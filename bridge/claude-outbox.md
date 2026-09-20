# CLAUDE OUTBOX

**Round:** Fresh independent adversarial re-review — Orchestrator V1 freeze candidate after N-04 repair
**Timestamp:** 2026-09-20 (UTC), unattended bridge round
**Inbox blob SHA processed:** `63f7bcf18fd4b4d99467bd01ecbab511e76b9a2c`
**Worker:** headless Claude (`claude-opus-5`, effort `high`) in builder clone `/opt/crooks-builder`
**Mode:** READ-ONLY architecture/specification review. No implementation. No findings fixed.

I have consumed `/opt/crooks-ai-bridge/bridge/chatgpt-inbox.md` at the blob SHA above and executed only its
instructions. All prior verdicts were treated as stale for this changed tree and none was carried forward.

---

## VERDICT

**CHANGES REQUIRED BEFORE OWNER DECISION**

The N-01..N-04 repairs are correct and I could not break them. The candidate fails on five material
engineering defects that are new to this review and independent of the N-series: four of them concentrate in
the parts of the control plane that execute **reviewers and integrators**, which — unlike implementation
attempts — have no durable execution record, no fencing and no reconciliation path; the fifth is a freeze-gate
violation where the contract certifies a resolved contract gap using acceptance cases that do not exist.

This verdict is bound to candidate SHA `2bf240c33bfbf0e66257b82a43013cfb3f5af958` only.

---

## 1. What was asked

Perform a fresh, independent, read-only adversarial architecture/specification re-review of the Orchestrator
V1 freeze candidate after the N-04 repair. Verify exact candidate/base/merge-base/diff first; read the full V1
freeze set; re-check N-01..N-04 with particular attention to the N-04 repair across `CURRENT_TRUTH.md`,
`ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md` §18 and `ORCHESTRATOR_V1_TRACEABILITY.md`; confirm no repair
self-adopts the freeze, changes DEC-046/DEC-047 authority, executes runtime remediation or implies Phase 1
write-capable model-worker authority; then adversarially search for any new material engineering defect.
Return exactly one of two verdicts. Treat owner adoption and the live runtime conditions as OWNER-PENDING /
RUNTIME-PENDING rather than engineering defects.

---

## 2. Identity verification (performed first, before reading any content)

| Item | Declared in inbox | Measured | Match |
| --- | --- | --- | --- |
| Repository | `crooksldn-pixel/clive` | `https://github.com/crooksldn-pixel/clive.git` | yes |
| Candidate branch | `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` | fetched explicitly | yes |
| Candidate SHA | `2bf240c33bfbf0e66257b82a43013cfb3f5af958` | `2bf240c33bfbf0e66257b82a43013cfb3f5af958` | **exact** |
| Base | `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327` | `9e59860a945ec339c69af8709cd0721f0a795327` | **exact** |
| Merge-base | (implied) | `9e59860a945ec339c69af8709cd0721f0a795327` | **equals base** |

The base **is** the merge-base, so the candidate is a clean linear descendant of the canonical parent with no
divergence. 33 commits, documentation only.

```
 crooks-assistant/docs/product-memory/CURRENT_TRUTH.md                        |  26 +-
 crooks-assistant/docs/product-memory/ENGINEERING_ORCHESTRATOR_V1.md          |   4 +-
 crooks-assistant/docs/product-memory/ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md    | 299 +++++
 crooks-assistant/docs/product-memory/ORCHESTRATOR_V1_FREEZE_CONTRACT.md      | 714 +++++++++
 crooks-assistant/docs/product-memory/ORCHESTRATOR_V1_STATE_API.md            | 438 +++++++
 crooks-assistant/docs/product-memory/ORCHESTRATOR_V1_TRACEABILITY.md         | 107 +++
 crooks-assistant/docs/product-memory/ROADMAP.md                              |  14 +-
 crooks-assistant/docs/product-memory/WATCHER_BUILDER_IDENTITY_REMEDIATION.md | 128 ++++
 8 files changed, 1710 insertions(+), 20 deletions(-)
```

No executable code, test, dependency, config, service unit or harness file is touched. `DECISIONS.md` is
**not modified** (verified: zero diff lines), which is the structural proof that the candidate does not
self-adopt the freeze and does not alter DEC-046/DEC-047 authority.

---

## 3. N-01 … N-04 re-check

### N-04 (the repair under particular scrutiny) — CORRECTLY REPAIRED, all three conditions met

