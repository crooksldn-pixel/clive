# Agent Environment — CLIVE state feed

A contract for the smallest honest thing CLIVE can show the Agent Environment.

The Agent Environment is a projection. It renders CLIVE state; it never asserts
it. If this feed says a worker is OFFLINE, the environment shows it offline — it
does not animate a placeholder, infer from a branch name, or fill a gap with
something plausible. Motion is not evidence. The purpose of the whole surface is
that nobody — ChatGPT, Claude or the owner — can claim workers are operating
without something observable behind the claim.

## Producing it

    python crooks-assistant/scripts/agent_state_view.py --json

Read-only: it reads `/proc`, file mtimes, `systemctl show` and `git rev-parse`,
and writes nothing. Safe to poll. Exit status is `0` even when every worker is
offline, because "nothing is running" is a successful observation, not an error.

It reads its roster from `crooks-assistant/config/agent_roster.json`. Listing a
worker there is a *declaration*, not evidence: each entry is probed against the
live system on every call, and an entry with nothing behind it reports OFFLINE.
That asymmetry is the design — the roster can only ever cause a worker to be
checked, never to appear.

## Shape

`schema: clive.agent_environment_view.v1`

Top level: `generated_at`, `host`, `fresh_window_s`, `stale_window_s`,
`workers[]`, `totals{}`.

Each worker carries exactly the fields the owner asked for — `worker_id`,
`display_name`, `role`, `status`, `current_task`, `project`, `branch`,
`head_sha`, `last_heartbeat`, `last_event`, `last_event_at`, `blocker`,
`owner_gate` — plus two that exist to make the verdict auditable:

- `status_reason` — one sentence naming the evidence the status rests on.
- `evidence[]` — the raw observations (PIDs, CPU seconds, write ages, unit
  state). Render it behind a disclosure; it is what makes a wrong status
  arguable rather than mysterious.
- `process_started_at` — when the worker's process started, if one was found.
  This is presence evidence and is reported under its own name on purpose.

`last_heartbeat` is `null` until an authoritative heartbeat exists for the
worker. A process start time is not a heartbeat (nothing beats), and the
watcher's last-run timestamp is when a run completed (`last_event_at`), not
liveness; neither is ever reported as one.

`totals.online` counts the workers whose presence was established: every
status except `OFFLINE` and `UNKNOWN`. An `UNKNOWN` worker is one CLIVE could
not observe; it is counted in `totals.unknown` only, never as online.

## Status vocabulary

| Status | Means | Requires |
| --- | --- | --- |
| `OFFLINE` | no worker process exists | probe found no agent process |
| `IDLE` | the worker exists and holds no task | process alive, no recent write |
| `BUILDING` | a task is executing | process alive **and** a write inside `fresh_window_s` |
| `REVIEWING` | as BUILDING, worker's role is reviewer | same, plus `role: reviewer` |
| `BLOCKED` | a deterministic blocker was recorded | a recorded failure or blocker |
| `OWNER_GATE` | a genuine owner decision is required | an explicit gate record |
| `STALE` | a task is held open but nothing has moved | process alive, last write older than `stale_window_s` |
| `UNKNOWN` | the probe could not settle it | always accompanied by a reason |
| `ASSIGNED` | the kernel recorded an assignment the worker has not acknowledged | an attempt record, no `acknowledged` event |
| `COMPLETE` | the task reached DONE with every record present | acceptance and verified integration records that agree, within one stale window |

There is deliberately no value meaning "probably fine".

The load-bearing rule is that **liveness alone never yields BUILDING**. A
process can be alive and idle at a prompt for thirty hours; a systemd unit can
report `active (running)` for days having dispatched nothing. Both were true on
this host when this feed was written, and both had been read as progress. So
`BUILDING` additionally requires a write newer than `fresh_window_s`, and the
same live process degrades through `IDLE` to `STALE` as its evidence ages.

`UNKNOWN` and `OFFLINE` are kept apart on purpose: "I looked and there is
nothing" and "I could not look" are different claims and should not collapse.

## Records first, probes reconcile

When the roster declares `engineering_store` (the kernel's `engineering/`
directory, see ENGINEERING_LIFECYCLE_PRODUCERS.md in product memory), the
records decide a worker's status before any probe does: a current assignment
reads ASSIGNED, BUILDING while its lease is alive, STALE once the lease has
expired without a heartbeat, IDLE while its candidate is under review, accepted
or rejected, and BLOCKED or OWNER_GATE from the record; a principal with an open
review dispatch reads REVIEWING; a worker whose task reached COMPLETE reads
COMPLETE for one stale window. `last_heartbeat` is then the last heartbeat the
kernel journaled, never anything inferred.

The probes still run. Where they disagree with the record the disagreement is
reported in `reconciliation` and appended to `status_reason`; the status itself
is not changed, because a process table is evidence about a machine and the
record is the claim being reconciled, not the other way round. `status_source`
says which decided: `records`, `records+probe` (a disagreement was noted) or
`probe`. A roster entry may declare `probe.kind: records_only` for a worker
nothing on the host can observe; it is UNKNOWN unless a record places it.

The document also carries `tasks[]`, one entry per task revision the kernel
holds, with its stage, stage reason, attempt, lease, candidate, review
dispatch and verdicts, acceptance, integration and history, and `engineering`:

- `store_root` — the declared store, or `null`.
- `lifecycle` — `KNOWN` when the kernel's records were read, `UNKNOWN` when
  they were not.
- `problem` — `null` when `lifecycle` is `KNOWN`; otherwise one sentence naming
  why the records were not read.
- `task_count` — the number of task records read when `lifecycle` is `KNOWN`;
  `null` when it is `UNKNOWN`. A count of `0` means a store was read and holds
  no tasks, and appears in no other case.

`engineering_store` is optional, and a roster without it is legitimate: every
worker is probed exactly as before, the totals are unchanged and the exit status
is still `0`. But no records were read, so `lifecycle` is `UNKNOWN` and
`problem` starts `no engineering store declared` and says the engineering
lifecycle is unknown. A store that is declared but missing (`declared
engineering store …`) or unreadable (`engineering store unreadable: …`) is
likewise `UNKNOWN` with its named problem — never an empty campus.

The human-readable output prints one line, `Engineering lifecycle unknown:`
followed by the reason, whenever `lifecycle` is `UNKNOWN`; when a store was read
and holds no tasks it says no tasks are recorded instead, so the two never
render the same.

## For the environment's authors

1. Treat this JSON as the only source for agent state. Do not merge it with a
   task list, a branch listing or a status document; those are claims, and
   reconciling them here would reintroduce exactly the confusion this replaces.
2. Show `last_event_at` next to every worker. A status without its timestamp is
   how a 29-hour-old observation passes for a live one.
3. Render `OFFLINE` and `STALE` as prominently as `BUILDING`. The failure mode
   worth catching is a quiet absence, not a busy worker.
4. If `generated_at` is itself old, say so; a stalled feed must not read as a
   stalled-but-known system.

## What it does not do

No dispatch, no scheduling, no aggregation across hosts, and no write path. It
answers one question — what is true on this machine right now, and what the
kernel's records say — and stops there. Writing the records is the kernel's
job (`scripts/engineering_kernel.py`), which runs only when invoked.
