# CHATGPT INBOX

## Fresh independent adversarial re-review — Orchestrator V1 freeze candidate after N-01/N-02/N-03 repair

This is a **read-only independent architecture/specification re-review**. It is not implementation.

Review exact candidate:
- repository: `crooksldn-pixel/clive`
- base: `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- candidate SHA: `3c5a06271ac6cda3f6a9942632ff1390e2daa16b`

The prior review of `a4ec77ff...` is stale. Do not carry its verdict forward.

### Hard scope

Read-only everywhere except the normal bridge outbox. Do **not** edit, create, delete, commit, push, merge, switch/reset/clean/stash branches, install, restart, deploy or alter repository/runtime/systemd/account/global Claude/MCP/connector/credential/permission/production state. Do not execute the watcher/builder runtime remediation. Do not fix findings.

### Required review

Verify exact candidate SHA, base, merge-base and diff first.

Read in full:
- `ORCHESTRATOR_V1_FREEZE_CONTRACT.md`
- `ORCHESTRATOR_V1_STATE_API.md`
- `ORCHESTRATOR_V1_TRACEABILITY.md`
- `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md`
- `WATCHER_BUILDER_IDENTITY_REMEDIATION.md`
- modified `CURRENT_TRUTH.md`, `ROADMAP.md`, `ENGINEERING_ORCHESTRATOR_V1.md`
- canonical `DECISIONS.md`, `DEV_TEAM_V1_PILOT.md`, `ENGINEERING_STACK_REUSE_PLAN.md`, `SELF_IMPROVEMENT.md`
- the previous outbox review that raised N-01, N-02 and N-03.

Explicitly re-check the three repaired findings:

1. **N-01 watcher/builder remediation topology**
   - remote `claude/bridge-builder` is absent;
   - plan now treats publication as a guarded create, not a fake fast-forward;
   - accepted Builder ref fetch uses an actually existing ref and does not depend on the broken configured fetch path;
   - create is compare-and-swap guarded against a raced/unexpected ref;
   - local semantic ref reconciliation is expected-old guarded and does not require reset/clean/stash;
   - scratch rehearsal BR-01..BR-04 is sufficient and technically executable;
   - Phase 1/write-capable execution remains blocked until live closure.

2. **N-02 task/attempt state-table overlap**
   - `REJECTED -> attempt.assign` correction is legal in both task and attempt tables;
   - deterministic preflight failure from ASSIGNED/STARTING reaches task BLOCKED through a listed edge and closes/quarantines the attempt coherently;
   - the joint-oracle rule makes overlap fail closed rather than ambiguous;
   - ST-11..ST-13 make the combined state machine testable.

3. **N-03 canonical truth drift**
   - CURRENT_TRUTH now distinguishes "addressed by freeze candidate" from "canonically closed only after owner adoption";
   - no document self-adopts the freeze or re-sequences DEC-046;
   - the freeze gate's mechanical gap/finding consistency check would catch a conflicting status.

Then adversarially search again for **new material defects** introduced by these repairs or still present anywhere in the V1 freeze set. Pay special attention to:
- task/attempt/integration lifecycle contradictions;
- idempotency/replay of every retryable command;
- authoritative principal boundaries;
- candidate/evidence/review identity and invalidation;
- branch/ref publication and ambiguous external effects;
- DB backup/restore/schema/host-loss assumptions;
- capability/network/MCP/credential isolation;
- cancellation/orphan-process races;
- risk classification/reviewer independence;
- drain/upgrade/cutover;
- any MUST that lacks a deterministic acceptance/fault test or an explicitly static invariant;
- any Symphony/ECC/skills finding silently dropped;
- any owner/runtime gate accidentally converted into implementation authority.

### Owner/runtime handling

Do not treat these as engineering defects if the contract correctly fails closed:
- owner adoption of the exact freeze SHA and any DEC-046 sequencing amendment = **OWNER-PENDING**;
- live watcher/builder branch mismatch = **RUNTIME-PENDING**;
- inherited business MCP connector surface for unattended engineering workers = **RUNTIME-PENDING**.

### Verdict

Return exactly one:
- `ENGINEERING CONTRACT READY — OWNER/RUNTIME GATES REMAIN`
- `CHANGES REQUIRED BEFORE OWNER DECISION`

If changes are required, list only material engineering blockers with exact file/section, unsafe consequence, smallest repair and exact acceptance test. List owner/runtime pending gates separately. Do not approve because the documents are detailed; try to break them.
