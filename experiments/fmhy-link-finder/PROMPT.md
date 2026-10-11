# Build prompt — standalone FMHY public title-page finder

## Outcome

Build a disposable proof of concept, entirely inside this directory, that proves:

`movie/TV title + optional year -> one or more public catalogue searches -> correctly matched public title-page URL`

The result is a research/discovery interface. It is intentionally **not connected to CLIVE**.

A successful example should look conceptually like:

```
Query: Interstellar (2014)

Source A
FOUND
Matched: Interstellar (2014)
Confidence: 0.99
Public page: https://example.test/title/interstellar-2014
Elapsed: 0.74s

Source B
NO_MATCH
```

## Non-negotiable boundaries

Keep all implementation in `experiments/fmhy-link-finder/`.

Do not modify:
- CLIVE app routing;
- CLIVE tools;
- orchestrator;
- world model / product memory;
- production schemas or stores;
- production deploy files;
- `crooks-assistant/pyproject.toml`.

Do not extract or inspect:
- media files or segments;
- `.m3u8`/manifest URLs;
- MP4/CDN URLs;
- player tokens;
- DRM information;
- hidden media/provider APIs;
- iframe media sources;
- browser network traffic for underlying playback.

Do not implement:
- CAPTCHA or Cloudflare bypass;
- stealth/browser fingerprint evasion;
- proxy rotation;
- credential/account automation;
- geoblock bypass;
- aggressive crawling.

If a candidate site needs any of that, classify it as unsuitable and move on.

## How to work

Use the repo's custom agents rather than letting one long context do everything.

### Wave 1 — parallel discovery

Run `fmhy-discovery`.

In parallel, have a normal code-exploration pass inspect:
- this branch's CLAUDE.md;
- existing Python versions/patterns only as reference;
- the current experiment support files;
- available MCP servers.

The output of Wave 1 must choose a single first site and explain the reason.

### Wave 2 — architecture

Before implementation, write a 10–20 line plan in this directory's README covering:
- request flow;
- adapter interface;
- result model;
- matching logic;
- HTTP/browser strategy;
- tests;
- run command.

Keep it simple enough to throw away.

### Wave 3 — implementation

Run `fmhy-adapter-builder` for the first site.

Then the main agent builds:
- small orchestration/service layer;
- deterministic title matching;
- minimal local API/UI;
- structured diagnostics;
- tests.

Only after one site works end-to-end may you add a second adapter.

### Wave 4 — verification

Use Playwright MCP in the main session for live DOM verification where useful.

Run `fmhy-browser-verifier` for:
- local end-to-end UI checks;
- safe live smoke matrix;
- result evidence.

### Wave 5 — independent review

Run `fmhy-reviewer`.

Fix BLOCKER/HIGH findings. Rerun tests. Stop once acceptance passes.

## Preferred technical shape

Use Python 3.11+.

The CLIVE repo already demonstrates FastAPI, httpx and RapidFuzz, but this experiment should have
its own environment/dependency declaration.

Suggested layout:

```
experiments/fmhy-link-finder/
├── README.md
├── PROMPT.md
├── ACCEPTANCE.md
├── REFERENCES.md
├── pyproject.toml
├── app.py
├── finder/
│   ├── __init__.py
│   ├── models.py
│   ├── normalize.py
│   ├── match.py
│   ├── service.py
│   ├── fetch.py
│   ├── browser.py              # only if needed
│   └── adapters/
│       ├── __init__.py
│       ├── base.py
│       └── <site>.py
├── static/
│   └── index.html
├── tests/
│   ├── fixtures/
│   ├── test_normalize.py
│   ├── test_match.py
│   ├── test_urls.py
│   └── test_<site>_parser.py
└── reports/
    └── live-smoke.md
```

This is a suggestion, not a requirement. Fewer files is fine if clearer.

## Request/fetch strategy

Use HTTP first:
- `httpx.AsyncClient`;
- explicit connect/read timeout;
- normal descriptive User-Agent;
- follow ordinary redirects;
- low concurrency;
- no retry storms.

