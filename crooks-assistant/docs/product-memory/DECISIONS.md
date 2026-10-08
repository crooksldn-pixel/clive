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
**Status:** ACTIVE for the server as canonical always-on runtime; the Mac's rollback role is SUPERSEDED (2026-09-25) by the Mac's role in DEC-058 / [OWNER_DECISIONS_2026-09-25.md](./OWNER_DECISIONS_2026-09-25.md): Swift and iPhone builds and tests, spare builder capacity; not a production or rollback host.  
**Was:** ACTIVE

CROOKS runtime should not depend on the Mac being awake.

Mac becomes optional control/development/rollback device. *(2026-09-19 wording, kept as history; see Status for the current Mac role.)*

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
**Status:** SUPERSEDED — production writes are on: `CROOKS_WRITES_ENABLED=true` in the production `.env`, by the owner's choice (`docs/DEPLOY_LINUX.md`; recorded on the host by `crooks-assistant/reports/deploy-66d3e05d.md`, 2 October 2026, and untouched by the deploys since). No dated owner-decision file records the day he turned them on. Every write still waits for its card (DEC-005, DEC-006, DEC-007), and `CROOKS_WRITES_LOCAL_OWNER=false` still holds. Was: ACTIVE UNTIL EXPLICIT CHANGE

`CROOKS_WRITES_ENABLED=false` and `CROOKS_WRITES_LOCAL_OWNER=false` remain the migration baseline.

Enabling writes is a separate explicit decision.

---

## DEC-028 — GitHub bridge uses a separate branch
**Date:** 2026-09-19  
**Status:** RETIRED 2026-09-25 with the bridge watcher (DEC-058); was ACTIVE

`crooks-ai-bridge` carries communication only.

It must not be merged into production code.

---

## DEC-029 — Bridge watcher should trigger on inbox blob SHA, not branch HEAD
**Date:** 2026-09-19  
**Status:** RETIRED 2026-09-25 with the bridge watcher (DEC-058); was ACTIVE

Claude updating its outbox must not retrigger itself.

---

## DEC-030 — Bridge watcher must fail closed around shared/dirty worktrees
**Date:** 2026-09-19  
**Status:** RETIRED 2026-09-25 with the bridge watcher (DEC-058); was ACTIVE

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
**Status:** HISTORICAL / SUPERSEDED (2026-09-25) as the execution order — the current order is the 2026-09-25 finish-first rule followed by the approved next phase ([ROADMAP.md](./ROADMAP.md) "NOW — 2026-09-25", [NEXT_PHASE_2026-09-25.md](./NEXT_PHASE_2026-09-25.md), DEC-058). The sequence below is the 2026-09-19 history of how that order was reached; its safety gates still apply.  
**Was:** ACTIVE  
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
**Status:** FULFILLED / HISTORICAL — the bounded implementation approval has been used: Engineering Orchestrator V1 is running as the remote engineering loop (DEC-060; [ROADMAP.md](./ROADMAP.md) D7; [CURRENT_TRUTH.md](./CURRENT_TRUTH.md)). Its DEC-046 gating is history with DEC-046; the limits listed below (no deployment, secrets, privilege, business-write or review-bypass authority) still hold, and later loop changes follow DEC-058.  
**Was:** ACTIVE  
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
**Status:** HISTORICAL — the 2026-09-19 ratification of production at `1cf3a0f…`. It is superseded as current production truth by `clive/trunk` `ce791d03…`, deployed 2026-09-25 under the 2026-09-24 operational alpha promotion decision (DEC-058; [CURRENT_TRUTH.md](./CURRENT_TRUTH.md)); its Gmail gap was closed on 2026-09-24 (DEC-058). Its limit on authority still holds: it approved no further deployment, exposure, secrets, privileges or business writes.  
**Was:** ACTIVE  
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
---

## DEC-052 — Preserve CLIVE's mission while making its mechanisms replaceable

**Date:** 2026-09-21  
**Status:** ACTIVE PRODUCT / ARCHITECTURE DIRECTION  
**Source:** explicit owner direction after long-horizon product-philosophy discussion

**Decision:** CLIVE must be designed for a permanently moving technological and organisational frontier. Its identity is attached to the durable problem — preserving human intention through distributed execution — rather than to today's models, APIs, UI, databases, orchestration or connectors.

Large organisations already exhibit distributed organisational agency across people, software, policies, records, incentives and delegated authority. CLIVE should progressively make relevant organisational cognition more explicit: objectives, evidence, unresolved state, dependencies, authority, capabilities, consequences and verified outcomes. The aim is not centralised machine control; it is reducing the human coordination tax while preserving human judgement and consequential authority.

There is no meaningful final "100% complete" CLIVE. Capability is a moving frontier. The architecture should preserve durable semantics such as objectives, identity/relationships, evidence/provenance, authority, time, uncertainty, commitments/dependencies, capabilities, outcomes and verification while allowing implementation mechanisms to be replaced or deleted.

Core architectural rule: **preserve accumulated understanding; make accumulated implementation expendable.** A technology that makes part of CLIVE obsolete should normally be treated as an opportunity to simplify or move the product's differentiation upward, not as something the old implementation must resist.

Adaptability remains controlled, not arbitrary self-modification: observed limitation → candidate change → isolated implementation/experiment → adversarial evaluation → independent review → controlled adoption. Tests protect active desired properties, not historical mechanisms. Components survive only while they retain a unique responsibility.

Maturity principle: **no reasonable objective should leave CLIVE without a useful next move.** When completion is impossible, the next move may be investigation, composition, delegation, missing-evidence request, human decision, capability proposal, physical-world step or explicit authority/safety boundary.

Detailed doctrine: [CLIVE_ADAPTATION_AND_ORGANISATIONAL_INTELLIGENCE.md](./CLIVE_ADAPTATION_AND_ORGANISATIONAL_INTELLIGENCE.md).

**Reason:** The owner explicitly identified technological obsolescence and organisational inertia as central risks. A system intended to mediate intention and execution over a long horizon must be capable of incorporating discontinuous technological change without fossilising the mechanisms that happened to work in 2026.

**Consequences:** Major architecture choices should identify the durable semantic contract separately from the replaceable mechanism and should state deletion/replacement conditions where useful. This strengthens EVOLUTION_POLICY and DEC-051; it does not waive DEC-046/047, adopt a freeze candidate, authorise deployment, credentials/connectors, privileges, business writes, or weaken action-safety/evidence gates.

---

## DEC-053 — CLIVE is the primary product identity and home projects persistent world state

**Date:** 2026-09-21
**Status:** ACTIVE PRODUCT DIRECTION
**Source:** explicit owner direction while reviewing the current mobile interface and startup identity

**Decision:** The user-facing product identity is **CLIVE**, expanded as **Computer Language Interface Virtual Environment**.

The primary CLIVE surface must not conceptually reset to an empty assistant waiting for a command. When relevant operational state exists, home should project the highest-value objectives, changes, commitments, exceptions and unfinished work from CLIVE's persistent operational model.

The orb remains a core identity/presence object, but is not merely a giant microphone button. Voice is one interaction path into CLIVE. The orb may contract or reposition when useful information deserves the space.

Permanent provider/service plumbing does not belong on the primary idle surface. Capability health becomes prominent when it materially affects the current objective. Fixed navigation/shortcuts may exist where useful, but must not make CLIVE behave like a dashboard of implementation modules.

Startup identity should move from point of light → abstract world/intelligence orb → CLIVE acronym reveal → final CLIVE wordmark. This records the conceptual identity, not one permanent animation asset.

Detailed direction: [CLIVE_IDENTITY_AND_HOME_SURFACE.md](./CLIVE_IDENTITY_AND_HOME_SURFACE.md).

**Reason:** The current screen's “System ready / What do you need?” framing contradicts CLIVE's persistent intent-to-execution model by visually implying the system wakes with no objectives or unfinished state. The interface should expose operational significance, not internal plumbing.

**Consequences:** Existing CROOKS-branded shell elements and fixed status/navigation patterns are migration evidence rather than permanent identity requirements. This decision does not require all historical CROOKS product-memory documents to be renamed immediately, and it does not authorise production deployment or weaken existing safety/authority gates.

---

## DEC-054 — Engineering continuation should become queued and event-driven; hourly polling is supervisory

**Date:** 2026-09-21
**Status:** ACTIVE ENGINEERING DIRECTION
**Source:** observed dual-stream freeze/Live Experience operation plus explicit owner approval to improve the Termius/Claude workflow

**Decision:** The current single-slot bridge/hourly-controller pattern is a validated bootstrap mechanism, not the desired control plane.

