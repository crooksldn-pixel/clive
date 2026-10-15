# PDP buy panel: pre-order cleanup (15 Oct 2026)

On a pre-order size the product page showed IN STOCK, "ships today", two
prices (£60 at the top, £51 in the app's panel), and a Buy it now box carrying
Shopify's deferred-purchase disclaimer. This change leaves one state per size.

| Size state | Shows |
|---|---|
| Pre-order | Pre-order price in the main price line (£51, £60 struck), PRE-ORDER label, dispatch date, one note, one PRE-ORDER button. No stock line, no ships-today, no Buy it now. Sticky bar: price · size and PRE-ORDER only |
| In stock | Stock line, live dispatch line (the static "Order before 18:00" rule is hidden while the live line shows), ADD TO BAG, Buy it now as a plain outlined button |
| Sold out | One red "SIZE X IS SOLD OUT" line and NOTIFY ME. The app's duplicate note, the dead SOLD OUT button and the sticky CHECKOUT NOW are hidden |

Every size also gets the size guide as a link on the SIZE row (it was a boxed
button under the stock line), and more space between the price and the sizes.

The disclaimer moves to checkout without any work here: Shopify's checkout
shows its own deferred-purchase agreement under Pay now whenever the bag holds
a selling-plan line (`preview/5-checkout-disclaimer.png`).

## Where the change is

| State | Where |
|---|---|
| Code updated | Unpublished theme "CROOKSLDN — REVIEW: SEO + Tee Week + Returns" (#207020425559) |
| Deployed to live | No. The live theme (#206162461015) is unchanged |
| Verified | On #207020425559 through the theme preview, with live store data |

The repo's own `sections/crooks-exhibit-record.liquid` and
`assets/crooks-record.js` have drifted from the theme's copies (the repo holds
PDP work that no theme has, and the theme holds the app-block edits the repo
lacks), so they are not overwritten here. `theme-207020425559/` holds the three
files exactly as uploaded:

| File | MD5 on the theme |
|---|---|
| `assets/crooks-record-buy.css` (new) | `eedab44eb90aec81bb1a376c52c0a968` |
| `assets/crooks-record.js` | `e3a8c97a2e631511f3c96c4bc1a7d779` |
| `sections/crooks-exhibit-record.liquid` | `e6fcc49ebc5bfc9c97c2c809b0a69764` |

`changes.diff` is the change to the two existing files, against the versions
that were on the theme before (section `10910860…`, script `2e415f76…`).

## How it works

- The CROOKS Operations app block decides the state and shows its own panel.
  `crooks-record.js` reads which panel is showing and marks the record
  `[data-crk-preorder]` or `[data-crk-notify]`; `crooks-record-buy.css` hides
  what stops being true. With no app block, or one that changes its markup,
  nothing is marked and the page behaves as before.
- After each size change the script fires a non-bubbling `change` on the app's
  section so the app re-checks at once instead of on its 300 ms timer, then
  reads the result.
- The pre-order price shown is the one the app reports for the selling plan,
  which is what checkout charges.

## Verified

- Pre-order M: main price £51.00 (£60.00 struck), selling plan 692059799895 on
  the form, PRE-ORDER button and sticky bar, no Buy it now. Added to bag: cart
  line £51.00 with "Pre-order: expected to dispatch by 31 October".
- Size switching XS → M → L → XS → M: correct state each time.
- In-stock XS: £60.00, IN STOCK, live dispatch line, Buy it now; added to bag
  at £60.00 with no selling plan.
- Sold-out S (Grey Wash Yard Jeans): one sold-out line, NOTIFY ME opens the
  email form.
- Desktop 1440, light mode, and a product with the complete-the-set toggle
  (unchanged behaviour).
- Checkout with the pre-order line shows Shopify's deferred-purchase agreement.

`preview/` has the before/after screenshots shown for sign-off and the render
from the review theme after upload.
