# CHATGPT INBOX

## Fresh independent read-only adversarial review — Orchestrator V1 freeze candidate 2f1acc0

Review exact candidate:
- repository: `crooksldn-pixel/clive`
- canonical base: `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- exact candidate SHA: `2f1acc0b7edd233735e419d92cfbade914b0042f`
- rejected/superseded SHA: `9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f`
- repair outbox blob consumed: `d6af4db6f83cf2e1a30b96d4cce987b02f2f8eb2`

This is a fresh independent **read-only** adversarial review. The prior verdict is stale for this changed SHA. Do not repair anything in this round.

### Hard scope
Read-only everywhere except the normal bridge outbox. Do not edit/commit/push/merge/switch/reset/clean/stash, create worktrees, change watcher/systemd/builder runtime, repair the stale fetch refspec, touch secrets or credentials, alter account/global Claude settings, change MCP/connectors, widen privileges, touch production/business state, spend externally, adopt the freeze, amend DEC-046/DEC-047, or implement Orchestrator code.

### Identity first
Before substantive review, resolve fresh remote truth explicitly and verify:
1. candidate branch == exactly `2f1acc0b7edd233735e419d92cfbade914b0042f`;
2. canonical base == exactly `9e59860a945ec339c69af8709cd0721f0a795327`;
3. merge-base(candidate, canonical) == canonical;
4. `9fbe4a9..2f1acc0` is exactly one repair commit;
5. inspect that exact repair diff and then re-read the complete freeze set plus canonical DECISIONS/CURRENT_TRUTH/ROADMAP. Never trust stale tracking refs.

### Attack H-03 — one owned group/write-once handle
Try to falsify the repair, especially crash/restart and stale-identity cases.
- An attempt must own exactly one controller-created process group/cgroup for its full lifetime.
- `lease.owned_process_group_handle` must be committed before that group exists, be write-once while live, and never be replaced on STARTING -> RUNNING.
- Preflight and model execution must inhabit that same group; a surviving preflight descendant must remain discoverable after RUNNING.
- `attempt.running_process_group_identity` remains accounting-only and must never become cleanup authority.
- Cancellation/restart emptiness must cover the entire group before workspace/slot release.
- A stale/recycled handle must fail closed: ownership/identity is reverified before signalling, and an unrelated recycled OS process must never be killed.
- Check whether the controller-allocated/non-recycled identity wording is implementable and deterministic across supported platforms without introducing a hidden second authority.
- Verify ST-16 actually proves the surviving-preflight-child case and the structural tests fail the rejected SHA for the defect rather than merely for new prose.

### Attack H-04 — kernel-owned reviewer write-ahead identity
- External vs kernel-owned must derive from durable reviewer principal/session ownership kind, not NULL process identity.
- Ownership kind must be durable before any reviewer process exists and immutable for the dispatch.
- For KERNEL_OWNED, the handle must be committed before reviewer group creation; NULL must positively mean no group was created, never “external”.
- §6 must branch on ownership kind first, reverify handle ownership, prove group empty, and release neither required-review slot nor reviewer-concurrency unit while an orphan may exist.
- Crash before fork, after fork, during candidate.reject/integration.reject, controller epoch change and restart reconciliation must all fail closed.
- EXTERNAL must retain fencing-only semantics with limitation recorded, without accidentally consuming kernel-owned process cleanup requirements.
- Verify ST-17 covers both kernel-owned crash and external negative arms and that structural tests bind to the actual record/§6 semantics.

### Broader adversarial regression search
Try to find any new material engineering blocker in:
- §3/§3A/§3B joint state legality and §3.1 execution-record disposal;
- restart/epoch fencing and stale-result admission;
- attempt/reviewer slot and concurrency release;
- attempt budget and R-02 ceiling accounting;
- delivery §3C arming/idempotency/UNKNOWN reconciliation/duplicate-effect prevention;
- journal completeness and impossible/unreachable states;
- structural-test parser false greens and mutation resistance;
- zero dangling acceptance IDs and complete §18A MUST coverage;
- every non-terminal attempt state having terminal cleanup/fencing;
- delivery enum/§3C completeness;
- regressions N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03, G-01..G-03, H-01/H-02;
- self-adoption or DEC-046/DEC-047 sequencing drift.

Run the committed spec test if possible without violating read-only scope; otherwise recompute from exact blobs. Distinguish actual pytest from equivalent recomputation. Mutation-test important structural gates where possible using ephemeral scratch only.

### Owner/runtime separation
These remain gates, not engineering defects if the contract fails closed:
- exact freeze adoption: OWNER-PENDING;
- any DEC-046 sequencing amendment: OWNER-PENDING;
- live watcher/builder branch mismatch: RUNTIME-PENDING;
- stale Builder fetch refspec: RUNTIME-PENDING;
- inherited business MCP connector surface: RUNTIME-PENDING.

### Verdict
Return exactly one:
- `ENGINEERING CONTRACT READY — OWNER/RUNTIME GATES REMAIN`
- `CHANGES REQUIRED BEFORE OWNER DECISION`

If changes are required, list only material engineering blockers with exact location, consequence, smallest bounded repair and exact acceptance/mechanical test. Separate OWNER-PENDING and RUNTIME-PENDING from engineering findings. Record reviewer-independence limitations if the same model/provider is used.

Do not self-certify because the repair is detailed. Try to break it.