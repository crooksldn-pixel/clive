# CLAUDE OUTBOX — latest handoff only

## 2026-09-19T21:26Z — Repair round for rejected harness candidate `dd50ebb`: new candidate `d7911b2` pushed

**Inbox consumed:** yes. Blob SHA processed: `4843e76fb5523a4486c1d275f67842d3ab567ef3`
(`bridge/chatgpt-inbox.md`, heading "2026-09-19 — Repair rejected harness candidate after
independent review"). These instructions are now recorded as executed and must not be run again.

**Result.** Exactly one new commit on `claude/harness-hooks-experiment`, on top of the rejected
candidate, pushed and read back from the remote:

| | SHA |
|---|---|
| **New candidate (this round)** | `d7911b24979be2306749b7333ec60edc28cba857` |
| Parent = rejected candidate | `dd50ebbca6eca9c4e2ee1e85ad17d2c7e5afd25e` |
| Accepted Builder base | `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` |
| Remote `refs/heads/claude/harness-hooks-experiment` (`git ls-remote` after push) | `d7911b24979be2306749b7333ec60edc28cba857` |

`git rev-list --left-right --count 295e483…...d7911b2…` → `0 2`; `d7911b2^` = `dd50ebb…`;
merge-base with the rejected candidate = `dd50ebb…`. Author `Claude <noreply@anthropic.com>`,
2026-09-19 21:25:34 UTC. 8 files, +1869/−242. Not merged, not deployed, nothing under `.claude/`
written. **This is a review candidate. It is not accepted, and no hook is active anywhere: the
`.claude/settings.json` that would register the hooks is still the owner's pending apply step.**
No owner approval is inferred for anything.

**Recommendation: a fresh independent adversarial review of `d7911b2…`**, base `dd50ebb…`,
with the same read-only contract as the review of inbox `2b1030bd…`. This round does not
certify its own work (pilot §5).

---

## 1. What was asked

One bounded repair round for the independently rejected candidate: repair D-01…D-12, D-15…D-18,
D-20, the stale root `CLAUDE.md` test count, and record D-14 and D-13/D-19 dispositions; one
negative test per defect using the review's vectors with failing-before/passing-after evidence;
re-run targeted tests, full offline suite, Ruff and gitleaks; exact identity; clean worktree;
push and read back; do not remove/relocate the worktree, do not touch the local exclude entry or
the watcher unit, no `.claude/` writes, no account/global/connector/identity changes, no merge, no
self-certification. Repository is now `crooksldn-pixel/clive`; fetch fresh refs.

## 2. Checkout state — start and end

| Repo | Branch | Start | End |
|---|---|---|---|
| Builder `/opt/crooks-builder` | `claude/builder-environment-repair` (unit env still says `claude/bridge-builder`; untouched) | `295e483b…`, clean (`--untracked-files=all`, 0 lines) | unchanged, clean. `.git/info/exclude` still ends with the owner's `.worktrees/` line — **not touched** |
| Candidate worktree `/opt/crooks-builder/.worktrees/harness-hooks-experiment` | `claude/harness-hooks-experiment` | `dd50ebb…`, clean | **`d7911b2…`**, clean (0 status lines); not moved, not removed |
| Bridge `/opt/crooks-ai-bridge` | `crooks-ai-bridge` | `f1055c3f…`, clean | only `bridge/claude-outbox.md` modified (this file) |
| Production `/opt/crooks-os` (read-only, `git rev-parse`/`status` only) | `claude/linux-prod-migration-production` | `1cf3a0f3…`, clean | `1cf3a0f3…`, clean, never entered for anything else |

Fresh refs: `git fetch --all` **fails** in the builder (`fatal: couldn't find remote ref
refs/heads/claude/bridge-builder` — its only fetch refspec names a branch that no longer exists on
`crooksldn-pixel/clive`), so branches were fetched explicitly: `claude/product-memory-foundation`
at `052a27d496845a4c8b8eddb5c32685a3892b6a72` (the inbox's stated head — confirmed on the remote),
`claude/harness-hooks-experiment` at `dd50ebb…`, `claude/builder-environment-repair-review` at
`295e483…`. Canonical truth read at `052a27d…` by `git show`: CURRENT_TRUTH (rename complete,
harness review verdict, D-14 incident and durable lesson, DEC-049 scope), DECISIONS DEC-048/049,
DEV_TEAM_V1_PILOT §5. The review outbox (inbox `2b1030bd…`) was read from bridge commit `dfe7028`
and its exact vectors are the tests. Note for future rounds: the stale refspec is a builder-clone
configuration fact, not something this round changed.

## 3. What was found (the review's defects, reproduced)

Before touching source, the new test file `tests/test_harness_review_repairs.py` (the review's
command strings, one section per defect) was run against the rejected source at `dd50ebb…`:
**162 failed, 18 passed** of 180. The 18 passes are the "still allowed" halves and a few vectors
the rejected code already caught (`cp x /opt/crooks-os/{a..c}`, `cd …; cd ..; git pull`,
`pushd/popd`, `export -p`, `cat < crooks-assistant/.env`, `rm -rf /root/.cache/x`). Every H defect
reproduced exactly as the review stated.

**Found while repairing, not in the review:** `_protected_hit` matched a glob whose literal prefix
sat *above* a protected root (`/opt/*`) but never one whose prefix sat *under* it, so
`cp x /opt/crooks-os/*`, `echo x > /etc/systemd/system/*.service` and
`tee /opt/crooks-os/crooks-assistant/config/*.py` were **ALLOW** on `dd50ebb…` (verified against
the rejected guard after the fact: all ALLOW). Fixed and tested
(`test_found_during_repair_a_glob_under_a_protected_root_is_inside_it`).

## 4. What changed — per defect

All in one commit, `d7911b2…`. File-level: `scripts/hooks/guard_bash.py` (1340 → 2024 lines),
`scripts/hooks/gitleaks_gate.py` (194 → 258), `scripts/roster_assert.py` (146 → 209),
`tests/test_harness_review_repairs.py` (new, 715 lines, 181 tests), root `CLAUDE.md`,
`docs/DEV_ENVIRONMENT.md`, `docs/dev-environment/WORKER_TOOL_SURFACE_ISOLATION.md`,
`docs/dev-environment/PROJECT_CLAUDE_FILES_PENDING.md`. No other file. The lexer, input contract,
ported ECC table and every existing rule id are unchanged; new rule ids are `NESTED-CLAUDE-SESSION`,
`PROJECT-CLAUDE-WRITE`, `GIT-HOOKS-WRITE`, `GIT-CONFIG-EXEC`, `INTERPRETER-SECRET-READ`,
`NETWORK-MUTATION`, `PUBLIC-BIND`, `INTERNAL-ERROR` (stderr only).

| Defect | Repair (in `guard_bash.py` unless stated) | Evidence (test name / vectors) |
|---|---|---|
| **D-01 H** | `SECRET_DIRS = (/etc/crooks-os/credentials, /etc/crooks-os/secrets)`; any token or assignment value reaching either, in any command (reads, `ls`, `cd`, `cp`, `tar`, globs one level up) → `SECRET-FILE-READ`. `SECRET_FILE_RE` gains `.*\.cred`, `.*signing_key`. Values never opened. | `test_d01_*` — the review's four vectors plus six more; `ls -la /etc/crooks-os` still allowed |
| **D-02 H** | `_git_read_only("stash", [])` → False; bare `git stash` gets irreversibility context in the builder | `test_d02_*`: `git -C /opt/crooks-os stash` → PROTECTED-PATH; `cd /opt/crooks-os && git stash` → PROTECTED-CWD |
| **D-03 H** | Command word containing `$`, backtick, `{`, `*`, `?`, `[` (except `[`/`[[`) → `UNPARSEABLE`, checked at every unwrap step (sudo/timeout/xargs/find -exec too). The segmenter marks a command whose word is produced by `$(…)`/backtick (`$SUBST` marker; the substitution body is still evaluated on its own). `eval`, `watch`, `su -c`, `env -S` are shell strings: evaluated when literal, refused when they carry `$`/backtick. | `test_d03_*`: all seven review vectors + `$(echo git) push`, `` `echo git` push ``, `{git,x} push`, `/usr/bin/gi? push`, `env -S`, `watch`, `su -c`; `echo y \| $(rm -rf /tmp)` still RM-RECURSIVE |
| **D-04 H** | `_shell_texts`: a shell's `-c` string, `<<<` operand, heredoc (already evaluated) and script positional are enumerated; a shell that is piped, bare, `-s`, `-`, `< file` or `<(…)` is refused unless the pipe's left side is a literal `echo`/`printf` (no `$`, backtick, backslash, `%`, `-e`) whose text is then evaluated. Same for an interpreter reading stdin. `_heredoc_owner` reads the whole line. | `test_d04_*`: all six review vectors + 16 more; `bash script.sh`, `sh <<'EOF'`, `echo 'ls' \| sh`, `cat data \| python3 script.py` still allowed |
| **D-05 M** | `_tokens` returns the dropped assignments; `env NAME=value` collected too; a value reaching a protected path denies unless the command is read-only; `GIT_DIR`/`GIT_WORK_TREE`/`GIT_COMMON_DIR`/`GIT_INDEX_FILE`/`GIT_OBJECT_DIRECTORY` are git global-option paths (read-only git still passes). | `test_d05_*`: both review vectors + 5 |
| **D-06 M** | `_git_subcommand` now returns a `_GitCall` with `-c`/`--config-env` values; `core.hookspath` → `GIT-CONFIG-HOOKSPATH`; keys whose value is a command git runs (`core.fsmonitor`, `core.sshCommand`, `core.pager`, `core.editor`, `credential.*`, `alias.*`, `filter.*`, `diff.external`, …) → `GIT-CONFIG-EXEC`, for `-c` and for `git config` writes. `git config --get core.hooksPath` is a read again (review false positive). | `test_d06_*` |
| **D-07 M** | `_claude_rule` is an allow-list: `--version/-v/--help/-h/doctor` and read-only `mcp list/get`, `plugin list`, `config get/list/ls`; every other invocation → `NESTED-CLAUDE-SESSION` (covers `-p`, `--print`, `--permission-mode`, `--bare`, `--mcp-config`, `--setting-sources`, `--plugin-dir`, bare `claude`, a prompt). | `test_d07_*`: the review's four vectors + 6 |
| **D-08 M** | Any token with a `.claude` path component, or `.git/hooks`, in any spelling: redirect target, cp/rsync/install destination, or argument of a non-read-only command → `PROJECT-CLAUDE-WRITE` / `GIT-HOOKS-WRITE`; `rm -rf .claude` → RM-RECURSIVE. Reads, `git add/commit/diff/status/reset` of those paths stay allowed. | `test_d08_*`: the review's four vectors + 12 |
| **D-09 M** | curl short-option bundles parsed with value-taking letters (`-XPOST`, `-sSXPOST`, `-d'{}'`, `-sS -XDELETE`); package verb = first non-dash token, pacman-style short verbs still matched; systemctl verb found past value-taking options (`-n 5 status` — review false positive). | `test_d09_*` |
| **D-10 bounded** | Brace forms expanded per alternative (`_brace_alternatives`; sequences/nesting → unknown → checked by literal prefix); `//opt/x`, `~root`, `-o/opt/x` spellings; working directory tracked from the payload `cwd` through absolute, home, relative and `-` targets (`_cd_rule`), `cd -` into the unknown → UNPARSEABLE; relative recursive-delete targets resolved against the tracked cwd (`cd /opt; rm -rf crooks-os`); `{}` unknown outside a `find -exec` scope; worktrees under `.worktrees/` are checkout roots of their own. Symlink-through-parent is recorded as a limit in the guard docstring, not solved. | `test_d10_*`: 19 deny vectors + 11 allowed forms |
| **D-11 M** | `main()` in both hooks wraps everything in `try/except BaseException` → one fixed line (`… DENY [INTERNAL-ERROR] …`), exit 2, nothing on stdout. | `test_d11_*` (monkeypatched `decide`/`run_gate` raising; the sentinel never appears) |
| **D-12 bounded** | `printf` and embedded/sliced credential-variable references (`"token=$X"`, `${X:0:8}`, `${X#…}`); `<<<` operands; `/proc/<pid>/environ`; `declare/typeset/export -x/-p`; inline interpreter code that reads the environment or a credential file (`os.environ`, `getenv`, `process.env`, `$ENV`, `.env`, `.credentials`, `/proc/`, …) → `INTERPRETER-SECRET-READ`, for `-c` and code heredocs; dot-prefixed globs (`.en?`, `.env*`); `< .env` input redirects. | `test_d12_*`: 22 deny vectors + 11 allowed |
| **D-13 (scope decision)** | The general conservative rule was implemented because it is two constants, not a policy surface: `/etc` and `/root` appended to `PROTECTED_DIRS` (specific roots stay first so reasons keep naming them). Writes, deletes, `cd`-then-mutate under either are denied; reads stay. Plus one line each: `systemd-run`/`at`/`batch` → SERVICE-MUTATION; `ufw`/`iptables`/`ip6tables`/`nft`/`firewall-cmd` mutating verbs → NETWORK-MUTATION; any `0.0.0.0`/`[::]` bind → PUBLIC-BIND; `git push --all` → GIT-PUSH-PROTECTED-REF. **Deferred, documented:** `kill`/`pkill` of the production process (legitimately used to stop test processes), `docker`, `socat`, `python -m pip install --user`, and a finite command-word allow-list. | `test_d13_*`: 16 deny vectors + 11 allowed (`cat /root/.bashrc`, `cp /etc/hosts /tmp/`, loopback binds, `ufw status`, `iptables -L`) |
| **D-15 M→H** (`gitleaks_gate.py`) | `_publish_actions` walks a queue of command texts: `-c` strings, `<<<` operands, `eval`/`watch`/`su -c`/`env -S` strings and literal `echo … \| sh` text via the guard's shared `_shell_texts`/`_dynamic_word`; a laundered form the guard refuses raises → `UNPARSEABLE` deny in the gate too. | `test_d15_*`: `bash -c 'git push'`, `eval`, `<<<`, `printf \| sh`, heredoc `\| bash`, `env -S`, `timeout … bash -c` all found; six laundered forms denied |
| **D-16 L** | `_GitCall.chdir` is the last `-C` **before** the subcommand only; `git commit -C HEAD` scans the real repo (verified in a temp repo with the pinned binary). | `test_d16_*` |
| **D-17 M** | `TOTAL_SCAN_BUDGET_S = 100`, one `deadline` per `run_gate` call shared by every scan; each scan's `timeout` is what remains; an exhausted budget denies without starting a scan. Registered timeout stays 120 s; the pending `settings.json` text is **unchanged** and the test asserts the budget sits below it. | `test_d17_*` (fake clock: two scans get 90 s then 40 s of a 100 s budget) |
| **D-18 M** (`roster_assert.py`) | Documented key set; `agents`/`skills`/`plugins` are surfaces that must be empty unless explicitly allowed; **any undocumented list- or object-valued key is a violation**; undocumented scalars are reported as `unknown_keys`; digest covers `slash_commands` and every surface; `ToolSearch` and `Skill` added to the disallowed built-ins. | `test_d18_*` (5 tests); existing `test_roster_assert.py` unchanged and passing |
| **D-19** | No code claim. Isolation doc §3 now states in its own paragraph that layer-1 isolation is **not proven**: deferred tools behind `ToolSearch`, and whether `--disallowed-tools` removes or only denies, are empirical questions for an owner-approved live capture. No account, global Claude, connector, MCP, identity, credential or launch-flag change was made. | doc only |
| **D-20 L** | Isolation doc §4 and the module docstring: "a kill switch, not the gate"; the launch configuration is the gate; the token-zero guarantee is withdrawn. | doc only |
| Item 18 | Root `CLAUDE.md`: "~2800 tests" removed (no number). | `test_root_claude_md_is_short_…` still passes (49 lines < 60) |
| Item 19 / **D-14** | `DEV_ENVIRONMENT.md` §11 records the incident (eight watcher refusals, unprocessed inbox), the owner-side `.git/info/exclude` entry as a **temporary operational workaround, not architecture**, that the tracked `.gitignore` line is the durable form, that the entry must not be touched by a worker, and why worker workspaces stay under the builder until the watcher unit (`ReadWritePaths=/opt/crooks-builder` under `ProtectSystem=strict`) is separately hardened. Worktree not moved; exclude entry not touched; unit not touched. | doc only |

**One documented behaviour change the reviewer should weigh.** D-03 refuses `eval` of a
substitution, which includes the repository's documented idiom
`eval "$(python3 scripts/dev_env.py env)"`. Rather than special-case one command in a security
repair, `CLAUDE.md` and `DEV_ENVIRONMENT.md` now show
`python3 scripts/dev_env.py env > /tmp/crooks-env.sh && . /tmp/crooks-env.sh` (the guard can name
the file; sourcing a file is the same documented "script file" limit as `bash script.sh`).
`scripts/dev_env.py` itself still *prints* the `eval` hint (lines 9, 202, 626) — it is output, not
a command the guard sees, and changing product-script text was outside this round's scope; noted in
the doc.

**Size.** The guard grew from 1,340 to 2,024 lines (≈60 of them the new "Known limits" docstring).
The inbox said to shrink only "without reducing the proved safety contract" and not to refactor for
line count during a security repair; each repair added parsing (shell texts, brace expansion, cwd
tracking, curl bundles) rather than removing any. The reviewer's §5F suggestion — split the
`gh`/package/disk/keyring/network families into an advisory table and make the command-word rule a
finite allow-list — is a design decision for a separate round; unknown *static* command words are
still allowed, and the docstring says so.

## 5. Evidence — all measured on the exact tree of `d7911b2…` (working tree identical; 0 status lines)

From the worktree's `crooks-assistant/`, base builder's `.venv` and pinned tooling by absolute
path (the worktree has neither; `import app` resolves to the worktree copy).

| Check | Result |
|---|---|
| **Failing-before** (new test file vs rejected source `dd50ebb…`) | `pytest tests/test_harness_review_repairs.py` → **162 failed, 18 passed** (180). The later-added glob test's six vectors were run against the rejected guard afterwards: all six ALLOW. |
| **Passing-after** (same file, repaired source) | **181 passed, 0 failed, 0 skipped** |
| Targeted: `pytest tests/test_harness_review_repairs.py tests/test_guard_bash.py tests/test_gitleaks_gate.py tests/test_roster_assert.py tests/test_project_claude_layout.py tests/test_dev_env.py -q -p no:cacheprovider -rs` | **568 passed, 2 skipped**, 22.8 s. The 2 skips are the same two layout tests as before (`.claude/settings.json` absent; vendored skill absent) and print their reasons — **skips, not passes**. Every pre-existing test (387) passes unchanged: all ECC ported vectors, all CROOKS vectors, the stdin-only/stdlib-only source checks. |
| Full offline suite: `pytest -m "not live" -q -p no:cacheprovider -n 4` | **3374 passed, 10 skipped, exit 0**, 244.1 s (= previous 3193 + 181 new). Same two "Event loop is closed" xdist-teardown tracebacks the reviewer recorded; not failures. |
| `ruff check app config scripts tests` (= `make lint`, ruff 0.16.8) | All checks passed |
| `gitleaks git --redact --log-opts=dd50ebb…..d7911b2…` (pinned 8.30.1, stdout/stderr discarded, JSON report read for the count only, deleted) | **0 findings** ("no leaks found") |
| `gitleaks dir` on each of the 8 changed files individually (copied alone into a temp dir, redacted) | **0 findings in every file**. (A first `dir` scan given several paths walked the whole tree and reported 7 findings, all in pre-existing test fixtures and `__pycache__` on the base branch — `tests/test_scribe.py`, `test_tts.py`, `test_observability*.py`, the synthetic `ghp_` token of `test_gitleaks_gate.py` — none in a changed file. Rule/file/line only were read.) |
| Fuzz: 6,000 random/mutated command strings × `evaluate`, `decide`, `run_gate` (18,000 calls) | **0 exceptions** |
| False-positive probe: 83 ordinary engineering commands from this round's own transcript (fetch/show/diff/pytest/ruff/systemctl cat/ss/stat/journalctl/worktree add/commit/push/heredocs/find -exec/xargs/gh view/curl download/…) | **2 denied**: `eval "$(python3 scripts/dev_env.py env)"` (D-03, by design, documented above) and `env \| grep -i crooks_` (bare `env`, pre-existing rule). Everything else allowed. |
| Hooks under the system `/usr/bin/python3` 3.12.3 (what the pending `settings.json` invokes), as subprocesses on real JSON | guard: `git status` exit 0 silent; `git reset --hard` exit 2 `[GIT-RESET-HARD]`; `eval "$(…)"` exit 2 `[UNPARSEABLE]`; `printf %s "$SHOPIFY_TOKEN"` exit 2 `[SECRET-ECHO]`. gate: `git status` exit 0; garbage → exit 2 `[MALFORMED-INPUT]`. |
| Identity | one commit, parent `dd50ebb…`, 8 files, `+1869/−242`; local = remote = `d7911b2…` |

Not done: no ECC fetch (digests not re-verified — unchanged from the candidate); no Claude session
launched; no browser; no `.claude/` file; nothing executed from the candidate except its hooks/tests
in-process and as subprocesses on synthetic JSON and throwaway `tmp_path` repos.

## 6. Production, services, account, connectors — unchanged

**Production branch HEAD: `1cf3a0f3361b79f9de208d80f501543c53c244b5` — unchanged, clean (0
status lines), never entered except `git rev-parse`/`status`.** `crooks-assistant.service`,
`crooks-bridge-watcher.service`, `tailscaled.service`: active (read-only `is-active`). Listener
`127.0.0.1:8000` only (`ss -ltn`); nothing on `0.0.0.0:8000`. `/health` not called.
`/root/.claude/settings.json` mtime 2026-09-18 16:29 (unchanged); `/root/.claude` writable and used
only for this session's own memory notes under `/root/.claude/projects/-opt-crooks-builder/memory/`
(two project-fact files + index: worktree tooling paths and bridge-round facts; no secrets).
`/opt/crooks-builder/.git/info/exclude` unchanged. Watcher unit unchanged (`systemctl cat` read
only). No `claude config/mcp/plugin`, no unit, Tailscale, secret, permission, connector or
business-tool call. Network use: `git ls-remote` (×3), explicit `git fetch` of three branches,
one `git push --dry-run` (authentication probe; "Everything up-to-date"), one real `git push` of
`claude/harness-hooks-experiment` only. Scratch under the watcher's `PrivateTmp` (`/tmp/repairs-before.txt`,
`/tmp/repair-suite.log`, gitleaks reports since deleted) vanishes on restart; nothing is relied on.

## 7. Safety constraints — all preserved

`writes_enabled` false; `CROOKS_WRITES_LOCAL_OWNER` false; FastAPI on 127.0.0.1; port 8000 not
public; proposal/action/verification semantics untouched (no `app/` code changed); no live Shopify,
Gmail or ElevenLabs call; no external mutation other than the one branch push; V2 not begun; UI
untouched; Mac deployment/rollback untouched; `/root/.claude` writable; no secret value read,
printed or committed (credential file **names** appear in D-01 tests because refusing them is the
point; their contents were never opened; the gitleaks synthetic token is the existing test
fixture, not a credential); nothing installed, started, merged, reset, cleaned, stashed, amended or
deleted; no `.claude/` file created; worktree not moved; exclude entry and watcher unit untouched;
no permission widened; nothing outside `bridge/claude-outbox.md` touched in the bridge.

## 8. Errors, corrections made during the round, and limits

- **Introduced and caught before commit:** merging the guard's two redirect loops let a bare
  `>>` match the attached-form regex with a target of `>`, so `echo x >> ~/.ssh/authorized_keys`
  was ALLOW for one iteration; the D-13 tests caught it, the alternation was reordered and the
  attached form now requires a non-operator first character; a regression test pins both bare
  and attached `>>`, `2>>`, `&>>`.
- **Test expectation corrected:** the review's "deny `cd -` when ambiguous" was first written as
  `cd /tmp; cd -; cd -; cd -` which is *not* ambiguous when the payload cwd is known; replaced by
  `cd $X; cd /tmp; cd -; cd -` (returning into an unknown directory), which is.
- **Tooling:** `gitleaks dir` with several paths walked the tree (see §5); per-file scans are the
  evidence. `git fetch --all` fails on the builder's stale refspec (§2); not changed.
- **Behaviour changes a reviewer may judge too strict:** `/root` and `/etc` are now
  write-protected as a whole (D-13): `rm -rf ~/.cache/x`, `mkdir -p /root/.config/x`, `cd /root &&
  git clone …` are denied; a session whose payload `cwd` is under `/root` would have every
  non-read-only command denied (the watcher launches in `/opt/crooks-builder`, so this does not
  arise here). `$VAR/bin/python` as a command word is denied (write the path). `eval "$(…)"` is
  denied (§4). `cat <<EOF | tee x | bash` is denied even with a benign body (the shell is fed by
  `tee`, not by the heredoc directly).
- **Not solved, recorded in the guard's "Known limits" docstring:** symlink/bind-mount aliasing;
  script files (`bash x.sh`, `source x.sh`, `python x.py`, `make` targets) beyond a
  protected-path check; unknown *static* command words allowed; variables inside paths beyond
  same-line assignments (`> $OUT`); `PATH=` hijack; interpreter code beyond the substrings it
  names (`os.system(...)` inside `python3 -c` is not seen).
- **D-19 remains empirical**; **D-14's durable fix** (external workspaces + watcher unit change +
  precondition-failure classification) is deferred to a separately reviewed round, as the inbox
  directed. **The two layout skips remain skips** until the owner applies `.claude/`.
