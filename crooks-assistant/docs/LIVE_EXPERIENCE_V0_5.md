# CLIVE LIVE EXPERIENCE V0.5 — IMPLEMENTATION CONTRACT

Status: isolated product implementation stream. Not production. Not Orchestrator freeze/adoption.

Base: `claude/crooks-appliance-phase6@93dcd5dad6ebb2ee6191caa7ca7951e826c33ca4`
Relevant mobile UX evidence branch: `claude/mobile-experience-v1-review@564ef3430d58b34de582f5548d7fe201c4cfe04b`
Owner direction: retire user-facing Split; preserve useful concurrency primitives underneath; continue premium dark/liquid-glass direction; make voice/model/tools/results one continuous live experience.

## Objective

From pointer-down on the voice surface until useful information is visible and CLIVE is speaking, the owner must always be able to perceive what CLIVE heard, what state it is in, and what work is progressing.

The first milestone is not broad autonomy. It is a coherent, honest, progressively-rendered Jarvis loop using existing safe capabilities.

## Product invariants

1. No user-facing Split, Half 1/Half 2, Merge or Close interaction model. Do not delete backend concurrency primitives merely because their old UI is retired. Future concurrency is task/job based inside one CLIVE session.
2. One canonical interaction state drives microphone, orb, transcript, reasoning/progress, results and speech:
   `IDLE -> LISTENING -> HEARING -> UNDERSTOOD -> THINKING -> WORKING -> RESPONDING -> IDLE`.
   Error, interruption and recovery states must be explicit.
3. Voice must be tested from physical/pointer microphone capture, not only by injecting a completed transcript at `POST /turn`.
4. Partial speech feedback appears while the owner is speaking where supported. Final transcript visibly settles before/while reasoning begins. Never leave an unexplained dead interval.
5. Results are progressive. Independent jobs may complete in any order and useful completed information renders immediately. One slow dependency must not hold the whole answer hostage.
6. Multiple simultaneous jobs are represented as lightweight work/progress objects inside one session, not separate assistant personalities/workspaces.
7. Deterministic fast paths and model-routed paths must present as one CLIVE. Architecture must not leak into interaction language.
8. Connection/service health is contextual. Remove permanent diagnostic clutter from the primary idle surface; diagnostics remain available in Settings. Surface a connection problem in the main flow only when it affects the current objective.
9. Preserve safe proposal/confirmation/verification semantics. This stream does not authorize new writes, secrets, connector grants, runtime privilege, production deployment or public exposure.
10. UI is response-driven. Reuse typed safe primitives (order, customer, email, metric, task/progress, action, warning, etc.) and compose the smallest useful scene for the objective rather than creating a new fixed screen for every query.
11. Every real interaction should emit privacy-minimised evaluation evidence sufficient to later assess acknowledgement latency, transcript correction, time-to-first-useful-result, tool/job progression, completion, errors and abandonment. Evaluation does not self-modify production.

## First implementation slice

### A. Retire Split UI without destroying concurrency internals

Current split/branch UI is concentrated in:
- `web/index.html`: `branch-rail`, `branch-head`, `branch-zone` / `branch-bar`
- `web/app.js`: branch rendering around `applyBranches`, `branchChip`, `drawBranches`, split/merge/close commands and per-half deck switching
- `web/style.css`: branch band, split chips, half chips and branch layout
- browser/tests that explicitly assert Split/halves.

For V0.5, the page must no longer invite manual division. Do not simply hide controls while leaving state semantics ambiguous. Map any still-required backend branch/workspace state into one foreground session and background job/progress representation. Existing branch APIs may remain internal during migration.

### B. Continuous voice state

Create one client-side state authority. Pointer-down must synchronously enter LISTENING and wake the orb. Audio energy drives the listening visual. Transcript/recognition events drive HEARING. Pointer-up/final transcript drives UNDERSTOOD. Backend/model/tool events drive THINKING/WORKING. First speakable response drives RESPONDING.

Do not infer state from arbitrary DOM text. State transitions must be explicit and testable.

### C. Progressive job strip

Add a compact, liquid-glass work surface that appears only when there is meaningful work. Each job has stable identity, concise verb/object label, state, optional result summary and failure/retry affordance where safe. Examples:
- Checking today's orders — done
- Checking customer email — working
- Preparing packing list — queued

Completed jobs may collapse once their result is represented in the scene. The strip must not become a permanent dashboard.

### D. Layout / liquid glass

Keep the dark CROOKS identity and orb. Reduce idle dead space and competing labels. The primary hierarchy on idle is:
- CROOKS wordmark / contextual connection status / settings
- orb
- prompt / live transcript
- hold-to-speak affordance
- bottom area shortcuts

Remove the central Split CTA and its explanatory copy. Move persistent service status out of the idle footer into Settings/diagnostics; retain contextual fault presentation.

Liquid-glass rules: translucent surfaces only where they communicate grouping/depth; restrained blur; thin highlights; depth through opacity/border/shadow rather than constant animation. Respect lite-device and reduced-motion behaviour already present.

### E. Acceptance scenario

On a real device, hold the orb and say:

“Clive, check today's orders, see if anyone important is waiting for a reply and tell me what I need to deal with first.”

Required observable sequence:
- immediate LISTENING acknowledgement;
- speech activity / partial heard text while speaking where available;
- final transcript visible on release;
- explicit THINKING/WORKING transition with no unexplained blank state;
- orders and email represented as independently progressing jobs;
- first useful result appears without waiting for every job;
- final prioritised summary appears and begins speech;
- owner can interrupt with “Open the second customer” without losing other in-flight work;
- owner can then ask “while you're doing that, prepare the packing list as well” and a new background job progresses without Split.

If live Gmail/model access is still gated, use an honest fixture/fake adapter for the acceptance harness and label it as such. Do not pretend fixture data is live.

## Evidence gates

- Existing relevant web/mobile tests remain green or are intentionally replaced where they encode retired Split behaviour.
- New deterministic tests cover state transitions, interruption, progressive out-of-order job completion, failure of one job while others continue, and no Split UI.
- Browser/device evidence at iPhone-class 390x844 and current tablet target.
- Measure pointer-down -> visual acknowledgement, release -> final transcript acknowledgement, release -> first progress indication, and release -> first useful result.
- No production deploy in this stream until separately authorized.
- No connector/credential expansion in this stream until separately authorized.

## Sequencing with Orchestrator freeze

This branch is deliberately isolated from `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`. It must not modify freeze documents or canonical product-memory decisions.

The current Orchestrator freeze/review lane may continue independently. When the freeze is accepted, reconcile this implementation stream with the owner-adopted exact SHA and sequencing decision before any production/runtime promotion.
