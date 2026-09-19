# Project-scoped `.claude/` files — exact content, pending one reviewed apply step

**Status:** SPECIFIED, NOT WRITTEN. The worker that produced candidate
`claude/harness-hooks-experiment` was refused every write under `.claude/` by its own
permission layer, in the isolated worktree DEC-049 approved. Per the inbox's permission rule
the refusal was not retried, not routed around, and nothing was written via any other path.
The hooks, tests, docs and `.gitignore` change that do not live under `.claude/` are in the
candidate; the files below are what completes it.

## 0. The refusal, verbatim

Three `Write` calls, one each for `.claude/rules/safety.md`, `.claude/rules/testing.md` and
`.claude/rules/builder-vs-production.md`, each returned:

```
Claude requested permissions to edit <worktree>/.claude/rules/<name>.md which is a sensitive file.
```

One Bash call that combined `mkdir -p <worktree>/.claude/skills/agent-architecture-audit
<worktree>/.claude/rules …` with a `python3 -` heredoc that would copy the skill returned:

```
This Bash command contains multiple operations. The following parts require approval: mkdir -p … , python3 - …
```

So the "sensitive file" protection is Claude Code's own, keyed on the `.claude/` path, and it
is independent of the inbox, of DEC-049 and of the worktree being isolated. An owner decision
recorded in product memory does not change it. What changes it is one of: a human creating the
files; a permission rule granting `Write(.claude/**)` for the builder (which itself lives in a
settings file the worker cannot write); or a different launch configuration. Which of those is
acceptable is the owner's call — the worker's job was to stop and say so.

## 1. Apply in one step

From the candidate worktree, as a human, create the files in §2–§5 with exactly the content
shown, then:

```sh
git add .claude CLAUDE.md
.venv/bin/python -m pytest tests/test_project_claude_layout.py tests/test_guard_bash.py -q
```

`tests/test_project_claude_layout.py` checks the files once they exist (hook commands are
project-relative, timeouts are sane, no `permissions`, no `env`, no other hook events) and
skips — saying so — while they do not.

## 2. `.claude/settings.json`

