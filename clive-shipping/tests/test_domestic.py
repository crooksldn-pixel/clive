"""UK (domestic) orders: shown only when switched on, no customs, and the Royal Mail service
decided by the owner's mapping of the checkout delivery method, never guessed."""

from __future__ import annotations

import pytest

from shipping import domestic
from shipping.domestic import TRACKED_24, TRACKED_48, DomesticPolicy, RateCode
from shipping.fake_shopify import FakeShopify, fo, tee_line
from shipping.models import Quote, Shipment
from shipping.models import ShipmentStatus as S
from shipping.money import Money
from shipping.purchase import ActionError, Purchases, Stale
from shipping.service import ShippingService
from shipping.settings import Settings

from .conftest import NOW, SHOP
from .test_stage2 import PACKAGE, kinds

RATES: dict[str, RateCode | None] = {
    TRACKED_24: RateCode("rm", "T24"),
    TRACKED_48: RateCode("rm", "T48"),
}
LINES = domestic.parse_lines("Tracked 24=24; Tracked 48=48")
ON = DomesticPolicy(enabled=True, lines=LINES, rates=RATES)


class OneService:
    """Stands in for Shopify Shipping's quote: the service asked for, no price."""

    name = "Shopify Shipping"

    def __init__(self) -> None:
        self.asked: list[str | None] = []

    def quotes(self, s):
        self.asked.append(s.domestic_service)
        return [
            Quote(
                provider=self.name,
                carrier="Royal Mail",
                service_code=s.domestic_service,
                service_name=domestic.title(s.domestic_service),
                amount=Money(minor=0),
                price_known=False,
                generated_at=NOW,
            )
        ]


@pytest.fixture
def shopify():
    return FakeShopify()


def service(store, shopify, provider, clock, policy=ON, uk=None):
    return ShippingService(
        store,
        shopify,
        provider,
        Purchases(store, provider, clock=clock),
        clock=clock,
        domestic=policy,
        domestic_provider=uk,
    )


def by_order(svc, name):
    return next(s for s in svc.store.shipments(SHOP) if s.order_name == name)


def get(svc, sid) -> Shipment:
    s = svc.store.get(SHOP, sid)
    assert s is not None
    return s


def quote(s: Shipment) -> Quote:
    assert s.quote is not None
    return s.quote


def with_package(svc, s):
    return svc.answer(SHOP, s.id, "package", "first_package", PACKAGE, "george")


# --------------------------------------------------------------------------- the setting


def test_off_by_default_uk_orders_are_not_found_and_international_is_unchanged(
    store, shopify, provider, clock
):
    svc = service(store, shopify, provider, clock, policy=DomesticPolicy())
    shopify.add(fo(3001, [tee_line()], country="GB"))
    shopify.add(fo(3002, [tee_line()], country="DE"))
    assert svc.sync(SHOP) == {"open": 1, "new": 1}
    (s,) = svc.store.shipments(SHOP)
    assert s.order_name == "CROOKS-3002" and not s.domestic
    assert kinds(s) == ["customs", "origin", "package"]  # international still asks customs


def test_settings_default_off_and_refuse_anything_but_off_or_shopify(monkeypatch):
    assert Settings().domestic().enabled is False
    with pytest.raises(ValueError):
        Settings(domestic_labels="yes")
    assert Settings(domestic_labels="Shopify").domestic().enabled is True


def test_a_bad_mapping_or_rate_stops_the_service_starting():
    with pytest.raises(ValueError, match="only 24 or 48"):
        Settings(domestic_shipping_lines="Tracked 24=24; Express=12")
    with pytest.raises(ValueError, match="should read"):
        Settings(domestic_shipping_lines="Tracked 24")
    with pytest.raises(ValueError, match="mapped twice"):
        Settings(domestic_shipping_lines="Tracked 24=24; tracked  24=48")
    with pytest.raises(ValueError, match="carrierCode"):
        Settings(shopify_tracked_24_rate="royal_mail")
    s = Settings(
        domestic_labels="shopify",
        domestic_shipping_lines="Tracked 24=24; Tracked 48=48",
        shopify_tracked_48_rate="rm/T48",
    )
    policy = s.domestic()
    assert policy.service_for("tracked 48") == TRACKED_48
    assert policy.rate(TRACKED_48) == RateCode("rm", "T48") and policy.rate(TRACKED_24) is None


def test_on_uk_orders_appear_without_customs_questions(store, shopify, provider, clock):
    svc = service(store, shopify, provider, clock, uk=OneService())
    shopify.add(fo(3001, [tee_line()], country="GB"))  # no HS code or origin anywhere
    shopify.add(fo(3002, [tee_line(n=7)], country="DE"))
    assert svc.sync(SHOP) == {"open": 2, "new": 2}
    uk, de = by_order(svc, "CROOKS-3001"), by_order(svc, "CROOKS-3002")
    assert uk.domestic and not de.domestic
    assert kinds(uk) == ["package"] and kinds(de) == ["customs", "origin", "package"]
    uk = with_package(svc, uk)
    assert uk.status == S.ready and uk.duties is None and uk.questions == []
    assert quote(uk).provider == "Shopify Shipping" and quote(uk).service_code == TRACKED_48
    assert quote(uk).price_known is False


def test_uk_weight_and_address_are_still_asked(store, shopify, provider, clock):
    svc = service(store, shopify, provider, clock, uk=OneService())
    line = tee_line()
    line.weight_g = None
    snap = fo(3001, [line], country="GB")
    snap.destination.postcode = ""
    shopify.add(snap)
    svc.sync(SHOP)
    assert kinds(by_order(svc, "CROOKS-3001")) == ["address", "package", "weight"]


