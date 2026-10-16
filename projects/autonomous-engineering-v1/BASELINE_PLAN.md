# Baseline and measurement plan

Do not claim autonomy or speed improvement without a baseline. Three baselines exist, and each
answers a different question:

1. **Historical.** Computed now from the loop's own records, 24 Sep → 14 Oct, the GPT-reviewer era.
   It needs no new runs. Numbers are in [audit/BASELINE_EVIDENCE.md](audit/BASELINE_EVIDENCE.md).
2. **B0: the owner's "before".** Real work done as today, on the re-pinned loop (after RP1) until D1, with the
   attention ledger on. This is the OAMAB and chain-ETAB baseline that **V1-real** is judged against.
   **ACTIVE since 2026-10-16 13:34:31 UTC, without PR 1's ledger.** It runs on records the system already keeps; one OAMAB part has
   no source. See [B0.md](B0.md).
3. **B1: the machine "before".** The replay set, run twice on the RP2 loop with single requests. It
   isolates the loop's machine-side behaviour on the new pin (Claude reviewer, FIFO, plan pause) from
   the historical era, and anchors the concurrency ladder.

Replay *projects* are a dependency drill only. They recast unrelated historical changes as dependent
members, so they are not a fair before/after comparison. V1 is judged on real work.

## Primary metrics, defined against real sources

### OAMAB: Owner Active Minutes per Accepted Build

Active owner effort only, from four sources. **Passive waiting is not counted.**

| Source | How minutes are counted | Instrument |
|---|---|---|
| Supervisor and Director sessions | Each owner message counts as min(gap since the previous owner message, 5 min) + 1 min. Only timestamps are read, never content | `scripts/engineering_measures.py` over the supervisor host's session transcripts (PR 1) |
| CLIVE gestures | 1 min per hold, passkey approval or Builds ruling about engineering | Timestamps from the judgment ledger, filing holds and deploy approvals (PR 1); counts only, no content |
| Relays | Minutes as entered: Termius, sudo, re-pin, phone checks, copy-pasting errors | `--add` entries (PR 1) |
| Final evidence review | As entered | Same |

The ledger format is `{at, minutes, about, source}`, which `engineering_measures --attention-log`
already accepts. "Accepted build" means a request whose candidate is on `clive/trunk`, counted once
per chain.

### ETAB: Elapsed Time per Accepted Build

