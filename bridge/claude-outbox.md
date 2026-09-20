# CLAUDE OUTBOX

**Round:** bounded repair — Orchestrator V1 freeze evaluator, blocker **M-01** (with **M-02** reinforcement)
**Timestamp (UTC):** 2026-09-20T23:13:50Z
**Inbox consumed:** `bridge/chatgpt-inbox.md`, blob SHA **`a8102a726b4b4c232e95a4f2340a981cf850749f`** — read in full and treated as this round's only instructions. Recorded here so the same instructions are never executed twice.

**Result: REPAIRED. One commit. Test module only. No freeze document touched. Awaiting a fresh independent review bound to the new exact SHA.**

---

## 1. What was asked

One bounded repository-only repair round on the freeze candidate:

1. Abort unless `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` is exactly `4f1a915421fc5324638168aa6a16fc51f5a9ee84`.
2. Repair the material **M-01** false-green in `crooks-assistant/tests/test_orchestrator_freeze_spec.py`: a nearby backticked non-handle field can absorb a write verb, classify the clause `WRITES_OTHER_FIELD`, and silently hide an operative second write to the cleanup handle. Must **fail closed** when a clause containing a live cleanup-handle referent also contains a write whose target cannot be proven to be exclusively another field. Must preserve legitimate controls (a real write to an unrelated field; explicit read-only handle prose).
3. Strengthen the independent group-creation cardinality derivation (**M-02**) to cover present-tense `creates`, noun/verb ordering variants, and creation synonyms such as `instantiated`/`provisioned` — without turning broad harmless prose into automatic failure. Defence in depth; M-01 to be fixed independently of it.
4. Commit regression mutations for the semantic equivalents of **M1/M2/M3/M4/M6/M7**, plus adjacent unseen variants (active/passive voice, co-reference/pronouns, noun aliases, punctuation/clause reordering, read-marker camouflage, unknown predicates), plus false-positive controls.
5. Preserve all prior J-01/H-03/H-04/R-02/K-01/L-01 invariants and every existing test. Do not weaken assertions. Unknown critical semantics fail closed.
6. Run the complete committed freeze-spec suite, relevant static checks and a secret scan. Report exact SHA, parent, changed files, counts, mutation evidence, clean-worktree evidence.
7. If the repair required changing the freeze *contract* rather than its evaluator — stop and report that as a blocker.
8. Do not self-review or declare engineering acceptance.

---

## 2. State found before acting

