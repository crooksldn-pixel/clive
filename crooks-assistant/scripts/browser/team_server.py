#!/usr/bin/env python3
"""The team's screen, served for a real browser: CLIVE with two members of the team let in, a day's
work to do, and a stand-in for their assistant, so scripts/browser/team.js can look at /today as a
member of the team on a phone and on the shared tablet, and as the owner.

    python scripts/browser/team_server.py --port 8791 --state /tmp/somewhere

Nothing here reaches Shopify, Gmail, Instagram, ElevenLabs or Claude. The app is the real one, with
its real door: a request carrying Tailscale's headers for mia@example.com is Mia, as the door lets her
in once the owner has (Tailscale's own device check is off, as in the offline tests). A request with
no such headers is made on the server itself, which is the owner (CROOKS_LOCAL_OWNER).

What CLIVE finds (orders to pack, an email and an Instagram message waiting) is a fixed answer, and
the members' assistant is a script that does what the real one is told to do for the few sentences the
browser check sends: it asks the work list and the owner-only tools through the real gate, under the
member's own authority, so a refusal here is the real refusal. Its words are fixtures, said as such.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

MIA = "mia@example.com"
KIT = "kit@example.com"
OWNER = "owner@example.com"


def _environment(state: Path) -> None:
    for name, value in {
        "CROOKS_ENV_FILE": "", "CROOKS_LOG_DIR": str(state / "logs"), "CROOKS_BENCH_AUDIO_DIR": str(state / "bench"),
        "CROOKS_SAVE_CAPTURES": "false", "CROOKS_ANALYTICS_WARM_DAYS": "0", "CROOKS_SECRET_DIR": str(state / "secrets"),
        "CROOKS_OBJECTIVES_DIR": str(state / "objectives"), "CROOKS_REPORTS_DIR": str(state / "reports"),
        "CROOKS_ALLOWED_LOGINS": OWNER, "CROOKS_LOCAL_OWNER": "true", "CROOKS_TAILSCALE_VERIFY": "false",
        "CROOKS_WRITES_ENABLED": "false",
    }.items():
        os.environ[name] = value


def _found() -> dict:
    """What CLIVE finds on a working morning, as app/work/found.py shapes it."""
    orders = [
        ("5001", "#2106", "Jane Okafor", "placed 2 hours ago; Royal Mail Tracked 48",
         [("Loopback Hoodie (M)", "LH-M", 1), ("Getaway Tee (L)", "GT-L", 1)], False),
        ("5002", "#2107", "Sam Reyes", "placed 1 hour ago; Royal Mail Tracked 24; label already printed",
         [("Cuffs Cap", "CC-OS", 1)], True),
        ("5003", "#2109", "Priya Shah", "placed 20 minutes ago; Royal Mail Tracked 48",
         [("Getaway Tee (S)", "GT-S", 2), ("Loopback Hoodie (L)", "LH-L", 1)], False),
    ]
    items = []
    for gid, name, who, details, lines, labelled in orders:
        count = sum(q for _, _, q in lines)
        items.append({"ref": f"order:gid://shopify/Order/{gid}", "kind": "pack_order", "order_number": name,
                      "title": f"Pack {name}: {count} item{'s' if count != 1 else ''} for {who}", "details": details,
                      "lines": [{"item": i, "sku": s, "quantity": q} for i, s, q in lines], "since": "2026-10-02T08:00:00Z",
                      "partly": False, "labelled": labelled})
    emails = [{"ref": "email:18f2a9c0d1", "kind": "reply_email", "title": "Reply to Tom Briggs: Where is my order #2098?",
               "details": "waiting 3 hours; 2 orders; the latest, #2098, is fulfilled",
               "snippet": "Hi, it said dispatched on Monday but nothing has turned up yet. Can you check?",
               "from_email": "tom@example.net", "since": 1759390000000}]
    instagram = [{"ref": "instagram:ig_77120", "kind": "reply_instagram", "title": "Instagram: @lenaxmoves is waiting",
                  "details": "waiting 40 minutes", "snippet": "do you restock the black hoodie in small?",
                  "since": "2026-10-02T09:20:00+0000"}]
    return {"orders": {"available": True, "items": items}, "emails": {"available": True, "items": emails},
            "instagram": {"available": True, "items": instagram}}


OWNERS = re.compile(r"\b(refund|discount|cancel|money back|price|settings|connections)\b", re.I)


def _script(runtime):
    """The members' assistant for the browser check. For an owner-only ask it does what the team's
    prompt tells the real one to: tries nothing it may not, notes it for George on the work list, and
    says so. Anything else gets one fixed line, said as a fixture."""
    from app.providers.base import TurnResult
    from app.tools.dispatch import dispatch

    class Scripted:
        async def start(self): pass
        async def stop(self): pass
        async def health(self): return True, "harness"
        async def reset_session(self, session_id): pass
        async def set_system_prompt(self, prompt): pass
        async def interrupt(self, session_id): return True

        async def turn(self, session_id, text):
            session = runtime.sessions.get_or_create(session_id)
            # The turn route puts the time on the first line and the person's words on the second.
            words = (str(text or "").splitlines() + ["", ""])[1]
            if OWNERS.search(words):
                # The gate's own answer to the refund, under this member's authority: refused.
                refused = await dispatch("shopify_refund_create", {"order_id": "gid://shopify/Order/5001"},
                                         session=session, timeout_s=5)
                assert refused.startswith("REFUSED"), refused
                await dispatch("work_note", {"action": "flag", "title": f"Refund asked for: {words[:80]}",
                                             "details": "Asked by the team through CLIVE."}, session=session, timeout_s=5)
                return TurnResult(text="That's George's to do; I've told him.", session_id=session_id)
            return TurnResult(text="(harness) CLIVE would answer this from the work list and the shop.",
                              session_id=session_id)

    return Scripted()


def seed(runtime, state: Path, patch=setattr) -> None:
    """The team's world on this runtime: Mia and Kit let in, Henry to suggest, a count handed to Mia,
    a job for anyone, a daily routine, what CLIVE finds, and the members' scripted assistant. `patch`
    sets a module's attribute (pytest's monkeypatch.setattr, so a test puts it back)."""
    from app.people import access
    from app.people.store import people
    from app.work import found as live
    from app.work.store import work

    people.configure(state / "people.json")
    access.configure(state_dir=state / "secret")
    work.configure(state / "work")
    people.note({"name": "Mia", "kind": "staff", "role": "packing, emails and Instagram", "login": MIA})
    people.note({"name": "Kit", "kind": "staff", "role": "packing and the stock counts", "login": KIT})
    people.note({"name": "Henry", "kind": "contact", "role": "graphic design: posters and post designs",
                 "uses": "posters"})
    for person, login in (("mia", MIA), ("kit", KIT)):
        access.ask(person, login)
        access.approve(person, login=login, by="owner", passkey="harness")
    work.assign(title="Count the hoodies on the back rail", kind="stock_count", assignee="mia", by="owner")
    work.assign(title="Restock the tee shelf", details="Blacks first, then the whites", by="owner")
    work.add_routine(title="Tidy the packing bench", cadence="daily", by="owner")
    # #2107's label was bought, so Shopify calls it fulfilled, and Kit packed it and marked it done: it is
    # finished here, and is never offered a Fulfil as if it were waiting for its tracking.
    labelled = work.claim_found(ref="order:gid://shopify/Order/5002", kind="pack_order",
                                title="Pack #2107: 1 item for Sam Reyes", details="", who="kit")
    work.packed(labelled.item_id, who="kit")
    work.done(labelled.item_id, who="kit")
    answers = _found()

    async def found(_runtime, *, fresh=False):
        return answers

    patch(live, "found", found)
    runtime.staff_provider_factory = lambda person: _script(runtime)
    runtime.staff_providers.clear()


async def _serve(port: int, state: Path) -> None:
    import uvicorn

    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.main import app
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("the harness never starts the real Claude")

    async def healthy(self):
        return True, "harness"

    max_agent_sdk.MaxAgentSDKProvider.start = no_start
    ScribeClient.health = healthy
    VoiceClient.health = lambda self: (True, "harness")
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        seed(runtime, state)
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="off", log_level="warning",
                                               proxy_headers=False))
        print(f"team harness on http://127.0.0.1:{port}", flush=True)
        await server.serve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--state", default="")
    args = parser.parse_args()
    state = Path(args.state or tempfile.mkdtemp(prefix="crooks-team-"))
    state.mkdir(parents=True, exist_ok=True)
    _environment(state)
    os.chdir(ROOT)
    asyncio.run(_serve(args.port, state))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
