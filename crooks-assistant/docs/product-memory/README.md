# CLIVE Product Memory

This directory is the canonical durable product memory for CLIVE. Historical documents may still use the earlier CROOKS OS name where that context matters.

Current repository: `crooksldn-pixel/clive`. Since the consolidation of 2026-09-25 the canonical copy is this directory on `clive/trunk` (`crooks-assistant/docs/product-memory`); it is not assumed to exist on the repository's default theme branch. Earlier product-memory branches (`claude/product-memory-foundation`, the 2026-09-21 base; `chatgpt/product-memory-reconcile-2026-09-23`; `claude/product-memory-truth-2026-09-23`; the Opus 5.5 handoff branch) are history.

The `_incoming/` directory holds byte-identical staging copies of the truth and handoff branches, used for the consolidation and left for the Director to remove. It is not canonical and is not indexed; everything in it is represented in the files below.

The rule is simple:

> If an idea, product principle, architecture decision, roadmap item, or self-improvement concept matters to CLIVE, it must not live only in an AI conversation.

ChatGPT, Claude, future model workers, and human contributors should treat these documents as the durable source of truth for product intent.

## Files

- [PRODUCT_BRAIN.md](./PRODUCT_BRAIN.md) — enduring vision, product principles, architecture philosophy, and non-negotiables.
- [ROADMAP.md](./ROADMAP.md) — ordered Now / Next / Later / Someday implementation roadmap.
- [IDEAS.md](./IDEAS.md) — captured ideas that are not yet necessarily approved for implementation.
- [FEATURES.md](./FEATURES.md) — feature register with state and ownership.
- [DECISIONS.md](./DECISIONS.md) — important decisions and the reasoning behind them.
- [SELF_IMPROVEMENT.md](./SELF_IMPROVEMENT.md) — controlled self-improvement, multi-agent development hierarchy, reviewers, replay, and deployment gates.
- [CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md](./CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md) — active 2026-09-20 direction for the continuous voice/work loop, retirement of Split, simultaneous jobs, liquid-glass UI, scene compilation, per-session evaluation, adversarial/mutation/device testing, and evaluation-drift controls.
- [CLIVE_IDENTITY_AND_HOME_SURFACE.md](./CLIVE_IDENTITY_AND_HOME_SURFACE.md) — active 2026-09-21 identity/home doctrine: CLIVE branding and acronym, persistent-world-state home surface, orb-as-presence, contextual health, response-driven scenes and startup identity.
- [ENGINEERING_CONTROL_PLANE_VNEXT.md](./ENGINEERING_CONTROL_PLANE_VNEXT.md) — active control-plane upgrade plan: persistent Termius/tmux workers, queued task/result records, event-driven continuation, reviewer independence, active-state generation and starvation prevention.
- [CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY.md](./CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY.md) — owner-approved north-star doctrine: CLIVE as a persistent operational layer from intention to execution, with contextual investigation, world state, persistent objectives, people/workspaces, relevant memory, capability-gap learning and operational-value evaluation.
- [CLIVE_ADAPTATION_AND_ORGANISATIONAL_INTELLIGENCE.md](./CLIVE_ADAPTATION_AND_ORGANISATIONAL_INTELLIGENCE.md) — owner-approved long-horizon doctrine: distributed organisational intelligence, coordination cost, a moving capability frontier, stable semantic purpose with replaceable mechanisms, and future-disposable architecture.
- [CURRENT_TRUTH.md](./CURRENT_TRUTH.md) — compact active state; the first context file future directors/workers should read.
- [EVOLUTION_POLICY.md](./EVOLUTION_POLICY.md) — release doctrine: preserve value and lessons without fossilising obsolete implementation or design.
- [DIRECTOR_PROTOCOL.md](./DIRECTOR_PROTOCOL.md) — named memory/continuity procedures for bootstrap, release context, supersession, pruning, handoff, and audits.
- [MIGRATION_HANDOFF.md](./MIGRATION_HANDOFF.md) — SUPERSEDED: the 2026-09-19 GPT-conversation migration handoff (active state, in-flight work, control-plane status and continuation instructions as of then), kept as history.
- [RECONCILIATION_2026-09-23.md](./RECONCILIATION_2026-09-23.md) — the 2026-09-23 reconciliation checkpoint: the precedent rule (precedent may be explicitly superseded or retired when its durable responsibility is preserved), CLIVE as one product, engineering-kernel progress, direct objective ingress, model/role replaceability, commercial validation and the NEEDED ≠ AUTHORISED ≠ STARTED ≠ COMPLETED ≠ VERIFIED invariant; its engineering state is history.
- [OWNER_DECISION_PACKET_2026-09-21.md](./OWNER_DECISION_PACKET_2026-09-21.md) — the owner-only choices kept explicit while repository-only engineering continued unattended (2026-09-21); Gate C decided 2026-09-24, Gate A overtaken by the remote loop, Gate B open.
- [OPUS_5_5_HANDOFF_2026-09-24.md](./OPUS_5_5_HANDOFF_2026-09-24.md) — SUPERSEDED: the 2026-09-24 engineering handoff to a fresh Opus 5.5 session (branches, SHAs, safety invariants, activation state, next steps), kept as history.
- [OPUS_5_5_START_PROMPT_2026-09-24.md](./OPUS_5_5_START_PROMPT_2026-09-24.md) — SUPERSEDED: the 2026-09-24 startup prompt for that Opus 5.5 session, kept as history.