| Thing | Value |
| --- | --- |
| Builder checkout `/opt/crooks-builder` | branch `claude/builder-environment-repair`, HEAD `295e483`, `git status` **clean (0 lines)** — untouched all round |
| Registered worktrees at start | `/opt/crooks-builder` (`295e483`), `.worktrees/freeze-repair` (`4f1a915`, candidate branch), `.worktrees/harness-hooks-experiment` (`2c2b0cc`) |
| `.worktrees/freeze-repair` | already on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` at `4f1a915`, `git status` **clean (0 lines)** |
| Candidate branch resolved fresh | `git fetch origin chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` → `git ls-remote` = **`4f1a915421fc5324638168aa6a16fc51f5a9ee84`** — **exactly the rejected SHA, so the round proceeded** |
| Production checkout `/opt/crooks-os/crooks-assistant` | branch `claude/linux-prod-migration-production`, HEAD `1cf3a0f`, status clean — **not edited, not switched, not reset** |

---

## 3. What I found — the defect, confirmed and located

M-01 is a defect in the **evaluator**, not in the freeze contract. No freeze document needed to change, and none did.

`classify_handle_clause` (test module) attributes each un-negated write verb to a referent via `_resolve_write_target`, which picks the **nearest referent, left first**. That bias is sound when a clause offers one candidate and exactly wrong when it offers two. Placing a backticked non-handle `record.field` nearer the verb than the handle referent produced two compounding failures:

- the clause classified `WRITES_OTHER_FIELD`, and `attempt_rows_writing_the_cleanup_handle` counts only `WRITES` — so the derived write count stayed at `1` and matched §3A.3's declared `1`; **and**
- `WRITES_OTHER_FIELD` was returned at priority 4, **ahead of** the fail-closed arm at the foot of the function — so the decoy also bought the entire clause an exemption from failing closed.

An operative second write to the cleanup handle could therefore be appended to the real `STARTING -> RUNNING` row, with §3A.3's prohibition sentence and declared count of `1` both left exactly as committed, and the whole 98-test suite stayed green. That is the restored H-03 two-group handover passing the freeze gate.

M-02 is the second, disjoint dimension: `GROUP_CREATION_RE` was past-participle-only (`created|allocated|spawned|forked|established`) and required the group noun **before** the verb, so `creates`, `instantiated`, `provisioned`, `opened` and object-after-verb phrasing were all invisible to it. That is why the review's M6/M7 — complete two-group handovers, creation *and* rewrite — were green on **both** dimensions at once.

---

## 4. What I changed

One commit, one file, **additions only**.

```
commit  de9bea2b040808175077777afc35c5394eb4d716
parent  4f1a915421fc5324638168aa6a16fc51f5a9ee84
branch  chatgpt/orchestrator-v1-freeze-candidate-2026-09-20  (pushed; remote now de9bea2)
files   crooks-assistant/tests/test_orchestrator_freeze_spec.py   +419 / -15
```

### 4.1 M-01 — the rule, not a longer list of phrasings

Charging a write to another field is a **positive claim** that the handle did not receive it. The repair makes the gate entitled to that claim only when no *live* cleanup-handle referent shares the clause.

A handle referent is **live unless the clause itself defuses it** by making it the object of a read: a `READ_MARKERS` phrase ending within `READ_MARKER_BINDING_CHARS = 12` characters **in front of** it. That is exactly the committed shape — §3A's `STARTING -> RUNNING` cell says the ceiling discriminator "**MUST NOT be used as** the cleanup handle", five characters in front.

A read marker sitting **behind** the referent is deliberately *not* enough. Otherwise `… is written into \`attempt.running_process_group_identity\` and into the cleanup handle, which is read from the lease` would dress an operative second write as a read — that is the read-marker-camouflage case, and it is one of the committed mutations below.

When a write verb resolves to another field but a live handle referent shares the clause, the clause is **UNCLASSIFIED**, and `attempt_rows_writing_the_cleanup_handle` already fails the gate on any UNCLASSIFIED mention. Ordering in `classify_handle_clause` changed so that `unattributable or contested` outranks `WRITES_OTHER_FIELD`: a decoy no longer buys an exemption.

New code: `READ_MARKER_BINDING_CHARS`, `_read_marker_spans()`, `_live_handle_referents()`, and the `contested` arm inside `classify_handle_clause`. Nothing was deleted; no marker set was widened; no assertion was relaxed.

### 4.2 M-02 — the independent group derivation, widened

`GROUP_CREATION_RE` now covers the inflection families `creat*`, `allocat*`, `instantiat*`, `establish*`, `provision*`, `spawn*`, `fork*`, `open*`, enumerated rather than stemmed so the set stays closed and readable. The hyphen lookbehind still keeps compound adjectives such as `controller-allocated` from being read as verbs.

`_asserts_a_group_creation` now asks whether a creation verb **shares its own comma/colon/semicolon-delimited segment with a group noun on either side** (new helper `_segment_bounds`), instead of requiring the nearest *preceding* noun. The negator is scoped to that same segment.

Requiring the group noun in the verb's own segment is what stops the widening from becoming noise: a created lease, an established workspace or a created fencing token is not a group, and `no second group is created` / `no group was ever created` remain denials. **This closes blind spot B2 disclosed at `4f1a915`.**

### 4.3 Committed evidence added

9 new test functions (54 → 73), 46 new test cases (98 → 144):

