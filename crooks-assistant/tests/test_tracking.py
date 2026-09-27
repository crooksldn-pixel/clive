"""Tracking added to a shipment already marked shipped: RED, a hold, the one shipment
without a number chosen on the Mac, the carrier as Shopify names it, proven by re-reading
the shipment. The store is a fake with shipments of its own; nothing reaches a network."""

from __future__ import annotations

import copy

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.grammar import gesture_for
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

TOOL = "shopify_fulfillment_tracking_set"
SHIPMENT = "gid://shopify/Fulfillment/1"
TRACKING = "AB123456785GB"


class Policy:
    carrier = "Royal Mail"
    fulfil_notify = False


class TrackingStore(FakeStore):
    """An order shipped without a number. Setting tracking stores it on that shipment."""

    def __init__(self) -> None:
        super().__init__(note="")
        self.shipments: list[dict] = [{"id": SHIPMENT, "status": "SUCCESS", "tracking": None}]
        self.cancelled_at: str | None = None
        self.refuse = False
        self.answer_other_id = False   # Shopify names a different shipment in its answer

    def _order(self) -> dict:
        node = super()._order()
        node.update({
            "cancelledAt": self.cancelled_at, "displayFulfillmentStatus": "FULFILLED",
            "fulfillments": [{"id": s["id"], "status": s["status"], "displayStatus": "FULFILLED", "trackingInfo": [s["tracking"]] if s["tracking"] else []} for s in self.shipments],
        })
        return node

    async def mutate(self, name: str, variables: dict) -> dict:
        reviewed = REVIEWED_MUTATIONS[name]
        assert set(variables) == set(reviewed.variables), "the reviewed variable set, exactly"
        assert reviewed.validate("trackingInfoInput", variables["trackingInfoInput"]), "the nested shape, checked as the client would"
        self.mutations.append((name, copy.deepcopy(variables)))
        if self.fail_mutation or self.refuse:
            raise ShopifyError("Shopify refused it.")
        shipment = next(s for s in self.shipments if s["id"] == variables["fulfillmentId"])
        shipment["tracking"] = {"company": variables["trackingInfoInput"]["company"], "number": variables["trackingInfoInput"]["number"], "url": "https://track.example/x"}
        if self.lose_answer:
            raise ShopifyError("timed out")
        answered = "gid://shopify/Fulfillment/999" if self.answer_other_id else shipment["id"]
        return {"data": {"fulfillmentTrackingInfoUpdate": {"fulfillment": {"id": answered, "status": "SUCCESS", "trackingInfo": [shipment["tracking"]]}, "userErrors": []}}}


@pytest.fixture()
def store():
    s = TrackingStore()
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
    s.issue(ORDER)
    s.epoch = 1
    return s


def lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def stage(session, **args):
    text = await dispatch(TOOL, {"order_id": ORDER, "tracking_number": TRACKING, **args}, session=session, timeout_s=5)
    return text, (session.proposals[-1] if session.proposals else None)


async def hold(engine, proposal):
    armed, code = engine.arm(proposal.proposal_id, "c1")
    assert code == ""
    proposal.armed_at -= 1.0
    return await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)


# --------------------------------------------------------------------------- declaration


