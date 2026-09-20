# CLAUDE OUTBOX

**Timestamp:** 2026-09-20T19:17:15Z
**Inbox SHA processed:** `376d63b16297e9827e37d15973506290d2f8c648` (consumed; these instructions are not to be executed again)
**Round type:** fresh independent read-only adversarial review — Orchestrator V1 freeze candidate
**Role:** reviewer only. Nothing was edited, committed, merged, rebased, adopted or deployed.

---

## VERDICT

# CHANGES REQUIRED BEFORE OWNER DECISION

One material blocker, **L-01**, recorded below with reproduction and a bounded repair.

K-01 is **narrowed, not closed**. The repair genuinely fixes the exact defect as it was
*phrased* in the K-01 report (a second write introduced by a different **verb**), and I
reproduced that independently. But the replacement detector still only inspects clauses that
textually repeat the backticked field name, so an operative second write that refers to the
handle by ordinary co-reference — "it", "this field", "the cleanup handle", "the attempt's
owned process group handle" — restores the H-03 two-group handover on the real
`STARTING -> RUNNING` edge with **the entire 75-test committed suite green**. The inbox
directs that a plausible operative write which evades the gate be reported as a material
blocker; four do.

---

## 1. Evidence identity — established fresh, not carried forward

| Fact | Resolved value | Status |
| --- | --- | --- |
| repository | `crooksldn-pixel/clive` (`origin` of the builder checkout) | ✅ |
| freeze branch | `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` | ✅ |
| branch resolves to | `a904a209d57add65f3878b4f7ee3eec19b6c35a9` | ✅ matches inbox exactly |
| candidate parent | `c7c3d523b7bafe5c73ae4d82275e6f1a297600f0` | ✅ matches "rejected parent" |
| pinned historical base | `9e59860a945ec339c69af8709cd0721f0a795327` | ✅ still an ancestor of the candidate |
| `merge-base(a904a20, canonical)` | `9e59860a945ec339c69af8709cd0721f0a795327` | ✅ |
| current canonical `claude/product-memory-foundation` | `3ba4edeb1bdeb317a08932e44557c7e6051fa510` | ✅ matches inbox |

Both refs were fetched by explicit full refname before use. Review artefacts were produced in
a scratch tree from `git archive`/`git show` of committed objects; every blob used was proved
by `git hash-object` == `git rev-parse <sha>:<path>`:

- test module @ `a904a20` = `77ca5595c3fcc8ed87d67f3f952d9db01b5fcb21`
- test module @ `c7c3d52` (the rejected gate, used as the before-side) = `0e68c720fdeeafcaf2bc0389d4148406c172043c`
- `ORCHESTRATOR_V1_STATE_API.md` @ `a904a20` = `189601e8a6b6f468aa87cd87096037014ffb3929`

No previous verdict was carried forward; every claim below was recomputed from committed source.

---

## 2. What the repair actually is

`git diff --name-status c7c3d52 a904a20` → **exactly one file**:

```
M  crooks-assistant/tests/test_orchestrator_freeze_spec.py      +407 / −24
```

Inbox item 10 ✅. The four freeze documents are **byte-identical** between `c7c3d52` and
`a904a20` (`git diff c7c3d52 a904a20 -- crooks-assistant/docs/` is empty). No DECISIONS,
adoption or sequencing change occurred; `DECISIONS.md` @ `a904a20` is blob
`a6dc313173bca86e139ebb5acd221753f1aaaeff`, identical to the pinned base.

**No prior guard was removed or weakened.** Test count 53 → 57; the set difference is four
*additions* only. The 24 deleted lines are the broken detector
(`attempt_rows_committing_the_cleanup_handle`, which matched the verbatim substring
`` `lease.owned_process_group_handle` is committed ``), its two assertions, and the
refactor of `table_rows_under_header` into a text-taking `table_rows_under_header_in` with
the original kept as a wrapper. The false docstring claim *"A second write point fails
whatever words introduce it"* was correctly deleted.

---

## 3. Inbox verification items — findings

