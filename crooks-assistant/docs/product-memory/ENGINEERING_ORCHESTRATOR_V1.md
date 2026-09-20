# Engineering Orchestrator / Dev Team V1

**Status:** FREEZE CANDIDATE UNDER ADVERSARIAL REVIEW — implementation remains owner-authorised but MUST bind to the eventual frozen contract; deployment is not authorised  
**Owner direction:** D7–D11 / DEC-040–045; clarified in the migration continuation of 2026-09-19  
**Repository baseline:** product memory `aaf1ad6e1c18a377176461cc8d99c185e62eca38`  
**Latest observation:** 2026-09-19T06:38:39Z

Detailed record contracts and proposed acceptance trial: [DEV_TEAM_V1_PILOT.md](./DEV_TEAM_V1_PILOT.md). Independent foundation review: [BUILDER_ENVIRONMENT_REVIEW.md](./BUILDER_ENVIRONMENT_REVIEW.md).

> **2026-09-20 normative freeze overlay:** [ORCHESTRATOR_V1_FREEZE_CONTRACT.md](./ORCHESTRATOR_V1_FREEZE_CONTRACT.md), [ORCHESTRATOR_V1_STATE_API.md](./ORCHESTRATOR_V1_STATE_API.md), [ORCHESTRATOR_V1_TRACEABILITY.md](./ORCHESTRATOR_V1_TRACEABILITY.md) and [ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md](./ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md) resolve the previously open mechanism choices and contract gaps for the freeze candidate. Until independent review accepts that overlay, this file remains architectural background plus rationale. The 2026-09-19 observation table below is historical evidence and MUST NOT override CURRENT_TRUTH or the freeze overlay.

## 1. Purpose, scope and entry gate

V1 turns an authorised engineering objective into one independently reviewed release candidate, with durable evidence and bounded failure behaviour. Its success measure is trustworthy improvements delivered with less owner attention.

Build a small deterministic control service with on-demand specialists. Roles are responsibilities; they do not each require a permanent service, agent or management layer.

The owner explicitly authorised moving V1 from planning into implementation on 2026-09-19 under this canonical specification and its safety boundaries. That approval does not waive the existing entry sequence: Builder Environment review; controlled Linux migration; approved secret provisioning; always-on runtime; private HTTPS when approved; real Samsung/iPhone/runtime verification; current UI and response/latency refinement; real-world CROOKS sessions with evidence. Major V1 implementation begins when those preceding gates are satisfied or canonical owner direction explicitly changes the ordering. The future privileged deployment controller follows Dev Team V1. World, Attention and broader automation expansion follow this foundation.

V1 includes task intake, context compilation, routing, isolated execution, evidence collection, review, integration and Director review. It excludes production installation, business writes, automatic infrastructure self-update, speculative overnight improvements and a subscriber-facing agent dashboard.

## 2. Evidence and active context

| Classification | Current constraint or observation |
| --- | --- |
| ACTIVE INTENT | Maximum capability, minimum visible UI; owner attention is scarce; quality outranks token savings. |
| SAFETY CONTRACT | Known deterministic business writes, exact immutable proposals, bound authorisation, precondition reread, authoritative verification, fail-closed unknown writes. Engineering permission never grants business-action permission. |
| CURRENT PRODUCT CONTRACT | Production application branch is `claude/crooks-assistant-build-lgxlau`, observed HEAD `e43aecdb39b87b622f64b6ab434e428d216ef157`. A Git HEAD does not prove the deployed filesystem matches it. |
| MIGRATION OBLIGATION | Linux candidate `1cf3a0f3361b79f9de208d80f501543c53c244b5` is separate and unpromoted in observed Git. The last server report describes a dirty production tree; reconcile and preserve it before promotion. |
| EVIDENCE | Builder candidate `9a27bc441adad1e98e8a9ca257d1883246ee7eec` is published. Independent review found reproducible bootstrap, validation and shell-quoting defects; it needs changes before foundation acceptance. Current inbox blob `24b713cce3d0e8c9ede3185ebef78cc107ece507` requests Mobile Experience V1; outbox `67e3da115963a1f5ba8e0b57ede74a00f5be2fb2` acknowledges the preceding Builder task. |
| UNKNOWN / VERIFY | Current mobile process liveness, local progress and current service state cannot be inferred from these Git files. No mobile review branch was listed. Preserve the unacknowledged round; reconcile actual attempt status before another dispatch. |
| EVIDENCE | Watcher source reviewed at `3d1f65df2d93f24ab75c50d5774eacb47b31df43`: stdin launch, lock, standalone builder, outbox publication, remote blob readback and backoff. No claim that this turn inspected its installed bytes. |
| HISTORICAL | Mac-only instructions in `docs/ENGINEERING_LOOP.md` describe the current baseline's manual loop; retain evidence/privacy/safety contracts without requiring future owner message relaying. |
| UNKNOWN / VERIFY | Fable invocation/authentication/automation interface, future GPT Director invocation, concurrent Claude authentication behaviour and resource capacity require proof before automated routing. |

