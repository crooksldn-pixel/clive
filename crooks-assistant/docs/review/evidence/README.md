# Review evidence — what settles each open finding

Rounds 9 and 10 of the exact-SHA deploy review came back mostly "I cannot settle this from my
files": each reviewer held one slice of the tree and only the signatures of what it calls, and
its own rule makes an unsettled finding BLOCKS. Rewriting code does not answer that; putting the
right bodies in front of a reviewer does. These files say, for every open finding, which bodies
and which tests settle it, so the next review can hand exactly those over.

One JSON file per area of the fix round that wrote it (`pages`, `screens-server`, `door`,
`records`, `families`, `turn`, `tests`). Each is a list of entries:

| Field | What it is |
|---|---|
| `finding` | The finding's id as the review record gives it (`R9-…` for a round-9 finding ruled on in round 10; a part's own id, such as `S1T-01` or `CFG-01`, for a new round-10 finding). |
| `parts` | The round-10 parts that raised it. |
| `status` | `FIXED` (a real defect, fixed, with a test that fails on the old code), `EVIDENCED` (the code already does what the finding needs; the named tests prove it), `DEPLOY-TIME` (only a live result at deploy settles it; the answer names the check), or `LEFT` (a follow-up not fixed, and why). |
| `question` | One sentence: what the reviewer has to settle. |
| `files` | The bodies that settle it, from the repo root. Kept under about 250 KB together, so that one entry, with its question, fits one review packet. |
| `excerpts` | Only where one file is too large to send whole beside the rest (`web/app.js`): the functions of it to send. |
| `tests` | `path::name` of the tests that prove it — pytest node ids, or a node test's title. Every one exists and passes at the commit that carries this file. |
| `answer` | What the author found, true at that commit: which symbols settle it, and how. A claim for the reviewer to check against the files, never evidence in itself. |

An entry is a claim. The reviewer reads the files and rules; where the files do not bear the
answer out, that is a finding.

Round 11 wrote these for all 100 open findings: every material finding of round 10's nineteen
reviewed parts, and every round-9 finding round 10 ruled STILL PRESENT, CANNOT TELL, or could
not rule on because its part was never reviewed.

Round 13 added `round12.json`, one entry for each of round 12's blocking findings that is not a
defect once the code is read or not a blocker by the rule's own terms, with the ids as round 12's
record gives them, `parts` naming the round-12 part (or the round-11 entry's parts for an
evidence finding), and `excerpts` given as line ranges (`lines 503-600: what they are`) that
`tests/test_r13_evidence_index.py` holds to the tree. Where writing the evidence showed a real
defect instead, it was fixed in the same round and the entry says `FIXED`, naming first the tests
that fail on the code before the fix.

It now holds all 62: the entries above, and one for each of the 39 findings round 13's fix map
found real (blocking, or real but not a blocker as configured). Each of those says `FIXED`, naming
first the tests that fail at `361b0138` and then the neighbouring tests that hold the rest, or
`LEFT` with the reason: R9-A3b-F-04-SHUTDOWN on purpose, and R9-I-tests5-I-01 until George
decides it. The record gives one id twice — R9-B2-B2-01, a finding of the pages evidence and
another of the screens-server evidence — so it has two entries, told apart by their `parts`.
