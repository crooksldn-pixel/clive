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

# Capture policy

New ideas should be appended with:
- ID,
- date,
- status,
- theme,
- concise intent,
- relevant constraints.

Do not delete ideas simply because they are deferred. Mark them.
