# CLAUDE OUTBOX — M-06 repair handoff

**Timestamp:** 2026-09-21T04:57:58Z
**Inbox SHA processed:** `ce544b327576bbec785e4d6ead1a56cdde62c484` (consumed; these instructions are now spent)
**Round type:** bounded repair. **NOT a certification.** See §7.

---

## 1. What was asked

Repair exactly one bounded evaluator defect — **M-06**, a quantified-adjective false green in
`_asserted_group_count` — on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, required to be
at exact HEAD `7f92215f0fc1a44f0865af316ce0f02780345417`, stopping without changes if it differed.

Smallest test/evaluator-module-only repair so explicit cardinals governing the same noun phrase
outrank non-cardinal modifiers (`new`/`existing`), without letting quantifiers leak across
constituent boundaries; preserve fail-closed behaviour for genuinely ambiguous plurality; do not
touch normative freeze/product-memory documents. Add adversarial regression evidence; self-attack
adjacent adjective/quantifier ordering; run the freeze suite, static checks and secret scan;
require a clean worktree and exact SHA evidence; **do not self-certify**.

## 2. Preconditions checked before acting

| Check | Result |
|---|---|
| Builder checkout at start | `/opt/crooks-builder`, branch `claude/builder-environment-repair`, HEAD `295e483`, **clean** — not touched this round |
| Candidate branch resolved | explicit fetch (the local refspec is stale and must never be trusted) |
| Candidate HEAD | `7f92215f0fc1a44f0865af316ce0f02780345417` — **exact match to the inbox**, no drift, so the round proceeded |
| Repair worktree | `/opt/crooks-builder/.worktrees/freeze-repair`, already at `7f92215`, **0 dirty lines** before any edit |
| Authorship note | I authored the M-05 repair at `7f92215`. That is a bar on *reviewing* it, not on repairing it under an explicit instruction, so this round proceeded. It is also why §7 and §10 are not optional. |

## 3. What I found — M-06 confirmed, and wider than stated

**Confirmed exactly as described.** `_SINGULAR_QUANTIFIERS` contained `new`, `existing` and `same`.
These are not quantifiers at all: they say *which* groups are meant, never how many. The leftward
walk in `_asserted_group_count` **returned** on the first such token, reporting `1`, so an explicit
cardinal sitting immediately to its left was never read.

The dangerous placement is **not** appending a sentence to a §3A row — that adds a second creating
*row*, which the row-counting dimension catches regardless of the count. The escape is **rewriting
the one committed clause that legitimately creates the attempt's group** (`CREATED -> STARTING`).
There the creating-row count stays `1` and §3A.3's declared cardinality stays `1`, so the asserted
group count is the *entire* remaining guard — and it was wrong.

Measured against `7f92215`'s own test module (blob `41d9340a0418042e416674b880a4dab8f15cfd21`,
`git hash-object` proven equal to `git rev-parse 7f92215:<path>`) with byte-identical docs:

| `CREATED -> STARTING` clause rewritten to | at `7f92215` | at `450cc52` |
|---|---|---|
| `two new process groups are created` | **GREEN** | RED — asserts 2 |
| `three existing process groups are created` | **GREEN** | RED — asserts 3 |
| `two new groups are provisioned` | **GREEN** | RED — asserts 2 |
| `two new cgroups are created` | **GREEN** | RED — asserts 2 |
| `2 new process groups are created` (numeral) | **GREEN** | RED — asserts 2 |
| `both new process groups are created` | **GREEN** | RED — asserts 2 |
| `three new same process groups are created` | **GREEN** | RED — asserts 3 |
| `several new process groups are created` | **GREEN** | RED — unstated count |
| `the same process groups are created` | **GREEN** | RED — unstated count |
| `new process groups are created` (bare plural) | **GREEN** | RED — unstated count |

**Two escapes beyond the inbox's report**, same root cause: `new`/`existing` also collapsed an
*unquantified* plurality to one (`several new process groups`, bare `new process groups`), which is
worse than over-counting — an unknown critical cardinality must redden the gate, not be read as 1.

**A second, pre-existing weakness surfaced while bounding the fix**: the walk already skipped
unknown tokens freely, so it would *steal* a number from the neighbouring phrase —
`two attempts create process groups` derived **2** at `7f92215`. Both readings are red, but the
stolen number is not this phrase's number, and letting the walk see further past `new` would have
made stealing easier. It is fixed as part of the bound (§4.3).

## 4. What I changed

**One file, test module only: `crooks-assistant/tests/test_orchestrator_freeze_spec.py`, +204 / −4.
Zero freeze/product-memory documents touched — all 21 docs blobs verified byte-identical to
`7f92215`.**

