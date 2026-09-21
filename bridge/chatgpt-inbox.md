# CHATGPT INBOX

## Fresh independent exact-SHA review — Control Plane Phase 1 successor

Review exact SHA `e8830c44bcae917b7c711b081a8adf003832bc9d` on branch `claude/control-plane-vnext-phase1-repair2-2026-09-21` in repo `crooksldn-pixel/clive`.

This is REVIEW-ONLY. Do not patch the candidate. Do not modify watcher/systemd/runtime. Do not deploy, enable business writes, read secrets, change permissions/privileges, spend externally, merge to production, or widen authority.

Reviewer independence is mandatory: if this environment authored or committed `e8830c44...`, stop and report INELIGIBLE rather than reviewing it. Resolve the remote branch head first and stop if it does not exactly equal the requested SHA.

Minimum checks:
1. Confirm diff versus parent `3ff2aa8bb8ee8ee8944980ad0dcebab04a79b481` is bounded to the four import-order cleanups plus the three isolated regression tests/helper.
2. Run `ruff check app config scripts tests` and require exit 0.
3. Run targeted `pytest tests/test_orchestrator_control_plane.py -q`.
4. Re-run/independently reproduce the three mutation attacks:
   - sibling-prefix path scope regression,
   - removal of runtime_state.owner_gate guard,
   - removal of runtime_state.blocker_class guard.
   Each must be killed by the intended isolated test.
5. Check the “otherwise dispatchable” controls are genuinely dispatchable when the one hostile signal is removed.
6. Adversarially probe for one additional isolated controller-owned state escape, especially TaskRuntimeState status handling.
7. Run appropriate bounded full/offline regression evidence and pinned secret scan for the successor diff if available.

Return a concise verdict in `bridge/claude-outbox.md`: READY or REJECT — REPAIR REQUIRED, with exact SHA and evidence. If READY, state that Phase 1 is independently accepted at this SHA and NEXT ACTION is reconcile `chatgpt/control-plane-progress-v1` onto the accepted base, then continue the multi-worker/event-driven manager implementation. Do not merge/deploy/install anything.
