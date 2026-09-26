# CROOKS OS — Ideas Register

**Purpose:** preserve valuable ideas before they are forgotten.  
**Important:** CAPTURED does not mean “build now.”

Status vocabulary is defined in [README.md](./README.md).

---

## IDEA-001 — WhatsApp integration
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** integrations / communications

Use WhatsApp as a business data source and action channel.

Potential scope:
- ingest supplier/customer messages,
- link conversations to Customer/Supplier/Order/Product/Production,
- use messages as event triggers,
- draft replies,
- send approved replies,
- automate supplier follow-ups,
- optionally allow CROOKS control via WhatsApp later.

Key principle: WhatsApp should become part of the business World, not a disconnected chat transcript.

---

## IDEA-002 — Royal Mail Click & Drop integration
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** fulfilment

Integrate Click & Drop so CROOKS can:
- create labels,
- attach tracking to orders,
- detect label-created/not-dispatched mismatches,
- monitor shipment progression,
- detect stuck parcels,
- verify fulfilment actions against authoritative shipping state.

---

## IDEA-003 — Resend transactional email layer
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** communications

Use Resend for controlled outbound transactional/operational email while Gmail remains useful for inbox/conversation context.

Possible uses:
- supplier follow-ups,
- customer operational emails,
- system alerts,
- daily/weekly reports,
- reusable templates,
- internal CROOKS notifications.

---

## IDEA-004 — Business World graph
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** core architecture

Build durable linked entities:
- Person,
- Customer,
- Order,
- Product,
- Production,
- Supplier,
- Payment,
- Shipment,
- Issue,
- Decision,
- Task,
- Event.

Goal: CROOKS should reason over business state, not just chat history.

---

## IDEA-005 — Event Ledger
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** core architecture

Maintain a durable event history for:
- external changes,
- user statements,
- actions,
- verified outcomes,
- deadlines,
- expectations,
- corrections.

Supports audit, replay, debugging, automation, and self-improvement.

---

## IDEA-006 — Casual statement → structured expectation
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** anticipation

Example:
“Jessica said the sample should take four weeks.”

CROOKS should convert this into:
- supplier/person,
- related product/production object,
- expected milestone,
- expected date,
- evidence/source,
- future escalation.

---

## IDEA-007 — “What needs my attention?”
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** attention / UX

Make owner attention a first-class product surface.

CROOKS should answer from current business state and surface only meaningful exceptions, not a generic dashboard dump.

---

## IDEA-008 — Anticipation engine
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** proactive intelligence

CROOKS should notice missing/late/abnormal states without being asked.

Candidate detections:
- overdue supplier milestone,
- stuck tracking,
- likely stock-out,
- high-risk refund,
- unresolved support issue,
- important communication,
- sales anomaly,
- expected event that never happened.

---

## IDEA-009 — Persistent Objectives
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** automation / goals

Create durable goals such as:
- keep unresolved support below threshold,
- keep production milestones progressing,
- prevent avoidable stock-outs,
- surface high-risk refunds,
- control fulfilment exceptions.

Objectives persist until satisfied or changed.

---

## IDEA-010 — Natural-language automation authoring
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** automation

Allow the owner to describe operating rules normally.

Example:
“If a customer says their parcel hasn’t arrived, check tracking. If it’s still moving, draft a reassurance. If it hasn’t moved for five days, flag it. Never automatically refund.”

CROOKS converts the rule into durable triggers/conditions/actions/escalations without exposing a workflow builder.

---

## IDEA-011 — Earned autonomy
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** autonomy

Track repeated owner approvals for narrow action classes.

Example:
“You approved this exact class 31/31 times. Allow CROOKS to handle it automatically?”

Autonomy is never blanket/global.

---

## IDEA-012 — Model Gateway
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** model architecture

Prevent Claude quota/provider availability becoming a CROOKS outage.

Gateway should support:
- Claude primary,
- alternative provider/model fallback,
- specialist routing,
- deterministic non-model paths,
- future model swaps without rewriting business logic.

---

## IDEA-013 — Scene compiler
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** UI architecture

Render the smallest useful scene for the current context/objective.

Possible outputs:
- text,
- customer/order card,
- timeline,
- approval,
- warning,
- nothing.

Avoid defaulting to a static dashboard.

---

## IDEA-014 — Native CROOKS Phone
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** client

Move from responsive web/PWA to a polished phone client once the backend/product interaction is proven.

Focus:
- approvals,
- notifications,
- quick commands,
- voice,
- business attention.

---

## IDEA-015 — CROOKS Pad hardened shell
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** client

Evolve the Samsung experience into a purpose-built tablet shell / hardened WebView or native client.

---

## IDEA-016 — CROOKS Control as a proper Mac app
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** client / admin

Replace the current engineering-style menu utility with a polished resizable control surface.