1. `new`, `existing`, `same` moved out of `_SINGULAR_QUANTIFIERS` into a new, documented
   `_NON_QUANTIFYING_MODIFIERS`.
2. **No modifier ends the walk any more.** Modifiers now *record* what they mean and the walk
   continues, so a stated cardinal in the same phrase always outranks them. The two vocabularies
   stay distinct because they differ when no cardinal is found: a singular quantifier asserts one
   even with no determiner to lean on (`single process group` → 1), while `new` asserts nothing,
   leaving a bare plural **unknown** → red. This also removes a residual miss the narrow fix would
   have left behind and pinned: `two single process groups` now reads 2, not 1.
3. **New bound, `_heads_a_different_noun_phrase`.** Letting the walk see further needs a new stop
   or it reads the phrase next door. English premodifiers here are adjectives, participles,
   singular noun modifiers and possessives; a **bare plural word cannot premodify a head**, so
   meeting one means the walk has crossed into the subject phrase and the count is unknown.
   Possessives (`the attempt's`) keep the walk alive. The existing determiner / boundary-word /
   8-word-limit stops are unchanged, so no quantifier crosses a constituent boundary.

## 5. Self-attack — adjacent adjective/quantifier ordering

15 orderings I invented, gated the same way (rewriting the committed creating clause):

| Form | `7f92215` | `450cc52` |
|---|---|---|
| `two additional new process groups`, `the two new owned process groups`, `the attempt's two new process groups`, `two further existing cgroups`, `a further two new process groups`, `up to two new process groups`, `two or three new process groups`, `between two and four new process groups`, `two new controller-allocated process groups`, `twelve new process groups` | **GREEN (10)** | RED — stated count |
| `one or more new process groups`, `both of the new process groups`, `all new process groups` | **GREEN (3)** | RED — unstated count |
| `two brand-new process groups`, `two newly provisioned process groups` | already RED | RED (unchanged) |

**False-positive controls — the direction that must not move.** 8 genuinely singular rewrites stay
**GREEN on both dimensions**: `a new process group`, `the existing owned process group`,
`a second owned process group`, `another new process group`, `one new process group`,
`the single new process group`, `the same process group`, `the attempt's new owned process group`
(plus `its new`, `each new`, `the same single new`). **Pristine is GREEN on both dimensions before
and after.**

**No-theft controls:** `two attempts create new process groups` (**GREEN → unknown/red**),
`two attempts create process groups` (**stolen 2 → unknown**), `three leases provision existing
cgroups`, `after two failures new process groups are created` — all now read *unknown*, which is
red, rather than a borrowed number. `the attempt's two new owned process groups` still reads 2, and
`two leases each create a new process group` still reads 1.

## 6. Verification

| Check | Result |
|---|---|
| Freeze spec suite | **225 passed** (203 at `7f92215`), 2.6 s |
| Test functions | **94 → 99**: 5 added (all parametrised), **0 removed, 0 renamed** (`comm` on sorted `^def test_`) |
| Deleted asserts / `pytest.raises` | **0** (`git diff -U0` grep) |
| `skip` / `xfail` | **0** |
| Prior protections M-01..M-05, L-01, K-01, J-01, H-03/H-04, R-02 | intact — every earlier round's test is still present, unmodified and green inside the 225 |
| `ruff check app config scripts tests` | **All checks passed** (`ruff format` deliberately not run — it is not a repo gate and would reformat ~114 unrelated files) |
| gitleaks 8.30.1, changed file | no leaks |
| gitleaks 8.30.1, range `7f92215..450cc52` | no leaks, 1 commit scanned |
| Full offline suite `pytest tests -m "not live" -n 4` | **3029 passed / 8 skipped / 2 failed** in 3m03s |
| Those 2 failures | the **known `test_experience.py` `-n 4` load flakes** — `test_experience.py` run alone immediately after: **85 passed**, 3m37s. Reconciles exactly: `7f92215` was 3006 passed + 3 flakes = 3009; 3009 + 22 new = 3031 = 3029 + 2 |
| Files changed vs `7f92215` | exactly 1; `docs/` files changed: **0** |
| Worktree after everything | **0 dirty lines** |

## 7. Result — exact SHA, NOT certified

| | |
|---|---|
| **Resulting candidate SHA** | **`450cc524e4da1397b44df022ac6e2fa546edd13d`** |
| Parent | `7f92215f0fc1a44f0865af316ce0f02780345417` |
| Commits added | exactly 1 |
| Branch (pushed) | `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` — remote head verified `450cc52` |
| Canonical base | `claude/product-memory-foundation` @ **`654a9ed7d790e38597a3c5852d9b3e0a42902a1a`** (unmoved). Merge-base with the candidate is still `9e59860`; `git merge-tree --write-tree 450cc52 654a9ed` exits **0** → tree `677d3ddb0804d0ec1be436058f1606653fc622e4`, conflict-free |
| **Production branch HEAD** | **`1cf3a0f3361b79f9de208d80f501543c53c244b5`** — remote branch `claude/linux-prod-migration-review`; the local production checkout `/opt/crooks-os/crooks-assistant` is on local branch `claude/linux-prod-migration-production` at the same SHA `1cf3a0f`, **0 dirty lines, not touched, not switched, not reset**. There is no `main` on this remote. |

