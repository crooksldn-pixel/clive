# CLIVE — Current Truth

**Purpose:** compact active context for GPT/Claude/Fable/engineering workers  
**Status:** ACTIVE — update whenever a material product/architecture state changes  
**As of:** 2026-09-25 (product-memory consolidation; earlier states from 2026-09-21 and 2026-09-23 are kept below as history)

This file is intentionally not a historical transcript. It answers: **what is true and important now?**

For historical rationale, use Git and DECISIONS.md. For release evolution rules, use EVOLUTION_POLICY.md.

## Now — 2026-09-25

Where anything further down this file disagrees with this section, this section is the current truth and the text below is history.

### Production

- `/opt/crooks-os` on the production host runs **`clive/trunk` `ce791d03`** (`ce791d032dcc8cf9b761ca40ce0b08a259c897a2`), deployed on 2026-09-25 after a green GitHub acceptance run on that exact SHA and an independent exact-SHA review with zero findings. Production deploys come from the trunk.
- It includes: CLIVE Live Experience V0.5; the mobile alpha (conversation, Objective V0 and the Support Investigator on the phone, [MOBILE_ALPHA.md](./MOBILE_ALPHA.md)); derived truth and attention V1; the mobile dogfood voice rules; the Support Investigator revisions; the judgment ledger CI stream and its corrections; and the age-days floor.
- **Merged to the trunk since, not yet deployed:** needs-reply routing, the microphone permission fix, the voice-credits wording and health, and the remote-engineering journal-safe repair. They reach production only through the next reviewed deploy from the trunk.
- **Gmail OAuth was provisioned on 2026-09-24** by the owner on the production host, outside every checkout, with unattended refresh verified ([OWNER_DECISIONS_2026-09-24.md](./OWNER_DECISIONS_2026-09-24.md)). CLIVE's writes remain governed by the existing action gate.
- **The Derek voice is unavailable on the server:** the ElevenLabs credits are exhausted, so FEAT-006 is not shipped there. Topping up the credits is spend, and therefore the owner's decision.
- Samsung verification is still outstanding.

### Engineering

- **The one-trunk rule governs what counts as finished:** work is finished only when it is in `clive/trunk` and the trunk passes full repository acceptance; an objective's own branch is a candidate, not the product ([OWNER_DECISIONS_2026-09-24.md](./OWNER_DECISIONS_2026-09-24.md), DEC-058).
- **The remote engineering loop** ([REMOTE_ENGINEERING_CONTROL_V1.md](./REMOTE_ENGINEERING_CONTROL_V1.md), [ENGINEERING_DISPATCHER_V1.md](./ENGINEERING_DISPATCHER_V1.md)) runs on three machines, all builders on `claude-opus-5-5`:
  - the production host, two builders;
  - `clive-worker-01`, an HPE server, eight builders;
  - the owner's Mac, being set up.
  Each loop has its own inbox and status branch under `clive/control/` ([INFRASTRUCTURE_2026-09-25.md](./INFRASTRUCTURE_2026-09-25.md)). Candidates pass declared checks and an independent exact-SHA review; the frozen lifecycle kernel `18c3153a` is unchanged.
