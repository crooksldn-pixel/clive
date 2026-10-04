# CROOKS LDN: theme and Shopify sister apps

This repo holds the CROOKS Shopify theme (Liquid, at the root) and the Shopify **sister apps**:

| App | Path | State |
| --- | --- | --- |
| CROOKS Returns | `crooks-returns/` | live at crooksldn.com/pages/returns |
| CLIVE Shipping | `clive-shipping/` | in development, see `docs/shipping/DESIGN.md` |
| Restock, Fit/Size, Preorder, Wishlist, Stock Intelligence, Offers | (future) | build in the same pattern |

Sister apps are separate services that share patterns, not code: Python 3.11, FastAPI, httpx,
Pydantic, SQLite, pytest and ruff; Shopify Admin GraphQL; embedded admin built with Polaris web
components and App Bridge; Docker Compose behind Caddy. The main CLIVE system is not in this
repo and is out of scope here.

## How work is done here

1. Understand the requirement.
2. Inspect the relevant sister app or pattern; Returns is the precedent.
3. Design the smallest sensible change.
4. Implement.
5. Test, and deliberately test the dangerous failure cases (lost replies, retries, double
   clicks, stale previews, partial failures).
6. Review (see `REVIEW.md`); "tests pass" is not a review.
7. Verify in the actual UI or API.
8. Commit one coherent stage.

Don't change Returns to match Shipping (or the reverse) unless the owner asks. Live secrets never
go in chat or the repo; they are set on the server.

## Checks

Run from the app's directory (`crooks-returns/` or `clive-shipping/`):

```bash
python -m pytest -q                    # tests
ruff check . && ruff format --check .  # lint and format (config in pyproject.toml)
pyright <changed files>                # types; config in /pyrightconfig.json
```

Pyright had 54 existing errors on 2026-10-05 (after the purchase-path fixes), mostly Optional
narrowing that is already guarded. Don't add new ones in
files you touch. In cloud sessions the pyright-lsp plugin doesn't run (Claude Code doesn't start
language servers there), so run the CLI; in a local terminal the plugin gives diagnostics after
edits and an `LSP` tool for definitions and references.

## Project skills

`.claude/skills/`: `shopify-sister-app` (product philosophy), `shopify-native-ui` (embedded
screens), `transaction-safety` (anything that pays, buys, refunds or can't be undone),
`provider-integration` (external APIs), `testing-standard` (failure-mode tests, done means
verified). Use them whenever their description applies; several often do at once.

## Which tool, when

**Shopify: check, don't remember.** For any Shopify API work that is new to the code, or
version-sensitive (Admin GraphQL fields and mutations, FulfillmentOrders, Returns, Inventory,
Products/Variants, Metafields, webhooks, scopes, App Bridge, Polaris, Functions, extensions,
Shopify CLI), use the Shopify AI Toolkit skills (`shopify-plugin:*`, e.g.
`shopify-plugin:shopify-admin`, `shopify-plugin:shopify-polaris-app-home`).
- Validate every new or changed GraphQL document with its `validate.mjs` before relying on it.
  Validation is local; telemetry is off (`OPT_OUT_INSTRUMENTATION=true`).
- Its docs search needs `shopify.dev`, which the cloud environment's network allowlist may block
  (HTTP 403). Then use the Shopify connector's `search_docs_chunks` / `graphql_schema` /
  `validate_graphql_codeblocks` if this session has it, and say which source you used.
- Don't do a lookup for code that already works and that you are only moving.

**Other libraries: Context7** (`crooks-dev` plugin, `resolve-library-id` then `query-docs`) for
version-sensitive behaviour of FastAPI, httpx, Pydantic, pytest, Playwright, provider SDKs.
Not for language basics or our own code.

**Browser: Playwright MCP** (`crooks-dev` plugin, Microsoft's `@playwright/mcp`). Any significant
UI change is checked in a real browser, not by reading HTML/CSS:
- Returns locally: `cd crooks-returns && python scripts/dev_server.py` (fake store, test labels,
  two seeded returns, no secrets). Admin `http://127.0.0.1:8114/apps/returns/admin`, portal
  `http://127.0.0.1:8114/` (order 1939, proof `E1 6AN`).
- Check the screens, the empty, error and confirmation states, and the console and network.
  Outside Shopify admin, "App Bridge Next: missing required configuration fields: shop" and a
  favicon 404 are expected; anything else is a finding.
- Screenshots and snapshots go to the server's output directory (`/tmp/playwright-mcp`, outside
  the repo; the server refuses other paths). Copy from there if one should be kept.
- The embedded app inside Shopify admin needs a Shopify login, so it is checked by the owner.

**Debugging, TDD, finishing:** `crooks-dev:systematic-debugging` (root cause before fixes),
`crooks-dev:test-driven-development` (failing test first for bugs and protocol changes),
`crooks-dev:verification-before-completion` (evidence before "done"),
`crooks-dev:receiving-code-review`. These are on-demand discipline, not product direction.

**Review:** see `REVIEW.md`. After a significant stage, run `/code-review` on the diff. For error
handling and tests use the pr-review-toolkit agents (`silent-failure-hunter`,
`pr-test-analyzer`, `type-design-analyzer`).

**Security:** the security-guidance plugin warns on risky edits and reviews diffs and commits
automatically, using the project rules in `.claude/claude-security-guidance.md`. Run a deep
`/claude-security` scan, and `/security-review` on the diff, before any of these milestones:
multi-tenancy, a public API, App Store submission, more merchants, storing merchant secrets,
billing, or new money-moving actions.

## Cloud sessions

`.claude/hooks/session-start.sh` installs both apps (editable, dev extras), pyright, and trusts
the environment's TLS-inspection CAs in the browser store, so Chromium can load
`cdn.shopify.com` (App Bridge and Polaris). Plugins are declared in `.claude/settings.json`. The
`crooks-dev` plugin lives in `.claude/marketplace/`. Which tool for which situation, and what was
rejected: `docs/development/CLAUDE_TOOLING.md`.
