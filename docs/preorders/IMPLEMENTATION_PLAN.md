# CLIVE Preorders: implementation plan

Status: plan written before implementation (2026-10-13); sections 1-10 are kept as written.
Section 11 records what was actually built and where it differs.

## 1. What exists (audit)

| Area | Found |
| --- | --- |
| Shopify app | One Dev Dashboard app, **CROOKS Operations** (client credentials, `client_id` + secret on the server). Config template `crooks-returns/shopify.app.toml.example`; the real `shopify.app.toml` is copied from it and deployed with `npx @shopify/cli app deploy` from `crooks-returns/` (the app project root). No extensions yet. |
| Services | Python 3.11, FastAPI, httpx, Pydantic, SQLite, pytest, ruff, pyright. Each sister app is its own service and database: Returns (`/`, port 8100) and Shipping (`/shipping/*`, port 8120), Docker Compose behind Caddy (`crooks-returns/Caddyfile`, `docker-compose.yml`). Patterns are shared, code is not. |
| Admin UI | Single-file `static/admin.html` per service: Polaris web components (`polaris.js`) and App Bridge (`app-bridge.js`), session-token auth (`auth.verify_session_token`, HS256 with the app secret). Shared sidebar via `<s-app-nav>`. |
| Shopify API | Admin GraphQL **2026-10** everywhere; documents validated with the Shopify AI Toolkit; client credentials token; no 5xx retry for mutations (Shipping). |
| Scopes today | `read_orders, read_customers, read_products, read_returns, write_returns, read_/write_merchant_managed_fulfillment_orders, read_assigned_fulfillment_orders, read_third_party_fulfillment_orders, store credit scopes, read_inventory, write_inventory, read_locations`. No purchase-option scopes, no `write_products`. |
| Webhooks | Classic HTTPS subscriptions in the app toml (`returns/*` today), HMAC-SHA256 with the app secret. No Shopify Events. |
| App proxy | One per app: `crooksldn.com/apps/returns/*` → `https://<host>/proxy/*`, signed. |
| Jobs | No queue. Each service runs a background `tick` in-process; webhooks are handled inline. |
| Email | None. Returns relies on Shopify's own notifications; CLIVE gets signed webhooks. Omnisend exists for marketing (not used here: transactional only). |
| Theme | The CROOKS theme (Liquid) is at the repo root; no theme app extension exists. |
| Shipping link | Shipping reads only `status:open` fulfilment orders. A preorder line on a fixed-date selling plan gets a **SCHEDULED** fulfilment order, so Shipping naturally leaves it alone until it opens, and in-stock lines of the same order ship normally. |
| Tests/CI | pytest per service; ruff; pyright baseline 71; Playwright for UI checks. |

## 2. Proposed architecture

A third sister service, **`clive-preorders/`** (package `preorders`), in the same shape as
Shipping: FastAPI, SQLite (relational tables with constraints, not one JSON blob), a background
tick, an embedded admin page under `/preorders/admin`, a bearer-key API for CLIVE under
`/preorders/api/v1`, Shopify webhooks under `/preorders/webhooks/shopify`, and storefront calls
through the existing app proxy at `/apps/returns/preorders/*` (Caddy routes
`/proxy/preorders/*` to the service).

Layers:

- `domain.py`: pure rules. Variant state (IN_STOCK / PREORDER / NOTIFY_ME), remaining capacity,
  readiness (received stock assigned to preorder lines oldest first), line classification.
- `store.py`: SQLite schema, transactions (`BEGIN IMMEDIATE`), unique constraints.
- `shopify.py`: Admin GraphQL client (2026-10), every document validated.
- `selling_plans.py`: the **selling-plan adapter boundary** (`SellingPlanPort`): Shopify
  implementation, plus a "not available" implementation used when purchase-option access is
  missing. Nothing else talks to selling plans.
- `sync.py`: desired-state convergence. Given our offers and Shopify's inventory, it makes Shopify
  match: variants in or out of the selling plan group, inventory policy, storefront metafield.
  Idempotent; run after every change and on the tick.
