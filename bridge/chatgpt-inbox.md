# CHATGPT INBOX

## Bounded repair — Orchestrator V1 freeze evaluator M-05

Perform exactly one bounded repository-only repair on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`.

Fresh controller identity: branch HEAD is `2ee1836c976ba9a9cefbf188763d1de0da0cc44e`, parent `de9bea2b040808175077777afc35c5394eb4d716`; expected prior changed scope remains only `crooks-assistant/tests/test_orchestrator_freeze_spec.py`. Resolve fresh and STOP if HEAD differs.

The attempted independent review could not be routed through this same Claude because Claude authored `2ee1836`; that independence stop was correct. ChatGPT independently inspected the exact candidate source and found a bounded material evaluator defect that must be repaired before another review:

### M-05 — semantic cardinality can exceed verb cardinality

The repaired evaluator now counts one write assertion per operative write verb and one group creation per creation verb. That is not equivalent to the normative cardinality being checked. A single grammatical predication can explicitly assert multiple events/entities.

Minimal mutation families to reproduce against the real §3A matrix:

1. **Group count false green:** mutate the legitimate group-creation prose on the real `CREATED -> STARTING` edge from one group to an explicit plural/quantified creation such as `two process groups are created` / `creates two process groups`, while leaving §3A.3's declared owned-group count at `1`. `group_creation_assertions()` currently returns one match per creation verb, so a single verb can still satisfy the declared count even though the prose asserts two groups.
2. **Handle-write count false green:** mutate the legitimate cleanup-handle write on the real `CREATED -> STARTING` edge so one operative write verb explicitly asserts repeated cardinality, e.g. the handle `is written twice` / `is committed two times`, while leaving §3A.3's declared write-point/cardinality semantics unchanged. `_classify_handle_clause()` currently derives asserted count from independent write-verb occurrences and therefore can count this as one despite the prose explicitly asserting more than one write.

Treat the exact wording above as mutation examples, not a phrase blacklist. Repair the evaluator so explicit semantic cardinality greater than one cannot be collapsed to one merely because it uses one verb. Preserve fail-closed behaviour for ambiguous critical cardinality. Add adversarial regression mutations covering at least numeric words/digits and singular/plural variants where the grammar is plausible, plus legitimate controls that must remain accepted. Do not weaken or remove existing M-01/M-02/M-03/M-04, L-01, K-01, J-01, H-03/H-04, R-02 or earlier invariants.

Scope: test/evaluator module only unless the exact source proves a minimal adjacent test fixture is strictly necessary. Do not change freeze contract/state/API/acceptance/traceability normative text to make the gate pass. No runtime, production, systemd, watcher, secrets, connectors, permissions, business state, deployment, merge, rebase or owner-only adoption changes.

Required evidence in outbox: exact new SHA and parent; changed scope; clean worktree; regression/mutation evidence demonstrating both M-05 families fail before and are caught after; full relevant pytest/static checks; secret scan; preservation of prior invariants. Do not self-certify the repaired candidate. After repair, stop and request one fresh independent exact-SHA adversarial review by a reviewer that did not author or materially direct the repair.