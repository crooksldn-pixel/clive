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
- process-group/cgroup identity;
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
- runner/process-group identity.

Lease replacement and fencing-token increment occur atomically. Workspace ID and runner/process-group identity are listed here to match the lease contents already required by `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §8.

### `review_dispatch`
The durable execution record for one dispatched reviewer. Review execution is a scheduled, cancellable, crash-prone model process, so §1A requires it to be represented before it runs rather than only once a verdict arrives.

- `review_dispatch_id TEXT PRIMARY KEY`;
- subject kind `CANDIDATE|INTEGRATION`;
- subject ID;
- exact subject SHA;
- subject revision — task revision for `CANDIDATE`, `1` for `INTEGRATION`, matching the `lease` convention;
- evidence-manifest digest presented to the reviewer;
- required-review slot identity — which required independent review of the subject's review policy this dispatch fills;
- reviewer principal/session identity;
- reviewer role;
- controller epoch;
- dispatch fencing token — monotonic per `(subject_kind, subject_id)`;
- state `DISPATCHED|COMPLETED|CANCELLED|FENCED|EXPIRED`;
- heartbeat deadline and expiry deadline;
- process-group/cgroup identity — NULL only where the reviewer is an external principal whose process the kernel does not own, in which case cancellation relies on fencing alone and the limitation is recorded;
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
- attempt count;
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
- fencing token presented, and the execution record it belonged to;
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
- an in-flight unit MUST be visible in the database. A subject sitting in `BUILDING`, `INTEGRATING` or `REVIEWING` with no non-terminal execution record is an inconsistency that reconciliation MUST surface as BLOCKED; it MUST NOT be read as progress, and it MUST NOT be resolved by blind re-dispatch;
- result admission MUST present the current controller epoch and the current fencing token of that exact record, and MUST be rejected with `FENCE_STALE` when the record is terminal, superseded or unknown — **including when the subject SHA has not changed**;
- cancellation, expiry and replacement each move the record to a terminal state, and that is what makes a late result stale. Candidate-mutation invalidation (freeze contract §14.3) is an additional and independent mechanism; it MUST NOT be relied on as the only one, because a stale reviewer or integrator commonly returns against an unchanged SHA;
- termination follows the §6 cancellation race contract against that record's own process group, and workspace reuse follows the freeze-contract §11 emptiness rule;
- restart reconciliation (freeze contract §21) covers all three record kinds before dispatch is re-enabled.

`subject_kind = TASK` is exactly the pre-existing implementation-attempt semantics under a generalised column name, so this section adds an execution substrate for integrators and reviewers without changing the task-attempt model that `ST-*`, `LS-*`, `WS-*` and `CXN-01..CXN-04` already prove.

## 2. Command surface

Commands are deterministic kernel operations. A local library/CLI/API may expose them, but semantics are identical.

| Command | Allowed caller | Core effect |
| --- | --- | --- |
| `task.create` | Director/intake adapter | create PROPOSED task + revision 1 |
| `task.revise` | Director | from any nonterminal task, create immutable new revision, fence obsolete attempt/lease, mark old revision superseded and set new revision to PROPOSED |
| `task.plan` | Director through validated channel | PROPOSED/BLOCKED/ESCALATED -> PLANNED after contract/context validation |
| `task.block` | kernel/policy/reviewer/Director channel | enter BLOCKED with typed reason |
| `task.escalate` | kernel/reviewer/Director | enter ESCALATED |
| `task.fail` | kernel | enter FAILED when approved execution budget exhausted |
| `task.cancel` | authorised controller/Owner/Director policy | fence active attempt; enter CANCELLED |
| `task.supersede` | Director/Owner | fence active attempt; enter SUPERSEDED |
| `attempt.assign` | scheduler | PLANNED or bounded-correction REJECTED -> ASSIGNED; create a fresh attempt/workspace reservation + lease |
| `attempt.start` | runner adapter | ASSIGNED -> BUILDING only after measured preflight |
| `attempt.heartbeat` | current runner adapter | renew the presenting attempt's current lease only; valid for either attempt subject kind |
| `attempt.cancel_ack` | runner/process manager | record process-tree stop/quarantine outcome; valid for either attempt subject kind |
| `candidate.register` | deterministic collector | while task remains BUILDING, create durable Candidate immediately after immutable commit identity is measured; does not itself advance task state |
| `evidence.register` | collector/CI adapter | attach content-addressed evidence; when required manifest is complete, advance BUILDING -> EVIDENCE_READY atomically |
| `review.request` | review coordinator | EVIDENCE_READY -> REVIEWING and create one non-terminal `review_dispatch` per required-review slot, each bound to exact subject SHA, subject revision, controller epoch and a fresh dispatch fencing token, before any reviewer process is launched |
| `review.record` | validated independent reviewer channel | persist exact-SHA verdict/findings under a named live dispatch; that dispatch becomes `COMPLETED` in the same transaction |
| `review.cancel` | review coordinator/kernel policy | move a named `review_dispatch` to `CANCELLED`, `FENCED` or `EXPIRED` and stop its owned process group per §6; no later verdict from that dispatch is admissible |
| `candidate.accept` | kernel policy | REVIEWING -> ACCEPTED only when all required reviews/findings satisfy policy |
| `candidate.reject` | kernel policy | REVIEWING -> REJECTED |
| `integration.create` | integration coordinator | create separate CREATED integration from one or more exact ACCEPTED candidate SHAs |
| `integration.begin` | integrator coordinator | CREATED -> INTEGRATING and atomically create the integration `attempt` (`subject_kind = INTEGRATION`), workspace reservation, controller epoch, fencing token and authoritative `lease`; allocation only — no model/toolchain preflight and no integrator process launch occur here |
| `integration.start` | runner adapter | while the integration remains INTEGRATING, drive its allocated attempt through STARTING -> RUNNING only after the measured §5B/§11 preflight passes and owned process-group identity is established |
| `integration.register` | deterministic collector | INTEGRATING -> EVIDENCE_READY after integration SHA + evidence exist; requires the current epoch/fencing token of the live integration attempt |
| `integration.review_request` | review coordinator | EVIDENCE_READY -> REVIEWING and create one non-terminal `review_dispatch` per required integrated-review slot, exactly as `review.request` does for candidates |
| `integration.verify` | kernel policy/CI/review coordinator | REVIEWING -> VERIFIED when required integrated gates pass and no blocking finding for that integration subject is `OPEN`/`BLOCKED` |
| `integration.reject` | kernel policy | REVIEWING -> REJECTED on blocking integrated finding; REJECTED integration is immutable/terminal and any correction uses a new integration record with parent_integration_id |
| `integration.block` | kernel/policy/review coordinator | CREATED/INTEGRATING/EVIDENCE_READY/REVIEWING -> BLOCKED with typed reason; no automatic retry |
| `integration.cancel` | authorised controller/Director policy | CREATED/INTEGRATING/EVIDENCE_READY/REVIEWING/BLOCKED -> CANCELLED; the integration attempt's lease is fenced and its process group stopped per §6, and any non-terminal `review_dispatch` for that integration is fenced. If the process group cannot be proven empty the attempt closes `QUARANTINED`, the workspace is not reused and the integration goes to BLOCKED instead of CANCELLED |
| `release_candidate.mark` | GPT Director validated channel + kernel policy | create immutable ReleaseCandidate from VERIFIED integration |
| `delivery.publish` | publication adapter | publish immutable result/ref with idempotency |
| `controller.reconcile` | authoritative controller | observe DB/process/workspace/remote truth across all three execution record kinds of §1A; no blind effects |
| `controller.drain` | authorised operator/controller policy | set DRAINING; no new assignments |
| `controller.resume` | authorised operator/controller policy | RUNNING only after health/reconciliation |
| `status.snapshot` | read-only consumer | return current deterministic state |

No model receives an operation that bypasses these guards.

## 3. Transition matrix

Any transition not listed is forbidden.

| From | Command | To | Mandatory preconditions |
| --- | --- | --- | --- |
| none | task.create | PROPOSED | valid unique task/idempotency key; authorised intake reference |
| PROPOSED | task.plan | PLANNED | complete immutable revision; context/authority current; no missing required source |
| BLOCKED | task.plan | PLANNED | blocker resolved and same revision remains valid; otherwise task.revise first |
| ESCALATED | task.plan | PLANNED | escalation resolved; same-revision contract still valid |
| PLANNED | attempt.assign | ASSIGNED | controller RUNNING; capacity; no current lease; dependencies accepted; **per-revision attempt ceiling not exhausted**; workspace reservation succeeds |
| ASSIGNED | attempt.start | BUILDING | current epoch/fence; measured clean exact base; tool/capability roster passes; process ownership established |
| BUILDING | candidate.register | BUILDING (Candidate row added) | current epoch/fence; candidate commit measured; Candidate persisted before evidence collection; evidence digest may be NULL |
| BUILDING + Candidate | evidence.register | EVIDENCE_READY | current epoch/fence; required evidence artifacts durably imported; manifest digest validated and attached |
| EVIDENCE_READY | review.request | REVIEWING | exact candidate/evidence frozen; required reviewer policy resolved; one non-terminal `review_dispatch` created per required-review slot under the current revision/epoch and a fresh dispatch fencing token |
| REVIEWING | review.record | REVIEWING (Review row added) | presented `review_dispatch_id` exists, is in state `DISPATCHED`, belongs to this exact subject/SHA, and presents the current task revision, controller epoch and that dispatch's current fencing token; presenting reviewer principal equals the dispatch's bound principal; §9 independence holds. The dispatch becomes `COMPLETED` in the same transaction. Any other case is rejected with `FENCE_STALE` and no Review row is written |
| REVIEWING | review.cancel | REVIEWING (dispatch terminal) | caller authorised or deterministic expiry/replacement condition met; dispatch moves to `CANCELLED`/`FENCED`/`EXPIRED`; owned reviewer process group stopped per §6; rejection of any later verdict from it is thereafter automatic |
| REVIEWING | candidate.accept | ACCEPTED | all required independent reviews ACCEPT, each admitted under a then-live dispatch for a distinct required-review slot; no `OPEN`/`BLOCKED` blocking finding for this candidate subject; context still current |
| REVIEWING | candidate.reject | REJECTED | one or more required reviews CHANGES_REQUIRED or blocking finding for this candidate subject |
| REJECTED | attempt.assign | ASSIGNED | same task revision; correction budget available; **per-revision attempt ceiling not exhausted**; fresh attempt/fence; prior candidate retained |
| ACCEPTED task(s) | integration.create | integration CREATED | one or more exact accepted candidate SHAs; explicit target base; dependencies/context current; source task states remain ACCEPTED |
| integration CREATED | integration.begin | integration INTEGRATING | controller RUNNING; integration capacity available; no current integration lease; workspace reservation succeeds; integration `attempt` (`subject_kind = INTEGRATION`) and authoritative `lease` are created atomically; **no preflight and no integrator process launch occur in this command** |
| integration INTEGRATING + attempt CREATED/STARTING | integration.start | integration INTEGRATING (attempt RUNNING) | current integration epoch/fence and reserved workspace; measured exact base/branch/environment/tool/capability preflight passes; owned integrator process group is established before RUNNING is committed |
| integration INTEGRATING | integration.register | integration EVIDENCE_READY | current epoch/fencing token of the live integration attempt; integration SHA independently measured; required evidence manifest exists; the integration attempt reaches `CANDIDATE_READY` and then `CLOSED / SUCCEEDED` |
| integration EVIDENCE_READY | integration.review_request | integration REVIEWING | required integrated reviewer policy resolved; one non-terminal `review_dispatch` created per required integrated-review slot |
| integration REVIEWING | integration.verify | integration VERIFIED | all required integrated tests/reviews pass, each verdict admitted under a then-live dispatch; no blocking finding whose subject is this integration is `OPEN` or `BLOCKED`; where this integration carries `parent_integration_id`, every unresolved inherited finding has an explicit `RESOLVED`/`OBSOLETE` disposition with a recorded reason |
| integration REVIEWING | integration.reject | integration REJECTED | blocking finding for this integration subject or required gate failure |
| integration CREATED/INTEGRATING/EVIDENCE_READY/REVIEWING | integration.block | integration BLOCKED | deterministic dependency/authority/evidence/resource blocker; exact reason persisted |
| integration CREATED/INTEGRATING/EVIDENCE_READY/REVIEWING/BLOCKED | integration.cancel | integration CANCELLED | caller authorised; the integration attempt's `lease` is fenced and its process group is stopped through the §6 TERM/grace/KILL sequence; process group verified empty; every non-terminal `review_dispatch` for this integration is fenced |
| integration CREATED/INTEGRATING/EVIDENCE_READY/REVIEWING/BLOCKED | integration.cancel where the process group cannot be proven empty | integration BLOCKED | integration attempt closes `QUARANTINED`; integration workspace is not reused; the blocking reason is persisted. Cancellation never reports CANCELLED on unproven cleanup |
| integration VERIFIED | release_candidate.mark | ReleaseCandidate record | GPT Director independently accepts exact integrated SHA/evidence/limitations |
| any nonterminal active | task.block | BLOCKED | typed deterministic reason persisted; active attempt fenced/stopped when continuation unsafe |
| any nonterminal active | task.escalate | ESCALATED | ambiguity/decision beyond automatic authority |
| PROPOSED/PLANNED/ASSIGNED/BUILDING/EVIDENCE_READY/REVIEWING/REJECTED/BLOCKED/ESCALATED/FAILED | task.cancel | CANCELLED | caller authorised; any active lease fenced immediately; no later result admitted |
| PROPOSED/PLANNED/ASSIGNED/BUILDING/EVIDENCE_READY/REVIEWING/REJECTED/BLOCKED/ESCALATED/FAILED | task.supersede | SUPERSEDED | replacement revision/objective reference recorded; active attempt fenced |
| PROPOSED/PLANNED/ASSIGNED/BUILDING/EVIDENCE_READY/REVIEWING/REJECTED/BLOCKED/ESCALATED/FAILED | task.revise | PROPOSED (new revision) | revision-changing authority valid; old revision immutable/superseded; active attempt fenced; new context/base/acceptance revalidated before planning |
| BUILDING/REJECTED | task.fail | FAILED | execution/correction/integration budget exhausted or unrecoverable failure within current contract |

`ACCEPTED`, `CANCELLED` and `SUPERSEDED` are terminal task states for V1. They cannot be revised, cancelled or superseded in-place. If later product intent invalidates an accepted outcome, a new task is created and dependency/currentness rules decide whether downstream work remains valid. Integration/release records have their own terminal states. A `FAILED` task does not auto-resume; continuation requires `task.revise` to a new PROPOSED revision (or explicit supersession before terminal acceptance).

## 3A. Attempt transition matrix

The matrix in §3 is authoritative for **subject-state** changes (task and integration). This attempt matrix is authoritative for **attempt-state** changes and adds attempt-specific preconditions. Where one command changes both subject and attempt state, **both tables must permit the same operation**; the kernel uses their intersection. Any disagreement is a specification error and MUST fail closed rather than allowing either table to override the other silently.

Attempt transitions are independent records from the subject state transaction but must be performed atomically with the corresponding lease/subject mutation where one exists.

This matrix applies to both attempt subject kinds. Where the trigger differs by subject kind it is named for each; everything else is identical, which is the point of the §1A generalisation. For an `INTEGRATION` attempt, read "task" as "integration", "candidate" as "integration SHA" and `task.block` as `integration.block`.

| From | Trigger/command | To | Preconditions / result |
| --- | --- | --- | --- |
| none | `attempt.assign` (TASK) / `integration.begin` (INTEGRATION) | CREATED | TASK: task is `PLANNED`, or task is `REJECTED` with bounded-correction budget available as permitted by §3; in **both TASK branches the per-revision attempt ceiling must not be exhausted**. INTEGRATION: integration is `CREATED`. Capacity/workspace reservation succeeds; new epoch/fence bound |
| CREATED | runner preflight begins | STARTING | current lease; workspace exists; no model process yet |
| STARTING | `attempt.start` (TASK) / `integration.start` (INTEGRATION) | RUNNING | exact base/branch/environment/tool/capability checks pass; owned process group established |
| STARTING | preflight deterministic failure | CLOSED / FAILED or QUARANTINED | no model launch; a TASK subject reaches `BLOCKED` through §3 `task.block`, while an INTEGRATION subject reaches `BLOCKED` through §3 `integration.block`, using the typed precondition reason. Attempt disposition is `FAILED` when cleanup is proven complete, or `QUARANTINED` when process/workspace safety cannot be proven. Preflight failure never fabricates RUNNING and never uses an unlisted direct subject transition. |
| RUNNING | `candidate.register` (TASK) / `integration.register` (INTEGRATION) | CANDIDATE_READY | current epoch/fence; immutable commit identity independently measured and the Candidate / integration SHA persisted |
| RUNNING | process exits without producing a commit | CLOSED / FAILED | diagnostics/evidence persisted; the subject takes the §10.3 non-rejection path of `ORCHESTRATOR_V1_FREEZE_CONTRACT.md`, which is a finite persistent budget rather than implementer discretion |
| RUNNING | process stalls past its deadline with no commit | CLOSED / FAILED or QUARANTINED | reason code `PROCESS_STALLED`/`PROCESS_TIMEOUT`, which §7 classifies BLOCKED; disposition is `FAILED` when cleanup is proven and `QUARANTINED` otherwise; the subject reaches BLOCKED through its legal block edge |
| RUNNING | `task.cancel` / `integration.cancel` / fencing event | CLOSED / CANCELLED or FENCED | old token immediately loses authority; process cleanup follows §6 |
| RUNNING | process cannot be proven stopped | CLOSED / QUARANTINED | subject BLOCKED; workspace cannot be reused |
| CANDIDATE_READY | evidence completion / subject reaches EVIDENCE_READY | CLOSED / SUCCEEDED | commit already durable; no later worker authority needed |
| CANDIDATE_READY | cancellation/fence before evidence completion | CLOSED / FENCED | the Candidate or integration SHA remains durable/discoverable; evidence may remain incomplete |

`CLOSED` is terminal for an attempt. A correction always creates a new attempt with a new fencing token.

## 3B. Review dispatch transition matrix

Authoritative for `review_dispatch` state. Review dispatch is the third execution record of §1A; it is not an `attempt`, because independence requires several concurrent reviewer principals for one subject and a single per-subject lease cannot express that.

| From | Trigger/command | To | Preconditions / result |
| --- | --- | --- | --- |
| none | `review.request` / `integration.review_request` | DISPATCHED | subject is `REVIEWING`; exact subject SHA and evidence-manifest digest frozen; no other non-terminal dispatch occupies this required-review slot; controller epoch and a fresh monotonic dispatch fencing token bound; §9 independence satisfiable for the bound reviewer principal |
| DISPATCHED | `review.record` | COMPLETED | preconditions of the §3 `review.record` row hold; the Review row and this terminal transition are one transaction |
| DISPATCHED | `review.cancel` by authorised caller | CANCELLED | owned reviewer process group stopped per §6; no verdict admitted |
| DISPATCHED | heartbeat/expiry deadline passes without a verdict | EXPIRED | expiry is deterministic and recorded; the subject does not silently remain in `REVIEWING`; policy then either creates exactly one replacement dispatch for the slot or blocks the subject, never both |
| DISPATCHED | replacement dispatch required for the same slot, or `task.cancel`/`task.supersede`/`task.revise`/`integration.cancel`, or controller-epoch change | FENCED | fencing happens **before** any replacement row is created, so the slot uniqueness constraint holds and the original reviewer loses authority even though the subject SHA is unchanged |
| DISPATCHED | reviewer process cannot be proven stopped after cancellation/expiry | FENCED, subject BLOCKED | the dispatch loses authority immediately, but the subject is BLOCKED rather than re-dispatched, mirroring the attempt quarantine rule |

Every terminal state is final. A verdict presented for a terminal, unknown or non-matching dispatch is rejected with `FENCE_STALE`, and the rejection is recorded as a `transition_event`.

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

On cancellation:

1. transactionally mark cancellation requested and advance/fence lease authority;
2. stop accepting heartbeats/candidates/evidence from the old token;
3. send TERM to the attempt cgroup/process group;
4. after configured grace, send KILL;
5. verify process group empty;
6. if empty, close attempt CANCELLED;
7. if not provably empty, mark attempt QUARANTINED and task BLOCKED.

A candidate arriving after step 1 is stale even if it was produced before the signal reached the process.

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
| `REMOTE_EFFECT_UNKNOWN` | BLOCKED | BLOCKED until reconciled; reconciliation may then permit a bounded retry under §9 |
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
