# EXACT-SHA GPT REVIEW PACKET 7 — Authoritative lifecycle producers (the kernel mandate)

Generated 2026-09-22 22:30Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. Two repositories, one package, plus the engineering-state branch the package wrote.

## Identity

| Field | CLIVE (kernel, CLI, projection, docs) | AGENT-ENVIRONMENT (rendering) | Engineering state (records) |
| --- | --- | --- | --- |
| candidate_sha | `6ffb2c6626e020c8313910adf76dd6e6be2c6848` | `c20f5397197652a65814bfc2972c19a4e4ec65f4` | `f514f5645b3d144784596c33d2ebc4da0d790670 (head after this package's candidate was recorded; the dispatch carrying this packet is the next kernel commit)` |
| branch (head == candidate when written) | `claude/control-plane-producers-2026-09-22` | `claude/clive-state-adapter` | `clive/engineering-state` (orphan; no code) |
| base / previous candidate | `84e12e77e712ed454f12a6300f6e5f5b54391252` (truth repairs, packet 6); also merges `ef3d08ff` (packet 8) | `119bb9bff5a09aa7f1f04799396bcb68cf34a10a` (packet 6) | none: created today |
| commits in the candidate | 11060463 (package), 33cf16c9 (attempt ids), 47dc8917 (assignment precedence), c96ecbfd (superseded history), ef3d08ff via merge 6ffb2c66 (age-days fix) | one commit | 27 kernel commits |
| author_principal | claude | claude | the kernel, operator "claude executor, session_014NGs3CS6XKQVhULWsHgqsi" |
| review_state | NOT_REVIEWED | NOT_REVIEWED | not code; evidence |
| ci_state | PASS — run 35791621164, https://github.com/crooksldn-pixel/clive/actions/runs/35791621164, 2026-09-22T22:18:08Z to 22:21:38Z, all five gates green (the three earlier commits' runs: 11060463 green, 33cf16c9 and c96ecbfd red on the nightly golden-scenario failure that packet 8 fixes; 47dc8917 cancelled as superseded) | no CI on that repository | none |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha 6ffb2c66… --suite full`, Python 3.12.3, gitleaks 8.30.1, clean tree, 22:18Z to 22:23Z: ruff pass; pytest_control_plane 44 passed; product_memory_structure pass (24 documents); pytest_offline_full 3085 passed, 8 skipped, 2 deselected; secret_scan no leaks; `eligible_for_acceptance_decision: true`, `accepted: false` (`acc-wt-cp-6ffb2c66….json`, recorded as this task's evidence in the store) | vitest 51 passed (7 new, on a fixture that is the real route's document); tsc clean; build clean; Playwright 19 of 19 (`tools/verify/verify_lifecycle.mjs`) | `engineering_kernel.py view` and the projection read it; see the write-up |

## Purpose

The owner's mandate: implement the smallest coherent repository-only producer layer so CLIVE authors and persists its engineering lifecycle rather than inferring it from processes; task created → assignment → fenced attempt and lease → dispatch identity → progress, heartbeat, evidence → immutable candidate SHA → independent review dispatch → exact-SHA verdict admitted or rejected → repair cycle → accepted → integration → COMPLETE only from evidence; fencing, reviewer independence, owner authority, immutable candidate identity and restart-safe state preserved; probes as reconciliation only; reuse the existing store and contracts.

## What was built (see `docs/product-memory/ENGINEERING_LIFECYCLE_PRODUCERS.md` for the contract)

**Reused unchanged:** `EngineeringTask`, `TaskRuntimeState` (compare-and-swap), `EngineeringResult` as the candidate, `JsonRecordStore`, `evaluate_obvious_continuation`, `evaluate_review_eligibility`, `ReviewEvidence`, `evaluate_review_acceptance`, `gate_review_result`, `build_active_state`.

**Added** (`app/orchestrator/lifecycle.py`, 1,516 lines; `scripts/engineering_kernel.py`, 328 lines): `Attempt` (lease, monotonic fencing token per task, dispatch identity as a `Party`), `AttemptEvent` (append-only journal, `seq` must be the next), `ReviewDispatch` (+ packet bytes and digest), `VerdictAdmission` (+ verdict bytes; outcomes accepted / rejected_by_verdict / refused with every reason), `Acceptance`, `Integration` (ancestry verified, remote head when asked); `LifecycleStore` extending the Phase 1 store; `Kernel` with the verbs task, assign, ack, heartbeat, evidence, candidate, dispatch, verdict, integrate, cancel, block, resume; `lifecycle_view` (the read-only projection of the records); git journaling of every write by "CLIVE kernel" naming the operator.

**Projection** (`scripts/agent_state_view.py`): roster `engineering_store` → records first (ASSIGNED, BUILDING while the lease is alive, STALE when it expired, IDLE while a candidate waits, REVIEWING for the principal with an open dispatch, COMPLETE for one window after integration with both records present), probes reconcile aloud (`reconciliation`, `status_source`), `tasks[]` and `engineering{}` in the document, `records_only` probe kind, `also_assigned`; `last_heartbeat` is only what the kernel journaled.

**Environment** (AGENT-ENVIRONMENT): `src/adapters/clive/lifecycle.ts` maps the records to projects (one per stream, evidence = every SHA, dispatch, verdict, acceptance, integration), tasks (current revisions) and activity (the journal minus heartbeats); ASSIGNED and COMPLETE statuses; the profile shows status source, attempt, candidate, also-holds and reconciliation.

## Diff scope

