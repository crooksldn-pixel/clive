# Dev Team V1 — contracts and first acceptance trial

**Status:** PROPOSED — specification only, no dispatch or implementation approval  
**Date:** 2026-09-19  
**Parent:** ENGINEERING_ORCHESTRATOR_V1.md; DEC-046  
**Concrete evidence:** BUILDER_ENVIRONMENT_REVIEW.md

## 1. What the first trial must prove

An engineering request must survive task revision, worker failure, missing evidence, independent rejection and integration without losing authority or asking the owner to carry messages.

Use the demonstrated Builder Environment defects as a frozen, offline challenge. They provide unambiguous outcomes and exercise the foundation future workers actually need.

There are two separate uses:
- **Foundation repair now, after current round reconciliation:** the existing single-worker engineering process can repair the candidate. This does not demonstrate that Dev Team V1 exists.
- **Orchestrator acceptance later:** after implementation is authorised at the roadmap gate, run a disposable trial from the frozen broken candidate, or an equivalent fixture, through the complete V1 lifecycle. Never revert the live builder to create the test.

The first meaningful UI trial follows this mechanical acceptance trial. The Mobile Experience task already in the bridge is existing work; do not duplicate it or retrospectively claim it used Fable/independent orchestration. A later bounded UI follow-up can become the experience trial after its actual candidate and current owner design decisions are reviewed.

## 2. Durable records

| Record | Immutable identity and contents | Who can create or advance it |
| --- | --- | --- |
| Objective | owner intent reference; desired outcome; exclusions | Director, from authorised intake |
| TaskRevision | task/revision ID; exact base/context/environment; scope; risk; proof; escalation; authorisation reference | Director/planner proposal, accepted through policy |
| Attempt | task revision; worker/session/model; workspace; start/end; resource budget; lease/fencing identity | Scheduler/runner |
| Candidate | task revision; base SHA; candidate SHA; full diff digest; evidence manifest digest | Validated collector; never accepted by its author |
| Review | reviewer identity/independence; subject SHA and evidence; findings; required dispositions | Reviewer through validated result channel |
| Integration | target SHA; accepted inputs; integration SHA; extra edits; fresh evidence | Integrator |
| DirectorDecision | exact integrated subject; evidence; conditions; accept/reject rationale | Independent GPT Director |
| ReleaseRequest | artifact digest; target environment; preconditions; required approval; health/rollback plan | Separate release process; no V1 installation authority |

Operational records live durably outside model context. Read-only Git manifests may reference them; credentials and private transcripts do not enter those manifests.

A task revision change invalidates a previous assignment. A candidate change invalidates candidate-bound reviews. A changed integrated tree invalidates integrated evidence unless an explicit dependency-aware reuse rule proves relevance unchanged.

## 3. Proposed foundation repair task

| Contract field | Proposed value |
| --- | --- |
| Task ID | ENV-REPRO-001 |
| Status | PROPOSED; dispatch blocked on current-round reconciliation |
| Objective | Reconstruct a pinned Builder environment from a clean isolated checkout and make its validation truthful |
| Base SHA | 9a27bc441adad1e98e8a9ca257d1883246ee7eec; re-plan explicitly if a different base is chosen |
| Evidence | BE-01 bootstrap TypeError; BE-02 false-success doctor; BE-03 shell substitution; BE-04 incomplete reconstruction |
| Scope | scripts/dev_env.py; docs/dev-environment/manifest.json; directly related reproducibility inputs/docs; targeted tests/test_dev_env.py or equivalent |
| Excluded | product UI/backend/action semantics; production checkout; system services; secrets; live business APIs; .claude permission workarounds |
| Architecture | Opus resolves installer versus plan/executor contract and integrity/path rules |
| Implementation | Opus for unresolved security/bootstrap decisions; Sonnet only once the task is bounded with accepted contracts |
| Required review | Independent technical/QA and shell/security review; Director acceptance of integrated evidence |
| Fable | Not required for this environment-only task; required later for meaningful experience work |
| Environment | Disposable builder sandbox; no existing ignored tool state assumed |
| Integration | Exact accepted candidate into an isolated target; no production promotion |
| Completion | Required cases below pass, original failure evidence retained, actual fresh build and idempotence proved |
| Stop conditions | Missing native permission; unapproved host changes; unavailable artifact integrity evidence; scope conflict; repeated failure |

