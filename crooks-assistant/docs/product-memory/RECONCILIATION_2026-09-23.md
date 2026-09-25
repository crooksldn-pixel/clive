# CLIVE Reconciliation — 2026-09-23

> **Consolidation note — 2026-09-25 (the checkpoint below is kept as written):** the doctrine here stays active: the precedent rule (§1), one product (§2), the self-referential convergence rule (§12) and the state invariant (§17). The engineering and release state it describes is history. The Objective Intake + Engineering Dispatcher of §16 was built and the remote engineering loop now runs on three machines; V0.5 and the Support Investigator revisions are in production; the one-trunk rule now decides what counts as finished. For what is live now, read `CURRENT_TRUTH.md`.

**Status:** ACTIVE CONTEXT RECONCILIATION  
**Purpose:** reconcile the 2026-09-21→2026-09-23 engineering/product discussion with canonical product memory without turning old implementation precedent into permanent doctrine.

This document is an Active Context checkpoint. It does not replace `PRODUCT_BRAIN.md`, `CURRENT_TRUTH.md`, `EVOLUTION_POLICY.md`, `SELF_IMPROVEMENT.md` or active decisions. Where this document identifies an older mechanism as superseded or implementation-specific, the durable outcome/safety constraint remains unless explicitly retired.

## 1. The precedent rule

CLIVE should respect precedent without becoming trapped by it.

Use this order when old and new directions appear to conflict:

1. **Current explicit owner intent.**
2. **Active safety/security/authority invariants.**
3. **Durable product semantics and outcomes.**
4. **Current canonical decisions and verified evidence.**
5. **Historical precedent and implementation history.**

Historical precedent is a **presumption and source of evidence, not a constitutional ban on change**.

A worker may not silently reverse an active decision. But an old mechanism may be explicitly **SUPERSEDED** or **RETIRED** when:
- its required outcome is preserved elsewhere,
- its safety/authority responsibility is preserved or strengthened,
- migration/recovery obligations are accounted for,
- the replacement is evidenced rather than merely asserted,
- and the old component no longer has a unique responsibility.

A component becoming null is a legitimate improvement.

When changing precedent, record four things:
- what old rule/mechanism is being changed,
- what durable purpose it served,
- how the new mechanism preserves or improves that purpose,
- what evidence makes the old form safe to retire.

This is the practical meaning of the existing rule:

> **Preserve accumulated understanding; make accumulated implementation expendable.**

## 2. Product convergence: CLIVE is one product

The engineering system is not a separate end product from CLIVE.

The converged model is:

```
CLIVE
├── persistent objectives / world state / memory
├── authority / permissions / evidence / verification
├── business capabilities
├── human and software coordination
└── self-engineering capability
    ├── task creation
    ├── worker routing
    ├── isolated execution
    ├── candidate identity
    ├── independent review
    ├── repair
    ├── integration
    └── controlled capability evolution
```

Engineering is one domain CLIVE can operate in. Commerce, customer support, fulfilment, product development and other operational work are other domains.

Therefore the long-run product is not "CLIVE plus a builder". The builder/control plane is an internal organ of CLIVE.

What does **not** converge is authority. Self-building must not become self-authorising.

CLIVE may identify a capability gap, create an engineering objective, commission work, evaluate it, route independent review and propose adoption. It may only cross deployment/privilege/business-write/owner-decision boundaries according to the authority policy for that class.

## 3. Current engineering state

The missing authoritative write-side identified by Objective E now exists as a repository-only engineering lifecycle kernel.

The implemented record model now covers:

`task → assignment → attempt/lease/fencing → acknowledgement/progress/evidence → immutable candidate SHA → independent review dispatch → exact-SHA verdict → rejection/repair or acceptance → verified integration → COMPLETE`.

Agent Environment can render those lifecycle records. Probe/process/git observations are reconciliation evidence; they are not the authoritative source of task state.

This is materially different from the earlier observation-only state.

### Verified lifecycle progress

Recent real work has been placed through the kernel rather than represented only as prose:

