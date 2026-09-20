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
| ST-11 | generate a joint oracle across every task state × attempt/integration state × command | task-side and attempt/integration-side guards must agree for every combined mutation; exactly the intersection of the normative tables is accepted, every unlisted/conflicting edge returns a stable typed error and no partial state/event write |
| ST-12 | reject a candidate, then invoke the one permitted bounded correction | full `REJECTED -> attempt.assign -> ASSIGNED -> attempt STARTING/RUNNING -> BUILDING` path is legal with a fresh attempt/fencing token and retained prior candidate |
| ST-13 | deterministic preflight failure occurs while task is ASSIGNED and attempt is STARTING | no model launch; attempt closes FAILED when cleanup is proven or QUARANTINED otherwise; task reaches BLOCKED through the listed `task.block` edge, never an illegal `ASSIGNED -> FAILED` task transition |

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

## 2B. Identity and binding invariants

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| ID-01 | create execution-bearing task/attempt without repository, task revision, product-memory SHA, base SHA, environment/context digests or scope/policy digest | schema/contract validation rejects record before assignment |
| ID-02 | candidate admission reports branch name but measured HEAD/ancestry differs from bound base/candidate SHA | measured Git identity wins; candidate/launch rejected |
| ID-03 | heartbeat/candidate/evidence/delivery/terminal-result omits or mismatches task revision, controller epoch or fencing token | authoritative mutation rejected |
| ID-04 | review/evidence subject kind or exact subject SHA omitted/mismatched for candidate or integration | record rejected; no acceptance/verification transition |
| ID-05 | ReleaseCandidate points to non-VERIFIED integration or mismatched exact integration SHA/evidence digest | record creation rejected |
| ID-06 | implementation is started against a freeze document branch name rather than the owner-adopted exact frozen SHA | authority validation blocks execution |

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
| WS-13 | measured toolchain/environment fingerprint differs from task-bound environment-manifest digest | BLOCKED before any model starts |
| WS-14 | `doctor`/bootstrap exits 0 while measured tool versions/provenance differ from bound manifest | false green rejected; launch blocked despite exit 0 |
| WS-15 | local mirror exists but exact task base SHA is absent/stale | refresh only from task-approved origin under allowed network policy, then re-measure exact SHA; if still absent, BLOCKED; never fall back to production checkout |

## 5A. Existing bridge identity remediation rehearsal

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| BR-01 | scratch remote reproduces current topology: remote `claude/bridge-builder` absent, local ref at ancestor, accepted SHA available through another remote ref, narrowed fetch refspec names absent branch | documented remediation sequence completes without `fatal: couldn't find remote ref`; no fetch-all dependency |
| BR-02 | remote `claude/bridge-builder` appears at an unexpected SHA after absence check but before create | create-only compare-and-swap/lease fails; procedure stops without overwrite |
| BR-03 | local semantic branch ref has changed from expected old SHA before local reconciliation | expected-old `update-ref`/equivalent fails; no reset/clean/stash or unguarded rewrite occurs |
| BR-04 | guarded remote create and local branch reconciliation succeed in scratch rehearsal | post-create remote readback equals exact accepted SHA; checked-out tree bytes and HEAD remain identical before/after; existing narrowed fetch refspec works after ref recreation |

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
| CP-09 | worker attempts direct read/write of authoritative state DB file | OS/API boundary denies write authority; any permitted diagnostic read is separately controlled and never allows mutation |
| CP-10 | worker shell/network attempts destination not present in task egress allow-list | denied by effective runtime policy; model-provider/kernel publication transport remains separate host capability |

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

