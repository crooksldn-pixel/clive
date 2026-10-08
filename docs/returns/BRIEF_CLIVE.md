# Brief for the CLIVE builder: CROOKS Returns

**Status (2026-10-03):** built, deployed by the owner and live on crooksldn.com. CROOKS Returns replaces AfterShip for returns and exchanges. This brief says what exists, how it behaves, and how CLIVE should connect to it.

- **Code:** branch `claude/compassionate-dirac-44hnee`, folder `crooks-returns/`. The customer page is in the theme files (see `BRIEF_THEME.md`).
- **Scope and owner decisions:** `docs/returns/SCOPE.md`.
- **How it was built:** outside the CLIVE engineering kernel. It has no kernel task, review or acceptance records. Record it in product memory (`DECISIONS.md` / `CURRENT_TRUTH.md`) as an owner-deployed service; don't assume kernel status.

---

## 1. What it is

A small service in its own container, separate from the CLIVE application:

| | |
| --- | --- |
| URL | `https://returns.crooksldn.com` |
| Host | Hetzner `crooks-os-prod-1`, `/opt/clive/crooks-returns`, Docker Compose (service + Caddy for HTTPS) |
| Stack | Python 3.12, FastAPI, SQLite (`data/returns.sqlite3`), httpx |
| Shopify | Its own app, **CROOKS Returns** (Dev Dashboard, client credentials, Admin GraphQL `2026-10`) |
| Labels | Parcel2Go API, paid from the CROOKS **PrePay** balance (Click & Drop code remains, switched off) |
| Settings | `.env` on the server; every key starts `RETURNS_`. Secrets are never in the repo. |

**Shopify is the system of record.** An approved request becomes a native Shopify Return on the order, with exchange lines, refund and store credit done by `returnProcess`. So CLIVE's existing Shopify reads also see returns. The returns service adds the request before Shopify knows about it, the customer's choices, the label, the timeline and the attention flags.

## 2. What it does

1. **Customer** (`crooksldn.com/pages/returns`):
   - Verifies with order number plus email, postcode or phone (5 wrong tries per order per 15 minutes).
   - Picks items and a reason. A size issue offers only the smaller or larger sizes in stock, with the product's size chart.
   - Is offered: **exchange** (free) → **store credit + bonus** (+£5 under £40, +£10 from £40; free postage) → **refund** (always available; change-of-mind postage is self-ship, or our label at cost taken off the refund).
   - Chooses where to drop it off (Evri / InPost / Royal Mail, with the nearest shops), then submits. The case is saved as `requested`. **Nothing in Shopify changes yet.**
2. **Staff or CLIVE approve:**
   - A Shopify Return is created.
   - Postage is a separate decision: `label_now` (buys a Parcel2Go label: **spends money**), `self_ship`, `label_later` or `no_return`.
3. **Drop-off:** Parcel2Go's tracking webhook moves the return to `in_transit`. Delivery to us flags `delivered_unchecked`.
4. **Receive:**
   - Condition `ok` processes it straight away (**moves money**): the exchange is released to ship, the refund is sent to the card, or store credit is issued plus the bonus. The result is read back from Shopify and marked `verified`.
   - Any other condition stops at `received` for a decision, then `complete`.
5. **Shopify admin:** returns closed, cancelled or declined there sync back (`return.synced`).

**Rules (owner decisions):**
- 14 days from delivery; 30 days for faulty, wrong or misdescribed items (UK law).
- Sale items are treated the same.
- An exchange ships when the return arrives back.
- A tag `non-returnable` allows fault returns only.
- Free or gifted items get no credit or bonus.

## 3. Data model (money is always integer pence)

