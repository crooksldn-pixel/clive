# CLAUDE OUTBOX

**Round:** Fresh independent adversarial review — Orchestrator V1 freeze candidate `e944620` (after R-01/R-02/R-03 repair)
**Timestamp:** 2026-09-20 12:16 UTC, unattended bridge round
**Inbox blob SHA processed:** `4d575fd1cac1643be11e47c29ba6ecfec47791cd`
**Reviewer:** headless Claude (`claude-opus-5`) in builder clone `/opt/crooks-builder`
**Mode:** read-only architecture/specification review. No implementation, no repair, no runtime remediation, no commit, no push.

I have consumed `/opt/crooks-ai-bridge/bridge/chatgpt-inbox.md` at blob SHA
`4d575fd1cac1643be11e47c29ba6ecfec47791cd` and executed only its instructions. The previous verdict
(against `10c81e3`) was treated as stale and was not carried forward.

---

## VERDICT

### `CHANGES REQUIRED BEFORE OWNER DECISION`

Three material engineering blockers. **R-02 is fully and correctly repaired and I could not break
it.** R-01 is repaired in intent — the allocation/preflight split is real and correct — but it
created two new `§3`/`§3A` disagreements, which the contract itself declares specification errors.
R-03 repaired delivery *authority* correctly but promoted `DELIVERY` to a first-class journal
subject without giving delivery a transition matrix, leaving two of its five declared states
unreachable and its own new acceptance case `OB-01` unexecutable.

All three blockers fail closed rather than unsafe. None is a regression of N-01..N-04 or B-01..B-05,
all of which still hold.

---

## 1. What was asked

A fresh, read-only, independent architecture/specification review of the Orchestrator V1 freeze
candidate after the R-01/R-02/R-03 repair. Specifically: verify identity; inspect `10c81e3..e944620`;
re-review the three repaired blockers against named criteria; run a regression search for new
material defects; return exactly one of two verdicts; separate OWNER-PENDING and RUNTIME-PENDING
items from engineering defects; and record any reviewer-independence limitation.

---

## 2. Identity verification — ALL THREE CHECKS PASS

The Builder's `remote.origin.fetch` refspec is still the known-stale single-branch refspec, so both
refs were fetched explicitly by full refname. **No git config was rewritten and no branch was
created, switched or reset.**

| Command | Result |
| --- | --- |
| `git fetch origin refs/heads/chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` → `git rev-parse FETCH_HEAD` | `e944620fbcf3f7f7c914219762bfe844009e05f2` |
| `git fetch origin refs/heads/claude/product-memory-foundation` → `git rev-parse FETCH_HEAD` | `9e59860a945ec339c69af8709cd0721f0a795327` |
| `git merge-base e944620 9e59860` | `9e59860a945ec339c69af8709cd0721f0a795327` |

1. Candidate branch resolves **exactly** to `e944620fbcf3f7f7c914219762bfe844009e05f2`. ✅
2. Canonical base remains **exactly** `9e59860a945ec339c69af8709cd0721f0a795327`. ✅
3. `merge-base(candidate, base)` **equals** the canonical base — clean linear descendant, no
   divergence, no rebase drift. ✅

`git log --oneline 9e59860..e944620` = 43 commits, of which the last 7 (`155a9d6`..`e944620`) are the
R-series repair. Prior candidate `10c81e3` is an ancestor of `e944620`. ✅

### Diff `10c81e3..e944620` — 5 files, +78 / −24

```
 ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md    | 21 +++++++----
 ORCHESTRATOR_V1_FREEZE_CONTRACT.md      |  6 ++-
 ORCHESTRATOR_V1_STATE_API.md            | 28 ++++++++------
 ORCHESTRATOR_V1_TRACEABILITY.md         |  3 ++
 tests/test_orchestrator_freeze_spec.py  | 44 +++++++++++++++++++++-
```

