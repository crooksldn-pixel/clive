# CLIVE Reconciliation — 2026-09-23

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