- Judgment Ledger J-02 repair `1958b3272e42a2608dfbd957ccf249c720af8332` — independently reviewed READY and recorded/integrated COMPLETE on its declared handoff branch.
- Agent Environment truth repair CLIVE `84e12e77e712ed454f12a6300f6e5f5b54391252` with environment `119bb9bff5a09aa7f1f04799396bcb68cf34a10a` — reviewed READY; UNKNOWN is not online and process start is presence, not heartbeat.
- age-days deterministic CI repair `ef3d08ff9fc58d33ba96994bb2e3256010bda1f4` — reviewed READY.
- lifecycle producer first candidate `6ffb2c6626e020c8313910adf76dd6e6be2c6848` — reviewed REPAIR_REQUIRED and recorded rejected, proving the rejection path on the producer itself.
- lifecycle producer repair `acef34793d8742516aa7526480cb7cb959f0e651` — fixes the first five kernel findings but remains under fresh adversarial review; later findings K-06..K-09 are not waived by prior green tests.
- CI-stream judgment integration candidate `b68e6e827afbeba3364c8239a2d814a60372f498` — reviewed READY relative to stream base `6b7c43d29f5deb0317517eb1577e98b4b693eaf7`; this does not retroactively independently review GPT-authored content already present in that base.
- engineering-state branch latest observed in this reconciliation: `65cc585894f33000a830aba3975d779498b3a0b0`.

No production deployment/runtime/watcher/systemd/business-write authority follows from these repository-only lifecycle records.

### Current hardening findings on the producer repair

The successor to `acef3479` should close these remaining fail-closed gaps before the kernel is treated as accepted:

- **K-06 rename scope escape:** changed-path derivation must preserve both source and destination paths for renames/copies so moving an out-of-scope file into an allowed path cannot appear in-scope.
- **K-07 owner-resolution provenance:** naming an owner principal string is not authority. Owner-gate resolution must bind to immutable owner-origin evidence/session/provenance for the exact gated task/revision.
- **K-08 journal rollback boundary:** a Git failure after staging must restore filesystem state, index state and HEAD, not only lifecycle files.
- **K-09 stale integration acceptance:** an obsolete/superseded integration-candidate acceptance must not remain valid authority for later completion.

These are subject defects, not grounds to reopen the parked unrestricted-prose verifier loop.

## 4. What is still missing from the self-managed engineering milestone

The lifecycle kernel can now author and persist the engineering states. It does **not yet prove the full autonomous runtime loop**.

The remaining major proof is:

```
owner objective
→ CLIVE creates persistent engineering objective
→ CLIVE chooses and launches eligible worker
→ worker builds
→ CLIVE records candidate
→ CLIVE launches independent reviewer
→ verdict returns directly to CLIVE
→ CLIVE routes repair if needed
→ fresh exact-SHA review
→ accepted integration
→ COMPLETE / OWNER_GATE
```

The owner must not be the message courier during this demonstration.

Today the user still relays some worker/reviewer text manually. That is temporary scaffolding, not the target product interaction.

### Objective ingress

Long term, GPT is beneath CLIVE, not the doorway to CLIVE.

A direct CLIVE input surface should create the persistent objective. It may be exposed through CLIVE chat/voice and/or an Agent Environment command surface such as **New Objective**, but the UI is only a client:

`UI/voice → CLIVE command/API → authoritative control-plane objective`.

Agent Environment must not become a second source of truth merely because it gains a command surface.

## 5. Engineering organisation: preserve invariants, not fixed job titles

Earlier memory describes a fairly rigid hierarchy of GPT Director, Claude manager, specialist roles, integrator and named model families.

Preserve the durable responsibilities:
- owner authority,
- deterministic CLIVE control plane,
- explicit task/attempt/candidate identity,
- isolated worker workspace,
- evidence/provenance,
- independent review,
- stale-result fencing,
- integration verification,
- recovery/reconciliation,
- owner gates where required.

Do **not** fossilise a specific worker org chart or provider assignment.

The current orchestration principle is:

> **Give the most capable eligible worker the largest coherent unit of work that can safely be verified. Decompose only when it materially improves reliability, parallelism, authority separation or recovery.**

Fable is not permanently limited to "Experience Director". Recent recovery work proved it can be a strong general construction/execution worker when the task and evidence are appropriate.

