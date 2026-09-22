# EXACT-SHA GPT REVIEW PACKET 6 — Agent Environment truth repairs (UNKNOWN is not online; a start time is not a heartbeat)

Generated 2026-09-22 21:32Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. Packet 4's candidates (71ac13a, 8c025aa) are preserved as the previous candidates; this is a fresh review of two new SHAs, one per repository.

## Identity

| Field | CLIVE (route + projection) | AGENT-ENVIRONMENT (adapter + UI) |
| --- | --- | --- |
| candidate_sha | `84e12e77e712ed454f12a6300f6e5f5b54391252` | `119bb9bff5a09aa7f1f04799396bcb68cf34a10a` |
| branch (head == candidate when written) | `claude/agent-environment-clive-state-2026-09-22` | `claude/clive-state-adapter` |
| parent / previous candidate | `71ac13a534c52a71600363916bd4a29ca5f600f9` | `8c025aa1eb04e4aea1c429677e2ef50f1a089924` |
| author_principal | claude | claude |
| review_state | NOT_REVIEWED | NOT_REVIEWED |
| ci_state | PASS — run 35785800257, https://github.com/crooksldn-pixel/clive/actions/runs/35785800257, 21:18:16Z to 21:22:24Z, all five gates | no CI on that repository |
| local evidence | provenance full at the SHA, clean tree: ruff pass; control plane 44; product memory pass; offline full 3047 passed, 8 skipped, 2 deselected; secret scan no leaks; eligible true, accepted false | vitest 44 passed (13 in the adapter suite, one new); tsc clean; build clean; Playwright 16 of 16 against the fixture regenerated from the real route at 84e12e77 |

## Purpose

Two defects named by the independent review of the projection:

1. **UNKNOWN counted as online.** `totals.online` was every status except OFFLINE. UNKNOWN means CLIVE could not establish presence. Now `online` = presence established = every status except OFFLINE and UNKNOWN; UNKNOWN counts under `unknown` only.
2. **Process start time exposed as `last_heartbeat`.** The worktree probe reported the agent process's start time as a heartbeat; the bridge probe reported the watcher's last-run timestamp as one. Neither beats. The start time is now `process_started_at`, its own field, labelled presence evidence; the last-run timestamp remains `last_event_at` only. `last_heartbeat` is null on every record until an authoritative heartbeat exists (the producer layer will write those).

The read-only rule is untouched on both sides: the projection still only reads /proc, mtimes, git and `systemctl show`; the route is unchanged; the adapter still only polls.

## Diff scope

CLIVE `git diff --stat 71ac13a..84e12e77`: 4 files, 78 insertions, 4 deletions.
- `scripts/agent_state_view.py` (+15/−4): `Probe.process_started_at`; worktree probe sets it instead of `last_heartbeat`; bridge probe no longer sets `last_heartbeat`; record carries `process_started_at`; `totals.online` excludes UNKNOWN.
- `docs/AGENT_ENVIRONMENT_STATE_VIEW.md` (+11): the field, what a heartbeat is not, what online counts.
- `tests/test_agent_state_view.py` (+55): a live agent reports its start time and no heartbeat; the bridge's last run is an event and no heartbeat; an UNKNOWN worker is not online; online counts an idle live process and not an absent one; the required-fields list gains `process_started_at`.
- `tests/test_environment_route.py` (+1): required field.

AGENT-ENVIRONMENT `git diff --stat 8c025aa..119bb9b`: 6 files.
- `src/adapters/clive/stateView.ts`: `process_started_at` on the feed type; `processStartedAt` mapped; nothing derived from anything else.
- `src/state/types.ts`: `processStartedAt`, and the heartbeat field documented as authoritative-only.
- `src/ui/views/workerProfile.ts`: the Heartbeat row says "None — CLIVE has no heartbeat for this worker"; a new "Process started" row shows the start time "· presence, not liveness".
- `src/adapters/clive/stateViewAdapter.test.ts`: one test for the mapping and the non-derivation; the synthetic view's online rule mirrors CLIVE's corrected one.
- `src/adapters/clive/fixtures/state-view.container.json`: regenerated from the real route at 84e12e77 (online 0, unknown 1, declared 3; heartbeat null; start time null for three workers with no process).
- `README.md`: one clause.

## Reviewer checklist

1. Both SHAs resolve; parents as stated; trees clean.
2. `grep -n "last_heartbeat" crooks-assistant/scripts/agent_state_view.py` → only the dataclass field and the record key remain; no assignment from a start time or a run timestamp.
3. In crooks-assistant: `python -m pytest tests/test_agent_state_view.py tests/test_environment_route.py -q` → 27 passed; `python scripts/agent_state_view.py --json` → `last_heartbeat: null` on every worker and `totals.online` not counting UNKNOWN.
4. In AGENT-ENVIRONMENT: `npx vitest run` → 44 passed; open a worker profile and read the two rows.
5. Decide the judgement calls below.

## Known risks and judgement calls to challenge

1. **What counts as present.** STALE (a live process that has written nothing for over the stale window) and BLOCKED (an active unit whose last run failed) still count as online: presence is established even though no work is. Challenge if you want online to mean working-or-idle only; `working`, `idle`, `stale` and `blocked` are all reported separately either way.
2. **Bridge start time.** The bridge probe does not read the unit's MainPID start time, so `process_started_at` is null for the bridge worker. Adding it means reading `/proc/<MainPID>/stat`; left out to keep this narrow.
3. **Heartbeat is now always null** from both probes. The field stays in the schema on purpose: the producer layer (next mandate) is what will write authoritative heartbeats, and the projection will report those and nothing else.
4. **Open findings not in this candidate**, by the "narrow" instruction: bridge IDLE asserted when the cgroup file is unreadable (should be UNKNOWN); BLOCKED over-read for any non-`ok` token and the fixture's `fail` versus the watcher's `failed`; the STALE reason printing whole hours; the linked-worktree `.git` file not excluded from the mtime scan.

## After acceptance

Nothing deploys. The kernel producer package (next mandate) stacks on 84e12e77 and 119bb9b.
