#!/usr/bin/env python3
"""Investigate one customer enquiry about an existing order, read-only, from the command line.

    python scripts/support_investigate.py --text "Where is my order 2101?" --sender sam@example.com
    python scripts/support_investigate.py --file enquiry.txt --subject "Order 2101" --capture case.json
    python scripts/support_investigate.py --bundle case.json --out report.md

Live mode (the first two forms) engages the process-wide read-only latch before it builds a
client, so no Shopify mutation and no Gmail change can be executed by this process however
it is driven; it then reads the store, the inbox and the knowledge base through the
application's own read tools. `--capture` saves the evidence bundle as read, which contains
customer data and belongs on the owner's machine only; `--redacted-capture` saves the copy
with the person removed, which is what an engineering record may hold. `--bundle` replays a
saved bundle without reading anything.

The output is the internal summary (Markdown) with the reply draft inside it. The draft is
text: it has not been sent, and nothing here can send it.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import readonly  # noqa: E402
from app.support import EvidenceBundle, investigate_bundle, parse_enquiry  # noqa: E402
from app.support.evidence import gather  # noqa: E402
from app.support.redact import redact_bundle  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Investigate one customer enquiry, read-only.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text", help="the customer's message")
    source.add_argument("--file", type=Path, help="a file holding the customer's message")
    source.add_argument("--bundle", type=Path, help="replay a saved evidence bundle (no reads)")
    parser.add_argument("--subject", default="", help="the email subject, if it came by email")
    parser.add_argument("--sender", default="", help="the address it came from, if known")
    parser.add_argument("--kb-dir", type=Path, default=None, help="the knowledge base directory (default: the application's)")
    parser.add_argument("--capture", type=Path, default=None, help="save the evidence bundle as read (contains customer data)")
    parser.add_argument("--redacted-capture", type=Path, default=None, help="save the redacted evidence bundle")
    parser.add_argument("--out", type=Path, default=None, help="write the Markdown summary here instead of stdout")
    parser.add_argument("--json", action="store_true", help="print the whole result as JSON instead of Markdown")
    parser.add_argument("--signature", default="", help="the sign-off on the draft (default: the configured one)")
    return parser


async def run(args: argparse.Namespace) -> int:
    from config.settings import get_settings

    settings = get_settings()
    signature = args.signature or str(getattr(settings, "gmail_signature", "") or "CROOKS")
    shopify = None
    try:
        if args.bundle is not None:
            bundle = EvidenceBundle.from_dict(json.loads(args.bundle.read_text(encoding="utf-8")))
            mode = "replay"
        else:
            text = args.text if args.text is not None else args.file.read_text(encoding="utf-8")
            if not text.strip():
                print("The customer's message is empty.", file=sys.stderr)
                return 2
            # The latch first, the clients second: a process that has read-only mode engaged
            # before it holds a client cannot have made a change before the latch came down.
            readonly.engage("support investigator CLI: read-only by construction")
            from app.clients.gmail import GmailClient
            from app.clients.shopify import ShopifyClient
            from app.support.live import readers
            from app.tools import gmail_tools, shopify_tools

            shopify = ShopifyClient(settings.shopify_shop_domain, settings.shopify_api_version, auth_mode=settings.shopify_auth_mode)
            shopify_tools.bind(shopify)
            gmail_tools.bind(GmailClient())
            enquiry = parse_enquiry(text, subject=args.subject, sender_email=args.sender)
            bundle = await gather(enquiry, **readers(settings, kb_dir=args.kb_dir))
            mode = "live"
        result = investigate_bundle(bundle, signature=signature)
        result["mode"] = mode
        result["read_only"] = True
        if args.capture is not None:
            args.capture.write_text(json.dumps(bundle.to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"evidence bundle saved to {args.capture} (contains customer data; keep it on this machine)", file=sys.stderr)
        if args.redacted_capture is not None:
            args.redacted_capture.write_text(json.dumps(redact_bundle(bundle).to_dict(), indent=1, ensure_ascii=False), encoding="utf-8")
            print(f"redacted evidence bundle saved to {args.redacted_capture}", file=sys.stderr)
        rendered = json.dumps(result, indent=1, ensure_ascii=False) if args.json else result["markdown"]
        if args.out is not None:
            args.out.write_text(rendered, encoding="utf-8")
            print(f"written to {args.out}", file=sys.stderr)
        else:
            print(rendered)
        return 0
    finally:
        if shopify is not None:
            await shopify.aclose()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
