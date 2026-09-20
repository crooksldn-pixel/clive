# Engineering Orchestrator V1 — State Store and Command Contract

**Status:** FREEZE CANDIDATE — normative companion  
**Date:** 2026-09-20

This file makes the control-plane state model executable. It resolves the mechanism gap left by prose lifecycle diagrams.

## 1. Database records

All authoritative records live in one SQLite database under the deterministic kernel. Workers and reviewers never receive direct DB write access.

### `meta`
- `schema_version INTEGER NOT NULL`
- `controller_epoch INTEGER NOT NULL`
- `operational_mode TEXT NOT NULL` — `RUNNING|DRAINING|BLOCKED`
- `cutover_watermark TEXT NULL`

Exactly one row.

### `task`
- `task_id TEXT PRIMARY KEY`
- `current_revision INTEGER NOT NULL`
- `state TEXT NOT NULL`
- `created_at TEXT NOT NULL`
- `updated_at TEXT NOT NULL`
- `blocking_reason_code TEXT NULL`

### `task_revision`
Primary key `(task_id, revision)`.

Required fields:
- source/authorising reference digest;
- objective digest;
- non-goals digest;
- repository;
- base SHA;
- product-memory SHA;
- context-manifest digest;
- environment-manifest digest;
- scope/policy digest;
- risk class;
- acceptance-policy digest;
- review-policy digest;
- retry/correction policy;
- created timestamp.

Revision rows are immutable.

### `finding`
- `finding_id TEXT PRIMARY KEY`
- subject kind `CANDIDATE|INTEGRATION`;
- subject ID;
- exact subject SHA;
- `task_id TEXT NULL` / `revision INTEGER NULL` — mandatory when subject kind is `CANDIDATE`; retained when an `INTEGRATION` finding is attributable to exactly one source task/candidate, otherwise NULL;
- source kind/id;
- severity;
- `blocking INTEGER NOT NULL` — computed by kernel policy from severity and the subject's acceptance/review policy at insert time; a model cannot set or clear it;
- disposition `OPEN|RESOLVED|BLOCKED|OBSOLETE`;
- disposition reason digest — NULL while disposition is `OPEN`, mandatory once it leaves `OPEN`;
- summary digest;
- evidence reference;
- created/resolved timestamps.

A finding is authoritative for its own subject, and findings are queryable by `(subject kind, subject ID)`. `candidate.accept` evaluates blocking findings whose subject is that candidate; `integration.verify` evaluates blocking findings whose subject is that integration. Integration findings are therefore first-class and are not merely re-discovered by the next reviewer. Task/candidate lineage is preserved wherever it exists, so CG-04's partial-progress representation extends to integrations without losing source attribution.

### `attempt`
- `attempt_id TEXT PRIMARY KEY`
- subject kind `TASK|INTEGRATION`;
- subject ID — task ID when subject kind is `TASK`, integration ID when `INTEGRATION`;
- subject revision — task revision when subject kind is `TASK`; fixed at `1` when `INTEGRATION`, because a corrected integration is a new `integration_id` under `parent_integration_id` rather than a new revision of the same record;
- state `CREATED|STARTING|RUNNING|CANDIDATE_READY|CLOSED`;
- terminal disposition nullable `SUCCEEDED|FAILED|CANCELLED|FENCED|QUARANTINED`;
- workspace ID/path;
- measured base SHA;
- controller epoch;
- fencing token;
- provider/model/effort/runner kind;
- `running_process_group_identity` — the **execution-ceiling discriminator** of §3A.3. NULL until the attempt commits `RUNNING`, non-NULL from then on, written exactly once in that commit, and never written by any other edge. It is the durable authoritative fact of whether this attempt ever reached `RUNNING`, and §3A.2 is its only reader. It is deliberately **not** the handle used to find and stop an owned process group, and §3A.3 forbids promoting it into that role; §3A.3 gives the cleanup role permanently to `lease.owned_process_group_handle`, which is written once, earlier, and is never replaced while the attempt is live, so neither field is asked two questions at once;
- start/end timestamps;
- failure code nullable.

For `subject_kind = TASK` these columns are exactly the previous `task/revision` binding under a generalised name. No task-attempt field, precondition, transition or acceptance case (`ST-*`, `LS-*`, `WS-*`, `CXN-01..CXN-04`) changes meaning because of this generalisation; they are the `TASK` projection of this record. An `INTEGRATION` attempt is the integrator's execution record and carries the same workspace, epoch, fencing-token, process-group and disposition machinery.

### `lease`
One authoritative lease per `(subject_kind, subject_id, subject_revision)`, taken from the attempt's subject. For `subject_kind = TASK` this is exactly the previous "one authoritative lease per `(task_id, revision)`" rule; `INTEGRATION` occupies a disjoint key space and cannot collide with it.

- subject kind/ID/revision;
- attempt ID;
- controller epoch;
- fencing token;
- acquired time;
- heartbeat deadline;
- workspace ID;
- `owned_process_group_handle` — the **owned-process-group cleanup handle** of §3A.3: the durable identity of the single process group this attempt owns for its whole lifetime, committed **before** that group is created on the `CREATED -> STARTING` edge. It is **write-once** under §3A.3: once non-NULL it is never updated, replaced or cleared while the attempt is non-terminal, and no later edge — `STARTING -> RUNNING` included — writes it. NULL means no owned group has ever been created under this attempt, which is a positive proof rather than an absence of knowledge, because the write always precedes the fork. The value is a **controller-allocated, attempt-bound identity** per §3A.3, not a bare OS process-group number that the kernel could recycle onto an unrelated process.

Lease replacement and fencing-token increment occur atomically. Workspace ID and `owned_process_group_handle` are listed here to match the lease contents already required by `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §8. `owned_process_group_handle` is the cleanup handle only; the separate question of whether the attempt ever reached `RUNNING` is answered by `attempt.running_process_group_identity`, per §3A.3.

### `review_dispatch`
The durable execution record for one dispatched reviewer. Review execution is a scheduled, cancellable, crash-prone model process, so §1A requires it to be represented before it runs rather than only once a verdict arrives.

- `review_dispatch_id TEXT PRIMARY KEY`;
- subject kind `CANDIDATE|INTEGRATION`;
- subject ID;
- exact subject SHA;
- subject revision — task revision for `CANDIDATE`, `1` for `INTEGRATION`, matching the `lease` convention;
- evidence-manifest digest presented to the reviewer;
- required-review slot identity — which required independent review of the subject's review policy this dispatch fills;
- reviewer principal/session identity, including its **execution-ownership kind** `KERNEL_OWNED|EXTERNAL` — whether the reviewer runs as a process this controller forks and owns, or as an external principal whose process the kernel does not own. This kind is a declared attribute of the principal/session binding, committed durably in the same transaction that creates the `DISPATCHED` row and immutable thereafter, so it is already known before any reviewer process exists. It is the **only** authoritative answer to "does the kernel own this reviewer?"; §3A.3 forbids deriving that answer from the process-group identity field below;
- reviewer role;
- controller epoch;
- dispatch fencing token — monotonic per `(subject_kind, subject_id)`;
- state `DISPATCHED|COMPLETED|CANCELLED|FENCED|EXPIRED`;
- heartbeat deadline and expiry deadline;
- process-group/cgroup identity — the dispatch's **owned-process-group cleanup handle**, governed by the same §3A.3 write-ahead, write-once, controller-allocated rule as an attempt's. For a `KERNEL_OWNED` dispatch it is committed **before** the reviewer process group is created and is never replaced while the dispatch is non-terminal, so NULL is positive proof that no owned reviewer group exists — **not** a signal that the reviewer is external. For an `EXTERNAL` dispatch it is always NULL, cancellation relies on fencing alone, and that limitation is recorded;
- `review_id TEXT NULL` until a verdict is admitted;
- created/updated/terminal timestamps.

`DISPATCHED` is the only non-terminal state; `COMPLETED`, `CANCELLED`, `FENCED` and `EXPIRED` are terminal and a terminal dispatch can never regain authority.

Several `DISPATCHED` rows may coexist for one subject, up to the freeze-contract §19 reviewer-concurrency ceiling, because independence requires distinct reviewer principals. Review execution is therefore deliberately **not** keyed one-per-subject like `lease`, and each dispatch is fenced individually by its own dispatch fencing token. A uniqueness constraint over `(subject kind, subject ID, required-review slot)` restricted to non-terminal rows means a replacement dispatch for a slot can be created only after the previous dispatch for that slot is terminal. That is the mechanism by which cancellation, expiry or replacement fences the original reviewer **even when the subject SHA has not changed**.

### `authority_grant`
- `grant_id TEXT PRIMARY KEY`;
- authority/source reference digest;
- task/revision;
- action class;
- scope/resource digest;
- constraints digest;
- issued/expires/revoked timestamps.

### `candidate`
- `candidate_id TEXT PRIMARY KEY`;
- task/revision/attempt;
- base SHA;
- repository identity;
- candidate SHA;
- diff digest;
- changed-files digest;
- measured environment digest;
- evidence-manifest digest NULL until evidence completes;
- UNIQUE(repository identity, task_id, revision, candidate SHA);
- created timestamp.

Candidate rows are immutable. A replacement candidate is a new row.

### `evidence_manifest`
- `manifest_digest TEXT PRIMARY KEY`;
- schema version;
- subject kind `CANDIDATE|INTEGRATION`;
- subject ID;
- exact subject SHA;
- storage root/reference;
- redaction status;
- created timestamp.

The manifest schema is shared by candidate and integration evidence. The exact subject SHA is mandatory.

Canonical manifest bytes use UTF-8 canonical JSON with stable key ordering and no insignificant whitespace; SHA-256 is computed over those exact bytes.

### `review`
- `review_id TEXT PRIMARY KEY`;
- `review_dispatch_id TEXT NOT NULL` — the dispatch under whose authority this verdict was admitted; UNIQUE, so one dispatch yields at most one authoritative verdict;
- subject kind `CANDIDATE|INTEGRATION`;
- subject ID;
- exact subject SHA;
- task revision, controller epoch and dispatch fencing token presented at admission;
- evidence-manifest digest;
- reviewer principal/session identity;
- reviewer role;
- verdict `ACCEPT|CHANGES_REQUIRED|BLOCKED`;
- findings digest;
- created timestamp;
- invalidated timestamp nullable.

A review is immutable once recorded; invalidation is a separate timestamped state change caused by subject/evidence/policy change.

### `integration`
- `integration_id TEXT PRIMARY KEY`;
- `parent_integration_id TEXT NULL` for a bounded correction lineage;
- state `CREATED|INTEGRATING|EVIDENCE_READY|REVIEWING|VERIFIED|REJECTED|BLOCKED|CANCELLED`;
- target base SHA;
- ordered accepted input-SHA digest;
- integration SHA nullable until committed;
- integration-only-edit digest;
- evidence-manifest digest;
- created/updated timestamps.

### `release_candidate`
- `release_candidate_id TEXT PRIMARY KEY`;
- integration ID;
- exact integration SHA;
- evidence-manifest digest;
- GPT Director decision reference/digest;
- limitations/release-plan digest;
- created timestamp.

Release candidates are immutable V1 outputs; they carry no deployment authority.

### `delivery`
Represents publication independently from work completion.
- `delivery_id TEXT PRIMARY KEY`;
- controller epoch of the last authoritative delivery mutation;
- subject kind/id;
- destination;
- idempotency key UNIQUE;
- state `PENDING|UNKNOWN|PUBLISHED|FAILED|BLOCKED`;
- expected remote identity;
- observed remote identity;
- attempt count — the number of external publication effects that have been *initiated* for this delivery. §3C requires the increment to be committed before each effect is initiated and never decremented, which makes a non-zero count the durable evidence that an effect may already have reached the destination;
- last error/reconcile timestamp.

### `idempotency`
- `key TEXT PRIMARY KEY`;
- operation;
- canonical request digest;
- result reference;
- created timestamp.

A duplicate key with the same request digest returns the stored result. Same key with a different request digest is a conflict.

### `transition_event`
Append-only:
- monotonically increasing sequence;
- event ID;
- subject kind `TASK|INTEGRATION|CANDIDATE|REVIEW|DELIVERY` and subject ID;
- `task_id`/`revision` — mandatory for a `TASK` subject, retained for other subject kinds wherever a single source task owns the event, otherwise NULL, so an integration-only or review-only event is representable;
- attempt/candidate/review/`review_dispatch`/integration identifiers as applicable;
- from/to state;
- actor principal;
- controller epoch;
- fencing token presented and the execution record it belonged to, or NULL for a `DELIVERY` subject whose authority is the controller epoch plus delivery idempotency key/request digest;
- reason code;
- trace ID;
- payload digest;
- timestamp.

Rejected admissions are events too: a verdict or result refused with `FENCE_STALE` appends an event recording the rejection and the stale execution identity even though no state changed, as required by `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §18. Otherwise a stale reviewer or integrator would be invisible in the journal.

