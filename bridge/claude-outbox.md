# CLAUDE OUTBOX

**Timestamp (UTC):** 2026-09-21T11:41:05Z
**Inbox SHA processed:** `721962eb97da7023d7bb7efb72e4b631493d72c0` — consumed in full. These instructions are spent and must never be executed again.
**Round type:** bounded repository-only repair (Control Plane VNext Phase 1 acceptance defects)
**Result:** repair complete, pushed, **not self-accepted**

---

## 1. What was asked

The independent review of exact SHA `3ff2aa8bb8ee8ee8944980ad0dcebab04a79b481` on
`chatgpt/control-plane-vnext-phase1-repair-2026-09-21` returned `REJECT — REPAIR REQUIRED`
with **no runtime semantic defect**. Four bounded items remained:

- **S-01** — four `I001` import-order errors (subject defect, repeat of R-01), fix only those.
- **V-01** — add a test proving `allowed_paths=("crooks-assistant/app",)` rejects sibling-prefix
  `changed_paths=("crooks-assistant/application/secrets.py",)`, failing if the boundary-safe
  check is regressed to raw `path.startswith(allowed)`.
- **V-02** — add a test isolating `runtime_state.owner_gate` (gate on, status otherwise
  dispatchable, blocker `NONE`).
- **V-03** — add a test isolating `runtime_state.blocker_class` (`DETERMINISTIC`, status
  otherwise dispatchable, `owner_gate=False`).

Plus: new successor branch off exact `3ff2aa8`, minimal diff, targeted/full/static/secret
evidence, explicit mutation proof per new test, clean worktree, push, do not self-accept.

## 2. What I found

I was the reviewer who produced these findings; this round I acted as the repairer only.

- **S-01 reproduced exactly.** `ruff check app config scripts tests` at `3ff2aa8` exited 1 with
  precisely the four named `I001` errors — `app/orchestrator/contracts.py:10`,
  `app/orchestrator/policy.py:9`, `app/orchestrator/scheduler.py:9`,
  `tests/test_orchestrator_control_plane.py:1`. All four were a single surplus blank line after
  the import block. No other rule fired anywhere in the repository.
- **The three runtime guards are, as the review said, already correct.** No line of
  `policy.py` or `scheduler.py` logic was changed. `policy.py:141` already does
  `path == allowed.rstrip("/") or path.startswith(allowed.rstrip("/") + "/")`;
  `policy.py:83-84` already refuses on `runtime_state.owner_gate`; `policy.py:85-89` already
  refuses on a non-`NONE` `runtime_state.blocker_class`.
- **Root cause of V-01/V-02/V-03 confirmed in the test module.**
  `test_scheduler_respects_controller_owned_owner_gate` (was line 507) sets
  `status=OWNER_GATE`, `blocker_class=OWNER_ONLY` **and** `owner_gate=True` simultaneously, so
  deleting any single one of the three guards left the whole 33-test module green.
- **Contract constraint worth recording:** `TaskRuntimeState.blocker_fields_are_consistent`
  forces `blocker_reason` to be present iff `blocker_class != NONE`, and forces
  `owner_gate=True` whenever `blocker_class == OWNER_ONLY`. That is why V-02 must use
  `blocker_class=NONE` (not `OWNER_ONLY`) to isolate the gate — `OWNER_ONLY` would drag the gate
  in with it and re-create the very conflation being repaired.

## 3. What I changed

Successor branch created from exact `3ff2aa8`; the reviewed branch was **not** rewritten.

**Branch:** `claude/control-plane-vnext-phase1-repair2-2026-09-21`
**Exact SHA for review:** `e8830c44bcae917b7c711b081a8adf003832bc9d`
**Parent:** `3ff2aa8bb8ee8ee8944980ad0dcebab04a79b481` (single commit on top)

```
 crooks-assistant/app/orchestrator/contracts.py     |  1 -
 crooks-assistant/app/orchestrator/policy.py        |  1 -
 crooks-assistant/app/orchestrator/scheduler.py     |  1 -
 .../tests/test_orchestrator_control_plane.py       | 96 +++++++++++++++++++++-
 4 files changed, 95 insertions(+), 4 deletions(-)
```

- **S-01** — `ruff check --select I001 --fix` over exactly those four paths. The entire
  production-code change is **four deleted blank lines**. `ruff format` was **not** run (it is
  not a repo gate, and running it would produce a large unrelated diff).
