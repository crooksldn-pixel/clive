# EXACT-SHA GPT REVIEW PACKET 9 — Kernel repair round K-01..K-05 (control-plane-producers r2)

Generated 2026-09-23 00:05Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. One repository, one commit, the five findings of packet 7 resolved together.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `acef34793d8742516aa7526480cb7cb959f0e651` |
| branch (head == candidate when written) | `claude/control-plane-producers-2026-09-22` |
| base / parent | `6ffb2c6626e020c8313910adf76dd6e6be2c6848` (packet 7, CHANGES REQUIRED; preserved, not rewritten) |
| kernel task | `control-plane-producers` r2, attempt `control-plane-producers-a2`, fencing token 2, on `clive/engineering-state` |
| author_principal | claude |
| review_state | NOT_REVIEWED |
| ci_state | PASS — run 35799408335, https://github.com/crooksldn-pixel/clive/actions/runs/35799408335, 2026-09-22T23:51:38Z to 23:55:10Z, all five gates green |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha acef3479… --suite full` at 2026-09-23T00:01:57Z, Python 3.12.3, gitleaks 8.30.1, clean tree: ruff pass; pytest_control_plane 44 passed; product_memory_structure pass; pytest_offline_full 3093 passed, 8 skipped, 2 deselected in 291.88s; secret_scan no leaks; `eligible_for_acceptance_decision: true`, `accepted: false` (`acc-wt-cp-acef3479….json`, recorded as this attempt's evidence) |
| Agent Environment | unchanged at `c20f5397`: the record schema changed only additively (`owner_resolutions` on a task, `local_head_sha` and `integration_candidate` on an integration), which the adapter ignores; no rendering was required by the findings |

## Diff scope

`git diff --stat 6ffb2c66..acef3479`: 4 files, 740 insertions, 68 deletions — `app/orchestrator/lifecycle.py` (+450/−?), `scripts/engineering_kernel.py`, `tests/test_lifecycle_kernel.py` (+297), `docs/product-memory/ENGINEERING_LIFECYCLE_PRODUCERS.md`. The gates are untouched: `git diff 6ffb2c66 acef3479 -- app/orchestrator/{routing,review_acceptance,review_result_gate,policy,store,contracts}.py` is empty. The task/attempt/lease/event/review/acceptance/integration model is unchanged; two records were added (`OwnerResolution`, `IntegrationCandidateRef`) and two optional fields on `Integration`.

## The five findings, each with its mechanism and its test

| Finding | Mechanism at acef3479 | Test |
| --- | --- | --- |
| **K-01** scope worker-declared | `record_candidate()` calls `GitFacts.changed_paths(base, candidate)` (`git diff --name-only`) and records that; `changed_paths` is now optional and, when declared, must equal the derived set exactly (a refusal names what was omitted and what is not in the diff); a repository that cannot answer is a refusal. `evaluate_obvious_continuation()` (unchanged) therefore enforces `allowed_paths` against the diff at dispatch. | `test_changed_paths_come_from_git_and_an_omitted_out_of_scope_change_cannot_reach_review` (declared subset refused; undeclared → recorded from git → dispatch refused "outside task scope: ops/deploy.sh"); `test_an_in_scope_candidate_declared_exactly_or_not_at_all_is_recorded_from_git` |
| **K-02** revision bypasses an owner gate | `create_task()` refuses when revision N−1 is owner-gated (status OWNER_GATE, `owner_gate`, or blocker class OWNER_ONLY: `_owner_gated()`), before any write; the only way out is `resume --owner-resolution <text/ref> --resolved-by <principal>` where the principal must carry the `owner` role in `config/review_principals.json` (`PrincipalRegistry.is_owner`), which writes an immutable `OwnerResolution` record and a `resumed` event naming it; the stage is recomputed, the live attempt still has to be cancelled, and only then can N+1 open. A revision blocked on a TRANSIENT or DETERMINISTIC blocker may still be superseded (that is how such a blocker is repaired); challenge this. | `test_a_revision_cannot_supersede_an_owner_gate_without_the_owners_recorded_resolution` (OWNER_GATE r1 → create r2 refused → r1 state bytes identical; resume without resolution refused; resume by `gpt` refused; resume by `owner` writes the record; r2 still refused while the attempt lives; cancel; r2 opens; a DETERMINISTIC-blocked t-3 r1 is superseded) |
| **K-03** partial records on a lost CAS | Every verb is wrapped by `_verb`: it holds an exclusive `flock` on `<store>/.kernel.lock` for the verb's whole duration (every process on the filesystem contends; `--lock-timeout`, default 10 s, then `StoreBusyError`, nothing written) and keeps an undo log: `LifecycleStore._atomic_write` and `append_event` remember each path's previous bytes (or absence), and any exception after the first write restores them in reverse order. Each verb still checks everything before its first write (`_checkpoint`, which is also the test seam `on_validated`). | `test_two_competing_assignments_cannot_both_write` (kernel B assigns while A holds the lock between checks and first write: refused by the lock, nothing written; after A, refused by the stage; one attempt, one opened event, one token; the lock releases with the verb); `test_a_refusal_after_the_first_write_leaves_no_partial_record` (the state file is moved under the verb between checks and swap: the swap refuses, the attempt and the event are gone, state untouched); `test_a_journal_failure_rolls_the_store_back_to_the_last_commit` (real git store: a failing journal leaves the checkout clean and the records as before). Cross-process: `scripts/engineering_kernel.py --lock-timeout 0.3` was refused from a second process while a first held the lock (smoke test in the write-up). |
| **K-04** MERGE completes with unreviewed content | `integrate()`: the target base must be a commit and an ancestor of the integration SHA; the target ref must resolve to the integration SHA (the remote's with `--verify-remote`, else the local ref; the record carries `remote_head_sha` or `local_head_sha`, the validator requires one); FAST_FORWARD must land exactly the accepted SHA (also enforced by the record's validator); any integration SHA other than the accepted SHA is refused unless an `Acceptance` exists whose `accepted_sha` is the integration SHA and whose task's `base_sha` is the named target base; that acceptance is recorded in `integration_candidate`. No canonical contract defined a stronger mechanism (ENGINEERING_CONTROL_PLANE_VNEXT.md leaves integration to Phase 2), so this is the V1 rule as you stated it. | `test_a_merge_result_completes_only_as_an_accepted_integration_candidate` (accepted A; merge M refused "lands more than the accepted candidate"; M recorded, dispatched and accepted as its own candidate at base BASE; integrate with the wrong target base refused "not on the target base"; then DONE with `integration_candidate` naming the task; projection COMPLETE); `test_integration_requires_acceptance_ancestry_and_the_remote_head` (target base not an ancestor; local ref elsewhere; remote at None; fast-forward not at the accepted SHA) |
| **K-05** resume resurrects a rejected candidate | `resume()` recomputes through `_stage_from_records()`: the latest admitted (non-refused) verdict first (READY with its acceptance → ACCEPTED; REPAIR_REQUIRED → REJECTED), then dispatch → REVIEWING, candidate → EVIDENCE_READY, acknowledgement → RUNNING, else ASSIGNED. | `test_a_rejected_candidate_stays_rejected_across_block_and_resume` (REVIEWING → REPAIR_REQUIRED → BLOCKED → resume → REJECTED, and a late READY is refused; a refused verdict decides nothing → REVIEWING; an admitted READY → ACCEPTED) |

