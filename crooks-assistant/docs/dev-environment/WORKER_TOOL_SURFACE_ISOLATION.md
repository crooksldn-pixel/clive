# Worker tool-surface isolation — design and test proposal

**Status:** PROPOSAL. Nothing here is installed. The watcher service, its unit file and
`/root/.claude` were not touched in the round that wrote this. Reference code:
`crooks-assistant/scripts/roster_assert.py`, tests `tests/test_roster_assert.py`.

## 1. The problem, as observed

The ECC audit (bridge round 2026-09-19, product memory `ENGINEERING_STACK_REUSE_PLAN.md`) ran
inside a headless engineering session and read its own tool roster. The session had been
launched by the watcher as

```
HOME=/root  cd /opt/crooks-builder
claude --print --model claude-fable-5-1 --effort high --permission-mode acceptEdits \
       --allowed-tools Read,Edit,Write,Glob,Grep,Bash
```

and its roster contained, besides the six engineering tools: ~250 `mcp__claude_ai_*` tools
from the owner's claude.ai connectors (Gmail, Shopify, Google Drive, Resend, Omnisend, Claude
Docs — including `send_message`, `create-product`, `set-inventory`, `send-broadcast`,
`create-api-key`); fourteen further connectors listed as needing auth; four account-synced
plugins exposing `design:*`, `marketing:*`, `base44:*`, `wix:*` skills; and the built-in
`Agent`, `Workflow`, `WebFetch`, `WebSearch` and cron tools. None of that comes from a file in
the repository: `/root/.claude.json` has `mcpServers: {}`, there is no `.mcp.json`, and
`/root/.claude/settings.json` is `{"theme": "dark"}`. It comes with the **account** whose
login lives in `/root/.claude`, which the watcher needs for OAuth refresh.

`--allowed-tools` does not narrow this. It auto-approves the listed tools; it removes nothing.
One read-only probe of a non-business connector tool was refused by the permission layer
("you haven't granted it yet"), so an unattended invocation is denied *today* — by prompt-
denial behaviour that vanishes the moment permission mode is widened or a permission-prompt
host auto-approves. The Orchestrator safety contract says engineering permission never grants
business-action permission; at present that separation is accidental.

## 2. Design: four layers, cheapest first, and the one that turns prose into evidence

| Layer | Change | Who decides | Status |
|---|---|---|---|
| 1 Launch flags | narrow the roster at launch (§3) | unit-file edit → owner | proposed |
| 2 Identity | a dedicated engineering login/HOME with no connectors, or API-key auth with `--bare` | owner (account, possibly spend) | proposed |
| 3 Proof at launch | read the `system/init` message and **fail closed** on any unexpected tool (§4) | watcher source change, reviewed | reference code here |
| 4 Account | review the connector and plugin grants on the account the server uses | owner | proposed |

Layer 3 is built regardless of which of 1–2 is chosen: it is what makes "the worker only has
engineering tools" a checked statement instead of a sentence in a prompt.

## 3. Layer 1 — launch flags: what the CLI documents, and what must be tried

Read from `claude --help`, Claude Code **2.1.276**, on the builder host. Quoted text is the
help text; everything else is inference and is marked so.

| Flag | Help text (documented) | Effect we need | Verified? |
|---|---|---|---|
| `--strict-mcp-config` | "Only use MCP servers from --mcp-config, ignoring all other MCP configurations" | drop every file-configured MCP server | **NOT VERIFIED** whether *account* (claude.ai) connectors count as "other MCP configurations". This is the single most important empirical question. |
| `--mcp-config '{"mcpServers":{}}'` | "Load MCP servers from JSON files or strings" | with the flag above, an explicitly empty server set | not tried |
| `--restricted` | "removes the built-in tools that run commands or code (Bash …) and WebFetch unless --tools names them, and ignores user, project and local settings files … add --strict-mcp-config to skip MCP servers too … refuses bypassPermissions" | too broad for the bridge as-is (it needs Bash and project settings) but its "skip MCP servers too" phrasing suggests `--strict-mcp-config` is the MCP switch | not tried |
| `--permission-prompts none` | "nobody: anything that would prompt is denied automatically; the permission mode still decides everything else" | turn today's *implicit* prompt-denial into an explicit policy | **NOT VERIFIED** that a run under `none` does not stall on a denied prompt, and that `acceptEdits` still auto-approves edits |
| `--disallowed-tools WebFetch,WebSearch,Agent,Workflow` | (listed; no help sentence) | remove built-ins the bridge has no contract to use | not tried; also unknown whether it removes them from the roster or only denies them |
| `--setting-sources project` | "Comma-separated list of setting sources to load (user, project, local)" | ignore `/root/.claude/settings.json` so only the reviewed project file applies | not tried; unknown whether **synced plugins** follow the user setting source |
| `--disable-slash-commands` | "Disable all skills" | remove `design:*`, `marketing:*`, `base44:*`, `wix:*` and any other synced plugin surface | not tried; unknown whether it also disables project skills under `.claude/skills/` (it says "all") |
| `--plugin-dir <path>` | "Load a plugin from a directory or .zip for this session only" | an explicit allow-list instead of account sync, if any plugin is ever wanted | not needed now |
| `--bare` | "skip hooks, LSP, plugin sync, attribution, auto-memory … Anthropic auth is strictly ANTHROPIC_API_KEY or apiKeyHelper (OAuth and keychain are never read)" | the strongest isolation, but drops **hooks** (so the project guard would not run) and needs a provisioned API key with its own spend | owner decision; not for this experiment |
| `--output-format stream-json` | "realtime streaming" (print mode only) | the `system/init` message layer 3 reads | print-mode `stream-json` may require `--verbose`; not tried |
| `--max-budget-usd` | "Maximum dollar amount to spend" (print mode) | a hard ceiling per run if API-key auth is ever used | n/a under the Max login |

