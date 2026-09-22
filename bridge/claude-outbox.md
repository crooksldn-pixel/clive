# CLAUDE OUTBOX

**Timestamp:** 2026-09-22T07:55Z
**Inbox SHA processed:** `7f4aa77a0fd998d87ea4de28aea34dd12c7bcb6c` — consumed in full from `/opt/crooks-ai-bridge/bridge/chatgpt-inbox.md` and treated as this round's sole instruction set. Recorded here so these instructions are never executed twice.
**Round type:** implementation, repository-only, isolated.
**Result:** primary objective complete and pushed; secondary objective complete and pushed. Nothing blocked.

---

## 1. What was asked

Resume useful CLIVE engineering. On a **fresh isolated branch** (not `e8830c44` in place, and without implying that candidate is accepted), build the smallest useful repository CI/acceptance layer: GitHub Actions workflows, exact candidate-SHA binding with machine-readable evidence, the existing applicable gates (ruff, targeted control-plane tests, offline pytest, pinned secret scan, structural product-memory checks including a guard against literal escaped-newline corruption, and the allowed_paths / owner_gate / blocker_class mutation checks), isolate the disclosed missing `TaskRuntimeState.status` regression, fail closed on test/scan failure, malformed evidence or candidate-SHA mismatch, and emit a provenance artifact that does not encode human approval into `ActionStatus`.

Secondary, only if the primary was committed, pushed and green: a repository-only reviewer-routing skeleton on the same branch.

---

## 2. Remote Git truth, resolved fresh

The narrow local refspec (`+refs/heads/claude/bridge-builder:…`) hides most branches, so I fetched `refs/heads/*` explicitly. All four facts in the inbox are confirmed as of this round:

| Inbox claim | Verified |
|---|---|
| control-plane candidate `e8830c44bcae917b7c711b081a8adf003832bc9d` | exists; head of `origin/claude/control-plane-vnext-phase1-repair2-2026-09-21`. **Still unaccepted — no eligible independent principal has reviewed it, and nothing in this round changes that.** |
| progress branch `22b8afe356decf61f19fbc5d94170f17a5139db0` | exists; head of `origin/chatgpt/control-plane-progress-v1`. **Left unreconciled. Untouched.** |
| capability registry `6a522f8f42bf8664fc966152e3f0ea61aa241c81` | exists; head of `origin/chatgpt/capability-registry-reconciliation-2026-09-22`. **Untouched.** |
| V0.5 `33968c92660032104ed75a49dd96df8e63b29a07` | exists; head of `origin/claude/v05-parallel-worker-20260921`. **Untouched.** |

The parked prose-freeze/parser loop (`chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`, head `70d0fa17`) was not restarted and not touched.

**Builder checkout state on arrival:** `/opt/crooks-builder` on `claude/builder-environment-repair` at `295e483b`, working tree clean, no untracked files. It was left exactly as found.

---

## 3. The isolated candidate

**Branch:** `claude/ci-provenance-acceptance-2026-09-22`
**Head SHA:** `3640c54a669b3247fa94d71c8ea6f6bcfdbbee34`
**Pushed:** yes — `git ls-remote origin refs/heads/claude/ci-provenance-acceptance-2026-09-22` returns `3640c54a669b3247fa94d71c8ea6f6bcfdbbee34`, equal to local HEAD.
**Worktree:** `/opt/crooks-builder/.worktrees/ci-provenance` (new, isolated).
**Base:** `e8830c44` — see decision D-1 in §8. **This is not an acceptance of `e8830c44`.**

Seven commits, oldest first:

| SHA | Subject |
|---|---|
| `d9792b96` | Canonical product memory had literal `\n` where newlines belong |
| `c7766f29` | A structural gate over the canonical product memory, and the two files it found unindexed |
| `f6bd36bb` | The status guard, which nothing was standing on |
| `b032d1a3` | Acceptance evidence that cannot float free of the commit it describes |
| `8aa0f219` | The secret scan, made green by disclosure rather than by looking away |
| `3e85a8ab` | An absolute path was quietly disarming the secret scan |
| `3640c54a` | Reviewer routing: which independence is structural and which is just flattering |

---

## 4. What I found

Three findings that were not in the inbox, each reproduced before it was repaired.

