"""The engine's new hooks, proved on a stand-in write before any real one uses them: a
change proven by predicate rather than equality; a change Shopify finishes later; a refusal
Shopify phrases as a precondition; and the client that never sends a change twice."""

from __future__ import annotations

import asyncio

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine, PreconditionFailed
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus, Observed, Prepared
from app.clients.shopify import ShopifyError
from app.session.models import Session
from app.tools import registry
from app.tools.dispatch import dispatch
from app.tools.gate import Tier
from app.tools.registry import WriteSpec, tool

# The admitted owner calling tools directly, as a request the door let through would: every tool
# call here is his (the 2026-09-27 deploy review, round 8, F-A2-FIXTURE). Production's default,
# and every test's that does not say this, is no authority at all.
pytestmark = pytest.mark.usefixtures("owner_asking")

ORDER = "gid://shopify/Order/1938"


class World:
    """An entity Shopify would finish cancelling later: `cancelled` flips only when the job
    runs, and the refund lands after that, or not at all."""

    def __init__(self) -> None:
        self.cancelled = False
        self.refunded = 0.0
        self.job_done = False
        self.mutations: list[dict] = []
        self.refuse_code: str | None = None
        self.lose_answer = False
        self.refund_lands = True
        self.observes = 0

    def state(self) -> dict:
        return {"cancelled": self.cancelled, "refunded": self.refunded}


world = World()


async def observe(execution):
    world.observes += 1
    return Observed(fingerprint=dict(world.state()), entity={"order_id": ORDER, "cancelled": world.cancelled})


async def execute(execution):
    world.mutations.append(dict(execution))
    if world.refuse_code:
        raise PreconditionFailed(world.refuse_code)
    world.job_done = False
    if world.lose_answer:
        raise ShopifyError("timed out")
    return {"job_id": "gid://shopify/Job/1", "customer_email": "must-not-be-kept@example.com"}


async def settle(execution, sent):
    # The job runs now: the cancel lands, then the refund if it will.
    world.cancelled = True
    if world.refund_lands:
        world.refunded = float(execution["refund"])
    world.job_done = True


def verify(before, observed, execution):
    if not observed.get("cancelled"):
        return False, ""
    if float(execution["refund"]) > 0 and observed.get("refunded", 0) < float(execution["refund"]):
        return True, "The refund isn't showing yet; check the order."
    return True, ""


def present(proposal):
    return {"title": "Cancel order", "summary": "", "detail": "", "confirm_label": "Hold, then drag", "facts": [{"label": "Refund", "value": "£60.00"}]}


@tool(
    name="mock_cancel_probe",
    description="a stand-in for a change Shopify finishes later",
    input_schema={"type": "object", "properties": {"order_id": {"type": "string"}, "refund": {"type": "string", "maxLength": 12}}, "required": ["order_id"]},
    tier=Tier.RED,
    issued_id_args=("order_id",),
    write=WriteSpec(
        operation="cancel_probe", entity_kind="order", entity_arg="order_id", mutation="order_note_set",
        observe=observe, execute=execute, present=present, op_class="money",
        verify=verify, settle=settle,
        spoken_success="Order {label} cancelled.", spoken_failure="I couldn't confirm that change.",
        spoken_stale="The order changed since this was prepared. Nothing was sent.",
    ),
)
async def mock_cancel_probe(order_id: str, refund: str = "60.00") -> Prepared:
    if world.cancelled:
        raise registry.ToolError("Already cancelled.")
    return Prepared(execution={"order_id": order_id, "refund": refund}, before=dict(world.state()), expected_after={"cancelled": True},
                    entity_ref=order_id, entity_label="#1938", summary={"read_back": "cancel and refund sixty pounds"})


@pytest.fixture(autouse=True)
def fresh_world():
    global world
    world = World()
    yield


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def clock():
    return Clock()


@pytest.fixture()
def engine(monkeypatch, clock):
    e = ActionEngine(ledger=NullLedger(), clock=clock)
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


async def hold(engine, clock, proposal, *, for_s: float = 1.2) -> str:
    """The owner's hold, as the Mac sees it: armed, then the dwell passes."""
    armed, code = engine.arm(proposal.proposal_id, "e1")
    assert code == "" and armed is proposal and proposal.arm_nonce
    clock.now += for_s
    return proposal.arm_nonce


