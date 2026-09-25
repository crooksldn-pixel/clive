# CROOKS OS — GPT Conversation Migration Handoff

> **SUPERSESSION NOTICE — 2026-09-23:** This file is retained as the 2026-09-19 migration handoff and contains stale active-task/state details. For current engineering/product truth, read `CURRENT_TRUTH.md` and `RECONCILIATION_2026-09-23.md`. Do not restart the old harness/watcher sequence merely because it appears below. Its durable lessons remain evidence; its then-current mechanics are not binding precedent.
>
> **2026-09-25:** the reconciliation is itself now history. `CURRENT_TRUTH.md` is the entry point. The bridge watcher described below was retired on 2026-09-25, and production runs `clive/trunk` at `ce791d03`.

**Purpose:** deterministic handoff for moving CROOKS OS work into a fresh GPT conversation without losing continuity  
**Status:** SUPERSEDED — kept as history (was ACTIVE)  
**Created:** 2026-09-19

This document is intentionally compact enough to be useful and exact enough to prevent a new director from restarting, duplicating, or accidentally constraining the project with stale context.

The canonical source of truth is GitHub, not the previous chat.

---

## 1. New-conversation bootstrap

A new GPT Director should begin by reading, in this order:

1. `docs/product-memory/CURRENT_TRUTH.md`
2. `docs/product-memory/PRODUCT_BRAIN.md`
3. `docs/product-memory/EVOLUTION_POLICY.md`
4. `docs/product-memory/DIRECTOR_PROTOCOL.md`
5. relevant ACTIVE entries in `DECISIONS.md`
6. `ROADMAP.md`
7. `SELF_IMPROVEMENT.md` when engineering autonomy, agents, deployment, review or self-modification are involved
8. latest `crooks-ai-bridge` inbox/outbox state
9. task-specific code/reports/evidence only after the active context is understood

Do **not** load the entire Git history or reconstruct the project from old chat transcripts by default.

Historical material should be retrieved only when it explains an active constraint, migration obligation, regression or previously failed approach.

---

## 2. Product doctrine that must survive the chat migration

CROOKS OS is the intelligent operating layer for the business, not a chatbot wrapper.

Core active principles:

- maximum capability, minimum visible UI,
- human attention is scarce,
- persistent business state lives outside model context,
- models propose; deterministic capabilities execute consequential actions,
- actions are verified against authoritative state,
- autonomy is narrow and earned,
- models/providers are replaceable,
- self-improvement is isolated, evidence-driven and reversible,
- implementers do not solely certify themselves,
- quality comes before model cost or elapsed time,
- owner approval should remain where valuable, but owner terminal operation should disappear from routine workflow.

### Evolution rule

Previous versions are **evidence and acceleration, not a prison**.

Preserve:
- current owner intent,
- active safety/security invariants,
- desired product outcomes,
- useful capabilities,
- hard-won lessons,
- current evidence,
- migration obligations that are genuinely still active.

Do not preserve merely because it existed:
- obsolete implementation shape,
- old UI direction,
- dead abstractions,
- stale compatibility layers,
- old model/provider assumptions,
- tests guarding behaviour the product deliberately no longer wants.

A component becoming **null** is a valid result.

If a better system fully subsumes an older responsibility, the older component may be explicitly RETIRED and removed.

Git keeps the history. Current truth drives the next release.

---

## 3. Current engineering control-plane state

Repository:
`crooksldn-pixel/clive`

### Production application

Ratified Linux production candidate:
`1cf3a0f3361b79f9de208d80f501543c53c244b5`

Observed/ratified state:
- `/opt/crooks-os` clean at the exact candidate;
- `crooks-assistant.service` installed, enabled and active;
- FastAPI bound to `127.0.0.1:8000`;
- tailnet-only Tailscale HTTPS active;
- CROOKS writes disabled;
- Gmail OAuth token still absent, so health was degraded for that reason in the last reconciliation;
- iPhone activity observed; Samsung verification remains outstanding.

DEC-048 ratifies only that already-performed state. It does not approve another deployment, new secrets, broader privileges, public/Funnel exposure, account-level connector changes or business writes.

### Bridge / watcher

Communication-only orphan branch:
`crooks-ai-bridge`

Files:
- `bridge/chatgpt-inbox.md`
- `bridge/claude-outbox.md`

Watcher:
- installed/enabled on the server;
- model `claude-fable-5-1`, effort `high`;
- reviewed source revision `5ada7b47f13547f107be1f53beeb79021cc48c24`;
- polls inbox blob SHA;
- uses a single-run lock;
- leaves failed instructions pending;
- owns outbox publication;
- production checkout remains read-only to the watcher.

### Builder / accepted environment

Canonical builder checkout:
`/opt/crooks-builder`

Observed branch:
`claude/builder-environment-repair`

Accepted Builder candidate:
`295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`

Accepted review branch:
`claude/builder-environment-repair-review`

The old watcher/unit assumption that the Builder branch is `claude/bridge-builder` is a standing discrepancy, not current truth.

