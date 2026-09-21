# CROOKS OS — Self-Improvement and Autonomous Engineering

**Status:** architectural direction  
**Last consolidated:** 2026-09-19

This document defines how CROOKS may eventually improve its own software without turning production into an uncontrolled self-modifying system.

The objective is:

> evidence-driven improvement with isolation, independent review, verification, and rollback.

Not:

> an AI that edits production whenever it feels like it.

---

# 1. Evidence sources

CROOKS already has or plans to have unusually rich evidence about how the product behaves.

Relevant evidence includes:

- backend error logs,
- server logs,
- verbal/turn logs,
- image/screenshot logs,
- UI interaction/tap logs,
- physical test-session telemetry,
- proposal/action/verification history,
- user corrections,
- repeated questions,
- abandoned interactions,
- tool errors,
- latency,
- entity focus,
- model responses,
- action outcomes,
- post-deploy regressions.

The self-improvement system should use this evidence to identify recurring failures and friction.

A single weak signal should not automatically become a code change.

---

# 2. Improvement loop

The canonical loop is:

```
PRODUCTION
   ↓
OBSERVER
   ↓
TRIAGE
   ↓
REPRODUCTION
   ↓
BUILDER
   ↓
SPECIALIST REVIEWER
   ↓
QA / REPLAY
   ↓
INTEGRATION
   ↓
GPT DIRECTOR REVIEW
   ↓
OWNER GATE where required
   ↓
STAGING / CONTROLLED DEPLOYMENT
   ↓
POST-DEPLOY MONITORING
   ↓
ROLLBACK if regression detected
```

Every stage should produce durable evidence.

---

# 3. Observer

The Observer does not immediately edit code.

Its job is to answer:

- what went wrong,
- how often,
- for whom/which workflow,
- whether the issue is reproducible,
- how material it is,
- whether there is enough evidence to justify engineering work.

Example:

> 17 customer-name lookups occurred today.  
> 3 returned the previously focused customer instead.  
> All 3 share the same focus-routing signature.

That is a useful issue.

“Maybe the customer UI could be nicer” is not enough evidence by itself.

---

# 4. Triage

Triage classifies findings into categories such as:

- BUG
- UI FRICTION
- UX FRICTION
- BAD RESPONSE
- ENTITY RESOLUTION
- LATENCY
- TOOL FAILURE
- VISUAL DEFECT
- AUTOMATION OPPORTUNITY
- SECURITY
- INSUFFICIENT EVIDENCE

Triage should reject low-confidence noise.

---

# 5. Reproduction before implementation

Before changing code, the system should try to reproduce the problem using frozen evidence.

A reproduction bundle may contain:

- original user turn,
- prior turns,
- focused entity,
- server state,
- tool calls,
- response,
- screenshot,
- action ledger,
- subsequent correction.

A reproducible failure should become a regression fixture where possible.

---

# 6. Builder environment

Builders must not edit the live production checkout.

Each task gets:

- unique task ID,
- unique branch,
- unique worktree,
- narrow objective,
- relevant evidence,
- explicit constraints.

Example:

```
/opt/crooks-builder/ui-185
branch: builder/ui-185

/opt/crooks-builder/bug-187
branch: builder/bug-187

/opt/crooks-builder/perf-186
branch: builder/perf-186
```

Parallel agents sharing one mutable checkout is prohibited.

---

# 7. Specialist engineering organisation

Long-term target:

```
                         OWNER
                           │
                           ▼
                     GPT DIRECTOR
                           │
                           ▼
                  CLAUDE DEV MANAGER
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
     UI WORKER         DEBUG WORKER      FEATURE WORKER
        │                  │                  │
     UI CRITIC         DEBUG CRITIC       CODE REVIEWER
        │                  │                  │
        ├──────────────┬───┴───────┬──────────┤
        ▼              ▼           ▼          ▼
   UX RESEARCHER     QA WORKER   PERF WORKER  SECURITY
        │              │           │          REVIEWER
     UX CRITIC       QA REVIEW   PERF REVIEW
        └──────────────┴──────┬────┴──────────┘
                              ▼
                      INTEGRATION AGENT
                              │
                              ▼
                     FULL TEST + REPLAY
                              │
                              ▼
                         GPT DIRECTOR
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
                CANDIDATE           OWNER DECISION
```