- Reviewer independence: implementer and reviewer are the same model family on the same account;
  the pilot's reviewer-identity field should record this again for the fresh review.

## 9. Decisions or questions needing review

1. **Accept `d7911b2…` as the new review candidate and commission a fresh independent adversarial
   review of it** (pilot §5: corrections create a new candidate; the previous review bound only
   `dd50ebb…`). Suggested focus for the reviewer, beyond re-attacking every D-id: the new
   `_segments` substitution marker, `_shell_texts`/`_fed_text`, `_brace_alternatives`, `_cd_rule`
   resolution of relative deletes, the D-13 `/etc`+`/root` widening for dangerous false
   positives, and whether the gate's UNPARSEABLE-on-laundering is the right contract for a gate
   that "does nothing for any other command".
2. D-13 breadth: the general rule landed as two constants; confirm that is the intended scope
   decision, or ask for the narrower CROOKS-only form back.
3. The `eval "$(…)"` idiom change in `CLAUDE.md`/`DEV_ENVIRONMENT.md` (and whether
   `scripts/dev_env.py`'s printed hint should follow in a later, non-security round).
4. Guard size (2,024 lines): whether the §5F split into core + advisory tables and a finite
   command-word allow-list becomes its own design round. Not attempted here, per the inbox.
5. D-14: nothing for this round; the owner still holds the local exclude entry and the later
   watcher/systemd hardening decision.

## 10. Exact proposed next step

An independent, read-only, adversarial review round of `claude/harness-hooks-experiment` at exact
head `d7911b24979be2306749b7333ec60edc28cba857`, exact parent `dd50ebbca6eca9c4e2ee1e85ad17d2c7e5afd25e`,
accepted base `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`: verify the two-commit identity, re-run
`tests/test_harness_review_repairs.py` (181), the targeted set (568 + 2 skips), the offline suite
(3374 + 10 skips), Ruff and the range scan; re-attack the repaired rules with vectors not in this
file; return exactly one verdict. No `.claude/` apply, no merge, no unit/exclude/identity change
until that verdict. Separately and only by the owner: the D-19 live init-line capture and the
D-14 watcher hardening remain open.

## 11. Stop

Repair candidate published and read back. Nothing merged, deployed, installed, started or
approved by this round.

Inbox SHA processed: `4843e76fb5523a4486c1d275f67842d3ab567ef3`
