"""The acceptance scenarios (A-H) and the failure modes around them, end to end against the fake
Shopify (which keeps Shopify's own rules: ON_SALE commits stock, DENY refuses past zero)."""

import json

import pytest

from preorders.domain import CommerceState
from preorders.service import ActionError
from preorders.shopify import ShopifyError

from .conftest import line_of, open_preorder


def plan(shopify, vid):
    return shopify.plan_of(vid)


# ------------------------------------------------------------------ A-D: state per variant


def test_a_normal_stock_stays_normal(svc, shopify, jogger):
    pid, sizes = jogger
    open_preorder(svc, pid, sizes)
    assert svc.state_of(sizes["XS"]) == CommerceState.IN_STOCK
    assert plan(shopify, sizes["XS"]) is None  # never offered as a preorder
    assert shopify.variants_by_id[sizes["XS"]].inventory_policy == "DENY"
    row = next(r for r in svc.products() if r["variant_id"] == sizes["XS"])
    assert row["badge"] == "In stock"


def test_b_incoming_preorder_counts_sales(svc, shopify, jogger):
    pid, sizes = jogger
    batch, offer = open_preorder(svc, pid, sizes, m=100, alloc_m=90)
    m = sizes["M"]
    assert svc.state_of(m) == CommerceState.PREORDER
    assert shopify.variants_by_id[m].inventory_policy == "CONTINUE"  # may sell past zero
    for _ in range(31):
        svc.ingest_order(shopify.checkout([(m, 1, plan(shopify, m))]))
    view = svc.offer_view(offer["id"])
    vm = next(v for v in view["variants"] if v["variant_id"] == m)
    assert (vm["sold"], vm["remaining"], vm["preorder_allocation"]) == (31, 59, 90)
    assert svc.state_of(m) == CommerceState.PREORDER
    assert json.loads(shopify.metafields[m])["state"] == "PREORDER"
    assert json.loads(shopify.metafields[m])["dispatch_by"] == "2026-11-07"
    # Shopify committed the preordered units; the snapshot the screens read says so at once.
    stock = svc.variant(m)
    assert (stock["available"], stock["committed"]) == (-31, 31)


def test_c_sold_out_preorder_falls_back_to_notify_me_and_refuses_more(svc, shopify, jogger):
    pid, sizes = jogger
    open_preorder(svc, pid, sizes, s=10, alloc_s=3)
    s = sizes["S"]
    p = plan(shopify, s)
    svc.ingest_order(shopify.checkout([(s, 3, p)]))
    assert svc.state_of(s) == CommerceState.NOTIFY_ME
    assert plan(shopify, s) is None  # off the selling plan
    assert shopify.variants_by_id[s].inventory_policy == "DENY"  # no sale past zero
    with pytest.raises(ValueError):  # a 4th preorder through the old plan
        shopify.checkout([(s, 1, p)])
    with pytest.raises(ValueError):  # or as an ordinary purchase
        shopify.checkout([(s, 1, None)])
    row = next(r for r in svc.products() if r["variant_id"] == s)
    assert row["badge"] == "Sold out" and row["remaining"] == 0


def test_d_nothing_inbound_collects_demand(svc, shopify, jogger):
    pid, sizes = jogger
    assert svc.state_of(sizes["L"]) == CommerceState.NOTIFY_ME
    out = svc.waitlist.signup(variant_id=sizes["L"], email="Ann@Example.com")
    assert out["status"] == "joined"
    again = svc.waitlist.signup(variant_id=sizes["L"], email="ann@example.com ")
    assert again["status"] == "already"  # one active signup per email and size
    top = svc.waitlist.demand("most_wanted")
    assert [(r["variant"], r["signups"]) for r in top] == [("L", 1)]
    # An in-stock size isn't a waitlist.
    assert (
        svc.waitlist.signup(variant_id=sizes["XS"], email="b@example.com")["status"] == "available"
    )


# ------------------------------------------------------------------ E: mixed orders


