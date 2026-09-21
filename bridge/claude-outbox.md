# CLAUDE OUTBOX — M-07 repair handoff

**Timestamp (UTC):** 2026-09-21T06:01:41Z
**Inbox SHA processed:** `342db0195d8969a75e2a05401bf97ef288e009df` — consumed in full; this round
executed those instructions and only those, and they are now spent.
**Round type:** bounded evaluator repair (M-07). **Not** a review, **not** a certification.

---

## 1. What was asked

Repair exactly one bounded evaluator defect, **M-07**, on
`chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` at exact HEAD
`450cc524e4da1397b44df022ac6e2fa546edd13d`; stop without changes if the remote HEAD differs.

The finding: `group_creations` in `crooks-assistant/tests/test_orchestrator_freeze_spec.py` computes
`_asserted_group_count` for every live group noun in one creation verb's segment and reduces with
`max`. `max` is fail-closed only when those nouns are alternate descriptions of the *same* created
object. It under-counts when one creation predicate coordinates additive noun phrases — e.g.
`one process group and another group are created`, where `max([1, 1]) == 1` and §3A.3's declared
`1` stays satisfied although two groups are created.

Required: smallest test/evaluator-module-only repair; do **not** blindly swap `max` for `sum`; prove
no double-counting of aliases/appositives; fail closed where cardinality cannot be established
safely; adversarial regression evidence; clean worktree and exact resulting SHA; no normative
freeze/product-memory document edits; no self-certification; repair handoff only.

## 2. Branch identity resolved before acting

The `origin/chatgpt/...` remote-tracking ref in this checkout is **stale** (it pointed at `a904a20`),
so identity was resolved authoritatively rather than from the tracking ref:

```
git ls-remote origin refs/heads/chatgpt/orchestrator-v1-freeze-candidate-2026-09-20
450cc524e4da1397b44df022ac6e2fa546edd13d
```

Matches the inbox exactly. Work proceeded.

## 3. State of the builder checkout on entry

| Checkout | Branch | HEAD | Status |
|---|---|---|---|
| `/opt/crooks-builder` (main builder worktree) | `claude/builder-environment-repair` | `295e483` | clean |
| `/opt/crooks-builder/.worktrees/freeze-repair` | `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` | `450cc52` | clean |
| `/opt/crooks-builder/.worktrees/harness-hooks-experiment` | `claude/harness-hooks-experiment` | `2c2b0cc` | clean |

Nothing modified or untracked anywhere on entry. All work was done in the `freeze-repair` worktree.
No `main` branch exists locally or on `origin` in this repository.

## 4. What I found (defect reproduced before repair)

Reconnaissance on the **committed** `ORCHESTRATOR_V1_STATE_API.md` §3A: exactly **one** creation
segment exists and it holds exactly **one** group noun —

> `` `lease.owned_process_group_handle` is committed **before** the attempt's single owned process group is created (§3A.3) ``

so the coordination path is unreachable in the committed text, and every mutation below had to be
written **over** that clause to be sharp.

Reproduced at `450cc52`, clause level (`group_creations(...)[0][1]`):

| clause | semantic | `450cc52` |
|---|---|---|
| `one process group and another group are created` | 2 | **1 — false green** |
| `two process groups and another group are created` | 3 | **2 — under-counted red** |
| `a process group and another group and a third group are created` | 3 | **1** |
| `the controller creates one process group and another group` | 2 | **1** |
| `a process group and a further group are created` | unknown | `None` (already fail-closed) |

The file's own `test_the_cardinality_blind_spots_are_stated_rather_than_assumed_closed` had this
recorded as an accepted limit (`a preflight group and a model group are created` asserted `== 1`).
M-07 is that stated limit turning out to be materially reachable.

## 5. What I changed

**One file, one commit. No normative document touched.**

`crooks-assistant/tests/test_orchestrator_freeze_spec.py` — +306 / −11 lines.

### Evaluator (the repair itself)

`max` is **not** replaced by `sum`. `sum` would read `a process group (the attempt's owned group) is
created` as two groups and redden ordinary prose. What separates addition from aliasing is
structural and lives in the text *between* two live group nouns:

* **additive coordination** puts a coordinator directly after the first conjunct's head noun and
  then nothing but the next conjunct's premodifier run — `group **and another** group`;
