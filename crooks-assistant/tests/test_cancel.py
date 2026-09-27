"""Cancelling an order: RED, a hold and a drag, the money printed on the card, a job Shopify
finishes later, proven by re-reading. The store is a fake whose cancellation lands when its
job is looked at; nothing here reaches a network."""

from __future__ import annotations

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.clients.shopify import REVIEWED_MUTATIONS, ShopifyError
from app.session.models import Session
from app.tools import registry, shopify_tools, shopify_writes
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.test_actions import ORDER, FakeStore

# The admitted owner calling tools directly, as a request the door let through would: every tool
# call here is his (the 2026-09-27 deploy review, round 8, F-A2-FIXTURE). Production's default,
# and every test's that does not say this, is no authority at all.
pytestmark = pytest.mark.usefixtures("owner_asking")

TOOL = "shopify_order_cancel"


class Policy:
    cancel_refund = True
    cancel_restock = True
    cancel_notify = True


class CancelStore(FakeStore):
    """An order that cancels in a job. The job finishes on the second look, and the refund
    lands with it unless told otherwise."""

    def __init__(self) -> None:
        super().__init__(note="")
        self.cancelled_at: str | None = None
        self.refunded = 0.0
        self.fulfillment = "UNFULFILLED"
        self.financial = "PAID"
        self.job_polls = 0
        self.job_lands_after = 2
        self.refund_lands = True
        self.refuse_code: str | None = None
        self.no_job = False
        self.total = 60.0

    def _order(self) -> dict:
        node = super()._order()
        node.update({
            "cancelledAt": self.cancelled_at, "cancelReason": "CUSTOMER" if self.cancelled_at else None,
            "displayFulfillmentStatus": self.fulfillment, "displayFinancialStatus": "REFUNDED" if self.refunded >= self.total else self.financial,
            "fullyPaid": True,
            "currentTotalPriceSet": {"shopMoney": {"amount": f"{self.total:.2f}", "currencyCode": "GBP"}},
            "totalRefundedSet": {"shopMoney": {"amount": f"{self.refunded:.2f}", "currencyCode": "GBP"}},
            "totalOutstandingSet": {"shopMoney": {"amount": "0.00", "currencyCode": "GBP"}},
            "fullRefund": {"amountSet": {"shopMoney": {"amount": f"{self.total - self.refunded:.2f}", "currencyCode": "GBP"}},
                           "maximumRefundableSet": {"shopMoney": {"amount": f"{self.total - self.refunded:.2f}", "currencyCode": "GBP"}}},
            "lineItems": {"edges": [{"node": {"id": "gid://shopify/LineItem/1", "quantity": 2, "unfulfilledQuantity": 2 if self.fulfillment == "UNFULFILLED" else 0, "refundableQuantity": 2}}]},
        })
        return node

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        if "CrooksJob" in query:
            self.job_polls += 1
            if self.job_polls >= self.job_lands_after:
                self._land()
                return {"data": {"job": {"id": (variables or {}).get("id"), "done": True}}}
            return {"data": {"job": {"id": (variables or {}).get("id"), "done": False}}}
        return await super().graphql(query, variables)

    def _land(self) -> None:
        if self.cancelled_at is None:
            self.cancelled_at = "2026-09-09T12:00:00Z"
            if self.refund_lands:
                self.refunded = self.total

    async def mutate(self, name: str, variables: dict) -> dict:
        reviewed = REVIEWED_MUTATIONS[name]
        assert set(variables) == set(reviewed.variables), "the reviewed variable set, exactly"
        self.mutations.append((name, dict(variables)))
        if name != "order_cancel":
            return await super().mutate(name, variables)
        if self.refuse_code:
            from app.clients.shopify import ShopifyPreconditionFailed

            raise ShopifyPreconditionFailed(f"Order cannot be cancelled ({self.refuse_code})")
        if self.fail_mutation:
            raise ShopifyError("Shopify refused it.")
        if self.no_job:
            return {"data": {"orderCancel": {"job": None, "orderCancelUserErrors": []}}}
        if self.lose_answer:
            raise ShopifyError("timed out")
        return {"data": {"orderCancel": {"job": {"id": "gid://shopify/Job/abc", "done": False}, "orderCancelUserErrors": []}}}


@pytest.fixture()
def store():
    s = CancelStore()
    shopify_tools.bind(s)
    shopify_writes.bind_policy(lambda: Policy())
    return s


@pytest.fixture()
def engine(monkeypatch):
    e = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", e)
    monkeypatch.setattr(shopify_writes, "JOB_POLL_FIRST_S", 0.0)
    monkeypatch.setattr(shopify_writes, "JOB_POLL_MAX_S", 0.0)
    return e


@pytest.fixture()
def session():
    s = Session(session_id="c1")
    s.issue(ORDER)
    s.epoch = 1
    return s


def lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def stage(session, **args):
    text = await dispatch(TOOL, {"order_id": ORDER, **args}, session=session, timeout_s=5)
    return text, (session.proposals[-1] if session.proposals else None)


