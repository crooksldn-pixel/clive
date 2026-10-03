# CROOKS Returns

The returns and exchanges service that replaces AfterShip. It runs the customer portal's
backend, writes every return into Shopify's own Returns API, buys Royal Mail labels through
Click & Drop, and gives CLIVE a read/act API with signed webhooks. The scope and the decisions
behind it are in [`docs/returns/SCOPE.md`](../docs/returns/SCOPE.md).

The customer-facing page is in the theme, not here: `sections/returns-portal.liquid`,
`assets/returns-portal.js`, `templates/page.returns.json`.

```
crooksldn.com/pages/returns  ->  /apps/returns/api/*  (Shopify app proxy, signed)
                                       |
                                       v
                             this service  --  Shopify Admin API (Return, exchange, refund, credit)
                                       |  --  Click & Drop (labels)
                                       ^
                             CLIVE  /api/v1/*  (bearer keys; webhooks back)
```

## What it does

| Step | Who | What happens |
| --- | --- | --- |
| Find order | customer | Order number plus email, postcode or phone. Five tries per order per 15 min. |
| Choose items | customer | Only items Shopify says are returnable, within 14 days of delivery (30 for faulty or wrong). |
| Options | customer | Size swap first (in-stock sizes at the same price), then store credit plus a bonus, then refund. Exchanges and credit get free postage. A change-of-mind refund is self-ship or a Royal Mail label at cost taken off the refund. Faulty or wrong items are free. |
| Request | customer | Saved as `requested`. Nothing in Shopify changes yet. |
| Approve | staff / CLIVE | Creates the Shopify Return (with exchange lines and any label fee). Postage is a separate choice: `label_now`, `self_ship`, `no_return` or `label_later`. A label that can't be made leaves the return `awaiting_label` with a deadline; it is never silently lost. |
| Receive | staff / CLIVE | Condition `ok` processes it straight away: releases the exchange to ship, refunds, or credits with the bonus. Any other condition stops for a decision. |

Every action has a `preview` that states exactly what will happen, in pounds, and an `execute`
that needs an idempotency key, records who did it, then reads Shopify back and marks the
step `verified`.

## CLIVE API

All calls take `Authorization: Bearer <key>`. A read key can see and preview; a write key can
also act.

```
GET  /api/v1/returns?open=true | ?status=awaiting_label,received | ?since=2026-10-01
GET  /api/v1/returns/{id}
GET  /api/v1/orders/{order}/returns          e.g. /api/v1/orders/1939/returns
GET  /api/v1/stats?since=...                 reasons, SKUs, size swaps, value kept vs refunded
POST /api/v1/returns/{id}/actions/{action}/preview   {"params": {...}}
POST /api/v1/returns/{id}/actions/{action}           {"params": {...}, "actor": "clive", "idempotency_key": "..."}
POST /api/v1/tick                            flag overdue labels (run every 15 minutes)
GET  /health                                 policy and connection state
```

Actions: `approve {postage_mode}`, `decline {reason}`, `label {tracking?, label_url?}`,
`tracking {number}`, `receive {condition, restock, note}`, `complete`, `cancel {reason}`,
`note {text}`.

Each return carries `summary` (one line, for example
`#1939: 1x Docket Tee (M) -> L [Too small]; exchange`), `attention` (`needs_approval`,
`awaiting_label_overdue`, `needs_decision`, `error`), the money, the Shopify IDs that prove it
and a timeline in which every entry names its actor and says whether it was verified.

Webhooks to `RETURNS_CLIVE_WEBHOOK_URL` are signed:
`X-Crooks-Returns-Signature` is the hex HMAC-SHA256 of the body with
`RETURNS_CLIVE_WEBHOOK_SECRET`. Events: `return.requested`, `return.approve`, `return.label`,
`return.tracking`, `return.receive`, `return.complete`, `return.decline`, `return.cancel`,
`return.note`, `return.awaiting_label.overdue`, `return.synced`.

## Run it

```
cd crooks-returns
pip install -e '.[dev]'
pytest                                   # offline, fake Shopify
RETURNS_SHOPIFY_BACKEND=fake RETURNS_DEV_SKIP_PROXY_SIGNATURE=true \
  uvicorn returns.app:app --port 8100    # local, sample orders #1939, #1800, #1950
```

API docs are served at `/api/docs`.

## Test before launch

1. **Preview, no setup.** The clickable preview runs the real portal page on sample orders with
   a staff/CLIVE panel beside it. Nothing touches the store.