From `requested_at` (the owner's utterance, or the supervisor turn that drafted the request) to
**on trunk**. The intermediate stamps are taken from the projection and the request file:

| Stamp | Source |
|---|---|
| requested | The build objective's creation, or its plan card's hold (PR 7); otherwise the inbox commit time |
| submitted | The inbox commit time |
| recorded | Intake |
| first assigned | Projection |
| candidate | Projection |
| checks done | Stage transitions in the status snapshot history (PR 1, ~1 min resolution) |
| CI done | The same |
| review done | Projection |
| accepted | Projection |
| landed | Projection |

ETAB is reported per request and per chain, because re-files dominate real elapsed time: a 0.65 h
single request against a 2.33 h median per chain.

### ABER: Accepted Build Escape Rate

The share of accepted builds with at least one defect that should have been caught before acceptance
and was found later. A finding counts when made by any of: a later review, trunk CI turning red, the
owner, a post-deploy review, or a production incident.

The instrument is a defect record `{found_at, found_by, introduced_by: request|PR|sha, severity, fixed_by}`
kept by PR 1's defect ledger, and mandatory `fixes:` on fix requests. The comparison window is
14 days after landing.

## Secondary metrics (all from the projection and its snapshot history, PR 1)

- Owner interruptions per project, split into owner-class and Director-class.
- First-pass review READY rate. Historical: 25%.
- Repair rounds per accepted build.
- Re-files per chain. Historical: 49 of 101 requests were re-files.
- Check, CI, review and queue durations. Historical medians: build 4.7 min per attempt, CI 10.0 min, review 1.1 min, queue 0.4 min.
- Refresh merges per landing. Historical: 7 of 26 COMPLETE needed one; 3 hit the cap.
- Blocked-reason distribution. Historical: about half are spec or environment.
- Worker failure, lease cancellation and plan-limit pauses.
- Bench regressions on trunk heads.

## Historical baseline (computed 2026-10-14)

| Metric | Value |
|---|---|
| Completion rate | 35% of worker-01 requests (26 of 74); 31% across both loops |
| Chains reaching COMPLETE | 60% (31 of 52) |
| ETAB, single request, self-landed | median 0.65 h (n = 12) |
| ETAB, chain, self-landed | median 2.33 h (n = 12) |
| ETAB, chain, human-landed | median 7.96 h (n = 18) |
| First-pass review READY | 25% |
| Machine time per accepted build | ~43 builder-min, ~31 CI-min, ~6 review-min |
| ABER lower bound | ≥3 of 30 trunk-landed accepted loop builds broke trunk CI before the GitHub gate existed (~10%) |
| OAMAB | **not measurable**: no instrument. Proxies only (BASELINE_EVIDENCE §3) |

## Representative baseline set

Ten real chains, each with an exact request file, base SHA and a reference result on trunk. They are
listed in [audit/BASELINE_EVIDENCE.md §5](audit/BASELINE_EVIDENCE.md) and cover:

- a small bug fix;
- a backend fix with a scope trap;
- an external API;
- UI plus backend;
- a test-only repair;
- a behavioural prompt change;
- a cross-component change;
- an ambiguous request;
- a scope or security conflict;
- a parallel wave.

### How they are replayed (PR 11)

- Each request is re-filed as `bl-<n>-<run>`, at its **original `base_sha`**, with `land: false`
  (PR 5c) and the checks' interpreter rewritten for the worker.
- A replay must never reach trunk.
  - PR 5c integrates `land: false` work **without a landing proof**, so once integrated under RP2, no
    pin will treat it as its own to land (`_eligible` returns None).
  - Work still **in flight** during a rollback to an older pin is protected only by running that pin
    with `--no-land` until it is terminal (IMPLEMENTATION_PLAN, RP2 rollback).
  - An old base on its own would **not** stop a landing: the loop would refresh it onto the current
    trunk.
- After every run, check that no `bl-*` SHA is contained in `clive/trunk`.
- Replays push only `clive/objective/bl-*` branches. GitHub runs `acceptance.yml` on those SHAs; it
  costs no minutes while the repository is public.
- They spend Max-plan usage. Each full run of 10 replays costs about 7 builder-hours (43 builder-minutes
  each, from history) plus review. This is an engineering setting under ruling 4: overnight, with live use first.
- The owner-intent part of OAMAB cannot be replayed. Replays measure machine-side ETAB, first-pass
  review, repair rounds and blocks. OAMAB comes from B0 against V1-real.
- With 10 tasks, one task flipping moves a rate by 10 points. **Every replay level runs twice, and
  comparisons are paired per task** (the same task at two levels).

## Runs

| Run | When | Configuration | Purpose |
|---|---|---|---|
| B0 | RP1 → D1 (at least 7 days) | Real work as today, attention ledger on | The owner's "before": OAMAB, chain ETAB, interruptions, blocks by cause after DEC-068 and DEC-076 are in force |
| B1 | After RP2 | Replay set ×2, at concurrency 2 (the RP1 setting), single requests | The machine "before" on the RP2 loop |
| C2, C4 | After B1 | Replay set ×2 at concurrency 2, then 4 | CONCURRENCY_PLAN |
| F1 | After RP1 | Fault-injection set (QUALITY_HARNESS) | Which layer catches what |
| Drill | After RP2 | A two-member `land: false` replay chain | Dependency semantics only. Drills X1 and X2 run in V1-real, on a real project that lands |
| V1-real | 2–3 weeks after D2 | Real intentions as build objectives with authorised plans, ledger on | V1-real against B0 |

## Baseline rule

Measure how George actually builds today. Do not make the current workflow worse to make V1 look
better. Report every metric with n and confidence. MEASURED_OUTCOME.md stays empty until run V1
exists.
