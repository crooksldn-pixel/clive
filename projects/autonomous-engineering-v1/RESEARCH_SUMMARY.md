# Research synthesis

This is the distilled research input. It is not proof of live host state.

## Strongest conclusion

The recommended architecture is Desktop-as-Supervisor:

George → Claude Desktop over SSH → inspect/research/specify/explain → CLIVE engineering control plane → isolated workers → tests and exact-SHA CI → independent review → bounded repair → trunk → evidence summary → owner deployment decision.

Desktop-as-Worker is not the default because durable work should not depend on an interactive session. GitHub-only is durable but unnecessarily indirect for interactive supervision. A dedicated engineering MCP may be useful later, but only after a small deterministic CLI/control interface is proven insufficient.

## Source-level findings to verify

Prior repository review indicates CLIVE already has:
- dispatcher lifecycle and repair;
- separate workspaces and fresh builder sessions;
- configurable concurrency;
- candidate check sandbox;
- exact-SHA GitHub acceptance;
- fresh independent reviewer implementations;
- remote engineering inbox/status;
- Builds surfaces;
- behavioral Bench;
- hash-pinned builder skills.

The planning session must prove which are live and exercised on the worker.

## Research priorities

1. establish current engineering reality;
2. establish baseline owner attention and wall-clock time;
3. add project-level orchestration above objectives;
4. compile intent into bounded acceptance and dependencies;
5. route narrow skills/context;
6. measure concurrency rather than maximize it;
7. route appropriate quality gates;
8. reduce owner interruptions to genuine owner decisions;
9. make execution resilient to Desktop/SSH loss;
10. measure before/after outcomes.

## Tooling conclusion

For coding agents, current Playwright MCP guidance notes that CLI + skills can be more token-efficient than MCP for high-throughput coding workflows. Therefore V1 should not automatically make Playwright MCP a universal worker dependency. CLIVE already has browser-capable tests; planning should decide whether exploratory browser work uses Playwright CLI, existing tests, or MCP only on a narrow verifier/supervisor path.

Context7 is useful for current external library/API documentation, but it is supporting evidence, not authority over CLIVE's source or decisions.