- [ENGINEERING_ORCHESTRATOR_V1.md](./ENGINEERING_ORCHESTRATOR_V1.md) — proposed Dev Team V1 contract: authority, lifecycle, context, isolation, evidence, review, integration and recovery; planning only.

- [DEV_TEAM_V1_PILOT.md](./DEV_TEAM_V1_PILOT.md) — proposed task/review/recovery records and first end-to-end acceptance trial; no dispatch approval.
- [BUILDER_ENVIRONMENT_REVIEW.md](./BUILDER_ENVIRONMENT_REVIEW.md) — independent review of candidate 9a27bc4 with reproduced defects and current bridge status.
- [ENGINEERING_STACK_REUSE_PLAN.md](./ENGINEERING_STACK_REUSE_PLAN.md) — research/proposed plan for reusing mature public agent infrastructure while owning CROOKS-specific policy and evidence semantics; no approval to install, spend or widen privileges.
- [HARNESS_ACCEPTANCE_2C2B0CC.md](./HARNESS_ACCEPTANCE_2C2B0CC.md) — the sixth independent adversarial review's ACCEPT FOR NEXT GATE verdict on harness candidate 2c2b0cc, with the limits it recorded.
- [REVIEW_ACCEPTANCE_CONTRACT.md](./REVIEW_ACCEPTANCE_CONTRACT.md) — repository-only contract binding final engineering acceptance to an exact candidate SHA and an operationally independent reviewer, with the fencing rules for stale and late verdicts.
- [JUDGMENT_LEDGER_CONTRACT.md](./JUDGMENT_LEDGER_CONTRACT.md) — OwnerDecision as a decision record separate from ActionStatus, and the append-only, redacted Judgment Ledger with its fail-closed invariants.
- [SUPPORT_INVESTIGATOR_V1.md](./SUPPORT_INVESTIGATOR_V1.md) — the read-only Customer Support Investigator V1: one enquiry about an existing order, identification only where the evidence supports it, verified facts kept apart from inference and the unknown, every piece of evidence exposed, and a reply draft that requires the owner's approval; nothing external happens.
- [MOBILE_ALPHA.md](./MOBILE_ALPHA.md) — the private, read-only phone alpha: conversation first, the objectives CLIVE is keeping alive (Objective V0, with proposed, authorised, started, completed and verified kept distinct and authorisation the owner's alone) and the Support Investigator on the phone.
- [ENGINEERING_LIFECYCLE_PRODUCERS.md](./ENGINEERING_LIFECYCLE_PRODUCERS.md) — the write side of the control plane: attempts with leases and fencing tokens, an append-only journal, review dispatch, verdict admission, acceptance and verified integration, so stages are recorded rather than inferred; repository-only.
- [ENGINEERING_DISPATCHER_V1.md](./ENGINEERING_DISPATCHER_V1.md) — Objective Intake + Engineering Dispatcher V1 around the frozen kernel: one owner objective in, an isolated restricted builder, Git-derived candidate, exact-SHA independent review with a typed result, bounded repair, verified integration; COMPLETE, BLOCKED or OWNER_GATE; repository-only, and not by itself the no-courier milestone.
- [REMOTE_ENGINEERING_CONTROL_V1.md](./REMOTE_ENGINEERING_CONTROL_V1.md) — repository-only bounded GitHub transport/control adapter for submitting and observing engineering objectives without making GitHub lifecycle authority; deployment remains separately owner-authorised.
- [GENERATIVE_UI_V1.md](./GENERATIVE_UI_V1.md) — owner-approved generative interface: connectors describe data, CLIVE decides what to show, the screen shows findings not sources; evidence-bound scene primitives, attention budget, user-facing settings and the capability-gap bridge.
- [OWNER_DECISIONS_2026-09-24.md](./OWNER_DECISIONS_2026-09-24.md) — judgment-evidence retention, Gmail runtime credential, operational-alpha promotion authority, Generative UI V1 approval, the one-trunk finish rule and the retirements.
- [PROJECT_AUDIT_2026-09-24.md](./PROJECT_AUDIT_2026-09-24.md) — whole-project finish list: why accepted work never reached the product, what is live, finished-but-unlanded work, stopped streams, agreed-but-unbuilt items, stale records and the finish order.
- [SOURCE_ASSIMILATION_V1.md](./SOURCE_ASSIMILATION_V1.md) — how CLIVE learns from external repositories, skills and tools: quarantine, inventory, compare, decide the use, prove or drop; authority lines and the constraints found.
- [SOURCE_SHELF.md](./SOURCE_SHELF.md) — the owner-supplied candidate sources (Taste Skill, Vercel guidelines, Playwright CLI, Agent Browser, Jev, LangWatch and others), triaged into batches.
- [OWNER_DECISIONS_2026-09-25.md](./OWNER_DECISIONS_2026-09-25.md) — synthetic test credentials by runtime assembly, the approved loop update (builder checks, green-CI gate, protected safety core and loop code), engineering off the production host, and the Mac's role.
- [OWNER_DECISIONS_2026-09-26.md](./OWNER_DECISIONS_2026-09-26.md) — GPT reviewer cost: the loop's routine reviews on `gpt-6-luna` at medium effort, the production deploy review on `gpt-6-sol`; the loop-update follow-ups (manual kernel CLI gated, the tests of protected code protected).
- [OWNER_DECISIONS_2026-09-28.md](./OWNER_DECISIONS_2026-09-28.md) — the fast lane and the speech term base removed (every sentence a model turn, nothing biasing or rewriting what was heard; why "Clive" was heard as "Plaid"), the app's accent in iOS blue, and a remote mode for the TV screens.
- [OWNER_DECISIONS_2026-09-30.md](./OWNER_DECISIONS_2026-09-30.md) — the ship rule made regression-only with one exception (anything shown to leak customer data, or to write or send what the owner did not confirm, blocks whether new or old), acceptance on a self-hosted runner on clive-worker-01, the owner's curated skill list as his decision, and builders on one Max plan for now.
- [CLIVE_SELF_KNOWLEDGE.md](./CLIVE_SELF_KNOWLEDGE.md) — owner doctrine: CLIVE as a machine insisting upon itself, product memory as the way future models and CLIVE itself understand its direction and why it came to be; provenance of intent and honest history.
- [NEXT_PHASE_2026-09-25.md](./NEXT_PHASE_2026-09-25.md) — the finish-first rule, the approved next phase (eyes, taste, the absorbing machine, the shelf) and every direction and idea captured on 2026-09-24 and 2026-09-25.
- [INFRASTRUCTURE_2026-09-25.md](./INFRASTRUCTURE_2026-09-25.md) — the production host, clive-worker-01 and the Mac: roles, open hardware items and setup lessons.
- [EXTERNAL_REVIEW_2026-09-25.md](./EXTERNAL_REVIEW_2026-09-25.md) — the owner-provided external review of 2026-09-25, kept verbatim: red trunk, landing before verification, unprotected safety core, loop confinement, direction carried forward.
- [RECONCILIATION_2026-09-25.md](./RECONCILIATION_2026-09-25.md) — evening reconciliation of the trunk, all 48 loop objectives, all 110 branches (knowledge found only on unmerged branches, proposed clean-up) and what waits on the owner.
- [DRIFT_REVIEW_2026-09-26.md](./DRIFT_REVIEW_2026-09-26.md) — the build measured against the philosophy: what converges, the eight drifts (machinery ahead of the owner's attention, roadmap out of order, three approval systems, stale device model, no way to consume new technology) and the corrections.
- [KNOWLEDGE_DIGESTER_V1.md](./KNOWLEDGE_DIGESTER_V1.md) — how CLIVE digests any artifact (repositories, skills, documents, API specifications, data, websites, themes, media, applications, itself) into provenance-tagged, reversible units, relates them to its self-model, and proves or drops what it absorbs.
- [DIGESTIONS_2026-09-26.md](./DIGESTIONS_2026-09-26.md) — the digester's first real digestions (Vercel's interface guidelines, anthropics/skills, Playwright CLI, Taste Skill, CLIVE itself): what each is, what came out, what CLIVE should absorb, the defects found and fixed, and what the digester is and is not good at yet.
- [PLAN_2026-09-26.md](./PLAN_2026-09-26.md) — the day's plan: the deploy and owner steps, digester waves, loop update part 2, and how the day is judged.

## Status model

Use these states consistently:

- **CAPTURED** — worth preserving; not yet committed.
- **APPROVED** — owner has explicitly agreed with the direction.
- **PLANNED** — accepted into the roadmap with an intended phase.
- **BUILDING** — actively being implemented.
- **TESTING** — implementation exists and is under validation.
- **SHIPPED** — in the production system and verified.
- **DEFERRED** — intentionally not being worked on now.
- **REJECTED** — considered and intentionally not proceeding.
- **SUPERSEDED** — replaced by a newer active decision/direction; retained only as historical rationale.
- **RETIRED** — previously active capability/component intentionally removed after its responsibility became unnecessary or moved elsewhere.

## Capture rule

When the owner raises a potentially meaningful CROOKS idea:

1. Capture it in `IDEAS.md` with an ID, date, context, and status.
2. Do **not** silently convert brainstorming into implementation.
3. If the owner explicitly approves it, promote it to `FEATURES.md` and/or `ROADMAP.md`.
4. If implementation changes product behaviour or architecture, record the decision in `DECISIONS.md`.
5. If an old idea is superseded, keep the history and mark it superseded rather than deleting context.

## Agent startup rule

Before making meaningful CROOKS changes, an engineering agent should read:

1. `CURRENT_TRUTH.md`
2. `PRODUCT_BRAIN.md`
3. `EVOLUTION_POLICY.md`
4. relevant **active** entries in `DECISIONS.md`
5. the assigned feature/issue
6. `SELF_IMPROVEMENT.md` when the task touches agent autonomy, deployment, testing, or self-modification
7. `DIRECTOR_PROTOCOL.md` when assembling release context, superseding prior work, or handing off to another agent

Do not inject the entire project history into every task. Historical context should be pulled only when it explains an active constraint, migration obligation, regression, or previously failed approach.

An agent must not reverse a recorded **active** product or safety decision silently. It must escalate the disagreement.

Equally, an agent must not treat a superseded implementation, UI direction, temporary workaround, or old test as a permanent requirement merely because it exists in history.

## Maintenance

This product memory should be reviewed periodically to:

- merge duplicates,
- mark shipped/deferred/rejected items,
- update sequencing,
- preserve rationale,
- remove stale implementation detail while retaining decisions.

The goal is durable product intent, not an ever-growing transcript dump.

Git is the historical archive. `CURRENT_TRUTH.md` is the compact working memory. Old context should accelerate future work by preventing repeated mistakes, never constrain a better release solely because “that is how the previous version worked.”
