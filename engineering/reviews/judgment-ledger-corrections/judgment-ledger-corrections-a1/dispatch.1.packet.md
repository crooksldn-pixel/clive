# EXACT-SHA GPT REVIEW PACKET 1 — CI/provenance stream repair

Generated 2026-09-22 by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**, per `crooks-assistant/config/review_principals.json` at
`e9b5da1094f39f6f29462714a9e30955800e0fd8` on `claude/recovery-handoff-2026-09-22`.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `1ec236a1d2a96ec9c39f69cdac4937db31e2bd85` |
| branch | `claude/clive-recovery-handoff-pwuuse` (head == candidate when this packet was written) |
| base_sha | `b1897a6f12a6e87853547fcc3b83d6bc2881797f` = head of `claude/ci-provenance-acceptance-2026-09-22` (GPT-authored, CI red: run 35768944912, ninth consecutive failure) |
| author_principal | claude |
| assigned_reviewer | gpt (eligible: gpt authored the base, not these four commits) |
| review_state | NOT_REVIEWED |
| ci_state | PASS — run 35771824941, https://github.com/crooksldn-pixel/clive/actions/runs/35771824941, completed 2026-09-22T19:12:03Z, artifact `acceptance-1ec236a1d2a96ec9c39f69cdac4937db31e2bd85` |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha 1ec236a1d2a96ec9c39f69cdac4937db31e2bd85 --suite full` on Python 3.12.3 with gitleaks 8.30.1, clean tree: 5/5 gates pass. ruff 0 findings; pytest_control_plane 44 passed; product_memory_structure ok (23 documents); pytest_offline_full 3007 passed, 8 skipped, 2 deselected; secret_scan no leaks (5 baseline-suppressed fixtures). |

Verify identity before reading anything else:

```
git fetch origin claude/clive-recovery-handoff-pwuuse
git rev-parse origin/claude/clive-recovery-handoff-pwuuse     # must print 1ec236a1d2a96ec9c39f69cdac4937db31e2bd85
git merge-base 1ec236a1d2a96ec9c39f69cdac4937db31e2bd85 b1897a6f12a6e87853547fcc3b83d6bc2881797f  # must print b1897a6...
```

## Commits, base → candidate (all Claude-authored, in order)

1. `eb1e75056571c2e0a54003277fb422a1c17262d3` Two product-memory documents indexed, one of them moved to where the index can see it
2. `5f60642271e1245ca848f5429646e893bbfcaf3c` Judgment records that cannot exist in an invalid state
3. `a67349503a3eb9e22f4b258b049858fef62605af` The Judgment Ledger refuses a proposal id that comes back with different content
4. `1ec236a1d2a96ec9c39f69cdac4937db31e2bd85` Review gate tests rebuilt on the Party that routing actually defines

Only the candidate SHA is gate-green. Intermediate commits are not individually green and are not candidates.

## Purpose

Restore a green, trustworthy acceptance run on the CI/provenance stream without retriggering CI, without relaxing the reviewer-independence rule, and without inventing a second routing module. The stream had been red since 10:44Z with ten hourly GPT commits landing on it; each of the three GPT-authored test files was written against an API that the module it tests never had.

## Diff scope (`git diff --stat b1897a6..1ec236a1d2a96ec9c39f69cdac4937db31e2bd85`)

     crooks-assistant/app/actions/judgment.py           | 244 +++++++++++++++------
     crooks-assistant/app/actions/judgment_ledger.py    |  27 ++-
     .../app/orchestrator/review_acceptance.py          |   2 +-
     .../product-memory/JUDGMENT_LEDGER_CONTRACT.md     |   2 +-
     crooks-assistant/docs/product-memory/README.md     |   2 +
     .../product-memory/REVIEW_ACCEPTANCE_CONTRACT.md   |   0
     crooks-assistant/tests/test_judgment.py            |   3 +
     .../tests/test_judgment_construction.py            | 154 +++++++++++++
     crooks-assistant/tests/test_judgment_ledger.py     | 124 ++++++-----
     crooks-assistant/tests/test_review_acceptance.py   |  27 ++-
     crooks-assistant/tests/test_review_result_gate.py  |  78 ++++---
     11 files changed, 504 insertions(+), 159 deletions(-)

