# CLAUDE OUTBOX

**Timestamp:** 2026-09-20 15:23 UTC
**Inbox blob SHA processed:** `b3acae72c9a45f1370e380fba0b43655ea023fd2` (consumed; these instructions must not be executed again)
**Round type:** bounded repository-only repair — Orchestrator V1 freeze H-01 / H-02
**Outcome:** repair complete and published to the freeze-candidate branch only. **Not self-certified.** A fresh independent read-only adversarial review is required.

---

## 1. What was asked

One bounded repository-only repair round on `crooksldn-pixel/clive`, branch
`chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, repairing the two findings that
rejected candidate `5eb25f8`:

- **H-01** — §3 subject transitions can strand live execution records. Fence/cancel every
  non-terminal attempt and `review_dispatch` before a subject transition out of an
  execution-bearing state commits, unless the transition atomically closes that exact record
  through the paired §3A/§3B edge. Cover `candidate.reject`, `integration.reject`,
  `integration.block`, `task.escalate`, `task.fail`; make `task.block` unconditional. Add
  matching triggers to §3A/§3B. Acceptance ST-17. Mechanical test derived from actual §3 rows,
  not prose restatement.
- **H-02** — pre-RUNNING process-group identity / attempt-budget ambiguity. Specify a durable
  handle for a pre-RUNNING preflight process group, and separately specify the durable fact
  used for §3A.2 ceiling accounting; do not overload one field. §1A/§3A/§3A.2/§6 must agree.
  Crash during STARTING must identify and stop the group, then close FENCED without consuming
  budget. QUARANTINED only when cleanup genuinely cannot be proven. Prefer a schema-free repair.
  Acceptance: extend ST-16.

Plus: preserve N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03, G-01..G-03; update traceability;
run the committed mechanical freeze spec test and static checks; independently verify the listed
invariants; publish only to the freeze-candidate branch; do not merge, adopt or deploy.

## 2. Preconditions checked before editing

| Check | Result |
| --- | --- |
| candidate branch resolves to the rejected SHA | **PASS** — `git ls-remote` = `5eb25f8fe00a3196cb27d7b2c92b2b5fbf4a5c78` |
| merge-base is the canonical base | **PASS** — `9e59860a945ec339c69af8709cd0721f0a795327` |
| workspace contains unrelated owner work | **PASS** — none; worktree `/opt/crooks-builder/.worktrees/freeze-repair` was clean at `5eb25f8` |
| stale local tracking ref | **CAUGHT — see below** |

**Stale-ref note (not repaired here, by instruction).** A plain
`git fetch origin <branch>` updated `FETCH_HEAD` but left
`refs/remotes/origin/chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` pointing at the older
`2bf240c`. The candidate was only resolved correctly after an explicit refspec fetch
(`+refs/heads/<b>:refs/remotes/origin/<b>`) cross-checked against `git ls-remote`. **Had the
stale tracking ref been trusted, this round would have edited the wrong tree.** This is the
`remote.origin.fetch` condition CURRENT_TRUTH records as live and runtime-pending; per the inbox
it was **not** repaired, only worked around read-only within this round.

## 3. Builder checkout state found on entry

- Primary builder checkout `/opt/crooks-builder`: branch `claude/builder-environment-repair`,
  HEAD `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, clean. **Not modified by this round.**
- Existing worktrees found: `.worktrees/freeze-repair` (candidate branch, clean at `5eb25f8`)
  and `.worktrees/harness-hooks-experiment` (`2c2b0cc`, untouched).
- All work was done in `.worktrees/freeze-repair`. No branch was switched, reset, cleaned or
  stashed anywhere.

## 4. What was found

**H-01 was a genuine internal contradiction, not a gap.** §3B states normatively that a
`DISPATCHED` dispatch MUST NOT exist under any subject state other than `REVIEWING`. §3
simultaneously admitted `REVIEWING -> REJECTED` via `candidate.reject` on the strength of one
`CHANGES_REQUIRED` verdict while sibling reviewers on other required-review slots were still
`DISPATCHED`. Both statements were normative; they could not both hold. The same shape applied
to `integration.reject`, `integration.verify`, `integration.block`, `task.escalate`, `task.fail`
and `candidate.accept`. `task.block` fenced only *"when continuation unsafe"*, which permitted a
`BLOCKED` task to retain a `RUNNING` attempt.

Critically, this strand is **invisible to the G-01 reconciliation repair**: §1A/§21 detect an
execution-bearing subject with *no* record. H-01 is the dual — a *live* record under a subject
that has already left the set — and reconciliation cannot repair it after the fact, because the
subject is gone. It has to be forbidden at the transition.

