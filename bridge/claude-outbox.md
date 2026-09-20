# CLAUDE OUTBOX

**Timestamp:** 2026-09-20 20:47 UTC
**Inbox consumed:** `9c09d52e263fd27b8f6d02a0d5f67c00a93e9266` — read, executed once, recorded here so it is never executed again.
**Round type:** bounded repository-only repair. Orchestrator V1 freeze candidate, blocker **L-01**.
**Result:** repair complete, evidence green, one new candidate SHA published.

---

## 1. What was asked

Perform exactly one bounded test-module-only repair of L-01 on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, whose candidate `a904a20` was rejected with verdict `CHANGES REQUIRED BEFORE OWNER DECISION`.

L-01: the K-01 clause classifier only *examined* clauses that repeated the literal backticked identifier `` `lease.owned_process_group_handle` ``. An operative second write to the cleanup handle expressed through ordinary English co-reference — `it`, `this field`, `the cleanup handle`, `the attempt's owned process group handle` — was therefore never classified at all, so it could not even be reported as unclassifiable. The derived write count stayed at `1`, matched §3A.3's declared `1`, and the full suite stayed green on a restored H-03 two-group handover.

Required: repair structurally and fail closed; inspect the complete relevant cell/clauses rather than only clauses repeating the identifier; preserve WRITES / PROHIBITS_WRITE / READS_ONLY semantics and negation precedence; cover co-reference across sentence and semicolon boundaries; distinguish writes to explicitly different backticked fields; closed carve-outs that are themselves asserted; preserve the derived sole write point `CREATED -> STARTING` and declared cardinality `1`; add defence-in-depth group-creation cardinality if derivable structurally; do not blacklist the review's exact phrases.

---

## 2. Pre-flight state, verified before any edit

Refs resolved fresh from `origin` (`https://github.com/crooksldn-pixel/clive.git`) by explicit full refname before editing:

| Check | Result |
| --- | --- |
| Freeze branch tip | `a904a209d57add65f3878b4f7ee3eec19b6c35a9` — **exactly `a904a20` as the inbox states** |
| Canonical `claude/product-memory-foundation` | `3ba4edeb1bdeb317a08932e44557c7e6051fa510` — matches the inbox's observed canonical |
| Repair worktree | `/opt/crooks-builder/.worktrees/freeze-repair`, on the candidate branch, at `a904a20`, `git status` **0 lines** |
| Unrelated work present? | No — clean worktree, no modified or untracked files |
| Merge-base vs canonical | `9e59860a945ec339c69af8709cd0721f0a795327` — unchanged pinned base, canonical is still a fast-forward from it |
| Builder checkout (`/opt/crooks-builder`) | branch `claude/builder-environment-repair`, HEAD `295e483`, clean — **not** where this round worked, and untouched |

No abort condition applied. No rebase onto moving canonical truth was performed.

---

## 3. What was found

The defect is exactly as the review described, and it is a **gate** defect, not a contract defect. `classified_handle_mentions` iterated a cell's clauses and applied `classify_handle_mention` only when `HANDLE_MENTION_RE` matched that clause. Everything else in the cell was invisible — including the pristine document's own co-reference, which is why the fix had a natural correctness check available.

Two pieces of pristine prose turned out to be co-referential and therefore **not inspected at all** by the rejected gate:

- `STARTING -> CLOSED / QUARANTINED` names the handle in its **trigger** cell and then refers to it as "that handle" in its preconditions cell. Establishment therefore has to carry across cells of a row, not just within one cell.
- `STARTING -> RUNNING` contains a legitimate write to a *different* field (`` `attempt.running_process_group_identity` is written in this same commit ``) that the old classifier never looked at, because that clause says "the cleanup handle" in English rather than backticks.

The freeze contract invariant itself was re-confirmed sound; no freeze document was edited.

---

## 4. What was changed

**One commit, one file** — `crooks-assistant/tests/test_orchestrator_freeze_spec.py`, `+517 / −22`.

### 4.1 Structural repair

The unit of inspection is now the **transition row**, not the matching clause. Once a row names the handle (literal `HANDLE_MENTION_RE` or a self-establishing English alias), every subsequent clause of that row is classified, whether or not it repeats the name. Clauses before the naming point have no antecedent and are left alone, which is what keeps ordinary preconditions prose out of the gate.

Each un-negated `WRITE_VERBS` occurrence is then attributed to a referent by **nearest-antecedent resolution** — left first (covers the passive subject-verb order these documents use), falling back to the right (covers active voice, "the controller rewrites the handle"):

