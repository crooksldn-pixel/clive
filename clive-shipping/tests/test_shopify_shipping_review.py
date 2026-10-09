"""Failure modes found by the independent review of UK labels (2026-10-09), each a way a label
could be bought twice, wrongly recorded as bought, or left waiting where nobody sees it."""

from __future__ import annotations

import json

import httpx
import pytest

from shipping import domestic
from shipping.domestic import TRACKED_24, TRACKED_48
from shipping.fake_shopify import fo, tee_line
from shipping.models import DocumentKind, OpState
from shipping.models import ShipmentStatus as S
from shipping.money import Money
from shipping.operations import Operations
from shipping.physical_printing import PhysicalPrinting
from shipping.providers.base import ProviderUncertain
from shipping.providers.shopify_shipping import ShopifyShipping
from shipping.purchase import ActionError
from shipping.settings import Settings
from shipping.shopify import GraphQLShopify, ShopifyError, ShopifyRefused

from .conftest import SHOP
from .test_shopify_shipping import POLICY, World, label_of


@pytest.fixture
def w(store, clock) -> World:
    return World(store, clock)


# --------------------------------------------------------------------------- Shopify's answers


def gql(body: dict) -> tuple[GraphQLShopify, list]:
    posts: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/admin/oauth/access_token":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        posts.append(json.loads(request.content))
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GraphQLShopify("crooks.myshopify.com", "id", "s", http=client), posts


INTERNAL = {
    "errors": [{"message": "Internal error", "extensions": {"code": "INTERNAL_SERVER_ERROR"}}]
}


@pytest.mark.parametrize(
    "body",
    [
        INTERNAL,  # Shopify's usual internal-error shape: no data key at all
        {**INTERNAL, "data": None},
        {**INTERNAL, "data": {"shippingLabelPurchase": None}},
        {"errors": [{"message": "Timeout"}], "data": {"shippingLabelPurchase": None}},
    ],
)
def test_an_error_inside_shopify_is_unknown_never_a_refusal(body):
    client, posts = gql(body)
    with pytest.raises(ShopifyError) as caught:
        client.purchase_label({"fulfillmentOrderId": "x"})
    assert not isinstance(caught.value, ShopifyRefused) and len(posts) == 1


def test_refused_only_when_shopify_never_ran_it():
    for body in (
        {"errors": [{"message": "Parse error"}]},  # no data at all: the query never ran
        {"errors": "Not Found"},
        {
            "data": {"shippingLabelPurchase": None},
            "errors": [{"message": "Access denied", "extensions": {"code": "ACCESS_DENIED"}}],
        },
    ):
        client, _ = gql(body)
        with pytest.raises(ShopifyRefused) as caught:
            client.purchase_label({"fulfillmentOrderId": "x"})
        assert str(caught.value)  # says why, never an empty "()"


def test_a_result_id_wins_over_errors_beside_it():
    started = {"shippingLabelPurchaseResult": {"id": "gid://r/1", "status": "PENDING_PURCHASE"},
               "userErrors": []}  # fmt: skip
    throttled = [{"message": "Throttled", "extensions": {"code": "THROTTLED"}}]
    client, _ = gql({"data": {"shippingLabelPurchase": started}, "errors": throttled})
    assert client.purchase_label({})["shippingLabelPurchaseResult"]["id"] == "gid://r/1"


def test_an_internal_error_end_to_end_waits_unknown_never_ready(store, clock):
    w = World(store, clock)
    s = w.ready()
    client, posts = gql({**INTERNAL, "data": {"shippingLabelPurchase": None}})
    w.uk.api = client
    out = w.buy(s)
    after = w.get(s.id)
    assert out["may_have_been_charged"] and after.status == S.reconciliation_required
    assert "weren't charged" not in (after.last_error or "") and len(posts) == 1


# --------------------------------------------------------------------------- lost replies


