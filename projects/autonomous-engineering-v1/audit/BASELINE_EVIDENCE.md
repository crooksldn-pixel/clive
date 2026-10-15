# Baseline evidence: what the loop's own records say (as of 2026-10-14)

**Method:** read-only. The work was done by the baseline-miner agent of the planning session. The two
scripts it used are in [`../baseline/`](../baseline/):

- `walk_status.py` walks every snapshot commit of a status branch and records each request's stage
  transitions at the snapshot time.
- `analyse.py` joins those transitions with the inbox filing commits and trunk reachability.

Both read with `git log`, `git show` and `git cat-file` only. To reproduce:

```bash
python3 -I -B baseline/walk_status.py <repo> origin/clive/control/worker-01-status <out>/w01.json
python3 -I -B baseline/walk_status.py <repo> origin/clive/control/status <out>/st.json
python3 -I -B baseline/analyse.py <repo> <out>
```

## 1. Sources

| Source | What it holds | Coverage | Reliability |
|---|---|---|---|
| `clive/control/worker-01-status:status.json` | 74 requests: `recorded_at`, `attempts[]`, `build_history`, `repairs`, `review`, `github_acceptance`, `acceptance`, `integration`, `landing`, `blocker`, `stage` | 3,543 snapshots, 25 Sep → 14 Oct | Best source. The final snapshot keeps only the last round, so per-round data needs the snapshot history |
| `clive/control/status:status.json` | The production-host loop: 27 requests | 24–25 Sep | Older schema: no `repairs`, `github_acceptance` or `landing` |
| `clive/control/{worker-01,owner}-inbox` | `requests/*.json`. The commit time is the filing time and the commit author is the filer | 24 Sep → 8 Oct | The request has no timestamp, no requester and no `supersedes` link |
| `clive/engineering-state` | The kernel store of the operator era: 12 tasks | 22–23 Sep | Complete per-round history, for that era only |
| `clive/objective/*` (75 branches) | Final candidates | 23 Sep → 8 Oct | — |
| `clive/trunk` | 121 PR merges, loop pushes, direct pushes | from 20 Sep | **`--first-parent` is unreliable.** Loop merges make old trunk the second parent; 14 PRs are invisible to first-parent |
| `reports/deploy-*.md` | Three deploy records (plus 09b633cc on its own branch) | 1–9 Oct | Markdown only; there is no deploy log |
| `app/engineering_measures.py` | Computes submitted→trunk→production, review rounds, owner minutes | — | **Its deploy-log and attention-log inputs exist nowhere**, and it has four defects (§4) |

## 2. Numbers computable now

### Volume and outcome

**Up to 1 Oct, the CURRENT_TRUTH tally reproduces exactly:**

- 65 requests: 21 COMPLETE, 40 BLOCKED, 2 OWNER_GATE, 2 refused.
- The 40 BLOCKED: 17 at the repair limit, 10 blocked by their builder, 7 on a red GitHub run, 4 on
  workspace errors, 2 on failed checks.

**Extended to 14 Oct on worker-01:**

- 74 requests: **26 COMPLETE (35%)**, 44 BLOCKED, 2 OWNER_GATE, 2 refused.
- The 44 BLOCKED: 18 at the repair limit, 13 blocked by their builder, 7 on a red GitHub run,
  4 on workspace errors, 2 on failed checks.
- No request has been filed since 8 Oct 14:57Z.

**The production-host loop:** 27 requests, 5 of them COMPLETE.

**Both loops together:** 101 requests, **31 COMPLETE (31%)**.

**Activity:** requests were filed on 7 of 21 days: 10, 38, 11, 9, 24, 5 and 4 on 24, 25, 26 and 30 Sep
and on 1, 7 and 8 Oct.

**Re-files:** the 101 requests form 52 chains (re-files `-2…-6` grouped). **49 of the 101 requests are
re-files.** 31 chains (60%) reached COMPLETE.

**Who landed the 31 COMPLETE builds:**

| Landed by | Builds |
|---|---|
| The loop itself (1–8 Oct) | 12 |
| A human PR merge | 17 |
| An old dispatcher push | 1 |
| Never reached trunk | 1 |

