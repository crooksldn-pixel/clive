# Repository audit — CLIVE engineering control plane

**Run:** 2026-10-14, read-only, by the repo-auditor agent of the planning session. Verified by the
planning lead with spot checks noted inline (✔).
**Source read:** this worktree = `origin/clive/trunk` `dc59047e` (2026-10-09) + planning-only commits.
Paths are relative to `crooks-assistant/` unless they start with `.github/` or `projects/`.

Two kinds of evidence are kept apart: **source** (what the code says) and **projection signal** (what
the public status branches `origin/clive/control/{status,worker-01-status}` say ran). Neither is host
verification; host facts are in [HOST_AUDIT_RESULTS.md](./HOST_AUDIT_RESULTS.md).

## 1. Headline findings

1. **The inbox has a hard intake ceiling.** `MAX_INBOX_RECORDS = 100` (`app/remote_engineering/inbox.py:35` ✔). Above it **nothing** is admitted (`:199-200` ✔), and request files are never removed. `worker-01-inbox` held 75 request files on 2026-10-08. Roughly 25 more requests stop all intake. A Project DAG of any size makes this worse.
2. **Every control-plane file is a protected path** (`app/orchestrator/objectives.py:88-207` ✔): dispatcher, objectives, contracts, lifecycle, workers, reviewers, checks, `app/remote_engineering`, `app/engineering_bridge`, `app/tools/engineering_tools.py`, `config/builder_skills.json`, the loop scripts, and their tests. **The loop cannot build its own extensions.** Each control-plane PR is built by a Director session, reviewed independently before merge, and takes effect only at an owner-gated worker re-pin. That re-pin is reviewed by `root-repin.sh` (GPT, outside the repository; DEC-076).
3. **Pieces of a Project layer already exist, unused:**
   - `EngineeringTask.predecessor_task_ids` and `priority` (`app/orchestrator/contracts.py:112,116` ✔). The dispatcher reads neither.
   - `scheduler.select_obvious_dispatch` orders by priority (`app/orchestrator/scheduler.py:56-115` ✔). Nothing calls it; DEC-071 ruling 41 keeps the file.
   - The `integrate` objective merges several accepted objectives (`scripts/engineering_dispatcher.py:163-176`, `workers/integrator.py`). It is CLI only: the remote request schema excludes it.
   - CLIVE's own `Objective` of kind `build` groups several engineering requests (`app/objectives/store.py:126,356-360,1617-1632`). Kind `project` has typed blockers `missing_info, missing_capability, needs_owner, external` (`:122`).
4. **Ordering is alphabetical.** Objectives are read in `sorted(glob("*.json"))` order (`objectives.py:411-417` ✔). The first READY objective by id takes a free slot.
5. **The tick is synchronous.** Sandboxed checks and generators run inside the tick (`dispatcher.py:839-850,1069-1075`). A running worker's lease-expiry check runs *before* its finished result is read (`dispatcher.py:696-706`). At concurrency above 1, long checks can starve other attempts' heartbeats until they are cancelled as transient.
6. **Reviewers are not counted against concurrency.** `_live_count` counts only ASSIGNED and RUNNING builders (`dispatcher.py:489-495` ✔). Reviews are detached processes, and they share the same Max plan.
7. **A plan-allowance pause is not built.** Rate-limit events are parsed (`workers/claude.py:672-675` ✔), and nothing acts on them. The 30 Sep decision asked for launches to "pause before the allowance runs out" (`OWNER_DECISIONS_2026-09-30.md:99`).
8. **Owner gates are a dead end in the kernel.** `OWNER_GATE` is set only when a worker reports `owner_decision_required` (`dispatcher.py:771-773`). There is no trusted owner adapter, so the kernel can never lift it (`lifecycle.py:1229-1235,1969-1990`). The Builds decision cards record George's answers in the judgment ledger, but "the build loop cannot read the ledger yet" (`app/builds/decisions.py:28-33` ✔).
9. **Code default is `max_concurrent=1`** (`dispatcher.py:253`). FEATURES.md and INFRASTRUCTURE_2026-09-25.md describe worker-01 as an eight-builder loop. The projection shows at least four builders overlapping on 2026-10-07 23:16–23:30. The owner never approved "parallel builders" (DEC-064).

