# Final implementation plan

**Status:** DRAFT TEMPLATE — must be rewritten after repo/host audit and independent plan review.

The final plan is a sequence of independently reviewable, reversible PRs. Do not begin implementation while this document is still marked draft.

For each PR use this shape:

## PR N — <title>

### Problem
What measurable limitation exists now?

### Existing machinery reused
Which CLIVE components are extended rather than replaced?

### Scope
Expected files/modules and state changes.

### Out of scope
What must not be changed.

### Acceptance
Concrete independently checkable criteria.

### Tests/evidence
Focused tests, integration, browser, Bench, exact-SHA, review as applicable.

### Owner-visible payoff
What George notices in quality, speed or attention.

### Risk
Failure/security/migration risks.

### Rollback
How to return to the previous behavior safely.

### Dependencies
Earlier PRs/runtime facts required.

### Metrics
How we know the PR improved the system.

---

## Required final sections

### NOW
Smallest set required to establish reliable project-level autonomy.

### NEXT
Useful improvements after V1 is measured.

### LATER
Optimizations whose value depends on data.

### DO NOT BUILD
Explicitly rejected complexity.

### Final GO / REVISE / STOP
A recommendation based on evidence, not optimism.
