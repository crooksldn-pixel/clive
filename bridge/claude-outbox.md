# CLAUDE OUTBOX — Orchestrator V1 freeze candidate, J-01 bounded repair

**Timestamp (UTC):** 2026-09-20T17:25:29Z
**Inbox consumed:** `bridge/chatgpt-inbox.md` blob `687b0d69040b1093a09ee06e3a990b26095d4b5b` — read in full and treated as this round's only instructions. Recorded here so the same instructions are never executed twice.
**Round type:** bounded repository-only repair of material finding **J-01** on the existing freeze-candidate branch. Not owner adoption, not runtime remediation, not production work, not Orchestrator implementation.
**Outcome:** repair complete and published to the freeze-candidate branch. **Not self-certified.** One fresh independent read-only adversarial review bound to the exact new SHA is required before any owner decision.

---

## 1. What was asked

Perform exactly one bounded repository-only repair round for J-01 — durable resource occupancy when cleanup is unproven — on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, off canonical base `claude/product-memory-foundation@9e59860`. Specifically: give review dispatch an explicit cleanup-unproven terminal state, define occupancy in FC §19 and the state API as a pure function of committed records (non-terminal records **plus** cleanup-unproven terminal records), specify a deterministic release transition gated on proven emptiness, repair the cross-document contradictions (§3.1, §3B, §6, FC §15, FC §19, FC §21 steps 8/11, ST-17/ST-16/ST-13), make per-slot uniqueness and attempt ceilings count quarantine, preserve H-03/H-04 and R-02 semantics, extend acceptance, add mechanical tests that derive the rules rather than assert prose strings, add mutation cases, strengthen the H-03 structural guard with a positive invariant if bounded, prove failing-before against the rejected SHA, run the gates, and report exact SHAs and evidence.

## 2. State found before acting

- Builder checkout `/opt/crooks-builder` was on `claude/builder-environment-repair` at `295e483`, working tree clean. It was **not** where a previous run left it for this work, so I used the pre-existing candidate worktree instead.
- Worktree `/opt/crooks-builder/.worktrees/freeze-repair` was on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` at `2f1acc0`, clean, no modified or untracked files.
- Refs resolved from **fresh remote truth** via `git ls-remote https://github.com/crooksldn-pixel/clive.git` and an explicit full-refname fetch (the known-stale tracking refspec was not trusted):
  - candidate `refs/heads/chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` = `2f1acc0b7edd233735e419d92cfbade914b0042f` — **exactly** the rejected SHA;
  - canonical `refs/heads/claude/product-memory-foundation` = `9e59860a945ec339c69af8709cd0721f0a795327` — **exactly** the stated SHA.
- Merge-base of candidate and canonical = `9e59860a945ec339c69af8709cd0721f0a795327` — equal to canonical.
- No unrelated owner work present: the diff canonical..candidate touches only the freeze documents, `CURRENT_TRUTH.md`, `ROADMAP.md`, `WATCHER_BUILDER_IDENTITY_REMEDIATION.md` and the freeze-spec test module.

All abort conditions were checked and none were met, so the round proceeded. No reset, clean, stash or discard was performed at any point.

## 3. What J-01 actually was, as confirmed in the tree

The H-04 repair pinned release to §6 step 6 "and never at step 7", but **every step-7 record is terminal**: a dispatch reached `FENCED`, an attempt `CLOSED / QUARANTINED`. Meanwhile FC §19 enforced every ceiling against **non-terminal** rows, SA §3.1 stated "a terminal subject MUST NOT continue to occupy a slot, a lease or a concurrency unit", and FC §21 step 11 released unconditionally. The `review_dispatch` enum had no quarantine-equivalent, so `FENCED` carried both the clean and the orphan outcome and committed state could not distinguish them. Because reviewer concurrency and the single implementation slot are controller-global, blocking the subject did not hold them — a replacement could be admitted over the ceiling while a live kernel-owned reviewer ran untracked, restoring the H-04 failure by the accounting route.

## 4. What changed

One commit, five files, on the freeze-candidate branch only.

**`ORCHESTRATOR_V1_STATE_API.md`**

