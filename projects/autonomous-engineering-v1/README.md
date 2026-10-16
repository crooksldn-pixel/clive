# CLIVE Autonomous Engineering V1 — planning package

**Status (2026-10-16):** revision 4 **APPROVED by George.** **The Stage A steps he authorised are done:** A1, RP1 (worker-01 on `ef204bc2` with the Claude reviewer) and retiring the production-host loop. The record is in [STAGE_A_RUNBOOK.md](STAGE_A_RUNBOOK.md). The rest of the plan's Stage A (PR 0, PR 1, B0) and Stage B wait for his go. O-1 and O-2 are approved, and O-3 is deferred until the baseline (DECISIONS.md). Start with
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) (its last section is the recommendation), then
[CURRENT_ENGINEERING_REALITY.md](CURRENT_ENGINEERING_REALITY.md) and
[DECISIONS.md](DECISIONS.md) (three open owner decisions: O-1, the ruling-9 filing-authority design in [FILING_AUTHORITY.md](FILING_AUTHORITY.md); O-2, the supervisor's identity; O-3, the OAMAB threshold, after measurement). The evidence is in
[`audit/`](audit/); the plan's review is in [PLAN_REVIEW.md](PLAN_REVIEW.md).

**Audit disclosure:** the host audit was read-only except for one incidental write. A `git status`
on the production checkout refreshed git's index stat cache (`/opt/crooks-os/.git/index`, 2026-10-14
11:40:50 UTC). HEAD, refs, the working tree and the service were unchanged.

**Correction to the original brief:** the SSH host this package was planned from is
`crooks-os-prod-1`, the **production** host, not the engineering worker. The loop runs on
clive-worker-01, which was observed only through its public status branch.

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

## What is already believed to exist (now verified: see CURRENT_ENGINEERING_REALITY)

The repository appears to already contain most of the durable engineering kernel: dispatcher/lifecycle, isolated workspaces, bounded repair, candidate sandbox checks, exact-SHA GitHub acceptance, fresh independent reviewers, remote engineering/status bridge, Builds, Bench, and hash-pinned builder skills. These are source-level findings, not proof of live worker state.

## What this project should add (original brief; superseded in part: the "durable Project object" is CLIVE's existing `Objective(kind=build)`, see DECISIONS P-011)

Only missing layers: a durable Project object above objectives, intent-to-spec compilation, dependency-aware scheduling on top of the existing dispatcher, targeted skill/context routing, measured concurrency, quality-gate routing, owner-interruption classification/batching, a small deterministic Desktop supervisor interface, and project-first evidence/status presentation.

## What this project must not become

No second orchestrator, no second queue, no arbitrary swarm, no telemetry wall, no builder self-review, no automatic production deployment, no bypass of exact-SHA evidence, and no durable work that depends on the SSH/Desktop session staying connected.

## Branch rule

This planning branch may produce planning artifacts and supporting Claude skills/agents only. Implementation starts later on independently reviewable branches after owner approval.
