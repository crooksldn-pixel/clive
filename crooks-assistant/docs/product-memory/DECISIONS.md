# CROOKS OS — Decision Log

**Purpose:** preserve important product/architecture decisions and the reasoning behind them so future agents do not silently reverse them.

---

## DEC-001 — CROOKS is an operating layer, not a chatbot
**Date:** 2026-09-19  
**Status:** ACTIVE

CROOKS should be designed around persistent business state, capabilities, automation, anticipation, and verified actions.

Chat is one interface, not the product definition.

**Reason:** a generic conversational wrapper is not sufficiently differentiated or operationally valuable.

---

## DEC-002 — Maximum capability, minimum visible UI
**Date:** 2026-09-19  
**Status:** ACTIVE

Hide complexity whenever possible.

Prefer one useful card/action over large dashboards or multiple controls.

**Reason:** subscriber usability is a core differentiator.

---

## DEC-003 — Human attention is the scarce resource
**Date:** 2026-09-19  
**Status:** ACTIVE

CROOKS should suppress routine normality and surface exceptions.

**Reason:** the product should reduce owner attention cost, not simply centralise more information.

---

## DEC-004 — Durable business state lives outside the model
**Date:** 2026-09-19  
**Status:** ACTIVE

Critical state, events, decisions, expectations, and actions must not depend on conversational memory.

**Reason:** model context is transient and unreliable as a system of record.

---

## DEC-005 — Models propose; deterministic server capabilities execute
**Date:** 2026-09-19  
**Status:** ACTIVE / SAFETY-CRITICAL

Consequential actions use the proposal/action/verification model.

Preserve:
- immutable server-side action identity/arguments,
- explicit authorisation where required,
- precondition reread,
- deterministic execution,
- authoritative verification.

**Reason:** model narration is not proof of execution.

---

## DEC-006 — Voice “yes” is not sufficient for sensitive authorisation
**Date:** 2026-09-19  
**Status:** ACTIVE / SAFETY-CRITICAL

Sensitive writes require the appropriate bound approval mechanism.

---

## DEC-007 — Unknown writes fail closed
**Date:** 2026-09-19  
**Status:** ACTIVE / SAFETY-CRITICAL

Do not allow models to improvise arbitrary write operations outside known capability families.

---

## DEC-008 — Autonomy is narrow and earned
**Date:** 2026-09-19  
**Status:** ACTIVE

No blanket “full autonomy.”

Autonomy should be granted per action class based on repeated approval history, risk, reversibility, and verification.

---

## DEC-009 — Event-driven architecture is preferred where available
**Date:** 2026-09-19  
**Status:** ACTIVE

Use real events/webhooks when practical; use schedules for deadlines/reconciliation and systems without useful events.

---

## DEC-010 — Models are replaceable
**Date:** 2026-09-19  
**Status:** ACTIVE

The long-term architecture requires a Model Gateway.

Claude may be primary, but model/provider identity must not become the durable business architecture.

---

## DEC-011 — Self-improvement uses isolated candidate development
**Date:** 2026-09-19  
**Status:** ACTIVE

Production does not freely rewrite itself.

Required direction:
observe → diagnose → reproduce → isolated branch/worktree → tests → replay → independent review → candidate → controlled deployment → monitoring/rollback.

---

## DEC-012 — Every autonomous worker gets its own worktree
**Date:** 2026-09-19  
**Status:** ACTIVE

Parallel agents must not share one mutable working tree.

**Reason:** the Linux migration exposed a real duplicate-Claude collision where two agents edited the same checkout.

---

## DEC-013 — Implementers do not solely review themselves
**Date:** 2026-09-19  
**Status:** ACTIVE

Every specialist layer should eventually have an independent reviewer/critic.

Reviewer objective is adversarial verification, not agreement.

---

## DEC-014 — GPT should eventually act as independent director/reviewer above Claude workers
**Date:** 2026-09-19  
**Status:** DIRECTION APPROVED

