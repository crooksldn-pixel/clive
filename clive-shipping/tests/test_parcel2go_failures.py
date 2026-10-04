"""Parcel2Go misbehaving: every 4xx, 5xx, lost or malformed answer ends in a state staff can act
on, and never in a second charge or a corrupted shipment. Plus countries: ISO inside, Parcel2Go's
names at the boundary, and a cached list so CLIVE doesn't depend on that endpoint being up."""

import httpx
import pytest

from shipping.models import OpState
from shipping.models import ShipmentStatus as S
from shipping.providers.base import ProviderRefused, ProviderUnavailable
from shipping.purchase import ActionError, Purchases

from .conftest import SHOP, make_shipment
from .fake_p2g import COUNTRIES
from .fake_p2g import adapter as fake_adapter


@pytest.fixture
def ready(p2g, store, provider):
    """A ready shipment whose quote came from the Parcel2Go adapter."""
    s = make_shipment(store, provider)
    s.quote = p2g.quotes(s)[0]
    return store.save(s)


@pytest.fixture
def purchases(store, p2g, clock):
    return Purchases(store, p2g, clock=clock)


def buy(purchases, s, key="k1"):
    b = purchases.preview(SHOP, s.id)["basis"]
    return purchases.buy(SHOP, s.id, b, "george", key)


# ------------------------------------------------------------------ countries


def test_country_is_iso_inside_and_parcel2go_outside(p2g):
    pt = p2g.place("PT", "9000-018")
    assert (pt.iso2, pt.iso3, pt.name, pt.subdivision) == ("PT", "PRT", "Portugal", "PT-30")
    assert p2g.place("GB").name == "United Kingdom" and p2g.place("US").name == "United States"
    with pytest.raises(ProviderRefused):
        p2g.place("ZZ")


def test_the_country_list_is_cached_and_survives_parcel2go_being_down(server, cfg, clock, store):
    def adapter():
        return fake_adapter(server, cfg, clock, cache=store)

    assert adapter().place("DE").iso3 == "DEU"  # fetched once, stored
    server.faults["countries"] = httpx.Response(503)
    assert adapter().place("DE").iso3 == "DEU"  # fresh cache: no call made
    clock.advance(days=8)  # stale now, and Parcel2Go is down
    server.faults["countries"] = httpx.Response(503)
    assert adapter().place("DE").iso3 == "DEU"  # the stale copy beats nothing
    cached, at = store.reference("Parcel2Go", "countries")
    assert len(cached) == len(COUNTRIES) and at < clock()
    adapter().place("DE")  # up again after the TTL: refreshed
    assert store.reference("Parcel2Go", "countries")[1] == clock()


def test_no_country_list_at_all_is_unavailable_not_a_crash(server, cfg, clock):
    p = fake_adapter(server, cfg, clock)
    server.faults["countries"] = "garbage"
    with pytest.raises(ProviderUnavailable):
        p.place("DE")


# ------------------------------------------------------------------ quotes and price


@pytest.mark.parametrize("fault", ["garbage", httpx.Response(500), httpx.Response(200, json=[])])
def test_unreadable_quotes_are_unavailable(p2g, store, provider, server, fault):
    s = make_shipment(store, provider)
    server.faults["quotes"] = fault
    with pytest.raises(ProviderUnavailable):
        p2g.quotes(s)


def test_a_quote_row_without_a_price_is_skipped(p2g, store, provider, server):
    s = make_shipment(store, provider)

    def one_bad_row(request):
        return httpx.Response(
            200,
            json={
                "Quotes": [
                    {"Service": {"Slug": "dpd-classic", "DeliveryType": "Door"}},  # no price
                    {"TotalPrice": 6.6},  # no service
                ]
            },
        )

    server.faults["quotes"] = one_bad_row
    assert p2g.quotes(s) == []


@pytest.mark.parametrize(
    "fault",
    ["garbage", httpx.Response(200, json={"Errors": []}), httpx.Response(503)],
    ids=["garbage", "no-cost", "503"],
)
def test_a_price_check_that_fails_never_reads_as_free(purchases, ready, server, fault):
    server.faults["verify"] = fault
    with pytest.raises(ActionError) as e:
        purchases.preview(SHOP, ready.id)
    assert e.value.status == 503 and "Nothing was bought" in str(e.value)
    assert purchases.store.get(SHOP, ready.id).quote.amount.minor == 1069  # not £0


def test_a_refusal_at_the_price_check_is_the_providers_reason(purchases, ready, server):
    server.faults["verify"] = httpx.Response(
        200, json={"Errors": [{"Error": "Receivers (DNI) Number is required"}], "Cost": 0}
    )
    with pytest.raises(ActionError) as e:
        purchases.preview(SHOP, ready.id)
    assert e.value.status == 422 and "DNI" in str(e.value)


# ------------------------------------------------------------------ creating the order


