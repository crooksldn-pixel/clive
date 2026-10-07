# CROOKS Operations: deploy Shipping beside Returns, prepare a live order, then stop

One embedded Shopify app (**CROOKS Operations**, today named "CROOKS Returns") with three
sections, each its own service with its own data:

| Sidebar | Path on returns.crooksldn.com | Service | Data |
| --- | --- | --- | --- |
| Returns | `/admin` | `crooks-returns` | `crooks-returns/data/returns.sqlite3` |
| Shipping | `/shipping/admin` | `clive-shipping` | `clive-shipping/data/shipping.sqlite3` |
| Settings | `/settings` | static page (`ops-shell/`) | none: links to each service's own settings |

Caddy routes the paths (`crooks-returns/Caddyfile`). The services share only the Shopify app
(client id and secret, so the same session check) and the navigation. Each has its own code,
database, `.env`, Parcel2Go credential and API.

**Money safety.** `SHIPPING_AUTHORISED_ORDERS` is empty, so **no label can be bought**.
Orders are found, checked and priced, and the preview runs, but the Buy button is replaced by
"Check price" and the server refuses any purchase (403, "not authorised"). A label can only be
bought after the owner names that one order on the server (step 9).

## 1. Shopify app changes, and their risk

`crooks-returns/shopify.app.toml.example` holds both changes. Copy them into your real
`shopify.app.toml`, then deploy them with the Shopify CLI.

- **Scopes added for Shipping** (from the Admin API 2026-10 docs):
  - `write_merchant_managed_fulfillment_orders`: marks the order fulfilled with the tracking number.
  - `read_inventory` and `write_inventory`: HS code, country of origin, weight.
  - `read_locations`: the ship-from address.

  After `app deploy`, Shopify asks the store to approve the new permissions. Returns keeps
  working before and after the approval. Until you approve them, Shipping can still read
  orders, but answers it saves can't be written to Shopify. CLIVE keeps them and says so.
- **Name "CROOKS Operations".** This changes only the name in the admin sidebar. The client
  id, the app's URL, the customer portal path (`/apps/returns`) and the webhooks stay the same.
  It's low risk. To defer it, keep `name = "CROOKS Returns"`; the three sections work either way.

## 2. Server: update the code

Back up the Returns database first.

```bash
cd /opt/clive
cp crooks-returns/data/returns.sqlite3 ~/returns-$(date +%F-%H%M).sqlite3
git pull
```

## 3. Server: Shipping's settings (secrets stay on the server)

```bash
cp clive-shipping/.env.example clive-shipping/.env
chmod 600 clive-shipping/.env
mkdir -p clive-shipping/data
nano clive-shipping/.env
```

Fill in these values:

- `SHIPPING_SHOPIFY_CLIENT_ID` and `SHIPPING_SHOPIFY_CLIENT_SECRET`: the **same values** as
  `RETURNS_SHOPIFY_CLIENT_ID` / `RETURNS_SHOPIFY_CLIENT_SECRET` in `crooks-returns/.env`. It's
  the same app.
- `SHIPPING_P2G_CLIENT_ID` and `SHIPPING_P2G_CLIENT_SECRET`: a **new live Parcel2Go API
  credential** for Shipping (Parcel2Go account → API). Don't reuse the Returns credential.
- Leave `SHIPPING_P2G_BASE_URL=https://www.parcel2go.com`.
- **Leave `SHIPPING_AUTHORISED_ORDERS=` empty.**
- Keep the PrePay balance small, for example £30. It caps what any mistake could spend.

## 4. Server: start it

```bash
cd /opt/clive/crooks-returns
docker compose up -d --build
docker compose ps
```

This builds Shipping, rebuilds Returns (its page gained the shared navigation) and restarts
Caddy with the new routes. Returns is unavailable for a few seconds while it restarts.

Check all three answer:

```bash
curl -s https://returns.crooksldn.com/health | head -c 80; echo
curl -s https://returns.crooksldn.com/shipping/health; echo        # {"ok":true}
curl -sI https://returns.crooksldn.com/settings | head -1           # 200
docker compose logs --tail 50 shipping
```

## 5. Shopify: deploy the app configuration

Run this on the machine where you keep `shopify.app.toml`:

```bash
npx @shopify/cli app deploy
```

Then, in Shopify admin, approve the updated permissions when the app asks (or under
Settings → Apps).

