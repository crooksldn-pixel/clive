#!/usr/bin/env python3
"""crooks-status — is CROOKS OS up, and what is it running?

One screen, no arguments:

    Build      the page files the tablet is being served
    Voice      the speech recogniser and the voice
    Claude     the provider, and how it is authenticated
    Shopify    the store, and how fresh the order cache is
    Gmail      the inbox
    Orders     what the read layer is answering from
    Tablet     the HTTPS address to open
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

OK, BAD, MEH = "ok  ", "DOWN", "--  "


def _line(state: str, name: str, detail: str) -> str:
    return f"  {state}  {name:<9} {detail}"


def show(port: int, out=None) -> int:
    import launch_common as lc

    # Read at call time, not bound when the module was imported: a stream swapped since (a test's
    # capture, a redirected stdout) is the one written to.
    out = out if out is not None else sys.stdout

    health = lc.fetch_health(f"http://127.0.0.1:{port}/health")
    if not health:
        print(_line(BAD, "Backend", f"nothing answering on 127.0.0.1:{port}. `make status` says why; `make restart` brings the service back."), file=out)
        return 1
    if lc.health_limited(health):
        # Liveness alone (round 8, F-NEW-PAD): what it does not show is not known to be working.
        print(_line(MEH, "Backend", lc.summarise_health(health)), file=out)
        return 1
    raw = health.get("checks")
    # /health answers with a map of name -> {ok, detail}; older builds answered with a list.
    checks: dict[str, dict] = (
        {str(k): v for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict)
        else {str(c.get("name") or ""): c for c in (raw or []) if isinstance(c, dict)}
    )
    print(_line(OK, "Build", str(health.get("build") or "?")), file=out)
    for name, label in (("speech", "Voice"), ("tts", "Speaks"), ("claude", "Claude"),
                        ("shopify", "Shopify"), ("gmail", "Gmail")):
        check = checks.get(name)
        if check is None:
            continue
        print(_line(OK if check.get("ok") else BAD, label, str(check.get("detail") or "")[:100]), file=out)
    cache = health.get("orders_cache") if isinstance(health.get("orders_cache"), dict) else None
    if cache:
        held, age = cache.get("orders", 0), cache.get("age_s")
        print(_line(OK if held else MEH, "Orders", f"{held} held" + (f", read {age}s ago" if age is not None else "")), file=out)
    manifest = health.get("manifest") if isinstance(health.get("manifest"), dict) else None
    if manifest:
        print(_line(OK, "Can do", f"{manifest.get('reads', 0)} reads, {manifest.get('writes', 0)} changes, {manifest.get('batches', 0)} bulk  ({manifest.get('fingerprint', '')[:8]})"), file=out)
    writes = health.get("writes") if isinstance(health.get("writes"), dict) else None
    if writes:
        print(_line(OK if writes.get("state") == "ready" else MEH, "Changes", str(writes.get("detail") or writes.get("state") or "")[:100]), file=out)
    host, note = lc.serve_status(port)
    print(_line(OK if host else MEH, "Tablet", f"https://{host}/" if host else note), file=out)
    observed = health.get("observability") if isinstance(health.get("observability"), dict) else {}
    if observed.get("test_session"):
        print(_line(OK, "Session", f"{observed['test_session']} recording — crooks-watch to follow it"), file=out)
    # The verdict: the parts that make it usable. Tailscale and the order cache are shown
    # but do not make it "down" — the tablet's route can be off while the server is fine. An
    # essential the answer does not report is unknown, never working (round 9, E-01): an answer
    # without them — or without any checks — is not a well one.
    missing = [name for name in lc.ESSENTIAL if name not in checks]
    if missing:
        print(_line(MEH, "Unknown", "not reported: " + ", ".join(lc.PLAIN_NAMES.get(n, n) for n in missing)), file=out)
    return 0 if not missing and all(checks[name].get("ok") for name in lc.ESSENTIAL) else 1


def main(argv: list[str] | None = None) -> int:
    from config.settings import get_settings

    return show(get_settings().port)


if __name__ == "__main__":
    sys.exit(main())
