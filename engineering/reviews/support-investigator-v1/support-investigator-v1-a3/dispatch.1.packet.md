# EXACT-SHA GPT REVIEW PACKET 16 — Support Investigator V1, repair S-01 (support-investigator-v1 r3)

Generated 2026-09-23 10:26Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. One repository, one successor commit to the packet-15 candidate 92137562, the one finding of packet 15 resolved. No kernel, evidence-gathering, identification, routing or write-authority change; no K-series work.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `2ca2bfee61f91425f119e751ea598d2337b1443e` |
| branch (head == candidate when written) | `claude/support-investigator-v1-2026-09-23` (target); `claude/support-investigator-v1-2026-09-23-r3` (the r3 workspace branch, same head) |
| base / parent | task base `b68e6e827afbeba3364c8239a2d814a60372f498` (the landed packet-10 candidate); parent `921375628d13ce338c659a7b789c11d8ac2b5f58` (packet 15, CHANGES REQUIRED; preserved, not rewritten) |
| kernel task | `support-investigator-v1` r3 (kind repair), attempt `support-investigator-v1-a3`, fencing token 3, on `clive/engineering-state`; the packet-15 verdict is admitted against r2's attempt a2 (`rejected_by_verdict`), r2 OBSOLETE, superseded by r3 |
| author_principal | claude |
| review_state | NOT_REVIEWED |
| ci_state | PASS — run 35848037844, https://github.com/crooksldn-pixel/clive/actions/runs/35848037844, 2026-09-23T10:18:30Z to 10:21:59Z, all five gates green at 2ca2bfee61f91425f119e751ea598d2337b1443e |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha 2ca2bfee… --suite full` at 2026-09-23T10:25:16Z in the r3 workspace (clean tree, head == candidate), Python 3.12.3, gitleaks 8.30.1: ruff pass; pytest_control_plane pass (44 passed in 3.60s); product_memory_structure pass; pytest_offline_full pass (3110 passed, 8 skipped, 2 deselected in 384.55s (0:06:24)); secret_scan pass (10:25AM INF no leaks found); `eligible_for_acceptance_decision: True`, `accepted: False` (`acc-support-2ca2bfee.json`, recorded as this attempt's `acceptance_provenance` evidence) |
| real-case evidence | `evidence-support/real_case_acceptance.json` (sha256 `7dc8ad3395c1fce84c449be8813b30dc6a5c8d2ed6a052e436f9bd31b8f37864`), redacted, the same two captured cases replayed on this tree; recorded as this attempt's `real_case_acceptance` evidence |
| Agent Environment, kernel, watcher, systemd, runtime | untouched |

## Diff scope

`git diff --stat 92137562..2ca2bfee`: 5 files, 150 insertions, 26 deletions — `app/support/reply.py` (+51/−26: the template audit), `app/support/investigate.py` (+21: `MOVING_STATUSES`, `moving()`, `pending_approval()`, the bounded label-only inference wording), `tests/test_support_investigator.py` (+72: three tests, one parametrised over eighteen scenarios), `tests/fixtures/support/threads.json` (one synthetic returns-system thread), `docs/product-memory/SUPPORT_INVESTIGATOR_V1.md` (one sentence). Untouched: enquiry parsing, the evidence bundle and its readers, identification, the route, the CLI, redaction, the live adapters, and everything outside `app/support` and its tests.

## The finding, its mechanism and its test

