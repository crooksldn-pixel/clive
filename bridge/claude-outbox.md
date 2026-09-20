# CLAUDE OUTBOX

**Timestamp:** 2026-09-20 14:15 UTC
**Inbox SHA processed:** `0fe99fdf734a845734aaaeee829af504034b75f7` (consumed — this round executed those instructions and only those)
**Round type:** fresh independent **read-only** adversarial review. Nothing was edited, committed, pushed, merged, checked out, reset, cleaned or stashed. No worktree was created. No runtime, systemd, watcher, secret, connector, privilege, production or business state was touched.

---

## VERDICT

### `CHANGES REQUIRED BEFORE OWNER DECISION`

Two material engineering blockers, both in the newly added G-01/G-02 text. G-03 survived every attack I could construct. The previous verdict was treated as stale and nothing was certified on the strength of it.

---

## 1. What was asked

Re-review Orchestrator V1 freeze candidate `5eb25f8` read-only: verify the four preconditions, re-attack G-01/G-02/G-03, hunt for new material defects across state legality, cancellation/restart races, stale-result admission, idempotency, attempt-budget safety, journal completeness, §18A coverage, structural-test false greens, N/B/R/F regressions and self-adoption; verify mechanically without violating read-only scope; return exactly one of two verdicts.

## 2. Preconditions — all four verified

| # | Check | Result |
| --- | --- | --- |
| 1 | candidate branch resolves to `5eb25f8fe00a3196cb27d7b2c92b2b5fbf4a5c78` | **PASS** — `git ls-remote origin refs/heads/chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` → `5eb25f8fe00a3196cb27d7b2c92b2b5fbf4a5c78` |
| 2 | canonical base resolves to `9e59860a945ec339c69af8709cd0721f0a795327` | **PASS** — `git ls-remote origin refs/heads/claude/product-memory-foundation` → `9e59860a945ec339c69af8709cd0721f0a795327` |
| 3 | merge-base(candidate, base) == canonical base | **PASS** — `git merge-base 5eb25f8 9e59860` → `9e59860a945ec339c69af8709cd0721f0a795327` |
| 4 | `31b0e07..5eb25f8` is exactly one repair commit | **PASS** — `git rev-list --count` → `1`; `5eb25f8 docs: repair stranded ASSIGNED reconciliation, ceiling accounting and delivery crash window`, authored Claude, 2026-09-20 13:42:02 +0000 |

Note: the local remote-tracking ref `origin/chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` is stale at `2bf240c`. The refs above were fetched by explicit full refname and cross-checked against `git ls-remote`, so this review is bound to the true remote tips, not to the stale tracking ref.

Repair commit shape — 5 files, +388/−26: the four freeze docs plus `crooks-assistant/tests/test_orchestrator_freeze_spec.py`. Full diff read line by line.

## 3. Blockers

### H-01 (BLOCKER) — the new subject-binding claims in §3A.1 and §3B are falsified by §3's own matrix, and the structural test cannot see it