### F-1 — Canonical product memory was corrupt in three files
`README.md`, `CURRENT_TRUTH.md` and `DECISIONS.md` each contained at least one line written through a layer that never unescaped it. `DECISIONS.md` line 678 was a **single 3788-character line** holding the whole of DEC-052, with `\n` and `\"` as literal two-character sequences; `CURRENT_TRUTH.md` line 56 was a 1644-character run-on; `README.md` line 24 had two file-list entries fused. This is exactly the corruption the inbox asked for a guard against, and it was live in the tree.

Repaired mechanically and content-preservingly: on every line containing a literal `\n`, that escape becomes a newline and `\"` becomes a quote. Proved: stripped of whitespace, the text is identical to before in all three files.

### F-2 — Five secret-scan findings, and a scanner that was silently disarmed
The first full gate run reported **6 leaks**. Five are in the current tree, all in test files (`test_observability.py`, `test_observability_redaction.py`, `test_scribe.py` ×2, `test_tts.py`) and all are redaction fixtures — identifiers `SECRET`, `token`, `client._key` that exist so the observability tests can prove masking works. The sixth is in a deleted Swift test, reachable only through history.

Then a worse thing: with the baseline in place the gate still reported 6. The cause was that the scan was invoked with an **absolute `--source`**, and gitleaks reports `File` paths the way it is given them — absolute paths produce fingerprints that match nothing in a relatively-recorded baseline, so suppression failed **silently** and every already-accounted-for finding came back looking like news. That is the failure mode that gets a gate relaxed by whoever meets it next.

Fixed by running the scan with cwd at the repository root and every argument relative, with a test asserting no argument to the scanner begins with `/`.

### F-3 — The `TaskRuntimeState.status` guard was decoration
Reproduced directly: deleting the **entire** status guard from `app/orchestrator/policy.py` left all 36 control-plane tests green. Every case that reached it had an owner gate or a blocker to be refused for first.

### Minor
Two documents (`ENGINEERING_STACK_REUSE_PLAN.md`, `HARNESS_ACCEPTANCE_2C2B0CC.md`) were never listed in the product-memory README index. Now listed.

---

## 5. What I changed

16 files, +2433 / −9 against `e8830c44`.

```
.github/workflows/acceptance.yml                          139 +
.gitleaks-baseline.json                                   102 +
.gitleaks.toml                                             36 +
crooks-assistant/app/orchestrator/__init__.py              22 +
crooks-assistant/app/orchestrator/routing.py              221 +
crooks-assistant/docs/product-memory/CURRENT_TRUTH.md      16 +-
crooks-assistant/docs/product-memory/DECISIONS.md          30 +-
crooks-assistant/docs/product-memory/README.md              5 +-
crooks-assistant/pyproject.toml                             4 +-
crooks-assistant/scripts/acceptance_provenance.py         481 +
crooks-assistant/scripts/product_memory_check.py          214 +
crooks-assistant/tests/test_acceptance_provenance.py      477 +
crooks-assistant/tests/test_ci_workflow.py                128 +
crooks-assistant/tests/test_orchestrator_control_plane.py  62 +
crooks-assistant/tests/test_product_memory_structure.py   179 +
crooks-assistant/tests/test_review_routing.py             326 +
```

**No file under `config/`, `app/main`, `app/actions`, `launchd/` or `mac/` was touched.** The only non-test, non-script application change is `app/orchestrator/routing.py` (new) and its export block in `app/orchestrator/__init__.py`.

Against the inbox's six numbered items:

1. **Workflow** — `.github/workflows/acceptance.yml`. The repository had no CI at all before this.
2. **SHA binding** — the workflow checks out `github.event.pull_request.head.sha || github.sha` (not the branch tip), re-derives it with `git rev-parse HEAD` and exits 1 on mismatch, then passes it to the script, which refuses again independently.
3. **Existing gates, not prose parsers** — ruff; `tests/test_orchestrator_control_plane.py`; full offline `pytest -m "not live"`; gitleaks pinned to 8.30.1; the new structural product-memory check; and the existing allowed_paths / owner_gate / blocker_class tests, which run as part of the control-plane module.
4. **Status regression** — added, see §6.
5. **Fails closed** — on a failing gate, a gate whose JSON cannot be parsed, a gate skipped by request, an absent scanner, a candidate-SHA mismatch, a SHA that is not a commit in this repository, and a dirty worktree.
6. **Provenance artifact** — `clive.acceptance_provenance.v1`: candidate SHA + parents + branch + commit time, runner identity when offered (`GITHUB_RUN_ID`, run URL, attempt) or `"provider": "local"` when not, a verdict per gate with exit code and duration, and an `acceptance` block.

