# Knowledge from branches that never reached trunk

Why this folder exists: nine branches held documents that never reached `clive/trunk`.
RECONCILIATION_2026-09-25 §3.2 proposed copying them here as history, and on 7 October 2026 that
was done so the branches could be archived (as `archive/…` tags) and deleted. See
[`docs/repo/BOUNDARY.md`](../../../../docs/repo/BOUNDARY.md) for the branch cleanup.

What it promises:

- **Every file is a verbatim copy** of the branch's own file at the commit named below, never
  edited. [`MANIFEST.txt`](MANIFEST.txt) lists each file's blob and source, and
  `tests/test_repo_boundary.py` checks that none has changed.
- **None of it is current.** Each document describes its own date. A status line inside one
  ("ACTIVE", "FREEZE CANDIDATE", "PROPOSED") was true of that day only. What is live now is in
  [`MAP.md`](../../../MAP.md) and
  [`CURRENT_TRUTH.md`](../../product-memory/CURRENT_TRUTH.md); decisions are in
  [`DECISIONS.md`](../../product-memory/DECISIONS.md).
- **Links inside may be broken.** They point at paths as they were on the branch.

## What is here

| Folder | Source branch and commit | What it is |
|---|---|---|
| `2026-09-19-builder-environment/` | `claude/builder-environment-repair-review` at `295e483b` | The 19 Sep builder environment review: a proposed `DESIGN.md` (the UI's design rules), `DEV_ENVIRONMENT.md` for the bridge-era builder worktree, and `dev-environment/` (the browser gate finding, the Claude project layout, contract trial `CONTRACT_TRIAL_ENV_REPRO_001`, later candidates, and the pinned package and binary lists). This branch contains `claude/builder-environment-review` (`9a27bc44`) whole, so the review's documents are here in their repaired form. |
| `2026-09-19-mobile-experience-v1/` | `claude/mobile-experience-v1-review` at `564ef343` | `MOBILE_EXPERIENCE_V1.md`: what the phone layout did on 19 Sep and what the redesign changed. `DESIGN.md` is that branch's copy, with the phone additions (the `--ink-3` contrast fix and the two-row bottom band). |
| `2026-09-19-ops-runbook/` | `chatgpt/ops-memory-2026-09-19` at `028aca1f` (also `chatgpt/memory-reconcile-2026-09-19`, the same commit, and open PR #2) | `OPS_RUNBOOK.md`: the 19 Sep operator and bridge recovery runbook. The bridge it covers was retired on 25 Sep. |
| `2026-09-20-orchestrator-v1-freeze/` | `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20` at `70d0fa17` | The Orchestrator V1 freeze candidate: acceptance matrix, freeze contract, state API, research traceability, and the watcher/builder identity remediation plan. The owner retired that stream on 24 Sep (DECISIONS, "Retirements, 2026-09-24"). |
| `2026-09-22-capability-registry/` | `chatgpt/capability-registry-reconciliation-2026-09-22` at `6a522f8f` | `ENGINEERING_CAPABILITY_REGISTRY.md`, the one document of that branch that never reached trunk. |
| `2026-09-22-recovery-handoff/` | `claude/recovery-handoff-2026-09-22` at `3df126c2` | `RECOVERY_HANDOFF_2026-09-22.md`, the 22 Sep independent audit of what CLIVE engineering was doing, and its two machine-readable companions in `handoff/`. |
| `2026-09-23-product-memory-reconcile/` | `chatgpt/product-memory-reconcile-2026-09-23` at `95227cc2` | That branch's `RECONCILIATION_2026-09-23.md`, with its late-day §18 (dispatcher convergence, the parallel team proof, the split of the publication and release lineages). Trunk's copy at `docs/product-memory/` stops before it and ends with a different §18, a closure addendum. |

## What was not copied, and why

- **The 37 phone screenshots** of `claude/mobile-experience-v1-review`
  (`crooks-assistant/docs/screens/mobile-v1/*.png`, about 10 MB). They show order lists, order
  details and proposals. The document says they were taken against the fixture world, and the
  one checked shows an `example.com` address, but screens of orders are the kind that could
  show customer data, and this repository is public, so none was copied. They stay in the
  archive tag: `git show archive/claude-mobile-experience-v1-review:crooks-assistant/docs/screens/mobile-v1/<name>.png`.
- **Code and tests** on these branches (`scripts/dev_env.py`, `tests/test_dev_env.py`,
  `tests/test_orchestrator_freeze_spec.py`, and the phone branch's CSS, browser script and test
  changes). This folder is for knowledge. The code was superseded and stays in the archive tags.
- **Edits to documents trunk still keeps** (CURRENT_TRUTH, DECISIONS, ROADMAP, README and the
  others): later product memory replaced them. Their texts stay in the archive tags.
- **`config/review_principals.json`** from `claude/recovery-handoff-2026-09-22`: trunk's own
  file replaced it.

Each branch's archive tag is `archive/` followed by the branch name with `/` replaced by `-`, for
example `archive/chatgpt-ops-memory-2026-09-19`.