def test_e_mixed_order_keeps_lines_apart(svc, shopify, jogger):
    pid, sizes = jogger
    open_preorder(svc, pid, sizes)
    oid = shopify.checkout([(sizes["XS"], 1, None), (sizes["S"], 1, plan(shopify, sizes["S"]))])
    svc.ingest_order(oid)
    out = {x["variant_id"]: x["classification"] for x in svc.classify_order(oid)["lines"]}
    assert out == {sizes["XS"]: "IN_STOCK", sizes["S"]: "PREORDER_WAITING"}
    # Shopify keeps them apart too: the in-stock line is OPEN (Shipping sees it), the preorder
    # line SCHEDULED (Shipping only reads open fulfilment orders).
    fos = {f.status: f.line_item_ids for f in shopify.orders[oid].fulfillment_orders}
    assert set(fos) == {"OPEN", "SCHEDULED"}
    xs_line = next(x for x in shopify.orders[oid].lines if x.variant_id == sizes["XS"])
    assert svc.classify_line(xs_line.line_item_id)["classification"] == "IN_STOCK"


# ------------------------------------------------------------------ F: delays


def test_f_delay_keeps_the_original_promise_and_notifies_only_on_request(
    svc, shopify, mailer, jogger
):
    pid, sizes = jogger
    batch, offer = open_preorder(svc, pid, sizes)
    m = sizes["M"]
    for email in ("a@example.com", "b@example.com"):
        svc.ingest_order(shopify.checkout([(m, 2, plan(shopify, m))], email=email))
    assert svc.affected(batch["id"]) == {"units": 4, "lines": 2, "orders": 2, "customers": 2}
    svc.change_dispatch(batch["id"], expected_dispatch_at="2026-11-14", delayed=True, actor="Sam")
    assert mailer.sent == []  # saving never emails anyone
    lines = svc.preorder_lines()
    assert {(x["promised_dispatch_at"], x["current_dispatch_at"]) for x in lines} == {
        ("2026-11-07", "2026-11-14")
    }
    assert svc.batch(batch["id"])["status"] == "DELAYED"
    # New orders are sold on a new plan with the new date; the old orders keep theirs.
    new_plan = plan(shopify, m)
    assert new_plan != offer["selling_plan_id"]
    svc.ingest_order(shopify.checkout([(m, 1, new_plan)], email="c@example.com"))
    c = next(x for x in svc.preorder_lines() if x["customer_email"] == "c@example.com")
    assert c["promised_dispatch_at"] == "2026-11-14"
    assert svc.comms.audience(batch["id"])["customers"] == 3
    sent = svc.comms.notify_delay(batch["id"], "Sam")
    assert (sent["SENT"], sent["unchanged"]) == (2, 1)  # c bought on 14 November: no news
    a = next(x for x in mailer.sent if x["to"] == "a@example.com")
    assert "7 November" in a["text"] and "14 November" in a["text"]
    again = svc.comms.notify_delay(batch["id"], "Sam")
    assert again["SENT"] == 0 and again["ALREADY"] == 2 and len(mailer.sent) == 2


# ------------------------------------------------------------------ G: receiving stock


def test_g_partial_receipt_updates_shopify_once_and_readies_oldest(svc, shopify, jogger, clock):
    pid, sizes = jogger
    batch, _ = open_preorder(svc, pid, sizes, m=100, alloc_m=90)
    m = sizes["M"]
    first = shopify.checkout([(m, 40, plan(shopify, m))], email="early@example.com")
    clock.advance(hours=1)
    second = shopify.checkout([(m, 30, plan(shopify, m))], email="later@example.com")
    svc.ingest_order(first)
    svc.ingest_order(second)
    ln = line_of(svc, batch, m)
    out = svc.receive(ln["id"], 65, "receipt-key-1", "Sam")
    b = out["batch"]
    got = line_of(svc, b, m)
    assert (got["received_quantity"], got["outstanding"]) == (65, 35)
    assert b["status"] == "PARTIALLY_RECEIVED"
    assert shopify.variants_by_id[m].available == -70 + 65  # Shopify got +65, once
    states = {x["customer_email"]: (x["state"], x["ready_quantity"]) for x in svc.preorder_lines()}
    assert states == {
        "early@example.com": ("READY", 40),
        "later@example.com": ("AWAITING_STOCK", 25),
    }
    # The same request again (double click, lost reply) changes nothing.
    again = svc.receive(ln["id"], 65, "receipt-key-1", "Sam")
    assert again["replayed"] and shopify.variants_by_id[m].available == -5
    assert len(shopify.adjustments) == 1
    with pytest.raises(ActionError):  # more than is still expected
        svc.receive(ln["id"], 36, "receipt-key-2", "Sam")


