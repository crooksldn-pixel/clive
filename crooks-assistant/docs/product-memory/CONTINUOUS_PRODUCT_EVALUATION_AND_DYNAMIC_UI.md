# CLIVE Continuous Product Evaluation, Dynamic UI, and Live Experience Direction

**Status:** ACTIVE OWNER DIRECTION — durable product/engineering memory  
**Date:** 2026-09-20  
**Scope:** product quality, testing, live interaction, adaptive presentation, concurrency UX, engineering evaluation  
**Relationship to Orchestrator:** complements the Engineering Orchestrator V1 freeze; does not waive DEC-046/047, owner-only adoption, runtime, credential, connector, deployment, or privilege gates.

This document captures the product direction and research conclusions developed after the previous product-memory update. It is deliberately outcome-focused: future implementations may change radically if they preserve the active outcomes and safety invariants.

---

## 1. Why this exists

CLIVE must stop being judged mainly by whether isolated endpoints, fixtures, or code paths are green.

The product target is an assistant/operating layer that feels continuously aware and coherent:

> I speak → CLIVE visibly hears me → I can see what it understood → I can see useful work progressing → useful information appears as soon as it is available → CLIVE responds → I can interrupt, redirect, or add work without managing the software's internal architecture.

Every meaningful interaction should therefore be both:
1. a real product session; and
2. an evidence-producing evaluation case.

The engineering organisation should improve the product from accumulated evidence without allowing a model to grade itself, rewrite production immediately, or optimise against one simplistic score.

---

## 2. Research / observed findings that now constrain the next release

### 2.1 Green tests did not prove the live voice experience

Existing experience evidence exercised the pipeline primarily after transcription. The experience harness injects a transcript at `POST /turn`; the documented benchmark explicitly states that no run calls `/speak`.

Consequence:

A green post-transcription suite is useful but cannot establish that the physical experience from hold-to-speak through microphone capture, speech recognition, reasoning, progressive UI and spoken response is coherent.

New acceptance must include the real audio path or explicitly label a fixture/fake path as non-live.

### 2.2 Tested capability is not the same as deployed capability

Substantial mobile/UX work exists in review/evidence branches and was explicitly not deployed. Some live checks were narrowed/read-only or blocked for missing credentials.

Consequence:

Never infer that a capability is connected merely because code/tests exist. Product status and UI must distinguish:
- implemented,
- fixture-proven,
- device-proven,
- connected live,
- write-capable,
- deployed/verified.

The interface itself must not imply a service is usable when only its fixture or code path exists.

### 2.3 Split exposed the wrong user abstraction

The Split/Half model accumulated significant complexity: branch chips, per-half decks, focus switching, Merge/Close semantics, hit-testing, branch-scoped notifications, and explanations of which half was listening. Evidence showed cases where changing halves changed who was listening without making what the owner was seeing intuitively follow.

Owner direction on 2026-09-20:

> retire user-facing Split.

This does **not** mean discard useful internal branch/concurrency work. The capability should evolve into simultaneous jobs within one CLIVE session. The user should express objectives; CLIVE should manage concurrency.

### 2.4 The current interaction feels stagnant because state is fragmented

The observed phone experience has perceptual gaps between:
- holding to speak,
- speech being captured,
- confirming what was heard,
- thinking,
- tools/work,
- showing relevant information,
- speaking.

The product needs one perceptible interaction lifecycle rather than several unrelated loading behaviours.

Target conceptual lifecycle:

`IDLE → LISTENING → HEARING → UNDERSTOOD → THINKING → WORKING → RESPONDING → IDLE`

Error, interruption, cancellation, recovery and degraded-capability states must be explicit.

### 2.5 Permanent plumbing indicators are not the product

Persistent SHOPIFY/GMAIL/VOICE/CHANGES status on the main idle surface exposes implementation plumbing and competes with the primary interaction.

Direction:
- connection diagnostics primarily belong in Settings/diagnostics;
- a capability problem becomes prominent when it affects the current objective;
- status must be truthful, not decorative.

