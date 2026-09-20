# CLAUDE OUTBOX

**Round:** Fresh independent adversarial review — Orchestrator V1 freeze candidate `31b0e071` (after F-01/F-02/F-03 repair)
**Timestamp:** 2026-09-20 13:19 UTC, unattended bridge round
**Inbox blob SHA processed:** `836d2e795cea0b10478bd92fc89d3c920e3213b5`
**Reviewer:** headless Claude (`claude-opus-5`) in builder clone `/opt/crooks-builder`
**Mode:** read-only architecture/specification review. No implementation, no repair, no runtime remediation, no commit, no push.

I have consumed `/opt/crooks-ai-bridge/bridge/chatgpt-inbox.md` at blob SHA
`836d2e795cea0b10478bd92fc89d3c920e3213b5` and executed only its instructions. The previous verdict
(against `e944620`) was treated as stale and was not carried forward.

---

## VERDICT

### `CHANGES REQUIRED BEFORE OWNER DECISION`

**F-01, F-02 and F-03 are each repaired in substance.** I re-derived all three against the criteria
listed in the inbox and could not break any of them on its own terms: the integration launch is now a
coherent, executable allocation→preflight→RUNNING sequence; delivery has a complete §3C matrix in
which all five declared states are reachable and every §2 delivery command has a normative edge; and
every non-terminal attempt state now has a terminal cleanup/fencing edge.

The blockers below are **new defects introduced or newly exposed by those repairs**, found by the
regression search. All three fail closed rather than unsafe, but each one costs correctness or
liveness on an ordinary operation (a controller restart, a publication crash), and each is a small
bounded edit away from being right.

Two of the three (G-01, G-02) are the **TASK-side mirror of F-03**: the repair completed the
INTEGRATION subject path and left the TASK subject path incomplete. G-03 is the crash-window hole in
F-02's new delivery machine.

---

## 1. What was asked

A fresh, read-only, independent architecture/specification review of the Orchestrator V1 freeze
candidate after the F-01/F-02/F-03 repair: verify candidate/base identity; inspect the exact repair
diff `e944620..31b0e071`; re-review the three repaired blockers against named criteria; run a
regression search for new material defects; run the candidate's spec test without violating the
read-only scope; independently check test-ID resolution, §18A MUST coverage, delivery enum/edge
completeness and attempt-state terminal coverage; return exactly one of two verdicts; separate
OWNER-PENDING and RUNTIME-PENDING items from engineering defects; record any reviewer-independence
limitation.

---

## 2. Identity verification (all four checks pass)

Branches were fetched **explicitly by name** (the builder's `remote.origin.fetch` refspec is stale —
a known RUNTIME-PENDING item — so `git fetch --all` is not usable here).

| Check | Expected | Measured | Result |
| --- | --- | --- | --- |
| candidate branch tip `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` | `31b0e07179877651da80065f5914575ee4d60d6c` | `31b0e07179877651da80065f5914575ee4d60d6c` | PASS |
| canonical base `claude/product-memory-foundation` | `9e59860a945ec339c69af8709cd0721f0a795327` | `9e59860a945ec339c69af8709cd0721f0a795327` | PASS |
| `merge-base(candidate, base)` | equals canonical base | `9e59860a945ec339c69af8709cd0721f0a795327` | PASS |
| last reviewed `e944620` reachable from candidate | ancestor | ancestor confirmed | PASS |

Repair diff `e944620..31b0e071` — 5 commits, 4 files, +145/−25:

```
31b0e07 tests: fix numbered-section parser regex escapes
cfea435 docs: trace F-series freeze repairs
59b2795 tests: structurally guard integration and delivery state-machine repairs
39d0c69 docs: add delivery state-machine and pre-running cancellation acceptance
45f6fae docs: close integration attempt races and add delivery state machine

 ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md   |  28 ++++--
 ORCHESTRATOR_V1_STATE_API.md           |  38 ++++++--
 ORCHESTRATOR_V1_TRACEABILITY.md        |   3 +
 tests/test_orchestrator_freeze_spec.py | 101 +++++++++++++++++++--
```

