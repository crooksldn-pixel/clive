"""The Parcel2Go adapter against a stand-in server shaped like the sandbox's real answers."""

import httpx
import pytest

from shipping.documents import print_plan
from shipping.models import (
    CustomsMode,
    DocumentKind,
    DutiesTerms,
    PageSize,
)
from shipping.providers.base import ProviderRefused, ProviderUnavailable, ProviderUncertain
from shipping.providers.parcel2go import region, split_address
from shipping.purchase import Purchases

from .conftest import SHOP, make_shipment
from .fake_p2g import COUNTRIES


def test_quotes_keep_door_delivery_that_fits(p2g, store, provider):
    s = make_shipment(store, provider)
    qs = p2g.quotes(s)
    assert [(q.carrier, q.service_code, q.amount.minor) for q in qs] == [
        ("DPD", "dpd-classic", 1069),
        ("Evri", "myhermes-international-parcelshop", 660),
    ]
    assert qs[0].est_days_max == 2 and qs[0].ship_date == "2026-10-06"


def test_the_order_carries_customs_facts_in_parcel2go_terms(p2g, store, provider, server, cfg):
    s = make_shipment(store, provider)
    s.quote = p2g.quotes(s)[0]
    p2g.create_order(s, s.quote, "op_1")
    item = server.bodies[-1]["Items"][0]
    contents = item["Parcels"][0]["Contents"]
    assert contents == [
        {
            "Description": "Men's cotton T-shirt",
            "Quantity": 2,
            "EstimatedValue": 74.0,
            "TariffCode": "610910",
            "OriginCountry": "Portugal",
        }
    ]  # a name, as Parcel2Go requires
    assert item["ExportReason"] == "Sale" and item["Service"] == "dpd-classic"
    assert item["Parcels"][0]["DeliveryAddress"]["CountryIsoCode"] == "DEU"
    assert item["CollectionAddress"]["Postcode"] == "SL8 5AS"
    assert item["Reference"] == "CROOKS-2145 op_1" and item["CollectionDate"].startswith(
        "2026-10-06"
    )
    assert "IOSSCode" not in item and "EoriNumber" not in item  # nothing invented


def test_ioss_and_eori_are_sent_only_when_they_exist(p2g, store, provider, server, cfg):
    cfg.eori_number = "GB123456789000"
    s = make_shipment(store, provider)
    s.duties = DutiesTerms(
        incoterm="DAP", ioss_number="IM2760000000", recipient_may_pay=True, summary="x"
    )
    p2g.create_order(s, p2g.quotes(s)[0], "op_1")
    item = server.bodies[-1]["Items"][0]
    assert item["IOSSCode"] == "IM2760000000" and item["EoriNumber"] == "GB123456789000"


@pytest.mark.parametrize(
    ("fault", "kind"),
    [
        ("connect", ProviderUnavailable),
        ("timeout_after_charge", ProviderUncertain),
        ("500", ProviderUncertain),
        ("refuse", ProviderRefused),
    ],
)
def test_payment_failures_are_sorted_by_what_may_have_happened(
    p2g, store, provider, server, fault, kind
):
    s = make_shipment(store, provider)
    order = p2g.create_order(s, p2g.quotes(s)[0], "op_1")
    server.pay_fault = fault
    with pytest.raises(kind):
        p2g.pay(order.ref)


def test_reads_never_count_as_uncertain(p2g, server, monkeypatch):
    def broken(request):
        raise httpx.ReadTimeout("slow", request=request)

    p2g._countries = [COUNTRIES[0]]
    p2g._token = ("t", 9e12)
    p2g._http = httpx.Client(transport=httpx.MockTransport(broken))
    with pytest.raises(ProviderUnavailable):
        p2g.read_order("p2g:1:2:h")


def paid_order(p2g, store, provider, service="dpd-classic"):
    s = make_shipment(store, provider)
    quote = p2g.quotes(s)[0].model_copy(update={"service_code": service})
    order = p2g.create_order(s, quote, "op_1")
    p2g.pay(order.ref)
    return order


