# CLIVE Preorders

Pre-orders, incoming stock and Notify me for the CROOKS store. It is a sister service beside
Returns and Shipping and uses the same app (**CROOKS Operations**), Caddy and Compose. Design and
"as built" notes are in `docs/preorders/IMPLEMENTATION_PLAN.md`.

Each size (Shopify variant) is in one of three states, derived from data:

| State | When | Storefront |
| --- | --- | --- |
| In stock | Shopify has it available | the theme's normal Add to cart |
| Pre-order | none on the shelf, a live offer on an incoming batch, preorder units left | PRE-ORDER, dispatch date, price (and was-price), button "Pre-order", paid in full at checkout on a Shopify **selling plan** |
| Notify me | neither | an email signup, no account needed |

## How staff use it

1. **Incoming stock → Create incoming batch**: the supplier batch, its sizes and quantities,
   expected arrival and dispatch dates.
2. **Set up preorder** for a product on that batch: how many of each size to sell ahead
   (defaults to what's coming; set lower to keep safety stock), an optional percentage
   discount, then **Save and start preorder**. Shopify gets a `PRE_ORDER` selling plan; the
   sizes may sell past zero only while preorder units remain.
3. Orders arrive by webhook. **Pre-orders** lists every preorder line with its original and
   current ETA. When a size's units are used up it stops selling and falls back to Notify me.
4. **Dates move**: Edit dates on the batch shows how many units, orders and customers are
   affected and offers **Save & notify N customers** or **Save only**. Each line keeps the date
   it was promised; the new one is shown beside it.
5. **Stock arrives**: Receive on a size (part deliveries are fine). Shopify's inventory is
   adjusted once (idempotent key), the oldest preorders are marked ready, and **Release for
   dispatch** opens their scheduled fulfilment orders so Shipping picks them up.
6. **Notify me** ranks waiting demand (stock, inbound, signups, 7 and 30 days, last signup).
   When a size becomes preorderable or in stock, **Notify N people** sends a one-off alert,
   once per person.

Overview answers: preorder revenue, units, inbound units, waitlist size, and what needs
attention (delays, late lines, sold-through sizes, oversold units, lines bought without the
plan, Shopify out of step, unconfirmed receipts).

## Interfaces

| Path (behind `https://returns.crooksldn.com/preorders`) | Who | Auth |
| --- | --- | --- |
| `/admin`, `/admin/api/*` | the embedded admin | App Bridge session token |
| `/api/v1/*` | CLIVE (see `docs/sister-apps/CLIVE_OPERATIONS.md`) | `Authorization: Bearer` read key |
| `/webhooks/shopify` | Shopify `orders/create`, `orders/updated`, `inventory_levels/update` | HMAC; stored and answered at once, processed by the tick |
| `crooksldn.com/apps/returns/preorders/*` → `/proxy/preorders/*` | the storefront block | Shopify's app proxy signature |

## Run and check locally

```bash
cd clive-preorders
pip install -e '.[dev]'
python -m pytest -q
ruff check . && ruff format --check .
pyright .                                              # from the repo root: pyright clive-preorders
OPT_OUT_INSTRUMENTATION=true python scripts/validate_graphql.py   # needs the Shopify AI Toolkit
python scripts/dev_server.py                           # fake store, no secrets, nothing sent
```

The dev server: admin `http://127.0.0.1:8130/admin`, a product page with the storefront block at
`/dev/storefront`, emails it would have sent at `/dev/emails`.

## Deploy (the owner does this)

Order matters: the service must be up before Shopify sends it webhooks, and selling plans stay
off until Shopify has granted the scopes.

```bash
cd /opt/clive && git pull
cp clive-preorders/.env.example clive-preorders/.env && chmod 600 clive-preorders/.env
mkdir -p clive-preorders/data
nano clive-preorders/.env      # client id and secret: the same as Returns; leave SELLING_PLANS=off
cd crooks-returns && docker compose up -d --build
curl -s https://returns.crooksldn.com/preorders/health     # {"ok":true}
```

`clive-preorders/.env` must exist before `docker compose up`: Compose refuses to start any
service if a named env file is missing.

Then deploy the app configuration and the theme extension from where `shopify.app.toml` lives
(copy the new scopes, webhook subscription and metafield block from
`crooks-returns/shopify.app.toml.example`):

```bash
npx @shopify/cli app deploy
```

Approve the new permissions in Shopify admin. Then:

1. **Online Store → Themes → Customize → a product template**: add the app block
   "Pre-order / Notify me" under the buy buttons and save.
2. If `app deploy` was refused the purchase-option scopes, request access in the Dev
   Dashboard (Shopify reviews most preorder apps); everything except selling as a preorder
   works meanwhile.
3. Set `PREORDERS_SELLING_PLANS=shopify`, `docker compose up -d preorders`, start one test
   offer on a cheap product and buy it once with a test order before relying on it.
4. Email: set `PREORDERS_EMAIL_PROVIDER=resend`, `PREORDERS_RESEND_API_KEY` and a verified
   `PREORDERS_EMAIL_FROM` domain. Until then the screens say nothing can be sent.

First-deploy checks:

- Storefront signups are limited per email (`PREORDERS_SIGNUP_EMAIL_LIMIT`, 10 an hour) and,
  as a flood brake only, per address (`PREORDERS_SIGNUP_IP_LIMIT`, 300 an hour): through the
  app proxy the address may be Shopify's, shared by every shopper. Signed proxy requests older
  than 5 minutes, or for another shop, are refused.
- The theme's product form keeps the selected variant in a field named `id` (all Online Store
  2.0 themes do). The block follows that field.

Privacy: a signup can be deleted from Notify me (per person); finished signups (notified,
converted, unsubscribed) are deleted a year after they finished; logs carry ids, not emails. An
alert
carries a one-click unsubscribe. The webhook endpoint also handles `customers/redact`, but the
app has no compliance webhooks configured today (it is a single-store app, not listed); if they
are added for App Store listing, Preorders needs the topic too.

When something goes wrong it is shown, not hidden: Overview → Needs attention lists offers out
of step with Shopify, Shopify updates that couldn't be processed, stock receipts or emails that
weren't confirmed, failing background work and errors from the last check against Shopify. An
unconfirmed receipt has **Confirm with Shopify** on its batch page (it resends the same request,
which can't add stock twice). An email whose outcome is unknown is retried with the same key
only within 23 hours (Resend remembers a key for 24); after that it stays "not confirmed".

Rollback: `docker compose stop preorders`. Closing every offer first (Stop preorder) puts the
sizes back to their own inventory policy and removes them from the selling plans.
