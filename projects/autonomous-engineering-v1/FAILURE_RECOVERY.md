# Failure and recovery plan

Durability is a first-class acceptance requirement.

## Where durable state lives (and where it must not)

| State | Durable home | Survives Desktop, SSH or production loss? |
|---|---|---|
| A filed request or project | `clive/control/worker-01-inbox` on GitHub (create-only files) | Yes |
| Intake claim, receipt or wait | worker-01 adapter root | Yes; restart-safe (`receipts.py`, `waits.py`) |
| Lifecycle (tasks, attempts, verdicts, integrations) | worker-01 kernel store, git-journalled | Yes |
| Candidates | `clive/objective/<id>` on GitHub | Yes |
| Landings | `clive/trunk` plus worker-01 landing intents | Yes |
| Public status | `clive/control/worker-01-status` | Yes; re-derived on every publish |
| Stop reports | worker-01 `<runtime>/stops`, served over the tailnet | Yes |
| A supervisor's draft | The supervisor's session on worker-01 | **No, by design.** A draft is not work. Once CLIVE files it (PR 8), or he holds its card, it is |
| An authorised plan | Production: the build objective's design file (PR 7) | Survives Desktop and SSH loss. The loop does not need it once its members are filed |
| Admission facts (`land`, edges, admitted base) | worker-01 `links/<id>.json` sidecar | Yes; ignored by an older loop |
| Owner answers | Production judgment ledger, and the re-file his confirmed answer files (DEC-082; PR 8 for "Allow the change") | Yes |

**Rule:** once CLIVE's filing path has written the inbox commit, nothing on the Desktop, the SSH session or
the supervisor host is needed for the project to proceed.

## Drills: the mechanism, its current proof, and what V1 adds