The GPT layer should inspect actual diffs/tests/evidence and challenge Claude manager/worker assumptions.

The owner remains above both for genuine product decisions.

---

## DEC-015 — Owner should not be a message courier
**Date:** 2026-09-19  
**Status:** ACTIVE

Bridge/watcher/orchestrator work should progressively remove the need for the owner to manually copy messages between ChatGPT and Claude.

---

## DEC-016 — GitHub is canonical product memory
**Date:** 2026-09-19  
**Status:** ACTIVE

Important product ideas, decisions, and roadmaps must be versioned and durable.

AI memory is not the system of record.

---

## DEC-017 — Brainstorming does not equal implementation approval
**Date:** 2026-09-19  
**Status:** ACTIVE

Ideas are captured first.

Only explicit owner approval promotes them into committed roadmap/feature work.

---

## DEC-018 — Current product quality comes before major V2 expansion
**Date:** 2026-09-19  
**Status:** ACTIVE

Before building the full World/automation/self-improvement system, finish:
- always-on deployment,
- UI,
- response quality,
- reliability,
- device experience,
- error cleanup.

**Reason:** self-improvement should operate on a solid baseline rather than compensate for an unfinished product.

---

## DEC-019 — Server becomes canonical always-on runtime
**Date:** 2026-09-19  
**Status:** ACTIVE

CROOKS runtime should not depend on the Mac being awake.

Mac becomes optional control/development/rollback device.

---

## DEC-020 — Private-first networking
**Date:** 2026-09-19  
**Status:** ACTIVE

FastAPI should bind loopback by default and be accessed through private Tailscale HTTPS.

Avoid unnecessary public endpoints.

---

## DEC-021 — Temporary root execution is acceptable for initial Linux migration
**Date:** 2026-09-19  
**Status:** TEMPORARY

Root is temporarily approved because Claude Max auth currently lives under `/root/.claude`.

Later hardening should migrate CROOKS to a dedicated service account.

---

## DEC-022 — Whisper is intentionally disabled on the Linux production server initially
**Date:** 2026-09-19  
**Status:** ACTIVE FOR CURRENT DEPLOYMENT

ElevenLabs Scribe remains primary STT.

Do not reproduce the Mac M4 whisper.cpp/Core ML setup on the Hetzner CPU VM initially.

Health must distinguish intentional disablement from failure.

---

## DEC-023 — Disabled optional subsystem must not falsely degrade top-level health
**Date:** 2026-09-19  
**Status:** ACTIVE

If local Whisper is explicitly disabled:
- mark it disabled/not in use,
- do not run Mac/Core ML checks,
- do not degrade top-level health solely because it is absent.

Speech health must still fail if no usable STT remains.

---

## DEC-024 — Static and mutable secrets require different Linux storage
**Date:** 2026-09-19  
**Status:** ACTIVE

Do not use systemd `LoadCredential` as a universal secret backend.

Static secrets may use encrypted systemd credentials.

Mutable credentials require secure writable persistence.

---

## DEC-025 — Gmail token should live outside the Git checkout on Linux
**Date:** 2026-09-19  
**Status:** ACTIVE

Preferred Linux production location:
`/etc/crooks-os/secrets/gmail_token`

Requirements:
- root-only,
- 0600,
- writable for OAuth refresh,
- outside Git.

Existing `token.json` may remain fallback/compatibility.

---

## DEC-026 — media_signing_key is a recognised persistent secret on both platforms
**Date:** 2026-09-19  
**Status:** ACTIVE

Accept:
- new Mac Keychain entry,
- one initial cache invalidation.

**Reason:** the previous unrecognised key silently regenerated each boot and invalidated media URLs.

---

## DEC-027 — Writes remain disabled during migration/verification
**Date:** 2026-09-19  
**Status:** ACTIVE UNTIL EXPLICIT CHANGE