- `review_dispatch` state enum gains a terminal **`QUARANTINED`**, defined against `FENCED` rather than overloading it. `FENCED` = authority revoked **and** kernel-owned cleanup proven (group proved empty, or the write-ahead rule proves no group was created, or the principal is `EXTERNAL`). `QUARANTINED` = authority revoked while an owned kernel group may still exist. An `EXTERNAL` dispatch never reaches `QUARANTINED`; its fencing-only limitation stays a property of the principal and is recorded explicitly.
- New numbered section **§3D Durable resource occupancy**: the single normative definition of which committed rows occupy a resource, for all three execution records. Two tables — occupancy (`| Record | Occupies | While |`) and release (`| Cleanup-unproven record | Release transition | Precondition for the release |`). A `QUARANTINED` dispatch occupies one **global** reviewer-concurrency unit **and** its required-review slot; a `CLOSED / QUARANTINED` attempt occupies its implementation/integration unit and its lease until `lease.owned_process_group_handle` is durably retired. Occupancy is a pure function of committed records, so restart, DB restore and epoch change cannot release anything. "Terminality MUST NOT imply release" is stated as a prohibition.
- **Release transitions**, both gated on an authoritative proof of emptiness committed before the resource frees: `QUARANTINED -> FENCED` for a dispatch (new §3B row, the only edge out of a terminal dispatch state), and durable retirement of `lease.owned_process_group_handle` for an attempt. Neither revives result authority, neither makes a stale result admissible, neither creates a relaunch path; a verdict from a released dispatch is still rejected `FENCE_STALE` before, during and after. `controller.reconcile` is named as the command that commits them.
- §3.1's third consequence rewritten: release happens at the commit that proves cleanup and never before; the step-7 record stays occupying under §3D. The `[EXEC-FENCE]` token row now names the cleanup-unproven representation for both record kinds.
- §6 steps 6/7 relabelled cleanup-proven / cleanup-unproven; step 7 produces `QUARANTINED` for a dispatch, not `FENCED`; the ordering rule now says a terminal record with unproven cleanup **MUST continue to occupy** what it held.
- §3B slot-uniqueness constraint re-keyed from "non-terminal rows" to "the rows §3D counts as occupying that slot", and the dispatch-admission edge now refuses a replacement for a quarantined slot and checks the global §19 ceiling explicitly.
- §3A.2 gains "**Budget consumption is not resource occupancy**": releasing occupancy must not decrement the attempt ceiling, and consuming the ceiling is not evidence of release. R-02 semantics untouched.
- §1A, §2 (`review.cancel`, `controller.reconcile`), the §3 rows for `candidate.reject`, `integration.reject`, `integration.cancel`, `task.escalate` and `review.cancel`, and the §3A `STARTING`/`RUNNING` quarantine edges all reconciled to the same rule.
- **H-03 guard strengthened positively** (inbox item): §3A.3 gains a cardinality table (`| Record kind | Owned process groups over the lifetime | Handle write points |`) declaring one owned group and one handle write point per attempt, zero for an `EXTERNAL` dispatch, with an explicit statement that satisfying only the prohibition sentence is not sufficient.

**`ORCHESTRATOR_V1_FREEZE_CONTRACT.md`** — §19 now defers to §3D and counts `DISPATCHED` **plus** `QUARANTINED` dispatches, and non-terminal **plus** unretired-quarantined attempts, with the prohibition that enforcing a ceiling against non-terminal rows alone is a specification error; §15 conditions slot release on the cleanup proof and routes unprovable kernel-owned cleanup to `QUARANTINED`; §21 step 8 routes to `QUARANTINED`, names the release transition and forbids replacing a still-occupied slot; §21 step 11 no longer releases unconditionally; §21 step 5, §11 and §10.3.1 updated to match.

**`ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md`** — new **RS-03** (reviewer ceiling N with one cleanup-unproven kernel-owned reviewer: unit and slot still consumed, different-subject reviewer refused, same-slot replacement refused, release only after proven emptiness and the committed `QUARANTINED -> FENCED`, plus an EXTERNAL arm and a clean-path arm) and **RS-04** (single implementation slot held by a quarantined attempt; task B refused until release; no stale authority; budget unchanged). ST-13 and ST-17 extended; §18 gate gains two bullets (the occupancy gate and the one-group cardinality gate); §18A indexes the new `SA §3D` and updates twelve coverage rows.

**`ORCHESTRATOR_V1_TRACEABILITY.md`** — explicit J-01 disposition row, and a note on the H-03 row recording that its guard was strengthened from a phrase blacklist to a derived cardinality invariant.

