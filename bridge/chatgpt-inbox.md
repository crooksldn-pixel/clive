# CHATGPT INBOX

## Fresh independent adversarial review — Orchestrator V1 freeze candidate after R-01/R-02/R-03 repair

This is a **read-only independent architecture/specification review**. It is not implementation and it is not a repair round.

Review exact candidate:
- repository: `crooksldn-pixel/clive`
- canonical base: `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- exact candidate SHA: `e944620fbcf3f7f7c914219762bfe844009e05f2`
- last reviewed candidate: `10c81e31f21f62f4115133232cc672c63f52d078`

The previous verdict is stale for this SHA. Do not carry it forward.

### Hard scope

Read-only everywhere except the normal bridge outbox. Do **not** edit, create, delete, commit, push, merge, switch/reset/clean/stash branches, install, restart, deploy, alter systemd/watcher/runtime, rewrite Git config, change account/global Claude settings, change MCP/connector grants, read new secrets, perform business writes, or execute any runtime remediation. Do not fix findings.

The live watcher/builder branch mismatch, stale Builder fetch refspec, and inherited business-MCP connector surface remain runtime-pending. Measure/report only as needed; do not remediate.

### Identity first

Before substantive review:
1. verify the candidate branch resolves exactly to `e944620fbcf3f7f7c914219762bfe844009e05f2`;
2. verify canonical base remains exactly `9e59860a945ec339c69af8709cd0721f0a795327`;
3. verify merge-base(candidate, base) equals that canonical base;
4. inspect the full diff `10c81e3..e944620`;
5. re-read the full freeze set at `e944620`, especially:
   - `ORCHESTRATOR_V1_FREEZE_CONTRACT.md`
   - `ORCHESTRATOR_V1_STATE_API.md`
   - `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md`
   - `ORCHESTRATOR_V1_TRACEABILITY.md`
   - `tests/test_orchestrator_freeze_spec.py`
   - `WATCHER_BUILDER_IDENTITY_REMEDIATION.md`
   - canonical `DECISIONS.md`, `CURRENT_TRUTH.md`, `ROADMAP.md`.

### Re-review the three repaired blockers

#### R-01 — integration launch path
Prove the repaired path is actually executable under the joint-oracle rule:
- `integration.begin` is allocation-only: CREATED -> INTEGRATING, atomically creating workspace reservation + INTEGRATION attempt + lease/fence, with no model/toolchain preflight and no process launch;
- preflight begins only after the lease/workspace exist;
- `integration.start` is the only command that admits STARTING -> RUNNING after measured preflight and owned process-group establishment;
- deterministic preflight failure reaches integration BLOCKED via `integration.block`, closing the attempt FAILED or QUARANTINED, with no unfenceable/unregistered window;
- cancellation while the integration is still CREATED before `integration.begin` is directly representable and does not invent a lease/process that does not exist;
- cancellation after allocation still fences the real lease/process group;
- ST-11, IN-15, IN-16 and IN-17 are sufficient and non-contradictory.

#### R-02 — per-revision attempt ceiling
Verify the three-attempt ceiling is authoritative rather than prose-only:
- every TASK `attempt.assign` path (PLANNED and REJECTED, plus §3A's TASK allocation rule) requires the per-revision ceiling not to be exhausted;
- persisted counters survive restart, DB restore and epoch change;
- when a non-rejection failure consumes attempt 3, the contract's single declared path is BLOCKED then `task.escalate` to ESCALATED;
- a fourth `attempt.assign` is forbidden by the transition guard;
- ST-14 and PR-10 actually cover this.

#### R-03 — delivery authority and journal semantics
Verify delivery is no longer forced through an execution-record fence it does not own:
- delivery record binds controller epoch and idempotency identity;
- delivery mutation authority is current controller epoch + idempotency key/request digest + the §4 two-phase persist/observe/persist protocol;
- stale epoch or conflicting request digest is refused;
- `DELIVERY` is a valid transition-event subject kind;
- a DELIVERY event may have NULL execution-record fencing token and still be fully representable;
- ID-07 and OB-01 correctly cover delivery authority and journal transitions;
- execution-record fencing in §7 remains scoped only to task/integration/review execution results.

### Regression search

Try to break the repair and look for new material defects, especially:
- any remaining §3/§3A contradiction;
- any integration state with a mandatory cancellation/cleanup action but no real execution record;
- attempt-ceiling paths that can bypass the guard by BLOCKED -> plan -> assign, rejection correction, revision reuse or restart;
- delivery events that remain impossible to encode or reconcile;
- malformed §18A coverage-index rows or dangling test IDs introduced by the repair;
- structural tests that false-green because they only check strings but do not prove the claimed edge;
- any self-adoption or DEC-046/DEC-047 sequencing change;
- any regression of previously closed N-01..N-04 or B-01..B-05.

If you run the mechanical spec tests, report exact commands/results and independently test failing-before behaviour against `10c81e3` where useful.

### Verdict

Return exactly one:

- `ENGINEERING CONTRACT READY — OWNER/RUNTIME GATES REMAIN`
- `CHANGES REQUIRED BEFORE OWNER DECISION`

If changes are required, list only material engineering blockers with exact location, unsafe/incorrect consequence, smallest bounded repair and exact acceptance/mechanical test required.

List OWNER-PENDING and RUNTIME-PENDING items separately and do not count them as engineering defects if the contract correctly fails closed.

Record the same-model/provider reviewer-independence limitation explicitly if applicable; independence must still come from a fresh session/principal, read-only workspace/channel and immutable SHA-bound subject.

Do not approve because the documents are detailed. Try to break them.