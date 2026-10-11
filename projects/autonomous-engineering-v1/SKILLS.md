# Skills and context strategy

## Rule

Workers receive the minimum relevant skills and context for the objective. Do not inject the whole product brain into every session.

## Core skills
### clive-engineering
Repository map, integration base, engineering lifecycle, protected boundaries, existing dispatcher/reviewer/check contracts and deploy separation.

### clive-product-philosophy
Minimal surfaces, authority boundaries, truthful state, proposed vs verified, progressive disclosure and low owner interruption.

### clive-testing
Focused tests, exact-SHA evidence, browser/Bench routing, independent review and repair evidence.

## Specialist skills
### clive-ui
Owner-visible screens, mobile/tablet behavior and browser evidence.

### external-api-integration
Auth, permissions, rate limits, retries, webhooks, idempotency, failure classification and mocks.

### clive-security
Credentials, PII, prompt injection, permissions, network boundaries, destructive operations and fail-closed behavior.

### research-assimilation
Canonical upstream, pinned versions, license, hooks/installers/binaries, compare-with-CLIVE, adopt/park/reject.

### browser-investigation
Deterministic browser checks first; bounded exploratory Playwright only when useful.

Future domain skills such as clive-commerce, clive-messaging, clive-operations and clive-observability should be created only when repeated work proves a need.

## Routing examples

Fix Builds mobile spacing:
- clive-engineering
- clive-product-philosophy
- clive-ui
- clive-testing

Add Meta webhook ingestion:
- clive-engineering
- clive-product-philosophy
- external-api-integration
- clive-security
- clive-testing

Harden exact-SHA review:
- clive-engineering
- clive-security
- clive-testing

## Context hierarchy

1. project/task packet;
2. relevant skill;
3. CURRENT_TRUTH;
4. relevant architecture/source files;
5. relevant decisions;
6. external docs/research only as needed.

Production builder skills must remain curated, hash-pinned, protected from worker modification and loaded from a trusted base. Skills in this planning branch are planning-session tools, not automatically approved builder skills.
