"""Easyship as a second provider: rates normalised into our Quote, failures classified, and the
same purchase protocol as Parcel2Go (one charge, reconcile on doubt, print never buys)."""

from __future__ import annotations

import httpx
import pytest

from shipping import views
from shipping.fake_shopify import FakeShopify, fo, tee_line
from shipping.models import Address, CustomsMode, DocumentKind, OpState, PageSize
from shipping.models import ShipmentStatus as S
from shipping.printing import Printing
from shipping.providers.base import ProviderRefused, ProviderUnavailable
from shipping.providers.fake import FakeProvider
from shipping.providers.multi import Providers
from shipping.purchase import ActionError, Purchases, Stale
from shipping.service import ShippingService

from .conftest import SHOP, make_shipment
from .fake_easyship import GUERNSEY, FakeEasyship, service, spec_errors
from .fake_easyship import adapter as easyship_adapter
from .test_stage2 import answer_all_first_time

GG = Address(
    name="Test Recipient",
    line1="1 Test Street",
    city="St Peter Port",
    postcode="GY1 1AA",
    country="GG",
    phone="07781000000",
    email="recipient@example.com",
)


@pytest.fixture
def es_server():
    return FakeEasyship()


@pytest.fixture
def es(es_server, cfg, clock):
    return easyship_adapter(es_server, cfg, clock)


@pytest.fixture
def ready(es, store, provider):
    """A ready Guernsey shipment priced by Easyship (the cheapest tracked service)."""
    s = make_shipment(store, provider)
    s.destination = GG
    s.quote = next(q for q in es.quotes(s) if q.tracked)
    return store.save(s)


@pytest.fixture
def purchases(store, es, clock):
    return Purchases(store, es, clock=clock)


def buy(purchases, s, key="k1"):
    b = purchases.preview(SHOP, s.id)["basis"]
    return purchases.buy(SHOP, s.id, b, "george", key)


# ------------------------------------------------------------------ rates


def test_rates_are_normalised_into_our_quotes(es, es_server, store, provider):
    s = make_shipment(store, provider)
    s.destination = GG
    quotes = es.quotes(s)
    assert [q.amount.minor for q in quotes] == [295, 324, 4102]  # cheapest first
    rm = quotes[1]
    assert rm.provider == "Easyship" and rm.carrier == "Royal Mail"
    assert (
        rm.service_name == "Royal Mail International Tracked" and rm.service_code == "es-svc-rm-ci"
    )
    assert rm.amount.currency == "GBP" and (rm.est_days_min, rm.est_days_max) == (2, 4)
    assert rm.tracked is True and rm.handover == "dropoff" and rm.billed_by == "provider"
    assert quotes[0].tracked is False  # tracking_rating -1
    assert quotes[2].handover == "either"
    _, body = es_server.bodies[-1]
    assert body["destination_address"]["country_alpha2"] == "GG"
    assert body["origin_address"]["postal_code"] == "SL8 5AS"
    assert body["courier_settings"]["apply_shipping_rules"] is False  # nothing changes it later
    assert body["shipping_settings"]["output_currency"] == "GBP"
    parcel = body["parcels"][0]
    assert parcel["total_actual_weight"] == 0.48 and parcel["box"] == {
        "length": 38.0,
        "width": 28.0,
        "height": 8.0,
    }
    item = parcel["items"][0]
    assert item["hs_code"] == "610910" and item["origin_country_alpha2"] == "PT"
    assert item["declared_customs_value"] == 37.0 and item["quantity"] == 2
    assert body["incoterms"] == "DDU"


def test_requests_keep_to_easyships_own_schema(es, es_server, store, provider):
    """Live, Easyship refused CROOKS-2142's rates for `"sku": null`; it also needs `state`."""
    s = make_shipment(store, provider)
    s.destination = GG
    assert s.lines[0].sku is None  # many CROOKS lines have no SKU
    es.quotes(s)
    _, body = es_server.bodies[-1]
    assert "sku" not in body["parcels"][0]["items"][0]
    assert body["origin_address"]["state"] == "" and body["destination_address"]["state"] is None
    assert spec_errors("rates", body) == []
    s.lines[0].sku = "TEE-BLK-M"
    es.quotes(s)
    assert es_server.bodies[-1][1]["parcels"][0]["items"][0]["sku"] == "TEE-BLK-M"


def test_the_fake_refuses_what_easyship_refuses(es, es_server, store, provider):
    s = make_shipment(store, provider)
    s.destination = GG
    body = es._rates_body(s)
    body["parcels"][0]["items"][0]["sku"] = None
    assert any("items/0" in e for e in spec_errors("rates", body))
    del body["parcels"][0]["items"][0]["sku"]
    del body["origin_address"]["state"]
    assert any("state" in e for e in spec_errors("rates", body))


