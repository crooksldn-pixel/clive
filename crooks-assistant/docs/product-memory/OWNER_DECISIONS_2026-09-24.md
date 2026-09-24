# Owner Decisions - 2026-09-24

Recorded from the owner's explicit statements in the Opus 5.5 engineering session.

## Judgment evidence retention (Gate C of the 2026-09-21 decision packet)

Keep redacted rich judgment evidence (the owner's redacted explanation and edited deltas) for 90 days on a rolling basis. Keep the structured record permanently: decision (APPROVED, DECLINED, EDITED, DEFERRED), action class, reason code and proposal fingerprint. Nothing learned from judgments becomes a durable preference until the owner confirms it. Expiry is never a decline.

## Gmail runtime credential

Provisioned by the owner on the production host on 2026-09-24 for team@crooksldn.com. The refresh token is stored in the Linux secret store outside every checkout; a fresh-process verification confirmed unattended refresh. Scopes: gmail.modify and gmail.compose. Production writes remain governed by the existing action gate.

## Operational alpha promotion

Authorised: promote the repaired operational alpha to production once the exact successor SHA passes full repository acceptance and an independent exact-SHA review, using an explicit deploy with a prepared rollback and a post-deploy health check.

## Generative UI V1

Approved as specified in GENERATIVE_UI_V1.md, including user-facing settings, reduced chrome and density, the microphone permission fix and the capability-gap bridge as its own objective track.
