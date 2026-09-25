# CROOKS OS — Roadmap

**Last consolidated:** 2026-09-25 (finish-first rule and approved next phase added; stale statuses corrected with their earlier wording kept). Previously consolidated 2026-09-19.  
**Purpose:** keep sequencing explicit so ambitious ideas do not derail the current product.

This roadmap is intentionally staged. “Later” ideas should not be used as an excuse to leave the current product unfinished.

**Execution order as of 2026-09-25:** the section directly below (finish first, then the approved next phase) is authoritative. The final Sequencing rule and DEC-046 are kept as the 2026-09-19 history of how the order was reached; their safety gates still apply.

Was, 2026-09-19: "The final Sequencing rule and DEC-046 are authoritative for execution order. Engineering Orchestrator specification planning is active alongside N7; implementation waits until deployment, current-product quality and real-world evidence gates are satisfied."

---

# NOW — 2026-09-25: finish first, then the approved next phase

Production runs `clive/trunk` `ce791d03` (deployed 2026-09-25). The remote engineering loop builds everything, and work counts as finished only when it is in `clive/trunk` and the trunk passes full repository acceptance. See [CURRENT_TRUTH.md](./CURRENT_TRUTH.md).

## F0. Finish what is already started
**Status:** ACTIVE — owner rule, 2026-09-25

Finish everything already started before starting anything new. The finish list is [PROJECT_AUDIT_2026-09-24.md](./PROJECT_AUDIT_2026-09-24.md) §7 plus what 2026-09-25 added ([NEXT_PHASE_2026-09-25.md](./NEXT_PHASE_2026-09-25.md) §1):

