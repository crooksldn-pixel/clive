"""CLIVE's /api/v1: the Shipping screen's own service paths, behind bearer keys.

CLIVE can find orders by stage, read one, price it, buy the previewed label once, print it once,
read tracking and follow what changed. It cannot buy without a preview, buy twice, buy for an
order whose payment changed, or reprint without saying so.
"""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from shipping.app import create_app
from shipping.fake_shopify import FakeShopify, fo, tee_line
from shipping.models import DocumentKind
from shipping.purchase import Purchases
from shipping.service import ShippingService
from shipping.settings import Settings

from .conftest import SHOP
from .test_label_selection import bundle
from .test_stage2 import answer_all_first_time, only

R = {"Authorization": "Bearer read-key"}
W = {"Authorization": "Bearer write-key"}


@pytest.fixture
def shopify():
    return FakeShopify()


@pytest.fixture
def svc(store, shopify, provider, clock):
    return ShippingService(
        store, shopify, provider, Purchases(store, provider, clock=clock), clock=clock
    )


def app_for(svc, **kw):
    cfg = Settings(
        shop_domain=SHOP,
        provider="fake",
        tick_interval_s=0,
        clive_read_keys="read-key",
        clive_write_keys="write-key",
        buying_enabled=True,
        **kw,
    )
    return TestClient(create_app(cfg, svc))


@pytest.fixture
def api(svc):
    with app_for(svc) as c:
        yield c


@pytest.fixture
def ready(svc, shopify):
    snap = shopify.add(fo(2145, [tee_line(qty=2)]))
    svc.sync(SHOP)
    return answer_all_first_time(svc, only(svc)), snap


def buy(api, sid, key="clive-buy-0001", headers=W):
    pv = api.post(f"/api/v1/shipments/{sid}/preview", headers=R).json()
    return api.post(
        f"/api/v1/shipments/{sid}/buy",
        headers=headers,
        json={"basis": pv["basis"], "idempotency_key": key, "actor": "George"},
    )


# ------------------------------------------------------------------ keys


def test_keys_decide_what_clive_may_do(api, ready):
    s, _ = ready
    assert api.get("/api/v1/shipments").status_code == 401
    assert api.get("/api/v1/shipments", headers={"Authorization": "Bearer nope"}).status_code == 403
    assert api.get("/api/v1/shipments", headers=R).status_code == 200
    assert api.get("/api/v1/shipments", headers=W).status_code == 200  # write can read
    refused = buy(api, s.id, headers=R)  # a read key can price but not buy
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "forbidden"


def test_no_keys_set_means_no_api(svc, ready):
    s, _ = ready
    cfg = Settings(shop_domain=SHOP, provider="fake", tick_interval_s=0)
    with TestClient(create_app(cfg, svc)) as c:
        for h in (R, W, {"Authorization": "Bearer "}):
            assert c.get("/api/v1/shipments", headers=h).status_code in (401, 403)


def test_capabilities_say_what_is_possible(api):
    caps = api.get("/api/v1/capabilities", headers=R).json()
    paths = {(o["method"], o["path"], o["key"]) for o in caps["operations"]}
    assert ("POST", "/api/v1/shipments/{id}/buy", "write") in paths
    assert ("POST", "/api/v1/shipments/{id}/preview", "read") in paths
    assert caps["stages"] == ["attention", "ready", "bought", "printed", "in_transit", "delivered"]


# ------------------------------------------------------------------ reading


def test_clive_lists_by_stage_and_reads_one(api, ready):
    s, _ = ready
    rows = api.get("/api/v1/shipments?stage=ready", headers=R).json()["shipments"]
    assert [r["id"] for r in rows] == [s.id] and rows[0]["payment"] == "Paid"
    assert api.get("/api/v1/shipments?stage=attention", headers=R).json()["shipments"] == []
    d = api.get(f"/api/v1/shipments/{s.id}", headers=R).json()
    assert d["stage"] == "ready" and d["can_buy"] and d["questions"] == []
    assert api.get("/api/v1/shipments/nope", headers=R).status_code == 404


# ------------------------------------------------------------------ buying


def test_clive_buys_the_previewed_label_once(api, ready, provider, svc):
    s, _ = ready
    pv = api.post(f"/api/v1/shipments/{s.id}/preview", headers=R).json()
    body = {"basis": pv["basis"], "idempotency_key": "clive-buy-0001", "actor": "George"}
    first = api.post(f"/api/v1/shipments/{s.id}/buy", headers=W, json=body)
    assert first.status_code == 200 and first.json()["charged"]
    again = api.post(f"/api/v1/shipments/{s.id}/buy", headers=W, json=body)  # reply lost, retried
    assert again.status_code == 200 and again.json()["replayed"]
    assert len(provider.charges) == 1
    after = svc.store.get(SHOP, s.id)
    assert any(e.actor == "George (CLIVE)" for e in after.timeline)  # the event names CLIVE
    d = first.json()["shipment"]
    assert d["stage"] == "bought" and d["label"]["tracking_number"]


def test_clive_cannot_buy_without_a_preview(api, ready, provider):
    s, _ = ready
    r = api.post(
        f"/api/v1/shipments/{s.id}/buy",
        headers=W,
        json={"basis": "b1_made_up", "idempotency_key": "clive-buy-0001"},
    )
    assert r.status_code == 409 and provider.charges == []


