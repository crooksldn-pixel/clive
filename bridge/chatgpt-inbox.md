# CHATGPT INBOX

## 2026-09-20 — Bounded repair of harness candidate after d7911b2 adversarial rejection

Repository: `crooksldn-pixel/clive`.

### Target

- candidate branch: `claude/harness-hooks-experiment`
- rejected exact head: `d7911b24979be2306749b7333ec60edc28cba857`
- accepted Builder base remains: `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`
- latest independent review verdict: `REJECT — REPAIR REQUIRED`

Read fresh canonical truth from `claude/product-memory-foundation` and the latest `bridge/claude-outbox.md` before changing anything. Do not trust stale local tracking refs. `git fetch --all` is known to fail because of the deleted `claude/bridge-builder` refspec; explicit branch fetches are acceptable. Do not rewrite that local Git config in this round.

### Scope

Repair only the five findings F-1…F-5 from the latest independent review. They reduce to three bounded root causes:

1. **F-1 relative protected-target resolution:** after a literal `cd` into a protected checkout, relative output redirects/copy-like destinations must be resolved against tracked cwd and denied when they target the protected tree. Cover `>` and `>>` and representative `echo`, `printf`, `cat`; inspect adjacent copy/rsync/install destination handling for the same root cause without widening unrelated policy.
2. **F-2/F-3/F-5 substitution marker gap:** a whole-command `$()` or backtick substitution, and a dynamic command word behind passthrough wrappers/assignments, must fail closed as `UNPARSEABLE`; the gitleaks publish detector must likewise fail closed rather than miss a publish laundered through such a substitution. Repair the shared lexer/segmenter root cause rather than adding string-specific special cases.
3. **F-4 dynamic git subcommand:** if the parsed git subcommand itself is dynamic (`$p`, `${SUB}`, substitution, equivalent), deny `UNPARSEABLE` before destructive flags can be ignored.

Use the exact reproducers in the review as regression tests, then add a small number of neighbouring/adversarial variants that exercise the repaired root causes rather than merely the literal strings. Preserve ordinary safe commands with positive controls.

### Required evidence

- Verify the branch/worktree starts clean at exact `d7911b24979be2306749b7333ec60edc28cba857` before editing. If identity or cleanliness differs, stop and report `BLOCKED`; do not reset, clean or stash.
- Add regression tests for every F-1…F-5 reproducer and the root-cause neighbours.
- Run the repair-specific harness tests and targeted guard/gitleaks/roster/layout/dev-environment tests.
- Run the full offline suite. The review reproduced `query_international_waiting` failing identically on accepted base because of current catalogue/data drift; if and only if that exact unrelated failure reproduces identically, record it as pre-existing rather than modifying product/fixture code in this repair.
- Run Ruff.
- Run redacted gitleaks across `d7911b2…<new-candidate>` with the pinned scanner.
- Confirm clean candidate worktree after commit/push.
- Create exactly one new repair commit on `claude/harness-hooks-experiment`, push it, and read back the exact remote SHA. Do not amend `d7911b2`.
- Report diff/stat and exact test/scan results.

### Hard boundaries

No merge. No production changes or deployment. Do not enter production for writes. No `.claude/` activation. No `/root/.claude`, account/global Claude, MCP, connector, identity or credential changes. No watcher/systemd changes. Do not touch the owner-side `.git/info/exclude`. No destructive reset/clean/stash. No external spend or business writes. D-19 remains empirically unproven and is not part of this repair.

Do not opportunistically refactor the ~2024-line guard beyond what is necessary for these three root causes. Auditability can be addressed separately after correctness is accepted.

### Handoff

Replace only `bridge/claude-outbox.md` with:
- starting identity/cleanliness proof;
- exact files changed and repair explanation mapped F-1…F-5;
- exact new candidate SHA and remote read-back;
- regression/targeted/full-suite/Ruff/gitleaks evidence;
- production/global/account/worktree invariants;
- any blocker or unrelated pre-existing failure clearly separated.

STOP after publishing the new candidate. Do not self-certify it and do not start the next independent review.