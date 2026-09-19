# CHATGPT INBOX

## 2026-09-19 — Build isolated CROOKS Claude harness experiment

The ECC audit is complete. Do not repeat it. The owner has now explicitly approved the bounded project-scoped harness experiment in DEC-049 and ratified the already-observed Linux production state in DEC-048.

This is a **repository-only isolated engineering experiment**. It is not a production deployment, account/global Claude configuration change, connector/MCP permission change, secret task, or Orchestrator runtime deployment.

### Canonical truth first

Read fresh from `claude/product-memory-foundation`:
- CURRENT_TRUTH.md
- DECISIONS.md, especially DEC-048 and DEC-049
- ROADMAP.md
- ENGINEERING_STACK_REUSE_PLAN.md
- ENGINEERING_ORCHESTRATOR_V1.md
- DEV_TEAM_V1_PILOT.md

Read the accepted Builder candidate at:
- branch `claude/builder-environment-repair-review`
- exact base `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`
- `crooks-assistant/docs/DEV_ENVIRONMENT.md`
- `crooks-assistant/docs/dev-environment/CLAUDE_PROJECT_LAYOUT.md`

Read the completed ECC audit from the immediately preceding bridge outbox. ECC source provenance is pinned to:
`07756cee15788a54506031462794ad645719b028`

### Workspace contract

1. Verify `/opt/crooks-builder` is clean and still at the expected accepted Builder state before creating anything. Do not reset, clean, stash, switch or discard existing work.
2. Create a **new isolated git worktree** from exact base `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` on new branch `claude/harness-hooks-experiment`. Use a path under the already-writable Builder area, e.g. `/opt/crooks-builder/.worktrees/harness-hooks-experiment`.
3. If that branch/worktree already exists unexpectedly, or the base/main Builder is dirty, STOP and report instead of reusing/resetting it.
4. All implementation edits happen only in that isolated worktree. Production `/opt/crooks-os` remains read-only and untouched.

### Implement the smallest experiment

Build only the reviewed subset:

1. **Project-scoped Claude layout**
   - change the repository-root `.gitignore` from excluding all `.claude/` contents to the reviewed allowlist form needed to version project config;
   - add a short root `CLAUDE.md`;
   - add only the minimum useful `.claude/rules/` files needed for this experiment: `safety.md`, `testing.md`, and `builder-vs-production.md`;
   - add project `.claude/settings.json` with exactly the approved conservative hooks below.
   - Do not write anything under `/root/.claude`, user/global settings, account plugin state, or MCP grants.

2. **CROOKS-specific fail-closed Bash guard**
   - implement `crooks-assistant/scripts/hooks/guard_bash.py` using stdlib only;
   - reimplement the useful decision-table concepts from ECC GateGuard; do not import/execute ECC runtime;
   - deny destructive Git/history/worktree commands covered by the audit such as `reset --hard`, destructive `restore/checkout`, `clean -f`, force pushes, `branch -D`, stash drop/clear, reflog deletion/expiry, `update-ref -d`, destructive switch forms and destructive `rm -rf` patterns;
   - add CROOKS-specific protection for production/infrastructure mutation: writes/mutations targeting `/opt/crooks-os`, `/etc/crooks-os`, `/etc/systemd`, `/root/.claude`; `tailscale serve|funnel` mutations; service start/enable/restart/stop/disable for CROOKS; `make install`; `make secrets`; production/product-memory ref force/destructive pushes;
   - allow normal safe engineering commands such as `git status`, read-only Git inspection, tests and lint;
   - fail closed on malformed/oversized/unparseable hook input;
   - no environment-variable bypass, no network, no persistence, no source mutation;
   - hook output must never echo secret values.

3. **Tests**
   - add `crooks-assistant/tests/test_guard_bash.py`;
   - port/adapt a representative subset of ECC's audited destructive-command vectors and record the ECC commit/digest as provenance in comments/docs, not executable dependency;
   - include explicit positive cases and malformed-input cases;
   - test CROOKS-specific path/service/Tailscale/secret/global-Claude protections.

4. **Project hooks**
   - register `guard_bash.py` as a project-scoped PreToolUse hook for Bash;
   - add the conservative gitleaks commit/publish hook described in CLAUDE_PROJECT_LAYOUT, reporting rule + path only and never a secret value;
   - do not add format-on-write, session persistence, observer/learning, desktop notification, network-on-edit, MCP-health, global-config protection, or any ECC runtime hook.

5. **Static skill**
   - vendor only the audited `agent-architecture-audit` static skill from ECC commit `07756cee15788a54506031462794ad645719b028`;
   - narrow its tools to read-only/diagnostic scope as recommended by the audit;
   - preserve license/provenance;
   - rescan the exact landed skill with the existing SkillSpector `--no-llm` gate and inspect any finding manually.

6. **Worker tool-surface isolation proposal — code/docs only**
   - add a bounded design/test proposal for the future watcher launch hardening: strict empty MCP config / project-only settings where supported, explicit permission-prompt denial, plugin/slash-command restriction where supported, and a launch-time `system/init` roster assertion that fails closed on unexpected `mcp__*` or plugin tools;
   - distinguish what is documented vs what must be empirically verified;
   - **do not edit/install/restart the watcher service or `/root/.claude` in this round**.

### Verification

At minimum:
- targeted guard tests;
- `crooks-assistant/tests/test_dev_env.py`;
- Ruff on new Python;
- appropriate offline suite if time/resources permit;
- SkillSpector scan of the exact vendored skill;
- gitleaks/secret scan over the candidate without printing values;
- inspect `.claude/settings.json` and hook commands for project-relative correctness;
- exact diff against base;
- clean worktree after committing.

Push the new review candidate branch only after evidence passes. Do not merge it.

### Permission rule

DEC-049 is the explicit owner approval for project-scoped `.claude/` files in this isolated engineering worktree. If the agent/tool permission layer **still** refuses those project-scoped writes, STOP and report the exact refusal. Do not route around it, change global settings, change permissions, or write via another privileged path.

### Hard boundaries

- no production edits/deployment/service actions;
- no Tailscale mutation;
- no new secrets/credentials;
- no `/root/.claude` or account-level changes;
- no connector/MCP grant changes;
- no business connector calls;
- no CROOKS writes;
- no external spend;
- no ECC plugin/runtime installation;
- no destructive/reset/cleanup shortcuts;
- no Orchestrator runtime deployment.

### Handoff

Replace only `bridge/claude-outbox.md` with:
- workspace/branch/base identity;
- candidate commit SHA and pushed ref, if produced;
- exact files changed;
- test/scan evidence;
- any permission refusal or unresolved issue;
- explicit statement that this is a **review candidate, not accepted or deployed**;
- smallest safe next review step.

STOP.
