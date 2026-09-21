# Engineering Control Plane VNext — Bridge, Termius and Claude Workflow

**Status:** ACTIVE ENGINEERING DIRECTION / IMPLEMENTATION PLAN
**Date:** 2026-09-21
**Scope:** bridge throughput, task identity, Termius/tmux operation, worker isolation, reviewer independence, event-driven continuation, machine-readable state

This document records lessons observed while running the dual-stream Orchestrator-freeze and CLIVE Live Experience work. It is evidence from the current manual/single-worker control plane, not a claim that the final Orchestrator already exists.

No runtime/systemd/watcher modification is authorised merely by this document.

## 1. Observed problem

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

## 6. Reviewer independence becomes a scheduler invariant

Candidate/result records must identify the worker that authored them.

For gates requiring independence:

    reviewer_id != author_worker_id

If no eligible reviewer exists, transition to a visible routing block. Do not quietly send the same author another "independent" review prompt.

Where risk justifies it, independence should also vary model/session/context, not merely worktree.

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

### Phase 0 — now, repository-only
- record this doctrine;
- use persistent tmux sessions for manual/Termius workers;
- use isolated external worker worktrees;
- require exact-SHA + worker identity + result metadata in handoffs;
- keep the hourly controller as reconciliation;
- keep hard runtime boundaries unchanged.

### Phase 1 — repository implementation
- define task/result JSON schemas;
- implement queue/state library and tests;
- implement generated ACTIVE_STATE;
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