async def commit(engine, clock, proposal, *, nonce: str | None = None, session: str = "e1"):
    token = await hold(engine, clock, proposal) if nonce is None else nonce
    return await engine.commit(proposal.proposal_id, session, caller="o", spec_lookup=lookup, nonce=token)


@pytest.fixture()
def session():
    s = Session(session_id="e1")
    s.issue(ORDER)
    s.epoch = 1
    return s


def lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def stage(session):
    text = await dispatch("mock_cancel_probe", {"order_id": ORDER}, session=session, timeout_s=5)
    return text, session.proposals[-1]


# --------------------------------------------------------------------------- the grammar


async def test_a_red_money_change_is_a_hold_and_a_drag_and_the_model_is_told_so(session, engine):
    text, proposal = await stage(session)
    assert proposal.risk == "RED" and proposal.interaction == "hold_drag_target"
    assert "dragging the handle onto the target applies it" in text and "It has NOT happened" in text
    assert "cancel and refund sixty pounds" in text
    assert "tapping" not in text


def test_the_gesture_table_is_total_and_only_ever_stricter():
    from app.actions.grammar import KINDS, gesture_for, words_for

    assert gesture_for("AMBER", "reversible") == "tap_commit"
    assert gesture_for("AMBER", "irreversible") == "swipe_commit"
    assert gesture_for("RED", "reversible") == "hold_to_arm" and gesture_for("RED", "irreversible") == "hold_to_arm"
    assert gesture_for("RED", "money") == "hold_drag_target"
    assert gesture_for("GREEN", "reversible") == "hold_drag_target" and gesture_for("RED", "nonsense") == "hold_drag_target"
    for kind in KINDS:
        assert {"label", "footer", "verb", "affirmation"} <= set(words_for(kind))


# --------------------------------------------------------------------------- proof by predicate


async def test_a_change_shopify_finishes_later_is_proven_by_predicate_and_speaks_its_caveat(session, engine, clock):
    _, proposal = await stage(session)
    world.refund_lands = False
    result = await commit(engine, clock, proposal)
    assert result.code == "verified" and proposal.status is ActionStatus.VERIFIED
    assert result.spoken == "Order 1938 cancelled. The refund isn't showing yet; check the order."
    assert proposal.note.startswith("The refund")
    assert proposal.sent == {"job_id": "gid://shopify/Job/1"}, "the answer keeps ids, never content"
    assert [e["event"] for e in engine.ledger.read()] == ["PROPOSED", "ARMED", "EXECUTING", "EXECUTED", "VERIFIED"]
    assert engine.ledger.read()[3]["job"] == "gid://shopify/Job/1"


async def test_when_the_refund_lands_the_success_line_has_no_caveat(session, engine, clock):
    _, proposal = await stage(session)
    result = await commit(engine, clock, proposal)
    assert result.code == "verified" and result.spoken == "Order 1938 cancelled." and proposal.note == ""


async def test_a_lost_answer_on_a_job_backed_change_is_never_written_off_as_nothing_changed(session, engine, clock):
    _, proposal = await stage(session)
    world.lose_answer = True

    async def never_finishes(execution, sent):
        return None   # the job cannot be found: nothing lands during the wait

    monkeypatch_settle = registry.get("mock_cancel_probe").write
    object.__setattr__(monkeypatch_settle, "settle", never_finishes)
    try:
        result = await commit(engine, clock, proposal)
    finally:
        object.__setattr__(monkeypatch_settle, "settle", settle)
    assert result.code == "unverified" and proposal.status is ActionStatus.UNVERIFIED
    assert "unchanged after an ambiguous send" in proposal.reason
    assert len(world.mutations) == 1
    again = await engine.commit(proposal.proposal_id, "e1", caller="o", spec_lookup=lookup)
    assert again.code == "unverified" and len(world.mutations) == 1


async def test_a_lost_answer_whose_job_ran_is_settled_by_looking_after_the_wait(session, engine, clock):
    _, proposal = await stage(session)
    world.lose_answer = True
    result = await commit(engine, clock, proposal)
    assert result.code == "verified" and world.cancelled is True and len(world.mutations) == 1


async def test_shopifys_own_precondition_refusal_is_stale_not_a_failure(session, engine, clock):
    _, proposal = await stage(session)
    world.refuse_code = "ORDER_NOT_CANCELLABLE"
    result = await commit(engine, clock, proposal)
    assert result.code == "stale" and proposal.status is ActionStatus.STALE
    assert result.spoken == "The order changed since this was prepared. Nothing was sent."
    assert engine.ledger.read()[-1]["event"] == "STALE"


