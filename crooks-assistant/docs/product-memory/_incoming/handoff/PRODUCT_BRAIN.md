# CROOKS OS — Product Brain

**Status:** canonical product vision  
**Owner intent:** durable until explicitly superseded  
**Last consolidated:** 2026-09-19

## 1. What CROOKS OS is

CROOKS OS is not intended to be another chatbot, another dashboard, or a thin wrapper around Claude/ChatGPT.

It is intended to become the **operating layer for running a business**: a persistent, connected system that understands the current state of the business, can reason over it, can act through controlled capabilities, can verify what actually happened, and can increasingly surface only the decisions and exceptions that need human attention.

The long-term value is not one specific model. Models are replaceable. The durable product is:

- business state,
- event history,
- permissions,
- capabilities,
- verified actions,
- automation,
- anticipation,
- interfaces,
- auditability,
- and the business-specific operating model around them.

## 2. Core product principles

### 2.1 Maximum capability, minimum visible UI

The system may be sophisticated underneath, but the user should see as little complexity as possible.

The ideal CROOKS interaction is often:

- one useful answer,
- one contextual card,
- one approval action,
- or nothing at all.

Avoid turning internal complexity into dashboards, settings, prompts, agent controls, workflow builders, or technical jargon unless absolutely necessary.

### 2.2 Human attention is the scarce resource

CROOKS should reduce how often an owner must manually inspect Shopify, Gmail, Stripe, fulfilment software, supplier messages, spreadsheets, analytics, and task lists.

Routine normality should disappear into the background.

The system should preferentially surface:

- exceptions,
- contradictions,
- overdue expectations,
- material changes,
- unresolved risks,
- meaningful opportunities,
- and decisions that genuinely require the owner.

### 2.3 The human becomes the exception handler

The target state is not “AI replaces the owner.”

It is:

> CROOKS handles observation, context gathering, routine coordination, safe execution, and verification; the owner handles judgement, taste, strategy, and high-risk exceptions.

### 2.4 CROOKS should feel like software, not prompt engineering

Subscribers and operators should not need to:

- design system prompts,
- configure MCPs,
- understand agents,
- create complex workflows,
- understand model routing,
- know how OAuth/systemd/Tailscale work,
- or manually assemble context for every request.

The target experience is:

> connect business → ask normally → approve important actions.

### 2.5 Persistent business state beats conversational memory

Important business facts and expectations must live in durable structured state, not only in model context.

Examples:

- customers,
- orders,
- products,
- production,
- suppliers,
- payments,
- shipments,
- issues,
- decisions,
- tasks,
- events,
- deadlines,
- and expectations.

A casual statement such as:

> “Jessica said the sample should take four weeks.”

should be capable of becoming a structured supplier/product/production expectation with a due date and future monitoring.

### 2.6 Models propose; the system executes

For consequential actions, CROOKS should preserve the existing safety direction:

1. model proposes,
2. server stores the exact immutable action,
3. user gesture authorises where required,
4. server re-reads preconditions,
5. server executes known deterministic capability,
6. server verifies against authoritative state,
7. only then is the action recorded as VERIFIED.

The model saying “done” is never sufficient evidence that something happened.

### 2.7 Autonomy is earned, not globally granted

CROOKS should not receive one blanket “fully autonomous” switch.

Autonomy should be narrow and evidence-based.

Example:

> “You approved this exact action class 31/31 times. Allow CROOKS to handle these automatically?”

Different action classes can have different autonomy levels based on:

- risk,
- reversibility,
- financial impact,
- user approval history,
- confidence,
- precondition certainty,
- and verification strength.

### 2.8 Event-driven over timer-driven where possible

CROOKS should react to business events rather than repeatedly poll everything on arbitrary schedules when better triggers exist.

Examples:

- Shopify order events,
- Stripe events,
- incoming email,
- WhatsApp messages,
- fulfilment/tracking events,
- supplier/production updates.

Scheduled checks remain appropriate for deadlines, reconciliation, and systems without useful event hooks.

### 2.9 Models are replaceable infrastructure

