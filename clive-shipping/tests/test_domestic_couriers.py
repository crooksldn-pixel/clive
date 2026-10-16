"""UK orders can use another connected courier (Parcel2Go, Easyship) instead of the owner's
Shopify Shipping service, order by order: e.g. Special Delivery Guaranteed by 1pm.

Shopify Shipping stays the default. The other couriers are asked only when a person wants
their prices; a chosen courier is re-priced with every refresh, and its choice is never
quietly swapped back to Shopify Shipping while that courier is merely not answering.
"""

from __future__ import annotations

import pytest

from shipping.fake_shopify import fo, tee_line
from shipping.models import ShipmentStatus as S
from shipping.providers.base import ProviderUnavailable
from shipping.purchase import ActionError

from .conftest import SHOP
from .test_domestic import OneService, by_order, get, quote, service, shopify, with_package
from .test_stage2 import kinds

__all__ = ["shopify"]  # the fixture


@pytest.fixture
def uk_order(store, shopify, provider, clock):
    svc = service(store, shopify, provider, clock, uk=OneService())
    shopify.add(fo(3001, [tee_line()], country="GB", shipping_line="Tracked 48"))
    svc.sync(SHOP)
    s = with_package(svc, by_order(svc, "CROOKS-3001"))
    assert s.status == S.ready and quote(s).provider == "Shopify Shipping"
    return svc, s


def test_other_couriers_are_asked_only_on_request(uk_order, provider):
    svc, s = uk_order
    assert "quotes" not in provider.calls  # a UK order alone never asks them
    s = svc.other_services(SHOP, s.id)
    assert provider.calls.count("quotes") == 1
    offered = {(q.provider, q.service_code) for q in s.rates}
    assert ("Shopify Shipping", "tracked_48") in offered
    assert ("Parcel2Go", "dpd-classic") in offered
    assert quote(s).provider == "Shopify Shipping"  # asking changes nothing by itself
    assert s.service_choice is None


def test_choosing_another_courier_buys_through_it(uk_order, provider):
    svc, s = uk_order
    svc.other_services(SHOP, s.id)
    s = svc.choose_service(SHOP, s.id, "dpd-classic", "george")
    assert s.status == S.ready and s.service_choice == "dpd-classic"
    assert quote(s).provider == "Parcel2Go"
    pv = svc.preview(SHOP, s.id)
    assert pv["money"]["shipping_minor"] == provider.price_minor
    out = svc.buy(SHOP, s.id, pv["basis"], "george", "k-dpd")
    assert out["charged"] and len(provider.charges) == 1
    after = get(svc, s.id)
    assert after.label is not None and after.label.provider == "Parcel2Go"


def test_the_chosen_courier_is_repriced_on_every_refresh(uk_order, provider):
    svc, s = uk_order
    svc.other_services(SHOP, s.id)
    svc.choose_service(SHOP, s.id, "dpd-classic", "george")
    asked = provider.calls.count("quotes")
    s = svc.prepare(SHOP, s.id)
    assert provider.calls.count("quotes") == asked + 1
    assert s.status == S.ready and quote(s).service_code == "dpd-classic"


def test_back_to_shopify_shipping(uk_order):
    svc, s = uk_order
    svc.other_services(SHOP, s.id)
    svc.choose_service(SHOP, s.id, "dpd-classic", "george")
    s = svc.choose_service(SHOP, s.id, "", "george")  # "" = the owner's Shopify Shipping service
    assert s.service_choice is None and quote(s).provider == "Shopify Shipping"
    assert s.status == S.ready


def test_a_courier_that_stops_offering_it_goes_back_to_shopify_and_says_so(
    uk_order, provider, monkeypatch
):
    svc, s = uk_order
    svc.other_services(SHOP, s.id)
    svc.choose_service(SHOP, s.id, "dpd-classic", "george")
    monkeypatch.setattr(provider, "quotes", lambda _s: [])
    s = svc.prepare(SHOP, s.id)
    assert s.service_choice is None and quote(s).provider == "Shopify Shipping"
    assert any(e.type == "service_choice_dropped" for e in s.timeline)


def test_a_courier_not_answering_never_swaps_the_choice_for_shopify(
    uk_order, provider, monkeypatch
):
    svc, s = uk_order
    svc.other_services(SHOP, s.id)
    svc.choose_service(SHOP, s.id, "dpd-classic", "george")

    def down(_s):
        raise ProviderUnavailable("Parcel2Go didn't answer.")

    monkeypatch.setattr(provider, "quotes", down)
    s = svc.prepare(SHOP, s.id)
    assert s.service_choice == "dpd-classic"  # still what the person chose
    assert s.quote is None and s.status == S.needs_attention
    assert kinds(s) == ["provider_unavailable"]
    with pytest.raises(ActionError):
        svc.preview(SHOP, s.id)  # nothing is bought on a service no one chose


def test_an_unmapped_uk_order_can_go_with_another_courier(store, shopify, provider, clock):
    svc = service(store, shopify, provider, clock, uk=OneService())
    shopify.add(fo(3001, [tee_line()], country="GB", shipping_line="Express"))
    svc.sync(SHOP)
    s = with_package(svc, by_order(svc, "CROOKS-3001"))
    assert kinds(s) == ["domestic_service"]
    svc.other_services(SHOP, s.id)
    s = svc.choose_service(SHOP, s.id, "dpd-classic", "george")
    assert s.status == S.ready and s.questions == [] and quote(s).provider == "Parcel2Go"
    # Back to Shopify Shipping: the question about which Royal Mail service comes back.
    s = svc.choose_service(SHOP, s.id, "", "george")
    assert kinds(s) == ["domestic_service"] and s.quote is None


def test_other_couriers_all_down_leaves_the_order_as_it_was(uk_order, provider, monkeypatch):
    svc, s = uk_order

    def down(_s):
        raise ProviderUnavailable("Parcel2Go didn't answer.")

    monkeypatch.setattr(provider, "quotes", down)
    with pytest.raises(ActionError, match="didn't answer"):
        svc.other_services(SHOP, s.id)
    after = get(svc, s.id)
    assert after.status == S.ready and quote(after).provider == "Shopify Shipping"


def test_only_uk_orders_waiting_for_a_label_can_ask(store, shopify, provider, clock, uk_order):
    svc, s = uk_order
    shopify.add(fo(3002, [tee_line(n=7)], country="DE"))
    svc.sync(SHOP)
    de = by_order(svc, "CROOKS-3002")
    with pytest.raises(ActionError, match="UK orders"):
        svc.other_services(SHOP, de.id)