## 7A. Idempotency breadth

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| IP-01 | replay each retryable mutation class listed by the contract with same key/request | same authoritative result returned; no duplicate task/attempt/candidate/evidence/review/integration/delivery record |
| IP-02 | replay each class with same key but altered request digest | conflict; no mutation |
| IP-03 | controller restarts after persisting idempotency result but before caller receives response | retry returns persisted result rather than repeating effect |
| IP-04 | transport retry budget exceeded | counters persist across controller restart; operation becomes BLOCKED/ESCALATED and does not silently reset |

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
| EV-09 | candidate commit exists and evidence collection/storage fails before manifest completion | Candidate record remains durable/discoverable with null evidence-manifest digest; it cannot reach EVIDENCE_READY and reconciliation does not re-dispatch the completed build |
| EV-10 | evidence/result publication succeeds but response is lost | reconcile remote identity before retry; no duplicate authoritative record |
| EV-11 | collector is invoked from inside worker process group or with worker write authority over candidate/evidence store | candidate admission rejected; authoritative collector must be kernel-owned and outside worker writable/process boundary |
| EV-12 | candidate exists but delivery/outbox publication fails after evidence completion | Candidate/Evidence records remain discoverable; only Delivery is retried, never rebuild |

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
| RV-08 | task is unclassified or model claims it is low-risk without a deterministic rule | authoritative risk class defaults to MATERIAL; independent review and exact-SHA CI remain required |
| RV-09 | reviewer uses implementer's session, workspace, hidden reasoning context or candidate write authority under a different label/attempt ID | independence check rejects review |
| RV-10 | MATERIAL reviewer uses same model/provider because no verified equal-or-stronger alternative is available | allowed only as a distinct session/workspace with limitation recorded and GPT Director gate still required; never silently represented as stronger diversity |

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
| IN-09 | integrated change intersects unknown/uncomputable verification input closure | full required gate set reruns; unknown closure never permits evidence reuse |
| IN-10 | rejected integration is corrected | correction creates a new immutable integration record/SHA and requires fresh integrated evidence/review; rejected integration record remains historical |

## 11. Context and authority freshness

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| AU-01 | canonical prose/spec/roadmap asserts a sequencing or authority change without an owner-adopted DECISIONS entry bound to exact SHA | kernel authority/gate state does not change; typed AUTHORITY_STALE/BLOCKED finding is emitted |


| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| CX-01 | product-memory/policy SHA unchanged | progression permitted |
| CX-02 | relevant safety/policy changed during build | progression blocked for re-plan/review |
| CX-03 | irrelevant historical doc changed | deterministic relevance policy decides; no blanket historical injection |
| CX-04 | owner narrows scope mid-run | new task revision; current attempt fenced |
| CX-05 | owner broadens privilege mid-run | structured AuthorityGrant/new revision required |
| CX-06 | prose approval exists without structured grant | kernel does not widen authority |
| CX-07 | AuthorityGrant is expired at an authority-bearing transition | treated as no grant; transition blocked |
| CX-08 | AuthorityGrant is revoked while attempt is running | attempt is immediately fenced before any further authoritative result; revocation event persisted |

## 12. Publication ambiguity and Git remote behaviour

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| PB-01 | Git publication times out after send | controller does not blind-push again; reconcile exact remote ref/SHA first |
| PB-02 | remote already contains exact intended SHA/ref | treat as success idempotently |
| PB-03 | remote contains different SHA at expected ref | BLOCKED; no force push |
| PB-04 | branch name matches but commit ancestry wrong | exact SHA/ancestry wins; reject |
| PB-05 | worker attempts force push / protected branch write | denied by capability policy |
| PB-06 | worker attempt has a usable remote push credential or can directly publish its candidate | preflight/policy rejects launch; candidate publication authority belongs only to the kernel publication adapter |
| PB-07 | publication adapter creates candidate ref, response is lost, retry observes the same create-only ref at exact candidate SHA | reconcile as success; never create a second authoritative Candidate or force-update the ref |

## 13. Database durability and recovery

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| DB-01 | abrupt controller kill during WAL activity | integrity check passes or controller blocks for recovery; no silent scheduling |
| DB-02 | DB corruption detected | DRAINING/BLOCKED; restore procedure required |
| DB-03 | restore backup | epoch increment + stale lease invalidation + full reconciliation before dispatch |
| DB-04 | schema migration fails | rollback/restore known-good schema; no worker launch on half-migrated DB |
| DB-05 | disk reaches admission high-watermark | new attempts blocked; evidence not deleted blindly |
| DB-06 | disk exhaustion during evidence import | atomic temp write not registered; task BLOCKED/retryable after space recovery |
| DB-07 | controller dies after `candidate.register` but before evidence manifest completion | restart finds durable Candidate with null evidence digest; task remains BUILDING until evidence is completed or explicitly blocked; build is not re-dispatched |
| DB-08 | backup job writes to same active DB path/filesystem object | rejected as not an independent backup destination |
| DB-09 | restore rehearsal from latest declared backup | recovered DB passes integrity check; controller increments epoch and reconciles before dispatch |
| DB-10 | backup is older than declared RPO | health/admission gate reports degraded/BLOCKED according to policy; no false backup-health green |
| DB-11 | primary SQLite path becomes unreadable/corrupt while controller is live | controller drains/blocks scheduling, preserves diagnostics and requires restore/reconciliation; it does not create a fresh empty authority store |
| DB-12 | restore onto a replacement host/process from the declared independent backup destination | recovered store passes integrity/migration checks, new controller epoch invalidates all prior leases/tokens, and no dispatch occurs until remote/workspace/process reconciliation completes |

