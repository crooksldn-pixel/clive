# CLIVE — Current Truth

**Purpose:** compact active context for GPT/Claude/Fable/engineering workers  
**Status:** ACTIVE — update whenever a material product/architecture state changes  
**As of:** 2026-09-21

This file is intentionally not a historical transcript. It answers: **what is true and important now?**

For historical rationale, use Git and DECISIONS.md. For release evolution rules, use EVOLUTION_POLICY.md.

## Product

CLIVE is the intelligent persistent operational layer for the business: contextual understanding, persistent state/objectives, controlled capabilities, verified actions, proactive exception handling, and minimal owner attention.

Core product principles remain:

- maximum capability, minimum visible UI,
- human attention is scarce,
- persistent business state outside conversational memory,
- models propose; deterministic capabilities execute consequential actions,
- autonomy is narrow and earned,
- models/providers are replaceable,
- self-improvement is isolated, evidence-driven and reversible.


### North-star operational philosophy

The owner has approved CLIVE's broader product identity as a **persistent intent-to-execution operational layer**, not an AI dashboard or phrase-to-screen router.

Operational implications:
- conversation can end while objectives, commitments and relevant state remain alive;
- language is interpreted with conversation, role, current work, device, time and world state;
- the same phrase may require different investigations in different contexts, while different phrases may express the same objective;
- APIs are evidence/action capabilities beneath reasoning, not destinations the owner must manually coordinate;
- investigate for exceptions, blockers, dependencies, changes and cross-system significance rather than reproducing obvious source facts;
- dynamic UI is a role/device-appropriate projection of the evolving objective and evidence, and may correctly render almost nothing when nothing needs attention;
- staff, collaborators and devices can participate in shared objectives under scoped permissions;
- working-monologue commitments should persist and resurface when relevant, not as indiscriminate recall;
- capability gaps become controlled self-improvement evidence rather than dead ends or permission for uncontrolled self-modification;
- product quality includes operational value and human attention removed, not only correctness or test counts.

Full doctrine: [CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY.md](./CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY.md).

### CLIVE identity and home surface — 2026-09-21

The user-facing product identity is **CLIVE — Computer Language Interface Virtual Environment**.

The home surface must not visually imply that CLIVE wakes empty and waits for a command. When relevant operational state exists, home projects the highest-value current objectives, changes, commitments, exceptions and unfinished work. A sparse/empty surface is valid when nothing earns attention.

The orb is CLIVE's presence/status object rather than merely a giant microphone button. Voice is one interaction path. Useful information may displace/reposition the orb when it deserves the space. Permanent provider/service status and fixed implementation-module navigation should not define the primary surface; health is contextual to the current objective and scenes are response/objective-driven.

Startup identity direction: point of light → abstract world/intelligence orb → C/L/I/V/E acronym reveal → CLIVE wordmark.

Full direction: [CLIVE_IDENTITY_AND_HOME_SURFACE.md](./CLIVE_IDENTITY_AND_HOME_SURFACE.md).

\n### Long-horizon adaptation doctrine\n\nCLIVE must preserve its **mission and accumulated operational understanding without treating its current mechanisms as permanent**. Large organisations already exhibit distributed agency across people, software, rules, records and incentives; CLIVE's opportunity is to make more of that implicit organisational cognition explicit while reducing coordination cost and preserving human authority.\n\nThe capability frontier is permanently moving. There is no meaningful final 100% state. Models, APIs, interfaces, organisations and working patterns will change, so components should be expected to be replaced or deleted when superior mechanisms appear. Preserve durable semantics — objectives, identity, evidence/provenance, authority, time, commitments, capabilities, uncertainty, outcomes and verification — while keeping providers, frameworks, databases, orchestration, UI and connectors replaceable.\n\nCore rule: **preserve accumulated understanding; make accumulated implementation expendable.** CLIVE should be able to consume technology that would otherwise obsolete its current implementation. Adaptability remains controlled: observed limitation → candidate change → isolated experiment → adversarial evaluation → independent review → controlled adoption.\n\nMaturity principle: **no reasonable objective should leave CLIVE without a useful next move**, even when autonomous completion is impossible.\n\nFull doctrine: [CLIVE_ADAPTATION_AND_ORGANISATIONAL_INTELLIGENCE.md](./CLIVE_ADAPTATION_AND_ORGANISATIONAL_INTELLIGENCE.md).\n\n## Active Live Experience / evaluation direction — 2026-09-20

