# CHATGPT INBOX

## Bounded repair — Orchestrator V1 freeze G-01 / G-02 / G-03

This is exactly one bounded repository-only repair round on the existing freeze-candidate branch. It is not production/runtime remediation and it is not owner adoption.

### Exact identities

- repository: `crooksldn-pixel/clive`
- canonical base: `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- rejected candidate: `31b0e07179877651da80065f5914575ee4d60d6c`
- review outbox blob: `c68050463a7e3e0608a852a8afa3d9f868a7602b`

Before editing, explicitly fetch/read the candidate branch and canonical base. Abort and report BLOCKED if the candidate branch no longer resolves exactly to `31b0e07179877651da80065f5914575ee4d60d6c`, if merge-base is not the canonical base, or if the workspace contains unrelated owner work. Do not reset/clean/stash/discard anything.

### Hard scope

Allowed: repository-only edits on the same freeze-candidate branch to the freeze contract/state API/acceptance matrix/traceability/mechanical spec test needed to repair G-01/G-02/G-03, plus test execution and repository-local evidence.

Forbidden: production deployment/promotion; systemd/watcher/runtime changes; secrets/credential reads; `/root/.claude` or account/global Claude changes; MCP/connector grant changes; privilege expansion; CROOKS/CLIVE business writes; public exposure; destructive reset/clean/stash; external spend; production merge; freeze adoption; sequencing changes.

Do not repair the known Builder stale fetch refspec. Explicit branch fetches are acceptable.

### G-01 — TASK stranded in ASSIGNED after pre-RUNNING fencing

Repair the TASK-side reconciliation hole identified by the independent review.

Required outcome:
- a TASK in `ASSIGNED` whose execution attempt is no longer non-terminal after controller-epoch fencing/cancellation cannot remain silently stranded;
- state API §1A and freeze contract §21 must cover `ASSIGNED` consistently with the existing BUILDING/INTEGRATING/REVIEWING ambiguity rule, or replace the literal enumeration with an equivalent mechanically derivable rule;
- reconciliation surfaces the subject as BLOCKED through the already-listed `task.block` edge; no blind redispatch.

Acceptance:
- add ST-15: controller epoch changes while TASK is ASSIGNED and attempt is CREATED or STARTING -> attempt closes FENCED and task is surfaced BLOCKED with typed reason;
- add a structural mechanical test deriving from §3A the subject states that can hold a non-terminal execution record and proving each is covered by both §1A and §21 reconciliation semantics. Avoid a literal-substring-only false green.

### G-02 — restart fencing must not consume execution budget when no model ran

Repair the attempt-ceiling accounting hole without weakening R-02.

Required outcome:
- an attempt that closes CANCELLED or FENCED having never reached RUNNING / never launched a model process does not consume the per-revision execution-attempt ceiling;
- deterministic preflight failure remains budget-consuming because it closes FAILED or QUARANTINED, not CANCELLED/FENCED;
- the rule is normative and consistent between state API §3A and freeze contract §10.3.1;
- restart, DB restore and epoch change cannot reset or accidentally decrement legitimate consumed attempts.

Acceptance:
- add ST-16: repeated controller restarts while TASK is ASSIGNED with CREATED attempt do not exhaust the three real execution attempts; after three such restart-fencings a legitimate attempt assignment remains admissible according to the repaired accounting rule;
- extend PR-10 so it asserts exactly which dispositions consume the ceiling and that persistence survives restart/restore/epoch change.

### G-03 — delivery crash window between external effect and outcome persistence

Repair the new delivery state machine so a crash after an external effect cannot cause blind duplicate publication.

Required outcome:
- before/when an external publication effect is initiated, persist durable evidence that the effect may have started (using the existing delivery attempt count if sufficient; do not add schema merely for convenience);
- on restart/epoch change, PENDING with evidence that an effect may have been initiated reconciles to UNKNOWN before any further external effect;
- `delivery.publish` cannot blindly replay that record;
- freeze contract §21 delivery reconciliation and state API §3C agree;
- authoritative remote reconciliation remains the only path out of ambiguity.

Acceptance:
- add DL-06: crash between external effect and outcome persistence -> restart produces UNKNOWN, publish is refused pending `delivery.reconcile`, and no second external effect occurs;
- add a structural test proving every §3C state from which an external effect can be initiated is terminal or has an explicit reconciliation/precondition rule that prevents blind replay after an initiated effect.

### Regression and evidence requirements

Preserve all earlier repairs N-01..N-04, B-01..B-05, R-01..R-03, F-01..F-03. Update traceability for G-01/G-02/G-03.

Run the committed mechanical spec test and any relevant document/static checks. Independently verify:
- zero dangling acceptance IDs;
- every MUST-bearing numbered FC/SA section is represented in §18A;
- every non-terminal attempt state has a terminal cleanup/fencing path;
- delivery enum and §3C remain mutually complete;
- no self-adoption and no DEC-046/DEC-047 sequencing change.

Before publishing the repair result, require:
- exact base/rejected/new candidate SHAs;
- exact changed-file set and diff summary;
- test commands/results;
- repository worktree clean after commit;
- repository candidate secret scan with exact command/result and no secret values in the report;
- exact remote branch readback equals the new candidate SHA.

Publish the repair only to `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`. Do not merge or adopt it.

### Handoff

After the bounded repair is committed and pushed, report the exact new SHA and evidence in the outbox. Do **not** self-certify. State explicitly that the previous verdict is stale for the changed SHA and that a fresh independent read-only review is required.