```
Return {
  id "ret_…", order_id (gid), order_name "CROOKS-2131", customer_id, customer_name, customer_email,
  status, resolution, created_at, updated_at,
  lines[ {title, variant_title, sku, quantity, reason, note, unit_paid_pence, unit_price_pence,
          exchange_variant_id/title/sku, exchange_price_pence, exchange_direction size_up|size_down|same|other} ],
  money { items_pence, bonus_pence, fee_pence, shipping_refund_pence, refund_pence, credit_pence },
  postage { chosen, mode, carrier, tracking, tracking_url, service (courier key), service_name,
            label_price_pence (what we paid), label_ref, label_due_at, courier_stage, shops[] },
  shopify { return_id, return_name, reverse_fulfillment_order_ids, exchange_line_item_ids,
            reverse_delivery_id, processed, refund_ids, store_credit_transaction_id },
  inspection, decline_reason, last_error,
  timeline[ {at, type, actor, detail, verified} ],
  // added in API responses:
  summary "CROOKS-2131: 1x Express Tee (Black / S) [Faulty or damaged]; refund £0.00",
  attention [needs_approval | awaiting_label_overdue | delivered_unchecked | needs_decision | error],
  label_url
}
```

| Enum | Values |
| --- | --- |
| `status` | `requested → awaiting_label → awaiting_shipment → in_transit → received → completed`, plus `declined`, `cancelled` |
| `resolution` | `exchange`, `store_credit`, `refund` |
| `reason` | `too_small`, `too_big`, `changed_mind`, `not_as_described`, `faulty`, `wrong_item` |

**`verified: true`** on a timeline entry means the outcome was read back from Shopify, or confirmed by Parcel2Go. This maps to CLIVE's "verified", which is distinct from "completed".

## 4. The API CLIVE uses

Base `https://returns.crooksldn.com/api/v1`. Send `Authorization: Bearer <key>` on every call.

- **Keys:** `RETURNS_CLIVE_READ_KEYS` and `RETURNS_CLIVE_WRITE_KEYS` in the server `.env` (comma-separated; a write key can also read). The owner reads them with `grep CLIVE /opt/clive/crooks-returns/.env` and gives them to CLIVE through its secrets mechanism.

```
GET  /returns?open=true                 open returns (also ?status=a,b  ?since=ISO  ?limit=)
GET  /returns/{id}                      one return, full
GET  /orders/{order}/returns            by order: /orders/2131/returns or /orders/CROOKS-2131/returns
GET  /stats?since=ISO                   counts by status/resolution/reason, top SKUs, size swaps up/down,
                                        value returned vs kept (credit+exchange), kept_share, bonus given,
                                        label fees recovered
POST /returns/{id}/actions/{action}/preview   {"params": {...}}            read key; changes nothing
POST /returns/{id}/actions/{action}           {"params": {...}, "actor": "clive", "idempotency_key": "…"}  write key
GET  /capabilities                      what CLIVE can do here: actions, statuses, operations
GET  /events?since=ISO&limit=           what changed across returns, oldest first (see below)
POST /tick                              flag overdue labels (the service already does this every 15 min)
GET  /health                            no key; policy and connection state
GET  /api/docs                          OpenAPI
```

**Actions and params:**

| Action | Allowed from | Params | Effect |
| --- | --- | --- | --- |
| `approve` | requested | `postage_mode`: label_now / self_ship / label_later / no_return (default: what the customer chose) | Shopify `returnCreate`; label_now **buys a Parcel2Go label**; no_return **processes money now** |
| `decline` | requested | `reason` | nothing in Shopify |
| `label` | awaiting_label | `tracking` (+ `carrier`, `tracking_url`) to attach your own, or nothing to **buy** one | `reverseDeliveryCreateWithShipping` |
| `tracking` | awaiting_shipment, awaiting_label | `number` | marks in_transit |
| `receive` | awaiting_*, in_transit | `condition` ok / damaged / worn / missing, `restock` (default true), `note` | ok → **processes money** (`returnProcess`, store credit + bonus) |
| `complete` | received | — | **processes money** after a decision |
| `cancel` | requested, awaiting_* | `reason` | `returnCancel` if in Shopify |
| `note` | any | `text` | timeline only |