Likewise Claude/Opus/Sonnet/GPT/Fable names are replaceable provider/model capabilities, not permanent semantic roles in CLIVE.

The stronger doctrine is:

> **Use capable models aggressively for construction. Use CLIVE aggressively for control.**

Cognitive diversity remains useful. Operational reviewer independence remains mandatory where the contract requires it. They are not the same property.

## 6. Old engineering scaffolding that must not become permanent precedent

The following should be treated as replaceable/retirable mechanisms once their responsibilities are proven elsewhere:

- manual copy/paste between GPT and Fable/Claude,
- the old hourly supervisor as the normal continuation clock,
- the single shared bridge inbox as the long-run scheduler,
- unrestricted-English parser/freeze machinery,
- fixed model-to-role mappings,
- rigid specialist-agent counts,
- nested/shared workspace patterns that create coordination hazards,
- any dashboard state inferred from appearances when authoritative records exist.

The old **CLIVE Engineering Supervisor** automation is currently disabled. Do not use it as the normal controller unless explicitly re-authorised.

The unrestricted prose-freeze/parser loop remains parked unless the owner explicitly reopens it.

## 7. V0.5 remains a separate product-integration stream

User-facing CLIVE V0.5 and the engineering control-plane milestone are distinct.

Known integration candidate:
`d9621337129b171ad284e04c8894884a0612edd1`.

Do not deploy it directly.

Its unresolved secret-scan fixture must not be baselined merely to obtain a green badge. Baseline only if the owner can establish that the fixture was always synthetic/never live. If uncertain, replace the fixture with clearly synthetic material and rotate any credential that may have been real.

Product decisions around recognizer/privacy behaviour and CLIVE-vs-old CROOKS OS naming remain separate owner product decisions where still unresolved.

The correct product path remains explicit integration of the production lineage and V0.5 lineage, followed by acceptance/review and an owner deployment decision where required.

## 8. Near-term sequencing after kernel acceptance

Do not respond to kernel acceptance by starting another broad architecture expansion.

The next proof should be one genuinely new, bounded CLIVE-managed engineering objective with no owner courier. A suitable example is worker/model cost tracking or another narrow Agent Environment/control-plane feature.

Success means the owner supplies the objective once and later observes real states such as:

`ASSIGNED → BUILDING → REVIEWING → REPAIR → REVIEWING → COMPLETE`

without manually moving messages between workers.

After that proof, shift the centre of gravity from engineering architecture to operational evidence.

Run a narrow real Crooks workflow for roughly a week. Start with a reversible/approval-friendly action class such as drafting customer-support replies rather than broad autonomous writes.

Measure:
- owner minutes required,
- actions accepted unchanged,
- actions edited,
- actions declined/deferred,
- errors caught before execution,
- errors found after execution,
- unauthorised/stale actions attempted,
- useful work completed,
- hours of owner attention removed.

The success metric is operational value and reduced coordination cost, not code volume or test count.

## 9. Commercial hypothesis — captured, not an engineering mandate

CLIVE should be presented commercially as one platform, not as a pile of internal subsystems.

A customer should first be shown a concrete outcome, for example:

> connect the store and inbox; CLIVE handles routine operational work and brings the owner the exceptions.

The self-engineering system is part of why the product can adapt; it is not necessarily the first thing a customer buys.

For technical/enterprise buyers, the control plane itself may also be valuable as the trust layer between autonomous coding agents and production. Treat that as a hypothesis to validate through repeated use, not a reason to split the product prematurely.

The strongest future proof is the same kernel operating in two domains:
1. CLIVE manages the workers that improve CLIVE.
2. CLIVE manages real business work.

If both are demonstrated using the same objective/authority/evidence architecture, the general operating-layer thesis is materially stronger.

## 10. Anti-ossification audit for future workers

Before preserving an old component solely because product memory mentions it, ask:

1. Is this an active owner decision or merely historical implementation?
2. What unique responsibility does it still hold?
3. Is that responsibility now fully covered elsewhere?
4. Would deleting it violate an active safety/authority invariant?
5. Is there migration/recovery evidence that still depends on it?
6. If we were designing the system today, would we still choose it?