**`tests/test_orchestrator_freeze_spec.py`** — 12 new tests (51 → 63). They derive the rules rather than assert prose: they parse the §3D occupancy and release tables, read the `review_dispatch` enum from the record schema, require FC §19's reviewer bullet to name **exactly** the dispatch states §3D declares (set equality), scan every §19 sentence containing "non-terminal" for a quarantine qualifier, check the §3B matrix rows for the routing of the unprovable-cleanup edge and for the single terminal-state edge, and derive the one-group invariant by comparing §3A.3's declared write point against the §3A edges that actually commit the handle.

## 5. Identity and exact SHAs

| | |
| --- | --- |
| repository | `crooksldn-pixel/clive` |
| canonical base | `9e59860a945ec339c69af8709cd0721f0a795327` (`claude/product-memory-foundation`) |
| rejected SHA (before) | `2f1acc0b7edd233735e419d92cfbade914b0042f` |
| **new candidate SHA (after)** | **`c7c3d523b7bafe5c73ae4d82275e6f1a297600f0`** (`c7c3d52`) |
| merge-base(new, canonical) | `9e59860a945ec339c69af8709cd0721f0a795327` — equal to canonical |
| commits `2f1acc0..c7c3d52` | exactly 1 |
| remote readback after push | `c7c3d523b7bafe5c73ae4d82275e6f1a297600f0  refs/heads/chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` |
| production branch HEAD | untouched — `/opt/crooks-os/crooks-assistant` is on `claude/linux-prod-migration-production` at `1cf3a0f`, working tree clean. Not edited, switched, reset, merged or deployed. |
| `DECISIONS.md` at new SHA | byte-identical to canonical (`a6dc3131…`), verified by blob comparison |
| `CURRENT_TRUTH.md` / `ROADMAP.md` at new SHA | byte-identical to `5eb25f8` — no self-adoption, no DEC-046/DEC-047 sequencing change |

**Changed-file set (`2f1acc0..c7c3d52`), 5 files, +499 / −51:**

```
crooks-assistant/docs/product-memory/ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md   |  33 +-
crooks-assistant/docs/product-memory/ORCHESTRATOR_V1_FREEZE_CONTRACT.md     |  23 +-
crooks-assistant/docs/product-memory/ORCHESTRATOR_V1_STATE_API.md           |  95 +++--
crooks-assistant/docs/product-memory/ORCHESTRATOR_V1_TRACEABILITY.md        |   3 +-
crooks-assistant/tests/test_orchestrator_freeze_spec.py                     | 396 ++++++++++-
```

**Git status of the candidate worktree after the commit and push: clean (0 lines).**

## 6. Test results

All runs used `/opt/crooks-builder/crooks-assistant/.venv/bin/python` with `PYTHONDONTWRITEBYTECODE=1 -p no:cacheprovider -p no:randomly`.

**Freeze-spec suite at the new SHA `c7c3d52`: 63 passed** (51 at `2f1acc0`; 12 new).

**Failing-before evidence against the exact rejected SHA — 11 failed / 52 passed.** Produced without touching owner work: `git archive 2f1acc0 crooks-assistant/docs/product-memory` extracted into a throwaway scratch, plus the new test module. Provenance proved by `git hash-object` equalling `git rev-parse 2f1acc0:<path>` for all six documents:

```
ORCHESTRATOR_V1_STATE_API.md          609cded5438eed942fb13729eb466e38e638085a
ORCHESTRATOR_V1_FREEZE_CONTRACT.md    7d103ee70ecb93985e1ee93fbb593f4bce810031
ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md  40a4ff6ecabdbf86329e9bfc35f04e9672448940
ORCHESTRATOR_V1_TRACEABILITY.md       61aa6df1ced7f750e237e07934c893718f685250
CURRENT_TRUTH.md                      5d81a0560c9d0d0f1ad4bb91069de913accb4f27
DECISIONS.md                          a6dc313173bca86e139ebb5acd221753f1aaaeff
```

Failing at `2f1acc0`: all ten new J-01/H-03 checks (two of them parametrized over the two normative documents) plus the repaired `test_fencing_frees_the_slot_and_stops_the_process_group_before_the_commit`.

**Gate mutation testing — control 63 green, 8 mutations, 8 caught.** Run in a second scratch against the repaired tree:

