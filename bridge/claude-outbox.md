# CLAUDE OUTBOX — Orchestrator V1 freeze candidate `2f1acc0`, fresh independent read-only adversarial review

- **Timestamp (UTC):** 2026-09-20T16:49:23Z
- **Inbox blob SHA processed:** `a06148a9ddb288f445b4e010b1d4f60091757ff0` — consumed as this round's sole instruction set. Recorded here so the same instructions are never executed twice.
- **Round type:** read-only adversarial review. No repair performed, as instructed.

## VERDICT

**CHANGES REQUIRED BEFORE OWNER DECISION**

One material engineering blocker (**J-01**), newly introduced by this repair commit. H-03 and H-04 as
raised are otherwise correctly and thoroughly repaired; J-01 is the unfinished half of H-04's
resource-release requirement, and it currently reproduces the H-04 consequence on one branch of a
genuine ambiguity.

## 1. What was asked

Fresh independent read-only adversarial review of exact candidate
`2f1acc0b7edd233735e419d92cfbade914b0042f` on `crooksldn-pixel/clive`: verify identity against fresh
remote truth, attack the H-03 (one owned process group / write-once handle) and H-04 (kernel-owned
reviewer write-ahead identity) repairs, run a broader adversarial regression search, run the committed
spec test or recompute from exact blobs, mutation-test structural gates using ephemeral scratch only,
and return exactly one of two verdicts. Hard read-only scope everywhere except this outbox.

## 2. Identity verification — all five checks PASS

Resolved from `git ls-remote` against the live remote, not from tracking refs. The Builder's
`remote.origin.fetch` refspec is still the stale single-branch form naming the deleted
`claude/bridge-builder`, so both branches were fetched by explicit full refname. **The refspec was not
repaired** (RUNTIME-PENDING, and out of scope).

| # | Check | Result |
| --- | --- | --- |
| 1 | candidate branch head | `2f1acc0b7edd233735e419d92cfbade914b0042f` — **exact match** |
| 2 | canonical base head | `9e59860a945ec339c69af8709cd0721f0a795327` — **exact match** |
| 3 | `merge-base(candidate, canonical)` | `9e59860a945ec339c69af8709cd0721f0a795327` == canonical — **PASS** |
| 4 | `9fbe4a9..2f1acc0` | exactly **1** commit — "One process group per attempt, and a reviewer the kernel can still find after a crash" (Claude, 2026-09-20 16:33:42 +0000) |
| 5 | repair diff + full freeze set re-read | done; 5 files, +300/−35 |

Repair touches exactly: `ORCHESTRATOR_V1_STATE_API.md` (+48/−23), `ORCHESTRATOR_V1_FREEZE_CONTRACT.md`,
`ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md`, `ORCHESTRATOR_V1_TRACEABILITY.md`,
`tests/test_orchestrator_freeze_spec.py` (+242).

`DECISIONS.md` is byte-identical to canonical (`a6dc313`) — **no DEC-046/DEC-047 amendment**.
`CURRENT_TRUTH.md` and `ROADMAP.md` are byte-identical to `5eb25f8`, where their candidate-not-authority
framing was already verified; re-read confirms the freeze is described as a candidate requiring
independent review and an exact accepted SHA, with DEC-046 still the active sequencing gate. **No
self-adoption.**

## 3. Test execution — actual pytest, not recomputation

The pre-existing worktree `/opt/crooks-builder/.worktrees/freeze-repair` was already checked out at
exactly `2f1acc0` and clean, so no worktree was created, switched or reset.

| Run | Tree | Result |
| --- | --- | --- |
| Committed spec suite at candidate | `2f1acc0` worktree | **51 passed** in 0.76s |
| Candidate gate vs rejected SHA | `9fbe4a9` doc blobs + candidate test module, ephemeral scratch | **14 failed / 37 passed** |

Both figures independently reproduce the implementer's claims. All five blobs in the failing-before
scratch were provenance-proved by `git hash-object` == `git rev-parse <sha>:<path>` before use. The
scratch trees have been deleted; both worktrees ended at 0 status lines.

Notably `test_pre_running_cleanup_handle_and_ceiling_discriminator_are_distinct_facts` — which at
`9fbe4a9` *asserted* the two-group handover and so locked the H-03 defect in — now fails against the old
tree. That defect-locking assertion was correctly removed.

