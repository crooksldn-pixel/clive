# Reaction test: water- and heat-reactive product photos (16 Oct 2026)

A "material evidence" card for the HydroCuff Windbreaker (water) and the
Double-Agent Puffa (heat). The shopper drags or swipes across the jacket and
the reacted photo comes through where they paint, with a soft edge, and stays.
VIEW FULL REACTION shows the whole reacted jacket and switches back; RESET
clears the paint.

## Update, 16 Oct afternoon: real Puffa photo

George supplied the heated Puffa photo (black shell → metallic silver),
1122×1402, transparent background. It lines up with the product's front photo
(98.9% silhouette overlap, at most 1 px off).

| | |
|---|---|
| File | Content › Files: `crooksldn-double-agent-puffa-heat-reacted.webp`, alt "CROOKSLDN Double-Agent Puffa with heat applied: the black shell shows metallic silver" |
| Theme | New unpublished copy of live, #207338668375 "CROOKSLDN — Puffa heat reaction (from live 16 Oct)". The live theme is read-only to me, so the photo is set there |
| On that copy | `templates/product.reaction-puffa.json` uses the real photo (no placeholder tag); the `pending/` sizes tweak is applied; the heat brush is stronger (0.16 → 0.24 per stamp, sample stroke 0.24 → 0.30), because with the real photo one stroke only half-revealed the silver and read as a sheen. Copies in `theme-207338668375/` |
| Tested on the copy | Desktop and phone runs as below, all passing; a phone now downloads the 1000 px reacted file on first load |
| Still to do | George publishes the copy; then the Puffa's theme template is set to `reaction-puffa`. Until that, customers see nothing new |

The HydroCuff template on the copy still has its placeholder and stays
unassigned.

## Where it is

| | |
|---|---|
| Theme | #207329132887 "CROOKSLDN — SEO round 2 (from live 16 Oct)". Built there while it was unpublished; George published it at 13:33 on 16 Oct, so it is now **live** |
| Seen by customers | **No.** Nothing shows until a product is assigned one of the two new templates (below) |
| Reachable by URL | `/products/hydrocuff-windbreaker?view=reaction-hydrocuff` and `/products/double-agent-puffa?view=reaction-puffa`. Not linked anywhere; the canonical tag points at the normal product page; both show a red PLACEHOLDER tag |
| Photos | **No real reacted photos exist yet.** The two templates use placeholder images I made from the product photos (a cuff pattern; a purple tint), stamped "PLACEHOLDER – SIMULATED REACTION – NOT A PHOTO". The card shows a red "PLACEHOLDER · NOT A REAL PHOTO" tag whenever the reacted image's file name contains `placeholder` |
| Admin | Two files added to Content › Files: `crooks-reaction-placeholder-hydrocuff-water.png`, `crooks-reaction-placeholder-puffa-heat.png`. Nothing else in admin changed |

`live-theme-207329132887/` holds every feature file exactly as it is on the
live theme (the templates as Shopify returns them, with its header comment).

## Files

| File | New / changed | What it does |
|---|---|---|
| `snippets/crooks-reaction.liquid` | new | The card: file strip (MATERIAL EVIDENCE · TEST / 02 / WATER-REACTIVE), title, copy, the photo pair with the canvas between them, the prompt, the status line and the two buttons, the no-JavaScript fallback, editor-only warnings. Renders nothing until a reacted image is set |
| `assets/crooks-reaction.js` | new | The painting (Canvas 2D, Pointer Events), VIEW FULL REACTION, RESET, the sample stroke, analytics events. 21 KB unminified, no dependencies, loaded only on pages with a card |
| `assets/crooks-reaction.css` | new | The look, on the crooks.css tokens and classes. 7 KB, loaded only with a card |
| `sections/crooks-reaction.liquid` | new | The same card as a standalone section ("Crooks — Reaction test") for any page: photo left, text right on desktop |
| `templates/product.reaction-hydrocuff.json` | new | Copy of the default product template plus a Reaction test block: water, TEST 02 |
| `templates/product.reaction-puffa.json` | new | The same for the Puffa: heat, TEST 01 |
| `sections/crooks-exhibit-record.liquid` | changed | Adds a "Reaction test" block type (max one) and renders it inside the product grid. Diff: `exhibit-record.diff`. A product page without the block renders exactly as before (checked on four products, HTML identical apart from whitespace) |

The repo's `sections/crooks-exhibit-record.liquid` has drifted from the
theme's (see `docs/pdp-buy-panel-2026-10/`), so it is not overwritten; the
theme's version is in `live-theme-207329132887/` and `pending/`.

## Where it sits

- **Phone:** directly under the buy panel (ADD TO BAG / PRE-ORDER), before
  the shipping and description panels.
- **Desktop:** under the main photo, with the buy panel sticky beside it, so
  ADD TO BAG stays on screen while the shopper plays.
- The purchase flow is untouched: no change to the form, the buttons, the
  pre-order app block or the sticky bar.

## Adding the real photos

