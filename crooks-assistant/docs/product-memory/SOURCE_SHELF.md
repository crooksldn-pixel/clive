# Source Shelf

**Status:** owner-supplied candidates, triaged 2026-09-24. Triage is a first read, not an assimilation verdict; every source still goes through SOURCE_ASSIMILATION_V1.md before anything is adopted.

## Batch 1 - make the dev team build better screens (serves GENERATIVE_UI_V1.md)

- Taste Skill (Leonxlnx/taste-skill, MIT) - anti-generic, premium frontend rules; many same-named copies exist, pin the original.
- Web Design Guidelines (vercel-labs/agent-skills) - 100+ interface rules; candidate automatic check on every UI candidate; freeze its live-fetched rules.
- Awesome Design - design references for agents; exact upstream to confirm.
- Image to Code - screenshot or mockup to component; exact upstream to confirm.
- Playwright CLI - real-browser checks of the phone surface as evidence for UI candidates.

## Batch 2 - things CLIVE could do, pulled by real capability gaps

- Agent Browser (vercel-labs) and PinchTab (pinchtab/pinchtab) - using websites that have no API, such as courier tracking pages; evaluate one against the other.
- Jev (TypeSafe AI) - fast typed decisions for intent routing, significance and guardrails; evaluate on CLIVE's own golden scenarios. Owner gate: API key and a data policy for what business text leaves the host.
- check-if-email-exists (reacherhq) - address verification before sending.
- Agent-Reach (Panniantong) - reading public social platforms for brand listening.
- Voicebox (jamiepine) - local voice if the hosted voice stays unavailable; likely too slow without a GPU.

## Batch 3 - engineering machinery: mine patterns, do not adopt runtimes

- Pullfrog - agents triggered by CI failures; the loop should queue a repair when GitHub acceptance fails.
- LangWatch - tracing and evaluation; the evaluation layer CLIVE lacks; hosted or elsewhere, not on this server.
- Orca, Multica - parallel agents, worktrees, mobile monitoring of agent work.
- Dagu - scheduled workflow runs.
- Aider - a second worker for measured comparison on CLIVE tasks.

## Reference architectures - read, do not install

- Hermes Agent, OpenClaw - general agents that write their own skills and work across messaging; community skill marketplaces are where malicious skills appear, so quarantine applies in full.

## Not now

- Fleetbase - a full logistics operating system, beyond current scale; revisit for fulfilment work.
- Polar - billing for selling software; only relevant if CLIVE is sold.
- llama.cpp - local models; no GPU and little free memory here.
- worldmonitor (koala73) - global news dashboard; no current business gap.
