# CROOKS LDN — Shopify theme and CLIVE

This repository (`crooksldn-pixel/clive`, renamed from `Shopify-theme` on 2026-09-19) holds three things for CROOKS LDN (`5wn03t-nm.myshopify.com`):

1. **The Shopify theme**, at the repository root (`layout/`, `templates/`, `sections/`, `blocks/`, `snippets/`, `assets/`, `config/`, `locales/`): the storefront code, pulled from the live "Horizon" theme. Its workflow is unchanged and is described under [Shopify theme](#shopify-theme) below.
2. **The Partner Hub functions**, in [`partner-hub/`](partner-hub/README.md): the Base44 backend functions that connect the influencer portal (`crooks-partner-hub.base44.app`) to Shopify. They create gifted orders after a live stock check, sync tracking back, and serve an API for CLIVE ([`partner-hub/CLIVE_API.md`](partner-hub/CLIVE_API.md)). They are deployed to Base44, not to the theme.
3. **CLIVE** (*Computer Language Interface Virtual Environment*): the operational assistant for the business, in `crooks-assistant/` on the application branches listed below. It is not on this default theme branch. It began as the CROOKS Assistant, a voice assistant (a FastAPI backend on the owner's Mac, and since 2026-09-19 on a Linux server) that reads the Shopify store and the Gmail inbox and proposes changes the owner applies. The product identity is now CLIVE: a persistent intent-to-execution operational layer in which models propose and deterministic, evidence-checked capabilities execute, with human authority over every consequential action.

## Where the truth lives

- **Product memory**, the canonical durable product intent, is `crooks-assistant/docs/product-memory/` on the application branches. Read `CURRENT_TRUTH.md` first, then `PRODUCT_BRAIN.md`, `EVOLUTION_POLICY.md` and the active entries of `DECISIONS.md`. Read it by explicit ref from the most recent reconciled branch: `chatgpt/product-memory-reconcile-2026-09-23` at the time of writing (`claude/product-memory-foundation` is the 2026-09-21 base). Two documents live only on the branches that produced them: `ENGINEERING_LIFECYCLE_PRODUCERS.md` (the kernel contract, on the kernel branch) and `SUPPORT_INVESTIGATOR_V1.md` (on the support-investigator branch).
- **Engineering state** is the orphan branch `clive/engineering-state`: the records of the repository-only lifecycle kernel (tasks, attempts, evidence, reviews, acceptances, integrations and a generated `ACTIVE_STATE.json`), written only by the kernel itself (`crooks-assistant/scripts/engineering_kernel.py`, frozen at `18c3153a2eec10c6343153b550776afed3bec2ba`). A task is COMPLETE only when every record is present: candidate, exact-SHA evidence, an independent reviewer's acceptance, and a verified integration.
- **The communication bridge** is the orphan branch `crooks-ai-bridge` (GitHub inbox/outbox for the engineering workers).

## Branch map (as of 2026-09-23)

| Branch | Head | What it is |
| --- | --- | --- |
| `claude/shopify-theme-dev-setup-934mht` (default) | `c7988fa4` | The theme. No application code. |
| `claude/ci-provenance-acceptance-2026-09-22` | `b68e6e82` | The CI stream: the application with the `acceptance` workflow, the judgment ledger and its corrections. Every push runs the five acceptance gates. |
| `claude/control-plane-producers-2026-09-22` | `18c3153a` | The frozen lifecycle kernel (`control-plane-producers` r6, COMPLETE). |
| `claude/support-investigator-v1-2026-09-23` | `2dbb97bc` | Customer Support Investigator V1, read-only, on top of `b68e6e82` (`support-investigator-v1` r5, COMPLETE). |
| `claude/agent-environment-clive-state-2026-09-22` | `84e12e77` | Agent Environment authoritative-state repairs (COMPLETE; not yet on the CI stream). The Agent Environment is a read-only projection of the kernel's records. |
| `claude/ci-age-days-floor-2026-09-22` | `ef3d08ff` | CI age-floor fix (COMPLETE); not yet on the CI stream. |
| `claude/clive-recovery-handoff-pwuuse` | `1958b327` | Judgment-ledger corrections r3 (COMPLETE); merged into the CI stream. |
| `chatgpt/product-memory-reconcile-2026-09-23` | `3ed0fd1e` | The 2026-09-23 product-memory reconciliation (documents only). |
| `claude/product-memory-foundation` | `8d6b1112` | Product memory as of 2026-09-21. |
| `claude/v05-production-integration-2026-09-22` | `d9621337` | CLIVE Live Experience V0.5 production-lineage integration candidate: owner-gated, not accepted, not deployed. |
| `chatgpt/clive-live-experience-v0-5` | `ff7e2279` | The V0.5 implementation stream; not production authority. |
| `clive/engineering-state` (orphan) | moves with every kernel verb | Kernel records. |
| `crooks-ai-bridge` (orphan) | moves with every message | Inbox/outbox. |

The other `claude/*`, `chatgpt/*` and `experiment/*` branches are earlier reviews, experiments and candidates. Their standing is recorded in the product memory (`DECISIONS.md`, `CURRENT_TRUTH.md`); treat them as history unless a record says otherwise.

## What is, and is not, deployed

Deployment is recorded in the product memory, not implied by a branch: DEC-048 ratified the Linux production runtime at `1cf3a0f3361b79f9de208d80f501543c53c244b5` (2026-09-19). None of the candidates accepted since then has been deployed, and a green acceptance run or a COMPLETE kernel task is not a deployment. Deployment, runtime, watcher, systemd, secrets, permissions, external sends and business writes are the owner's decisions, made outside this repository. Nothing in this repository sends an email, changes an order or writes to the store on its own: the application proposes, the owner applies, and read-only tools (the Support Investigator among them) cannot write at all.

## How engineering work happens

One bounded task at a time, through the kernel: task → assignment → candidate → evidence bound to the exact SHA → independent exact-SHA review by a different principal (GPT reviews Claude-authored candidates) → repair rounds as successor commits, never rewrites → acceptance → fast-forward integration of the exact accepted SHA into the task's target branch → COMPLETE. Mechanical evidence comes from `crooks-assistant/scripts/acceptance_provenance.py` (ruff, control-plane tests, product-memory structure, the full offline test suite, a secret scan) and the `acceptance` GitHub Actions workflow on the application branches; mechanical gates produce evidence, not permission. Previous reviews never transfer to a modified SHA.

## Shopify theme


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
