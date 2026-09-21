# CLAUDE OUTBOX — Orchestrator V1 freeze evaluator, bounded repair of M-03 + M-04

**Timestamp:** 2026-09-21T01:12Z
**Inbox consumed:** yes — `/opt/crooks-ai-bridge/bridge/chatgpt-inbox.md`, blob SHA
`97f375f17303de11d981ab2e5d134fcd9cca9010`, read in full and treated as this round's sole
instruction set. Recorded here so the same instructions are never executed twice.
**Round type:** bounded repository-only repair.
**Result:** REPAIRED AND PUSHED — `2ee1836c976ba9a9cefbf188763d1de0da0cc44e`. Not self-certified.

---

## 1. What was asked

One bounded repair round on `crooksldn-pixel/clive`, branch
`chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, off the rejected SHA
`de9bea2b040808175077777afc35c5394eb4d716`, changing only
`crooks-assistant/tests/test_orchestrator_freeze_spec.py`:

- **M-03** — make the authoritative cardinality checks count semantic assertions instead of
  distinct transition rows; add regressions for same-row complete handovers in explicit/backticked
  and natural-language alias forms, plus pristine controls.
- **M-04** — require negation to *govern* the creation assertion it suppresses; a principled local
  rule rather than a phrase list; preserve the committed document's genuine denials; catch
  `created … without delay`, `created … and not for preflight`, and a preceding unrelated condition
  such as `if cleanup cannot be proven … a second process group is created`; ambiguous critical
  semantics must fail closed.
- Preserve M-01/M-02, J-01/H-03/H-04/R-02/K-01/L-01 and earlier invariants; remove, skip, weaken or
  rename nothing; add adversarial combinations beyond the review's examples plus false-positive
  controls.
- Report exact SHA and parent, changed-file scope, clean worktree, freeze-document byte identity,
  tests/static checks, before/after mutation evidence, accurate counts, and remaining uncertainty.
  Commit and stop; do not review or certify the repaired SHA.

## 2. State found before acting

- Builder base checkout `/opt/crooks-builder`: branch `claude/builder-environment-repair`, HEAD
  `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, **0 dirty lines**, nothing untracked. Untouched by
  this round.
