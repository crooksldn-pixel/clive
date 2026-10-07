"""CLIVE operates Returns through /api/v1: "approve both pending returns" without a phone button.

The API calls the same ReturnsService.execute as the Returns screen; the only difference on the
record is where the change came from (event.source "api" versus "ui").
"""

from fastapi.testclient import TestClient

from returns.app import create_app
from returns.models import Postage, Resolution

from .test_admin import token
from .test_service import submit

R = {"Authorization": "Bearer read-key"}
W = {"Authorization": "Bearer write-key"}
JEANS = "gid://shopify/FulfillmentLineItem/2"


def client(svc):
    return TestClient(create_app(svc.s, svc))


def two_pending(svc):
    a = submit(svc, Resolution.refund, Postage.self_ship)
    b = submit(svc, Resolution.store_credit, Postage.self_ship, fli=JEANS)
    return a, b


def test_clive_finds_and_approves_both_pending_returns(svc, shop):
    a, b = two_pending(svc)
    c = client(svc)
    pending = c.get("/api/v1/returns?status=requested", headers=R).json()["returns"]
    assert {r["id"] for r in pending} == {a.id, b.id}
    for r in pending:
        url = f"/api/v1/returns/{r['id']}/actions/approve"
        will = c.post(url + "/preview", json={}, headers=R).json()["will"]
        assert will  # what it would do, in words, before doing it
        out = c.post(
            url, json={"idempotency_key": f"clive-{r['id']}", "actor": "George"}, headers=W
        )
        assert out.status_code == 200 and out.json()["status"] == "awaiting_shipment"
    assert c.get("/api/v1/returns?status=requested", headers=R).json()["returns"] == []
    assert len(shop.called("returnCreate")) == 2  # one each, never more
    for rid in (a.id, b.id):  # the result is observable, with its evidence
        doc = c.get(f"/api/v1/returns/{rid}", headers=R).json()
        assert doc["status"] == "awaiting_shipment" and doc["shopify"]["return_id"]
        approved = next(e for e in doc["timeline"] if e["type"] == "approved")
        assert approved["source"] == "api" and approved["actor"] == "George"
        assert approved["verified"]


def test_the_screen_and_clive_use_the_same_action(svc, shop):
    a, b = two_pending(svc)
    svc.s.shopify_client_id, svc.s.shop_domain = "app-id", "crooks-test.myshopify.com"
    c = client(svc)
    ui = c.post(
        f"/admin/api/returns/{a.id}/approve",
        json={"params": {}, "idempotency_key": "ui-1"},
        headers={"Authorization": f"Bearer {token()}"},
    ).json()
    api = c.post(
        f"/api/v1/returns/{b.id}/actions/approve", json={"idempotency_key": "api-1"}, headers=W
    ).json()
    assert ui["status"] == api["status"] == "awaiting_shipment"
    kinds = lambda rid: [  # noqa: E731
        (e.type, e.verified) for e in svc.store.get(rid).timeline if e.type != "requested"
    ]
    assert kinds(a.id) == kinds(b.id)  # the same steps, the same checks
    sources = {e.source for e in svc.store.get(a.id).timeline if e.type == "approved"}
    assert sources == {"ui"}
    sources = {e.source for e in svc.store.get(b.id).timeline if e.type == "approved"}
    assert sources == {"api"}


def test_a_key_is_one_request(svc, shop):
    a, _ = two_pending(svc)
    c = client(svc)
    url = f"/api/v1/returns/{a.id}/actions/note"
    first = c.post(url, json={"params": {"text": "hi"}, "idempotency_key": "k-1"}, headers=W)
    again = c.post(url, json={"params": {"text": "hi"}, "idempotency_key": "k-1"}, headers=W)
    assert first.status_code == again.status_code == 200 and again.json()["replayed"]
    other = c.post(url, json={"params": {"text": "bye"}, "idempotency_key": "k-1"}, headers=W)
    assert other.status_code == 409 and "different request" in other.json()["detail"]
    notes = [e for e in svc.store.get(a.id).timeline if e.type == "note"]
    assert len(notes) == 1  # done once


def test_approving_twice_is_refused_in_words_and_changes_nothing(svc, shop):
    a, _ = two_pending(svc)
    c = client(svc)
    url = f"/api/v1/returns/{a.id}/actions/approve"
    assert c.post(url, json={"idempotency_key": "k-1"}, headers=W).status_code == 200
    second = c.post(url, json={"idempotency_key": "k-2"}, headers=W)  # a new key: a new request
    assert second.status_code == 409 and isinstance(second.json()["detail"], str)
    assert len(shop.called("returnCreate")) == 1


