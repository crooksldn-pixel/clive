"""The order's own payment decides whether a NEW label may be bought (shipping.payment).

An unpaid order used to look as if its only problem was a missing weight. Now every reason
shows at once, the payment is read from Shopify again immediately before any purchase, and a
label already bought is kept (with a warning) whatever happens to the payment afterwards.
"""

import pytest

from shipping import views
from shipping.fake_shopify import FakeShopify, fo, hoodie_line, tee_line
from shipping.models import ShipmentStatus as S
from shipping.payment import POLICY, payment
from shipping.purchase import ActionError, Purchases
from shipping.service import ShippingService

from .conftest import SHOP
from .test_order_changes import assert_nothing_bought
from .test_stage2 import answer_all_first_time, only


@pytest.fixture
def shopify():
    return FakeShopify()


@pytest.fixture
def svc(store, shopify, provider, clock):
    return ShippingService(
        store, shopify, provider, Purchases(store, provider, clock=clock), clock=clock
    )


@pytest.fixture
def previewed(svc, shopify):
    """A paid, ready order whose price has been shown: (shipment, basis, Shopify snapshot)."""
    snap = shopify.add(fo(2145, [tee_line(qty=2)]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    return s, svc.preview(SHOP, s.id)["basis"], snap


BLOCKING = ["PENDING", "PARTIALLY_PAID", "REFUNDED", "VOIDED", "EXPIRED", "AUTHORIZED"]


# ------------------------------------------------------------------ the policy


def test_every_shopify_status_has_a_decision():
    # OrderDisplayFinancialStatus, Admin API 2026-10 (checked against the schema).
    assert set(POLICY) == {"AUTHORIZED", "EXPIRED", "PAID", "PARTIALLY_PAID",
                           "PARTIALLY_REFUNDED", "PENDING", "REFUNDED", "VOIDED"}  # fmt: skip
    assert payment("PAID").allows_purchase
    assert payment("PARTIALLY_REFUNDED").allows_purchase
    assert payment("PARTIALLY_REFUNDED").label == "Partially refunded"  # never "unpaid"
    for status in BLOCKING:
        state = payment(status)
        assert not state.allows_purchase and state.reason, status
    assert payment("AUTHORIZED").label == "Authorized — not captured"


@pytest.mark.parametrize("status", [None, "", "SOMETHING_NEW"])
def test_unknown_payment_blocks(status):
    state = payment(status)
    assert not state.allows_purchase and state.label == "Payment status unknown"


# ------------------------------------------------------------------ preparing an order


def ready_order(svc, shopify, financial="PAID", lines=None):
    snap = fo(2145, lines or [tee_line(qty=2)])
    snap.financial_status = financial
    shopify.add(snap)
    svc.sync(SHOP)
    return answer_all_first_time(svc, only(svc)), snap


def test_a_paid_order_is_ready(svc, shopify):
    s, _ = ready_order(svc, shopify)
    assert s.status == S.ready and s.payment_status == "PAID" and not s.questions


def test_a_partially_refunded_order_still_ships(svc, shopify):
    s, _ = ready_order(svc, shopify, "PARTIALLY_REFUNDED")
    assert s.status == S.ready and views.status_of(s)["label"] == "Ready"


@pytest.mark.parametrize("status", [*BLOCKING, None])
def test_an_unpaid_order_needs_attention_and_cannot_buy(svc, shopify, provider, status):
    s, _ = ready_order(svc, shopify, status)
    assert s.status == S.needs_attention and s.quote is None
    (q,) = [q for q in s.questions if q.kind == "payment"]
    badge = views.status_of(s)
    assert badge["label"] == payment(status).label and badge["tone"] == "critical"
    with pytest.raises(ActionError):
        svc.preview(SHOP, s.id)
    assert_nothing_bought(provider)
    assert any(e.type == "payment_blocking" for e in s.timeline)


def test_every_blocker_shows_at_once(svc, shopify):
    """The real case: payment pending, and a product never shipped abroad before."""
    snap = fo(2150, [hoodie_line(qty=1)])
    snap.financial_status = "PENDING"
    shopify.add(snap)
    svc.sync(SHOP)
    s = only(svc)
    reasons = views.status_of(s)["reasons"]
    assert reasons[0] == "Payment pending"
    for missing in ("Missing weight", "Missing HS code", "Missing country of origin"):
        assert missing in reasons, reasons
    assert views.status_of(s)["label"] == "Payment pending"


def test_payment_taken_later_makes_it_ready(svc, shopify):
    s, snap = ready_order(svc, shopify, "PENDING")
    snap.financial_status = "PAID"
    svc.sync(SHOP)
    s = only(svc)
    assert s.status == S.ready and not s.questions
    assert any(e.type == "payment_cleared" for e in s.timeline)


# ------------------------------------------------------------------ at the moment of buying


@pytest.mark.parametrize("now", ["PENDING", "REFUNDED", "VOIDED", None])
def test_payment_read_again_just_before_buying(svc, previewed, provider, now):
    """Paid when the price was shown; not paid by the time Buy is pressed. Shopify is read
    again, the provider is never called, and the order goes back to Needs attention."""
    s, basis, snap = previewed
    assert s.payment_status == "PAID"
    snap.financial_status = now
    with pytest.raises(ActionError) as caught:
        svc.buy(SHOP, s.id, basis, "george", "k1")
    assert caught.value.code == "payment" and "Nothing was bought" in str(caught.value)
    assert_nothing_bought(provider)
    s = svc.store.get(SHOP, s.id)
    assert s.status == S.needs_attention and s.questions[0].kind == "payment"


def test_check_price_is_refused_too(svc, previewed, provider):
    s, _, snap = previewed
    snap.financial_status = "PENDING"
    calls = list(provider.calls)
    with pytest.raises(ActionError):
        svc.preview(SHOP, s.id)
    assert provider.calls == calls  # not even a price check at the provider


def test_a_bought_label_stays_when_payment_changes_later(svc, previewed, provider):
    s, basis, snap = previewed
    assert svc.buy(SHOP, s.id, basis, "george", "k1")["charged"]
    snap.financial_status = "REFUNDED"
    svc.sync(SHOP)  # the fulfilment order is closed now: sync no longer reads it
    svc.tick(SHOP)  # the tracking read sees the order's payment too
    s = svc.store.get(SHOP, s.id)
    assert s.label is not None and s.status in (S.fulfilled, S.label_purchased)
    assert any("Payment is now 'Refunded'" in a for a in s.alerts)
    assert len(provider.charges) == 1  # nothing cancelled, nothing bought again
