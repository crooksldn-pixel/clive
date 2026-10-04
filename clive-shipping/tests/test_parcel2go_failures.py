"""Parcel2Go misbehaving: every 4xx, 5xx, lost or malformed answer ends in a state staff can act
on, and never in a second charge or a corrupted shipment. Plus countries: ISO inside, Parcel2Go's
names at the boundary, and a cached list so CLIVE doesn't depend on that endpoint being up."""

import base64

import httpx
import pytest

from shipping.documents import print_plan
from shipping.models import CustomsMode, DocumentKind, OpState
from shipping.models import ShipmentStatus as S
from shipping.providers.base import ProviderRefused, ProviderUnavailable
from shipping.providers.parcel2go import balance
from shipping.purchase import ActionError, Purchases

from .conftest import SHOP, make_shipment
from .fake_p2g import COUNTRIES
from .fake_p2g import adapter as fake_adapter
from .pdfs import A4, pdf


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


# ------------------------------------------------------------------ customs evidence strength


def paid_ref(p2g, store, provider, service="dpd-classic"):
    s = make_shipment(store, provider)
    quote = p2g.quotes(s)[0].model_copy(update={"service_code": service})
    order = p2g.create_order(s, quote, "op_1")
    p2g.pay(order.ref)
    return order.ref


@pytest.mark.parametrize(
    ("detail", "answer"),
    [
        ("AdditionalDocuments", "empty"),  # a 200 with no documents is not a 404
        ("AdditionalDocuments", "objstm"),  # a PDF we can't count
        ("AdditionalDocuments", "two_files"),  # several files: we'd only keep one
        ("CommercialInvoice", httpx.Response(503)),  # the invoice view failed
        ("CommercialInvoice", "empty"),
    ],
    ids=[
        "additional-empty",
        "additional-uncountable",
        "additional-two-files",
        "invoice-503",
        "invoice-empty",
    ],
)
def test_anything_short_of_clear_evidence_is_not_paperless(
    p2g, store, provider, server, detail, answer
):
    ref = paid_ref(p2g, store, provider, "dpd-classic")
    server.labels_override[detail] = answer
    assert p2g.documents(ref).customs == CustomsMode.unknown


def test_paperless_is_shown_at_once_then_confirmed_by_a_later_look(purchases, ready, server, clock):
    out = buy(purchases, ready)
    s = purchases.store.get(SHOP, ready.id)
    assert out["charged"] and print_plan(s.label).ready  # feels domestic straight away
    op = purchases.store.op_by_key(SHOP, "k1")
    assert op.state == OpState.paid and not s.label.customs_confirmed  # one more look to come
    purchases.reconcile_all()  # too soon to count as a second look
    assert purchases.store.op_by_key(SHOP, "k1").state == OpState.paid
    clock.advance(minutes=3)
    purchases.reconcile_all()
    s = purchases.store.get(SHOP, ready.id)
    assert s.label.customs_confirmed and purchases.store.op_by_key(SHOP, "k1").state == OpState.done
    assert len(server.charges) == 1


def test_paperwork_that_appears_after_the_label_switches_to_paper_and_says_so(
    purchases, ready, server, clock
):
    buy(purchases, ready)
    server.copies["dpd"] = 2  # the carrier generates customs paperwork late
    clock.advance(minutes=3)
    purchases.reconcile_all()
    s = purchases.store.get(SHOP, ready.id)
    invoice = s.label.document(DocumentKind.commercial_invoice)
    assert (
        s.label.customs == CustomsMode.paper and invoice.must_print and invoice.copies_required == 2
    )
    assert any("appeared after the label" in a for a in s.alerts)
    assert print_plan(s.label).lines[-1].text == "Commercial invoice — print 2 copies (A4)"
    assert len(server.charges) == 1


def test_multi_page_invoices_are_counted_as_copies(p2g, store, provider, server):
    server.invoice_pages = 2  # each invoice is two pages long; 3 copies = 6 pages
    ref = paid_ref(p2g, store, provider, "myhermes-international-parcelshop")
    docs = p2g.documents(ref)
    invoice = docs.find(DocumentKind.commercial_invoice)
    assert docs.customs == CustomsMode.paper
    assert invoice.must_print and invoice.pages == 6 and invoice.copies_required == 3


def test_pages_that_are_not_whole_invoices_are_printed_as_given(p2g, store, provider, server):
    # A 2-page invoice but 5 extra pages: not "copies" of it. Print what Parcel2Go returned.
    server.copies["myhermes"] = 5  # 5 single pages of additional documents
    server.labels_override["CommercialInvoice"] = httpx.Response(
        200, json={"Base64EncodedLabels": [base64.b64encode(pdf(A4, A4)).decode()]}
    )
    server.all_extra_pages = 1  # "All": label + 2-page invoice + 5 = 8 pages
    ref = paid_ref(p2g, store, provider, "myhermes-international-parcelshop")
    docs = p2g.documents(ref)
    other = docs.find(DocumentKind.other_documents)
    assert docs.customs == CustomsMode.paper
    assert other.must_print and other.pages == 5 and other.copies_required == 1


def test_when_in_doubt_a_route_needs_customs(p2g, store, provider, server):
    ref = paid_ref(p2g, store, provider, "myhermes-international-parcelshop")
    server.faults["read"] = httpx.Response(
        200,
        json={"PaidDate": "2026-10-05T10:00:00", "TotalPrice": 10.69},  # no Items
    )
    assert p2g.documents(ref).customs != CustomsMode.not_required


def test_a_domestic_route_needs_no_customs(p2g, store, provider, server):
    s = make_shipment(store, provider)
    s.destination = s.destination.model_copy(
        update={"country": "GB", "postcode": "E1 6AN", "line1": "1 Brick Lane", "city": "London"}
    )
    quote = p2g.quotes(s)[0].model_copy(update={"service_code": "dpd-classic"})
    order = p2g.create_order(s, quote, "op_1")
    p2g.pay(order.ref)
    assert p2g.documents(order.ref).customs == CustomsMode.not_required


def test_odd_optional_fields_never_lose_the_label(p2g, store, provider, server):
    ref = paid_ref(p2g, store, provider)
    oid = ref.split(":")[1]
    real = server.__call__

    def odd(request):
        answer = real(request)
        body = answer.json()
        body["Links"] = ["not", "a", "dict"]
        return httpx.Response(200, json=body)

    server.faults["read"] = odd
    server.faults["parcelnumbers"] = httpx.Response(200, json={"TrackingNumbers": 7})
    docs = p2g.documents(ref)
    assert docs.find(DocumentKind.shipping_label) is not None
    assert docs.tracking_number == "P2G45800" and oid


@pytest.mark.parametrize("answer", [None, {"Balance": 5}, "abc", True])
def test_balance_is_never_made_up(p2g, server, answer):
    server.faults["prepay"] = httpx.Response(200, json=answer)
    assert balance(p2g) is None