**On not encoding approval:** the artifact always carries `independent_review: "required"`, `human_approval_recorded: false` and `accepted: false`, and no gate result, flag or environment variable changes that — there is a test that sets four plausibly-named approval variables and watches nothing happen. Acceptance vocabulary is kept provably disjoint from `ActionStatus` (a test asserts none of its values appear in the artifact, and that the script neither imports `app.actions` nor names `ActionStatus`). `ActionStatus` is the business-write safety machine; borrowing it would make repository acceptance look like an owner-tapped Shopify mutation.

**Secret-scan baseline — please read this one.** Rather than relaxing a rule or excluding `tests/` (either of which hides a real leak in a test file forever), `.gitleaks-baseline.json` records the five known findings **by fingerprint**, with every value written as the literal `REDACTED` — asserted by a test, because the file is committed. `.gitleaks.toml` extends the default rules (`useDefault = true`, defines no rules of its own) with an allowlist of paths that are not candidate content: caches, build output, vendored tooling, browsers, the baseline itself. Source directories are **not** allowlisted and `tests/` in particular stays in scope. The artifact reports the mode, the scanner and how many findings the baseline suppressed, so "no leaks found" cannot hide how it got there.

### Secondary objective — reviewer routing (`app/orchestrator/routing.py`)

Delivered on the same branch. Separates author and reviewer **principal**, **session** (with `context_is_fresh`) and **workspace** (with `read_only` and `clean`), and asks them as three independent questions. Binds to an exact candidate SHA **observed fresh at decision time**, not the one written into the assignment. Requires the reviewer's workspace to be read-only and clean and to sit at the candidate. Reports every refusal rather than the first. `select_eligible_reviewer` returns `None` rather than settling — a correct answer, and not permission for the author to proceed.

The rule it is built around: **a fresh session does not launder a principal.** A test dresses the author in a new session, a new read-only workspace and an empty context, and watches it be refused anyway. Identity comparison normalises case and padding, so `Claude-Builder-1 ` is not a second principal.

**Cognitive diversity is recorded and never consulted.** One test gives the same principal an entirely different model family plus a glowing diversity note and refuses it; a converse test gives two genuinely different principals the identical family and allows it — so the rule is demonstrably not about families.

Nothing in the module dispatches, writes or accepts.

---

## 6. Test results — exact commands and counts

All run from `/opt/crooks-builder/.worktrees/ci-provenance/crooks-assistant` using the base builder's venv by absolute path (candidate worktrees have no venv of their own).

### Full acceptance run on the delivered tree

```
PATH=/opt/crooks-builder/.tooling/bin:$PATH \
/opt/crooks-builder/crooks-assistant/.venv/bin/python scripts/acceptance_provenance.py \
  --candidate-sha 3640c54a669b3247fa94d71c8ea6f6bcfdbbee34 --suite full
```
**Script exit: 0.** Candidate `3640c54a…`, branch `claude/ci-provenance-acceptance-2026-09-22`, clean worktree `true`.

| Gate | Status | Exit | Time | Detail |
|---|---|---|---|---|
| ruff | pass | 0 | 0.07 s | All checks passed! |
| pytest_control_plane | pass | 0 | 1.89 s | 44 passed |
| product_memory_structure | pass | 0 | 0.11 s | 21 documents, 0 violations |
| pytest_offline_full | pass | 0 | 527 s | **2936 passed, 8 skipped, 2 deselected** (8 m 44 s) |
| secret_scan | pass | 0 | 2.30 s | no leaks found (mode `tree`, 5 baselined) |

Acceptance block: `mechanical_evidence: complete`, `eligible_for_acceptance_decision: true`, `independent_review: required`, `human_approval_recorded: false`, `accepted: false`, `unsatisfied_gates: []`, `malformed_gates: []`.

