# Engineering Control Plane VNext — Bridge, Termius and Claude Workflow

**Status:** SUPERSEDED as an implementation plan on 2026-09-25 and kept as history (was ACTIVE ENGINEERING DIRECTION / IMPLEMENTATION PLAN). The durable requirements named in the notice below remain active.
**Date:** 2026-09-21
**Scope:** bridge throughput, task identity, Termius/tmux operation, worker isolation, reviewer independence, event-driven continuation, machine-readable state

> **Status as of 2026-09-25 (the 2026-09-21 plan is kept unchanged below):** this plan's rollout is over. Its goal was reached by a different route, so do not follow its sequencing.
>
> - **History: the bridge.** §1–§3 describe the Git bridge (`crooks-ai-bridge`) and its watcher as the current workflow. They were the 2026-09-21 workflow. The bridge watcher was retired on 2026-09-25 (DEC-058). The `bridge/tasks` record shape in §3 was never built.
> - **History: the phases in §11.** Phase 0 was the 2026-09-21 operating practice. The Phase 1 repository candidate `8588776455a1832da763810064cacb47d7192ef4` received `REJECT — REPAIR REQUIRED` (CURRENT_TRUTH, 2026-09-21), and the control-plane-progress stream was retired on 2026-09-24 (DEC-058). Phase 2 (an isolated watcher/orchestrator trial) and Phase 3 (watcher runtime adoption) are no longer open steps: the watcher they would have adopted is retired.
> - **What replaced them.** The engineering path is the remote engineering loop: Objective Intake + Engineering Dispatcher V1 around the frozen kernel, with Remote Engineering Control V1 as its bounded inbox and status projection ([ENGINEERING_DISPATCHER_V1.md](./ENGINEERING_DISPATCHER_V1.md), [REMOTE_ENGINEERING_CONTROL_V1.md](./REMOTE_ENGINEERING_CONTROL_V1.md)). Its builders work in isolated workspaces on the machines listed in [CURRENT_TRUTH.md](./CURRENT_TRUTH.md). Phase 4's aims (one workspace per worker, independent review, an integration gate) are carried by that loop and by the one-trunk rule (DEC-058). Task-specific model routing is not in place: all builders run `claude-opus-5-5`.
>
> These requirements from this document remain active and bind the remote loop:
>
> - **Reviewer independence (§6, DEC-013).** The reviewer is never the author, and identity is issued or bound by the controller rather than self-asserted by a worker. The dispatcher and kernel enforce the first part. The worker's identity is still the session CLIVE chose, not a cryptographic binding (ENGINEERING_DISPATCHER_V1, "Declared, not verified").
> - **Progress telemetry (§5.1, DEC-055).** Liveness and meaningful progress are different facts, and progress is operational telemetry, never hidden model reasoning. The dispatcher records heartbeats and progress separately, and the loop publishes a status projection. The richer progress events and operator progress view described in §5.1 are still a requirement, not a claim.
> - **Machine-readable results, state separate from curated memory, and explicit failure classes (§4, §7, §9).**
> - **Structured critical semantics, the verification stopping rule and obvious continuation (§8, §8.1, §8.2; DEC-057).**
> - **Starvation prevention and the success criteria (§10, §12),** read against the remote loop rather than the bridge. The Termius items are history.

This document records lessons observed while running the dual-stream Orchestrator-freeze and CLIVE Live Experience work. It is evidence from the current manual/single-worker control plane, not a claim that the final Orchestrator already exists.

No runtime/systemd/watcher modification is authorised merely by this document.

## 1. Observed problem

*History (2026-09-25): §1–§3 describe the bridge-era workflow of 2026-09-21. The bridge watcher is retired; see the status notice at the top.*

The existing Git bridge is a valuable verified single-worker foundation, but it behaves operationally like a **single-slot mailbox**.

Observed consequences:
- a repair/review loop in one stream can occupy the lane while another legitimate stream waits;
- an hourly supervisory controller can discover completion up to almost an hour late;
- the bridge may be pending=no and lock=free while useful follow-on work exists conceptually but has not been dispatched;
- reviewer independence has required prompt-level policing and has previously routed repair authors back toward their own work;
- large prose outboxes are excellent audit evidence but expensive for controllers to parse for simple state;
- volatile exact-SHA engineering truth drifts faster than curated prose CURRENT_TRUTH can reasonably be maintained.