def test_missing_contact_details_refuse_before_anything_reaches_easyship(
    es, es_server, store, provider
):
    s = make_shipment(store, provider)
    s.destination = GG.model_copy(update={"phone": "", "email": ""})
    s.quote = next(q for q in es.quotes(s) if q.tracked)  # quoting doesn't need them
    sent = len(es_server.requests)
    with pytest.raises(ProviderRefused, match="customer phone, customer email"):
        es.verify(s, s.quote)
    with pytest.raises(ProviderRefused, match="customer phone, customer email"):
        es.create_order(s, s.quote, "op-1")
    assert es_server.requests[sent:] == [] and es_server.charges == []


def test_a_shipment_names_the_sender_company(es, es_server, store, provider):
    s = make_shipment(store, provider)
    s.destination = GG
    s.quote = next(q for q in es.quotes(s) if q.tracked)
    es.create_order(s, s.quote, "op-1")
    name, body = es_server.bodies[-1]
    assert name == "create" and spec_errors("create", body) == []
    assert body["origin_address"]["company_name"] == "CROOKS LDN"
    assert body["destination_address"]["contact_email"] == "recipient@example.com"
    assert es_server.charges == []


def test_the_same_service_twice_keeps_the_cheaper_and_other_currencies_are_dropped(
    cfg, clock, store, provider
):
    server = FakeEasyship(
        [
            service("svc-a", "Royal Mail", "Tracked", 3.90),
            service("svc-a", "Royal Mail", "Tracked", 4.10),  # the dearer one comes second
            service("svc-usd", "USPS", "Priority", 2.00, currency="USD"),
        ]
    )
    quotes = easyship_adapter(server, cfg, clock).quotes(make_shipment(store, provider))
    assert [(q.service_code, q.amount.minor) for q in quotes] == [("es-svc-a", 390)]


@pytest.mark.parametrize(
    "fault",
    ["garbage", "timeout", httpx.Response(503), httpx.Response(200, json={"rates": "nope"})],
)
def test_unusable_rates_answers_are_unavailable(es, es_server, store, provider, fault):
    es_server.faults["rates"] = fault
    with pytest.raises(ProviderUnavailable):
        es.quotes(make_shipment(store, provider))


def test_a_rate_without_a_price_is_skipped(cfg, clock, store, provider):
    server = FakeEasyship([service("svc-a", "Royal Mail", "Tracked", 3.24)])
    real = server.rate_row

    def no_price(svc):
        row = real(svc)
        row["total_charge"] = None
        return row

    server.rate_row = no_price
    assert easyship_adapter(server, cfg, clock).quotes(make_shipment(store, provider)) == []


def test_a_refused_token_says_so(es_server, cfg, clock, store, provider):
    bad = easyship_adapter(es_server, cfg, clock, token="prod_wrong")
    with pytest.raises(ProviderRefused) as e:
        bad.quotes(make_shipment(store, provider))
    assert e.value.code == "auth"
    with pytest.raises(ProviderRefused):
        easyship_adapter(es_server, cfg, clock, token="not-a-token").quotes(
            make_shipment(store, provider, sid="shp_2", fo="gid://shopify/FulfillmentOrder/2")
        )


def test_the_rate_limit_is_unavailable_not_refused(es, es_server, store, provider):
    es_server.faults["rates"] = httpx.Response(429)
    with pytest.raises(ProviderUnavailable):
        es.quotes(make_shipment(store, provider))


# ------------------------------------------------------------------ the purchase


def test_buying_through_easyship_charges_once_and_stores_a_4x6_label(
    purchases, ready, es_server, store
):
    out = buy(purchases, ready)
    assert out["charged"] and es_server.charges == ["ESGG1001"]
    s = store.get(SHOP, ready.id)
    assert s.status == S.label_purchased and s.label.provider == "Easyship"
    assert s.label.carrier == "Royal Mail" and s.label.tracking_number == "RM123456789GB"
    label = s.label.document(DocumentKind.shipping_label)
    assert label.page_size == PageSize.label_4x6 and label.must_print
    assert s.label.customs == CustomsMode.electronic  # Easyship gave no invoice
    _, create = next(b for b in es_server.bodies if b[0] == "create")
    assert create["courier_settings"] == {
        "courier_service_id": "svc-rm-ci",
        "allow_fallback": False,
        "apply_shipping_rules": False,
    }
    assert create["shipping_settings"]["buy_label"] is False
    _, label_req = next(b for b in es_server.bodies if b[0] == "label")
    assert label_req["printing_options"]["label"] == "4x6"


