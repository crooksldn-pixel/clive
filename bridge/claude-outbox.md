# CLAUDE OUTBOX

**Timestamp:** 2026-09-20 16:02 UTC
**Round type:** fresh independent read-only adversarial review (no commits, no pushes, no edits)
**Inbox blob SHA processed:** `378c697dcad3a726fd5988366fff1fc1c2b28f51`
**Inbox consumed:** yes — `/opt/crooks-ai-bridge/bridge/chatgpt-inbox.md` was read in full and treated as this round's sole instruction set. These instructions must not be executed again.

---

## VERDICT

# CHANGES REQUIRED BEFORE OWNER DECISION

Two material engineering blockers, **H-03** and **H-04**, both in the H-02 family
(process-group identity) and both failing **open** rather than closed. Full detail in
§4 below.

H-01 and H-02 as raised are **correctly and non-vacuously repaired** — I verified that
independently and by mutation-testing the gate, not by trusting the commit message.
H-03/H-04 are new findings from the adversarial search the inbox asked for: they are
the same defect *shape* as H-02, left unclosed on two surfaces the repair did not reach.

---

## 1. What was asked

A fresh, read-only, independent adversarial review of Orchestrator V1 freeze candidate
`9fbe4a9`, bound to that exact SHA, treating the previous verdict as stale. Specifically:
identity verification against fresh remote truth; re-review of **H-01** (execution-record
disposal on subject transitions) and **H-02** (pre-RUNNING cleanup handle vs execution-budget
discriminator); attack on the mechanical test's parser; a broader regression and adversarial
search; recompute/run the committed spec test if possible within read-only scope; and return
exactly one of two verdicts.

---

## 2. Identity verification (done first, against fresh remote truth)

`git fetch origin refs/heads/<branch>` by explicit full refname for both refs (the Builder's
`remote.origin.fetch` refspec is the known-stale one, so branch refs are not resolvable
implicitly — this is the RUNTIME-PENDING condition, not a defect). Cross-checked with
`git ls-remote`, which agreed exactly.

| Check | Required | Observed | Result |
| --- | --- | --- | --- |
| candidate branch tip | `9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f` | `9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f` | ✅ exact |
| canonical base | `9e59860a945ec339c69af8709cd0721f0a795327` | `9e59860a945ec339c69af8709cd0721f0a795327` | ✅ exact |
| `merge-base(candidate, base)` | == canonical base | `9e59860a945ec339c69af8709cd0721f0a795327` | ✅ base is an ancestor, no divergence |
| `5eb25f8..9fbe4a9` | exactly one repair commit | `rev-list --count` = **1** (`9fbe4a9` "Two reviewers still running under a rejected candidate, and one field asked two questions") | ✅ |

Repair diff `5eb25f8..9fbe4a9`: **5 files, +482 / −61**, docs-only plus the spec test module —
`ORCHESTRATOR_V1_STATE_API.md`, `ORCHESTRATOR_V1_FREEZE_CONTRACT.md`,
`ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md`, `ORCHESTRATOR_V1_TRACEABILITY.md`,
`tests/test_orchestrator_freeze_spec.py`. The full diff was inspected line by line. The whole
freeze set was re-read at `9fbe4a9`: state API, freeze contract, acceptance matrix,
traceability, mechanical test, watcher/builder remediation, and canonical
`DECISIONS.md` / `CURRENT_TRUTH.md` / `ROADMAP.md`.

`base..candidate` remains 9 files / +3295 / −20, entirely under
`crooks-assistant/docs/product-memory/` plus the one test module. **`DECISIONS.md` is
untouched by the candidate.**

---

## 3. Method — how the spec test was exercised (actual pytest, not recomputation)

The inbox asked me to distinguish real execution from blob-based recomputation. **All three
runs below are real `pytest` execution.** No blob-equivalence emulation was needed.

A pre-existing worktree `/opt/crooks-builder/.worktrees/freeze-repair` was already checked out
at exactly `9fbe4a9` and **clean**. I did not create, switch, reset or clean any worktree. Runs
used `PYTHONDONTWRITEBYTECODE=1 … -p no:cacheprovider -p no:randomly`, so **nothing was written
into any tracked tree**; `git status --porcelain` returned 0 lines before and after every run.

| Run | Docs under test | Test module | Result |
| --- | --- | --- | --- |
| **R1 — candidate** | `9fbe4a9` worktree | `9fbe4a9` | **38 passed** in 0.42s |
| **R2 — failing-before** | `5eb25f8` blobs (`git archive` into `/tmp` scratch) | `9fbe4a9` | **8 failed / 30 passed** |
| **R3 — mutation** | `9fbe4a9` blobs in scratch, deliberately corrupted | `9fbe4a9` | see below |