| # | Item | Result |
| --- | --- | --- |
| 1 | every §3A transition-row handle mention classified fail-closed | ✅ verified — 8 mentions, all classified, see §3.1 |
| 2 | ordinary paraphrases cannot introduce an operative write while count stays 1 | ❌ **FAILS — blocker L-01** |
| 3 | prohibition not misread as write; a real write beside a prohibition not swallowed | ✅ verified by mutation |
| 4 | unknown/unclassifiable critical wording fails closed | ✅ verified by mutation |
| 5 | sole derived write point is `CREATED -> STARTING` | ✅ verified |
| 6 | seven prior J-01/K-01 mutation cases independently reproduced | ✅ reproduced, all unsafe variants fail |
| 7 | invent further adversarial mutations | ❌ **4 of 10 evade — blocker L-01** |
| 8 | mutation resistance structural, not shared literal strings | ⚠️ **partial** — verb set is now open-ended, but the *mention* test is still one literal identifier |
| 9 | committed suite and static checks green | ✅ 75 passed; ruff clean; gitleaks clean |
| 10 | diff bounded to one test module, no DECISIONS/sequence change | ✅ verified |

### 3.1 What the classifier produces on the pristine candidate

Recomputed from `a904a20`'s committed `ORCHESTRATOR_V1_STATE_API.md` (14 §3A transition rows,
8 handle mentions):

```
[WRITES]      CREATED -> STARTING                        "This is the only edge that may write the cleanup handle: … is committed **before** …"
[PROHIBITS]   STARTING -> RUNNING                        "… MUST NOT update, replace or clear `lease.owned_process_group_handle` …"
[READS_ONLY]  CREATED -> CLOSED / CANCELLED or FENCED    "… proven by … being NULL"
[READS_ONLY]  STARTING -> CLOSED / CANCELLED or FENCED   "… identified from …"
[READS_ONLY]  STARTING -> CLOSED / QUARANTINED           "… named by …"
[READS_ONLY]  RUNNING -> CLOSED / CANCELLED or FENCED    "… identified from the write-once …"
[READS_ONLY]  RUNNING -> CLOSED / QUARANTINED            "… until … is durably retired …"   (deferred-retirement path)
[READS_ONLY]  CANDIDATE_READY -> CLOSED / FENCED         "… cleanup follows §6 against …"

declared cardinality: attempt = (1 group, `CREATED -> STARTING`)   derived writes = [CREATED -> STARTING]
```

Items 1, 3, 4 and 5 hold on the committed text. `attempt_transition_rows()` addressing §3A's
matrix **by its own header** is a real improvement: it correctly excludes §3A.3's durable-fact
table, which also has four columns and names the handle, so the old `len(row) >= 4` filter was
indeed luck.

### 3.2 Item 6 — the before/after evidence reproduces exactly

Rejected gate (`c7c3d52` module) vs repaired gate (`a904a20` module), both against the
*same* committed documents, one operative second write injected into the genuine
`STARTING -> RUNNING` row, prohibition and declared count `1` left intact:

| injected phrasing | rejected gate | repaired gate |
| --- | --- | --- |
| `is written to name` | **63 passed (MISSED)** | 3 failed, 72 passed |
| `is rewritten to name` | **63 passed (MISSED)** | 3 failed, 72 passed |
| `is durably rewritten to name` | **63 passed (MISSED)** | 3 failed, 72 passed |
| `is updated to name` | **63 passed (MISSED)** | 3 failed, 72 passed |
| `is replaced with` | **63 passed (MISSED)** | 3 failed, 72 passed |
| `is set to` | **63 passed (MISSED)** | 3 failed, 72 passed |
| `is recorded as` | **63 passed (MISSED)** | 3 failed, 72 passed |
| `is superseded by the identity of` | **63 passed (MISSED)** | 3 failed, 72 passed |
| `is committed for` | 1 failed, 62 passed | 3 failed, 72 passed |
| *control (pristine)* | 63 passed | **75 passed** |

The implementer's claim is accurate and non-inflated. Prior-invariant regression battery,
run independently against `a904a20` (control green, 75 passed, between every case):

| mutation | result |
| --- | --- |
| J-01 — FC §19 ceilings back to non-terminal rows only | CAUGHT (1 failed) |
| J-01 — SA §6 "released at step 6 **and also at step 7**" | CAUGHT (2 failed) |
| J-01 — "Terminality alone **MAY** release a resource" | CAUGHT (1 failed) |
| J-01 — unproven dispatch row back to `FENCED` | CAUGHT (1 failed) |
| J-01 — §3B per-slot uniqueness back to non-terminal rows | CAUGHT (1 failed) |
| J-01 — §3D dispatch release gated on a grace period, not emptiness | CAUGHT (1 failed) |
| H-03 — verbatim two-group handover restored | CAUGHT (4 failed) |
| H-03 — §3A.3 drops `write-once` | CAUGHT (1 failed) |
| R-02 — SA §3A.2 charges pre-`RUNNING` fencing to the ceiling | CAUGHT (1 failed) |

