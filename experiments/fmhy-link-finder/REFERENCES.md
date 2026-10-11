# Reference stack

Use these as documentation/pattern sources. Do not vendor whole repositories.

## Source catalogue

### FMHY

- Repository: `fmhy/edit`
- Purpose here: current public catalogue and metadata about streaming aggregator entries.
- Prefer FMHY's maintained Markdown/JSON backup surfaces rather than scraping the rendered FMHY site
  when structured data is available.
- FMHY is a directory; it does not make an adapter trustworthy or stable by itself.

## Browser automation

### Playwright MCP

- Repository: `microsoft/playwright-mcp`
- Project MCP server is configured in root `.mcp.json`.
- Use for exploratory DOM/accessibility inspection and live verification.
- Config is pinned to `@playwright/mcp@0.0.83` in this branch for reproducibility.
- Headless + isolated mode is intentional.
- Keep it on public catalogue/search/title pages only.

### Playwright Python

- Repository: `microsoft/playwright-python`
- Add as an experiment dependency only if a runtime adapter truly needs JS rendering.
- Install only Chromium if that is all the experiment uses.
- Prefer locator/condition waits over sleeps.

## Current library documentation

### Context7

- Repository: `upstash/context7`
- Remote MCP server is configured in root `.mcp.json`.
- Use it for version-current docs for Playwright, FastAPI, httpx, RapidFuzz and pytest.
- If unavailable, use official upstream docs. Do not block the build on Context7.

## HTTP/API

### httpx

- Repository: `encode/httpx`
- Use async client, finite timeouts and ordinary redirects.
- Keep concurrency low and source failures isolated.

### FastAPI

- Repository: `fastapi/fastapi`
- Suitable for the tiny local API and static page if the prototype uses a server.
- Avoid introducing persistence/auth/session machinery.

## Matching

### RapidFuzz

- Repository: `rapidfuzz/RapidFuzz`
- Use deterministic string similarity as one signal, not the only signal.
- Exact normalized title and year agreement should dominate.
- Prefer NO_MATCH to a plausible-but-wrong title.

## HTML parsing

Start with a small established parser rather than browser automation if the page is server-rendered.
`beautifulsoup4` is acceptable for the disposable prototype. Keep selectors adapter-local.

Do not add anti-bot/scraping-evasion frameworks.

## Tests

### pytest

- Repository: `pytest-dev/pytest`
- Offline parser fixtures are the primary tests.
- Live smoke tests get a separate marker/command and must not make normal tests flaky.

## Claude development patterns

### Anthropic official plugin repository

- Repository: `anthropics/claude-plugins-official`
- Useful patterns:
  - `feature-dev` for explore -> architect -> implement -> review workflows;
  - `code-review` for independent multi-agent review;
  - `plugin-dev` for clean skill/subagent structure.
- This branch already contains purpose-built agents, so installing those plugins is optional.

## Existing repo skills

Use only where relevant:
- `web-design-guidelines`: final quick UI/accessibility review;
- `design-taste-frontend`: optional, only after acceptance behavior works;
- `high-end-visual-design`: not needed for the first prototype;
- `image-to-code`: not needed unless the user supplies a UI reference.

Functional correctness and evidence outrank visual polish.
