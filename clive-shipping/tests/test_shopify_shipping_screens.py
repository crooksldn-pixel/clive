"""What the admin and CLIVE's /api/v1 say about a UK order: Shopify Shipping, the Royal Mail
service and where it came from, no customs, and no made-up price."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shipping.app import create_app
from shipping.fake_shopify import fo, tee_line
from shipping.settings import Settings

from .conftest import SHOP
from .test_shopify_shipping import World

R = {"Authorization": "Bearer read-key"}
W = {"Authorization": "Bearer write-key"}


@pytest.fixture
def w(store, clock) -> World:
    return World(store, clock)


@pytest.fixture
def client(w, tmp_path):
    settings = Settings(
        shop_domain=SHOP,
        shopify_backend="fake",
        provider="fake",
        db_path=str(tmp_path / "unused.sqlite3"),
        tick_interval_s=0,
        dev_skip_admin_auth=True,
        clive_read_keys="read-key",
        clive_write_keys="write-key",
        buying_enabled=True,
        domestic_labels="shopify",
        domestic_shipping_lines="Tracked 24=24; Tracked 48=48",
        shopify_tracked_24_rate="royal_mail/T24",
        shopify_tracked_48_rate="royal_mail/T48",
    )
    with TestClient(create_app(settings, w.svc)) as c:
        yield c


def ok(r):
    assert r.status_code == 200, r.text
    return r.json()


def test_the_admin_shows_a_uk_order_with_its_service_and_no_price(w, client):
    s = w.ready(line="Tracked 24")
    inbox = ok(client.get("/admin/api/inbox?stage=ready"))
    assert inbox["domestic"] is True
    (row,) = inbox["rows"]
    assert row["shipping"] == "Royal Mail Tracked 24 · Shopify Shipping"
    d = ok(client.get(f"/admin/api/shipments/{s.id}"))
    assert d["domestic"]["service"] == "Royal Mail Tracked 24"
    assert d["domestic"]["why"] == "From the checkout delivery method “Tracked 24”"
    assert d["shipping"]["chosen"]["price"] == "Price set by Shopify Shipping"
    assert d["shipping"]["chosen"]["price_known"] is False
    assert d["shipping"]["recommended"] is None and len(d["shipping"]["options"]) == 1
    assert d["customs"]["state"] == "not_required"
    pv = ok(client.post(f"/admin/api/shipments/{s.id}/preview"))
    assert pv["price"] is None and pv["price_known"] is False
    assert any("set by Shopify Shipping when the label is bought" in x for x in pv["will"])


def test_the_admin_buy_then_detail_names_shopify_shipping_without_an_amount(w, client):
    s = w.ready()
    pv = ok(client.post(f"/admin/api/shipments/{s.id}/preview"))
    out = ok(
        client.post(
            f"/admin/api/shipments/{s.id}/buy",
            json={"basis": pv["basis"], "idempotency_key": "click-0001"},
        )
    )
    assert out["charged"]
    label = out["shipment"]["label"]
    assert (
        label["provider"] == "Shopify Shipping"
        and label["price"] == "Price set by Shopify Shipping"
    )
    assert label["tracking"] == "RM9001GB" and label["documents"][0]["page_size"] == "4x6"
    assert len(w.ss.purchases) == 1


def test_an_unmapped_order_asks_which_service_and_takes_the_answer(w, client):
    w.shopify.add(fo(3009, [tee_line()], country="GB", shipping_line=None))
    w.svc.sync(SHOP)
    s = next(x for x in w.store.shipments(SHOP) if x.order_name == "CROOKS-3009")
    d = ok(client.get(f"/admin/api/shipments/{s.id}"))
    q = next(q for q in d["questions"] if q["kind"] == "domestic_service")
    assert q["phrase"] == "Which service?" and q["choices"] == ["Tracked 24", "Tracked 48"]
    d = ok(
        client.post(
            f"/admin/api/shipments/{s.id}/answer",
            json={
                "kind": "domestic_service",
                "subject": "service",
                "value": {"service": "tracked_24"},
            },
        )
    )
    assert not any(q["kind"] == "domestic_service" for q in d["questions"])
    assert d["domestic"]["why"].startswith("Chosen for this order by")


def test_clive_sees_shopify_shipping_in_capabilities_and_orders(w, client):
    cap = ok(client.get("/api/v1/capabilities", headers=R))
    uk = next(p for p in cap["providers"] if p["name"] == "Shopify Shipping")
    assert uk["orders"] == "uk" and uk["price_before_buying"] is False
    assert uk["idempotent_at_provider"] is False
    assert {x["service"] for x in uk["services"]} == {"Tracked 24", "Tracked 48"}
    assert all(x["buyable"] for x in uk["services"])
    assert cap["uk_orders"]["enabled"] is True
    assert cap["uk_orders"]["service_by_checkout_line"] == {
        "tracked 24": "Tracked 24",
        "tracked 48": "Tracked 48",
    }
    assert all(p["orders"] == "international" for p in cap["providers"] if p is not uk)

    s = w.ready()
    (row,) = ok(client.get("/api/v1/shipments?stage=ready", headers=R))["shipments"]
    assert row["domestic"] is True and row["price"] is None and row["price_known"] is False
    assert row["service"] == "Shopify Shipping · Royal Mail Tracked 48"
    pv = ok(client.post(f"/api/v1/shipments/{s.id}/preview", headers=R))
    assert pv["money"] == {"shipping_minor": 0, "currency": "GBP", "price_known": False}
    body = {"basis": pv["basis"], "idempotency_key": "clive-buy-0001", "actor": "George"}
    out = ok(client.post(f"/api/v1/shipments/{s.id}/buy", headers=W, json=body))
    assert out["charged"] and out["shipment"]["label"]["provider"] == "Shopify Shipping"
    assert out["shipment"]["label"]["price"] is None
    again = ok(client.post(f"/api/v1/shipments/{s.id}/buy", headers=W, json=body))
    assert again["replayed"] and len(w.ss.purchases) == 1
