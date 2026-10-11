---
name: fmhy-link-finder
description: Build, test, or review the standalone FMHY public title-page discovery experiment on experiment/fmhy-link-finder. Use for public catalogue/search/title URLs only; never media stream extraction or access-control bypass.
metadata:
  author: crooksldn-pixel
  version: "0.1.0"
---

# FMHY public link finder experiment

Use this skill only for the isolated experiment under `experiments/fmhy-link-finder/`.

## Mission

Prove the smallest reliable pipeline that turns a movie or TV query into a correctly matched
**public title/watch page URL** on one or more publicly accessible, FMHY-listed catalogue/stream
aggregator sites.

This is a discovery/search experiment. It is not a streaming client, downloader, proxy, scraper
framework, or CLIVE feature.

## Scope boundary

Allowed:
- read FMHY's public catalogue/backup data to identify candidate sites;
- use a site's ordinary public search or catalogue pages;
- extract result-card hrefs, canonical URLs, visible title/year metadata and public page metadata;
- use normal HTTP requests first;
- use Playwright for JavaScript-rendered public search/title pages when HTTP is insufficient;
- report BLOCKED, SITE_UNAVAILABLE, PARSE_ERROR and NO_MATCH cleanly;
- save small HTML fixtures for parser tests if they contain only the catalogue/search markup needed.

Do not:
- inspect player network traffic;
- extract `.m3u8`, MP4, CDN, manifest, token, media-segment or provider URLs;
- inspect hidden media APIs, iframe player internals or DRM;
- log in, create accounts or submit credentials;
- bypass CAPTCHA, Cloudflare, bot checks, geoblocks or rate limits;
- rotate proxies, spoof fingerprints or automate ad/redirect chains;
- download media;
- modify CLIVE runtime code, production schemas, tools, routes or deployment.

If a site requires any prohibited step, mark it BLOCKED or UNSUPPORTED and choose another target.

## First reads

Before implementation:
1. Read `experiments/fmhy-link-finder/PROMPT.md`.
2. Read `experiments/fmhy-link-finder/ACCEPTANCE.md`.
3. Read `experiments/fmhy-link-finder/REFERENCES.md`.
4. Read root `CLAUDE.md` only for repository boundaries.
5. Do not pull CLIVE architecture into this experiment unless a tiny generic utility is genuinely
   useful and copying the idea is simpler than coupling to it.

## Development strategy

Work in five passes.

### Pass 1 — discovery

Dispatch `fmhy-discovery` and have it:
- inspect the current FMHY catalogue/backup source;
- shortlist 3–5 candidate sites whose public search/catalogue surface is simple;
- prefer server-rendered HTML and stable title-page URLs;
- identify the smallest evidence needed for an adapter;
- reject targets that require challenge bypassing or player inspection.

The main agent then selects one target. Do not start with multiple adapters.

### Pass 2 — core implementation

Dispatch `fmhy-adapter-builder` for one adapter.

Prefer this dependency order:
1. Python standard library where adequate;
2. existing CLIVE versions conceptually: FastAPI, httpx, RapidFuzz;
3. Beautiful Soup only if DOM parsing is awkward without it;
4. Playwright only when the target genuinely requires browser rendering.

Keep dependencies in the experiment's own `pyproject.toml`. Never add experiment dependencies to
`crooks-assistant/pyproject.toml`.

Use an adapter contract roughly equivalent to:

```python
class SiteAdapter(Protocol):
    name: str
    async def search(self, query: SearchQuery) -> list[Candidate]: ...
```

Candidate/result data should be explicit:
- requested_title
- requested_year (optional)
- title
- year (optional)
- url
- source
- confidence
- status
- evidence/reason

Do not return an apparently successful result below the match threshold. False positives are worse
than NO_MATCH.

### Pass 3 — matching and orchestration

Normalize:
- Unicode/case;
- punctuation and repeated whitespace;
- apostrophes;
- `&` versus `and`;
- a trailing/parenthesized year.

Score with deterministic, inspectable signals:
- exact normalized title;
- token similarity / RapidFuzz ratio;
- year agreement when present;
- penalties for conflicting year or materially different subtitle/sequel text.

Return the selected result plus enough scoring evidence to understand why it won.

Each source is isolated. A failed source must not fail the whole query.

Suggested status vocabulary:
- FOUND
- NO_MATCH
- SITE_UNAVAILABLE
- PARSE_ERROR
- BLOCKED
- UNSUPPORTED

### Pass 4 — local interface

Build the smallest useful browser UI:
- one search box;
- optional year field;
- Search button / Enter;
- per-source status;
- matched title/year;
- confidence;
- public page URL;
- concise error reason.

Do not spend significant time on aesthetics until the pipeline passes acceptance.

After functionality is correct, use the existing `web-design-guidelines` skill for a quick
accessibility/UX pass. The visual-design skills are optional and should not turn the prototype into
a design project.

### Pass 5 — live verification

The main agent should use Playwright MCP for exploratory verification of public search/title pages.
The `fmhy-browser-verifier` subagent should run deterministic local and live smoke checks.

For live pages:
- inspect DOM/accessibility state;
- search through the site's ordinary UI or public URL;
- verify that the returned href resolves to the expected public title page;
- stop before player/media interaction.

Then dispatch `fmhy-reviewer` for a fresh review against ACCEPTANCE.md. Fix material findings and
rerun the focused tests.

## Browser policy

HTTP first. Browser second.

Use Playwright because it gives deterministic DOM/accessibility inspection and JavaScript rendering,
not because it can expose network internals.

For this experiment:
- use isolated/incognito contexts;
- headless is fine;
- no saved cookies/session state;
- no credentials;
- no stealth plugins;
- no network interception aimed at media;
- no player clicks after reaching the public title page.

If Playwright MCP is unavailable, the implementation may use Playwright Python as an optional
runtime/dev dependency. Keep that fallback adapter-specific.

## Documentation grounding

When using library APIs, use Context7 if available for current documentation, especially for:
- Playwright;
- FastAPI;
- httpx;
- RapidFuzz;
- pytest.

Do not copy external projects wholesale. Use official docs and small established patterns.

## Evidence expected at the end

Produce:
- commands used to install/run;
- tests run and their result;
- live smoke matrix for at least five materially different queries;
- actual status and public page URL for FOUND cases;
- per-site latency;
- failures with classified reason;
- files changed;
- dependencies added;
- one paragraph on whether this experiment is worth integrating later.

Stop there. Do not integrate it into CLIVE.
