# Objective Intake + Engineering Dispatcher V1

Status (2026-09-25): ACTIVE. The dispatcher is the engine inside the remote engineering loop ([REMOTE_ENGINEERING_CONTROL_V1.md](./REMOTE_ENGINEERING_CONTROL_V1.md)), activated by the owner (DEC-059). The loop runs on three machines, and all builders run `claude-opus-5-5`:
- the production host, with two builders;
- `clive-worker-01`, an HPE server with eight builders;
- the owner's Mac, which is being set up.

Every candidate gets an exact-SHA independent review by GPT (see "Reviewers") and bounded repair. Dispatcher COMPLETE is not "finished": under the owner's one-trunk rule (DEC-058), work is finished only when it is in `clive/trunk` and the trunk passes full repository acceptance. The dispatcher is repository-only. It authorises no deployment, no runtime, service, watcher or systemd change, no secret, no permission or connector change, no business write and no spend.

*History (2026-09-23): this document was written as "repository-only implementation, awaiting independent exact-SHA review". It stated then that the dispatcher did not by itself prove the no-courier milestone, which is met only when a separate, real, bounded product objective enters through this intake and reaches independently reviewed COMPLETE, BLOCKED or OWNER_GATE without anyone relaying messages between workers. The sections below describe the design as built; where a passage records the 2026-09-23 state, it is marked as history.*

