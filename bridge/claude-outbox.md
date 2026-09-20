# CLAUDE OUTBOX — latest handoff only

## 2026-09-20T06:27Z — Sixth independent adversarial review of `claude/harness-hooks-experiment` @ `2c2b0cc` — verdict below

**Inbox consumed:** yes. Blob SHA processed:
`00cb6e121210be0cc771d6bfedac0b9144a3cf11` (`bridge/chatgpt-inbox.md`, heading "Fresh
independent adversarial review — harness candidate
`2c2b0cc4a5f3d82a929eedfa053b5cc46478215f`"). These instructions are now recorded as executed
and must not be run again.

**This was an INDEPENDENT REVIEW, not implementation.** Nothing was modified on the candidate
branch, merged, deployed, installed, restarted, reset, cleaned, stashed, amended or
force-pushed. No `.claude/` activation. No production, global, account, connector, credential,
watcher/systemd or local Git-configuration change. No live tool-surface isolation experiment
(D-19). The only outward actions were read-only `git fetch` / `git ls-remote` of three branches.
The candidate worktree was not written to. Scratch was created and deleted under `/tmp` only.

---

## VERDICT

**`ACCEPT FOR NEXT GATE`.**

No substantive harness defect remains within this review scope. The two rejected defects (A-01,
A-02) and the two adjacent heredoc-reader siblings (S-1, S-2) reproduce as ALLOW on the parent
`c16d6db` and are closed on `2c2b0cc`. The repair was attacked with new vectors beyond its own
tests — coreutils spellings, nested/backtick/comment substitution states, malformed-later-state
laundering, heredocs inside substitutions in every position, and the gitleaks publish path — and
every attack fails closed (DENY or, where the text is genuinely ambiguous, `UNPARSEABLE`). The
previously closed contracts (D-01…D-20, F-1…F-6, R-01) still hold. Recorded, non-blocking limits
are in §6; D-19 remains unresolved and owner-held.

Implementers do not self-certify; this verdict is the reviewer's, bound to the exact SHA below.

---

## 1. Review subject and identity — independently verified

| What | Value |
|---|---|
| Branch | `claude/harness-hooks-experiment` |
| Candidate commit (remote readback) | `git ls-remote origin refs/heads/claude/harness-hooks-experiment` = **`2c2b0cc4a5f3d82a929eedfa053b5cc46478215f`** |
| Parent | `git rev-parse 2c2b0cc^` = **`c16d6db8cd5b7d7a7048462e367339218d178a11`** (as required) |
| Commit count over parent | `rev-list --count c16d6db..2c2b0cc` = **1**; `rev-list --parents -n1 2c2b0cc` = `2c2b0cc c16d6db` |
| Diff (`--name-status c16d6db..2c2b0cc`) | exactly two files: **M** `crooks-assistant/scripts/hooks/guard_bash.py` (+344/−96), **A** `crooks-assistant/tests/test_harness_review_c16d6db_repairs.py` (+770). `--stat`: 2 files, 1114 insertions, 96 deletions. No `app/`, `config/`, gate, watcher, systemd, `.claude/` or product-memory change (`git diff c16d6db..2c2b0cc -- crooks-assistant/app crooks-assistant/config` empty). |
| `gitleaks_gate.py` at candidate | unchanged from parent (`rev-parse 2c2b0cc:…gitleaks_gate.py` == `c16d6db:…` == `536970a4…`) — it inherits the scanner fixes through `guard_bash`. |
| Remote | `origin` = `https://github.com/crooksldn-pixel/clive.git` (canonical `crooksldn-pixel/clive`). Branches fetched explicitly (the stale Builder refspec for deleted `claude/bridge-builder` was not touched; `main` does not exist remotely — expected). |
| Candidate worktree `/opt/crooks-builder/.worktrees/harness-hooks-experiment` | HEAD `2c2b0cc`, branch `claude/harness-hooks-experiment`, **0 status lines** (`--untracked-files=all`) before and after the review, no `.claude/` present. |
| Base Builder `/opt/crooks-builder` | `claude/builder-environment-repair` @ `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, untouched. |
| Production `/opt/crooks-os/crooks-assistant` | **`1cf3a0f3361b79f9de208d80f501543c53c244b5`** (ratified DEC-048), branch `claude/linux-prod-migration-production`, **0 status lines**, opened read-only only. Unchanged. |
| Canonical product memory | `claude/product-memory-foundation` fetched by ref = `c7a1cf64781a2ecfaf17908236404df06033cffe`; CURRENT_TRUTH, DECISIONS (through DEC-049), ROADMAP, ENGINEERING_ORCHESTRATOR_V1, DEV_TEAM_V1_PILOT, ENGINEERING_STACK_REUSE_PLAN and MIGRATION_HANDOFF read by ref. |

## 2. What was asked

Independently review `2c2b0cc` (parent `c16d6db`, production untouched at `1cf3a0f`). Verify
remote identity and the actual diff. Treat A-01 (coreutils `cp`/`install` target-directory and
option-grammar destination parsing) and A-02 (nested command-substitution quote-state
fail-open) and the adjacent scanner/heredoc siblings as untrusted until reproduced. Attack the
repair rather than merely rerunning its tests; re-check the previously closed contracts with new
vectors; inspect the implementation for fail-open paths; reproduce the regression evidence, run
Ruff and pinned redacted gitleaks over `c16d6db..2c2b0cc`, verify clean state, remote SHA, and
production invariants read-only. Return exactly one verdict. Do not repair; replace only the
outbox; STOP.

## 3. Commands run and raw result summaries

All tooling by absolute path from the base Builder (the worktree has no `.venv`/`.tooling`).

| Check | Result |
|---|---|
| Failing-before, parent hooks: `git show c16d6db:…{guard_bash,gitleaks_gate}.py` into `/tmp/rv-c16-before`, candidate test file beside it, `pytest --rootdir=/tmp/rv-c16-before` | **414 failed, 144 passed** (copies proven: `hash-object` == `rev-parse c16d6db:<path>`, `5c10c4cf…` / `536970a4…`). The 144 are positive controls + bash/coreutils witnesses. |
| Passing-after, candidate: `pytest tests/test_harness_review_c16d6db_repairs.py` | **558 passed** (4.3 s) |
| Prior regression files `test_harness_review_ef73fbe_repairs.py` (R-01), `test_harness_review_repairs.py` (D-01…D-20, F-1…F-6), `test_guard_bash.py`, `test_gitleaks_gate.py` | **896 passed** (23 s) |
| Full offline suite `pytest tests -m "not live" -q -n 4`, run **alone** | **4661 passed, 10 skipped, 2 errors** (218 s). Arithmetic: 4105 (parent baseline) + 558 = 4663 = 4661 + 2. |
| The 2 errors, classified | `tests/test_routes.py::test_speak_says_the_prepared_text_not_the_written_one` and `::test_state_carries_what_was_heard_while_thinking` — both `FileNotFoundError … logs/capabilities.tmp -> capabilities.json` at `app/capabilities/delta.py:45` (`os.replace`): the known `-n 4` writer race in **unchanged product code**. **Both pass serially** (2 passed, 1.0 s). Same race the last three rounds recorded; it lands on a different test file each run. Not a candidate regression (candidate touches no `app/`). |
| `ruff check app config scripts tests` (ruff 0.16.8), run **alone** | **All checks passed** (a first parallel run printed spurious errors from shared-shell CWD interference with a scratch-cleanup command; re-run alone it is clean — the guard file lints clean). |
| gitleaks 8.30.1 (pinned `/opt/crooks-builder/.tooling/bin/gitleaks`) `git --no-banner --redact --exit-code 1 --log-opts=c16d6db..2c2b0cc <worktree>` | **1 commit scanned, ~54.9 KB, no leaks found, exit 0** |
| Host shells for cross-checks | bash 5.2.21, cp/install (GNU coreutils) 9.4 |

## 4. Adversarial findings — the attack, and what happened

### 4.1 A-01 (coreutils destination) — closed, and holds against new spellings

All nine review reproducers ALLOW on `c16d6db`, DENY `PROTECTED-PATH` on `2c2b0cc`; the hook
process exits 2 and never echoes the operand. New vectors beyond the candidate's own tests, run
against `2c2b0cc`:

- `cp -t /opt/crooks-os/app --no-target-directory /tmp/x` → **DENY** (target seen before the
  conflicting flag; coreutils would error, denying is safe).
- `cp --update=older -t …` (optional-value long option consumed) → **DENY**.
- `install --strip -t …`, `cp --parents … /opt/crooks-os/app/`, `cp -rft /etc/crooks-os …`,
  `cp --reflink[=always] -t …`, `install -Dt …`, `install -o root -t … -- /tmp/x`,
  `cp -t/opt/crooks-os/app/ …` → **DENY** each.
- `install --s /tmp/x /opt/crooks-os/app` (ambiguous abbreviation: strip / strip-program /
  suffix) → **DENY** every operand (fail closed; coreutils errors).
- `cp -- -t /opt/crooks-os/app /tmp/x` → **ALLOW** (after `--`, dest is last `/tmp/x`; `app` is a
  read-out source) — correct.
- `cp -tv /opt/crooks-os/app /tmp/x` and `cp -St /opt/crooks-os/app /tmp/x` → **ALLOW**: in both,
  the letter that takes a value swallows the next bundle char (`-t` value `v`; `-S` value `t`), so
  `/opt/crooks-os/app` is a **source**, copied out — a read, correctly allowed. Verified this is
  exactly what GNU cp 9.4 does.

rsync/scp/mv/ln scoping confirmed by the candidate's own parametrised test and re-read in source:
`rsync -t` keeps `--times` (dest last), `scp -t DIR` sink mode names the dir last, `mv -t`/`ln -t`
are caught by the general branch. Reads out of production (`cp -t /var/tmp/out
/opt/crooks-os/app/main.py`) are correctly ALLOWED.

### 4.2 A-02 (nested substitution quote state) — closed, and cannot launder a later line

The reproducer `echo "$(echo "it's")" >/opt/crooks-os/app/main.py⏎echo it's` is ALLOW on
`c16d6db` and **DENY `UNPARSEABLE`** on `2c2b0cc`; balanced single-line forms are
`PROTECTED-PATH`. New attacks, all against `2c2b0cc`:

- nested `$( $( ) )`, backtick-around-`$()`, comment-inside-spanning-lines, glued `)">` → all
  **DENY `PROTECTED-PATH`**.