## 2. Capability matrix (source level)

| Capability | Source status | Evidence |
|---|---|---|
| Dispatcher lifecycle | BUILT | `dispatcher.py:374-427` (`tick`, `_step`). Kernel verbs `lifecycle.py:1215-1998`. Up to 12 transitions per objective per tick (`:380`). |
| Persistence | BUILT | JSON `StrictRecord` files under the store root: `tasks/<t>.r<n>.json`, `task-state/` (compare-and-swap on `transition_seq`, `store.py:59-80`), `attempts/`, `events/<t>/<a>.jsonl`, `reviews/`, `acceptances/`, `integrations/`, `objectives/<id>.json`. Each verb is a git-journal commit under `.kernel.lock` (`lifecycle.py:630-660,908-1020`). The journal is **not pushed** (`origin/clive/engineering-state` last updated 2026-09-23). |
| Intake / inbox | BUILT | `requests/<request_id>.json` on `clive/control/<host>-inbox` (production maps `worker-01` → `clive/control/worker-01-inbox`, `engineering_bridge/github.py:52-58`). Claims and receipts make it idempotent (`controller.py:262-365`). A base not yet fetched is *deferred*: no claim, no receipt, nothing burned, for up to 1 h (`waits.py:1-24` ✔). |
| Workspace isolation | BUILT | `<root>/<task>/<attempt>/` with its git directory beside it; a `clone --local` with the remote removed and hooks and fsmonitor off (`workspaces.py:1-24,44-45,107-138`). |
| Workspace cleanup | **GAP** | Nothing removes attempt workspaces or `runtime/homes/<attempt>`. |
| Builder session isolation | BUILT | `workers/claude.py:217-270`: `-p --output-format stream-json --verbose --session-id <uuid> --restricted`; `--tools Read,Edit,Write,Glob,Grep` (+`Skill`); `--permission-mode dontAsk`; `--strict-mcp-config --mcp-config {}` (or only `clive_checks`); `--setting-sources ""`; `--disable-slash-commands`, or `--plugin-dir` with skills; `--no-session-persistence`; `--max-turns 200`; `--json-schema`. The environment is built from scratch, with only `CLAUDE_CODE_OAUTH_TOKEN` from a file. The init roster is verified (`dispatcher.py:676-693`). No Bash by default. |
| Bounded repair | BUILT | `max_repair_rounds` 0–5, default 2 (`objectives.py:271`); host `--default-repair-rounds`. Review and CI repairs share the budget (`dispatcher.py:1187-1194,1421-1427`). Evidence carried forward: review findings verbatim (`_repair_brief :1962-1976`), red CI log summary (`_red_run_brief :2633-2659`), failed-check tails (`:458-476`), and the earlier try's stop report for a `<id>-N` re-file (`:2185-2208,2666-2698`, matched on the same title or the same allowed paths, `:2319-2325`). |
| Check sandbox | BUILT | `NamespaceSandbox` (`checks.py:211-400`): `unshare` of mount, net, pid, ipc and uts; chroot; `setpriv` to uid 65534 with no capabilities; tmpfs root with read-only `/usr`; no host network; CPU, memory, file and process limits; a fail-closed canary. Commands are each objective's own `checks` argv, with no shell. |
| Browser-capable checks | BUILT, opt-in | `--sandbox-browsers` and `--sandbox-node-path` bind Playwright's Chromium read-only (`checks.py:230-249`). **Exact-SHA CI already runs every browser screen test in real Chromium** and refuses to run without one (`.github/workflows/acceptance.yml:89-109`). |
| Exact-SHA GitHub acceptance | BUILT | Asks the Actions API for `acceptance.yml` runs with `head_sha=<sha>` (`github_acceptance.py:94,206-277`). Asked fresh before dispatch, before admitting READY, at integration and at landing (`dispatcher.py:1112-1180`). |
| Claude independent reviewer | BUILT | Principal `claude-reviewer` (`reviewers/claude.py:58`; `config/review_principals.json`). A read-only exported room at the exact SHA; Read, Glob and Grep only; `--json-schema`; up to 3 runs. Projection signal: **not in use on worker-01** (every verdict is `gpt`). |
| GPT reviewer | BUILT, as a flag choice | `--reviewer claude|gpt` (+`relay`), default `claude` (`reviewers/choice.py:28,59-77`). When the Claude reviewer fails 3 runs, the task **blocks**; it does not fail over to GPT (`dispatcher.py:1369-1372`). |
| Review contract | BUILT | `clive.review_result.v1` (`reviewers/base.py:108-140`): READY or CHANGES_REQUIRED with typed findings. The kernel re-checks reviewer eligibility (`lifecycle.py:1551+`, `routing.py`). |
| Landing on `clive/trunk` | BUILT, on by default (`--no-land` turns it off) | `dispatcher.py:1449-1714`. Lands only when green asked at that moment, READY, no protected path, the base on trunk, and the SHA containing the trunk head (DEC-064). A plain push, never forced. When the trunk has moved, a refresh revision merges it (an integrator merge that needs its own CI and review), at most 3 times, then the Director lands it (`:1825-1857`). |
| Remote status | BUILT | `status.json` (`clive.remote_engineering_status.v1`, `status.py:67,101-169`) on `clive/control/<host>-status`, with a 600 s heartbeat. A private stops channel serves over the tailnet only (`remote_engineering/private.py`; DEC-068). |
| Engineering bridge (production) | BUILT | `submit_engineering_request` is a write that waits for the owner's hold (`app/tools/engineering_tools.py:939-1060`). It writes create-only through the contents API. Checks come from `default_checks(paths)` (`:1141-1163`); ids from `_free_id`, which appends `-2..-9` (`:1069-1086`). |
| Builds owner surface | BUILT | `app/builds/board.py` groups: needs you, in progress, queued, stopped, on the trunk, live; a road from Filed to Live; requests grouped into builds by `-N` family. Decision cards: Try again, Leave it, Drop it, Allow the change (`decisions.py:97-107`), recorded but not acted on. |
| Bench | BUILT, CLI only | `python -m app.bench generate|run|judge|report` (`docs/BENCH.md`). Not wired to the loop. It needs the model over the network, so it **cannot** run in the no-network check sandbox. |
| Hash-pinned builder skills | BUILT | `config/builder_skills.json` (4 design skills, a sha256 for every file). Withheld on any mismatch. CLI gating: `BUILTIN_SLASH_COMMANDS` covers only 2.1.285 and 2.1.293 (`claude.py:130-133`). **Every skill goes to every builder: there is no per-task routing.** |
| Concurrency | BUILT | `--max-concurrent`, default 1; gate at `dispatcher.py:511-512` ✔. Reviewers, checks and generators are not counted. |
| Priority / ordering | **GAP** | Alphabetical (see §1.4). |
| Dependencies between objectives | **GAP** | The schema field is unused (see §1.3). |
| Project above objectives | **GAP** on the engineering side; partial in CLIVE (see §1.3) | — |
| Lifecycle timestamps | Partial | Kernel event times exist (`lifecycle.py:146-160`). `app/engineering_measures.py` computes submitted→candidate→accepted→integrated→landed→deployed, review rounds and owner minutes. Missing: check durations, CI start and finish (the wait note is popped once green, `dispatcher.py:1157`), queue reasons, and any owner-attention source. |
| OWNER_GATE | BUILT, a dead end | See §1.8. |
| Blocked-reason taxonomy | BUILT, derived from prose | `_block` records `DETERMINISTIC` except for owner gates (`dispatcher.py:1860-1864` ✔). Causes come from blocker text prefixes (`STOP_CAUSES :2341-2366`), with a second regex copy in `app/builds/plain.py:112-119`. |
| Duplicate-dispatch protection | BUILT | A flock on `<runtime>/dispatcher.lock` (exit 4 if held); the kernel `.kernel.lock`; fencing tokens; a launch is refused while a process with the attempt marker is alive. |
| Restart recovery | BUILT | Stage is re-derived from records every tick; workers are found by their marker; results are re-read from the whole log; landing and push intents prevent double pushes. Tests: `test_engineering_dispatcher.py:437-506`. |
| Stale candidate when trunk moves | BUILT, at landing only | A refresh revision (see Landing). |