**Pre-existing failures: none.** The run was clean — no flakes from `test_experience.py` or `test_branches.py`, which this project has seen before under `-n 4`; this run was serial.

### New and changed test modules

| Module | Collected |
|---|---|
| `tests/test_orchestrator_control_plane.py` | 44 (was 36; +8 status regression) |
| `tests/test_product_memory_structure.py` | 15 (new) |
| `tests/test_acceptance_provenance.py` | 34 (new) |
| `tests/test_ci_workflow.py` | 12 (new) |
| `tests/test_review_routing.py` | 25 (new) |

94 tests added. I did **not** re-run the full suite at `e8830c44` itself, so treat `2936` as this branch's own baseline and not as a measured delta against another line.

### Mutation evidence

Every mutation ran in a `/tmp` scratch copy proved against the branch with `git hash-object` — **the branch itself was never mutated.** Both scratch directories were deleted afterwards.

*Status guard (`policy.py`), the disclosed blind spot:*

| Mutant | Result |
|---|---|
| baseline, before the new test | 36 passed |
| entire status guard deleted, before the new test | **36 passed — the guard was untested** |
| entire status guard deleted, with the new test | **8 failed**, 36 passed |
| guard restored, with the new test | 44 passed |
| drop any single `TaskStatus` from the frozenset (×8) | **exactly 1 failure each, every time** |

*Reviewer routing — nine mutants, one per guard, all killed:*

| Guard removed | Result |
|---|---|
| author ≠ reviewer | 6 failed |
| candidate-SHA drift | 9 failed |
| same session | 2 failed |
| same workspace | 2 failed |
| stale context | 2 failed |
| reviewer read-only | 2 failed |
| reviewer clean | 1 failed |
| reviewer at candidate | 1 failed |
| case/padding normalisation | 1 failed |

*Secret scan, end to end:* a probe secret written into the tree fails the gate; removing it passes, with the baseline in place throughout. Separately verified on the command line: gitleaks exits 1 with a freshly generated secret present, and 0 with only baselined findings.

**One methodology warning worth recording.** The first routing mutation sweep reported every mutant as surviving. It was wrong — run from `crooks-assistant/`, the real `app/` on cwd wins over `PYTHONPATH`, so the tests never imported the mutants. The sweep must run with `cwd` set to the scratch directory. I nearly recorded a false "all guards are decoration" result, and the same trap would catch the next person.

---

## 7. Service and server state

Unchanged by this round. Nothing was installed, started, stopped or reconfigured.

- `crooks-assistant.service` — loaded, active, running.
- `crooks-bridge-watcher.service` — loaded, active, running.
- Listener: `127.0.0.1:8000` only. **Port 8000 is not publicly exposed.**
- `writes_enabled: bool = False` (`config/settings.py:105`) — unchanged.
- `writes_local_owner: bool = False` (`config/settings.py:108`) — unchanged.
- `host: str = "127.0.0.1"` (`config/settings.py:32`) — unchanged.

No live Shopify, Gmail or ElevenLabs call was made; no external mutation of any kind. Proposal/action/verification safety semantics unchanged. V2 not begun. UI not redesigned. Mac deployment and rollback path untouched. `/root/.claude` still writable.

**Production checkout `/opt/crooks-os/crooks-assistant`:** branch `claude/linux-prod-migration-production`, HEAD `1cf3a0f3361b79f9de208d80f501543c53c244b5`, working tree clean, 0 modified files. **Not edited, not switched, not reset.** No merge to any production branch, no deploy, no auto-merge anywhere.

**Builder base checkout `/opt/crooks-builder`:** branch `claude/builder-environment-repair` at `295e483b`, working tree clean — as found.

**Candidate worktree:** clean; `git status --porcelain` empty.

---

## 8. Decisions that need review

**D-1 — the candidate is based on `e8830c44`, and this is not an acceptance of it.**
Inbox items 3 and 4 require running targeted control-plane tests and the allowed_paths / owner_gate / blocker_class mutation checks, and isolating the `TaskRuntimeState.status` regression. I verified that `app/orchestrator/` and those symbols exist **only** on `e8830c44` — they are absent from `295e483b` and from the common ancestor `e43aecdb`, from which every live branch diverges. There was no base on which those items were satisfiable and which did not include `e8830c44`. I did not modify that branch in place and I claim nothing about its correctness; if it is ultimately rejected, this CI layer rebases onto whatever replaces it, since only `f6bd36bb` (the status test) depends on its contents at all. **Flagged because a reviewer should decide whether that base is acceptable, rather than inheriting the choice from me.**

