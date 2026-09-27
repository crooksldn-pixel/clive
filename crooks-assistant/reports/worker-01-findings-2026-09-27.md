# Worker-01 findings, 2026-09-27

From the Claude Code session on clive-worker-01, for the Director. Two subjects: the owner-gated
re-pin of the engineering loop (stopped on review), and the three pytest failures CI reports on
`94663378` (not reproducible on the host). Nothing on the loop has changed: it still runs
`4c32bb3d5f4935402c9cdc897914370950f7f206`, idle.

## 1. Loop re-pin to `a599a447`: stopped, review CHANGES_REQUIRED

The owner chose to pin exactly `a599a44789f950e65e72f66921a0c92862fe3a24` even though
`clive/trunk` had moved past it (it is on the trunk; the ancestry check replaced the "is the head" check).

| Step | Result |
|---|---|
| Fetch with the loop's credential for `origin`; `4c32bb3d` is an ancestor of `a599a447` | ok |
| Gate at `a599a447` (its own code, the loop's credential) | **GREEN**: acceptance run 36255451100 completed with success |
| One Responses API request, gpt-6-luna, effort medium, strict json_schema | HTTP 200, status completed, model gpt-6-luna |
| Exact-SHA review of the scoped diff `4c32bb3d..a599a447`, gpt-6-sol, effort medium | **CHANGES_REQUIRED** (`openai-response:resp_0902f741c1f3b606016ab858fb470487d1a419a5088cdcf99c`) |

Scope of the review: `app/orchestrator/`, `app/remote_engineering`, `scripts/engineering_dispatcher.py`,
`scripts/remote_engineering.py`, `scripts/engineering_kernel.py` and the tests that exercise them
(27 files). The reviewer ran from the loop's current pin (`4c32bb3d`), not from the code under review.

### F-01 (material): the gate can miss a failing pull-request run

> The acceptance gate excludes pull-request workflow runs while treating the returned list as
> complete. A successful push run can therefore produce a green answer even when an acceptance run
> for the same SHA on a pull request is pending or failed.

- Evidence: `crooks-assistant/app/orchestrator/github_acceptance.py`, `GitHubAcceptance.check`
  (`exclude_pull_requests=true`); `test_github_acceptance.py`,
  `test_it_asks_for_exactly_the_acceptance_runs_of_exactly_the_sha_then_each_runs_job`.
- Required repair: include pull-request runs in the workflow-run query and require every returned
  run and its acceptance job to satisfy the exact-SHA gate. Add a client-level regression test with
  a green push run and a pending or failed pull-request run.

This is a real code finding in a protected path; it needs a fix on the trunk before a re-pin.

### F-02 (material): restart on the existing host state not shown

> Restart with the stated, unchanged host flags is not established. The new adapter-root guard
> refuses run when the default `<store>/remote_engineering` directory is unignored in the journalled
> store's work tree [...]. The packet provides neither the host's ignore rule nor a compatible
> migration for its existing claims and receipts, and the unit arguments supply no `--adapter-root`.

- Required repair: demonstrate that the existing host store and flags pass this precondition without
  losing access to recorded claims and receipts, or provide a restart-compatible default and
  migration; test startup and replay using the base-written layout.

**Host evidence (read-only, gathered after the review):** the store's work tree already ignores the
directory. `/srv/clive-engineering/state/.git/info/exclude` line 7 is `/engineering/remote_engineering/`,
and `git check-ignore -v engineering/remote_engineering/x` matches it. The existing `claims/` and
`receipts/` are at the default adapter root. So the precondition should pass with unchanged flags and
no migration. F-02 is missing evidence in the packet rather than a host defect; the next packet will
carry this, and a startup test on this layout would close it for good.

### Next re-pin

After F-01 is fixed and its acceptance run is green, give the new SHA. The same script
(`~/clive-review/repin/root-repin.sh` on the host) re-runs everything: gate, gpt-6-luna request,
fresh gpt-6-sol review, and applies only on READY (pin + `--product-memory-ref origin/clive/trunk`,
no model flags; restart only when no builder or GPT review is running).

## 2. The three pytest failures CI reports on `94663378`: not reproducible on the host

CI's evidence records only `3 failed, 5085 passed, 16 skipped` with no test names. At exactly
`94663378f7fd239b537322fe537de18442d7ba29`, on this host (Ubuntu 24.04, Python 3.12.3, a fresh venv
from `pip install -e ".[dev]"`, `pytest tests -m 'not live' -q -p no:cacheprovider`):

| Run | Result |
|---|---|
| Node 22, git worktree checkout | 5087 passed, 16 skipped, 1 failed (see note) |
| Node 20.20.2 (as the GitHub runner ships), plain clone | **5087 passed, 17 skipped, 0 failed** |

Note: the one failure, `tests/test_capability_gaps.py::test_a_gap_is_followed_from_proposal_to_a_fix_that_held_or_came_back`,
is an artifact of the worktree: `running_sha()` reads `.git/HEAD` as a directory, and in a worktree
`.git` is a file, so it returns "" and the test counts one compare instead of two. It passes in a
plain clone (12/12). It does show the test depends on the real checkout's git state before its
`running_sha` monkeypatch; worth making it independent of that.

So the code at `94663378` passes on an ordinary machine with either Node version. CI's three failures
depend on something specific to the GitHub runner (network, installed tools, timing, or kernel
features such as the namespaces the check sandbox uses). They can't be named from here.

### What would name them

`scripts/acceptance_provenance.py` keeps only pytest's last line in the gate's `detail`, so neither the
job log nor the uploaded evidence names a failing test. Recommend: run pytest with `-rf` in the
`pytest_offline_full` gate and keep the `FAILED ...` lines (bounded) in `detail`. The next CI run then
names them in the log and the artifact. A red gate is not fixable without that.

## Context

- The loop's GitHub credential is a fine-grained token. It has Actions: Read-only (added 2026-09-26);
  fine-grained tokens cannot be given Checks, which is why the gate moved to the Actions API (#33).
- `clive/trunk` was at `3e77f2157a35a23ba69014c1b0161a9351accd48` when this was written.