Potential roles:
- system health,
- release/deployment,
- test sessions,
- improvements,
- logs,
- approvals,
- builder activity.

---

## IDEA-017 — Selective push notifications
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** attention

Push only material exceptions.

Examples:
- supplier sample overdue,
- refund needs approval,
- order stuck,
- stock risk,
- important support issue.

Avoid notification spam.

---

## IDEA-018 — Multi-user/staff roles
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** commercial / permissions

Different interfaces and permissions for:
- owner,
- fulfilment,
- customer service,
- product development,
- finance,
- supplier-facing work.

All share the same World and event history.

---

## IDEA-019 — Base44/internal app capability layer
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** integrations

Treat Base44 apps and other internal utilities as data/capability sources behind CROOKS rather than separate products the owner has to manually switch between.

---

## IDEA-020 — Drive / Notes / documents as linked context
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** knowledge

Link business documents to entities and decisions.

Examples:
- supplier specs,
- production notes,
- product docs,
- contracts,
- decision records.

---

## IDEA-021 — Long-running background jobs
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** server runtime

Always-on server should support jobs that outlive the client:
- historical order analysis,
- stock reconciliation,
- customer cohorts,
- production reconciliation,
- weekly reporting,
- large data processing.

---

## IDEA-022 — Nightly Observer
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** self-improvement

Analyse the day’s evidence:
- errors,
- voice/turn logs,
- screenshots,
- UI interactions,
- proposal/action ledger,
- corrections,
- latency,
- abandoned interactions.

Output evidence-backed engineering issues.

---

## IDEA-023 — Automated reproduction from logs
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** self-improvement

When CROOKS fails, reconstruct:
- spoken/user turn,
- focused entity,
- tool calls,
- server state,
- rendered scene,
- subsequent correction.

Produce a deterministic reproduction before editing code.

---

## IDEA-024 — Historical replay as an engineering gate
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** testing

Compare candidate behaviour against frozen historical interactions.

Goal:
- prove a fix solves the original issue,
- detect new regressions,
- prevent “tests pass because expectations were changed.”

---

## IDEA-025 — Morning improvement report
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** self-improvement / UX

Example report:

- 1,842 interactions analysed
- 7 possible issues found
- 4 reproduced
- 3 fixes produced
- 2 passed independent review
- 1 rejected
- 0 production changes without approval

---

## IDEA-026 — Limited autonomous low-risk fixes
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** self-improvement

Eventually allow narrow low-risk classes to deploy automatically after strong objective gates.

Possible candidates:
- harmless CSS/layout fixes,
- missing loading state,
- deterministic parser bug with frozen regression test.

Explicitly higher-risk:
- auth,
- secrets,
- refunds,
- write semantics,
- permissions,
- migrations,
- action authorisation.

---

## IDEA-027 — Claude Dev Manager
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** autonomous engineering

A manager agent receives a broad objective, decomposes it, assigns specialist tasks, reviews results, and prepares an integration candidate.

Manager should not simply write all code itself.

---

## IDEA-028 — Specialist engineering workers
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** autonomous engineering

Potential workers:
- UI Engineer,
- UX Researcher,
- Debugger,
- Feature Engineer,
- QA/Test Engineer,
- Performance Engineer,
- Security/Actions Reviewer,
- Integration Engineer.

Each receives narrow context/tools relevant to its speciality.

---

## IDEA-029 — Independent reviewer for every specialist
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** autonomous engineering

Every implementation layer gets its own “voice of reason.”

Reviewer instruction should be adversarial:
- find why the change should not ship,
- challenge diagnosis,
- challenge test quality,
- look for simpler fixes,
- look for untested regressions,
- detect tests being modified merely to accommodate a bad implementation.

---

## IDEA-030 — Dedicated worktree per worker
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** autonomous engineering / safety

Each agent gets:
- own branch,
- own worktree,
- own task,
- narrow authority.

Never allow parallel agents to share a mutable working tree.

This directly follows the duplicate-Claude collision during Linux migration.

---

## IDEA-031 — GPT Director
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** autonomous engineering

GPT sits above the Claude development hierarchy as an independent reviewer/architecture director.

It should inspect:
- actual diff,
- tests,
- replay,
- worker reports,
- product memory.

It can approve, reject, or send work back down.

---

## IDEA-032 — Automatic GPT ↔ Claude engineering loop
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** autonomous engineering

Event loop:
1. Claude finishes.
2. Outbox changes.
3. GPT reviewer inspects result.
4. GPT writes next inbox.
5. watcher launches Claude.
6. repeat until gate/owner escalation.

Requirements:
- hard maximum rounds,
- stop conditions,
- no implicit production approval.

---

## IDEA-033 — CROOKS manages Claude Code
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** autonomous engineering

Long-term user should not “use Claude Code.”

Example request:
“That customer screen was bad — fix whatever caused it.”