def test_lost_receipt_reply_is_retried_with_the_same_key(svc, shopify, jogger):
    pid, sizes = jogger
    batch, _ = open_preorder(svc, pid, sizes)
    ln = line_of(svc, batch, sizes["S"])
    shopify.fail_next("adjust_available", "unknown")
    with pytest.raises(ActionError) as caught:
        svc.receive(ln["id"], 10, "receipt-lost-1", "Sam")
    assert caught.value.code == "unknown"
    assert line_of(svc, svc.batch(batch["id"]), sizes["S"])["received_quantity"] == 0
    with pytest.raises(ActionError):  # a different receipt waits for that one
        svc.receive(ln["id"], 5, "receipt-other", "Sam")
    # Staff confirm it from the batch page (the dialog that held the key is gone by then).
    unconfirmed = next(r for r in svc.batch(batch["id"])["receipts"] if r["status"] == "UNKNOWN")
    svc.retry_receipt(unconfirmed["id"], "Sam")
    assert line_of(svc, svc.batch(batch["id"]), sizes["S"])["received_quantity"] == 10
    assert shopify.variants_by_id[sizes["S"]].available == 10
    svc.retry_receipt(unconfirmed["id"], "Sam")  # a second press adds nothing
    assert shopify.variants_by_id[sizes["S"]].available == 10


def test_a_receipt_that_cant_be_sent_is_never_left_pending(svc, shopify, jogger):
    pid, sizes = jogger
    batch, _ = open_preorder(svc, pid, sizes)
    ln = line_of(svc, batch, sizes["S"])
    svc.store.x("UPDATE batch_lines SET inventory_item_id = NULL WHERE id = ?", (ln["id"],))
    with pytest.raises(ActionError):
        svc.receive(ln["id"], 3, "receipt-no-item", "Sam")
    assert svc.store.value("SELECT COUNT(*) FROM receipts") == 0


def test_full_receipt_moves_preorder_to_in_stock(svc, shopify, jogger):
    pid, sizes = jogger
    batch, offer = open_preorder(svc, pid, sizes)
    s = sizes["S"]
    svc.ingest_order(shopify.checkout([(s, 4, plan(shopify, s))]))
    for size, n in (("S", 30), ("M", 50)):
        svc.receive(line_of(svc, batch, sizes[size])["id"], n, f"full-{size}-key", "Sam")
    assert svc.batch(batch["id"])["status"] == "RECEIVED"
    assert svc.offer(offer["id"])["status"] == "CLOSED"
    assert svc.state_of(s) == CommerceState.IN_STOCK
    assert plan(shopify, s) is None
    assert shopify.variants_by_id[s].inventory_policy == "DENY"  # back as it was
    assert svc.preorder_lines()[0]["state"] == "READY"
    assert svc.release_preview(batch["id"])["orders"] == 1
    released = svc.release_ready(batch["id"], "Sam")
    assert len(released["opened"]) == 1  # the scheduled fulfilment order opens for dispatch
    # Released once: nothing is offered again, and pressing it again changes nothing.
    assert svc.release_preview(batch["id"])["orders"] == 0
    again = svc.release_ready(batch["id"], "Sam")
    assert again == {"opened": [], "already_open": [], "skipped": []}


