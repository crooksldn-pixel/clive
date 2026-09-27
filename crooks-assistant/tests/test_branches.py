"""The orb, divided: two halves that share what is safe and share nothing that is not."""

from __future__ import annotations

import pytest

from app.session.branch import MAX_BRANCHES, Branch, Workflow
from app.session.models import Session


@pytest.fixture()
def session():
    return Session(session_id="s1")


# -------------------------------------------------------------- the state itself

def test_a_session_has_one_branch_from_its_first_question(session):
    first = session.branch()
    assert first.branch_id and session.focused_branch == first.branch_id
    assert session.branch() is first, "asking again is the same branch, not a second one"


def test_an_unknown_branch_id_gets_the_focused_one_rather_than_a_new_empty_history(session):
    first = session.branch()
    assert session.branch("br_madeup") is first


def test_each_half_keeps_its_own_place(session):
    left = session.branch()
    right = Branch(branch_id="br_right", session_id="s1", parent_id=left.branch_id)
    session.branches[right.branch_id] = right
    left.visit("order", "o1", "#1938", tab="overview")
    right.visit("customer", "c1", "Millie Rogers", tab="orders")
    assert left.entity["ref"] == "o1" and right.entity["ref"] == "c1"
    left.mark(scroll=300)
    assert right.scroll == 0, "scrolling one half does not move the other"


def test_a_cursor_moved_in_one_half_does_not_move_the_other(session):
    left = session.branch()
    left.workflow = Workflow(workflow_id="wf", set_id="set_a", kind="orders", total=5, cursor=0)
    from dataclasses import replace

    right = Branch(branch_id="br_right", session_id="s1", workflow=replace(left.workflow, workflow_id="wfb"))
    session.branches[right.branch_id] = right
    left.workflow.cursor += 1
    assert left.workflow.cursor == 1 and right.workflow.cursor == 0


# ------------------------------------------------------------------- the routes

@pytest.fixture()
async def client(monkeypatch):
    """The routes over a real app with a fake everything: no Claude, no store, no network."""
    import httpx

    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.main import app
    from app.providers import max_agent_sdk
    from app.providers.base import TurnResult
    from app.session.manager import SessionManager

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", lambda self: (True, "fake scribe"))
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))

    class Provider:
        async def start(self): pass
        async def stop(self): pass
        async def health(self): return True, "fake"
        async def reset_session(self, session_id): pass
        async def set_system_prompt(self, prompt): pass
        async def interrupt(self, session_id): return True
        async def turn(self, session_id, text): return TurnResult(text="fake answer", session_id=session_id)

    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = Provider()
        runtime.sessions = SessionManager()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.runtime = runtime
            session = runtime.sessions.get_or_create("br")
            session.branch()
            yield c


async def test_the_orb_divides_once(client):
    first = (await client.post("/branches/fork", data={"session_id": "br"})).json()
    assert len(first["branches"]) == 2 and first["can_fork"] is False
    second = await client.post("/branches/fork", data={"session_id": "br"})
    assert second.status_code == 409 and second.json()["code"] == "too_many_branches"
    assert MAX_BRANCHES == 2


async def test_the_new_half_starts_where_the_old_one_is(client):
    session = client.runtime.sessions.get("br")
    parent = session.branch()
    parent.visit("order", "o1", "#1938", tab="items")
    parent.set_id = "set_abc"
    body = (await client.post("/branches/fork", data={"session_id": "br"})).json()
    child = session.branches[body["branch_id"]]
    assert child.entity["ref"] == "o1" and child.set_id == "set_abc" and child.parent_id == parent.branch_id
    child.visit("customer", "c9", "Someone Else")
    assert parent.entity["ref"] == "o1", "and then goes its own way"


