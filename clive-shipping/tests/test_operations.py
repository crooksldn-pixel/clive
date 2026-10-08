"""Daily fulfilment operations preserve individual purchase and print boundaries."""

from datetime import timedelta
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from shipping.app import create_app
from shipping.fake_shopify import fo, tee_line
from shipping.models import DocumentKind, ShipmentStatus
from shipping.operations import Operations
from shipping.physical_printing import PhysicalPrinting
from shipping.print_provider import PrintProviderError
from shipping.purchase import ActionError
from shipping.settings import Settings
from shipping.store import Store, now

from . import test_printing as printing
from .conftest import SHOP
from .test_label_selection import bundle
from .test_stage2 import answer_all_first_time

svc = printing.svc
shopify = printing.shopify


@pytest.fixture
def sender():
    p = Mock()
    p.print_pdf.side_effect = range(1000, 2000)
    p.get_job_status.return_value = "done"
    p.get_job_states.return_value = [dict(state="done", at="2026-10-07T15:25:31Z", message="")]
    return p


@pytest.fixture
def ops(svc, sender):
    return Operations(svc, PhysicalPrinting(svc.store, sender, 75883753))


def ready(svc, shopify, count=10):
    for n in range(3000, 3000 + count):
        shopify.add(fo(n, [tee_line()]))
    svc.sync(SHOP)
    first = svc.store.shipments(SHOP)[0]
    answer_all_first_time(svc, first)
    return sorted(svc.store.shipments(SHOP), key=lambda s: s.order_name)


def purchased(svc, shopify, count=5):
    rows = ready(svc, shopify, count)
    for s in rows:
        pv = svc.preview(SHOP, s.id)
        s = svc.buy(SHOP, s.id, pv["basis"], "staff", "purchase-" + s.id)["shipment"]
        doc = s.label.document(DocumentKind.shipping_label)
        doc.artifact_id = svc.store.put_artifact(
            SHOP, s.id, "shipping_label", "application/pdf", bundle(("LABEL " + s.order_name,))
        )
        svc.store.save(s)
    return [svc.store.get(SHOP, s.id) for s in rows]


def batch(ops, rows, kind="buy", key="batch-request"):
    b = ops.preview(SHOP, kind, [s.id for s in rows], "staff", key)
    ops.confirm(SHOP, b["id"], "staff")
    ops.run(SHOP, b["id"])
    return ops.get(SHOP, b["id"])


def test_ten_safe_children_total_and_batch_replay(svc, shopify, ops, provider):
    rows = ready(svc, shopify)
    b = ops.preview(SHOP, "buy", [s.id for s in rows], "staff", "review-key")
    assert b["total_minor"] == 10 * provider.price_minor
    assert not provider.charges and all(c["basis"] for c in b["children"])
    assert len({c["key"] for c in b["children"]}) == 10
    ops.confirm(SHOP, b["id"], "staff")
    ops.run(SHOP, b["id"])
    ops.confirm(SHOP, b["id"], "staff")
    ops.run(SHOP, b["id"])
    assert len(provider.charges) == 10
    assert all(c["state"] == "purchased" for c in ops.get(SHOP, b["id"])["children"])
    assert all(len(svc.store.ops_for(SHOP, s.id)) == 1 for s in rows)
    assert ops.preview(SHOP, "buy", [s.id for s in rows], "staff", "review-key")["id"] == b["id"]
    with pytest.raises(ActionError):
        ops.get("another-shop", b["id"])


def test_one_stale_among_ten_continues(svc, shopify, ops, provider):
    rows = ready(svc, shopify)
    b = ops.preview(SHOP, "buy", [s.id for s in rows], "staff", "review-key")
    shopify.fos[rows[0].fulfillment_order_id].destination.city = "Changed city"
    ops.confirm(SHOP, b["id"], "staff")
    ops.run(SHOP, b["id"])
    out = ops.get(SHOP, b["id"])
    assert out["children"][0]["state"] == "failed"
    assert "changed" in out["children"][0]["message"]
    assert sum(c["state"] == "purchased" for c in out["children"]) == 9
    assert len(provider.charges) == 9


