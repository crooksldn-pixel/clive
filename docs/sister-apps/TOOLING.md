# Claude Code tooling for the sister apps

Set up on 2026-10-05. Everything is declared in the repo, so every cloud session and every local
clone gets the same tools. How Claude should use them is in `/CLAUDE.md`; the review bar is in
`/REVIEW.md`.

## What is installed

**Plugins from `anthropics/claude-plugins-official`** (the official marketplace, declared in
`.claude/settings.json`):

| Plugin | Publisher | What it gives | Verified |
| --- | --- | --- | --- |
| `shopify-ai-toolkit` (skills `shopify-plugin:*`) | Shopify, v1.8.4 | 22 skills covering Admin GraphQL, Polaris app home and admin extensions, Functions, Liquid, custom data, Shopify CLI, App Store review. GraphQL validation against the bundled schema. | A fresh session validated a `fulfillmentOrders` query against 2026-07 and listed the required scopes. Docs search needs `shopify.dev`, which the cloud allowlist blocks today (403). |
| `pyright-lsp` | Anthropic | Diagnostics after edits and an `LSP` tool (definitions, references) | Terminal sessions only: Claude Code doesn't start language servers in cloud sessions (per the docs). In the cloud, the `pyright` CLI does the same checks. |
| `security-guidance` | Anthropic, v2.0.9 | Pattern warnings on edits; LLM review of the diff when a turn ends with source changes; agentic review on `git commit` | Its hooks ran in fresh sessions (baseline captured, empty review sets skipped). Uses `.claude/claude-security-guidance.md`. |
| `claude-security` | Anthropic, v0.12.0 | On-demand deep scan (`/claude-security`) with every finding challenged, plus verified patches | For milestones; nothing runs automatically except a tip after `git push`. |
| `pr-review-toolkit` | Anthropic | Review agents: `silent-failure-hunter`, `pr-test-analyzer`, `type-design-analyzer`, `code-reviewer`, `comment-analyzer`, `code-simplifier` | Complements the built-in `/code-review` and `/security-review`. |

**Our own plugin, `crooks-dev`** (`.claude/marketplace/crooks-dev`):

- **Playwright MCP.** Microsoft's `@playwright/mcp` 0.0.83, through `bin/playwright-mcp.sh`.
  - The official `playwright` plugin runs `npx @playwright/mcp@latest`, which wants Google
    Chrome. The cloud image has only Playwright's Chromium (`/opt/pw-browsers/chromium`, a build
    older than that release expects), so the wrapper points it there.
  - Off the cloud image, Playwright's defaults apply.
  - Verified in a fresh session: it opened the Returns admin, clicked into a return, read the
    heading, console errors and network requests, and took a screenshot.
- **Context7.** The anonymous hosted endpoint `https://mcp.context7.com/mcp`.
  - The official `context7` plugin's URL (`?client=claude-code-plugin`) demands an OAuth login,
    which a cloud session can't complete.
  - The plain endpoint works anonymously; a `CONTEXT7_API_KEY` raises the rate limits if set.
  - Verified: resolved httpx to `/encode/httpx` and returned the timeout docs.
- **Four Superpowers skills,** vendored at a pinned commit (MIT): `systematic-debugging`,
  `test-driven-development`, `verification-before-completion`, `receiving-code-review`. See
  `skills/README.md`.

**Session-start hook** (`.claude/hooks/session-start.sh`, cloud only, about 12 seconds,
idempotent):
- installs both apps editable with their dev extras;
- ensures pyright;
- trusts the environment's TLS-inspection CAs in the browser NSS store. Without this, Chromium
  fails on `cdn.shopify.com` with `ERR_CERT_AUTHORITY_INVALID`, and the admin renders without
  Polaris. Only the environment's own CAs are added; verification stays on.

**Also in the repo:**
- `pyrightconfig.json`: the two apps as separate roots; the theme and `node_modules` excluded.
- `crooks-returns/scripts/dev_server.py`: Returns with the fixture store, for browser checks.

## Considered and not installed

- **Superpowers (full plugin).** It is maintained (v6.4.x) and good, but its SessionStart hook
  injects a rule that makes skill use mandatory before any action, including brainstorming before
  any build. That would dictate process, so only the four discipline skills are vendored.
- **Official `playwright` and `context7` plugins.** Replaced by the `crooks-dev` versions above,
  for the reasons given there. Same upstream servers.
- **`code-review` plugin.** Duplicates the built-in `/code-review`, and its command is aimed at
  posting on GitHub PRs.
- **Chrome DevTools MCP** (`chrome-devtools-mcp`, Google). Playwright MCP already covers console
  errors, failed requests with status, screenshots and scripted journeys, verified above.
  DevTools would add performance traces and source-mapped stacks. Revisit when debugging
  performance, CSP or App Bridge iframe issues inside the real admin; it needs a Chrome
  executable.
- **Logfire** (Pydantic, plugin `logfire`). It would give real visibility: FastAPI requests,
  httpx calls to Parcel2Go and Shopify, latencies and exceptions, with auto-instrumentation in a
  few lines. It is not adopted yet because:
  - it is a hosted service that would receive request data, including customer details unless
    scrubbing is configured;
  - it needs an account and a token on the server;
  - today one store runs on one box, where structured logs, `returns-ctl` and the timelines
    answer the questions.

  Revisit when Shipping goes live, or when a second merchant arrives: instrument FastAPI and
  httpx, scrub PII, and keep the token on the server.
- **Shopify App Builder** (community). 36 skills that overlap Shopify's own toolkit, with no
  verified publisher. Shopify's official toolkit is preferred.
- **`liquid-lsp`** (Shopify). Useful for theme work, not the sister apps. It also needs the
  Shopify CLI, and plugin language servers don't run in cloud sessions anyway.

## Known gaps

- `shopify.dev` isn't on the cloud environment's network allowlist, so the toolkit's docs search
  gets HTTP 403. Add it under Network access → Custom → Allowed domains in the environment
  settings. Until then, the Shopify connector's docs search works.
- The embedded app inside Shopify admin can't be opened by Claude (it needs a Shopify login).
  Local checks use the dev server; checks inside the admin are the owner's.
- Shipping has no admin UI yet (Stage 6). Comparing Returns and Shipping screens side by side
  becomes possible then, with the same Playwright setup.