def test_shopify_bought_without_fulfilling_is_never_bought_again_by_itself(w, clock):
    w.ss.creates_fulfillment, w.ss.lose_reply = False, True  # bought; nothing on the order
    s = w.ready()
    w.buy(s)
    other = w.ready(n=3002)
    for _ in range(4):
        clock.advance(minutes=5)
        w.svc.tick(SHOP)
    after = w.get(s.id)
    assert after.status == S.needs_attention and after.label_check
    ops = Operations(w.svc, PhysicalPrinting(w.store, None, 1))
    review = ops.preview(SHOP, "buy", [s.id, other.id], "george", "bulk-1")
    states = {c["shipment_id"]: c["state"] for c in review["children"]}  # type: ignore[index]
    assert states == {s.id: "excluded", other.id: "review"}
    assert w.ss.labels_bought == 1  # only the person can let it be bought again


def test_an_earlier_tracking_number_on_the_order_is_never_taken_for_this_label(w, clock):
    s = w.ready()
    snap = w.shopify.fos[s.fulfillment_order_id]
    snap.status, snap.tracking_numbers = "IN_PROGRESS", ["OLD123"]  # part-fulfilled earlier
    w.ss.lose_reply, w.ss.outcome = True, "PURCHASE_FAILED"  # nothing bought this time
    w.buy(s)
    for _ in range(3):
        clock.advance(minutes=6)
        w.svc.tick(SHOP)
    after = w.get(s.id)
    assert after.label is None and after.status == S.needs_attention
    assert w.store.label_purchase(SHOP, f"ss:{w.op(s.id).id}")["tracking_before"] == ["OLD123"]


def test_a_new_number_beside_an_old_one_is_the_one_adopted(w):
    s = w.ready()
    snap = w.shopify.fos[s.fulfillment_order_id]
    snap.status, snap.tracking_numbers = "IN_PROGRESS", ["OLD123"]
    w.ss.lose_reply = True
    w.buy(s)
    assert label_of(w.get(s.id)).tracking_number == "RM9001GB"


def test_poll_reads_that_fail_stay_unknown_then_settle_from_the_result(w, clock):
    s = w.ready()
    w.ss.pending_polls, w.ss.reads_fail = 1, 100
    out = w.buy(s)
    assert out["may_have_been_charged"] and w.get(s.id).status == S.reconciliation_required
    w.ss.reads_fail = 0
    for _ in range(2):  # Shopify finishes it on its next look
        clock.advance(minutes=1)
        w.svc.tick(SHOP)
    assert w.get(s.id).status == S.fulfilled and len(w.ss.purchases) == 1


def test_an_answer_without_a_result_id_is_unknown(w, clock):
    s = w.ready()
    w.ss.no_result_id = True  # Shopify bought it but said nothing usable
    w.buy(s)
    after = w.get(s.id)
    events = [e.type for e in after.timeline]
    assert "payment_outcome_unknown" in events and "purchase_failed" not in events
    assert label_of(after).tracking_number == "RM9001GB" and len(w.ss.purchases) == 1


def test_a_crash_before_sending_settles_as_never_sent_and_then_never_sends(w):
    s = w.ready()
    order = w.uk.create_order(s, s.quote, "op_crash")  # type: ignore[arg-type]
    assert w.uk.read_order(order.ref).failed  # never claimed for sending: nothing went out
    with pytest.raises(ProviderUncertain):  # settled as unsent: the request can't go out now
        w.uk.pay(order.ref)
    assert w.ss.purchases == []


def test_a_purchase_claimed_for_sending_is_never_settled_as_unsent(w):
    s = w.ready()
    order = w.uk.create_order(s, s.quote, "op_race")  # type: ignore[arg-type]
    w.uk.pay(order.ref)
    seen = w.uk.read_order(order.ref)
    assert seen.paid and not seen.failed and len(w.ss.purchases) == 1


