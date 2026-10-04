---
name: testing-standard
description: What tests a sister-app change needs before it is called done. Tests target failure modes, not line coverage. Use when writing tests for integrations, money-moving or state-changing code, webhooks, or before claiming a feature complete.
---

# Testing standard

A test suite is judged by the failures it would catch. For each change, list what can go wrong
and prove the system's behaviour in each case.

## External integrations: cover the ones that apply

- timeout **before** the request reached the provider; timeout **after** the side effect happened
- duplicate request; retry after a definite refusal
- provider 4xx, provider 5xx, malformed or non-JSON body, 200 with errors inside
- stale state: the order, price or address changed between preview and execute
- webhook duplicate, webhook missing (reconciliation covers it), webhook with an invalid signature
- Shopify failure after provider success (paid, but fulfilment failed); provider success after
  Shopify state changed (order cancelled meanwhile)
- user double click: same idempotency key, and a different key while one is open
- partial completion: a crash between each saved step, then reconcile
- reconciliation both ways: confirmed done, and confirmed not done

## How

- **Fakes that misbehave like the real thing.** A fake provider charges again on re-pay, can
  lose the reply after charging, can lag on read-back, and can return garbage.
- **Assert on effects, not calls.** Count charges, orders, emails and fulfilments; check the
  stored state and the message staff will see.
- **Break the safeguard on purpose.** Remove the read-back, the unique index, the fingerprint
  check, or the read-before-write, and confirm the relevant test fails. A test that passes
  either way proves nothing.
- **Sandbox proof for provider facts.** When a sandbox exists, run the real flow once and record
  the evidence: ids, amounts, document page sizes.
- **Done means verified.** Run tests, lint and format, and type checks on touched files; then
  check the real UI or API (see `shopify-native-ui`), and state what was not verified.
