"""The action endpoint: the write boundary, the contract with the tablet, and the health line.

The tablet posts a proposal id and its session. It cannot post an argument: anything else in
the body is ignored, and the mutation is built from the Mac's stored proposal.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.actions.ledger import NullLedger
from app.main import app
from app.providers.base import TurnResult
from app.session.manager import SessionManager
from app.tools import shopify_tools
from app.tools.dispatch import dispatch
from tests.test_actions import ORDER, TOOL, FakeStore

# The admitted owner calling tools directly, as a request the door let through would: every tool
# call here is his (the 2026-09-27 deploy review, round 8, F-A2-FIXTURE). Production's default,
# and every test's that does not say this, is no authority at all.
pytestmark = pytest.mark.usefixtures("owner_asking")

OWNER = "owner@example.com"
PROXIED = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.9"}


class FakeProvider:
    async def start(self): pass
    async def stop(self): pass
    async def health(self): return True, "fake"
    async def reset_session(self, session_id): pass
    async def set_system_prompt(self, prompt): pass
    async def interrupt(self, session_id): return True
    async def turn(self, session_id, text): return TurnResult(text="fake answer", session_id=session_id)


@pytest.fixture()
async def client(monkeypatch):
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))

    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = FakeProvider()
        store = FakeStore(note="Gift wrap please")
        runtime.shopify = store
        shopify_tools.bind(store)
        runtime.actions.ledger = NullLedger()
        # The session manager is a process singleton; each test starts with no sessions.
        runtime.sessions = SessionManager()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.store = store
            c.runtime = runtime
            yield c


def configure(client, *, writes=True, logins=OWNER, local=False):
    runtime = client.runtime
    runtime.settings = runtime.settings.model_copy(
        update={"writes_enabled": writes, "allowed_logins": logins, "writes_local_owner": local, "tailscale_verify": False}
    )
    app.state.allowed_logins = runtime.allowed_logins


def as_owner(runtime, *, logins=OWNER, local=True):
    """The server is the owner's, for the owner-only routes: his login is on the list and, by
    default, a request made on the server itself speaks for him (CROOKS_LOCAL_OWNER and
    CROOKS_WRITES_LOCAL_OWNER alike). Writes are left as they are. With no allow-list those
    routes answer nobody (F-05B)."""
    runtime.settings = runtime.settings.model_copy(
        update={"allowed_logins": logins, "writes_local_owner": local, "local_owner": local, "tailscale_verify": False}
    )
    app.state.allowed_logins = runtime.allowed_logins


async def staged(client, session_id="s1", note="Customer asked for an exchange"):
    session = client.runtime.sessions.get_or_create(session_id)
    session.issue(ORDER)
    session.epoch = max(session.epoch, 1)
    text = await dispatch(TOOL, {"order_id": ORDER, "note": note}, session=session, timeout_s=5)
    assert text.startswith("PROPOSED")
    return session.proposals[-1]


async def commit(client, proposal_id, session_id="s1", headers=PROXIED, **extra):
    return await client.post(f"/actions/{proposal_id}/commit", data={"session_id": session_id, **extra}, headers=headers)


# --------------------------------------------------------------------------- the boundary


async def test_writes_off_means_nothing_executes(client):
    configure(client, writes=False)
    proposal = await staged(client)
    response = await commit(client, proposal.proposal_id)
    assert response.status_code == 403 and response.json()["code"] == "writes_disabled"
    assert client.store.mutations == [] and proposal.status.value == "PENDING"


async def test_no_allow_list_means_nothing_executes(client):
    configure(client, writes=True, logins="")
    proposal = await staged(client)
    response = await commit(client, proposal.proposal_id)
    assert response.status_code == 403 and response.json()["code"] == "allow_list_missing"
    assert client.store.mutations == []


async def test_an_unlisted_login_is_refused(client):
    configure(client)
    proposal = await staged(client)
    response = await commit(client, proposal.proposal_id, headers={"Tailscale-User-Login": "stranger@example.com", "X-Forwarded-For": "100.64.0.2"})
    assert response.status_code == 403
    assert client.store.mutations == []


async def test_a_proxied_request_with_no_login_is_refused(client):
    configure(client)
    proposal = await staged(client)
    response = await commit(client, proposal.proposal_id, headers={"X-Forwarded-For": "100.64.0.2"})
    assert response.status_code == 403 and client.store.mutations == []


async def test_the_mac_itself_may_not_commit_unless_told_so(client):
    configure(client, local=False)
    proposal = await staged(client)
    response = await commit(client, proposal.proposal_id, headers={})
    assert response.status_code == 403 and response.json()["code"] == "not_authorised_local"
    assert client.store.mutations == []
    configure(client, local=True)
    response = await commit(client, proposal.proposal_id, headers={})
    assert response.status_code == 200 and response.json()["status"] == "verified"
    assert proposal.caller == "local"


async def test_a_missing_scope_blocks_every_commit_and_shows_in_health(client):
    configure(client)
    client.store.scopes = {"read_orders"}
    proposal = await staged(client)
    response = await commit(client, proposal.proposal_id)
    assert response.status_code == 403 and response.json()["code"] == "scope_missing"
    assert client.store.mutations == []
    health = (await client.get("/health?fresh=1")).json()
    # Every write scope the build knows about, named, so the owner can see what to grant. A
    # family added later adds its scope to this line (write_order_edits is Phase 3's order
    # item editing; write_discounts, write_draft_orders and
    # write_store_credit_account_transactions are its discount, order-creation and
    # store-credit families) — which is the point of the line, and is why it is asserted in
    # full rather than by a substring.
    assert health["writes"] == {"state": "blocked", "detail": "blocked — Shopify write_discounts, write_draft_orders, write_inventory, write_merchant_managed_fulfillment_orders, write_order_edits, write_orders, write_store_credit_account_transactions scope missing"}
    assert health["checks"]["writes"]["ok"] is False


async def test_health_says_when_writes_are_off_and_when_they_are_ready(client):
    configure(client, writes=False)
    health = (await client.get("/health?fresh=1")).json()
    assert health["writes"] == {"state": "disabled", "detail": "disabled — CROOKS_WRITES_ENABLED=false"}
    assert health["checks"]["writes"]["ok"] is True, "off by configuration is not a fault"
    configure(client, writes=True, logins="")
    # With no allow-list nobody is the owner, so the server's own status reader reads this with
    # the server's key; without it, only liveness (the 2026-09-27 deploy review, round 8, F-NEW-PAD).
    from app import local_cli

    local_cli.bind_key("k" * 43)
    blocked = (await client.get("/health?fresh=1", headers={local_cli.HEADER: "k" * 43})).json()
    assert blocked["writes"]["detail"] == "blocked — CROOKS_ALLOWED_LOGINS not configured"
    assert "writes" not in (await client.get("/health")).json()
    configure(client)
    ready = (await client.get("/health?fresh=1")).json()["writes"]
    assert ready["state"] == "ready" and ready["detail"].startswith("ready — ") and "order note append" in ready["detail"]
    assert client.store.mutations == [], "health never mutates"


# --------------------------------------------------------------------------- the contract


async def test_an_authorised_tap_executes_once_and_returns_verified_state(client):
    configure(client)
    proposal = await staged(client)
    response = await commit(client, proposal.proposal_id)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "verified" and body["code"] == "verified"
    assert body["spoken"] == "Note added to order 1930."
    assert [i["type"] for i in body["ui"]] == ["success", "order"]
    assert body["ui"][0]["data"]["title"] == "Note added" and body["ui"][0]["data"]["detail"] == "Order #1930"
    assert body["ui"][1]["data"]["note"].endswith("Customer asked for an exchange")
    assert body["undo"]["status"] == "pending" and body["undo"]["undo_of"] == proposal.proposal_id
    # The public shape, exhaustively: an id, a lifecycle, words for the card, and which
    # branch of the conversation it belongs to. No arguments, no fingerprint, no personal data.
    assert set(body) <= {"proposal_id", "status", "code", "operation", "risk", "entity_kind", "entity_label", "interaction",
                         "reversible", "expires_at", "ttl_s", "undo_of", "undo_id", "note", "branch_id", "spoken", "ui", "undo"}
    assert client.store.mutations == [("order_note_set", {"id": ORDER, "note": "Gift wrap please\nCustomer asked for an exchange"})]


async def test_the_body_cannot_change_what_is_sent(client):
    configure(client)
    proposal = await staged(client)
    response = await commit(
        client, proposal.proposal_id, order_id="gid://shopify/Order/999", note="EVIL", desired_note="EVIL",
        amount="1000", query="mutation { orderUpdate }",
    )
    assert response.status_code == 200 and response.json()["status"] == "verified"
    (name, variables), = client.store.mutations
    assert variables == {"id": ORDER, "note": "Gift wrap please\nCustomer asked for an exchange"}


async def test_two_taps_at_once_are_one_mutation(client):
    configure(client)
    proposal = await staged(client)
    a, b = await asyncio.gather(commit(client, proposal.proposal_id), commit(client, proposal.proposal_id))
    assert {a.status_code, b.status_code} == {200}
    assert sorted([a.json()["code"], b.json()["code"]]) == ["already_executed", "verified"]
    assert len(client.store.mutations) == 1


async def test_a_retried_request_returns_the_settled_outcome(client):
    configure(client)
    proposal = await staged(client)
    await commit(client, proposal.proposal_id)
    again = (await commit(client, proposal.proposal_id)).json()
    assert again["code"] == "already_executed" and again["ui"][0]["type"] == "success"
    assert len(client.store.mutations) == 1


async def test_a_stale_order_is_reported_not_overwritten(client):
    configure(client)
    proposal = await staged(client)
    client.store.note = "Changed in Admin"
    body = (await commit(client, proposal.proposal_id)).json()
    assert body["status"] == "stale" and body["spoken"].startswith("The order changed")
    assert body["ui"][0]["type"] == "error" and body["ui"][0]["data"]["title"] == "Not applied"
    assert client.store.mutations == [] and client.store.note == "Changed in Admin"


async def test_unverified_is_never_shown_as_success(client):
    configure(client)
    proposal = await staged(client)
    client.store.note_after_mutation = "Gift wrap please"
    body = (await commit(client, proposal.proposal_id)).json()
    assert body["status"] == "unverified" and body["spoken"] == "I couldn't confirm that change."
    assert [i["type"] for i in body["ui"]] == ["error"] and body["undo"] is None


async def test_the_wrong_session_or_an_unknown_proposal_is_refused(client):
    configure(client)
    proposal = await staged(client)
    assert (await commit(client, proposal.proposal_id, session_id="other")).status_code == 403
    assert (await commit(client, "prop_nothing")).status_code == 404
    assert client.store.mutations == []


async def test_state_can_be_asked_after_a_lost_connection(client):
    configure(client)
    proposal = await staged(client)
    pending = (await client.get(f"/actions/{proposal.proposal_id}?session_id=s1")).json()
    assert pending["status"] == "pending" and pending["ui"][0]["type"] == "confirmation"
    # What the state answer carries is the public card, never the execution the Mac will send
    # or the fingerprint it will check: those stay on the Mac (round 9, I-tests1 I-01 — this
    # line ended in `or True` and so asserted nothing).
    card = pending["ui"][0]["data"]
    assert "execution" not in pending and "execution" not in card
    assert "before" not in card and "expected_after" not in card and "model_args" not in card
    assert "execution" not in str(pending) and "orderUpdate" not in str(pending)
    await commit(client, proposal.proposal_id)
    settled = (await client.get(f"/actions/{proposal.proposal_id}?session_id=s1")).json()
    assert settled["status"] == "verified" and settled["ui"][0]["type"] == "success"
    assert (await client.get(f"/actions/{proposal.proposal_id}?session_id=other")).status_code == 404


async def test_a_new_turn_a_cancel_and_a_reset_withdraw_pending_proposals(client):
    configure(client)
    p1 = await staged(client, session_id="s2")
    await client.post("/turn", json={"text": "and what about yesterday?", "session_id": "s2"})
    assert p1.status.value == "REVOKED"
    assert (await client.get("/state/s2")).json()["epoch"] == 2
    p2 = await staged(client, session_id="s2")
    await client.post("/cancel", data={"session_id": "s2"})
    assert p2.status.value == "REVOKED"
    p3 = await staged(client, session_id="s2")
    await client.post("/reset", data={"session_id": "s2"})
    assert p3.status.value == "REVOKED"
    assert (await commit(client, p3.proposal_id, session_id="s2")).status_code == 404
    assert client.store.mutations == []


async def test_a_turn_response_carries_the_confirmation_card_not_a_result(client):
    """/turn's `ui` shows the proposal as an action card; the tool call's content is not
    logged, only its length."""
    configure(client)
    session = client.runtime.sessions.get_or_create("s3")
    session.issue(ORDER)
    from app.presentation import present
    from app.providers.base import ToolCall

    session.epoch = 1
    text = await dispatch(TOOL, {"order_id": ORDER, "note": "Hold for collection"}, session=session, timeout_s=5)
    proposal = session.proposals[-1]
    ui = present([ToolCall(name=TOOL, args={"order_id": ORDER, "note": "Hold for collection"}, ok=True, proposal_id=proposal.proposal_id)], session=session)
    assert ui[0]["type"] == "confirmation"
    card = ui[0]["data"]
    assert card["proposal_id"] == proposal.proposal_id and card["risk"] == "amber" and card["status"] == "pending"
    assert card["title"] == "Add order note" and card["entity"] == "Order #1930" and card["summary"] == "Hold for collection"
    assert card["interaction"]["kind"] == "tap_commit" and card["interaction"]["label"] == "Tap to apply"
    assert card["interaction"]["armed_after_ms"] == 650 and card["interaction"]["footer"] == "nothing happens until you tap"
    assert card["ttl_s"] <= 60 and card["reversible"] is True
    assert "PROPOSED" in text
    from app.routes.turn import _loggable_args

    logged = _loggable_args(ToolCall(name=TOOL, args={"order_id": ORDER, "note": "Hold for collection"}, ok=True, proposal_id=proposal.proposal_id))
    assert logged == {"order_id": ORDER, "note": "<19 chars>"}


async def test_whoami_reports_the_tailscale_login_or_says_there_is_none(client):
    configure(client)   # the check that tailscaled opened the connection is off here; see below
    body = (await client.get("/whoami", headers=PROXIED)).json()
    assert body["login"] == OWNER and body["proxied"] is True and body["through"] == "tailscale"
    body = (await client.get("/whoami")).json()
    assert body["login"] is None and body["proxied"] is False and body["through"] == "direct"
    # With it on (production), the same headers from something that is not tailscaled are refused
    # before any route answers (F-05B; tests/test_proxy_identity.py).
    client.runtime.settings = client.runtime.settings.model_copy(update={"tailscale_verify": True})
    refused = await client.get("/whoami", headers=PROXIED)
    assert refused.status_code == 403 and refused.json() == {"error": "not allowed", "who": "unverified proxy"}


async def test_a_commit_never_reaches_claude(client):
    configure(client)
    turns_before = list(getattr(client.runtime.provider, "turns", []))
    proposal = await staged(client)
    await commit(client, proposal.proposal_id)
    assert list(getattr(client.runtime.provider, "turns", [])) == turns_before


# --------------------------------------------------------------------------- what the turn says


class StagingProvider(FakeProvider):
    """A provider that behaves like Claude asked to add a note: finds nothing, calls the write
    tool, and answers as the tool told it to."""

    def __init__(self, runtime):
        self.runtime = runtime
        self.turns = []

    async def turn(self, session_id, text):
        from app.providers.base import ToolCall

        self.turns.append((session_id, text))
        session = self.runtime.sessions.get_or_create(session_id)
        session.issue(ORDER)
        await dispatch(TOOL, {"order_id": ORDER, "note": "Customer asked for an exchange"}, session=session, timeout_s=5)
        proposal = session.proposals[-1]
        return TurnResult(
            text="The note's ready. Tap the card to apply it.", session_id=session_id,
            tool_calls=[ToolCall(name=TOOL, args={"order_id": ORDER, "note": "Customer asked for an exchange"}, ok=True, proposal_id=proposal.proposal_id)],
        )


async def test_a_proposal_from_an_allowed_tablet_arms_and_says_only_that_it_is_ready(client):
    configure(client)
    client.runtime.provider = StagingProvider(client.runtime)
    body = (await client.post("/turn", json={"text": "add a note to order 1938", "session_id": "t1"}, headers=PROXIED)).json()
    assert body["answer"] == "The note's ready. Tap the card to apply it."
    (card,) = [i for i in body["ui"] if i["type"] == "confirmation"]
    assert card["data"]["commit"] == {"allowed": True}
    assert card["data"]["status"] == "pending" and card["data"]["interaction"]["kind"] == "tap_commit"
    assert body["writes"]["allowed"] is True and body["writes"]["caller"] == OWNER
    assert body["error_kind"] is None and not [i for i in body["ui"] if i["type"] == "error"]
    for forbidden in ("not allowed", "isn't allowed", "aren't allowed", "read-only", "cannot", "permission", "added the note", "note added"):
        assert forbidden not in body["answer"].lower()
    assert body["revoked"] == [] and client.store.mutations == []
    assert body["ui"][0]["type"] == "confirmation", "the card is first"
    assert [i["type"] for i in body["ui"]].count("confirmation") == 1
    assert card["data"]["risk"] == "amber" and card["data"]["interaction"]["armed_after_ms"] == 650
    # The ledger shows the proposal and its delivery, and nothing executed.
    events = [e["event"] for e in client.runtime.actions.ledger.read()]
    assert events[-2:] == ["PROPOSED", "DELIVERED"] and "EXECUTING" not in events


async def test_a_turn_time_refusal_is_logged_and_the_local_case_is_named(client, caplog):
    """The sentence the owner hears when a tap would be refused is matched by one warning in
    the log, naming the code; and a request made on the Mac itself is not blamed on 'this
    tablet's login'."""
    import logging

    caplog.set_level(logging.WARNING, logger="crooks.actions")
    configure(client, writes=True, logins=OWNER, local=False)
    client.runtime.provider = StagingProvider(client.runtime)
    body = (await client.post("/turn", json={"text": "add a note to order 1938", "session_id": "loc"})).json()
    assert body["writes"]["allowed"] is False and body["writes"]["code"] == "not_authorised_local"
    (card,) = [i for i in body["ui"] if i["type"] == "confirmation"]
    assert card["data"]["commit"]["code"] == "not_authorised_local"
    assert "server itself" in card["data"]["commit"]["reason"] and "tablet" not in card["data"]["commit"]["reason"].lower()
    lines = [r.getMessage() for r in caplog.records if "tap would be refused" in r.getMessage()]
    assert len(lines) == 1 and "not_authorised_local" in lines[0] and "proxied=False" in lines[0]


@pytest.mark.parametrize("setup, headers, code, phrase", [
    (dict(writes=False), PROXIED, "writes_disabled", "switched off"),
    (dict(writes=True, local=False), {}, "not_authorised_local", "from the server itself"),
])
async def test_a_proposal_this_tablet_cannot_apply_says_so_at_once(client, setup, headers, code, phrase):
    """The card appears, but its surface never arms, the reason is on it, and the spoken answer
    carries the same fixed sentence — before anyone taps, not after a refused tap. (A login
    that is not on the allow-list never gets this far: the middleware refuses it outright.)"""
    configure(client, **setup)
    client.runtime.provider = StagingProvider(client.runtime)
    body = (await client.post("/turn", json={"text": "add a note to order 1938", "session_id": "t2"}, headers=headers)).json()
    assert body["writes"]["allowed"] is False and body["writes"]["code"] == code
    (card,) = [i for i in body["ui"] if i["type"] == "confirmation"]
    assert card["data"]["commit"]["allowed"] is False and card["data"]["commit"]["code"] == code
    assert card["data"]["commit"]["reason"]
    assert phrase in body["answer"], body["answer"]
    assert body["answer"].startswith("The note's ready.")
    assert client.store.mutations == []


async def test_with_no_allow_list_nobody_can_even_ask(client):
    """Round 6: a server nobody has said is anyone's answers no turn at all, from a device or from
    itself, and says so with the write boundary's own code and line, rather than drawing a card a
    tap could not apply."""
    configure(client, writes=True, logins="", local=True)
    for headers in (PROXIED, {}):
        refused = await client.post("/turn", json={"text": "add a note to order 1938", "session_id": "t3"}, headers=headers)
        assert refused.status_code == 403 and refused.json()["code"] == "allow_list_missing"
        assert refused.json()["spoken"] == "Nobody is allowed to apply changes yet: the allowed logins aren't set on the server."
    assert client.store.mutations == []


async def test_a_refused_commit_carries_a_spoken_line(client):
    configure(client, writes=False)
    proposal = await staged(client)
    body = (await commit(client, proposal.proposal_id)).json()
    assert body["code"] == "writes_disabled" and body["spoken"].startswith("Changes are switched off")
    configure(client, local=False)
    body = (await commit(client, proposal.proposal_id, headers={})).json()
    assert body["code"] == "not_authorised_local" and body["spoken"].startswith("Requests from the server itself")


async def test_a_login_outside_the_allow_list_cannot_even_ask(client):
    """The general guard, not the write boundary: such a tablet gets a 403 on everything, and
    the tablet must show that as "not allowed", never as "offline"."""
    configure(client, logins="someone-else@example.com")
    for path in ("/ping", "/health", "/turn"):
        response = await (client.post(path, json={"text": "hi", "session_id": "x"}, headers=PROXIED) if path == "/turn" else client.get(path, headers=PROXIED))
        assert response.status_code == 403 and response.json()["error"] == "not allowed", path


# --------------------------------------------------------------------------- cross-site


async def test_a_cross_site_post_is_refused_even_with_the_tablets_identity(client):
    configure(client)
    proposal = await staged(client)
    for headers in (
        {**PROXIED, "Sec-Fetch-Site": "cross-site"},
        {**PROXIED, "Sec-Fetch-Site": "same-site"},
        {**PROXIED, "Origin": "https://evil.example"},
        {**PROXIED, "Origin": "null"},
    ):
        response = await commit(client, proposal.proposal_id, headers=headers)
        assert response.status_code == 403, headers
        response = await client.post("/turn", json={"text": "hi", "session_id": "x"}, headers=headers)
        assert response.status_code == 403, headers
    assert client.store.mutations == [] and proposal.status.value == "PENDING"


async def test_the_tablets_own_page_and_scripts_still_pass(client):
    configure(client)
    proposal = await staged(client)
    ok = [
        {**PROXIED, "Sec-Fetch-Site": "same-origin", "Origin": "https://crooks-assistant.taildfb357.ts.net", "X-Forwarded-Host": "crooks-assistant.taildfb357.ts.net"},
        {**PROXIED, "Sec-Fetch-Site": "none"},
        {**PROXIED},                                  # curl-style: no fetch metadata at all
        {**PROXIED, "Origin": "http://t", "Host": "t"},
    ]
    for headers in ok[:-1]:
        assert (await client.get("/ping", headers=headers)).status_code == 200
        assert (await client.post("/cancel", data={"session_id": "x"}, headers=headers)).status_code == 200, headers
    response = await commit(client, proposal.proposal_id, headers=ok[0])
    assert response.status_code == 200 and response.json()["status"] == "verified"


async def test_a_fumbled_hold_does_not_withdraw_the_card(client):
    """A recording that said nothing is not an instruction. The card the owner was about to
    tap survives it; the next real question withdraws it and says which cards it withdrew."""
    configure(client)
    proposal = await staged(client, session_id="s7")
    noise = await client.post("/turn", data={"session_id": "s7"}, files={"audio": ("t.webm", b"\x00" * 64, "audio/webm")})
    assert noise.json()["error_kind"] == "speech" and noise.json()["revoked"] == []
    empty = await client.post("/turn", json={"text": "   ", "session_id": "s7"})
    assert empty.json()["error_kind"] == "empty" and empty.json()["revoked"] == []
    assert proposal.status.value == "PENDING"
    real = (await client.post("/turn", json={"text": "and yesterday?", "session_id": "s7"})).json()
    assert real["revoked"] == [proposal.proposal_id] and proposal.status.value == "REVOKED"


async def test_while_a_change_is_being_applied_the_state_says_so(client):
    configure(client)
    proposal = await staged(client)
    client.store.gate_reads_after_mutation = asyncio.Event()
    tap = asyncio.create_task(commit(client, proposal.proposal_id))
    for _ in range(200):
        await asyncio.sleep(0.005)
        if client.store.mutations:
            break
    assert client.store.mutations, "the mutation left"
    mid = (await client.get(f"/actions/{proposal.proposal_id}?session_id=s1")).json()
    assert mid["status"] in ("executing", "executed")
    assert mid["ui"][0]["data"]["title"] == "Applying"
    assert "Nothing was changed" not in str(mid["ui"])
    client.store.gate_reads_after_mutation.set()
    assert (await tap).json()["status"] == "verified"


async def test_a_lost_answer_is_never_reported_as_nothing_changed(client):
    configure(client)
    proposal = await staged(client)
    client.store.lose_answer = True
    body = (await commit(client, proposal.proposal_id)).json()
    assert body["status"] == "verified" and body["ui"][0]["type"] == "success"
    assert len(client.store.mutations) == 1


def test_a_write_tools_note_is_logged_by_length_only_even_when_refused():
    from types import SimpleNamespace

    from app.routes.turn import _loggable_args

    refused = SimpleNamespace(name=TOOL, args={"order_id": ORDER, "note": "Refund Daniel Sear, 12 Acacia Avenue"}, proposal_id=None)
    logged = _loggable_args(refused)
    assert logged["note"] == "<36 chars>" and logged["order_id"] == ORDER
    # A READ's arguments are kept, because they are what make a wrong answer diagnosable, and
    # are redacted by shape at once; a name is not a shape, and it goes when the turn log is
    # written with the names the turn's tools returned (`TurnLog.write(..., names=...)`). This
    # line used to end in `or True` and assert nothing (round 9, I-tests1 I-01).
    from app.logging.turnlog import redact

    read = SimpleNamespace(name="shopify_find_order", args={"query": "Daniel Sear daniel@example.com"}, proposal_id=None)
    kept = _loggable_args(read)
    assert "daniel@example.com" not in str(kept) and "[email]" in kept["query"]
    assert "Daniel" not in str(redact(kept, {"Daniel Sear"}))


async def test_a_proxied_request_with_no_login_is_refused_even_with_no_allow_list(client):
    """Funnel, a tagged node, anything reaching tailscale serve without a tailnet identity:
    refused whether or not CROOKS_ALLOWED_LOGINS is set. The Mac itself (no headers) and a
    tailnet login (any, when no list is set) still pass."""
    configure(client, logins="")
    anonymous = {"X-Forwarded-For": "100.64.0.9"}
    for path in ("/ping", "/health", "/"):
        response = await client.get(path, headers=anonymous)
        assert response.status_code == 403 and response.json() == {"error": "not allowed", "who": "unknown"}, path
    assert (await client.post("/turn", json={"text": "hi", "session_id": "x"}, headers=anonymous)).status_code == 403
    assert (await client.get("/ping")).status_code == 200
    assert (await client.get("/ping", headers=PROXIED)).status_code == 200
    # And with a list, only its logins pass.
    configure(client, logins="someone-else@example.com")
    assert (await client.get("/ping", headers=PROXIED)).status_code == 403


async def test_a_spoken_yes_leaves_the_card_waiting_and_says_what_applies_it(client):
    """"Yes" while a card is waiting is neither an instruction nor an authorisation: the
    card stays, the epoch stays, the model is not asked, and a fixed line says to tap."""
    configure(client)
    proposal = await staged(client, session_id="s9")
    epoch_before = client.runtime.sessions.get("s9").epoch
    turns_before = len(getattr(client.runtime.provider, "turns", []))
    body = (await client.post("/turn", json={"text": "Yes, go ahead.", "session_id": "s9", "speak": True}, headers=PROXIED)).json()
    assert body["answer"] == "Nothing happens until you tap the card. It is still waiting on the screen."
    assert proposal.status.value == "PENDING" and body["revoked"] == []
    assert client.runtime.sessions.get("s9").epoch == epoch_before
    assert len(getattr(client.runtime.provider, "turns", [])) == turns_before
    assert body["ui"][0]["type"] == "confirmation" and body["ui"][0]["data"]["proposal_id"] == proposal.proposal_id
    assert body["ui"][0]["data"]["commit"] == {"allowed": True}
    assert client.store.mutations == []
    # The next real question withdraws it as before.
    real = (await client.post("/turn", json={"text": "and what about yesterday?", "session_id": "s9"}, headers=PROXIED)).json()
    assert real["revoked"] == [proposal.proposal_id]
    # With nothing waiting, "yes" is an ordinary (if odd) question for the model.
    again = (await client.post("/turn", json={"text": "yes", "session_id": "s9"}, headers=PROXIED)).json()
    assert again["answer"] == "fake answer"


async def test_the_spoken_yes_line_is_synthesised_once_and_kept(client):
    """It is said often and always in the same words: one ElevenLabs request, ever."""
    from tests.test_routes import stub_voice

    configure(client)
    calls = stub_voice(app)
    await staged(client, session_id="s11")
    for _ in range(3):
        body = (await client.post("/turn", json={"text": "yes", "session_id": "s11", "speak": True}, headers=PROXIED)).json()
        assert body["answer"].startswith("Nothing happens until you tap")
        assert (await client.post("/speak", json={"text": body["answer"]})).status_code == 200
    assert len(calls) == 1


async def test_a_spoken_yes_does_not_wind_the_clock_back_and_ignores_the_undo(client):
    """The card's minute runs from its first delivery; saying yes again and again does not
    keep it alive. And "okay" said after "Note added" is not about the undo card."""
    configure(client)
    proposal = await staged(client, session_id="s10")
    first = (await client.post("/turn", json={"text": "yes", "session_id": "s10"}, headers=PROXIED)).json()
    assert first["ui"][0]["type"] == "confirmation"
    expires = proposal.expires_at
    second = (await client.post("/turn", json={"text": "okay", "session_id": "s10"}, headers=PROXIED)).json()
    assert second["ui"][0]["type"] == "confirmation" and proposal.expires_at == expires, "no second minute"
    events = [e["event"] for e in client.runtime.actions.ledger.read() if e["proposal_id"] == proposal.proposal_id]
    assert events.count("DELIVERED") == 1
    # Applied; the undo now waits. "Okay" is for the model, not the undo.
    body = (await commit(client, proposal.proposal_id, session_id="s10")).json()
    assert body["status"] == "verified" and body["undo"]["proposal_id"]
    after = (await client.post("/turn", json={"text": "okay", "session_id": "s10"}, headers=PROXIED)).json()
    assert after["answer"] == "fake answer" and not [i for i in after["ui"] if i["type"] == "confirmation"]
    # The undo belongs to the change just made, not to "okay": it is still there to tap.
    undo = client.runtime.sessions.get("s10").proposal(body["undo"]["proposal_id"])
    assert undo.status.value == "PENDING" and undo.epoch == client.runtime.sessions.get("s10").epoch
    undone = (await commit(client, undo.proposal_id, session_id="s10")).json()
    assert undone["status"] == "verified" and len(client.store.mutations) == 2


async def test_a_shopify_blip_is_not_spoken_as_a_permission_refusal(client):
    """The scope check is a read that can fail like any other. When it does, the Mac must not
    tell the owner the store has refused it: the card stays live and the tap decides."""
    configure(client)

    async def unreachable(*a, **k):
        raise RuntimeError("Shopify is not answering")

    client.store.access_scopes = unreachable  # type: ignore[method-assign]
    client.runtime.provider = StagingProvider(client.runtime)
    body = (await client.post("/turn", json={"text": "add a note to order 1938", "session_id": "blip"}, headers=PROXIED)).json()
    assert body["writes"]["allowed"] is True and body["writes"]["state"] == "unknown"
    assert "permission" not in body["answer"].lower() and "not allowed" not in body["answer"].lower()
    (card,) = [i for i in body["ui"] if i["type"] == "confirmation"]
    assert card["data"]["commit"] == {"allowed": True}
    # And the tap is still answered by Shopify, not by a guess: with the store back, it works.
    proposal = client.runtime.sessions.get("blip").proposals[-1]
    del client.store.access_scopes
    assert (await commit(client, proposal.proposal_id, session_id="blip")).json()["status"] == "verified"


async def test_a_login_header_without_the_proxy_is_worth_nothing(client):
    """Only `tailscale serve` stamps an identity, and it stamps X-Forwarded-For with it. A
    process on the Mac that adds the header by hand is still a request made on the Mac."""
    configure(client, local=False)
    proposal = await staged(client, session_id="s12")
    spoofed = {"Tailscale-User-Login": OWNER}
    response = await commit(client, proposal.proposal_id, session_id="s12", headers=spoofed)
    assert response.status_code == 403 and response.json()["code"] == "not_authorised_local"
    assert client.store.mutations == []
    # With the local owner permitted, the same request is allowed — as a local one, and the
    # ledger says so rather than naming a login it cannot check.
    configure(client, local=True)
    assert (await commit(client, proposal.proposal_id, session_id="s12", headers=spoofed)).json()["status"] == "verified"
    assert proposal.caller == "local"


async def test_a_card_recovered_after_a_lost_connection_is_honest_about_the_tap(client):
    """The tablet asks what happened when a commit's answer never arrived. If a tap from
    where it is would now be refused, the card it gets back must say so rather than arming."""
    configure(client)
    proposal = await staged(client, session_id="s13")
    live = (await client.get(f"/actions/{proposal.proposal_id}?session_id=s13", headers=PROXIED)).json()
    assert live["ui"][0]["data"]["commit"] == {"allowed": True}
    configure(client, writes=False)
    blocked = (await client.get(f"/actions/{proposal.proposal_id}?session_id=s13", headers=PROXIED)).json()
    assert blocked["ui"][0]["data"]["commit"]["allowed"] is False
    assert blocked["ui"][0]["data"]["commit"]["code"] == "writes_disabled"


async def test_a_slow_shopify_costs_the_preflight_bound_once(client):
    """A scope check that hangs must not be paid twice — once before the answer's voice and
    again when the owner taps. The bound is paid once, then remembered for a while."""
    import time as _time

    from app.routes import actions as actions_module

    configure(client)
    actions_module._preflight_timed_out_at = 0.0
    hang = asyncio.Event()

    async def slow_scopes(*a, **k):
        await hang.wait()
        return frozenset({"write_orders"})

    client.store.access_scopes = slow_scopes  # type: ignore[method-assign]
    client.runtime.provider = StagingProvider(client.runtime)
    started = _time.perf_counter()
    body = (await client.post("/turn", json={"text": "add a note to order 1938", "session_id": "slow"}, headers=PROXIED)).json()
    first_ms = (_time.perf_counter() - started) * 1000
    assert body["writes"]["allowed"] is True and body["writes"]["state"] == "unknown"
    assert first_ms < actions_module.WRITE_STATUS_TIMEOUT_S * 1000 + 800, first_ms

    proposal = client.runtime.sessions.get("slow").proposals[-1]
    started = _time.perf_counter()
    tapped = (await commit(client, proposal.proposal_id, session_id="slow")).json()
    tap_ms = (_time.perf_counter() - started) * 1000
    assert tapped["status"] == "verified"
    assert tap_ms < 500, f"the tap paid the bound again: {tap_ms:.0f} ms"
    hang.set()
    actions_module._preflight_timed_out_at = 0.0


# --------------------------------------------------------------------------- capabilities


async def test_health_names_every_change_and_whether_it_could_be_made(client):
    configure(client)
    health = (await client.get("/health?fresh=1")).json()
    caps = health["capabilities"]
    assert caps["order_note_append"] == {"state": "ready", "detail": "ready — order note append", "scope": "write_orders"}
    # No Gmail credential is stored here: the email changes are blocked, and say why — never
    # "disabled" by a switch, never "ready" on the strength of a comment.
    assert caps["gmail_send_reply"]["state"] == "blocked" and "Re-authorise" in caps["gmail_send_reply"]["detail"]
    assert caps["gmail_draft_reply"]["scope"] == "gmail:draft" and caps["gmail_send_reply"]["scope"] == "gmail:send"
    client.store.scopes = {"read_orders"}
    client.store._scopes = None
    health = (await client.get("/health?fresh=1")).json()
    assert health["capabilities"]["order_note_append"]["state"] == "blocked"
    assert "write_orders scope missing" in health["capabilities"]["order_note_append"]["detail"]
    configure(client, writes=False)
    assert (await client.get("/health?fresh=1")).json()["capabilities"]["order_note_append"]["state"] == "disabled"


async def test_the_commit_preflight_is_for_the_proposals_own_scope(client, monkeypatch):
    """A fulfilment scope the store has not granted does not stop a note."""
    from app.clients.shopify import REVIEWED_MUTATIONS, ReviewedMutation
    from app.tools import registry
    from app.tools.gate import Tier
    from app.tools.registry import ToolSpec, WriteSpec

    configure(client)
    client.store.scopes = {"read_orders", "write_orders"}
    client.store._scopes = None
    monkeypatch.setitem(REVIEWED_MUTATIONS, "probe_fulfil", ReviewedMutation(name="probe_fulfil", document="mutation X { x }", variables={}, scope="write_merchant_managed_fulfillment_orders"))

    async def never(*a, **k):
        raise AssertionError("never runs")

    spec = ToolSpec(name="shopify_fulfil_probe", description="d", input_schema={"type": "object", "properties": {"order_id": {"type": "string"}}}, tier=Tier.RED, handler=never,
                    issued_id_args=("order_id",), write=WriteSpec(operation="fulfillment_probe", entity_kind="order", entity_arg="order_id", mutation="probe_fulfil", observe=never, execute=never, present=lambda p: {}))
    monkeypatch.setitem(registry._REGISTRY, "shopify_fulfil_probe", spec)
    health = (await client.get("/health?fresh=1")).json()
    assert health["writes"]["state"] == "ready", "a scope one change lacks does not block the others"
    assert "fulfillment probe needs write_merchant_managed_fulfillment_orders" in health["writes"]["detail"]
    assert health["capabilities"]["order_note_append"]["state"] == "ready"
    assert health["capabilities"]["fulfillment_probe"]["state"] == "blocked"
    proposal = await staged(client)
    response = await commit(client, proposal.proposal_id)
    assert response.status_code == 200 and response.json()["status"] == "verified", response.text


# --------------------------------------------------------------------------- one conversation, one login


async def test_a_conversation_belongs_to_the_login_that_started_it(client):
    """Two logins the Mac admits; one conversation. The other login gets none of it."""
    configure(client, logins=f"{OWNER}, other@example.com")
    stranger = {"Tailscale-User-Login": "other@example.com", "X-Forwarded-For": "100.64.0.3"}
    started = await client.post("/turn", json={"text": "hello", "session_id": "mine"}, headers=PROXIED)
    assert started.status_code == 200
    assert client.runtime.sessions.peek("mine").login == OWNER
    for path in ("/state/mine",):
        assert (await client.get(path, headers=stranger)).status_code == 403
        assert (await client.get(path, headers=PROXIED)).status_code == 200
    assert (await client.post("/turn", json={"text": "and mine?", "session_id": "mine"}, headers=stranger)).status_code == 403
    assert (await client.post("/cancel", data={"session_id": "mine"}, headers=stranger)).status_code == 403
    assert (await client.post("/reset", data={"session_id": "mine"}, headers=stranger)).status_code == 403
    assert client.runtime.sessions.exists("mine"), "the stranger's reset reset nothing"
    proposal = await staged(client, session_id="mine")
    refused = await commit(client, proposal.proposal_id, session_id="mine", headers=stranger)
    assert refused.status_code == 403 and refused.json()["code"] == "wrong_session"
    assert (await client.get(f"/actions/{proposal.proposal_id}", params={"session_id": "mine"}, headers=stranger)).status_code == 403
    assert client.store.mutations == []
    # The Mac itself is the owner's own machine: it may look, and binds nothing.
    assert (await client.get("/state/mine")).status_code == 200
    # A session made outside a request binds to its first tailnet caller, and to nobody after.
    client.runtime.sessions.get_or_create("fresh")
    assert (await client.get("/state/fresh")).status_code == 200
    assert client.runtime.sessions.peek("fresh").login == ""
    assert (await client.get("/state/fresh", headers=stranger)).status_code == 200
    assert (await client.get("/state/fresh", headers=PROXIED)).status_code == 403


# --------------------------------------------------------------------------- arming


async def test_a_hold_is_armed_on_the_mac_and_the_commit_carries_the_token_in_a_header(client, monkeypatch):
    """A RED hold: the tablet arms when the hold begins, the Mac hands back a single-use
    token, and the commit must carry it — in a header, so the body stays the session alone."""
    import tests.test_engine_hooks as hooks
    from app.actions.models import Prepared
    from app.tools import registry
    from app.tools.gate import Tier
    from app.tools.registry import ToolSpec, WriteSpec
    from tests.test_engine_hooks import World
    from tests.test_engine_hooks import execute as probe_execute
    from tests.test_engine_hooks import observe as probe_observe
    from tests.test_engine_hooks import present as probe_present
    from tests.test_engine_hooks import settle as probe_settle
    from tests.test_engine_hooks import verify as probe_verify

    hooks.world = World()
    configure(client)

    async def prepare(order_id: str, refund: str = "60.00") -> Prepared:
        return Prepared(execution={"order_id": order_id, "refund": refund}, before=dict(hooks.world.state()), expected_after={"cancelled": True},
                        entity_ref=order_id, entity_label="#1930", summary={"read_back": "cancel"})

    spec = ToolSpec(name="shopify_cancel_probe", description="d", input_schema={"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
                    tier=Tier.RED, handler=prepare, issued_id_args=("order_id",),
                    write=WriteSpec(operation="cancel_probe", entity_kind="order", entity_arg="order_id", mutation="order_note_set", observe=probe_observe,
                                    execute=probe_execute, present=probe_present, op_class="money", verify=probe_verify, settle=probe_settle, spoken_success="Order {label} cancelled."))
    monkeypatch.setitem(registry._REGISTRY, "shopify_cancel_probe", spec)
    session = client.runtime.sessions.get_or_create("h1")
    session.issue(ORDER)
    session.epoch = max(session.epoch, 1)
    text = await dispatch("shopify_cancel_probe", {"order_id": ORDER}, session=session, timeout_s=5)
    assert text.startswith("PROPOSED")
    proposal = session.proposals[-1]
    assert proposal.interaction == "hold_drag_target"

    # Without the hold: refused, and the card is still waiting.
    refused = await commit(client, proposal.proposal_id, session_id="h1")
    assert refused.status_code == 409 and refused.json()["code"] == "not_armed" and proposal.status.value == "PENDING"
    # The hold begins: a token. A stranger cannot arm it; nor can an unlisted login.
    stranger = {"Tailscale-User-Login": "x@example.com", "X-Forwarded-For": "100.64.0.3"}
    assert (await client.post(f"/actions/{proposal.proposal_id}/arm", data={"session_id": "h1"}, headers=stranger)).status_code == 403
    armed = await client.post(f"/actions/{proposal.proposal_id}/arm", data={"session_id": "h1"}, headers=PROXIED)
    assert armed.status_code == 200 and armed.json()["hold_ms"] == 900
    nonce = armed.json()["nonce"]
    # Too soon: the dwell has not passed.
    early = await client.post(f"/actions/{proposal.proposal_id}/commit", data={"session_id": "h1"}, headers={**PROXIED, "X-Crooks-Arm": nonce})
    assert early.status_code == 409 and early.json()["code"] == "not_armed"
    proposal.armed_at -= 1.0   # the dwell passes
    done = await client.post(f"/actions/{proposal.proposal_id}/commit", data={"session_id": "h1"}, headers={**PROXIED, "X-Crooks-Arm": nonce})
    assert done.status_code == 200 and done.json()["status"] == "verified", done.text
    assert done.json()["spoken"] == "Order 1930 cancelled."
    assert len(hooks.world.mutations) == 1
    # Arming a settled card is refused.
    assert (await client.post(f"/actions/{proposal.proposal_id}/arm", data={"session_id": "h1"}, headers=PROXIED)).status_code == 409


# --------------------------------------------------------------------------- council PASS B: the arm preflight, the identity check, the Gmail scope


async def test_a_hold_is_refused_at_the_arm_when_the_change_needs_a_scope_the_store_has_not_granted(client, monkeypatch):
    """The tablet never says "armed" about a tap the Mac already knows it will refuse: the
    arm is judged by the proposal's own scope, as the tap would be."""
    from app.actions.models import Prepared
    from app.clients.shopify import REVIEWED_MUTATIONS, ReviewedMutation
    from app.tools import registry
    from app.tools.gate import Tier
    from app.tools.registry import ToolSpec, WriteSpec

    configure(client)
    client.store.scopes = {"read_orders", "write_orders"}
    client.store._scopes = None
    monkeypatch.setitem(REVIEWED_MUTATIONS, "probe_fulfil", ReviewedMutation(name="probe_fulfil", document="mutation X { x }", variables={}, scope="write_merchant_managed_fulfillment_orders"))

    async def prepare(order_id: str) -> Prepared:
        return Prepared(execution={"order_id": order_id}, before={}, expected_after={}, entity_ref=order_id, entity_label="#1930", summary={"read_back": "ship"})

    async def never(*a, **k):
        raise AssertionError("never runs")

    spec = ToolSpec(name="shopify_fulfil_probe", description="d", input_schema={"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}, tier=Tier.RED, handler=prepare,
                    issued_id_args=("order_id",), write=WriteSpec(operation="fulfillment_probe", entity_kind="order", entity_arg="order_id", mutation="probe_fulfil", observe=never, execute=never, present=lambda p: {}, op_class="irreversible"))
    monkeypatch.setitem(registry._REGISTRY, "shopify_fulfil_probe", spec)
    session = client.runtime.sessions.get_or_create("a1")
    session.issue(ORDER)
    session.epoch = max(session.epoch, 1)
    text = await dispatch("shopify_fulfil_probe", {"order_id": ORDER}, session=session, timeout_s=5)
    assert text.startswith("PROPOSED")
    proposal = session.proposals[-1]
    assert proposal.interaction == "hold_to_arm"
    armed = await client.post(f"/actions/{proposal.proposal_id}/arm", data={"session_id": "a1"}, headers=PROXIED)
    assert armed.status_code == 403 and armed.json()["code"] == "scope_missing", armed.text
    assert "write_merchant_managed_fulfillment_orders" in armed.json()["detail"]
    assert not proposal.arm_nonce and proposal.status.value == "PENDING"
    # A note, needing only write_orders, arms as before.
    note = await staged(client, session_id="a1")
    assert note.interaction == "tap_commit"
    assert (await commit(client, note.proposal_id, session_id="a1")).status_code == 200


async def test_a_login_header_tailscale_does_not_vouch_for_applies_nothing(client, monkeypatch):
    """The header is a claim. Before a change is applied the forwarded address is put to
    `tailscale whois`; a different holder, or no answer, refuses the tap — and the arm."""
    from app import identity

    configure(client)
    client.runtime.settings = client.runtime.settings.model_copy(update={"tailscale_verify": True})
    monkeypatch.setattr(identity, "cli_path", lambda configured="": "/usr/bin/tailscale")
    # The connection itself came from tailscaled, from another device (F-05B's half of the
    # check, tested on its own in tests/test_proxy_identity.py); the question here is whose.
    identity.bind_peer_check(lambda client_, server: (True, "opened by tailscaled"))
    identity.bind_self_check(lambda address: False)
    holders = {"100.64.0.9": "intruder@example.com"}
    identity.bind_runner(lambda cli, address: {"UserProfile": {"LoginName": holders.get(address, "")}})
    try:
        proposal = await staged(client)
        response = await commit(client, proposal.proposal_id)
        assert response.status_code == 403 and response.json()["code"] == "identity_unverified", response.text
        assert "belongs to a different login" in response.json()["detail"]
        assert response.json()["spoken"] == "I couldn't confirm which device this is with Tailscale, so I can't apply that."
        assert client.store.mutations == [] and proposal.status.value == "PENDING"
        assert (await client.post(f"/actions/{proposal.proposal_id}/arm", data={"session_id": "s1"}, headers=PROXIED)).status_code == 403
        # Nor may it read the card back: a device Tailscale does not vouch for is refused at the
        # door, before any route, with the same code and line (round 6: every route is the owner's).
        state = await client.get(f"/actions/{proposal.proposal_id}?session_id=s1", headers=PROXIED)
        assert state.status_code == 403 and state.json()["code"] == "identity_unverified"
        assert state.json()["spoken"] == "I couldn't confirm which device this is with Tailscale, so I can't apply that."
        # Tailscale names the login on the header: the same tap applies.
        holders["100.64.0.9"] = OWNER
        identity.bind_runner(lambda cli, address: {"UserProfile": {"LoginName": holders.get(address, "")}})
        response = await commit(client, proposal.proposal_id)
        assert response.status_code == 200 and response.json()["status"] == "verified", response.text
        assert proposal.caller == OWNER
    finally:
        identity.bind_runner(None)
        identity.bind_peer_check(None)
        identity.bind_self_check(None)


async def test_a_gmail_change_the_credential_does_not_allow_is_refused_by_name(client, monkeypatch):
    """An email change is judged by the Gmail credential's own scopes, read back from Google,
    never by the Shopify scopes; the refusal names Gmail and the card says which permission."""
    from app.clients.gmail import SCOPE_READONLY, ScopeReport
    from app.tools import gmail_writes  # noqa: F401 — registers the Gmail writes

    configure(client)
    monkeypatch.setattr(client.runtime.gmail, "scopes", lambda fresh=False: ScopeReport(frozenset({SCOPE_READONLY}), "google", 1e12))
    status = await client.runtime.write_status("gmail_send_reply")
    assert not status.ready and status.code == "gmail_scope_missing" and "gmail" in status.detail.lower() and "send" in status.detail.lower()
    assert (await client.runtime.write_status("gmail_draft_reply_undo")).code == "gmail_scope_missing", "an undo is judged as the change it reverses"
    assert (await client.runtime.write_status("order_note_append")).ready, "Shopify changes are not held by a Gmail scope"
    health = (await client.get("/health?fresh=1")).json()
    assert health["capabilities"]["gmail_send_reply"]["state"] == "blocked" and health["capabilities"]["order_note_append"]["state"] == "ready"
    monkeypatch.setattr(client.runtime.gmail, "scopes", lambda fresh=False: ScopeReport(frozenset({"https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/gmail.compose"}), "google", 1e12))
    assert (await client.runtime.write_status("gmail_send_reply")).ready


async def test_the_spoken_refusal_for_a_missing_scope_does_not_name_a_scope_the_change_does_not_need(client):
    """The words say the store has not granted what this change needs and point at the
    card, which carries the Mac's detail; they never claim every change needs write orders."""
    from app.routes.actions import SPOKEN_REFUSALS

    assert SPOKEN_REFUSALS["scope_missing"] == "The store hasn't granted the permission this change needs; the card says which."
    assert "gmail" in SPOKEN_REFUSALS["gmail_scope_missing"].lower()
    assert "Tailscale" in SPOKEN_REFUSALS["identity_unverified"]
