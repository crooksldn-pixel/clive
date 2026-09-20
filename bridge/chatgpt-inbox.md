# CHATGPT INBOX

## Fresh independent read-only adversarial review — Orchestrator V1 freeze candidate c7c3d52

Review exact candidate only:
- repository: `crooksldn-pixel/clive`
- canonical base: `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- exact candidate SHA: `c7c3d523b7bafe5c73ae4d82275e6f1a297600f0`
- parent/rejected SHA: `2f1acc0b7edd233735e419d92cfbade914b0042f`
- J-01 repair outbox consumed: blob from the immediately preceding completed repair round; do not trust its prose without reproducing evidence.

This is exactly one fresh independent **read-only** adversarial review. The previous verdict is stale for this SHA.

### Hard scope
Read-only everywhere except normal publication of `bridge/claude-outbox.md`. Do not edit candidate/canonical/product code or docs, commit, push, merge, deploy, switch/reset/clean/stash owner work, change watcher/systemd/runtime, repair the stale Builder fetch refspec, alter `/root/.claude` or account/global settings, change MCP/connectors, read new secrets, widen privileges, perform CROOKS/CLIVE business writes, expose anything publicly, spend externally, adopt the freeze, or amend DEC-046/DEC-047.

### Identity first
Resolve candidate and canonical refs from fresh remote truth using explicit full refs / ls-remote. Abort review as BLOCKED if candidate != exact `c7c3d523b7bafe5c73ae4d82275e6f1a297600f0`, canonical != exact `9e59860a945ec339c69af8709cd0721f0a795327`, merge-base(candidate, canonical) != canonical, or unrelated owner work contaminates the review workspace. Never trust the known-stale tracking ref. Verify `2f1acc0..c7c3d52` is exactly one commit and inspect the full five-file diff.

### Re-review J-01 aggressively
Try to break the new durable occupancy model rather than confirming the narrative.

Verify from the actual normative tables/state enum/transitions that:
- `review_dispatch.QUARANTINED` is durable, authority-terminal, distinct from clean `FENCED`, and cannot admit a result;
- EXTERNAL reviewers never acquire kernel cleanup/quarantine semantics merely because they lack a process-group handle;
- occupancy is a pure function of committed records and counts cleanup-unproven terminal records, not terminality/non-terminality alone;
- a QUARANTINED kernel-owned dispatch holds both its required-review slot and global reviewer-concurrency unit across controller restart/epoch change/DB restore;
- a CLOSED/QUARANTINED attempt with an unretired owned-process-group handle holds its implementation/integration execution capacity and lease;
- same-slot replacement and different-subject admission cannot exceed the configured ceiling while quarantine occupancy exists;
- the only dispatch release transition is cleanup-proven `QUARANTINED -> FENCED`, committed after authoritative emptiness proof, without restoring result authority;
- attempt occupancy release by durable handle retirement likewise requires authoritative emptiness proof and does not decrement/reset R-02 execution-attempt budget or create a relaunch path;
- clean cancellation/fencing releases promptly only after cleanup proof and does not leak capacity;
- stale/recycled process identity remains fail-closed;
- §3.1, §3B, §3D, §6, FC §15, FC §19, FC §21 and ST-13/ST-16/ST-17/RS-03/RS-04 agree without a second contradictory accounting rule.

Attack cross-resource cases: quarantined reviewer + unrelated reviewer, quarantined implementation attempt + integration attempt, multiple tasks, restart during reconciliation, crash after emptiness proof but before release commit, crash after release commit, and late result before/during/after release transition.

### H-03 structural guard
The prior review showed a paraphrased two-group handover could coexist with a prohibition and still pass. Verify the new positive cardinality/write-point invariant actually derives one lifetime owned group and one handle write point from the real transition rows, and cannot be bypassed by adding a second semantically equivalent write/handover path or by rephrasing the old defect. Check that FC §11 and SA §3A.3 still agree.

### Mechanical-test quality / false-green search
Re-run the committed freeze-spec suite if possible. Reproduce the implementer's failing-before evidence against exact parent `2f1acc0` using immutable blobs/scratch only. Independently inspect the new test logic, not just its pass count. Try mutations equivalent to:
1. FC §19 counts non-terminal dispatches only;
2. step-7 unproven cleanup releases occupancy;
3. QUARANTINED dispatch represented as FENCED;
4. per-slot uniqueness ignores quarantine;
5. release transition no longer requires proven emptiness;
6. attempt quarantine no longer occupies capacity;
7. a paraphrased second attempt process-group handover/write path is introduced.
A conforming gate should fail each unsafe mutation for a structural/derived reason, not only a brittle phrase blacklist.

### Full regression search
Also re-check all prior resolved classes N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03, G-01..G-03, H-01..H-04 for regression. Recompute/inspect:
- zero dangling acceptance IDs;
- complete §18A MUST coverage;
- every non-terminal attempt state has terminal cleanup/fencing;
- delivery enum ↔ §3C completeness and crash/idempotency guarantees;
- subject/attempt/reviewer/integration joint-state legality;
- restart/epoch/stale-result fencing;
- attempt-ceiling liveness/safety;
- journal completeness;
- no self-adoption;
- no DEC-046/DEC-047 sequencing drift.

Search for any new material engineering blocker, not just J-01. Distinguish engineering blockers from known owner/runtime gates.

### Owner/runtime separation
These remain separate and are not engineering defects if the contract correctly fails closed:
- exact freeze adoption by SHA = OWNER-PENDING;
- any DEC-046 sequencing amendment = OWNER-PENDING;
- live watcher/builder branch mismatch = RUNTIME-PENDING;
- stale Builder fetch refspec = RUNTIME-PENDING;
- inherited business MCP connector surface = RUNTIME-PENDING.
Do not remediate them.

### Verdict
Return exactly one:
- `ENGINEERING CONTRACT READY — OWNER/RUNTIME GATES REMAIN`
- `CHANGES REQUIRED BEFORE OWNER DECISION`

If changes are required, report only material engineering blockers with exact location, concrete failure scenario/consequence, smallest bounded repair, and exact acceptance/mechanical test. Record reviewer-independence limitations. Do not self-certify because the documents are detailed; try to break the contract.
