# EXACT-SHA GPT REVIEW PACKET 18 — Support Investigator V1, repair S-01C (support-investigator-v1 r5)

Generated 2026-09-23 11:08Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. One repository, one successor commit to the packet-17 candidate 109f58c4, the S-01C path closed. No kernel, routing, Agent Environment, evidence-gathering, write-authority or runtime change.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `2dbb97bc6c88d3ee3cf5cdf6a980df4f3405104a` |
| branch (head == candidate when written) | `claude/support-investigator-v1-2026-09-23` (target); `claude/support-investigator-v1-2026-09-23-r5` (the r5 workspace branch, same head) |
| base / parent | task base `b68e6e827afbeba3364c8239a2d814a60372f498`; parent `109f58c40b12b996a353731f5a42bdbf2abbf9bb` (packet 17, CHANGES REQUIRED S-01C; preserved, not rewritten) |
| kernel task | `support-investigator-v1` r5 (kind repair), attempt `support-investigator-v1-a5`, fencing token 5, on `clive/engineering-state`; the packet-17 verdict is admitted against r4's attempt a4 (`rejected_by_verdict`), r4 OBSOLETE, superseded by r5 |
| author_principal | claude |
| review_state | NOT_REVIEWED |
| ci_state | PASS — run 35852041530, https://github.com/crooksldn-pixel/clive/actions/runs/35852041530, 2026-09-23T11:00:38Z to 11:04:17Z, all five gates green at 2dbb97bc6c88d3ee3cf5cdf6a980df4f3405104a |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha 2dbb97bc… --suite full` at 2026-09-23T11:07:21Z in the r5 workspace (clean tree, head == candidate), Python 3.12.3, gitleaks 8.30.1: ruff pass; pytest_control_plane pass (44 passed in 0.53s); product_memory_structure pass; pytest_offline_full pass (3120 passed, 8 skipped, 2 deselected in 384.62s (0:06:24)); secret_scan pass (11:07AM INF no leaks found); `eligible_for_acceptance_decision: True`, `accepted: False` (`acc-support-2dbb97bc.json`, recorded as this attempt's `acceptance_provenance` evidence) |
| real-case evidence | `evidence-support/real_case_acceptance.json` (sha256 `9463f46f129d1aa2cc7baf7f0cec14abc5a9fe7a5aff099b11be346717c1db08`), redacted, the same two captured cases replayed on this tree; recorded as this attempt's `real_case_acceptance` evidence |
| Agent Environment, kernel, watcher, systemd, runtime | untouched |

## Diff scope

`git diff --stat 109f58c4..2dbb97bc`: 3 files, 121 insertions, 24 deletions — `app/support/reply.py` (+46/−... : `_after_fulfilment()`, the cancel/address-change call site, the no-fulfilment wording, delivery-only lines restricted to delivery enquiries), `app/support/investigate.py` (+37: `_change_decision()`, the no-fulfilment fact and inference wording, the lateness verb), `tests/test_support_investigator.py` (+62: four tests, four scan scenarios, three updated assertions). `git diff 109f58c4 2dbb97bc -- app/support/enquiry.py app/support/evidence.py app/support/live.py app/support/redact.py app/support/report.py app/routes scripts docs tests/fixtures` is empty.

## The finding, its mechanism and its test

| Finding | Mechanism at 2dbb97bc | Test |
| --- | --- | --- |
| **S-01C** cancel and address-change paths said "already been dispatched", and could refuse, whenever any fulfilment existed (draft and owner decisions) | Both now read the fulfilment record with the same three-way movement reading the rest of the reply uses. `reply.py::_after_fulfilment(kind, order, fulfillments)`: **delivered** → "Our records show it delivered on <date>, so it can no longer be cancelled; you have fourteen days from delivery to return it for a refund" / "…so the delivery address can no longer be changed"; **moving** (PICKED_UP, IN_TRANSIT, OUT_FOR_DELIVERY, ATTEMPTED_DELIVERY) → the previous "Because it has already been dispatched…" lines, unchanged; **otherwise** (CONFIRMED, FULFILLED, any status without recorded movement) → "Our records show a fulfilment for it created on <date> (status <STATUS>), but not whether the parcel has actually left us, so we cannot say yet whether it can still be cancelled / the address can still be changed." + "That needs checking on our side before we can give you an answer." + (cancel) the return policy if it has gone / (address) an ask for the full new address. No fulfilment: "Our records show no fulfilment for it yet (placed on <date>), so it can still be cancelled / the address can still be changed" (a Shopify capability, not a guessed rule). Delivery-only lines (window, chasing, lost parcel) no longer appear on a cancel or address-change reply. `investigate.py::_change_decision(kind, number, fulfillments)`: no fulfilment → "Our records show no fulfilment."; delivered → "The carrier reports it delivered, so this is a return question rather than a cancellation." / "…so the delivery address can no longer be changed."; moving → "The recorded status is <STATUS>: it has already been dispatched, so a cancellation would be a return instead." / "…so the address cannot be changed on this shipment."; otherwise → "A fulfilment is recorded (status <STATUS>) without recorded movement, so whether the parcel has left is not established: check with the warehouse or courier first; if it has not gone, cancel it / change the address; if it has, treat it as a return / the address cannot be changed on this shipment." The same reading is applied to the no-fulfilment fact ("No fulfilment recorded on the order."), the held inference ("No fulfilment recorded N working day(s) after the order was placed…") and its decision, and the lateness verb ("Fulfilment recorded N day(s) ago" for a status without movement). | `test_a_cancellation_against_a_label_only_fulfilment_is_uncertainty_not_a_refusal` (label_only_us, CONFIRMED): no "dispatched" anywhere in the draft, no "cannot cancel" / "can no longer be cancelled", the uncertainty sentence and the "needs checking" sentence verbatim, no delivery-window or lost-parcel line, and the decision contains "without recorded movement" and "not established" and not "already been dispatched". `test_an_address_change_against_a_label_only_fulfilment_is_uncertainty_not_a_refusal`: the same for the address path with the full-address ask. `test_cancel_and_address_change_against_a_moving_fulfilment_still_say_dispatched` (late_uk, IN_TRANSIT): both "Because it has already been dispatched…" lines verbatim and the IN_TRANSIT decision. `test_cancel_against_a_fulfilled_untracked_or_delivered_order_reads_the_record_not_the_fulfilment`: FULFILLED without tracking → the uncertainty branch with "(status FULFILLED)" and no "dispatched"; DELIVERED → "can no longer be cancelled; you have fourteen days from delivery…" and the return-question decision. Four new scenarios in the action-underway scan; the cancel-before-dispatch, cancel-after-dispatch and held tests updated to the record wording. |

