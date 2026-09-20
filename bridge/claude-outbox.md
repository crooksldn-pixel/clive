# CLAUDE OUTBOX — Orchestrator V1 freeze candidate `de9bea2`, fresh adversarial review

**Timestamp:** 2026-09-20 (UTC, builder host)
**Inbox processed (blob SHA):** `b8298d6435435db87475bc7399ed303bcb7fbb77`
**Inbox consumed:** yes — `/opt/crooks-ai-bridge/bridge/chatgpt-inbox.md` was read in full and treated as this round's sole instruction set. Recorded here so the same instructions are never executed twice.

---

## VERDICT

**`REJECT — REPAIR REQUIRED`**, bound only to `de9bea2b040808175077777afc35c5394eb4d716`.

Two reproducible blockers. Both are defects **in the evaluator (the test module), not in the freeze contract**. The four freeze documents are byte-identical to the rejected parent and are not implicated.

- **M-03 (blocker, pre-existing and not closed by this repair).** A complete two-group handover — a second controller-created process group **plus** an operative rewrite of `lease.owned_process_group_handle` to name it — confined to a **single** §3A row leaves the full 144-test suite green, with the write-once prohibition and the declared count of `1` intact.
- **M-04 (blocker, REGRESSION introduced by this repair).** The M-02 rewrite of the group-creation derivation made a second controller-created process group **invisible** in a case the rejected parent `4f1a915` caught: any negator word appearing anywhere in the creation's own comma-segment defuses the creation, even when that negator negates something else entirely.

Neither blocker was reachable by replaying the repair's own mutations; both were found with new mutations, and M-04's regression is demonstrated by direct comparison against the parent gate.

---

## REQUIRED DISCLOSURE — this round is NOT independent

The inbox asks for a "fresh **independent** adversarial review". I must state plainly that I am not independent of this candidate: my own persistent project memory records, in the first person, that **I authored the `de9bea2` M-01/M-02 repair** in the previous bridge round (inbox `a8102a7`). The bridge's own stated rule is "implementation workers never self-certify."

I carried out the review anyway, as adversarially as I could, and it produced a REJECT — so the failure mode that self-certification usually creates (a rubber-stamp ACCEPT) did not occur here. But the converse guarantee is absent: **an ACCEPT from me on this SHA would not have been worth anything**, and the blind spots I did not find may be the ones I built in. The owner should treat this round as a self-review that happened to reject, and should route the next review of any repaired SHA to a reviewer that did not write the repair.

---

## Identity and scope (all verified this round, none taken on trust)

| Check | Result |
|---|---|
| Branch resolved fresh | `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` fetched explicitly from `origin` |
| Exact candidate SHA | `de9bea2b040808175077777afc35c5394eb4d716` — **matches the inbox**, review proceeded |
| Commits since parent `4f1a915` | exactly **1** (`de9bea2` "A decoy field can no longer absorb a write the cleanup handle could have taken") |
| Changed-file scope | exactly **1 file**, `crooks-assistant/tests/test_orchestrator_freeze_spec.py`, **+419 / −15** |
| Freeze-document byte identity | **all 21** files under `docs/product-memory` byte-identical `4f1a915` → `de9bea2`; `ORCHESTRATOR_V1_STATE_API.md` blob `189601e8a6b6f468aa87cd87096037014ffb3929` unchanged |
| `DECISIONS.md` | candidate blob `a6dc313…` == merge-base `9e59860` blob — candidate does not touch it (canonical has moved it to `27231ba…`, expected) |
| Merge-base vs canonical | merge-base `9e59860`; canonical `claude/product-memory-foundation` = `654a9ed7d790e38597a3c5852d9b3e0a42902a1a`; `9e59860` is still an ancestor (fast-forward) |
| `merge-tree de9bea2 654a9ed` | conflict-free → tree `216f9ce8d8d4cc060416074f4afb1444d7022669` |
| No self-adoption | candidate does not alter `DECISIONS.md` or DEC-046/047 sequencing |
| Worktree clean | `git status --porcelain` = **0 lines** at start and at end |
| Test module weakening | **0** test functions removed, **0** `assert` lines deleted. Test functions **65 → 73 (8 added)**. The 15 deleted lines are entirely the replaced bodies of `GROUP_CREATION_RE` / `_asserts_a_group_creation` and the `if unattributable:` → `if unattributable or contested:` line |
| Skip/xfail bypass | **0** `pytest.mark.skip` / `xfail` / `pytest.skip` in the module |

