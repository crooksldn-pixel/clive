# Human-attention contract

## Objective

George should direct engineering, not operate the agents.

## Allowed owner interruption classes

### PRODUCT_DECISION
Two materially different valid outcomes require George's preference.

### PERMISSION_CHANGE
The implementation changes who or what may read, write or approve something.

### SECURITY_DECISION
A genuine security trade-off requires owner authority.

### IRREVERSIBLE_OPERATION
A migration/destructive action cannot be safely undone within the approved plan.

### CREDENTIAL_REQUIRED
An external system cannot proceed without a credential or connection George controls.

### REQUIREMENT_AMBIGUITY
The requested outcome cannot be faithfully inferred from repository/current context.

### EXTERNAL_BLOCKER
A third-party approval, outage or inaccessible dependency prevents progress.

### REPAIR_LIMIT_REACHED
Autonomous bounded repair is exhausted.

Everything else should normally remain internal engineering status.

## Not owner interruptions

Do not interrupt George merely because a test failed, CI failed, a reviewer requested a bounded repair, a worker crashed and can safely retry, a branch needs a defined rebase, or browser evidence exposed a reproducible implementation defect.

## Batching

Non-urgent decisions should be presented together. The default owner view is project, status, progress and needs-you. Objective DAG, reviewer findings, tests, SHAs, worker ids and raw logs are progressive disclosure.