Code: `app/orchestrator/objectives.py` (intake), `app/orchestrator/dispatcher.py` (controller), `app/orchestrator/workspaces.py`, `app/orchestrator/checks.py` (the check sandbox), `app/orchestrator/workers/` (builder drivers), `app/orchestrator/reviewers/` (typed review result and reviewer drivers), `scripts/engineering_dispatcher.py` (the CLI). The kernel is used, unchanged, at `18c3153a2eec10c6343153b550776afed3bec2ba`: `Kernel`, `LifecycleStore`, `PrincipalRegistry`, `GitFacts`, `lifecycle_view`, `journal_preconditions`, `git_journal`.

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
- allowed paths: required and non-empty. They may never cover the frozen kernel, the dispatcher itself, the principal registry, the roster, launchd/secrets scripts, `.github` or the `engineering/` store;
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
| READY | Check the retry budget and backoff (from the kernel's cancellation records) and the concurrency limit. Create a fresh workspace at the base, assign with a CLIVE-chosen session id, launch. | `assign` |
| ASSIGNED | Wait for the worker's own `system/init` event and check it against the launch policy. A pass is the acknowledgement. A widened surface kills the worker and blocks. No init within `init_timeout_s` cancels (transient). | `ack` / `block` / `cancel` |
| RUNNING | Stream events renew the lease. A successful Edit/Write is progress, and edits seen before a result are flushed as progress before the candidate. No event for `stall_s`: kill, cancel (transient). Process gone with no result: diagnose; authentication is deterministic, anything else transient. On a result, see below. | `heartbeat`, `heartbeat --progress`, `evidence`, `candidate`, `cancel`, `block` |
| EVIDENCE_READY | Choose the first configured reviewer that is registered `may_review`, is not the author principal, and whose driver says it can actually be reached. If none: block with every gap named, and dispatch nothing. | `dispatch` / `block` |
| REVIEWING | Read the typed result. A result naming another task, revision or attempt is refused at the door. Everything else goes to the kernel, which admits, rejects or refuses it. | `verdict` |
| REJECTED | Route a repair revision (`kind: repair`, same base, scope and evidence) that names the admitted verdict record. After `max_repair_rounds`, block and leave the next move to the owner. | `task` r+1 / `block` |
| ACCEPTED | Verify the target ref resolves to the accepted SHA (the remote's with `--publish-remote`). If it has moved, block. | `integrate` (fast-forward) / `block` |
| DONE | Nothing. The projection says COMPLETE only when acceptance and integration agree. | — |
| BLOCKED, OWNER_GATE | Nothing. The dispatcher never lifts either. | — |

When a worker result arrives (`completed`), these steps run in order, and nothing earlier in the list is skipped:

1. CLIVE commits whatever the worker left in the tree (the worker has no git and cannot commit).
2. The candidate is `git rev-parse HEAD`. If the tree is unchanged, the result is refused.
3. The candidate is fetched into the dispatcher's repository as `refs/clive/candidates/<attempt>` and verified to be exactly that SHA.
4. The changed paths are read from `git diff --no-renames` and must fall inside scope.
5. Each check runs in the check sandbox (see "Check sandbox") on a fresh export of exactly the committed candidate, never on the live workspace, and its output is evidence. If the sandbox cannot be established, the task blocks and no check runs.
6. The transcript and report are recorded as evidence.
7. The target branch moves fast-forward only (and is pushed, with `--publish-remote`).
8. `candidate` records the exact SHA with every required evidence name.

An out-of-scope tree, a failed check or an empty tree cancels the attempt (`result_refused:`) and never becomes a candidate. The next attempt's prompt says why. After `max_result_refusals` the task blocks.

Worker outcomes map to lifecycle outcomes like this:

- `blocked` → BLOCKED (deterministic);
- `owner_decision_required` → OWNER_GATE (OWNER_ONLY). This is the safe direction: the worker can stop work, never start it;
- a structured error → transient or deterministic, by its API status and subtype, never by prose.

## Builder driver: Claude Code CLI (verified 2026-09-23, CLI 2.1.280)

Launch is `claude -p <prompt> --output-format stream-json --verbose --session-id <uuid> --restricted --tools Read,Edit,Write,Glob,Grep --allowedTools Read Edit Write Glob Grep --permission-mode dontAsk --strict-mcp-config --mcp-config '{"mcpServers":{}}' --setting-sources "" --disable-slash-commands --no-session-persistence --max-turns N --json-schema <report schema> [--model M]`. It runs detached (`start_new_session`) with cwd set to the workspace.

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
- another cwd, another session, or another permission mode.

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

State of the reviewer side as of 2026-09-25:

- **GPT, programmatic: the reviewer the remote loop uses.** The dispatcher line carries an exact-SHA GPT reviewer driver that calls the OpenAI Responses API (`gpt-5.6-sol`, high effort, `store:false`), reading its key from a host-side credential file ([OPUS_5_5_HANDOFF_2026-09-24.md](./OPUS_5_5_HANDOFF_2026-09-24.md) §4–§5). It reaches the reviewer without a person carrying messages. GPT here is the independent reviewer only: the runtime GPT Director is still not implemented (§13 of that handoff; FEAT-043).
- **Claude as reviewer: ineligible by contract.** Unchanged, as below.
- **Relay: still exists, and is still a courier.** Unchanged, as below. The remote loop's review is the GPT reviewer above, not the relay.

*History (2026-09-23): the reviewer side as found when this document was written. The "GPT unavailable" path below described the environment at that time, not the reviewer the loop now uses.*

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

Failure classes:

- **Transient** (a provider error, a process that died, a stall, no init): the attempt is cancelled with a `transient:` reason. The next attempt waits `backoff_base_s · 2^(n-1)`. After `max_transient_retries`, the task blocks.
- **Deterministic** (a refused launch surface, authentication, a worker's own `blocked`, the turn budget, a publish refusal, no reviewer): the task blocks once, with the reason.

## Observability

`status` prints, per objective:

- task, revision, kind and attempt;
- stage and reason, from the projection;
- the dispatch identity;
- whether the process is actually alive (by marker) and the last observed stream event;
- the last kernel heartbeat and last progress (nothing is derived from the launch time);
- the lease, candidate, review mechanism and courier flag, acceptance and integration;
- the blocker and the next lifecycle action.

`--json` gives the same data as JSON. Agent Environment can read the same records and is not required.

## Operating it

- The store is a dedicated checkout of `clive/engineering-state`, whose journal is pushed fast-forward. That is the existing operating rule: one writer clone.
- `--repo` is a dedicated dispatcher clone. The dispatcher refuses to move a target branch that the clone has checked out. It is never the production checkout and never the canonical Builder checkout.
- `--workspace-root` defaults to `/opt/crooks-workers`.
- Use `--publish-remote origin` when the reviewer must fetch the candidate from GitHub.
- `run` ticks until every objective is COMPLETE, BLOCKED or at OWNER_GATE.

## Declared, not verified

- Owner provenance of an objective (see Intake).
- A reviewer's session and workspace facts (the kernel's existing limit).
- Worker identity is the session CLIVE chose and observed in the init event. It is not bound cryptographically (ENGINEERING_CONTROL_PLANE_VNEXT §6).
- The worker process itself reaches the model provider over the network. What it cannot use are Bash, web tools, MCP and connectors, because those are cut and checked at launch. That is a surface reduction, not a network sandbox.
- The check sandbox shares the host kernel: it is namespace isolation, not a virtual machine. A kernel vulnerability reachable from an unprivileged process is outside what it defends against.
- Process discovery reads Linux `/proc`: single host, single dispatcher.
- The worker's confinement to its cwd, which keeps it away from the attempt's git directory, is Claude Code's `--restricted` file-tool boundary. The real-worker smoke asks a worker to write into the sibling git directory and to an absolute host path, and records the result.

## Before the no-courier dogfood

**As of 2026-09-25:** this precondition is met. A genuinely independent reviewer that the dispatcher reaches with no courier now exists: the programmatic GPT reviewer described under "Reviewers". The owner authorised activation (DEC-059), and objectives now enter through the remote loop's bounded inbox with no one relaying messages between workers. Nothing below is an open instruction.

*History (2026-09-23): the text below is the instruction as written before the reviewer existed.*

This is an owner decision. Provide a genuinely independent reviewer that the dispatcher can reach without a person carrying messages, then give CLIVE one real, bounded product objective with an external oracle through `objective`. The options are:

- a programmatic GPT reviewer (a credential and spend decision), plus its driver behind `ReviewerDriver`;
- another principal registered `may_review` with a real transport.

Until then, the honest outcomes are:

- BLOCKED at review with the gap (default);
- REVIEWING through the relay, which is a courier.
