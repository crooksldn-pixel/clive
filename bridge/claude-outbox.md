# CLAUDE OUTBOX

**Round:** Fresh independent adversarial review — Orchestrator V1 freeze candidate `10c81e3`
**Timestamp:** 2026-09-20 11:30 UTC, unattended bridge round
**Inbox blob SHA processed:** `88fa08f0cb6a544af080a17b67dcfc436594c851`
**Reviewer:** headless Claude (`claude-opus-5`) in builder clone `/opt/crooks-builder`
**Mode:** read-only architecture/specification review. No implementation, no repair, no runtime remediation, no commit, no push.

I have consumed `/opt/crooks-ai-bridge/bridge/chatgpt-inbox.md` at the blob SHA above and executed only its instructions. The previous verdicts were treated as stale and were not carried forward.

---

## VERDICT

### `CHANGES REQUIRED BEFORE OWNER DECISION`

Three material engineering blockers, **all newly introduced by the B-01…B-05 repair itself**, all in the B-04 / §1A generalisation. The B-01, B-02, B-03 and B-05 repairs hold up under adversarial testing and I could not break them.

This is not a rejection of the repair's direction. Generalising `attempt`/`lease` over `subject_kind` was the right move and the TASK projection really is semantically unchanged. The defects are that (a) the integration launch path collapsed two phases into one command while keeping both phases' preconditions, producing an empty intersection under the document's own joint-oracle rule, and (b) two newly closed enumerations forgot `delivery`.

All three repairs are bounded and local. None requires re-architecting the substrate.

---

## 1. What was asked

A fresh, independent, read-only adversarial review bound to exact candidate SHA `10c81e3`, trying to prove the contract is *not* ready: identity verification first; full read of the freeze set; re-review of the five repaired load-bearing areas (TASK/INTEGRATION generalisation, reviewer dispatch/fencing, failure taxonomy and retry budget, the freeze meta-gate, integration findings); confirmation that owner and runtime gates remain open; and an adversarial search for anything newly introduced by the repair. Return exactly one of two verdicts. Do not fix findings. Do not remediate runtime conditions.

---

## 2. Identity verification — performed before any substantive reading

Explicit branch fetches were used; the stale Builder fetch refspec is a known live condition and `git fetch --all` is unusable there. I did not repair it and rewrote no Git config.

| Check | Required | Measured | Result |
| --- | --- | --- | --- |
| candidate branch tip (`git ls-remote origin`) | `10c81e31f21f62f4115133232cc672c63f52d078` | `10c81e31f21f62f4115133232cc672c63f52d078` | **exact match** |
| canonical base (`claude/product-memory-foundation`) | `9e59860a945ec339c69af8709cd0721f0a795327` | `9e59860a945ec339c69af8709cd0721f0a795327` | **exact match** |
| `merge-base(candidate, base)` | `9e59860a945…` | `9e59860a945ec339c69af8709cd0721f0a795327` | **equals the base; no divergence** |
| parent of candidate | `2bf240c33bfbf0e66257b82a43013cfb3f5af958` | `2bf240c33bfbf0e66257b82a43013cfb3f5af958` | **exact match, linear** |
| candidate mutated during review? | must not be | re-measured at end: `10c81e3…`, worktree `git status` empty | **unmutated — review valid** |

Diff inspected: `2bf240c..10c81e3` (5 files, +714 / −86) and the whole freeze set `9e59860..10c81e3` (9 files, +2338 / −20, 34 commits).

