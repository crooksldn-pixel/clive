# CLAUDE OUTBOX

**Timestamp:** 2026-09-20T16:34:10Z
**Inbox blob SHA processed:** `6b647f2fc42eda31d68cb95364d50690b5df1db4` — consumed as this round's sole instruction set. Recorded here so the same instructions are never executed twice.
**Round type:** bounded repository-only repair (H-03 / H-04) on the existing freeze-candidate branch. Not owner adoption, not runtime remediation, not production work, not Orchestrator implementation.

---

## 1. What was asked

Perform exactly one bounded repository-only repair round on `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, repairing the two blockers the independent review raised against the rejected candidate:

- **H-03** — eliminate the process-group handle overwrite. Adopt the smaller *single per-attempt owned process group, write-once handle* design; `STARTING -> RUNNING` must not update the cleanup handle; close the adjacent identity-reuse ambiguity without prescribing a platform.
- **H-04** — make the reviewer process identity write-ahead too; decide external-vs-kernel-owned from durable principal kind rather than from a NULL process-group identity; branch §6 step 3 on ownership first.

Plus: preserve all prior findings, add H-03/H-04 traceability, prove the new tests fail against the exact rejected SHA, recompute the standing invariants, report SHAs/diff/tests/clean worktree/secret scan/remote readback, publish only to the freeze-candidate branch, and do not self-certify.

## 2. Preconditions verified before any edit

Resolved from fresh remote truth via `git ls-remote` with explicit full refs (the builder's tracking refs are known-stale; they were not trusted).

| Check | Required | Found | Verdict |
| --- | --- | --- | --- |
| candidate head | `9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f` | `9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f` | exact match |
| canonical base | `9e59860a945ec339c69af8709cd0721f0a795327` | `9e59860a945ec339c69af8709cd0721f0a795327` | exact match |
| merge-base(candidate, base) | equals canonical | `9e59860a945ec339c69af8709cd0721f0a795327` | equals canonical |
| worktree state | clean, no owner work | `git status --porcelain` = 0 lines | clean |
| unrelated owner work | none | diff vs base = the known candidate surface only | none present |

No reset, clean, stash or discard was performed at any point.

**Builder checkout inspected first, as instructed:** `/opt/crooks-builder` was on `claude/builder-environment-repair` at `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, working tree clean, nothing modified or untracked. The repair was done in the already-registered worktree `/opt/crooks-builder/.worktrees/freeze-repair`, which was already on the candidate branch at the rejected SHA and clean. Nothing about the builder checkout was assumed from a previous run.

## 3. What I found

Both findings reproduced exactly as the review described them.

**H-03.** `ORCHESTRATOR_V1_STATE_API.md` §3A.3 gave `lease.owned_process_group_handle` two population times — the preflight group on `CREATED -> STARTING`, then *updated* to the model process group on `STARTING -> RUNNING` — with no requirement to prove the preflight group empty before the overwrite. Between the overwrite and any later cleanup, a preflight child that outlived preflight is named by no durable field: §6 verifies emptiness of the model group only, and freeze contract §11's "workspace reuse is forbidden until emptiness is verified" then passes vacuously over the wrong set of processes. This also stood as a direct contradiction between two normative documents — §11 gave each attempt **one** cgroup covering the "complete attempt process tree" while §3A.3 gave it **two** with a handover.

Additionally confirmed: the existing test `test_pre_running_cleanup_handle_and_ceiling_discriminator_are_distinct_facts` *asserted* the handover wording (`assert "CREATED -> STARTING" in cleanup[2] and "STARTING -> RUNNING" in cleanup[2]`), so it locked the defect in and had to change with the fix rather than being left as a passing regression guard.

**H-04.** `review_dispatch`'s process-group/cgroup identity had no write-ahead ordering — §3A.3 was scoped to `attempt` only, even though §1A claimed its rules applied "uniformly to all three" execution records. NULL on that field was overloaded in the *opposite* direction from the attempt handle: it meant "external principal, do not signal". A controller crash between reviewer fork and identity persistence is therefore indistinguishable from an external reviewer, so §6 step 3 skipped it, released the required-review slot and the freeze contract §19 reviewer-concurrency unit, admitted a replacement, and left a live kernel-owned reviewer running untracked. That also defeats §3.1 `[EXEC-FENCE]`, which depends on §6 having actually stopped the group before the subject transition commits.

