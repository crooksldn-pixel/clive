# Engineering Orchestrator V1 — Acceptance and Fault-Injection Matrix

**Status:** FREEZE CANDIDATE companion  
**Date:** 2026-09-20  
**Rule:** a MUST-level invariant is not frozen unless at least one deterministic test proves the positive path and one negative/fault path where applicable.

## 1. Test layers

1. **Schema/unit** — DB constraints, serializers, policy tables, transition guards.
2. **State-machine/property** — generated legal/illegal transition sequences, idempotency and fencing.
3. **Fault injection** — process kill, network ambiguity, disk/database faults, clock/lease edges.
4. **Workspace/process integration** — real Git repos, process groups/cgroups, wrong-branch/dirty/symlink/tool-roster failures.
5. **Independent CI** — exact SHA checked independently from worker workspace.
6. **End-to-end** — one bounded task through build, evidence, review, integration and Director gate; no deployment.

## 2. Core state and idempotency

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| ST-01 | create task with same idempotency key twice | one task revision; duplicate returns same authoritative identity |
| ST-02 | mutate objective/scope/authority on existing revision | rejected; caller must create new revision |
| ST-03 | legal lifecycle progression | each transition atomically writes state + journal event |
| ST-04 | illegal transition, e.g. PROPOSED -> ACCEPTED | rejected with stable typed error; no partial write |
| ST-05 | kill controller between transition DB statements | after restart state/event are both committed or both absent |
| ST-06 | duplicate candidate registration | same candidate record, no duplicate authoritative candidate |
| ST-07 | duplicate review result | idempotent if exact identity/result matches; conflict rejected |
| ST-08 | task restart does not reset retry/correction counters | persisted counters unchanged |
| ST-09 | finding can be BLOCKED while other findings RESOLVED | partial progress represented without task false-success |
| ST-10 | restore DB backup | controller epoch increments; all old leases/results are stale |

## 2A. Command/transition completeness

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| API-01 | enumerate every task state × command pair | only pairs listed in the normative transition matrix can mutate state; all others reject without side effects |
| API-02 | same idempotency key + same canonical request | stored result returned; no duplicate transition/event |
| API-03 | same idempotency key + different canonical request | conflict; no mutation |
| API-04 | BLOCKED/ESCALATED resume with unchanged valid revision | must pass task.plan validation before execution resumes |
| API-05 | scope/authority/acceptance changed while blocked | old revision cannot resume; task.revise required and active attempt fenced |
| API-06 | dependency candidate not ACCEPTED/current | scheduler leaves dependent task blocked/unqueued; no attempt created |
| API-07 | slot capacity exhausted | task remains planned/queued; retry/correction budget unchanged |
| API-08 | external effect intent persisted, effect succeeds, process dies before outcome persistence | recovery enters UNKNOWN/reconcile path and observes remote identity before any repeat |
| API-09 | evidence artifact write dies before atomic rename | no DB manifest registration points at partial artifact |
| API-10 | reviewer session identity equals implementer attempt/session | independence check rejects review |

## 3. Controller authority and split-brain

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| CT-01 | start controller A | acquires exclusive lock, increments epoch, may schedule |
| CT-02 | start controller B concurrently | cannot become writer; no state mutation/dispatch |
| CT-03 | kill A, then start B | B increments epoch and reconciles before dispatch |
| CT-04 | A process somehow continues after B epoch established | all A result writes rejected by epoch/token checks |
| CT-05 | PID reused by unrelated process | no authority granted from PID alone |
| CT-06 | runtime lock unavailable/ambiguous | scheduling fails closed |

## 4. Lease, heartbeat and fencing

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| LS-01 | attempt acquires lease | task revision, epoch and monotonic fence persisted atomically |
| LS-02 | valid heartbeat | deadline renewed; no task state success implied |
| LS-03 | stale fencing token heartbeat | rejected |
| LS-04 | stale worker publishes candidate after reassignment | rejected; candidate cannot become authoritative |
| LS-05 | lease expires but process still alive | no reassignment until process reconciliation/termination succeeds |
| LS-06 | process cannot be killed | workspace QUARANTINED; task BLOCKED |
| LS-07 | controller restart with active recorded lease | reconcile process/workspace; do not blindly duplicate dispatch |
| LS-08 | worker clock lies/skews | no effect on authoritative lease decisions |

## 5. Workspace and Git identity

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| WS-01 | clean standalone workspace at exact base SHA | launch permitted |
| WS-02 | declared branch differs from actual branch/HEAD | write-capable launch blocked before model start |
| WS-03 | HEAD differs from task base SHA | blocked |
| WS-04 | dirty workspace | blocked; no reset/clean/stash performed |
| WS-05 | workspace Git common-dir points into production | blocked |
| WS-06 | symlink/path escape reaches protected tree | blocked |
| WS-07 | foreign worker process owns workspace | blocked |
| WS-08 | two tasks request same workspace ID/path | uniqueness constraint rejects second |
| WS-09 | worker modifies outside allowed workspace | attempt failed/quarantined and evidence retained |
| WS-10 | cancelled worker leaves background child | cgroup/process-group cleanup removes it before reuse |
| WS-11 | child cannot be removed | quarantine + BLOCKED |
| WS-12 | local clone source/mirror unavailable | typed BLOCKED/RETRY according to cause; no production checkout fallback |