| Finding | Mechanism at 2ca2bfee | Test |
| --- | --- | --- |
| **S-01** drafts claimed internal actions were underway (checking with the courier, confirming a return) without evidence; systemic in the templates | Every template line in `reply.py` was audited against the rule a draft may only state a verified fact, state uncertainty, say what still needs doing, ask the customer for what is needed, or make a policy-backed statement. Removed: "we are checking…", "we are chasing…", "we are finding out…", "we have passed it to the team…", "we are confirming it now…", "we will look into / take it up / come back / update / arrange / get / check / send / confirm…". The label-only shipment is now described by Shopify's recorded status ("Our system currently shows the shipment as CONFIRMED rather than picked up or in transit, so we cannot confirm from our records that FedEx has collected it yet. We need to check that with the courier before we can give you a definite update."), and the matching inference reads "recorded status is CONFIRMED, not PICKED_UP, IN_TRANSIT or DELIVERED: Shopify holds a label … and no later status, so whether the carrier has collected the parcel is not established from our records". An open return is said to be "currently pending approval" only when a message read from the inbox (or the order note) says so, and that message is cited in the draft's basis; otherwise the recorded return status is given; the second line is "Once it has been reviewed, we can confirm the outcome and the return instructions." "It was dispatched on…" is said only for statuses that record movement (PICKED_UP, IN_TRANSIT, OUT_FOR_DELIVERY, ATTEMPTED_DELIVERY); otherwise "Our records show it as fulfilled on…". Unresolved cases say what needs doing: "Cancelling it is a step we need to take on our side"; "we need to find out what has held it before we can give you a date"; "we need to check with the courier before we can say where it is"; "it needs chasing with the courier"; the lost-or-damaged line is the policy as published ("that is on us to sort, and the options are chasing the courier, a replacement or a refund"). The module docstring states the rule. | `test_no_draft_claims_an_internal_action_is_underway_or_promised` (eighteen scenarios: the two real-case shapes, late, twice-chased, held, cancel before and after dispatch, address change before and after dispatch, cancelled, wrong item, missing item, untracked, damaged, return, not found, ambiguous): the draft matches no action-underway or promise pattern and none of the eight named phrases. `test_an_open_return_that_the_returns_system_says_is_pending_approval_is_said_so_with_its_evidence`: "pending approval" appears only with the returns-system thread present and its reference is in `based_on`. `test_unresolved_cancel_held_and_untracked_cases_say_what_needs_doing_not_what_is_being_done`: the four need-phrasings, and IN_TRANSIT is still "dispatched". The label-only and open-return tests assert the new wording verbatim. |

`tests/test_support_investigator.py` 73 passed; `test_context.py`, `test_tool_matrix.py` and `test_product_memory_structure.py` pass beside it; the generated tool matrix is unchanged.

## The real cases (redacted; the oracle is unchanged)

The same two captured bundles, replayed on this tree. Both drafts pass the action-underway scan; the identification, facts, unknowns and owner decisions are as in packet 15.

**Case A** — delivery enquiry, order named, written from the address on the order; international order, fulfilment CONFIRMED (a label, no later status) 2 working days after the order; one unanswered message.

- identification: `identified`, `confident`, CROOKS-1968; reasons: the customer named order 1968; written from the email address on the order
- reads only: True; external effects: none; every order- or tracking-shaped token in the draft is in the evidence: True; no action-underway or promise phrase in the draft: True
- the redacted copy yields the same identification, confidence, inference texts and owner decisions: True
- inferences (redacted copy, verbatim):
  - The fulfilment's recorded status is CONFIRMED, not PICKED_UP, IN_TRANSIT or DELIVERED: Shopify holds a label (created 15 Sep 2026) and no later status, so whether FedEx has collected the parcel is not established from our records.
  - Label created 7 day(s) ago for an international address: the parcel is still within the published international window (seven to fourteen days).
  - The first fulfilment was recorded 2 working day(s) after the order was placed; the published rule is same-day dispatch before 6pm, Monday to Saturday.
  - The customer is waiting on us in thread 'Order Shipping Update': the latest message is theirs.
- owner decisions:
  - Order CROOKS-1968: confirm with the courier whether the parcel was collected on or after 15 Sep 2026; if it was not, get it collected or re-dispatch it, and tell the customer which.
- draft basis: `enquiry`, `shopify:order:gid://shopify/Order/8258430566743`, `kb:delivery_windows`, `kb:lost_or_damaged`
- reply draft (redacted copy; the real one names the customer and the full tracking reference):

```
Hi Redacted,

Thanks for getting in touch about order CROOKS-1968.
Sorry for the wait.
A shipping label was created for it on 15 Sep 2026 with FedEx, tracking number …8110.
Our system currently shows the shipment as CONFIRMED rather than picked up or in transit, so we cannot confirm from our records that FedEx has collected it yet. We need to check that with the courier before we can give you a definite update.
Once it is on its way, international delivery usually takes seven to fourteen days.
If it does not turn up, reply here: that is on us to sort, and the options are chasing the courier, a replacement or a refund.

CROOKS
```