## 1A. Execution substrate and subject kinds

Every model-running or process-owning unit of work in V1 has a durable execution record that is created **before** its process runs, is bound to a controller epoch and a monotonic fencing token, is terminated through an owned process group, and is reconciled after controller restart. There are exactly three such units and exactly two record shapes.

| Execution unit | Record | Subject | Concurrency rule | Authority token |
| --- | --- | --- | --- | --- |
| implementation attempt | `attempt` with `subject_kind = TASK` | task revision | one authoritative `lease` per subject | lease fencing token |
| integration attempt | `attempt` with `subject_kind = INTEGRATION` | integration ID | one authoritative `lease` per subject | lease fencing token |
| review dispatch | `review_dispatch` | candidate or integration subject | at most one non-terminal dispatch per required-review slot, bounded by the reviewer-concurrency ceiling | dispatch fencing token |

The following rules apply uniformly to all three, and are the reason the substrate is generalised rather than duplicated:

- the execution record MUST exist and be non-terminal before any model process is launched for that unit;
- an in-flight unit MUST be visible in the database. Which subject states can hold one is **derived, not hand-enumerated**: a subject state is **execution-bearing** exactly when §3A or §3B admits a non-terminal execution record — an `attempt` in `CREATED`, `STARTING`, `RUNNING` or `CANDIDATE_READY`, or a `review_dispatch` in `DISPATCHED` — while the subject sits in that state. §3A's subject-binding table and §3B's binding rule are that derivation in mechanically checkable form, and adding an edge there extends this rule automatically. Under the matrices as written it derives to the `TASK` subject states `ASSIGNED`, `BUILDING`, `REVIEWING`, and the `INTEGRATION` subject states `INTEGRATING`, `REVIEWING`;
- an execution-bearing subject with **no** non-terminal execution record is an inconsistency that reconciliation MUST surface as BLOCKED, using the subject's already-listed §3 block edge — `task.block` for a `TASK` subject and `integration.block` for an `INTEGRATION` subject — with reason code `EXECUTION_RECORD_MISSING`. It MUST NOT be read as progress, it MUST NOT be left silently in that state, and it MUST NOT be resolved by blind re-dispatch. `ASSIGNED` is covered for exactly the same reason as `BUILDING`: controller-epoch fencing closes a `CREATED` or `STARTING` attempt terminally (§3A) without touching the subject, so an `ASSIGNED` task whose only attempt has just been fenced is precisely the stranded case this rule exists to catch;
- result admission MUST present the current controller epoch and the current fencing token of that exact record, and MUST be rejected with `FENCE_STALE` when the record is terminal, superseded or unknown — **including when the subject SHA has not changed**;
- cancellation, expiry and replacement each move the record to a terminal state, and that is what makes a late result stale. Candidate-mutation invalidation (freeze contract §14.3) is an additional and independent mechanism; it MUST NOT be relied on as the only one, because a stale reviewer or integrator commonly returns against an unchanged SHA;
- termination follows the §6 cancellation race contract against that record's own process group, and workspace reuse follows the freeze-contract §11 emptiness rule;
- **every** execution record of this table — implementation attempt, integration attempt and review dispatch alike — owns **at most one** controller-created process group for its entire non-terminal lifetime, and records that group in its own durable cleanup handle: `lease.owned_process_group_handle` for an attempt, the `review_dispatch` process-group/cgroup identity for a dispatch. §3A.3 states the write-ahead, write-once and controller-allocated-identity rules once, for all three, and they apply without exception. A record MUST NOT hand its cleanup handle over from one group to another, because the handed-off group becomes untracked the moment the handle is replaced;
- the durable handle used to **find and stop** an owned process group and the durable fact used to decide whether an attempt ever **reached `RUNNING`** are two different fields with two different population times, defined once in §3A.3. One MUST NOT be inferred from the other: a missing cleanup handle proves no group was created, and it MUST NOT be read as "the attempt never ran" for ceiling purposes, nor MUST a populated ceiling discriminator be used as a cleanup handle;
- whether the kernel owns a record's process at all is decided from **durable principal/role identity** — the `review_dispatch` reviewer principal's `KERNEL_OWNED|EXTERNAL` execution-ownership kind — and never from a NULL cleanup handle. Under the write-ahead rule above, NULL means "no owned group was created", which is exactly the state a crash between the handle commit and the fork leaves behind, so reading NULL as "this process belongs to someone else" would release a live kernel-owned process's slot;
- a subject transition that leaves an execution-bearing state MUST NOT strand a record this substrate created. §3.1 makes that a per-row obligation on the §3 matrix, so the guarantee is checked against the transitions themselves rather than promised here;
- restart reconciliation (freeze contract §21) covers all three record kinds before dispatch is re-enabled.

`subject_kind = TASK` is exactly the pre-existing implementation-attempt semantics under a generalised column name, so this section adds an execution substrate for integrators and reviewers without changing the task-attempt model that `ST-*`, `LS-*`, `WS-*` and `CXN-01..CXN-04` already prove.

## 2. Command surface

Commands are deterministic kernel operations. A local library/CLI/API may expose them, but semantics are identical.

