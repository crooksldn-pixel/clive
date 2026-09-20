# CROOKS OS — Current Truth

**Purpose:** compact active context for GPT/Claude/Fable/engineering workers  
**Status:** ACTIVE — update whenever a material product/architecture state changes  
**As of:** 2026-09-20

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

- Canonical repository: `crooksldn-pixel/clive`.
- Repository rename: `crooksldn-pixel/Shopify-theme` was renamed to `crooksldn-pixel/clive` on 2026-09-19. This is a repository identity/naming migration only; branches, commit history, safety decisions and product semantics are unchanged. **Repository rename completed operationally:** the active server checkouts (`/opt/crooks-interactive`, `/opt/crooks-ai-bridge`, `/opt/crooks-builder`, `/opt/crooks-os`) now use `https://github.com/crooksldn-pixel/clive.git`; the installed watcher default repo slug is `crooksldn-pixel/clive`, the watcher restarted healthy (`pending no`, `failures 0`, `lock free`, service active), and a read-only grep found no active old repo references outside Git history.
- Canonical product memory currently lives on `claude/product-memory-foundation`; read it by explicit ref. The default theme branch is not the CROOKS product-memory source.
- **Linux production is ratified at exact candidate `1cf3a0f3361b79f9de208d80f501543c53c244b5` (DEC-048).** Independent read-only reconciliation observed `/opt/crooks-os` clean and byte-identical to that candidate, `crooks-assistant.service` installed/enabled/active on `127.0.0.1:8000`, and tailnet-only Tailscale HTTPS. The owner explicitly ratified that already-performed state on 2026-09-19. This does not authorise another deployment, new secrets, broader privileges, public/Funnel exposure, or CROOKS writes.
- The GitHub communication bridge uses orphan branch `crooks-ai-bridge`.
- The CROOKS bridge watcher is installed and enabled. Source branch `claude/crooks-bridge-watcher-review` is published at exact commit `73f2000256db8767e2fe09c5f7f05a92f002ac2d`, pinning unattended bridge invocations to `claude-opus-5` at `high` effort while preserving the existing permission/tool flags. The source/runtime reconciliation reported `install.sh verify` = `Runtime matches source` and the watcher regression suite `126 passed, 0 failed`. A real unattended verification round consumed inbox blob `2dc4abb4ef01e992a1797bd7d772ab6a3c2e606b` and directly observed its own live `claude --print --model claude-opus-5 --effort high` process ancestry. The same round exposed two remaining engineering-control issues: the builder checkout was actually on `claude/builder-environment-repair` at accepted SHA `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` while the unit still declared `claude/bridge-builder`, and the unattended session inherited account-level business MCP connector tools beyond the six CLI `--allowed-tools`. Both are fail-closed requirements for write-capable Orchestrator workers; neither was mutated by the verification round.
- Headless Claude runs in the standalone isolated builder clone at `/opt/crooks-builder`, not the production checkout.
- **Observed workspace-management incident (2026-09-19):** the harness worker correctly created a registered isolated worktree at `/opt/crooks-builder/.worktrees/harness-hooks-experiment`, but the accepted Builder checkout did not yet ignore `.worktrees/`. The watcher therefore saw `?? .worktrees/` and correctly failed closed rather than launching another headless worker, but it retried the same deterministic precondition failure eight times. After inspecting the actual status and confirming no unfinished tracked work, the owner-side Director added `.worktrees/` only to the Builder checkout's local `.git/info/exclude`; the Builder returned clean and the watcher was restarted. This was a local bookkeeping correction, not a tracked-code change, stash/reset/clean, or weakening of the dirty-tree guard.
- **Durable lesson from that incident:** legitimate worker workspaces should not live in a place that makes the canonical Builder appear dirty. The preferred V1 shape remains worker attempts outside the canonical Builder, e.g. `/opt/crooks-workers/<task-id>/<attempt-id>/`, or an equivalently proven workspace manager. Deterministic safety/precondition failures such as dirty workspace, missing permission, missing required secret/capability, or invalid task contract should transition to `BLOCKED / ESCALATED` and notify once rather than consume repeated transient retry/backoff cycles. Backoff retries are for genuinely transient transport/provider failures. This is an observed design requirement, not yet a claim that the watcher implements the classification.
- **Harness security experiment accepted for the next gate:** branch `claude/harness-hooks-experiment`, exact candidate `2c2b0cc4a5f3d82a929eedfa053b5cc46478215f`, accepted Builder base `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`. After multiple independent adversarial rejection/repair rounds, the sixth review returned `ACCEPT FOR NEXT GATE`; the canonical acceptance record is `HARNESS_ACCEPTANCE_2C2B0CC.md`. This acceptance does not itself deploy, merge, activate production, broaden privileges, grant connector access, or authorise business writes.
- Watcher publication of the outbox is watcher-owned; the owner is no longer the normal message courier.
- **Builder Environment is independently accepted at `claude/builder-environment-repair-review`, commit `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`.** Director review verified the exact published identity and one-commit diff from `326c150`, inspected the actual repaired implementation, and checked the SHA-bound reconstruction/gate evidence. BE-01 through BE-04 are closed: manifest handling no longer crashes; doctor fails closed on wrong/failed/unverifiable tools; shell exports use safe quoting; and the declared environment was reconstructed twice from a checkout with no `.tooling/` or `.venv/`, producing an identical environment fingerprint. The exact-candidate suite reported `2834 passed, 2 skipped, 2 deselected`; `tests/test_dev_env.py` reported 22 passed; lint passed; candidate secret scans reported no findings; the review branch was read back at the exact SHA and was not merged or deployed.
- The accepted Builder candidate pins release tags/assets and enforces pre-extraction and post-install integrity checks. Four upstreams (shellcheck, fd, ast-grep, hyperfine) do not publish independent checksum files; their committed asset digests are enforced but remain explicitly advisory as first-fetch observations rather than upstream attestations.
- SkillSpector provenance is now a fail-closed PEP 610 commit check. The existing `/opt/crooks-builder` tooling was installed using the older local-path method, so its own `doctor` is expected to fail until that gitignored Builder-local tool install is reconciled to the accepted pinned git requirement. Do not mistake this expected red check for regression in the accepted candidate.
- Mobile Experience V1 is published at `claude/mobile-experience-v1-review`, commit `564ef3430d58b34de582f5548d7fe201c4cfe04b`; it remains the single-worker control sample for the later Dev Team mobile benchmark. It was not merged or deployed.
- A read-only ECC reuse/security audit completed against pinned commit `07756cee15788a54506031462794ad645719b028`. Full ECC plugin/runtime installation is rejected; selected static methodologies and a small reimplemented destructive-command guard are preferred. The audit also proved current headless engineering Claude sessions inherit the owner's claude.ai business connector/plugin roster even though unattended connector use is presently permission-denied. Future worker hardening must remove that unnecessary tool surface and fail closed on the observed launch roster rather than relying on prompt instructions.
- **DEC-049 explicitly approves project-scoped `.claude/` files in isolated engineering workspaces for the reviewed harness experiment.** It does not approve `/root/.claude` or account-level changes, connector/MCP grant changes, production deployment, new secrets, broader privileges, business writes, external spend or destructive actions.
- The Builder rejection/repair served as Dev Team contract trial `ENV-REPRO-001`. False-success handling, exact candidate identity binding, review invalidation after candidate changes, and reviewer gating were exercised. Publication retry and integration re-verification were not falsely claimed where they did not occur. Contract gaps **CG-01 through CG-06 are addressed by the 2026-09-20 Orchestrator freeze candidate** in its freeze contract/state API/traceability/acceptance matrix, but they become canonically closed only if the owner adopts that freeze by exact SHA; until adoption they remain open in canonical truth. The original trial record remains `docs/dev-environment/CONTRACT_TRIAL_ENV_REPRO_001.md` at `295e483`.
- Latest worker read-only runtime reconciliation proved the ratified Linux runtime above, with writes disabled. Gmail OAuth remains absent, so `/health` was degraded for that reason in the reconciliation round; new secret provisioning remains separately gated. iPhone activity has been observed on the Linux runtime, while Samsung verification remains outstanding.

