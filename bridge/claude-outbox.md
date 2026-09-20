# CLAUDE OUTBOX — latest handoff only

## 2026-09-20T05:32Z — Bounded harness repair of A-01 and A-02 on `claude/harness-hooks-experiment` → new candidate `2c2b0cc` — STOP FOR INDEPENDENT REVIEW

**Inbox consumed:** yes. Blob SHA processed:
`8767e12c53621203ba62ba0f6fdbc50a190775b3` (`bridge/chatgpt-inbox.md`, heading "Bounded harness
repair after independent review of `c16d6db8cd5b7d7a7048462e367339218d178a11`"). These
instructions are now recorded as executed and must not be run again.

**Nothing was merged, deployed, installed, restarted, reset, cleaned, stashed, amended or
force-pushed. No `.claude/` activation. No production, global, account, connector, credential,
watcher/systemd or local Git-configuration change. The only outward actions were explicit
`git fetch` / `git ls-remote` reads of two branches and the ONE `git push` of the candidate
branch the inbox asked for. Implementers do not self-certify: this candidate needs a fresh
independent review bound to the new SHA.**

---

## 1. Identity

| What | Value |
|---|---|
| New candidate commit | **`2c2b0cc4a5f3d82a929eedfa053b5cc46478215f`** |
| Parent (the reviewed head) | `c16d6db8cd5b7d7a7048462e367339218d178a11` (verified before editing: worktree HEAD, local branch and `git ls-remote origin refs/heads/claude/harness-hooks-experiment` all equal) |
| `git rev-list --count c16d6db..2c2b0cc` | **1** (exactly one new commit; `rev-list --parents -n1` = `2c2b0cc c16d6db`) |
| Remote readback after push | `git ls-remote origin refs/heads/claude/harness-hooks-experiment` = **`2c2b0cc4a5f3d82a929eedfa053b5cc46478215f`** |
| Files changed (`git diff --stat c16d6db..2c2b0cc`) | `crooks-assistant/scripts/hooks/guard_bash.py` (+344/−96) and new `crooks-assistant/tests/test_harness_review_c16d6db_repairs.py` (+770). **No `app/`, `config/`, gate, watcher, systemd, `.claude/` or product-memory change** (`git diff c16d6db..HEAD -- crooks-assistant/app crooks-assistant/config` is empty). |
| Candidate worktree `/opt/crooks-builder/.worktrees/harness-hooks-experiment` | branch `claude/harness-hooks-experiment`, HEAD `2c2b0cc`, **0 status lines** (`--untracked-files=all`), stash empty, no `.claude/` |
| Base Builder `/opt/crooks-builder` | `claude/builder-environment-repair` @ `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, clean, untouched |
| Production `/opt/crooks-os/crooks-assistant` | **`1cf3a0f3361b79f9de208d80f501543c53c244b5`**, `claude/linux-prod-migration-production`, **0 status lines**, opened read-only only (`rev-parse`, `branch`, `status`) — unchanged |
| Canonical product memory | `claude/product-memory-foundation` fetched by explicit ref = `c7a1cf64781a2ecfaf17908236404df06033cffe`; `CURRENT_TRUTH.md` read by ref (DEC-048 ratified production SHA above; DEC-049 not exercised — no `.claude/` exists) |
| Bridge worktree | clean before this file was written; only `bridge/claude-outbox.md` is modified now |

The stale Builder fetch refspec was not modified; both branches were fetched explicitly.

## 2. What was asked

Repair exactly A-01 (coreutils `-t`/`--target-directory` destination parsing for `cp` and
`install`, all three option forms, single- and multi-source, scoped so rsync keeps its
semantics) and A-02 (nested command-substitution quote state inside double quotes, repaired at
the shared parser/scanner level, failing closed), with failing-before/passing-after proof, the
exact review reproducers as regression tests, adjacent vectors, positive controls, all prior
harness tests, the targeted sets, the full offline suite, Ruff, pinned redacted gitleaks over
the new range, a clean worktree, exact remote readback and proof production is unchanged.
Cover a directly adjacent sibling only if necessary for the same parser-level repair; otherwise
record it. One new commit on top of `c16d6db`. Replace only the outbox. STOP.

## 3. What was found — reproduced before touching anything

All nine A-01 review reproducers ALLOW on `c16d6db`, plus the glued/bundled spellings
`cp -rt DIR SRC`, `cp -Rvt DIR SRC`, `cp -tDIR SRC`, `install -D -t DIR SRC`,
`install -o root -g root -m 0644 -t DIR SRC`. The A-02 reproducer ALLOWs; its single-line control
DENIES `PROTECTED-PATH`. The same confusion also **hides a later executable line**
(`echo "$(echo "it's")" x⏎rm -rf /opt/crooks-os⏎echo it's` → ALLOW, and bash runs the rm —
witnessed) and **hides a push from the gitleaks gate** (`echo "$(echo "it's")"; git push origin
claude/x⏎echo it's` → `_publish_actions` = `[]`).

Real bash 5.2.21 (the host shell) was run in a scratch directory to witness every semantic the
repair matches before writing it: line 1 of the A-02 reproducer executes (the file is written)
before bash fails on line 2, for both a script file and `bash -c`; `\<newline>` is removed
inside `$( )` and inside backticks, including inside double quotes; a comment inside `$( )`
hides a `)`; single quotes inside `$( )` protect a `)`; quotes inside backticks do NOT protect
the closing backtick and the outer command (with its redirect) still runs; a heredoc inside a
multi-line `"$( )"` works; a heredoc inside single-line backticks does not read the following
lines (they run as commands); a heredoc inside single-line `$( )` DOES read them on 5.2; and a
commented `# <<EOF` reads no body. Scratch removed afterwards.

**Two directly adjacent siblings** (same scanner, same missing state, pre-existing, both
bash-witnessed) were found while giving the heredoc-operator reader the shared state, and were
covered by the same change because the repaired scanner IS the fix:

- **S-1 — a commented heredoc operator read a body.** `echo hi # <<EOF⏎rm -rf /opt/crooks-os⏎EOF`
  → ALLOW on `c16d6db`: the reader has no comment state, so lines 2–3 were stripped as prose
  while bash runs `rm -rf /opt/crooks-os` (line 3 is `EOF: command not found`). HIGH-class
  (hides a production delete). Now `RM-RECURSIVE`.
- **S-2 — a heredoc operator inside single-line backticks read a body.**
  `` echo `cat <<EOF`⏎rm -rf /opt/crooks-os⏎EOF `` → ALLOW on `c16d6db`; bash parses the backtick
  text on its own, so the following lines are commands and the rm runs. Now `RM-RECURSIVE`.

**One A-01-adjacent gap in the same function, same cause (the option grammar was not read)**,
also covered because reading `-t` correctly requires reading the grammar: coreutils permutes
options after operands, so `install /tmp/x /etc/crooks-os/x -m 644`,
`cp /tmp/x /opt/crooks-os/app/main.py --suffix bak` and `install -d /etc/crooks-os/newdir /tmp/b`
were ALLOWED (the last word was an option value or a sibling directory). Witnessed with real
`cp`/`install`: each writes the protected destination. Now `PROTECTED-PATH`.

## 4. What changed (both files at `2c2b0cc`; read in full, not just the diff)

### 4.1 A-01 — `guard_bash.py`

- New constant **`COPY_OPTIONS`** (after `CURL_VALUE_LETTERS`): per command (`cp`, `install`)
  the short letters that take a value, the short letters that take none, the long options that
  take a value (`--opt=V` or `--opt V`), the long options whose value is optional (`--opt[=V]`
  only) and the long options that take none — coreutils 9.x tables.
- New **`_long_option(name, *tables)`**: exact match, else the one option `name` unambiguously
  abbreviates (GNU getopt rule); `None` when unknown or ambiguous.
- New **`_copy_destinations(base, operands) -> list[str]`**: the operands the line writes to.
  Every `-t DIR`, `-tDIR`, `-<flags>t DIR`, `--target-directory DIR`, `--target-directory=DIR`
  and any abbreviation (`--targ DIR`, `--t=DIR`, `--target=DIR`) is a target directory and then
  no operand is a destination (every operand is a source); an option's value is consumed and
  never read as an operand; `install -d`/`--directory` makes every operand a destination; `--`
  ends the options; every target named is returned (two `-t` → both checked). **Fail closed:** an
  unknown long option, an ambiguous abbreviation, an unknown short letter, or a value option
  with nothing after it returns *every* operand, so a protected one is refused rather than
  guessed about (`cp --frobnicate /opt/crooks-os/app/main.py /tmp/` → DENY; `cp -t` alone →
  nothing to check, coreutils refuses the line).
- **`_path_rule`** copy branch split: `cp`/`install` → each destination from
  `_copy_destinations(base, _without_redirections(toks[1:]))` goes through the existing
  `_write_target_problem` (so F-1 relative resolution and PROTECTED-CWD still apply);
  `scp`/`rsync` keep the previous last-operand rule with `remote_ok=True` (rsync `-t` =
  `--times`; scp's sink mode `scp -t DIR` names the directory last and was already denied).
  `mv -t` / `ln -t` were already caught by the general branch (controls included).
- Behaviour change in the permissive direction, deliberate and tested:
  `cp -t /tmp/out /opt/crooks-os/app/main.py /opt/crooks-os/app/x.py` was DENIED on `c16d6db`
  (last operand under production) and is now ALLOWED — it is a read out of production.

### 4.2 A-02 — `guard_bash.py`, shared scanner level

One rule, written as a comment block above `_unquoted_heredoc_ops` and applied by every
quote-tracking scanner: **a `$( … )` or backtick substitution, met unquoted or inside double
quotes, is a command of its own with fresh quote/comment/paren state; it ends at its own `)`
(or first unescaped backtick); the enclosing state resumes after it untouched.** A substitution
that never closes leaves the enclosing state dead (the rest is its text) and the segmenter then
refuses the command as unterminated.

- **`_substitution_end(text, start, nesting=0)`**: for `$( … )` now recurses into a nested `$(`
  or backtick met unquoted or inside its double quotes (so an inner apostrophe never reaches the
  outer state), honours a word-initial `#` comment (a `)` inside a comment closes nothing —
  bash-witnessed), and raises past `MAX_SUBSTITUTION_NESTING` (=16) instead of recursing
  unboundedly. Backtick rule unchanged (first unescaped backtick, whatever quotes sit between).
- **`_scan_continuations(text, nesting=0)`** (R-01's pass): stack-based `$(`/`)` nesting with the
  enclosing quote saved and restored; backtick text scanned recursively with fresh state;
  `\<newline>` removed inside substitutions with the substitution's own quotes deciding
  (single-quoted inside stays literal). No recursion for `$(` (a 16 KB `$($($(…` cannot blow the
  stack); an unterminated backtick resets to fresh state for the remainder. `_join_continuations`
  / `_continued` unchanged in contract; `_segments` and `_tokens` pass nesting through.
- **`_segments`**: a `$(`/backtick **inside double quotes** is now lexed exactly like an
  unquoted one — its body is emitted first as segments of its own and `SUBST_MARKER` takes its
  place inside the quotes — so `_split_redirects` and shlex never meet a nested quote.
  `echo "$(echo "it's")" >/opt/x` → segments `echo "it's"` then `echo "$SUBST" >/opt/x`, tokens
  `["echo", "$SUBST", ">/opt/x"]`, redirect target `/opt/x`. **`_double_quoted_substitutions`
  and its call in `_evaluate_raw` are removed** (their job is now the segmenter's; the body is
  evaluated once, at the same point an unquoted body is). `_evaluate_raw` now also catches a
  `ValueError` from `_strip_heredocs` (→ `UNPARSEABLE`).
- **Heredoc reader**: `_unquoted_heredoc_ops(line)` is a thin wrapper over new
  **`_heredoc_scan(line) -> (ops, owner_start, owner_end)`**, which tracks the same state:
  a `<<` is an operator only outside quotes, outside a comment (S-1), and not inside a backtick
  that closes on the line (S-2); inside a `$( … )` (closed on the line or still open) and inside
  the text of a backtick still open at the end of the line it is reported (bash 5.2, witnessed).
  It also returns where the **owner** of the first operator is written: inside a substitution,
  the substitution's own text (`x="$(cat <<EOF` is owned by `cat`; `echo "$(cat <<EOF)" | bash`'s
  owner text ends at the `)`, and the pipe to a shell is refused by the evaluator on its own —
  `_fed_text` cannot read a `$SUBST` argument → `UNPARSEABLE`). `_strip_heredocs` passes
  `line[owner_start:owner_end]` to `_heredoc_owner` (signature unchanged: prior tests call it
  with one argument).
- Why the owner change was necessary (a regression I caught and fixed before committing):
  giving the heredoc reader the shared state made it report `<<EOF` inside `x="$(cat <<EOF` —
  which `c16d6db` did not see at all — and the old owner logic (`_segments` of the whole line)
  hit the unterminated `$(`, counted the owner as a shell (fail closed) and evaluated the prose
  body as commands, so `x="$(cat <<EOF⏎it's prose⏎EOF⏎)"` went from ALLOW to `UNPARSEABLE`. The
  inbox requires valid quoted-data behaviour to be preserved; it now is (test
  `test_siblings_a_real_heredoc_body_is_still_prose`), while `$(bash <<EOF`, `` `bash <<EOF `` and
  `$(python3 <<EOF` bodies are still evaluated (`RM-RECURSIVE` / `INTERPRETER-SECRET-READ`).
- `_split_redirects` is unchanged: it only ever receives `_segments` output, which no longer
  contains a substitution.
- Module docstring: three recorded limits added (§7).
- The gitleaks gate (`gitleaks_gate.py`, **unchanged**) inherits all of this through
  `_strip_heredocs`/`_segments`/`_tokens`.

### 4.3 What A-02 now does with the reproducer

`echo "$(echo "it's")" >/opt/crooks-os/app/main.py⏎echo it's` → **DENY `UNPARSEABLE`**
("unbalanced quote"): the substitution's apostrophe no longer leaks, so line 2's odd apostrophe
is what it is — an unbalanced quote — and the whole command is refused (fail closed; bash would
execute line 1). Every balanced form is classified, not merely refused:
`echo "$(echo "it's")" >/opt/crooks-os/app/main.py` (one line) → **`PROTECTED-PATH`** (it was
`UNPARSEABLE` by luck on `c16d6db`); the review's control `echo "$(echo "a")" >…` → `PROTECTED-PATH`
as before. A later dangling backslash after a complete first line
(`…>/opt/crooks-os/app/main.py⏎echo '#' \`) → `PROTECTED-PATH` (line 1 is read first).

## 5. Evidence

### 5.1 Failing-before / passing-after (the same test file, hooks swapped)

A scratch copy `/tmp/c16-before/crooks-assistant/scripts/hooks/{guard_bash.py,gitleaks_gate.py}`
was written with `git show c16d6db:…`; `git hash-object` of each copy equals
`git rev-parse c16d6db:<path>` (`5c10c4cf…`, `536970a4…`). The new test file was copied beside it
and run with `--rootdir=/tmp/c16-before` (absolute paths, no `cd`, `-p no:cacheprovider`).

| Hooks | Result |
|---|---|
| `c16d6db` (before) | **414 failed, 144 passed** — the 144 are positive controls and bash/coreutils witnesses, true regardless of the guard |
| `2c2b0cc` (after) | **558 passed** (4.5 s) |

Failing-before groups (count): every-spelling × cp/install × protected-root matrix 240;
`_copy_destinations` grammar 33; redirect after nested quote 17; bundles/values/abbreviations
16; option value never a destination 10; the nine A-01 reproducers 9 (+9 hook-process exits);
A-02 reproducer 1 (+1 process exit); later-malformed-line 7; later-executable-line 4; heredoc
reader state 7; owner-inside-substitution 7; siblings 5 (+5 process exits); sibling prose
controls 5; gate 4; segmenter 3; `_substitution_end` 3 (+2 refusals); continuations 2;
continued-line 1; unreadable lines 3; relative targets 4; valid quoted data 9 (over-blocks on
`c16d6db` such as `echo "$(echo "it's")" >/tmp/x`, now correctly allowed); ordinary copies 2
(the read-out-of-production case). Scratch deleted afterwards.

### 5.2 Test runs on the candidate worktree (base-Builder venv and pinned tooling by absolute path)

| Check | Result |
|---|---|
| New file `tests/test_harness_review_c16d6db_repairs.py` | **558 passed** |
| Prior R-01 file `test_harness_review_ef73fbe_repairs.py` + prior targeted set (`fe96bb6`, `d7911b2`, `review_repairs`, `guard_bash`, `gitleaks_gate`, `roster_assert`, `project_claude_layout`, `dev_env`, `engine_hooks`) — i.e. all D-01…D-20, F-1…F-6, R-01 tests | **1313 passed, 2 skipped** (26.7 s) before the new file was added; **1871 passed, 2 skipped** (30.5 s) with it (1313 + 558) |
| Full offline suite `pytest tests -m "not live" -q -n 4 -p no:cacheprovider`, run **alone** | **4662 passed, 10 skipped, 1 error** (216 s). Arithmetic: 4105 (reviewer's count at `c16d6db`) + 558 = 4663 = 4662 + 1. |
| The 1 error, classified | `tests/test_experience.py::test_the_golden_scenarios[full_address]` — `FileNotFoundError … logs/capabilities.tmp -> capabilities.json` at `app/capabilities/delta.py:45` (`os.replace`): the known `-n 4` writer race in **unchanged product code** (no `app/`/`config/` diff). **Passes alone** (1 passed, 5.4 s); the whole `test_experience.py` run **serially: 85 passed** (203 s). A focused `-n 4` rerun of that file alone reproduced the race once more (1 error) plus the previously recorded tapping-hold flake ("a record already held is replayed, not re-read") — both environmental xdist effects on code this candidate does not touch, both green serially. A trailing `RuntimeError: Event loop is closed` at interpreter shutdown is noise after the summary line. |
| `ruff check app config scripts tests` (ruff 0.16.8) | **All checks passed** |
| gitleaks 8.30.1 (pinned `/opt/crooks-builder/.tooling/bin/gitleaks`) `git --no-banner --redact --exit-code 1 --log-opts=c16d6db..2c2b0cc` | **1 commit scanned, ~54.9 KB, no leaks found, exit 0** |

### 5.3 Witnesses inside the test file (skip if the tool is absent; none skipped here)

Real bash on `tmp_path`: the write happens before the later-apostrophe failure; the hidden line
runs; continuations inside substitutions; a substitution's own quote/comment/paren state; a
backtick ends at the first unescaped backtick and the outer redirect still runs; a commented
operator reads no body; single-line backtick heredoc lines run as commands while a multi-line
backtick reads its body; a heredoc inside `"$( )"` reads its body. Real `cp`/`install` on
`tmp_path`: `-t DIR`, `-tDIR`, `--targ DIR`, `--t=DIR`, `-m644 -t`, `SRC DEST -m 644`,
`SRC DEST --suffix bak`, `-d D1 D2`, `-rt DIR` each write where the guard now says they do.

## 6. Safety constraints — all preserved

`writes_enabled` false; `CROOKS_WRITES_LOCAL_OWNER` false; FastAPI on `127.0.0.1:8000` only
(`ss -ltn`: `127.0.0.1:8000`, nothing on `0.0.0.0`); port 8000 not public; proposal/action/
verification semantics untouched (no `app/`/`config/` change); no live Shopify/Gmail/ElevenLabs
call; the only external mutation is the requested push of the candidate branch; V2 not begun; UI
untouched; Mac deploy/rollback untouched; `/root/.claude` writable and not reconfigured (used only
for this session's memory notes under `projects/`); no account/MCP/connector/identity/credential
change; no watcher/systemd/local-exclude/Git-config change; no `.claude/` activation (none
exists); nothing installed, started, merged, reset, cleaned, stashed, amended or force-pushed;
worktree not moved. `crooks-assistant.service` and `crooks-bridge-watcher.service` both
**active**, not touched. No secret value read, printed or committed (range scan clean). Nothing
was blocked by my own permission layer.

## 7. Decisions and items needing review

1. **Scope taken beyond the two named reproducers, all in the same functions/scanners and
   necessary for a correct repair** — please rule on each: (a) the full coreutils option grammar
   for `cp`/`install` (option values consumed, `-d`, abbreviations, unknown-option fail-closed)
   rather than a `-t`-only patch, because `-t` cannot be located correctly without consuming the
   other options' values, and because `install SRC DEST -m 644` was an equally natural ALLOWED
   write; (b) the two heredoc-reader siblings S-1/S-2; (c) the owner-inside-substitution change,
   which was required to keep valid quoted data allowed once the reader saw operators inside
   `"$( … )"`.
2. **A-02 reproducer verdict is `UNPARSEABLE`, not `PROTECTED-PATH`.** The redirect is no longer
   misclassified — the balanced single-line forms are `PROTECTED-PATH` — but with a genuinely
   unbalanced later quote the segmenter refuses the whole text before rules run. Deliberate fail
   closed; say if the Director wants the first complete line ruled instead.
3. **Bash-version dependency, recorded in the module docstring:** a heredoc inside a `$( … )`
   that closes on its line takes its body from the following lines, matching bash 5.2.21 (the
   host shell; witnessed) — this keeps `$(python3 <<EOF)` / `$(bash <<EOF)` bodies analysed.
   Older bash ran those lines as commands. If the harness must be version-agnostic, the closed
   direction (evaluate those lines as commands AND analyse the body) is a small follow-up.
4. **Recorded, not repaired (docstring, module "Known limits"):** a `case` pattern's bare `)`
   inside a substitution is taken for its end (text after it is still evaluated, nothing hidden);
   two heredocs on one logical line with one inside a substitution still open at its end are read
   in operator order rather than bash's (the outer body is not found → refused as unterminated,
   fail closed, same as `c16d6db`).
5. **Permissive change to confirm:** `cp -t /tmp/out <production files…>` is now ALLOWED as a read
   (was denied by the old last-operand rule).
6. **D-19 remains unresolved**; no live tool-surface isolation experiment was run or is authorised
   by anything here. D-14 unchanged, owner-held.
7. The xdist race in `app/capabilities/delta.py` is now the third round to observe it; it is
   product code outside every harness candidate and may deserve its own bounded ticket.

## 8. Exact proposed next step

**Fresh independent adversarial review of `claude/harness-hooks-experiment` bound to
`2c2b0cc4a5f3d82a929eedfa053b5cc46478215f`** (parent `c16d6db`, one commit, two files):
reproduce §5.1 by swapping the hooks, attack `_copy_destinations` with coreutils spellings not
listed here (bundles mixing value letters, `--no-target-directory` with `-t`, `--update=…`,
operands that look like options after `--`), attack the shared substitution state with new
vectors (unbalanced inner quotes across lines, comments inside nested substitutions, backticks
inside `$( )` inside double quotes, redirects glued to a closing `)"`, heredocs inside
substitutions in every position, the gate's publish detection through each), and rule on §7
items 1–5. Do not merge, deploy, apply `.claude/`, touch the watcher unit or the local exclude
entry, or begin the D-19 live experiment.

## 9. Stop

Repair complete and published as one commit; worktree clean; production unchanged. Only this
file was written in the bridge worktree; the watcher will publish it.

Inbox SHA processed: `8767e12c53621203ba62ba0f6fdbc50a190775b3`
