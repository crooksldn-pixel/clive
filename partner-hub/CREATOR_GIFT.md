# Creator gift: a code that puts free socks in the bag

A UK creator code (e.g. `BILLYJPEG`) puts a 1-pair pack of MOTIONTEC socks
in the customer's bag at £0. They see it in the bag and as a £0 line in
checkout before they pay. 15% codes (ALESSIA, OKQ8) work as normal discounts
and need nothing here.

Two ways a code reaches the bag:

1. **The code box in the cart.** Horizon's cart drawer and cart page
   already have one (`cart-discount-component`). It's switched on live.
2. **The creator's link** `https://crooksldn.com/discount/BILLYJPEG`. The
   code sits on the cart, and the socks go in as soon as there's a piece in
   the bag.

**The one limit.** On the Shopify plan, nothing can add a line inside
checkout; that's Plus-only for every app. If someone ignores the bag and types
a sock code in Shopify's checkout box with no socks in the bag, Shopify rejects
it with its own message. The bag prompt and creators saying "put my code in
your bag" cover this.

Checked against the live site on 9 Oct 2026: theme "CROOKSLDN — SEO fixes
2026-09-30" (Horizon), `cart-discount-component` defined, `/cart.js` returns
`discount_codes: [{ code, applicable }]`.

## Pieces

| Piece | Where | Runs on |
| --- | --- | --- |
| Sock discount per code (Shopify Buy X Get Y) | `shopifyCreateDiscount` in the Partner Hub | Base44 → Shopify Admin API |
| Gift rules (which codes, which socks) | App-data metafield on the CROOKS Partner Hub app installation, written by `syncPromotions` | Base44 → Shopify |
| Bag script (adds/removes/swaps the socks) | Theme app embed `creator-gift` in the CROOKS Partner Hub Shopify app | crooksldn.com |
| Promotions tab | Partner Hub admin (Base44 builder) | Base44 |

No new Shopify app, no new server, no theme code edits, no new permissions.
The Hub's app already has `write_discounts`, and writing its own app-data
metafield needs no scope.

## 1. The discount (replaces today's `shopifyCreateDiscount`)

Today's version (builder-made, backed up in
`~/.config/crooks-partner-hub/backup-20261009-011928`) can't work and has a
hole:

- Buy X Get Y doesn't accept `items: { all: true }` for what the customer
  buys (Shopify: "Not supported for Buy X get Y discounts").
- It sends no `context`, which Shopify requires when creating a code
  discount.
- It makes **any** sock product free, so a 12-pack (£45) or 6-pack (£25) goes
  for £0.

Move it into this repo (`src/handlers/shopifyCreateDiscount.ts`, built into
`base44/functions/shopifyCreateDiscount/entry.ts`). Add it to `FUNCTIONS` in
`scripts/server-setup.sh` and to the "maintained outside the builder" list in
`BASE44_PROMPT.md`. Keep the request and response the frontend already uses:
`{ code }` from the affiliate tab, `{ code, type, value, influencerId,
override: true }` from the admin override, returning `{ discountId, type,
value }`.

Free socks (`type: "free_socks"`). This was validated against the Admin API
schema:

```graphql
discountCodeBxgyCreate(bxgyCodeDiscount: {
  title: "SEEDING BILLYJPEG"
  code: "BILLYJPEG"
  startsAt: <now>
  context: { all: ALL }
  appliesOncePerCustomer: true          # unchanged from today
  usesPerOrderLimit: 1
  combinesWith: { orderDiscounts: false, productDiscounts: false, shippingDiscounts: false }
  customerBuys: {
    items: { collections: { add: [<qualifying collection id>] } }
    value: { quantity: "1" }
  }
  customerGets: {
    items: { products: { productVariantsToAdd: [
      "gid://shopify/ProductVariant/53455222964567",   # BLACK/BLUE MOTIONTEC 1pc
      "gid://shopify/ProductVariant/53456567238999"    # WHITE/RED MOTIONTEC 1pc
    ] } }
    value: { discountOnQuantity: { quantity: "1", effect: { percentage: 1.0 } } }
  }
})
```