def test_uncertain_purchase_not_retried(svc, shopify, ops, provider, monkeypatch):
    rows = ready(svc, shopify, 3)
    original = provider.pay

    def lose_first(ref):
        if not provider.charges:
            provider.lose_pay_reply = True
            provider.read_down = 1
        return original(ref)

    monkeypatch.setattr(provider, "pay", lose_first)
    b = batch(ops, rows)
    assert b["children"][0]["state"] == "uncertain"
    assert sum(c["state"] == "purchased" for c in b["children"]) == 2
    ops.run(SHOP, b["id"])
    ops.resume(SHOP)
    assert provider.calls.count("pay") == 3
    svc.tick(SHOP)
    ops.resume(SHOP)
    assert provider.calls.count("pay") == 3
    assert ops.get(SHOP, b["id"])["children"][0]["state"] == "purchased"


@pytest.mark.parametrize("fault", ["hold", "cancel", "unauthorised", "price"])
def test_existing_purchase_safeguards_remain(svc, shopify, ops, provider, fault):
    rows = ready(svc, shopify, 1)
    b = ops.preview(SHOP, "buy", [rows[0].id], "staff", "review-key")
    if fault == "hold":
        shopify.fos[rows[0].fulfillment_order_id].status = "ON_HOLD"
    if fault == "cancel":
        shopify.fos[rows[0].fulfillment_order_id].order_cancelled = True
    if fault == "unauthorised":
        svc.may_buy = lambda s: False
    if fault == "price":
        provider.price_minor += 100
    ops.confirm(SHOP, b["id"], "staff")
    ops.run(SHOP, b["id"])
    assert not provider.charges
    assert ops.get(SHOP, b["id"])["children"][0]["state"] == "failed"


def test_purchased_excluded_from_buy_preflight(svc, shopify, ops):
    rows = purchased(svc, shopify, 1)
    b = ops.preview(SHOP, "buy", [rows[0].id], "staff", "review-key")
    assert b["total_minor"] == 0 and b["children"][0]["state"] == "excluded"


def test_restart_unclaimed_resume_and_interrupted_child_no_retry(svc, shopify, ops, provider):
    rows = ready(svc, shopify, 2)
    b = ops.preview(SHOP, "buy", [s.id for s in rows], "staff", "review-key")
    ops.confirm(SHOP, b["id"], "staff")
    b = ops.get(SHOP, b["id"])
    b["children"][0].update(state="running", started_at=(now() - timedelta(minutes=16)).isoformat())
    with svc.store.atomic():
        svc.store.save_batch(SHOP, b)
    path = svc.store._db.execute("PRAGMA database_list").fetchone()[2]
    reopened = Store(path)
    previous = svc.store
    svc.store = reopened
    try:
        recovered = Operations(svc, ops.physical)
        recovered.resume(SHOP)
        result = recovered.get(SHOP, b["id"])
        assert result["children"][0]["state"] == "uncertain"
        assert result["children"][1]["state"] == "purchased"
        assert len(provider.charges) == 1
    finally:
        svc.store = previous


@pytest.mark.parametrize(
    "state,label",
    [("accepted", "Printing…"), ("failed", "Print failed"), ("unknown", "Print uncertain")],
)
def test_durable_print_states_and_reopen(svc, shopify, ops, sender, state, label):
    s = purchased(svc, shopify, 1)[0]
    assert ops.physical.summary(SHOP, s.id)["label"] == "Not printed"
    if state != "accepted":
        sender.print_pdf.side_effect = PrintProviderError("Test", uncertain=state == "unknown")
    intent = ops.physical.print_label(SHOP, s.id, "staff", "first-request")
    assert ops.physical.summary(SHOP, s.id)["label"] == label
    path = svc.store._db.execute("PRAGMA database_list").fetchone()[2]
    reopened = PhysicalPrinting(Store(path), sender, 75883753)
    summary = reopened.summary(SHOP, s.id)
    assert summary is not None and summary["label"] == label
    assert reopened.print_label(SHOP, s.id, "staff", "first-request")["id"] == intent["id"]
    sender.print_pdf.side_effect = range(1000, 2000)  # the printer is back
    again = reopened.print_label(SHOP, s.id, "staff", "other-request")
    if state == "failed":  # definitely not printed: a new press of Print tries again, once
        assert again["id"] != intent["id"] and sender.print_pdf.call_count == 2
        assert reopened.print_label(SHOP, s.id, "staff", "third-request")["id"] == again["id"]
    else:  # printing, or it may have printed: never sent again by a first print
        assert again["id"] == intent["id"] and sender.print_pdf.call_count == 1