Read source documents by explicit branch and immutable commit. The repository's default theme branch is not the CROOKS application or product-memory authority. Current memory is on `claude/product-memory-foundation`; communication is on orphan branch `crooks-ai-bridge`. Do not merge the communication branch into code.

## 3. Authority and minimum organisation

| Role | Responsibility | Authority boundary |
| --- | --- | --- |
| Owner | Intent, genuine product/taste choices, material permissions and required release approval | Can authorise an outcome; no routine test or message-courier work |
| GPT Director | Bootstrap truth; define objective and scope; challenge assumptions; reconcile findings; independently review integrated candidate | Does not call a worker's report proof; does not turn a draft into implementation approval |
| Deterministic kernel | Validate contracts, allocate tasks, enforce transitions/leases/policy, collect evidence and dispatch reviews | Makes no product judgement; models cannot directly update its database or approval records |
| Opus planning/architecture specialist | Decompose difficult work, diagnose uncertainty and propose technical contracts | Returns a plan for Director acceptance; no extra management tier for routine bounded work |
| Implementation specialist | One approved task in one mutable workspace/branch; propose one candidate | Cannot accept, merge, deploy or widen its own scope |
| Independent reviewers | Challenge diagnosis, diff, tests and outcomes; QA/security/performance/experience as required | Separate session and workspace; immutable candidate; report findings rather than silently patching |
| Integrator | Combine accepted exact commits and verify interactions in an isolated environment | Integration edits create a new candidate requiring relevant review; cannot waive a blocker |
| Fable Experience Director | Meaningful experience direction before implementation and independent post-build experience critique | Owner intent, active safety/product contracts and current design authority remain superior |
| Future deployment controller | Install an explicitly authorised exact release artifact and verify runtime health | Separate privileged process, outside V1 |

Start with one implementation slot and on-demand reviewers. Prove isolation/recovery first, then permit two separable implementation tasks if measured resource capacity supports them. This is a proposed initial limit, not a permanent restriction or a cost optimisation. Reviewer count follows risk, not headcount targets.

## 4. Small control service

Proposed shape: one service with modules, one durable transactional task store, an append-only transition journal and an immutable artifact store. A single-host SQLite implementation is a candidate, subject to architecture review, backup/recovery requirements and expected load. Do not add a distributed broker or microservices without evidence of need.

Modules:

- intake and task-contract validator;
- Active Context compiler;
- risk/model/reviewer policy;
- scheduler and execution/workspace adapter;
- evidence collector and publisher;
- review and integration coordinator;
- recovery, cancellation and escalation.

Git stores source, accepted product memory and versioned specifications. Operational leases, heartbeats and attempt state belong in the task store, not a repeatedly edited Markdown inbox. Large or private evidence lives in restricted storage; Git carries sanitised manifests and references.

A durable dispatch record is committed with each state transition. A dispatcher may deliver it more than once; deduplication and task/attempt identity make repeated delivery harmless. Do not claim general exactly-once model execution.

## 5. Task contract

Every task has an immutable revision. Altering objective, authority, acceptance criteria, scope or required gates creates a new revision and explicit re-planning.