2. **Locally.** `RETURNS_SHOPIFY_BACKEND=fake` (above) runs the real service on sample orders.
3. **On the real store, hidden from customers.**
   - Do steps 1 to 4 of "Going live" below, with `RETURNS_PILOT_ORDER_NUMBERS` set to your
     own test orders. Every other order number gets "Online returns are not open yet".
   - Leave `RETURNS_RETURN_LABEL_COST_PENCE` empty and Click & Drop unset until you want to
     test one paid label; approvals then use "label later" or "customer posts it".
   - `npm run push` sends the theme to the unpublished **CROOKSLDN — Staging** theme. Open
     `https://5wn03t-nm.myshopify.com/pages/returns?preview_theme_id=202053779799`.
   - Test orders: create a draft order in the admin for your own customer account, mark it as
     paid (manual payment, so refunds move no money), and fulfil it. A real fulfilment
     counts as delivered three days after dispatch unless the carrier reports delivery
     sooner.
   - Run each path once: size swap, store credit, change-of-mind refund (self-ship), faulty
     refund, label later then add tracking, and a return that arrives damaged. Check each one
     in the Shopify admin (the order's Returns), in `GET /api/v1/returns`, and in your
     store-credit balance.
   - Clear `RETURNS_PILOT_ORDER_NUMBERS` to open it to everyone.

## On your own server (Hetzner)

`docker-compose.yml` runs the service and Caddy, which fetches and renews the HTTPS
certificate by itself. The service checks for overdue labels on its own every 15 minutes.

1. **Address.** Where crooksldn.com's DNS is managed, add an `A` record: name `returns`,
   value the server's IPv4 address.
2. **Ports.** Allow 80 and 443 in the Hetzner Cloud firewall (and `ufw allow 80,443/tcp` if
   ufw is on). If something on the server already uses 80 or 443, put this site in that web
   server instead of running Caddy.
3. **Docker.** `curl -fsSL https://get.docker.com | sh`
4. **Code.** `git clone -b claude/compassionate-dirac-44hnee https://github.com/crooksldn-pixel/clive.git /opt/clive`
   (the repository is private: sign in with a GitHub token when asked).
5. **Settings.** `cd /opt/clive/crooks-returns && cp .env.example .env && nano .env`
6. **Start.** `docker compose up -d --build`, then open `https://returns.crooksldn.com/health`.
7. **Backups.** Turn on Backups for the server in the Hetzner console. The returns live in
   `/opt/clive/crooks-returns/data/returns.sqlite3`.
8. **Updates.** `cd /opt/clive && git pull && cd crooks-returns && docker compose up -d --build`
9. **Logs.** `docker compose logs -f returns`

## Going live

1. **Shopify app.** In the Dev Dashboard, create a custom app for the store (or reuse CLIVE's
   app). Scopes: `read_orders`, `read_customers`, `read_products`, `read_returns`,
   `write_returns`, `read_merchant_managed_fulfillment_orders`,
   `read_assigned_fulfillment_orders`, `read_third_party_fulfillment_orders`,
   `read_store_credit_accounts`, `read_store_credit_account_transactions`,
   `write_store_credit_account_transactions`. Every query and mutation here was validated
   against the Admin API 2026-10 schema.
   `shopify.app.toml.example` holds all of this (scopes, app proxy, webhooks): fill in the
   client id and host, then `npx @shopify/cli app config link` and `npx @shopify/cli app deploy`
   apply steps 1 to 3 in one go.
2. **App proxy.** Subpath prefix `apps`, subpath `returns`, proxy URL
   `https://<this service>/proxy`. The theme then calls `/apps/returns/api/*` on crooksldn.com.
3. **Webhooks.** `returns/close`, `returns/cancel` and `returns/decline` to
   `https://<this service>/webhooks/shopify`, so work done in the Shopify admin flows back.
4. **Click & Drop.** API key from Click & Drop -> Settings -> Integrations, and the Tracked
   Returns service code for the account. Labels through the API need a Royal Mail Online
   Business Account. The first live label is the test of both.
5. **Hosting.** Any small always-on host behind HTTPS that builds the `Dockerfile` (Railway,
   Render, Fly.io) with a persistent volume mounted at `/data`, or the CLIVE Linux server
   behind a public HTTPS tunnel. Set the `RETURNS_*` values from `.env.example` as the host's
   environment variables. One process, one SQLite file; back the file up. Run
   `POST /api/v1/tick` every 15 minutes.
6. **Theme.** Create a page with the handle `returns` and the template `page.returns`, then
   link it from the footer and the shipping emails. `?order=1939&proof=name@example.com`
   prefills the lookup.
7. **Emails.** Shopify sends the return emails (label, refund, credit). Restyle them under
   Settings -> Notifications.
8. **AfterShip.** Run both side by side. Point the returns link at the new page, let
   AfterShip's open returns finish, then cancel it.
