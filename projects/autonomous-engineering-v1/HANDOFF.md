# Fresh Claude Code session handoff

Use this after connecting Claude Desktop/Code over SSH and opening the dedicated planning worktree.

Paste:

> You are in the CLIVE repository on the dedicated planning/autonomous-engineering-v1 branch/worktree. This is the final planning phase for CLIVE Autonomous Engineering V1.
>
> Read root CLAUDE.md, then projects/autonomous-engineering-v1/README.md, PROMPT.md and ACCEPTANCE.md. Read crooks-assistant/MAP.md and CURRENT_TRUTH before making claims about CLIVE.
>
> Load autonomous-engineering-planner, clive-engineering, clive-product-philosophy and clive-testing. Use the repo-auditor and host-auditor agents first; both are read-only. Then use the architect agent to synthesize, the quality reviewer to attack the plan, and the final reviewer to decide whether the planning package is READY.
>
> Reconcile the research against actual source and actual SSH host. Distinguish BUILT, ACTIVE, PROVEN, GAP and UNKNOWN.
>
> This phase is plan only. Do not modify CLIVE application code, production, /opt/crooks-os, systemd, credentials, worker state or deploy configuration. Do not install tools.
>
> Update the planning artifacts with evidence and produce a PR-sized final implementation sequence with acceptance, tests, rollback, dependencies and owner-visible payoff for every PR.
>
> Do not stop at generic architecture. Make the next implementation session able to execute without redoing the research.
>
> Do not start implementation until I explicitly approve the final plan.

## Worktree setup

From a clean engineering checkout:

```bash
git fetch origin
git worktree add /srv/clive-engineering/autonomy-plan origin/planning/autonomous-engineering-v1
cd /srv/clive-engineering/autonomy-plan
git status --short --branch
claude
```

If you need to commit planning updates from that worktree, attach/create the local branch deliberately without disturbing the FMHY checkout.

For mobile SSH, use tmux so the interactive planning session survives a terminal disconnect. Durable implementation later must not depend on tmux.