- `ingest.py`: webhook inbox (deduplicated by Shopify's event id) and order ingestion. Each order
  is re-read from GraphQL (authoritative, order of delivery irrelevant) and its preorder lines
  upserted by line item id.
- `inbound.py`: batches, allocation, receipt (Shopify `inventoryAdjustQuantities` with
  `@idempotent`, recorded before sending).
- `waitlist.py`: storefront signups and explicit notification.
- `comms.py`: email provider interface (Resend implementation; disabled by default), templates,
  delivery log with dedupe keys.
- `reconcile.py`: rebuild counts from Shopify orders, re-converge Shopify, report differences.
- `classification.py`: the stable boundary for CLIVE Shipping and others.
- Theme app extension `crooks-returns/extensions/clive-preorders/` (app block + small JS/CSS).

## 3. Shopify API surfaces (Admin GraphQL 2026-10)

- Selling plans: `sellingPlanGroupCreate`, `sellingPlanGroupUpdate`,
  `sellingPlanGroupAddProductVariants`, `sellingPlanGroupRemoveProductVariants`. One group per
  offer (product × inbound batch), one plan: `category: PRE_ORDER`, billing
  `fixed { checkoutCharge: PERCENTAGE 100, remainingBalanceChargeTrigger: NO_REMAINING_BALANCE }`,
  delivery `fixed { fulfillmentTrigger: EXACT_TIME, fulfillmentExactTime: <dispatch date> }`,
  pricing `fixed PERCENTAGE <discount>` when there is a discount, inventory
  `reserve: ON_SALE`.
  - **Why ON_SALE:** units are committed when the preorder is placed, so stock that arrives
    covers the preorders first and is not sold again to walk-in buyers. With ON_FULFILLMENT,
    received stock would show as available and be sold twice.
- Variants: `productVariantsBulkUpdate` (inventory policy CONTINUE only while the variant is in
  PREORDER state, DENY otherwise), catalogue reads (`products`, `productVariants`,
  `inventoryItem.inventoryLevels.quantities(available, committed, incoming, on_hand)`).
- Metafields: `metafieldsSet` on variants, app-owned `$app:preorder` (JSON), declared in
  `shopify.app.toml`.
- Inventory: `inventoryAdjustQuantities` (`available`, reason `received`) with `@idempotent`.
- Orders: `order(id)` with `lineItems { sellingPlan { sellingPlanId name } quantity
  currentQuantity unfulfilledQuantity ... }`, `fulfillmentOrders { status fulfillAt }`,
  `fulfillmentOrderOpen` (release a stock-backed preorder early, explicit action).
- Locations: `locations(first)` for the receiving location.

## 4. Database (SQLite, `clive-preorders/data/preorders.sqlite3`)

`batches`, `batch_lines`, `offers`, `offer_variants`, `preorder_lines`, `waitlist`,
`communications`, `receipts`, `webhook_inbox`, `catalog` (Shopify snapshot), `events` (audit).
Key constraints: `preorder_lines.line_item_id` unique; `waitlist (shop, variant, email)` unique
while ACTIVE (partial index); `communications.dedupe_key` unique; `receipts.idempotency_key`
unique; `webhook_inbox.event_id` primary key. Sold counts are **derived** from ingested lines,
never incremented. Migrations: schema version table; `CREATE TABLE IF NOT EXISTS` plus ordered
migrations.

## 5. Scopes

Add `read_purchase_options`, `write_purchase_options` (selling plans) and `write_products`
(variant inventory policy, variant metafields). Already granted and used: `read_orders`,
`read_customers`, `read_products`, `read_inventory`, `write_inventory`, `read_locations`,
`write_merchant_managed_fulfillment_orders`. Not needed for 100%-at-checkout preorders (only for
deposits): `read_customer_payment_methods`, payment mandate scopes, `read_all_orders`.

**Access blocker.** Shopify says most pre-order apps must request API access in the Partner
Dashboard, and that custom apps made in the Shopify admin cannot use pre-orders. CROOKS
Operations is a Dev Dashboard app, the kind Shopify recommends for a single store. Whether
`write_purchase_options` is granted without a request can only be seen on `app deploy`. If it is
refused, the selling-plan adapter reports "not available": the domain, admin, inbound stock,
waitlist and communications all work, and no fake preorder is offered on the storefront.

## 6. Extensions

Theme app extension `clive-preorders` with one app block, "Pre-order / Notify me", placed in
the product template's buy area. It reads the selected variant from the product form's `id`
field, decides the state from Shopify's own data (the variant's selling-plan allocation from this
app's group and its inventory), adds `selling_plan` to the form for a preorder, relabels the
button "Pre-order", shows the dispatch date, price and payment timing, and shows a Notify me
form when the variant can't be bought. The cart and checkout show the selling plan name natively
("Pre-order: expected to dispatch by 7 November").

## 7. Webhooks

Add to the app toml (uri `https://<host>/preorders/webhooks/shopify`, API 2026-10):
`orders/create`, `orders/updated` (also fires for cancellation, refunds, edits and fulfilment),
`inventory_levels/update`. Handlers verify the HMAC, store the event id and return; the tick
processes the inbox. `app/uninstalled` is not needed (single store; uninstall removes the
selling plans after 48 hours; data retention is documented).

## 8. Migration strategy

New service and database: nothing existing changes shape. Shopify changes are additive (scopes,
webhooks, metafield definition, extension). Rollout: deploy with `PREORDERS_SELLING_PLANS=off`
(admin, inbound, waitlist only), then switch on after the scope is granted and one test offer
works.

## 9. Phases

1. Audit and this plan. 2. Database and domain. 3. Selling-plan adapter and sync.
4. Admin products and preorder configuration. 5. Theme extension. 6. Order ingestion and the
Pre-orders screen. 7. Incoming stock and receipt. 8. Notify me storefront and demand screen.
9. Communications. 10. Reconciliation, resilience, tests and polish. Tests are written with
each phase.

## 10. Risks

- **Oversell window.** Shopify can't cap checkout at our allocation. Protection: the variant is
  in the selling plan group and set to CONTINUE only while capacity remains; the order that uses
  the last unit closes it (group removal and DENY) as soon as it is ingested; reconciliation
  flags any over-allocation. Concurrent checkouts in the seconds before that can exceed the
  allocation by a few units. These are shown, never hidden. A Cart and Checkout Validation
  Function would narrow it further (V2).
- **A line bought without the selling plan** while a variant is on CONTINUE (theme JS failed or
  a crafted cart): flagged as "bought without the preorder plan" for staff.
- Purchase-option access (above). The fulfilment date on a SCHEDULED fulfilment order isn't
  moved when the dispatch date changes; release is explicit.

## 11. As built (2026-10-13)

**Shape.** As planned, with fewer files: `sync`, `ingest`, `inbound` and `classification` live in
`service.py` (`PreordersService`), because they share one transaction boundary and the same
convergence step; the selling-plan adapter boundary is its own module as planned.

| File | What it holds |
| --- | --- |
| `preorders/domain.py` | Pure rules: `derive_state` (override → NOTIFY_ONLY → PREORDER_ONLY → shelf → preorder → notify), `remaining`, `oversold`, `ready_units` (oldest first), `line_state`, `classify`, customer wording. |
| `preorders/store.py` | SQLite (WAL, foreign keys), numbered migrations, `tx()` = `BEGIN IMMEDIATE`, nestable. |
| `preorders/shopify.py` | Admin GraphQL 2026-10 client (13 documents, all validated), `ShopifyPort`, `ShopifyError` (outcome unknown) vs `ShopifyRefused`. |
| `preorders/fake.py` | The same port in memory, keeping Shopify's rules (ON_SALE commits stock, DENY refuses, SCHEDULED fulfilment orders for plan lines, idempotent inventory adjust). Tests and the dev server use it. |
| `preorders/selling_plans.py` | `SellingPlanPort`: `ShopifyPlans`, and `UnavailablePlans` when `PREORDERS_SELLING_PLANS=off` or Shopify answers ACCESS_DENIED. Then nothing is sold as a preorder. |
| `preorders/service.py` | Catalogue, batches and allocation, offers, convergence with Shopify, webhook inbox, order ingestion, readiness, date changes, receipt, release, classification, screen data. |
| `preorders/comms.py` | Mailer interface (Resend, disabled, recording), templates, delivery log with dedupe keys. |
| `preorders/waitlist.py` | Signups, unsubscribe tokens, demand views, explicit notify, retention. |
| `preorders/reconcile.py` | Re-read every order on our plans and every known order, recompute readiness, re-converge Shopify, report what needs attention. |
| `preorders/app.py` | FastAPI: admin API, CLIVE `/api/v1`, app proxy, webhooks, the background tick. |
| `preorders/static/admin.html` | The embedded admin (Polaris web components, App Bridge). |
| `crooks-returns/extensions/clive-preorders/` | Theme app extension: one app block, `preorder.js`, `preorder.css`, English strings. |

**Database.** Tables: `batches`, `batch_lines` (allocation ≤ expected, one line per variant per
batch), `offers` (one per product × batch), `selling_plans` (**plan history**: every plan id we
ever created with its dispatch date and discount, so an order is always read against the promise
it was bought with), `offer_variants` (enabled, override, the variant's original inventory
policy, last metafield written), `preorder_lines` (`line_item_id` unique; `promised_dispatch_at`
never changes, `current_dispatch_at` follows the batch), `unplanned_lines`, `waitlist` (one
ACTIVE signup per shop, variant and email: partial unique index), `communications`
(`dedupe_key` unique), `receipts` (`idempotency_key` unique), `webhook_inbox` (`event_id`
primary key), `catalog` (Shopify snapshot), `events` (audit), `schema_version`. Sold counts are
always derived (`SUM(current_quantity)` of uncancelled lines). Migration 2 adds
`preorder_lines.released_at` (tested upgrading a version-1 database in place).

**Differences from the plan.**

- A date or discount change **replaces the plan** in the group rather than editing it, and keeps
  the old plan in `selling_plans`; existing orders keep their plan and promise. The group is
  recreated if it was deleted in Shopify.
- Safety ordering when converging: opening attaches the plan, then sets CONTINUE; closing sets
  DENY, then detaches. A failure in between leaves the variant unsellable rather than sellable
  without a plan. Each variant's own policy is restored when its preorder closes.
- After each ingested order the touched products' stock is re-read from Shopify, and the order
  that uses the last unit closes the offer in the same pass.
- `classify_order` ingests an order first if it has a line on one of our plans that hasn't been
  seen yet, so CLIVE never gets IN_STOCK for an unprocessed preorder.
- The storefront signup is not a `<form>`: themes may render the block inside their product
  form, and browsers drop a nested form. The script sends it (button or Enter).
- Fully receiving a batch closes its offers; the sizes then sell normally from stock.
- Release for dispatch opens only SCHEDULED fulfilment orders whose preorder lines are all
  ready; it shows the orders first. Each order is re-read before acting; a fulfilment order
  already open (opened by staff, or by Shopify on the date) is counted, not opened again; a line
  is marked released only once its fulfilment order is known to be open, so a lost reply is
  safe to repeat and a released order isn't offered again.
- A size added to a batch without a preorder quantity preorders all that's coming (as when the
  batch is created); 0 is only ever an explicit choice.
- `customers/redact` is handled by the webhook endpoint, but the app has no compliance
  webhooks configured, so nothing sends it yet (README).
- PREORDER_ONLY and NOTIFY_ONLY modes and per-variant overrides exist in the domain and
  database; the admin offers AUTO only.

**Not built (V2).** A Cart and Checkout Validation Function to close the oversell window;
moving a SCHEDULED fulfilment order's date when the dispatch date changes (release is explicit
instead); deposits / partial payment; other languages than English; fixed-amount discounts.

**Verified.** 37 tests (scenarios A-H and the failure modes around them, HTTP doors); ruff;
pyright clean on `clive-preorders`; 13/13 GraphQL documents valid at 2026-10; theme check (no
offences); a browser walk-through of every screen at 1280 px and 390 px; in the browser, the
date change with Save & notify (6 customers emailed with the original and new dates), a partial
receipt (20 of 30), Release for dispatch (3 orders, then none offered again), Notify 10 people
when a size opened for preorder (a second press sends nothing), and the storefront block in its
three states with a signup. Not
verifiable here: a real Shopify checkout on a selling plan, Shopify's answer on purchase-option
access, real email delivery.