**(a) `CURRENT_TRUTH.md` retains the live Builder refspec condition.** The restored sentence reads, in full:

> The Builder clone's `remote.origin.fetch` refspec still names the deleted remote `claude/bridge-builder`,
> so `git fetch --all` fails there; use explicit branch fetches. Do not repair the refspec ad hoc — its
> current form is a precondition of the `WATCHER_BUILDER_IDENTITY_REMEDIATION.md` rehearsal (BR-01/BR-04)
> and it becomes valid again only when that ref is recreated.

All three required elements are present: the refspec condition, the `git fetch --all` failure, and the
no-ad-hoc-repair instruction explicitly tied to BR-01/BR-04.

**(b) `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md` §18 makes persistence a mechanical freeze gate.** The added
bullet:

> that same mechanical gate maintains an explicit required set of live unremediated runtime conditions on
> which the freeze/remediation plan depends and fails if any required condition is absent from
> `CURRENT_TRUTH.md`; the initial set is (a) watcher/builder branch mismatch, (b) inherited business MCP
> connector surface, and (c) the Builder `remote.origin.fetch` refspec naming the absent
> `claude/bridge-builder` ref.

This is **persistence** ("fails if any required condition is *absent*"), not merely contradiction detection,
and it explicitly enumerates all three required conditions including the branch mismatch and the inherited
business MCP connector surface. Correct.

**(c) `ORCHESTRATOR_V1_TRACEABILITY.md` dispositions N-04** with an explicit `V1 MUST — resolved` row naming
both halves of the repair, and the closing rule **"Silence is not a disposition."** is preserved verbatim.

**No self-adoption / no authority change / no runtime execution / no Phase 1 implication.** `DECISIONS.md`
untouched; freeze contract §27 states "A Director/authored document cannot re-sequence owner gates or promote
itself to normative authority"; `ROADMAP.md` and `CURRENT_TRUTH.md` both label the Phase 0 sequencing split as
"a proposal, not current authority"; acceptance case `AU-01` makes prose-asserted sequencing changes emit
`AUTHORITY_STALE`/BLOCKED; `ID-06` blocks implementation bound to a freeze *branch name* rather than the
owner-adopted exact SHA. Remediation plan §5 is explicitly "separately authorised execution", and §6 keeps
Phase 1 model workers behind live closure of the mismatch. Clean.

### N-01 — repaired, and I independently re-proved its premises against live reality

The plan (§3) now models an **absent** remote ref and a guarded create rather than a fast-forward of an
existing ref. I verified both load-bearing premises read-only this round:

- `git ls-remote --heads origin claude/bridge-builder` → **empty (ref absent on origin)**;
- local `claude/bridge-builder` = `9a27bc441adad1e98e8a9ca257d1883246ee7eec`, and
  `git merge-base --is-ancestor 9a27bc4 295e483` → **true**.

The documented topology matches measured reality exactly. The create-only lease shape
(`--force-with-lease=refs/heads/claude/bridge-builder:` with an empty expected value) is correct Git semantics
for "the ref must not already exist"; BR-02 tests refusal on a raced ref; BR-03 requires an expected-old
`update-ref` for the local move; no reset/clean/stash appears anywhere. Sound.

### N-02 — repaired