## 4. What I changed

One commit, five files, on the freeze-candidate branch only.

**H-03 — single owned group, write-once handle.**
- `lease.owned_process_group_handle` is now write-once: committed before the attempt's single owned process group is created on `CREATED -> STARTING`, and never updated, replaced or cleared while the attempt is non-terminal.
- The `STARTING -> RUNNING` row now carries an explicit prohibition ("MUST NOT update, replace or clear"), launches the model **inside the attempt's existing owned process group**, and states that no second group is created. The two-group handover wording is deleted from every freeze document.
- `attempt.running_process_group_identity` remains the write-once ceiling discriminator, read only by §3A.2, and is explicitly forbidden from being promoted into the cleanup role.
- Preflight and model execution share one group, so cancellation, restart and emptiness checks cover the whole of it; §6 step 5 now verifies the **entire** owned group is empty, and freeze contract §11 states one group per attempt and requires emptiness over that whole group ("an emptiness proof over any narrower group does not satisfy this rule"). A surviving preflight descendant can no longer become invisible.
- Identity-reuse ambiguity closed without prescribing a platform: the handle MUST be a controller-allocated, attempt- or dispatch-bound identity (a per-record cgroup path or equivalent is given as an example, not a mandate) and MUST NOT be a bare recyclable OS process-group number. §6 re-verifies that the group a handle resolves to is still this record's **before signalling**; a failed check is never signalled and falls through to the fail-closed outcome (`QUARANTINED` for an attempt, `FENCED` + subject BLOCKED for a dispatch). Stale-handle reuse therefore fails closed and can never kill an unrelated recycled process.

**H-04 — kernel-owned reviewer is write-ahead; ownership comes from the principal.**
- §3A.3 is restated as normative for **all three** execution records, which is what makes §1A's "uniformly to all three" mechanically true rather than aspirational.
- The reviewer principal/session identity now carries a declared **execution-ownership kind `KERNEL_OWNED|EXTERNAL`**, committed durably in the same transaction that creates the `DISPATCHED` row — before any reviewer process exists — and immutable thereafter. No new schema: this is a declared attribute of the existing principal/session binding, as the inbox permitted.
- A `KERNEL_OWNED` dispatch commits its process-group handle before creating the reviewer group, under the same write-ahead/write-once/controller-allocated discipline as an attempt. NULL there is positive proof that no owned reviewer group exists — explicitly **not** a signal that the reviewer is external. An `EXTERNAL` dispatch is always NULL and fencing-only, with the limitation recorded.
- §6 step 3 now branches on reviewer ownership/principal kind **first**, then identifies, ownership-verifies and signals. Fencing-only is reachable *only* through an `EXTERNAL` principal.
- §6's release rule is pinned to "step 6 **and never step 7**", so neither the required-review slot nor the §19 reviewer-concurrency unit is released while a kernel-owned orphan may exist, and no replacement reviewer can be admitted. Freeze contract §21 step 8 reconciles on the same terms and names the exact crash: "A crash between the reviewer-handle commit and the reviewer fork is therefore reconciled as a kernel-owned dispatch with no group, not as an external reviewer." Freeze contract §15 states the same ordering for sibling-reviewer fencing.

**Acceptance and traceability.**
- **ST-16** gains a *surviving-preflight-child* arm: fork a preflight child that outlives preflight, let the attempt reach `RUNNING`, assert the handle holds exactly its `STARTING` value and the model joined that same group, then cancel/restart-fence and assert §6 finds the child through the one write-once handle, that emptiness is proved over the whole group rather than a model-only group, and that workspace reuse stays forbidden until the entire group is empty. Explicitly states R-02's attempt-budget semantics are preserved.
- **ST-17** gains a *kernel-owned reviewer crash* arm (crash after the durable handle commit, both before and after reviewer fork, then `candidate.reject`; prove the reviewer is stopped before `REJECTED` commits or the subject is BLOCKED, and prove slot/concurrency are not released) and an *external-principal negative* arm (fencing-only, limitation recorded, reachable only via the external principal kind).
- Traceability gains explicit **H-03** and **H-04** dispositions. The H-02 row's resolution text was corrected where it still described the now-deleted two-group handover; the finding description itself is unchanged.