CROOKS packages evidence, invokes Builder, runs review/tests/replay, and returns a candidate.

Termius becomes emergency/admin access only.

---

## IDEA-034 — Engineering tasks generated from user correction
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** self-improvement

If owner says:
“No, I don’t need all that. Just show the order and whether it shipped.”

Capture structured feedback and later detect repeated UX patterns rather than relying on a static style prompt.

---

## IDEA-035 — Behavioural response-quality metrics
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** self-improvement

Measure:
- immediate re-ask,
- corrections,
- interruption,
- abandoned screen,
- offered action usage,
- response length before interruption,
- tool call that should have happened earlier,
- latency.

Use these as eval signals for prompt/routing/presentation changes.

---

## IDEA-036 — Product memory as canonical truth
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** governance

Use GitHub product-memory docs so valuable ideas/decisions survive:
- model changes,
- chat loss,
- memory compaction,
- time.

Agents must read relevant product memory before meaningful work.

---

## IDEA-037 — Subscriber CROOKS OS
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** commercial product

Turn CROOKS from one company’s operating system into a configurable product for ecommerce/small businesses.

The subscriber buys:
- one intelligent business control centre,
- persistent context,
- verified actions,
- proactive exceptions,
- automation,
- simple interfaces.

Not “another chatbot.”

---

## IDEA-038 — Extremely simple subscriber onboarding
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** commercial UX

Target:
1. create account,
2. connect Shopify,
3. connect email,
4. connect payments/fulfilment,
5. CROOKS builds initial model,
6. use normally.

Do not expose prompt engineering, agents, MCPs, or infrastructure.

---

## IDEA-039 — Subscriber-native ecommerce workflows
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** commercial differentiation

CROOKS should understand concepts such as:
- order,
- fulfilment,
- return,
- chargeback,
- inventory,
- supplier,
- production,
- campaign,
- support,
- cash.

This opinionated domain layer is a major advantage over generic AI chat.

---

## IDEA-040 — Contextual action UI instead of generic chat
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** UX

Example:
“Refund Jack’s order.”

Should be capable of becoming:
- resolved customer/order,
- amount/status/card,
- one approval control,

rather than instructions about how to use Shopify.

---

## IDEA-041 — One business state across every device
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** platform

Phone, tablet, Mac Control, web, and future channels should be views into the same server-owned World.

---

## IDEA-042 — Owner as product CEO, not command courier
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** operating model

The automation/dev hierarchy should escalate only:
- product taste,
- material architecture changes,
- high-risk actions,
- unresolved disagreement.

The owner should not shuttle messages between AI workers.

---

## IDEA-043 — Product memory auto-capture
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** governance

Eventually detect when the owner raises:
- a feature,
- product principle,
- integration,
- architecture idea,
- operating rule,

and automatically propose/capture a durable entry.

Do not automatically promote brainstorming to implementation.

---

## IDEA-044 — Periodic product-memory cleanup
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** governance

Periodically:
- merge duplicates,
- update statuses,
- mark superseded ideas,
- consolidate rationale,
- keep product memory useful rather than becoming another transcript archive.

---

## IDEA-045 — Skill/environment inventory
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** engineering environment

Track Claude Code skills, plugins, runtime tools, and environment-specific capabilities in durable versioned documentation so a future server migration does not depend on someone remembering which skills were installed.

---

## IDEA-046 — Private-first runtime
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** infrastructure

Default architecture:
- FastAPI loopback,
- Tailscale/private access,
- no unnecessary public endpoints,
- no public webhook exposure unless justified.

---

## IDEA-047 — Stable production + disposable builder
**Date:** 2026-09-19  
**Status:** APPROVED  
**Theme:** infrastructure / self-improvement

Production should become boring and stable.

Experimentation belongs in:
- builder worktrees,
- review branches,
- staging,
- replay environments.

Do not make production the development environment.

---

## IDEA-048 — Rollback-aware self-improvement
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** self-improvement

Every automatically promoted change should retain:
- previous known-good build,
- measured post-deploy health,
- rollback trigger,
- evidence linking rollback to regression.

---

## IDEA-049 — Attention-based morning brief
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** anticipation

Morning brief should answer:
“What changed overnight that affects what I should care about today?”

Not:
“Here is a generic summary of everything.”

---

## IDEA-050 — Capability graph
**Date:** 2026-09-19  
**Status:** CAPTURED  
**Theme:** architecture

Represent available capabilities, scopes, risk, reversibility, verification, and provider dependencies explicitly so automation and model routing can reason about what is possible without hard-coded one-off logic.

---

## IDEA-051 — Dev Team V1 deterministic contracts and recovery
**Date:** 2026-09-19  
**Status:** CAPTURED — detailed design proposal under the approved Dev Team direction  
**Theme:** engineering orchestration / verification

Detailed proposal: [ENGINEERING_ORCHESTRATOR_V1.md](./ENGINEERING_ORCHESTRATOR_V1.md).

