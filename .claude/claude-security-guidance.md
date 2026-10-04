# Project security rules: CROOKS Shopify sister apps

Python/FastAPI services embedded in Shopify admin, with a customer portal behind the Shopify app
proxy and a bearer-key API for CLIVE. Flag violations of these in addition to the built-in
classes.

- **Admin requests** must verify the App Bridge session token (HS256 with the app secret,
  `aud` = API key, `dest` = the shop, `exp`/`nbf`) before any data or action. A dev bypass flag
  must never be on in production settings.
- **App proxy requests** must verify Shopify's `signature` (HMAC-SHA256 over the sorted query)
  with a constant-time compare, and reject stale timestamps.
- **Webhooks** (Shopify, Parcel2Go) must verify the HMAC over the raw body before parsing, with
  a constant-time compare, and ignore replays (event id stored).
- **Tenant isolation:** every query and every stored record is scoped by shop. An id from
  another shop gives 404, never data.
- **Customer portal:** a return or order is shown only after the order number and a proof
  (email or postcode) match. Lookups are rate-limited and don't reveal whether an order exists.
- **Secrets** (Shopify app secret, Parcel2Go client secret, API keys, session secret) come from
  the environment only. They are never in code, tests, logs, error messages, timelines or
  responses. Parcel2Go order refs carry an access hash: show the order number only.
- **Logging:** no customer PII beyond what is needed (no full addresses, emails or phone
  numbers at info level) and no request bodies containing tokens.
- **SSRF:** outbound HTTP only to configured provider base URLs and to label links returned by
  that provider. Never fetch a URL taken from a customer or webhook payload without an
  allowlist.
- **SQL:** parameters only, never string-built queries.
- **Money-moving actions** (labels, refunds, credit, payments) require a staff identity, an
  idempotency key and a durable ledger row written first. An unattended path must not pay.
- **CSRF:** state-changing admin routes accept only the session-token bearer header, never
  cookies alone.
- **Signed file links** expire and are tied to one file id.