def test_release_survives_a_lost_reply_and_counts_orders_already_open(svc, shopify, jogger):
    pid, sizes = jogger
    batch, _ = open_preorder(svc, pid, sizes)
    s = sizes["S"]
    first = shopify.checkout([(s, 1, plan(shopify, s))])
    second = shopify.checkout([(s, 1, plan(shopify, s))])
    for oid in (first, second):
        svc.ingest_order(oid)
    svc.receive(line_of(svc, batch, s)["id"], 2, "rcv-two-key", "Sam")
    shopify.fail_next("open_fulfillment_order", "unknown")
    with pytest.raises(ShopifyError):
        svc.release_ready(batch["id"], "Sam")
    assert svc.release_preview(batch["id"])["orders"] == 2  # not marked on an unknown outcome
    # Meanwhile someone opened one in Shopify admin (or Shopify did, on the date).
    fo = shopify.orders[second].fulfillment_orders[0]
    fo.status = "OPEN"
    out = svc.release_ready(batch["id"], "Sam")
    assert len(out["opened"]) + len(out["already_open"]) == 2
    assert svc.release_preview(batch["id"])["orders"] == 0


# ------------------------------------------------------------------ H: waitlist to preorder


def test_h_waitlist_is_told_when_preorder_opens_once(svc, shopify, mailer, jogger):
    pid, sizes = jogger
    for i in range(3):
        svc.waitlist.signup(variant_id=sizes["M"], email=f"w{i}@example.com")
    assert svc.waitlist.notify_preview(sizes["M"])["reason"] is None  # nothing to tell yet
    with pytest.raises(ActionError):
        svc.waitlist.notify(sizes["M"], "Sam")
    open_preorder(svc, pid, sizes, m=200, alloc_m=180)
    preview = svc.waitlist.notify_preview(sizes["M"])
    assert (preview["count"], preview["reason"]) == (3, "PREORDER_OPEN")
    out = svc.waitlist.notify(sizes["M"], "Sam")
    assert out["SENT"] == 3 and "open for preorder" in mailer.sent[0]["subject"]
    assert "unsubscribe" in mailer.sent[0]["text"]
    assert {r["status"] for r in svc.waitlist.subscribers(sizes["M"])} == {"NOTIFIED"}
    assert svc.waitlist.notify(sizes["M"], "Sam")["SENT"] == 0  # never twice
    # A waiter who then preorders counts as converted.
    svc.ingest_order(
        shopify.checkout([(sizes["M"], 1, plan(shopify, sizes["M"]))], email="w0@example.com")
    )
    assert {r["email"]: r["status"] for r in svc.waitlist.subscribers(sizes["M"])}[
        "w0@example.com"
    ] == "CONVERTED"


# ------------------------------------------------------------------ webhooks and replays


def test_webhook_replay_and_reordering_change_nothing(svc, shopify, jogger):
    pid, sizes = jogger
    batch, offer = open_preorder(svc, pid, sizes)
    s = sizes["S"]
    oid = shopify.checkout([(s, 2, plan(shopify, s))])
    assert svc.record_webhook("evt-1", "orders/updated", oid)  # update before create
    assert svc.record_webhook("evt-2", "orders/create", oid)
    assert not svc.record_webhook("evt-2", "orders/create", oid)  # Shopify's retry
    svc.process_inbox()
    svc.ingest_order(oid)
    svc.ingest_order(oid)
    assert len(svc.preorder_lines()) == 1
    assert line_of(svc, svc.batch(batch["id"]), s)["sold"] == 2