CLIVE `git diff --stat 84e12e77..6ffb2c66`: 14 files, 2,886 insertions, 31 deletions — `app/orchestrator/lifecycle.py` (+1516, new), `scripts/engineering_kernel.py` (+328, new), `scripts/agent_state_view.py` (+182/−?; records-first, reconciliation, tasks[], records_only, also_assigned), `tests/test_lifecycle_kernel.py` (+645, new, 30 tests), `tests/test_environment_route.py` (vocabulary), `config/review_principals.json` (new, the handoff branch's principals), `config/agent_roster.json` (comment), `docs/product-memory/ENGINEERING_LIFECYCLE_PRODUCERS.md` (new) and README index, `docs/AGENT_ENVIRONMENT_STATE_VIEW.md`; from the merged fix: `app/analytics/engine.py`, `app/analytics/summarise.py`, `tests/test_analytics.py`, `tests/test_fixture_wiring.py`.

AGENT-ENVIRONMENT `git diff --stat 119bb9b..c20f5397`: 14 files: lifecycle.ts (new, 200 lines), lifecycle.test.ts (new), fixtures/state-view.lifecycle.json (new, the real document), stateView.ts, types.ts, selectors.ts, components.ts, stations.ts, world.ts, projects.ts, workerProfile.ts, status.ts, verify_lifecycle.mjs (new), README.

## The real records (the acceptance demonstration)

On `clive/engineering-state`, written only by the kernel: task `judgment-ledger-corrections` in three revisions, r1 candidate 1ec236a → dispatched to gpt → J-01 admitted as REPAIR_REQUIRED (rejected_by_verdict); r2 candidate 2a08f456 → dispatched → J-02 admitted as REPAIR_REQUIRED; r3 candidate 1958b327 (publication verified against origin) → dispatched to gpt with packet 5 → REVIEWING now. Past-dated records are marked backfilled with their evidence (commits, CI run ids, packets, the owner-relayed verdict texts). Task `control-plane-producers`: assigned, acknowledged, heartbeats, candidate 6ffb2c66 with the acceptance-provenance evidence and publication verified, dispatched to gpt with this packet. The environment renders: assignment and BUILDING (the executor, by its lease), REVIEWING (the GPT principal, by the open dispatch), the repair cycle's three exact candidates and two admitted rejections on the board. **accepted and COMPLETE** are exercised by the kernel tests and will render from records when a real READY verdict is admitted and task 12 integrates it; nothing here can produce a verdict.

## Reviewer checklist

1. SHAs resolve; parents as stated; trees clean. `git log --format=%P -1 6ffb2c66` → `c96ecbfd… ef3d08ff…`.
2. In crooks-assistant: `python -m pytest tests/test_lifecycle_kernel.py tests/test_agent_state_view.py tests/test_environment_route.py tests/test_orchestrator_control_plane.py -q` → 108 passed. Read the 30 kernel tests as the attack list: stale token, expired lease, unbacked evidence, one candidate per attempt, author-as-reviewer, unregistered reviewer, moved branch, observed and current SHA drift, writable or dirty or inherited reviewer workspace, reviewer not at the candidate, wrong dispatched principal, duplicate final verdict, late verdict for a superseded attempt, integration without acceptance, wrong ancestry, wrong remote head, DONE without records is UNKNOWN, backfill without a reference, restart safety, the journal.
3. Confirm no existing gate was weakened: `git diff 84e12e77..6ffb2c66 -- crooks-assistant/app/orchestrator/routing.py crooks-assistant/app/orchestrator/review_acceptance.py crooks-assistant/app/orchestrator/review_result_gate.py crooks-assistant/app/orchestrator/policy.py crooks-assistant/app/orchestrator/store.py crooks-assistant/app/orchestrator/contracts.py` is empty.
4. Check out `clive/engineering-state`, declare its `engineering/` in a roster, run `scripts/agent_state_view.py --roster <it>` and `scripts/engineering_kernel.py --store <it>/engineering --repo <clive> view`; compare with the write-up.
5. Decide the judgement calls below.

## Known risks and judgement calls to challenge

1. **Declared reviewer facts.** A verdict's reviewer session and workspace (fresh, read-only, clean, at the candidate) are declared by whoever relays the verdict; the kernel records and evaluates them and cannot inspect GPT's environment. This is the same limit the handoff recorded; the difference is that it is now written into an immutable admission with the verdict bytes.
2. **Backfilled history.** r1 and r2 of the judgment task were recorded today from evidence, with approximate verdict times that say so. They went through the real gates, but they are reconstruction, and every record says `backfilled`.
3. **Self-recording.** The executor recorded its own assignment and heartbeats for `control-plane-producers`; the kernel is the author and the operator is named, but there is no second principal behind the write. Independence is enforced at dispatch and admission, not at assignment.
4. **Single writer.** The JSON store's compare-and-swap protects against a stale writer on one host, not two kernels on two hosts. Git journaling gives an audit trail, not a lock.
5. **Precedence rule.** A worker holding two live assignments is placed by the more active one (running > assigned > blocked/gated > evidence ready > reviewing > rejected > accepted); the others are listed. Challenge the order.
6. **COMPLETE window.** A worker reads COMPLETE for one stale window after integration, then returns to its probe. The task itself stays COMPLETE.
7. **Scope.** No scheduler, watcher, service or runtime; the store branch in this container is real for this session, and wiring the builder host to it is the owner's environment step.
8. **The merge of packet 8's fix** is in this candidate so its CI can be green in the 21:48–23:00 UTC window; it is reviewable on its own branch and touches only analytics rounding.

## After acceptance

Task 12 (integration of the J-02 candidate) and this package's own integration are recorded through the kernel (`verdict`, `integrate`), which is what makes accepted and COMPLETE render from records. Nothing deploys.
