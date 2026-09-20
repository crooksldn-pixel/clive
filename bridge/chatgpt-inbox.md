# CHATGPT INBOX

## Bounded repair — Orchestrator V1 freeze H-01 / H-02

This is exactly one bounded repository-only repair round on the existing freeze-candidate branch. It is not production/runtime remediation and it is not owner adoption.

### Exact identities
- repository: `crooksldn-pixel/clive`
- canonical base: `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- rejected candidate: `5eb25f8fe00a3196cb27d7b2c92b2b5fbf4a5c78`
- independent review outbox processed: timestamp 2026-09-20 14:15 UTC, inbox blob `0fe99fdf734a845734aaaeee829af504034b75f7`

Before editing, explicitly fetch/read the candidate branch and canonical base. Abort and report BLOCKED if the candidate branch no longer resolves exactly to `5eb25f8fe00a3196cb27d7b2c92b2b5fbf4a5c78`, merge-base is not the canonical base, or the workspace contains unrelated owner work. Never trust stale local tracking refs. Do not reset/clean/stash/discard anything.

### Hard scope
Allowed: repository-only edits on the same freeze-candidate branch to state API/freeze contract/acceptance matrix/traceability/mechanical spec tests needed to repair H-01/H-02, plus test execution and repository-local evidence.
Forbidden: production deployment/promotion; systemd/watcher/builder-runtime changes; secrets/credential reads; `/root/.claude` or account/global Claude changes; MCP/connector changes; privilege expansion; CROOKS/CLIVE business writes; public exposure; destructive reset/clean/stash; external spend; production merge; freeze adoption; DEC-046/DEC-047 sequencing changes; Orchestrator implementation.
Do not repair the live watcher/builder mismatch or stale fetch refspec in runtime; those remain runtime-pending.

### H-01 — subject transitions can strand live execution records
Repair the internal contradiction identified by the independent review.
Required outcome:
- every §3 subject transition leaving an execution-bearing state MUST terminally fence/cancel every non-terminal attempt and review_dispatch owned by that subject before the subject transition commits, unless the transition atomically closes that exact record through the paired §3A/§3B edge;
- explicitly cover `candidate.reject`, `integration.reject`, `integration.block`, `task.escalate`, `task.fail`; make `task.block` fencing unconditional;
- add matching triggers/semantics to §3A and §3B so matrices agree;
- no DISPATCHED review or non-terminal attempt may remain under a subject state outside the mechanically derived execution-bearing set;
- owned process groups stop per §6 before subject transition commit; freed review slot/concurrency becomes immediately reusable.
Acceptance: add ST-17 covering REVIEWING with >=2 live dispatches followed by reject/block/escalate and BUILDING followed by fail/escalate, proving all non-terminal execution records terminal and process groups stopped before subject transition; no stale slot/concurrency occupation.
Mechanical test: derive from actual §3 transition rows, not just restatement prose. For every §3 row whose From includes an execution-bearing state and whose To is outside it, assert the row requires corresponding execution-record termination/fencing (or atomic paired close). Preserve set-equality checks against §1A and FC §21, but do not allow two prose restatements to false-green each other.

### H-02 — pre-RUNNING process-group identity / attempt-budget ambiguity
Repair the STARTING crash window deterministically.
Required outcome:
- specify a durable handle for any owned preflight process group before RUNNING;
- separately specify the durable authoritative fact used to decide whether an attempt ever reached RUNNING for §3A.2 ceiling accounting; do not overload one field ambiguously;
- §1A, §3A, §3A.2 and §6 must agree exactly on when each fact is populated and how restart cleanup uses it;
- controller crash during STARTING with a live preflight group must identify and stop that group per §6, then close FENCED/CANCELLED without consuming execution budget when cleanup is proven;
- QUARANTINED is permitted only when cleanup genuinely cannot be proven, not merely because no durable identity was recorded;
- deterministic preflight failure remains budget-consuming and R-02 remains intact.
Prefer the smallest schema-free repair if an existing durable lease field and existing committed RUNNING fact can provide distinct authoritative roles; otherwise make the minimum explicit schema change required by the contract.
Acceptance: extend ST-16 with crash-during-STARTING and live preflight process-group arm; prove durable identification, cleanup, FENCED closure, unchanged ceiling; assert QUARANTINED only for genuinely unprovable cleanup.
Mechanical test: assert the ceiling discriminator and pre-RUNNING process-group cleanup handle are explicitly named, distinct in role, their population timing is normative, and §1A/§3A/§3A.2/§6 agree.

### Regression/evidence
Preserve N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03, G-01..G-03. Update traceability for H-01/H-02. Run committed mechanical freeze spec test and relevant non-live/static checks. Independently verify zero dangling acceptance IDs, complete §18A MUST coverage, terminal cleanup paths for every non-terminal attempt state, delivery enum/§3C completeness, no self-adoption, no DEC-046/DEC-047 sequencing change.

Before publishing require exact base/rejected/new SHAs, exact changed-file set/diff summary, tests/results, clean worktree, candidate secret scan with no values printed, and exact remote branch readback equal to new SHA. Publish only to the freeze-candidate branch. Do not merge/adopt/deploy.

### Handoff
After repair, report exact new SHA and evidence in outbox. Do not self-certify. State previous verdict is stale for the changed SHA and a fresh independent read-only adversarial review is required. Do not dispatch more than this one repair task.