| Command | Allowed caller | Core effect |
| --- | --- | --- |
| `task.create` | Director/intake adapter | create PROPOSED task + revision 1 |
| `task.revise` | Director | from any nonterminal task, create immutable new revision, fence obsolete attempt/lease, mark old revision superseded and set new revision to PROPOSED |
| `task.plan` | Director through validated channel | PROPOSED/BLOCKED/ESCALATED -> PLANNED after contract/context validation |
| `task.block` | kernel/policy/reviewer/Director channel | enter BLOCKED with typed reason; fences every non-terminal execution record of the subject per §3.1 |
| `task.escalate` | kernel/reviewer/Director | enter ESCALATED; fences every non-terminal execution record of the subject per §3.1 |
| `task.fail` | kernel | enter FAILED when approved execution budget exhausted; fences every non-terminal execution record of the subject per §3.1 |
| `task.cancel` | authorised controller/Owner/Director policy | fence active attempt; enter CANCELLED |
| `task.supersede` | Director/Owner | fence active attempt; enter SUPERSEDED |
| `attempt.assign` | scheduler | PLANNED or bounded-correction REJECTED -> ASSIGNED; create a fresh attempt/workspace reservation + lease |
| `attempt.start` | runner adapter | ASSIGNED -> BUILDING only after measured preflight; commits the write-once §3A.3 owned-process-group handle before creating the attempt's single process group, runs preflight and the model inside that same group without ever replacing the handle, and writes the §3A.3 ceiling discriminator in the `RUNNING` commit |
| `attempt.heartbeat` | current runner adapter | renew the presenting attempt's current lease only; valid for either attempt subject kind |
| `attempt.cancel_ack` | runner/process manager | record process-tree stop/quarantine outcome; valid for either attempt subject kind |
| `candidate.register` | deterministic collector | while task remains BUILDING, create durable Candidate immediately after immutable commit identity is measured; does not itself advance task state |
| `evidence.register` | collector/CI adapter | attach content-addressed evidence; when required manifest is complete, advance BUILDING -> EVIDENCE_READY atomically |
| `review.request` | review coordinator | EVIDENCE_READY -> REVIEWING and create one non-terminal `review_dispatch` per required-review slot, each bound to exact subject SHA, subject revision, controller epoch and a fresh dispatch fencing token, before any reviewer process is launched |
| `review.record` | validated independent reviewer channel | persist exact-SHA verdict/findings under a named live dispatch; that dispatch becomes `COMPLETED` in the same transaction |
| `review.cancel` | review coordinator/kernel policy | move a named `review_dispatch` to `CANCELLED`, `FENCED` or `EXPIRED` and stop its owned process group per §6; no later verdict from that dispatch is admissible |
| `candidate.accept` | kernel policy | REVIEWING -> ACCEPTED only when all required reviews/findings satisfy policy; fences any non-terminal `review_dispatch` still owned by the candidate per §3.1 |
| `candidate.reject` | kernel policy | REVIEWING -> REJECTED; fences every non-terminal `review_dispatch` still owned by the candidate per §3.1, including the dispatches that have not reported |
| `integration.create` | integration coordinator | create separate CREATED integration from one or more exact ACCEPTED candidate SHAs |
| `integration.begin` | integrator coordinator | CREATED -> INTEGRATING and atomically create the integration `attempt` (`subject_kind = INTEGRATION`), workspace reservation, controller epoch, fencing token and authoritative `lease`; allocation only — no model/toolchain preflight and no integrator process launch occur here |
| `integration.start` | runner adapter | while the integration remains INTEGRATING, drive its allocated attempt through STARTING -> RUNNING only after the measured §5B/§11 preflight passes; the write-once §3A.3 owned-process-group handle is committed before the integration attempt's single process group is created, preflight and the integrator run inside that same group, and the §3A.3 ceiling discriminator is written in the `RUNNING` commit without replacing the handle |
| `integration.register` | deterministic collector | INTEGRATING -> EVIDENCE_READY after integration SHA + evidence exist; requires the current epoch/fencing token of the live integration attempt |
| `integration.review_request` | review coordinator | EVIDENCE_READY -> REVIEWING and create one non-terminal `review_dispatch` per required integrated-review slot, exactly as `review.request` does for candidates |
| `integration.verify` | kernel policy/CI/review coordinator | REVIEWING -> VERIFIED when required integrated gates pass and no blocking finding for that integration subject is `OPEN`/`BLOCKED` |
| `integration.reject` | kernel policy | REVIEWING -> REJECTED on blocking integrated finding; fences every non-terminal `review_dispatch` of the integration per §3.1; REJECTED integration is immutable/terminal and any correction uses a new integration record with parent_integration_id |
| `integration.block` | kernel/policy/review coordinator | CREATED/INTEGRATING/EVIDENCE_READY/REVIEWING -> BLOCKED with typed reason; fences every non-terminal integration `attempt` and `review_dispatch` of the integration per §3.1; no automatic retry |
| `integration.cancel` | authorised controller/Director policy | CREATED/INTEGRATING/EVIDENCE_READY/REVIEWING/BLOCKED -> CANCELLED. If still `CREATED` before `integration.begin`, no attempt/lease exists and the subject is cancelled directly. Otherwise the allocated integration attempt's lease is fenced and its process group stopped per §6, and any non-terminal `review_dispatch` is fenced. If an owned process group cannot be proven empty the attempt closes `QUARANTINED`, the workspace is not reused and the integration goes to BLOCKED instead of CANCELLED |
| `release_candidate.mark` | GPT Director validated channel + kernel policy | create immutable ReleaseCandidate from VERIFIED integration |
| `delivery.publish` | publication adapter | create/reuse a durable PENDING delivery intent before the external publication effect; after the effect, persist exact observed success as PUBLISHED or an ambiguous outcome as UNKNOWN according to §3C |
| `delivery.reconcile` | publication adapter / controller reconciliation | reconcile a PENDING or UNKNOWN delivery against authoritative remote state and move it to PUBLISHED, FAILED or BLOCKED only through §3C |
| `delivery.block` | kernel/policy/publication adapter | move PENDING/UNKNOWN/FAILED delivery to BLOCKED with a typed persisted reason |
| `controller.reconcile` | authoritative controller | observe DB/process/workspace/remote truth across all three execution record kinds of §1A **and delivery publication state**; no blind effects |
| `controller.drain` | authorised operator/controller policy | set DRAINING; no new assignments |
| `controller.resume` | authorised operator/controller policy | RUNNING only after health/reconciliation |
| `status.snapshot` | read-only consumer | return current deterministic state |

No model receives an operation that bypasses these guards.

## 3. Task and integration subject transition matrix

Any **task or integration subject-state** transition not listed in §3 is forbidden. Attempt, review-dispatch and delivery-record transitions are governed by §3A, §3B and §3C respectively; a command that mutates more than one record must satisfy every applicable matrix.

