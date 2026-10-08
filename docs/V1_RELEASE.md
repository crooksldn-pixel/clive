# CLIVE Shipping V1 and CROOKS Returns V1

What V1 is, the rules it never breaks, what it can't do, and how to release and roll it back.
Details live with each app (`docs/shipping/DESIGN.md`, `clive-shipping/OPERATIONS.md`,
`clive-shipping/PRINTNODE.md`, `docs/returns/BRIEF_CLIVE.md`, `docs/sister-apps/CLIVE_OPERATIONS.md`).

## The rules both apps keep

- **Preview, then act.** An action that moves money or changes Shopify is previewed, re-checked
  against Shopify and the provider at the moment of acting, and done only on an explicit press
  (or an explicit CLIVE call with the preview's basis and an idempotency key).
- **Three outcomes, never two.** Verified success, verified failure, or UNKNOWN. UNKNOWN (no
  answer, a timeout, a 5xx, an answer that can't be read) is never treated as failure and never
  repeated blindly: the thing is read back first, and "not found" counts only after it has had
  time to land. A Shopify change (a mutation) that meets a 5xx is never re-sent by the client:
  the order is read back instead.
- **Written down before it is sent.** A purchase, a Shopify return, a label hand-over or a label
  payment is recorded before the call, so a crash or a lost reply leaves a record that is
  reconciled, never a second charge.
- **One key, one action.** Repeating a request with the same idempotency key replays its first
  answer; it never acts again. In Returns the same key with different details is refused.
- **Print never buys. Fulfilled is not delivered.** Delivered comes only from the carrier's
  tracking in Shopify.

## Shipping V1

- **Inbox, like Shopify's Orders.** Tabs: Needs attention, Ready to ship, Labels bought,
  Printed, In transit, Delivered, All (stages derived by `shipping/lifecycle.py`, never stored).
  Columns: Order, Purchased (Shopify's order time, in the store's time zone: "Today at 13:06"),
  Customer (a guest or deleted customer shows the addressee), Destination, Shipping (package
  under it), Status, Label. Newest order first. On a phone the table becomes a list. Search and
  the tab live in the URL.
- **Payment gating.** A new label needs a payment status that allows it
  (`Order.displayFinancialStatus`), re-read just before buying. Every blocker shows at once.
- **Customs.** HS code, origin, weight and description are asked once per product and saved to
  Shopify and CLIVE's product facts, so the next order isn't asked.
- **Finding the commodity code** ("Not sure of the code? Describe it"): plain English and what
  Shopify already says about the product → the official UK Trade Tariff tree → one question at
  a time, in the tariff's own words, only for a fact that decides the code → a ten-digit code
  read back from the tariff (exists, declarable, in force) with its official description and
  why → the merchant uses it and saves. A suggestion is never saved by itself. The merchant's
  own words decide; Shopify's title and type only fill what they leave open. A blend is
  classified by the fibre with the largest share when the shares are given ("80% polyester
  20% cotton"), otherwise "What is it mostly made of?" is asked. Lines passed over without
  asking (workwear, hand-made, batik, fine-knit roll necks) are named in the reasons. A typed
  ten-digit code is checked on save (one the tariff doesn't have is refused); if the tariff
  can't be reached, or answers in a shape CLIVE can't read, the code is kept, marked unchecked.
  Covered garments: jeans, jorts, shorts, joggers and other trousers, skirts, T-shirts, hoodies
  and jumpers. Anything else (underwear, swimwear, dresses, jackets), or a line that turns on
  something not asked (a 600 g wool jumper, a fine-knit turtleneck, silk), is entered by hand.
- **Buying a label.** Preview (the exact price now), buy once with the preview's basis; the
  purchase ledger makes a lost reply UNKNOWN and reconciles it before anything is repeated; the
  provider is paid at most once per attempt. Shopify is marked fulfilled with the tracking
  number only after the purchase is known to have succeeded. If Shopify closes an order's
  fulfilment order and opens another after a label was bought (moved location, an order edit),
  the new one is not offered for a label: it waits in Needs attention ("Already has a label")
  until a person confirms it really is a second parcel. If the provider later says a label it
  accepted payment for isn't paid, staff get one alert; nothing is paid again.
- **Bulk.** Select rows (header box: none → all, some or all → none; up to 100 at a time;
  "Select all ready" asks the server again),
  review (each order re-checked; any that changed since selection, e.g. now unpaid, is left out
  and named), confirm; each order then runs independently in the durable batch engine.
- **Printing.** Without PrintNode, Print opens the label as a 4×6 PDF to print from the browser
  (bulk: one combined PDF); opening it counts as printed. With PrintNode, Print sends the job;
  the order says Printing… until PrintNode reports done (Printed) or error/expired (Print
  failed, with PrintNode's reason; Print works again). A retried request never prints twice,
  and once any copy has printed, Print (from a stale tab or CLIVE) is refused: Reprint is the
  deliberate way;
  never confirmed after six hours shows "Not confirmed by printer". The printer and its computer
  are shown with their states.
- **Journey and tracking.** Order placed → Label bought → Label printed → In transit → Out for
  delivery → Delivered, each with its time; the carrier's own updates (message, country) and
  where the parcel was last seen. Each scan is in the history. Staff names, not ids.
- **CLIVE `/api/v1`.** Capabilities, list by stage, read, preview, buy, print, reprint,
  tracking, events (oldest first, `has_more`, `source`). Read and write keys are separate.

## Returns V1

- **Customer portal.** Order number plus email, postcode or phone; choose items, reason and
  outcome (refund, store credit with bonus, exchange); postage by the policy; the case file
  shows progress; the customer can add tracking.
- **Staff review.** Approve (book a label now, customer posts it, label later, or keep it),
  decline, label, tracking, receive, complete, cancel, note; each previewed ("This will…") and
  run through one `execute`. Works on a phone.
- **Shopify.** `returnCreate`, the label hand-over and `returnCancel` are sent once; a lost or
  unreadable answer is UNKNOWN, recorded before sending, reconciled against Shopify (two
  minutes before "none" is believed). `returnProcess` and store credit use Shopify's
  `@idempotent` keys. Declining or cancelling after an unknown approval checks Shopify first and
  cancels any return it made.
- **Return labels (Parcel2Go).** The order and the payment are recorded before paying; a lost
  pay reply is settled by reading the order, and an "unpaid" read within 15 minutes of a payment
  sent is not believed, so a label is never paid twice. A clear refusal (e.g. not enough PrePay)
  can be retried at once. Paid labels that weren't released are collected later, never re-bought.
- **CLIVE `/api/v1`** with the same shape; every event names its source (portal, ui, api,
  ctl, system). The Parcel2Go access hash is never shown, sent or logged.

## Known V1 limitations

- **Tracking detail** is what the carrier gives Shopify: for Royal Mail a message, a time and a
  country (no city, no means of transport). Channel Islands parcels: Royal Mail's tracking stops
  at the hand-over to Guernsey/Jersey Post, so Shopify may never say delivered.
- **"Printed"** via PrintNode means the printer's computer finished the job; a jam after that is
  not visible. Via the print view it means the PDF was opened.
- **Commodity codes** are UK (UK Global Tariff) ten-digit codes for the garments listed above;
  other goods are typed by hand. Workwear, batik prints and hand-made lines are treated as not
  applying (the chosen path shows "Other" before the merchant confirms).
- **Shopify admin** must be opened by the owner to check the embedded screens (needs a login).
- **Returns' admin** is styled with its own CSS, Shipping's with Polaris components: they look
  related, not identical.
- **Bulk buys of more than about 50 orders** can run past the review's ten minutes; the later
  orders then stop with "Review expired" (nothing bought for them) and need a fresh review.
- **Older print count.** "Print all ready labels" (the legacy print page) treats a label whose
  PrintNode job failed as printed; the order itself says Print failed and Print works there.
- **Provider wording** on single-order errors is shown as the provider wrote it (no
  credentials are in it; the bulk path already rewrites it).
- **One channel at a time** for Returns actions on the same return (screen, CLIVE, `returns-ctl`
  run in separate processes share a database but not a lock).

## Deferred to V2

- More carriers' tracking, maps, transport mode, predicted delivery dates.
- Commodity codes beyond the garments above, an AI classifier behind the same interface,
  non-UK tariffs.
- Returns: Parcel2Go label refunds on cancel; re-checking the price paid against the preview;
  re-choosing drop-off shops when the chosen courier is unavailable; a database-level guard
  across processes; Click & Drop as a label provider (not configured in production).
- One design system across Returns and Shipping.
- Shipping: bulk review expiry measured per order rather than per batch; one definition of
  "printed" everywhere; sanitised provider text on single-order errors; an alert when a
  purchase thread conflicts after paying; a timeout for an unconfirmed label cancellation;
  startup resume off the request path; secrets as `SecretStr` throughout settings.
- Returns: a crash between paying for a return label and saving the approval leaves the return
  as it was with the paid Parcel2Go order recorded on it: approving again reads that order back
  and uses it (never paid twice), but declining it instead leaves a paid label to refund on
  parcel2go.com. A refused token waits out the 15-minute window although nothing was paid.

## Release checklist (V1)

Do not deploy without the owner. Nothing here buys postage, prints, or changes a live return.

1. **Release SHA.** Note the commit running now (`git log --oneline -1` on the server) for
   rollback, and the release commit (this branch's head).
2. **Back up both databases** (SQLite online backup: safe while running, WAL included).
3. **Config.**
   - Shopify scopes: Shipping now reads `Order.customer` (`read_customers`), already granted
     to the shared CROOKS Operations app (Returns needs it). No `app deploy` needed.
   - Shipping `.env`: optional `SHIPPING_TARIFF_ENABLED` (default true) and
     `SHIPPING_TARIFF_BASE_URL`; the server needs outbound HTTPS to
     `www.trade-tariff.service.gov.uk`. Nothing else is new.
   - Returns `.env`: check `RETURNS_RETURN_LABEL_COST_PENCE`. The portal policy text offers a
     paid drop-off label for change-of-mind refunds; set it, or the offer isn't made.
   - Unchanged and still required: `SHIPPING_AUTHORISED_ORDERS` / `SHIPPING_BUYING_ENABLED`
     (no label can be bought unless set), PrintNode keys (only if printing directly).
   - Optional, only when CLIVE is to use Shipping: `SHIPPING_CLIVE_READ_KEYS` /
     `SHIPPING_CLIVE_WRITE_KEYS`, generated on the server (never in chat). Without them
     Shipping's `/api/v1` answers nothing.
4. **Build and restart** `returns` and `shipping` with Docker Compose.
5. **Health.** `/health` for Returns, `/shipping/health` for Shipping.
   Shipments stored before the payment gate show "Payment status unknown" in Needs attention
   until the first tick re-reads them (about a minute) or someone presses "Check Shopify for
   orders"; nothing can be bought meanwhile.
6. **Dry run.** `python -m shipping.tools.dry_run` in the shipping container: reads every open
   order, buys nothing.
7. **UI smoke in Shopify admin** (owner):
   - Shipping: each tab loads; Purchased and Customer show; tick a Ready row (the bar changes in
     place, nothing moves), Clear; open an order without an HS code, "Find the code", answer,
     check the code shown, do not save unless it's right; open a delivered or in-transit order:
     the journey and carrier updates show.
   - Returns: open a pending return on a phone, tap Approve, check the dialog, Cancel.
8. **Logs.** `docker compose logs --since 10m returns shipping`: no new errors.
9. **Rollback constraints.** The old code reads the new records and ignores new fields; before
   rolling back, settle any return with a lost-reply or payment marker (the query below) and any
   Shipping purchase that is UNKNOWN (Needs attention).

### Commands

```bash
ssh root@crooks-os-prod-1
cd /opt/clive
git log --oneline -1                      # note it: the rollback commit
# 2. Back up
for db in crooks-returns/data/returns.sqlite3 clive-shipping/data/shipping.sqlite3; do
  python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); print('backed up', sys.argv[1], '->', sys.argv[2])" \
    "$db" "/root/$(basename "$db" .sqlite3)-$(date +%F-%H%M).sqlite3"
done
# 1. Update to the release
git fetch origin claude/compassionate-dirac-44hnee
git checkout claude/compassionate-dirac-44hnee && git pull --ff-only && git log --oneline -1
# 3. Config check (prints no secrets)
grep -E '^SHIPPING_TARIFF_|^SHIPPING_AUTHORISED_ORDERS|^SHIPPING_BUYING_ENABLED|^PRINTNODE_ENABLED' clive-shipping/.env || true
grep -E '^RETURNS_RETURN_LABEL_COST_PENCE' crooks-returns/.env || echo "RETURNS_RETURN_LABEL_COST_PENCE not set"
# 4. Build and restart
cd crooks-returns && docker compose up -d --build returns shipping && docker compose ps
# 5. Health
curl -s https://returns.crooksldn.com/health | head -c 80; echo
curl -s https://returns.crooksldn.com/shipping/health; echo
docker compose exec -T shipping python -c "import httpx; print(httpx.get('https://www.trade-tariff.service.gov.uk/uk/api/commodities/6109100010', timeout=10).status_code)"
docker compose exec -T shipping python -c "from shipping.settings import Settings as S; s=S(); print('buying_enabled:', s.buying_enabled, '| orders:', sorted(s.authorised()) or 'none')"
# 6. Dry run (buys nothing)
docker compose exec -T shipping python -m shipping.tools.dry_run
# 8. Logs
docker compose logs --since 10m returns shipping | grep -iE 'error|exception|traceback' || echo "no errors"
```

### Rollback

```bash
cd /opt/clive
# Returns with a lost-reply marker, or a label payment sent in the last 15 minutes: settle first
python3 - <<'PY'
import sqlite3
d = sqlite3.connect("crooks-returns/data/returns.sqlite3")
print(d.execute("""SELECT id, order_name FROM returns WHERE
  json_extract(doc,'$.shopify.create_unknown_at') IS NOT NULL
  OR json_extract(doc,'$.shopify.attach_unknown_at') IS NOT NULL
  OR (json_extract(doc,'$.postage.label_paying_since') IS NOT NULL
      AND json_extract(doc,'$.status') = 'awaiting_label')""").fetchall())
PY
git checkout <the commit noted in step 1>
cd crooks-returns && docker compose up -d --build returns shipping && docker compose ps
```

The databases need no restore. Restore a backup only if a record is damaged:
`docker compose stop returns shipping`, copy the backup over the `.sqlite3` file (after removing
its `-wal` and `-shm` files), start both again.
