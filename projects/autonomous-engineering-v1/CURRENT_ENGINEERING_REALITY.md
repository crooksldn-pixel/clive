# Current engineering reality

**Status:** FILLED 2026-10-14 from a read-only repo audit and a read-only audit of the SSH host.
**As of:** host audit 2026-10-14 11:40–11:46 UTC. **Re-checked 2026-10-15** (read-only): production is now `dc59047e`; trunk is `ef204bc2` (DEC-079); the worker-01 projection, generated 2026-10-15 15:28 UTC, shows the same 74 requests, with no new request since 8 Oct.
**Detail:** [audit/REPO_AUDIT.md](audit/REPO_AUDIT.md) · [audit/HOST_AUDIT_RESULTS.md](audit/HOST_AUDIT_RESULTS.md) · [audit/BASELINE_EVIDENCE.md](audit/BASELINE_EVIDENCE.md)

## The classification scale

| Class | Meaning |
|---|---|
| **BUILT** | The code exists on trunk. |
| **ACTIVE** | It is running on a host, shown by a unit, a process or a fresh heartbeat. |
| **PROVEN** | It has run end to end in real work, shown by records of outcomes. |
| **GAP** | It is not built. |
| **UNKNOWN** | It cannot be determined safely from here. |

**Each class is stated per host where it differs.** Two engineering hosts are involved:
- **worker-01** is `clive-worker-01`, the designated loop. Everything known about it comes from its
  public status projection, never from host inspection.
- **prod** is `crooks-os-prod-1`, the production host. It still runs an older loop.

## Capability table