| From | Command | To | Mandatory preconditions |
| --- | --- | --- | --- |
| none | task.create | PROPOSED | valid unique task/idempotency key; authorised intake reference |
| PROPOSED | task.plan | PLANNED | complete immutable revision; context/authority current; no missing required source |
| BLOCKED | task.plan | PLANNED | blocker resolved and same revision remains valid; otherwise task.revise first |
| ESCALATED | task.plan | PLANNED | escalation resolved; same-revision contract still valid |
| PLANNED | attempt.assign | ASSIGNED | controller RUNNING; capacity; no current lease; dependencies accepted; **per-revision attempt ceiling not exhausted**; workspace reservation succeeds |
| ASSIGNED | attempt.start | BUILDING | current epoch/fence; measured clean exact base; tool/capability roster passes; process ownership established |
| BUILDING | candidate.register | BUILDING (Candidate row added) | current epoch/fence; candidate commit measured; Candidate persisted before evidence collection; evidence digest may be NULL |
| BUILDING + Candidate | evidence.register | EVIDENCE_READY | current epoch/fence; required evidence artifacts durably imported; manifest digest validated and attached; the same transaction closes the `CANDIDATE_READY` attempt `SUCCEEDED`, so no execution record survives the move out of BUILDING. [EXEC-ATOMIC-CLOSE: §3A CANDIDATE_READY -> CLOSED / SUCCEEDED] |
| EVIDENCE_READY | review.request | REVIEWING | exact candidate/evidence frozen; required reviewer policy resolved; one non-terminal `review_dispatch` created per required-review slot under the current revision/epoch and a fresh dispatch fencing token |
| REVIEWING | review.record | REVIEWING (Review row added) | presented `review_dispatch_id` exists, is in state `DISPATCHED`, belongs to this exact subject/SHA, and presents the current task revision, controller epoch and that dispatch's current fencing token; presenting reviewer principal equals the dispatch's bound principal; §9 independence holds. The dispatch becomes `COMPLETED` in the same transaction. Any other case is rejected with `FENCE_STALE` and no Review row is written |
| REVIEWING | review.cancel | REVIEWING (dispatch terminal) | caller authorised or deterministic expiry/replacement condition met; dispatch moves to `CANCELLED`/`FENCED`/`EXPIRED`; owned reviewer process group stopped per §6; rejection of any later verdict from it is thereafter automatic |
| REVIEWING | candidate.accept | ACCEPTED | all required independent reviews ACCEPT, each admitted under a then-live dispatch for a distinct required-review slot; no `OPEN`/`BLOCKED` blocking finding for this candidate subject; context still current. `ACCEPTED` is terminal, so any `review_dispatch` still `DISPATCHED` is fenced before the subject transition commits. [EXEC-FENCE] |
| REVIEWING | candidate.reject | REJECTED | one or more required reviews CHANGES_REQUIRED or blocking finding for this candidate subject. Rejection is decidable from one verdict while sibling dispatches are still live, so every `review_dispatch` of this candidate that is still `DISPATCHED` is fenced, its owned reviewer process group stopped per §6 and its required-review slot released, before `REJECTED` commits. [EXEC-FENCE] |
| REJECTED | attempt.assign | ASSIGNED | same task revision; correction budget available; **per-revision attempt ceiling not exhausted**; fresh attempt/fence; prior candidate retained |
| ACCEPTED task(s) | integration.create | integration CREATED | one or more exact accepted candidate SHAs; explicit target base; dependencies/context current; source task states remain ACCEPTED |
| integration CREATED | integration.begin | integration INTEGRATING | controller RUNNING; integration capacity available; no current integration lease; workspace reservation succeeds; integration `attempt` (`subject_kind = INTEGRATION`) and authoritative `lease` are created atomically; **no preflight and no integrator process launch occur in this command** |
| integration INTEGRATING | integration.start | integration INTEGRATING | current integration epoch/fence and reserved workspace; the allocated integration attempt is CREATED or STARTING; §3A owns the attempt-state edges; measured exact base/branch/environment/tool/capability preflight passes before RUNNING, and the attempt's single owned process group — established with its write-once handle on `CREATED -> STARTING` per §3A.3 and never replaced — already contains both preflight and the integrator when RUNNING is committed |
| integration INTEGRATING | integration.register | integration EVIDENCE_READY | current epoch/fencing token of the live integration attempt; integration SHA independently measured; required evidence manifest exists; the integration attempt reaches `CANDIDATE_READY` and then `CLOSED / SUCCEEDED` in that same transaction. [EXEC-ATOMIC-CLOSE: §3A CANDIDATE_READY -> CLOSED / SUCCEEDED] |
| integration EVIDENCE_READY | integration.review_request | integration REVIEWING | required integrated reviewer policy resolved; one non-terminal `review_dispatch` created per required integrated-review slot |
| integration REVIEWING | integration.verify | integration VERIFIED | all required integrated tests/reviews pass, each verdict admitted under a then-live dispatch; no blocking finding whose subject is this integration is `OPEN` or `BLOCKED`; where this integration carries `parent_integration_id`, every unresolved inherited finding has an explicit `RESOLVED`/`OBSOLETE` disposition with a recorded reason; any `review_dispatch` still `DISPATCHED` is fenced before `VERIFIED` commits. [EXEC-FENCE] |
| integration REVIEWING | integration.reject | integration REJECTED | blocking finding for this integration subject or required gate failure; every `review_dispatch` of this integration that is still `DISPATCHED` is fenced, its owned reviewer process group stopped per §6 and its slot released, before `REJECTED` commits. [EXEC-FENCE] |
| integration CREATED/INTEGRATING/EVIDENCE_READY/REVIEWING | integration.block | integration BLOCKED | deterministic dependency/authority/evidence/resource blocker; exact reason persisted; every non-terminal integration `attempt` and `review_dispatch` of this integration is terminally fenced and its owned process group stopped per §6 before `BLOCKED` commits, unconditionally. This is also the edge §1A reconciliation uses for an execution-bearing INTEGRATION subject found with no non-terminal execution record, carrying `EXECUTION_RECORD_MISSING`. [EXEC-FENCE] |
| integration CREATED | integration.cancel | integration CANCELLED | caller authorised; `integration.begin` has not allocated an attempt/lease/workspace, so cancellation is a direct subject-state transition with no fictitious execution record to fence |
| integration INTEGRATING/EVIDENCE_READY/REVIEWING/BLOCKED | integration.cancel | integration CANCELLED | caller authorised; the allocated integration attempt's `lease` is fenced and any owned process group is stopped through the §6 TERM/grace/KILL sequence; process group verified empty; every non-terminal `review_dispatch` for this integration is fenced and its slot released, before `CANCELLED` commits. [EXEC-FENCE] |
| integration INTEGRATING/EVIDENCE_READY/REVIEWING/BLOCKED | integration.cancel where an owned process group cannot be proven empty | integration BLOCKED | integration attempt closes `QUARANTINED` — itself a terminal disposition, so the record is not left non-terminal — integration workspace is not reused, non-terminal `review_dispatch` rows are still fenced, and the blocking reason is persisted. Cancellation never reports CANCELLED on unproven cleanup. [EXEC-FENCE] |
| integration VERIFIED | release_candidate.mark | ReleaseCandidate record | GPT Director independently accepts exact integrated SHA/evidence/limitations |
| any nonterminal active | task.block | BLOCKED | typed deterministic reason persisted; every non-terminal `attempt` and `review_dispatch` owned by the task is terminally fenced and its owned process group stopped per §6 before `BLOCKED` commits — unconditionally, not only when continuation is judged unsafe, because `BLOCKED` is outside the execution-bearing set and no live record may survive there. [EXEC-FENCE] This is also the edge §1A reconciliation uses for an execution-bearing TASK subject — `ASSIGNED`, `BUILDING` or `REVIEWING` — found with no non-terminal execution record, carrying `EXECUTION_RECORD_MISSING`; no new transition and no blind re-dispatch is introduced for that case |
| any nonterminal active | task.escalate | ESCALATED | ambiguity/decision beyond automatic authority; `ESCALATED` waits on a human decision of unbounded duration, so every non-terminal `attempt` and `review_dispatch` owned by the task is terminally fenced and its owned process group stopped per §6 before `ESCALATED` commits, and the freed review slot/execution concurrency is immediately reusable. [EXEC-FENCE] |
| PROPOSED/PLANNED/ASSIGNED/BUILDING/EVIDENCE_READY/REVIEWING/REJECTED/BLOCKED/ESCALATED/FAILED | task.cancel | CANCELLED | caller authorised; any active lease fenced immediately; every non-terminal `attempt` and `review_dispatch` owned by the task is terminally closed and its owned process group stopped per §6 before `CANCELLED` commits; no later result admitted. [EXEC-FENCE] |
| PROPOSED/PLANNED/ASSIGNED/BUILDING/EVIDENCE_READY/REVIEWING/REJECTED/BLOCKED/ESCALATED/FAILED | task.supersede | SUPERSEDED | replacement revision/objective reference recorded; every non-terminal `attempt` and `review_dispatch` owned by the task is terminally fenced and its owned process group stopped per §6 before `SUPERSEDED` commits. [EXEC-FENCE] |
| PROPOSED/PLANNED/ASSIGNED/BUILDING/EVIDENCE_READY/REVIEWING/REJECTED/BLOCKED/ESCALATED/FAILED | task.revise | PROPOSED (new revision) | revision-changing authority valid; old revision immutable/superseded; every non-terminal `attempt` and `review_dispatch` owned by the old revision is terminally fenced and its owned process group stopped per §6 before the new revision commits; new context/base/acceptance revalidated before planning. [EXEC-FENCE] |
| BUILDING/REJECTED | task.fail | FAILED | execution/correction/integration budget exhausted or unrecoverable failure within current contract; from BUILDING a `RUNNING` or `CANDIDATE_READY` attempt may still be live, so every non-terminal `attempt` and `review_dispatch` owned by the task is terminally fenced and its owned process group stopped per §6 before `FAILED` commits. [EXEC-FENCE] |

`ACCEPTED`, `CANCELLED` and `SUPERSEDED` are terminal task states for V1. They cannot be revised, cancelled or superseded in-place. If later product intent invalidates an accepted outcome, a new task is created and dependency/currentness rules decide whether downstream work remains valid. Integration/release records have their own terminal states. A `FAILED` task does not auto-resume; continuation requires `task.revise` to a new PROPOSED revision (or explicit supersession before terminal acceptance).

### 3.1 Execution-record fencing on subject transitions

§1A defines which subject states are **execution-bearing**, and §3A.1/§3B bind each non-terminal execution record to those states. The two claims are only consistent if every §3 edge that carries a subject *out* of the execution-bearing set also disposes of the records that set admits. Without that obligation the matrices contradict each other: §3B says a `DISPATCHED` dispatch cannot exist under a non-`REVIEWING` subject, while §3 lets `candidate.reject` move a candidate to `REJECTED` with two reviewers still running. This section is the missing obligation, and it is written as a per-row requirement so it is checked against the transitions rather than against a restatement of them.

**The rule.** Let *E(kind)* be the execution-bearing set derived for that subject kind. A §3 row **qualifies** when its **From** cell names at least one state in *E(kind)* and its **To** cell names at least one subject state, none of which is in *E(kind)*. Every qualifying row MUST carry exactly one of the following two tokens in its preconditions cell. The token is the requirement, not a label for one stated elsewhere:

| Token | Obligation |
| --- | --- |
| `[EXEC-FENCE]` | Before the subject transition commits, in the same transaction, every non-terminal `attempt` and every non-terminal `review_dispatch` owned by that subject MUST be moved to a terminal state — `CLOSED` with a terminal disposition for an attempt, `CANCELLED`/`FENCED`/`EXPIRED` for a dispatch. Each such record's owned process group MUST be stopped through §6 before that commit, and `QUARANTINED` (attempt) or `FENCED` + subject `BLOCKED` (dispatch) MUST be used where cleanup cannot be proven, so an unprovable process never yields a silently clean subject transition. |
| `[EXEC-ATOMIC-CLOSE: <edge>]` | The same transaction closes exactly those records through the named paired §3A/§3B edge. This is admissible only when the named edge is terminal and the row can close no record it does not name. |

Three consequences are normative:

- no `review_dispatch` in `DISPATCHED` and no `attempt` in `CREATED`/`STARTING`/`RUNNING`/`CANDIDATE_READY` may exist under a subject state outside *E(kind)*. `[EXEC-FENCE]` and `[EXEC-ATOMIC-CLOSE]` are the only two ways a §3 edge may leave that set, so the §3B binding rule and §1A's derivation hold by construction rather than by assertion;
- the commands named by qualifying `[EXEC-FENCE]` rows MUST appear as triggers on terminal edges of §3A and §3B wherever those matrices can actually hold a record for the states the row leaves. Concretely: if a state in *From ∩ E(kind)* binds a non-terminal attempt state under §3A.1, §3A MUST list that command on a terminal edge out of each such attempt state; if a state in *From ∩ E(kind)* is a §3B dispatch-bearing subject state, §3B MUST list that command on a terminal edge out of `DISPATCHED`. This is what makes the three matrices agree, and it is derived from §3A.1/§3B rather than restated;
- fencing releases resources immediately. The required-review slot freed by a fenced dispatch and the reviewer-concurrency and execution-slot occupancy freed by a fenced record MUST be reusable as soon as the subject transition commits; a terminal subject MUST NOT continue to occupy a slot, a lease or a concurrency unit.