**Builder checkout inspected before acting, not assumed:** branch `claude/builder-environment-repair`, HEAD `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, `git status --porcelain` **empty**. Unchanged and clean at the end of the round. I did not switch, reset or dirty it. I read the candidate from the pre-existing registered worktree `/opt/crooks-builder/.worktrees/freeze-repair`, verified clean at exactly `10c81e3`, and read committed blobs via `git show` where provenance mattered.

---

## 3. Blockers

### R-01 — `integration.begin` has an empty intersection between the two authoritative tables; integration can never start · **HIGH** · newly introduced by B-04

**Where:** `ORCHESTRATOR_V1_STATE_API.md` §2 (line 285), §3 (line 322), §3A (lines 350–352).

The repair gave integration a real execution record, but did not give it the two-phase launch the task path has. One command, `integration.begin`, is now asked to play both the `attempt.assign` role and the `attempt.start` role — and it kept both roles' preconditions.

- §3 line 322 — precondition of `integration.begin`: *"integrator workspace/base preflight passes as measured … integration `attempt` … and its authoritative `lease` created atomically with the transition"*. Preflight must pass **before** the attempt and lease exist.
- §2 line 285 says the same: the attempt is created *"after the same measured preflight §5B/§11 require"*.
- §3A line 350 — `none → CREATED` is triggered by `integration.begin`.
- §3A line 351 — `CREATED → STARTING` is *"runner preflight begins"*, precondition **"current lease; workspace exists"**. The lease must exist **before** preflight may begin.
- §3A line 352 — `STARTING → RUNNING` is *"integrator process ownership established under `integration.begin`"*, so the same command also drives the post-preflight edge.

§3A's own conflict rule is explicit: *"both tables must permit the same operation; the kernel uses their intersection. Any disagreement is a specification error and MUST fail closed."*

**Unsafe/incorrect consequence:** the intersection for `integration.begin` is **empty** — preflight requires a lease that only `integration.begin` creates, and `integration.begin` requires a preflight that cannot run without that lease. A kernel built strictly to the normative tables MUST fail closed, so integration can never be started at all. `ST-11`, the joint-oracle test, is specified to detect exactly this and return a typed error, so the contract's own acceptance gate fails at Phase 3. This directly violates freeze condition §27.2, *"state/API contract has no undefined authoritative transition or mutation path."*

Two secondary effects of the same collapse:
- `integration.cancel` is legal from `CREATED` (§3 line 328) and unconditionally requires fencing *"the integration attempt's `lease`"*. During preflight no attempt exists under the §2/§3 ordering — this is **B-04's original defect reappearing in the pre-`INTEGRATING` window**.
- Under that ordering the integration workspace must exist on disk to be preflighted, but its reservation is recorded only afterwards, so `WS-08`'s workspace-uniqueness constraint is bypassed for that window. The task path has no such window: `attempt.assign` (§3 line 311) reserves the workspace with **no** preflight precondition, and `attempt.start` (line 312) carries the preflight.

**Smallest bounded repair:** mirror the task split. Remove the preflight precondition from `integration.begin` in §2 and §3 so it only creates the integration `attempt` (`CREATED`), its `lease` and the workspace reservation, transitioning the subject `CREATED → INTEGRATING`; then add a distinct trigger for the attempt's `STARTING → RUNNING` edge carrying the measured §5B/§11 preflight, exactly as `attempt.start` does. A new `integration.start` command is the cleanest form; naming the existing edge and removing the duplicated precondition is the minimum. Either way §3A's preflight rows must stop being reachable only through a command that §3 forbids issuing before preflight.

**Exact acceptance/mechanical test required:** an `IN-*` row asserting the full legal launch path `integration CREATED → integration.begin → INTEGRATING` with attempt `none → CREATED → STARTING → RUNNING`, each edge admitted by **both** tables; plus an explicit case that a deterministic integrator preflight failure closes the attempt `FAILED`/`QUARANTINED` with the integration reaching `BLOCKED` through `integration.block`, never leaving an unreserved workspace or an unfenceable window. `ST-11` must be extended to enumerate integration-state × attempt-state × command, and must be asserted to pass for `integration.begin` rather than merely to reject conflicting edges.

---

### R-02 — the §10.3.1 per-revision attempt ceiling is not a precondition on any transition · **MEDIUM** · newly introduced by B-02

**Where:** `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §10.3.1 vs `ORCHESTRATOR_V1_STATE_API.md` §3 (line 311) and §3A (line 350).

§10.3.1 states, bolded and normative: *"absolute ceiling: at most 3 attempts per task revision in total, counting every attempt whatever its disposition. On exhaustion the task goes to `FAILED` or `ESCALATED`, **never to a further attempt**."*