The next repository implementation should move toward:
- durable machine-readable task/result records rather than one overwriteable inbox;
- exact base/result SHA and worker identity on every attempt;
- scheduler-enforced reviewer independence;
- one task = one isolated worktree = one persistent worker session = one candidate;
- event-driven continuation immediately after completion;
- policy-validated obvious continuation: if the next stage is mechanically implied by the same authorised bounded objective, continue without waiting for owner/hourly approval; stop when scope, authority, safety, product direction or deployment changes;
- hourly GPT supervision as reconciliation/stall recovery rather than the normal continuation clock;
- generated active engineering state separate from curated product memory;
- explicit deterministic/transient/obsolete/owner-only blocker classes;
- fairness so a repeated repair/review loop in one stream cannot silently starve unrelated repository-only work in another.

Termius/manual workers should run in persistent tmux sessions so closing the mobile SSH client does not terminate legitimate work.

Critical machine invariants should migrate toward structured representations or a constrained semantic grammar rather than indefinitely extending regex/NLP-like interpretation of unrestricted prose.

Detailed plan: [ENGINEERING_CONTROL_PLANE_VNEXT.md](./ENGINEERING_CONTROL_PLANE_VNEXT.md).

**Reason:** Overnight operation demonstrated real idle gaps and stream starvation despite correct safety rules: one stream repeatedly occupied the shared lane, another stopped moving, and completed work could remain undispatched until a later hourly tick. M-01 through M-08 also demonstrated the cost of asking a mechanical evaluator to infer critical semantics from unrestricted English.

**Consequences:** Phase 0/1 repository work may proceed within existing engineering boundaries. This decision alone does **not** authorise watcher/systemd/runtime installation, production promotion, secrets/credentials, connector changes, privilege expansion, business writes or owner-only freeze adoption.

---

## DEC-055 — Engineering work-in-progress is observable operational state

**Date:** 2026-09-21
**Status:** ACTIVE ENGINEERING DIRECTION
**Source:** explicit owner direction while reviewing hourly-controller utilisation and Orchestrator philosophy

**Decision:** Active engineering attempts must expose structured operational progress rather than collapsing to a binary running/not-running state.

The minimum useful progress model includes current bounded activity, completed milestones, evidence produced, waiting/blocking state, next known action, last meaningful progress and separate liveness heartbeat, all bound to exact task/revision/attempt/worker identity.

Heartbeat must not count as meaningful progress.

The hourly supervisor should consume this progress and use its window productively: leave healthy work intact, schedule unrelated eligible work when safe spare capacity exists, investigate alive-but-nonprogressing attempts without duplicating them, reconcile stale attempts before retry, park blocked/owner-gated streams while others move, and advance completed attempts through already-authorised next actions immediately.

Operator visibility is also a product requirement for the engineering system. Termius and later CLIVE engineering surfaces should be able to render a compact live progress table from the same machine-readable state. This is operational telemetry, not exposure of hidden model reasoning.

Do not invent percentage completion where no reliable bounded denominator exists; show concrete milestones/evidence instead.

**Reason:** Binary liveness wastes supervisory windows and hides whether useful work is advancing. The Orchestrator's purpose is not merely to know whether a worker process exists, but to understand enough verified operational state to coordinate useful work around it without interruption or duplication.

**Consequences:** Phase 1 control-plane work should include append-only progress events, progress projection into ACTIVE_STATE, supervisor interpretation and a human-readable progress view. This decision does not authorise live watcher/systemd/runtime changes, production deployment, additional worker concurrency, new privileges, credentials, connectors, business writes or owner-only release/adoption decisions.

---

## DEC-056 — Explicit owner disagreement is durable operational evidence

**Date:** 2026-09-21
**Status:** ACTIVE PRODUCT / LEARNING DIRECTION
**Source:** repository review of the action lifecycle plus explicit owner instruction to preserve the finding

**Decision:** CLIVE must represent an owner explicitly considering and rejecting, editing or deferring a concrete proposal as first-class durable evidence.

Absence is not disagreement:
- proposal expiry means no decision was captured;
- revocation/moving-on means the proposal was withdrawn by context;
- neither may be counted as a decline.

For consequential proposals, the learning model should distinguish at least:
- **APPROVED** — the proposed action was accepted as presented;
- **DECLINED** — the owner explicitly decided the proposed action should not happen;
- **EDITED** — the action class was useful, but material execution details were changed by the owner;
- **DEFERRED** — the action may be appropriate, but not now.

This evidence should support earned autonomy, usefulness measurement, correction-burden analysis and future policy/world-model learning.

The existing action audit ledger remains deliberately content-minimised. Do not weaken that safety boundary by placing free-text proposal content or customer-sensitive deltas directly into `actions.jsonl`. Instead, design a separate redacted **Judgment Ledger / Judgment Event** layer that can reference the proposal/action identity while storing only the minimum useful learning context under the existing privacy/redaction seams.

A judgment event should be capable of carrying:
- proposal/action identity and action class;
- explicit decision outcome;
- bounded reason code;
- optional redacted owner explanation;
- proposal representation or fingerprint sufficient for learning;
- an edited replacement/delta where applicable;
- contextual/provenance references;
- timestamp and owner identity/authority evidence.

Unknown/expired proposals are excluded from approval-rate denominators.

Earned autonomy must be falsifiable. A statement such as “31/31 approved” is only valid when the denominator is defined over explicit considered decisions, not merely the subset that produced approval events.

**Reason:** The current action lifecycle records successful/failed execution, expiry and revocation, but lacks a semantic state for “the owner saw this specific proposal and said no.” The observability layer can detect generic corrections and owner feedback, but that does not recover the exact proposal → judgment → preferred alternative relationship. This loses some of the highest-value business-specific evidence and makes approval-only autonomy metrics structurally biased.

**Consequences:** Future action/judgment work should add explicit decline/edit/defer affordances and durable redacted judgment events before relying on approval-frequency metrics for autonomy. §22-style success criteria should incorporate usefulness/correction evidence as well as conformance. This decision does not enable production writes, alter action-authorisation semantics, weaken TTL/precondition/verification safety, or authorise collection of unredacted customer data.

---

## DEC-057 — Verification must reduce subject uncertainty, not justify itself

**Date:** 2026-09-21
**Status:** ACTIVE ENGINEERING DIRECTION
**Source:** observed 30-round Orchestrator freeze loop plus owner direction to optimise unattended engineering for useful product progress

**Decision:** Adversarial review remains required where appropriate, but a verifier does not gain unlimited authority to block a subject merely by finding further defects in the verifier itself.

A review finding blocks the subject only when it demonstrates a material defect in subject behaviour, safety, authority, state semantics or required evidence. A defect confined to the verification apparatus becomes its own bounded verifier task.

Two consecutive verifier-only rounds are a convergence signal to park that verification path and continue with a more appropriate verification mechanism unless the verifier defect invalidates prior subject evidence.

Reviewers are explicitly allowed to return READY/ACCEPT when no material subject defect remains.

The unrestricted-English prose-freeze parser experiment is therefore parked as historical engineering evidence. Preserve the real state-machine and safety lessons it discovered, but do not continue M-series/parser expansion as the active Orchestrator path. The typed Engineering Control Plane VNext implementation is the active path.

**Reason:** The freeze loop grew a 5k-line natural-language parser because each adversarial round could generate new English constructions for the parser to fail on. That process improved its own verifier rather than the Orchestrator subject and starved product-facing work. CLIVE's own evolution doctrine says mechanisms are expendable and null is a valid end state when a mechanism no longer earns its responsibility.

**Consequences:** Hourly supervision and future schedulers should favour actual product/control-plane progress, direct behavioural evidence and structured invariants. Verifier maintenance remains legitimate when it protects a real property, but it must not silently become the dominant product. This does not weaken independent review, safety gates or owner-only authority.

---

## DEC-058 — The 2026-09-24 and 2026-09-25 owner decisions join the log

**Date:** 2026-09-25 (recorded in this log during the product-memory consolidation; the decisions themselves are dated 2026-09-24 and 2026-09-25)
**Status:** ACTIVE
**Source:** the owner's explicit statements, recorded in [OWNER_DECISIONS_2026-09-24.md](./OWNER_DECISIONS_2026-09-24.md) and [OWNER_DECISIONS_2026-09-25.md](./OWNER_DECISIONS_2026-09-25.md), which remain the full text

**Decision:** These owner decisions are active and are listed here so that the decision log stays the one place every decision can be found:

- **Judgment evidence retention (Gate C of [OWNER_DECISION_PACKET_2026-09-21.md](./OWNER_DECISION_PACKET_2026-09-21.md)), 2026-09-24:** redacted rich judgment evidence is kept for 90 days on a rolling basis; the structured record is kept permanently; nothing learned from judgments becomes a durable preference until the owner confirms it; expiry is never a decline. Extends DEC-056.
- **Gmail runtime credential, 2026-09-24:** provisioned by the owner on the production host, stored outside every checkout, unattended refresh verified. The "still-missing Gmail OAuth token" of DEC-048 is history. Production writes remain governed by the existing action gate (DEC-027 unchanged).
- **Operational alpha promotion, 2026-09-24:** promotion authorised once the exact successor SHA passes full repository acceptance and an independent exact-SHA review, with a prepared rollback and a post-deploy health check.
- **Generative UI V1, 2026-09-24:** approved as specified in [GENERATIVE_UI_V1.md](./GENERATIVE_UI_V1.md).
- **One trunk, 2026-09-24:** work is finished only when it is in `clive/trunk` and the trunk passes full repository acceptance; production deploys come from the trunk.
- **Retirements, 2026-09-24:** the bridge watcher, `engineering-team-activation-v1` (superseded by the remote loop), `claude/release-secret-baseline-2026-09-24`, and the ChatGPT orchestrator-freeze and control-plane-progress streams. The bridge watcher was retired on 2026-09-25.
- **Synthetic credentials in tests, 2026-09-25:** assembled at runtime through one shared test helper, never listed in the secret-scan baseline; supersedes the 2026-09-24 baseline authorisation for HumanisingTests.swift.
- **Loop update, 2026-09-25:** builders may run declared checks in the check sandbox; acceptance and landing into `clive/trunk` require a green GitHub acceptance run on the exact SHA; the product safety core, evidence tools and loop code join the protected paths.
- **Engineering off the production host, 2026-09-25:** once clive-worker-01 has proven itself, the loop on the production host is stopped and its reviewer key and worker token are removed there.
- **The Mac's role, 2026-09-25:** Swift and iPhone builds and tests, spare builder capacity; not a production host.

**Supersedes:** DEC-028, DEC-029 and DEC-030 are RETIRED with the bridge watcher; their outcome (DEC-015: the owner is not a message courier) is carried by the remote engineering loop. DEC-048's Gmail gap is closed, and DEC-048 is historical as production truth: production now runs `ce791d03…`, promoted under the operational alpha promotion decision above. DEC-019's Mac rollback role is superseded by the Mac's role above. DEC-046's execution order is superseded by the 2026-09-25 finish-first rule and the approved next phase ([NEXT_PHASE_2026-09-25.md](./NEXT_PHASE_2026-09-25.md)). DEC-047's implementation approval is fulfilled: the remote engineering loop is running.

**Reason:** the dated records were written outside this log; without an entry here a reader of DECISIONS.md would miss active owner decisions and would still treat the bridge watcher decisions as active.

**Consequences:** No new authority is created by this entry. Deployment, credentials, spend, permissions and business writes remain owner-gated exactly as the dated records say.

---

## DEC-059 — Canonical Objective IDs keep their three-character minimum; invalid fixtures are repaired

**Date:** 2026-09-23/24 (recorded in this log during the product-memory consolidation on 2026-09-25)
**Status:** HISTORICAL TECHNICAL RATIONALE — not superseded
**Source:** owner decision during the Remote Engineering Control V1 repairs, recorded in [OPUS_5_5_HANDOFF_2026-09-24.md](./OPUS_5_5_HANDOFF_2026-09-24.md) §8 ("Owner decision")

**Decision:** When the initial Remote Engineering Control V1 worker candidate (`f496bf61…`) failed because its test request IDs were only two characters long, the owner decided:
- preserve the canonical Objective ID minimum length of 3;
- do not weaken `app/orchestrator/objectives.py`;
- fix the invalid test fixture IDs instead.

**Reason:** the canonical Objective validation is shared by the whole engineering lifecycle; a new consumer's fixtures must conform to it rather than loosen it for everyone.

**Consequences:** The repair line (`a15f87ed…`, then `6c300c5f…`) fixed the fixtures and left the validator unchanged. The decision is kept as the rationale for that validation rule; any change to the minimum needs a new owner decision.

---

## DEC-060 — Owner authority to activate Remote Engineering Control, conditional on its gates

**Date:** 2026-09-24 (recorded in this log during the product-memory consolidation on 2026-09-25)
**Status:** FULFILLED — the conditional authority has been exercised; it is not standing runtime authority
**Source:** the owner's explicit words "authorise activation", recorded in [OPUS_5_5_HANDOFF_2026-09-24.md](./OPUS_5_5_HANDOFF_2026-09-24.md) §9 ("Owner activation authority")

**Decision:** The owner authorised activation of Remote Engineering Control once the activation candidate had satisfied the required evidence and review gates: full repository acceptance and a fresh independent exact-SHA review of that exact candidate. The authority explicitly did not permit bypassing exact-SHA review, carrying a review over to a successor SHA, or activating an unreviewed or unaccepted candidate (such as `5fc4aa94…`, whose acceptance run was cancelled).

**Reason:** the owner wanted routine repository-only engineering to stop depending on relayed terminal commands (DEC-015), without giving up the evidence gates.

**Consequences:** The authority has since been used: the remote engineering loop is running (see [CURRENT_TRUTH.md](./CURRENT_TRUTH.md)). It covered that one bounded activation only. It grants no deploy, runtime, secrets, permissions or business-write authority; later changes to the loop, its hosts or its privileges follow their own owner decisions (DEC-058).

---

## DEC-062 — The 2026-09-26 owner decisions join the log: the reviewer's model and cost

**Date:** 2026-09-26 (recorded in this log on 2026-10-05)
**Status:** ACTIVE
**Source:** [OWNER_DECISIONS_2026-09-26.md](./OWNER_DECISIONS_2026-09-26.md), "recorded from the owner's explicit answers in the Opus 5.5 engineering session", which remains the full text. It records his answers, not his words verbatim.

**Decision:**
- **The loop's routine exact-SHA reviews run on `gpt-6-luna` at medium effort.** The code defaults are `DEFAULT_MODEL` and `DEFAULT_EFFORT` in `app/orchestrator/reviewers/gpt.py`. He had asked to move from `gpt-5.6-sol` to `gpt-5.6-luna`, because the reviews were burning OpenAI tokens. On that day's list prices, `gpt-6-luna` beat `gpt-5.6-luna` on both cost and quality.
- **The production deploy review stays on `gpt-6-sol` at medium effort** (`DEPLOY_REVIEW_MODEL`). It is rare, and it is the last gate before the live system.
- **He accepted the risk.** A weaker reviewer can pass a defect, or raise a finding that is not real and costs a repair round. The engineering measures judge the choice: review rounds, false findings, and defects found after acceptance. If Luna's quality shows there, the loop moves back to `gpt-6-sol`.
- **The loop-update follow-ups were left to the Director, who did both.**
  - The manual kernel CLI's `verdict` and `integrate` need the same green GitHub acceptance gate as the loop.
  - The tests that hold the protected code are protected too.

**Reason:** the dated record was written outside this log. Without an entry here, a reader of DECISIONS.md would miss an active owner decision (DEC-016, DEC-058).

**Consequences:** this entry creates no new authority.

---

## DEC-063 — The 2026-09-28 owner decisions join the log: every sentence is a model turn

**Date:** 2026-09-28 (recorded in this log on 2026-10-05)
**Status:** ACTIVE
**Source:** [OWNER_DECISIONS_2026-09-28.md](./OWNER_DECISIONS_2026-09-28.md), "recorded from the owner's explicit instructions in the Opus 5.5 engineering session", which remains the full text.

**Decision:** The owner, verbatim:

> get rid of the fast path actions and inbuilt voice term base because sometimes even just mentioning a word means nothing gets done but look up order xyz, and the terms block means certain words such as Clive - is registered as Plaid. and many other instances, overall, they are holding it back a for lot more than helping it and this is not good.

- **Every typed or spoken request is a model turn.** The words go in exactly as said, with the tools the model already has. No phrase, order number or intent match answers a sentence, and nothing is looked up before the model is asked. The fast lane is gone: `app/fastpath/`, its recipes and lanes, the order prefetch and the self-correction layer.
- **Nothing tells the recogniser which words to expect, and nothing rewrites what it heard.**
  - ElevenLabs Scribe is sent the audio alone, and the Whisper fallback gets no prompt.
  - The post-transcription normaliser is gone; the transcript is only trimmed.
  - `CROOKS_SCRIBE_KEYTERMS` and `CROOKS_SCRIBE_MAX_KEYTERMS` are no longer settings.
- **What was kept:**
  - Taps. A button names what it does, and `app/recipes.py` holds the reads that buttons name.
  - The spoken "yes" over a waiting card. That is the write boundary's interlock, and a spoken yes never applies a change.
  - Plain trimming of the transcript.
- **The app's accent is iOS blue**, and the start-up's dots go steel (`0bdfe58c`).
- **The owner's TV screens get a remote mode.**

**Supersedes:** for anything said or typed, the "deterministic fast paths remain" line of [CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md](./CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md) §2.6. Taps stay deterministic.

**Reason:** the dated record was written outside this log (DEC-016, DEC-058).

**Consequences:**
- A simple lookup is now a model round trip: seconds, not milliseconds.
- "Next", "go back" or "open the inbox" said aloud reach the model, which has no tool that moves the screen. The buttons do that.
- One departure is on the trunk. The team page reads short sentences such as "I've packed 2106" on the phone (`web/today-say.js`, built from his words of 2 October: "any way they intend to act can be accepted as input: a click, speech, typing"). Whether that is an allowed exception to this decision is his call.

---

