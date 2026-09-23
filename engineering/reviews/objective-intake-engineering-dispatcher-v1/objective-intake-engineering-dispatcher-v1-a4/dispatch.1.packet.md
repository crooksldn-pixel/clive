# CLIVE review packet — objective-intake-engineering-dispatcher-v1 r3 (repair of D-01), attempt a4

```json
{
  "task_id": "objective-intake-engineering-dispatcher-v1",
  "task_revision": 3,
  "task_kind": "repair",
  "attempt_id": "objective-intake-engineering-dispatcher-v1-a4",
  "candidate_sha": "d2cecbd285ac15b5a5cca09bd1ce667b4c094231",
  "rejected_candidate": "da15c629e95ad7ff27903d417f63f16b78f467bb",
  "base_sha": "18c3153a2eec10c6343153b550776afed3bec2ba",
  "target_branch": "claude/objective-intake-dispatcher-v1-uz8g7z",
  "author_principal": "claude",
  "author_session": "session_01TupGArGERqu9aRQJ41Sce5",
  "reviewer_principal": "gpt",
  "review_mechanism": "bootstrap manual handoff (owner relays)",
  "state_record": "clive/engineering-state"
}
```

Your verdict applies to exactly `d2cecbd285ac15b5a5cca09bd1ce667b4c094231`. The candidate fast-forwards the rejected `da15c629` with three commits:

- `68e872a4`: the D-01 repair;
- `dcd7d745`: an adjacent defect found while proving the repair, disclosed below as ADJ-01;
- `d2cecbd2`: tests and doc only, repairing CI red at `dcd7d745` (see "CI" directly below).

Attempt a3, whose candidate was `dcd7d745`, was cancelled on the kernel for that CI failure. Any verdict on `dcd7d745` is stale and would be refused. Product code (`app/`, `scripts/`) is byte-identical between `dcd7d745` and `d2cecbd2`.

## CI

**The red run.** Acceptance run `35874441460` at `dcd7d745` failed with `pytest_offline_full: 3 failed, 3175 passed, 8 skipped, 2 deselected, 4 errors`. The run at `da15c629` (`35865643668`) was green, so none of the failures are pre-existing.

**The cause.** The `ubuntu-latest` runner (non-root `runner` user) cannot establish the check sandbox, and the dispatcher correctly failed closed there. But my sandbox tests demanded a working sandbox on every host:

- 4 errors: the escape tests' fixture called `pytest.fail` when the sandbox was unavailable.
- 3 failures:
  - two dispatcher tests ran their checks through the real sandbox and so blocked;
  - the escaping-canary test got "could not be established" instead of "canary escaped".

The runner's exact canary reason is not printed by the provenance gate. The likely cause is Ubuntu 24.04's restriction on unprivileged user namespaces. A faithful local simulation (`unshare` present, the kernel refusing the uid map, no code path short-circuited) reproduces exactly 3 failed and 4 errors at `dcd7d745`.

**The repair (tests only).**

- The escape tests skip where the sandbox cannot be established, with the canary's exact reason. They fail when `CLIVE_REQUIRE_CHECK_SANDBOX=1`, meant for the dispatcher's own host.
- A new test proves the kernel-refusal path fails closed on every host.
- Dispatcher logic tests use an explicit runner double (`TreeRunnerForTests`).
- The sandbox-backed dispatcher test requires the sandbox.

**Green at `d2cecbd2`.** Acceptance run `35877264585`: success, with `pytest_offline_full: 3177 passed, 14 skipped, 2 deselected`. That is 8 skips before plus the 6 predicted sandbox skips. Ruff, control plane, product-memory structure and secret scan pass.

**What green CI does and does not prove.** It proves fail-closed behaviour and the dispatcher's logic. Escape resistance is proven here: 12/12 sandbox and trust-boundary tests as root, with 0 leftover processes, and the non-root user-namespace mode was exercised earlier. It must be proven on the dispatcher's own host (`CLIVE_REQUIRE_CHECK_SANDBOX=1`) before objectives with checks run there.

## Lifecycle

- Your CHANGES REQUIRED on `da15c629` was admitted on the kernel as `rejected_by_verdict`, at `reviews/…/objective-intake-engineering-dispatcher-v1-a2/verdict.1.json`, and r2 is REJECTED.
- r3 (`kind: repair`, same base) was routed for D-01 only. Its scope is r2's plus exactly `app/orchestrator/checks.py` and `tests/test_check_sandbox.py`. Its required evidence is r2's plus `sandbox_escape_tests`.
- r3 was assigned a3 (token 3), with the workspace at base, then fast-forwarded to the rejected candidate.
- a3's candidate `dcd7d745` was cancelled for CI red. r3 was reassigned as a4 (token 4), with the workspace at base, then fast-forwarded to `dcd7d745`. The test repair was made there.

