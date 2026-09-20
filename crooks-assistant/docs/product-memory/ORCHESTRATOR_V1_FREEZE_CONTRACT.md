# CLIVE Engineering Orchestrator V1 — Freeze Contract

**Status:** FREEZE CANDIDATE — normative contract, repository-only; no deployment authority  
**Date:** 2026-09-20  
**Canonical parent:** `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`  
**Purpose:** collapse the approved Orchestrator direction, Symphony/ECC research, contract-trial findings and incident lessons into one implementable contract.

The words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT** and **MAY** are normative.

This contract governs Engineering Orchestrator V1 together with the normative companions `ORCHESTRATOR_V1_STATE_API.md`, `ORCHESTRATOR_V1_TRACEABILITY.md` and `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md`. Older prose remains evidence and rationale, but where it conflicts with this freeze set after acceptance, the freeze set is authoritative for V1 implementation. Product safety decisions in `DECISIONS.md` remain superior.

## 1. V1 objective

V1 turns an authorised engineering task into an independently reviewed release candidate with durable state, immutable identity, bounded failure behaviour and low owner attention.

V1 is a **deterministic control plane with model workers beneath it**. Models may plan, implement, diagnose and review. Models MUST NOT authoritatively mutate task state, approval state, release authority or production.

V1 MUST preserve the existing single-worker bridge/watcher as the reliable fallback while the Orchestrator is built and proven.

## 2. Explicit non-goals

V1 does **not** include:

- production deployment or promotion;
- CROOKS/CLIVE business writes;
- automatic infrastructure self-update;
- new secrets, credential provisioning or connector grants;
- account/global Claude configuration changes;
- public/Funnel exposure;
- arbitrary shell/admin control;
- subscriber-facing agent dashboards;
- autonomous product/taste decisions;
- blanket self-improvement or overnight production changes.

A later Privileged Action Broker / Deployment Controller is a separate authority domain.

## 3. Authority model

| Principal | MAY | MUST NOT |
| --- | --- | --- |
| Owner | set intent; grant material permissions; approve owner-gated release/privilege decisions | be required as routine message courier |
| GPT Director | compile objective/scope; reconcile evidence; challenge plans; perform final independent review | mutate state DB directly; deploy; self-authorise owner gates |
| Deterministic kernel | validate contracts; persist state; schedule; fence; admit results; dispatch reviews; enforce policy | make product judgement; infer approval from prose |
| Evidence Collector (kernel component) | measure committed workspace identity read-only; copy/hash evidence from worker staging into kernel-owned immutable storage; create Candidate/Evidence records | execute candidate-controlled code to determine identity; run inside worker process group; accept worker prose as identity |
| Architecture specialist (normally Opus) | propose plans/contracts; diagnose ambiguity; perform high-scrutiny technical review | grant itself scope, privileges or acceptance |
| Implementation worker | modify one authorised attempt workspace and produce one candidate | accept/review itself; write controller DB; deploy; access unrelated business tools |
| Independent reviewer | inspect exact candidate/evidence and submit findings/verdict through validated channel | modify the candidate it certifies |
| Integrator | combine exact accepted SHAs in an isolated integration workspace | substitute branch heads; waive blocking findings |
| Fable Experience Director | define/review substantial UX/interaction requirements where required | override owner intent, safety policy or current design authority |
| Future deployment controller | install an explicitly authorised exact artifact and verify/rollback | act as engineering planner or accept its own update |

Roles are responsibilities, not mandatory permanent daemons.

## 4. Authoritative identity rules

**Branches are labels. SHAs are authority.**

Every execution-bearing record MUST bind:

- repository identity;
- task ID and immutable task revision;
- product-memory SHA;
- application/base SHA;
- environment/toolchain manifest digest;
- attempt ID;
- workspace ID/path;
- controller epoch;
- monotonic fencing token;
- candidate SHA, once one exists;
- evidence-manifest digest;
- reviewer identity and review subject SHA.

