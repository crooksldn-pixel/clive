"""Before buying, the order is re-read from Shopify. An old preview can never buy a label for a
materially changed order (Stage 4)."""

import pytest

from shipping.fake_shopify import FakeShopify, fo, hoodie_line, tee_line
from shipping.models import ShipmentStatus as S
from shipping.money import Money
from shipping.purchase import ActionError, Purchases, Stale
from shipping.service import ShippingService

from .conftest import SHOP
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
    """A ready order whose price has been shown: (shipment, basis, the Shopify snapshot)."""
    snap = shopify.add(fo(2145, [tee_line(qty=2)]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    return s, svc.preview(SHOP, s.id)["basis"], snap


def assert_nothing_bought(provider):
    assert "create_order" not in provider.calls and provider.charges == []


def test_an_unchanged_order_buys(svc, previewed, provider):
    s, b, _ = previewed
    assert svc.buy(SHOP, s.id, b, "george", "k1")["charged"]


def test_a_quantity_change_refuses_the_old_preview(svc, previewed, provider):
    s, b, snap = previewed
    snap.lines[0].quantity = 3
    with pytest.raises(Stale, match="changed in Shopify"):
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert_nothing_bought(provider)
    fresh = svc.store.get(SHOP, s.id)
    assert fresh.lines[0].quantity == 3  # refreshed, ready for a new preview
    assert svc.buy(SHOP, s.id, svc.preview(SHOP, s.id)["basis"], "george", "k2")["charged"]


def test_an_added_item_refuses_the_old_preview(svc, previewed, provider, shopify):
    s, b, snap = previewed
    snap.lines.append(hoodie_line())
    shopify.add(snap)  # registers the hoodie's inventory item
    with pytest.raises(Stale):
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert_nothing_bought(provider)


def test_a_new_address_refuses_the_old_preview(svc, previewed, provider):
    s, b, snap = previewed
    snap.destination = snap.destination.model_copy(update={"line1": "Unter den Linden 1"})
    with pytest.raises(Stale):
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert_nothing_bought(provider)


def test_a_price_change_on_a_line_refuses_the_old_preview(svc, previewed, provider):
    s, b, snap = previewed
    snap.lines[0].unit_value = Money(minor=2900)  # customs value changes
    with pytest.raises(Stale):
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert_nothing_bought(provider)


def test_a_weight_change_in_shopify_refuses_the_old_preview(svc, previewed, provider, shopify):
    s, b, snap = previewed
    # Shopify's variant weight arrives on the fulfillment order line (and the inventory item).
    snap.lines[0].weight_g = 900
    shopify.items[snap.lines[0].inventory_item_id].weight_g = 900
    with pytest.raises(Stale):
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert_nothing_bought(provider)


def test_a_cancelled_order_is_never_bought(svc, previewed, provider):
    s, b, snap = previewed
    snap.order_cancelled = True
    with pytest.raises(Stale, match="cancelled or fulfilled"):
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert_nothing_bought(provider)
    assert svc.store.get(SHOP, s.id).status == S.cancelled


def test_an_order_fulfilled_elsewhere_is_never_bought(svc, previewed, provider):
    s, b, snap = previewed
    snap.status = "CLOSED"  # e.g. fulfilled by hand in Shopify meanwhile
    with pytest.raises(Stale):
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert_nothing_bought(provider)


def test_shopify_unreachable_at_buy_time_buys_nothing(svc, previewed, provider, shopify):
    s, b, _ = previewed
    shopify.fo_reads_fail = 1
    with pytest.raises(ActionError) as e:
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert e.value.status == 503 and "nothing was bought" in str(e.value).lower()
    assert_nothing_bought(provider)
    assert svc.buy(SHOP, s.id, b, "george", "k2")["charged"]  # Shopify back: same preview buys


def test_the_preview_itself_shows_the_current_order(svc, previewed, provider):
    s, b, snap = previewed
    snap.lines[0].quantity = 1
    with pytest.raises(Stale):
        svc.preview(SHOP, s.id)  # a preview of an old order would mislead too
    pv = svc.preview(SHOP, s.id)
    assert pv["basis"] != b and "1 items" in " ".join(pv["will"])