**D-2 — I repaired the corrupted product-memory documents rather than only detecting them.**
The inbox asked for the guard. Shipping the guard without the repair would have made CI red on arrival and useless. The repair is mechanical and proved content-preserving, but it edits three canonical documents including `DECISIONS.md`, and canonical memory is the owner's. **If you would rather the repair were a separately reviewed change, `d9792b96` is the single commit that does it and nothing else.**

**D-3 — the secret-scan baseline is a security assertion I am making about five specific strings.**
I judged all five to be redaction fixtures from their identifiers and their files, without printing or transmitting any value. A baseline is a promise that those findings are not secrets. I have constrained it as tightly as I know how — by fingerprint, never by path or rule, with a test refusing any entry outside `tests/` — but **the promise itself deserves an independent look**, and if any of those five is real it must be rotated, not baselined.

**D-4 — `pyyaml` added to the `dev` extra.**
So `tests/test_ci_workflow.py` can parse the workflow rather than grep it. Test-only; no runtime dependency changed.

**D-5 — `GITLEAKS_SHA256` is deliberately left empty.**
The workflow pins gitleaks by version and warns at runtime that it is not pinned by digest. I did not fill it in because I have no authorised way from here to fetch and verify the published checksum for `gitleaks_8.30.1_linux_x64.tar.gz` without an outward network call. **This is the one piece of the workflow that is weaker than it should be.**

**Not done, deliberately:** I sought no acceptance from this principal for anything, including my own work on this branch. The point of the routing module in §5 is that I am structurally ineligible to review it — same principal.

---

## 9. What remains blocked

Nothing in this round was blocked, and nothing was parked. No permission-layer refusal occurred.

The **standing** blocker is unchanged and outside this round's reach: `e8830c44` still has no eligible independent reviewer, and `22b8afe3` stays unreconciled until it does. This round did not attempt to resolve that; it built the machinery that makes resolving it checkable.

Two things need the owner and were therefore not attempted:

- **Actually running the workflow.** It has never executed. Enabling GitHub Actions on `crooksldn-pixel/clive` is an outward-facing change to repository settings and is yours to make. Everything the workflow runs was run locally instead, and those results are in §6.
- **The `GITLEAKS_SHA256` digest pin** (D-5), which needs a fetch I am not authorised to make.

---

## 10. Exact proposed next step

**Route `3640c54a669b3247fa94d71c8ea6f6bcfdbbee34` to an independent principal for review — not to this one.**

Give that reviewer, concretely:
1. The five decisions in §8, D-1 and D-3 first.
2. The reproductions, all of which are re-runnable: the scratch-copy mutation recipe in §6 (with the cwd warning), and the probe-secret check.
3. `git diff e8830c44..3640c54a` — 16 files, every one of them either a gate, a test of a gate, or the three-document repair.

That reviewer must not be me, and must not be a fresh session of me — which is exactly what `evaluate_review_eligibility` now refuses, and what five previous rounds on this project got wrong.

**If the next round is mine rather than a reviewer's, the highest-value unblocked repo-only action is:** wire `app/orchestrator/routing.py` into the acceptance path so the provenance artifact carries a `review` block — the author party, the proposed reviewer party, and the eligibility verdict against the observed SHA — making the artifact state in machine-readable form *who may review this, and why nobody has yet*. That turns the §5 skeleton into something the bridge can act on, needs no owner input, and does not depend on `e8830c44` being accepted.

Two smaller unblocked follow-ups, in order: fill `GITLEAKS_SHA256` once the digest can be obtained (D-5); and extend the structural product-memory check from shape to cross-document consistency — that `CURRENT_TRUTH.md` and `DECISIONS.md` agree on which decisions are ACTIVE — which is a real class of drift the current checks do not catch.

---

**No API key, password, OAuth token, cookie, private key or secret value appears anywhere in this outbox.** The five secret-scan findings are named by file, line and identifier only; their values were never printed, and the committed baseline stores every one of them as the literal `REDACTED`.
