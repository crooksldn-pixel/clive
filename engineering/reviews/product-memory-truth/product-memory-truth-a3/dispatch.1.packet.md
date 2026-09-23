# EXACT-SHA GPT REVIEW PACKET 20 — Product memory repair PM-01, PM-02 (product-memory-truth r3)

Generated 2026-09-23T11:37:59Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. Documentation only: one successor commit to the packet-19 candidate B (`5d12aa5e`), the two findings repaired, nothing else touched. Candidate A of packet 19 (`40e6bc6d`, the root README) was READY and is COMPLETE in the kernel; the GitHub default branch was not touched.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `4a4633767e15120f9edea275f3cb646177496995` |
| branch (head == candidate when written) | `claude/product-memory-truth-2026-09-23` (r3 workspace branch `…-r3`, same head) |
| base / parent | task base `3ed0fd1e2f1bc5dc6a2d3abb3d1e88ed19172f56` (GPT's 2026-09-23 reconciliation); parent `5d12aa5e9ef92e5aee5a7ba40242557e7587deb7` (packet 19 B, CHANGES REQUIRED; preserved) |
| kernel task | `product-memory-truth` r3 (kind repair), attempt a3, token 3; the packet-19 verdict is admitted against r2's attempt a2 (`rejected_by_verdict`), r2 OBSOLETE |
| author_principal | claude |
| review_state | NOT_REVIEWED |
| ci_state | none (the reconciliation base predates the workflow); the CI stream's structure checker run by hand: ok, 23 documents, 0 violations (`evidence-docs-structure-4a463376.json`, sha256 `6b79a1884d7c18c1985199d6908e215cccc2978755c1a67e6c6ea34aedf375a7`) |
| review evidence | `evidence-docs-review-4a463376.json`, sha256 `b84f7786bea40d89205a8845a79caf51db702b1e9061d2b19383fa00b295da75` |
| diff scope vs `5d12aa5e` | `FEATURES.md` (+6/−6) and `CURRENT_TRUTH.md` (+5/−1); `DECISIONS.md` unchanged since packet 19 |

## The findings, their repair and its check

| Finding | Repair at `4a463376` | Check |
| --- | --- | --- |
| **PM-01** the five added rows reused FEAT-033…037 | The five rows take FEAT-055…059 (the next unused identifiers after FEAT-054) and sit after FEAT-054; the pre-existing FEAT-033…037 rows (anticipation engine, scene compiler, staff roles, nightly observer, replay framework) and every other pre-existing row are byte-identical to the base except FEAT-010/011/012/014, which packet 19 already re-read from DEC-048. The "last consolidated" line names FEAT-055…059 as added. | `evidence-docs-review`: 59 identifiers, 59 unique, no duplicates; base rows 54, candidate rows 59; pre-existing rows unchanged except the four named. |
| **PM-02** "The root README on every branch carries the branch map." | Replaced by: "The updated repository README carries the branch map on the branches where this documentation update has landed (`claude/repository-readme-2026-09-23`, based on the default branch, and `claude/product-memory-truth-2026-09-23`); every other branch, including the CI stream, the kernel branch and the support branch, still carries the older theme-only README until the owner lands the update there." | The old sentence is absent; the bounded one present. |
| Checker limitation | Recorded as backlog in CURRENT_TRUTH's engineering-state section ("Backlog recorded by this documentation round"): the structure checker does not check feature-identifier uniqueness; PM-01 was caught by review, not by the gate; adding the assertion is a small code change for a later bounded task, not part of this documentation update. | Present in the candidate; no code touched. |

Rerun after the repair: structure checker 0 violations; literal `\n` rescan 0 in every changed document; no non-`.md` path changed anywhere in the lineage.

## Reviewer checklist

1. SHA resolves; lineage `3ed0fd1e → a0ef89b4 → 5d12aa5e → 4a463376`; `git diff --name-only 5d12aa5e 4a463376` is the two files above.
2. `grep -o "^| FEAT-[0-9]*" FEATURES.md | sort | uniq -d` is empty; the FEAT-033…037 lines equal the base's.
3. The bounded README sentence; the backlog line; nothing else in `CURRENT_TRUTH.md` changed since packet 19.

## After acceptance

`integrate --task-id product-memory-truth --revision 3 --integration-sha 4a463376… --target-base-sha 3ed0fd1e… --method fast_forward --verify-remote origin` into the task branch → DONE, rendered COMPLETE. Fast-forwarding GPT's reconciliation branch, the CI stream or the default branch to either documentation candidate remains the owner's decision. Nothing deploys; no watcher, systemd, runtime, secret, permission or business write.