def test_a_price_rise_after_the_preview_buys_nothing(purchases, ready, es_server):
    b = purchases.preview(SHOP, ready.id)["basis"]
    es_server.services[0]["price"] = 3.99  # svc-rm-ci went up
    with pytest.raises(Stale):
        purchases.buy(SHOP, ready.id, b, "george", "k1")
    assert es_server.charges == [] and not any(n == "create" for n, _ in es_server.bodies)


def test_a_stale_fingerprint_sends_nothing_to_easyship(purchases, ready, es_server, store):
    b = purchases.preview(SHOP, ready.id)["basis"]
    s = store.get(SHOP, ready.id)
    s.lines[0].quantity = 3
    store.save(s)
    calls = len(es_server.requests)
    with pytest.raises(Stale):
        purchases.buy(SHOP, ready.id, b, "george", "k1")
    assert len(es_server.requests) == calls


def test_a_lost_label_reply_after_the_charge_is_reconciled_never_rebought(
    purchases, ready, es_server, store, clock
):
    es_server.faults["label"] = "timeout_after"
    out = buy(purchases, ready)
    assert len(es_server.charges) == 1
    s = store.get(SHOP, ready.id)
    # Resolved by reading Easyship, not by paying again.
    assert s.status == S.label_purchased or out["may_have_been_charged"]
    clock.advance(minutes=6)
    purchases.reconcile_all()
    assert store.get(SHOP, ready.id).status == S.label_purchased
    assert len(es_server.charges) == 1
    assert sum(1 for n, _ in es_server.bodies if n == "label") == 1


def test_a_label_request_that_never_arrived_is_confirmed_unpaid_and_never_paid(
    purchases, ready, es_server, store, clock
):
    es_server.faults["label"] = "timeout"
    buy(purchases, ready)
    assert es_server.charges == []
    for _ in range(3):
        clock.advance(minutes=6)
        purchases.reconcile_all()
    s = store.get(SHOP, ready.id)
    assert s.status == S.ready and es_server.charges == []
    assert sum(1 for n, _ in es_server.bodies if n == "label") == 1


def test_a_refused_label_means_not_charged(purchases, ready, es_server, store):
    es_server.balance = 1.0
    out = buy(purchases, ready)
    assert not out["charged"] and es_server.charges == []
    assert store.get(SHOP, ready.id).status == S.ready
    assert "Insufficient balance" in (store.get(SHOP, ready.id).last_error or "")


def test_a_double_click_charges_once(purchases, ready, es_server):
    b = purchases.preview(SHOP, ready.id)["basis"]
    first = purchases.buy(SHOP, ready.id, b, "george", "k1")
    again = purchases.buy(SHOP, ready.id, b, "george", "k1")
    assert first["charged"] and again["replayed"]
    with pytest.raises(ActionError):
        purchases.buy(SHOP, ready.id, b, "george", "k2")
    assert len(es_server.charges) == 1


def test_easyship_switching_the_courier_is_refused_and_unpaid(purchases, ready, es_server, store):
    real = es_server.handle

    def other_courier(name, path, body, request):
        if name == "create":
            body["courier_settings"]["courier_service_id"] = "svc-ups"
        return real(name, path, body, request)

    es_server.handle = other_courier
    out = buy(purchases, ready)
    assert not out["charged"] and es_server.charges == []
    op = store.ops_for(SHOP, ready.id)[0]
    assert op.state == OpState.failed and "didn't keep" in (op.last_error or "")


def test_a_shipment_easyship_could_not_rate_is_never_paid(purchases, ready, es_server, store):
    es_server.services = [s for s in es_server.services if s["id"] != "svc-rm-ci"]
    real_verify = es_server.handle

    def keep_verify(name, path, body, request):  # the price check still passes
        if name == "rates":
            es_server.services.append(GUERNSEY[0])
            try:
                return real_verify(name, path, body, request)
            finally:
                es_server.services.remove(GUERNSEY[0])
        return real_verify(name, path, body, request)

    es_server.handle = keep_verify
    out = buy(purchases, ready)
    assert not out["charged"] and es_server.charges == []
    assert "couldn't rate it" in (store.ops_for(SHOP, ready.id)[0].last_error or "")


