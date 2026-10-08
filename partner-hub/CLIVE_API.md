# Partner Hub API (for CLIVE)

One endpoint, `partnerApi`, that CLIVE (or any script) can call once the
functions are deployed and the app is published.

```
POST https://crooks-partner-hub.base44.app/api/apps/6a96ee08b3aefa8357c55ed7/functions/partnerApi
Content-Type: application/json
X-Partner-Key: <PARTNER_API_KEY>

{ "action": "<action>", ...parameters }
```

- **Auth:** the `X-Partner-Key` header must equal the `PARTNER_API_KEY`
  secret in Base44. Use 24+ random characters, e.g. `openssl rand -hex 32`;
  a shorter key switches the API off. Don't send the key in `Authorization`,
  because Base44 reads that header as a user login.
- **Writes are off by default.** `createSend`, `markShipped` and `recordPost`
  return 403 until the Base44 secret `PARTNER_API_ALLOW_WRITES` is `true`.
  That fits CLIVE's rule that it proposes and the owner applies. `createSend`
  with `"dryRun": true` always works, so CLIVE can prepare and check an order
  without placing it.
- **Responses:** `{ "ok": true, "action": "...", "data": ... }`. Errors are
  `{ "ok": false, "error": "plain English", "code": "machine_code", "details": ... }`
  with a 4xx/5xx status.
- **Privacy:** list views carry no emails or street addresses.
  `getInfluencer` adds the email, and the city and country they ship to.

## Read actions

| action | parameters | returns |
| --- | --- | --- |
| `ping` | – | `{ app, writesEnabled, time }` |
| `listInfluencers` | `status?` (`pending`/`active`/`paused`/`blocked`), `hasInterests?: true`, `neverSent?: true` | influencers with `tiktok`/`instagram` `{ handle, url, followers }`, `interests` (product, size, variantId, stock), `affiliateCode`, `codeUses`, `sends { total, active, owesPost, last }` |
| `getInfluencer` | `influencerId` or `username` | the above plus `email`, `shipsTo { city, country }`, `sizes { top, bottom }`, `sendHistory[]` |
| `listSends` | `status?`, `influencerId?` | sends with order name/link, carrier, tracking number/link, dispatched/delivered/post-by dates, posted URL |
| `listProducts` | – | catalogue with `availableToInfluencers`, Shopify status and per-variant stock (as of the last catalogue sync) |
| `checkStock` | `items: [{ variantId, quantity? }]` | live from Shopify: `sendable`, per-piece `stock`, `problems` (sets are checked piece by piece) |
| `syncTracking` | – | pulls fulfilment, tracking numbers and cancellations from Shopify into the hub |
| `syncCatalog` | – | refreshes products and stock from Shopify |
| `syncUsage` | – | refreshes affiliate code uses and revenue |

The three sync actions only copy Shopify's data into the hub, so they work
with writes off.

## Write actions (need `PARTNER_API_ALLOW_WRITES=true`)

| action | parameters | does |
| --- | --- | --- |
| `createSend` | `influencerId`, `items: [{ variantId, quantity? }]`, `note?`, `dryRun?` | checks live stock, then creates the gifted Shopify order (100% off, free shipping, tagged `SEEDING`) and the hub's Send record. Same code as the CREATE SEND button. |
| `markShipped` | `sendId`, `trackingNumber`, `carrier`, `trackingUrl?`, `notifyCustomer?` | fulfils the Shopify order with that tracking number and marks the send dispatched |
| `recordPost` | `sendId`, `postedUrl` (https) | marks the send posted and stores the link |

`variantId` takes a Shopify GID (`gid://shopify/ProductVariant/53075854197079`)
or the bare number. Influencers' picks from `listInfluencers` already carry
the right `variantId`.

## Examples

```bash
KEY=...   # the PARTNER_API_KEY secret
URL=https://crooks-partner-hub.base44.app/api/apps/6a96ee08b3aefa8357c55ed7/functions/partnerApi

# Who has picked things but never been sent anything?
curl -s $URL -H "X-Partner-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"action":"listInfluencers","hasInterests":true,"neverSent":true}'

# Will this parcel go through? (live stock, nothing created)
curl -s $URL -H "X-Partner-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"action":"createSend","influencerId":"<id>","items":[{"variantId":"53075854197079"}],"dryRun":true}'

# Who owes a video?
curl -s $URL -H "X-Partner-Key: $KEY" -H 'Content-Type: application/json' \
  -d '{"action":"listSends","status":"overdue"}'
```

## Error codes

| code | meaning |
| --- | --- |
| `unauthenticated` | missing or wrong `X-Partner-Key`, or `PARTNER_API_KEY` unset/too short |
| `writes_disabled` | a write action while `PARTNER_API_ALLOW_WRITES` isn't `true` |
| `stock_check_failed` | something is sold out or deleted. `details.problems` lists each one; nothing was created |
| `send_pending` | the same items were just sent and Shopify hasn't confirmed yet. Run `syncTracking` in a few minutes |
| `shopify_uncertain` | Shopify didn't answer the order request. Don't retry: `syncTracking` links the order if it exists |
| `shopify_rejected` | Shopify refused (message included) |
| `shopify_not_configured` / `shopify_auth` / `shopify_scope` | connection setup; see README troubleshooting |
| `address_missing` / `address_incomplete` / `address_invalid` | the influencer's address needs fixing |
| `influencer_blocked`, `not_found`, `bad_request`, `unknown_action` | as named |