def test_tracking_is_red_irreversible_a_hold_and_a_reviewed_idempotent_mutation():
    spec = registry.get(TOOL)
    assert spec.tier is Tier.RED and spec.write.complete and spec.write.kind == "irreversible" and not spec.write.reversible and spec.write.undo is None
    assert gesture_for("RED", spec.write.kind) == "hold_to_arm"
    reviewed = REVIEWED_MUTATIONS["fulfillment_tracking_set"]
    assert reviewed.scope == "write_merchant_managed_fulfillment_orders" and reviewed.idempotent and reviewed.root == "fulfillmentTrackingInfoUpdate"
    assert reviewed.validate("trackingInfoInput", {"company": "Royal Mail", "number": TRACKING})
    assert not reviewed.validate("trackingInfoInput", {"company": "Royal Mail", "number": TRACKING, "url": "https://x"}), "no model-supplied urls"
    assert not reviewed.validate("trackingInfoInput", {"company": "Royal Mail"})
    assert not reviewed.validate("trackingInfoInput", {"company": "<b>", "number": TRACKING})
    assert classify(TOOL, {"order_id": ORDER, "tracking_number": TRACKING}, issued_ids={ORDER}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify(TOOL, {"order_id": ORDER, "tracking_number": TRACKING}).disposition is Disposition.DENY
    assert classify(TOOL, {"order_id": ORDER}, issued_ids={ORDER}).disposition is Disposition.DENY
    assert classify(TOOL, {"order_id": ORDER, "tracking_number": TRACKING, "notify": True}, issued_ids={ORDER}).disposition is Disposition.DENY, "policy is not an argument"


# --------------------------------------------------------------------------- preparing


async def test_the_shipment_without_a_number_is_chosen_on_the_mac_and_nothing_is_sent(store, engine, session):
    text, proposal = await stage(session)
    assert text.startswith("PROPOSED") and "add tracking AB123456785GB with Royal Mail to order 1930 for Daniel Sear, without emailing the customer" in text
    assert store.mutations == [] and proposal.risk == "RED" and proposal.interaction == "hold_to_arm"
    ex = dict(proposal.execution)
    assert ex == {"order_id": ORDER, "fulfillment_id": SHIPMENT, "input": {"company": "Royal Mail", "number": TRACKING}, "notify": False, "number": TRACKING}
    assert proposal.before == {"number": "", "company": "", "status": "SUCCESS", "cancelled": False}
    words = registry.get(TOOL).write.present(proposal)
    facts = {f["label"]: f["value"] for f in words["facts"]}
    assert words["title"] == "Add tracking" and facts["Customer"] == "Daniel Sear" and facts["Carrier"] == "Royal Mail" and facts["Tracking"] == TRACKING and facts["Customer emailed"] == "no"


async def test_the_number_is_stored_without_spaces_and_an_unusual_royal_mail_number_is_flagged(store, engine, session):
    text, proposal = await stage(session, tracking_number="ab 1234 56785 gb")
    assert text.startswith("PROPOSED") and dict(proposal.execution)["number"] == TRACKING
    session.epoch += 1
    text, proposal = await stage(session, tracking_number="1234567890")
    assert text.startswith("PROPOSED")
    facts = {f["label"]: f for f in registry.get(TOOL).write.present(proposal)["facts"]}
    assert facts["Tracking"]["tone"] == "warn" and "not the usual Royal Mail form" in facts["Tracking"]["value"]


async def test_the_carrier_is_named_as_shopify_names_it_or_refused(store, engine, session):
    text, proposal = await stage(session, carrier="dpd uk")
    assert text.startswith("PROPOSED") and dict(proposal.execution)["input"]["company"] == "DPD UK"
    facts = {f["label"]: f["value"] for f in registry.get(TOOL).write.present(proposal)["facts"]}
    assert facts["Tracking"] == TRACKING, "only Royal Mail numbers are held to the Royal Mail form"
    session.epoch += 1
    text, proposal = await stage(session, carrier="Pigeon Post")
    assert text.startswith("ERROR") and "must be one Shopify knows" in text


@pytest.mark.parametrize("bad", ["", "AB1", "x" * 35, "AB123456785GB;DROP", "<b>x</b>"])
async def test_a_number_that_is_not_a_number_is_refused_before_anything_is_read(store, engine, session, bad):
    text = await dispatch(TOOL, {"order_id": ORDER, "tracking_number": bad}, session=session, timeout_s=5)
    assert text.startswith("ERROR") or text.startswith("REFUSED"), text
    assert store.reads == 0 and session.proposals == []


async def test_an_order_that_is_not_shipped_cancelled_or_already_tracked_is_refused(store, engine, session):
    store.shipments = []
    text, _ = await stage(session)
    assert text.startswith("ERROR") and "no shipment marked shipped" in text
    store.shipments = [{"id": SHIPMENT, "status": "SUCCESS", "tracking": {"company": "Evri", "number": "H0012345678901", "url": ""}}]
    text, _ = await stage(session)
    assert text.startswith("ERROR") and "already has tracking H0012345678901" in text
    store.shipments = [{"id": SHIPMENT, "status": "SUCCESS", "tracking": None}, {"id": "gid://shopify/Fulfillment/2", "status": "SUCCESS", "tracking": None}]
    text, _ = await stage(session)
    assert text.startswith("ERROR") and "2 shipments without tracking" in text
    store.shipments = [{"id": SHIPMENT, "status": "CANCELLED", "tracking": None}]
    text, _ = await stage(session)
    assert text.startswith("ERROR") and "no shipment marked shipped" in text, "a cancelled shipment is not a shipment"
    store.shipments = [{"id": SHIPMENT, "status": "SUCCESS", "tracking": None}]
    store.cancelled_at = "2026-09-08T12:00:00Z"
    text, _ = await stage(session)
    assert text.startswith("ERROR") and "is cancelled" in text
    assert session.proposals == [] and store.mutations == []


# --------------------------------------------------------------------------- applying


async def test_a_hold_sets_the_number_once_and_proves_it_from_the_shipment(store, engine, session):
    _, proposal = await stage(session)
    result = await hold(engine, proposal)
    assert result.code == "verified" and result.spoken == "Tracking added to order 1930."
    assert store.mutations == [("fulfillment_tracking_set", {"fulfillmentId": SHIPMENT, "trackingInfoInput": {"company": "Royal Mail", "number": TRACKING}, "notifyCustomer": False})]
    assert store.shipments[0]["tracking"]["number"] == TRACKING and proposal.status is ActionStatus.VERIFIED and proposal.undo_id is None
    again = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)
    assert again.code == "already_executed" and len(store.mutations) == 1, "settled is settled: a second commit is never a second mutation"