## DEC-064 — The 2026-09-30 owner decisions join the log: the ship rule, acceptance, skills, capacity, the re-pin, filing and landing

**Date:** 2026-09-30 (recorded in this log on 2026-10-05)
**Status:** ACTIVE
**Source:** [OWNER_DECISIONS_2026-09-30.md](./OWNER_DECISIONS_2026-09-30.md), "recorded from the owner's explicit answers in the Opus 5.5 engineering session", which remains the full text.

**Decision:**
- **The ship rule is regression-only, with one exception.**
  - The owner, verbatim: "regression only ship rule is good for now". He was answering the advice he quoted: "anything shown to leak customer data, or to write to the shop or send an email you didn't confirm, blocks whether it's new or old. Everything else old goes into the next build".
  - A material finding blocks a deploy only when this change makes production worse, or when it is shown to leak customer data, or to write to the shop or send an email he did not confirm, whether the defect is new or old.
  - Every other material finding is a follow-up for the next build. A finding that cannot be dated to this change is treated as new.
  - The rule stands "for now", until he changes it.
  - What stays: the exact-SHA review; green acceptance on the exact head; merging only at the expected head; his hold on every shop or email write; and the rule never to weaken the kernel, test assertions, secret scanning or the acceptance machinery.
- **Acceptance moves to a self-hosted runner on clive-worker-01.** The owner, verbatim: "Self hosted runner definetely".
  - The runner is isolated in its own VM or its own user.
  - It holds no production credential and not the engineering token.
  - It is registered to this repository only.
- **The owner's curated skill list is his decision.** He answered "Yes" to: "Does your own skill list count as your approval? That skips the per-skill sign-off and the cap of 5."
  - Every skill is still pinned, scanned per skill, licence-checked, and installed with its provenance, and it can be removed.
  - Anything that runs on its own stays his to approve: a hook, an MCP server, an executable, a key, a new data vendor or spend.
- **Builders run on his one Max plan.** The owner, verbatim: "Just max currently if we need more i can get another max plan". He accepted the consumer-terms risk; the fallback is a Team plan or the API.
- **The loop was re-pinned to `40e6a73f` under his waiver.** The owner, verbatim: "waive". He said it after being told that the second review's findings were not regressions against the loop the host was running.
  - The waiver covers exactly `40e6a73fb5095e9415b1e07283ed084bec82f2fd`; any other SHA still needs READY.
  - Its three follow-ups are the Director's, by hand: a stopped worker is confirmed gone; a restart test of `run`; declared checks are required.
- **Filing is switched on, and the loop lands its own work.** He was offered four steps: filing; the loop merging its own work; the release service; and parallel builders. He answered, verbatim: "I say yes to the first two".
  - Filing: `CROOKS_ENGINEERING_HOST=worker-01`, and the engineering inbox credential moves to the live secret tier. Every filing still waits for his hold on its card.
  - Landing: the loop may fast-forward `clive/trunk` to exactly a candidate's SHA only when all of these hold:
    - GitHub acceptance is green on that SHA, asked at that moment;
    - the loop's review of that SHA is READY;
    - the candidate changes no protected path;
    - the candidate already contains the trunk head.
  - Deploying is unchanged by this.

**Still open on that day:** Jev access; a written data policy for business text leaving the host; the reviewer's monthly budget; and decisions 3 and 6 of the self-shipping plan.

**Supersedes:**
- The rule applied in review rounds 9, 10 and 12 ("it can be exploited; it would lose data; it would leak data").
- From filing on, the standing deploy rule that the engineering credential stays parked and `CROOKS_ENGINEERING_HOST` stays unset.

**Reason:** the dated record was written outside this log (DEC-016, DEC-058).

**Consequences:** this entry creates no new authority. Deploys, credentials, spend and business writes stay owner-gated exactly as the dated record says.

---

## DEC-065 — The 2026-10-01 owner decisions join the log: CLIVE's voice, keys from the app, the team, and three numbered rulings

**Date:** 2026-10-01 (recorded in this log on 2026-10-05)
**Status:** ACTIVE
**Source:**
- [OWNER_DECISIONS_2026-10-01.md](./OWNER_DECISIONS_2026-10-01.md) is the full text for the voice, the keys and the team.
- Decisions 7 and 8 and ruling 12 of the same day never reached product memory. They are recorded here from:
  - PR #85 (`159b4fcc`);
  - PR #78 (`9252de68`);
  - the loop request `mark-packed-counts-as-packed-3` on `clive/control/worker-01-inbox`;
  - the code that carries them.
- The re-pin waiver is from PR #72.

**Decision:**
- **CLIVE speaks in his voice spec.** He wrote "JARVIS Decoded — A Voice Spec for CLIVE" (his Claude doc, 30 September) and said, verbatim: "i created this for the personality i want clive to have".
  - Its drop-in prompt is `PERSONALITY` in `app/kb/loader.py`, the first section after who CLIVE is.
  - The sections after it win any conflict. So figures are said as words, there is no spoken "Confirm?", and the examples show only what CLIVE can do.
  - It governs wording only.
- **Keys and sign-ins are stored from the app.** He was asked whether the app may store keys, and whether every change should ask for a passkey. He answered "yes" to both.
  - Keys are stored from `/connections`.
  - Each key is tested with its service before it is stored, and stored encrypted.
  - Every change asks for his passkey at that moment.
- **The team uses CLIVE.** His choices, verbatim: "Own phones"; "Mark orders packed, Fulfil in Shopify, Send email replies, Adjust stock from counts"; "Everything but your chats".
  - The Today screen (`/today`) is the team's.
  - A member of the team gets in only after he approves their login with his passkey.
  - Refunds, cancellations, order edits, discounts, store credit and new emails stay his.
  - The team's conversations run on his Max plan. That carries the consumer-plan risk recorded on 30 September, with the same fallback.
