# Implementation sequence (summary)

**Revision 4, 2026-10-15**, after the CLIVE Director's cross-check. The full per-PR contracts are in
[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md). This page is the index.

**The order follows the bottleneck evidence.** Of the 44 blocks on worker-01:

| Cause | Blocks |
|---|---:|
| Review not converging | 18 |
| Environment or base | 9 |
| CI or checks red | 9 |
| Scope | 8 |

Re-files multiply all four. So the order is: re-pin first, then measure, preflight, "Try again" (the
Director's, DEC-082) and archiving. Only then come the new loop semantics, the filing model and the
replays.

| Step | Title | Built by | Takes effect at | Depends on |
|---|---|---|---|---|
| A1 | worker-01 read-only audit | George, or a session he authorises | — | — |
| PR 0 | Current truth (production `dc59047e`, DEC-079); the planning package reaches trunk (`projects/…` only) | Director | merge | — |
| **RP1** | Re-pin worker-01 to the trunk head: DEC-068 and DEC-076 in force and **verified**; concurrency 2; EXDEV host fix; **then stop the production-host loop** (ruling 11) | George (Termius) | at once | A1 |
| PR 1 | Measures fixed; attention and defect ledgers | **Loop** (with his hold) | merge | PR 0 |
| B0 | The "before" window, at least 7 days | — | — | RP1, PR 1 |
| PR 2 | Archive-safe ids and readers (roll forward only once archived) | Director (protected) | D1 | — |
| PR 3 | **The preflight inside `submit_engineering_request`**: base, scope with paired tests, toolchain and environment against the worker profile, ids | Director (protected) | D1 | PR 2, A1, DEC-081 (rebase), DEC-082 (coordinate) |
| **D1** | Deploy PRs 2 and 3 (plus whatever DEC-080 to DEC-082 has landed); the Director archives once | George decides | — | B0 |
| PR 4 | `depends_on`, `supersedes`, `land`; dependency wait at intake; admission-time green base; `links/` sidecar | Director (protected) | RP2 | PR 3 |
| PR 5a | FIFO; the clone fix | Director (protected) | RP2 | — |
| PR 5b | One knob for builders and reviews; plan-limit pause, including at the warning level | Director (protected) | RP2 | — |
| PR 5c | `land: false` integrated without a landing proof | Director (protected) | RP2 | PR 4 |
| PR 6 | `loop{}` self-description with host load; stop cause words; owner class; `applies_to` routing; protected paths named in advance | Director (protected) | RP2 | PR 5b |
| **RP2** | Re-pin carrying PRs 4–6, plus the side-effect-free rollback rehearsal | George (Termius) | — | PRs 4–6 |
| PR 7 | Authorised plans on build objectives: plan card, one hold, revoke | Director | D2 | **O-1**, DEC-082 |
| PR 8 | `filing_decision`; the supervisor's draft channel; "Allow the change"; automatic archiving | Director (protected) | D2 | **O-1**, **O-2**, PR 7, RP2, DEC-080 |
| PR 9 | Builds: one row per build objective | **Loop** | D2 | RP2, DEC-082 |
| PR 10a | `clive-eng` read verbs, triage, judge, decisions, deploy-brief | Director (protected) | supervisor user | **O-2** |
| PR 10b | `clive-eng draft` | Director (protected) | supervisor user | PR 8 |
| **D2** | Deploy PRs 7–9; set the private URL (DEC-068) | George decides | — | PRs 7–9 |
| PR 11 | Baseline replays **B1**, twice | Loop plus operator | — | RP2, PR 1 |
| PR 12 | Fault injection **F1** | Loop (script) plus George's run | — | RP1 |
| PR 13 | Concurrency ladder (engineering setting, ruling 4) | Operator; George's unit edits | — | RP2, B1 |
| **V1-real** | 2–3 weeks of real build objectives; drills X1, X2, X7; MEASURED_OUTCOME | Everyone | — | D2 |

**Owner decisions needed:**
- **O-1:** approve [FILING_AUTHORITY.md](FILING_AUTHORITY.md).
- **O-2:** the supervisor's identity.
- **O-3:** the OAMAB threshold, after V1-real.

## Renumbering from revision 3

| Revision 3 | Revision 4 |
|---|---|
| W0.1 | A1 |
| W0.2 (stop the production-host loop now) | RP1 step 5, after the re-pin, as ruling 11 says |
| PR 3a | PR 2 |
| PR 3b | PR 3 (now the preflight inside `submit_engineering_request`, covering environment and toolchain) |
| PR 4a | PR 10a |
| PR 4b | Dropped: the supervisor no longer writes the inbox; drafts go through CLIVE (PR 8, PR 10b) |
| PR 5 "Try again" | DEC-082 (the Director's) |
| PR 5 "Allow the change" | PR 8 |
| PR 6 | PR 4 (`project` field dropped) |
| PR 7a, 7b, 7c | PR 5a, 5b, 5c |
| PR 8 | PR 6 |
| PR 2 | PR 9 (rows on the build objective) |
| PR 9 | PR 11 |
| PR 10 | PR 12 |
| PR 11 | PR 13 |
| R1 (single re-pin) | RP1 (today's trunk) plus RP2 (loop changes) |
| The inert project packet | Dropped: the project is `Objective(kind=build)` |

## Changes from the original draft sequence (still true)

| Original draft | Where it went |
|---|---|
| Lifecycle metrics | PR 1, fixes and ledgers. `engineering_measures` already exists |
| Project model and packet | `Objective(kind=build)` plus PR 4's request fields plus PR 7's plans |
| Spec compiler | The supervisor (drafts George sees) plus PR 3's preflight plus PR 8's filing decision. No automatic decomposition (DEC-018) |
| Dependency-aware scheduling | PR 4 intake deferral plus PR 5a FIFO |
| Controlled concurrency | PR 5b safety plus PR 13's ladder (ruling 4) |
| Quality routing | PR 3 (paired tests, toolchain), F1 (PR 12), deploy-brief (PR 10a) |
| Reviewer and repair hardening | Already built (DEC-068, DEC-076); verified at RP1 |
| Human-attention contract | PR 6 owner class; PR 8 "Allow the change"; DEC-082 "Try again" |
| Desktop CLI | PRs 10a and 10b |
| Builds UX | PR 9 |