### Harness hardening candidate

Candidate branch:
`claude/harness-hooks-experiment`

Exact candidate:
`dd50ebbca6eca9c4e2ee1e85ad17d2c7e5afd25e`

Exact base:
`295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`

The candidate contains the non-`.claude/` harness pieces: Bash safety guard, gitleaks gate, roster assertion, isolation proposal, tests, root `CLAUDE.md`, `.gitignore` changes and pending project-Claude-file specification. The worker could not create files under project `.claude/` because Claude Code itself refused the sensitive-file writes. DEC-049 approves those project-scoped files conceptually in isolated engineering workspaces, but it does not override that enforcement boundary. No hook is active until the project settings file exists.

### Observed workspace incident

The harness worker created a valid registered worktree at:
`/opt/crooks-builder/.worktrees/harness-hooks-experiment`

Because the accepted Builder did not yet ignore `.worktrees/`, the parent checkout showed:
`?? .worktrees/`

The watcher correctly failed closed and refused the next worker, but retried the same deterministic blocker eight times. After inspection confirmed this was the only dirty item, the owner-side Director added `.worktrees/` to the Builder checkout's local `.git/info/exclude`, restoring a clean parent without deleting/stashing/resetting anything or weakening the dirty-tree guard. The watcher was restarted and the pending independent review began.

Durable lesson:
- normal worker attempts should live outside the canonical Builder, preferably `/opt/crooks-workers/<task-id>/<attempt-id>/`, or use an equivalently proven workspace manager;
- deterministic precondition/policy failures should become `BLOCKED / ESCALATED` with one notification, not repeated transient backoff;
- the local exclude entry is a workaround, not architecture.

### Headless tool-surface risk

The ECC audit proved headless Claude under the shared `/root` identity can inherit schemas/tools for business connectors/plugins even though unattended use was permission-refused in the probe. Treat this as unnecessary attack/context surface. Future worker hardening must prove a narrow launch roster fail-closed; do not change account/global Claude settings or connector grants without explicit owner approval.

## 4. Current in-progress task — do not duplicate it

The active bridge inbox is an **independent adversarial review** of the harness candidate.

Inbox blob SHA:
`2b1030bd48ee14888e0c85b7d160fa39b2cba6eb`

Review subject:
- branch `claude/harness-hooks-experiment`;
- base `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`;
- candidate `dd50ebbca6eca9c4e2ee1e85ad17d2c7e5afd25e`.

As of this handoff update, the workspace cleanliness blocker has been cleared, the watcher was restarted, and its lock was observed **HELD**, meaning the review run had started. Do not restart, duplicate, manually implement fixes, or apply the pending `.claude/` files while that review is in flight.

The reviewer is required to inspect the actual diff/source, adversarially challenge the command guard/gitleaks gate/roster assertion, rerun evidence where practical, assess the nested-worktree design defect, and verify that no production/global/account/connector/secret/service/Tailscale/business-write change occurred.

Allowed overall verdicts are only:
- `ACCEPTABLE AS PARTIAL REVIEW CANDIDATE`; or
- `REJECT — REPAIR REQUIRED`.

Even an acceptable partial verdict does **not** mean the harness is active or fully accepted because the project `.claude/` activation files remain unapplied.

After the review completes:
1. inspect the new outbox and exact evidence;
2. accept the committed non-`.claude/` pieces only if the reviewer supports it, otherwise dispatch the smallest bounded repair;
3. resolve project `.claude/` activation through an owner-approved mechanism rather than routing around Claude Code's refusal;
4. harden workspace placement and BLOCKED-vs-RETRY behaviour before relying on unattended multi-round operation.

## 5. Approved future engineering organisation

The single-worker watcher is a proven foundation, not the final dev-team architecture.

Target:

```
Owner
  ↓
GPT Director
  ↓
Engineering Orchestrator
  ↓
Manager / specialist workers / reviewers
  ↓
Integrator
  ↓
GPT independent review
  ↓
owner approval / deployment gate where required
```

### Quality-first model routing

Do not optimise substantive work toward weaker models merely for cost or speed.

Preferred direction:

- **Claude Opus** — architecture, security, difficult diagnosis, major refactors, integration decisions, high-scrutiny review.
- **Claude Sonnet** — well-bounded implementation where quality is protected by tests/evidence/review.
- **Fable** — first-class Experience Director for substantial UX/interaction work before implementation and again as independent post-build experience review.
- **GPT Director** — decomposition, continuity, challenge/review, reconciliation and final independent review.
- cheaper/faster workers only for genuinely mechanical operations where reasoning quality is immaterial.

Automatic escalation should exist for ambiguous, repeatedly failing, high-risk or architectural work.

### Parallelism

Parallelism must improve quality and throughput without shared-state races.

Rule:

> one worker = one task = one isolated workspace = one branch = one result

Do not achieve concurrency by removing the lock and allowing multiple writers in `/opt/crooks-builder`.

