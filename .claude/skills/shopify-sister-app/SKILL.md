---
name: shopify-sister-app
description: Product philosophy for the CROOKS Shopify sister apps (Returns, Shipping, and future Restock, Fit/Size, Preorder, Wishlist, Stock Intelligence, Offers). Use when designing a new sister app, a new screen or flow, a setting, or deciding what an app should do or show.
---

# Shopify sister apps: how they should feel

These apps are a family of small Shopify-native tools, not a SaaS suite. Each one should feel
like another part of Shopify admin that happens to know CROOKS well.

## Principles

- **Native to Shopify.** Use Shopify's current recommended UI (Polaris web components and App
  Bridge; see `shopify-native-ui`). No separate dashboard look, no custom brand chrome beyond a
  small app mark.
- **Shopify is the system of record.** Orders, fulfillment orders, returns, inventory, customs
  data (HS code, origin) and customers live in Shopify. The app keeps only what Shopify can't
  hold: its own ledger, provider references, decisions and audit trail. Write learned facts
  back to Shopify where a field exists.
- **Exception-driven, not configuration-driven.** The default path needs no setup. The app asks
  a question only when it can't proceed (a missing country of origin, the first real package),
  asks it once, remembers the answer, and never asks catalogue-wide up front.
- **Simple by default, with progressive disclosure.** Lead with the decision ("Buy label —
  £6.60", "Approve return"), with detail one click away. Surface decisions, not raw API
  complexity.
- **List → detail → setup.** Prefer this three-screen shape: a list of what needs attention,
  a record with its next step and timeline, and one short setup page. Add navigation only when
  that genuinely stops being enough.
- **Minimal settings.** Each setting must change a real decision. Prefer sensible defaults and
  learned behaviour over options.
- **Honest wording.** Say what actually happened and what the customer or merchant may face
  ("may be asked to pay import VAT"), never optimistic claims.
- **Related, not coupled.** Sister apps share patterns and look; they don't share code,
  databases or deploys. Don't change one app to match another unless the owner asks.

## Before building a new screen or app

1. Look at how Returns solved the same shape: it is the precedent for flows and screen
   structure (its admin's hand-made CSS is not; new screens use real Polaris components).
2. Write down the merchant's one decision on each screen.
3. Remove any setting, column or step that doesn't change that decision.
4. Plan the empty, error, and "money may have moved" states up front, not as polish.
