# Target architecture

## Principle

Add the missing control layers around CLIVE's engineering kernel. Do not replace the kernel. Every new
piece names the component it extends.

This design reconciles four independent passes with the source: the planning lead, the
autonomy-architect, the adversarial and final reviewers, and the CLIVE Director's cross-check of
15 Oct. Where they differed, the source decided ([PLAN_REVIEW.md](PLAN_REVIEW.md)).

**The decisions that bound it:**

- **DEC-018 in force:** no automatic decomposition, no proactive filing, no self-adjusting policy.
- **DEC-079:** ruling 4, parallel engineering as an engineering setting; ruling 9, a narrower
  filing-authority model.
- **DEC-064:** landing.
- **DEC-072:** deploy.

## Control flow (V1)

```
George ─ intent ─► CLIVE (production)
   ├─ chat / research "Approve the work" ─┐
   ├─ plan card on a build objective (one hold authorises the set: PR 7)
   ├─ "Try again" (his confirmed answer: DEC-082) / "Allow the change" (his hold: PR 8)
   │                                       ▼
   │        submit_engineering_request ─► preflight (PR 3: base, scope, toolchain, ids)
   │                                    ─► filing_decision (PR 8: FILE / HOLD → card / REFUSE)
   │                                    ─► create-only write ─► clive/control/worker-01-inbox
   ▲                                       ▲  (archive/ housekeeping, PR 2 + PR 8)
Supervisor = Claude Desktop (Mac) → worker-01 as a non-root, read-only user (O-2)
   reads public status + stop reports · clive-eng status/triage/judge/decisions/deploy-brief
   clive-eng draft ─► POST /engineering/drafts (tailnet, supervisor identity) ─────┘   (never pushes)
                                           ▼  from here nothing on the Desktop, SSH or the supervisor is needed
worker-01 loop (existing; durable; RP1 brings DEC-068 + DEC-076 into force)
   poll → preflight → base wait → DEPENDENCY WAIT (PR 4) → claim → links/<id>.json → objective on a green
          head containing its predecessors → intake (+ predecessor_task_ids) → receipt
   tick: FIFO (5a); --max-concurrent counts builders AND reviews (5b); plan-limit pause (5b); land:false (5c)
        → build (fresh session; findings + earlier stop report fed in: DEC-068; skills by path: PR 6)
        → sandbox checks → candidate → exact-SHA acceptance.yml → Claude reviewer (DEC-076)
        → bounded repair → accept → integrate → land (DEC-064)
   publish status.json: + loop{} (self-description, host load), waiting_on, stop_cause, owner_class (PR 6)
CLIVE production: Builds — one row per build objective (PR 9; items advance from loop records: DEC-082)
   Needs you = owner classes + plan cards + held drafts · Deploy (DEC-072, his) · trunk ≠ deployed
```

## What is new, and what it extends

| New | Extends | Why extension alone was not enough | PR |
|---|---|---|---|
| Archive-safe ids and readers; `archive` / `unarchive` | `_free_id`, `github.py`, `builds/read.py` | The inbox stops all intake above 100 files. Archiving is safe only if ids are never reused (`controller.py:245-249`) | 2 (roll-forward only) |
| **The preflight** inside `submit_engineering_request`, plus `config/worker_profile.json` | `build_request`, `default_checks`, `PROTECTED_PATHS`, `github_acceptance` | Environment or base (9), CI or checks red (9) and scope (8) blocks are found late. Every filer passes here | 3 |
| Three optional request fields; dependency wait; `links/` sidecar; `predecessor_task_ids` filled | `RemoteObjectiveRequest`, `waits.py`, adapter-root records, the unused kernel field | A dependent's base must contain its predecessors. Kernel records cannot grow without breaking rollback | 4 |
| FIFO and the clone fix; one knob for builders and reviews; the plan-limit pause; `land: false` without a landing proof | `tick()`, `workspaces.py`, `_live_count`, `_dispatch_review`, `Activity.rate_limited`, the `--no-land` integration path | The order is alphabetical; EXDEV; reviews uncounted; plan limits burn retries; a landing proof written at integration lets any pin land the work | 5a, 5b, 5c |
| `loop{}` self-description with host load; `stop_cause`; `owner_class`; `applies_to` routing; protected paths named in advance | `status.py`, `STOP_CAUSES`, `WORKER_REPORT_SCHEMA`, `_skills_for`, `PROTECTED_PATHS` | Configuration and load are unknowable from outside; prose causes; owner gates without a class; every builder gets every skill | 6 |
| **Authorised plans** (plan items, plan card, one hold, revoke) | `Objective(kind=build)`, its design file, the item ladder and owner-only `authorise`, Builds cards | Ruling 9 needs a durable record of what he approved together | 7 |
| **`filing_decision`**; the supervisor's draft channel; "Allow the change"; automatic archiving | `submit_engineering_request`, the judgment ledger, the private stops channel, PR 2 | Ruling 9's model; the supervisor files only through CLIVE; owner gates are dead ends | 8 |
| Project rows | `board.py` families and roads; `Objective.engineering[]`; DEC-082's item advancement | The board groups only by `-N` | 9 |
| `clive-eng` | The shared engineering library | The supervisor reads JSON by eye, and nobody triages without George relaying | 10a, 10b |

**Not built here, because others own them or they already exist:**