def test_documents_need_a_paid_order(p2g, store, provider, server):
    s = make_shipment(store, provider)
    order = p2g.create_order(s, p2g.quotes(s)[0], "op_1")
    with pytest.raises(ProviderRefused):
        p2g.documents(order.ref)


def test_the_label_is_the_genuine_4x6_and_ids_are_kept(p2g, store, provider, server):
    order = paid_order(p2g, store, provider)
    docs = p2g.documents(order.ref)
    label = docs.find(DocumentKind.shipping_label)
    assert label.page_size == PageSize.label_4x6 and label.pages == 1 and label.must_print
    assert docs.tracking_number == "P2G45800"  # the sandbox gives no courier number
    assert docs.tracking_url == "https://p2g.test/track/45800"
    assert docs.provider_ids == {"order": "26700", "order_line": "45800"}


def test_paperless_customs_prints_only_the_label(p2g, store, provider, server):
    docs = p2g.documents(paid_order(p2g, store, provider, "dpd-classic").ref)
    assert docs.customs == CustomsMode.electronic
    invoice = docs.find(DocumentKind.commercial_invoice)
    assert invoice.electronic and not invoice.must_print and invoice.pages == 1


@pytest.mark.parametrize(
    ("service", "copies"), [("myhermes-international-parcelshop", 3), ("ups-access-point", 4)]
)
def test_paper_customs_asks_for_the_copies_returned(p2g, store, provider, server, service, copies):
    docs = p2g.documents(paid_order(p2g, store, provider, service).ref)
    assert docs.customs == CustomsMode.paper
    invoice = docs.find(DocumentKind.commercial_invoice)
    assert invoice.must_print and invoice.attach_to_parcel and invoice.copies_required == copies
    assert invoice.page_size == PageSize.a4 and "Customs Documents" in invoice.note


@pytest.mark.parametrize(
    "break_it",
    [
        lambda server: server.labels_override.update(AdditionalDocuments=httpx.Response(503)),
        lambda server: setattr(server, "all_extra_pages", 3),  # 404, but "All" has more
        lambda server: server.labels_override.update(AdditionalDocuments="garbage"),
        lambda server: server.labels_override.update(All=httpx.Response(500)),
    ],
    ids=["additional-503", "views-disagree", "additional-not-a-pdf", "all-500"],
)
def test_customs_is_unknown_not_paperless_without_evidence(p2g, store, provider, server, break_it):
    order = paid_order(p2g, store, provider, "dpd-classic")
    break_it(server)
    docs = p2g.documents(order.ref)
    assert docs.customs == CustomsMode.unknown
    assert docs.find(DocumentKind.shipping_label) is not None  # the label itself is fine


def test_a_label_that_is_not_a_pdf_is_not_ready(p2g, store, provider, server):
    order = paid_order(p2g, store, provider)
    server.labels_override["Labels"] = "garbage"
    with pytest.raises(ProviderUnavailable, match="isn't ready"):
        p2g.documents(order.ref)


def test_lost_reply_through_the_real_adapter_charges_once(p2g, store, provider, server, clock):
    s = make_shipment(store, provider)
    s.quote = p2g.quotes(s)[0]
    store.save(s)
    purchases = Purchases(store, p2g, clock=clock)
    server.pay_fault = "timeout_after_charge"
    b = purchases.preview(SHOP, s.id)["basis"]
    out = purchases.buy(SHOP, s.id, b, "george", "k1")
    assert out["status"] == "label_purchased" and out["charged"]
    assert len(server.charges) == 1  # read back PaidDate, never paid again
    plan = print_plan(out["shipment"].label)
    assert plan.ready and plan.lines[0].text == "Shipping label — 4×6 thermal"


