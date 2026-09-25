# Owner Decision Packet — 2026-09-21

> **Status as of 2026-09-25 (consolidation note; the packet below is kept as written):** Gate C was decided by the owner on 2026-09-24 (90-day rolling redacted rich evidence, permanent structured record; see OWNER_DECISIONS_2026-09-24.md). Gate A was overtaken by the remote engineering loop, which now runs the event-driven engineering runtime (CURRENT_TRUTH.md). Gate B has no recorded owner decision: CLIVE writes remain governed by the existing action gate.

**Purpose:** keep owner-only choices explicit while repository-only engineering continues unattended.

This packet is intentionally short. Anything not listed here should continue under existing safe engineering authority if it is bounded, repository-only and already covered by product doctrine.

## Gate A — Event-driven control-plane runtime trial

**Decision required:** whether to authorise an isolated runtime/watcher trial once the repository foundation is independently accepted and the progress/event layer has been reconciled onto it.

**Recommended default:** **YES, after the acceptance conditions below are met.**

Acceptance conditions before asking the owner to approve installation/runtime modification:
- Phase 1 repair has a fresh independent exact-SHA ACCEPT verdict;
- observable-progress work is reconciled onto that accepted base;
- duplicate dispatch, stale SHA, owner-gate, obsolete revision, reviewer-independence and starvation scenarios pass in isolation;
- rollback/removal path is documented;
- no new secrets, credentials, connectors, permissions or public exposure are required;
- production CLIVE/business writes remain unchanged.

**What can continue without this decision:** all repository-only implementation, tests, review, replay and documentation.

## Gate B — First real CLIVE business-write trial

**Decision required:** whether to enable exactly one reviewed low-risk/reversible business action class for a controlled real-use trial.

**Recommended default:** **DO NOT ENABLE YET.** First implement and independently review explicit owner judgment capture (DEC-056 / IDEA-059), then choose the action class and its rollback/verification conditions.

Candidate once ready: a narrow order-note action **only if** its exact write, verification and undo/recovery semantics are independently proven suitable for the trial.

The trial should not enable broad writes or grant blanket autonomy.

**What can continue without this decision:** Judgment Ledger design/implementation in repository-only isolation, action UX for APPROVED/DECLINED/EDITED/DEFERRED, observability metrics, tests and safety review.

## Gate C — Judgment evidence retention policy

**Decision required before rich real-world capture:** whether optional redacted free-text owner explanations / edited deltas may be retained, and for how long.

**Recommended default:** keep the action audit ledger content-minimised permanently; implement the separate Judgment Ledger with structured reason codes now; keep optional rich/redacted explanation capture configurable and **off by default** until the owner chooses retention.

Suggested owner choices when ready:
- structured-only;
- redacted rich evidence with short rolling retention;
- redacted rich evidence retained as durable business-learning data.

No timeout/expiry may be treated as a decline under any option.

## Not an owner gate

The following are already authorised engineering directions and should not wait:
- park the unrestricted-English prose-freeze parser loop;
- repair/review the typed Engineering Control Plane Phase 1;
- reconcile observable progress after Phase 1 acceptance;
- continue CLIVE Live Experience V0.5 repository-only work;
- remove user-facing Split entry points while preserving internal/legacy concurrency machinery;
- build tests/evidence and prepare the next exact-SHA review.

Production deployment/promotion remains separate from repository acceptance.
