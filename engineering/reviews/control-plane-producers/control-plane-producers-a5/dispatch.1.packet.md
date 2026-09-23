# EXACT-SHA GPT REVIEW PACKET 13 — Kernel repair round K-12, K-13 (control-plane-producers r5)

Generated 2026-09-23 01:10Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. One repository, one successor commit to 692999fc, the two journal findings of packet 12 resolved; K-10 was closed by that review.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `5063115965d6b431019e8b9bc4008fdf8133e008` |
| branch (head == candidate when written) | `claude/control-plane-producers-2026-09-22` |
| base / parent | `692999fcffea238e4fd6acb4722ba2e02955dc9f` (packet 12, CHANGES REQUIRED; preserved, not rewritten) |
| kernel task | `control-plane-producers` r5, attempt `control-plane-producers-a5`, fencing token 5, on `clive/engineering-state` |
| author_principal | claude |
| review_state | NOT_REVIEWED |
| ci_state | PASS — run 35804714683, https://github.com/crooksldn-pixel/clive/actions/runs/35804714683, 2026-09-23T01:03:37Z to 01:07:05Z, all five gates green |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha 50631159… --suite full` at 2026-09-23T01:08:28Z, Python 3.12.3, gitleaks 8.30.1, clean tree: ruff pass; pytest_control_plane 44 passed; product_memory_structure pass; pytest_offline_full 3100 passed, 8 skipped, 2 deselected in 289.63s; secret_scan no leaks; `eligible_for_acceptance_decision: true`, `accepted: false` (`acc-wt-cp-50631159….json`, recorded as this attempt's evidence) |
| Agent Environment | unchanged at `c20f5397`; the projection document is unchanged |
| packet 10 | `b68e6e827afbeba3364c8239a2d814a60372f498` unchanged, READY and ACCEPTED in the store; landed only after this candidate is READY |

## Diff scope

`git diff --stat 692999fc..50631159`: 3 files, 101 insertions, 22 deletions — `app/orchestrator/lifecycle.py` (+42/−22 within `journal_preconditions` and `git_journal`, plus the porcelain parser), `tests/test_lifecycle_kernel.py` (+56), `docs/product-memory/ENGINEERING_LIFECYCLE_PRODUCERS.md` (two bullets). Untouched: the CLI, the gates, the owner judgment modules, the owner-authority policy of packet 12 (`resume`, `cancel_attempt`, `block`, `create_task`, `verify_owner_judgment_binding` and `gate_proposal` are byte-identical), the lifecycle architecture, the Agent Environment, routing and product semantics.

## The two findings, each with its mechanism and its test

| Finding | Mechanism at 50631159 | Test |
| --- | --- | --- |
| **K-12** the lock exemption matched by suffix | `journal_preconditions()` reads `git status --porcelain -z --untracked-files=all -- <store>` and `git diff --cached --name-only -z`, parsed NUL-terminated (`_porcelain_entries`: one `(status, path)` per entry, a rename's original path skipped), and exempts exactly one path: `<store>/.kernel.lock` computed relative to the checkout's toplevel (`os.path.relpath` of the resolved paths). Nothing else under the store is exempt, whatever it is called. | `test_a_stray_file_named_like_the_lock_is_not_exempt_from_the_journal_preconditions` (real repository): `engineering/evil.kernel.lock` and `engineering/attempts/.kernel.lock` are each refused before any write, naming the path; each stays untracked (`?? …` in the porcelain, never staged); HEAD, the index and the task state are unchanged; removed, the verb commits; the layout's own `engineering/.kernel.lock` is tracked and stays exempt. |
| **K-13** the clean check is point-in-time; the commit took the whole index | The journal commit is scoped to the store: `git commit -q -m <msg> -- <store>` after `git add -A -- <store>`. Git's pathspec commit records the store's paths and nothing else; index state another process staged after the precondition can neither enter the kernel's commit nor be consumed by it, it stays staged exactly as that process left it. The precondition remains the early fail-closed check (a clean index before the verb), and the rollback (`git reset HEAD -- <store>`) still touches store paths only. No new transaction mechanism. | `test_the_journal_commit_is_scoped_to_the_store_so_a_change_staged_mid_verb_is_neither_committed_nor_consumed` (real repository, deterministic through the `on_validated` seam, which runs after the precondition and before the writes): an outside `notes.txt` is written and staged mid-verb; the verb commits; `git show --name-only HEAD` lists only `engineering/` paths and not `notes.txt`; `git diff --cached --name-only` still shows `notes.txt` (left staged, not consumed); the store is clean; the next verb's precondition names `notes.txt`; once it is committed, the next verb runs. The K-08 hook test and the K-11 precondition test are unchanged and pass. |

`tests/test_lifecycle_kernel.py` 52 passed; with the projection, route, control-plane and judgment suites 153 passed.

## Reviewer checklist

1. SHA resolves; parent 692999fc; tree clean; `git diff 692999fc 50631159 --stat` is the three files above; `git diff 692999fc 50631159 -- scripts/engineering_kernel.py` is empty.
2. `python -m pytest tests/test_lifecycle_kernel.py -q` → 52 passed. Then try: a store path with a space or a newline in its name (`-z` handles it); a stray file exactly named `.kernel.lock` at the store root while the real one is absent (it *is* the lock file's path, and the layout would create it there anyway); a staged rename outside the store mid-verb (still not committed); an outside path staged *before* the verb (refused by the precondition, as before).
3. Confirm the commit command carries the pathspec (`"commit", "-q", "-m", message, "--", str(root)`) and that `git add` is still scoped to the store.
4. Decide the judgement calls below.

## Known risks and judgement calls

1. **The precondition stays repository-wide** even though the scoped commit makes an outside staged change harmless to the commit: the kernel refuses to work on a checkout being used for something else rather than silently working around it. Relaxable to store-only if you prefer.
2. **A pathspec commit is a partial commit**: git builds it from the working tree of the matched paths, which the preceding `git add -A -- <store>` has made identical to the index for the store. A store path changed by another process between the `add` and the `commit` would be committed as it is in the working tree; the store is the kernel's under the writer lock, and other processes writing into it are outside the model, as before.
3. **Records written this round by the 692999fc kernel** (the packet 12 admission, r5's task, assignment, acknowledgement and heartbeat) went through the K-11 preconditions on a clean checkout; the K-12 and K-13 paths were not exercised by them. r5's evidence, candidate and dispatch are written by 50631159 itself.
4. As before: the writer lock is filesystem-scoped; the `on_validated` seam is a no-op in production; owner gates are unresolvable by this kernel.

## After acceptance

`integrate --task-id control-plane-producers --revision 5 --integration-sha 50631159… --target-base-sha 692999fc… --method fast_forward --verify-remote origin` → DONE, rendered COMPLETE. Then packet 10's accepted candidate b68e6e82 is landed on the CI stream (fast-forward from 6b7c43d2, re-checked at the time), its integration recorded, and the recovery/integration sequence reported closed. Nothing deploys; no watcher, systemd, runtime or business write.
