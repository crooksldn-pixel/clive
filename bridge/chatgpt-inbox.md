# CHATGPT INBOX

## Fresh independent adversarial review of harness candidate `c16d6db8cd5b7d7a7048462e367339218d178a11`

Read fresh canonical product memory from `claude/product-memory-foundation` and the latest outbox first. This is REVIEW-ONLY. Do not implement fixes, amend, merge, deploy, install, restart, activate `.claude/`, modify account/global Claude/MCP/connectors, touch secrets/credentials, alter watcher/systemd/local Git config, reset/clean/stash, or mutate production.

### Exact review identity
- candidate branch: `claude/harness-hooks-experiment`
- exact candidate: `c16d6db8cd5b7d7a7048462e367339218d178a11`
- exact parent: `ef73fbe738cd805c21b9a33b0cc0d36245251658`
- accepted Builder base: `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`
- production must remain exactly `1cf3a0f3361b79f9de208d80f501543c53c244b5`

Verify remote identity explicitly and prove `c16d6db…` is exactly one commit over `ef73fbe…`. Use explicit branch fetches if required; do not modify the known stale Builder fetch refspec.

### Review contract
Reproduce the implementer evidence rather than trusting the outbox. Inspect the actual two-file diff and independently attack the parser with NEW vectors not copied from the new test file. Re-check the complete prior D-01…D-20 and F-1…F-6/R-01 safety contract where relevant, with particular focus on whether the new continuation normalisation creates parser disagreement, fail-open paths, or over-permissive heredoc behaviour.

Required focus:
1. Bash-equivalent backslash-newline semantics in unquoted, double-quoted, single-quoted, comments, command words, redirect operators/targets, operands, nested substitutions and wrappers.
2. Heredoc owner and body parsing: quoted/unquoted delimiters, continued delimiter candidates, multiple heredocs, malformed/unterminated heredocs, shell-fed heredocs, and any case where `_strip_heredocs` might erase executable text or preserve dangerous text incorrectly.
3. Protected writes/copies/deletes after `cd`, payload cwd, chained commands, descriptor redirects, glued operators, braces/globs and relative targets.
4. Gitleaks publish detection through continuations, wrappers, shell strings, substitutions and malformed input; fail closed where semantics cannot be proved.
5. New scanner complexity: quote/comment state, odd/even trailing backslashes, CRLF or unusual newline neighbours if Bash semantics differ, escaped `#`, quote transitions across continuations, nested command substitutions and idempotence of normalisation.
6. Re-run the new R-01 tests; all prior harness review repair/guard/gitleaks/roster/layout/dev-env/engine-hook targeted tests; full offline suite; Ruff; and pinned redacted gitleaks over `ef73fbe…c16d6db…`. Classify the reported xdist capability-delta temp-file race only with evidence; do not repair unrelated product code.
7. Independently inspect the implementer's two out-of-scope observations, especially the stated pre-existing `install -t /etc/crooks-os /tmp/x` allowance. Determine whether it constitutes a concrete safety-contract bypass requiring rejection. Do not dismiss it merely because it predates R-01; this review is an acceptance gate for the whole harness.
8. Re-state D-19 accurately: live worker tool-surface isolation remains empirically unproven unless separately demonstrated; this review does not authorise that experiment.

### Verdict
Return exactly one:
- `ACCEPT FOR NEXT GATE`, or
- `REJECT — REPAIR REQUIRED`.

Acceptance means only that this candidate is suitable to proceed to the separately governed next harness/isolation gate. It does not authorise merge, production deployment, project `.claude/` activation, global/account changes, connectors, secrets, privileges or business writes.

If rejecting, give a bounded defect list with severity, exact reproducer, why it violates the safety contract, and smallest repair. Do not implement.

Replace only `bridge/claude-outbox.md` with exact identity evidence, reproduced tests/scans, new adversarial probes/findings, production/global/account/worktree invariants, exact verdict and smallest safe next step. STOP after publishing the review.