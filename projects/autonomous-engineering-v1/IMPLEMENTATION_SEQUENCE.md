# Proposed implementation sequence

This sequence must be revised after source/host audit. It is not implementation authority.

## PR 0 — current truth and baseline protocol
Record BUILT / ACTIVE / PROVEN / GAP / UNKNOWN, confirm worker pin/runtime configuration, and define reproducible baseline tasks. No product behavior change.

## PR 1 — lifecycle metrics
Instrument the existing engineering lifecycle without changing scheduling. Capture queue, build, check, CI, review, repair and landing timestamps/reasons so OAMAB, ETAB and ABER can be measured.

## PR 2 — Project model
Add a durable Project object above existing engineering objectives. Existing single-objective builds must behave identically when no Project is attached.

## PR 3 — project packet/schema
Validate and render intent, acceptance, risk, decisions, dependencies, skills/context and evidence.

## PR 4 — production-ready core skills + routing
Curate clive-engineering, clive-product-philosophy and clive-testing for the real builder allow-list, then add task-specific routing while preserving hash pinning.

## PR 5 — specification compiler
Turn a high-level approved request into a draft Project packet and objective DAG. Inspect repo/current truth first, separate facts from assumptions, batch owner-only questions, and require owner approval before durable execution.

## PR 6 — dependency-aware scheduling
Extend the existing dispatcher/scheduler with the minimum project semantics: dependency readiness, priority, path conflict metadata and resource class. No second queue.

## PR 7 — controlled concurrency
Benchmark 1 → 2 → 4 active builders. Increase defaults only when worker resources, plan/rate behavior, CI/review capacity and ABER remain healthy.

## PR 8 — quality routing
Map work/risk type to existing evidence layers: scope/static/unit/integration/browser/Bench/exact-SHA/review.

## PR 9 — reviewer/repair hardening
Ensure structured failed-check/reviewer evidence automatically reaches the next repair attempt. Escalate only on exhausted repair budget, requirement conflict or owner authority.

## PR 10 — human-attention contract
Add typed owner blockers and batching. Distinguish needs-owner, waiting-on-system, external blocker and autonomous repair.

## PR 11 — deterministic Desktop supervisor interface
Add a small stable interface over existing engineering state. Candidate shape:
- clive-eng status
- clive-eng projects
- clive-eng show <id>
- clive-eng draft <project>
- clive-eng submit <id>
- clive-eng evidence <id>

Exact commands depend on audit. Do not build an MCP first.

## PR 12 — project-first Builds UX
Default view: project name, meaningful state, trustworthy progress, and needs-you. SHAs, workers and logs are progressive disclosure.

## NEXT after measured V1
- critical-path scheduling;
- duration estimation;
- advanced resource scheduling;
- engineering MCP if CLI friction is material;
- heterogeneous/elevated reviewers for selected S4 work;
- source-assimilation automation;
- controlled proactive improvement proposals.

## DO NOT BUILD in V1
- replacement dispatcher;
- arbitrary swarm orchestration;
- automatic production deployment;
- universal worker browser MCP;
- universal all-skills context;
- self-modifying acceptance policy;
- broad owner/business connectors in autonomous workers.
