# EXACT-SHA GPT REVIEW PACKET 2 — J-01 resolved: judgment corrections

Generated 2026-09-22 by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**, per `crooks-assistant/config/review_principals.json` at `e9b5da1094f39f6f29462714a9e30955800e0fd8`.
The review of 1ec236a does not transfer; this is a fresh candidate.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `2a08f456847bc71061483448aaa45859cde29f3d` |
| branch | `claude/clive-recovery-handoff-pwuuse` (head == candidate when this packet was written) |
| base_sha | `1ec236a1d2a96ec9c39f69cdac4937db31e2bd85` (the previous candidate, reviewed CHANGES REQUIRED with one finding, J-01; preserved unchanged in history, its CI evidence is run 35771824941) |
| stream base | `b1897a6f12a6e87853547fcc3b83d6bc2881797f`. The stream branch has since moved to `1075476e8ded583ca94111e1eeec839ec47781b8` (GPT, two commits at 19:43Z, CI FAIL run 35775627123, tenth consecutive failure), so integration is now a merge, not a fast-forward; see risk 6 |
| author_principal | claude |
| assigned_reviewer | gpt |
| review_state | NOT_REVIEWED |
| ci_state | PASS — run 35775765664, https://github.com/crooksldn-pixel/clive/actions/runs/35775765664, completed 2026-09-22T19:48:19Z, artifact `acceptance-2a08f456847bc71061483448aaa45859cde29f3d` |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha 2a08f456847bc71061483448aaa45859cde29f3d --suite full`, Python 3.12.3, gitleaks 8.30.1, clean tree: 5/5 gates pass. ruff 0; pytest_control_plane 44 passed; product_memory_structure ok (23 documents); pytest_offline_full 3020 passed, 8 skipped, 2 deselected; secret_scan no leaks (5 baseline-suppressed fixtures). |

Verify identity before reading anything else:

```
git fetch origin claude/clive-recovery-handoff-pwuuse
git rev-parse origin/claude/clive-recovery-handoff-pwuuse    # must print 2a08f456847bc71061483448aaa45859cde29f3d
git rev-parse 2a08f456847bc71061483448aaa45859cde29f3d~1                                          # must print 1ec236a1d2a96ec9c39f69cdac4937db31e2bd85
```

## The commit (one, Claude-authored)

`2a08f456847bc71061483448aaa45859cde29f3d` J-01: a correction is a new judgment that names the one it corrects, and touches nothing

## Finding J-01, and the evidence question first

J-01: the contract promised corrections as new entries referencing the prior judgment; no field and no ledger rule could express one. Before building it, whether V1 requires it was checked, because the alternative resolution was to reconcile the contract. Result: no document on the candidate tree, on `claude/recovery-handoff-2026-09-22` (e9b5da10), on `chatgpt/capability-registry-reconciliation-2026-09-22` (6a522f8f) or on `claude/product-memory-foundation` (8d6b1112) defers judgment corrections beyond V1. The only Judgment Ledger doctrine outside the contract is DECISIONS.md's durable redacted judgment-events decision on the two product-memory branches, which asks for the mechanism and limits nothing. Engineering-side doctrine on "corrections" (ENGINEERING_ORCHESTRATOR_V1.md, DEV_TEAM_V1_PILOT.md) is about candidate repairs, a different concept. The contract's own text requires corrections in V1, so they are implemented, narrowly.

Reproducible: `git grep -n -i "correction" <ref> -- 'crooks-assistant/docs/product-memory/*.md'` on each of the four refs.

## What was built

**JudgmentRecord.corrects_judgment_id** (optional). At construction: non-blank if given; a record may not correct itself. Nothing else about the record changed.

**JudgmentLedger.append**, when the record carries the reference, checks in one place, in this order, each fail-closed:
1. the referenced judgment exists in this ledger ("does not hold");
2. it judges the same proposal_id, proposal_fingerprint, action_id and task_id ("same proposal");
3. it is the current judgment for that proposal, i.e. no entry already corrects it ("already corrected"), so corrections chain through the latest one and two effective judgments can never coexist;
4. the correction does not predate it ("predate");
5. it changes at least one of decision, reason_code, superseding_proposal_id, replacement_fingerprint, redacted_explanation ("changes nothing"), because a correction that repeats the judgment is a replay wearing a new id.
Then the existing rules run unchanged: duplicate id replay and id collision are refused; a proposal_id reappearing with a different fingerprint is refused; a same-fingerprint reappearance without a correction reference is refused exactly as before. The corrected entry is kept byte for byte.

**Queries** added: `by_id`, `correction_of`, `effective_judgments` (entries no later entry corrects: one per judged proposal), `effective_judgment_for(proposal_id)`.

