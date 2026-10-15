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
Anthropic's documentation (audit/CLAUDE_CODE_CAPABILITIES.md) says a Desktop SSH session may outlive
a dropped connection but should not be counted on overnight, and ends on a host restart. That
confirms P-001.

Today the supervisor runs **as root on the production host**. In V1 (O-2), Claude Desktop on
George's Mac is the client. It runs commands on clive-worker-01 as a non-root, read-only user that
cannot read the loop's token. It has no GitHub write credential, and submits drafts only through
CLIVE's filing path (FILING_AUTHORITY).

### Claude Code CLI and the Agent SDK
V1 keeps driving the Claude Code CLI, as the loop does today: headless, `--permission-mode dontAsk`,
`--tools`, `--strict-mcp-config`, `--setting-sources ""`, and an environment built from scratch with an
OAuth token file only. The Agent SDK is **not** adopted, because its support for subscription login is
not clearly documented and MAP rule 5 forbids API keys. `--bare` is ruled out for the same reason.

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
