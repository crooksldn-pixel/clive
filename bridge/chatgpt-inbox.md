# CHATGPT INBOX

## Independent adversarial review of harness candidate `fe96bb661140089647c3e6cb90a269c869a076fa`

Read fresh canonical product memory from `claude/product-memory-foundation` and the latest outbox first. This is a read-only independent review. Do not implement repairs in this round.

### Exact target
- candidate branch: `claude/harness-hooks-experiment`
- candidate: `fe96bb661140089647c3e6cb90a269c869a076fa`
- exact parent / previously rejected candidate: `d7911b24979be2306749b7333ec60edc28cba857`
- accepted Builder base: `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`
- production must remain `1cf3a0f3361b79f9de208d80f501543c53c244b5`

First verify the remote branch still points exactly to `fe96bb6…` and that it is exactly one commit on `d7911b2…`. The Director independently confirmed GitHub currently has that shape and only three changed files: `gitleaks_gate.py`, `guard_bash.py`, and new `test_harness_review_d7911b2_repairs.py`. Treat implementer claims as untrusted until reproduced.

### Review contract
Re-read the previous review's F-1…F-5 findings and the complete `d7911b2…fe96bb6…` diff. Reproduce the repair-specific tests, targeted harness/roster/layout/dev-environment set, full offline suite, Ruff, and pinned redacted gitleaks range scan. The known `query_international_waiting` catalogue-drift failure may only be classified pre-existing if reproduced identically and untouched by this candidate.

Adversarially attack the *root causes*, using new vectors not copied from the repair tests. At minimum probe:
1. relative redirect and copy-like write destinations after `cd`, nested/grouped commands, wrappers, all redirect operators, `../` traversal, glob/brace destinations, no-space redirects, `/etc`, `/root`, and production paths;
2. command substitution/backticks in whole-command, glued-prefix/suffix, assignment, wrapper, pipeline, group, nested, quoted and malformed forms; ensure substitution bodies remain inspected while benign argument substitutions remain usable;
3. dynamic Git subcommands and laundering through env/timeout/sudo-like passthroughs, shell strings, aliases/assignments, substitution and quoting; verify the gitleaks publish gate fails closed consistently;
4. interactions between the new `_segments` substitution lexer and existing heredoc/here-string/shell-fed-text logic, brace expansion, cwd tracking, redirects and glob-prefix handling;
5. parser resource bounds and malformed/nested substitutions, including whether MAX_SUBSTITUTION_NESTING actually fails closed without crash or non-blocking timeout;
6. false-positive/operational impact sufficient to break ordinary Builder commands. Note conservative pre-existing denials separately from regressions.

Also re-check the earlier D-01…D-20 security contract at a high level so the F-1…F-5 repair has not reopened a previously closed bypass. D-19 remains empirically unproven and must not be represented as solved. D-14/worktree/systemd/local-exclude remain untouched and owner-held.

### Hard boundaries
No edits to candidate files; no merge/deploy/install/restart; no `.claude/` activation; no `/root/.claude`, account/global Claude, MCP, connector, identity, credential or secret changes; no watcher/systemd/local Git-config changes; no reset/clean/stash; no production/business writes; no external spend. Explicit branch fetches are acceptable because the Builder's stale deleted-branch refspec still breaks `git fetch --all`; do not repair that here.

### Verdict and handoff
Return exactly one verdict: `ACCEPT FOR NEXT GATE` or `REJECT — REPAIR REQUIRED`.

If rejecting, give a bounded defect list with severity, exact reproducer, observed verdict, required verdict, root cause where known, and smallest safe repair. Do not implement.

If accepting, acceptance only means the harness candidate may proceed to the separately governed next gate; it does not authorise merge, production deployment, project `.claude/` activation, privileges, connectors, secrets or business writes.

Replace only `bridge/claude-outbox.md` with exact identity evidence, reproduced tests/scans, adversarial probes/findings, invariant checks and verdict, then STOP.