| Capability | BUILT | ACTIVE | PROVEN | GAP / UNKNOWN | Evidence |
|---|---|---|---|---|---|
| Dispatcher lifecycle | ✔ | ✔ worker-01 (heartbeat 11:31Z) · ✔ prod (idle since 25 Sep) | ✔ worker-01: 26 COMPLETE, 12 self-landings · ✔ prod 23–25 Sep | — | `dispatcher.py:374-427`; projection; prod journal |
| Workspace isolation | ✔ | ✔ | ✔ prod (per-attempt clones) · worker-01 workspaces evidenced | Cleanup is a **GAP** (nothing removes old workspaces or homes) | `workspaces.py`; 4 EXDEV failures on worker-01 |
| Claude builder session isolation | ✔ | prod ✔ · worker-01 UNKNOWN | ✔ prod (per-attempt session and home, minimal environment, file tools only, no MCP) | worker-01 flags UNKNOWN | `workers/claude.py:217-270`; prod `controller.log` |
| Bounded repair | ✔ | ✔ | ✔ worker-01: 79 repair revisions, 18 convergence stops | Plan-limit pause is a **GAP** | `dispatcher.py:1187-1194,1421-1427` |
| Repair evidence carried forward | ✔ | worker-01 UNKNOWN (DEC-068 parts need the re-pin) | Findings verbatim: ✔ (pre-DEC-068 behaviour) | Stop-report carry-over on worker-01 is UNKNOWN | `_repair_brief`, `_red_run_brief`, `earlier_try` |
| Check sandbox | ✔ | prod ✔ · worker-01 UNKNOWN | ✔ prod (50 check runs, canary) | worker-01 UNKNOWN | `checks.py:211-400` |
| Browser-capable checks (in the loop) | ✔ (opt-in) | prod ✘ (Chrome outside the sandbox root) | — | worker-01 UNKNOWN | `checks.py:230-249` |
| Browser evidence in exact-SHA CI | ✔ | ✔ | ✔ (every SHA since PR #108) | — | `acceptance.yml:89-109` |
| GitHub exact-SHA acceptance | ✔ | ✔ | ✔ worker-01: 29 records, 22 green, 7 red | — | `github_acceptance.py`; projection |
| Claude independent reviewer | ✔ (PR #114, DEC-076) | ✘ worker-01 (0 Claude verdicts) · ✘ prod (its pin predates it) | ✘ | Needs the worker-01 re-pin | `reviewers/claude.py`; projection |
| GPT reviewer | ✔ | ✔ | ✔ 44 verdicts on worker-01, last 8 Oct | A flag set at re-pin, not a runtime failover | `reviewers/choice.py` |
| Remote engineering inbox/status | ✔ | ✔ both hosts | ✔ | **The inbox stops admitting anything above 100 records; 75 are used** | `inbox.py:35,199-200` |
| Private stops channel (DEC-068) | ✔ | UNKNOWN | ✘ not evidenced | Needs the re-pin and `CROOKS_ENGINEERING_PRIVATE_URL` | `remote_engineering/private.py` |
| Engineering bridge (filing from CLIVE) | ✔ | UNKNOWN (`.env` not read) | ✔ 7 owner filings on 30 Sep | Filing was broken until PRs #122 and #123 ("CLIVE can file a build again", "a bad character can't stop filing"), live since the `dc59047e` deploy of 14 Oct |  `engineering_tools.py:939-1060`; inbox history |
| Builds owner surface | ✔ | ✔ deployed since `cac1a9e7` (runtime not queried) | Partial: George used decision cards; the loop cannot read his answers | Owner answers reaching the loop is a **GAP** | `app/builds/*`; `decisions.py:28-33` |
| Bench | ✔ (CLI) | UNKNOWN | UNKNOWN | Not wired to the loop; **cannot run in the sandbox** (needs network) | `docs/BENCH.md` |
| Hash-pinned builder skills | ✔ | UNKNOWN | ✘ not evidenced | Works only on CLI 2.1.285 or 2.1.293. **No per-task routing (GAP)** | `workers/skills.py`; `claude.py:130-133` |
| Priority ordering | field only | — | — | **GAP**: objectives are taken in alphabetical order | `objectives.py:411-417` |
| Dependencies / DAG | field only | — | — | **GAP**: `predecessor_task_ids` is unused | `contracts.py:112` |
| Project above objectives | ✔ CLIVE `Objective(kind=build)`: owner's words, purpose, done-when, `engineering[]` (linked by `submit_engineering_request(objective_id)`), typed blockers, attention, history, owner-only `authorise` | ✔ (production) | — | **GAP:** authorised plans of several requests (PR 7); dependency edges the loop can read (PR 4) | `app/objectives/store.py:1-60,114-126,353-363,1556-1632`; `engineering_tools.py:853-865,945-1018` |
| Lifecycle metrics | ✔ (`engineering_measures`) | UNKNOWN | ✘ deploy and attention inputs exist nowhere; 4 defects | **GAP**: check, CI and queue timings, and the owner-attention instrument | `engineering_measures.py` |
| Supervisor CLI | Host verbs only (`status`, `stops`, `resume`) | prod-host verbs only | — | **GAP**: filing helper and project views (Director hand-commits JSON) | `scripts/*` |
| Current worker pin | — | — | — | worker-01 **UNKNOWN** · prod `4c32bb3d` (701 behind trunk) | Unit; projection silent |
| Current max concurrency | default 1 | prod **2** (unit) · worker-01 ≥4 observed | — | worker-01 configured value UNKNOWN (docs say 8). Allowed in principle since DEC-079 ruling 4 (14 Oct), as an engineering setting chosen by measurement | Unit; projection timings; DEC-064 |
| Current reviewer selection | default `claude` | prod: GPT · worker-01: GPT in practice | — | worker-01 configuration UNKNOWN | Unit; projection |
| Landing enabled | ✔ (default on) | worker-01 ✔ | ✔ 12 loop self-landings (1–8 Oct) | prod: not evidenced | Projection |
| Production SHA | — | **`dc59047e`** (deployed 2026-10-14 19:45 UTC; service restarted 19:46:15). Before it: `09b633cc` (9 Oct) | — | CURRENT_TRUTH says `b33ccbc2` (stale) | `/opt/crooks-os` reflog (read with `GIT_OPTIONAL_LOCKS=0`); `systemctl show` |
| Trunk SHA | — | **`ef204bc2`** (DEC-079, a docs-only PR #125; 1 ahead of production) | — | DEC-080 to DEC-082 are not on trunk yet (the Director's, in progress) | `origin/clive/trunk`, refreshed every 5 min |
| Release service | ✔ (PRs #101, #116) | ✘ not installed | ✘ | — | No units on prod |

## worker-01, from George's A1 audit (2026-10-15 16:31 UTC)

| Fact | Value |
|---|---|
| Unit | `clive-remote-engineering` active, running since 2026-10-01 22:04 UTC, 0 restarts, peak memory 17 GB |
| Pin | `718fbc41` (PR #88), 58 commits behind trunk `ef204bc2`. **DEC-068 and DEC-076 are confirmed not in force** |
| Reviewer | GPT through `--gpt-api-key-file`; there is no `--reviewer` flag at that pin |
| Concurrency | `--max-concurrent 8` |
| Claude CLI | 2.1.280 (`/srv/clive-engineering/bin/claude`): not a skills-gated version |
| Browser | None configured. Node at `/opt/node22` (v22.23.3) |
| Layout | Repo and workers on a 52G tmpfs, re-cloned at boot by `clive-repo-clone.service`; the store (20 MB) and runtime (53 GB) on disk; 3.4 TB free; 32 cores, 125 GiB RAM |
| Health | 0 lease cancellations, 0 rate-limit lines (14 days), 0 stop reports (that pin predates DEC-068) |
| Users | The unit runs as root. `clive-trunk-fetch.timer` every 5 min |

## After Stage A (2026-10-16): what changed

The record of each step is in [STAGE_A_RUNBOOK.md](STAGE_A_RUNBOOK.md). Where the A1 table above and this
one differ, this one is current.

| Fact | Before | Now | Evidence |
|---|---|---|---|
| worker-01 pin | `718fbc41` | **`ef204bc2`** (RP1, review READY on gpt-6-sol with no waiver) | `/proc` cwd; the tree's HEAD |
| Reviewer | GPT | **Claude (`claude-reviewer`)**: ACTIVE and PROVEN by the smoke request | Its verdict and acceptance on `cdee8fce` |
| `--max-concurrent` | 8 | **2** (an engineering setting; not raised in Stage A) | `/proc` cmdline |
| Builder skills | on by default | **off** (`--no-builder-skills`; CLI 2.1.280 is not gated) | `/proc` cmdline; `probe-launch` PASS |
| Repair rounds | — | **`--default-repair-rounds 2`**, in force | The smoke request's `max_repair_rounds: 2` |
| Private stops channel (DEC-068) | absent | **ACTIVE**: listens on worker-01's tailnet address, allows production only; answered production with 46 reports; folder `700`, reports `600` | R6; George's `stat` |
| `earlier_try`, findings reaching a repair | not in force | BUILT and running; **not yet PROVEN** (no repair or re-file since) | — |
| Loop landing | 12 self-landings to 8 Oct | **PROVEN again**: `cdee8fce` landed by the loop | Status `landing.by: loop` |
| Trunk | `ef204bc2` | **`cdee8fce`** (the smoke request) | `origin/clive/trunk` |
| Production-host loop | active, enabled, pin `4c32bb3d` | **inactive and disabled** since 2026-10-16 13:13:06 UTC; its directories kept | `systemctl`; no process |
| Rollback target for RP1 | — | `718fbc41`, rehearsed (R7) | R7 |

Facts 2 and 3 under "Facts that change the plan" are resolved by this: one loop runs, and worker-01 runs
trunk's DEC-068 and DEC-076.

## Host identity

| Field | Value |
|---|---|
| Host audited | `crooks-os-prod-1` |
| Role | **Both: production, plus a second (older) engineering loop that is still enabled.** It is not the designated worker. |
| Timestamp | 2026-10-14 11:39–11:46 UTC |
| Current worktree | `…/claude-worktrees/repo-4141a1c464d9024e/autonomous-engineering-v1-plan-92e29a`, branch `claude/autonomous-engineering-v1-plan-92e29a` at `cec92afa` (= `origin/planning/autonomous-engineering-v1`) |
| Claude CLI | 2.1.276 (production app) · 2.1.280 (prod loop's worker CLI) · 2.1.295 (this session) · worker-01 UNKNOWN |
| Node | v22.23.2 |
| Python | 3.12.3 |
| CPU | 4 vCPU |
| RAM | 7.6 GiB, no swap |
| Disk | 26 GB free of 75 GB |
| Browser runtime | Chrome 155 at `/opt/google/chrome`, outside the check sandbox. worker-01 UNKNOWN |
| worker-01 (documented, not verified) | 2× Xeon Silver 4110 (32 threads), 128 GB, RAID 1+0 on spinning disks |

## Facts that change the plan

1. **The planning and supervisor session runs as root on the production host.** In V1 the supervisor
   moves to a non-root, read-only user on worker-01, which files only through CLIVE (DECISIONS O-2).
2. **Two loops are live.** The production-host loop is stale-pinned, GPT-only, and accepts anything
   committed to `clive/control/owner-inbox`. DEC-071 ruling 11 already says to stop it after the
   worker-01 re-pin, and it has not been stopped.
3. **worker-01 does not run what trunk says it runs.** No Claude verdicts appear, so DEC-076 is not in
   force. Its pin is unknown, and DEC-068 is probably not in force either. Every V1 change to the loop
   lands only through that same re-pin gate.
4. **The binding constraints are review convergence and request quality, not builder capacity:**
   - median queue time is 0.4 min;
   - 35% of worker-01 requests completed;
   - **the 44 blocks:** 18 review not converging, 9 environment or base, 9 CI or checks red, 8 scope
     (the Director's grouping of BASELINE_EVIDENCE §2);
   - 49 of 101 requests are re-files;
   - the inbox stops at 100 records, and 75 are used.
5. **The loop is not yet "the normal way work lands"** (DEC-071 ruling 9). Since that ruling, 13 PRs
   landed outside the loop and 2 requests went into it.
6. **worker-01 runs at least 4 builders at once.** DEC-079 ruling 4 (14 Oct) now allows parallel
   engineering as an engineering setting chosen by measurement, with live use first. RP1 sets 2 until
   the plan-limit pause exists (RP2), and the ladder sets the standing value.

## Important rule

When host evidence cannot prove a runtime fact safely, the fact is marked UNKNOWN. The worker-01 facts
above are resolved only by the read-only worker-01 audit (step A1)
([WORKER01_AUDIT.md](WORKER01_AUDIT.md)), run by George or with his explicit permission.