If the answers show no unique responsibility, propose explicit RETIREMENT instead of maintaining dead architecture.

Never silently delete active safety or owner-authority semantics.

## 11. Current milestone definition

The next milestone is not "more orchestrator code."

It is:

> **The owner gives CLIVE one engineering objective once; CLIVE gets it to independently reviewed completion without the owner acting as courier.**

The next product milestone after that is:

> **CLIVE performs a narrow class of real Crooks operational work for long enough to measure whether owner attention actually falls.**

Those two proofs convert the project from architecture into evidence.


## 12. Post-kernel closure and first product dogfood — 2026-09-23

The lifecycle recovery sequence is now closed.

Verified repository state after Packet 14:
- frozen repository-only lifecycle kernel: `18c3153a2eec10c6343153b550776afed3bec2ba`;
- Packet 14 READY was admitted and `control-plane-producers` r6 reached COMPLETE;
- the already-READY judgment-ledger CI integration candidate `b68e6e827afbeba3364c8239a2d814a60372f498` was landed by fast-forward on `claude/ci-provenance-acceptance-2026-09-22`;
- acceptance run `35806286976` passed at that exact stream head;
- the engineering-state branch recorded the resulting COMPLETE states;
- no deployment, watcher, systemd, runtime, secret, permission or business-write authority was added by this closure.

The kernel is a milestone, not a new product to keep hardening speculatively. Future kernel changes require either:
1. real dogfood evidence that a core invariant is broken, or
2. a demonstrated release-blocking failure against the frozen V1 acceptance properties.

Do not reopen a K-series merely because another hypothetical edge case can be invented.

### Self-referential convergence rule

The Packet 7→14 sequence exposed a general rule that extends DEC-057 beyond verifier-only defects:

> **When the subject is machinery that defines, executes or evaluates its own improvement process, freeze the acceptance criteria for the round. New non-critical criteria discovered during review become backlog work. Repeated rounds that improve only the machinery without increasing externally observable product capability are a stop signal.**

A new finding should block a frozen engineering-control milestone only when it demonstrates a material failure such as:
- worker self-certification;
- stale/wrong SHA inheriting review;
- out-of-scope code being accepted;
- fabricated owner authority;
- rejected/superseded work becoming authoritative again;
- COMPLETE without accepted and verified integration evidence;
- failed kernel operation corrupting authoritative state or consuming unrelated work;
- reviewer-independence failure.

Everything else is either evidence for a future bounded task or a backlog item unless real dogfood makes it material.

## 13. First real product dogfood: Customer Support Investigator V1

The first post-kernel product task is `support-investigator-v1`, a read-only Crooks customer-support investigator.

Its purpose is deliberately external to the engineering machinery:
- take a real customer enquiry;
- identify the correct customer/order where evidence permits;
- gather order, fulfilment/tracking and conversation evidence;
- separate verified facts, reasonable inference and unknowns;
- expose evidence;
- prepare a reply draft requiring owner approval;
- perform no email/order/refund/fulfilment/business write.

The initial implementation candidate is:
`921375628d13ce338c659a7b789c11d8ac2b5f58`.

At that SHA:
- CI run `35810435777` passed;
- two real Crooks support cases were used as the external acceptance oracle;
- Shopify and Gmail source data independently confirmed that the candidate selected the correct orders/customers and recovered the relevant evidence;
- the exact-SHA review returned **CHANGES REQUIRED** for one bounded product defect, S-01.

S-01 is not an infrastructure finding. The deterministic reply templates could claim internal operational work was already underway without evidence, for example “we are checking with them” or “we are confirming it now.” That violates the product’s evidence/verified-reality doctrine even though the underlying investigation was correct.

The current engineering-state branch records `support-investigator-v1` r3 / attempt a3 as BUILDING to repair S-01. Treat this as a one-repair convergence round:
- rerun the same real cases;
- block only on a new material customer-facing/safety/authority failure;
- stylistic or hypothetical improvements become backlog;
- when the external acceptance properties are clean, freeze Support Investigator V1 and use it rather than polishing indefinitely.

This is a useful proof because real operational evidence found a defect that synthetic tests missed.

### Important runtime limitation