async def test_the_card_carries_the_facts_and_the_gesture_words(session, engine):
    from app.presentation import present as present_ui
    from app.providers.base import ToolCall

    _, proposal = await stage(session)
    items = present_ui([ToolCall(name="mock_cancel_probe", args={}, ok=True, proposal_id=proposal.proposal_id)], session=session)
    card = items[0]["data"]
    assert card["risk"] == "red" and card["interaction"]["kind"] == "hold_drag_target"
    assert card["interaction"]["footer"].startswith("nothing happens until you hold")
    assert card["interaction"]["hold_ms"] == 900 and card["interaction"]["armed_after_ms"] == 650
    assert card["facts"] == [{"label": "Refund", "value": "£60.00", "tone": ""}]


async def test_two_holds_at_once_send_one_change(session, engine, clock):
    _, proposal = await stage(session)
    token = await hold(engine, clock, proposal)
    a, b = await asyncio.gather(
        engine.commit(proposal.proposal_id, "e1", caller="o", spec_lookup=lookup, nonce=token),
        engine.commit(proposal.proposal_id, "e1", caller="o", spec_lookup=lookup, nonce=token),
    )
    assert sorted([a.code, b.code]) == ["already_executed", "verified"] and len(world.mutations) == 1


# --------------------------------------------------------------------------- the hold is a server fact