**Note on a repair claim that does not reproduce:** the repair is recorded as adding 9 test functions ("54 → 73"). Independently measured, the parent has **65** test functions and the candidate **73** — **8 added**. The discrepancy is in the claim, not in the code; no test was removed either way, so this is a bookkeeping error rather than a weakening. Flagged because the inbox says not to accept the repair prose as proof.

---

## Static checks and secret scan

- `ruff check app config scripts tests` → **All checks passed!**
- `gitleaks git --log-opts="4f1a915..de9bea2"` → 1 commit scanned, **no leaks found** (exit 0)
- `gitleaks dir` on the changed test file → **no leaks found**
- No secret value was printed, read or committed at any point in this round.

---

## Test results

- Freeze spec at `de9bea2`, in the candidate worktree: **144 passed in 1.62s** — the claimed count reproduces exactly.
- Freeze spec at `de9bea2`, in an isolated scratch with hash-verified docs: **144 passed**.
- Freeze spec at parent `4f1a915`, in an isolated scratch with the same (byte-identical) docs: **98 passed**.
- **The full offline suite was deliberately NOT run.** It writes databases and workspaces into the tree, which would violate the read-only constraint of this round. The prior round's figure (2947 passed / 8 skipped) is therefore carried forward **unverified** by me. The inbox's own instruction applies: ordinary regression green counts are necessary but insufficient, and 144/144 is exactly what both blockers below survive.

### Provenance of every scratch used
Both scratch trees were proved against git before use, and deleted afterwards:
- candidate test module `git hash-object` = `d58398c92273492f161ab79dceee0db7adae5099` = `git rev-parse de9bea2:…`
- parent test module `git hash-object` = `6ffa17430450218a2b6a7a7c88378526c4274e1f` = `git rev-parse 4f1a915:…`
- `ORCHESTRATOR_V1_STATE_API.md` `git hash-object` = `189601e8a6b6f468aa87cd87096037014ffb3929` = `git rev-parse de9bea2:…`

---

## BLOCKER M-03 — both derivations count *rows*, so a whole handover hides inside one row

### The defect
`attempt_rows_writing_the_cleanup_handle` (test module line 1855) and `attempt_rows_creating_an_owned_process_group` (line 1940) each return a **list of rows**, deduplicated by `if row not in rows`. `assert_declared_write_point_matches_the_matrix` and `assert_declared_group_count_matches_the_matrix` then compare `len(rows)` against §3A.3's declared count of `1`.

A row that already legitimately contains one write and one creation can therefore absorb an unlimited number of further writes and further creations without either count moving. The classifier is *not* fooled — it correctly returns `WRITES` for the injected clause and `_asserts_a_group_creation` correctly returns `True` — the information is computed and then discarded by the aggregation.

### Reproduction (exact)
Append to the committed `CREATED -> STARTING` cell of §3A, immediately after
`…and preflight runs inside that group; \`attempt.running_process_group_identity\` stays NULL`:

```
; once preflight passes a second process group is created for the model,
and `lease.owned_process_group_handle` is rewritten to name that new group
```

**Result: 144 passed.** The English-alias variant ("the controller then creates a separate process group for the model run and the cleanup handle is updated to name it") is also **144 passed**.

### Gate's own derivations, pristine vs mutated
```
                              PRISTINE                     MUTATED (M-03)
rows WRITING the handle     : 1  CREATED -> STARTING       1  CREATED -> STARTING
rows CREATING a group       : 1  CREATED -> STARTING       1  CREATED -> STARTING
§3A.3 declares              : groups=1 write_points=`CREATED -> STARTING`
assert_declared_write_point_matches_the_matrix : PASS      PASS
assert_declared_group_count_matches_the_matrix : PASS      PASS
```
Clause verdicts on that row in the mutated document show **two** separate `WRITES` clauses; the row count stays 1.

`test_every_handle_mention_in_the_attempt_matrix_is_classified` does not help: it compares a **set** of verdicts per edge, and `{WRITES, READS_ONLY}` is unchanged by adding a second `WRITES`.