- **Approved on 2026-09-25, not yet in force until the owner-gated re-pin:** the loop update (builders run declared checks in the check sandbox; acceptance and landing require a green GitHub acceptance run on the exact SHA; the product safety core, the evidence tools and the loop's own code join the protected paths), and moving engineering off the production host once clive-worker-01 has proven itself ([OWNER_DECISIONS_2026-09-25.md](./OWNER_DECISIONS_2026-09-25.md)).
- **Decided on 2026-09-26:** the loop's routine exact-SHA reviews run on `gpt-6-luna` at medium effort to cut OpenAI spend; the production deploy review stays on `gpt-6-sol` ([OWNER_DECISIONS_2026-09-26.md](./OWNER_DECISIONS_2026-09-26.md)).
- **Retired:** the bridge watcher on 2026-09-25 (its job is done by the remote loop); `engineering-team-activation-v1` is superseded by the remote loop; also the competing alpha fix `claude/release-secret-baseline-2026-09-24` and the ChatGPT orchestrator-freeze and control-plane-progress streams. The old hourly supervisor stays disabled and the unrestricted prose-freeze loop stays parked.
- The runtime GPT Director is still not implemented; the Director acts only while the owner is in a chat (IDEA-065).
- The trunk was red from PR #8 onwards on 2026-09-25 ([EXTERNAL_REVIEW_2026-09-25.md](./EXTERNAL_REVIEW_2026-09-25.md) §1.1); the trunk repair is on the finish list.

### Product memory

- Canonical product memory is this directory on `clive/trunk` (`crooks-assistant/docs/product-memory`). The truth branch (`claude/product-memory-truth-2026-09-23`, PM-01 to PM-04 on the 2026-09-23 reconciliation) and the Opus 5.5 handoff branch were consolidated into it on 2026-09-25; the older product-memory branches are history.
- The staging copies under `_incoming/` are left byte-identical to their sources for the Director to remove after this lands; they are not canonical and are not indexed.
- Builders read product memory from the trunk (part of the approved loop update).

### What comes next

1. **Finish first** (owner rule, 2026-09-25): finish everything already started before starting anything new. The finish list is [PROJECT_AUDIT_2026-09-24.md](./PROJECT_AUDIT_2026-09-24.md) §7 plus [NEXT_PHASE_2026-09-25.md](./NEXT_PHASE_2026-09-25.md) §1.
2. **Then the approved next phase:** eyes, taste, the absorbing machine, the rest of the shelf ([ROADMAP.md](./ROADMAP.md), "Approved next phase").
3. The build system is judged on two measures: hours from asking to seeing it on the phone, and minutes of the owner's attention per change (IDEA-084).

### Still the owner's

Deploying the merged-but-undeployed trunk work; the ElevenLabs credits; making the repository private; the loop re-pin and any systemd or privilege change to the loop's service; the first business-write trial (Gate B of [OWNER_DECISION_PACKET_2026-09-21.md](./OWNER_DECISION_PACKET_2026-09-21.md), undecided); any new credential, connector grant or spend.

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

General operational-state invariant learned from dogfood (RECONCILIATION_2026-09-23 §17):

`NEEDED/PROPOSED ≠ AUTHORISED ≠ STARTED ≠ COMPLETED ≠ VERIFIED`.

The same distinction applies to customer operations and engineering. CLIVE must not turn a proposed next step into a claimed action, an accepted candidate into a deployment, an assignment into active execution, or liveness into meaningful progress.

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

Full doctrine: [CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY.md](./CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY.md). The approved generative interface that applies it on screen: [GENERATIVE_UI_V1.md](./GENERATIVE_UI_V1.md). Why product memory exists at all: [CLIVE_SELF_KNOWLEDGE.md](./CLIVE_SELF_KNOWLEDGE.md).

### CLIVE identity and home surface — 2026-09-21

The user-facing product identity is **CLIVE — Computer Language Interface Virtual Environment**.

The home surface must not visually imply that CLIVE wakes empty and waits for a command. When relevant operational state exists, home projects the highest-value current objectives, changes, commitments, exceptions and unfinished work. A sparse/empty surface is valid when nothing earns attention.

The orb is CLIVE's presence/status object rather than merely a giant microphone button. Voice is one interaction path. Useful information may displace/reposition the orb when it deserves the space. Permanent provider/service status and fixed implementation-module navigation should not define the primary surface; health is contextual to the current objective and scenes are response/objective-driven.

Startup identity direction: point of light → abstract world/intelligence orb → C/L/I/V/E acronym reveal → CLIVE wordmark.

Full direction: [CLIVE_IDENTITY_AND_HOME_SURFACE.md](./CLIVE_IDENTITY_AND_HOME_SURFACE.md).

### Long-horizon adaptation doctrine

CLIVE must preserve its **mission and accumulated operational understanding without treating its current mechanisms as permanent**. Large organisations already exhibit distributed agency across people, software, rules, records and incentives; CLIVE's opportunity is to make more of that implicit organisational cognition explicit while reducing coordination cost and preserving human authority.

The capability frontier is permanently moving. There is no meaningful final 100% state. Models, APIs, interfaces, organisations and working patterns will change, so components should be expected to be replaced or deleted when superior mechanisms appear. Preserve durable semantics — objectives, identity, evidence/provenance, authority, time, commitments, capabilities, uncertainty, outcomes and verification — while keeping providers, frameworks, databases, orchestration, UI and connectors replaceable.

Core rule: **preserve accumulated understanding; make accumulated implementation expendable.** CLIVE should be able to consume technology that would otherwise obsolete its current implementation. Adaptability remains controlled: observed limitation → candidate change → isolated experiment → adversarial evaluation → independent review → controlled adoption.

Maturity principle: **no reasonable objective should leave CLIVE without a useful next move**, even when autonomous completion is impossible.

Full doctrine: [CLIVE_ADAPTATION_AND_ORGANISATIONAL_INTELLIGENCE.md](./CLIVE_ADAPTATION_AND_ORGANISATIONAL_INTELLIGENCE.md).

## Active Live Experience / evaluation direction — 2026-09-20

> **2026-09-25:** Live Experience V0.5 is now in production as part of `ce791d03`. The stream and head named in the second paragraph are history.

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

## Dev-team direction

> **2026-09-25:** the durable responsibilities below stand; RECONCILIATION_2026-09-23 §5 records that model names and worker roles are replaceable capabilities, not a fixed org chart. Today every loop builder runs on `claude-opus-5-5`.

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

# History — kept as written

Everything below records the state as it stood on 2026-09-19, 2026-09-21 and 2026-09-23. It is kept as evidence and rationale. It is **not** the current state: production, Gmail, the bridge watcher, where product memory lives and the order of work have all moved on (see "Now — 2026-09-25" above).

## 2026-09-23 reconciliation checkpoint

Read [RECONCILIATION_2026-09-23.md](./RECONCILIATION_2026-09-23.md) before making substantial engineering/control-plane changes.

The active reconciliation establishes these points without weakening older safety invariants:

- precedent is evidence and a presumption, not permanent implementation law; an old mechanism may be explicitly SUPERSEDED/RETIRED when its durable outcome, authority and safety responsibility are preserved or strengthened;
- CLIVE is one product: self-engineering is an internal capability/domain of the same persistent intent-to-execution system, not a separate end product;
- the authoritative engineering lifecycle write-side exists, survived the bounded Packet 14 repair sequence, and is frozen at `18c3153a2eec10c6343153b550776afed3bec2ba`; do not reopen speculative K-series hardening;
- Agent Environment is a projection/client of CLIVE records, never a second source of truth;
- direct objective ingress should write to CLIVE's persistent control plane; GPT/models sit beneath CLIVE as workers/directors, not as the permanent doorway;
- preserve engineering invariants, not a fixed provider/agent org chart; model names, worker roles, bridges, polling and UI mechanisms remain replaceable;
- the old hourly supervisor is disabled and the unrestricted prose-freeze/parser loop remains parked;
- the first real Crooks operational dogfood, read-only Customer Support Investigator V1, is COMPLETE in the engineering lifecycle at `2dbb97bc6c88d3ee3cf5cdf6a980df4f3405104a` (accepted and integrated 2026-09-23 11:11Z; the owner's verification of the two real cases, the first live run and any landing or deployment remain the owner's); the next engineering proof is Objective Intake + Engineering Dispatcher V1 so the owner can give CLIVE one objective once without acting as courier.

This checkpoint supersedes stale active-state claims in the 2026-09-19 migration handoff. Git retains that handoff as history.


### Post-kernel dogfood checkpoint — 2026-09-23

- Packet 14 READY was admitted; `control-plane-producers` r6 is COMPLETE and the repository-only lifecycle kernel is frozen at `18c3153a2eec10c6343153b550776afed3bec2ba`.
- Packet 10 candidate `b68e6e827afbeba3364c8239a2d814a60372f498` was fast-forward landed on the CI stream and acceptance run `35806286976` passed.
- Five recovery-era tasks are recorded COMPLETE; rejected/superseded revisions remain history rather than authority.
- No deployment, runtime, watcher, systemd, secret, permission or business-write authority followed from the kernel closure.
- The first post-kernel product dogfood is `support-investigator-v1`. Candidate `921375628d13ce338c659a7b789c11d8ac2b5f58` passed CI run `35810435777` and correctly identified two real Crooks cases, but exact-SHA review found one material customer-facing issue: deterministic drafts could claim internal follow-up was already underway without evidence. Revisions 3 to 5 repaired that bounded defect and its two directly reachable siblings (S-01, S-01R, S-01C); r5 candidate `2dbb97bc6c88d3ee3cf5cdf6a980df4f3405104a` was accepted (packet 18) and integrated on 2026-09-23 at 11:11Z. See [Engineering state — 2026-09-23 11:12Z](#engineering-state--2026-09-23-1112z) below.
- Treat that support repair as a one-round convergence exercise. Block only on material failures of customer/order identity, factual grounding, uncertainty, read-only authority, privacy or materially misleading output; stylistic/theoretical improvements go to backlog.
- The next engineering capability after Support Investigator closes is the minimum **Objective Intake + Engineering Dispatcher V1** around the frozen kernel: owner objective → worker launch → result/candidate ingestion → independent GPT review → bounded repair → integration → COMPLETE/OWNER_GATE. Do not redesign the kernel.
- The first no-courier test must be a small real product task with an external oracle, not a task to redesign the dispatcher itself.
- Agent Environment remains a read-only projection/client of authoritative CLIVE records. A private live preview is useful observability, not an authority source or a prerequisite to the no-courier milestone.
- Distinguish product-code capability from deployed runtime readiness: the real support cases were verified through authorised live Shopify/Gmail connectors, but CLIVE's own deployed connector credentials still require fresh verification before claiming end-to-end live support operation.


## Engineering state — 2026-09-23 11:12Z

Exact state after the closure of Support Investigator V1, as recorded on `clive/engineering-state` at `4e0194c9668c7d1193af3e5cbd0db6e9748e53ed`. Everything here is a record in that branch or a commit in this repository; nothing here is a deployment.

### Kernel tasks

| Task | State | Accepted SHA | Integrated into |
| --- | --- | --- | --- |
| `judgment-ledger-corrections` r3 | COMPLETE | `1958b3272e42a2608dfbd957ccf249c720af8332` | `claude/clive-recovery-handoff-pwuuse` |
| `agent-environment-truth-repairs` r1 | COMPLETE | `84e12e77e712…` | `claude/agent-environment-clive-state-2026-09-22` |
| `ci-age-days-floor` r1 | COMPLETE | `ef3d08ff9fc5…` | `claude/ci-age-days-floor-2026-09-22` |
| `control-plane-producers` r6 | COMPLETE (the kernel, frozen) | `18c3153a2eec10c6343153b550776afed3bec2ba` | `claude/control-plane-producers-2026-09-22` |
| `judgment-ledger-ci-stream-integration` r1 | COMPLETE | `b68e6e827afbeba3364c8239a2d814a60372f498` | `claude/ci-stream-integration-judgment-2026-09-22`, then landed by fast-forward on `claude/ci-provenance-acceptance-2026-09-22` (run `35806286976` green) |
| `support-investigator-v1` r5 | COMPLETE | `2dbb97bc6c88d3ee3cf5cdf6a980df4f3405104a` | `claude/support-investigator-v1-2026-09-23` |

Revisions r1–r5 of `control-plane-producers`, r1–r2 of `judgment-ledger-corrections` and r1–r4 of `support-investigator-v1` are OBSOLETE, each superseded by the next revision; rejected candidates stay in history and never become authority.

### Support Investigator V1 (read-only), as accepted

- One customer enquiry about an existing order → the order identified only where the evidence supports it → an evidence bundle read through the application's own read tools (order, fulfilment, tracking, note, events, customer history, up to three inbox threads, the knowledge-base policy lines verbatim) → verified facts, reasonable inference and unknowns kept apart and cited → a reply draft that requires the owner's approval. Entry points: `POST /support/investigate` and `scripts/support_investigate.py` (which engages the process-wide read-only latch before it builds a client). Nothing in it can send, refund, cancel, alter an order, a fulfilment, tracking or a note.
- Review history: packet 15 (S-01: drafts claimed internal actions were underway), packet 16 (S-01R: an untracked fulfilment was called dispatched), packet 17 (S-01C: cancel/address-change paths equated a fulfilment record with dispatch), packet 18 READY. The rule that closed them: a draft states verified facts, uncertainty, what still needs doing, asks and policy-backed statements only; "dispatched" only for a status that records movement; never an action that the evidence does not prove.
- The acceptance oracle was two real Crooks cases captured read-only (a delivery enquiry on a label-only international fulfilment; a return enquiry on an order with an open return), replayed through the same code; GPT verified both against the live sources. The raw captures never entered the repository, a packet or the kernel store; the engineering evidence is redacted.
- Still to happen, all owner decisions: the owner's own verification of the two cases and any sending of the replies by hand from the mailbox; the first live run on the Mac under the read-only latch; landing on the CI stream; deployment. The product-memory document is `SUPPORT_INVESTIGATOR_V1.md` on `claude/support-investigator-v1-2026-09-23` (not on this branch); its status stays TESTING until something is deployed and verified.

### Capability gaps recorded by the dogfood

- No carrier tracking is integrated (Easyship is not connected), so where a parcel is stays an explicit unknown and a fulfilment status is read as Shopify's recorded status, not as carrier knowledge.
- The engineering container holds no CLIVE credential; the live adapters were exercised against a fake store and their unavailable path. Product-code capability is not deployed-runtime readiness.
- Drafting is deterministic; no model is in the loop.

### Where the documents are

Product memory is split across branches until reconciled: this file and the 2026-09-23 reconciliation on `chatgpt/product-memory-reconcile-2026-09-23`; `ENGINEERING_LIFECYCLE_PRODUCERS.md` on the kernel branch at `18c3153a`; `SUPPORT_INVESTIGATOR_V1.md` on `claude/support-investigator-v1-2026-09-23`; `JUDGMENT_LEDGER_CONTRACT.md` and `REVIEW_ACCEPTANCE_CONTRACT.md` on the CI stream at `b68e6e82`. The updated repository README carries the branch map on the branches where this documentation update has landed (`claude/repository-readme-2026-09-23`, based on the default branch, and `claude/product-memory-truth-2026-09-23`); every other branch, including the CI stream, the kernel branch and the support branch, still carries the older theme-only README until the owner lands the update there.

### Backlog recorded by this documentation round

- `scripts/product_memory_check.py` (on the CI stream) checks document structure only; it does not check that feature identifiers in `FEATURES.md` are unique. Packet 19's PM-01 (five rows added under identifiers already in use) was caught by review, not by the gate. Adding that assertion is a small code change for a later bounded task, not part of this documentation update.

### Not authorised by any of the above

Landing on the CI stream, production deployment, runtime, service, watcher or systemd changes, external customer sends, Shopify or Gmail writes, secret or permission changes. The operational-state invariant from the dogfood applies to this list: `NEEDED/PROPOSED ≠ AUTHORISED ≠ STARTED ≠ COMPLETED ≠ VERIFIED`.

### Next engineering capability

Unchanged from the reconciliation (§16): the minimum Objective Intake + Engineering Dispatcher V1 around the frozen kernel, started only on an owner objective; the kernel stays frozen unless dogfood demonstrates a core-invariant failure.

## Engineering control plane

> **2026-09-25:** history. Production is now `ce791d03`, not `1cf3a0f3`; Gmail OAuth was provisioned on 2026-09-24; the bridge watcher was retired on 2026-09-25 and its job is done by the remote engineering loop; canonical product memory lives on `clive/trunk`. See "Now — 2026-09-25".

- Canonical repository: `crooksldn-pixel/clive`.
- Repository rename: `crooksldn-pixel/Shopify-theme` was renamed to `crooksldn-pixel/clive` on 2026-09-19. This is a repository identity/naming migration only; branches, commit history, safety decisions and product semantics are unchanged. **Repository rename completed operationally:** the active server checkouts (`/opt/crooks-interactive`, `/opt/crooks-ai-bridge`, `/opt/crooks-builder`, `/opt/crooks-os`) now use `https://github.com/crooksldn-pixel/clive.git`; the installed watcher default repo slug is `crooksldn-pixel/clive`, the watcher restarted healthy (`pending no`, `failures 0`, `lock free`, service active), and a read-only grep found no active old repo references outside Git history.
- Canonical product memory currently lives on `claude/product-memory-foundation`; read it by explicit ref. The default theme branch is not the CROOKS product-memory source.
- **Linux production is ratified at exact candidate `1cf3a0f3361b79f9de208d80f501543c53c244b5` (DEC-048).** Independent read-only reconciliation observed `/opt/crooks-os` clean and byte-identical to that candidate, `crooks-assistant.service` installed/enabled/active on `127.0.0.1:8000`, and tailnet-only Tailscale HTTPS. The owner explicitly ratified that already-performed state on 2026-09-19. This does not authorise another deployment, new secrets, broader privileges, public/Funnel exposure, or CROOKS writes.
- The GitHub communication bridge uses orphan branch `crooks-ai-bridge`.
- The CROOKS bridge watcher is installed and enabled. Reviewed source revision `5ada7b47f13547f107be1f53beeb79021cc48c24` pins the installer's runtime to `claude-fable-5-1` at `high` effort, and the corrected installer upgrade-order regression suite passed `126 passed, 0 failed`; but the most recent verified live probe, a read-only live-host review on 2026-09-23 reported in the packet-20 review verdict relayed by the owner, found the loaded systemd unit (no drop-ins) carrying `Environment=CROOKS_BRIDGE_CLAUDE_MODEL=claude-opus-5`. Runtime truth comes from such probes, not from this document: the model and effort actually in force are whatever the most recent probe shows, and the discrepancy between the reviewed source and the loaded unit is itself an open observation, not resolved here. A real unattended post-install smoke round consumed inbox blob `5d659fbc9418f378a10ddc5666e79ffc5b94ae7c`, published a new outbox, made no application/infrastructure/production changes, and returned the watcher to `pending no`, `failures 0`, `lock free`. The single-worker bridge's model/effort baseline is therefore whatever the latest probe establishes, not what the reviewed source states; future Engineering Orchestrator routing remains task-specific rather than permanently fixed to any one model.
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
- **Harness repair candidate published:** `claude/harness-hooks-experiment` now points to exact candidate `d7911b24979be2306749b7333ec60edc28cba857`, one commit on top of rejected `dd50ebbca6eca9c4e2ee1e85ad17d2c7e5afd25e`. Implementer evidence reports 181 new repair tests passing, targeted 568 passed/2 skipped, full offline 3374 passed/10 skipped, Ruff clean, range gitleaks 0, clean worktree, and no production/account/connector/service mutation. This is **not accepted**: it now requires a fresh independent adversarial review bound to `d7911b2…`. A stale Builder fetch refspec for deleted `claude/bridge-builder` still makes `git fetch --all` fail; the implementer worked around it with explicit branch fetches. Do not treat that local refspec problem as fixed.

## Near-term order of 2026-09-19/21

> **2026-09-23 note:** this ordering is the 2026-09-19/21 list, kept as written. Items 2, 4 and 5 are done as marked; the Builder/harness items are historical scaffolding under §6 of the reconciliation; the current sequencing after the kernel closure is §15–§16 of [RECONCILIATION_2026-09-23.md](./RECONCILIATION_2026-09-23.md) and the engineering-state section above.
>
> **2026-09-25 note:** superseded again by "What comes next" in "Now — 2026-09-25" (finish first, then the approved next phase). Item 3's Gmail OAuth was provisioned on 2026-09-24; item 10's engineering organisation now exists as the remote engineering loop.

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
