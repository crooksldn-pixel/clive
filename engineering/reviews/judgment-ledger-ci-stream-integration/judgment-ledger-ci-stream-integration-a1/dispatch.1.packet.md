# EXACT-SHA GPT REVIEW PACKET 10 — CI-stream integration candidate for the accepted judgment-ledger work (task 12)

Generated 2026-09-23 00:05Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored merge; GPT is eligible. This is an *integration candidate* in the sense of K-04: a merge result that lands more than an accepted SHA, so it completes nothing until reviewed at its own exact SHA.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `b68e6e827afbeba3364c8239a2d814a60372f498` |
| holding branch (head == candidate when written) | `claude/ci-stream-integration-judgment-2026-09-22` |
| target base | `6b7c43d29f5deb0317517eb1577e98b4b693eaf7` = the CI stream `claude/ci-provenance-acceptance-2026-09-22` head (unchanged since 20:59Z; the hourly committer has not landed since) |
| commits | `292b1bd7` merge of `1958b3272e42a2608dfbd957ccf249c720af8332` (READY in packet 5, admitted 23:39Z, integrated on its own branch) into 6b7c43d2, conflict-free, no content edits; `b68e6e82` the 15-line fixture adaptation of `tests/test_judgment_chain.py` |
| merge-base of the stream and the accepted candidate | `b1897a6` |
| kernel task | `judgment-ledger-ci-stream-integration` r1 (kind integration), on `clive/engineering-state` |
| author_principal | claude |
| review_state | NOT_REVIEWED |
| ci_state | PASS — run 35799538394, https://github.com/crooksldn-pixel/clive/actions/runs/35799538394, 2026-09-22T23:53:18Z to 23:57:00Z, all five gates green |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha b68e6e82… --suite full` at 2026-09-23T00:01:55Z, clean tree: ruff pass; pytest_control_plane 44 passed; product_memory_structure pass; pytest_offline_full 3037 passed, 8 skipped, 2 deselected in 289.89s; secret_scan no leaks; `eligible_for_acceptance_decision: true`, `accepted: false` (`acc-stream-b68e6e82….json`, recorded as the attempt's evidence) |

## What the merge lands, precisely

`git diff --stat 6b7c43d2..b68e6e82`: 12 files, 850 insertions, 167 deletions. All of it is the accepted lineage `b1897a6..1958b327` (judgment.py, judgment_ledger.py, review_acceptance.py one line, the JUDGMENT_LEDGER contract, the README index, the moved REVIEW_ACCEPTANCE_CONTRACT.md, six test files) plus the one file this candidate changes on its own:

- `tests/test_judgment_chain.py` (+11/−4): the stream's GPT-authored fixture built records for the flat `JudgmentRecord` (`OwnerProvenance` without `session_id`, `reason_code="ACCEPT_AS_PROPOSED"` where the enum member is `ACCEPTED_AS_PROPOSED`, `decided_at` as a string). With the accepted record it failed 8 of 8 on construction. Only construction changes; the assertions are untouched; `app/actions/judgment_chain.py` itself is unchanged and works with the reconciled record (chain → anchor → verify round trip; truncation, reordering and a forged hash refused).

Commands: `git diff 292b1bd7 b68e6e82` (the fixture adaptation alone); `git diff 6b7c43d2 292b1bd7 --stat` versus `git diff b1897a6 1958b327 --stat` (identical file set: the merge adds nothing of its own); `git log --format=%P -1 292b1bd7` → `6b7c43d2… 1958b327…`.

## Why this is a candidate and not a push

Under K-04 a merge result contains bytes nobody reviewed under the accepted SHA: here the stream's own commits since b1897a6 (`ed01699`, `1075476e`, `b015cb7`, `6b7c43d`, GPT-authored) and the fixture adaptation. The kernel refuses to complete a task from such a result until the result was recorded, dispatched and accepted at its exact SHA. The task's target is the holding branch it is published on (the kernel's dispatch rule requires the target head to equal the candidate); landing it on the stream is the push that acceptance authorises (owner authority of 2026-09-22, workstream 1: CI-stream integration after independent acceptance).

## Reviewer checklist

1. SHA resolves on the holding branch; parents as stated; tree clean.
2. The merge adds nothing: the three-way diff of 292b1bd7 against its parents is empty beyond the union (`git diff 292b1bd7^1 292b1bd7` equals `git diff b1897a6 1958b327` file for file; `git diff 292b1bd7^2 292b1bd7` is the stream's own commits).
3. The fixture adaptation changes construction only; read the 15 lines.
4. `python -m pytest tests/test_judgment.py tests/test_judgment_ledger.py tests/test_judgment_chain.py tests/test_judgment_construction.py tests/test_review_acceptance.py tests/test_orchestrator_control_plane.py -q` → 138 passed.
5. Decide whether the stream's GPT-authored commits need a non-GPT review before the push: this candidate does not launder them, and the packet records that they remain reviewed by no non-GPT principal.

## Known risks

1. **The stream may move.** If the hourly committer lands before the push, the candidate is stale: it is rebuilt on the new head as revision 2 and reviewed again; nothing is force-pushed.
2. **The stream's own commits are still unreviewed by a non-GPT principal.** Unchanged fact; the merge does not change it and the record says so.
3. **A GPT-authored test is edited.** The adaptation is to the reconciled record the accepted candidate defines; if you would rather the chain test be rewritten by its author, say so and the fixture commit is dropped, leaving 8 failing tests on the stream until then.

## After acceptance

`git push origin b68e6e82…:claude/ci-provenance-acceptance-2026-09-22` (a fast-forward from 6b7c43d2), then `integrate --task-id judgment-ledger-ci-stream-integration --revision 1 --integration-sha b68e6e82… --target-base-sha 6b7c43d2… --method fast_forward --verify-remote origin` → DONE; the stream head, then b68e6e82, is named in the operator string. Nothing deploys.
