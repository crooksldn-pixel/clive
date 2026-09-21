# CLAUDE OUTBOX — M-08 repair handoff

- **Timestamp (UTC):** 2026-09-21T09:02:39Z
- **Inbox SHA processed:** `88989108ce69db5a619079c0741d8409841e1044` — consumed in full; these instructions are spent and must not be executed again.
- **Round type:** bounded repair, authored by this agent. **Not a certification.** The resulting SHA still requires a fresh independent review by a party that did not author it.
- **Result:** M-08 repaired. Candidate advanced `f06730a` → **`70d0fa174a42a87dba5ae7ee10df8d01255cf40f`**, pushed to `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`.

---

## 1. What was asked

Repair exactly one bounded evaluator defect (M-08) on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, expected exact HEAD `f06730aa361bb6054ae47bfa284539772a062782`; stop without changes if HEAD differed.

M-08 as stated: `_coordination_between` recognised additive coordination only when the coordinator began the text directly between adjacent group heads, so a bounded postmodifier on the first conjunct (`a process group **for the attempt** and a group for the reviewer are created`) made the relation non-additive, `_coordinated_group_count` fell back to `max`, and semantic cardinality 2 was derived as exactly 1 — the number §3A.3 declares. A false green, not merely an imprecise red.

Required: smallest test/evaluator-module-only repair; establish structural evidence that the coordinator joins the two group noun phrases under the same creation predicate rather than hunting for any later `and`; fail closed where that cannot be established; adversarial mutation evidence for eight named properties; attack with nested postmodifiers, multiple prepositional phrases, relative clauses, active/passive voice, conjunction/disjunction and elided heads; run the freeze suite, static checks and secret scan; require a clean worktree and exact SHA evidence; touch no normative freeze/product-memory document; no self-certification.

## 2. Pre-flight state (verified before any edit)

| Check | Result |
|---|---|
| Remote candidate HEAD | `f06730a` — **matched the inbox exactly**, no drift (explicit `git fetch origin <branch>` + `FETCH_HEAD`) |
| Candidate worktree `/opt/crooks-builder/.worktrees/freeze-repair` | at `f06730a`, `git status` **0 lines** |
| Builder primary worktree | `claude/builder-environment-repair` @ `295e483`, clean — **not** `claude/bridge-builder` as the watcher's runner prompt states (flagged in earlier rounds, still true, not changed) |
| Production checkout `/opt/crooks-os/crooks-assistant` | `claude/linux-prod-migration-production` @ `1cf3a0f`, clean — **not touched, not switched, not reset** |
| Freeze-spec suite at `f06730a` | **247 passed** (reproduces the recorded baseline) |

Authorship note: this agent authored `f06730a` (the M-07 repair). That is disqualifying for a *review* round and is fine for a *repair* round, which is what this inbox requested. It is restated here so the next router does not mistake this handoff for a verdict.

## 3. The defect, confirmed from source

`_coordination_between(between)` matched an additive coordinator only at token index 0 of the run between two live group nouns; anything else returned `False`, which routes `_coordinated_group_count` to `max`. For `a process group for the attempt and a group for the reviewer are created` the run is `for the attempt and a`, index 0 is `for`, so the coordination was never seen and the derived count was `max([1, 1]) = 1`.

Reproduced against the `f06730a` module itself — a scratch copy proved by `git hash-object` == `git rev-parse f06730a:<path>` = `433af64a9485ecfccf195c31df7fd035aef3e702`, reading the `f06730a` docs tree. Rewritten over the committed `CREATED -> STARTING` creation clause, the sentence leaves the creating-row count at 1 and §3A.3's declared `1` as committed, and the whole gate is **GREEN at n=1**.

## 4. What changed

**One commit, `f06730a..70d0fa1`, one file — `crooks-assistant/tests/test_orchestrator_freeze_spec.py`, +378/−17.** No freeze or product-memory document touched: all **21** `docs/product-memory` blobs are byte-identical to `f06730a`, checked blob-by-blob with `git rev-parse` / `git hash-object`.

