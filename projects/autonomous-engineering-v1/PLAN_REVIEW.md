# Plan review log

The planning package went through three independent read-only passes, run as fresh agent sessions
that did not write the plan:

1. **The architect.**
2. **The adversarial quality reviewer.**
3. **The final reviewer.**

This file records what each found and what was done about it, so the next session can see why the plan
looks the way it does.

## 1. Architect pass (independent synthesis), 2026-10-14

The architect produced its own design from the audit evidence and was then compared with the
planning lead's draft. Six source facts it raised were checked by the planning lead against the code
and adopted:

| # | Fact | Verified | Effect on the plan |
|---:|---|---|---|
| A1 | A builder-written path must lie inside the objective's immutable `allowed_paths`. Only loop-written generated files are exempt (`dispatcher.py:828-829`) | ✔ | The draft's "scope envelope widening inside the loop" was dropped. Scope is fixed at filing, so validation does the work (P-017) |
| A2 | A dependent's base must contain its predecessors | ✔ | Dependencies gate intake, and the base is chosen at admission (P-010) |
| A3 | `Objective`, `Receipt` and `EngineeringTask` are `extra="forbid"` | ✔ | New facts go in optional request fields plus a `links/` sidecar, so rollback stays possible (P-018) |
| A4 | A receipted id that reappears with different bytes makes the loop refuse the whole snapshot (`controller.py:245-249`) | ✔ | Archiving requires ids checked against receipts and `archive/` (PR 3) |
| A5 | An explicit `clone --bare --local` dies on a failed hard link (`workspaces.py:123`). That is the likely cause of the 4 EXDEV stops | ✔ | Clone fix in PR 7a |
| A6 | With the Claude reviewer, three failed runs block a task, so a plan limit would mass-block reviews | ✔ | The plan-limit pause rides the same re-pin as the reviewer. The three re-pins became one (R1) |

**Adopted from the architect's design:**

- no manifest the loop reads;
- no stored project state;
- no stored risk classes;
- one shared validator;
- `clive-eng` as a protected path;
- `loop{}` self-description;
- FIFO instead of priority;
- re-files instead of in-loop widening or resume.

**Kept from the lead's draft:**

- the inert project packet, as a durable home for intent, acceptance, decisions and the approval
  attestation;
- the blind fault-injection harness;
- the owner-attention instrument;
- `applies_to` skill routing in R1, now inert unless the CLI version is gated.

## 2. Adversarial quality review: CHANGES_REQUIRED (2 blockers, 14 major), 2026-10-14

