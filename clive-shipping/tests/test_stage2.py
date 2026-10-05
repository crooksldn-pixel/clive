"""Stage 2: Shopify discovery, readiness, remembered answers, packages, duties, fulfilment."""

import pytest

from shipping.fake_shopify import FakeShopify, fo, hoodie_line, tee_line
from shipping.models import ShipmentStatus as S
from shipping.purchase import ActionError, Purchases
from shipping.service import ShippingService

from .conftest import SHOP

PACKAGE = {
    "name": "Standard mailer",
    "length_cm": 38,
    "width_cm": 28,
    "height_cm": 8,
    "empty_weight_g": 40,
}


@pytest.fixture
def shopify():
    return FakeShopify()


@pytest.fixture
def svc(store, shopify, provider, clock):
    return ShippingService(
        store, shopify, provider, Purchases(store, provider, clock=clock), clock=clock
    )


def only(svc, shop=SHOP):
    (s,) = svc.store.shipments(shop)
    return s


def kinds(s):
    return sorted(q.kind for q in s.questions)


def answer_all_first_time(svc, s, actor="george"):
    svc.answer(SHOP, s.id, "package", "first_package", PACKAGE, actor)
    svc.answer(
        SHOP,
        s.id,
        "customs",
        "gid://shopify/Product/tee",
        {"hs_code": "6109.10", "description": "Men's cotton T-shirt"},
        actor,
    )
    return svc.answer(SHOP, s.id, "origin", "gid://shopify/Product/tee", {"country": "PT"}, actor)


def buy(svc, s, key="k1"):
    b = svc.preview(SHOP, s.id)["basis"]
    return svc.buy(SHOP, s.id, b, "george", key)


def test_first_order_asks_once_then_ships_and_fulfils(svc, shopify, provider):
    """Two tees to Germany, the first time: three facts, then one decision."""
    shopify.add(fo(2145, [tee_line(qty=2)]))
    assert svc.sync(SHOP) == {"open": 1, "new": 1}
    s = only(svc)
    assert s.status == S.needs_attention and kinds(s) == ["customs", "origin", "package"]
    assert s.questions[1].choices == ["T-Shirt"]  # description prefill: their own product type

    s = answer_all_first_time(svc, s)
    assert s.status == S.ready and not s.questions
    # Saved to Shopify (the record) for every size of the product, not just this one.
    assert (
        "inventoryItemUpdate",
        "gid://shopify/InventoryItem/tee-M",
        "610910",
        None,
        None,
    ) in shopify.writes
    assert shopify.items["gid://shopify/InventoryItem/tee-M"].origin_country == "PT"
    assert s.package.total_weight_g == 40 + 2 * 220 and s.package.source == "default"
    assert s.lines[0].customs_description == "Men's cotton T-shirt"

    pv = svc.preview(SHOP, s.id)
    assert any(
        "may be asked to pay import VAT" in w and "Nothing is prepaid" in w for w in pv["will"]
    )
    assert (
        pv["will"][-1] == "Mark CROOKS-2145 fulfilled in Shopify with the tracking number "
        "and email the customer"
    )
    out = svc.buy(SHOP, s.id, pv["basis"], "george", "k1")
    assert out["status"] == "fulfilled" and len(provider.charges) == 1
    (f,) = shopify.fulfillments
    assert f["company"] == "DPD UK" and f["number"] == out["shipment"].label.tracking_number
    assert f["lines"] == [("gid://shopify/FulfillmentOrderLineItem/1", 2)] and f["notify"]
    assert out["shipment"].timeline[-1].verified  # read back from Shopify


