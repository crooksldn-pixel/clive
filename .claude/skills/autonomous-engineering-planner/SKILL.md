---
name: autonomous-engineering-planner
description: Plan CLIVE Autonomous Engineering V1 by auditing existing machinery, reconciling host truth, and producing a reversible PR-sized implementation plan without implementing it.
---

# Autonomous Engineering Planner

Use only for the Autonomous Engineering V1 planning project.

## Workflow
1. Read project README, PROMPT and ACCEPTANCE.
2. Read MAP and CURRENT_TRUTH.
3. Inventory existing engineering machinery before proposing additions.
4. Run repo and host audits read-only.
5. Classify evidence BUILT / ACTIVE / PROVEN / GAP / UNKNOWN.
6. Draft target architecture around the existing dispatcher.
7. Define Project/DAG, skills/context, quality routing, attention contract and resilience.
8. Produce a PR-sized implementation sequence.
9. Ask independent reviewer agents to challenge it.
10. Stop before implementation and request owner approval.

## Rules
- no production mutation;
- no worker re-pin during planning;
- no install/restart/deploy commands;
- no replacement orchestrator unless evidence proves the current one insufficient;
- no arbitrary agent swarm;
- no automatic deploy;
- no performance claim without baseline;
- no conflating docs with runtime truth.