- **Decision 7: builders never auto-update the Claude CLI** (PR #85). The builder environment carries `DISABLE_AUTOUPDATER=1`, and the CLI is updated deliberately, with the pin.
- **Decision 8: a custom item on an existing order.** His words, as PR #78 records them: "custom item on an existing order: yes". It is a write, staged on a card for his confirmation, like adding a catalogue item.
- **Ruling 12, closing B-04: a screen's own Mark packed counts as packed.** The owner, verbatim: "yes, the mark packed should be in clive memory, not shopify this becomes more important later down the line". A packed record counts as packed whichever way it was made (`app/displays/store.py`):
  - by a screen's own button;
  - by his remote;
  - by the remote's controls on a device that is itself a screen.
- **The loop was re-pinned to `b577bc97`, with two narrow findings waived.** He waived them on the understanding that their fixes ship with the next re-pin (PR #72 carries them).

**Reason:** the dated record was written outside this log, and three of that day's numbered decisions were written only into code, pull requests and a loop request (DEC-016, DEC-058).

**Consequences:** this entry creates no new authority. The numbers 7, 8 and 12 come from a list of that day's decisions that is not in the repository. Nothing else from that list is recorded here, because nothing else from it can be read.

---

## DEC-066 — CROOKS Returns is an owner-deployed service outside the engineering kernel; CLIVE connects to it read-first, writes as proposals, money on the owner's hold

**Date:** 2026-10-03
**Status:** ACTIVE
**Source:** the owner's brief for the CLIVE builder (`docs/returns/BRIEF_CLIVE.md` and `docs/returns/SCOPE.md` on branch `claude/compassionate-dirac-44hnee`), which says to record the service this way
**Recorded here:** on 2026-10-05, from the text of DEC-061 on PR #96's branch (`claude/returns-and-design`, `f475be0d`), word for word apart from this line and the number. PR #96 is not on the trunk. DEC-061 is used on two unmerged branches: on PR #96 for this entry, and on `claude/venture-engine-v1-2026-09-29` for the venture engine. So this log leaves DEC-061 unused, and the two never clash. The files this entry names (`app/tools/returns_tools.py`, `app/clients/crooks_returns.py`, `tests/test_crooks_returns_contract.py`) arrive with PR #96. When PR #96 lands, its DEC-061 is this entry and is dropped as a duplicate.

**Decision:** CROOKS Returns (`https://returns.crooksldn.com`) is the owner's own returns and exchanges service, replacing AfterShip. He built it and deployed it himself on 3 October 2026, in its own Docker Compose container (service plus Caddy) on `crooks-os-prod-1` at `/opt/clive/crooks-returns`, from branch `claude/compassionate-dirac-44hnee`, folder `crooks-returns/`. It was built **outside the CLIVE engineering kernel**: it has no kernel task, no review record and no acceptance record, and none is to be assumed. Shopify stays the system of record (an approved request becomes a native Shopify Return); the service adds the request before Shopify knows of it, the customer's choices, the Parcel2Go label paid from the PrePay balance, the timeline and the attention flags. Its settings are its own `.env` (`RETURNS_*`), never CLIVE's.

CLIVE connects to it as the brief's section 6 says, and only through its `/api/v1`:
- **Read-only first, the owner's alone.** `returns_open`, `return_find` and `returns_stats` (`app/tools/returns_tools.py`), the home's Needs you row (`GET /returns/brief`), the order card's Returns section and the customer's story. No staff member's set and no bounded service work names them.
- **Writes are proposals.** `return_action` reads the return, asks the service's `/preview`, and stages a card that is that preview — its `will` lines and money exactly as returned. A refused preview stages nothing. Only the owner's gesture executes, with an idempotency key made for that card (the service scopes it to the return and the action) and actor `clive for George`; the result is verified (the re-read shows what the service said it did, with no error) or the service's own error.
- **Money only on his hold.** Approve with `label_now` or `no_return`, `label` with no tracking (it buys one), `receive` in condition `ok`, and `complete` are raised to RED and so are hold-to-arm; every other action is his swipe.
- **Never** the customers' portal (`/proxy/api/*`), the service's SQLite file, or Shopify's return mutations for a return the service owns. A return's money moves through `return_action`, never `shopify_refund_create`.
- **Keys through Connections.** A "CROOKS Returns" card with a read key and a write key (`crooks_returns_read_key`, `crooks_returns_write_key`), stored like Ship24's. The read key is tested when it is saved; the write key is never sent to read (the service would allow it), so it is proven on the first action he approves, and a refusal there asks for it alone. The owner copies them from `grep CLIVE /opt/clive/crooks-returns/.env`. The base URL is the setting `CROOKS_RETURNS_BASE_URL` (default `https://returns.crooksldn.com`).
- **No webhooks yet.** Receiving the service's signed webhooks would mean a new route through the access door, which is the owner's decision. Until he makes it, CLIVE asks `GET /returns?open=true` at most once a minute and only while someone is using CLIVE, then `?since=` for what changed.

**Reason:** the service and CLIVE are separate trust boundaries (the service takes public traffic; CLIVE is behind Tailscale with owner-only writes), and the owner's rule `proposed ≠ authorised ≠ started ≠ completed ≠ verified` holds for a change made through another system as for one CLIVE makes itself.

**Consequences:** CLIVE gains no authority over the service: it cannot change its settings, its policy or its data except through the actions the owner approves on a card. The service's code is tested against CLIVE's client offline (`tests/test_crooks_returns_contract.py`, which runs the service's own code from that branch with its fake Shopify and simulated Parcel2Go), not reviewed by the kernel. A change to the service is the owner's, on its own branch, and does not pass through CLIVE's engineering loop.

**Follow-up: a ceiling on a label's price (needs a change to the service).** A label's price on the card is the service's preview, which quotes Parcel2Go; when the owner approves, the service asks Parcel2Go again and buys at that price, and its execute takes no ceiling (an approve takes `postage_mode`; a label takes tracking or nothing). CLIVE cannot hold a purchase to the quoted price without the service's help, so the card says the price is quoted again when bought. The fix is the service's: accept a `max_label_pence` on `approve` (label_now) and `label`, refuse with 409 when the new quote is higher, and CLIVE would send the preview's figure. Until then the label actually bought is on the return's timeline (`label_bought`, with its cost).

**What a webhook from the service would need, when the owner decides it:**
1. **A way in.** CLIVE listens on `127.0.0.1:8000` behind `tailscale serve`; the service runs in a Docker container, where `127.0.0.1` is the container itself, so today it cannot reach CLIVE at all. One of: CLIVE also listening on the Docker bridge address, or the service container on the host's network. That is a unit or compose change on the production host.
2. **A door that lets it through.** Every route but the public ones needs the owner's Tailscale identity (`app/main.py` `guard_and_freshness`); the service has none. The route (for example `POST /hooks/returns`) would join the door's public paths, and its own signature check becomes its only lock: `X-Crooks-Returns-Signature` is hex HMAC-SHA256 of the raw body with the shared secret, compared in constant time; anything unsigned, malformed or over a small size is refused before it is parsed.
3. **A shared secret.** Generated once, stored as a new CLIVE key (`crooks_returns_webhook_secret`, static tier) and as `RETURNS_CLIVE_WEBHOOK_SECRET` in `/opt/clive/crooks-returns/.env`, with `RETURNS_CLIVE_WEBHOOK_URL` set to the route's address as the container reaches it; the service restarted.
4. **What it does with an event.** Nothing a customer could steer: it reads only `event` and the return's `id`, keeps none of the body (the body carries the customer's email and address), and drops the minute's cache (`app/clients/crooks_returns.py` `forget()`), so the home's row and the next read ask again. It changes nothing in the service and stages nothing.
5. **Reconciliation stays.** Delivery is at most once and never retried, so the minute's poll and `?since=` remain the source of truth either way.

---

## DEC-067 — The release service is built and switched off; it deploys only once the owner names who holds deploy authority

**Date:** 2026-10-07
**Status:** ACTIVE. On 8 Oct the owner named the rule: he approves each deploy himself, and his approval deploys at once (DEC-071, ruling 7).
**Source:** the owner's approval in the night-build brief of 7 October 2026, verbatim: "Release service. I build it tonight, switched off. It only deploys once you've said who holds deploy authority." His reason, as the brief records it: he wants deploys "to just happen (or fix themselves) without him relaying commands between Claude and the Termius Claude".

**Decision:**
- **Decision 3 of the self-shipping plan ([2026-09-29](../plans/2026-09-29-clive-ships-its-own-fixes.md)) is answered in part: the release service is built.** It is `app/release/`, with its unit and timer in `deploy/release/`, documented in [`docs/RELEASE_SERVICE.md`](../RELEASE_SERVICE.md). It performs DEPLOY_LINUX.md's "Deploying a new build" as code, rolls back on any failure after a change, writes the deploy record to `claude/deploy-<sha8>-record`, and shows its status on CLIVE's Builds screen.
- **It is switched off.** `CLIVE_RELEASE_ENABLED` defaults to off, and the unit is not installed. Installing it is a hand step on the production host; switching it on is the owner's setting in `/etc/crooks-os/release.env`.
- **It deploys nothing until the owner names who holds deploy authority**, as `CLIVE_RELEASE_RULE`:
  - `exact_sha_review`: a reviewer's SHIP record for exactly that SHA (branch `claude/review-<sha8>-record`);
  - `owner_waiver`: the owner's waiver of the review for exactly that SHA, given on the server, or with his passkey once CLIVE collects it.
  - Until then the rule is `off`, and nothing deploys.
- **Under either rule:** only `clive/trunk`'s head, only forward from what production runs, only with GitHub acceptance green on that exact SHA, one deploy at a time; a change to how CLIVE is installed (deploy/, the Makefile, the installer, the dependencies) stays a hand deploy.

**Still the owner's:** which rule (who holds deploy authority); when to switch it on, and when to leave dry run; and decision 6 of the self-shipping plan, whether anything may ship without his hold. Under `owner_waiver` nothing does; under `exact_sha_review` a deploy needs no gesture of his.

**Consequences:** this entry grants no deploy authority by itself. DEPLOY_LINUX.md's procedure is unchanged and stays the way production is deployed until the owner switches the service on. The service runs from its own pinned copy, never from the checkout it deploys, so moving that pin is a person's act, as the loop's re-pin is.

---

## DEC-068 — The loop upgrade of 7 October: why a build stopped stays off GitHub, findings reach the repair, more repair rounds, skills and a browser for builders

**Date:** 2026-10-08
**Status:** ACTIVE. Built in the repository; in force on a loop only through the owner-gated re-pin.
**Source:** the owner on 7 October 2026, verbatim: "Loop upgrades as protected PRs: publishing findings, findings fed back, more repair rounds, skills and a browser for builders. Termius re-pins worker-01 in the morning on your go." Before it: "I still don't feel like you are using the servers we have to its greatest capability ... Eventually, I should just be able to say to Clive what to do." The skills rest on his decision of 30 September that his curated skill list is his approval (DEC-064, [OWNER_DECISIONS_2026-09-30.md](./OWNER_DECISIONS_2026-09-30.md)).

**Decision:**
- **Why a build stopped is kept on the loop host and served over the tailnet only.** A stopped build's reviewer findings, failing check output and builder's report are kept in `<runtime>/stops` (files 0600) and served by `remote_engineering.py run --private-listen <tailnet address>:<port> --private-allow-node <node>` ([REMOTE_ENGINEERING_CONTROL_V1.md](./REMOTE_ENGINEERING_CONTROL_V1.md), "The private channel"). A node is named by its full tailnet name or its StableID, never by a bare machine name, which a node shared in from another tailnet can also carry. Nothing new goes to `clive/control/*` or anywhere else on GitHub. CLIVE shows them on the owner's Builds screen when `CROOKS_ENGINEERING_PRIVATE_URL` names the channel (off by default).
- **Findings reach whoever repairs.** A repair revision already got each material finding word for word; a test now pins it. A build filed again as `<id>-2` starts with the stop report of the try before it, but only when its title or its allowed paths are also the same.
- **More repair rounds.** A request may name 0 to 5. One that names none gets the host's `--default-repair-rounds` (2 unless the operator raises it, at most 5). No review is added per round.
- **Skills for builders.** A builder gets exactly the skills in `config/builder_skills.json` (now a protected path), every file pinned by its sha256: today the four design skills vendored in `.claude/skills/`. A launch with skills is made only on a Claude CLI version whose own commands are pinned by name (`BUILTIN_SLASH_COMMANDS` in `app/orchestrator/workers/claude.py`: 2.1.285 and 2.1.293, probed 8 Oct). On any other version no builder is launched with skills, and the loop is run with `--no-builder-skills` (builders then launch as before, with `--disable-slash-commands` and no skills) until a reviewed change pins that version.
- **A browser for checks.** When the host names them, Playwright's Chromium and playwright-core are bound read-only into the same check sandbox: no network, uid 65534, no capabilities.
- **The CLI's own plugins are an exact list** (`ALLOWED_PLUGINS`), each accepted only as reported with path `builtin`.

**Reason:** since 25 Sep the loop on clive-worker-01 took 65 requests and stopped 40, and it never published why (`status.py`: "What is never published: review findings text"), so whoever repaired a build had nothing to work from. With the repository public since 7 Oct, those words cannot go on GitHub.

**Consequences:** nothing here weakens exact-SHA review, the gate, protected paths, secret scanning or acceptance. None of it governs a loop until the owner-gated re-pin; the re-pin steps travel with the pull request, and the re-pin is recorded when it happens. The public status branch gains nothing, but it still carries what it carried before, including each stop's one-line blocker, which for a builder-reported or owner-decision stop is the builder's own words, redacted; publishing the stop's cause word instead is a recorded follow-up. So is bounding a check's memory with a cgroup: with browsers named, every check is bounded by `RLIMIT_DATA` rather than `RLIMIT_AS`.

---

## DEC-069 — From the question to the action: progress words while CLIVE works, then only what the answer is about; a message is one card and one hold

**Date:** 2026-10-07 (built on the night of 7–8 October, branch `claude/n2-flow`)
**Status:** ACTIVE
**Source:** the owner's words of 7 October, quoted in the night-build brief for the "flow" workstream, and the three points he approved in it.

**The owner, verbatim:**

> Currently, if you ask a question, sometimes you'll get shown irrelevant screens that just happened during a search process. For instance, today I asked for the email reply to [a customer] and it showed [a customer]'s total orders as a customer, then some random email from someone else, today's email threads and today's orders when all I wanted to see was the reply to [a customer].

> I also don't want to have to click save draft and then send — why do I have to click save draft and then say send it and then it pulls up a send it screen to send.

He wants "the flow from actually asking a question to the action happening to be a bit more smooth".

**Decision (the three points he approved):**
1. **Searches in progress never take the screen.** While CLIVE works the glass says what it is doing in words (the running tool, `web/app.js` `DETAIL_WORDS`), and then shows only what the answer is about. A turn's progressive workspace is begun quiet (`app/progressive.py`): no shell, header or read's card is staged before the answer. The answer's cards are chosen by `app/focus.py`, by three rules over the cards (never over words, MAP rule 7): a change waiting for him wins; otherwise a record read in full wins over the searches that found it; otherwise the listings and numbers are the answer. An error and a change are never set aside. Two cases, precisely:
   - **A change to a record he already had up keeps the rest of his screen.** When the change is to a record on the half's screen as the turn began, the other records he had up stay beside the change card, which stays on top (they are his screen, not this turn's finds), as do the attention lines of the changed record. What the model read on the way to the change never shows beside it, and never takes his screen away either (`app/screen.py` `carry`; an order number he says that the screen does not show still does, as round 12 holds). A change to a record that was not up, such as the reply to a customer found by searching, is the change card alone.
   - **An order asked for by its own id or number is never a find.** An order read whole this turn, or looked up by its number and found alone, is what the answer is about even when it is drawn as its one-line card: "put 1938 and 1940 side by side" shows both orders.
2. **Draft to send is one hold that sends it.** No Save draft step and no second Send screen. The hold stays (it is the approval gesture, MAP rule 2), and he can edit the words on that same card before holding: an edit withdraws the waiting change and prepares the same write again with the new words, through the gate and the write's own checks, so the hold always sends the words on the card.
3. **The same card for every message.** The one-hold card is the action engine's confirmation card carrying a generic `message` block (channel, to, subject if any, words, which fields are editable). Its contract is in `app/families/message.py`, for the WeCom, WhatsApp and Instagram writes to use.

**What this changes:** D-5's progressive hydration put a read's cards on the glass as each read landed (`tests/test_progressive_turn.py`, `turn_c8eb4cffe077`). For a spoken turn that is reversed: the owner judged a screen that fills with searches worse than a screen that waits for the answer, and the wait is said in words. Round 12's "the order that proved who it is for sits under the new one" is replaced by the new order alone (its card already names what it was made from). Replies and new emails are prepared by `gmail_send_reply` and `gmail_send_new`, whose card is the email and whose hold sends it; `gmail_draft_reply` and `gmail_draft_new` stay, and are for when he asks to keep it as a draft. The quiet "Save as draft" on the card, and "Send instead" on a draft's card, prepare the same words the other way.

**Reason:** the owner's own account of the flow, above.

**Consequences:** the gesture table, the gate, staff authority and the proof are unchanged: a send to a customer is still RED and still the hold, and is proven by reading the sent message back. Which tool the model chooses is still the model's; it is told which one to use in the tools' descriptions and one sentence of the system prompt.

**How a failure reads:** a send that provably did not go (Gmail refused it, or it never left) says "Not sent", why, and "Nothing was sent", on the card and in the voice, and offers "Try again": the same words, as they were on the card he held, prepared again as a new card to hold. A send whose outcome is not known (it may have gone) says to check Sent and never offers to send again. A change card on the screen is never swapped for a record the answer names beside it: that sentence is taken out instead.

---

## DEC-070 — George's research goes through the digester: each recommendation is a proposal weighed against the map, and he answers it on the Builds screen

**Date:** 2026-10-08
**Status:** ACTIVE. Built in the repository (`claude/n2-research`); live once deployed.
**Source:** the owner on 7 October 2026, verbatim: "I've also done some ChatGPT research products on Clive overall, so stuff like integrations, product roadmap, feature roadmap, how to integrate connections easily, the human API, and I think it'd be good for a way to actually accept this research into part of the Clive design and philosophy and actually to make a better way of accepting it." What he approved, verbatim: "Your research goes through the digester. Each recommendation becomes a proposal checked against the map's rules (adopt, park or reject, with a reason), and you approve them on the Builds screen."

**Decision:**
- **One way in, by two doors.** He gives a research file (PDF, Word, Markdown, text, a saved web page, or a ChatGPT export) on the Builds screen's Research section, or puts it in `.state/research/inbox/` on the server. Both go through the digester as it stands: its quarantine (the `research` intake handler, used only by name), its safety scan and its documents adapter. A scan block stops the document before any model sees it. How it works is [`docs/RESEARCH.md`](../RESEARCH.md).
- **Weighed against the map, not taken on trust.** Claude on the Max plan, with no tools, names each concrete recommendation with CLIVE's view (adopt, park or reject), a one-line reason, what building it would touch and what done looks like. Then CLIVE holds it to the repository's own design:
  - a quote that is not in the research is dropped, and the document says so;
  - a citation must be a rule, parked item, decision, idea or feature that exists; one backed by nothing is parked (DEC-017);
  - one that needs protected paths is parked for him (Rule 8);
  - the rules that never bend are checked again without the model, over the recommendation and its "done when". That check is advisory: it only moves a view towards reject, and his answer decides;
  - a repeat of an idea, a feature or earlier research is linked, not asked again.
- **His answer is an owner judgment.** Adopt, Park or Reject goes into the owner-judgment ledger (`app/builds/decisions.py`), bound to the proposal exactly as he saw it. A change of mind is a correction that keeps the first answer.
- **Adopt files nothing by itself.** It prepares a build request through the existing filing path (`submit_engineering_request`) on a card, filed only on his hold. The request goes to the build loop's inbox in the public repository, in CLIVE's words only: the research's quote and file name stay in CLIVE's private record, which the request names by id.
- **Research stays on the server.** `.state/research/` is git-ignored, and research is never committed.

**Reason:** his words above. The digester and the owner-judgment ledger already existed; this wires research into both rather than building a second path.

**Consequences:** no new authority. Adopt uses the existing filing path and his hold, and Park and Reject change nothing outside CLIVE's records. One new dependency, `pypdf>=6.19.0`, reads PDFs in a process of its own with a time and memory limit; installing it is a hand deploy, because `pyproject.toml` changed. Not built: the home's Builds row does not count research waiting on him, and ChatGPT share links are not fetched by URL.

---

## DEC-071 — The owner's rulings of 8 October: 43 questions answered

**Date:** 2026-10-08
**Status:** ACTIVE
**Source:** the owner's answers in the Director's session on 8 October 2026 (12:34 and 12:43 London), to 43 numbered yes/no questions. Every open owner decision the records held was put to him; his answers are quoted as he gave them.

**Decision:**

| # | Question | His answer, verbatim | What it means |
|---|---|---|---|
| 1 | Make the repository private again today? | N - for now | It stays public. Nothing secret or customer-identifying may be committed (the night's privacy sweep, PR #104, cleaned trunk). |
| 2 | Rewrite the history to strip the real customer details? | N | History is not rewritten. |
| 3 | Ask GitHub Support to purge old commits and pull-request copies? | N | No purge request. |
| 4 | Move the Returns/Shipping service into its own private repository? | Eventually - not now | Stays on its branch for now. |
| 5 | If private, run CI on clive-worker-01 instead of paying for minutes? | Y | Applies once the repository is private. While it is public, CI stays on GitHub's runners: a self-hosted runner on a public repository would run outsiders' code. |
| 6 | Make waiving the exact-SHA review the standing rule (green acceptance plus an independent review is enough to ship)? | Y | DEPLOY_LINUX.md's requirement of an exact-SHA review before every deploy is replaced by: green acceptance on the exact SHA, the pull requests' independent pre-merge reviews, and the owner's approval (ruling 7). |
| 7 | Release service: the owner approves each SHA, rather than anything reviewed ships? | "i want to say yes to deploy - but, once deploy should be instant, not deploy and then the deploy service runs and takes hours. deploy as in, implement this now" | `CLIVE_RELEASE_RULE=owner_waiver`. His approval, given in CLIVE with his passkey, starts the deploy at once (no waiting for a timer); CLIVE shows it through to the result. |
| 8 | Switch the release service on in dry run after the next hand deploy? | Y | Installed after the first hand deploy that carries it. |
| 9 | The build loop on clive-worker-01 is the normal way work lands; direct builders only for urgent work? | Y | Work is filed to the loop first. |
| 10 | Replace the GPT reviewer with a Claude reviewer? | Y | The loop's exact-SHA reviewer becomes Claude on his plan (a loop change; owner-gated re-pin). |
| 11 | Stop the old build loop on the production host after the re-pin? | Y | Confirms the 25 Sep decision. |
| 12 | GitHub Issues as the build board (Symphony)? | N for now | Not built. |
| 13 | Give the Director and CLIVE their own GitHub identity? | Y | A GitHub App per identity; George creates them. |
| 14-15 | WhatsApp for suppliers? For customers? | "Whatsapp for anything - not just one set role" | WhatsApp is a general channel: suppliers, customers, anyone. |
| 16 | Give CLIVE's WhatsApp its own new number? | Y | A new number; his phone's WhatsApp is untouched. |
| 17 | Apply for Instagram Advanced Access? | not right now | Not applied for. |
| 18 | Instagram's human-agent tag? | n for now | Not used. |
| 19 | hooks.crooksldn.com as the one public webhook address? | Y | The public door for /hooks/* only. |
| 20 | Returns events reach CLIVE through that address? | Y | CROOKS Returns posts its events to CLIVE's hooks door. |
| 21 | Let CLIVE use CLIVE Shipping now? | Y | CLIVE's Shipping keys are created at the service deploy. |
| 22 | Allow label buying on every order rather than an approved list? | Y ("22 is fine") | `SHIPPING_BUYING_ENABLED=true` on the service. CLIVE still needs his hold for every label. |
| 23 | Send labels straight to the printer through PrintNode? | Y | PrintNode on, on the service. |
| 24 | Delete CLIVE's old Easyship code? | Y | `app/shipping/` and its family go. |
| 25 | Accept that a two-part ask ("list today's orders and open 1940") shows only the order? | N, and: "asking to see todays orders and to show a specific order s different to asking to see a specific order and seeing the specific order + todays orders. in one instance it was asked, in the other, the ai inferred it was needed when it wasnt specified. clive can infer but inferring needs stronger relation, for instance, asking about a customers email can give detailed explanation as to why with other cards, not just showing the reason. this can be its tracking status, an instagram message. they were't asked for but if theyre relevant they are inferred, asking to see the customers email and it showing you every other email from other people today is not what we want to happen." | DEC-069's focus rules change: what he asked for always shows; what CLIVE adds unasked must be about the same subject (the same customer, order or thread); anything else stays off. |
| 26 | Never let the owner's own MCP servers load into CLIVE's live turns? | Y | `strict_mcp_config` on in production. |
| 27 | Bulk inbox actions (archive or junk many at once) on one hold? | Y | One card, one hold, for a set of threads. |
| 28 | Let CLIVE delete the unused Gmail drafts it leaves behind? | Y | CLIVE removes drafts it made and that were never sent. |
| 29 | Allow an email to be shown on a TV? | Y | An email may go on a screen when he puts it there. |
| 30 | Keep the team page acting on "packed 2106" without the model, as an exception to DEC-063? | Y | `web/today-say.js` stays: a recorded exception to "every sentence is a model turn". |
| 31 | "Routines" means saved multi-step jobs started by name? | Y | Routines are built as named, saved sequences of steps. |
| 32 | Run the scenes-versus-cards comparison on the bench and keep the winner? | Y | Ten real questions on the bench. |
| 33 | Can staff read security and login emails? | not yet | No. |
| 34 | Can staff send a draft the owner left, on their own hold? | Y | A staff member may send his draft with their own hold. |
| 35 | Staff join with a link and a code instead of Tailscale? | Y | Staff sign-in by invitation link and code. |
| 36 | Keep staff on the owner's Max plan for now? | Y | No Team plan yet. |
| 37 | Delete the retired Split code? | Y | Deleted (DEC-050). |
| 38 | Retire the Mac runtime and the menu-bar app? | Y | Deleted (DEC-058). |
| 39 | Delete the local Whisper speech client? | Y | Deleted (DEC-022: no local fallback on the server). |
| 40 | Archive the CROOKS Pad? | Y | Removed from the app; kept in history. |
| 41 | Delete the retired orchestrator scheduler? | NO | `orchestrator/scheduler.py` stays. |
| 42 | Keep the venture engine parked? | "park venture engine for now" | Stays parked on its branch. |
| 43 | Allow business text to go to AI services other than Claude (such as Jev)? | Y | Allowed, service by service; customer details still never go into logs, URLs or build requests (MAP rule 4). |

**Reason:** he asked for every decision that needed him, as yes or no, in one place.

**Consequences:** rulings 6 and 7 settle decisions 3 and 6 of the self-shipping plan and DEC-067's open question. Ruling 25 changes DEC-069's focus rules. Ruling 30 is a recorded exception to DEC-063. Rulings 37–40 and 24 retire parked code (MAP "Parked"); ruling 41 keeps the scheduler; ruling 42 keeps the venture engine parked. Rulings that need building are built as their own pull requests, each citing its ruling.

---

## DEC-072 — Approval to deploy: George's hold and passkey on the Builds screen approve one exact version, and the release service deploys it at once

**Date:** 2026-10-08
**Status:** ACTIVE. Built in the repository (`claude/n3-deploy-now`); live once deployed by hand and the release service installed (rulings 7 and 8).
**Source:** the owner's rulings 6, 7 and 8 of 8 October 2026 (DEC-071). Ruling 7, verbatim: "i want to say yes to deploy - but, once deploy should be instant, not deploy and then the deploy service runs and takes hours. deploy as in, implement this now". Ruling 6: waiving the exact-SHA review is the standing rule. Ruling 8: the release service goes on, in dry run, after the next hand deploy.

**Decision:**
- **What a deploy needs** (ruling 6, [`DEPLOY_LINUX.md`](../DEPLOY_LINUX.md)): GitHub acceptance green on the exact SHA, the pull requests it carries each independently reviewed before they merged, and the owner's approval of that exact SHA. An exact-SHA review is no longer required before a deploy.
- **Who approves:** the owner, each deploy (ruling 7). The release service's rule is `CLIVE_RELEASE_RULE=owner_waiver`. The code defaults stay as built: the service off, no rule, dry run on, until the install steps in [`RELEASE_SERVICE.md`](../RELEASE_SERVICE.md) set them as he ruled; dry run stays on until he switches it off himself.
- **How he approves:** on the Builds screen's **Deploy now** card, shown only when `clive/trunk`'s head is ahead of what CLIVE runs and acceptance is green on exactly that SHA, owner only. It names the version by its pull requests' own titles. His hold asks for his passkey for exactly that SHA, over a challenge CLIVE's server issues: a fresh nonce and the moments it was issued and expires, all inside what the passkey signs, held three minutes for the prompt, good once, and expiring ten minutes after the hold. When his hold cannot deploy it (the service not installed, off, not under `owner_waiver`, stopped, or the change one that stays a hand deploy), the card says why instead of offering it.
- **"At once":** CLIVE writes his approval into its own state folder, and a systemd path unit (`deploy/release/clive-release-now.path`) starts the release service the moment it lands. CLIVE never holds root and never starts a unit. The five-minute timer stays as the fallback.
- **The release service believes only the signature:** it checks his passkey's signature itself, for exactly the trunk's head, refuses an approval that has expired, and marks it used before a live deploy begins, so one hold starts one deploy at most. Every other condition is as DEC-067 built it.
- **Shown through to the end:** the service writes each stage on its status as it is reached (started, checks, installing, health, then done, rolled back with why, stopped part way, or refused with why), and CLIVE's card follows it. Once done, CLIVE's page on his device asks `/whoami` itself and hands its token over; the deploy is **kept** once CLIVE finds `whoami: id=<token> through=tailscale owner=true refusal=none` in its own journal, on the new build, as the procedure keeps a deploy.

**Reason:** his words above. The release service (DEC-067) and the passkey waiver's format already existed; this connects his hold to them, fixes the waiver's replay (the review of the release service, notes 10 and 11), and removes the timer's wait.

**Consequences:** decisions 3 and 6 of the self-shipping plan are settled: the release service deploys, and nothing ships without his gesture. The service's unit time limit is 4 hours, above the measured worst tick including a second look. A change to `deploy/`, the installer, the dependencies or `.github/` stays a hand deploy, and the first deploy that carries this is one. Not built: a push message to his phone for each outcome, and writing "kept" into the release service's public record (CLIVE keeps it in its own).

---

## DEC-076 — The loop's exact-SHA reviewer is Claude on the owner's plan; the Director and CLIVE get GitHub Apps of their own

**Date:** 2026-10-08
**Status:** ACTIVE. Built in the repository (`claude/n3-claude-reviewer`); in force on clive-worker-01 only through the owner-gated re-pin. The GitHub Apps take effect when the owner creates them ([`GITHUB_IDENTITY.md`](../GITHUB_IDENTITY.md)).
**Source:** the owner's rulings of 8 October 2026 (DEC-071), verbatim: ruling 10, "Replace the GPT reviewer with a Claude reviewer?" — "Y"; ruling 13, "Give the Director and CLIVE their own GitHub identity?" — "Y".

**Decision:**
- **Claude reviews every candidate in the loop by default.** `app/orchestrator/reviewers/claude.py` is the reviewer: the claude CLI on the owner's Max plan, never an API key. Its contract is the one GPT kept:
  - the same packet;
  - the same typed `clive.review_result.v1`, READY or CHANGES_REQUIRED with numbered findings;
  - bound to the exact SHA by the driver, never by the model;
  - the same repair loop and limits, and the same private stop reports;
  - one detached process per review, up to three runs, then the task blocks with the reason.
- **It is independent of the builder, by how it runs.** It is a principal of its own, `claude-reviewer`, registered in `config/review_principals.json` with the reviewer role only. The builder's principal `claude` still may not review. Each review gets:
  - a fresh session: its own id, nothing persisted, an empty HOME with no settings or memory;
  - a review room of its own: the candidate's whole tree written from git objects at the exact SHA, with links shown as notes and never followed, made read-only, and compared with the commit's blobs after the review;
  - only Read, Glob and Grep, under `dontAsk`.
  
  The launch is checked at the CLI's init event, as a builder's is. It is refused for any other tool, any MCP server, any plugin beyond the builtin allowance, any skill or command, any permission mode but `dontAsk`, or any API-key source. A room that changed, or a reviewer that used any other tool, voids the review: that is an error, never a verdict.
- **GPT stays selectable, so a re-pin can fall back.** Both loop scripts take `--reviewer claude|gpt` (and `engineering_dispatcher.py` still takes `relay`); `claude` is the default for a new pin. The reviewer not chosen never takes a new review. It is kept only to finish one it was given before the switch (`reviewers/choice.py`, `CollectOnly`). The GPT reviewer is kept for that only while the unit still names its key file.
- **The reviewer runs on the builders' token by default** (`--reviewer-token-file`, else `--worker-token-file`). The file must be 600, owned by the loop's user, and never hold an API key. `engineering_dispatcher.py probe-review` launches it as a review would and stops it at its init event; `--turn` lets it answer one tiny prompt on the token.
- **The Director and CLIVE each get a GitHub App.** George creates them. Both get contents write on `clive` only, pull requests, Actions read and Workflows. The Director needs Workflows to merge a workflow change (PR #108). CLIVE's App needs it because the loop's refresh merge can carry the trunk's own workflow change; the loop's protected-path checks still refuse any `.github` change a builder makes. Each key lives in a 600 file on its host, never in the repository. `scripts/github_app_token.py` mints an installation token narrowed to `clive` and the permissions named, and works as git's credential helper. The loop switches by configuration alone: git's credential helper in its clone, which the GitHub acceptance gate already asks. CLIVE's production filing (`app/engineering_bridge/github.py`) and the Director are recorded follow-ups, for the reasons in GITHUB_IDENTITY.md.

**Reason:** his rulings. On the reviewer: the loop's routine reviews were a second, pay-as-you-go bill (the OpenAI API), and his Max plan already runs the builders and CLIVE. On identity: today everything the loop and the Director do on GitHub is done as his account.

**Consequences:**
- **What the change gives up.** The review loses the second model family. `routing.py` has always recorded that diversity is never what eligibility rests on. The registry's note that "every Claude session on this host resolves to this one principal" still holds for the builder principal `claude`. `claude-reviewer` is separate by how it is launched and checked, not by its model.
- **The plan's limits.** Reviews and builders now share his plan's usage windows.
- **Untouched.** Nothing in the kernel, the gate, the GitHub acceptance gate or the dispatcher changed. The protected paths only grew.
- **Newly protected.** The new tests (`test_claude_reviewer.py`, `test_github_app_token.py`) and the token helper are protected paths.
- **The re-pin's own review stays GPT for now.** `root-repin.sh` on clive-worker-01 runs its own exact-SHA review of the loop's code through the OpenAI API. It lives outside the repository and is not changed here.
  - The re-pin that brings this in is reviewed by it as before, so the OpenAI key stays on clive-worker-01 for that script. Once the unit drops `--gpt-api-key-file`, the loop no longer reads the key.
  - **The owner's open call:** keep GPT for re-pin reviews only (a few a month), or move that review to Claude too. Moving it means bringing `root-repin.sh` into the repository, so the change to it is itself reviewed, and then swapping its review call.

---

## DEC-077 — CROOKS Returns rings CLIVE's public door for each event it records; CLIVE reads the return itself before it tells George

**Date:** 2026-10-08
**Status:** ACTIVE. Built on branches `claude/n3-returns-events` (CLIVE) and `claude/n3-service-events` (the service). Live once both are deployed and set up ([`docs/RETURNS_EVENTS.md`](../RETURNS_EVENTS.md)).
**Source:** the owner's ruling 20 of 8 October ([DEC-071](#dec-071--the-owners-rulings-of-8-october-43-questions-answered)): "Returns events reach CLIVE through that address?" (hooks.crooksldn.com, ruling 19) "Y".

**Decision:**
- **The service rings.** CROOKS Returns writes one outbox row for each event a return records, in the same transaction as the return. A thread of its own posts each row to `RETURNS_CLIVE_WEBHOOK_URL` (`https://hooks.crooksldn.com/hooks/returns`). The post carries the event's id, its type, the return's id, when it happened, and when it was sent, and nothing of the customer. It is signed with HMAC-SHA256 over the raw body. A post that does not get a 2xx is retried with backoff for a day. It is never on the request path and never fails the person acting. With no URL set, nothing is written and no thread starts. The service's old post of the whole return, which carried the customer's details and was never received, is gone.
- **CLIVE's door is as strict as the WeCom door.** `/hooks/returns` is on the same exact-path list (`app/routes/hooks.py` `HOOK_PATHS`) and carries no authority. It caps the body at 4 KB before reading it. It needs a stored secret and checks the signature in constant time before decoding the body. It accepts exactly the five fields, `sent_at` within five minutes, and an event id it has not seen. Anything else is an empty 403. The secret is stored on the Connections screen with the returns keys (`crooks_returns_hook_secret`). It is optional: without it CLIVE asks the service as before.
- **The doorbell, then the truth.** An event marks the open returns stale and reads them again through the API, so the home's row and the next returns card are fresh. If the event can make a return need George (one to approve, delivered back unchecked, a decision on one received, a label overdue or failed, money that did not move, an approval or cancel that failed), CLIVE reads that return. Only if that read says it needs him for that reason does the home show a notice that stays until he dismisses it. The notice names the order, never the customer, is shown once per device, and goes when the open returns say it is resolved.

**Reason:** his ruling. Polling once a minute only while someone is looking meant a return to approve, or a refund Shopify refused, waited until he next opened CLIVE and the minute had passed.

**Consequences:** no new authority and no change to any approval: an event can only make CLIVE read. Nothing customer-identifying is logged, on either side of the door. The notices live in memory, so after a restart the home's row still says what needs him, from the API. A phone push outside CLIVE is not built. Deploy order: CLIVE and the secret, then the public address, then the service. Shipping's events are not part of this.
