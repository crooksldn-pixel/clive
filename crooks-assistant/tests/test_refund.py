"""Refunds: priced by Shopify, capped at what the store can still refund, allocated across
the tenders it suggests, restocked at the one location, proven by the refunded total moving
by exactly the amount. The store is a fake with one card tender and one gift card."""

from __future__ import annotations

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.clients.shopify import REVIEWED_MUTATIONS, ShopifyError, refund_input_ok
from app.session.models import Session
from app.tools import registry, shopify_tools, shopify_writes
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.test_actions import ORDER, FakeStore

# The admitted owner calling tools directly, as a request the door let through would: every tool
# call here is his (the 2026-09-27 deploy review, round 8, F-A2-FIXTURE). Production's default,
# and every test's that does not say this, is no authority at all.
pytestmark = pytest.mark.usefixtures("owner_asking")

TOOL = "shopify_refund_create"
LINE = "gid://shopify/LineItem/1"
LINE2 = "gid://shopify/LineItem/2"


class Policy:
    refund_notify = True


class RefundStore(FakeStore):
    def __init__(self) -> None:
        super().__init__(note="")
        self.total = 65.0          # 60 of items + 5 shipping
        self.refunded = 0.0
        self.card_max = 65.0
        self.locations = [{"id": "gid://shopify/Location/1", "name": "Studio", "isActive": True, "fulfillsOnlineOrders": True}]
        self.suggested_calls: list[dict] = []
        self.refund_lands = True

    def _order(self) -> dict:
        node = super()._order()
        node.update({
            "displayFinancialStatus": "REFUNDED" if self.refunded >= self.total else ("PARTIALLY_REFUNDED" if self.refunded else "PAID"),
            "refundable": self.refunded < self.total,
            "currentTotalPriceSet": {"shopMoney": {"amount": f"{self.total:.2f}", "currencyCode": "GBP"}},
            "totalRefundedSet": {"shopMoney": {"amount": f"{self.refunded:.2f}", "currencyCode": "GBP"}},
            "lineItems": {"edges": [
                {"node": {"id": LINE, "title": "Yard Jeans", "variantTitle": "M", "quantity": 1, "refundableQuantity": 1, "unfulfilledQuantity": 1,
                          "originalTotalSet": {"shopMoney": {"amount": "40.00", "currencyCode": "GBP"}}}},
                {"node": {"id": LINE2, "title": "Cap", "variantTitle": None, "quantity": 2, "refundableQuantity": 2, "unfulfilledQuantity": 2,
                          "originalTotalSet": {"shopMoney": {"amount": "20.00", "currencyCode": "GBP"}}}},
            ]},
        })
        return node

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        variables = variables or {}
        if "CrooksLocations" in query:
            return {"data": {"locations": {"edges": [{"node": n} for n in self.locations]}}}
        if "CrooksSuggestedRefund" in query:
            self.suggested_calls.append(dict(variables))
            lines = variables.get("refundLineItems") or []
            prices = {LINE: 40.0, LINE2: 10.0}
            subtotal = sum(prices[line["lineItemId"]] * line["quantity"] for line in lines)
            shipping = 5.0 if variables.get("shippingFull") else float(variables.get("shippingAmount") or 0)
            amount = (self.total - self.refunded) if variables.get("full") else subtotal + shipping
            maximum = self.total - self.refunded
            money = lambda v: {"shopMoney": {"amount": f"{v:.2f}", "currencyCode": "GBP"}}  # noqa: E731
            return {"data": {"order": {"id": ORDER, "name": "#1930", "suggestedRefund": {
                "amountSet": money(amount), "subtotalSet": money(subtotal), "totalTaxSet": money(0), "maximumRefundableSet": money(maximum),
                "shipping": {"amountSet": money(shipping), "maximumRefundableSet": money(5.0)},
                "suggestedTransactions": [
                    {"amountSet": money(min(amount, 10.0)), "maximumRefundableSet": money(10.0), "gateway": "gift_card", "kind": "SUGGESTED_REFUND", "parentTransaction": {"id": "gid://shopify/OrderTransaction/9"}},
                    {"amountSet": money(min(amount, self.card_max)), "maximumRefundableSet": money(self.card_max), "gateway": "shopify_payments", "kind": "SUGGESTED_REFUND", "parentTransaction": {"id": "gid://shopify/OrderTransaction/1"}},
                ],
                "refundLineItems": [{"quantity": line["quantity"], "lineItem": {"id": line["lineItemId"], "title": "x"}, "priceSet": money(prices[line["lineItemId"]])} for line in lines],
            }}}}
        return await super().graphql(query, variables)

    async def mutate(self, name: str, variables: dict) -> dict:
        reviewed = REVIEWED_MUTATIONS[name]
        assert set(variables) == set(reviewed.variables)
        assert refund_input_ok(variables["input"]), "the reviewed shape, or nothing"
        self.mutations.append((name, dict(variables)))
        if self.fail_mutation:
            raise ShopifyError("Shopify refused it.")
        amount = sum(float(t["amount"]) for t in variables["input"]["transactions"])
        if self.refund_lands:
            self.refunded = round(self.refunded + amount, 2)
        if self.lose_answer:
            raise ShopifyError("timed out")
        return {"data": {"refundCreate": {"refund": {"id": "gid://shopify/Refund/1", "createdAt": "now", "totalRefundedSet": {"shopMoney": {"amount": f"{amount:.2f}", "currencyCode": "GBP"}}}, "userErrors": []}}}


