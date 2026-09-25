# Customer Support Investigator V1

Status: **SHIPPED (read-only)** as of 2026-09-25.
- Revision 5 (`2dbb97bc`) closed S-01, S-01R and S-01C and was accepted COMPLETE in the kernel on 2026-09-23.
- The revisions are in production `clive/trunk` `ce791d03`, deployed 2026-09-25.
- It is on the phone through the mobile alpha.
- Still open: the owner's live verification of the two real cases and the dogfood week.

History: "TESTING (built 2026-09-23 as task `support-investigator-v1`, revision 2, through the frozen repository-only lifecycle kernel; awaiting independent exact-SHA review and the owner's verification of the real cases)."

Owner objective (2026-09-23): given one customer enquiry about an existing order, CLIVE must understand what is asked, identify the correct customer and order where the evidence supports it, gather the order and conversation context, produce an internal "what happened" summary that separates verified facts from reasonable inference from the unknown, expose the evidence so the owner can check it, and draft a concise customer reply that requires the owner's explicit approval before anything external happens.

## What V1 is, and is not

V1 is **read-only**. It cannot send an email or an SMS, refund, cancel or alter an order, alter a fulfilment or tracking, add or edit a Shopify note, or make any other external business write. No write authority is implied by the objective, and none is taken: the package (`crooks-assistant/app/support/`) imports only the GREEN and AMBER read tools, holds no client of its own, and the command-line entry point engages the process-wide one-way read-only latch (`app/readonly.py`) before it builds a client. The reply draft is text for the owner. Sending it is a separate act, by the owner, outside this tool.

V1 is deterministic. No model is in the loop: the kind of enquiry is read from a bounded phrase list, identification follows fixed rules, every statement is built from fields the source systems returned, and the draft is assembled from those statements and quoted policy lines. A reading the owner cannot check against a source is not an investigation, so nothing here guesses.

## The pipeline

1. **Enquiry** (`app/support/enquiry.py`). The customer's message, subject and sender address, bounded. The kind (`cancel`, `change_address`, `damaged`, `wrong_item`, `missing_item`, `return_exchange`, `delivery`, `other`) is the first whose phrases appear, in that precedence. Identifiers are the ones the application already trusts: order-shaped numbers (`app/context/graph.py::order_numbers_in`), with a phone-number group or a year inside a date excluded and a number the text calls an order first, and email addresses other than the sender's. The asks are the customer's own words above any quoted reply (what they quoted of their own earlier message counts; what they quoted of ours does not), questions first.
2. **Evidence bundle** (`app/support/evidence.py`). Everything read, with where it came from and when: the order search and its result, the hydrated order (items, fulfilments, tracking, note, tags, refunds, customer history), up to three inbox threads from the customer's address or naming the order (bounded to six messages of 1,500 characters each), and the named knowledge-base lines the reply may quote, verbatim from `kb/shipping-policy.md` and `kb/cs-rules.md`. Every reader failure is a named problem, never a silent gap. The bundle is JSON (`clive.support_evidence_bundle.v1`); gathered live or loaded from a capture, the investigation cannot tell the difference.
3. **Identification** (`app/support/investigate.py::identify`). Exactly one order is chosen only when the evidence supports it: the order the customer named, or the single recent order under their address. Confidence is `confident` when the enquiry came from the address on the order, otherwise `possible`, and the reasons are listed. Two candidates and no number is `ambiguous`; an unknown number is `not_found`; no number and no address is `no_identifier`; a store that did not answer is `unavailable`. Nothing is guessed between two.
4. **Facts, inference, unknowns** (`app/support/investigate.py`). A fact is a field a source returned, cited by its evidence reference: the order, each fulfilment as recorded (never called "dispatched"), the return status, the Shopify events, the customer's history, each thread. An inference is a conclusion from facts and policy, and says so: a fulfilment whose status is a label without a carrier scan (`CONFIRMED`) may not have been collected; a `DELIVERED` fulfilment is answered from the delivery scan; a return already open on the order (`IN_PROGRESS`) is recognised rather than restarted; lateness against the published delivery windows; a first fulfilment later than the published dispatch rule; an order not dispatched within it; a cancellation; a customer waiting on us, or unanswered beyond the published reply time (a system email matched only by the order number is evidence, not the customer waiting). An unknown is a question the evidence cannot answer, named rather than papered over: where the parcel is now (no carrier tracking is integrated), whether the confirmation email arrived, what actually turned up. The reference time is the bundle's own `gathered_at`, so a bundle always yields the same investigation.
5. **Reply draft** (`app/support/reply.py`). Built only from verified facts and the published policy, put in the customer's terms for the destination where the line is the known one and quoted verbatim otherwise. Every number, date and tracking reference in the body comes from the bundle; an unknown is answered by asking; the draft apologises when the customer has been kept waiting. A draft may state a verified fact, state uncertainty, say what still needs doing, ask for what is needed, or make a policy-backed statement; it never says an internal action has begun or been completed unless the bundle proves it (review finding S-01 on packet 15). The draft carries `requires_owner_approval: true`, what it was based on, what was deliberately not said, and `external_effects: none`.
6. **Internal summary** (`app/support/report.py`). Markdown for the owner: the enquiry, the identification and its reasons, what happened, the three lists with their evidence references, the evidence table, the decisions only the owner can make, and the draft.

