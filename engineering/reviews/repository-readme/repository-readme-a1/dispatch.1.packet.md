# EXACT-SHA GPT REVIEW PACKET 19 — Repository documentation: root README and current truth (repository-readme r1, product-memory-truth r2)

Generated 2026-09-23 11:55Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. Documentation only, under the owner's instruction of 2026-09-23 (session message 15): "Update the root README and the relevant current-truth/status documentation so the repository presents CLIVE accurately. Docs only. Do not change code, runtime, branches, deployment, lifecycle/kernel behaviour, or default branch settings. Preserve history; do not rewrite old design documents." Two candidates because the root README lives on the theme-only default branch and the product memory lives on the application line; the README text is byte-identical in both.

## Identity

| Field | Candidate A — root README | Candidate B — product memory |
| --- | --- | --- |
| candidate_sha | `40e6bc6d0fa8328067e60e3a805f001d946e04fb` | `5d12aa5e9ef92e5aee5a7ba40242557e7587deb7` |
| branch (head == candidate when written) | `claude/repository-readme-2026-09-23` | `claude/product-memory-truth-2026-09-23` (r2 workspace branch `…-r2`, same head) |
| base | `c7988fa4cbcff8b7079a578d19563e26a293f93e`, the default branch `claude/shopify-theme-dev-setup-934mht` (theme only, no `crooks-assistant/`) | `3ed0fd1e2f1bc5dc6a2d3abb3d1e88ed19172f56`, GPT's `chatgpt/product-memory-reconcile-2026-09-23` (the 2026-09-23 reconciliation), two commits: `a0ef89b4` (r1, content) then `5d12aa5e` (r2, structure repairs); preserved, not rewritten |
| kernel task | `repository-readme` r1, attempt a1, token 1 | `product-memory-truth` r2, attempt a2, token 2 (r1 OBSOLETE: superseded when the structure checker found a defect in `DECISIONS.md`, outside r1's allowed paths) |
| author_principal | claude | claude (on a GPT-authored base; this packet reviews only the two commits above and does not launder the base) |
| review_state | NOT_REVIEWED | NOT_REVIEWED |
| ci_state | none: the theme branch has no workflow | none: the reconciliation base predates the `acceptance` workflow; the CI stream's product-memory structure gate was run by hand over this branch (evidence below) |
| evidence | `docs_review` (`evidence-docs-review.json`, sha256 `4606d078b6726264054950d386299129e4f76deddcf6553d260f5de506f2227c`) | `docs_structure` (`evidence-docs-structure-5d12aa5e.json`, sha256 `6b79a1884d7c18c1985199d6908e215cccc2978755c1a67e6c6ea34aedf375a7`: ok, 23 documents, 0 violations) and the same `docs_review` |
| diff scope | `README.md` only (+50/−2 after the theme text is kept verbatim under its own heading) | `README.md`, `CURRENT_TRUTH.md`, `FEATURES.md`, `RECONCILIATION_2026-09-23.md`, product-memory `README.md`, `DECISIONS.md`; no non-`.md` path |

## What changed and why

**Root README (both candidates, identical bytes).** The old README described only the Shopify theme. The new one says what the repository holds (the theme at the root; CLIVE, the CROOKS Assistant application, under `crooks-assistant/` on the application branches, not on the default branch), where the truth lives (product memory read by explicit ref from the reconciled branch; `clive/engineering-state` for the kernel's records; `crooks-ai-bridge`), a branch map with exact heads as of 2026-09-23, what is and is not deployed (DEC-048's `1cf3a0f3…` is the recorded deployment; nothing accepted since has been deployed; a green run or a COMPLETE task is not a deployment; nothing in the repository writes on its own), and how engineering work moves through the frozen kernel. The theme instructions are kept verbatim under "Shopify theme" (headings demoted one level). Branch-map facts were checked against git: `1958b327` is in the CI stream; `ef3d08ff` and `84e12e77` are not (the map says so).

**CURRENT_TRUTH.md (B).** On top of GPT's 2026-09-23 checkpoint: (1) the one stale bullet ("Revision 3 / attempt a3 is currently BUILDING") is brought to the closure, in place; (2) a dated "Engineering state — 2026-09-23 11:12Z" section is inserted before "Product": the kernel task table with exact accepted SHAs and integration targets, Support Investigator V1 as accepted after packets 15–18 and what remains the owner's, the capability gaps the dogfood recorded, where each product-memory document lives (the split across branches stated plainly), what is not authorised, and the next capability unchanged from the reconciliation's §16; (3) a dated note at the head of "Current near-term order" pointing at §15–§16 of the reconciliation without deleting the 2026-09-19/21 list; (4) the "Long-horizon adaptation doctrine" section, which the base carried as one 1,644-character line with thirteen literal `\n` escapes, is restored to the paragraphs those escapes stood for (the same class of corruption the structure gate exists to catch; the stream fixed its own copy on 2026-09-22).

**FEATURES.md (B).** Last-consolidated line updated; FEAT-010/012/014 read from DEC-048 and the reconciled control-plane state (deployment ratified, tailnet HTTPS active, watcher installed and pinned); FEAT-011 notes Gmail OAuth still outstanding; five rows added (FEAT-033 lifecycle kernel, FEAT-034 judgment ledger and CI provenance, FEAT-035 Agent Environment state, FEAT-036 Support Investigator V1, FEAT-037 Live Experience V0.5), each TESTING or BUILDING with the exact SHA and what is pending; none SHIPPED, because nothing is deployed.

**RECONCILIATION_2026-09-23.md (B).** An appended, dated "18. Closure addendum — 2026-09-23 11:12Z" (the S-01 → S-01R → S-01C convergence, packet 18 READY, the integration, what was not authorised, the next capability). Nothing above it changed.

**Product-memory README.md (B).** The canonical-ref sentence now names the reconciled branch as the ref to read (foundation as the 2026-09-21 base) and the two documents that live on the branches that produced them. Structure repairs: one collapsed index line (two entries joined by a literal `\n`) split; the three documents present on this line but unlinked from the index (`ENGINEERING_STACK_REUSE_PLAN.md`, `HARNESS_ACCEPTANCE_2C2B0CC.md`, `OWNER_DECISION_PACKET_2026-09-21.md`) indexed, the first two with the CI stream's own wording.

**DECISIONS.md (B, r2 only).** One collapsed line (DEC-051's consequences paragraph, the `---` rule and the DEC-052 heading joined by three literal `\n` escapes) restored to line breaks. No decision wording changed: the diff, ignoring whitespace, is those line breaks (`decisions_md_change_is_escapes_only: true` in the evidence).

## Reviewer checklist

1. Both SHAs resolve; A's parent is the default branch head `c7988fa4`; B's lineage is `3ed0fd1e → a0ef89b4 → 5d12aa5e`; both trees clean; `git diff --name-only` is exactly the paths above and every one ends in `.md`.
2. `README.md` at A and at B are byte-identical; the theme section is the old README verbatim with headings demoted.
3. Every claim in the branch map and the engineering-state section is a git fact or a kernel record: check the heads (`git rev-parse origin/<branch>`), the ancestry statements, and the task states on `clive/engineering-state` (`ACTIVE_STATE.json`, `integrations/`).
4. `python scripts/product_memory_check.py --json --docs <B's docs/product-memory>` from the CI stream's script → ok, 0 violations (the base has 6). Read the restored DEC-051/DEC-052 boundary and the restored "Long-horizon adaptation doctrine" against the base and confirm only line breaks changed.
5. Nothing in either candidate changes code, tests, workflows, configuration, runtime, branch structure or the default-branch setting; no design document was rewritten (the reconciliation received an appended addendum only; the handoff, already superseded, is untouched).

## Known risks and judgement calls

1. **Where the README lands is the owner's.** A is based on the default branch so it can be fast-forwarded there; B carries the same README so the application line reads the same. Neither packet nor verdict lands anything on the default branch or on GPT's reconciliation branch; the kernel integrates each candidate only into its own task branch.
2. **Product memory remains split across branches** (reconciliation line, kernel branch, support branch, CI stream). The documents now say so instead of implying one canonical tree; merging them is a separate task.
3. **FEATURES statuses use the register's own model** (nothing accepted-in-repository is SHIPPED until deployed and verified); FEAT-010/012/014 statuses restate DEC-048 and the reconciled control-plane text rather than a fresh runtime observation from this session.
4. **DECISIONS.md was touched only mechanically**, under a recorded scope widening (r2); the wording of every decision is unchanged.

## After acceptance

`integrate --task-id repository-readme --revision 1 --integration-sha 40e6bc6d… --target-base-sha c7988fa4… --method fast_forward --verify-remote origin` and `integrate --task-id product-memory-truth --revision 2 --integration-sha 5d12aa5e… --target-base-sha 3ed0fd1e… --method fast_forward --verify-remote origin`, each into its own task branch → DONE, rendered COMPLETE. Fast-forwarding the default branch to A, and GPT's reconciliation branch (or the CI stream) to B, are the owner's decisions, stated as such. Nothing deploys; no watcher, systemd, runtime, secret, permission or business write.