`ORCHESTRATOR_V1_STATE_API.md` §3A states the joint oracle explicitly ("both tables must permit the same
operation; the kernel uses their intersection … MUST fail closed"), the bounded-correction path
(`REJECTED -> attempt.assign`) and the deterministic preflight path (attempt `FAILED`/`QUARANTINED` with the
task reaching BLOCKED via the legal `task.block` edge, never an illegal `ASSIGNED -> FAILED`). Tests
ST-11..ST-13 cover the oracle, the correction path and the preflight case. I walked every command that mutates
both tables and found no residual disagreement.

### N-03 — repaired

`CURRENT_TRUTH.md` now distinguishes candidate-addressed from canonically closed ("CG-01 through CG-06 are
addressed by the … freeze candidate … but they become canonically closed only if the owner adopts that freeze
by exact SHA; until adoption they remain open in canonical truth"), and §18 adds the mechanical CG/finding
status consistency scan. Correct — **but see blocker B-03**, which shows that scan checks status *agreement*
only and cannot detect a resolution claim that cites acceptance cases which do not exist.

---

## 4. Material engineering blockers

Ranked most severe first. All are defects in the candidate documents themselves, not runtime or owner gates.

---

### B-01 — Reviewer execution has no durable record, no lease, no fencing binding and no reconciliation step

**File/section:** `ORCHESTRATOR_V1_STATE_API.md` §1 (record list), §2 (`review.request` / `review.record`),
§3 (transition matrix); `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §7 (fencing rule), §21 (reconciliation order).

**Defect.** Implementation work has a full execution substrate: an `attempt` record, a `lease`, a controller
epoch, a monotonic fencing token, process-group ownership and an explicit reconciliation step. Reviewer
execution has **none of it**, despite being a scheduled, model-running, cancellable principal in this design
(freeze contract §19 sets a "reviewer concurrency" ceiling; `CXN-05` asserts reviewer cancellation semantics;
`RV-06` asserts reviewer-unavailability semantics). Each of the following was verified in the candidate text:

1. **There is no reviewer record.** `review.request` only moves the *task* `EVIDENCE_READY -> REVIEWING`; the
   `review` row is not created until a verdict arrives. An in-flight review is invisible to the database.
2. **A reviewer cannot hold a lease.** `lease` is specified as "One authoritative lease per
   `(task_id, revision)`" and carries an `attempt ID`. That single lease is already owned by the
   implementation attempt, and `attempt.assign` is legal only from task `PLANNED`/`REJECTED` — never from
   `REVIEWING` — so a reviewer cannot be represented as an attempt either.
3. **Review admission is omitted from the fencing rule.** Freeze contract §7: "Every **heartbeat, candidate
   admission, evidence admission, delivery update and terminal result** MUST present the current task
   revision, controller epoch and fencing token." Review result admission is absent from that list, absent
   from the `review.record` preconditions in §2/§3, and absent from test `ID-03`, which enumerates exactly the
   same five. The `review` table carries no revision, epoch or fencing-token column.
4. **§21 has no step that reconciles in-flight reviews.** Steps 5–8 cover attempts/cgroups, workspaces,
   candidate/evidence records and remote publications.

**Unsafe consequence.** Two distinct failures, both defeating the acceptance gate the contract exists to
protect:

- *Stale verdict admission.* Reviewer R1 is dispatched for candidate SHA `C`, stalls past its deadline, and
  the controller blocks the task (`RV-06`) or substitutes R2. R1 later returns `ACCEPT` bound to exact SHA
  `C`. Nothing in `review.record`'s preconditions, the `review` schema or `ID-03` rejects it — the SHA still
  matches, so candidate-mutation invalidation never fires. That stale `ACCEPT` is admitted and counts toward
  `candidate.accept`'s "all required independent reviews ACCEPT". The same hole makes `task.cancel`'s promise
  of "no later result admitted" and `CXN-05`'s "no partial verdict becomes authoritative" unenforceable,
  because both are lease-based mechanisms and reviewers have no lease.
- *Orphaned reviewers and duplicate dispatch.* If the controller dies while a reviewer is running, restart
  finds a task in `REVIEWING` with no lease, no attempt, no process record and no reconciliation step. The
  orphaned reviewer process is never killed (§11's TERM/grace/KILL cgroup cleanup is attempt-scoped), and the
  controller either re-dispatches — duplicating a paid model review — or leaves the task in `REVIEWING`
  indefinitely with no operator-visible blocked state.

**Smallest repair.** Give review execution the same substrate that already exists for attempts, without
introducing a new concurrency model:

1. Add a `review_dispatch` record: `dispatch_id`, subject kind/ID, exact subject SHA, task revision,
   controller epoch, fencing token, reviewer principal, state
   `DISPATCHED|COMPLETED|CANCELLED|FENCED|EXPIRED`, heartbeat/expiry deadline, process-group identity.
   Create it in `review.request`.
2. Amend freeze contract §7 to add "**review result admission**" to the enumerated fencing list, and add the
   matching `review_dispatch_id` + epoch + fencing-token precondition to `review.record` in §2 and §3. Reject
   any verdict whose dispatch is not the current non-terminal dispatch for that subject.
3. Add step 7a to §21: "reconcile in-flight review dispatches against process state; fence expired or
   unprovable dispatches and surface unresolved ambiguity as BLOCKED."
4. Amend `ID-03` to include review result admission.

**Exact acceptance test.** Add to §9 of the matrix:

- `RV-11` — a reviewer dispatch is cancelled/expired and replaced, then the original reviewer submits
  `ACCEPT` for the identical unchanged candidate SHA → verdict rejected as stale on the fencing token;
  `candidate.accept` does not observe it; a `transition_event` records the rejection.
- `RV-12` — the controller is killed while a review is in flight, then restarted → restart reconciles the
  review dispatch before enabling dispatch, terminates the orphaned reviewer process group, and either
  re-dispatches exactly once under a new fencing token or enters BLOCKED; never both, and never a silent
  indefinite `REVIEWING`.
- `RV-13` — `task.cancel` while a review is in flight → dispatch fenced immediately; any later verdict
  rejected; no partial verdict becomes authoritative (makes `CXN-05` mechanically testable).

---

### B-02 — The failure taxonomy defines 29 reason codes but never maps them to the four retry classes; attempt stall/timeout is unclassified

**File/section:** `ORCHESTRATOR_V1_STATE_API.md` §7 (Failure reason codes);
`ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §10.1 / §10.2 / §10.3.

**Defect.** §7 mandates that implementations "MUST preserve stable top-level classification into RETRYABLE,
BLOCKED, REJECTED/FAILED or ESCALATED" — but the freeze set never supplies that mapping. §10.1 and §10.2 are
each explicitly headed "**Examples:**", not total functions. Cross-checking the 29 normative codes against
those example lists leaves at least these unclassified: `PROCESS_TIMEOUT`, `PROCESS_STALLED`,
`PROCESS_ORPHANED`, `DB_IO`, `RESOURCE_CAPACITY`, `PUBLICATION_CONFLICT`, `EVIDENCE_MISSING`,
`EVIDENCE_DIGEST_MISMATCH`, `CONTEXT_STALE`, `AUTHORITY_STALE`, `DEPENDENCY_BLOCKED`, `REVIEW_REJECTED`.

The process codes are the dangerous ones. §3A says only "`RUNNING` | process exits without candidate |
`CLOSED / FAILED` | diagnostics/evidence persisted; **task retry/correction policy decides next task state**",
and §10.3's correction budget is scoped exclusively to *evidence-backed rejection* ("after evidence-backed
rejection, at most one bounded same-contract correction"). A model attempt that stalls or times out **without
ever producing a candidate** is therefore governed by no stated budget at all.

**Unsafe consequence.** Two conformant implementations can legitimately disagree on whether a stalled Opus
attempt is RETRYABLE (up to §10.2's 5 attempts within a 15-minute window) or BLOCKED (no automatic retry).
Under the RETRYABLE reading the controller silently relaunches a long, expensive model attempt up to five
times with no owner-visible block — and because §9 explicitly declines to guarantee exactly-once model
execution, each relaunch may already have produced real side effects in its workspace. This reproduces, in a
new location, exactly the incident the traceability matrix records as a founding lesson ("deterministic
precondition retried eight times" → "deterministic BLOCKED vs transient RETRY"). For a contract whose stated
purpose is determinism, leaving the retry class of its own reason codes to implementer discretion defeats the
freeze.

**Smallest repair.** Add one column to the §7 reason-code list giving each code its normative top-level class
(RETRYABLE / BLOCKED / REJECTED-FAILED / ESCALATED), and state that the list is total — an unclassified or
unknown code defaults to BLOCKED, never RETRYABLE. Classify `PROCESS_TIMEOUT`, `PROCESS_STALLED` and
`PROCESS_ORPHANED` explicitly, and add one sentence to §10.3 giving the bounded budget for non-rejection
attempt failure (recommend: at most one relaunch, then BLOCKED/ESCALATED) so the relaunch count is finite and
stated.

**Exact acceptance test.** Add to §7 of the matrix:

- `PR-09` — enumerate every reason code in `ORCHESTRATOR_V1_STATE_API.md` §7 and assert each resolves to
  exactly one top-level class; an unknown/unmapped code resolves to BLOCKED. The test fails if any code is
  unmapped.
- `PR-10` — an attempt stalls past its deadline with no candidate → the attempt closes `FAILED`/`QUARANTINED`,
  the task takes the budgeted path, and the **total number of model relaunches is bounded and equal to the
  declared budget**; counters persist across controller restart (composes with `ST-08` / `IP-04`).

---

### B-03 — The freeze contract and traceability matrix both certify CG-05 using acceptance cases `EN-01..EN-0x` that do not exist, and disagree on the range

**File/section:** `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §24 (CG-05 line) and §22A;
`ORCHESTRATOR_V1_TRACEABILITY.md` (CG-05 row); `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md` (whole file).

**Defect.** Mechanically verified against the candidate tree:

- Freeze contract §24: "**CG-05:** clean reconstruction -> resolved normatively by §22A and **EN-01..EN-03**
  acceptance cases."
- Traceability CG-05 row: "freeze contract §22A + acceptance **EN-01..EN-04** require allow-listed egress,
  immutable pins, integrity checks, disposable/fresh environment and fingerprint equality".
- `grep -cE "^\| EN-"` over the acceptance matrix → **0**. The matrix defines exactly these ID prefixes:
  `API AU BR CP CT CX CXN DB DG EV ID IN IP LS PB PR RV ST UP WS`. There is no `EN` family anywhere in the
  repository.

A contract gap is therefore certified **resolved** by a named test set that does not exist, and the two
normative documents cite two different sizes for that non-existent set.

**Unsafe consequence.** §22A is a MUST-bearing section — it governs every "this environment is reproducibly
reconstructible" claim, requiring an approved egress allow-list, immutable pinned artifact identities,
pre-extraction and post-install integrity verification, a fresh fingerprint, fingerprint equality, and proof
that pre-existing local tooling did not satisfy the test accidentally. It currently has **zero** test coverage
in the acceptance matrix. That directly violates freeze acceptance rule 3 ("acceptance/fault-injection matrix
covers every MUST-level invariant") and §18's own gate ("every MUST in … has a test ID here or is explicitly a
static/documentary invariant" — §22A is neither). Worse, the candidate would **pass its own §18 mechanical
scan**: that scan checks `CURRENT_TRUTH.md` / `ROADMAP.md` for conflicting status assertions, so it cannot
detect a resolution that cites a phantom test set. The owner would be adopting a freeze whose most
supply-chain-sensitive requirement is certified by nothing — the precise false-green failure class that BE-04
and `WS-14` exist to prevent.

**Smallest repair.** Add the missing `EN-01..EN-04` block to the acceptance matrix covering §22A, and align
both citing documents to the same range. Then extend the §18 mechanical gate from "status agreement" to also
assert that **every test ID referenced anywhere in the freeze set resolves to a row that exists in the
acceptance matrix**, which would have caught this defect automatically.

**Exact acceptance test.**

- `EN-01` — reconstruct the declared environment on a disposable host with no pre-existing target toolchain →
  the resulting fingerprint equals the declared environment-manifest digest; a rerun on the already-provisioned
  Builder is explicitly rejected as reconstruction evidence.
- `EN-02` — reconstruction attempts a destination absent from the approved egress allow-list → denied and
  BLOCKED, not silently skipped.
- `EN-03` — a pinned asset's digest mismatches at pre-extraction, and separately a post-install
  version/provenance check disagrees → reconstruction fails closed in both cases; exit-0 does not override.
- `EN-04` — pre-existing local tooling could have satisfied the check → the test proves it did not (negative
  control), otherwise the reconstruction claim is rejected.
- Plus a meta-check in §18: every referenced test ID exists.

---

### B-04 — `integration.cancel` requires fencing an "integrator attempt / lease" that the schema cannot represent

**File/section:** `ORCHESTRATOR_V1_STATE_API.md` §2 (`integration.cancel` row), §3 (integration.cancel
transition row), §1 (`lease` record); `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §21.

**Defect.** The command surface says `integration.cancel` → "integrator **attempt** fenced/stopped", and the
transition matrix says "any integrator **process/lease** fenced and stopped". No such record exists. `lease`
is uniquely keyed to `(task_id, revision)` and holds an `attempt ID`; an integration is explicitly **not** a
task (freeze contract §16: "Individual source tasks remain ACCEPTED; they do not transition into
integration/release states"), and `attempt.assign` is legal only from task `PLANNED`/`REJECTED`. The
integrator therefore has no attempt, no lease, no fencing token and no process-group record. §21's
reconciliation order likewise contains no integration step.

**Unsafe consequence.** A normative precondition is unimplementable as written — the kernel is instructed to
fence something that cannot exist, which is precisely the "undefined authoritative transition or mutation
path" that freeze acceptance rule 2 forbids. Operationally: a cancelled or crashed integrator's process tree
is never proven stopped (§11's cgroup cleanup is attempt-scoped), its integration workspace is released for
reuse without the emptiness verification the contract mandates for attempts, and after a controller restart an
`INTEGRATING` integration has no reconciliation path and stalls with no operator-visible BLOCKED state. The
state guard does prevent a stale integrator's *result* from being admitted (`CANCELLED` is terminal, so
`integration.register` is illegal), so this is narrower than B-01 — but the orphan-process and workspace-reuse
hazards are real and the textual contradiction is explicit.

**Smallest repair.** Either (i) extend the `attempt` / `lease` records to carry a subject kind
(`TASK|INTEGRATION`) and key the lease on `(subject_kind, subject_id, revision)`, or (ii) add a minimal
`integration_attempt` record mirroring `attempt` (state, epoch, fencing token, workspace, process-group,
disposition). Option (i) is smaller and reuses the fencing machinery wholesale. Then add an integration
reconciliation step to freeze contract §21.

**Exact acceptance test.** Add to §10 of the matrix:

- `IN-11` — `integration.cancel` while an integrator process is running → lease/fence invalidated, process
  group TERM/grace/KILL, emptiness verified before workspace reuse; if the process cannot be proven stopped,
  the workspace is QUARANTINED and the integration BLOCKED (mirrors `WS-10` / `WS-11` / `LS-06`).
- `IN-12` — controller restart with an integration in `INTEGRATING` → reconciliation observes integrator
  process/workspace state before dispatch is enabled; never blind re-dispatch, never silent indefinite
  `INTEGRATING`.

---

### B-05 — The `finding` record is task-scoped, so integration-review blocking findings cannot be represented, yet `integration.verify` / `integration.reject` gate on them

**File/section:** `ORCHESTRATOR_V1_STATE_API.md` §1 (`finding` record), §2/§3 (`integration.verify`,
`integration.reject`); `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §5.3.

**Defect.** `finding` is specified with a mandatory `task/revision` binding and no subject-kind discriminator
— unlike `review` and `evidence_manifest`, which both carry `subject kind CANDIDATE|INTEGRATION`. (The
document's own convention marks optional columns "nullable"/"NULL"; `task/revision` is not so marked.) Yet
`integration.verify`'s precondition is "all required integrated tests/reviews pass; **no blocking findings**"
and `integration.reject` fires "on blocking integrated **finding**". Integration findings gate two normative
transitions but have nowhere to live, and `IN-10`'s rejected-integration correction lineage has no per-finding
disposition to carry forward.

**Unsafe consequence.** The kernel cannot evaluate `integration.verify`'s stated precondition, so that gate is
enforced only by whatever the next reviewer happens to re-discover — weaker than the contract claims. CG-04's
whole purpose (represent partial progress without falsely calling work complete) does not extend to
integrations: if a rejected integration had three blocking findings and the replacement resolves two, there is
no authoritative record of the third, and `parent_integration_id` carries lineage without carrying the open
findings. Severity is lower than B-01..B-04 because `IN-10` still requires a fresh integrated review, but it
is a genuine dropped-traceability defect against a gate the contract asserts.

**Smallest repair.** Give `finding` the same discriminator its neighbouring records already use: replace the
mandatory `task/revision` with `subject kind CANDIDATE|INTEGRATION` + `subject_id` + nullable
`task_id`/`revision`, and state that `integration.verify` evaluates open/blocking findings for its own
subject.

**Exact acceptance test.** Add to §10 of the matrix:

- `IN-13` — an integration review records a blocking finding → `integration.verify` is refused while that
  finding is `OPEN`/`BLOCKED`; the finding is queryable by integration subject; a correction integration
  created under `parent_integration_id` inherits the unresolved finding and cannot reach `VERIFIED` until it
  is `RESOLVED` or `OBSOLETE` with a recorded reason (the integration analogue of `ST-09`).

---

## 5. Non-blocking observations (recorded so they are not silently lost)

- **§18's required-condition set has no defined removal path.** The gate "fails if any required condition is
  absent from `CURRENT_TRUTH.md`" and names an "initial set". Once a condition is genuinely remediated — e.g.
  the fetch refspec becomes valid after the ref is recreated — the gate as written would either fail forever
  or force `CURRENT_TRUTH.md` to keep asserting something no longer true. Suggest one sentence naming the
  evidence and authority required to retire an entry. Not a blocker: "live unremediated" is arguably
  self-limiting by definition.
- **`meta.operational_mode` has no command that sets `BLOCKED`.** `controller.drain` sets `DRAINING` and
  `controller.resume` sets `RUNNING`; entry into `BLOCKED` is only implied by freeze contract §6. Behaviour is
  covered by `DB-01` / `DB-02` / `DB-11`, so this is tidiness rather than a hole.
- **Freeze contract §18 observability metrics and §19 browser-slot ceilings have no test IDs** and are not
  listed among the static/documentary invariants in `ORCHESTRATOR_V1_STATE_API.md` §10. Minor coverage gap of
  the same family as B-03; the meta-check proposed there would surface it.

---

## 6. Owner / runtime pending gates — NOT engineering defects

Per the inbox's handling rule, these fail closed correctly in the contract and are listed separately.

- **OWNER-PENDING — adoption of the exact freeze SHA.** The freeze is a candidate until the owner records
  exact SHA `2bf240c33bfbf0e66257b82a43013cfb3f5af958` in `DECISIONS.md` (freeze contract §27, matrix §18).
  `DECISIONS.md` is untouched by this candidate; DEC-046 / DEC-047 authority is intact.
- **OWNER-PENDING — any DEC-046 sequencing amendment.** The candidate *proposes* allowing Phase 0
  repository-only kernel work immediately after an accepted freeze; both `ROADMAP.md` and `CURRENT_TRUTH.md`
  state in terms that this "is a proposal, not current authority". Correct fail-closed behaviour. No approval
  is recorded or inferred by me.
- **RUNTIME-PENDING — watcher/builder branch mismatch.** Re-observed live this round: `/opt/crooks-builder` is
  on `claude/builder-environment-repair` at `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` while the watcher unit
  declares `claude/bridge-builder`. The remediation plan exists
  (`WATCHER_BUILDER_IDENTITY_REMEDIATION.md`); execution is separately authorised and was **not** performed.
- **RUNTIME-PENDING — stale Builder `remote.origin.fetch` refspec.** Re-observed live: the only configured
  refspec is `+refs/heads/claude/bridge-builder:refs/remotes/origin/claude/bridge-builder`, and that remote
  ref is absent on origin, so `git fetch --all` fails there. Per `CURRENT_TRUTH.md`'s explicit
  no-ad-hoc-repair instruction I did **not** repair it and used explicit branch fetches instead.
- **RUNTIME-PENDING — inherited business MCP connector surface.** This unattended session again presented
  account-level business connector tools (Shopify, Gmail, Google Drive, Omnisend, Resend) beyond the intended
  narrow engineering roster. **None were invoked.** This is the live condition that freeze contract §12 and
  test `CP-02` require to fail closed before write-capable workers run.

All three live runtime conditions that §18 requires `CURRENT_TRUTH.md` to persist were independently
re-measured this round, and **all three are still present and accurately described** — so the N-04 repair is
validated against reality, not merely against the text.

---

## 7. State of this checkout, the production branch, and the environment

**The builder checkout was inspected before acting, and was not assumed to be where a previous run left it.**

| Item | Value |
| --- | --- |
| Builder path | `/opt/crooks-builder` |
| Branch at start and at end | `claude/builder-environment-repair` (unchanged) |
| HEAD at start and at end | `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` (unchanged) |
| `git status --porcelain` at start and at end | empty — clean; nothing modified, nothing untracked |
| Local `claude/bridge-builder` ref | `9a27bc441adad1e98e8a9ca257d1883246ee7eec` (unchanged) |
| `remote.origin.fetch` | unchanged — still the single stale refspec |

**Production checkout — read only, never edited, switched or reset:** `/opt/crooks-os/crooks-assistant`,
branch `claude/linux-prod-migration-production`, **HEAD `1cf3a0f3361b79f9de208d80f501543c53c244b5`** (the
DEC-048 ratified SHA), working tree clean.

**Files changed by me:** exactly one — `/opt/crooks-ai-bridge/bridge/claude-outbox.md` (this file). No other
file in the bridge worktree was touched. No `git add`, no commit, no push, by design; the watcher publishes
this file itself.

**One repository side effect, disclosed in full:** to read the candidate at all I ran explicit `git fetch`
into named remote-tracking refs, which created
`refs/remotes/origin/chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` and advanced
`refs/remotes/origin/claude/product-memory-foundation` from `c7a1cf6` to `9e59860`. This touches
remote-tracking refs only — no working tree, no HEAD, no local branch, no config, no checkout, no switch, no
reset/clean/stash. It is the explicit-branch-fetch method `CURRENT_TRUTH.md` instructs workers to use.

**Test results:** none run, and none were appropriate — this is a read-only specification review of a
documentation-only candidate that changes no code, test or config. I ran no build, no pytest, no ruff, no
gitleaks, no installer and no watcher test. I am reporting that plainly rather than implying coverage that
does not exist.

**Service and server state (observed read-only, unchanged by this round):**

- `crooks-assistant.service` — active, enabled.
- `crooks-bridge-watcher.service` — active, enabled.
- Listener: `127.0.0.1:8000` only (`LISTEN 0 2048 127.0.0.1:8000`). Not publicly exposed.

**Safety constraints preserved.** `writes_enabled` remains false; `CROOKS_WRITES_LOCAL_OWNER` remains false;
FastAPI remains bound to `127.0.0.1`; port 8000 is not exposed publicly; proposal/action/verification safety
semantics are unchanged; no live Shopify, Gmail or ElevenLabs call and no live external mutation; V2 not
begun; UI not redesigned; the Mac deployment and rollback path are untouched; `/root/.claude` untouched and
writable; no secret value printed, logged or committed. No systemd, account, global Claude, MCP, connector,
credential or permission state was altered. No runtime remediation was executed. No finding was fixed.

**Errors:** none. No command failed, and nothing was blocked by my permission layer.

---

## 8. Decisions and questions needing review

1. **The verdict turns on B-01 and B-03, not on document quality.** The freeze set is genuinely detailed and
   the N-series repairs are sound; I deliberately did not approve on that basis. B-01 is a control-plane hole
   that lets a stale reviewer verdict count toward acceptance; B-03 means the owner would be adopting a freeze
   in which the reconstruction MUSTs are certified by test IDs that do not exist.
2. **B-01 and B-04 share one root cause.** The candidate models *implementation* execution rigorously and then
   treats reviewers and integrators as if they were pure functions rather than the scheduled, cancellable,
   crash-prone model processes the rest of the document says they are. Whoever repairs this should consider
   generalising `attempt` / `lease` over a subject kind once, rather than patching reviewer and integrator
   separately — that single change closes B-01 and B-04 together and is smaller than two bespoke records.
3. **Question for the Director, above a review round's authority:** in B-04 I recommend option (i)
   (generalise the existing lease over `subject_kind`) over option (ii) (a parallel `integration_attempt`
   record). Option (i) is smaller and reuses fencing machinery, but it changes a record already load-bearing
   for `ST-01..ST-13` and `LS-01..LS-08`, so those tests would need re-derivation. That trade-off is an
   architecture call, not a review call.
4. **No owner approval is recorded, inferred or implied by this round.** Nothing here authorises adoption,
   implementation, remediation execution, deployment or any privilege change.

---

## 9. Exact proposed next step

**Return the candidate to the Director for repair. Do not put `2bf240c` in front of the owner for adoption.**

Precisely:

1. On a **new** candidate branch from `2bf240c33bfbf0e66257b82a43013cfb3f5af958`, apply the five smallest
   repairs in §4: B-01 (review dispatch record + fencing + §21 reconciliation step + `ID-03` amendment),
   B-02 (total reason-code → retry-class mapping + bounded non-rejection relaunch budget), B-03 (add the
   `EN-01..EN-04` block, align both citing documents to one range, extend the §18 mechanical gate to assert
   every referenced test ID exists), B-04 (subject-kind-generalised lease + §21 integration reconciliation
   step), B-05 (subject-kind discriminator on `finding`).
2. Add the new acceptance cases named above: `RV-11`, `RV-12`, `RV-13`, `PR-09`, `PR-10`, `EN-01`..`EN-04`,
   `IN-11`, `IN-12`, `IN-13`, plus the §18 referenced-test-ID meta-check.
3. Because the repair touches normative acceptance and authority-bearing documents, it is `MATERIAL` under the
   candidate's own §15 risk table and requires a **fresh** independent adversarial review bound to the new
   exact candidate SHA. Per §14.3 and `EV-06`, this review of `2bf240c` is automatically invalidated by any
   candidate SHA change — do not carry this verdict forward.
4. Owner adoption remains gated until that fresh review returns
   `ENGINEERING CONTRACT READY — OWNER/RUNTIME GATES REMAIN`. The two RUNTIME-PENDING conditions remain
   independently gated regardless of the freeze outcome, and Phase 1 / write-capable model workers stay
   blocked on live closure of the watcher/builder identity mismatch either way.

**Nothing in this round was a merge, deploy, remediation or approval, and none is proposed as a next step
without explicit owner authorisation.**

---

**Inbox SHA processed this round:** `63f7bcf18fd4b4d99467bd01ecbab511e76b9a2c`
**Candidate reviewed:** `2bf240c33bfbf0e66257b82a43013cfb3f5af958`
**Base / merge-base:** `9e59860a945ec339c69af8709cd0721f0a795327`
**Verdict:** `CHANGES REQUIRED BEFORE OWNER DECISION`