def test_payment_changed_since_the_preview_buys_nothing(api, ready, provider):
    s, snap = ready
    pv = api.post(f"/api/v1/shipments/{s.id}/preview", headers=R).json()
    snap.financial_status = "PENDING"
    r = api.post(
        f"/api/v1/shipments/{s.id}/buy",
        headers=W,
        json={"basis": pv["basis"], "idempotency_key": "clive-buy-0001"},
    )
    assert r.status_code == 409 and r.json()["detail"]["code"] == "payment"
    assert provider.charges == [] and "create_order" not in provider.calls


def test_an_unauthorised_order_is_refused_by_the_same_gate(svc, ready, provider):
    """CLIVE has no way round the screen's buying authorisation: it is the service's gate."""
    s, _ = ready
    svc.may_buy = lambda shipment: False
    with app_for(svc) as c:
        r = buy(c, s.id)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "not_authorised"
    assert provider.charges == []


# ------------------------------------------------------------------ printing


def test_printing_is_refused_while_printnode_is_off(api, ready):
    s, _ = ready
    buy(api, s.id)
    r = api.post(f"/api/v1/shipments/{s.id}/print", headers=W, json={"idempotency_key": "p-000001"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "printing_disabled"


def test_clive_prints_once_and_reprints_only_when_it_says_so(api, ready, provider, svc):
    s, _ = ready
    buy(api, s.id)
    row = svc.store.get(SHOP, s.id)  # a real 4x6 label PDF, as a provider returns it
    row.label.document(DocumentKind.shipping_label).artifact_id = svc.store.put_artifact(
        SHOP, s.id, "shipping_label", "application/pdf", bundle(("LABEL",))
    )
    svc.store.save(row)
    sender = Mock()
    sender.print_pdf.side_effect = range(7000, 7100)
    sender.get_job_states.return_value = [dict(state="done", at="2026-10-07T15:25:31Z", message="")]
    api.app.state.operations.physical.provider = sender  # PrintNode switched on
    charges = list(provider.charges)
    p1 = api.post(
        f"/api/v1/shipments/{s.id}/print", headers=W, json={"idempotency_key": "p-000001"}
    )
    p2 = api.post(
        f"/api/v1/shipments/{s.id}/print", headers=W, json={"idempotency_key": "p-000002"}
    )
    assert p1.status_code == 200, p1.json()
    assert p2.status_code == 200
    assert sender.print_pdf.call_count == 1  # a second first-print never prints again
    # PrintNode took it; until it says the printer finished, it is printing, not printed.
    assert p1.json()["sent_to_printer"] and p1.json()["shipment"]["stage"] == "bought"
    assert p1.json()["shipment"]["print"] == "Printing…"
    api.app.state.operations.resume(SHOP)  # the minute's check asks PrintNode: done
    done = api.get(f"/api/v1/shipments/{s.id}", headers=R).json()
    assert done["stage"] == "printed" and done["print"] == "Printed"
    no = api.post(
        f"/api/v1/shipments/{s.id}/reprint", headers=W, json={"idempotency_key": "r-000001"}
    )
    assert no.status_code == 422 and sender.print_pdf.call_count == 1
    yes = api.post(
        f"/api/v1/shipments/{s.id}/reprint",
        headers=W,
        json={"idempotency_key": "r-000001", "confirm": True},
    )
    assert yes.status_code == 200 and sender.print_pdf.call_count == 2
    assert provider.charges == charges  # printing never buys


# ------------------------------------------------------------------ what changed


def test_events_say_what_changed_on_which_order(api, ready, clock):
    s, _ = ready
    before = clock().isoformat()
    clock.advance(minutes=1)
    buy(api, s.id)
    events = api.get("/api/v1/events", params={"since": before}, headers=R).json()["events"]
    types = [e["type"] for e in events]
    assert "label_purchased" in types and all(e["order"] == s.order_name for e in events)
    bought = next(e for e in events if e["type"] == "label_purchased")
    assert bought["verified"] and bought["what"] == "Label purchased"
    assert bought["source"] == "api"  # as in Returns: where each change came from
    assert all(e["source"] in ("api", "system", "ui") for e in events)


def test_events_page_oldest_first_and_paging_skips_nothing(api, ready, clock):
    s, _ = ready
    start = clock().isoformat()
    clock.advance(minutes=1)
    buy(api, s.id)
    every = api.get("/api/v1/events", params={"since": start}, headers=R).json()
    assert not every["has_more"] and len(every["events"]) >= 3
    seen, since = [], start
    for _ in range(20):  # a page of one, again and again, from the last `at` seen
        got = api.get("/api/v1/events", params={"since": since, "limit": 1}, headers=R).json()
        seen += got["events"]
        if not got["has_more"]:
            break
        since = got["events"][-1]["at"]
    assert [e["type"] for e in seen] == [e["type"] for e in every["events"]]  # oldest first


def test_a_since_without_a_zone_is_utc_not_an_error(api, ready, clock):
    s, _ = ready
    naive = clock().replace(tzinfo=None).isoformat()
    clock.advance(minutes=1)
    buy(api, s.id)
    r = api.get("/api/v1/events", params={"since": naive}, headers=R)
    assert r.status_code == 200 and any(e["type"] == "label_purchased" for e in r.json()["events"])


def test_a_key_with_any_characters_is_refused_not_a_crash(api):
    r = api.get("/api/v1/shipments", headers={"Authorization": "Bearer clé".encode("latin-1")})
    assert r.status_code == 403
