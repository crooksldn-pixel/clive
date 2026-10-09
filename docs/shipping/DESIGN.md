# CLIVE Shipping: design and Phase 0 findings

**Status (2026-10-05):**
- **Stage 1 built:** domain, state machine and the pay-once purchase protocol.
- **Stage 2 built:** Shopify discovery, readiness, remembered answers, packages, duties and fulfilment with read-back.
- **Stage 3 built and proven (2026-10-05):** the Parcel2Go sandbox adapter, with documents
  modelled separately, the genuine 4×6 label, evidence-based customs, and every failure case
  proven in tests and against the sandbox. No live credential, no live spending.
- Nothing is deployed.
- **UK labels through Shopify Shipping built (2026-10-09):** behind `SHIPPING_DOMESTIC_LABELS`
  (off by default). See H, stage 9.

## Owner decisions (2026-10-05)

| Topic | Decision | Where it lives |
| --- | --- | --- |
| Duties | No IOSS today. Ship DAP: the customer may pay import VAT, duty and fees on arrival, and CLIVE says exactly that and never claims prepaid. IOSS/DDP is a per-shop setting for later, not a constant. | `DutiesPolicy` in `ShopConfig`; `duties.terms()` |
| Packaging | Never invented. The first real package is entered once, when the first shipment needs it, and remembered. Multiple presets are supported; the package used for a mix of products is learned on purchase; inference comes later. | `PackagePreset`, `packages.plan()`, `package_choices` |
| Country of origin | Never inferred or bulk-filled. Asked once per product when a real shipment needs it and Shopify has none. Saved to every size's InventoryItem in Shopify (the record) and remembered here with who and when. Not asked again unless Shopify's value changes. | `readiness`, `facts`, `inventoryItemUpdate` |
| Printer | JADENS roll-fed thermal on a Windows laptop via PrintNode. Prefer 4×6 in (~100×150 mm) labels. Printing comes later, but the label is stored once as an artifact (`label_4x6` first). Reprint renders that stored file and has no path to a purchase. | `Label.artifacts`, `Purchases.reprint()` |
| Setup | Progressive: nothing catalogue-wide up front. A fact is asked only when a real shipment needs it. | readiness questions |
| UK labels (2026-10-09) | Bought through the store's Shopify Shipping account, Royal Mail Tracked 24 or Tracked 48 only, decided by the checkout delivery method through an explicit mapping; an unmapped method waits for a person. Never guessed, never Shopify's default rate selection. No price before buying: accepted for now. | `domestic.py`, `providers/shopify_shipping.py`, `SHIPPING_DOMESTIC_*` |

**Thesis:** international orders ship like domestic ones. CLIVE absorbs the complexity; the merchant sees one decision, "Buy label — £X?", and the occasional single question it can't answer itself.

---

## Phase 0: what was verified, and how

Everything marked **[tested]** was exercised on 2026-10-04 against the Parcel2Go sandbox with CROOKS's sandbox credentials, or against shopify.dev's 2026-10 reference.

| Finding | Evidence | Consequence |
| --- | --- | --- |
| Parcel2Go quotes UK→DE/FR/US/AU with 23–28 services each (Evri Intl from £6.60 to DE; DPD, Parcelforce, UPS, USPS via OCS, Asendia, Landmark). | [tested] `POST /api/quotes` | Enough choice for a recommendation of three |
| Every international quote declares `RequiresCustoms`, `CountryOfManufactureRequired`, `ExportReasonRequired`, `RequiresCommercialInvoice`; `TariffCodeRequired` false in the sandbox. | [tested] | Origin country is a hard requirement; the HS code is sent always (best practice, and the EU/US increasingly expect it) |
| An order with `Contents[{Description, Quantity, EstimatedValue, TariffCode, OriginCountry}]` + `ExportReason: Sale` produces a label PDF with **3 commercial invoices** filled from our data. | [tested] order 26670 | CLIVE supplies facts; Parcel2Go produces the paperwork |
| `POST /api/orders/verify` returns the exact price for the exact order without creating anything. | [tested] | Preview can show the real price, not just a quote |
| Orders are created **unpaid**, then paid with `paywithprepay`. `GET /api/orders` exposes `PaidDate`. | [tested] | Money moves at one call, and we can read back whether it moved |
| **Paying an already-paid order charges again** (200, balance −£2.39). | [tested] order 26633 | The pay call must never be repeated blindly. This also fixed the same latent bug in Returns (commit `7e67e1e`) |
| There is **no cancel/void endpoint** in Parcel2Go's API (Swagger v1). A secondary report of a "Cancellation API" did not match the published spec. | [tested] swagger | Void is a manual, merchant-confirmed flow in v1 |
| International services are printer-required (no QR); labels come as A4, 4×6 and A4-with-4×6, as PDF. | [tested] | Fine for outbound (CROOKS has a printer); 4×6 is the default |
| `shippingLabelPurchase` (Shopify Shipping, Admin API **2026-07+**) buys a label for a fulfillment order, async (`PENDING_PURCHASE → PURCHASED/FAILED`), customs taken from Shopify's product data, needs `write_orders` + fulfillment-order scope + staff `buy_shipping_labels` + Shopify Shipping ToS. **No idempotency key, no app-callable rates query, no void mutation, no FedEx.** | [docs] shopify.dev 2026-10 reference | Strong future option (native, merchant pays Shopify, no reseller issue), but it cannot show a price before purchase today, which breaks "Buy label — £X". Kept behind the provider port. **Used for UK labels since 2026-10-09** (owner accepted no price; see H, stage 9) |
| No list of `preferredRateSelection` carrier/service codes exists, and no API returns them. `FulfillmentOrder.deliveryMethod.serviceCode` is the checkout display name, not a rate code. | [forum] Shopify staff, community.shopify.dev, July 2026 | The Tracked 24 / 48 codes are server settings, empty until the owner gets them from Shopify |
| The ShippingLabel is reachable only by its own id or the purchase result's id; no field on Fulfillment or FulfillmentOrder leads to it. | [schema] 2026-10 introspection | After a lost reply (no result id) a label can be found on the order but its file can't be fetched |
| Shopify stores customs facts on `InventoryItem`: `harmonizedSystemCode`, `countryHarmonizedSystemCodes`, `countryCodeOfOrigin`, `measurement` (weight). | [schema] | Shopify is the system of record for product customs facts; CLIVE writes confirmed facts back there |
| Shopify's recommended embedded UI is now **Polaris web components** (`<s-page>`, `<s-section>`, `<s-table>`, `<s-badge>`, `<s-app-nav>`, `<s-modal>`) loaded from `cdn.shopify.com/shopifycloud/polaris.js`, alongside App Bridge. | [docs] app-home | Shipping uses the real components (Returns hand-styles a Polaris look-alike; it stays as it is) |
| EU de minimis ended 1 Jul 2026: €3 duty on parcels under €150. | [secondary] | DAP vs DDP/IOSS matters for EU customer experience; see open questions |

**Still to confirm live, as Phase 0 exit items:**
1. Whether the live CROOKS Parcel2Go account shows DHL Express/UPS international, and at what prices.
2. What a cancelled order looks like through `GET /orders`: does `PaidDate` remain, or is there a refund marker? Cancel a £0-risk sandbox order on the sandbox website, then read it back.
3. Whether Parcel2Go's tracking webhook covers international services.
4. `IOSSCode`/DDP upsell availability on the live account.
5. Introspect `shippingLabelPurchase` on the store at 2026-10, and check which Shopify Shipping international services CROOKS sees in admin (for the fallback). One curl from the server with the Returns app token: `__type(name:"ShippingLabelPurchaseResult")`.
6. Parcel2Go's API terms on acting for other merchants (for Phase 3). Unverified; do not assume.

---

## A. Existing-system assessment (CROOKS Returns as precedent)