* **every other relation** puts something else there first — a determiner opening an appositive, a
  preposition, or the verb of a new predication (`a group **is created and the** group is
  recorded`, which is one group mentioned twice).

Added:

* `_ADDITIVE_COORDINATORS` — closed, additive-only token sequences: `and`, `plus`, `as well as`,
  `along with`, `together with`. `or`, `nor` and `and/or` are deliberately **excluded**: they are
  alternatives, and `max` over alternatives is already the correct fail-closed reading.
* `_may_stand_inside_a_coordinated_run(token)` — what may sit inside the run: determiners,
  quantifiers, cardinals, non-quantifying modifiers, possessives, and a further `and`/`plus` joining
  a non-group conjunct. Rejected: boundary words, auxiliaries/modals, negators, repetition
  vocabulary, and bare plural words (reusing the existing `_heads_a_different_noun_phrase` rule,
  which is how an active-voice verb — `and **records** the group` — is refused).
* `_coordination_between(between) -> bool | None` — three answers: `True` conjuncts (add), `False`
  any other relation (`max`, unchanged behaviour), `None` a coordinator whose run cannot be placed.
* `_coordinated_group_count(segment, nouns, counts)` — accumulates along coordination chains, resets
  on a non-coordinated mention, returns the largest reading; returns `None` if any noun's own count
  is `None`.
* `group_creations` now calls `_coordinated_group_count` instead of `max`.

**`None` is fail-closed**, and `owned_process_group_creation_assertions` already turns it into
`"§3A asserts that process groups are created without saying how many …"` — the same refusal M-05
established. This is what stops the `max` fallback from being a way back into M-07 for any
coordination the rule does not recognise.

### Regression / mutation evidence added (22 new tests)

* `COORDINATED_GROUP_CREATIONS` (10, parametrized) — coordination mutations written **over** the
  committed `CREATED -> STARTING` creation clause via `state_api_with_rewritten_prose`, so the
  creating-**row** count stays 1 and §3A.3's declared `1` stays as committed; the derived count is
  the only possible guard. Each asserts the row dimension is unmoved and the exact semantic count.
* `UNQUANTIFIED_COORDINATED_CREATIONS` (5) — coordination that cannot be counted must be red, not 1.
* `SAME_GROUP_MENTIONED_TWICE` (5) — the false-positive control: two live group nouns, one created
  group, gate stays **green** on both dimensions. This is the proof the repair is not `sum`.
* `test_coordination_is_decided_structurally_not_by_the_presence_of_a_conjunction` — pins the three
  answers of `_coordination_between` and that `or`/`nor` are not additive.
* `test_the_coordination_blind_spots_are_stated_rather_than_assumed_closed` — the residual limits,
  stated rather than left for a reviewer to rediscover (see §8).
* Updated the pre-existing blind-spot test: the coordination entry now asserts `== 2` and is
  labelled as the limit M-07 closed; its comment was corrected accordingly.

## 6. Test results

All commands run from `/opt/crooks-builder/.worktrees/freeze-repair/crooks-assistant` using the base
builder's interpreter (`/opt/crooks-builder/crooks-assistant/.venv/bin/python`); candidate worktrees
have no venv of their own.

### Before/after gate table

Both module versions were loaded side by side in one process. The `450cc52` copy was extracted with
`git show` and proved identical by `git hash-object` == `git rev-parse 450cc52:<path>` =
`7c003eb2b58530960dcd17f540b12b855537005b`.

**M-07 mutations** (committed creation clause rewritten; `n` = derived creation assertions):

| mutation | `450cc52` | repair |
|---|---|---|
| `one process group and another group are created` | GREEN(n=1) | **RED(n=2)** |
| `two process groups and another group are created` | RED(n=2) | **RED(n=3)** |
| `two process groups and three cgroups are created` | RED(n=3) | **RED(n=5)** |
| `a process group and another group and a third group are created` | GREEN(n=1) | **RED(n=3)** |
| `a process group and a lease and another group are created` | GREEN(n=1) | **RED(n=2)** |
| `the controller creates one process group and another group` | GREEN(n=1) | **RED(n=2)** |
| `the attempt's process group and the reviewer's group are created` | GREEN(n=1) | **RED(n=2)** |
| `a new process group and another new cgroup are created` | GREEN(n=1) | **RED(n=2)** |
| `a process group plus another group are created` | GREEN(n=1) | **RED(n=2)** |
| `a process group as well as another group are created` | GREEN(n=1) | **RED(n=2)** |