## 2026-09-20 Orchestrator freeze candidate

A repository-only freeze candidate is being prepared on branch `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`. Its normative candidate files are `ORCHESTRATOR_V1_FREEZE_CONTRACT.md`, `ORCHESTRATOR_V1_STATE_API.md`, `ORCHESTRATOR_V1_TRACEABILITY.md` and `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md`. No implementation, deployment, privilege change or business write is authorised merely by those documents. Freeze requires independent adversarial review and an exact accepted commit SHA before implementation binds to them.

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

[ENGINEERING_ORCHESTRATOR_V1.md](./ENGINEERING_ORCHESTRATOR_V1.md) holds the original detailed V1 design. The 2026-09-20 freeze candidate adds a normative state/API contract, traceability ledger and fault-injection matrix. **Owner implementation approval was explicitly granted on 2026-09-19**, but only implementation bound to the eventual accepted freeze SHA may proceed and DEC-046 remains the active sequencing gate. The freeze candidate proposes that repository-only deterministic-kernel work may follow the freeze; that proposal is not active until the owner explicitly adopts it in DECISIONS.md. Unattended model-worker concurrency/cutover, new privileges and deployment remain separately gated.

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
3. provision remaining runtime secrets only through an approved process — Gmail OAuth remains outstanding,
4. **always-on server runtime — installed/enabled/running and ratified,**
5. **private tailnet-only Tailscale HTTPS — active and ratified,**
6. verify real Samsung/iPhone/runtime behaviour — iPhone observed; Samsung outstanding,
7. perfect current UI,
8. perfect response behaviour and latency,
9. conduct real-world CROOKS sessions and collect evidence,
10. implement Engineering Orchestrator / Dev Team V1 under the existing owner authorisation once the preceding DEC-046 gates are satisfied,
11. bootstrap the privileged deployment/infrastructure control plane separately,
12. expand World / Event Ledger / Attention / expectations / automation / integrations.

The 2026-09-20 freeze candidate proposes, but does not itself authorise, a narrower amendment allowing Phase 0 repository-only deterministic-kernel work immediately after an accepted freeze. Until the owner explicitly records that amendment in DECISIONS.md against the exact freeze SHA, the sequence above remains authoritative.

Do not skip safety/deployment gates merely because later architecture is more exciting.


- **Harness acceptance supersedes earlier intermediate candidate notes:** `2c2b0cc4a5f3d82a929eedfa053b5cc46478215f` is the accepted next-gate subject. Earlier `d7911b2`, `fe96bb6`, `ef73fbe`, and `c16d6db` records remain historical rejection/repair evidence only.