`task.block` is unconditional under this rule. Its earlier "when continuation unsafe" qualifier let a `BLOCKED` task keep a `RUNNING` attempt, which is exactly the strand §1A's `EXECUTION_RECORD_MISSING` reconciliation cannot see, because the inconsistency there is a live record under a non-execution-bearing subject rather than a missing record under an execution-bearing one.

Rows that stay inside *E(kind)* — `attempt.start` (ASSIGNED -> BUILDING), `candidate.register`, `review.record`, `review.cancel`, `integration.start` — carry no token, because they strand nothing. `integration CREATED -> CANCELLED` likewise carries none: `integration.begin` has not run, so no execution record exists to fence, and §3A.1 does not bind any attempt state to `CREATED`.

## 3A. Attempt transition matrix

The matrix in §3 is authoritative for **subject-state** changes (task and integration). This attempt matrix is authoritative for **attempt-state** changes and adds attempt-specific preconditions. Where one command changes both subject and attempt state, **both tables must permit the same operation**; the kernel uses their intersection. Any disagreement is a specification error and MUST fail closed rather than allowing either table to override the other silently.

Attempt transitions are independent records from the subject state transaction but must be performed atomically with the corresponding lease/subject mutation where one exists.

This matrix applies to both attempt subject kinds. Where the trigger differs by subject kind it is named for each; everything else is identical, which is the point of the §1A generalisation. For an `INTEGRATION` attempt, read "task" as "integration", "candidate" as "integration SHA" and `task.block` as `integration.block`.

| From | Trigger/command | To | Preconditions / result |
| --- | --- | --- | --- |
| none | `attempt.assign` (TASK) / `integration.begin` (INTEGRATION) | CREATED | TASK: task is `PLANNED`, or task is `REJECTED` with bounded-correction budget available as permitted by §3; in **both TASK branches the per-revision attempt ceiling must not be exhausted**. INTEGRATION: integration is `CREATED`. Capacity/workspace reservation succeeds; new epoch/fence bound |
| CREATED | `attempt.start` (TASK) / `integration.start` (INTEGRATION) begins measured preflight | STARTING | current lease; workspace exists; no model process yet; subject remains ASSIGNED (TASK) or INTEGRATING (INTEGRATION) during preflight. This is the only edge that may write the cleanup handle: `lease.owned_process_group_handle` is committed **before** the attempt's single owned process group is created (§3A.3), and preflight runs inside that group; `attempt.running_process_group_identity` stays NULL |
| STARTING | `attempt.start` (TASK) / `integration.start` (INTEGRATION) completes successfully | RUNNING | exact base/branch/environment/tool/capability checks pass; the model process is launched **inside the attempt's existing owned process group**, so this edge MUST NOT update, replace or clear `lease.owned_process_group_handle` (§3A.3) and no second group is created; `attempt.running_process_group_identity` is written in this same commit and only here, as the ceiling discriminator alone, and MUST NOT be used as the cleanup handle (§3A.3) |
| STARTING | preflight deterministic failure | CLOSED / FAILED or QUARANTINED | no model launch; a TASK subject reaches `BLOCKED` through §3 `task.block`, while an INTEGRATION subject reaches `BLOCKED` through §3 `integration.block`, using the typed precondition reason. Attempt disposition is `FAILED` when cleanup is proven complete, or `QUARANTINED` when process/workspace safety cannot be proven. Preflight failure never fabricates RUNNING and never uses an unlisted direct subject transition. |
| CREATED | `task.cancel` / `task.supersede` / `task.revise` / `task.block` / `task.escalate` (TASK) / `integration.cancel` / `integration.block` (INTEGRATION) / controller-epoch fencing event, as applicable to the subject kind | CLOSED / CANCELLED or FENCED | no owned process group has been created, proven by `lease.owned_process_group_handle` being NULL (§3A.3), so process cleanup is proven by construction; the lease is released/retired and the old fencing token can never admit a result. `running_process_group_identity` is NULL, so §3A.2 does not charge the ceiling |
| STARTING | `task.cancel` / `task.supersede` / `task.revise` / `task.block` / `task.escalate` (TASK) / `integration.cancel` / `integration.block` (INTEGRATION) / controller-epoch fencing event, as applicable to the subject kind | CLOSED / CANCELLED or FENCED | authority is fenced immediately; the preflight process group is identified from `lease.owned_process_group_handle`, stopped through §6 and proven empty before the non-quarantined terminal disposition. A NULL handle means no group was ever created (§3A.3) and cleanup is therefore proven, not unknown. `running_process_group_identity` is NULL, so §3A.2 does not charge the ceiling |
| STARTING | cancellation/fencing event where a preflight process group named by `lease.owned_process_group_handle` cannot be proven stopped | CLOSED / QUARANTINED | authority remains fenced, workspace is not reused, and the subject is BLOCKED until cleanup/reconciliation proves safety. This disposition requires a genuinely unprovable *live* group: a NULL or absent handle is proof of no group and takes the FENCED/CANCELLED edge above instead, so missing durable identity can never be the reason for quarantine (§3A.3) |
| RUNNING | `candidate.register` (TASK) / `integration.register` (INTEGRATION) | CANDIDATE_READY | current epoch/fence; immutable commit identity independently measured and the Candidate / integration SHA persisted |
| RUNNING | process exits without producing a commit | CLOSED / FAILED | diagnostics/evidence persisted; the subject takes the §10.3 non-rejection path of `ORCHESTRATOR_V1_FREEZE_CONTRACT.md`, which is a finite persistent budget rather than implementer discretion |
| RUNNING | process stalls past its deadline with no commit | CLOSED / FAILED or QUARANTINED | reason code `PROCESS_STALLED`/`PROCESS_TIMEOUT`, which §7 classifies BLOCKED; disposition is `FAILED` when cleanup is proven and `QUARANTINED` otherwise; the subject reaches BLOCKED through its legal block edge |
| RUNNING | `task.cancel` / `task.supersede` / `task.revise` / `task.block` / `task.escalate` / `task.fail` (TASK) / `integration.cancel` / `integration.block` (INTEGRATION) / controller-epoch fencing event, as applicable to the subject kind | CLOSED / CANCELLED or FENCED | old token immediately loses authority; the process group is identified from the write-once `lease.owned_process_group_handle` and cleanup follows §6. Because that one group has covered the attempt since `STARTING`, emptiness is proved over the **entire** group, so a preflight child that survived into `RUNNING` is found and stopped here rather than being invisible. `running_process_group_identity` is non-NULL, so §3A.2 charges the ceiling |
| RUNNING | process cannot be proven stopped | CLOSED / QUARANTINED | subject BLOCKED; workspace cannot be reused |
| CANDIDATE_READY | evidence completion / subject reaches EVIDENCE_READY | CLOSED / SUCCEEDED | commit already durable; no later worker authority needed |
| CANDIDATE_READY | `task.cancel` / `task.supersede` / `task.revise` / `task.block` / `task.escalate` / `task.fail` (TASK) / `integration.cancel` / `integration.block` (INTEGRATION) / controller-epoch fencing event, as applicable to the subject kind, before evidence completion | CLOSED / FENCED | the Candidate or integration SHA remains durable/discoverable; evidence may remain incomplete; cleanup follows §6 against `lease.owned_process_group_handle`, and `QUARANTINED` is used instead when that group cannot be proven stopped |

`CLOSED` is terminal for an attempt. A correction always creates a new attempt with a new fencing token.

### 3A.1 Subject binding of non-terminal attempt states

Every edge above either leaves the subject state alone or is paired with a §3 subject edge, so the subject states that may hold a non-terminal attempt are a **derivation of this matrix** rather than a separate claim. The table restates that derivation so §1A and freeze contract §21 can be checked against it mechanically; it is normative, and it MUST agree with the edges above. An attempt state that gains a new subject pairing above MUST gain it here, and §1A/§21 MUST then be re-derived.

| Non-terminal attempt state | TASK subject state | INTEGRATION subject state |
| --- | --- | --- |
| `attempt` CREATED | `ASSIGNED` | `INTEGRATING` |
| `attempt` STARTING | `ASSIGNED` | `INTEGRATING` |
| `attempt` RUNNING | `BUILDING` | `INTEGRATING` |
| `attempt` CANDIDATE_READY | `BUILDING` | `INTEGRATING` |

`CANDIDATE_READY` is bound to `BUILDING`/`INTEGRATING` rather than `EVIDENCE_READY` because `evidence.register` and `integration.register` advance the subject to `EVIDENCE_READY` and close the attempt `SUCCEEDED` in the same transaction; the attempt is never non-terminal under an `EVIDENCE_READY` subject.

### 3A.2 Per-revision execution-attempt ceiling

For TASK attempts, the per-revision execution-attempt ceiling is computed authoritatively from durable `attempt` rows with `(subject_kind = TASK, subject_id = task_id, subject_revision = revision)`. It is never an in-memory-only counter, so restart, restore and controller-epoch changes cannot reset it.

The ceiling bounds **model relaunches**, so it counts **execution-consuming** attempt rows, and the classification is total over the `attempt` disposition enum:

| Attempt row | Consumes the ceiling? | Why |
| --- | --- | --- |
| non-terminal (`CREATED`/`STARTING`/`RUNNING`/`CANDIDATE_READY`) | yes | the execution opportunity is currently held |
| `CLOSED / SUCCEEDED` | yes | a model process ran and produced a candidate |
| `CLOSED / FAILED` | yes | includes deterministic preflight failure, which §3A closes `FAILED`, so a deterministic failure can never be retried around this budget |
| `CLOSED / QUARANTINED` | yes | process or workspace safety could not be proven; freeze contract §10.3.1 forbids relaunching it at all until cleanup is proven |
| `CLOSED / CANCELLED` or `CLOSED / FENCED` **that reached `RUNNING`** | yes | a model process was launched under this attempt |
| `CLOSED / CANCELLED` or `CLOSED / FENCED` **that never reached `RUNNING`** | **no** | no model process was ever launched, so charging it would let controller restarts and epoch changes consume a budget that exists to bound model relaunches |

