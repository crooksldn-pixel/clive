# CROOKS OS — Current Truth

**Purpose:** compact active context for GPT/Claude/Fable/engineering workers  
**Status:** ACTIVE — update whenever a material product/architecture state changes  
**As of:** 2026-09-19

This file is intentionally not a historical transcript. It answers: **what is true and important now?**

For historical rationale, use Git and DECISIONS.md. For release evolution rules, use EVOLUTION_POLICY.md.

## Product

CROOKS OS is the intelligent operating layer for the business: persistent state, controlled capabilities, verified actions, proactive exception handling, and minimal owner attention.

Core product principles remain:

- maximum capability, minimum visible UI,
- human attention is scarce,
- persistent business state outside conversational memory,
- models propose; deterministic capabilities execute consequential actions,
- autonomy is narrow and earned,
- models/providers are replaceable,
- self-improvement is isolated, evidence-driven and reversible.

## Engineering control plane

- Canonical repository: `crooksldn-pixel/Shopify-theme`.
- Canonical product memory currently lives on `claude/product-memory-foundation`; read it by explicit ref. The default theme branch is not the CROOKS product-memory source.
- **Linux production is ratified at exact candidate `1cf3a0f3361b79f9de208d80f501543c53c244b5` (DEC-048).** Independent read-only reconciliation observed `/opt/crooks-os` clean and byte-identical to that candidate, `crooks-assistant.service` installed/enabled/active on `127.0.0.1:8000`, and tailnet-only Tailscale HTTPS. The owner explicitly ratified that already-performed state on 2026-09-19. This does not authorise another deployment, new secrets, broader privileges, public/Funnel exposure, or CROOKS writes.
- The GitHub communication bridge uses orphan branch `crooks-ai-bridge`.
- The CROOKS bridge watcher is installed and enabled. Its runtime is now explicitly pinned to `claude-fable-5-1` at `high` effort from reviewed source revision `5ada7b47f13547f107be1f53beeb79021cc48c24`; the corrected installer upgrade-order regression suite passed `126 passed, 0 failed`. A real unattended post-install smoke round consumed inbox blob `5d659fbc9418f378a10ddc5666e79ffc5b94ae7c`, published a new outbox, made no application/infrastructure/production changes, and returned the watcher to `pending no`, `failures 0`, `lock free`. The single-worker bridge therefore has a verified deterministic Claude model/effort baseline; future Engineering Orchestrator routing remains task-specific rather than permanently fixed to this one model.
- Headless Claude runs in the standalone isolated builder clone at `/opt/crooks-builder`, not the production checkout.
- **Observed workspace-management incident (2026-09-19):** the harness worker correctly created a registered isolated worktree at `/opt/crooks-builder/.worktrees/harness-hooks-experiment`, but the accepted Builder checkout did not yet ignore `.worktrees/`. The watcher therefore saw `?? .worktrees/` and correctly failed closed rather than launching another headless worker, but it retried the same deterministic precondition failure eight times. After inspecting the actual status and confirming no unfinished tracked work, the owner-side Director added `.worktrees/` only to the Builder checkout's local `.git/info/exclude`; the Builder returned clean and the watcher was restarted. This was a local bookkeeping correction, not a tracked-code change, stash/reset/clean, or weakening of the dirty-tree guard.
- **Durable lesson from that incident:** legitimate worker workspaces should not live in a place that makes the canonical Builder appear dirty. The preferred V1 shape remains worker attempts outside the canonical Builder, e.g. `/opt/crooks-workers/<task-id>/<attempt-id>/`, or an equivalently proven workspace manager. Deterministic safety/precondition failures such as dirty workspace, missing permission, missing required secret/capability, or invalid task contract should transition to `BLOCKED / ESCALATED` and notify once rather than consume repeated transient retry/backoff cycles. Backoff retries are for genuinely transient transport/provider failures. This is an observed design requirement, not yet a claim that the watcher implements the classification.
- **Harness candidate review is in flight:** branch `claude/harness-hooks-experiment`, exact candidate `dd50ebbca6eca9c4e2ee1e85ad17d2c7e5afd25e` from accepted Builder base `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`. The committed non-`.claude/` pieces are under independent adversarial review via inbox blob `2b1030bd48ee14888e0c85b7d160fa39b2cba6eb`. The watcher lock was observed held after the workspace blocker was cleared and the service restarted. Do not call the harness accepted or active: project `.claude/` files remain unapplied because the worker hit Claude Code's sensitive-file boundary.
- Watcher publication of the outbox is watcher-owned; the owner is no longer the normal message courier.
- **Builder Environment is independently accepted at `claude/builder-environment-repair-review`, commit `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`.** Director review verified the exact published identity and one-commit diff from `326c150`, inspected the actual repaired implementation, and checked the SHA-bound reconstruction/gate evidence. BE-01 through BE-04 are closed: manifest handling no longer crashes; doctor fails closed on wrong/failed/unverifiable tools; shell exports use safe quoting; and the declared environment was reconstructed twice from a checkout with no `.tooling/` or `.venv/`, producing an identical environment fingerprint. The exact-candidate suite reported `2834 passed, 2 skipped, 2 deselected`; `tests/test_dev_env.py` reported 22 passed; lint passed; candidate secret scans reported no findings; the review branch was read back at the exact SHA and was not merged or deployed.
- The accepted Builder candidate pins release tags/assets and enforces pre-extraction and post-install integrity checks. Four upstreams (shellcheck, fd, ast-grep, hyperfine) do not publish independent checksum files; their committed asset digests are enforced but remain explicitly advisory as first-fetch observations rather than upstream attestations.
- SkillSpector provenance is now a fail-closed PEP 610 commit check. The existing `/opt/crooks-builder` tooling was installed using the older local-path method, so its own `doctor` is expected to fail until that gitignored Builder-local tool install is reconciled to the accepted pinned git requirement. Do not mistake this expected red check for regression in the accepted candidate.
- Mobile Experience V1 is published at `claude/mobile-experience-v1-review`, commit `564ef3430d58b34de582f5548d7fe201c4cfe04b`; it remains the single-worker control sample for the later Dev Team mobile benchmark. It was not merged or deployed.
- A read-only ECC reuse/security audit completed against pinned commit `07756cee15788a54506031462794ad645719b028`. Full ECC plugin/runtime installation is rejected; selected static methodologies and a small reimplemented destructive-command guard are preferred. The audit also proved current headless engineering Claude sessions inherit the owner's claude.ai business connector/plugin roster even though unattended connector use is presently permission-denied. Future worker hardening must remove that unnecessary tool surface and fail closed on the observed launch roster rather than relying on prompt instructions.
- **DEC-049 explicitly approves project-scoped `.claude/` files in isolated engineering workspaces for the reviewed harness experiment.** It does not approve `/root/.claude` or account-level changes, connector/MCP grant changes, production deployment, new secrets, broader privileges, business writes, external spend or destructive actions.
- The Builder rejection/repair served as Dev Team contract trial `ENV-REPRO-001`. False-success handling, exact candidate identity binding, review invalidation after candidate changes, and reviewer gating were exercised. Publication retry and integration re-verification were not falsely claimed where they did not occur. Contract gaps CG-01 through CG-05 remain open and CG-06 was added by the continuation; the in-candidate record is `docs/dev-environment/CONTRACT_TRIAL_ENV_REPRO_001.md` at `295e483`.
- Latest worker read-only runtime reconciliation proved the ratified Linux runtime above, with writes disabled. Gmail OAuth remains absent, so `/health` was degraded for that reason in the reconciliation round; new secret provisioning remains separately gated. iPhone activity has been observed on the Linux runtime, while Samsung verification remains outstanding.

