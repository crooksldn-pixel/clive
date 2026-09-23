# EXACT-SHA GPT REVIEW PACKET 15 — Customer Support Investigator V1 (support-investigator-v1 r2)

Generated 2026-09-23 02:34Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. One repository, four commits on top of the landed stream head b68e6e82, product work under the owner's objective of 2026-09-23 (message 10), run through the frozen kernel at 18c3153a as a product task. Nothing here deploys, and the candidate carries no write authority: every path it takes is a read.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `921375628d13ce338c659a7b789c11d8ac2b5f58` |
| branch (head == candidate when written) | `claude/support-investigator-v1-2026-09-23` (target); `claude/support-investigator-v1-2026-09-23-r2` (the r2 workspace branch, same head) |
| base | `b68e6e827afbeba3364c8239a2d814a60372f498` (the landed packet-10 candidate; the CI stream head at the time of writing) |
| lineage | b68e6e82 → e07e9130 (r1 checkpoint) → 3e6ec77f → 9f30dd7a → 92137562; preserved, not rewritten |
| kernel task | `support-investigator-v1` r2, attempt `support-investigator-v1-a2`, fencing token 2, on `clive/engineering-state`; r1 (attempt a1) OBSOLETE, superseded by r2 when the allowed paths gained the generated `docs/phase4/TOOL_MATRIX.md` (the r1 checkpoint failed `tests/test_tool_matrix.py` because the checked-in matrix must equal the generator's output once a new test file names a tool) |
| author_principal | claude |
| review_state | NOT_REVIEWED |
| ci_state | PASS — run 35810435777, https://github.com/crooksldn-pixel/clive/actions/runs/35810435777, 2026-09-23T02:27:37Z to 02:31:47Z, all five gates green at 921375628d13ce338c659a7b789c11d8ac2b5f58 (the earlier r1 checkpoint e07e9130 failed only the tool-matrix test, run 35808803871; 3e6ec77f passed, run 35809745186) |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha 92137562… --suite full` at 2026-09-23T02:32:45Z in the r2 workspace (clean tree, head == candidate), Python 3.12.3, gitleaks 8.30.1: ruff pass; pytest_control_plane pass (44 passed in 0.18s); product_memory_structure pass; pytest_offline_full pass (3090 passed, 8 skipped, 2 deselected in 293.47s (0:04:53)); secret_scan pass (2:32AM INF no leaks found); `eligible_for_acceptance_decision: True`, `accepted: False` (`acc-support-92137562.json`, recorded as this attempt's `acceptance_provenance` evidence) |
| real-case evidence | `evidence-support/real_case_acceptance.json` (sha256 `b258e8fdc65de207813169b7f74a5b4dcf366adb139b056b82d85d025eea45b8`), redacted; recorded as this attempt's `real_case_acceptance` evidence; raw captures stay on the engineering session and are never in the store, a packet or a commit |
| Agent Environment, kernel, watcher, systemd, runtime | untouched |

## Diff scope

`git diff --stat b68e6e82..92137562`: 17 files, 3082 insertions, 1 deletion, all inside the task's allowed paths: `app/support/` (eight new modules), `app/routes/support.py` (new), `app/main.py` (+2: the router import and `include_router`), `scripts/support_investigate.py` (new), `tests/test_support_investigator.py` (new, 53 tests), `tests/fixtures/support/orders.json` and `threads.json` (new, synthetic), `docs/product-memory/SUPPORT_INVESTIGATOR_V1.md` (new) and `README.md` (+1 index line), `docs/phase4/TOOL_MATRIX.md` (one regenerated line: the new test file on the `shopify_find_order` row). `git diff b68e6e82 92137562 -- app/tools app/clients app/actions app/families app/orchestrator scripts/engineering_kernel.py` is empty.

## What the candidate does

One customer enquiry about an existing order → `parse_enquiry` (kind by bounded phrase precedence; identifiers the application already trusts: order-shaped numbers with phone groups and dated years excluded, sender and mentioned addresses; asks from the customer's own words above any quoted reply) → `gather` (an evidence bundle: the order search, the hydrated order with history, up to three inbox threads from the customer's address or naming the order, the named knowledge-base lines quoted verbatim; every reader failure a named problem) → `identify` (exactly one order, or `ambiguous`/`not_found`/`no_identifier`/`unavailable`; `confident` only when written from the address on the order) → facts (fields the sources returned, cited), inferences (fulfilment status read as the carrier's word: label-only, delivered; open return; lateness against the published windows; dispatch later than the published rule; unanswered messages against the published reply time) and unknowns (where the parcel is: no carrier tracking is integrated; receipt of emails; what arrived) → `draft_reply` (from verified facts and the published policy only; unknowns answered by asking; `requires_owner_approval: true`, `external_effects: none`) → the Markdown summary with an evidence table. Entry points: `POST /support/investigate` (replays a bundle, or reads live through the bound read tools) and `scripts/support_investigate.py` (engages `app/readonly.py` before building a client; `--capture`, `--redacted-capture`, `--bundle`). `app/support/redact.py` produces the copy an engineering record may hold.

Nothing in the package imports or names a write tool (`test_nothing_in_the_support_package_imports_a_write_tool`); the live readers are `shopify_find_order`, `hydrator().order`, `gmail_tools.threads_for` and `gmail_read_thread` only; a fake store bound through the real tools sees only `CrooksOrderByName`, `CrooksOrderContext` and `CrooksCustomerOrders` queries and no mutation.

## The three rounds

1. e07e9130 — the package, route, CLI, synthetic tests, product-memory document.
2. 3e6ec77f — from the two real cases: a `CONFIRMED` fulfilment (label, no carrier scan) is not "dispatched"; a `DELIVERED` one is answered from the scan; an open return (`IN_PROGRESS`, name from the events) is recognised, not restarted; Shopify events are facts; the tool matrix regenerated.
3. 9f30dd7a and 92137562 — the enquiry read the way a person reads it (quoted mail, soft line breaks, greetings; phone groups and dated years are not order numbers); fulfilments as recorded facts; a system email matched by order number is evidence but not the customer waiting; unanswered messages named against the published reply time and the draft apologises; the delivery window and the returns rule in the customer's terms for the destination (verbatim when the line is not the known one); the internal note on one line; payout events not facts; tracking masked wherever typed in the redacted copy; the product-memory document brought up to r2.

## The real cases (redacted; the acceptance criterion is at least one)

Captured 2026-09-23 ~02:04–02:10Z, read-only, through the owner's Shopify and Gmail connectors from the engineering session: the application's own `CrooksOrderContext` and `CrooksCustomerOrders` queries run verbatim and shaped by `app.context.order`, and the same sender-or-order-number inbox search the application makes. Replayed through `gather` with readers answering from the capture, so the whole investigation ran on the candidate's code; only the transport differs from the Mac (no CLIVE credential exists in the engineering container).

**Case A** — delivery enquiry, order named, written from the address on the order; international order, fulfilment CONFIRMED (label, no carrier scan) 2 working days after the order; one unanswered message.

- identification: `identified`, `confident`, CROOKS-1968; reasons: the customer named order 1968; written from the email address on the order
- counts: 20 facts, 4 inferences, 2 unknowns, 1 owner decision(s), 16 evidence items, 2 thread(s) read
- reader calls (in order): find_order, order_detail, threads_for, read_thread, read_thread; reads only: True; external effects: none; approval state: awaiting_owner
- every order- or tracking-shaped token in the draft is in the evidence: True (tokens, tracking masked: 1968, 2026, 358824433, …8110)
- the redacted copy yields the same identification, confidence, inference texts and owner decisions: True
- inferences (redacted copy, verbatim):
  - The fulfilment status is CONFIRMED: a shipping label exists (created 15 Sep 2026) but no carrier scan has reached Shopify, so the parcel may not have been collected by FedEx yet.
  - Label created 7 day(s) ago for an international address: the parcel is still within the published international window (seven to fourteen days).
  - The first fulfilment was recorded 2 working day(s) after the order was placed; the published rule is same-day dispatch before 6pm, Monday to Saturday.
  - The customer is waiting on us in thread 'Order Shipping Update': the latest message is theirs.
- unknowns:
  - Where the parcel is now and whether it has been delivered: no carrier tracking is integrated, so only the tracking reference and the fulfilment status are known, not the scan history.
  - Whether the customer received the email(s) Shopify records as sent (15 Sep 2026): sending is recorded, receipt is not visible.
- owner decisions:
  - Order CROOKS-1968: confirm with the courier whether the parcel was collected on or after 15 Sep 2026; if it was not, get it collected or re-dispatch it, and tell the customer which.
- reply draft (redacted copy; the real one names the customer and the full tracking reference):

```
Hi Redacted,

Thanks for getting in touch about order CROOKS-1968.
Sorry for the wait.
A shipping label was created for it on 15 Sep 2026 with FedEx, tracking number …8110.
The carrier has not yet reported a collection scan on our side, so we are checking with them that it has been picked up and will confirm as soon as it is moving.
Once it is on its way, international delivery usually takes seven to fourteen days.
If it does not turn up, reply here and we will sort it: we chase the courier, or send a replacement or a refund.

CROOKS
```

**Case B** — return enquiry (too big), order named in the subject, written from the address on the order; UK order DELIVERED 10 Sep; return IN_PROGRESS opened 12 Sep through the returns portal; two unanswered messages.

- identification: `identified`, `confident`, CROOKS-1924; reasons: the customer named order 1924; written from the email address on the order
- counts: 23 facts, 3 inferences, 2 unknowns, 1 owner decision(s), 16 evidence items, 2 thread(s) read
- reader calls (in order): find_order, order_detail, threads_for, read_thread, read_thread; reads only: True; external effects: none; approval state: awaiting_owner
- every order- or tracking-shaped token in the draft is in the evidence: True (tokens, tracking masked: 1924)
- the redacted copy yields the same identification, confidence, inference texts and owner decisions: True
- inferences (redacted copy, verbatim):
  - The carrier has reported the parcel delivered on 10 Sep 2026; the fulfilment status is DELIVERED.
  - A return is already open on this order (CROOKS-1924-R1) (return status IN_PROGRESS), so the customer's request has reached us through the returns process and is waiting on our side.
  - The customer has written 2 time(s) in thread 'Fwd: Order CROOKS-1924 confirmed' without a reply from us; the latest was 1 working day(s) ago, and the published promise is a reply within one to two working days.
- unknowns:
  - Whether the parcel is actually with the customer: the carrier reports it delivered, and nothing here can see beyond that scan.
  - Whether the customer received the email(s) Shopify records as sent (10 Sep 2026): sending is recorded, receipt is not visible.
- owner decisions:
  - Order CROOKS-1924: approve or decline the open return CROOKS-1924-R1 and send the return instructions.
- reply draft (redacted copy; the real one names the customer and the full tracking reference):

```
Hi Redacted,

Thanks for getting in touch about order CROOKS-1924.
Sorry for the slow reply.
Your return request is already open on our side (CROOKS-1924-R1), so there is nothing more you need to do to start it.
We are confirming it now and will send you the return instructions as soon as that is done.
As a reminder, returns and exchanges are within fourteen days of delivery for unworn items with the tags on; return postage is yours to cover, and a UK size swap is free with the new size sent out at our cost.

CROOKS
```

The owner's verification (correct order, factual account matches the evidence, nothing invented, uncertainty explicit, reply answers the question, no more than minor editing) is pending and is the acceptance oracle; the raw reports are with the owner on the engineering session.

## Reviewer checklist

1. SHA resolves; parents as in the lineage row; tree clean; the 17 files above and nothing else; the six untouched directories' diff is empty.
2. `python -m pytest tests/test_support_investigator.py -q` → 53 passed; `tests/test_tool_matrix.py`, `tests/test_context.py`, `tests/test_product_memory_structure.py` pass beside it.
3. Try to make it write: the CLI with `--text` engages the latch before any client; the route holds no client and calls `gather` with the read tools; grep the package for a mutation, `send`, `create_draft`, `orderCancel`, `refundCreate`, `fulfillmentCreate`.
4. Try to make it invent: every scenario's draft tokens ⊆ evidence tokens; not-found and ambiguous drafts carry no number the customer did not give; an unknown is never answered.
5. Try to make it misidentify: two orders under the address and no number → ambiguous; a number from another address → possible, and the unknowns say so; a phone group or a dated year in the text; a number cued as an order comes first.
6. Redaction: `redact_bundle` on the synthetic late-UK case and on the real bundles leaves no name, address, phone, message body, note, or full tracking reference; the redacted run reaches the same identification, inferences and decisions.

## Known risks and judgement calls

1. **The route is guarded by the tailnet allow-list only**, not bound to a conversation like the other routes (it has no session); read-only, owner logins only, and a customer's order data is what the owner asked it to show. A session binding would be a small follow-up if the owner wants it.
2. **The live path was not run with CLIVE's own clients**: no credential exists in the engineering container. `app/support/live.py` is covered against a fake store through the real tools and by its unavailable path; the first live run is on the Mac, under the latch, and is part of the owner's verification.
3. **Deterministic drafting.** No model is in the loop; the wording is templated from facts and two policy lines put in the customer's terms (guarded to the known lines; verbatim otherwise). A more natural draft is a later revision, bound to the same evidence.
4. **Regex redaction.** Names are learned from the order and the address; a name typed in a message that is not on the order would survive as text (bodies themselves are replaced, the enquiry text is scrubbed). The real cases were checked by hand for leaks before recording.
5. **Reading of Shopify's fulfilment display statuses** (`CONFIRMED` = label without a scan; `DELIVERED`; the rest as dispatched) is the reading of the store's own field, not of carrier data; it is stated as inference, and "where the parcel is" stays unknown.
6. **The tool-matrix line** and the r1→r2 revision: a generated document changed because a new test file names a tool; the scope was widened by that one file through a recorded revision rather than by editing around it.
7. **Scheduled lateness arithmetic** counts weekdays; Saturday is a dispatch day at CROOKS but not a delivery day, so dispatch delays may read one day long on a Saturday order (stated in the inference wording as working days).

## After acceptance

`integrate --task-id support-investigator-v1 --revision 2 --integration-sha 92137562… --target-base-sha b68e6e82… --method fast_forward --verify-remote origin` on the task's target branch (already at the candidate) → DONE, rendered COMPLETE. Landing on the CI stream `claude/ci-provenance-acceptance-2026-09-22` is a fast-forward from b68e6e82 if the stream is still exactly there when the owner asks for it, as packet 10 was landed; not done from this verdict alone. Production deployment is not authorised by this packet or by a green CI run: the owner decides, after verifying the real cases. No watcher, systemd, runtime, secret, permission or business write.
