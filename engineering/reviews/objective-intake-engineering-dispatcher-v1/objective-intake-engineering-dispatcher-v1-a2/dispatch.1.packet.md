# CLIVE review packet — objective-intake-engineering-dispatcher-v1 r2, attempt a2

```json
{
  "task_id": "objective-intake-engineering-dispatcher-v1",
  "task_revision": 2,
  "attempt_id": "objective-intake-engineering-dispatcher-v1-a2",
  "candidate_sha": "da15c629e95ad7ff27903d417f63f16b78f467bb",
  "base_sha": "18c3153a2eec10c6343153b550776afed3bec2ba",
  "target_branch": "claude/objective-intake-dispatcher-v1-uz8g7z",
  "repository": "crooksldn-pixel/clive",
  "author_principal": "claude",
  "author_session": "session_01TupGArGERqu9aRQJ41Sce5",
  "reviewer_principal": "gpt",
  "review_mechanism": "bootstrap manual handoff (owner relays); allowed once for this task",
  "state_record": "clive/engineering-state"
}
```

Your verdict applies to exactly `da15c629e95ad7ff27903d417f63f16b78f467bb` and to nothing else. It is a fast-forward of `c425cb72` (all code) plus one README index line.

## What this is, and what it is not

This is the bootstrap build of **Objective Intake + Engineering Dispatcher V1** around the frozen kernel `18c3153a`. The code that would remove the courier now exists, but that does **not** prove the no-courier milestone. That milestone needs a separate, real product objective to enter through the new intake and reach independently reviewed COMPLETE, BLOCKED or OWNER_GATE with nobody relaying. It cannot happen yet, because **no programmatic independent reviewer exists** (see "Reviewer reality").

## Base

- Base: `18c3153a` (the frozen kernel lineage). It is the only lineage that contains `app/orchestrator/lifecycle.py` and `scripts/engineering_kernel.py`. The CI/Support lineage (`b68e6e82` → `2dbb97bc`) diverges from it at `2a08f456` and has neither file.
- No merge of lineages was performed.
- Kernel and authority files are unchanged: `git diff --name-only 18c3153a da15c629 -- app/orchestrator/{lifecycle,contracts,policy,routing,review_acceptance,review_result_gate,store,state}.py scripts/engineering_kernel.py config/` prints nothing.

## Changed paths (base..candidate), all inside r2's allowed paths

```
crooks-assistant/app/orchestrator/dispatcher.py            (new, controller)
crooks-assistant/app/orchestrator/objectives.py            (new, intake)
crooks-assistant/app/orchestrator/workspaces.py            (new, per-attempt clone)
crooks-assistant/app/orchestrator/workers/{__init__,base,claude}.py    (new, builder driver)
crooks-assistant/app/orchestrator/reviewers/{__init__,base,relay}.py   (new, typed result + reviewer drivers)
crooks-assistant/scripts/engineering_dispatcher.py         (new, CLI door)
crooks-assistant/tests/test_engineering_dispatcher.py      (new, 28 tests)
crooks-assistant/tests/test_engineering_objective_intake.py (new, 21 tests)
crooks-assistant/tests/test_claude_worker_adapter.py       (new, 21 tests)
crooks-assistant/docs/product-memory/ENGINEERING_DISPATCHER_V1.md (new, design/operations)
crooks-assistant/docs/product-memory/README.md             (+1 index line)
```

Read `ENGINEERING_DISPATCHER_V1.md` first. It maps every lifecycle stage to what the dispatcher does and which kernel verb records it.

## Facts established in this session (observed, not assumed)

**Worker invocation**

- Claude Code CLI 2.1.280, `claude -p` headless, `--output-format stream-json --verbose`. The Python Agent SDK is not used: it wraps the same CLI, and a detached CLI process with a log file is what makes restart re-attachment possible.
- Launch flags: `--session-id <CLIVE-chosen uuid> --restricted --tools Read,Edit,Write,Glob,Grep --allowedTools Read Edit Write Glob Grep --permission-mode dontAsk --strict-mcp-config --mcp-config '{"mcpServers":{}}' --setting-sources "" --disable-slash-commands --no-session-persistence --max-turns 200 --json-schema <report schema>`.
- Environment: only `PATH, HOME (fresh per attempt), LANG, TMPDIR, CLIVE_ATTEMPT_ID`. GH_TOKEN, cloud and proxy variables are not passed on.