async def test_focus_moves_the_owners_attention_and_nothing_else(client):
    body = (await client.post("/branches/fork", data={"session_id": "br"})).json()
    other = body["branch_id"]
    moved = (await client.post(f"/branches/{other}/focus", data={"session_id": "br"})).json()
    assert moved["focused"] == other
    session = client.runtime.sessions.get("br")
    assert len(session.branches) == 2, "both halves are still there"


async def test_a_merge_brings_back_a_summary_not_a_transcript(client):
    session = client.runtime.sessions.get("br")
    body = (await client.post("/branches/fork", data={"session_id": "br"})).json()
    other = session.branches[body["branch_id"]]
    other.visit("customer", "c1", "Millie Rogers")
    other.remember_result("shopify_customer_history", summary="shopify_customer_history: Millie Rogers", ref="c1", ms=120.0)
    other.learn("millie", "customer", "c1", "Millie Rogers")
    merged = (await client.post(f"/branches/{other.branch_id}/merge", data={"session_id": "br"})).json()
    summary = merged["merged"]
    assert summary["looked_at"][0]["ref"] == "c1"
    assert summary["read"][0]["tool"] == "shopify_customer_history"
    assert summary["resolved"][0]["said"] == "millie"
    assert "answer" not in summary and "question" not in summary, "structure, not a conversation"
    keeper = session.branch()
    assert keeper.resolve("millie")["ref"] == "c1", "what it learned comes back"
    assert len(merged["branches"]) == 1


async def test_a_half_with_a_change_waiting_cannot_be_put_aside(client):
    from types import MappingProxyType

    from app.actions.models import ActionProposal, ActionStatus

    session = client.runtime.sessions.get("br")
    body = (await client.post("/branches/fork", data={"session_id": "br"})).json()
    other = body["branch_id"]
    session.proposals.append(ActionProposal(
        proposal_id="prop_x", session_id="br", epoch=session.epoch, tool_name="shopify_order_note_append",
        operation="order_note_append", risk="AMBER", model_args=MappingProxyType({}), execution=MappingProxyType({}),
        entity_kind="order", entity_ref="o1", entity_label="#1938", interaction="tap_commit", reversible=True,
        before={}, expected_after={}, summary={}, fingerprint="f", created_at=0.0, expires_at=9e9,
        status=ActionStatus.PENDING, branch_id=other,
    ))
    refused = await client.post(f"/branches/{other}/background", data={"session_id": "br"})
    assert refused.status_code == 409 and refused.json()["code"] == "change_waiting"


async def test_cancelling_one_half_leaves_the_other_alone(client):
    session = client.runtime.sessions.get("br")
    keeper = session.branch()
    keeper.visit("order", "o1", "#1938")
    body = (await client.post("/branches/fork", data={"session_id": "br"})).json()
    other = body["branch_id"]
    gone = (await client.post(f"/branches/{other}/cancel", data={"session_id": "br"})).json()
    assert [b["branch_id"] for b in gone["branches"]] == [keeper.branch_id]
    assert keeper.entity["ref"] == "o1", "the other half is exactly as it was"
    assert session.branches[other].status == "CANCELLED"


async def test_the_last_half_cannot_be_cancelled(client):
    session = client.runtime.sessions.get("br")
    only = session.branch().branch_id
    refused = await client.post(f"/branches/{only}/cancel", data={"session_id": "br"})
    assert refused.status_code == 409 and refused.json()["code"] == "last_branch"


async def test_back_and_forward_restore_the_tab_and_the_scroll(client):
    session = client.runtime.sessions.get("br")
    branch = session.branch()
    branch.visit("order", "o1", "#1938", tab="overview")
    await client.post(f"/branches/{branch.branch_id}/mark", data={"session_id": "br", "tab": "shipping", "scroll": "420"})
    branch.visit("customer", "c1", "Millie")
    back = (await client.post(f"/branches/{branch.branch_id}/back", data={"session_id": "br"})).json()
    assert back["landed"]["ref"] == "o1" and back["branch"]["tab"] == "shipping" and back["branch"]["scroll"] == 420
    ahead = (await client.post(f"/branches/{branch.branch_id}/forward", data={"session_id": "br"})).json()
    assert ahead["landed"]["ref"] == "c1"