- **The security-critical direction — can a malformed later state hide an earlier action?** No:
  - `rm -rf /opt/crooks-os # "$(echo "it's)"` (bash runs the rm; the broken sub is in a comment)
    → **DENY `RM-RECURSIVE`**. Bash cross-check: the marker file is created, i.e. bash really
    runs it, and the guard catches it.
  - `x="$(echo "a")" y="$(rm -rf /opt/crooks-os)"`, `echo "$(echo "a")" && rm -rf /opt/crooks-os`,
    `echo "$(echo "a")"; rm -rf …` → **DENY `RM-RECURSIVE`**.
  - `echo "$(cat /etc/crooks-os/credentials/x)"` → **DENY `SECRET-FILE-READ`**.
  - `echo "$(echo "it's")"; git push --force origin main` → **DENY `GIT-PUSH-FORCE`**;
    `… | git push origin main` → **DENY `GIT-PUSH-PROTECTED-REF`**.
  - a body that runs (`echo "$(rm -rf /opt/crooks-os)" >/tmp/x`) → **DENY `RM-RECURSIVE`**.
- Reading the parser: an unbalanced quote anywhere makes `_segments` raise → `UNPARSEABLE`
  (fail closed); a substitution the scanner cannot close raises → `UNPARSEABLE`;
  `MAX_SUBSTITUTION_NESTING`=16 bounds recursion in `_substitution_end` / `_scan_continuations`.
  I could not construct a vector where the scanner treats as *data* something bash runs as a
  *command*, other than the two siblings below, which are fixed.

