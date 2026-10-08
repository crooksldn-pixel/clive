# Proposed project-scoped Claude configuration

**Status:** PROPOSED AND NOT INSTALLED.

Writes to `/opt/crooks-builder/.claude/` are refused by the agent's permission layer. That refusal
was not worked around: no `.claude/` directory was created, no skill was installed, and no hook is
active. This file specifies the layout precisely enough to be applied in one reviewed step.

Nothing here takes effect until a human creates these files.

---

## 0. Prerequisite: the `.gitignore` line

The repository root `.gitignore` currently has:

```
.claude/
```

Git **cannot re-include a file inside an excluded directory**, so negation patterns under
`.claude/` are dead while the trailing slash is there. Adopting this layout requires:

```gitignore
# Claude Code's own scaffolding: the agent worktrees it creates while working are checkouts of
# THIS repository living inside it. Excluding the CONTENTS rather than the directory keeps every
# worktree and scratch file out while letting versioned project configuration back in by name.
.claude/*
!.claude/rules/
!.claude/skills/
!.claude/settings.json
```

---

## 1. Layout

```
CLAUDE.md                      # short. pointers, not content.
.claude/
  rules/
    safety.md                  # the invariants that must never be edited away
    python.md                  # app/, config/, scripts/, tests/
    frontend.md                # web/
    shell.md                   # mac/, launchd/
    testing.md                 # how to run what, and what proves a change
    builder-vs-production.md   # the boundary
  skills/
    frontend-design/           # anthropics/skills @ 34040c9  (vendored, pinned)
    web-interface-guidelines/  # vercel-labs @ e3d624b        (CONTENT ONLY — never install.sh)
    redesign-skill/            # Leonxlnx/taste-skill @ e79ca9e
    image-to-code-skill/       # Leonxlnx/taste-skill @ e79ca9e
  settings.json                # hooks
```

Only the four skills that **cleared** the §5 gate in `docs/DEV_ENVIRONMENT.md` appear here.
`webapp-testing` and `taste-skill` are rejected; `create-design-md` is not installed; `impeccable`
is deferred.

---

## 2. `CLAUDE.md` — keep it short

It should point, not contain. Thousands of lines in `CLAUDE.md` is the failure mode. Proposed
content, in full:

```markdown
# CROOKS

A local-first business assistant. FastAPI + a hand-written PWA. Voice-first, read-mostly,
safety-gated.

## Read these before changing anything
- `crooks-assistant/docs/product-memory/PRODUCT_BRAIN.md` — what the product is
- `crooks-assistant/docs/product-memory/DECISIONS.md` — decisions not to reverse silently
- `crooks-assistant/DESIGN.md` — the UI language, and the authority order for UI work
- `crooks-assistant/PHASE_1_UX_BASELINE.md` — what each surface is for
- `crooks-assistant/docs/ENGINEERING_LOOP.md` — how work gets done here
- `crooks-assistant/docs/DEV_ENVIRONMENT.md` — the tools, and their limits

## Commands
    make test          # offline suite (~2800 tests)
    make lint          # ruff
    make experience    # scenarios against the golden fixture world
    python3 scripts/dev_env.py doctor    # is the tooling present?
    eval "$(python3 crooks-assistant/scripts/dev_env.py env)"   # before any browser check

## Safety invariants — never edit these away
Writes stay disabled. FastAPI binds 127.0.0.1. Models propose; the server executes and verifies.
A spoken "yes" authorises nothing. Unknown writes fail closed.
See `.claude/rules/safety.md`.

## Builder vs production
You are in a builder worktree. Never edit, switch or reset `/opt/crooks-os/crooks-assistant`.
Never merge to production. Never deploy. See `.claude/rules/builder-vs-production.md`.
```

---

## 3. `.claude/rules/` — what each file carries

Path-scoped so the right rules load for the file being edited.

