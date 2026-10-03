""""Not now" on a card waiting for the owner's approval (the design pass of 3 October).

The approval cards offered only the gesture that applies a change, so the owner's "no" looked the
same as walking away from the card (DEC-056; night/audit/DESIGN.md §5). The card now carries
"Not now", which posts the proposal's id and the session to /actions/{id}/decline (or the batch's
to /batches/{id}/decline), and the Mac withdraws it through its own withdrawal — the REVOKED a new
instruction makes — with the owner's reason on it.

What these hold: a decline withdraws a change that is waiting and applies nothing; a change it
withdrew can never be applied afterwards; it does not touch a change that has been applied, an
undo offer, or another login's conversation; and the body cannot carry anything else.
"""

from __future__ import annotations

import httpx
import pytest

from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.main import app
from app.routes.actions import DECLINED_BY_OWNER
from app.session.manager import SessionManager
from app.tools import shopify_tools
from app.tools.dispatch import dispatch
from tests.test_actions import FakeStore
from tests.test_actions_routes import PROXIED, FakeProvider, commit, configure, staged
from tests.test_batch import orders_set, store_of

pytestmark = pytest.mark.usefixtures("owner_asking")

OWNER = "owner@example.com"
STRANGER = {"Tailscale-User-Login": "stranger@example.com", "X-Forwarded-For": "100.64.0.2"}


async def _world(monkeypatch):
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


@pytest.fixture()
async def client(monkeypatch):
    await _world(monkeypatch)
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = FakeProvider()
        store = FakeStore(note="Gift wrap please")
        runtime.shopify = store
        shopify_tools.bind(store)
        runtime.actions.ledger = NullLedger()
        runtime.batches.ledger = NullLedger()
        runtime.sessions = SessionManager()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            c.store = store
            c.runtime = runtime
            configure(c, writes=True)
            yield c


async def decline(client, proposal_id, session_id="s1", headers=PROXIED, **extra):
    return await client.post(f"/actions/{proposal_id}/decline", data={"session_id": session_id, **extra}, headers=headers)


async def test_not_now_withdraws_a_waiting_change_and_applies_nothing(client):
    proposal = await staged(client)
    answer = await decline(client, proposal.proposal_id)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"proposal_id": proposal.proposal_id, "status": "revoked", "withdrawn": True}
    assert proposal.status is ActionStatus.REVOKED
    assert proposal.reason == DECLINED_BY_OWNER
    assert client.store.mutations == []


async def test_a_change_he_said_not_now_to_can_never_be_applied_afterwards(client):
    proposal = await staged(client)
    assert (await decline(client, proposal.proposal_id)).status_code == 200
    late = await commit(client, proposal.proposal_id)
    assert late.json().get("status") != "verified"
    assert client.store.mutations == [], "a withdrawn change is not applied by a gesture that comes after it"
    assert proposal.status is ActionStatus.REVOKED


async def test_a_change_already_applied_is_not_withdrawn(client):
    proposal = await staged(client)
    applied = await commit(client, proposal.proposal_id)
    assert applied.status_code == 200 and applied.json()["status"] == "verified"
    answer = await decline(client, proposal.proposal_id)
    assert answer.status_code == 409 and answer.json()["code"] == "not_waiting"
    assert proposal.status is ActionStatus.VERIFIED and len(client.store.mutations) == 1


async def test_an_undo_offer_is_not_a_change_waiting_for_him(client):
    proposal = await staged(client)
    assert (await commit(client, proposal.proposal_id)).json()["status"] == "verified"
    session = client.runtime.sessions.get_or_create("s1")
    undo = session.proposal(proposal.undo_id)
    assert undo is not None and undo.status is ActionStatus.PENDING
    answer = await decline(client, undo.proposal_id)
    assert answer.status_code == 409 and answer.json()["code"] == "an_undo"
    assert undo.status is ActionStatus.PENDING, "an offer to undo is let go by its own door, not this one"


async def test_only_his_conversation_and_only_a_proposal_it_holds(client):
    proposal = await staged(client)
    stranger = await decline(client, proposal.proposal_id, headers=STRANGER)
    assert stranger.status_code == 403
    missing = await client.post(f"/actions/{proposal.proposal_id}/decline", data={}, headers=PROXIED)
    assert missing.status_code == 400 and missing.json()["code"] == "wrong_session"
    elsewhere = await decline(client, proposal.proposal_id, session_id="s9")
    assert elsewhere.status_code == 404
    unknown = await decline(client, "prop_000000000000")
    assert unknown.status_code == 404
    assert proposal.status is ActionStatus.PENDING, "nothing above touched it"


async def test_the_body_carries_the_session_and_nothing_else(client):
    proposal = await staged(client)
    other = await staged(client, note="Another note")
    answer = await client.post(f"/actions/{proposal.proposal_id}/decline", headers=PROXIED,
                               data={"session_id": "s1", "ids": other.proposal_id, "proposal_id": other.proposal_id})
    assert answer.status_code == 200
    assert proposal.status is ActionStatus.REVOKED
    assert other.status is ActionStatus.PENDING, "only the proposal the path names is withdrawn"


# ------------------------------------------------------------------ a bulk change


@pytest.fixture()
async def batch_client(monkeypatch):
    await _world(monkeypatch)
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = FakeProvider()
        store = store_of(3)
        runtime.shopify = store
        runtime.actions.ledger = NullLedger()
        runtime.batches.ledger = NullLedger()
        runtime.sessions = SessionManager()
        runtime.settings = runtime.settings.model_copy(update={"writes_enabled": True, "allowed_logins": OWNER,
                                                               "writes_local_owner": False, "tailscale_verify": False})
        app.state.allowed_logins = runtime.allowed_logins
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            c.store = store
            c.runtime = runtime
            yield c


async def test_not_now_withdraws_a_bulk_change_with_every_member_and_applies_none(batch_client):
    runtime = batch_client.runtime
    session = runtime.sessions.get_or_create("s1")
    session.epoch = max(session.epoch, 1)
    ws = orders_set(session, batch_client.store, clock=None)
    calls: list = []
    text = await dispatch("batch_order_tags_add", {"set_id": ws.set_id, "tags": ["hold"]}, session=session, timeout_s=10, calls=calls)
    assert text.startswith("PROPOSED BATCH")
    batch_id = calls[-1].proposal_id
    batch = runtime.batches.state(batch_id, "s1")
    children = [c.proposal_id for c in batch.eligible]
    assert children
    stranger = await batch_client.post(f"/batches/{batch_id}/decline", data={"session_id": "s1"}, headers=STRANGER)
    assert stranger.status_code == 403 and batch.status.value == "PENDING"
    answer = await batch_client.post(f"/batches/{batch_id}/decline", data={"session_id": "s1"}, headers=PROXIED)
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"batch_id": batch_id, "status": "revoked", "withdrawn": True}
    assert batch.reason == DECLINED_BY_OWNER
    assert all(runtime.actions.find(pid).status is ActionStatus.REVOKED for pid in children)
    late = await batch_client.post(f"/batches/{batch_id}/commit", data={"session_id": "s1"}, headers=PROXIED)
    assert late.json().get("status") != "done" and batch_client.store.mutations == []
    again = await batch_client.post(f"/batches/{batch_id}/decline", data={"session_id": "s1"}, headers=PROXIED)
    assert again.status_code == 409 and again.json()["code"] == "not_waiting"