Kernel, principal registry and `config/` are unchanged: `git diff --name-only 18c3153a dcd7d745 -- app/orchestrator/{lifecycle,contracts,policy,routing,review_acceptance,review_result_gate,store,state}.py scripts/engineering_kernel.py config/` prints nothing. The no-programmatic-GPT truth is unchanged.

## D-01 repair: worker-authored checks run only in an OS sandbox

**The seam.** `app/orchestrator/checks.py` holds the `CheckRunner` protocol (`availability()`, `run(argv, tree, cwd, timeout_s)`). `Dispatcher` takes a `checks: CheckRunner`; the default is `NamespaceSandbox()`. The old host `_run_check` (`subprocess.run(check.argv, cwd=workspace)`) is gone. `dispatcher.py` `_run_check` now exports the candidate, then calls `self.checks.run`.

**What a check gets from `NamespaceSandbox`.** The mechanism is util-linux `unshare`, then `chroot`, then `setpriv`. bwrap and nsjail are absent on this host, and docker has no daemon.

- **Tree.** A fresh export of exactly the committed candidate (`WorkspaceManager.export`: `read-tree` + `checkout-index` from the attempt's git dir). It is never the live workspace, so a check cannot alter the tree that becomes the candidate.
- **Filesystem.** Private mount namespace with a tmpfs root holding:
  - `/usr`, `/bin`, `/sbin` and `/lib*`, read-only binds;
  - a curated `/etc` (passwd, group, hosts, nsswitch.conf, ld.so.cache, localtime);
  - private `/proc`;
  - `/dev/{null,zero,random,urandom}`;
  - operator-named read-only dirs (`--check-ro-path`, e.g. the virtualenv).

  The writable places are the tree and a 512 MB private `/tmp`. Nothing else of the host exists inside.
- **Network.** An empty network namespace.
- **Identity.**
  - Dispatcher is root (this host): the check drops to uid/gid 65534 via `setpriv --reuid/--regid --clear-groups`.
  - Dispatcher is not root: a user namespace over the dispatcher's own uid.
  - Both modes: `--inh-caps=-all --bounding-set=-all --no-new-privs`. Both modes were exercised here.
- **Resources.** Wall-clock timeout, CPU, address space (4 GiB), file size (1 GiB), open files (1024), and processes (512, when the check has its own uid).
- **Timeout.** On timeout the dispatcher SIGKILLs the check's PID-namespace init, and the kernel kills every process in the namespace.
- **Fail-closed canary.** `availability()` runs a canary inside that must:
  - fail to read a world-readable host sentinel;
  - fail to leave a file at a host path (checked on the host, not self-reported);
  - fail to connect to a listener on the host loopback, and to 1.1.1.1:443;
  - run as the expected uid with `CapEff == 0`;
  - be able to write its tree.

  Any failure, or a missing `unshare`, makes the runner unavailable. The dispatcher then blocks the task with "check sandbox unavailable … never run unsandboxed". There is no fallback.

**Adversarial regressions, `tests/test_check_sandbox.py`.** Hostile candidate test code runs under the virtualenv's real `pytest` inside the sandbox. Every property is asserted from the host side:

1. **Read.** A world-readable host sentinel is FileNotFound. So are `/etc/shadow` and `/root`. `/proc/1/environ` holds only the sandbox's own variables.
2. **Write.** Writes to a host path, `/usr`, `/etc` and `/` leave nothing on the host. The sandbox's `/tmp` is private.
3. **Network.** A real listener on the host's 127.0.0.1 accepted nothing, and 1.1.1.1:443 failed.
4. **Identity.** uid 65534, `CapEff 0000000000000000`.

Further cases:

- The root holds only the minimal set (no `root`, `opt` or `home`), and `/etc` holds only the curated files.
- Timeout: a `setsid`-escaped background loop dies with the namespace, and 0 processes are left over.
- A `cwd` escape is refused (exit 126).
- An unestablishable sandbox, a missing `unshare`, and an escaping canary are each unavailable and refuse to run.

Dispatcher-level tests:

- `test_checks_run_in_the_sandbox_on_a_copy_and_cannot_touch_the_candidate_tree`;
- `test_without_a_sandbox_checks_never_run_and_the_task_blocks`: the runner is never called, and no candidate is recorded.

**Found by that suite and fixed in the same commit.** `unshare --kill-child` did not bound the timeout. The kernel clears the parent-death signal when `setpriv` changes the uid, so background loops survived. Five were found alive on the host after the first run. That is why the repair kills PID 1 of the namespace (`checks.py` `_kill_namespace`).

## D-01 adjacent boundary: git metadata the worker cannot reach

- **Layout** (`workspaces.py`). The attempt's git directory is a sibling of the worker's tree (`<root>/<task>/<attempt>.git/`, a bare local clone, remote removed, used with an explicit `--work-tree`). The tree contains no `.git` of CLIVE's.
- **Every CLIVE git command on an attempt** names `--git-dir`/`--work-tree`, with `GIT_CONFIG_NOSYSTEM`, `GIT_CONFIG_GLOBAL=/dev/null`, `core.hooksPath=/dev/null` and `core.fsmonitor=false`.
- **`test_nothing_the_worker_writes_in_its_tree_can_steer_clives_git`.** The fake worker plants:
  - `.git/config` with an fsmonitor command, a hooksPath and a filter driver;
  - executable `.git/hooks/post-commit` and `pre-commit`;
  - `pkg/.gitattributes` with `* filter=evil`;
  - a `pkg/.git` gitlink file.

  None runs, no sentinel appears, and the candidate tree contains no `.git` path. **This test fails against r2's `workspaces.py`.**
- **The real worker's reach, observed** (Claude Code 2.1.280, the adapter's exact flags, code at `dcd7d745`). All of this is in the `real_worker_smoke` evidence:
  - **Write probe.** Writes to `<attempt>.git/hooks/post-commit` (new file), an absolute host path, and `.git/config` in its own tree were denied by the tool layer and listed in `permission_denials`. On the host: git config unchanged, no hook, no outside file, no `.git` in the tree. Only the in-tree file was written.
  - **Read probe** (benign, so model willingness plays no part). `Read` of the existing `<attempt>.git/config` and `<attempt>.git/HEAD` returned "… is outside <cwd>" as tool errors, both in `permission_denials`. The in-tree Read succeeded. So the confinement is path-based for existing files too.
  - **Not counted.** A read-then-overwrite request that the model declined on its own is behaviour, not boundary evidence.

