# Acceptance contract

The prototype is accepted only when every MUST below is true.

## MUST — isolation

- All implementation lives under `experiments/fmhy-link-finder/`.
- No CLIVE production route/tool/store/schema/deploy path is changed.
- Experiment dependencies are not added to `crooks-assistant/pyproject.toml`.
- No production secret is required.

## MUST — behavior

- Accept title and optional year.
- Search at least one ordinary public catalogue/search surface.
- Extract candidate title/year/public page href.
- Return a fully resolved public title-page URL for FOUND.
- Return explicit status for failure.
- One source failure does not fail the whole request.
- Matching is deterministic and inspectable.
- Ambiguity/low confidence fails closed rather than guessing.

## MUST — allowed surface only

Implementation contains no mechanism for:
- media manifest/segment/file URL extraction;
- CDN/provider token extraction;
- player/iframe media reverse engineering;
- DRM inspection;
- CAPTCHA/challenge bypass;
- proxy rotation or fingerprint spoofing;
- account/credential automation;
- geoblock bypass.

Playwright is used only for public search/catalogue/title DOM when HTTP is insufficient.

## MUST — quality

- Offline unit tests cover normalization, matching, URL resolution and parser fixtures.
- At least one explicit false-positive test exists.
- Live checks are separate from normal unit tests.
- HTTP/browser calls have finite timeouts.
- UI exposes loading and per-source failure states.
- Raw tracebacks are not shown in the UI.
- Logs avoid cookies/auth data and giant HTML dumps.

## MUST — evidence

A final `reports/live-smoke.md` contains at least five materially different queries and records:
- query;
- source;
- status;
- matched title/year;
- confidence;
- public URL for FOUND;
- elapsed time;
- note.

A FOUND result is counted only after the public URL is verified to resolve to the intended title
page.

## SHOULD

- HTTP is attempted before browser rendering.
- No more than one or two new runtime dependencies beyond the experiment's web stack.
- One adapter can be understood in one file plus shared helpers.
- Median HTTP-only search is under 3 seconds when the source is responsive.
- Browser fallback is under 12 seconds when the source is responsive.
- At least two sources work if a second source can be added without reverse engineering.

## Reviewer verdict

`fmhy-reviewer` must end with PASS.

If it returns FAIL, the experiment is not done even if the UI appears to work.