## 3. Lifecycle and data flow as built

```
OWNER (phone) ─hold card─► CLIVE prod: submit_engineering_request (engineering_tools.py:939)
   │  base = trunk head SHA, checks = default_checks(paths), id = _free_id
   │  GitHub contents API, create-only ─► clive/control/worker-01-inbox:requests/<id>.json
DIRECTOR (interactive Claude session) ─hand-committed JSON─┘   (no CLI helper)
                                   ▼
worker-01: remote_engineering.py run   (poll → tick → publish, every 15 s)
  poll: fetch inbox → ≤100 records → preflight → claim → objective_from_request → intake (READY) → receipt
        (unfetched base → deferred up to 1 h, nothing burned)
                                   ▼
Dispatcher.tick (flock; objectives in id order; ≤12 steps each)
  READY ─ widen scope for generated files (r1→r2) ─ backoff / retry / max_concurrent ─►
     workspace → kernel.assign → skills plugin → ClaudeCodeWorker.launch (fresh HOME, dontAsk, file tools)
  ASSIGNED ─ init roster check ─► RUNNING ─ heartbeat/progress (lease 1800 s, stall 1200 s)
  RUNNING + result: commit tree → candidate SHA → protected-path check → generators → scope check
     → checks in NamespaceSandbox (synchronous) → push clive/objective/<id> → EVIDENCE_READY
  EVIDENCE_READY ─ acceptance.yml on the exact SHA (poll 60 s, ≤3600 s) ─┬ red → repair revision r+1
                                                                         └ green → reviewer (never the author)
  REVIEWING ─ READY → (green again) ACCEPTED │ CHANGES_REQUIRED → repair r+1 with findings verbatim
                                             │ (≥ max → BLOCKED "convergence limit")
  ACCEPTED → integrate (fast-forward) → DONE → land: green again, no protected path, base on trunk,
             SHA ⊇ trunk → git push <sha>:clive/trunk │ trunk moved → refresh revision (≤3, then Director)
  BLOCKED / OWNER_GATE: nothing further (resume only through the host CLI; owner gate cannot be lifted)
                                   ▼
publish status.json → clive/control/worker-01-status   ·   private stops over the tailnet
                                   ▼
CLIVE prod: engineering_status + Builds board ← status, request files, compare, objectives, judgment ledger
Deploy: release service + "Deploy now" on the owner's passkey (DEC-072): separate from all of the above
```

