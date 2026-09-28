"""D-2 of the live session: a pending Undo counted as "changes still waiting".

At 00:24:53 the tablet said *"Merged. 2 changes still waiting over there."* The two were
`gmail_draft_reply_undo` and `gmail_thread_archive_undo` — undo offers for changes that had
already been made and proven. Nothing was waiting.

An undo is a property of a completed action, not a queued one. These tests hold the
separation everywhere a count is made: the branch summary the merge toast reads, the states
the tablet reconciles against, the turn's own record of what was waiting when it started —
and they hold that an offer nobody took up expires on its own clock and can be let go.
"""

from __future__ import annotations

import httpx
import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine, undoable_ids, waiting_ids
from app.actions.ledger import NullLedger
from app.actions.models import PROPOSAL_TTL_S, UNDO_TTL_S, ActionStatus
from app.main import app
from app.routes import branches as branch_routes
from app.session.manager import SessionManager
from app.session.models import Session
from app.tools import gmail_writes, shopify_tools
from app.tools.dispatch import dispatch
from tests.test_actions import ORDER, TOOL, FakeStore
from tests.test_actions_routes import PROXIED, FakeProvider, configure
from tests.test_gmail_writes import (
    BODY,
    CUSTOMER_ID,
    THREAD,
    FakeGmail,
    Policy,
    customer_of,
    stage,
    tap,
)

# The admitted owner calling tools directly, as a request the door let through would: every tool
# call here is his (the 2026-09-27 deploy review, round 8, F-A2-FIXTURE). Production's default,
# and every test's that does not say this, is no authority at all.
pytestmark = pytest.mark.usefixtures("owner_asking")

OWNER = "owner@example.com"


# The inbox, the engine and the conversation the email tests use, built here so that this
# file's names are its own (see tests/test_gmail_writes.py for the world they describe).
@pytest.fixture()
def box():
    inbox = FakeGmail()
    gmail_writes.bind(inbox, customer=customer_of, policy=lambda: Policy())
    yield inbox
    gmail_writes.bind(None)


@pytest.fixture()
def engine(monkeypatch):
    made = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", made)
    monkeypatch.setattr(gmail_writes, "SETTLE_POLL_S", 0.0)
    monkeypatch.setattr(gmail_writes, "SETTLE_S", 0.5)
    return made


@pytest.fixture()
def session():
    conversation = Session(session_id="c1")
    conversation.issue(ORDER, THREAD, CUSTOMER_ID)
    conversation.epoch = 1
    return conversation


async def archived_with_an_undo(box, engine, session):
    """Archive the thread, prove it, and take the undo the Mac then staged."""
    _, proposal = await stage(session, "gmail_thread_archive", thread_id=THREAD)
    result = await tap(engine, proposal)
    assert result.code == "verified"
    undo = engine.find(proposal.undo_id)
    assert undo is not None and undo.status is ActionStatus.PENDING and undo.undo_of == proposal.proposal_id
    return proposal, undo


# --------------------------------------------------------------- the counts, one by one


async def test_an_archive_leaves_an_undo_and_nothing_waiting(box, engine, session):
    done, undo = await archived_with_an_undo(box, engine, session)
    branch_id = str(done.branch_id or "")
    assert waiting_ids(session) == [], "the change is done; nothing is waiting for a gesture"
    assert undoable_ids(session) == [undo.proposal_id]
    # And the branch summary the merge toast reads says the same.
    assert branch_routes._waiting(session, branch_id) == []
    assert branch_routes._undoable(session, branch_id) == [undo.proposal_id]


async def test_a_change_that_is_waiting_is_still_counted(box, engine, session):
    _, waiting = await stage(session, "gmail_thread_archive", thread_id=THREAD)
    assert waiting_ids(session) == [waiting.proposal_id]
    assert undoable_ids(session) == []


async def test_a_proposal_nobody_looked_at_is_not_waiting_once_it_has_expired(box, engine, session):
    """A proposal expires on the Mac's clock, not when someone next asks about it. The live
    session's toast counted an undo staged three minutes earlier."""
    _, waiting = await stage(session, "gmail_thread_archive", thread_id=THREAD)
    waiting.expires_at = 0.0
    assert waiting.status is ActionStatus.PENDING, "nothing has looked at it yet"
    assert waiting_ids(session) == []
    assert branch_routes._waiting(session, str(waiting.branch_id or "")) == []


async def test_the_undo_has_its_own_clock(box, engine, session):
    done, undo = await archived_with_an_undo(box, engine, session)
    assert UNDO_TTL_S > PROPOSAL_TTL_S, "an offer to put something back outlives a card waiting for a tap"
    assert round(undo.expires_at - undo.created_at) == round(UNDO_TTL_S)
    assert round(done.expires_at - done.created_at) == round(PROPOSAL_TTL_S)


async def test_an_undo_can_be_let_go_without_withdrawing_anything_else(box, engine, session):
    done, undo = await archived_with_an_undo(box, engine, session)
    # And a real change waiting beside it, to prove the one does not take the other.
    _, waiting = await stage(session, "gmail_draft_reply", thread_id=THREAD, body=BODY)
    assert engine.dismiss_undo(undo.proposal_id) is True
    assert undo.status is ActionStatus.EXPIRED and undo.code == "expired" and undo.reason == "the offer was let go"
    assert undoable_ids(session) == []
    assert waiting_ids(session) == [waiting.proposal_id], "letting an offer go withdraws nothing else"
    # Only an offer, and only once.
    assert engine.dismiss_undo(undo.proposal_id) is False
    assert engine.dismiss_undo(waiting.proposal_id) is False
    assert waiting.status is ActionStatus.PENDING