### 4.3 Siblings S-1/S-2 (heredoc-operator reader) — closed, bash-confirmed

- `echo hi # <<EOF⏎rm -rf /opt/crooks-os⏎EOF` (and `;#`, `#<<EOF` forms) → **DENY `RM-RECURSIVE`**.
- `` echo `cat <<EOF`⏎rm -rf /opt/crooks-os⏎EOF `` → **DENY `RM-RECURSIVE`**.
- Bash cross-check: for both, bash creates the marker (runs the "hidden" line), so the guard is
  right to read it as a command. The valid-data controls (`echo hi '#' <<EOF`, `x=$(cat
  <<EOF…EOF)`, quoted/spanning heredocs, prose bodies with apostrophes) stay **ALLOWED**, and
  shell/interpreter owners inside substitutions (`$(bash <<EOF)`, `$(python3 <<EOF)`) are still
  evaluated (`RM-RECURSIVE` / `INTERPRETER-SECRET-READ`).

### 4.4 gitleaks publish detection — sees the push through every laundering form

`gate._publish_actions` correctly returns the push for: after a nested substitution
(`echo "$(…)"; git push origin claude/x`), behind a commented heredoc operator, after a
backtick that closes on its line, and across an R-01 line continuation (`git \<newline>push …`).
A message built from a substitution becomes the marker (`git commit -m "$SUBST"`). A malformed
later line **raises `ValueError`** and `run_gate` returns `UNPARSEABLE` (fail closed) rather than
laundering the push — reproduced directly.

### 4.5 Previously closed contracts — re-checked with new vectors, still hold

R-01 continuation handling, D-01 (secret store never named — incl. inside a substitution),
D-02…D-20 and F-1…F-6 all pass in the 896-test regression run and were spot-attacked live
(secret-file-read inside `$()`, force-push inside `$()`, protected redirect glued to `)"`,
`echo "$(rm …)"` body execution). No fail-open observed.

## 5. Production invariant evidence (read-only)

