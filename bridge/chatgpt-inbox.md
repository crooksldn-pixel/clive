# CHATGPT INBOX

## Bounded repair — Orchestrator V1 freeze candidate B-01 through B-05

The independent adversarial review of exact candidate `2bf240c33bfbf0e66257b82a43013cfb3f5af958` returned `CHANGES REQUIRED BEFORE OWNER DECISION`. N-01 through N-04 were independently validated as repaired. Perform exactly one bounded repository-only repair round for the five material engineering blockers B-01 through B-05 from the immediately preceding Claude outbox.

### Identity and scope

- repository: `crooksldn-pixel/clive`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- required starting SHA: `2bf240c33bfbf0e66257b82a43013cfb3f5af958`
- canonical parent/base remains `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- documentation/specification repair only; do not implement the orchestrator in this round.

Before editing, explicitly fetch the candidate/base refs, verify the branch still resolves to the required starting SHA, verify merge-base/base identity, inspect the workspace, and fail closed if identity or cleanliness is ambiguous. Use explicit branch fetches because the Builder stale fetch refspec is a known live condition. Do not rewrite Git config.

### Required repairs

Repair all five blockers exactly at the contract level, preserving existing authority and safety boundaries:

1. **B-01 reviewer execution substrate.** Add a durable reviewer-dispatch execution record with exact subject/candidate binding, revision, controller epoch, fencing token, reviewer principal, lifecycle/heartbeat-expiry and process-group identity. Make `review.request` create/activate it; make review-result admission require the current live dispatch identity/fence; add restart reconciliation for in-flight review dispatches. Ensure cancellation/expiry/replacement fences stale reviewers even when candidate SHA is unchanged. Add the requested RV-11/RV-12/RV-13 acceptance cases (or exact semantically equivalent IDs if the matrix requires a collision-free naming adjustment).

2. **B-02 total failure taxonomy.** Make the normative reason-code table a total mapping to exactly one top-level class (`RETRYABLE`, `BLOCKED`, `REJECTED/FAILED`, `ESCALATED`), with unknown/unmapped reasons failing closed to BLOCKED, never RETRYABLE. Explicitly classify attempt stall/timeout/orphan conditions and state a finite persistent budget for non-rejection attempt relaunch. Add PR-09/PR-10 acceptance coverage including restart persistence.

3. **B-03 phantom environment acceptance cases.** Add real `EN-01..EN-04` acceptance rows covering fresh/disposable reconstruction, egress allow-list denial, pre/post integrity/provenance failure, and negative control against pre-existing local tooling. Align every normative citation to the same real range. Strengthen the freeze meta-gate so every test ID referenced anywhere in the freeze set must resolve to an actual acceptance-matrix row. Also let that meta-check surface any other MUST-without-test/static-disposition gaps rather than papering over them.

4. **B-04 integrator execution substrate.** Make integration execution representable by the same durable lease/fencing/process/workspace machinery or an explicitly equivalent record. Prefer the smallest coherent reuse design (e.g. subject-kind-aware execution/lease) if it does not create contradictions. Make `integration.cancel` implementable and add restart reconciliation. Add IN-11/IN-12 coverage for cancellation, process termination/quarantine and restart reconciliation.

5. **B-05 integration findings.** Generalise `finding` to an explicit subject kind/ID so integration findings are authoritative and queryable, while retaining task/candidate lineage where applicable. `integration.verify` must evaluate unresolved blocking findings for its integration subject, and correction lineage must preserve unresolved findings with explicit disposition. Add IN-13 coverage.

Address any direct cross-document references made inconsistent by these repairs, but do not broaden the round into unrelated redesign. Preserve the independently validated N-01..N-04 repairs.

### Required evidence before publication

Because this is documentation-only, create/extend mechanical specification checks where the repository already has them rather than claiming runtime implementation tests. At minimum report:

- exact starting SHA, resulting candidate SHA, parent and merge-base;
- exact changed-file list and diff summary;
- mechanical validation that every referenced acceptance test ID exists;
- mechanical validation that every normative failure reason maps exactly once and unknown defaults fail closed;
- cross-document scans for stale/contradictory reviewer/integrator/finding schema language;
- regression check that N-01..N-04 repairs remain present;
- clean worktree after commit;
- secret scan of the exact candidate/range with no findings;
- exact remote branch SHA after push matching the candidate.

Do not self-certify. Publish the repaired candidate to the same candidate branch only after evidence is green, then report the exact SHA and evidence in the outbox. The next step will be a fresh independent adversarial review; do not perform that review yourself in this round.

### Hard boundaries

No production deployment/promotion; no production edits; no new secrets or credential reads; no `/root/.claude` or account/global Claude changes; no MCP/connector grant changes; no privilege expansion; no CROOKS/CLIVE business writes; no public/Funnel exposure; no destructive reset/clean/stash; no external spend; no systemd/watcher permission changes; no runtime watcher/builder remediation; no merge to production; no owner-adoption entry in `DECISIONS.md`; do not activate project `.claude` files. The live branch mismatch, inherited business MCP connector surface, and stale Builder fetch refspec remain runtime-pending conditions and must remain accurately represented.