`CROOKS_WRITES_ENABLED=false` and `CROOKS_WRITES_LOCAL_OWNER=false` remain the migration baseline.

Enabling writes is a separate explicit decision.

---

## DEC-028 — GitHub bridge uses a separate branch
**Date:** 2026-09-19  
**Status:** ACTIVE

`crooks-ai-bridge` carries communication only.

It must not be merged into production code.

---

## DEC-029 — Bridge watcher should trigger on inbox blob SHA, not branch HEAD
**Date:** 2026-09-19  
**Status:** ACTIVE

Claude updating its outbox must not retrigger itself.

---

## DEC-030 — Bridge watcher must fail closed around shared/dirty worktrees
**Date:** 2026-09-19  
**Status:** ACTIVE

Before launching a headless Claude worker:
- acquire lock,
- confirm expected worktree state,
- ensure no unrelated Claude process is editing the same target,
- prefer dedicated builder worktree.

---

## DEC-031 — Subscriber product must hide internal engineering complexity
**Date:** 2026-09-19  
**Status:** ACTIVE

Subscribers should not need to understand:
- prompts,
- agents,
- MCPs,
- systemd,
- model routing,
- OAuth internals,
- Tailscale.

---

## DEC-032 — Commercial differentiation is operating leverage, not model cleverness
**Date:** 2026-09-19  
**Status:** ACTIVE

The key metric is:

> How much owner attention can CROOKS remove without reducing control or trust?

---

## DEC-033 — Ecommerce domain knowledge should be opinionated
**Date:** 2026-09-19  
**Status:** ACTIVE

Future subscriber CROOKS should natively understand:
- orders,
- fulfilment,
- returns,
- chargebacks,
- stock,
- suppliers,
- production,
- campaigns,
- support,
- payments/cash.

This is part of differentiation from generic chat.

---

## DEC-034 — Self-improvement may learn from behaviour, not just explicit preference text
**Date:** 2026-09-19  
**Status:** ACTIVE DIRECTION

Use signals such as:
- corrections,
- repeated questions,
- interruptions,
- abandoned screens,
- action usage,
- latency.

Do not infer major product decisions from weak signals without review.

---

## DEC-035 — High-risk self-modification areas stay approval-gated
**Date:** 2026-09-19  
**Status:** ACTIVE

Do not auto-deploy changes touching:
- authentication,
- secrets,
- permissions,
- refunds,
- Shopify write semantics,
- action authorisation,
- safety invariants,
- destructive migrations.

---

## DEC-036 — Product memory should be cleaned periodically, not allowed to become a transcript dump
**Date:** 2026-09-19  
**Status:** ACTIVE

Maintain:
- concise rationale,
- status,
- supersession history,
- deduplication.

---

## DEC-037 — Previous releases accelerate; they do not constrain future releases
**Date:** 2026-09-19  
**Status:** ACTIVE

Preserve current product intent, safety contracts, useful capabilities, validated evidence and lessons.

Do not preserve obsolete implementation shape merely because it existed before.

**Reason:** historical context should prevent repeated mistakes without turning CROOKS into an accumulation of legacy constraints.

---

## DEC-038 — Preserve outcomes, not mechanisms; deletion is a valid improvement
**Date:** 2026-09-19  
**Status:** ACTIVE

If a new system fully subsumes an old component, abstraction, UI surface, compatibility path or agent role, the old element may be retired/deleted.

A component becoming effectively null is valid when it has no remaining unique responsibility.

**Reason:** avoiding deletion creates zombie architecture and forces future releases to accommodate obsolete structures.

---

## DEC-039 — Major releases use curated active context, not full historical context
**Date:** 2026-09-19  
**Status:** ACTIVE

Future agents should start from `CURRENT_TRUTH.md`, active decisions, current product/design doctrine and relevant evidence.

Superseded/history is retrieved only when relevant to migration, regression, rationale or a known failure.

**Reason:** unlimited context accumulation causes old assumptions to masquerade as current requirements.

---

