---
name: transaction-safety
description: Rules for any operation with a consequential external side effect, such as charging or paying, buying labels, refunds or store credit, changing inventory, creating irreversible resources, or sending customer emails. Use automatically when writing or reviewing such code paths, their retries, reconciliation, or reprint/resend features.
---

# Transaction safety

Learned the hard way: Parcel2Go charges again when an already-paid order is paid again, and a
lost reply looked exactly like a failure. Treat every external write as possibly done.

## Rules

1. **Persist intent before the side effect.** Write a ledger row (operation id, idempotency key,
   approved amount, fingerprint of what was approved, actor) before calling the provider. Save
   each state transition before the call that might move money ("pay_sent" before pay).
2. **Our own idempotency, always.** The same key replays the stored outcome. A new key while an
   operation is open is refused. Enforce one open operation per subject in the database (a
   unique partial index), not only with a lock. Use provider idempotency keys too where they
   exist, but never rely on them alone.
3. **Timeout is not failure.** A write whose reply was lost (read timeout, reset, 5xx, or an
   unreadable body) is **UNKNOWN**. Only a definite refusal (4xx, explicit errors, or "never
   connected") is a failure.
4. **Resolve UNKNOWN by reading, never by repeating.** Read the provider's own record (e.g.
   `PaidDate`). Believe "not done" only after repeated reads spaced apart, then abandon that
   provider object for good; a new attempt needs a fresh approval.
5. **Never exceed the approval.** Re-check the exact price before executing. If the provider's
   object costs more than approved, don't pay.
6. **Reject stale execution.** Fingerprint what was approved (items, address, package,
   service, price). If anything changed between preview and execute, stop. Build the provider
   request from the approved snapshot, not from state re-read later.
7. **Separate reprint from repurchase.** Reprint and resend read stored artifacts only. They
   must have no code path to the purchase or payment calls.
8. **Unattended paths never pay.** Timers, reconcilers and webhooks may finish or collect what
   was paid; they never start or retry a payment.
9. **Contain unexpected errors.** Any exception after the side effect may have happened maps to
   UNKNOWN, never to "failed", and must not stop other operations' reconciliation.
10. **Keep evidence.** Provider ids, amounts, timestamps and who approved, on the record's
    timeline. Never log secrets or access hashes.
11. **Say it plainly.** Staff see "paid for, collecting the label", "checking with the
    provider, don't buy again", never a bare "failed".

## Tests every such change needs

A lost reply after the side effect (exactly one charge), a double click (same key and new key),
a stale fingerprint, a definite refusal then a retry, reconciliation both ways (paid and
confirmed unpaid), a crash between each saved state, and reprint never reaching the provider.
Break the safeguard on purpose and confirm the test fails. See `testing-standard`.
