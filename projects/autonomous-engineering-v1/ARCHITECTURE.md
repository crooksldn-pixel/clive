# Target architecture

## Principle

Add the missing control layers around CLIVE's engineering kernel. Do not replace the kernel.

## Control flow

Owner
→ Claude Desktop / SSH supervisor
→ current-truth inspection, external research, owner clarification, project drafting
→ project specification compiler
→ owner intent + acceptance + risk + skills/context + objective DAG
→ existing CLIVE dispatcher
→ dependency readiness + priority + path/resource constraints
→ isolated builders
→ candidate SHA
→ sandboxed checks
→ browser/Bench when required
→ exact-SHA GitHub acceptance
→ fresh independent reviewer
→ READY or bounded repair
→ trunk
→ evidence synthesis
→ owner deployment decision.

## New durable Project layer

A Project sits above individual engineering objectives. It stores project id, title, owner intent, risk class, state, base SHA, acceptance contract, owner decisions, objectives, dependency edges, required skills/context, blockers, evidence, final candidate/trunk state, and a separate deployment state.

The Project does not execute code. It coordinates existing objectives.

## Suggested project states

DRAFT, READY, RUNNING, NEEDS_OWNER, VERIFYING, REVIEWING, ACCEPTED, ON_TRUNK, BLOCKED, CANCELLED.

Deployment is deliberately not a Project completion state.

## Dependency semantics

An objective is runnable when all required predecessors are complete/accepted under the existing lifecycle, no owner/project hold exists, declared path/resource constraints allow it, and dispatcher capacity exists.

V1 needs correct dependencies and bounded concurrency, not a sophisticated optimizer.

## Risk classes

S0 trivial/test/docs/local repair.
S1 ordinary bounded change.
S2 cross-component feature.
S3 external integration or architectural change.
S4 security, permissions, money, destructive data or deployment infrastructure.

Risk class controls required evidence and owner involvement. It never grants additional authority.

## Supervisor boundary

Desktop supervisor may read source/state, research, draft project packets, ask owner-only questions, submit approved requests, read evidence and explain blockers. It must not be the only process holding durable project state and must not bypass the loop to land or deploy application code.

## Durable-worker boundary

The existing dispatcher owns attempts, workspaces, worker sessions, check execution, review dispatch, repairs and integration/landing where already authorized. A dropped SSH session should be operationally irrelevant after work is filed.