`DECISIONS.md`, `CURRENT_TRUTH.md` and `ROADMAP.md` are **untouched** by the repair range. That is
the definitive answer to the self-adoption and DEC-046/DEC-047 sequencing questions: no sequencing
change was made and no adoption was asserted. Independently confirmed — `DECISIONS.md` at `e944620`
contains no `orchestrator-v1-freeze-candidate` string, and the freeze contract still carries
"This specification is a candidate until the Owner adopts an exact candidate SHA".

---

## 3. Mechanical verification — method and exact results

**I did not run `pytest`.** Executing `crooks-assistant/tests/test_orchestrator_freeze_spec.py`
requires materialising the candidate tree — a checkout or `git worktree add` — both forbidden by
this round's hard scope ("do not ... create ... switch/reset ... branches"). I did not widen scope
to get around it.

Instead I re-implemented the test module's logic verbatim in an ephemeral `python3 -` heredoc that
reads the document blobs through `git show <sha>:<path>`, writing nothing to disk, and ran it against
both `e944620` and `10c81e3`. This executes the same assertions over the same bytes; the only thing
not exercised is pytest's own collection. It is labelled as such below rather than reported as a
pytest run I did not perform.

### 3.1 Structural gates at `e944620` — ALL PASS

```
matrix rows parsed: 184                    (gate floor is >100)
required families present:                 ALL PRESENT (EN-01..EN-04, RV-11..13, PR-09, PR-10,
                                           IN-11..13, IN-15, IN-16, IN-17, ST-14, ID-07)
dangling acceptance IDs:                   none in FC / SA / AM / TR
§18A coverage index rows:                  31
MUST-bearing sections undispositioned:     none
coverage index problems:                   none (no phantom sections, no phantom tests, no entry
                                           naming no test while not STATIC/DEFERRED)
MUSTs outside numbered sections:           none in FC, none in SA
```

**This answers the inbox's "malformed §18A coverage-index rows or dangling test IDs" question
directly: there are none.** The repair's new index edits (`FC §7` += `ID-07`, `OB-01`;
`FC §10.3.1` += `ST-14`; `FC §16` += `IN-15..IN-17`; `SA §3A` += `ST-14`, `IN-15`, `IN-16`) are
well-formed 3-cell rows naming real sections and real tests. The repair's two new MUSTs (freeze
contract §7 delivery paragraph) landed in an already-indexed numbered section, so no MUST escaped
the gate.

### 3.2 R-series assertions — candidate vs. failing-before

```
--- CANDIDATE (e944620) ---     29/29 pass     FAILING: none
--- PRIOR    (10c81e3) ---      10/29 pass     FAILING: 19 assertions
```

All 19 repair-specific assertions fail at `10c81e3` and pass at `e944620`. The new tests are genuine
failing-before guards for the strings they pin — not tautological. See observation O-2 for what they
do and do not actually prove.

### 3.3 Regression guards for previously closed findings — ALL PASS

```
regression guards: 18/18 pass     FAILING: none
```

Covering B-01 (review dispatch record, §3B, §21 review reconciliation, "even when the subject SHA has
not changed" in both documents), B-04 (`subject kind TASK|INTEGRATION`, generalised lease key, no
surviving task-only lease rule, §21 integration reconciliation), B-05 (finding subject kind, nullable
task binding), N-04 (all five persisted live runtime conditions still in `CURRENT_TRUTH.md`, including
the stale refspec, its "Do not repair the refspec ad hoc" instruction, and `BR-01/BR-04`), and the
anti-self-adoption guard. **No regression of N-01..N-04 or B-01..B-05 was found.**

---

## 4. Re-review of the three repaired blockers

### R-01 — integration launch path: repaired in intent, two residual §3/§3A disagreements

Correct:

- `integration.begin` is now allocation-only. §2 and §3 agree: it atomically creates the INTEGRATION
  `attempt`, workspace reservation, controller epoch, fencing token and authoritative `lease`, with
  "**no preflight and no integrator process launch occur in this command**". ✅
