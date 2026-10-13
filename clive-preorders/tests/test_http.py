"""The HTTP doors: each checks who is calling, and answers quickly."""

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient

from preorders.app import create_app

from .conftest import open_preorder


@pytest.fixture
def client(svc, settings):
    with TestClient(create_app(settings, svc)) as c:
        yield c


def signed_webhook(client, topic, payload, event_id, secret="test-secret"):
    body = json.dumps(payload).encode()
    mac = base64.b64encode(hmac.new(secret.encode(), body, hashlib.sha256).digest()).decode()
    return client.post(
        "/webhooks/shopify",
        content=body,
        headers={
            "X-Shopify-Hmac-Sha256": mac,
            "X-Shopify-Topic": topic,
            "X-Shopify-Event-Id": event_id,
            "Content-Type": "application/json",
        },
    )


def proxy_query(params, secret="test-secret"):
    params = {"shop": "crooks-test.myshopify.com", "timestamp": str(int(time.time())), **params}
    message = "".join(sorted(f"{k}={v}" for k, v in params.items()))
    sig = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return urlencode({**params, "signature": sig})


def test_webhooks_are_checked_recorded_once_and_processed_later(client, svc, shopify, jogger):
    pid, sizes = jogger
    open_preorder(svc, pid, sizes)
    oid = shopify.checkout([(sizes["S"], 1, shopify.plan_of(sizes["S"]))])
    payload = {"admin_graphql_api_id": oid}
    assert signed_webhook(client, "orders/create", payload, "e1", secret="wrong").status_code == 401
    assert signed_webhook(client, "orders/create", payload, "e1").status_code == 200
    assert signed_webhook(client, "orders/create", payload, "e1").status_code == 200  # retry
    assert svc.store.value("SELECT COUNT(*) FROM webhook_inbox") == 1
    assert svc.preorder_lines() == []  # answered at once; the work happens on the tick
    client.app.state.tick()
    assert len(svc.preorder_lines()) == 1


def test_customer_redaction_removes_their_personal_data(client, svc, shopify, jogger):
    pid, sizes = jogger
    open_preorder(svc, pid, sizes)
    svc.waitlist.signup(variant_id=sizes["L"], email="gone@example.com")
    oid = shopify.checkout(
        [(sizes["S"], 1, shopify.plan_of(sizes["S"]))], email="gone@example.com", name="Gone Person"
    )
    other = shopify.checkout(
        [(sizes["S"], 1, shopify.plan_of(sizes["S"]))], email="old@example.com", name="Old Name"
    )
    for o in (oid, other):
        svc.ingest_order(o)
    payload = {
        "customer": {"email": "Gone@example.com"},
        "orders_to_redact": [int(other.rsplit("/", 1)[1])],  # an order under an older address
    }
    assert signed_webhook(client, "customers/redact", payload, "r1").status_code == 200
    assert svc.store.value("SELECT COUNT(*) FROM waitlist") == 0
    people = svc.store.all("SELECT customer_name, customer_email FROM preorder_lines")
    assert {(r["customer_name"], r["customer_email"]) for r in people} == {
        ("[redacted]", "[redacted]")
    }
    batch_id = svc.store.value("SELECT batch_id FROM preorder_lines LIMIT 1")
    who = svc.comms.audience(batch_id)
    assert (who["orders"], who["customers"], who["without_email"]) == (2, 0, 2)  # nobody to write
    svc.ingest_order(oid)  # a later re-read doesn't bring them back
    assert (
        svc.store.value("SELECT customer_email FROM preorder_lines WHERE order_id = ?", (oid,))
        == "[redacted]"
    )


def test_storefront_signup_needs_shopifys_signature(client, svc, jogger):
    pid, sizes = jogger
    vid = sizes["L"].rsplit("/", 1)[1]
    body = {"variant_id": vid, "email": "fan@example.com"}
    assert client.post("/proxy/preorders/waitlist", json=body).status_code == 401
    q = proxy_query({"path_prefix": "/apps/returns"})
    r = client.post(f"/proxy/preorders/waitlist?{q}", json=body)
    assert r.status_code == 200 and r.json()["status"] == "joined"
    # A correctly signed request replayed later, or signed for another shop, is refused.
    stale = proxy_query({"path_prefix": "/apps/returns", "timestamp": str(int(time.time()) - 600)})
    assert client.post(f"/proxy/preorders/waitlist?{stale}", json=body).status_code == 401
    other = proxy_query({"path_prefix": "/apps/returns", "shop": "someone-else.myshopify.com"})
    assert client.post(f"/proxy/preorders/waitlist?{other}", json=body).status_code == 401
    bad = client.post(f"/proxy/preorders/waitlist?{q}", json={**body, "email": "nope"})
    assert bad.status_code == 422