The owner has explicitly retired **user-facing Split** as the future interaction model. Preserve useful concurrency primitives internally where they still earn their place, but simultaneous work should appear as independently progressing jobs inside one CLIVE session rather than Half 1 / Half 2 / Merge / Close.

An isolated repo-only implementation stream exists at `chatgpt/clive-live-experience-v0-5`; initial contract `4469e0b9c4450cd1f7244b028a5684394a0a0b6f`, current observed implementation head at this reconciliation `f9bdc7682939448d77f10aeaf4048ca62eb370fb`. It is intentionally separate from the Orchestrator freeze and is not production authority.

Immediate product direction:
- one perceptible lifecycle: `IDLE → LISTENING → HEARING → UNDERSTOOD → THINKING → WORKING → RESPONDING → IDLE`, with explicit interruption/error/recovery;
- test the physical voice path, not only post-transcription `POST /turn`; existing experience evidence explicitly did not call `/speak`;
- progressive results: useful completed work renders while slower sibling jobs continue;
- liquid-glass/dark CROOKS direction, with less dead space and less permanent plumbing/status chrome;
- connection health is contextual and truthful;
- scene composition evolves toward typed safe primitives selected for objective/evidence/device rather than one hard-coded screen per workflow;
- every real session becomes privacy-minimised evaluation evidence;
- quality evaluation is multidimensional and independently reviewed, not naive same-model self-scoring;
- important gates are tested adversarially, including mutation of the tests themselves, hidden/scenario-mutated/device/long-session evaluation and blind baseline/candidate comparison where useful;
- evaluator drift/gaming is controlled through versioning, hidden sets, human calibration, disagreement retention and frozen replay.

Full doctrine and research/observed findings: [CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md](./CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md).

This direction does not waive DEC-046/047, exact-SHA Orchestrator adoption, runtime/credential/connector/deployment/privilege gates, or action-safety invariants.

### Control-plane throughput lesson — 2026-09-21

Dual-stream operation proved that the current Git bridge/hourly-controller combination is safe but throughput-limited: the single inbox behaves as a shared lane, repeated repair/review cycles can starve another stream, and completion can sit idle until the next supervisory tick. Preserve the precision; remove the coordination waste.

Approved direction: persistent tmux-backed Termius workers, one task/worktree/session/candidate, machine-readable queued tasks/results, event-driven continuation, scheduler-enforced reviewer independence, generated volatile ACTIVE_STATE, explicit blocker classes and starvation prevention. The hourly GPT controller becomes reconciliation/supervision rather than the normal continuation clock.

Critical contract semantics should migrate toward structured data or a constrained grammar rather than indefinitely expanding regex interpretation of unrestricted prose.

Plan: [ENGINEERING_CONTROL_PLANE_VNEXT.md](./ENGINEERING_CONTROL_PLANE_VNEXT.md).

**Freeze-loop status — 2026-09-21:** the unrestricted-English prose-freeze repair/review loop is parked. Its state-machine, identity, stale-result and review lessons remain evidence, but the 5k-line natural-language parser is no longer the active route to the Orchestrator. Do not dispatch further M-series/parser rounds unless the owner explicitly reopens that experiment. The active engineering path is the typed control-plane implementation plus CLIVE Live Experience V0.5.

Exact control-plane Phase 1 candidate `8588776455a1832da763810064cacb47d7192ef4` received an independent `REJECT — REPAIR REQUIRED` for R-01..R-06, with R-07/R-08 advisory. A successor repair branch is expected to address lint, filesystem/path traversal, controller-owned owner/obsolete gates, genuine CAS/starvation mutation coverage, changed-path/result-SHA binding and the simulation-only worker-identity limitation before a fresh exact-SHA review.

## Engineering control plane