The real acceptance cases were reached using owner-authorised Shopify/Gmail connectors available to the engineering session. This did **not** prove that the currently deployed CLIVE runtime itself has every required live connector credential. In particular, historical roadmap state still marks Gmail runtime OAuth as unresolved unless fresh deployment evidence supersedes it.

Therefore distinguish:
- **product code capability** — Support Investigator can consume the application’s read-only readers;
- **real-case acceptance evidence** — proved using live Crooks systems through authorised connectors;
- **deployed runtime readiness** — still requires fresh verification of CLIVE’s own bound Shopify/Gmail clients before claiming the feature is live end to end.

Credential provisioning remains an owner/authority boundary, not an excuse to widen engineering scope.

## 14. Direction check against the product philosophy

The project is converging toward the approved philosophy rather than away from it.

### Intent-to-execution

The philosophy says the human should stop being the transport and coordination layer. The kernel removed ambiguity from engineering state; Support Investigator removes cross-system support investigation from the owner. The remaining obvious violation is manual couriering between CLIVE, Fable/Claude and GPT.

Therefore the next engineering capability should remove that courier role, not add more control-plane theory.

### Evidence-backed world state

The product doctrine requires observed evidence, inference and unknowns to remain distinct. Support Investigator implements exactly that split. S-01 is important because it caught a subtler version of the same rule: a reply must not convert a proposed/needed operational action into a claimed current fact.

This is a durable product invariant:
> **CLIVE must distinguish what is true, what it infers, what it proposes, what has been authorised, what has actually started, and what has been verified complete.**

That invariant should generalise beyond support to fulfilment, supplier work, product development and self-engineering.

### APIs are capabilities, not destinations

Support Investigator uses Shopify/Gmail as evidence providers beneath the objective. The owner does not need to coordinate “open Shopify, then Gmail, then compare them.” This directly matches the capability-oriented philosophy.

Do not fossilise the current support implementation into permanent provider-specific UX. The durable capability is “investigate a customer/order case from trustworthy evidence and prepare the next authorised response.”

### Human authority

The product still preserves the right boundary:
- investigation is read-only;
- drafts require owner approval;
- refunds/cancellations/order edits/sends remain external writes;
- owner gates are not fabricated by the repository kernel.

Self-engineering must follow the same pattern: CLIVE may commission and review changes to itself without gaining the authority to deploy, change privileges/secrets, spend money or cross owner-only business-write gates.

### Future-disposable machinery

The kernel’s semantic responsibilities are worth preserving; its implementation, model/provider adapters and future dispatcher are not sacred. Objective intake and model invocation should therefore be implemented as replaceable adapters around the frozen lifecycle semantics rather than by expanding the kernel into a monolith.

### Dynamic UI / Agent Environment

Agent Environment remains correctly positioned as a projection/client of CLIVE state. Its lifecycle-aware candidate is useful for visibility, but promotion of that UI is not a prerequisite for self-managed engineering.

A private read-only preview is useful because it lets the owner inspect real ASSIGNED/BUILDING/REVIEWING/COMPLETE state. It must not become a second authoritative task store.

## 15. Where the roadmap is actually converging

The 2026-09-19 ROADMAP still contains useful long-horizon stages, but several “Someday” engineering items have effectively moved forward because their prerequisites now exist.

What was once described as:
- Y1 natural-language engineering requests,
- Y2 CLIVE-managed Claude Code,
- Y3 automatic GPT ↔ Claude loop,

is now the immediate missing layer around an already-working authoritative lifecycle kernel.

This is not a contradiction of sequencing. The kernel, exact-SHA review discipline, state projection and first real product dogfood now provide the evidence that makes the old “Someday” idea actionable in a bounded form.

At the same time, the roadmap’s broader warning remains correct: do not jump from this into an indefinitely expanding engineering platform. The purpose of the self-engineering loop is to make product capability cheaper to add, not to become the product.

The converged near-term sequence is now:

