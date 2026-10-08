# Shipping fulfilment operations

## Merchant workflow

The inbox reads like Shopify's Orders: Order, Purchased (Shopify's order time in the store's time zone), Customer, Destination, Shipping (package under it), Status and Label (Not printed / Printing… / Printed / Print failed). Newest order first; on a phone the table becomes a list. Each row has a checkbox. Ticking one turns the list's header into the selection bar in place (the header box shows none, some or all; the count; Buy labels or Print labels; Clear), so nothing on the page moves. "Select all ready" asks the server for the current Ready list (up to 100). Buy labels reviews each order again (provider, service, current price, total) and names any that changed since they were selected (e.g. "17 ready to buy · 1 changed since you selected them (not included)"), then confirm. Print labels takes purchased rows only, in their visible order. Excluded rows explain why they will not run.

Batch progress has independent per-order outcomes and survives browser reload. Open a recent batch to inspect purchased, sent, failed, skipped and uncertain rows. A failure does not roll back successful rows or retry an uncertain payment or print. There is deliberately no combined Buy & print action.

An unpurchased shipment has inline HS code, origin and customs-description fields. Save uses the existing canonical product-facts and Shopify inventory-item update path, rechecks readiness and refreshes rates. HS codes are 6–10 ASCII digits; leading zeros are preserved, punctuation and padding are rejected. Existing provider-specific length checks remain. Shopify inventory items hold HS code/origin; CLIVE's existing product facts hold the merchant description and confirmed customs facts. Shopify-write problems remain visible through the existing warning mechanism. Purchased customs snapshots cannot be edited.

"Not sure of the code? Describe it" finds a UK commodity code from plain English (e.g. "men's cotton hoodie") and what Shopify already says about the product. It walks the official UK Trade Tariff, asks one question at a time in the tariff's own words only when a fact decides the code, and shows a ten-digit code read back from the tariff (exists, declarable, in force) with its official description and the reasons. Use this code fills the field; nothing is saved until Save. A typed ten-digit code is checked on save and refused if the tariff doesn't have it; if the tariff can't be reached the code is kept, marked unchecked. How it was chosen (manual, or suggested then confirmed; the answers; who; when) is kept with the product's facts. Garments covered: jeans, jorts, shorts, joggers and other trousers, skirts, T-shirts, hoodies and jumpers; anything else is typed by hand. `SHIPPING_TARIFF_ENABLED=false` turns the finder and the check off.

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

The V1 gate results are recorded in the release notes, `docs/V1_RELEASE.md`.

## Deployment (separate approval)

Released with Returns as V1: the checklist, commands and rollback are in `docs/V1_RELEASE.md`. The batch tables and indexes are created automatically on startup. Back up the live SQLite database first (SQLite backup, not a copy of an active WAL database). After deployment, inspect an existing purchased shipment's badge, a non-purchasing batch review and an unpurchased product's customs fields. Physical fulfilment still requires the merchant to verify the printer output.