### Evaluator — the repair itself

- New closed vocabulary `_POSTMODIFIER_PREPOSITIONS` (18 words: `of for in into on at to by with from under over upon through during against between within`). Every one is already a `_CONSTITUENT_BOUNDARIES` member, readmitted in this one position and nowhere else. Relativisers (`which/who/whom/whose/where`), subordinators (`if/when/while/unless/until/because/though/although`), comparatives (`as/than`) and coordinators are deliberately absent — what they open is a clause whose end this walk cannot find, so a coordinator behind one is unplaceable rather than additive. Pinned by an assertion.
- `_may_stand_inside_a_governed_noun_phrase(token)` — the coordinated-run vocabulary minus the coordinators themselves, so a coordinator inside a postmodifier ends the phrase instead of being swallowed by it.
- `_is_a_bounded_postmodifier(tokens)` — is this run *exactly* zero or more prepositional phrases, each a postmodifying preposition followed by at least one token that can stand inside the noun phrase it governs? A run that ends early (on a relativiser, on an auxiliary, on a preposition governing nothing) is **not** a shorter postmodifier; it is the absence of an answer.
- `_additive_coordinator_at(tokens, index)` — the existing coordinator table, matched at an arbitrary index instead of only at 0.
- `_coordination_between` rewritten. It now scans the whole run for the first additive coordinator and believes it only when the prefix is a bounded postmodifier **and** the remainder is the next conjunct's premodifiers. Otherwise it returns `None` (unknown ⇒ red), with exactly one exception: a prefix that opens with a predication auxiliary and contains no postmodifier preposition is clause coordination about one group (`a group **is created and the** group is recorded`), and stays `False`, which is what `max` is for and what the M-07 controls pin.

`_coordinated_group_count`, `group_creations`, `_asserted_group_count`, `_may_stand_inside_a_coordinated_run`, `GROUP_NOUN_RE`, `GROUP_CREATION_RE`, segmentation and both negation walks are **unchanged**.

Direction of the change is monotone toward red: a link can move `False → True` (the running total accumulates) or `* → None` (unknown), and no link can move to a *smaller* number — so this repair cannot itself introduce a new false green.

### Tests

104 → **111** test functions: **7 added, 0 removed, 0 renamed, 0 skip/xfail markers.** Exactly one assertion was removed — the line in `test_the_coordination_blind_spots_are_stated_rather_than_assumed_closed` that *pinned M-08 as an accepted limit* (`… == 1` on the postmodified shape). It is replaced by 12 mutations asserting the correct counts. The pristine control `group_creations(COMMITTED_CREATION_PROSE) == [1]` is now asserted **twice** (was once).

Every mutation rewrites the committed creation clause via `state_api_with_rewritten_prose`, so the creating-**row** count stays 1 and §3A.3's declared `1` stays as committed — the derived count is the only thing that can object. Each parametrised test asserts that confinement first.

## 5. Evidence — the `f06730a` module beside the repaired module, on the same docs

Both modules loaded in one process via `importlib.util.spec_from_file_location`; each resolves its own `DOCS` from its own path.

### 5.1 Additive family — now counted, at the semantic number (committed as tests)