But neither normative transition table encodes it:
- §3 `PLANNED | attempt.assign | ASSIGNED` lists *"controller RUNNING; capacity; no current lease; dependencies accepted; workspace reservation succeeds"* — **no budget or ceiling precondition**.
- §3A row 1 lists *"task is `PLANNED`, or task is `REJECTED` with bounded-correction budget available"* — the budget is named **only** on the `REJECTED` branch. The absence on the `PLANNED` branch reads as deliberate to a literal implementer.

**Unsafe/incorrect consequence:** §3 declares *"Any transition not listed is forbidden"* and §3A declares the kernel uses the intersection of the two tables. A kernel built to those tables admits a 4th, 5th, … attempt via the `BLOCKED → task.plan → attempt.assign` path that §10.3.1 itself nominates as the controlled way back. Two conformant kernels can therefore disagree about whether a 4th attempt is admissible — precisely the condition §7 was rewritten to eliminate (*"two conformant kernels MUST NOT be able to disagree"*). Mitigating: each extra attempt is operator-gated on *"blocker resolved"*, so it cannot spin automatically, and `PR-10` does assert the ceiling — the gap is between the prose and the tables the kernel is told are authoritative.

Related, same section: §10.3.1's exit *"the task goes to `FAILED` or `ESCALATED`"* is only half-reachable. Bullet 1 puts a non-rejection failure in `BLOCKED`, and §3's `task.fail` is legal only from `BUILDING/REJECTED` — there is no `BLOCKED → FAILED` edge. `task.escalate` is reachable from any nonterminal state, so the contract fails closed here; but bullets 1 and 4 prescribe different destinations for the ceiling-exhausting attempt and the document does not say which wins.

**Smallest bounded repair:** add *"per-revision attempt ceiling not exhausted"* as an explicit precondition to the §3 `PLANNED → ASSIGNED` row and to both branches of §3A row 1; and state in §10.3.1 which edge the ceiling-exhausting attempt takes (`task.fail` from `BUILDING` before the block edge, or `task.escalate` from `BLOCKED`), so the two bullets do not prescribe different destinations.

**Exact acceptance/mechanical test required:** extend `PR-10` — or add `ST-14` — to drive three attempts on one revision through `BLOCKED → task.plan → attempt.assign` and assert the fourth `attempt.assign` is **refused by the transition guard** with a stable typed error, that the counter survives controller restart and DB restore, and that the task reaches the single declared terminal state.

---

### R-03 — `delivery` was left outside two newly closed enumerations it is still required to satisfy · **MEDIUM** · newly introduced by B-01/B-04

**Where:** `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` §7 (line 160); `ORCHESTRATOR_V1_STATE_API.md` §1 `transition_event` (line 224) and §1A (line 240); `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md` `ID-03`.

Both enumerations were widened or closed by this commit, and both omit `delivery` while continuing to bind it.

1. **Fencing clause.** §7 now reads: *"Every heartbeat, candidate admission, integration-result admission, evidence admission, review-result admission, **delivery update** and terminal result MUST present … the current fencing token of the exact execution record it claims to act under — the attempt's lease token for task and integration attempts, the dispatch token for review results. §1A defines those three execution records and no result may be admitted without one."* §1A says *"There are exactly three such units"* and `delivery` is not one of them. The `delivery` record (§1, lines 199–209) carries no controller epoch and no fencing token at all. **The MUST is unsatisfiable for delivery**, and under a fail-closed reading every delivery update must be refused. At the parent this sentence was generic (*"the current task revision, controller epoch and fencing token"*) and had no closed record enumeration, so this is a regression of the rewrite. `ID-03` inherits the error verbatim, asserting coverage is *"enumerated over all three execution records of §1A so no admission path is exempt"* — which is false for the delivery path it lists.

2. **Journal subject kind.** `transition_event` gained a **closed** subject-kind enum `TASK|INTEGRATION|CANDIDATE|REVIEW` (absent at `2bf240c`, which had only `task/revision` plus identifiers). `delivery` has its own state machine `PENDING|UNKNOWN|PUBLISHED|FAILED|BLOCKED`, and FC §18 requires *"Every transition emits a structured append-only event"*. A delivery transition now has **no representable subject kind**. `OB-01` does not catch it, because it enumerates *"every transition in the normative matrices"* and delivery transitions appear in none of §3/§3A/§3B.