Eight were false greens. The two already red were red at the **wrong** number (`max` reporting the
larger conjunct, not the total) and are now pinned to the semantic total — an under-counted red is
still a defect, because removing one conjunct in a later edit would silently turn it green.

**Coordination that cannot be counted** (must be red, never 1):

| mutation | `450cc52` | repair |
|---|---|---|
| `a process group and a further group are created` | RED(unknown) | RED(unknown) |
| `a process group and several other groups are created` | RED(unknown) | RED(unknown) |
| `a process group and new groups are created` | RED(unknown) | RED(unknown) |
| `a process group and/or another group are created` | GREEN(n=1) | **RED(unknown)** |
| `the controller creates a process group and records the group` | GREEN(n=1) | **RED(unknown)** |

**Same group named twice — must stay green at one** (the anti-`sum` control): all five
(`parenthetical appositive`, `disjunction of two descriptions`, `relative clause naming the group`,
`back-reference in a following predication`, `back-reference behind a preposition`) are
**GREEN(n=1) at both** `450cc52` and the repair.

**Prior families unmoved** — all 7 `QUANTIFIED_GROUP_CREATIONS`, 7 `QUANTIFIED_MODIFIER_CREATIONS`,
5 `UNQUANTIFIED_GROUP_CREATIONS`, 5 `UNQUANTIFIED_MODIFIER_CREATIONS` and 8
`SINGULAR_CREATIONS_THAT_MUST_STILL_PASS` produce **identical verdicts and identical counts** before
and after (M-05 / M-06 protections intact by measurement, not by assertion).

**Committed document:** GREEN with exactly 1 creation assertion at `450cc52` **and** at the repair,
on both the group and the write-point dimensions.

### Suites

| check | result |
|---|---|
| `pytest tests/test_orchestrator_freeze_spec.py -q -p no:randomly` | **247 passed** in 3.4 s (was **225** at `450cc52`; +22) |
| `pytest tests -m "not live" -q -n 4 -p no:randomly` | **3051 passed, 8 skipped, 2 failed** in 185 s (baseline at `450cc52`: 3029 passed / 8 skipped; 3051 = 3029 + 22) |
| the 2 failures | `tests/test_experience.py::test_a_record_is_only_replayed_to_the_conversation_it_was_shown_to` and `::test_a_record_reached_by_tapping_is_still_held_a_moment_later` — the **known `-n 4` load/timing flakes** already recorded on this branch. Re-run alone: `pytest tests/test_experience.py` → **85 passed** in 210 s. Unrelated to this change: this commit touches one test file, `test_orchestrator_freeze_spec.py`, which imports no app code. |
| `ruff check app config scripts tests` | **All checks passed** (`ruff format` is not a repo gate and was not run) |
| `gitleaks git --no-banner --redact --exit-code 1 --log-opts="450cc52..f06730a"` | 1 commit scanned, **no leaks found**, exit 0 |

## 7. Resulting SHA and worktree state

```
branch : chatgpt/orchestrator-v1-freeze-candidate-2026-09-20
parent : 450cc524e4da1397b44df022ac6e2fa546edd13d
HEAD   : f06730aa361bb6054ae47bfa284539772a062782
title  : One creation verb, two groups, and the count that read them as one
files  : crooks-assistant/tests/test_orchestrator_freeze_spec.py  (+306 / -11)
status : clean (git status --porcelain empty)
remote : origin refs/heads/chatgpt/... = f06730aa361bb6054ae47bfa284539772a062782
         (verified by git ls-remote after the push)
```

One commit, one file, repository-only. Pushed to the isolated candidate branch **only** so an
independent reviewer can fetch the exact SHA — the same publication path every prior round on this
branch used. No merge, no production branch touched, no deployment.

## 8. Disclosed residual blind spots (stated in-tree, not hidden)

All are **under-counts** — ways a future edit could be missed, never ways legitimate prose is
wrongly rejected — and none is reachable in the committed §3A, which has one group noun in one
creation segment. Pinned by `test_the_coordination_blind_spots_are_stated_rather_than_assumed_closed`:

1. **Postmodified first conjunct.** `a process group for the attempt and a group for the reviewer
   are created` → 1. The prepositional postmodifier puts the coordinator out of adjacency, and
   relaxing adjacency is exactly what would let clause coordination be misread as NP coordination.
