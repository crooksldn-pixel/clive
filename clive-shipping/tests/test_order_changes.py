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


def test_an_address_missing_its_postcode_asks_for_it_and_buys_nothing(svc, shopify, provider):
    snap = fo(2146, [tee_line()])
    snap.destination = snap.destination.model_copy(update={"postcode": ""})
    shopify.add(snap)
    svc.sync(SHOP)
    s = only(svc)
    address = [q for q in s.questions if q.kind == "address"]
    assert s.status == S.needs_attention and "postcode" in address[0].text
    snap.destination = snap.destination.model_copy(update={"postcode": "10115"})
    svc.sync(SHOP)  # fixed in Shopify: picked up without asking anything here
    assert not [q for q in only(svc).questions if q.kind == "address"]


def test_places_without_postcodes_arent_asked_for_one():
    from shipping.models import Address
    from shipping.readiness import address_gaps

    hk = Address(name="Ka Ming", line1="1 Queen's Road", city="Hong Kong", country="HK")
    assert address_gaps(hk) == []
    assert address_gaps(hk.model_copy(update={"country": "DE"})) == ["postcode"]


# ------------------------------------------------------------------ Setup changes (review, 4f)


def test_changed_customs_terms_after_the_preview_refuse_the_old_preview(svc, previewed, provider):
    s, b, _ = previewed
    cfg = svc.store.config(SHOP)
    cfg.duties.mode = "DDP"  # changes the terms the carrier is given
    svc.store.save_config(cfg)
    with pytest.raises(Stale):
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert_nothing_bought(provider)
    fresh = svc.store.get(SHOP, s.id)
    assert fresh.duties and fresh.duties.incoterm == "DDP"


def test_an_ioss_number_that_cant_apply_doesnt_invalidate_the_preview(svc, previewed, provider):
    # Without a confirmed euro value IOSS is never sent, so nothing the carrier gets changed.
    s, b, _ = previewed
    cfg = svc.store.config(SHOP)
    cfg.duties.ioss_number = "IM1234567890"
    svc.store.save_config(cfg)
    assert svc.buy(SHOP, s.id, b, "george", "k1")["charged"]


@pytest.mark.parametrize(
    "change",
    [
        lambda cfg: setattr(cfg, "eori_number", "GB123456789000"),
        lambda cfg: setattr(cfg, "vat_number", "GB123456789"),
        lambda cfg: setattr(cfg, "origin", cfg.origin.model_copy(update={"postcode": "SL8 5AT"})),
    ],
    ids=["eori", "vat", "ship-from"],
)
def test_sender_details_changed_after_the_preview_refuse_it(svc, previewed, provider, change):
    s, b, _ = previewed
    cfg = svc.store.config(SHOP)
    change(cfg)
    svc.store.save_config(cfg)
    with pytest.raises(ActionError):
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert_nothing_bought(provider)
    assert svc.buy(SHOP, s.id, svc.preview(SHOP, s.id)["basis"], "george", "k2")["charged"]


def test_an_order_put_on_hold_is_never_bought(svc, previewed, provider):
    s, b, snap = previewed
    snap.status = "ON_HOLD"  # e.g. fraud review in Shopify
    with pytest.raises(Stale, match="on hold"):
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert_nothing_bought(provider)
    held = svc.store.get(SHOP, s.id)
    assert held.status == S.needs_attention and held.questions[0].kind == "on_hold"
    snap.status = "OPEN"  # released
    svc.sync(SHOP)
    assert svc.store.get(SHOP, s.id).status == S.ready


def test_a_fulfillment_order_that_disappeared_is_never_bought(svc, previewed, provider, shopify):
    s, b, snap = previewed
    del shopify.fos[snap.id]
    with pytest.raises(Stale):
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert_nothing_bought(provider)


def test_item_facts_unreachable_at_buy_time_buys_nothing(svc, previewed, provider, shopify):
    s, b, _ = previewed
    from shipping.shopify import ShopifyError

    real = shopify.item_facts
    shopify.item_facts = lambda ids: (_ for _ in ()).throw(ShopifyError("timed out"))
    with pytest.raises(ActionError) as e:
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert e.value.status == 503 and "nothing was bought" in str(e.value).lower()
    assert_nothing_bought(provider)
    shopify.item_facts = real


def test_choosing_another_service_makes_the_old_preview_stale(svc, previewed, provider):
    s, b, _ = previewed
    other = next(
        q for q in svc.store.get(SHOP, s.id).rates if q.service_code != s.quote.service_code
    )
    svc.choose_service(SHOP, s.id, other.service_code, "george")
    with pytest.raises(ActionError):
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert_nothing_bought(provider)


def test_a_service_cant_be_changed_on_a_bought_label(svc, previewed):
    s, b, _ = previewed
    svc.buy(SHOP, s.id, b, "george", "k1")
    with pytest.raises(ActionError):
        svc.choose_service(SHOP, s.id, s.quote.service_code, "george")


def test_answering_once_unblocks_other_orders_with_the_same_product(svc, shopify, provider):
    shopify.add(fo(2145, [tee_line()]))
    shopify.add(fo(2146, [tee_line()]))
    svc.sync(SHOP)
    first = next(x for x in svc.store.shipments(SHOP) if x.order_name == "CROOKS-2145")
    answer_all_first_time(svc, first)
    assert {x.status for x in svc.store.shipments(SHOP)} == {S.ready}  # no sync needed
    assert "create_order" not in provider.calls


def test_one_failing_order_doesnt_fail_the_answer_that_unblocks_it(svc, shopify, provider):
    shopify.add(fo(2145, [tee_line()]))
    shopify.add(fo(2146, [tee_line()], country="US"))
    svc.sync(SHOP)
    real = provider.quotes

    def us_broken(shipment):
        if shipment.destination.country == "US":
            raise RuntimeError("unexpected provider bug")
        return real(shipment)

    provider.quotes = us_broken
    first = next(x for x in svc.store.shipments(SHOP) if x.order_name == "CROOKS-2145")
    assert answer_all_first_time(svc, first).status == S.ready


def test_a_service_change_racing_a_purchase_never_lands_on_it(svc, previewed, monkeypatch):
    s, _, _ = previewed
    other = next(q for q in s.rates if q.service_code != s.quote.service_code)
    real = svc.recommendation

    def a_buy_starts_meanwhile(shipment):
        fresh = svc.store.get(SHOP, s.id)
        fresh.status = S.purchasing  # a purchase was authorised in between
        svc.store.save(fresh)
        return real(shipment)

    monkeypatch.setattr(svc, "recommendation", a_buy_starts_meanwhile)
    with pytest.raises(ActionError):
        svc.choose_service(SHOP, s.id, other.service_code, "george")
    assert svc.store.get(SHOP, s.id).quote.service_code == s.quote.service_code