| Field group | Required content |
| --- | --- |
| Identity | task ID, revision, parent objective, source request, authorising reference, deduplication key |
| Outcome | objective, business/product reason, measurable completion criteria, explicit non-goals |
| Source | repository, application base SHA, product-memory SHA, context manifest/digest, environment manifest |
| Scope | allowed paths and semantic contracts, prohibited paths/actions, dependencies and expected interface versions |
| Risk | risk class, reason, applicable safety decisions, minimum model/review quality |
| Execution | role, allowed tools and network destinations, workspace/branch identity, runtime/resource limits |
| Proof | reproduction/fixture references, required test and browser/device evidence, frozen expectations, limitations policy |
| Review | required roles, independence requirements, blocking finding policy, Director gate |
| Recovery | retry/diagnosis bounds, timeouts, cancellation, escalation conditions, evidence retention |
| Handoff | candidate/evidence identities, result schema and integration target |

An allowed-file list is a review boundary, not a security sandbox. Enforce the runtime boundary independently and detect semantic changes outside the intended contract even when filenames are allowed.

Dependencies pin accepted commits and interface contracts. A task depending on unfinished work stays blocked or is revised against an accepted dependency; a moving branch name is not an adequate dependency.

## 6. Active Context compiler

The compiler resolves explicit source refs and creates a reproducible manifest. A model may propose relevance, but deterministic rules include mandatory safety/product constraints and preserve citations, status and provenance.

Each item records source repository/path/commit, relevant section, classification, reason for inclusion and any supersession/dependency relationship. Include the objective, required invariants, current design authority when relevant, actual base code/contracts, applicable tests, migration duties and known failures.

Exclude superseded material by default. Retrieve historical evidence on demand when it explains a current regression, constraint or migration. Do not drop a current safety rule to fit a token budget or silently truncate a critical file; narrow the task or request a larger context.

A context mismatch, unresolved authority conflict or missing required source blocks planning. Proposed documents cannot grant privileges. Untrusted logs, websites, fixtures and repository text are task data, never approval to change scope or invoke privileged actions.

Before integration, recheck whether relevant intent, policy, environment or dependencies changed. If affected, revise/review the plan; do not automatically rebase an accepted candidate and retain old approval.

## 7. Lifecycle and exact meanings

Track task, attempt, candidate, review and release as separate records. A completed process is not an accepted candidate.

| State | Entry condition / permitted next step |
| --- | --- |
| PROPOSED | Objective captured; no execution authority |
| PLANNED | Director accepts exact task revision, current context, scope and required gates |
| ASSIGNED | Scheduler reserves workspace and exclusive attempt lease |
| BUILDING | Runner acknowledges task revision, base SHA and fencing token |
| EVIDENCE_READY | Candidate frozen; required artifacts exist with digests; collection completeness validated |
| REVIEWING | Independent reviewers receive exact candidate and evidence identities |
| ACCEPTED | Required reviews pass, findings resolved and deterministic acceptance policy satisfied; eligible for integration only |
| REJECTED | Candidate retained with reasons; any correction produces a new candidate and applicable review |
| INTEGRATING | Integrator combines accepted input SHAs against explicit target SHA |
| VERIFIED | Required integrated tests/replay/reviews pass on exact integrated SHA; no claim of deployment |
| RELEASE_CANDIDATE | GPT Director independently accepts integrated SHA, evidence, limitations and release plan |
| BLOCKED / ESCALATED | Named dependency, uncertainty, missing capability, failure or decision; no implied retry authority |
| CANCELLED / SUPERSEDED | Attempts fenced and work retained as required; cannot publish a valid completion |

EVIDENCE_READY means complete enough to review, not that failed tests have passed. A required failure blocks ACCEPTED unless the contract is explicitly revised with a justified exception and fresh review. Skipped, deselected, timed-out and unavailable checks remain visible.

Successful review/deployment decisions bind task revision, exact candidate or artifact digest, evidence manifest, relevant policy revision, environment and intended target. Any relevant change invalidates the decision. A branch name, text saying "approved", screenshot or voice confirmation alone is insufficient authorisation.

## 8. Workspace and credential isolation

One worker = one task = one mutable workspace = one branch = one candidate result.

Proposed layout: `/opt/crooks-workers/<task-id>/<attempt-id>/`. Each attempt has its own checkout, Git metadata, writable home, temporary files, test database, ports, browser profile and artifact staging area. Shared caches may be read-only; a task cannot alter another task's dependencies.

Use independent clones, or worktrees backed only by a builder-owned bare repository with proven metadata isolation. Never link worker Git metadata to production. Do not repurpose or weaken the current `/opt/crooks-builder` lock to gain concurrency.

