# EXACT-SHA GPT REVIEW PACKET 17 — Support Investigator V1, repair S-01R (support-investigator-v1 r4)

Generated 2026-09-23 10:39Z by the Claude engineering executor (session_014NGs3CS6XKQVhULWsHgqsi).
Reviewer principal: **gpt**. Claude-authored; GPT is eligible. One repository, one successor commit to the packet-16 candidate 2ca2bfee, the one remaining S-01 path closed. Nothing else changed: no evidence gathering, identification, kernel, routing, Agent Environment or write-authority change.

## Identity

| Field | Value |
| --- | --- |
| candidate_sha | `109f58c40b12b996a353731f5a42bdbf2abbf9bb` |
| branch (head == candidate when written) | `claude/support-investigator-v1-2026-09-23` (target); `claude/support-investigator-v1-2026-09-23-r4` (the r4 workspace branch, same head) |
| base / parent | task base `b68e6e827afbeba3364c8239a2d814a60372f498`; parent `2ca2bfee61f91425f119e751ea598d2337b1443e` (packet 16, CHANGES REQUIRED S-01R; preserved, not rewritten) |
| kernel task | `support-investigator-v1` r4 (kind repair), attempt `support-investigator-v1-a4`, fencing token 4, on `clive/engineering-state`; the packet-16 verdict is admitted against r3's attempt a3 (`rejected_by_verdict`), r3 OBSOLETE, superseded by r4 |
| author_principal | claude |
| review_state | NOT_REVIEWED |
| ci_state | PASS — run 35849264263, https://github.com/crooksldn-pixel/clive/actions/runs/35849264263, 2026-09-23T10:31:14Z to 10:34:27Z, all five gates green at 109f58c40b12b996a353731f5a42bdbf2abbf9bb |
| local evidence | `scripts/acceptance_provenance.py --candidate-sha 109f58c4… --suite full` at 2026-09-23T10:37:56Z in the r4 workspace (clean tree, head == candidate), Python 3.12.3, gitleaks 8.30.1: ruff pass; pytest_control_plane pass (44 passed in 0.36s); product_memory_structure pass; pytest_offline_full pass (3112 passed, 8 skipped, 2 deselected in 384.31s (0:06:24)); secret_scan pass (10:37AM INF no leaks found); `eligible_for_acceptance_decision: True`, `accepted: False` (`acc-support-109f58c4.json`, recorded as this attempt's `acceptance_provenance` evidence) |
| real-case evidence | `evidence-support/real_case_acceptance.json` (sha256 `85a32877b5efbdaa6004c60e2cc804561cd75c948e3d7667dc11d89ff27be276`), redacted, the same two captured cases replayed on this tree; recorded as this attempt's `real_case_acceptance` evidence |
| Agent Environment, kernel, watcher, systemd, runtime | untouched |

## Diff scope

`git diff --stat 2ca2bfee..109f58c4`: 3 files, 79 insertions, 2 deletions — `app/support/reply.py` (+3/−1: the no-tracking branch), `tests/test_support_investigator.py` (+13/−1), `tests/fixtures/support/orders.json` (one synthetic order, `untracked_moving`). `git diff 2ca2bfee 109f58c4 -- app/support/enquiry.py app/support/evidence.py app/support/investigate.py app/support/live.py app/support/redact.py app/support/report.py app/routes scripts docs` is empty.

## The finding, its mechanism and its test

| Finding | Mechanism at 109f58c4 | Test |
| --- | --- | --- |
| **S-01R** the no-tracking fulfilment branch said "It was dispatched on…" whatever the fulfilment display status | The branch now makes the same bounded reading as the tracked branch: `opening = "It was dispatched on" if moving([f]) else "Our records show it as fulfilled on"`, where `moving()` is the existing `MOVING_STATUSES` reading (PICKED_UP, IN_TRANSIT, OUT_FOR_DELIVERY, ATTEMPTED_DELIVERY). The line "We do not have a tracking reference on file for it, so we need to check with the courier before we can say where it is." is kept unchanged. | `test_a_fulfilment_without_tracking_is_an_unknown_not_a_guess` now asserts, for the `untracked` fixture (FULFILLED, no tracking), that the draft contains "Our records show it as fulfilled on 15 Sep 2026", the tracking line verbatim, and that "dispatched" does not appear anywhere in the body. `test_an_untracked_fulfilment_whose_status_records_movement_is_still_dispatched` (new fixture `untracked_moving`, IN_TRANSIT, no tracking) asserts "It was dispatched on 15 Sep 2026 with Royal Mail" and the same tracking line. The unresolved-cases test asserts the FULFILLED wording too, and both fixtures are in the eighteen-plus-one scenario action-underway scan. |

`tests/test_support_investigator.py` 75 passed.

## The real cases (redacted; the oracle is unchanged)

Neither real case has an untracked fulfilment, so both drafts are byte-identical to packet 16's; they are replayed on this tree and re-checked (identity, tokens, reads only, no action-underway phrase).

**Case A** — delivery enquiry, order named, written from the address on the order; international order, fulfilment CONFIRMED (a label, no later status) 2 working days after the order; one unanswered message.

- identification: `identified`, `confident`, CROOKS-1968; reads only: True; external effects: none; draft tokens in evidence: True; no action-underway or promise phrase: True; dispatched only with recorded movement: True
- the redacted copy yields the same identification, confidence, inferences and owner decisions: True
- reply draft (redacted copy, byte-identical to packet 16's):

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

- identification: `identified`, `confident`, CROOKS-1924; reads only: True; external effects: none; draft tokens in evidence: True; no action-underway or promise phrase: True; dispatched only with recorded movement: True
- the redacted copy yields the same identification, confidence, inferences and owner decisions: True
- reply draft (redacted copy, byte-identical to packet 16's):

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

1. SHA resolves; parent 2ca2bfee; tree clean; `git diff 2ca2bfee 109f58c4 --stat` is the three files above; the listed untouched paths' diff is empty.
2. `python -m pytest tests/test_support_investigator.py -q` → 75 passed. `grep -n "dispatched" app/support/reply.py`: two occurrences, both behind `moving([f])`.
3. The convergence rule of packet 16: this closes the named path; customer identity, factual grounding, uncertainty, read-only authority and privacy are unchanged (no code outside the one branch and its tests moved).

## Known risks and judgement calls

1. As packet 16: conditional statements remain; "pending approval" depends on a read message or the note; movement statuses are Shopify's; the route is allow-list guarded; the live clients were not run in the container; deterministic drafting; regex redaction.

## After acceptance

`integrate --task-id support-investigator-v1 --revision 4 --integration-sha 109f58c4… --target-base-sha b68e6e82… --method fast_forward --verify-remote origin` on the task's target branch (already at the candidate) → DONE, rendered COMPLETE. Landing on the CI stream is a separate owner ask (fast-forward from b68e6e82 if the stream is still exactly there). Production deployment is not authorised by this packet or by a green CI run; the owner decides after verifying the two cases. No watcher, systemd, runtime, secret, permission or business write.
