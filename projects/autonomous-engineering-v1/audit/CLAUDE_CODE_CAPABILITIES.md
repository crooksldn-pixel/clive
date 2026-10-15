# Claude Code capabilities relevant to V1 (official documentation, checked 2026-10-14)

These answers were gathered from Anthropic's Claude Code documentation through a summarising fetch.
Spot-check a phrase before quoting it as normative. "Not documented" means it was not in the pages
read. The documentation is external evidence; it is not authority over CLIVE's source or decisions.

## Supervisor durability (why Desktop must not be the durable worker)

- **Desktop Code tab over SSH** ([desktop docs](https://code.claude.com/docs/en/desktop)):
  - The session runs on the remote host under a helper, so it survives a dropped SSH connection
    until the task finishes, needs input, or hits a limit.
  - It stops if Desktop cannot rejoin.
  - It ends if the host restarts, or if the SSH server kills processes on disconnect.
  - Pending approvals wait indefinitely.
  - The documentation says: "don't count on a task to run overnight."
  - **Consequence:** P-001 stands. Work becomes durable only when it is filed into the loop.
- **`claude -p`:** there is no supervisor process. SIGTERM exits 143 mid-turn
  ([headless](https://code.claude.com/docs/en/headless)). The loop already detaches workers and
  recovers results from logs.
- **Background sessions (`claude --bg`):** these survive the shell but not a reboot. An idle,
  unattached session stops after about an hour ([agent view](https://code.claude.com/docs/en/agent-view)).
  They are not a substitute for the loop.

## Headless flags the loop depends on ([CLI reference](https://code.claude.com/docs/en/cli-reference))

All of the following exist. Points that matter for V1:

- **Pass `--permission-mode` explicitly.** From v2.1.285 a `-p` run may start in `auto`
  ([permission modes](https://code.claude.com/docs/en/permission-modes)). The loop already passes
  `dontAsk`.
- **Use `--tools`, not `--allowedTools`, to restrict which tools exist.** The loop already passes both.
- **`--bare` cannot be used.** It skips OAuth and requires an API key, which MAP rule 5 forbids.
- **Strip `ANTHROPIC_API_KEY` from child environments.** In `-p` it overrides the subscription login.
  The loop builds the environment from scratch.
- **`--setting-sources ""`** drops user and project settings; skills from `--add-dir` and
  `--plugin-dir` still load. **`--disable-slash-commands`** disables all skills and commands.
  **`skillOverrides`** can turn individual skills off.
- **`--max-turns`** exits with an error when the limit is reached. **`--output-format stream-json`**
  needs `--verbose`.

## Skills ([skills](https://code.claude.com/docs/en/skills))

- A headless session loads skills from:
  - the managed or enterprise location, `~/.claude/skills` and project `.claude/skills`;
  - `--add-dir` directories;
  - plugins;
  - claude.ai account skills (`syncClaudeAiSkills: false` turns these off).
- **Per-task routing is achievable with the loop's existing mechanism.** The loop builds one plugin
  directory per attempt (`workers/skills.py`). Putting only the routed skills in it is a per-task
  allow-list, and it needs no new Claude Code feature.

## Hooks ([hooks](https://code.claude.com/docs/en/hooks))

- In a PreToolUse hook, exit code 2 blocks the call. **Any other non-zero exit lets the call proceed**,
  and so does a timeout. These are fail-open traps. The loop does not rely on hooks for scope; it
  checks scope on the candidate after the build, which fails closed. Keep it that way.

## Agent SDK ([overview](https://code.claude.com/docs/en/agent-sdk/overview))

- The SDK offers typed results, hooks and per-session skill lists.
- **Subscription login for the SDK is not clearly supported:** "Unless previously approved, Anthropic
  does not allow third party developers to offer claude.ai login or rate limits for their products…",
  and the quickstart uses `ANTHROPIC_API_KEY`.
- **Consequence:** V1 stays on the CLI, which the loop already drives. Do not migrate to the SDK.

## Usage limits ([errors](https://code.claude.com/docs/en/errors))

- Max plan allowances are rolling session (5-hour) and weekly limits. They are shared by claude.ai,
  Claude Code and Desktop. CLIVE's live turns, the staff turns, the builders, the reviewers and the
  supervisor all draw on one plan (DEC-064, DEC-071 ruling 36).
- **There is no official guidance on how many concurrent sessions one Max plan supports.**
  Concurrency must be measured (CONCURRENCY_PLAN).
- **What the loop can act on:**
  - Limit messages read like "You've hit your session limit · resets 3:45pm" or "…weekly limit…".
  - The stream carries `rate_limit_event` (already parsed in `workers/claude.py:672-675`) and
    `api_retry` events with an error category.
- **The exit code for a plan-limit stop in `-p` is not documented.** Classify it from the stream: park
  the work until the reset time. A plan limit is not a builder failure and must not burn a repair
  round.

## Playwright

- **[microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp)** says: "If you are using a
  coding agent, you might benefit from using the CLI+SKILLS instead". MCP "remains relevant for
  specialized agentic loops that benefit from persistent state".
- **[microsoft/playwright-cli](https://github.com/microsoft/playwright-cli)** (`@playwright/cli`)
  exists. It is not adopted by V1, because exact-SHA CI already runs CLIVE's browser screen tests in
  real Chromium.
