# Quality harness plan

Quality is layered evidence, not a single test command.

## Evidence layers

1. Scope and protected paths — candidate stayed inside approved boundaries.
2. Static checks — lint, format, schema/control checks.
3. Focused unit tests — fast feedback on changed behavior.
4. Integration tests — prove module interactions and persistence boundaries.
5. Browser verification — required for meaningful owner-visible interaction changes.
6. CLIVE Bench — required when assistant behavior, tool selection, presentation or permission semantics change.
7. Exact-SHA GitHub acceptance — final CI evidence must refer to the candidate under review.
8. Independent review — fresh principal/session, read-only candidate, explicit acceptance contract.

## Quality routing

The implementation plan must encode which work types need which evidence. Example only:

| Change | Typical evidence |
| --- | --- |
| docs/test-only | scope/static/focused as relevant |
| backend parser | scope/static/unit/integration/exact-SHA/review |
| UI flow | plus browser |
| assistant behavior | plus Bench |
| security/permissions | targeted negative/security evidence + exact-SHA + elevated review |

Do not hard-code this table until existing acceptance behavior is audited.

## Repair

A failed gate becomes structured evidence for the next repair attempt. George should not relay stack traces, failed tests, CI output or reviewer findings. Escalate only after repair limit or when owner authority is genuinely required.

## Fault injection

Before calling the harness strong enough, deliberately test candidates with:
- subtle regression;
- missing edge case;
- wrong date/time assumption;
- UI interaction bug;
- permission widening;
- false success state;
- hidden external dependency;
- scope violation;
- concurrency/race defect where practical.

Record which layer caught each defect.

## Fast feedback vs final gate

Fast local checks may be selective. Final exact-SHA acceptance remains authoritative and cannot be silently replaced by impacted-test selection alone.