def test_channel_islands_stay_international(store, shopify, provider, clock):
    svc = service(store, shopify, provider, clock, uk=OneService())
    snap = fo(3001, [tee_line()], country="GB")
    snap.destination.country = "GG"
    shopify.add(snap)
    svc.sync(SHOP)
    s = by_order(svc, "CROOKS-3001")
    assert not s.domestic and "customs" in kinds(s)


def test_switching_off_hides_waiting_uk_orders_and_refuses_to_buy(store, shopify, provider, clock):
    on = service(store, shopify, provider, clock, uk=OneService())
    shopify.add(fo(3001, [tee_line()], country="GB"))
    on.sync(SHOP)
    s = with_package(on, by_order(on, "CROOKS-3001"))
    assert s.status == S.ready and on.visible(s)
    basis = on.preview(SHOP, s.id)["basis"]

    off = service(store, shopify, provider, clock, policy=DomesticPolicy(), uk=OneService())
    assert not off.visible(get(off, s.id))
    with pytest.raises(ActionError, match="switched off"):
        off.buy(SHOP, s.id, basis, "george", "k-off")
    off.sync(SHOP)
    after = get(off, s.id)
    assert after.status == S.needs_attention and kinds(after) == ["domestic_off"]
    assert after.quote is None


# --------------------------------------------------------------------------- the mapping


@pytest.mark.parametrize(
    ("line", "expected"),
    [("Tracked 24", TRACKED_24), ("Tracked 48", TRACKED_48), ("  tracked   24 ", TRACKED_24)],
)
def test_the_checkout_delivery_method_decides_the_service(
    store, shopify, provider, clock, line, expected
):
    uk = OneService()
    svc = service(store, shopify, provider, clock, uk=uk)
    shopify.add(fo(3001, [tee_line()], country="GB", shipping_line=line))
    svc.sync(SHOP)
    s = with_package(svc, by_order(svc, "CROOKS-3001"))
    assert s.status == S.ready and s.domestic_service == expected
    assert quote(s).service_code == expected and uk.asked[-1] == expected


@pytest.mark.parametrize("line", ["Express", None, "Tracked 72"])
def test_an_unmapped_delivery_method_waits_for_a_person_and_is_never_priced(
    store, shopify, provider, clock, line
):
    uk = OneService()
    svc = service(store, shopify, provider, clock, uk=uk)
    shopify.add(fo(3001, [tee_line()], country="GB", shipping_line=line))
    svc.sync(SHOP)
    s = with_package(svc, by_order(svc, "CROOKS-3001"))
    assert s.status == S.needs_attention and kinds(s) == ["domestic_service"]
    q = s.questions[0]
    assert q.text.startswith("Which service: Tracked 24 or Tracked 48?")
    assert q.choices == ["Tracked 24", "Tracked 48"]
    assert s.quote is None and s.domestic_service is None and uk.asked == []
    with pytest.raises(ActionError):
        svc.preview(SHOP, s.id)  # nothing to price, nothing to buy

    s = svc.answer(SHOP, s.id, "domestic_service", "service", {"service": TRACKED_24}, "george")
    assert s.status == S.ready and quote(s).service_code == TRACKED_24
    assert s.domestic_service_by == "george"


def test_a_mapped_order_cant_be_switched_to_the_other_service_by_hand(
    store, shopify, provider, clock
):
    svc = service(store, shopify, provider, clock, uk=OneService())
    shopify.add(fo(3001, [tee_line()], country="GB", shipping_line="Tracked 24"))
    svc.sync(SHOP)
    s = with_package(svc, by_order(svc, "CROOKS-3001"))
    with pytest.raises(ActionError, match="already decides"):
        svc.answer(SHOP, s.id, "domestic_service", "service", {"service": TRACKED_48}, "x")
    with pytest.raises(ActionError, match="Choose Tracked 24 or Tracked 48"):
        svc.answer(SHOP, s.id, "domestic_service", "service", {"service": "next_day"}, "x")


def test_a_service_without_its_shopify_code_is_never_bought(store, shopify, provider, clock):
    uk = OneService()
    policy = DomesticPolicy(enabled=True, lines=LINES, rates={TRACKED_48: None})
    svc = service(store, shopify, provider, clock, policy=policy, uk=uk)
    shopify.add(fo(3001, [tee_line()], country="GB"))
    svc.sync(SHOP)
    s = with_package(svc, by_order(svc, "CROOKS-3001"))
    assert s.status == S.needs_attention and kinds(s) == ["service_code"]
    assert "isn't set on the server" in s.questions[0].text and uk.asked == []


def test_the_delivery_method_changing_after_the_preview_stops_the_buy(
    store, shopify, provider, clock
):
    svc = service(store, shopify, provider, clock, uk=OneService())
    snap = shopify.add(fo(3001, [tee_line()], country="GB", shipping_line="Tracked 48"))
    svc.sync(SHOP)
    s = with_package(svc, by_order(svc, "CROOKS-3001"))
    basis = svc.preview(SHOP, s.id)["basis"]
    snap.shipping_line = "Tracked 24"  # an order edit upgraded the delivery
    with pytest.raises(Stale):
        svc.buy(SHOP, s.id, basis, "george", "k1")
    after = get(svc, s.id)
    assert after.status == S.ready and quote(after).service_code == TRACKED_24
    assert after.label is None
