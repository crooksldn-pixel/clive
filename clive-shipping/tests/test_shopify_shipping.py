"""Shopify Shipping UK labels through the purchase ledger: failure modes first.

The fake Shopify Shipping (FakeShopifyShipping) behaves like the Admin API: each mutation buys
again (no idempotency), the result is polled, and it can lose the reply after buying, stay
pending, fail the purchase or refuse it. `labels_bought` counts what Shopify would bill."""

from __future__ import annotations

from datetime import timedelta

import pytest

from shipping.domestic import TRACKED_24, TRACKED_48, DomesticPolicy, RateCode, parse_lines
from shipping.fake_shopify import FakeShopify, FakeShopifyShipping, fo, label_pdf, tee_line
from shipping.models import DocumentKind, OpState, PageSize, Shipment
from shipping.models import ShipmentStatus as S
from shipping.providers.base import ProviderUncertain
from shipping.providers.fake import FakeProvider
from shipping.providers.multi import Providers
from shipping.providers.shopify_shipping import ShopifyShipping
from shipping.purchase import ActionError, Purchases
from shipping.service import ShippingService

from .conftest import SHOP
from .test_stage2 import PACKAGE

POLICY = DomesticPolicy(
    enabled=True,
    lines=parse_lines("Tracked 24=24; Tracked 48=48"),
    rates={TRACKED_24: RateCode("royal_mail", "T24"), TRACKED_48: RateCode("royal_mail", "T48")},
)


class Ticks:
    """Monotonic time that moves only when the adapter sleeps between polls."""

    def __init__(self) -> None:
        self.t = 0.0

    def sleep(self, seconds: float) -> None:
        self.t += seconds

    def __call__(self) -> float:
        return self.t


class World:
    def __init__(self, store, clock, may_buy=lambda s: True) -> None:
        self.store, self.clock = store, clock
        self.shopify = FakeShopify()
        self.ss = FakeShopifyShipping(self.shopify)
        self.intl = FakeProvider()
        ticks = Ticks()
        self.uk = ShopifyShipping(
            self.ss,
            self.shopify,
            store,
            SHOP,
            POLICY,
            store.config,
            clock=clock,
            poll_for=10,
            poll_every=1,
            sleep=ticks.sleep,
            monotonic=ticks,
        )
        self.provider = Providers([self.intl, self.uk])
        self.svc = ShippingService(
            store,
            self.shopify,
            self.provider,
            Purchases(store, self.provider, clock=clock),
            clock=clock,
            may_buy=may_buy,
            domestic=POLICY,
            domestic_provider=self.uk,
        )

    def ready(self, n: int = 3001, line: str | None = "Tracked 48") -> Shipment:
        self.shopify.add(fo(n, [tee_line(qty=2)], country="GB", shipping_line=line))
        self.svc.sync(SHOP)
        s = next(x for x in self.store.shipments(SHOP) if x.order_name == f"CROOKS-{n}")
        if not self.store.config(SHOP).packages:
            s = self.svc.answer(SHOP, s.id, "package", "first_package", PACKAGE, "george")
        s = self.get(s.id)
        assert s.status == S.ready, s.questions
        return s

    def get(self, sid: str) -> Shipment:
        s = self.store.get(SHOP, sid)
        assert s is not None
        return s

    def buy(self, s: Shipment, key: str = "k1") -> dict:
        basis = self.svc.preview(SHOP, s.id)["basis"]
        return self.svc.buy(SHOP, s.id, basis, "george", key)

    def op(self, sid: str):
        (op,) = self.store.ops_for(SHOP, sid)
        return op


@pytest.fixture
def w(store, clock) -> World:
    return World(store, clock)


def label_of(s: Shipment):
    assert s.label is not None
    return s.label


# --------------------------------------------------------------------------- refusals


