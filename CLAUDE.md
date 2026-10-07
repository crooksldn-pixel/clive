# CLAUDE.md

This repository holds two things: the CROOKSLDN Shopify theme (at the root, see `README.md`) and
CLIVE, George's business assistant (`crooks-assistant/`).

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
