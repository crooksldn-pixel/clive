"""Adjusting stock: RED, a hold then a tap, one variant at the one location, the new number
decided on the Mac and held to the old one by Shopify's compare-and-swap. The store is a
fake with levels of its own; nothing reaches a network."""

from __future__ import annotations

import copy

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.grammar import gesture_for
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.clients.shopify import REVIEWED_MUTATIONS, ShopifyError, ShopifyPreconditionFailed
from app.session.models import Session
from app.tools import (  # noqa: F401 — registers the stock change
    registry,
    shopify_tools,
    shopify_writes,
)
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.test_actions import FakeStore

# The admitted owner calling tools directly, as a request the door let through would: every tool
# call here is his (the 2026-09-27 deploy review, round 8, F-A2-FIXTURE). Production's default,
# and every test's that does not say this, is no authority at all.
pytestmark = pytest.mark.usefixtures("owner_asking")

TOOL = "shopify_inventory_adjust"
VARIANT = "gid://shopify/ProductVariant/44"
ITEM = "gid://shopify/InventoryItem/440"
LOCATION = "gid://shopify/Location/1"


class StockStore(FakeStore):
    """One variant, stocked at one location, whose quantity only changes if the compare
    quantity still stands."""

    def __init__(self) -> None:
        super().__init__(note="")
        self.available = 4
        self.tracked = True
        self.levels = 1
        self.sell_before_mutation = 0    # units sold between the precondition read and the write
        self.title = "M"
        self.reads_of_stock = 0

    def _variant(self) -> dict:
        edges = [{"node": {"id": f"gid://shopify/InventoryLevel/{i}", "location": {"id": LOCATION if i == 0 else f"gid://shopify/Location/{i + 1}", "name": "CROOKS HQ" if i == 0 else "Pop-up", "isActive": True},
                           "quantities": [{"name": "available", "quantity": self.available if i == 0 else 1}, {"name": "on_hand", "quantity": self.available + 1 if i == 0 else 1}]}} for i in range(self.levels)]
        return {
            "id": VARIANT, "title": self.title, "sku": "BWYJ-M", "inventoryQuantity": self.available, "product": {"id": "gid://shopify/Product/4", "title": "Blue Wash Yard Jeans"},
            "inventoryItem": {"id": ITEM, "tracked": self.tracked, "inventoryLevels": {"edges": edges}},
        }

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        if "CrooksVariantStock" in query:
            self.reads_of_stock += 1
            return {"data": {"productVariant": self._variant() if (variables or {}).get("id") == VARIANT else None}}
        return await super().graphql(query, variables)

    async def mutate(self, name: str, variables: dict) -> dict:
        reviewed = REVIEWED_MUTATIONS[name]
        assert set(variables) == set(reviewed.variables), "the reviewed variable set, exactly"
        assert reviewed.validate("input", variables["input"]), "the nested shape, checked as the client would"
        self.mutations.append((name, copy.deepcopy(variables)))
        if self.fail_mutation:
            raise ShopifyError("Shopify refused it.")
        if self.sell_before_mutation:
            self.available -= self.sell_before_mutation
            self.sell_before_mutation = 0
        q = variables["input"]["quantities"][0]
        if q["compareQuantity"] != self.available:
            raise ShopifyPreconditionFailed("COMPARE_QUANTITY_STALE: the quantity has changed")
        delta = q["quantity"] - self.available
        self.available = q["quantity"]
        if self.lose_answer:
            raise ShopifyError("timed out")
        return {"data": {"inventorySetQuantities": {"inventoryAdjustmentGroup": {"id": "gid://shopify/InventoryAdjustmentGroup/9", "reason": variables["input"]["reason"], "changes": [{"name": "available", "delta": delta, "quantityAfterChange": self.available}]}, "userErrors": []}}}


@pytest.fixture()
def store():
    s = StockStore()
    shopify_tools.bind(s)
    return s


@pytest.fixture()
def engine(monkeypatch):
    e = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


@pytest.fixture()
def session():
    s = Session(session_id="c1")
    s.issue(VARIANT)
    s.epoch = 1
    return s


def lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def stage(session, **args):
    before = len(session.proposals)
    text = await dispatch(TOOL, {"variant_id": VARIANT, **args}, session=session, timeout_s=5)
    return text, (session.proposals[-1] if len(session.proposals) > before else None)


