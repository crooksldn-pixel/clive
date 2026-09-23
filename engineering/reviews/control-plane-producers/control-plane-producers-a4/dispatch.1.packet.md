# EXACT-SHA GPT REVIEW PACKET 12 — Kernel repair round K-10, K-11 (control-plane-producers r4)

Generated 2026-09-23 00:57Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. One repository, one successor commit to 31fb7553, the two findings of packet 11 resolved; K-06 and K-09 were closed by that review.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `692999fcffea238e4fd6acb4722ba2e02955dc9f` |
| branch (head == candidate when written) | `claude/control-plane-producers-2026-09-22` |
| base / parent | `31fb755360ae40959c14d608de0035815c41cc40` (packet 11, CHANGES REQUIRED; preserved, not rewritten) |
| kernel task | `control-plane-producers` r4, attempt `control-plane-producers-a4`, fencing token 4, on `clive/engineering-state` |
| author_principal | claude |
| review_state | NOT_REVIEWED |
| ci_state | PASS — run 35803753989, https://github.com/crooksldn-pixel/clive/actions/runs/35803753989, 2026-09-23T00:50:04Z to 00:53:36Z, all five gates green |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha 692999fc… --suite full` at 2026-09-23T00:55:01Z, Python 3.12.3, gitleaks 8.30.1, clean tree: ruff pass; pytest_control_plane 44 passed; product_memory_structure pass; pytest_offline_full 3098 passed, 8 skipped, 2 deselected in 294.96s; secret_scan no leaks; `eligible_for_acceptance_decision: true`, `accepted: false` (`acc-wt-cp-692999fc….json`, recorded as this attempt's evidence) |
| Agent Environment | unchanged at `c20f5397`; the projection document is unchanged (no `owner_resolutions` entry can be written any more, so the list stays empty) |
| packet 10 | `b68e6e827afbeba3364c8239a2d814a60372f498` unchanged, READY and ACCEPTED in the store; landed only after this candidate is READY |

## Diff scope

`git diff --stat 31fb7553..692999fc`: 4 files, 249 insertions, 122 deletions — `app/orchestrator/lifecycle.py` (+196/−?), `scripts/engineering_kernel.py`, `tests/test_lifecycle_kernel.py` (+138/−?), `docs/product-memory/ENGINEERING_LIFECYCLE_PRODUCERS.md`. Untouched: the gates (`routing`, `review_acceptance`, `review_result_gate`, `policy`, `store`, `contracts`) and the owner judgment modules (`app/actions/judgment.py`, `judgment_ledger.py`). Lifecycle architecture, Agent Environment, model routing and product semantics are unchanged.

## The two findings, each with its mechanism and its test