**Unsafe/incorrect consequence:** publication state changes — exactly the ambiguous-remote path §9 and §21 step 10 depend on for reconciliation — are either unjournalable or unadmissible. `PB-01`/`PB-07`/`EV-10`/`API-08` all assume a durable, observable delivery trail.

**Smallest bounded repair:** add `DELIVERY` to the `transition_event` subject-kind enum; and in §7 (and correspondingly in `ID-03`) scope the execution-record clause to admissions that *act under* an execution record, stating delivery's own authority basis explicitly — controller epoch plus the delivery idempotency key plus §4's observe-then-persist two-phase rule — rather than asserting it presents a fencing token it does not have.

**Exact acceptance/mechanical test required:** extend `OB-01` to enumerate delivery transitions and assert each emits a complete §18 event; add an `ID-*` or `PB-*` row asserting a delivery update presented under a superseded controller epoch or a conflicting idempotency-key digest is refused, naming the authority basis actually used.

---

## 4. What I could not break — the repaired areas that hold

Reported as evidence, not as approval.

**B-01 reviewer dispatch and fencing — sound.** I ran the ordering races conceptually and could not construct an admission path for a stale verdict. `review.record` (§3 line 316) requires the named dispatch to exist, be `DISPATCHED`, belong to the exact subject/SHA, and present the current revision, epoch and that dispatch's fence, with the presenting principal equal to the bound principal; the Review row and the terminal transition are one transaction. Expiry-vs-verdict, cancel-vs-verdict and two-concurrent-replacements all serialise on the DB transaction, and the loser is `FENCE_STALE`. Slot uniqueness over non-terminal rows genuinely fences a replaced reviewer with an unchanged candidate SHA — §3B line 374 fences **before** the replacement row is created, which is the ordering that makes the constraint hold. Stale, foreign and unknown dispatches are all refused (`RV-14`), and `candidate.accept` counts only verdicts admitted *"under a then-live dispatch for a distinct required-review slot"*, so repeated dispatches on one slot cannot inflate the required-review count.

**Externally hosted reviewers are safely fenced.** Where the kernel does not own the process, `process-group identity` is NULL and cancellation relies on fencing alone. Admission identity alone is sufficient for *safety*: a terminal dispatch can never regain authority, so no verdict is admissible regardless of whether the external process is still running. There is a **liveness** ambiguity worth clarifying but not a blocker: §1 says fencing alone suffices for external principals with the limitation recorded, while §3B's last row and §8 say an unprovable reviewer process blocks the subject. Read literally, an external reviewer can never be *proven* stopped, so every external cancellation would force `BLOCKED` and `RV-12`'s replacement branch would be unreachable for the reviewer class the contract most expects. This fails **closed**, so per the inbox's instruction I am not counting it as an engineering defect — but §3B's row should say it applies only where the kernel owns a process group.

**SQLite representability — all constraints are expressible.** Slot uniqueness restricted to non-terminal rows is a partial unique index (`WHERE state = 'DISPATCHED'`), supported since SQLite 3.8.0. The lease key, `review.review_dispatch_id UNIQUE`, the candidate composite unique and the delivery idempotency key are ordinary unique indexes. The §19 ceilings are counts over durable rows, not constraints. I found nothing the contract describes that SQLite cannot represent.

**B-02 failure taxonomy — total, and total against actual usage.** I extracted the §7 table independently (29 codes), confirmed no duplicates and no class outside the normative four, and — going beyond `PR-09` — scanned all four freeze-set documents for every `ALL_CAPS_UNDERSCORE` token of reason-code shape and diffed against the table. **Zero reason codes are used anywhere in the freeze set that the table does not map.** The only unmatched tokens were filenames and the two risk classes `DOCUMENTARY_NONNORMATIVE` / `SECURITY_CRITICAL`. `PROCESS_TIMEOUT`/`PROCESS_STALLED`/`PROCESS_ORPHANED` are BLOCKED; `FENCE_STALE` is `REJECTED_FAILED`; the unmapped default is BLOCKED and persistent across restart.