## 6. Capability, connector and secret isolation

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| CP-01 | launched worker effective tools equal policy | execution may proceed |
| CP-02 | inherited Shopify/Gmail/Drive/Omnisend/Resend tools appear unexpectedly | fail closed before substantive work |
| CP-03 | worker attempts controller DB write | denied by OS/API boundary |
| CP-04 | worker attempts systemd/service control | denied |
| CP-05 | worker attempts production credential read | denied and recorded as policy finding |
| CP-06 | task genuinely needs new credential/permission | task BLOCKED; no self-provisioning |
| CP-07 | logs include secret-like fixture | redaction policy prevents secret value from structured telemetry |
| CP-08 | prompt/repo text asks worker to widen permissions | treated as untrusted data; denied |

## 7. Provider/model failure handling

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| PR-01 | provider 429 + Retry-After | bounded backoff honours Retry-After; no busy loop |
| PR-02 | transient 5xx/network failure | retries within configured count/elapsed ceiling |
| PR-03 | provider outage exceeds budget | BLOCKED/ESCALATED with typed reason |
| PR-04 | authentication expired/revoked | BLOCKED; not counted as implementation defect |
| PR-05 | quota exhausted | BLOCKED; no silent weaker-model downgrade |
| PR-06 | required model unavailable | queue/block/escalate according to task risk policy |
| PR-07 | model self-reports different model | measured launcher/process evidence remains authoritative |
| PR-08 | model behaviour/provider version changes | attempt evidence records effective provider/model/version; acceptance remains candidate-specific |

## 8. Candidate and evidence

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| EV-01 | collector observes committed candidate | Candidate record built from measured SHA, not worker prose |
| EV-02 | evidence manifest generated | canonical JSON digest stable for same content |
| EV-03 | raw artifact changed after manifest | digest mismatch; evidence invalid |
| EV-04 | required evidence missing | UNKNOWN / cannot ACCEPT |
| EV-05 | candidate SHA changes after evidence | previous evidence invalidated automatically |
| EV-06 | candidate SHA changes after review | previous review invalidated automatically |
| EV-07 | worker says tests passed but independent CI fails | CI failure blocks acceptance |
| EV-08 | skipped/deselected/timed-out checks present | remain explicit; cannot be silently counted as pass |
| EV-09 | candidate exists but delivery/outbox publication fails | candidate remains discoverable and no rebuild is triggered |
| EV-10 | evidence/result publication succeeds but response is lost | reconcile remote identity before retry; no duplicate authoritative record |

## 9. Review and correction

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| RV-01 | implementer submits own ACCEPT review | independence policy rejects it |
| RV-02 | reviewer patches candidate then accepts same patch | rejected as independent certification; new reviewer required |
| RV-03 | blocking finding unresolved | candidate cannot become ACCEPTED |
| RV-04 | one bounded correction produces new SHA | old review/evidence invalid; fresh review required |
| RV-05 | second substantive rejection | task escalates/re-plans; no infinite patch loop |
| RV-06 | reviewer unavailable | task BLOCKED, not silently relabelled or skipped |
| RV-07 | reviewers disagree | Director investigates evidence; vote count does not override demonstrated defect |

## 10. Integration

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| IN-01 | integrator receives accepted exact SHAs | integration may start |
| IN-02 | branch head moved after acceptance | irrelevant; pinned SHA used |
| IN-03 | one input no longer accepted/current | integration blocked |
| IN-04 | clean non-overlapping merge | fresh integrated evidence still required |
| IN-05 | semantic conflict despite non-overlapping files | integration/replay catches conflict; no acceptance inheritance |
| IN-06 | integrator makes conflict-resolution edit | integrated SHA is new subject requiring relevant review |
| IN-07 | integration changes UX contract | corresponding experience review rerun |
| IN-08 | integration target base changed | stale integration invalid; explicit re-plan/rebase/review required |

## 11. Context and authority freshness

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| CX-01 | product-memory/policy SHA unchanged | progression permitted |
| CX-02 | relevant safety/policy changed during build | progression blocked for re-plan/review |
| CX-03 | irrelevant historical doc changed | deterministic relevance policy decides; no blanket historical injection |
| CX-04 | owner narrows scope mid-run | new task revision; current attempt fenced |
| CX-05 | owner broadens privilege mid-run | structured AuthorityGrant/new revision required |
| CX-06 | prose approval exists without structured grant | kernel does not widen authority |