A further 15 BLOCKED candidates reached trunk only through human PRs (#25, #66, #80–#84).

**Since DEC-071 ruling 9** (8 Oct, "the loop is the normal way work lands"), 2 requests were filed to
the loop and **13 PRs (#112–#124) landed outside it**.

### ETAB (elapsed time per accepted build)

| Measure | n | Median | Note |
|---|---:|---:|---|
| Filed → on trunk, loop self-landed | 12 | **0.65 h** | range 0.22–1.05 h |
| First filing of the chain → on trunk, loop self-landed | 12 | **2.33 h** | max 20.2 h |
| Filed → on trunk, human-landed accepted builds | 18 | 3.03 h | max 9.15 h |
| First filing of the chain → on trunk, human-landed | 18 | 7.96 h | max 26.3 h |
| Loop acceptance → human merge (the courier wait) | 18 | 2.19 h | max 8.27 h |
| Filed → terminal, COMPLETE | 31 | 23 min | p90 51 min |
| Filed → terminal, BLOCKED | 58 | 35 min | p90 74 min |
| Trunk → production, 1 Oct loop landings | 6 | 4.2–8.8 h after filing | Deploy `718fbc41` |
| Trunk → production, 7–8 Oct loop landings | 5 | **>6 days, still waiting** | The trunk is undeployed |

### Stage durations (snapshot resolution ~1 min)

| Stage | n | Median | p90 | max |
|---|---:|---:|---:|---:|
| Queue: filed → ASSIGNED | 88 | **0.4 min** | 7.3 | 33 |
| Build per attempt | 204 | 4.7 min | 18.0 | 28.4 |
| CI: candidate → GitHub acceptance | 78 | **10.0 min** | 11.2 | 35.6 |
| Review dispatch → verdict (GPT) | 162 | 1.1 min | 3.2 | — |

**Per self-landed request:** build 8.0 min, **CI 27.9 min**, review 1.9 min. CI is about 70% of
machine time, because every repair and every refresh re-runs the full acceptance.

**worker-01 totals:** 1,130 builder-minutes, 794 CI-minutes and 168 review-minutes for 26 accepted
builds, which is about 43 builder-minutes per accepted build.

### Repair and review

**First-pass review READY: 12 of 48 reviewed requests (25%).**

| Review repair rounds | Reviewed requests | COMPLETE requests |
|---|---:|---:|
| 0 | 12 | 12 |
| 1 | 11 | 10 |
| 2 | 12 | 3 |
| 3 | 13 | 1 |

- **Attempts:** 175 in total: 121 candidate, 45 blocked, 9 refused.
- **Revisions:** 68 build, 79 repair, 21 integration refresh.
- **Refreshes:** 7 of the 26 COMPLETE needed at least one integration refresh. 3 of them hit the
  refresh cap, and the Director landed them.

### Why requests blocked (worker-01, 44 BLOCKED)

- **18 at the repair limit.**
- **13 blocked by their builder:**
  - ~6 on a scope or `allowed_paths` mismatch;
  - 2 on having no shell;
  - 4 on a base or environment that failed a declared check (node missing, sandbox loopback, a
    pre-existing failing test, a timing race);
  - 1 on unreadable CI output.
- **7 on a red GitHub run.** 6 of them on 30 Sep; the cause needs the GitHub API.
- **4 on workspace errors** (EXDEV cross-device link).
- **2 on failed checks.**

**Roughly half of all blocks come from the request specification or the environment, not from code
quality.**

## 3. What cannot be computed, and the instrument each needs

| Missing | Instrument |
|---|---|
| Owner intent time (the true start of ETAB) | `submitted_at`, `requested_at`, `requested_by` and `origin` on the request |
| Chain identity | A `supersedes` field |
| Per-round CI and review history | An append-only per-request event list in the status (or the private channel): ci_started, ci_completed (run id, conclusion, duration), review_dispatched, verdict (counts), repair_routed, refreshed, landed |
| Human landing of loop work | `landing.by = director|owner`, with `pr` and `merged_at`, or a `Request: <id>` trailer on landing PRs |
| Deploys | The release service's JSONL log `{sha, deployed_at, approved_by, approved_at, rollback}`, which is `engineering_measures --deploy-log`'s schema |
| **OAMAB** | Nothing records owner time, and git authorship cannot separate George from Claude sessions using his account. Needed: (a) an owner-attention ledger `{at, minutes, about}` written at each owner gesture (CLIVE hold, passkey approval, Builds ruling, filing, deploy approval, phone check); (b) owner-turn timestamps from Director/supervisor transcripts, with an idle cutoff; (c) manual relay entries for Termius, sudo and re-pin steps; (d) the DEC-076 GitHub Apps, so commit identity separates people from agents |
| **ABER** | A defect record `{found_at, found_by, introduced_by (sha/PR/request), severity, fixed_by}`. Make `fixes:` mandatory on fix requests and fix PRs |

**OAMAB proxies that exist today (not minutes):**

- 49 re-files, each a manual rewrite of scope.
- 33 human landings of loop work.
- 7 in-app filings on 30 Sep.
- DEC-071: 43 rulings answered in about 9 minutes.
- Waivers on three deploys.
- The Termius re-pin relay.

## 4. Defects in the existing `engineering_measures`

1. `pull_request_of` matches `Merge pull request #N` and `(#N)`, but trunk subjects say `(PR #N)`. The PR column is always empty.
2. Its first-parent landing walk misattributes the 14 hidden PRs, and it uses commit time, not push time.
3. `review_rounds = revision − 1 + verdicts` counts integration refreshes and refused builds as review rounds.
4. It counts BLOCKED requests as "landed" when a human later merged their candidate.

## 5. Proposed baseline task set (real, replayable at their own `base_sha`)

| # | Type | Request chain | Why |
|---:|---|---|---|
| 1 | Small bug fix | `voice-credits-honest-3` | A real production defect, READY on first review. Its chain has one repair-limit block and one workspace error |
| 2 | Backend fix with a scope trap | `fix-item-search-failures-order-creation` → `-2` | The first try was blocked on a protected mutation; chain ETAB 20.2 h |
| 3 | External API | `expose-draft-order-s-payment-link` (`-1…-3`) | All three died on red CI; landed by hand (PR #66) |
| 4 | UI and backend | `followups-app-page-and-cards` | 9 findings, 3 refreshes, hit the refresh cap; landed in PR #79 |
| 5 | Test-only repair | `deflake-reply-turn-enrichment` | A real race that turned trunk red twice; self-landed after one repair |
| 6 | Behavioural prompt | `clive-voice-uses-the-clock` → `-2` | The first try blocked on unreadable CI output |
| 7 | Cross-component | `skill-read-runtime-tool` (`-1…-4`) | OWNER_GATE → builder-blocked → red → repair limit; finished by hand in PR #98 |
| 8 | Ambiguous request | `owner-facing-host-wording` (`-1…-6`) | Six filings because `allowed_paths` never matched where the strings lived |
| 9 | Scope or security conflict (optional) | `production-strict-mcp` → `-2` | An existing test pinned the opposite behaviour |
| 10 | Parallel wave (optional) | `knowledge-digester-adapter-*` | 8 in parallel, 7 at the repair limit, landed by hand (PR #25, "64 repairs") |

The checks' argv hard-code `/home/user/clive/crooks-assistant/.venv`, so a replay must name the
interpreter the replay host has. **Replays must never land:** see PR 5c and the RP2 rollback rule in the implementation plan.

## 6. ABER: concrete escapes

1. **Before the GitHub gate existed, three loop-accepted builds landed by PR broke trunk CI:** PR #8 `7914ed8d`, PR #9 `ba6d7103` and PR #11 `55a9bece`. Trunk was red until PR #12 `87c4f8c4`. That is at least 3 of 30, about 10%, as a lower bound.
2. **PR #94 `cac1a9e7`** merged with no review (137 files) and was deployed on a waiver. The post-deploy review raised 7 notes, fixed in PR #95 `b33ccbc2`.
3. **PR #73 `cdd5bcbf` (the team build):** review after merge found 6 work-list defects and 3 staff-turn gaps.
4. **The round-12 deploy review** found 62 findings (PR #58), and 50 follow-ups were filed to the loop on 1 Oct.
5. **Flaky or time-dependent tests reached trunk:** PR #86, PR #93, `deflake-reply-turn-enrichment`, `fixture-clock-dst-nights-2`.
6. **Production defects found after deploy:** the ElevenLabs credits outage (fixed in PR #9), age-days rounding, London-versus-UTC day boundaries (PR #99), and a read-only path for `people.json`.

DEC-062 already names "defects found after acceptance" as the measure for judging a reviewer, and no
such record is kept.