**Files changed (5):**

```
 crooks-assistant/docs/product-memory/ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md |   6 +-
 crooks-assistant/docs/product-memory/ORCHESTRATOR_V1_FREEZE_CONTRACT.md   |  12 +-
 crooks-assistant/docs/product-memory/ORCHESTRATOR_V1_STATE_API.md         |  71 ++++--
 crooks-assistant/docs/product-memory/ORCHESTRATOR_V1_TRACEABILITY.md      |   4 +-
 crooks-assistant/tests/test_orchestrator_freeze_spec.py                   | 242 ++++++++++++++++++++-
 5 files changed, 300 insertions(+), 35 deletions(-)
```

`DECISIONS.md` is byte-identical to canonical base `9e59860` (verified by empty diff). `CURRENT_TRUTH.md` and `ROADMAP.md` were not touched this round.

## 5. Exact SHAs

| | SHA |
| --- | --- |
| canonical base | `9e59860a945ec339c69af8709cd0721f0a795327` |
| rejected candidate | `9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f` |
| **new candidate** | **`2f1acc0b7edd233735e419d92cfbade914b0042f`** |
| merge-base(new, base) | `9e59860a945ec339c69af8709cd0721f0a795327` (equals canonical) |

Commit subject: *"One process group per attempt, and a reviewer the kernel can still find after a crash"*.

## 6. Test results

**Committed freeze-spec suite at the new SHA:** `51 passed` in 0.73s (was 38 at `9fbe4a9`; +13 new, of which 4 are parametrizations of the handover-wording guard across the freeze set).

**Failing-before evidence against the exact rejected SHA `9fbe4a9`** — produced without modifying owner work, by materialising the rejected tree's docs into a scratch directory via `git archive 9fbe4a9 crooks-assistant/docs/product-memory` plus the candidate test module:

- Provenance proved blob-by-blob, `git hash-object` == `git rev-parse 9fbe4a9:<path>`:
  - `ORCHESTRATOR_V1_STATE_API.md` → `4a12ba4de3499cfa389f0c12917d85723c89bbcf`
  - `ORCHESTRATOR_V1_FREEZE_CONTRACT.md` → `73de0f4b971598b1d47f4504a941c7b455eb3a28`
  - `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md` → `2513f531fc54212646abcaae1bbf8b0dc16e64d7`
  - `ORCHESTRATOR_V1_TRACEABILITY.md` → `727a3d3725d4e1279277cc34b720e7c572d4a257`
- Result: **14 failed / 37 passed**. The failures are the defect-bearing ones, and they fail *because the rejected tree contains the handover wording*, not merely because it lacks new prose:
  `test_pre_running_cleanup_handle_and_ceiling_discriminator_are_distinct_facts`,
  `test_no_freeze_document_retains_the_two_group_handover_wording` (STATE_API, FREEZE_CONTRACT, TRACEABILITY — the acceptance matrix never carried it, so that parametrization correctly passes),
  `test_the_running_commit_must_not_replace_the_cleanup_handle`,
  `test_one_group_per_attempt_agrees_across_the_contract_and_the_state_api`,
  `test_cleanup_handles_are_controller_allocated_and_reuse_fails_closed`,
  `test_review_dispatch_records_a_durable_reviewer_ownership_kind`,
  `test_kernel_owned_reviewer_handle_is_write_ahead_and_null_is_not_externality`,
  `test_section_six_branches_on_reviewer_ownership_before_it_signals`,
  `test_restart_reconciliation_treats_a_forkless_kernel_reviewer_as_kernel_owned`,
  `test_the_substrate_rules_really_do_apply_to_all_three_execution_records`,
  `test_acceptance_arms_exist_for_both_repaired_findings`,
  `test_traceability_dispositions_every_reviewed_finding`.