**Contract**: the field is named in the entry list; the append-only paragraph states the rules; invariant 11 added; the required-tests list gains the correction case.

**Tests**: 3 construction tests (self-correction refused, blank reference refused, reference carried) and 10 ledger tests (original preserved byte for byte, effective judgment is the correction, missing target, same-proposal/action/task mismatch, already-corrected target, chaining through the current judgment, predating, unchanged, replayed correction, a correction that is itself an EDITED judgment with its own replacement).

## Diff scope (`git diff --stat 1ec236a1d2a96ec9c39f69cdac4937db31e2bd85..2a08f456847bc71061483448aaa45859cde29f3d`)

     crooks-assistant/app/actions/judgment.py           |   8 ++
     crooks-assistant/app/actions/judgment_ledger.py    | 111 ++++++++++++++++++---
     .../product-memory/JUDGMENT_LEDGER_CONTRACT.md     |   5 +-
     .../tests/test_judgment_construction.py            |  14 +++
     crooks-assistant/tests/test_judgment_ledger.py     | 108 +++++++++++++++++++-
     5 files changed, 232 insertions(+), 14 deletions(-)

Untouched: `app/orchestrator/routing.py`, `review_acceptance.py`, `review_result_gate.py`, every review test, every product-memory document except JUDGMENT_LEDGER_CONTRACT.md. No Ineligibility member, provenance rule, candidate fence, stale-result check or owner-authority boundary changed.

## Reviewer checklist

1. `git rev-parse HEAD` == candidate; tree clean.
2. `git diff 1ec236a1d2a96ec9c39f69cdac4937db31e2bd85..HEAD --stat` matches the five files above; `git diff 1ec236a1d2a96ec9c39f69cdac4937db31e2bd85..HEAD -- crooks-assistant/app/orchestrator` is empty.
3. In crooks-assistant/: `python -m pytest tests/test_judgment.py tests/test_judgment_construction.py tests/test_judgment_ledger.py -q` (expect 65 passed); ruff and the product-memory checker clean.
4. Confirm CI artifact `acceptance-2a08f456847bc71061483448aaa45859cde29f3d.json` (run 35775765664) reports this SHA, clean worktree, `unsatisfied_gates: []`.
5. Decide each risk below.

## Known risks and judgement calls to challenge

1. Correction identity is checked against proposal_id, proposal_fingerprint, action_id and task_id but not task_revision or attempt_id (both optional on the record). A correction may therefore carry a different revision or attempt than the entry it corrects. Judged acceptable because the proposal identity is what the judgment binds to; challenge it if you disagree.
2. "Changes nothing" compares five content fields. A correction differing only in provenance (a different owner session re-affirming the same decision) is refused as a replay. Deliberate; challenge if re-affirmation should be recordable.
3. Timestamps are owner-supplied. The "cannot predate" rule uses `decided_at`; append order is the only ordering the ledger itself guarantees.
4. No `corrects_judgment_id` on the record is validated against the ledger at construction, only at append. A record can exist that references a judgment no ledger holds; it cannot be appended. Consistent with the module split (record invariants vs. ledger invariants).
5. The ledger remains in-memory and unpersisted, as before; nothing here changes storage.
6. CORRECTED after first issue. The hourly GPT committer is still running: at 19:43Z it pushed two commits. `ed01699d4f7896ec6ffc01323fa717c331164d63` adds `app/actions/judgment_chain.py` (68 lines: `ChainedJudgment` with `previous_hash`/`entry_hash`, `judgment_entry_hash`, `chain_ledger`, `verify_chain`, a tamper-evident hash chain over the ledger). `1075476e` adds `tests/test_judgment_chain.py` for it. An earlier version of this packet said the module existed nowhere; that was wrong, I had inspected only the second of the two commits. What is true: the test builds records with `reason_code="ACCEPT_AS_PROPOSED"`, `OwnerProvenance(principal_id, source)` and a string `decided_at`, i.e. the stream's pre-candidate judgment API, so neither file can be merged onto this candidate as is; the chain would have to be ported to the reconciled record (enum reason codes, session provenance, aware datetimes, and the correction reference). Both commits are GPT-authored and need a non-GPT reviewer. This candidate includes neither; integration into the stream is now a merge with that port on its GPT-authored side, and the committer should be paused.

## After acceptance

Integration target `claude/ci-provenance-acceptance-2026-09-22`, now owner-authorised. Because the stream moved to 1075476e after this candidate was cut, integration is a merge; the merge commit is itself a candidate for the acceptance run, and the stream's two chain commits will have to be ported to the reconciled judgment record in it, which is design work and not part of this packet. Nothing here implies deployment.
