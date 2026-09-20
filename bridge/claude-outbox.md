# CLAUDE OUTBOX

## Fresh independent read-only adversarial review — Orchestrator V1 freeze candidate `c7c3d52`

- **Timestamp (UTC):** 2026-09-20T18:05Z
- **Inbox blob SHA processed:** `7c038f0cd016dbf261b38f43f6c573db358d2fff` (consumed in full and treated as this round's only instructions; recorded so they are never executed twice)
- **Round type:** read-only adversarial review. No candidate/canonical/product file edited, no commit, no push, no merge, no deploy, no adoption.

---

## VERDICT

### `CHANGES REQUIRED BEFORE OWNER DECISION`

**One material engineering blocker: K-01.** It is a defect in the *mechanical freeze gate*, not in the contract prose. The J-01 repair itself is sound — I attacked the new durable occupancy model along every axis the inbox named and could not break it. But the **H-03 structural guard that the inbox specifically asked me to verify is bypassable by ordinary paraphrase**, and the test asserts in its own docstring a property it does not have. Inbox mutation case 7 ("a paraphrased second attempt process-group handover/write path is introduced") leaves the suite fully green.

Six of the seven required mutations are caught. The seventh is not.

---

## Identity verification — all five checks PASS

Resolved from fresh remote truth via `git ls-remote` against `https://github.com/crooksldn-pixel/clive.git`, then fetched by explicit full refname (the known-stale tracking refspec was never trusted and was **not** repaired — it stays RUNTIME-PENDING).

| Check | Required | Observed | Result |
| --- | --- | --- | --- |
| candidate ref | `c7c3d523b7bafe5c73ae4d82275e6f1a297600f0` | `c7c3d523b7bafe5c73ae4d82275e6f1a297600f0` | PASS |
| canonical ref | `9e59860a945ec339c69af8709cd0721f0a795327` | `9e59860a945ec339c69af8709cd0721f0a795327` | PASS |
| merge-base(candidate, canonical) | == canonical | `9e59860a945ec339c69af8709cd0721f0a795327` | PASS |
| `2f1acc0..c7c3d52` | exactly one commit | 1 commit; candidate's parent **is** `2f1acc0b7edd233735e419d92cfbade914b0042f` | PASS |
| workspace contamination | none | review worktree `/opt/crooks-builder/.worktrees/freeze-repair` at `c7c3d52`, `git status` **0 lines** before and after all work | PASS |

Candidate commit: `c7c3d52` — *"A quarantined reviewer that still holds its slot, and the proof that finally lets it go"*.

**Five-file diff, `2f1acc0..c7c3d52`, +499/−51** — matches the claim exactly:

```
 ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md    |  33 +-
 ORCHESTRATOR_V1_FREEZE_CONTRACT.md      |  23 +-
 ORCHESTRATOR_V1_STATE_API.md            |  95 +++--
 ORCHESTRATOR_V1_TRACEABILITY.md         |   3 +-
 tests/test_orchestrator_freeze_spec.py  | 396 ++++++++++++++++++++-
```

`DECISIONS.md` is **byte-identical to canonical** (empty diff vs `9e59860`). No DEC-046/DEC-047 sequencing drift; no self-adoption — both `CURRENT_TRUTH.md` and the acceptance matrix still frame the freeze as a candidate pending explicit owner adoption of a SHA in `DECISIONS.md`.

---

## K-01 — BLOCKER: the H-03 cardinality guard only fires on one verbatim verb

**Class:** false green / mechanical-test quality. **Severity:** material engineering blocker.

**Exact location:** `crooks-assistant/tests/test_orchestrator_freeze_spec.py`
- helper `attempt_rows_committing_the_cleanup_handle()` — **lines 1390–1395**
- test `test_one_owned_group_per_attempt_is_a_declared_count_not_a_missing_phrase()` — **lines 1398–1440**, with the false claim at **line 1406**
- the normative sentence it is supposed to enforce: `ORCHESTRATOR_V1_STATE_API.md` §3A.3, **line 471**

**The defect.** The repair replaced the verbatim `HANDOVER_WORDINGS` blacklist with a "positive cardinality invariant": §3A.3 declares an attempt owns `1` group with write point `CREATED -> STARTING`, and the gate cross-checks that against the §3A rows that actually write the handle. But the detection of "a row that writes the handle" is itself a verbatim phrase match:

```python
# tests/test_orchestrator_freeze_spec.py:1390-1395
return [
    row for row in table_rows_in_numbered_section(STATE_API, "3A")
    if len(row) >= 4 and f"`{CLEANUP_HANDLE}` is committed" in row[3]
]
```

Only the literal string ``` `lease.owned_process_group_handle` is committed ``` counts as a write. Any other verb is invisible, so the derived count stays `1`, matches the declared `1`, and the suite passes. The docstring at line 1406 — *"A second write point fails whatever words introduce it"* — is **false**.

**Concrete failure scenario / consequence.** A future freeze edit reintroduces the exact H-03 defect (blocker at `9fbe4a9`) into the real `STARTING -> RUNNING` row of §3A, while leaving both the §3A.3 prohibition sentence and the declared count of `1` untouched:

> `attempt.running_process_group_identity` is written in this same commit and only here, as the ceiling discriminator alone, and MUST NOT be used as the cleanup handle (§3A.3). **A fresh controller-allocated process group is allocated for the model process and `lease.owned_process_group_handle` is durably rewritten to name that group, superseding the preflight group's recorded identity**

That is an operative two-group handover on a real transition row, in direct contradiction of the prohibition sitting in the same cell. **The gate returns 63 passed.** A surviving preflight descendant is then owned by nobody the database can name, FC §11's emptiness rule passes vacuously over the wrong group, and — now that §3D keys occupancy off that same handle — the attempt's release transition would prove the *wrong* group empty and free the implementation slot with an orphan alive. H-03 and J-01 both re-open, with a green freeze gate.

**Verified bound on the gap** (five variants, pristine candidate docs restored each time, control 63 green before and after):

| Second-write phrasing, prohibition + declared count `1` left in place | Gate |
| --- | --- |
| `…handle` **is durably rewritten to name** that group | **MISSED — 63 passed** |
| `…handle` **is written** to name it | **MISSED — 63 passed** |
| `…handle` **is committed** for that group | CAUGHT — 1 failed |
| paraphrased write **and** declared count raised to `2` | CAUGHT — 1 failed |
| paraphrased write **and** §3A.3 prohibition sentence deleted | CAUGHT — 1 failed |

So the guard catches a handover only if the drafter happens to use the gate's own verb, raises the declared number, or also deletes the prohibition. It does not catch the ordinary case the inbox asked about.

This is **wider than the limitation the implementer disclosed**. Their outbox flagged only that "a handover asserted purely as §3A.3 prose that no edge implements still passes", claiming the invariant catches "an *operative* handover (a second §3A write point or a raised count)". The mutations above are operative second write points on a real §3A edge, and they pass.

**Smallest bounded repair.** Make handle-write detection structural instead of single-verb, in `attempt_rows_committing_the_cleanup_handle()`:

1. Select every §3A row whose precondition cell mentions `CLEANUP_HANDLE` at all.
2. Classify each mention into exactly one of `WRITES` / `PROHIBITS-WRITE` / `READS-ONLY` using a closed marker set — write verbs (`committed`, `written`, `rewritten`, `updated`, `replaced`, `cleared`, `set`, `recorded`, `populated`, `assigned`, `superseded`), negated forms (`MUST NOT update, replace or clear`), read-only forms (`identified from`, `read from`, `named by`, `proven by`, `MUST NOT be used as`).
3. **Fail closed** on any mention matching no marker — an unclassifiable mention is a gate failure, not a pass.
4. Assert `len(WRITES) == int(declared group count)` and that the single `WRITES` row equals the declared write point, exactly as now.

Keep the existing prohibition and blacklist assertions; they then genuinely become the second, independent gate the document already claims they are.

**Exact acceptance / mechanical test.** Add a parametrised gate test that, for each of at least `is written`, `is rewritten`, `is updated to`, `is replaced with`, `is set to`, constructs the `STARTING -> RUNNING` row with a second handle write while leaving the §3A.3 prohibition and the declared count `1` in place, and asserts the invariant **fails**. Variants A and B in the table above are the two that must flip from MISSED to CAUGHT. No freeze-document text needs to change for K-01; §3A.3 line 471 already states the invariant correctly.

---

## J-01 re-review — attacked, not confirmed by narrative. NO DEFECT FOUND

I read the normative tables, the state enum and the transition rows directly rather than the repair narrative or the traceability entry. Every property the inbox listed holds:

| Required property | Where it is actually established | Result |
| --- | --- | --- |
| `QUARANTINED` durable, authority-terminal, distinct from clean `FENCED`, admits no result | SA §1A l.112 (enum + the two facts), l.118; §3B l.506, l.509 (`FENCE_STALE` incl. against a QUARANTINED dispatch) | PASS |
| EXTERNAL reviewers never acquire kernel cleanup/quarantine semantics | SA §1A l.108 (principal kind is the *only* authority), §3A.3 l.487–491, §3B l.506 ("An `EXTERNAL` dispatch never reaches this row"), §3D l.555, §6 step 3 | PASS |
| Occupancy = pure function of committed records, counting cleanup-unproven terminal rows | SA §3D l.547 + occupancy table l.549–553; "Terminality MUST NOT imply release" l.545 | PASS |
| QUARANTINED dispatch holds slot **and** global reviewer unit across restart/epoch/DB restore | SA §3D l.547 ("restart, DB restore and controller-epoch change therefore cannot release"); FC §21 steps 8 and 11 | PASS |
| CLOSED/QUARANTINED attempt with unretired handle holds execution capacity **and** lease | SA §3D l.551–552, §3A rows l.389/l.394; FC §19, FC §21 step 5, FC §10.3.1 l.275 | PASS |
| Same-slot replacement and different-subject admission cannot exceed the ceiling | SA §1A l.120 (uniqueness keyed on occupying rows), §3B l.501 admission precondition, §3D l.566–567 (global), FC §19 l.564 | PASS |
| Only dispatch release is cleanup-proven `QUARANTINED -> FENCED`, committed before release, no result authority restored | SA §3B l.507 ("the only edge out of a terminal dispatch state", "It restores nothing"), §3D l.557 | PASS |
| Attempt release by handle retirement needs emptiness proof, does not touch the R-02 budget, creates no relaunch path | SA §3D l.561, §3A.2 l.438 ("Budget consumption is not resource occupancy"), §3A.3 l.453, FC §10.3.1 l.275 | PASS |
| Clean cancellation releases promptly only after cleanup proof; no capacity leak | SA §6 step 6 + ordering rule l.642; §3.1 l.367; §3D l.555 (EXTERNAL must **not** be held indefinitely) | PASS |
| Stale/recycled process identity fails closed | SA §3A.3 l.481–485 (controller-allocated, not a bare recyclable PGID; ownership re-verified before signalling; unsatisfiable check → quarantine, never a kill and never a release) | PASS |
| §3.1, §3B, §3D, §6, FC §15, §19, §21 agree; no second contradictory accounting rule | full four-document sweep, below | PASS |

**The head-on contradiction that *was* J-01 is gone.** SA §3.1's old "a terminal subject MUST NOT continue to occupy a slot, a lease or a concurrency unit" is replaced at l.367 by the opposite, correct rule: *"**Terminality alone MUST NOT release a resource**, and no document of this freeze set may state that a terminal record never occupies one."* FC §19 no longer counts non-terminal rows; it defers to §3D and is forbidden from restating it differently (l.566).

**Contradictory-rule sweep.** I grepped all four documents for every release/reuse/occupancy assertion (`immediately reusable`, `never occupies`, `releases the slot/unit/lease`, `non-terminal rows only`, …). Every surviving "reusable at once" is explicitly conditioned on the §6 step-6 proven-empty path — SA §3 l.344, §3.1 l.367, §6 l.642, FC §15 l.447, FC §21 step 11. **No** unconditional release statement and **no** second accounting rule survives anywhere in the set.

**Cross-resource and crash cases attacked, all fail closed:**
- *quarantined reviewer + unrelated reviewer* — ceiling is global (§3D l.567; FC §19 l.564 "not available to a different subject either"); N−1 admissible. Holds.
- *quarantined implementation attempt + integration attempt* — separate ceilings, both counted by §3D l.551–552; RS-04 asserts the single-slot case.
- *restart during reconciliation* — FC §21 steps 5/6/8/11; occupancy recomputed from committed rows, so a restart mid-pass changes nothing.
- *crash after emptiness proof, before release commit* — §3D l.557 requires the cleanup-proven representation to commit *before or in the same transaction as* the release, so an uncommitted proof leaves the row occupying; a later pass re-proves. No leak.
- *crash after release commit* — row is `FENCED` / handle retired; occupancy legitimately ended, authority still terminal.
- *late result before / during / after the release transition* — §3B l.507 and l.509: the token stays superseded throughout, `FENCE_STALE` at all three times.
- *NULL-handle quarantine (would be an unreleasable occupancy)* — **unreachable by construction**: §3A l.389 and §3A.3 l.478 both forbid quarantine for a NULL/absent handle, routing it to the proven `FENCED`/`CANCELLED` edge. Every quarantined row therefore has a handle a release transition can name.

---

## H-03 structural guard — contract correct, gate defective

The *documents* are right: §3A.3 l.463–471 carries the cardinality table (`attempt` → 1 group, write point `CREATED -> STARTING`; `KERNEL_OWNED` dispatch → 1; `EXTERNAL` → 0 / none) and l.471 states that any second write point "is a specification error that MUST fail closed, whether or not the prohibition sentence above is also present". FC §11 agrees ("**exactly one** per attempt", l.293/314) and SA §3A.3 agrees with it — checked directly, no one-vs-two-cgroup contradiction remains.

The *enforcement* is what fails — see **K-01**. The invariant is stated correctly and not actually derived.

---

## Mechanical-test quality / false-green search

**Committed suite re-run at the candidate:** `63 passed in 0.93s`. Worktree `git status` 0 lines before and after.

**Failing-before evidence independently reproduced** against exact parent `2f1acc0`, using immutable blobs in a throwaway scratch (`git archive` of the parent docs + the candidate's test module), with provenance proven by `git hash-object` == `git rev-parse <sha>:<path>` for all five files:

```
11 failed, 52 passed in 1.93s
```

This matches the implementer's claim exactly. The 11 failures are the 9 new J-01/H-03 tests plus 2 parametrised arms of `test_no_document_releases_a_resource_on_terminality_alone`.

**Independent inspection of the new test logic** (not just the pass count). The load-bearing checks are genuinely derived, not phrase blacklists:
- `test_freeze_contract_ceilings_count_exactly_the_occupying_rows` takes **set equality** between the state tokens in FC §19's reviewer bullet and the tokens §3D declares as occupying, so a reworded §19 still fails; it also scans every §19 sentence containing "non-terminal" and requires a quarantine/specification-error qualifier.
- `test_the_release_transition_exists_and_requires_proven_emptiness` derives from §3B that there is **exactly one** edge out of a terminal dispatch state and that it is `QUARANTINED -> FENCED`.
- `test_durable_occupancy_counts_cleanup_unproven_terminal_records` reads the §3D table and asserts all three record kinds, the `global` qualifier and every non-terminal state.
- `test_a_cleanup_unproven_dispatch_cannot_be_represented_as_ordinary_fenced` reads the enum from the record schema, not from prose.

Weaker, but paired with derived checks and therefore not themselves false greens: `RELEASE_BY_TERMINALITY` (verbatim absence list) and `assert "FENCED" not in step_seven`.

**The seven mutations the inbox required** — each applied to pristine candidate docs, suite re-run, control green (63) before and after:

| # | Mutation | Gate |
| --- | --- | --- |
| 1 | FC §19 counts non-terminal dispatches only | **CAUGHT** (1 failed) |
| 2 | step-7 unproven cleanup releases occupancy | **CAUGHT** (2 failed) |
| 3 | QUARANTINED dispatch represented as FENCED | **CAUGHT** (1 failed) |
| 4 | per-slot uniqueness ignores quarantine | **CAUGHT** (1 failed) |
| 5 | release transition no longer requires proven emptiness | **CAUGHT** (1 failed) |
| 6 | attempt quarantine no longer occupies capacity | **CAUGHT** (1 failed) |
| 7 | paraphrased second attempt handover/write path | **MISSED — 63 passed** → **K-01** |

Every catch was for a structural/derived reason, not a brittle phrase blacklist. Mutation 7 is the blocker.

---

## Full regression sweep — N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03, G-01..G-03, H-01..H-04

No regression found. Recomputed **independently of the candidate's own helpers**, with my own parsing code:

- **zero dangling acceptance IDs** — 196 IDs defined as matrix rows, 87 referenced across the freeze set, `referenced − defined = ∅`.
- **§18A MUST coverage complete** — 23 MUST-bearing FC sections, 23 indexed, none missing. `SA §3D` is indexed (RS-01, RS-02, RS-03, RS-04, ST-13, ST-17). New rows RS-03/RS-04 are real matrix rows, and FC §15/§19/§21 and SA §1A/§3.1/§3A.2/§3A.3/§3B/§6 all cite them.
- **every non-terminal attempt state has a terminal cleanup/fencing edge** — `CREATED`, `STARTING`, `RUNNING`, `CANDIDATE_READY` all carry a `CLOSED` edge in §3A; none stranded.
- **delivery enum ↔ §3C completeness and crash/idempotency guarantees** — §3C untouched by this commit; publish admissible only from `attempt count = 0`, increment committed before the external effect, restart of a non-zero PENDING → UNKNOWN (FC §21 step 10). G-03 intact.
- **subject/attempt/reviewer/integration joint-state legality** — §3A.1 bindings unchanged; §3.1's `[EXEC-FENCE]` / `[EXEC-ATOMIC-CLOSE]` obligation preserved and *strengthened* (the token now also forbids releasing resources at step 7). H-01 intact.
- **restart/epoch/stale-result fencing** — FC §21 steps 3, 5, 6, 8, 11; `EXECUTION_RECORD_MISSING` derivation unchanged. G-01 intact.
- **attempt-ceiling liveness/safety** — §3A.2 untouched except the added "Budget consumption is not resource occupancy" paragraph; the `running_process_group_identity` discriminator and the total-over-the-enum classification are unchanged. R-02 and G-02 intact.
- **journal completeness, no self-adoption, no DEC-046/047 sequencing drift** — `DECISIONS.md` byte-identical to canonical; adoption still requires an explicit owner SHA there.

**Secret hygiene:** `gitleaks` 8.30.1 over the `2f1acc0..c7c3d52` range — *1 commit scanned, no leaks found*. No secret value appears in this outbox.

---

## Non-blocking observations (NOT blockers; no action required for the owner decision)

1. **SA §3B row `DISPATCHED -> EXPIRED` (l.504) is the one terminal dispatch edge whose precondition cell does not name the cleanup proof.** Its repaired siblings all do: l.503 (`review.cancel`) says "stopped per §6", l.505 (`FENCED`) says "admissible only on the **cleanup-proven** path", l.506 routes the unprovable case to `QUARANTINED`. I could **not** turn this into a defect: §2's `review.cancel` row and §3's `REVIEWING` row were both tightened by this very commit to require proven emptiness or `QUARANTINED`; §6 step 6 lists `EXPIRED` only on the proven-empty branch; §3B l.506 explicitly covers "after cancellation/**expiry**"; and §3D l.555 asserts `EXPIRED` is cleanup-proven. Four independent places force the proof, so a conformant kernel cannot commit `EXPIRED` with an unproven group. Optional hardening at some later edit: add "on the cleanup-proven path (§6 step 6)" to row 504, and extend the gate to require every terminal §3B edge to name its cleanup disposition.
2. **A quarantine whose handle can never be resolved is a permanent occupancy with no declared operator escape.** §3A.3 l.485 makes an unsatisfiable ownership check fail closed to `QUARANTINED`, and §3D's only release needs an authoritative emptiness proof. With one implementation slot this can wedge the controller until a human intervenes. This is the deliberate, correct fail-closed direction (killing an unidentifiable group would be worse) and is the same accepted property carried forward from the G-repair; recorded so it is not rediscovered as new.
3. `test_no_document_releases_a_resource_on_terminality_alone` remains a verbatim-absence list. It is paired with derived checks, so it is not itself a false green, but it should not be relied on alone.

---

## Owner / runtime gates — separate, not engineering defects, NOT remediated

Per the inbox, these remain open and I did nothing about any of them:
- **OWNER-PENDING** — exact freeze adoption by SHA; any DEC-046 sequencing amendment.
- **RUNTIME-PENDING** — live watcher/builder branch mismatch; **stale Builder fetch refspec** (worked around by fetching explicit full refnames, deliberately **not** repaired); inherited business MCP connector surface.

---

## Reviewer-independence limitations (recorded as required)

- I am the same model family as the implementer of `c7c3d52`, running in a fresh session with no access to that session's reasoning. Mitigations: I read the normative tables/enum/rows directly rather than the repair narrative or traceability entry; I recomputed the regression classes with my own parsing code rather than the candidate's helpers; and I reproduced both the failing-before evidence and all seven mutations from immutable blobs.
- The freeze set is a **specification**; there is no orchestrator implementation to execute. Every "PASS" above is a document/gate-level judgement, not a runtime observation. ST-13/ST-16/ST-17/RS-03/RS-04 are acceptance *specifications* whose text I inspected — they have not been run against a kernel, because none exists.
- I did not re-derive H-03/H-04 soundness at `2f1acc0`, nor the classes settled at `5eb25f8`/`9fbe4a9`, beyond checking them for regression at `c7c3d52` as the inbox directed.
- The full offline suite was **not** run: it writes DBs and workspaces into the tree, which would violate the read-only constraint. The freeze-spec suite is the gate relevant to this candidate and it was run in full.

---

## State of the machine at end of run

| Item | Value |
| --- | --- |
| Review worktree | `/opt/crooks-builder/.worktrees/freeze-repair` @ `c7c3d52`, **`git status` 0 lines** |
| Builder checkout | `/opt/crooks-builder`, branch `claude/builder-environment-repair` @ `295e483`, **clean** (untouched this round) |
| Production checkout | `/opt/crooks-os/crooks-assistant`, branch `claude/linux-prod-migration-production` @ `1cf3a0f`, **clean — never edited, switched or reset** |
| Production branch HEAD | `1cf3a0f3361b79f9de208d80f501543c53c244b5` |
| Files changed by me | **none** in any repo. Only `/opt/crooks-ai-bridge/bridge/claude-outbox.md` (this file), left uncommitted for the watcher |
| Services | `crooks-assistant.service` active/running; `crooks-bridge-watcher.service` active/running — neither touched |
| Port 8000 | `127.0.0.1:8000` only — **not publicly exposed**, unchanged |
| Scratch | `/tmp/rev-c7c3d52-parent`, `/tmp/rev-c7c3d52-mut` created for evidence, **both deleted** |
| Errors | none |

**Safety constraints preserved:** `writes_enabled` false; `CROOKS_WRITES_LOCAL_OWNER` false; FastAPI bound to 127.0.0.1; port 8000 not public; proposal/action/verification semantics unchanged; no live Shopify, Gmail or ElevenLabs call and no live external mutation; V2 not begun; UI not redesigned; Mac deployment and rollback path preserved; `/root/.claude` writable; no secret printed or committed. Nothing was merged, deployed or auto-merged. No owner approval was assumed, inferred or recorded.

---

## Decisions / questions needing review

- **Decision taken by me:** I classified K-01 as a *blocker* rather than a non-blocking observation. Rationale: the inbox set the acceptance criterion explicitly — "A conforming gate should fail each unsafe mutation for a structural/derived reason, not only a brittle phrase blacklist" — and listed this exact mutation as case 7. The gate also asserts a property in its own docstring that it does not have, which is worse than an admitted limit because subsequent rounds will rely on it. If the owner prefers to treat gate-only defects as non-blocking when the contract prose is correct, that is an owner call and would flip this verdict to READY; I did not assume it.
- **No question blocks the next step.** The repair is fully specified below.

---

## Exact proposed next step

**One bounded repair round on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, one commit, test-module-only — then one fresh independent read-only review bound to the new SHA.**

1. Fix `attempt_rows_committing_the_cleanup_handle()` (`crooks-assistant/tests/test_orchestrator_freeze_spec.py:1390–1395`) to classify **every** §3A mention of `lease.owned_process_group_handle` as WRITES / PROHIBITS-WRITE / READS-ONLY against a closed marker set, **failing closed on any unclassifiable mention**, then assert `len(WRITES) == declared count` and `WRITES[0] == declared write point`.
2. Correct the docstring at line 1406 so it states the property the code actually enforces.
3. Add the parametrised mutation test described under K-01, covering at least `is written`, `is rewritten`, `is updated to`, `is replaced with`, `is set to`.
4. Re-run and record: freeze-spec suite (expect > 63 passed), all seven inbox mutations (expect **7/7 CAUGHT**, control green), plus variants A and B above, which must flip to CAUGHT. `ruff check` clean; `gitleaks` clean on the range. Failing-before evidence against `c7c3d52` blobs, hash-verified.
5. No freeze-document prose needs to change for K-01. **If the repair round also elects to take non-blocking observation 1** (SA §3B row 504), that is a separate one-clause edit and must carry its own gate assertion and its own failing-before evidence.

Expected outcome of the following review: if 7/7 mutations are caught and nothing else regresses, the engineering contract should reach `ENGINEERING CONTRACT READY — OWNER/RUNTIME GATES REMAIN`. The J-01 durable occupancy model itself needs no further work — I could not break it.

**Do not adopt `c7c3d52`.** The contract it states is sound; the gate that is supposed to keep it sound is not yet.
