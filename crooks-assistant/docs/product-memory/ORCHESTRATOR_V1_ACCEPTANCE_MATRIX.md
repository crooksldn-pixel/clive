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
| ST-11 | generate a joint oracle across every task/integration subject state × attempt state × command | subject-state and attempt-state guards must agree for every combined mutation. The legal integration launch sequence is exact: `integration.begin` admits `(integration CREATED, attempt none) -> (INTEGRATING, CREATED)`; `integration.start` admits attempt `CREATED -> STARTING` while subject remains INTEGRATING, then `STARTING -> RUNNING` on successful preflight; every conflicting/unlisted combination rejects with no partial state/event write |
| ST-12 | reject a candidate, then invoke the one permitted bounded correction | full `REJECTED -> attempt.assign -> ASSIGNED -> attempt STARTING/RUNNING -> BUILDING` path is legal with a fresh attempt/fencing token and retained prior candidate |
| ST-13 | deterministic preflight failure occurs while task is ASSIGNED and attempt is STARTING | no model launch; attempt closes FAILED when cleanup is proven or QUARANTINED otherwise; task reaches BLOCKED through the listed `task.block` edge, never an illegal `ASSIGNED -> FAILED` task transition |
| ST-14 | drive three attempts on one task revision through failure/block/re-plan paths, then request a fourth `attempt.assign` | the fourth assignment is refused by the transition guard because the per-revision attempt ceiling is exhausted; the persisted counter survives controller restart, DB restore and epoch change; when the third attempt is a non-rejection failure the task follows `BLOCKED -> task.escalate -> ESCALATED` and no further assignment is admissible |
| ST-15 | controller epoch changes while a TASK is `ASSIGNED` and its only attempt is `CREATED` or `STARTING` | the attempt closes `FENCED` (or `QUARANTINED` when a `STARTING` preflight process group cannot be proven stopped) and the task does not stay silently in `ASSIGNED`: §21 reconciliation identifies `ASSIGNED` as an execution-bearing state holding no non-terminal execution record and surfaces the task BLOCKED through the listed `task.block` edge with typed reason `EXECUTION_RECORD_MISSING`. No blind redispatch occurs, and the same holds for `BUILDING`/`REVIEWING` and for an `INTEGRATION` subject in `INTEGRATING`/`REVIEWING` through `integration.block` |
| ST-16 | restart the controller repeatedly while a TASK sits in `ASSIGNED` with a `CREATED` attempt, so each restart fences that attempt before any model runs; then repeat with the attempt in `STARTING` having forked a live preflight process group, killing the controller mid-preflight | each fencing closes the attempt `FENCED` having never reached `RUNNING`, so none of them consumes the per-revision execution-attempt ceiling; after three such restart-fencings a legitimate `attempt.assign` is still admissible, and the three real execution attempts remain available. Attempts that did reach `RUNNING`, and attempts closed `FAILED`/`QUARANTINED` by deterministic preflight failure, still consume the ceiling. **Crash-during-STARTING arm:** the restarted controller identifies the orphaned preflight process group from the durable `lease.owned_process_group_handle` written before the fork, stops it through the §6 TERM/grace/KILL sequence, verifies emptiness and closes the attempt `FENCED`; `attempt.running_process_group_identity` is NULL, so the ceiling is unchanged and the task's three real attempts survive. A NULL handle is proved to mean no group was ever created and also yields `FENCED`, never `QUARANTINED`; `QUARANTINED` is produced only by injecting a preflight group named by a non-NULL handle that cannot be proven stopped. The two fields are asserted to be distinct: the handle is non-NULL while `running_process_group_identity` is still NULL throughout `STARTING`. **Surviving-preflight-child arm:** fork a preflight child that deliberately outlives preflight, then let the attempt commit `STARTING -> RUNNING` and launch the model. Assert that `lease.owned_process_group_handle` holds exactly the value it held in `STARTING` — the `RUNNING` commit neither updated nor replaced it, and `attempt.running_process_group_identity` did not become the cleanup handle — and that the model process joined that same owned group rather than a second one. Then cancel or restart-fence the attempt and assert that §6 finds the surviving preflight child through that one write-once handle, that emptiness is proved over the whole group rather than over a model-only group, and that workspace reuse stays forbidden until the entire group is empty; with the child held alive the attempt closes `QUARANTINED` with the workspace unreused, and only once it exits does cleanup prove and the workspace become reusable. A specification that hands the handle over at `STARTING -> RUNNING` fails this arm, because the surviving child is then in a group no durable field names. The ceiling accounting of the arms above is unchanged, so R-02's attempt-budget semantics are preserved |
| ST-17 | drive a candidate to `REVIEWING` with **two or more** live `DISPATCHED` reviewers on distinct required-review slots, then fire each of `candidate.reject`, `task.block`, `task.escalate` in turn; separately drive an integration to `REVIEWING` with two live dispatches and fire `integration.reject` and `integration.block`; separately drive a TASK to `BUILDING` with a `RUNNING` attempt and fire `task.fail` and `task.escalate` | in every arm the subject transition commits only after every non-terminal execution record it owned is terminal: each remaining `review_dispatch` is `FENCED` (never left `DISPATCHED`) and each non-terminal `attempt` is `CLOSED` with a terminal disposition, and each owned process group has been stopped and proved empty through §6 **before** the commit. A verdict submitted afterwards by a fenced reviewer is rejected with `FENCE_STALE` even though the subject SHA never changed. No `DISPATCHED` row and no non-terminal attempt exists under any subject state outside the mechanically derived execution-bearing set. The freed required-review slots and reviewer-concurrency units are immediately reusable — a fresh dispatch for the same slot on a different subject succeeds at once — and no lease or execution slot remains occupied by the terminal subject. Where an owned group cannot be proven stopped, the arm instead yields `QUARANTINED`/BLOCKED rather than a silently clean transition. **Kernel-owned reviewer crash arm:** dispatch a reviewer whose principal carries execution-ownership kind `KERNEL_OWNED`, kill the controller in the window after its durable process-group handle is committed and around reviewer process creation — both before the fork and after it — then restart and fire `candidate.reject`. Assert the restarted controller classifies the dispatch as kernel-owned from the durable reviewer principal kind, **not** from the NULL-or-not state of its process-group identity; that where a reviewer process exists it is stopped and proved empty before `REJECTED` commits, and where cleanup cannot be proven the dispatch is `FENCED` and the subject is BLOCKED instead of `REJECTED`. Assert that across the whole window the required-review slot and the §19 reviewer-concurrency unit are **not** released and no replacement dispatch is admitted while a kernel-owned orphan can still exist. **External-principal negative arm:** repeat with a reviewer principal of kind `EXTERNAL`; assert no signal is sent, cancellation is fencing-only, the recorded limitation is present, and this fencing-only path is reachable *only* through the external principal kind — a kernel-owned dispatch with a NULL handle must not fall into it. A specification that reads external-vs-kernel-owned from a NULL process-group identity fails both arms |

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
| ID-03 | heartbeat, candidate admission, integration-result admission, evidence admission, **review-result admission** or terminal execution result omits or mismatches the subject revision, controller epoch or current fencing token of the execution record it acts under | authoritative execution mutation is rejected with `FENCE_STALE`; coverage is enumerated over all three execution record kinds of `ORCHESTRATOR_V1_STATE_API.md` §1A |
| ID-04 | review/evidence subject kind or exact subject SHA omitted/mismatched for candidate or integration | record rejected; no acceptance/verification transition |
| ID-05 | ReleaseCandidate points to non-VERIFIED integration or mismatched exact integration SHA/evidence digest | record creation rejected |
| ID-06 | implementation is started against a freeze document branch name rather than the owner-adopted exact frozen SHA | authority validation blocks execution |
| ID-07 | delivery update presents a stale controller epoch, an unknown idempotency key, or the same idempotency key with a conflicting canonical request digest | authoritative delivery mutation is refused; delivery uses controller-epoch + idempotency/request-digest authority and the §4 two-phase observe/persist protocol, not an execution-record fencing token |

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