### 2.6 The existing product contains useful fast paths

The existing UX doctrine correctly keeps deterministic fast paths for obvious operations and uses screen detail differently from speech.

Preserve:
- speech is concise;
- screen carries useful detail;
- deterministic fast paths remain where they are objectively better;
- consequential actions remain staged/verified;
- model/provider architecture is not exposed to the user.

Do not turn every request into a slow model round trip merely to make CLIVE appear more “AI”.

---

## 3. Live Experience V0.5 — immediate product direction

An isolated implementation stream was created at:

`chatgpt/clive-live-experience-v0-5`

Initial contract commit:

`4469e0b9c4450cd1f7244b028a5684394a0a0b6f`

It is intentionally isolated from the Orchestrator freeze branch.

### Immediate objective

Make the existing CLIVE OS feel alive end-to-end before broadening autonomy.

The first release slice should:
- remove the user-facing Split/Half/Merge/Close interaction model;
- keep useful concurrency internals available for migration;
- establish one canonical client interaction state authority;
- make the orb/transcript/progress/results/speech reflect that authority;
- show useful results progressively;
- represent simultaneous work as jobs/tasks inside one CLIVE session;
- continue the premium dark/liquid-glass direction;
- reduce idle dead space and permanent diagnostics;
- test the physical voice path on real devices;
- preserve current action-safety boundaries.

### Canonical acceptance conversation

Hold the orb:

> “Clive, check today's orders, see if anyone important is waiting for a reply and tell me what I need to deal with first.”

Expected observable behaviour:
- immediate listening acknowledgement;
- speech activity / partial heard text where available;
- final transcript visibly settles on release;
- no unexplained blank interval;
- order and email work progress independently;
- first useful result appears before all dependencies finish;
- final prioritised summary is presented and spoken.

Then:

> “Open the second customer.”

CLIVE changes foreground context without losing unrelated work.

Then:

> “While you're doing that, prepare the packing list as well.”

A new background job progresses. No Split button, no second assistant personality, no manual workspace management.

This one scenario intentionally exercises voice, state continuity, model/routing, parallel jobs, progressive presentation, interruption, context, and speech.

---

## 4. Simultaneous work: replace Split with jobs

The future interaction unit is not a “half”; it is a job/objective.

Example session:

- Check today's orders — DONE
- Check important unanswered email — WORKING
- Prepare packing list — QUEUED

Properties:
- stable job identity;
- concise owner-readable label;
- explicit state;
- independent completion/failure;
- optional result summary;
- jobs may settle in any order;
- one failed job does not erase successful siblings;
- completed jobs can collapse when their information is represented in the scene;
- jobs are not permanent dashboard chrome;
- foreground conversation can interrupt or redirect without destroying background work.

The eventual Orchestrator may provide deeper execution concurrency, but product-level simultaneous work must not depend on exposing Orchestrator concepts to the owner.

---

## 5. Dynamic UI / scene compiler direction

CLIVE should not grow into an ERP with a hard-coded screen for every possible sentence.

The rendering question is:

> Given the user's objective, available evidence, device, urgency, current work and likely next actions, what is the smallest interface that best communicates the current state?

### 5.1 Scene compiler

A future scene compiler should consume semantic state such as:
- objective;
- entities;
- evidence/provenance;
- job state;
- device/viewport;
- urgency/attention;
- safe available actions;
- uncertainty;
- foreground/background context.

It composes from a small typed primitive vocabulary, for example:
- text/summary;
- order;
- customer;
- email/message;
- metric;
- timeline;
- task/progress;
- warning/exception;
- evidence/source;
- proposed action;
- confirmation;
- nothing.

The model may choose/combine semantic primitives, but it must not emit arbitrary executable UI code into the trusted client.

### 5.2 Generated actions remain contracts, not arbitrary code

Any generated action must be:
- typed;
- capability-bound;
- authorised;
- staged where required;
- idempotent where applicable;
- verified;
- explicit about risk/reversibility;
- unable to smuggle arbitrary model code into execution.

Dynamic presentation must never weaken the existing action-safety model.