**Why Returns feels simple:**
- **One decision per screen.** The customer picks a deal; staff press the next step. The service decides eligibility, offers, prices, sizes and drop-offs. The UI only displays decisions and asks for the one missing choice.
- **Shopify is the record.** An approved return is a native Shopify Return; money moves through `returnProcess`. The service keeps only what Shopify can't: the request, the timeline, the label and attention flags.
- **Every consequential step is `preview` then `execute`.** The preview is plain-language `will` lines with pounds. Execute needs an idempotency key, signs the timeline with the actor, then reads Shopify back and marks the step `verified`.
- **Exceptions are attention flags** (`needs_approval`, `awaiting_label_overdue`, `delivered_unchecked`, `error`), not screens. The inbox is "Needs you".

**Shipping should mirror, adapt, share or keep separate as follows:**

| | Decision | Why |
| --- | --- | --- |
| Action model (preview/execute, idempotency, actor, `will` lines, verified, attention) | **Mirror**, and strengthen with a precondition fingerprint (matching CLIVE's own `STALE`) and a provider-operation ledger | Money-moving and multi-step |
| API shape (`/api/v1`, bearer read/write keys, signed webhooks to CLIVE, `returns-ctl`-style CLI) | **Mirror** | CLIVE integrates both the same way |
| Shopify GraphQL client (client credentials, retries, cost-aware queries), session-token verification, HMAC helpers, signed file links | **Copy and adapt**, not import | Importing Returns' package would couple deploys. Extract a shared kit only if a third service appears |
| Persistence | **Adapt**: same SQLite start, but every row carries `shop`, money-moving operations get their own ledger table, and knowledge has its own table | Tenancy from day one; the ledger is the double-charge defence |
| Embedded UI | **Adapt**: the same three-screen shape (list, record, Setup), built with real Polaris web components | Native look the Returns page imitates |
| Parcel2Go client | **Adapt**: domestic drop-off logic doesn't apply; international `Contents`/customs/export reason, and pay-once settlement | Different domain; the same pay-once rule |
| Shopify app, scopes, secrets, Parcel2Go API credential, database, container, domain | **Separate** | Independent deploy, blast radius and future public app |
| Returns itself | **Untouched**, apart from the double-pay fix found during this investigation | |

**How CLIVE interacts with Returns today:** it doesn't yet. Returns exposes `/api/v1` and signed webhooks, and `docs/returns/BRIEF_CLIVE.md` hands that to the CLIVE builder. CLIVE's application (`crooks-assistant/`) has an action engine (`PENDING → EXECUTING → EXECUTED → VERIFIED`, with `STALE`, `EXPIRED`, `UNVERIFIED`, `FAILED`), a fail-closed permission gate (GREEN/AMBER/RED → execute / stage for owner / deny) and precondition fingerprints. Shipping's API is designed to slot into exactly that:
- `preview` maps to staging a proposal and returns a **basis** fingerprint;
- `execute` with that basis maps to commit;
- a basis mismatch maps to `STALE`;
- read-back maps to `VERIFIED`.

## B. Provider decision

**v1: Parcel2Go (PrePay).**
- **Verified technically** (the table above): international quotes, exact-price verify, customs contents, generated commercial invoices, 4×6 PDF, readable `PaidDate`.
- **Already available** to CROOKS: account, API credentials and PrePay balance, with the same supplier as Returns.
- **Economically sensible:** competitive consolidator prices (Evri Intl £6.60 to DE in the sandbox) and no platform fee.
- **Reliable enough** given the pay-once protocol below.

**Second choice / future SaaS default: Shopify Shipping via `shippingLabelPurchase`.**
- Native.
- The merchant pays Shopify, so CLIVE never handles merchant money or reseller terms.
- Customs come from Shopify product data, which CLIVE will already be keeping correct.

It is blocked for v1 by the lack of a pre-purchase price, idempotency and void. Revisit when Shopify adds a rates query. The provider port is designed so a second adapter is additive.

**Third: Royal Mail Click & Drop**, if CROOKS has an OBA (cheap tracked light parcels to the EU). The code exists in Returns, switched off.

**Not chosen on current evidence:**
- **Shippo:** weak UK international coverage.
- **EasyPost / ShipEngine:** UK value needs your own carrier accounts, which brings per-label fees and onboarding.
- **Direct DHL/UPS/FedEx:** a carrier account per merchant, and heavy onboarding for a small brand.

**Uncertainties requiring the provider:**
- Parcel2Go multi-merchant terms (Phase 3 blocker, flagged, not assumed);
- whether live has DHL Express;
- IOSS/DDP;
- international tracking webhooks;
- void/refund handling and timing.

## C. Architecture

```
Shopify (orders, fulfillment orders, products/InventoryItem customs, fulfillments)
   ▲  GraphQL Admin 2026-10, webhooks (orders/*, fulfillment_orders/*, app/uninstalled)
   │
clive-shipping/  (FastAPI, own container, own Shopify app "CLIVE Shipping", own DB)
   ├─ discovery     open international fulfillment orders → Shipment (one per FO)
   ├─ readiness     facts from Shopify + store knowledge → READY or one question
   ├─ knowledge     confirmed product customs/weight, package choices, service preferences
   ├─ rates         quote → recommend (recommended / cheapest / fastest)
   ├─ purchase      ledger-backed, pay-once protocol (the money boundary)
   ├─ fulfilment    fulfillmentCreate with tracking, then read-back
   ├─ artifacts     label / customs PDFs, stored once; print = render existing artifact
   ├─ providers/    ShippingProvider port → parcel2go (v1), shopify_shipping (later), fake
   ├─ /admin        embedded UI (App Bridge + Polaris web components): Inbox, Shipment, Setup
   ├─ /api/v1       CLIVE: reads, preview, execute, batch preview
   └─ /webhooks     Shopify (HMAC), Parcel2Go tracking (signed)
   │
   ▼ signed events shipment.* → CLIVE (same scheme as Returns)
```

- **Tenancy:** a `shops` row per installed shop. Every table is keyed by `shop`, so no query omits it. Phase 1 has one row (CROOKS) with its credentials from env. Phase 3 moves tokens and provider credentials to per-shop encrypted columns (envelope key from env). Nothing reads `crooksldn` from code.
- **Secrets:** a separate Shopify app (client credentials now, token exchange later), and a **separate Parcel2Go API credential** ("CLIVE Shipping") on the same PrePay account, so audit trails don't mix with Returns.
- **Hosting:** the same Hetzner host, its own container, its own subdomain `shipping.crooksldn.com`. Caddy currently lives in the Returns compose file; adding one site block there is the smallest change. Moving Caddy to a shared `infra/` compose comes at Phase 3.

### Domain objects (money always integer minor units + ISO currency)

```
Shop        shop, name, origin (from Shopify location), label_format, provider, settings…
Shipment    id, shop, order_id, order_name, fulfillment_order_id, destination (address),
            status, attention[], questions[], package (PackagePlan), lines[CustomsLine],
            quote (Quote, basis), recommended, label (Label), fulfillment, tracking,
            timeline[Event], last_error, created/updated
CustomsLine fulfillment_order_line_item_id, variant_id, inventory_item_id, sku, title,
            customs_description, quantity, unit_value_minor, currency, unit_weight_g,
            hs_code, origin_country, facts_source {shopify|knowledge|merchant}, confirmed
PackagePlan preset_id, dims_mm, empty_weight_g, items_weight_g, total_weight_g, source
            {default|learned|merchant}, confirmed
Quote       provider, carrier, service_code, service_name, amount_minor, currency,
            est_days_min/max, printer_required, generated_at, basis (fingerprint)
Label       provider_order_ref, tracking_number, tracking_url, amount_minor, currency,
            artifacts[file ids: label_4x6, label_a4, customs], purchased_at, void_state
ProviderOp  (ledger) id, shop, shipment_id, kind {buy_label}, idempotency_key, basis,
            amount_minor, state, provider_ref, attempts, last_error, created/updated
Knowledge   shop, inventory_item_id → hs_code, origin_country, customs_description,
            weight_g (each with source, confirmed_by, confirmed_at); package_choice by
            item signature; preferred service by destination
Artifact    id, shop, shipment_id, kind, format, sha256, bytes, created_at
PrintJob    (later) id, artifact_id, printer, status, requested_by
```

### Shopify interactions

| | |
| --- | --- |
| Read | `order.fulfillmentOrders` (OPEN, merchant-managed, destination country ≠ origin), line items → `variant.inventoryItem { harmonizedSystemCode, countryCodeOfOrigin, measurement { weight } }`, prices paid, shipping address, assigned location |
| Write (after purchase) | `fulfillmentCreate { lineItemsByFulfillmentOrder, trackingInfo { company, number, url }, notifyCustomer }`. **Before writing, read the FO's fulfillments for our tracking number:** that makes a retried fulfil idempotent |
| Write (knowledge) | `inventoryItemUpdate` for HS code, origin and weight once the merchant confirms. Shopify stays the record, and Shopify Shipping would see the same facts |
| Webhooks in | `orders/updated`, `orders/cancelled`, `fulfillment_orders/*`, `app/uninstalled`. Signals only: a 15-minute reconcile re-reads open shipments regardless |
| Scopes | `read_orders`, `read_merchant_managed_fulfillment_orders`, `write_merchant_managed_fulfillment_orders`, `read_products`, `read_inventory`, `write_inventory`, `read_locations`; for UK labels also `write_orders` (`shippingLabelPurchase`) |

### API for CLIVE (`/api/v1`, bearer read/write keys, mirrors Returns): as built 2026-10-07

`shipping/api.py`. Keys `SHIPPING_CLIVE_READ_KEYS` / `SHIPPING_CLIVE_WRITE_KEYS`; none set, it
answers nothing. Every route calls the same service method as the screen.

```
GET  /capabilities                       read   what CLIVE can do
GET  /shipments?stage=&q=&limit=         read   stage: attention|ready|bought|printed|in_transit|delivered|all
GET  /shipments/{id}                     read   stage, payment, fulfilment, print, carrier, blockers, label
POST /shipments/{id}/preview             read   Shopify re-read + exact price; returns the basis
POST /shipments/{id}/buy                 write  {basis, idempotency_key, actor}: the purchase protocol
POST /shipments/{id}/print               write  first print through PrintNode, once
POST /shipments/{id}/reprint             write  {confirm: true, ...}: an extra copy
POST /shipments/{id}/tracking            read   read Shopify's carrier tracking now
GET  /events?since=&limit=               read   every order's history after `since`
```

The earlier plan's prepare/answer/choose-service/void actions and batch endpoints are not
exposed: CLIVE asks a person to answer questions in the screen, and bulk work stays a reviewed
screen action. The shared contract for CLIVE: `docs/sister-apps/CLIVE_OPERATIONS.md`.

### Webhooks out (signed like Returns)

- `shipment.ready`, `shipment.needs_attention`
- `shipment.label_purchased`, `shipment.purchase_failed`, `shipment.reconciliation_required`
- `shipment.fulfilled`, `shipment.tracking`, `shipment.delivered`
- `shipment.void_requested`, `shipment.voided`

## D. State machine

```
            ┌────────────── order cancelled / FO closed ───────────────┐
            ▼                                                           │
discovered ──► needs_attention ◄──► ready ──(buy-label: authorised, basis ok)──► purchasing
                  ▲   (one question)    ▲                                         │
                  │                     └──── purchase_failed (nothing paid) ◄────┤
                  │                                                               │
                  │                    reconciliation_required ◄─(pay outcome unknown)─┤
                  │                        │  read PaidDate                       │
                  │                        ├─ unpaid → purchasing (pay same order, once)
                  │                        └─ paid ──────────────┐                │
                  │                                               ▼                ▼
                  └── order edited after purchase ──── label_purchased ──(fulfillmentCreate)──► fulfilled
                       (attention: label may not match)      │     ▲          │ read-back ✓
                                                            │     └ fulfil retry (read first)
                                                            ▼
                                       fulfillment_failed (label bought, Shopify not updated)
fulfilled ─► in_transit ─► delivered            any purchased state ─► void_requested ─► voided
cancelled (before purchase; terminal)                                       └► void_rejected
```

**Provider operation ledger (one row per buy attempt), the money boundary:**

```
authorised ─► order_created (Parcel2Go order id+hash stored; no money)
           └► create_unknown (timeout creating) → safe: an unpaid order costs nothing;
              the next attempt makes a new order; the orphan is never paid
order_created ─► pay_sent ─► paid ─► documents_fetched ─► done
                         ├► refused (clear provider error: not charged) → failed; shipment back to ready
                         └► pay_unknown (timeout / 5xx / lost reply)
                              → reconcile: GET order PaidDate
                                   set   → paid (continue, no second pay)
                                   null  → stays pay_unknown until two reads ≥ 2 min apart both say
                                           unpaid; then abandoned (that order is NEVER paid) and the
                                           shipment returns to ready: a new buy needs a new preview
                                           and a new authorisation, and makes a new order
```

The invariants (tested):
1. At most one non-terminal buy operation per shipment, enforced by a unique index.
2. `paywithprepay` is called at most once per Parcel2Go order, ever. An order whose payment outcome was unknown is either confirmed paid or abandoned, never paid again.
3. An idempotency key replays the stored result.
4. `basis` must equal the current fingerprint (order lines, quantities, address, package, service, price) or the action is `STALE` and nothing is sent.

## E. UX specification (Polaris web components; compare with the Returns admin)

The same three screens as Returns: list, record, Setup. App nav has two items: **Shipping**, **Setup**.

**1. Shipping inbox** (`s-page` "International orders"; Returns' equivalent: the Returns list)
- **Purpose:** what can ship now, and what needs one answer.
- **Shows (as built, V1):** tabs **Needs attention · Ready to ship · Labels bought · Printed · In transit · Delivered · All**, then an `s-table` like Shopify's Orders: checkbox · Order · Purchased (Shopify's `createdAt` in the store's `ianaTimezone`: "Today at 13:06", "Yesterday at…", weekday, "7 Oct") · Customer (`Order.customer.displayName`; a guest or deleted customer shows the addressee) · Destination · Shipping (service, package under it) · Status · Label (Not printed / Printing… / Printed / Print failed). Newest order first. On a phone the table's list variant (`listSlot`) shows each order as a card.
- **Selection (V1):** ticking a row turns the list header into the selection bar in place: the header box (none → all; some or all → none), "N selected", Buy labels / Print labels, Clear. Nothing on the page moves. "Select all ready" re-reads the tab from the server; at most 100. The review re-checks every order and names any that changed since selection.
- **Primary:** none page-level; bulk actions live in the selection bar.
- **Secondary:** search by order or name.
- **Exceptions:** each row says the one thing ("HS code for Heavyweight Hoodie").
- **Hidden:** rates tables, providers, customs forms, settings.

**2. Shipment** (`s-page` "#2145 · Germany", back to inbox; Returns' equivalent: one return)
- `s-section` **Ship to:** the address. An `s-banner` appears only if a correction is proposed (original vs suggested, **Use suggested / Keep original**).
- `s-section` **Items:** title × qty, value; customs shown as `✓ Customs` with **Review** (opens details).
- `s-section` **Package:** "Standard CROOKS parcel · 38×28×8 cm · 0.84 kg", **Change**.
- `s-section` **Shipping:** Recommended — "DHL International · £11.24 · 2–4 days · Best balance of price and speed"; one line each for Cheapest and Fastest; **See all services** (modal).
- **Primary:** `s-button variant=primary` **Buy label — £11.24**. It opens an `s-modal` with the `will` lines (service, price, parcel, customs value, "Shopify will be marked fulfilled with tracking"), then **Buy label — £11.24**.
- **Needs-attention state:** the primary button is replaced by the single question card. For example: "Heavyweight Hoodie has never shipped abroad. HS code? Suggested 6110.20 (confirm)" with **Confirm / Change**. As built (V1): the HS code card has **Not sure of the code? Describe it**, which walks the official UK Trade Tariff from the merchant's words (and the product's title and type for what they leave open), asks one question at a time in the tariff's words, and shows a ten-digit code read back from the tariff with its official path and the reasons. **Use this code** fills the field; only **Save** confirms it, through the same product-facts path, with how it was chosen kept beside it (`shipping/commodity.py`). Or: "Where was Express Tee made?" with **China · Portugal · Other**. Answering remembers the fact and writes it to Shopify.
- **After purchase:** success banner "Label bought · Tracking H01… · Shopify fulfilled ✓", with **Print label** (primary; the 4×6 artifact), **Print customs documents**, and in the overflow **Reprint** and **Request void**.
- **Checking-purchase state:** "We're checking whether the label was bought. Parcel2Go stopped responding after the payment request. Don't buy again — CLIVE is checking so you're not charged twice." No buy button.
- **Hidden:** export reason (Sale), incoterm (DAP), contents JSON, provider ids (in Review / timeline).

**3. Setup** (Returns' equivalent: Setup)
- Ship-from (prefilled from the Shopify location, **Change**).
- Default package (name, dims, empty weight).
- Label size (4×6 · A4).
- Parcel2Go connection + PrePay balance.
- Optional IOSS / EORI numbers.
- A health check list (same pattern as Returns).

Nothing else.

**Interaction budget:**
- **Repeat order:** 2 clicks (Buy label → confirm), then Print.
- **New product:** + 1–3 answers, once ever.

## F. Happy path: two tees to Germany

**First order (CROOKS-2145):**
1. **Shopify:** the order is placed, and an OPEN fulfillment order is assigned to Bourne End with destination DE.
2. **Webhook/reconcile:** `orders/create` (or the 15-minute sweep) creates Shipment `shp_…` in `discovered`.
3. **prepare** reads the FO lines, then reads each variant's InventoryItem:
   - Express Tee / M has weight 220 g. Shopify has no HS code and no origin.
   - Knowledge has nothing yet, so the status is `needs_attention`.
   - The questions are "HS code for Express Tee (suggested 6109.10 — cotton T-shirt, confirm)" and "Where is Express Tee made?".
4. **George** opens the inbox. The row says "Needs 2 details". He opens it, confirms 6109.10 and taps **Portugal**:
   - Each answer is written to Knowledge (`merchant`, George, time).
   - `inventoryItemUpdate` writes the HS code and origin to Shopify.
   - The prepare re-runs and the shipment is `ready`.
5. **Package:** the default "Standard CROOKS parcel" (380×280×80 mm, 40 g). Items 2 × 220 g, so 0.48 kg total.
6. **Quote:** Parcel2Go `/quotes` with the parcel and DE address. CLIVE drops printer-free filtering (outbound has a printer) and services above the parcel limits. It scores price + speed + carrier reliability:
   - **Recommended:** DPD Classic £10.69, 2 days.
   - **Cheapest:** Evri Intl £6.60, 6–8 days.
   - **Fastest:** UPS Express.

   The quote is stored with its `basis`.
7. **Preview (Buy label):** `orders/verify` gives the exact price, £10.69. The `will` lines:
   - "Buy DPD Classic for £10.69 from Parcel2Go PrePay (balance £50.00)"
   - "Parcel 38×28×8 cm, 0.48 kg"
   - "Customs: 2 × Express Tee, 6109.10, Portugal, £74.00, reason Sale"
   - "Mark CROOKS-2145 fulfilled in Shopify with the tracking number"
8. **George** presses **Buy label — £10.69** (one key from the modal):
   - The ledger row is created as `authorised`.
   - `POST /orders` (unpaid; the Reference is the operation id) → `order_created`, with the id and hash stored.
   - `paywithprepay` → `paid`.
   - The label (4×6) and customs PDFs are fetched and stored as artifacts → `label_purchased`.
   - `fulfillmentCreate` with tracking → `fulfilled`.
   - The FO is read back: closed, tracking matches, so `verified` ✓.
9. George presses **Print label** and the 4×6 PDF opens. Phase 2 sends it straight to the printer.

**Second identical order (CROOKS-2151):** prepare finds the HS code and origin on Shopify's InventoryItem (written last time) and the weight on the variant. The package is learned: "2 × tee → Standard parcel" was confirmed once. The status is **ready immediately**, and the inbox shows "DPD £10.69 · Ready". George opens it and presses **Buy label → Buy label**, then **Print**. Nothing was typed.

## G. Failure walkthrough: the payment reply is lost

1. George presses Buy. The operation `op_7` is `authorised`, then `order_created` (Parcel2Go order 91234, no money yet), then `pay_sent`.
2. Parcel2Go charges £10.69, but the connection drops before the reply. The operation is `pay_unknown` and the shipment is `reconciliation_required`. The UI says "We're checking whether the label was bought… don't buy again" and **shows no buy button**.
3. George double-clicks anyway, or CLIVE retries with the same key: the key replays `op_7`'s state. With a new key, the unique index allows **one** open buy operation per shipment, so the API answers 409 "a purchase is being checked". **No second `POST /orders`, no second pay.**
4. The reconciler, within seconds and then on the 15-minute tick, runs `GET /orders?orderId=91234` and sees `PaidDate` set. The operation goes to `paid`, the documents are fetched, and the shipment goes to `label_purchased`, then `fulfilled` as normal. The timeline records "Payment confirmed by Parcel2Go read-back after a lost reply".
5. If `PaidDate` were null, CLIVE would not believe it at once: a payment still processing can read as unpaid for a moment. Only when two reads at least two minutes apart both say unpaid is the operation abandoned. Order 91234 is then **never paid**, and the shipment returns to Ready saying "You weren't charged". Buying again is a fresh preview and authorisation on a new order.

The sandbox proves why this matters: paying order 26633 twice charged twice.

## H. Implementation sequence (small reviewable stages)

1. **Stage 1 — domain core, no network. ✅ Built.**
   - `clive-shipping/shipping/{money,models,states,basis,store,ledger,providers/base,providers/fake,purchase}.py`
   - Tests: the state machine, the ledger invariants, and the lost-reply, refused, double-click, stale-basis and replay cases.
2. **Stage 2 — Shopify adapter + readiness + knowledge. ✅ Built (46 tests in total).**
   - `shopify.py` (discover FOs, read customs, `fulfillmentCreate` with read-first, `inventoryItemUpdate`), `readiness.py` (questions), `knowledge.py`, `packages.py`, fake Shopify.
   - Tests: missing HS/origin/weight, order edited after quote, cancellation, partial FO.
3. **Stage 3 — Parcel2Go provider. ✅ Built (90 tests in total).**
   - `providers/parcel2go.py`: quotes → normalised quotes, verify, create, pay-once, documents, tracking.
   - Every failure is sorted into refused / unavailable / uncertain, the three kinds the purchase protocol acts on. A lost reply to a POST is *uncertain*; a failed GET never is.
   - `scripts/sandbox_run.py` runs the 2-tee-to-Germany order end to end against the sandbox (the order is simulated in Shopify):
     - questions asked once, then ready;
     - preview, then buy, charged once;
     - label and invoices stored;
     - fulfilled and verified;
     - the same key replays;
     - the second identical order needs no questions and uses the learned package.
   - **Found in the sandbox and fixed:**
     - **Priced regions.** Without the region code, Parcel2Go quotes Tenerife as mainland Spain (£7.49 instead of £26.39) and Palermo as mainland Italy. Its `PostcodeRegex` is only a format check (`^.*$` for Madeira and Northern Ireland). CLIVE works the region out from the postcode (`REGIONS` covers the Canaries by island, Ceuta, Melilla, Madeira, the Azores, Sicily, Sardinia, NI, Isle of Man and the Highlands). It refuses rather than quoting the mainland if Parcel2Go stops listing a region. Madeira now quotes £15.99, and verify agrees.
     - **Country of origin.** The customs invoice printed "Madeira" for Portugal, because region rows share the ISO code. CLIVE now uses the main row, with clean names ("United Kingdom", "Spain").
     - **Address lines.** Parcel2Go requires a house number/name *and* a street. A single Shopify line is split the way it was written ("Torstrasse 12" → 12 / Torstrasse), never doubled.
     - **Duties wording.** The Canaries, Ceuta and Melilla are outside the EU VAT area, so they get the non-EU wording and never IOSS.
     - **Refusals at verify.** These now report Parcel2Go's reason (422) instead of "try again in a minute".
   - **Open (needs live, or a later stage):**
     - **Canaries recipient ID.** Parcel2Go requires the recipient's DNI/NIE. This will become an *address* question; the request field is still to be confirmed.
     - **4×6 output.** The sandbox returns 5-page A4 PDFs for every label format. The first live label will show the real 4×6 output and whether the invoices are separate.
     - **Courier tracking numbers.** The sandbox gives none, so CLIVE uses `P2G{line}`. Live numbers may arrive after purchase, which needs a later `fulfillmentTrackingInfoUpdate`.
     - **Void.** Parcel2Go has no void endpoint, so voids are manual.
   - **Verified in the sandbox on 2026-10-05: countries and customs paperwork.** Eight paid sandbox orders were booked from SL8 5AS: four to Berlin and four to New York. Every artifact was saved and measured.
     - **Country of origin:** `OriginCountry` takes a name. Swagger: "e.g. United Kingdom. This is not an ISO-3166 code." Parcel2Go prints the value verbatim: `PRT` appears on the commercial invoice as "PRT", and `Portugal` as "Portugal". CLIVE keeps ISO-2 internally and the adapter sends Parcel2Go's name.
     - **A true 4×6 label exists.** `GET /labels/{orderId}?detailLevel=Labels&labelMedia=Label4X6&labelFormat=PDF` returns 1 page of 100×150 mm (PNG: 787×1181 px, 200 dpi).
       - The order's `labels-4x6` link is *not* that: it mixes A4 advice and invoice pages with one 4×6 page.
       - `labels-a4-4x6` is all A4.
       - `label-a4-21` answers "OrderLine contains no labels".
       - The `invoice` link is Parcel2Go's own purchase invoice for the order, not a customs document.
       - `/invoices/{ref}` returns 500 in the sandbox.
     - **Paperless is per service.** `RequiresCommercialInvoice` is true for every international quote, so it can't be used to tell them apart. The reliable signals are `detailLevel=AdditionalDocuments` (404 when nothing is to be printed, otherwise N A4 pages, one per invoice copy) and the "Label Advice" page:

       | Service (sandbox) | Customs | Physically required |
       | --- | --- | --- |
       | DPD Classic (DE), DPD Pickup Air Classic (US) | Electronic: "Any required commercial invoices will be handled by us electronically" | 4×6 label only |
       | Landmark drop-off (US), OCS/UPS drop shop (US) | Electronic (same wording) | 4×6 label only |
       | Evri International ParcelShop (DE) | Paper | 4×6 label plus **3** A4 commercial invoices, in an envelope marked "Customs Documents" attached outside |
       | UPS Access Point (DE, US) | Paper | 4×6 label plus **4** A4 commercial invoices, same envelope |

     - **Each commercial invoice is one A4 page.** Terms printed are "DDU", including on the DPD service tagged `DDP`. DDP is an extra (`DeliveredDutyPaid`), not the tag.
     - **Consequence for the design:** documents are modelled separately (shipping label, commercial invoice, customs declaration, other), each with media type, page size, copies, must-print, attach-to-parcel and electronic. Electronic-customs services feel domestic: one 4×6 label goes to the JADENS. Paper services surface exactly one extra line, e.g. "Commercial invoice: print 3 copies (A4)". The paperwork requirement should also feed the rate recommendation in Stage 4. The sandbox is a stand-in, so the first live label will confirm all of this.
   - **Stage 3 completion (2026-10-05), in five commits:**

     1. *Admin API 2026-10.* Shipping pins `API_VERSION = "2026-10"`. All seven GraphQL documents
        validate against the 2026-10 schema (`scripts/validate_graphql.py`, Shopify AI Toolkit),
        and a test keeps the list complete.
     2. *Purchase-path fixes (from the type review), each with a test that fails without it:*
        - **Shipment saves are compare-and-set.** Before this, a refresh waiting on quotes could
          save its old copy over a purchase made meanwhile; reproduced as 2 charges.
        - **The order is placed from the quote authorised on the operation,** and only if the
          shipment still matches the authorised fingerprint.
        - **The label is recorded from that authorised quote.**
        - **Unexpected exceptions are contained:** after create, the operation fails with
          nothing paid; after pay, it becomes UNKNOWN and is read back; one broken operation no
          longer stops reconciliation of the others.
     3. *Documents.* `shipping_label`, `commercial_invoice`, `customs_declaration` and
        `other_documents`, each with media type, page size, pages, copies, must-print,
        attach-to-parcel and electronic. Each label has a customs mode (`electronic`, `paper`,
        `not_required` or `unknown`). The rest follows the sandbox evidence:
        - **The label is the genuine 4×6** (`/labels?detailLevel=Labels&labelMedia=Label4X6`).
        - **Paperless needs two views to agree:** additional documents 404, and `All` holding
          only the label and invoice. Any gap or disagreement is `unknown`, never paperless.
        - **The print plan** reads "Shipping label — 4×6 thermal / Customs — filed
          electronically" or "Commercial invoice — print 3 copies (A4)".
     4. *Countries and bad answers:*
        - Internal `Country` (ISO-2, ISO-3, name, Parcel2Go region); Parcel2Go's spellings only
          at the adapter.
        - The country list is cached for 7 days, with a stale copy used if Parcel2Go is down.
        - Unreadable JSON is uncertain for writes and unavailable for reads.
        - A missing or zero price is an error and is never paid (adapter and protocol).
        - A read-back without `PaidDate` is not counted as unpaid.
     5. *Sandbox proof* (`scripts/sandbox_proof.py`), run 2026-10-05. Orders 26682 (unpaid),
        26683 (DPD, reply lost), 26684 (Evri), 26685 (UPS); PrePay £9854.90 → £9813.57
        (= £11.93 + £6.60 + £22.80, each charged once). Labels measured 100×150 mm; the invoice
        files were 3 and 4 A4 pages, every page a commercial invoice.

     6. *Independent review (silent-failure hunter and test-coverage analyst), findings fixed
        in three commits:*
        - **Paid but unrecorded labels repaired:** reconcile records a paid label that a crash
          left unrecorded.
        - **Atomic transitions:** operation and shipment changes are one transaction.
        - **Operations are compare-and-set too:** a timer that gave up on an operation can never
          be followed by its stalled thread paying.
        - **In-flight payments are left alone** by the timer.
        - **A 2xx carrying errors is UNKNOWN** and read back; only a 4xx is a definite "no".
        - **"Unpaid" after a paid reply goes back to the read-back rule.**
        - **Long silences raise one alert**, never a payment.
        - **Customs evidence must be clear:** only Parcel2Go's 404 means none; paperless is
          confirmed by a second look ≥ 2 minutes later, and paperwork appearing late switches to
          paper with an alert.
        - **Service saves survive concurrent saves** (buy's fulfilment, answers, preview).
        - **Mutation checks:** every guard is caught by a test when removed.

        The sandbox proof was re-run after the fixes: orders 26686 (unpaid), 26687 (DPD, reply
        lost, paperless confirmed), then Evri and UPS; PrePay £9813.57 → £9772.24, again
        exactly one charge each.
   - **Parcel2Go endpoints used:**
     - `POST /auth/connect/token`
     - `GET /countries`
     - `POST /quotes`
     - `POST /orders/verify`
     - `POST /orders`
     - `POST /orders/{id}/paywithprepay?hash=`
     - `GET /orders?orderId&hash`
     - `GET /labels/{orderId}`, detail levels `Labels` / `AdditionalDocuments` /
       `CommercialInvoice` / `All`, PDF
     - `POST /orders/{id}/parcelnumbers`
     - `GET /prepay`
   - **Needs the first live label to confirm:**
     - that live services classify as in the sandbox (and DPD, Evri and UPS stay as observed);
     - live courier tracking numbers and when they appear (the sandbox gives none, so CLIVE
       uses `P2G{line}`);
     - that the real Label4X6 prints correctly on the JADENS through PrintNode;
     - whether `AdditionalDocuments` is ever briefly 404 right after payment on live (if so,
       the `All` cross-check makes it `unknown` and CLIVE retries, never paperless);
     - the Canaries DNI field, for Stage 4.

4. **Stage 4 — international fulfilment that feels domestic. ✅ Built (2026-10-05).**
   Five commits (4a–4e), 248 tests, plus a 36-check browser walk. The Stage 3 invariants and
   their tests are unchanged: fingerprint, compare-and-set, pay at most once, UNKNOWN never
   retried, reconcile first, purchase and reprint separate, documents decide paper vs
   electronic, `Label4X6`, integer minor units, durable state before side effects.

   - **Recommendation (`rates.py`, documented in the module).** Deterministic:
     1. "Reasonable" services promise delivery in ≤ 10 days; if none do, all count.
     2. The cheapest reasonable price sets the bar. Comparable = within max(£1.00, 10%).
        Nothing materially dearer is ever chosen silently.
     3. Among comparable services: the merchant's preferred carrier, then customs paperwork
        (electronic, unknown, paper), then price, then speed.
     4. Cheapest and Fastest are shown only when they differ (fastest only if actually quicker).
     Paperwork per service comes from this shop's own labels (service + destination, learned
     when customs settle), else the dated sandbox evidence, shown as "expected". The
     merchant's own choice is kept until that service stops being offered.
   - **Revalidation before preview and buy (`service._revalidate`).** The fulfillment order
     and item facts are re-read from Shopify; the fingerprint is recomputed from them (items,
     quantities, values, address, weights, package). Any difference refreshes the shipment and
     refuses: "Order changed — refresh required", nothing bought. Cancelled or closed: refused.
     Shopify unreachable: 503, nothing bought.
   - **Shopify after purchase.** Separate, recorded steps: label purchased → Shopify fulfilment
     created (its id kept; tracking goes in the same `fulfillmentCreate`) → tracking on the
     order, verified by reading the fulfillment order back. A failure shows "Label purchased —
     Shopify update needs retry"; the retry (button or timer) touches Shopify only (proved: the
     provider sees no call). An order closed in Shopify without this label's number is flagged,
     not blindly retried. A repeated identical failure doesn't grow the timeline.
   - **Readiness in merchant phrases (`views.py`).** Ready · "N details needed" (Missing
     weight / HS code / country of origin, Package needed) · Address needs attention · No
     available service · Provider unavailable · Purchase requires reconciliation · Label
     purchased — updating Shopify / Shopify update needs retry · Fulfilled. Inbox rows carry no
     provider ids, hashes or raw customs. Answers are saved to Shopify and to CLIVE; an answer
     unblocks every other order waiting on the same product at once. Origin is never guessed;
     an HS suggestion (from the shop's own products of the same type) needs confirmation.
   - **Printing (`printing.py`).** Print and reprint build jobs from stored files only: the
     4×6 label (label printer) and each must-print customs document with its copies (A4
     printer). The module imports no provider or purchase code (a test parses its imports),
     refuses an unbought order ("Printing never buys one"), and supports "reprint order 2145"
     and "print all ready labels". Jobs are plain data (printer role, file, copies), so a
     PrintNode sender can take them later; today the browser opens each PDF.
   - **Embedded admin (`admin.py`, `static/admin.html`).** Polaris web components and App
     Bridge; session token checked on every call (HS256, aud, dest, exp/nbf); the page may only
     be framed by Shopify admin. Inbox (Needs attention / Ready to ship / Labels bought, search,
     filter), shipment detail (problems first; questions answered in place; Recommended /
     Cheapest / Fastest and "See other services"; package Change; customs Review; "Buy label —
     £X" through the preview; label, tracking, Shopify steps, documents, print/reprint), Setup
     (ship-from, packages, Parcel2Go connection by reading the PrePay balance, 4×6, printer
     placeholder, customs defaults). One idempotency key per buy confirmation; after a lost
     reply "Check again" resends the same key. Rendered markup validated with the Shopify AI
     Toolkit (Polaris App Home v1).
   - **Verified in a browser (`scripts/ui_walk.cjs`, screenshots in
     `docs/shipping/stage4-screens/`).** Every state: inbox, ready, needs attention, customs
     missing → confirmed, quote selection, preview, purchase (double click charges once),
     purchase uncertain, Shopify failure and retry, paperless, paper, print, reprint, print all,
     stale preview, provider outage, no service, address, Setup, empty, 390 px.
   - **E2E through the embedded UI against the Parcel2Go sandbox** (fixture Shopify; no real
     store touched): CROOKS-2160, two tees to Berlin. Recommended Evri International
     Collection £6.65 (Evri ParcelShop £6.60 had 3 A4 copies; paperless DPD Direct £8.49 was
     outside the allowance). Bought once: PrePay £9772.24 → £9765.59. Paper customs detected
     (commercial invoice ×3, A4) and learned for that service; the genuine 4×6 label and the
     invoice printed from the stored files.

   - **Independent review (2026-10-05): code, silent failures, security, test coverage.** Fixed
     in one commit, each with a test and mutation-checked (removing any guard fails a test):
     - *Found by the reviews and fixed:* a Setup change (ship-from, EORI, VAT, duties terms)
       after a preview still bought; an order on hold in Shopify could be bought; the page
       could say "That didn't work" after a proxy error while the label was bought
       (bookkeeping after payment can no longer raise, and an unclear reply offers "Check
       again" with the same key); a fulfilment Shopify accepted but couldn't show yet was
       reported as "closed without this label"; a fulfilment could be created while the order
       was unreadable; a refusal wasn't read back; one broken shipment stopped the timer;
       prints were recorded before a window opened (now opened synchronously, copies shown,
       skipped labels reported); the fastest note said "more" for a cheaper option; a
       preview's new price didn't reach the services list; a service change could race a
       purchase.
     - *Security:* `iss` host must be the shop; malformed tokens are 401 not 500; the sandbox
       is the exact host; provider tracking links must be https; documents served only as
       PDF/PNG/JPEG with CSP sandbox; no raw provider text or order hash in messages; Setup
       field limits. Judged sound: HS256 pinned, aud/dest/exp/nbf, every API route
       authenticated, bearer-only (no CSRF), per-shop document lookup, `/dev` routes never in
       the app, live Parcel2Go never the default, CDN scripts without SRI (Shopify requires
       App Bridge unpinned).
     - *Left open, deliberately:*
       - an order moved to another location in Shopify (`fulfillmentOrderMove`) is reported
         as closed without the label; the message says what to do, but it isn't detected;
       - the timer re-quotes ready orders each minute, so if Parcel2Go's quote and exact
         prices differ, a preview left open over a tick comes back "changed";
       - staff appear as "Staff {id}" on the timeline (Returns looks names up);
       - `Purchases.reprint` (Stage 3) still exists beside `printing.py`; both read stored
         files only;
       - no `script-src` CSP or rate limit (staff-only, single shop);
       - Returns has the same missing `iss` check; changing Returns is the owner's call.

   - **Live-readiness gate.** The code is ready for one manually authorised live label. The
     environment is not yet: it needs the Stage 6 steps below, done by the owner on the
     server. No live credential is in the repo or this session.

     *Before (owner, on the server):*
     1. Deploy Shipping beside Returns (compose service, Caddy site block, a persistent
        volume for the SQLite file, a backup of it).
     2. Shopify app: client id and secret on the server; scopes for merchant-managed
        fulfillment orders, orders, inventory items (customs facts) and locations; app URL
        `/admin`. Open it from Apps in admin and confirm the inbox loads (this is where the
        session-token checks meet real tokens).
     3. `SHIPPING_SHOP_DOMAIN`, `SHIPPING_DEV_SKIP_ADMIN_AUTH` unset (false),
        `SHIPPING_TICK_INTERVAL_S=60`.
     4. A separate **live** Parcel2Go API credential, set only on the server
        (`SHIPPING_P2G_BASE_URL=https://www.parcel2go.com`, client id, secret). Keep the PrePay
        balance small (e.g. £30): it caps what any mistake can spend.
     5. Setup screen shows "Connected · Live"; confirm ship-from, the real mailer's size and
        empty weight, EORI/VAT if any, DAP.

     *The label (one, by hand):*
     6. One real international order (ideally a staff order to a known address in Germany),
        tees whose customs facts are answered once in the app.
     7. Read the preview: the service, the price (compare with Parcel2Go's site), the parcel,
        customs and DAP lines. Click Buy once.

     *Check afterwards:*
     8. PrePay dropped by exactly the price; Parcel2Go's dashboard shows one order.
     9. The order in Shopify is fulfilled with the tracking number, and the customer email
        went (or not, per Setup).
     10. Customs: paperless confirmed after ~2 minutes, or paper with the copies to print;
         matches Parcel2Go's label advice.
     11. The 4×6 label prints on the JADENS from the browser at actual size (no "fit to
         page"), and scans.
     12. The courier tracking number: the sandbox gave only `P2G{line}`. If live gives a
         courier number later, note when; updating Shopify with it is not built yet
         (`fulfillmentTrackingInfoUpdate`).

     *If anything is wrong:* there is no void API. Cancel the label in Parcel2Go's
     dashboard, and in Shopify cancel the fulfilment. CLIVE never re-buys on its own.

5. **Easyship, the second provider (2026-10-05).** Parcel2Go stays; both are asked for every
   order and their quotes are ranked together (`providers/multi.py`). Verified against
   Easyship's developer reference (version 2024.09, the OpenAPI definitions on each page):

   | Need | Easyship 2024-09 | Notes |
   | --- | --- | --- |
   | Quotes, exact price | `POST /2024-09/rates` (read) | price = `total_charge`; no rate id: a service is `courier_service.id`; `output_currency` = the shop's; shipping rules off |
   | Unpaid order | `POST /2024-09/shipments` | `courier_service_id`, `allow_fallback: false`, `buy_label: false`; 202 = created without a rate (never paid) |
   | Pay | `POST /2024-09/shipments/{id}/label` | the only call that spends; `printing_options` 4x6 label, A4 invoice |
   | Read back | `GET /2024-09/shipments/{id}` | paid = `label_paid_at` or `label_state` pending/generating/generated/printed/reported |
   | Documents | same, `?format=PDF&label=4x6&commercial_invoice=A4` | `shipping_documents[]` base64; an invoice "only if necessary": none = customs travels with the label |
   | Tracking | same (`trackings[]`, `tracking_page_url`) | a number that arrives later is filled in by the timer, then Shopify is updated |
   | Cancel | `POST /2024-09/shipments/{id}/cancel` | Easyship only (Parcel2Go has no void); merchant confirms; a lost reply is read back, never repeated |
   | Balance | `GET /2024-09/account/credit` | `available_balance`; shown in Setup |

   Hosts: `public-api.easyship.com` (token `prod_…`), `public-api-sandbox.easyship.com`
   (`sand_…`). Bearer token. 60 requests a minute. **No idempotency key is documented**, so the
   purchase ledger alone prevents a second payment, as for Parcel2Go. Recommendation: price
   dominates (only services within max(£1, 10%) of the cheapest compete); among those,
   preferred carrier, then tracked, then the merchant's hand-over preference, then paperwork,
   then price and speed. Read-only live comparison: `python -m shipping.tools.compare_rates 2142`.

   Request bodies follow Easyship's OpenAPI schemas exactly; the live API refuses anything else
   with a 400 (CROOKS-2142's first live quote failed on `"sku": null`). The fake Easyship in the
   tests validates every request against those schemas (`tests/easyship_requests_2024-09.json`,
   request schemas only). Rates need a `state` key on both addresses (origin: a string, may be
   empty; destination: may be null) and refuse null item fields; a line without a SKU is sent
   as `shopify-variant-<id>`. Creating a shipment also needs the sender's company, contact,
   phone and email and the customer's name, phone and email.

   **Only genuine facts block a label.** Shopify doesn't require a customer phone (or always an
   email), so the carrier contact is deterministic (`shipping/contacts.py`, both providers):
   the customer's phone/email if given, otherwise Setup → Ship from phone/email. It is booking
   data only, never written to Shopify; the detail screen shows a subtle "Carrier contact:
   store phone used…" note, not an error. Both are part of the purchase basis, so a change
   between Check price and Buy is stale. Only a missing Ship-from phone/email (or customer
   name) stops an Easyship booking, at Check price, before anything is sent. The Easyship
   credit balance is information only (a saved card may pay); only Easyship's own refusal of
   the label stops a purchase, with "Add credit or a payment method in your Easyship
   account" and nothing charged.

   **Dry run:** `python -m shipping.tools.dry_run [--probe-easyship]` refreshes every open
   international order, lists genuine blockers and runs Check price (Parcel2Go's is its full
   `/orders/verify`). `--probe-easyship` also creates each Easyship booking exactly as Buy
   would but without a label (no money moves), reports Easyship's verdict, and deletes it.

6. **Payment, tracking, lifecycle and the CLIVE API (2026-10-07).**
   - **Payment** (`shipping/payment.py`): one policy over `Order.displayFinancialStatus`
     (2026-10 enum: PAID and PARTIALLY_REFUNDED allow a new label; PENDING, PARTIALLY_PAID,
     REFUNDED, VOIDED, EXPIRED, AUTHORIZED and unknown block it). The payment is a blocker
     beside every other, read again in `_revalidate` before Check price and Buy (single, bulk
     and API), and a label already bought is kept with a warning.
   - **Tracking** (`shipping/tracking.py`): `Fulfillment.displayStatus`, `inTransitAt`,
     `deliveredAt`, `estimatedDeliveryAt`, read by the stored fulfilment id, else matched by
     tracking number (never the first fulfilment). Fulfilment SUCCESS is never delivery. The
     tick reads at most 25 due parcels: every 2h (1h out for delivery), twice a day after 5
     quiet days, never after delivery, 30 days without carrier news, or 90 days after the
     label; the next check is stored on the shipment.
     Seen live (2026-10-07): UK Royal Mail reaches DELIVERED in Shopify; Channel Islands Royal
     Mail stops at IN_TRANSIT (handed to Guernsey/Jersey Post), so Shopify alone can't say those
     arrived. No carrier integration is added for that.
   - **Journey** (`views.journey_view`): the order page shows Order placed (Shopify
     `Order.createdAt`) → Label bought → Label printed → In transit → Out for delivery →
     Delivered, each with its time, plus the carrier's own updates (`Fulfillment.events`, newest
     30: status, time, message, city/country) and where the parcel was last seen. Each new scan
     is also a `carrier_scan` history entry at the scan's own time. Live Royal Mail events carry
     a message and a country only (no city, no means of transport), so nothing more is shown.
     History names the staff member (session-token exchange, as Returns) instead of their id.
   - **Lifecycle** (`shipping/lifecycle.py`): Needs attention, Ready to ship, Labels bought,
     Printed (PrintNode reported done, or opened in the print view; `PhysicalPrinting.summary`), In transit, Delivered, All;
     derived on every read. Ready selects for bulk Buy, Labels bought for bulk first Print;
     the batch preview enforces both. The detail keeps Payment, Fulfilment, Print and Carrier
     apart.
   - **API for CLIVE**: above.
7. **Still not built:** webhooks out and `shipping-ctl` (CLIVE polls `/events` instead).
8. **Stage 6 — deploy and pilot:**
   - Shopify app toml, compose service, Caddy site block, separate Parcel2Go credential;
   - pilot behind an order-number allowlist (like Returns);
   - one real label to Germany (see the live-readiness gate below).

9. **UK labels through Shopify Shipping (2026-10-09).** Off unless
   `SHIPPING_DOMESTIC_LABELS=shopify`; international behaviour is unchanged.
   - **Which orders.** Destination country = the ship-from country (GB to GB). The Channel
     Islands and the Isle of Man keep their own country codes and stay international. A UK
     parcel asks no HS code or origin and gets no duties terms; weight, package, address,
     payment, hold and second-label checks apply as before.
   - **Which service** (`domestic.py`). The order's checkout shipping line
     (`Order.shippingLine.title`, read with each fulfilment order) through
     `SHIPPING_DOMESTIC_SHIPPING_LINES="Tracked 24=24; Tracked 48=48"` (case and spacing
     ignored; a bad entry stops the service starting). The store's lines, read from its last
     ~100 orders on 2026-10-09: "Tracked 24", "Tracked 48", and none on manual/draft orders.
     Unmapped or missing: Needs attention, "Which service: Tracked 24 or Tracked 48?", answered
     per order by a person. Each service needs Shopify Shipping's code
     (`SHIPPING_SHOPIFY_TRACKED_24_RATE` / `_48_RATE`, "carrierCode/serviceCode"); without it
     the order waits ("code not set"). A delivery method changed after the preview is stale.
   - **The provider** (`providers/shopify_shipping.py`), behind the same ledger and protocol.
     `quotes` gives the one mapped service with `price_known=False`; the ledger skips its amount
     checks (owner-accepted) and the preview says the price is set by Shopify Shipping.
     `create_order` writes the exact request to `label_purchases` (fulfilment order, shipping
     time ten minutes ahead, the custom package and empty weight, total weight,
     `preferredRateSelection`, `notifyCustomer`); nothing is sent. `pay` sends
     `shippingLabelPurchase` once from a path that never retries
     (`GraphQLShopify.purchase_label`): connect failure, 429 or THROTTLED = not sent; other 4xx
     or a field error = refused; timeout, reset, 5xx or an unreadable body = UNKNOWN. The result
     id is saved before polling; `node(id)` is polled to PURCHASED / PURCHASE_FAILED within 60 s
     (Shopify's advice), else UNKNOWN. userErrors and PURCHASE_FAILED are refusals (nothing
     bought, the order is ready again). The adapter refuses to send a row already sent.
   - **UNKNOWN.** With the result id: read back (PURCHASED = bought; PURCHASE_FAILED = settled
     at once; pending = wait, alert after an hour, never given up). Without it (lost reply): the
     fulfilment order is read; a tracking number that wasn't on it before sending (recorded with
     the request) is the label, adopted, but its file can't be fetched, so staff are told to
     print it from Shopify admin and Print is not offered. A fulfilment order Shopify no longer
     shows can't tell either way and stays unknown. Nothing found for Shopify's 10-minute settle
     window (two reads) is not taken as "not bought": the order waits in Needs attention ("Check
     Shopify for a label") until a person has looked in Shopify admin and says there's none.
     The same applies when Shopify refuses because another purchase is running for the order
     (JOB_NOT_ENQUEUED, PURCHASE_IN_PROGRESS). A purchase whose "sending" mark was never saved
     was never sent, and settles at once.
   - **Shopify's answer.** A result id means the purchase started, whatever else the answer
     carries. A field error is a refusal only when Shopify never ran the mutation (no `data`,
     ACCESS_DENIED, MAX_COST_EXCEEDED); an error inside Shopify (INTERNAL_SERVER_ERROR) is
     UNKNOWN.
   - **After buying.** Each `shippingDocument` (LABEL, CUSTOMS_FORM) is fetched server-side
     over https (streamed, capped at 10 MB), without the app token; a file that isn't a readable
     PDF is never stored and is fetched again later. A label is stored and measured. Only a portrait 4×6 PDF goes to
     the label printer; any other size (US Letter, A4, landscape) is never scaled: PrintNode
     refuses with the reason and the print view opens the file whole with the same note. ZPL is
     kept and said to be unprintable here. CLIVE reads the order first: if Shopify put the
     tracking on the order itself, that fulfilment is adopted; if not within two minutes, CLIVE
     adds one (read-first, as always).
   - **Also:** UK collection and local-delivery orders (`deliveryMethod.methodType` not
     SHIPPING) are left to Shopify. A person's service choice holds only while the order keeps
     the delivery method it was made for. Turning UK labels off never hides an order whose label
     may have been paid for, and the provider is still built to finish it. The ledger lets a
     quote skip the amount checks only when its provider says it can't price before buying.
   - **Verified:** 91 new tests (fake Shopify Shipping that loses replies, stays pending, fails
     and refuses; HTTP-level one-POST and error-classification tests; an independent review's
     findings, each with a test; each guard removed once and a test failed); the admin in a real
     browser (`scripts/ui_walk_uk.cjs`, 38 checks, desktop and phone,
     `docs/shipping/uk-screens/`); `M_SHIPPING_LABEL_PURCHASE` and `Q_SHIPPING_LABEL_PURCHASE`
     validated at 2026-10.
   - **Not verifiable without a real purchase:** whether a label bought this way creates the
     Shopify fulfilment itself (the docs don't say; labels bought in Shopify admin do, seen
     live as LABEL_PURCHASED); the Tracked 24 / 48 codes; the label file's size and format
     (they follow the store's label settings); whether the document links need anything beyond
     a plain GET; how long purchases really take.

## I. Test plan

**Deterministic offline tests** (fake Parcel2Go and fake Shopify that behave like the real ones, including the double charge on re-pay):

| Area | Cases |
| --- | --- |
| Money | integer minor units only; float JSON converted through Decimal; currency never mixed |
| Purchase | happy path · lost pay reply → reconcile paid (no second pay) · lost reply → unpaid (confirmed twice, 2 min apart) → abandoned, never paid · refused (balance) → not charged → a later buy makes a fresh order · create timeout → orphan never paid · double click (same key replays; new key → 409) · CLIVE retry · two workers racing (unique index) |
| Basis / stale | order line or qty changed after preview · address changed · package changed · price moved on verify → STALE, nothing sent |
| Shopify | fulfil fails after purchase → `fulfillment_failed`, retry reads first, never duplicates · order cancelled before purchase → `cancelled` · cancelled after purchase → attention + void request · partial FO quantities |
| Readiness | HS missing · origin missing · weight missing · restricted item (Parcel2Go prohibited check) · destination needing unavailable data (e.g. a tax ID) → one question each; answers persisted and written back |
| Rates | none returned → attention · selected service gone on requote → recommend again with a new preview |
| Artifacts | reprint returns the same bytes and never calls the provider |
| Void | request → manual → confirm; void rejected → stays purchased with a note |
| Webhooks | Shopify HMAC, Parcel2Go signature, replay ignored, a missing webhook covered by reconcile |
| Tenancy | every query scoped by shop; a cross-shop id returns 404 |

**Controlled sandbox plan:** quote DE/US/AU, then create, pay, documents and read-back. Then force a pay re-read by killing the client between pay and reply (a proxy timeout), and check the reconcile path against the real `PaidDate`.

## J. Scope guard: not building

Warehouse/inventory, ERP, automation-rule builder, workflow canvas, carrier contract portal, branded tracking pages, insurance marketplace, analytics suite, returns (Returns owns it), 3PL, multi-warehouse optimisation, enterprise permissions, many carriers, settings beyond the one Setup page, SaaS billing (Phase 4), UK services beyond Royal Mail Tracked 24 / 48 (UK labels themselves are built: H, stage 9), autonomous purchasing (the authority policy hook exists; v1 always asks).

## Open product questions for George

1. **DAP or DDP for the EU after the €3 duty change?** v1 assumes **DAP**: the customer may pay duty or VAT on delivery. If CROOKS has an IOSS number, CLIVE can send it for EU orders under €150.
2. **Default parcel:** the real dimensions and empty weight of the CROOKS mailer(s).
3. **Where are the products made?** Answered once per product, as orders arrive. A list up front speeds the first week.
4. **Label printer:** 4×6 thermal, or A4?
