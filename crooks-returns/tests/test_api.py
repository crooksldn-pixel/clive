import base64
import hashlib
import hmac
import json

from fastapi.testclient import TestClient

from returns.app import create_app

TEE = "gid://shopify/FulfillmentLineItem/1"


def client(svc):
    return TestClient(create_app(svc.s, svc))


def test_portal_to_clive_round_trip(svc):
    c = client(svc)
    found = c.post("/proxy/api/lookup", json={"order": "#1939", "proof": "E1 6AN"}).json()
    assert found["order"] == "#1939" and found["lines"][0]["eligible"]
    session = found["session"]
    items = [{"fulfillment_line_item_id": TEE, "quantity": 1, "reason": "too_small"}]
    quote = c.post("/proxy/api/quote", json={"session": session, "items": items}).json()
    assert [o["resolution"] for o in quote["options"]] == ["exchange", "store_credit", "refund"]
    assert found["lines"][0]["size"] == "M"
    assert found["lines"][0]["size_chart"][1]["chest"] == "110.5cm"
    assert quote["options"][0]["exchange_choices"][TEE] == [
        {"id": "gid://shopify/ProductVariant/tee-L", "title": "L", "size": "L"}
    ]
    made = c.post(
        "/proxy/api/submit",
        json={
            "session": session,
            "items": items,
            "resolution": "store_credit",
            "postage": "free_label",
        },
    ).json()["return"]
    assert made["status"] == "requested" and made["credit"] == "£30.00"

    read = {"Authorization": "Bearer read-key"}
    write = {"Authorization": "Bearer write-key"}
    listed = c.get("/api/v1/returns?open=true", headers=read).json()["returns"]
    assert listed[0]["attention"] == ["needs_approval"]
    assert "store credit £30.00" in listed[0]["summary"]
    assert c.get("/api/v1/orders/1939/returns", headers=read).json()["returns"]

    url = f"/api/v1/returns/{made['id']}/actions/approve"
    assert c.post(url, json={"idempotency_key": "a"}, headers=read).status_code == 403
    assert c.post(url, json={}, headers=write).status_code == 422  # no key
    approved = c.post(url, json={"idempotency_key": "a", "actor": "clive"}, headers=write).json()
    assert approved["status"] == "awaiting_shipment" and approved["verified"]

    label = approved["return"]["label_url"]
    path = label.split("returns.example.com")[1]
    pdf = c.get(path)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert c.get(path.split("?")[0] + "?t=forged").status_code == 404

    stats = c.get("/api/v1/stats", headers=read).json()
    assert stats["by_resolution"] == {"store_credit": 1} and stats["kept_share"] == 1.0


def test_portal_requires_shopify_signature(svc):
    svc.s.dev_skip_proxy_signature = False
    c = client(svc)
    assert c.post("/proxy/api/lookup", json={"order": "1939", "proof": "x"}).status_code == 401


def test_unknown_key_cannot_read(svc):
    c = client(svc)
    assert c.get("/api/v1/returns").status_code == 401
    assert c.get("/api/v1/returns", headers={"Authorization": "Bearer nope"}).status_code == 403


def test_shopify_webhook_is_verified(svc):
    c = client(svc)
    body = json.dumps({"admin_graphql_api_id": "gid://shopify/Return/1"}).encode()
    good = base64.b64encode(hmac.new(b"shpss_test", body, hashlib.sha256).digest()).decode()
    headers = {"X-Shopify-Topic": "returns/close", "Content-Type": "application/json"}
    assert (
        c.post(
            "/webhooks/shopify", content=body, headers={**headers, "X-Shopify-Hmac-Sha256": "bad"}
        ).status_code
        == 401
    )
    ok = c.post(
        "/webhooks/shopify", content=body, headers={**headers, "X-Shopify-Hmac-Sha256": good}
    )
    assert ok.status_code == 200 and ok.json()["return"] is None


def test_health_reports_policy(svc):
    h = client(svc).get("/health").json()
    assert h["policy"]["window_days"] == 14
    assert h["policy"]["return_label_cost"] == "£3.50"
