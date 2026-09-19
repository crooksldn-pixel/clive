# CHATGPT INBOX

## 2026-09-19 — Independent review of isolated harness candidate

The implementation round that consumed inbox blob `83ead96b48252a6339adbf8bfc1a8351e43255f4` is complete. Do **not** rerun it and do not attempt the refused `.claude/` writes.

### Objective

Perform an adversarial, read-only independent review of review candidate:

- branch: `claude/harness-hooks-experiment`
- exact candidate: `dd50ebbca6eca9c4e2ee1e85ad17d2c7e5afd25e`
- exact base: `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`

Read fresh canonical truth from `claude/product-memory-foundation`, especially CURRENT_TRUTH, DECISIONS DEC-048/049, ENGINEERING_STACK_REUSE_PLAN, ENGINEERING_ORCHESTRATOR_V1 and DEV_TEAM_V1_PILOT. Read the preceding outbox in Git history if needed for the implementation evidence.

This is a reviewer task. Do not implement fixes, do not create another candidate, do not apply pending `.claude/` files, and do not touch production/global Claude/account settings/connectors/secrets/services/Tailscale.

### Review requirements

Independently inspect the actual one-commit diff and source, not just the implementer's report. At minimum:

1. Verify exact base/head identity and that the candidate is exactly one commit ahead of the accepted Builder base.
2. Review `guard_bash.py` adversarially for parser/quoting/wrapper/separator/redirection/path/ref bypasses, false allows on destructive operations, dangerous false positives that would make normal engineering unusable, secret leakage, environment bypasses, and any fail-open path. Pay particular attention to shell constructs not represented in the implementer's named vectors.
3. Review `gitleaks_gate.py` for commit/push detection bypasses, protected-checkout logic, scan scope, missing-tool/error handling, report handling and secret-value leakage.
4. Review `roster_assert.py` and `WORKER_TOOL_SURFACE_ISOLATION.md`. Challenge whether the proposed init-message fields are actually sufficient to prove absence of inherited MCP/plugin surface. Treat undocumented/missing roster evidence as UNKNOWN/fail-closed, not proof. Explicitly flag any assumption that requires empirical verification before watcher integration.
5. Review `.gitignore`, root `CLAUDE.md`, and `PROJECT_CLAUDE_FILES_PENDING.md`. Confirm the pending `.claude/settings.json` would register only the intended project hooks and would not grant permissions, set environment, persist state, reach network, or activate ECC runtime. Confirm the static skill provenance/narrowed-tool plan.
6. Independently run/re-run the targeted tests and, if practical, the offline suite on exact candidate. Re-run Ruff and candidate secret scan without printing secret values. Confirm skipped layout tests are not represented as passes for the missing `.claude/` files.
7. Check whether creating the worktree under `/opt/crooks-builder/.worktrees/` causing the parent builder to show `?? .worktrees/` violates the accepted clean-builder/watcher precondition or requires a `.gitignore`/workspace-manager design correction. Do not clean/remove it; report the consequence.
8. Assess the 1,340-line guard against the reuse plan's stated preference for a small CROOKS-specific guard. Complexity alone is not a rejection, but identify whether the size materially harms auditability or creates unnecessary policy surface.
9. Verify no production/global/account/connector/secret/service/Tailscale/business-write change occurred.

### Verdict contract

Return exactly one overall verdict:
- `ACCEPTABLE AS PARTIAL REVIEW CANDIDATE` — only if the committed non-`.claude/` pieces are sound, while clearly keeping the refused `.claude/` activation incomplete; or
- `REJECT — REPAIR REQUIRED` — with numbered defects, severity, exact evidence and smallest bounded repair.

Do **not** call the harness accepted or active: `.claude/` files were refused and no hook is active. Do not infer owner approval for a workaround. The owner has approved project-scoped files conceptually (DEC-049), but Claude Code's sensitive-file refusal remains a separate enforcement boundary.

### Handoff

Replace only `bridge/claude-outbox.md` with the review evidence, verdict, any defect IDs, and the smallest safe next step. STOP.