## 5B. Clean reconstruction claims

Covers the MUST-bearing requirements of `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §22A. These are the acceptance cases cited by CG-05 in §24 of the freeze contract and in the traceability matrix; before this section existed, §22A had no test coverage at all.

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| EN-01 | reconstruct the declared environment on a fresh disposable host with no pre-existing target toolchain state | reconstruction completes from pinned immutable artifact identities and the resulting environment fingerprint equals the declared environment-manifest digest; a rerun on the already-provisioned Builder is explicitly rejected as reconstruction evidence rather than counted as a pass |
| EN-02 | reconstruction attempts a download/egress destination that is absent from the approved allow-list | denied by effective runtime policy and the reconstruction is BLOCKED with a typed reason; the destination is never silently skipped, and a partially reconstructed environment is never reported as reconstructed |
| EN-03 | a pinned asset's digest mismatches at pre-extraction verification, and separately a post-install version/provenance check disagrees with the pinned identity | reconstruction fails closed in both cases independently; an exit status of zero from a bootstrap/doctor script does not override either failure (the §22A pairing of `WS-13`/`WS-14` at reconstruction time) |
| EN-04 | pre-existing local tooling on the host could have satisfied the reconstruction check | the test proves by negative control that it did not — the declared toolchain is absent before reconstruction and its absence is measured, not assumed; without that proof the reconstruction claim is rejected |

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
| PR-09 | enumerate every reason code in `ORCHESTRATOR_V1_STATE_API.md` §7 and resolve each to a top-level class | every code resolves to exactly one of RETRYABLE/BLOCKED/REJECTED_FAILED/ESCALATED; no code is unmapped and none maps twice; an unknown or implementation-added code with no resolvable mapping resolves to BLOCKED and never to RETRYABLE. The test fails if any code is unmapped rather than defaulting silently |
| PR-10 | exercise non-rejection attempt failures across controller restart/DB restore until the per-revision ceiling is reached, and separately enumerate every terminal attempt disposition against the ceiling | automatic relaunch count remains zero; persisted attempt count never resets; the third attempt may finish only through the declared BLOCKED path and then deterministic `task.escalate` to ESCALATED; a fourth `attempt.assign` is rejected by the transition precondition with a stable typed error. The disposition enumeration asserts *exactly* which rows consume the ceiling per `ORCHESTRATOR_V1_STATE_API.md` §3A.2 — non-terminal, `SUCCEEDED`, `FAILED`, `QUARANTINED`, and `CANCELLED`/`FENCED` that reached `RUNNING`, consume; `CANCELLED`/`FENCED` that never reached `RUNNING` do not — and that this classification is total over the disposition enum. Persistence is proved across controller restart, DB restore and controller-epoch change in both directions: a consumed attempt is never decremented or reclassified, and a non-consuming fencing never becomes consuming |

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
| RV-11 | a review dispatch is cancelled or expires and is replaced, then the original reviewer submits `ACCEPT` for the **identical unchanged** candidate SHA | the verdict is rejected as stale on the dispatch fencing token with reason `FENCE_STALE`; no Review row is written; `candidate.accept` never observes it; the rejection is recorded as a `transition_event`. Candidate-mutation invalidation is not what catches this, because the SHA did not change |
| RV-12 | the controller is killed while a review is in flight, then restarted | restart reconciles the review dispatch at the §21 review-reconciliation step **before** dispatch is enabled, terminates the orphaned reviewer process group the kernel owns, and then either creates exactly one replacement dispatch under a new fencing token or blocks the subject — never both, never a duplicate paid review, and never a silent indefinite `REVIEWING` |
| RV-13 | `task.cancel` (and separately `integration.cancel`) arrives while a review is in flight | every non-terminal dispatch for that subject is fenced immediately; any later verdict is rejected; no partial verdict becomes authoritative. This makes `CXN-05` mechanically testable rather than aspirational |
| RV-14 | a verdict is presented with no dispatch identity, an unknown dispatch identity, a dispatch belonging to a different subject, or a reviewer principal that differs from the one bound to the named dispatch | rejected in every case with no Review row written; a verdict can only be admitted under its own live dispatch |

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
| IN-11 | `integration.cancel` while an integrator process is running | the integration attempt's lease/fence is invalidated immediately, the process group receives TERM/grace/KILL, and emptiness is verified before any workspace reuse. If the process cannot be proven stopped the integration attempt closes QUARANTINED, the workspace is not reused and the integration goes BLOCKED rather than CANCELLED — mirroring `WS-10`/`WS-11`/`LS-06` on the integration subject |
| IN-12 | controller restart with an integration in `INTEGRATING` | the §21 integration-reconciliation step observes integrator process and workspace state before dispatch is enabled; there is never a blind re-dispatch and never a silent indefinite `INTEGRATING`; an integration in `INTEGRATING` with no non-terminal integration attempt is surfaced as BLOCKED |
| IN-13 | an integrated review records a blocking finding against the integration subject | `integration.verify` is refused while that finding is `OPEN`/`BLOCKED`; the finding is queryable by `(subject kind = INTEGRATION, subject ID)`; a correction integration created under `parent_integration_id` inherits the unresolved finding and cannot reach `VERIFIED` until it is `RESOLVED` or `OBSOLETE` with a recorded reason — the integration analogue of `ST-09` |
| IN-14 | a stale integration result is presented under a superseded or terminal integration attempt | rejected with `FENCE_STALE`; the integration state is unchanged by the rejected admission |
| IN-15 | launch an integration through the exact allocation/preflight triples | `integration.begin` is legal only from `(integration CREATED, attempt none)` and leaves `(INTEGRATING, CREATED)` with workspace/lease allocated; `integration.start` is legal from `(INTEGRATING, CREATED)` to attempt STARTING and from `(INTEGRATING, STARTING)` to attempt RUNNING on successful measured preflight; no §3 row claims an attempt-state edge that §3A does not own |
| IN-16 | integrator preflight fails deterministically after `integration.begin` allocated the attempt/workspace | no integrator process reaches RUNNING; the STARTING attempt closes FAILED if cleanup is proven or QUARANTINED otherwise, and the integration reaches BLOCKED through `integration.block`; no unfenceable or unregistered preflight window exists |
| IN-17 | cancel an integration while it is still subject-state CREATED, before `integration.begin` | cancellation is a direct subject transition with no fictitious attempt/lease/process; once allocation has occurred, cancellation is governed by the real attempt/lease edges in §3A |
| IN-18 | cancel/fence an allocated integration attempt while its attempt state is CREATED or STARTING, including controller-epoch change during that window | authority is fenced immediately; CREATED closes CANCELLED/FENCED with cleanup proven by construction; STARTING closes CANCELLED/FENCED only after preflight process cleanup is proven, otherwise QUARANTINED and subject BLOCKED; no live lease/attempt remains stranded |

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


## 12A. Delivery state machine

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| DL-01 | create a delivery publication intent | `delivery.publish` creates/reuses PENDING only after idempotency key/request digest and expected remote identity are persisted before the external effect |
| DL-02 | exact expected remote identity is observed after publication | PENDING -> PUBLISHED with observed identity persisted and a DELIVERY transition event |
| DL-03 | publication response is ambiguous after the external effect | PENDING -> UNKNOWN; blind replay is forbidden until `delivery.reconcile` observes authoritative remote truth |
| DL-04 | reconcile UNKNOWN delivery | authoritative remote truth moves UNKNOWN to PUBLISHED when exact identity exists, or FAILED when the intended effect definitively did not occur and no safe retry remains |
| DL-05 | block a PENDING/UNKNOWN/FAILED delivery on deterministic policy/authority/conflict | `delivery.block` moves it to BLOCKED with typed persisted reason; PUBLISHED and BLOCKED are terminal for that delivery record |
| DL-06 | kill the controller after `delivery.publish` has initiated the external publication effect but before any outcome is persisted | the `attempt count` increment was committed before the effect, so restart finds PENDING with a non-zero count and §21 step 10 reconciles it to UNKNOWN before any further external effect; a subsequent `delivery.publish` is refused with `REMOTE_EFFECT_UNKNOWN` pending `delivery.reconcile`; exactly one external effect ever occurs, and the destination is reached at most once. Repeat with the crash placed *before* the increment commits: the record is PENDING with `attempt count = 0`, no effect was initiated, and publish remains admissible |

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
| CXN-05 | reviewer cancelled | no partial verdict becomes authoritative; enforced by fencing the reviewer's `review_dispatch` rather than by a lease it never held, and mechanised by RV-13 |

## 14A. Observability contract

Covers the MUST-bearing requirements of `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §18. Added because the strengthened §18 meta-gate below surfaces MUST sections with no test ID rather than tolerating them.

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| OB-01 | emit every task/integration/review-dispatch and **§3C delivery** transition and inspect the resulting journal events | each event carries the complete §18 minimum field set and a representable subject kind; delivery transitions DL-01..DL-05 emit `DELIVERY` events with controller epoch and delivery/idempotency identity and may have NULL execution-record fencing token; no authoritative transition commits without its journal event |
| OB-04 | present a heartbeat, candidate, integration result and review verdict under a superseded or terminal execution record | each admission is refused and each refusal appends a journal event naming the stale execution identity and `FENCE_STALE`; the `stale-result rejections` metric is derivable from those events, so a fenced reviewer or integrator is never silently invisible |
| OB-02 | enumerate the mandatory operational metrics listed in §18 | every listed metric is exposed by the running controller; a missing metric fails the health/readiness gate rather than being silently absent |
| OB-03 | telemetry, logs and journal payloads are generated for a task carrying secret-like and PII-like fixtures | no secret value, raw credential, customer PII or full prompt is emitted by default; composes with `CP-07` on the worker side and covers the controller/journal side |

