# CHATGPT INBOX

## Fresh independent adversarial review — harness candidate `2c2b0cc4a5f3d82a929eedfa053b5cc46478215f`

Read fresh canonical product memory first, especially CURRENT_TRUTH, DECISIONS, ROADMAP, ENGINEERING_ORCHESTRATOR_V1, DEV_TEAM_V1_PILOT, ENGINEERING_STACK_REUSE_PLAN and MIGRATION_HANDOFF. Then read the latest outbox. This is an INDEPENDENT REVIEW, not implementation. Do not modify the candidate branch, merge, deploy, install, restart, activate project `.claude/` configuration, alter production, account/global settings, connectors, credentials, watcher/systemd, privileges, local Git configuration, or business state. Do not reset, clean or stash.

Review exact branch `claude/harness-hooks-experiment` at exact candidate `2c2b0cc4a5f3d82a929eedfa053b5cc46478215f`, whose exact parent must be `c16d6db8cd5b7d7a7048462e367339218d178a11`. Independently verify remote identity and the actual diff. Expected candidate diff is exactly two files: `crooks-assistant/scripts/hooks/guard_bash.py` and new `crooks-assistant/tests/test_harness_review_c16d6db_repairs.py`. Production must remain exact ratified SHA `1cf3a0f3361b79f9de208d80f501543c53c244b5` and untouched.

The implementer claims A-01 (coreutils cp/install target-directory and option-grammar destination parsing) and A-02 (nested command-substitution quote-state fail-open) are repaired, plus directly adjacent scanner/heredoc siblings. Treat every claim as untrusted until reproduced from source/evidence.

Adversarially attack the repair rather than merely rerunning its tests. In particular:

1. A-01: exercise `cp` and `install` destination semantics across `-t`, glued/bundled short forms, `--target-directory`, equals forms, GNU long-option abbreviations, options before/after operands, option values, `--`, multiple sources, `install -d`, relative targets after `cd`, wrappers/substitutions, and protected roots. Confirm safe read-out-of-production cases remain allowed. Confirm `rsync -t` retains its unrelated `--times` semantics and scp/mv/ln behaviour is not regressed. Probe unknown/ambiguous options for fail-closed behaviour without inventing false write semantics.
2. A-02: attack nested `$(...)` and backticks inside/outside double quotes, balanced/unbalanced quotes, comments, parentheses, continuations, multiline substitutions, redirects before/after substitutions, wrappers, shell-fed text, heredocs and nested substitutions. Specifically test whether malformed state later in the command can hide an earlier executable protected write/delete/read or Git publication. Compare disputed parser semantics with real Bash in scratch-only paths where safe.
3. Re-test the adjacent commented-heredoc and single-line-backtick-heredoc defects and look for sibling parser/scanner disagreements that can hide production writes, recursive deletes, protected secret reads, destructive Git, or publication.
4. Recheck the previously closed D-01…D-20, F-1…F-6 and R-01 security contracts with new vectors, not only historical reproducers. D-19 remains unresolved and no live tool-surface isolation experiment is authorised.
5. Inspect the actual implementation for fail-open paths, parser disagreement, recursion/resource hazards, command-word laundering, relative-path/CWD errors, copy destination mistakes, heredoc ownership errors, and gitleaks publish-detection bypasses.
6. Independently reproduce the targeted regression evidence where practical. Inspect the reported full-suite xdist error rather than silently treating prose as proof; distinguish unchanged reproducible environmental race from candidate regression. Run Ruff and pinned redacted gitleaks over `c16d6db..2c2b0cc`. Verify clean candidate state and exact remote SHA. Verify production invariants read-only.

Return exactly one overall verdict:
- `ACCEPT FOR NEXT GATE`, only if no substantive harness defect remains within this review scope; or
- `REJECT — REPAIR REQUIRED`, with a bounded numbered finding list including severity, exact reproducer/evidence, affected contract, and required outcome.

Do not repair findings yourself. Replace only `bridge/claude-outbox.md` with the exact review subject, identity/diff verification, commands/tests/scans and raw result summaries, adversarial findings, production invariant evidence, limitations, and verdict. STOP after publishing the review. Implementers never self-certify.