# CLAUDE OUTBOX

**Timestamp (UTC):** 2026-09-21T10:07:06Z
**Inbox SHA processed:** `a8195b2a1b7599f7929a8a8db369d611f34876c2` — consumed in full. These instructions are spent and must never be executed again.
**Round type:** independent adversarial review — review-only, no patching

---

## VERDICT

# REJECT — REPAIR REQUIRED

Four material repository-only defects (R-01 … R-04) and two test-quality defects
(R-05, R-06) reproduce against the exact candidate SHA. R-07 and R-08 are advisory
and do not on their own block acceptance.

This verdict is bound to `8588776455a1832da763810064cacb47d7192ef4` only. It carries
no authorisation of any kind — see "Authority not claimed" at the end.

---

## 1. What was asked

Independently and adversarially review **exactly**
`8588776455a1832da763810064cacb47d7192ef4` on `chatgpt/control-plane-vnext-phase1`
— the Engineering Control Plane VNext Phase 1 repository-only foundation.

Constraints from the inbox: resolve the remote branch HEAD first and stop without a
verdict if it is not that SHA; review-only, do not patch the branch; independently
verify authorship rather than trusting the inbox's assertion of eligibility; do not
accept green counts as proof — re-derive properties from source and attack them;
treat the reported local Director evidence purely as a claim to challenge; return
exactly one of `ACCEPT FOR PHASE 1 REPOSITORY FOUNDATION` / `REJECT — REPAIR
REQUIRED` / `BLOCKED`.

## 2. Preconditions I verified before reviewing

**Remote branch HEAD — matches exactly.** Fetched the branch explicitly (this repo
has a stale refspec, so an implicit fetch is not trustworthy):

```
git fetch origin chatgpt/control-plane-vnext-phase1
git ls-remote origin chatgpt/control-plane-vnext-phase1
8588776455a1832da763810064cacb47d7192ef4  refs/heads/chatgpt/control-plane-vnext-phase1
```

Repository is `https://github.com/crooksldn-pixel/clive.git`. No stop condition.

**Authorship — independently verified, not taken from the inbox.** Two checks:

- Commit metadata for all 44 commits between the merge-base `3ba4edeb` and the
  candidate tip: author and committer are `crooksldn-pixel <crooksldn@gmail.com>`
  on every one; zero commits authored by Claude.
- The candidate SHA appears **nowhere** in this builder checkout's reflog, i.e. it
  was not created locally by any prior bridge round in this worktree.

I did not author this candidate and am eligible to review it. (I checked this
deliberately: the previous five review rounds were mis-routed back to the author of
the commit under review, so authorship is now verified before anything else.)

**Review isolation.** I reviewed in a detached worktree
`/opt/crooks-builder/.worktrees/cp-vnext` at the candidate SHA. It is still
detached, unmodified and clean (`git status` empty). The candidate branch was not
patched, rebased, pushed or otherwise touched.

## 3. What I found

### R-01 — MATERIAL — the repository's accepted lint gate fails, entirely because of this candidate

`ruff check` is a repository gate (`ruff format` is not). Run over the accepted
environment's target set:

```
.venv/bin/ruff check app config scripts tests --output-format=concise
```

**10 errors, and all 10 are in files this candidate adds.** No other file in the
repository reports an error, so the tree was gate-clean before this branch and is
gate-dirty after it:

```
app/orchestrator/contracts.py:10:1   I001  Import block is un-sorted or un-formatted
app/orchestrator/contracts.py:145:48 UP037 Remove quotes from type annotation
app/orchestrator/contracts.py:183:57 UP037 Remove quotes from type annotation
app/orchestrator/contracts.py:225:48 UP037 Remove quotes from type annotation
app/orchestrator/policy.py:9:1       I001  Import block is un-sorted or un-formatted
app/orchestrator/scheduler.py:9:1    I001  Import block is un-sorted or un-formatted
app/orchestrator/scheduler.py:13:1   UP035 Import from `collections.abc` instead: `Sequence`
app/orchestrator/state.py:6:1        UP035 Import from `collections.abc` instead: `Mapping`, `Sequence`
app/orchestrator/store.py:17:1       UP035 Import from `collections.abc` instead: `Iterable`
tests/test_orchestrator_control_plane.py:1:1 I001 Import block is un-sorted or un-formatted
```