### 5.3 UI decision trace

For substantial adaptive scenes, retain enough privacy-minimised trace to answer:
- what objective was inferred;
- what evidence/entities were available;
- which primitives/actions were selected;
- what was omitted;
- what device/context constraints applied;
- how the owner interacted with the result.

This allows an evaluator to judge the presentation decision rather than only its pixels.

---

## 6. Liquid-glass design direction

Owner explicitly likes the liquid-glass direction.

Use it as a coherent material system, not decoration.

Principles:
- dark CROOKS identity remains primary;
- translucent surfaces communicate grouping, layering or transient work;
- restrained blur;
- thin highlights and borders;
- depth through opacity/border/shadow before gratuitous motion;
- orb remains the primary living status object;
- the orb can contract/reposition when content becomes more important;
- motion communicates state change, not visual noise;
- respect reduced-motion and lite-device behaviour;
- idle screen should be calm and sparse;
- useful content gets the space when it exists.

Idle hierarchy should trend toward:
1. CROOKS / contextual status / settings;
2. orb;
3. prompt or live transcript;
4. hold-to-speak affordance;
5. minimal contextual shortcuts.

Remove the central Split CTA and explanatory copy.

---

## 7. Every session is an evaluation session

There should not be a separate concept where only a special “test session” evaluates CLIVE.

Every real session should produce a privacy-minimised evidence trace that can later be evaluated.

Candidate trace fields:
- session/interaction identity;
- objective as understood;
- source modality;
- partial/final transcript timing where applicable;
- entities/evidence used;
- tools/capabilities invoked;
- jobs spawned and their state transitions;
- UI scene/primitives shown;
- actions proposed/executed/verified;
- latency milestones;
- errors/degraded dependencies;
- interruptions;
- owner corrections/rephrases;
- repeated requests;
- manual overrides;
- abandonment;
- downstream completion/outcome where deterministically observable.

Do not retain sensitive content merely because it may be useful for evaluation. Prefer derived/redacted evidence and explicit retention policy.

---

## 8. Evaluation is multidimensional

Do not collapse product quality to one score.

Dimensions should include at least:
- objective understanding;
- factual/evidence correctness;
- entity correctness;
- completeness;
- unnecessary information;
- task/outcome completion;
- user effort;
- correction burden;
- relevance;
- UI appropriateness;
- action quality;
- trust/provenance quality;
- latency;
- interruption/recovery quality;
- conversation continuity;
- whether the product chose the right amount of UI;
- whether useful work appeared progressively.

Satisfaction is partly latent. Behavioural signals are proxies, not ground truth.

A fast interaction can still be wrong. A correct interaction can still be frustrating. A visually attractive scene can still expose the wrong information. Keep these dimensions separable.

---

## 9. Independent evaluation — no naive self-grading

The same model that produced a response should not be the sole authority deciding that the response was good.

Preferred evaluation pattern:
1. collect deterministic trace/evidence;
2. run deterministic checks first;
3. use an independent evaluator/reviewer for semantic/experience judgement;
4. compare evaluator judgement with behavioural outcome;
5. aggregate patterns across sessions;
6. reproduce material issues;
7. only then propose product/code changes.

Evaluator should ask:
- did CLIVE understand the objective;
- was the answer supported;
- did it use the right information;
- what important information was missing;
- what was unnecessary;
- was the UI appropriate for the objective/device;
- were actions correct/safe;
- how much correction did the owner have to provide;
- did the task actually complete;
- was a simpler interaction possible;
- would a different scene/action sequence have been better?

Evaluator output is evidence, not deployment authority.

---

## 10. Better testing: move beyond happy-path green suites

The next test system should combine deterministic tests with adversarial and experiential evaluation.

### 10.1 Real-device black-box tests

Where practical, a test agent should interact as a user:
- screenshot/visual observation;
- DOM/accessibility tree where available;
- pointer/touch;
- keyboard;
- physical/virtual microphone path;
- interruption;
- orientation/viewport;
- degraded network/dependency.