Proposed mechanics:
- a small deterministic kernel with durable task/attempt/candidate/review records;
- curated, cited and versioned Active Context Packs;
- isolated worker credentials/state as well as source workspaces;
- immutable candidate/evidence identities and independent review;
- fencing/recovery that rejects stale worker results;
- publication retries that do not repeat successful builds;
- integration verification and an explicit external Director gate;
- bounded attempts and on-demand specialists rather than permanent manager layers.

Capture is not implementation approval. These mechanics need architecture/security review and verified Fable/GPT/credential adapters at the appropriate roadmap stage.

---


## IDEA-052 — Transitional Engineering Console
**Date:** 2026-09-19  
**Status:** CAPTURED — not implementation approval  
**Theme:** engineering UX / autonomy transition

Provide a very small private control surface while the watcher/orchestrator stack is still maturing so the owner does not need Termius for routine observation and bounded recovery.

The console should expose deterministic state and a tiny allow-listed action set rather than an arbitrary browser terminal. Candidate V1 surface:
- current worker/task, inbox SHA, last processed SHA, lock, failure/block reason and model/effort;
- Builder branch/HEAD/cleanliness and production HEAD/read-only health summary;
- latest Claude outbox and bounded watcher logs with one-tap copy/diagnostic report;
- refresh and, only where semantics are deterministic, retry/restart controls.

Constraints:
- private/Tailscale-only;
- no arbitrary shell input;
- no model-generated commands;
- no secrets, business writes, production deployment, Git reset/clean, account-level Claude settings or privilege expansion;
- actions map to reviewed server functions with explicit policy and audit evidence;
- do not build around defects that should instead be removed from the autonomous control plane.

Sequencing: finish the in-flight harness review, reconcile its repairs, then fix workspace-management and BLOCKED-vs-RETRY reliability before building this surface. If built, it should evolve into the Engineering Orchestrator control/approval view or be retired when it has no unique responsibility.

This is intentionally compatible with the autonomy goal: the number of controls the owner needs should decrease over time. The console is a transition/control surface, not a regression to manual operation.


## IDEA-053 — General work operating layer
**Date:** 2026-09-19  
**Status:** CAPTURED — long-term, not current implementation scope  
**Theme:** work orchestration / adaptive interfaces

Long-term, CLIVE may evolve beyond a business assistant into a general work operating layer that coordinates people, systems, devices and tasks from natural-language objectives.

Example:
“Split today’s order load evenly between workers X and Y, prepare each packing list, project them to Screen 1 and Screen 2, and prepare the corresponding order confirmations.”

CLIVE would reason across capabilities such as orders, workers, task queues, displays, printers, scanners, fulfilment and messaging, then create and verify the required workflow rather than requiring a dedicated hard-coded screen for every operation.

Core product implication:
- CLIVE should understand entities, state, people/roles, capabilities, rules, objectives, actions and verification;
- task-specific interfaces may be generated or selected for the current role/device/job rather than exposing a large permanent ERP-style UI;
- staff may increasingly interact with CLIVE as the coordination layer above existing business systems;
- the architecture should favour composable capabilities over an ever-growing catalogue of one-off workflows.

This is deliberately **later-stage direction**. Do not let it displace current reliability, product quality, harness hardening, runtime verification or Engineering Orchestrator sequencing. Preserve the idea without treating the current mechanism, UI shape or example workflow as fixed.

## IDEA-054 — One-session simultaneous work replaces Split
**Date:** 2026-09-20  
**Status:** APPROVED / BUILDING IN ISOLATED STREAM  
**Theme:** interaction model / concurrency

Retire the user-facing Split/Half/Merge/Close model. Preserve useful concurrency machinery internally, but represent simultaneous work as independently progressing jobs inside one CLIVE session.

The owner expresses objectives; CLIVE manages concurrency. A foreground interruption or new request must not require the owner to manually allocate the assistant's attention.

Detailed direction: [CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md](./CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md).

---

## IDEA-055 — Every session is an evaluation session
**Date:** 2026-09-20  
**Status:** APPROVED DIRECTION  
**Theme:** evaluation / self-improvement

Every real interaction should emit privacy-minimised evidence sufficient to evaluate understanding, latency, progressive work, scene choice, corrections, interruption, completion and failure.

Do not rely on naive same-model self-scoring. Use deterministic evidence plus independent evaluation and aggregate/reproduce patterns before changing the product.

---

## IDEA-056 — Adversarial product-test quality
**Date:** 2026-09-20  
**Status:** APPROVED DIRECTION  
**Theme:** testing / verification

Important product and safety gates should themselves be attacked.

Use a combination of:
- mutation testing of the test/gate;
- hidden scenarios;
- wording/state/order mutations;
- black-box device interaction;
- interruption and partial-failure sequences;
- long-session tests;
- frozen replay;
- blind baseline/candidate experience comparison where useful.