def test_cancellation_and_refund_give_capacity_back(svc, shopify, jogger):
    pid, sizes = jogger
    open_preorder(svc, pid, sizes, s=10, alloc_s=3)
    s = sizes["S"]
    oid = shopify.checkout([(s, 3, plan(shopify, s))])
    svc.ingest_order(oid)
    assert svc.state_of(s) == CommerceState.NOTIFY_ME  # sold through
    shopify.cancel(oid)
    svc.ingest_order(oid)
    assert svc.preorder_lines("cancelled")[0]["state"] == "CANCELLED"
    assert svc.state_of(s) == CommerceState.PREORDER  # capacity back, back on sale
    assert plan(shopify, s) is not None
    other = shopify.checkout([(s, 2, plan(shopify, s))])
    svc.ingest_order(other)
    line = next(x for x in shopify.orders[other].lines)
    shopify.refund(other, line.line_item_id, 1)
    svc.ingest_order(other)
    assert svc.sold_for_line(svc.preorder_lines()[0]["batch_line_id"]) == 1


def test_simultaneous_checkouts_beyond_the_allocation_are_shown_not_hidden(svc, shopify, jogger):
    pid, sizes = jogger
    batch, _ = open_preorder(svc, pid, sizes, s=10, alloc_s=2)
    s = sizes["S"]
    p = plan(shopify, s)
    a = shopify.checkout([(s, 2, p)])  # both pass checkout before either is ingested
    b = shopify.checkout([(s, 2, p)])
    svc.ingest_order(a)
    svc.ingest_order(b)
    ln = line_of(svc, svc.batch(batch["id"]), s)
    assert (ln["sold"], ln["remaining"], ln["oversold"]) == (4, 0, 2)
    assert plan(shopify, s) is None and shopify.variants_by_id[s].inventory_policy == "DENY"
    kinds = {x["kind"] for x in svc.overview()["attention"]}
    assert "oversold" in kinds


def test_a_preorder_size_bought_without_the_plan_is_flagged(svc, shopify, jogger):
    pid, sizes = jogger
    open_preorder(svc, pid, sizes)
    oid = shopify.checkout([(sizes["S"], 1, None)])  # CONTINUE lets it through
    svc.ingest_order(oid)
    assert svc.preorder_lines() == []  # never guessed into a preorder
    assert "unplanned" in {x["kind"] for x in svc.overview()["attention"]}


# ------------------------------------------------------------------ Shopify refusing


def test_without_purchase_option_access_nothing_is_sold_as_a_preorder(svc, shopify, jogger):
    pid, sizes = jogger
    shopify.access_denied = True
    batch, offer = open_preorder(svc, pid, sizes)
    assert not svc.plans.available and "purchase-option access" in svc.plans.reason
    assert svc.offer(offer["id"])["sync_error"]
    assert svc.state_of(sizes["S"]) == CommerceState.NOTIFY_ME  # no imitation preorder
    assert shopify.variants_by_id[sizes["S"]].inventory_policy == "DENY"
    assert shopify.groups == {}


def test_switching_selling_off_takes_live_preorders_off_sale(svc, shopify, jogger):
    # The kill switch (PREORDERS_SELLING_PLANS=off, then a restart) after offers went live.
    from preorders.selling_plans import OFF, UnavailablePlans

    pid, sizes = jogger
    batch, offer = open_preorder(svc, pid, sizes)
    s = sizes["S"]
    assert shopify.variants_by_id[s].inventory_policy == "CONTINUE"
    svc.plans = UnavailablePlans(OFF, shopify)
    result = svc.sync_offer(offer["id"])
    assert result["ok"] is False and svc.offer(offer["id"])["sync_error"] == OFF
    assert shopify.variants_by_id[s].inventory_policy == "DENY"  # no longer sells past zero
    assert plan(shopify, s) is None  # and off the plan
    svc.close_offer(offer["id"], "Sam")
    assert shopify.variants_by_id[s].inventory_policy == "DENY"


