# CHATGPT INBOX

## Bounded repair — Orchestrator V1 freeze H-03 / H-04

Perform exactly one bounded repository-only repair round on the existing freeze-candidate branch. This is not owner adoption, runtime remediation, production work, or Orchestrator implementation.

### Exact identities
- repository: `crooksldn-pixel/clive`
- canonical base: `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- rejected candidate: `9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f`
- independent-review outbox blob consumed: `79d8f2986c1be25224a5400c459b1a17c2560212`

Before editing, resolve both branch heads from fresh remote truth using explicit full refs / ls-remote as needed. Abort if candidate is not exactly the rejected SHA, canonical base is not exactly the stated SHA, merge-base differs from canonical, or unrelated owner work is present. Never trust the known-stale tracking ref. Do not reset/clean/stash/discard owner work.

### Hard scope
Allowed: repository-only edits on the same freeze-candidate branch to the freeze contract/state API/acceptance matrix/traceability/mechanical spec tests necessary to repair H-03/H-04, plus repository-local/static test evidence.
Forbidden: production deployment/promotion; systemd/watcher/builder-runtime changes; repair of the stale fetch refspec; secrets/credential reads; account/global Claude changes; MCP/connector changes; privilege expansion; CROOKS/CLIVE business writes; public exposure; destructive cleanup; external spend; production merge; freeze adoption; DEC-046/DEC-047 sequencing changes; Orchestrator implementation.

### H-03 — eliminate process-group handle overwrite

The independent review verified that the current text can overwrite the preflight cleanup handle at STARTING -> RUNNING before proving the preflight group empty, contradicting the no-untracked-owned-group invariant.

Adopt the smaller **single per-attempt owned process group, write-once handle** design, which already matches freeze-contract §11:
- an attempt owns exactly one controller-created process group/cgroup for its full lifetime;
- `lease.owned_process_group_handle` is committed before that group is created on CREATED -> STARTING and is never replaced while the attempt is live;
- preflight and model execution both run inside that same owned group;
- STARTING -> RUNNING MUST NOT update/replace the cleanup handle;
- `attempt.running_process_group_identity` remains the distinct write-once ceiling discriminator committed only with RUNNING and MUST NOT become the cleanup handle;
- cancellation/restart emptiness checks apply to the entire per-attempt group, so surviving preflight descendants cannot become invisible.

Also close the review's adjacent identity-reuse ambiguity without widening scope: specify that the cleanup handle is a controller-allocated, attempt-bound identity that cannot be confused with a recycled unrelated OS process group (for example an attempt-specific cgroup path/identity), and §6 must verify ownership/identity before signalling. Do not prescribe a platform-specific implementation beyond what is necessary to make stale-handle reuse fail closed.

Acceptance:
- extend ST-16 with a preflight child that survives into RUNNING; prove cancellation/restart finds it through the same write-once handle and workspace reuse remains forbidden until the whole group is empty;
- preserve crash-after-handle-before-fork and crash-during-STARTING cases;
- structural test must fail the rejected tree because it contains the handle-update/two-group handoff wording, and must assert FC §11 and SA §3A.3 agree on one group/write-once lifetime ownership;
- preserve R-02 attempt-budget semantics.

### H-04 — reviewer process identity must be write-ahead too

The independent review verified that `review_dispatch.process-group/cgroup identity` can currently be NULL for an external reviewer, but there is no normative write-ahead rule for a kernel-owned reviewer. A crash after reviewer fork but before identity persistence can therefore make §6 treat a live kernel-owned process as external/unowned and release its slot.

Repair without new schema if possible:
- for a **kernel-owned** review dispatch, commit its durable owned-process-group handle/identity before creating the reviewer process group, using the same write-ahead/no-untracked-group discipline as attempts;
- NULL on that field for a kernel-owned dispatch is positive proof no owned group was created, not a signal that the reviewer is external;
- determine external-vs-kernel-owned reviewer from the already-durable reviewer principal/session kind (or equivalent existing principal/role identity), never from NULL process-group identity;
- §6 step 3 must branch on reviewer ownership/principal kind first. For kernel-owned reviewer: use the durable handle and prove empty before slot/concurrency release. For external reviewer: fencing-only cancellation is allowed and the limitation remains recorded;
- apply the same controller-allocated/non-recycled identity requirement and ownership re-verification before signalling;
- make §1A's “uniformly to all three” execution records mechanically true.

Acceptance:
- extend ST-17 with controller crash after durable kernel-owned reviewer handle commit / around reviewer process creation, then candidate.reject; prove the reviewer is stopped before REJECTED commits, or subject BLOCKED if cleanup cannot be proven;
- prove required-review slot and reviewer-concurrency unit are not released while a kernel-owned orphan can still exist;
- add an external-principal negative arm proving external review still uses fencing-only semantics;
- structural test must inspect the actual review_dispatch record and §6, and fail the rejected tree rather than only restating prose.

### Regression/evidence
Preserve N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03, G-01..G-03, H-01/H-02. Add explicit H-03/H-04 traceability dispositions. Keep §3.1 token/derivation behaviour intact.

Run the committed freeze-spec test and relevant non-live/static checks. Prove the new tests fail against exact rejected SHA `9fbe4a9` using blob/scratch materialisation without modifying owner work. Recompute:
- zero dangling acceptance IDs;
- complete §18A MUST coverage;
- every non-terminal attempt state has terminal cleanup/fencing;
- delivery enum/§3C completeness;
- no self-adoption;
- no DEC-046/DEC-047 drift.

Before publication report exact base/rejected/new SHAs, changed-file set/diff summary, test results, clean worktree, changed-file secret scan with no values printed, and exact remote readback. Publish only to the freeze-candidate branch.

### Handoff
Do not self-certify. State the previous verdict is stale for the changed SHA and that exactly one fresh independent read-only adversarial review bound to the new exact SHA is required. Do not dispatch any additional task yourself.