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


## Autonomous Engineering V1 planning branch

When the current branch is `planning/autonomous-engineering-v1`, this branch is a planning environment, not an implementation branch.

Before doing anything else:

1. Read `projects/autonomous-engineering-v1/README.md`.
2. Read `projects/autonomous-engineering-v1/PROMPT.md`.
3. Read `projects/autonomous-engineering-v1/ACCEPTANCE.md`.
4. Load the `autonomous-engineering-planner`, `clive-engineering`, `clive-product-philosophy` and `clive-testing` skills.
5. Use the project agents for independent repo audit, host audit, architecture and review.

Planning rules:

- Reconcile plans against real repository and read-only host evidence before proposing code.
- Reuse the existing dispatcher, workspaces, reviewers, check sandbox, engineering bridge, Builds surfaces and Bench wherever possible.
- Do not modify production, `/opt/crooks-os`, systemd, credentials, secrets, worker runtime state or deployment configuration.
- Do not implement Autonomous Engineering V1 application code on this planning branch.
- Planning changes should stay inside `projects/autonomous-engineering-v1/`, `.claude/agents/`, `.claude/skills/`, this planning section and project MCP config unless the owner explicitly widens scope.
- Host inspection is read-only. Install/restart/mutate/deploy commands are forbidden during planning.
- Production deployment remains an explicit owner decision.
- End planning with a repo-specific PR-sized implementation plan, measurable acceptance contracts, unresolved owner decisions and a GO / REVISE / STOP recommendation.
- Do not begin implementation until the owner approves that final plan.
