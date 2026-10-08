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
    assert c.get("/api/v1/orders/CROOKS-1939/returns", headers=read).json()["returns"]
    assert not c.get("/api/v1/orders/1940/returns", headers=read).json()["returns"]

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


def test_a_key_with_any_characters_is_refused_not_a_crash(svc):
    # A header Shopify, a proxy or a typo could send: refused like any wrong key, never a 500.
    c = client(svc)
    odd = {"Authorization": "Bearer clé".encode("latin-1")}
    assert c.get("/api/v1/returns", headers=odd).status_code == 403
    assert c.post("/api/v1/returns/x/actions/note", headers=odd, json={}).status_code == 403


def test_signatures_with_any_characters_are_refused_not_a_crash(svc):
    # The portal's proxy signature, Shopify's webhook HMAC and Parcel2Go's webhook signature can
    # arrive with characters no real signature has: refused like a wrong one, never a 500.
    svc.s.dev_skip_proxy_signature = False
    svc.s.p2g_webhook_secret = "hook-secret"
    c = TestClient(create_app(svc.s, svc), raise_server_exceptions=False)
    lookup = {"order": "1939", "proof": "x"}
    assert c.post("/proxy/api/lookup?shop=s&signature=clé", json=lookup).status_code == 401
    body = json.dumps({"admin_graphql_api_id": "gid://shopify/Return/1"}).encode()
    headers = {"X-Shopify-Topic": "returns/close", "X-Shopify-Hmac-Sha256": "clé".encode("latin-1")}
    assert c.post("/webhooks/shopify", content=body, headers=headers).status_code == 401
    hook = {"Id": "1", "Timestamp": "2026-10-04T10:15:00", "Type": "Tracking", "Payload": {}}
    for odd in ({"Signature": "clé"}, {"Signature": "\ud800"}, {"Id": "\ud800"}):
        sent = json.dumps({**hook, **odd}).encode()  # escaped, as JSON may carry any character
        assert c.post("/webhooks/parcel2go", content=sent).status_code == 401


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


def test_staff_tool_lists_and_acts(svc, monkeypatch, capsys):
    from returns import ctl
    from returns.models import Postage, Reason, Resolution, Selection

    session, _ = svc.lookup("1939", "customer@example.com", "1.1.1.1")
    order = svc.order_for_session(session)
    ret = svc.submit(
        order,
        [Selection(fulfillment_line_item_id=TEE, quantity=1, reason=Reason.changed_mind)],
        Resolution.refund,
        Postage.self_ship,
    )
    monkeypatch.setattr(ctl, "build_service", lambda settings: svc)
    assert ctl.main(["list"]) == 0
    assert ret.id in capsys.readouterr().out
    assert ctl.main(["approve", ret.id, "self_ship", "--yes", "--as", "george"]) == 0
    out = capsys.readouterr().out
    assert "requested -> awaiting_shipment" in out
    assert ctl.main(["receive", ret.id, "--yes"]) == 0
    assert "-> completed" in capsys.readouterr().out
    assert ctl.main(["decline", ret.id, "--yes"]) == 1


def test_shopify_failure_reads_as_a_plain_message(svc, monkeypatch):
    from returns.shopify import ShopifyError

    def down(digits):
        raise ShopifyError("Query cost is 1367, which exceeds the single query max cost limit")

    monkeypatch.setattr(svc.shopify, "find_orders", down)
    r = client(svc).post("/proxy/api/lookup", json={"order": "1939", "proof": "E1 6AN"})
    assert r.status_code == 503
    assert "try again" in r.json()["detail"]


def test_returnable_items_and_products_are_fetched_separately():
    from returns.settings import Settings
    from returns.shopify import PRODUCTS_PER_QUERY, Q_PRODUCTS, GraphQLShopify, parse_order

    item = {
        "quantity": 1,
        "fulfillmentLineItem": {
            "id": "fli1",
            "lineItem": {
                "id": "li1",
                "title": "CROOKS EXPRESS TEE",
                "variantTitle": "Black / S",
                "sku": None,
                "quantity": 1,
                "image": None,
                "discountedUnitPriceAfterAllDiscountsSet": {"shopMoney": {"amount": "25.0"}},
                "variant": {
                    "id": "v-S",
                    "price": "25.00",
                    "selectedOptions": [
                        {"name": "Colour", "value": "Black"},
                        {"name": "Size", "value": "S"},
                    ],
                    "product": {"id": "p1"},
                },
            },
        },
    }
    product = {
        "id": "p1",
        "tags": ["tee"],
        "options": [
            {"name": "Colour", "optionValues": [{"name": "Black"}]},
            {"name": "Size", "optionValues": [{"name": "S"}, {"name": "M"}]},
        ],
        "measurements": {
            "value": '[{"size":"S","chest":"105.4cm"},{"size":"M","chest":"110.5cm"}]'
        },
        "variants": {
            "nodes": [
                {
                    "id": "v-S",
                    "title": "Black / S",
                    "sku": None,
                    "price": "25.00",
                    "availableForSale": True,
                    "inventoryQuantity": 13,
                    "selectedOptions": [
                        {"name": "Colour", "value": "Black"},
                        {"name": "Size", "value": "S"},
                    ],
                },
                {
                    "id": "v-M",
                    "title": "Black / M",
                    "sku": None,
                    "price": "25.00",
                    "availableForSale": True,
                    "inventoryQuantity": -2,
                    "selectedOptions": [
                        {"name": "Colour", "value": "Black"},
                        {"name": "Size", "value": "M"},
                    ],
                },
            ]
        },
    }
    calls = []

    def fake_call(document, variables=None):
        calls.append(document)
        if document == Q_PRODUCTS:
            assert len(variables["ids"]) <= PRODUCTS_PER_QUERY
            return {"nodes": [product]}
        return {
            "returnableFulfillments": {
                "nodes": [{"id": "rf1", "returnableFulfillmentLineItems": {"nodes": [item]}}]
            }
        }

    shop = GraphQLShopify(Settings())
    shop._call = fake_call
    returnable = shop._returnable("gid://shopify/Order/1")
    assert len(calls) == 2
    node = {
        "id": "o1",
        "name": "CROOKS-2129",
        "createdAt": "2026-10-03T15:22:05Z",
        "fulfillments": [],
    }
    line = parse_order(node, returnable).lines[0]
    assert line.size == "S" and line.sizes == ["S", "M"]
    assert line.size_chart[1]["chest"] == "110.5cm"
    assert [v.available for v in line.siblings] == [True, False]  # oversold M is not offered