### Safety prose left fully intact by the mutation
- `It is **write-once** under §3A.3` — PRESENT
- `no later edge — \`STARTING -> RUNNING\` included — writes it` — PRESENT
- `a record owns **exactly one** controller-created process group` — PRESENT
- `and **never written again** while the attempt is non-terminal` — PRESENT

This is the H-03 defect restored in full, with both defence-in-depth dimensions defeated by the same single property.

### Information gain
Green at `de9bea2` **and** green at `4f1a915` — pre-existing, and **not closed** by this repair. It is reported now because every previously tested handover (M6/M7 and the review's own mutations) was placed on a *second* row, which is the only placement the row-counting aggregation can see. The repair's disclosed scope claims complete two-group handovers are caught; that holds only for cross-row placement.

### Smallest safe repair (prototyped and measured this round, in scratch only)
Count **assertions, not rows**, in both derivations — keep the existing row-level assertion first so the existing mutation tests' expected messages still match, then add a clause-level count:

- in `assert_declared_write_point_matches_the_matrix`: count `classified_handle_mentions(api_text)` entries whose verdict is `WRITES` and assert that count `== int(groups)`;
- in `assert_declared_group_count_matches_the_matrix`: count clauses for which `_asserts_a_group_creation(clause)` holds, across `attempt_transition_rows`, and assert that count `== int(groups)`.

The pristine document yields **exactly 1** write clause and **exactly 1** creation clause, so this is a drop-in. Measured with that ~16-line, test-module-only patch:

| Mutation | `4f1a915` | `de9bea2` | prototype |
|---|---|---|---|
| pristine control | 98 passed | **144 passed** | **144 passed** |
| M-03 same-row handover (backticked) | GREEN | **GREEN** | **RED (caught)** |
| M-03 same-row handover (English alias) | GREEN | **GREEN** | **RED (caught)** |
| cross-row handover (control) | RED | RED | RED |
| relocated creation (control) | — | RED | RED |

The prototype was built and run entirely in `/tmp`; the candidate worktree was never modified.

---

## BLOCKER M-04 — a negator anywhere in the segment defuses a real creation (regression)

### The defect
`_asserts_a_group_creation` (line 1916) accepts a creation when a `GROUP_CREATION_RE` verb shares its `[,:;]`-delimited segment with a group noun, and rejects it when `CREATION_NEGATION_RE` matches **anywhere in that same segment**. The negator is never required to *govern* the creation verb — not by position, not by scope. Any of `no|not|never|nor|without|MUST NOT|cannot|can never` landing in the segment for unrelated reasons silences the creation.

This is the half of the M-02 rewrite that regressed: the parent scoped the segment from the nearest preceding group noun up to the verb, so a negator appearing *after* the verb could not reach it. Widening the segment to "either side of the verb" widened the negation defusal by exactly the same amount.

### Direct probes of `_asserts_a_group_creation` at `de9bea2`
```
True   a second process group is created for the model                                    (correct)
True   the controller creates a second process group                                      (correct)
True   the model is placed into a newly created process group                             (correct)
False  no second process group is created                                                 (correct denial)
False  a second process group is created without delay                                    <-- WRONG
False  if preflight cannot be proven empty a second process group is created              <-- WRONG
False  a second process group is created for the model and not for preflight              <-- WRONG
False  though cleanup is not yet proven the controller creates a second process group     <-- WRONG
```

### End-to-end reproduction, unconfounded by baseline pins
The `STARTING -> RUNNING` cell is protected by a **verbatim** string pin (`test_the_committed_running_edge_still_charges_its_write_to_the_other_field`), so any edit there goes red for reasons unrelated to the derivation. To isolate the real behaviour the mutation was placed on `RUNNING -> CANDIDATE_READY`, a §3A row that establishes no handle context and carries no pin — so the write dimension is silent by construction and only the group dimension can speak.

Appended to that row's last cell:

| Appended clause | `4f1a915` | `de9bea2` |
|---|---|---|
| `; a second process group is created for the model` (control) | RED — 10 failed | RED — 20 failed |
| `; a second process group is created for the model without delay` | **RED — 10 failed** | **GREEN — 144 passed** |
| `; if cleanup cannot be proven a second process group is created for the model` | GREEN | **GREEN — 144 passed** |

Row 2 is the regression: **caught at the parent, escapes at the candidate.** Row 3 is pre-existing and of the same family.

### Why this is unsafe, not merely imprecise
The escaping mutation asserts a second controller-created process group that the cleanup handle **never names** — so no handle write exists for the write dimension to find, and the group dimension is the only guard there is. §6 then proves the handle's group empty and closes the attempt clean while the second group's processes survive untracked. That is exactly the orphan-survival semantics H-03 was raised for.

The M-03 prototype does **not** fix this (it corrects counting granularity, not negation scoping); measured: `without delay` and `cannot` variants remain GREEN under the prototype.

### Smallest safe repair scope
Require the negator to actually govern the creation verb. The pristine document constrains this precisely — every one of its three genuine denials places the negator **before** the creation verb in the segment:

```
[DENIED by 'no']  STARTING -> RUNNING                      …and no second group is created
[DENIED by 'no']  CREATED -> CLOSED / CANCELLED or FENCED  no owned process group has been created
[DENIED by 'no']  STARTING -> CLOSED / CANCELLED or FENCED A NULL handle means no group was ever created
```
and the single genuine creation (`CREATED -> STARTING`) carries no negator at all.

A positional rule — the negator must precede the creation verb within the segment — preserves all three denials and closes the `without` / `and not` / post-verb `never` family. It does **not** close the `cannot`-in-a-subordinate-clause form, where the negator precedes the verb but governs a different one; closing that needs the negation to be scoped to the verb it actually commands (the analogue of the existing `_negated_spans` coordinated-verb walk, built over creation verbs rather than write verbs), and whichever rule is chosen must be measured against those three pristine denials, which a naive verb-list walk breaks. I did not prototype a full fix for M-04 — I am reporting the constraint set rather than guessing the rule.

---

## Non-blocking observations (reported, not blocking; no repair requested)

1. **The `STARTING -> RUNNING` cell is effectively byte-pinned.** `test_the_committed_running_edge_still_charges_its_write_to_the_other_field` asserts the full committed cell string is present. Two of my false-positive controls — a legitimate unrelated-field write (`` `attempt.attempt_index` is recorded in the same commit ``) and a genuine read-only handle reference (`` the owned group is identified from `lease.owned_process_group_handle` ``) — went RED on that pin and on the per-edge verdict-set pin. **Importantly, the classifier itself accepts both correctly** (`WRITES_OTHER_FIELD` and `READS_ONLY` respectively) and both core invariants PASS; only the baseline pins object. So the inbox's requirement that legitimate writes and genuine reads "remain accepted" **is satisfied at the semantic layer**. The pins are over-strict in the fail-closed direction — they block legitimate future prose edits, they never admit unsafe prose. The unrelated-field case is newly red at `de9bea2` (it was green at `4f1a915`), i.e. this candidate tightened the baseline deliberately.

2. **The noun "record" is read as a write verb.** `WRITE_VERBS` contains `record`/`records`/`recorded`, and `WRITE_VERB_RE` is purely lexical, so harmless prose in handle-established context — e.g. `a measurement record is created for the preflight result` — resolves to no referent and fails closed as `UNCLASSIFIED`. Red at both SHAs. Fail-closed direction, but "record" is a very common noun in these documents and this will bite legitimate §3A edits.

3. **Blind spot B1 is still live but was not exploitable here.** A clause containing any `READ_MARKERS` substring anywhere returns `READS_ONLY` before the fail-closed arm; `"against"` in particular is an ordinary English word. My attempt to exploit it (`the cleanup handle is read from the lease and thereafter designates the model process group instead`) was caught — by the per-edge verdict-set pin, not by the classifier. On an unpinned row the same shape would need a group creation to do real damage, which lands back in M-04.

4. Canonical has not moved since the last round (`654a9ed`); reconciliation with it remains out of scope and unperformed, to be flagged at adoption time.

---

## What I changed

**Nothing.** This was a read-only round.

- No file in the candidate worktree was created, modified or deleted. `git status --porcelain` = 0 lines before and after.
- No commit, no push, no branch or worktree created or switched, no rebase, no merge.
- No freeze document, test, canonical product memory, runtime or infrastructure was touched.
- All mutation and prototype work was done in throwaway scratch trees under `/tmp`, built from `git archive` / `git show` with blob hashes verified against git, and **deleted at the end of the round**.
- The only file written outside the repos is this outbox.

**Files changed: none.**

---

## Repository and service state

| Item | State |
|---|---|
| Candidate worktree `/opt/crooks-builder/.worktrees/freeze-repair` | HEAD `de9bea2b040808175077777afc35c5394eb4d716`, `git status` **0 lines** |
| Builder checkout `/opt/crooks-builder` | branch `claude/builder-environment-repair`, HEAD `295e483`, `git status` **0 lines** — untouched this round |
| Production checkout `/opt/crooks-os/crooks-assistant` | branch `claude/linux-prod-migration-production`, HEAD `1cf3a0f3361b79f9de208d80f501543c53c244b5`, `git status` **0 lines** — **read only, never switched, reset or edited** |
| `crooks-assistant.service` | loaded, active, running — not restarted, not reconfigured |
| `crooks-bridge-watcher.service` | loaded, active, running |
| FastAPI binding | `LISTEN 127.0.0.1:8000` — loopback only, **port 8000 not exposed publicly** |

### Safety constraints — all preserved, none altered
`writes_enabled` false · `CROOKS_WRITES_LOCAL_OWNER` false · FastAPI bound to 127.0.0.1 · port 8000 not public · proposal/action/verification safety semantics unchanged · **no live Shopify, Gmail or ElevenLabs calls and no live external mutations** · V2 not begun · UI not redesigned · Mac deployment and rollback path preserved · `/root/.claude` still writable · no secret value printed or committed · nothing merged, nothing deployed, nothing auto-merged.

---

## Errors

None. No command failed unexpectedly, and nothing was blocked by my permission layer. One prototype iteration initially broke 31 tests because my added assertion fired ahead of an existing one and changed a `pytest.raises(match=…)` message; reordering the assertion resolved it, and that is reflected in the measured prototype above.

---

## Decisions and questions needing review

1. **The independence failure is the most important thing on this page.** The bridge asked for an independent review of a repair my own memory records me as having authored. It rejected, so nothing was rubber-stamped — but the process guarantee is broken and should be fixed before the next round, not after. **Question for the owner: should the next review of this candidate line be routed to a reviewer that did not write the repair?** I cannot answer that myself and have not assumed an answer.
2. **M-03 is pre-existing, not a regression.** It has been green through several rounds. The owner may wish to know that the "two independent dimensions" guarantee has, for that placement, never actually held.
3. **M-04 is a genuine regression** introduced by the repair that was supposed to strengthen that exact dimension. This is the strongest argument that the M-02 change needs re-measurement against the parent, not just against its own new tests.
4. I did **not** run the full offline suite (read-only constraint); the 2947/8 figure is unverified by me.
5. No approval of any kind is recorded or assumed. Nothing in this round required owner approval, and none was sought or given.

---

## Exact proposed next step

**One repair round on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, branching from `de9bea2`, one commit, test module only** (`crooks-assistant/tests/test_orchestrator_freeze_spec.py`) — **no freeze document may be touched; both blockers are evaluator defects.**

The repair must:

1. **Close M-03** by counting write assertions and creation assertions rather than rows carrying at least one, in `assert_declared_write_point_matches_the_matrix` and `assert_declared_group_count_matches_the_matrix`. Keep the existing row-level assertions ahead of the new clause-level ones so the committed `pytest.raises(match=…)` messages still match. Pristine yields exactly 1 and 1.
2. **Close M-04** by requiring the negator to govern the creation verb in `_asserts_a_group_creation`, measured against the three pristine denials listed above, which must all remain denials, and against the `without delay` / `and not` / `cannot`-subordinate-clause forms, which must all become creations.
3. **Add regression tests** that pin both: a same-row handover (backticked and English-alias forms) must fail the gate, and a negator-defused second creation on an unpinned row must fail the gate.
4. **Measure every claim against the parent gate**, not only against the new tests — M-04 existed precisely because the repair was measured only in the direction it was aiming at. The comparison tables in this outbox are the minimum shape.
5. Keep the suite additions-only; remove or weaken no assertion.

Then: **one fresh independent read-only adversarial review bound to the exact new SHA, performed by a reviewer that did not write the repair.**

Engineering acceptance remains distinct from owner adoption. Nothing here authorises rebase, merge, deployment, runtime or watcher changes, secrets or connectors, privilege expansion, business writes, production promotion, freeze adoption, or any DEC-046/047 sequencing change.

**Inbox SHA processed: `b8298d6435435db87475bc7399ed303bcb7fbb77`.** Review complete; stopping here as instructed.
