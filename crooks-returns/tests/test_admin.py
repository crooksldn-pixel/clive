import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from returns.admin import BadToken, verify_session_token
from returns.app import create_app

TEE = "gid://shopify/FulfillmentLineItem/1"
SHOP = "crooks-test.myshopify.com"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def token(secret="shpss_test", aud="app-id", dest=f"https://{SHOP}", exp=None, alg="HS256"):
    now = int(time.time())
    head = b64(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    body = b64(
        json.dumps(
            {
                "iss": f"{dest}/admin",
                "dest": dest,
                "aud": aud,
                "sub": "42",
                "exp": exp if exp is not None else now + 60,
                "nbf": now - 5,
                "iat": now - 5,
            }
        ).encode()
    )
    sig = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{b64(sig)}"


@pytest.fixture
def admin(svc):
    svc.s.shopify_client_id = "app-id"
    svc.s.shop_domain = SHOP
    c = TestClient(create_app(svc.s, svc))
    c.headers["Authorization"] = f"Bearer {token()}"
    return c


def request_credit(c):
    found = c.post("/proxy/api/lookup", json={"order": "#1939", "proof": "E1 6AN"}).json()
    items = [{"fulfillment_line_item_id": TEE, "quantity": 1, "reason": "changed_mind"}]
    made = c.post(
        "/proxy/api/submit",
        json={
            "session": found["session"],
            "items": items,
            "resolution": "store_credit",
            "postage": "self_ship",
        },
    ).json()["return"]
    return made["id"]


def test_session_token_checks():
    ok = dict(client_id="app-id", secret="shpss_test", shop_domain=SHOP)
    assert verify_session_token(token(), **ok)["sub"] == "42"
    for bad in (
        token(secret="someone-else"),
        token(aud="another-app"),
        token(dest="https://other.myshopify.com"),
        token(exp=int(time.time()) - 120),
        token(alg="none"),
        "not.a.token",
        "",
    ):
        with pytest.raises(BadToken):
            verify_session_token(bad, **ok)


def test_page_only_frames_in_shopify_admin(admin):
    page = admin.get("/admin")
    assert page.status_code == 200
    assert 'content="app-id"' in page.text and "app-bridge.js" in page.text
    assert (
        "frame-ancestors https://crooks-test.myshopify.com https://admin.shopify.com"
        in (page.headers["content-security-policy"])
    )


def test_api_needs_a_shopify_admin_session(admin):
    assert admin.get("/admin/api/overview", headers={"Authorization": ""}).status_code == 401
    forged = {"Authorization": f"Bearer {token(secret='guess')}"}
    assert admin.get("/admin/api/returns", headers=forged).status_code == 401
    # A CLIVE key is not an admin session.
    assert (
        admin.get("/admin/api/returns", headers={"Authorization": "Bearer read-key"}).status_code
        == 401
    )


def test_staff_run_a_return_from_the_admin(admin, svc, shop):
    rid = request_credit(admin)
    ov = admin.get("/admin/api/overview").json()
    assert ov["me"] == "Sam Staff" and ov["counts"]["todo"] == 1

    rows = admin.get("/admin/api/returns?view=todo").json()["returns"]
    assert rows[0]["id"] == rid and rows[0]["outcome"] == "£30.00 credit"
    assert admin.get("/admin/api/returns?q=1939").json()["returns"][0]["id"] == rid
    assert admin.get("/admin/api/returns?q=Sam").json()["returns"]
    assert not admin.get("/admin/api/returns?q=9999").json()["returns"]

    doc = admin.get(f"/admin/api/returns/{rid}").json()
    assert doc["actions"] == ["approve", "decline", "note"]
    assert doc["default_postage_mode"] == "self_ship"
    assert doc["links"]["order"] == "shopify://admin/orders/1939"
    assert doc["lines"][0]["reason_label"] == "Changed my mind"

    pv = admin.post(
        f"/admin/api/returns/{rid}/approve/preview", json={"params": {"postage_mode": "self_ship"}}
    ).json()
    assert any("send it back themselves" in w for w in pv["will"])
    assert not shop.called("returnCreate")  # a preview changes nothing

    body = {"params": {"postage_mode": "self_ship"}, "idempotency_key": "k1"}
    out = admin.post(f"/admin/api/returns/{rid}/approve", json=body).json()
    assert out["status"] == "awaiting_shipment" and out["verified"]
    again = admin.post(f"/admin/api/returns/{rid}/approve", json=body).json()
    assert again["replayed"] and len(shop.called("returnCreate")) == 1
    assert out["return"]["timeline"][-1]["actor"] == "Sam Staff"
    assert out["return"]["actions"] == ["receive", "tracking", "cancel", "note"]

    got = admin.post(
        f"/admin/api/returns/{rid}/receive",
        json={"params": {"condition": "ok"}, "idempotency_key": "k2"},
    ).json()
    assert got["status"] == "completed" and got["verified"] and not got["error"]
    assert shop.called("storeCreditAccountCredit")[0]["pence"] == 500

    refused = admin.post(f"/admin/api/returns/{rid}/approve", json={"idempotency_key": "k3"})
    assert refused.status_code == 409
    assert admin.get("/admin/api/overview").json()["counts"]["todo"] == 0


def test_pilot_list_is_set_from_the_admin(admin, svc):
    assert admin.post("/admin/api/pilot", json={"orders": "#2130, CROOKS-2129"}).json() == {
        "pilot": ["2129", "2130"]
    }
    blocked = admin.post("/proxy/api/lookup", json={"order": "#1939", "proof": "E1 6AN"})
    assert blocked.status_code == 403
    checks = admin.get("/admin/api/checks").json()["checks"]
    assert any(c["text"] == "Testing: only orders 2129, 2130" for c in checks)
    assert admin.post("/admin/api/pilot", json={"orders": ""}).json() == {"pilot": []}
    assert (
        admin.post("/proxy/api/lookup", json={"order": "#1939", "proof": "E1 6AN"}).status_code
        == 200
    )


def test_a_failed_staff_name_lookup_is_not_repeated_on_every_tap(admin, shop, monkeypatch):
    """The name lookup sits in front of every admin call; when Shopify refused it, each tap
    (Approve's preview included) waited on it again. A miss is remembered for a while."""
    asked = []

    def refused(id_token):
        asked.append(id_token)
        return None

    monkeypatch.setattr(shop, "staff_member", refused)
    for _ in range(3):
        assert admin.get("/admin/api/overview").json()["me"] == "Staff 42"
    assert len(asked) == 1