**Mutation testing — the gate is non-vacuous.** In a separate scratch holding the *repaired* docs, each defect was re-introduced individually:

| Mutation | Result |
| --- | --- |
| M1 — restore the handover on `STARTING -> RUNNING` (the exact H-03 defect) | 2 failed, 49 passed |
| M2 — delete only the §6 ownership-re-verification clause | 1 failed, 50 passed |
| M3 — re-overload NULL as externality in the `review_dispatch` record | 1 failed, 50 passed |
| M4 — control, mutation reverted | 51 passed |

So the new tests bind to the specific normative claims rather than to incidental wording.

**Full offline suite at the new SHA:** `2857 passed, 8 skipped` in 224.57s (`pytest tests -m "not live" -q -n 4`). This is the expected `2844 + 13`; the doc-only candidate branch baseline was 2837/8 at `5eb25f8` with 31 spec tests, and `9fbe4a9` carried 38. Teardown emits harmless asyncio `Event loop is closed` noise from subprocess fixtures, as in previous rounds. **No regressions.**

**Lint:** `ruff check tests/test_orchestrator_freeze_spec.py` → All checks passed. (`ruff format` is not a repo gate and was not run across the repo.)

**Recomputed standing invariants — all green at the new SHA, via the committed suite:**
- zero dangling acceptance IDs (every referenced test ID resolves to a real matrix row);
- complete §18A MUST coverage — every MUST-bearing numbered section is dispositioned, and no MUST hides in an unnumbered subsection;
- every non-terminal attempt state has a terminal cleanup/fencing edge;
- delivery enum ↔ §3C mutually complete;
- no self-adoption (`DECISIONS.md` contains no freeze-candidate reference; the contract still declares itself a candidate until the Owner adopts an exact SHA);
- no DEC-046/DEC-047 sequencing drift (`DECISIONS.md` byte-identical to canonical base; `ROADMAP.md` untouched);
- §3.1 token/derivation behaviour intact, and the N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03, G-01..G-03, H-01, H-02 regression guards all still pass.

Two notes on the gate's own constraints, which shaped the wording rather than the design: the pre-existing guard forbidding MUSTs outside numbered sections meant §3A.3's new subsections are bolded lead-ins rather than `####` headings (which would have created new indexable sections requiring §18A entries), and the record-schema blocks point at §3A.3 rather than restating its MUSTs. Both are the gate working as designed; I did not weaken it.

## 7. Clean worktree, secret scan and remote readback

- **Worktree clean:** `git status --porcelain` in `/opt/crooks-builder/.worktrees/freeze-repair` = **0 lines** after commit and after the full suite run. Scratch directories used for failing-before and mutation evidence were outside the repo and have been removed.
- **Secret scan on the changed-file set:** gitleaks 8.30.1, `--redact --no-git --exit-code 1`, over `crooks-assistant/docs/product-memory` (~440 KB) and the changed test module (~69 KB) → **no leaks found**, exit 0 in both cases. No secret value is printed anywhere in this handoff.
- **Push:** `9fbe4a9..2f1acc0 HEAD -> chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`. Only the freeze-candidate branch was pushed.
- **Exact remote readback:** `git ls-remote origin refs/heads/chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` → `2f1acc0b7edd233735e419d92cfbade914b0042f`. Canonical base re-read unchanged at `9e59860a945ec339c69af8709cd0721f0a795327`.

## 8. Service and server state

