# SEO/GEO round 2 (16 October 2026)

Work on the open items from the 15 October status report. Admin changes are
live; theme changes are on an unpublished copy for George to publish.
`admin-backup/` holds every value as it was before it changed, so each change
can be put back.

## Changed in Shopify admin (live)

| What | Before | After | Finding |
|---|---|---|---|
| Accessories description | "Socks, bags and extras." (the only bag is archived) | 47 words on MotionTec socks, colourways and pack prices | C5, G10 |
| Accessories meta description | 161 characters | 139 characters | M1 |
| Tracksuits description | none | 51 words on the three Convict sets | C4 |
| Returns page meta description | none | "Return or swap a CROOKSLDN order within 14 days of delivery. Size swaps are free, and faulty or wrong items always return free." | M1 |
| FAQ meta description | 167 characters | 145 characters | M1 |
| Double-Agent Puffa page title / meta description | none | "Double-Agent Puffa \| Heat-Reactive Puffer Jacket" / 147 characters | M1 |
| Product facts (crooks.fabric / crooks.cut) | on 9 of 21 products | on 19 of 21; only from each product's own title or description; origin and care left alone where unknown | G8 |
| Grey Convict Sweats fabric | "500gsm cotton" (title and description say 550gsm brushed fleece) | "550gsm brushed fleece" | G10 |
| T-shirt Week page | none | /pages/t-shirt-week on the T-shirt Week template, own title and description; **hidden**, because T-shirt Week is switched off | — |
| Buyer article | blog empty | "Convict 550gsm vs Cellblock 450gsm: how they fit", **hidden draft** in Blog › News (`article/`) | G7, G11, G15 |

## Theme copy #207329132887 (unpublished)

"CROOKSLDN — SEO round 2 (from live 16 Oct)", a copy of live made on 16 Oct.

- `snippets/crooks-schema-offer-state.liquid` (new): an offer is PreOrder at the
  plan's price when the CROOKS Operations app sells that size as a pre-order
  (app id `clive-preorders`), the same test the app uses on the page.
  Pink Convict Sweats M, L and XL: InStock £60 → PreOrder £51.
- `snippets/crooks-schema-product.liquid`, `snippets/crooks-schema-shipping.liquid`:
  use it; a pre-order offer keeps its shipping rate but drops the 0–2 day
  delivery time.
- `sections/crooks-header.liquid`: while /pages/t-shirt-week is visible, the
  T-SHIRT WEEK link goes there instead of the FAQ view.
- `sections/crooks-sightings.liquid`: a frame with no alt text falls back to the
  piece it links to, so no image goes out without alt.
- `templates/index.json`: alt text on the two homepage photos (diff in
  `theme-207329132887-index-json.diff`; the repo's homepage template differs
  from the editor's, so it is not changed here).

Checked through the preview: 21 product pages, valid JSON-LD, only the three
pre-order offers changed; both photos have alt text and no homepage image lacks
one; with T-shirt Week switched on and the page hidden, the link stays on the
FAQ view (the switch was put back off afterwards).

## Not done, and why

| Item | Why |
|---|---|
| Denim, Tees, Sweats, New, ALL: titles, descriptions, meta (D1, D2, D4) and Denim membership (D3) | The connector's Admin API cannot see these five collections (it lists 9 of the store's 13) |
| Unpublish denim-1, new-1, sweats-1, tees-1 (D3) | Unpublishing is blocked by the connector's safety policy. The redirects already exist |
| Refund policy and policy emails (D7) | The connector has read-only access to legal policies |
| Replace heavy images (D5) | Tested on the heaviest file (2048px PNG, 3.5 MB): browsers already get Shopify's WebP at 1400px, 240 KB; a re-encoded WebP source is 208 KB; a resized lossless PNG is no smaller (1,889 KB); only a 256-colour PNG (363 KB) shrinks what non-WebP crawlers get, and it would degrade the photo for everyone |
| PageSpeed (D10) | Google's keyless quota was used up on both days |

## Found on the way

An older app's selling plan group, "preorder" (app id `ReStock`, 0% discount),
is still attached to 480 variants. The CROOKS Operations app and the theme
ignore it; if ReStock is no longer used, its plans can be removed in that app
or by uninstalling it.