def test_user_errors_buy_nothing_and_the_order_can_be_bought_again(w):
    s = w.ready()
    w.ss.user_errors = [{"code": "RATES_NOT_FOUND", "field": None, "message": "Rate not found"}]
    out = w.buy(s)
    assert not out["charged"] and not out["may_have_been_charged"]
    after = w.get(s.id)
    assert after.status == S.ready and after.label is None
    assert "no rate for this service" in (after.last_error or "")
    assert w.ss.labels_bought == 0 and len(w.ss.purchases) == 1
    assert w.op(s.id).state == OpState.failed

    assert w.buy(after, key="k2")["charged"]  # a fresh attempt is allowed
    assert w.ss.labels_bought == 1 and len(w.ss.purchases) == 2


def test_a_failed_purchase_buys_nothing_and_can_be_retried(w):
    s = w.ready()
    w.ss.outcome = "PURCHASE_FAILED"
    w.ss.pending_polls = 2
    out = w.buy(s)
    after = w.get(s.id)
    assert not out["charged"] and after.status == S.ready and after.label is None
    assert "Royal Mail isn't available" in (after.last_error or "")
    assert w.ss.labels_bought == 0
    w.ss.outcome = "PURCHASED"
    assert w.buy(after, key="k2")["charged"] and w.ss.labels_bought == 1


def test_never_reaching_shopify_buys_nothing_and_can_be_retried(w):
    s = w.ready()
    w.ss.not_sent = 1
    out = w.buy(s)
    assert not out["charged"] and w.get(s.id).status == S.ready and w.ss.purchases == []
    assert w.buy(w.get(s.id), key="k2")["charged"] and w.ss.labels_bought == 1


# --------------------------------------------------------------------------- unknown outcomes


def test_a_lost_reply_is_unknown_then_the_label_on_the_order_is_adopted(w, clock):
    s = w.ready()
    w.ss.lose_reply = True  # Shopify bought it, and put it on the order; the answer was lost
    out = w.buy(s)
    # UNKNOWN, then read back at once: a fulfilment with a tracking number on this
    # fulfillment order is a label, so the answer is "bought", from Shopify's own record.
    assert out["charged"] and not out["replayed"]
    assert w.ss.labels_bought == 1 and len(w.ss.purchases) == 1
    events = [e.type for e in w.get(s.id).timeline]
    assert events.index("payment_outcome_unknown") < events.index("label_purchased")
    after = w.get(s.id)
    assert after.status in (S.label_purchased, S.fulfilled)
    label = label_of(after)
    assert label.tracking_number == "RM9001GB" and label.provider == "Shopify Shipping"
    assert "Print it from the order in Shopify admin" in label.file_note
    assert any("can't fetch its file" in a for a in after.alerts)
    assert w.op(s.id).state == OpState.done
    for _ in range(3):  # sweeps never send it again
        clock.advance(minutes=5)
        w.svc.tick(SHOP)
    assert len(w.ss.purchases) == 1 and w.ss.labels_bought == 1
    assert w.get(s.id).status == S.fulfilled
    assert len(w.shopify.fulfillments) == 1  # Shopify's own; CLIVE added none


def test_a_lost_reply_with_nothing_on_the_order_waits_for_a_person_to_check(w, clock):
    s = w.ready()
    w.ss.lose_reply, w.ss.outcome = True, "PURCHASE_FAILED"  # in truth nothing was bought
    w.buy(s)
    assert w.get(s.id).status == S.reconciliation_required
    with pytest.raises(ActionError):  # a person can't buy again meanwhile
        w.svc.buy(SHOP, s.id, "anything", "george", "k2")
    for minutes in (2, 3, 4):  # past the protocol's own 2 minutes, inside Shopify's 10
        clock.advance(minutes=minutes)
        w.svc.purchases.reconcile_all()
        assert w.get(s.id).status == S.reconciliation_required
    clock.advance(minutes=2)  # 11 minutes since the first look found nothing
    w.svc.tick(SHOP)
    after = w.get(s.id)
    # Nothing found is not "not bought": the order waits for a person, never Ready by itself.
    assert after.status == S.needs_attention and w.op(s.id).state == OpState.abandoned
    assert [q.kind for q in after.questions] == ["label_check"]
    assert "can't confirm either way" in after.questions[0].text
    assert "weren't charged" not in (after.last_error or "")
    assert not any(e.type == "payment_not_taken" for e in after.timeline)
    with pytest.raises(ActionError):
        w.svc.preview(SHOP, s.id)
    assert len(w.ss.purchases) == 1 and w.ss.labels_bought == 0

    s = w.svc.answer(SHOP, s.id, "label_check", s.id, {"confirm": True}, "george")
    assert s.status == S.ready and s.label_check is None
    w.ss.outcome = "PURCHASED"
    assert w.buy(w.get(s.id), key="k3")["charged"] and len(w.ss.purchases) == 2