- the trunk repair (red from PR #8 onwards; [EXTERNAL_REVIEW_2026-09-25.md](./EXTERNAL_REVIEW_2026-09-25.md) §1.1);
- the approved loop update ([OWNER_DECISIONS_2026-09-25.md](./OWNER_DECISIONS_2026-09-25.md)), in force through an owner-gated re-pin;
- deploy bundles, including the trunk work merged but not yet deployed: needs-reply routing, the microphone permission fix, the voice-credits wording and health, the remote-engineering journal-safe repair;
- Generative UI V1 objectives 2 to 4 ([GENERATIVE_UI_V1.md](./GENERATIVE_UI_V1.md));
- Build from CLIVE objective 2;
- the product-memory consolidation;
- the Mac loop;
- moving engineering off the production host once clive-worker-01 has proven itself.

## Approved next phase
**Status:** APPROVED by the owner on 2026-09-25; starts when F0 is clear. Order is binding.

### NP1. Eyes
Real-browser screenshots (Playwright CLI from the source shelf) of every user-interface and theme candidate, at phone and desktop sizes, as evidence for review and for the owner.

### NP2. Taste
Taste Skill and Vercel's web design guidelines, frozen at pinned versions, loaded as skills for builders doing interface work and turned into automatic review checks.

### NP3. The absorbing machine
Source Assimilation V1 ([SOURCE_ASSIMILATION_V1.md](./SOURCE_ASSIMILATION_V1.md)): quarantine, inventory, compare with what CLIVE has, propose objectives, measure, prove or drop. Steps 1 and 2 are done semi-manually first so the machine is designed from real cases.

### NP4. The rest of the shelf
[SOURCE_SHELF.md](./SOURCE_SHELF.md), pulled in only when a real need appears. New keys, data leaving the host and spend stay owner-gated.

The owner's image for this phase is agar.io: CLIVE grows by absorbing what it meets, and the game's own catch keeps it right: mass makes you slow. Absorb the useful part, not the whole repository; measure it; drop what does not earn its place.

**After the next phase (CAPTURED, not scheduled):** the Shopify theme built by the loop (IDEA-060) is proposed as the first new project. The other directions captured on 2026-09-24 and 2026-09-25 are IDEA-061 to IDEA-089.

**How the build system is judged (owner-agreed, IDEA-084):** hours from asking to seeing it on the phone, and minutes of the owner's attention per change. If the loop does not clearly beat asking a model directly on both, it is cut back to the one trunk, the tests and reviewed deploys.

---

# NOW — make the current CROOKS product genuinely reliable

## N1. Complete the always-on Linux deployment
**Status:** SHIPPED — production runs `clive/trunk` `ce791d03`, deployed 2026-09-25 after GitHub acceptance and an independent exact-SHA review with zero findings; Gmail OAuth provisioned 2026-09-24. Still open: Samsung verification; the Derek voice is unavailable on the server (ElevenLabs credits exhausted). The Mac is no longer a production or rollback host (OWNER_DECISIONS_2026-09-25).  
**Was (2026-09-19):** RUNNING / PARTIALLY VERIFIED — production state ratified at `1cf3a0f`; remaining Gmail/device verification open

- Linux migration candidate `1cf3a0f` reviewed and owner-ratified in production (DEC-048)
- provision remaining secrets safely — Gmail OAuth still outstanding; no new secret provisioning approved by DEC-048
- `crooks-assistant.service` installed/enabled/running and ratified
- private tailnet-only Tailscale HTTPS active and ratified
- verify reboot recovery
- verify Claude Max auth under systemd
- verify Shopify read path
- verify Gmail
- verify ElevenLabs Scribe
- verify Derek TTS
- keep writes disabled until the read/runtime layer is proven
- keep Mac deployment as rollback
- later move service from temporary root execution to a dedicated `crooks` user

## N2. Install and harden the Claude inbox watcher
**Status:** RETIRED 2026-09-25 — the remote engineering loop does its job (OWNER_DECISIONS_2026-09-24, DEC-058). The list below is kept as history.  
**Was:** SHIPPED / HARDENING

- standalone bridge and builder clones
- poll inbox blob SHA, not branch HEAD
- single-run lock
- failed instructions remain pending
- bounded backoff/retry for genuinely transient failures
- deterministic precondition/policy failures must evolve to explicit BLOCKED / ESCALATED state rather than repeated backoff
- worker workspace creation must not dirty the canonical Builder; prefer external `/opt/crooks-workers/<task>/<attempt>/` attempts over nested `.worktrees/`
- Claude Max auth preserved
- production checkout read-only to watcher
- watcher owns outbox publication
- stdin prompt delivery regression-tested
- corrected watcher passed end-to-end automatic smoke test
- 2026-09-19 incident proved the dirty-tree fail-closed guard works, but also exposed the need for workspace-aware placement and blocked-vs-transient failure classification
- no public webhook endpoint required
- normal GPT → Claude → outbox loop no longer requires the owner to relay messages

## N3. Perfect the current UI
**Status:** BUILDING — as Generative UI V1 (approved 2026-09-24; objective 1 of 4 in the trunk, 2 to 4 on the F0 finish list). Was: PLANNED

Primary focus after deployment.

- fix truncation/spacing/layout issues
- remove engineering-looking UI
- make mobile responsive
- Samsung refinement
- iPhone refinement
- better loading states
- better error states
- better media/image presentation
- cleaner action cards
- one contextual action where possible
- reduce unnecessary information density
- improve CROOKS Control from engineering utility to polished resizable app

## N4. Perfect response behaviour
**Status:** PLANNED — first fix, needs-reply routing, is merged to the trunk and not yet deployed

- concise by default
- better entity/customer/order focus
- fewer unnecessary clarifying questions
- better multi-turn context
- reduce repeated answers
- reduce hallucinated references
- lower model/tool latency
- improve voice turn-taking and interruptions
- improve “what actually matters” presentation

## N5. Real-world test sessions
**Status:** PLANNED

Use CROOKS normally and intentionally stress:

- Shopify queries
- Gmail
- customer/order lookup
- product questions
- voice
- images
- action proposals
- multi-turn context
- device switching

Capture:

- failures
- friction
- corrections
- latency
- abandoned interactions
- screenshots
- tool/action traces

## N6. Product-memory foundation
**Status:** BUILDING / ACTIVE — consolidated into `clive/trunk` on 2026-09-25 (the 2026-09-23 truth branch and the Opus 5.5 handoff merged with the 2026-09-24 and 2026-09-25 records)

- PRODUCT_BRAIN
- ROADMAP
- IDEAS
- FEATURES
- DECISIONS
- SELF_IMPROVEMENT
- CURRENT_TRUTH
- EVOLUTION_POLICY
- DIRECTOR_PROTOCOL

All future meaningful ideas and architecture decisions should become durable entries.

Active context must remain curated: Git stores history; current truth and active decisions drive new releases.

## N7. Permanent Builder Environment
**Status:** ACCEPTED at `295e483` on 2026-09-19 (see CURRENT_TRUTH history); loop builders now work in the remote engineering loop's own isolated workspaces. The text below is kept as history.  
**Was:** TESTING — published candidate requires corrections

Candidate `9a27bc441adad1e98e8a9ca257d1883246ee7eec` is published on `claude/builder-environment-review`. Independent review reproduced failures in bootstrap, environment validation and shell quoting; clean reconstruction remains incomplete. See [BUILDER_ENVIRONMENT_REVIEW.md](./BUILDER_ENVIRONMENT_REVIEW.md).

No project skills/rules/hooks were installed because the worker's native permission layer refused them. Preserve that boundary. Current bridge intake has moved to Mobile Experience V1; reconcile that unacknowledged round before sending foundation repair work. Candidate delivery does not mean the permanent environment gate is passed.

Required foundation outcomes:

- security-gated project skills,
- current DESIGN.md derived from CROOKS evidence,
- browser/Playwright/accessibility tooling,
- code-discovery/security/performance tools,
- concise CLAUDE.md/rules/hooks,
- DEV_ENVIRONMENT manifest,
- idempotent bootstrap/check,
- no production deployment as part of this task.

---

# AFTER CURRENT BASELINE — engineering organisation and controlled infrastructure

This foundation precedes major World/Attention/automation expansion. Detailed V1 mechanisms remain proposed until reviewed; this is not permission to start implementation during the current Builder/deployment sequence.

## D1. Claude Dev Manager
**Status:** CAPTURED

Takes broad engineering objectives and decomposes them into specialist tasks.

## D2. Specialist workers
**Status:** CAPTURED

Potential agents:

- UI Engineer
- UX Researcher
- Debugger
- Feature Engineer
- QA/Test Engineer
- Performance Engineer
- Security/Actions Reviewer
- Integration Engineer

## D3. Specialist critics
**Status:** CAPTURED

Each worker has an independent “voice of reason” reviewer.

Reviewer objective is to find why a change should **not** ship, not to agree by default.

## D4. Parallel isolated worktrees
**Status:** APPROVED DIRECTION

Each worker gets:

- own task
- own branch
- own worktree
- narrow tools/context

Never repeat the shared-working-tree collision experienced during Linux migration.

## D5. GPT Director
**Status:** CAPTURED

GPT sits above Claude manager/team as an independent architecture/review layer.

Reads:

- actual diffs
- tests
- replay results
- worker reports
- product memory

Can approve, reject, or send work back.

## D6. Owner escalation
**Status:** APPROVED DIRECTION

Agents should escalate decisions that are fundamentally product/taste/strategy questions.

The owner should not be used as a command courier.

## D7. Engineering Orchestrator V1
**Status:** RUNNING as the remote engineering loop — the frozen lifecycle kernel, Objective Intake + Engineering Dispatcher V1 and Remote Engineering Control V1, on three machines with builders on `claude-opus-5-5`. The runtime GPT Director is not implemented (IDEA-065). `engineering-team-activation-v1` is superseded by the remote loop.  
**Was:** IMPLEMENTATION AUTHORISED — harness preparation active; current-product/device/quality gates still precede major V1 implementation

Detailed proposal: [ENGINEERING_ORCHESTRATOR_V1.md](./ENGINEERING_ORCHESTRATOR_V1.md). Record/review/recovery contracts and the proposed first trial are in [DEV_TEAM_V1_PILOT.md](./DEV_TEAM_V1_PILOT.md). The owner has explicitly authorised V1 implementation under the existing canonical specification and safety boundaries. DEC-046's preceding deployment/current-product gates remain binding; unresolved mechanism choices still require the reviews described by the specification.

Build the layer above the single-worker watcher:

- task queue,
- quality-first model/effort selection,
- isolated worker workspace per task,
- safe parallel execution,
- dependency tracking,
- result/evidence collection,
- independent review routing,
- integration gate,
- bounded retries and escalation.

Do not obtain concurrency by allowing several writers into the same checkout.

## D8. Fable Experience Director
**Status:** APPROVED DIRECTION

Make Fable a first-class specialist for substantial UX/interaction work:

- pre-implementation experience direction,
- device/workflow evaluation,
- post-implementation independent experience review.

Fable complements DESIGN.md, browser evidence and technical review.

## D9. Quality-first model routing
**Status:** APPROVED DIRECTION

Routing should use:
- Opus for high-complexity/high-risk reasoning,
- Sonnet for bounded implementation,
- cheaper/faster models only for mechanical work,
- automatic escalation on ambiguity/failure/risk.

Cost and speed must not reduce code/product quality.

## D10. Privileged Action Broker + Deployment/Infrastructure Controller
**Status:** APPROVED DIRECTION

Bootstrap a controlled privileged plane so approved backend/infrastructure changes no longer require routine owner shell commands.

Requirements:
- allowlisted structured privileged actions,
- exact artifact/version identity,
- owner approval gates where needed,
- versioned installs,
- health checks,
- automatic rollback,
- separation of duties for self-updating infrastructure,
- SSH/Termius retained as break-glass recovery.

## D11. Active Context / release evolution automation
**Status:** APPROVED DIRECTION

Automate the memory procedures in DIRECTOR_PROTOCOL:

- bootstrap current truth,
- generate Active Context Packs,
- classify active vs historical/superseded constraints,
- supersede/retire obsolete architecture explicitly,
- audit memory drift,
- keep future releases free to simplify/delete obsolete systems while preserving current outcomes and lessons.

---

# CURRENT PRODUCT QUALITY — Live Experience V0.5 and evaluation foundation

This work may proceed in isolated repo-only branches while Orchestrator freeze convergence continues. It does not itself authorise production/runtime/connector changes.

> **2026-09-25:** Live Experience V0.5 is in production as part of `clive/trunk` `ce791d03`. The Orchestrator freeze stream was parked and then retired (OWNER_DECISIONS_2026-09-24); new work goes through the remote loop and the trunk.

## Q1. Retire Split as user-facing interaction
**Status:** V0.5 IN PRODUCTION (`ce791d03`); whether every user-facing Split entry point is gone is not recorded here. Was: BUILDING IN ISOLATED STREAM

Replace manual halves with one CLIVE session and independently progressing jobs. Preserve useful concurrency internals during migration where they still have a unique responsibility.

## Q2. Continuous voice/work state
**Status:** APPROVED DIRECTION

Create one explicit state authority from physical hold-to-speak through hearing, understanding, thinking, work, progressive result and response. Real-device evidence must exercise the microphone/STT path; post-transcription injection alone is insufficient.

## Q3. Progressive simultaneous jobs
**Status:** APPROVED DIRECTION

Render useful completed work immediately while slower dependencies continue. Support interruption, foreground context changes and adding background work without manual workspace management.

## Q4. Liquid-glass hierarchy refinement
**Status:** APPROVED DIRECTION

Continue the premium dark/liquid-glass direction while reducing dead space, permanent diagnostics and competing chrome. Visual state must communicate real system state.

## Q5. Continuous evaluation foundation
**Status:** APPROVED DIRECTION

Treat real sessions as privacy-minimised evaluation evidence. Add multidimensional independent evaluation, black-box/device testing, hidden/scenario-mutated cases, test mutation, long-session evidence and evaluator-drift controls.

## Q6. Typed scene compiler evolution
**Status:** APPROVED DIRECTION

Evolve from existing safe presentation primitives toward objective/evidence/device-driven scene composition. Do not permit arbitrary model-generated executable UI or weaken action contracts.

Detailed active doctrine: [CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md](./CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md).

---

# NEXT — make CROOKS proactive and operationally useful

## X1. Formal issue/improvement pipeline
**Status:** PLANNED

Convert telemetry into structured categories:

- bug
- UI friction
- UX friction
- bad response
- latency
- failed tool call
- wrong entity
- visual issue
- repeated owner correction
- automation opportunity

This becomes the engineering backlog.

## X2. CROOKS World / persistent business state
**Status:** APPROVED DIRECTION

Core entities:

- Person
- Customer
- Order
- Product
- Production
- Supplier
- Payment
- Shipment
- Issue
- Decision
- Task
- Event

Build durable relationships and provenance.

## X3. Event Ledger
**Status:** APPROVED DIRECTION

- append important events
- preserve source/provenance
- support debugging, audit, replay, anticipation, automation
- avoid relying on model memory for durable state

## X4. Expectations and deadlines
**Status:** APPROVED DIRECTION

Convert normal statements into structured expectations.

Example:
“Jessica said the sample takes four weeks.”

Becomes:

- supplier: Jessica
- related product/production item
- expected milestone
- due date
- source event
- escalation rule

## X5. Attention / “What needs me?”
**Status:** APPROVED DIRECTION

Core owner experience:

- surface exceptions
- suppress routine normality
- prioritise by urgency/materiality
- “What needs my attention?” should be first-class

## X6. Notifications
**Status:** PLANNED

Examples:

- supplier overdue
- refund approval required
- order stuck
- stock risk
- important support issue

Notifications should be selective, not noisy.

## X7. Automation/Objectives engine
**Status:** APPROVED DIRECTION

Support:

- scheduled
- event-driven
- conditional
- deadline-based
- stateful
- goal-based
- human-in-the-loop
- narrow autonomous actions

Natural-language authoring should be possible without exposing workflow-builder complexity.

## X8. Earned autonomy
**Status:** APPROVED DIRECTION

Track repeated approval patterns.

Example:
“You approved this exact class of action 31/31 times. Allow CROOKS to handle these automatically?”

Autonomy remains action-class-specific.

---

# NEXT — integrations that make CROOKS an operating layer

## I1. WhatsApp
**Status:** CAPTURED / HIGH VALUE

- ingest supplier/customer messages
- link messages to business entities
- use messages as event triggers
- draft replies
- approved sending
- supplier follow-up automation
- optional CROOKS control channel later

## I2. Royal Mail Click & Drop
**Status:** CAPTURED / HIGH VALUE

- create labels
- attach tracking
- monitor dispatch state
- detect label-created/not-dispatched mismatch
- track shipment progression
- surface stuck parcels
- verified fulfilment actions

## I3. Resend
**Status:** CAPTURED

Use as a clean transactional outbound-email layer for:

- operational notifications
- supplier/customer messages
- system reports
- controlled templates

Gmail remains useful for inbox/conversation ingestion.

## I4. Stripe
**Status:** PLANNED

- payment state
- refunds/charge context
- event triggers
- financial verification

## I5. Drive / Notes / business documents
**Status:** CAPTURED

- durable supplier/product docs
- decision context
- production notes
- linked document references

## I6. Base44/internal apps
**Status:** CAPTURED

Treat internal apps as capabilities/data sources inside CROOKS rather than isolated tools.

## I7. Broader fulfilment/supplier integrations
**Status:** CAPTURED

Use a capability graph so integrations do not become one-off hardcoded logic.

---

# LATER — make CROOKS model-independent and anticipatory

## L1. Model Gateway
**Status:** APPROVED DIRECTION

- Claude primary where appropriate
- fallback provider/model
- specialist model routing
- deterministic routes for non-AI work
- usage-limit resilience
- model vendor invisible to product/user

## L2. Anticipation engine
**Status:** APPROVED DIRECTION

Move from request-response to continuous business awareness.

Detect:

- overdue supplier milestones
- stuck fulfilment
- likely stock-outs
- unresolved customer problems
- important communications
- sales anomalies
- missing expected events

## L3. Objectives
**Status:** APPROVED DIRECTION

Persistent goals rather than isolated tasks.

Examples:

- keep support backlog controlled
- maintain production progress
- prevent avoidable stock-outs
- prevent overdue fulfilment exceptions
- surface high-risk refunds

## L4. Scene compiler
**Status:** APPROVED DIRECTION

Render the smallest useful interface based on current context/objective:

- text
- card
- timeline
- one action
- warning
- nothing

## L5. Multi-user/staff permissions
**Status:** CAPTURED

Potential roles:

- owner
- fulfilment
- customer service
- product development
- supplier-facing
- finance

All share the same World with scoped capabilities.

---

# LATER — controlled self-improvement

## S1. Nightly Observer
**Status:** APPROVED DIRECTION

Analyse:

- error logs
- turn/verbal logs
- image logs
- UI telemetry
- action ledger
- corrections
- latency
- abandoned interactions
- physical test sessions

Output evidence-backed issues, not speculative “improvements.”

## S2. Reproduction and replay
**Status:** APPROVED DIRECTION

Before changing code:

- reproduce issue
- freeze relevant evidence
- create regression fixture
- prove candidate improves the original failure

## S3. Builder environment
**Status:** APPROVED DIRECTION

- isolated worktree/branch
- never edit live production directly
- sanitised test/replay data
- full suite before promotion

## S4. Independent review
**Status:** APPROVED DIRECTION

Developer agent cannot be its own sole reviewer.

Reviewers should challenge:

- diagnosis
- necessity
- regression risk
- test quality
- changed expectations
- security implications

## S5. Morning improvement report
**Status:** CAPTURED

Example:

- interactions analysed
- issues detected
- issues reproduced
- fixes prepared
- fixes rejected
- candidates ready
- production changes made

Initially zero production auto-deploy.

## S6. Limited autonomous deployment
**Status:** SOMEDAY

Possible only for narrow, low-risk, objectively verified classes.

High-risk areas remain approval-gated:

- auth
- secrets
- refunds
- permissions
- Shopify write semantics
- action authorisation
- migrations

---

# SOMEDAY — CROOKS manages its own engineering

## Y1. Natural-language engineering requests
**Status:** CAPTURED

Example:
“That customer screen was bad — fix whatever caused it.”

CROOKS packages:

- screenshot
- verbal turn
- focused entity
- logs
- tool calls
- UI state
- source context

Then invokes Builder/Reviewer automatically.

## Y2. CROOKS-managed Claude Code
**Status:** CAPTURED

User no longer “uses Claude Code.”

Claude Code becomes an internal engineering worker.

Termius becomes emergency/admin access only.

## Y3. Automatic GPT ↔ Claude loop
**Status:** SHIPPED as the remote engineering loop (Claude builders, exact-SHA GPT review, bounded repair; see D7). Was: CAPTURED

- Claude completes
- GPT reviews
- GPT writes next instruction
- watcher launches Claude again
- repeat until gate or escalation

Hard stop conditions and max rounds required.

---

# SOMEDAY — subscriber product

## P1. CROOKS SaaS
**Status:** APPROVED DIRECTION

Configurable operating layer for ecommerce/small businesses.

## P2. Simple onboarding
**Status:** APPROVED DIRECTION

Target:

1. create account
2. connect Shopify
3. connect email
4. connect payments/fulfilment
5. CROOKS builds business model
6. use normally

No agent/MCP/prompt setup required.

## P3. Subscriber differentiation
**Status:** APPROVED DIRECTION

Sell:

- one intelligent business control centre
- persistent context
- proactive exceptions
- verified actions
- automation
- easy UI

Not:

- “another chatbot”
- “Claude with Shopify attached”

## P4. Multi-device commercial clients
**Status:** CAPTURED

- phone
- tablet
- desktop/control
- notifications
- role-based staff interfaces

---

# Sequencing rule

> **2026-09-25:** the numbered sequence below is history, superseded as the working order by "NOW — 2026-09-25: finish first, then the approved next phase" at the top of this file. Since it was written: production moved to `clive/trunk` `ce791d03` (2026-09-25); Gmail OAuth was provisioned (2026-09-24), closing step 3; the engineering organisation of step 10 exists as the remote engineering loop. Samsung verification (step 6) is still open. The rule in the next line and the safety gates still apply.

Do not jump to Later/Someday because the concept is exciting.

The current sequence, reaffirmed by the owner in the 2026-09-19 migration continuation (DEC-046), is:

1. finish and review the permanent Builder Environment,
2. **controlled Linux production migration/promotion — ratified complete at `1cf3a0f`,**
3. provision remaining runtime secrets through the approved process — Gmail OAuth outstanding,
4. **always-on server runtime — installed/enabled/running and ratified,**
5. **private tailnet-only Tailscale HTTPS — active and ratified,**
6. verify real Samsung/iPhone/runtime behaviour — iPhone observed; Samsung outstanding,
7. perfect current UI,
8. perfect response behaviour and latency,
9. conduct real-world CROOKS sessions and collect evidence,
10. implement Engineering Orchestrator / Dev Team V1,
11. bootstrap the privileged deployment/infrastructure control plane,
12. expand World / Event Ledger / Attention / expectations / automation / integrations.

Dev Team V1 implementation is owner-authorised, but execution remains sequenced after the preceding DEC-046 deployment/current-product gates. Planning and implementation preparation may proceed without treating that approval as a waiver of those gates.

This replaces the older footer that placed World/automation ahead of the engineering organisation. No active safety gate is removed.

At every stage, apply EVOLUTION_POLICY: inherit value and evidence, not obsolete implementation form.

The system should earn complexity only after the layer below it is reliable.