## Dev-team direction

The approved direction is a quality-first engineering organisation:

- GPT Director above the engineering loop for independent decomposition/review.
- Claude Opus for architecture, security, difficult diagnosis, major refactors, integration decisions and high-scrutiny review.
- Claude Sonnet for bounded implementation where quality remains protected by evidence and review.
- Fable as a first-class Experience Director for substantial UX/interaction work, including pre-implementation direction and post-implementation experience review.
- Specialist QA, performance, security and integration workers.
- Independent reviewers rather than implementers certifying themselves.
- Parallel work only in isolated worker workspaces/branches.
- An Integrator combines successful candidates and proves the integrated result.

Cost and speed are subordinate to quality. Cheaper/faster models may handle genuinely mechanical work, but substantive product/code quality is not traded away to save usage.

[ENGINEERING_ORCHESTRATOR_V1.md](./ENGINEERING_ORCHESTRATOR_V1.md) holds the detailed V1 specification. **Owner implementation approval was explicitly granted on 2026-09-19** for Engineering Orchestrator V1 under the existing canonical specification and safety boundaries. This removes the planning→implementation approval gate but does **not** waive DEC-046's prerequisite ordering, owner-only gates, or unresolved mechanism reviews. Major implementation starts only when the existing deployment/current-product prerequisites are satisfied or canonical Git is explicitly changed by the owner.