## DEC-040 — Engineering quality outranks model cost and speed
**Date:** 2026-09-19  
**Status:** ACTIVE

Do not trade substantive code/product quality for lower model usage or shorter elapsed time.

Use cheaper/faster models only where the work is genuinely mechanical and quality is not affected.

**Reason:** the engineering system exists to improve CROOKS, not optimise token cost at the expense of the product.

---

## DEC-041 — Model routing is quality-first and supports automatic escalation
**Date:** 2026-09-19  
**Status:** APPROVED DIRECTION

Use the strongest appropriate model/effort for the task.

Direction:
- Opus for architecture, security, difficult diagnosis, major refactors, integration decisions and high-scrutiny review,
- Sonnet for bounded implementation with objective proof and independent review,
- weaker/faster models only for genuinely mechanical work,
- automatic escalation when uncertainty, repeated failure, novelty or risk increases.

**Reason:** routing should remove wasted computation without reducing engineering quality.

---

## DEC-042 — Fable is a first-class Experience Director
**Date:** 2026-09-19  
**Status:** APPROVED DIRECTION

For substantial UX/interaction work, Fable should participate as a specialist in:
- experience/interaction direction before implementation,
- physical-device behaviour and workflow quality,
- post-implementation independent experience review.

Fable complements rather than replaces DESIGN.md, Claude implementation, browser evidence, accessibility checks or technical review.

**Reason:** product experience should have an independent specialist voice rather than being reduced to CSS implementation or generic design linting.

---

## DEC-043 — Parallel engineering requires isolated workers and an integration gate
**Date:** 2026-09-19  
**Status:** ACTIVE

Parallel tasks may run only when workers have independent mutable workspaces/branches and genuinely separable scope.

The Integrator is responsible for combining candidates and proving the integrated result.

**Reason:** parallelism should increase quality/throughput, not reintroduce shared-checkout races.

---

## DEC-044 — Routine infrastructure maintenance should require approval, not terminal choreography
**Date:** 2026-09-19  
**Status:** APPROVED DIRECTION

Watcher/orchestrator/backend/systemd/deployment updates should eventually be developed, reviewed, installed, verified and rolled back by controlled infrastructure tooling.

The owner should approve sensitive changes in the product/chat flow rather than manually copying shell commands.

Termius/SSH becomes break-glass recovery.

---

## DEC-045 — Privileged infrastructure needs separation of duties and automatic rollback
**Date:** 2026-09-19  
**Status:** APPROVED DIRECTION

Build a Privileged Action Broker plus Deployment/Infrastructure Controller.

A component may participate in building its replacement, but must not have unrestricted authority to rewrite itself and declare success.

Versioned releases, exact artifact identity, health verification and rollback are required for infrastructure promotion.

**Reason:** increased autonomy must not collapse the safety boundary that makes unattended operation trustworthy.

---

## DEC-046 — Dev Team planning can proceed now; implementation follows the current-product gates
**Date:** 2026-09-19  
**Status:** ACTIVE  
**Source:** explicit owner migration continuation; consistent with CURRENT_TRUTH and MIGRATION_HANDOFF

**Decision:** Plan Engineering Orchestrator / Dev Team V1 while the permanent Builder Environment round remains in flight. Preserve that round; do not duplicate or restart it without failure/stoppage evidence.

Implementation order: Builder Environment review → controlled Linux migration/promotion → approved secrets → always-on runtime → private HTTPS when approved → real Samsung/iPhone/runtime verification → UI refinement → response/latency refinement → real-world sessions/evidence → Dev Team V1 → privileged infrastructure control → World/Event Ledger/Attention/expectations/automation/integrations.

**Reason:** preserve the current reliability/deployment sequence while using waiting time for rigorous specification work.

**Supersedes:** the contradictory Sequencing rule at the end of the previous ROADMAP, which placed World/automation expansion before the engineering organisation. Product goals and safety invariants remain active.