**B-03 meta-gate — genuinely sound, and I verified it independently rather than trusting it.** I wrote my own parser, with different attribution rules from the candidate's, and recomputed the MUST-bearing section set from both normative documents. **It matches §18A exactly** — FC §1, §3, §4, §5.3, §6, §7, §8, §9, §10.1, §10.3.1, §11, §12, §13, §14.5, §16, §18, §19, §20, §21, §22, §22A, §23, §27 and SA §1A, §3A, §4, §5, §5A, §5B, §7, §8. No section is missing, none is indexed spuriously. The only MUST outside a numbered section is the RFC-2119 keyword definition in the freeze contract's H1 preamble, which states no requirement. I also scanned **twelve** product-memory documents — wider than the candidate's own `FREEZE_SET` tuple, including `CURRENT_TRUTH.md`, `ROADMAP.md`, `DECISIONS.md` and `WATCHER_BUILDER_IDENTITY_REMEDIATION.md` — for dangling acceptance IDs against the 179 defined matrix rows: **zero dangling references anywhere.** CG-05 now cites a real `EN-01..EN-04` and both citing documents agree on the range.

**B-05 integration findings — representable and authoritative.** `finding` carries subject kind, subject ID, exact subject SHA and a kernel-computed `blocking` flag a model cannot set or clear; findings are queryable by `(subject kind, subject ID)`; `integration.verify` (§3 line 325) refuses while any blocking finding for **its own** subject is `OPEN`/`BLOCKED`, and a correction under `parent_integration_id` must disposition every unresolved inherited finding with a recorded reason before reaching `VERIFIED`. Correction lineage does not drop blockers.

**No self-adoption.** `DECISIONS.md` is byte-identical across the entire freeze set `9e59860..10c81e3` — not merely across the repair commit. DEC-046 and DEC-047 are untouched, and `CURRENT_TRUTH.md` records CG-01…CG-06 as *"addressed by the candidate … they remain open in canonical truth until adoption"*, with DEC-046 still the active sequencing gate. The candidate cannot promote itself.

---

## 5. Test results

Exact commands and results. I distinguish the new structural checks from the broader suite, which I did **not** run — this review is read-only and the doc-only branch's suite baseline is unrelated to these document invariants.

**The candidate's own mechanical spec test, at `10c81e3`:**
```
/opt/crooks-builder/crooks-assistant/.venv/bin/python -m pytest \
  tests/test_orchestrator_freeze_spec.py -q -p no:cacheprovider -p no:randomly
  ->  22 passed in 0.45s
```

**Independent reproduction of the claimed failing-before evidence.** I extracted the parent's documents to a scratch tree with `git archive 2bf240c crooks-assistant/docs/product-memory`, repointed the test module's `DOCS` path, and ran it without touching the repository:
```
pytest <scratch>/test_freeze_at_parent.py -q --rootdir=<scratch> -p no:cacheprovider -p no:randomly
  ->  14 failed, 8 passed in 0.48s
```
**The commit message's claim of "fourteen of its twenty-two checks fail against `2bf240c`" is exactly correct.** The failures name the phantom `EN` family, the unmapped taxonomy, the missing coverage index and the three missing execution-substrate repairs. The test has real discriminating power; it is not a tautology. Scratch tree deleted afterwards.

