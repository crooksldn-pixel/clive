# CHATGPT INBOX

## Independent adversarial review — Control Plane Phase 1 repair

Review **exactly** `3ff2aa8bb8ee8ee8944980ad0dcebab04a79b481` on `chatgpt/control-plane-vnext-phase1-repair-2026-09-21`.

Resolve the remote branch HEAD first. STOP without verdict if it is not exactly that SHA.

This is **review-only**. Do not patch the candidate branch. This repair branch was authored through the GPT/GitHub path after your prior review of `8588776455a1832da763810064cacb47d7192ef4`; independently verify reviewer eligibility before proceeding.

### Why this repair exists

Your prior exact-SHA review rejected Phase 1 with:
- R-01: repository Ruff gate failed in candidate files;
- R-02: `task_id=".."` escaped the results directory;
- R-03: traversal inside `changed_paths` defeated scope checks;
- R-04: controller-owned owner-gate/obsolete state was ignored by scheduler composition;
- R-05: CAS mutation survived;
- R-06: starvation mutation survived;
- R-07 advisory: edited results could omit `result_sha` and evade branch binding;
- R-08 advisory: `worker_id` is a simulation-only self-asserted string, not trustworthy identity.

The repair attempts to address all eight without widening runtime authority.

### Required review

Recompute everything from source. Do not trust this summary or prior local claims.

1. **Ruff / static quality**
   - run the repository's accepted `ruff check app config scripts tests` gate;
   - all candidate-introduced lint must be clean;
   - do not run broad `ruff format` over unrelated files.

2. **Filesystem / identifier safety**
   - attack `task_id` and `attempt_id` with `.`, `..`, slash traversal, nested components and adjacent odd values;
   - prove `put_result` cannot escape `results_dir` or collide with `ACTIVE_STATE.json`.

3. **Changed-path scope safety**
   - attack absolute paths, backslashes, empty/dot/dotdot segments and traversal such as `crooks-assistant/tests/../app/main.py`;
   - prove an out-of-scope path cannot become in-scope through raw-prefix tricks;
   - judge whether the validation is appropriately fail-closed for repository-relative Git paths.

4. **SHA binding**
   - non-empty `changed_paths` must require an exact `result_sha`;
   - a malformed or moved current branch head must fail closed;
   - stale subject SHA must still fail.

5. **Controller-owned state**
   - construct a valid-looking worker result plus `TaskRuntimeState(owner_gate=True/status=OWNER_GATE)` and prove scheduler composition does not dispatch it;
   - repeat for controller-owned blockers/obsolete/cancelled state where relevant;
   - prove a superseded task revision cannot dispatch when the controller supplies a newer latest revision;
   - ensure the repair has not accidentally made legitimate ready continuations impossible.

6. **Mutation quality**
   - remove/neutralise the CAS expected-sequence comparison. The targeted tests must fail for the CAS reason, not a different increment guard;
   - mutate the scheduler so the first **policy-denied** candidate returns/aborts instead of continuing. The starvation test must fail;
   - recheck reviewer independence, branch-head binding, out-of-scope path gate and stale subject SHA mutations;
   - invent at least two adjacent counterexamples not in the committed table.

7. **Regression evidence**
   - targeted control-plane module;
   - full offline suite `pytest tests -m "not live" -q -n 4` if the accepted environment supports it;
   - gitleaks/secret scan over the repair diff;
   - clean review worktree and exact identity evidence.

8. **R-08 documentation**
   - verify the candidate now explicitly says worker IDs are Phase 1 simulation placeholders and must become controller-issued/bound identity before runtime authority relies on them;
   - this is documentation, not a request to invent cryptographic identity in Phase 1.

### Scope / authority

This candidate is repository-only. Acceptance means only that Phase 1 is sound enough for the next isolated control-plane step. It does not authorise:
- watcher/systemd/runtime installation or modification;
- production deployment/promotion;
- credentials/secrets or permission changes;
- privilege expansion;
- CROOKS/CLIVE business writes;
- external spend;
- destructive owner-work cleanup;
- merge to production;
- owner-only release/adoption.

### Verdict

Return exactly one:
- `ACCEPT FOR PHASE 1 REPOSITORY FOUNDATION`;
- `REJECT — REPAIR REQUIRED` with bounded reproducing defects;
- `BLOCKED` only for a genuine inability to perform the review.

If accepted, include the exact SHA, targeted/full-suite/static/secret evidence and mutation outcomes. If rejected, separate subject defects from verifier/test defects so the verifier cannot recursively monopolise the subject.
