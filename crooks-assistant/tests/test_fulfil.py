"""Marking an order shipped: RED, a hold then a tap, the fulfilment orders read on the Mac and
fulfilled exactly, the carrier named as Shopify names it, proven by what remains to ship. The
store is a fake with fulfilment orders of its own; nothing reaches a network."""

from __future__ import annotations

import copy

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.grammar import gesture_for, words_for
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

TOOL = "shopify_order_fulfil"
FO = "gid://shopify/FulfillmentOrder/1"
FO2 = "gid://shopify/FulfillmentOrder/2"
LINE = "gid://shopify/LineItem/1"
LINE2 = "gid://shopify/LineItem/2"
FOL = "gid://shopify/FulfillmentOrderLineItem/11"
FOL2 = "gid://shopify/FulfillmentOrderLineItem/12"
TRACKING = "AB123456785GB"


class Policy:
    carrier = "Royal Mail"
    fulfil_notify = False


class FulfilStore(FakeStore):
    """An order with one fulfilment order of two lines at one location. Fulfilling moves the
    remaining quantities and records a fulfilment with its tracking."""

    def __init__(self) -> None:
        super().__init__(note="")
        self.remaining = {FOL: 2, FOL2: 1}
        self.locations = {FO: ("gid://shopify/Location/1", "CROOKS HQ")}
        self.financial = "PAID"
        self.cancelled_at: str | None = None
        self.fulfillments: list[dict] = []
        self.split = False   # a second fulfilment order at another location
        self.refuse = False
        self.stuck = False   # Shopify keeps saying "partially fulfilled" after everything shipped

    def _fulfillment_orders(self) -> list[dict]:
        lines = [
            {"node": {"id": FOL, "remainingQuantity": self.remaining[FOL], "totalQuantity": 2, "lineItem": {"id": LINE, "title": "Blue Wash Yard Jeans", "variantTitle": "M"}}},
            {"node": {"id": FOL2, "remainingQuantity": self.remaining[FOL2], "totalQuantity": 1, "lineItem": {"id": LINE2, "title": "Convict Sweats", "variantTitle": "L"}}},
        ]
        status = "OPEN" if any(self.remaining.values()) else "CLOSED"
        orders = [{"node": {"id": FO, "status": status, "requestStatus": "UNSUBMITTED", "assignedLocation": {"name": "CROOKS HQ", "location": {"id": "gid://shopify/Location/1"}}, "lineItems": {"edges": lines}}}]
        if self.split:
            orders.append({"node": {"id": FO2, "status": "OPEN", "requestStatus": "UNSUBMITTED", "assignedLocation": {"name": "Pop-up", "location": {"id": "gid://shopify/Location/2"}}, "lineItems": {"edges": [
                {"node": {"id": "gid://shopify/FulfillmentOrderLineItem/21", "remainingQuantity": 1, "totalQuantity": 1, "lineItem": {"id": "gid://shopify/LineItem/3", "title": "Cap", "variantTitle": ""}}},
            ]}}})
        return orders

    def _status(self) -> str:
        if not any(self.remaining.values()):
            return "PARTIALLY_FULFILLED" if self.stuck else "FULFILLED"
        return "PARTIALLY_FULFILLED" if self.fulfillments else "UNFULFILLED"

    def _order(self) -> dict:
        node = super()._order()
        node.update({
            "cancelledAt": self.cancelled_at, "displayFulfillmentStatus": self._status(), "displayFinancialStatus": self.financial,
            "fulfillmentOrders": {"edges": self._fulfillment_orders()},
            "fulfillments": [{"id": f["id"], "status": "SUCCESS", "displayStatus": "FULFILLED", "createdAt": "2026-09-09T12:00:00Z", "trackingInfo": [f["tracking"]] if f["tracking"] else []} for f in self.fulfillments],
            "lineItems": {"edges": [
                {"node": {"id": LINE, "title": "Blue Wash Yard Jeans", "quantity": 2, "unfulfilledQuantity": self.remaining[FOL], "refundableQuantity": 2}},
                {"node": {"id": LINE2, "title": "Convict Sweats", "quantity": 1, "unfulfilledQuantity": self.remaining[FOL2], "refundableQuantity": 1}},
            ]},
        })
        return node

    async def mutate(self, name: str, variables: dict) -> dict:
        reviewed = REVIEWED_MUTATIONS[name]
        assert set(variables) == set(reviewed.variables), "the reviewed variable set, exactly"
        assert reviewed.validate("fulfillment", variables["fulfillment"]), "the nested shape, checked as the client would"
        self.mutations.append((name, copy.deepcopy(variables)))
        if self.fail_mutation or self.refuse:
            raise ShopifyError("Shopify refused it.")
        sent = variables["fulfillment"]
        for entry in sent["lineItemsByFulfillmentOrder"]:
            assert entry["fulfillmentOrderId"] == FO
            for line in entry["fulfillmentOrderLineItems"]:
                assert self.remaining[line["id"]] >= line["quantity"]
                self.remaining[line["id"]] -= line["quantity"]
        tracking = sent.get("trackingInfo")
        self.fulfillments.append({"id": f"gid://shopify/Fulfillment/{len(self.fulfillments) + 1}", "tracking": {"company": tracking["company"], "number": tracking["number"], "url": f"https://track.example/{tracking['number']}"} if tracking else None, "notify": sent["notifyCustomer"]})
        if self.lose_answer:
            raise ShopifyError("timed out")
        return {"data": {"fulfillmentCreate": {"fulfillment": {"id": self.fulfillments[-1]["id"], "status": "SUCCESS"}, "userErrors": []}}}