A green suite is evidence only to the extent that the suite has demonstrated it can catch plausible defects.

---

## IDEA-057 — Typed dynamic scene compiler
**Date:** 2026-09-20  
**Status:** APPROVED DIRECTION — incremental evolution, not arbitrary model UI code  
**Theme:** adaptive UI

Compose the smallest useful interface from typed safe primitives using objective, evidence, entities, device, urgency, job state and safe available actions.

The model may select semantic primitives but does not emit arbitrary trusted executable UI. Generated actions remain typed, authorised, staged/idempotent/verified as applicable.

---

## IDEA-058 — Liquid-glass CLIVE interaction material
**Date:** 2026-09-20  
**Status:** APPROVED DIRECTION  
**Theme:** visual design

Continue the premium dark/liquid-glass direction as a coherent material system:
- orb as living state object;
- restrained translucent grouping/depth;
- thin highlights/borders;
- reduced idle dead space;
- motion communicates state;
- content takes priority once useful work exists;
- reduced-motion/lite-device behaviour remains respected.

Do not use visual polish to disguise fragmented interaction state.

---

## IDEA-059 — Judgment Ledger and explicit proposal outcomes
**Date:** 2026-09-21  
**Status:** APPROVED DIRECTION — implementation requires action-safety review  
**Theme:** learning / autonomy / action UX

Add an explicit owner-judgment path for consequential proposals.

Required semantic outcomes:
- APPROVED;
- DECLINED;
- EDITED;
- DEFERRED;
- UNKNOWN/EXPIRED remains separate and does not count as disagreement.

The existing action ledger remains content-minimised and should not be repurposed as a rich learning log.

Create a separate redacted Judgment Event / Judgment Ledger linked to proposal identity and capable of preserving bounded reason codes, optional redacted explanation, edited replacement/delta and contextual provenance.

Use this evidence for:
- earned-autonomy denominators;
- correction-burden and usefulness metrics;
- recurring proposal-quality analysis;
- future business-policy learning;
- operational-twin adaptation.

UI should provide an explicit decline/edit/defer affordance; absence of a gesture must never be inferred as a negative judgment.

Do not enable production writes merely to implement this evidence layer. Production write enablement remains a separate owner-only gate.

---

Entries IDEA-060 to IDEA-089 are the directions and ideas captured in [NEXT_PHASE_2026-09-25.md](./NEXT_PHASE_2026-09-25.md) section 3, one entry per item, in that section's order. Source: the owner's messages and the Director's proposals in the 2026-09-24 and 2026-09-25 sessions. Each is CAPTURED unless marked otherwise.

---

## IDEA-060 — The Shopify theme built by the loop
**Date:** 2026-09-25  
**Status:** CAPTURED — proposed as the first new project after the next phase  
**Theme:** building other projects / storefront  
**Source:** NEXT_PHASE_2026-09-25 §3.1

The Crooks Shopify theme (Horizon 3.5.0) and its storefront roadmap (navigation, product page, homepage, lookbook, events, tracking and returns, Crack the Cuffs integration, performance pass) built through the engineering loop: Shopify theme checks, screenshots, independent review, pushed to an unpublished preview theme, published only on the owner's tap with the previous version one tap away.

Needs a theme access credential (owner step). Base44 apps do not fit this path because they are not in git (see IDEA-019).

---

## IDEA-061 — Automatic landing into the trunk
**Date:** 2026-09-25  
**Status:** CAPTURED  
**Theme:** loop throughput and autonomy  
**Source:** NEXT_PHASE_2026-09-25 §3.2

Land a candidate into `clive/trunk` automatically once its checks pass, the independent review is ready and GitHub acceptance is green on the exact SHA. Builds on the approved loop update (OWNER_DECISIONS_2026-09-25.md), which makes green acceptance a precondition for landing; this idea removes the manual step after it.

---

## IDEA-062 — Automatic follow-up and re-planning
**Date:** 2026-09-25  
**Status:** CAPTURED  
**Theme:** loop throughput and autonomy  
**Source:** NEXT_PHASE_2026-09-25 §3.2

When an objective lands, its dependent objective is queued; a blocked objective is re-planned with its reason instead of waiting for the Director. Extends the obvious-continuation rule (DEC-054, ENGINEERING_CONTROL_PLANE_VNEXT §8.2).

---

## IDEA-063 — Multi-loop router
**Date:** 2026-09-25  
**Status:** CAPTURED  
**Theme:** loop throughput and autonomy  
**Source:** NEXT_PHASE_2026-09-25 §3.2

A router that spreads objectives across the engineering loops (production host, clive-worker-01, the Mac) by each loop's published capacity.

---

## IDEA-064 — Automatic job splitter
**Date:** 2026-09-25  
**Status:** CAPTURED (owner idea)  
**Theme:** loop throughput and autonomy  
**Source:** NEXT_PHASE_2026-09-25 §3.2