def test_two_explicit_reprints_count_and_printnode_done_is_printed(svc, shopify, ops):
    s = purchased(svc, shopify, 1)[0]
    first = ops.physical.print_label(SHOP, s.id, "staff", "first-request")
    assert ops.physical.summary(SHOP, s.id)["state"] == "printing"  # accepted is not printed
    ops.physical.print_label(SHOP, s.id, "staff", "reprint-one", True)
    ops.physical.print_label(SHOP, s.id, "staff", "reprint-two", True)
    ops.physical.status(SHOP, first["id"])
    summary = ops.physical.summary(SHOP, s.id)
    assert summary["reprint_count"] == 2 and summary["state"] == "printed"
    assert len(summary["history"]) == 3 and summary["last_sent"]
    assert not summary["first_print_available"]


def test_bulk_print_independent_intents_and_no_postage(
    svc, shopify, ops, provider, sender, monkeypatch
):
    rows = purchased(svc, shopify)
    printing.trap(provider, monkeypatch)
    # The first document is Easyship's combined label/CN23; the remainder are dedicated P2G.
    first = rows[0]
    first.label.provider = "Easyship"
    first.label.carrier = "Royal Mail"
    first.label.service_name = "Royal Mail Domestic Tracked 48 - Small Parcel"
    original = bundle()
    doc = first.label.document(DocumentKind.shipping_label)
    doc.artifact_id = svc.store.put_artifact(
        SHOP, first.id, "shipping_label", "application/pdf", original
    )
    doc.pages = 2
    svc.store.save(first)
    b = batch(ops, rows, "print")
    assert all(c["state"] == "sent" for c in b["children"])
    assert sender.print_pdf.call_count == 5
    from io import BytesIO

    from pypdf import PdfReader

    # The label and its CN23 customs form, both, exactly as Easyship made them.
    assert sender.print_pdf.call_args_list[0].args[0] == original
    assert len(PdfReader(BytesIO(original)).pages) == 2
    assert svc.store.get_artifact(SHOP, doc.artifact_id)[2] == original
    for row, call in zip(rows[1:], sender.print_pdf.call_args_list[1:], strict=True):
        artifact = row.label.document(DocumentKind.shipping_label).artifact_id
        assert call.args[0] == svc.store.get_artifact(SHOP, artifact)[2]
    assert [c["shipment_id"] for c in b["children"]] == [s.id for s in rows]


def test_bulk_print_skips_three_sent_and_unknown(svc, shopify, ops, sender):
    rows = purchased(svc, shopify)
    for s in rows[:3]:
        ops.physical.print_label(SHOP, s.id, "staff", "first-request")
    b = batch(ops, rows, "print")
    assert sum(c["state"] == "sent" for c in b["children"]) == 2
    assert sum(c["state"] == "excluded" for c in b["children"]) == 3
    assert sender.print_pdf.call_count == 5
    # A lost submission is permanently protected from bulk first-print retries.
    s = purchased  # keep the assertion focused on a separate fresh review of the same labels.
    b2 = batch(ops, rows, "print", "another-review")
    assert all(c["state"] == "excluded" for c in b2["children"])
    assert sender.print_pdf.call_count == 5


def test_unknown_print_is_not_bulk_retryable(svc, shopify, ops, sender):
    rows = purchased(svc, shopify, 1)
    sender.print_pdf.side_effect = PrintProviderError("Lost response", uncertain=True)
    b = batch(ops, rows, "print")
    assert b["children"][0]["state"] == "uncertain"
    batch(ops, rows, "print", "new-review-key")
    assert sender.print_pdf.call_count == 1


@pytest.mark.parametrize("hs", ["abc12345", "61.10.20", "12345", "12345678901", "１２３４５６７８"])
def test_invalid_inline_hs_refused_without_shopify_write(svc, shopify, hs):
    rows = ready(svc, shopify, 1)
    before = list(shopify.writes)
    with pytest.raises(ActionError):
        svc.edit_customs(
            SHOP, rows[0].id, rows[0].lines[0].product_id, hs, "Cotton tee", "CN", "staff"
        )
    assert shopify.writes == before


