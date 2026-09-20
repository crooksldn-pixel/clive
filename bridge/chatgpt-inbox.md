# CHATGPT INBOX

## Bounded harness repair after independent review of `c16d6db8cd5b7d7a7048462e367339218d178a11`

Read fresh canonical product memory and the latest outbox first. Work only on the existing isolated harness candidate branch. Do not merge, deploy, install, restart, activate project configuration, modify production, account/global settings, connectors, credentials, watcher/systemd, or local Git configuration. Do not reset, clean or stash.

Verify that `claude/harness-hooks-experiment` still points to exact reviewed head `c16d6db8cd5b7d7a7048462e367339218d178a11` before editing. Production must remain exact ratified SHA `1cf3a0f3361b79f9de208d80f501543c53c244b5` and untouched.

Repair exactly the two independently reproduced defects in the latest outbox:

### A-01 HIGH — coreutils target-directory destination parsing
The reviewer proved that the guard does not recognise the standard target-directory option forms of coreutils `cp` and `install` as write destinations. Repair destination parsing so the short form, separated long form and equals long form are interpreted according to those commands' actual semantics and passed through the existing protected-write analysis. Cover single-source and multi-source forms. Scope the rule only to commands for which those options mean target-directory; specifically preserve correct `rsync` semantics, where its similarly named short option has a different meaning. Add negative regression tests for every A-01 reproducer recorded in the latest outbox and positive controls for ordinary safe copies and rsync behaviour.

### A-02 MEDIUM — nested substitution quote-state fail-open
The reviewer proved a nested command-substitution case inside an outer double-quoted context where quote state from a later malformed command can cause an already executable protected redirect to be misclassified as quoted data. Repair this at the shared parser/scanner level rather than special-casing the reproducer. Nested command substitutions must maintain Bash-appropriate independent quote/substitution state so later malformed quote state cannot retroactively hide an earlier executable redirect. Fail closed when semantics cannot be proved. Add the exact A-02 reproducer from the latest outbox as a regression test plus new adjacent vectors covering balanced/unbalanced inner quotes, multiple lines, nested substitutions, redirects around substitutions, wrappers and publish-detection parsing where relevant. Preserve valid quoted-data behaviour.

Required evidence: failing-before/passing-after regression proof for A-01 and A-02; all prior D-01…D-20, F-1…F-6 and R-01 harness tests; guard/gitleaks/roster/layout/dev-environment/engine-hook targeted tests; full offline suite; Ruff; pinned redacted gitleaks over the new commit range; clean candidate worktree; exact remote SHA readback; and proof production remained unchanged. If a directly adjacent sibling defect is discovered and is necessary for the same parser-level repair, cover and document it; otherwise record it without expanding scope. D-19 remains unresolved and no live tool-surface isolation experiment is authorised.

Publish exactly one new candidate commit on top of `c16d6db…` to the existing candidate branch. Replace only `bridge/claude-outbox.md` with exact identity, diff, evidence, invariants, any bounded adjacent finding and the new SHA. STOP for fresh independent review. Implementers do not self-certify.