**Consequences:** ENGINEERING_ORCHESTRATOR_V1.md records a PROPOSED detailed design. Its task-store choice, retry counts, concurrency limits and other new mechanics are not silently promoted to approved decisions. No runtime work or bridge instruction is authorised merely by the presence of that specification.

---

# How to add a decision

Use:

```
## DEC-XXX — Title
Date:
Status:

Decision:

Reason:

Consequences:
```

Never silently rewrite old rationale. If a decision changes, add a new decision that explicitly supersedes the old one.


## DEC-047 — Engineering Orchestrator V1 implementation is owner-authorised
**Date:** 2026-09-19  
**Status:** ACTIVE  
**Source:** explicit owner approval in the GPT Director conversation

**Decision:** The owner explicitly approved Engineering Orchestrator V1 moving from planning into implementation under the existing canonical Git specification and safety boundaries.

This approval removes the separate planning → implementation authorisation gate. It does **not**:
- waive the prerequisite ordering in DEC-046;
- approve production deployment or promotion;
- approve secrets/credential handling, privilege expansion, CROOKS business writes, destructive actions, or new external spend;
- silently approve unresolved mechanism choices that the V1 specification marks for architecture/engineering review;
- authorise bypassing independent review, evidence binding, workspace isolation, or release gates.

Implementation may begin once the preceding DEC-046 deployment/current-product prerequisite gates are satisfied, unless the owner explicitly changes that ordering in canonical Git.

**Reason:** preserve the owner's explicit implementation approval without allowing it to be misread as a blanket waiver of established safety and sequencing constraints.


## DEC-048 — Ratify the observed Linux production promotion
**Date:** 2026-09-19  
**Status:** ACTIVE  
**Source:** explicit owner ratification in the GPT Director conversation

**Decision:** The owner ratified the already-observed, owner-performed Linux production promotion to exact candidate `1cf3a0f3361b79f9de208d80f501543c53c244b5`, including the installed/enabled `crooks-assistant.service` backend and tailnet-only Tailscale HTTPS route.

This ratifies the existing observed runtime state; it is **not** approval for another production deployment, broader exposure, Funnel/public networking, new secrets, broader privileges, CROOKS business writes, or account-level connector changes.

The observed production runtime remains:
- checkout at exact candidate `1cf3a0f3361b79f9de208d80f501543c53c244b5`;
- backend bound to `127.0.0.1:8000`;
- tailnet-only Tailscale HTTPS;
- CROOKS writes disabled.

Existing already-present credential state is recorded as observed runtime state. Any **new** secret provisioning, including the still-missing Gmail OAuth token, remains separately gated.

**Reason:** reconcile canonical Git with the owner-performed and independently observed production state without widening authority beyond that exact state.

**Consequences:** DEC-046's controlled Linux promotion, always-on backend, and private-HTTPS gates may be treated as satisfied by the ratified state. Remaining prerequisite work includes unresolved runtime-secret gaps, real-device/runtime verification, current UI/response quality, and real-world evidence.

## DEC-049 — Approve project-scoped Claude harness experiment files
**Date:** 2026-09-19  
**Status:** ACTIVE / BOUNDED  
**Source:** explicit owner approval in the GPT Director conversation

**Decision:** Project-scoped `.claude/` files may be created or modified **only in isolated engineering workspaces** for the reviewed CROOKS harness experiment.

This approval covers the bounded project harness experiment described by the verified ECC audit/reuse plan, including reviewed project-scoped rules, skills, settings/hooks and their tests. It does **not** approve:
- user/global `/root/.claude` or account-level setting changes;
- connector/MCP grant changes;
- production deployment;
- new secrets or credentials;
- broader privileges;
- business writes;
- external spend;
- destructive actions.

The worker must not route around any unrelated permission refusal; it should use only the newly approved project-scoped workspace boundary and stop on any broader permission requirement.

**Reason:** enable the smallest isolated harness-hardening experiment without weakening the account, production, connector, secret or privilege boundaries.