Whether an attempt reached `RUNNING` MUST be decidable from the committed `attempt` row alone, without replaying journal history. The authoritative fact is `attempt.running_process_group_identity`, which §3A.3 defines as NULL until the attempt commits `RUNNING`, non-NULL from then on and written exactly once in that commit: a NULL value on a `CANCELLED`/`FENCED` row is the durable proof that no model process was launched. §3A.2 is the only reader of that field, and it MUST NOT be used as a cleanup handle; conversely `lease.owned_process_group_handle` MUST NOT be read here, because it is populated before `RUNNING` and a pre-`RUNNING` preflight group would otherwise be miscounted as an execution attempt. No additional column is introduced for this.

Three consequences are normative:

- an attempt that closes `CANCELLED` or `FENCED` before reaching `RUNNING` MUST NOT consume the ceiling, so repeated controller restarts, cancellations or epoch changes while a task sits in `ASSIGNED` with a `CREATED` attempt cannot exhaust the three real execution attempts;
- a deterministic preflight failure MUST remain budget-consuming; §3A gives it the disposition `FAILED` (or `QUARANTINED` on unproven cleanup) and never `CANCELLED`/`FENCED`, so this rule cannot be used to retry a deterministic failure indefinitely;
- the count is a pure function of committed `attempt` rows and their immutable terminal dispositions, so controller restart, DB restore and controller-epoch change can neither reset it nor decrement a legitimately consumed attempt. Reclassifying an already-`CLOSED` attempt is forbidden by §4's atomicity rules; a disposition is written once.

The ceiling guard on every `attempt.assign` path in §3 and in this matrix is unchanged — only the definition of which rows it counts is repaired.

### 3A.3 Owned process groups, write-once cleanup handles and the ceiling discriminator

This subsection is normative for **all three** execution records of §1A — implementation attempts, integration attempts and review dispatches — not for attempts alone. It is the single place the substrate's process-ownership rules are stated, which is what makes §1A's "the following rules apply uniformly to all three" mechanically true rather than aspirational.

An attempt in `STARTING` may already own a live process group: §5B/§11 preflight measures a real environment and can fork real tool processes. Two different questions are therefore asked about a pre-`RUNNING` attempt, and answering both from one field is what made the `STARTING` crash window non-deterministic:

1. *which process group, if any, does this record own, so that §6 can stop it?* — a **cleanup** question, asked from the moment the group is forked;
2. *did this attempt ever reach `RUNNING`, so that §3A.2 can decide whether it consumed execution budget?* — an **accounting** question, answerable only at the `RUNNING` commit.

These are two durable facts in two fields with two population times. One MUST NOT be derived from the other.

| Durable fact | Field | Written | Read by |
| --- | --- | --- | --- |
| owned-process-group cleanup handle | `lease.owned_process_group_handle` | committed **before** the attempt's single owned process group is created, on the `CREATED -> STARTING` edge, and **never written again** while the attempt is non-terminal. Retired when the attempt closes and cleanup is proven | §6 cancellation, and freeze contract §21 steps 5, 6 and 11 restart cleanup |
| execution-ceiling discriminator | `attempt.running_process_group_identity` | exactly once, in the transaction that commits `STARTING -> RUNNING`; NULL at every other time and never written by any other edge | §3A.2 only |

**One owned group per record, one write of the handle.**

- a record owns **exactly one** controller-created process group/cgroup for its entire non-terminal lifetime. For an attempt that one group is created on `CREATED -> STARTING` and **both preflight and model execution run inside it**; the model process is launched into the existing group rather than into a new one;
- the cleanup handle is therefore **write-once**. `STARTING -> RUNNING` MUST NOT update, replace or clear `lease.owned_process_group_handle`, and no other edge may either. A two-group handover — recording a preflight group, then overwriting the handle with a model group — is **forbidden**, because between the overwrite and the proof of the first group's emptiness any surviving preflight descendant is owned by nobody the database can name, and the §11 emptiness rule then passes vacuously over the wrong group;
- `attempt.running_process_group_identity` stays what §3A.2 needs and nothing more. It is the ceiling discriminator only; it MUST NOT be promoted into the cleanup handle, and §6 MUST NOT read it;
- consequently every cancellation, restart and emptiness check applies to the **whole** per-attempt group. A preflight child that outlives preflight and survives into `RUNNING` is inside the group §6 stops and proves empty, so it cannot become invisible, and workspace reuse stays forbidden under freeze contract §11 until that entire group is empty.

**Write-ahead ordering.**

- the handle MUST be committed before the corresponding process group is created. A controller crash can therefore leave a recorded handle with no group, but never a group with no recorded handle;
- consequently a NULL cleanup handle is **positive proof that no owned group exists**, not an absence of information. For a pre-`RUNNING` attempt cleanup is proven and the attempt MUST close `FENCED`/`CANCELLED`;
- a controller crash during `STARTING` with a live group MUST be reconciled by reading that handle, stopping the named group through §6, and then closing the attempt `FENCED` once emptiness is verified. Because `running_process_group_identity` is NULL, §3A.2 does not charge the ceiling, so crash-and-restart in the `STARTING` window cannot consume execution budget;
- `QUARANTINED` is permitted **only** when a group named by a non-NULL handle cannot be proven stopped. It MUST NOT be used merely because no durable identity was recorded, which under the ordering above cannot happen for a group that exists;
- a deterministic preflight failure is unaffected: §3A closes it `FAILED` (or `QUARANTINED` on genuinely unprovable cleanup) and never `CANCELLED`/`FENCED`, so it remains budget-consuming and R-02 is not weakened.

**Controller-allocated, non-recycled identity.** A cleanup handle names a group the controller will later signal, possibly after a crash and restart, so it MUST NOT be a value the operating system can reissue to an unrelated process in the meantime:

- the handle MUST be a **controller-allocated, attempt-bound (or dispatch-bound) identity** — for example a per-record cgroup path or equivalent kernel-scoped container identity derived from the record's own primary key — and MUST NOT be a bare recyclable OS process-group/process number standing alone;
- before signalling, §6 MUST verify that the group the handle currently resolves to is still the one this record created, by checking the identity recorded in the handle against the live group. This requirement is about failing closed on a stale handle, not about mandating a particular kernel mechanism; any substrate that makes reuse detectable satisfies it;
- if that ownership check cannot be satisfied — the handle resolves to nothing identifiable, or to a group that is not this record's — the controller MUST NOT signal it. Where the record's own processes therefore cannot be proven gone, the outcome is the fail-closed one: `QUARANTINED` for an attempt, `FENCED` with the subject BLOCKED for a dispatch. Stale-handle reuse thus fails closed and can never cause an unrelated process to be killed.

**Ownership is decided from the principal, never from NULL.** For a `review_dispatch`, whether the kernel owns the reviewer process is decided **only** from the durable reviewer principal/session execution-ownership kind `KERNEL_OWNED|EXTERNAL` recorded at dispatch creation:

- a `KERNEL_OWNED` dispatch commits its cleanup handle before creating the reviewer process group, exactly as an attempt does. NULL on that field is positive proof that no reviewer group was created — the state a crash between the handle commit and the fork leaves behind — and it MUST NOT be read as "the reviewer is external";
- an `EXTERNAL` dispatch never has an owned group, so its cleanup handle is always NULL and cancellation is fencing-only, with the limitation recorded. That limitation is a property of the *principal*, not an inference from a missing identity;
- inverting this — treating a NULL handle as evidence of an external reviewer — would let a controller crash around reviewer fork release the required-review slot and the freeze contract §19 reviewer-concurrency unit while a live kernel-owned reviewer keeps running untracked, and would defeat §3.1 `[EXEC-FENCE]`, which depends on §6 having actually stopped the group before the subject transition commits. §6 step 3 therefore branches on the principal kind **first**.

§1A, §3A, §3A.2, §3B and §6 all refer to exactly these fields under exactly these names and timings; any document that names one where the other is meant, or that derives ownership from a NULL handle, is a specification error and MUST fail closed.

## 3B. Review dispatch transition matrix

Authoritative for `review_dispatch` state. Review dispatch is the third execution record of §1A; it is not an `attempt`, because independence requires several concurrent reviewer principals for one subject and a single per-subject lease cannot express that.