The task must identify an allowed package-fetch policy before network reconstruction. Unavailable approved access produces BLOCKED, not permission to bypass the boundary.

## 4. Acceptance cases

| Case | Required observation |
| --- | --- |
| Committed manifest | Metadata is handled without crash; malformed tools fail clearly |
| Missing required executable | Validation fails with precise name and reason |
| Wrong version / failed probe | Validation fails even if the path exists |
| Advisory source lint | Remains advisory where policy explicitly says so |
| Shell metacharacters | Environment round-trips literally; no interpretation of path contents |
| Empty tool output tree | Required inputs can be reconstructed without hidden files |
| Integrity mismatch | Download/install stops; no partially verified tool accepted |
| Interrupted bootstrap | Safe resume or actionable failure; no false-ready status |
| Second bootstrap | No unintended artifact/version changes or repeated destructive work |
| Required browser evidence | Browser starts, interacts with a fixture, captures artifacts and exits cleanly |
| Candidate identity | Tests and screenshots identify exact code/environment; stale evidence rejected |
| Permission refusal | Task blocks without alternate-path escalation or blanket permissions |
| Production boundary | Sandbox denies out-of-scope mutation; proof covers actual enforcement |

Network/package rebuild evidence is a separate class from offline unit tests. Report both explicitly. Unit tests alone cannot prove a server can be recreated.

## 5. Independent review contract

Review requests contain the frozen task, actual base/candidate diff, raw evidence references, changed tests, known limitations and policy—not just a worker summary.

Each finding records:
- stable finding ID, severity and affected active contract;
- code/evidence location;
- reproduction or clearly labelled inference;
- requested outcome;
- disposition, resolver identity and follow-up proof;
- exact candidate on which it was resolved.

The reviewer returns ACCEPT, CHANGES_REQUIRED or BLOCKED with unresolved findings. The kernel validates required reviewers and subjects before allowing ACCEPTED.

For this trial, deliberately submit at least one false-green result (for example doctor exit 0 with mismatched tooling). The pipeline must reject it. A trial that only demonstrates the happy path is insufficient.

Corrections create a new candidate. The implementer cannot edit the review record to close a finding. A reviewer who supplies an implementation patch does not independently certify that patch.

## 6. Recovery and delivery contract

Distinguish four facts: process exited; candidate persisted; evidence validated; result published.

Use task revision + attempt ID + fencing token for result admission. Candidate/evidence publication has its own idempotency key and persistent delivery state.

Fault-injection trial:
1. kill the coordinator after assignment; recover without a second writer;
2. finish a build, then fail publication; retry delivery of the same result without rebuilding;
3. let remote publication succeed, then lose the response; read back identity before retry;
4. cancel an attempt, then submit a late result; reject the stale token;
5. change a required context/contract during review; block stale acceptance;
6. combine two accepted candidates with a semantic conflict; integration must catch it;
7. remove a required evidence artifact; release-candidate creation must fail closed.

Persist failures and distinguish application attempts from delivery attempts. Retries must not erase an earlier failed test or reset the escalation budget.

## 7. Owner experience

The normal completion is a short decision-ready result: what improved, what evidence proves it, what remains uncertain, and whether a release decision is needed.

The owner does not select worker IDs, run unit tests, copy prompts or repair routine publications. Detailed records remain available for inspection.

A missing capability is presented with a concrete remedy once investigated. Do not label the team fully automated while Fable, GPT invocation or secure runner credentials still require unimplemented adapters.

## 8. Exit gate

Before the first V1 release candidate:
- task records survive restart;
- the incorrect candidate is rejected for the right reason;
- a correction is independently reviewed against fresh evidence;
- integrated proof covers the exact final tree;
- permission and deployment boundaries remain enforced;
- no owner courier work was needed;
- no production installation occurred.

This specification sets proposed acceptance requirements. It does not authorise implementation before the current-product sequence or displace the current Mobile Experience round.