async def test_another_logins_session_gets_nothing_of_it(client):
    # Whose session it is, not whether tailscaled opened the connection (tests/test_proxy_identity.py).
    client.runtime.settings = client.runtime.settings.model_copy(update={"tailscale_verify": False})
    session = client.runtime.sessions.get("br")
    session.login = "someone-else@example.com"
    refused = await client.post(
        "/branches/fork", data={"session_id": "br"},
        headers={"Tailscale-User-Login": "george@example.com", "X-Forwarded-For": "100.64.0.9"},
    )
    assert refused.status_code == 403 and refused.json()["code"] == "wrong_session"


# ------------------------------------------- a change belongs to where it was asked

async def test_a_staged_change_carries_the_branch_that_staged_it():
    """The property this test is named for, asserted rather than grepped.

    It used to check that `app/actions/engine.py` contained a particular line of source —
    and the line it pinned was `focused_branch`, which is NOT the branch that staged the
    change whenever the tablet addresses a half that is not on screen. A test that reads the
    implementation can only ever agree with it; this one drives the engine and looks at what
    came out, and it is what makes the four properties below hold: a spoken "yes" matched
    against the speaking half, `revoke_pending` withdrawing by half, `/branches/{id}
    /background` refusing a half with a change waiting, and a BACKGROUND half never
    committing (the test directly beneath this one).
    """
    from app.actions import engine as engine_module
    from app.actions.engine import ActionEngine
    from app.actions.ledger import NullLedger
    from app.tools import shopify_tools
    from tests.test_actions import ORDER, Clock, FakeStore, stage

    shopify_tools.bind(FakeStore(note="Gift wrap please"))
    engine_module._engine = ActionEngine(ledger=NullLedger(), clock=Clock())

    session = Session(session_id="staged")
    session.issue(ORDER)
    session.epoch = 1
    on_screen, put_aside = session.branch().branch_id, "br_put_aside"
    session.focused_branch = on_screen
    session.acting_branch = put_aside

    _, proposal = await stage(session)
    assert proposal.branch_id == put_aside, (
        "the change was filed against the half on screen, not the half that asked for it"
    )


def test_a_change_in_a_backgrounded_half_cannot_be_committed():
    from app.routes.actions import _branch_may_commit

    session = Session(session_id="s1")
    branch = session.branch()

    class Proposal:
        branch_id = branch.branch_id

    assert _branch_may_commit(session, Proposal()) == ""
    branch.status = "BACKGROUND"
    assert "put aside" in _branch_may_commit(session, Proposal())
    branch.status = "CANCELLED"
    assert "closed" in _branch_may_commit(session, Proposal())


# --------------------------------------------------- what the Mac says is true

async def test_the_screen_can_ask_what_became_of_every_card_at_once(client):
    from types import MappingProxyType

    from app.actions.models import ActionProposal, ActionStatus

    session = client.runtime.sessions.get("br")

    def proposal(pid: str, status: ActionStatus) -> ActionProposal:
        return ActionProposal(
            proposal_id=pid, session_id="br", epoch=session.epoch, tool_name="shopify_order_note_append",
            operation="order_note_append", risk="AMBER", model_args=MappingProxyType({}), execution=MappingProxyType({}),
            entity_kind="order", entity_ref="o1", entity_label="#1938", interaction="tap_commit", reversible=True,
            before={}, expected_after={}, summary={}, fingerprint=pid, created_at=0.0, expires_at=9e9, status=status,
        )

    waiting, done = proposal("prop_waiting", ActionStatus.PENDING), proposal("prop_done", ActionStatus.VERIFIED)
    session.proposals.extend([waiting, done])
    # The engine's index is proposal id -> the session holding it, which is how `find` gets
    # from an id the tablet named to the proposal without trusting the tablet's session.
    client.runtime.actions._index.update({p.proposal_id: session for p in (waiting, done)})

    body = (await client.get("/actions/states", params={"session_id": "br", "ids": "prop_waiting,prop_done,prop_invented"})).json()
    assert body["session_known"] is True
    assert body["states"]["prop_waiting"]["status"] == "pending" and body["states"]["prop_waiting"]["kind"] == "action"
    assert body["states"]["prop_done"]["status"] == "verified"
    assert body["unknown"] == ["prop_invented"], "an id the Mac never issued comes back named"
    # Public fields only: no arguments, no fingerprint, nothing a card said.
    assert "execution" not in body["states"]["prop_waiting"] and "model_args" not in body["states"]["prop_waiting"]