Two PreToolUse hooks on Bash and nothing else. `$CLAUDE_PROJECT_DIR` is the directory Claude
Code was started in (the builder root), so the commands are project-relative and survive a
worktree move. Timeouts are seconds. Neither hook can auto-approve anything: a denial is exit 2
and the only stdout either ever writes is `additionalContext`.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/crooks-assistant/scripts/hooks/guard_bash.py\"",
            "timeout": 15
          },
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/crooks-assistant/scripts/hooks/gitleaks_gate.py\"",
            "timeout": 120
          }
        ]
      }
    ]
  }
}
```

The 120 s registered for `gitleaks_gate.py` is not extended by this candidate (review D-17):
the gate now runs every scan a single call performs — two for `git commit -a` — against **one**
shared budget of 100 s (`TOTAL_SCAN_BUDGET_S`), so it always answers inside the registered
timeout instead of being killed by it, which Claude Code would treat as a non-blocking error.
`tests/test_harness_review_repairs.py` holds the budget below the number written here.

Deliberately absent (CLAUDE_PROJECT_LAYOUT §4 and the ECC audit §4.11): format-on-write,
Stop-time formatters/type-checkers, session persistence, observer/learning capture, desktop
notification, network-on-edit, MCP health, global-config protection, any `permissions` block,
any `env` block, any `node -e` bootstrap.

## 3. `.claude/rules/safety.md`

````markdown
# Safety invariants (editing rules)

These restate PRODUCT_BRAIN §9 and the decisions that fix them. They are changed only by an
explicit owner decision recorded in `DECISIONS.md` on `claude/product-memory-foundation`, never
as a side effect of other work.

- **Writes stay disabled** (`DEC-027`). `writes_enabled` is false; `CROOKS_WRITES_LOCAL_OWNER`
  is false. Do not flip either, do not add a code path that behaves as if they were true.
- **Loopback only** (`DEC-020`). FastAPI binds `127.0.0.1`. Port 8000 is never exposed publicly.
  No Funnel. No new listening socket.
- **Proposal → authorise → re-read → execute → verify** (`DEC-005`). Models propose; the server
  executes deterministic capabilities and verifies against the authoritative source. Do not
  short-circuit any stage, and do not let a model's claim stand in for verification.
- **A spoken "yes" authorises nothing** (`DEC-006`). Voice input never carries authority.
- **Unknown writes fail closed** (`DEC-007`). A write the server cannot classify is refused, not
  attempted. Preserve that in every new tool, route and adapter.
- **No arbitrary HTML/JS execution and no service-worker write replay.** The PWA renders data;
  it does not evaluate it.
- **No live business calls from engineering.** No live Shopify, Gmail or ElevenLabs request and
  no external mutation from tests, scripts or hooks. The fixture world is the test target.
- **No secret value, ever.** Never print, log, echo, commit or paste an API key, token, cookie,
  password, private key or OAuth grant. Name the secret if you must; never its value. A scan
  reports rule and path only. Never read `.env`, `.credentials.json` or a keychain entry just
  to "check" it.
- **Nothing auto-updates.** Pins move only through: upstream update → security scan → diff →
  test → review → manifest (`docs/DEV_ENVIRONMENT.md` §7).

## Review checklist for a diff touching proposals, actions, verification or secrets

1. Does any change let a tool run without the server's proposal record and authorisation?
2. Does any change treat model output, transcript text or a fixture as verified state?
3. Does any new write path have an explicit classification, or does it fall to "unknown"?
   Unknown must refuse.
4. Does any log line, error message, hook output or test fixture carry a secret value?
5. Does any change reach the network in a test, a hook or an edit-time check?
6. Is the change recorded against a `DEC-` id where it touches an invariant above?
````

## 4. `.claude/rules/testing.md`

````markdown
# Testing

`make test` (from `crooks-assistant/`) is the offline suite: `-m "not live"`, no network, no
real store. Ruff is the linter of record (`line-length = 100`, `py311`). Pyright and Biome are
advisory and check-only; never `--fix`, `--write` or `--apply` over existing source.

## What counts as evidence

- **A test that was only written is not RED.** It must have been run and failed *because of the
  defect it targets*, then run and passed after the fix. Record the command and the result.
- **Missing evidence is UNKNOWN, not PASS.** A skipped browser check has proved nothing; never
  record it as a pass. The browser gate needs `eval "$(python3 scripts/dev_env.py env)"` first,
  or it reports itself skipped.
- **Name tests after the defect.** `test_be02_doctor_fails_closed_when_tools_are_present_but_wrong`
  says what it proves; `test_doctor_2` does not. Prove both directions: a fail-closed check that
  always fails is not a check.
- **Test where bugs were found**, not for a coverage number. Do not rewrite passing tests to
  claim a tool or a percentage.
- **Implementers do not certify themselves** (`DEC-013`). Run the tests before asking for review,
  and bind every result to the exact candidate SHA it was measured on.
- **Fixture world vs live.** The offline suite runs against the golden fixture world. A result
  there says nothing about the live store; say so rather than implying it.

## How to run what

    make test                                   # whole offline suite, serial (the measured default)
    .venv/bin/python -m pytest tests/test_x.py  # one file, while iterating
    .venv/bin/python -m pytest -n 4 -m "not live"   # parallel; identical outcome measured on this host
    make lint                                   # ruff over the tree
    python3 scripts/dev_env.py doctor           # tooling identity, fails closed

Do not run the full suite after every edit. Run the targeted file while iterating, the whole
suite before publishing a candidate. Never add a retry plugin; a flaky test is fixed, not
rerun. Hypothesis belongs on parsers and state machines, not everywhere.
````

## 5. `.claude/rules/builder-vs-production.md`

````markdown
# Builder vs production

Per `DEC-011` / `DEC-012` and the bridge contract. This is the boundary; the Bash guard in
`scripts/hooks/guard_bash.py` enforces the parts of it that can be enforced from a command line.

| Path | What it is | What you may do |
|---|---|---|
| `/opt/crooks-builder` and its `.worktrees/` | builder checkouts, one branch per candidate | edit, test, commit on the candidate branch |
| `/opt/crooks-os` | the **production** checkout, ratified at an exact SHA | read only: `git -C /opt/crooks-os status`, `log`, `diff`, `cat` |
| `/etc/crooks-os`, `/etc/systemd` | production configuration and units | read only |
| `/root/.claude`, `/root/.claude.json` | the account-level Claude login and settings | read only; never write, never `claude config`/`mcp`/`plugin` |
| `/opt/crooks-ai-bridge` | the bridge worktree | write **only** `bridge/claude-outbox.md`; the watcher commits and pushes it |

## Never

- edit, switch, reset, fetch into, or clean `/opt/crooks-os`;
- merge to the production branch, or push to `main`, `master`,
  `claude/linux-prod-migration-production`, `claude/product-memory-foundation` or
  `crooks-ai-bridge`;
- force-push, delete a remote ref, or rewrite published history — a review binds an exact SHA,
  and rewriting it invalidates the review;
- install, enable, start, stop or restart a service (`systemctl`, `launchctl`, `make install`,
  `make up`, `make restart`);
- change a Tailscale route (`tailscale serve`, `tailscale funnel`, `up`, `down`, `set`);
- provision or read a secret (`make secrets`, `set_secrets.py`, `.env`, keychain);
- run `make gmail`, `make shopify`, `make voice`, `make test-live`, `make experience-live` or
  any other live business call;
- widen your own permissions, or route around a refusal from the permission layer or a hook.

## Candidate discipline

Work on an isolated branch from an exact base SHA. Commit on that branch. Push the branch only
after the evidence passes. Never merge it yourself. A candidate is **a review candidate, not
accepted or deployed**, until an independent review says otherwise and the owner acts.

If the inbox asks for something that needs the owner's approval — a service, a secret, a
Tailscale change, any live verification, anything irreversible or outward-facing — stop at that
point and write what you are waiting for into the outbox. Never infer approval.
````

## 6. `.claude/skills/agent-architecture-audit/`

Three files. The skill was audited at ECC commit `07756cee15788a54506031462794ad645719b028`
(`SKILL.md` sha256 `64f57e232c3533877403703bc95b3c75df9de23f657899a306f13c703009ff57`, 0
SkillSpector issues, no executable scripts). The vendored copy differs from upstream in
**one line of frontmatter** and nothing else; the body is byte-identical.

- **`SKILL.md`** — upstream `skills/agent-architecture-audit/SKILL.md` at that commit, with
  `tools: Read, Write, Edit, Bash, Grep, Glob` replaced by `tools: Read, Grep, Glob`. The
  audit recommended Read/Grep/Glob/Bash; Bash is dropped here too because the skill's only
  shell use is `rg` searches, which the `Grep` tool serves, and a read-only reviewer slot does
  not need command execution. Widening back to Bash is a one-word review decision.
  The exact candidate bytes were re-scanned in this round (see `DEV_ENVIRONMENT.md` §5.1).
- **`LICENSE`** — the ECC repository's MIT license, verbatim (`Copyright (c) 2026 Affaan
  Mustafa`). The frontmatter's `origin: oh-my-agent-check` marks third-party-derived content
  redistributed under ECC's MIT; that upstream was not independently verified (audit §4.1).
- **`PROVENANCE.md`**:

````markdown
# Provenance

- Upstream: https://github.com/affaan-m/ECC — `skills/agent-architecture-audit/SKILL.md`
- Commit: `07756cee15788a54506031462794ad645719b028` (2026-09-19)
- Upstream SKILL.md sha256: `64f57e232c3533877403703bc95b3c75df9de23f657899a306f13c703009ff57`
- License: MIT (`LICENSE` beside this file). Frontmatter `origin: oh-my-agent-check` is
  upstream's own attribution; not independently verified.
- Local change: frontmatter `tools:` narrowed to `Read, Grep, Glob`. Body byte-identical.
- Gate: SkillSpector 2.11.2 `--no-llm` over the upstream directory (audit) and over these
  exact bytes (candidate round) — see docs/DEV_ENVIRONMENT.md §5.1.
- Update policy: docs/DEV_ENVIRONMENT.md §7 — never auto-updated; re-gate on any pin move.
- Its "Related Skills" section names ECC skills that do not exist here; they are prose, not
  dependencies.
````

## 7. What is *not* pending

`CLAUDE.md` at the repository root was written (it is not under `.claude/`). The `.gitignore`
allowlist form is in place. The hooks, their tests, the roster assertion and the isolation
proposal are in the candidate and were verified there.