async def hold(engine, proposal):
    armed, code = engine.arm(proposal.proposal_id, "c1")
    assert code == ""
    proposal.armed_at -= 1.0
    return await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)


# --------------------------------------------------------------------------- declaration


def test_stock_is_red_reversible_a_hold_and_held_to_the_old_number():
    spec = registry.get(TOOL)
    assert spec.tier is Tier.RED and spec.write.complete and spec.write.kind == "reversible" and spec.write.reversible and spec.write.undo is not None
    assert gesture_for("RED", spec.write.kind) == "hold_to_arm"
    reviewed = REVIEWED_MUTATIONS["inventory_set_quantities"]
    assert reviewed.scope == "write_inventory" and not reviewed.idempotent and reviewed.root == "inventorySetQuantities"
    good = {"name": "available", "reason": "correction", "referenceDocumentUri": "gid://crooks-assistant/StockAdjustment/abc123", "ignoreCompareQuantity": False,
            "quantities": [{"inventoryItemId": ITEM, "locationId": LOCATION, "quantity": 6, "compareQuantity": 4}]}
    assert reviewed.validate("input", good)
    assert not reviewed.validate("input", {**good, "ignoreCompareQuantity": True}), "the compare is never skipped"
    assert not reviewed.validate("input", {**good, "name": "on_hand"})
    assert not reviewed.validate("input", {**good, "reason": "felt like it"})
    assert not reviewed.validate("input", {**good, "quantities": good["quantities"] * 2}), "one variant at one location"
    assert not reviewed.validate("input", {**good, "quantities": [{**good["quantities"][0], "quantity": -1}]})
    assert not reviewed.validate("input", {**good, "quantities": [{k: v for k, v in good["quantities"][0].items() if k != "compareQuantity"}]})
    assert not reviewed.validate("input", {**good, "referenceDocumentUri": "https://evil.example/x"})
    assert classify(TOOL, {"variant_id": VARIANT, "delta": 2}, issued_ids={VARIANT}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify(TOOL, {"variant_id": VARIANT, "delta": 2}).disposition is Disposition.DENY
    assert classify(TOOL, {"variant_id": "gid://shopify/Order/1", "delta": 2}, issued_ids={"gid://shopify/Order/1"}).disposition is Disposition.DENY, "an order is not a variant"
    assert classify(TOOL, {"variant_id": VARIANT, "delta": 500}, issued_ids={VARIANT}).disposition is Disposition.DENY
    assert classify(TOOL, {"variant_id": VARIANT, "delta": 2, "location_id": LOCATION}, issued_ids={VARIANT}).disposition is Disposition.DENY, "the location is the Mac's to find"


# --------------------------------------------------------------------------- preparing


async def test_preparing_reads_the_level_decides_the_number_and_sends_nothing(store, engine, session):
    text, proposal = await stage(session, delta=2, reason="delivery")
    assert text.startswith("PROPOSED") and "add 2 Blue Wash Yard Jeans M at CROOKS HQ: 4 to 6, a delivery" in text
    assert store.mutations == [] and proposal.risk == "RED" and proposal.interaction == "hold_to_arm" and proposal.reversible
    ex = dict(proposal.execution)
    assert ex["from"] == 4 and ex["to"] == 6 and ex["delta"] == 2 and ex["location_id"] == LOCATION
    assert ex["input"]["quantities"] == [{"inventoryItemId": ITEM, "locationId": LOCATION, "quantity": 6, "compareQuantity": 4}]
    assert ex["input"]["reason"] == "received" and ex["input"]["ignoreCompareQuantity"] is False and ex["input"]["referenceDocumentUri"].startswith("gid://crooks-assistant/StockAdjustment/")
    assert proposal.before == {"available": 4, "tracked": True, "levels": 1} and proposal.entity_label == "Blue Wash Yard Jeans M"
    words = registry.get(TOOL).write.present(proposal)
    assert words["title"] == "Adjust stock" and words["done_title"] == "Stock adjusted"
    facts = {f["label"]: f["value"] for f in words["facts"]}
    assert facts == {"Item": "Blue Wash Yard Jeans M", "Location": "CROOKS HQ", "Available": "4 → 6", "Reason": "a delivery"}
    line = engine.ledger.read()[-1]
    assert line["facts"] == {"delta": 2, "was": 4, "now": 6, "reason": "received"}


async def test_an_oversold_variant_is_said_on_the_card(store, engine, session):
    store.available = -2
    _, proposal = await stage(session, delta=2)
    facts = {f["label"]: f["value"] for f in registry.get(TOOL).write.present(proposal)["facts"]}
    assert facts["Available"] == "-2 → 0" and "oversold" in facts["Note"]


@pytest.mark.parametrize("state,args,words", [
    ({}, {"delta": 0}, "1 to 100"),
    ({}, {"delta": -5}, "cannot go below zero"),
    ({"tracked": False}, {"delta": 1}, "not tracked"),
    ({"levels": 2}, {"delta": 1}, "2 locations"),
    ({"levels": 0}, {"delta": 1}, "not stocked at any location"),
    ({}, {"delta": 1, "reason": "vibes"}, "reason must be one of"),
])
async def test_refusals_stage_nothing(store, engine, session, state, args, words):
    for key, value in state.items():
        setattr(store, key, value)
    text, proposal = await stage(session, **args)
    assert text.startswith("ERROR") and words in text, text
    assert proposal is None and store.mutations == []


# --------------------------------------------------------------------------- committing


async def test_a_hold_moves_the_stock_once_and_the_undo_moves_it_back(store, engine, session):
    _, proposal = await stage(session, delta=2, reason="received")
    result = await hold(engine, proposal)
    assert result.code == "verified" and result.spoken == "Stock for Blue Wash Yard Jeans M is now 6."
    assert store.available == 6 and len(store.mutations) == 1
    assert proposal.status is ActionStatus.VERIFIED and proposal.after == {"available": 6, "tracked": True, "levels": 1}
    undo = engine.find(proposal.undo_id)
    assert undo is not None and undo.interaction == "hold_to_arm" and undo.risk == "RED"
    words = registry.get(TOOL).write.present(undo)
    assert words["title"] == "Put the stock back" and words["detail"] == "6 → 4 at CROOKS HQ."
    reverse = dict(undo.execution)
    assert reverse["input"]["quantities"] == [{"inventoryItemId": ITEM, "locationId": LOCATION, "quantity": 4, "compareQuantity": 6}]
    assert reverse["input"]["referenceDocumentUri"] != dict(proposal.execution)["input"]["referenceDocumentUri"]
    undone = await hold(engine, undo)
    assert undone.code == "verified" and undone.spoken == "Stock for Blue Wash Yard Jeans M is back to 4." and store.available == 4
    again = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)
    assert again.code == "already_executed" and len(store.mutations) == 2


