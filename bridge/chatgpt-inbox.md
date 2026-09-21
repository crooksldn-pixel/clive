# CHATGPT INBOX

## Bounded repair — Control Plane Phase 1 acceptance defects

The independent review of exact SHA `3ff2aa8bb8ee8ee8944980ad0dcebab04a79b481` on `chatgpt/control-plane-vnext-phase1-repair-2026-09-21` returned `REJECT — REPAIR REQUIRED`.

This is a **bounded repository-only repair**, not another architecture/prose round. Do not touch the parked prose-freeze parser track. Do not modify watcher/systemd/runtime. Do not deploy, enable business writes, read secrets, change permissions/privileges, spend externally, merge to production, or widen authority.

### Proportion / review result

The reviewer found **no runtime semantic defect** in the candidate. Seven of the eight prior R-01..R-08 findings are genuinely repaired. The remaining acceptance work is:

1. **Subject defect S-01 — Ruff import ordering only**
   - `ruff check app config scripts tests` still reports four `I001` errors in:
     - `app/orchestrator/contracts.py`
     - `app/orchestrator/policy.py`
     - `app/orchestrator/scheduler.py`
     - `tests/test_orchestrator_control_plane.py`
   - Fix only those import-order errors. `ruff check ... --fix` is acceptable if the resulting diff is bounded. Do **not** run broad `ruff format` over the repository.

2. **Verifier/test defect V-01 — path boundary guard needs a killing test**
   - Runtime is correct: scope matching uses `path == allowed.rstrip("/") or path.startswith(allowed.rstrip("/") + "/")`.
   - Add a test proving `allowed_paths=("crooks-assistant/app",)` rejects sibling-prefix `changed_paths=("crooks-assistant/application/secrets.py",)`.
   - The test must fail if the boundary-safe check is regressed to raw `path.startswith(allowed)`.

3. **Verifier/test defect V-02 — isolate controller `owner_gate`**
   - Runtime is correct but current test sets redundant signals together.
   - Add a test with `owner_gate=True` while status is otherwise dispatchable (for example `TaskStatus.EVIDENCE_READY`) and blocker class is `NONE`; prove scheduler refuses dispatch.
   - The test must fail if the `runtime_state.owner_gate` guard is removed.

4. **Verifier/test defect V-03 — isolate controller `blocker_class`**
   - Add a test with `blocker_class=DETERMINISTIC` while status is otherwise dispatchable and `owner_gate=False`; prove scheduler refuses dispatch.
   - The test must fail if the `runtime_state.blocker_class` guard is removed.

### Branch / evidence

Create a **new successor repair branch** from exact `3ff2aa8bb8ee8ee8944980ad0dcebab04a79b481`; do not rewrite the reviewed branch. Keep the diff minimal.

Before completion:
- run targeted `pytest tests/test_orchestrator_control_plane.py -q`;
- run repository Ruff gate `ruff check app config scripts tests`;
- run full offline suite `pytest tests -m "not live" -q -n 4` if supported;
- run the pinned secret scan over only the successor diff;
- explicitly perform the three relevant mutations/counterexamples so each new test is shown to kill its intended regression;
- leave worktree clean and push the successor branch.

Return in `bridge/claude-outbox.md`:
- successor branch and exact SHA;
- bounded diff summary;
- targeted/full/static/secret evidence;
- V-01/V-02/V-03 mutation outcomes;
- confirmation no runtime/service/business side effects;
- `NEXT ACTION: fresh independent exact-SHA review required`.

Do not self-accept this repair. A fresh reviewer must review the exact successor SHA.