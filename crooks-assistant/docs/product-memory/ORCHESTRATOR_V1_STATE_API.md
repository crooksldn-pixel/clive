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
| `candidate.register` | deterministic collector | while task remains BUILDING, create durable Candidate immediately after immutable commit identity is measured; does not itself advance task state |
| `evidence.register` | collector/CI adapter | attach content-addressed evidence; when required manifest is complete, advance BUILDING -> EVIDENCE_READY atomically |
| `review.request` | review coordinator | EVIDENCE_READY -> REVIEWING |
| `review.record` | validated independent reviewer channel | persist exact-SHA verdict/findings |
| `candidate.accept` | kernel policy | REVIEWING -> ACCEPTED only when all required reviews/findings satisfy policy |
| `candidate.reject` | kernel policy | REVIEWING -> REJECTED |
| `integration.create` | integration coordinator | create separate CREATED integration from one or more exact ACCEPTED candidate SHAs |
| `integration.begin` | integrator coordinator | CREATED -> INTEGRATING |
| `integration.register` | deterministic collector | INTEGRATING -> EVIDENCE_READY after integration SHA + evidence exist |
| `integration.review_request` | review coordinator | EVIDENCE_READY -> REVIEWING |
| `integration.verify` | kernel policy/CI/review coordinator | REVIEWING -> VERIFIED when required integrated gates pass |
| `integration.reject` | kernel policy | REVIEWING -> REJECTED on blocking integrated finding; REJECTED integration is immutable/terminal and any correction uses a new integration record with parent_integration_id |
| `release_candidate.mark` | GPT Director validated channel + kernel policy | create immutable ReleaseCandidate from VERIFIED integration |
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
| BUILDING | candidate.register | BUILDING (Candidate row added) | current epoch/fence; candidate commit measured; Candidate persisted before evidence collection; evidence digest may be NULL |
| BUILDING + Candidate | evidence.register | EVIDENCE_READY | current epoch/fence; required evidence artifacts durably imported; manifest digest validated and attached |
| EVIDENCE_READY | review.request | REVIEWING | exact candidate/evidence frozen; required reviewer policy resolved |
| REVIEWING | candidate.accept | ACCEPTED | all required independent reviews ACCEPT; no OPEN/BLOCKED blocking findings; context still current |
| REVIEWING | candidate.reject | REJECTED | one or more required reviews CHANGES_REQUIRED or blocking finding |
| REJECTED | attempt.assign | ASSIGNED | same task revision; correction budget available; fresh attempt/fence; prior candidate retained |
| ACCEPTED task(s) | integration.create | integration CREATED | one or more exact accepted candidate SHAs; explicit target base; dependencies/context current; source task states remain ACCEPTED |
| integration CREATED | integration.begin | integration INTEGRATING | integrator workspace/base preflight passes |
| integration INTEGRATING | integration.register | integration EVIDENCE_READY | integration SHA measured; required evidence manifest exists |
| integration EVIDENCE_READY | integration.review_request | integration REVIEWING | required integrated reviewer policy resolved |
| integration REVIEWING | integration.verify | integration VERIFIED | all required integrated tests/reviews pass; no blocking findings |
| integration REVIEWING | integration.reject | integration REJECTED | blocking finding or required gate failure |
| integration VERIFIED | release_candidate.mark | ReleaseCandidate record | GPT Director independently accepts exact integrated SHA/evidence/limitations |
| any nonterminal active | task.block | BLOCKED | typed deterministic reason persisted; active attempt fenced/stopped when continuation unsafe |
| any nonterminal active | task.escalate | ESCALATED | ambiguity/decision beyond automatic authority |
| PROPOSED/PLANNED/ASSIGNED/BUILDING/EVIDENCE_READY/REVIEWING/REJECTED/BLOCKED/ESCALATED/FAILED | task.cancel | CANCELLED | caller authorised; any active lease fenced immediately; no later result admitted |
| PROPOSED/PLANNED/ASSIGNED/BUILDING/EVIDENCE_READY/REVIEWING/REJECTED/BLOCKED/ESCALATED/FAILED | task.supersede | SUPERSEDED | replacement revision/objective reference recorded; active attempt fenced |
| PROPOSED/PLANNED/ASSIGNED/BUILDING/EVIDENCE_READY/REVIEWING/REJECTED/BLOCKED/ESCALATED/FAILED | task.revise | PROPOSED (new revision) | revision-changing authority valid; old revision immutable/superseded; active attempt fenced; new context/base/acceptance revalidated before planning |
| BUILDING/REJECTED | task.fail | FAILED | execution/correction/integration budget exhausted or unrecoverable failure within current contract |

`ACCEPTED`, `CANCELLED` and `SUPERSEDED` are terminal task states for V1. They cannot be revised, cancelled or superseded in-place. If later product intent invalidates an accepted outcome, a new task is created and dependency/currentness rules decide whether downstream work remains valid. Integration/release records have their own terminal states. A `FAILED` task does not auto-resume; continuation requires `task.revise` to a new PROPOSED revision (or explicit supersession before terminal acceptance).

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
