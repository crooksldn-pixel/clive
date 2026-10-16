# Final implementation plan — CLIVE Autonomous Engineering V1

**Status:** APPROVED by George on 2026-10-15 (revision 4). **Stage A only is authorised.** Stage B and
any V1 application code wait for his further go. O-1 and O-2 are approved, and O-3 is deferred
until the baseline (DECISIONS.md).

**Progress (2026-10-16):** A1, RP1 and retiring the production-host loop are done
([STAGE_A_RUNBOOK.md](STAGE_A_RUNBOOK.md)). Two of RP1's DEC-068 rows wait for the first real repair or
re-file. PR 0, PR 1 and B0 were not in George's Stage A order and have not started.

**Written against:**
- trunk `ef204bc2` (DEC-079);
- production `dc59047e` (deployed 2026-10-14 19:45 UTC);
- a read-only audit of the production host.

**Reconciled with:**
- an independent architect pass;
- an adversarial review;
- two final reviews;
- the CLIVE Director's architectural cross-check of 15 Oct ([PLAN_REVIEW.md](PLAN_REVIEW.md) §5).

**Evidence:**
- [CURRENT_ENGINEERING_REALITY.md](CURRENT_ENGINEERING_REALITY.md)
- [audit/REPO_AUDIT.md](audit/REPO_AUDIT.md)
- [audit/HOST_AUDIT_RESULTS.md](audit/HOST_AUDIT_RESULTS.md)
- [audit/BASELINE_EVIDENCE.md](audit/BASELINE_EVIDENCE.md)

**Design:**
- [ARCHITECTURE.md](ARCHITECTURE.md)
- [FILING_AUTHORITY.md](FILING_AUTHORITY.md), the ruling-9 model, for George's approval.

**Decisions:** [DECISIONS.md](DECISIONS.md).

**One disclosure about the audit.** It was read-only except for one incidental write. A `git status`
on the production checkout let git refresh its index stat cache, rewriting `/opt/crooks-os/.git/index`
at 2026-10-14 11:40:50 UTC. HEAD, refs, the working tree and the running service were unchanged. Every
later command set `GIT_OPTIONAL_LOCKS=0` ([audit/HOST_AUDIT_RESULTS.md](audit/HOST_AUDIT_RESULTS.md) §8).

## What governs this plan

- **DEC-018 stays in force** (DEC-079, ruling 0). V1 does three things only:
  - makes what George already approved work correctly: the loop, its reviewer, findings fed back,
    filing and Builds;
  - adds capacity (ruling 4);
  - builds the narrower filing-authority model he asked for (ruling 9).

  It never decomposes an intention into work he has not seen, never files proactively, and never
  adjusts its own policy.
- **Ruling 4: parallel engineering is allowed.** Concurrency is an engineering setting chosen by
  measurement. Three things bound it:
  - host resources;
  - the one Max plan, with live CLIVE and staff use first;
  - DEC-012 (a worktree of its own for each worker) and DEC-043 (separable scope plus an integration
    gate).

  It is not an owner decision.
- **Ruling 9: the per-filing hold goes, through a model.** The model is
  [FILING_AUTHORITY.md](FILING_AUTHORITY.md). Until it is built, every filing waits for his hold. A
  confirmed "Try again" is his hold for that exact re-file; DEC-082 builds that.
- **One implementation per behaviour.** The Director owns:
  - DEC-080: outside text cannot trigger CLIVE's instant actions;
  - DEC-081: no draft order before his hold; a change fails if its record cannot be written; pinned
    Python dependencies; Actions pinned to SHAs in `acceptance.yml`. This plan rebases on it;
  - DEC-082: "verified" needs evidence; build items advance from loop records; the MAP and FEATURES
    check; "Try again" files `<id>-N` on his confirmed answer.

  **This plan does not build any of them.** DEC-080 to DEC-082 were not yet on trunk at `ef204bc2`;
  this plan coordinates with them as they land.
- **Built, waiting only on the worker-01 re-pin: verify, don't rebuild.**
  - DEC-068: findings reach repairs and re-files; 0–5 repair rounds; builder skills; a browser for
    checks;
  - DEC-076: the Claude reviewer.

## How to read this plan

**Four facts from the source shape it.**

1. **The loop cannot build its own control plane.** Control-plane files are protected paths.
   - **Director PRs:** those PRs are built by a Director session.
   - **Loop code** takes effect only at a re-pin of worker-01. George does that over Termius, and
     `root-repin.sh` reviews it.
   - **Production code** takes effect only at a deploy he decides (DEC-072, DEPLOY_LINUX).
2. **Kernel records are strict** (`extra="forbid"`). New loop facts ride in optional request fields
   and an adapter-root sidecar. Production-side additions to build objectives use the objectives
   store's existing rollback-safe design file.
3. **A builder can only write inside the objective's immutable `allowed_paths`**
   (`dispatcher.py:828-829`). Scope is fixed at filing, so the preflight must make it right.