def test_inline_hs_canonical_future_orders_and_no_purchase(svc, shopify, provider):
    s = ready(svc, shopify, 1)[0]
    s = svc.edit_customs(SHOP, s.id, s.lines[0].product_id, "01012100", "Cotton tee", "CN", "staff")
    assert s.lines[0].hs_code == "01012100" and s.status == ShipmentStatus.ready
    assert shopify.items[s.lines[0].inventory_item_id].hs_code == "01012100"
    assert svc.store.fact(SHOP, "product", s.lines[0].product_id, "hs_code") == "01012100"
    shopify.add(fo(4000, [tee_line()]))
    svc.sync(SHOP)
    other = next(x for x in svc.store.shipments(SHOP) if x.order_name == "CROOKS-4000")
    assert other.lines[0].hs_code == "01012100" and other.lines[0].origin_country == "CN"
    assert not provider.charges and "pay" not in provider.calls


def test_purchased_customs_history_locked(svc, shopify):
    s = purchased(svc, shopify, 1)[0]
    before = s.model_dump_json()
    writes = list(shopify.writes)
    with pytest.raises(ActionError):
        svc.edit_customs(SHOP, s.id, s.lines[0].product_id, "01012100", "Cotton tee", "CN", "staff")
    assert svc.store.get(SHOP, s.id).model_dump_json() == before and shopify.writes == writes


def test_operations_auth_and_durable_api_progress(svc, shopify, ops, monkeypatch):
    rows = ready(svc, shopify, 1)
    cfg = Settings(shop_domain=SHOP, provider="fake", dev_skip_admin_auth=False, tick_interval_s=0)
    with TestClient(create_app(cfg, svc)) as c:
        assert (
            c.post(
                "/admin/api/batches/preview",
                json=dict(kind="buy", shipment_ids=[rows[0].id], idempotency_key="request-key"),
            ).status_code
            == 401
        )
        assert c.get("/admin/api/batches/missing").status_code == 401
        assert (
            c.post(
                f"/admin/api/shipments/{rows[0].id}/customs",
                json=dict(
                    subject=rows[0].lines[0].product_id,
                    hs_code="01012100",
                    origin="CN",
                    description="Cotton tee",
                ),
            ).status_code
            == 401
        )
    cfg.dev_skip_admin_auth = True
    with TestClient(create_app(cfg, svc)) as c:
        b = c.post(
            "/admin/api/batches/preview",
            json=dict(kind="buy", shipment_ids=[rows[0].id], idempotency_key="request-key"),
        ).json()
        assert (
            c.post(
                "/admin/api/batches/" + b["id"] + "/confirm", json=dict(confirm=False)
            ).status_code
            == 422
        )
        assert (
            c.post(
                "/admin/api/batches/" + b["id"] + "/confirm", json=dict(confirm=True)
            ).status_code
            == 200
        )
        result = c.get("/admin/api/batches/" + b["id"]).json()
        assert result["state"] == "complete" and result["children"][0]["state"] == "purchased"
        assert (
            c.get("/admin/api/shipments/" + rows[0].id).json()["print_status"]["label"]
            == "Not printed"
        )
        inbox = c.get("/admin/api/inbox?stage=ready").json()
        assert inbox["batches"][0]["id"] == b["id"]


def test_mixed_providers_stay_shipment_specific(svc, shopify, ops, provider):
    from shipping.providers.multi import Providers

    from .fake_easyship import FakeEasyship, adapter, service

    rows = ready(svc, shopify, 2)
    cfg = svc.store.config(SHOP)
    cfg.origin.phone = "01753000000"
    cfg.origin.email = "store@example.com"
    server = FakeEasyship()
    server.services = [service("rm48", "Royal Mail", "Tracked 48", 3.01)]
    es = adapter(server, cfg, svc.clock)
    original = es.quotes
    es.quotes = lambda shipment: original(shipment) if shipment.id == rows[0].id else []
    providers = Providers([provider, es])
    svc.provider = providers
    svc.purchases.provider = providers
    for s in rows:
        svc.prepare(SHOP, s.id)
    out = batch(ops, rows)
    assert [c["provider"] for c in out["children"]] == ["Easyship", "Parcel2Go"]
    assert all(c["state"] == "purchased" for c in out["children"])
    assert len(server.charges) == 1 and len(provider.charges) == 1


def test_duplicate_workers_claim_each_purchase_once(svc, shopify, ops, provider):
    from concurrent.futures import ThreadPoolExecutor

    rows = ready(svc, shopify, 3)
    b = ops.preview(SHOP, "buy", [s.id for s in rows], "staff", "review-key")
    ops.confirm(SHOP, b["id"], "staff")
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _: ops.run(SHOP, b["id"]), range(2)))
    assert len(provider.charges) == 3
    assert all(c["state"] == "purchased" for c in ops.get(SHOP, b["id"])["children"])


