# CROOKS

A local-first business assistant. FastAPI + a hand-written PWA. Voice-first, read-mostly,
safety-gated. This file points; it does not contain.

## Read these before changing anything
- `crooks-assistant/docs/product-memory/PRODUCT_BRAIN.md` and `DECISIONS.md` on branch
  `claude/product-memory-foundation` — read them by explicit ref; they are not on this branch
- `crooks-assistant/DESIGN.md` — the UI language, and the authority order for UI work
- `crooks-assistant/PHASE_1_UX_BASELINE.md` — what each surface is for
- `crooks-assistant/docs/ENGINEERING_LOOP.md` — how work gets done here
- `crooks-assistant/docs/DEV_ENVIRONMENT.md` — the tools, and their limits
- `crooks-assistant/docs/dev-environment/CLAUDE_PROJECT_LAYOUT.md` — this configuration, and why

## Commands (from `crooks-assistant/`)
    make test                              # offline suite (~2800 tests)
    make lint                              # ruff
    make experience                        # scenarios against the golden fixture world
    python3 scripts/dev_env.py doctor      # is the pinned tooling present? (read-only)
    eval "$(python3 scripts/dev_env.py env)"   # before any browser check

## Safety invariants — never edit these away
Writes stay disabled. FastAPI binds 127.0.0.1. Models propose; the server executes and
verifies. A spoken "yes" authorises nothing. Unknown writes fail closed. No live Shopify,
Gmail or ElevenLabs call from engineering work. No secret value is ever printed or committed.

## Builder vs production
You are in a builder worktree. Never edit, switch or reset `/opt/crooks-os`. Never merge to
production. Never deploy, install, start or restart a service. Never touch `/root/.claude`.
Never push to `main`, `master`, `claude/linux-prod-migration-production`,
`claude/product-memory-foundation` or `crooks-ai-bridge`.

## Hooks and rules
The project-scoped hooks live in `crooks-assistant/scripts/hooks/` (`guard_bash.py`, a
fail-closed destructive/production/secret guard; `gitleaks_gate.py`, a secret scan before
`git commit` / `git push`). They are registered by `.claude/settings.json`, and the editing
rules live in `.claude/rules/`. **If those `.claude/` files are absent in this checkout, the
hooks are not active** — see `crooks-assistant/docs/dev-environment/PROJECT_CLAUDE_FILES_PENDING.md`
for the exact files and why they could not be written by the worker. A denial from a hook is
a boundary, not a puzzle: do not rephrase the command to get past it — report it.