Future worker locations may resemble:

```
/opt/crooks-workers/
  ui-<task>/
  backend-<task>/
  qa-<task>/
  security-<task>/
  fable-ux-<task>/
```

The Integrator alone combines candidate work and proves the integrated result.

---

## 6. Infrastructure autonomy direction

Routine infrastructure maintenance should eventually require **owner approval, not owner copy/paste**.

Target components:

- Engineering Orchestrator,
- worker/workspace manager,
- model router,
- Privileged Action Broker,
- Deployment/Infrastructure Controller,
- versioned infrastructure releases,
- deterministic health checks,
- automatic rollback.

Future watcher/orchestrator/systemd/backend updates should follow:

```
candidate
→ deterministic tests
→ security review
→ independent review
→ exact version/artifact
→ owner approval where required
→ privileged installer/controller
→ health verification
→ automatic rollback on failure
```

No component should have unrestricted authority to rewrite itself and declare the update successful.

Termius/SSH should become break-glass recovery only.

A final privileged-control-plane bootstrap may still require deliberate manual installation once; after that, normal updates should be handled by the system.

---

## 7. Near-term sequence

DEC-046 remains authoritative unless the owner explicitly changes it in canonical Git.

1. finish the in-flight harness independent review and bounded repair/acceptance work without duplicating the running round;
2. reconcile the accepted Builder Environment into the persistent builder and canonical trial records;
3. harden engineering reliability exposed by the watcher incident: external worker workspace placement, deterministic `BLOCKED / ESCALATED` classification, and remaining Builder/watcher branch/tooling discrepancies;
4. provision remaining runtime secrets only through an approved process — Gmail OAuth remains outstanding;
5. verify real Samsung/iPhone/runtime behaviour — iPhone observed, Samsung outstanding;
6. perfect current CROOKS UI;
7. perfect response behaviour and latency;
8. run real-device/real-world sessions and collect evidence;
9. implement Engineering Orchestrator / Dev Team V1 under the already-granted owner implementation approval and existing safety/review gates;
10. bootstrap the Privileged Action Broker + Deployment/Infrastructure Controller;
11. continue World / Event Ledger / Attention / automation / integrations from a stable product baseline.

A small **Engineering Console** is captured as IDEA-052, not yet implementation-approved. If the owner later approves it, build it only after the immediate workspace/retry hardening. It should be a private deterministic control/status surface, not a browser terminal, and should either evolve into the Orchestrator control surface or be retired when it has no unique responsibility.

Do not skip current-product quality because future architecture is interesting.

## 8. Safety/action invariants

For consequential CROOKS business actions preserve:

- model proposes,
- server stores immutable exact action,
- client approval posts identity only,
- server executes staged args once,
- TTL/session/turn binding,
- risk separated from execution disposition,
- voice “yes” never authorises sensitive writes,
- preconditions are re-read,
- deterministic verification,
- VERIFIED only on actual success,
- unknown writes fail closed,
- no arbitrary HTML/JS,
- no service-worker write cache/replay,
- least privilege,
- append-only PII-minimised action ledger.

Do not casually weaken these during migrations or refactors.

---

## 9. Working style for owner interaction

For hands-on server/deployment troubleshooting:

- give exactly **one step at a time** unless the owner explicitly asks for a full sequence,
- provide the exact command/action,
- state what success should look like,
- then stop,
- never ask the owner to paste secrets/tokens/passwords/private keys,
- remember the long-term objective is to eliminate routine terminal use entirely.

For normal architecture/product discussion, direct comprehensive answers are appropriate.

---

## 10. First actions in a new GPT conversation

The new GPT Director should:

1. run the `BOOTSTRAP` procedure from `DIRECTOR_PROTOCOL.md`;
2. read CURRENT_TRUTH and this handoff from the explicit product-memory ref;
3. inspect the current bridge inbox/outbox and watcher state;
4. if the harness review is still running, do not interfere;
5. if it completed, inspect the actual verdict, exact candidate/evidence and reviewer findings before issuing any repair or acceptance instruction;
6. never treat the local `.git/info/exclude` workaround as the durable workspace architecture;
7. preserve the distinction between deterministic `BLOCKED / ESCALATED` failures and genuinely transient retryable failures;
8. update `CURRENT_TRUTH.md` whenever material state changes.

Do not ask the owner to reconstruct the old chat. Do not infer that captured ideas such as IDEA-052 are implementation approval.

## 11. Memory discipline

The durable memory model is:

- **Git history** = archive,
- **PRODUCT_BRAIN / DECISIONS / EVOLUTION_POLICY** = durable intent and rationale,
- **CURRENT_TRUTH** = active compact state,
- **ROADMAP** = sequencing,
- **bridge inbox/outbox** = current machine-to-machine engineering round,
- **this handoff** = conversation migration entry point.

When active reality changes, update the canonical documents rather than appending endless handoff prose.

The purpose of memory is to prevent repeated mistakes and accelerate progress.

It must never become architectural gravity.