J-01, H-03's write-once half, H-04's dispatch representation and R-02's budget/occupancy
separation are **not** weakened by this repair. Nothing in the repair could weaken the
contract, because the contract text is byte-identical to the parent.

---

## 4. L-01 — MATERIAL BLOCKER

**An operative second write of the cleanup handle evades the new classifier whenever the
writing clause refers to the handle by co-reference instead of repeating the backticked
field name. The full committed suite stays green on a restored H-03 two-group handover.**

### Mechanism

`classified_handle_mentions()` (test module lines 1583–1596) splits each cell into clauses and
then classifies **only** clauses matching:

```python
HANDLE_MENTION_RE = re.compile(r"`(?:lease\.)?owned_process_group_handle`")   # line 1423
...
for clause in _CLAUSE_BOUNDARY_RE.split(cell):
    if HANDLE_MENTION_RE.search(clause):                                       # line 1594
        mentions.append((row, classify_handle_mention(clause), clause.strip()))
```

A clause without that literal identifier is not classified, not counted, and — critically —
**not flagged as unclassifiable either**. The fail-closed rule at lines 1608–1617 only fires on
mentions the classifier *saw*. `_CLAUSE_BOUNDARY_RE` splits on `;` and on sentence-ending `. `,
which is exactly where ordinary English drops the repeated identifier and switches to a pronoun.

So K-01 moved the gate from *"one literal verb"* to *"a closed verb set, applied only to clauses
containing one literal noun."* Inbox item 8 — "structural rather than dependent on literal
strings shared by the test and the fixture" — is therefore only half satisfied.

### Reproduction (independently run, not taken from the implementer)

Each mutation appends to the genuine `STARTING -> RUNNING` row of the committed
`ORCHESTRATOR_V1_STATE_API.md`, leaving **both** independent gates satisfied — the
`MUST NOT update, replace or clear …` prohibition sentence and
``| `attempt` (TASK or INTEGRATION) | 1 | `CREATED -> STARTING` |`` are untouched — and then
runs the **entire committed 75-test freeze-spec suite**:

| # | appended to the `STARTING -> RUNNING` cell | suite |
| --- | --- | --- |
| M1 | `; a fresh controller-allocated process group is created for the model process and it is set to that group's identity` | **75 passed — MISSED** |
| M2 | `. A fresh controller-allocated process group is created for the model process and the cleanup handle is rewritten to name it` | **75 passed — MISSED** |
| M3 | `. A fresh controller-allocated process group is created for the model process. This field is then updated to name that group` | **75 passed — MISSED** |
| M5 | `. The attempt's owned process group handle is replaced with the identity of a fresh controller-allocated model process group` | **75 passed — MISSED** |
| — | *control, pristine* | 75 passed |

Each of M1/M2/M3/M5 is an **operative** second write plus an explicit second group creation on
the edge H-03 forbids to write — i.e. the H-03 defect fully restored, in prose a careless
freeze edit would plausibly produce, with the derived write count still reported as `1`.
M2 and M5 use verbs that *are* in the new closed marker set (`rewritten`, `replaced`); they
evade purely because the clause does not repeat the backticked identifier.

### Mutations the repair correctly catches (so the finding is narrow, not general)

| mutation | result |
| --- | --- |
| write verb placed *before* a trailing prohibition in the same clause | CAUGHT (cardinality) |
| write appended after `MUST NOT update, replace or clear …` in the same clause | CAUGHT (cardinality) |
| em-dash clause chain (``… — `handle` is updated to name it``) | CAUGHT (cardinality) |
| `until`-deferral with a **non**-retirement verb (`is recorded as`) | CAUGHT (cardinality) |
| unknown verb (`assumes the identity of`) | CAUGHT (fail-closed) |
| deferred **retirement** on `STARTING -> RUNNING` (`Once preflight is proven empty, … is retired …`) | CAUGHT — by `test_every_handle_mention_in_the_attempt_matrix_is_classified` pinning that edge to `{PROHIBITS_WRITE}` |

The negation-scoping work (`_negated_spans`) is sound: I could not construct a case where an
operative verb was swallowed by a prohibition span, nor one where a prohibition was misread as
a write. Inbox item 3 is genuinely satisfied. The defect is exclusively the *mention* predicate.

### Smallest bounded repair

Test-module only; **no freeze-document change is required** — §3A.3 already states the
invariant correctly, so this remains a gate defect, not a contract defect.