| Finding | Mechanism at 692999fc | Test |
| --- | --- | --- |
| **K-10** owner origin is not trusted | The smallest fail-closed rule you named: no existing owner-ingress artifact in this repository has verifiable origin (the owner's ledger is a file; a git author or committer string is self-asserted), so an owner gate is unresolvable by the repository-only kernel. `resume` refuses an owner-gated task outright; `cancel_attempt` (which would have reset the task to READY with the gate cleared) and `block` (which would have overwritten the gate's class and flag with a non-owner blocker, then resumable) now refuse it too, alongside `create_task`'s existing refusal to supersede it: the kernel has no path round the owner. The binding contract is preserved read-only: `gate_proposal()` (CLI `gate`) says what an owner judgment must be about; `verify_owner_judgment_binding()` (CLI `verify-judgment`) checks that a `JudgmentRecord` is in the owner's ledger and uncorrected, was made by an owner-role principal in a named session, judges exactly this gate (proposal id and fingerprint), task, revision and attempt, and is APPROVED, and reports `origin_trusted: false`, `lifts_the_gate: false`. `--owner-judgment` and `--owner-ledger` no longer exist on `resume`. `OwnerResolution` stays defined as the record a trusted owner authority adapter would write; no verb writes it. Non-owner BLOCKED tasks resume as before. | `test_an_owner_judgment_binding_is_verified_but_never_lifts_the_gate`: the ten binding refusals from packet 11 now through `verify_owner_judgment_binding`; then **the adversarial case you asked for**: the controller writes a perfectly valid owner judgment itself (principal `owner`, a session, the exact task, revision, attempt, proposal id and fingerprint, APPROVED); the binding verifies (`bound: true`, `origin_trusted: false`), and `resume` is still refused ("cannot verify owner origin"), the gated state byte-identical, no resolution written, the gate's proposal unchanged. `test_an_owner_gate_is_not_lifted_cancelled_reblocked_or_superseded_by_the_kernel`: OWNER_GATE r1 → create r2, resume, cancel, re-block each refused; state bytes and journal identical; a DETERMINISTIC-blocked task is still superseded normally. `test_block_and_resume_recompute_the_stage_from_the_records` now uses a non-owner blocker. |
| **K-11** rollback restores HEAD, not the pre-verb index | Rule A, enforced mechanically: `journal_preconditions()` runs under the lock, before a journaled verb's first write. Nothing may be staged anywhere in the checkout (`git diff --cached --name-only` empty): a staged change outside the store would ride along in the kernel's commit, one inside it would be lost to a rollback. Nothing under the store may be modified or untracked (`git status --porcelain --untracked-files=all -- <store>` empty, the layout's own lock file excepted): it would be swept into the commit as the verb's own. Either is a refusal naming the paths; the offending state is left as found. With both true the pre-verb index equals HEAD for the store, so the K-08 rollback (`git reset HEAD -- <store>`) restores the pre-verb index exactly, and a kernel commit can carry nothing but the kernel's writes. The dedicated clean checkout is a checked precondition, not a documented assumption. A store outside any checkout has no journal and no preconditions; `journal=False` skips them. | `test_the_journal_refuses_a_checkout_with_staged_or_uncommitted_state_before_writing_anything` (real repository): a file staged outside the store → refused naming `notes.txt`, the index left with it staged, HEAD and the store unchanged; an edited `ACTIVE_STATE.json` → refused naming it, the edit left in place; a stray file under the store → refused naming it; then, clean, the verb commits and `git show --name-only HEAD` lists only `engineering/` paths, never `notes.txt`. The K-08 hook test still holds (clean pre-verb index, so HEAD state is the pre-verb index state). |

The other 48 kernel tests are unchanged in intent; `tests/test_lifecycle_kernel.py` 50 passed; with the projection, route, control-plane and judgment suites 151 passed.

## Reviewer checklist

1. SHA resolves; parent 31fb7553; tree clean; `git diff 31fb7553 692999fc --stat` is the four files above.
2. `python -m pytest tests/test_lifecycle_kernel.py -q` → 50 passed. Then try: `resume`, `cancel`, `block` and `task --revision N+1` on an owner-gated task through the CLI; a judgment file with two entries about the gate; `git add` of a file outside the store followed by any verb; a store edited by hand followed by any verb; an untracked directory under the store (empty directories are invisible to git and harmless).
3. Confirm `journal_preconditions` runs before `begin_undo` in `_verb`, under the lock, and only when `journal` is on.
4. Confirm no verb calls `put_owner_resolution` (`grep put_owner_resolution app/orchestrator/lifecycle.py` shows the store method only).
5. Decide the judgement calls below.

## Known risks and judgement calls

1. **Owner gates are terminal for this kernel.** Until a trusted owner authority adapter exists, an owner-gated task cannot be lifted, cancelled, re-blocked or superseded; a gate set by mistake stays too. This is the doctrine you stated (an owner gate may remain an owner gate); the cost is that a wrongly gated task needs the adapter, not a workaround.
2. **The staged-changes check is repository-wide**, because `git commit` commits the whole index; a person using the state checkout for anything else will be refused until they commit or unstage. Deliberate: the store is a dedicated checkout.
3. **`OwnerResolution` and its store methods remain without a writer.** Kept as the adapter's contract; removable if you would rather the kernel carry no unreachable record type.
4. **Rule A over rule B.** Snapshotting and restoring the pre-verb index was rejected as a second rollback mechanism; the precondition makes the existing one exact.
5. **Records written this round by the 31fb7553 kernel** (the packet 11 admission, r4's task, assignment, acknowledgement and heartbeat) used none of the two repaired paths; r4's evidence, candidate and dispatch are written by 692999fc itself, under its own preconditions.
6. As before: the writer lock is filesystem-scoped; the `on_validated` seam is a no-op in production.

## After acceptance

`integrate --task-id control-plane-producers --revision 4 --integration-sha 692999fc… --target-base-sha 31fb7553… --method fast_forward --verify-remote origin` → DONE, rendered COMPLETE. Then packet 10's accepted candidate b68e6e82 is landed on the CI stream (fast-forward from 6b7c43d2, re-checked at the time), its integration recorded, and the recovery/integration sequence reported closed. Nothing deploys; no watcher, systemd, runtime or business write.