Untouched, and the reviewer should confirm it: `app/orchestrator/routing.py` (diff is 0 lines, i.e. empty). No member of `Ineligibility` was added, removed, renamed or relaxed. `review_acceptance.py` changes by one quoted annotation (numstat: 1	1	crooks-assistant/app/orchestrator/review_acceptance.py). `review_result_gate.py` is untouched.

## What the three gates were failing on, and what fixed each

| Gate at b1897a6 | Failure | Fix in this candidate | Mechanical? |
| --- | --- | --- | --- |
| ruff | 7 findings (UP035 ×2, UP037 ×3, F401, I001), all in the stream's own files | fixed in place; the two test files were rewritten anyway | yes |
| product_memory_structure | JUDGMENT_LEDGER_CONTRACT.md unindexed | one index line; REVIEW_ACCEPTANCE_CONTRACT.md was also sitting in a root-level docs/product-memory/ outside the canonical directory, so it was moved (content unchanged) and indexed | yes |
| pytest_offline_full | exit 2: two collection errors. Once collection is repaired, tests/test_review_acceptance.py fails 13/13 at runtime (hidden by the collection errors) and the b1897a6 tests/test_judgment_ledger.py cannot construct a single record | see next section | no |

## The reconciliation direction, per file (the part that needs judgement)

**tests/test_review_acceptance.py, tests/test_review_result_gate.py** — the tests were fixed, not the types.
Both built a flat Party (principal_id, session_id, workspace_id, a writable flag, model_family). `routing.Party` is principal × session × workspace, and `review_acceptance.py` already uses it correctly. The flat shape cannot carry `Workspace.head_sha`, `SessionContext.context_is_fresh` or `Workspace.clean`, so changing the types to fit the tests would have silently dropped REVIEWER_NOT_AT_CANDIDATE, STALE_CONTEXT and REVIEWER_WORKSPACE_IS_DIRTY. The fixtures now build the nested Party; every test body in test_review_acceptance.py is byte-identical to b1897a6. test_review_result_gate.py imported a module (`app.orchestrator.reviewer_routing`) that never existed; it now imports the real one. Three further changes there: `dataclasses.replace` → `model_copy` (targets are pydantic models); the author-drift case passes a second Party instead of a string the evidence model would refuse; the late-result assertion names the reason the evaluator actually emits, `current_candidate_sha_drift`, rather than a bare `candidate_sha_drift` that no code path produces.

**app/actions/judgment.py** — the module was moved toward the test, because the test was the stronger contract.
tests/test_judgment.py expected: a `ReasonCode` enum (member ACCEPTED_AS_PROPOSED), validation at construction, `OwnerProvenance(principal_id, session_id)`, `superseding_proposal_id`, and `proposal_fingerprint(bytes)`. All implemented. Additionally: (a) the previous implementation required `supersedes_proposal_id == proposal_id` for EDITED, which inverts the contract's invariants 4 and 5 (EDITED must create a *distinct* superseding proposal and must not overwrite the original) — it is now `superseding_proposal_id`, required to differ from `proposal_id`, and the contract document's field name was aligned (one line); (b) `decided_at` is a required timezone-aware datetime because the contract lists a decision timestamp — this is the one argument added to the GPT test's fixture (3 lines changed in test_judgment.py, nothing else); (c) OwnerDecision and ReasonCode are coerced from their string values at construction so records rebuilt from storage carry enum members and unknown values fail closed; (d) "chain of thought" (spaced) joins the forbidden-label list, which the GPT test already parametrised. `validate_judgment()` remains public and idempotent. Every GPT refusal test was vacuous before (the fixture could not construct a valid record), so tests/test_judgment_construction.py adds the positive control plus the invariants the adversarial file does not reach (overwrite refusal, EXPIRED/AUTO_APPROVED refusal, naive timestamp, immutability, fingerprint over mappings).

