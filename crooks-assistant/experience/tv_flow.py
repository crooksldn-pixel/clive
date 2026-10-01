"""The screen page's visual flow, measured in a real browser at 1920 x 1080 (round 12).

The owner, 29 September: "i can ask to put xyz on screen, if i ask for something new, it reverts
to home screen for a second then reverts to the new screen. why is the home animation happening
it just adds delays and makes things clunky." That is a claim about pixels and about time, so this
is a measurement of both: the real backend (experience/browser.py serve_fixture_world), a real
Chromium opening /display as a TV does, naming itself and being approved with the code it shows,
and then, one after another, the things he asks for put on it through the display store —
exactly what CLIVE's screen tools call (app/tools/display_tools.py screen_show, screen_off).

`scripts/browser/tv_flow.js` drives the page and asks this process, a line at a time on its
standard output, to approve the screen or put something on it; each answer goes back on its
standard input. The script reports, per change: how long from the page receiving the new answer
to the new thing being readable, and whether any frame in between showed the clock (the screen's
home) or nothing at all.

The orders, objective, list and video are invented; nothing here is the owner's business.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from experience import browser

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "browser" / "tv_flow.js"


def _order(number: str, customer: str, street: str, town: str, postcode: str, items: list[tuple[str, str, str, int]],
           note: str | None = None) -> dict[str, Any]:
    from app.displays import views

    return views.order_view({
        "order_id": f"gid://shopify/Order/{number}", "order_number": f"#{number}", "customer_name": customer,
        "placed_at": "2026-09-29T09:12:00Z", "payment": "PAID", "note": note, "tags": [],
        "shipping_address": {"name": customer, "lines": [street], "city": town, "zip": postcode, "country": "United Kingdom"},
        "items": [{"title": title, "variant": variant, "sku": sku, "quantity": n, "unfulfilled_quantity": n}
                  for title, variant, sku, n in items],
    })


def _views() -> dict[str, dict[str, Any]]:
    """What the owner asks for in the walk: two orders, an objective, a list, a video, a third
    order. Invented, and each with a title the page can be looked for by."""
    from app.displays import views

    return {
        "order-a": _order("2041", "Jonah Reyes", "12 Elm Row", "Leeds", "LS6 2AB",
                          [("Heavyweight Tee", "Black / L", "HW-TEE-BL-L", 2), ("Canvas Tote", "Natural", "CV-TOTE", 1)]),
        "order-b": _order("2042", "Mina Okafor", "7 Harbour Lane", "Bristol", "BS1 4QD",
                          [("Loopback Hoodie", "Grey / M", "LB-HD-GR-M", 1), ("Logo Cap", "Navy", "CAP-NV", 1),
                           ("Rib Socks", "White", "SK-WH", 3)], note="Gift, please leave out the receipt."),
        "objective": views.objective_view(
            {"id": "obj_walk", "title": "Autumn samples", "deadline": "2026-10-10", "days_left": 11,
             "doing": "Fitting the second hoodie sample", "needs_you": ["Choose the rib colour"],
             "next": ["Photograph the tee samples", "Send the fit notes to the factory"]}, []),
        "list": views.list_view("Studio jobs", ["Steam the hoodies", "Restock the mailers", "Book the courier"]),
        "video": views.video_view("dQw4w9WgXcQ", title="Studio playlist", channel="A channel", duration_s=213),
        "order-c": _order("2043", "Theo Marsh", "3 Mill Street", "York", "YO1 7HH",
                          [("Coach Jacket", "Olive / S", "CJ-OL-S", 1)]),
        "beside": views.list_view("Packing today", ["Order #2043", "Order #2044"]),
    }


def _act(msg: dict[str, Any], views_: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """One thing the script asked for, done as CLIVE's screen tools do it."""
    from app.displays.store import store

    s = store()
    what = msg.get("do")
    if what == "approve":
        return s.approve(str(msg["name"]), str(msg["code"]))
    screen = s.find(str(msg["name"]), exact=True)
    if what == "show":
        replace = msg.get("replace")
        shown = s.show(screen["id"], views_[str(msg["view"])], beside=bool(msg.get("beside")),
                       replace=replace if isinstance(replace, int) else None)
        return {"version": shown.get("version")}
    if what == "off":
        pane = msg.get("pane")
        out = s.take_off(screen["id"], pane if isinstance(pane, int) else None)
        return {"version": out.get("version"), "taken_off": out.get("taken_off")}
    raise ValueError(f"unknown step {what!r}")