Percentage (`type: "percentage"`): `discountCodeBasicCreate` with
`context: { all: ALL }`, `customerGets: { items: { all: true }, value: {
percentage: value / 100 } }`, same title, `appliesOncePerCustomer` and
`combinesWith`.

Gift variant IDs and the qualifying collection come from the Promotion record
(section 4), not hard-coded.

**Override (admin).** Shopify codes are unique, so the current "old
discount stays live either way" can't happen.
- Same type, new value: update in place (`discountCodeBxgyUpdate` /
  `discountCodeBasicUpdate`).
- Type changes: delete the old discount by its stored id, then create the new
  one, then save the new id. If the create fails after the delete, return an
  error that says the code is currently off in Shopify.

Change the override hint text to match.

**Pausing.** When an influencer's status leaves `active`, deactivate their
discount (`discountCodeDeactivate`). Reactivate it (`discountCodeActivate`)
when they come back. Both run through `syncPromotions`.

### Qualifying collection (George, 2 minutes, once)

Buy X Get Y needs a collection for "buys any piece". In Shopify admin →
Products → Collections → Create collection:

- Title: `Creator gift – qualifying` (any name works).
- Type: Smart. Condition: **Product type is not equal to Socks**.
- Sales channels: untick Online Store so it never shows on the site.

That catches all current pieces, including the cap and puffa with a blank
type, and new drops automatically. Paste its ID into the Promotions tab. Doing
it by hand keeps the app off `write_products`.

## 2. Gift rules metafield

`syncPromotions` (new Hub function, admin-only or `PARTNER_API_KEY`) writes
one app-data metafield on the app installation:

- Get the owner: `query { currentAppInstallation { id } }`.
- `metafieldsSet` with `ownerId: <AppInstallation id>`, `namespace:
  "creator_gift"`, `key: "rules"`, `type: "json"`.

Value:

```json
{
  "v": 1,
  "gift": {
    "variantIds": [53455222964567, 53456567238999],
    "excludeProductTypes": ["Socks"],
    "label": "MOTIONTEC socks"
  },
  "codes": ["BILLYJPEG", "E1LISSPAM", "KATE"],
  "updatedAt": "2026-10-09T16:30:00Z"
}
```

- `codes`: uppercase codes from `AffiliateCode` where `type == "free_socks"`,
  the influencer is `active`, and `shopifyDiscountId` is set.
- `variantIds`: in order of preference. The script uses the first one in
  stock.

Run it after every create, override, pause or unpause, and at the end of SYNC.

These codes end up in the page source. They're shared publicly by creators
anyway, and paused ones are left out.

## 3. Bag script (theme app embed)

New Shopify CLI project at `partner-hub/shopify-app/`, linked to the existing
app. Don't create a new app:

```
partner-hub/shopify-app/
  shopify.app.toml                       # from `shopify app config link`, client_id 1857f2241edff09b0ce6a8e3b3030e38
  extensions/creator-gift/
    shopify.extension.toml               # type = "theme"
    blocks/creator-gift.liquid           # app embed, target "body"
    assets/creator-gift.js
    assets/creator-gift.css
```

`creator-gift.liquid`:
- Prints `{{ app.metafields.creator_gift.rules.value | json }}` into a
  `<script type="application/json" id="crooks-gift-rules">`.
- Loads the JS and CSS through the schema's `javascript` and `stylesheet`.
- Has no settings. Rules only come from the Hub.

`creator-gift.js` is plain JS with no dependencies. Keep a pure
`reconcile(cart, rules)` that returns the actions, and a thin layer that runs
them, so it can be unit-tested.

**Definitions** (from `/cart.js`):
- *gift code*: the first entry of `cart.discount_codes` whose `code`,
  uppercased, is in `rules.codes`.
- *gift line*: an item whose `properties._crooks_gift` is set. Horizon and
  checkout hide `_` properties.
- *qualifying item*: a non-gift item whose `product_type` isn't in
  `excludeProductTypes`.

**Rules:**

