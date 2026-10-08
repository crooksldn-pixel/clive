"""V1 release review: each test is a reproduced failure that must stay fixed."""

import json
import logging
from datetime import datetime

import httpx
import pytest

from shipping import shopify as sh
from shipping import views
from shipping.fake_shopify import fo, tee_line
from shipping.models import OpState
from shipping.models import ShipmentStatus as S
from shipping.physical_printing import PhysicalPrinting, PrintError
from shipping.purchase import ActionError

from .conftest import SHOP
from .test_operations import purchased, ready, sender  # noqa: F401  (fixture)
from .test_printing import shopify, svc  # noqa: F401  (fixtures)


def test_an_order_with_a_label_is_never_offered_for_a_second_one_unasked(
    svc,  # noqa: F811
    shopify,  # noqa: F811
    provider,
    monkeypatch,
):
    (s,) = ready(svc, shopify, 1)
    real = provider.documents

    def no_tracking_yet(ref):  # e.g. Easyship: the number comes later, Shopify not yet fulfilled
        d = real(ref)
        d.tracking_number = None
        return d

    monkeypatch.setattr(provider, "documents", no_tracking_yet)
    svc.buy(SHOP, s.id, svc.preview(SHOP, s.id)["basis"], "staff", "k1")
    assert svc.store.get(SHOP, s.id).status == S.label_purchased
    # The merchant moves the fulfilment order: Shopify closes it and opens another.
    old = shopify.fos[s.fulfillment_order_id]
    old.status = "CLOSED"
    new = fo(9999, [tee_line()])
    new.order_id, new.order_name = old.order_id, old.order_name
    shopify.add(new)
    svc.sync(SHOP)
    other = next(
        x for x in svc.store.shipments(SHOP) if x.order_id == old.order_id and x.id != s.id
    )
    assert other.status == S.needs_attention
    assert [q.kind for q in other.questions][:1] == ["second_label"]
    assert views.status_of(other)["label"] == "Already has a label"
    with pytest.raises(ActionError):
        svc.preview(SHOP, other.id)  # not offered: nothing to buy
    assert len(provider.charges) == 1
    # A person who knows it is really a second parcel can say so; then it is priced as usual.
    with pytest.raises(ActionError):
        svc.answer(SHOP, other.id, "second_label", "order", {}, "Sam")
    svc.answer(SHOP, other.id, "second_label", "order", {"confirm": True}, "Sam")
    other = svc.store.get(SHOP, other.id)
    assert other.status == S.ready and other.second_label_confirmed_by == "Sam"
    assert any(e.type == "second_label_confirmed" for e in other.timeline)


def test_unpaid_after_a_paid_reply_on_a_fulfilled_label_alerts_once_and_stops(
    svc,  # noqa: F811
    shopify,  # noqa: F811
    provider,
    clock,
    caplog,
):
    (s,) = ready(svc, shopify, 1)
    svc.buy(SHOP, s.id, svc.preview(SHOP, s.id)["basis"], "staff", "k1")
    assert svc.store.get(SHOP, s.id).status == S.fulfilled
    assert svc.store.op_by_key(SHOP, "k1").state == OpState.paid  # paperless still to confirm
    for o in provider.orders.values():
        o.paid = False  # the provider contradicts its own 2xx
    caplog.set_level(logging.ERROR)
    for _ in range(5):
        clock.advance(minutes=3)
        svc.purchases.reconcile_all()
    op = svc.store.op_by_key(SHOP, "k1")
    s = svc.store.get(SHOP, s.id)
    assert op.state == OpState.abandoned and len(op.unpaid_reads) == 2  # stopped
    assert s.status == S.fulfilled and s.label is not None
    assert sum("isn't paid" in a for a in s.alerts) == 1
    assert not any(r.exc_info for r in caplog.records)  # no IllegalTransition every sweep
    assert len(provider.charges) == 1  # never paid again


def test_first_print_never_prints_again_after_a_reprint_printed(svc, shopify, sender):  # noqa: F811
    (s,) = purchased(svc, shopify, 1)
    pp = PhysicalPrinting(svc.store, sender, 75883753)
    a = pp.print_label(SHOP, s.id, "staff", "key-A")
    sender.get_job_states.return_value = [
        dict(state="error", at="2026-10-07T15:25:31Z", message="paper out")
    ]
    pp.status(SHOP, a["id"])
    b = pp.print_label(SHOP, s.id, "staff", "key-B", reprint=True)
    sender.get_job_states.return_value = [dict(state="done", at="2026-10-07T15:26:31Z")]
    pp.status(SHOP, b["id"])
    summary = pp.summary(SHOP, s.id)
    assert summary is not None and summary["first_print_available"] is False
    with pytest.raises(PrintError) as refused:  # a stale tab, or CLIVE's "print"
        pp.print_label(SHOP, s.id, "staff", "key-C")
    assert refused.value.status == 409 and sender.print_pdf.call_count == 2
    assert pp.print_label(SHOP, s.id, "staff", "key-A")["id"] == a["id"]  # replays still work


def test_a_failed_first_print_still_frees_the_next_first_print(svc, shopify, sender):  # noqa: F811
    (s,) = purchased(svc, shopify, 1)
    pp = PhysicalPrinting(svc.store, sender, 75883753)
    a = pp.print_label(SHOP, s.id, "staff", "key-A")
    sender.get_job_states.return_value = [dict(state="expired", at="2026-10-07T15:25:31Z")]
    pp.status(SHOP, a["id"])
    b = pp.print_label(SHOP, s.id, "staff", "key-B")
    c = pp.print_label(SHOP, s.id, "staff", "key-C")  # a second click: the same print
    assert b["id"] == c["id"] and sender.print_pdf.call_count == 2


def test_a_shopify_mutation_is_not_sent_again_after_a_5xx(monkeypatch):
    monkeypatch.setattr(sh.time, "sleep", lambda s: None)
    posts: list[dict] = []

    def handler(req):
        if req.url.path.endswith("/access_token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3600})
        body = json.loads(req.content)
        posts.append(body)
        return httpx.Response(502)  # the reply is lost: Shopify may have done it

    g = sh.GraphQLShopify(
        "x.myshopify.com", "id", "secret", http=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(sh.ShopifyError, match="may have been done"):
        g.create_fulfillment(
            "gid://shopify/FulfillmentOrder/1", [("li", 1)], "DPD", "H1", None, True
        )
    assert len(posts) == 1
    posts.clear()
    with pytest.raises(sh.ShopifyError):  # a read is safe to repeat
        g.fulfillment_order("gid://shopify/FulfillmentOrder/1")
    assert len(posts) == 4


def test_a_label_bought_before_payment_was_kept_is_not_shown_as_changed(svc, shopify):  # noqa: F811
    (s,) = purchased(svc, shopify, 1)
    s.payment_status = None
    view = views.payment_view(s)
    assert view["tone"] == "neutral" and "changed" not in view["note"]


def test_order_times_with_and_without_a_zone_sort_together(svc, shopify):  # noqa: F811
    a, b = ready(svc, shopify, 2)
    a.order_created_at = "2026-10-08T09:00:00"  # no zone
    b.order_created_at = "2026-10-08T10:00:00Z"
    b.created_at = datetime(2026, 10, 8, 8, 0)  # naive, as an old record might be
    assert sorted([a, b], key=views.placed_at, reverse=True)[0] is b