@pytest.fixture()
def store():
    s = FulfilStore()
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
    s = Session(session_id="c1")
    s.issue(ORDER, LINE, LINE2)
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
    armed, code = engine.arm(proposal.proposal_id, "c1")
    assert code == ""
    proposal.armed_at -= 1.0
    return await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)


# --------------------------------------------------------------------------- declaration


def test_fulfilment_is_red_irreversible_a_hold_then_a_tap_and_never_resent():
    spec = registry.get(TOOL)
    assert spec.tier is Tier.RED and spec.write.complete and spec.write.kind == "irreversible" and not spec.write.reversible and spec.write.undo is None
    assert gesture_for("RED", spec.write.kind) == "hold_to_arm"
    reviewed = REVIEWED_MUTATIONS["fulfillment_create"]
    assert reviewed.scope == "write_merchant_managed_fulfillment_orders" and not reviewed.idempotent and reviewed.root == "fulfillmentCreate"
    good = {"notifyCustomer": False, "trackingInfo": {"company": "Royal Mail", "number": TRACKING}, "lineItemsByFulfillmentOrder": [{"fulfillmentOrderId": FO, "fulfillmentOrderLineItems": [{"id": FOL, "quantity": 2}]}]}
    assert reviewed.validate("fulfillment", good)
    assert reviewed.validate("fulfillment", {k: v for k, v in good.items() if k != "trackingInfo"})
    assert not reviewed.validate("fulfillment", {**good, "originAddress": {}}), "unknown keys refused"
    assert not reviewed.validate("fulfillment", {**good, "trackingInfo": {"company": "Royal Mail", "number": "AB 123"}})
    assert not reviewed.validate("fulfillment", {**good, "trackingInfo": {"company": "Royal Mail", "url": "https://x"}}), "no model-supplied urls"
    assert not reviewed.validate("fulfillment", {**good, "lineItemsByFulfillmentOrder": []})
    assert not reviewed.validate("fulfillment", {**good, "lineItemsByFulfillmentOrder": [{"fulfillmentOrderId": FO, "fulfillmentOrderLineItems": [{"id": FOL, "quantity": 0}]}]})
    assert not reviewed.validate("fulfillment", {**good, "lineItemsByFulfillmentOrder": [{"fulfillmentOrderId": FO, "fulfillmentOrderLineItems": []}]}), "lines are always named"
    assert classify(TOOL, {"order_id": ORDER, "tracking_number": TRACKING}, issued_ids={ORDER}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify(TOOL, {"order_id": ORDER}).disposition is Disposition.DENY
    assert classify(TOOL, {"order_id": ORDER, "notify": True}, issued_ids={ORDER}).disposition is Disposition.DENY, "policy is not an argument"


def test_carriers_are_spelled_as_shopify_spells_them():
    assert "Royal Mail" in shopify_writes.CARRIERS and "DPD UK" in shopify_writes.CARRIERS and "Evri" in shopify_writes.CARRIERS
    assert shopify_writes._CARRIER_BY_KEY["royalmail"] == "Royal Mail" and shopify_writes._CARRIER_BY_KEY["dpduk"] == "DPD UK"


# --------------------------------------------------------------------------- preparing


async def test_preparing_reads_the_fulfilment_orders_names_every_line_and_sends_nothing(store, engine, session):
    text, proposal = await stage(session, tracking_number="ab123456785gb")
    assert text.startswith("PROPOSED") and words_for("hold_to_arm")["verb"] in text
    assert "mark order 1930 for Daniel Stub as shipped with Royal Mail, tracking AB123456785GB, without emailing the customer" in text
    assert store.mutations == [] and proposal.risk == "RED" and proposal.interaction == "hold_to_arm"
    ex = dict(proposal.execution)
    assert ex["input"] == {
        "notifyCustomer": False, "trackingInfo": {"company": "Royal Mail", "number": TRACKING},
        "lineItemsByFulfillmentOrder": [{"fulfillmentOrderId": FO, "fulfillmentOrderLineItems": [{"id": FOL, "quantity": 2}, {"id": FOL2, "quantity": 1}]}],
    }
    assert ex["complete"] is True and ex["expected_remaining"] == shopify_writes._remaining_hash({FOL: 0, FOL2: 0})
    assert proposal.before == {"fulfillment": "UNFULFILLED", "cancelled": False, "remaining": shopify_writes._remaining_hash({FOL: 2, FOL2: 1}), "lines": 2}
    words = registry.get(TOOL).write.present(proposal)
    assert words["title"] == "Mark as shipped" and words["detail"] == "Marks every item shipped." and words["done_title"] == "Shipped"
    facts = {f["label"]: f["value"] for f in words["facts"]}
    assert facts == {"Customer": "Daniel Stub", "Items": "Blue Wash Yard Jeans M ×2, Convict Sweats L", "From": "CROOKS HQ", "Carrier": "Royal Mail", "Tracking": TRACKING, "Customer emailed": "no"}
    assert all(f.get("tone", "") == "" for f in words["facts"])
    line = engine.ledger.read()[-1]
    assert line["event"] == "PROPOSED" and line["facts"] == {"lines": 2, "units": 3, "carrier": "Royal Mail", "tracked": True, "notify": False, "complete": True}
    assert "Jeans" not in str(line) and "Daniel" not in str(line)


async def test_the_carrier_is_matched_loosely_and_sent_exactly(store, engine, session):
    _, proposal = await stage(session, tracking_number="1234567890123456", carrier="dpd uk")
    assert dict(proposal.execution)["input"]["trackingInfo"] == {"company": "DPD UK", "number": "1234567890123456"}
    facts = {f["label"]: f["value"] for f in registry.get(TOOL).write.present(proposal)["facts"]}
    assert facts["Carrier"] == "DPD UK" and facts["Tracking"] == "1234567890123456"


async def test_a_royal_mail_number_of_the_wrong_shape_is_printed_as_a_doubt_not_refused(store, engine, session):
    _, proposal = await stage(session, tracking_number="JD0002A10012345678")
    tracking = [f for f in registry.get(TOOL).write.present(proposal)["facts"] if f["label"] == "Tracking"][0]
    assert tracking["value"].startswith("JD0002A10012345678 · not the usual Royal Mail form") and tracking["tone"] == "warn"


async def test_no_tracking_ships_without_a_link_and_says_so(store, engine, session):
    text, proposal = await stage(session)
    assert "no tracking number" in text
    ex = dict(proposal.execution)
    assert "trackingInfo" not in ex["input"]
    tracking = [f for f in registry.get(TOOL).write.present(proposal)["facts"] if f["label"] == "Tracking"][0]
    assert tracking["value"] == "none" and tracking["tone"] == "warn"
    assert engine.ledger.read()[-1]["facts"]["tracked"] is False


async def test_policy_decides_the_email_and_the_card_prints_it(store, engine, session):
    class Loud(Policy):
        fulfil_notify = True

    shopify_writes.bind_policy(lambda: Loud())
    text, proposal = await stage(session, tracking_number=TRACKING)
    assert ", emailing the customer" in text and dict(proposal.execution)["input"]["notifyCustomer"] is True
    facts = {f["label"]: f["value"] for f in registry.get(TOOL).write.present(proposal)["facts"]}
    assert facts["Customer emailed"] == "yes — with the tracking link"


async def test_only_the_items_named_ship_and_the_rest_stay_open(store, engine, session):
    text, proposal = await stage(session, tracking_number=TRACKING, items=[{"line_item_id": LINE, "quantity": 1}])
    assert "as shipped in part" in text
    ex = dict(proposal.execution)
    assert ex["input"]["lineItemsByFulfillmentOrder"] == [{"fulfillmentOrderId": FO, "fulfillmentOrderLineItems": [{"id": FOL, "quantity": 1}]}]
    assert ex["complete"] is False and ex["expected_remaining"] == shopify_writes._remaining_hash({FOL: 1, FOL2: 1})
    words = registry.get(TOOL).write.present(proposal)
    assert words["detail"] == "Marks these items shipped; the rest stay open."
    assert {f["label"]: f["value"] for f in words["facts"]}["Items"] == "Blue Wash Yard Jeans M"
    result = await commit(engine, proposal)
    assert result.code == "verified" and store.remaining == {FOL: 1, FOL2: 1}


@pytest.mark.parametrize("state,args,words", [
    ({"cancelled_at": "2026-09-01T00:00:00Z"}, {}, "is cancelled"),
    ({"remaining": {FOL: 0, FOL2: 0}}, {}, "nothing left to ship"),
    ({"financial": "PENDING"}, {}, "is pending; it should not ship yet"),
    ({"financial": "PARTIALLY_PAID"}, {}, "is partly paid; take the balance first"),
    ({"split": True}, {}, "split across locations"),
    ({}, {"carrier": "Pigeon Post"}, "carrier must be one Shopify knows"),
    ({}, {"tracking_number": "AB 12"}, "tracking number must be"),
    ({}, {"items": [{"line_item_id": LINE, "quantity": 3}]}, "Only 2 of Blue Wash Yard Jeans remain"),
    ({}, {"items": [{"line_item_id": "gid://shopify/LineItem/9", "quantity": 1}]}, "not still to ship"),
    ({}, {"items": [{"line_item_id": LINE, "quantity": "two"}]}, "whole-number quantity"),
])
async def test_refusals_stage_nothing(store, engine, session, state, args, words):
    for key, value in state.items():
        setattr(store, key, value)
    text, proposal = await stage(session, **args)
    assert text.startswith("ERROR") and words in text, text
    assert proposal is None and store.mutations == []


# --------------------------------------------------------------------------- committing


async def test_a_hold_then_a_tap_ships_it_once_and_proves_it(store, engine, session):
    _, proposal = await stage(session, tracking_number=TRACKING)
    result = await commit(engine, proposal)
    assert result.code == "verified" and result.spoken == "Order 1930 marked as shipped."
    assert len(store.mutations) == 1 and store.mutations[0][0] == "fulfillment_create"
    assert store.remaining == {FOL: 0, FOL2: 0} and store.fulfillments[0]["tracking"]["number"] == TRACKING and store.fulfillments[0]["notify"] is False
    assert proposal.status is ActionStatus.VERIFIED and proposal.note == "" and proposal.undo_id is None
    assert proposal.sent == {"fulfillment_id": "gid://shopify/Fulfillment/1", "status": "SUCCESS"}
    assert proposal.entity["fulfillment"] == "FULFILLED" and proposal.entity["fulfillments"][0]["number"] == TRACKING
    events = [line["event"] for line in engine.ledger.read()]
    assert events[-3:] == ["EXECUTING", "EXECUTED", "VERIFIED"] and "ARMED" in events
    again = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)
    assert again.code == "already_executed" and len(store.mutations) == 1