[DEV_TEAM_V1_PILOT.md](./DEV_TEAM_V1_PILOT.md) defines proposed durable record/review/recovery contracts and the acceptance trial seeded by the reproduced Builder defects. The first manual/simulated trial has now run through the rejected-and-repaired Builder candidate; its observed contract gaps must be reconciled into the canonical planning docs rather than silently worked around. Foundation repair through the existing bridge and later Orchestrator acceptance remain separate activities.

## Infrastructure autonomy direction

Routine infrastructure maintenance should eventually require owner **approval**, not owner **terminal operation**.

Target components:

- Engineering Orchestrator,
- worker/workspace manager,
- model router,
- Privileged Action Broker,
- Deployment/Infrastructure Controller,
- versioned infrastructure releases,
- deterministic health checks,
- automatic rollback.

No component should have unrestricted authority to rewrite itself and declare itself healthy.

Termius/SSH should become break-glass recovery, not a normal workflow.

## Release doctrine

History accelerates the next version but does not constrain it.

Preserve valuable outcomes, contracts, safety invariants and lessons.

Allow obsolete implementation, UI, compatibility layers, abstractions, tests and even whole components to be superseded, retired or deleted when a better system makes them unnecessary.

A component becoming null is valid.

DESIGN.md describes the current direction; older visual directions are evidence/history, not permanent constraints.

Every substantial release should operate from a curated Active Context Pack rather than carrying all historical context forward.

## Current near-term order

1. reconcile the accepted Builder Environment into the persistent builder and canonical Dev Team trial records,
2. **Linux production migration/promotion — ratified complete at `1cf3a0f` (DEC-048),**
3. provision remaining runtime secrets through the approved process — Gmail OAuth remains outstanding and is not authorised by DEC-048,
4. **always-on server runtime — installed/enabled/running and ratified,**
5. **private tailnet-only Tailscale HTTPS — active and ratified,**
6. verify real Samsung/iPhone/runtime behaviour — iPhone observed; Samsung still outstanding,
7. perfect current UI,
8. perfect response behaviour and latency,
9. conduct real-world CROOKS sessions and collect evidence,
10. implement Engineering Orchestrator / Dev Team V1 — **owner implementation approval is granted; execute when the preceding DEC-046 prerequisite gates are satisfied**,
11. bootstrap the privileged deployment/infrastructure control plane,
12. expand World / Event Ledger / Attention / expectations / automation / integrations.

Dev Team specification planning may proceed while earlier operational work continues. Planning does not advance its implementation gate. DEC-046 records this ordering and resolves the older conflicting roadmap footer.

Do not skip safety/deployment gates merely because later architecture is more exciting.