## 12. Publication ambiguity and Git remote behaviour

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| PB-01 | Git push succeeds, response lost | remote ref/SHA readback reconciles before retry |
| PB-02 | force-push/branch deletion by outside actor | candidate SHA record survives; routing ref drift surfaced |
| PB-03 | worker attempts production push | denied by credential/policy layer |
| PB-04 | remote branch points to unexpected SHA | publication blocked/escalated; no blind overwrite |
| PB-05 | branch name reused for unrelated history | immutable candidate/base SHA ancestry checks prevent confusion |

## 13. Database, disk and recovery

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| DB-01 | clean startup integrity check | controller may reconcile |
| DB-02 | integrity check fails | no dispatch; BLOCKED with restore path |
| DB-03 | migration succeeds | schema version advanced atomically; post-check passes |
| DB-04 | migration interrupted/fails | old DB restored/left valid; no partial scheduling state |
| DB-05 | backup restore | new epoch; stale leases/results rejected |
| DB-06 | disk crosses high-watermark | new task admission stops before ENOSPC |
| DB-07 | evidence storage write fails | candidate cannot reach EVIDENCE_READY |
| DB-08 | safe GC | accepted/reconciliation-required artifacts retained; only eligible disposable data removed |
| DB-09 | newer schema opened by old binary | binary refuses to start writer mode |
| DB-10 | abrupt host reboot | startup reconciliation restores deterministic state before dispatch |

## 14. Drain, upgrade and cutover

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| UP-01 | enter DRAINING | no new assignments; reconciliation continues |
| UP-02 | active attempt during drain | follows explicit finish/cancel policy; no surprise reassignment |
| UP-03 | upgrade with ambiguous remote publication | upgrade blocked until reconciled |
| UP-04 | schema upgrade | backup + integrity + exclusive authority required |
| UP-05 | new binary fails smoke test | scheduling remains stopped; rollback/recovery path invoked |
| UP-06 | old binary incompatible with new schema | downgrade fails closed |
| UP-07 | existing bridge cutover | persist watermark, only one consumer enabled, watcher retained as rollback until parity proven |

## 15. Resource isolation and concurrency

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| RS-01 | V1 initial state | max implementation concurrency = 1 |
| RS-02 | reviewer runs alongside implementation | only if resource/tool/workspace isolation policy permits |
| RS-03 | second implementation enabled before two-task gate | configuration rejected |
| RS-04 | two separable tasks after gate | distinct workspaces/process groups/fences; no shared mutable state |
| RS-05 | host CPU/memory/browser saturation | admission control waits/blocks rather than starving business runtime |
| RS-06 | all provider slots busy | task remains queued; no uncontrolled spawn |

## 16. Observability

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| OB-01 | every state transition | append-only structured event emitted with task/revision/epoch/fence/trace |
| OB-02 | stale result rejected | explicit metric/event with reason |
| OB-03 | provider retry/block | typed reason visible |
| OB-04 | reconciliation after restart | duration/outcome visible |
| OB-05 | secret/PII field presented | excluded/redacted from normal telemetry |
| OB-06 | OTEL exporter unavailable | local correctness/logging continues; warning visible |

## 17. End-to-end gates

### E2E-0 — deterministic kernel, no model

Using fake worker/remote/process adapters:

- create task revision;
- assign attempt;
- simulate candidate/evidence;
- review/accept;
- integration/verify;
- crash controller at each transition boundary;
- repeat duplicate commands;
- inject stale tokens;
- prove deterministic recovery.

No network/model/production access.

### E2E-1 — one isolated model worker

One bounded repository-only task:

- exact base SHA measured;
- narrow effective tool roster proven;
- one workspace;
- candidate collector creates record;
- evidence manifest generated;
- independent review occurs in separate session/workspace;
- no deployment.

### E2E-2 — correction path

Intentionally reject a candidate, perform exactly one bounded correction, verify new SHA invalidates old evidence/review and fresh independent review is required.

### E2E-3 — ambiguous publication

Force remote publication to succeed while the controller observes a timeout. Prove readback prevents duplicate build/publication.

### E2E-4 — two-candidate isolation

Only after E2E-0..3:

- two separable implementation tasks;
- independent workspaces/process groups;
- bounded resource use;
- no shared mutable Git/config;
- exact-SHA integration and fresh verification.

### E2E-5 — experience lane

One meaningful UI/UX task with verified Fable adapter, browser/accessibility evidence, real-device evidence when the task contract requires it, and post-build experience review.

## 18. Freeze gate

Before marking the V1 contract frozen:

- every MUST in `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` has a test ID here or is explicitly a static/documentary invariant;
- the branch-identity mismatch is addressed by a reviewed remediation path;
- canonical truth/roadmap are reconciled;
- traceability has no unexplained V1-relevant row;
- an independent adversarial reviewer is asked specifically to find missing failure modes or authority leaks;
- exact freeze commit SHA is recorded.