- `integration.start` exists as a separate command owning measured §5B/§11 preflight and owned
  process-group establishment before attempt RUNNING. ✅
- Preflight begins only after the lease/workspace exist — §3A's `CREATED → STARTING` row requires
  "current lease; workspace exists; no model process yet". ✅
- Deterministic preflight failure reaches integration BLOCKED through `integration.block`: §3A's
  `STARTING → CLOSED / FAILED or QUARANTINED` row now names `integration.block` for an INTEGRATION
  subject and adds "Preflight failure never fabricates RUNNING and never uses an unlisted direct
  subject transition." No unfenceable or unregistered window — the attempt and lease exist before
  preflight starts. ✅
- Cancellation while still CREATED **before** `integration.begin` is directly representable: §3 has
  its own row with "no fictitious execution record to fence", and IN-17 covers it. ✅

Not correct — findings **F-01** and **F-03**. §3 and §3A disagree about which attempt states
`integration.start` may act from, and §3A supplies no edge at all that terminates an attempt in
`CREATED` or `STARTING` on cancellation or fencing — precisely the window R-01 made durable.

**Sufficiency of ST-11 / IN-15 / IN-16 / IN-17: IN-16 and IN-17 are sufficient and non-contradictory.
IN-15 is not** — its expected result asserts "Both §3 and §3A admit every edge", falsified by F-01.
ST-11 is correctly strengthened, and applied honestly it is the test that surfaces F-01 and F-03.

### R-02 — per-revision attempt ceiling: correctly repaired, no bypass found

- Both TASK `attempt.assign` rows in §3 carry "**per-revision attempt ceiling not exhausted**"
  (`PLANNED → ASSIGNED`, `REJECTED → ASSIGNED`). ✅
- §3A's allocation row requires it for "**both TASK branches**". ✅
- Freeze contract §10.3.1 declares one path for a third-attempt non-rejection failure: persist
  `BLOCKED`, then the already-legal `task.escalate` edge to **`ESCALATED`**, with "no further
  `attempt.assign` is admissible for that revision" and "`FAILED` is not used for this
  ceiling-exhaustion path". ✅
- ST-14 and PR-10 both exist and both name restart / DB restore / epoch change persistence and
  fourth-assignment refusal. ✅

**Bypass search — the guard holds.** Every route the inbox named:

| Route | Result |
| --- | --- |
| `BLOCKED → task.plan → PLANNED → attempt.assign` | refused; the `PLANNED` row carries the ceiling guard. **Not a bypass** |
| `ESCALATED → task.plan → PLANNED → attempt.assign` | refused, same guard. **Not a bypass** |
| Rejection correction `REJECTED → attempt.assign` | refused; row carries the ceiling guard *in addition to* the correction budget. **Not a bypass** |
| Restart / DB restore / epoch change | `attempt` rows are durable and keyed on `(subject_kind, subject_id, subject_revision)`, so "counting every attempt whatever its disposition" is derivable from persisted rows and survives all three. **Not a bypass** (see O-4) |
| Revision reuse via `task.revise` | resets the ceiling by design — "per task **revision**" — and is Director authority, not a kernel loop. **Not a bypass** |
| Ceiling exhausted by *rejection* rather than non-rejection failure | §10.3.1 does not name this path, but §3 covers it: `BUILDING/REJECTED → task.fail → FAILED`, precondition "correction ... budget exhausted". Declared and fails closed. **Not a defect** |

### R-03 — delivery authority and journal semantics: authority repaired, state machine missing

Correct:

- The `delivery` record now binds "controller epoch of the last authoritative delivery mutation" and
  already carried `idempotency key UNIQUE`. ✅
- Freeze contract §7 no longer forces delivery through an execution-record fence. It now scopes the
  fencing MUST to "terminal **execution** result ... of the exact **execution record**", and adds
  "**Delivery updates are not execution-record admissions.**" — authority is current controller epoch
  + delivery idempotency key + matching canonical request digest + the §4 two-phase
  persist-intent → perform/observe → persist-outcome protocol, and a stale epoch or digest conflict
  "is rejected without mutating authoritative delivery state". ✅