async def test_a_half_holding_only_an_undo_offer_can_be_put_aside(box, engine, session):
    """`/branches/{id}/background` refuses a half with a change waiting. An offer to undo
    something already done is not a change waiting."""
    done, _undo = await archived_with_an_undo(box, engine, session)
    assert branch_routes._waiting(session, str(done.branch_id or "")) == []


# --------------------------------------------------------------- through the routes


@pytest.fixture()
async def client(monkeypatch):
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))

    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = FakeProvider()
        store = FakeStore(note="Gift wrap please")
        runtime.shopify = store
        shopify_tools.bind(store)
        runtime.actions = ActionEngine(ledger=NullLedger())
        monkeypatch.setattr(engine_module, "_engine", runtime.actions)
        runtime.sessions = SessionManager()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.store = store
            c.runtime = runtime
            yield c


async def note_applied(client, session_id="s1"):
    """A note added and proven through the routes, with the undo the Mac then offers."""
    configure(client, writes=True)
    conversation = client.runtime.sessions.get_or_create(session_id)
    conversation.issue(ORDER)
    conversation.epoch = max(conversation.epoch, 1)
    conversation.branch()
    text = await dispatch(TOOL, {"order_id": ORDER, "note": "Customer asked for an exchange"}, session=conversation, timeout_s=5)
    assert text.startswith("PROPOSED")
    proposal = conversation.proposals[-1]
    answer = await client.post(f"/actions/{proposal.proposal_id}/commit", data={"session_id": session_id}, headers=PROXIED)
    assert answer.status_code == 200 and answer.json()["status"] == "verified"
    undo = conversation.proposal(proposal.undo_id)
    assert undo is not None
    return conversation, proposal, undo


async def test_the_states_route_separates_what_is_waiting_from_what_can_be_undone(client):
    conversation, done, undo = await note_applied(client)
    ids = ",".join([done.proposal_id, undo.proposal_id])
    answer = await client.get(f"/actions/states?session_id=s1&ids={ids}", headers=PROXIED)
    body = answer.json()
    assert answer.status_code == 200
    assert body["pending"] == [], "the change is finished"
    assert body["undoable"] == [undo.proposal_id]
    assert body["states"][undo.proposal_id]["undo_of"] == done.proposal_id
    assert body["states"][done.proposal_id]["status"] == "verified"


async def test_a_merge_says_nothing_is_waiting_when_all_that_is_left_is_an_undo(client):
    conversation, _done, undo = await note_applied(client)
    forked = await client.post("/branches/fork", data={"session_id": "s1"}, headers=PROXIED)
    assert forked.status_code == 200
    other = [b["branch_id"] for b in forked.json()["branches"] if b["branch_id"] != forked.json()["focused"]]
    # The undo belongs to the half the change was made in; merge that half into the other.
    merging = str(undo.branch_id or "")
    if merging == forked.json()["focused"]:
        await client.post(f"/branches/{other[0]}/focus", data={"session_id": "s1"}, headers=PROXIED)
    answer = await client.post(f"/branches/{merging}/merge", data={"session_id": "s1"}, headers=PROXIED)
    assert answer.status_code == 200, answer.text
    merged = answer.json()["merged"]
    assert merged["still_waiting"] == [], "nothing was waiting: it was an offer to undo something done"
    assert merged["undoable"] == [undo.proposal_id]


async def test_the_watchdog_and_the_dismissal_reach_the_record_with_their_fields(client):
    """D-1's other half: the tablet's telemetry recorded the stuck card once a turn for six
    turns and nobody read it. The watchdog's event says plainly what it corrected — which
    state the surface was in, what the Mac said, which proposal — and the route must carry
    all of it rather than dropping the fields on the floor."""
    from pathlib import Path

    from app.observability.timeline import read_events
    from tests.test_actions_routes import as_owner

    as_owner(client.runtime)   # the test session is the owner's to start (F-05A)
    await client.post("/test-session/start", json={"name": "watchdog"})
    conversation, _done, undo = await note_applied(client)
    assert conversation is not None
    posted = await client.post("/telemetry", json={"session_id": "s1", "events": [
        {"kind": "action_watchdog", "proposal_id": "prop_stuck", "before": "EXECUTING", "after": "VERIFIED", "status": "verified", "reason": "turn"},
        {"kind": "undo_dismissed", "proposal_id": undo.proposal_id, "reason": "expired"},
    ]}, headers=PROXIED)
    assert posted.status_code == 204 and posted.headers["x-crooks-telemetry"] == "2"
    stopped = (await client.post("/test-session/stop", headers=PROXIED)).json()   # from his device
    client.runtime.timeline.flush()
    events = read_events(Path(stopped["path"]))
    watchdog = next(e for e in events if e["kind"] == "tablet_action_watchdog")
    assert watchdog["proposal_id"] == "prop_stuck" and watchdog["before"] == "EXECUTING"
    assert watchdog["after"] == "VERIFIED" and watchdog["status"] == "verified" and watchdog["reason"] == "turn"
    assert any(e["kind"] == "tablet_undo_dismissed" for e in events)


async def test_an_undo_offer_can_be_let_go_through_the_route(client):
    conversation, done, undo = await note_applied(client)
    answer = await client.post(f"/actions/{undo.proposal_id}/dismiss", data={"session_id": "s1"}, headers=PROXIED)
    assert answer.status_code == 200 and answer.json()["status"] == "expired"
    assert undo.status is ActionStatus.EXPIRED
    # The change itself is not an offer, and the route will not touch it.
    refused = await client.post(f"/actions/{done.proposal_id}/dismiss", data={"session_id": "s1"}, headers=PROXIED)
    assert refused.status_code == 409 and refused.json()["code"] == "not_an_undo"
