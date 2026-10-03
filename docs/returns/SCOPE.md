# CROOKS Returns: scope (2026-10-03)

This replaces AfterShip Returns with a returns and exchanges system that CROOKS owns: a
customer portal on crooksldn.com, a small backend service, Shopify's own Returns API as the
record, Royal Mail Click & Drop for labels, and an API that CLIVE can read and act through.

## Why replace AfterShip

- Customisation is held back behind paid tiers, and the portal does not sit in the site the
  way we want.
- Approving a return without a label is impossible: AfterShip tells the customer "you'll be
  given a label later" and leaves it there.
- CLIVE cannot see into it: it cannot tell a refund from an exchange, or what an exchange is
  for (size up, size down, a different item).
- The settings are hard to work through for the staff using it.

What AfterShip does well, and we keep: moving the money (refunds, credit) and the
return-saving offers.

## Decision: build in code, not on Base44

The portal is one small part of this. Most of the work is the backend: the Shopify Returns and
Exchanges API, refunds and store credit, Click & Drop labels, webhooks, the policy rules and
an API for CLIVE. Base44 hosts its own app and database on its own domain, so a Base44 portal
would sit outside the theme just as AfterShip does now, the data would be held in another
vendor's database, and the code would not be in this repository, where CLIVE's reviewed,
evidence-checked changes happen.

Base44 is still useful as a sketchpad: a quick way to try how the portal screens look and
read before they are built in the theme. Nothing from it ships.

## Architecture

```
crooksldn.com/pages/returns          theme section in this repo (bone/ink/caution yellow,
        |                            Archivo Narrow, the mono face), same look as the site
        v
crooksldn.com/apps/returns/api/*     Shopify app proxy: same domain, signed by Shopify
        |
        v
crooks-returns service               rules, state machine, audit log, CLIVE API
   |-- Shopify Admin API             Return / exchange / refund / store credit: the record
   |-- Royal Mail Click & Drop API   return labels and tracking
   |-- Resend (or Shopify notices)   branded customer emails
   `-- Postgres                      what Shopify does not hold: reason detail, photos,
                                     offers made and accepted, label choice, audit trail
        ^
        |
CLIVE                                reads every return; proposes actions; the owner
                                     authorises; the service executes and re-reads
```

- **Shopify is the system of record.** Each request becomes a real Shopify `Return` on the
  order (`returnRequest` / `returnCreate`, with `exchangeLineItems` for exchanges, confirmed by
  `returnProcess`, which also creates the exchange's fulfilment order). Returns therefore show
  in the Shopify admin, in Shopify's reports and to CLIVE's existing Shopify reads, and the
  history survives if the service is ever replaced.
- **A separate service, not part of CLIVE.** The portal takes public traffic; CLIVE runs
  behind Tailscale with owner-only writes. Keep the two trust boundaries apart and let CLIVE
  use the service through its API.
- **Stack:** Python/FastAPI and Postgres to match `crooks-assistant`, as a single-store custom
  app (the same `client_credentials` set-up CLIVE already uses) with an app proxy. Hosting
  needs better uptime than a single home server, because customers use it.

## Customer flow

1. **Find the order:** order number plus one of email, postcode or phone. Normalise inputs
   (case, spaces, `#`), allow a few attempts per order and per IP, then lock for a while.
   A signed link in the delivery email skips this step.
2. **Choose items:** only lines that can be returned (Shopify `returnableFulfillments`), and
   only within the window. Excluded items (final sale, underwear, gift cards) are shown with
   the reason, not hidden.
3. **Reason:** too small, too big, not as pictured, quality, faulty or damaged, wrong item,
   changed my mind. Faulty and wrong item ask for a photo.
4. **Resolution:** offers are ranked by what saves the sale (see below). Every option shows
   its cost plainly, for example "Refund to card: £45.00 minus £3.95 return postage".
5. **Postage:** a Royal Mail label or QR code, instructions to send it yourself, or no return
   needed, depending on the rule.
6. **Status page:** one link showing requested, approved, label, in transit, received,
   refunded or exchange shipped, with tracking.

## Return-saving offers