def test_bulk_print_never_calls_real_postage_adapters(svc, shopify, ops, monkeypatch):
    from shipping.providers.easyship import Easyship
    from shipping.providers.parcel2go import Parcel2Go

    rows = purchased(svc, shopify, 1)
    forbidden = Mock(side_effect=AssertionError("Postage transport must not be called"))
    monkeypatch.setattr(Easyship, "_call", forbidden)
    monkeypatch.setattr(Parcel2Go, "_call", forbidden)
    assert batch(ops, rows, "print")["children"][0]["state"] == "sent"
    forbidden.assert_not_called()


def test_expired_review_cannot_buy(svc, shopify, ops, provider):
    rows = ready(svc, shopify, 1)
    b = ops.preview(SHOP, "buy", [rows[0].id], "staff", "review-key")
    b["expires_at"] = (now() - timedelta(seconds=1)).isoformat()
    with svc.store.atomic():
        svc.store.save_batch(SHOP, b)
    with pytest.raises(ActionError):
        ops.confirm(SHOP, b["id"], "staff")
    assert not provider.charges


def test_inline_hs_clears_missing_blocker(svc, shopify, provider):
    s = ready(svc, shopify, 1)[0]
    shopify.items[s.lines[0].inventory_item_id].hs_code = None
    svc.store._db.execute("DELETE FROM facts WHERE fact='hs_code'")
    s = svc.prepare(SHOP, s.id)
    assert any(q.kind == "customs" for q in s.questions)
    s = svc.edit_customs(
        SHOP, s.id, s.lines[0].product_id, "61102091", "Cotton hoodie", "CN", "staff"
    )
    assert s.status == ShipmentStatus.ready and not s.questions and s.quote
    assert not provider.charges


def test_ui_selection_review_progress_filters_and_customs(svc, shopify, ops, sender, tmp_path):
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed for the UI interaction check")
    rows = ready(svc, shopify, 2)
    cfg = Settings(shop_domain=SHOP, provider="fake", dev_skip_admin_auth=True, tick_interval_s=0)
    with TestClient(create_app(cfg, svc)) as c:
        inbox = c.get("/admin/api/inbox?stage=ready").json()
        detail = c.get("/admin/api/shipments/" + rows[0].id).json()
        ids = [r["id"] for r in inbox["rows"]]
        review = ops.preview(SHOP, "buy", ids, "staff", "ui-review-key")
        queued = ops.confirm(SHOP, review["id"], "staff")
        ops.run(SHOP, review["id"])
        complete = ops.get(SHOP, review["id"])
        for row in rows:
            row = svc.store.get(SHOP, row.id)
            doc = row.label.document(DocumentKind.shipping_label)
            doc.artifact_id = svc.store.put_artifact(
                SHOP, row.id, "shipping_label", "application/pdf", bundle(("LABEL",))
            )
            svc.store.save(row)
        first = ops.physical.print_label(SHOP, rows[0].id, "staff", "first-print")
        ops.physical.status(SHOP, first["id"])  # PrintNode: done
        sent = c.get("/admin/api/shipments/" + rows[0].id).json()
        bought_inbox = c.get("/admin/api/inbox?stage=bought").json()
        printed_inbox = c.get("/admin/api/inbox?stage=printed").json()
    # This app was built with PrintNode off; the UI check needs it on (the server's own rule
    # for first prints is tested in test_lifecycle).
    bought_inbox["printing"] = True
    bought_inbox["print_method"] = sent["print_method"] = "printnode"
    for r in bought_inbox["rows"]:
        r["can_first_print"] = r["can_select"] = r["print_status"]["first_print_available"]
    data = tmp_path / "operations.json"
    data.write_text(
        json.dumps(
            dict(
                inbox=inbox,
                detail=detail,
                review=review,
                queued=queued,
                complete=complete,
                sent=sent,
                bought_inbox=bought_inbox,
                printed_inbox=printed_inbox,
            )
        ),
        encoding="utf-8",
    )
    runner = Path(__file__).with_name("operations_ui.cjs")
    html = Path(__file__).parents[1] / "shipping/static/admin.html"
    result = subprocess.run(
        [node, str(runner), str(html), str(data)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