The kernel MUST independently measure checkout `HEAD`, ancestry and cleanliness. Prompt text, worker self-report, branch name, screenshot or prose MUST NOT substitute for measured Git identity.

A branch mismatch between declared routing metadata and actual checkout MUST block write-capable execution before any model is launched.

## 5. State model

Task, attempt, candidate, review, integration and delivery are separate records.

### 5.1 Task lifecycle

`PROPOSED -> PLANNED -> ASSIGNED -> BUILDING -> EVIDENCE_READY -> REVIEWING -> ACCEPTED`

`ACCEPTED` is terminal for an individual task/candidate. Integration and release-candidate state are separate records; multiple accepted tasks may feed one integration. This prevents a task record from pretending to own a multi-candidate release.

Side states:

- `BLOCKED` — deterministic precondition/capability/authority problem; no automatic retry.
- `ESCALATED` — requires higher-level diagnosis or owner/Director decision.
- `REJECTED` — candidate failed review/acceptance; retained with reasons.
- `FAILED` — execution failed within the approved task contract and retry/correction budget is exhausted.
- `CANCELLED` — explicitly stopped; all active attempts fenced.
- `SUPERSEDED` — replaced by a new task revision/objective.

No state name implies deployment.

### 5.2 Attempt lifecycle

`CREATED -> STARTING -> RUNNING -> CANDIDATE_READY -> CLOSED`

Terminal attempt dispositions:

- `SUCCEEDED`
- `FAILED`
- `CANCELLED`
- `FENCED`
- `QUARANTINED`

A task may have multiple attempts. Only one attempt may hold the authoritative lease for a task revision at a time.

### 5.3 Finding lifecycle

Every review/test finding has its own disposition:

- `OPEN`
- `RESOLVED`
- `BLOCKED`
- `OBSOLETE`

This closes contract gap CG-04: partial progress is represented without falsely calling the whole task complete.

## 6. Durable store

V1 is single-host. The authoritative store MUST be SQLite for frozen V1. Replacing it requires a new reviewed revision of this contract; implementation may not substitute another store under an informal architecture exception.

Required SQLite settings/behaviour:

- WAL journal mode;
- `foreign_keys=ON`;
- `synchronous=FULL` for authoritative state transitions;
- bounded busy timeout;
- explicit schema version;
- migrations executed under exclusive controller authority;
- integrity check at startup and before/after schema migration;
- pre-migration online backup;
- transactionally atomic state transition + transition-event append;
- unique constraints for idempotency keys and authoritative lease ownership;
- no direct model/worker database access.

Database corruption or failed integrity check MUST stop scheduling and enter operator-visible `BLOCKED`; V1 MUST NOT guess-repair authoritative state.

Before model-running V1 is enabled, a tested online-backup destination independent of the active DB file MUST exist. Backups are required before every schema migration and at controlled periodic intervals chosen to meet the declared recovery-point objective; backup integrity and restore are rehearsed in acceptance. Backups MUST never be restored while an older controller instance can still publish authoritative results. Restore increments the controller epoch, enters DRAINING/BLOCKED until reconciliation finishes, and invalidates all pre-restore leases.

## 7. Single-controller authority and fencing

V1 MUST run with one authoritative controller writer.

On a single host:

1. controller acquires an OS-level exclusive runtime lock;
2. inside a DB transaction it increments and persists `controller_epoch`;
3. all new leases/results bind that epoch;
4. a second controller that cannot acquire the lock MUST fail closed or run read-only diagnostics only.

Every lease acquisition increments a per-task monotonic fencing token.

Every heartbeat, candidate admission, evidence admission, delivery update and terminal result MUST present the current task revision, controller epoch and fencing token.

A stale token MUST be rejected even if the worker is still running and its output would otherwise pass tests.

PID identity alone is never authority and PID reuse is irrelevant to correctness.

## 8. Leases and heartbeats

A lease records:

- task revision;
- attempt ID;
- controller epoch;
- fencing token;
- acquired time;
- heartbeat deadline;
- workspace ID;
- runner/process-group identity.