| Lever | When it is offered |
| --- | --- |
| Free size exchange, shown first, with only in-stock sizes | Too small / too big |
| Exchange for a different item, paying or refunding the difference | Any reason except faulty |
| Store credit plus a bonus (for example +10%), instant once tracking shows a scan | Ahead of a refund |
| Keep it with a partial refund (for example 20–30%) | Low-value items, or when return postage costs more than the margin |
| Discount code on the next order | Refund chosen |
| Return postage fee taken from the refund; free for exchanges and credit | Changed my mind |
| Free label, no fee, priority handling | Faulty, wrong item |
| Fit note for the item ("runs small: most people size up") | Shown before ordering, from return data |

**UK law limits these offers.** For online sales the customer can cancel within 14 days of
delivery (Consumer Contracts Regulations) and must be refunded within 14 days of the goods
coming back. A return postage fee is allowed only if the policy says so in advance. Faulty
goods (Consumer Rights Act) are returned free, with a full refund within 30 days. Offers can
come first, but a refund to the original payment method must always be available inside
those rights. Check the final wording with whoever writes the returns policy.

## Staff side, and the fix for AfterShip's label problem

Approving a return and choosing its postage are separate decisions:

- **Approve and create a label now** (Click & Drop, sent to the customer as a PDF or QR code)
- **Approve, customer sends it themselves** (send the address, ask for a tracking number)
- **Approve, no return needed** (refund or credit without the item coming back)
- **Approve, label later:** an explicit `awaiting_label` state with a timer, shown on the
  queue and to CLIVE, never left hanging silently
- **Decline**, with a reason the customer sees

Rules pick a default (for example: faulty means a free label now; changed my mind means the
customer sends it themselves or pays the label fee), and staff or CLIVE can override it.

When the exchange is sent is a setting: on approval, on the return's first carrier scan
(recommended), or on receipt and inspection.

## Click & Drop

- **Generating labels through the API requires a Royal Mail Online Business Account (OBA).**
  Pay-as-you-go Click & Drop accounts get `403 Feature not available`. Confirm which account
  CROOKS has: it decides whether labels can be automatic.
- Use Royal Mail Tracked Returns. Customers can show a QR code at a Post Office, so they do
  not need a printer.
- Tracking numbers are written back onto the Shopify return (`reverseDeliveryCreateWithShipping`)
  so tracking events move the state forward: in transit, delivered back to us.
- Fallback without OBA: staff create the label in Click & Drop and upload it, or paste its
  tracking number, on the return. This is already better than AfterShip, because the state is
  explicit.

## CLIVE integration

Every return is visible, every action is a reviewed mutation, and every result is checked by
reading it back. This follows CLIVE's rule:
`PROPOSED ≠ AUTHORISED ≠ STARTED ≠ COMPLETED ≠ VERIFIED`.

**Read**

```
GET /api/v1/returns?status=&reason=&since=
GET /api/v1/returns/{id}
GET /api/v1/orders/{order_name}/returns
GET /api/v1/stats?from=&to=            return rate by product and size, offer take-up
```

A return reads like this:

```json
{
  "id": "ret_8F2K", "shopify_return_id": "gid://shopify/Return/123",
  "order": "#1939", "customer": "…", "status": "awaiting_label",
  "lines": [{ "sku": "YARD-JEAN-M", "qty": 1, "reason": "too_small",
              "resolution": { "type": "exchange", "to_sku": "YARD-JEAN-L",
                              "direction": "size_up", "in_stock": true } }],
  "offers_shown": ["exchange_free", "credit_plus_10", "refund_minus_fee"],
  "offer_taken": "exchange_free",
  "postage": { "mode": "label_later", "carrier": null, "tracking": null },
  "money": { "refund": 0, "credit": 0, "fee": 0, "difference_due": 0 },
  "exchange_order": null,
  "timeline": [{ "at": "…", "state": "requested", "actor": "customer" }]
}
```

**Act:** each action has a `preview` (what will happen, in pounds, before anything moves) and
an `execute` call that takes an idempotency key and the authorising actor, then returns the
new state together with the Shopify IDs that prove it.