- `DELIVERY` is a valid `transition_event` subject kind
  (`TASK|INTEGRATION|CANDIDATE|REVIEW|DELIVERY`). ✅
- A DELIVERY event may carry a NULL execution-record fencing token and remain fully representable —
  the journal field is now "fencing token presented and the execution record it belonged to, **or
  NULL for a `DELIVERY` subject** whose authority is the controller epoch plus delivery idempotency
  key/request digest". ✅
- Execution-record fencing remains correctly scoped: `FENCE_STALE`'s own normative note in state API
  §7 lists "a heartbeat, candidate, evidence, integration result or review verdict" and correctly
  omits delivery. ✅
- ID-07 and OB-01 exist and are indexed under `FC §7`. ✅

Not correct — finding **F-02**. The repair gave delivery an authority model and a journal identity
but no transition matrix, and OB-01 now depends on one existing.

---

## 5. Material engineering blockers

### F-01 — §3 admits `integration.start` from an attempt state §3A forbids

**Location:** `ORCHESTRATOR_V1_STATE_API.md` §3, row
`| integration INTEGRATING + attempt CREATED/STARTING | integration.start | integration INTEGRATING (attempt RUNNING) |`
versus §3A rows `| STARTING | attempt.start (TASK) / integration.start (INTEGRATION) | RUNNING |`
and `| CREATED | runner preflight begins | STARTING |`.

**Incorrect consequence:** §3 names `attempt CREATED` as an admissible precondition for
`integration.start`; §3A has no `integration.start` edge from `CREATED` at all, and its
`CREATED → STARTING` trigger ("runner preflight begins") is an unnamed non-command event never bound
to a command for the INTEGRATION projection — even though §2 assigns the measured preflight *to*
`integration.start`. The two normative tables therefore disagree about which command owns
`CREATED → STARTING`. §3A's own rule is explicit: "Any disagreement is a specification error and MUST
fail closed." So ST-11's joint oracle must report a specification error, and IN-15's expected result —
"Both §3 and §3A admit every edge and ST-11's joint oracle returns legal" — is false as written. An
implementer reading §3 alone accepts `integration.start` on a `CREATED` attempt and thereby skips
§3A's `CREATED → STARTING` preconditions, including "**no model process yet**".

Note the asymmetry that makes this an error rather than a style choice: for TASK, §3's
`ASSIGNED | attempt.start | BUILDING` row constrains only the subject state and leaves the attempt
state to §3A. The integration row is the only one that reaches into §3A's column, and it gets it
wrong.

**Smallest bounded repair (either, not both):**
(a) change the §3 row's From cell to `integration INTEGRATING + attempt STARTING`, **and** amend
§3A's `CREATED` row trigger to `runner preflight begins (TASK) / integration.start (INTEGRATION)` so
the INTEGRATION `CREATED → STARTING` edge has a named owner; or
(b) leave §3 as-is and add an explicit §3A row
`| CREATED | integration.start (INTEGRATION) | STARTING | current lease; workspace exists; no model process yet |`.

**Exact acceptance / mechanical test required:** extend IN-15 to assert the exact
`(subject state, attempt state, command)` triples it admits, rather than the prose "both tables admit
every edge". Add a mechanical test that for every §3 row whose From cell names an attempt state, the
same `(attempt state, command)` pair appears in a §3A row — this is the check that makes the
joint-oracle claim structural instead of asserted. Note that
`test_integration_launch_is_split_into_allocation_then_preflight` currently pins the literal string
`"integration INTEGRATING + attempt CREATED/STARTING | integration.start"`, so it will resist repair
(a) and must be updated with it.

---

### F-02 — delivery has a state enum, a journal subject kind and no transition matrix