async def test_a_tap_without_the_hold_sends_nothing(store, engine, session):
    _, proposal = await stage(session)
    result = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup)
    assert result.code == "not_armed" and store.mutations == [] and proposal.status is ActionStatus.PENDING


async def test_a_number_added_in_admin_meanwhile_makes_it_stale(store, engine, session):
    _, proposal = await stage(session)
    store.shipments[0]["tracking"] = {"company": "Royal Mail", "number": "ZZ999999999GB", "url": ""}
    result = await hold(engine, proposal)
    assert result.code == "stale" and store.mutations == [] and proposal.status is ActionStatus.STALE
    assert result.spoken.startswith("The shipment changed")


async def test_policy_decides_the_email_not_the_model(store, engine, session):
    class Notify(Policy):
        fulfil_notify = True

    shopify_writes.bind_policy(lambda: Notify())
    text, proposal = await stage(session)
    assert ", emailing the customer" in text and dict(proposal.execution)["notify"] is True
    facts = {f["label"]: f["value"] for f in registry.get(TOOL).write.present(proposal)["facts"]}
    assert facts["Customer emailed"] == "yes — with the tracking link"
    await hold(engine, proposal)
    assert store.mutations[0][1]["notifyCustomer"] is True


async def test_a_refusal_from_shopify_leaves_the_shipment_as_it_was(store, engine, session):
    _, proposal = await stage(session)
    store.refuse = True
    result = await hold(engine, proposal)
    assert result.code in ("failed", "unverified", "service_unavailable", "refused") and store.shipments[0]["tracking"] is None
    assert proposal.status is not ActionStatus.VERIFIED and "couldn't confirm" in result.spoken or result.spoken


async def test_a_lost_answer_is_settled_by_re_reading_the_shipment(store, engine, session):
    _, proposal = await stage(session)
    store.lose_answer = True
    result = await hold(engine, proposal)
    assert result.code == "verified" and proposal.status is ActionStatus.VERIFIED and len(store.mutations) == 1


async def test_an_answer_naming_another_shipment_is_not_taken_as_proof(store, engine, session):
    _, proposal = await stage(session)
    store.answer_other_id = True
    result = await hold(engine, proposal)
    # The number is on the shipment (the fake stored it); the re-read proves that, whatever the answer said.
    assert result.code == "verified" and len(store.mutations) == 1


async def test_the_ledger_keeps_the_carrier_and_the_policy_never_the_number(store, engine, session):
    _, proposal = await stage(session)
    line = engine.ledger.read()[-1]
    assert line["event"] == "PROPOSED" and line["facts"] == {"carrier": "Royal Mail", "notify": False}
    assert TRACKING not in str(line) and "Daniel" not in str(line)
