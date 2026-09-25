# Review Acceptance Contract

Status: repository-only candidate contract. This document does not accept, deploy, promote, or activate any candidate.

## Purpose

Bind final engineering acceptance to an exact immutable candidate and an operationally independent reviewer. A fresh context, model change, or workspace alone cannot launder the candidate author into an eligible reviewer.

## Required identities

Every review assignment and verdict MUST record:

- `task_id`
- `attempt_id`
- `candidate_sha`
- `candidate_task_version`
- `author_principal_id`
- `reviewer_principal_id`
- `reviewer_session_id`
- `reviewer_workspace_id`
- `reviewer_workspace_read_only`
- `reviewer_workspace_clean`
- `observed_candidate_sha`
- `verdict`
- `evidence_fingerprint`
- `reviewed_at`

Cognitive-diversity metadata (provider/model/deterministic verifier/human) MAY be recorded as additional evidence but MUST NOT satisfy operational independence.

## Eligibility

Final acceptance MUST fail closed unless all are true:

1. reviewer principal differs from author principal after canonical identity normalisation;
2. reviewer session is fresh and distinct from the authoring session;
3. reviewer workspace is isolated, clean, and candidate read-only;
4. reviewer has no candidate mutation capability during review;
5. `observed_candidate_sha == candidate_sha` at review time;
6. task/version identity matches the assignment being reviewed;
7. evidence is well-formed and its fingerprint verifies;
8. verdict is explicitly `READY`.

Self-review and same-principal fresh-context review are R0/adversarial evidence only and MUST NOT produce final acceptance.

## Fencing and stale evidence

Acceptance MUST reject rather than reinterpret:

- branch movement after dispatch;
- candidate SHA drift;
- task-version drift;
- verdicts for superseded attempts;
- late results from a prior attempt;
- malformed/missing provenance;
- duplicate final verdicts;
- reviewer self-certification;
- evidence fingerprints that do not recompute exactly.

A rejected/stale verdict cannot be carried forward to a successor SHA. A successor requires a fresh eligible review.

## Owner boundary

Engineering `READY` is not owner adoption, production promotion, release authorisation, business-write authority, or permission to modify systemd/watcher/runtime state. Those remain separately gated.

## Required executable attacks

The dispatch/acceptance implementation is not complete until automated tests prove at minimum:

- same principal + fresh session/workspace is rejected;
- same principal + different model/provider is rejected;
- distinct eligible principal on exact SHA can be selected;
- SHA drift between dispatch and verdict is rejected;
- task-version drift is rejected;
- late/superseded-attempt result is rejected;
- duplicate final verdict is rejected;
- writable/dirty reviewer workspace is rejected;
- malformed evidence and fingerprint mismatch are rejected;
- `READY` from an eligible reviewer does not cross the owner/deployment gate.

Mutation testing should remove or invert each guard and demonstrate that the corresponding test fails.

## Current known candidate

`e8830c44bcae917b7c711b081a8adf003832bc9d` remains **NOT independently accepted** until an eligible reviewer executes the exact-SHA review under this contract. This document must not be interpreted as acceptance of that candidate.