| Cart state | Action |
| --- | --- |
| Gift code, ≥1 qualifying item, no gift line | `POST /cart/add.js` first in-stock `variantIds` entry, qty 1, `properties: { _crooks_gift: CODE }`. On 422 (sold out) try the next; if none, show "Free socks are sold out right now". |
| Gift line but no gift code, or no qualifying item | Remove gift lines (`/cart/change.js`, qty 0) |
| Gift line qty > 1 | Set it to 1 |
| More than one gift line | Keep the first, remove the rest |

The socks are only free when a piece is in the bag ("buy 1 qualifying, get
socks"), so the script never leaves free socks on their own.

**Hooking into Horizon** (checked in `assets/cart-discount.js`,
`assets/events.js` and `assets/component-cart-items.js`):

- **On load:** fetch `/cart.js` and reconcile. This covers the link route.
- **Cart and discount events:** listen on `document` for `cart:update` and
  `discount:update`, then re-fetch and reconcile. Ignore events whose
  `detail.sourceId === 'crooks-gift'`.
- **The code box:** Horizon marks a code that isn't applying yet as invalid
  and clears it. So intercept `submit` on `form.cart-discount__form` with a
  capture listener on `window`:
  - If the entered code (trimmed, uppercased) is in `rules.codes`, the cart
    has a qualifying item and no gift line: `preventDefault()` and
    `stopImmediatePropagation()`, add the gift, set
    `form.dataset.crooksGiftReady = '1'`, then call `form.requestSubmit()`.
    Horizon then applies the code (now applying), re-renders, and shows the
    pill and the £0 socks line.
  - If there's no qualifying item, let Horizon run, and show under the box:
    "Add any CROOKS piece to your bag to unlock free socks with {CODE}."
- **After any add or remove the script does itself:** dispatch a refresh
  event:

  ```js
  document.dispatchEvent(new CustomEvent('cart:update', { bubbles: true,
    detail: { resource: cart, sourceId: 'crooks-gift', data: { source: 'crooks-gift', itemCount: cart.item_count } } }));
  ```

  `data` must be present; Horizon reads `detail.data.sections`.

**Bag UI** (inside `cart-discount-component`, matching Horizon type and
spacing):
- Prompt above the box when no gift code is on: "Creator code? Enter it
  here for free socks."
- When the gift is in: "Free MOTIONTEC socks added with {CODE}", plus a
  "Swap to White/Red" (or Black/Blue) link. Swapping replaces the gift
  line's variant: remove, then add the other variant with the same
  property.
- Hide the swap when the other colour is sold out.

**Not in scope:** product pages, checkout (not possible on this plan),
anything for 15% codes.

## 4. Partner Hub changes (Base44 builder prompt)

Add to `BASE44_PROMPT.md` as a new section:

- **New entity `Promotion`:** `name`, `active` (bool),
  `giftVariantIds` (number[], ordered), `qualifyingCollectionId` (string),
  `excludeProductTypes` (string[]).
  - Seed one record: "Creator socks", active, `[53455222964567,
    53456567238999]`, `["Socks"]`, collection ID empty until George adds
    it.
- **Admin → Promotions tab:**
  - Edit that record.
  - List every free-socks code with: influencer, active/paused, Shopify
    discount id present (yes/no), uses.
  - A "SYNC GIFT RULES" button calling
    `base44.functions.invoke("syncPromotions", {})`, showing `codes` and
    `updatedAt` from the response.
  - A short how-to: "Theme editor → App embeds → Creator gift must be
    on."
- **Influencer portal → Affiliate tab (UK, free_socks):** the share line
  says "Use code {CODE} in your bag for free MOTIONTEC socks" and shows the
  link `crooksldn.com/discount/{CODE}`.
- **Admin code override:** replace "Old discount stays live either way."
  with "Replaces the Shopify discount for this code."
- The builder must not create, edit or delete `shopifyCreateDiscount` or
  `syncPromotions`.

## 5. Deploying the Shopify app

1. Create the project with `shopify app init` as an **extension-only app**.
   When it asks, connect to the existing "CROOKS Partner Hub" app and never
   create a new one. Then run `npx shopify app config link` and choose
   "CROOKS Partner Hub" again. The sign-in uses George's Dev Dashboard account.
   Afterwards the Dev Dashboard app list should still show only Threads
   software, CROOKS Operations, API and CROOKS Partner Hub.
2. **Before deploying, check `shopify.app.toml` has exactly the live scopes.**
   Deploy replaces the active version's config, so a missing scope breaks the
   Hub:
   `read_products, read_inventory, write_orders,
   write_merchant_managed_fulfillment_orders, read_discounts, read_locations,
   read_fulfillments, write_discounts`.
   - Also keep `application_url = "https://example.com"`, `embedded = true`,
     and webhooks `api_version = "2026-10"`. The three order/fulfilment
     webhooks are registered per shop by `shopifyCheckConnection` and aren't
     in the TOML.
3. `npx shopify app deploy` releases a new version with the embed. Scopes are
   unchanged, so there's no approval in Shopify admin.
4. Run `bash scripts/server-setup.sh --check` afterwards. It must still say
   "All Shopify permissions granted".

## 6. Tests

**Unit** (`test/creator_gift_test.ts`, Deno, alongside the 49 existing):
- `reconcile()` covers every row of the rules table: sold-out fallback,
  only-socks cart, gift qty 2, two gift lines, paused code not in rules, and a
  lowercase code.
- `shopifyCreateDiscount` builds exactly the two inputs above, using
  `productVariantsToAdd` and never `productsToAdd`.
- Override update vs delete-and-create.
- `syncPromotions` code filtering.
- Fakes as in `test/fakes.ts`.

**Live, on a duplicate theme only.** Online Store → Themes → duplicate the
live theme → turn on the Creator gift embed on the **duplicate** → use its
preview link. Playwright. **Never place an order;** stop on the checkout page.

1. Hoodie in bag → `BILLYJPEG` in the cart box → socks line £0, pill shows,
   no error.
2. Go to checkout → socks line shows £0 and `BILLYJPEG` is applied.
3. Remove the code → socks gone. Remove the hoodie with code on → socks
   gone.
4. Open `/discount/BILLYJPEG`, then add a hoodie → socks added without
   typing.
5. Code with an empty bag → "Add any CROOKS piece…" message, no socks.
6. Gift qty set to 2 → back to 1. Swap colour → variant changes, still £0.
7. `ALESSIA` → 15% off, no socks.
8. Screenshot each step.

## 7. Rollout (G = George)

1. Build and unit-test. Deploy `shopifyCreateDiscount` and `syncPromotions`
   with `server-setup.sh`.
2. **G:** create the qualifying collection and paste its ID in Promotions.
3. **G says go →** create the 5 active codes:
   - KATE, E1LISSPAM, BILLYJPEG: socks.
   - ALESSIA, OKQ8: 15%.
   - Skip the paused CROOKSLDN and THREADSALLIANCE.
   - Then SYNC GIFT RULES.
4. Deploy the Shopify app version (section 5).
5. Live tests on the duplicate theme (section 6). Send G the screenshots.
6. **G:** turn on the Creator gift embed on the live theme.
7. Re-run test 1 on the live site without checking out, then empty the bag.

## Claude Code prompt

```text
Build the creator gift in crooksldn-pixel/clive, folder partner-hub, following
partner-hub/CREATOR_GIFT.md exactly. Read it, README.md and
scripts/server-setup.sh first.

Ground rules
- Never create, cancel or edit a Shopify order; never change products, prices
  or stock. Never place a test order: stop on the checkout page.
- Never run `base44 deploy`, `base44 entities push`, or anything with --force.
- Ask me before: creating any Shopify discount, `shopify app deploy`, and
  turning on the embed on the live theme. Test only on a duplicate theme.
- shopify.app.toml must keep exactly the eight live scopes in section 5.
- Never print the Shopify client secret or the CLIVE API key.
- If anything in the live store or theme doesn't match the spec, stop and
  tell me what you see.
- Run the checks with TZ=UTC (e.g. `TZ=UTC bash scripts/server-setup.sh`).
  One existing tracking test fails on London time.

Done means: unit tests pass with the existing 49; the functions deploy and
`server-setup.sh --check` passes; the section 6 live tests pass on the
duplicate theme with screenshots; you've listed what's left for me (collection,
go-ahead for codes, embed on live).
```
