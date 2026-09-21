# CLAUDE OUTBOX

**Timestamp (UTC):** 2026-09-21T11:07Z
**Inbox SHA processed:** `6a3ea1f9d0e903249a51394c4944117074f00f7d` — consumed in full. These instructions are spent and must never be executed again.
**Round type:** independent adversarial review — review-only, no patching

---

## VERDICT

# REJECT — REPAIR REQUIRED

Reviewed SHA: **`3ff2aa8bb8ee8ee8944980ad0dcebab04a79b481`**
Branch: `chatgpt/control-plane-vnext-phase1-repair-2026-09-21`

One subject defect and three verifier/test defects reproduce against the exact
candidate SHA. **All eight prior findings (R-01…R-08) were re-tested; seven are
genuinely repaired.**

I want to be plain about proportion: **no defect in the candidate's runtime
behaviour was found.** Every semantic attack I mounted held. The rejection rests on
one explicitly-required gate that still fails, plus three load-bearing guards
introduced by this very repair that have no test holding them.

---

## What was asked

Independently review exactly `3ff2aa8b…`, resolving the remote branch head first and
stopping without verdict if it differed. Verify reviewer eligibility independently.
Recompute everything from source; do not trust the summary or prior local claims.
Eight areas: ruff gate; filesystem/identifier safety; changed-path scope safety; SHA
binding; controller-owned state; mutation quality (two mandated mutations, four
re-checks, ≥2 invented adjacent counterexamples); regression evidence; R-08
documentation. Review-only — do not patch the candidate branch.

## Pre-flight

- **Remote head resolved first:** fetched the branch explicitly (the repo's refspec is
  stale for new branches), then `git rev-parse` →
  `3ff2aa8bb8ee8ee8944980ad0dcebab04a79b481`. Exact match to the inbox. Proceeded.
- **Reviewer eligibility — verified independently, not assumed.** All 7 commits in
  `8588776..3ff2aa8` are authored *and* committed by `crooksldn-pixel
  <crooksldn@gmail.com>`; none by Claude. The only reflog entry mentioning `3ff2aa8`
  in the builder repo is my own `fetch … storing head` from this run — there is no
  `commit:` entry, so this SHA was not produced in this environment. I am eligible.
  (This check matters: five earlier freeze rounds were mis-routed back to me.)
- `8588776` — the SHA I previously rejected — is an ancestor of `3ff2aa8`.
- Repair diff: 7 files, +228/−22 (5 source, 1 doc, 1 test module). No subprocess,
  network, systemd, config or dependency change. Genuinely repository-only.
- Review performed in a fresh detached worktree at the exact SHA,
  `/opt/crooks-builder/.worktrees/cp-repair`, **clean throughout**
  (`git status --porcelain` empty at start and at end).

---

## DEFECT 1 — SUBJECT DEFECT (blocks acceptance)

### S-01 — `ruff check` still fails; R-01 is only partially repaired

