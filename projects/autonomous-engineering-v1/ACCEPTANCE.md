# Planning acceptance contract

The planning phase passes only when all criteria below are evidenced.

## Current truth
- [ ] CURRENT_ENGINEERING_REALITY.md distinguishes BUILT / ACTIVE / PROVEN / GAP / UNKNOWN.
- [ ] Canonical integration base is confirmed from repo evidence.
- [ ] Production SHA, trunk SHA and worker pin are recorded separately where knowable.
- [ ] Claude CLI version, reviewer selection, concurrency, browser availability and relevant worker services are verified read-only or marked UNKNOWN.
- [ ] No host mutation was performed to obtain evidence.

## Architecture
- [ ] The design reuses CLIVE's existing dispatcher rather than replacing it.
- [ ] Claude Desktop/SSH is supervisory; durable work survives Desktop/SSH loss.
- [ ] A Project layer above engineering objectives is specified.
- [ ] Project dependency/DAG semantics are specified.
- [ ] Builder, verifier and reviewer responsibilities are separated.
- [ ] Production deployment remains an explicit owner decision.
- [ ] No builder can accept its own candidate.

## Context and skills
- [ ] Core and specialist skills are defined.
- [ ] Skill routing is task-specific rather than all-skills-by-default.
- [ ] Existing hash-pinned skill guarantees are preserved.
- [ ] Product memory retrieval is selective and current-truth-first.
- [ ] External instructions are treated as untrusted data.

## Quality
- [ ] Quality routing covers scope/static/unit/integration/browser/Bench/exact-SHA/review layers.
- [ ] Work types map to required gates.
- [ ] Bounded repair carries structured failure evidence automatically.
- [ ] Fault-injection experiments are planned before claiming the harness is sufficient.
- [ ] Fast feedback is separated from final exact-SHA acceptance.

## Human attention
- [ ] Allowed owner-interruption categories are explicit.
- [ ] Routine build/test/review failures do not require George as courier.
- [ ] Non-urgent owner questions are batched.
- [ ] Technical telemetry is progressively disclosed rather than shown by default.

## Concurrency and resilience
- [ ] Baseline measurement precedes concurrency claims.
- [ ] Concurrency is benchmarked incrementally.
- [ ] Dependencies, path conflicts and resource classes are represented.
- [ ] Disconnect/restart/outage drills are defined.
- [ ] No false COMPLETE state is possible after a failed or partial recovery.

## Implementation plan
- [ ] PR-sized sequence is ordered and dependency-aware.
- [ ] Every PR has acceptance, tests, risk, rollback and owner-visible payoff.
- [ ] NOW / NEXT / LATER / DO NOT BUILD are explicit.
- [ ] No implementation work is performed on this planning branch.
- [ ] Independent final reviewer returns READY or material findings are surfaced to George.

## Failure conditions

The plan fails if it proposes a second orchestrator without proving the current one insufficient, makes Desktop the durable executor, raises concurrency without evidence, permits self-review, weakens exact-SHA/sandbox/deploy controls, makes George relay routine errors, grants broad credentials/connectors to workers, confuses documentation with runtime truth, or begins implementation before owner approval.