| Mutation | `f06730a` | `70d0fa1` |
|---|---|---|
| `a process group for the attempt and a group for the reviewer are created` | **GREEN n=1** | **RED n=2** |
| `two process groups for the attempt and another group for the reviewer are created` | RED n=2 *(wrong number)* | **RED n=3** |
| `two process groups for the attempt and three cgroups for the reviewer are created` | RED n=3 *(wrong number)* | **RED n=5** |
| active voice: `the controller creates a process group for the attempt and a group for the reviewer` | **GREEN n=1** | **RED n=2** |
| active voice, quantified first conjunct | RED n=2 *(wrong number)* | **RED n=3** |
| two prepositional phrases on the first conjunct | **GREEN n=1** | **RED n=2** |
| a postmodifier nested inside a postmodifier | **GREEN n=1** | **RED n=2** |
| a possessive inside the postmodifier | **GREEN n=1** | **RED n=2** |
| `as well as` behind a postmodifier | **GREEN n=1** | **RED n=2** |
| `plus` behind a postmodifier | **GREEN n=1** | **RED n=2** |
| three postmodified conjuncts | **GREEN n=1** | **RED n=3** |
| postmodifier on the second conjunct only | RED n=2 | RED n=2 *(regression control, unmoved)* |

Nine green→red; three that were already red were red at the **wrong** number (`max` = the larger conjunct, not the total) and are now pinned to the total.

### 5.2 Fail-closed family — unknown, never an assumed one (committed as tests)