The remedy is not weaker review. It is a stronger control plane.

## 2. Immediate operating rule in Termius

Until the Orchestrator replaces this workflow:

> **one task = one worktree = one persistent tmux session = one candidate identity**

Preferred worker path:

    /opt/crooks-workers/<task-id>/<attempt-id>/

Do not place normal worker attempts inside the canonical Builder checkout in a way that dirties it.

Recommended Termius pattern:

    tmux new -s <task-id>
    # run the worker inside the isolated worktree

Detach without terminating the worker:

    Ctrl-b d

Return later:

    tmux ls
    tmux attach -t <task-id>

Closing Termius/mobile SSH must not be equivalent to terminating the engineering worker.

## 3. Replace the single inbox with task records

Target repository shape:

    bridge/
      tasks/
        <task-id>.json
      results/
        <task-id>/<attempt-id>.json
      events/
        ...

A task record should contain at minimum:
- task ID;
- stream / objective ID;
- task type: build / repair / review / integration / evidence;
- repository;
- exact base SHA;
- target branch;
- allowed paths/scope;
- hard boundaries;
- worker identity;
- reviewer-independence requirements;
- predecessor/dependency IDs;
- status;
- timestamps;
- retry class;
- owner-gate state.

Task records are append/update state. A new task must not overwrite another stream's instructions.

## 4. Machine-readable result contract

Every worker may still publish a human-readable handoff, but it should also publish a compact result record.

Minimum fields:
- task ID / attempt ID;
- worker ID;
- exact base SHA;
- exact result SHA;
- changed paths;
- tests/checks executed and structured outcomes;
- clean-worktree state;
- secret-scan state;
- runtime/deployment effects: expected to be NONE unless authorised;
- verdict or repair handoff;
- blocker classification;
- owner decision required: yes/no + reason;
- eligible next stage.

Controllers should not need to infer basic state from thousands of words of prose.

## 5. Event-driven continuation

Normal work should advance on completion events, not wait for an hourly poll.

Target:

> worker completes → result published → task state changes → next eligible task/reviewer is scheduled immediately

The hourly GPT controller remains valuable as:
- reconciliation;
- stalled-task detection;
- stale-state detection;
- independent supervisory review;
- recovery when an event was missed.

It should not be the normal clock that makes work continue.

## 5.1 Observable work-in-progress is first-class state

A worker being merely `running` is insufficient control-plane information.

Every active attempt should publish structured operational progress that can be consumed by:
- the deterministic scheduler;
- the hourly supervisory controller;
- Termius/operator views;
- future CLIVE engineering scenes.

Progress is **operational telemetry, not hidden model reasoning**. It should expose facts such as:
- current activity / active bounded step;
- completed step identities;
- evidence artifacts produced;
- waiting dependency or blocker;
- next known action;
- last activity change;
- last meaningful progress;
- liveness heartbeat;
- exact task/attempt/worker identity.

Heartbeat and progress are different facts. A fresh heartbeat proves liveness only. It must not reset the meaningful-progress clock or make a stalled/looping worker look productive.

The hourly supervisory loop should use this state to make a useful decision rather than only ask whether a process exists:
- progressing + no spare safe work → observe, do not interrupt;
- progressing/waiting + spare eligible worker capacity → schedule unrelated eligible work around it;
- alive but no meaningful progress → investigate evidence/logs without duplicating the attempt;
- stale liveness → reconcile process/worktree/result identity before retry;
- blocked/owner-gated → park that stream while others continue;
- completed → evaluate the already-authorised `next_action` immediately rather than waiting for another poll.

Progress streams should be append-only, ordered, exact-attempt-bound and survive controller restart. Generated `ACTIVE_STATE` should project the current useful summary so supervisors do not have to parse raw logs.

A compact operator table should make ongoing work visible, for example:

| Stream | Task | Worker | Health | Current activity | Done | Evidence | Waiting / next | Last progress |
| --- | --- | --- | --- | --- | ---: | ---: | --- | --- |
| freeze | exact-SHA review | reviewer-2 | progressing | mutation-testing evaluator | 3 | 5 | recompute verdict | 2m ago |
| live-v0.5 | home lifecycle | builder-1 | waiting | device evidence captured | 4 | 7 | physical mic check | 6m ago |

Do not invent percentage-complete estimates where the task has no trustworthy bounded denominator. Prefer concrete completed milestones and evidence over cosmetic progress bars.

## 6. Reviewer independence becomes a scheduler invariant

Candidate/result records must identify the worker that authored them.

For gates requiring independence:

    reviewer_id != author_worker_id

If no eligible reviewer exists, transition to a visible routing block. Do not quietly send the same author another "independent" review prompt.

Where risk justifies it, independence should also vary model/session/context, not merely worktree.

**Phase 1 identity limitation:** the repository simulator's `worker_id` fields are plain strings and therefore are not trustworthy attestations when supplied by a worker. They are placeholders for controller-issued identity. Before any runtime phase relies on reviewer independence for authority, worker/attempt identity must be issued or bound by the controller rather than self-asserted by the worker. Repository-only Phase 1 may exercise the scheduling semantics with strings, but must not claim cryptographic or process-level identity enforcement.

## 7. Generated active engineering state

Curated product memory should not be forced to track every repair SHA.

Create a generated/machine-maintained active-state view such as:

    engineering/ACTIVE_STATE.json

It should expose:
- stream;
- objective;
- branch;
- exact HEAD;
- current stage;
- current task/attempt;
- worker/reviewer;
- bridge/queue state;
- last transition;
- blocker/owner gate;
- evidence/result references.

Future agents resolve this first, then read curated product doctrine.

## 8. Critical semantics should be structured

The M-01 through M-08 freeze rounds demonstrated a systemic lesson:

> critical machine invariants should not require an ever-growing regex parser to understand unrestricted English.

Preferred direction:
- represent critical contract facts in typed JSON/YAML/Pydantic/tables or a constrained DSL;
- mechanically verify that structure;
- generate or explicitly bind human-readable prose to it.

If prose itself must be normative, define a constrained semantic grammar and fail closed outside that grammar.

Do not indefinitely grow an accidental natural-language parser for authority/safety invariants.

## 8.1 Verification must have a stopping rule

Adversarial review exists to reduce uncertainty about the **subject**. It must not become a self-expanding product that indefinitely blocks the subject because the verifier can always invent another weakness in its own machinery.

Operating rule:
- a finding may block the subject only when it demonstrates a material defect in subject behaviour, authority, safety, state semantics or required evidence;
- a defect confined to the verification apparatus becomes a separate verifier task;
- verifier-only repair loops do not reset the subject's acceptance evidence unless the verifier defect invalidates that evidence;
- two consecutive rounds producing only verifier-apparatus defects are a convergence signal: park that verifier path, preserve the evidence and continue through a more suitable verification mechanism;
- reviewers are explicitly allowed to return READY/ACCEPT when no material subject defect remains;
- prefer structured contracts and direct behavioural evidence over adding grammar to parse unrestricted prose.

The practical objective is **uncertainty reduction and useful product progress**, not the number of adversarial rounds.

## 8.2 Obvious continuation should not wait for the owner or hourly controller

A worker/controller should continue automatically when the next action is a mechanically implied stage of the **same already-authorised objective** and does not widen authority, scope, risk or side effects.

Examples:
- bounded implementation finishes cleanly → publish exact result/evidence;
- repair finishes → schedule a fresh eligible independent review of that exact SHA;
- review returns a bounded unambiguous defect → schedule one bounded repair under the same contract;
- a required test/evidence step is still outstanding and is already named in the task contract → run it;
- publication acknowledgement is missing but remote identity can be reconciled read-only → reconcile and complete publication bookkeeping;
- one sibling task completes while another remains eligible → continue the eligible sibling rather than waiting for an hourly poll.

This is **continuation**, not new planning authority.

A worker/controller must stop or escalate when continuation would require:
- changing the objective, acceptance criteria or allowed scope;
- choosing between materially different product/architecture directions;
- relaxing a safety invariant or review requirement;
- new credentials/secrets, connector permissions or privilege;
- deployment/runtime/systemd/watcher mutation;
- business writes or external spend;
- destructive cleanup;
- owner-only adoption, sequencing changes or release approval;
- proceeding despite contradictory evidence or an unresolved blocker.