## 6. In Shopify admin: check the shell

1. Open the app from the Apps menu. The sidebar shows **Returns, Shipping, Settings**.
2. **Returns** opens as before. Open one return to confirm it still works.
3. **Settings** has two cards, Returns and Shipping, each opening that service's settings.

## 7. In Shopify admin: Shipping setup

Go to Shipping → Setup.

- **Parcel2Go:** it must show **Connected · Live**, with the PrePay balance.
- **Ship from:** filled in from the Shopify location. Check it and save.
- **Packages:** add the real mailer(s): name, length, width, height, empty weight. The first
  one becomes the default.
- **Customs defaults:** DAP. Add an EORI or VAT number only if CROOKS has one.

## 8. Prepare one genuine international order (no money)

1. In Shipping, click **Check Shopify for orders**. On 2026-10-05 the open international
   orders were six to **Guernsey** (CROOKS-2142, 2134, 2125, 2124, 2122, 2120) and #1405 to
   Australia. Guernsey is outside UK customs, so these are international and need customs data.
2. Open one order, for example **CROOKS-2142**. It asks for the details Shopify doesn't have:
   the product's weight, HS code and country of origin.
   - Today every CROOKS product has a weight of 0 and no HS code or origin.
   - Answer with **real facts only**. They're written to the product in Shopify and reused
     for every later order.
3. Once it's **Ready**, check:
   - the address;
   - the recommended service and "See other services";
   - the package and weight;
   - the customs summary;
   - the DAP sentence.
4. Click **Check price — £X**. The window shows exactly what a purchase would do, under the
   heading "Exact price (not bought)". The page says "Buying is not authorised for this order".
5. Take screenshots of the detail page and the price window. **Stop here.**

In the sandbox (2026-10-05), a Guernsey parcel was quoted only by:

| Service | Sandbox price | Days |
| --- | --- | --- |
| Parcelforce Worldwide Channel Islands | £11.79 | up to 8 |
| Landmark | £18.05 | up to 24 |
| UPS Express Saver | £52.38 | up to 3 |

Live prices may differ. Compare them with what Guernsey parcels cost you today before
choosing Shipping for them.

## 9. Authorising one label (only on the owner's explicit decision)

```bash
cd /opt/clive/crooks-returns
nano ../clive-shipping/.env            # SHIPPING_AUTHORISED_ORDERS=2142
docker compose up -d shipping          # picks up the change
```

1. In the admin, the order now offers **Buy label — £X**. Buy once.
2. Then check the purchase (see `docs/shipping/DESIGN.md`, "Live-readiness gate", steps 8–12):
   - PrePay dropped by exactly the price;
   - the Shopify order is fulfilled with tracking;
   - customs is confirmed;
   - the 4×6 label prints at actual size on the JADENS;
   - note the tracking number.
3. Close the authorisation again:

```bash
nano ../clive-shipping/.env            # SHIPPING_AUTHORISED_ORDERS=
docker compose up -d shipping
```

## Release 2026-10-07: payment, tracking, lifecycle tabs, CLIVE API, Returns safety

What changes: Shipping blocks new labels for unpaid orders and re-reads payment before buying,
reads carrier tracking from Shopify, and shows lifecycle tabs; both apps gain CLIVE `/api/v1`
additions; Returns never repeats a Shopify change whose reply was lost, and its action dialog
works on a phone. No Shopify app change: `read_orders` and the fulfilment-order scopes are
already granted. No database migration: both apps store each record as one JSON document and
new fields have defaults, so existing rows load unchanged; nothing is rewritten on start.

```bash
ssh root@crooks-os-prod-1
cd /opt/clive
# 1. Back up both databases (SQLite's online backup: safe while the services run, WAL included)
for db in crooks-returns/data/returns.sqlite3 clive-shipping/data/shipping.sqlite3; do
  python3 -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); print('backed up', sys.argv[1], '->', sys.argv[2])" \
    "$db" "/root/$(basename "$db" .sqlite3)-$(date +%F-%H%M).sqlite3"
done
# 2. Update and check the commit
git pull --ff-only && git log --oneline -1
# 3. Rebuild and restart both services (Caddy is unchanged)
cd crooks-returns && docker compose up -d --build returns shipping && docker compose ps
# 4. Health
curl -s https://returns.crooksldn.com/health | head -c 80; echo
curl -s https://returns.crooksldn.com/shipping/health; echo        # {"ok":true}
# 5. Buying authorisation is unchanged (prints "none" unless set on purpose)
docker compose exec -T shipping python -c "from shipping.settings import Settings as S; s=S(); print('buying_enabled:', s.buying_enabled, '| orders:', sorted(s.authorised()) or 'none')"
# 6. A read-only look at every open order (buys nothing)
docker compose exec -T shipping python -m shipping.tools.dry_run
```