Do not give the black-box agent internal implementation knowledge it would not have as a user.

### 10.2 Hidden tests

Maintain evaluation scenarios the implementation worker does not optimise against directly.

Purpose:
- reduce test gaming;
- detect brittle overfitting;
- protect general interaction quality.

### 10.3 Scenario mutation

Mutate:
- wording;
- entity count;
- ordering;
- latency;
- one dependency failing;
- ambiguous requests;
- corrections;
- interruption timing;
- device dimensions;
- background-job completion order.

A candidate that only passes one scripted sentence is not robust.

### 10.4 Composite / exploratory tests

Test sequences, not only atomic actions.

Examples:
- ask → interrupt → redirect → resume;
- start two jobs → one fails → third added → foreground context changes;
- partial data arrives → scene updates → user acts before slow dependency completes;
- speech recognition correction occurs mid-flow.

### 10.5 Visual reviewer

Use screenshot/visual evidence to judge:
- hierarchy;
- dead space;
- collisions;
- overflow;
- tap targets;
- keyboard occlusion;
- state legibility;
- whether the important thing is visually important;
- whether progressive changes are understandable.

Pixel equality alone is insufficient.

### 10.6 Blind baseline vs candidate

For subjective experience evaluation, where feasible show an evaluator baseline and candidate without telling it which is “new”.

Judge against explicit criteria and evidence rather than novelty.

### 10.7 Mutation testing for the tests themselves

The Orchestrator freeze review demonstrated why this matters: a test can claim to enforce an invariant while only detecting one literal wording.

For important safety/contract/product gates:
- deliberately introduce plausible defects;
- prove the gate catches them;
- include paraphrases/structural variants;
- fail closed when the gate cannot classify a critical case;
- do not let the test restate the same assumption it is supposed to independently verify.

### 10.8 Long-session tests

CLIVE is persistent software. Test:
- accumulated context;
- repeated corrections;
- many job transitions;
- stale UI;
- reconnect/reload;
- background completion;
- memory/context boundaries;
- resource/latency degradation.

A product that survives a 20-second fixture but degrades after an hour is not ready.

---

## 11. Protect evaluation from drift and gaming

A self-improving product can learn to optimise the evaluator instead of the user.

Controls:
- hidden evaluation sets;
- evaluator versioning;
- periodic human calibration;
- multiple independent signals;
- mutation tests;
- disagreement tracking;
- frozen historical replay;
- do not rewrite expected behaviour merely to make a candidate pass;
- retain rejected examples;
- compare downstream outcome, not only evaluator prose;
- periodically evaluate the evaluator itself.

When evaluators disagree, preserve the disagreement and escalate material uncertainty rather than averaging it into false confidence.

---

## 12. Improvement loop

Target product-improvement loop:

`interaction → evidence → independent evaluation → issue/pattern → reproduction → proposed improvement → isolated implementation → hidden/device/replay evaluation → independent review → candidate`

Important:
- one poor interaction does not immediately rewrite the product;
- aggregate evidence where appropriate;
- severe deterministic failures may be escalated immediately;
- product/taste changes remain owner decisions when material;
- production changes remain gated by risk and existing governance.

This is compatible with the Engineering Orchestrator but does not depend on its first implementation.

---

## 13. User-specific adaptation vs global learning

Keep these separate.

User-specific adaptation may learn preferences/context within allowed memory/privacy boundaries.

Global product learning should require:
- de-identification/minimisation;
- aggregation where possible;
- reproduction;
- independent evaluation;
- review;
- versioned candidate.

Do not convert one user's preference into global product doctrine automatically.

---

## 14. Latency milestones that matter

Measure the experience, not only backend duration.

For voice:
- pointer-down → visible LISTENING;
- first speech energy → visible HEARING;
- first partial transcript;
- pointer-up → final transcript settled;
- final transcript → first thinking/work acknowledgement;
- release → first useful result;
- release → first spoken response;
- total objective completion.

Progressive useful information can matter more than total completion time.

Do not hide latency behind meaningless animation.

---

## 15. Engineering process lessons from the freeze work

