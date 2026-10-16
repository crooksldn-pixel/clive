# Exact-SHA review: re-pinning the engineering loop on clive-worker-01

## What you are asked to decide

**The question.** Is the candidate `ef204bc29d7e6c6d8e518f62f01c9574a160e23b` safe to become the
pinned code of the engineering loop (`clive-remote-engineering.service` on clive-worker-01)?

- It replaces the base `718fbc41652a47e6538b8e61b3de1a8a290c5b7e`, which the host runs now.
- The host's configuration stays exactly as it is today (below).

**Your answer.**
- **READY** only if it is safe.
- Otherwise **CHANGES_REQUIRED**, with each material finding.

**No waiver applies to this candidate.**

## The two commits

| | Commit | Detail |
|---|---|---|
| **Base** (what runs now) | `718fbc41652a47e6538b8e61b3de1a8a290c5b7e`, on `clive/trunk` since 2026-10-01 | The loop process runs this code. Its unit file names this pinned tree, and the process has run it since 2026-10-01 22:04 UTC (one restart on the same code on 2026-10-15 16:51 UTC) |
| **Candidate** | `ef204bc29d7e6c6d8e518f62f01c9574a160e23b`, the current `clive/trunk` head (2026-10-14) | GitHub acceptance (`acceptance.yml`) on this exact SHA: run `38638076616`, completed, **success**. The gate record that follows this head was asked just now by the candidate's own gate code |

The script-generated loop-code diff below runs from the base to the candidate (`718fbc41..ef204bc2`).
Additional candidate files read or imported by the loop, but outside that generated diff, are
reproduced and reviewed separately below.

## What the re-pin does, and what it does not

After your READY, the re-pin script:

1. builds the candidate's tree;
2. rewrites **only** the pinned path in the unit file (the product-memory ref is rewritten to the same
   value);
3. reloads systemd;
4. waits until no builder or review process is running;
5. restarts the loop;
6. waits one tick.

**It changes no other flag.** A separate configuration step may follow later, but only after the
re-pin has succeeded. **It is not part of this review, and nothing below assumes it.** Judge the
candidate under the configuration the host has today.

## The host configuration the candidate must be safe with (audited 2026-10-15)

`ExecStart` (credential file paths omitted):

```
remote_engineering.py --store /srv/clive-engineering/state/engineering --repo /srv/clive-engineering/repo
  --runtime-root /srv/clive-engineering/runtime --workspace-root /srv/clive-engineering/workers
  --publish-remote origin --gpt-api-key-file <file> --worker-cli /srv/clive-engineering/bin/claude
  --worker-token-file <file> --worker-model claude-opus-5-5 --worker-effort high
  --check-ro-path /home/user/clive/crooks-assistant/.venv --check-ro-path /opt/node22
  --max-concurrent 8
  run --repository crooksldn-pixel/clive --product-memory-ref origin/clive/trunk --remote origin
  --branch clive/control/worker-01-inbox --interval 15 --status-branch clive/control/worker-01-status
```

**Flags:**
- `--max-concurrent 8`.
- **Absent:**
  - `--reviewer`;
  - `--no-builder-skills`;
  - `--default-repair-rounds`;
  - `--private-listen` and `--private-allow-node`;
  - `--sandbox-browsers` and `--sandbox-node-path`;
  - `--worker-bash-prefix`.

**Host:**
- The builder and reviewer CLI is **Claude Code 2.1.280**.
- There is no Chromium or Playwright on the host.
- The unit runs as root, with `ReadOnlyPaths=/srv/clive-engineering/remote-control`.
- The repository clone and builder workspaces share one tmpfs. The store and runtime are on disk.

**The loop is idle.**
- 74 requests are recorded, every one terminal: 26 COMPLETE, 44 BLOCKED, 2 OWNER_GATE, and 2 refused
  at intake.
- None is waiting.
- No builder or review is running.

### What that configuration means under the candidate (each from the candidate's source: check it)