Inbox item 1 requires: *"run the repository's accepted `ruff check app config scripts
tests` gate; all candidate-introduced lint must be clean."* It does not pass. Run in
the review worktree with the repo's pinned ruff 0.16.8:

```
app/orchestrator/contracts.py:10:1: I001 [*] Import block is un-sorted or un-formatted
app/orchestrator/policy.py:9:1:    I001 [*] Import block is un-sorted or un-formatted
app/orchestrator/scheduler.py:9:1: I001 [*] Import block is un-sorted or un-formatted
tests/test_orchestrator_control_plane.py:1:1: I001 [*] Import block is un-sorted or un-formatted
Found 4 errors.  [*] 4 fixable with the `--fix` option.   (exit 1)
```

Bounded against both reference points:

| SHA | `ruff check app config scripts tests` |
|---|---|
| merge-base `3ba4edeb` | **All checks passed** (exit 0) — the repo is otherwise gate-clean |
| prior rejected `8588776` | 10 errors: 4 × I001, 3 × UP037, 3 × UP035 |
| candidate `3ff2aa8` | **4 errors: the same 4 × I001, unchanged** |

All four files are **new in the candidate line** (absent at the merge-base), so every
error is candidate-introduced. The repair fixed the 6 `UP035`/`UP037` errors (commits
`42d4756`, `b173d24` moved `Mapping`/`Sequence`/`Iterable` to `collections.abc`) but
**never touched the 4 `I001` import-ordering errors** — they survive unchanged from
the SHA I rejected for this exact reason.

**Fix:** `ruff check app config scripts tests --fix` resolves all four automatically.
Do **not** run `ruff format` across the repo — it is not a repo gate and would
reformat ~114 unrelated test files into a huge irrelevant diff.

---

## DEFECTS 2–4 — VERIFIER / TEST DEFECTS

Separated from the subject as the inbox requires, so the verifier cannot recursively
monopolise the subject. **In all three cases the shipped candidate behaves
correctly** — I proved that directly. The defect is that the repair's own new guard
has *no* test holding it, so a later edit silently reintroduces the vulnerability the
guard exists to close. Same class as R-05/R-06, which grounded the prior rejection.

Method: `app/orchestrator/*.py` and the test module copied into a scratch tree, every
copy proven with `git hash-object` == `git rev-parse 3ff2aa8:<path>`; baseline
reproduced (33 passed) before mutating; source restored from backup after each mutant;
post-restore baseline re-confirmed green.

### V-01 — the R-03 path-scope boundary fix is untested

The repair changed the scope check to
`path == allowed.rstrip("/") or path.startswith(allowed.rstrip("/") + "/")`
(`policy.py:142`), correctly closing the sibling-prefix trick. Reverting it to the
raw `path.startswith(allowed)` **survives the entire 33-test module** (33 passed,
exit 0).

Reproducing escape under that revert — `allowed_paths=("crooks-assistant/app",)`,
`changed_paths=("crooks-assistant/application/secrets.py",)`:

```
unmutated 3ff2aa8 : refused             <- correct
raw-prefix revert : DISPATCHED (escape)
```

`test_out_of_scope_changed_path_fails_closed` only exercises a path sharing no prefix
with the allowed root, so it never reaches the boundary condition.

### V-02 — `runtime_state.owner_gate` is untested

Replacing `if runtime_state.owner_gate:` (`policy.py:84`) with `if False:`
**survives all 33 tests**. It is load-bearing, not merely redundant with the status
set:

```
state: owner_gate=True, status=EVIDENCE_READY (an otherwise dispatchable status)
unmutated 3ff2aa8  : refused             <- correct
owner_gate removed : DISPATCHED (escape) <- an owner-gated task dispatches
```

### V-03 — `runtime_state.blocker_class` is untested

Replacing `if runtime_state.blocker_class is not BlockerClass.NONE:` (`policy.py:86`)
with `if False:` **survives all 33 tests**. Also load-bearing:

```
state: blocker_class=DETERMINISTIC, status=EVIDENCE_READY
unmutated 3ff2aa8   : refused             <- correct
blocker check gone  : DISPATCHED (escape) <- a deterministically-blocked task dispatches
```

**Shared root cause of V-02/V-03.** The only test covering controller-owned state,
`test_scheduler_respects_controller_owned_owner_gate`, sets *all three* redundant
signals simultaneously — `status=OWNER_GATE` **and** `blocker_class=OWNER_ONLY`
**and** `owner_gate=True`. Any one guard alone satisfies the assertion, so none is
isolated.

**Fix:** split into three tests, each pairing one controller-owned signal with an
otherwise-dispatchable status (the exact states above are constructible and pass
contract validation), plus a sibling-prefix case for V-01.

---

## Prior findings re-tested: 7 of 8 repaired

| # | Prior defect | Status at `3ff2aa8` | Evidence |
|---|---|---|---|
| R-01 | ruff gate fails | ❌ **still fails** (4 of 10 remain) | see S-01 |
| R-02 | `task_id=".."` escapes `results/` | ✅ repaired | `_validate_component` rejects `.`/`..`; regex excludes `/`. 23 hostile ids attacked; **no accepted id escapes `results_dir` or collides with `ACTIVE_STATE.json`** (which lives at the store root, not under `results/`) |
| R-03 | `..` in `changed_paths` defeats scope | ✅ repaired | `_validate_repo_path` rejects absolute, backslash and empty/`.`/`..` segments; all 12 hostile paths rejected incl. `crooks-assistant/tests/../app/main.py`; boundary match closes prefix tricks (untested → V-01) |
| R-04 | scheduler ignores `TaskRuntimeState` | ✅ repaired | `ContinuationCandidate` now carries `runtime_state`/`latest_task_revision`; the scheduler threads both into the policy. **15 hostile controller-owned states all refused**; superseded revision refused (untested → V-02/V-03) |
| R-05 | CAS mutant survived | ✅ repaired | mandated mutation now **RED, for the correct reason** — see below |
| R-06 | starvation mutant survived | ✅ repaired | mandated mutation now **RED** — see below |
| R-07 | `changed_paths` without `result_sha` | ✅ repaired | `contracts.py:276` rejects it at construction; confirmed by attack |
| R-08 | `worker_id` trust undisclosed | ✅ repaired | doc now states `worker_id` fields "are not trustworthy attestations when supplied by a worker", are "placeholders for controller-issued identity", must be controller-bound "before any runtime phase relies on reviewer independence for authority", and "must not claim cryptographic or process-level identity enforcement". Documentation only, as scoped — no invented cryptography |

## Mutation results (item 6)

**The two mandated mutations now both die:**

| Mutation | Result |
|---|---|
| **M1/R-05** — neutralise the CAS expected-sequence comparison in `write_task_state` | **RED (killed)** — and **for the CAS reason**: the failure is `DID NOT RAISE StateConflictError`, *not* a different increment guard. The test now uses `transition_seq=2`, a *valid* increment from current `1`, so only the stale `expected_previous_seq=0` comparison can reject it. Exactly the R-05 defect, fixed. |
| **M2/R-06** — scheduler `return None` instead of `continue` on the first policy-denied candidate | **RED (killed)** — the denied stream-a now uses `required_role="builder"` matching the only worker, so it *is* routable by role and the denial (`clean_worktree=False`) is genuinely a policy denial. The R-06 defect — denial by role rather than policy — is fixed. |

**Re-checks, all killed:** reviewer independence (M3), branch-head binding (M4, 2
tests), out-of-scope path gate (M5), stale subject SHA (M6).

**Adjacent counterexamples I invented — 7, not the 2 required:**
A2 drop `.`/`..` rejection from `_validate_component` → RED; A3 drop
`changed_paths`→`result_sha` binding → RED; A4 drop obsolete-revision gate → RED;
A7 drop repo-path `..` segment rejection → RED.
**A1, A5, A6 SURVIVED the whole 33-test module → V-01, V-02, V-03 above.**

## Independent attack results (items 2–5)

All assertions held on the shipped candidate:

- **Identifiers (item 2):** 23 hostile `task_id`/`attempt_id` values — `..`, `.`,
  `../x`, `..\x`, `a/b`, `/abs`, empty, space, newline, NUL, over-length,
  URL-encoded `%2e%2e` and `..%2f`, Unicode one-dot-leader `․․`, fullwidth `．．`,
  RTL-override — all rejected. `put_result` proven to land inside `results_dir`;
  no accepted value escapes it or collides with `ACTIVE_STATE.json`.
- **Residual observation (not a defect):** `....`, `..:..`, `-`, `ACTIVE_STATE` and
  `ACTIVE_STATE.json` are *accepted* as `task_id`. I verified none escapes or
  collides — `ACTIVE_STATE.json` merely creates a `results/ACTIVE_STATE.json/`
  *directory*, while the real state file is `<root>/ACTIVE_STATE.json`. Harmless
  today; worth a comment if that layout ever flattens.
- **SHA binding (item 4):** fails closed on unresolved (`None`), malformed,
  uppercase, short (39), long (41) and moved HEAD; stale subject SHA fails.
- **Fail-closed judgement (item 3):** appropriate for repository-relative Git paths.
  It is a syntax whitelist that rejects *before* any normalisation, so it cannot be
  defeated by a normalisation mismatch between validator and consumer. Correct posture.
- **Legitimate continuations NOT broken (item 5, explicitly checked):** the baseline
  continuation dispatches; `EVIDENCE_READY`, `READY`, `PROPOSED`, `ACCEPTED` and
  `REJECTED` all still dispatch; the current revision still dispatches. The repair
  is not over-tight.

## Regression evidence (item 7)

- **Targeted module** (real worktree, candidate SHA): **33 passed** in 0.58 s.
- **Full offline suite** `pytest tests -m "not live" -q -n 4`: **2839 passed,
  8 skipped, exit 0**, 247.8 s. No failures and no flakes this run. Prior SHA
  `8588776` baseline was 2836 / 8 — the repair adds 3 tests net. Not a regression.
- **Secret scan:** gitleaks 8.30.1 (pinned), range `8588776..3ff2aa8`, redacted:
  7 commits, ~9.06 KB scanned, **no leaks found** (exit 0).
- **Static:** ruff 0.16.8 → **exit 1, 4 errors** (S-01).
- **Identity / cleanliness:** review worktree clean before and after; scratch trees
  deleted; candidate branch untouched.

## Files changed

**None, in any repository.** Review-only, as instructed. No commit, no patch to the
candidate branch, no push, no merge.

- Builder branch `claude/bridge-builder`: not committed to.
- Builder checkout `/opt/crooks-builder` is on branch
  `claude/builder-environment-repair`, HEAD
  `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, `git status` **clean** — inspected
  before acting and left exactly as found (it was not where a previous run's branch
  name would suggest, hence the check).
- Temporary review worktree `.worktrees/cp-repair` at `3ff2aa8` retained as evidence;
  a temporary merge-base worktree created for the ruff baseline was removed.
- The only file written this round is this outbox. Nothing else in
  `/opt/crooks-ai-bridge` was touched, and I ran no git command there.

## Production branch HEAD

`claude/linux-prod-migration-production` at
**`1cf3a0f3361b79f9de208d80f501543c53c244b5`** (read from
`/opt/crooks-os/crooks-assistant` by read-only `rev-parse` only).
**Not edited, not switched, not reset, not merged, not deployed.**

## Service and server state

- `crooks-assistant`: **active**, **enabled** — untouched.
- Listener: **`127.0.0.1:8000` only** (loopback); port 8000 not publicly exposed — unchanged.
- Host: up 2 days 20 h; load 1.12 / 1.42 / 0.76; `/opt` 14 G used of 75 G (19 %).

## Safety constraints

All preserved. Nothing was installed, started, stopped, provisioned or routed.
`writes_enabled` false, `CROOKS_WRITES_LOCAL_OWNER` false, FastAPI loopback-bound,
8000 unexposed, proposal/action/verification semantics unchanged, no live Shopify,
Gmail or ElevenLabs calls, no external mutations, V2 not begun, UI not redesigned,
Mac deployment and rollback path preserved, `/root/.claude` writable. **No secret
value is printed or committed anywhere in this handoff.** No owner approval was
needed, sought, assumed or recorded.

## Errors and blockers

None. No permission-layer blocks. The review completed in full; all eight inbox
areas were executed. `BLOCKED` was not warranted.

## Decisions and questions needing review

1. **S-01 is the whole of the subject rejection, and it is a one-command fix.** I
   considered accepting with S-01 as advisory. I did not, for two reasons: the inbox
   names the ruff gate as requirement #1 in imperative terms ("all
   candidate-introduced lint must be clean"), and this is the *second consecutive*
   rejection on the identical four errors. Accepting would make the gate advisory in
   practice.
2. **Question for the owner — is `I001` intended to be in the gate?** All four errors
   are pure import ordering, and two repair commits already tried and failed to clear
   ruff. If the preference is to exempt `I001` repo-wide, that is a deliberate
   configuration decision (`extend-ignore` in `pyproject.toml`) and should be made
   explicitly rather than by leaving a gate failing. I changed no configuration.
3. **V-01…V-03 are coverage, not behaviour.** If the priority is unblocking the next
   control-plane step, note the candidate's *semantics* are sound under everything I
   attacked. But a guard with no test is a guard that silently disappears, and these
   three guards are precisely the R-03/R-04 fixes this repair exists to deliver.
4. **The verifier defects cannot monopolise the subject.** V-01…V-03 are fixed by
   adding tests to `tests/test_orchestrator_control_plane.py` and require **no**
   change to `app/orchestrator/`. The subject source needs only the ruff fix.

## Exact proposed next step

One repair commit on `chatgpt/control-plane-vnext-phase1-repair-2026-09-21`, authored
through the GPT/GitHub path so I remain eligible to review the result:

1. From `crooks-assistant/`, run `ruff check app config scripts tests --fix`; confirm
   `ruff check app config scripts tests` exits 0. Do **not** run `ruff format`.
2. Add four tests to `tests/test_orchestrator_control_plane.py`:
   - sibling-prefix scope: `allowed_paths=("crooks-assistant/app",)` with
     `changed_paths=("crooks-assistant/application/secrets.py",)` must not dispatch;
   - `owner_gate=True` with `status=EVIDENCE_READY` must not dispatch;
   - `blocker_class=DETERMINISTIC` (+ `blocker_reason`) with `status=EVIDENCE_READY`
     must not dispatch;
   - retain the existing combined-signal test as a regression case.
3. Confirm each new test **fails** against `3ff2aa8` with the corresponding guard
   mutated out, and passes unmutated — i.e. that it actually holds its guard.
4. Re-run and record: targeted module; `pytest tests -m "not live" -q -n 4` (expect
   ≥2843 passed / 8 skipped); `ruff check` exit 0; gitleaks over the new range.
5. Push and send the new exact SHA for review.

Expected next verdict: **ACCEPT FOR PHASE 1 REPOSITORY FOUNDATION**, since the seven
substantive findings are already repaired and independently verified. Acceptance would
mean only that Phase 1 is sound enough for the next isolated control-plane step — it
authorises no watcher/systemd/runtime change, no deployment or promotion, no
credentials or permission change, no privilege expansion, no CROOKS/CLIVE business
writes, no external spend, no destructive cleanup, no merge to production and no
owner-only release or adoption.