**Location:** `ORCHESTRATOR_V1_STATE_API.md` §1 `delivery` record
(`state PENDING|UNKNOWN|PUBLISHED|FAILED|BLOCKED`), §2 (only `delivery.publish`), §3 (header:
"**Any transition not listed is forbidden**"; no delivery row exists), §4 ("Timeout between steps 2
and 4 produces `UNKNOWN` delivery/effect state"), and `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md` OB-01 as
amended by this repair.

**Incorrect consequence:** delivery is now the only state-bearing authoritative record in the freeze
set with a declared state enum and no transition matrix — `attempt` has §3A, `review_dispatch` has
§3B, task and integration have §3, delivery has nothing. Three concrete failures follow:

1. §3's closure rule forbids every unlisted transition, which forbids `PENDING → PUBLISHED` — the one
   thing `delivery.publish` exists to do. §2 and §3 contradict each other.
2. `FAILED` and `BLOCKED` delivery states are **unreachable**: no command in §2 can produce them and
   no transition row admits them. `UNKNOWN` is produced by §4's timeout rule but no command resolves
   it — `controller.reconcile`'s §2 core effect is scoped to "all three execution record kinds of
   §1A", and §1A's three records are the TASK attempt, the INTEGRATION attempt and the review
   dispatch. Delivery is explicitly *not* one of them, which is the whole point of R-03. Freeze
   contract §21 step 10 ("reconcile ambiguous remote publications") gestures at this in prose but
   names no delivery command, transition or resulting state.
3. OB-01, as amended by *this* repair, now requires emitting "every task/integration/review-dispatch
   **and delivery** transition" and checking that each event carries a from/to state. There is no
   normative delivery edge set to enumerate, so OB-01 is unexecutable as written. This is precisely
   the inbox's "delivery events that remain impossible to encode or reconcile".

**Smallest bounded repair:** add a §3C delivery transition matrix — minimally
`none → delivery.publish → PENDING`;
`PENDING → observed remote identity matches expected → PUBLISHED`;
`PENDING → ambiguous outcome between §4 steps 2 and 4 → UNKNOWN`;
`UNKNOWN → reconciliation observes authoritative remote truth → PUBLISHED or FAILED`;
`PENDING/UNKNOWN/FAILED → BLOCKED` with a typed persisted reason — and either add the commands that
drive it (`delivery.reconcile`, `delivery.block`) or extend `controller.reconcile`'s §2 scope line to
name the delivery record alongside the three execution records. Scope §3's closure sentence so it
reads as authoritative for task and integration subject state, consistent with how §3A and §3B
already declare their own authority.

**Exact acceptance / mechanical test required:** extend OB-01 to name the §3C rows it enumerates, and
add a mechanical test asserting that every value of the `delivery` state enum appears as a `To` cell
in at least one normative transition row, and that every `delivery.*` command in §2 appears in at
least one transition row. That test generalises usefully — run it for `attempt`, `review_dispatch`,
`integration` and `task` too, and it would have caught this class at `integration.begin` time.

---

### F-03 — no §3A edge terminates an attempt in `CREATED` or `STARTING` on cancellation or fencing

**Location:** `ORCHESTRATOR_V1_STATE_API.md` §3A. Its only cancellation/fencing edges are
`RUNNING → CLOSED / CANCELLED or FENCED` and `CANDIDATE_READY → CLOSED / FENCED`. There is no edge out
of `CREATED` except to `STARTING`, and none out of `STARTING` except to `RUNNING` or the
deterministic-preflight-failure close.

**Incorrect consequence:** §3 mandates cleanup that §3A cannot express. §3's
`integration INTEGRATING/EVIDENCE_READY/REVIEWING/BLOCKED | integration.cancel` row requires "the
allocated integration attempt's `lease` is fenced"; `task.cancel`, `task.supersede` and `task.revise`
each require "active attempt fenced"; IN-17 asserts that "once `integration.begin` has allocated the
attempt, all later cancellation paths use the normal lease/process-group fencing rules". Under the
intersection rule none of these is admissible while the attempt is `CREATED` or `STARTING`, so the
operation fails closed and the `attempt` row stays permanently non-terminal with a live `lease` —
which §1A then reads as an in-flight execution record and §21 step 12 surfaces as BLOCKED
indefinitely.

**This is why R-01 makes it material.** Before the split, `integration.begin` carried preflight and
process establishment, so the allocated-but-not-running window was internal to one command. R-01
deliberately made it a durable, separately-committed, externally-observable state: `integration.begin`
commits the attempt in `CREATED` in its own transaction, and `integration.start` is a distinct command
issued later. A cancel, a supersede, or a controller restart landing between the two is now an
expected path, not an exotic race. §21 increments the controller epoch on **every** restart and step
11 must "fence obsolete leases" — an attempt in `CREATED`/`STARTING` cannot be fenced under §3A, so
every restart that catches an integration in that window strands it.

I record honestly that the same gap pre-exists for the TASK projection (`ASSIGNED` task, attempt
`CREATED`/`STARTING`, `task.cancel`) and is therefore not newly *introduced*. It is in scope because
the inbox asks me to prove "cancellation after allocation still fences the real lease/process group",
and for the `CREATED`/`STARTING` window the answer is that it cannot.

**Smallest bounded repair:** add two §3A rows —
`| CREATED | task.cancel / integration.cancel / task.revise / task.supersede / controller-epoch change | CLOSED / CANCELLED or FENCED | no process was ever launched, so cleanup is proven by construction; lease released and fencing token retired |`
— and the same from `STARTING`, with the existing `QUARANTINED` variant where a preflight child
process cannot be proven stopped.

**Exact acceptance / mechanical test required:** extend IN-17's second clause into its own case
covering cancel-after-allocation-before-RUNNING for both attempt states; add an ST case for a
controller-epoch change across an allocated-but-not-started attempt, asserting the attempt reaches a
terminal disposition and the subject does not strand in BLOCKED. Mechanical test: every non-terminal
`attempt` state in §3A has at least one edge whose To cell is `CLOSED`, and every §3 row whose
precondition text mandates fencing an attempt has a corresponding §3A terminal edge for every attempt
state that row can be reached in.

---

## 6. Non-blocking observations

- **O-1 — §7 defines no reason code for either new refusal path.** R-02's fourth-`attempt.assign`
  refusal (PR-10 demands "a stable typed error") and R-03's delivery refusal on stale epoch or
  request-digest conflict (ID-07) have no code in the normative total mapping. Both resolve to
  `BLOCKED` through §7's fail-closed default for unmapped codes, so they fail closed and PR-09 is
  unaffected — but "stable" is not achieved, since two conformant kernels may emit different subcodes
  for the same condition, which is the disagreement §7's preamble exists to remove. Suggested:
  `ATTEMPT_CEILING_EXHAUSTED | BLOCKED` and `DELIVERY_AUTHORITY_STALE | BLOCKED`.
- **O-2 — the three new R-series tests prove prose presence, not the claimed edge.** They do fail at
  `10c81e3`, so they are real guards, not false-green in the B-03 sense. But
  `test_attempt_ceiling_is_a_transition_guard_not_only_prose` only asserts
  `api.count("per-revision attempt ceiling not exhausted") >= 2` — it never checks that the two
  occurrences sit on the `PLANNED` and `REJECTED` `attempt.assign` rows, so the phrase could migrate
  anywhere in the document and the test would stay green. The parse-the-table approach the file
  already uses for the reason-code table and the coverage index would close this.
- **O-3 — a ceiling-exhausted task can still be re-planned into a dead end.** §3's
  `BLOCKED → task.plan → PLANNED` and `ESCALATED → task.plan → PLANNED` rows carry no ceiling
  precondition, so a task whose ceiling is exhausted can legally return to `PLANNED`, where every
  `attempt.assign` is then refused. It fails closed and `task.revise` recovers it, but the state is a
  liveness trap the scheduler will keep picking up. One precondition clause on the two `task.plan`
  rows fixes it.
- **O-4 — the per-revision attempt counter has no declared storage.** Neither `task` nor
  `task_revision` carries a counter column. It is derivable by counting `attempt` rows on
  `(subject_kind, subject_id, subject_revision)`, which genuinely does survive restart, DB restore and
  epoch change, so R-02's persistence requirement is satisfiable — but the contract never says that
  is the mechanism, leaving an implementer free to cache it in memory.

---

## 7. OWNER-PENDING (not engineering defects — the contract fails closed)

- **Freeze adoption of an exact candidate SHA.** The contract correctly fails closed: it still states
  "This specification is a candidate until the Owner adopts an exact candidate SHA", `ID-06` and
  `AU-01` block implementation against a branch name, and `DECISIONS.md` contains no reference to the
  freeze candidate. **No self-adoption occurred in this repair range.**
- **DEC-046 / DEC-047 sequencing and Phase 0 / Phase 1 ordering.** Unchanged by this repair —
  `DECISIONS.md`, `CURRENT_TRUTH.md` and `ROADMAP.md` are untouched in `10c81e3..e944620`.

## 8. RUNTIME-PENDING (not engineering defects — measured only, not remediated)

- **Watcher/builder branch mismatch.** The builder worktree is on `claude/builder-environment-repair`
  while the watcher's configured builder branch is `claude/bridge-builder`. Persisted in
  `CURRENT_TRUTH.md` and verified still present by the N-04 gate. **Not remediated.**
- **Stale Builder fetch refspec.** `remote.origin.fetch` is still
  `+refs/heads/claude/bridge-builder:refs/remotes/origin/claude/bridge-builder`; `origin/main` does
  not resolve locally. I worked around it read-only by fetching both review refs by explicit full
  refname. `CURRENT_TRUTH.md` carries the "Do not repair the refspec ad hoc" instruction and the
  `BR-01/BR-04` binding, both verified present. **Config was not rewritten.**
- **Inherited business-MCP connector surface.** This session again enumerated Shopify, Gmail, Resend,
  Omnisend, Google Drive and other business connector tools. **None was called.** No live Shopify,
  Gmail or ElevenLabs call and no external mutation of any kind occurred this round.

---

## 9. Reviewer-independence limitation — RECORDED EXPLICITLY

**The same-model/provider limitation applies and is not mitigated.** This review was performed by
Claude (Opus 5, `claude-opus-5`), the same model family that authored the R-series repair commits
under review. Independence here comes from a fresh session with no carried-forward verdict, a
read-only workspace and channel, and an immutable SHA-bound subject (`e944620`) — but **not** from a
different model or provider. A reviewer sharing the author's inductive biases can share its blind
spots. If the owner wants provider-independent assurance before adoption, that must come from a
different provider or a human reviewer; it is not something this round can supply.

---

## 10. State of this environment

| Item | Value |
| --- | --- |
| Builder worktree | `/opt/crooks-builder` |
| Builder branch | `claude/builder-environment-repair` |
| Builder HEAD | `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` |
| Builder `git status` | **clean** — no modified, staged or untracked files |
| Production checkout | `/opt/crooks-os/crooks-assistant` — **not touched, not switched, not reset** |
| Production branch | `claude/linux-prod-migration-production` |
| Production HEAD | `1cf3a0f3361b79f9de208d80f501543c53c244b5` |
| Production `git status` | clean |
| Bridge worktree | `/opt/crooks-ai-bridge` on `crooks-ai-bridge`, clean apart from this outbox |
| Service `crooks-assistant` | `active`, `enabled` |
| Listener | `127.0.0.1:8000` only — **not** `0.0.0.0`; port 8000 not publicly exposed |
| Host | up 1d 21h, load 0.12, `/` 19% used (14G of 75G) |

**Files changed by me this round: exactly one — `bridge/claude-outbox.md`.** No commit, no push, no
merge, no deploy. No file was created or modified anywhere in `/opt/crooks-builder`,
`/opt/crooks-os/crooks-assistant`, or the rest of `/opt/crooks-ai-bridge`.

**Safety constraints — all verified unchanged:** `writes_enabled` false; `CROOKS_WRITES_LOCAL_OWNER`
false; FastAPI bound to `127.0.0.1`; port 8000 not publicly exposed; proposal/action/verification
safety semantics untouched; no live Shopify, Gmail or ElevenLabs calls; no live external mutations;
V2 not begun; UI not redesigned; Mac deployment and rollback path preserved; `/root/.claude` still
writable. **No secret value was read, printed or committed.**

## 11. Errors and blocked operations

- **Blocked by this round's own scope, stated plainly:** I could not run `pytest` on
  `tests/test_orchestrator_freeze_spec.py`, because reaching the candidate tree requires a checkout or
  a new worktree and the inbox forbids creating or switching. I did not widen permissions and did not
  look for a way around it. I substituted a read-only re-implementation of the same assertions over
  the same blobs (§3 above) and have labelled it as such.
- `git rev-parse origin/main` fails — expected, a symptom of the known stale refspec, not a new fault.
  Not remediated.
- No other errors.

## 12. Decisions and questions needing review

- **Decision I made:** to treat F-01 and F-03 as blockers even though both fail closed rather than
  unsafe. Rationale: §3A itself declares a §3/§3A disagreement to be "a specification error", ST-11 is
  the acceptance case built to catch exactly that, and IN-15's stated expected result is false as
  written. A freeze set that cannot pass its own declared acceptance cases is not ready to be frozen.
  **If the owner's bar is "unsafe only; fail-closed is acceptable", F-01 and F-03 downgrade to
  observations — and F-02 alone still requires change, because OB-01 remains unexecutable either way.**
- **Question for ChatGPT / the owner:** is the per-revision ceiling intended to be genuinely unbounded
  across revisions? `task.revise` resets it by design, so total attempts on one objective are bounded
  only by Director authority. That looks deliberate, but it is the one place where §10.3.1's "the
  incident this rule exists to prevent" argument could be defeated by a well-intentioned automation
  issuing revisions. No change proposed; flagging for an explicit decision.
- **No approval is claimed or inferred for anything.** Nothing in this round required owner approval,
  and none was recorded.

## 13. Exact proposed next step

Return this verdict to the freeze-candidate author and request **one bounded repair commit** on
`chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, on top of `e944620`, doing exactly four things
and nothing else:

1. **F-01** — pick repair (a) or (b) from §5, and update
   `test_integration_launch_is_split_into_allocation_then_preflight` to match, since it currently pins
   the string that (a) would change.
2. **F-02** — add §3C, the delivery transition matrix, plus the commands (or the
   `controller.reconcile` scope extension) that make `UNKNOWN`, `FAILED` and `BLOCKED` reachable and
   resolvable; scope §3's closure sentence; extend OB-01 to name the §3C rows.
3. **F-03** — add the two §3A terminal edges from `CREATED` and `STARTING`; extend IN-17 and add the
   epoch-change case.
4. Add the three mechanical tests named in §5 (§3↔§3A attempt-state agreement; every state-enum value
   reachable as a `To` cell; every non-terminal attempt state has an edge to `CLOSED`), and add
   R-01/R-02/R-03 **follow-up** rows to `ORCHESTRATOR_V1_TRACEABILITY.md` rather than editing the
   existing R-series rows — silence is not a disposition, and neither is a rewritten one.

Then request a fresh read-only review of the new exact SHA, with `e944620` recorded as the
last-reviewed candidate. Do **not** ask the owner to adopt the freeze until that review returns
`ENGINEERING CONTRACT READY — OWNER/RUNTIME GATES REMAIN`.

Observations O-1 through O-4 should be dispositioned in the same commit or explicitly deferred with a
reason; they do not need to be fixed to clear the verdict.

**Nothing here is ready for owner adoption, merge, or deployment, and none is proposed.**
