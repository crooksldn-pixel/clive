# CLIVE Autonomous Engineering V1 — planning package

This branch is the starting environment for a fresh Claude Code session connected over SSH to the real CLIVE engineering host.

It exists to turn the research and product philosophy into one repo-specific implementation plan. It is intentionally plan first. It does not authorize code changes to CLIVE, worker re-pins, service changes or production deployment.

## Desired outcome

George should be able to describe an engineering intention once, then leave the mechanical journey to CLIVE: Claude Desktop/SSH supervises, the existing CLIVE dispatcher owns durable execution, isolated workers build, evidence gates verify, a fresh independent reviewer judges, bounded repairs happen automatically, trunk integration is separate from production deployment, and George is interrupted only for genuine owner decisions.

## Read order

1. root `CLAUDE.md`
2. `crooks-assistant/MAP.md`
3. `crooks-assistant/docs/product-memory/CURRENT_TRUTH.md`
4. `PROMPT.md`
5. `ACCEPTANCE.md`
6. `RESEARCH_SUMMARY.md`
7. `ARCHITECTURE.md`
8. `HOST_AUDIT.md`
9. `IMPLEMENTATION_SEQUENCE.md`
10. remaining topic documents as needed

## What is already believed to exist

The repository appears to already contain most of the durable engineering kernel: dispatcher/lifecycle, isolated workspaces, bounded repair, candidate sandbox checks, exact-SHA GitHub acceptance, fresh independent reviewers, remote engineering/status bridge, Builds, Bench, and hash-pinned builder skills. These are source-level findings, not proof of live worker state.

## What this project should add

Only missing layers: a durable Project object above objectives, intent-to-spec compilation, dependency-aware scheduling on top of the existing dispatcher, targeted skill/context routing, measured concurrency, quality-gate routing, owner-interruption classification/batching, a small deterministic Desktop supervisor interface, and project-first evidence/status presentation.

## What this project must not become

No second orchestrator, no second queue, no arbitrary swarm, no telemetry wall, no builder self-review, no automatic production deployment, no bypass of exact-SHA evidence, and no durable work that depends on the SSH/Desktop session staying connected.

## Branch rule

This planning branch may produce planning artifacts and supporting Claude skills/agents only. Implementation starts later on independently reviewable branches after owner approval.
