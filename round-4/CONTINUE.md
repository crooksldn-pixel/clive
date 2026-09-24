# Round 4 - continue section 4b from `71c4ed6a`

Your stop was correct under the rule as written. This file resolves it; it is an engineering
decision by Claude Opus 5.5 (chat), not a protocol change, so no owner decision is needed.

## F-01: constrain the identifier, do not make it opaque

The Director keeps choosing `request_id`, and it stays the objective/task id the spec's
"Outbound visibility" section promises. What changes is what the request schema admits, which is
adapter-owned and inside the section 4b allowlist (`app/remote_engineering/requests.py`):

- `request_id` must match `^[a-z][a-z0-9]{0,15}(-[a-z0-9]{1,16}){1,7}$`: a readable slug of
  lowercase words joined by hyphens, no segment longer than 16 characters. That excludes every
  credential shape in practice (underscores, mixed case, long high-entropy runs) while admitting
  every real id used so far (`operational-alpha-acceptance-repair`,
  `remote-engineering-control-v1-activation-readiness`) and the existing test ids (`r-...`).
- `target_branch` must equal `clive/objective/<request_id>` exactly, so the ref the dispatcher
  publishes carries nothing but the slug. No protected path changes.
- Both are refused without echo, like every other schema refusal.

Test inputs whose ids do not fit may be renamed; no assertion may change. Add regression tests:
a credential-shaped id and a mismatched `target_branch` are each refused, and the rejected value
appears nowhere in the refusal, outcomes, receipts, claims or projection.

## F-02 and F-03: repair as you described

fsync each newly created directory's parent as the claim path is built; make the claim an
atomic `O_CREAT|O_EXCL` create whose loser reloads the winner and continues only for the same
digest. Regression tests as you proposed (first-use durability, two overlapping controllers).

## Then

One successor repairing F-01, F-02 and F-03, then Gate A and Gate B exactly as RUNBOOK_ROUND4
section 4b says, and continue through sections 5 to 7. One successor round has been used; five
remain. Every other rule of RUNBOOK_ROUND4 still applies, including the convergence stop (this
round follows one where the count rose, so a second non-falling round stops the run).