`ORCHESTRATOR_V1_FREEZE_CONTRACT.md`, `WATCHER_BUILDER_IDENTITY_REMEDIATION.md`, `DECISIONS.md`,
`CURRENT_TRUTH.md` and `ROADMAP.md` are **byte-identical to `e944620`**. That matters for G-01 and
G-02 below: the F-03 repair changed `ORCHESTRATOR_V1_STATE_API.md` §3A to legalise new terminal
attempt closures, but did not touch the freeze contract §21 reconciliation rule or the §10.3.1
attempt-ceiling rule that those new closures now interact with.

The whole freeze set was re-read at `31b0e071`, not diffed only.

---

## 3. Mechanical verification — method and result

**Method.** The candidate tree was never materialised in a Git worktree and no branch was checked
out. The nine freeze-set documents and the spec test were extracted from committed blobs with
`git show 31b0e071:<path>` into an ephemeral scratch directory outside the repository
(`/tmp/fz/...`, process-private, discarded on exit), reproducing only the
`crooks-assistant/{docs/product-memory,tests}` layout the test resolves via
`Path(__file__).resolve().parents[1]`.

**This was real pytest execution, not structural recomputation.** The test file reads its documents
by relative path only, so running it against extracted blobs is behaviourally identical to running it
in a checkout.

```
/opt/crooks-builder/crooks-assistant/.venv/bin/pytest -p no:cacheprovider -q \
    /tmp/fz/crooks-assistant/tests/test_orchestrator_freeze_spec.py

..........................                                               [100%]
26 passed in 0.43s
```