## 4. H-03 — attacked, and found correctly repaired

Every sub-check the inbox named holds:

- **Exactly one owned group for the full lifetime.** SA §3A.3 and FC §11 now agree: "**exactly one** per
  attempt, created once before preflight". The prior direct FC-§11-vs-SA-§3A.3 contradiction (one cgroup
  vs two) is gone.
- **Write-once, committed before the group exists, never replaced on STARTING → RUNNING.** SA §3A (line
  389) carries an explicit prohibition — "MUST NOT update, replace or clear" — rather than silence;
  `CREATED -> STARTING` is declared "the only edge that may write" it.
- **Preflight and model inhabit the same group; surviving preflight descendant stays discoverable.** SA §6
  step 5 proves "the **entire** owned process group is empty"; FC §11 forbids reuse until "**that whole
  group**" is empty and states that "an emptiness proof over any narrower group does not satisfy this
  rule". The vacuous-emptiness path is genuinely closed.
- **`attempt.running_process_group_identity` stays accounting-only.** Explicitly forbidden from being
  promoted into the cleanup role, and §6 is forbidden from reading it. §3A.2 remains its only reader;
  R-02 ceiling semantics are untouched.
- **Stale/recycled handle fails closed.** §3A.3 requires a controller-allocated, attempt/dispatch-bound
  identity (not a bare recyclable PGID) and §6 re-verifies that the resolved group is still this record's
  before signalling; a failed check is never signalled and falls through to `QUARANTINED`/BLOCKED. This
  closes the "PGID reuse defence not explicit" item carried forward from the `9fbe4a9` review. The wording
  is substrate-agnostic ("per-record cgroup path or equivalent kernel-scoped container identity derived
  from the record's own primary key") and is implementable and deterministic on Linux; it introduces no
  second cleanup authority.
- **ST-16** does prove the surviving-preflight-child case: it asserts the handle holds its `STARTING`
  value after `RUNNING`, that the model joined the same group, that §6 finds the surviving child, and that
  "a specification that hands the handle over at `STARTING -> RUNNING` fails this arm".

**Attack that did not land (recorded so it is not re-derived):** the cleanup handle lives on `lease`, which
is one row per `(subject_kind, subject_id, subject_revision)` while §3A.2 permits three attempts per
revision — so I tried to overwrite a quarantined attempt's still-live group identity with a successor
attempt's handle. It fails: SA §3A.2 line 423 plus FC §10.3.1 forbid relaunch "at all until cleanup is
proven", FC §8 blocks reassignment on unprovable cleanup, and SA §3 line 318 requires the blocker resolved
before `BLOCKED -> task.plan -> PLANNED`. The handle cannot be clobbered while it still names a live group.

## 5. H-04 — attacked, correctly repaired **except** for its resource-release half (→ J-01)

Sound: ownership kind is a durable `KERNEL_OWNED|EXTERNAL` attribute of the reviewer principal/session
binding, committed in the same transaction as the `DISPATCHED` row and immutable thereafter, so it exists
before any reviewer process does; NULL on a kernel-owned handle now positively means "no group created";
§6 step 3 branches on principal kind **first**, then re-verifies ownership, then signals; FC §21 step 8
reconciles a crash-before-fork as kernel-owned-with-no-group rather than as external; EXTERNAL retains
fencing-only semantics with the limitation recorded and cannot absorb kernel-owned cleanup duties. ST-17
covers both the kernel-owned crash arm (before and after fork) and the external negative arm.

The one thing that does **not** hold is the repair's own new release rule. See J-01.

## 6. J-01 — MATERIAL ENGINEERING BLOCKER (new in `2f1acc0`)

**A terminal execution record is required to keep holding a global concurrency unit, but every stated
accounting mechanism counts only non-terminal rows, and the record model cannot represent "terminal,
cleanup unproven" for a dispatch at all.**

### Exact locations

| Requires the unit **HELD** at step 7 | Requires / mechanically performs **RELEASE** |
| --- | --- |
| `ORCHESTRATOR_V1_STATE_API.md` §6, line **597** — "resources MUST be released at step 6 **and never at step 7** … cannot have its required-review slot or its freeze-contract §19 reviewer-concurrency unit released" | `ORCHESTRATOR_V1_STATE_API.md` §6, line **597**, same bullet — "A terminal subject MUST NOT continue to occupy a slot, a lease or a concurrency unit." |
| `ORCHESTRATOR_V1_STATE_API.md` §3B, line **493** — slot and §19 unit "**not** released while that orphan may still exist" | `ORCHESTRATOR_V1_STATE_API.md` §3.1, line **366** — "fencing releases resources immediately … the reviewer-concurrency and execution-slot occupancy freed by a fenced record MUST be reusable" |
| `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §21 step 8, line **604** — "still held" | `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §19, line **560** — "The reviewer-concurrency ceiling is enforced against non-terminal `review_dispatch` rows, and the implementation/integration concurrency ceilings against non-terminal `attempt` rows" |
| `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §15, line **449** — slot and unit "stay held" | `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §21 step **11**, line 607 — "fence obsolete … dispatches …, releasing the required-review slots, reviewer-concurrency units and execution slots they occupied" |
| Acceptance `ST-17` kernel-owned arm — slot and §19 unit "**not** released … while a kernel-owned orphan can still exist" | Acceptance `ST-17`, same case — "The freed required-review slots and reviewer-concurrency units are immediately reusable"; `ORCHESTRATOR_V1_STATE_API.md` §1A line **247** — "at most one **non-terminal** dispatch per required-review slot" |

The decisive facts: §6 step 7 makes the dispatch **`FENCED`**, and SA §1A line 118 states "`DISPATCHED` is
the only non-terminal state; `COMPLETED`, `CANCELLED`, `FENCED` and `EXPIRED` are terminal". A step-7
record is therefore terminal, and §19 counts it as zero. Symmetrically, an attempt at step 7 closes
`QUARANTINED`, which is a disposition of terminal `CLOSED`, so §19's implementation/integration ceiling
also counts it as zero.

Worse, the `review_dispatch` state enum (SA §1A line **112**,
`DISPATCHED|COMPLETED|CANCELLED|FENCED|EXPIRED`) has **no** quarantine-equivalent and the record carries no
`cleanup_proven` field. `FENCED` is reached both by the normal proven-clean fence path (§3B, slot "released
for immediate reuse") and by the step-7 orphan path (§3B line 493, slot "not released"). The two are
indistinguishable in the durable store — the same overloading defect as H-04's NULL, relocated from the
process-group field onto the state enum.

### Failure scenario (concrete)

Reviewer-concurrency ceiling = N. A `KERNEL_OWNED` reviewer's group cannot be proven empty on
`candidate.reject`. §6 step 7 fires: dispatch → `FENCED` (terminal), subject → BLOCKED. The live untracked
reviewer process keeps running. The controller now admits reviewer work by §19, counting non-terminal
`review_dispatch` rows: the orphan's row is terminal, so the count is N−1 and a new dispatch **on a
different subject** is admitted. Subject-BLOCKED does not prevent this, because the reviewer-concurrency
ceiling is controller-global, not per-subject. Actual concurrent reviewer processes = N+1, exceeding a
ceiling §19 says MUST NOT be exceeded — and reproducing precisely the H-04 consequence ("a live
kernel-owned reviewer keeps running untracked" while its unit is reused) that this commit set out to
eliminate.

Attempt arm, sharper because V1 ships **one** implementation slot (FC §19): task A's attempt closes
`QUARANTINED` with a live unprovable group. §19 counts non-terminal `attempt` rows → 0 → the single
implementation slot is free → task B is admitted and launches a model. Two live attempt process groups
exist on a one-slot controller, contending for the CPU/memory/process, browser-slot and port resources
§19 exists to bound.

Two conformant kernels cannot agree here: one implements §3.1 line 366 / §19 / §21 step 11 and releases;
the other implements §6 line 597 / §3B line 493 / §21 step 8 and holds. Both cite MUSTs. `ST-17` as written
cannot pass against a conformant implementation of §19.

### Why the gate did not catch it — confirmed false green

The structural gate asserts the **presence of both contradictory strings** and never asks whether they can
both hold: the test module at lines 1006 and 1012 asserts "MUST NOT continue to occupy a slot, a lease or
a concurrency unit" appears in §3.1 *and* §6; line 1312 asserts "at step 6 **and never at step 7**"
appears in §6; line 1331 asserts the slot and unit "stay held". No test binds §19's counting rule at all.

Proved by mutation in ephemeral scratch (all against `2f1acc0`, control green at 51 passed):

| Mutation | Gate |
| --- | --- |
| M1 — delete §6's ownership re-verification clause | **1 failed** (caught) |
| M2 — re-overload NULL in §6 step 3 as externality | **1 failed** (caught) |
| M3 — add a paraphrased two-group handover permission to §3A.3, leaving the prohibition sentence intact | **51 passed** (missed) |
| M4 — §19 amended to release the unit at step 7 explicitly (**unsafe** resolution) | **51 passed** (missed) |
| M5 — §19 amended to count unproven-cleanup rows (**safe** resolution) | **51 passed** (missed) |

M4/M5 are decisive: the gate is green on the ambiguity and on **both** resolutions, including the one
that explicitly reinstates the H-04 failure. M3 additionally shows the H-03 guard is a verbatim blacklist
(`HANDOVER_WORDINGS`, test-module lines 1148–1155) that cannot see a paraphrase, so a contradicting
*addition* passes — which is structurally how J-01 itself survived 51 green tests.

### Smallest bounded repair

1. Give `review_dispatch` a durable way to record unproven cleanup — either a terminal `QUARANTINED`
   state mirroring the attempt, or a `cleanup_proven` boolean — so "fenced, clean" and "fenced, orphan may
   exist" are distinguishable in the store (SA §1A line 112).
2. Amend FC §19 line 560 to define occupancy the way SA §3A.2 defines the ceiling — a pure function of
   committed rows and dispositions: non-terminal rows **plus** terminal rows whose owned group was never
   proven empty (`QUARANTINED` attempts; cleanup-unproven dispatches), released only when reconciliation
   proves emptiness.
3. Add the step-7 exclusion to SA §3.1 line 366, FC §21 step 11, and the "immediately reusable" clause of
   ST-17, so no document still mandates release on the unproven path.

### Exact acceptance / mechanical test

- Extend `ST-17`'s kernel-owned crash arm and `ST-16`/`ST-13`'s quarantine arms: with the relevant ceiling
  at N and one record holding an unprovable group, assert admission of the (N+1)-th unit is **refused**,
  and that the unit becomes admissible only after reconciliation proves the group empty.
- Add a structural test that recomputes FC §19's counting basis and asserts it names the
  unproven-cleanup disposition set, and that neither SA §3.1 nor FC §21 step 11 releases those units —
  i.e. a test that would fail M4 and pass M5. The present gate fails both ways round.

## 7. Broader adversarial regression search — no further blockers

Checked and found sound: §3/§3A/§3B joint state legality and §3.1 per-row disposal; restart/epoch fencing
and `FENCE_STALE` stale-result admission; attempt budget and R-02 ceiling accounting (unchanged by this
commit); delivery §3C arming/idempotency/UNKNOWN reconciliation; journal completeness; zero dangling
acceptance IDs and complete §18A MUST coverage (both gated, green); every non-terminal attempt state has a
terminal `CLOSED` edge; delivery enum ↔ §3C mutual completeness; regressions N-01..N-04, B-01..B-05,
R-01..R-03, F-01..F-03, G-01..G-03, H-01/H-02 — none reintroduced. Attempt/reviewer slot release is the one
area that fails, and that is J-01.

**Open, non-blocking, carried forward** (unchanged, not re-derived): §7 has no dedicated reason code for
ceiling exhaustion or delivery epoch/digest refusal; `BLOCKED/ESCALATED → task.plan → PLANNED` carries no
ceiling guard; the attempt counter has no declared storage column; `QUARANTINED` from `STARTING` still
consumes the ceiling though it never reached `RUNNING` (deliberate, fail-closed). New this round: the
gate's mutation resistance on prose-absence guards (M3) — not a defect in the contract as written, but it
is why J-01 was invisible.

## 8. OWNER-PENDING and RUNTIME-PENDING — separate from the above, none actioned

- **OWNER-PENDING** — exact freeze adoption by SHA; any DEC-046 sequencing amendment. Neither touched;
  `DECISIONS.md` is byte-identical to canonical.
- **RUNTIME-PENDING** — live watcher/builder branch mismatch (unit declares `claude/bridge-builder`; the
  checkout is on `claude/builder-environment-repair` at `295e483`); stale Builder fetch refspec (still the
  single-branch form naming the deleted `claude/bridge-builder` — deliberately **not** repaired, as
  `WATCHER_BUILDER_IDENTITY_REMEDIATION.md` BR-01/BR-04 depend on its current form); inherited business MCP
  connector surface (this session was offered Shopify/Gmail/Drive/Resend/Omnisend/Wix connector tools
  beyond the intended CLI allow-list — **none were invoked**; several also require OAuth this
  non-interactive session cannot perform, and `plugin:marketing:similarweb` failed to connect).

## 9. Reviewer-independence limitation — recorded

The repair commit `2f1acc0` is authored by "Claude" and this review was performed by Claude Opus 5. This
is **same-model, same-provider review**. It is a genuine independence limitation: shared priors can mask a
shared blind spot. Mitigations actually applied — the verdict rests on mechanically reproduced evidence
(hash-verified blobs, real pytest runs, five mutations) rather than on agreement with the repair's
reasoning, and J-01 was found by attacking the repair's own new requirement rather than by re-reading its
narrative. A different-provider review before owner adoption would still be worth having.

## 10. State at end of run

- **Production checkout `/opt/crooks-os/crooks-assistant`:** branch
  `claude/linux-prod-migration-production`, HEAD `1cf3a0f3361b79f9de208d80f501543c53c244b5` (the DEC-048
  ratified SHA), `git status` clean — **not written to, not modified, not switched, not reset**. There is
  no `main` branch on the remote; that is the production branch.
- **Builder `/opt/crooks-builder`:** branch `claude/builder-environment-repair`, HEAD `295e483`, status
  clean (0 lines). Unchanged by this round.
- **Worktree `.worktrees/freeze-repair`:** `2f1acc0`, status clean (0 lines). Pre-existing; used read-only
  for the pytest run. Not created, switched or reset.
- **Files changed by this round:** exactly one — `bridge/claude-outbox.md`. No commit, no push, no merge,
  no deploy. Nothing else in `/opt/crooks-ai-bridge` was touched.
- **Services:** `crooks-assistant.service` active and enabled; `crooks-bridge-watcher.service` active,
  `.timer` inactive. FastAPI listening on `127.0.0.1:8000` only — no public exposure.
- **Safety constraints:** all preserved. `writes_enabled` false, `CROOKS_WRITES_LOCAL_OWNER` false,
  127.0.0.1 binding intact, proposal/action/verification semantics unchanged, no live Shopify/Gmail/
  ElevenLabs call and no external mutation, V2 not begun, UI not redesigned, Mac deploy/rollback path
  untouched, `/root/.claude` writable. No secret value was read, printed or committed.
- **Ephemeral scratch:** `/tmp/rev-h34-before`, `/tmp/rev-h34-mut`, `/tmp/rev-h34-mut-pristine` created and
  **deleted**; zero remain.
- **Errors:** none. Nothing was blocked by the permission layer; no permission was widened.

## 11. Decisions or questions needing review

No owner decision is requested by this round. The freeze is **not** ready for owner adoption: J-01 must be
repaired and independently re-reviewed first. The only judgement call worth flagging to a senior reviewer
is the scoping of J-01 as a single finding — the reviewer-concurrency arm and the implementation-slot arm
share one root cause, one location set and one repair, so they are reported together rather than split to
inflate the count.

## 12. Exact proposed next step

Return `2f1acc0` to the implementer for **one** bounded repair commit on
`chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, addressing J-01 only, in the three parts of §6
above: (1) a durable unproven-cleanup marker for `review_dispatch`; (2) FC §19 re-based to count
unproven-cleanup rows for both the reviewer-concurrency and implementation/integration ceilings; (3) the
step-7 exclusion added to SA §3.1 line 366, FC §21 step 11 and ST-17's "immediately reusable" clause — plus
the two mechanical tests specified, one of which must fail mutation M4 and pass M5. Then a fresh
independent review bound to that exact new SHA, ideally by a different provider.

Do **not** adopt `2f1acc0` and do **not** amend DEC-046/DEC-047 on the strength of this review. No owner
approval is requested or implied by this round, and none was given in the inbox.