def test_still_pending_after_the_poll_is_unknown_and_settled_from_the_result(w, clock):
    s = w.ready()
    w.ss.pending_polls = 50  # longer than the 10 s the buy waits
    out = w.buy(s)
    assert out["may_have_been_charged"] and w.get(s.id).status == S.reconciliation_required
    assert w.ss.labels_bought == 0 and len(w.ss.purchases) == 1
    w.ss._results[next(iter(w.ss._results))]["polls_left"] = 0  # Shopify finishes it
    clock.advance(minutes=1)
    w.svc.tick(SHOP)
    after = w.get(s.id)
    assert w.ss.labels_bought == 1 and len(w.ss.purchases) == 1
    label = label_of(after)
    assert label.tracking_number == "RM9001GB" and not label.file_note
    assert after.status == S.fulfilled


def test_pending_that_then_fails_is_settled_at_once_without_waiting(w, clock):
    s = w.ready()
    w.ss.pending_polls, w.ss.outcome = 50, "PURCHASE_FAILED"
    w.buy(s)
    w.ss._results[next(iter(w.ss._results))]["polls_left"] = 0
    clock.advance(seconds=30)
    w.svc.purchases.reconcile_all()  # one read: Shopify's own record says it failed
    after = w.get(s.id)
    assert after.status == S.ready and w.op(s.id).state == OpState.abandoned
    assert "confirms" in (after.last_error or "") and w.ss.labels_bought == 0


def test_the_adapter_never_sends_a_purchase_twice(w):
    s = w.ready()
    order = w.uk.create_order(s, s.quote, "op_manual")  # type: ignore[arg-type]
    w.uk.pay(order.ref)
    with pytest.raises(ProviderUncertain):
        w.uk.pay(order.ref)
    assert len(w.ss.purchases) == 1 and w.ss.labels_bought == 1


# --------------------------------------------------------------------------- success


def test_preview_shows_service_package_and_weight_and_says_there_is_no_price(w):
    s = w.ready(line="Tracked 24")
    calls = len(w.intl.calls)
    pv = w.svc.preview(SHOP, s.id)
    assert pv["will"][0] == "Buy Royal Mail Tracked 24 from Shopify Shipping"
    assert pv["will"][1] == "Parcel 38×28×8 cm, 0.48 kg"
    assert "price is set by Shopify Shipping when the label is bought" in pv["will"][2]
    assert not any("Customs" in x for x in pv["will"])
    assert pv["money"] == {"shipping_minor": 0, "currency": "GBP", "price_known": False}
    assert "Shopify bill" in pv["charged"]
    assert len(w.intl.calls) == calls  # Parcel2Go/Easyship are never asked about a UK parcel