def test_access_lost_after_going_live_still_stops_sales_and_is_retried(svc, shopify, jogger):
    pid, sizes = jogger
    batch, offer = open_preorder(svc, pid, sizes)
    s = sizes["S"]
    shopify.access_denied = True  # e.g. scope removed; the next plan change is refused
    svc.change_dispatch(batch["id"], expected_dispatch_at="2026-11-14", actor="Sam")
    assert not svc.plans.available
    assert "purchase-option access" in svc.offer(offer["id"])["sync_error"]
    assert shopify.variants_by_id[s].inventory_policy == "DENY"
    assert plan(shopify, s) is None
    assert "sync" in {a["kind"] for a in svc.overview()["attention"]}
    shopify.access_denied = False  # access comes back: the next pass tries again by itself
    svc.sync_all()
    assert svc.plans.available and svc.offer(offer["id"])["sync_error"] is None
    assert shopify.variants_by_id[s].inventory_policy == "CONTINUE" and plan(shopify, s)


def test_a_selling_plan_group_deleted_in_shopify_is_rebuilt_in_one_pass(svc, shopify, jogger):
    pid, sizes = jogger
    batch, offer = open_preorder(svc, pid, sizes)
    shopify.groups.clear()
    result = svc.sync_offer(offer["id"])
    assert result["ok"] and svc.offer(offer["id"])["sync_error"] is None
    assert plan(shopify, sizes["S"]) is not None
    assert shopify.variants_by_id[sizes["S"]].inventory_policy == "CONTINUE"


def test_a_failed_sync_is_retried_without_duplicating(svc, shopify, jogger):
    pid, sizes = jogger
    shopify.fail_next("add_to_group", "unknown")
    batch, offer = open_preorder(svc, pid, sizes)
    assert svc.offer(offer["id"])["sync_error"]
    assert shopify.variants_by_id[sizes["S"]].inventory_policy == "DENY"  # not opened half-way
    svc.sync_offer(offer["id"])
    assert svc.offer(offer["id"])["sync_error"] is None
    assert len(shopify.groups) == 1 and plan(shopify, sizes["S"]) is not None


def test_allocation_rules(svc, shopify, jogger):
    pid, sizes = jogger
    batch, _ = open_preorder(svc, pid, sizes, s=10, alloc_s=8)
    s = sizes["S"]
    svc.ingest_order(shopify.checkout([(s, 5, plan(shopify, s))]))
    ln = line_of(svc, batch, s)
    with pytest.raises(ActionError):
        svc.update_batch_line(ln["id"], preorder_allocation=4, actor="Sam")  # below sold
    with pytest.raises(ActionError):
        svc.update_batch_line(ln["id"], preorder_allocation=11, actor="Sam")  # above coming
    svc.update_batch_line(ln["id"], preorder_allocation=5, actor="Sam")
    assert svc.state_of(s) == CommerceState.NOTIFY_ME and plan(shopify, s) is None


def test_reconciliation_rebuilds_what_webhooks_missed(svc, shopify, jogger, clock):
    pid, sizes = jogger
    batch, _ = open_preorder(svc, pid, sizes)
    s = sizes["S"]
    shopify.checkout([(s, 2, plan(shopify, s))], at=clock())  # no webhook ever arrives
    from preorders.reconcile import reconcile

    report = reconcile(svc)
    assert report["orders"] == 1 and len(svc.preorder_lines()) == 1
    assert line_of(svc, svc.batch(batch["id"]), s)["sold"] == 2
    assert reconcile(svc)["orders"] == 1 and len(svc.preorder_lines()) == 1  # idempotent


def test_closing_restores_the_variants_own_policy(svc, shopify, jogger):
    pid, sizes = jogger
    _, offer = open_preorder(svc, pid, sizes)
    assert shopify.variants_by_id[sizes["S"]].inventory_policy == "CONTINUE"
    svc.close_offer(offer["id"], "Sam")
    assert shopify.variants_by_id[sizes["S"]].inventory_policy == "DENY"
    assert plan(shopify, sizes["S"]) is None
    assert svc.state_of(sizes["S"]) == CommerceState.NOTIFY_ME