**`safety.md`** — the `PRODUCT_BRAIN` §9 invariants, restated as editing rules: writes disabled
(`DEC-027`), loopback binding (`DEC-020`), proposal → authorise → re-read → execute → verify
(`DEC-005`), voice "yes" authorises nothing (`DEC-006`), unknown writes fail closed (`DEC-007`),
no arbitrary HTML/JS execution, no service-worker write replay. Plus: these are changed by an
explicit owner decision recorded in `DECISIONS.md`, never as a side effect.

**`python.md`** — ruff is the formatter/linter of record (`line-length = 100`, `py311`). Pyright
is advisory and has no baseline. `asyncio_mode = "auto"`. Markers `live` and `macos` mean a test
needs something this host may not have. Never add a retry plugin.

**`frontend.md`** — `DESIGN.md` governs. Use the token ladder; never a raw
`rgba(255,255,255,…)`. Biome is check-only — **never** `--write` or `--apply` over `web/`. Never
add a web font, a CSS framework or a component library. The layer table in `DESIGN.md` §9.2 is a
safety invariant. Every change is verified at the four viewports in `DESIGN.md` §13.

**`shell.md`** — ShellCheck advisory; `shfmt -d` only, never `-w`.

**`testing.md`** — `make test` for the offline suite. The browser gate needs
`eval "$(… dev_env.py env)"` first, or it reports itself skipped. A skipped browser check has
proved nothing — never record it as a pass. Don't run the full suite after every edit.

**`builder-vs-production.md`** — the boundary, per `DEC-011`/`DEC-012`: isolated worktree, no
merge to production, no deploy, production checkout is read-only.

---

## 4. Hooks — proposed, deliberately conservative

The rule that shapes all of these: **do not run the full suite after every file edit, and never
let a hook mutate source.** Every hook below is read-only and reports.

| Trigger | Hook | Scope |
|---|---|---|
| `PostToolUse` on Edit/Write to `**/*.py` | `ruff check` **on the changed file only** | targeted feedback |
| `PostToolUse` on Edit/Write to `**/*.sh` | `shellcheck` on the changed file | advisory |
| `PostToolUse` on Edit/Write to `web/**` | `biome check` on the changed file, **no `--apply`** | advisory |
| `PreToolUse` on a commit/publish command | `gitleaks` over the staged candidate | **blocking** |

Deliberately **not** hooks:

- the full test suite, or the browser gate — far too slow for an edit hook; they are explicit
  steps in the workflow, run when a UI candidate is complete
- anything with `--write`, `--fix` or `--apply`
- anything that reaches the network on an edit

The Gitleaks hook must report **rule and path only**. A secret value is never printed, echoed or
committed.

---

## 5. Future specialist-agent slots

Placeholders for `DEC-013` (implementers do not solely review themselves). Not created here.

| Slot | Job |
|---|---|
| `ui-implementer` | applies a UI change and captures before/after at the four viewports |
| `ui-critic` | adversarial review of the captured evidence; does not implement |
| `safety-reviewer` | reviews any diff touching proposals, actions, verification or secrets |
| `test-author` | writes the reproduction before the fix |

---

## 6. Vendoring the cleared skills

For each: clone at the pinned commit, copy the skill directory only, and record the commit.

```bash
# frontend-design — anthropics/skills @ 34040c9
#   copy skills/frontend-design/  (SKILL.md + LICENSE.txt; no scripts)

# web-interface-guidelines — vercel-labs @ e3d624b
#   copy command.md, AGENTS.md, LICENSE
#   DO NOT copy or run install.sh: it curls unpinned `main` into $HOME/.claude/commands
#   and into six other agent tools. See docs/DEV_ENVIRONMENT.md §5.2.

# redesign-skill, image-to-code-skill — Leonxlnx/taste-skill @ e79ca9e
#   copy skills/redesign-skill/ and skills/image-to-code-skill/ ONLY.
#   Do NOT copy skills/taste-skill/ — rejected, see docs/DEV_ENVIRONMENT.md §5.2.
```

After vendoring, re-run the gate on what actually landed:

```bash
skillspector scan .claude/skills/<name> --no-llm --format json --output .tooling/scans/<name>.json
```