CROOKS should eventually have a Model Gateway so that:

- Claude can be primary where useful,
- other models can act as fallback or specialists,
- simple deterministic paths do not invoke AI unnecessarily,
- usage limits from one provider do not disable the business system,
- and subscribers do not need to care which model answered.

The business operating layer must outlive individual model vendors.

### 2.10 Self-improvement must be controlled

Self-improvement means:

> observe → diagnose → reproduce → build candidate → test → replay → review → deploy → monitor.

It does **not** mean:

> production AI edits production code directly and hopes.

Self-modification should use isolated branches/worktrees, objective tests, historical replay, independent review, and rollback.

### 2.11 Anything important must survive model memory loss

If an idea, decision, safety rule, or architectural principle matters, it belongs in versioned durable product memory.

ChatGPT/Claude memory is useful but is not the canonical store.

### 2.12 Continuity without ossification

Previous releases should accelerate the next release by preserving lessons, evidence, active contracts, useful capabilities, and safety invariants.

They must not become architectural gravity.

Preserve **outcomes and current intent**, not obsolete forms.

If a newer system fully subsumes an older component, that component may legitimately become null and be removed. If the product takes a new UI direction, old visual language is historical evidence rather than a permanent constraint. If an old test protects behaviour the product no longer wants, the contract should be deliberately superseded rather than preserved as archaeology.

Use `EVOLUTION_POLICY.md` for the canonical release/supersession rules.

### 2.13 Quality comes before model cost or elapsed time

Engineering orchestration should use the strongest appropriate intelligence and enough independent review to protect product/code quality.

Cost and speed may optimise waste, but they must not justify weaker architecture, weaker security, poorer UX, lower maintainability, or less reliable code.

Parallelism exists to increase quality and throughput only where isolation is real.

### 2.14 Engineering is multi-model by role, not one model pretending to be a company

The long-term engineering organisation should combine complementary specialists:

- GPT Director for decomposition, continuity and independent final review,
- Claude Opus for architecture, security, difficult diagnosis, major refactors and high-scrutiny review,
- Claude Sonnet for well-bounded implementation where quality is protected by proof/review,
- Fable as a first-class Experience Director for substantial UX/interaction direction and post-build experience review,
- specialist QA, performance, security and integration workers.

Model routing should be dynamic and quality-first. Difficult or ambiguous work escalates rather than being forced through a cheaper/faster worker.

## 3. Product architecture direction

### 3.1 Durable kernel

The durable core should include:

- identity/authentication,
- capability registry,
- proposal/action engine,
- verification,
- event ledger,
- business state,
- objectives,
- attention,
- automation,
- permissions,
- audit history,
- model gateway,
- and scene/presentation compilation.

### 3.2 World model

The CROOKS World should eventually represent linked entities such as:

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

The World should be updated by:

- integrations,
- user statements,
- actions,
- verified outcomes,
- deadlines,
- automations,
- and external events.

### 3.3 Event Ledger

Important state changes should be represented as append-only events where practical.

The event history supports:

- auditability,
- reconstruction,
- debugging,
- automation,
- anticipation,
- replay,
- and self-improvement analysis.

### 3.4 Objectives

CROOKS should eventually maintain persistent objectives such as:

- keep unresolved support issues below a threshold,
- ensure production milestones progress,
- prevent avoidable stock-outs,
- surface high-risk refunds,
- keep fulfilment exceptions controlled,
- maintain owner attention on the highest-value issues.

Objectives are more powerful than isolated reminders because they persist until satisfied or explicitly changed.

### 3.5 Attention

The Attention layer determines what deserves interruption.

The goal is not “show everything.”

The goal is:

> show what materially needs the human now.

### 3.6 Scene compiler

The interface should be generated from current context and objective.

Sometimes the correct scene is:

- conversational text,
- a customer card,
- an order card,
- one approval action,
- a production timeline,
- a warning,
- or no UI change.

Avoid static dashboard thinking where every metric must always be visible.

## 4. Product experience

### 4.1 Current near-term experience

Before major new architecture is added, the existing CROOKS experience must be made excellent:

- clean UI,
- correct entity focus,
- concise useful responses,
- low latency,
- stable voice,
- reliable media rendering,
- clear loading/error states,
- good Samsung layout,
- good iPhone layout,
- predictable actions,
- no obvious engineering rough edges.

### 4.2 Device model

Long term:

- **CROOKS Control** — Mac control/administration/development surface.
- **CROOKS Pad** — tablet-first operational interface.
- **CROOKS Phone** — mobile access, notifications, approvals, quick commands.
- Browser/PWA may remain a useful universal fallback.

All clients should talk to the same business state and runtime.

### 4.3 Voice

Voice should feel like a first-class control surface, not a novelty.

The system should improve:

- hold-to-talk / turn-taking,
- interruption,
- intent resolution,
- response length,
- audio latency,
- and context carry-over.

## 5. Integration philosophy

Integrations should become capabilities inside CROOKS rather than separate product silos.

Important planned integrations include:

- Shopify
- Gmail
- Stripe
- WhatsApp
- Royal Mail Click & Drop
- Resend
- Google Drive / Notes / documents
- supplier/production systems
- fulfilment systems
- Base44 apps and other internal tools

Each integration should have:

- least privilege,
- known scopes,
- clear read/write classification,
- deterministic execution where possible,
- verification,
- and audit history.

## 6. Anticipation

CROOKS should progressively move from:

> user asks → CROOKS answers

toward:

> business changes → CROOKS notices → updates its world → decides whether it matters → handles safe work → asks the owner only when necessary.

Examples:

- supplier milestone overdue,
- tracking stuck,
- unusual refund request,
- likely stock-out,
- important customer email,
- unresolved issue that should have progressed,
- sales anomaly,
- production delay.

Anticipation should be evidence-based and quiet by default.

## 7. Subscriber product thesis

The eventual commercial product is not “CROOKS London’s internal assistant.”

It is a configurable intelligent operating layer for ecommerce/small businesses.

Subscriber onboarding should eventually feel like:

1. create account,
2. connect Shopify,
3. connect business email,
4. connect payments/fulfilment,
5. CROOKS builds the initial business model,
6. start asking and operating normally.

The subscriber should not need to understand the underlying engineering.

The commercial differentiation is:

- persistent business context,
- business-specific workflows,
- verified actions,
- proactive exceptions,
- automation,
- one operating layer across multiple tools,
- and extreme ease of use.

## 8. Self-improving engineering thesis

CROOKS should eventually be capable of improving the software that runs CROOKS.

Evidence sources include:

- error logs,
- verbal/turn logs,
- screenshots/image logs,
- UI interaction logs,
- physical test sessions,
- proposal/action/verification history,
- user corrections,
- repeated questions,
- latency,
- abandoned screens,
- and regression outcomes.

The system may eventually operate as a small software organisation:

- Observer
- Triage
- Claude Dev Manager
- specialist workers
- specialist independent reviewers
- QA/replay
- integration
- GPT Director
- owner escalation

See `SELF_IMPROVEMENT.md`.

## 9. Non-negotiable safety direction

Preserve these invariants unless explicitly superseded after deliberate review:

- voice “yes” does not by itself authorise sensitive actions,
- action identity and arguments are stored server-side,
- proposals are bound to session/turn/TTL,
- risk is separate from execution disposition,
- writes are deterministic and known,
- unknown writes fail closed,
- preconditions are re-read before execution,
- success requires deterministic verification,
- no arbitrary HTML/JS execution,
- no service-worker write replay,
- no parallel/background writes without explicit architecture,
- least privilege,
- append-only PII-minimised action ledger where practical,
- Tailscale/private networking rather than public backend exposure by default.

## 10. What CROOKS should become

A good final description is:

> CROOKS OS is an intelligent operating layer that continuously understands the business, notices what matters, handles safe work, verifies what actually happened, and asks the owner only for decisions that genuinely need a human.

The measure of success is not “how clever does the AI sound?”

It is:

> how much owner attention can CROOKS remove without reducing control or trust?