## DEC-050 — Retire user-facing Split; one CLIVE session manages simultaneous work
**Date:** 2026-09-20  
**Status:** ACTIVE PRODUCT DIRECTION  
**Source:** explicit owner direction in GPT Director conversation

**Decision:** The future CLIVE interaction model must not require the owner to divide the assistant into manual halves. Retire the user-facing Split / Half 1 / Half 2 / Merge / Close abstraction.

Useful internal branch/concurrency mechanisms may survive temporarily or evolve where they retain a unique responsibility. User-facing simultaneous work should instead appear as independently progressing jobs/objectives inside one coherent CLIVE session.

The immediate interaction direction is a continuous perceptible lifecycle from listening/hearing through understanding/work/result/response, progressive results, interruption without losing unrelated work, and the premium dark/liquid-glass visual direction.

Every real session should increasingly produce privacy-minimised evaluation evidence. Important quality gates should use independent/adversarial evaluation, including mutation of the tests themselves where material. Dynamic UI should evolve through typed safe primitives/scene composition rather than arbitrary model-generated executable UI.

Detailed doctrine and observed research findings are recorded in [CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md](./CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md).

**Reason:** Split exposes internal concurrency management to the owner and has accumulated interaction complexity. The desired product is one operating intelligence that manages simultaneous objectives itself. Existing evidence also shows post-transcription tests do not prove the live voice experience, so current-product quality must be evaluated end-to-end.

**Consequences:** Existing Split-specific UI/tests are migration evidence, not permanent product requirements. Retiring them is valid under DEC-037/038. This decision does **not** alter DEC-046 sequencing, adopt an Orchestrator freeze candidate, authorise production deployment, enable connectors/secrets/business writes, expand privileges, or weaken action-safety invariants.

---

## DEC-051 — CLIVE is a persistent intent-to-execution operational layer

**Date:** 2026-09-20  
**Status:** ACTIVE PRODUCT DIRECTION  
**Source:** explicit owner approval after product-philosophy synthesis

**Decision:** CLIVE's north-star product identity is a persistent operational layer between human intention and the software, people, devices and real-world processes required to accomplish it.

The product should not collapse into an AI dashboard, unified inbox, phrase-to-screen router, or one-shot chatbot. It should maintain evidence-backed operational state outside conversation, infer objectives from language plus context, investigate for significance rather than merely repeat source-system facts, coordinate deterministic capabilities beneath the reasoning layer, maintain objectives and commitments as reality changes, and present the smallest role/device-appropriate interface justified by the current situation.

The same utterance may require different work under different contexts; different utterances may represent the same objective. Evaluation must explicitly test both properties. Information gain, operational usefulness and human attention consumed are product-quality concerns, not only factual correctness.

People and staff may participate in shared objectives through permission-scoped workspaces. External collaborators may receive structured context and return evidence into the same operational model. Relevant working-monologue commitments should persist and resurface when useful rather than becoming recall spam.

Capability gaps are structured self-improvement evidence. Repeated/high-value gaps may drive proposed new capabilities through isolated implementation, adversarial/hidden evaluation, independent review and controlled adoption. This does not authorise uncontrolled self-modification.

Detailed doctrine: [CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY.md](./CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY.md).

**Reason:** The intended product removes human glue work — remembering, checking, translating, routing, coordinating, chasing and reconstructing context — rather than merely aggregating applications. The existing multi-API, dynamic-UI, persistent-memory, staff-workspace and self-improvement directions become coherent under this model.

**Consequences:** Future features should be challenged against whether they reduce human coordination/attention while preserving actual intention, authority and evidence. Deterministic fast paths remain valuable for genuinely explicit objectives, but keyword-triggered fixed outcomes must not substitute for contextual understanding. This decision does **not** alter DEC-046/047 sequencing, adopt any freeze candidate, authorise deployment, grant credentials/connectors, expand privileges or weaken action safety.