- **V-01** — new `test_scope_match_is_a_path_boundary_not_a_string_prefix`.
- **V-02** — new `test_owner_gate_alone_stops_an_otherwise_dispatchable_task`.
- **V-03** — new `test_deterministic_blocker_alone_stops_an_otherwise_dispatchable_task`.
- One small shared helper `_controller_dispatch(runtime, task)` for V-02/V-03.

Each new test carries **one** hostile signal over an otherwise dispatchable state, **plus a
load-bearing control** that flips only that signal off and asserts the same task *does*
dispatch. The control is what converts "the mutant survived" into a named escape: it proves
the guard is genuinely the only thing refusing, not redundant with something else.

No change to policy logic, scheduler logic, contracts logic, store, state, docs, config,
scripts, watcher, systemd or runtime.

## 4. Evidence

All tooling by absolute path from the base builder venv; the candidate worktree has no venv.

| Gate | Command | Result |
|---|---|---|
| Targeted | `pytest tests/test_orchestrator_control_plane.py -q` | **36 passed in 0.48s** (was 33 at `3ff2aa8`) |
| Static | `ruff check app config scripts tests` | **All checks passed — exit 0** (was exit 1, 4×I001) |
| Full offline | `pytest tests -m "not live" -q -n 4` | **2840 passed, 8 skipped, 2 errors in 234.71s** |
| Secret scan | gitleaks 8.30.1, `--log-opts="3ff2aa8..e8830c4"` | **no leaks found — exit 0**, 1 commit / ~3.78 KB |
| Worktree | `git status --porcelain` | **clean** |

**On the 2 full-suite errors — these are the known `-n 4` infrastructure race, not a
regression.** Both are `ERROR at setup`, both with the identical cause
`FileNotFoundError: '/tmp/crooks-tests-.../logs/capabilities.tmp' -> '.../capabilities.json'`
at `app/capabilities/delta.py:45` — an `os.replace` race on a shared temp file between xdist
workers. The two affected tests are
`tests/test_actions_routes.py::test_a_shopify_blip_is_not_spoken_as_a_permission_refusal` and
`tests/test_experience.py::test_the_golden_scenarios[tabs]`. **Re-run serially they pass:
60 passed in 171.32s, exit 0.** Neither touches `app/orchestrator/`, which is the only package
this diff modifies. This race is a pre-existing, previously recorded `-n 4` flake on this box.

**Count reconciles exactly:** 2839 passed at `3ff2aa8` + 3 new tests = 2842 attempted;
2 raced in setup ⇒ **2840 passed**. No test lost, none skipped that was not skipped before.

## 5. V-01 / V-02 / V-03 mutation outcomes

Mutations were applied in an isolated `/tmp` scratch copy — the branch itself was never
mutated. Every copied file was verified byte-identical to the worktree by `sha256sum` before
mutating, module resolution was pinned with `PYTHONPATH` and confirmed to resolve to the
scratch (`/tmp/cp-mut/app/orchestrator/policy.py`), the baseline reproduced at 36 passed, and
`policy.py` was restored from `.bak` between each mutant. Scratch deleted afterwards; the
restored copy was re-verified byte-identical and re-ran 36 passed.

| Mutant | Regression introduced | Outcome |
|---|---|---|
| **M-V01** | `path == allowed.rstrip("/") or path.startswith(allowed.rstrip("/") + "/")` → `path.startswith(allowed)` | **KILLED — 1 failed, 35 passed.** Only `test_scope_match_is_a_path_boundary_not_a_string_prefix` failed: `assert True is False`, decision `allowed=True, reason='same authorised bounded workflow may continue'` — i.e. `crooks-assistant/application/secrets.py` passed `allowed_paths=("crooks-assistant/app",)`. |
| **M-V02** | `if runtime_state.owner_gate: …` guard deleted | **KILLED — 1 failed, 35 passed.** Only `test_owner_gate_alone_stops_an_otherwise_dispatchable_task` failed: an `owner_gate=True` / `status=EVIDENCE_READY` / `blocker=NONE` task dispatched to `reviewer-1`. |
| **M-V03** | `if runtime_state.blocker_class is not BlockerClass.NONE: …` guard deleted | **KILLED — 1 failed, 35 passed.** Only `test_deterministic_blocker_alone_stops_an_otherwise_dispatchable_task` failed: a `blocker_class=DETERMINISTIC` / `owner_gate=False` / `status=EVIDENCE_READY` task dispatched to `reviewer-1`. |

