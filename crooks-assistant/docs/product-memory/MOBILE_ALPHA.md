# CLIVE Mobile Alpha (2026-09-23)

Private, read-only alpha of the phone surface. Built on the v05 line (d9621337) with Support
Investigator V1 (2dbb97bc) ported in file-for-file and a first General Objective (V0).

## What is on the phone

- **Conversation first.** The orb (hold to speak) and an "Ask CLIVE…" box at the thumb. Every
  message goes through the existing `/turn`.
- **What CLIVE is keeping alive.** One card per live objective: status, days left, what needs the
  owner or what it is waiting for, and what happens next. Tapping opens the full record: questions
  to answer in place, work items (with Approve for anything that needs the owner), blockers,
  unknowns, facts with their sources, a "Continue" box, history and "Mark done".
- **Crooks support.** Paste a customer's message, get the Support Investigator's read-only answer:
  who and which order, what happened, verified / likely / unknown, the owner's decisions and a
  reply draft to copy. Nothing is sent or changed. A missing source (store or inbox) is said
  plainly at the top, with the setup detail folded away.

No dashboard, no debug controls. Tablet is compatibility only.

## Objective V0

`app/objectives/store.py`: one JSON file per objective under `settings.objectives_dir`
(`CROOKS_OBJECTIVES_DIR`, default `.state/objectives`), written atomically. Record: id, title,
original request, created/updated, deadline, status, work items, facts with provenance, unknowns,
blockers (missing_info / missing_capability / needs_owner / external), owner-attention items and
full history.

Work items climb `proposed → authorised → started → completed → verified`, each distinct:

- only the owner authorises (the phone's Approve button; the model's tool cannot);
- an item that needs the owner cannot start until authorised;
- verified requires evidence;
- only the owner closes an objective.

The model has four local tools (`objective_open/list/show/note`), on the gate's read allow-list
beside the composer's for the same reason: they change only CLIVE's own records, never a
business system.

## Dogfood: son from Ethiopia to the UK for the baptism (13 October)

Three real turns, two of them in fresh sessions after a server restart. CLIVE opened the
objective, recorded the owner's facts, labelled what it knew only generally ("general knowledge,
not verified live"), proposed the passport-then-visa step as needing the owner, recorded that it
has no booking, visa, appointment or route tool (a missing-capability blocker) and asked only what
it could not know. Later turns picked the objective up from "About my son…" and "On the baptism
trip…" without being told which, recorded the answers and resolved the questions they settled.
Nothing was booked, applied for or sent.

## Not in this alpha

Any write to Shopify, Gmail or anywhere else; booking, payment, calendar, maps or web search;
objectives acting on their own between conversations.