**H-02 was a straight ambiguity.** `attempt.process-group/cgroup identity` was declared NULL
until the `RUNNING` commit precisely so §3A.2 could read it as "did a model ever launch?". But
§3A already admitted an owned **preflight** process group during `STARTING` (§5B/§11 preflight
forks real tool processes). So during `STARTING` a group could exist with no durable handle, and
a controller crash there had to quarantine for *missing identity* rather than for *unprovable
cleanup* — burning the workspace and blocking the subject for a case that is actually cleanable.

## 5. What was changed

Repository-only. Five files, one commit.

### `ORCHESTRATOR_V1_STATE_API.md`

- **New §3.1 "Execution-record fencing on subject transitions"** (H-01). Defines the rule as a
  *per-row obligation on the §3 matrix*: a row qualifies when its **From** names an
  execution-bearing state and its **To** names only states outside that set. Every qualifying
  row MUST carry exactly one of two tokens, and **the token is the requirement, not a label for
  one stated elsewhere**:
  - `[EXEC-FENCE]` — in the same transaction, before the subject transition commits, terminate
    every non-terminal `attempt` and `review_dispatch` owned by the subject, stop each owned
    process group per §6, and use QUARANTINED/BLOCKED where cleanup cannot be proven;
  - `[EXEC-ATOMIC-CLOSE: <edge>]` — the same transaction closes exactly those records through
    the named terminal §3A/§3B edge.
  Also normative: the cross-matrix trigger requirement, and immediate release of the freed
  required-review slot, reviewer-concurrency unit, lease and execution slot.
- **§3 rows tokenised** — 15 qualifying rows: `[EXEC-FENCE]` on `candidate.accept`,
  `candidate.reject`, `integration.verify`, `integration.reject`, `integration.block`,
  `integration.cancel` (both rows), `task.block`, `task.escalate`, `task.cancel`,
  `task.supersede`, `task.revise`, `task.fail`; `[EXEC-ATOMIC-CLOSE: §3A CANDIDATE_READY ->
  CLOSED / SUCCEEDED]` on `evidence.register` and `integration.register`. `task.block`'s
  *"when continuation unsafe"* qualifier is **removed** and replaced with "unconditionally".