2. **Comma-separated conjunct lists.** `a process group, another group and a third group are
   created` → 2: `_segment_bounds` splits on the comma before coordination is ever seen. This is
   pre-existing segmentation behaviour, unchanged by M-07.
3. Carried forward from M-05, unchanged: elided second predicates (`…, as is a second process
   group`) and repetition nouns other than `time`/`occasion` (`written in two batches`).

**Deliberate fail-closed cost — flagged for reviewer judgement.** When an additive coordinator sits
directly after a group noun but the run to the next group noun cannot be placed, the count is
`None` → red, rather than collapsing to `max`. Consequence: `the controller creates a process group
and records the group` — one group, plausible prose — now **reddens** the gate with "without saying
how many". I chose this over `max` because `max` there is precisely the silent under-count M-07 is
about, and the inbox directs failing closed when cardinality cannot be established safely. It is a
loud, self-describing failure, it does not fire on the committed document or on any existing green
control, and it is asserted as intended behaviour in `UNQUANTIFIED_COORDINATED_CREATIONS` and
`test_coordination_is_decided_structurally_not_by_the_presence_of_a_conjunction`. **If the reviewer
judges that trade wrong, this is the single line to challenge** — `_coordination_between` returning
`None` rather than `False`.

## 9. Safety constraints — all preserved, none touched

`writes_enabled` false, `CROOKS_WRITES_LOCAL_OWNER` false, FastAPI bound to `127.0.0.1` (verified:
the only listener on 8000 is `127.0.0.1:8000`, not publicly exposed), proposal/action/verification
semantics unchanged, no live Shopify / Gmail / ElevenLabs call and no live external mutation, V2 not
begun, UI not redesigned, Mac deployment and rollback path untouched, `/root/.claude` writable, no
secret value printed or committed (gitleaks clean). No production, runtime, systemd, watcher,
connector, MCP, privilege, business-write, deployment, sequencing or adoption change of any kind. No
normative freeze or product-memory document was modified — the whole diff is one test file.

## 10. Service and server state (observed; unchanged by this round)

| item | state |
|---|---|
| Production checkout `/opt/crooks-os/crooks-assistant` | branch `claude/linux-prod-migration-production`, HEAD `1cf3a0f3361b79f9de208d80f501543c53c244b5`, **clean** — never edited, switched or reset |
| Production branch HEAD | `1cf3a0f` — `Linux production migration (Phases 1-4) for review`. No `main` branch exists locally or on `origin` |
| `crooks-assistant` service | `active` (untouched) |
| `crooks-ai-bridge-watcher` | `inactive` at the time of the check (it invoked this run) |
| Listener on port 8000 | `127.0.0.1:8000` only |
| `/opt/crooks-ai-bridge` | branch `crooks-ai-bridge`, clean apart from this outbox file |

## 11. Errors, blockers, approvals

* **No errors.** Nothing was blocked by my permission layer. No permission was widened and no
  workaround was sought.
* **No owner approval was sought, given, assumed or recorded.** Nothing in this round required it:
  it is a repository-only test-module repair.
* **No self-certification.** I authored this repair and therefore cannot review it.
* **Process note for the bridge operator:** the last three rounds routed my own repair back to me
  for review, and each of those review rounds stalled without a verdict. `f06730a` must be routed to
  a **fresh independent reviewer that did not author it**.

## 12. Exact proposed next step

Commission a **fresh independent source review of exact SHA
`f06730aa361bb6054ae47bfa284539772a062782`** on
`chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, by a reviewer that did not author the repair.
Ask that review specifically to:

1. attack `_coordination_between` with coordination shapes not in the added tables — coordinated
   subjects, elided heads (`two process groups and three more`), `both … and …`, nested
   parentheticals, and hyphenated or compound group nouns;
2. rule on the §8 fail-closed trade (`None` vs `False` for an unreadable coordinated run) — the one
   deliberate false-red family this repair introduces;
3. confirm the two disclosed under-counts (postmodified first conjunct; comma-split conjunct lists)
   are acceptable as stated limits rather than M-07 resurfacing under another wording;
4. re-derive from the source — not from this handoff — that M-01..M-06, L-01, K-01, J-01, H-03/H-04
   and R-02 remain intact.

No acceptance, adoption, merge or Phase 0 authority is claimed or implied by this round.