When a candidate fails in several separate parts, split the repair into separate workers so each part is fixed faster and more specifically.

---

## IDEA-065 — Continuous Director
**Date:** 2026-09-25  
**Status:** CAPTURED  
**Theme:** loop throughput and autonomy  
**Source:** NEXT_PHASE_2026-09-25 §3.2

Today the Director acts only while the owner is in a chat, so finished work waits. Landing, requeuing and next-step queuing should not depend on that. Extends IDEA-031 (GPT Director) and the open runtime-Director gap recorded in OPUS_5_5_HANDOFF_2026-09-24 §13.

---

## IDEA-066 — Status projection publishes findings, failing checks and reports
**Date:** 2026-09-25  
**Status:** CAPTURED — objective `status-publishes-findings` parked under the finish-first rule  
**Theme:** loop throughput and autonomy  
**Source:** NEXT_PHASE_2026-09-25 §3.2

The loop's status projection publishes the open review findings, the failing check output and the worker reports, so the Director and the owner see why an objective is stuck without a shell. Extends DEC-055 (work-in-progress is observable state).

2026-09-26: still the direction (DRIFT_REVIEW_2026-09-26: the owner must stop being the courier). Loop update part 2 pins, as an interim guard, that the published status carries no findings text (`test_the_published_status_never_carries_review_findings_text`), because nothing yet bounds or redacts it. Building this idea means publishing findings, failing checks and reports with per-field caps and credential redaction, and replacing that test.

---

## IDEA-067 — Builders run their declared checks
**Date:** 2026-09-25  
**Status:** APPROVED — being built (part of the loop update in OWNER_DECISIONS_2026-09-25.md)  
**Theme:** builder efficiency  
**Source:** NEXT_PHASE_2026-09-25 §3.3; EXTERNAL_REVIEW_2026-09-25 §1.5

Builders may run their objective's declared checks in the loop's check sandbox (no credentials, no network, advisory only), so repairs are no longer blind.

---

## IDEA-068 — Match the model to the job class
**Date:** 2026-09-25  
**Status:** CAPTURED  
**Theme:** builder efficiency  
**Source:** NEXT_PHASE_2026-09-25 §3.3

Opus for design and hard problems, Sonnet for routine changes, Haiku for lint and wording. Extends DEC-041 and ROADMAP D9 (quality-first routing); DEC-040 still applies: cost never outranks quality.

---

## IDEA-069 — Repository maps and pre-warmed workspaces
**Date:** 2026-09-25  
**Status:** CAPTURED  
**Theme:** builder efficiency  
**Source:** NEXT_PHASE_2026-09-25 §3.3

Give builders repository maps so they do not rediscover the code each time, and pre-warm their workspaces.

---

## IDEA-070 — Scope lessons for whoever writes objectives
**Date:** 2026-09-25  
**Status:** CAPTURED  
**Theme:** builder efficiency  
**Source:** NEXT_PHASE_2026-09-25 §3.3; INFRASTRUCTURE_2026-09-25 lessons

An objective should include the tests and generators a change will obviously touch; remember that builders cannot delete files or run commands; declare only checks that are runnable inside the builder sandbox; use a new base commit only after the loop has fetched it.

---

## IDEA-071 — clive-worker-01 as the engineering host
**Date:** 2026-09-25  
**Status:** APPROVED (OWNER_DECISIONS_2026-09-25.md, engineering off the production host)  
**Theme:** local server roles  
**Source:** NEXT_PHASE_2026-09-25 §3.4

clive-worker-01 hosts the engineering loop, with builders' working copies in memory. Realises IDEA-047 (do not make production the development environment).

---

## IDEA-072 — clive-worker-01 as the proving ground
**Date:** 2026-09-25  
**Status:** CAPTURED  
**Theme:** local server roles / testing  
**Source:** NEXT_PHASE_2026-09-25 §3.4

Run the full suite in parallel on every candidate, clock-boundary sweeps (UK midnight, month end, clock changes), nightly mutation testing (IDEA-056), replay of real sessions (IDEA-024) and phone-screen screenshots.

---

## IDEA-073 — Preview stage: preview, then ship
**Date:** 2026-09-25  
**Status:** CAPTURED  
**Theme:** local server roles / release  
**Source:** NEXT_PHASE_2026-09-25 §3.4

Each finished objective runnable as a live CLIVE preview over Tailscale, behind a "preview, then ship" button.

---

## IDEA-074 — Field operations on the local server
**Date:** 2026-09-25  
**Status:** CAPTURED  
**Theme:** local server roles / capabilities  
**Source:** NEXT_PHASE_2026-09-25 §3.4

Browser agents for sites without APIs (courier tracking, supplier portals, marketplaces), the Nightly Observer (IDEA-022), and brand media processing such as TikTok edits.