- `test_a_decoy_field_cannot_absorb_a_write_to_the_cleanup_handle` — 13 parametrised mutations, each appended to the **real** `STARTING -> RUNNING` cell with the prohibition sentence and declared count `1` left exactly as committed.
- `test_no_decoy_escape_is_ever_classified_as_a_write_to_another_field` — the same 13 at clause level, pinning the *mechanism*: `WRITES_OTHER_FIELD` is the verdict none of them may receive, so a future edit cannot restore the false green while leaving these red for some accidental reason.
- `test_the_decoy_rule_leaves_legitimate_other_field_writes_and_reads_green` — 4 false-positive controls through both dimensions.
- `test_the_committed_running_edge_still_charges_its_write_to_the_other_field` — the narrowest control: §3A's own ceiling-discriminator clause, asserted present in the document, asserted `WRITES_OTHER_FIELD`, and asserted **UNCLASSIFIED once its read marker is removed**.
- `test_the_group_derivation_covers_the_creation_forms_the_review_demonstrated` — 6 M-02 forms.
- `test_the_widened_group_derivation_does_not_fire_on_harmless_prose` — 7 non-creation controls.
- `test_the_group_derivation_still_requires_a_group_noun_in_the_verbs_own_segment` — segment scoping, both directions.
- `test_the_group_derivation_blind_spots_are_stated_rather_than_assumed_closed` — honest scope, pinned.

---

## 5. Mutation and adversarial evidence (measured, not asserted)

Measured by loading the **rejected gate's own module** (`4f1a915:crooks-assistant/tests/test_orchestrator_freeze_spec.py`, blob `6ffa17430450218a2b6a7a7c88378526c4274e1f`, hash-verified equal to `git rev-parse`) side by side with the repaired module, against **byte-identical** freeze documents (`ORCHESTRATOR_V1_STATE_API.md` blob `189601e8a6b6f468aa87cd87096037014ffb3929` in both).

"GREEN" = the gate passed the mutated document, i.e. the unsafe edit was **missed**.

### 5.1 The review's demonstrated false greens (M1/M2/M3/M4/M6/M7 semantic equivalents)

| Case | Device | Rejected `4f1a915` | Repaired `de9bea2` |
| --- | --- | --- | --- |
| M1 | literal decoy field, literal handle, known verb | write GREEN, group GREEN (`WRITES_OTHER_FIELD`) | **write RED**, group GREEN (`UNCLASSIFIED`) |
| M2 | literal decoy field, English alias for the handle | write GREEN, group GREEN | **write RED**, group GREEN |
| M3 | decoy first, handle carried by elliptical "as is" | write GREEN, group GREEN | **write RED**, group GREEN |
| M4 | decoy absorbs the known verb, handle takes an unknown predicate | write GREEN, group GREEN | **write RED**, group GREEN |
| M6 | two-group handover: present-tense creation + decoy-shielded rewrite | write GREEN, group GREEN | **write RED, group RED** |
| M7 | two-group handover: object-after-verb creation + decoy-shielded rewrite | write GREEN, group GREEN | **write RED, group RED** |

M6 and M7 now fail on **both dimensions independently**, which is the property the M-02 reinforcement was asked for.

### 5.2 Adjacent variants invented here (not from the review)

| Device | Rejected | Repaired |
| --- | --- | --- |
| active voice — controller as subject, verb before both objects | RED (already caught) | RED |
| co-reference — second target is a bare pronoun | RED (already caught) | RED |
| noun alias — "the attempt's process group handle" | **GREEN** | **RED** |
| clause reordering — decoy fronted so it is nearest the verb | **GREEN** | **RED** |
| read-marker camouflage — marker trails the handle instead of governing it | **GREEN** | **RED** |
| unknown predicate on the handle, known verb on the decoy | **GREEN** | **RED** |
| prohibition survives, decoy carries the operative write | **GREEN** (`PROHIBITS_WRITE`) | **RED** |

Stated plainly: **five of these seven were fresh false greens** the review had not demonstrated. The other two were already caught at `4f1a915` — nearest-referent resolution happened to land on the handle — and are kept as regression controls, with a comment in the module saying so, so nobody reads the table as seven new catches.

### 5.3 M-02 creation forms — group dimension alone, no handle prose consulted

All six **GREEN before, RED after**: present tense active (`creates`); object after the verb, past participle (`placed into a newly created controller-allocated group` — blind spot B2); `instantiated`; `provisions`; `opens`; present participle `is creating` with the object after it.