4. **The bottleneck** is the 74 requests on worker-01, 25 Sep–8 Oct, of which 26 completed and 44
   blocked. The 44 blocks (the Director's grouping, which matches BASELINE_EVIDENCE §2):

   | Cause | Blocks |
   |---|---:|
   | Review not converging | 18 |
   | Environment or base | 9 |
   | CI or checks red | 9 |
   | Scope | 8 |

   Re-files multiply all of it. That is why the order below is:
   1. re-pin, which brings in the findings fed back and the Claude reviewer;
   2. measure;
   3. preflight;
   4. "Try again" (DEC-082);
   5. archiving;
   6. only then the new loop semantics, the filing model and the baseline replays.

**Review and merge rule (existing practice, made explicit) for every Director PR:**
- The reviewer is a session started by someone other than the author, with a fixed packet: the
  diff at the PR's exact head plus this plan's contract for it.
- The verdict is recorded on the PR as `clive.review_result.v1`, naming the SHA. A new commit voids
  it.
- The merge happens only at that SHA, with green `acceptance.yml`, by a session that is neither the
  author nor the reviewer.
- The effect is gated by George's re-pin or deploy.

**Focused tests:** `cd crooks-assistant && .venv/bin/pytest tests/<file> -q -p no:cacheprovider`.
Every PR keeps `make lint` and its focused tests green. **Loop-eligible** PRs (no protected path)
are filed to worker-01 as ordinary requests.

---

## Stage A — now: truth, the re-pin, and measurement

### A1 — worker-01 read-only audit
- **Who:** George, or a session he authorises on clive-worker-01.
- **What:** run [WORKER01_AUDIT.md](WORKER01_AUDIT.md). Record the results in
  CURRENT_ENGINEERING_REALITY; private-channel and tailnet values are recorded as present or absent
  only.
- **Acceptance:** each worker-01 UNKNOWN has a value and a source line: the pin, the CLI version,
  `--max-concurrent`, `--reviewer`, the private channel, Chromium, disk, lease cancellations, and
  rate-limit lines.
- **State change:** none (read-only; `GIT_OPTIONAL_LOCKS=0`).
- **Why first:** the RP1 rollback target is the pin it records.

### PR 0 — Current truth catches up; the planning package reaches trunk (docs; Director)
- **Problem:** CURRENT_TRUTH is stale:
  - it says production is `b33ccbc2` and not the `dc59047e` deployed on 14 Oct;
  - it says the loop has been "quiet since 1 Oct";
  - it omits that the production-host loop is still running;
  - it omits that worker-01 reviews with GPT.

  This plan's inputs (audit records, templates, baseline scripts) are on the planning branch only.
- **Scope:**
  - `CURRENT_TRUTH.md`; any missing deploy records (`09b633cc`, `dc59047e`); MAP's `map:live`;
  - `projects/autonomous-engineering-v1/` as approved.

  **Not carried:** `.mcp.json` (Context7), `.claude/agents/autonomy-*`, the planning section of
  root `CLAUDE.md`, and the planning skills. An MCP server for every session would be George's to
  approve (DEC-064), and none of these is needed by V1.
- **State change:** none.
- **Acceptance:**
  - `git diff --stat` touches only `crooks-assistant/docs/product-memory/CURRENT_TRUTH.md`,
    `crooks-assistant/reports/`, `crooks-assistant/MAP.md` and `projects/autonomous-engineering-v1/`;
  - the facts above are stated;
  - `python scripts/map.py --check` passes.
- **Tests:** `tests/test_product_memory_structure.py`; `make lint`.
- **Owner-visible:** CLIVE's account of itself is true.
- **Risk:** low.
- **Rollback:** revert.
- **Dependencies:** none.
- **Metric:** n/a.

### RP1 — Re-pin worker-01 to the trunk head; verify DEC-068 and DEC-076; retire the production-host loop
- **Problem:**
  - worker-01 runs an unknown pin. Its 44 verdicts are all GPT.
  - "Review not converging" (18 blocks) is what DEC-068 attacks: findings reach repairs verbatim, a
    re-file starts from the earlier stop report, and 0–5 repair rounds. All of it is built and none
    of it is in force.
- **Reuse:** the existing re-pin procedure (`root-repin.sh`), `probe-launch`, `probe-review`.
- **Steps (George, one Termius session):**
  1. Run `root-repin.sh` on the trunk head.
  2. Set the unit flags:
     - `--reviewer claude`;
     - `--max-concurrent 2`, an engineering setting under ruling 4. It stays conservative until
       RP2's plan-limit pause exists, with live CLIVE first;
     - `--default-repair-rounds 2`;
     - `--private-listen` per DEC-068, and, if O-2 chooses the channel route for the supervisor,
       `--private-allow-node` naming worker-01's own full tailnet name;
     - `--sandbox-browsers` and `--sandbox-node-path` if A1 found Chromium and node;
     - **the workspace root on the repository's filesystem.** This is the host-side EXDEV fix for 4 of
       the "environment or base" blocks;
     - `--no-builder-skills` unless the CLI is 2.1.285 or 2.1.293.
  3. Run the probes; both must PASS.
  4. Restart the loop.
  5. Then **stop and disable `clive-remote-engineering` on the production host**, as ruling 11 says:
     after the re-pin. Keep its directories; delete nothing.
- **Verification checklist** (each item ticked from records, never assumed):

  | DEC | Behaviour | Proof |
  |---|---|---|
  | DEC-076 | Claude reviewer | A smoke request gets a `claude-reviewer` verdict |
  | DEC-068 | Findings reach the repair verbatim | The repair revision's brief carries them (runtime evidence) |
  | DEC-068 | A `-N` re-file starts from the earlier stop report | `earlier_try` in its attempt notes |
  | DEC-068 | Repair rounds 0–5 honoured | — |
  | DEC-068 | Stop reports kept 0600 and served on `--private-listen` to production only (and to worker-01 itself, if O-2 chooses `--private-allow-node`) | — |
  | DEC-068 | Skills | Only on a gated CLI: `probe-launch --skill-turn` |
  | DEC-068 | Browser in checks | Only if bound |

- **Acceptance:**
  - every checklist row is ticked or marked "not applicable on this host";
  - a docs-only smoke request (filed by George's hold) reaches COMPLETE and lands;
  - `clive/control/status` stops heartbeating;
  - a commit to `owner-inbox` is built nowhere.
- **Cheap rollback rehearsal** (before declaring RP1 done):
  - copy the post-smoke store;
  - run the A1 pin's `remote_engineering.py status` and one `tick --no-land` against the copy, side
    effect free (scratch runtime, throwaway local remote, stub worker and reviewer, no network).
  - If it refuses a record RP1 wrote, the rollback target becomes the oldest pin that passes.
  - DEC-068 changed no kernel contract (PR #102), so this is expected to pass.
- **Residual risk, accepted and watched:** the Claude reviewer arrives before RP2's plan-limit pause.
  A plan limit can then fail three review runs and block a task. The block is visible and recoverable
  ("Try again"), and concurrency 2 keeps load low. B0 counts any such blocks.
- **Rollback:**
  - re-pin the rehearsed pin (the A1 pin, unless the rehearsal said otherwise);
  - `systemctl enable --now clive-remote-engineering` on the production host if needed.
- **Owner-visible:** the reviewer he chose; repairs that know why they failed; one loop.

### PR 1 — Measures that measure; the attention and defect ledgers (loop-eligible)
- **Problem:**
  - OAMAB and ABER have no instrument.
  - `engineering_measures` has four defects (BASELINE_EVIDENCE §4).
- **Reuse:** `app/engineering_measures.py` and `scripts/engineering_measures.py` (with their
  `--attention-log` schema), and the baseline scripts (on trunk from PR 0).
- **Scope:**
  - Fix the four defects:
    - the PR regex for `(PR #N)`;
    - per-SHA reachability instead of first-parent;
    - only verdicts count as review rounds;
    - BLOCKED is never "landed by the loop".
  - Move the scripts into `scripts/engineering_baseline.py`. It computes stage timings from the
    status snapshot history, with no loop change.
  - Derive owner attention from existing records, as timestamps and counts only:
    - judgment-ledger `decided_at`, filing holds and deploy approvals;
    - supervisor and Director transcripts, counted as min(gap, 5 min) + 1 per owner message.
      **Starting a session counts.**
  - Add `--add` for relays.
  - Add a defect ledger.
- **State change:** two local JSONL ledgers, holding no customer data and no message text.
- **Acceptance:**
  - a trimmed fixture from snapshot `ffa815d6` (under `tests/fixtures/`) reproduces
    BASELINE_EVIDENCE's counts for its rows;
  - PR numbers are filled for #8, #9, #11 and #25;
  - a fixture transcript yields the expected minutes and stores no text.
- **Tests:** `test_engineering_measures.py`, `test_engineering_loop_measures.py`, a new
  `test_engineering_baseline.py`.
- **Owner-visible:** a number for what a build costs him.
- **Risk:** low.
- **Rollback:** revert.
- **Dependencies:** PR 0.
- **Who:** the loop (dogfood), filed with his hold.
- **Metric:** every BASELINE_PLAN metric has a value or a stated reason it has none.

### B0 — the "before" window
From RP1 until D1 (aim for at least 7 days), real work is filed as today, with the ledger on.
- **It gives:** OAMAB, chain ETAB, and blocks by cause on the re-pinned loop.
- **What it isolates:** DEC-068's and DEC-076's effect on "review not converging", before any V1
  change.

---

## Stage B — D1: the preflight and the inbox cliff

### PR 2 — Archive-safe ids and readers (protected; Director; roll forward only)
- **Problem:**
  - The inbox refuses **all** intake above 100 files, and 75 are used.
  - Archiving is safe only if an id is never reused. A receipted id that reappears with different
    bytes makes the loop refuse every snapshot (`controller.py:245-249`). Yet `_free_id` checks only
    `requests/` (`engineering_tools.py:1069-1086`).
- **Scope:**
  - `_free_id` consults `requests/`, `archive/` and every receipt in the status.
  - `engineering_bridge/github.py` and `app/builds/read.py` read `archive/<id>.json` when
    `requests/<id>.json` is absent.
  - The library gets `archive(min_age_days, headroom)` and `unarchive()`. `unarchive` refuses past
    the 100-record bound.
- **Once `archive` has run, this PR rolls forward only.** Unarchiving about 72 records could exceed
  the bound; dropping the PR would let ids be reused.
- **State change:** none in the loop. The inbox can hold `archive/`, which the loop never lists.
- **Acceptance:**
  - no title is ever given an archived or receipted id;
  - an archived request's title shows on Builds;
  - `archive` moves only receipted, terminal requests;
  - `unarchive` refuses past the bound.
- **Tests:** `test_engineering_bridge.py`, `test_build_from_clive.py`, `test_builds.py`.
- **Owner-visible:** the inbox's cliff is gone.
- **Risk:** low.
- **Rollback:** before archiving, redeploy; after it, roll forward only (drill 17).
- **Dependencies:** none.
- **Metric:** intake refusals at the bound (target 0).

### PR 3 — The preflight inside `submit_engineering_request` (protected; Director)
- **Problem:** "environment or base" (9), "CI or checks red" (9) and "scope" (8) blocks are found by
  a builder, or by CI 20–40 minutes later. Every filer goes through `submit_engineering_request`: CLIVE
  chat, research "Approve the work", DEC-082's "Try again", and later the supervisor's drafts. The
  check therefore belongs there, once.
- **Reuse:** `build_request`, `default_checks`, `PROTECTED_PATHS`, `github_acceptance`, PR 2's id
  check.
- **Scope:** a new `app/engineering_bridge/preflight.py`, called inside `submit_engineering_request`
  before the card.
  1. **Base.** The trunk head.
     - Green: file.
     - Pending: file and say so.
     - **Red: refuse, "Director work first".** Landing needs the head, so an older base only moves
       the stop.
     - Unknown (no Actions read): file and say so.
  2. **Scope.**
     - Paths exist at the base, or their parent directory does; areas are preferred.
     - **Paired test modules** join scope and checks.
     - A protected path is refused as Director work.
  3. **Toolchain and environment**, checked against the **worker profile**:
     - `config/worker_profile.json` (protected) records the audited facts at RP1: the interpreter
       path, node, Chromium, the CLI version, and whether builders have a shell (no);
     - it is replaced by the loop's live `loop{}` once RP2 publishes it;
     - every check's argv must name an interpreter the worker has;
     - a check needing node or Chromium is refused when the worker lacks it;
     - **declared check time** is at most 600 s;
     - acceptance criteria that need deleting or renaming files, or running a shell, are flagged
       "builders have no shell: Director or generator work". This is advisory text on the card.
  4. **Ids.** Through PR 2.
  5. **New request fields** only when the live loop advertises them (RP2).
  6. **Customer details and secrets**, by the bridge's rules.
  7. **No finding text in any request** (DEC-068).
- **State change:**
  - `config/worker_profile.json`;
  - `PROTECTED_PATHS` gains `crooks-assistant/config/worker_profile.json`. `PROTECTED_PATHS` lives in
    `app/orchestrator/objectives.py` and is shared by production's filer, so production refuses a
    request naming the profile from D1, and the loop does too from RP2.
- **Acceptance:** each case is refused or normalised, with the reason on the card:
  - a protected path;
  - a missing directory;
  - a red head;
  - a check naming an absent interpreter;
  - node needed on a worker without it;
  - checks summing past 600 s;
  - a deletion-shaped criterion flagged;
  - a customer email;
  - a new field before it is advertised.

  All filers reach the same function. A test covers each entry point: chat, research approval, and
  "Try again" through DEC-082's hook.
- **Tests:** a new `test_engineering_preflight.py`, `test_engineering_bridge.py`,
  `test_build_from_clive.py`, `test_engineering_bridge_bounds.py`.
- **Owner-visible:** fewer builds that stop for reasons unrelated to their code. The card says what
  the preflight changed or found.
- **Risk:** medium. It is the held filer.
- **Rollback:** a revert PR, then a deploy. PR 2 stays.
- **Dependencies:**
  - PR 2;
  - A1, for the worker profile;
  - **DEC-081 on trunk, to rebase on**;
  - **DEC-082 coordinated**: its "Try again" calls this path; it does not duplicate it.
- **Metric:** environment, base, checks and scope stops per filed request, against B0.

### D1 — deploy (George's decision; DEC-072 and DEPLOY_LINUX)
- **What:** trunk carrying PRs 2 and 3, plus whatever the Director has landed by then (DEC-080 to
  DEC-082).
- **Then:** the Director runs the library's `archive` once by hand (about 72 records). Automatic
  archiving waits for O-1.
- **From then on**, any request the Director still commits by hand must first be checked against
  `archive/` and the status receipts for its id. One reused id makes the loop refuse every snapshot
  (`controller.py:245-249`).
- **Acceptance:** phone check; inbox headroom ≥ 90; archived titles shown.
- **Rollback:** a revert of PR 3, then a deploy. PR 2 stays.

---

## Stage C — RP2: the loop changes (one re-pin)

### PR 4 — Dependencies at intake (protected; Director)
- **Problem:** dependent work must be filed by hand after its predecessor lands, which needs a
  supervisor present. A dependent filed early would be built without its predecessor's code.
- **Reuse:**
  - `waits.py` deferral (no claim, nothing burned, restart-safe);
  - `objective_from_request`;
  - kernel integrations;
  - `git.is_ancestor`;
  - `GitHubAcceptance`;
  - the unused `predecessor_task_ids`;
  - status `waiting_requests`.
- **Scope:**
  - **Optional request fields** (schema v1), refused visibly by an older loop:
    - `depends_on` (at most 8 ids);
    - `supersedes`;
    - `land` (default true).

    **There is no `project` field.** The project is the build objective on production, which the
    loop never needs to read.
  - **`controller._await_dependencies`.** An id is satisfied when an admitted request in its
    `supersedes` closure has an integration whose SHA is an ancestor of the trunk head. A squash merge
    does not count, and the Director rule is never to squash a loop candidate.
  - **The wait is bounded** by `--dependency-wait-s`, default 7 days (an engineering setting).
  - **Admission-time base:** the trunk head when it is green and contains the predecessors.
  - **Replay chains** (`land: false`): a dependency is satisfied by COMPLETE, and the base is the
    single predecessor's integrated SHA.
  - **The `links/<id>.json` sidecar** holds these facts at admission; `predecessor_task_ids` is filled.
  - **The status** shows `waiting_on`.
- **State change:** adapter-root `links/` and `dependency-waits/`.
- **Acceptance:**
  - **A → B → C filed together:** B and C are deferred, nothing is burned, and each is admitted on a
    green head containing its predecessor.
  - **A blocks:** B and C wait with `waiting_on: [A]`.
  - **A-2 supersedes A and lands:** B proceeds.
  - **Restart:** waits survive it.
  - **A v1 request without the fields:** byte-identical to today.
- **Tests:** `test_remote_engineering.py`, `test_engineering_objective_intake.py`, and a new
  end-to-end three-member chain through the real kernel with a fake worker.
- **Owner-visible:** an approved plan proceeds step by step with nobody filing the next one.
- **Risk:** medium-high (intake). A waiting dependent is always visible, bounded and re-fileable.
- **Rollback:** see RP2.
- **Dependencies:** PR 3.
- **Metric:** courier filings per plan (target 0).

### PR 5a — FIFO and the clone fix (protected; Director)
- **Problem:** the start order is alphabetical (`objectives.py:411-417`). An explicit
  `clone --bare --local` dies on a failed hard link across filesystems (`workspaces.py:123`).
- **Reuse:** `Dispatcher.tick`, `scheduler.py`'s ordering key, `WorkspaceManager.create`.
- **Scope:**
  - start order by admission (`created_at`, then id), using `scheduler.py`'s key (ruling 41);
  - drop the explicit `--local`.
- **State change:** none. The order of starts changes; no record changes.
- **Acceptance:** admission order is kept regardless of id; a cross-filesystem workspace is copied.
- **Tests:** `test_engineering_dispatcher.py`.
- **Owner-visible:** builds are taken in the order asked.
- **Risk:** low.
- **Rollback:** re-pin.
- **Dependencies:** none.
- **Metric:** workspace errors (target 0).

### PR 5b — One knob for builders and reviews; the plan-limit pause (protected; Director)
- **Problem:**
  - `_dispatch_review` never checks `max_concurrent`, and `_live_count` counts builders only
    (`dispatcher.py:489-495,511`).
  - Plan limits are retried as transients. With the Claude reviewer, three failed review runs block
    the task.
  - The 30 Sep decision asked to "pause launches before the allowance runs out".
  - Ruling 4 puts live CLIVE and staff use first.
- **Reuse:** `_live_count`, `_start_attempt`, `_dispatch_review`, `Activity.rate_limited`
  (`workers/claude.py:672-675`), `TRANSIENT` handling, the runtime notes.
- **Scope:**
  - `_live_count` counts REVIEWING, and `_dispatch_review` waits at the cap.
  - **At `allowed_warning`:** start no new builds or reviews (`soft_paused_until`, 30 min,
    re-evaluated). Running work finishes.
  - **At a limit:** cancel with `plan_limit:`. It costs no retry, review run or repair round. The loop
    sets `paused_until` (the reset time, else 30 min, at most 7 days) and publishes it.
- **State change:** two runtime notes, `paused_until` and `soft_paused_until`, both published in
  `status.json`.
- **Acceptance:**
  - at cap 1, a pending review blocks a new build and vice versa, with no deadlock;
  - `allowed_warning` stops new starts;
  - "hit your session limit · resets 3:45pm" pauses until 15:45, with zero cost.
- **Tests:** `test_engineering_dispatcher.py`, `test_claude_worker_adapter.py`,
  `test_claude_reviewer.py`.
- **Owner-visible:** the loop stops starting work as the allowance nears its end, so his own CLIVE is
  not the one that hits it.
- **Risk:** medium. The pause is bounded, published, and shown by `clive-eng status`.
- **Rollback:** re-pin.
- **Dependencies:** none.
- **Metric:** work lost to plan limits (target 0); minutes paused per day.

### PR 5c — `land: false` integrated without a landing proof (protected; Director)
- **Problem:** the landing proof is written at integration whenever global `land` is on
  (`dispatcher.py:1464-1475`). Any pin then lands a proven integration, refreshing it if needed
  (`:1590-1615`, `:1667-1669`).
- **Reuse:** the existing `--no-land` integration path, which writes no proof; `_eligible`; `_land`.
- **Scope:**
  - `land: false` (from the sidecar), or an unreadable sidecar, means integrate without a proof;
  - `_land` skips it;
  - the status says "landing: off for this request".
- **State change:** integration records without a proof for those objectives; a landing record
  `off`.
- **Acceptance:** COMPLETE with no proof, and the RP2 rollback pin's `_eligible` returns None for it
  (tested against that pin's code). A corrupt sidecar behaves as `land: false`.
- **Tests:** `test_loop_landing.py`, `test_engineering_dispatcher.py`.
- **Owner-visible:** experiments never touch his trunk.
- **Risk:** low.
- **Rollback:** see RP2.
- **Dependencies:** PR 4.
- **Metric:** `bl-*` and `fi-*` SHAs on trunk (target 0).

### PR 6 — The loop describes itself; stop cause words; owner class; skill routing (protected; Director)
- **Problem:**
  - Pin, CLI, concurrency, reviewer and host load are unknowable from outside.
  - Causes are prose parsed twice.
  - Owner gates carry no class.
  - Every builder gets every skill.
- **Reuse:** `status.py` and the runner, `STOP_CAUSES`, `WORKER_REPORT_SCHEMA`, `plain.py`,
  `_skills_for`, `builder_skills.build_plugin`, `verify_started`, `PROTECTED_PATHS`, `_private_write`.
- **Scope:**
  - **`loop{}` in the status:**
    - `pin_sha`, `cli_version`, `max_concurrent`, `reviewer`, `land`, `default_repair_rounds`;
    - `builder_skills`, `sandbox_browsers`, `node`, `tick_max_s`;
    - `paused_until`, `soft_paused_until`, `capabilities[]`;
    - `host{loadavg_1m, mem_available_pct, psi_io_avg60}`.

    These are numbers or fixed words only. PR 3's preflight reads this in place of the static
    worker profile.
  - **`stop_cause`** from the `STOP_CAUSES` enum.
  - **`owner_class`**, required with `owner_decision_required`. One missing is refused once, then
    blocked. It is published as a fixed prefix.
  - **`applies_to` globs** in `builder_skills.json`:
    - `_skills_for` gives only matching skills; the design skills go to `web/**` and `app/builds/**`;
    - this is inert unless the CLI version is gated.
  - **`PROTECTED_PATHS` gains, in advance** (a protected path can be named before it exists):
    - `crooks-assistant/app/objectives/plans.py` (PR 7);
    - `crooks-assistant/scripts/clive_eng.py` (PR 10);
    - `crooks-assistant/config/worker_profile.json` (PR 3).

    The loop only learns protected paths at a re-pin, and none is planned after RP2.
  - **Stop reports readable by a named group.** `--stops-read-group <group>`, default off: the stops
    directory becomes 0750 and each file 0640, with that group. Today `_private_write` forces
    0700/0600 (`dispatcher.py:2328-2337`), so a read group cannot work without this. It is the route
    O-2 recommends for the supervisor.
- **State change:**
  - the published `status.json` gains `loop{}`, `stop_cause` and `owner_class`; readers tolerate
    their absence;
  - `config/builder_skills.json` gains `applies_to`;
  - `PROTECTED_PATHS` grows by three paths. **It is shared with production's filer, so production
    also refuses requests naming those paths from the next deploy (D2).**
  - the stops directory's mode, when the group is set.
- **Acceptance:**
  - `loop{}` carries the unit's real values and host numbers;
  - every BLOCKED request has a `stop_cause`;
  - an owner gate without a class is refused once;
  - on a gated CLI, the routed roster is verified at init.
- **Tests:** `test_remote_engineering.py`, `test_engineering_dispatcher.py`,
  `test_claude_worker_adapter.py`, `test_builds.py`.
- **Owner-visible:** Needs you holds real owner questions only.
- **Risk:** low.
- **Rollback:** re-pin.
- **Dependencies:** PR 5b.
- **Metric:** owner-class share of stops; builder input tokens per backend attempt.

### RP2 — Re-pin worker-01 carrying PRs 4–6
1. **Re-pin.** The same procedure as RP1. The flags carry on. Concurrency then follows the ladder
   (PR 13).
2. **Smoke.** A two-member `land: false` chain completes in order and is not on trunk; `loop{}` is
   published.
3. **Side-effect-free rollback rehearsal**, before declaring RP2 done:
   - take a copy of the RP2 store that includes one `land: false` objective still in flight;
   - run the RP1 pin's `status` and `tick --no-land` against it, with a scratch runtime, a throwaway
     local bare remote, a stub worker and reviewer, and no network.
   - If either refuses an RP2 record, the target becomes the oldest pin that passes.
4. **Rollback rule.** Re-pin the rehearsed target **with `--no-land`, until every `land: false`
   objective is terminal**.
   - An older pin does not read `links/`, so it would write a proof for in-flight replay work.
   - Work integrated under RP2 carries no proof, so it stays safe.
   - Real work integrated during the `--no-land` window gets no proof either, and the Director lands
     it by hand.
   - New `land: false` requests are refused by an older pin.

---

## Stage D — D2: the filing-authority model, the supervisor, project rows

**Gate:** George approves [FILING_AUTHORITY.md](FILING_AUTHORITY.md) (O-1). The supervisor's identity
is O-2.

### PR 7 — Authorised plans on build objectives (Director)
- **Problem:** ruling 9 needs a durable record of what he authorised together. The build objective
  already holds the owner's words, purpose, done-when, `engineering[]`, blockers and history, and
  only his screen can set `authorised`.
- **Reuse:**
  - `Objective(kind=build)`;
  - the rollback-safe design file (`design/obj_x.json`);
  - the item ladder and `authorise` (`store.py:1556-1578`);
  - `builds/decisions.py` cards and the judgment ledger.
- **Scope:**
  - **Plan items.** Each is a request spec: a reserved id, title, areas, criteria, `depends_on`
    among items, and repair rounds. They are kept in the design file.
  - **A plan card.** It shows every item. **One hold authorises the set**, recording its
    `judgment_id` and a digest of what he saw.
  - **A change** to an authorised plan is a new card.
  - **"Stop filing for this"** revokes it in one tap.
  - **A single request he files with his hold, linked to a build objective,** is recorded as an
    authorised one-item scope of that objective. A request with no objective has no scope.
  - The plan and authorisation code lives in a new `app/objectives/plans.py`, which PR 6 protects.
- **State change:** design-file fields on build objectives. An older build reads them as plain
  objectives, so untapped filing simply stops: the safe direction.
- **Acceptance:**
  - a three-item plan shows as one card and one hold authorises all three;
  - a change after authorisation needs a new hold;
  - revocation stops untapped filing;
  - an older build reads the objective without error.
- **Tests:** `test_objectives*.py` (store), `test_builds.py`, `test_builds_browser.py`.
- **Owner-visible:** he approves a plan once, seeing every step.
- **Risk:** medium (an authority record). It is Director-built. `app/objectives/plans.py` is protected
  from RP2 (PR 6), so the loop can never edit it.
- **Rollback:** redeploy; untapped filing stops.
- **Dependencies:** O-1; DEC-082 (build items from loop records), coordinated, not duplicated.
- **Metric:** plan cards per project (target 1, unless he changes the plan).

### PR 8 — `filing_decision` on the filing path; the supervisor's draft channel; "Allow the change"; archive housekeeping (protected; Director)
- **Problem:**
  - Every filing waits for a hold, and ruling 9 removes that in principle.
  - The supervisor must file only through CLIVE.
  - Owner-gate stops are dead ends today.
  - Archiving is by hand.
- **Reuse:** PR 3's preflight, PR 7's plans, `submit_engineering_request`, the judgment ledger, the
  private stops channel, PR 2's `archive`.
- **Scope:** exactly [FILING_AUTHORITY.md](FILING_AUTHORITY.md):
  - **`filing_decision`** gives FILE, HOLD or REFUSE, with the approved bounds. It compares structured
    fields only (DEC-080). A filing that carries his gesture for exactly this draft is FILE, subject
    only to REFUSE and the preflight. A plan's authorisation is verified against the protected judgment
    ledger, never trusted from the design file alone.
  - **`POST /engineering/drafts`**, tailnet only, from the supervisor identity (O-2). Drafts carry
    finding ids and dispositions, never finding text.
  - **"Allow the change":** the path delta comes from the private stop, and his hold files the re-file
    and widens that item.
  - **Automatic archiving** when headroom falls below 30.
  - **Every untapped filing** is recorded with its rule and shown on Builds.
- **State change:** the objective's history entries; the inbox `archive/`.
- **Acceptance:**
  - **Retries:** a retry of an authorised item files without a tap, up to the bound, and the next is
    held.
  - **Splits:** files only when the parts' paths lie inside the item's and its criteria are
    partitioned.
  - **Held:** a draft adding a path or criterion; any draft on an unauthorised objective.
  - **Refused:** a protected path; a red head.
  - **Source:** a draft from any source but the supervisor identity is refused.
  - **No text-driven filings:** no finding text reaches GitHub, and outside text cannot change a
    decision (tests in DEC-080's style).
  - **"Allow the change":** shows the exact delta.
  - **Archive:** moves only receipted, terminal requests.
  - **Filings he gestured:**
    - a confirmed "Try again" on a request with **no** authorised plan files with **no second card**;
    - so does his third "Try again" on a plan item;
    - owner-gestured filings never consume the untapped bounds.
  - **Tampered records:** a plan record whose `judgment_id` or digest does not match the judgment
    ledger is HOLD.
- **Tests:** a new `test_filing_authority.py`, `test_engineering_bridge.py`, `test_builds.py`,
  `test_builds_browser.py`.
- **Owner-visible:** one hold per plan, not per request. "Allow the change" acts.
- **Risk:** **high**. This is the authority boundary, so it gets an independent review recorded at
  the exact SHA, and targeted negative tests.
- **Rollback:** redeploy. Every filing then waits for his hold again, the safe direction.
- **Dependencies:** O-1, O-2, PR 7, RP2 (`depends_on`, `supersedes`), DEC-080.
- **Metric:** holds per accepted build; untapped filings per plan; owner answers left unacted
  (target 0).

### PR 9 — Builds: project rows on the build objective (loop-eligible)
- **Problem:** the board groups only by `-N` family.
- **Reuse:**
  - `board.py`, `read.py`, `plain.py`;
  - `Objective(kind=build)` `engineering[]`;
  - **DEC-082's item advancement from loop records**, used, not rebuilt.
- **Scope:**
  - `app/builds/projects.py`, a pure `project_view(objective, requests, status)`, shared with
    `clive-eng`. One row per build objective.
  - **Members keep their road:** Filed → Built (completed, not verified) → Reviewed (verified) → On the
    trunk → Live.
  - **Project states:**
    - Queued;
    - In progress — x of n on the trunk;
    - Waiting on <member>;
    - Needs you;
    - Stopped — waiting for the Director (N, oldest X h);
    - On the trunk, not live yet;
    - Live;
    - Filing stopped (after revocation).
  - `land: false` work sits behind "Measurements". A status older than 30 min says so.
- **State change:** none. It is derived.
- **Acceptance:**
  - a three-request objective renders as one row;
  - a re-file replaces its predecessor;
  - measurements are hidden;
  - a status without the new fields renders as today;
  - browser test at phone and tablet sizes.
- **Tests:** `test_builds.py`, a new `test_builds_projects.py`, `test_builds_browser.py`.
- **Owner-visible:** one row per thing he asked for.
- **Risk:** low.
- **Rollback:** redeploy.
- **Dependencies:** RP2; DEC-082.
- **Metric:** rows per authorised plan.

### PR 10a — `clive-eng` read verbs and triage (protected; Director)
- **Problem:** the supervisor reads `status.json` by eye. After a repair limit, nobody judges findings
  without George starting a session and relaying.
- **Scope:** `scripts/clive_eng.py` is a thin `--json` shell over the shared engineering library
  (protected from RP2, PR 6). It runs on worker-01 as the supervisor user (O-2). Verbs:

  | Verb | What it does |
  |---|---|
  | `status` | Needs-you first; the Director queue with its age; `paused_until` |
  | `show <id> [--why]` | `--why` reads stop reports through the access O-2 grants |
  | `triage` | Lists Director-class stops |
  | `judge <id>` | Records a disposition per finding id (valid, false, verifier defect) into a local draft. **A disposition never dismisses a finding** |
  | `decisions` | Owner-class questions as one list |
  | `measure` | — |
  | `deploy-brief [<sha>]` | Recorded reviews, exact-SHA green, behaviour-path changes, and an existing Bench report, if any |

- **What it never does:** write the inbox; raise repair rounds; touch protected paths; land; deploy.
- **The supervisor skill.** `.claude/skills/clive-project-compiler/SKILL.md` is for the supervisor
  only, never a builder skill. It covers turning George's intention into a draft plan *he sees on a
  plan card*:
  - read CURRENT_TRUTH and MAP first;
  - separate facts from assumptions;
  - ask only owner-class questions, batched;
  - order overlapping items with `depends_on` (DEC-043);
  - add a tests-first root item and a final integrating item for multi-item plans;
  - never decompose without his seeing it (DEC-018);
  - never squash a loop candidate.
- **State change:** `judge` writes a local draft file in the supervisor's home on worker-01. Nothing
  else is written.
- **Acceptance:**
  - every verb has `--json`;
  - `status` matches the board's grouping;
  - `judge` never changes a finding's state anywhere;
  - `show --why` returns a stop report through the access O-2 chose.
- **Tests:** a new `test_clive_eng.py` (fixtures, no network).
- **Owner-visible:** a supervisor session can clear the Director queue without him relaying.
- **Risk:** low (read-only).
- **Rollback:** revert.
- **Dependencies:**
  - O-2 (the user and its access to stop reports);
  - for stop reports: either RP1's `--private-allow-node` for worker-01, or RP2's `--stops-read-group`
    (PR 6).

  Usable before PR 8.
- **Metric:** Director-queue age.

### PR 10b — `clive-eng draft` (protected; Director)
- **Problem:** after PR 10a, the supervisor can judge findings but has no way to propose the re-file
  except asking George, which makes him a courier.
- **Reuse:** PR 8's draft channel and `filing_decision`; PR 10a's local draft; the shared library's
  request builder.
- **State change:** none on worker-01 beyond the local draft. CLIVE's filing path decides and writes.
- **Scope:** submits a structured draft (retry, split, item or dependency, with dispositions) to PR 8's
  channel, and prints FILE, HOLD or REFUSE.
- **Acceptance:**
  - a retry inside an authorised item files;
  - a widened draft becomes a card;
  - the CLI holds no GitHub write credential.
- **Tests:** `test_clive_eng.py`.
- **Dependencies:** PR 8.
- **Rollback:** revert.
- **Risk:** low; the authority sits in PR 8.
- **Owner-visible:** retries happen without him; anything wider reaches him as one card.
- **Metric:** HOLD share of drafts.

### D2 — deploy (George's decision)
- **What:** PRs 7, 8 and 9. Production's `.env` gains `CROOKS_ENGINEERING_PRIVATE_URL`, as DEC-068
  provides.
- **Acceptance:** phone check; a plan card; one untapped retry shown on Builds.
- **Rollback:** redeploy; every filing waits for his hold again.

---

## Stage E — measurement and V1

### PR 11 — Baseline replays B1 (loop-eligible plus operator)
- **Problem:** there is no fixed task set, so before and after cannot be compared on the machine side.
- **Reuse:** the ten historical requests (BASELINE_EVIDENCE §5), `land: false` (PR 5c), the replay
  chains (PR 4), `measure` (PR 1).
- **Scope:**
  - `baseline/tasks/<n>.json`: the ten historical requests (BASELINE_EVIDENCE §5), `land: false`,
    ids `bl-<n>-<run>`;
  - **filed by George's hold, as one batch.** Once PR 8 is live, they can be filed as an authorised
    measurement plan;
  - **run twice**, overnight, at the RP2 concurrency.
- **State change:** `clive/objective/bl-*` branches.
- **Acceptance:** all 10 run twice; no `bl-*` SHA in trunk; `clive-eng measure --run B1`.
- **Tests:** every task validates and carries `land: false`.
- **Owner-visible:** the machine baseline.
- **Risk:** plan usage (about 7 builder-hours per pass), run off-hours with live use first.
- **Rollback:** delete the branches.
- **Dependencies:** RP2, PR 1.
- **Metric:** this is B1.

### PR 12 — Fault injection F1 (loop-eligible script; George's run on worker-01)
- **Problem:** what the checks and review catch has never been measured (DEC-062).
- **Reuse:** `acceptance.yml` (runs on every push), `NamespaceSandbox`, the dispatcher's packet code,
  `reviewers/claude.py`.
- **Scope:** `scripts/fault_injection.py` and `baseline/faults/*.patch` (9 seeded defects,
  QUALITY_HARNESS). For each defect it:
  - pushes branch `fi/<n>` (`acceptance.yml` runs on every push);
  - runs the declared checks in `NamespaceSandbox`;
  - runs the Claude reviewer blind, in a scratch store, on the original task's packet.

  It never touches the kernel store, the inbox or trunk.
- **State change:** temporary `fi/*` branches, deleted after the run.
- **Acceptance:** a row per defect with its first catching layer; branches and scratch store removed.
- **Tests:** the dispatcher's own packet builder is used; a dry run with a fake reviewer.
- **Owner-visible:** what the loop catches, honestly.
- **Risk:** low.
- **Rollback:** delete the branches.
- **Dependencies:** RP1 (the Claude reviewer).
- **Metric:** catch rate per layer. **Pass bar:** every critical row caught, and at least 7 of 9
  before landing. That is an engineering bar, reported to him.

### PR 13 — Concurrency ladder (engineering setting under ruling 4)
- **Problem:** worker-01's concurrency has never been measured. Ruling 4 makes it an engineering
  setting chosen by measurement.
- **Reuse:** the replay set (PR 11), `loop{}.host` (PR 6), `measure` (PR 1).
- **State change:** the unit's `--max-concurrent` value, changed by George's Termius edits.
- **Scope:** the replay set at 2, then 4 (and 6 or 8 only if 4 is healthy), **two passes per level**,
  overnight, using `loop{}.host` and paired per-task stop rules (CONCURRENCY_PLAN).
  - The engineering team picks the standing value from the data. **It is not an owner decision.**
  - George applies each unit flag change as a Termius gesture.
- **Acceptance:** every metric per level; each stop rule evaluated; the standing value recorded in
  CURRENT_TRUTH.
- **Tests:** n/a. The numbers come from `measure`.
- **Owner-visible:** the throughput his plan buys.
- **Risk:** plan usage. Live CLIVE first: any hard plan-limit pause stops the ladder.
- **Rollback:** set the flag back.
- **Dependencies:** RP2, B1.
- **Metric:** accepted replays per hour at an equal paired first-pass rate.

### V1-real and MEASURED_OUTCOME
- **V1-real** runs for 2–3 weeks after D2. Real intentions go in as build objectives with authorised
  plans, with the ledger on.
- **Drills:**
  - X1: close Desktop;
  - X2: drop SSH;
  - X7: reboot worker-01, an owner gesture.
- **The comparison:**
  - B0 against V1-real for owner measures;
  - history against B1 for the machine side;
  - F1 for the quality floor.

  Each figure carries n and confidence. Nothing is promoted on fewer than 10 accepted builds.
- **Autonomy levels** are promoted only by AUTONOMY_LEVELS' rule, and DEC-018 still bounds levels 5
  and 6.

---

## Order and dependencies

```
A:  A1 ─► RP1 (verify DEC-068/076; concurrency 2) ─► stop prod-host loop        PR 0 ─► PR 1 ─► B0 (≥7 days)
B:  PR 2 ─► PR 3 (rebased on DEC-081; DEC-082 "Try again" calls it) ─► D1 ─► Director archives once
C:  PR 3 ─► PR 4 ─► PR 5c        PR 5a        PR 5b ─► PR 6 ─► RP2 (+ rehearsal)
D:  O-1 ─► PR 7 ─► PR 8 (O-2, RP2, DEC-080) ─┐
    RP2 + DEC-082 ─► PR 9 ───────────────────┼─► D2
    O-2 ─► PR 10a;  PR 8 ─► PR 10b           │
E:  RP1 ─► PR 12 (F1)    RP2 ─► PR 11 (B1 ×2) ─► PR 13 (ladder)    D2 ─► V1-real ─► MEASURED_OUTCOME
```

**Parallel work:**
- PRs 0, 2, 5a and 5b can start at once. PR 1 follows PR 0.
- PR 12's script can be written any time; it runs after RP1.

## Owner gestures, complete

| When | Gesture |
|---|---|
| Decisions | **O-1** (the filing-authority design) and **O-2** (the supervisor's identity), before Stage D. **O-3** (the OAMAB threshold), after V1-real |
| Stage A | Run the A1 audit; the RP1 Termius session, including stopping the production-host loop; the holds for PR 1's and the smoke request's filings |
| Stage B | Decide and run D1; phone check |
| Stage C | The RP2 Termius session |
| Stage D | Decide and run D2; set the private URL; phone check; the first plan card |
| Stage E | The hold for the replay batch; the F1 run on worker-01; the ladder's unit flag edits; the X7 reboot drill |
| Reading | B0, B1, F1, the ladder report, MEASURED_OUTCOME |

---

## NOW (V1)
A1, PR 0, RP1, PR 1, B0, PRs 2–3, D1, PRs 4–6, RP2, PRs 7–10b, D2, PRs 11–13, V1-real.

## NEXT (each only if V1 data shows its cause matters)
- A base and environment preflight inside the loop, if environment stops persist after PR 3.
- A path-overlap launch gate (DEC-043), if conflicts or refreshes rise across objectives.
- A lease-ordering fix, if A1 or B1 shows lease cancellations.
- A workspace cleanup verb.
- A remote resume for `github_waited`.
- The deploy brief on the "Deploy now" card.
- A durable "Director on duty" running `triage` and drafting retries inside authorised scope. Ruling
  9's model allows those retries; DEC-018 bounds the rest. Only if Director-queue time dominates
  V1-real's remaining owner minutes.
- A scheduled Bench runner.
- `root-repin.sh` in the repository, reviewed with Claude (DEC-076's open call).
- Curated CLIVE builder skills (his list, DEC-064), on a gated CLI.
- Heterogeneous dual review.

## LATER
- Priority.
- Critical-path ordering.
- Merge trains.
- Impacted-test selection, for the fast layer only.
- An engineering MCP wrapping `clive-eng`, if CLI friction is measured.
- Resource classes.

## DO NOT BUILD
- **While DEC-018 stands:**
  - automatic decomposition of an intention into work he has not seen;
  - proactive filing;
  - policy that adjusts itself (filing bounds, concurrency, gates);
  - proactive improvement proposals (autonomy levels 5 and 6).
- **No second control plane or store:**
  - a project store;
  - a manifest the loop reads;
  - a stored project state machine;
  - a replacement dispatcher;
  - a second queue or scheduler process;
  - a new database;
  - GitHub Issues as the board.
- **Nothing that already exists, built again:**
  - DEC-068 or DEC-076 behaviours (re-pin and verify);
  - "Try again" (DEC-082);
  - outside-text protection (DEC-080);
  - the DEC-081 items;
  - build-item advancement (DEC-082).
- **No new fields on `Objective` records in `obj_x.json`.** The design file only.
- **No new fields on kernel records.**
- **No path into the loop's inbox or the kernel outside CLIVE's filing path:**
  - no scope widening inside the loop;
  - no automatic re-file by the loop;
  - no supervisor push to the inbox;
  - no kernel owner adapter or owner-gate lifting.
- **No new runtimes or credentials:**
  - the Agent SDK, `--bare`, or any API-key path;
  - an engineering MCP before the CLI is proven insufficient;
  - universal Playwright MCP;
  - network in the check sandbox;
  - Bench as a landing gate, or a model credential in `clive-eng`;
  - broad connectors or credentials for builders or the supervisor.
- **No path to production or trunk outside the existing gates:**
  - automatic deploy;
  - deploy implied by "on the trunk";
  - automatic GPT failover;
  - any weakening of exact-SHA CI, review, the sandbox, protected paths or hash pins;
  - impacted-test selection in the final gate.
- **Nothing published that DEC-068 keeps private:** no review findings or builder words on GitHub.
- **No growth in roles or skills:**
  - planning or authority skills as builder skills;
  - agent roles beyond supervisor, builder, sandbox and CI verification, and independent reviewer.
- **No self-hosted runner while the repository is public.**

---

## The answers the prompt asks for

1. **What CLIVE already has.** Proven in real work: 26 COMPLETE and 12 self-landings on worker-01.
   - **The loop:** the dispatcher, isolated workspaces and sessions, the check sandbox, exact-SHA
     acceptance with browser tests, landing under DEC-064.
   - **Review and repair:** an independent reviewer; bounded repair. DEC-068 (findings fed back, stop
     reports, repair rounds, skills, browser) and DEC-076 (Claude reviewer) are built and await the
     re-pin.
   - **Filing and channels:** a create-only inbox and status; a private stops channel; a held filer
     that links to build objectives.
   - **Owner surfaces:** `Objective(kind=build)` with owner-only authorise; Builds with decision cards;
     Bench.
   - **Tooling:** hash-pinned skills; measures.
2. **What must actually be added:**
   - **Truth:** the re-pin with verification; retiring the second loop.
   - **Measurement:** the measures and ledgers; replays, fault injection and the concurrency ladder.
   - **Filing (D1):** a preflight in the one filing path; archive-safe ids.
   - **Loop (RP2):** dependency deferral at intake; FIFO and the clone fix; one concurrency knob and
     the plan-limit pause; `land: false` without a proof; a loop that describes itself; stop and owner
     classes; skill routing.
   - **The ruling-9 model:** authorised plans on build objectives; `filing_decision`; the supervisor's
     draft channel; "Allow the change"; automatic archiving.
   - **Owner surfaces:** project rows; the `clive-eng` shell.
3. **What must not be built:** see DO NOT BUILD.
4. **Expected quality effect** (a hypothesis):
   - no gate is weakened;
   - the Claude reviewer and findings fed back are in force;
   - paired tests and a green base come from the preflight;
   - the harness is measured (F1);
   - ABER becomes measurable.
5. **Expected wall-clock effect** (a hypothesis):
   - fewer re-file chains, as review convergence (DEC-068) and the preflight act on 44 of 44 block
     causes;
   - dependents start minutes after their predecessor lands;
   - parallel capacity for authorised plans with separable steps;
   - CI at about 10 min per candidate stays the floor.
6. **Expected owner-attention effect** (a hypothesis until V1-real against B0):
   - one hold per plan instead of per request;
   - "Try again" and "Allow the change" act on one hold;
   - retries inside scope need no tap;
   - questions arrive as one list;
   - the Director queue is visible.
7. **Unresolved owner decisions:** O-1 (approve the ruling-9 design), O-2 (the supervisor's
   identity), O-3 (the OAMAB threshold, after measurement). DECISIONS.md also lists open calls that
   V1 does not need.
8. **Recommendation:** below.

## Final GO / REVISE / STOP

**GO, staged:**
1. **Now:** Stage A. RP1 needs no new code, and it is the largest lever on the largest bottleneck.
2. **Stage B** after B0 has at least 7 days.
3. **Stage C** when PRs 4–6 have READY reviews.
4. **Stage D** when George approves FILING_AUTHORITY (O-1) and the supervisor identity (O-2).
5. **Stage E** as each dependency lands.

**Why GO:**
- Every addition sits at a named seam with a precedent in the code.
- DEC-018 is respected.
- No authority moves without his approval of O-1.
- Each stage rolls back:
  - **RP1 and RP2:** re-pin a recorded or rehearsed pin;
  - **D1:** revert PR 3, keeping PR 2;
  - **D2:** redeploy, and every filing waits for his hold again.

**What would turn this into STOP:**
- RP1's verification shows DEC-068 or DEC-076 misbehaving on worker-01;
- no pin passes the RP2 rehearsal;
- F1 shows a critical defect class passing every layer.

Any of these goes to George before anything further.
