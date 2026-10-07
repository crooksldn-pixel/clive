# Shipping fulfilment operations

## Merchant workflow

The inbox now shows durable print badges, selection checkboxes, Not printed / Printing… / Printed / Print failed badges, and links to recent batches. Select ready shipments (up to 100), choose Buy labels, review each provider/service/current price and the total, then confirm. Purchased rows can be selected for a separate reviewed Print labels batch. The review lists their print order, matching the selected rows' visible inbox order. Excluded rows explain why they will not run.

Batch progress has independent per-order outcomes and survives browser reload. Open a recent batch to inspect purchased, sent, failed, skipped and uncertain rows. A failure does not roll back successful rows or retry an uncertain payment or print. There is deliberately no combined Buy & print action.

An unpurchased shipment has inline HS code, origin and customs-description fields. Save uses the existing canonical product-facts and Shopify inventory-item update path, rechecks readiness and refreshes rates. HS codes are 6–10 ASCII digits; leading zeros are preserved, punctuation and padding are rejected. Existing provider-specific length checks remain. Shopify inventory items hold HS code/origin; CLIVE's existing product facts hold the merchant description and confirmed customs facts. Shopify-write problems remain visible through the existing warning mechanism. Purchased customs snapshots cannot be edited.

## Print evidence

**How Print works.** Without PrintNode, Print opens the label as a 4×6 PDF in a new tab (the
print view), as Shopify prints labels; bulk Print opens the selected labels as one PDF. Opening
it is recorded as the print: nothing else could know. With PrintNode connected, Print sends the
label to the printer instead and the order says "Printing…" until PrintNode reports the end of
the job. Open PDF stays available either way.

Status comes from stored `print_intents` for the current label file, never browser storage:

| Status | Evidence / action |
| --- | --- |
| Not printed | No print yet. Eligible for first print. |
| Sending to printer | A PrintNode request is being submitted. Do not submit another copy. |
| Printing… | PrintNode accepted the job; its states so far are shown (sent to the computer, queued, printing). Stays under Labels bought. |
| Printed | The print view was opened, or PrintNode reported `done`: the printer's computer finished the job. A jam after that can't be seen by PrintNode. Moves to Printed. |
| Print failed | Refused before PrintNode took it, or PrintNode reported `error`, `expired`, `deleted` or `disappeared`, with PrintNode's own message. Nothing was printed: Print label works again (once per press; a retried request replays). |
| Print uncertain | Submission outcome lost, or interrupted for more than five minutes. No automatic retry; check the printer, then Reprint on purpose. |
| Not confirmed by printer | PrintNode took it but never reported an end within six hours. Check the printer; Reprint on purpose. |

PrintNode is asked about every unfinished job from the last two days each minute (GET only, never
another print), and the order page asks every two seconds for a minute after Print. Each end of
a job is written to the order's history ("Printer finished printing the label" / "Label didn't
print"). The print card shows the printer and the computer it hangs off, and their states.

Bulk Print with PrintNode runs each first print separately through review, as before. Easyship
label+CN23 bundles print their label page only; Parcel2Go 4×6 labels go unchanged.

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
