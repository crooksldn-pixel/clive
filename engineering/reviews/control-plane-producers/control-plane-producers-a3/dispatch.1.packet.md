# EXACT-SHA GPT REVIEW PACKET 11 — Kernel repair round K-06..K-09 (control-plane-producers r3)

Generated 2026-09-23 00:30Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. One repository, one successor commit to acef3479, the four findings of packet 9 resolved together.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `31fb755360ae40959c14d608de0035815c41cc40` |
| branch (head == candidate when written) | `claude/control-plane-producers-2026-09-22` |
| base / parent | `acef34793d8742516aa7526480cb7cb959f0e651` (packet 9, CHANGES REQUIRED; preserved, not rewritten) |
| kernel task | `control-plane-producers` r3, attempt `control-plane-producers-a3`, fencing token 3, on `clive/engineering-state` |
| author_principal | claude |
| review_state | NOT_REVIEWED |
| ci_state | PASS — run 35801776658, https://github.com/crooksldn-pixel/clive/actions/runs/35801776658, 2026-09-23T00:22:32Z to 00:25:55Z, all five gates green |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha 31fb7553… --suite full` at 2026-09-23T00:27:17Z, Python 3.12.3, gitleaks 8.30.1, clean tree: ruff pass; pytest_control_plane 44 passed; product_memory_structure pass; pytest_offline_full 3097 passed, 8 skipped, 2 deselected in 284.66s; secret_scan no leaks; `eligible_for_acceptance_decision: true`, `accepted: false` (`acc-wt-cp-31fb7553….json`, recorded as this attempt's evidence) |
| Agent Environment | unchanged at `c20f5397`; the only projection change is additive (the `owner_resolutions` entries of a task carry the judgment id, owner session, decision and proposal id) |

## Diff scope

`git diff --stat acef3479..31fb7553`: 4 files, 504 insertions, 67 deletions — `app/orchestrator/lifecycle.py` (+327/−?), `scripts/engineering_kernel.py`, `tests/test_lifecycle_kernel.py` (+200), `docs/product-memory/ENGINEERING_LIFECYCLE_PRODUCERS.md`. Untouched: the gates (`routing`, `review_acceptance`, `review_result_gate`, `policy`, `store`, `contracts`) and the owner judgment modules (`app/actions/judgment.py`, `judgment_ledger.py`), whose diff is empty. The task/attempt/lease/event/review/acceptance/integration model is unchanged.

## The four findings, each with its mechanism and its test

| Finding | Mechanism at 31fb7553 | Test |
| --- | --- | --- |
| **K-06** rename collapses scope | `GitFacts.changed_paths()` runs `git diff --name-status --no-renames -z <base> <head>` and takes every path of every entry (`_paths_from_name_status`: one path per status, both for an R or C entry should git still emit one). Rename and copy detection is off, so a move is a deletion of its source and an addition of its destination, and both are in the recorded set that the scope gate inspects at dispatch. | `test_a_move_out_of_scope_is_seen_in_a_real_repository`: a real repository, `forbidden/secret.txt` committed, then `git mv` to `allowed/secret.txt`; the plain `--name-only` output is shown to contain the destination (with rename detection it is all it contains); `changed_paths` returns both; through the kernel with the real `GitFacts`, a task scoped to `allowed` refuses the declaration that omits the source (`omitted: forbidden/secret.txt`), records both paths when nothing is declared, and refuses the dispatch (`outside task scope: forbidden/secret.txt`). |
| **K-07** owner authority typed at a prompt | `resume` for an owner gate takes `--owner-judgment <id> --owner-ledger <path>` and nothing else. The ledger is the owner layer's file of `JudgmentRecord`s (JSON lines; `judgment_to_dict` is the line, `load_judgment_ledger` rebuilds each line as a `JudgmentRecord`, which validates itself, and appends it through `JudgmentLedger.append`, so a ledger the ledger would not have accepted is refused whole). `_verified_owner_judgment` requires: the id is in the ledger; no later entry corrects it; its `provenance.principal_id` carries the owner role in the registry (its `session_id` is required by the record itself); it judges exactly this gate: `gate_proposal()` derives the proposal id (`owner-gate:<task>:r<rev>:t<gating transition>`) and the canonical fingerprint of the gated state (task, revision, attempt, blocker class and reason, gating transition, time), and the judgment's `task_id`, `task_revision`, `attempt_id`, `proposal_id` and `proposal_fingerprint` must all match; and its decision is APPROVED. Only then is the `OwnerResolution` written, naming the judgment id, the ledger path and its SHA-256, the owner principal and session, the decision and reason code, and the proposal id and fingerprint. `--resolved-by` and `--owner-resolution` no longer exist. `gate` (read-only) prints the proposal for the owner layer to judge. | `test_an_owner_gate_is_lifted_only_by_an_owner_judgment_bound_to_the_gate`: ten refusals, each leaving the gated state byte-identical and no resolution written: no judgment; no ledger file; a judgment by `claude` in a named session ("naming the owner is not the owner"); an id not in the ledger; a judgment for revision 2; for another attempt; with another fingerprint; for another gating transition; DECLINED; an APPROVED judgment corrected by a later DECLINED one (both ids refused); a ledger line that is not a judgment. Then the owner's effective APPROVED judgment lifts the gate and the resolution carries the judgment id, session, ledger digest and proposal binding. The K-02 and block/resume tests go through the same path. |
| **K-08** journal failure leaves the index staged | `git_journal()` stages and commits inside one try; on `CalledProcessError` from either step it runs `git reset -q HEAD -- <store>` (every index entry under the store back to HEAD's) and raises `JournalError`; the `_verb` guard then restores the files from the undo log. Files and index are one rollback boundary; HEAD never moved. The CLI reports `JOURNAL FAILED` (exit 3), distinct from a refusal (exit 2). | `test_a_journal_commit_failure_after_staging_leaves_tree_index_and_head_as_before`: a real repository with a `pre-commit` hook that exits 1; the verb raises `JournalError("git commit failed…")`; `git status --porcelain` is empty, `git diff --cached --name-only` is empty, HEAD is unchanged, the state and journal are as before; with the hook removed the next verb commits and HEAD moves. The earlier monkeypatch test (failure before staging) is kept. |
| **K-09** a stale acceptance authorises a merge | `_accepted_integration_candidate()` refuses an acceptance whose revision is not its task's latest (`_latest_revision`, the continuation policy's own stale-revision rule), whose task state is not ACCEPTED or DONE (blocked, gated, obsolete, cancelled), or whose attempt is not the task's current one. The refusal names which. | `test_a_superseded_or_withdrawn_integration_candidate_acceptance_cannot_complete_a_merge`: the integration candidate r1 is accepted; blocked on a deterministic blocker → refused ("is blocked, not accepted or done"); revision 2 supersedes it, the r1 acceptance stays on disk → refused ("superseded by revision 2; its acceptance is history"); the original task stays ACCEPTED with no integration record. |