def test_paper_customs_come_as_an_a4_invoice(cfg, clock, store, provider):
    server = FakeEasyship([service("svc-ups", "UPS", "UPS Standard", 9.00, invoice=True)])
    es = easyship_adapter(server, cfg, clock)
    s = make_shipment(store, provider)
    s.destination.email = "max@example.com"  # Easyship needs it to book
    s.quote = es.quotes(s)[0]
    store.save(s)
    p = Purchases(store, es, clock=clock)
    buy(p, s)
    label = store.get(SHOP, s.id).label
    assert label.customs == CustomsMode.paper
    invoice = label.document(DocumentKind.commercial_invoice)
    assert invoice.page_size == PageSize.a4 and invoice.must_print


def test_a_label_still_being_made_is_fetched_later(purchases, ready, es_server, store, clock):
    es_server.label_state_after_buy = "generating"
    buy(purchases, ready)
    s = store.get(SHOP, ready.id)
    assert s.status == S.label_purchased and not s.label.complete
    es_server.shipments["ESGG1001"]["label_state"] = "generated"
    clock.advance(minutes=3)
    purchases.reconcile_all()
    assert store.get(SHOP, ready.id).label.complete
    assert len(es_server.charges) == 1


def test_printing_and_reprinting_never_reach_easyship(purchases, ready, es_server, store, clock):
    buy(purchases, ready)
    calls = len(es_server.requests)
    printing = Printing(store, clock=clock)
    printing.print_shipment(SHOP, ready.id, "george")
    printing.print_shipment(SHOP, ready.id, "george")
    assert len(es_server.requests) == calls and len(es_server.charges) == 1


# ------------------------------------------------------------------ two providers together


@pytest.fixture
def p2g_fake():
    """Parcel2Go as the owner saw it for Guernsey: Parcelforce, about £16.51."""
    from datetime import UTC, datetime

    from shipping.models import Quote
    from shipping.money import Money

    p = FakeProvider(price_minor=1651)
    p.quotes = lambda shipment: [  # type: ignore[method-assign]
        Quote(
            provider="Parcel2Go",
            carrier="Parcelforce",
            service_code="parcelforce-channel-islands",
            service_name="Parcelforce Worldwide - Channel Islands",
            amount=Money(minor=1651),
            est_days_max=8,
            generated_at=datetime(2026, 10, 5, tzinfo=UTC),
        )
    ]
    return p


@pytest.fixture
def shopify():
    return FakeShopify()


@pytest.fixture
def svc(store, shopify, p2g_fake, es, clock):
    both = Providers([p2g_fake, es])
    return ShippingService(store, shopify, both, Purchases(store, both, clock=clock), clock=clock)


def guernsey_order(svc, shopify):
    snap = fo(2142, [tee_line(qty=1)])
    snap.destination = GG
    shopify.add(snap)
    svc.sync(SHOP)
    (s,) = svc.store.shipments(SHOP)
    return answer_all_first_time(svc, s)


def test_the_cheap_easyship_channel_islands_service_is_recommended(svc, shopify):
    s = guernsey_order(svc, shopify)
    assert s.status == S.ready
    rec = svc.recommendation(s)
    assert rec.recommended.quote.provider == "Easyship"
    assert rec.recommended.quote.service_name == "Royal Mail International Tracked"
    assert rec.recommended.quote.amount.minor == 324  # tracked beats £2.95 untracked
    assert rec.cheapest.quote.amount.minor == 295 and not rec.cheapest.quote.tracked
    assert rec.fastest.quote.carrier == "UPS"
    titles = {(o.quote.provider, o.quote.title) for o in rec.options}
    assert ("Parcel2Go", "Parcelforce Worldwide - Channel Islands") in titles
    d = views.detail(s, rec, [])
    assert d["shipping"]["recommended"]["provider"] == "Easyship"
    assert d["shipping"]["note"] is None


def test_easyship_down_still_ships_with_parcel2go(svc, shopify, es_server):
    es_server.faults["rates"] = httpx.Response(503)
    s = guernsey_order(svc, shopify)
    assert s.status == S.ready and s.quote.provider == "Parcel2Go"
    assert s.rates_unavailable == ["Easyship"]
    d = views.detail(s, svc.recommendation(s), [])
    assert d["shipping"]["note"] == "Easyship unavailable — showing Parcel2Go rates"


def test_parcel2go_down_still_ships_with_easyship(svc, shopify, p2g_fake):
    def down(shipment):
        raise ProviderUnavailable("Parcel2Go timed out")

    p2g_fake.quotes = down
    s = guernsey_order(svc, shopify)
    assert s.status == S.ready and s.quote.provider == "Easyship"
    assert s.rates_unavailable == ["Parcel2Go"]


