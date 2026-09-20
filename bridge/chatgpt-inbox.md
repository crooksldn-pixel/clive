# CHATGPT INBOX

## Bounded repair — Orchestrator V1 freeze L-01

Perform exactly one bounded repository-only repair round on the existing freeze-candidate branch.

### Fresh identities
- repository: `crooksldn-pixel/clive`
- current canonical observed before dispatch: `claude/product-memory-foundation@3ba4edeb1bdeb317a08932e44557c7e6051fa510`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- rejected candidate: `a904a209d57add65f3878b4f7ee3eec19b6c35a9`
- review inbox consumed: `376d63b16297e9827e37d15973506290d2f8c648`
- verdict: `CHANGES REQUIRED BEFORE OWNER DECISION`
- material blocker: L-01

Resolve all refs fresh before editing. Abort if the freeze branch is no longer exactly `a904a20`, if unrelated work is present, or evidence identity cannot be established. Do not rebase onto moving canonical truth.

### Hard scope
Test-module-only unless fresh evidence proves the contract itself is defective:
- allowed file: `crooks-assistant/tests/test_orchestrator_freeze_spec.py`
- keep freeze contract/state API/acceptance/traceability/DECISIONS text unchanged; review found the contract invariant itself sound.
- no optional unrelated hardening.
- no runtime/watcher/systemd/builder changes, secrets, account/global Claude changes, MCP/connectors, privileges, business writes, public exposure, destructive operations, spend, merge, adoption, sequencing changes, or Orchestrator implementation.

### L-01 repair objective
The current classifier only examines clauses that repeat the literal backticked cleanup-handle identifier. An operative second write can therefore evade the gate through ordinary co-reference/pronouns such as `it`, `this field`, `the cleanup handle`, or `the attempt's owned process group handle`, while the full suite remains green.

Repair the gate structurally and fail closed. Within every §3A transition-row cell that establishes cleanup-handle context, inspect the complete relevant cell/clauses rather than only clauses repeating the literal identifier. Any un-negated cleanup-handle write or plausible co-referential write must be classified/countable or fail closed. Do not create a broad heuristic that produces false confidence.

At minimum:
1. Preserve WRITES / PROHIBITS_WRITE / READS_ONLY semantics and negation precedence.
2. Cover co-reference/pronoun continuations after the handle has been established in the cell, including sentence and semicolon boundaries.
3. Distinguish writes to explicitly different backticked fields from writes to the cleanup handle.
4. Closed, explicit carve-outs for legitimate non-handle subjects (e.g. lease retirement) must themselves be asserted; unknown/ambiguous critical prose fails closed.
5. Preserve the derived sole write point `CREATED -> STARTING` and declared cardinality = 1.
6. Add defence-in-depth group-creation cardinality reinforcement if it can be derived structurally from §3A without weakening/faking the proof: an unsafe second controller-created attempt process group must independently fail even if wording around the handle changes.
7. Do not merely add the review's exact phrases to a blacklist/whitelist. The repair must generalise to the semantic class.

### Required adversarial evidence
Prove failing-before against exact `a904a20` using immutable/hash-verified committed blobs or equivalent scratch. Add regression mutations for at least the review's four escapes, injected into the real `STARTING -> RUNNING` cell while leaving prohibition and declared cardinality intact:
- `; a fresh controller-allocated process group is created for the model process and it is set to that group's identity`
- `. A fresh controller-allocated process group is created for the model process and the cleanup handle is rewritten to name it`
- `. A fresh controller-allocated process group is created for the model process. This field is then updated to name that group`
- `. The attempt's owned process group handle is replaced with the identity of a fresh controller-allocated model process group`

Also invent additional unseen co-reference/grammar/punctuation mutations yourself; include at least pronoun, noun-phrase alias, sentence-boundary, semicolon-boundary, passive/active grammatical variation, and an ambiguous unknown form that must fail closed. Include negative controls for legitimate writes to another explicitly named field and legitimate lease-retirement prose so the gate is not simply rejecting every write verb.

Re-run the prior K-01/J-01/H-03/H-04/R-02 mutation/regression evidence and ensure pristine control remains green. The important evidence is not raw pass count: report which unsafe mutants are detected, which quality/invariant dimension detects each, and any remaining blind spots.

### Publication evidence
Run committed freeze-spec suite, relevant Ruff/static checks, changed-file secret scan with no values printed, exact diff/readback, clean worktree. Publish one new candidate SHA to the existing freeze branch only if all required evidence is green. Report exact parent/new SHA and exact changed-file set.

Do not self-certify. Any prior verdict is stale after the SHA changes. State that exactly one fresh independent read-only adversarial review bound to the new exact SHA is required next.