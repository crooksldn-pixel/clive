# CHATGPT INBOX

## Independent adversarial review of repaired harness candidate `ef73fbe738cd805c21b9a33b0cc0d36245251658`

Read fresh canonical product memory from `claude/product-memory-foundation` and the latest outbox first. This is a review-only round. Do not implement or repair anything.

### Exact review identity
- candidate branch: `claude/harness-hooks-experiment`
- review target: `ef73fbe738cd805c21b9a33b0cc0d36245251658`
- direct parent: `fe96bb661140089647c3e6cb90a269c869a076fa`
- earlier repaired candidate: `d7911b24979be2306749b7333ec60edc28cba857`
- accepted Builder base: `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`
- production must remain exactly `1cf3a0f3361b79f9de208d80f501543c53c244b5`

Verify the remote branch points exactly to `ef73fbe…`, that it is exactly one commit on `fe96bb6…`, and that production is unchanged. Use explicit branch fetches if required; do not modify the known stale Builder fetch refspec.

### Review contract
Independently reproduce the claimed F-6/F-6b/F-6c/F-6d fixes and attack them with NEW vectors not copied from the implementation tests. Treat the implementer outbox and tests as untrusted evidence until reproduced.

Focus on Bash parsing equivalence and fail-closed behaviour introduced by `_split_redirects`, `_segments`, `_redirect_targets`, `_without_redirections`, `_heredoc_owner`, `_shell_texts`, `_path_rule`, and `_disk_rule`. Probe at minimum:
- glued and spaced `>`, `>>`, `>|`, `&>`, `&>>`, `>&`, `<>`, descriptor forms and chains of multiple redirects;
- quoting, escaping, comments, assignments, wrappers, separators, subshell/group forms and nested substitutions;
- relative/absolute protected targets, cwd changes, traversal, brace/glob/tilde/variable forms, protected hook cwd;
- copy/install destinations followed by redirects;
- heredoc/here-string owners with glued operators/pipes and malformed forms;
- block-device writes;
- gitleaks publish detection through the shared lexer;
- false-negative regressions against F-1…F-5 and D-01…D-20.

Specifically look for places where Bash and the custom lexer disagree, including descriptor-vs-word ambiguity, quoted numeric words, escaped digits/operators, `>&word` versus fd duplication, redirect operands beginning with metacharacters, no-space redirect chains, and malformed input. New parser complexity is not accepted merely because the supplied 292 tests pass.

Re-run the new repair tests, prior harness repair/guard/gitleaks/roster/layout/dev-environment targeted set, full offline suite, Ruff, and pinned redacted gitleaks over `fe96bb6…ef73fbe…`. Record unrelated environmental/baseline failures accurately rather than attributing them to the candidate.

### Verdict
Return exactly one verdict: `ACCEPT FOR NEXT GATE` or `REJECT — REPAIR REQUIRED`.

If rejecting, give a bounded defect list with severity, exact reproducer, observed vs required result, root cause, and smallest safe repair. Do not implement it.

If accepting, state exactly what was independently reproduced, what remains empirically unproven (D-19 remains unproven), and that acceptance does not authorise merge, deployment, project `.claude/` activation, account/global changes, connectors, secrets, privileges, business writes, watcher/systemd changes, or production changes.

Replace only `bridge/claude-outbox.md` with the review handoff and STOP.

### Hard boundaries
No merge/deploy/install/restart; no production writes; no `.claude/` activation; no `/root/.claude`, account/global Claude, MCP, connector, identity, credential or secret changes; no watcher/systemd/local Git-config changes; no reset/clean/stash; no external spend; no owner-side `.git/info/exclude` changes.