Worth flagging to the author: the most recent commits on the branch
(`8588776` "clean store imports and spacing", `bf66357` "normalize contract
imports", `63bede1` / `c3dd844` "normalize/repair test import formatting") were
attempts to fix exactly this by hand, and did not succeed. All 10 are
auto-fixable with `ruff check --fix` on those six files. **Do not run
`ruff format` across the repository** — it would reformat ~114 unrelated test
files and is not a gate.

### R-02 — MATERIAL — a result identity of `..` escapes the results directory

`EngineeringResult.task_id` is constrained by `pattern=r"^[A-Za-z0-9._:-]+$"`.
That pattern **accepts the literal string `..`**, and `JsonRecordStore.put_result`
uses `task_id` as a bare path component:

```python
path = self.results_dir / result.task_id / f"{result.attempt_id}.json"
```

Reproduced against the candidate source:

```
put_result(result(task_id="..", attempt_id="attempt-1"))
  wrote:    <root>/results/../attempt-1.json
  resolved: <root>/attempt-1.json          <-- outside results_dir
```

Two concrete consequences, both reproduced:

1. **Silent replay loss.** `read_results()` globs `*/*.json`, so the escaped record
   is never replayed. After publishing one legitimate result and one escaped
   result, `len(read_results())` is `1`, not `2`. The store reports success while
   the record vanishes from the offline simulation it exists to support.
2. **Collision with generated active state.** With `attempt_id="ACTIVE_STATE"` the
   escaped record lands on `<root>/ACTIVE_STATE.json`. In one order the immutable
   guard fires (`RecordConflictError` — good); in the other order,
   `write_active_state` uses `_atomic_write` with **no** immutability guard and
   silently overwrites the published immutable record. Verified both orders.

The committed test `test_result_identity_rejects_path_traversal_attempt_id` covers
only `attempt_id` (`"../escape"`, `"nested/attempt"`), both of which are caught by
the `/`. It never attacks `task_id`, and a whole-component `..` contains no `/`,
so the pattern does not see it.

Note `put_task` and `write_task_state` are **not** affected: they interpolate the id
into a filename (`f"{task_id}.r{revision}.json"`) rather than using it as a
directory, so `..` becomes the harmless filename `...r1.json`.

### R-03 — MATERIAL — `..` inside `changed_paths` defeats the out-of-scope gate entirely

`evaluate_obvious_continuation` enforces task scope by raw string prefix match,
with no normalisation:

```python
path == allowed.rstrip("/") or path.startswith(allowed.rstrip("/") + "/")
```

`EngineeringResult.changed_paths` has no validator at all. With
`allowed_paths=("crooks-assistant/tests",)`:

| `changed_paths[0]`                                | continuation allowed |
|---------------------------------------------------|----------------------|
| `crooks-assistant/app/main.py`                     | **False** (correct)  |
| `crooks-assistant/tests/../app/main.py`            | **True**  (escape)   |
| `crooks-assistant/tests/../../../../etc/passwd`    | **True**  (escape)   |

This contradicts the stated property "dirty result or out-of-scope edits cannot
auto-continue". It matters precisely because this module's premise is that a
worker's result is untrusted data, not authority — `changed_paths` is exactly such
untrusted input. The committed test `test_out_of_scope_changed_path_fails_closed`
uses only a plain non-prefixed path and therefore does not reach this.

Suggested repair shape (not applied): normalise with `posixpath.normpath` /
`PurePosixPath`, and reject any changed path that is absolute or that still
contains a `..` segment after normalisation, rather than only prefix-matching.

### R-04 — MATERIAL — an owner-gated task is still dispatchable through scheduler composition

The inbox names this property directly: "no owner-gated or stale task becomes
dispatchable through scheduler composition." It does not hold.

`evaluate_obvious_continuation` fails closed on owner gates asserted **in the
worker's own result** (`result.owner_decision_required`, `result.blocker_class`).
It never consults `TaskRuntimeState` — the mutable, controller-owned record that
carries `status=OWNER_GATE`, `blocker_class=OWNER_ONLY` and `owner_gate=True`.
Neither does `select_obvious_dispatch`, and the package exports no queue-builder
that would filter candidates by runtime state (grepped: no such function exists).

Reproduced:

```
TaskRuntimeState(status=OWNER_GATE, blocker_class=OWNER_ONLY,
                 blocker_reason="owner paused this stream",
                 owner_gate=True, transition_seq=3)

build_active_state(...)      ->  stream stage = "owner_gate", owner_gate = True   (correct)
select_obvious_dispatch(...) ->  DISPATCHED to worker "reviewer-1"                (defect)
```

So the generated active state correctly shows the stream as owner-gated at the very
moment the scheduler routes it. The authoritative, controller-side gate is the one
being ignored, while the self-asserted, worker-side gate is the one enforced —
which is the inverse of the module's own stated threat model.

Corroborating, same root cause: a candidate built from a **superseded** task
revision also dispatches, because the scheduler has no notion that a newer revision
exists. (`build_active_state` *does* handle late results from old revisions
correctly — the gap is confined to the scheduler/policy composition.)

### R-05 — TEST QUALITY — the compare-and-swap mutant survives; the Director's CAS claim does not reproduce

Deleting the compare-and-swap comparison in `store.write_task_state` outright:

```python
if expected_previous_seq != current.transition_seq:   ->   if False:
```

leaves the committed module at **30 passed / 0 failed**. The mutant survives.

Cause: `test_runtime_state_compare_and_swap_rejects_stale_writer` writes a state
with `transition_seq=1` when the stored current is already `1`. That trips the
*separate* increment rule (`1 != 1 + 1`), and the test only asserts that *some*
`StateConflictError` was raised — never which guard fired. The compare-and-swap
guard itself is therefore never exercised.

To be fair to the code: the guard **is** real and load-bearing in the shipped
version. I drove it directly and it behaves correctly:

| write attempt                                 | shipped behaviour |
|-----------------------------------------------|-------------------|
| `seq=2, expected_previous_seq=0` (lying CAS)   | rejected          |
| `seq=1, expected_previous_seq=1` (replay)      | rejected          |
| `seq=5, expected_previous_seq=1` (skip ahead)  | rejected          |
| `seq=2, expected_previous_seq=1` (legitimate)  | accepted          |

So this is a coverage defect, not a behavioural one. It nonetheless directly
refutes the inbox's reported local evidence that a CAS mutation was killed — under
recomputation, it was not.

### R-06 — TEST QUALITY — the starvation mutant survives

Changing the scheduler so that the first policy-denied candidate aborts the whole
sweep — the canonical starvation bug:

```python
if not decision.allowed:
    continue        ->        return None
```

also leaves the module at **30 passed / 0 failed**.

Cause: in `test_scheduler_skips_unroutable_stream_instead_of_starving_other_stream`
the "blocked" stream is made unroutable by **role** (its action requires
`independent-reviewer`; the only worker has role `builder`). `_worker_supports`
short-circuits in the worker loop, so `evaluate_obvious_continuation` is never
called for that stream and the mutated line is never reached. The test proves
role-routing skip, not policy-denial skip.

Again the shipped behaviour is correct — I confirmed it with a candidate that is
denied by *policy* rather than by role (high priority, `clean_worktree=False`,
sorted first): the eligible second stream was still dispatched. Coverage defect,
not a behavioural one.

### R-07 — ADVISORY — `changed_paths` without `result_sha` bypasses all SHA binding

The fresh-HEAD check is gated on `result.result_sha is not None`. A result that
reports edits but declares no commit skips it entirely:

```
changed_paths=("crooks-assistant/tests/t.py",), result_sha=None, next_action=CONTINUE
  current_branch_head=None          -> allowed = True
  current_branch_head="not-a-sha"   -> allowed = True
```

No rule ties a non-empty `changed_paths` to a required `result_sha`, and
`ContinuationCandidate.current_branch_head` is an unvalidated plain `str`. A worker
can therefore evade branch-truth binding by omitting its own result SHA. Low
severity in Phase 1 (nothing dispatches), but it is a hole in a property the
candidate otherwise enforces well.

### R-08 — ADVISORY — answering the inbox's `worker_id` question explicitly

The inbox asked me to identify the gap between a string `worker_id` and a
trustworthy controller-issued identity, and to judge it.

**The gap:** both sides of the independence test (`candidate_worker_id` and
`result.worker_id`) are free-form self-asserted strings. `EngineeringResult` is
worker-authored, so a worker can simply declare a different `worker_id` and satisfy
"independence" while being the same agent. There is no controller-issued token,
signature or attestation anywhere in the contract.

**My judgement: acceptable for this repository-only Phase 1 simulation, not a
material Phase 1 defect.** Nothing dispatches, no worker process exists, and every
record in the committed tests is constructed in-process by the controller side. The
string is adequate as a placeholder for an identity that Phase 2 must issue.

**But it is undisclosed, and that should be fixed.**
`ENGINEERING_CONTROL_PLANE_VNEXT.md:128` states the rule as bare
`reviewer_id != author_worker_id`, with no caveat anywhere in that document or in
`DECISIONS.md` that both operands are untrusted. A Phase 2 controller reading this
foundation would reasonably assume the independence property is enforceable. I
recommend an explicit recorded limitation before any phase that trusts a
worker-supplied identifier. This is a documentation repair, not a code one.

## 4. What held up under attack (re-derived from source, not taken on trust)

I did not rely on the green counts. Each item below was either attacked directly or
proven by a surviving/killed mutant.

**Mutation results — 6 of 8 mutants killed:**

| # | mutation                                              | outcome | killed by |
|---|-------------------------------------------------------|---------|-----------|
| M1 | author may self-review (independence check removed)   | KILLED  | `test_author_cannot_satisfy_independent_review` |
| M2 | stale HEAD accepted (branch-head binding removed)     | KILLED  | `test_fresh_remote_head_is_required…`, `test_branch_movement_after_result_blocks…` |
| M3 | `attempt_id` pattern removed (fs identity)            | KILLED  | `test_result_identity_rejects_path_traversal_attempt_id` |
| M4 | compare-and-swap comparison removed                   | **SURVIVED** | — (see R-05) |
| M5 | LRU fairness term dropped from sort key               | KILLED  | `test_scheduler_fairness_prefers_least_recently_dispatched…` |
| M6 | blocked stream aborts the sweep (starvation)          | **SURVIVED** | — (see R-06) |
| M7 | out-of-scope gate removed                             | KILLED  | `test_out_of_scope_changed_path_fails_closed` |
| M8 | stale subject-SHA gate removed                        | KILLED  | `test_stale_subject_sha_cannot_continue` |

Mutations were applied in a `/tmp` scratch copy, never to the branch. Each copied
file was proven byte-identical to the candidate SHA via
`git hash-object` == `git rev-parse <sha>:<path>` before mutating (all 6 MATCH),
and the scratch reproduced the 30/30 baseline before any mutation.

**Counterexamples I invented beyond the committed test table, which the code handled correctly:**

- Branch moved to an unrelated SHA after the result → no dispatch.
- Only available worker is the result's author → no dispatch; adding a second
  reviewer dispatches to the non-author. Role routing never selected the author.
- Equal priority, least-recently-dispatched wins; never-dispatched wins over both;
  explicit priority deliberately overrides LRU. All three deterministic.
- High-priority but policy-denied stream sorted first does not starve an eligible
  lower-priority stream.
- Immutable replay: identical bytes are idempotent; different bytes on an existing
  identity raise `RecordConflictError`.
- Late result from an old task revision is correctly ignored by
  `build_active_state`; an advanced branch correctly renders the stream `OBSOLETE`.
- CAS lying / replay / skip-ahead all rejected (table in R-05).

**On the inbox's concurrency question (item 4) — the candidate is honest here.**
I looked specifically for a misleading multi-process safety claim and did not find
one. `store.py` states the implementation "is for repository/offline simulation. A
production multi-process controller will require a transactional store", and
`ENGINEERING_CONTROL_PLANE_VNEXT.md:233` says "This is not fake concurrency. It is
starvation prevention while running a single shared lane." The check-then-write in
`_put_immutable` and `_atomic_write` is TOCTOU-racy across processes, but that is
exactly what those disclaimers cover, so I do not raise it as a defect. (The
missing immutability guard on `write_active_state` in R-02 is a different issue and
is not covered by the disclaimer.)

## 5. Test, lint and scan results

| check | result |
|---|---|
| Targeted module `tests/test_orchestrator_control_plane.py` | **30 passed in 0.94s** |
| Full offline suite `pytest tests -m "not live" -q -n 4` | **2836 passed, 8 skipped in 258s (4m18s)** — exit 0, no failures, no flakes |
| `ruff check app config scripts tests` | **FAIL — 10 errors, all in candidate files** (R-01) |
| `gitleaks git --redact --log-opts=3ba4edeb..8588776` | **no leaks found**, 41 commits scanned |

The full suite is clean, so the new `app/orchestrator` package introduces no
regression anywhere else in the tree. The targeted count matched exactly in both
the worktree and the isolated scratch copy.

## 6. Diff scope and safety surface

Candidate diff vs merge-base `3ba4edeb`: **15 files, +2569 / −10**, confined to
`crooks-assistant/app/orchestrator/` (5 new modules, 861 lines),
`crooks-assistant/docs/product-memory/` (8 files), and one new test module (609
lines). **Nothing outside those three areas is touched** — verified by inverted
path filter.

Safety-relevant greps over the whole diff found no runtime code at all: no
`subprocess`, no `httpx`/`requests`, no `uvicorn` / `host=` / `0.0.0.0`, no systemd
unit, no `writes_enabled` or `CROOKS_WRITES_LOCAL_OWNER` change. Every match for
"secret", "systemd", "watcher" is prose that *disclaims* authority, or a test
fixture literal named `"secret_scan"`. This is consistent with the candidate's
claim to be repository-only.

## 7. State at end of run

| item | value |
|---|---|
| Production branch HEAD (`/opt/crooks-os/crooks-assistant`) | `claude/linux-prod-migration-production` @ `1cf3a0f3361b79f9de208d80f501543c53c244b5` — **not touched, read only** |
| Builder checkout (`/opt/crooks-builder`) | `claude/builder-environment-repair` @ `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` — `git status` clean |
| Review worktree (`/opt/crooks-builder/.worktrees/cp-vnext`) | detached @ `8588776455a1832da763810064cacb47d7192ef4` — `git status` clean, left in place for reproduction |
| Candidate branch | **unmodified** — not patched, not committed to, not pushed, not merged |
| Bridge worktree (`/opt/crooks-ai-bridge`) | `crooks-ai-bridge`; only `bridge/claude-outbox.md` written by me |
| `crooks-assistant.service` | loaded active running (unchanged) |
| `crooks-bridge-watcher.service` | loaded active running (unchanged) |
| Port 8000 | `LISTEN 127.0.0.1:8000` only — **not publicly exposed**, unchanged |
| Scratch artifacts | `/tmp/cpatk`, `/tmp/cpmut` deleted |

**Files changed by me this round:** `bridge/claude-outbox.md` only. No commits were
made in any repository.

**Preserved safety constraints:** `writes_enabled` false, `CROOKS_WRITES_LOCAL_OWNER`
false, FastAPI bound to 127.0.0.1, port 8000 not exposed, proposal/action/
verification semantics unchanged, no live Shopify/Gmail/ElevenLabs calls, no
external mutation, V2 not begun, UI not redesigned, Mac deploy/rollback path
untouched, `/root/.claude` still writable, no secret value printed or committed.

## 8. Errors and blockers

None. Nothing in this round was blocked by my permission layer, and I did not need
to widen any permission. No owner approval was requested or implied by the inbox,
and none is recorded here.

## 9. Decisions and questions for review

1. **R-05 and R-06 contradict the reported local Director evidence.** The inbox
   said mutations were killed for CAS and for starvation/fairness. On
   recomputation, fairness was indeed killed (M5) but **CAS and starvation both
   survived**. Whoever produced that evidence should re-run it — I suspect the
   original mutations were applied to a different line than the guard actually
   under test, which is exactly the failure mode both tests have.
2. **R-04 is a design question, not just a bug.** The cheapest repair is a
   queue-builder that filters candidates by `TaskRuntimeState` before they reach
   `select_obvious_dispatch`. But it is worth deciding deliberately whether the
   owner gate belongs in the *policy* (so it cannot be bypassed by any caller) or
   in *candidate construction* (so the scheduler stays a pure function). I lean to
   the policy, since the module's stated contract is that it "fails closed on owner
   gates" — today that sentence is only true for worker-asserted gates.
3. **R-01 is trivially repairable but should not be hand-fixed again.** Several
   prior commits tried and failed. `ruff check --fix` on the six files resolves all
   10. Do not run `ruff format`.
4. I have deliberately **not** applied any of these repairs — the inbox said
   review-only.

## 10. Proposed next step (exact)

Issue a single bounded repair task on `chatgpt/control-plane-vnext-phase1`,
authored by someone other than me so I remain eligible to review the result, with
this exact scope and nothing else:

1. `ruff check --fix` the six candidate files; do not run `ruff format`. (R-01)
2. Reject `.` and `..` as whole-component record identities in `EngineeringTask`,
   `EngineeringResult` and `TaskRuntimeState`, and add a defensive containment
   assertion in `JsonRecordStore.put_result` that the resolved path stays under
   `results_dir`. Give `write_active_state` the same immutability discipline as
   `_put_immutable`, or document explicitly why it is exempt. (R-02)
3. Normalise `changed_paths` before the scope comparison and fail closed on any
   absolute path or surviving `..` segment. (R-03)
4. Make the owner gate authoritative: have `evaluate_obvious_continuation` accept
   the task's `TaskRuntimeState` and fail closed on `owner_gate`, `OWNER_ONLY` and
   superseded revisions; thread it through `ContinuationCandidate`. (R-04)
5. Repair the two blind tests so their mutants die: assert *which* guard fires in
   the CAS test (distinct expected_previous_seq vs. increment cases), and add a
   starvation case whose first candidate is denied by **policy** rather than by
   role. (R-05, R-06)
6. Require `result_sha` when `changed_paths` is non-empty, and validate
   `current_branch_head` as an exact SHA. (R-07)
7. Record the self-asserted `worker_id` limitation explicitly in
   `ENGINEERING_CONTROL_PLANE_VNEXT.md` next to the
   `reviewer_id != author_worker_id` rule. (R-08)

Evidence required with the repair: `ruff check` clean over
`app config scripts tests`; the targeted module green; the full offline suite with
no regression against **2836 passed / 8 skipped**; and a mutation table showing M4
and M6 now killed, plus the R-02 / R-03 / R-04 reproductions in this document now
failing closed.

Then route the repaired SHA back to me for a fresh independent review. Please state
the new SHA explicitly in the inbox, as before.

## 11. Authority not claimed

This is an engineering verdict on a repository-only candidate. It authorises
nothing. Specifically it does **not** authorise watcher/systemd/runtime
installation, production deployment, new credentials or secrets, connector/MCP
permission changes, privilege expansion, CROOKS/CLIVE business writes, destructive
owner-work cleanup, external spend, production merge, freeze adoption, or any
DEC-046/047 sequencing amendment. No owner approval was given in the inbox and none
is inferred.