- `writes_enabled` false, `CROOKS_WRITES_LOCAL_OWNER` false: `/opt/crooks-os/crooks-assistant/.env`
  shows `CROOKS_WRITES_ENABLED=false` and `CROOKS_WRITES_LOCAL_OWNER=false` (values not otherwise
  printed).
- FastAPI on `127.0.0.1:8000` only: the unit's `ExecStart` binds `--host 127.0.0.1 --port 8000`;
  `ss -ltn` shows `127.0.0.1:8000` and Tailscale `100.72.82.24:443`, nothing on `0.0.0.0:8000`.
  Port 8000 not public.
- `crooks-assistant.service` and `crooks-bridge-watcher.service` both **active**, untouched.
- Production checkout byte-state: `1cf3a0f`, 0 status lines, not modified.
- No live Shopify/Gmail/ElevenLabs call; no external mutation of any kind; V2 not begun; UI
  untouched; Mac deploy/rollback untouched; `/root/.claude` writable, used only for this
  session's memory notes under `projects/`, not reconfigured; no `.claude/` activation (none
  exists in the checkout). Range gitleaks scan clean, so no secret is in the candidate diff.

## 6. Limitations of this review, and recorded (non-blocking) limits of the harness

- **Text hook, not a boundary.** The guard reads command text; symlink aliasing, script-file
  contents, `PATH` hijack and variable-valued paths are out of scope by design (module docstring).
  The real boundaries are the systemd sandbox, the permission layer and the builder/production
  split.
- **`cp`/`install` option values that name a production path to *execute*, not write** — e.g.
  `install --strip-program=/opt/crooks-os/bin/s /tmp/x /tmp/y` is ALLOWED: the destination is
  `/tmp/y` (a legitimate write) and the strip-program is an existing production binary the guard
  treats as a read. This runs a production binary rather than writing production. Low severity,
  outside the A-01 write-destination contract; recorded for the Director, not a blocker.
- **Bash-version dependency (documented in the module docstring):** a heredoc inside a `$( … )`
  that closes on its line takes its body from the following lines, matching bash 5.2.21 (the host
  shell). Older bash would run those lines as commands. If the harness must be version-agnostic,
  the closed direction is a small follow-up. Not a fail-open on 5.2.
- **Recorded, not repaired (docstring):** a `case` pattern's bare `)` inside a substitution is
  taken for its end (text after it is still evaluated — nothing hidden); two heredocs on one
  logical line with one inside a still-open substitution are read in operator order and refused as
  unterminated (fail closed). Verified these are the current behaviour; neither hides an action.
- **D-19 remains unresolved** and owner-held; no live tool-surface isolation experiment was run
  or authorised. D-14 unchanged.
- I did not execute any real destructive/protected/publish command; bash cross-checks used
  harmless marker files under a throwaway `/tmp` directory to witness *which line bash runs*, then
  compared that to the guard's static verdict.

## 7. Decisions / items for the Director (carried from the implementer's §7; my read)

The implementer asked the Director to rule on scope taken beyond the two named reproducers. My
review finds each in-scope and correct: (a) the full coreutils option grammar is necessary to
locate `-t` at all and to stop `install SRC DEST -m 644` writing the real destination; (b) S-1/S-2
are the same scanner and the same missing state as A-02; (c) the owner-inside-substitution change
is required to keep valid quoted data allowed once the reader sees operators inside `"$( … )"`.
The A-02 reproducer verdict is `UNPARSEABLE` (fail closed on a genuinely unbalanced later quote),
not `PROTECTED-PATH`; I judge this correct and safer than ruling only the first line. These are
engineering-correct; whether to narrow them is the Director's call, not a defect.

## 8. Exact proposed next step

**Accept `2c2b0cc` for the next gate.** Fold the harness acceptance state into canonical product
memory (CURRENT_TRUTH / DEV_TEAM_V1_PILOT), noting that A-01/A-02 and siblings S-1/S-2 are closed
and the guard/gate scanners are reviewed correct at this SHA. Do **not** merge, deploy, apply
`.claude/`, touch the watcher unit or the Builder's local exclude entry, provision secrets, or
begin the D-19 live experiment — all remain owner-gated. If the Director wants the
strip-program-execution note (§6) or the bash-version-agnostic heredoc direction closed, that is a
new bounded repair round with a fresh commit on top of `2c2b0cc`, then another independent review.
The `app/capabilities/delta.py` xdist writer race is now observed across four rounds in unchanged
product code and deserves its own bounded ticket, separate from the harness.

## 9. Stop

Review complete and published as this one file. Nothing else in the bridge worktree was written;
the watcher will publish it. Verdict: **ACCEPT FOR NEXT GATE**.

Inbox SHA processed: `00cb6e121210be0cc771d6bfedac0b9144a3cf11`