def test_discount_is_on_the_plan_and_the_line(svc, shopify, jogger):
    pid, sizes = jogger
    _, offer = open_preorder(svc, pid, sizes, discount=10)
    group = next(iter(shopify.groups.values()))
    assert group.plans[-1].spec.discount_percent == 10
    assert group.plans[-1].spec.plan_name == "Pre-order: expected to dispatch by 7 November"
    svc.ingest_order(shopify.checkout([(sizes["S"], 1, plan(shopify, sizes["S"]))]))
    line = svc.preorder_lines()[0]
    assert (line["unit_price_minor"], line["discount_minor"]) == (3600, 400)


def test_classification_never_calls_an_unseen_preorder_in_stock(svc, shopify, jogger):
    # CLIVE asks before the order's webhook has been processed: the answer is still right.
    pid, sizes = jogger
    open_preorder(svc, pid, sizes)
    oid = shopify.checkout([(sizes["XS"], 1, None), (sizes["S"], 1, plan(shopify, sizes["S"]))])
    kinds = sorted(x["classification"] for x in svc.classify_order(oid)["lines"])
    assert kinds == ["IN_STOCK", "PREORDER_WAITING"]


# ------------------------------------------------------------------ review findings


def test_a_lost_reply_on_a_date_change_adopts_the_plan_shopify_made(svc, shopify, jogger):
    pid, sizes = jogger
    batch, offer = open_preorder(svc, pid, sizes, s=10, alloc_s=2)
    s = sizes["S"]
    shopify.fail_next("replace_plan", "lost")  # Shopify replaced it; the answer was lost
    svc.change_dispatch(batch["id"], expected_dispatch_at="2026-11-14", actor="Sam")
    live = plan(shopify, s)
    assert svc.offer(offer["id"])["selling_plan_id"] == live  # adopted, not orphaned
    for _ in range(2):
        svc.ingest_order(shopify.checkout([(s, 1, plan(shopify, s))]))
    rows = svc.preorder_lines()
    assert len(rows) == 2 and {r["promised_dispatch_at"] for r in rows} == {"2026-11-14"}
    assert shopify.variants_by_id[s].inventory_policy == "DENY"  # allocation used: stops
    with pytest.raises(ValueError):
        shopify.checkout([(s, 1, None)])


def test_a_closed_offer_leaves_the_next_offer_for_the_size_alone(svc, shopify, jogger):
    pid, sizes = jogger
    batch_a, offer_a = open_preorder(svc, pid, sizes)
    svc.close_offer(offer_a["id"], "Sam")
    batch_b, offer_b = open_preorder(svc, pid, sizes, dispatch="2026-12-05", arrival="2026-12-01")
    s = sizes["S"]
    assert shopify.variants_by_id[s].inventory_policy == "CONTINUE"
    shopify.calls.clear()
    for _ in range(3):
        svc.sync_offer(offer_a["id"])
        svc.sync_all()
    assert shopify.variants_by_id[s].inventory_policy == "CONTINUE"
    assert "set_inventory_policy" not in shopify.calls  # nobody fights over the size
    assert json.loads(shopify.metafields[s])["dispatch_by"] == "2026-12-05"


def test_the_same_receipt_twice_at_once_counts_once(svc, shopify, jogger, monkeypatch):
    pid, sizes = jogger
    batch, _ = open_preorder(svc, pid, sizes)
    ln = line_of(svc, batch, sizes["S"])
    real = shopify.adjust_available

    def double_click(*args):  # the second request arrives while the first is in flight
        monkeypatch.setattr(shopify, "adjust_available", real)
        svc.receive(ln["id"], 10, "rcv-double-key", "Sam")
        return real(*args)

    monkeypatch.setattr(shopify, "adjust_available", double_click)
    svc.receive(ln["id"], 10, "rcv-double-key", "Sam")
    assert line_of(svc, svc.batch(batch["id"]), sizes["S"])["received_quantity"] == 10
    assert shopify.variants_by_id[sizes["S"]].available == 10