**Authentication**

- Observed `apiKeySource: "none"`. The host-managed provider authenticated the sanitised process.
- The rate-limit event showed subscription windows (`five_hour`, `seven_day`), `isUsingOverage: false`, `overageStatus: rejected` (`org_level_disabled`). No pay-as-you-go. `total_cost_usd` in the result is the CLI's notional figure.
- No credential was read, copied or created.
- On a host where the login lives in `~/.claude`, the fresh HOME will not find it. The launch then blocks deterministically as an authentication failure. Providing `--worker-token-file` (`CLAUDE_CODE_OAUTH_TOKEN`) is an owner decision.

**Observed worker surface** (init event of the real smoke)

| Property | Observed |
| --- | --- |
| Tools | `Edit, Glob, Grep, Read, StructuredOutput, Write` |
| MCP servers | `[]` |
| Plugins | `telemetry@builtin` only |
| Skills | 0 |
| Slash commands | 0 |
| Permission mode | `dontAsk` |
| Session | Equal to the kernel's recorded session |

- An earlier probe with `Bash(git status)` and `Bash(git diff)` allowed had `git commit` and `curl` denied and listed in `permission_denials`.
- The launch check is fail-closed. Any extra tool, MCP server, non-builtin plugin, skill, other cwd, session or permission mode kills the worker and blocks the task before acknowledgement.
- Bash is off by default. Prefix allowlists leak (`git diff --no-index`), and `--restricted` confines only the file tools.

**Isolation**

- One attempt gets one `git clone --local` at `<root>/<task>/<attempt>/`.
- The clone is detached at the base, on branch `clive/attempt/<attempt>`, with its remote removed, and bound to its attempt by metadata in `.git`.
- CLIVE commits the tree. The candidate is `git rev-parse HEAD`, fetched back as `refs/clive/candidates/<attempt>` and verified.
- The scope comes from `git diff --no-renames`.

**Reviewer reality**

- **Programmatic GPT: none.** There is no OpenAI credential, and no supported programmatic ChatGPT review mechanism was found or verified. The OpenAI API would be a new secret and new spend, both owner decisions. **GPT was not invoked programmatically.**
- **Claude cannot review.** `config/review_principals.json` registers `claude` with `may_review: false`. The dispatcher also refuses the author principal.
- With the default `--reviewer gpt`, a finished candidate is **BLOCKED** with that exact gap, and nothing is dispatched.
- `--reviewer relay` works but is explicitly a **courier** path (`courier: true` everywhere it shows).

## Evidence (recorded on the kernel for attempt a2, names and sha256 in the store)

**`unit_tests`**: `70 passed` (the three new test files) at `da15c629`. The worker in these tests is a real subprocess: a fake `claude` executable speaking the recorded stream-json format. They cover:

- intake;
- one launch;
- restart re-attachment (5 fresh dispatchers while a worker lives: 1 launch);
- a crash mid-ingest that recovers the same candidate (this test failed before its fix);
- process death leading to a transient retry with a higher token, with bounded retries and backoff;
- authentication leading to a deterministic block;
- stall leading to a kill and cancel;
- liveness that is not progress;
- roster widenings (MCP, tools, session) refused;
- out-of-scope and empty trees never becoming candidates;
- failed checks as evidence, never as a candidate;
- no reviewer, or the author as reviewer, leading to BLOCKED with nothing dispatched;
- CHANGES_REQUIRED leading to a repair revision whose old verdict does not transfer;
- the convergence limit;
- stale and drifted verdicts refused, and prose never parsed;
- the relay marked as courier;
- an owner gate never lifted;
- COMPLETE only after verified integration (a moved target leads to BLOCKED);
- status output;
- the CLI door.

**`kernel_regression`**:

