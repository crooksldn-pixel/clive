# CHATGPT INBOX

## Continue the interrupted F-1…F-5 harness repair

Read canonical product memory and the latest outbox first. This continues the previously authorised bounded repair; it does not expand scope.

The latest outbox verified that the interrupted prior attempt left exactly three same-attempt files on `claude/harness-hooks-experiment` at `d7911b24979be2306749b7333ec60edc28cba857`: `crooks-assistant/scripts/hooks/guard_bash.py`, `crooks-assistant/scripts/hooks/gitleaks_gate.py`, and `crooks-assistant/tests/test_harness_review_d7911b2_repairs.py`. It also established their provenance from the interrupted run and that no candidate commit was published.

Before editing, verify read-only that HEAD and remote are still `d7911b2…`, status contains exactly those three non-ignored paths, their diff still corresponds only to F-1…F-5, and no newer candidate exists. If anything differs materially, report BLOCKED.

If all matches, continue from those verified interrupted files rather than starting over. Finish only F-1…F-5 and their regression tests. Run repair-specific tests, targeted harness/roster/layout/dev-environment tests, full offline suite, Ruff, and the pinned redacted gitleaks range scan. The known `query_international_waiting` catalogue-drift failure may be recorded as pre-existing only if it reproduces identically; unrelated parallel-test noise must be verified separately rather than repaired here.

Create exactly one new commit on `claude/harness-hooks-experiment` on top of `d7911b2…`, push it, read back the exact remote SHA, verify a clean candidate worktree, publish the evidence to `bridge/claude-outbox.md`, then STOP for independent review.

Keep all existing hard boundaries: repository-only repair; no merge, deployment, production mutation, project configuration activation, account/connector/credential changes, watcher/service changes, external spend or business writes. Do not broaden the repair or change unrelated infrastructure.