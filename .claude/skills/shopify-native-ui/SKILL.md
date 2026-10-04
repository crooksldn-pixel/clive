---
name: shopify-native-ui
description: Building or changing embedded Shopify admin screens for the sister apps, using Polaris web components and App Bridge. Use when writing admin HTML/JS, choosing components, laying out list/detail/setup screens, or checking a screen in the browser.
---

# Shopify-native UI

Goal: the app should feel like another Shopify admin surface, not a SaaS website loaded
inside Shopify.

## Build

- Use **Polaris web components** (`s-page`, `s-section`, `s-button`, `s-badge`, `s-table`,
  `s-text-field`, `s-banner` and so on) and **App Bridge** from Shopify's CDN. Check current
  component names, attributes and events with `shopify-plugin:shopify-polaris-app-home`; don't
  write them from memory.
- Don't imitate Polaris with custom CSS when a real component exists. Custom CSS is for layout
  gaps only and uses Polaris tokens. (The Returns admin predates this and is hand-styled; copy
  its screen structure, not its CSS. Don't restyle Returns unless the owner asks.)
- Get the session token from App Bridge for every API call. The backend verifies it (see
  `.claude/claude-security-guidance.md`). Use App Bridge for navigation, toasts, modals and the
  title bar where it offers them.
- Follow Shopify conventions:
  - one primary action per screen;
  - destructive actions in critical tone with a confirmation;
  - badges for status (tone by meaning, not decoration);
  - tables for lists;
  - banners for problems that need action.
- Keep the information hierarchy flat: the next step first, the facts second, the timeline
  last. Money and consequences go next to the action that causes them.
- Every screen has deliberate **empty**, **loading**, **error** and **confirmation** states.

## Verify

Check every significant UI change in a real browser with the Playwright MCP, not by reading
HTML. Run the app's dev server (Returns: `crooks-returns/scripts/dev_server.py`). Then:

- walk the journey: list, open a record, take the action, confirm, see the result;
- snapshot or screenshot each state, at desktop width and at 390 px;
- read the console and network: anything beyond the documented expected warnings is a finding;
- compare with the sibling app's equivalent screen for obvious inconsistency, without changing
  the sibling unless asked.