Heartbeats prove liveness only. They MUST NOT extend scope or mark progress/success.

Lease expiry does not by itself prove the process is dead. Before reassignment the controller MUST reconcile process/cgroup state. If the old process tree cannot be proven stopped, quarantine the workspace and block reassignment.

Clock rules:

- local timeout decisions SHOULD use a monotonic clock;
- persisted wall-clock timestamps are for audit only;
- worker-provided clocks are never authoritative.

## 9. Idempotency and external effects

Every retryable mutation MUST have a stable idempotency key.

At minimum:

- task intake;
- attempt creation;
- candidate registration;
- evidence registration;
- review request;
- review result admission;
- Git publication;
- integration creation;
- delivery/outbox publication.

V1 MUST NOT claim exactly-once model execution. It guarantees at most one **authoritative admitted result** per fenced attempt, while duplicate underlying execution may occur after failures.

If an external write may have succeeded but its response is lost, the controller MUST reconcile authoritative remote state before retrying. Blind replay after ambiguous success is forbidden.

## 10. Failure taxonomy and retry policy

Failures are classified before retry.

### 10.1 BLOCKED / no automatic retry

Examples:

- wrong branch/HEAD/base SHA;
- dirty or ambiguous workspace;
- missing permission/capability;
- missing/expired authentication;
- quota exhaustion requiring external action;
- unavailable required reviewer;
- unresolved authority conflict;
- protected-path refusal;
- disk/evidence high-watermark;
- database integrity failure;
- tool-roster mismatch;
- unsafe credential/tool surface;
- unknown external-effect outcome until reconciled.

Persist exact evidence and notify once materially; restart MUST NOT reset this classification.

### 10.2 RETRYABLE transport/provider failures

Examples:

- temporary network failure;
- provider 429 with retry guidance;
- provider 5xx;
- remote Git/API transient failure where no ambiguous write remains.

Default transport retry budget:

- maximum 5 attempts per operation;
- exponential backoff with jitter;
- respect authoritative `Retry-After`;
- maximum elapsed retry window 15 minutes;
- then transition to `BLOCKED` or `ESCALATED` with reason.

Provider auth failure is BLOCKED, not transport retry. Provider quota exhaustion is BLOCKED, not an excuse to silently downgrade model quality.

### 10.3 Build/review correction budget

Default:

- one initial implementation attempt;
- after evidence-backed rejection, at most one bounded same-contract correction;
- a second substantive rejection or changed diagnosis triggers re-planning/escalation.

A changed objective, authority, acceptance criterion or scope creates a new task revision.

## 11. Workspace contract

V1 worker attempts MUST live outside production and outside the canonical Builder checkout.

Canonical shape:

`/opt/crooks-workers/<task-id>/<attempt-id>/`

For the first implementation phase, use a **standalone clone with its own .git metadata**, created from a builder-owned local source/mirror with `--no-hardlinks` or equivalent isolation. It MUST NOT be a linked worktree of production.

Each attempt receives isolated:

- checkout/Git metadata;
- writable HOME/config location;
- temp directory;
- test DB;
- browser profile;
- ports;
- artifact staging;
- process group/cgroup.

Before launch the kernel MUST verify:

- measured HEAD equals exact base SHA;
- declared branch metadata is either absent or resolves consistently;
- working tree clean;
- Git common-dir is not production;
- no foreign worker process owns the workspace;
- effective tool/network/credential roster matches task policy;
- measured environment/toolchain fingerprint equals the environment-manifest digest bound to the task revision; an exit-0 `doctor` or self-report cannot override a fingerprint mismatch.

After cancellation/failure, the complete attempt process tree is terminated via dedicated cgroup/process group: TERM, bounded grace, then KILL. Workspace reuse is forbidden until emptiness is verified.

No reset/clean/stash of owner work is permitted as a recovery mechanism.

## 12. Capability, connector and secret isolation

Engineering workers MUST receive only engineering capabilities required by the task.

The launcher MUST assert the **effective** tool/MCP/plugin roster after launch. Prompt instructions and `--allowed-tools` alone are insufficient.