- Kernel, control-plane and product-memory structure tests: `112 passed`.
- Kernel and authority files are unchanged.
- Full suite at `da15c629`: `1 failed, 3169 passed, 11 skipped`; the one failure is `test_memory::test_a_prefetch_that_has_not_landed_is_never_waited_for`, which also fails on the pristine base. At `c425cb72` it was 4 failed. Two were mine: the unindexed document, fixed by this revision. Two are pre-existing and fail on the pristine base `18c3153a` in a full run (the second one intermittently: it passed at `da15c629`): `test_memory::test_a_prefetch_that_has_not_landed_is_never_waited_for` and `test_write_walkthrough::test_the_owner_asks_for_a_note_and_gets_a_card_that_says_only_that_it_is_ready`.

**`lint`**: `ruff check .` clean.

**`real_worker_smoke`**: a real `claude` (haiku) launched through the adapter, with dispatcher code at `c425cb72`, a throwaway journaled store and default `--reviewer gpt`. The kernel journal shows:

1. objective entered;
2. task r1;
3. assigned `dispatcher-smoke-a1`, token 1;
4. acknowledged from the init event;
5. progress: `worker edited crooks-assistant/docs/smoke/DISPATCHER_SMOKE.md`;
6. evidence `check-content`, `worker_transcript`, `worker_report`;
7. candidate `768b0d96e6b6…`, parent `18c3153a`, authored "CLIVE worker claude (dispatcher-smoke-a1)", workspace clean, no remote;
8. **BLOCKED**: "no eligible independent reviewer … gpt: no programmatic GPT reviewer exists …".

A second smoke with `--reviewer relay` reached REVIEWING with the packet in the relay outbox, marked COURIER. I did not act as its reviewer.

## Lifecycle of this task (clive/engineering-state)

- r1: created → assigned a1 (token 1) → acknowledged → cancelled. The reason was a scope omission: the new product-memory document must be indexed from `docs/product-memory/README.md`, which r1's scope lacked.
- r2: supersedes r1 (r1 is OBSOLETE) with exactly that one path added → assigned a2 (token 2), workspace at base → acknowledged → evidence → candidate `da15c629` (verified on origin) → review dispatched to gpt → **awaiting your verdict**.

## What to try to break (my own adversarial list; do not limit yourself to it)

1. Can any path make the dispatcher manufacture a state? For example: ack without a verified init, a candidate from prose, integration without the target ref at the accepted SHA, or COMPLETE without the records.
2. Can a stale or foreign verdict be admitted, or can a verdict transfer across revisions?
3. Can a worker widen its surface without the launch check catching it? What does the check *not* see?
4. Restart: can a second worker launch for one attempt, or can a candidate be lost?
5. Scope: can a worker land a path outside the objective's scope, or an objective reach a protected path (`PROTECTED_PATHS` in `objectives.py`)?
6. Authority: can anything here deploy, write business systems, add credentials, lift an owner gate, or spend?
7. Is the transient/deterministic classification ever the unsafe way round (an infinite retry on a deterministic failure)?
8. Is anything claimed in `ENGINEERING_DISPATCHER_V1.md` not true of the code?

Known limits, stated in the document's "Declared, not verified" section:

- reviewer facts are declared;
- worker identity is not cryptographic;
- the worker process reaches the model provider over the network, so this is a surface reduction, not a network sandbox;
- checks run repository code on the host;
- the design is Linux `/proc`, single host.

## How to answer

Return one JSON object of schema `clive.review_result.v1` (defined in `app/orchestrator/reviewers/base.py`):

- `verdict` is `READY` or `CHANGES_REQUIRED`;
- each material finding has `finding_id`, `material: true`, `finding`, `evidence_ref` (file:line at this SHA) and a bounded `required_repair`;
- non-material observations use `material: false`;
- `reviewer` states your principal (`gpt`), your session, and a read-only, clean workspace at `da15c629e95ad7ff27903d417f63f16b78f467bb`;
- `summary` is for people and decides nothing.

A prose verdict is also acceptable for this bootstrap task, since the owner relays it, but the typed form is what the dispatcher itself will admit from now on.