@pytest.mark.parametrize(
    ("line1", "line2", "expected"),
    [
        ("12 Brick Lane", "", ("12", "Brick Lane")),
        ("Torstrasse 12", "", ("12", "Torstrasse")),
        ("Via Roma 5, 2B", "", ("5, 2B", "Via Roma")),
        ("221B Baker Street", "", ("221B", "Baker Street")),
        ("Rose Cottage, High Street", "", ("Rose Cottage", "High Street")),
        ("Unit M", "Bourne End Business Park", ("Unit M", "Bourne End Business Park")),
        ("", "5 Rue de Rivoli", ("5", "Rue de Rivoli")),
    ],
)
def test_one_address_line_is_split_not_repeated(line1, line2, expected):
    assert split_address(line1, line2) == expected


def test_the_destination_street_is_not_doubled(p2g, store, provider, server):
    s = make_shipment(store, provider)
    p2g.create_order(s, p2g.quotes(s)[0], "op_1")
    to = server.bodies[-1]["Items"][0]["Parcels"][0]["DeliveryAddress"]
    assert (to["Property"], to["Street"]) == ("12", "Torstrasse")


def test_origin_is_the_country_not_a_region_that_shares_its_code(p2g):
    # Madeira's row has PT too; the invoice must still say Portugal.
    assert p2g._country_name("PT") == "Portugal"
    assert p2g._country_name("GB") == "United Kingdom"
    assert p2g._country_name("ES") == "Spain"
    assert p2g._country_name("US") == "United States"
    assert p2g._iso3("PT") == "PRT"


def test_a_postcode_in_a_priced_region_is_sent_as_that_region(p2g, store, provider, server):
    s = make_shipment(store, provider)
    s.destination = s.destination.model_copy(
        update={"country": "PT", "postcode": "9000-018", "line1": "Rua da Alfandega 10"}
    )
    p2g.quotes(s)
    assert server.bodies[-1]["DeliveryAddress"]["Subdivision"] == "PT-30"
    assert "Subdivision" not in server.bodies[-1]["CollectionAddress"]
    p2g.create_order(s, p2g.quotes(s)[0], "op_1")
    to = server.bodies[-1]["Items"][0]["Parcels"][0]["DeliveryAddress"]
    assert to["Subdivision"] == "PT-30" and to["CountryIsoCode"] == "PRT"


@pytest.mark.parametrize(
    ("country", "postcode", "expected"),
    [
        ("PT", "1100-148", None),  # Lisbon
        ("PT", "9000-018", "PT-30"),  # Funchal
        ("ES", "28013", None),  # Madrid
        ("ES", "07001", None),  # Palma: Parcel2Go has no code, prices it as the mainland
        ("ES", "38001", "ES-TEN"),
        ("ES", "35500", "ES-GC"),  # Lanzarote isn't in this list, so the Canaries row
        ("GB", "SL8 5AS", None),  # the old regex test put every UK postcode in NI
        ("GB", "BT1 1AA", "NIR"),
        ("GB", "PA2 6AA", None),  # Paisley, not the islands
        ("DE", "10115", None),
    ],
)
def test_the_postcode_decides_the_region(p2g, country, postcode, expected):
    assert p2g._subdivision(country, postcode) == expected


@pytest.mark.parametrize(
    ("country", "postcode", "expected"),
    [
        ("ES", "35001", ("ES-GRC", "ES-GC")),
        ("ES", "35600", ("ES-FU", "ES-GC")),
        ("ES", "38760", ("ES-LP", "ES-GC")),
        ("ES", "51001", ("ES-CE",)),
        ("PT", "9500-150", ("PT-20",)),
        ("IT", "90133", ("IT-SI",)),
        ("IT", "09124", ("IT-SA",)),
        ("IT", "00184", ()),
        ("GB", "PA20 0AA", ("HIGH",)),
        ("GB", "HS1 2AA", ("HIGH",)),
        ("GB", "IM1 1AA", ("IOM",)),
    ],
)
def test_region_rules(country, postcode, expected):
    assert region(country, postcode) == expected


def test_a_region_parcel2go_stopped_listing_is_refused_not_priced_as_mainland(p2g):
    with pytest.raises(ProviderRefused, match="region"):
        p2g._subdivision("IT", "90133")  # Sicily isn't in this stand-in list
