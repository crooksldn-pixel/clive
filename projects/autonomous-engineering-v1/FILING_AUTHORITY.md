# Engineering filing authority (DEC-079 ruling 9): design for George's approval

**Status:** DESIGN. Needs George's approval (decision O-1) before it is built.

**Until it is built, reviewed and deployed, every engineering filing waits for his hold, as today**
(DEC-079). The one exception is already his: a confirmed "Try again" on one build is his hold for
that exact re-file. DEC-082 builds that, and the Director owns it.

## What he asked for (DEC-079, verbatim conditions)

CLIVE may file work **clearly within an engineering intention or scope he has already
authorised**, without a tap for each child request. These still come to him:

- genuinely new scope;
- expanded authority;
- consequential ambiguity;
- protected changes;
- other owner-level decisions.

This is not unrestricted autonomous engineering, and it does not waive DEC-018.

### The boundary DEC-079 records under DEC-018

**Authorised scope** is a request, or a plan or set of requests he saw and approved together,
with their allowed paths and acceptance criteria.

| Inside authorised scope: may file without a tap | Held by DEC-018: never automatic |
|---|---|
| Retries | Automatic decomposition into work he has not seen |
| Repairs | Proactive filing |
| Splits | Policy that adjusts itself |
| Dependency-ordered requests | |

## Where authorised scope lives: CLIVE's `Objective(kind=build)`

No new store is needed. The Project *is* the build objective (`app/objectives/store.py`). It already
has:

- the owner's words, `purpose` and `done_when`;
- `engineering[]`, the linked requests (`link_engineering`, called by `submit_engineering_request`
  with an `objective_id`);
- typed blockers, attention and history;
- work items on the ladder proposed → authorised → started → completed → verified, where
  **`authorised` can only be set by the owner from his own screen** (`authorise`, `store.py:1556-1578`).

**What is added** (PR 7):

- **A plan item's request spec.** Each planned request is a work item. Its spec is kept in the
  objective's rollback-safe design file (`design/obj_x.json`, the existing sidecar pattern): a
  reserved request id, title, allowed paths (areas), acceptance criteria, `depends_on` among the
  plan's items, and its repair rounds.
- **One hold authorises the whole plan.** A **plan card** shows every item: its title, areas,
  criteria and order. His single hold authorises all of them together. The judgment is recorded with
  its `judgment_id` and a digest of exactly what he saw.
- **Changing an authorised plan** (a new item, wider areas, a new criterion) is a new plan card and
  a new hold.
- **A single request he files with his hold, for a build objective,** is recorded by PR 7 as an
  authorised one-item scope of that objective: his hold is the authorisation. Retries and splits of
  it then fall under the rules below. **A request filed with no objective has no recorded scope**, so
  every draft for it is held.
- **Where the record lives, and how it is checked.** It is kept in the objective's design file, which
  unprotected code writes. `filing_decision` therefore **never trusts it alone**. It verifies the
  plan's `judgment_id` and digest against the **judgment ledger**, which is protected
  (`app/actions/judgment_ledger.py`) and written only by his gestures. A mismatch means HOLD.

## The decision: one deterministic function on the filing path

All filers go through `submit_engineering_request`:

- CLIVE chat;
- research "Approve the work";
- DEC-082's "Try again";
- the supervisor's drafts;
- the set filing of an authorised plan.

That path runs PR 3's preflight, then `filing_decision(draft, objective)`. The function lives in the
shared engineering library, on a protected path.

### A filing that already carries his gesture is never held again
A filing comes with a recorded owner judgment for exactly this draft:
- his hold on its card;
- his confirmed "Try again" (DEC-079 / DEC-082);
- his hold on "Allow the change";
- his hold on a plan card, for that plan's items.

Such a filing is **FILE**, subject only to REFUSE and the preflight. It is **never held a second
time**, and it **never counts against the untapped bounds** below. The bounds apply only to filings
made *without* a gesture of his.

### FILE (no tap) only when all of these hold
- The objective is `kind=build` and its plan is **authorised** by his hold, not revoked, and not
  closed.
