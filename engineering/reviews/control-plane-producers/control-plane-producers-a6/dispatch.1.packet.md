# EXACT-SHA GPT REVIEW PACKET 14 — Kernel repair round K-14 (control-plane-producers r6)

Generated 2026-09-23 01:23Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. One repository, one successor commit to 50631159, the one finding of packet 13 resolved; K-13 was closed by that review.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `18c3153a2eec10c6343153b550776afed3bec2ba` |
| branch (head == candidate when written) | `claude/control-plane-producers-2026-09-22` |
| base / parent | `5063115965d6b431019e8b9bc4008fdf8133e008` (packet 13, CHANGES REQUIRED; preserved, not rewritten) |
| kernel task | `control-plane-producers` r6, attempt `control-plane-producers-a6`, fencing token 6, on `clive/engineering-state` |
| author_principal | claude |
| review_state | NOT_REVIEWED |
| ci_state | PASS — run 35805639327, https://github.com/crooksldn-pixel/clive/actions/runs/35805639327, 2026-09-23T01:16:47Z to 01:21:03Z, all five gates green |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha 18c3153a… --suite full` at 2026-09-23T01:21:38Z, Python 3.12.3, gitleaks 8.30.1, clean tree: ruff pass; pytest_control_plane 44 passed; product_memory_structure pass; pytest_offline_full 3101 passed, 8 skipped, 2 deselected in 289.07s; secret_scan no leaks; `eligible_for_acceptance_decision: true`, `accepted: false` (`acc-wt-cp-18c3153a….json`, recorded as this attempt's evidence) |
| Agent Environment | unchanged at `c20f5397` |
| packet 10 | `b68e6e827afbeba3364c8239a2d814a60372f498` unchanged, READY and ACCEPTED in the store; landed only after this candidate is READY |

## Diff scope

`git diff --stat 50631159..18c3153a`: 3 files, 72 insertions, 6 deletions — `app/orchestrator/lifecycle.py` (+25/−6, all inside `journal_preconditions`), `tests/test_lifecycle_kernel.py` (+47, one test), `docs/product-memory/ENGINEERING_LIFECYCLE_PRODUCERS.md` (one bullet). Untouched: the CLI, the gates, the owner judgment modules, the K-10 owner policy, the K-13 scoped commit, the lifecycle architecture, the Agent Environment, routing and product semantics.

## The finding, its mechanism and its test

| Finding | Mechanism at 18c3153a | Test |
| --- | --- | --- |
| **K-14** the canonical lock was exempt whatever its state | In `journal_preconditions()`, a porcelain entry for exactly `<store>/.kernel.lock` is exempt only when its status is `??` (untracked) and the file is empty (`st_size == 0`): the one state the layout creates, seen once, on the first journaled verb, which commits it. Once tracked, a clean lock produces no entry. Any other state of that path (` M` modified, a replaced or non-empty file, `??` with content) is a refusal before any write that names the git status and the size; a staged lock is refused by the staged-anywhere check that runs first, as before. The writer lock (`flock`) never needs the file's content to change, so nothing legitimate is refused. Every other store path is handled as before. | `test_the_lock_file_is_exempt_only_while_untracked_and_empty` (real repository): (1) a fresh store creates the exact empty lock and the first journaled verb succeeds and commits it (`git ls-files` shows it; status clean); (2–4) the tracked lock is overwritten with "unexpected", the next verb is refused naming `engineering/.kernel.lock`, the contents stay "unexpected", the porcelain still reads ` M`, the index is empty, HEAD and the task state are unchanged and no attempt exists; staging the modification is refused by the staged-anywhere check; restored with `git checkout`, the verb runs and commits; (5) in a second fresh repository a pre-existing non-empty untracked `engineering/.kernel.lock` makes the first verb refuse (status `??`, 8 bytes) rather than bless it, nothing is tracked, no task is written; emptied, the first verb succeeds and commits the lock. The K-12 stray-name test and the K-13 scoped-commit test are unchanged and pass. |

`tests/test_lifecycle_kernel.py` 53 passed; with the projection, route, control-plane and judgment suites 154 passed.

## Reviewer checklist

1. SHA resolves; parent 50631159; tree clean; `git diff 50631159 18c3153a --stat` is the three files above; `git diff 50631159 18c3153a -- scripts app/actions` is empty.
2. `python -m pytest tests/test_lifecycle_kernel.py -q` → 53 passed. Then try: a lock deleted and recreated empty while tracked (identical to HEAD, so no entry: allowed, and correct); a lock deleted and not recreated (the layout recreates it empty before the check, so it reads clean); a symlink at the lock path (`is_file()` follows it; a symlink to an empty file is `??` or `T`; a typechange is refused by the rule since its status is not `??`); a lock made non-empty between the precondition and `git add` (outside the model, as any concurrent write into the store under the writer lock).
3. Confirm the exemption is the only special case in the working-tree rule and that the staged-anywhere check precedes it.

## Known risks and judgement calls

1. **Recreation is indistinguishable from cleanliness.** A tracked lock deleted and recreated empty reads clean to git and is allowed; that is the same bytes as HEAD and harmless to the journal.
2. **The first verb on a fresh store commits the lock.** As before; the exemption is what lets it, and only in that state.
3. **Records written this round by the 50631159 kernel** (the packet 13 admission, r6's task, assignment, acknowledgement and heartbeat) ran with the tracked, clean lock; the K-14 paths were not exercised by them. r6's evidence, candidate and dispatch are written by 18c3153a itself.
4. As before: the writer lock is filesystem-scoped; the `on_validated` seam is a no-op in production; owner gates are unresolvable by this kernel; the precondition stays repository-wide.

## After acceptance

`integrate --task-id control-plane-producers --revision 6 --integration-sha 18c3153a… --target-base-sha 50631159… --method fast_forward --verify-remote origin` → DONE, rendered COMPLETE. Then packet 10's accepted candidate b68e6e82 is landed on the CI stream (fast-forward from 6b7c43d2, re-checked at the time), its integration recorded, and the recovery/integration sequence reported closed. Nothing deploys; no watcher, systemd, runtime or business write.