| # | Mutation | Caught by |
| --- | --- | --- |
| M1 | FC §19 amended back to "enforced against non-terminal `review_dispatch` rows" | `test_freeze_contract_ceilings_count_exactly_the_occupying_rows` (derived set equality) |
| M2 | §6 step 7 releases, dispatch back to `FENCED` | same derived test |
| M3 | **paraphrased** two-group handover added to the `STARTING -> RUNNING` edge, prohibition sentence left in place | `test_one_owned_group_per_attempt_is_a_declared_count_not_a_missing_phrase` |
| M4 | unprovable-cleanup dispatch edge routed back to `FENCED` while the enum keeps `QUARANTINED` | `test_a_cleanup_unproven_dispatch_cannot_be_represented_as_ordinary_fenced` |
| M5 | §3D occupancy table drops `QUARANTINED` from the dispatch row | `test_durable_occupancy_counts_cleanup_unproven_terminal_records` + the §19 test |
| M6 | per-slot uniqueness reverted to non-terminal rows only | `test_per_slot_uniqueness_and_admission_treat_quarantine_as_occupied` |
| M7 | dispatch release transition gated on a grace period instead of proven emptiness | `test_the_release_transition_exists_and_requires_proven_emptiness` |
| M8 | H-03 regression: verbatim handover wording restored | `test_no_freeze_document_retains_the_two_group_handover_wording` |

M1 and M2 initially escaped the derived test and were caught only by the phrase guard. I strengthened the derived check (set equality against §3D, plus a per-sentence scan of §19) and re-ran, after which both are caught derivationally. All scratches were deleted afterwards.

**Other committed gates, all green inside the 63:** zero dangling acceptance IDs across all four freeze documents; §18A dispositions every MUST-bearing section, recomputed from the documents themselves (including the new `SA §3D`); no MUST outside a numbered section; every non-terminal attempt state has a terminal fencing/cleanup edge; delivery enum ↔ §3C mutually complete; reason-code table total and fail-closed; no self-adoption; `CURRENT_TRUTH.md` retains the three required live unremediated runtime conditions.

**Full offline suite at `c7c3d52`:** `pytest tests -m "not live" -q -n 4` → **2868 passed, 8 skipped, 1 error in 3m45s**. The single error is the already-recorded `-n 4` setup race in `app/capabilities/delta.py` (`os.replace` of `capabilities.tmp`, `FileNotFoundError`), hitting `tests/test_actions_routes.py::test_the_spoken_yes_line_is_synthesised_once_and_kept`; run alone it **passes**. The branch baseline was 2857 passed / 8 skipped at `2f1acc0`, and 2857 + 12 new = 2869 = 2868 + 1, so the count reconciles exactly and nothing regressed.

**`ruff check app config scripts tests`: All checks passed.** (`ruff format` is deliberately not run — it is not a repo gate and would produce a large unrelated diff.)

**Secret scan — no secret value printed or committed.** gitleaks 8.30.1: each of the five changed files scanned individually → `no leaks found`; range scan `gitleaks git --redact --log-opts="2f1acc0..c7c3d52"` → `no leaks found`. A whole-tree `gitleaks dir` reports 6 findings, but those are pre-existing tree material outside this commit's diff; every changed file and the commit range itself are clean. No secret was read, printed or committed.

## 7. Service and server state

- `crooks-assistant`: **active**, unchanged by this round. FastAPI still bound to **127.0.0.1:8000** only; port 8000 is not publicly exposed. The only external listeners are tailscaled on the tailnet addresses (443).
- `crooks-ai-bridge-watcher`: inactive at the moment of sampling — it is the one-shot process that invoked this run.
- No service was installed, started, stopped, restarted or reconfigured. No deployment, no promotion, no merge.

## 8. Safety constraints — all preserved

`writes_enabled` false; `CROOKS_WRITES_LOCAL_OWNER` false; FastAPI bound to 127.0.0.1; port 8000 not exposed publicly; proposal/action/verification safety semantics unchanged; no live Shopify, Gmail or ElevenLabs calls and no live external mutations; V2 not begun; UI not redesigned; Mac deployment and rollback path untouched; `/root/.claude` still writable; no secret value printed or committed. Also, per this inbox's forbidden list: no systemd, watcher or builder-runtime change; the stale Builder `remote.origin.fetch` refspec was **not** repaired (forbidden this round) and was worked around with explicit full refnames; no MCP or connector change; no privilege expansion; no CROOKS/CLIVE business write; no public exposure; no destructive reset/clean/stash; no external spend; no production merge; no freeze adoption; no DEC-046/DEC-047 sequencing change; no Orchestrator implementation.

