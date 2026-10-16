"""Run Returns locally for browser checks (Playwright), with no Shopify and no secrets.

    cd crooks-returns && python scripts/dev_server.py [PORT]      # default 8114

    http://127.0.0.1:8114/                       the customer portal (the theme section)
    http://127.0.0.1:8114/apps/returns/admin     the staff screen (admin auth skipped)

The store is the built-in fixture (order #1939, proof E1 6AN or customer@example.com) and
labels are test labels with drop-off points and a QR code, so nothing real is booked. Emails
are kept, never sent: the last one is at /apps/returns/dev/emails. Two returns are seeded, one waiting for a
decision and one approved, so the list and detail screens have something to show. The data
lives in a throwaway SQLite file and is rebuilt on every start.

App Bridge and Polaris load from cdn.shopify.com; outside Shopify admin App Bridge has no host
to talk to, so expect its console warnings, not app errors.
"""

from __future__ import annotations

import base64
import html
import os
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parent
REPO = APP.parent
sys.path.insert(0, str(APP))
os.environ.setdefault("RETURNS_ENV_FILE", "")

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from returns.app import build_service, create_app  # noqa: E402
from returns.fake import FakeLabels  # noqa: E402
from returns.mailer import RecordingMailer  # noqa: E402
from returns.models import Postage, Reason, Resolution, Selection  # noqa: E402
from returns.settings import Settings  # noqa: E402

TEE = "gid://shopify/FulfillmentLineItem/1"
JEANS = "gid://shopify/FulfillmentLineItem/2"


def settings(port: int) -> Settings:
    db = Path(tempfile.mkdtemp(prefix="returns-dev-")) / "dev.sqlite3"
    return Settings(
        shopify_backend="fake",
        label_provider="none",
        dev_skip_proxy_signature=True,
        dev_skip_admin_auth=True,
        db_path=str(db),
        session_secret="dev-only",
        public_base_url=f"http://127.0.0.1:{port}/apps/returns",
        tick_interval_s=0,
        returns_address_line1="Unit M",
        returns_address_line2="Bourne End Business Park",
        returns_address_city="Bourne End, Buckinghamshire",
        returns_address_postcode="SL8 5AS",
        returns_contact_email="team@example.com",
    )


def seed(svc) -> None:
    order = svc.shopify.get_order("gid://shopify/Order/1939")
    svc.submit(
        order,
        [Selection(fulfillment_line_item_id=TEE, quantity=1, reason=Reason.too_small)],
        Resolution.refund,
        Postage.self_ship,
    )
    approved = svc.submit(
        order,
        [Selection(fulfillment_line_item_id=JEANS, quantity=1, reason=Reason.changed_mind)],
        Resolution.store_credit,
        Postage.self_ship,
    )
    svc.execute(approved.id, "approve", {"postage_mode": "self_ship"}, "dev", "seed-approve")


def portal_page() -> str:
    section = (REPO / "sections" / "returns-portal.liquid").read_text()
    found = re.search(r"{% stylesheet %}(.*){% endstylesheet %}", section, re.S)
    css = found.group(1) if found else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Returns (dev)</title>
<style>body{{margin:0;background:#0a0a0a}}{css}</style>
<script src="/assets/returns-portal.js" defer></script></head><body>
<section class="returns-desk"><div class="returns-desk__inner">
<returns-portal class="rd-app" data-endpoint="/apps/returns/proxy/api" data-contact="/">
</returns-portal></div></section></body></html>"""


def build(port: int) -> FastAPI:
    s = settings(port)
    svc = build_service(s)
    svc.labels = FakeLabels(drop_off=True)  # drop-off points and a QR code, as Parcel2Go
    outbox = RecordingMailer()
    svc.mailer = outbox  # kept, never sent
    seed(svc)
    root = FastAPI()
    root.mount("/assets", StaticFiles(directory=str(REPO / "assets")), name="assets")

    @root.get("/", response_class=HTMLResponse)
    def index() -> str:
        return portal_page()

    @root.get("/apps/returns/dev/emails", response_class=HTMLResponse)
    def emails() -> str:
        sent = outbox.sent
        if not sent:
            return "<p>No email yet.</p>"
        last = sent[-1]
        page = last["html"]
        for f in last["files"]:
            if f.get("content_id"):
                data = base64.b64encode(f["content"]).decode()
                page = page.replace(f"cid:{f['content_id']}", f"data:image/png;base64,{data}")
        names = ", ".join(a["filename"] for a in last["attachments"])
        return (
            f"<p style='font:13px sans-serif;color:#666'>To {html.escape(last['to'])} · "
            f"{html.escape(last['subject'])} · attached: {html.escape(names)}</p><hr>{page}"
        )

    root.mount("/apps/returns", create_app(s, svc))
    return root


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8114
    uvicorn.run(build(port), host="127.0.0.1", port=port, log_level="warning")