---

## IDEA-075 — Business memory on the local server
**Date:** 2026-09-25  
**Status:** CAPTURED  
**Theme:** local server roles / knowledge  
**Source:** NEXT_PHASE_2026-09-25 §3.4

A local mirror of Shopify, Gmail metadata and analytics for instant answers, semantic search over the business's history, a local Whisper fallback for voice (see DEC-022) and encrypted off-site backups. Data leaving the host and new keys stay owner-gated.

---

## IDEA-076 — Builder capacity through the API or a Team plan
**Date:** 2026-09-25  
**Status:** CAPTURED — spend is owner-gated  
**Theme:** capacity  
**Source:** NEXT_PHASE_2026-09-25 §3.5

For many parallel builders, use the Claude API or a Team plan rather than stacked consumer subscriptions.

---

## IDEA-077 — Cloud-session credits for command-line and visual work
**Date:** 2026-09-25  
**Status:** CAPTURED — spend is owner-gated  
**Theme:** capacity  
**Source:** NEXT_PHASE_2026-09-25 §3.5

Use cloud-session credits for work that needs a command line or eyes, which loop builders do not have.

---

## IDEA-078 — Hybrid building
**Date:** 2026-09-25  
**Status:** CAPTURED  
**Theme:** ways of building  
**Source:** NEXT_PHASE_2026-09-25 §3.5

The loop for anything that must be correct and safe; a direct session with a browser for visual design, landing through the same checks and the same trunk.

---

## IDEA-079 — "What needs me today"
**Date:** 2026-09-25  
**Status:** CAPTURED — extends IDEA-007 and IDEA-049  
**Theme:** attention / Generative UI  
**Source:** NEXT_PHASE_2026-09-25 §3.6

At most three ranked items across orders, email and stock, then one quiet line saying everything else is on track.

---

## IDEA-080 — Stock run-out prediction
**Date:** 2026-09-25  
**Status:** CAPTURED — extends IDEA-008 (likely stock-out)  
**Theme:** anticipation  
**Source:** NEXT_PHASE_2026-09-25 §3.6

Predict stock run-out from sell-through rate, raise it as a risk, and offer a waitlist proposal.

---

## IDEA-081 — Courier tracking through the capability-gap bridge
**Date:** 2026-09-25  
**Status:** CAPTURED — extends IDEA-002  
**Theme:** fulfilment / capability gaps  
**Source:** NEXT_PHASE_2026-09-25 §3.6; GENERATIVE_UI_V1 §5

Courier tracking closes the shipping-evidence gap (fulfilment records alone do not prove movement), offered to the owner through the capability-gap bridge; the owner's step is the credential.

---

## IDEA-082 — Resend connection with a duplicate guard
**Date:** 2026-09-25  
**Status:** CAPTURED — extends IDEA-003  
**Theme:** communications  
**Source:** NEXT_PHASE_2026-09-25 §3.6

Read Resend delivery events and resend published templates such as `shipped-today`, with the `ship-email-sent` tag as the duplicate guard, a last-moment recheck and delivery verification. Sending remains a business write under the action gate.

---

## IDEA-083 — Every capability outage explained in plain words
**Date:** 2026-09-25  
**Status:** CAPTURED as a general principle — the voice-credits case is merged to the trunk, not yet deployed  
**Theme:** honesty / health  
**Source:** NEXT_PHASE_2026-09-25 §3.6

Every capability outage is explained to the owner in plain words with its cause and the owner's fix. Extends DEC-023 and the contextual-health rule of DEC-053.

---

## IDEA-084 — How the build system is judged
**Date:** 2026-09-25  
**Status:** APPROVED (owner-agreed 2026-09-25)  
**Theme:** engineering evaluation  
**Source:** NEXT_PHASE_2026-09-25 §3.7

Two measures: hours from asking to seeing it on the phone, and minutes of the owner's attention per change. If the loop does not clearly beat asking a model directly on both, it is cut back to the one trunk, the tests and reviewed deploys.

---

## IDEA-085 — One kernel for engineering and business work
**Date:** 2026-09-25  
**Status:** CAPTURED — parked until the finish list is clear  
**Theme:** architecture  
**Source:** NEXT_PHASE_2026-09-25 §3.8; EXTERNAL_REVIEW_2026-09-25 §2.1; RECONCILIATION_2026-09-23 §9

Replace the three separate propose → authorise → execute → verify engines (`app/actions`, `app/objectives`, `app/orchestrator`) with one kernel operating in both domains. First reversible step: a Support Investigator reply becomes a Gmail draft through the kernel, approved through the ledger and verified by reading the draft back.

---

## IDEA-086 — The Judgment Ledger as the record of the owner's authority
**Date:** 2026-09-25  
**Status:** CAPTURED — parked until the finish list is clear; extends IDEA-059 and DEC-056  
**Theme:** authority / learning  
**Source:** NEXT_PHASE_2026-09-25 §3.8; EXTERNAL_REVIEW_2026-09-25 §1.6