## 4. Exact schemas, states and flags

**Remote request `clive.remote_engineering_request.v1`** (`app/remote_engineering/requests.py:48-80`). Unknown fields are forbidden.
- **Required:** `request_id` (`^[a-z][a-z0-9]{0,15}(-[a-z0-9]{1,16}){1,7}$`, at most 80 characters), `title`, `requested_outcome`, `base_ref`, `base_sha` (40 hex), `allowed_paths` (at least one), `target_branch` (exactly `clive/objective/<request_id>`).
- **Optional:** `acceptance_criteria`, `checks` (`{name, argv, cwd=".", timeout_s ≤7200}`), `max_repair_rounds` (0–5 or null).
- **Absent:** priority, depends_on, skills, risk, project, supersedes, submitted_at, requested_by.

**Engineering Objective `clive.engineering_objective.v1`** (`objectives.py:256-277`). Extra fields are forbidden and the record is immutable. `authority_class="repository_only"`; 7 prohibited actions by default, which cannot be removed.

**Kernel `EngineeringTask`** adds `stream_id`, `kind`, `predecessor_task_ids`, `required_evidence`, `priority` (−100..100) and `authorising_reference` (`contracts.py:99-117`). A task revision can widen `allowed_paths` with an `authorising_reference` (the generated-files precedent, `dispatcher.py:909-939` ✔). **But a builder-written path must also lie inside the objective's immutable `allowed_paths`** (`dispatcher.py:828-829` ✔, found by the architect pass). Only loop-written generated files are exempt. So the loop cannot widen a builder's scope without changing that check.

