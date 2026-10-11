---
name: browser-investigation
description: Use browser tooling as evidence for CLIVE UI behavior while preferring deterministic tests and the existing browser harness over unrestricted exploratory automation.
---

# Browser Investigation

Order of preference:
1. existing deterministic browser tests;
2. Playwright CLI/skill for focused reproduction if available and approved;
3. Playwright MCP only when persistent structured browser state materially improves investigation.

Do not install browser tooling during planning. Do not weaken sandboxing merely to make browser tooling launch. Record route, viewport, user journey and observed result. Exploratory success is not final acceptance.