| # | Severity | Finding | Disposition |
|---:|---|---|---|
| 1 | BLOCKER | PR 5 would put reviewer findings into public request files, against DEC-068. "Allow the change" needs a private channel production may not have | **Fixed.** Re-files keep the same title and paths, and name finding ids only; the loop's `earlier_try` carries the stop report privately. PR 5 moved to D2, after R1. "Allow the change" needs O-18. Acceptance: "the created file contains no finding or builder text" |
| 2 | BLOCKER | `land: false` work could reach trunk after a rollback. The landing proof is written whenever global `land` is on (`dispatcher.py:1464-1475`, verified), and any pin lands proven work, refreshing it if needed | **Fixed.** PR 7c integrates `land: false` work without a proof, so `_eligible` returns None under any pin, with a test against the rollback pin's code. BASELINE_PLAN's wrong "old base cannot land" claim was corrected |
| 3 | MAJOR | A D1 rollback after `archive` could stop intake | **Fixed.** `archive` is gated on a deploy record whose SHA contains PR 3. `unarchive` must run before any D1 rollback. Drill 17 added |
| 4 | MAJOR | Director-PR review was arranged by the author, not bound to a SHA, with no named merger | **Fixed.** Review and merge rule in IMPLEMENTATION_PLAN: the reviewer is started by a non-author with a fixed packet; the verdict is recorded on the PR at its exact head; the merge is by a non-author at that SHA. O-15 settles whether George's go is needed |
| 5 | MAJOR | The CLI's limits were advisory; O-2 contradicted the Director's role | **Fixed.** The code limits are labelled defence in depth. O-2 now covers a trunk ruleset plus an inbox-only identity separate from the Director's PR identity. PR 4b is not in daily use before O-1 and O-2 |
| 6 | MAJOR | `clive-eng bench` contradicted the CLI's own limits | **Fixed.** The verb is dropped. `deploy-brief` shows an existing Bench report. O-16 decides where Bench runs |
| 7 | MAJOR | The D1 deploy mechanism is not installed (no release service) | **Fixed.** D1 and D2 are George's deploys per DEPLOY_LINUX, by hand or with "Deploy now" after O-20. `clive-eng` never deploys |
| 8 | MAJOR | The R1 rollback rehearsal was too narrow | **Fixed.** The rollback pin's `status` and `tick --no-land` run against a copy of the R1 store. If they refuse, the target is the oldest pin that passes. Drill 18 |
| 9 | MAJOR | A green base on an older commit only delays red-trunk stops | **Fixed.** Filing on a red head is refused as Director work. Dependents wait for a green head. The claim was removed from QUALITY_HARNESS |
| 10 | MAJOR | George was still operator for the largest class of stops; owner gestures were undercounted | **Fixed.** Review-limit stops stay in Needs you with a one-hold "Try again" (the cheapest path while the supervisor is not durable). The Director queue is shown as "N waiting, oldest X h". Session starts are counted in OAMAB. Owner gestures are now complete (IMPLEMENTATION_PLAN, HUMAN_ATTENTION). The durable Director is NEXT, decided by data |
| 11 | MAJOR | The ladder lacked resource evidence; review dispatch ignored the cap; the sample was too small | **Fixed.** `loop{}.host` publishes load, memory and I/O pressure. `_dispatch_review` checks the cap (verified: it did not). Each level runs twice, with paired per-task stop rules |
| 12 | MAJOR | The plan-limit pause only reacted after the limit | **Fixed.** At `allowed_warning`, no new builds or reviews start and running work finishes. The payoff was reworded |
| 13 | MAJOR | Owner authority rested on the supervisor's say-so | **Fixed as an owner decision.** The packet approval is labelled an attestation (verbatim words, session, time), matching how 25 Director filings work today. O-17 offers the held CLIVE card, which is NEXT |
| 14 | MAJOR | PR 2 could not read packets (protected reader); replays would clutter the board | **Fixed.** Packet reads moved to PR 3. PR 2 moved to D2, after R1 provides `project`. `land: false` work is hidden behind "Measurements" |
| 15 | MAJOR | PRs 4 and 7 were not PR-sized | **Fixed.** Split into 4a and 4b, and 7a, 7b and 7c, still shipping at one re-pin |
| 16 | MAJOR | V1 against B1 was confounded; project acceptance tests could never fail first | **Fixed.** V1 is judged on real work (V1-real against B0-real); replay projects are a drill only. Acceptance tests are written first as **non-strict** xfail and shown XFAIL at base. Strict xfail was rejected on review, because intermediate members would turn their own CI red |
| 17a | MINOR | PLAN_REVIEW.md was missing | **Fixed:** this file |
| 17b | MINOR | Wrong line references and "could never land" wording | **Fixed:** `dispatcher.py:828-829`; "built without its predecessor's code" |
| 17c | MINOR | Private-channel and tailnet values would be recorded in a public repository | **Fixed.** WORKER01_AUDIT records present or absent only |
| 17d | MINOR | `file` promised one commit through a one-file-per-commit client | **Fixed.** It uses git directly, and the commit is refused if it modifies or deletes any existing `requests/` file |
| 17e | MINOR | O-3 and O-5 were "before any work", yet PR 1 is filed now | **Fixed.** The timing of each decision is stated per step. A single request exercises no concurrency |
| 17f | MINOR | The state tables disagreed, and "completed" and "verified" were merged | **Fixed.** The member road keeps Built (completed) separate from Reviewed (verified). The project tables are aligned |
| 17g | MINOR | Missing fields for PR 11, B1-real and V1; Actions read not listed; PR 1's acceptance not checkable by CI; routing inert on ungated CLIs | **Fixed.** Fields added; O-19 added; a trimmed snapshot fixture; routing is stated as inert unless the CLI version is gated |

## 3. Final review, round 1: CHANGES_REQUIRED (6 material findings; no failure condition triggered), 2026-10-14

The reviewer's spot checks confirmed the source citations, the host facts and the branch's
planning-only state. It found that prior blocker 1 was fixed and prior blocker 2 only partly fixed.