def test_unsubscribe_link_works_once_and_only_with_its_token(client, svc, jogger):
    pid, sizes = jogger
    svc.waitlist.signup(variant_id=sizes["L"], email="fan@example.com")
    sub = svc.waitlist.subscribers(sizes["L"])[0]
    q = proxy_query({"id": sub["id"], "t": "forged"})
    assert "isn't valid" in client.get(f"/proxy/preorders/waitlist/unsubscribe?{q}").text
    q = proxy_query({"id": sub["id"], "t": svc.waitlist.token(sub["id"])})
    assert "won't get" in client.get(f"/proxy/preorders/waitlist/unsubscribe?{q}").text
    assert svc.waitlist.subscribers(sizes["L"])[0]["status"] == "UNSUBSCRIBED"


def test_admin_needs_a_shopify_session(client):
    assert client.get("/admin/api/overview").status_code == 401
    assert client.get("/admin").status_code == 200  # the page shell itself holds no data


def test_clive_reads_classification_with_its_key(client, svc, shopify, jogger):
    pid, sizes = jogger
    open_preorder(svc, pid, sizes)
    oid = shopify.checkout([(sizes["XS"], 1, None), (sizes["S"], 1, shopify.plan_of(sizes["S"]))])
    svc.ingest_order(oid)
    n = oid.rsplit("/", 1)[1]
    assert client.get(f"/api/v1/orders/{n}/classification").status_code == 401
    assert (
        client.get(
            f"/api/v1/orders/{n}/classification", headers={"Authorization": "Bearer nope"}
        ).status_code
        == 403
    )
    r = client.get(
        f"/api/v1/orders/{n}/classification", headers={"Authorization": "Bearer read-key"}
    )
    kinds = sorted(x["classification"] for x in r.json()["lines"])
    assert kinds == ["IN_STOCK", "PREORDER_WAITING"]
    s_line = next(x for x in r.json()["lines"] if x["preorder"])
    assert s_line["expected_dispatch_at"] == "2026-11-07"
    assert s_line["inbound_batch"]["reference"] == "Jogger Batch 2"


def test_email_off_means_nothing_is_sent_and_says_so(settings, shopify, clock, jogger, svc):
    from preorders.app import build_service
    from preorders.comms import DisabledMailer

    off = build_service(settings, shopify=shopify, mailer=DisabledMailer())
    off.clock = clock
    pid, sizes = jogger
    off.waitlist.signup(variant_id=sizes["L"], email="fan@example.com")
    assert off.waitlist.notify_preview(sizes["L"])["email_enabled"] is False
    with TestClient(
        create_app(settings.model_copy(update={"dev_skip_admin_auth": True}), off)
    ) as c:
        batch = off.create_batch(
            reference="B",
            expected_arrival_at="2026-11-01",
            expected_dispatch_at="2026-11-03",
            lines=[],
            actor="Sam",
        )
        r = c.post(f"/admin/api/batches/{batch['id']}/notify-update")
        assert r.status_code == 503 and "nothing was sent" in r.json()["detail"]["message"]


def test_a_size_added_without_an_allocation_preorders_what_is_coming(settings, svc, jogger):
    pid, sizes = jogger
    dev = settings.model_copy(update={"dev_skip_admin_auth": True})
    with TestClient(create_app(dev, svc)) as c:
        n = lambda size: sizes[size].rsplit("/", 1)[1]  # noqa: E731
        r = c.post(
            "/admin/api/batches",
            json={
                "reference": "B",
                "expected_arrival_at": "2026-11-01",
                "expected_dispatch_at": "2026-11-03",
                "lines": [{"variant_id": n("S"), "expected_quantity": 12}],
            },
        )
        assert r.status_code == 200, r.text
        bid = r.json()["id"]
        assert (
            c.post(
                f"/admin/api/batches/{bid}/lines",
                json={"variant_id": n("L"), "expected_quantity": 20},
            ).status_code
            == 200
        )
        lines = {x["variant_title"]: x for x in svc.batch(bid)["lines"]}
        assert (lines["S"]["preorder_allocation"], lines["L"]["preorder_allocation"]) == (12, 20)


def test_signup_limits_follow_the_email_not_the_shared_proxy_address(client, svc, shopify):
    # Every shopper arrives from Shopify's proxy: one address must not throttle them all.
    pid = shopify.add_product("Tee", {f"S{i}": 0 for i in range(12)})
    svc.refresh_catalog()
    vids = [shopify.variant(pid, f"S{i}").variant_id.rsplit("/", 1)[1] for i in range(12)]
    q = proxy_query({"path_prefix": "/apps/returns"})
    shared = {"X-Forwarded-For": "23.227.38.1"}
    for i in range(25):
        body = {"variant_id": vids[0], "email": f"fan{i}@example.com"}
        r = client.post(f"/proxy/preorders/waitlist?{q}", json=body, headers=shared)
        assert r.status_code == 200, (i, r.text)
    # One address used for alert after alert is stopped at the email limit (10 an hour).
    codes = [
        client.post(
            f"/proxy/preorders/waitlist?{q}",
            json={"variant_id": v, "email": "victim@example.com"},
            headers=shared,
        ).status_code
        for v in vids
    ]
    assert codes == [200] * 10 + [429] * 2