Unexpected access to business connectors (Shopify, Gmail, Google Drive, Omnisend, Resend or similar) MUST fail the attempt closed before substantive execution. Worker-tool network egress is default-deny except destinations explicitly required by the task policy. Model-provider transport, candidate publication and controller APIs are host/kernel capabilities rather than permission for arbitrary worker-shell egress.

Workers MUST NOT receive:

- production service-control authority;
- deployment credentials;
- broad SSH credentials;
- host-management sockets;
- controller-state DB write access;
- unrestricted repository push authority;
- raw secrets unrelated to the exact task.

If the current provider/runtime cannot present a sufficiently narrow effective roster, model-running V1 remains BLOCKED. This does not block repository-only deterministic kernel implementation.

## 13. Structured authority grants

Approvals that matter to execution MUST exist as structured `AuthorityGrant` records, not only prose.

A grant binds:

- grant ID;
- owner/authority source;
- task revision;
- allowed action class;
- resource/scope;
- constraints;
- expiry/revocation condition;
- exact approval text/reference digest where relevant.

The kernel enforces the structured boundary. A model cannot convert conversational prose into broader authority on its own. An expired or revoked grant is equivalent to no grant. Grant validity MUST be re-evaluated at every authority-bearing transition; revocation while an attempt is active immediately fences that attempt before any further authoritative result is admitted.

This closes contract gap CG-06.

## 14. Candidate and evidence protocol

### 14.1 Candidate

A Candidate record is created by the kernel-owned collector **immediately after an immutable commit exists and before evidence collection begins**. Creation-time fields bind:

- task revision;
- attempt;
- base SHA;
- candidate SHA;
- complete changed-file set and diff digest;
- measured workspace/environment identity.

`evidence_manifest_digest` is nullable at Candidate creation and is populated only after the evidence manifest is durably stored and validated at the `EVIDENCE_READY` transition. Candidate existence therefore survives evidence-storage, outbox or delivery failure and is independently discoverable during reconciliation.

A candidate cannot authoritatively define its own identity.

### 14.2 Evidence manifest

The collector creates a canonical JSON evidence manifest outside candidate-controlled source and computes its SHA-256 digest.

Required fields:

- schema version;
- task/revision/attempt;
- base and candidate SHA;
- context/product-memory/environment digests;
- provider/model/version/effort and measured launch identity;
- commands, cwd, timestamps, exit status;
- pass/fail/skip/deselected/timeout counts;
- raw artifact/log digests and locations;
- reproduction before/after;
- changed tests/config;
- security/performance/browser/device evidence as applicable;
- known baseline failures;
- limitations;
- redaction status.

Raw evidence is independently addressable and content-addressed where practical. Final evidence storage is kernel-owned and not writable by the worker; the worker may write only to attempt-local staging, which the collector measures and imports.

Missing evidence is UNKNOWN, never PASS.

This closes CG-01.

### 14.3 Evidence invalidation

V1 uses a deliberately strict rule: **any candidate SHA change invalidates candidate-bound evidence and review.**

Evidence reuse across candidate changes is DEFERRED to V1.x until a machine-checkable input-closure system exists.

This closes CG-02 without introducing a false-green optimisation.

### 14.4 Candidate persistence vs delivery

Candidate state is persisted independently from evidence completion and from result/outbox delivery. A candidate may exist with no evidence manifest yet, and may remain discoverable even if publication of the human/model handoff fails.

Delivery has its own durable record and idempotency key.

This closes CG-03.

### 14.5 Candidate publication

Remote candidate publication is a **kernel publication-adapter operation**, never a worker push. Attempt workspaces MUST have no usable remote push credential.

The kernel reads the exact local candidate SHA from the quarantined/read-only post-build workspace, verifies it matches the Candidate record, and publishes that commit to a create-only namespaced ref such as `orchestrator/candidate/<task-id>/<candidate-id>` using a narrow kernel credential. The ref is for discoverability only; reviewers/integrators consume the immutable SHA, never the branch name. Corrections create new candidate IDs/refs; no candidate ref is force-updated.