**Case B** — return enquiry (too big), order named in the subject, written from the address on the order; UK order DELIVERED 10 Sep; return IN_PROGRESS opened 12 Sep through the returns portal, pending approval per the returns-system message in the inbox; two unanswered messages.

- identification: `identified`, `confident`, CROOKS-1924; reasons: the customer named order 1924; written from the email address on the order
- reads only: True; external effects: none; every order- or tracking-shaped token in the draft is in the evidence: True; no action-underway or promise phrase in the draft: True
- the redacted copy yields the same identification, confidence, inference texts and owner decisions: True
- inferences (redacted copy, verbatim):
  - The carrier has reported the parcel delivered on 10 Sep 2026; the fulfilment status is DELIVERED.
  - A return is already open on this order (CROOKS-1924-R1) (return status IN_PROGRESS), so the customer's request has reached us through the returns process and is waiting on our side.
  - The customer has written 2 time(s) in thread 'Fwd: Order CROOKS-1924 confirmed' without a reply from us; the latest was 1 working day(s) ago, and the published promise is a reply within one to two working days.
- owner decisions:
  - Order CROOKS-1924: approve or decline the open return CROOKS-1924-R1 and send the return instructions.
- draft basis: `enquiry`, `shopify:order:gid://shopify/Order/8244675281239`, `kb:returns`
- reply draft (redacted copy; the real one names the customer and the full tracking reference):

```
Hi Redacted,

Thanks for getting in touch about order CROOKS-1924.
Sorry for the slow reply.
Your return request is already open on our side (CROOKS-1924-R1) (status IN_PROGRESS), so you do not need to submit another request.
Once it has been reviewed, we can confirm the outcome and the return instructions.
As a reminder, returns and exchanges are within fourteen days of delivery for unworn items with the tags on; return postage is yours to cover, and a UK size swap is free with the new size sent out at our cost.

CROOKS
```


## Reviewer checklist

1. SHA resolves; parent 92137562; tree clean; `git diff 92137562 2ca2bfee --stat` is the five files above; `git diff 92137562 2ca2bfee -- app/support/enquiry.py app/support/evidence.py app/support/live.py app/support/redact.py app/routes scripts` is empty.
2. `python -m pytest tests/test_support_investigator.py -q` → 73 passed. Then grep `app/support/reply.py` for `we are `, `we will`, `we'll`, `we have passed`: the only "we are" left is none, and the remaining first-person lines are facts, needs ("we need to…"), asks and policy.
3. Case A's draft: no claim that anyone is checking with the courier; the status sentence is bounded to what Shopify records. Case B's draft: "pending approval" cited to the returns-system message; no claim that the return is being confirmed.
4. Try to find an unproved claim in any other branch of the template (cancelled order, address change after dispatch, damaged, wrong or missing item, return without an open request, not identified).

## Known risks and judgement calls

1. **Conditional statements remain** ("once it has been cancelled you will get a confirmation", "once it has been reviewed, we can confirm the outcome"): these describe what follows a step the owner has yet to take, not an action underway; the owner decision list names the step.
2. **"Pending approval" depends on a returns-system message being in the bundle** (matched by the order number in the sixty-day inbox search) or on the order note; without it the draft gives the recorded return status, which is the weaker but true statement.
3. **Movement statuses** are Shopify's display statuses; `FULFILLED`/`MARKED_AS_FULFILLED` without carrier events now read "our records show it as fulfilled on…" rather than "dispatched", which is the bounded reading.
4. Unchanged from packet 15: the route is guarded by the allow-list only; the live clients were not run in the container; deterministic drafting; regex redaction.

## After acceptance

`integrate --task-id support-investigator-v1 --revision 3 --integration-sha 2ca2bfee… --target-base-sha b68e6e82… --method fast_forward --verify-remote origin` on the task's target branch (already at the candidate) → DONE, rendered COMPLETE. Landing on the CI stream is a separate owner ask (a fast-forward from b68e6e82 if the stream is still exactly there), as packet 10 was landed. Production deployment is not authorised by this packet or by a green CI run; the owner decides after verifying the two cases. No watcher, systemd, runtime, secret, permission or business write.
