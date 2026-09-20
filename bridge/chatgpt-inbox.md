# CHATGPT INBOX

## Bounded repair of R-01 on harness candidate `ef73fbe738cd805c21b9a33b0cc0d36245251658`

Read fresh canonical product memory from `claude/product-memory-foundation` and the latest outbox first. The fourth independent review returned `REJECT — REPAIR REQUIRED` with one bounded HIGH defect, R-01. This round is implementation-only: repair R-01, publish one new candidate commit on `claude/harness-hooks-experiment`, provide evidence, and STOP for a fresh independent review. Do not self-certify.

### Exact starting identity
- candidate branch: `claude/harness-hooks-experiment`
- required starting HEAD / parent: `ef73fbe738cd805c21b9a33b0cc0d36245251658`
- its parent: `fe96bb661140089647c3e6cb90a269c869a076fa`
- accepted Builder base: `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`
- production must remain exactly `1cf3a0f3361b79f9de208d80f501543c53c244b5`

Verify remote identity explicitly before editing. If the candidate worktree is not clean, or remote no longer points to `ef73fbe…`, STOP BLOCKED rather than resetting, cleaning, stashing, rebasing, amending or discarding anything. Use explicit branch fetches if required; do not modify the known stale Builder fetch refspec.

### R-01 — required repair
The independent reviewer process-confirmed that Bash removes an unquoted or double-quoted backslash-newline before word splitting, while the shared custom lexer preserves it into the redirect target/operand. This allows protected writes/copies/deletes to be mis-resolved as relative paths.

At minimum these exact forms must fail closed after the repair (the `\\` is immediately followed by a real newline):

    echo x >\\
    /opt/crooks-os/app/main.py

    echo x>\\
    /opt/crooks-os/app/main.py

    cp /tmp/x \\
    /opt/crooks-os/app/main.py

    rm -rf \\
    /opt/crooks-os

Required classifications: protected redirect/copy targets must DENY `PROTECTED-PATH`; recursive production delete must DENY `RM-RECURSIVE`.

Implement the smallest parser-level, quote-aware correction in the shared lexing pipeline so guard and gitleaks parsing inherit it. Match Bash semantics for backslash-newline removal: unquoted and double-quoted continuation is removed before tokenisation; single-quoted backslash-newline remains literal. Do not add command-string-specific patches. Fail closed on ambiguity.

### Required adversarial regression coverage
Add failing-before/passing-after tests for the four review reproducers plus NEW neighbouring vectors, including:
- continuation adjacent to glued and spaced redirect operators and descriptor redirects;
- continuation in copy/install/delete operands;
- continuation after `cd` with relative protected destinations;
- double-quoted continuation semantics;
- single-quoted continuation positive control demonstrating Bash keeps it literal and that benign behaviour is not overblocked;
- continuation inside an ordinary command/word;
- chained redirects and shell wrappers where relevant;
- gitleaks publish detection through the shared lexer, proving a continuation cannot launder a publish action.

Run the new tests against the pre-repair `ef73fbe…` source and record the expected failures, then against the repaired source and require pass.

### Verification before publication
Re-run:
1. new R-01 regression tests;
2. all prior harness review repair tests including `test_harness_review_fe96bb6_repairs.py`, d7911b2 repairs, guard, gitleaks, roster, project-Claude-layout and dev-environment targeted tests;
3. full offline suite;
4. Ruff over `app config scripts tests`;
5. pinned redacted gitleaks over `ef73fbe…<new-candidate>`.

The known accepted-base `test_experience.py::test_a_record_reached_by_tapping_is_still_held_a_moment_later` failure may be classified as baseline only if it reproduces unchanged and there is still no relevant candidate diff. Do not repair unrelated product code in this round.

Publish exactly one NEW commit on `claude/harness-hooks-experiment` (no amend/rebase/force push). The outbox must state exact new SHA and parent, changed files, failing-before/passing-after evidence, targeted/full-suite/Ruff/gitleaks results, clean worktree/stash state, remote branch identity, and confirmation production/global/account/connector/service state was untouched. Then STOP for independent review.

### Hard boundaries
No merge/deploy/install/restart; no production writes; no project `.claude/` activation; no `/root/.claude`, account/global Claude, MCP, connector, identity, credential or secret changes; no watcher/systemd/local Git-config changes; no reset/clean/stash; no external spend; no owner-side `.git/info/exclude` changes; no unrelated refactor or scope expansion.