| Referent resolved | Classification |
| --- | --- |
| The handle: backticked field, self-establishing alias (`cleanup handle`, `owned process group handle`), or post-establishment anaphor (`it`, `this field`, `that value`, `a NULL or absent handle`, …) | `WRITES` — counted |
| A different backticked `record.field` | `WRITES_OTHER_FIELD` — not counted (requirement 3) |
| A closed `NON_HANDLE_WRITE_SUBJECTS` carve-out | not counted (requirement 4) |
| **Nothing on either side** | **`UNCLASSIFIED` — gate fails closed** |

`FIELD_MENTION_RE` requires a lower-case initial, which separates field references from state/disposition literals (`` `STARTING` ``, `` `QUARANTINED` ``) without a hand-maintained list of either. Negation precedence, `_negated_spans` scoping, the deferred-retirement read, and the existing marker sets are preserved unchanged; an operative write still outranks a prohibition in the same clause, and `UNCLASSIFIED` outranks every benign class.

The single carve-out is §3A's `the lease is released/retired` on `CREATED -> CLOSED / CANCELLED or FENCED`. It is asserted by `test_every_non_handle_write_carve_out_is_live_and_narrow`: the pattern must match real committed §3A prose, must not match the handle, and must be load-bearing (without it the pristine document fails closed).

### 4.2 Defence in depth (requirement 6)

`attempt_rows_creating_an_owned_process_group` / `assert_declared_group_count_matches_the_matrix` derive §3A.3's **group count** a second time, from §3A's creation prose alone, with **zero** reference to any handle wording: a creation verb whose nearest preceding noun, inside its own comma/colon/semicolon segment, is a process group — with negation scoped to that same segment so `no second group is created`, `no owned process group has been created` and `no group was ever created` are read as denials. Pristine derives exactly one creating row, `CREATED -> STARTING`, equal to the declared write point.

### 4.3 Preserved

Derived sole write point `CREATED -> STARTING` and declared cardinality `1` unchanged. Freeze contract / state API / acceptance / traceability / `DECISIONS.md` untouched (**0 doc files changed**; the state API blob at the new SHA is `189601e`, byte-identical to `a904a20`). No optional unrelated hardening. No test removed or weakened — **additions only**, 46 → 54 test functions, 75 → 98 cases.

---

## 5. Adversarial evidence

**Failing-before is hash-verified against exact `a904a20`.** The rejected gate was extracted from the committed blob and proved identical to it:

```
scratch copy      77ca5595c3fcc8ed87d67f3f952d9db01b5fcb21
git rev-parse a904a20:crooks-assistant/tests/test_orchestrator_freeze_spec.py
                  77ca5595c3fcc8ed87d67f3f952d9db01b5fcb21   <- identical
state API blob    189601e8a6b6f468aa87cd87096037014ffb3929   <- identical at a904a20 and at the new SHA
```

Every mutation is injected into the **real** `STARTING -> RUNNING` row and leaves §3A.3's prohibition sentence and its declared count of `1` exactly as committed — the shape the review demonstrated, verified per-mutation before each run.

### 5.1 Detection matrix

| # | Mutation | Kind | OLD `a904a20` | NEW — handle dimension | NEW — group-count dimension |
| --- | --- | --- | --- | --- | --- |
| L1 | `; … and it is set to that group's identity` (pronoun, semicolon boundary) | unsafe | **MISSED** | CAUGHT (write-count) | CAUGHT |
| L2 | `. … and the cleanup handle is rewritten to name it` (alias, sentence boundary) | unsafe | **MISSED** | CAUGHT (write-count) | CAUGHT |
| L3 | `. … This field is then updated to name that group` (anaphor, own sentence) | unsafe | **MISSED** | CAUGHT (write-count) | CAUGHT |
| L4 | `. The attempt's owned process group handle is replaced with …` (noun-phrase alias) | unsafe | **MISSED** | CAUGHT (write-count) | silent — see §6 |
| I1 | bare pronoun after a semicolon | unsafe | **MISSED** | CAUGHT (write-count) | silent |
| I2 | active voice, verb precedes its object | unsafe | **MISSED** | CAUGHT (write-count) | silent |
| I3 | noun-phrase alias with a trailing qualifier | unsafe | **MISSED** | CAUGHT (write-count) | silent |
| I4 | demonstrative + generic noun, `this value` | unsafe | **MISSED** | CAUGHT (write-count) | silent |
| I5 | em-dash aside, two coordinated verbs (`is cleared and then set to`) | unsafe | **MISSED** | CAUGHT (write-count) | silent |
| I6 | passive with an adverb inside the verb phrase (`is durably populated with`) | unsafe | **MISSED** | CAUGHT (write-count) | silent |
| A1 | pronoun + unknown predicate (`It thereafter designates …`) | must fail closed | **MISSED** | CAUGHT (unclassified) | silent |
| A2 | alias + unknown predicate (`The cleanup handle henceforth tracks …`) | must fail closed | **MISSED** | CAUGHT (unclassified) | silent |
| A3 | literal field + unknown predicate (K-01 regression) | must fail closed | CAUGHT (unclassified) | CAUGHT (unclassified) | silent |
| N1 | write to an explicitly different backticked field | **legitimate** | green | **green** | green |
| N2 | lease retirement, not handle retirement | **legitimate** | green | **green** | green |
| N3 | an unambiguous read of the handle | **legitimate** | green | **green** | green |
| — | **PRISTINE CONTROL, unmutated** | control | **green** | **green** | **green** |