def test_a_purchase_sends_the_mapped_service_stores_the_label_and_adopts_shopifys_fulfilment(
    w,
):
    s = w.ready(line="Tracked 24")
    out = w.buy(s)
    assert out["charged"] and len(w.ss.purchases) == 1
    sent = w.ss.purchases[0]
    assert sent["preferredRateSelection"] == {"carrierCode": "royal_mail", "serviceCode": "T24"}
    assert sent["fulfillmentOrderId"] == s.fulfillment_order_id
    assert sent["packageInfo"]["customPackage"]["dimensions"] == {
        "length": 38.0,
        "width": 28.0,
        "height": 8.0,
        "unit": "CENTIMETERS",
    }
    assert sent["totalWeight"] == {"value": 480.0, "unit": "GRAMS"}
    assert sent["notifyCustomer"] is True
    after = w.get(s.id)
    label = label_of(after)
    assert after.status == S.fulfilled and label.tracking_number == "RM9001GB"
    assert label.service_code == TRACKED_24 and label.price_known is False
    doc = label.document(DocumentKind.shipping_label)
    assert doc is not None and doc.artifact_id and doc.page_size == PageSize.label_4x6
    stored = w.store.get_artifact(SHOP, doc.artifact_id)
    assert stored is not None and stored[2] == w.ss.label_file
    assert len(w.shopify.fulfillments) == 1 and w.shopify.fulfillments[0]["by"] == (
        "shopify_shipping"
    )


def test_if_shopify_doesnt_fulfil_clive_does_once_after_the_grace_period(w, clock):
    w.ss.creates_fulfillment = False
    s = w.ready()
    w.buy(s)
    after = w.get(s.id)
    assert after.status == S.label_purchased and w.shopify.fulfillments == []
    clock.advance(seconds=60)
    w.svc.tick(SHOP)
    assert w.shopify.fulfillments == []  # still within Shopify's grace
    clock.advance(minutes=2)
    w.svc.tick(SHOP)
    w.svc.tick(SHOP)
    assert len(w.shopify.fulfillments) == 1
    assert w.shopify.fulfillments[0]["number"] == "RM9001GB"
    assert w.get(s.id).status == S.fulfilled and w.ss.labels_bought == 1


def test_documents_that_fail_to_download_are_fetched_later_never_rebought(w, clock):
    s = w.ready()
    w.ss.downloads_fail = 2
    assert w.buy(s)["charged"]
    after = w.get(s.id)
    label = label_of(after)
    assert label.document(DocumentKind.shipping_label) is None and not label.complete
    for _ in range(2):
        clock.advance(minutes=1)
        w.svc.tick(SHOP)
    label = label_of(w.get(s.id))
    assert label.complete and len(w.ss.purchases) == 1 and w.ss.labels_bought == 1


def test_a_customs_form_is_stored_and_printed_with_it(w):
    w.ss.customs_file = label_pdf(text="CN22")
    s = w.ready()
    w.buy(s)
    label = label_of(w.get(s.id))
    form = label.document(DocumentKind.customs_declaration)
    assert form is not None and form.artifact_id and form.must_print
    assert label.customs.value == "paper"


# --------------------------------------------------------------------------- double clicks


def test_a_double_click_and_a_repeated_key_send_one_purchase(w):
    s = w.ready()
    basis = w.svc.preview(SHOP, s.id)["basis"]
    first = w.svc.buy(SHOP, s.id, basis, "george", "same")
    again = w.svc.buy(SHOP, s.id, basis, "george", "same")
    assert first["charged"] and again["replayed"] and again["charged"]
    assert len(w.ss.purchases) == 1 and w.ss.labels_bought == 1


def test_a_new_key_while_unknown_is_refused_and_sends_nothing(w):
    s = w.ready()
    w.ss.pending_polls = 50
    basis = w.svc.preview(SHOP, s.id)["basis"]
    w.svc.buy(SHOP, s.id, basis, "george", "k1")
    with pytest.raises(ActionError):
        w.svc.buy(SHOP, s.id, basis, "george", "k2")
    assert len(w.ss.purchases) == 1


# --------------------------------------------------------------------------- re-checks