Every result record should therefore expose a machine-readable `next_action` with:
- `kind`: continue / review / repair / evidence / integrate / blocked / owner_gate / done;
- `reason`;
- exact subject/base SHA;
- whether the action is mechanically authorised by the current task revision;
- required worker/reviewer eligibility;
- any remaining evidence requirements.

The scheduler validates `next_action` against policy. It does not blindly trust a model's suggestion.

The operating principle is:

> **Do not ask the owner or wait for the hourly supervisor to approve the obvious next step of an already-approved bounded workflow. Do stop when the next step changes what is being decided or what authority is required.**

## 9. Queue and retry semantics

Different failures require different treatment.

**Transient:** provider outage, network failure, temporary rate/transport issue → bounded retry/backoff.

**Deterministic:** dirty workspace, invalid SHA, missing permission, unsupported task contract, reviewer conflict, required credential unavailable → BLOCKED/ESCALATED once, not repeated blind retries.

**Obsolete:** predecessor/candidate changed → mark result/task obsolete; never apply verdict to a new SHA.

**Owner-only:** deployment, credentials, privilege expansion, business writes, sequencing/product-intent decisions outside recorded doctrine → park that stream while unrelated work continues.

## 10. Dual-stream fairness

Until genuine multi-worker execution exists, use an explicit fairness rule:

- an in-flight task is never interrupted;
- a stream at an owner-only gate does not block another stream;
- repeated repair/review cycles in one stream must not prevent repository-only progress in another stream;
- when the shared worker becomes free, dispatch the highest-value eligible task rather than mechanically continuing the same stream forever;
- record why a stream was intentionally parked.

This is not fake concurrency. It is starvation prevention while running a single shared lane.

## 11. Implementation phases

*History (2026-09-25): these phases are the 2026-09-21 rollout sequence. They are not an open plan. The remote engineering loop replaced them; see the status notice at the top.*

### Phase 0 — now, repository-only
- record this doctrine;
- use persistent tmux sessions for manual/Termius workers;
- use isolated external worker worktrees;
- require exact-SHA + worker identity + result metadata in handoffs;
- keep the hourly controller as reconciliation;
- keep hard runtime boundaries unchanged.

### Phase 1 — repository implementation
- define task/result/progress-event JSON schemas;
- implement queue/state library and tests;
- implement generated ACTIVE_STATE with current progress projection;
- add a compact Termius/operator progress view;
- add reviewer-eligibility checks;
- add deterministic/transient/owner/obsolete blocker classification;
- test with simulated dual streams.

No systemd/watcher deployment yet.

### Phase 2 — isolated watcher/orchestrator trial
- adapt an isolated watcher candidate to consume queued tasks/events;
- completion wakes scheduling immediately;
- prove single-worker compatibility first;
- replay current freeze/V0.5 starvation scenarios;
- adversarially test duplicate dispatch, stale SHA, late results and reviewer conflict.

Requires normal independent review. Still not production promotion.

### Phase 3 — controlled runtime adoption
Only with explicit owner authority:
- install reviewed watcher/orchestrator runtime;
- verify rollback;
- verify no secret/connector/privilege expansion;
- monitor queue/event behaviour.

### Phase 4 — real parallel workers
After isolation/integration semantics are proven:
- bounded concurrency;
- one workspace per worker;
- independent reviewer pool;
- integration gate;
- task-specific model routing.

## 12. Success criteria

The control-plane upgrade is successful when:
- closing Termius does not kill legitimate workers;
- two independent streams can be queued without overwriting each other;
- completed work advances without waiting for an hourly tick;
- no task is duplicated because a controller could not see current state;
- stale verdicts cannot cross SHA boundaries;
- repair authors cannot satisfy independent-review gates;
- deterministic blocks do not burn retry loops;
- one stalled stream does not starve another;
- every stage has exact machine-readable identity/evidence;
- Git remains the auditable source of record.

The goal is higher throughput **without trading away the precision learned from the freeze work**.