Entry points: `POST /support/investigate` (`app/routes/support.py`; the tailnet allow-list middleware decides who may call it; a `bundle` in the body replays a capture without reading anything) and `python scripts/support_investigate.py` (live, with `--capture` and `--redacted-capture`; or `--bundle` to replay).

## Evidence references

`shopify:order_search:<query>`, `shopify:order:<order_id>` (and `#history`), `gmail:search`, `gmail:thread:<thread_id>`, `kb:<policy line name>`, `enquiry`. Every fact and inference cites at least one; the summary's evidence table lists them all with a one-line summary each, so a conclusion can be checked against the source system in one step.

## Privacy

The minimum customer information is read, and only from systems the owner already operates. Raw customer data does not enter product-memory documents, review packets, commits, fixtures or test snapshots: the automated tests use invented people at `.invalid` addresses (`tests/fixtures/support/`), and the real acceptance case is captured to the owner's machine only. `app/support/redact.py` produces the copy an engineering record may hold: names, addresses, phone numbers, message bodies, the internal note and tracking references (masked to their last four characters) are removed, with email addresses replaced consistently so the identification still holds in the redacted copy.

## Capability gaps recorded

- **Carrier tracking scans** are not available: Easyship is not integrated (`app/shipping/`), so the parcel's whereabouts is always an unknown, and the draft says the tracking reference rather than a location.
- **Credentials in the engineering container**: the builder's container holds no Shopify or Gmail credential, so the live path (`app/support/live.py`) was exercised against fakes and its "unavailable" branch; the live run is on the owner's Mac.
- **No model**: drafting is deterministic. A worded, more natural draft would be a later revision, and would still be bound to the same evidence.

## Acceptance

- `tests/test_support_investigator.py`: the kinds, the identifiers, every identification status, facts/inference/unknown separation, the no-invention rule (every order- or tracking-shaped token in a draft appears in the bundle), each kind of draft, the summary, the bundle round trip, redaction, the live adapters against a fake store (reads only, no mutation), the route and the CLI, and a static check that nothing in the package names a write tool.
- Real Crooks cases (the criterion is at least one; two were captured read-only, a delivery enquiry on a label-only international fulfilment and a return enquiry on an order with an open return) replayed through the same code; the owner verifies that the correct order was identified, the factual account matches the evidence, no detail was invented, the uncertainty is explicit, the reply answers the question and needs no more than minor editing. The engineering record holds the redacted copies only.

## Not in V1 (backlog unless a material blocker)

Sending or drafting into the mailbox; any order, fulfilment, tracking or note change; carrier tracking; a model-written draft; multi-enquiry triage; customer identification by name alone; anything outside the last sixty days of orders without the `read_all_orders` scope.
