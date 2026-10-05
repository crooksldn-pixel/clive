# Shipping fulfilment operations

## Merchant workflow

The inbox now shows durable print badges, selection checkboxes, Not printed / Sent to printer / Print problem filters, and links to recent batches. Select ready shipments (up to 100), choose Buy labels, review each provider/service/current price and the total, then confirm. Purchased rows can be selected for a separate reviewed Print labels batch. The review lists their print order, matching the selected rows' visible inbox order. Excluded rows explain why they will not run.

Batch progress has independent per-order outcomes and survives browser reload. Open a recent batch to inspect purchased, sent, failed, skipped and uncertain rows. A failure does not roll back successful rows or retry an uncertain payment or print. There is deliberately no combined Buy & print action.

An unpurchased shipment has inline HS code, origin and customs-description fields. Save uses the existing canonical product-facts and Shopify inventory-item update path, rechecks readiness and refreshes rates. HS codes are 6–10 ASCII digits; leading zeros are preserved, punctuation and padding are rejected. Existing provider-specific length checks remain. Shopify inventory items hold HS code/origin; CLIVE's existing product facts hold the merchant description and confirmed customs facts. Shopify-write problems remain visible through the existing warning mechanism. Purchased customs snapshots cannot be edited.

## Print evidence

Status is derived from stored `print_intents` for the current purchased label artifact, never browser storage:

| Status | Evidence / action |
| --- | --- |
| Not printed | Purchased label with no print attempt. Eligible for first print. |
| Sending | Durable intent being submitted. Do not submit another copy. |
| Sent to printer | PrintNode accepted the job and assigned a job ID. Physical paper emergence is not proven. |
| Print uncertain | Submission outcome lost, or interrupted submission more than five minutes old. No automatic retry. |
| Print failed | Definitive submission failure, or PrintNode error/expiry. Inspect the shipment and intentionally Reprint if appropriate. |

PrintNode's `done` means the client delivered the job to the operating-system queue; it does not prove paper emerged. Even `done` remains **Sent to printer**. See [PrintNode job states](https://www.printnode.com/en/docs/api/curl).

Detail shows last attempt, last accepted send time, submitted reprint count and job ID. Reprint count counts additional accepted submissions, not physical copies proven. A recorded first attempt switches the main action to Reprint, which asks for confirmation. First-print retries reuse the existing intent. Bulk Print excludes every previously attempted label, including failed/uncertain ones; it never silently creates a second attempt. Open PDF stays separate.

Bulk Print runs each existing PhysicalPrinting first-print path separately. Each PDF undergoes the existing selection/validation: supported Easyship label+CN23 bundles select the shipping-label page; Parcel2Go dedicated 4×6 bytes stay unchanged. No PDF concatenation, postage-provider purchase, automatic uncertain-job retry or reprint semantics are introduced.

## Durable batch safety

`fulfilment_batches` stores the batch and child outcomes in the existing SQLite store. Each child has an independent stable purchase key and reviewed basis. Review calls existing preview; execution calls existing buy, retaining fresh Shopify checks, authorisation, hold/cancel guards, price validation, provider ownership, one-payment-attempt limits and reconciliation. Print children use existing stable first-print identities.

Repeated confirmation does not reset children. An atomic durable claim precedes each action, preventing concurrent workers from submitting the same child. Confirmed unclaimed children resume through the existing startup/tick worker. Interrupted running children become uncertain after 15 minutes and are never resubmitted; purchase reconciliation may subsequently confirm their outcome. Reviews expire after 10 minutes, including before each child executes, so stale queued rows fail safely and need a fresh review. Batches contain at most 100 distinct rows and one currency. GET progress/status polling never buys or prints.

The endpoints use the same authenticated, shop-scoped staff dependency as existing individual actions. No credentials are returned or added to repository files.

## Validation

Automated tests use fake postage providers and mocked PrintNode transport. They cover partial success, stale/held/cancelled/unauthorised/changed-price refusal, uncertain results and restart/concurrent-worker safety; durable print status and reprints; canonical customs persistence and historical immutability; independent PDF selection; and actual admin JavaScript selection/review/confirmation/progress/filter/reprint/customs interactions. No live postage or physical jobs are submitted.

Final integrated checks: 429 Shipping tests passed; Ruff lint and formatting passed; inline JavaScript syntax and admin interaction tests passed. Pyright remains at the accepted baseline of 72 errors and one warning, with zero new diagnostic signatures.

## Deployment (separate approval)

No new environment variables are required. Existing provider, buying-authorisation and PrintNode settings remain in place. The additive table/index are created automatically on startup. Back up the live SQLite database before updating; use SQLite backup rather than copying an active WAL database.

On the existing deployment checkout:

```bash
cd /opt/clive
python3 - <<'PY'
import sqlite3
from datetime import datetime
from pathlib import Path
p = Path('clive-shipping/data/shipping.sqlite3')
backup = p.with_name('shipping-before-operations-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '.sqlite3')
with sqlite3.connect(p) as source, sqlite3.connect(backup) as target:
    source.backup(target)
print(backup)
PY
git pull --ff-only origin codex/printnode-shipping
cd crooks-returns
docker compose build shipping
docker compose up -d --no-deps shipping
docker compose exec -T shipping python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8120/health').read().decode())"
```

After deployment, inspect an existing purchased shipment's badge, a non-purchasing batch review and an unpurchased product's customs fields. Physical fulfilment still requires the merchant to verify the printer output. Deployment is not performed by this change.