| From | Trigger/command | To | Preconditions / result |
| --- | --- | --- | --- |
| none | `review.request` / `integration.review_request` | DISPATCHED | subject is `REVIEWING`; exact subject SHA and evidence-manifest digest frozen; no other non-terminal dispatch occupies this required-review slot; controller epoch and a fresh monotonic dispatch fencing token bound; §9 independence satisfiable for the bound reviewer principal; the reviewer principal's execution-ownership kind `KERNEL_OWNED|EXTERNAL` is committed durably in this same transaction, before any reviewer process exists. For a `KERNEL_OWNED` dispatch the write-once process-group/cgroup cleanup handle is then committed **before** the reviewer process group is created and is never replaced while the dispatch is non-terminal (§3A.3); for an `EXTERNAL` dispatch it stays NULL |
| DISPATCHED | `review.record` | COMPLETED | preconditions of the §3 `review.record` row hold; the Review row and this terminal transition are one transaction |
| DISPATCHED | `review.cancel` by authorised caller | CANCELLED | owned reviewer process group stopped per §6; no verdict admitted |
| DISPATCHED | heartbeat/expiry deadline passes without a verdict | EXPIRED | expiry is deterministic and recorded; the subject does not silently remain in `REVIEWING`; policy then either creates exactly one replacement dispatch for the slot or blocks the subject, never both |
| DISPATCHED | replacement dispatch required for the same slot, or controller-epoch change, or any §3.1 `[EXEC-FENCE]` subject transition out of `REVIEWING` — `candidate.accept` / `candidate.reject` / `integration.verify` / `integration.reject` / `integration.block` / `integration.cancel` / `task.block` / `task.escalate` / `task.cancel` / `task.supersede` / `task.revise` | FENCED | fencing happens **before** any replacement row is created and **before** the subject transition commits, so the slot uniqueness constraint holds, the original reviewer loses authority even though the subject SHA is unchanged, and no `DISPATCHED` row survives under a subject state outside the execution-bearing set. The owned reviewer process group is stopped per §6 and the required-review slot is released for immediate reuse |
| DISPATCHED | reviewer process cannot be proven stopped after cancellation/expiry | FENCED, subject BLOCKED | the dispatch loses authority immediately, but the subject is BLOCKED rather than re-dispatched, mirroring the attempt quarantine rule. This is the outcome whenever a `KERNEL_OWNED` reviewer's owned group cannot be proven empty — including when its recorded handle fails the §3A.3 ownership re-verification — and the required-review slot and the freeze contract §19 reviewer-concurrency unit are **not** released while that orphan may still exist |

Every terminal state is final. A verdict presented for a terminal, unknown or non-matching dispatch is rejected with `FENCE_STALE`, and the rejection is recorded as a `transition_event`.

**Subject binding.** A `review_dispatch` is created only while its subject is `REVIEWING` and every edge out of `DISPATCHED` is terminal, so a `DISPATCHED` dispatch MUST NOT exist under any other subject state. That is not self-enforcing: it holds only because §3.1 requires every §3 edge leaving `REVIEWING` for a non-execution-bearing state to fence the live dispatches in the same transaction, and requires each such command to appear as a trigger on the FENCED row above. A rejection, verification, block or escalation decided from one verdict while sibling reviewers are still running MUST fence those siblings rather than abandon them, including the case of two or more concurrent `DISPATCHED` rows on distinct required-review slots. For §1A's derivation this contributes exactly the `TASK` subject state `REVIEWING` and the `INTEGRATION` subject state `REVIEWING`, and a subject left in `REVIEWING` with no non-terminal dispatch MUST be surfaced as BLOCKED by §1A's execution-bearing rule rather than silently re-dispatched.

## 3C. Delivery transition matrix

Authoritative for the `delivery.state` enum. Delivery is not an execution record and owns no lease/fencing token; §7 of the freeze contract defines its controller-epoch and idempotency authority.

An **external publication effect** is any outward-facing call that may create, mutate or deliver the intended artifact at the destination. The `delivery` record's `attempt count` is the durable evidence that such an effect may have been initiated: `delivery.publish` MUST increment it and MUST commit that increment **before** initiating the effect, and it is never decremented. Because the marker is committed first, a crash between initiating the effect and persisting its outcome leaves exactly the same durable evidence as a lost response, which is what makes the two indistinguishable to reconciliation and is the reason a crash cannot produce a blind duplicate publication. `delivery.reconcile` reads authoritative remote state and initiates no external publication effect, so it never touches this counter.

| From | Trigger/command | To | Preconditions / result |
| --- | --- | --- | --- |
| none | `delivery.publish` creates the intent | PENDING with `attempt count = 0` | idempotency key/request digest validated; expected remote identity and destination persisted; the intent commits before any external effect and no effect has been initiated |
| PENDING with `attempt count = 0` | `delivery.publish` arms the external effect | PENDING with `attempt count >= 1` | current controller epoch; matching idempotency key/request digest; the increment is committed **before** the external publication effect is initiated. This row is the durable record that an effect may have started, and it is the only admissible way to reach an initiated effect |
| PENDING with `attempt count >= 1` | `delivery.publish` observes exact expected remote identity after the effect | PUBLISHED | authoritative remote readback matches the intended immutable identity; observed identity persisted |
| PENDING with `attempt count >= 1` | `delivery.publish` loses or receives an ambiguous response after the effect | UNKNOWN | ambiguity persisted with reason `REMOTE_EFFECT_UNKNOWN`; blind replay forbidden; reconciliation required |
| PENDING with `attempt count >= 1` | controller restart, DB restore or controller-epoch change reconciles the record (freeze contract §21 step 10) | UNKNOWN | the committed counter proves an external effect may already have been initiated, so the record MUST reconcile to UNKNOWN **before any further external effect**. This transition performs no external effect of its own |
| PENDING with `attempt count = 0` | controller restart, DB restore or controller-epoch change reconciles the record | PENDING with `attempt count = 0` | no external effect was ever initiated under this record, so the intent survives unchanged and `delivery.publish` remains admissible; `delivery.state` does not change |
| PENDING | `delivery.reconcile` observes exact expected remote identity | PUBLISHED | authoritative remote truth proves the intended effect occurred; no external publication effect is performed |
| PENDING | `delivery.reconcile` proves a definite non-ambiguous terminal failure | FAILED | exact failure evidence/reason persisted; no claim of publication success |
| UNKNOWN | `delivery.reconcile` observes exact expected remote identity | PUBLISHED | ambiguous effect reconciled as success without replay |
| UNKNOWN | `delivery.reconcile` proves the intended effect did not occur and no safe retry remains | FAILED | authoritative remote evidence persisted; no duplicate external effect |
| PENDING / UNKNOWN / FAILED | `delivery.block` | BLOCKED | typed deterministic policy/authority/conflict reason persisted; no external retry while blocked |

Any delivery transition not listed above is forbidden, and `delivery.publish` is the only trigger in this matrix that initiates an external publication effect. Every state it is admissible from is listed, and each such row carries an explicit `attempt count` precondition, so no state admits an effect without first committing the evidence that one may have started. Consequently:

- `delivery.publish` MUST be refused for a record in `UNKNOWN`, with reason code `REMOTE_EFFECT_UNKNOWN`. Authoritative remote reconciliation through `delivery.reconcile` is the **only** path out of `UNKNOWN`, and it MUST NOT be satisfied by replaying the publication;
- `delivery.publish` is inadmissible from `PUBLISHED`, `FAILED` and `BLOCKED` because no row lists it there. `PUBLISHED` and `BLOCKED` are terminal for the delivery record; `FAILED` may only move to BLOCKED in V1, and a new permitted publication attempt after a failed delivery uses a new delivery/idempotency record rather than silently resetting this one;
- a `PENDING` record MUST NOT be republished on the strength of its state alone. `attempt count = 0` is the only condition under which a fresh external effect may be armed, and reaching `attempt count >= 1` commits the record to the observe-or-reconcile path.

Every §3C transition that changes `delivery.state` emits a `DELIVERY` `transition_event`.

## 4. Atomic transaction rules

One database transaction MUST include all authoritative effects for a command:

- validate expected current state/revision/epoch/fence;
- insert/check idempotency record;
- mutate state/record;
- insert transition event;
- update lease/fencing information where applicable;
- commit.

If commit fails, none of those effects are authoritative.

Filesystem/remote operations that cannot share the DB transaction use a two-phase durable record:

1. persist intent/expected identity;
2. perform effect;
3. observe authoritative result;
4. persist observed identity/outcome.

Timeout between steps 2 and 4 produces `UNKNOWN` delivery/effect state and requires reconciliation before retry.

## 5. Dependencies and queueing

A task revision may list dependency candidate SHAs and required interface/context digests.

- unfinished or rejected dependencies keep the task BLOCKED;
- moving branch names are not valid dependencies;
- scheduler considers only PLANNED tasks with satisfied immutable dependencies;
- priority may affect order, never safety/authority;
- slot exhaustion keeps work queued/PLANNED; it is not a failure and MUST NOT consume a retry budget.

V1 does not need a separate distributed message broker.

## 5A. Workspace source and publication authority

Workspace creation MUST start from a builder-owned non-production source/mirror and then verify the exact task base SHA.

- If the local source/mirror contains the exact base SHA, clone/fetch that object into the standalone attempt workspace and checkout the exact SHA.
- If the mirror is stale or lacks the base SHA, the kernel MAY refresh only from the task-approved repository origin under the task's network policy, then MUST re-measure the exact SHA.
- If the exact SHA remains unavailable, the task is BLOCKED with `PRECONDITION_BASE_MISMATCH`.
- Production checkout paths are never fallback clone sources.

Workers receive no usable remote push credential. Candidate publication is performed by the kernel publication adapter under a narrow credential after Candidate registration. The adapter publishes the exact candidate commit to a create-only namespaced candidate ref and reconciles remote SHA on ambiguous outcomes; it never force-updates a candidate ref.

## 5B. Pre-launch environment identity

Before `attempt.start`, the runner adapter MUST independently compute/obtain the environment/toolchain fingerprint defined by the task's environment manifest and compare it to the bound `environment_manifest_digest`.

An exit status of zero from bootstrap/doctor scripts is insufficient. Version/provenance/fingerprint mismatch produces `PRECONDITION_CAPABILITY_MISSING` or a more specific environment mismatch subcode and blocks launch before model execution.

## 6. Cancellation race contract

This contract governs every owned process group of §1A — implementation attempts, integration attempts and review dispatches alike — and it is the sequence §3.1 requires to complete **before** a subject transition out of an execution-bearing state commits.

