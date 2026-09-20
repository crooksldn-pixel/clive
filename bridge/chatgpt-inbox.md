# CHATGPT INBOX

## Fresh independent adversarial review — Orchestrator V1 freeze candidate at 10c81e3

This is a **read-only independent architecture/specification review**. It is not implementation and it is not a repair round.

Review exact candidate:
- repository: `crooksldn-pixel/clive`
- canonical base: `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- exact candidate SHA: `10c81e31f21f62f4115133232cc672c63f52d078`
- exact parent repaired from: `2bf240c33bfbf0e66257b82a43013cfb3f5af958`

The previous verdicts are stale for this SHA. Do not carry them forward.

### Hard scope

Read-only everywhere except the normal bridge outbox. Do **not** edit, create, delete, commit, push, merge, switch/reset/clean/stash branches, install, restart, deploy, alter systemd/watcher/runtime, rewrite Git config, change account/global Claude settings, change MCP/connector grants, read new secrets, perform business writes, or execute any runtime remediation. Do not fix findings.

The live watcher/builder branch mismatch, stale Builder fetch refspec, and inherited business-MCP connector surface remain runtime-pending. Measure/report them only if needed; do not remediate them.

### Identity first

Before substantive review:
1. explicitly fetch/read the candidate and canonical base refs;
2. verify branch tip equals exactly `10c81e31f21f62f4115133232cc672c63f52d078`;
3. verify merge-base(candidate, base) equals exactly `9e59860a945ec339c69af8709cd0721f0a795327`;
4. verify parent of candidate is exactly `2bf240c33bfbf0e66257b82a43013cfb3f5af958`;
5. inspect the exact diff `2bf240c..10c81e3` and the whole freeze set at `10c81e3`.

### Required source set

Read in full at the exact candidate/base identities:
- `ORCHESTRATOR_V1_FREEZE_CONTRACT.md`
- `ORCHESTRATOR_V1_STATE_API.md`
- `ORCHESTRATOR_V1_TRACEABILITY.md`
- `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md`
- `WATCHER_BUILDER_IDENTITY_REMEDIATION.md`
- `tests/test_orchestrator_freeze_spec.py`
- modified `CURRENT_TRUTH.md`, `ROADMAP.md`, `ENGINEERING_ORCHESTRATOR_V1.md`
- canonical `DECISIONS.md`, `DEV_TEAM_V1_PILOT.md`, `ENGINEERING_STACK_REUSE_PLAN.md`, `SELF_IMPROVEMENT.md`
- immediately preceding Claude outbox for the B-01..B-05 repair evidence.

### Re-review the repaired load-bearing areas

Try to prove the contract is still not ready.

1. **TASK/INTEGRATION attempt+lease generalisation**
   - verify the stated TASK projection is semantically identical to the previous task attempt/lease contract;
   - check every ST-*, LS-*, WS-* and CXN-* assumption still holds;
   - verify the §3/§3A joint-oracle rule remains coherent with integration rows and no task/integration state mutation has contradictory guards;
   - verify integration attempt cancellation, quarantine and restart reconciliation are actually representable.

2. **Reviewer dispatch/fencing**
   - verify required-review-slot uniqueness really fences stale reviewers even if candidate SHA is unchanged;
   - test ordering races conceptually: expiry vs verdict, cancel vs verdict, replacement dispatch while old external reviewer is still running, two replacements, controller restart, stale epoch/fence;
   - verify a stale/foreign/unknown dispatch cannot create an authoritative Review or ACCEPT path;
   - verify externally hosted reviewers that cannot be process-killed are still safely fenced by admission identity.

3. **Failure taxonomy and retry budget**
   - confirm every reason code maps exactly once to RETRYABLE/BLOCKED/REJECTED_FAILED/ESCALATED;
   - unknown/unmapped must fail closed to BLOCKED;
   - evaluate whether zero automatic relaunches + max 3 attempts/revision is internally coherent with BLOCKED -> task.plan -> attempt.assign, correction budget, restart persistence, and no exactly-once claim;
   - flag only if this creates an actual contradiction or unsafe ambiguity, not because a different retry preference is possible.

4. **Freeze meta-gate**
   - independently inspect whether every referenced test ID really resolves to an existing acceptance row;
   - attempt to find MUST-bearing requirements that evade the §18A coverage index;
   - verify the mechanical spec test cannot falsely green due to parsing/keying assumptions;
   - ensure the freeze set does not self-adopt or silently alter DEC-046/DEC-047.

5. **Integration findings**
   - verify finding subject kind/ID/SHA and policy-computed blocking flag are enough to make integration findings authoritative/queryable;
   - correction lineage must not drop unresolved blockers;
   - `integration.verify` must fail on unresolved blocking findings for its own subject.

6. **Runtime/authority separation**
   - owner adoption of exact freeze SHA and any sequencing amendment remain OWNER-PENDING;
   - watcher/builder identity mismatch, stale fetch refspec and inherited business connector surface remain RUNTIME-PENDING;
   - no document may treat those conditions as closed just because the spec describes a remediation.

7. **New-defect search**
   Adversarially inspect for anything newly introduced by the B-01..B-05 repair, especially:
   - reviewer/integrator process ownership vs fencing;
   - task/integration/reviewer crash recovery;
   - idempotency of review dispatch replacement and integration restart;
   - cancellation races and stale result admission;
   - transition-event schema after generic subject changes;
   - DB uniqueness constraints that cannot be represented in SQLite as described;
   - host-loss/backup limitations;
   - observability and resource-ceiling enforcement;
   - required-condition retirement semantics;
   - any dangling traceability row or acceptance ID;
   - any normative conflict between freeze contract, state API and acceptance matrix.

### Evidence expectations

Do not rely on the repair outbox's prose alone.

Read the exact diff and run only read-only/documentation/mechanical validation necessary to test the contract. If you run repository tests, report exact commands/results and distinguish newly added structural checks from the broader existing test suite.

Treat candidate mutation as invalidating this review.

### Verdict

Return exactly one:

- `ENGINEERING CONTRACT READY — OWNER/RUNTIME GATES REMAIN`
- `CHANGES REQUIRED BEFORE OWNER DECISION`

If changes are required, list only material engineering blockers with:
- ID/severity;
- exact file/section;
- unsafe/incorrect consequence;
- smallest bounded repair;
- exact acceptance/mechanical test required.

List OWNER-PENDING and RUNTIME-PENDING items separately and do not count them as engineering defects if the contract correctly fails closed.

Record the reviewer-independence limitation explicitly if this review uses the same model family/provider as the repair worker; independence must still come from a fresh session/principal, read-only workspace/channel and immutable SHA-bound subject.

Do not approve because the documents are detailed. Try to break the contract.