def test_the_timer_and_a_slow_buy_never_both_decide(w, clock):
    """The sweep settles a buy interrupted before sending; the buy's thread then wakes up.
    Exactly one of them decides, and nothing is sent after "never sent" was believed."""
    s = w.ready()
    real_pay = w.uk.pay

    def slow_pay(ref):
        clock.advance(minutes=6)  # the thread stalls past interrupted_after
        w.svc.purchases.reconcile_all()  # the sweep: unknown, read back, never sent
        return real_pay(ref)

    w.uk.pay = slow_pay  # type: ignore[method-assign]
    w.buy(s)
    after = w.get(s.id)
    assert w.ss.purchases == [] and w.ss.labels_bought == 0
    assert after.status == S.ready and after.label is None


# --------------------------------------------------------------------------- Shopify refusals


def test_another_purchase_running_waits_for_a_person(w):
    s = w.ready()
    w.ss.outcome = "PURCHASE_FAILED"
    w.ss.fail_errors = [{"code": "JOB_NOT_ENQUEUED", "message": "Another label"}]
    out = w.buy(s)
    after = w.get(s.id)
    assert not out["charged"] and after.status == S.needs_attention
    assert [q.kind for q in after.questions] == ["label_check"]
    assert "Check the order in Shopify admin for a label" in after.questions[0].text
    with pytest.raises(ActionError):
        w.svc.preview(SHOP, s.id)


def test_refusal_wording_has_no_doubled_full_stops(w):
    s = w.ready()
    w.ss.user_errors = [{"code": "RATES_NOT_FOUND", "field": None, "message": "x"}]
    w.buy(s)
    assert ".." not in (w.get(s.id).last_error or "")


# --------------------------------------------------------------------------- documents


def test_a_file_that_isnt_really_a_pdf_is_never_stored_and_is_fetched_again(w, clock):
    good = w.ss.label_file
    w.ss.label_file = b"<html>Service unavailable</html>"
    s = w.ready()
    assert w.buy(s)["charged"]
    label = label_of(w.get(s.id))
    assert label.document(DocumentKind.shipping_label) is None and not label.complete
    w.ss.label_file = good
    clock.advance(minutes=1)
    w.svc.tick(SHOP)
    assert label_of(w.get(s.id)).complete and len(w.ss.purchases) == 1


def test_tracking_that_arrives_late_is_filled_in_and_the_order_fulfilled(w, clock):
    w.ss.creates_fulfillment, w.ss.tracking_late = False, 2  # the poll and the documents read
    s = w.ready()
    w.buy(s)
    assert label_of(w.get(s.id)).tracking_number is None
    clock.advance(minutes=3)
    w.svc.tick(SHOP)
    w.svc.tick(SHOP)
    after = w.get(s.id)
    assert label_of(after).tracking_number == "RM9001GB" and after.status == S.fulfilled


# --------------------------------------------------------------------------- switching off


def test_switching_off_with_a_purchase_open_keeps_it_visible_and_checked(w, clock):
    s = w.ready()
    w.ss.pending_polls = 10_000
    w.buy(s)
    w.svc.domestic = domestic.DomesticPolicy(enabled=False, lines=POLICY.lines)  # switched off
    assert w.svc.visible(w.get(s.id))  # money may have moved: never hidden
    w.ss._results[next(iter(w.ss._results))]["polls_left"] = 0
    clock.advance(minutes=1)
    w.svc.tick(SHOP)
    assert w.get(s.id).label is not None and len(w.ss.purchases) == 1


def test_the_app_keeps_shopify_shipping_for_read_back_once_it_was_used(tmp_path):
    from shipping.app import build_service

    db = str(tmp_path / "s.db")

    def settings(labels: str = "off") -> Settings:
        return Settings(shopify_backend="fake", provider="fake", db_path=db, domestic_labels=labels)

    assert build_service(settings()).domestic_provider is None  # never used: as before
    on = build_service(settings("shopify"))
    on.store.add_label_purchase(settings().shop_domain, "ss:op_x", {"ref": "ss:op_x"})
    again = build_service(settings())  # switched off afterwards
    assert isinstance(again.domestic_provider, ShopifyShipping)
    assert not again.domestic.enabled


# --------------------------------------------------------------------------- the service choice