**Primary (verified, catches all four):** make the fail-closed rule cover the *cell*, not just
the matched clause. Within any §3A transition-row cell that mentions the handle at all,
every clause carrying an un-negated `WRITE_VERBS` verb must name a backticked
`record.field` identifier as its target. A clause naming the handle → `WRITES`; a clause naming
a different field (e.g. `` `attempt.running_process_group_identity` is written in this same
commit ``) → ignored; a clause naming **no** field → `UNCLASSIFIED` → gate failure.

Prototyped against the committed document: **zero** false positives on the pristine candidate
and **all four** of M1/M2/M3/M5 caught. One pristine clause needs an explicit carve-out —
`CREATED -> CLOSED / CANCELLED or FENCED`: *"the lease is released/retired and the old fencing
token can never admit a result"*, whose subject is `the lease`, not the handle. Recognising the
literal subject `the lease` is sufficient; that carve-out is itself a marker set and should be
closed and asserted.

**Secondary (defence in depth, recommended alongside):** cross-check the **first** column of
§3A.3's cardinality table, which is currently declared and never used. The table declares
``| `attempt` (TASK or INTEGRATION) | 1 | `CREATED -> STARTING` |`` — the gate verifies the
write-point column and ignores the group-count column. Deriving group *creations* from §3A
transition rows and asserting the count equals the declared `1` is structural in a way the
handle-name scan can never be, since a handover must create a second group whatever it calls the
handle. Prototyped: green on pristine (one creation, `CREATED -> STARTING`; `no second group is
created` correctly read as negated) and catches M1/M2/M3. It does **not** catch M5, whose
creation is a past participle — so it is not a substitute for the primary repair, only a
reinforcement.

**Also required:** the docstring at lines 1663–1666 should state the residual limit explicitly.
It currently reads *"a second write point on a real §3A edge fails whatever verb from that marker
set introduces it, and an unrecognised verb fails too"* — accurate as written, but it does not
disclose that both claims are conditional on the clause repeating the backticked identifier.
The previous round's lesson was precisely that an over-broad docstring hid a live hole.

---

## 5. Non-blocking observations (not gating this candidate)

1. **H-04 ownership sentence is unguarded against inversion.** Replacing SA §6's bold lead-in
   *"**Ownership is decided from the principal, never from NULL.**"* with
   *"Ownership is decided from the process-group identity: NULL means external."* leaves the
   suite **75 passed**. The document would then be self-contradictory (§6 step 3, FC §21 step 8
   and the §3A.3 write-ahead rule still say the right thing), so the H-04 *contract* is intact
   and the defect is not exploitable as written. Same family as L-01 — a prose-presence guard
   cannot see a contradicting alteration. Pre-existing; **not** introduced by this repair.
2. **FC §19's summary of §3A.2 is unguarded.** Flipping FC line 278 from
   *"MUST NOT consume the ceiling"* to *"MUST consume the ceiling"* leaves the suite green;
   only the normative SA §3A.2 table is gated. FC §19 explicitly defers to §3A.2 and is
   forbidden from restating it differently, so the contract still resolves correctly, but the
   restatement-drift risk is real. Pre-existing.
3. **The classifier is over-strict in the safe direction.** Innocuous rewording such as *"the
   group recorded in `lease.owned_process_group_handle` is stopped"* would classify as `WRITES`
   (`recorded` is a write verb regardless of grammatical role) and redden the gate. Fail-closed,
   so not a defect — but it is a maintenance cost worth knowing about before the next doc edit.
4. Previously disclosed and still true: the gate scans **§3A transition rows only**. A handover
   asserted purely as §3A.3 prose that no edge implements still passes. Out of scope for the
   inbox's item 1, but it bounds what "K-01 closed" can ever mean.

---

## 6. Canonical-base movement — read-only reconciliation assessment

**Nothing was rebased, merged, edited or adopted.** All of the following is analysis over
committed objects only.

**Ancestry `9e59860` → `3ba4ede`:** a clean fast-forward, six docs-only commits, `9e59860`
still an ancestor — so every pinned merge-base check in the gate remains valid and the
candidate remains valid against its pinned base.

```
a47e461 docs: capture live experience and continuous evaluation direction
c4913ed docs: index continuous evaluation and live experience direction
e378cf9 docs: update current truth for live experience direction
397b32c docs: capture live interaction and evaluation ideas
a7792c0 docs: add live experience and evaluation roadmap
3ba4ede docs: record one-session simultaneous work direction
```

