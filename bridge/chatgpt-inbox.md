# CHATGPT INBOX

## Fresh independent adversarial review — Orchestrator V1 freeze candidate after F-01/F-02/F-03 repair

This is a **read-only independent architecture/specification review**. It is not implementation and it is not a repair round.

Review exact candidate:
- repository: `crooksldn-pixel/clive`
- canonical base: `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- exact candidate SHA: `31b0e07179877651da80065f5914575ee4d60d6c`
- last reviewed candidate: `e944620fbcf3f7f7c914219762bfe844009e05f2`

The previous verdict is stale for this SHA. Do not carry it forward.

### Hard scope

Read-only everywhere except the normal bridge outbox. Do **not** edit, create, delete, commit, push, merge, switch/reset/clean/stash branches, install, restart, deploy, alter systemd/watcher/runtime, rewrite Git config, change account/global Claude settings, change MCP/connector grants, read new secrets, perform business writes, or execute any runtime remediation. Do not fix findings.

The live watcher/builder branch mismatch, stale Builder fetch refspec, and inherited business-MCP connector surface remain runtime-pending. Measure/report only if needed; do not remediate.

### Identity first

Before substantive review:
1. explicitly fetch/read the candidate and canonical base refs;
2. verify candidate branch tip equals exactly `31b0e07179877651da80065f5914575ee4d60d6c`;
3. verify canonical base equals exactly `9e59860a945ec339c69af8709cd0721f0a795327`;
4. verify merge-base(candidate, base) equals the canonical base;
5. inspect the exact repair diff `e944620..31b0e071`;
6. re-read the whole freeze set at `31b0e071`, including:
   - `ORCHESTRATOR_V1_FREEZE_CONTRACT.md`
   - `ORCHESTRATOR_V1_STATE_API.md`
   - `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md`
   - `ORCHESTRATOR_V1_TRACEABILITY.md`
   - `tests/test_orchestrator_freeze_spec.py`
   - `WATCHER_BUILDER_IDENTITY_REMEDIATION.md`
   - canonical `DECISIONS.md`, `CURRENT_TRUTH.md`, `ROADMAP.md`.

### Re-review the three repaired blockers

#### F-01 — integration launch / §3 vs §3A ownership
Verify the exact legal path is coherent and executable:
- `integration.begin` owns only subject CREATED -> INTEGRATING plus attempt/workspace/lease allocation;
- §3 no longer claims an attempt-state edge for `integration.start`;
- §3A owns `CREATED -> STARTING` and `STARTING -> RUNNING` for `integration.start`;
- preflight begins only after the integration attempt, lease and workspace reservation exist;
- successful preflight establishes the owned process group before RUNNING;
- deterministic preflight failure closes FAILED/QUARANTINED and blocks the integration through the listed edge;
- ST-11 and IN-15 are structurally true, not merely prose assertions.

#### F-03 — cancellation/fencing before RUNNING
Verify every non-terminal attempt state has a safe terminal fencing/cleanup path:
- CREATED attempt can close CANCELLED/FENCED without inventing a process;
- STARTING attempt fences immediately and only closes non-quarantined after any preflight process group is proven empty;
- unproven preflight cleanup becomes QUARANTINED and subject BLOCKED;
- controller-epoch change can fence CREATED/STARTING attempts;
- TASK and INTEGRATION projections are both covered;
- IN-18 and the structural mechanical test really detect a missing terminal edge.

#### F-02 — delivery state machine
Verify delivery is now a complete authoritative state machine:
- §3 closure is scoped only to task/integration subject state;
- §3C exists and governs delivery states `PENDING|UNKNOWN|PUBLISHED|FAILED|BLOCKED`;
- `delivery.publish`, `delivery.reconcile` and `delivery.block` in §2 all have normative §3C edges;
- every declared delivery state is reachable as a To-state;
- ambiguous external success reaches UNKNOWN and cannot be blindly replayed;
- reconciliation can resolve UNKNOWN using authoritative remote truth;
- PUBLISHED/BLOCKED terminal semantics are coherent;
- every §3C transition produces a DELIVERY journal event;
- DELIVERY events are representable with NULL execution-record fencing token and current controller epoch/idempotency identity;
- DL-01..DL-05, ID-07 and OB-01 accurately cover the model.

### Regression search

Try to break the new candidate beyond those three findings. In particular inspect:

- task/attempt/integration joint-oracle contradictions;
- cancellation races in CREATED/STARTING/RUNNING/CANDIDATE_READY;
- restart reconciliation across allocated-but-not-started attempts;
- delivery UNKNOWN/PUBLISHED/FAILED/BLOCKED recovery and idempotency;
- whether a delivery command/state is still unrepresented;
- whether any task/integration/review/delivery record has an impossible or unjournalled state;
- attempt-ceiling bypasses after BLOCKED/ESCALATED/rejection/restart/restore;
- whether the new durable attempt-count derivation actually satisfies persistence;
- reviewer dispatch fencing and stale verdict admission;
- malformed §18A rows, dangling test IDs, or a MUST-bearing section with no disposition;
- the structural-test helper/parser itself, including regex/section parsing and whether the new tests can false-green;
- any regression of N-01..N-04, B-01..B-05, R-01..R-03;
- any self-adoption or DEC-046/DEC-047 sequencing change.

### Mechanical verification

Run the candidate's spec test if this can be done without violating the read-only scope:
`tests/test_orchestrator_freeze_spec.py`.

If materialising the candidate tree would violate the scope, use committed blobs through `git show` and an ephemeral read-only script, as in the previous review. Report the exact command/method and distinguish pytest execution from equivalent structural recomputation.

Also independently check:
- every test ID referenced by the freeze set resolves to a real matrix row;
- every MUST-bearing numbered section is covered by §18A;
- the delivery state enum and §3C edges are mutually complete;
- every non-terminal attempt state has at least one terminal cleanup/fencing edge.

### Owner/runtime handling

Do not count these as engineering defects if the contract correctly fails closed:
- exact freeze adoption / any DEC-046 sequencing amendment = **OWNER-PENDING**;
- live watcher/builder branch mismatch = **RUNTIME-PENDING**;
- stale Builder fetch refspec = **RUNTIME-PENDING**;
- inherited business MCP connector surface = **RUNTIME-PENDING**.

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

List OWNER-PENDING and RUNTIME-PENDING items separately. Record the same-model/provider reviewer-independence limitation explicitly if applicable.

Do not approve because the documents are detailed. Try to break the contract.