On cancellation:

1. transactionally mark cancellation requested and advance/fence lease or dispatch authority;
2. stop accepting heartbeats/candidates/evidence/verdicts from the old token;
3. decide **ownership first, from durable principal/role identity, never from a NULL handle** (§3A.3), then identify and signal:
   - for an `attempt`, and for a `review_dispatch` whose reviewer principal carries execution-ownership kind `KERNEL_OWNED`, the kernel owns the process. Identify its single owned process group from the record's write-once durable handle — `lease.owned_process_group_handle` for an attempt, the `review_dispatch` process-group/cgroup identity for a dispatch — **verify that the group the handle resolves to is still the one this record created** per §3A.3, and only then send TERM to it. A NULL handle here means no group was ever created and the step is satisfied without signalling anything; it does **not** mean the process belongs to someone else. A handle that fails the ownership check is never signalled and is treated as cleanup that cannot be proven, so it takes step 7;
   - only for a `review_dispatch` whose reviewer principal carries execution-ownership kind `EXTERNAL` does the kernel own no process. Cancellation there relies on fencing alone, nothing is signalled, and the limitation is recorded;
4. after configured grace, send KILL;
5. verify the **entire** owned process group is empty — for an attempt that is the one group that has covered it since `STARTING`, so surviving preflight descendants are included;
6. if empty, close the attempt `CANCELLED`/`FENCED`, or the dispatch `CANCELLED`/`FENCED`/`EXPIRED`;
7. if not provably empty, mark the attempt `QUARANTINED` — or the dispatch `FENCED` — and the subject BLOCKED.

Two ordering rules are normative:

- for a §3.1 `[EXEC-FENCE]` transition, steps 1–7 MUST complete for every non-terminal record owned by the subject before the subject transition commits. A subject MUST NOT reach a non-execution-bearing state while any of its records is still non-terminal, and where step 7 applies the subject takes its BLOCKED/QUARANTINED outcome instead of the transition it requested;
- resources MUST be released at step 6 **and never at step 7**: the workspace becomes reusable under the freeze-contract §11 emptiness rule, the required-review slot of a terminated dispatch becomes immediately available to a replacement, and the reviewer-concurrency and execution-slot units the record occupied are freed at the same commit. A terminal subject MUST NOT continue to occupy a slot, a lease or a concurrency unit. Because step 6 is reached only once the whole owned group is proven empty, a `KERNEL_OWNED` reviewer whose group is unproven cannot have its required-review slot or its freeze-contract §19 reviewer-concurrency unit released, and no replacement reviewer can be admitted while that orphan may still be alive; the subject is BLOCKED at step 7 instead.

A candidate arriving after step 1 is stale even if it was produced before the signal reached the process. The same holds for a verdict from a dispatch fenced at step 1.

## 7. Failure reason codes

The following table is the normative reason-code set and is a **total mapping**: every code resolves to exactly one top-level class. The four classes are `RETRYABLE`, `BLOCKED`, `REJECTED_FAILED` and `ESCALATED`, and they mean exactly what `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §10 says they mean. Leaving this mapping to implementer discretion was the defect this table exists to remove: two conformant kernels MUST NOT be able to disagree about whether a given failure is automatically retried.

| Reason code | Class | Notes |
| --- | --- | --- |
| `PRECONDITION_BASE_MISMATCH` | BLOCKED | deterministic; restart MUST NOT reclassify |
| `PRECONDITION_BRANCH_MISMATCH` | BLOCKED | deterministic |
| `PRECONDITION_DIRTY_WORKSPACE` | BLOCKED | no reset/clean/stash recovery |
| `PRECONDITION_TOOL_ROSTER_MISMATCH` | BLOCKED | deterministic |
| `PRECONDITION_CAPABILITY_MISSING` | BLOCKED | includes environment-fingerprint mismatch subcodes under §5B |
| `AUTH_EXPIRED` | BLOCKED | never transport retry |
| `AUTH_FORBIDDEN` | BLOCKED | never transport retry |
| `QUOTA_EXHAUSTED` | BLOCKED | no silent model downgrade |
| `PROVIDER_RATE_LIMIT` | RETRYABLE | §10.2 budget; honour authoritative `Retry-After` |
| `PROVIDER_TRANSIENT` | RETRYABLE | §10.2 budget |
| `PROVIDER_UNAVAILABLE` | RETRYABLE | §10.2 budget; on exhaustion becomes BLOCKED/ESCALATED per §10.2, which is a budget outcome and not a reclassification of this code |
| `PROCESS_TIMEOUT` | BLOCKED | attempt stall/timeout is never a transport retry; §10.3 governs relaunch |
| `PROCESS_STALLED` | BLOCKED | as above |
| `PROCESS_ORPHANED` | BLOCKED | unproven process state; workspace quarantine applies |
| `RESOURCE_DISK_HIGH_WATERMARK` | BLOCKED | admission gate, not a retry |
| `RESOURCE_CAPACITY` | BLOCKED | recorded only where a capacity condition prevents admission of already-authorised work. Ordinary scheduler slot exhaustion is **not** a failure, is not recorded with this code, and per §5 leaves the task PLANNED/queued without consuming any budget |
| `DB_INTEGRITY` | BLOCKED | no guess-repair of authoritative state |
| `DB_IO` | BLOCKED | fail closed; never a silent retry against a possibly damaged store |
| `REMOTE_EFFECT_UNKNOWN` | BLOCKED | BLOCKED until reconciled; reconciliation may then permit a bounded retry under §9. Also the refusal code for a `delivery.publish` presented against an `UNKNOWN` delivery, or against a `PENDING` delivery whose `attempt count` already shows an initiated effect (§3C) |
| `EXECUTION_RECORD_MISSING` | BLOCKED | an execution-bearing subject state (§1A) holds no non-terminal execution record — the stranded case left behind when cancellation or controller-epoch fencing terminates the record without moving the subject. Reconciliation surfaces the subject BLOCKED through its listed `task.block`/`integration.block` edge; never a blind re-dispatch |
| `PUBLICATION_CONFLICT` | BLOCKED | no force push |
| `EVIDENCE_MISSING` | BLOCKED | missing evidence is UNKNOWN, never PASS |
| `EVIDENCE_DIGEST_MISMATCH` | BLOCKED | integrity failure |
| `FENCE_STALE` | REJECTED_FAILED | a heartbeat, candidate, evidence, integration result or review verdict presented under a superseded, terminal or unknown execution record. The admission is rejected and the presenting execution has no authority; the subject's own state is unchanged by the rejected admission |
| `REVIEW_BLOCKED` | BLOCKED | reviewer unavailable or reviewer returned `BLOCKED` |
| `REVIEW_REJECTED` | REJECTED_FAILED | evidence-backed rejection; §10.3 correction budget applies |
| `CONTEXT_STALE` | BLOCKED | re-plan or revise |
| `AUTHORITY_STALE` | BLOCKED | expired/absent/insufficient grant |
| `DEPENDENCY_BLOCKED` | BLOCKED | unfinished or rejected dependency |
| `POLICY_VIOLATION` | ESCALATED | a safety/authority boundary was actually attempted; requires higher-level diagnosis rather than automatic handling, and MUST NOT be retried |

Totality and fail-closed default:

- the table above is total over the normative code set — every listed code has exactly one class, and no code appears twice;
- implementations MAY add more specific subcodes, and a subcode inherits the class of its top-level code;
- a code or subcode with **no resolvable top-level mapping MUST be treated as BLOCKED**. It MUST NOT be treated as RETRYABLE, and it MUST NOT be silently dropped;
- this default is persistent: controller restart MUST NOT reclassify a persisted code, and MUST NOT convert a BLOCKED classification into a retry.

## 8. Artifact store write protocol

Evidence/artifact storage MUST be crash-safe:

1. write to a unique temporary file inside the artifact root;
2. fsync file;
3. compute/verify SHA-256;
4. atomically rename into `sha256/<digest>`;
5. fsync containing directory where supported;
6. only then register digest in the DB.

A DB evidence record MUST NOT point to an artifact that has not completed this protocol.

## 8A. Evidence collector authority

The Evidence Collector is a kernel component, not part of the worker process group.

- it opens the attempt workspace read-only after candidate commit creation;
- independently measures repository identity, base/candidate SHA, diff and changed paths;
- imports worker-staged raw artifacts into kernel-owned content-addressed storage using §8;
- creates/updates Candidate/Evidence records only after digest verification;
- does not execute candidate-controlled code to derive identity.

A collector running with worker authority or inside the worker process group is not authoritative and its result is rejected.

## 9. Review independence identity

A review is independent only if:

- reviewer session/principal differs from implementation attempt/session;
- reviewer has no write access to the candidate workspace/branch through the review channel;
- reviewer is given immutable candidate/evidence identity;
- any patch authored by the reviewer is treated as a new implementation candidate and cannot be certified by the same review record.

Independence always requires distinct session/principal, review channel/workspace and no candidate write authority. For MATERIAL-or-higher work, a distinct verified equal-or-stronger model/provider SHOULD be used where available; if unavailable, a separate high-quality session may review only with the limitation recorded and the GPT Director gate retained. Model/vendor diversity strengthens review but never substitutes for authority/session/workspace separation.

## 10. Static invariants

The following are documentary/static and do not require a runtime transition test:

- no V1 production deployment authority;
- no business-write authority;
- no global/account Claude/MCP/connector changes;
- no external spend without owner approval;
- no destructive cleanup of owner work;
- branches are labels, SHAs are authority;
- implementation workers never self-certify.
