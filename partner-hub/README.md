# CROOKS Partner Hub ↔ Shopify

Backend functions for the Base44 app **crooks-partner-hub**
(<https://crooks-partner-hub.base44.app>, app id `6a96ee08b3aefa8357c55ed7`)
that connect it to the CROOKSLDN Shopify store (`5wn03t-nm.myshopify.com`).

The hub's admin screens already call these functions by name (CREATE SEND,
SYNC, SYNC SHOPIFY). These versions replace whatever is deployed under those
names now.

## What it does

| Function | Called by | What it does |
| --- | --- | --- |
| `shopifyCreateSend` | CREATE SEND dialog | Checks each chosen item against **live** Shopify stock, then creates a gifted order: real items at full price, a 100% `INFLUENCER-SEEDING` discount, free shipping, marked paid, tagged `SEEDING` + `influencer-<username>`, with their TikTok/Instagram in the order note. No email goes to the influencer. Records a Send in the hub. |
| `shopifySyncTracking` | SYNC button, Shopify webhook, CLIVE | Reads each open send's Shopify order. When you buy the label (or Click & Drop pushes tracking in), the send becomes **dispatched** with the carrier, tracking number and link. Then **delivered**, then **overdue** 21 days after dispatch unless a post was recorded. Cancelled orders become **cancelled**. |
| `shopifySyncCatalog` | SYNC, SYNC SHOPIFY | Refreshes every product, variant, price, image and stock count from Shopify. Keeps your on/off and ordering choices. Products whose handle changed in Shopify are matched by variant id, and influencers' picks move with them. |
| `shopifySyncUsage` | SYNC | Affiliate code uses and revenue (read-only). |
| `sendMarkShipped` | MARK SHIPPED (after the Base44 prompt) | For parcels sent outside Shopify: fulfils the Shopify order with your tracking number. |
| `shopifyWebhook` | Shopify | Updates a send the moment its order is fulfilled, re-labelled or cancelled. Rejects anything not signed by Shopify. |
| `shopifyCheckConnection` | CHECK SHOPIFY (after the Base44 prompt) | Tests the connection, lists missing permissions, registers the webhooks. |
| `portalCheckAvailable` | onboarding / affiliate code (after the Base44 prompt) | "Is this username/code taken?" once records are private. |
| `partnerApi` | CLIVE | See [CLIVE_API.md](CLIVE_API.md). |
| `shopifyCreateDiscount` | Affiliate tab, admin code override | A creator code's Shopify discount: free MOTIONTEC socks (Buy X Get Y) or % off. See [CREATOR_GIFT.md](CREATOR_GIFT.md). |
| `syncPromotions` | SYNC, SYNC GIFT RULES, status changes | Pauses/unpauses codes with the influencer and writes the gift rules the bag script reads. |

### What stops an order failing

- **Live stock check before the order.** Shopify's own check isn't enough:
  your tees allow overselling and several sizes are at 0 or below, so Shopify
  would accept an order you can't ship. The function refuses anything you
  don't have on hand and names the item, e.g. "BLACK CONVICT HOODIE - M: 0 in
  stock, 1 needed". Nothing is created.
- **Sets are bundles in Shopify.** A set goes on the order as its actual
  hoodie and sweats, so stock comes off the right pieces and the packing slip
  shows what to pick. Each piece is checked, including when the same piece is
  also ordered on its own.
- **Deleted or archived products, blocked influencers and incomplete
  addresses** are caught before Shopify is called, with a message saying what
  to fix. US, Canadian and Australian addresses get the state/province code
  Shopify needs.
- **Double clicks** return the first order instead of creating a second.
- **Expired tokens are renewed automatically.** The Shopify token lasts 24
  hours and the functions request a fresh one when needed. A one-off pasted
  token stopping after a day is a likely cause of the old setup breaking: its
  only order, CROOKS-1869, was made on 1 Sep and cancelled the next day.
- **If Shopify doesn't answer, the order isn't retried blindly.** The function
  looks the order up by its unique tag. If it can't tell yet, the hub keeps
  the send and links it on the next SYNC, so pressing the button again can't
  make a duplicate.
- **Shopify rate limits** are waited out.

## Setup

### 1. Create the Shopify app (about 5 minutes)

1. Open the Shopify **Dev Dashboard** (<https://dev.shopify.com/dashboard>,
   signed in as the store owner). **Create app** → name it `CROOKS Partner Hub`.
2. On **Versions**, set these **scopes**, then **Release**:
   `read_products, read_inventory, write_orders, write_merchant_managed_fulfillment_orders, read_discounts, read_locations`
   (each `write_` scope includes its `read_`).