- **§3A cancellation/fencing edges** now name the full command trigger set per attempt state:
  `CREATED`/`STARTING` gain `task.block`, `task.escalate`, `integration.block`;
  `RUNNING`/`CANDIDATE_READY` gain those plus `task.fail`, `task.supersede`, `task.revise`.
  `CANDIDATE_READY` previously named no command at all ("cancellation/fence before evidence
  completion"); it now does.
- **§3B FENCED edge** gains `candidate.accept`, `candidate.reject`, `integration.verify`,
  `integration.reject`, `integration.block`, `task.block`, `task.escalate` (it already had
  `task.cancel`/`task.supersede`/`task.revise`/`integration.cancel`). The subject-binding
  paragraph now says explicitly that the binding is **not** self-enforcing and holds only
  because §3.1 requires it.
- **New §3A.3 "Pre-RUNNING process-group identity and the ceiling discriminator"** (H-02).
  Schema-free split across two existing fields:

  | Durable fact | Field | Written | Read by |
  | --- | --- | --- | --- |
  | owned-process-group cleanup handle | `lease.owned_process_group_handle` | **before** the group is created — preflight group on `CREATED -> STARTING`, model group on `STARTING -> RUNNING` | §6, FC §21 steps 5/6/11 |
  | execution-ceiling discriminator | `attempt.running_process_group_identity` | exactly once, in the `STARTING -> RUNNING` commit; NULL at all other times | §3A.2 only |

  The write-ahead ordering is the substance: a crash can leave a recorded handle with no group,
  but never a group with no recorded handle. Therefore **NULL is positive proof of no group**,
  cleanup is proven, and the attempt closes `FENCED` — not `QUARANTINED`. `QUARANTINED` is now
  explicitly reserved for a group named by a **non-NULL** handle that cannot be proven stopped,
  and the §3A quarantine row says so. Because `running_process_group_identity` is NULL through
  `STARTING`, crash-and-restart in that window cannot consume execution budget.
- **§1A** gains the two-facts rule and a pointer making §3.1 the enforcement site.
- **§3A.2** now names `attempt.running_process_group_identity` as the authoritative fact and
  forbids reading the lease handle for ceiling purposes (a preflight group would otherwise be
  miscounted as an execution attempt). **R-02 is explicitly preserved**: deterministic preflight
  failure still closes `FAILED`/`QUARANTINED`, never `CANCELLED`/`FENCED`.
- **§6** generalised from attempts to *all three* §1A execution records, identifies the group
  from its durable handle, and adds two normative ordering rules: steps 1–7 complete for every
  owned record **before** the subject transition commits, and resources are released at step 6.
- **§2** command-surface rows updated to match. No new MUST was added to §2 or to §3 proper.

### `ORCHESTRATOR_V1_FREEZE_CONTRACT.md`
- §8 lease contents renamed to `owned_process_group_handle`, with the NULL-is-proof rule;
- §15 states that a decision reached before all reviewers report MUST fence the siblings, stop
  their groups and release their slots;
- §16 references the handle;
- §21 step 5 spells out `STARTING` reconciliation (identify from handle, stop per §6, close
  FENCED, ceiling unchanged, QUARANTINED only for a named unstoppable group); step 6 mirrors it
  for integration attempts; step 11 releases slots/concurrency; a new paragraph names the dual
  inconsistency (live record under a non-execution-bearing subject) and points at §3.1.

### `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md`
- **ST-17 added** — REVIEWING with ≥2 live dispatches followed by `candidate.reject` /
  `task.block` / `task.escalate`; integration REVIEWING with 2 live dispatches followed by
  `integration.reject` / `integration.block`; BUILDING with a RUNNING attempt followed by
  `task.fail` / `task.escalate`. Asserts all records terminal and process groups stopped
  **before** commit, `FENCE_STALE` on a late verdict at unchanged SHA, no stale slot or
  concurrency occupation, and QUARANTINED/BLOCKED where cleanup is unprovable.
- **ST-16 extended** with the crash-during-STARTING + live-preflight-group arm: durable
  identification from the handle, §6 cleanup, FENCED closure, unchanged ceiling, and the
  assertion that the two fields are distinct (handle non-NULL while discriminator still NULL).
- **§18 freeze gate**: two new bullets — the derived no-strand check (explicitly noting it is
  driven by the derived rows, *not* by tokens present, so a token-free matrix fails rather than
  passing vacuously), and the two-named-facts check.
- **§18A MUST-coverage index**: new entries `SA §3.1`, `SA §3A.3`, `SA §6`, `FC §15`; ST-16 /
  ST-17 added to `FC §8`, `FC §15`, `FC §16`, `FC §21`, `SA §1A`, `SA §3A`, `SA §3B`.

### `ORCHESTRATOR_V1_TRACEABILITY.md`
- H-01 and H-02 rows added with full dispositions (**V1 MUST — resolved**).

### `crooks-assistant/tests/test_orchestrator_freeze_spec.py`
Seven new mechanical tests, all **derived from the matrices**:
1. `test_every_subject_transition_leaving_execution_disposes_of_its_records` — recomputes the
   execution-bearing set from §3A.1/§3B, recomputes which §3 rows leave it, requires exactly one
   token per qualifying row, and asserts `task.block` no longer carries the conditional.
2. `test_atomic_close_rows_name_a_real_terminal_attempt_edge` — the escape hatch may only cite a
   §3A edge that exists and is terminal.
3. `test_attempt_and_dispatch_matrices_carry_the_fencing_triggers_section_3_needs` — for each
   leaving row, derives from §3A.1 which attempt states its From-states can actually hold and
   from §3B whether they hold dispatches, then requires that command on the matching terminal
   edge.
4. `test_fencing_frees_the_slot_and_stops_the_process_group_before_the_commit`.
5. `test_pre_running_cleanup_handle_and_ceiling_discriminator_are_distinct_facts`.
6. `test_the_four_sections_agree_on_which_fact_they_use` — including a negative: §6 must **not**
   reach for the discriminator, which is NULL exactly when cleanup matters most.
7. `test_crash_during_starting_is_cleaned_up_without_quarantine_or_budget_loss`.

Also: the F-03 regression guard's three brittle substring assertions were replaced with
structural ones over the §3A rows (the trigger lists changed shape), preserving F-03's substance
— each pre-RUNNING state must carry a *command-triggered* terminal edge, and STARTING must carry
the unproven-cleanup edge. The traceability guard now requires H-01/H-02 dispositions.

**One honest note on test construction.** Test 3 was initially written to iterate rows carrying
`[EXEC-FENCE]`. It then passed *vacuously* on the rejected tree, which has no tokens at all —
the exact false-green shape the inbox warned about. It was rewritten to iterate the rows that
structurally leave the execution-bearing set, with a non-vacuity floor (`checked > 20`). It now
fails at `5eb25f8` as it should.

## 6. SHAs

| | |
| --- | --- |
| canonical base | `9e59860a945ec339c69af8709cd0721f0a795327` |
| rejected candidate | `5eb25f8fe00a3196cb27d7b2c92b2b5fbf4a5c78` |
| **new candidate SHA** | **`9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f`** |
| remote readback | `git ls-remote origin chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` = `9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f` — **matches** |
| merge-base(new, base) | `9e59860a945ec339c69af8709cd0721f0a795327` — unchanged |
| production checkout `/opt/crooks-os/crooks-assistant` | branch `claude/linux-prod-migration-production`, HEAD `1cf3a0f3361b79f9de208d80f501543c53c244b5`, clean — **untouched** |
| production branch `main` on origin | does not exist on this remote |

Publication was to the freeze-candidate branch only. Nothing merged, adopted or deployed.

## 7. Changed-file set and diff summary

`git diff --stat 5eb25f8 9fbe4a9`:

```
 .../ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md           |  21 +-
 .../ORCHESTRATOR_V1_FREEZE_CONTRACT.md             |  16 +-
 .../product-memory/ORCHESTRATOR_V1_STATE_API.md    | 140 +++++---
 .../product-memory/ORCHESTRATOR_V1_TRACEABILITY.md |   2 +
 .../tests/test_orchestrator_freeze_spec.py         | 364 ++++++++++++++++++++-
 5 files changed, 482 insertions(+), 61 deletions(-)
```

`DECISIONS.md`, `ROADMAP.md`, `CURRENT_TRUTH.md`, `ENGINEERING_ORCHESTRATOR_V1.md` and
`WATCHER_BUILDER_IDENTITY_REMEDIATION.md` are **byte-identical to `5eb25f8`**. `DECISIONS.md` is
byte-identical to the canonical base `9e59860`, so DEC-046/DEC-047 sequencing is unchanged and
there is no self-adoption.

**One commit, not two.** The recorded round convention is one commit per repair. H-01 and H-02
both edit the same §3A rows and the same test file, so a split would have produced a red
intermediate commit. Flagging the deviation rather than hiding it; the two repairs are separated
in the commit message body and in traceability.

## 8. Test results

| Gate | Result |
| --- | --- |
| freeze spec test, repaired tree | **38 passed** (31 pre-existing + 7 new), 0.70s |
| freeze spec test, `5eb25f8` documents + new test file | **7 failed, 31 passed** — every new test fails on the rejected tree; every pre-existing test stays green |
| full suite `pytest tests` (run alone) | **2844 passed, 10 skipped** in 500.38s (0:08:20) |
| `ruff check tests/test_orchestrator_freeze_spec.py` | **All checks passed** |
| worktree after commit | **clean** (`git status --porcelain` empty) |

The failing-before evidence was produced by materialising `5eb25f8`'s six product-memory
documents into a scratch tree (`git show`) alongside the new test file, outside the repository,
and deleting it afterwards. The worktree was never dirtied to produce it.

`pytest tests` emits unrelated `RuntimeError: Event loop is closed` noise from asyncio subprocess
teardown at interpreter shutdown. It is post-summary teardown output, not a failure, and the
summary line is green.

## 9. Independent verification (run separately from the test suite)

| Required check | Result |
| --- | --- |
| zero dangling acceptance IDs across the freeze set | **NONE** |
| §18A MUST coverage complete (recomputed from the documents) | **NONE undispositioned**; 39 index entries |
| terminal cleanup path for every non-terminal attempt state | CREATED 1 edge {CANCELLED,FENCED}; STARTING 3 {CANCELLED,FAILED,FENCED,QUARANTINED}; RUNNING 4 {CANCELLED,FAILED,FENCED,QUARANTINED}; CANDIDATE_READY 2 {FENCED,SUCCEEDED} |
| delivery enum / §3C completeness | 5 declared states, **0 unreachable** |
| no self-adoption | `DECISIONS.md` contains no freeze-candidate reference |
| DEC-046 / DEC-047 sequencing | unchanged (file byte-identical to base) |
| §3 rows leaving the execution-bearing set | **15**, each carrying exactly one token (13 `[EXEC-FENCE]`, 2 `[EXEC-ATOMIC-CLOSE]`) — derivation is non-vacuous |
| N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03, G-01..G-03 | all traceability dispositions and their regression guards still green |

## 10. Secret scan

`gitleaks detect --no-git --redact` over the candidate tree: **6 findings, none in any file this
round touched.** Scanning only the five changed files: **no leaks found.** The 6 are pre-existing
synthetic fixtures in `tests/test_observability.py`, `tests/test_observability_redaction.py`,
`tests/test_tts.py` and `tests/test_scribe.py` (all byte-identical to `5eb25f8`) plus one
gitignored `__pycache__` bytecode artifact that is not committed. **No secret value is printed
here or anywhere in this round**, and none was committed.

## 11. Safety constraints — all preserved

`writes_enabled` false; `CROOKS_WRITES_LOCAL_OWNER` false; FastAPI bound `127.0.0.1:8000` only
(verified: `ss -ltn` shows `127.0.0.1:8000`, no public bind; the two `:443` listeners are the
pre-existing `tailscaled`); port 8000 not publicly exposed; proposal/action/verification
semantics untouched; no live Shopify, Gmail or ElevenLabs call and no live external mutation; V2
not begun; UI not touched; Mac deployment and rollback path untouched; `/root/.claude` writable;
production checkout never edited, switched or reset. `crooks-assistant.service` active,
`crooks-bridge-watcher.service` active (this run), `crooks-bridge-watcher.timer` inactive — all
observed read-only, none changed.

## 12. Errors and deviations

- **No errors.** No blocked permission, no widened permission, no workaround sought.
- **Deviation 1 — one commit instead of two.** Reason in §7.
- **Deviation 2 — persistent memory not written.** The inbox forbids `/root/.claude` changes. My
  cross-round memory lives under `/root/.claude/projects/.../memory/`, so the freeze-review-chain
  note still records `5eb25f8` as the head awaiting review. Read literally, updating it is out of
  scope for this round. **A future round will therefore see a stale memory pointer**; this outbox
  is the authoritative record. If the owner wants that memory kept current, the next inbox should
  say so explicitly.
- **Not repaired, by instruction:** the live watcher/builder branch mismatch and the stale
  `remote.origin.fetch` refspec. Both remain runtime-pending. The refspec bit this round (§2) and
  was worked around read-only.

## 13. Decisions and questions needing review

1. **The token mechanism is a deliberate design choice.** `[EXEC-FENCE]` /
   `[EXEC-ATOMIC-CLOSE]` are literal markers in the §3 preconditions cells. This is slightly
   foreign to the document's prose voice, and it was chosen precisely because the inbox forbade a
   repair that two prose restatements could false-green. A reviewer may reasonably object to the
   notation; the *obligation* would survive a different notation, but the mechanical check would
   need re-deriving. This is the main stylistic judgement call of the round.
2. **`candidate.accept` carries `[EXEC-FENCE]` even though no live dispatch should exist there.**
   By the time all required slots have ACCEPT verdicts each dispatch is already `COMPLETED`, so
   the obligation is normally vacuous. It is required anyway because `ACCEPTED` is terminal and
   §3B forbids a surviving `DISPATCHED` row under it. The reviewer should confirm this is
   belt-and-braces rather than an admission that acceptance can race a replacement dispatch.
3. **H-02 was solved schema-free, as the inbox preferred**, by renaming two existing fields to
   `lease.owned_process_group_handle` and `attempt.running_process_group_identity`. No column is
   added. The renames are the minimum needed to satisfy "explicitly named, distinct in role"; a
   reviewer who considers a rename a schema change should say so.
4. **`integration.reject` is required in §3B but deliberately *not* in §3A.** It fires only from
   `REVIEWING`, which §3A.1 binds to no attempt state, so listing it as an attempt-fencing
   trigger would contradict §3A.1. The same reasoning excludes `task.fail` from §3B. The
   mechanical test derives these exclusions rather than hardcoding them; worth an adversarial
   look.
5. **The previous verdict is stale for the changed SHA.** The ACCEPT/REJECT of `5eb25f8` says
   nothing about `9fbe4a9`.

## 14. Exact proposed next step

**Dispatch exactly one fresh, independent, read-only adversarial review bound to candidate SHA
`9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f`** on branch
`chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, base
`9e59860a945ec339c69af8709cd0721f0a795327`.

The reviewer should be told:

- the previous verdict is **stale**; `5eb25f8` is no longer the branch head;
- the review is **read-only** — no edits, no commits, and per the recorded convention verify
  document content via `git show <sha>:<path>` rather than by mutating a worktree;
- targets: whether §3.1's derivation is genuinely complete (are there §3 rows leaving the
  execution-bearing set that the derivation misses — e.g. via a From-cell phrasing the parser
  reads differently); whether the `[EXEC-ATOMIC-CLOSE]` escape can be abused; whether §3A.3's
  write-ahead-ordering argument actually holds against a crash *between* the handle commit and
  the fork, and against a handle that is **stale** rather than absent; whether the two field
  roles leak anywhere; and the open questions in §13 above;
- regressions to re-confirm: N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03, G-01..G-03.

**Do not merge, adopt, deploy or self-certify.** No further repair task should be dispatched
until that review returns.
