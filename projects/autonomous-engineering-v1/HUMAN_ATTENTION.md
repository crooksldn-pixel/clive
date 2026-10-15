# Human-attention contract

## Objective

George directs engineering. He does not operate the agents. DEC-079 ruling 9 ends the blanket
per-filing hold in principle. DEC-018 keeps him the author of what is built.

## Three audiences

| Audience | Who | Gets |
|---|---|---|
| **The loop** (worker-01, durable) | The dispatcher | Every mechanical failure inside bounds: failing tests, red CI, reviewer findings (fed to the repair: DEC-068), worker crashes, transient outages, plan-limit pauses, refreshes |
| **The supervisor** | A Claude Desktop session he starts, running on worker-01 as a non-root, read-only user (O-2). **It is not durable**, and starting one costs his minutes, which OAMAB counts | Engineering stops past the loop's bounds: repair limit, refresh cap, scope, environment or base, workspace, and dependents waiting on a stopped member. See the limits below. Builds shows "N waiting for the Director, oldest X h" |
| **George** | The owner | Owner classes, plan cards, and held drafts, batched |

## What the supervisor may do after a repair limit (the Director's correction, adopted)

**It may:**
- read the stop report (DEC-068) and judge each finding: valid, false, or verifier defect;
- record that judgment (`clive-eng judge`);
- draft a re-file, a narrower split or a fix, through CLIVE's draft channel;
- **once the ruling-9 model is built**, have a draft inside the approved scope file without a tap.
  Anything wider becomes a card for George.

**It never:**
- dismisses a finding (only a new commit that passes review does);
- raises repair rounds;
- touches protected paths;
- lands, deploys or re-pins;
- writes to the inbox.

## Owner interruption classes, bound to code

A builder that returns `owner_decision_required` must name one class (PR 6). A supervisor that
escalates must name one too. Anything without a class is not an owner question.

| Class | Meaning |
|---|---|
| PRODUCT_DECISION | Two materially different valid outcomes |
| PERMISSION_CHANGE | Changes who or what may read, write or approve |
| SECURITY_DECISION | A genuine security trade-off |
| IRREVERSIBLE_OPERATION | A migration or destructive action outside the approved plan |
| CREDENTIAL_REQUIRED | A key or connection he controls |
| REQUIREMENT_AMBIGUITY | The outcome cannot be inferred from the repository and current truth. The supervisor tries first |
| EXTERNAL_BLOCKER | A third party's approval or outage |
| REPAIR_LIMIT_REACHED | The loop's review limit. A card with "Try again" recommended: one confirmed answer files the same build as `<id>-N` (DEC-079; DEC-082 builds it). The supervisor may also have triaged and drafted it already |

### Under ruling 9's model (FILING_AUTHORITY), these also reach him
- **A plan card:** one per build objective, or per change to its plan.
- **A held draft:** new scope, new paths or criteria, more repair rounds, beyond the bounds, or
  ambiguous.
- **"Allow the change":** an owner-gate stop that needs wider paths. It shows the exact delta.

**Not owner interruptions:**
- a failing test, red CI or reviewer findings;
- a crashed worker;
- a needed refresh;
- a plan-limit pause;
- a red base (Director work);
- a retry or split inside an authorised plan, once the model is built.

## What changes for George, concretely

| Today | V1 |
|---|---|
| Every filing waits for its own hold | One plan card per build objective. Retries, splits and dependency-ordered items inside it file without a tap, within bounds, each recorded and shown. "Stop filing for this" revokes the plan (PRs 7, 8; O-1) |
| "Try again" is recorded and nothing acts on it | His confirmed "Try again" files that build again (DEC-082, the Director's) |
| An owner gate is a dead end | "Allow the change" shows the exact path delta; his hold files it and widens that item (PR 8) |
| 49% of requests were hand-written re-files | The preflight (PR 3) catches environment, base, toolchain and scope before filing. The supervisor triages and drafts the rest |
| Status means reading branch names and SHAs | One row per build objective; Needs you only for owner items; details behind a tap (PR 9) |

## Batching

- **Builds' Needs you is the batch.** Each item is one card.
- **In a supervisor session,** `clive-eng decisions` prints every open owner question as one numbered
  list with a recommendation each. That is the format behind DEC-071's 43 rulings in about 9
  minutes.
- **A held item pauses only its own dependents.**
- **No new notification channel.** CLIVE's home "what needs him" row is the channel.

## Every owner gesture V1 asks for

See IMPLEMENTATION_PLAN, "Owner gestures, complete":

- **Decisions:** O-1 and O-2, then O-3 later.
- **The A1 audit.**
- **Two Termius re-pins:** RP1 (with stopping the production-host loop) and RP2.
- **Two deploys:** D1 and D2, with the private URL set at D2.
- **Holds:** the filing holds until PR 8; the first plan cards.
- **The F1 run.**
- **The ladder's unit edits.**
- **The X7 reboot drill.**
- **Reading the reports.**

## Progressive disclosure

| Level | Shows |
|---|---|
| Default | Build objective name, plain state, "x of n on the trunk", needs-you |
| One tap | Each member's road, why it waits, and the untapped filings with the rule that allowed each |
| Two taps | Tries, the reviewer's findings (over the private channel), check output, CI run, candidate SHA |
| Never on the face | Worker ids, attempt ids, raw logs, token usage |

## Measures

- Owner interruptions per build objective, by class.
- Holds per accepted build.
- Untapped filings per plan.
- Director-queue age.
- Owner minutes (BASELINE_PLAN).

**Target, as a hypothesis until measured:** no owner interruption for a mechanical cause, and one
hold per plan.
