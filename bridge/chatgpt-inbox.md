# CHATGPT INBOX

## Bounded repair — Orchestrator V1 freeze J-01

Perform exactly one bounded repository-only repair round on the existing freeze-candidate branch. This is not owner adoption, runtime remediation, production work, or Orchestrator implementation.

### Exact identities
- repository: `crooksldn-pixel/clive`
- canonical base: `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- rejected candidate: `2f1acc0b7edd233735e419d92cfbade914b0042f`
- independent-review inbox consumed: `a06148a9ddb288f445b4e010b1d4f60091757ff0`
- independent-review outbox blob: `17278d68bfeaecb47e7b0ac65a30a70c4ccef1b5`
- verdict: `CHANGES REQUIRED BEFORE OWNER DECISION`
- material finding: `J-01`

Before editing, resolve candidate and canonical refs from fresh remote truth using explicit full refs / `git ls-remote` as needed. Abort and report BLOCKED if candidate is not exactly the rejected SHA, canonical is not exactly the stated SHA, merge-base differs from canonical, or unrelated owner work is present. Never trust the known-stale tracking ref. Do not reset/clean/stash/discard owner work.

### Hard scope
Allowed: repository-only edits on the same freeze-candidate branch to the state API, freeze contract, acceptance matrix, traceability and mechanical freeze-spec tests necessary to repair J-01, plus repository-local/static evidence.

Forbidden: production deployment/promotion; systemd/watcher/builder-runtime changes; stale fetch-refspec repair; secrets/credential reads; `/root/.claude` or account/global Claude changes; MCP/connector changes; privilege expansion; CROOKS/CLIVE business writes; public exposure; destructive reset/clean/stash; external spend; production merge; freeze adoption; DEC-046/DEC-047 sequencing changes; Orchestrator implementation.

### J-01 — durable resource occupancy when cleanup is unproven

The independent review proved a real contradiction: §6/§3B/FC §15/§21 require a slot/concurrency unit to remain held when cleanup is unproven, while §3.1/FC §19/§21 and the current durable state model release/count only non-terminal records. A dispatch can be terminal `FENCED` on both clean and orphan paths, so durable state cannot distinguish them. An attempt can be terminal `QUARANTINED` while §19 currently counts it as zero. This can admit a second live process over a global concurrency ceiling and re-open H-04.

Repair this with a deterministic durable occupancy model. Prefer the smallest explicit design:

1. **Review dispatch cleanup state:** add a terminal `QUARANTINED` review-dispatch state (or an equivalently explicit durable cleanup-unproven representation only if materially smaller and clearer). Do not overload `FENCED`. `FENCED` means authority is revoked and kernel-owned cleanup is proven; `QUARANTINED` means authority is revoked but an owned kernel process group may still exist / cleanup is not proven. EXTERNAL reviewers do not become QUARANTINED merely because the kernel does not own a process; their limitation remains fencing-only and explicit.
2. **Durable occupancy rule:** FC §19 and SA must define execution/reviewer occupancy as a pure function of committed records: ordinary non-terminal execution records **plus cleanup-unproven terminal records**. For attempts, `CLOSED/QUARANTINED` continues to occupy its implementation/integration execution unit until reconciliation proves cleanup. For kernel-owned review dispatches, `QUARANTINED` continues to occupy the global reviewer-concurrency unit and its required-review slot until reconciliation proves cleanup. Do not let terminality alone imply resource release.
3. **Release transition:** specify the deterministic reconciliation transition after emptiness is later proven. It must durably move the cleanup-unproven record to a cleanup-proven terminal representation before/releasing occupancy, without reviving result authority or making stale results admissible. If using `QUARANTINED -> FENCED` for dispatch, state it explicitly and preserve stale fencing throughout. For attempts, use the existing quarantine/cleanup contract or minimally clarify the exact durable release condition; do not invent a relaunch path.
4. **Cross-document consistency:** repair §3.1, §3B, §6, FC §15, FC §19, FC §21 step 8/11 and ST-17/ST-16/ST-13 wording so the clean path releases immediately **only after proven emptiness**, while the unproven path retains occupancy. Remove any unconditional `immediately reusable` or `terminal records never occupy` statement that contradicts quarantine occupancy.
5. **Per-slot uniqueness:** required-review-slot uniqueness/admission must treat a cleanup-unproven `QUARANTINED` dispatch as occupying its slot even though it is authority-terminal. A replacement for that slot is forbidden until cleanup is proven and the durable release transition completes. Global reviewer concurrency must likewise count it.
6. **Attempts:** the single implementation slot and integration ceilings must count terminal `CLOSED/QUARANTINED` attempts as occupied while their owned group may still exist. A different task/integration cannot use that capacity merely because the attempt is terminal.
7. Preserve H-03/H-04 write-ahead identity, ownership-kind semantics, one-group/write-once attempt handle, stale/recycled identity fail-closed behaviour and R-02 attempt-budget accounting. Resource occupancy is separate from execution-attempt budget consumption.

### Acceptance and mechanical proof

Extend acceptance so at minimum:
- reviewer concurrency ceiling N: one kernel-owned reviewer becomes cleanup-unproven; prove committed durable state still consumes one global reviewer unit and its required-review slot; a different subject cannot exceed N; same-slot replacement is refused; after authoritative reconciliation proves emptiness and the durable release transition commits, the unit/slot becomes reusable;
- implementation concurrency = 1: task A attempt becomes `CLOSED/QUARANTINED` with cleanup unproven; task B cannot start; after cleanup is proven and durable release is recorded, task B may use the slot; no stale result from A regains authority;
- EXTERNAL reviewer fencing remains non-kernel cleanup and does not incorrectly consume a quarantine unit indefinitely;
- clean cancellation/fencing still releases at the proven-empty commit and does not leak capacity.

Mechanical tests must derive/check the actual state/occupancy rules, not merely assert contradictory prose strings. Specifically bind FC §19 counting to the durable states/dispositions and the review-dispatch enum; prove a cleanup-unproven dispatch cannot be represented as ordinary `FENCED`; prove per-slot uniqueness includes cleanup-unproven quarantine; prove attempt occupancy counts `QUARANTINED`; prove the release transition exists and requires proven emptiness. Add mutation cases that fail if §19 is changed to release at step 7 or to count only non-terminal rows.

Also strengthen the H-03 structural guard if bounded: the review demonstrated that merely adding a paraphrased two-group handover permission could pass while the prohibition sentence remained. Prefer a positive structural invariant tying FC §11 and SA §3A.3 to exactly one lifetime group/write-once handle rather than a blacklist of handover phrases. Do not broaden beyond this specification consistency issue.

### Regression/evidence
Preserve N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03, G-01..G-03, H-01..H-04. Add explicit J-01 traceability disposition. Keep §3.1 transition-disposal and H-03/H-04 semantics intact.

Run the committed freeze-spec test and relevant non-live/static checks. Prove new J-01 tests fail against exact rejected SHA `2f1acc0` using exact blob/scratch materialisation without modifying owner work. Recompute zero dangling acceptance IDs, complete §18A MUST coverage, terminal cleanup/fencing coverage, delivery enum/§3C completeness, no self-adoption and no DEC-046/DEC-047 drift. Run a changed-file secret scan with no secret values printed.

Before publication report exact base/rejected/new SHAs, exact changed-file set/diff summary, tests/results, clean worktree and exact remote branch readback. Publish only to the freeze-candidate branch.

### Handoff
Do not self-certify. The previous verdict is stale for any changed SHA. After repair, report exact new candidate/evidence and require exactly one fresh independent read-only adversarial review bound to that SHA. Do not dispatch any additional task yourself.