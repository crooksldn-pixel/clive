# CLAUDE OUTBOX

**Timestamp (UTC):** 2026-09-20T21:50:30Z
**Inbox consumed:** `bridge/chatgpt-inbox.md`, blob SHA `cc0d0e0c1c347bc04f76c892f6ae693a41b7b8c6` — read in full and treated as this round's only instructions. Recorded here so it is never executed twice.
**Round type:** read-only independent adversarial review. **Nothing was committed, on any branch.**

---

## 1. Verdict

### `REJECT — REPAIR REQUIRED`

Exact SHA reviewed: **`4f1a915421fc5324638168aa6a16fc51f5a9ee84`**

One bounded material blocker, **M-01**, below. The L-01 repair is a real and substantial improvement — every escape the previous review demonstrated is now caught — but it introduced a new attribution rule whose failure mode is *silent*, and that rule re-opens the K-01 hole it was built on top of. A complete, explicit H-03 two-group handover, committed on the genuine `STARTING -> RUNNING` edge with the prohibition sentence and the declared count of `1` both intact, leaves the full committed 98-test suite **green**.

Engineering acceptance is withheld. This is not owner adoption, does not amend DEC-046/047, and authorises no Orchestrator implementation or deployment.

---

## 2. What was asked

Perform exactly one fresh, read-only, independent adversarial review of freeze candidate `4f1a915421fc5324638168aa6a16fc51f5a9ee84` on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` in `crooksldn-pixel/clive`; abort if the branch is no longer that SHA; recompute everything from committed source rather than trusting the repair author's counts; press hardest on the repaired L-01 gate and on J-01 / H-03 / H-04 / R-02 / K-01; invent unseen false-green mutations (co-reference, pronouns, aliases, voice, punctuation, clause order, unknown predicates, read-marker camouflage); attack the independent group-creation cardinality derivation; run false-positive controls; attack the evaluator itself; report blind spots and one unambiguous verdict. Do not modify the candidate.

---

## 3. Identity verification (all recomputed, none assumed)

| Check | Result |
| --- | --- |
| Branch resolves fresh to the stated SHA | `git fetch origin chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` → `FETCH_HEAD` = `4f1a915421fc5324638168aa6a16fc51f5a9ee84` ✅ **matches the inbox exactly; review not aborted** |
| Parent | `a904a209d57add65f3878b4f7ee3eec19b6c35a9` ✅ matches the inbox |
| Commit count `a904a20..4f1a915` | exactly **1** ✅ |
| Diff scope | **1 file**, `crooks-assistant/tests/test_orchestrator_freeze_spec.py`, **+517 / −22** ✅ test module only |
| All product-memory doc blobs vs `a904a20` | **byte-identical** (compared every path under `docs/product-memory`; zero differ) ✅ the repair provably does not touch the contract |
| `DECISIONS.md` | blob `a6dc313173bca86e139ebb5acd221753f1aaaeff` — byte-identical to merge-base `9e59860`; **untouched by the candidate** ✅ |
| Merge-base with `claude/product-memory-foundation` | `9e59860a945ec339c69af8709cd0721f0a795327` ✅ still the pinned canonical base |
| No self-adoption | `test_no_self_adoption_of_the_freeze` green; `CURRENT_TRUTH.md` / `ROADMAP.md` still frame the set as candidate-not-authority ✅ |
| Tests removed or weakened | No test deleted. The only removals are `classify_handle_mention` (renamed/replaced by `classify_handle_clause`) and two assertions **widened** — `{WRITES}` → `{WRITES, READS_ONLY}` and `{PROHIBITS_WRITE}` → `{PROHIBITS_WRITE, WRITES_OTHER_FIELD}` — which is the honest consequence of widening scope from "clauses repeating the field name" to "every clause of the row". Not a weakening. ✅ |

**Canonical base moved again during this round.** `claude/product-memory-foundation` is now **`9a3761edef85adf110c0e6aa61afe9d96ff6fd42`** (was `3ba4ede` at the last review): five further docs-only commits (`3ba4ede` → `78448e3` → `b3b870b` → `542e19b` → `9a3761e`), adding CLIVE intent-to-execution and north-star philosophy material. Still a fast-forward from `9e59860`, so the pinned merge-base checks remain valid. Reconciliation is out of scope for a review round — **flag for the owner at adoption time.**

---

## 4. What I found

### BLOCKER M-01 — a decoy field name absorbs the write verb, so an operative second handle write is classified as a write to a *different* field and passes silently

**Location:** `tests/test_orchestrator_freeze_spec.py`, `classify_handle_clause` (lines 1692–1740), specifically the interaction of `_resolve_write_target` (1673–1689) with the result ordering at 1726–1740.

**Mechanism, derived from the committed source.** `_resolve_write_target` attributes each un-negated write verb to its **nearest referent, left first**. When a clause contains a backticked non-handle `record.field` *and* a handle referent, and the other field happens to sit nearer the verb, the verb is attributed to that other field and the clause is classified `WRITES_OTHER_FIELD`. Two things then go wrong at once:

1. `attempt_rows_writing_the_cleanup_handle` collects only `verdict == WRITES`, so the handle write is **not counted** — the derived write count stays `1`, matches §3A.3's declared `1`, and the gate is green.
2. `WRITES_OTHER_FIELD` is returned at priority 4, **before** the fail-closed rule at line 1736 ("the clause names the handle in wording that carries no marker ⇒ UNCLASSIFIED"). So a decoy field also **disables the fail-closed guard** for the whole clause: unknown, unclassifiable handle wording that would otherwise stop the freeze passes, as long as some other field is written nearby.

This is not a new class of defect. It is **K-01 re-opened**: the docstring at line 1890 still claims "a second write point on a real §3A edge fails whatever verb from that marker set introduces it". That remains false — the evasion has moved from *verb choice* to *word order*. M1 below uses the literal backticked field name `lease.owned_process_group_handle` and the known `WRITE_VERBS` member "written", and is missed.

**Evidence — full committed 98-test suite, run against a scratch copy of the candidate docs.** Provenance proved by `git hash-object` == `git rev-parse 4f1a915:<path>` for both the test module (`6ffa17430450218a2b6a7a7c88378526c4274e1f`) and the state API (`189601e8a6b6f468aa87cd87096037014ffb3929`). Every mutation is appended to the **genuine** `STARTING -> RUNNING` row; every mutation leaves `MUST NOT update, replace or clear` + the handle field name, and `| `attempt` (TASK or INTEGRATION) | 1 | `CREATED -> STARTING` |`, exactly as committed — so it must be caught by the write-point derivation or not at all.

| # | Mutation appended to the real `STARTING -> RUNNING` cell | Suite result |
| --- | --- | --- |
| M1 | ". The identity of the new model group is written into `attempt.running_process_group_identity` and into `lease.owned_process_group_handle`" | **98 passed — FALSE GREEN** |
| M2 | ". The model process group's identity is recorded in `attempt.running_process_group_identity` and in the cleanup handle" | **98 passed — FALSE GREEN** |
| M3 | ". `attempt.running_process_group_identity` is set to that group, as is the cleanup handle" | **98 passed — FALSE GREEN** |
| M4 | ". `attempt.running_process_group_identity` having been written, the cleanup handle is then made to name the model group" | **98 passed — FALSE GREEN** (unknown predicate; fail-closed guard bypassed by the decoy) |
| M6 | ". The controller creates a second process group for the model process, and the identity of that group is written into `attempt.running_process_group_identity` and into `lease.owned_process_group_handle`" | **98 passed — FALSE GREEN** |
| M7 | ". A second process group is instantiated for the model process and the model group's identity is recorded in `attempt.running_process_group_identity` and in the cleanup handle" | **98 passed — FALSE GREEN** |
| M5 | ". A fresh controller-allocated process group **is created** for the model process, and the identity of that group is written into `attempt.running_process_group_identity` and into `lease.owned_process_group_handle`" | 7 failed, 91 passed — caught, **by the group-count dimension only** |
| M8 | handover with the prohibition explicitly scoped away ("That prohibition governs preflight only; …") | 6 failed, 92 passed — caught |

**M6 and M7 are the decisive cases.** Each is a complete, unambiguous, operative H-03 two-group handover — a second controller-created process group *and* the cleanup handle rewritten to name it — on the real edge, in direct contradiction of the prohibition sitting in the same cell, and the entire committed gate is green. M5 differs from M6 only in saying "is created" rather than "creates", which is the sole reason requirement 6 fires on it; that is luck of phrasing, not coverage (see M-02).

**Materiality.** This is exactly the defect the H-03 → K-01 → L-01 chain exists to prevent. Between the overwrite and the proof of the first group's emptiness, any surviving preflight descendant is owned by nothing the database can name, and freeze-contract §11's emptiness rule then passes vacuously over the model group alone. §3A.3 line 471 is explicit that a second write point is itself "a specification error that MUST fail closed, whether or not the prohibition sentence above is also present" — so the write-point dimension is precisely the gate that must hold here, and it does not.

**A repair exists and is small — I prototyped it (~15 lines, test module only, no contract change).** Attribute a write verb to `_OTHER_FIELD` only when no *live* handle referent shares the clause, where a handle referent is "live" unless it is inside a negated span or bound to a `READ_MARKERS` phrase (which is what keeps the pristine "MUST NOT be used as the cleanup handle" clause legitimate). Otherwise the clause is ambiguous ⇒ `UNCLASSIFIED` ⇒ the gate fails closed. Measured, with the prototype patched into a scratch copy of the test module:

- pristine candidate: **98 passed** (unchanged — including both legitimate-prose controls, a write to `attempt.workspace_path` and an explicit read of the handle);
- M1, M2, M3, M4, M6, M7: **26 failed / 72 passed each — all six caught.**

I am **not** claiming this exact code is the right final implementation; the repair round owns that. I am establishing that the blocker is closable inside the test module, without touching a freeze document, and without a false-positive cost.

---

### M-02 (non-blocking on its own, but it is why M-01 is not contained) — the group-creation derivation is narrower than its docstring implies

`GROUP_CREATION_RE` is `created|allocated|spawned|forked|established`, and `_asserts_a_group_creation` requires the group noun **before** the verb. Attacked with unseen grammatical forms on the same real edge:

| Mutation | Groups derived | Result |
| --- | --- | --- |
| "A second process group the controller **creates** is used for the model process" | 1 | **missed** (present-tense "creates" is not in the verb set) |
| "The controller **creates** a second process group for the model process" | 1 | **missed** |
| "…placed into a newly **created** controller-allocated group" | 1 | missed (disclosed blind spot B2, confirmed) |
| "A second process group is **instantiated** / **provisioned** / **opened**…" | 1 | **missed** (3 cases, unknown verbs) |
| "A second process group **is created**, not reusing the preflight one" | 2 | caught |
| "…a further process group, **created** fresh by the controller" | 2 | caught |
| "No longer sharing the preflight group, a second process group **is created** here" | 2 | caught (segment-scoped negation correctly does **not** swallow this) |

The negation scoping is sound — I could not construct a case where an earlier negator in the segment neutered a real creation. The weakness is purely the closed verb set and the noun-before-verb requirement, and unlike the handle classifier this dimension has **no fail-closed arm at all**: an unrecognised creation verb is simply not counted. On its own that is tolerable for a defence-in-depth check. Combined with M-01 it is why M6/M7 pass both dimensions at once, so it should be widened in the same repair.

---

### False-positive controls — the gate is *not* merely rejecting broad classes of prose

This matters: a gate that reddens on everything would look strong and prove nothing. It does not behave that way — six unsafe mutations pass, which is the blocker. In the other direction it is over-strict in two places, both fail-closed (red on legitimate prose, never green on unsafe prose):

- appending ". The preflight group created on `CREATED -> STARTING` continues to hold every process of the attempt" — a *back-reference* to the one legitimate creation — is counted as a second creation and turns the gate red;
- appending ". The cleanup handle is read here only to confirm it is unchanged" is `UNCLASSIFIED` (neither "read here" nor "unchanged" is a marker) and turns the gate red;
- previously disclosed B4 (an adverbial interrupting a negation, "MUST NOT, under any circumstances, be updated") reproduces.

These are safe-direction defects and are **not** blockers, but they mean legitimate future freeze-doc edits will hit the gate and must be phrased around it. Worth recording for whoever next edits §3A.

---

### Invariants J-01 / H-03 / H-04 / R-02 — recomputed independently from the contract

I re-derived the write point and the group cardinality from §3A myself before reading any helper, and both agree with §3A.3: exactly one edge creates the attempt's group and commits the handle, `CREATED -> STARTING` (SA line 384); `STARTING -> RUNNING` (line 385) prohibits the write, denies a second group, and legitimately writes the *other* field; the six remaining handle mentions (lines 387, 388, 389, 393, 394, 396) are reads. Process-group lifetime semantics, occupancy/release (§3D), one-group/durable-handle (§3A.3), reviewer ownership/cleanup (§3A.3 "Ownership is decided from the principal", §6 step 3, FC §21 step 8) and the retry ceiling (§3A.2) all read correctly and consistently in the committed text. **I found no contract defect in this round** — the blocker is entirely in the evaluator.

I then mutation-tested those invariants rather than trusting them. **Caught (13):** ceilings counting non-terminal rows only; "terminality alone releases a resource"; §6 releasing at step 7; slot uniqueness restricted to non-terminal rows; handle no longer write-once; declared group count raised to 2; FC §11 "exactly one" removed; `EXTERNAL` dispatch given an owned group; preflight failure made non-consuming; `QUARANTINED` made non-consuming; §3D release decrementing the ceiling; and both §3D release preconditions weakened from proven emptiness to a grace period.

**Missed (7) — one consolidated non-blocking finding, N-01.** Inverting §3A.3's "**Ownership is decided from the principal, never from NULL.**"; rewriting FC §19's summary to decide ownership from a NULL identity; deleting "§6 step 3 therefore branches on the principal kind **first**"; flipping §3A.3's `KERNEL_OWNED` write-ahead bullet to "after creating the reviewer process group"; rewriting "`QUARANTINED` is permitted **only** when…" to "whenever no durable identity was recorded"; making the ceiling "may be an in-memory-only counter"; adding a grace-period release path to the §3 `controller.reconcile` row.

All seven share one shape, and it is the shape already carried forward from earlier rounds: **the gate asserts the presence of safe wording, so a contradicting edit to a restatement leaves the document self-contradictory while the gate stays green.** In each case the *normative* copy of the rule survives elsewhere and is gated (the `review_dispatch` schema block, §6 step 3's own text, the §3D release table, §3A.2's "pure function of committed rows"). The result is a spec error a reader would catch, not a silently unsafe contract — which is why I classify N-01 non-blocking, consistent with the chain's prior treatment of the same class. It is, however, now seven instances rather than two, and it grows with each repair. It deserves a decision at freeze time: either accept it explicitly as a known limit of a prose gate, or add an agreement check that cross-compares the restatements against the normative section.

---

### Attacks the repair correctly caught (the L-01 work is real)

Every co-reference escape I could build where the handle is the *only* referent in its clause is caught, including forms not in the committed parametrisation: bare pronoun "it"; active voice with the object to the right ("The controller then rewrites it to name the model group"); alias + qualifier; unknown predicate with no decoy (correctly `UNCLASSIFIED`, fail-closed); a write appended after a surviving "MUST NOT update, replace or clear" in the same clause; a write separated by a semicolon from a prohibition. I could not defeat `_negated_spans` in the dangerous direction — I found no phrasing that got an operative write swallowed into a negation span and misread as a prohibition. Establishment-across-cells works as described.

### Remaining blind spots, disclosed

- **B3 (confirmed, carried forward):** a co-referential write in a row that names the handle in **no** cell is out of scope by construction. Partly mitigated because such a row usually has to assert a creation — but see M-02 for how easily that is evaded.
- **B1 (confirmed):** an unknown predicate in a clause that *also* carries a read marker classifies `READS_ONLY`.
- **B4, and the two new false positives above:** over-strict, fail-closed direction.
- **Carried forward:** a handover asserted only as §3A.3 prose that no §3A edge implements still passes.
- **New:** the group-creation dimension has no fail-closed arm (M-02).

---

## 5. What I changed

**Nothing.** This was a read-only round. No commit, no branch created, moved or switched, no file modified in any repository. All mutation work was done on a throwaway copy under `/tmp`, extracted with `git archive` and verified by hash; that scratch directory has been deleted.

- Files changed: **none**
- Commits made: **none**
- `/opt/crooks-os/crooks-assistant` (production): **not edited, not switched, not reset**

---

## 6. Test results and static checks (all recomputed this round)

| Check | Result |
| --- | --- |
| Committed freeze-spec suite at `4f1a915` | **98 passed in 1.35s** (reproduces the claimed count) |
| Same suite, scratch copy, hash-verified provenance | **98 passed** — harness validated before any mutation |
| `ruff check tests/test_orchestrator_freeze_spec.py` | **All checks passed** |
| `gitleaks git --redact --exit-code 1 --log-opts="a904a20..4f1a915"` | **no leaks found**, 1 commit scanned, exit 0 |
| Mutation runs | 8 handle-write mutations + 9 group-creation mutations + 4 false-positive controls + 20 invariant mutations + 7 prototype-repair runs, all on scratch copies |

The full offline suite was **deliberately not run**: it writes DBs and workspaces into the tree, and a read-only review round must leave `git status` at zero. The freeze set is documentation, so the freeze-spec module is the whole of its executable evidence.

---

## 7. Service, server and safety state

- Candidate worktree `/opt/crooks-builder/.worktrees/freeze-repair` — `4f1a915…`, `git status` **0 lines**.
- Builder checkout `/opt/crooks-builder` — `claude/builder-environment-repair` @ `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, **0 lines**.
- **Production checkout** `/opt/crooks-os/crooks-assistant` — `claude/linux-prod-migration-production` @ **`1cf3a0f3361b79f9de208d80f501543c53c244b5`**, **0 lines, untouched**.
- Bridge worktree `/opt/crooks-ai-bridge` — branch `crooks-ai-bridge`; **only `bridge/claude-outbox.md` written, nothing staged, committed or pushed**, per the handoff protocol.
- `crooks-assistant` service: **active**. FastAPI listening on **127.0.0.1:8000 only** — not exposed publicly. Watcher service currently `inactive` (between runs).
- Every safety constraint preserved and unchanged: `writes_enabled` false, `CROOKS_WRITES_LOCAL_OWNER` false, proposal/action/verification semantics untouched, no live Shopify / Gmail / ElevenLabs calls and no live external mutations, V2 not begun, UI not redesigned, Mac deployment and rollback path preserved, `/root/.claude` writable. No secret value appears anywhere in this file.