- The draft is one of:
  - **an authorised item**, exactly as authorised;
  - **a retry** of an item: `<id>-N` with `supersedes`, the same title, allowed paths equal or
    narrower, the same criteria. Repair rounds are never raised;
  - **a split** of an item into parts:
    - each part's paths lie inside the item's paths;
    - each of the item's criteria appears in exactly one part, and there are no new criteria;
    - one level deep;
    - the parts are ordered by `depends_on`;
  - **a dependency-ordered filing** of authorised items, with `depends_on` naming only items of the
    same plan.
- No protected path is involved; the preflight passes; the draft comes from an authenticated filer.
- **Bounds hold (proposed; part of his approval):**
  - at most **2** untapped retries per item;
  - splits **one level** deep;
  - at most **4** untapped filings per item in total.

  Beyond them, the draft is held. The bounds never change themselves.

### HOLD (a card in Needs you, batched) for everything else
- New paths, new criteria, new items, or more repair rounds.
- A scope stop whose fix needs wider paths: "Allow the change" (below).
- Anything the preflight marks ambiguous.
- Any objective that is not authorised.
- Drafts beyond the bounds.

### REFUSE (with a reason)
- A protected path: "Director work".
- Customer details or secrets.
- A red trunk head: "Director work first".
- A malformed draft.

### Outside text never triggers a filing (in line with DEC-080)
The function compares structured fields only: ids, path sets and criteria strings, by exact equality
or subset. Text from a builder report, a reviewer finding, a research document or a supervisor's
prose can inform a draft. It can never widen a scope, or make a held filing file.

### Every untapped filing is visible
- Each one is recorded in the objective's history, with the rule that allowed it: `item`, `retry`,
  `split` or `dependency`.
- Builds shows it under the project.
- **"Stop filing for this"** on the project revokes the authorisation in one tap. From then on, every
  draft is held.

## "Allow the change": an owner-gate stop that needs wider scope

When a builder stops because the work needs paths outside its scope:

- The card shows the **exact path delta**, read from the stop report over the private channel (paths
  only, never the builder's words on GitHub). It needs `CROOKS_ENGINEERING_PRIVATE_URL`, which DEC-068
  already provides for, set at a deploy.
- **His hold does two things:** it files the re-file with those paths, and it widens that item's
  authorised spec, so later retries of it stay inside scope.

## The supervisor's drafts

The supervisor never pushes to the inbox. It submits structured drafts to CLIVE:

- **The channel:** `POST /engineering/drafts`, tailnet only. CLIVE accepts it only from the
  supervisor's identity (decision O-2).
- **The body:** `{objective_id, kind: retry|split|item|dependency, request spec,
  finding_dispositions: [{finding_id, disposition: valid|false|verifier_defect}]}`.
- **No finding text is ever written to GitHub.** Re-files carry finding ids and dispositions only.
  The loop's `earlier_try` gives the next builder the full stop report privately (DEC-068).
- **A disposition never dismisses a finding.** Only a new commit that passes review does.
- **The response** is FILE, HOLD (a card was made) or REFUSE.

## Inbox housekeeping (archive)

CLIVE's bridge is the only filer holding inbox write. When inbox headroom falls below 30, it moves
receipted, **terminal** requests older than 7 days from `requests/` to `archive/`.

- It never moves an unreceipted or non-terminal request.
- Ids are never reused (PR 2).
- The loop lists only `requests/` and never sees `archive/`.

**This is a write by CLIVE that files nothing, so it is part of what he approves here.** Until he
approves it, the Director archives once by hand after D1.

## Credentials this needs

- **Reading Actions runs.** While the repository is public, GitHub serves workflow-run reads for
  public repositories to any token, so this likely needs no new permission; this is to be verified at
  PR 3. **Actions: read on the production filer's token is needed only if the repository goes
  private.** Without it, the preflight files on the head and says "trunk state unknown".
- **A credential for the supervisor's draft channel** (O-2).

## What it never does
- Decompose an intention into work he has not seen (DEC-018).
- File proactively: every draft has a trigger, which is a stop, an authorised plan, or his request.
- Adjust its own bounds.
- File protected changes.
- Raise repair rounds.
- Land or deploy.

## What George approves (decision O-1)

1. The model as a whole: plan cards on build objectives, and the FILE / HOLD / REFUSE rules above.
2. The bounds: 2 untapped retries per item, splits one level deep, 4 untapped filings per item.
3. Archive housekeeping by CLIVE's bridge.
4. Actions read on the production filer's token, if the repository goes private.

The supervisor's identity and its draft channel are decided separately (O-2).
