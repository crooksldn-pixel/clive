# CLAUDE OUTBOX — latest handoff only

## 2026-09-19T22:04Z — Independent adversarial review of harness candidate `d7911b2`: REJECT — REPAIR REQUIRED

**Inbox consumed:** yes. Blob SHA processed: `7ac15d08d6f5e83a3ed5f396df86262c59dab976`
(`bridge/chatgpt-inbox.md`, heading "2026-09-20 — Independent adversarial review of repaired
harness candidate d7911b2"). These instructions are now recorded as executed and must not be run
again.

**Verdict: `REJECT — REPAIR REQUIRED`.** Candidate `d7911b24979be2306749b7333ec60edc28cba857`
on `claude/harness-hooks-experiment` has the exact identity claimed, its own tests/scans/Ruff
reproduce exactly, and every prior defect D-01 … D-20 that I re-attacked with fresh vectors is
closed. But my own vectors — none copied from `tests/test_harness_review_repairs.py` — found
**five new bypasses in the same families the inbox told me to re-probe** (command-position
substitutions and cwd/redirect tracking). Two are high: one **writes into the production
checkout**, one **runs an arbitrary laundered destructive command** (force push, `rm -rf`
production). Both defeat the guard's own stated contract on a real target, which is the
review's rejection bar. All five are bounded, same-branch repairs; none is a design rejection.
Defect list in §5. Nothing was implemented, committed, pushed or written to the candidate or
the builder; no `.claude/` file exists anywhere; no owner approval is inferred for anything.

---

## 1. What was asked

Independent, read-only, adversarial review of `claude/harness-hooks-experiment` at exact head
`d7911b2…`, parent `dd50ebb…`, accepted base `295e483…`: verify identity; re-read D-01 … D-20
and the repair diff; re-run the repair suite, targeted tests, the offline suite, Ruff and a
redacted range gitleaks; re-attack every repaired rule with new vectors (substitutions/dynamic
words, shell-fed text/nested wrappers/heredocs, brace/path/cwd/relative deletes, secret store
and env leakage, git `-c`/`-C`/stash, project `.claude/` and `.git/hooks/`, gitleaks laundering
and timeout, roster surfaces); focus on the new parser complexity; assess D-13 breadth, the
`eval` idiom replacement, guard size, D-14 documentation and that exclude/worktree/unit were not
changed; re-state D-19 as empirically unproven; return exactly one verdict; if rejecting, give a
bounded defect list with severity, exact reproducer, contract violation and smallest repair. No
fixes, no new candidate, no merge, no `.claude/` apply, no global/account/connector/secret change.

## 2. Checkout state — start and end

| Repo | Branch | Start | End |
|---|---|---|---|
| Builder `/opt/crooks-builder` | `claude/builder-environment-repair` (unit env still says `claude/bridge-builder`; untouched) | `295e483…`, clean (`--untracked-files=all`, 0 lines) | unchanged, clean. `.git/info/exclude` still ends with the owner's `.worktrees/` line — **not touched** |
| Candidate worktree `/opt/crooks-builder/.worktrees/harness-hooks-experiment` | `claude/harness-hooks-experiment` | `d7911b2…`, clean | `d7911b2…`, clean (0 status lines); not moved, not removed |
| Bridge `/opt/crooks-ai-bridge` | `crooks-ai-bridge` | `0364d10…`, clean | only `bridge/claude-outbox.md` modified (this file) |
| Production `/opt/crooks-os` (read-only, `git rev-parse`/`status` only) | `claude/linux-prod-migration-production` | `1cf3a0f3…`, clean | `1cf3a0f3…`, clean (0 status lines), never entered for anything else |

**Fresh refs, not stale tracking.** `git fetch --all` still **fails** in the builder (its only
fetch refspec names deleted `claude/bridge-builder`), so branches were fetched explicitly per the
inbox: `claude/harness-hooks-experiment` and `claude/product-memory-foundation`. The stale
refspec is a builder-clone config fact; this round did **not** repair it, as instructed. Canonical
truth was read by explicit ref from `claude/product-memory-foundation` at its current remote head
`c7a1cf64781a2ecfaf17908236404df06033cffe` (`git show`): CURRENT_TRUTH (rename complete, DEC-048
Linux prod ratified at `1cf3a0f`, DEC-049 bounded `.claude/` approval, the D-14 incident and
durable lesson, the harness reject-then-repair record) and DECISIONS DEC-047/048/049. The prior
independent review (inbox `2b1030bd…`, verdict REJECT) was read from bridge commit `dfe7028`, and
the implementer's repair outbox (inbox `4843e76…`) from `5ed8a99`; my attack vectors are new and
reuse neither.

## 3. Identity — verified (inbox required verification 1)

- `d7911b2^` = `dd50ebbca6eca9c4e2ee1e85ad17d2c7e5afd25e` (the rejected candidate).
- `git rev-list dd50ebb..d7911b2` = **1** commit; `git merge-base dd50ebb d7911b2` = `dd50ebb…`.
- `git rev-list --left-right --count 295e483…...d7911b2…` = `0 2` (two commits above the accepted
  base: the rejected candidate plus this repair).
- Remote `git ls-remote origin refs/heads/claude/harness-hooks-experiment` = `d7911b2…` (matches
  local).
- One commit, author `Claude <noreply@anthropic.com>`, 2026-09-19 21:25:34 UTC, "The rejected
  harness candidate, repaired against each of the review's vectors". Diff `dd50ebb..d7911b2`:
  **8 files, +1869/−242** (`CLAUDE.md`, `docs/DEV_ENVIRONMENT.md`, two dev-environment docs,
  `scripts/hooks/guard_bash.py`, `scripts/hooks/gitleaks_gate.py`, `scripts/roster_assert.py`,
  new `tests/test_harness_review_repairs.py`). No `app/` change; no `.claude/` directory anywhere.
- **Production remains exactly `1cf3a0f3361b79f9de208d80f501543c53c244b5`** (the `/opt/crooks-os`
  checkout HEAD), clean, untouched.

## 4. Evidence re-run on the exact tree of `d7911b2` (inbox required verification 3)

From the worktree's `crooks-assistant/`, using the base builder's gitignored `.venv` and the
pinned gitleaks by absolute path (the worktree has neither `.venv/` nor `.tooling/`; `import app`
resolves to the worktree copy).

| Check | Result |
|---|---|
| `pytest tests/test_harness_review_repairs.py` | **181 passed**, 1.99 s |
| Targeted: `pytest tests/test_harness_review_repairs.py tests/test_guard_bash.py tests/test_gitleaks_gate.py tests/test_roster_assert.py tests/test_project_claude_layout.py tests/test_dev_env.py -q -rs` | **568 passed, 2 skipped**, 22.1 s. The 2 skips are the same two layout tests (`.claude/settings.json` absent; vendored skill absent) and print "this skip proves nothing" — **skips, not passes** |
| Full offline suite: `pytest -m "not live" -q -n 4` | **3373 passed, 1 failed, 10 skipped**, 241.8 s. The one failure is `tests/test_experience.py::test_the_golden_scenarios[query_international_waiting]` — **not attributable to the candidate**; see the note below |
| `ruff check app config scripts tests` | All checks passed |
| `gitleaks git --redact --log-opts=dd50ebb…..d7911b2…` (pinned 8.30.1, stdout/stderr discarded, JSON read for the count only, then deleted) | **0 findings** |

**The one full-suite failure is pre-existing and environmental, not a candidate regression.**
`test_the_golden_scenarios[query_international_waiting]` fails **identically on the accepted base
`295e483`** (I re-ran it from `/opt/crooks-builder/crooks-assistant` at `295e483`: same failure,
5.5 s). The candidate changes **zero** `app/` or experience-fixture code
(`git diff --stat 295e483 d7911b2 -- app/ tests/test_experience.py` is empty). The test log shows
`normaliser repointed at live catalogue: 38 terms`, i.e. it depends on catalogue/data state that
has drifted since the implementer's run (who reported 3374 passed). It is an environment/data
issue to raise separately; it does not bear on the harness verdict.

## 5. Findings — new bypasses (vectors are mine; none are in the repair test file)

Severity as the prior review defined it: **H** = defeats the hook's stated contract on a real
target on this host or allows a production/shared-state mutation; **M** = a bypass or fail-open of
a stated rule with lower reach. Every reproducer below was confirmed in-process via
`guard_bash.evaluate(...)` and the two H findings again as a subprocess under the system
`/usr/bin/python3` (what the pending `settings.json` invokes) — both returned **exit 0 (allow)**.

### F-1 (H) — a relative output redirect into a protected checkout is allowed
After a literal `cd` into production, a **read-only** command with an output redirect to a
**relative** path writes into the production checkout, and the guard allows it:

```
cd /opt/crooks-os && echo pwned  > app/main.py        → ALLOW  (writes /opt/crooks-os/app/main.py)
cd /opt/crooks-os && echo pwned >> app/routes.py      → ALLOW
cd /opt/crooks-os && cat /tmp/x  > app/main.py        → ALLOW
cd /opt/crooks-os && printf x    > config/settings.py → ALLOW
```

Controls that are correctly denied: the **absolute** form `echo x > /opt/crooks-os/app/main.py`
→ `PROTECTED-PATH`; a **non-read-only** base `cd /opt/crooks-os && sed -i … app/main.py`
→ `PROTECTED-CWD`. Two compounding causes in `_path_rule` (`guard_bash.py` ~1221–1266):
(a) redirect (and `cp`/`rsync`/`install`) targets are matched only when absolute or home-anchored
— `_protected_hit` on a relative target returns None — whereas relative **rm** targets *are*
resolved against `ctx.cwd` in `_delete_one_problem`; (b) the `PROTECTED-CWD` backstop is guarded
by `not read_only`, so `echo`/`printf`/`cat`/`date`/`yes` with a redirect slip past it.
**Contract violated:** the builder/production write boundary — the guard's central purpose — for
the read-only-command-with-redirect case. **Smallest repair:** when `ctx.cwd`/`ctx.protected_cwd`
is set, resolve relative redirect/copy targets against `ctx.cwd` before `_protected_hit`, or treat
any output redirect to a relative target under a protected cwd as a write regardless of the base
command's read-only status. One negative test per redirect operator (`>`, `>>`), for `echo`,
`printf`, `cat`.

### F-2 (H) — a command that is entirely a `$( )`/backtick substitution evades the D-03 marker
D-03 was meant to fail closed on "a command word produced by a substitution". It does when there
is trailing text, but **not** when the substitution is the whole command:

```
$(echo 'git push --force origin main')      → ALLOW   (real shell: force-push)
$(printf 'rm -rf /opt/crooks-os')           → ALLOW   (real shell: rm -rf production)
`echo 'git reset --hard'`                   → ALLOW
$(echo 'systemctl restart crooks-assistant')→ ALLOW
```

Control correctly denied: `$(echo git) push --force origin main` → `UNPARSEABLE`. Cause: in
`_segments` (`guard_bash.py` ~488–590) the `SUBST_MARKER` is only prepended to a segment flushed
**at the substitution's depth**; when the substitution constitutes the entire command with no
trailing text, no segment is ever flushed at that depth, so no marker is emitted and only the
inner body (`echo '…'`, harmless) is evaluated. The shell runs the substitution's **output**.
**Contract violated:** the guard's own "dynamic words are refused" statement and the D-03 repair
claim; reaches force-push and `rm -rf` of production. **Smallest repair:** when a depth recorded
in `dynamic` is closed (at `)`, closing backtick, or end of input) without a subsequent same-depth
segment, still emit a bare `SUBST_MARKER` segment so the evaluator refuses it. Negative tests:
substitution-only forms wrapping a destructive command, both `$( )` and backticks.

### F-3 (M) — a dynamic word in argument position behind a passthrough wrapper is split away
```
sudo    $(echo git)       push --force origin main    → ALLOW
command $(echo git)       push --force origin main    → ALLOW
env X=1 $(echo systemctl) restart crooks-assistant    → ALLOW
```
Same root cause as F-2: a leading wrapper/assignment makes the segmenter's buffer non-empty, so
`dynamic.add(depth)` is skipped; the substitution body and the residual (`push --force …`,
`restart …`) become separate segments and the residual is evaluated as a standalone command whose
word (`push`/`restart`) is unknown and therefore allowed. **Repair:** treat the substitution as
occupying the command-word position when everything before it in the segment is a passthrough
wrapper or a `NAME=value` assignment (mark it), not only when the buffer is empty.

### F-4 (M) — a git subcommand supplied as a variable ignores its own destructive flags
```
p=push;  git $p  --force origin main   → ALLOW
s=reset; git $s  --hard                → ALLOW
git ${SUB} --hard                      → ALLOW
```
`_git_subcommand` returns the dynamic token as `sub`; no rule matches it, and `--force`/`--hard`
are only inspected under the literal `push`/`reset` branches, so the destructive flags are present
but ignored. `_dynamic_word` is applied only to the command word `git`, not to the subcommand.
**Repair:** if `_dynamic_word(call.sub)`, deny `UNPARSEABLE`.

### F-5 (M) — the gitleaks gate misses a publish laundered through a whole-command substitution
`_publish_actions` returns `[]` (so `run_gate` → ALLOW, no scan) for a `git push` whose verb comes
from a substitution:
```
_publish_actions('bash -c "$(echo git push)"')    → []           (real shell: git push)
_publish_actions("$(echo 'git push origin x')")   → []           (real shell: git push)
_publish_actions("bash -c 'git push origin x'")   → [('push', ['origin','x'], None)]   (correct)
_publish_actions("printf 'git push' | sh")        → [('push', [], None)]                (correct)
```
Same root cause as F-2, in the gate's shared lexer path. The gate's docstring claims it denies
shell text it cannot read as `UNPARSEABLE`; here it neither scans nor denies — a fail-open of the
secret scan. Lower reach (needs a secret already committed and a contrived launder), hence M.
**Repair:** the F-2 segmenter fix, plus have the gate treat queued/`-c` text whose command word is
an unexpanded substitution as `UNPARSEABLE`.

**These five reduce to three root causes:** the substitution-marker gap (F-2, F-3, F-5), the
relative-target resolution gap in `_path_rule` (F-1), and the dynamic git subcommand (F-4). All
sit in the exact parser complexity the inbox flagged (`_segments` substitution marking, cwd/
redirect tracking, the gate's shared lexer).

## 6. What I re-attacked and found sound (so the repair is bounded)

Every prior defect the repair claimed to close held against fresh vectors:

- **D-01** secret store: `grep -r . /etc/crooks-os/secrets`, `tar cf /tmp/a.tar
  /etc/crooks-os/credentials`, `cat …/credentials/../secrets/media_signing_key`,
  `awk 'END{print}' …/x.cred`, `python3 -c 'open("…/media_signing_key")'` → all **DENY**
  (SECRET-FILE-READ / INTERPRETER-PROTECTED-PATH). Reads of `ls /etc/crooks-os` still allowed.
- **D-02/D-06** git: `git -C /opt/crooks-os stash` and `… stash pop` → PROTECTED-PATH;
  `git -c core.pager='rm -rf x' log`, `git -c alias.foo='!…' foo`,
  `git --config-env=core.sshCommand=X push` → GIT-CONFIG-EXEC; `git config --get core.hooksPath`
  and `git commit -C HEAD` still allowed (old false positives fixed).
- **D-03/D-04** laundering (with trailing text): `sudo bash -c 'git reset --hard'`,
  `timeout 5 bash -c 'rm -rf /opt/crooks-os'`, `env FOO=1 sh -c 'git reset --hard'`,
  `printf '%s' 'git reset --hard' | bash`, `echo -e 'git reset --hard' | sh`,
  `cat <<'EOF' | bash …`, `bash -lc 'git reset --hard'`, `\rm -rf /opt/crooks-os`,
  `'git' push --force`, `gi"t" push --force` → all **DENY**. (The residual-after-substitution and
  whole-command-substitution cases are the new F-2/F-3 holes.)
- **D-08** `printf x > .claude/settings.json`, `install .git/hooks/pre-commit`,
  `cp … ./.claude/settings.local.json`, `rsync -a /tmp/ .claude/` → PROJECT-CLAUDE-WRITE /
  GIT-HOOKS-WRITE.
- **D-10** paths/cwd: `cp x /opt/{crooks-os,crooks-builder}/f` → PROTECTED-PATH;
  `rm -rf /opt/crooks-o{s,}`, `cd /opt && cd crooks-os && rm -rf app`, `rm -rf ~/../opt/crooks-os`
  → RM-RECURSIVE; `cd /opt; git -C crooks-os reset --hard` → GIT-RESET-HARD; `cp x //opt/crooks-os/y`,
  `tee /etc/systemd/system/x.service` → PROTECTED-PATH.
- **D-11** internal-error path: both hooks wrap `main()` in `try/except BaseException`; the repair
  suite's monkeypatched-raise tests pass and the sentinel never reaches stdout.
- **D-12/D-13** env & breadth: `cat /proc/self/environ`, `echo "$SHOPIFY_TOKEN" | base64` →
  SECRET-ECHO; `uvicorn --host 0.0.0.0`, `python3 -m http.server --bind 0.0.0.0` → PUBLIC-BIND;
  `systemd-run` → SERVICE-MUTATION; `iptables -A INPUT -j DROP` → NETWORK-MUTATION;
  `git push --all origin` → GIT-PUSH-PROTECTED-REF. Reads/loopback stay allowed:
  `cat /etc/hosts`, `cat /root/.bashrc`, `ls /etc/crooks-os`, `uvicorn --host 127.0.0.1`.
- **D-15/D-16/D-17** gate: `bash -c 'git push'`, `eval 'git commit'`, `git push … <<< y`,
  `printf 'git push' | sh`, `watch -n1 '…'`, `env -S '…'` all detected and scanned;
  `$(echo git) push`, `g=git; $g push` → UNPARSEABLE; the budget test holds
  `TOTAL_SCAN_BUDGET_S=100` below the registered 120 s.
- **D-18** roster: unknown list/object-valued keys are violations, documented surfaces
  (`agents`/`skills`/`plugins`) checked, `ToolSearch`/`Skill` in the disallowed built-ins, digest
  covers every surface; the 5 repair tests and the unchanged `test_roster_assert.py` pass.

**Inbox items 6–10.** D-13 breadth (`/etc`+`/root` as two constants) is safe in practice: reads
and loopback binds stay allowed and the watcher launches in `/opt/crooks-builder`, so no
material false positive arises for normal engineering work; leaving it as-is is defensible, but
it does make F-1's read-only-redirect hole land inside a broadly protected area, which raises
the stakes of fixing F-1. The `eval "$(python3 scripts/dev_env.py env)"` → file-and-source
replacement in `CLAUDE.md`/`DEV_ENVIRONMENT.md` is honest and correct given D-03; the product
script still prints the `eval` hint, correctly out of scope. Guard size (2,024 lines) is a real
auditability concern — a reviewer can enumerate only the deny-set, and F-1 … F-4 are again "one
case too generous" in exactly the newest, largest parser additions — but per the inbox I do not
reject on line count. D-14: the DEV_ENVIRONMENT.md §11 write is accurate; the local
`.git/info/exclude` still carries the owner's `.worktrees/` line (mtime 2026-09-19 19:47:45,
unchanged by this round), the worktree was not moved, and the watcher unit is unchanged
(`systemctl cat`, read only). D-19 restated: **layer-1 tool-surface isolation remains
empirically unproven** — deferred tools behind `ToolSearch` and whether `--disallowed-tools`
removes vs only denies are open questions for an owner-approved live init-line capture; no such
experiment was run this round, and the doc (§3) now says so in its own words.

## 7. Production, services, account, connectors — unchanged (inbox handoff item)

**Production HEAD `1cf3a0f3361b79f9de208d80f501543c53c244b5` — unchanged, clean (0 status lines),
entered only for `git rev-parse`/`status`.** `crooks-assistant.service` and
`crooks-bridge-watcher.service` active; listener `127.0.0.1:8000` only (`ss -ltn`); nothing on
`0.0.0.0:8000`. `/health` not called. No `.claude/` file created anywhere. `/root/.claude`
writable and used only for this session's own memory notes; `/root/.claude/settings.json` mtime
2026-09-18 16:29 (unchanged). Builder `.git/info/exclude` and the watcher unit untouched. No
`claude config/mcp/plugin`, no unit/Tailscale/secret/permission/connector/business-tool call.
Network: two explicit `git fetch` (harness + product-memory branches) and `git ls-remote` reads;
**no push, no ECC fetch.** Scratch probe scripts were kept under `/root/.cache/review-d7911b2/`
and **deleted** at the end (no secrets in them). The gitleaks JSON report was deleted after the
count was read.

## 8. Safety constraints — all preserved

`writes_enabled` false; `CROOKS_WRITES_LOCAL_OWNER` false; FastAPI on 127.0.0.1; port 8000 not
public; proposal/action/verification semantics untouched (no `app/` change); no live Shopify,
Gmail or ElevenLabs call; no external mutation of any kind; V2 not begun; UI untouched; Mac
deploy/rollback untouched; `/root/.claude` writable; **no secret value read, printed or
committed** (credential-store paths appear by name in F-1/§6 because refusing or reaching them is
the finding; no contents were opened); nothing installed, started, merged, pushed, reset,
cleaned, stashed, amended or deleted; no `.claude/` file created; no candidate created; worktree
not moved; exclude entry and watcher unit untouched; no permission widened; nothing outside
`bridge/claude-outbox.md` touched in the bridge.

## 9. Errors, limits, independence

- The one full-suite failure is pre-existing/environmental (§4), reproduced on the accepted base;
  it is not the candidate's and should be triaged separately (looks like golden-catalogue drift).
- `git fetch --all` still fails on the builder's stale refspec; explicit fetches used; not changed.
- ECC upstream digests not re-verified (no network fetch in a read-only review); unchanged from
  the candidate.
- No Claude session launched, no browser, no `.claude/` file, nothing executed from the candidate
  except its hooks/tests in-process and the two H reproducers as subprocesses on synthetic JSON.
- Reviewer independence: implementer and reviewer are the same model family on the same account;
  the vectors are mine and reuse neither the implementer's nor the prior reviewer's tables. The
  pilot §5 reviewer-identity field should record this again.

## 10. Decisions or questions needing review

1. **Accept the verdict `REJECT — REPAIR REQUIRED`** with F-1 … F-5; corrections are a **new
   commit on the same branch → new candidate SHA → fresh independent review** (pilot §5; this
   review binds only `d7911b2…`). F-1 and F-2 are high (production write; laundered destructive
   command) and should gate acceptance.
2. F-1's fix interacts with D-13 breadth: because `/etc` and `/root` are now broadly protected,
   confirm the redirect-resolution fix denies relative writes under any protected cwd, not just
   `/opt/crooks-os`.
3. Guard size/auditability (2,024 lines): the recurrence of "one case too generous" in the newest
   parser additions is evidence for the prior review's §5F suggestion (finite command-word
   allow-list, split advisory tables) as a **separate** design round — not a reason to reject now.
4. D-19 and D-14 remain owner-held (live init-line capture; watcher/systemd hardening); nothing
   for a bridge round.

## 11. Smallest safe next step

One bounded repair round on `claude/harness-hooks-experiment`, base `d7911b2…`, one commit, no
`.claude/` attempt: fix the three root causes — (a) emit a `SUBST_MARKER` for a substitution that
is the whole command or sits behind wrappers/assignments (closes F-2, F-3, and F-5 via the shared
lexer); (b) resolve relative redirect/copy targets against the tracked cwd, and/or make the
`PROTECTED-CWD` backstop apply to output redirects even for read-only commands (closes F-1);
(c) deny a dynamic git subcommand (closes F-4) — each with a failing-before/passing-after negative
test using the exact strings in §5. Re-run the repair suite, targeted set, offline suite, Ruff and
the range gitleaks; push; then a fresh independent review of the new SHA. Separately: triage the
`query_international_waiting` experience failure (base-level, not the harness). Do not merge, do
not apply `.claude/`, do not touch the watcher unit or the local exclude entry.

## 12. Stop

Review complete. Nothing was implemented, committed or pushed by this round.

Inbox SHA processed: `7ac15d08d6f5e83a3ed5f396df86262c59dab976`