## 14B. Resource and storage ceilings

Covers the MUST-bearing requirements of `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §19.

| ID | Scenario | Expected invariant / result |
| --- | --- | --- |
| RS-01 | enumerate every ceiling §19 requires — implementation concurrency, reviewer concurrency, per-provider concurrency, per-attempt CPU/memory/process, browser slots, evidence/workspace disk high-watermark — and drive each to its limit | admission is refused at the ceiling rather than exceeded; each ceiling is measured against durable records (non-terminal `attempt` rows per subject kind, non-terminal `review_dispatch` rows) rather than an in-memory counter, so it survives controller restart |
| RS-02 | reviewer-concurrency and browser-slot ceilings are reached while further eligible work exists | the work queues rather than exceeding the ceiling, no retry/correction budget is consumed, and no ceiling is silently widened; composes with `API-07` |

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
- **every test ID referenced anywhere in the freeze set resolves to an actual row of this matrix.** A normative document MUST NOT certify a requirement, close a contract gap or cite coverage using a test ID that does not exist here. This check exists because status-agreement scanning alone cannot detect a resolution claim that cites a phantom test set, which is how CG-05 came to be certified by a non-existent `EN` family;
- **the MUST-coverage index in §18A is complete and accurate.** Every section of `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` and `ORCHESTRATOR_V1_STATE_API.md` that contains a MUST or MUST NOT appears in that index exactly once, and each entry names either at least one existing test ID, or `STATIC` with a matching entry in `ORCHESTRATOR_V1_STATE_API.md` §10, or `DEFERRED` with an explicit recorded reason. The mechanical gate recomputes the MUST-bearing section set from the documents themselves and **fails on any section it finds that the index does not disposition** — it reports the gap rather than papering over it, and a MUST that is neither tested nor explicitly static nor explicitly deferred is a freeze blocker;
- the normative failure reason-code table in `ORCHESTRATOR_V1_STATE_API.md` §7 is a total mapping — every code resolves to exactly one top-level class, no code is listed twice, and the fail-closed default for unmapped codes is BLOCKED rather than RETRYABLE (mechanised by `PR-09`);
- that same mechanical gate maintains an explicit required set of live unremediated runtime conditions on which the freeze/remediation plan depends and fails if any required condition is absent from `CURRENT_TRUTH.md`; the initial set is (a) watcher/builder branch mismatch, (b) inherited business MCP connector surface, and (c) the Builder `remote.origin.fetch` refspec naming the absent `claude/bridge-builder` ref;
- **no subject transition may strand an execution record.** The mechanical gate recomputes, from the `ORCHESTRATOR_V1_STATE_API.md` §3 matrix and the §3A.1/§3B derivation of the execution-bearing set, exactly which §3 rows carry a subject out of that set, and fails unless each one carries the §3.1 `[EXEC-FENCE]` or `[EXEC-ATOMIC-CLOSE]` obligation **and** each such command appears as a trigger on the corresponding terminal §3A/§3B edge. The check is driven by the derived rows rather than by the tokens present, so a matrix carrying no tokens fails rather than passing vacuously;
- **the pre-RUNNING process-group cleanup handle and the execution-ceiling discriminator are separate named facts.** The gate asserts `ORCHESTRATOR_V1_STATE_API.md` §3A.3 declares exactly two durable fields with distinct roles, distinct population times and one reader each, and that §1A, §3A, §3A.2 and §6 each name the one whose role they need;
- traceability has no unexplained V1-relevant row;
- a fresh independent adversarial reviewer bound to the exact candidate SHA finds no material missing failure mode, authority leak or contradiction;
- the accepted freeze SHA is then recorded in a separate follow-up canonical product-memory commit.

## 18A. MUST-coverage index

Every section of the two normative documents that contains a MUST or MUST NOT appears here exactly once. `FC` is `ORCHESTRATOR_V1_FREEZE_CONTRACT.md`; `SA` is `ORCHESTRATOR_V1_STATE_API.md`. Coverage is one of: a list of test IDs that exist in this matrix, `STATIC` for a documentary invariant listed in `SA` §10, or `DEFERRED` with an explicit reason.

The §18 mechanical gate recomputes the MUST-bearing section set from the documents and fails on any section missing from this table, so a new MUST cannot be added to the freeze set without receiving a disposition here.

| Doc | Section | Coverage |
| --- | --- | --- |
| FC | §1 | STATIC — V1 objective and the models-never-mutate-authority rule; enforced structurally by CP-03, CP-09, DG-04 |
| FC | §3 | STATIC — authority table; per-principal enforcement is tested by RV-01, RV-02, RV-09, CP-03, CP-05, EV-11, DG-01, DG-04 |
| FC | §4 | ID-01, ID-02, ID-03, ID-04, ID-05, ID-06, WS-02, WS-03, EV-01 |
| FC | §5.3 | ST-09, RV-03, IN-13 |
| FC | §6 | DB-01, DB-02, DB-03, DB-04, DB-08, DB-09, DB-10, DB-11, DB-12 |
| FC | §7 | CT-01, CT-02, CT-03, CT-04, CT-05, CT-06, ID-03, ID-07, LS-03, LS-04, RV-11, RV-14, IN-14, OB-01, DL-01, DL-02, DL-03, DL-04, DL-05, DL-06 |
| FC | §8 | LS-01, LS-02, LS-03, LS-05, LS-06, LS-07, LS-08, RV-12, RV-13, ST-16 |
| FC | §9 | IP-01, IP-02, IP-03, IP-04, API-02, API-03, API-08, EV-10, PB-01, PB-02, PB-07, DL-06 |
| FC | §10.1 | PR-03, PR-04, PR-05, PR-09, ST-08, WS-04, WS-13, DB-05 |
| FC | §10.3.1 | PR-09, PR-10, ST-08, ST-14, ST-16, IP-04 |
| FC | §11 | WS-01, WS-04, WS-05, WS-06, WS-07, WS-08, WS-09, WS-10, WS-11, WS-13, WS-14, CXN-01, CXN-04, IN-11 |
| FC | §12 | CP-01, CP-02, CP-03, CP-04, CP-05, CP-06, CP-07, CP-08, CP-09, CP-10, PB-05, PB-06 |
| FC | §13 | CX-05, CX-06, CX-07, CX-08, AU-01 |
| FC | §14.5 | PB-03, PB-04, PB-05, PB-06, PB-07 |
| FC | §15 | RV-01, RV-02, RV-03, RV-04, RV-05, RV-06, RV-07, RV-08, RV-09, RV-10, RV-11, RV-12, RV-13, RV-14, ST-17 |
| FC | §16 | IN-01, IN-02, IN-03, IN-04, IN-05, IN-06, IN-07, IN-08, IN-09, IN-10, IN-11, IN-12, IN-13, IN-14, IN-15, IN-16, IN-17, IN-18, ST-17 |
| FC | §18 | OB-01, OB-02, OB-03, OB-04 |
| FC | §19 | RS-01, RS-02, DB-05, API-07 |
| FC | §20 | UP-01, UP-02, UP-03, UP-04, UP-05, UP-06, DB-04 |
| FC | §21 | LS-07, CT-03, IN-12, RV-12, DB-07, EV-09, API-08, ST-15, ST-16, ST-17, DL-06 |
| FC | §22 | EV-07, EV-08, ID-06, RV-08 |
| FC | §22A | EN-01, EN-02, EN-03, EN-04 |
| FC | §23 | STATIC — reuse boundary; the MUST NOT is "do not import the ECC plugin/runtime graph", a repository-composition invariant with no runtime transition |
| FC | §27 | STATIC — freeze acceptance is an owner/process gate, not a kernel transition; the anti-self-adoption half is tested by AU-01 and ID-06 |
| SA | §1A | ID-03, LS-01, LS-03, LS-04, RV-11, RV-12, RV-13, RV-14, IN-11, IN-12, IN-14, CXN-05, ST-15, ST-16, ST-17 |
| SA | §3.1 | ST-17, ST-15, ST-12, RV-12, RV-13, IN-11, IN-17, WS-10 |
| SA | §3A | ST-11, ST-12, ST-13, ST-14, ST-15, ST-16, ST-17, API-01, PR-10, IN-11, IN-12, IN-15, IN-16, IN-18 |
| SA | §3A.1 | ST-15, IN-12, IN-18, RV-12 |
| SA | §3A.2 | ST-14, ST-16, PR-10, ST-08 |
| SA | §3A.3 | ST-16, ST-17, ST-13, ST-15, IN-18, WS-10, WS-11 |
| SA | §3B | RV-11, RV-12, RV-13, RV-14, ST-15, ST-17 |
| SA | §3C | DL-01, DL-02, DL-03, DL-04, DL-05, DL-06, API-08, PB-01, PB-07 |
| SA | §4 | ST-03, ST-04, ST-05, API-09, DB-01 |
| SA | §5 | API-06, API-07, RS-02 |
| SA | §6 | WS-10, WS-11, LS-06, IN-11, RV-12, ST-16, ST-17 |
| SA | §5A | WS-12, WS-15, PB-06, CP-10 |
| SA | §5B | WS-13, WS-14, EN-01, EN-03 |
| SA | §7 | PR-09, PR-10, ST-15, DL-06 |
| SA | §8 | API-09, EV-02, EV-03, DB-06 |