Canonical touched: `CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI.md` (new), `CURRENT_TRUTH.md`,
**`DECISIONS.md`**, `IDEAS.md`, `README.md`, `ROADMAP.md`. *(Note: `DECISIONS.md` has now moved
on canonical — it had not at `a7792c0`. The candidate still carries the pinned-base blob
`a6dc313…`, which is correct: the candidate must not author decisions.)*

**Exact overlap with the freeze candidate:** two files only —
`CURRENT_TRUTH.md` and `ROADMAP.md`.

**Mechanically conflict-free:** yes. `git merge-tree --write-tree a904a20 3ba4ede` exits 0 with
zero conflicts, auto-merging both overlapping files, producing tree
`09682d2c3cf8f7b7c0852a5de8b73aff85794d5e`.

**The merged tree still passes the freeze gate:** I materialised that tree into scratch and ran
the committed freeze-spec suite against it — **75 passed**. So the base movement costs the freeze
nothing mechanically, including `test_no_self_adoption_of_the_freeze` and
`test_current_truth_retains_the_live_unremediated_runtime_conditions`.

**Semantic conflict with the freeze contract: none found.** DEC-050 retires the *user-facing*
Split / Half 1 / Half 2 / Merge / Close abstraction and explicitly preserves internal
branch/concurrency mechanisms. The freeze contract governs the orchestrator kernel (attempts,
leases, dispatches, process groups, ceilings) and has no user-facing Split surface — the only
occurrences of "split" in the freeze documents are "split-brain" (§3 of the acceptance matrix)
and a historical F-01 note, both unrelated. DEC-050 states in terms that it *"does not alter
DEC-046 sequencing, adopt an Orchestrator freeze candidate, authorise production deployment,
enable connectors/secrets/business writes, expand privileges, or weaken action-safety
invariants."* It also affirmatively endorses *"independent/adversarial evaluation, including
mutation of the tests themselves where material"* — which is the method that produced L-01.

**Smallest safe reconciliation path, if and when the freeze receives a clean engineering
verdict** (owner decision; not proposed for action now):

1. Land the L-01 repair on the freeze branch as one further commit (test module only).
2. Obtain one more fresh independent read-only review bound to that new exact SHA.
3. Only then: fast-forward the candidate's pinned base by rebasing the freeze branch onto the
   then-current `claude/product-memory-foundation`. The two overlapping files auto-merge; expect
   no conflicts, but re-verify `merge-tree` at the actual SHAs of the day rather than trusting
   this measurement.
4. Re-run the freeze-spec suite on the rebased tree and require it green (it is green on today's
   merge result).
5. Adoption remains a separate owner act: an explicit `DECISIONS.md` entry naming the exact
   freeze SHA and stating the DEC-046 sequencing amendment. The candidate's own ROADMAP text
   already says *"That split is a proposal, not current authority"* — no self-adoption is
   present and none should be added by reconciliation.

Engineering readiness and owner adoption/reconciliation are kept separate throughout, as
instructed. Base movement is **not** counted as an engineering defect in `a904a20`.

---

## 7. Test results, static checks, state

Run in the pre-existing clean worktree `/opt/crooks-builder/.worktrees/freeze-repair` at the
exact candidate, and in a `/tmp` scratch for every mutation (scratch deleted afterwards):

| check | result |
| --- | --- |
| `pytest tests/test_orchestrator_freeze_spec.py -q -p no:cacheprovider -p no:randomly` | **75 passed** in 0.94s |
| same suite against the hypothetical `a904a20` × `3ba4ede` merge tree | **75 passed** |
| `ruff check app config scripts tests` | **All checks passed!** |
| `gitleaks git --redact --log-opts="c7c3d52..a904a20"` | 1 commit scanned, **no leaks found** |
| full offline suite | **not run** — deliberately: it writes DBs/workspaces into the tree and this is a read-only round |

**Files changed by me: none.** No commit, no push, no branch created, switched or reset.

| location | branch | HEAD | `git status --porcelain` |
| --- | --- | --- | --- |
| `/opt/crooks-builder` (builder base) | `claude/builder-environment-repair` | `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` | 0 lines (clean) |
| `/opt/crooks-builder/.worktrees/freeze-repair` | `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` | `a904a209d57add65f3878b4f7ee3eec19b6c35a9` | 0 lines (clean) |
| `/opt/crooks-os/crooks-assistant` (**production — read only**) | `claude/linux-prod-migration-production` | `1cf3a0f3361b79f9de208d80f501543c53c244b5` | 0 lines (clean) |
| `/opt/crooks-ai-bridge` | `crooks-ai-bridge` | — | only `bridge/claude-outbox.md` (this file) |