**States**
- **`TaskStatus`:** proposed, ready, assigned, running, evidence_ready, reviewing, accepted, rejected, blocked, owner_gate, done, obsolete, cancelled.
- **Projected stages:** the upper-cased status, plus COMPLETE and UNKNOWN.
- **`BlockerClass`:** none, transient, deterministic, obsolete, owner_only.
- **Stop causes:** review_limit, github_red, github_waited, builder_blocked, owner_decision, checks_failed, worker_failures, workspace, launch_refused, no_reviewer, review_unavailable, sandbox, protected_scope, merge_conflict, owner_gate, other.
- **Worker report:** `status ∈ {completed, blocked, owner_decision_required}` with `summary` and `reason` (`claude.py:149-158` ✔).

**`DispatcherConfig` defaults** (`dispatcher.py:237-274`)

| Setting | Default |
|---|---|
| `lease_s` | 1800 |
| `stall_s` | 1200 |
| `attempt_timeout_s` | 14400 |
| `max_transient_retries` | 3 |
| `max_result_refusals` | 2 |
| `max_concurrent` | **1** |
| `acceptance_poll_s` | 60 |
| `acceptance_timeout_s` | 3600 |
| `land` | **True** |
| `max_landing_refreshes` | 3 |
| `builder_skills` | True |

**Loop scripts**
- `scripts/remote_engineering.py` takes `--max-concurrent` (default 1), `--reviewer`, `--default-repair-rounds` (default 2), `--branch`, `--status-branch`, `--interval` (default 15), `--private-listen`, `--private-allow-node`, `--no-land`, and the store, repo, runtime and worker flags.
- `scripts/engineering_dispatcher.py` also has the verbs `objective`, `integrate`, `tick`, `run`, `status`, `stops`, `probe-launch`, `probe-review` and `skill-entry`.

## 5. Extension points (where V1 attaches)

| Need | Seam |
|---|---|
| Dependency readiness | The adapter's deferral (`waits.py`) keeps a request waiting with nothing burned. A sibling "dependency wait" defers intake until every predecessor's candidate is on trunk. The dispatcher and kernel are unchanged. |
| Priority | Replace the alphabetical `read_all()` order at `_start_attempt` with `scheduler.py`'s ordering; `EngineeringTask.priority` is already in the schema. |
| Path conflicts | `allowed_paths` is the declared write-set; `_in_scope` and `_overlaps` exist (`dispatcher.py:2515`, `objectives.py:344`). |
| Scope envelope | **Not a seam.** See §4: builder-written paths are held to the objective's immutable scope (`dispatcher.py:828-829`). The envelope must be set at filing. |
| Metrics | Extend `engineering_measures.read_loop_records` (`:644-735`); add a check `finished_at`, keep the GitHub wait history, and record queue reasons. |
| Typed owner blockers | `_block(owner=…)` and the worker report's `owner_decision_required`; reuse CLIVE `BLOCKER_KINDS`, `builds/decisions.py` and the judgment ledger. |
| Supervisor CLI | Host verbs exist (`engineering_dispatcher.py status/stops`, `remote_engineering.py status/stops`, `engineering_kernel.py resume`, `engineering_measures.py`). Missing: a filing helper that wraps `engineering_bridge.requests.build_request` (`:87-149`), and project views. |
| Skill routing | `_skills_for(obj, task, attempt)` can filter `allow.skills` per objective, still hash-verified; `verify_started` already requires the roster to equal the folder. |
| Quality routing | `checks` are per-objective argv derived by `default_checks(paths)`. The final gate (`acceptance.yml` → `acceptance_provenance.py`: ruff, control-plane pytest, product-memory structure, full offline pytest including browser tests, gitleaks) is the same for every SHA. |