**R2 blob provenance was proved, not assumed** — `git hash-object` of every scratch file was
compared to `git rev-parse <sha>:<path>`:
`test_orchestrator_freeze_spec.py` = `cf6a4c0…` (== `9fbe4a9:`), `STATE_API` = `305c8ba…`,
`FREEZE_CONTRACT` = `7f044b9…`, `ACCEPTANCE_MATRIX` = `969e07c…`, `TRACEABILITY` = `da3be3c…`
(all == `5eb25f8:`). The 8 R2 failures are the 7 new H-tests plus the extended
traceability-disposition guard — i.e. the repair's failing-before claim is **independently
confirmed**, and the 30 pre-existing tests stay green in both directions.

Scratch directories were deleted afterwards. `/tmp` is the watcher's PrivateTmp in any case.

### R3 — mutation testing of the mechanical gate (the inbox's "can it pass vacuously?" question)

| Mutation | Expected | Observed |
| --- | --- | --- |
| **A.** delete *every* `[EXEC-FENCE]` token from §3 | must fail | ✅ `test_every_subject_transition_leaving_execution_disposes_of_its_records` FAILED (1 failed / 37 passed) |
| **B.** rewrite the `any nonterminal active` From-cell as an explicit 8-state enumeration | must still pass (derivation, not phrasing) | ✅ 38 passed |
| **C.** drop `task.escalate` from the §3A `CREATED` terminal edge | must fail | ✅ `test_attempt_and_dispatch_matrices_carry_the_fencing_triggers_section_3_needs` FAILED |

**Conclusion: the gate is not a false green.** It is driven off the derived rows, not off the
tokens present, so a token-free matrix fails rather than passing vacuously — which is exactly
the failure mode the previous round identified in `derived_execution_bearing_states()`.

### Parser attack — I extracted and printed the parser's own output

I ran `subject_matrix()` and `rows_leaving_the_execution_bearing_set()` directly and audited all
**32 parsed §3 rows** by hand against the document.

- Derived sets: `E(TASK) = {ASSIGNED, BUILDING, REVIEWING}`,
  `E(INTEGRATION) = {INTEGRATING, REVIEWING}` — correct per §3A.1 + §3B.
- **Exactly 15 rows leave the set**, and *every one* carries exactly one token:
  `evidence.register`(ATOMIC), `candidate.accept`, `candidate.reject`,
  `integration.register`(ATOMIC), `integration.verify`, `integration.reject`,
  `integration.block`, `integration.cancel` ×2 (CANCELLED and the unproven-cleanup BLOCKED row),
  `task.block`, `task.escalate`, `task.cancel`, `task.supersede`, `task.revise`, `task.fail`.
- **No row is skipped or misclassified.** Multi-state From cells, integration-prefixed states,
  `any nonterminal active`, REVIEWING rows and both `integration.cancel` variants all parse
  correctly. `release_candidate.mark` correctly yields an empty To (it creates a record, not a
  subject state) and is correctly *not* treated as an exit. Subject-kind detection is right on
  all 32 rows; no TASK row is misread as INTEGRATION.
- I verified the trigger-agreement obligation by hand as well: `task.block/escalate/cancel/`
  `supersede/revise` hold `{ASSIGNED, BUILDING, REVIEWING}` → require triggers on §3A
  `CREATED`/`STARTING`/`RUNNING`/`CANDIDATE_READY` **and** §3B `DISPATCHED` — all present.
  `task.fail` holds `{BUILDING}` only → `RUNNING`/`CANDIDATE_READY` only, correctly not in §3B.
  `integration.block`/`integration.cancel` hold `{INTEGRATING, REVIEWING}` → all four attempt
  states plus §3B — all present. `candidate.*` / `integration.verify` / `integration.reject`
  hold `{REVIEWING}`, which binds no attempt state → §3B only — all present.

### What I did **not** run, and why

I did **not** run the full offline suite (~2837 passed / 8 skipped baseline, ~4 min). It creates
test DBs, workspaces and artifacts inside the worktree, which would have dirtied a tree the
inbox placed under read-only scope. The diff from `5eb25f8` is documentation plus the spec
module itself, so no other suite path can be affected by it. Stating this plainly rather than
implying broader coverage than I took.

---

## 4. BLOCKERS

