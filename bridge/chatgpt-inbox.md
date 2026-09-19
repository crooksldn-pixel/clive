# CHATGPT INBOX

## 2026-09-19 — Repair rejected harness candidate after independent review

Repository is now `crooksldn-pixel/clive`. Fetch fresh refs; do not rely on stale tracking refs.

### Objective

Perform one bounded repair round for the independently rejected harness candidate.

- branch: `claude/harness-hooks-experiment`
- rejected candidate: `dd50ebbca6eca9c4e2ee1e85ad17d2c7e5afd25e`
- accepted Builder base: `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`
- review inbox: `2b1030bd48ee14888e0c85b7d160fa39b2cba6eb`
- review verdict: `REJECT — REPAIR REQUIRED`
- current canonical product-memory head after repo rename/review record: `052a27d496845a4c8b8eddb5c32685a3892b6a72`

Read fresh canonical truth from `claude/product-memory-foundation` and the latest review outbox before editing.

### Director resolution on D-14 workspace incident

For this current single-worker watcher, **do not remove or relocate the existing candidate worktree during this repair** and do not weaken the dirty-tree guard.

The owner-side `.git/info/exclude` entry for `.worktrees/` is acknowledged as a temporary operational workaround used to unblock review. Preserve the candidate's tracked `.worktrees/` ignore and document the incident/workaround accurately.

The durable V1 direction remains external worker attempts such as `/opt/crooks-workers/<task-id>/<attempt-id>/`, but the reviewer correctly noted the current watcher unit only grants `ReadWritePaths=/opt/crooks-builder`. Therefore moving worker workspaces outside the Builder requires a separately reviewed watcher/systemd hardening change later; **do not change the watcher unit in this repair round**.

### Required repair

Create exactly one new repair commit on `claude/harness-hooks-experiment` on top of `dd50ebb…`. Do not merge.

Repair the review's bounded defects:

1. **D-01 H:** deny any access, including reads, under `/etc/crooks-os/credentials` and `/etc/crooks-os/secrets`; cover `.cred` and signing-key names without reading secret values.
2. **D-02 H:** bare `git stash` is mutating; only explicit `stash list` / `stash show` are read-only.
3. **D-03 H:** fail closed on command-word laundering / dynamic command names; cover variable command words, ANSI-C command words and `eval`.
4. **D-04 H:** fail closed on shell-fed text via pipes, here-strings and prose heredocs; cover literal echo/printf only where the text itself is safely re-evaluated.
5. **D-05 M:** inspect dropped assignments and protect `GIT_DIR`, `GIT_WORK_TREE`, `GIT_COMMON_DIR`.
6. **D-06 M:** detect `git -c core.hooksPath=...`.
7. **D-07 M:** deny nested Claude launches that can change permission/settings/MCP/bare/print behaviour.
8. **D-08 M:** project `.claude/` and `.git/hooks/` are Bash-write-protected; reads may remain allowed.
9. **D-09 M:** joined curl short options and package-manager short-option verb parsing.
10. **D-10 bounded cases:** brace/path spellings, relative `cd` tracking, deny `cd -` when safety state becomes ambiguous, and treat `{}` placeholders as unknown for destructive targeting. Record symlink-through-parent as a textual-hook limitation rather than pretending to solve filesystem aliasing.
11. **D-11 M:** both hooks catch unexpected exceptions and exit fail-closed with a fixed non-secret stderr line and status 2.
12. **D-12 bounded cases:** `printf` credential variables, sliced variable forms, `/proc/*/environ`, `declare/typeset -x`, and inline interpreter environment/secret-file reads.
13. **D-15 M→H:** gitleaks publish detection must recurse into shell `-c` / here-string forms and remain effective against the repaired laundering cases.
14. **D-16 L:** parse `git commit -C <commit>` correctly; only treat global `git -C` before the subcommand as checkout path.
15. **D-17 M:** use one total gitleaks scan deadline that is safely below the registered hook timeout; do not extend timeout by touching pending `.claude/settings.json`.
16. **D-18 M:** roster assertion fails closed on undocumented/list-valued roster surfaces and includes `slash_commands` in the digest. Unknown evidence is UNKNOWN, not PASS.
17. **D-20 L:** isolation documentation must say the runtime roster assertion is a kill switch/backstop, not the primary gate; launch configuration is the gate.
18. Correct the stale root `CLAUDE.md` approximate test-count wording if still present.
19. Record D-14's temporary local exclude workaround and the future external-workspace/systemd implication in `DEV_ENVIRONMENT.md` or the existing isolation/workspace doc without presenting the workaround as permanent architecture.

### Scope decision for D-13

Prefer the simpler conservative rule where it reduces code: engineering workers do not write under `/etc` or `/root` except explicitly declared scratch/approved project-local paths. Do not broaden permissions to achieve this. Preserve legitimate read-only diagnostics only where they cannot expose credentials/secrets. If implementing this general rule would materially expand or destabilise the repair, keep the narrower CROOKS rules and document D-13 as deferred; do not silently add a large new policy surface.

### D-19 / tool-surface rule

Do **not** claim layer-1 roster isolation is proven. The deferred-tool / `ToolSearch` question remains empirical. Do not change account/global Claude settings, MCPs/connectors, identity, credentials or watcher launch flags in this round. Record the limitation and leave the empirical isolation experiment for a separately authorised live check.

### Evidence contract

For every repaired defect, add a negative regression test using the review's exact vectors or an equivalent minimal vector. Demonstrate failing-before / passing-after where practical from the rejected SHA, without exposing secret values.

Re-run:
- targeted hook/roster/layout/dev-environment tests;
- full offline suite;
- Ruff;
- gitleaks over the new commit/range and changed files with redaction/no secret-value output;
- exact diff and branch identity;
- clean candidate worktree.

If the 1,340-line guard can be made materially smaller **without reducing the proved safety contract**, do so; otherwise do not refactor for line count during a security repair. Auditability matters more than an arbitrary target.

### Hard boundaries

- no production changes;
- no business writes;
- no service/systemd/Tailscale mutation;
- no account/global Claude or connector/MCP changes;
- no new secrets or credential reads;
- no `.claude/` writes or workaround attempts;
- no merge;
- no destructive cleanup/reset/stash of owner work;
- do not touch the current owner-side local exclude entry;
- do not self-certify acceptance.

Push the one-commit repair candidate and read back its exact remote SHA.

### Handoff

Replace only `bridge/claude-outbox.md` with:
- exact new candidate SHA and parent;
- defects repaired/deferred with evidence;
- test/scan results;
- remaining limitations;
- proof production/global/account state was untouched;
- recommendation for a **fresh independent review** of the new SHA.

STOP after publishing the repair candidate.