async def hold(engine, proposal) -> str:
    armed, code = engine.arm(proposal.proposal_id, "c1")
    assert code == ""
    proposal.armed_at -= 1.0   # the dwell passes
    return proposal.arm_nonce


async def commit(engine, proposal):
    token = await hold(engine, proposal)
    return await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=token)


# --------------------------------------------------------------------------- declaration


def test_cancel_is_red_money_and_its_mutation_is_reviewed_and_never_resent():
    spec = registry.get(TOOL)
    assert spec.tier is Tier.RED and spec.write.complete and spec.write.kind == "money" and not spec.write.reversible
    reviewed = REVIEWED_MUTATIONS["order_cancel"]
    assert reviewed.scope == "write_orders" and not reviewed.idempotent and reviewed.root == "orderCancel"
    assert reviewed.validate("refundMethod", {"originalPaymentMethodsRefund": True})
    assert not reviewed.validate("refundMethod", {"originalPaymentMethodsRefund": True, "storeCreditRefund": {}})
    assert classify(TOOL, {"order_id": ORDER}, issued_ids={ORDER}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify(TOOL, {"order_id": ORDER}).disposition is Disposition.DENY
    assert classify(TOOL, {"order_id": ORDER, "refund": False}, issued_ids={ORDER}).disposition is Disposition.DENY, "policy is not an argument"
    assert classify(TOOL, {"order_id": ORDER, "notify": True}, issued_ids={ORDER}).disposition is Disposition.DENY


# --------------------------------------------------------------------------- preparing


async def test_preparing_reads_the_order_prints_the_money_and_sends_nothing(store, engine, session):
    text, proposal = await stage(session)
    assert text.startswith("PROPOSED") and "holding the card and dragging the handle onto the target applies it" in text
    assert "cancel order 1930, refunding sixty pounds to the original payment, restocking, emailing the customer" in text
    assert store.mutations == [] and proposal.risk == "RED" and proposal.interaction == "hold_drag_target"
    assert dict(proposal.execution) == {
        "order_id": ORDER, "reason": "CUSTOMER", "staff_note": "", "refund": True, "restock": True, "notify": True,
        "expected_refund": "60.00", "currency": "GBP",
    }
    assert proposal.before == {"cancelled": False, "fulfillment": "UNFULFILLED", "financial": "PAID", "refunded": "0.00"}
    words = registry.get(TOOL).write.present(proposal)
    assert words["title"] == "Cancel order" and words["target"] == "Drop to cancel and refund £60.00"
    facts = {f["label"]: f["value"] for f in words["facts"]}
    assert facts == {"Customer": "Daniel Sear", "Items": "1 · £60.00, paid", "Refund": "£60.00 to the original payment", "Restock": "2 items", "Customer emailed": "yes", "Reason": "customer request"}
    line = engine.ledger.read()[-1]
    assert line["event"] == "PROPOSED" and line["facts"] == {"refund": True, "amount": "60.00", "currency": "GBP", "restock": 2, "notify": True, "reason": "CUSTOMER"}
    assert "Daniel" not in str(line)


async def test_policy_off_and_fraud_are_printed_not_hidden(store, engine, session):
    class Quiet(Policy):
        cancel_refund = False
        cancel_restock = False

    shopify_writes.bind_policy(lambda: Quiet())
    _, proposal = await stage(session, reason="fraud", staff_note="Card mismatch.")
    ex = dict(proposal.execution)
    assert ex["refund"] is False and ex["restock"] is False and ex["notify"] is False and ex["reason"] == "FRAUD" and ex["staff_note"] == "Card mismatch."
    facts = {f["label"]: f["value"] for f in registry.get(TOOL).write.present(proposal)["facts"]}
    assert facts["Refund"] == "not refunded (policy)" and facts["Restock"] == "no" and facts["Customer emailed"] == "no" and facts["Reason"] == "suspected fraud"
    assert registry.get(TOOL).write.present(proposal)["target"] == "Drop to cancel"


@pytest.mark.parametrize("state,words", [
    ({"cancelled_at": "2026-09-01T00:00:00Z"}, "already cancelled"),
    ({"fulfillment": "FULFILLED"}, "has shipped"),
    ({"fulfillment": "PARTIALLY_FULFILLED"}, "has shipped"),
])
async def test_an_order_that_cannot_be_cancelled_is_refused_at_preparation(store, engine, session, state, words):
    for k, v in state.items():
        setattr(store, k, v)
    text, proposal = await stage(session)
    assert text.startswith("ERROR") and words in text and proposal is None and store.mutations == []


async def test_a_reason_outside_the_list_is_refused(store, engine, session):
    text, proposal = await stage(session, reason="because")
    assert text.startswith("ERROR") and proposal is None and store.reads == 0


# --------------------------------------------------------------------------- applying


async def test_the_hold_and_drag_cancels_once_waits_for_the_job_and_proves_it(store, engine, session):
    _, proposal = await stage(session)
    result = await commit(engine, proposal)
    assert result.code == "verified" and result.spoken == "Order 1930 cancelled." and proposal.note == ""
    assert store.mutations == [("order_cancel", {"orderId": ORDER, "reason": "CUSTOMER", "refundMethod": {"originalPaymentMethodsRefund": True}, "restock": True, "notifyCustomer": True, "staffNote": ""})]
    assert store.job_polls == 2 and store.cancelled_at and store.refunded == 60.0
    assert proposal.sent == {"job_id": "gid://shopify/Job/abc", "done": False}
    assert proposal.after == {"cancelled": True, "fulfillment": "UNFULFILLED", "financial": "REFUNDED", "refunded": "60.00"}
    assert proposal.entity and proposal.entity["cancelled_at"], "the card shows the order as it now is"
    assert proposal.undo_id is None, "no undo for a cancellation"
    events = [e["event"] for e in engine.ledger.read()]
    assert events == ["PROPOSED", "ARMED", "EXECUTING", "EXECUTED", "VERIFIED"]
    again = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)
    assert again.code == "already_executed" and len(store.mutations) == 1


