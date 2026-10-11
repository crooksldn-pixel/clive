# CLAUDE.md

This repository is CLIVE, George's business assistant (`crooks-assistant/`). The CROOKSLDN
Shopify theme is not part of CLIVE: it is moving to the private repository
`crooksldn-pixel/crooksldn-theme`; until then, its source is the branch
`claude/crooksldn-theme-init-bnen7a`. CLIVE work never touches it (`docs/repo/BOUNDARY.md`).

For any work on CLIVE:

1. **Read `crooks-assistant/MAP.md` first.** It covers where CLIVE started, the rules that never
   bend, a turn end to end, and every package, page, store and switch. It also lists what is parked.
2. **Follow the rules in it.** They override convenience. If a change would break one, stop and
   say so instead of working around it.
3. **Then read `crooks-assistant/docs/product-memory/CURRENT_TRUTH.md`** for what is live now.

Where things live:

- **Decisions:** `crooks-assistant/docs/product-memory/DECISIONS.md`. Never edit an existing
  decision's text; only its status line may change. Record a change as a new DEC entry.
- **Deploy:** `crooks-assistant/docs/DEPLOY_LINUX.md` covers the server, secrets, deploy and
  rollback. Each deploy's record is in `crooks-assistant/reports/deploy-<sha>.md`.
- **Tests:** `crooks-assistant/README.md`. Run the focused tests for what you touch; the full
  suite is GitHub's `acceptance` run.

After adding or removing a package, page, store or switch, run `python scripts/map.py` in
`crooks-assistant/`. Its `--check` says whether MAP.md is stale.

## Branch-local experiment: FMHY public link finder

When the current branch is `experiment/fmhy-link-finder`, or work is under
`experiments/fmhy-link-finder/`, this is **not a CLIVE product integration**. Before coding, read
`experiments/fmhy-link-finder/PROMPT.md`, `ACCEPTANCE.md`, and `REFERENCES.md`, then load the
`fmhy-link-finder` skill.

Keep implementation inside `experiments/fmhy-link-finder/`. Do not modify CLIVE production
routing, tools, stores, schemas, deployment, or `crooks-assistant/pyproject.toml` for this
experiment. Reuse ideas, not runtime coupling.

For library/API syntax, prefer current documentation through Context7 when available. For browser
inspection and live verification, prefer the project Playwright MCP. Browser work is limited to
public catalogue/search/title pages: do not inspect or extract media delivery URLs, player tokens,
CDN requests, DRM data, hidden stream APIs, or bypass access controls/anti-bot challenges.