`tests/test_support_investigator.py` 83 passed; the generated tool matrix is unchanged.

## Every "dispatched" in the two modules at this SHA (correcting packet 17's count)

`grep -n dispatched app/support/reply.py app/support/investigate.py`:

- `reply.py:160` and `reply.py:175` — `opening = "It was dispatched on" if moving([f]) else …` (tracked and untracked description; behind `moving`).
- `reply.py:173` and `reply.py:249` — a comment and the `_after_fulfilment` docstring.
- `reply.py:261` and `reply.py:262` — the cancel and address-change lines, inside `_after_fulfilment` under `if moving(fulfillments):`.
- `investigate.py:337` and `investigate.py:338` — the published UK window wording "one to two working days once dispatched" (the policy's own words, in the lateness inference; the inference's verb is "Label created" / "Dispatched" / "Fulfilment recorded" by status).
- `investigate.py:420` and `investigate.py:421` — the moving-status decisions, inside `_change_decision` under `if moving(fulfillments):`.

No occurrence is reachable without a movement status, except the quoted policy wording.

## The real cases (redacted; the oracle is unchanged)

Neither real case is a cancel or address-change enquiry, so both drafts are byte-identical to packets 16 and 17; both are replayed on this tree and re-checked (identity, tokens, reads only, no action-underway phrase, no dispatch claim from a fulfilment record).

**Case A** — delivery enquiry, order named, written from the address on the order; international order, fulfilment CONFIRMED (a label, no later status) 2 working days after the order; one unanswered message.

- identification: `identified`, `confident`, CROOKS-1968; reads only: True; external effects: none; draft tokens in evidence: True; no action-underway or promise phrase: True; no dispatch claim from a fulfilment record: True
- the redacted copy yields the same identification, confidence, inferences and owner decisions: True
- reply draft (redacted copy, byte-identical to packets 16 and 17):

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

- identification: `identified`, `confident`, CROOKS-1924; reads only: True; external effects: none; draft tokens in evidence: True; no action-underway or promise phrase: True; no dispatch claim from a fulfilment record: True
- the redacted copy yields the same identification, confidence, inferences and owner decisions: True
- reply draft (redacted copy, byte-identical to packets 16 and 17):

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

1. SHA resolves; parent 109f58c4; tree clean; `git diff 109f58c4 2dbb97bc --stat` is the three files above; the listed untouched paths' diff is empty.
2. `python -m pytest tests/test_support_investigator.py -q` → 83 passed.
3. The grep list above against the working tree: every customer-facing or decision "dispatched" sits under a `moving(...)` test; the remaining two are the policy's published window wording.
4. The convergence criteria of packet 17: customer identity, factual grounding, explicit uncertainty, read-only authority, privacy, materially misleading output — nothing outside `_after_fulfilment`, `_change_decision`, the record wording and the tests moved.

## Known risks and judgement calls

1. **"So it can still be cancelled" with no fulfilment** states a Shopify capability (an unfulfilled order can be cancelled in the store), not a business rule about whether the owner will; the decision list carries the question.
2. **The moving-status refusal** ("we cannot cancel it now") is kept as accepted in packets 16 and 17: movement recorded by the carrier is the evidence for it.
3. **A fulfilment without movement** is now always uncertainty in the draft, including FULFILLED/MARKED_AS_FULFILLED set by hand without a carrier; if the owner's practice is that such a status means the parcel left, that is a rule for the owner to write into the knowledge base, not for the tool to assume.
4. As packets 16 and 17 for the rest.

## After acceptance

`integrate --task-id support-investigator-v1 --revision 5 --integration-sha 2dbb97bc… --target-base-sha b68e6e82… --method fast_forward --verify-remote origin` on the task's target branch (already at the candidate) → DONE, rendered COMPLETE. Landing on the CI stream is a separate owner ask; production deployment is not authorised by this packet or by a green CI run. No watcher, systemd, runtime, secret, permission or business write.
