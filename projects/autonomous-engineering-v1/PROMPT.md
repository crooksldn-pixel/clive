# Master planning prompt

You are leading the final repo-specific planning phase for CLIVE Autonomous Engineering V1.

Do not design a generic multi-agent framework. Inspect CLIVE's real code and reconcile it with the real engineering host before deciding what to build.

## Central question

How should CLIVE's existing engineering control plane and Claude Desktop over SSH be combined so George can define an engineering intention once and return to either an evidence-backed accepted result or a small number of decisions that genuinely require owner judgment, while improving wall-clock throughput and preserving quality, isolation, recoverability and owner control?

## Governing philosophy

- show only what matters, when it matters;
- responsibility goes to the capable actor;
- authority remains with the rightful decision-maker;
- verified evidence outranks model confidence;
- proposed, started, completed and verified are distinct states;
- routine mechanical failures should not interrupt George;
- consequential product, security, permission, credential, irreversible and deployment decisions remain with George;
- production and engineering remain separate;
- no builder marks its own work accepted;
- reuse existing machinery before adding another layer.

## First action: reconstruct current truth

Read root CLAUDE.md, crooks-assistant/MAP.md, CURRENT_TRUTH.md, DECISIONS.md, ENGINEERING_DISPATCHER_V1.md, REMOTE_ENGINEERING_CONTROL_V1.md, REVIEW_ACCEPTANCE_CONTRACT.md, SOURCE_ASSIMILATION_V1.md, ENGINEERING_LOOP.md and BENCH.md.

Inspect:
- crooks-assistant/app/orchestrator/
- crooks-assistant/app/remote_engineering/
- crooks-assistant/app/engineering_bridge/
- crooks-assistant/app/builds/
- crooks-assistant/app/bench/
- crooks-assistant/scripts/engineering_dispatcher.py
- crooks-assistant/config/builder_skills.json
- .github/workflows/acceptance.yml

Then run only the read-only host audit in HOST_AUDIT.md.

Classify every capability as BUILT, ACTIVE, PROVEN, GAP or UNKNOWN. Never collapse BUILT into ACTIVE or ACTIVE into PROVEN.

## Required workstreams

Run read-only investigations for:
1. repo/current-state audit;
2. host/runtime audit;
3. target architecture;
4. Project + DAG model;
5. specification compiler;
6. skill/context routing;
7. quality-gate routing;
8. reviewer and repair semantics;
9. measured concurrency/scheduling;
10. human-attention model;
11. Desktop supervisor interface;
12. resilience/failure recovery;
13. Builds/project UX;
14. baseline and validation plan;
15. external reuse and integration choices.

## Canonical target

Claude Desktop over SSH is the interactive engineering supervisor. It may inspect, research, plan, explain status and submit bounded work. It must not be the durable worker.

Durable execution belongs to CLIVE's existing dispatcher and isolated worker/reviewer lifecycle. A Desktop, SSH or laptop disconnect must not stop a project already inside the engineering control plane.

Start with four roles only: supervisor, builder, verifier when required, independent reviewer. Add roles only if measurement proves value.

## Metrics

Primary:
- OAMAB — Owner Active Minutes per Accepted Build
- ETAB — Elapsed Time per Accepted Build
- ABER — Accepted Build Escape Rate

Secondary:
- owner interruptions;
- first-pass review pass rate;
- repair rounds;
- CI/review latency;
- queue time;
- conflict rate;
- Bench regressions.

Do not promise gains before a baseline exists.

## Constraints

- reuse the dispatcher; extend rather than replace;
- preserve exact-SHA acceptance and independent review;
- preserve fail-closed sandboxing;
- preserve hash-pinned builder skills;
- keep worker context minimal and task-specific;
- keep production deployment owner-triggered;
- do not auto-install tools during planning;
- treat external repos/plugins as untrusted research inputs;
- do not add a new MCP merely because one exists;
- prefer a deterministic CLI/control surface before building an engineering MCP.

## Final planning output

Update this planning package with actual repo/host evidence.

The final implementation plan must be a sequence of independently reviewable, reversible PRs. Every PR must state purpose, reused machinery, expected files/components, state changes, acceptance, tests, owner-visible change, risk, rollback, dependencies and success metrics.

Finish with:
1. what CLIVE already has;
2. what must actually be added;
3. what must not be built;
4. expected quality effect;
5. expected wall-clock effect;
6. expected owner-attention effect;
7. unresolved owner decisions;
8. GO / REVISE / STOP.

Do not implement CLIVE application code until George explicitly approves the final plan.