def test_changing_the_preorders_own_date_moves_customers_and_mails_only_real_changes(
    svc, shopify, mailer, jogger
):
    pid, sizes = jogger
    batch, offer = open_preorder(svc, pid, sizes)
    s = sizes["S"]
    svc.ingest_order(shopify.checkout([(s, 1, plan(shopify, s))], email="a@example.com"))
    svc.configure_offer(product_id=pid, batch_id=batch["id"], dispatch_at="2026-12-20", actor="Sam")
    row = svc.preorder_lines()[0]
    assert (row["promised_dispatch_at"], row["current_dispatch_at"]) == ("2026-11-07", "2026-12-20")
    svc.comms.notify_delay(batch["id"], "Sam")
    assert len(mailer.sent) == 1 and "20 December" in mailer.sent[0]["text"]
    svc.ingest_order(shopify.checkout([(s, 1, plan(shopify, s))], email="b@example.com"))
    svc.comms.notify_delay(batch["id"], "Sam")
    assert len(mailer.sent) == 1  # b bought on the new date: nothing changed for them


def test_a_size_with_stock_on_the_shelf_is_not_on_the_preorder_plan(svc, shopify, jogger):
    pid, sizes = jogger
    batch, offer = open_preorder(svc, pid, sizes)
    s = sizes["S"]
    shopify.variants_by_id[s].available = 4  # stock turned up outside the batch
    svc.refresh_catalog(pid)
    svc.sync_offer(offer["id"])
    assert plan(shopify, s) is None
    assert shopify.variants_by_id[s].inventory_policy == "DENY"


def test_release_reports_held_and_mixed_fulfilment_orders(svc, shopify, jogger):
    pid, sizes = jogger
    batch, _ = open_preorder(svc, pid, sizes)
    s, m = sizes["S"], sizes["M"]
    held = shopify.checkout([(s, 1, plan(shopify, s))])
    mixed = shopify.checkout([(s, 1, plan(shopify, s)), (m, 1, plan(shopify, m))])
    for o in (held, mixed):
        svc.ingest_order(o)
    shopify.orders[held].fulfillment_orders[0].status = "ON_HOLD"
    svc.receive(line_of(svc, batch, s)["id"], 2, "rcv-two-s-key", "Sam")
    out = svc.release_ready(batch["id"], "Sam")
    assert out["opened"] == [] and out["already_open"] == []
    assert len(out["skipped"]) == 2  # said, not silently dropped
    assert svc.release_preview(batch["id"])["orders"] == 2  # still offered


def _one_delayed_order(svc, shopify, jogger):
    pid, sizes = jogger
    batch, _ = open_preorder(svc, pid, sizes)
    s = sizes["S"]
    svc.ingest_order(shopify.checkout([(s, 1, plan(shopify, s))], email="a@example.com"))
    svc.change_dispatch(batch["id"], expected_dispatch_at="2026-11-14", actor="Sam")
    return batch


def test_an_unconfirmed_email_is_retried_once_within_the_providers_window(
    svc, shopify, mailer, jogger, clock
):
    batch = _one_delayed_order(svc, shopify, jogger)
    mailer.fail_next = "unknown"  # it went out; the answer was lost
    assert svc.comms.notify_delay(batch["id"], "Sam")["UNKNOWN"] == 1
    clock.advance(hours=1)
    assert svc.comms.notify_delay(batch["id"], "Sam")["SENT"] == 1  # same key: delivered once
    assert len(mailer.sent) == 1


def test_an_unconfirmed_email_is_never_resent_after_the_providers_window(
    svc, shopify, mailer, jogger, clock
):
    batch = _one_delayed_order(svc, shopify, jogger)
    mailer.fail_next = "unknown"
    svc.comms.notify_delay(batch["id"], "Sam")
    clock.advance(hours=30)  # Resend has forgotten the key: a resend could arrive twice
    mailer.keys.clear()
    assert svc.comms.notify_delay(batch["id"], "Sam")["UNKNOWN"] == 1
    assert len(mailer.sent) == 1
    assert "emails" in {a["kind"] for a in svc.overview()["attention"]}