| # | Finding | Disposition |
|---:|---|---|
| F1 | An R1 rollback could land `land: false` work **still in flight**. An older pin does not read `links/`, so it writes a proof at integration and lands the work. The rehearsal could not detect this, and was not specified to be free of side effects | **Fixed.** The rollback runs the older pin with `--no-land` until every `land: false` objective is terminal. The rehearsal includes an in-flight `land: false` objective and is side-effect free (scratch runtime, throwaway local remote, stub worker and reviewer, no network). The "any pin" wording is corrected in IMPLEMENTATION_PLAN (PR 7c and R1), DECISIONS P-009, FAILURE_RECOVERY 18 and 19, and BASELINE_PLAN |
| F2 | A D1 rollback after `archive` runs into the 100-record ceiling (unarchive), or into id reuse (no unarchive) | **Fixed.** PR 3 is split. PR 3a (archive-safe ids and readers) is **roll-forward only** once archived. PR 3b (the validator) is reverted on its own. `unarchive` refuses past the bound. Drill 17 files more than 25 requests after archiving |
| F3 | Planning inputs (baseline scripts, templates, `baseline/` folders) never reach trunk, and a wholesale merge would carry `.mcp.json`, the agents and the CLAUDE.md section | **Fixed.** PR 0 carries `projects/autonomous-engineering-v1/` only, with an acceptance check on the paths it touches. Everything else is O-21. PR 1 now depends on PR 0 |
| F4 | P-015 contradicted the success measure | **Fixed.** P-015 now reads: V1-real against B0-real for owner measures; B1 against history for the machine side; replay projects are a drill |
| F5 | D1 and D2 named both deploys and drills; stale references | **Fixed.** The drills are renamed X1, X2 and X7. BASELINE_EVIDENCE §5 now cites PR 7c, CONCURRENCY_PLAN cites 7a and 4b, and FAILURE_RECOVERY 14 cites 3a and 4b |
| F6 | The incidental index write on production was disclosed only in an appendix | **Fixed.** It is disclosed in README and in IMPLEMENTATION_PLAN's evidence section. The ACCEPTANCE "no host mutation" item stays NOT MET, honestly disclosed: a stat-cache refresh, with no change to HEAD, refs, the working tree or the service |

**Also adopted from its "should see" notes:**

- **The Director rule for project members:** land a loop candidate by fast-forward or merge commit,
  never squash. It is in PR 6's risk section and in the compiler skill.
- **O-3 can be decided now.** It is listed as needed before R1, and George may answer it at once.

## 4. Final review, round 2: **READY**, 2026-10-14

- **All six findings were verified as fixed in the planning files themselves.** No material new
  inconsistency was found, and no failure condition is triggered.
- **The branch is still planning-only.** Every changed path is under `projects/autonomous-engineering-v1/`.
- **One ACCEPTANCE item stays NOT MET, now surfaced to George:** "no host mutation". The audit made
  one incidental stat-cache write to `/opt/crooks-os/.git/index`; HEAD, refs, the working tree and the
  service were unchanged.

**Non-blocking cleanups it listed, all applied:**

- the parallel-work line and the order diagram now agree with PR dependencies (PR 1 after PR 0; PR 4b
  needs PR 3b);
- O-13 cites PR 3b;
- drills X1 and X2 run in V1-real on a real project; the replay project is a dependency drill only;
- the side effect of an R1 rollback under `--no-land` is stated: the Director lands real work
  integrated in that window by hand;
- "Filing after D1" requires validated filing, or an `archive/` and receipt check for any
  hand-commit.

## 5. The CLIVE Director's architectural cross-check (15 Oct): reconciliation, revision 4

The Director session sent an advisory cross-check. George asked for it to be reconciled against the
package and the evidence, with any disagreement recorded here. **Each point was checked against the
source and the host** (read-only, `GIT_OPTIONAL_LOCKS=0`).

**New facts found while checking:**