Theme editor (Online Store › Themes › Customize), template picker at the top ›
Products › **reaction-hydrocuff** › Crooks — Product Record › **Reaction
test** block:

- **Reacted image:** the wet HydroCuff photo.
- **Normal image:** leave blank to use the product's first photo, or upload
  the matching dry shot.

Then the same in **reaction-puffa** with the heated Puffa photo.

### What the photos must be

The reacted photo is drawn exactly over the normal one, so the pair must be
the **same shot**: same camera position, framing, crop, pixel size and
background. Only the fabric changes. Tripod, same lighting.

| Product | Current photo | Pair to supply |
|---|---|---|
| HydroCuff | 2048×2048 (square), transparent background | Both at 2048×2048. If the normal image is left blank, the wet photo must line up with the current product photo exactly |
| Puffa | 1122×1402 (4:5), transparent background | Ideally a new pair at 1600×2000 (4:5) uploaded into both slots. If the normal image is left blank, the heated photo must be exactly 1122×1402 and line up with the current front photo |

- At least 1400 px wide: the card asks for up to 1400 px.
- PNG with a transparent background (like the current photos) or JPG. Shopify
  serves WebP/AVIF automatically.
- Don't put "placeholder" in the file names.
- In the editor the card warns (editor only) if the two images are different
  shapes.

## Assigning it to the two products

After the real photos are in (otherwise shoppers see the placeholder and its
red tag):

1. Products › HYDROCUFF WINDBREAKER › **Theme template** (right-hand column) ›
   `reaction-hydrocuff` › Save.
2. Products › DOUBLE-AGENT PUFFA › Theme template › `reaction-puffa` › Save.

For a future reactive product: Customize › Products › Create template, based
on `reaction-hydrocuff`; set its photos, type and text; assign it to the
product. No code.

The two templates are copies of the default product template as of 16 Oct. A
later change to the default template (say a new shipping step) has to be made
in these two as well.

## Editor settings (block and section)

Normal image · Reacted image · Reacted image description (alt) · Load
straight away (only when at the top of a page) · Reaction type (water / heat)
· Brush size · Sample stroke on/off · Eyebrow · Test word · Test / evidence
number · Reaction label · Heading · Supporting copy · Interaction label ·
Status words · Status label · button labels · Screen reader instructions ·
Accent colour · Space above / below.

Blank text falls back to sensible defaults (WATER-REACTIVE, SWIPE TO APPLY
WATER →, DRY / WET / FULLY WET; HEAT-REACTIVE, DRAG TO APPLY HEAT →, AMBIENT /
WARM / FULL HEAT).

## How it works

- Two `<img>` with Shopify `srcset`/`sizes` (400–1400 px; the 2048 px source
  is never sent). On a product page the normal photo uses the gallery's own
  URLs and `sizes`, so it comes from cache. Both load lazily as the card
  nears the screen, unless "Load straight away" is ticked.
- A canvas sits between them. A soft radial brush paints an alpha mask; the
  reacted photo is drawn through it. Water: a wetter core, a short feathered
  edge, slightly uneven like water in a weave. Heat: a long, even falloff.
  Holding still soaks or warms the spot a little more.
- Vertical swipes on a phone scroll the page (CSS `touch-action: pan-y`); a
  finger paints once it moves sideways, or on a tap. Mouse and pen paint at
  once; a thin ring shows the brush on desktop.
- No loop at rest. Frames are drawn only when there is new paint, plus a
  short loop while a pointer is held down. Canvas resolution capped at 2×.
  The mask is kept in image space, so a resize or rotation keeps every
  painted area in place. The canvas is set up only near the screen.
- One sample stroke draws across the chest when the card first comes into
  view (instantly with reduced motion), so the effect is visible before
  anyone touches it. The prompt (SWIPE TO APPLY WATER →) fades once the
  shopper paints.
- VIEW FULL REACTION fades the full reacted photo in (no fade with reduced
  motion) and becomes VIEW ORIGINAL; painting while it is on returns to the
  painted view. RESET clears everything; it is `aria-disabled` when there is
  nothing to clear, so focus is never lost.
- No JavaScript: the normal photo, plus a VIEW FULL REACTION disclosure that
  opens the reacted photo underneath. No canvas: VIEW FULL REACTION still
  works; RESET and the prompt hide.