The other 37 kernel tests are unchanged in intent; eleven happy-path calls dropped their declared `changed_paths` (the record takes them from git) and the two completion tests integrate by fast-forward, as the rule now requires. `tests/test_lifecycle_kernel.py` 45 passed; with the projection, route and control-plane suites 116 passed.

## Reviewer checklist

1. SHA resolves; parent 6ffb2c66; tree clean; `git diff 6ffb2c66 acef3479 --stat` is the four files above.
2. `python -m pytest tests/test_lifecycle_kernel.py -q` → 45 passed. Read the eight tests named above as the attack list; then try to break them: a declared path set that is a superset; a merge whose integration task was built on the target base but accepted for a different SHA; an owner resolution by a principal whose registry entry has `may_review` but no `owner` role; a second kernel process during a verb.
3. Confirm `record_candidate` no longer stores anything the worker said about paths (`changed_paths=derived`).
4. Confirm the lock is held across the journal commit (`_verb` wraps the whole verb, `_commit` is inside) and that `roll_back` restores previous bytes rather than deleting a pre-existing file.
5. Decide the judgement calls below.

## Known risks and judgement calls

1. **The lock is filesystem-scoped.** Two hosts with separate clones of the state branch are not serialised by it; the contract states the operating rule (one clone writes; the journal is pushed fast-forward only, so divergence is a visible conflict, not a silent overwrite). Not enforced from inside one clone.
2. **BLOCKED (non-owner) predecessors may still be superseded.** Deliberate: a deterministic blocker is repaired by a new revision at a new base. If you want every BLOCKED predecessor refused until resumed, it is a one-line change to `create_task`.
3. **Integration candidates are matched by SHA and base, not by target branch.** The holding-branch flow (packet 10) relies on this: the integration candidate's task targets the holding branch it is published on, and the completing task's `integrate` checks its own target ref. Challenge whether the completing task's target branch should be required to equal the candidate task's target.
4. **`on_validated` is a test seam in production code.** No-op by default; it exists so the race and the rollback are deterministic rather than timing-based.
5. **The owner's resolution is declared.** `resume` records whoever the operator names as `--resolved-by`, checked only for the owner role in the registry; the kernel cannot verify the owner spoke, the same limit as reviewer facts.
6. **Records written this round by the 6ffb2c66 kernel.** The four verdict admissions, the three fast-forward integrations and the r2 task/assign/ack were written before the repair by the code under repair. None of those verbs is among the five findings (K-04's fast-forward rule is what they used), and the repaired kernel reads them unchanged. The r2 evidence, candidate and dispatch are written by acef3479 itself.
7. **`.kernel.lock`** is an empty file the layout creates under the store and the journal commits once.

## After acceptance

`integrate --task-id control-plane-producers --revision 2 --integration-sha acef3479… --target-base-sha 6ffb2c66… --method fast_forward --verify-remote origin` → DONE, rendered COMPLETE. Nothing deploys; no watcher, systemd or runtime change.