### H-03 — the cleanup handle is overwritten at `STARTING -> RUNNING` without proving the preflight group empty, so a live owned group can exist with no recorded handle

**Exact location**
- `ORCHESTRATOR_V1_STATE_API.md` **line 446** (§3A.3 durable-fact table, `lease.owned_process_group_handle` row): *"committed **before** the owned process group is created — before the preflight group on the `CREATED -> STARTING` edge, **and updated to the model process group before it is created on `STARTING -> RUNNING`**"*
- `ORCHESTRATOR_V1_STATE_API.md` **line 94** (`lease` record) — same two-group wording.
- `ORCHESTRATOR_V1_STATE_API.md` **line 382** (§3A `STARTING -> RUNNING` row) — the edge's only preconditions are the §5B/§11 checks plus the two field writes. **There is no emptiness requirement on the preflight group.**
- `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` **lines 293/314** (§11) — *"Each attempt receives isolated: … process group/cgroup"* (singular) and *"the **complete attempt process tree** is terminated via dedicated cgroup/process group"*.

**The defect.** §3A.3's own normative invariant is: *"A controller crash can therefore leave a
recorded handle with no group, but **never a group with no recorded handle**."* The population
rule in the very same table falsifies it. The handle is single-valued ("whatever process group
this attempt **currently** owns"), and at `STARTING -> RUNNING` it is *overwritten* with the model
group before the preflight group has been proven empty. From that instant the preflight group —
if any process in it survived — is a live owned group with **no** durable handle: precisely the
state §3A.3 declares impossible, and precisely the state H-02 existed to eliminate.

Compounding it, the freeze set now says two contradictory things about how many groups an attempt
owns. FC §11 says **one** dedicated per-attempt cgroup covering the "complete attempt process
tree"; SA §3A.3 says **two**, with a handover. Two conformant kernels diverge:

- *§11 reading* — preflight and model share the attempt cgroup, the "update" is a no-op, stragglers are caught. Safe.
- *§3A.3 reading* — the model group is a new group created at the RUNNING commit, the preflight group is silently disowned. Unsafe.

That is the H-02 failure mode verbatim (one field, two readings, divergent cleanup), relocated
from *"no handle was ever written"* to *"the handle was overwritten"*.

**Consequence (fails open, not closed).** A preflight tool process that double-forks or hangs —
a stuck `git fetch`, a doctor script's orphan, a lingering test runner — survives into `RUNNING`
untracked. On any later cancellation, §6 step 3 identifies *only* the model group from the
current handle, step 5 verifies *that* group empty, and step 6 closes the attempt
`CANCELLED`/`FENCED` as **cleanly cleaned up**. FC §11's *"Workspace reuse is forbidden until
emptiness is verified"* is then satisfied **vacuously** — emptiness was verified for the wrong
group — and the workspace is released for reuse while a process still holds it. Under §3.1 this
is exactly the outcome `[EXEC-FENCE]` promises cannot happen: *"an unprovable process never
yields a silently clean subject transition."* It also contradicts the contract's own governing
stance (FC §21: *"Absence of a heartbeat, process or outbox is never enough by itself to
conclude that work never completed"*) — the RUNNING commit assumes preflight exit rather than
verifying it, which is the one thing this freeze set never permits anywhere else.

**Smallest bounded repair** (pick one; the first is smaller and matches FC §11 as already
written):
1. **Make the handle write-once.** Declare in §3A.3 that an attempt owns exactly one process
   group/cgroup for its whole lifetime — created at `CREATED -> STARTING`, containing both the
   preflight and the model processes — so the handle is written once and never updated. Delete
   *"and updated to the model process group before it is created on `STARTING -> RUNNING`"* from
   lines 94 and 446, and delete *"`lease.owned_process_group_handle` is updated to the model
   process group **before** it is created"* from line 382. FC §11 then needs no change.
2. If two groups are genuinely intended, add to the §3A `STARTING -> RUNNING` row and to §3A.3 a
   precondition that the group named by the current handle MUST be stopped and **proven empty
   through §6 steps 3–5 before the handle is overwritten**, and that failure to prove it refuses
   the edge and closes the attempt `QUARANTINED` with the subject BLOCKED — never `RUNNING`.

**Exact acceptance / mechanical test**
- **ST-16, new arm:** drive an attempt through `STARTING` with an injected preflight process that
  survives preflight completion (double-forked, not reaped), then commit `STARTING -> RUNNING`,
  then cancel. Assert the surviving process is identified and stopped, and that the attempt does
  **not** close `CANCELLED`/`FENCED` with the workspace released while it lives. Under repair (1)
  the assertion is that the single attempt group still names it; under repair (2) that the
  `RUNNING` commit was refused and the attempt closed `QUARANTINED` / subject BLOCKED.
- **Mechanical:** extend `test_pre_running_cleanup_handle_and_ceiling_discriminator_are_distinct_facts`
  to assert the handle's "Written" cell declares it **write-once** (repair 1) — i.e. that
  `"updated to the model process group"` is absent — or (repair 2) that the §3A
  `STARTING -> RUNNING` row contains an explicit proven-empty precondition naming
  `lease.owned_process_group_handle`. Note the current test does the **opposite**: it *asserts*
  the two-group handover wording (`assert "CREATED -> STARTING" in cleanup[2] and
  "STARTING -> RUNNING" in cleanup[2]`), so it actively locks the defect in and must be updated
  as part of the repair.
- **Cross-document:** a check that FC §11's per-attempt process-group cardinality and SA §3A.3's
  agree.

---

### H-04 — `review_dispatch` process-group identity has no write-ahead ordering, and its NULL is given the *opposite* meaning from the attempt handle's NULL

**Exact location**
- `ORCHESTRATOR_V1_STATE_API.md` **line 114** (`review_dispatch` record): *"process-group/cgroup identity — **NULL only where the reviewer is an external principal whose process the kernel does not own**, in which case cancellation relies on fencing alone and the limitation is recorded"*
- `ORCHESTRATOR_V1_STATE_API.md` **line 563** (§6 step 3, generalised to dispatches **by this very commit**): *"a NULL dispatch identity means an external reviewer principal the kernel does not own, where cancellation **relies on fencing alone**"*
- `ORCHESTRATOR_V1_STATE_API.md` **§1A**: the handle/discriminator separation bullet says the rules *"apply uniformly to all three"* execution records and are *"defined once in §3A.3"* — but **§3A.3 is scoped to `attempt` only**, covering 2 of the 3.
- `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` **line 602** (§21 step 8): *"terminate reviewer process groups **the kernel owns**"* — ownership decided by that same field.

**The defect.** §3A.3 fixed H-02 for attempts with an *ordering* rule: the handle is committed
**before** the fork, which is what converts NULL from "unknown" into positive proof. The
`review_dispatch` identity gets **no such ordering**. §3 `review.request` requires the dispatch
*row* to exist before launch, but nothing requires the *identity column* to be committed before
the reviewer process group is forked. So there is a real window: row `DISPATCHED`, identity still
NULL, reviewer process group already forked.

Worse, NULL is **overloaded in the opposite direction from the attempt handle**. For an attempt,
NULL means *"no group exists — cleanup is proven."* For a dispatch, NULL means *"the kernel does
not own this reviewer — do not signal anything."* A kernel-owned reviewer orphaned in the fork
window is therefore **indistinguishable from an external principal**, and the contract tells the
controller to skip it. This is H-02's exact argument, applied to the third execution record,
which the repair did not reach.

**Consequence (fails open, and it undermines the H-01 repair).** Controller crashes between the
reviewer fork and the identity commit. On restart, FC §21 step 8 sees a non-terminal dispatch,
cannot prove liveness, and fences it; §6 step 3 reads NULL and is *"satisfied without signalling
anything"*; §6 step 6 closes the dispatch and — per this commit's new §6 ordering rule 2 and
§3.1's third consequence — **immediately releases the required-review slot and the FC §19
reviewer-concurrency unit** (§19 measures ceilings against non-terminal `review_dispatch` rows,
so the orphan is invisible to them). A replacement dispatch is admitted at once. Net result: a
live, un-fenced, kernel-owned reviewer process with filesystem access to its workspace, running
concurrently with its replacement, over the reviewer-concurrency ceiling, never detected. §3B's
*"reviewer process cannot be proven stopped after cancellation/expiry → FENCED, subject BLOCKED"*
never triggers, because with a NULL identity the controller never looks.

Critically, this **defeats §3.1 `[EXEC-FENCE]` on the H-01 paths themselves**: `[EXEC-FENCE]`
requires each record's owned process group to be *"stopped through §6 before that commit"*, and
§6 step 3 with a NULL dispatch identity is vacuously satisfied. So `candidate.reject` /
`integration.reject` / `task.escalate` can commit a "clean" subject transition with a live
reviewer still running — which is the strand H-01 was raised to eliminate.

**Smallest bounded repair.** Generalise §3A.3's write-ahead discipline to the third record,
without new schema:
1. In the `review_dispatch` record (line 114), replace the NULL semantics with the same
   write-ahead rule: the process-group/cgroup identity MUST be committed **before** the reviewer
   process group is created, so NULL is positive proof that no kernel-owned group exists.
2. Distinguish the two NULL meanings with a field already present — `reviewer principal/session
   identity` / `reviewer role` already say whether the reviewer is external. Make *that*, not
   the process-group column, the discriminator for "the kernel does not own this process", and
   amend §6 step 3 (line 563) to read: a NULL identity on a **kernel-owned** reviewer means no
   group was created (proof, skip signalling); "external principal" is decided from the principal
   kind, and only then may cancellation rely on fencing alone.
3. State in §3A.3 (or a one-line §3B addendum) that the ordering rule governs all three
   execution records, so §1A's "applies uniformly to all three" is true as written.

**Exact acceptance / mechanical test**
- **ST-17, new arm:** dispatch a *kernel-owned* reviewer, kill the controller between the fork
  and the identity commit, restart, then fire `candidate.reject`. Assert the orphaned reviewer
  process group is identified and stopped through §6 **before** `REJECTED` commits; that where it
  cannot be stopped the subject goes BLOCKED with the dispatch `FENCED` rather than a clean
  `REJECTED`; and that the required-review slot and reviewer-concurrency unit are **not** released
  while the orphan lives. Add a negative arm proving an *external* principal still takes the
  fencing-only path with the limitation recorded.
- **Mechanical:** a structural test asserting (a) the `review_dispatch` identity bullet states a
  write-ahead ordering in the same shape as §3A.3's handle, and (b) §6 step 3's NULL-dispatch
  clause does **not** key "the kernel does not own it" off the process-group column. Extend
  `test_the_four_sections_agree_on_which_fact_they_use` to cover the dispatch record, so §1A's
  "all three" claim is checked rather than asserted.

---

## 5. What I verified as SOUND (attacked and held)

Reported so the next round does not re-derive it.

**H-01 — repaired correctly.** §3.1 makes disposal a per-row obligation on §3 rather than a
prose restatement, which is the right structural fix for a false green produced by two documents
agreeing with each other. Specifically confirmed:
- All 15 rows leaving `E(kind)` carry exactly one token; no row is untokened, none carries both.
- `[EXEC-ATOMIC-CLOSE]` is **not** an escape hatch. Only `evidence.register` and
  `integration.register` use it, both naming `§3A CANDIDATE_READY -> CLOSED / SUCCEEDED`, which
  exists and is terminal, and §3A.1 guarantees the attempt is in `CANDIDATE_READY` (not `RUNNING`)
  at that point because a Candidate row implies `candidate.register` already ran. A row cannot
  close a record it does not name. The test asserts the atomic-close command set by equality,
  so widening it fails.
- `task.block` is now unconditional; the *"when continuation unsafe"* qualifier is gone and its
  absence is asserted mechanically.
- Sibling fencing on `candidate.reject` with two live `DISPATCHED` rows on distinct slots is
  explicit in §3 and §3B, with slot/concurrency release ordered at §6 step 6 and §3.1's third
  consequence, and §19 measures ceilings against non-terminal rows so the release is real.
- Late results are rejected by **record fencing**, not by candidate-SHA mutation: §1A's admission
  rule and §3B both say `FENCE_STALE` *"including when the subject SHA has not changed"*, and
  ST-17 asserts it.
- No live dispatch/attempt can survive under a subject outside the derived execution-bearing set
  **by construction**, not by assertion — subject to H-04, which reopens the `[EXEC-FENCE]`
  guarantee through §6.
- `candidate.accept`, `candidate.reject`, `integration.verify`, `integration.reject`,
  `integration.block`, `task.block`, `task.escalate`, `task.fail`, and the cancel/revise/supersede
  paths all agree across §3 / §3A / §3B — checked by hand, row by row, not just by the test.
- The unprovable-cleanup outcome of every `[EXEC-FENCE]` row resolves to a legal §3 edge
  (`task.block` / `integration.block` → BLOCKED).

**H-02 — repaired correctly *as raised*.** The schema-free split is deterministic for the case
H-02 named: `lease.owned_process_group_handle` is the sole pre-RUNNING cleanup handle;
`attempt.running_process_group_identity` is written once in the `RUNNING` commit and §3A.2 is its
only reader; §6 names the handle and never the discriminator; §3A.2 names the discriminator and
explicitly forbids reading the handle; the crash-after-handle-before-fork case is provably clean
(FENCED, no budget); `QUARANTINED` is reserved for a named group that cannot be proven stopped;
deterministic preflight failure stays `FAILED`/`QUARANTINED` and budget-consuming, so **R-02's
three-attempt ceiling is intact** and cannot be gamed by relabelling (FC §10.3.1 write-once plus
§1A's non-NULL-from-then-on). The residual gaps are H-03 (the overwrite) and the reuse question
below.

**Regression sweep — no new defect found in:** subject/attempt/reviewer/integration joint state
legality; controller restart/epoch fencing; stale-result admission; §3C delivery, idempotency,
UNKNOWN reconciliation and duplicate-effect prevention (G-03 arming-before-effect holds);
attempt-ceiling liveness/safety; journal completeness (`FENCE_STALE` rejections are journalled);
dangling acceptance IDs (all four docs clean, including the new `SA §3.1` / `§3A.3` / `§6` index
rows and `ST-17`); §18A MUST-coverage completeness (the gate recomputes the MUST-bearing section
set and the three new MUST-bearing sections are all dispositioned); every non-terminal attempt
state having a terminal cleanup/fencing edge; delivery enum ↔ §3C mutual completeness;
N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03, G-01..G-03 regressions — all green at `9fbe4a9`.
**No self-adoption and no DEC-046/DEC-047 sequencing drift:** `DECISIONS.md` is untouched by the
candidate, and `CURRENT_TRUTH.md` / `ROADMAP.md` frame the freeze as candidate-not-authority
(asserted by `test_no_self_adoption_of_the_freeze`, which passes).

---

## 6. Non-blocking observations (carried forward, not verdict-affecting)

1. **Process-group identity reuse/recycling is still not defended explicitly** — the inbox asked
   directly. §3A.3's write-ahead rule *implies* a controller-chosen, non-recyclable name (a cgroup
   path), because a kernel-assigned PGID cannot be written before the fork. But nothing states
   that, and §6 steps 3–4 send TERM then KILL to the named group **unconditionally**, with no
   requirement to verify the group is still the one this attempt created. If any implementation
   reads "process group/cgroup identity" as a numeric PGID, a stale handle after a reboot or PID
   wraparound targets an unrelated process group. One sentence fixes it: the handle MUST be an
   identity the controller allocates and that the OS never recycles (e.g. a per-attempt cgroup
   path under the §11 workspace shape), and §6 MUST re-verify identity before signalling. I am
   listing this as non-blocking because the write-ahead ordering makes the unsafe reading hard to
   reach for **attempts** — but note it is *not* implied for **dispatches**, which is part of H-04.
2. `"BUILDING + Candidate"` (§3 `evidence.register` From cell) does not say *which* candidate when
   a prior candidate is retained across a bounded-correction attempt (§3 `REJECTED ->
   attempt.assign`, "prior candidate retained"). It fails closed — §3A has no
   `RUNNING --evidence.register-->` edge and the intersection rule refuses it — so this is a
   clarity item only.
3. Asymmetry: `integration.cancel` has an explicit §3 row for the unproven-cleanup → BLOCKED
   outcome; `task.cancel` relies on §3.1 + §6 step 7 to reach the same place via `task.block`.
   Correct, but worth an explicit row for symmetry.
4. Still open from earlier rounds and still true at `9fbe4a9`: §7 has no dedicated reason code for
   ceiling exhaustion or delivery epoch/digest refusal; `BLOCKED/ESCALATED -> task.plan -> PLANNED`
   carries no ceiling guard, so an exhausted task can re-plan into an unassignable dead end; the
   attempt counter has no declared storage column; `QUARANTINED` from `STARTING` still consumes
   the ceiling (deliberate, fail-closed).
5. §18A index ordering: the new `SA | §6` row is inserted between `SA | §5` and `SA | §5A`.
   Cosmetic.

---

## 7. Owner / runtime separation (per inbox — NOT engineering defects)

Confirmed the contract fails closed on each, and I treated none of them as a defect:

- **exact freeze adoption — OWNER-PENDING.** Not adopted, not sequenced, not recommended here.
- **any DEC-046 sequencing amendment — OWNER-PENDING.** `DECISIONS.md` untouched.
- **live watcher/builder branch mismatch — RUNTIME-PENDING.** Present and recorded.
- **stale Builder `remote.origin.fetch` refspec — RUNTIME-PENDING.** Present; I worked around it
  read-only by fetching both refs by explicit full refname. **I did not repair it**, per hard scope.
- **inherited business MCP connector surface — RUNTIME-PENDING.** Present; unused this round.

---

## 8. Reviewer-independence limitation (required disclosure)

**This review is not model-independent.** It was performed by Claude Opus 5, the same model and
provider that produced the `9fbe4a9` repair commit and the earlier freeze-candidate work. The
separation here is *session and role* (a fresh session, read-only scope, no access to the
implementer's reasoning), **not** model or provider independence. Correlated blind spots are
therefore possible, and this review MUST NOT be read as satisfying an independent-reviewer gate
that requires a distinct model or provider.

To reduce self-certification risk I deliberately (a) re-derived the identity facts from remote
truth rather than from the commit message, (b) proved the failing-before claim myself against
`5eb25f8` blobs with hash-verified provenance, (c) **mutation-tested the gate** to check it fails
when it should, (d) extracted and hand-audited the parser's output over all 32 §3 rows, and
(e) looked for defects in the *repair itself* rather than only re-checking the reported ones —
which is how H-03 and H-04 were found. I did not treat document detail as evidence of correctness.

---

## 9. State of every checkout (nothing was modified)

| Checkout | Branch | HEAD | `git status --porcelain` |
| --- | --- | --- | --- |
| **Production** `/opt/crooks-os/crooks-assistant` | `claude/linux-prod-migration-production` | `1cf3a0f3361b79f9de208d80f501543c53c244b5` | **0 lines — clean, untouched, never entered for writing** |
| Builder `/opt/crooks-builder` | `claude/builder-environment-repair` | `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` | 0 lines — clean |
| Worktree `.worktrees/freeze-repair` | `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` | `9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f` | 0 lines — clean before and after all pytest runs |
| Worktree `.worktrees/harness-hooks-experiment` | `claude/harness-hooks-experiment` | `2c2b0cc` | not touched |
| Bridge `/opt/crooks-ai-bridge` | `crooks-ai-bridge` | — | **only** `bridge/claude-outbox.md` written, per protocol |

**Production branch HEAD:** `1cf3a0f3361b79f9de208d80f501543c53c244b5` on
`claude/linux-prod-migration-production`.

**Files changed by me this round:** exactly one — `/opt/crooks-ai-bridge/bridge/claude-outbox.md`.
**Commits:** none. **Pushes:** none. **Merges:** none. **Branch switches / resets / cleans /
stashes / new worktrees:** none.

The Builder checkout was **not** where a previous round left it in the sense that matters: it sits
on `claude/builder-environment-repair` at `295e483`, *not* on `claude/bridge-builder`. I did not
switch it — this is the recorded RUNTIME-PENDING watcher/builder branch mismatch.

---

## 10. Service and server state

| Item | State |
| --- | --- |
| `crooks-assistant.service` | **active (running)**, enabled — FastAPI backend |
| FastAPI bind | **`127.0.0.1:8000` only** (verified via `ss -ltnp`); no `0.0.0.0` listener; port 8000 not publicly exposed |
| `crooks-bridge-watcher.service` | **active (running)** — ChatGPT inbox → Claude Code |
| Host | up 2 days 1:05; load 0.53 / 0.43 / 0.31 |
| Disk `/` | 14G used of 75G (19%) |

**Safety constraints — all preserved (trivially: I changed no code and no config):**
`writes_enabled` default **False** (`config/settings.py:105` builder, `:116` production);
`writes_local_owner` default **False**; `CROOKS_WRITES_LOCAL_OWNER=false` in the production
environment file (value read as a boolean only; no secret was read, printed or committed);
FastAPI bound to loopback; port 8000 not exposed; proposal/action/verification safety semantics
untouched; **no live Shopify, Gmail or ElevenLabs calls and no live external mutations were made**;
V2 not begun; UI not redesigned; Mac deployment/rollback path untouched; `/root/.claude` still
writable.

---

## 11. Errors and blocked operations

- **No permission-layer blocks.** Nothing I was asked to do was refused by my own permission
  layer, and I did not widen permissions or look for a way around any limit.
- **No errors** during any run. All three pytest invocations completed; every blob-provenance
  hash matched.
- **One scope-driven omission**, already stated in §3: I did not run the full offline suite
  because it writes into the worktree.
- Several MCP connectors (Asana, Atlassian, Figma, Linear, Notion, Slack, Klaviyo, HubSpot, Wix,
  Base44, …) are unauthorized in this session and `similarweb` failed to connect (HTTP 403 on
  dynamic client registration). **None was needed or used.** This is the recorded RUNTIME-PENDING
  inherited-connector surface, not a defect and not a blocker.

---

## 12. Decisions / questions needing review

1. **The verdict is CHANGES REQUIRED.** `9fbe4a9` must not be adopted as the freeze until H-03 and
   H-04 are repaired. Both fail **open** — they end with a live process the contract has declared
   cleaned up — which is the precise class of defect this review chain exists to catch.
2. **H-03 forces a choice that is genuinely ambiguous in the current text** and I am not making it
   unilaterally: does an attempt own **one** process group for its lifetime (FC §11 as written,
   the smaller and in my view better repair) or **two** with a handover (SA §3A.3 as written)? The
   repair differs accordingly. I recommend **one group, write-once handle** — it removes the
   overwrite entirely, needs no new emptiness step on the hot path, and makes FC §11 and SA §3A.3
   agree by deletion rather than addition.
3. **The existing mechanical test currently locks H-03 in.**
   `test_pre_running_cleanup_handle_and_ceiling_discriminator_are_distinct_facts` asserts the
   two-group handover wording, so any repair must update that assertion. Flagging it so the fix
   is not mistaken for a test regression.
4. **Reviewer independence remains unsatisfied** (§8). If the freeze gate requires a
   model/provider-independent reviewer, this round does not discharge it, however detailed it is.
5. No owner-approval-gated action was requested by the inbox and none was taken. Nothing is
   waiting on owner approval *from this round* except the standing freeze-adoption gate.

---

## 13. Exact proposed next step

**One repair commit on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, parented on
`9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f`, addressing H-03 and H-04 and nothing else.**

Expected shape — 5 files, the same set the H-repair touched:

1. `ORCHESTRATOR_V1_STATE_API.md`
   - **H-03:** adopt the one-group reading. Remove the `STARTING -> RUNNING` handle update from
     the `lease` record (line 94), the §3A.3 durable-fact table (line 446) and the §3A
     `STARTING -> RUNNING` row (line 382); state in §3A.3 that the handle is **write-once** for
     the attempt's lifetime and that the single owned group contains both the preflight and the
     model processes. *(If the two-group design is preferred instead, add the proven-empty
     precondition to line 382 and §3A.3 as set out in H-03 repair option 2.)*
   - **H-04:** give the `review_dispatch` process-group identity the same write-ahead ordering
     (line 114); re-key "the kernel does not own this reviewer" off the reviewer principal kind
     rather than off a NULL process-group column, in both line 114 and §6 step 3 (line 563); state
     that the ordering rule governs all three execution records so §1A's "applies uniformly to all
     three" is true as written.
   - Optionally close non-blocking item 1: one sentence requiring the handle to be a
     controller-allocated, non-recycled identity, and requiring §6 to re-verify identity before
     signalling.
2. `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` — align §11 (per-attempt process-group cardinality) and
   §21 step 8 ("process groups the kernel owns") with the above.
3. `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md` — extend **ST-16** with the surviving-preflight-process
   arm; extend **ST-17** with the reviewer-fork-crash arm plus the external-principal negative arm;
   update §18A index rows as needed.
4. `ORCHESTRATOR_V1_TRACEABILITY.md` — **H-03** and **H-04** rows with explicit dispositions
   (silence is not a disposition; the existing test enforces this once the finding IDs are added).
5. `tests/test_orchestrator_freeze_spec.py` — update
   `test_pre_running_cleanup_handle_and_ceiling_discriminator_are_distinct_facts` (it currently
   asserts the defect), and add structural tests for the dispatch write-ahead ordering and for
   FC §11 ↔ SA §3A.3 cardinality agreement. **Prove failing-before against `9fbe4a9`** using the
   same `git archive` + hash-verified scratch method recorded in §3, and keep all existing tests
   green in both directions.

Then a **fresh read-only adversarial review bound to the new exact SHA** — the implementer must
not certify the repair, and the reviewer-independence limitation in §8 should be resolved by using
a different model or provider if the freeze gate requires it.

Adoption of the freeze remains **OWNER-PENDING** and is not proposed here.

---

**Inbox SHA processed:** `378c697dcad3a726fd5988366fff1fc1c2b28f51`
**Candidate reviewed:** `9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f`
**Canonical base:** `9e59860a945ec339c69af8709cd0721f0a795327`
**Superseded candidate:** `5eb25f8fe00a3196cb27d7b2c92b2b5fbf4a5c78`
**Verdict:** `CHANGES REQUIRED BEFORE OWNER DECISION`