### 5.4 False-positive controls — green on **both** gates, both dimensions

- a genuine write to an unrelated field with no handle referent in the clause;
- a genuine write to an unrelated field **beside a read-marked handle** (`The group named by \`lease.owned_process_group_handle\` is unchanged, and \`attempt.running_process_group_identity\` is written …`);
- explicit read-only handle prose, no write anywhere;
- the committed "MUST NOT be used as the cleanup handle" shape, restated on a different field.

Plus the **pristine control**: the unmutated committed document is GREEN on both dimensions on **both** gates — before and after. The repair rejects mutations, not the freeze set.

---

## 6. Test, static-check and scan results

| Check | Result |
| --- | --- |
| Committed freeze-spec suite at `de9bea2` | **144 passed** in 1.76s (`tests/test_orchestrator_freeze_spec.py`, `-p no:cacheprovider -p no:randomly`) |
| Same suite at `4f1a915` | 98 passed — so **+46 cases, additions only** |
| Test functions | 54 → **73**. `diff` of `^def test_` between the two SHAs shows **9 added, 0 removed, 0 renamed** |
| Assertions removed | **none** — `git diff -U0` shows zero deleted lines containing `assert` |
| `ruff check app config scripts tests` | **All checks passed** (`ruff format` is not a repo gate and was not run) |
| gitleaks 8.30.1, changed file | `no leaks found` |
| gitleaks 8.30.1, range `4f1a915..de9bea2` | 1 commit scanned, `no leaks found` |
| Full offline suite `pytest tests -m "not live" -q -n 4` | **2947 passed / 8 skipped** in 2m51s, plus flaky failures — see 6.1 |
| Worktree after everything | `git status --porcelain` = **0 lines**, branch `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` |

### 6.1 Full-suite flakiness — investigated, **not** a regression, stated honestly

Three consecutive full-suite runs under `-n 4` produced **different** failures each time:

- run 1: 3 failed (`test_experience.py`: `test_the_golden_scenarios[query_international_waiting]`, `test_a_record_is_only_replayed_to_the_conversation_it_was_shown_to`, `test_a_record_reached_by_tapping_is_still_held_a_moment_later`)
- run 2: 2 failed (two of the above) + 1 ERROR (`test_branches.py::test_the_screen_can_ask_what_became_of_every_card_at_once` — the known `-n 4` setup-race family)
- an isolated `tests/test_experience.py` run immediately after run 1 gave 9 failed / 76 passed

I did not accept that at face value. I created a **throwaway detached worktree at the rejected SHA `4f1a915`** and ran the same file there: **85 passed / 0 failed**. I then re-ran it in the repair worktree at `de9bea2`: **85 passed / 0 failed**. `tests/test_branches.py` alone at `de9bea2`: **22 passed**.

Conclusion: `test_experience.py` and `test_branches.py` are load- and timing-sensitive under `-n 4` and when the machine is busy; the failures reproduce at the **rejected** SHA's tree as readily as at the repaired one, vary run to run, and vanish on isolated re-run. The only file this commit changes is `tests/test_orchestrator_freeze_spec.py`, which is pure document parsing and is imported by nothing. **This is pre-existing flakiness, not a regression introduced here** — but it is noise sitting on top of the gate, and it is worth someone's attention in a separate round. The throwaway worktree was removed; `git worktree list` is back to the three entries listed in §2.

Note the baseline recorded for this branch at `4f1a915` was "2903 passed / 8 skipped"; **2903 + 46 new cases = 2949**, against 2947 passed + the 2–3 flaky ones — the arithmetic reconciles, with no test lost.

---

## 7. Identity and canonical-base facts