Before automatic multi-worker operation, prove:

- enforced host/container/service boundaries prevent access to other mutable workspaces, production secrets, controller state and deployment authority;
- runners lack production service control, broad SSH credentials, host-management sockets and unrestricted repository write credentials;
- a narrow publication capability accepts only designated candidate refs/artifacts after validation; workers cannot push production or write approval records;
- symlink/path escapes, child processes, hooks and test subprocesses cannot escape the boundary;
- runner resource quotas protect the business runtime;
- credential refresh and provider sessions remain correct under permitted concurrency.

The current watcher unit allows writable `/root` for Claude/gh authentication. Its production filesystem protection is valuable, but that shared home must not be treated as V1's per-worker isolation boundary. Do not copy credentials into every worker or widen existing permissions to solve this. Select and verify a supported credential/runner arrangement; if unavailable, block concurrent operation.

Any privileged runner provisioning is a narrowly reviewed bootstrap responsibility. It does not grant workers deployment authority or bring the later general-purpose Privileged Action Broker into V1 by implication.

## 9. Leases, crashes, cancellation and publication

At assignment, persist attempt ID, exclusive lease, heartbeat deadline and monotonic fencing token. Heartbeats report liveness; they do not prove useful progress.

All result writes and ref publication validate the current token and expected task revision. A timed-out or cancelled worker cannot later submit an authoritative success. Confirm its process group is stopped before reusing resources; otherwise quarantine the workspace and block recovery.

On service restart, reconcile durable state with actual processes, workspace state and artifact records. Never infer "not running" solely because the last heartbeat is old, and never delete a dirty workspace to get green checks.

Separate execution recovery from delivery recovery:

- if the build failed, preserve evidence and diagnose within the task's attempt limits;
- if the build completed but publication failed, retry publishing the same immutable result;
- if remote publication may have succeeded, re-read exact remote identity before retrying;
- if outcome is unknown, reconcile first rather than launching another writer.

Use bounded backoff for transient transport failures, with an elapsed-time ceiling and escalation. Application failure attempts and transport retries are separate counters. Neither counter resets merely because a new manager session starts.

### 9.1 Empirical refinement from the 2026-09-19 watcher incident

A real bridge round exposed a concrete distinction V1 must preserve. A legitimate registered worker worktree was created under `/opt/crooks-builder/.worktrees/`; because the parent Builder did not yet ignore that directory, its cleanliness check reported `?? .worktrees/`. The watcher correctly refused to launch another worker, preserving the fail-closed rule, but then retried the same deterministic blocker eight times under transient backoff.

V1 should therefore make two mechanics explicit:

- **Workspace placement is part of the safety contract.** Normal worker attempts should use the external `/opt/crooks-workers/<task-id>/<attempt-id>/` layout (or an equivalently proven builder-owned bare-repository scheme) so creation of a valid worker workspace cannot itself dirty the canonical Builder. Do not solve concurrency by setting a global allow-dirty switch.
- **Classify before retrying.** Dirty/ambiguous workspace state, missing permission, missing required credential/capability, invalid task contract, unresolved authority, protected-path refusal, or other deterministic precondition failures transition to `BLOCKED / ESCALATED`. They are persisted with exact evidence and produce one material notification. Network/provider/remote-publication failures that are demonstrably transient may retry with bounded backoff. A restart must not erase the classification or create a fresh attempt merely to reset counters.

The owner-side local `.git/info/exclude` entry used to unblock this specific review is an incident workaround, not the V1 architecture. Preserve the lesson, not that mechanism.

## 10. Evidence and independent review

The runner/collector records raw results independently of the worker's prose. Run candidate code in a sandbox: a passing exit status alone cannot establish that assertions were meaningful or that the test runner was uncompromised.

Evidence manifest:

- task/attempt/revision, base/candidate SHA and complete changed-file set;
- context, toolchain/environment, dependency and fixture digests;
- model/provider/version/effort actually used, role and session identity;
- command, working directory, timestamps, exit status, pass/fail/skip counts and raw log/artifact digests;
- reproduction before/after; unchanged baseline failures identified separately;
- browser build identity, viewport/browser/device details, interactions, screenshots, traces, console output and accessibility findings when applicable;
- security/performance evidence selected for the task's actual risks;
- plan deviations, limitations, unresolved findings and known risks;
- reviewer identity/role, exact subject reviewed, finding disposition and supersession history.