---

# 8. Claude Dev Manager

The Manager receives a broad objective.

Example:

> Improve the customer/order experience; it feels slow and messy.

The Manager should not immediately edit code.

It should decompose the objective:

```
UX-184
Investigate repeated customer-lookup friction.

UI-185
Fix mobile customer-card overflow.

PERF-186
Investigate slow Shopify customer lookup.

BUG-187
Reproduce focused-customer carryover.

QA-188
Create replay corpus from relevant sessions.
```

The Manager:
- assigns tasks,
- tracks dependencies,
- collects results,
- rejects weak work,
- prepares integration.

---

# 9. Specialist workers

## 9.1 UI Engineer

Receives:
- screenshots,
- DOM/CSS,
- device viewport evidence,
- design system,
- collision tests.

Primary concerns:
- layout,
- hierarchy,
- responsiveness,
- visual correctness,
- loading/error states.

Should not spend context analysing Gmail internals unless necessary.

## 9.2 UX Researcher

Receives:
- turn logs,
- corrections,
- interaction telemetry,
- abandoned screens,
- screenshots.

Primary concerns:
- friction,
- unnecessary information,
- poor flow,
- confusing presentation,
- wrong next action.

May recommend no code change if evidence is weak.

## 9.3 Debugger

Receives:
- stack traces,
- request IDs,
- tool traces,
- event ledger,
- reproduction evidence.

Primary goal:
- deterministic root cause.

Should reproduce before “fixing.”

## 9.4 Feature Engineer

Receives:
- approved feature spec,
- relevant architecture,
- capability constraints,
- acceptance criteria.

Builds feature without redefining product intent.

## 9.5 QA/Test Engineer

Does not implement the feature.

Attempts to break it.

Creates:
- regression tests,
- edge cases,
- replay cases,
- negative tests.

## 9.6 Performance Engineer

Examines:
- latency,
- model round trips,
- provider calls,
- unnecessary reads,
- slow code paths,
- cache opportunities.

## 9.7 Security/Actions Reviewer

Special protection for:
- auth,
- secrets,
- permissions,
- Shopify writes,
- refunds,
- action authorisation,
- proposal binding,
- verification,
- migrations.

This worker should be intentionally conservative.

## 9.8 Integration Agent

Combines independently accepted specialist branches into an integration candidate.

Does not bypass failed specialist review.

---

# 10. Independent reviewers — the “voice of reason”

Every important worker should have an independent reviewer.

The reviewer is instructed:

> Your job is not to agree with the implementation agent. Find reasons this change should not ship.

Reviewer questions:

- Was the diagnosis actually correct?
- Did the change solve the observed issue?
- Is the change larger than necessary?
- Were tests modified simply until they passed?
- Did the change remove old behaviour that still matters?
- Are the new tests meaningful?
- Does historical replay improve?
- Did the change introduce security/permission risk?
- Is there a smaller deterministic solution?
- Is the implementation agent overconfident?

A worker never becomes the sole authority on its own output.

---

# 11. GPT Director

The GPT Director sits above the Claude hierarchy as an independent reviewer/architecture layer.

It should inspect actual evidence rather than trust summaries.

Inputs may include:

- manager report,
- worker reports,
- actual Git diff,
- changed files,
- test output,
- historical replay,
- browser/device tests,
- product-memory decisions,
- security review,
- current production state.

Example decision:

> Rejected. The candidate appears to improve replay success only because expected entity resolution was changed in the fixture. Restore frozen expectations and rerun QA.

The GPT Director should escalate product/taste decisions rather than pretending they are engineering facts.

---

# 12. Owner role

The owner should increasingly receive only decisions that require human judgement.

Examples:

- simplify a customer card from six fields to three,
- change the product’s interaction model,
- enable a new autonomy class,
- deploy a material architecture change,
- enable live writes,
- approve high-risk permissions.

The owner should not:
- copy messages between agents,
- manually run routine tests,
- arbitrate obvious code formatting,
- babysit workers.

---

# 13. Historical replay

Replay is a core safety/effectiveness gate.

For each relevant candidate:

1. run frozen baseline interactions against old build,
2. run same interactions against candidate,
3. compare outputs/actions/latency,
4. inspect regressions,
5. retain frozen expectations.