def test_second_identical_order_needs_nothing(svc, shopify):
    shopify.add(fo(2145, [tee_line(qty=2)]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    buy(svc, s)
    shopify.add(fo(2151, [tee_line(n=7, qty=2)]))
    svc.sync(SHOP)
    second = next(x for x in svc.store.shipments(SHOP) if x.order_name == "CROOKS-2151")
    assert second.status == S.ready and not second.questions
    assert second.package.source == "learned"  # this mix went in this package last time
    assert second.lines[0].facts_source == "shopify"  # HS code and origin now live in Shopify


def test_shopify_already_knowing_the_facts_means_no_questions(svc, shopify):
    shopify.add(fo(2145, [tee_line()]))
    for item in shopify.items.values():
        item.hs_code, item.origin_country = "610910", "CN"
    svc.sync(SHOP)
    assert kinds(only(svc)) == ["package"]  # only the one-off package


def test_suggestions_come_only_from_what_the_merchant_confirmed(svc, shopify):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    other = tee_line(n=9)
    other.product_id, other.title = "gid://shopify/Product/tee2", "Logo Tee"
    other.inventory_item_id = "gid://shopify/InventoryItem/tee2-M"
    shopify.add(fo(2160, [other]))
    svc.sync(SHOP)
    s2 = next(x for x in svc.store.shipments(SHOP) if x.order_name == "CROOKS-2160")
    customs = next(q for q in s2.questions if q.kind == "customs")
    origin = next(q for q in s2.questions if q.kind == "origin")
    assert customs.suggestion == "610910"  # used for their other T-Shirt
    assert origin.choices == ["PT"]  # countries they've confirmed before; nothing invented
    assert s.lines[0].hs_code == "610910"


def test_first_product_gets_no_invented_suggestion(svc, shopify):
    shopify.add(fo(2145, [hoodie_line()]))
    svc.sync(SHOP)
    s = only(svc)
    assert kinds(s) == ["customs", "origin", "package", "weight"]
    assert all(q.suggestion is None for q in s.questions)
    assert next(q for q in s.questions if q.kind == "origin").choices == []


def test_missing_weight_is_asked_once_and_written_to_shopify(svc, shopify):
    shopify.add(fo(2145, [hoodie_line()]))
    svc.sync(SHOP)
    s = svc.answer(
        SHOP, only(svc).id, "weight", "gid://shopify/Product/hood", {"grams": 780}, "george"
    )
    assert "weight" not in kinds(s)
    assert shopify.items["gid://shopify/InventoryItem/hood-L"].weight_g == 780


def test_bad_answers_are_refused_plainly(svc, shopify):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = only(svc)
    with pytest.raises(ActionError, match="6 to 10 digits"):
        svc.answer(
            SHOP,
            s.id,
            "customs",
            "gid://shopify/Product/tee",
            {"hs_code": "61", "description": "Tee"},
            "george",
        )
    with pytest.raises(ActionError, match="country"):
        svc.answer(
            SHOP, s.id, "origin", "gid://shopify/Product/tee", {"country": "Portugal"}, "george"
        )
    with pytest.raises(ActionError, match="between 1 and 200"):
        svc.answer(SHOP, s.id, "package", "first_package", {**PACKAGE, "length_cm": 0}, "george")


def test_shopify_refusing_a_fact_still_remembers_it(svc, shopify):
    shopify.add(fo(2145, [tee_line()]))
    shopify.refuse_item_update = True
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    assert s.status == S.ready and "Shopify didn't store it" in s.alerts[0]
    shopify.add(fo(2151, [tee_line(n=7)]))
    svc.sync(SHOP)
    second = next(x for x in svc.store.shipments(SHOP) if x.order_name == "CROOKS-2151")
    assert second.status == S.ready  # not asked again


def test_domestic_orders_are_left_to_shopify(svc, shopify):
    shopify.add(fo(3000, [tee_line()], country="GB"))
    assert svc.sync(SHOP) == {"open": 0, "new": 0}


def test_us_duties_are_described_without_eu_terms(svc, shopify):
    shopify.add(fo(2170, [tee_line()], country="US"))
    svc.sync(SHOP)
    d = only(svc).duties
    assert d.incoterm == "DAP" and d.recipient_may_pay
    assert "import duties and taxes" in d.summary and "VAT" not in d.summary


def test_ioss_is_a_setting_not_a_guess(svc, shopify, store):
    from shipping import duties
    from shipping.models import DutiesPolicy
    from shipping.money import Money

    policy = DutiesPolicy(ioss_number="IM2760000000")
    no_rate = duties.terms(policy, "DE", Money(minor=7400))
    assert no_rate.ioss_number is None and "couldn't be confirmed" in no_rate.summary
    under = duties.terms(policy, "DE", Money(minor=7400), value_in_eur_minor=8600)
    assert under.ioss_number == "IM2760000000" and "IOSS" in under.summary
    us = duties.terms(policy, "US", Money(minor=7400), value_in_eur_minor=8600)
    assert us.ioss_number is None


def test_canary_islands_are_described_as_outside_the_eu_vat_area(svc, shopify):
    from shipping import duties
    from shipping.models import DutiesPolicy
    from shipping.money import Money

    snap = fo(2171, [tee_line()], country="ES")
    snap.destination = snap.destination.model_copy(
        update={"postcode": "38001", "city": "Santa Cruz de Tenerife"}
    )
    shopify.add(snap)
    svc.sync(SHOP)
    d = only(svc).duties
    assert "import duties and taxes" in d.summary and "VAT" not in d.summary
    assert duties.in_eu_vat_area("ES", "28013") and not duties.in_eu_vat_area("ES", "35 001")
    assert not duties.in_eu_vat_area("GB", "SW1A 1AA")
    ioss = duties.terms(
        DutiesPolicy(ioss_number="IM2760000000"),
        "ES",
        Money(minor=7400),
        value_in_eur_minor=8600,
        postcode="38001",
    )
    assert ioss.ioss_number is None  # IOSS can't cover the Canaries


def test_order_cancelled_before_purchase_drops_out(svc, shopify):
    snap = shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    snap.order_cancelled = True
    svc.sync(SHOP)
    assert only(svc).status == S.cancelled


def test_order_cancelled_after_purchase_alerts_and_never_rewrites(svc, shopify):
    snap = shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    shopify.refuse_fulfillment = 1
    buy(svc, s)
    snap.order_cancelled = True
    s = svc.prepare(SHOP, s.id)
    assert s.status == S.fulfillment_failed and s.label  # the label is still the label
    assert any("cancelled after the label was bought" in a for a in s.alerts)


def test_order_edited_after_preview_is_stale(svc, shopify, provider):
    snap = shopify.add(fo(2145, [tee_line(qty=2)]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    b = svc.preview(SHOP, s.id)["basis"]
    snap.lines[0].quantity = 3  # the customer added one more
    svc.sync(SHOP)
    with pytest.raises(ActionError, match="changed"):
        svc.buy(SHOP, s.id, b, "george", "k1")
    assert not provider.charges


def test_partial_fulfillment_order_ships_what_remains(svc, shopify):
    shopify.add(fo(2145, [tee_line(qty=1), hoodie_line()]))
    shopify.fos["gid://shopify/FulfillmentOrder/2145"].lines.pop()  # hoodie already sent
    svc.sync(SHOP)
    assert [ln.title for ln in only(svc).lines] == ["Express Tee"]


def test_shopify_refusing_the_fulfilment_never_rebuys(svc, shopify, provider):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    shopify.refuse_fulfillment = 1
    out = buy(svc, s)
    assert out["status"] == "fulfillment_failed" and "no need to buy again" in out["error"]
    svc.tick(SHOP)  # the sweep retries the fulfilment, not the purchase
    assert only(svc).status == S.fulfilled
    assert len(shopify.fulfillments) == 1 and len(provider.charges) == 1


def test_lost_fulfilment_reply_is_read_back_not_duplicated(svc, shopify):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    shopify.fulfillment_reply_lost = True
    out = buy(svc, s)
    assert out["status"] == "fulfilled" and len(shopify.fulfillments) == 1
    svc.fulfil(SHOP, s.id, "george")  # asking again is harmless
    assert len(shopify.fulfillments) == 1


def test_choosing_another_package_requotes_and_is_learned(svc, shopify, store):
    shopify.add(fo(2145, [tee_line(qty=2)]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    cfg = store.config(SHOP)
    from shipping import packages

    big = packages.add(
        cfg,
        name="Large mailer",
        length_cm=45,
        width_cm=35,
        height_cm=10,
        empty_weight_g=70,
        actor="george",
    )
    store.save_config(cfg)
    s = svc.choose_package(SHOP, s.id, big.id, "george")
    assert s.package.name == "Large mailer" and s.package.source == "merchant"
    buy(svc, s)
    shopify.add(fo(2151, [tee_line(n=7, qty=2)]))
    svc.sync(SHOP)
    second = next(x for x in svc.store.shipments(SHOP) if x.order_name == "CROOKS-2151")
    assert second.package.name == "Large mailer" and second.package.source == "learned"


def test_no_rates_is_one_plain_question(svc, shopify, provider, monkeypatch):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    monkeypatch.setattr(provider, "quotes", lambda s: [])
    s = answer_all_first_time(svc, only(svc))
    assert s.status == S.needs_attention and kinds(s) == ["no_rates"]
    assert "No courier offered a price" in s.questions[0].text


def test_reprint_after_fulfilment_never_buys(svc, shopify, provider):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    buy(svc, s)
    _, first = svc.purchases.reprint(SHOP, s.id)
    _, again = svc.purchases.reprint(SHOP, s.id)
    assert first == again and first.startswith(b"%PDF-1.4 4x6") and len(provider.charges) == 1


def test_origin_location_is_prefilled_from_shopify(svc, shopify, store):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    cfg = store.config(SHOP)
    assert cfg.origin.postcode == "SL8 5AS" and cfg.label_format == "4x6"
    assert cfg.duties.mode == "DAP" and cfg.duties.ioss_number is None


def test_fulfilment_created_but_unconfirmed_is_found_on_retry_not_duplicated(svc, shopify):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    shopify.fulfillment_reply_lost = True
    real_buy = svc.purchases.buy

    def buy_then_lose_shopify(*args, **kwargs):
        out = real_buy(*args, **kwargs)  # the order check before buying got through
        shopify.fo_reads_fail = 2  # neither the pre-check nor the read-back gets through
        return out

    svc.purchases.buy = buy_then_lose_shopify
    out = buy(svc, s)
    assert out["status"] == "fulfillment_failed"
    svc.tick(SHOP)  # reads first, finds it, doesn't create another
    assert only(svc).status == S.fulfilled and len(shopify.fulfillments) == 1
