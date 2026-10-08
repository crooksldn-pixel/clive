# Objective Intake + Engineering Dispatcher V1

Status: repository-only implementation, awaiting independent exact-SHA review. It authorises no deployment, no runtime, service, watcher or systemd change, no secret, no permission or connector change, no business write and no spend. It does not by itself prove the no-courier milestone. That milestone is met only when a separate, real, bounded product objective enters through this intake and reaches independently reviewed COMPLETE, BLOCKED or OWNER_GATE without anyone relaying messages between workers.

Code: `app/orchestrator/objectives.py` (intake), `app/orchestrator/dispatcher.py` (controller), `app/orchestrator/workspaces.py`, `app/orchestrator/checks.py` (the check sandbox), `app/orchestrator/generated.py` and `config/generated_files.json` (the loop's generators, part 3), `app/orchestrator/workers/` (builder drivers), `app/orchestrator/reviewers/` (typed review result and reviewer drivers), `scripts/engineering_dispatcher.py` (the CLI). The kernel is used, unchanged, at `18c3153a2eec10c6343153b550776afed3bec2ba`: `Kernel`, `LifecycleStore`, `PrincipalRegistry`, `GitFacts`, `lifecycle_view`, `journal_preconditions`, `git_journal`.

## Division of responsibility

CLIVE keeps the meaning. The kernel's records are the only lifecycle state. Those records hold:

- the objective and task identity, and the revision and attempt with its fencing token;
- the authority (the objective's scope, prohibited actions and authority class);
- the evidence and the candidate SHA;
- review dispatch, verdict admission, acceptance and integration;
- blockers and owner gates.

The execution machinery can be replaced. That covers the worker process, its flags and environment, the stream parser, the workspace clone, the reviewer transport and retry pacing. A driver returns observations; the dispatcher maps them onto kernel verbs. Swapping Claude Code for another runner, or the relay reviewer for a programmatic one, touches one driver and no lifecycle code.

## Intake

`engineering_dispatcher.py objective --title … --objective "…" --base-ref … --allowed-path … [--acceptance …] [--check NAME=CMD [--check-cwd NAME=DIR]]`

It writes `objectives/<id>.json` (an immutable `clive.engineering_objective.v1`) under the kernel's store root, using the kernel's writer lock and git journal. Then `Kernel.create_task` records task revision 1. The owner's words are stored verbatim as `requested_outcome` and are never parsed. Everything that decides authority is a structured field:

- base SHA (resolved from the ref at intake), target branch (default `clive/objective/<id>`) and product-memory SHA;
- allowed paths: required and non-empty. They may never cover the frozen kernel, the dispatcher itself, the principal registry, the roster, launchd/secrets scripts, `.github` or the `engineering/` store, nor, since the loop update (see "Loop update part 2" below), the product safety core, the evidence tools and the loop's own code;
- prohibited actions: the defaults cannot be removed;
- `authority_class: repository_only`, the only value that exists;
- checks as argv without a shell;
- `max_repair_rounds` (default 2, the convergence doctrine).

Required evidence is always `worker_report`, `worker_transcript` and `check-<name>` for each check. Intake is idempotent for identical bytes, and a changed objective under the same id is refused.

Owner provenance is recorded as declared (`os_user`, `host`, `channel: cli`) with `origin_verified: false`. A shell on the host proves the host account, not the owner. That is the same limit the kernel states for owner judgments, and it is why an objective can only authorise repository-only work.

## The controller

`tick` holds `<runtime>/dispatcher.lock`, so only one dispatcher runs. It re-reads every record and advances each objective by the transitions its latest revision allows (at most 12 per tick):

| Stage (kernel) | What the dispatcher does | Kernel verbs |
| --- | --- | --- |
| READY | A build revision with no attempt yet whose base declares generated files outside its scope first becomes revision r+1 with exactly those files added (part 3); a declaration the loop will not run blocks here. Then: check the retry budget and backoff (from the kernel's cancellation records) and the concurrency limit. Create a fresh workspace at the base, assign with a CLIVE-chosen session id, launch. | `task` r+1 / `block` / `assign` |
| ASSIGNED | Wait for the worker's own `system/init` event and check it against the launch policy. A pass is the acknowledgement. A widened surface, or a launch with declared checks whose roster lacks `run_checks` or its connected server, stops the worker and blocks. No init within `init_timeout_s` stops the worker and cancels (transient). | `ack` / `block` / `cancel` |
| RUNNING | Stream events renew the lease. A successful Edit/Write is progress, and edits seen before a result are flushed as progress before the candidate. No event for `stall_s`: stop, cancel (transient). Process gone with no result: diagnose; authentication is deterministic, anything else transient. On a result, the worker is stopped first; then see below. Every stop is confirmed (see "Stopping a worker"). | `heartbeat`, `heartbeat --progress`, `evidence`, `candidate`, `cancel`, `block` |
| EVIDENCE_READY | Wait (bounded) for a green GitHub acceptance run on the exact candidate SHA; no green within the bound blocks; red routes a repair revision carrying the failure while repair rounds remain, and blocks once they are used (part 3). Then choose the first configured reviewer that is registered `may_review`, is not the author principal, and whose driver says it can actually be reached. If none: block with every gap named, and dispatch nothing. | `dispatch` / `block` / `task` r+1 |
| REVIEWING | Read the typed result. A result naming another task, revision or attempt is refused at the door. A READY is submitted only while the candidate SHA is green on GitHub (otherwise it waits unconsumed, or the task blocks). Everything else goes to the kernel, which admits, rejects or refuses it. | `verdict` / `block` |
| REJECTED | Route a repair revision (`kind: repair`, same base, scope and evidence) that names the admitted verdict record. After `max_repair_rounds`, block and leave the next move to the owner. | `task` r+1 / `block` |
| ACCEPTED | Verify the accepted SHA is green on GitHub, then that the target ref resolves to it (the remote's with `--publish-remote`). If it has moved, block. The gate's answer is the integration's `gates_evidence`. | `integrate` (fast-forward) / `block` |
| DONE | The projection says COMPLETE only when acceptance and integration agree. With landing on (the default since part 3), the loop lands the integrated SHA on `clive/trunk`, or, if the trunk moved, routes a refresh revision (`kind: integration`) that merges the trunk into the objective's branch. | — / `task` r+1 |
| BLOCKED, OWNER_GATE | Nothing. The dispatcher never lifts either. | — |

When a worker result arrives (`completed`), these steps run in order, and nothing earlier in the list is skipped:

1. CLIVE commits whatever the worker left in the tree (the worker has no git and cannot commit).
2. The candidate is `git rev-parse HEAD`. If the tree is unchanged, the result is refused.
3. The candidate is fetched into the dispatcher's repository as `refs/clive/candidates/<attempt>` and verified to be exactly that SHA.
4. The changed paths are read from `git diff --no-renames`. None may be a protected path, whatever the task's scope says.
5. The generators the task's base declares (`config/generated_files.json`, part 3) run in the check sandbox on a fresh export of the candidate; a declared output they changed is committed on top as the loop's own commit, which becomes the candidate (steps 3 and 4 again). A change a generator made to anything else blocks the task.
6. Every changed path must fall inside the objective's scope, except a declared output, which is accepted only as exactly the generator's output on this candidate.
7. Each check runs in the check sandbox (see "Check sandbox") on a fresh export of exactly the committed candidate, never on the live workspace, and its output is evidence. If the sandbox cannot be established, the task blocks and no check runs.
8. The transcript and report are recorded as evidence.
9. The target branch moves fast-forward only (and is pushed, with `--publish-remote`). It is never the trunk (`clive/trunk`): a candidate is not yet green, reviewed or accepted, so the loop refuses to publish one onto a landing branch.
10. `candidate` records the exact SHA with every required evidence name.

An out-of-scope tree, a failed check or an empty tree cancels the attempt (`result_refused:`) and never becomes a candidate. The next attempt's prompt says why. After `max_result_refusals` the task blocks.

Worker outcomes map to lifecycle outcomes like this:

- `blocked` → BLOCKED (deterministic);
- `owner_decision_required` → OWNER_GATE (OWNER_ONLY). This is the safe direction: the worker can stop work, never start it;
- a structured error → transient or deterministic, by its API status and subtype, never by prose.

## Loop update part 2: the GitHub acceptance gate, protected paths, product memory from the trunk

Status: built in the repository for the owner's loop update ([OWNER_DECISIONS_2026-09-25.md](./OWNER_DECISIONS_2026-09-25.md), "Loop update"; part 1, the builder's `run_checks`, landed as PR #22). **It is not in force on any host.** It takes effect only through the owner-gated re-pin of a loop to a trunk commit that carries it, after that commit's own green GitHub acceptance run and exact-SHA review. A loop still running an older pin behaves as before.

### The GitHub acceptance gate

The owner's rule: an objective counts as accepted, and a landing may happen, only after a green GitHub acceptance run on that exact SHA. Code: `app/orchestrator/github_acceptance.py` (the gate) and three calls in `app/orchestrator/dispatcher.py`.

- **What is asked.** Through the Actions API, because a fine-grained token cannot be granted the Checks permission but can be granted Actions: read for one repository (found at the 2026-09-26 re-pin on clive-worker-01): `GET /repos/{repository}/actions/workflows/acceptance.yml/runs?head_sha={sha}`, then, for each run that concluded success, `GET /repos/{repository}/actions/runs/{run_id}/jobs?filter=latest` to confirm its `acceptance` job ran on that SHA and succeeded. The workflow checks out and tests exactly the commit it runs for. `repository` is the objective's; `sha` is the kernel's candidate or accepted SHA, never a reviewer's claim.
- **Green, and only green:** at least one run of the acceptance workflow exists for the SHA, every one has completed and concluded `success`, and in every one the `acceptance` job itself ran on that SHA and concluded `success`. Anything else fails closed and is named: `missing` (no run yet), `pending` (a run not completed), `red` (any completed run with another conclusion, including `cancelled` and `skipped`, even beside a green duplicate; or a run that succeeded without its `acceptance` job succeeding, e.g. a skipped job), `unavailable` (GitHub unreachable or refusing, an answer of the wrong shape, a run of another workflow or for another commit, a list shorter than GitHub's own count, or a gate that raised). A push and a pull-request run on one SHA are both counted; a workflow run carries its latest attempt, so a re-run replaces the earlier attempt.
- **Where it is applied.** (1) Before review dispatch: nothing is reviewed until its exact SHA is green, and the review packet carries the gate's answer. (2) Before a READY verdict is submitted to the kernel, which is the moment the kernel records an acceptance: a READY waits unconsumed while the SHA is not green; a CHANGES_REQUIRED is admitted at once, since a rejection accepts nothing. (3) Before integration, on the accepted SHA; this also holds any acceptance recorded before the gate existed.
- **By hand, too.** The kernel CLI (`scripts/engineering_kernel.py`) holds the same gate on the two verbs that record an acceptance or a landing: `verdict --verdict ready` asks about the attempt's exact candidate SHA, and `integrate` about the integrated SHA and the accepted SHA. Any answer but green refuses the verb before it writes anything to the store (exit 2), with a message that names the SHA, the gate's answer, where the answer was recorded and what to do next (re-run the workflow, push the SHA, wait for the run, or check the remote's credential). A one-shot command does not wait: it is run again once the SHA is green. `repair_required` is not held. There is no bypass flag. The CLI records each answer exactly where the dispatcher does, under the dispatcher's runtime lock (`--runtime-root`, default `/opt/crooks-workers/runtime`; exit 4 when a tick holds the lock longer than `--lock-timeout`), and asks with the credential git holds for `--github-remote` (default `origin`).
- **Bounded waiting.** GitHub is asked about a SHA at most every `acceptance_poll_s` (60 s). `red` blocks the task at once, except at review dispatch, where since part 3 it routes a repair revision while the objective's repair rounds remain (and blocks, as before, once they are used). `missing`, `pending` and `unavailable` wait; a step that has waited `acceptance_timeout_s` (3600 s) for its SHA blocks the task with the last answer. The start of each wait is an execution note, so it survives a restart. A blocked task is resumed with the kernel's `resume`; the wait then starts again, and a remembered answer is never reused across a resume. Every waiting tick logs `<step> waits for a green GitHub acceptance run on <sha> (<state>: <detail>)`. A dispatcher built without a gate blocks every candidate before review: there is no "off". **A remembered green answer never authorises anything** (the 2026-09-26 re-pin review, F-01): dispatching a review (the 2026-09-30 re-pin review, F-01: a green answer remembered from a tick whose dispatch the kernel refused must not start a review later), admitting a READY verdict, which records the acceptance, and integrating each ask GitHub again at that moment, because a re-run or an outage may have turned the SHA pending, red or unavailable inside the poll interval. Only a remembered answer that is not green may be reused inside the interval, since it authorises nothing.
- **Where the answer is recorded.** Each answer, with the SHA it is about, its state, a sentence the gate built itself, the run ids and GitHub's status and conclusion words, and when it was asked, goes to the attempt's runtime notes (`github_acceptance`) and to `<runtime>/evidence/<attempt>/github-acceptance.json`. The green answer is in the review packet (whose digest the kernel's dispatch record holds). An integration's `gates_evidence` is the green answers it rests on, kept byte for byte in `<runtime>/evidence/<attempt>/integration-gates.json` (schema `clive.integration_gates.v1`, with the digest of any `--gates-evidence` file an operator gives the kernel CLI); the kernel's integration record holds the digest of exactly those bytes. The remote loop's status projection publishes it per request as `github_acceptance`, and `status` shows it. Nothing GitHub wrote (titles, summaries, URLs) and no credential is ever recorded or published.
- **Credential.** None of its own; it needs **Actions: read** on the repository (a fine-grained token), or a classic token's `repo` scope, which reaches every repository the account can and is broader than the loop should hold. The gate reuses the credential git already holds for the publish remote (`--publish-remote`, else `origin`; for the remote loop, else `--remote`): `git credential fill` with prompts and askpass programs off, answered from the remote URL or a configured credential helper. It is sent only to `api.github.com`, only as a bearer header, and only when the remote is an https URL of exactly the objective's repository on github.com. With an ssh remote, or no stored credential, the gate asks without one: that reads a public repository (60 requests an hour per address, so about one waiting SHA at a time) and fails closed on a private one.
- **Head SHA, not merge result.** The workflow checks out `github.event.pull_request.head.sha || github.sha` and refuses any other commit, so a green run on SHA X means X's own tree passed, never a merge result. The loop's integration is fast-forward only: the kernel refuses a fast-forward integration unless the integrated SHA is exactly the accepted SHA, and the gate runs on that same SHA, so what the loop integrates is exactly what was green. A builder never targets `clive/trunk`: an objective's candidate lives on its own branch, a task targeting the trunk is blocked before any work, and `_publish` refuses the trunk as a target. Since part 3 the loop's own landing step moves the trunk, under exactly the rule below, and nothing else of the loop does; with `--no-land` landing into the trunk is the Director's step, outside the loop. For it to meet the owner's rule, the green SHA must be what lands: land it only when the current trunk head is an ancestor of the green SHA (a fast-forward lands exactly that SHA; a merge commit then has exactly its tree). When the trunk has moved on and the candidate does not contain it, the merge is a new SHA that has not been tested: integrate first (an `integrate` objective, whose merge is its own candidate, gated and reviewed like any other) or merge on a branch and land that SHA only once it is green itself.

### Protected paths

`PROTECTED_PATHS` (repository-root relative; a directory entry protects everything beneath it) now also holds the product safety core (`crooks-assistant/app/tools/gate.py`, `crooks-assistant/app/readonly.py`, `crooks-assistant/app/tools/shopify_writes.py`, `crooks-assistant/app/tools/gmail_writes.py`, `crooks-assistant/app/actions`), the evidence tools (`crooks-assistant/scripts/acceptance_provenance.py`, `.gitleaks.toml`, `.gitleaks-baseline.json` at the repository root, `crooks-assistant/pyproject.toml`) and the loop's own code (`crooks-assistant/app/remote_engineering`, `crooks-assistant/scripts/remote_engineering.py`, and the new gate, `crooks-assistant/app/orchestrator/github_acceptance.py`). Part 3 adds the loop's generator declaration and the module that runs it (`crooks-assistant/config/generated_files.json`, `crooks-assistant/app/orchestrator/generated.py`) and their tests (`test_loop_generated.py`, `test_loop_landing.py`). The owner's decision names them relative to `crooks-assistant/`, except the two gitleaks files, which live at the repository root.

The tests that hold all of that are protected with it, so a builder that cannot change the safety core cannot weaken what proves it either. They are listed one by one in `PROTECTED_PATHS`, each chosen by the protected code its own source imports or loads, never by a pattern over `tests/`: the gate (`test_gate.py`), the read-only latch (`test_readonly.py`), the Shopify write funnel (`test_cancel.py`, `test_refund.py`, `test_address.py`, `test_fulfil.py`, `test_inventory.py`, `test_tracking.py`, `test_order_edit.py`), the Gmail write funnel (`test_gmail_writes.py`, `test_compose.py`), the action engine and the judgment ledger (`test_actions.py`, `test_actions_routes.py`, `test_engine_hooks.py`, `test_batch.py`, `test_available.py`, `test_judgment.py`, `test_judgment_construction.py`, `test_judgment_chain.py`, `test_judgment_ledger.py`), the evidence tools (`test_acceptance_provenance.py`, `test_ci_workflow.py`), and the kernel, dispatcher, objectives, workers, reviewers, remote loop and gate (`test_lifecycle_kernel.py`, `test_orchestrator_control_plane.py`, `test_review_acceptance.py`, `test_review_result_gate.py`, `test_review_routing.py`, `test_engineering_objective_intake.py`, `test_engineering_dispatcher.py`, `test_engineering_kernel_gate.py`, `test_check_sandbox.py`, `test_builder_check_server.py`, `test_claude_worker_adapter.py`, `test_gpt_reviewer.py`, `test_remote_engineering.py`, `test_github_acceptance.py`), all under `crooks-assistant/tests/`. `tests/conftest.py` is protected as well, because its autouse fixtures run inside every one of them. `test_engineering_objective_intake.py` checks that the list and the imports agree.

- An objective may still name any other test file, including a new one beside a protected test. What it can no longer name is `crooks-assistant/tests` as a whole, because that directory holds protected tests: name the test files the change touches.

- Intake refuses any objective whose allowed paths are, contain or lie beneath one of them, as before, through the same `Objective` door the remote inbox and the bridge use.
- An objective recorded before its scope became protected still loads (the store reads records without that one rule, so one old record cannot stop the dispatcher reading every objective), but the dispatcher blocks it before it can launch, dispatch, admit, route a repair or integrate, naming the protected paths. A worker already assigned to or running on it is stopped and the task blocked at the next tick, rather than left to work on until its candidate is refused (the 2026-09-30 re-pin review, F-02). The stop is confirmed like every other (see "Stopping a worker").
- A candidate that changes a protected path is refused (`result_refused:`) whatever the task's scope says; this covers a worker that was already running when the update took effect.

### Product memory from the trunk

The default `--product-memory-ref` of `engineering_dispatcher.py objective` and `integrate`, and of `remote_engineering.py poll` and `run` (where it was a required flag), is `origin/clive/trunk`, where canonical product memory has lived since the 2026-09-25 consolidation. A host's unit file that passes the old ref explicitly keeps it until the re-pin changes it.

## Loop update part 3 (2026-09-30): generated files, red runs as repair rounds, the loop lands its own work

Status: built in the repository under the owner's decisions of 30 September ([OWNER_DECISIONS_2026-09-30.md](./OWNER_DECISIONS_2026-09-30.md): the "go" to fix builds that die for reasons unrelated to their code, and "Filing is switched on, and the loop lands its own work"). **It is not in force on any host.** It changes the loop's own code, so it takes effect only at the owner-gated re-pin, after its own green run and exact-SHA review.

Why: on 30 September six of seven builds the owner filed were BLOCKED with GitHub acceptance red, and the only failure was `tests/test_tool_matrix.py::test_the_checked_in_document_is_the_generated_one`. Any new test file can change the generated `docs/phase4/TOOL_MATRIX.md`; a builder may not regenerate it; red blocked a task at once, and nothing went back to a builder, so re-filing failed the same way every time.

### 1. Generated files are the loop's job

- **The declaration.** `crooks-assistant/config/generated_files.json` (schema `clive.generated_files.v1`, a protected path) lists each generator as a name, an argv, a cwd and its output paths. The first is the tool matrix: `{python} -c "import sys; sys.path.insert(0, '.'); from experience import tool_matrix; tool_matrix.write()"` in `crooks-assistant`, output `crooks-assistant/docs/phase4/TOOL_MATRIX.md`, as `make tool-matrix` writes it. `{python}` is the builders' check interpreter: the one the objective's declared checks name (else `DispatcherConfig.generator_python`, else the dispatcher's own).
- **Read from the base, never the candidate.** The declaration is read from git's objects at the task's base commit (for a refresh, the trunk head it merges; never a candidate), so a builder cannot add a generator that runs anything. A declaration that is malformed, or names a protected path as an output, blocks the task before any builder is spent.
- **When and where it runs.** After the builder reports and CLIVE commits its tree, before CLIVE's own checks: each generator runs through the check runner (the namespace sandbox: no network, bounded, no capabilities) on a fresh export of the candidate. Nothing runs on the host or on the live tree. Before a generator runs, its declared outputs are removed from that copy. Whatever is at an output afterwards is therefore only what the generator wrote, never the builder's own bytes read back as its output (the b577bc97 re-pin review, F-01). Two cases refuse the candidate:
  - a generator that exits 0 without writing a declared output;
  - an output path the builder made into a link, a non-directory on the way, or a directory. Nothing such a link names is followed or removed.
- **What comes back.** Only the declared outputs, each read as a regular file with no link on its way. If an output differs from the candidate's, the loop commits it onto the candidate branch as its own commit, `Regenerate generated files (loop)` by `CLIVE loop <loop@clive.invalid>`, written with git plumbing and proved to change exactly those paths. That commit is the candidate SHA the checks, GitHub, the reviewer and the landing see. A generator that fails refuses the candidate (`result_refused:`; the next attempt is shown its output). A change a generator made to any other file is discarded and blocks the task: it would be a surprise.
- **Scope, and its one narrow exception.** The kernel reviews a candidate only inside its task's scope, and a builder's scope never names a generated file. So before a build revision's first attempt the dispatcher records revision r+1: the same task with exactly the declared outputs that lie outside its scope added, saying why (repairs and refreshes are created with them). The dispatcher still judges a candidate against the objective's own scope, and accepts a declared output outside it only as exactly the generator's output on that candidate; a builder's own edit of one is replaced. The builder's prompt lists the outputs under `GENERATED BY CLIVE` and leaves them out of its allowed paths.
- **Evidence.** `generate-<name>.json` (argv, exit, output tails, the files it changed) and `generated.json` (worker head, candidate, loop commit, regenerated and unchanged outputs), recorded with the kernel as evidence `generated`; the review packet lists the regenerated files; `status` reports them as `generated`.
- **Refresh merges.** The integrator treats a merge conflict confined to declared outputs as none: it takes the trunk's copy and the loop regenerates the file from the merged tree. Two builds that each add a test no longer conflict on the tool matrix.

### 2. A red GitHub run is a repair round

- At review dispatch a red answer routes a repair revision (`kind: repair`, starting from the red SHA), the kernel's existing repair route. The dispatcher records its own block first (reason `red GitHub acceptance, repair routed: …`), because the kernel lets a new revision supersede a live one only once it is blocked, then the repair revision; a restart between the two completes it.
- **What the next builder is told.** Fetched through the gate client with the gate's own credential (`GitHubAcceptance.failure_log`): the red run's jobs, the failed job (the `acceptance` job first), and `GET /repos/{repo}/actions/jobs/{job_id}/logs`, whose redirect to a signed URL is followed without the credential. From the log: pytest's short summary (the FAILED and ERROR lines), the failing assertion lines (`E …`), and at most 4 KB of its tail, all redacted through the check server's secret redaction and credentials in URLs, with GitHub's timestamps and colours removed. The run and job URLs are built from GitHub's ids. If the log cannot be fetched, the repair still goes, with the run URL, the job and step names, and a line saying the log could not be fetched. Recorded at `<runtime>/evidence/<attempt>/github-failure.json`.
- **Bounded.** Review repairs and GitHub repairs share `max_repair_rounds`. Once they are used, red blocks as it always did, naming the last failure (the failing tests and the job, never raw log text). It is never an owner gate: GitHub acceptance is the loop's gate, not an owner decision, and the repair prompt tells the builder not to report `owner_decision_required` for it.
- **Only a run that failed its tests is repaired.** A repair goes only when a completed run concluded `failure` or `timed_out`. A run GitHub cancelled, never started (`startup_failure`) or let go `stale`, or a success whose acceptance job never ran, is red but leaves nothing for a builder to fix. It blocks as red always did, spends no repair round and fetches no log (the #70 pre-review).
- **A red that routes a repair is asked at that moment.** At review dispatch a remembered red answer is not reused: GitHub is asked again, so a run re-run green since is seen and the candidate goes to review instead (the #70 pre-review). A restart between the `red GitHub acceptance, repair routed` block and its repair revision completes the decision made on that fresh red.
- **Not "rerun until green".** Every repair is a new SHA made by a builder; the loop never re-runs a job. Integration and landing still ask afresh and refuse red, and a READY verdict still waits for, or is refused by, the gate exactly as before.

### 3. The loop lands its own work

After the integration onto the objective's branch, at most one landing per tick, under the dispatcher's exclusive lock, the loop fast-forwards `clive/trunk` to exactly the integrated SHA only when all of these hold:

- (a) GitHub acceptance is green on that exact SHA, asked afresh at that moment (pending waits, bounded by `acceptance_timeout_s`, then the landing is refused; red refuses);
- (b) its independent review was READY, the kernel accepted it, and it was integrated fast-forward at exactly that SHA;
- (c) the whole diff from the trunk head to it touches no protected path, checked again at landing with `protected_paths_in`, and the task's base is already on the trunk: the review packet shows only base..candidate, so a base ahead of the trunk (a Director's unlanded branch) would carry commits no reviewer saw, and the landing is refused for the Director (the #67 review);
- (d) it already contains the current remote trunk head, so the push is a plain `git push --quiet <publish-remote> <sha>:refs/heads/clive/trunk`, never forced (`landing_push_argv` refuses anything else), which git refuses if the trunk moved. The remote trunk is then read back and must equal the SHA.

The loop lands only SHAs it integrated itself while landing was on. Before integrating it writes an intent, and it marks the SHA eligible only once the kernel has recorded the integration. A restart between the two promotes the SHA only when the kernel's record says the loop integrated it (`integrated_by` begins `clive-dispatcher (`), no earlier than the intent. An integration an operator records after the loop's own was refused or interrupted is never the loop's to land (the b577bc97 re-pin review, F-01). Work completed before the re-pin, or with `--no-land`, stays the Director's to land. Records: `<runtime>/landings/<objective>.json` (state, SHA, reason, the SHAs eligible, the push intent) and `<runtime>/evidence/<attempt>/landing.json` (trunk before and after, the push argv, the gate's answer, the review). The push intent is written before the push, so a restart between the push and its record records the landing without pushing again; if the trunk has moved away from an interrupted push, the loop never pushes that SHA, or any other for it, again.

**Already on the trunk.** Sometimes the trunk already holds the SHA when the loop comes to land it. That happens when the loop's own push was interrupted by a restart, or when someone else put it there. Either way the loop pushes nothing, and it records a landing only on a green GitHub answer about that SHA, asked at that moment:
- red refuses it for the Director;
- pending waits, within the same bound as any other landing.

The record says who put it there (`by`):
- `loop` only for a push the loop saw git accept. The moment git accepts it, the loop adds `pushed_at` to the push intent, so a restart after that point knows the push was its own.
- `unconfirmed` when the loop wrote an intent but never saw git accept the push. The intent is written before git runs, so on its own it proves nothing: git may have refused the push, or someone else may have pushed the same SHA.
- `other` for anyone else.

Neither `unconfirmed` nor `other` is ever counted as the loop's landing (the 2c8d2caf re-pin review, F-01, and the #70 pre-review). CLIVE says "on the trunk, put there by someone other than the loop" or "the loop began pushing it, but cannot tell whether its push or someone else's put it there".

**If the trunk has moved** (the SHA does not contain its head), the loop routes a refresh: revision r+1 of `kind: integration`, based on the trunk head, run by the integrator in a fresh workspace made by the loop, merging the objective's integrated SHA; the dispatcher records the merged tree as a merge commit whose parents are the objective's SHA and the trunk head, runs the generators on it, checks it and pushes it to the objective's branch. That merge SHA needs its own green acceptance and its own READY review, through the normal path, before it can land. A conflict blocks it: `merging the trunk into <branch> conflicts in <paths>; the Director resolves it`. Refreshes are bounded (`DispatcherConfig.max_landing_refreshes`, default 3); after that the landing is refused for the Director.

**At the re-pin.** A build revision gains the generated outputs in its scope only before its first attempt. A build that already had an attempt when this update took effect, or a repair the older loop routed, does not gain them, so whenever regeneration changes a generated file its candidate is refused as outside its scope. Re-file such a build once; nothing unsafe follows from it.

**The switch.** Landing is on by default. `--no-land` on `scripts/engineering_dispatcher.py tick` and `run` and on `scripts/remote_engineering.py run` and `poll` (poll never advances the dispatcher; it takes the flag so a unit can pass one set), or `DispatcherConfig.land = False`, is exactly the loop as it was: nothing lands and nothing is refreshed. The refusal of the trunk as a builder's target (`landing_branches`) stays either way.

### Status contract

`Dispatcher.status()` rows keep every key they had and gain:

- `attempts`: every attempt of the objective, oldest first, as `{"attempt_id", "revision", "outcome", "reason", "at"}`, where `outcome` is `launched`, `cancelled`, `refused` (CLIVE refused its result), `candidate` or `blocked` (a resume restores what it was before the block);
- `repairs`: `{"review": n, "ci": n, "max": max_repair_rounds}`, the repair revisions routed from a review and from a red GitHub run (they share `max`);
- `generated`: the output paths the loop regenerated for the current revision's candidate;
- `landing`: `null` while there is nothing to land yet, else `{"state", "sha", "at", "reason", "by"}`. `state` is one of `off` (landing switched off), `waiting`, `landed`, `refused` or `refreshing`. A refresh stays `refreshing` while a repair of its merge is under way. `by` is set only for `landed`: `loop`, `unconfirmed` or `other`.

## Loop update part 4 (2026-10-07): findings to whoever repairs, more rounds, skills and a browser for builders

Status: built in the repository under the owner's approval of 7 October 2026 ("Loop upgrades as protected PRs: publishing findings, findings fed back, more repair rounds, skills and a browser for builders"). **It is not in force on any host** until the owner-gated re-pin of clive-worker-01 to a trunk commit that carries it. Nothing here weakens exact-SHA review, the GitHub gate, protected paths, secret scanning or acceptance; no review is added per round.

1. **Why a build stopped, kept privately.** Since 7 October the repository is public, so the status branch keeps counts and fixed words (`app/remote_engineering/status.py`, unchanged). For each objective whose task is BLOCKED or at OWNER_GATE, `Dispatcher.stop_reports()` builds `clive.stop_report.v1` from the records the loop already keeps: the cause as one fixed word (`stop_cause`: `review_limit`, `github_red`, `builder_blocked`, `checks_failed`, `owner_decision`, `workspace` ...), the blocker, every rejecting review round with each finding, its evidence and required repair verbatim and the reviewer's summary, the failing checks' and generators' output tails, the last red GitHub run, and the builder's own report. Credentials are redacted (`_redact_log`). Each is kept at `<runtime>/stops/<objective>.json` (0600, in a 0700 folder), rebuilt only when the stop changes. It is served only over the tailnet (Remote Engineering Control, "The private channel") and printed by `engineering_dispatcher.py stops` and `remote_engineering.py stops` on the host.
2. **Findings fed back.** A repair revision's prompt already carried each material finding verbatim (`_repair_brief`: `- [F-01] <finding>`, `evidence:`, `required repair:`); a test now pins it. New: a build filed again under the owner's convention (`<id>-2`, `-3` ...) starts with the stop report of the try before it (`earlier_try`, `_earlier_try_brief`), framed as records to read, not instructions.
3. **More repair rounds.** A request may name `max_repair_rounds` (0 to 5, the objective's bound), and keeps it. A request that names none gets the build server's default, `--default-repair-rounds` on `remote_engineering.py poll` and `run` (2 unless the owner raises it). An admitted objective keeps its number when the default changes later. CLIVE's filer no longer pins 2: it leaves the number to the server unless asked for one.
4. **Skills for builders** (`app/orchestrator/workers/skills.py`, `config/builder_skills.json`, a protected path). The owner's curated list is his approval (OWNER_DECISIONS_2026-09-30). The list names four skills: the design skills vendored in `.claude/skills/` (design-taste-frontend, high-end-visual-design, image-to-code, web-design-guidelines). Each is pinned by the sha256 of every file. Per attempt, CLIVE builds a plugin folder called `clive-skills` in the attempt's HOME, outside the workspace and read-only, holding exactly the listed files that verify against their hashes at the task's base. A skill that differs, has an extra file, a hooks key, a `` !`command` `` line or a non-text file is withheld, and the launch notes say why. The launch passes `--plugin-dir` with that folder, switches the CLI's own bundled skills off (`--settings` `disableBundledSkills` and `skillOverrides`, `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1`), and adds the `Skill` tool, allowed only as `Skill(clive-skills:<name>)`. The launch check then requires the skills to be exactly `clive-skills:<name>` for the skills in the folder, the plugin to be exactly that folder, and no command from a plugin or the workspace. With no skill verified, or `--no-builder-skills`, the launch is exactly as before (`--disable-slash-commands`, no skills). A launch with skills keeps the CLI's command machinery (the Skill tool needs it), so its commands are held by name instead (review of the loop branch, N2): `BUILTIN_SLASH_COMMANDS` in `workers/claude.py` pins, per CLI version, the commands the CLI carries itself, as 2.1.285 and 2.1.293 listed them when probed on 8 Oct 2026 (the same 33). The launch check refuses any command that is neither one of the owner's skills nor pinned for the version the init event names. On a CLI version with no pinned list, a builder with skills is never launched: `claude --version` is asked first (once per binary) and the task blocks with "worker launch refused: Claude Code <version> has no pinned list of its own commands ... run the loop with --no-builder-skills"; a CLI changed under a running loop is refused the same way at its init event. `probe-launch` prints every command by name, so a new version's list can be pinned by a reviewed change.
5. **A browser for builders' checks.** With `--sandbox-browsers <Playwright browsers folder>` and `--sandbox-node-path <node_modules holding playwright-core>`, both bound read-only, the check sandbox gives a check `PLAYWRIGHT_BROWSERS_PATH`, `NODE_PATH` and `CROOKS_CHROMIUM`, a private size-bounded `/dev/shm` and the host's font configuration. Its memory is bounded by `RLIMIT_DATA` instead of `RLIMIT_AS`, because Chromium reserves terabytes of address space it never touches. The namespaces, the absence of network, uid 65534 and the dropped capabilities are unchanged. The builder's own `run_checks` gets the same settings.
6. **The CLI's own plugins.** `ALLOWED_PLUGINS` is an exact list of the plugins each pinned CLI was seen to carry: `telemetry@builtin` (2.1.280), `cc-plugin-agents-md@builtin` (2.1.285, PRs #63 and #85), and `cc-plugin-sec-default`, `cc-plugin-telemetry` and `cc-plugin-plugin-authoring` (2.1.293). Each must be reported with path `builtin`. Any other plugin is refused. A deliberate CLI update that brings a new one is refused until a reviewed change names it; `engineering_dispatcher.py probe-launch` launches a builder exactly as an attempt would, stops it at its init event, and prints the verdict, so the operator sees this before a re-pin.
7. **Two root-run tests and the `_supervise` race.** `_supervise` now asks whether the worker lives before it reads the log (PR #63's note), so a builder that reports and exits between the two is ingested, not cancelled. `test_checks_run_in_the_sandbox_on_a_copy_and_cannot_touch_the_candidate_tree` now says outright that there is one attempt. The sandbox tests no longer assume the tree and interpreter are outside `/root` and `/opt`: a sandbox whose tree lies under one of them holds only the way down to it, and the test checks exactly that. The canary follows `/usr/bin/python3` to the interpreter itself (a Debian-style alternatives link points into the host's `/etc`).

## Builder driver: Claude Code CLI (verified 2026-09-23, CLI 2.1.280)

Launch is `claude -p <prompt> --output-format stream-json --verbose --session-id <uuid> --restricted --tools Read,Edit,Write,Glob,Grep --allowedTools Read Edit Write Glob Grep --permission-mode dontAsk --strict-mcp-config --mcp-config '{"mcpServers":{}}' --setting-sources "" --disable-slash-commands --no-session-persistence --max-turns N --json-schema <report schema> [--model M]`. It runs detached (`start_new_session`) with cwd set to the workspace.

When the objective declares checks, the launch differs in exactly two places: `--mcp-config` names one server, CLIVE's own `clive_checks` (`app/orchestrator/workers/check_server.py`, started as `<dispatcher python> -I check_server.py <config>`), and `--allowedTools` adds its one tool, `mcp__clive_checks__run_checks`. The config is written by the dispatcher outside the workspace and lists the objective's declared checks; the builder can name one of them, never an argv. Each run is on a fresh copy of the workspace in the same `NamespaceSandbox` as the dispatcher's own checks (own PID and mount namespaces with a private `/proc`, no network, PATH-only environment, same limits and timeout); the server re-executes itself with a PATH-only environment before reading anything, so the worker's OAuth token is not in its memory or `/proc/<pid>/environ`. Output comes back bounded and redacted. The runs are advisory: the dispatcher still runs every check itself after the builder reports, and only that run is evidence. The launch check accepts that server and tool only when the launch asked for them, and, when it did, requires both (the 2026-09-30 re-pin review, second run, F-01): the init roster must list `mcp__clive_checks__run_checks` and the server `clive_checks` with status `connected`. Claude Code 2.1.285 reported exactly that for this launch on 2026-09-30 (`{"name": "clive_checks", "status": "connected", "source": "dynamic"}`). A builder whose prompt says it has `run_checks` and whose launch lacks either is refused, stopped and blocked like any other launch surface; CLIVE's own sandboxed run of the checks at ingestion is still the run that counts.

The environment is built, not inherited. It contains `PATH` (the CLI's directory plus system bins), `HOME` (a fresh directory per attempt, outside the workspace), `LANG`, `TMPDIR` and `CLIVE_ATTEMPT_ID` (the marker `<attempt>/<session uuid>` by which a restarted dispatcher finds the process; the session UUID, chosen by CLIVE and recorded in the kernel, keeps two dispatchers or stores on one host from confusing or killing each other's workers). Nothing else passes through: no GitHub, Shopify, Gmail, cloud or proxy variables. `--worker-token-file` adds `CLAUDE_CODE_OAUTH_TOKEN` from a host-side file. That is the same variable `app/providers/max_agent_sdk.py` already uses for the owner's subscription, and it is the only credential the driver will pass.

Observed on this container with that launch:

| Property | Observed |
| --- | --- |
| Authentication | `apiKeySource: "none"`. The host provider authenticated the process. The rate-limit event reported subscription windows (`five_hour`) with `overageStatus: rejected`, so no pay-as-you-go. |
| Tools | `Edit, Glob, Grep, Read, StructuredOutput, Write` |
| MCP servers | none |
| Plugins | `telemetry@builtin` only |
| Skills, slash commands | 0 and 0 |
| Permission mode | `dontAsk`. A probe with `Bash(git status)` and `Bash(git diff)` allowed saw `git commit` and `curl` denied, and both appeared in `permission_denials`. |
| Session | Exactly the `--session-id` CLIVE chose, recorded in the kernel at assignment |

The launch check (`verify_started`) fails closed if any of these hold:

- a tool beyond the requested set plus `StructuredOutput`;
- any MCP server, or any plugin other than `telemetry@builtin`;
- any skill or slash command;
- another cwd, another session, or another permission mode;
- when the objective declares checks: no `mcp__clive_checks__run_checks` in the tools, or no `clive_checks` server with status `connected` (absent, `failed`, `pending` or no status at all).

The earlier ECC audit found that headless sessions on the owner's host inherit the claude.ai connector roster. This check is the mechanism that catches that, whatever the prompt says.

Bash is off by default. A prefix allowlist is not a sandbox: `git diff --no-index` reads any host file, and `git log --output` writes one. `--restricted` confines only the file tools. CLIVE runs the objective's checks itself, so a builder does not need a shell. `--worker-bash-prefix` exists for objectives that genuinely need one, and using it is an explicit widening.

This runs on the owner's existing subscription through the CLI that the application's Agent SDK provider already drives. It adds no credential in this environment. On a host where the CLI's login lives in the owner's `~/.claude`, the fresh HOME will not find it, and the launch fails deterministically as an authentication blocker. The owner then decides whether to provision a worker token file (`claude setup-token`). This code never copies credentials.

## Reviewers

A reviewer is a driver (`availability`, `start`, `poll`). The dispatcher admits exactly one output, `clive.review_result.v1`, a strict pydantic record:

- task, revision, attempt and candidate SHA;
- `verdict`: `READY` or `CHANGES_REQUIRED`;
- findings, each with `finding_id`, `material`, `finding`, `evidence_ref` and `required_repair`;
- `reviewer` facts: principal, session, workspace, read-only, clean, and head at the candidate.

`READY` with a material finding, or `CHANGES_REQUIRED` without one, is invalid. Prose goes in `summary` and decides nothing. There is no verdict parser. The kernel re-runs the eligibility rule on the reviewer facts at the exact SHA. As the kernel documents, those facts are declared by whoever relays them.

State of the reviewer side, as found:

- **GPT, programmatic: does not exist.** This environment has no OpenAI credential and no verified supported programmatic ChatGPT review mechanism. The OpenAI API would be a new secret and new pay-as-you-go spend, both owner decisions. `GptUnavailable` reports exactly this. With the default `--reviewer gpt`, a finished candidate is BLOCKED with the gap. Nothing is dispatched to nobody.
- **Claude as reviewer: ineligible by contract.** `config/review_principals.json` registers `claude` with `may_review: false`, because every Claude session on the host is one principal. The dispatcher also refuses any reviewer that is the author principal. Changing that registry is an authority change, and objective scope cannot reach it.
- **Relay: exists, and is a courier.** `--reviewer relay` writes the exact-SHA packet to `<runtime>/relay/<task>/<attempt>/dispatch.N.packet.md` and waits for typed results in `dispatch.N.results/` (via `submit-review --file`). It is marked `courier: true` in the dispatch note, the status output and the runtime record. A task reviewed this way is not no-courier evidence.

## Workspaces, restart and failure classes

Each attempt gets its own workspace at `<workspace-root>/<task>/<attempt>/`. Both components are validated, and the resolved path must stay under the root. The workspace is a plain tree with no git metadata of CLIVE's inside it. The attempt's git directory is its sibling, `<workspace-root>/<task>/<attempt>.git/`:

- a bare `git clone --local` of the dispatcher's repository, used with an explicit `--work-tree`;
- the tree checked out at the base, on branch `clive/attempt/<attempt>`;
- with its remote removed;
- with a metadata file in the git directory binding it to its task, attempt and base. A directory without matching metadata is refused, never reused.

Why the git directory is outside the tree: the worker's file tools are confined to its cwd (`--restricted`), so the metadata CLIVE later trusts is out of its reach. Whatever the worker does write in its tree is inert. That covers a `.git` directory or gitlink file, a config naming an fsmonitor command, hooks, or a `.gitattributes` naming a filter driver. Every CLIVE git command on an attempt names `--git-dir` and `--work-tree`, ignores system and global config, and forces `core.hooksPath=/dev/null` and `core.fsmonitor=false`. Git never adds a path named `.git`. `tests/test_engineering_dispatcher.py::test_nothing_the_worker_writes_in_its_tree_can_steer_clives_git` plants all of these (hooks armed executable) and shows none runs. The same test fails against r2's layout, where the git directory lived inside the tree.

## Check sandbox

An objective's checks run worker-authored code, so they run only through a `CheckRunner` (`app/orchestrator/checks.py`). The one that exists, `NamespaceSandbox`, uses util-linux `unshare` with private mount, network, PID, IPC and UTS namespaces, then `chroot` and `setpriv`:

- **Filesystem.** The root is a tmpfs holding only `/usr`, `/bin`, `/sbin` and `/lib*` (bound read-only), a curated `/etc` (passwd, group, hosts, nsswitch.conf, ld.so.cache, localtime), a private `/proc` and four `/dev` nodes. It also holds any read-only directories the operator names with `--check-ro-path`, such as the interpreter's virtualenv. The only writable places are the check's own export of the candidate and a 512 MB private `/tmp`. `/root`, `/home`, `/opt`, the runtime, the store, the repository and the live workspace do not exist inside.
- **Network.** None: an empty network namespace, so neither the internet nor services on the host's loopback are reachable.
- **Identity.** When the dispatcher runs as root, the check runs as uid/gid 65534. Otherwise it runs in a user namespace over the dispatcher's own unprivileged uid. Either way it has no capabilities and `no_new_privs`.
- **Resources.** A wall-clock timeout, on which the check's PID-namespace init is SIGKILLed, taking every process in the namespace with it. Also CPU, address-space, file-size and open-file limits, and a process-count limit when the check has its own uid. `unshare --kill-child` alone is not enough, because the kernel clears the parent-death signal when `setpriv` changes the uid. The first version of the adversarial test caught background loops surviving the timeout that way.
- **Fail closed.** Before the first check, a canary runs inside. It must fail to read a world-readable host sentinel, fail to leave a file at a host path, fail to reach a listener on the host loopback, and run as the expected uid with no effective capabilities. The host side is what is checked, not the canary's own report. If any property fails, or `unshare` is missing, the runner is unavailable and the task blocks with the exact reason. There is no unsandboxed fallback.

`tests/test_check_sandbox.py` runs hostile candidate test code through the real `pytest` inside the sandbox. From the host's side, it shows the code:

- cannot read a sentinel, `/etc/shadow` or `/root`;
- cannot write outside its tree and private `/tmp`;
- cannot connect to a host-loopback listener or an external address;
- runs as 65534 with no capabilities;
- is killed, together with a `setsid`-escaped background loop, on timeout.

Both root and non-root modes were exercised on this host. On a host where neither the dispatcher is root nor unprivileged user namespaces are allowed (Ubuntu's AppArmor `kernel.apparmor_restrict_unprivileged_userns=1`, for example), the canary fails, and objectives with checks block with that reason until the owner decides how the dispatcher should run.

Where the tests run matters. CI acceptance run `35874441460` at `dcd7d745` was red: 3 failed and 4 errors. The CI runner (`ubuntu-latest`, the non-root `runner` user) cannot establish the sandbox, and the dispatcher correctly failed closed there. But the escape tests demanded a working sandbox on every host. The runner's exact canary reason is not visible in CI output. Its most likely cause is Ubuntu's restriction on unprivileged user namespaces. A faithful local simulation (`unshare` present, the kernel refusing the uid map) reproduced exactly those 3 failures and 4 errors.

The tests now require the sandbox only where it can be established:

- **Escape tests:** on a host that cannot establish it, they skip, naming the canary's reason. With `CLIVE_REQUIRE_CHECK_SANDBOX=1`, which the dispatcher's host should set, a skip is a failure.
- **Fail-closed behaviour:** proven on every host, including "unshare refused by the kernel".
- **Dispatcher logic tests** (evidence, refusal, retry) use an explicit runner double.

So green CI proves fail-closed behaviour and the dispatcher logic. It does not prove escape resistance. That is proven on a host that can establish the sandbox (this one, as root and as non-root), and it must be proven on the dispatcher's own host before objectives with checks run there.

A repair attempt fast-forwards its fresh workspace to the rejected candidate after assignment, so the kernel's "workspace at the base" fact stays true at assign time.

Restart works like this:

- Every stage comes from the records.
- The runtime notes (`<runtime>/attempts/<attempt>.json`: pid, launch time, mapped-event count, observed roster) are execution facts only.
- Live workers are found through `/proc/*/environ` by their attempt marker. A second launch is refused while one lives, both in the dispatcher and in the driver.
- A worker that finished while the dispatcher was down is ingested from its log and workspace.
- A lease that expired while nobody observed cancels the attempt (transient) rather than failing late.
- The long-running `remote_engineering.py run` is tested restarted, in process, with the host's flags (`--publish-remote origin`, `--product-memory-ref origin/clive/trunk`, a journalled store, the default adapter root under the host's exclude rule) against a store its first life left: v1 claims and receipts (one a refusal), objectives, tasks, an attempt with a live builder and its runtime notes. Replay keeps every record (write-once records byte for byte, event logs only appended to, the runtime notes unchanged), admits and launches nothing twice, and stops and blocks, with its reason, an objective whose scope became protected in between (the 2026-09-30 re-pin review, F-02).

Stopping a worker (the 2026-09-30 re-pin review, F-01). Every place the dispatcher stops one goes through `_stop`: a stall, no init in time, a refused launch surface, an expired lease, a protected scope, the attempt time limit, a result (before its tree is committed) and every cancel. The driver's `kill`:

1. sends SIGTERM to the worker's process group (and to any marked process outside it);
2. waits up to `kill_grace_s` (5 s by default, a `ClaudeCodeWorker` setting), polling for processes carrying the attempt marker;
3. sends SIGKILL to whatever remains;
4. waits up to `kill_confirm_s` (5 s) again;
5. returns the pids still alive.

A worker that exits on SIGTERM costs no wait. The cancel, block or candidate that follows is recorded only on an empty answer, so it is recorded only once no process of the attempt is alive. If any is still alive, nothing is recorded as a stop: the task is blocked (deterministic) with the reason "the worker of `<attempt>` could not be stopped: pid(s) … still alive after SIGTERM, SIGKILL and a bounded wait …", followed by why it was being stopped. The owner stops it on the host before resuming. It is never a normal cancel, so it is never retried while the old worker may still write.

Failure classes:

- **Transient** (a provider error, a process that died, a stall, no init): the attempt is cancelled with a `transient:` reason. The next attempt waits `backoff_base_s · 2^(n-1)`. After `max_transient_retries`, the task blocks.
- **Deterministic** (a refused launch surface, authentication, a worker's own `blocked`, the turn budget, a publish refusal, no reviewer, a worker that could not be stopped): the task blocks once, with the reason.

## Observability

`status` prints, per objective:

- task, revision, kind and attempt;
- stage and reason, from the projection;
- the dispatch identity;
- whether the process is actually alive (by marker) and the last observed stream event;
- the last kernel heartbeat and last progress (nothing is derived from the launch time);
- the lease, candidate, review mechanism and courier flag, acceptance and integration;
- the blocker and the next lifecycle action;
- since part 3: the attempts and what became of each, the repair rounds used by cause, the files the loop regenerated, and where the landing stands (see "Status contract").

`--json` gives the same data as JSON. Agent Environment can read the same records and is not required.

## Operating it

- The store is a dedicated checkout of `clive/engineering-state`, whose journal is pushed fast-forward. That is the existing operating rule: one writer clone.
- `--repo` is a dedicated dispatcher clone. The dispatcher refuses to move a target branch that the clone has checked out. It is never the production checkout and never the canonical Builder checkout.
- `--workspace-root` defaults to `/opt/crooks-workers`.
- Use `--publish-remote origin` when the reviewer must fetch the candidate from GitHub. From the loop update on, it is also how a candidate reaches GitHub at all, so `engineering_dispatcher.py tick` and `run` and `remote_engineering.py run` refuse to start without it (the 2026-09-26 re-pin review, F-02): a candidate that is never pushed would never get an acceptance run, wait `missing` and block.
- A failed push's error text reaches the blocker reason (which the store keeps and the status publishes) only through `safe_git_error`: one line, credentials in URLs and token shapes redacted before it is cut (the 2026-09-26 re-pin review, F-03).
- `run` ticks until every objective is COMPLETE, BLOCKED or at OWNER_GATE, and none is still waiting to land or being refreshed. `tick --no-land` and `run --no-land` never land.

## Declared, not verified

- Owner provenance of an objective (see Intake).
- A reviewer's session and workspace facts (the kernel's existing limit).
- Worker identity is the session CLIVE chose and observed in the init event. It is not bound cryptographically (ENGINEERING_CONTROL_PLANE_VNEXT §6).
- The worker process itself reaches the model provider over the network. What it cannot use are Bash, web tools, MCP and connectors, because those are cut and checked at launch. That is a surface reduction, not a network sandbox.
- The check sandbox shares the host kernel: it is namespace isolation, not a virtual machine. A kernel vulnerability reachable from an unprivileged process is outside what it defends against.
- Process discovery reads Linux `/proc`: single host, single dispatcher.
- The worker's confinement to its cwd, which keeps it away from the attempt's git directory, is Claude Code's `--restricted` file-tool boundary. The real-worker smoke asks a worker to write into the sibling git directory and to an absolute host path, and records the result.

## Before the no-courier dogfood

This is an owner decision. Provide a genuinely independent reviewer that the dispatcher can reach without a person carrying messages, then give CLIVE one real, bounded product objective with an external oracle through `objective`. The options are:

- a programmatic GPT reviewer (a credential and spend decision), plus its driver behind `ReviewerDriver`;
- another principal registered `may_review` with a real transport.

Until then, the honest outcomes are:

- BLOCKED at review with the gap (default);
- REVIEWING through the relay, which is a courier.