Optional, only when CLIVE is to use Shipping: generate keys on the server and add them to
`clive-shipping/.env` as `SHIPPING_CLIVE_READ_KEYS` / `SHIPPING_CLIVE_WRITE_KEYS` (never in
chat), then `docker compose up -d shipping`. Without them Shipping's `/api/v1` answers nothing.

**Check in Shopify admin (CROOKS Operations):**
- **Shipping**: the tabs show Needs attention, Ready to ship, Labels bought, Printed, In transit,
  Delivered, All. An unpaid order is in Needs attention with "Payment pending" (or its status)
  beside any missing details. Within about 2 hours of the first tick, recent labels move to In
  transit / Delivered as Shopify reports them; Guernsey parcels stay In transit (Royal Mail's
  tracking ends at Guernsey Post).
- **Returns on a phone**: open a pending return, tap Approve: the dialog's Approve is on screen,
  says "Checking what this will do…" until it can be pressed, then approves once.

**Expected for the first few minutes:** shipments stored before this release have no payment
status yet, so ready ones show in Needs attention ("Payment status unknown") until the first
tick re-reads them from Shopify (about a minute after start) or someone presses "Check Shopify
for orders". Nothing can be bought while that is so.

### Rolling this release back

Note the commit before pulling (`git log --oneline -1`). To go back:

```bash
cd /opt/clive
# Returns that met a lost Shopify reply carry a marker the old code doesn't know; it would drop it.
python3 -c "import sqlite3; d=sqlite3.connect('crooks-returns/data/returns.sqlite3'); print(d.execute(\"SELECT id, order_name FROM returns WHERE json_extract(doc,'$.shopify.create_unknown_at') IS NOT NULL OR json_extract(doc,'$.shopify.attach_unknown_at') IS NOT NULL\").fetchall())"
# Settle any listed (approve or label again, which reads Shopify) before going back.
git checkout <previous commit>
cd crooks-returns && docker compose up -d --build returns shipping && docker compose ps
```

The databases need no restore: the old code reads the new records and ignores the new fields
(payment, tracking, lost-reply markers). Restore the backup from step 1 only if a record is
damaged: `docker compose stop returns shipping`, copy the backup over the `.sqlite3` file
(after removing its `-wal` and `-shm` files), and start both again.

## Rollback

- **Shipping only:** `docker compose stop shipping`. Returns and Settings are unaffected; the
  Shipping section shows a gateway error until it's started again.
- **Everything back as it was:** `git checkout <previous commit> -- crooks-returns/Caddyfile
  crooks-returns/docker-compose.yml crooks-returns/returns/static/admin.html`, then
  `docker compose up -d --build`.
- **Scopes:** extra scopes are harmless to Returns. Remove them from the toml and run
  `app deploy` to drop them.

## Verified before handing over (2026-10-05, in the cloud session)

- The real `Caddyfile` validated with Caddy 2.10.2, and was run locally over both services:
  - Returns at `/admin` (with its own `/admin/api`);
  - Shipping at `/shipping/admin`, its API under `/shipping/admin/api`;
  - `/settings` rendered with the client id and a `frame-ancestors` header.
- In a browser, when App Bridge changes the URL to another section, that section loads.
  Returns' own hash navigation doesn't reload the page. No console errors.
- Tests:
  - Shipping: 282 pytest tests, including the purchase authorisation guard: unauthorised
    orders are priced but never bought, one authorised order buys, and nothing is authorised
    by default.
  - Returns: 85 tests.
- The Settings markup validates against Polaris v1, apart from `rel="home"` on the App
  Bridge `s-app-nav` link, which App Bridge defines.
- Guernsey prepared end to end against the Parcel2Go **sandbox**: four questions, then Ready,
  four services, preview run, buy refused (not authorised).
- **Not verified here:** the real admin embedding and the live Parcel2Go account. This
  session has no access to the server or to live secrets; steps 2–8 do that.