Suggested defaults:
- overall source timeout: 6s;
- max concurrent sources: 3;
- at most one retry for transient 5xx/network failures;
- no retry for 4xx/challenge pages.

A site adapter may declare that JavaScript rendering is required. Only then use Playwright.

Browser mode should:
- use an isolated context;
- navigate to public search/catalogue pages;
- wait for specific result DOM, not arbitrary sleeps;
- read visible attributes/hrefs;
- stop at the public title page.

## Parsing

Prefer stable semantic signals:
1. result-card anchor href;
2. visible title text;
3. visible year;
4. `link[rel=canonical]` or `meta[property=og:url]` on the public title page.

Do not scrape huge pages when one result container is enough.

When saving fixture HTML, reduce it to the minimum fragment necessary to test the parser. Fixtures
should not include player/media internals.

## Matching

Matching must be deterministic.

Normalize:
- Unicode;
- case;
- whitespace;
- punctuation;
- apostrophes;
- `&` / `and`;
- optional year suffix.

Score with inspectable components. A reasonable starting scheme:
- exact normalized title: dominant;
- RapidFuzz token/set or ratio score;
- year match bonus;
- year conflict penalty;
- sequel/subtitle mismatch penalty.

Do not let a generic shared word create a match.

Require a confidence threshold. If two candidates are too close and materially different, return
NO_MATCH/AMBIGUOUS rather than guessing.

The UI may show the final confidence; logs/dev diagnostics should show component scores.

## Result model

At minimum:

```json
{
  "source": "example",
  "status": "FOUND",
  "requested_title": "Interstellar",
  "requested_year": 2014,
  "matched_title": "Interstellar",
  "matched_year": 2014,
  "url": "https://example.test/title/interstellar",
  "confidence": 0.99,
  "elapsed_ms": 742,
  "reason": "exact normalized title + year"
}
```

Failure results still use the same envelope with URL/match fields null.

## Local interface

One screen.

Required:
- title input;
- optional year;
- Search;
- loading state;
- source result cards/rows;
- FOUND/NO_MATCH/BLOCKED/etc.;
- matched title/year;
- confidence;
- clickable public title-page URL;
- concise error reason.

No auth, accounts, database, saved history, analytics, CLIVE chrome or production design system.

After it works, use `web-design-guidelines` once. Do not spend more time polishing than building.

## Debugging

Development logs may include:
- source;
- search URL;
- HTTP status;
- parse candidate count;
- extracted title/year/public href;
- score components;
- selected match;
- elapsed time;
- classified failure.

Never log:
- cookies;
- auth headers;
- full challenge pages;
- player/media URLs;
- arbitrary giant HTML dumps.

Provide a `--debug` or environment switch if useful; normal mode should remain quiet.

## Tests

Unit tests must run offline.

Use minimal saved HTML fixtures for each parser.

Required coverage:
- normalization;
- URL resolution;
- title/year matching;
- false-positive examples;
- parser extraction;
- malformed/missing fields;
- source failure isolation.

Live tests are separate and manually invoked. CI/unit tests must not depend on FMHY or third-party
sites being online.

## Live smoke set

Use at least five materially different queries. The original examples are acceptable:
- Interstellar
- The Dark Knight
- Parasite
- Breaking Bad
- The Office

Add year where useful to test ambiguity.

For each query record:
- source;
- status;
- matched title/year;
- confidence;
- public title page URL if FOUND;
- elapsed time;
- note.

Do not claim a URL is valid merely because parsing returned it. Verify it resolves to the expected
public title page.

## Definition of done

Done means:
- one source works end-to-end;
- a second source is a bonus, not a blocker;
- local UI works;
- offline tests pass;
- five-query smoke matrix exists;
- false positives are not silently returned;
- failures are classified;
- no prohibited extraction/bypass exists;
- reviewer returns PASS;
- README tells a new person exactly how to install and run it.

At the end report:
- files created/changed;
- dependencies;
- run command;
- test command/result;
- smoke results;
- what worked;
- what failed;
- biggest brittleness;
- whether an eventual CLIVE connector is technically worthwhile.

Then stop. Do not integrate it into CLIVE.
