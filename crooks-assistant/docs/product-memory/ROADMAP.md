# CROOKS OS — Roadmap

**Last consolidated:** 2026-09-25 (status lines corrected against production and the remote loop; the 2026-09-19 text is kept as history)  
**Purpose:** keep sequencing explicit so ambitious ideas do not derail the current product.

This roadmap is intentionally staged. “Later” ideas should not be used as an excuse to leave the current product unfinished.

The final Sequencing rule and DEC-046 are authoritative for execution order. Engineering Orchestrator specification planning is active alongside N7; implementation waits until deployment, current-product quality and real-world evidence gates are satisfied. *(2026-09-25: the order now in force is the finish order below; see the note under the Sequencing rule.)*

---

# Status as of 2026-09-25

**Production.** `/opt/crooks-os` runs `clive/trunk` at `ce791d03`, deployed on 2026-09-25 after GitHub acceptance and an independent exact-SHA review with zero findings. It includes:
- Live Experience V0.5;
- the mobile alpha;
- derived truth and attention V1;
- the mobile dogfood voice rules;
- the support investigator revisions;
- the judgment ledger CI stream and corrections;
- the age-days floor.

**Merged to the trunk, not yet deployed:**
- needs-reply routing;
- the microphone permission fix;
- the voice-credits wording and health;
- the remote-engineering journal-safe repair.

**Engineering.** The remote engineering loop runs on three machines, and all builders run `claude-opus-5-5`:
- the production host, with two builders;
- `clive-worker-01`, an HPE server with eight builders;
- the owner's Mac, which is being set up.

The owner's one-trunk rule (DEC-058) governs what counts as finished.

**Retired or superseded:**
- The bridge watcher was retired on 2026-09-25.
- `engineering-team-activation-v1` is superseded by the remote loop.

**Credentials and voice:**
- Gmail OAuth was provisioned on 2026-09-24.
- The Derek voice is unavailable on the server because the ElevenLabs credits are exhausted (FEAT-006).

**Finish order now in force.** Taken from [PROJECT_AUDIT_2026-09-24.md](./PROJECT_AUDIT_2026-09-24.md) §7, with completed steps removed:
1. Deploy the merged trunk items through an explicit trunk deploy.
2. Close gates:
   - the Support Investigator's live verification and the dogfood week;
   - Samsung verification;
   - a keep-or-retire decision for each unlanded stream.
3. Build what is agreed:
   - Generative UI V1 objectives 2 to 4;
   - Build from CLIVE objective 2;
   - response behaviour (interpretation);
   - the capability-gap bridge;
   - expectations and deadlines;
   - selective notifications;
   - then the Nightly Observer and morning report.
4. Give every other approved idea an explicit place in the order rather than leaving it silently approved.

Current state detail: [CURRENT_TRUTH.md](./CURRENT_TRUTH.md). Feature statuses: [FEATURES.md](./FEATURES.md).

---

# NOW — make the current CROOKS product genuinely reliable

## N1. Complete the always-on Linux deployment
**Status:** RUNNING — production runs `clive/trunk` at `ce791d03` (deployed 2026-09-25); Gmail OAuth provisioned 2026-09-24; Derek TTS unavailable on the server (ElevenLabs credits exhausted); Samsung verification open  
*History: RUNNING / PARTIALLY VERIFIED — production state ratified at `1cf3a0f`; remaining Gmail/device verification open.*

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
**Status:** RETIRED 2026-09-25 — the remote engineering loop does its job (DEC-058; FEATURES FEAT-013, FEAT-014, FEAT-063)  
*History: SHIPPED / HARDENING. The list below records what the watcher proved.*

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
**Status:** BUILDING — carried by Generative UI V1, approved 2026-09-24 ([GENERATIVE_UI_V1.md](./GENERATIVE_UI_V1.md)); the microphone permission fix is merged to the trunk, not yet deployed

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
**Status:** BUILDING — needs-reply routing (the 2026-09-24 “customers who need a reply” misreading) is merged to the trunk, not yet deployed; interpretation work remains

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
**Status:** PLANNED — the dogfood week and the Support Investigator's live verification are next in the finish order

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
**Status:** ACTIVE — consolidated into `clive/trunk` on 2026-09-25 (truth branch PM-01 to PM-04 and the Opus 5.5 handoff merged with the 2026-09-24 records)

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
**Status:** HISTORY — accepted at `295e483b` (see CURRENT_TRUTH); builders now run in the remote engineering loop's isolated workspaces  
*History: TESTING — published candidate requires corrections.*

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
**Status:** SUPERSEDED IN PRACTICE — the working path is Objective Intake + Engineering Dispatcher V1 around the frozen kernel, run by the remote engineering loop (FEAT-063); the GPT Director runtime above it is still not implemented  
*History: IMPLEMENTATION AUTHORISED — harness preparation active; current-product/device/quality gates still precede major V1 implementation.*

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

## Q1. Retire Split as user-facing interaction
**Status:** SHIPPED — Live Experience V0.5 is in production `ce791d03`  
*History: BUILDING IN ISOLATED STREAM.*

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
**Status:** APPROVED DIRECTION — V1 shipped as derived truth and attention V1 in production `ce791d03` (FEAT-061); the broader engine remains ahead

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
**Status:** APPROVED DIRECTION — Objective V0 is in production in the mobile alpha (FEAT-060); objectives do not yet act on their own between conversations

Persistent goals rather than isolated tasks.

Examples:

- keep support backlog controlled
- maintain production progress
- prevent avoidable stock-outs
- prevent overdue fulfilment exceptions
- surface high-risk refunds

## L4. Scene compiler
**Status:** APPROVED DIRECTION — now pursued as Generative UI V1 (FEAT-064)

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

*2026-09-25: this stage moved forward (RECONCILIATION_2026-09-23 §15). A bounded form of Y2 and Y3 now runs as the remote engineering loop. Owner objectives go into a bounded inbox, and Opus 5.5 builders work in isolated workspaces. Every candidate gets an exact-SHA GPT review and bounded repair, and work is finished only in the trunk. The loop has no deploy, secret or business-write authority.*

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
**Status:** BUILDING — repository-only form running in the remote engineering loop (FEAT-063)

User no longer “uses Claude Code.”

Claude Code becomes an internal engineering worker.

Termius becomes emergency/admin access only.

## Y3. Automatic GPT ↔ Claude loop
**Status:** SHIPPED (ENGINEERING LOOP) — realised by the remote engineering loop (FEAT-063, FEAT-044 superseded); the GPT Director runtime is still not implemented

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

**2026-09-25 note:** the list above is kept as the 2026-09-19 sequence.
- Items 2, 4 and 5 are done.
- Item 3 is done: Gmail OAuth was provisioned on 2026-09-24.
- Item 10 is realised as the dispatcher and remote engineering loop.
- Items 6 to 9 continue under the finish order at the top of this file.

The owner's one-trunk rule (DEC-058) now governs what counts as finished.

At every stage, apply EVOLUTION_POLICY: inherit value and evidence, not obsolete implementation form.

The system should earn complexity only after the layer below it is reliable.