- `crooks-assistant.service`: **active**, **enabled**. Not restarted, reloaded or reconfigured this round.
- FastAPI listener: `127.0.0.1:8000` only. Port 8000 is **not** publicly exposed.
- `config/settings.py`: `writes_enabled: bool = False` — unchanged. `CROOKS_WRITES_LOCAL_OWNER` is not set on the unit and remains false.
- Production checkout `/opt/crooks-os/crooks-assistant`: **untouched and not entered for any write**. Read-only inspection only — branch `claude/linux-prod-migration-production`, HEAD `1cf3a0f3361b79f9de208d80f501543c53c244b5`, `git status --porcelain` = 0 lines.
- Builder main checkout `/opt/crooks-builder`: still `claude/builder-environment-repair` at `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b`, clean. Not switched or reset.
- No merge to any production branch, no deploy, no auto-merge. No systemd/watcher/builder-runtime change. The stale builder fetch refspec was **not** repaired (explicitly forbidden this round); branches were fetched by explicit full refname instead.
- No live Shopify, Gmail or ElevenLabs call, no live external mutation, no MCP/connector change, no privilege expansion, no public exposure, no external spend. V2 not begun, UI not redesigned, Mac deployment and rollback path preserved, `/root/.claude` still writable.

## 9. Errors

None that persisted. Four test failures occurred mid-round on first run and were resolved before commit:

- two were defects in my own new tests (a `.lower()` comparison against a mixed-case literal, and a wrong acceptance-matrix table header string) — fixed in the test module;
- two were the pre-existing freeze gate correctly catching my edits: the `####` subheadings I had added inside §3A.3 put MUSTs outside any indexable numbered section, and I had introduced MUSTs into the `attempt`/`lease` record-schema blocks, which the gate forbids by design. Both were fixed by rewording the documents to satisfy the existing gate, not by relaxing the gate.

No permission-layer blocks were encountered. Nothing was attempted that required widening permissions.

## 10. Decisions and questions needing review

- **No owner approval was sought or recorded, because this round required none.** Nothing in the inbox asked for a service install/start, secret provisioning, Tailscale activation, live verification, or any irreversible or outward-facing action. The single outward action taken — pushing to the freeze-candidate branch — is what the inbox explicitly instructed ("Publish only to the freeze-candidate branch").
- **Design decision worth a reviewer's attention:** H-04 is repaired *without new schema* by declaring `KERNEL_OWNED|EXTERNAL` as an attribute of the already-durable reviewer principal/session identity, as the inbox's "or equivalent existing principal/role identity" allowed. A reviewer may reasonably want to confirm that this is genuinely no-new-column rather than a column in disguise; I judged it an attribute of an existing binding, committed in the transaction that already creates the `DISPATCHED` row.
- **Deliberately not widened:** the identity-reuse repair states a requirement (controller-allocated, attempt-/dispatch-bound, ownership re-verified before signalling, failing closed) and gives a per-record cgroup path only as an example. No platform-specific implementation is prescribed, per the inbox's constraint.
- **Carried forward, non-blocking, unchanged by this round:** §7 still has no dedicated reason code for ceiling exhaustion or delivery epoch/digest refusal; `BLOCKED/ESCALATED → task.plan → PLANNED` carries no ceiling guard; the attempt counter has no declared storage column; `QUARANTINED` from `STARTING` still consumes the ceiling even though it never reached `RUNNING` (deliberate, fail-closed).

## 11. Verdict status and the exact proposed next step

**I do not self-certify this repair.** The previous independent-review verdict is **stale for the changed SHA**: it was bound to `9fbe4a9212ef8a509856b8ff7fb75b78c253dc5f`, which is no longer the candidate head. It carries no authority over `2f1acc0b7edd233735e419d92cfbade914b0042f` and must not be read as covering it.

**Exact proposed next step:** dispatch **exactly one** fresh, independent, read-only adversarial review bound to the exact new SHA `2f1acc0b7edd233735e419d92cfbade914b0042f` on branch `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` in `crooksldn-pixel/clive`, against canonical base `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`. That review should focus on H-03 and H-04 as repaired here, confirm the N/B/R/F/G/H-01/H-02 regressions are intact, and re-check that the new structural tests are not false greens — the mutation evidence in §6 is offered as a starting point, not as a substitute for its own adversarial check.

I have **not** dispatched that review or any other task, as instructed. This round is complete and awaiting that single review.

**Inbox SHA processed:** `6b647f2fc42eda31d68cb95364d50690b5df1db4`