| # | Scenario | Mechanism today | Proof today | V1 action |
|---:|---|---|---|---|
| 1 | Close Claude Desktop during a running project | The supervisor holds nothing durable | — | Drill X1 (V1-real): a two-item authorised plan is filed, then Desktop is closed. Pass when both items land with no supervisor action |
| 2 | Drop SSH | Same as 1 | — | Drill X2: as X1 with SSH killed |
| 3 | Kill the supervisor Claude process mid-draft | The supervisor never writes the inbox; CLIVE files | — | PR 8 test: a draft is filed whole or not at all; a re-sent draft is idempotent (same id refused as already filed) |
| 4 | Restart the dispatcher | Stage is re-derived each tick; marker-based reattach; flock | `test_engineering_dispatcher.py:437-506` | PR 4 test: a dependency wait survives restart, as base waits do |
| 5 | Terminate a builder | Stall and lease, then transient retry with backoff (≤3) | `test_engineering_dispatcher.py` (stall, transient) | — |
| 6 | Crash a reviewer | Up to 3 runs, then block with the reason | `test_claude_reviewer.py` | Drill on worker-01 after the re-pin |
| 7 | Reboot worker-01 | systemd restart plus record re-derivation; the repository is re-cloned at boot (INFRASTRUCTURE) | Restarts observed on the production-host loop (journal) | Drill X7 during V1-real: reboot mid-build, then check that no false COMPLETE appears, no duplicate attempt runs, and the work resumes |
| 8 | GitHub temporarily unavailable | Gate state `unavailable` waits up to 3600 s, then blocks | `test_github_acceptance.py` | Known gap: an outage of more than an hour blocks as `github_waited`, resumed only on the host or by a re-file. A remote resume record is NEXT, if it recurs |
| 9 | Claude rate-limited or out of allowance | **GAP**: retried as a transient, which burns retries | — | PR 5b plan-limit pause, with a test that a limit never costs a retry, a review run or a repair round |
| 10 | Trunk moves while a candidate is under review | Review is bound to the exact SHA; landing needs the SHA to contain trunk; a refresh revision follows (≤3) | `test_loop_landing.py`, `test_review_routing.py` | PR 7: overlapping items in a plan must be ordered by `depends_on` (DEC-043). Refreshes are measured (CONCURRENCY_PLAN) |
| 11 | A stale candidate or workspace | Objective branch head checked at review and integration | `test_engineering_dispatcher.py` | RP1 (workspace root on the repository's filesystem) and PR 5a (the clone fix) end EXDEV errors. Cleanup is NEXT |
| 12 | Duplicate dispatch | flock, kernel lock, fencing tokens, marker check; idempotent intake | `test_lifecycle_kernel.py`, `test_remote_engineering.py` | PR 2: ids are checked against `requests/`, `archive/` and receipts, so an archived id is never reused (reuse would stop all intake: `controller.py:245-249`) |
| 13 | Partial status publication | `publish_error` recorded; the projection is re-derived next cycle | `test_remote_engineering.py` | PR 9 and PR 10a: Builds and `clive-eng status` say "status is N minutes old" past 30 min instead of trusting a stale state |
| 14 | **Inbox at its 100-record bound** (new) | **GAP**: all intake stops | — | PR 2, after D1: the Director runs `archive` once; then CLIVE's bridge archives automatically (PR 8, if O-1 approves). It moves receipted, terminal requests to `archive/`, which the loop never lists; Builds reads archived titles. Test: archive 72 records, file 30 more, and none are refused |
| 15 | **Two loops listening** (new) | The production-host loop still polls `owner-inbox` | Host audit | RP1 step 5: stop and disable it after the re-pin (ruling 11). Drill: a request committed to `owner-inbox` afterwards is not built anywhere |
| 16 | **Predecessor blocks inside a project** (new) | — | — | PR 4: dependents stay deferred with `waiting_on: [id]`, never started, and refused only at the 7-day bound. The project shows the one stop, not N |
| 17 | **D1 rolled back after `clive-eng archive`** (new) | The old `_free_id` checks only `requests/`. A reused archived id would make the loop refuse every snapshot (`controller.py:245-249`) | — | PR 2 is **roll-forward only** once `archive` has run. A D1 problem is fixed by reverting PR 3, never by dropping PR 2, because unarchiving about 72 records could exceed the bound (`inbox.py:199-200`). `archive` runs only once production carries PR 2. `unarchive` refuses past the bound. Drill: archive, file more than 25 new requests, revert PR 3 and deploy; intake continues, and no id is reused |
| 18 | **RP2 rolled back** (new) | — | — | RP2 rehearsal, side-effect free (scratch runtime, throwaway local remote, stub worker and reviewer, no network): run the rollback pin's `status` and `tick --no-land` against a copy of the RP2 store that **includes an in-flight `land: false` objective**. If it refuses an RP2-written record, the target becomes the oldest pin that passes. The rollback itself runs with `--no-land` until every `land: false` objective is terminal |
| 19 | **`land: false` work across pins** (new) | The landing proof is written whenever global `land` is on (`dispatcher.py:1464-1475`), and any pin lands a proven integration, refreshing it if needed | — | PR 5c: `land: false` work integrated under RP2 carries **no** proof, so `_eligible` returns None under every pin, which a test checks with the rollback pin's code. Work still **in flight** at a rollback is integrated by the older pin, which does not read the sidecar, so it is protected only by running that pin with `--no-land` until it is terminal (drill 18) |

## Required outcome (unchanged)

No scenario may cause any of these:

- lost accepted work;
- duplicate authoritative execution;
- silent scope widening (scope is fixed at filing; the loop never widens it);
- false COMPLETE;
- a review against the wrong SHA;
- automatic production deploy;
- an unrecoverable state without a clear blocker.

## Recovery principles

- Durable state lives outside the Desktop and SSH session.
- Attempt identity is explicit.
- A candidate SHA is immutable once dispatched to review.
- Retries are idempotent, or create a new explicit attempt.
- A reviewer result is bound to its task, revision, attempt and SHA.
- Stale candidates are rejected or revalidated.
- A restart reconstructs state from durable records.
- George sees a concise blocker only when autonomous recovery is exhausted **and** the cause is owner-class (HUMAN_ATTENTION).

## The FMHY lesson

An interactive Claude process died when its SSH terminal disappeared while work was still
uncommitted on disk. V1 makes that irrelevant for CLIVE engineering: the supervisor's only durable act
is a draft that CLIVE files with one create-only inbox commit, and everything after that commit runs on worker-01.
