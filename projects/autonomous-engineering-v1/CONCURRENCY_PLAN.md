# Concurrency and scheduling plan

## Goal

Maximise **accepted** throughput without increasing owner attention or defect escape. The goal is not
the largest worker count.

## What is true today (evidence: CURRENT_ENGINEERING_REALITY)

- **The code default is `--max-concurrent 1`.**
- **The production-host loop runs at 2**, set in its unit.
- **worker-01 is documented as an eight-builder loop**, and at least 4 builders overlapped on
  2026-10-07 23:16–23:30. Its configured value is UNKNOWN until A1.
- **Parallel engineering is allowed** (DEC-079 ruling 4, superseding DEC-064's answer). How many run
  at once is **an engineering setting chosen from measurement**, not an owner decision. Three things
  bound it:
  - the host's resources;
  - the one Max plan's usage, **with his and his staff's live use first**;
  - DEC-012 (a worktree of its own for each worker) and DEC-043 (parallel only where the scope is
    separable, with an integration gate).

  It grants no authority: parallel builders build only what was filed.
- **Concurrency is not the bottleneck at today's volume.** The median queue time is 0.4 min (p90 7.3
  min). Concurrency helps only when many objectives are ready at once, which is what Projects create.
- **Machine time per accepted build is dominated by CI** (about 70%), and every trunk move after
  acceptance forces a refresh merge that needs its own full CI and review. More parallel landings mean
  more refreshes. That cost is real and must be measured, not assumed away.

## Defects that must be fixed before concurrency is raised past RP1's value (PRs 5a and 5b, at RP2)

RP1 sets `--max-concurrent 2`: conservative while there is no plan-limit pause, with live CLIVE first.

| Defect | Evidence | Fix |
|---|---|---|
| Reviewers are not counted | `_live_count` counts ASSIGNED and RUNNING builders only (`dispatcher.py:489-495`). Claude reviews run up to 150 turns on the same Max plan | `_live_count` also counts REVIEWING, so one knob, `--max-concurrent`, bounds everything that uses the plan |
| No plan-limit pause | Rate-limit events are parsed and ignored (`workers/claude.py:672-675`). With the Claude reviewer, three failed review runs block the task, so a plan limit would mass-block reviews | Classify "hit your session/weekly limit · resets …" and `rate_limit_event` statuses other than allowed. Set a loop-wide `paused_until`, with no launches or review dispatch until then. The paused attempt costs no retry, no review run and no repair round |
| Synchronous tick with lease ordering | Checks run inside the tick; the lease-expiry check precedes reading a finished result (`dispatcher.py:696-706`) | V1 caps declared check time at 600 s per request (PR 3's preflight) and publishes `tick_max_s` (PR 6). Reordering the lease check is NEXT, if A1 or B1 shows lease cancellations |
| Alphabetical start order | `objectives.py:411-417` | FIFO by admission time, using `scheduler.py`'s ordering key (kept by ruling 41). Priority is LATER |
| Configuration unknowable from outside | Projection silent on pin, CLI and concurrency | `loop{}` self-description in the status (PR 6) |

## Scheduler V1 inputs (only these)

| Input | Where | PR |
|---|---|---|
| Order | FIFO by admission. Priority is LATER: queue time is 0.4 min | 5a |
| Dependency readiness | A request with `depends_on` is held at intake until every predecessor's integration is on trunk, then admitted on a green base containing them (the waits.py deferral; nothing burned) | 4 |
| Path conflict (DEC-043: separable scope) | Inside an authorised plan, items whose areas overlap must be ordered by `depends_on` (a rule of the plan card, PR 7). Across objectives, rely on the refresh path (the integration gate) and measure; a launch gate on overlap is NEXT | 7 |
| Resource class | Not added in V1. Browser checks run in CI, not in the loop, so a `browser-heavy` class has nothing to schedule yet | — |

Duration prediction, critical-path ordering and merge trains are LATER.

## Experiment ladder (PR 13; after RP2 and B1; on the replay set with `land: false`)

**Levels:** 2 (the RP1 setting, measured by B1) → 4 → 6 → 8, each only if the one before is healthy. A run at 1 is added only if 2 shows a problem.

**Record at each level:**

- Throughput: accepted replays per hour, ETAB per replay, first-pass review rate, repair rounds,
  refreshes.
- Failures: lease cancellations, plan-limit pauses, worker crashes.
- worker-01 resources, from `loop{}.host` in the public status (PR 6): load average, available
  memory and I/O pressure (PSI). These are published in the status, so they are visible without
  host access. Its disks are spinning (INFRASTRUCTURE: the suite runs 10× slower from disk than from
  memory).
- CI: queue time on GitHub. Public runners have per-repository concurrency limits.
- Review: time from candidate to review dispatch. Reviews share the `--max-concurrent` slots.

**Concurrency counts only when work is ready.** At each level, file the whole replay set at once.
**Run each level twice** and compare paired per task against B1: the same task, the two levels.

## Stop conditions (any one stops the ladder at the previous level)

- In the paired comparison, more tasks lose first-pass READY or acceptance than gain it, across both
  passes. With 10 tasks, a single flip is noise; two or more net losses stop the ladder.
- Any lease cancellation or plan-limit pause that costs a repair round.
- Refreshes per landing double.
- `loop{}.host` shows available memory under 25%, or I/O pressure (PSI `some` avg60) above 30%, for
  10 minutes or more.
- A plan-limit pause (not a warning) occurs at all. At the warning level (`allowed_warning`) the loop
  already stops starting work (PR 5b), so a hard pause means the level is too high. Live CLIVE and
  staff use come first (DEC-079 rulings 4 and 5).
- Any ABER signal: trunk CI red after a loop landing.

## Project DAG rule

An objective is admitted only when all of these hold:

1. its predecessors' integrations are on trunk;
2. it has not been withdrawn.

It starts only when a slot under `--max-concurrent` is free. Builders and reviews both count.

Path overlap is a signal, not proof of conflict. Ordering overlapping items is the conservative V1
rule (DEC-043), because a conflict discovered at landing costs a refresh, a full CI run and a review.
Where parallel work is meant to converge, the plan carries an explicit final item that depends on all
of it: the integration gate.

## Default after measurement

The engineering team picks the standing value from the ladder's data (ruling 4) and records it in
CURRENT_TRUTH. George applies the unit change at a Termius session. Until then the worker runs at 2,
the RP1 setting. The value is never adjusted automatically (DEC-018: no self-adjusting policy).