**Contract:**
- `preview` returns `{"will": ["Create Shopify return …", "Book Evri (Evri ParcelShop) for £2.98 from Parcel2Go PrePay, balance £50.00 …"], "shopify_calls": [...], "money": {...}}`. It uses the same rule checks as execute, so a refused preview means a refused execute.
- `execute` needs an `idempotency_key`, scoped per return and action. Sending the same key again returns `{"replayed": true}` and **never repeats a refund or a label**.
- The response is `{from, status, verified, error, evidence, return}`. A non-empty `error` means the step was recorded but Shopify or Parcel2Go refused part of it. The return carries `last_error` and the `error` attention flag.
- `actor` is written on the timeline. Use `"clive"`, or `"clive for George"` when acting on the owner's instruction.
- **One key is one request.** The same key with the same params replays the first outcome; the same key with *different* params is refused (409 "That key was already used for a different request"). A failed outcome is replayed too: to try again, use a new key.
- **Where it came from.** Every timeline event carries `source`: `ui` (the Returns screen), `api` (this API), `ctl`, `portal` (the customer) or `system`. The screen and the API run the same `ReturnsService.execute`; only `source` differs.
- **Lost replies.** If Shopify doesn't answer a change (`returnCreate`, the label hand-over), the return says so (`approve_unknown`, `shipping_attach_unknown`) and nothing is sent again blindly: the next attempt reads Shopify back first and adopts what it finds. The intent is saved before the change is sent, so a crash is treated the same way. Finding nothing only counts as "safe to send" two minutes after the unanswered attempt; sooner, the action stops and says to try again shortly. Declining or cancelling after an unknown approval checks first, and cancels in Shopify any return the approval made. An action interrupted by an unexpected error answers 503 and keeps what it did (a paid label is settled, never bought twice).
- **`GET /events`** returns `{"events": [{at, return_id, order, type, actor, source, verified, detail, status_now}]}`, oldest first. Poll it with the last `at` you saw as `since`: it is the record of what changed, so CLIVE never has to keep its own.

## 5. Events from the service to CLIVE (the doorbell)

