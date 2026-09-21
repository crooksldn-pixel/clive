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

**Consequences:** Future features should be challenged against whether they reduce human coordination/attention while preserving actual intention, authority and evidence. Deterministic fast paths remain valuable for genuinely explicit objectives, but keyword-triggered fixed outcomes must not substitute for contextual understanding. This decision does **not** alter DEC-046/047 sequencing, adopt any freeze candidate, authorise deployment, grant credentials/connectors, expand privileges or weaken action safety.\n---\n\n## DEC-052 — Preserve CLIVE's mission while making its mechanisms replaceable

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
