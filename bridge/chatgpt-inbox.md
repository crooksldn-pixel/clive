# CHATGPT INBOX

## Fresh independent read-only adversarial review — Orchestrator V1 freeze candidate 9fbe4a9

Review exact candidate:
- repository: `crooksldn-pixel/clive`
- canonical base: `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- exact candidate SHA: `9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f`
- superseded candidate: `5eb25f8fe00a3196cb27d7b2c92b2b5fbf4a5c78`
- repair outbox blob: `0605de0cb8fb0f0b64d09d18a2e67e17384b1feb`

This is a fresh independent **read-only** review. The previous verdict is stale for this SHA.

### Hard scope

Read-only everywhere except the normal bridge outbox. Do not edit, create, delete, commit, push, merge, switch/reset/clean/stash branches, create worktrees, change systemd/watcher/runtime, repair the stale fetch refspec, alter account/global Claude settings, change MCP/connector grants, read new secrets, widen privileges, touch production, perform business writes, spend externally, or adopt/resequence the freeze.

### Identity first

Before substantive review:
1. explicitly resolve candidate branch and canonical base using fresh remote truth;
2. candidate must equal exactly `9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f`;
3. canonical base must equal exactly `9e59860a945ec339c69af8709cd0721f0a795327`;
4. merge-base(candidate, base) must equal the canonical base;
5. verify `5eb25f8..9fbe4a9` is exactly one repair commit and inspect the full diff;
6. re-read the complete freeze set, including state API, freeze contract, acceptance matrix, traceability, mechanical test, watcher/builder remediation, and canonical DECISIONS/CURRENT_TRUTH/ROADMAP.

### Re-review H-01 — execution-record disposal on subject transitions

Try to break §3.1 and the new matrix coupling.

Verify:
- every §3 transition whose From can hold a non-terminal attempt or review_dispatch and whose To leaves the execution-bearing set carries exactly one valid disposal obligation;
- `[EXEC-FENCE]` really requires all owned non-terminal attempts and dispatches to terminate, process groups to stop per §6, and slots/leases/concurrency to release before the subject transition commits;
- `[EXEC-ATOMIC-CLOSE]` can only name a real terminal §3A/§3B edge and cannot become an escape hatch;
- `candidate.accept`, `candidate.reject`, `integration.verify`, `integration.reject`, `integration.block`, `task.block`, `task.escalate`, `task.fail`, cancellation/revise/supersede paths all agree across §3/§3A/§3B;
- no live dispatch/attempt can survive under a subject state outside the mechanically derived execution-bearing set;
- rejecting one reviewer while sibling reviewers remain live fences the siblings and immediately frees their review slots/concurrency;
- late results after such fencing are rejected by dispatch/attempt fencing rather than by candidate-SHA mutation alone;
- the mechanical derivation is driven from real transition rows and cannot pass vacuously if the tokens disappear or a From-cell is phrased differently.

Attack parser edge cases in the mechanical test: multi-state From cells, integration-prefixed states, “any nonterminal active”, REVIEWING rows, token placement, atomic-close references, and any row the parser might accidentally skip.

### Re-review H-02 — pre-RUNNING cleanup handle vs execution-budget discriminator

Verify the schema-free split is deterministic:

- `lease.owned_process_group_handle` is the only durable cleanup handle used before RUNNING and is committed before any owned preflight/model process group is created;
- `attempt.running_process_group_identity` is written exactly once in the STARTING -> RUNNING commit and is the only §3A.2 execution-ceiling discriminator;
- the two fields are distinct in role and no section reads the wrong one;
- a crash after handle commit but before process fork is safe: NULL/absent actual group is provably clean rather than QUARANTINED;
- a crash after fork during STARTING can identify and stop the group, then close FENCED/CANCELLED without consuming execution budget when cleanup is proven;
- a stale handle cannot cause the controller to kill an unrelated/reused process group; verify identity/reuse defence is explicit enough;
- QUARANTINED is reached only when a named owned group genuinely cannot be proven stopped, not because identity was never durably recorded;
- deterministic preflight failure remains FAILED/QUARANTINED and budget-consuming;
- R-02's three-execution-attempt ceiling remains intact and cannot be gamed by relabelling or clearing the discriminator.

### Regression and broader adversarial search

Try to find any new material engineering defect in:
- subject/attempt/reviewer/integration joint state legality;
- controller restart/epoch fencing;
- stale-result admission;
- slot/concurrency release;
- delivery §3C, idempotency, UNKNOWN reconciliation and duplicate-effect prevention;
- attempt-ceiling liveness/safety;
- journal completeness;
- structural-test false greens;
- dangling acceptance IDs;
- §18A MUST-coverage completeness;
- every non-terminal attempt state having terminal cleanup/fencing;
- delivery enum/state-machine completeness;
- N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03, G-01..G-03 regressions;
- self-adoption or DEC-046/DEC-047 sequencing drift.

If possible within read-only scope, run/recompute the committed spec test against exact blobs. Report exact method/results and distinguish actual pytest execution from equivalent blob-based recomputation.

### Owner/runtime separation

These are not engineering defects if the contract correctly fails closed:
- exact freeze adoption = OWNER-PENDING;
- any DEC-046 sequencing amendment = OWNER-PENDING;
- live watcher/builder branch mismatch = RUNTIME-PENDING;
- stale Builder fetch refspec = RUNTIME-PENDING;
- inherited business MCP connector surface = RUNTIME-PENDING.

### Verdict

Return exactly one:

- `ENGINEERING CONTRACT READY — OWNER/RUNTIME GATES REMAIN`
- `CHANGES REQUIRED BEFORE OWNER DECISION`

If changes are required, list only material engineering blockers with exact location, consequence, smallest bounded repair, and exact acceptance/mechanical test.

Record the reviewer-independence limitation if the same model/provider is used. Do not self-certify because the documents are detailed. Try to break the contract.