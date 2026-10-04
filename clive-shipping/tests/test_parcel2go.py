"""The Parcel2Go adapter against a stand-in server shaped like the sandbox's real answers."""

import json

import httpx
import pytest

from shipping.models import Address, DutiesTerms, ShopConfig
from shipping.providers.base import ProviderRefused, ProviderUnavailable, ProviderUncertain
from shipping.providers.parcel2go import Parcel2Go, region, split_address
from shipping.purchase import Purchases

from .conftest import SHOP, make_shipment

# Shaped like the sandbox's list: regions come as extra rows of the same country, some before
# the main row, each recognised by postcode.
COUNTRIES = [
    {"Name": "UK - Mainland", "Iso3Code": "GBR", "Iso2Code": "GB", "Subdivision": None},
    {
        "Name": "Northern Ireland",
        "Iso3Code": "GBR",
        "Iso2Code": "GB",
        "Subdivision": "NIR",
        "PostcodeRegex": "^.*$",  # a format check, not a region test
    },
    {"Name": "Germany", "Iso3Code": "DEU", "Iso2Code": "DE", "Subdivision": None},
    {"Name": "Portugal", "Iso3Code": "PRT", "Iso2Code": "PT", "Subdivision": None},
    {
        "Name": "Madeira",
        "Iso3Code": "PRT",
        "Iso2Code": "PT",
        "Subdivision": "PT-30",
        "PostcodeRegex": "^.*$",
    },
    {
        "Name": "Tenerife",
        "Iso3Code": "ESP",
        "Iso2Code": "ES",
        "Subdivision": "ES-TEN",
        "PostcodeRegex": "^[0-9]{5}$",
    },
    {
        "Name": "Canary Islands",
        "Iso3Code": "ESP",
        "Iso2Code": "ES",
        "Subdivision": "ES-GC",
        "PostcodeRegex": "^[0-9]{5}$",
    },
    {"Name": "Spain (Mainland Only)", "Iso3Code": "ESP", "Iso2Code": "ES", "Subdivision": None},
    {"Name": "USA", "Iso3Code": "USA", "Iso2Code": "US", "Subdivision": None},
]


def quote(
    slug, courier, price, delivery="Door", max_w=None, collection="2026-10-06", est="2026-10-08"
):
    return {
        "Service": {
            "Slug": slug,
            "Name": slug.title(),
            "CourierSlug": courier,
            "CourierName": courier.title(),
            "CollectionType": "Shop",
            "DeliveryType": delivery,
            "IsPrinterRequired": True,
            "MaxWeight": max_w,
            "MaxLength": 1.2,
        },
        "TotalPrice": price,
        "Collection": f"{collection}T00:00:00",
        "EstimatedDeliveryDate": f"{est}T00:00:00",
    }


class FakeP2G:
    def __init__(self):
        self.orders: dict[str, dict] = {}
        self.charges: list[str] = []
        self.bodies: list[dict] = []
        self.pay_fault: str | None = None  # connect | timeout_after_charge | 500 | refuse

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        if path == "/auth/connect/token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 7200})
        if path == "/api/countries":
            return httpx.Response(200, json=COUNTRIES)
        if path == "/api/quotes":
            self.bodies.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "Quotes": [
                        quote("dpd-classic", "dpd", 10.69),
                        quote(
                            "myhermes-international-parcelshop", "myhermes", 6.6, est="2026-10-14"
                        ),
                        quote(
                            "ups-shop-to-shop", "ups", 5.0, delivery="Shop"
                        ),  # recipient collects
                        quote("tiny", "dpd", 3.0, max_w=0.2),  # too light a limit for our parcel
                    ]
                },
            )
        if path == "/api/orders/verify":
            self.bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"Errors": [], "Cost": 10.69})
        if path == "/api/orders" and method == "POST":
            body = json.loads(request.content)
            self.bodies.append(body)
            oid = str(26700 + len(self.orders))
            self.orders[oid] = {"paid": False}
            return httpx.Response(
                200,
                json={
                    "OrderId": oid,
                    "Hash": "h/+=",
                    "TotalPrice": 10.69,
                    "OrderlineIdMap": [{"OrderLineId": "45800"}],
                },
            )
        if path.endswith("/paywithprepay"):
            oid = path.split("/")[3]
            fault, self.pay_fault = self.pay_fault, None
            if fault == "connect":
                raise httpx.ConnectError("refused", request=request)
            if fault == "refuse":
                return httpx.Response(
                    400, json={"Errors": [{"Name": "Balance", "Description": "Not enough"}]}
                )
            self.orders[oid]["paid"] = True
            self.charges.append(oid)  # charges every time, like the real one
            if fault == "timeout_after_charge":
                raise httpx.ReadTimeout("lost", request=request)
            if fault == "500":
                return httpx.Response(502)
            return httpx.Response(200, json={"Links": []})
        if path == "/api/orders" and method == "GET":
            oid = request.url.params["orderId"]
            paid = self.orders[oid]["paid"]
            return httpx.Response(
                200,
                json={
                    "PaidDate": "2026-10-05T10:00:00" if paid else None,
                    "TotalPrice": 10.69,
                    "Links": {
                        "labels-4x6": "https://p2g.test/label/x?m=1",
                        "labels-a4": "https://p2g.test/label/x?m=0",
                        "tracking-page": "https://p2g.test/track/45800",
                    },
                },
            )
        if path.startswith("/label/"):
            return httpx.Response(200, content=b"%PDF-1.4 label " + request.url.query)
        if path.endswith("/parcelnumbers"):
            return httpx.Response(200, json={"TrackingNumbers": [{"TrackingNumber": None}]})
        if path == "/api/prepay":
            return httpx.Response(200, json=50.0)
        return httpx.Response(404)


@pytest.fixture
def server():
    return FakeP2G()


@pytest.fixture
def cfg():
    return ShopConfig(
        shop=SHOP,
        origin=Address(
            name="CROOKS LDN",
            line1="Unit M",
            line2="Bourne End Business Park",
            city="Bourne End",
            postcode="SL8 5AS",
            country="GB",
            phone="07700900000",
            email="team@crooksldn.com",
        ),
    )


@pytest.fixture
def p2g(server, cfg, clock):
    return Parcel2Go(
        "https://p2g.test",
        "id",
        "secret",
        config=lambda shop: cfg,
        http=httpx.Client(transport=httpx.MockTransport(server)),
        clock=clock,
    )


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


def test_documents_need_a_paid_order(p2g, store, provider, server):
    s = make_shipment(store, provider)
    order = p2g.create_order(s, p2g.quotes(s)[0], "op_1")
    with pytest.raises(ProviderRefused):
        p2g.documents(order.ref)
    p2g.pay(order.ref)
    docs = p2g.documents(order.ref)
    assert docs.label_4x6.startswith(b"%PDF") and docs.label_a4.startswith(b"%PDF")
    assert docs.tracking_number == "P2G45800"  # sandbox gives no courier number yet
    assert docs.tracking_url == "https://p2g.test/track/45800"


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
    assert set(out["shipment"].label.artifacts) == {"label_4x6", "label_a4"}


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
