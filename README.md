# CROOKSLDN: the Shopify theme and CLIVE

This repository holds two separate things:

- **The Shopify theme**, at the root. It is described below.
- **CLIVE**, the assistant and its engineering control plane, in [`crooks-assistant/`](crooks-assistant/).
  - Where it stands now, including what is in production and what is waiting to deploy: [`crooks-assistant/docs/product-memory/CURRENT_TRUTH.md`](crooks-assistant/docs/product-memory/CURRENT_TRUTH.md).
  - How the production host runs it: [`crooks-assistant/docs/DEPLOY_LINUX.md`](crooks-assistant/docs/DEPLOY_LINUX.md).

Changes reach `clive/trunk` only through a pull request whose exact head passed acceptance.

## Shopify Theme

Theme code for `5wn03t-nm.myshopify.com`, pulled from the live "Horizon" theme (#196747034967).

### Setup

1. Install [Node.js](https://nodejs.org) 18+ and the [Shopify CLI](https://shopify.dev/docs/api/shopify-cli):
   ```
   npm install
   ```
2. Log in to the store (opens a browser for auth):
   ```
   npx shopify auth login --store=5wn03t-nm.myshopify.com
   ```

### Workflow

- **`npm run dev`** — uploads the theme as a temporary development theme and serves it locally with live reload. Preview and editor URLs are printed to the terminal. Changes on disk sync to the store instantly; nothing is published.
- **`npm run check`** — runs [Theme Check](https://shopify.dev/docs/storefronts/themes/tools/theme-check) (linting) against the theme.
- **`npm run pull`** — downloads the latest theme files from the store, in case changes were made in the theme editor.
- **`npm run push`** — pushes local changes to the unpublished **CROOKSLDN — Staging** theme (id `202053779799`), never to live. Preview it here: https://5wn03t-nm.myshopify.com?preview_theme_id=202053779799 — publishing to live only happens on George's explicit say-so.

Note: `CROOKSLDN — Dev` (id `202044309847`) is currently the **live** theme (Sprint 1). The original `Horizon` (id `196747034967`) is kept unpublished as a rollback point.

### Structure

Standard Shopify Online Store 2.0 theme layout: `layout/`, `templates/`, `sections/`, `blocks/`, `snippets/`, `assets/`, `config/`, `locales/`.