## 6. Duplications V1 must avoid

1. A Project store that duplicates CLIVE `Objective` kinds `build` and `project`. Note the name collision: "objective" already means two records.
2. A new queue or scheduler. Use `Dispatcher.tick` and `scheduler.py`.
3. New metrics plumbing. `engineering_measures` exists; fix its four defects (see [BASELINE_EVIDENCE.md](./BASELINE_EVIDENCE.md)).
4. Repair-evidence plumbing. Already built (PR 9 of the draft sequence is largely done).
5. A fifth blocked-reason taxonomy. Consolidate `STOP_CAUSES`, the `plain.py` regexes, `BlockerClass` and `BLOCKER_KINDS`.
6. Owner-decision UX. The `builds/decisions.py` cards and the judgment ledger exist.
7. Convergence tasks. `integrate` and the integrator driver exist.
8. A Desktop status surface. `engineering_status`, Builds and `status.json` exist.
9. A browser verifier. Exact-SHA CI already runs Chromium screen tests.
10. An intent-to-spec path from scratch. The CLIVE filer, research ideas and capability gaps already turn intent into a hold-gated request.

## 7. Where the draft planning package was wrong

- "SSH to the real CLIVE engineering host": this host is production (see HOST_AUDIT_RESULTS).
- The concurrency ladder starts at 1. Worker-01 already overlaps ≥4 builders, and parallel builders were never approved.
- PRs 2 and 6 assumed no dependency or priority concepts exist. They also ignored the protected-path and re-pin constraint.
- PR 1 (metrics) largely exists; the gaps are timings and an owner-attention source.
- PR 4 (skills): new skills need a protected PR and a re-pin, and work only on CLI 2.1.285 or 2.1.293.
- PR 8: Bench cannot run in the check sandbox, and browser evidence is already in exact-SHA CI.
- PR 9 (repair evidence) is already built. The real gap is owner answers reaching the loop.
- "GPT fallback reviewer" is a flag chosen at re-pin, not a runtime failover.
- Throughput: ETAB is dominated by full CI per candidate (~10 min each) and by refresh merges after trunk moves; landings run one per tick.

## 8. Tests that cover the loop (all under `tests/`; most are protected)

| Test file | Tests | Covers |
|---|---:|---|
| `test_engineering_dispatcher.py` | 86 | Restart, transient, stall, roster, scope, repair, convergence, owner gate, red repair, skills gating, stop reports, `earlier_try` |
| `test_loop_landing.py` | 35 | Landing |
| `test_loop_generated.py` | 16 | Generated files |
| `test_lifecycle_kernel.py` | 46 | The kernel |
| `test_remote_engineering.py` | 138 | Inbox bounds, idempotency, waits, projection, private channel |
| `test_engineering_objective_intake.py` | 19 | Objective intake |
| `test_check_sandbox.py` | 13 | Sandbox escape tests; `CLIVE_REQUIRE_CHECK_SANDBOX=1` fails closed |
| `test_claude_worker_adapter.py` | 33 | The builder adapter |
| `test_claude_reviewer.py` | 20 | The Claude reviewer |
| `test_gpt_reviewer.py` | 10 | Includes 3 concurrent objectives and the concurrency limit |
| `test_github_acceptance.py` | 39 | The GitHub acceptance gate |
| `test_review_*` | — | Review acceptance, result gate and routing |
| `test_engineering_bridge*.py`, `test_build_from_clive.py`, `test_engineering_status_bounds.py` | — | Production filing and status |
| `test_engineering_measures.py` | 24 | Measures |
| `test_engineering_loop_measures.py` | 26 | Measures from loop records |
| `test_builds.py` | 31 | The Builds board and decisions |
| `test_builds_browser.py` | 1 | Builds in a browser |
| `test_bench*.py` | — | Bench |
| `test_ci_workflow.py` | 15 | Workflow drift |

**Not covered by any test:** depends_on or priority scheduling, project grouping, workspace garbage collection, rate-limit pausing, and the inbox approaching its 100-record bound.
