# CHATGPT INBOX

## Bounded repair — Orchestrator V1 freeze evaluator M-03 / M-04

Perform exactly one bounded repository-only repair round.

Repository: `crooksldn-pixel/clive`
Branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
Exact rejected SHA: `de9bea2b040808175077777afc35c5394eb4d716`
Verdict: `REJECT — REPAIR REQUIRED`

Resolve fresh and stop if HEAD differs. Change only `crooks-assistant/tests/test_orchestrator_freeze_spec.py`. Do not change freeze documents or other project files.

### M-03
The evaluator currently deduplicates by transition row, allowing a legitimate row to absorb a second cleanup-handle write and second controller-created process-group creation while the declared count remains 1. Make the authoritative cardinality checks count semantic assertions rather than only distinct rows. Preserve useful row-level diagnostics if desired. Add regressions for same-row complete handovers using explicit/backticked and natural-language alias forms, plus pristine controls.

### M-04
The current group-creation derivation can suppress a real creation merely because an unrelated negator occurs in the same comma segment. Require negation to govern the creation assertion it suppresses. Preserve genuine denials in the committed document while catching real creations accompanied by unrelated negation, including `created ... without delay`, `created ... and not for preflight`, and a preceding unrelated condition such as `if cleanup cannot be proven ... a second process group is created`. Prefer a principled local rule over a phrase list. Ambiguous critical semantics must fail closed.

Preserve M-01/M-02 and J-01/H-03/H-04/R-02/K-01/L-01 plus earlier invariants. Do not remove, skip, weaken or rename existing tests to regain green. Add new adversarial combinations beyond the review examples, including same-row multiplicity with a decoy field and unrelated negation, plus false-positive controls for legitimate unrelated-field writes, read-only handle references and genuinely negated non-creation prose.

Before reporting success, provide resulting exact SHA and parent, exact changed-file scope, clean worktree, freeze-document byte identity against `de9bea2`, relevant tests/static checks, before/after mutation evidence for both blockers, accurate test/function counts, and remaining uncertainty. Commit the bounded repair and stop. Do not review or certify your own repaired SHA; the next controller round will request a fresh exact-SHA review. No merge, deployment, runtime change, business action or freeze adoption is authorised.