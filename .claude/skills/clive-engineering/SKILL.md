---
name: clive-engineering
description: Repository and engineering-control rules for planning or building CLIVE without duplicating its existing dispatcher, review, acceptance, sandbox or deployment boundaries.
---

# CLIVE Engineering

Always read root CLAUDE.md, crooks-assistant/MAP.md and CURRENT_TRUTH.

Core rules:
- inspect existing modules before creating new infrastructure;
- durable engineering belongs to the existing orchestrator/dispatcher;
- checks and independent review are separate evidence layers;
- reviewer independence and exact candidate SHA are non-negotiable;
- production deploy is separate from trunk;
- protected paths/decisions are not convenience obstacles;
- never infer live state solely from docs.

For every proposed new engineering component state:
1. which existing component it extends;
2. why extension is insufficient without the new part;
3. failure/rollback behavior;
4. how it is tested.