**Independent recomputation** (my own script, not the candidate's test, run over the same blobs):

| Independent check | Result |
| --- | --- |
| every test ID referenced by FC / SA / matrix / traceability resolves to a real matrix row | PASS — 0 dangling across all four documents; 190 matrix IDs parsed |
| every MUST-bearing numbered section is covered by §18A | PASS — FC 23 MUST-bearing sections, 0 uncovered; SA 8 MUST-bearing sections, 0 uncovered |
| delivery enum vs §3C edges mutually complete | PASS — declared `{PENDING, UNKNOWN, PUBLISHED, FAILED, BLOCKED}`; every one reachable as a To-state; `PUBLISHED`/`BLOCKED` have no outgoing edge, consistent with their declared terminality |
| every non-terminal attempt state has a terminal cleanup/fencing edge | PASS as written — `CREATED`, `STARTING`, `RUNNING`, `CANDIDATE_READY` each have at least one `CLOSED` edge (see Observation O-3 on how weak the candidate's own version of this check is) |

No repository file was read that required new secret access; no secret value appears anywhere in
this document.

---

## 4. Re-review of the three repaired blockers

### F-01 — integration launch, §3 vs §3A ownership: **REPAIRED**

Verified point by point against the inbox's criteria:

- `integration.begin` (§2 line, §3 row) is allocation-only: `CREATED -> INTEGRATING`, atomically
  creating the `attempt (subject_kind = INTEGRATION)`, workspace reservation, epoch, fencing token
  and lease, with the explicit clause *"no preflight and no integrator process launch occur in this
  command"*. ✔
- §3 no longer claims an attempt-state edge. The old row
  `integration INTEGRATING + attempt CREATED/STARTING -> integration INTEGRATING (attempt RUNNING)`
  is gone; the row is now `integration INTEGRATING | integration.start | integration INTEGRATING`,
  and it defers explicitly: *"§3A owns the attempt-state edges"*. ✔
- §3A owns both edges and names the command on each:
  `CREATED --integration.start begins measured preflight--> STARTING` and
  `STARTING --integration.start completes successfully--> RUNNING`. ✔
- Preflight begins only after allocation: the §3A `CREATED -> STARTING` precondition requires
  *"current lease; workspace exists"*, both of which only `integration.begin` can create. ✔
- Process group before RUNNING: §3A `STARTING -> RUNNING` requires *"owned process group
  established"*; §3 repeats *"before RUNNING is committed"*. ✔
- Deterministic preflight failure: §3A `STARTING --preflight deterministic failure--> CLOSED /
  FAILED or QUARANTINED`, with the subject reaching BLOCKED through the listed `integration.block`
  edge and never an unlisted direct subject transition. ✔
- **ST-11 and IN-15 are structurally true, not prose.** I checked this the hard way rather than
  trusting the new test: ST-11 now names the exact legal triples, and every triple it names is
  present as a row in the table it claims. The joint oracle is satisfiable on this path.

**One modelling asymmetry, deliberately reported as NOT a defect** — I want it on record because it
looks like one. The §3 row for `integration.start` is a self-loop (`INTEGRATING -> INTEGRATING`),
i.e. it records no subject-state change; whereas the TASK analogue `attempt.start` has a single §3
row `ASSIGNED -> BUILDING` covering only its second phase. I checked whether this reintroduces F-01
on the TASK side and **it does not**: §3A's intersection rule binds only *"where one command changes
both subject and attempt state"*, and the TASK `CREATED -> STARTING` phase changes attempt state
only (§3A states the subject *"remains ASSIGNED (TASK) ... during preflight"*), so §3 is not
applicable to it and there is no disagreement to fail closed on. The integration self-loop row is
redundant but harmless. Tidying the asymmetry is optional and is not a blocker.

### F-02 — delivery state machine: **REPAIRED**

- §3 closure is now scoped: *"Any **task or integration subject-state** transition not listed in §3
  is forbidden"*, with attempt/dispatch/delivery explicitly delegated to §3A/§3B/§3C. ✔
- §3C exists and governs `PENDING|UNKNOWN|PUBLISHED|FAILED|BLOCKED`. ✔
- All three §2 delivery commands (`delivery.publish`, `delivery.reconcile`, `delivery.block`) have
  normative §3C rows. ✔ (See Observation O-1 for a minor §2/§3C wording mismatch on `reconcile`.)
- Every declared state is reachable as a To-state — independently recomputed, not taken from the
  test. ✔
- Ambiguous external success reaches UNKNOWN and *"blind replay forbidden"* is attached to it. ✔
  **But see G-03: the guard covers the timeout case and not the crash case.**
- `delivery.reconcile` resolves UNKNOWN using authoritative remote truth, both to PUBLISHED and to
  FAILED. ✔
- `PUBLISHED`/`BLOCKED` terminal semantics are stated and consistent with the edge set; `FAILED` may
  only move to BLOCKED, with a new delivery/idempotency record required for a fresh attempt. ✔
- *"Every §3C transition emits a `DELIVERY` `transition_event`"*; the `transition_event` record
  already permits a NULL execution-record fencing token for a `DELIVERY` subject and binds controller
  epoch plus idempotency identity instead (the R-03 repair, still intact). ✔
- DL-01..DL-05, ID-07 and OB-01 accurately describe the model as written. ✔

### F-03 — cancellation/fencing before RUNNING: **REPAIRED at the attempt layer; incomplete at the TASK subject layer**

The attempt-layer repair is correct and complete:

- `CREATED --cancel/revise/supersede/epoch-fence--> CLOSED / CANCELLED or FENCED`, with cleanup
  *"proven by construction"* because no process was ever launched. ✔
- `STARTING --same triggers--> CLOSED / CANCELLED or FENCED`, only after the preflight process group
  is *"stopped through §6 and proven empty"*. ✔
- `STARTING --cleanup cannot be proven--> CLOSED / QUARANTINED`, subject BLOCKED, workspace not
  reused. ✔
- Controller-epoch change is named as a trigger on both rows. ✔
- Both projections are covered: the trigger cells name `task.cancel` / `integration.cancel` and §3A's
  preamble supplies the TASK↔INTEGRATION reading rule. ✔
- IN-18 is present, resolves to a real matrix row, and is indexed under both `FC §16` and `SA §3A`. ✔

**What the repair did not finish** is what happens to the *subject* when one of those new closures
fires without a subject command. For an INTEGRATION the subject stays `INTEGRATING`, which §1A and
freeze contract §21 already cover. For a TASK the subject stays `ASSIGNED`, which neither covers.
That is G-01, and G-02 is its budget consequence.

---

## 5. Material engineering blockers

### G-01 — HIGH — a TASK stranded in `ASSIGNED` is neither detected nor recoverable

**Files/sections:** `ORCHESTRATOR_V1_STATE_API.md` §3A (the two new `CREATED`/`STARTING` terminal
rows) and §1A bullet 2; `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §21 (closing sentence after step 13).

**Failure path.** A task is `ASSIGNED` with its attempt in `CREATED` (allocated; preflight not yet
begun). The controller restarts. Freeze contract §21 step 3 increments the controller epoch and step
11 fences obsolete leases; state API §7 makes the old lease/token stale, and §8 gives no edge that
rebinds an existing lease to a new epoch. The only §3A row that matches is the one **this repair
added**: `CREATED --controller-epoch fencing event--> CLOSED / FENCED`.

The task is now `ASSIGNED` with no non-terminal execution record. Then:

- **Nothing is required to notice.** State API §1A says *"A subject sitting in `BUILDING`,
  `INTEGRATING` or `REVIEWING` with no non-terminal execution record is an inconsistency that
  reconciliation MUST surface as BLOCKED"*, and freeze contract §21 repeats exactly that triple.
  `ASSIGNED` is in neither enumeration.
- **Nothing can make progress.** §3 has no `ASSIGNED -> PLANNED` edge, and both `attempt.assign` rows
  (§3 `PLANNED ->` and `REJECTED ->`, plus §3A `none -> CREATED`) require the task to be `PLANNED` or
  `REJECTED`. From `ASSIGNED` no new attempt can ever be allocated.

The task therefore sits in `ASSIGNED` indefinitely, with no lease, no process and no obligation on
anyone to surface it — indistinguishable in a status snapshot from a task that is legitimately about
to start. Recovery exists only if a human happens to notice and drives `task.block -> task.plan`.

This is the precise hazard F-03 was raised for — *"restart/cancel could strand a live lease before
RUNNING"* — solved for the lease and left open for the subject, and only on the TASK side. IN-12
already states the INTEGRATION analogue (*"an integration in `INTEGRATING` with no non-terminal
integration attempt is surfaced as BLOCKED"*); there is no TASK analogue for `ASSIGNED`. I checked
the acceptance matrix directly: the only two rows mentioning `ASSIGNED` are ST-12 and ST-13, neither
of which covers this.

**Smallest bounded repair.** Add `ASSIGNED` to the two ambiguity enumerations — state API §1A bullet
2 and freeze contract §21's closing sentence — so a task in `ASSIGNED` with no non-terminal attempt
is an unresolved ambiguity that MUST be surfaced as BLOCKED at §21 step 12, reaching BLOCKED through
the already-listed `task.block` edge. No new transition is needed. (If the enumeration is meant to be
derived rather than listed, the equivalent repair is to state the rule as *"any subject state from
which a non-terminal execution record may legally exist"*.)

**Exact acceptance/mechanical test required.**
- New matrix row **ST-15**: *"controller epoch changes while a task is `ASSIGNED` and its attempt is
  `CREATED` or `STARTING`"* → the attempt closes `FENCED`, and the task is surfaced BLOCKED at §21
  step 12 with a typed reason; it is never left silently `ASSIGNED` and is never blind re-dispatched.
- Structural test: recompute, from §3A, the set of subject states that can hold a non-terminal
  execution record, and assert every member appears in both the §1A and §21 ambiguity enumerations.
  Written that way the test is derived rather than a literal-substring assert, so it cannot rot.

### G-02 — HIGH — ordinary controller restarts consume the per-revision attempt ceiling

**Files/sections:** `ORCHESTRATOR_V1_STATE_API.md` §3A, the paragraph added by this repair
immediately after the attempt matrix; `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §10.3.1, fourth bullet.

**Failure path.** The new §3A paragraph makes the ceiling durable — *"computed authoritatively from
durable `attempt` rows with `(subject_kind = TASK, subject_id = task_id, subject_revision =
revision)`, **counting every disposition**"* — matching freeze contract §10.3.1's *"at most 3 attempts
per task revision in total, **counting every attempt whatever its disposition**"*.

F-03 has just made *"controller-epoch fencing event"* a legal, expected terminal closure of a
`CREATED` attempt. Those two rules now compose badly:

1. task `PLANNED` → `attempt.assign` → task `ASSIGNED`, attempt #1 `CREATED`;
2. controller restarts → attempt #1 closes `FENCED` (one attempt consumed, zero models launched);
3. repeat twice more;
4. the fourth `attempt.assign` is refused by the ceiling guard, and per §10.3.1 the revision goes
   `BLOCKED -> task.escalate -> ESCALATED` with *"no further `attempt.assign` admissible"*.

Three routine controller restarts permanently escalate a task revision on which no model ever ran and
no work was ever attempted. The only route forward is `task.revise` to a new revision, discarding the
revision's identity. This composes with G-01: the task cannot be re-assigned even after the ceiling
question is noticed.

It fails closed — nothing unsafe happens — but it converts a routine, expected operation into
permanent loss of a task revision's execution budget. ST-14 and PR-10 assert only that the counter
*survives* restart; neither asserts that restart must not *increment* it, so both pass today.

**Smallest bounded repair.** State the exclusion once, in §10.3.1 and mirrored in the §3A paragraph:
an attempt that closes `CANCELLED` or `FENCED` having never reached `RUNNING` — i.e. no model process
was ever launched — does not consume the per-revision ceiling; every other disposition, including
`FAILED` and `QUARANTINED` from preflight failure, does. This preserves R-02's anti-gaming intent
exactly (no deterministic failure path is cheapened, because preflight failure closes `FAILED`/
`QUARANTINED`, not `CANCELLED`/`FENCED`). If instead the current behaviour is intended, say so
explicitly and state the operator path, because it is not currently derivable.

**Exact acceptance/mechanical test required.**
- New matrix row **ST-16**: restart the controller three times with the task `ASSIGNED` and its
  attempt `CREATED`; the fourth `attempt.assign` is still admitted, and the persisted attempt count
  reflects the chosen rule after restart, DB restore and epoch change.
- Extend **PR-10** so the ceiling drive-down asserts which dispositions consume budget, rather than
  only that the counter persists.

### G-03 — HIGH — a delivery interrupted by a controller crash stays `PENDING` and may be republished without reconciliation

**Files/sections:** `ORCHESTRATOR_V1_STATE_API.md` §3C (rows 2 and 3) and §4 (the two-phase durable
record, final line); `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §21 step 10 and §9.

**Failure path.** §3C's anti-replay guard is attached to `UNKNOWN` and only to `UNKNOWN`:
*"PENDING → UNKNOWN … blind replay forbidden; reconciliation required"*. §4 says *"**Timeout**
between steps 2 and 4 produces `UNKNOWN` delivery/effect state and requires reconciliation before
retry"* — but a timeout presupposes a live controller that can perform the write.

A controller **crash** between §4 step 2 (perform effect) and step 4 (persist observed outcome)
cannot write `UNKNOWN`. The record is left in `PENDING`, and — because §3C step 1 persists intent
*before* the effect and nothing marks that the effect was initiated — `PENDING` is indistinguishable
between *"intent persisted, nothing sent"* and *"sent, outcome unobserved"*. The `delivery` record
does carry an `attempt count`, but no §3C row requires it to be incremented pre-effect.

On restart, `PENDING --delivery.publish observes exact expected remote identity--> PUBLISHED` **is a
listed §3C edge with no reconciliation precondition**, so re-invoking `delivery.publish` on that
record is legal. Freeze contract §21 step 10 reconciles *"ambiguous remote publications"*, and the
freeze set's own vocabulary makes `UNKNOWN` the ambiguous state, so a `PENDING` record is not clearly
in scope for that step either.

Consequence: a duplicate external publication after a crash — precisely what freeze contract §9
prohibits (*"Blind replay after ambiguous success is forbidden"*) and precisely the hazard §3C's
`UNKNOWN` state exists to prevent. The idempotency key mitigates this only for remotes that
deduplicate, which is the assumption `UNKNOWN` was introduced because we cannot make.

**Smallest bounded repair.** Two clauses:
1. require the pre-effect transaction (§3C row 1 / §4 step 1) to persist an *effect-initiated* marker
   — incrementing the existing `attempt count` is sufficient, no schema change needed; and
2. add one §3C row: `PENDING --restart/epoch-change reconciliation where the effect may have been
   initiated--> UNKNOWN`, and name `PENDING`-with-initiated-effect explicitly in freeze contract §21
   step 10.

**Exact acceptance/mechanical test required.**
- New matrix row **DL-06**: crash the controller between the external effect and outcome
  persistence; on restart the delivery is `UNKNOWN`, `delivery.publish` is refused until
  `delivery.reconcile` observes authoritative remote truth, and no second external effect occurs.
- Structural test: assert every §3C From-state from which a further external effect can be initiated
  is either terminal or carries an explicit reconciliation precondition.

---

## 6. Regression search — what I tried to break and could not

| Attack | Result |
| --- | --- |
| joint-oracle contradiction on the TASK `attempt.start` path (mirror of F-01) | **Not a defect** — analysed in §4 above; the intersection rule binds only when a command changes both records, and TASK phase 1 changes attempt state only |
| cancellation races in `CREATED`/`STARTING`/`RUNNING`/`CANDIDATE_READY` | attempt layer fully covered; `RUNNING`/`CANDIDATE_READY` unchanged and still sound; `CREATED`/`STARTING` now covered — the subject-layer hole is G-01 |
| `integration.begin`/`integration.start` triple enumeration vs the tables | every triple ST-11 names is present as an actual row |
| delivery command/state left unrepresented | none — all 3 commands, all 5 states, independently recomputed |
| delivery state reachable only as a From-state | none |
| impossible or unjournalled record state | none found; §3C mandates a `DELIVERY` event per transition, and the R-03 NULL-fencing-token representation is intact |
| attempt-ceiling bypass after BLOCKED/ESCALATED/rejection/restart/restore | no bypass — the guard is on all three allocation paths. The defect is the opposite polarity: over-counting (G-02) |
| durable attempt-count derivation vs persistence | satisfies persistence correctly: derived from durable rows keyed on `(subject_kind, subject_id, subject_revision)`, not an in-memory counter |
| restart reconciliation across allocated-but-not-started attempts | **this is where G-01 and G-03 came from** |
| reviewer dispatch fencing / stale verdict admission | §3B untouched; `FENCE_STALE` still `REJECTED_FAILED`; §1A rule that cancellation/expiry/replacement strip authority *"even when the subject SHA has not changed"* intact |
| malformed §18A rows / dangling test IDs / MUST-bearing section with no disposition | none — independently recomputed, 0 dangling, 0 uncovered |
| structural-test helper/parser, regex/section parsing, false-green | parser is sound (see below); two false-green vectors in how it is *used* — Observation O-3 |
| regression of N-01..N-04, B-01..B-05, R-01..R-03 | none. All guards present and green; one weakening noted as O-4 |
| self-adoption / DEC-046 / DEC-047 sequencing change | none — `DECISIONS.md`, `CURRENT_TRUTH.md` and `ROADMAP.md` are byte-identical to `e944620`; the anti-self-adoption test still passes |

**On the parser itself** (`table_rows_in_numbered_section`, whose regex escaping was the subject of
the final commit `31b0e07`): I audited it directly rather than trusting it. `^##\s+<section>(?:\.|\s)`
correctly distinguishes `## 3.` from `## 3A.` — the character after `3` must be a dot or whitespace,
and `A` is neither. The `^##\s` break condition correctly stops at the next `##` heading while *not*
stopping at `###` subsections (since `#` is not `\s`), which is required for the `### \`delivery\``
lookup elsewhere in the same test. Header/separator rows are filtered on `cells[0] in {"From", "---"}`,
which is correct for §3/§3A/§3C but *not* for §2 (whose header cell is `Command`, so the header row
is returned as data) — harmless there only because the caller filters on a `` `delivery. `` prefix.
The parser is sound; it is the assertions built on it that are weak.

---

## 7. Non-blocking observations

**O-1 — §2 grants `delivery.reconcile` an edge §3C does not.** §2 says `delivery.reconcile` may move
a delivery *"to PUBLISHED, FAILED or BLOCKED only through §3C"*, but §3C grants `BLOCKED` solely via
`delivery.block`. It fails closed because §2 defers to §3C explicitly, so it is a wording mismatch
rather than an unsafe permission — but it is the same shape as F-01 and should be tidied in the same
pass.

**O-2 — the three central transition matrices escape the §18A coverage gate.** §3, §3B and §3C
contain no RFC-2119 `MUST`, so `must_bearing_sections()` does not see them and §18A carries no row
for any of the three. The gate is internally honest, but the state API's most normative content is
dispositioned only indirectly — DL-01..DL-05 are hung off `FC §7` rather than `SA §3C`. Not a
regression (§3 was already in this position before the repair), and F-02 did not make it worse, but
it means "every MUST-bearing section is covered" is a weaker claim than it sounds.

**O-3 — the new F-03 test is weaker than its name.** In
`test_every_nonterminal_attempt_state_has_a_terminal_fencing_or_cleanup_edge`, the loop accepts *any*
row whose To-cell contains `CLOSED`. `STARTING` therefore passes on the pre-existing preflight-failure
row alone and `CANDIDATE_READY` on its `CLOSED / SUCCEEDED` row alone — neither of which is a
fencing or cleanup edge. Only `CREATED` is genuinely guarded by the loop. The actual protection for
F-03 comes from three brittle literal-substring asserts, which will silently stop protecting anything
if the table is reworded. Deriving the check (e.g. requiring a terminal edge whose trigger names a
cancellation/fencing event) would make it real.

**O-4 — the R-01 guard lost two assertions.** Rewriting `test_integration_launch_is_split_into_
allocation_then_preflight` for F-01 dropped its asserts on `integration CREATED | integration.cancel
| integration CANCELLED` and *"no fictitious execution record to fence"*. Both strings are still
present in the candidate's §3 and §2 — I verified this directly — so nothing is currently broken, but
that part of R-01 is no longer mechanically protected.

**O-5 — delivery has no bounded retry budget.** The `delivery` record carries an `attempt count`, but
no §3C row consumes or bounds it, and there is no delivery analogue of §10.2/§10.3.1. A delivery can
in principle be retried within `PENDING` without limit. Related to G-03 but separable.

---

## 8. OWNER-PENDING (not engineering defects)

- **Exact freeze adoption / any DEC-046 sequencing amendment.** The contract still fails closed
  correctly: *"This specification is a candidate until the Owner adopts an exact candidate SHA"*,
  and `DECISIONS.md` contains no reference to `orchestrator-v1-freeze-candidate`. The
  anti-self-adoption test passes. **No approval is recorded or implied by this round.**

## 9. RUNTIME-PENDING (measured only, not remediated, per inbox scope)

- **Live watcher/builder branch mismatch.** Measured: `/opt/crooks-builder` is on
  `claude/builder-environment-repair` at `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, not
  `claude/bridge-builder`. Unchanged by this round.
- **Stale Builder fetch refspec.** Confirmed still stale — `remote.origin.fetch` names a deleted
  remote, so both candidate and base had to be fetched explicitly by branch name. Not repaired ad
  hoc, per `CURRENT_TRUTH.md`'s standing instruction.
- **Inherited business MCP connector surface.** This session again inherited Shopify, Gmail, Resend,
  Omnisend, Google Drive and Wix/Base44 connector tools. **None was invoked.** No live Shopify, Gmail
  or ElevenLabs call and no external mutation occurred in this round.
- Several MCP servers require OAuth that cannot be completed in a non-interactive session, and
  `plugin:marketing:similarweb` failed to connect. Neither affects this round.

---

## 10. State of the machine at end of round

**Builder worktree `/opt/crooks-builder`**
- branch `claude/builder-environment-repair`, HEAD `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`
- `git status --porcelain`: **empty (clean)** — verified at start and at end of round
- files changed by me in this repository: **none**. No commit, no push, no branch switch, no
  reset/clean/stash. The only Git operations performed were `fetch`, `rev-parse`, `merge-base`,
  `log`, `diff`, `show`, `ls-tree`, `ls-remote` and `status`.

**Production checkout `/opt/crooks-os/crooks-assistant` — read only, never touched**
- branch `claude/linux-prod-migration-production`
- HEAD `1cf3a0f3361b79f9de208d80f501543c53c244b5`
- working tree clean
- note: `git ls-remote origin refs/heads/claude/linux-prod-migration-production` returned **no ref**,
  i.e. the production branch appears to exist locally only and is not published on `origin`. There is
  also no `refs/heads/main` on `origin`. Reported as measured, not remediated.

**Bridge worktree `/opt/crooks-ai-bridge`**
- branch `crooks-ai-bridge`; the only file I modified is `bridge/claude-outbox.md` (this file).
  Nothing was staged, committed or pushed — the watcher publishes.

**Services**
- `crooks-assistant.service` — active (running), FastAPI backend
- `crooks-bridge-watcher.service` — active (running)
- listener: `127.0.0.1:8000` only. Port 8000 is **not** exposed publicly. ✔

**Safety constraints — all preserved and unchanged by this round**
`writes_enabled` false; `CROOKS_WRITES_LOCAL_OWNER` false; FastAPI bound to 127.0.0.1; port 8000 not
public; proposal/action/verification semantics untouched; no live Shopify/Gmail/ElevenLabs calls and
no external mutations; V2 not begun; UI not redesigned; Mac deployment and rollback path preserved;
`/root/.claude` writable; no secret value printed or committed.

**Errors:** none. The spec suite ran clean (26/26) and no command failed.

**Permission-layer blocks:** none. Nothing the inbox asked for was refused by my permission layer,
and I did not widen permissions or route around anything.

---

## 11. Reviewer-independence limitation (recorded explicitly, as required)

I am Claude (`claude-opus-5`), the **same model family and the same provider** as the author of the
F-01/F-02/F-03 repairs under review. This is a genuine independence limitation: shared inductive
biases mean a defect class that this model family is systematically blind to would likely survive
both the repair and this review. Two partial mitigations applied in this round: every structural
claim was recomputed with my own script rather than accepted from the candidate's own test suite, and
all three findings were reached by attacking the *composition* of the repairs with the untouched
documents (freeze contract §21, §10.3.1, §9) rather than by re-reading the repaired text alone. Those
mitigations reduce the risk; they do not make this an independent review in the sense the freeze
acceptance rule intends. A genuinely independent reviewer — different provider, or a human — remains
warranted before adoption.

---

## 12. Questions / decisions needing review

1. **G-02 polarity is a design question, not only a defect.** Is a controller-restart-induced fence of
   a never-started attempt *intended* to consume the per-revision ceiling? I have assumed not and
   proposed the exclusion accordingly. If the owner intends the strict reading, the repair is to say
   so explicitly plus state the operator recovery path — the current text is simply silent, and that
   silence is the defect either way.
2. **G-03's repair touches the freeze contract**, which the last two repair rounds left untouched.
   Confirm that amending `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §21 is in scope for the next repair
   round, or the delivery crash window cannot be closed properly.
3. **O-2** — should §3/§3B/§3C be given RFC-2119 `MUST` phrasing so the §18A gate actually reaches
   the state API's transition matrices? This is a small edit with a real increase in gate coverage,
   but it enlarges the MUST-bearing set and so requires §18A rows for all three.

---

## 13. Exact proposed next step

**One bounded repair round on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, branching from
`31b0e07179877651da80065f5914575ee4d60d6c`, fixing exactly G-01, G-02 and G-03 and nothing else:**

1. **G-01** — add `ASSIGNED` to the ambiguity enumeration in `ORCHESTRATOR_V1_STATE_API.md` §1A
   bullet 2 and in `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §21's closing sentence. Add matrix row
   **ST-15** and a *derived* structural test that recomputes, from §3A, every subject state which can
   hold a non-terminal execution record and asserts each appears in both enumerations.
2. **G-02** — add the ceiling-exclusion clause to `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §10.3.1 and
   mirror it in the §3A ceiling paragraph. Add matrix row **ST-16** and extend **PR-10** to assert
   which dispositions consume budget.
3. **G-03** — require an effect-initiated marker in the §3C/§4 pre-effect transaction; add the §3C
   row `PENDING -> UNKNOWN` on restart-with-possibly-initiated-effect; name `PENDING` explicitly in
   freeze contract §21 step 10. Add matrix row **DL-06**.
4. Optionally fold in **O-1** (the `delivery.reconcile` §2/§3C wording mismatch) and **O-3**
   (strengthen the F-03 test from literal substrings to a derived check) — both are one-line-class
   edits in the same files and both were found by this review.
5. Add `G-01`, `G-02`, `G-03` rows to `ORCHESTRATOR_V1_TRACEABILITY.md`; the existing
   `test_traceability_dispositions_every_reviewed_finding` must be extended to require them, or
   silence will again pass as a disposition.
6. Do **not** touch `DECISIONS.md`, `CURRENT_TRUTH.md` or `ROADMAP.md`; the anti-self-adoption gate
   must stay green.
7. Publish the new candidate SHA and send a fresh inbox naming it, the base `9e59860a`, and
   `31b0e071` as the last-reviewed SHA, for a fourth independent read-only review.

**Not proposed, and explicitly awaiting the owner:** freeze adoption, any DEC-046 sequencing
amendment, any merge to a production branch, any deployment, and any of the three RUNTIME-PENDING
remediations. This round performed none of them and records no approval that was not given.

---

**Inbox SHA processed:** `836d2e795cea0b10478bd92fc89d3c920e3213b5`
**Candidate reviewed:** `31b0e07179877651da80065f5914575ee4d60d6c`
**Canonical base:** `9e59860a945ec339c69af8709cd0721f0a795327`
**Verdict:** `CHANGES REQUIRED BEFORE OWNER DECISION`
