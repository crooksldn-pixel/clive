# CLIVE and the sister apps: one contract for Shipping and Returns

CLIVE operates CROOKS Shipping and CROOKS Returns through their `/api/v1`, never through their
screens and never with logic of its own. Each app's API calls the same service methods as its
screen, so a label bought or a return approved by CLIVE goes through exactly the checks a click
does. This page is the shared shape; the details are in `clive-shipping/shipping/api.py` and
`docs/returns/BRIEF_CLIVE.md`.

## Same shape in both

| | Shipping | Returns |
| --- | --- | --- |
| Base | `https://returns.crooksldn.com/shipping/api/v1` | `https://returns.crooksldn.com/api/v1` |
| Keys (server `.env`) | `SHIPPING_CLIVE_READ_KEYS`, `SHIPPING_CLIVE_WRITE_KEYS` | `RETURNS_CLIVE_READ_KEYS`, `RETURNS_CLIVE_WRITE_KEYS` |
| Discover | `GET /capabilities` | `GET /capabilities` |
| What needs a person | `GET /shipments?stage=attention` | `GET /returns?status=requested` (and `attention` on each) |
| One thing | `GET /shipments/{id}` | `GET /returns/{id}` |
| Price / preview (changes nothing) | `POST /shipments/{id}/preview` (read key) | `POST /returns/{id}/actions/{a}/preview` (read key) |
| Act (write key) | `POST /shipments/{id}/buy` · `/print` · `/reprint` | `POST /returns/{id}/actions/{a}` |
| What changed | `GET /events?since=` | `GET /events?since=` |

- **Keys:** `Authorization: Bearer <key>`. A write key can read. No keys set means the API answers nothing.
- **Idempotency:** every act takes an `idempotency_key`. Repeating it replays the first outcome and never repeats a payment, label, refund or print. In Returns, the same key with different params is refused.
- **Failures** are an HTTP status plus words:
  - Shipping: `{"detail": {"message", "code"}}`
  - Returns: `{"detail": "..."}`
  - Shipping codes include `payment`, `stale`, `not_authorised`, `busy`, `printing_disabled`, `confirm_required` and `shopify_unavailable`.
- **Actor:** `actor` names who CLIVE acts for. Shipping records it as "`<actor>` (CLIVE)". Returns records it as given, with `source: api` on every event.

## Rules CLIVE must not work around (both apps enforce them)

**Unknown is not failed.** A 503, or no answer, during a buy, label or approve may have done it.
- Ask again with the **same** key, or read the thing.
- Never use a new key to "try again" after an unknown outcome.
- The apps reconcile before anything is repeated:
  - Shipping: its purchase ledger.
  - Returns: reads Shopify back. Finding nothing counts as safe only two minutes after the
    unanswered attempt; sooner, the answer says to try again shortly and nothing is sent.

**Buying postage in Shipping**
- Only `POST /shipments/{id}/buy` buys, with the `basis` that a preview returned.
- Shopify is read again first: payment, address, items, weights, hold or cancel.
- The buying authorisation still applies (`SHIPPING_BUYING_ENABLED`, or the order allowlist).

**Printing**
- `print` sends a label to PrintNode the first time only. `reprint` needs `"confirm": true`.
- Neither can buy.
- `sent_to_printer: true` means PrintNode accepted the job. The order is "Printing…" until PrintNode reports `done` (stage `printed`) or a failure (`print` says "Print failed", and print may be called again).

**Payment**
- Shipping never buys a new label unless the order's `displayFinancialStatus` allows it (see "Payment" below).
- A label already bought is never cancelled because payment changed. A warning is added instead.

**Delivered**
- Comes only from Shopify's carrier tracking (`deliveredAt` / `DELIVERED`).
- A fulfilment "SUCCESS" is never delivery.
- Channel Islands Royal Mail parcels stop at "in transit" in Shopify. They are never claimed delivered.

## Shipping stages (derived, never stored)

`attention`, `ready`, `bought`, `printed`, `in_transit`, `delivered` (and `all`). From `shipping/lifecycle.py`:

1. Not bought, and something blocks it → **attention**. Every blocker is listed: payment, weight, HS code, origin, address, hold, no service.
2. Not bought; payment allows it; ready with a service → **ready**.
3. Bought, and Shopify's tracking says delivered → **delivered**.
4. Bought, and the carrier has it (moving, or a carrier problem) → **in_transit**.
5. Bought, and the label printed (PrintNode reported done, or it was opened in the print view) → **printed**.
6. Otherwise bought → **bought**. A failed, uncertain or sending print stays here, with its badge.

Needs a person (a purchase to reconcile, a Shopify update to retry, a cancellation) → **attention**. A cancelled order or label shows only under `all`.

## Payment (Shopify `Order.displayFinancialStatus`, Admin API 2026-10)

| Status | New label | Shown as |
| --- | --- | --- |
| PAID | yes | Paid |
| PARTIALLY_REFUNDED | yes | Partially refunded (never "unpaid") |
| AUTHORIZED | no | Authorized — not captured |
| PENDING | no | Payment pending |
| PARTIALLY_PAID | no | Partially paid |
| REFUNDED | no | Refunded |
| VOIDED | no | Payment voided |
| EXPIRED | no | Payment expired |
| missing / anything else | no | Payment status unknown |

## Events: what changed, on what, with what evidence

Both `/events` feeds are each record's own history, flattened, oldest first, at most `limit` (default 200) per answer. Poll with `since=` the last `at` seen; while `has_more` is true, ask again at once. A page never ends part-way through one moment, so nothing is skipped. A `since` without a time zone is read as UTC. The record of what happened is the app's, not CLIVE's chat.

- **Shipping:** `{at, shipment_id, order, type, what, actor, verified, detail}`. Types include:
  - `payment_blocking`, `payment_cleared`
  - `purchase_authorised`, `label_purchased`, `fulfilled`
  - `label_printed`, `label_reprinted`, `label_print_done`, `label_print_failed`, `label_print_view`
  - `carrier_in_transit`, `carrier_out_for_delivery`, `carrier_delivered`, `carrier_exception`
  - `alert`
- **Returns:** `{at, return_id, order, type, actor, source, verified, detail, status_now}`. Types include:
  - `requested`, `approved`, `approve_unknown`, `approve_reconciled`, `declined`
  - `label_bought`, `shipping_attached`, `shipping_attach_unknown`
  - `in_transit`, `received`, `processed`, `completed`, `cancelled`, `cancel_unknown`
  - `action_interrupted`

`verified: true` means the outcome was read back from Shopify or the provider and matched.

## The boundary between Returns and Shipping

They stay separate services with separate databases, joined only through Shopify:

- **A return** changes real Shopify state (`returnCreate`, `returnProcess`). Shipping never reads Returns' database.
- **An exchange (size swap):** Returns sends `exchangeLineItems` with `returnProcess` once the item is back. Shopify then releases the replacement as a new open fulfilment order on the same order. Shipping finds it like any other order (if it goes abroad) and prices it.
- **A refund** closes the return in Shopify. No outbound shipment is created, so Shipping sees nothing.
- **A return label** is bought by Returns from its own Parcel2Go account. It is not a Shipping label and never appears in Shipping.

Nothing in Shipping reaches into Returns, or Returns into Shipping. If a later need arises (for example, linking an exchange's outbound parcel to its return), it should read Shopify's order: the exchange's fulfilment order belongs to the original order.