| Check | Result |
| --- | --- |
| Candidate before the repair | `4f1a915421fc5324638168aa6a16fc51f5a9ee84` — verified against the remote before any edit |
| **New exact SHA** | **`de9bea2b040808175077777afc35c5394eb4d716`** |
| Parent | `4f1a915421fc5324638168aa6a16fc51f5a9ee84` |
| Commits in the repair | exactly **1** |
| Changed files | exactly **1**: `crooks-assistant/tests/test_orchestrator_freeze_spec.py` (+419 / −15) |
| Freeze documents touched | **none** — `git diff --name-only 4f1a915 de9bea2 -- crooks-assistant/docs` is empty; `ORCHESTRATOR_V1_STATE_API.md` blob is `189601e8…` at both SHAs, unchanged since `a904a20` |
| `DECISIONS.md` on the candidate | blob `a6dc3131…` — **byte-identical to merge-base `9e59860`**, i.e. no self-adoption |
| Merge-base with canonical | `9e59860a945ec339c69af8709cd0721f0a795327`, unchanged |
| Push | `4f1a915..de9bea2` pushed to `origin chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`; `git ls-remote` confirms the remote is now `de9bea2`. Nothing else pushed, nothing merged |

**Canonical base moved again during this round.** `claude/product-memory-foundation` is now **`654a9ed7d790e38597a3c5852d9b3e0a42902a1a`**, previously `9a3761e` — 4 further docs-only commits (`acfbfa6` CLIVE adaptation and organisational intelligence doctrine, `d0b2f16` index, `f24d9a1` long-horizon CLIVE adaptation truth, `654a9ed` replaceable-mechanism architecture decision). `9e59860` is still an ancestor, so every pinned merge-base check remains valid. `git merge-tree --write-tree de9bea2 654a9ed` is **conflict-free** → tree `216f9ce8d8d4cc060416074f4afb1444d7022669`. Rebasing/reconciling the candidate onto the moved canonical was out of this round's scope and was **not** done — flag it for the owner at adoption time.

---

## 8. Known limits, disclosed rather than assumed closed

Carried forward from `4f1a915` and still true, except where noted:

- **B1** — an *unknown* predicate in a clause that also carries a read marker still classifies `READS_ONLY` (e.g. "The handle is identified from the lease and thereafter designates the model process group"). Residue of `WRITE_VERBS` being a closed set.
- **B2 — now CLOSED** by the M-02 widening: "placed into a newly created controller-allocated group" is counted as a creation.
- **B3** — a co-referential write in a §3A row that never names the handle in any cell is out of scope by construction.
- **B4** — over-strict in the safe direction: an adverbial interrupting a negation ("MUST NOT, under any circumstances, be updated") breaks `_negated_spans` and classifies `WRITES` — turns the gate red on legitimate future prose, never green.
- **New, over-strict, safe direction (M-01):** a clause that both writes another field *and* names the handle without a preceding read marker is now UNCLASSIFIED even when the intent is innocent. A freeze author fixes this by splitting the sentence or by phrasing the handle reference as an explicit read. This is the deliberate cost of the repair and is pinned by `test_the_committed_running_edge_still_charges_its_write_to_the_other_field`.
- **M-02 blind spots, pinned in `test_the_group_derivation_blind_spots_are_stated_rather_than_assumed_closed`:** the derivation reads *assertions*, not references — naming an already-created group asserts no creation and is silent here (the handle dimension covers that class, as the existing `test_the_group_cardinality_dimension_has_a_stated_blind_spot` records); and a back-reference to the legitimate `CREATED -> STARTING` creation is counted as a creation (over-strict, fail-closed).
- **N-01, non-blocking, untouched:** contradicting a *restatement* of a normative rule still leaves the gate green, because the normative copy survives and is the copy that is gated. 7 instances listed in the previous review. Out of this round's hard scope; **not repaired**.
- I did **not** add a broad fail-closed arm to the group derivation. The inbox asked for the widening "without turning broad harmless prose into automatic failure", and a fail-closed arm over unknown predicates near a group noun would fire on ordinary §3A prose. The two dimensions already fail on disagreement: `assert_declared_group_count_matches_the_matrix` requires the creating row to equal §3A.3's declared write point, so a creation and a write that diverge are caught. If a reviewer wants the fail-closed arm anyway, say so and I will scope it.

---

## 9. Safety constraints — all preserved, none touched

