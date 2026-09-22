# EXACT-SHA GPT REVIEW PACKET 5 — J-02 resolution (Judgment Ledger correction identity)

Generated 2026-09-22 21:25Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. The previous verdicts on 1ec236a (J-01) and 2a08f456 (J-02) do not transfer; this is a fresh review of a new SHA.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `1958b3272e42a2608dfbd957ccf249c720af8332` |
| branch (head == candidate when written) | `claude/clive-recovery-handoff-pwuuse` |
| parent / previous candidate | `2a08f456847bc71061483448aaa45859cde29f3d` (preserved; packet 2 and its J-02 verdict stand as records) |
| author_principal | claude |
| review_state | NOT_REVIEWED |
| ci_state | PASS — run 35785557523, https://github.com/crooksldn-pixel/clive/actions/runs/35785557523, 2026-09-22T21:15:53Z to 21:19:28Z, all five gates green |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha 1958b327… --suite full`, Python 3.12.3, gitleaks 8.30.1, clean tree: ruff pass; pytest_control_plane 44 passed; product_memory_structure pass; pytest_offline_full 3029 passed, 8 skipped, 2 deselected; secret_scan no leaks. `eligible_for_acceptance_decision: true`, `accepted: false`, `independent_review: required` (`acceptance-1958b327….json`) |

Verify: `git rev-parse origin/claude/clive-recovery-handoff-pwuuse` → `1958b3272e42a2608dfbd957ccf249c720af8332`; `git log --format=%P -1 1958b327…` → `2a08f456847bc71061483448aaa45859cde29f3d`.

## Purpose (J-02)

The review of 2a08f456 found that `JudgmentRecord` carries `task_revision` and `attempt_id` while `_check_correction()` bound a correction only to `proposal_id`, `proposal_fingerprint`, `action_id` and `task_id`, so a correction could silently move an owner's judgment between task revisions or attempts under one proposal id.

**Doctrine check before building.** Searched every product-memory document and the phase docs for a correction model across revisions or attempts: none exists. The Judgment Ledger contract and the durable judgment-events decision ask for corrections and say nothing about moving them; DEV_TEAM_V1_PILOT.md ("corrections create a new candidate") and ENGINEERING_ORCHESTRATOR_V1.md speak of engineering candidates, not owner judgments. With no doctrine defining a different model, the ledger fails closed.

**Resolution.** A correction must carry exactly the `task_revision` and `attempt_id` of the entry it corrects, each present or absent as there. Changing, adding or dropping either is refused; the message names both identities; the ledger is left unchanged. Because every link of a chain must match its own target, identity cannot drift across a chain. The check lives in the ledger (it needs the target), between the proposal-identity check and the already-corrected check.

## Diff scope

`git diff --stat 2a08f456…..1958b327…`: 3 files, 118 insertions, 5 deletions.

- `crooks-assistant/app/actions/judgment_ledger.py` (+22/−3): module docstring states the rule; `_check_correction` gains the revision/attempt check and its docstring.
- `crooks-assistant/docs/product-memory/JUDGMENT_LEDGER_CONTRACT.md` (+5/−2): append-only paragraph, invariant 11, required-tests line.
- `crooks-assistant/tests/test_judgment_ledger.py` (+96): nine tests — changed, dropped and added `task_revision`; changed, dropped and added `attempt_id`; positive control at a matching revision and attempt (original preserved, correction effective, identity carried); chain drift refused on revision, on attempt and on a dropped attempt, then accepted when matching; a refusal names both identities and moves nothing.

Nothing else: no construction rule (`validate_judgment`), no eligibility, fencing or stale-result rule, no other module.

## Reviewer checklist

1. SHA resolves; parent is 2a08f456; tree clean.
2. Read `_check_correction` in full: identity check → **revision/attempt check** → already-corrected → predate → changes-nothing. Confirm `None` on both sides passes and any asymmetry refuses.
3. `python -m pytest tests/test_judgment.py tests/test_judgment_construction.py tests/test_judgment_ledger.py -q` → 73 passed (64 before).
4. Confirm the contract's wording matches the code exactly (no promise the code does not keep, no rule the contract omits).
5. Decide the judgement calls below.

## Known risks and judgement calls to challenge

1. **Strictness.** A correction that adds a revision to a judgment made without one is refused. That is deliberate (fail closed, no doctrine for the move); relaxing it would need a doctrine decision first.
2. **Message content.** The refusal names both revision numbers and both attempt ids. These are identifiers, not owner content; nothing else is included.
3. **Both absent passes.** `None == None` is accepted, so judgments made without revision or attempt can still be corrected at that same (absent) identity.
4. **No migration.** No persisted ledger exists anywhere, so the stricter rule has nothing to invalidate.
5. **Stream interaction.** The GPT stream's `judgment_chain.py` hashes the whole record, identity fields included, and is unaffected. A dry-run merge of the previous candidate into the stream head 6b7c43d was conflict-free; the three files here do not overlap the stream's additions.

## After acceptance

Task 12 (integration into `claude/ci-provenance-acceptance-2026-09-22`) is prepared and owner-authorised; it waits on this verdict. Nothing here deploys.