Potential metrics:
- correct entity resolution,
- task completion,
- unnecessary clarification,
- response length,
- latency,
- action accuracy,
- UI overflow/collision,
- owner correction rate.

Tests must not be silently rewritten to make the candidate “win.”

---

# 14. Behavioural quality signals

Useful response/UX signals include:

- immediate re-ask,
- owner correction,
- interruption,
- action ignored,
- card closed immediately,
- repeated tool call,
- unnecessary follow-up,
- latency,
- abandonment,
- undo/reversal.

Example:

> 11 order-status interactions.  
> 7 contained information the owner immediately ignored.  
> Proposed change: initially show only fulfilment state, tracking, and exceptions.

Behavioural signals can suggest changes, but weak signals must not become major product changes without review.

---

# 15. Nightly improvement cycle

A mature overnight cycle may run:

1. Observer analyses previous day.
2. Triage filters issues.
3. Reproduction creates evidence.
4. Manager opens specialist tasks.
5. Workers build in isolated worktrees.
6. Critics review.
7. QA/replay runs.
8. Integration candidate is created.
9. GPT Director reviews.
10. Candidate waits for owner/staging gate where necessary.

Possible morning report:

```
CROOKS Engineering — Overnight

Interactions analysed: 1,842
Potential issues: 7
Reproduced: 4
Fixes prepared: 3
Passed independent review: 2
Rejected by QA: 1
Production changes made: 0
Candidates ready for staging: 2
Owner decisions required: 1
```

---

# 16. Deployment levels

## Level 0 — Observe only
System identifies issues. No code edits.

## Level 1 — Builder
System may create branches/candidates. No deployment.

## Level 2 — Reviewed staging
Candidates that pass review may be deployed to staging automatically.

## Level 3 — Narrow autonomous production maintenance
Only for explicitly whitelisted low-risk classes after extensive evidence.

Possible examples:
- CSS overflow fix,
- missing loading state,
- deterministic parser regression.

Never default to Level 3.

---

# 17. Permanent approval-gated areas

Even in a mature autonomous system, changes in these areas should remain high scrutiny:

- authentication,
- secrets,
- permissions,
- financial/refund semantics,
- Shopify write semantics,
- action authorisation,
- safety invariants,
- destructive migrations,
- broad new network exposure,
- production credential storage.

---

# 18. Automatic GPT ↔ Claude engineering loop

Target loop:

```
Claude worker finishes
        ↓
outbox / task result
        ↓
GPT Director invoked
        ↓
actual diff + tests + evidence reviewed
        ↓
GPT writes next instruction
        ↓
bridge watcher launches Claude
        ↓
repeat
```

Guardrails:
- maximum autonomous rounds,
- per-task budget,
- stop on repeated failure,
- stop on unresolved disagreement,
- stop on owner-only decisions,
- never infer approval for production deployment.

---

# 19. CROOKS-managed Claude Code

Long-term, the user should not need to interact with Claude Code directly.

Example:

> “That customer screen was bad — fix whatever caused it.”

CROOKS can package:
- screenshot,
- interaction,
- current entity,
- error log,
- related source,
- relevant product-memory decisions.

Then:
- Manager assigns work,
- specialist builds,
- critic reviews,
- QA replays,
- GPT Director reviews,
- owner sees candidate/decision.

Termius becomes an emergency/admin console.

---

# 20. Rollback

Every production promotion should retain:

- previous known-good build,
- deployment identifier,
- relevant health metrics,
- post-deploy monitoring window,
- rollback command/path.

If the candidate produces a measurable regression, CROOKS should be capable of rolling back to known-good state rather than asking a model to improvise a fix under pressure.

---

# 21. Resource discipline

Do not spend expensive model time on every log line.

Use cheaper/deterministic triage before invoking deep coding/reasoning.

Possible hierarchy:
- deterministic filters,
- cheap classifier,
- observer summarisation,
- expensive specialist only for worthwhile issues.

This is especially important while Claude Max/model usage has limits.

---

# 22. Success criteria

Self-improvement is successful when:

- recurring issues decrease,
- owner corrections decrease,
- task success increases,
- latency improves,
- regressions are caught before production,
- owner attention required for engineering falls,
- and production becomes more stable rather than more volatile.

The goal is not “more code changes.”