- Candidate worktree `/opt/crooks-builder/.worktrees/freeze-repair`: branch
  `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, HEAD
  `de9bea2b040808175077777afc35c5394eb4d716`, **0 dirty lines**, nothing untracked.
- Resolved fresh: `git fetch origin chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` gave
  `FETCH_HEAD` = `de9bea2b040808175077777afc35c5394eb4d716` — **matches the inbox's exact rejected
  SHA**, so the round proceeded rather than stopping.
- Production checkout `/opt/crooks-os/crooks-assistant`: branch
  `claude/linux-prod-migration-production`, HEAD `1cf3a0f3361b79f9de208d80f501543c53c244b5`, 0 dirty
  lines. **Never edited, switched or reset.**

## 3. What I found — both defects confirmed by measurement, not accepted on report

**M-03 — a transition row is not the unit §3A.3 declares.** Both
`attempt_rows_writing_the_cleanup_handle` and `attempt_rows_creating_an_owned_process_group`
accumulated rows under `if row not in rows`, and both `assert_declared_…_matches_the_matrix`
compared `len(rows)` against the declared count of `1`. The classifier was never fooled — on a
same-row handover it emitted a second `WRITES`, and `_asserts_a_group_creation` returned `True` —
the aggregation discarded the evidence. Measured against the rejected gate: a complete two-group
handover appended entirely inside the legitimate `CREATED -> STARTING` cell left **both dimensions
green**, with §3A.3's prohibition sentence and declared count `1` intact.

**M-04 — presence of a negator is not government.** `_asserts_a_group_creation` skipped a creation
verb whenever `CREATION_NEGATION_RE` matched anywhere in that verb's own `[,:;]` segment. Measured
against the rejected gate, every one of these was **green**: `a second … process group is created
for the model without delay`; `… and not for preflight`; `If cleanup cannot be proven a second …
process group is created here`; `… is created here and never reused afterwards`; `With no further
approval a second … process group is created`. In each case the negator governs something other
than the creation.

## 4. What I changed

One commit, **test module only**, no freeze document touched.

### M-03 — count assertions, not rows

- `classify_handle_clause` split into `_classify_handle_clause(clause, established) ->
  (verdict, writes)`. The public name and signature survive as a one-line wrapper, so the committed
  `pytest.raises(match=…)` tests and every direct verdict assertion are untouched.
- New `classified_handle_clauses` (4-tuples, carrying the count); `classified_handle_mentions` is
  now a thin projection of it, so its callers and its pinned output shape are unchanged.
- New `cleanup_handle_write_assertions(api_text)` and
  `owned_process_group_creation_assertions(api_text)` — one entry per asserted write / creation.
- `assert_declared_write_point_matches_the_matrix` and
  `assert_declared_group_count_matches_the_matrix` each gained **one** assertion comparing the
  declared count against the assertion count. **Both are placed last, after the existing row-level
  assertions**, deliberately: every mutation pinned by the earlier rounds still fails on its own
  original diagnostic message, so no committed `match=` expectation had to be edited.
- Within-clause multiplicity: a `WRITES` clause counts `max(1, independent write verbs)`. Two
  structural discounts, both forced by the committed matrix itself — a permission modal governing
  the verb (`the only edge that **may write** the cleanup handle`) and a noun-phrase determiner
  heading the token (`in this same **commit**`, where `commit` is in `WRITE_VERBS` because the verb
  is). The pristine write clause carries two `WRITE_VERBS` tokens and asserts one write; a test
  pins exactly that.

### M-04 — negation must govern what it suppresses

`CREATION_NEGATION_RE` is replaced by a constituent-aware rule. A negator suppresses a creation only
when it lies inside one of the two constituents a denial can attach to:

1. **the creation verb's own predication** — `_negation_governs_the_predication` walks left from the
   verb through its auxiliary/modal/adverb chain, then into the subject noun phrase that chain
   belongs to, and **stops at that phrase's determiner** or at a constituent-boundary word. That is
   what keeps `cannot` in `if cleanup cannot be proven a second process group is created` away from
   `created` — the walk halts at the determiner `a`. It still catches `MUST NOT create`, `never
   creates`, `is never created`, `no second group is created`, `no group was ever created`.
2. **the created group's own noun phrase** — `_negation_governs_the_noun_phrase` walks left through
   the phrase's modifiers to its determiner and is then allowed exactly **one** further step, onto a
   negating preposition. This preserves `provisioned without a new process group` while leaving
   `is created for the model without delay` — where `without` governs `delay` — a real creation.

Anything else is a negator speaking about something else in the segment, and the creation stands:
the fail-closed direction. `_asserts_a_group_creation` keeps its name, signature and meaning and is
now `bool(group_creation_assertions(clause))`.

### Tests added

11 new test functions, 26 new collected cases, **additions only**: same-row handovers in
explicit/backticked, alias and decoy-field forms; each half of the handover alone, so neither
dimension can be credited with the other's catch; a same-*clause* second write; the pristine
one-write/one-creation control with the two-token measurement pinned; the five ungoverned-negation
forms; the M-03 × M-04 cross; the government rule asserted as a property (`cannot`, `without` and
`never` each deciding both ways purely on what they govern, plus both walks called directly at the
offsets the gate uses); eight genuine-denial controls; three legitimate-prose controls inside the
creating row; and an explicit statement of the fail-closed over-counting this rule costs.

The M-04 mutations are placed on `RUNNING -> CANDIDATE_READY` on purpose: that row names the cleanup
handle nowhere and carries no byte-level pin, so the write dimension is silent by construction and
the group cardinality is provably the only guard. The tests assert the write dimension still passes
there, so the catch cannot be attributed to the wrong dimension.

## 5. Result identity

| | |
|---|---|
| Repaired SHA | `2ee1836c976ba9a9cefbf188763d1de0da0cc44e` |
| Parent | `de9bea2b040808175077777afc35c5394eb4d716` |
| Branch | `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` — pushed, remote tip verified `2ee1836` |
| Commits since `de9bea2` | 1 |
| Files changed | exactly 1 — `crooks-assistant/tests/test_orchestrator_freeze_spec.py`, **+618 / −31** |
| Worktree after the round | clean, `git status --porcelain` = 0 lines, nothing untracked |
| Freeze documents | **all 21 `docs/product-memory` blobs byte-identical to `de9bea2`**, each verified `git rev-parse de9bea2:<path>` == `git hash-object <path>`. `ORCHESTRATOR_V1_STATE_API.md` still `189601e8a6b6f468aa87cd87096037014ffb3929`; `DECISIONS.md` still `a6dc313173bca86e139ebb5acd221753f1aaaeff` |
| Canonical base | `claude/product-memory-foundation` = `654a9ed7d790e38597a3c5852d9b3e0a42902a1a`, unchanged since the last round; `9e59860` still an ancestor; merge-base(HEAD, canonical) = `9e59860a945ec339c69af8709cd0721f0a795327`; `git merge-tree --write-tree 2ee1836 654a9ed` exits 0 → **conflict-free**, tree `06d0b64c96e7847a508cab901d7ca9f07ee0a3ae` |

## 6. Test and static-check results

- **Freeze spec suite: 170 passed** in 1.9 s (144 at `de9bea2`).
- **Accounting, measured rather than claimed** (the previous round's bookkeeping did not reproduce,
  so every number here comes from a command):
  - `grep -c '^def test_'`: **73 → 84**.
  - `comm -23` of the sorted old/new `^def test_` lists: **0 removed, 0 renamed**. `comm -13`: **11
    added**.
  - `git diff -U0 | grep -E '^-\s*assert'`: **zero deleted assert lines**.
  - `pytest.mark.skip` / `pytest.mark.xfail` / `pytest.skip` / `pytest.xfail` in the file: **0**.
  - `--collect-only`: **170 tests collected** (144 → 170, +26).
- **`ruff check app config scripts tests`: All checks passed.** (`ruff format` is not a repo gate and
  was deliberately not run.) No line I added exceeds 101 characters, within the file's existing
  norms.
- **gitleaks 8.30.1:** clean on the changed file, and clean on the range `de9bea2..2ee1836`.
- **Full offline suite** (`pytest tests -m "not live" -q -n 4`) in the candidate worktree:
  **2974 passed / 8 skipped / 2 failed** in 3 m 10 s.
  - The two failures are `tests/test_experience.py::test_a_record_is_only_replayed_to_the_conversation_it_was_shown_to`
    and `::test_a_record_reached_by_tapping_is_still_held_a_moment_later`.
  - **Proved pre-existing.** A throwaway detached worktree at the parent SHA `de9bea2`, same
    command, produced **the identical two failures**: `2 failed, 2947 passed, 8 skipped, 1 error` —
    the error being the known `-n 4` `delta.py` `os.replace` race on
    `test_the_golden_scenarios[back]`. On the repaired tree `tests/test_experience.py` run alone:
    **85 passed**. The throwaway worktree was removed and the worktree list is back to three.
  - **The delta reconciles exactly:** 2947 baseline + 1 (the case that errored on the race at
    `de9bea2` and passed here) + 26 new collected cases = 2974.

## 7. Before/after mutation evidence for both blockers

Measured by loading the `de9bea2` module and the repaired module side by side against
**byte-identical documents**. Provenance proved by hash: the reconstructed old module hashes to
`d58398c92273492f161ab79dceee0db7adae5099` == `git rev-parse de9bea2:crooks-assistant/tests/test_orchestrator_freeze_spec.py`,
and `ORCHESTRATOR_V1_STATE_API.md` hashes to `189601e8…` identically in the scratch, at `de9bea2`
and in the live worktree. Every mutation leaves §3A.3's prohibition sentence and the declared count
`1` intact — asserted inside the harness, so a mutation that broke another dimension would not be
counted as evidence. `PASS` means the gate **accepted** the mutated document: the false green.

### M-03 — appended inside the legitimate `CREATED -> STARTING` cell

| Mutation | `de9bea2` write / group | `2ee1836` write / group |
|---|---|---|
| complete handover, backticked handle | PASS / PASS | **RED / RED** |
| complete handover, natural-language alias | PASS / PASS | **RED / RED** |
| complete handover, decoy field beside the alias | RED (M-01 fail-closed) / **PASS** | RED / **RED** |
| second creation only | PASS / PASS | PASS (silent by design) / **RED** |
| second write only | PASS / PASS | **RED** / PASS (silent by design) |
| second write in the **same clause** | PASS / PASS | **RED** / PASS |

For every case above the row-level derivations still report exactly one writing row and one creating
row — asserted in the committed tests, because that is precisely what row-counting cannot see.

### M-04 — appended to `RUNNING -> CANDIDATE_READY` (no handle context, no byte pin)

| Mutation | `de9bea2` | `2ee1836` |
|---|---|---|
| `… is created for the model without delay` | PASS / PASS | PASS (silent) / **RED** |
| `… is created for the model and not for preflight` | PASS / PASS | PASS / **RED** |
| `If cleanup cannot be proven a second … group is created here` | PASS / PASS | PASS / **RED** |
| `… is created here and never reused afterwards` | PASS / PASS | PASS / **RED** |
| `With no further approval a second … group is created` | PASS / PASS | PASS / **RED** |
| M-04's device at M-03's placement (the cross) | PASS / PASS | PASS / **RED** |

### False-positive controls — green on both gates, and are

Legitimate unrelated-field write inside the creating row; read-only handle reference inside the
creating row; `The controller MUST NOT create a second process group for the model`; `A second owned
process group is never created on this edge`; `A replacement workspace is provisioned without a new
process group, reusing the existing one`; `A new fencing token is created for the correction, and a
new lease is established`. **All six: PASS / PASS on both gates.** The committed matrix's three
genuine denials (`no second group is created`, `no owned process group has been created`, `A NULL
handle means no group was ever created`) all still read as denials, and the pristine document
derives **exactly 1 write assertion and exactly 1 creation assertion**.

## 8. Service and server state — unchanged by this round

- FastAPI listening on **`127.0.0.1:8000` only**, confirmed by `ss -ltn`. No `0.0.0.0:8000`, port
  8000 not exposed publicly. The other listeners are sshd, systemd-resolved and tailscaled, all
  pre-existing.
- No service installed, started, stopped or reconfigured. No Tailscale route activated. No secret
  provisioned, read or printed — **no secret value appears anywhere in this outbox.**
- `writes_enabled` still false; `CROOKS_WRITES_LOCAL_OWNER` still false; proposal/action/verification
  safety semantics untouched. This round changed a test module and nothing else.
- No live Shopify, Gmail or ElevenLabs call; no live external mutation. V2 not begun. UI not
  redesigned. Mac deployment and rollback path preserved. `/root/.claude` still writable.
- Nothing merged, nothing deployed, no auto-merge. `/opt/crooks-os/crooks-assistant` was not edited,
  switched or reset.

## 9. Errors

None. Nothing was blocked by the permission layer, and no permission was widened.

## 10. Remaining uncertainty — disclosed, not hidden

1. **I must not review this SHA.** My own memory records me as the author of the `de9bea2` repair and
   of this one. The next round must be a fresh adversarial review by an agent that did not write the
   code.
2. **M-04 is over-strict in the fail-closed direction, and a committed test says so.** A negator that
   reaches the creation through neither constituent is treated as unrelated, so two shapes are
   counted as creations although a human would read them as denials: negation of the *placement*
   (`the model process is not placed into a newly created … group` — the group is still asserted to
   exist) and a negator separated from the creation by a whole intervening predication. Both can turn
   the gate red on prose that meant no harm; neither can make it green.
3. **The `-ly` adverb rule is by shape, not by lexicon.** A non-adverb ending in `ly` standing between
   a negator and a creation verb would let that negator through. I found no such word in the
   committed matrix, but this part of the rule is heuristic where the rest is enumerated.
4. **Within-clause write counting rests on two structural discounts**, permission modals and
   noun-phrase determiners, both forced by committed prose. A future legitimate write clause phrased
   so that a `WRITE_VERBS` *noun* escapes the determiner test would be counted as a second write —
   over-strict, fail-closed, never silent. The floor of one write per `WRITES` clause guarantees the
   discounts can never take a clause below the count it already had.
5. **Carried forward from `de9bea2`, not addressed (outside this round's scope):** the
   `STARTING -> RUNNING` cell is effectively byte-pinned, so a legitimate unrelated-field write and a
   genuine read both go red on the pins although the classifier accepts them correctly; the noun
   "record" is lexically in `WRITE_VERBS`, so `a measurement record is created…` fails closed as
   UNCLASSIFIED; blind spot B1 (`READ_MARKERS` matching ordinary words such as "against") is still
   live but is not exploitable without a creation.
6. **The full offline suite has two genuinely flaky `test_experience.py` cases under `-n 4`.** I
   reproduced them at the parent SHA to show they are not mine, and they pass 85/85 when that file
   runs alone, but they are not *fixed* and will reappear on a loaded box.
7. **The candidate has not been reconciled with canonical.** `654a9ed` is a clean fast-forward
   descendant of the merge-base and `merge-tree` is conflict-free, but the overlap on
   `CURRENT_TRUTH.md` and `ROADMAP.md` is a real merge the owner should see at adoption time.

## 11. Decisions or questions needing owner review

Nothing in this round required the owner's approval, and none was assumed, inferred or recorded. To
be explicit about what was **not** done and is **not** authorised: no merge to any production
branch, no deployment, no runtime change, no business action, and **no freeze adoption**. The freeze
candidate remains a candidate.

## 12. Exact proposed next step

**One fresh, independent, read-only adversarial review bound to the exact SHA
`2ee1836c976ba9a9cefbf188763d1de0da0cc44e`, performed by an agent that did not author it.**

That review should, at minimum:

1. Re-verify identity: exactly one commit off `de9bea2`, test-module-only, all 21
   `docs/product-memory` blobs byte-identical, `DECISIONS.md` == merge-base `9e59860`, no
   self-adoption.
2. Reproduce 170 passed, ruff clean, gitleaks clean on the range, and the 73 → 84 / 0-removed /
   0-deleted-assert accounting **independently**, rather than trusting §6 above.
3. Attack **M-03 at sub-clause granularity** — `_is_an_independent_write_assertion` is the newest and
   least exercised code in the repair, and its two discounts are the obvious next escape.
4. Attack **M-04's two walks** — specifically bare plurals with no determiner to stop on, negators
   reaching across an `-ly` word, and any denial shape in plausible future freeze prose that sits in
   neither the verb's predication nor the group's noun phrase.
5. Check that placing the new assertions **last** really did preserve every earlier round's
   diagnostic, rather than merely appearing to.

**Do not treat this outbox as certification.** Nothing in it is a verdict on its own SHA.

**Inbox SHA processed: `97f375f17303de11d981ab2e5d134fcd9cca9010`.**
