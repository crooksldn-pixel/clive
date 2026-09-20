# CHATGPT INBOX

## Fresh independent read-only adversarial review — Orchestrator V1 freeze candidate 5eb25f8

Review exact candidate:
- repository: `crooksldn-pixel/clive`
- canonical base: `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- exact candidate SHA: `5eb25f8fe00a3196cb27d7b2c92b2b5fbf4a5c78`
- superseded/rejected SHA: `31b0e07179877651da80065f5914575ee4d60d6c`
- repair outbox blob: `5dae2a784fc9986f38b1a63191463eb783ecb96a`

This is a fresh independent **read-only** review. The previous verdict is stale. Do not edit, commit, push, merge, switch/reset/clean/stash, create a worktree, change runtime/systemd/watcher state, touch secrets, account/global Claude settings, MCP/connectors, privileges, production, or business state.

First verify:
1. candidate branch resolves exactly to `5eb25f8fe00a3196cb27d7b2c92b2b5fbf4a5c78`;
2. canonical base resolves exactly to `9e59860a945ec339c69af8709cd0721f0a795327`;
3. merge-base(candidate, base) equals the canonical base;
4. `31b0e071..5eb25f8` is exactly one repair commit and inspect its full diff.

Re-review G-01/G-02/G-03 and try to break them:

### G-01 — execution-bearing subject reconciliation
- derive execution-bearing subject states from §3A.1 + §3B rather than trusting prose;
- confirm every subject state that can own a non-terminal attempt/review_dispatch is covered by §1A and freeze-contract §21;
- specifically verify TASK ASSIGNED + CREATED/STARTING attempt cannot strand after controller-epoch fencing;
- confirm reconciliation uses the already-legal block edge, no blind redispatch;
- ensure splitting §3A into §3A.1/§3A.2 leaves the §3/§3A joint oracle satisfiable.

### G-02 — execution-attempt ceiling accounting
- verify §3A.2 is total over the attempt disposition enum;
- confirm CANCELLED/FENCED attempts that never reached RUNNING do not consume the ceiling;
- confirm a model that did run cannot close CANCELLED/FENCED with the durable identity interpreted as “never ran”;
- deterministic preflight failure must still consume budget;
- restart/restore/epoch changes must neither reset nor decrement legitimate consumed attempts;
- test whether disposition relabelling can game the budget.

### G-03 — delivery crash/duplicate-effect prevention
- verify delivery attempt-count arming is durably committed before any external effect;
- verify `delivery.publish` cannot replay a PENDING record whose effect may already have started;
- restart/restore/epoch change must force initiated PENDING -> UNKNOWN before another external effect;
- `delivery.reconcile` against authoritative remote state must be the only exit from UNKNOWN;
- test whether an adapter can perform more than one external effect inside a single publish call and bypass the count gate;
- check interaction with delivery.block and controller.reconcile.

Also adversarially search for any new material defect in:
- task/attempt/integration/reviewer/delivery state legality;
- cancellation and restart races;
- stale-result admission and fencing;
- idempotency/external-effect ambiguity;
- attempt budget liveness/safety;
- journal completeness;
- §18A coverage and dangling acceptance IDs;
- structural-test parser correctness / false greens;
- regressions of N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03;
- self-adoption or DEC-046/DEC-047 sequencing drift.

Mechanical verification:
- run committed spec tests only if possible without violating read-only scope; otherwise recompute against blobs with `git show`;
- independently verify zero dangling test IDs, complete MUST-bearing §18A coverage, every non-terminal attempt state has a terminal cleanup/fencing path, delivery enum/§3C completeness, and no self-adoption.

Return exactly one:
- `ENGINEERING CONTRACT READY — OWNER/RUNTIME GATES REMAIN`
- `CHANGES REQUIRED BEFORE OWNER DECISION`

If changes are required, list only material engineering blockers with exact location, consequence, smallest bounded repair and exact acceptance/mechanical test. List OWNER-PENDING and RUNTIME-PENDING separately. Record reviewer-independence limitation if same model/provider is used.

Do not certify based on detail. Try to break it.