def test_a_persons_choice_ends_when_the_delivery_method_changes(w):
    w.shopify.add(fo(3010, [tee_line()], country="GB", shipping_line=None))
    w.svc.sync(SHOP)
    s = next(x for x in w.store.shipments(SHOP) if x.order_name == "CROOKS-3010")
    s = w.svc.answer(SHOP, s.id, "package", "first_package", {"name": "Mailer", "length_cm": 38,
                     "width_cm": 28, "height_cm": 8, "empty_weight_g": 40}, "george")  # fmt: skip
    s = w.svc.answer(SHOP, s.id, "domestic_service", "service", {"service": TRACKED_48}, "george")
    assert s.status == S.ready and s.domestic_service == TRACKED_48
    basis = w.svc.preview(SHOP, s.id)["basis"]
    w.shopify.fos[s.fulfillment_order_id].shipping_line = "Tracked 24"  # an order edit
    with pytest.raises(ActionError):
        w.svc.buy(SHOP, s.id, basis, "george", "k1")
    after = w.get(s.id)
    assert after.domestic_service == TRACKED_24 and w.ss.purchases == []


def test_uk_collection_and_local_delivery_orders_are_left_to_shopify(w):
    for n, method in ((3011, "PICK_UP"), (3012, "LOCAL"), (3013, "SHIPPING")):
        snap = fo(n, [tee_line()], country="GB")
        snap.delivery_method = method
        w.shopify.add(snap)
    w.svc.sync(SHOP)
    assert sorted(x.order_name for x in w.store.shipments(SHOP)) == ["CROOKS-3013"]


def test_entries_run_together_with_a_comma_are_refused():
    with pytest.raises(ValueError):
        domestic.parse_lines("Tracked 24=24, Tracked 48=48")


# --------------------------------------------------------------------------- no made-up price


def test_no_made_up_amount_in_history_or_alerts(w):
    s = w.ready()
    w.buy(s)
    after = w.get(s.id)
    said = json.dumps([e.detail for e in after.timeline]) + " ".join(after.alerts)
    assert "£0.00" not in said and "the price Shopify Shipping set" in said


def test_an_unpriced_flag_on_another_providers_quote_never_skips_the_amount_check(w):
    w.ready()  # the shop's package, entered once
    w.shopify.add(fo(4001, [tee_line()], country="DE"))
    w.svc.sync(SHOP)
    s = next(x for x in w.store.shipments(SHOP) if x.order_name == "CROOKS-4001")
    s = w.svc.answer(SHOP, s.id, "customs", "gid://shopify/Product/tee",
                     {"hs_code": "6109.10", "description": "Cotton T-shirt"}, "g")  # fmt: skip
    s = w.svc.answer(SHOP, s.id, "origin", "gid://shopify/Product/tee", {"country": "PT"}, "g")
    assert s.quote is not None
    stray = s.quote.model_copy(update={"price_known": False, "amount": Money(minor=0)})
    s.quote, s.rates = stray, [stray]
    w.store.save(s)
    w.intl.price_minor = 0  # verify agrees with the stray zero, so only the ledger can stop it
    basis = w.svc.purchases.preview(SHOP, s.id)["basis"]
    w.svc.purchases.buy(SHOP, s.id, basis, "george", "stray")
    assert w.intl.charges == []  # Parcel2Go's order wasn't paid on a zero it never quoted


def test_an_order_shopify_no_longer_shows_is_never_taken_as_not_bought(w, clock):
    s = w.ready()
    w.ss.lose_reply, w.ss.outcome = True, "PURCHASE_FAILED"
    w.buy(s)
    del w.shopify.fos[s.fulfillment_order_id]  # can't be read back at all
    for _ in range(4):
        clock.advance(minutes=6)
        w.svc.purchases.reconcile_all()
    assert w.get(s.id).status == S.reconciliation_required  # still unknown, still checked
    # Only the one look made before the order vanished counts as "nothing found".
    assert w.op(s.id).state == OpState.pay_unknown and len(w.op(s.id).unpaid_reads) == 1


