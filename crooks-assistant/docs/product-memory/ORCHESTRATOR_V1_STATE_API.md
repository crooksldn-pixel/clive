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
- task/revision;
- source kind/id;
- severity;
- disposition `OPEN|RESOLVED|BLOCKED|OBSOLETE`;
- summary digest;
- evidence reference;
- created/resolved timestamps.

### `attempt`
- `attempt_id TEXT PRIMARY KEY`
- task/revision;
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

### `lease`
One authoritative lease per `(task_id, revision)`.
- attempt ID;
- controller epoch;
- fencing token;
- acquired time;
- heartbeat deadline.

Lease replacement and fencing-token increment occur atomically.

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
- candidate SHA UNIQUE within repository identity;
- diff digest;
- changed-files digest;
- environment digest;
- evidence-manifest digest;
- created timestamp.

Candidate rows are immutable. A replacement candidate is a new row.

### `evidence_manifest`
- `manifest_digest TEXT PRIMARY KEY`;
- schema version;
- candidate SHA;
- storage root/reference;
- redaction status;
- created timestamp.

Canonical manifest bytes use UTF-8 canonical JSON with stable key ordering and no insignificant whitespace; SHA-256 is computed over those exact bytes.

### `review`
- `review_id TEXT PRIMARY KEY`;
- candidate SHA;
- evidence-manifest digest;
- reviewer principal/session identity;
- reviewer role;
- verdict `ACCEPT|CHANGES_REQUIRED|BLOCKED`;
- findings digest;
- created timestamp;
- invalidated timestamp nullable.

### `integration`
- `integration_id TEXT PRIMARY KEY`;
- target base SHA;
- ordered input-SHA digest;
- integration SHA nullable until committed;
- integration-only-edit digest;
- evidence-manifest digest;
- state;
- created/updated timestamps.

### `delivery`
Represents publication independently from work completion.
- `delivery_id TEXT PRIMARY KEY`;
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
- task/revision;
- attempt/candidate/review/integration identifiers as applicable;
- from/to state;
- actor principal;
- controller epoch;
- fencing token;
- reason code;
- trace ID;
- payload digest;
- timestamp.

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
| `attempt.assign` | scheduler | PLANNED -> ASSIGNED; create attempt/workspace reservation + lease |
| `attempt.start` | runner adapter | ASSIGNED -> BUILDING only after measured preflight |
| `attempt.heartbeat` | current runner adapter | renew current lease only |
| `attempt.cancel_ack` | runner/process manager | record process-tree stop/quarantine outcome |
| `candidate.register` | deterministic collector | BUILDING -> EVIDENCE_READY when immutable commit + required evidence exist |
| `evidence.register` | collector/CI adapter | attach content-addressed evidence |
| `review.request` | review coordinator | EVIDENCE_READY -> REVIEWING |
| `review.record` | validated independent reviewer channel | persist exact-SHA verdict/findings |
| `candidate.accept` | kernel policy | REVIEWING -> ACCEPTED only when all required reviews/findings satisfy policy |
| `candidate.reject` | kernel policy | REVIEWING -> REJECTED |
| `integration.begin` | integrator coordinator | ACCEPTED -> INTEGRATING; bind exact ordered input SHAs |
| `integration.register` | deterministic collector | persist integration SHA + evidence |
| `integration.verify` | kernel policy/CI/review coordinator | INTEGRATING -> VERIFIED |
| `release_candidate.mark` | GPT Director validated channel + kernel policy | VERIFIED -> RELEASE_CANDIDATE |
| `delivery.publish` | publication adapter | publish immutable result/ref with idempotency |
| `controller.reconcile` | authoritative controller | observe DB/process/workspace/remote truth; no blind effects |
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
| PLANNED | attempt.assign | ASSIGNED | controller RUNNING; capacity; no current lease; dependencies accepted; workspace reservation succeeds |
| ASSIGNED | attempt.start | BUILDING | current epoch/fence; measured clean exact base; tool/capability roster passes; process ownership established |
| BUILDING | candidate.register | EVIDENCE_READY | current epoch/fence; candidate commit measured; required evidence manifest complete |
| EVIDENCE_READY | review.request | REVIEWING | exact candidate/evidence frozen; required reviewer policy resolved |
| REVIEWING | candidate.accept | ACCEPTED | all required independent reviews ACCEPT; no OPEN/BLOCKED blocking findings; context still current |
| REVIEWING | candidate.reject | REJECTED | one or more required reviews CHANGES_REQUIRED or blocking finding |
| REJECTED | attempt.assign | ASSIGNED | same task revision; correction budget available; fresh attempt/fence; prior candidate retained |
| ACCEPTED | integration.begin | INTEGRATING | exact accepted SHAs; explicit target base; dependencies/context current |
| INTEGRATING | integration.verify | VERIFIED | integration SHA measured; required integrated evidence/reviews pass |
| VERIFIED | release_candidate.mark | RELEASE_CANDIDATE | GPT Director independently accepts exact integrated SHA/evidence/limitations |
| any nonterminal active | task.block | BLOCKED | typed deterministic reason persisted; active attempt fenced/stopped when continuation unsafe |
| any nonterminal active | task.escalate | ESCALATED | ambiguity/decision beyond automatic authority |
| PROPOSED/PLANNED/ASSIGNED/BUILDING/EVIDENCE_READY/REVIEWING/ACCEPTED/REJECTED/INTEGRATING/VERIFIED/BLOCKED/ESCALATED/FAILED | task.cancel | CANCELLED | caller authorised; any active lease fenced immediately; no later result admitted |
| any state except RELEASE_CANDIDATE/CANCELLED/SUPERSEDED | task.supersede | SUPERSEDED | replacement revision/objective reference recorded; active attempt fenced |
| any state except RELEASE_CANDIDATE/CANCELLED/SUPERSEDED | task.revise | PROPOSED (new revision) | revision-changing authority valid; old revision immutable/superseded; active attempt fenced; new context/base/acceptance revalidated before planning |
| BUILDING/REJECTED/INTEGRATING | task.fail | FAILED | execution/correction/integration budget exhausted or unrecoverable failure within current contract |

