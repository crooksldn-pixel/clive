# Brief for the Shopify theme editor: the returns page

**Status (2026-10-03):** live at **crooksldn.com/pages/returns**. It replaces AfterShip's returns page. This brief says what's in the theme, what not to touch, and where the returns links still need to go.

## 1. What's in the theme (three files, self-contained)

| File | What it is |
| --- | --- |
| `sections/returns-portal.liquid` | The section "Returns desk": markup, all of its CSS (in `{% stylesheet %}`), and its settings |
| `assets/returns-portal.js` | The `<returns-portal>` custom element: every screen and every call to the returns service |
| `templates/page.returns.json` | The page template `page.returns`: just this one section |

- **Source of truth:** branch `claude/compassionate-dirac-44hnee`, at the repository root alongside the rest of the theme.
- **No dependencies:** it uses no other section, snippet, block or app block. It reads only the theme's font variables (`--font-heading--family`, `--font-body--family`, `--font-crx-mono`), with fallbacks.
- **Where it's installed:**
  - **Live theme "CROOKSLDN — SEO fixes 2026-09-30" (#206162461015):** yes. The **Returns** page (handle `returns`) uses template **returns**.
  - **"CROOKSLDN — Staging" (#202053779799):** an older, yellow version.
  - **"CROOKSLDN — LIVE" (#202044309847):** a copy only. That theme is not the published one, despite its name.

**When the live theme is replaced** (a new published theme, a duplicate or a reset), the three files must go into the new theme too, or `/pages/returns` falls back to an empty page. Push them on their own:

```
shopify theme push --theme <THEME_ID> --allow-live \
  --only sections/returns-portal.liquid --only assets/returns-portal.js --only templates/page.returns.json
```

**Always use `--only`.** A plain push overwrites the whole theme with this repo's copy, which is behind the live theme: the repo has no `--crk-*` / crooks-terminal work in it.

## 2. How it works (so nothing breaks it)

- **Where the data comes from:** the page holds no order data. The JS calls `/apps/returns/api/*` on crooksldn.com. That's a **Shopify app proxy** (app "CROOKS Returns"): Shopify signs the request and forwards it to `https://returns.crooksldn.com/proxy/api/*`. Every decision (eligibility, offers, prices, sizes, drop-off shops) is made there, not in the theme.
- **Don't rename** the section type `returns-portal`, the element `<returns-portal>`, or its `data-endpoint`. Keep the **Returns service path** setting as `/apps/returns/api`.
- **Customer screens:**
  1. Find the order (order number plus email, postcode or phone).
  2. Choose the items and why.
  3. Pick a deal: size swap, store credit with a bonus, or refund. For a free label, also choose the drop-off: Evri / InPost / Royal Mail, with the nearest shops.
  4. Confirm.
  5. Case open.
  6. The case status card. After approval it shows the drop-off QR code, the nearest shops and the label.
- **Deep link:** `/pages/returns?order=CROOKS-2131&proof=name@example.com` pre-fills the lookup. A signed-in customer's email is pre-filled automatically.
- **Saved on the customer's device:** the session (`sessionStorage`) and the cm/in choice for size charts (`localStorage`, `crooks_returns_unit`).

## 3. Look

- **Always dark.** It follows the site's dark palette, with the values copied from the live theme's `--crk-*` tokens:

  | Token | Value |
  | --- | --- |
  | ground | `#0b0a0e` |
  | text | `#ddd7c9` |
  | lavender accent | `#a77ac7` |
  | filled button | `#542578`, lavender border |

- **Edit colours in one place:** the `--rd-*` variables at the top of the section's stylesheet. Everything inside the section uses the `rd-` class prefix, so it can't clash with theme classes.
- **Light mode:** not handled yet; the page stays dark when the site is switched to light. An optional upgrade: map `--rd-ink`, `--rd-bone`, `--rd-accent` and `--rd-purple` to `var(--crk-ground)`, `var(--crk-text)`, `var(--crk-accent)` and `var(--crk-purple)`. Then check that the receipt and the QR card, which use light panels, still read well in both modes.
- **Accent setting:** only applies if it's set to something other than the old yellow `#FFD400`. The saved value is ignored on purpose.

## 4. Section settings (theme editor → page "Returns" → template returns)

| Setting | Default | Notes |
| --- | --- | --- |
| Kicker | CROOKS LDN / Returns desk | |
| Heading | Returns & exchanges | |
| Intro | Wrong size? Swap it free… 14 days from delivery. | |
| Returns service path | `/apps/returns/api` | **Do not change** |
| Contact page | (blank → home) | Set it to the contact page; customers are sent here when something can't be done online |
| Accent | `#A77AC7` | See section 3 |
| Policy heading / Policy summary | Returns policy / short policy | Shown under the form; must match the policy pages (section 6) |

The new policy wording (bonus amounts, drop-off label, 30 days for faulty) is the setting's **default**. A store that already saved the old text keeps it, so paste in the new wording.

## 5. Where to link it

The returns page should be the only place customers are sent for a return:

1. **Footer → Information → "Returns"** (already there): check it points to `/pages/returns`.
2. **Refunds, Shipping, Questions/FAQ and Terms pages:** add a clear "Start a return" link to `/pages/returns`, and take out any AfterShip links or wording.
3. **Track order page:** add a line such as "Need to send something back? Start a return".
4. **Shopify notifications** (Settings → Notifications): order confirmation, shipping confirmation and delivered. Add a "Start a return" button that pre-fills the lookup:
   `https://crooksldn.com/pages/returns?order={{ order_name | url_encode }}&proof={{ email | url_encode }}`
   (`order_name` and `email` are standard notification variables; check the preview shows the order
   number filled in).
5. **Customer accounts:** if the theme or account pages have an "orders" area, add the same link.
6. **Optional:** a "Free size swaps" or "Easy returns" note near the size picker or size guide on product pages, linking to `/pages/returns`. It helps the exchange-first story.

## 6. Policy wording the pages must match

The **Refunds/Terms** pages should say:
- 14 days from delivery to return for a change of mind (unworn, unwashed, tags on). Sale items are treated the same.
- Faulty, wrong or not-as-described items: 30 days, always free, with a full refund available.
- **Exchanges** (size swaps): free, including return postage. The new size ships when the return arrives back.
- **Store credit:** free return postage, plus a bonus: £5 on returns under £40, £10 from £40.
- **Refund to card for a change of mind:** post it yourself, or use our drop-off label at cost (from £2.98), taken off the refund.
- Free labels are printer-free: show the QR code at an Evri, InPost or Post Office drop-off.

## 7. Testing a change safely

- Edit in an unpublished copy and preview with `?preview_theme_id=<ID>` on `/pages/returns`.
- The returns service can be limited to test orders: in Shopify admin → Apps → CROOKS Returns → **Setup** → test order numbers. Use that, not real customer orders, when trying a flow end to end.
- After pushing, hard-refresh. Shopify caches theme assets.