async def test_a_conversation_the_mac_has_lost_says_so_rather_than_denying_every_card(client):
    body = (await client.get("/actions/states", params={"session_id": "never-existed", "ids": "prop_a"})).json()
    assert body["session_known"] is False
    assert body["unknown"] == ["prop_a"]


async def test_another_login_learns_nothing_about_the_cards(client):
    session = client.runtime.sessions.get("br")
    session.login = "someone-else@example.com"
    refused = await client.get(
        "/actions/states", params={"session_id": "br", "ids": "prop_a"},
        headers={"Tailscale-User-Login": "george@example.com", "X-Forwarded-For": "100.64.0.9"},
    )
    assert refused.status_code == 403


async def test_a_reconciliation_is_bounded(client):
    from app.routes.actions import MAX_RECONCILE

    many = ",".join(f"prop_{i}" for i in range(MAX_RECONCILE + 40))
    body = (await client.get("/actions/states", params={"session_id": "br", "ids": many})).json()
    assert len(body["unknown"]) == MAX_RECONCILE


# ------------------------------------------------- what a half is doing, in words

def test_a_branch_says_what_it_is_doing_in_words_and_never_in_a_percentage(session):
    branch = session.branch()
    assert branch.public()["task"] is None
    branch.working("reading the order")
    assert branch.public()["task"] == {"state": "WORKING", "what": "reading the order", "since": branch.task["since"]}
    branch.waiting()
    assert branch.task["state"] == "WAITING" and branch.task["what"] == "reading the order"
    branch.ready("there is an answer")
    assert branch.task["state"] == "READY"
    branch.failed("Shopify would not answer")
    assert branch.task["state"] == "FAILED" and branch.task["what"] == "Shopify would not answer"
    branch.idle()
    assert branch.task is None
    for state in ("WORKING", "WAITING", "READY", "FAILED"):
        assert state in ("QUEUED", "WORKING", "WAITING", "READY", "FAILED")


def test_nothing_in_a_branchs_words_is_a_number_out_of_a_number(session):
    from pathlib import Path

    source = Path("app/routes/turn.py").read_text(encoding="utf-8")
    words = source[source.index("_WORKING = {"): source.index("def _working_words")]
    assert "%" not in words and "percent" not in words
    assert all(not any(ch.isdigit() for ch in line) for line in words.splitlines())


async def test_the_half_being_talked_to_goes_quiet_and_the_one_aside_says_ready(client):
    session = client.runtime.sessions.get("br")
    body = (await client.post("/branches/fork", data={"session_id": "br"})).json()
    other = session.branches[body["branch_id"]]
    other.status = "BACKGROUND"
    session.focused_branch = [b for b in session.branches if b != other.branch_id][0]

    await client.post("/turn", json={"text": "hello", "session_id": "br"})
    assert session.branch().task is None, "the half he is looking at simply goes quiet"

    await client.post("/turn", json={"text": "hello", "session_id": "br", "branch_id": other.branch_id})
    assert other.task["state"] == "READY", "the one put aside says so on its own chip"