def test_both_down_is_provider_unavailable(svc, shopify, p2g_fake, es_server):
    def down(shipment):
        raise ProviderUnavailable("Parcel2Go timed out")

    p2g_fake.quotes = down
    es_server.services = []
    es_server.faults["rates"] = "timeout"
    s = guernsey_order(svc, shopify)
    assert s.status == S.needs_attention and s.questions[0].kind == "provider_unavailable"


def test_buying_the_easyship_service_through_both_providers(svc, shopify, es_server, p2g_fake):
    s = guernsey_order(svc, shopify)
    b = svc.preview(SHOP, s.id)["basis"]
    out = svc.buy(SHOP, s.id, b, "george", "k1")
    assert out["charged"] and es_server.charges == ["ESGG1001"]
    assert p2g_fake.charges == [] and "create_order" not in p2g_fake.calls
    s = svc.store.get(SHOP, s.id)
    assert s.status == S.fulfilled and s.label.provider == "Easyship"
    assert s.label.provider_ref == "es:ESGG1001"


def test_shopify_failing_after_an_easyship_purchase_retries_shopify_only(svc, shopify, es_server):
    shopify.refuse_fulfillment = 1
    s = guernsey_order(svc, shopify)
    svc.buy(SHOP, s.id, svc.preview(SHOP, s.id)["basis"], "george", "k1")
    assert svc.store.get(SHOP, s.id).status == S.fulfillment_failed
    calls = len(es_server.requests)
    assert svc.fulfil(SHOP, s.id, "george").status == S.fulfilled
    assert len(es_server.requests) == calls and len(es_server.charges) == 1


# ------------------------------------------------------------------ cancel and tracking


def bought(svc, shopify):
    s = guernsey_order(svc, shopify)
    svc.buy(SHOP, s.id, svc.preview(SHOP, s.id)["basis"], "george", "k1")
    return svc.store.get(SHOP, s.id)


def test_an_easyship_label_can_be_cancelled_and_says_so(svc, shopify, es_server):
    s = bought(svc, shopify)
    assert svc.can_cancel(s)
    s = svc.cancel_label(SHOP, s.id, "george")
    assert s.status == S.voided and es_server.shipments["ESGG1001"]["label_state"] == "voided"
    assert any("cancel that fulfilment in Shopify" in a for a in s.alerts)
    assert not svc.can_cancel(s)


def test_a_refused_cancel_keeps_the_label(svc, shopify, es_server):
    s = bought(svc, shopify)
    es_server.faults["cancel"] = httpx.Response(
        422, json={"error": {"code": "invalid_state", "message": "Already picked up"}}
    )
    s = svc.cancel_label(SHOP, s.id, "george")
    assert s.status == S.void_rejected and "Already picked up" in s.last_error


def test_a_lost_cancel_reply_is_settled_by_reading_not_by_cancelling_again(svc, shopify, es_server):
    s = bought(svc, shopify)
    es_server.faults["cancel"] = "timeout_after"
    s = svc.cancel_label(SHOP, s.id, "george")
    assert s.status == S.void_requested
    svc.tick(SHOP)
    assert svc.store.get(SHOP, s.id).status == S.voided
    assert sum(1 for m, p in es_server.requests if p.endswith("/cancel")) == 1


def test_parcel2go_labels_offer_no_cancel(store, shopify, clock):
    p = FakeProvider()
    one = Providers([p])
    svc = ShippingService(store, shopify, one, Purchases(store, one, clock=clock), clock=clock)
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    (s,) = svc.store.shipments(SHOP)
    s = answer_all_first_time(svc, s)
    svc.buy(SHOP, s.id, svc.preview(SHOP, s.id)["basis"], "george", "k1")
    s = svc.store.get(SHOP, s.id)
    assert s is not None and not svc.can_cancel(s)
    with pytest.raises(ActionError):
        svc.cancel_label(SHOP, s.id, "george")


def test_a_tracking_number_that_arrives_later_reaches_shopify(svc, shopify, es_server, clock):
    es_server.tracking_after_buy = False
    s = bought(svc, shopify)
    assert s.status == S.label_purchased and s.label.tracking_number is None
    clock.advance(minutes=3)
    svc.purchases.reconcile_all()  # customs settled: documents aren't read again after this
    assert svc.store.get(SHOP, s.id).label.customs_confirmed
    es_server.shipments["ESGG1001"]["trackings"] = [{"tracking_number": "RM999GB", "leg_number": 1}]
    svc.tick(SHOP)
    s = svc.store.get(SHOP, s.id)
    assert s.label.tracking_number == "RM999GB" and s.status == S.fulfilled
    assert len(es_server.charges) == 1


def test_the_easyship_balance_is_read_for_setup(es):
    assert es.account() == {"balance": 50.0, "currency": "GBP"}
