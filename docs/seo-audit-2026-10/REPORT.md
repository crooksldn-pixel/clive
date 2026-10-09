# CROOKSLDN: Promptd SEO/GEO audit, implementation report

9 October 2026. Audit: Promptd, "CrooksLDN AI search & website review", October 2026.

No audit fix is live yet. Every theme fix is on an unpublished copy of the live theme and on the git branch, and was checked there against the live store's own data. Of the audit's 51 findings, 10 are fixed, 13 are partly fixed and wait on admin copy or data, 14 need action outside the theme, and 14 needed no change.

| State | Status | Where |
|---|---|---|
| Code updated | Yes | Unpublished theme "CROOKSLDN — SEO-GEO audit fixes 2026-10-08" (#206765785431); git branch `claude/crooksldn-theme-init-bnen7a`, commit `9ffde766` |
| Deployed to live site | No | Live theme #206162461015 is unchanged |
| Verified on live site | No | Verified on #206765785431 through Shopify's theme preview; re-run after publishing (D10) |

## How it was verified

The baseline was captured from the live theme before any change; the same 52 URLs were then rendered by the new theme and compared.

- **URLs:** every sitemap URL, plus the cart, search, search for "jeans", a variant URL and a nested product URL (52; 50 return pages, 2 are a markdown file and a redirect).
- **Before:** live theme #206162461015, fetched 8 Oct 2026. **After:** theme #206765785431 on the live store through Shopify's theme preview; every page was checked to carry that theme's id.
- **Read from page source:** title, meta description, robots, canonical, Open Graph, h1s, every JSON-LD block (parsed as JSON), every image's loading, fetchpriority and srcset.
- **JSON-LD graph check:** every @id reference resolves on the page, no duplicate top-level objects, every offer has price, currency, availability, seller and shipping, and the shipping rate matches the price.
- **Largest paint:** Chromium at 390×844 (iPhone size), live and new theme side by side.
- **Regression:** a Chromium walk of both themes: home, mobile menu, two collections, a product (pick a size, add to bag), cart, search, tracking, FAQ.
- **Lint and uploads:** Shopify theme-check before and after; every uploaded file checked by MD5 against the repo.
- **Evidence:** all of it is in the repo under `docs/seo-audit-2026-10/` (index in its README).

One bug of my own was caught this way and fixed: the first upload escaped "&" twice in titles ("Socks &amp;amp; Accessories"). All 50 pages were re-checked after the fix.

## Finding by finding

One row per finding, in the audit's order. Locations are in the repo at commit `9ffde766`; evidence paths are under `docs/seo-audit-2026-10/`.

### Findings 1–6: AI visibility and technical triage (pp. 2–5)

| # | Audit Finding | Audit Recommendation | Before | Change Made | Location | Evidence After | Status |
|---|---|---|---|---|---|---|---|
| 1 (A1) | Brand recognition in AI answers is low (OpenAI 4/20, Perplexity 7/20, Gemini 5/20). | Give search and AI systems clearer, more consistent evidence about the brand and its products. | Organization and WebSite JSON-LD on every page (name, alternateName, logo, sameAs, contact). No legal name, no Brand entity; product brand and offer seller were unlinked name strings. | Organization gains legalName "Crooks Clothing Company Ltd" (from the Terms of Service), a Brand node and the store return policy. Product brand and offer seller now point at the same @ids. WebSite gains inLanguage. | snippets/crooks-schema-site.liquid:96-150; snippets/crooks-schema-product.liquid:144, 161, 182, 200 | All 50 pages: Organization with legalName, brand, hasMerchantReturnPolicy. 0 unresolved @id references. 21 of 21 product pages: brand @id https://crooksldn.com#brand, seller @id https://crooksldn.com#organization. | 🟡 PARTIALLY FIXED |
| 2 (A2) | Visibility differs by platform: 18% market position on OpenAI and Perplexity, 3.5% on Gemini. | Directional only; consistent evidence across platforms. | A grader snapshot, not a site state. | None. Nothing on the site answers this beyond A1. | - | - | ⚪ NOT APPLICABLE |
| 3 (A3) | Weaker signals: limited third-party reviews, uneven independent coverage, stronger competitors in some shortlists. | Make the story easier to verify outside CrooksLDN's own channels. | No review app, no review data on the site. | None in the theme. No rating or review markup added: there are no genuine reviews to mark up. | - | Product JSON-LD carries no AggregateRating or Review (correctly absent). | 🔵 EXTERNAL ACTION REQUIRED |
| 4 (A4) | Weaker signal: delivery delays and communication. | Clear, consistent delivery communication (implied). | Delivery terms in copy only (status bar, FAQ, tracking page). No machine-readable delivery times. | Every UK offer now states handling 0-2 days, transit 1-2 days and its rate (£3.00, free from £30), the store's own Tracked 48 terms (counted under G2). The delays themselves are operational. | snippets/crooks-schema-shipping.liquid (new) | 119 offers on 21 product pages carry OfferShippingDetails. | 🔵 EXTERNAL ACTION REQUIRED |
| 5 (T1) | 96 canonicalised URLs flagged High: product variant URLs pointing to the clean product URL. | NO ACTION: standard Shopify canonical handling. | `?variant=53639822377303` canonicalises to `https://crooksldn.com/products/blue-wash-yard-jeans`. | None (correct as it is). | snippets/meta-tags.liquid (canonical_url, unchanged) | Same canonical on the new theme. | ⚪ NOT APPLICABLE |
| 6 (T2) | 3 URLs blocked by robots.txt (account, checkout preload, authentication). | NO ACTION: keep utility and login areas blocked. | Shopify default robots.txt; the theme has no robots.txt.liquid. | None. robots.txt not touched. | - | evidence/robots.txt unchanged. | ⚪ NOT APPLICABLE |

### Findings 7–23: page titles (pp. 6–8)

| # | Audit Finding | Audit Recommendation | Before | Change Made | Location | Evidence After | Status |
|---|---|---|---|---|---|---|---|
| 7 (P1) | Homepage title slightly too long. | "Crooks London Streetwear \| Fleece, Denim & Tees" (Online Store > Preferences). | `Crooks London \| CROOKSLDN Streetwear: Fleece, Denim & Tees` (58 chars), from the theme's 30 Sept fallback. | The fallback now uses the audit's wording. It applies only while the Preferences title is blank; anything typed there wins. | snippets/meta-tags.liquid:45-52 | `Crooks London Streetwear \| Fleece, Denim &amp; Tees` (47 chars). | ✅ FIXED |
| 8 (P2) | /products/grey-wash-yard-jeans title too long (audit: "Grey Wash Yard Jeans — 14oz Straight Leg Denim \| CROOKSLDN"). | "Grey Wash Yard Jeans \| 14oz Straight Leg Denim" | `Grey Wash Yard Jeans — 14oz Straight Leg Denim \| CROOKSLDN` (58 chars) | Title rule: an admin-typed " \| CROOKSLDN" is taken off, then put back only if the whole title stays within 56 characters (every title the audit passed was 56 or under). No admin edit needed; future products follow the same rule. | snippets/meta-tags.liquid:97-136 | `Grey Wash Yard Jeans — 14oz Straight Leg Denim` (46 chars) | ✅ FIXED |
| 9 (P3) | /products/grey-wash-yard-jorts title too long (audit: "Grey Wash Yard Jorts — 14oz Baggy Denim Shorts \| CROOKSLDN"). | "Grey Wash Yard Jorts \| 14oz Baggy Denim Shorts" | `Grey Wash Yard Jorts — 14oz Baggy Denim Shorts \| CROOKSLDN` (58 chars) | Title rule: an admin-typed " \| CROOKSLDN" is taken off, then put back only if the whole title stays within 56 characters (every title the audit passed was 56 or under). No admin edit needed; future products follow the same rule. | snippets/meta-tags.liquid:97-136 | `Grey Wash Yard Jorts — 14oz Baggy Denim Shorts` (46 chars) | ✅ FIXED |
| 10 (P4) | /products/blue-wash-yard-jorts title too long (audit: "Blue Wash Yard Jorts — 14oz Baggy Denim Shorts \| CROOKSLDN"). | "Blue Wash Yard Jorts \| 14oz Baggy Denim Shorts" | `Blue Wash Yard Jorts — 14oz Baggy Denim Shorts \| CROOKSLDN` (58 chars) | Title rule: an admin-typed " \| CROOKSLDN" is taken off, then put back only if the whole title stays within 56 characters (every title the audit passed was 56 or under). No admin edit needed; future products follow the same rule. | snippets/meta-tags.liquid:97-136 | `Blue Wash Yard Jorts — 14oz Baggy Denim Shorts` (46 chars) | ✅ FIXED |
| 11 (P5) | /products/hydrocuff-windbreaker title too long (audit: "HydroCuff Windbreaker — Water-Reactive Jacket \| CROOKSLDN"). | "HydroCuff Windbreaker \| Water-Reactive Jacket" | `HydroCuff Windbreaker — Water-Reactive Jacket \| CROOKSLDN` (57 chars) | Title rule: an admin-typed " \| CROOKSLDN" is taken off, then put back only if the whole title stays within 56 characters (every title the audit passed was 56 or under). No admin edit needed; future products follow the same rule. | snippets/meta-tags.liquid:97-136 | `HydroCuff Windbreaker — Water-Reactive Jacket` (45 chars) | ✅ FIXED |
| 12 (P6) | /products/blue-wash-yard-jeans title too long (audit: "Blue Wash Yard Jeans — 14oz Straight Leg Denim \| CROOKSLDN"). | "Blue Wash Yard Jeans \| 14oz Straight Leg Denim" | `Blue Wash Yard Jeans — 14oz Straight Leg Denim \| CROOKSLDN` (58 chars) | Title rule: an admin-typed " \| CROOKSLDN" is taken off, then put back only if the whole title stays within 56 characters (every title the audit passed was 56 or under). No admin edit needed; future products follow the same rule. | snippets/meta-tags.liquid:97-136 | `Blue Wash Yard Jeans — 14oz Straight Leg Denim` (46 chars) | ✅ FIXED |
| 13 (P7) | /collections/denim title "Denim – CROOKSLDN" is very short. | "Men's Denim Jeans & Jorts \| CROOKSLDN" (collection Search engine listing). | `Denim – CROOKSLDN` (18 chars). | Separator now matches the rest of the site (" \| "). The wording itself is collection data in admin (D1). | snippets/meta-tags.liquid:97-136 | `Denim \| CROOKSLDN` | 🔵 EXTERNAL ACTION REQUIRED |
| 14 (P8) | /collections/new title "New – CROOKSLDN" is very short. | "New Streetwear Arrivals \| CROOKSLDN" (collection Search engine listing). | `New – CROOKSLDN` (16 chars). | Separator now matches the rest of the site (" \| "). The wording itself is collection data in admin (D1). | snippets/meta-tags.liquid:97-136 | `New \| CROOKSLDN` | 🔵 EXTERNAL ACTION REQUIRED |
| 15 (P9) | /collections/all title "ALL – CROOKSLDN" is very short. | "Shop CROOKSLDN Streetwear \| All Clothing" (collection Search engine listing). | `ALL – CROOKSLDN` (16 chars). | Separator now matches the rest of the site (" \| "). The wording itself is collection data in admin (D1). | snippets/meta-tags.liquid:97-136 | `ALL \| CROOKSLDN` | 🔵 EXTERNAL ACTION REQUIRED |
| 16 (P10) | /collections/tees title "Tees – CROOKSLDN" is very short. | "Streetwear T-Shirts & Graphic Tees \| CROOKSLDN" (collection Search engine listing). | `Tees – CROOKSLDN` (17 chars). | Separator now matches the rest of the site (" \| "). The wording itself is collection data in admin (D1). | snippets/meta-tags.liquid:97-136 | `Tees \| CROOKSLDN` | 🔵 EXTERNAL ACTION REQUIRED |
| 17 (P11) | /collections/sweats title "Sweats – CROOKSLDN" is very short. | "Hoodies, Sweatshirts & Joggers \| CROOKSLDN" (collection Search engine listing). | `Sweats – CROOKSLDN` (19 chars). | Separator now matches the rest of the site (" \| "). The wording itself is collection data in admin (D1). | snippets/meta-tags.liquid:97-136 | `Sweats \| CROOKSLDN` | 🔵 EXTERNAL ACTION REQUIRED |
| 18 (P12) | /policies/refund-policy title "Refund policy – CROOKSLDN". | Low priority: leave simple. | `Refund policy – CROOKSLDN` | Separator only, to match the rest of the site. | snippets/meta-tags.liquid:97-136 | `Refund policy \| CROOKSLDN` | ⚪ NOT APPLICABLE |
| 19 (P13) | /pages/tracking title "Track Your Order \| CROOKSLDN". | Optional: only if the page should be indexed. | `Track Your Order \| CROOKSLDN` (28 chars), indexable. | Decision: keep it indexable (it answers "how do I track my CROOKSLDN order"). The title is already descriptive, so it is unchanged. | - | `Track Your Order \| CROOKSLDN` | ⚪ NOT APPLICABLE |
| 20 (P14) | /policies/shipping-policy title "Shipping policy – CROOKSLDN". | Low priority: leave simple. | `Shipping policy – CROOKSLDN` | Separator only. | snippets/meta-tags.liquid:97-136 | `Shipping policy \| CROOKSLDN` | ⚪ NOT APPLICABLE |
| 21 (P15) | /search title "Search – CROOKSLDN". | Optional: only if the page should be indexed. | `Search – CROOKSLDN`; no robots meta, so every results URL was indexable. | Decision: internal search results are kept out of the index (`noindex, follow`), so the title is left plain. | snippets/meta-tags.liquid:248-259 | `Search \| CROOKSLDN` plus `<meta name="robots" content="noindex, follow">`. | ⚪ NOT APPLICABLE |
| 22 (P16) | /policies/terms-of-service title "Terms of service – CROOKSLDN". | Low priority: leave simple. | `Terms of service – CROOKSLDN` | Separator only. | snippets/meta-tags.liquid:97-136 | `Terms of service \| CROOKSLDN` | ⚪ NOT APPLICABLE |
| 23 (P17) | /policies/privacy-policy title "Privacy policy – CROOKSLDN". | Low priority: leave simple. | `Privacy policy – CROOKSLDN` | Separator only. | snippets/meta-tags.liquid:97-136 | `Privacy policy \| CROOKSLDN` | ⚪ NOT APPLICABLE |

### Findings 24–31: content and headings (p. 9)

| # | Audit Finding | Audit Recommendation | Before | Change Made | Location | Evidence After | Status |
|---|---|---|---|---|---|---|---|
| 24 (C1) | /collections/denim low content (69 words in the audit's crawl). | 80-150 useful words on the collection (Collections > Description); the theme must show it. | Description "Jorts, jeans and denim." (4 words) existed but was written only into the JSON-LD, never onto the page. | The collection description now prints under the heading on collection pages; nothing prints while it is empty. The copy is admin work (draft in D2). | sections/crooks-exhibit-log.liquid:161-172, 803-809 | Visible on the page: `<div class="crk-log__intro">Jorts, jeans and denim.</div>` (screenshot cmp-collection-denim.jpg). Still 4 words. | 🟡 PARTIALLY FIXED |
| 25 (C2) | /collections/tees low content (96 words in the audit's crawl). | 80-150 useful words on the collection (Collections > Description); the theme must show it. | Description "All CROOKSLDN tees." (3 words), JSON-LD only. | The collection description now prints under the heading on collection pages; nothing prints while it is empty. The copy is admin work (draft in D2). | sections/crooks-exhibit-log.liquid:161-172, 803-809 | Visible: `All CROOKSLDN tees.` Still 3 words. | 🟡 PARTIALLY FIXED |
| 26 (C3) | /collections/sweats low content (166 words in the audit's crawl). | 80-150 useful words on the collection (Collections > Description); the theme must show it. | Description "Hoodies, crewnecks, joggers and shorts." (5 words), JSON-LD only. | The collection description now prints under the heading on collection pages; nothing prints while it is empty. The copy is admin work (draft in D2). | sections/crooks-exhibit-log.liquid:161-172, 803-809 | Visible: `Hoodies, crewnecks, joggers and shorts.` Still 5 words. | 🟡 PARTIALLY FIXED |
| 27 (C4) | /collections/tracksuits low content (142 words in the audit's crawl). | 80-150 useful words on the collection (Collections > Description); the theme must show it. | No description at all. | The collection description now prints under the heading on collection pages; nothing prints while it is empty. The copy is admin work (draft in D2). | sections/crooks-exhibit-log.liquid:161-172, 803-809 | Nothing to show until a description is written. | 🟡 PARTIALLY FIXED |
| 28 (C5) | /collections/accessories low content (79 words in the audit's crawl). | 80-150 useful words on the collection (Collections > Description); the theme must show it. | Description "Socks, bags and extras." (4 words), JSON-LD only. The collection holds socks only. | The collection description now prints under the heading on collection pages; nothing prints while it is empty. The copy is admin work (draft in D2). | sections/crooks-exhibit-log.liquid:161-172, 803-809 | Visible: `Socks, bags and extras.` Still 4 words, and "bags" is not true. | 🟡 PARTIALLY FIXED |
| 29 (C6) | Functional pages flagged thin: /pages/tracking 142, /cart 134, /search 76 words. | Do not pad these utility pages. | Visible words (whole page, our count): tracking 199, cart 200, search 129. | No copy added. | - | tracking 202, cart 200, search 132; the +3 are the new h1s. | ⚪ NOT APPLICABLE |
| 30 (H1) | /pages/tracking has no h1. | Add one clear visible h1 (if the page stays indexable). | 0 h1. The two headings are h2s that change with the signed-in state. | One h1, "Track your order", in the page's existing eyebrow style; editable in the theme editor. | sections/crooks-tracking.liquid:32-39, 254, 311-314 | `<h1 class="crk-eyebrow crk-track__page-title">Track your order</h1>`; 1 h1, visible in Chromium at 390px. | ✅ FIXED |
| 31 (H2) | /search has no h1. | Add one clear visible h1 (if the page stays indexable). | 0 h1 on /search and /search?q=jeans. | One h1, "Search the store", where the field label sits, same style. | sections/crooks-search.liquid:23-32, 152, 183-186 | `<h1 class="crk-eyebrow crk-query__label crk-query__title">Search the store</h1>`; 1 h1 on both URLs, visible. | ✅ FIXED |

### Findings 32–36: images (p. 10, appendix pp. 15–20)

| # | Audit Finding | Audit Recommendation | Before | Change Made | Location | Evidence After | Status |
|---|---|---|---|---|---|---|---|
| 32 (I1) | 92 image URLs over 100 KB; largest 1.8 MB PNGs. | Resize sources, use WebP/JPEG where transparency is not needed, replace in Files or product media. | All 92 URLs re-measured. The audit's sizes are what a client without WebP support gets: 55,559 KB in total. A browser gets WebP from Shopify's CDN: 7,193 KB in total, 22 still over 100 KB (largest 247 KB). | None possible in the theme: it already requests sized images; the heavy files are store media (D5). | - | evidence/images-92-measured.tsv (URL, width, type served, bytes). | 🔵 EXTERNAL ACTION REQUIRED |
| 33 (I2) | (Developer) Use image_url + image_tag for responsive sizes. | Responsive srcset/sizes. | Already in place: product gallery srcset 400-1400, cards 200-800, homepage photos 320-1200, with sizes. | None needed. | - | Unchanged on the new theme; 0 Shopify images without srcset on 50 pages. | ⚪ NOT APPLICABLE |
| 34 (I3) | (Developer) Lazy-load images below the fold. | loading="lazy" below the fold. | Already lazy below the fold (and wrongly on the largest image too, see I4). | Kept. | - | Home: 60 of 62 images lazy; /collections/all: 33 lazy, the first 2 cards eager. | ⚪ NOT APPLICABLE |
| 35 (I4) | (Developer) Do not lazy-load the main hero/LCP image. | Eager and high fetch priority for the LCP image. | Measured LCP element at 390x844: homepage photo IMG_2393.jpg `loading="lazy"`; /collections/denim and /all first card `loading="lazy"`; product photo eager, no fetchpriority. | First homepage photo, first two collection cards and first product photo load eager; the very first of each at high priority. Everything else stays lazy. | sections/crooks-sightings.liquid:159-183; sections/crooks-exhibit-log.liquid:466-489; sections/crooks-exhibit-record.liquid:199-227 | Same LCP elements now `loading="eager" fetchpriority="high"` on all 4 templates (evidence/lcp-mobile-390.json). | ✅ FIXED |
| 36 (I5) | Re-test after a small batch. | Measure image weight and speed again after changes. | - | LCP element and image bytes re-measured on the new theme. | - | LCP attributes verified on 4 templates. Real-user speed (PageSpeed Insights, Core Web Vitals) can only be measured after publishing (D10). | 🟡 PARTIALLY FIXED |

### Findings 37–51: GEO foundations, authority and action plan (pp. 11–13)

| # | Audit Finding | Audit Recommendation | Before | Change Made | Location | Evidence After | Status |
|---|---|---|---|---|---|---|---|
| 37 (G1) | Public pages must stay crawlable, OAI-SearchBot not blocked; account, checkout and auth stay blocked. | Check product, collection and content pages are open. | robots.txt: `User-agent: *` allowed on public paths; no OAI-SearchBot rule; no robots meta on any page. | Only /search and /cart get `noindex, follow`. robots.txt untouched. | snippets/meta-tags.liquid:248-259 | 47 of 50 pages carry no robots meta; the 3 noindexed are /cart, /search and /search?q=jeans. robots.txt unchanged. | ⚪ NOT APPLICABLE |
| 38 (G2) | Validate product structured data: price, availability, variants, shipping, returns. | Validate rather than assume. | ProductGroup with a Product and Offer per variant (price, GBP, availability). No shipping, no return policy. Description ran together ("Blue wash.14oz"). Breadcrumb Home > NEW > product. 2 products sent `"description": ""`. | shippingDetails on every UK offer; return policy declared once on the Organization; seller and brand linked by @id; material, origin, cut and care from the product's own metafields; description spacing fixed; empty description falls back to the SEO description or is left out; breadcrumb skips ALL, PRODUCTS and NEW. | snippets/crooks-schema-product.liquid; snippets/crooks-schema-shipping.liquid; snippets/crooks-schema-site.liquid:111-125 | 21 of 21 product pages: valid JSON, 119 offers each with price, currency, availability, seller @id and shippingDetails; rate matches price on every offer; 0 graph errors. | ✅ FIXED |
| 39 (G3) | Names, descriptions, price and availability should match the website and any feeds. | Keep product data consistent. | JSON-LD built from the same Liquid product data as the page. | No separate data source added; description spacing fixed so the schema text matches the page. | snippets/crooks-schema-product.liquid | Page, JSON-LD and cart agree (Blue Wash Yard Jeans M: £60.00 in all three). Merchant Center feed not checked: no access (D10). | 🟡 PARTIALLY FIXED |
| 40 (G4) | Important categories and best-sellers linked from navigation, collections and content. | Check internal links to priority collections. | Every page links all 7 shop collections (header, menu, footer). | None needed in the theme. | - | Links verified on 50 pages. But Denim holds only OG Jeans (the 4 Yard denim pieces are missing) and 4 duplicate "-1" collections are in the sitemap (D3). | 🔵 EXTERNAL ACTION REQUIRED |
| 41 (G5) | Unique page titles, h1s and concise collection copy. | Clear page signals on every page. | Two title separators in use (" \| " and " – "); 3 URLs with no h1; 4 duplicate titles (Denim/DENIM, New/NEW, Sweats/SWEATS, Tees/TEES). | One separator; h1s added (H1, H2). | snippets/meta-tags.liquid | One separator on every title; exactly 1 h1 on all 50 pages. The 4 duplicate titles come from the duplicate collections (D3); collection copy is D2. | 🟡 PARTIALLY FIXED |
| 42 (G6) | Keep the site fast: heavy images slow shopping pages. | Compress the biggest files. | Largest image on home and collections lazy-loaded; heavy source files (I1). | As I4. | As I4 | As I4; the source files are D5. | 🟡 PARTIALLY FIXED |
| 43 (G7) | Answer real buyer questions: fit, sizing, fabric weight, care, styling, shipping, returns. | Buyer-focused content, not keyword lists. | FAQ page with valid FAQPage JSON-LD (14 questions on delivery, sizing, exchanges). | None in the theme; new content is the owner's (D13). | - | FAQPage still 14 questions, valid. | 🔵 EXTERNAL ACTION REQUIRED |
| 44 (G8) | Make product facts explicit: material, fit, measurements, weight, care, availability. | State them clearly on product pages. | The Specification panel shows fabric, cut, origin and care from the crooks.* metafields on 9 products; none of it in structured data. | The same metafields now go into Product JSON-LD: material, countryOfOrigin, and Cut and Care as additionalProperty. | snippets/crooks-schema-product.liquid:164-170, 186-192 | Present on the 9 products that have the data. 12 products have none (D6). | 🟡 PARTIALLY FIXED |
| 45 (G9) | Build independent proof: genuine reviews, creator, press and community coverage (also the action plan, week 4). | Encourage genuine reviews and third-party coverage. | No reviews. | None possible in the theme (D12). | - | - | 🔵 EXTERNAL ACTION REQUIRED |
| 46 (G10) | Brand, product names, sizing, returns and shipping claims should not conflict. | Keep facts consistent. | Footer (every page), Contact, FAQ, Terms and the product returns step said crooksldn@gmail.com while the Organization schema said team@crooksldn.com. Grey Convict Sweats: fabric "500gsm cotton" vs "550gsm brushed fleece" in its description. | team@crooksldn.com everywhere in the theme. Shipping and returns schema use the policies' own numbers. | new theme: sections/crooks-footer-log, crooks-contact, crooks-exhibit-record, footer-group.json; templates/page.contact, page.faq, page.terms, product, product.crooks (.json). Repo already had team@ (commit ed99ecb). | The gmail address now appears only inside 4 policy texts, which are admin text (D7). The fabric conflict is product data (D6). | 🟡 PARTIALLY FIXED |
| 47 (G11) | Make original content worth citing. | First-party content; avoid generic AI articles. | Blog has no articles. | None (owner's content, D13). | - | - | 🔵 EXTERNAL ACTION REQUIRED |
| 48 (G12) | Measure more than rankings: AI recommendations, cited sources, branded search, AI referrals. | Track AI visibility and referrals. | - | None possible in the theme (D11). | - | - | 🔵 EXTERNAL ACTION REQUIRED |
| 49 (G13) | Do not: force variant URLs to index, pad Cart/Search, change checkout/account robots rules, rely on llms.txt. | Avoid these. | Compliant. | Kept compliant: no variant indexing, no filler, robots.txt untouched, no llms.txt added. | - | Variant canonical unchanged (T1); cart and search word counts unchanged apart from the h1 (C6). | ⚪ NOT APPLICABLE |
| 50 (G15) | Plan one genuinely useful buyer-focused content piece (action plan, week 4). | Plan it. | - | Suggested topic in D13. | - | - | 🔵 EXTERNAL ACTION REQUIRED |
| 51 (M1) | Meta descriptions: 7 missing, 5 over 155 characters, 4 under 70. | Tidy in Shopify as a follow-up. | Our crawl of 46 indexable URLs: 14 missing, 5 over 155 (home 157, accessories 161, data-sharing 320, FAQ 167, puffa 188), 4 under 70 (denim 23, new 16, sweats 39, tees 19). | Over 160 characters: cut to whole words within 155 plus "…". Missing on a collection: built from its own products. Missing on a product: name, price and type. Homepage default shortened to 147. | snippets/meta-tags.liquid:37-95 | 10 missing (5 policies, blog, returns page, 3 duplicate collections), 0 over 155, 4 under 70 (the one-line collection descriptions). Exact text for the rest in D4. | 🟡 PARTIALLY FIXED |

## A. Implementation summary

The theme now gives search engines and AI systems one consistent, machine-readable account of the brand, its products and its terms, and its page signals are clean. Nothing visible changed except two small h1s, the collection descriptions and the contact email.

- **Titles:** one separator on every page; " | CROOKSLDN" only where the whole title fits in 56 characters. That fixes the six long titles with no admin edits, and future titles follow the same rule. The homepage uses the audit's wording.
- **Meta descriptions:** none over 155 characters (was 5). Collections and products with no description get one built from their own data.
- **Index control:** internal search results and the cart are `noindex, follow`. Nothing else changed; robots.txt untouched.
- **Structured data as one graph:** the Organization (`#organization`) carries the legal name, the Brand (`#brand`) and the return policy. The WebSite names it as publisher, every offer names it as seller, and every product's brand points at `#brand`. Each UK offer states its shipping rate and delivery time; product facts come from the metafields; description and breadcrumb are fixed.
- **Collection pages:** the collection description now prints under the heading. It used to reach only the structured data.
- **Speed:** the largest image on home, collection and product pages loads first at high priority; everything below the fold stays lazy. The share image (og:image) is 1200px instead of the 1–2 MB original.
- **Headings:** one h1 on tracking and on search; every page now has exactly one.
- **Consistency:** one contact email, team@crooksldn.com, across the theme.

## B. Files changed

In the repo, eight theme files changed and one was added, in commit `9ffde766` on `claude/crooksldn-theme-init-bnen7a`. All nine are uploaded to theme #206765785431 and MD5-matched. The email change touched eight more files on the new theme only, because the repo already had team@ (commit `ed99ecb`).

| File | Repo | Theme #206765785431 | Why |
|---|---|---|---|
| snippets/meta-tags.liquid | Changed | Changed | Titles, descriptions, robots, share image, escaping (P1–P6, M1, P15, G1) |
| snippets/crooks-schema-site.liquid | Changed | Changed | Organization legal name, Brand, return policy; WebSite language (A1, G2) |
| snippets/crooks-schema-product.liquid | Changed | Changed | Brand and seller @ids, shipping, product facts, description, breadcrumb (G2, G8) |
| snippets/crooks-schema-shipping.liquid | New | New | UK OfferShippingDetails, one place for the rate (G2, A4) |
| sections/crooks-exhibit-log.liquid | Changed | Changed | Collection description on the page; first cards load first (C1–C5, I4) |
| sections/crooks-exhibit-record.liquid | Changed | Changed | First product photo at high priority (I4); contact email (G10) |
| sections/crooks-sightings.liquid | Changed | Changed | First homepage photo loads first (I4) |
| sections/crooks-tracking.liquid | Changed | Changed | h1 (H1) |
| sections/crooks-search.liquid | Changed | Changed | h1 (H2) |
| sections/crooks-contact.liquid, crooks-footer-log.liquid, footer-group.json | Already team@ | Changed | Contact email (G10) |
| templates/page.contact.json, page.faq.json, page.terms.json, product.json, product.crooks.json | Already team@ | Changed | Contact email (G10) |
| docs/seo-audit-2026-10/ | New | Not uploaded | Finding matrix, evidence, scripts, this report |

The three snippets in the repo also gain the live theme's 30 Sept SEO changes (homepage fallback, alternate names, GTIN guard), which had been made on live but never committed.

## C. Before vs after

Rendered output, copied from page source (`evidence/head/`, `evidence/jsonld/`).

| Measure (50 pages) | Before | After |
|---|---|---|
| Titles over 55 characters | 7 | 1 (56, not flagged by the audit) |
| Title separators in use | 2 (" \| " and " – ") | 1 (" \| ") |
| Meta descriptions over 155 / missing / under 70 | 5 / 14 / 4 | 0 / 10 / 4 |
| Pages without exactly one h1 | 3 | 0 |
| Invalid JSON-LD blocks | 0 | 0 |
| Offers with shipping details | 0 of 119 | 119 of 119 |
| Pages showing crooksldn@gmail.com | 50 | 4 (policy texts) |
| Largest image loaded lazily (4 templates) | 3 | 0 |

**Homepage**

```html
<!-- before -->
<title> Crooks London | CROOKSLDN Streetwear: Fleece, Denim & Tees </title>
<meta name="description" content="Shop CROOKSLDN, the Crooks London streetwear label: 550gsm Convict fleece sets, 14oz Yard denim, graphic tees and MotionTec socks. Free UK shipping over £30." >
<!-- after -->
<title>Crooks London Streetwear | Fleece, Denim &amp; Tees</title>
<meta name="description" content="CROOKSLDN, the Crooks London streetwear label: 550gsm Convict fleece, 14oz Yard denim, graphic tees and MotionTec socks. Free UK shipping over £30." >
<img src="//crooksldn.com/cdn/shop/files/IMG_2393.jpg?v=1784545522&amp;width=1200" … loading="eager" fetchpriority="high">   <!-- was loading="lazy" -->
```

**Product page (/products/blue-wash-yard-jeans)**

```html
<!-- before -->
<title> Blue Wash Yard Jeans — 14oz Straight Leg Denim | CROOKSLDN </title>
<!-- after -->
<title>Blue Wash Yard Jeans — 14oz Straight Leg Denim</title>
```

```js
// one offer, before
"offers": { "@type": "Offer", "price": "60.00", "priceCurrency": "GBP", "availability": "https://schema.org/InStock",
  "seller": { "@type": "Organization", "name": "CROOKSLDN" } }
// the same offer, after
"offers": { "@type": "Offer", "price": "60.00", "priceCurrency": "GBP", "availability": "https://schema.org/InStock",
  "seller": { "@type": "Organization", "@id": "https://crooksldn.com#organization", "name": "CROOKSLDN" },
  "shippingDetails": { "@type": "OfferShippingDetails",
    "shippingDestination": { "@type": "DefinedRegion", "addressCountry": "GB" },
    "shippingRate": { "@type": "MonetaryAmount", "value": "0.00", "currency": "GBP" },
    "deliveryTime": { "@type": "ShippingDeliveryTime",
      "handlingTime": { "@type": "QuantitativeValue", "minValue": 0, "maxValue": 2, "unitCode": "DAY" },
      "transitTime": { "@type": "QuantitativeValue", "minValue": 1, "maxValue": 2, "unitCode": "DAY" } } } }
```

| Product JSON-LD field | Before | After |
|---|---|---|
| description | "Yard jeans — Blue wash.14oz denim, OG straight cut…" | "Yard jeans — Blue wash. 14oz denim, OG straight cut…" |
| brand | `{"@type":"Brand","name":"CROOKSLDN"}` | `{"@type":"Brand","@id":"https://crooksldn.com#brand","name":"CROOKSLDN"}` |
| material / countryOfOrigin | none | "14oz denim" / Portugal |
| additionalProperty | none | Cut: "OG straight, mid rise"; Care: "Cold wash inside out. Hang dry." |
| BreadcrumbList | Home > NEW > BLUE WASH YARD JEANS | Home > BLUE WASH YARD JEANS (becomes Home > Denim > … once it is in Denim, D3) |

**Organization (every page), added**

```js
"legalName": "Crooks Clothing Company Ltd",
"brand": { "@type": "Brand", "@id": "https://crooksldn.com#brand", "name": "CROOKSLDN", "logo": "https://crooksldn.com/cdn/shop/files/IMG_3682.png?v=1774356387&width=512" },
"hasMerchantReturnPolicy": { "@type": "MerchantReturnPolicy", "@id": "https://crooksldn.com#return-policy",
  "url": "https://crooksldn.com/policies/refund-policy", "applicableCountry": "GB", "returnPolicyCountry": "GB",
  "returnPolicyCategory": "https://schema.org/MerchantReturnFiniteReturnWindow", "merchantReturnDays": 14,
  "returnMethod": "https://schema.org/ReturnByMail",
  "customerRemorseReturnFees": "https://schema.org/ReturnShippingFees", "itemDefectReturnFees": "https://schema.org/FreeReturn" }
```

**Collection page (/collections/denim)**

```html
<!-- before -->
<title> Denim &ndash; CROOKSLDN</title>
<img … class="crk-card__img crk-card__img--main …" loading="lazy" sizes="(min-width: 1024px) 25vw, 50vw">
<!-- after -->
<title>Denim | CROOKSLDN</title>
<div class="crk-log__intro">Jorts, jeans and denim.</div>
<img … class="crk-card__img crk-card__img--main …" loading="eager" fetchpriority="high" sizes="(min-width: 1024px) 25vw, 50vw">
```

**Search, cart, tracking**

```html
<!-- /search?q=jeans, before: no robots meta, no h1 -->
<title> Search: 5 results found for &quot;jeans&quot; &ndash; CROOKSLDN</title>
<!-- after -->
<title>Search: 5 results found for &quot;jeans&quot; | CROOKSLDN</title>
<meta name="robots" content="noindex, follow" >
<h1 class="crk-eyebrow crk-query__label crk-query__title">Search the store</h1>
<!-- /cart, after -->
<meta name="robots" content="noindex, follow" >
<!-- /pages/tracking, after (before: no h1) -->
<h1 class="crk-eyebrow crk-track__page-title">Track your order</h1>
```

**Largest image at 390×844, measured in Chromium**

| Page | Image | Live theme | New theme |
|---|---|---|---|
| / | IMG_2393.jpg, width 900 | lazy | eager, high |
| /collections/denim | OG Jeans card, width 600 | lazy | eager, high |
| /collections/all | Black Convict Hoodie card, width 600 | lazy | eager, high |
| /products/blue-wash-yard-jeans | main photo, width 1400 | eager | eager, high |

**Regression (same walk, both themes):** home, mobile menu (8 links), /collections/denim (1 card), /collections/all (20 cards), product page (5 sizes; "Select Size" → "Add to bag"; added, cart.js count 1, £60.00), cart (item and checkout button), search "jeans" (5 results), tracking (form), FAQ. The results were identical on both themes. The console errors were the same on both and come from the analytics requests the test blocks. Side-by-side screenshots: `evidence/regression/cmp-*.jpg`.

**Lint (Shopify theme-check):** errors 394 before and 394 after, all from the partial file copy the check ran on. One real new warning: the tracking section's settings count (42 → 43, limit 40), accepted for an editable h1. One more is a false positive, explained in `evidence/theme-check.txt`.

## D. Remaining issues and admin actions

Everything left needs Shopify admin, content or operations; none of it can be done from the theme. Steps assume Shopify admin on desktop. Do D3 before D2: the copy describes products that must be in the collection.

**D1. Collection page titles (P7–P11).** Products → Collections → open the collection → Search engine listing (bottom) → Edit → Page title → Save. Type the words without the brand; the theme adds " | CROOKSLDN" when it fits.

| Collection | Type | Renders as |
|---|---|---|
| Denim | Denim Jeans & Jorts | Denim Jeans & Jorts \| CROOKSLDN |
| New | New Streetwear Arrivals | New Streetwear Arrivals \| CROOKSLDN |
| ALL | Shop CROOKSLDN Streetwear \| All Clothing | as typed (already has the brand) |
| Tees | Streetwear T-Shirts & Graphic Tees | Streetwear T-Shirts & Graphic Tees \| CROOKSLDN |
| Sweats | Hoodies, Sweatshirts & Joggers | Hoodies, Sweatshirts & Joggers \| CROOKSLDN |

The audit suggested "Men's Denim Jeans & Jorts". Use "Men's" only if the denim is cut for men.

**D2. Collection descriptions (C1–C5).** Products → Collections → open it → Description → paste → Save. They now show on the page under the heading. The drafts use only facts already in your product data; check each before pasting. They run 47–106 words, under the audit's 80–150, because that is all the data supports. To lengthen them, add what only you know: how each piece fits, who it is for, why the fabric weight matters. Don't add filler.

- **Denim** (after D3): "CROOKSLDN denim comes in three cuts. Yard Jeans are 14oz denim in an OG straight cut with a mid rise: structured, not baggy, in blue or grey wash, with an embroidered handcuff graphic on the back pockets. Yard Jorts are baggy 14oz denim shorts that finish below the knee, with the Convict embroidery on the back pockets, also in blue or grey wash. OG Jeans are heavyweight denim with a baggy, stacked fit and a white handcuff graphic on the back pockets. The Yard pieces are made in Portugal; wash cold, inside out, and hang dry. Sizes XS to XL, with measurements in each size guide."
- **Tees:** "CROOKSLDN tees are cotton T-shirts with a graphic across the chest, each in black or white, sizes XS to XL, £25. The Crooks Express tee carries the red CROOKS logo and a blue dashed-line graphic. The CRX Garms tee is premium cotton with a structured fit and the CRX Garms logo. The CRXST★RZ tee has the outlined CROOKS wordmark and a red star. Measurements are in each size guide."
- **Sweats:** "Heavyweight fleece from CROOKSLDN. The Convict Hoodie and Convict Sweats are 550gsm brushed fleece in a baggy fit, with the sweats cuffed at the hem; each hoodie pairs with the sweats in the same colour as the Black, Grey or Pink Set, £60 a piece. The Cellblock Crewneck (£50) and Cellblock Shorts (£45) are 450gsm brushed fleece in a relaxed cut with 3D embroidery, made in Portugal; the shorts finish above the knee. Sizes XS to XL."
- **Tracksuits:** "A CROOKSLDN tracksuit is the Convict Hoodie with the matching Convict Sweats: 550gsm brushed fleece, baggy fit, sweats cuffed at the hem. Three sets: Black, with white contrast piping; Grey, with the embroidered handcuff logo; and Pink, with white piping and handcuff embroidery. Each piece is £60, sizes XS to XL."
- **Accessories:** "MotionTec socks from CROOKSLDN: cotton blend with a reinforced heel, made for constant movement. Two colourways, black with blue and white with red. A single pair is £6; packs of 3, 6 and 12 are £15, £25 and £45, so the 12-pack ships free in the UK." Add the cap sentence only if you add the cap (D3).

**D3. Collection membership and duplicates (G4, G5).**

1. Denim holds only OG Jeans. Add Blue Wash Yard Jeans, Grey Wash Yard Jeans, Blue Wash Yard Jorts and Grey Wash Yard Jorts: Products → Collections → Denim → Products → Browse → tick them → Add → Save. If Denim is an automated collection, change its conditions instead.
2. Accessories: its description says "bags", and it holds only socks. Add the Major League Crooks Cap (Cream) if it is on sale, and replace the description (D2).
3. Four duplicate collections are in the sitemap with near-identical titles: DENIM (/collections/denim-1, 0 products), SWEATS (/collections/sweats-1, 0 products), NEW (/collections/new-1) and TEES (/collections/tees-1). Check Online Store → Navigation that no menu links them. Then delete them, or open each and remove Online Store from its sales channels. Then Online Store → Navigation → URL Redirects → Create: /collections/denim-1 → /collections/denim, and the same for the other three.

**D4. Meta descriptions (M1).** Collections and products: open it → Search engine listing → Edit → Meta description. Pages: Online Store → Pages → open it → Search engine listing.

| Page | Meta description | Chars |
|---|---|---|
| /collections/denim (after D3) | Yard Jeans, Yard Jorts and OG Jeans from CROOKSLDN: 14oz and heavyweight denim in straight and baggy cuts, blue and grey washes. Free UK shipping over £30. | 155 |
| /collections/tees | CROOKSLDN graphic tees in black or white cotton: Crooks Express, CRX Garms and CRXST★RZ. Sizes XS to XL, £25. Free UK shipping over £30. | 136 |
| /collections/sweats | Convict hoodies and sweats in 550gsm brushed fleece, plus the 450gsm Cellblock crewneck and shorts. Sizes XS to XL. Free UK shipping over £30. | 142 |
| /collections/new | The latest CROOKSLDN pieces: heavyweight fleece, 14oz denim, graphic tees and MotionTec socks. Free UK shipping over £30. | 121 |
| /collections/accessories (now 161, trimmed by the theme) | MotionTec socks from Crooks London: cotton blend with a reinforced heel, in single pairs or packs of 3, 6 or 12. Free UK shipping over £30. | 139 |
| /pages/faq (now 167, trimmed by the theme) | Crooks London delivery, sizing and exchanges: same-day dispatch before 18:00, free UK shipping over £30, worldwide delivery in 7–14 working days. | 145 |
| /pages/returns (none) | Return or swap a CROOKSLDN order within 14 days of delivery. Size swaps are free, and faulty or wrong items always return free. | 127 |
| /products/double-agent-puffa (none; page title also unset) | Heat-reactive puffer from CROOKSLDN that changes appearance with temperature. Handcuff embroidery on chest and hood, padded fit, concealed pockets. | 147 |

For the puffa, also set Page title "Double-Agent Puffa \| Heat-Reactive Puffer Jacket". The cap has no product description at all; write one from the real product (material, fit, adjuster) first, then its search listing. The blog has no articles; leave it until the first one (D13). Policy pages have no search-listing fields in Shopify; the audit says leave them (P12–P17).

**D5. Heavy source images (I1, G6).** Content → Files → search the file name → open it → Replace, which keeps the same URL everywhere it is used. If Replace is not offered, add the new image to the product's media and remove the old one. Start with the audit's eight largest (p. 10). Export at 1600px wide (the theme never asks for more than 1400px). Keep the cut-out product shots as WebP with transparency, because the catalogue's outline effect needs the transparent background; do not convert them to JPEG. Lifestyle photos can be JPEG at quality 80.

**D6. Product facts (G8, G10).** Products → open the product → Metafields (bottom of the page) → Fabric, Cut, Origin, Care → Save.

1. Grey Convict Sweats: Fabric says "500gsm cotton"; its description and title say "550gsm brushed fleece". Confirm which is right and correct the other. The page currently shows both.
2. These 12 products have no fabric, cut, origin or care data, so the Specification panel and the structured data have nothing to show: Black Convict Hoodie, Grey Convict Hoodie, Pink Convict Hoodie, Black Convict Sweats, Pink Convict Sweats, OG Jeans, Crooks Express Tee, CRX Garms T-Shirt, CRXST★RZ T-Shirt, HydroCuff Windbreaker, Double-Agent Puffa, Major League Crooks Cap (Cream).

**D7. Policies (G10).** Settings → Policies → Refund policy, Shipping policy, Terms of service, Privacy policy → replace crooksldn@gmail.com with team@crooksldn.com → Save. Also check the refund policy says what the returns desk says: free size swaps, 14 days, faulty or wrong items always free.

**D8. Homepage photos without alt text (found in verification).** Online Store → Themes → Customize (on the theme you publish) → Home → Sightings → frame 1 (IMG_2393) and frame 2 (8I2A9051) → Alt text → describe each photo in a sentence.

**D9. Publish (moves "Code updated" to "Deployed").** Three unpublished themes are each a separate copy of live: SEO fixes (#206765785431), T-shirt Week (#206733017431) and Returns staging (#206372733271). Publishing one drops the others' changes. Before publishing, the SEO files must be copied into whichever theme goes live; that is 9 theme files plus the email change in 8 more, and I can do it. Then you publish it: Online Store → Themes → ⋯ → Publish.

**D10. After publishing (moves "Deployed" to "Verified on live").**

1. [Rich Results Test](https://search.google.com/test/rich-results) on /products/blue-wash-yard-jeans: expect valid Product snippets and Merchant listings, with shipping and returns detected.
2. Google Search Console → URL Inspection → Test live URL for /, one product and /collections/denim, then Request indexing.
3. [PageSpeed Insights](https://pagespeed.web.dev/), mobile, for /, /collections/all and one product: the largest-paint image should no longer be flagged as lazy-loaded (I5).
4. If you use Google Merchant Center: confirm the feed's titles, prices and availability match the pages (G3).
5. Ask me to re-run this report's checks against the live site.

**D11. Measurement (G12).** Search Console → Performance → Search results → Query contains "crooks", for branded search. GA4 → Reports → Acquisition → Traffic acquisition → add a filter: session source matches regex `chatgpt|perplexity|gemini|copilot|claude`. Re-run the AI grader monthly to compare against the audit's scores.

**D12. Reviews and coverage (A3, G9).** Install a review app that asks buyers after delivery (for example Judge.me or Okendo). Once there are genuine reviews, the theme can add rating markup from the app's data. Do not add ratings before that.

**D13. Content (G7, G11, G15).** One buyer-focused piece, for example "Convict 550gsm vs Cellblock 450gsm: how they fit", using the real garment measurements from the size guides and the fabric facts. Publish it under Blog → News; it also gives the empty blog its first article.

**D14. When the returns desk goes live.** If its terms differ from today's (14 days; return postage paid by the buyer for change-of-mind refunds; faulty items free), update the return policy in `snippets/crooks-schema-site.liquid` to match.

**A4, delivery delays:** operational. The site now states delivery times in one consistent, machine-readable form; keeping to them is outside the theme.

## E. Audit scorecard

- **Total original findings:** 51
- **Fully fixed:** 10 (P1–P6, H1, H2, I4, G2)
- **Partially fixed:** 13 (A1, C1–C5, I5, G3, G5, G6, G8, G10, M1)
- **Not fixed:** 0
- **Not applicable:** 14 (A2, T1, T2, P12–P17, C6, I2, I3, G1, G13)
- **External action required:** 14 (A3, A4, P7–P11, I1, G4, G7, G9, G11, G12, G15)

**Theme-addressable audit completion rate = 10 / 23 = 43%.**

The 23 theme-addressable findings are those where changing theme code was all or part of the fix: the 10 fixed and the 13 partly fixed. The 14 not-applicable findings needed no change, and the 14 external ones need no theme code. That includes A4, G4, G7 and I1: what remains for them is operations, admin data or media files. All theme-side work on the 23 is done; the 13 partial findings wait on D1–D7 and on the post-publish checks in D10.

## F. Highest-value changes

1. **Shipping and returns in product data (G2).** Google's merchant listings and AI shopping answers read delivery cost, delivery time and return terms from here. Before, none was machine-readable; now all 119 offers carry them.
2. **One entity graph (A1).** The Organization, Brand, WebSite, products and offers now point at each other by @id, with the legal name and the known alternate names. A crawler or model can tie "Crooks London", "CROOKSLDN" and the products to one company, which is what the audit's low recognition scores are about.
3. **Largest image loads first (I4, G6).** On a phone the homepage photo and the first collection card were lazy-loaded, so they waited for layout before downloading. That delay feeds straight into Largest Contentful Paint, a Core Web Vitals measure.
4. **Collection descriptions on the page (C1–C5).** Without this, the copy the audit asks for would still have been invisible to shoppers and crawlers. Once D2 is pasted, each priority collection gets real context on the page, the first step to the 80–150 words the audit asks for.
5. **Product facts in structured data (G8).** Material, country of origin, cut and care now go to machines as well as shoppers, the explicit product facts the audit asks for. It covers 9 products today and all 21 once D6 is done.
6. **Search and cart kept out of the index (P15, G1).** This stops endless "search for X" URLs from competing with collections, and leaves every public page crawlable.
7. **Titles (P1–P6, G5).** The six long titles are fixed, every title uses one separator, and future titles follow the 56-character rule automatically.
8. **One contact address (G10).** The schema said team@crooksldn.com and every page footer said a Gmail address. Conflicting facts are exactly what the audit warns weaken AI confidence in a brand.

## Where this departs from the audit

- **Product titles (P2–P6):** fixed by a theme rule rather than six admin edits. The rule fixes future titles too. The admin titles' em dash is kept where the audit wrote "|"; the length, which was the finding, is what matters. The brand still reaches Google through the WebSite name (Google's site-name source) and og:site_name.
- **Image sizes (I1):** the audit's numbers are what a crawler without WebP support receives. A browser gets WebP, 7,193 KB for the 92 URLs against the audit's 55,559 KB, with 22 over 100 KB. Replacing the sources is still worth doing, at lower urgency. The width=3840 URLs are srcset candidates on /search that phones never download.
- **Search (H2, P15):** the h1 is added even though results are now noindexed. The audit made it conditional on indexing, but a page heading is right for people and screen readers either way. Google's guidelines have long advised keeping internal search results out of its index.
- **Cart:** noindexed too, beyond the audit. It has no search value, and robots.txt still lets agents reach it.
- **Denim title (P7):** "Men's" left out unless it is true.
- **Word counts (C1–C6):** the audit's counts (69, 96 …) and ours (whole page) measure different things. The 80–150-word target for collection copy stands.
- **Tracking (P13):** kept indexable. It answers a real query ("track my CROOKSLDN order") and is not thin filler.
- **llms.txt:** not added, per the audit's own advice (G13).

## Found beyond the audit

| Issue | Status | Where |
|---|---|---|
| Collection descriptions were never shown on the page, only in structured data | Fixed | C1–C5 |
| Product structured data ran paragraphs together ("Blue wash.14oz") and sent an empty description for 2 products | Fixed | G2 |
| Product breadcrumbs went through "NEW" (Home > NEW > product) | Fixed | G2 |
| Every page's footer said crooksldn@gmail.com while the schema said team@crooksldn.com | Fixed in theme; policies D7 | G10 |
| Denim collection holds only OG Jeans; the 4 Yard denim pieces are missing | Admin | D3 |
| Four duplicate "-1" collections in the sitemap, with near-identical titles | Admin | D3 |
| Accessories description promises bags; it holds socks only | Admin | D2, D3 |
| Grey Convict Sweats fabric: "500gsm cotton" vs "550gsm brushed fleece" on the same page | Admin | D6 |
| Two homepage photos have no alt text | Theme editor | D8 |
| The live theme's 30 Sept SEO changes were never in git; the repo's JSON templates differ from live's editor changes | Snippets now committed; templates noted | B |
| Three unpublished themes each hold different changes | Merge before publishing | D9 |

