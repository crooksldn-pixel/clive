"""The Shipping tabs: one derived stage per order (shipping.lifecycle), and the bulk actions each
tab allows, enforced by the server, not just hidden in the page."""

import pytest
from fastapi.testclient import TestClient

from shipping import lifecycle
from shipping.app import create_app
from shipping.models import ShipmentStatus as S
from shipping.models import TrackingState
from shipping.settings import Settings

from . import test_operations as operations
from .conftest import SHOP

# The operations tests' fixtures and helpers, shared the way those tests share printing's.
svc, shopify, ops, sender = operations.svc, operations.shopify, operations.ops, operations.sender
ready, purchased = operations.ready, operations.purchased


def summary(state="not_printed", first=True):
    return {"state": state, "first_print_available": first}


# ------------------------------------------------------------------ precedence


def test_unbought_orders_are_ready_or_need_attention(svc, shopify):
    rows = ready(svc, shopify, 2)
    assert {lifecycle.stage(s, None) for s in rows} == {"ready"}
    s = rows[0]
    s.payment_status = "PENDING"
    assert lifecycle.stage(s, None) == "attention"  # payment alone is enough
    s.payment_status = "PAID"
    s.status = S.needs_attention
    assert lifecycle.stage(s, None) == "attention"


def test_bought_labels_move_through_print_carrier_and_delivery(svc, shopify):
    (s,) = purchased(svc, shopify, 1)
    assert lifecycle.stage(s, summary()) == "bought"
    for not_printed in ("sending", "failed", "unknown"):  # never shown as Printed
        assert lifecycle.stage(s, summary(not_printed, first=False)) == "bought"
    assert lifecycle.stage(s, summary("sent", first=False)) == "printed"
    s.tracking = TrackingState(stage="pre_transit")
    assert lifecycle.stage(s, summary("sent", first=False)) == "printed"
    s.tracking = TrackingState(stage="in_transit")
    assert lifecycle.stage(s, summary("sent", first=False)) == "in_transit"
    assert lifecycle.stage(s, summary()) == "in_transit"  # moving even if never printed here
    s.tracking = TrackingState(stage="exception")
    assert lifecycle.stage(s, summary()) == "in_transit"  # a carrier problem: warn, not delivered
    s.tracking = TrackingState(stage="delivered")
    assert lifecycle.stage(s, summary("sent", first=False)) == "delivered"
    s.tracking = TrackingState(stage="cancelled")
    assert lifecycle.stage(s, summary()) == "attention"


@pytest.mark.parametrize(
    ("status", "stage"),
    [
        (S.reconciliation_required, "attention"),
        (S.purchasing, "attention"),
        (S.fulfillment_failed, "attention"),
        (S.cancelled, "closed"),
        (S.voided, "closed"),
    ],
)
def test_orders_a_person_must_settle(svc, shopify, status, stage):
    (s,) = purchased(svc, shopify, 1)
    s.status = status
    assert lifecycle.stage(s, summary()) == stage


# ------------------------------------------------------------------ bulk, server side


def test_bulk_buy_takes_only_ready_orders(svc, shopify, ops, provider):
    rows = ready(svc, shopify, 3)
    rows[1].payment_status = "PENDING"
    svc.store.save(rows[1])
    b = ops.preview(SHOP, "buy", [s.id for s in rows], "staff", "k")
    states = {c["shipment_id"]: c["state"] for c in b["children"]}
    assert states[rows[1].id] == "excluded" and list(states.values()).count("review") == 2
    assert not provider.charges


def test_bulk_first_print_takes_only_unprinted_labels_not_moving(svc, shopify, ops, sender):
    rows = purchased(svc, shopify, 3)
    moving = svc.store.get(SHOP, rows[1].id)
    moving.tracking = TrackingState(stage="in_transit")
    svc.store.save(moving)
    ops.physical.print_label(SHOP, rows[2].id, "staff", "first")  # printed already
    b = ops.preview(SHOP, "print", [s.id for s in rows], "staff", "k")
    c = {c["shipment_id"]: c for c in b["children"]}
    assert c[rows[0].id]["state"] == "review"
    assert (
        c[rows[1].id]["state"] == "excluded"
        and "carrier already has it" in c[rows[1].id]["message"]
    )
    assert c[rows[2].id]["state"] == "excluded"  # Printed: only an explicit Reprint
    assert sender.print_pdf.call_count == 1  # the review itself prints nothing


# ------------------------------------------------------------------ the inbox API


@pytest.fixture
def client(svc):
    cfg = Settings(shop_domain=SHOP, provider="fake", dev_skip_admin_auth=True, tick_interval_s=0)
    with TestClient(create_app(cfg, svc)) as c:
        yield c


def test_the_inbox_serves_one_stage_with_counts_for_all(svc, shopify, client):
    rows = ready(svc, shopify, 3)
    rows[0].payment_status = "PENDING"
    svc.store.save(rows[0])
    ib = client.get("/admin/api/inbox?stage=ready").json()
    assert ib["stage"] == "ready" and len(ib["rows"]) == 2
    assert ib["counts"]["ready"] == 2 and ib["counts"]["attention"] == 1
    assert all(r["can_buy"] is False or r["stage"] == "ready" for r in ib["rows"])
    att = client.get("/admin/api/inbox?stage=attention").json()
    assert [r["order"] for r in att["rows"]] == [rows[0].order_name]
    assert not att["rows"][0]["can_select"]  # Needs attention: no Buy, no Print
    assert client.get("/admin/api/inbox?stage=nonsense").json()["stage"] == "attention"
    assert len(client.get("/admin/api/inbox?stage=all").json()["rows"]) == 3


def test_search_stays_within_the_stage(svc, shopify, client):
    rows = ready(svc, shopify, 3)
    number = rows[1].order_name.split("-")[-1]
    ib = client.get(f"/admin/api/inbox?stage=ready&q={number}").json()
    assert [r["order"] for r in ib["rows"]] == [rows[1].order_name]
    assert ib["counts"]["ready"] == 1  # counts follow the search too
    assert client.get(f"/admin/api/inbox?stage=delivered&q={number}").json()["rows"] == []


def test_detail_keeps_payment_print_and_carrier_apart(svc, shopify, client):
    (s,) = purchased(svc, shopify, 1)
    s = svc.store.get(SHOP, s.id)
    s.tracking = TrackingState(stage="in_transit")
    s.payment_status = "REFUNDED"
    svc.store.save(s)
    d = client.get(f"/admin/api/shipments/{s.id}").json()
    assert d["stage"] == "in_transit" and d["stage_title"] == "In transit"
    assert d["payment"]["label"] == "Refunded" and d["payment"]["note"]
    assert d["carrier"]["label"] == "In transit"
    assert d["print_status"]["state"] == "not_printed"