I1–I6 and A1–A2 were invented for this round, not taken from the review; the required four are L1–L4 verbatim from the inbox. The three negative controls exist so that "the gate rejects every write verb near the handle" is excluded as an explanation of the result.

### 5.2 Which dimension detects what

- **Handle dimension** (nearest-antecedent attribution) detects **all 13** unsafe/ambiguous mutants: 10 as a derived second write point, 3 as unclassifiable.
- **Group-count dimension** (disjoint; reads no handle prose) independently detects **L1–L3**. However the handle sentence is reworded, an announced second controller-created group still fails.
- L4 is caught by the handle dimension alone. It names an *already-existing* group rather than asserting §3A creates one, so the cardinality dimension is silent by construction. This is pinned by `test_the_group_cardinality_dimension_has_a_stated_blind_spot` so the division of labour cannot silently drift.

### 5.3 Pristine classification after the repair

8 edges classified:

- `CREATED -> STARTING` → {WRITES, READS_ONLY}
- `STARTING -> RUNNING` → {PROHIBITS_WRITE, **WRITES_OTHER_FIELD**}
- the six remaining edges → {READS_ONLY}

`WRITES_OTHER_FIELD` on `STARTING -> RUNNING` is **new and expected**: it is the legitimate write to `` `attempt.running_process_group_identity` `` in that same cell, which the rejected gate never inspected. `test_every_handle_mention_in_the_attempt_matrix_is_classified` was updated to pin these classes; that is the only existing assertion whose expected value changed, and it changed because the gate now sees more, not because anything was relaxed.

### 5.4 Prior-round regression evidence re-run

All prior K-01 / J-01 / H-03 / H-04 / R-02 mutation and regression tests are present and green — none removed, none weakened. The K-01 nine-phrasing mutation set, the J-01 occupancy and release-transition guards, the H-03 cardinality guard, the H-04 principal-kind guards and the R-02 ceiling guards all pass. Targeted re-run of that subset: **52 passed, 46 deselected**.

---

## 6. Remaining blind spots — disclosed, not fixed

Reported rather than repaired: each fix would exceed the round's hard scope, and none affects the committed document.

1. **Unknown predicate cloaked by a read marker.** A clause carrying a read marker *and* an unrecognised predicate classifies `READS_ONLY` — e.g. "The handle is identified from the lease and thereafter designates the model process group" passes. This is the residue of `WRITE_VERBS` being a closed set. It is strictly better than `a904a20`, where that clause was invisible entirely, but it is not closed. Closing it properly needs a real parser.
2. **Creation derivation is order-sensitive.** The group noun must precede the creation verb, so "placed into a newly created controller-allocated group" is not counted as a creation. The handle dimension still covers it.
3. **Row scope.** A co-referential write in a row that never names the handle in *any* cell is out of scope by construction. The inbox scoped the repair to cells/rows establishing handle context.
4. **Over-strictness, fail-closed direction.** An adverbial interrupting a negation ("MUST NOT, under any circumstances, be updated") breaks negated-span scoping and classifies `WRITES`. This makes the gate **red** on legitimate future prose, never green — safe, but a future freeze edit may trip it.
5. **Carried forward, unchanged:** a handover asserted only as §3A.3 prose that no §3A edge implements still passes. Also unchanged and non-blocking from earlier rounds: inverting SA §6's "Ownership is decided from the principal, never from NULL" leaves the suite green; flipping FC §19's summary `MUST NOT consume the ceiling` is ungated.

---

## 7. Publication

| | |
| --- | --- |
| Parent SHA | `a904a209d57add65f3878b4f7ee3eec19b6c35a9` |
| **New candidate SHA** | **`4f1a915421fc5324638168aa6a16fc51f5a9ee84`** |
| Branch | `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` (existing freeze branch only) |
| Commits in range | exactly **1** |
| **Exact changed-file set** | `crooks-assistant/tests/test_orchestrator_freeze_spec.py` — and nothing else (`+517 / −22`) |
| Doc files changed | **0** |
| Remote readback | `4f1a915421fc5324638168aa6a16fc51f5a9ee84` confirmed on origin |

### Identity re-checks at the new SHA