async def test_a_hold_kind_cannot_be_committed_without_its_hold(session, engine, clock):
    _, proposal = await stage(session)
    for token in ("", "made-up"):
        result = await engine.commit(proposal.proposal_id, "e1", caller="o", spec_lookup=lookup, nonce=token)
        assert result.code == "not_armed" and proposal.status is ActionStatus.PENDING and world.mutations == []
    # Armed, but tapped before the dwell: not yet.
    armed, code = engine.arm(proposal.proposal_id, "e1")
    assert code == ""
    clock.now += 0.3
    assert (await engine.commit(proposal.proposal_id, "e1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)).code == "not_armed"
    # Armed and left: the arming lapses.
    clock.now += 30
    assert (await engine.commit(proposal.proposal_id, "e1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)).code == "not_armed"
    assert world.mutations == [] and proposal.status is ActionStatus.PENDING
    # A fresh hold, and the dwell: applied. The old token is worthless.
    old = proposal.arm_nonce
    engine.arm(proposal.proposal_id, "e1")
    clock.now += 1.0
    assert (await engine.commit(proposal.proposal_id, "e1", caller="o", spec_lookup=lookup, nonce=old)).code == "not_armed"
    assert (await engine.commit(proposal.proposal_id, "e1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)).code == "verified"
    assert len(world.mutations) == 1


async def test_a_tap_kind_needs_no_arming_and_arming_a_settled_card_is_refused(session, engine, clock):
    from app.actions.engine import ActionEngine as _E  # noqa: F401 — the note stays a tap
    from app.tools import shopify_tools
    from tests.test_actions import ORDER as NOTE_ORDER
    from tests.test_actions import FakeStore

    store = FakeStore(note="")
    shopify_tools.bind(store)
    session.issue(NOTE_ORDER)
    await dispatch("shopify_order_note_append", {"order_id": NOTE_ORDER, "note": "hi"}, session=session, timeout_s=5)
    note = session.proposals[-1]
    assert note.interaction == "tap_commit"
    result = await engine.commit(note.proposal_id, "e1", caller="o", spec_lookup=lookup)
    assert result.code == "verified"
    settled, code = engine.arm(note.proposal_id, "e1")
    assert settled is note and code == "verified"
    assert engine.arm("prop_nope", "e1") == (None, "unknown")


# --------------------------------------------------------------------------- the client never sends twice


def test_a_redacted_field_inside_a_mutation_that_ran_is_not_a_refusal_and_is_not_resent(monkeypatch):
    """A 200 whose root came back — with a protected field inside it nulled by ACCESS_DENIED —
    is a change that RAN. It is never sent again, whatever the token's scopes."""
    from app.clients.shopify import (
        REVIEWED_MUTATIONS,
        ReviewedMutation,
        ShopifyClient,
        ShopifyScopeRefused,
    )

    monkeypatch.setitem(REVIEWED_MUTATIONS, "probe_refund", ReviewedMutation(
        name="probe_refund", document="mutation P($id: ID!) { refundCreate(input: {orderId: $id}) { refund { id } userErrors { message } } }",
        variables={"id": str}, scope="write_orders", idempotent=False, root="refundCreate",
    ))
    client = ShopifyClient("x.myshopify.com", "2025-07")
    client._token = type("T", (), {"value": "tok", "fresh": True, "expires_in": 1})()
    posts: list[dict] = []

    class Response:
        status_code = 200
        text = ""

        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    ran = {"data": {"refundCreate": {"refund": {"id": "gid://shopify/Refund/1"}, "userErrors": []}},
           "errors": [{"message": "Access denied for phone field", "extensions": {"code": "ACCESS_DENIED"}}]}
    refused = {"data": {"refundCreate": None}, "errors": [{"message": "Access denied", "extensions": {"code": "ACCESS_DENIED"}}]}

    class Http:
        is_closed = False

        def __init__(self, answers):
            self.answers = list(answers)

        async def post(self, url, **kwargs):
            posts.append(kwargs["json"])
            return Response(self.answers.pop(0))

    async def run(answers, expect_refused: bool):
        posts.clear()
        client._http = Http(answers)
        client._token = type("T", (), {"value": "tok", "fresh": True, "expires_in": 1})()
        if expect_refused:
            with pytest.raises(ShopifyScopeRefused):
                await client.mutate("probe_refund", {"id": ORDER})
        else:
            return await client.mutate("probe_refund", {"id": ORDER})

    payload = asyncio.run(run([ran, ran], expect_refused=False))
    assert len(posts) == 1 and payload["data"]["refundCreate"]["refund"]["id"].endswith("/1")
    # A refusal (the root came back null) of a non-idempotent change is reported, not retried.
    asyncio.run(run([refused, ran], expect_refused=True))
    assert len(posts) == 1
    # The idempotent note may be retried once after a proven refusal — and only then.
    note_ran = {"data": {"orderUpdate": {"order": {"id": ORDER, "name": "#1", "note": "x"}, "userErrors": []}}}
    note_refused = {"data": {"orderUpdate": None}, "errors": [{"message": "Access denied", "extensions": {"code": "ACCESS_DENIED"}}]}
    posts.clear()
    client._http = Http([note_refused, note_ran])
    client._token = type("T", (), {"value": "tok", "fresh": True, "expires_in": 1})()

    async def mint():
        return "tok2"

    client._access_token = mint  # type: ignore[method-assign]
    asyncio.run(client.mutate("order_note_set", {"id": ORDER, "note": "x"}))
    assert len(posts) == 2


def test_every_flavour_of_user_error_is_read_and_a_precondition_code_is_typed():
    from app.clients.shopify import _collect_user_errors

    found = _collect_user_errors({"orderCancel": {"job": None, "orderCancelUserErrors": [{"field": ["orderId"], "message": "Order cannot be cancelled", "code": "ORDER_NOT_CANCELLABLE"}]}})
    assert found == [{"message": "Order cannot be cancelled", "code": "ORDER_NOT_CANCELLABLE", "field": ["orderId"]}]
    assert _collect_user_errors({"inventoryAdjustQuantities": {"userErrors": [{"message": "stale", "code": "CHANGE_FROM_QUANTITY_STALE"}]}})[0]["code"] == "CHANGE_FROM_QUANTITY_STALE"
    assert _collect_user_errors({"data": {"x": {"nested": {"userErrors": []}}}}) == []


def test_a_precondition_user_error_arrives_typed(monkeypatch):
    from app.clients.shopify import ShopifyClient, ShopifyPreconditionFailed

    client = ShopifyClient("x.myshopify.com", "2025-07")

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {"data": {"orderCancel": {"job": None, "orderCancelUserErrors": [{"message": "Order cannot be cancelled", "code": "ORDER_NOT_CANCELLABLE"}]}}}

    class Http:
        is_closed = False

        async def post(self, url, **kwargs):
            return Response()

    client._http = Http()
    client._token = type("T", (), {"value": "tok", "fresh": True, "expires_in": 1})()

    async def run():
        with pytest.raises(ShopifyPreconditionFailed, match="cannot be cancelled"):
            await client._post("query { x }", {}, mutation=True, root="orderCancel")

    asyncio.run(run())