1. **Reviewer.**
   - With no `--reviewer`, the default is `claude` (`app/orchestrator/reviewers/choice.py`,
     `DEFAULT_REVIEWER = "claude"`).
   - Because `--gpt-api-key-file` is still given, the GPT reviewer is kept as `CollectOnly`
     (`reviewers_for`). It can finish only a review dispatched to it before the switch, and takes no
     new one. None is in flight.
   - New reviews go to `ClaudeCodeReviewer`, under the principal `claude-reviewer`, on the worker's
     CLI and token file by default.
2. **Builder skills.**
   - With no `--no-builder-skills`, skills are on (`DispatcherConfig.builder_skills = True`).
   - `BUILTIN_SLASH_COMMANDS` (`app/orchestrator/workers/claude.py`) holds only 2.1.285 and 2.1.293.
   - So on CLI 2.1.280, a builder launch with skills raises a non-transient `WorkerLaunchError` in
     `ClaudeCodeWorker.launch` **before any process starts**.
   - A build filed in this configuration therefore blocks with "no pinned list of its own commands"
     instead of running. Judge whether that is fail-closed and safe.
3. **Repair rounds.**
   - A request that names none gets 2 (`DEFAULT_REPAIR_ROUNDS = 2`,
     `app/remote_engineering/controller.py`).
   - At the base, the request schema's own default was also 2 (`requests.py`).
   - A request that names its own limit (0–5) keeps it.
4. **Private channel.**
   - Off: no listener is opened.
   - Stop reports are still written on demand, to `<runtime>/stops/<objective>.json` (directory 0700,
     files 0600, `_private_write`): when the operator's `stops` verb runs, or when a re-filed build's
     `earlier_try` is computed.
5. **Check sandbox.** With no browser flags, checks run as at the base: `RLIMIT_AS` and no browser
   binds (`app/orchestrator/checks.py`).

## What changed in the range, and where to check it

Of the 58 commits in `718fbc41..ef204bc2`, **two change the loop's code**:

- `db61f8a1` (PR #102, DEC-068);
- `d0f03d77` (PR #114, DEC-076).

The rest change CLIVE's production app, documents and tests. The loop imports none of that code except
`app/logging/turnlog.py` (below).

### DEC-068 (PR #102): the loop upgrade of 7 October

- **Why a build stopped is kept on the loop host only.**
  - **Code:** `Dispatcher.stop_reports`, `_stop_of`, `_stop_report`, `_review_rounds`,
    `_failed_checks`, `_last_red`, `_builder_report`, `stop_cause`, `STOP_CAUSES` and
    `_private_write` (`dispatcher.py`).
  - **The private channel,** `app/remote_engineering/private.py`:
    - it binds only a Tailscale or loopback address;
    - it puts every connection to `tailscale whois` and allows only nodes named by their full tailnet
      name or StableID;
    - it serves `GET /v1/stops` only;
    - it redacts every text field.

    `runner.py` wires it in only when configured. The status projection (`status.py`) is unchanged,
    so nothing new is published.
  - **Tests in `test_engineering_dispatcher.py`:**
    - `test_a_build_stopped_at_its_repair_limit_keeps_the_reviewers_findings_whole_on_the_host_only`
    - `test_failed_checks_keep_their_output_with_the_stop`
    - `test_the_builders_own_report_is_kept_with_the_stop`
    - `test_a_build_still_running_or_complete_has_no_stop_report`
    - `test_each_stop_is_named_by_one_fixed_word`
    - `test_a_stop_report_that_cannot_be_kept_never_stops_the_next_try_launching`
  - **Tests in `test_remote_engineering.py`:**
    - `test_the_private_document_carries_each_stop_in_full_redacted_by_its_request_id`
    - `test_the_private_channel_listens_only_on_a_tailnet_or_loopback_address`
    - `test_only_the_tailnet_machines_the_operator_named_may_read_it`
    - `test_a_node_is_named_by_its_full_tailnet_name_or_stable_id_never_its_machine_name_alone`
    - `test_the_private_channel_serves_one_read_only_document_to_a_named_node`
    - `test_a_channel_that_cannot_bind_never_stops_the_loop_and_tries_again_a_minute_later`
    - `test_the_loop_rebuilds_the_private_document_each_cycle_and_publishes_counts_only`
    - `test_run_refuses_a_private_channel_that_is_not_tailnet_only_before_anything_starts`
    - `test_the_stops_verb_prints_what_the_running_loop_recorded_redacted`
- **Findings reach whoever repairs.**
  - A repair revision gets each material finding verbatim. That behaviour is unchanged and is now
    pinned by `test_a_repair_revision_is_given_each_material_finding_verbatim`.
  - A build filed again as `<id>-N` starts with the earlier try's stop report, but only when its title
    or allowed paths match: `Dispatcher.earlier_try`, `_same_build`, and `_earlier_try_brief` into
    `worker_prompt`.
  - **Tests:**
    - `test_a_build_filed_again_is_told_why_the_try_before_it_stopped`
    - `test_a_try_is_linked_to_the_one_before_it_only_when_it_is_the_same_build`
- **Repair rounds.**
  - A request may name 0–5. One that names none gets the host's `--default-repair-rounds`, default 2
    (`RemoteControllerConfig.default_repair_rounds` and `_repair_rounds` in `controller.py`;
    `RemoteObjectiveRequest.max_repair_rounds` now defaults to `None` in `requests.py`).
  - **Tests:**
    - `test_a_request_that_names_no_repair_rounds_gets_the_hosts_default_and_one_that_does_keeps_its_own`
    - `test_the_hosts_default_is_the_convergence_doctrines_two_and_stays_within_the_objectives_bound`
- **Builder skills.**
  - **How the folder is built:** `app/orchestrator/workers/skills.py` (new) builds a per-attempt
    plugin folder in the attempt's own HOME, from `config/builder_skills.json` read from the loop's
    own pinned checkout. Each file is verified by sha256 against git objects at the task's base.
  - **What is withheld:** a skill with a mismatch, an extra file, a `hooks` key, a `` !`command` ``
    line or a non-text file.
  - **How the launch uses it:** `workers/claude.py` passes the folder only on CLI versions with a
    pinned command list. `verify_started` requires the init roster to equal the folder exactly.
  - **`ALLOWED_PLUGINS`** is the exact list of built-in plugins each CLI was seen to carry, including
    `telemetry@builtin` for 2.1.280.
  - **Tests in `test_claude_worker_adapter.py`:**
    - `test_a_skills_launch_on_a_cli_version_with_no_pinned_commands_never_starts`
    - `test_a_cli_whose_version_cannot_be_read_launches_no_builder_with_skills`
    - `test_a_launch_without_skills_still_refuses_any_skill_or_command`
    - `test_only_skills_whose_every_file_matches_its_pinned_hash_are_built_into_the_folder`
    - `test_a_skill_that_would_run_something_is_withheld_even_with_matching_hashes`
    - `test_a_skill_folder_holding_a_link_is_withheld`
    - `test_the_built_in_plugins_each_pinned_cli_reported_pass_the_launch_check`
    - `test_any_plugin_that_is_not_one_the_cli_was_seen_to_carry_is_refused`
  - **Tests in `test_engineering_dispatcher.py`:**
    - `test_a_builder_gets_exactly_the_owners_skills_each_verified_by_hash`
    - `test_on_a_cli_version_with_no_pinned_commands_a_builder_with_skills_is_never_launched`
    - `test_with_builder_skills_off_the_launch_is_exactly_the_launch_without_skills`
- **A browser for checks** (off unless `--sandbox-browsers` names a folder).
  - `checks.py` binds Playwright's browsers and node modules read-only and adds a private `/dev/shm`.
    Only when browsers are named does it bound memory by `RLIMIT_DATA` instead of `RLIMIT_AS`.
  - **Tests:**
    - `test_check_sandbox.py`: `test_browser_settings_bind_their_folders_read_only_and_name_them_in_the_checks_environment`,
      `test_a_browser_folder_that_is_not_a_plain_directory_makes_the_sandbox_unavailable`,
      `test_a_check_drives_chromium_inside_the_sandbox_and_it_stays_inside`;
    - `test_builder_check_server.py`: `test_the_builders_own_runs_get_the_same_browser_settings_as_the_dispatchers`.
- **Probes.**
  - `engineering_dispatcher.py probe-launch` (with optional `--skill-turn`) launches a builder in a
    throwaway root and stops it at its init event.
  - **Tests:**
    - `test_probe_launch_says_whether_this_cli_passes_the_launch_check_and_leaves_nothing_running`
    - `test_after_a_re_pin_probe_launch_proves_a_builder_can_load_one_of_the_owners_skills`
- **One supervision fix.**
  - `_supervise` now checks liveness before reading the stream log. A worker that writes its result
    and exits between the two looks is now ingested, not cancelled as a transient death.
  - **Test:** `test_a_worker_that_reports_and_exits_between_two_looks_is_ingested_not_cancelled`.
- **Protected paths grow** by `config/builder_skills.json` (`objectives.py`).

### DEC-076 (PR #114): the Claude reviewer

- **`app/orchestrator/reviewers/claude.py` (new): `ClaudeCodeReviewer`.**
  - **Each review gets** a fresh session: its own id, `--no-session-persistence`, and an empty HOME.
  - **The review room** is exported from the candidate's git objects at the exact SHA (links are shown
    as notes, never followed), made read-only, and compared with the commit's blobs after the review.
  - **The launch argv** (`argv_for`) is `--restricted`, `--tools Read,Glob,Grep`,
    `--permission-mode dontAsk`, `--strict-mcp-config` with no MCP servers, `--setting-sources ""`,
    `--disable-slash-commands`, and `--json-schema` of the decision.
  - **The launch is checked at the init event.** It is refused for any other tool, any MCP server, any
    plugin outside `ALLOWED_PLUGINS`, any skill or command, any permission mode but `dontAsk`, or any
    API-key source.
  - **A changed room or a non-read-only tool call voids the review.** That is an error, never a
    verdict.
  - **Runs:** at most 3 (`MAX_RUNS = 3`); after that, the task blocks with the reason.
  - **The verdict** is the same `clive.review_result.v1`. The driver binds it to the exact SHA, never
    the model.
- **`reviewers/choice.py` (new): `reviewers_for`.**
  - The chosen reviewer comes first, and the one not chosen is `CollectOnly`.
  - GPT is kept only while its key file is given.
  - Both loop scripts build their reviewers here: `--reviewer claude|gpt` (default `claude`), plus
    `--reviewer-cli` and `--reviewer-token-file`, which default to the worker's.
- **`reviewers/base.py`, `gpt.py` and `relay.py`:** shared code moved into `base.py`. **Check that
  the GPT reviewer's behaviour is unchanged.**
- **`config/review_principals.json`** adds the principal `claude-reviewer`: reviewer role only,
  `may_review: true`. The builder principal `claude` still may not review. The entry is in full below.
- **`scripts/github_app_token.py` (new; DEC-076's GitHub Apps)** mints installation tokens. The loop
  uses it only when git's credential helper is configured to, and it is not configured on this host.
  It is now a protected path.
- **Tests in `test_claude_reviewer.py`:**
  - `test_claude_is_the_default_and_gpt_is_selectable_so_a_repin_can_fall_back`
  - `test_a_review_given_to_gpt_before_the_repin_to_claude_still_finishes_and_claude_takes_the_next`
  - `test_a_launch_that_is_not_read_only_on_the_owners_plan_is_stopped_at_init`
  - `test_a_review_room_changed_during_the_review_voids_it`
  - `test_a_reviewer_that_calls_anything_but_a_read_only_tool_is_refused`
  - `test_a_model_that_names_another_sha_is_refused`
  - `test_a_review_that_fails_every_run_blocks_with_the_reason_instead_of_waiting_for_ever`
  - `test_the_token_file_must_be_private_and_never_an_api_key`
  - `test_an_api_key_in_the_token_file_makes_the_reviewer_unavailable_so_the_task_blocks_with_the_gap`
  - `test_both_loop_scripts_run_the_claude_reviewer_by_default_on_the_workers_cli_and_token`
  - `test_probe_review_launches_the_reviewer_as_a_review_would_and_stops_it_at_init`

### Outside the scoped diff, but read or imported by the loop

| File | Change |
|---|---|
| `config/builder_skills.json` | New. Full content below |
| `config/review_principals.json` | The new entry, in full below |
| `app/logging/turnlog.py` | `redact_text`, used by the status projection (`status.py`), now also replaces a bare 16–19-digit number that passes the Luhn check with `[card]` (PR #94). More is redacted; nothing less |

### Unchanged in the range (check against the diff)

- **Byte-identical at base and candidate:**
  - `lifecycle.py`, `contracts.py`, `store.py`, `state.py`;
  - `policy.py`, `routing.py`, `review_acceptance.py`, `review_result_gate.py`;
  - `github_acceptance.py`, `workspaces.py`, `generated.py`, `scheduler.py`;
  - `workers/integrator.py`.
- **In `dispatcher.py`, no changed line falls inside:** `tick`, `_step`, `_start_attempt`,
  `_dispatch_review`, `_admit`, `_route_repair`, `_integrate`, `_land`, `_land_checked`, `_eligible`,
  `_refresh`, `_block` or `review_packet`.
- **So the kernel's record schemas are unchanged.** The records the base wrote are read by the same
  code.

## What to judge (these hold for every re-pin)

1. **Exact SHA.** The review is of `ef204bc2` exactly, and the gate's answer is for that SHA. Nothing
   here authorises any other SHA.
2. **Reviewer independence.** A candidate's author may never satisfy its own review. Check that the
   candidate keeps this: `routing.py` is unchanged, and so is the builder principal's exclusion.
3. **Restart and state compatibility.** The candidate must start on this host's store, runtime and
   journal as the base left them, with the flags above. It must not refuse, rewrite, duplicate or
   lose any record. New files (stop reports, skill folders, reviewer rooms) must be additive.
4. **Fail-closed acceptance.** The GitHub gate still decides at dispatch, admission, integration and
   landing. Anything the candidate cannot prove must stop work rather than let it proceed.
5. **Protected paths.** No build may change a protected path, and the list only grows.
6. **No weakening** of the check sandbox, landing (DEC-064's four conditions), the journal, secret
   handling, or the owner's gates.

Judge afresh, from the diff and the tests. A finding blocks only when it shows a material defect in the
candidate's behaviour, authority, safety, state handling or required evidence on this host. If
something in this packet itself is wrong or missing, say so plainly, as a finding about the packet.

## About the sections after this head

The re-pin script adds four sections:

1. **The GitHub gate record** at the candidate.
2. **"Evidence for F-02".** This is standing read-only evidence from this host that the inbox
   adapter's claims and receipts are excluded from the state journal's git work tree.
   `remote_engineering.py` `poll` and `run` check that condition at start-up, at both the base and the
   candidate. "F-02" is the label of the earlier review finding that first asked for this evidence; it
   is not a finding of this review.
3. **The commits in the range.**
4. **The scoped diff:** the loop's code (`app/orchestrator`, `app/remote_engineering`, and the
   `engineering_dispatcher.py`, `remote_engineering.py` and `engineering_kernel.py` scripts), plus
   every test file that names a loop module. Several of those tests concern CLIVE's production app
   (Builds, research, the release service, deploy) and only mention loop modules. The loop-relevant
   tests are the ones listed above.

## Config files the loop reads, at the candidate (not in the scoped diff)

### `crooks-assistant/config/builder_skills.json` (new in this range)

```json
{
  "schema": "clive.builder_skills.v1",
  "why": "The skills the engineering loop's builders get, and no others (app/orchestrator/workers/skills.py). The owner's decision of 30 September 2026: his curated skill list is his approval (OWNER_DECISIONS_2026-09-30.md). These are the four design skills he vendored into the repository (.claude/skills/README.md), each pinned by the sha256 of every file. A protected path: a builder can never change it; a Director changes it through a reviewed pull request, and it takes effect at the loop's next re-pin.",
  "skills": [
    {"name": "design-taste-frontend", "source": "repo", "path": ".claude/skills/design-taste-frontend",
     "files": {"SKILL.md": "aa194351b246b8b4799099d4ed7b033d29eab6e6e3d58d8d2172978be7b3ec89"}},
    {"name": "high-end-visual-design", "source": "repo", "path": ".claude/skills/high-end-visual-design",
     "files": {"SKILL.md": "e1e32f5e2d420872c6c7332b53d5ff7721946766b78c4822b424c2d512c8fdbc"}},
    {"name": "image-to-code", "source": "repo", "path": ".claude/skills/image-to-code",
     "files": {"SKILL.md": "4c060a8064a8b13380bc2ef3d6e6a1d0b1e316aa093cd9807d0ce9e4eeb037fa"}},
    {"name": "web-design-guidelines", "source": "repo", "path": ".claude/skills/web-design-guidelines",
     "files": {"SKILL.md": "f4647ca866a3accf763777f83e7682954f0187cd6bea7eea0399796652414e8f",
               "web-interface-guidelines.command.md": "5a775e6411f790f518dbc9c1fa7c50a89e6873502d9a3530a6eb223a590bcfe8"}}
  ],
  "cli_skills_off": ["design", "doctor", "plugin-authoring"]
}
```

### `crooks-assistant/config/review_principals.json`: the entry added in this range

```json
{
  "principal_id": "claude-reviewer",
  "kind": "model",
  "model_family": "claude",
  "roles": ["reviewer"],
  "may_review": true,
  "recorded_at": "2026-10-08",
  "recorded_by": "owner ruling of 8 October 2026 (DEC-071, ruling 10: replace the GPT reviewer with a Claude reviewer); DEC-076",
  "reason": "The loop's exact-SHA reviewer as Claude on the owner's plan (app/orchestrator/reviewers/claude.py). It is a principal of its own, separate from the builder principal claude by how it runs, not by model family: a fresh session each review (its own session id, never resumed, nothing persisted, an empty HOME with no settings, memory or CLAUDE.md), a review room of its own exported from the candidate's git objects (never a builder's workspace), and only Read, Glob and Grep under dontAsk, so it cannot edit the candidate. The launch is checked at its init event and the room is compared with the commit's blobs after every review. It never authors: the loop's builders are the principal claude, which still may not review. The cognitive diversity of a second model family is given up by the owner's ruling; routing.py records that diversity is never what eligibility rests on.",
  "conditions": [
    "candidate_sha must be an exact 40-character SHA, never a branch name",
    "the SHA must be re-resolved at decision time; CANDIDATE_SHA_DRIFT voids the review",
    "the reviewer workspace is its own export of the candidate at that SHA (REVIEWER_NOT_AT_CANDIDATE), never a builder's (SAME_WORKSPACE)",
    "the reviewer workspace must be read-only and clean (REVIEWER_WORKSPACE_IS_WRITABLE, REVIEWER_WORKSPACE_IS_DIRTY): verified after every review",
    "a fresh session per review (SAME_SESSION, STALE_CONTEXT)",
    "never authors a candidate; never runs on an API key"
  ]
}
```