| Mutation | `f06730a` | `70d0fa1` |
|---|---|---|
| `the controller creates a process group for the attempt and records the group for cleanup` *(the inbox's required case — one group, one `and`)* | **GREEN n=1** | **RED, unknown** |
| relative clause on the first conjunct (`which is owned by the attempt and a group …`) | **GREEN n=1** | **RED, unknown** |
| predicate interposed before the postmodifier (`is created for the attempt and a group …`) | **GREEN n=1** | **RED, unknown** |
| `and/or` behind a postmodifier | **GREEN n=1** | **RED, unknown** |
| subordinate clause on the first conjunct (`when cleanup is proven and …`) | **GREEN n=1** | **RED, unknown** |
| unquantified second conjunct (`and several groups for the reviewer`) | RED, unknown | RED, unknown |

### 5.3 The direction that must not move — postmodified same-entity references (committed as tests)

All **GREEN n=1** at both SHAs: appositive behind a postmodifier; disjunction behind a postmodifier; relative clause behind a postmodifier; prepositional back-reference (`… is created inside that group`); a comma between the creation and the back-reference; ordinary singular normative creation carrying a postmodifier (`the attempt's single owned process group for that attempt is created`).

### 5.4 Prior rounds unmoved

All 12 M-07 families give **identical verdicts and identical counts** before and after: the five additive mutations (n=2/3/3/2/2), the unplaceable run (unknown), the five same-group-named-twice controls (GREEN n=1), and the comma-split under-count (RED n=2). The committed clause is **GREEN n=1** at both SHAs. Suite-wide, the M-01…M-06, L-01, K-01, J-01, H-03/H-04 and R-02 tests all pass unchanged — the 247 tests at `f06730a` are a subset of the 275 here, with no test removed, renamed or weakened.

### 5.5 Extra adversarial probe — 25 shapes NOT in the committed tests

Newly red and correct: three stacked prepositional phrases (n=2); an of-genitive chain (n=2); `to` and `within` postmodifiers (n=2); a prepositional phrase on the verb in active voice (n=2); `along with` and `together with` behind a postmodifier (n=2). Newly red as fail-closed unknown: a postmodifier with a cardinal inside; a postmodifier governing a bare plural; a participial postmodifier (`owned by the attempt and …`); a bare relative; a `that`-relative; the gapped passive. Green and correct throughout: postmodifier + `or` + postmodifier; postmodifier + back-reference via `inside`; a postmodifier naming a second entity; a negated second conjunct; `without` on the second conjunct.

## 6. Limits — stated, pinned by tests, not assumed closed

**(a) Two new false *reds* (fail-closed, accepted).** Where a predicate stands between the first group noun and the coordinator *and* a postmodifier stands between that predicate and the coordinator, the second conjunct could equally be a gapped noun phrase or a new predication, and this window cannot draw the distinction. So `a process group is created for the attempt and the group is recorded` and `a process group for the attempt is created and the group runs preflight` are now **unknown (red)** rather than one. Neither occurs in the committed text, whose one creation segment holds one group noun and no coordinator. The no-postmodifier form of both is still green at one.

**(b) TWO MATERIAL UNDER-COUNTS FOUND WHILE ATTACKING M-08, LEFT OPEN DELIBERATELY — read this before reviewing.** Both derive exactly the declared `1` from prose that creates two groups, i.e. they are the same severity class the inbox used to justify M-08. Both are a **different mechanism** than the coordination rule and both predate this repair — identical behaviour at `f06730a` and at every SHA before it. Each is pinned by `test_two_under_counts_outside_the_coordination_rule_are_recorded_as_still_open`.

1. **Segmentation.** `_segment_bounds` ends a creation verb's segment at a comma or semicolon, so a conjunct on the far side of one is never in the verb's segment. `a process group, and a group for the reviewer are created` → **derives 1, gate GREEN.** Same for `a process group, for the attempt, and a group for the reviewer are created` and for the semicolon form. The three-conjunct form the M-07 repair disclosed (`a process group, another group and a third group are created`) under-counts 3 as 2 and *does* still fail a declared 1 — so **the inbox's premise that "comma-separated coordination remains red" holds for three conjuncts and does not hold for two.** The fix is the constituent the segment stands for (a comma-delimited conjunct list is one noun phrase), not the coordination rule.
2. **Elided heads.** A conjunct may omit the head noun — `a process group for the attempt and another for the reviewer are created` — and `GROUP_NOUN_RE` has nothing to match, so the segment holds one group noun and derives **1, gate GREEN.** Counting it needs the elided head recovered from the first conjunct, which is a question about the noun phrase, not about the coordinator.

I did not repair either: the inbox scoped this round to the postmodified first conjunct and to the smallest repair, and both fixes touch machinery (`_segment_bounds`, `GROUP_NOUN_RE`) that every M-03…M-07 behaviour depends on. **Recommended as M-09 (segmentation) and M-10 (elided heads), in that order.**

**(c) Minor, safe direction, not pinned.** `no process group for the attempt nor a group for the reviewer is created` derives 1 — `nor` is a `_CREATION_NEGATORS` member but not a `_NEGATING_PREPOSITIONS` member, so it does not defuse the second conjunct's noun phrase. This under-counts a *denial*, so it cannot conceal a creation; it can only leave the gate green on a document that says zero where it declares one. Unchanged by this repair.

**(d) Carried forward unchanged from earlier rounds:** the M-07 deliberate false-red (`_coordination_between` returning `None` rather than `False` for `and records the`); and the pre-existing false red on `a process group for the attempt, the group the handle names, is created` (RED n=0 at both SHAs, a comma consequence).

## 7. Gates run

| Gate | Result |
|---|---|
| Freeze-spec suite at `70d0fa1` | **275 passed** (247 at `f06730a`, +28) |
| `ruff check app config scripts tests` | **All checks passed** |
| Full offline suite `pytest tests -m "not live" -q -n 4` | **3080 passed / 8 skipped / 1 failed** in 233.7 s |
| — the 1 failure | `tests/test_experience.py::test_a_record_reached_by_tapping_is_still_held_a_moment_later`, the **known `-n 4` load flake**; the file passes **85/85 alone** immediately afterwards (216 s). Reconciles exactly against `f06730a`'s recorded 3051 passed / 8 skipped / 2 failed: 3053 → 3081 total tests = **+28**, the freeze-suite delta, with one of the two previous flakes passing this time. |
| gitleaks 8.30.1, changed file | no leaks found |
| gitleaks 8.30.1, range `f06730a..70d0fa1` | no leaks found |
| `git merge-tree --write-tree 70d0fa1 654a9ed` (canonical `claude/product-memory-foundation`) | exit 0, conflict-free, tree `535828a433fc39d0e53f89ddb1ae424f4339d671` |
| Candidate worktree `git status` after commit and push | **0 lines** |

Canonical base is still `654a9ed`, resolved by `ls-remote` rather than from the stale local `origin/*` tracking ref.

## 8. Service and server state (observed read-only; nothing started, stopped or changed)

- `crooks-assistant`: **active**. `crooks-bridge-watcher`: **active**.
- FastAPI listener: `127.0.0.1:8000` only, pid 217827. Port 8000 has **no** non-loopback listener.
- `CROOKS_WRITES_ENABLED=false` and `CROOKS_WRITES_LOCAL_OWNER=false` in the production `.env`; `config/settings.py` has `writes_enabled: bool = False`. Unchanged.
- No live Shopify, Gmail or ElevenLabs call, no external mutation, no deployment, no merge, no V2 work, no UI change, no systemd/watcher/connector/MCP change, no privilege change, and no secret read, printed or committed. Mac deploy/rollback path untouched. `/root/.claude` still writable.
- `/opt/crooks-os/crooks-assistant` remains on `claude/linux-prod-migration-production` @ `1cf3a0f`, clean. The remote production ref is `claude/linux-prod-migration-review` @ `1cf3a0f` (there is no `…-production` and no `main` on this remote).
- The scratch directory used for the before/after driver was deleted after the run; no evidence was left outside this handoff.

## 9. Errors and blockers

None. Nothing required the owner's approval, nothing was blocked by the permission layer, and no permission was widened. No approval is claimed or implied anywhere in this round.

## 10. Decisions needing review

1. **The two material under-counts in §6(b) were found by me and left open.** A reviewer should decide whether that scoping was right or whether M-09 should have been folded into this round. My reasoning is in §6(b); each is pinned by a test, so the decision is auditable either way.
2. **The one relation that still collapses on an unplaceable coordinator** — a predication opening the run with no postmodifier in it returns `False`, not `None`. This is the single line most worth an adversary's judgement, because it is the only place where an unreadable coordinator is answered with a number instead of with "unknown". It is retained because `a group is created and the group is recorded` is one group and the M-07 controls pin it green. Attack it.
3. **The inbox's stated premise "comma-separated coordination remains red" is true for three conjuncts and false for two** (§6(b)(1)). The required-evidence list should be corrected before the next round is written.
4. **Bridge routing, unchanged and still unresolved.** The bridge has no reviewer-identity check. This round was a repair and was correctly routed; the *review* of `70d0fa1` must not come back to this agent. Four consecutive review rounds have been mis-routed here.

## 11. Exact proposed next step

**One fresh independent adversarial review bound to exactly `70d0fa174a42a87dba5ae7ee10df8d01255cf40f`, by a party that did not author it — route it to ChatGPT, not to a Claude session on this machine** (a fresh session here would see the commit as a stranger's work and would not detect that it is not).

Give that reviewer this attack list:

- `_is_a_bounded_postmodifier`'s "exactly" condition — find a run it accepts that is not a postmodifier, or one it rejects that is.
- The `False` arm of `_coordination_between` (decision 2 above): find a two-group sentence whose run opens with a predication auxiliary and contains no postmodifier preposition.
- `_POSTMODIFIER_PREPOSITIONS` as a closed set — a postmodifying preposition of this prose that is missing (under-count), or a member that can open a clause (over-red).
- The interaction of the new unbounded coordinator scan with `_may_stand_inside_a_coordinated_run`, with `_asserted_group_count`'s leftward walk, and with the `_GOVERNMENT_WORD_LIMIT = 8` bound.
- Whether §6(b)(1) and §6(b)(2) are correctly scoped out, and whether either has a smaller safe fix than the one described.
- Re-verify independently: 275 green, ruff, gitleaks, docs-blob identity, one-commit scope, `merge-tree` against canonical `654a9ed`, and that no earlier round's protection was weakened.

Nothing in this round adopts, merges, deploys or sequences anything.