def test_a_label_already_bought_in_shopify_admin_drops_the_order_and_buys_nothing(w):
    s = w.ready()
    basis = w.svc.preview(SHOP, s.id)["basis"]
    snap = w.shopify.fos[s.fulfillment_order_id]
    snap.status, snap.tracking_numbers = "CLOSED", ["RM0000GB"]  # bought by hand in Shopify
    with pytest.raises(ActionError, match="cancelled or fulfilled in Shopify"):
        w.svc.buy(SHOP, s.id, basis, "george", "k1")
    assert w.get(s.id).status == S.cancelled and w.ss.purchases == []


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        (lambda snap: setattr(snap, "financial_status", "REFUNDED"), "Refunded"),
        (lambda snap: setattr(snap, "status", "ON_HOLD"), "on hold"),
        (lambda snap: setattr(snap, "order_cancelled", True), "cancelled"),
    ],
)
def test_payment_hold_and_cancel_are_read_again_before_buying(w, change, refusal):
    s = w.ready()
    basis = w.svc.preview(SHOP, s.id)["basis"]
    change(w.shopify.fos[s.fulfillment_order_id])
    with pytest.raises(ActionError, match=refusal):
        w.svc.buy(SHOP, s.id, basis, "george", "k1")
    assert w.ss.purchases == [] and w.get(s.id).label is None


def test_buying_stays_behind_the_owners_authorisation(store, clock):
    w = World(store, clock, may_buy=lambda s: False)
    s = w.ready()
    with pytest.raises(ActionError, match="isn't authorised"):
        w.buy(s)
    assert w.ss.purchases == []


def test_a_second_fulfilment_order_after_a_shopify_label_waits_for_a_person(w):
    s = w.ready()
    w.buy(s)
    again = fo(3002, [tee_line(qty=2)], country="GB")
    again.order_id, again.order_name = "gid://shopify/Order/3001", "CROOKS-3001"
    w.shopify.add(again)
    w.svc.sync(SHOP)
    second = next(x for x in w.store.shipments(SHOP) if x.fulfillment_order_id == again.id)
    assert second.status == S.needs_attention
    assert [q.kind for q in second.questions] == ["second_label"]
    assert "Shopify Shipping RM9001GB" in second.questions[0].text


def test_international_orders_never_reach_shopify_shipping(w):
    w.shopify.add(fo(4001, [tee_line()], country="DE"))
    w.svc.sync(SHOP)
    s = next(x for x in w.store.shipments(SHOP) if x.order_name == "CROOKS-4001")
    assert not s.domestic and w.ss.purchases == []
    assert all(q.provider != "Shopify Shipping" for q in s.rates)


def test_reconcile_never_sends_a_purchase(w, clock):
    s = w.ready()
    w.ss.lose_reply, w.ss.outcome = True, "PURCHASE_FAILED"
    w.buy(s)
    for _ in range(20):
        clock.advance(minutes=1)
        w.svc.tick(SHOP)
    assert len(w.ss.purchases) == 1  # only ever the person's one buy
    assert w.store.label_purchase(SHOP, f"ss:{w.op(s.id).id}")["state"] == "unknown"


def test_the_settle_window_is_shopifys_ten_minutes_not_the_protocols_two(w):
    s = w.ready()
    w.ss.lose_reply, w.ss.outcome = True, "PURCHASE_FAILED"
    w.buy(s)
    assert w.svc.purchases._settle_after(w.op(s.id)) == timedelta(minutes=10)


def test_a_purchase_shopify_keeps_pending_is_never_given_up_or_bought_again(w, clock):
    s = w.ready()
    w.ss.pending_polls = 10_000
    w.buy(s)
    for _ in range(7):  # 70 minutes of sweeps, far past the settle window
        clock.advance(minutes=10)
        w.svc.tick(SHOP)
    after = w.get(s.id)
    assert after.status == S.reconciliation_required and w.op(s.id).state == OpState.pay_unknown
    assert len(w.ss.purchases) == 1
    assert any("still buying this label after an hour" in a for a in after.alerts)
