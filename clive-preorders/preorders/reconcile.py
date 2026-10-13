"""Reconciliation: webhooks tell us something changed; they are not the record. This compares
Shopify with our database and puts right what is safe to put right, idempotently:

1. Every Shopify order bought on one of our selling plans (since the first offer) is ingested
   again: missed or out-of-order webhooks leave no gap, and counts are rebuilt from those rows.
2. The catalogue (stock, policies) is re-read.
3. Readiness is recomputed for every batch line from what was received.
4. Every offer is converged again (plan membership, inventory policy, storefront metafield).
5. Anything that needs a person is reported, never "fixed" silently: units sold beyond an
   allocation, lines bought without the plan, receipts and emails with unknown outcomes,
   webhooks that keep failing, offers out of step with Shopify.
"""

from __future__ import annotations

import logging
from typing import Any

from preorders.service import PreordersService
from preorders.shopify import ShopifyError
from preorders.store import iso

log = logging.getLogger("preorders.reconcile")


def reconcile(svc: PreordersService, actor: str = "system") -> dict[str, Any]:
    report: dict[str, Any] = {"started_at": iso(svc.clock()), "orders": 0, "errors": []}
    store = svc.store
    try:
        svc.refresh_catalog()
    except ShopifyError as exc:
        report["errors"].append(f"catalogue: {exc}")
    plans = {r["plan_id"] for r in store.all("SELECT plan_id FROM selling_plans")}
    first = store.value("SELECT MIN(created_at) FROM offers WHERE shop = ?", (svc.shop,))
    if plans and first:
        try:
            ids = svc.shopify.orders_with_plans(first[:10], plans)
        except ShopifyError as exc:
            ids = []
            report["errors"].append(f"orders: {exc}")
        known = {r["order_id"] for r in store.all("SELECT DISTINCT order_id FROM preorder_lines")}
        for oid in sorted(set(ids) | known):
            try:
                svc.ingest_order(oid)
                report["orders"] += 1
            except ShopifyError as exc:
                report["errors"].append(f"order {oid}: {exc}")
    for line in store.all("SELECT id FROM batch_lines"):
        svc.recompute_ready(line["id"])
    svc.sync_all()
    report["oversold"] = [
        {
            "batch": b["reference"],
            "variant": ln["variant_title"],
            "product": ln["product_title"],
            "allocation": ln["preorder_allocation"],
            "sold": ln["sold"],
        }
        for b in svc.batches()
        for ln in b["lines"]
        if ln["oversold"]
    ]
    report["unplanned"] = store.all(
        "SELECT order_name, variant_id, quantity, seen_at FROM unplanned_lines WHERE shop = ? AND"
        " resolved_at IS NULL",
        (svc.shop,),
    )
    report["receipts_unknown"] = store.all(
        "SELECT id, batch_line_id, quantity, error FROM receipts WHERE status IN ('UNKNOWN', "
        "'PENDING')"
    )
    report["emails_unknown"] = int(
        store.value("SELECT COUNT(*) FROM communications WHERE status IN ('UNKNOWN', 'PENDING')")
        or 0
    )
    report["webhooks_failing"] = store.all(
        "SELECT event_id, topic, attempts, error FROM webhook_inbox WHERE processed_at IS NULL "
        "AND attempts >= 3"
    )
    report["out_of_step"] = store.all(
        "SELECT id, product_title, sync_error FROM offers WHERE shop = ? AND sync_error IS NOT "
        "NULL",
        (svc.shop,),
    )
    report["finished_at"] = iso(svc.clock())
    report["needs_attention"] = bool(
        report["oversold"]
        or report["unplanned"]
        or report["receipts_unknown"]
        or report["emails_unknown"]
        or report["webhooks_failing"]
        or report["errors"]
    )
    store.event(
        svc.shop,
        "reconciled",
        "",
        {k: (len(v) if isinstance(v, list) else v) for k, v in report.items()},
        actor,
    )
    if report["needs_attention"]:
        log.warning(
            "reconciliation found things to look at: %s",
            {k: len(v) for k, v in report.items() if isinstance(v, list) and v},
        )
    return report


def last_report(svc: PreordersService) -> dict[str, Any] | None:
    return svc.store.one(
        "SELECT at, actor, detail FROM events WHERE shop = ? AND kind = "
        "'reconciled' ORDER BY id DESC LIMIT 1",
        (svc.shop,),
    )