@pytest.mark.parametrize(
    ("fault", "says"),
    [
        (httpx.Response(400, json={"Errors": [{"Error": "Please enter the county"}]}), "county"),
        (httpx.Response(500), "didn't confirm"),
        ("garbage", "didn't confirm"),
        (httpx.Response(200, json={"OrderId": "1", "Hash": "h"}), "didn't confirm"),  # no price
        (httpx.Response(200, json={"OrderId": "1", "Hash": "h", "TotalPrice": 0}), "didn't"),
        (httpx.Response(200, json={"Hash": "h", "TotalPrice": 10.69}), "no usable order"),
    ],
    ids=["400", "500", "garbage", "no-price", "zero-price", "no-order-id"],
)
def test_a_bad_order_answer_pays_nothing_and_says_why(purchases, ready, server, fault, says):
    server.faults["create"] = fault
    out = buy(purchases, ready)
    assert out["operation_state"] == "failed" and not out["charged"]
    assert out["status"] == "ready" and says in out["error"]
    assert server.charges == []
    out = buy(purchases, ready, key="k2")  # Parcel2Go recovers: the next buy works
    assert out["charged"] and len(server.charges) == 1


# ------------------------------------------------------------------ paying


@pytest.mark.parametrize(
    ("fault", "charged"),
    [
        ("connect", 0),  # never delivered
        ("refuse", 0),  # 400: not charged
        ("timeout_after_charge", 1),  # charged, reply lost
        ("500", 1),  # charged, then 502
        ("garbage_after_charge", 1),  # charged, reply unreadable
    ],
)
def test_every_payment_failure_ends_with_the_truth(purchases, ready, server, fault, charged):
    server.pay_fault = fault
    out = buy(purchases, ready)
    assert len(server.charges) == charged  # never more than once
    s = purchases.store.get(SHOP, ready.id)
    if charged:
        assert out["charged"] and s.status == S.label_purchased and s.label.complete
    else:
        assert not out["charged"] and s.status == S.ready and s.last_error
        assert "weren't charged" in s.last_error


def test_a_read_back_that_does_not_say_paid_or_not_stays_unknown(purchases, ready, server, clock):
    server.pay_fault = "timeout_after_charge"
    server.faults["read"] = httpx.Response(200, json={"TotalPrice": 10.69})  # no PaidDate
    out = buy(purchases, ready)
    assert out["status"] == "reconciliation_required" and out["may_have_been_charged"]
    op = purchases.store.op_by_key(SHOP, "k1")
    assert op.state == OpState.pay_unknown and op.unpaid_reads == []  # not counted as "no"
    with pytest.raises(ActionError):
        buy(purchases, ready, key="k2")  # can't buy again while unknown
    clock.advance(minutes=5)
    purchases.reconcile_all()
    assert purchases.store.get(SHOP, ready.id).status == S.label_purchased
    assert len(server.charges) == 1


def test_the_double_click_through_the_real_adapter_charges_once(purchases, ready, server):
    b = purchases.preview(SHOP, ready.id)["basis"]
    first = purchases.buy(SHOP, ready.id, b, "george", "k1")
    again = purchases.buy(SHOP, ready.id, b, "george", "k1")  # same click, replayed
    assert again["replayed"] and again["operation"] == first["operation"]
    with pytest.raises(ActionError):
        purchases.buy(SHOP, ready.id, b, "george", "k2")  # a second click, new key
    assert len(server.charges) == 1 and len(server.orders) == 1


def test_a_stale_fingerprint_sends_nothing_to_parcel2go(purchases, ready, server):
    b = purchases.preview(SHOP, ready.id)["basis"]
    s = purchases.store.get(SHOP, ready.id)
    s.destination = s.destination.model_copy(update={"postcode": "10117"})
    purchases.store.save(s)
    with pytest.raises(ActionError, match="changed"):
        purchases.buy(SHOP, ready.id, b, "george", "k1")
    assert server.orders == {} and server.charges == []


def test_a_document_failure_after_paying_keeps_the_label_and_retries(purchases, ready, server):
    server.labels_override["Labels"] = httpx.Response(500)
    out = buy(purchases, ready)
    s = purchases.store.get(SHOP, ready.id)
    assert out["charged"] and s.status == S.label_purchased and not s.label.complete
    assert "documents haven't arrived" in s.last_error
    server.labels_override.clear()
    purchases.reconcile_all()
    s = purchases.store.get(SHOP, ready.id)
    assert s.label.complete and not s.last_error and len(server.charges) == 1


@pytest.mark.parametrize("charged", [False, True])
def test_a_2xx_payment_answer_with_errors_is_read_back_not_trusted(
    purchases, ready, server, clock, charged
):
    def pay_answer_with_errors(request):
        oid = request.url.path.split("/")[3]
        if charged:
            server.orders[oid]["paid"] = True
            server.charges.append(oid)
        return httpx.Response(200, json={"Errors": [{"Description": "Something went wrong"}]})

    server.faults["pay"] = pay_answer_with_errors
    out = buy(purchases, ready)
    assert out["may_have_been_charged"] or out["charged"]
    for _ in range(2):
        clock.advance(minutes=3)
        purchases.reconcile_all()
    s = purchases.store.get(SHOP, ready.id)
    if charged:
        assert s.status == S.label_purchased and s.label.complete and len(server.charges) == 1
    else:
        assert s.status == S.ready and "weren't charged" in s.last_error
        assert server.charges == []
