# EXACT-SHA GPT REVIEW PACKET 21 — Product memory repair PM-03, PM-04 (product-memory-truth r4)

Generated 2026-09-23T11:51:12Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. Documentation only: one successor commit to the packet-20 candidate (`4a463376`), the two findings repaired, nothing else touched; PM-01, PM-02 and the packet-19 mechanical repairs preserved.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `07459b85df00f806d641d924499a207ad41cbe8b` |
| branch (head == candidate when written) | `claude/product-memory-truth-2026-09-23` (r4 workspace branch `…-r4`, same head) |
| base / parent | task base `3ed0fd1e2f1bc5dc6a2d3abb3d1e88ed19172f56`; parent `4a4633767e15120f9edea275f3cb646177496995` (packet 20, CHANGES REQUIRED; preserved) |
| kernel task | `product-memory-truth` r4 (kind repair), attempt a4, token 4; the packet-20 verdict is admitted against r3's attempt a3 (`rejected_by_verdict`), r3 OBSOLETE |
| author_principal | claude |
| review_state | NOT_REVIEWED |
| ci_state | none (the reconciliation base predates the workflow); the CI stream's structure checker run by hand: ok, 0 violations (`evidence-docs-structure-07459b85.json`, sha256 `6b79a1884d7c18c1985199d6908e215cccc2978755c1a67e6c6ea34aedf375a7`) |
| review evidence | `evidence-docs-review-07459b85.json`, sha256 `ef131c5360d4ad7ef16870faa2853dce959cbebdf5b6b6938a17c20ce3066536` |
| diff scope vs `4a463376` | `CURRENT_TRUTH.md` (+2/−2) and `FEATURES.md` (+1/−1); nothing else in the lineage since packet 20 |

## The findings and their repair

| Finding | Repair at `07459b85` | Check |
| --- | --- | --- |
| **PM-03** the watcher was documented as running `claude-fable-5-1` at high effort, contradicting the 2026-09-23 live probe | In both places the wording now distinguishes the reviewed source from the observed runtime: reviewed source revision `5ada7b47…` pins the installer's runtime to `claude-fable-5-1` at high effort, but the most recent verified live probe (a read-only live-host review on 2026-09-23, reported in the packet-20 review verdict relayed by the owner) found the loaded systemd unit, with no drop-ins, carrying `Environment=CROOKS_BRIDGE_CLAUDE_MODEL=claude-opus-5`; runtime truth comes from probes, not from the document or the register, and the model and effort in force are whatever the next probe shows. CURRENT_TRUTH adds that the discrepancy between the reviewed source and the loaded unit is an open observation, not resolved here, and the "verified deterministic baseline" clause now says the baseline is whatever the latest probe establishes. No manufactured current claim beyond that probe; nothing about the watcher, unit, model or configuration changed. | The stale claim is absent from both files; the probe appears once in each with its date and provenance; the "runtime truth comes from probes" sentence is present in both. |
| **PM-04** the active opening checkpoint still said the support dogfood was underway | That bullet now reads: the first real Crooks operational dogfood, read-only Customer Support Investigator V1, is COMPLETE in the engineering lifecycle at `2dbb97bc6c88d3ee3cf5cdf6a980df4f3405104a` (accepted and integrated 2026-09-23 11:11Z; the owner's verification of the two real cases, the first live run and any landing or deployment remain the owner's); the next engineering proof is Objective Intake + Engineering Dispatcher V1, unchanged. The historical reconciliation sections are untouched (the reconciliation document has no diff since packet 20). | The "already underway" wording is absent; the closure wording present; the reconciliation document unchanged. |

After the repair: feature identifiers 59/59 unique; structure checker 0 violations; literal `\n` rescan 0 in every changed document; no non-`.md` path anywhere in the lineage; `DECISIONS.md` unchanged since packet 19.

## Reviewer checklist

1. SHA resolves; lineage `3ed0fd1e → a0ef89b4 → 5d12aa5e → 4a463376 → 07459b85`; `git diff --name-only 4a463376 07459b85` is the two files above.
2. `grep -n "claude-fable-5-1\|claude-opus-5" FEATURES.md CURRENT_TRUTH.md`: every mention is inside the reviewed-source-versus-probe wording.
3. The opening checkpoint bullet; sections 12–17 of the reconciliation untouched.

## After acceptance

`integrate --task-id product-memory-truth --revision 4 --integration-sha 07459b85… --target-base-sha 3ed0fd1e… --method fast_forward --verify-remote origin` into the task branch → DONE, rendered COMPLETE. Fast-forwarding GPT's reconciliation branch, the CI stream or the default branch to either documentation candidate remains the owner's decision. Nothing deploys; no watcher, systemd, runtime, model, secret, permission or business write.