- Both photos have alt text (the reacted one from the "Reacted image
  description" setting, else the file's alt, else "<product>, after water is
  applied"). The copy states the USP in words, so nothing depends on the
  effect.

## Analytics

The site has no dataLayer or tag manager; analytics run as Shopify app
pixels (Customer events). Each event is sent three ways, with no new
library:

1. `Shopify.analytics.publish(name, data)`: Shopify's customer events.
2. `window.dataLayer.push({ event: name, ... })`, only if a tag manager has
   created `dataLayer`.
3. A DOM event `crk:reaction` on the card.

| Event | When |
|---|---|
| `interaction_start` | First paint stroke (adds `input`: mouse / touch / pen) |
| `interaction_engaged` | The shopper has painted 12% of the photo (adds `coverage`) |
| `view_full_reaction` | VIEW FULL REACTION pressed |
| `view_original` | VIEW ORIGINAL pressed |
| `reset` | RESET pressed |

Every event carries `component`, `reaction` (water / heat), `test`,
`placement`, `product_id` and `product_handle`.

To see them in reports, add a custom pixel (Settings › Customer events › Add
custom pixel) that subscribes to the five names and forwards them, for
example:

```js
['interaction_start', 'interaction_engaged', 'view_full_reaction', 'view_original', 'reset']
  .forEach((name) => analytics.subscribe(name, (event) => {
    // event.customData: component, reaction, test, placement, product_id, product_handle
    // forward to GA4 / Meta / TikTok here
  }));
```

## Tested (Chromium, through the preview, then on live)

| Check | Result |
|---|---|
| Desktop mouse paint (1440×900) | Paints along the stroke, soft edge, stays; 60 fps (16.7 ms frames, 1106×1106 canvas) |
| Phone (390×844, touch, 3× screen) | Card 32 px under the buy panel. Vertical swipe on the photo scrolls the page 179–239 px and paints nothing. Sideways swipes paint and do not scroll. Sideways-then-down keeps painting. Tap dabs |
| Slow phone (CPU 4× slower) | 16.8 ms median frame while painting; canvas capped at 2× (580×738 on a 3× screen) |
| Resize 1440 → 1024 → 800 → 1440; portrait → landscape → portrait | Painted area kept every time |
| VIEW FULL REACTION / VIEW ORIGINAL | Toggle, label, status word and purple pressed state correct; works by mouse, tap, Enter and Space |
| RESET | Clears all paint; disabled state blocks a second reset; focus stays on the button |
| Events | All five fire once per action, with the right reaction and product, and reach `Shopify.analytics.publish` |
| No JavaScript | Normal photo; VIEW FULL REACTION disclosure opens the reacted photo; no stray prompt or buttons |
| No canvas | VIEW FULL REACTION works, RESET and prompt hidden, no errors |
| Reduced motion | Sample stroke appears at once; no fades |
| Light mode | Follows the theme tokens |
| Every editor setting | Set to non-default values on the Puffa template (accent colour, spacing, brush, labels, status words, alt, eager, sample stroke off) and rendered as set; template then restored |
| Standalone section + block on one page | Both work independently |
| Console | No errors from the feature (only the trackers the test blocks) |
| Layout shift | CLS 0.0039 desktop / 0.0015 phone, all from the existing status bar and sticky bar, none from the card |
| Other product pages | HTML identical to before (four products) |

## Not done yet: one small improvement

`pending/` has a tweak that missed the publish: the reacted photo asks for
the size it is actually shown at, so a phone downloads the 1000 px file
(~95 KB) instead of 1400 px (~167 KB). It changes only `sizes` attributes
(`pending.diff`). The live theme is read-only to me, so it goes in on the next
unpublished copy, made after the real photos are in so none of George's
editor changes are lost.

## Limitations

- **The reacted photos are placeholders** until real ones are shot.
- Only Chromium is available here, so iPhone Safari, Android Chrome on a
  real device, desktop Safari and Firefox were not run. The code uses only
  standard features supported by iOS 13+ / Safari 13+, Chrome and Firefox
  (Pointer Events, Canvas 2D, `touch-action`, ResizeObserver and
  IntersectionObserver with fallbacks). A two-minute check on a real iPhone
  is worth doing before assigning the templates.
- The theme editor itself was not opened (it needs George's login); Shopify
  accepted the schema, and every setting was checked by rendering.
- On a phone, painting is sideways or diagonal; a stroke that starts
  straight down scrolls the page instead. That is what keeps scrolling free.
- Pre-existing, all product pages: on desktop the sticky buy panel sticks
  16 px from the top, under the 86 px pinned header, so the product title
  slides behind the header while scrolling. The card makes the panel stick
  for longer, so it shows more. Fix: give `.crk-panel-sticky` a top offset of
  the header height.

## Gallery: recommendation

**Don't make it a gallery slide yet.**

- The gallery changes photo on a horizontal swipe, and painting is a
  horizontal drag. On a REACTION slide the same gesture would mean two
  things; one of them has to lose.
- The card needs its controls, status and copy. The gallery strip has room
  for a counter, not for VIEW FULL REACTION, RESET and an explanation.
- Under the buy panel, the card sits where the decision is made and keeps
  ADD TO BAG in view on desktop.

Worth doing next instead: a small "REACTION ↓" link beside "PHOTO 1 OF 1"
under the main photo that scrolls to the card. Discovery from the gallery,
no gesture conflict, a few lines in the gallery chrome.

## Tools

`tools/`: the placeholder generator (`standins.py`), the schema and template
builders, and the Playwright tests (`t-desktop.mjs`, `t-mobile.mjs`,
`t-fallback.mjs`, `t-two.mjs`, `t-perf.mjs` with `rxlib.mjs`). `screens/` has
the screenshots.
