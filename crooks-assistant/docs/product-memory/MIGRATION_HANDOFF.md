# CROOKS OS — GPT Conversation Migration Handoff

**Purpose:** deterministic handoff for moving CROOKS OS work into a fresh GPT conversation without losing continuity  
**Status:** ACTIVE  
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
`crooksldn-pixel/Shopify-theme`

### Production application

**Ratified Linux production candidate:**
`1cf3a0f3361b79f9de208d80f501543c53c244b5`

Independent read-only reconciliation observed:
- production checkout clean and byte-identical to the candidate;
- `crooks-assistant.service` installed, enabled and active;
- FastAPI bound to `127.0.0.1:8000`;
- tailnet-only Tailscale HTTPS active;
- CROOKS writes disabled.

The owner explicitly ratified this already-performed state on 2026-09-19 (DEC-048). The ratification does not approve another deployment, new secrets, broader privileges, public/Funnel exposure, or business writes.

### Linux migration review provenance

Review branch:
`claude/linux-prod-migration-review`

Candidate commit:
`1cf3a0f3361b79f9de208d80f501543c53c244b5`

Known review proof:
- 2886 passed
- 8 skipped
- 2 deselected
- Ruff clean
- systemd-analyze verification clean

The review candidate has now been deliberately promoted by the owner and canonically ratified.

### Bridge

Communication-only orphan branch:
`crooks-ai-bridge`

Files:
- `bridge/chatgpt-inbox.md`
- `bridge/claude-outbox.md`

Do not merge this branch into application history.

### Watcher

The CROOKS bridge watcher is installed, enabled and running on the Hetzner server.

Important verified properties:

- watches inbox blob SHA rather than generic branch motion,
- failed inbox instructions remain pending,
- bounded retry/backoff,
- single-run lock,
- builder and bridge are standalone clones,
- production checkout is read-only to the watcher,
- Claude Max auth can refresh,
- Claude prompt is delivered over stdin,
- watcher owns outbox commit/push,
- end-to-end automatic smoke test passed,
- the owner no longer needs to relay normal GPT ↔ Claude messages.

The stdin launch regression was fixed and covered by the watcher test suite before the successful smoke test.

### Builder

Standalone isolated builder:
`/opt/crooks-builder`

Normal branch:
`claude/bridge-builder`

Production must not be used as the autonomous worker checkout.

---

## 4. Current in-progress task — do not duplicate it

At handoff time, the automated bridge inbox contains the task:

**build the permanent CROOKS Builder development environment**

Inbox blob SHA:
`607b607e54eb194b81d708dfbc7bd744c2e8cd18`

The latest outbox still contains the preceding successful watcher smoke test, so the Builder Environment task should be treated as **in progress / awaiting a new outbox**, not re-submitted.

A new GPT Director should first inspect the latest bridge outbox before issuing another builder-environment instruction.

The task includes:

- inventory of existing tools/skills,
- third-party skill security scanning,
- Anthropic frontend-design + webapp-testing,
- Vercel web-design-guidelines,
- Impeccable,
- create-design-md,
- selected Taste skills,
- DESIGN.md,
- Playwright/browser/accessibility tooling,
- engineering/security/performance tools,
- concise project CLAUDE.md/rules/hooks,
- DEV_ENVIRONMENT.md,
- idempotent environment bootstrap/check,
- exact version/provenance manifest,
- no production deployment.

Do not interrupt or duplicate that task unless evidence shows it failed or became stuck.

---

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

Unless new evidence changes sequencing:

1. reconcile the accepted permanent Builder Environment into the persistent builder and trial records,
2. **Linux migration/promotion — ratified complete at `1cf3a0f`,**
3. provision remaining runtime secrets through approved process — Gmail OAuth still outstanding,
4. **CROOKS backend — installed/enabled/running and ratified,**
5. **private tailnet-only Tailscale HTTPS — active and ratified,**
6. verify remote iPhone/Samsung/runtime behaviour — iPhone observed; Samsung outstanding,
7. perfect current UI and response behaviour,
8. run real-device/real-world sessions,
9. build Engineering Orchestrator V1 with model routing, isolated parallel workers and Fable,
10. bootstrap Privileged Action Broker + Deployment/Infrastructure Controller,
11. continue World / Event Ledger / Attention / automation / integrations from a stable product baseline.

Do not skip current-product quality because future architecture is interesting.

---

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

## 10. First actions in the new GPT conversation

The new GPT Director should:

1. run the `BOOTSTRAP` procedure from `DIRECTOR_PROTOCOL.md`,
2. inspect the current bridge inbox/outbox,
3. determine whether the Builder Environment round completed,
4. if complete, review the actual candidate diff/tests/evidence before deciding the next instruction,
5. if still running, do not interfere,
6. if failed, diagnose from evidence before retrying,
7. update `CURRENT_TRUTH.md` whenever material state changes.

Do not ask the owner to reconstruct the old chat.

---

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
