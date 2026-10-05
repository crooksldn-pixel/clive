"""Live safety: no label is bought until the owner authorises that order on the server.
Preparing, pricing and the preview still work, so a real order can be checked first."""

import pytest
from fastapi.testclient import TestClient

from shipping.app import build_service, create_app
from shipping.fake_shopify import FakeShopify, fo, tee_line
from shipping.purchase import ActionError, Purchases
from shipping.service import ShippingService
from shipping.settings import Settings

from .conftest import SHOP
from .test_stage2 import answer_all_first_time, only


@pytest.fixture
def shopify():
    return FakeShopify()


def gated(store, shopify, provider, clock, allowed=()):
    return ShippingService(
        store,
        shopify,
        provider,
        Purchases(store, provider, clock=clock),
        clock=clock,
        may_buy=lambda s: s.order_name.split("-")[-1] in allowed,
    )


def test_an_unauthorised_order_is_prepared_and_priced_but_never_bought(
    store, shopify, provider, clock
):
    svc = gated(store, shopify, provider, clock)
    shopify.add(fo(2190, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    pv = svc.preview(SHOP, s.id)  # the full check runs
    assert pv["basis"] and "verify" in provider.calls
    with pytest.raises(ActionError) as e:
        svc.buy(SHOP, s.id, pv["basis"], "george", "k1")
    assert e.value.status == 403 and e.value.code == "not_authorised"
    assert "create_order" not in provider.calls and provider.charges == []
    assert svc.store.ops_for(SHOP, s.id) == []


def test_authorising_one_order_allows_that_label_only(store, shopify, provider, clock):
    svc = gated(store, shopify, provider, clock, allowed=("2190",))
    shopify.add(fo(2190, [tee_line()]))
    shopify.add(fo(2191, [tee_line()]))
    svc.sync(SHOP)
    for s in store.shipments(SHOP):
        answer_all_first_time(svc, s)
    by = {s.order_name: s for s in store.shipments(SHOP)}
    ok = by["CROOKS-2190"]
    assert svc.buy(SHOP, ok.id, svc.preview(SHOP, ok.id)["basis"], "george", "k1")["charged"]
    other = by["CROOKS-2191"]
    with pytest.raises(ActionError):
        svc.buy(SHOP, other.id, svc.preview(SHOP, other.id)["basis"], "george", "k2")
    assert len(provider.charges) == 1


def test_production_settings_authorise_nothing_by_default(tmp_path):
    s = Settings(shopify_backend="fake", provider="fake", db_path=str(tmp_path / "s.db"))
    assert s.authorised() == set()
    svc = build_service(s)
    assert not svc.may_buy(svc.store.config(SHOP) and _shipment("CROOKS-2190"))


def test_authorised_orders_are_read_from_the_setting(tmp_path):
    s = Settings(
        shopify_backend="fake",
        provider="fake",
        db_path=str(tmp_path / "s.db"),
        authorised_orders="#2190, CROOKS-2191",
    )
    assert s.authorised() == {"2190", "2191"}
    svc = build_service(s)
    assert svc.may_buy(_shipment("CROOKS-2190")) and not svc.may_buy(_shipment("CROOKS-21900"))


def test_the_page_offers_a_price_check_not_a_purchase(store, shopify, provider, clock, tmp_path):
    svc = gated(store, shopify, provider, clock)
    settings = Settings(
        shop_domain=SHOP,
        shopify_backend="fake",
        provider="fake",
        db_path=str(tmp_path / "x.db"),
        tick_interval_s=0,
        dev_skip_admin_auth=True,
    )
    shopify.add(fo(2190, [tee_line()]))
    svc.sync(SHOP)
    s = answer_all_first_time(svc, only(svc))
    with TestClient(create_app(settings, svc)) as c:
        d = c.get(f"/admin/api/shipments/{s.id}").json()
        assert d["buy_authorised"] is False and "buy" not in d["actions"]
        assert "preview" in d["actions"]
        pv = c.post(f"/admin/api/shipments/{s.id}/preview").json()
        r = c.post(
            f"/admin/api/shipments/{s.id}/buy",
            json={"basis": pv["basis"], "idempotency_key": "click-0001"},
        )
        assert r.status_code == 403 and r.json()["detail"]["code"] == "not_authorised"
    assert provider.charges == []


def _shipment(name):
    from datetime import UTC, datetime

    from shipping.models import Address, Shipment, ShipmentStatus

    at = datetime(2026, 10, 5, tzinfo=UTC)
    return Shipment(
        id="shp_x",
        shop=SHOP,
        order_id="gid://shopify/Order/1",
        order_name=name,
        fulfillment_order_id="gid://shopify/FulfillmentOrder/1",
        destination=Address(country="DE"),
        status=ShipmentStatus.ready,
        created_at=at,
        updated_at=at,
    )