1. Close Support Investigator V1 after the bounded S-01 repair and external re-check.
2. Build **Objective Intake + Engineering Dispatcher V1** as the minimum no-courier layer around the frozen kernel.
3. Prove one genuinely owner-once engineering objective reaches independently reviewed COMPLETE without George relaying messages.
4. Keep Agent Environment as truthful observability; optionally expose a private read-only live preview.
5. Then return immediately to real business capability: support queue/triage, fulfilment exceptions, drop operations or another externally verifiable Crooks objective.
6. Measure owner attention removed, edits/declines, factual failures, interventions and useful work completed.
7. Only widen autonomy after repeated evidence justifies a specific action class.

V0.5 production integration remains a separate parked stream until its fixture/owner decisions are resolved. It should not block the no-courier engineering proof or read-only operational dogfood.

## 16. Exact next engineering capability

After Support Investigator V1 closes, the next bounded build should be:

> **CLIVE Objective Intake + Engineering Dispatcher V1**

It should provide only the missing transport/execution responsibilities:

```
owner objective
→ CLIVE persistent objective/task
→ eligible worker launch
→ worker result/evidence/candidate ingestion
→ independent reviewer launch
→ verdict ingestion
→ bounded repair routing
→ accepted integration
→ COMPLETE / OWNER_GATE
```

The lifecycle kernel remains the source of truth and stays frozen unless dogfood demonstrates a core-invariant failure.

The dispatcher should not become a new policy brain. It should:
- translate an already-authorised objective into the kernel’s existing lifecycle;
- invoke the selected worker in an isolated workspace/session;
- bind model/session/base/task/attempt identity;
- collect heartbeats/evidence/candidate identity;
- invoke the independent reviewer against the exact candidate;
- route CHANGES REQUIRED back as a bounded successor attempt;
- stop on COMPLETE, BLOCKED or OWNER_GATE;
- never infer deployment/business-write/privilege authority from repository acceptance.

The first no-courier acceptance test should be a small real product change with an external oracle. Do not test the dispatcher by asking it to redesign the dispatcher.

## 17. Product invariant learned from the first dogfood

Support Investigator produced a general operational-state distinction worth preserving across CLIVE:

```
NEEDED / PROPOSED
≠ AUTHORISED
≠ STARTED
≠ COMPLETED
≠ VERIFIED
```

Natural language must not collapse those states.

Examples:
- “we need to check with FedEx” is not “we are checking with FedEx”;
- “return pending approval” is not “we are confirming it now”;
- “candidate accepted” is not “deployed”;
- “task assigned” is not “worker running”;
- “process alive” is not “meaningful progress”;
- “email prepared” is not “email sent.”

This is the same semantic spine appearing in both business operations and engineering. That convergence is evidence that the architecture is moving toward a general intent-to-execution system rather than two unrelated products.

## 18. Closure addendum — 2026-09-23 11:12Z

Appended after the reconciliation above, without changing it. Sections 12 and 13 describe `support-investigator-v1` at revision 3 as BUILDING; that is now history.

- Support Investigator V1 converged in three bounded repair rounds on the same frozen S-01 criterion: S-01 (drafts claimed internal actions were underway; packet 15 on `92137562`), S-01R (an untracked fulfilment was called dispatched; packet 16 on `2ca2bfee`), S-01C (cancel and address-change paths equated a fulfilment record with dispatch; packet 17 on `109f58c4`). Packet 18 on `2dbb97bc6c88d3ee3cf5cdf6a980df4f3405104a` returned READY.
- The verdict was admitted against attempt a5 and the exact accepted SHA was integrated by fast-forward into `claude/support-investigator-v1-2026-09-23` with the remote target ref verified; the task is COMPLETE at revision 5 (r1–r4 OBSOLETE). Engineering state `4e0194c9668c7d1193af3e5cbd0db6e9748e53ed`.
- The convergence rule of §12 held: the review closed on the frozen dimensions (customer identity, factual grounding, explicit uncertainty, read-only authority, privacy, materially misleading output) and opened no speculative round.
- What the acceptance did not authorise, and what has not happened: landing on the CI stream, deployment, runtime or watcher changes, customer sends, Shopify or Gmail writes, secret or permission changes. The owner's verification of the two real cases and the first live run under the read-only latch are still ahead.
- The next capability remains §16: Objective Intake + Engineering Dispatcher V1, started only on an owner objective.
