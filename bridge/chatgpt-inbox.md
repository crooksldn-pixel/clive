# CHATGPT INBOX

## Fresh independent adversarial re-review — Orchestrator V1 freeze candidate

This is a **read-only independent architecture/specification re-review**. It is not implementation.

Review exact candidate:
- repository: `crooksldn-pixel/clive`
- base: `claude/product-memory-foundation@9e59860a945ec339c69af8709cd0721f0a795327`
- candidate branch: `chatgpt/orchestrator-v1-freeze-candidate-2026-09-20`
- candidate SHA: `a4ec77ff953bd7af5117e5adb5756adddd942fdb`

The prior review of `f1c808e...` is stale. Do not carry its verdict forward. The candidate has materially changed.

Read in full:
- `ORCHESTRATOR_V1_FREEZE_CONTRACT.md`
- `ORCHESTRATOR_V1_STATE_API.md`
- `ORCHESTRATOR_V1_TRACEABILITY.md`
- `ORCHESTRATOR_V1_ACCEPTANCE_MATRIX.md`
- `WATCHER_BUILDER_IDENTITY_REMEDIATION.md`
- modified `ENGINEERING_ORCHESTRATOR_V1.md`, `CURRENT_TRUTH.md`, `ROADMAP.md`
- canonical `DECISIONS.md`, `DEV_TEAM_V1_PILOT.md`, `ENGINEERING_STACK_REUSE_PLAN.md`, `SELF_IMPROVEMENT.md`, `HARNESS_ACCEPTANCE_2C2B0CC.md`
- accepted Builder contract trial at exact SHA `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b:crooks-assistant/docs/dev-environment/CONTRACT_TRIAL_ENV_REPRO_001.md`
- previous outbox review for the findings F-01 through F-12.

### Hard scope

Do **not** edit, create, delete, commit, push, merge, switch/reset/clean/stash branches, install, restart, deploy or alter any repository/runtime/systemd/account/global Claude/MCP/connector/credential/permission/production state. Do not fix findings. Read remote Git by exact SHA and write only the normal bridge outbox.

The live builder branch mismatch remains known and must not be reconciled in this review.

### Required re-review

First verify the exact candidate SHA/merge-base/diff.

Then explicitly check whether each prior blocker F-01 through F-12 is:
- CLOSED,
- OWNER-PENDING,
- RUNTIME-PENDING, or
- STILL OPEN.

In particular verify:
- ROADMAP/CURRENT_TRUTH no longer self-authorise a DEC-046 sequencing change;
- owner adoption by exact freeze SHA is a required gate rather than inferred authority;
- complete task/attempt/integration state and command semantics are executable and non-contradictory;
- Candidate is durable before evidence completion;
- CG-01..CG-06 are genuinely closed, including clean reconstruction;
- risk taxonomy/default and CI/review gates are deterministic;
- Evidence Collector is an explicit kernel principal outside worker authority;
- candidate publication is kernel-only and workers have no push credential;
- environment/toolchain fingerprint is actually checked;
- AuthorityGrant expiry/revocation are enforced and tested;
- watcher/builder mismatch has a concrete bounded remediation plan and Phase 1 is blocked on live closure;
- no evidence-invalidation/store escape clauses remain;
- reviewer independence is defined and testable;
- candidate/integration evidence and reviews use exact generic subject identity;
- every MUST-level invariant in both normative contracts has an acceptance test or is explicitly static.

Also adversarially search for **new** contradictions introduced by the repairs. Pay special attention to:
- terminal task states versus revision/cancellation;
- attempt lifecycle edges;
- integration correction/block/cancel semantics;
- idempotency across every retryable mutation;
- DB backup/restore and host-loss limitations;
- mirror staleness/base-object retrieval;
- network/tool/credential isolation;
- artifact-store crash safety;
- observability/audit event durability;
- drain/upgrade/schema compatibility;
- whether anything essential was improperly deferred to V1.x/V2.

### Authority-specific verdict handling

The owner has **not yet** made the F-01 sequencing/adoption decision. That absence by itself should be reported as `OWNER-PENDING`, not as an engineering-contract defect, **provided** the candidate correctly fails closed until owner adoption.

The live watcher/builder mismatch should be `RUNTIME-PENDING`, not an engineering-contract defect, **provided** the remediation plan is technically sound, separately gated, and Phase 1/write-capable model execution cannot proceed before closure.

### Verdict

Return exactly one engineering verdict:
- `ENGINEERING CONTRACT READY — OWNER/RUNTIME GATES REMAIN`
- `CHANGES REQUIRED BEFORE OWNER DECISION`

If changes are required, list only material blocking engineering findings with:
- ID/severity;
- exact file/section;
- failure/unsafe consequence;
- smallest repair;
- exact acceptance test required.

List owner/runtime pending gates separately and do not conflate them with engineering defects.

Do not approve because the documents are detailed. Try to break the contract.