The Orchestrator freeze rounds exposed several durable quality lessons applicable beyond Orchestrator code.

### 15.1 Exact identity matters

Review/acceptance binds to exact SHA/artifact/evidence. A verdict on an older candidate does not transfer to a repaired candidate.

### 15.2 Implementer evidence is not independent review

The implementer can supply evidence, but important work should be attacked by a fresh reviewer.

### 15.3 Tests can false-green

A green suite is not proof that the suite enforces its stated invariant. Adversarial mutation of the test contract is required for important gates.

### 15.4 Fail closed on unclassifiable critical semantics

If a safety/authority gate depends on classifying a critical operation and wording/state is unknown, “not detected” must not silently mean safe.

### 15.5 Separate architecture defects from test defects

A review may find the normative contract sound while its mechanical proof is weak. Repair the smallest layer that is actually wrong rather than churning architecture.

### 15.6 Bounded repairs beat broad rewrites during convergence

Once architecture is stable, repair one demonstrated defect, preserve previous invariants, then fresh-review the new exact SHA.

### 15.7 Independent recomputation is stronger than narrative confirmation

A reviewer should derive relevant sets/transitions/identities from source data where practical rather than merely checking that the implementation says the expected sentence.

### 15.8 Crash/ambiguity paths are first-class product engineering

A system is not correct only when the happy path finishes. Recovery, stale workers, ambiguous side effects, interrupted sessions and partial dependency failure must have explicit semantics.

These lessons should inform future CLIVE tests and the continuous-evaluation harness, not remain confined to the Orchestrator spec.

---

## 16. What the last two days changed for CLIVE implementation quality

The value is not that the Orchestrator runtime is already autonomously managing the new UI build. It is not.

The environment around the build is materially stronger:
- richer mobile/device evidence;
- explicit evidence that Split is the wrong user abstraction;
- a clear voice end-to-end gap;
- separation between implemented/tested/live/deployed;
- stronger independent-review discipline;
- adversarial mutation testing;
- exact-SHA evidence binding;
- Phase 6 appliance/runtime/observability work;
- quality-first model routing direction;
- explicit acceptance conversation;
- clearer product doctrine that liquid glass is presentation over a coherent behavioural system, not a cosmetic patch.

Before this work, “redesign the UI” could plausibly produce a prettier version of the same fragmented experience.

The current direction instead asks for a continuous interaction model with measurable behavioural proof.

---

## 17. Sequencing / authority

This document records active owner product direction. It does not silently alter existing canonical safety/governance decisions.

Current safe interpretation:
- product design, test design, repo-only prototypes and isolated implementation can proceed in bounded branches;
- Orchestrator freeze continues independently until exact-SHA owner adoption;
- production/runtime promotion, new secrets, connector/MCP grants, business writes, watcher/systemd changes, privilege expansion and public exposure remain separately gated;
- when the freeze receives a clean verdict, owner should explicitly reconcile/adopt the exact freeze SHA and any desired DEC-046 sequencing amendment;
- Live Experience work must be reconciled with the then-current canonical base before production promotion.

Do not let governance prevent safe isolated product progress; do not let parallel product progress become an excuse to bypass runtime authority.

---

## 18. Near-term implementation order

1. finish current Orchestrator freeze convergence independently;
2. continue isolated Live Experience V0.5 implementation;
3. retire Split UI and introduce one-session job presentation;
4. establish canonical interaction state authority;
5. wire real microphone/partial/final transcript state;
6. add progressive job/result rendering;
7. refine liquid-glass hierarchy/spacing;
8. add black-box/device/state/mutation/long-session evidence;
9. connect model/live read capabilities only when their runtime/credential gates are explicitly cleared;
10. collect real sessions and feed them into the independent evaluation loop;
11. evolve typed scene compilation from the proven primitive set;
12. allow the Engineering Orchestrator to automate more of this engineering loop only after its own acceptance/adoption/runtime gates are satisfied.

The target is not more architecture.

The target is a CLIVE that increasingly disappears as software and feels like one coherent operating intelligence.