def test_any_hold_code_among_several_holds_the_order(w):
    s = w.ready()
    w.ss.user_errors = [
        {"code": "RATES_NOT_FOUND", "message": "x"},
        {"code": "JOB_NOT_ENQUEUED", "message": "Another label"},
    ]
    w.buy(s)
    assert w.get(s.id).status == S.needs_attention and w.get(s.id).label_check


def test_another_purchase_running_found_on_read_back_also_holds_the_order(w, clock):
    s = w.ready()
    w.ss.pending_polls, w.ss.outcome = 50, "PURCHASE_FAILED"
    w.ss.fail_errors = [{"code": "JOB_NOT_ENQUEUED", "message": "Another label"}]
    w.buy(s)
    w.ss._results[next(iter(w.ss._results))]["polls_left"] = 0
    clock.advance(seconds=30)
    w.svc.purchases.reconcile_all()
    after = w.get(s.id)
    assert after.status == S.needs_attention and after.label_check
    assert "weren't charged" not in (after.last_error or "")


def test_a_held_order_stays_listed_when_uk_labels_are_switched_off(w, clock):
    s = w.ready()
    w.ss.lose_reply, w.ss.outcome = True, "PURCHASE_FAILED"
    w.buy(s)
    for _ in range(3):
        clock.advance(minutes=6)
        w.svc.purchases.reconcile_all()
    w.svc.domestic = domestic.DomesticPolicy(enabled=False)
    assert w.get(s.id).label_check and w.svc.visible(w.get(s.id))


def test_a_held_order_closed_in_shopify_says_a_label_may_exist(w, clock):
    s = w.ready()
    w.ss.lose_reply, w.ss.outcome = True, "PURCHASE_FAILED"
    w.buy(s)
    for _ in range(3):
        clock.advance(minutes=6)
        w.svc.purchases.reconcile_all()
    w.shopify.fos[s.fulfillment_order_id].status = "CLOSED"  # Shopify finished it late
    w.svc.sync(SHOP)
    after = w.get(s.id)
    assert after.status == S.cancelled
    assert any("A label may have been bought" in a for a in after.alerts)


def test_the_send_claim_is_atomic_against_a_sweep_between_read_and_send(w, clock):
    """The sweep settles the purchase as never sent after the buy's thread read the row as
    "prepared" but before it claimed it: the claim fails and nothing is sent."""
    s = w.ready()
    real_row, swept = w.uk._row, []

    def row_then_sweep(ref):
        row = real_row(ref)
        if row.get("state") == "prepared" and not swept:
            swept.append(ref)
            clock.advance(minutes=6)
            w.svc.purchases.reconcile_all()  # reads it back: never sent, settled as unsent
        return row

    w.uk._row = row_then_sweep  # type: ignore[method-assign]
    w.buy(s)
    assert swept and w.ss.purchases == [] and w.get(s.id).label is None


def test_a_choice_that_ended_never_comes_back_under_the_persons_name(w):
    w.ready()  # the shop's package, entered once
    w.shopify.add(fo(3015, [tee_line()], country="GB", shipping_line=None))
    w.svc.sync(SHOP)
    s = next(x for x in w.store.shipments(SHOP) if x.order_name == "CROOKS-3015")
    w.svc.answer(SHOP, s.id, "domestic_service", "service", {"service": TRACKED_48}, "george")
    snap = w.shopify.fos[s.fulfillment_order_id]
    snap.shipping_line = "Tracked 24"
    w.svc.prepare(SHOP, s.id)
    snap.shipping_line = None  # edited back
    after = w.svc.prepare(SHOP, s.id)
    assert after.domestic_service is None and after.domestic_service_by is None
    assert [q.kind for q in after.questions] == ["domestic_service"]


def test_never_sent_is_worded_as_never_sent(w):
    s = w.ready()
    order = w.uk.create_order(s, s.quote, "op_unsent")  # type: ignore[arg-type]
    first, again = w.uk.read_order(order.ref), w.uk.read_order(order.ref)
    assert first.failed and again.failed and "never sent to Shopify" in again.note