The other 45 kernel tests are unchanged in intent; `tests/test_lifecycle_kernel.py` 49 passed; with the projection, route, control-plane and judgment suites 150 passed.

## Reviewer checklist

1. SHA resolves; parent acef3479; tree clean; `git diff acef3479 31fb7553 --stat` is the four files above.
2. `python -m pytest tests/test_lifecycle_kernel.py -q` → 49 passed. Read the four tests named above as the attack list; then try: a move with edits (similarity below 100%: both paths still appear, detection is off); a copy; a binary file; two ledger lines about one proposal (the ledger refuses the second, so the whole ledger is refused); a judgment whose `attempt_id` is null for a gated task that has an attempt; a re-blocked task (the gating transition changed, so an old judgment no longer binds); a hook that fails on `git add` rather than `git commit`; an integration candidate whose task is DONE (accepted: a candidate fast-forwarded onto its holding branch is still authoritative).
3. Confirm the kernel never writes the owner ledger (`load_judgment_ledger` reads bytes; no writer exists in the kernel or the CLI).
4. Confirm `git reset -q HEAD -- <store>` runs before `JournalError` propagates and that the undo log then restores the files (`_verb`).
5. Decide the judgement calls below.

## Known risks and judgement calls

1. **Ledger authorship.** The kernel verifies a judgment's binding and provenance fields; it cannot verify who wrote the ledger file. That authorship belongs to the owner layer and, when the ledger lives in a checkout, to git. If you want the kernel to require the ledger inside the state checkout and the introducing commit authored by an owner identity, say so; it is a bounded addition.
2. **A gate re-blocked is a new proposal.** The proposal binds to the gating transition and time, so a judgment about an earlier gate on the same task does not lift a later one. Deliberate.
3. **`git reset HEAD -- <store>`** also unstages anything a person had staged under the store by hand before the verb; the store is meant to be written by the kernel only, and the working tree is untouched by the reset.
4. **DONE candidates count as authoritative** for K-09: an integration candidate fast-forwarded onto its holding branch has its state DONE and still authorises the merge it is. Challenge if you want ACCEPTED only.
5. **Records written this round by the acef3479 kernel** (the two verdict admissions, r3's task, assignment, acknowledgement and heartbeat) used none of the four repaired paths; r3's evidence, candidate and dispatch are written by 31fb7553 itself.
6. As before: the writer lock is filesystem-scoped; the `on_validated` seam is a no-op in production.

## After acceptance

`integrate --task-id control-plane-producers --revision 3 --integration-sha 31fb7553… --target-base-sha acef3479… --method fast_forward --verify-remote origin` → DONE, rendered COMPLETE. Then, and only then, packet 10's accepted candidate b68e6e82 is landed on the CI stream (fast-forward from 6b7c43d2, re-checked at the time) and its integration recorded. Nothing deploys; no watcher, systemd or runtime change.