**Proposed unit change (sketch, not applied)** — `crooks-bridge-watcher.service`
`Environment=` lines, or the `run_claude` argument list in `bin/crooks-bridge-watcher`:

```
--strict-mcp-config --mcp-config '{"mcpServers":{}}'
--permission-prompts none
--disallowed-tools WebFetch,WebSearch,Agent,Workflow
--setting-sources project
--output-format stream-json
```

`--disable-slash-commands` is held back until it is known whether it also removes project
skills (`.claude/skills/`), which the experiment wants to keep.

## 4. Layer 3 — the roster assertion

`scripts/roster_assert.py` decides on the first `{"type":"system","subtype":"init"}` message:

- **any** `tools` entry starting with `mcp__` → violation;
- any built-in outside `{Read, Edit, Write, Glob, Grep, Bash}` → violation (named);
- any entry in `mcp_servers` → violation unless explicitly allowed (default: none);
- any plugin-namespaced slash command (`name:cmd`) → violation unless its prefix is allowed;
- `permissionMode` other than the one the unit launched with → violation;
- `tools` missing or not a list → violation ("cannot prove the roster"); any non-object message
  → violation. Missing evidence is UNKNOWN and UNKNOWN fails.

It returns a report with a sha256 **roster digest** over the sorted tool and server names, for
the outbox. `tests/test_roster_assert.py` proves each rule and the fail-closed paths on fake
messages. Exit code 3 from the script means "do not proceed".

**What is assumed about the init message and must be confirmed empirically:** the field names
`tools` (list of str), `mcp_servers` (list of `{name, status}`), `slash_commands` (list of
str), `permissionMode`. These are the names the Agent SDK documents for the stream-json init
event; they were not captured on this host in this round because capturing one means launching
a Claude session under the owner's account, which is outside the round's approval.

**Watcher integration (sketch, not applied):** `run_claude` pipes Claude's stdout through a
small reader that (a) writes every line to the run log as today, (b) parses the first line as
JSON and runs `roster_assert`, (c) on violation sends TERM to the Claude process (the existing
`timeout --signal=TERM --kill-after=60` wrapper already owns that), records
`roster VIOLATION` with the violations in the watcher log, and leaves the inbox unprocessed so
the round is retried only after a human looks. On success it records the digest and continues.
The watcher's own test harness (the 126-test installer/upgrade suite recorded in
CURRENT_TRUTH) is where the reader would be tested with fake init lines.

## 5. Verification plan — what proves each layer

Every step below launches a Claude session under the account the server uses. That is an
**owner-approved live check**, not something a bridge round does on its own: it spends
account usage and the roster it reveals is the owner's. None of it invokes a business tool.

1. **Baseline capture.** Today's flags plus `--output-format stream-json`, prompt `echo ok`.
   Save the init line. Expected: the roster in §1. This binds the problem to evidence.
2. **`--strict-mcp-config --mcp-config '{"mcpServers":{}}'`.** Same prompt. Pass criterion:
   no `mcp__*` in `tools`, `mcp_servers` empty. If account connectors survive this flag, layer
   1 cannot deliver MCP isolation and layer 2 becomes mandatory.
3. **`--setting-sources project` and `--disable-slash-commands`**, separately. Pass criterion:
   no plugin-namespaced `slash_commands`; and, for the second, whether project skills also
   vanish (record either outcome; it decides which flag the unit uses).
4. **`--permission-prompts none`.** Prompt that attempts one non-business, read-only,
   prompt-requiring action (the same Claude Docs `guide` probe the audit used). Pass
   criterion: the run ends with an explicit denial, not a hang, and `acceptEdits` edits still
   apply.
5. **Roster assertion end to end.** Feed the captured init line to `roster_assert.py`; then
   feed the baseline (dirty) line; expected exit 0 then exit 3. Already proved on fake
   messages; this step proves it on a real one.
6. **Project hooks under `--print`.** Once `.claude/settings.json` exists, a session whose
   prompt runs `git reset --hard` must report the guard's denial. This also settles whether
   project hooks need a trust step in non-interactive mode.

Each capture goes into the candidate's docs with the Claude Code version and the exact flags,
because the help text is the only documentation and it changes between versions.

## 6. Out of scope, on purpose

- No unit-file edit, no watcher restart, no change under `/root/.claude` (DEC-049 excludes
  them; bridge rule 8 makes them owner steps).
- No dedicated identity or API key (provisioning and spend).
- No account-level connector review (owner only).
- Not a replacement for the systemd sandbox or the builder/production split: this removes
  unnecessary *tool surface*; it does not make a shared `/root` an isolation boundary
  (Orchestrator §8).