async def test_a_tap_without_the_hold_does_nothing(store, engine, session):
    _, proposal = await stage(session, delta=2)
    result = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce="")
    assert result.code == "not_armed" and store.mutations == []


async def test_a_sale_between_staging_and_the_hold_makes_it_stale_before_anything_is_sent(store, engine, session):
    _, proposal = await stage(session, delta=2)
    store.available = 3
    result = await hold(engine, proposal)
    assert result.code == "stale" and store.mutations == [] and store.available == 3
    assert result.spoken == "The stock moved since this was prepared — a sale, or a change in Admin. Nothing was sent."


async def test_a_sale_between_the_precondition_and_the_write_is_caught_by_shopify_itself(store, engine, session):
    _, proposal = await stage(session, delta=2)
    store.sell_before_mutation = 1
    result = await hold(engine, proposal)
    assert result.code == "stale" and len(store.mutations) == 1 and store.available == 3, "sent once, refused by the compare, nothing applied"
    assert proposal.status is ActionStatus.STALE


async def test_a_lost_answer_is_settled_by_reading_the_level(store, engine, session):
    _, proposal = await stage(session, delta=-3, reason="damaged")
    store.lose_answer = True
    result = await hold(engine, proposal)
    assert result.code == "verified" and store.available == 1 and len(store.mutations) == 1


async def test_a_refusal_from_shopify_is_a_failure_with_nothing_moved(store, engine, session):
    _, proposal = await stage(session, delta=2)
    store.fail_mutation = True
    result = await hold(engine, proposal)
    assert proposal.status is ActionStatus.FAILED and store.available == 4
    assert result.spoken == "I couldn't confirm the stock change. Check the variant before asking again."
