# CLIVE Shipping: design and Phase 0 findings

**Status (2026-10-05):**
- **Stage 1 built:** domain, state machine and the pay-once purchase protocol.
- **Stage 2 built:** Shopify discovery, readiness, remembered answers, packages, duties and fulfilment with read-back.
- **Stage 3 built:** the Parcel2Go provider, run end to end against the Parcel2Go sandbox.
- Nothing is deployed.

## Owner decisions (2026-10-05)

| Topic | Decision | Where it lives |
| --- | --- | --- |
| Duties | No IOSS today. Ship DAP: the customer may pay import VAT, duty and fees on arrival, and CLIVE says exactly that and never claims prepaid. IOSS/DDP is a per-shop setting for later, not a constant. | `DutiesPolicy` in `ShopConfig`; `duties.terms()` |
| Packaging | Never invented. The first real package is entered once, when the first shipment needs it, and remembered. Multiple presets are supported; the package used for a mix of products is learned on purchase; inference comes later. | `PackagePreset`, `packages.plan()`, `package_choices` |
| Country of origin | Never inferred or bulk-filled. Asked once per product when a real shipment needs it and Shopify has none. Saved to every size's InventoryItem in Shopify (the record) and remembered here with who and when. Not asked again unless Shopify's value changes. | `readiness`, `facts`, `inventoryItemUpdate` |
| Printer | JADENS roll-fed thermal on a Windows laptop via PrintNode. Prefer 4×6 in (~100×150 mm) labels. Printing comes later, but the label is stored once as an artifact (`label_4x6` first). Reprint renders that stored file and has no path to a purchase. | `Label.artifacts`, `Purchases.reprint()` |
| Setup | Progressive: nothing catalogue-wide up front. A fact is asked only when a real shipment needs it. | readiness questions |

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
| `shippingLabelPurchase` (Shopify Shipping, Admin API **2026-07+**) buys a label for a fulfillment order, async (`PENDING_PURCHASE → PURCHASED/FAILED`), customs taken from Shopify's product data, needs `write_orders` + fulfillment-order scope + staff `buy_shipping_labels` + Shopify Shipping ToS. **No idempotency key, no app-callable rates query, no void mutation, no FedEx.** | [docs] shopify.dev 2026-10 reference | Strong future option (native, merchant pays Shopify, no reseller issue), but it cannot show a price before purchase today, which breaks "Buy label — £X". Kept behind the provider port |
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
| Scopes | `read_orders`, `read_merchant_managed_fulfillment_orders`, `write_merchant_managed_fulfillment_orders`, `read_products`, `read_inventory`, `write_inventory`, `read_locations` |

### API for CLIVE (`/api/v1`, bearer read/write keys, mirrors Returns)

```
GET  /shipments?state=ready|needs_attention|open|done&since=   GET /shipments/{id}
GET  /orders/{order}/shipment           GET /provider (balance, connected)   GET /health
POST /shipments/{id}/prepare            (read Shopify, recompute readiness, no money)
POST /shipments/{id}/actions/{action}/preview      → {will[], money, service, basis}
POST /shipments/{id}/actions/{action}              {params, basis, actor, idempotency_key}
POST /batches/buy-label/preview         {shipment_ids} → per-shipment will/basis + total
```

Execute returns `{from, status, verified, error, evidence, shipment}`. Each batch member is executed separately, with its own key and basis, so a partial failure is exact.

**Actions:**

| Action | Spends money? |
| --- | --- |
| `buy-label` | **yes** |
| `fulfil` (retry the Shopify write) | no |
| `answer` (one question: HS / origin / weight / address / package) | no; writes knowledge and Shopify |
| `change-package` | no |
| `choose-service` | no |
| `requote` | no |
| `reprint` | **no**; renders an existing artifact only |
| `request-void` | no (manual at Parcel2Go in v1); `confirm-void` after the merchant cancels there |
| `note` | no |

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
- **Shows:** tabs **Ready (n) · Needs you (n) · Shipped today · All**, then an `s-table` with Order · Destination (flag + country) · Package · Shipping (recommended carrier + £) · Status badge (`Ready` success, `Needs 1 detail` attention, `Checking purchase` info, `Label bought` neutral).
- **Primary:** none page-level in v1. Phase 2 adds "Buy N labels — £X" for the Ready tab.
- **Secondary:** search by order or name.
- **Exceptions:** each row says the one thing ("HS code for Heavyweight Hoodie").
- **Hidden:** rates tables, providers, customs forms, settings.

**2. Shipment** (`s-page` "#2145 · Germany", back to inbox; Returns' equivalent: one return)
- `s-section` **Ship to:** the address. An `s-banner` appears only if a correction is proposed (original vs suggested, **Use suggested / Keep original**).
- `s-section` **Items:** title × qty, value; customs shown as `✓ Customs` with **Review** (opens details).
- `s-section` **Package:** "Standard CROOKS parcel · 38×28×8 cm · 0.84 kg", **Change**.
- `s-section` **Shipping:** Recommended — "DHL International · £11.24 · 2–4 days · Best balance of price and speed"; one line each for Cheapest and Fastest; **See all services** (modal).
- **Primary:** `s-button variant=primary` **Buy label — £11.24**. It opens an `s-modal` with the `will` lines (service, price, parcel, customs value, "Shopify will be marked fulfilled with tracking"), then **Buy label — £11.24**.
- **Needs-attention state:** the primary button is replaced by the single question card. For example: "Heavyweight Hoodie has never shipped abroad. HS code? Suggested 6110.20 (confirm)" with **Confirm / Change**. Or: "Where was Express Tee made?" with **China · Portugal · Other**. Answering remembers the fact and writes it to Shopify.
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
4. **Stage 4 — rates + recommendation.**
   - `rates.py`: recommended / cheapest / fastest, carrier reliability table, parcel limits.
5. **Stage 5 — API + webhooks + reconcile + notifier + `shipping-ctl`**, mirroring Returns.
6. **Stage 6 — Admin UI** (App Bridge + Polaris web components): Inbox, Shipment, Setup, with browser screenshots.
7. **Stage 7 — deploy and pilot:**
   - Shopify app toml, compose service, Caddy site block, separate Parcel2Go credential;
   - pilot behind an order-number allowlist (like Returns);
   - one real label to Germany.

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

Warehouse/inventory, ERP, automation-rule builder, workflow canvas, carrier contract portal, branded tracking pages, insurance marketplace, analytics suite, returns (Returns owns it), 3PL, multi-warehouse optimisation, enterprise permissions, many carriers, settings beyond the one Setup page, SaaS billing (Phase 4), domestic UK labels (Shopify's own flow is fine for them; revisit after Phase 2), autonomous purchasing (the authority policy hook exists; v1 always asks).

## Open product questions for George

1. **DAP or DDP for the EU after the €3 duty change?** v1 assumes **DAP**: the customer may pay duty or VAT on delivery. If CROOKS has an IOSS number, CLIVE can send it for EU orders under €150.
2. **Default parcel:** the real dimensions and empty weight of the CROOKS mailer(s).
3. **Where are the products made?** Answered once per product, as orders arrive. A list up front speeds the first week.
4. **Label printer:** 4×6 thermal, or A4?