`RELEASE_CANDIDATE`, `CANCELLED` and `SUPERSEDED` are terminal for V1. A `FAILED` task does not auto-resume; continuation requires `task.revise` to a new PROPOSED revision (or explicit supersession).

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

Minimum stable reason classes:

- `PRECONDITION_BASE_MISMATCH`
- `PRECONDITION_BRANCH_MISMATCH`
- `PRECONDITION_DIRTY_WORKSPACE`
- `PRECONDITION_TOOL_ROSTER_MISMATCH`
- `PRECONDITION_CAPABILITY_MISSING`
- `AUTH_EXPIRED`
- `AUTH_FORBIDDEN`
- `QUOTA_EXHAUSTED`
- `PROVIDER_RATE_LIMIT`
- `PROVIDER_TRANSIENT`
- `PROVIDER_UNAVAILABLE`
- `PROCESS_TIMEOUT`
- `PROCESS_STALLED`
- `PROCESS_ORPHANED`
- `RESOURCE_DISK_HIGH_WATERMARK`
- `RESOURCE_CAPACITY`
- `DB_INTEGRITY`
- `DB_IO`
- `REMOTE_EFFECT_UNKNOWN`
- `PUBLICATION_CONFLICT`
- `EVIDENCE_MISSING`
- `EVIDENCE_DIGEST_MISMATCH`
- `REVIEW_BLOCKED`
- `REVIEW_REJECTED`
- `CONTEXT_STALE`
- `AUTHORITY_STALE`
- `DEPENDENCY_BLOCKED`
- `POLICY_VIOLATION`

Implementations MAY add more specific subcodes but MUST preserve stable top-level classification into RETRYABLE, BLOCKED, REJECTED/FAILED or ESCALATED.

## 8. Artifact store write protocol

Evidence/artifact storage MUST be crash-safe:

1. write to a unique temporary file inside the artifact root;
2. fsync file;
3. compute/verify SHA-256;
4. atomically rename into `sha256/<digest>`;
5. fsync containing directory where supported;
6. only then register digest in the DB.

A DB evidence record MUST NOT point to an artifact that has not completed this protocol.

## 9. Review independence identity

A review is independent only if:

- reviewer session/principal differs from implementation attempt/session;
- reviewer has no write access to the candidate workspace/branch through the review channel;
- reviewer is given immutable candidate/evidence identity;
- any patch authored by the reviewer is treated as a new implementation candidate and cannot be certified by the same review record.

Using the same model family is permitted; independence is an authority/session/workspace property, not a vendor-name property.

## 10. Static invariants

The following are documentary/static and do not require a runtime transition test:

- no V1 production deployment authority;
- no business-write authority;
- no global/account Claude/MCP/connector changes;
- no external spend without owner approval;
- no destructive cleanup of owner work;
- branches are labels, SHAs are authority;
- implementation workers never self-certify.