## 14. Cancellation and orphan process races

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| CXN-01 | cancel while worker running | fence token invalid immediately; process tree terminated |
| CXN-02 | result arrives after cancel | rejected as stale |
| CXN-03 | cancellation signal lost | reconciliation observes process; retries termination; no reassignment until resolved |
| CXN-04 | process dies but grandchild survives | ownership scan catches child; quarantine if cleanup incomplete |
| CXN-05 | reviewer cancelled | no partial verdict becomes authoritative |

## 15. Integration and Director release gate

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| DG-01 | integration verified but Director has not accepted | no ReleaseCandidate record |
| DG-02 | Director accepts exact integrated SHA/evidence | ReleaseCandidate record created |
| DG-03 | later candidate accepted after RC | existing RC immutable; new integration/RC required |
| DG-04 | model attempts deployment from RC | denied; deployment controller outside V1 |

## 16. Drain, upgrade and cutover

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| UP-01 | controller enters DRAINING | no new attempts; active attempts reconcile/finish per policy |
| UP-02 | cutover watermark set | results from pre-watermark attempts obey explicit admission rule; no ambiguous mixed epochs |
| UP-03 | controller binary/schema upgrade | backup + migration + new epoch + reconcile before RUNNING |
| UP-04 | rollback controller version | schema compatibility checked; if unsafe, remain DRAINING/BLOCKED |
| UP-05 | bridge cutover begins with pending inbox | intake frozen at watermark; exactly one system owns post-watermark tasks |
| UP-06 | bridge fallback requested | Orchestrator drained first; old bridge re-enabled only after ownership proof |

## 17. Acceptance proof for first V1 slice

Minimum proof before moving beyond model-free Phase 0:

1. all schema/state/property tests green;
2. fault-injection suite green for controller kill, stale lease, ambiguous publication, DB restore, disk pressure and orphan process;
3. workspace isolation suite green;
4. effective capability roster test green;
5. one synthetic task reaches ACCEPTED with exact evidence;
6. one synthetic accepted task reaches VERIFIED integration;
7. Director marks a ReleaseCandidate;
8. no production deployment occurs.

## 18. Freeze gate

Before marking the V1 contract frozen:

- the owner has explicitly adopted the exact freeze candidate SHA in `DECISIONS.md`; any DEC-046 sequencing amendment is stated there rather than inferred from this spec;
- every MUST in `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` and `ORCHESTRATOR_V1_STATE_API.md` has a test ID here or is explicitly a static/documentary invariant;
- the branch-identity mismatch has an independently reviewed remediation path; `WATCHER_BUILDER_IDENTITY_REMEDIATION.md` is the current candidate plan, and live closure is mandatory before Phase 1/model-worker execution;
- canonical truth/roadmap are reconciled without self-authorising an owner gate;
- a mechanical doc-consistency check scans `CURRENT_TRUTH.md` and `ROADMAP.md` for every CG/finding identifier the freeze set marks resolved/addressed and fails if either file asserts a conflicting current status;
- that same mechanical gate maintains an explicit required set of live unremediated runtime conditions on which the freeze/remediation plan depends and fails if any required condition is absent from `CURRENT_TRUTH.md`; the initial set is (a) watcher/builder branch mismatch, (b) inherited business MCP connector surface, and (c) the Builder `remote.origin.fetch` refspec naming the absent `claude/bridge-builder` ref;
- traceability has no unexplained V1-relevant row;
- a fresh independent adversarial reviewer bound to the exact candidate SHA finds no material missing failure mode, authority leak or contradiction;
- the accepted freeze SHA is then recorded in a separate follow-up canonical product-memory commit.