`writes_enabled` unchanged (false) · `CROOKS_WRITES_LOCAL_OWNER` unchanged (false) · FastAPI still bound to **`127.0.0.1:8000`** (confirmed by `ss -ltnp`; no public exposure) · proposal/action/verification safety semantics unchanged · **no** live Shopify, Gmail or ElevenLabs calls and no live external mutations · V2 not begun · UI not redesigned · Mac deployment and rollback path untouched · `/root/.claude` still writable · **no secret value printed or committed** (gitleaks clean on the file and on the range; no secret is even named in the diff).

`/opt/crooks-os/crooks-assistant` was **not edited, switched or reset** — still `claude/linux-prod-migration-production` at `1cf3a0f`, `git status` clean. `crooks-assistant.service` and `crooks-bridge-watcher.service` remain `active running`; I started, stopped, installed and reloaded nothing. No production, runtime, watcher, builder, connector, credential, privilege, business-write, deployment, adoption or sequencing change was made. Nothing was merged and nothing was auto-merged.

In `/opt/crooks-ai-bridge` I have written **only** `bridge/claude-outbox.md`, and I ran no `git add`, `git commit` or `git push` there.

---

## 10. Errors, decisions and questions needing review

**Errors:** none that blocked the round. The full-suite flakiness in §6.1 is the one anomaly; it was chased to a baseline at the rejected SHA and is pre-existing.

**Decisions I made, which a reviewer should check:**

1. **A read marker defuses a handle referent only when it sits in front of it.** This is the single judgement the M-01 repair turns on. Preceding-only keeps the committed "MUST NOT be used as the cleanup handle" green while catching read-marker camouflage; a both-sides rule would have kept the camouflage case green. Both behaviours are pinned by tests.
2. **`contested` outranks `PROHIBITS_WRITE` as well as `WRITES_OTHER_FIELD`.** A clause carrying a surviving prohibition *and* a decoy-carried write is now UNCLASSIFIED. That is a new red for prose nobody has written yet; I judged fail-closed correct, per the inbox.
3. **No fail-closed arm added to the group derivation** — reasoning in §8.
4. **The candidate was not rebased** onto the moved canonical `654a9ed` — out of scope, merge-tree is conflict-free, flagged for the owner.

**Questions:** none blocking. Nothing in this round required owner approval, so none was sought, assumed or recorded.

**Not done, deliberately:** I did not self-review and I make **no** engineering-acceptance claim. Whether `de9bea2` is fit to freeze is for the next independent reviewer to decide.

---

## 11. Exact proposed next step

**One fresh, independent, read-only adversarial review bound to the exact SHA `de9bea2b040808175077777afc35c5394eb4d716`** on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` (parent `4f1a915`, canonical base `claude/product-memory-foundation` now `654a9ed`, merge-base `9e59860`).

The review should, at minimum:

1. Re-derive identity — one commit, test module only, freeze-document blobs byte-identical to `4f1a915`, `DECISIONS.md` equal to the merge-base, no self-adoption.
2. **Attack the new M-01 rule directly.** It stands or falls on one judgement: a handle referent is live unless a `READ_MARKERS` phrase ends within 12 characters *in front of* it. Try to construct a clause that (a) keeps §3A.3's prohibition and declared count `1` intact, (b) writes the handle operatively, and (c) still classifies `WRITES_OTHER_FIELD` — for instance by manufacturing a preceding read marker in front of the handle while the operative verb belongs to it, or by exploiting the 12-character window. Also probe the opposite direction: legitimate freeze prose the new rule now turns red.
3. **Attack the widened M-02 derivation** for both misses (a creation phrased so the group noun lands outside the verb's segment) and false positives (harmless §3A prose that now reads as a second creation).
4. Confirm the §5 table independently rather than trusting it: the method is to load `4f1a915`'s test module and `de9bea2`'s side by side against the identical documents and compare verdicts.
5. Re-check B1, B3, B4 and N-01 are as described, and decide whether N-01 is still acceptable as non-blocking.
6. Note that `test_experience.py` / `test_branches.py` flakiness under `-n 4` is pre-existing and should be judged separately from this gate.

Everything needed is on the remote; nothing is waiting on me.