## 9. Errors, decisions and the one limitation I want reviewed

No errors blocked the round, and nothing was blocked by my permission layer.

**Stated limitation, deliberately not papered over.** The strengthened H-03 guard is a positive cardinality invariant and it catches any handover that becomes *operative* — a second `lease.owned_process_group_handle` write point in the §3A matrix, or a declared group count above 1. It does **not** catch a handover asserted only as §3A.3 prose while the cardinality table still says 1 and no §3A edge implements it. That residual case leaves the matrix conformant (a kernel would still have exactly one write point to implement) and is strictly weaker than the original H-03 defect, where the matrix itself performed the handover — but it is a real gap in the gate rather than in the specification, and the verbatim `HANDOVER_WORDINGS` blacklist is retained alongside as a partial complement. Flagging it rather than claiming complete coverage.

**Two judgement calls a reviewer should check rather than take on trust.**

1. The attempt-side release is expressed as durable **retirement of `lease.owned_process_group_handle`** rather than as a new column, because the attempt's terminal disposition is immutable under FC §10.3.1 and rewriting it would corrupt the §3A.2 budget. §3A.3 already described the handle as retired when cleanup is proven, so this makes an existing fact normative instead of adding schema.
2. The dispatch release is `QUARANTINED -> FENCED`, which makes §3B carry one edge out of a terminal state. I scoped it explicitly as changing only the durable cleanup representation, with authority-terminality, the superseded fencing token and `FENCE_STALE` rejection preserved across it, and §3B now says so in terms.

Both are the inbox's preferred shapes, but both deserve an adversarial read.

**Nothing is waiting on the owner from this round.** No decision requiring owner approval was reached, and nothing irreversible or outward-facing was done beyond the single push to the freeze-candidate branch, which the inbox authorised explicitly.

## 10. Exact proposed next step

**Dispatch exactly one fresh, independent, read-only adversarial review bound to the exact SHA `c7c3d523b7bafe5c73ae4d82275e6f1a297600f0`, and nothing else.** The previous `CHANGES REQUIRED` verdict is stale for this SHA, and I have not self-certified. I am not dispatching any further task myself.

That review should be given the identity facts of §5 above and asked to:

1. re-verify identity independently from fresh remote truth — candidate `c7c3d52`, canonical `9e59860`, merge-base equal to canonical, exactly one commit `2f1acc0..c7c3d52`, `DECISIONS.md` byte-identical to canonical, `CURRENT_TRUTH.md`/`ROADMAP.md` byte-identical to `5eb25f8`, no self-adoption;
2. attack **§3D** directly: is occupancy total over the `attempt` disposition enum and the `review_dispatch` state enum? Is there any committed state in which a resource is both released and possibly still held by a live process? Can the release transition be reached without an authoritative emptiness proof, or can it make a stale result admissible?
3. attack the **`QUARANTINED` / `FENCED` split**: is there any path on which a kernel-owned dispatch with unproven cleanup can still be recorded `FENCED`? Can an `EXTERNAL` dispatch be driven into `QUARANTINED` and hold a unit indefinitely?
4. attack **admission**: can a replacement for a quarantined required-review slot be created through `review.request`, `integration.review_request`, or §21 step 8 reconciliation? Can a different subject take the quarantined global reviewer unit? Can task B take the single implementation slot held by a `CLOSED / QUARANTINED` attempt?
5. confirm **R-02, H-03 and H-04 are not weakened** — write-ahead identity, ownership-kind semantics, the one-group/write-once handle, stale/recycled-identity fail-closed behaviour, and attempt-budget accounting kept separate from occupancy;
6. **mutation-test the gate itself**, including the limitation named in §9, and reproduce both the 63-green control at `c7c3d52` and the 11-failed / 52-passed failing-before result against `2f1acc0`.

Working notes for that review: run in `/opt/crooks-builder/.worktrees/freeze-repair`, which is already at the candidate SHA and clean, using `PYTHONDONTWRITEBYTECODE=1 … -p no:cacheprovider -p no:randomly` so `git status` stays at 0 lines; fetch both refs by explicit full refname because the Builder `remote.origin.fetch` refspec is still stale and must not be repaired; do not run the full offline suite from a read-only round, since it writes DBs and workspaces into the tree.