**I did not certify this candidate and this handoff is not an acceptance.** I authored both this
repair and the M-05 repair it sits on. A fresh reviewer that did not author them must review
`450cc52` before any acceptance can count.

## 8. Service and server state (observed read-only; nothing changed)

`crooks-assistant.service` active/running; `crooks-bridge-watcher.service` active/running.
FastAPI listening on **`127.0.0.1:8000` only** — port 8000 not exposed publicly.
`writes_enabled: bool = False` (`config/settings.py:116`); `CROOKS_WRITES_LOCAL_OWNER=false`.
No Shopify, Gmail or ElevenLabs call, no live external mutation, no deployment, no merge, no
systemd/watcher/runtime change, no secret read or printed, V2 not begun, UI not touched, Mac
deploy/rollback path untouched, `/root/.claude` still writable.

## 9. Errors, and decisions a reviewer should challenge

**No errors and nothing blocked.** Nothing hit my permission layer; nothing needed owner approval.

Three judgement calls, made explicit because they are the places to attack:

1. **I went one step past the literal ask.** The inbox named `new`/`existing`; I also made *true*
   singular quantifiers (`single`, `second`, …) transparent to a stated cardinal. The narrow fix
   would have left `two single process groups` reading 1 and I would have had to pin that false
   green in a test — this review chain has been bitten before by tests that lock a defect in.
   Challenge whether the wider rule is right.
2. **`_heads_a_different_noun_phrase` is shape-based, not a lexicon**: "a token ending in `s`,
   without an apostrophe, that no earlier arm claimed". Consequences, all fail-closed: an adjective
   ending in `s` (`previous process groups`) stops the walk and reads *unknown* (red) instead of
   counting; auxiliaries `is`/`was`/`has` also stop it (no case found where a cardinal legitimately
   sits left of one). Verified it never fires on the committed prose.
3. **Disclosed residual limits — none reachable in committed prose, direction is red not green:**
   ranges and approximations (`up to two`, `two or three`, `between two and four`) are read as the
   first number they state rather than as ranges; `both of the new process groups` is unknown, not
   2. All of M-05's previously disclosed under-counts (coordination under one verb, elided
   predicates, repetition nouns outside `time(s)`/`occasion(s)`) are **unchanged** — M-06 did not
   touch the write dimension at all.

## 10. Exact proposed next step

**One fresh independent adversarial review bound to exactly
`450cc524e4da1397b44df022ac6e2fa546edd13d`, by an agent that did not author it.**

**Routing is the blocking problem, not the code.** Three consecutive review rounds (`de9bea2`,
`2ee1836`, `7f92215`) were routed back to the agent that wrote the repair; two ended with **no
verdict at all**. `2ee1836`'s M-03/M-04 work and `7f92215`'s M-05 work have *still* never been
checked by any independent reviewer — only by ChatGPT reading the source, which is how M-05 and
M-06 were both found. Sending `450cc52` to a Claude session on this machine will produce a fourth
stop, and a *fresh* Claude session would not detect that it doesn't qualify.

So: **route the `450cc52` review to ChatGPT**, which has now found two defects from source and
authored neither repair.

The review should attack, in this order:

1. `_heads_a_different_noun_phrase` — the `s`-suffix rule. Find a premodifier it wrongly stops on,
   or a plural word it wrongly walks through (hyphenated forms, acronyms, possessives written
   without an apostrophe, `-ss` words such as `process`/`status`/`access`).
2. Whether making true singular quantifiers transparent opened anything — specifically a phrase
   where `single`/`sole`/an ordinal used to bound the walk and now no longer does.
3. `max(counts)` in `group_creations` across several live group nouns in one segment, now that more
   nouns resolve to a number instead of to 1.
4. The `indefinite`/`singular` interaction in `settled()`: is there a phrase where both flags are
   set and the answer should not be unknown?
5. Everything `7f92215` still owes a reviewer: `_quantifier_tokens_after`'s single boundary
   crossing, whether the M-05 `UNCLASSIFIED` arm can *suppress* a real write, and the M-03/M-04
   clause-counting and negation-government walks.

**No owner approval is requested by this round and none was given.** Adoption, merge, deployment
and Phase 0 authority remain untouched and owner-only.