**Location:** `ORCHESTRATOR_V1_STATE_API.md` §3A.1 (lines 374–385, "Every edge above either leaves the subject state alone or is paired with a §3 subject edge"), §3B subject-binding paragraph (line 427, "a `DISPATCHED` dispatch MUST NOT exist under any other subject state"), consumed by §1A (line 252) and `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §21 (line 609). Test: `crooks-assistant/tests/test_orchestrator_freeze_spec.py:568` `derived_execution_bearing_states()`.

**The defect.** §3A.1's premise is false. §3 contains subject edges that are *not* paired with any §3A/§3B record edge and that move the subject out of an execution-bearing state while leaving the execution record non-terminal. I enumerated §3 mechanically; five such edges exist:

| §3 edge | Record left non-terminal | Row fences it? |
| --- | --- | --- |
| `REVIEWING → candidate.reject → REJECTED` | `review_dispatch` DISPATCHED on every *other* required-review slot | no |
| `integration REVIEWING → integration.reject → integration REJECTED` (terminal subject) | `review_dispatch` DISPATCHED | no |
| `integration CREATED/INTEGRATING/EVIDENCE_READY/REVIEWING → integration.block → BLOCKED` | `review_dispatch` DISPATCHED; integration `attempt` | no |
| `any nonterminal active → task.escalate → ESCALATED` | `attempt` RUNNING/CANDIDATE_READY; `review_dispatch` DISPATCHED | no — the row states no fencing at all |
| `BUILDING/REJECTED → task.fail → FAILED` (terminal subject) | `attempt` RUNNING/CANDIDATE_READY | no |

(`task.block` fences the attempt only "when continuation unsafe", so it is a sixth, conditional case. `task.cancel`/`task.supersede`/`task.revise` and `integration.cancel` *are* properly covered — §3B names them as FENCED triggers.) §3B's FENCED trigger row lists `task.cancel`/`task.supersede`/`task.revise`/`integration.cancel`/epoch change — it does **not** list `candidate.reject`, `integration.reject`, `integration.block`, `task.block` or `task.escalate`. §3A's CANCELLED/FENCED triggers likewise omit `task.fail` and `task.escalate`.

**Failure scenario (concrete).** A task in `REVIEWING` has two required-review slots, both `DISPATCHED`. Reviewer A returns CHANGES_REQUIRED. `candidate.reject` fires — its precondition is satisfied by "one or more required reviews CHANGES_REQUIRED" — and the task becomes `REJECTED`. Reviewer B's dispatch is still `DISPATCHED`, its reviewer model process still running and still kernel-owned, under a subject state that §3B now says it MUST NOT exist in. The task takes the bounded-correction path `REJECTED → attempt.assign → ASSIGNED`. Now: (a) §3B's normative MUST NOT is violated on an ordinary, expected path — not an edge case; (b) per FC §19 (line 556) the stale dispatch keeps consuming the reviewer-concurrency ceiling and keeps its required-review slot occupied until its expiry deadline, so the next `review.request` for that slot is refused by the slot-uniqueness precondition; (c) if the controller restarts in that window, FC §21 step 8 must, "for each required-review slot either create exactly one replacement dispatch under a new fencing token or block the subject" — but the subject is now `ASSIGNED`/`BUILDING`, and §3B admits dispatch creation only while the subject is `REVIEWING`, so step 8 has no legal action and either fails closed or blocks a task that is legitimately building. The `integration.reject` variant is worse: the integration subject is terminal, so step 8 can neither replace nor block, and the reconciliation obligation is unsatisfiable on every subsequent restart. The `task.fail` variant leaves a live model process with a live lease under a terminal `FAILED` task, terminated only by its own stall deadline or the next epoch change.

**Why this blocks the freeze rather than being cosmetic.** G-01's entire repair is the move from a hand-written enumeration to a *derivation*. §1A and FC §21 now say the execution-bearing set is "derived mechanically" from §3A/§3B. That derivation is sound only if §3A.1/§3B correctly characterise which subject states can hold a non-terminal record — and they do not. A normative freeze document must not contain a MUST NOT that its own transition matrix violates on a normal path. The defect in §3 is pre-existing and latent; this commit converts it into an internal contradiction and builds G-01's reconciliation rule on top of it.

**Additionally, the structural test is a false green.** `derived_execution_bearing_states()` does not derive from the §3/§3A/§3B *edges*. It parses §3A.1's restatement table and applies a regex to §3B's prose sentence, then compares that to prose in §1A and §21. `test_attempt_matrix_binds_every_nonterminal_state_to_a_subject_state` only checks that the subject-state *names* in §3A.1 appear somewhere in §3 — not that the pairing is correct or the table complete. So the gate compares two hand-written restatements of each other and passes, which is precisely the "coverage asserted but nothing verified" shape the test module's own docstring says it exists to prevent.

**Smallest bounded repair.**
1. In §3, add explicit execution-record termination to the five rows above, mirroring wording already present in the `integration.cancel` row ("every non-terminal `review_dispatch` for this integration is fenced"): `candidate.reject`, `integration.reject`, `integration.block`, `task.escalate` and `task.fail` MUST fence every non-terminal `review_dispatch` and any non-terminal `attempt` for that subject, stopping owned process groups per §6, before the subject transition commits; make `task.block`'s fencing unconditional.
2. Add those triggers to §3B's FENCED row and to §3A's CANCELLED/FENCED trigger lists so the record matrices agree.
3. Either delete §3A.1's false premise sentence or make it true by construction.

**Exact mechanical test.** Replace the restatement-parsing derivation with a real one: for every §3 row, take its From-state set and its To-state set; if any From state is execution-bearing and the To state is not, assert the preconditions cell states that the corresponding execution record is fenced/terminal. Keep the existing set-equality of the derived set against §1A and §21. **Acceptance case (new, e.g. ST-17):** "a subject in `REVIEWING` with two live dispatches is rejected/blocked/escalated, or a `BUILDING` task is failed/escalated — every non-terminal execution record for that subject is terminal and its owned process group stopped before the subject transition commits; no `DISPATCHED` dispatch and no non-terminal `attempt` exists under any subject state outside the derived execution-bearing set; the freed required-review slot and reviewer-concurrency capacity are immediately reusable." This case fails against `5eb25f8` today.

### H-02 (BLOCKER) — the pre-`RUNNING` process-group handle is unspecified, so §3A's STARTING cleanup and therefore the §3A.2 ceiling outcome are implementation-dependent

**Location:** `ORCHESTRATOR_V1_STATE_API.md` §1A `attempt` record line 78 (new text: process-group/cgroup identity "NULL until the attempt commits `RUNNING`, non-NULL from then on"), against §3A rows 362–363 and §6 step 3; consequence in §3A.2 (line 402) and acceptance ST-16.

**The defect.** §3A rows 362–363 make the terminal disposition of a `STARTING` attempt depend on proving "any preflight process group" stopped and empty: proven → `CANCELLED`/`FENCED`; unprovable → `QUARANTINED`. §6 step 3 executes that against "the attempt cgroup/process group". This commit newly pins the attempt row's process-group identity to NULL before `RUNNING`, because §3A.2 overloads that column as the "did a model ever launch" discriminator. Nothing in the freeze set then says where a *preflight* process group's identity is durably recorded. The `lease` record does carry a `runner/process-group identity` field, but no section says it is populated at preflight rather than at launch, and §1A's rule points §6 at "that record's own process group", i.e. the attempt.

**Failure scenario.** The controller dies mid-preflight with the attempt `STARTING`. On restart, FC §21 step 3 increments the epoch and fences that attempt. Kernel A, which wrote the preflight group id to the lease, proves the group empty, closes `FENCED`, consumes no ceiling. Kernel B, which took §1A literally and has no durable handle at all, cannot identify the orphaned preflight process group, cannot prove it empty, and must close `QUARANTINED` per row 363 — and §3A.2 makes `QUARANTINED` ceiling-consuming. Three such crashes and Kernel B has exhausted all three execution attempts and escalated a task on which no model ever ran, while also leaving three unidentifiable orphan process groups. That is the exact class of failure G-02 was raised to eliminate, merely relocated from `CREATED` to `STARTING`. §7's stated purpose — "two conformant kernels MUST NOT be able to disagree about whether a given failure is automatically retried" — is violated directly. ST-16's scenario is written only for "a `CREATED` attempt", so the acceptance gate is structured to miss the `STARTING` window entirely.

**Smallest bounded repair.** Stop overloading one column with two jobs. Either (a) state in §1A that the `lease`'s `runner/process-group identity` is written when any owned preflight process group is created and is the handle §6 uses before `RUNNING`, and say so in §3A rows 362–363; or (b) declare an explicit `reached_running` marker (the `attempt` row already carries a start timestamp — name which field is authoritative) as the §3A.2 discriminator, freeing the process-group column to hold the preflight group. Either way §3A.2's "no additional column is introduced" claim must be restated against whichever fact it actually reads.

**Exact mechanical test.** Assert that §3A.2's discriminator field and the field §6/§3A use to terminate a pre-`RUNNING` process group are named, are distinct, and that §1A declares when each is populated. **Acceptance case: extend ST-16** with a crash-during-`STARTING` arm — kill the controller with the attempt `STARTING` and a live preflight process group; on restart the group is identified from its declared durable handle, stopped per §6, the attempt closes `FENCED`, and the ceiling is unchanged. Also assert `QUARANTINED` is reachable here only when cleanup genuinely cannot be proven, never merely because no identity was recorded.

## 4. What I attacked and could NOT break (verified sound at `5eb25f8`)

**G-01, the part that was repaired.** `ASSIGNED` really is now covered. §3A.1 binds `CREATED`/`STARTING` → `ASSIGNED` (TASK) / `INTEGRATING` (INTEGRATION); §1A and FC §21 restate the identical derived set `{ASSIGNED, BUILDING, REVIEWING}` / `{INTEGRATING, REVIEWING}`; the epoch-fenced `CREATED`/`STARTING` attempt no longer strands the task. Reconciliation uses the already-listed `task.block`/`integration.block` edge with typed `EXECUTION_RECORD_MISSING` (classified BLOCKED in §7) — no new transition, no blind redispatch. The `CANDIDATE_READY → BUILDING` binding is correct: `evidence.register`/`integration.register` advance the subject and close the attempt `SUCCEEDED` in one transaction, so the attempt is never non-terminal under `EVIDENCE_READY`. The §3/§3A joint oracle remains satisfiable after the split — §3A.1/§3A.2 add no edges, only classifications. **The forward direction of G-01 is fixed; H-01 is the reverse direction, which the repair asserts and does not enforce.**

**G-02.** §3A.2 is total over the declared disposition enum `SUCCEEDED|FAILED|CANCELLED|FENCED|QUARANTINED` plus the non-terminal states — I recomputed the enum from the `attempt` record and matched it against the classification table independently; every member is classified exactly once. `CANCELLED`/`FENCED` that never reached `RUNNING` does not consume. Deterministic preflight failure stays budget-consuming because §3A closes it `FAILED`/`QUARANTINED`, never `CANCELLED`/`FENCED` — R-02 is not weakened. The ceiling guard is still present on both `attempt.assign` rows (`PLANNED` and `REJECTED`) and in §3A. **Disposition relabelling cannot game the budget:** FC §10.3.1 (line 279) says "a terminal disposition is written once and MUST NOT be rewritten", and §1A line 78 says the process-group identity is "non-NULL from then on", which forbids the natural attack of clearing that identity during post-fence cleanup to convert a consuming attempt into a non-consuming one. Because the count is a pure function of immutable committed rows, restart/restore/epoch change can neither reset nor decrement it. (Nit §5.4 below: §3A.2 cites §4 for that immutability and §4 does not say it — the real rule is FC §10.3.1.)

**G-03 — attacked hard, no break found.** The arming increment is committed before the external effect and is the only admissible route to an initiated effect (`PENDING count = 0 → PENDING count >= 1`). `delivery.publish` is admissible from `PENDING` only, and every publish row carries an explicit `attempt count` precondition, so no state admits an effect without the evidence committed first. A `PENDING` record with a non-zero count cannot be replayed — restart/restore/epoch change MUST move it to `UNKNOWN` before any further external effect (§3C row + FC §21 step 10), and publish from `UNKNOWN` is refused with `REMOTE_EFFECT_UNKNOWN`. `delivery.reconcile` against authoritative remote state is the only exit from `UNKNOWN` and performs no external effect, so it never touches the counter. The crash-before-increment case is handled distinctly and correctly (count = 0 survives, publish remains admissible). **The multi-effect-per-call attack fails:** the matrix admits exactly one arming row, "any delivery transition not listed above is forbidden", and a second effect would require a second increment that no row admits. `PUBLISHED`/`BLOCKED` are terminal with no publish row; `FAILED` reaches only `BLOCKED` and requires a new delivery/idempotency record for any further publication. Interaction with `delivery.block` and `controller.reconcile` produces no duplicate effect (see non-blocking note §5.1).

**Mechanical verification, independently recomputed from committed blobs.** I did not check out the candidate. I extracted the exact blobs with `git show` into a scratch outside the repository, verified each extraction with `git hash-object` against `git rev-parse <sha>:<path>` (STATE_API `305c8ba…`, FREEZE_CONTRACT `7f044b9…`, ACCEPTANCE_MATRIX `969e07c…`, TRACEABILITY `da3be3c…`, test module `0ca2432…` — all exact), and ran there.

- Committed spec suite against `5eb25f8` blobs: **31 passed in 0.44s**.
- Same test module against `31b0e07` blobs (failing-before evidence): **8 failed, 23 passed** — `test_execution_bearing_states_are_derived_and_agree_across_documents`, `test_stranded_execution_bearing_subject_blocks_through_a_listed_edge`, `test_pre_running_fencing_does_not_consume_the_execution_attempt_ceiling`, `test_delivery_cannot_blindly_replay_an_initiated_external_effect`, `test_attempt_matrix_binds_every_nonterminal_state_to_a_subject_state`, plus the three amended guards. The new tests do fail before and pass after.
- My own recomputation, not reusing the committed tests: **zero dangling acceptance IDs** across all four freeze docs (193 defined; every referenced ID resolves; ST-15, ST-16, DL-06 all defined); **23 of 23 MUST-bearing freeze-contract sections present in the §18A coverage index**, none undispositioned; **every non-terminal attempt state (`CREATED`, `STARTING`, `RUNNING`, `CANDIDATE_READY`) has at least one terminal `CLOSED` edge**; **delivery enum ↔ §3C mutually complete** (`PENDING`/`UNKNOWN`/`FAILED` appear as From and To, `PUBLISHED`/`BLOCKED` as To only — correct for terminal states).
- **No self-adoption, no DEC-046/047 sequencing drift.** `DECISIONS.md` is untouched across `9e59860..5eb25f8`. The `CURRENT_TRUTH.md`/`ROADMAP.md` changes are branch-level (earlier commits, not this repair) and explicitly framed as candidate-not-authority: status reads "FREEZE CANDIDATE UNDER ADVERSARIAL REVIEW", and the Phase-0 sequencing amendment is recorded as "a proposal, not current authority… becomes active only if the owner records an explicit DECISIONS.md entry adopting the exact freeze SHA". That is the correct posture.
- **N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03:** all regression guards in the committed module pass, and the traceability ledger carries an explicit disposition row for each, including G-01..G-03. No regression observed.

## 5. Non-blocking observations (not gating the owner decision)

1. `delivery.block` is admissible from `PENDING` regardless of `attempt count`, so a record whose external effect may already have reached the destination can be driven to terminal `BLOCKED` with a policy reason, pre-empting the mandatory §21 reconcile-to-`UNKNOWN`. No duplicate effect can result (`BLOCKED` is terminal and admits no publish), but the ambiguity is discarded and the operator sees a policy reason rather than `REMOTE_EFFECT_UNKNOWN`. Consider requiring `PENDING count >= 1` to pass through `UNKNOWN` before `delivery.block`.
2. §3C never states explicitly that one `delivery.publish` invocation MUST initiate at most one external publication effect. It is unreachable through the matrix, but the adapter is outside the kernel; an explicit MUST would close it by construction rather than by inference.
3. §2's `delivery.publish` summary still says "create/**reuse** a durable PENDING delivery intent", which reads as licensing replay of a `PENDING` record. §3C is authoritative and forbids it; the summary should be aligned.
4. §3A.2's third normative consequence cites §4 for the immutability of a terminal disposition. §4 is about transaction atomicity and says nothing of the kind. The rule does exist — FC §10.3.1 line 279 — so the citation should point there.
5. Carried forward from earlier rounds, still true at `5eb25f8`: §7 has no dedicated reason code for ceiling exhaustion or for delivery epoch/digest refusal; `BLOCKED/ESCALATED → task.plan → PLANNED` carries no ceiling guard, so an exhausted task can re-plan into a `PLANNED` state from which no `attempt.assign` is ever admissible, with no BLOCKED/ESCALATED visibility; the delivery/attempt counters have no declared storage column.

## 6. Reviewer-independence limitation

**Recorded.** This review was produced by Claude Opus 5 — the same model and provider that authored the `5eb25f8` repair commit. The sessions are separate and this round had no access to the implementing session's reasoning, but this is a same-model review, not a cross-provider one. Per FC §9 the limitation is recorded and the independent Director/owner gate remains mandatory.

## 7. OWNER-PENDING (nothing here was assumed, inferred or granted)

- Adoption of any freeze SHA in `DECISIONS.md`, and with it the proposed DEC-046 sequencing amendment permitting Phase-0 repository-only deterministic-kernel work. Not granted; not present in the inbox.
- Any decision to accept the freeze with H-01/H-02 open, or to require the repair first.
- Merge of the candidate branch to any production branch. Not performed, not requested.

## 8. RUNTIME-PENDING

- No orchestrator runtime exists; the freeze set is documentation only and implies no implementation.
- The acceptance cases (ST-*, DL-*, PR-*) are specification-level; none can be executed until a kernel exists.
- Pre-existing and unchanged by this round: Gmail OAuth secret provisioning outstanding; Samsung device verification outstanding.

## 9. State of every checkout and the server

| Checkout | Branch | HEAD | `git status` |
| --- | --- | --- | --- |
| Builder `/opt/crooks-builder` | `claude/builder-environment-repair` | `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` | clean |
| Candidate worktree `/opt/crooks-builder/.worktrees/freeze-repair` | `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` | `5eb25f8fe00a3196cb27d7b2c92b2b5fbf4a5c78` | clean (pre-existing worktree, already at the exact candidate; not created, moved or modified by this round) |
| **Production `/opt/crooks-os/crooks-assistant`** | **`claude/linux-prod-migration-production`** | **`1cf3a0f3361b79f9de208d80f501543c53c244b5`** | **clean — not written to, not switched, not reset, not modified** |
| Bridge `/opt/crooks-ai-bridge` | `crooks-ai-bridge` | — | clean apart from this outbox file |

**Files changed by this round:** exactly one — `bridge/claude-outbox.md`. No `git add`, `git commit` or `git push` was run. No other file in the bridge worktree was touched.

**Service and server state (observed, unchanged):** `crooks-assistant` **active**; `crooks-ai-bridge-watcher` reported inactive (timer/oneshot-driven; this run is its child — not started, stopped or reloaded by me). Listeners: FastAPI on **127.0.0.1:8000 only**; the two `:443` listeners are `tailscaled` on the Tailscale interface. Port 8000 is not publicly exposed. Uptime 1 day 23:20, load 0.84, disk 14G/75G used (19%).

**Safety constraints preserved:** `writes_enabled` false, `CROOKS_WRITES_LOCAL_OWNER` false, FastAPI bound to 127.0.0.1, port 8000 unexposed, proposal/action/verification semantics untouched, no live Shopify/Gmail/ElevenLabs call and no live external mutation, V2 not begun, UI not redesigned, Mac deployment/rollback path preserved, `/root/.claude` writable, no secret value read, printed or committed.

**Errors:** none. One first attempt used a wrong venv path (`/opt/crooks-builder/.venv`, which does not exist); corrected to `/opt/crooks-builder/crooks-assistant/.venv`. Temporary scratch directories under `/tmp` were used for the blob-based test runs and removed afterwards.

## 10. Exact proposed next step

Return `5eb25f8` to the implementer for one further bounded repair commit on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, addressing **H-01 and H-02 only**, plus optionally the four documentation nits in §5.1–§5.4. Concretely, in one commit:

1. Amend the five `ORCHESTRATOR_V1_STATE_API.md` §3 rows (`candidate.reject`, `integration.reject`, `integration.block`, `task.escalate`, `task.fail`) to fence every non-terminal `review_dispatch` and `attempt` for the subject before the subject transition commits, and make `task.block`'s fencing unconditional; add those triggers to §3B's FENCED row and §3A's CANCELLED/FENCED rows.
2. Separate the §3A.2 ceiling discriminator from the §6 process-group cleanup handle, and declare where a pre-`RUNNING` preflight process group's identity is durably recorded.
3. Replace `derived_execution_bearing_states()` with a derivation from the §3 × §3A/§3B *edges*, and add the §3-edge-closure assertion described under H-01.
4. Add acceptance case ST-17 (H-01) and extend ST-16 with the crash-during-`STARTING` arm (H-02); index both in §18A; add G-04/G-05 disposition rows to the traceability ledger.

Then publish the new exact SHA to this bridge for a further fresh independent read-only review. **No merge, no deployment and no owner adoption should occur on `5eb25f8`.**