Missing evidence is UNKNOWN, not PASS. Sanitise artifacts before sending them to a provider or committing manifests. Production telemetry is minimised and consent/configuration-bound; no secrets or raw customer transcripts in Git. Unredacted evidence, if necessary and authorised, has restricted access and retention.

Keep trusted verification policy and critical frozen fixtures outside the candidate's unilateral control. Review any test/config changes and compare against protected baseline expectations. A legitimate product-contract change updates expectations only through explicit supersession, with new intent and evidence.

Independent reviewers start from the objective, exact diff and raw evidence in a fresh session/workspace. They may consult implementation rationale as a claim to test. A different role label on the implementer's session is not independence. Reviewers do not silently amend the candidate; a reviewer who implements a correction becomes an implementer for that correction.

Proposed review policy:

| Change class | Required scrutiny |
| --- | --- |
| Bounded implementation | Independent technical review plus targeted regression evidence and Director review after integration |
| Architecture / difficult diagnosis / cross-system change | Opus architecture and technical review, reproduction/replay as applicable |
| Auth, secrets, permissions, writes, controller or deployment boundary | Independent security and architecture review; negative permission tests; explicit required owner gate |
| Meaningful UI/interaction | Fable direction, browser/accessibility/device evidence, Fable post-build review, technical review and Director review |
| Claimed latency/performance improvement | Comparable baseline/candidate measurements, functional checks and performance review |

A blocking finding requires evidence-backed resolution. Reviewer disagreement triggers investigation and Director reconciliation; counts of agreeing agents do not overrule a demonstrated safety defect. Product choices go to the owner with options and recommendation.

## 11. Fable and model routing

Fable receives workflow, user intent, devices, current DESIGN authority, speech/screen responsibilities, constraints and observed friction before implementation. Its output is a concrete experience brief: priorities, interaction/state requirements, acceptance scenarios and open product decisions.

Post-build, Fable reviews actual browser/device evidence against that brief, not merely a screenshot selected by the implementer. Browser emulation is labelled as emulation; it cannot certify real Samsung/iPhone voice, keyboard or background behaviour. Material unresolved device behaviours remain release blockers where the task requires them.

Fable's role is approved; its callable provider/runtime integration is not verified by this bootstrap. Establish its supported invocation, authentication, artifact formats and continuity constraints. If unavailable, mark the required review blocked or obtain an explicit authorised substitute; never silently relabel a generic worker "Fable".

Route architecture, security, novel systems, difficult diagnosis, integration judgement and high-scrutiny review to Opus. Sonnet may handle bounded implementation with objective evidence and independent review. Mechanical operations use deterministic tools wherever possible.

Pin the actual model/version/effort in each attempt. Do not hard-code unverified current model identifiers into this plan. If the required quality tier is unavailable, queue or escalate; never silently downgrade to a weaker model to finish sooner.

GPT Director automation likewise needs a supported invocation and result channel. Until verified, it is an explicit external review gate, not a fictional always-on process inside this conversation.

## 12. Integration and release boundary

Only the Integrator combines accepted commits. It records target base, ordered input SHAs, conflicts and any additional edits. Non-overlapping files do not prove independence: shared schemas, globals, UX state, configuration, test fixtures and API contracts can still conflict.

Re-run relevant integrated gates. Reuse evidence only when policy can show the subject and dependencies are unchanged; acceptance of isolated candidates is not proof about the integrated tree. Resolved conflicts and semantic interactions require fresh technical review. UI interactions require corresponding experience review where changed.

The Director reviews the integrated diff, actual evidence, finding resolutions, preserved/deleted contracts and limitations. The result is a release candidate, not a deployed service.

Future release approval binds the exact artifact, target environment, preconditions and rollback plan. The privileged controller performs installation and authoritative health/smoke verification. Rollback must address data/schema compatibility, not just changing a code pointer. Runtime truth updates only after authoritative verification.

## 13. Bounded failure and owner attention

Proposed initial policy, to be reviewed before implementation:

- one initial build and at most one bounded same-contract correction after diagnosis;
- continued or materially different failure escalates to Opus/Director for a revised plan;
- at most one further build under that revised plan before explicit re-planning;
- safety ambiguity, changed authority or contradictory evidence blocks immediately;
- provider outage is a transport/capability problem, not proof that weaker reasoning is acceptable;
- flaky tests remain failures to investigate; do not rerun until green and hide earlier results.

Timeouts are task-specific and declared before execution. Cancellation or resource-limit failure preserves diagnostics and reclaims processes safely.

The owner normally sees only a genuine decision, material blocker or a candidate requiring approval. Internal activity remains available on demand. An escalation includes the desired outcome, evidence, available options, recommendation and precise approval needed; it never asks the owner to relay agent messages.

## 14. Cutover and acceptance plan

Preserve the existing watcher until the new path proves its unique responsibilities are covered.

1. **Contracts and simulation:** validate tasks, transitions and evidence using fake workers, fault injection and a durable store. No bridge consumption or production change.
2. **One isolated candidate:** after prerequisite gates and implementation authorisation, run one bounded offline task through implementation, independent review, integration and Director review; no deployment.
3. **Recovery and publication:** kill/restart at assignment, build completion, evidence collection and publication boundaries. Prove no lost task, duplicate authoritative result or unnecessary rebuild.
4. **Two separable candidates:** prove isolation, resource limits and dependency handling; integrate and reverify. Parallel reviewers follow the same isolation rules.
5. **Experience path:** validate the actual Fable adapter and one meaningful UI task with the required browser and device evidence.
6. **Controlled cutover:** drain/acknowledge the current watcher round, persist a cutover watermark, enable only one consumer and retain rollback. Explicitly retire obsolete watcher responsibilities when replaced.

Required acceptance scenarios include duplicate intake; stale worker completion; cancelled process still alive; network failure after successful remote push; mismatched candidate/evidence SHA; modified frozen expectations; worker attempt to push production; cross-workspace/credential access; unavailable required reviewer; policy/context changes during a run; integration conflict; task-store/artifact recovery; disk exhaustion; and resource starvation of the business runtime.

Use current `make accept`, Node renderer tests, Ruff, offline pytest and relevant experience/collision/replay tooling where they still protect active contracts. Do not run credential/live-API checks by confusing `make check` with an offline acceptance gate. The current Makefile's `check` depends on `doctor shopify gmail-verify`.

## 15. Decisions to resolve at the appropriate stage

Engineering investigation, not immediate owner terminal work:

- supported Fable and GPT Director adapters;
- credential/session isolation and provider-concurrency limits;
- measured CPU/memory/browser capacity alongside the business runtime;
- minimum task-store/artifact backup and recovery policy;
- task risk taxonomy and exact policy-to-test mapping;
- controlled publication credentials and bootstrap installation boundary.

Owner decisions arise only for material product trade-offs, additional permissions, expenditure or approval-gated deployment. Detailed mechanisms in this specification remain subject to the architecture/engineering reviews named here even though implementation is now owner-authorised. The approval does not authorise production deployment, new privileges, secrets, business writes, destructive actions or infrastructure promotion.

## Source record

Read at the pinned baselines above:

- product memory: CURRENT_TRUTH, PRODUCT_BRAIN, EVOLUTION_POLICY, DIRECTOR_PROTOCOL, DECISIONS, ROADMAP, SELF_IMPROVEMENT and MIGRATION_HANDOFF;
- bridge inbox/outbox at latest observed branch HEAD `165c366c3132ef2dc3b42f3cc1ffaa5296b4af07`;
- Builder Environment source/manifest at `9a27bc441adad1e98e8a9ca257d1883246ee7eec`; independent targeted offline reproductions are recorded in BUILDER_ENVIRONMENT_REVIEW.md;
- watcher README, executable and systemd unit at `3d1f65df2d93f24ab75c50d5774eacb47b31df43`;
- application ENGINEERING_LOOP and Makefile at `e43aecdb39b87b622f64b6ab434e428d216ef157`.

The initial planning round executed no runtime/model/browser/application tests. The continuation performed targeted offline Builder-script reproductions, including a harmless shell-quoting probe; see the separate review for scope and results. No server state, model integration, complete bootstrap or application/browser suite was independently tested. This remains a planning document, not certified implementation.
