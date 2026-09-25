# Trunk landing ce791d03 deployed; engineering line landed; bridge watcher retired

2026-09-25, owner-authorised, one session. Production is `/opt/crooks-os`, served by
`crooks-assistant.service`.

## 1. Deploy of clive/trunk at ce791d032dcc8cf9b761ca40ce0b08a259c897a2

**Gate, before anything was touched.**

- GitHub acceptance **run 118** (`36071935518`), event push, branch `clive/trunk`, attempt 1,
  on exactly `ce791d03`: **success**. All five required gates pass — ruff,
  pytest_control_plane (44), product_memory_structure (25 documents), pytest_offline_full
  (3449 passed, 8 skipped, 2 deselected), secret_scan (no leaks). The artifact says of itself
  `accepted: false`, `independent_review: required`.
- **Independent exact-SHA GPT review: READY, zero findings** (`gpt-5.6-sol`, effort high,
  read-only, fresh context). Packet composed here for this landing, reviewed base
  `0bbcfb69e7be36f64261ddb56b9532dbbfca542f`, and framed as what it is: two branches that were
  each already reviewed READY at their own SHAs, merged, with only the merge result left to
  judge. Result: `ce791d032dcc8cf9b761ca40ce0b08a259c897a2.review.json`.

**What the packet put in front of the reviewer.** Of the 14 commits in
`0bbcfb69..ce791d03`, exactly two had never been judged by any principal — the two trunk merge
commits `247d53d5` (PR #3) and `ce791d03` (PR #4). Everything under them was covered by a
review at its own SHA:

| landed | branch tip | review | verdict |
|---|---|---|---|
| PR #3 `claude/ci-age-days-floor-2026-09-22` | `ef3d08ff` | `ci-age-days-floor-a1`, gpt | READY |
| carried by PR #3 | `84e12e77` | `agent-environment-truth-repairs-a1`, gpt | READY |
| PR #4 `claude/ci-stream-integration-judgment-2026-09-22` | `b68e6e82` | `judgment-ledger-ci-stream-integration-a1`, gpt | READY |
| carried by PR #4 | `1958b327` | `judgment-ledger-corrections-a3`, gpt | READY |

Both merges are exact unions: for each, the paths the side branch changed since the fork point
and the paths the merge changed against trunk are the same set — nothing lost, nothing invented.
`git show --cc` is empty for `ce791d03` and for the two inner merges; the whole landing contains
**one** textually resolved hunk, the route import list in `app/main.py`, resolved as the union
both sides need. One protected path is touched, `crooks-assistant/config/agent_roster.json` —
a new file, and it reached trunk through a pull request the owner merged by hand, which is the
lane `PROTECTED_PATHS` reserves.

**Why the previous deploy attempt is now unblocked.** `0bbcfb69` failed acceptance run 107 on
`pytest_offline_full`, one golden scenario: `test_the_golden_scenarios[query_international_waiting]`.
That was not CI flake and not live-store drift. `ef3d08ff` on the PR #3 line is its repair:
`age_days` was rounded to a tenth, so fourteen days and twenty-three hours read as 15.0 and then
floored to 15, and the scenario failed for the last seventy-two minutes of every day.
`age_days_tenths` truncates instead. The same test file is byte-identical at both SHAs.

**Deploy.**

- Production was at `ca388ceeedb54cfd495fb2b5205ec2184db9ccae` on
  `claude/linux-prod-migration-production`, clean worktree — `ce791d03` is 20 commits ahead,
  0 behind, a clean fast-forward.
- **No dependency install.** No lockfile or dependency manifest changes between the two SHAs
  (pyproject, requirements, poetry, uv, package.json all untouched), so the existing venv was
  left exactly as it was, per the standing instruction.
- `git fetch origin clive/trunk` then `git checkout --detach ce791d03` in `/opt/crooks-os`;
  `systemctl restart crooks-assistant.service` at 06:46:31Z.

**Health, after.**

- unit `active`, `NRestarts=0`
- `GET /health` → **200** (healthy 6s after restart)
- `GET /health?fresh=1` → the live read that exercises both integrations:
  `checks.shopify.ok = true` (CROOKSLDN, Europe/London), `checks.gmail.ok = true`
  (team@crooksldn.com, compose/modify verified by Google). No failing check in the whole block.
- build string moved `0b069c7e69ab` → `fc64b842ed67`, so the new code is what is serving
- `GET /environment/state` → **200**: the route this landing added is live
- two minutes of journal after the restart: no error, no exception, no traceback

Rollback was prepared and not needed: `git checkout claude/linux-prod-migration-production`
(returns to `ca388cee`) and restart.

## 2. The engineering line landed into trunk

`clive/trunk` merged with `claude/remote-engineering-control-v1-activation-successor-2026-09-24`
at `4c32bb3d5f4935402c9cdc897914370950f7f206` — the SHA the remote engineering loop is pinned to,
and the SHA an independent GPT review judged at its own SHA.

One conflict, as expected: `crooks-assistant/docs/product-memory/README.md`, where both sides had
appended to the index. Resolved as the union — 2 lines from trunk, 3 from the branch, 5 kept,
none reworded or dropped. The merge is again an exact union of both sides by path:
nothing lost, nothing invented.

Full acceptance was run locally on the merge commit before pushing, with the same gate script CI
runs (`scripts/acceptance_provenance.py --suite full`) and the same pinned scanner version
(gitleaks 8.30.1).

## 3. The bridge watcher is retired

`crooks-bridge-watcher.service` stopped and disabled at 06:56:20Z. Final state recorded: it had
been `active` since 2026-09-20T07:32:56Z, `enabled`, with its last real work on 2026-09-22 —
`last-run: ok 2026-09-22T07:58:53Z`, last processed inbox blob
`7f4aa77a0fd998d87ea4de28aea34dd12c7bcb6c`, `failures: 0`. It is now `inactive (dead)` /
`disabled`, with no process left. The unit file is left in place unchanged; only the
`multi-user.target.wants` symlink was removed. `/var/lib/crooks-bridge` is left intact.

Consequence worth naming: `config/agent_roster.json`, which this deploy put into production,
declares `clive-bridge-worker` with a `systemd_bridge` probe against this unit. The roster says in
its own comment that being listed is not evidence a worker exists and that an entry whose probe
finds nothing is reported OFFLINE. So `/environment/state` will now report that worker OFFLINE —
which is the roster working, not a fault.

`clive-remote-engineering.service` was left untouched throughout: `active`, `enabled`,
still pinned to `4c32bb3d`.

## 4. The builders are on Claude Opus 5.5

Last night this was attempted and rolled back: CLI **2.1.282** reports two builtin plugins —
`telemetry@builtin` and a new `agents-md@builtin` — and the pinned loop code
(`4c32bb3d`, `app/orchestrator/workers/claude.py:69`) allows only `telemetry@builtin`, so its
launch-surface guard killed every worker and blocked a task. The conclusion recorded then was
that `claude-opus-5-5` and the pinned loop code were mutually exclusive, because the model needs
CLI ≥ 2.1.280 and ≥ 2.1.280 was assumed to ship `agents-md`.

That last step is where the assumption was wrong, and it is worth stating plainly because it is
what unblocked this. **2.1.280 supports `claude-opus-5-5` and reports only `telemetry@builtin`.**
`agents-md@builtin` arrives in 2.1.282, not in 2.1.280. So there is a version that satisfies both
the model and the guard, and nothing pinned had to change.

Verified against the loop's own launch surface, not by inference — the exact flag set the
dispatcher builds (`--restricted`, its tool list, `--permission-mode dontAsk`,
`--strict-mcp-config`, `--setting-sources ""`, `--disable-slash-commands`, `--json-schema`,
`--effort high`) with the loop's own worker OAuth token:

```
init  : version 2.1.280 | model claude-opus-5-5 | plugins ['telemetry@builtin']
        | skills [] | slash [] | mcp [] | permissionMode dontAsk
result: success | is_error False | models ['claude-opus-5-5']
```

Every clause the guard checks is satisfied, so the refusal that killed the last attempt cannot
recur for this reason.

**Applied.**

- CLI the loop's workers ran before this: `/usr/local/bin/claude` →
  `/usr/local/lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`, **2.1.276**,
  sha256 `8a56c8a1…c6145`. It did **not** auto-update today — binary mtime is still
  2026-09-18T16:24:37Z, nothing under the package changed today, and there is no
  `~/.claude/downloads` or `versions` staging directory.
- 2.1.280 installed into an isolated prefix (`/srv/clive-engineering/cli/2.1.280/`) and pinned to
  the fixed path `/srv/clive-engineering/bin/claude`, sha256
  `1e08503dbdf3c2cb0d706d32f3408277388d1c76ef108673e8fe42c1b322925b`, byte-identical to the
  install. Production's own CLI is untouched: still **2.1.276**, sha256 unchanged.
- Unit backed up, then `--worker-cli /srv/clive-engineering/bin/claude`,
  `--worker-model claude-opus-5-5` and `--worker-effort high` added; `--max-concurrent 2`
  preserved. `systemd-analyze verify` clean. Applied with **no worker attempt running**, so
  nothing was interrupted. `daemon-reload` and restart at 07:03:21Z.
- The live process carries the new argv, the unit is `active` / `enabled`, `NRestarts=0`.
- **12 consecutive clean cycles** since the restart: no intake error, no publish error, no
  dispatcher event.
- `prod_state` is byte-identical to the post-deploy baseline — the loop touched nothing.

**What could not be confirmed, and why.** The earlier instruction's last check was that the *next
worker attempt* reports `claude-opus-5-5`. No worker has launched, because there is nothing
buildable: `generative-ui-v1-evidence-scenes` is the only task that would build and it still
carries last night's deterministic blocker
(`worker launch surface refused: plugins beyond the builtin allowance: agents-md@builtin`).
Rolling the CLI back reverted the cause but not the recorded state, and clearing it is a
journalled control-plane write — a kernel resume — which remains the owner's decision, untaken.
The remaining tasks are BLOCKED for unrelated, pre-existing reasons, COMPLETE, or OWNER_GATE.
So the configuration is proven at the launch surface and on a real run of the pinned binary with
the loop's own credentials, but not yet on a dispatcher-launched worker.

## Baseline note

The `prod_state` baseline of 2026-09-24T15:02Z is superseded by this session, in exactly two
intended places and nothing else:

```
-/opt/crooks-os ca388ceeedb54cfd495fb2b5205ec2184db9ccae   (step 1: the deploy)
+/opt/crooks-os ce791d032dcc8cf9b761ca40ce0b08a259c897a2
-active                                                     (step 3: the bridge watcher)
+inactive
```

`/opt/crooks-interactive` is unchanged at `31fb7553`, both worktrees are clean, and the
`systemctl cat` hash of the two production units is unchanged at `85e69489bc13299b`.