**app/actions/judgment_ledger.py** — one added refusal, plus tests it never had.
A proposal_id that reappears with a *different* fingerprint is now refused ("approval replayed against different content", contract invariant 6); previously only the exact (id, fingerprint) duplicate was. tests/test_judgment_ledger.py at b1897a6 was written against a third, mutually incompatible judgment API (ReasonCode.OWNER_CONFIRMED, OwnerProvenance(owner_id=), fields explanation / redacted_delta / superseding_proposal_fingerprint, none of which exist in the module, the contract, or GPT's own test_judgment.py). It is replaced; every invariant it set out to prove is still proved, and two more are added.

## Reviewer checklist (from a clean, read-only checkout at the exact SHA)

1. `git rev-parse HEAD` prints `1ec236a1d2a96ec9c39f69cdac4937db31e2bd85`; `git status --porcelain` is empty.
2. `git diff b1897a6..HEAD -- crooks-assistant/app/orchestrator/routing.py` is empty.
3. `git diff b1897a6..HEAD -- crooks-assistant/tests/test_review_acceptance.py` touches only the import block and the `party()` helper.
4. Run in crooks-assistant/: `python -m ruff check app config scripts tests`; `python scripts/product_memory_check.py`; `python -m pytest tests/test_judgment.py tests/test_judgment_construction.py tests/test_judgment_ledger.py tests/test_review_acceptance.py tests/test_review_result_gate.py tests/test_review_routing.py -q` (expect 155 passed); optionally the full suite on Python 3.12.
5. Confirm the CI artifact `acceptance-1ec236a1d2a96ec9c39f69cdac4937db31e2bd85.json` from run 35771824941 reports `candidate_sha` == this SHA, `clean_worktree: true`, and `unsatisfied_gates: []`.
6. Read each of the ten risks below and decide whether any is a REPAIR_REQUIRED.

## Known risks and judgement calls to challenge

1. `decided_at` made required (was optional in the GPT test's world). Contract-driven, but it is the one edit to a GPT test file.
2. EDITED semantics flipped relative to the prior implementation (`superseding_proposal_id != proposal_id` now required). Contract-driven; the contract line was edited to the implemented field name.
3. `ACCEPT_AS_PROPOSED` string → `ReasonCode.ACCEPTED_AS_PROPOSED`. No persisted ledgers exist (the ledger is in-memory only), so no migration, but it is a vocabulary rename.
4. `proposal_fingerprint(str)` now raises TypeError. API tightening; bytes or a mapping only.
5. The ledger's new refusal could reject a flow that legitimately re-presents a proposal_id with new content. The contract's immutable-proposal rule says that flow must not exist; confirm you agree.
6. The late-result test now asserts `current_candidate_sha_drift`. Confirm this is a naming correction and not a weakened check (the gate still refuses; the evaluator also emits `reviewer_ineligible:candidate_sha_drift`).
7. REVIEW_ACCEPTANCE_CONTRACT.md moved from `docs/product-memory/` (repo root) to `crooks-assistant/docs/product-memory/`. No in-tree references to the old path were found.
8. Intermediate commits are not individually green.
9. tests/test_memory.py::test_a_prefetch_that_has_not_landed_is_never_waited_for passes on Python 3.12 (CI) and fails deterministically on 3.11. Pre-existing at the base, outside this diff, not fixed here; recorded so nobody mistakes it for a flake.
10. The hourly GPT committer on `claude/ci-provenance-acceptance-2026-09-22` was still active when this packet was written (last commit 18:42Z). The candidate is pinned to its own branch, so it cannot drift; but the stream head may move again before integration, in which case integration is a merge rather than a fast-forward and the GPT-authored delta needs its own review.

## What GPT cannot review in this tree, and who can

Unchanged or near-unchanged GPT-authored files that remain unreviewed by any eligible principal: `app/orchestrator/review_acceptance.py`, `app/orchestrator/review_result_gate.py`, `docs/product-memory/REVIEW_ACCEPTANCE_CONTRACT.md`, `docs/product-memory/JUDGMENT_LEDGER_CONTRACT.md`, `tests/test_judgment.py`, and the nine GPT commits below the base. Under the symmetric rule, a **claude** principal in a fresh, read-only session at this SHA is eligible for those (different principal from their author), as is the owner. This session is not: it has a writable workspace and has now co-authored the surface.

## After acceptance

Integration target is `claude/ci-provenance-acceptance-2026-09-22`. The candidate descends from its current head, so integration is a fast-forward if the stream has not moved, otherwise a merge. This session's branch rules require explicit owner permission before it pushes to any branch other than `claude/clive-recovery-handoff-pwuuse`.

Deployment is not implied by anything here. Mechanical evidence and an independent review make the candidate eligible for integration, not for production.
