"""The rate recommendation rule (shipping/rates.py), case by case."""

from datetime import UTC, datetime

import pytest

from shipping.fake_shopify import FakeShopify, fo, tee_line
from shipping.models import CustomsMode, Quote
from shipping.money import Money
from shipping.purchase import Purchases
from shipping.rates import Option, Paperwork, recommend, sandbox_paperwork
from shipping.service import ShippingService

from .conftest import SHOP
from .test_stage2 import answer_all_first_time, only

AT = datetime(2026, 10, 5, tzinfo=UTC)


def must(option: Option | None) -> Option:
    assert option is not None
    return option


def q(code, carrier, pence, days=None):
    return Quote(
        provider="Parcel2Go",
        carrier=carrier,
        service_code=code,
        service_name=code,
        amount=Money(minor=pence),
        est_days_max=days,
        generated_at=AT,
    )


EVRI = q("myhermes-international-parcelshop", "Evri", 660, 9)  # paper, 3 copies
DPD = q("dpd-classic", "DPD", 700, 6)  # paperless
UPS = q("ups-access-point-euro", "UPS", 620, 6)  # paper, 4 copies
FEDEX = q("fedex-world-express", "FedEx", 2788, 2)
LANDMARK = q("landmark-dropoff", "Landmark", 1280, 20)


def test_a_few_pence_cheaper_with_a4_paperwork_loses_to_paperless():
    # UPS is £0.80 cheaper than DPD but means printing 4 A4 invoices; within £1, so DPD wins.
    rec = recommend([UPS, DPD])
    assert must(rec.recommended).quote is DPD
    assert "no customs paperwork" in must(rec.recommended).reason
    assert (
        must(rec.cheapest).quote is UPS
        and "4 a4 customs copies" in must(rec.cheapest).reason.lower()
    )


def test_paperless_is_never_chosen_when_materially_dearer():
    dear_dpd = q("dpd-classic", "DPD", 900, 6)  # £2.80 more than UPS: beyond max(£1, 10%)
    rec = recommend([UPS, dear_dpd])
    assert must(rec.recommended).quote is UPS and rec.cheapest is None


def test_the_allowance_grows_with_the_price():
    # Cheapest £20.00 (paper): 10% = £2.00 allowance, so a £21.50 paperless service is comparable.
    paper = q("ups-access-point-express", "UPS", 2000, 5)
    paperless = q("dpd-pickup-air-classic", "DPD", 2150, 6)
    assert must(recommend([paper, paperless]).recommended).quote is paperless
    pricier = q("dpd-pickup-air-classic", "DPD", 2250, 6)  # £2.50 more: not comparable
    assert must(recommend([paper, pricier]).recommended).quote is paper


def test_slow_services_are_not_recommended_while_reasonable_ones_exist():
    cheap_but_slow = q("landmark-dropoff", "Landmark", 500, 20)
    rec = recommend([cheap_but_slow, DPD])
    assert must(rec.recommended).quote is DPD
    assert (
        must(rec.cheapest).quote is cheap_but_slow and "up to 20 days" in must(rec.cheapest).reason
    )


def test_when_nothing_has_a_reasonable_estimate_everything_is_considered():
    rec = recommend([LANDMARK, q("odd", "X", 1500)])
    assert must(rec.recommended).quote is LANDMARK


def test_fastest_is_shown_only_when_actually_quicker():
    rec = recommend([DPD, FEDEX])
    assert must(rec.recommended).quote is DPD
    assert must(rec.fastest).quote is FEDEX and must(rec.fastest).reason.startswith("Up to 2 days")
    same_speed = q("dpd-other", "DPD", 900, 6)
    assert recommend([DPD, same_speed]).fastest is None


def test_a_preferred_carrier_wins_only_when_comparable():
    rec = recommend([UPS, EVRI, DPD], preferred_carriers=["Evri"])
    assert (
        must(rec.recommended).quote is EVRI and "preferred carrier" in must(rec.recommended).reason
    )
    rec = recommend([UPS, FEDEX], preferred_carriers=["FedEx"])
    assert must(rec.recommended).quote is UPS  # FedEx is £21.68 dearer: preference doesn't buy that


def test_own_labels_override_the_sandbox_expectation():
    # The sandbox said DPD files electronically; this shop's labels showed paper. Believe them.
    def seen(quote):
        if quote.service_code.startswith("dpd-"):
            return Paperwork(CustomsMode.paper, 3, "your labels")
        return sandbox_paperwork(quote.service_code)

    rec = recommend([UPS, DPD], paperwork=seen)
    assert must(rec.recommended).quote is UPS  # both paper now: the cheaper wins


def test_unknown_paperwork_sits_between_paperless_and_paper():
    mystery = q("parcelforce-euro-priority", "Parcelforce", 650, 5)  # never seen
    assert sandbox_paperwork(mystery.service_code).mode == CustomsMode.unknown
    assert must(recommend([mystery, UPS]).recommended).quote is mystery  # unknown beats known paper
    assert must(recommend([mystery, DPD]).recommended).quote is DPD  # known paperless beats unknown


def test_no_quotes_no_recommendation():
    rec = recommend([])
    assert rec.recommended is None and rec.options == []


# ------------------------------------------------------------------ through the service


@pytest.fixture
def shopify():
    return FakeShopify()


@pytest.fixture
def svc(store, shopify, provider, clock):
    return ShippingService(
        store, shopify, provider, Purchases(store, provider, clock=clock), clock=clock
    )


def test_a_chosen_service_is_kept_until_it_is_no_longer_offered(svc, shopify, provider):
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    recommended = s.quote.service_code
    s = svc.choose_service(SHOP, s.id, s.rates[-1].service_code, "george")
    other = s.quote.service_code
    s = svc.prepare(SHOP, s.id)  # a refresh keeps the merchant's pick
    assert s.quote.service_code == other and s.service_choice == other
    if other != recommended:
        real = provider.quotes
        provider.quotes = lambda shipment: [x for x in real(shipment) if x.service_code != other]
        s = svc.prepare(SHOP, s.id)
        assert s.quote.service_code == recommended and s.service_choice is None


def test_paperwork_seen_on_a_label_is_remembered_for_that_service_and_country(
    svc, shopify, provider, clock
):
    provider.customs = "paper"
    shopify.add(fo(2145, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    b = svc.preview(SHOP, s.id)["basis"]
    svc.buy(SHOP, s.id, b, "george", "k1")
    assert svc.store.paperwork(SHOP, s.quote.service_code, "DE") == ("paper", 3)
    assert svc.paperwork(SHOP, s.quote, "DE").source == "your labels"
    svc.tick(SHOP)
    svc.buy(SHOP, s.id, b, "george", "k1")  # a replay doesn't count it twice
    row = svc.store._db.execute("SELECT seen FROM service_paperwork").fetchone()
    assert row[0] == 1
