"""The embedded admin's API, as the page uses it: merchant phrases, the buy protocol, printing
that can't buy, and Shopify-only retries (Stage 4)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from shipping.app import create_app
from shipping.fake_shopify import FakeShopify, fo, tee_line
from shipping.providers.base import ProviderUnavailable
from shipping.purchase import Purchases
from shipping.service import ShippingService
from shipping.settings import Settings

from .conftest import SHOP

CLIENT_ID, SECRET = "client-abc", "app-secret-xyz"
TEE = "gid://shopify/Product/tee"


def token(shop: str = SHOP, secret: str = SECRET, aud: str = CLIENT_ID, exp: float = 0) -> str:
    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    now = time.time()
    body = b64(
        json.dumps(
            {
                "iss": f"https://{shop}/admin",
                "dest": f"https://{shop}",
                "aud": aud,
                "sub": "42",
                "exp": exp or now + 60,
                "nbf": now - 5,
            }
        ).encode()
    )
    sig = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(sig)}"


AUTH = {"Authorization": f"Bearer {token()}"}


@pytest.fixture
def shopify():
    return FakeShopify()


@pytest.fixture
def svc(store, shopify, provider, clock):
    return ShippingService(
        store, shopify, provider, Purchases(store, provider, clock=clock), clock=clock
    )


@pytest.fixture
def client(svc, tmp_path):
    settings = Settings(
        shop_domain=SHOP,
        shopify_client_id=CLIENT_ID,
        shopify_client_secret=SECRET,
        shopify_backend="fake",
        provider="fake",
        db_path=str(tmp_path / "unused.sqlite3"),
        tick_interval_s=0,
    )
    with TestClient(create_app(settings, svc)) as c:
        c.headers.update(AUTH)
        yield c


def ok(response):
    assert response.status_code == 200, response.text
    return response.json()


def first_order(client, shopify, **kw):
    shopify.add(fo(2145, [tee_line()], **kw))
    ok(client.post("/admin/api/sync"))
    return ok(client.get("/admin/api/inbox"))


def answer_everything(client, sid):
    ok(
        client.post(
            f"/admin/api/shipments/{sid}/answer",
            json={
                "kind": "package",
                "subject": "first_package",
                "value": {
                    "name": "Mailer",
                    "length_cm": 38,
                    "width_cm": 28,
                    "height_cm": 8,
                    "empty_weight_g": 40,
                },
            },
        )
    )
    ok(
        client.post(
            f"/admin/api/shipments/{sid}/answer",
            json={
                "kind": "customs",
                "subject": TEE,
                "value": {"hs_code": "6109.10", "description": "Men's cotton T-shirt"},
            },
        )
    )
    return ok(
        client.post(
            f"/admin/api/shipments/{sid}/answer",
            json={"kind": "origin", "subject": TEE, "value": {"country": "PT"}},
        )
    )


def ready_order(client, shopify):
    inbox = first_order(client, shopify)
    sid = inbox["groups"]["attention"][0]["id"]
    return answer_everything(client, sid)


def buy(client, d, key="click-0001"):
    pv = ok(client.post(f"/admin/api/shipments/{d['id']}/preview"))
    return pv, client.post(
        f"/admin/api/shipments/{d['id']}/buy",
        json={"basis": pv["basis"], "idempotency_key": key},
    )


# ------------------------------------------------------------------ auth


def test_only_shopify_admin_sessions_for_this_shop_get_in(client):
    assert client.get("/admin/api/inbox", headers={"Authorization": ""}).status_code == 401
    other = {"Authorization": f"Bearer {token(shop='other.myshopify.com')}"}
    assert client.get("/admin/api/inbox", headers=other).status_code == 401
    forged = {"Authorization": f"Bearer {token(secret='guess')}"}
    assert client.get("/admin/api/inbox", headers=forged).status_code == 401
    other_app = {"Authorization": f"Bearer {token(aud='another-app')}"}
    assert client.get("/admin/api/inbox", headers=other_app).status_code == 401
    expired = {"Authorization": f"Bearer {token(exp=time.time() - 120)}"}
    assert client.get("/admin/api/inbox", headers=expired).status_code == 401
    assert ok(client.get("/admin/api/inbox"))["me"] == "Staff 42"


def test_the_page_can_only_be_framed_by_shopify_admin(client):
    r = client.get("/admin", headers={"Authorization": ""})
    assert r.status_code == 200 and CLIENT_ID in r.text
    assert (
        "frame-ancestors https://crooks-test.myshopify.com https://admin.shopify.com"
        in (r.headers["content-security-policy"])
    )


# ------------------------------------------------------------------ inbox and phrases


def test_a_first_order_asks_in_merchant_words(client, shopify):
    inbox = first_order(client, shopify)
    (r,) = inbox["groups"]["attention"]
    assert r["status"]["label"] == "3 details needed"
    assert r["status"]["reasons"] == [
        "Package needed",
        "Missing HS code",
        "Missing country of origin",
    ]
    assert r["order"] == "CROOKS-2145" and r["destination"]["country"] == "DE"
    assert r["package"] == "Package needed" and r["shipping"] == "—"
    assert inbox["setup"] == {"origin": True, "package": False}


def test_answered_once_it_is_ready_and_the_inbox_shows_no_internals(client, shopify):
    d = ready_order(client, shopify)
    assert d["status"]["label"] == "Ready" and d["status"]["group"] == "ready"
    inbox = ok(client.get("/admin/api/inbox"))
    (r,) = inbox["groups"]["ready"]
    assert r["shipping"] == "DPD · £10.69" and r["package"].startswith("Mailer · ")
    raw = json.dumps(inbox)
    for internal in ("gid://", "b1_", "fake:", "hs_code", "dpd-classic"):
        assert internal not in raw, internal


def test_search_finds_by_order_number_and_city(client, shopify):
    first_order(client, shopify)
    assert ok(client.get("/admin/api/inbox?q=2145"))["counts"]["attention"] == 1
    assert ok(client.get("/admin/api/inbox?q=berlin"))["counts"]["attention"] == 1
    assert ok(client.get("/admin/api/inbox?q=9999"))["counts"]["attention"] == 0


def test_the_detail_explains_the_recommendation_and_the_alternatives(client, shopify):
    d = ready_order(client, shopify)
    ship = d["shipping"]
    assert ship["recommended"]["title"] == "DPD Classic" and ship["recommended"]["paperless"]
    assert ship["recommended"]["reason"].startswith("Recommended:")
    assert [o["title"] for o in ship["options"]] == ["DPD Classic", "Evri International Parcelshop"]
    assert d["customs"]["expected"] == "No customs paperwork expected"
    assert d["customs"]["summary"] == "2 items · £74.00" and d["customs"]["complete"]
    assert d["address"]["ok"] and d["package"]["source"] == "Your default package"
    assert set(d["actions"]) >= {"preview", "buy", "service", "package"}
    evri = "myhermes-international-parcelshop"
    d = ok(client.post(f"/admin/api/shipments/{d['id']}/service", json={"service_code": evri}))
    assert d["shipping"]["chosen"]["title"] == "Evri International Parcelshop"
    assert d["customs"]["expected"] == "Expect 3 A4 customs copies to print"


# ------------------------------------------------------------------ buying


def test_buy_label_then_print_4x6(client, shopify, provider):
    d = ready_order(client, shopify)
    pv, r = buy(client, d)
    assert pv["price"] == "£10.69" and any("Mark CROOKS-2145 fulfilled" in w for w in pv["will"])
    out = ok(r)
    assert out["charged"] and out["status"] == "fulfilled"
    d = out["shipment"]
    assert d["status"]["label"] == "Fulfilled"
    assert d["label"]["tracking"] and d["customs"]["text"] == "Electronic ✓"
    assert [s["done"] for s in d["steps"]] == [True, True, True]
    assert "print" in d["actions"]
    jobs = ok(client.post(f"/admin/api/shipments/{d['id']}/print"))["jobs"]
    assert jobs[0]["printer"] == "label" and jobs[0]["page_size"] == "4x6"
    pdf = client.get(f"/admin/api/documents/{jobs[0]['artifact_id']}")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-type"] == "application/pdf"
    d = ok(client.get(f"/admin/api/shipments/{d['id']}"))
    assert "reprint" in d["actions"] and d["label"]["printed"]
    assert len(provider.charges) == 1


def test_a_double_click_buys_once(client, shopify, provider):
    d = ready_order(client, shopify)
    pv, first = buy(client, d)
    again = client.post(
        f"/admin/api/shipments/{d['id']}/buy",
        json={"basis": pv["basis"], "idempotency_key": "click-0001"},
    )
    assert ok(first)["charged"] and ok(again)["replayed"]
    fresh_click = client.post(
        f"/admin/api/shipments/{d['id']}/buy",
        json={"basis": pv["basis"], "idempotency_key": "click-0002"},
    )
    assert fresh_click.status_code == 409
    assert len(provider.charges) == 1


def test_an_order_changed_since_the_preview_is_refused_in_words(client, shopify, provider):
    d = ready_order(client, shopify)
    pv = ok(client.post(f"/admin/api/shipments/{d['id']}/preview"))
    shopify.fos["gid://shopify/FulfillmentOrder/2145"].lines[0].quantity = 3
    r = client.post(
        f"/admin/api/shipments/{d['id']}/buy",
        json={"basis": pv["basis"], "idempotency_key": "click-0001"},
    )
    assert r.status_code == 409
    err = r.json()["detail"]
    assert err["code"] == "stale" and err["title"] == "Order changed — refresh required"
    assert provider.charges == []
    d = ok(client.get(f"/admin/api/shipments/{d['id']}"))
    assert d["customs"]["summary"].startswith("3 items")


def test_shopify_failing_after_purchase_is_retried_on_the_shopify_side_only(
    client, shopify, provider
):
    d = ready_order(client, shopify)
    shopify.refuse_fulfillment = 1
    _, r = buy(client, d)
    d = ok(r)["shipment"]
    assert d["status"]["label"] == "Label purchased — Shopify update needs retry"
    assert d["status"]["group"] == "attention" and "retry_shopify" in d["actions"]
    assert [s["done"] for s in d["steps"]] == [True, False, False]
    calls = list(provider.calls)
    d = ok(client.post(f"/admin/api/shipments/{d['id']}/retry-shopify"))
    assert d["status"]["label"] == "Fulfilled" and provider.calls == calls
    assert len(provider.charges) == 1 and len(shopify.fulfillments) == 1


def test_an_uncertain_purchase_says_so_and_offers_no_buy(client, shopify, provider):
    d = ready_order(client, shopify)
    provider.lose_pay_reply, provider.read_down = True, 5
    _, r = buy(client, d)
    d = ok(r)["shipment"]
    assert d["status"]["label"] == "Purchase requires reconciliation"
    assert d["actions"] == [] and "Don't buy again" in d["error"]
    again = client.post(f"/admin/api/shipments/{d['id']}/preview")
    assert again.status_code == 409


def test_paper_customs_are_spelled_out(client, shopify, provider):
    provider.customs = "paper"
    d = ready_order(client, shopify)
    _, r = buy(client, d)
    d = ok(r)["shipment"]
    assert d["customs"]["text"] == (
        "Customs paperwork required — Commercial invoice — 3 copies — A4"
    )
    jobs = ok(client.post(f"/admin/api/shipments/{d['id']}/print"))["jobs"]
    assert [(j["title"], j["copies"], j["printer"]) for j in jobs] == [
        ("Shipping label", 1, "label"),
        ("Commercial invoice", 3, "document"),
    ]


def test_a_provider_outage_is_named(client, shopify, provider, monkeypatch):
    def down(shipment):
        raise ProviderUnavailable("timed out")

    monkeypatch.setattr(provider, "quotes", down)
    d = ready_order(client, shopify)
    assert d["status"]["label"] == "Provider unavailable" and d["status"]["tone"] == "caution"


# ------------------------------------------------------------------ printing can't buy


def test_every_print_route_leaves_the_provider_alone(client, shopify, provider, monkeypatch):
    d = ready_order(client, shopify)
    buy(client, d)
    for name in ("quotes", "verify", "create_order", "pay", "read_order", "documents"):
        monkeypatch.setattr(
            provider, name, lambda *a, _n=name, **k: pytest.fail(f"print reached {_n}")
        )
    ok(client.post("/admin/api/print/ready"))
    jobs = ok(client.post(f"/admin/api/shipments/{d['id']}/print"))["jobs"]
    ok(client.post("/admin/api/print/order/2145"))
    assert client.get(f"/admin/api/documents/{jobs[0]['artifact_id']}").status_code == 200
    assert len(provider.charges) == 1


def test_printing_an_unbought_order_is_refused_not_bought(client, shopify, provider):
    d = ready_order(client, shopify)
    r = client.post(f"/admin/api/shipments/{d['id']}/print")
    assert r.status_code == 409 and "never buys" in r.json()["detail"]["message"]
    assert client.post("/admin/api/print/order/2145").status_code == 404
    assert "create_order" not in provider.calls


def test_documents_are_served_only_by_id_for_this_shop(client):
    assert client.get("/admin/api/documents/art_doesnotexist").status_code == 404
    assert client.get("/admin/api/documents/..%2F..%2Fetc").status_code == 404


def test_print_all_ready_labels(client, shopify):
    for n in (2145, 2146):
        shopify.add(fo(n, [tee_line()]))
    ok(client.post("/admin/api/sync"))
    ids = [r["id"] for r in ok(client.get("/admin/api/inbox"))["groups"]["attention"]]
    answer_everything(client, ids[0])
    ids = [r["id"] for r in ok(client.get("/admin/api/inbox"))["groups"]["ready"]]
    for i, sid in enumerate(ids):
        buy(client, {"id": sid}, key=f"click-000{i}")
    assert ok(client.get("/admin/api/inbox"))["ready_to_print"] == 2
    out = ok(client.post("/admin/api/print/ready"))
    assert out["labels"] == 2
    assert ok(client.get("/admin/api/inbox"))["ready_to_print"] == 0


# ------------------------------------------------------------------ setup


def test_setup_shows_the_connection_and_saves_safely(client, shopify):
    first_order(client, shopify)
    s = ok(client.get("/admin/api/setup"))
    assert s["label_format"] == "4x6" and s["connection"]["connected"]
    assert s["origin"]["postcode"] == "SL8 5AS" and s["customs"]["duties"] == "DAP"
    bad = client.post("/admin/api/setup", json={"origin": {"name": "X", "country": "GB"}})
    assert bad.status_code == 422
    assert client.post("/admin/api/setup", json={"ioss_number": "123"}).status_code == 422
    s = ok(
        client.post(
            "/admin/api/setup/packages",
            json={
                "name": "Hoodie box",
                "length_cm": 40,
                "width_cm": 30,
                "height_cm": 12,
                "empty_weight_g": 180,
                "make_default": True,
            },
        )
    )
    assert [p["name"] for p in s["presets"]] == ["Hoodie box"] and s["presets"][0]["default"]
    # The order that only lacked a package no longer asks for one.
    (r,) = ok(client.get("/admin/api/inbox"))["groups"]["attention"]
    assert "Package needed" not in r["status"]["reasons"]