```
POST /api/v1/returns/{id}/approve          {postage: label_now|self_ship|no_return|label_later}
POST /api/v1/returns/{id}/decline
POST /api/v1/returns/{id}/label            create or attach a label later
POST /api/v1/returns/{id}/receive          with an inspection result
POST /api/v1/returns/{id}/refund | /credit
POST /api/v1/returns/{id}/exchange         create, or change the size or item
POST /api/v1/returns/{id}/note
```

**Push:** signed webhooks to CLIVE for `return.requested`, `return.approved`,
`label.created`, `return.awaiting_label.overdue`, `return.in_transit`, `return.received`,
`refund.issued`, `credit.issued`, `exchange.created` and `exchange.shipped`.

Keys are scoped: CLIVE gets read access first, and write access only once its authorisation
cards for returns exist.

## Phases

**0. Decisions and accounts (a few days)**
- Policy: return window (counted from delivery), fee amount, credit bonus, sale-item rules,
  when exchanges are sent, international returns.
- Royal Mail: is the account OBA, and is Tracked Returns enabled?
- Shopify app with app proxy; scopes `read_returns` and `write_returns` added to the existing
  set.
- AfterShip: export open returns and history.

**1. MVP to replace AfterShip**
- Portal in the theme: find the order, choose items, give a reason, pick a resolution
  (refund, credit with bonus, size exchange), status page.
- Policy rules and the return window; Shopify `Return` records; native exchanges.
- Staff queue with the five approval options; labels uploaded by hand or pasted as a tracking
  number.
- Receive and inspect, then refund, credit or confirm the exchange; branded emails.
- CLIVE read API and webhooks.
- Run alongside AfterShip; switch the returns link; retire AfterShip once its open returns
  close.

**2. Automation**
- Click & Drop labels and QR codes (if OBA); tracking moves the state forward and sends
  exchanges.
- Postage fee, keep-it offers, photo evidence for faulty items.
- CLIVE write actions through preview, owner authorisation, execute and verify.

**3. Revenue and insight**
- Exchange for a different item with the price difference paid or refunded; shop with the
  credit inside the portal.
- Fit insight fed back to product pages; flags for frequent returners; instant exchanges for
  trusted customers.

## Decisions (owner, 2026-10-03)

| Question | Decision | Where it lives |
| --- | --- | --- |
| Return window | 14 days from delivery (UK law). Faulty, wrong or misdescribed items: 30 days. | `RETURNS_WINDOW_DAYS`, `RETURNS_FAULT_WINDOW_DAYS` |
| Change-of-mind postage | The customer sends it themselves, or uses a Royal Mail label at Click & Drop cost with no premium, taken off the refund. | `RETURNS_RETURN_LABEL_COST_PENCE` |
| Keeping the value | Store credit and exchanges get free return postage. | `policy.quote` |
| Credit bonus | £25 tee credits £30; £60 item credits £70. Built as bands: +£5 under £40, +£10 from £40. **The £40 boundary needs confirming.** | `RETURNS_CREDIT_BONUS_BANDS` |
| When an exchange ships | When the return arrives back. | the `receive` action |
| Sale items | Same as full price. The 14-day right covers sale items, so there is no separate rule. Only products tagged `non-returnable` (sealed hygiene goods, personalised items) are limited to faulty returns. | `RETURNS_NON_RETURNABLE_TAGS` |
| Royal Mail account | Online Business Account (to confirm with the first live label). | `RETURNS_CLICKDROP_*` |
| Staff work | Both: the Shopify admin (returns are native Shopify returns, and changes made there sync back) and CLIVE (the API). | `/webhooks/shopify`, `/api/v1` |

## Built (first version, 2026-10-03)

- `crooks-returns/`: the service (rules, verification, workflow, Shopify, Click & Drop, CLIVE
  API, webhooks), 39 offline tests. Every Shopify document was validated against the Admin
  2026-10 schema.
- Theme: `sections/returns-portal.liquid`, `assets/returns-portal.js` and
  `templates/page.returns.json`. Driven end to end in a browser at phone and desktop widths
  against the fake store.
- Not done yet: deployment, the Shopify app and app proxy, Click & Drop credentials, a staff
  screen beyond the Shopify admin and CLIVE, an exchange for a different product, and keep-it
  offers. The setup steps are in `crooks-returns/README.md`.