- **DEC-068 and DEC-076:** built; verified at RP1.
- **DEC-080, DEC-081 and DEC-082:** the Director's.

**Nothing new** is added as a queue, a database, a scheduler process, a project store, a manifest, a
state machine, an MCP server, a dispatcher, a reviewer kind, an owner channel into the kernel, or a
deploy path.

## The Project = CLIVE's `Objective(kind=build)`

**What exists** (`app/objectives/store.py`):

- the owner's words, `purpose` and `done_when`;
- `engineering[]`, linked by `submit_engineering_request(objective_id=…)` through `link_engineering`;
- typed blockers (`missing_info`, `missing_capability`, `needs_owner`, `external`);
- attention and history;
- work items on the ladder proposed → authorised → started → completed → verified, where **only the
  owner's screen can set `authorised`**;
- a rollback-safe design file beside each record.

**What V1 adds:**

- **PR 7:** plan items, kept in the design file with their request specs. **One plan card and one
  hold authorise the set.** Revocation takes one tap.
- **PR 4:** dependency edges in the *request* (`depends_on`). The loop on worker-01 cannot read
  production objectives.

**State is derived for Builds**, never stored (PR 9: `project_view(objective, requests, status)`):

| State | When |
|---|---|
| Queued | — |
| In progress — x of n on the trunk | — |
| Waiting on <member> | — |
| Needs you | Owner classes, plan cards, held drafts |
| Stopped — waiting for the Director (N, oldest X h) | — |
| On the trunk, not live yet | — |
| Live | — |
| Filing stopped | After revocation |

**Each member keeps its road:** Filed → Built (completed, not verified) → Reviewed (verified: green on
the exact SHA and READY) → On the trunk → Live (an owner deploy). DEC-082 advances the items from loop
records, and PR 9 renders them; it does not advance them.

## Dependency semantics (PR 4)

- **When an id is satisfied:** when an admitted request in its `supersedes` closure has a kernel
  integration whose SHA is an ancestor of the trunk head. A squash merge does not count, so the
  Director never squashes a loop candidate.
- **The base:** at admission, the trunk head when it is green and contains every predecessor.
  Otherwise the member keeps waiting.
- **The wait:** the existing deferral (no claim, nothing burned, restart-safe), bounded at 7 days.
- **A blocked predecessor:** its dependents wait with `waiting_on: [X]`, and only the root asks a
  question.
- **Replay chains** (`land: false`): a dependency is satisfied by COMPLETE, and the base is the single
  predecessor's integrated SHA.

## The filing-authority model (ruling 9)

The model is [FILING_AUTHORITY.md](FILING_AUTHORITY.md), for George's approval (O-1).

**FILE without a tap** only inside an authorised plan, for:
- authorised items;
- retries;
- splits that partition an item's criteria inside its paths;
- dependency-ordered items.

Within bounds (2 untapped retries per item, splits one level deep, 4 untapped filings per item), with
no protected path, and from an authenticated filer.

**HOLD** everything else. **REFUSE** protected paths, secrets and a red head.

**It compares structured fields only, so outside text never triggers or widens a filing** (DEC-080).
Every untapped filing is recorded and shown, and "Stop filing for this" revokes the plan.

## Supervisor boundary

**Where it runs (O-2):** Claude Desktop on George's Mac is the client. Commands run on clive-worker-01
as a non-root user that cannot read the loop's token.

**May:**
- read source, product memory, the public status and stop reports;
- research (external text is data);
- draft plans for George to see;
- after a repair limit:
  - read the stop report;
  - judge each finding as valid, false, or a verifier defect;
  - record that judgment;
  - draft a re-file;
- submit drafts **only** through CLIVE's draft channel, where `filing_decision` applies;
- explain evidence;
- write the deploy brief.

**Must not:**
- push to any branch: inbox, trunk, objective or status;
- dismiss a finding (only a new commit that passes review does);
- raise repair rounds;
- touch protected paths;
- land, deploy or re-pin;
- resume kernel tasks;
- record owner judgments;
- hold any state the loop needs.

`clive-eng`'s code limits are defence in depth. The boundary is the supervisor user's lack of any
GitHub write credential, plus `filing_decision` on CLIVE.

## Durable-worker boundary (unchanged)

The dispatcher on worker-01 owns attempts, workspaces, sessions, checks, review dispatch, repairs,
integration and landing (DEC-064). Once work is filed, Desktop, SSH and the supervisor are
operationally irrelevant.

## Authority

| Act | Authority |
|---|---|
| File a request (today, and until PR 8) | His hold on its card. A confirmed "Try again" is his hold for that exact re-file (DEC-079) |
| File inside an authorised plan (after PR 8) | The plan card he held, within FILING_AUTHORITY's rules and bounds |
| Anything wider: new scope, new paths or criteria, more repair rounds, protected, ambiguous | His hold on a card. Protected work is Director work |
| Land on `clive/trunk` | The loop under DEC-064's four conditions. Never protected paths; never `land: false` |
| Change loop code | A Director PR; an independent review at the exact SHA; a non-author merge; `root-repin.sh`; his re-pin |
| Change production code | A PR; an independent review at the exact SHA; a non-author merge; his deploy (DEC-072) |
| Concurrency | An engineering setting by measurement (ruling 4), applied at his re-pin or unit edit |
| Deploy | His hold and passkey, or his hand deploy. Never automatic; never implied by "on the trunk" |