The decisive point for acceptance: **in each case exactly one test failed, and it was the new
one.** The remaining 35 — including the old conflated
`test_scheduler_respects_controller_owned_owner_gate` — stayed green under all three mutants.
That is the direct measurement of the V-01/V-02/V-03 finding, and it is now closed: each guard
has exactly one test standing on it, and that test dies alone when the guard is removed.

## 6. Side-effect and safety confirmation

No runtime, service, business or external side effects. This round was repository-only.

- `writes_enabled` / `CROOKS_WRITES_ENABLED=false` — **unchanged**.
  `CROOKS_WRITES_LOCAL_OWNER=false` — **unchanged**.
- FastAPI still bound to **127.0.0.1:8000** only (`ss -ltn`: `LISTEN 127.0.0.1:8000`); port 8000
  not publicly exposed.
- `crooks-assistant` service **active**, `crooks-bridge-watcher` **active** — neither restarted,
  reloaded, installed nor modified by me.
- Production checkout `/opt/crooks-os/crooks-assistant` **not touched, not switched, not reset** —
  still branch `claude/linux-prod-migration-production`, **HEAD `1cf3a0f3361b79f9de208d80f501543c53c244b5`**,
  `git status` clean. Read only, for this report.
- No merge to any production branch, no deploy, no auto-merge, no PR opened.
- No Shopify, Gmail or ElevenLabs call; no live external mutation; no external spend.
- No proposal/action/verification safety semantics touched; V2 not begun; UI not touched; Mac
  deployment and rollback path untouched; `/root/.claude` still writable.
- No secret read, printed or committed; gitleaks clean over the successor diff.
- Parked prose-freeze parser track **not touched**. Watcher/systemd/runtime **not modified**.
- Builder root `/opt/crooks-builder` left clean on `claude/builder-environment-repair`; work was
  done in the existing `.worktrees/cp-repair` worktree.
- In this bridge worktree I wrote **only** `bridge/claude-outbox.md` and ran no git command here.

## 7. Decisions, questions, disclosed limits

1. **Branch name.** The inbox said "new successor repair branch" without naming it. I used
   `claude/control-plane-vnext-phase1-repair2-2026-09-21` — the `claude/` prefix reflects honest
   authorship (this commit is mine, not `crooksldn-pixel`'s). **The reviewer must account for
   this when checking authorship independence: the single commit `e8830c44` is authored by me,
   and the seven commits beneath it up to `3ff2aa8` are `crooksldn-pixel`'s.** Rename if the
   convention requires `chatgpt/`.
2. **Reviewer independence — I cannot review this.** I produced the S-01/V-01/V-02/V-03 findings
   *and* wrote this repair. Per the inbox I am not self-accepting; a genuinely fresh reviewer
   must review exact `e8830c44bcae917b7c711b081a8adf003832bc9d`.
3. **Disclosed blind spot.** My new tests kill the three specific mutants the review named. I did
   **not** re-run a broad mutation sweep over the rest of the 36-test module, so I cannot claim
   other guards in `policy.py`/`scheduler.py` are now load-bearing — only these three are
   measured. Residual non-defects recorded in the prior review (`....`, `..:..`, `-`,
   `ACTIVE_STATE.json` accepted as `task_id` but provably unable to escape `results/`) are
   unchanged and still not defects.
4. **No approval was requested or given this round, and none was needed** — nothing installed,
   started, provisioned, routed, deployed or verified live.

## 8. Proposed next step

**NEXT ACTION: fresh independent exact-SHA review required.**

Exactly:

1. Route a **fresh reviewer — not me** to review exact SHA
   `e8830c44bcae917b7c711b081a8adf003832bc9d` on branch
   `claude/control-plane-vnext-phase1-repair2-2026-09-21` (repo `crooksldn-pixel/clive`).
2. That reviewer should, at minimum: confirm `ruff check app config scripts tests` exits 0;
   confirm the diff versus `3ff2aa8` is the four blank lines plus three tests and one helper and
   nothing else; independently re-run the three mutations M-V01/M-V02/M-V03 and confirm each
   kills exactly its own test; and check the load-bearing controls are honest (that the
   "otherwise dispatchable" states really would dispatch).
3. Suggested adversarial angle for that reviewer, since I cannot check my own work here: try to
   construct a *fourth* isolated escape — a single controller-owned signal in `TaskRuntimeState`
   with no test standing on it (the `status` set at `policy.py:90-103` is the obvious place to
   attack, since no new test isolates it).
4. If accepted, the Phase 1 acceptance question returns to the owner. **Do not merge, deploy or
   enable anything on the strength of this outbox.**
