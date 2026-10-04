# Review rules for the sister apps

A stage is reviewed after it is implemented and before it is called done. Passing tests show the
tests pass; review asks what the tests don't cover. Findings are about real behaviour, ranked by
harm.

## Money-moving and side-effecting operations (look here first)

Label purchases, refunds, store credit, exchanges, provider payments, Shopify fulfilments and
emails to customers:

- **Durable state before side effects.** The intent (ledger row, reference, idempotency key) is
  written before the provider or Shopify call. A crash between the call and the save must not
  lose the fact that money may have moved.
- **Idempotency.** The same key replays the stored result. A new key while an operation is
  open is refused, not executed. Look for anything that can run twice: double clicks, retries,
  webhooks delivered twice, the timer racing a staff action.
- **Timeout ambiguity.** A lost reply to a write means "unknown", never "failed". Unknown is
  resolved by reading back (e.g. Parcel2Go `PaidDate`), never by repeating the write.
  Parcel2Go charges again when a paid order is paid again.
- **Never pay more than authorised**, and never pay from an unattended path (timers, reconcile)
  unless the owner has explicitly allowed it.
- **Stale previews.** What staff approved (price, items, address, package) is fingerprinted;
  a change between preview and execute stops the action.
- **Reconciliation.** Every state that says "money may have moved" has an automatic way back to
  a known state and a clear message for staff. Nothing waits silently for a human.
- **Honest wording.** The UI and customer messages say what actually happened: "paid for, will
  be sent", not "failed"; duties "may be charged", never "prepaid" unless they are.

## Everything else

- Correctness and unintended behaviour, including edge inputs (empty, zero value, missing
  email/phone, non-UK addresses, partial fulfilment orders).
- Race conditions between the request path, the timer and webhooks; locking around
  read-modify-write.
- Shopify API use: the operation is validated against the current schema (see CLAUDE.md), the
  scopes are declared, and `userErrors` are handled.
- Error handling: no swallowed exceptions, and no exception type that skips the code that
  records the reference.
- Missing tests, especially the failure case that the change exists for. A good test fails
  without the fix (try reverting it).
- Backwards compatibility of stored data, API responses, webhooks and settings.
- Security (see `.claude/claude-security-guidance.md`).
- Maintainability: matches the surrounding code; no speculative abstractions.
- UX: the merchant's next step is obvious; problems surface once, plainly.