# The changes the script walks through, by mode: the names of `WALK.full` and `WALK.short` in
# scripts/browser/tv_flow.js, held here so that the report is checked against what was asked
# for rather than against whatever it happens to contain (tests/test_followups_harness.py holds
# the two lists to each other).
FULL_WALK = ("first", "order-to-order", "order-to-objective", "objective-to-list", "list-to-video",
             "beside-the-video", "video-to-order", "two-to-one", "off")
SHORT_WALK = ("first", "order-to-order", "order-to-video", "video-to-order", "off")
WALKS = {"full": FULL_WALK, "portrait": FULL_WALK, "weak": SHORT_WALK, "calm": SHORT_WALK}


def judged(payload: dict[str, Any], *, modes: str, returncode: int | None) -> dict[str, Any]:
    """The script's report, with `ok` false and the reasons added to its `errors` when the driver
    did not exit cleanly or did not measure every change of every mode it was asked for.

    Its own last line used to be forwarded as it came (the 2026-09-30 deploy review, X2-01): a
    driver that crashed after printing, or a report with a mode or a change missing, read as a
    pass to anyone who looked only at `ok`."""
    out = dict(payload)
    why: list[str] = []
    if returncode != 0:
        why.append(f"the driver exited with status {returncode}")
    results = [r for r in out.get("results") or [] if isinstance(r, dict)]
    for mode in [m for m in modes.split(",") if m]:
        walk = WALKS.get(mode)
        if walk is None:
            why.append(f"{mode}: no walk is known for this mode")
            continue
        seen = {str(r.get("step")) for r in results if r.get("mode") == mode}
        if not seen:
            why.append(f"{mode}: no change was measured")
            continue
        missing = [step for step in walk if step not in seen]
        if missing:
            why.append(f"{mode}: no result for {', '.join(missing)}")
    if why:
        out["ok"] = False
        out["errors"] = [*(out.get("errors") or []), *why]
    return out


async def drive(argv: list[str], *, modes: str, views_: dict[str, dict[str, Any]] | None = None,
                env: dict[str, str] | None = None) -> dict[str, Any]:
    """Run the driver, do what it asks a line at a time, and judge the report it ends with."""
    proc = await asyncio.create_subprocess_exec(
        *argv, cwd=ROOT, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, env=env if env is not None else dict(os.environ),
    )
    try:
        payload: dict[str, Any] = {}
        while True:
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=240)
            if not raw:
                break
            try:
                msg = json.loads(raw.decode("utf-8"))
            except ValueError:
                continue
            if isinstance(msg, dict) and "do" in msg:
                try:
                    answer = {"ok": True, **_act(msg, views_ or {})}
                except Exception as exc:  # noqa: BLE001 — the script is told, and reports it
                    answer = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                proc.stdin.write((json.dumps(answer) + "\n").encode("utf-8"))
                await proc.stdin.drain()
            elif isinstance(msg, dict):
                payload = msg
        proc.stdin.close()
        # To the end of both streams, so the process and its pipes are closed inside this loop.
        _, err = await proc.communicate()
        if not payload:
            payload = {"ok": False, "error": err.decode("utf-8", "replace")[-1200:]}
        return judged(payload, modes=modes, returncode=proc.returncode)
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.communicate()


async def run(*, out: Path | None = None, modes: str = "full,weak,calm") -> dict[str, Any]:
    """Serve the fixture world, drive the screen page through the walk in each mode (`full`: a
    TV with the dots; `weak`: the lighter engine a small device gets; `calm`: reduced motion) and
    return the script's own report, judged (`judged`): per change, the time to readable and what
    each frame showed."""
    ok, why = browser.available()
    if not ok:
        return {"skipped": True, "why": why}
    if out is not None:
        out.mkdir(parents=True, exist_ok=True)
    port = browser._free_port()
    server, task, _world = await browser.serve_fixture_world(port)
    # The walk's screens in a record of their own, so a screen named by an earlier run, or by
    # another test in the same session, is never in the way.
    from app.displays import store as displays_module

    displays_module.install(Path(tempfile.mkdtemp(prefix="crooks-tv-flow-")) / "displays.json")
    try:
        return await drive(["node", str(SCRIPT), f"http://127.0.0.1:{port}", str(out or ""), modes],
                           modes=modes, views_=_views(), env={**os.environ, "CROOKS_CHROMIUM": browser.CHROMIUM})
    finally:
        await browser._stop(server, task)


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1] else None
    which = sys.argv[2] if len(sys.argv) > 2 else "full,weak,calm"
    print(json.dumps(asyncio.run(run(out=target, modes=which)), indent=1))
