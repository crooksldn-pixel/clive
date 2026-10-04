---
name: provider-integration
description: How to integrate an external API or provider (Parcel2Go, PrintNode, Resend, tracking providers, future carriers or services) into a sister app. Use when adding or changing a provider adapter, its error handling, webhooks, sandbox checks, or the internal model it maps to.
---

# Provider integration

Assume the provider is not safe by default: it may double-charge, lag, return HTML, change
shapes, or answer 200 with errors inside.

## Shape

- **Internal model first.** The app speaks its own types (ISO country codes, integer minor-unit
  money, our document kinds, our statuses). The adapter is the only place that knows the
  provider's names, codes, units and quirks, and it translates at the boundary.
- **A port, not a client.** Define the operations the app needs (quote, verify, create, pay,
  read back, documents, cancel, tracking) as a protocol, with a fake that behaves like the real
  one, including its dangerous behaviour.
- **Capabilities explicit.** Record what the provider can't do (no void, no idempotency key,
  documents per service) as data the app can show, not as hidden assumptions.

## Checklist

- **Auth:** where the credential lives (server environment, never chat or repo), token expiry
  and refresh, sandbox versus live base URLs, and a guard that refuses live in test scripts.
- **Reads versus writes:** classify every call. A failed read never moves money; a write whose
  reply is lost is UNKNOWN (see `transaction-safety`).
- **Error normalisation:** map every outcome to *refused* (definite no, actionable message),
  *unavailable* (never delivered, or a read failed), or *uncertain* (a write that may have
  happened). Malformed or non-JSON bodies are classified too; no raw `KeyError` or `ValueError`
  escapes the adapter.
- **Identifiers:** store the provider's ids and any access hash needed to read the object back;
  show staff only the plain id.
- **Retries and rate limits:** retry reads with backoff; never auto-retry a non-idempotent
  write. Respect rate-limit headers.
- **Webhooks:** verify the signature over the raw body with a constant-time compare, reject
  stale timestamps, store event ids to ignore replays, and have reconciliation cover any webhook
  that never arrives.
- **Versioning:** pin the API version; note the date it was verified.
- **Health:** a cheap read (balance, account) for a setup screen, without side effects.

## Evidence over assumption

When a sandbox exists, test the behaviour that matters before relying on it: re-paying,
timeouts, document formats, page sizes, regional pricing, required fields. Record what was
proven, with dates, in the app's design document. Use current official docs (Context7 or the
provider's own spec) for anything version-sensitive. List what only a first live transaction
can confirm.