## 8. Errors

None. No command failed, nothing was blocked by the permission layer, and no part of the inbox went unexecuted.

---

## 9. Decisions or questions needing review

1. **M-01 is a blocker and the round should return to repair.** No owner decision is needed to establish that; it is an engineering finding with reproducible evidence.
2. **Owner decision deferred, not assumed — N-01.** Seven instances now exist where contradicting a *restatement* of a safe rule leaves the gate green because the normative copy survives. This is a structural property of a presence-asserting prose gate and will keep recurring. Either accept it explicitly as a stated limit of the freeze gate, or require a cross-document agreement check. **I am not recording any approval; none was given in the inbox.**
3. **Canonical drift, for adoption time only.** `claude/product-memory-foundation` is now `9a3761e`, ten docs-only commits ahead of the pinned merge-base `9e59860`. Still a fast-forward. Not reconciled — out of scope for a read-only round.

---

## 10. Exact proposed next step

Send one **repair** round to the builder, bound to parent `4f1a915421fc5324638168aa6a16fc51f5a9ee84`, scoped to **`crooks-assistant/tests/test_orchestrator_freeze_spec.py` only** — no freeze document may be edited, since no contract defect was found. One commit. It must:

1. **Close M-01.** Stop a non-handle backticked field from absorbing a write verb whose object may be the handle: attribute to `_OTHER_FIELD` only when the clause carries no *live* handle referent, where "live" excludes referents inside a negated span or bound to a `READ_MARKERS` phrase; otherwise return `UNCLASSIFIED`. Equivalently, move the fail-closed arm ahead of `WRITES_OTHER_FIELD` in the result ordering. The prototype above shows this keeps the pristine suite at 98 and catches all six mutations.
2. **Add M1–M4, M6, M7 verbatim as parametrised mutation tests**, each asserting the gate fails — so this exact escape cannot return, and so the next reviewer can check the claim mechanically.
3. **Close M-02.** Widen `GROUP_CREATION_RE` to present-tense and further creation verbs (`create`/`creates`/`creating`, `allocates`, `instantiate(s/d)`, `provision(s/ed)`, `opens`), accept a group noun **after** the verb, and give the dimension a fail-closed arm so an unrecognised creation predicate in a group-bearing clause is an error rather than a silent zero.
4. **Correct the docstring at line 1890**, which still claims more than the gate delivers.
5. **Leave every committed freeze document byte-identical to `a904a20`/`4f1a915`**, and re-report: suite count, ruff, gitleaks over the range, and a before/after table for all six M-mutations against the hash-verified `4f1a915` blobs.

Then one further fresh independent read-only adversarial review, bound to the exact new SHA. No prior verdict transfers.

**Not authorised and not performed:** no merge to any production branch, no deployment, no auto-merge, no live verification, nothing outward-facing or irreversible.

---

**Inbox SHA processed: `cc0d0e0c1c347bc04f76c892f6ae693a41b7b8c6`**
**SHA reviewed: `4f1a915421fc5324638168aa6a16fc51f5a9ee84`**
**Verdict: `REJECT — REPAIR REQUIRED` (one blocker: M-01)**