async def test_a_tap_without_the_hold_does_nothing(store, engine, session):
    _, proposal = await stage(session, tracking_number=TRACKING)
    result = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce="")
    assert result.code == "not_armed" and store.mutations == [] and proposal.status is ActionStatus.PENDING


async def test_a_shipment_made_in_admin_meanwhile_makes_it_stale(store, engine, session):
    _, proposal = await stage(session, tracking_number=TRACKING)
    store.remaining[FOL2] = 0   # someone shipped the sweats from Admin
    result = await commit(engine, proposal)
    assert result.code == "stale" and store.mutations == [] and result.spoken == "The order's items changed since this was prepared. Nothing was sent."


async def test_a_lost_answer_is_settled_by_looking(store, engine, session):
    _, proposal = await stage(session, tracking_number=TRACKING)
    store.lose_answer = True
    result = await commit(engine, proposal)
    assert result.code == "verified" and len(store.mutations) == 1 and store.remaining == {FOL: 0, FOL2: 0}


async def test_a_refusal_from_shopify_is_a_failure_with_nothing_shipped(store, engine, session):
    _, proposal = await stage(session, tracking_number=TRACKING)
    store.refuse = True
    result = await commit(engine, proposal)
    assert proposal.status is ActionStatus.FAILED and store.fulfillments == [] and store.remaining == {FOL: 2, FOL2: 1}
    assert result.spoken == "I couldn't confirm the fulfilment. Check the order before asking again."


async def test_a_partial_shipment_that_shopify_still_calls_unfulfilled_is_said_out_loud(store, engine, session):
    _, proposal = await stage(session, tracking_number=TRACKING)
    store.stuck = True
    result = await commit(engine, proposal)
    assert result.code == "verified" and result.spoken.endswith("Shopify still shows the order as not fully shipped; check it.")