The goal is:

> fewer reasons for the owner to notice the software at all.

---

# 23. Quality-first model routing

The engineering organisation must not optimise model spend or elapsed time at the expense of product quality.

Routing principle:

> use the strongest appropriate intelligence; optimise waste, not reasoning quality.

Default direction:

- **Claude Opus** — architecture, security boundaries, difficult diagnosis, major refactors, integration decisions, high-risk changes, final technical review.
- **Claude Sonnet** — bounded implementation when scope is clear and objective proof/review are available.
- **Faster/weaker models** — only genuinely mechanical work where reduced reasoning quality cannot materially change the product.
- **GPT Director** — decomposition, continuity, independent review, reconciliation of worker conclusions.
- **Fable** — specialist product-experience/interaction direction and review.

Escalate automatically when:
- implementation fails repeatedly,
- root cause remains unclear,
- architecture changes,
- security/auth/action semantics are involved,
- a task crosses multiple systems,
- reviewers disagree,
- new evidence contradicts the original plan.

A worker's confidence is not proof.

# 24. Fable Experience Director

Fable is a first-class specialist for substantial UI/UX work.

Primary responsibilities:
- evaluate end-to-end interaction quality,
- identify friction in real workflows,
- reason about physical tablet/phone behaviour,
- challenge density/hierarchy/navigation,
- protect the speech-versus-screen interaction model,
- review the implemented experience independently after the coding pass.

Preferred substantial UI loop:

Fable direction
→ Opus architecture/constraints where needed
→ implementation worker(s)
→ browser/device/QA evidence
→ Fable post-build review
→ bounded correction
→ technical review
→ GPT Director review

Fable is not the sole design authority.

Current authority order remains:
1. explicit owner request,
2. current product-memory decisions/invariants,
3. current DESIGN.md,
4. current functional/safety behaviour,
5. specialist design/experience tools.

# 25. Engineering Orchestrator

The bridge watcher is a reliable single-worker foundation, not the final multi-agent runtime.

The next engineering layer should be an Orchestrator that can:

- accept multiple queued tasks,
- decompose broad objectives,
- select model + effort under quality-first policy,
- create isolated worker workspaces/branches,
- run independent workers concurrently where scope is genuinely separable,
- enforce per-task boundaries,
- collect test/evidence artifacts,
- route results to independent reviewers,
- integrate successful candidates,
- stop/escalate on disagreement or repeated failure.

Rule:

> one worker = one task = one mutable workspace = one candidate result.

Do not obtain parallelism by weakening the existing watcher lock and running several writers in one checkout.

# 26. Infrastructure self-maintenance

Routine infrastructure changes should eventually stop requiring the owner to operate the shell.

Target flow:

candidate infrastructure change
→ deterministic tests
→ independent security/architecture review
→ exact versioned artifact
→ owner approval where required
→ Privileged Action Broker / Infrastructure Controller
→ versioned install
→ health verification
→ smoke test
→ automatic rollback on failure
→ update current truth

This applies to:
- bridge watcher,
- Engineering Orchestrator,
- worker manager,
- model router,
- deployment controller,
- observability/control services,
- CROOKS backend releases.

No component should be able to give itself unrestricted new privilege, replace itself, and certify the result without an independent control plane.

Termius/SSH should remain available as break-glass access, not a normal deployment path.

# 27. Evolution without ossification

Self-improvement must be allowed to remove obsolete structure, not only append more structure.

A successful new system may make an old system unnecessary.

Examples:
- an event-driven capability can retire an old polling path,
- a stronger World/Attention abstraction can eliminate an intermediate legacy layer,
- a new product direction can replace an old UI language,
- a consolidated specialist role can make another agent role redundant.

The engineering organisation should explicitly search for deletion/simplification opportunities during major releases.

Historical context is used to:
- preserve lessons,
- explain rationale,
- prevent known regressions,
- support migration.

Historical context is **not** a requirement to reproduce historical form.

Before a substantial release, create a curated Active Context Pack using `EVOLUTION_POLICY.md` and `DIRECTOR_PROTOCOL.md`.

A future worker should be able to say:

> “This old component no longer has a unique responsibility; its required outcomes are covered elsewhere; retire it.”

and have deletion considered a legitimate improvement rather than an architectural failure.

