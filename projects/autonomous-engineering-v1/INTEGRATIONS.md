# Integration strategy

A new connector is justified only when it closes a measured gap.

## Required V1 integrations

### Existing Git/GitHub acceptance
Keep exact candidate SHA, branch/trunk history and CI evidence. Do not replace existing acceptance or engineering bridge behavior.

### Existing CLIVE engineering control plane
Reuse dispatcher, workspaces, workers, reviewers, sandbox checks, remote engineering, engineering bridge, Builds and Bench.

### Context7
The planning branch exposes Context7 for current external library/API documentation.

Rules:
- use exact library/version when possible;
- never treat community docs as authority over CLIVE source;
- do not send business/customer secrets;
- worker use requires separate justification before production enablement.

### Browser tooling
First reuse CLIVE's existing Chromium/Playwright-capable test harness.

For exploratory coding-agent browser work, evaluate Playwright CLI + skill before making Playwright MCP a universal dependency. Current Microsoft guidance explicitly notes CLI + skills can be more token-efficient for coding agents. Playwright MCP may still be useful on a narrow supervisor/verifier path where persistent browser state matters.

### Claude Desktop / SSH
This is the interactive supervisor surface. It must never hold durable project state exclusively.

## Not required for V1
- new database merely for orchestration;
- Redis/queue product merely for orchestration;
- external agent framework;
- new observability SaaS;
- broad GitHub MCP access for autonomous builders;
- inherited business connectors in workers;
- automatic production deployment.

## Future engineering MCP
Only build after a stable CLI/control surface exists and measured friction remains. If built, it should wrap that stable interface rather than become a second control plane.