- Canonical repository: `crooksldn-pixel/clive`.
- Repository rename: `crooksldn-pixel/Shopify-theme` was renamed to `crooksldn-pixel/clive` on 2026-09-19. This is a repository identity/naming migration only; branches, commit history, safety decisions and product semantics are unchanged. **Repository rename completed operationally:** the active server checkouts (`/opt/crooks-interactive`, `/opt/crooks-ai-bridge`, `/opt/crooks-builder`, `/opt/crooks-os`) now use `https://github.com/crooksldn-pixel/clive.git`; the installed watcher default repo slug is `crooksldn-pixel/clive`, the watcher restarted healthy (`pending no`, `failures 0`, `lock free`, service active), and a read-only grep found no active old repo references outside Git history.
- Canonical product memory currently lives on `claude/product-memory-foundation`; read it by explicit ref. The default theme branch is not the CROOKS product-memory source.
- **Linux production is ratified at exact candidate `1cf3a0f3361b79f9de208d80f501543c53c244b5` (DEC-048).** Independent read-only reconciliation observed `/opt/crooks-os` clean and byte-identical to that candidate, `crooks-assistant.service` installed/enabled/active on `127.0.0.1:8000`, and tailnet-only Tailscale HTTPS. The owner explicitly ratified that already-performed state on 2026-09-19. This does not authorise another deployment, new secrets, broader privileges, public/Funnel exposure, or CROOKS writes.
- The GitHub communication bridge uses orphan branch `crooks-ai-bridge`.
- The CROOKS bridge watcher is installed and enabled. Its runtime is now explicitly pinned to `claude-fable-5-1` at `high` effort from reviewed source revision `5ada7b47f13547f107be1f53beeb79021cc48c24`; the corrected installer upgrade-order regression suite passed `126 passed, 0 failed`. A real unattended post-install smoke round consumed inbox blob `5d659fbc9418f378a10ddc5666e79ffc5b94ae7c`, published a new outbox, made no application/infrastructure/production changes, and returned the watcher to `pending no`, `failures 0`, `lock free`. The single-worker bridge therefore has a verified deterministic Claude model/effort baseline; future Engineering Orchestrator routing remains task-specific rather than permanently fixed to this one model.
- Headless Claude runs in the standalone isolated builder clone at `/opt/crooks-builder`, not the production checkout.
- **Observed workspace-management incident (2026-09-19):** the harness worker correctly created a registered isolated worktree at `/opt/crooks-builder/.worktrees/harness-hooks-experiment`, but the accepted Builder checkout did not yet ignore `.worktrees/`. The watcher therefore saw `?? .worktrees/` and correctly failed closed rather than launching another headless worker, but it retried the same deterministic precondition failure eight times. After inspecting the actual status and confirming no unfinished tracked work, the owner-side Director added `.worktrees/` only to the Builder checkout's local `.git/info/exclude`; the Builder returned clean and the watcher was restarted. This was a local bookkeeping correction, not a tracked-code change, stash/reset/clean, or weakening of the dirty-tree guard.
- **Durable lesson from that incident:** legitimate worker workspaces should not live in a place that makes the canonical Builder appear dirty. The preferred V1 shape remains worker attempts outside the canonical Builder, e.g. `/opt/crooks-workers/<task-id>/<attempt-id>/`, or an equivalently proven workspace manager. Deterministic safety/precondition failures such as dirty workspace, missing permission, missing required secret/capability, or invalid task contract should transition to `BLOCKED / ESCALATED` and notify once rather than consume repeated transient retry/backoff cycles. Backoff retries are for genuinely transient transport/provider failures. This is an observed design requirement, not yet a claim that the watcher implements the classification.
- **Harness candidate review completed:** branch `claude/harness-hooks-experiment`, candidate `dd50ebbca6eca9c4e2ee1e85ad17d2c7e5afd25e` from accepted Builder base `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` received `REJECT — REPAIR REQUIRED` in the independent adversarial review of inbox `2b1030bd48ee14888e0c85b7d160fa39b2cba6eb`. The review reproduced the implementer evidence but found high-severity guard bypasses (production credential reads, bare production `git stash`, command-word laundering, and shell-fed text bypasses) plus bounded medium/low defects in Git/environment parsing, gitleaks invocation coverage/timeouts, roster evidence and workspace bookkeeping. No production/global/account/connector/secret/service/Tailscale/business mutation occurred during review. The harness remains inactive; project `.claude/` files are still unapplied.
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


- **Harness repair candidate published:** `claude/harness-hooks-experiment` now points to exact candidate `d7911b24979be2306749b7333ec60edc28cba857`, one commit on top of rejected `dd50ebbca6eca9c4e2ee1e85ad17d2c7e5afd25e`. Implementer evidence reports 181 new repair tests passing, targeted 568 passed/2 skipped, full offline 3374 passed/10 skipped, Ruff clean, range gitleaks 0, clean worktree, and no production/account/connector/service mutation. This is **not accepted**: it now requires a fresh independent adversarial review bound to `d7911b2…`. A stale Builder fetch refspec for deleted `claude/bridge-builder` still makes `git fetch --all` fail; the implementer worked around it with explicit branch fetches. Do not treat that local refspec problem as fixed.