3. In the app's settings, find **Protected customer data access** and select
   **Name, Email and Address**. Reason: "shipping gifted products to
   influencers". Custom apps on your own store get this without a review. The
   order carries the influencer's name and address, so this is required.
4. **Install app** → choose the CROOKSLDN store.
5. From **Settings**, copy the **Client ID** and **Client secret**.

Already have a working admin-created custom app with an `shpat_…` token and
those scopes (the "Threads software" app made CROOKS-1869)? You can use its
token instead of steps 1–5: set `SHOPIFY_ADMIN_ACCESS_TOKEN` and, for
webhooks, `SHOPIFY_WEBHOOK_SECRET` (that app's API secret key).

### Steps 2, 3 and 5 in one go: the setup script

On any Linux server (e.g. over SSH in Termius), Mac, or Cowork's shell:

```bash
git clone --depth 1 -b claude/compassionate-planck-9xe5of https://github.com/crooksldn-pixel/clive.git
cd clive/partner-hub
bash scripts/server-setup.sh
```

It installs what it needs for your user only, with no sudo: Node 22 through
nvm if yours is too old, plus the pinned Base44 CLI and Deno. Then it:

- runs the tests;
- signs you in to Base44 with a code you confirm on your phone;
- backs up the current functions;
- asks for the Shopify Client ID and secret (the secret is typed hidden);
- makes the CLIVE API key and keeps a copy in
  `~/.config/crooks-partner-hub/partner-api-key`;
- deploys the eleven functions and replaces any builder copies of them;
- checks Base44 is running exactly this version;
- connects to Shopify and registers the webhooks;
- calls the CLIVE API from outside to prove it answers.

It never creates an order. Re-running it is safe.

Then do step 4 (paste the prompt), and run `bash scripts/server-setup.sh --sync`
for the first SYNC. `--check` re-tests the connection later. Both first make
sure the builder hasn't changed the functions, and redeploy any it has.

To let Cowork do everything, including steps 1 and 4 in Chrome, give it
[COWORK_PROMPT.md](COWORK_PROMPT.md).

The manual steps below do the same by hand.

### 2. Add the secrets in Base44

Base44 dashboard → your app → **Settings → Secrets** (or `npx base44 secrets set NAME=value`):

| Secret | Value |
| --- | --- |
| `SHOPIFY_CLIENT_ID` | from step 1 |
| `SHOPIFY_CLIENT_SECRET` | from step 1 (also signs the webhooks) |
| `SHOPIFY_STORE_DOMAIN` | `5wn03t-nm.myshopify.com` (this is also the default) |
| `PARTNER_API_KEY` | 24+ random characters for CLIVE, e.g. from `openssl rand -hex 32` (leave unset to keep the API off) |
| `PARTNER_API_ALLOW_WRITES` | only set to `true` when you want CLIVE to create orders |

Optional: `SEEDING_DISCOUNT_CODE` (default `INFLUENCER-SEEDING`, the label on
the 100% discount), `POST_WINDOW_DAYS` (default 21), `SHOPIFY_API_VERSION`
(default `2026-07`), `SHOP_CURRENCY` (default `GBP`), `HUB_PUBLIC_URL`
(default `https://crooks-partner-hub.base44.app`).

### 3. Deploy the functions

The ready-to-deploy files are in `base44/functions/<name>/entry.ts`. Each one
is a single self-contained file.

**Back up first:** whatever the builder made under these names is replaced.
Copy the old code out of the dashboard (Code → Functions). Or run
`npx base44 functions pull --app-id 6a96ee08b3aefa8357c55ed7` inside a
**copy** of this folder, never this one, because pull overwrites
`base44/functions`.

**Option A, Base44 CLI.** From this `partner-hub` folder:

```bash
npx base44 login
npx base44 functions deploy --app-id 6a96ee08b3aefa8357c55ed7 \
  shopifyCreateSend shopifySyncCatalog shopifySyncTracking shopifySyncUsage \
  sendMarkShipped shopifyCheckConnection shopifyWebhook portalCheckAvailable partnerApi
```

Use only `functions deploy` with the names. Never run plain `base44 deploy`
or `--force` here: this folder holds no entities or site, and `--force`
deletes remote functions that aren't in it.

**Option B, dashboard.** Base44 dashboard → **Code → Functions**. For each
name above, open (or create) the function with exactly that name, replace its
code with the contents of `base44/functions/<name>/entry.ts`, and save.

### 4. Update the screens

Paste the prompt in [BASE44_PROMPT.md](BASE44_PROMPT.md) into the Base44 AI
chat. It rebuilds the CREATE SEND dialog: every flagged item with its exact
variant and stock, extra items, quantities and a note. It adds MARK SHIPPED,
RECORD POST and CHECK SHOPIFY, makes the TikTok/Instagram markers clickable
links, shows "Cancelled" correctly, replaces the fake Instagram "connect"
(it invents follower counts) and **locks down the data**. Right now anyone
with the app's address can download every influencer's email and home
address. That step is urgent.

### 5. Connect and test

1. As admin, press **CHECK SHOPIFY**. It should show the shop, no missing
   scopes, and the three webhooks `created`/`ok`. Without the button, run
   `shopifyCheckConnection` from Base44's function test panel with
   `{"registerWebhooks": true}`.
2. Press **SYNC**. The catalogue picks up today's stock. The old CROOKS-1869
   send becomes "cancelled", because it was cancelled in Shopify on 2 Sep.
3. Open an influencer, **CREATE SEND** with one in-stock item. Check the
   order in Shopify: £0.00, paid, tag `SEEDING`, their address. If it was
   only a test, cancel it in Shopify with *restock*, then SYNC.
4. Buy the label in Shopify (or let Click & Drop add tracking). Within moments
   the send shows **dispatched** with the tracking number. SYNC catches
   anything the webhook missed.

To dry-run without creating anything, call `shopifyCreateSend` from the
function test panel with `"dryRun": true`. It runs the live stock check and
returns the exact order it would create.

### Optional: hourly sync

Webhooks make tracking near-instant. As a backstop, add a scheduled
automation in Base44 (dashboard → the `shopifySyncTracking` function →
automations, every hour) with the function arguments
`{"key": "<your PARTNER_API_KEY>"}`. The key stays private in Base44, and
without it the sync functions refuse callers who aren't signed in as admin.

## Troubleshooting

| Message | Fix |
| --- | --- |
| "Shopify isn't connected yet…" | Secrets missing (step 2). |
| "Shopify: the access token request was refused…" | Wrong client ID/secret, or the app isn't installed on the store. |
| "Shopify: access denied…" / "…isn't allowed to do this (HTTP 403)" | A scope is missing. CHECK SHOPIFY lists which; add it, release a new version, and approve it in Shopify admin → Apps. |
| "Shopify refused the order: … customer data …" | Turn on protected customer data (name, email, address) in the app settings, step 1.3. |
| "Can't create the order: X: 0 in stock" | Working as intended; pick another size or restock. |
| "…no longer exists in Shopify…" | The product or variant was replaced in Shopify; run SYNC and pick again. |
| "Shopify didn't confirm the order. Don't retry yet…" | Wait a few minutes, press SYNC; the order is linked if Shopify made it. |
| Webhooks show `error` | Check the app is published and `HUB_PUBLIC_URL` is right. SYNC still works without webhooks. |
| Shopify's webhook delivery log shows 401 "Bad or missing Shopify signature" | The secret doesn't match: Dev Dashboard apps sign with the client secret, older custom apps with their API secret key (set `SHOPIFY_WEBHOOK_SECRET`). If it still fails, Base44 may be altering the request body; use the hourly sync above instead. |

## Development

The code is TypeScript in `src/`, split into handlers per function and shared
logic in `lib/`. `npm run build` bundles it into `base44/functions/`, and the
generated files are committed so deploying needs no build step.

```bash
npm install
TZ=UTC npm run verify   # type-check, 76 tests, build, end-to-end smoke test of the built files
```

- `test/` uses fakes for Base44 and Shopify. The fixtures are real responses
  captured from the store on 2026-10-08: the catalogue, a set, an oversold
  tee, a sold-out hoodie, a draft, a deleted variant, a Royal Mail
  fulfilment, and the cancelled CROOKS-1869.
- `scripts/smoke.ts` loads each **built** function in Deno with the real
  `@base44/sdk`, against a local stand-in for the Base44 API. It checks that
  entity calls use the service role and that the main flows work end to end.
- Every Shopify operation in `src/lib/queries.ts` has been validated against
  the Admin API schema, as has the exact `orderCreate` input the code builds.
  `npm run graphql` prints them for re-checking after an API version bump.

`shopify-app/` is the CROOKS Partner Hub Shopify app (extension only): the
`creator-gift` theme app embed that puts the free socks in the bag. See
[CREATOR_GIFT.md](CREATOR_GIFT.md) section 5 for deploying it.