async def test_without_the_hold_nothing_is_sent(store, engine, session):
    _, proposal = await stage(session)
    result = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup)
    assert result.code == "not_armed" and store.mutations == [] and proposal.status is ActionStatus.PENDING


async def test_a_cancellation_whose_refund_has_not_landed_says_so(store, engine, session):
    store.refund_lands = False
    _, proposal = await stage(session)
    result = await commit(engine, proposal)
    assert result.code == "verified" and proposal.status is ActionStatus.VERIFIED
    assert result.spoken == "Order 1930 cancelled. The refund isn't showing yet; check the order."


async def test_shopify_refusing_the_cancellation_is_stale_and_sends_nothing_twice(store, engine, session):
    _, proposal = await stage(session)
    store.refuse_code = "ORDER_NOT_CANCELLABLE"
    result = await commit(engine, proposal)
    assert result.code == "stale" and proposal.status is ActionStatus.STALE and len(store.mutations) == 1
    assert result.spoken == "The order changed since this was prepared. Nothing was sent."


async def test_no_job_and_no_error_is_settled_by_looking_never_by_hoping(store, engine, session):
    store.no_job = True
    _, proposal = await stage(session)
    result = await commit(engine, proposal)
    # The re-read sees the order uncancelled after the wait: unverified — never "nothing changed".
    assert result.code == "unverified" and proposal.status is ActionStatus.UNVERIFIED
    assert result.spoken.startswith("I couldn't confirm the cancellation")


async def test_a_lost_answer_whose_job_ran_is_verified_after_the_wait(store, engine, session):
    store.lose_answer = True
    store.job_lands_after = 1
    _, proposal = await stage(session)

    async def looking(execution, sent):
        # No job id came back with the lost answer; Shopify cancels anyway.
        store._land()

    spec = registry.get(TOOL).write
    object.__setattr__(spec, "settle", looking)
    try:
        result = await commit(engine, proposal)
    finally:
        object.__setattr__(spec, "settle", shopify_writes._settle_cancel)
    assert result.code == "verified" and len(store.mutations) == 1


async def test_an_order_cancelled_in_admin_meanwhile_is_not_sent_again(store, engine, session):
    _, proposal = await stage(session)
    store.cancelled_at = "2026-09-09T11:00:00Z"
    result = await commit(engine, proposal)
    assert result.code == "stale" and store.mutations == []


async def test_the_card_carries_the_facts_the_gesture_and_the_consequence_on_the_target(store, engine, session):
    from app.presentation import present
    from app.providers.base import ToolCall

    _, proposal = await stage(session)
    card = present([ToolCall(name=TOOL, args={}, ok=True, proposal_id=proposal.proposal_id)], session=session)[0]["data"]
    assert card["risk"] == "red" and card["interaction"]["kind"] == "hold_drag_target"
    assert card["interaction"]["target"] == "Drop to cancel and refund £60.00"
    assert [f["label"] for f in card["facts"]] == ["Customer", "Items", "Refund", "Restock", "Customer emailed", "Reason"]
    assert card["facts"][2]["tone"] == "bad" and card["reversible"] is False


async def test_the_rail_offers_cancel_only_while_it_makes_sense(store):
    from app.actions.available import available_actions

    caps = {"order_cancel": {"state": "ready"}, "order_note_append": {"state": "ready"}}
    order = await shopify_tools.hydrator().order(ORDER, budget_s=0)
    assert "cancel" in [a["id"] for a in available_actions(order, caps) if a["enabled"]]
    store.cancelled_at = "2026-09-09T11:00:00Z"
    order = await shopify_tools.hydrator().order(ORDER, budget_s=0, fresh=True)
    assert [a["reason"] for a in available_actions(order, caps) if a["id"] == "cancel"] == ["already cancelled"]