- Merge-base with canonical `3ba4ede` = `9e59860` — pinned base unchanged.
- `a904a20..HEAD` is exactly one commit.
- `DECISIONS.md` is byte-identical to merge-base `9e59860`, i.e. **untouched by the candidate**. It differs from canonical `3ba4ede` only because canonical itself added DEC-050 after the base — that is canonical moving, not the candidate editing it. No self-adoption.
- `git merge-tree` of `4f1a915` with canonical `3ba4ede` is **conflict-free** (tree `95646a6`). Reconciliation with moved canonical remains out of scope and was not done; flag it at adoption time.

---

## 8. Test, static and secret results

| Gate | Result |
| --- | --- |
| Committed freeze-spec suite | **98 passed** in 1.54 s (was 75 at `a904a20`) |
| Prior-round mutation/regression subset | 52 passed, 46 deselected |
| Full offline suite (`-m "not live" -n 4`) | **2903 passed, 8 skipped**, 1 error in 3 m 08 s |
| — that 1 error | the **known** `-n 4` setup race in `app/capabilities/delta.py` (`os.replace` of `capabilities.tmp`). Re-run alone: `tests/test_experience.py::test_the_golden_scenarios` → **59 passed** in 2 m 33 s. Pre-existing and documented in earlier rounds; not a regression and unrelated to this change. |
| `ruff check app config scripts tests` | **All checks passed** |
| gitleaks — changed file | no leaks found (redacted mode; **no secret value printed or committed**) |
| gitleaks — range `a904a20..4f1a915` | 1 commit scanned, no leaks found |
| Worktree after commit | **clean**, 0 lines |
| Scratch evidence tree | deleted |

---

## 9. Safety constraints — all preserved

Nothing in this round touched runtime, services or configuration. `writes_enabled` stays false; `CROOKS_WRITES_LOCAL_OWNER` stays false; FastAPI stays bound to `127.0.0.1`; port 8000 is not exposed; proposal/action/verification safety semantics are unchanged; **no live Shopify, Gmail or ElevenLabs calls and no live external mutations** were made; V2 is not begun; the UI is not redesigned; the Mac deployment and rollback path are untouched; `/root/.claude` stays writable; **no secret value is printed or committed anywhere in this outbox or the commit**.

No watcher, systemd, builder, MCP/connector, privilege, account or global-Claude change. No merge, no adoption, no sequencing change, no deploy, no auto-merge, no spend, no destructive or outward-facing operation. The production checkout `/opt/crooks-os/crooks-assistant` was **not read, edited, switched or reset**. The builder checkout `/opt/crooks-builder` (branch `claude/builder-environment-repair`, HEAD `295e483`) was left exactly as found. The only push was the candidate freeze branch, as the inbox directed.

### Service and server state

Unchanged by this round. No service was installed, started, stopped or reconfigured; nothing was provisioned; no Tailscale route was activated; no live verification was performed. No owner approval was sought, assumed, inferred or recorded — nothing in this round required it.

---

## 10. Errors, decisions and questions for review

**Errors:** none. No step was blocked by the permission layer.

**Decisions taken, each worth a reviewer's attention:**

1. **Establishment carries across a row's cells, not just within one cell.** Strictly wider than the inbox's literal "within every §3A transition-row cell". Required for correctness: `STARTING -> CLOSED / QUARANTINED` names the handle in its trigger cell and co-refers to it in its preconditions cell, so a per-cell rule leaves a real pristine co-reference uninspected.
2. **Three read markers added** (`is proof of`, `is positive proof`, `means no`) for the pristine absence/evidence predicates that the widened scope newly exposed. These are copular predicates that can commit nothing, and they are consulted **only** when a clause carries no operative write verb, so they cannot mask a write. They are pristine-document phrases, not the review's — but a reviewer should confirm this is not a whitelist creeping in, since it is the one place the repair added phrase-level matching.
3. **`test_every_handle_mention_in_the_attempt_matrix_is_classified` expectations changed** for `CREATED -> STARTING` and `STARTING -> RUNNING`. Please verify this is a strengthening (the gate inspects more) and not a relaxation.
4. **Five blind spots disclosed in §6 rather than fixed**, to respect the hard scope and the instruction not to build a broad heuristic that produces false confidence.

**Questions needing review:** none blocking. The four decisions above are the places where an independent reviewer should push hardest.

---

## 11. Self-certification

**This round does not self-certify.** Any prior verdict — including the `CHANGES REQUIRED` verdict on `a904a20` — is **stale** now that the SHA has changed.

**Exact proposed next step:** exactly **one fresh independent read-only adversarial review bound to the new exact SHA `4f1a915421fc5324638168aa6a16fc51f5a9ee84`**, on branch `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, repository `crooksldn-pixel/clive`. That review should establish evidence identity against `4f1a915` itself, attack the four decisions in §10 and the five disclosed blind spots in §6 first, and must not adopt, merge, sequence or deploy anything. No owner decision is requested until that review returns.

**Inbox SHA processed:** `9c09d52e263fd27b8f6d02a0d5f67c00a93e9266`
