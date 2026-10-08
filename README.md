# CLIVE

This repository is CLIVE, George's business assistant for CROOKSLDN, and the engineering control
plane that builds it. The app is in [`crooks-assistant/`](crooks-assistant/).

- **Start here:** [`CLAUDE.md`](CLAUDE.md), then [`crooks-assistant/MAP.md`](crooks-assistant/MAP.md).
- **What is live now:** [`crooks-assistant/docs/product-memory/CURRENT_TRUTH.md`](crooks-assistant/docs/product-memory/CURRENT_TRUTH.md).
- **How the production host runs it:** [`crooks-assistant/docs/DEPLOY_LINUX.md`](crooks-assistant/docs/DEPLOY_LINUX.md).

Changes reach `clive/trunk` only through a pull request whose exact head passed acceptance.

## What is not here

- **The Shopify theme.** It is moving to its own private repository,
  `crooksldn-pixel/crooksldn-theme`, and will ship to Shopify with the Shopify CLI from there;
  until then, its source is this repository's branch `claude/crooksldn-theme-init-bnen7a`. The theme
  files that sat at this repository's root until October 2026 were a stale 20 July snapshot,
  not the live theme, and they have been removed.
- **The sister apps.** CROOKS Returns and CLIVE Shipping (one embedded Shopify app, CROOKS
  Operations) live on branch `claude/compassionate-dirac-44hnee` for now. George deploys them
  with Docker Compose on the production host, outside CLIVE.

## What else is at the root

- [`docs/repo/BOUNDARY.md`](docs/repo/BOUNDARY.md): what lives where, the rules that keep CLIVE
  and the theme apart, and the branch cleanup.
- [`docs/phase6/`](docs/phase6/): the CROOKS OS appliance layer (Phase 6, September 2026). Its Mac
  half, the CROOKS Control menu-bar app and its `crooks-control` command, was retired on 8 October
  (DEC-071, ruling 38); the server's way of doing the same is in `DEPLOY_LINUX.md`.
- [`.claude/skills/`](.claude/skills/): pinned design skills for the builders, which CLIVE's
  knowledge digester also reads.
- [`.github/workflows/acceptance.yml`](.github/workflows/acceptance.yml): the acceptance run on
  every push.