- **Trunk is now `ef204bc2`**, carrying DEC-079 (docs only, PR #125).
- **Production is now `dc59047e`**, deployed 2026-10-14 19:45:38 UTC (reflog; the service restarted at
  19:46:15). So the Director's "deploy dc59047e" step has already happened, and PRs #122 and #123
  ("CLIVE can file a build again") are live.
- **DEC-080, DEC-081 and DEC-082 are not on trunk yet.** They are the Director's work in progress.
- **worker-01's projection** (generated 2026-10-15 15:28 UTC) is unchanged: 74 requests, with no new
  request since 8 Oct.

| # | Director's point | Evidence checked | Disposition |
|---:|---|---|---|
| 1 | DEC-018 remains in force | DEC-018 status line on trunk: "Reaffirmed in full… not waived, not superseded". DEC-079 ruling 0 | **Adopted.** P-021, plus a DEC-018 section in IMPLEMENTATION_PLAN and DO NOT BUILD (no automatic decomposition, proactive filing, self-adjusting policy, or levels 5 and 6). AUTONOMY_LEVELS updated |
| 2 | Ruling 4: parallel engineering allowed; concurrency is an engineering setting bounded by host, Max plan (live use first), DEC-012 and DEC-043 | DEC-079 ruling 4 text | **Adopted.** Former O-3 removed. RP1 sets 2 (engineering choice: there is no plan-limit pause until RP2, and live CLIVE comes first). The ladder (PR 13) sets the standing value, never automatically. CONCURRENCY_PLAN rewritten |
| 3 | Ruling 9: design a narrower filing-authority model; it returns to George; until built, every filing waits for his hold; a confirmed "Try again" is his hold for that exact re-file | DEC-079 ruling 9 and its DEC-018 boundary | **Adopted.** [FILING_AUTHORITY.md](FILING_AUTHORITY.md) is the design. It is decision O-1, with explicit bounds and a revoke. Built as PRs 7 and 8 only after his approval |
| 4 | Correction 1: DEC-068 and DEC-076 are built and wait only on the re-pin; verify, don't rebuild | `dispatcher.py` `_repair_brief`, `earlier_try`; `reviewers/claude.py`; DEC-068 and DEC-076 status lines | **Adopted.** RP1 is now first, with a verification checklist. Nothing in V1 rebuilds them. **Conditions noted, not disagreements:** skills work only on CLI 2.1.285 or 2.1.293, and browser checks only if Chromium is bound, so RP1's checklist marks those "not applicable" when the host lacks them |
| 5 | Correction 2: after a repair limit, the supervisor judges and drafts; it may re-file inside approved scope under ruling 9; it never dismisses findings, raises repair rounds, touches protected paths, lands or deploys | — | **Adopted.** HUMAN_ATTENTION, ARCHITECTURE (supervisor boundary), PR 10a (`judge`), PR 10b (`draft`), FILING_AUTHORITY (dispositions never dismiss a finding) |
| 6 | Correction 3: the Project = `Objective(kind=build)`; `depends_on` in the request schema; state derived for Builds | `store.py` (KINDS, `engineering[]`, `purpose`, `done_when`, BLOCKER_KINDS, the ladder, owner-only `authorise` at 1556-1578, the rollback-safe design file); `engineering_tools.py:853-865,945-1018` (`objective_id`, `link_engineering`) | **Adopted.** The inert packet and the `project` request field (revision 3) are dropped. PR 7 adds authorised plans in the objective's existing design file, an addition the Director's note implies but did not spell out: ruling 9 needs a record of "a plan or set of requests he saw and approved together", and the store authorises per item today. **This is an extension, not a disagreement** |
| 7 | Correction 4: the supervisor is Claude Desktop on George's Mac running commands on worker-01 as a non-root, read-only user that cannot read the loop's token; it files only through CLIVE's path, never by pushing to the inbox | `_private_write` forces 0700/0600 (`dispatcher.py:2328-2337`); `--private-allow-node` exists (`scripts/remote_engineering.py:198`) | **Adopted.** Revision 3's write verbs are dropped; drafts go to `POST /engineering/drafts` (PR 8, PR 10b). **Stop-report access needs either** RP1's `--private-allow-node` naming worker-01 itself, or PR 6's new `--stops-read-group` at RP2. A plain read group cannot override the forced modes, which the final review found. O-2 recommends the group route, with the channel route only to start before RP2 |
| 8 | Correction 5: bottleneck 18 / 9 / 9 / 8, with re-files multiplying it; order: deploy, re-pin and stop the production-host loop, measure, preflight (environment, base, toolchain and scope), "Try again", archiving, baseline | BASELINE_EVIDENCE §2: 18 repair limit; 13 builder-blocked (about 6 scope, 2 no shell, 4 environment, 1 CI output); 7 red; 4 EXDEV workspace; 2 failed checks. The two groupings agree (scope 6+2, environment or base 4+4+1, CI or checks 7+2) | **Adopted.** The order is IMPLEMENTATION_PLAN stages A–E. The deploy is already done. PR 3 (the preflight) now covers toolchain and environment against a worker profile, then the live `loop{}` |
| 9 | Ownership: DEC-080, DEC-081 and DEC-082 are the Director's; this project owns the listed set | — | **Adopted.** P-022. PR 3 rebases on DEC-081 and is called by DEC-082's "Try again". PR 9 renders DEC-082's item advancement, and PR 8's tests follow DEC-080's style. Revision 3's "Try again" half of PR 5 is removed; "Allow the change" moves to PR 8 |
| 10 | Remove settled owner decisions; still open: ruling-9 design approval, supervisor identity, OAMAB threshold | DEC-079, DEC-071, DEC-064, DEC-072 | **Adopted.** O-1, O-2 and O-3 only. Every removed item is listed with its settling record in DECISIONS.md |
| 11 | Push the plan files for cross-checking | — | Done after this revision's final review returned READY (§6) |

### Where this plan departs from the Director's note, with the reason

- **The production-host loop.** Revision 3 recommended stopping it *before* the re-pin. The Director
  and ruling 11 say *after*. **Revision 4 follows ruling 11** (RP1 step 5). Since RP1 is now first,
  the hazard window is short.
- **The order of the re-pin and the plan-limit pause.** Revision 3 had merged them into one re-pin.
  The concern: with the Claude reviewer in force and no pause, a plan limit fails three review runs
  and blocks a task. **Revision 4 follows the Director's order**, because the largest bottleneck
  (review not converging, 18 blocks) is what RP1 fixes. The risk is accepted and mitigated: a
  conservative concurrency of 2, live use first, blocks recoverable by "Try again", counted in B0, and
  the pause arriving at RP2. This is recorded as a residual risk in RP1, not a disagreement.
- **Archiving.** The Director lists archiving after "Try again". Revision 4 puts the archive-safe code
  (PR 2) in D1 with the preflight, because the inbox has only about 25 records of headroom and
  "Try again" re-files consume it. **The ordering is a minor variance, kept for that evidence.**
- **The supervisor's stop-report access.** It is not available by default (see row 7). It is listed
  under O-2 instead of assumed.

## 6. Final review, revision 4, round 1: CHANGES_REQUIRED (3 material findings; no failure condition)

The review re-verified the source claims and the production SHA (`dc59047e`), and confirmed the
branch is planning-only. It found all 11 Director points adopted, or departed from with evidence.

| # | Finding | Disposition |
|---:|---|---|
| R4-1 | FILING_AUTHORITY would hold a filing he had already gestured a second time (a confirmed "Try again" outside an authorised plan, or past the bounds). "A single chat request is its own scope" had no record | **Fixed.** New rule: a filing carrying his recorded judgment for exactly that draft is FILE, subject only to REFUSE and the preflight. It is never held again and never counts against the bounds, which apply only to untapped filings. PR 7 records a single held request on a build objective as a one-item scope; a request with no objective has none. PR 8 adds acceptance tests for both |
| R4-2 | O-2's "read group on `<runtime>/stops`" cannot work: `_private_write` forces 0700/0600 (`dispatcher.py:2328-2337`, verified), and no PR changed it | **Fixed.** PR 6 adds `--stops-read-group` (0750/0640 to one group, default off) at RP2. RP1 can instead set `--private-allow-node` for worker-01 itself. O-2 recommends the group route. PR 10a states its dependency on whichever route is chosen |
| R4-3 | PRs 5a, 5b, 5c, 6, 10a, 10b and 11–13 lacked Reuse, State change or Problem lines. PR 6's effect on production's filer (the shared `PROTECTED_PATHS`) was unstated | **Fixed.** The missing lines are added. PR 6 states that production also refuses the newly protected paths from D2 |

**Its non-blocking notes, all applied:**

- **An RP1 rollback rehearsal**, cheap and side-effect free, before declaring RP1 done.
- **Actions read.** It is likely not needed while the repository is public, which PR 3 verifies. O-1
  asks for it only if the repository goes private.
- **The worker profile.** PR 3 itself adds `config/worker_profile.json` to `PROTECTED_PATHS`, which
  production's filer enforces from D1.
- **Authority records.** `filing_decision` verifies a plan's `judgment_id` and digest against the
  protected judgment ledger, never trusting the design file alone. A mismatch is HOLD.
- **The hand-commit rule after archiving** is restored in P-019 and D1.
- **README.** The original "durable Project object" text is annotated as superseded by P-011.

## 7. Final review, revision 4, round 2: **READY**, 2026-10-15

- **All three findings were verified as fixed in the files**, and all six non-blocking notes were
  applied.
- **No material inconsistency is new**, and no failure condition is triggered.
- **The branch is still planning-only.**
- **Two wording nits it raised are fixed:**
  - P-009's RP1 rollback now says "the rehearsed pin";
  - RP1's checklist row names worker-01 when O-2 chooses `--private-allow-node`.
- **One ACCEPTANCE item stays NOT MET, surfaced to George:** "no host mutation". The audit made one
  incidental stat-cache write to `/opt/crooks-os/.git/index`, disclosed in README, IMPLEMENTATION_PLAN
  and HOST_AUDIT_RESULTS §8.