Since 8 October (CLIVE's DEC-071, ruling 20) the service posts each event it records to CLIVE's
public hooks door. The post is a doorbell, not the record: CLIVE reads the return through `/api/v1`
with its own key after it. Code: `crooks-returns/returns/doorbell.py`; the outbox is in `returns/store.py`.

Set both in `/opt/clive/crooks-returns/.env`, then `docker compose up -d`:

- `RETURNS_CLIVE_WEBHOOK_URL=https://hooks.crooksldn.com/hooks/returns`
- `RETURNS_CLIVE_WEBHOOK_SECRET=` a long random string (`openssl rand -hex 32`), pasted on CLIVE's
  Connections screen, CROOKS Returns, "Events secret".

- **Request:** `POST`, `Content-Type: application/json`, body exactly
  `{"id":"evt_…","type":"label_bought","return_id":"ret_…","at":"<when it happened, ISO>","sent_at":<unix seconds>}`.
  No customer's name, email, address or order, and nothing else of the return.
- **Signature:** `X-Crooks-Returns-Signature: sha256=<hex HMAC-SHA256 of the raw body with the secret>`.
  `sent_at` is inside the signed body; CLIVE refuses a post more than five minutes from its clock.
- **Every event, once each:** one outbox row per timeline event, written in the same transaction as
  the return, so nothing is recorded without its row; `returns-ctl` actions are sent too. The `id`
  is fixed per event, so CLIVE drops a repeat.
- **Delivery:** on its own thread, never on the request path and never under the store's lock; a
  five-second timeout; anything but a 2xx is tried again after 30 s, 1, 2, 4 … minutes, at most an
  hour apart, each try signed afresh, and given up after a day. Redirects are not followed.
- **Off when unset:** no URL, no rows and no thread. No secret: nothing is sent unsigned; the rows
  wait (and are given up after a day).
- **Is it working?** `docker compose exec returns returns-ctl doorbell`: waiting, delivered and
  given up, and the last answer CLIVE gave (403 means the secrets differ or the clocks are apart).

**Types:** the timeline's own: `requested`, `approved`, `approve_failed`, `approve_unknown`,
`awaiting_label`, `label_bought`, `label_overdue`, `label_payment_not_taken`, `label_paid_not_collected`,
`shipping_attached`, `shipping_attach_failed`, `shipping_attach_unknown`, `in_transit`,
`delivered_to_us`, `received`, `processed`, `process_failed`, `bonus_credited`, `bonus_failed`,
`completed`, `declined`, `cancelled`, `cancel_failed`, `cancel_unknown`, `note`, `no_return`,
`action_interrupted`, and the rest the service records.

Until 8 October this section described a post of the whole return, sent once from the request
itself and never retried. Nothing received it (CLIVE had no door for it), and it carried the
customer's details; it is gone.

## 6. How CLIVE should integrate (fits proposed ≠ authorised ≠ started ≠ completed ≠ verified)

**Read-only first.** These need no new authority:
- **Daily ops brief:** count `attention` across `GET /returns?open=true`: approvals waiting, labels overdue, parcels delivered but not checked, errors.
- **Support Investigator:** "where is my return?" maps to `GET /orders/{order}/returns`. Answer from `status`, `postage.tracking_url` and the timeline.
- **Weekly report:** `GET /stats?since=`. Report the kept share (credit and exchange against refunds), the top return reasons and SKUs, and size-up or size-down swaps per product. A product that keeps getting `too_small` swaps is a size chart or fit finding.

**Writes are proposals.** CLIVE calls `preview` and shows the owner the `will` lines; that is the proposal. After the owner authorises it, CLIVE calls execute with a fresh idempotency key and `actor` naming the authority. It then reports `verified`, or the `error`.

Treat three things as money-moving and always owner-gated:
- `approve` with `label_now` or `no_return`;
- `label` with no tracking (it buys a label);
- `receive` with `ok`, and `complete`.

`note`, `decline` and attaching tracking are lower risk, but are still the owner's call under the current authority model.

**Never:** call the portal endpoints (`/proxy/api/*`, which are for customers through Shopify's signed app proxy), write to the SQLite file, or call Shopify's return mutations for a return this service owns. Go through the actions, so the timeline and verification stay true.

## 7. Other surfaces (don't duplicate)

- **Staff screen in Shopify admin:** Apps → CROOKS Operations → Returns, served at `/admin`. On a phone the action dialog keeps its buttons on screen and says why Approve is waiting (checking, or what failed, with Try again). It has the returns list, each return, every action with its "This will…" preview, the health check, and the test-order (pilot) list. It authenticates with Shopify session tokens and signs the timeline with the staff member's name.
- **`returns-ctl` on the server:** `docker compose exec returns returns-ctl check | list | show ID | labels POSTCODE | approve ID self_ship …`.

## 8. Known gaps and ideas

- **PrePay balance:** shown in the admin Setup check and `returns-ctl labels`, but **not in `/api/v1`**. A `GET /api/v1/labels/balance` would let CLIVE warn before it runs out (under about £10). It's a small addition to `crooks-returns/returns/api.py`.
- **Unused labels:** the Parcel2Go API has no cancel. A label bought for a customer who never posts must be refunded on parcel2go.com. CLIVE could list `awaiting_shipment` returns with a label older than 14 days and `courier_stage` empty, for the owner to cancel.
- **Not built yet:**
  - exchanges for a different product;
  - "keep it" partial-refund offers;
  - CROOKS-styled Shopify return emails (Shopify's own templates are used);
  - an exact per-courier label fee for change-of-mind refunds (it's a flat `RETURNS_RETURN_LABEL_COST_PENCE`, currently £2.98).
- **Unconfirmed:** whether live Parcel2Go returns the in-store QR image (the sandbox doesn't). The first live label answers it.

## 9. Running it (owner)

```
cd /opt/clive && git pull && cd crooks-returns && docker compose up -d --build   # update
docker compose logs -f returns                                                     # logs
docker compose exec returns returns-ctl check                                      # health
```

**Backups:** Hetzner server backups cover `/opt/clive/crooks-returns/data/returns.sqlite3`.

**Tests:** `cd crooks-returns && pip install -e '.[dev]' && pytest`. 73 offline tests, fake Shopify, simulated Parcel2Go.