Unknown push outcomes use the §9 reconcile-before-retry rule.

## 15. Review contract

Reviewers receive:

- immutable task revision;
- exact base/candidate SHA;
- exact diff;
- evidence-manifest digest and raw evidence references;
- changed tests/config;
- known limitations;
- applicable policy/context digest.

Reviewer verdicts:

- `ACCEPT`
- `CHANGES_REQUIRED`
- `BLOCKED`

A reviewer may not silently patch the candidate it certifies. If it supplies code, it becomes an implementer for that new candidate and an independent reviewer must review the result.

Review records bind exact candidate/evidence identities. Candidate mutation invalidates review automatically.

Risk classification is deterministic and closed:

| Risk class | Rule | Minimum gate |
| --- | --- | --- |
| `DOCUMENTARY_NONNORMATIVE` | prose/history only; cannot change executable config, tests, policy, authority, safety, acceptance or runtime behaviour | independent document review; exact-SHA doc/schema/link checks as applicable |
| `MATERIAL` | any code, test, config, dependency, build, harness, normative policy/acceptance document, or behavior-affecting change not in a higher class | independent technical review + independent exact-SHA CI/reverification |
| `EXPERIENCE` | meaningful UI/UX/interaction change | MATERIAL gates + Fable direction/post-build review + browser/accessibility/device evidence as required |
| `SECURITY_CRITICAL` | auth, secrets, permissions, business-write semantics, controller/kernel, deployment, sandbox, credential or safety-boundary change | MATERIAL gates + independent security/architecture review + negative permission tests + owner gate where authority changes |

Unclassified work is `MATERIAL`. Models may propose a class but the kernel/policy rules compute the authoritative class.

Review independence requires at minimum: a distinct reviewer session/principal, a distinct review workspace/channel with no candidate write authority, immutable candidate/evidence inputs, and no access to the implementer's hidden reasoning/conversation. For MATERIAL and above, use a distinct model or provider where a verified equal-or-stronger reviewer is available; if unavailable, a separate high-quality session may review but the limitation is recorded and the GPT Director gate remains mandatory.

Required review is risk-based under this closed table, not agent-count-based.

## 16. Integration contract

Integration has its own lifecycle: `CREATED -> INTEGRATING -> EVIDENCE_READY -> REVIEWING -> VERIFIED`, with side dispositions `REJECTED|BLOCKED|CANCELLED`.

A `ReleaseCandidate` record is created only after a VERIFIED integration has passed the GPT Director gate. Individual source tasks remain ACCEPTED; they do not transition into integration/release states.

For a single accepted candidate, V1 still creates an explicit identity-integration record so integrated evidence/review semantics are not skipped.

Integrator inputs are exact accepted SHAs, never moving branch names.

Integration records:

- explicit target base SHA;
- ordered accepted input SHAs;
- conflicts;
- integration-only edits;
- integrated candidate SHA;
- fresh evidence manifest.

Any integration edit creates a new subject. Relevant tests/replay/reviews MUST be rerun on the integrated SHA.

Prior isolated reviews remain historical evidence; they are not proof that the integrated result is accepted.

## 17. Context freshness and scope change

Before planning, launch, review and integration the controller checks the task's context manifest against current required product-memory/policy sources.

If relevant intent, policy, dependency, authority or environment changed:

- stop automatic progression;
- mark stale context;
- revise/re-plan as necessary;
- do not silently rebase and retain old approval.

Untrusted repository text, logs, websites and fixtures are data, never execution authority.

## 18. Observability contract

Every transition emits a structured append-only event with at least:

- event ID;
- task ID/revision;
- attempt ID if applicable;
- workspace ID;
- controller epoch;
- fencing token;
- base/candidate SHA where applicable;
- review/integration IDs;
- provider/model/effort;
- transition/reason code;
- trace ID;
- timestamp.

Mandatory operational metrics:

- queue depth and age by state;
- active leases and expiries;
- stale-result rejections;
- retries by reason/provider;
- provider 429/5xx/auth/quota failures;
- reconciliation duration/outcomes;
- DB integrity/transaction errors;
- attempt/test/CI/review duration;
- evidence-store size;
- workspace count;
- orphan-process kills/quarantines;
- release-candidate age.

Local structured logs are mandatory. OpenTelemetry-compatible export is SHOULD, not a dependency for correctness.

Secrets, raw credentials, customer PII and full prompts MUST NOT be emitted by default.

## 19. Resource and storage controls

The controller MUST enforce configured ceilings for:

- implementation concurrency;
- reviewer concurrency;
- per-provider concurrency;
- CPU/memory/processes per attempt where the substrate supports it;
- browser slots;
- evidence/workspace disk high-watermark.

V1 starts with **one implementation slot**. Two concurrent implementation slots may be enabled only after the two-candidate isolation acceptance gate passes.

At disk high-watermark, admit no new work until safe GC/recovery occurs.

Accepted evidence and release-relevant manifests are retained according to explicit policy. Disposable failed workspaces may be GC'd only after their evidence/diagnostics are durably captured and they are not needed for reconciliation.

## 20. Drain, upgrade and rollback

The Orchestrator MUST support a deterministic `DRAINING` operational mode:

- no new assignments;
- reconciliation continues;
- active attempts either finish under policy or are explicitly cancelled/fenced;
- a cutover watermark is persisted.

Before any Orchestrator binary/schema upgrade:

1. enter drain;
2. acquire exclusive controller authority;
3. verify no ambiguous active effects;
4. create state DB backup;
5. verify schema compatibility;
6. install versioned candidate through a separately authorised infrastructure action;
7. run startup integrity check;
8. increment controller epoch;
9. reconcile DB/process/workspace/remote state;
10. run deterministic smoke tests;
11. resume scheduling only if all gates pass.

Schema migrations are forward-only in V1. An older binary MUST refuse a newer unsupported schema. Unsafe downgrade fails closed.

An ordinary engineering worker MUST NOT self-install the Orchestrator.

## 21. Crash/restart reconciliation order

On controller start/restart:

1. acquire exclusive runtime lock;
2. open DB and verify schema/integrity;
3. increment controller epoch;
4. enter implicit drain/no-dispatch mode;
5. reconcile recorded active attempts with cgroups/processes;
6. reconcile workspaces and measured Git identity;
7. reconcile candidate/evidence records;
8. reconcile ambiguous remote publications;
9. fence obsolete leases/results;
10. surface unresolved ambiguity as BLOCKED;
11. only then enable dispatch.

Absence of a heartbeat, process or outbox is never enough by itself to conclude that work never completed.

## 22. CI and provenance

Worker-local evidence is necessary but insufficient for material candidates.

Required CI/reverification policy is task-risk based, but CI MUST:

- checkout exact candidate SHA;
- run independently of the implementation worker's mutable workspace;
- publish machine-readable results bound to that SHA;
- prevent the implementer from marking itself accepted.

Security-sensitive changes require negative permission/security tests.

CodeQL/equivalent static analysis SHOULD be required for relevant code classes. SBOMs and external artifact attestations are REQUIRED only for releasable deployable artifacts, not every repository-only documentation or tiny test candidate.

## 22A. Clean reconstruction claims

Whenever a task or release claims that an environment/toolchain is reproducibly reconstructible, that claim MUST be proved on a disposable environment with no pre-existing target toolchain state.

The reconstruction contract MUST include:

- explicit approved egress policy and destination allow-list;
- pinned release tags/asset URLs or equivalent immutable package identities;
- pre-extraction/download integrity verification;
- post-install/version/provenance verification;
- a fresh environment fingerprint;
- equality of the reconstructed fingerprint to the declared environment manifest;
- evidence that pre-existing local tooling did not satisfy the test accidentally.

A rerun on the already-provisioned Builder is not reconstruction evidence.

## 23. Symphony/ECC reuse boundary