def test_clive_can_discover_what_it_may_do_and_what_changed(svc, clock):
    a, b = two_pending(svc)
    c = client(svc)
    caps = c.get("/api/v1/capabilities", headers=R).json()
    assert "approve" in caps["actions"] and "requested" in caps["open_statuses"]
    since = clock().isoformat()
    clock.now = clock.now.replace(minute=clock.now.minute + 1)
    c.post(f"/api/v1/returns/{a.id}/actions/approve", json={"idempotency_key": "k"}, headers=W)
    events = c.get("/api/v1/events", params={"since": since}, headers=R).json()["events"]
    assert events and {e["return_id"] for e in events} == {a.id}
    assert all(e["source"] == "api" for e in events)
    assert events[-1]["status_now"] == "awaiting_shipment"
    assert c.get("/api/v1/events", headers={"Authorization": "Bearer nope"}).status_code == 403


def test_events_page_oldest_first_and_paging_skips_nothing(svc, clock):
    from datetime import timedelta

    a, b = two_pending(svc)
    c = client(svc)
    start = clock().isoformat()
    for i, rid in enumerate((a.id, b.id)):
        clock.now = clock.now + timedelta(minutes=1)
        c.post(
            f"/api/v1/returns/{rid}/actions/note",
            json={"params": {"text": f"n{i}"}, "idempotency_key": f"n-{i}"},
            headers=W,
        )
        clock.now = clock.now + timedelta(minutes=1)
        c.post(
            f"/api/v1/returns/{rid}/actions/approve", json={"idempotency_key": f"a-{i}"}, headers=W
        )
    every = c.get("/api/v1/events", params={"since": start}, headers=R).json()
    assert not every["has_more"] and len(every["events"]) >= 4
    first = c.get("/api/v1/events", params={"since": start, "limit": 1}, headers=R).json()
    assert first["has_more"] and first["events"][0]["type"] == "note"  # the oldest, not newest
    seen, since = [], start
    for _ in range(30):
        got = c.get("/api/v1/events", params={"since": since, "limit": 1}, headers=R).json()
        seen += got["events"]
        if not got["has_more"]:
            break
        since = got["events"][-1]["at"]
    assert [(e["return_id"], e["type"]) for e in seen] == [
        (e["return_id"], e["type"]) for e in every["events"]
    ]


def test_a_since_without_a_zone_is_utc(svc, clock):
    from datetime import timedelta

    a, _ = two_pending(svc)
    c = client(svc)
    naive = clock().replace(tzinfo=None).isoformat()
    clock.now = clock.now + timedelta(minutes=1)
    c.post(f"/api/v1/returns/{a.id}/actions/approve", json={"idempotency_key": "k"}, headers=W)
    r = c.get("/api/v1/events", params={"since": naive}, headers=R)
    assert r.status_code == 200 and any(e["type"] == "approved" for e in r.json()["events"])


def test_events_made_outside_an_action_say_where_they_came_from(svc, shop, clock):
    # The customer's request comes from the portal; Shopify's webhooks and the timer are the
    # system. CLIVE's feed names the source of every new event, not only of actions.
    from datetime import timedelta

    a, b = two_pending(svc)
    svc.execute(a.id, "approve", {"postage_mode": "label_later"}, "Sam", "a-1", source="ui")
    done = svc.execute(b.id, "approve", {}, "Sam", "b-1", source="ui")["return_doc"]
    shop.returns[done.shopify.return_id]["status"] = "CANCELED"  # cancelled in Shopify admin
    svc.shopify_changed(done.shopify.return_id, "returns/cancel")
    clock.now = clock.now + timedelta(hours=25)
    assert svc.tick() == [a.id]  # the label is overdue
    events = client(svc).get("/api/v1/events", headers=R).json()["events"]
    source = {(e["return_id"], e["type"]): e["source"] for e in events}
    assert source[(a.id, "requested")] == source[(b.id, "requested")] == "portal"
    assert source[(a.id, "approved")] == "ui"
    assert source[(b.id, "cancelled")] == "system"
    assert source[(a.id, "label_overdue")] == "system"
    assert all(e["source"] for e in events)