Production was inspected with `git -C` only; it was never edited, switched or reset.

**Service and server state (observed, unchanged by this round):**

- `crooks-assistant` service: **active**
- `crooks-ai-bridge-watcher` service: inactive at the moment of sampling (this run was launched by it)
- FastAPI listener: `LISTEN 127.0.0.1:8000` only — **not** bound to `0.0.0.0`, port 8000 not publicly exposed
- `CROOKS_WRITES_ENABLED=false`, `CROOKS_WRITES_LOCAL_OWNER=false` — both unchanged

**Safety constraints preserved:** writes stay disabled; FastAPI stays on loopback; proposal /
action / verification semantics untouched; no live Shopify, Gmail or ElevenLabs call and no live
external mutation was made; V2 not begun; no UI change; Mac deployment and rollback path
untouched; `/root/.claude` still writable; **no secret value is printed or committed** anywhere
in this handoff (only the two flag names and their non-secret boolean values).

---

## 8. Errors and blocks

No errors. Nothing was blocked by my permission layer; no permission was widened and no
workaround was attempted. No approval-requiring action was reached — this round installed
nothing, started nothing, provisioned nothing and performed no live verification.

---

## 9. Reviewer / provider independence limitations — disclosed

- **Same provider and same model family.** This review was produced by Claude (Opus 5), the same
  provider and model family that authored `a904a20`. It is a *fresh session* with no access to
  the implementing session's transcript, and every factual claim here was recomputed from
  committed objects — but it is **not** provider-independent, and correlated blind spots between
  implementer and reviewer cannot be excluded.
- **Partially informed, not blind.** Persistent project memory in this environment carries the
  verdict chain and the K-01 statement. I used it to know *what to attack* and explicitly did not
  carry any prior verdict forward; the classifier behaviour, the before/after table, the J-01
  regression battery and the reconciliation analysis were all re-derived by execution in this
  round. A genuinely blind reviewer might attack differently.
- **Adversarial coverage is finite.** I ran 10 invented mutations plus a 9-case before/after
  matrix plus a 9-case prior-invariant battery. Absence of further evasions is *not* proved;
  L-01's existence shows the previous round's "closed" claim was itself over-broad, and the same
  caution applies to everything I have marked ✅.
- **Static review only.** No kernel implementation exists to execute; conformance of any future
  implementation to this contract is untested by construction.
- The candidate was neither adopted, rebased, merged nor deployed by this round, and this verdict
  confers no authority to do any of those.

---

## 10. Exact proposed next step

**One bounded repair round on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, closing
L-01 in the test module only:**

1. Extend the fail-closed rule from the matched clause to the whole cell: in any §3A
   transition-row cell that mentions `` `lease.owned_process_group_handle` ``, any clause
   carrying an un-negated `WRITE_VERBS` verb and naming **no** backticked `record.field` target
   is `UNCLASSIFIED` → gate failure. Carve out the single pristine exception whose subject is
   `the lease`, and assert that carve-out is a closed set.
2. Add the group-count cross-check as reinforcement: derive process-group *creations* from §3A
   transition rows and assert the count equals §3A.3's declared `1` for
   `` `attempt` (TASK or INTEGRATION) ``, treating `no second group is created` as negated.
3. Add M1/M2/M3/M5 verbatim as parametrised mutation tests alongside the existing
   `SECOND_WRITE_PHRASINGS`, each asserting the gate now fails, with the pristine control kept.
4. Correct the docstring at lines 1663–1666 to state the residual limit precisely.
5. Do **not** touch any freeze document — §3A.3 already states the invariant correctly.
6. One commit, test module only. Then one further fresh independent read-only adversarial review
   bound to the new exact SHA, before any owner decision.

Optionally in the same round, or explicitly deferred as non-blocking: the two prose-inversion
gaps in §5 (H-04 ownership sentence, FC §19's §3A.2 summary).

**Nothing is proposed for adoption, rebase, merge, deployment or any live action.** The owner,
reconciliation and runtime gates all remain closed and untouched, and this verdict binds only
to `a904a209d57add65f3878b4f7ee3eec19b6c35a9`.

**Awaiting:** the owner's or GPT Director's instruction on whether to proceed with the L-01
repair round as specified above.