V1 adopts commodity mechanisms, not external authority semantics.

From Symphony, V1 retains:

- authoritative assignment state;
- deterministic per-task workspace;
- bounded concurrency;
- heartbeat/reconciliation;
- stale completion rejection;
- retry/backoff;
- drain/cutover semantics;
- continuous operator-visible status.

CLIVE remains stricter through durable task revisions, exact SHA/evidence binding, independent review, structured authority grants, integration re-verification and owner-only release/privilege classes.

From ECC/skills research, V1 selectively adopts/reimplements methodology and guards. It MUST NOT import the full ECC plugin/runtime/MCP/memory graph.

## 24. Contract-trial gaps resolved by this freeze

- **CG-01:** evidence manifest identity -> canonical JSON + SHA-256 + independently addressable raw artifacts.
- **CG-02:** invalidation granularity -> strict full invalidation on candidate SHA change in V1; reuse deferred.
- **CG-03:** candidate without result -> Candidate record is independent of Delivery record.
- **CG-04:** partial BLOCKED state -> per-finding dispositions plus task-level BLOCKED.
- **CG-05:** clean reconstruction -> resolved normatively by §22A and EN-01..EN-03 acceptance cases.
- **CG-06:** approval prose -> structured AuthorityGrant bound to task/scope.

## 25. Owner-only decisions

V1 engineering may decide deterministic implementation details that preserve this contract.

Owner input is required only for:

- material product/taste/strategy choices;
- new permissions or privilege expansion;
- new secrets/credential provisioning;
- external spend;
- connector/MCP grant changes;
- CROOKS business-write authority;
- public exposure;
- production deployment/promotion;
- explicit exception to an active safety contract.

Routine DB schema details, retry code, tests, worker plumbing and non-privileged repository-only implementation do not require owner decisions if they stay inside this contract.

## 26. Initial implementation phases

### Phase 0 — repository-only deterministic kernel

Implement and fault-test:

- schema/store;
- task/revision records;
- legal transition engine;
- controller epoch;
- leases/fencing;
- idempotency;
- typed failure taxonomy;
- event journal;
- reconciliation engine with fake processes/remotes;
- candidate/evidence record schemas.

**No model launch. No external business call. No deployment.**

### Phase 1 — one isolated worker adapter

Only after Phase 0 acceptance:

- one implementation slot;
- exact-base workspace creation;
- process/cgroup ownership;
- launch-roster assertion;
- candidate/evidence collection;
- no concurrency yet.

### Phase 2 — independent review/CI

Add exact-SHA review and independent CI evidence.

### Phase 3 — integration

Add exact-SHA Integrator and integrated re-verification.

### Phase 4 — bounded concurrency

Only after two-candidate isolation/resource/fencing acceptance succeeds.

### Phase 5 — specialist routing

Add evidence-based Opus/Sonnet/Fable routing and external GPT Director automation only after each adapter is independently verified.

Production deployment remains outside V1 implementation authority.

## 27. Freeze acceptance rule

This specification is a candidate until the Owner adopts an exact candidate SHA in `DECISIONS.md`. A Director/authored document cannot re-sequence owner gates or promote itself to normative authority. Any sequencing change from active DEC-046/DEC-047 must be stated explicitly in that owner decision.

The accepted freeze SHA is then recorded in a separate follow-up canonical product-memory commit, matching the existing harness-acceptance pattern; the recording commit does not alter the frozen contract content.

This specification may be marked **FROZEN V1** only when:

1. traceability matrix has no unexplained V1-relevant research item;
2. state/API contract has no undefined authoritative transition or mutation path;
3. acceptance/fault-injection matrix covers every MUST-level invariant;
4. canonical current-truth/roadmap drift is reconciled;
5. the existing bridge branch/checkout identity defect has a reviewed remediation path and write-capable V1 does not depend on the defective assumption;
6. independent adversarial review finds no material missing control-plane/safety/recovery contract;
7. the exact freeze commit SHA is recorded in canonical product memory.

Implementation MUST bind to that exact frozen SHA.