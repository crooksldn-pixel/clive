# Claude Code tooling for the sister apps

The smallest toolkit that materially helps build safe, simple, Shopify-native sister apps.
Everything is declared in the repo (`.claude/`), so every session and clone gets the same setup.
Scope: the sister apps only (Returns, Shipping, and future Restock, Fit, Preorder, Wishlist,
Stock Intelligence, Offers), not the main CLIVE system.

## Which tool, when

| Situation | Use |
| --- | --- |
| Unsure about Shopify GraphQL schema, scopes or version differences | Shopify AI Toolkit: `shopify-plugin:shopify-admin`, then validate with its `validate.mjs` (Shipping: `python scripts/validate_graphql.py`, pinned to 2026-10) |
| Building embedded Shopify UI | `shopify-plugin:shopify-polaris-app-home` + the `shopify-native-ui` skill |
| Designing a new app, screen, flow or setting | the `shopify-sister-app` skill |
| Testing real UI | Playwright MCP, against the app's dev server (`crooks-returns/scripts/dev_server.py`) |
| Debugging browser/API interaction | Playwright MCP console and network tools (DevTools: later, see below) |
| Python symbol or type issue | Pyright: the `pyright` CLI in cloud sessions; the pyright-lsp plugin in a local terminal |
| Version-sensitive library question (FastAPI, httpx, Pydantic, Playwright…) | Context7 (`resolve-library-id`, then `query-docs`) |
| External API integration | the `provider-integration` skill |
| Money-moving or irreversible operation | the `transaction-safety` skill |
| Writing tests, or before claiming a feature complete | the `testing-standard` skill + `crooks-dev:verification-before-completion` + a real UI/API check |
| Bug or unexpected behaviour | `crooks-dev:systematic-debugging` |
| Significant implementation completed | `/code-review` on the diff + pr-review-toolkit agents (`silent-failure-hunter`, `pr-test-analyzer`), against `REVIEW.md` |
| Security-sensitive change | security-guidance (runs automatically); `/security-review` on the diff |
| Milestone: multi-tenancy, public API, App Store, more merchants, stored secrets, billing, new money-moving action | deep `/claude-security` scan |

## Classification

### Install now (installed, verified)

| Tool | Source | Why |
| --- | --- | --- |
| **Shopify AI Toolkit** (`shopify-ai-toolkit`, skills `shopify-plugin:*`) | Shopify, via Anthropic's official marketplace | Current schemas (2025-10 to 2026-10 and unstable, bundled) and local GraphQL validation; Polaris, Functions, Liquid and CLI skills. Telemetry off. |
| **Playwright MCP** (`@playwright/mcp` 0.0.83, in our `crooks-dev` plugin) | Microsoft | Real browser checks: navigation, clicks, forms, screenshots, console, network |
| **Context7** (in `crooks-dev`) | Upstash, hosted | Current library docs instead of memory |
| **pyright-lsp** + `pyright` CLI | Anthropic plugin; Microsoft pyright | Type awareness, diagnostics, navigation (the language server runs only in local terminals) |
| **security-guidance** | Anthropic | Lightweight, continuous: pattern warnings on edits, diff and commit reviews against `.claude/claude-security-guidance.md` |
| **claude-security** | Anthropic | Deep on-demand scans at milestones |
| **pr-review-toolkit** | Anthropic | Focused review agents for silent failures, test gaps and type design |
| **4 Superpowers skills** (vendored in `crooks-dev`) | obra/superpowers (MIT), pinned | Debugging, TDD, verification and review-handling discipline, used on demand |

Already present, no install needed: built-in `/code-review`, `/security-review` and `/simplify`;
ruff and pytest (project dev extras); Chromium at `/opt/pw-browsers`; the claude.ai Shopify
connector (`search_docs_chunks`, `graphql_schema`, `validate_graphql_codeblocks`), which is the
fallback when `shopify.dev` is blocked.

### Optional / later

- **Chrome DevTools MCP** (Google). Adds performance traces and source-mapped stacks. Add when
  debugging performance, CSP or App Bridge iframe issues inside the real admin; Playwright
  covers console, network and journeys today.
- **Logfire** (Pydantic). Would show FastAPI requests, httpx calls to Parcel2Go and Shopify,
  latency, exceptions, retries and webhook handling. Add when Shipping goes live or a second
  merchant arrives, with PII scrubbing and the token on the server. For now it is a hosted
  service receiving customer data, plus an account, for one store on one box where logs,
  `returns-ctl` and timelines suffice.
- **42Crunch API security testing**. When a public OpenAPI surface exists (multi-tenant or App
  Store).
- **liquid-lsp** (Shopify). For theme work, not the sister apps.

### Do not install

- **Superpowers (full plugin).** Its SessionStart hook makes skills mandatory before any action
  (brainstorming before every build), so it would dictate process. Its four useful skills are
  vendored instead.
- **Official `playwright` / `context7` plugins.** Replaced by `crooks-dev` versions: the official
  Playwright one wants Google Chrome (absent in cloud images), and the official Context7 URL
  forces an OAuth login a cloud session can't complete. Same upstream servers.
- **`code-review` plugin.** Duplicates the built-in `/code-review`.
- **Shopify App Builder** (community, 36 skills). Overlaps Shopify's own toolkit; unverified
  publisher.
- **Other "superpowers" remixes, memory/"OS" plugins, Langfuse.** Process takeover or not
  relevant.

## Project skills (`.claude/skills/`)

| Skill | Use when |
| --- | --- |
| `shopify-sister-app` | designing an app, screen, flow or setting (product philosophy) |
| `shopify-native-ui` | building or checking embedded admin screens |
| `transaction-safety` | anything that pays, buys, refunds, changes inventory or creates irreversible resources |
| `provider-integration` | adding or changing a provider adapter or webhook |
| `testing-standard` | writing tests; before calling anything done |

## How it was verified (2026-10-05)

Each check was run in a fresh `claude -p` session in this repo:

- **Shopify toolkit:** validated Shipping's seven Admin GraphQL documents against 2026-10 and
  listed their scopes.
- **Playwright:** opened the Returns admin and portal, clicked into a return, read the console
  and network, and took screenshots.
- **Context7:** returned current httpx timeout docs.
- **Pyright CLI:** ran clean on a sample file.
- **security-guidance:** its hooks ran (git baselines captured).

Fixes that were needed:

- **Browser trust.** The session-start hook trusts the environment's TLS-inspection CAs in the
  browser store, without which Chromium can't load App Bridge or Polaris from `cdn.shopify.com`.
- **Playwright launcher.** A wrapper points it at the installed Chromium.
- **Context7 login.** The anonymous endpoint avoids it.

## Known gaps

- `shopify.dev` isn't on the cloud environment's network allowlist, so the toolkit's docs
  search returns 403. Add it under the environment's Network access → Custom → Allowed domains.
  Validation works offline meanwhile.
- Language servers don't run in cloud sessions (a documented Claude Code limitation); the
  `pyright` CLI covers checks there.
- The embedded app inside Shopify admin needs a Shopify login: checking it there is the owner's.
