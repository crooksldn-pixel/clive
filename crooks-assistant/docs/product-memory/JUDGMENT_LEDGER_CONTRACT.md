# OwnerDecision and Judgment Ledger Contract

Status: repository-only P0 design contract. This document grants no production, deployment, business-write, or autonomous approval authority.

## Separation of concerns

`ActionStatus` is operational lifecycle only. Human judgment MUST NOT be encoded as an operational action status.

`OwnerDecision` is a separate decision record with exactly these V1 values:

- `APPROVED`
- `DECLINED`
- `EDITED`
- `DEFERRED`

`EXPIRED` is not an OwnerDecision. Expiry means UNKNOWN / no owner decision and MUST NOT be counted, trained, reported, or inferred as a decline.

## Immutable proposal rule

A proposal is immutable once presented for owner judgment. `EDITED` MUST preserve the original proposal and create a new immutable superseding proposal. The replacement links to the original by stable proposal/action/task identity; it never overwrites the original payload.

Approval of an edited replacement applies only to the replacement proposal fingerprint. It MUST NOT retroactively approve the superseded proposal.

## Append-only Judgment Ledger

Judgment learning uses a separate append-only, content-minimised ledger. It is not the operational action/audit ledger and must not cause production writes merely to collect training evidence.

Each ledger entry MUST contain only bounded/redacted fields:

- stable `judgment_id`
- `task_id` and, where applicable, task revision / attempt identity
- stable `action_id` and `proposal_id`
- `proposal_fingerprint` (cryptographic digest of the judged immutable proposal)
- optional `supersedes_proposal_id` and replacement/delta fingerprint for `EDITED`
- `decision`: one of the four OwnerDecision values above
- bounded `reason_code` from a versioned allow-list
- optional redacted explanation or minimal redacted delta/snapshot; never raw secrets, credentials, hidden prompts, chain-of-thought, or unrestricted business content
- owner/principal provenance sufficient to establish who made the decision without embedding credentials
- decision timestamp
- `redaction_version`
- ledger schema version

Entries are append-only. Corrections are new entries that reference the prior judgment; existing entries are never silently mutated or deleted by normal application logic.

## Fail-closed invariants

A judgment entry MUST be rejected when:

1. the decision value is unknown;
2. proposal/action/task identity is missing or inconsistent;
3. the proposal fingerprint does not bind to the proposal being judged;
4. `EDITED` lacks a distinct superseding proposal identity and replacement/delta fingerprint;
5. a replacement attempts to overwrite the original proposal;
6. an approval is replayed against a different proposal fingerprint;
7. owner/principal provenance is absent or malformed;
8. the reason code is outside the bounded versioned vocabulary;
9. the redaction/schema version is unsupported;
10. an expired/no-response state is presented as `DECLINED`.

## Required adversarial tests

Implementation acceptance requires tests proving at minimum:

- `ActionStatus` cannot represent APPROVED/DECLINED/EDITED/DEFERRED;
- EXPIRED/no-response remains UNKNOWN and is not counted as decline;
- EDITED preserves the original immutable proposal and creates a superseding proposal;
- approval cannot be replayed across proposal fingerprints;
- malformed/missing provenance fails closed;
- unbounded reason codes fail closed;
- ledger append cannot mutate a previous entry;
- duplicate judgment IDs are rejected or idempotently resolve to the byte-identical existing entry, never create divergent history;
- redaction forbids secrets/credentials/hidden prompts/chain-of-thought fields;
- collection of negative evidence does not itself execute or authorise the underlying action.

## Authority boundary

The Judgment Ledger records owner judgment; it does not create it. No ledger entry, metric, model inference, expiry, historical pattern, or future `AUTO_APPROVED` mechanism may substitute for an owner-only gate unless a separately reviewed and explicitly owner-approved autonomy policy grants that authority. `AUTO_APPROVED`, if introduced later, requires its own policy/version/provenance contract and is not part of this V1 decision enum.