**Independent recomputation (my parser, not the candidate's):** MUST-bearing section set matches §18A exactly, in both directions; 179 matrix rows defined; 0 dangling test IDs across 12 documents; 29 reason codes, 0 duplicates, 0 classes outside the normative four, 0 codes used-but-unmapped.

**One hardening note on the gate itself (not a blocker).** `test_no_must_hides_in_an_unnumbered_subsection` exempts the H1 preamble entirely, and `must_bearing_sections` attributes nothing to it — so a MUST added to either document's preamble would evade both halves of the gate. Correct today, since the only preamble MUST is the RFC-2119 definition. Also, `test_coverage_index_entries_name_real_sections_and_real_tests` and `test_static_dispositions_are_honest_about_being_static` pass **vacuously** on an empty index (they did at `2bf240c`); only `test_coverage_index_dispositions_every_must_bearing_section` asserts non-emptiness, so that one test is load-bearing for three. Worth tightening when R-01…R-03 are repaired.

---

## 6. OWNER-PENDING — not engineering defects

The contract correctly fails closed on each. No document treats any of them as closed.

- **Owner adoption of the exact freeze SHA in `DECISIONS.md`.** Required by FC §27 and matrix §18. `DECISIONS.md` is untouched by the entire freeze set; `AU-01` and `ID-06` test the anti-self-adoption half.
- **Any DEC-046 sequencing amendment.** FC §27 requires it be stated explicitly in the owner decision, not inferred from the spec. `CURRENT_TRUTH.md` states the candidate's Phase-0 proposal *"is not active until the owner explicitly adopts it."*
- **New permissions, secrets, connector grants, external spend, public exposure, deployment.** FC §25. None requested by this round.

## 7. RUNTIME-PENDING — measured read-only, not remediated

All three remain live. I measured them and changed nothing.

| Condition | Measured now | Status |
| --- | --- | --- |
| watcher/builder branch mismatch | unit declares `CROOKS_BRIDGE_BUILDER_BRANCH=claude/bridge-builder`; actual checkout is `claude/builder-environment-repair` @ `295e483…`, clean | **LIVE** |
| stale Builder fetch refspec | `remote.origin.fetch` = `+refs/heads/claude/bridge-builder:…`; `git ls-remote origin refs/heads/claude/bridge-builder` returns **nothing** — the ref is still absent on origin, so `git fetch --all` still fails | **LIVE** |
| inherited business MCP connector surface | **directly observed in this very session** — Shopify, Gmail, Google Drive, Omnisend and Resend tool surfaces were present in my own unattended runtime | **LIVE** |

`WATCHER_BUILDER_IDENTITY_REMEDIATION.md` remains correctly scoped as a **plan**: status `REVIEW CANDIDATE — plan only; no runtime mutation authorised by this document`, with §6 barring any Phase 1 model worker until the live mismatch is corrected and independently verified, and rehearsal evidence (`BR-01`…`BR-04`) required before the plan may be cited as executable. FC §27.5 and matrix §18 both keep live closure mandatory for Phase 1 while exempting repository-only Phase 0. **The separation is correctly maintained — no document treats a described remediation as an executed one.**

---

## 8. Reviewer-independence limitation — recorded explicitly

**This review uses the same model family and provider as the repair worker.** The repair at `10c81e3` was produced by headless `claude-opus-5`; this review was produced by headless `claude-opus-5`. Per FC §15 and §9 of the state API, model/vendor diversity is a `SHOULD`, and where an equal-or-stronger alternative is unavailable a separate high-quality session may review **only with the limitation recorded and the GPT Director gate retained**. This is that record, and the GPT Director gate remains mandatory.

Independence that *is* satisfied: a fresh session and principal with no access to the repair session's context or hidden reasoning; a read-only workspace and channel with no write authority over the candidate; and an immutable SHA-bound subject, re-measured as unmutated at the end of the round. I did not review my own work — I did not produce `10c81e3`. `RV-10` describes exactly this case and it is not being represented as stronger diversity than it is.

---

## 9. Safety and state — nothing mutated

No file in any repository was created, edited or deleted. No commit, push, merge, branch switch, reset, clean or stash. No install, restart, deploy, systemd/watcher/runtime change, Git-config rewrite, account or global Claude settings change, MCP/connector grant change, new secret read, business write or runtime remediation. No finding was fixed. No secret value is printed anywhere in this outbox.

| Item | State |
| --- | --- |
| Production checkout `/opt/crooks-os/crooks-assistant` | **not touched, not switched, not reset** — read-only measurement only: branch `claude/linux-prod-migration-production`, HEAD `1cf3a0f3361b79f9de208d80f501543c53c244b5`, `git status --porcelain` **empty** |
| Production branch HEAD | `1cf3a0f3361b79f9de208d80f501543c53c244b5` (DEC-048 ratified) |
| Builder `/opt/crooks-builder` | branch `claude/builder-environment-repair`, HEAD `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, `git status` **empty** |
| Candidate worktree `.worktrees/freeze-repair` | `10c81e3…`, `git status` **empty** — unmutated |
| Bridge worktree `/opt/crooks-ai-bridge` | on `crooks-ai-bridge`; **only** `bridge/claude-outbox.md` written, per the publication contract; nothing staged, committed or pushed by me |
| Files changed in any repo | **none** |
| `crooks-assistant.service` | `active` |
| `crooks-bridge-watcher.service` | `active` |
| FastAPI binding | `LISTEN 127.0.0.1:8000` only — **not publicly exposed**, unchanged |
| `writes_enabled` / `CROOKS_WRITES_LOCAL_OWNER` | unchanged (`false`); not read, not altered |
| Live Shopify / Gmail / ElevenLabs calls | **none**; no external mutation of any kind |
| V2 / UI redesign / Mac deploy & rollback path | not begun / not touched / preserved |
| `/root/.claude` | writable, unchanged |
| Errors encountered | none |

Scratch artefacts: one temporary tree under `/tmp` for the failing-before reproduction, deleted at the end of the round. Nothing was written into any repository.

---

## 10. Decisions and questions needing review

1. **R-01 is the one that matters.** The other two are enumeration omissions with obvious fixes. R-01 means a core V1 command has no admissible execution under the contract's own conflict rule, and it is the second time the integration launch path has produced this class of defect. I recommend the repair explicitly mirror the task path's two-phase shape rather than patching preconditions, so the symmetry §1A claims — *"the same workspace, epoch, fencing-token, process-group and disposition machinery"* — actually extends to the launch sequence and not only to the steady state.
2. **I did not fix anything**, per the inbox's read-only scope. All three findings are stated with an exact location, consequence, bounded repair and required acceptance test so a repair round can act without re-deriving them.
3. **No verdict is claimed on the repair of these findings**, and I should not review my own review. The next repair must be followed by a further independent adversarial round bound to the new exact SHA.
4. Non-blocking items recorded for that round, not counted against the verdict: the external-reviewer liveness ambiguity in §3B/§8 (section 4 above); the preamble blind spot and the three vacuously-passing gate tests (section 5 above).

---

## 11. Exact proposed next step

**One bounded, repository-only repair round on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, starting from exactly `10c81e31f21f62f4115133232cc672c63f52d078`, fixing R-01, R-02 and R-03 and nothing else.**

Scope, precisely:

1. **R-01** — split the integration launch into a creation phase and a preflight/ownership phase, mirroring `attempt.assign`/`attempt.start`; update `ORCHESTRATOR_V1_STATE_API.md` §2, §3 and §3A so both tables permit the same edges; add the `IN-*` acceptance rows named in section 3 above and extend `ST-11` to assert `integration.begin` **passes** the joint oracle rather than only that conflicts are rejected.
2. **R-02** — add the per-revision attempt ceiling as an explicit precondition to §3's `PLANNED → ASSIGNED` row and both branches of §3A row 1; state which terminal edge the ceiling-exhausting attempt takes; extend `PR-10` or add `ST-14` to prove the fourth `attempt.assign` is refused by the guard and that the counter survives restart and DB restore.
3. **R-03** — add `DELIVERY` to the `transition_event` subject-kind enum; rescope the §7 fencing clause and `ID-03` so delivery's authority basis is stated rather than misattributed to the three execution records; extend `OB-01` to enumerate delivery transitions.
4. Extend `tests/test_orchestrator_freeze_spec.py` with structural checks for all three, and **prove they fail against `10c81e3`** before proving they pass against the new candidate — the same failing-before discipline the current round used, which I independently reproduced and which worked.
5. Preserve every validated N-01…N-04 and B-01…B-05 repair. Do not touch `DECISIONS.md`. Do not remediate any runtime condition. Do not widen the §18A index by deleting MUSTs.
6. Publish to the same candidate branch, report the exact new SHA, and **do not self-certify** — then dispatch a further independent adversarial review bound to that exact SHA.

**Blocked on owner/runtime, unchanged by this round:** owner adoption of a freeze SHA in `DECISIONS.md`; any DEC-046 sequencing amendment; live closure of the watcher/builder identity mismatch, the stale fetch refspec and the inherited connector surface before any Phase 1 model worker or write-capable bridge round. **I am not asking for approval of anything in this round** — it changed nothing and requests nothing.

**Inbox SHA processed:** `88fa08f0cb6a544af080a17b67dcfc436594c851`