Owner decisions (baseline authorisations, retirements, deploy approvals, requeues) are written to the Judgment Ledger rather than living in commit messages and chat.

---

## IDEA-087 — A local SQLite store
**Date:** 2026-09-25  
**Status:** CAPTURED — parked until the finish list is clear  
**Theme:** architecture / storage  
**Source:** NEXT_PHASE_2026-09-25 §3.8; EXTERNAL_REVIEW_2026-09-25 §2.3; ENGINEERING_ORCHESTRATOR_V1 §4

A SQLite store on the host, arriving with the first business objective that runs through the kernel: privacy, crash safety, queryable ledger history. No free-form model query access; schema and migrations protected; encrypted backups with a tested restore. Not Supabase.

---

## IDEA-088 — The blind self-audit
**Date:** 2026-09-25  
**Status:** CAPTURED — parked until the finish list is clear  
**Theme:** self-knowledge / evaluation  
**Source:** NEXT_PHASE_2026-09-25 §3.8; EXTERNAL_REVIEW_2026-09-25 §2.2; CLIVE_SELF_KNOWLEDGE §3

A general retirement audit that never names components, with the owner's predictions sealed outside anything CLIVE reads (only their hash recorded), owner-chosen negative controls and scored timing. CLIVE proposes; the owner decides. Builders must not ask for, infer or store the sealed predictions.

---

## IDEA-089 — Harden the loop's service
**Date:** 2026-09-25  
**Status:** CAPTURED — parked; the protected-path part is covered by the approved loop update  
**Theme:** engineering safety  
**Source:** NEXT_PHASE_2026-09-25 §3.8; EXTERNAL_REVIEW_2026-09-25 §1.4

Confine the loop's service (strict filesystem protection with explicit write paths, no new privileges, private temp, ideally a non-root user). Any systemd or privilege change is an owner decision. Moving engineering off the production host (IDEA-071) is the stronger fix.

---

## IDEA-090 — Pin third-party instructions instead of fetching them live
**Date:** 2026-09-26  
**Status:** CAPTURED — found by the first digestions  
**Theme:** engineering safety, the absorbing machine  
**Source:** DIGESTIONS_2026-09-26.md (Vercel's interface guidelines)

CLIVE's `web-design-guidelines` skill fetches Vercel's `command.md` from its `main` branch at run time, before every review. That puts unpinned third-party text into an agent's context each time. The fix is the digester's own shape: take the guidelines in at a pinned commit (`e3d624ba`), absorb them as review checks with a removal handle, and let the watchlist propose updates when upstream changes.

---

## IDEA-091 — Provenance and an upstream watch for every vendored skill
**Date:** 2026-09-26  
**Status:** CAPTURED — found by the first digestions  
**Theme:** the absorbing machine  
**Source:** DIGESTIONS_2026-09-26.md (Taste Skill)

CLIVE's three taste skills are byte-identical to upstream `Leonxlnx/taste-skill` at `ce26fc25`, but carry no record of where they came from and nothing watches upstream. Each vendored skill should carry its Source (origin, pinned commit, licence) and be on the digester's watchlist, so an upstream change becomes a proposal rather than drift. Its redesign skill (for redesigning existing projects) is the one addition worth taking from that source, for the storefront work.

---

## IDEA-092 — Model-assisted relation for the digester
**Date:** 2026-09-26  
**Status:** CAPTURED — the digester's "Later" stage, now measured  
**Theme:** the absorbing machine, self-knowledge  
**Source:** KNOWLEDGE_DIGESTER_V1.md §9; the first self-digest

Relation today is deterministic word overlap. CLIVE's self-digest traces 21% of its code (512 of 2,458 code units) to a feature, idea or decision, and a module whose name shares no words with its feature is invisible. The next step is the model gateway: a model reads each unit with its neighbours and proposes the link, with its output provenance-tagged and treated as data. The traced share is the measure of success.

---

## IDEA-093 — The digester reconciles the feature register against the code
**Date:** 2026-09-26  
**Status:** CAPTURED  
**Theme:** self-knowledge, drift  
**Source:** the first self-digest (DIGESTIONS_2026-09-26.md §7)

Self mode found register entries that disagree with the code: FEAT-033 (anticipation engine) and FEAT-020 (event ledger) are PLANNED but have code in the tree, and FEAT-013 is SUPERSEDED but its code remains. Running self mode on every landing, and turning each disagreement into a proposed register correction or clean-up, would keep FEATURES.md true without anyone reconciling it by hand.

---

# Capture policy

New ideas should be appended with:
- ID,
- date,
- status,
- theme,
- concise intent,
- relevant constraints.

Do not delete ideas simply because they are deferred. Mark them.