## ADJ-01 (disclosed; found while proving the repair; commit `dcd7d745`)

The dispatcher found worker processes by `CLIVE_ATTEMPT_ID=<attempt id>` across all host processes. Attempt ids are unique only within one store. So two dispatchers or stores on one host could take each other's live worker for their own, refuse to launch, or kill it. This showed up as failures when the suite ran three times concurrently.

The marker is now `<attempt id>/<session uuid>`, where the session is the one CLIVE chose and the kernel recorded at assignment. The regression `test_a_worker_of_another_store_with_the_same_attempt_id_is_never_taken_for_ours` fails with the attempt-only marker and passes with the fix. Three concurrent runs of the suites now pass (39/39 each).

The defect was present in `da15c629`. Neither your review nor my earlier tests caught it. I fixed it here rather than leaving a known correctness defect, and it is small: the marker helper in 3 code files, plus its regression test and one doc sentence.

## Evidence (on the kernel for a4; names and sha256 in the store; the a3 evidence stays as history)

- `unit_tests`:
  - on this host: 82 passed (dispatcher 32, intake 21, adapter 21, sandbox 8);
  - on the simulated runner: 76 passed, 6 skipped;
  - three concurrent runs: 40/40 each.
- `sandbox_escape_tests`: the 12 sandbox and trust-boundary tests, all passing as root. Leftover processes after the timeout tests: 0.
- `kernel_regression`: kernel, control-plane and product-memory structure tests, 112 passed. Kernel and authority files are unchanged.
  - Local full suite at `d2cecbd2`: `1 failed, 3181 passed`. The failure is `test_memory` prefetch, which fails on the pristine base locally and passes in CI.
  - CI at `d2cecbd2` is green (run `35877264585`).
- `lint`: `ruff check .` clean.
- `real_worker_smoke`: a real haiku worker at `dcd7d745`, throwaway store, default `--reviewer gpt`:
  - objective, then r1, then assigned;
  - acknowledged from init (tools Edit/Glob/Grep/Read/StructuredOutput/Write, no MCP);
  - progress;
  - the check ran in the sandbox ("uid 65534, no capabilities; canary held", exit 0);
  - evidence ×3, then candidate `c2703a7b`: parent `18c3153a`, the tree has no `.git`, the git dir is beside it with no remote;
  - BLOCKED with the GPT gap.

  It also carries the write and read boundary probes above.

## Limits, stated in ENGINEERING_DISPATCHER_V1.md

- **Kernel sharing.** The sandbox is namespaces on the host kernel, not a VM.
- **Host support.** On a host where the dispatcher is not root *and* unprivileged user namespaces are disallowed (e.g. Ubuntu's `apparmor_restrict_unprivileged_userns`), the canary fails. Objectives with checks then block with that reason. How the dispatcher runs there is an owner decision.
- **Worker confinement.** Keeping the worker out of its git dir rests on Claude Code's `--restricted` path boundary, which was observed and recorded above.

## How to answer

Return one `clive.review_result.v1` JSON object for `d2cecbd285ac15b5a5cca09bd1ce667b4c094231` (`app/orchestrator/reviewers/base.py`), or prose for this bootstrap task. `READY` or `CHANGES_REQUIRED`; each material finding carries `finding_id`, `evidence_ref` (file:line at this SHA) and a bounded `required_repair`. The `reviewer` workspace is read-only, clean, at `d2cecbd285ac15b5a5cca09bd1ce667b4c094231`.