@pytest.fixture()
def store():
    s = RefundStore()
    shopify_tools.bind(s)
    shopify_writes.bind_policy(lambda: Policy())
    return s


@pytest.fixture()
def engine(monkeypatch):
    e = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


@pytest.fixture()
def session():
    s = Session(session_id="r1")
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


async def commit(engine, proposal):
    armed, code = engine.arm(proposal.proposal_id, "r1")
    assert code == ""
    proposal.armed_at -= 1.0
    return await engine.commit(proposal.proposal_id, "r1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)


def test_refund_is_red_money_and_its_input_shape_is_held_by_the_client():
    spec = registry.get(TOOL)
    assert spec.tier is Tier.RED and spec.write.kind == "money" and not spec.write.reversible
    assert not REVIEWED_MUTATIONS["refund_create"].idempotent and REVIEWED_MUTATIONS["refund_create"].root == "refundCreate"
    assert classify(TOOL, {"order_id": ORDER, "amount": "20.00"}, issued_ids={ORDER}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify(TOOL, {"order_id": ORDER, "amount": "20.00"}).disposition is Disposition.DENY
    good = {"orderId": ORDER, "notify": True, "currency": "GBP", "transactions": [{"orderId": ORDER, "gateway": "shopify_payments", "kind": "REFUND", "amount": "20.00", "parentId": "gid://shopify/OrderTransaction/1"}]}
    assert refund_input_ok(good)
    for bad in (
        {**good, "extra": 1}, {**good, "transactions": []}, {**good, "transactions": [{**good["transactions"][0], "kind": "SALE"}]},
        {**good, "transactions": [{**good["transactions"][0], "amount": "20.000"}]}, {**good, "currency": "gbp"},
        {**good, "refundLineItems": [{"lineItemId": "x", "quantity": 1}]}, {**good, "refundLineItems": [{"lineItemId": LINE, "quantity": 0}]},
        {**good, "refundLineItems": [{"lineItemId": LINE, "quantity": 1, "restockType": "MAYBE"}]}, {**good, "shipping": {}}, {**good, "shipping": {"amount": "abc"}},
        {**good, "orderId": "gid://shopify/Order/x"}, {},
    ):
        assert not refund_input_ok(bad), bad


async def test_a_plain_amount_is_priced_capped_and_goes_back_the_way_it_came(store, engine, session):
    text, proposal = await stage(session, amount="20")
    assert text.startswith("PROPOSED") and "refund twenty pounds to Daniel Stub on order 1930" in text and "emailing the customer" in text
    ex = dict(proposal.execution)
    assert ex["amount"] == "20.00" and ex["input"]["transactions"] == [
        {"orderId": ORDER, "gateway": "shopify_payments", "kind": "REFUND", "amount": "20.00", "parentId": "gid://shopify/OrderTransaction/1"}
    ], "never the gift card"
    assert "refundLineItems" not in ex["input"] and "shipping" not in ex["input"] and ex["input"]["notify"] is True
    assert store.suggested_calls[-1]["full"] is True
    assert proposal.before == {"refunded": "0.00", "financial": "PAID"} and proposal.risk == "RED" and proposal.interaction == "hold_drag_target"
    words = registry.get(TOOL).write.present(proposal)
    facts = {f["label"]: f["value"] for f in words["facts"]}
    assert facts["Amount"] == "£20.00 to the original payment" and facts["Of"] == "£65.00 paid · £45.00 remains refundable after" and facts["Items"] == "none · goodwill"
    assert words["target"] == "Drop to refund £20.00"
    assert store.mutations == []


async def test_items_are_priced_by_shopify_and_restocked_at_the_one_location(store, engine, session):
    text, proposal = await stage(session, items=[{"line_item_id": LINE, "quantity": 1}, {"line_item_id": LINE2, "quantity": 2}], restock="return", shipping="full", reason="Faulty zip")
    assert "refund sixty-five pounds to Daniel Stub on order 1930 for Yard Jeans M, Cap ×2, shipping in full, restocking" in text
    ex = dict(proposal.execution)
    assert ex["amount"] == "65.00"
    assert ex["input"]["refundLineItems"] == [
        {"lineItemId": LINE, "quantity": 1, "restockType": "RETURN", "locationId": "gid://shopify/Location/1"},
        {"lineItemId": LINE2, "quantity": 2, "restockType": "RETURN", "locationId": "gid://shopify/Location/1"},
    ]
    assert ex["input"]["shipping"] == {"fullRefund": True} and ex["input"]["note"] == "Faulty zip"
    assert store.suggested_calls[-1]["refundLineItems"] == [{"lineItemId": LINE, "quantity": 1, "restockType": "RETURN"}, {"lineItemId": LINE2, "quantity": 2, "restockType": "RETURN"}]
    facts = {f["label"]: f["value"] for f in registry.get(TOOL).write.present(proposal)["facts"]}
    assert facts["Restock"] == "returned to stock at Studio" and facts["Shipping"] == "in full" and facts["Reason"] == "Faulty zip"


async def test_postage_alone_can_be_refunded(store, engine, session):
    text, proposal = await stage(session, shipping="3.95")
    assert "refund three pounds ninety-five to Daniel Stub on order 1930, shipping £3.95" in text or "refund three pounds ninety-five to Daniel Stub on order 1930, shipping" in text
    ex = dict(proposal.execution)
    assert ex["amount"] == "3.95" and ex["input"]["shipping"] == {"amount": "3.95"} and "refundLineItems" not in ex["input"]


@pytest.mark.parametrize("args,words", [
    ({"amount": "80"}, "Only £65.00 can still be refunded"),
    ({"amount": "0"}, "must be a number"),
    ({"amount": "abc"}, "must be a number"),
    ({"amount": "20", "items": [{"line_item_id": LINE, "quantity": 1}]}, "not both"),
    ({}, "Say what to refund"),
    ({"items": [{"line_item_id": "gid://shopify/LineItem/999", "quantity": 1}]}, "is not on order"),
    ({"items": [{"line_item_id": LINE, "quantity": 3}]}, "Only 1 of Yard Jeans"),
    ({"items": [{"line_item_id": LINE, "quantity": 1}], "restock": "maybe"}, "restock must be"),
])
async def test_what_cannot_be_refunded_is_refused_at_preparation(store, engine, session, args, words):
    text, proposal = await stage(session, **args)
    assert text.startswith("ERROR") and words in text and proposal is None and store.mutations == []


async def test_restock_needs_exactly_one_location(store, engine, session):
    store.locations.append({"id": "gid://shopify/Location/2", "name": "Warehouse", "isActive": True, "fulfillsOnlineOrders": True})
    text, proposal = await stage(session, items=[{"line_item_id": LINE, "quantity": 1}], restock="return")
    assert text.startswith("ERROR") and "no single location" in text
    text, proposal = await stage(session, items=[{"line_item_id": LINE, "quantity": 1}], restock="none")
    assert text.startswith("PROPOSED") and "locationId" not in dict(proposal.execution)["input"]["refundLineItems"][0]


async def test_an_amount_the_card_cannot_take_back_is_refused_rather_than_sent_to_a_gift_card(store, engine, session):
    store.card_max = 15.0
    text, proposal = await stage(session, amount="20")
    assert text.startswith("ERROR") and "cannot go back the way it was paid" in text and proposal is None


async def test_a_fully_refunded_order_has_nothing_left(store, engine, session):
    store.refunded = 65.0
    text, proposal = await stage(session, amount="5")
    assert text.startswith("ERROR") and "nothing left to refund" in text


async def test_the_hold_and_drag_refunds_once_and_the_total_proves_it(store, engine, session):
    _, proposal = await stage(session, amount="20")
    result = await commit(engine, proposal)
    assert result.code == "verified" and result.spoken == "Refunded £20.00 on order 1930."
    assert len(store.mutations) == 1 and store.refunded == 20.0
    assert proposal.after == {"refunded": "20.00", "financial": "PARTIALLY_REFUNDED"}
    assert proposal.entity and proposal.entity["money"]["refunded"] == "20.00 GBP"
    assert proposal.undo_id is None
    line = [e for e in engine.ledger.read() if e["event"] == "PROPOSED"][0]
    assert line["facts"] == {"amount": "20.00", "currency": "GBP", "lines": 0, "restock": "NO_RESTOCK", "shipping": False, "notify": True, "tenders": 1}
    again = await engine.commit(proposal.proposal_id, "r1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)
    assert again.code == "already_executed" and len(store.mutations) == 1


async def test_a_refund_that_did_not_move_the_total_is_not_success(store, engine, session):
    store.refund_lands = False
    _, proposal = await stage(session, amount="20")
    result = await commit(engine, proposal)
    assert result.code == "unverified" and proposal.status is ActionStatus.UNVERIFIED
    assert result.spoken.startswith("I couldn't confirm the refund")


async def test_a_refund_made_in_admin_meanwhile_is_not_sent_on_top(store, engine, session):
    _, proposal = await stage(session, amount="20")
    store.refunded = 30.0
    result = await commit(engine, proposal)
    assert result.code == "stale" and store.mutations == []


async def test_a_lost_answer_is_settled_by_the_total(store, engine, session):
    store.lose_answer = True
    _, proposal = await stage(session, amount="20")
    result = await commit(engine, proposal)
    assert result.code == "verified" and len(store.mutations) == 1 and store.refunded == 20.0


async def test_the_spoken_refund_line_and_the_card(store, engine, session):
    from app.presentation import present
    from app.providers.base import ToolCall
    from app.speech.speakable import to_speakable

    _, proposal = await stage(session, amount="20")
    card = present([ToolCall(name=TOOL, args={}, ok=True, proposal_id=proposal.proposal_id)], session=session)[0]["data"]
    assert card["title"] == "Refund" and card["interaction"]["kind"] == "hold_drag_target" and card["interaction"]["target"] == "Drop to refund £20.00"
    assert to_speakable("Refunded £20.00 on order 1930.") == "Refunded twenty pounds on order nineteen thirty."
