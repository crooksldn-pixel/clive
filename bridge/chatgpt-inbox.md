# CHATGPT INBOX

## Bounded repair — Orchestrator V1 freeze evaluator M-01

Perform exactly one bounded repository-only repair round on the current freeze candidate.

### Exact identity
- repository: `crooksldn-pixel/clive`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- exact rejected SHA: `4f1a915421fc5324638168aa6a16fc51f5a9ee84`
- independent review verdict consumed: `REJECT — REPAIR REQUIRED`
- blocker: M-01, with M-02 reinforcement requested in the same bounded repair

Resolve refs fresh. Abort if the candidate branch is no longer exactly the rejected SHA above. Do not touch canonical product-memory documents or the freeze contract text. This is an evaluator/test-module repair only.

### Required repair
Repair the material M-01 false-green in `crooks-assistant/tests/test_orchestrator_freeze_spec.py`: a nearby backticked non-handle field can currently absorb a write verb, classify the clause as `WRITES_OTHER_FIELD`, and silently hide an operative second write to the cleanup handle. The repair must fail closed when a clause containing a live cleanup-handle referent also contains a write whose target cannot be proven to be exclusively another field. Preserve legitimate controls such as an actual write to an unrelated field and explicit read-only handle prose.

Also strengthen the independent group-creation cardinality derivation enough to cover the review's demonstrated M-02 forms, including present-tense `creates`, noun/verb ordering variants, and reasonable creation synonyms such as `instantiated`/`provisioned`, without turning broad harmless prose into automatic failure. Treat this as defence in depth; M-01 must be fixed independently rather than relying on group-count phrasing.

### Mandatory regression/adversarial evidence
Add committed regression mutations for the independent review's false greens, including the semantic equivalents of M1/M2/M3/M4/M6/M7. Add adjacent unseen variants covering active/passive voice, co-reference/pronouns, noun aliases, punctuation/clause reordering, read-marker camouflage and unknown predicates. Include false-positive controls proving legitimate other-field writes and read-only handle references remain accepted.

Preserve all prior J-01/H-03/H-04/R-02/K-01/L-01 invariants and all existing tests. Do not weaken assertions to make the candidate green. Unknown critical semantics should fail closed.

Run the complete committed freeze-spec suite, relevant static checks and secret scan without printing secret values. Report exact resulting SHA, parent, changed files, test counts, mutation/adversarial cases and clean-worktree evidence. If the repair requires changing the freeze contract rather than its evaluator, stop and report that as a blocker instead.

Do not self-review or declare engineering acceptance. After the repair, stop for a fresh independent review on the new exact SHA. No production/runtime/watcher/builder/connectors/credentials/privileges/business writes/deployment/adoption/sequencing changes.