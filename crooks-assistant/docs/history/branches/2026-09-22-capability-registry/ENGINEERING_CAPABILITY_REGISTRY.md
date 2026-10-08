# CLIVE Engineering Capability Registry

**Status:** CANDIDATE — repository-only reconciliation; not activation or installation authority  
**Registry base:** `claude/product-memory-foundation` @ `8d6b111259f66a4d6a0704146da29b6e54d1c57e`  
**Date:** 2026-09-22

## Status vocabulary

- `DISCOVERED` — identified, not yet audited.
- `AUDITED/CLEARED` — bounded source/methodology reviewed for the stated use; not installed or active.
- `ACCEPTED_CANDIDATE` — independently accepted for the next gate; still not installed/active unless separately recorded.
- `INSTALLED` — bytes/tooling present in the engineering environment; does not imply active policy use.
- `ACTIVE` — currently used by the engineering workflow.
- `DISABLED` — installed/present but deliberately inactive.
- `REJECTED` — explicitly unsuitable for the stated CLIVE use.
- `DEPRECATED` — previously used/accepted but superseded.
- `PROPOSED` — desired candidate with adoption evidence still incomplete.

No entry may infer `INSTALLED` or `ACTIVE` from `AUDITED/CLEARED` or `ACCEPTED_CANDIDATE`.

## Registry

| Capability / source | Pinned identity | Status | Current CLIVE disposition / authority |
|---|---|---|---|
| affaan-m/ECC selective audit | upstream commit `07756cee15788a54506031462794ad645719b028` | AUDITED/CLEARED | Selective reuse only. Full ECC plugin/runtime/hook graph is rejected for V1. No wholesale installation. |
| ECC `agent-architecture-audit` | ECC `07756cee15788a54506031462794ad645719b028` | AUDITED/CLEARED | Static/reference capability; reviewer tools must be narrowed before activation. |
| ECC agent-eval / ai-regression-testing / automation-audit-ops / selected TDD evidence rules | ECC `07756cee15788a54506031462794ad645719b028` | AUDITED/CLEARED | Methodology to adapt/reimplement, not evidence of installation. |
| ECC destructive-Git GateGuard concept | ECC `07756cee15788a54506031462794ad645719b028` | AUDITED/CLEARED | Reimplement as a small fail-closed CLIVE project hook with tests; do not import ECC runtime. |
| `frontend-design` | exact upstream pin not evidenced in canonical source at this registry base | PROPOSED | Do not claim installed/active until source, exact commit/path/hash, audit and activation evidence are recorded. |
| Vercel `web-interface-guidelines` | exact upstream pin not evidenced in canonical source at this registry base | PROPOSED | Same gate: pin + audit + explicit activation evidence required. |
| Leonxlnx `redesign-skill` | exact upstream pin not evidenced in canonical source at this registry base | PROPOSED | Candidate design capability only. |
| Leonxlnx `image-to-code-skill` | exact upstream pin not evidenced in canonical source at this registry base | PROPOSED | Candidate implementation aid only. |
| `taste-skill` | exact upstream pin not evidenced in canonical source at this registry base | REJECTED | Preserve rejection; do not activate merely because adjacent design skills are considered. |
| `create-design-md` methodology | exact upstream pin not evidenced in canonical source at this registry base | PROPOSED | Methodology candidate; no live-status inference. |
| Impeccable | exact upstream pin/status unresolved; Builder review records contradictory scan status | PROPOSED | Must not be described as installed, security-approved or active until contradiction is resolved with exact evidence. |
| Playwright builder tooling | Playwright `1.56.1`; Chromium revision `1194` | INSTALLED | Builder tooling inventory only. `INSTALLED` does not imply every worker has browser authority or that UI evidence has been captured. |
| Anthropic `webapp-testing` skill | exact upstream pin not evidenced in canonical source at this registry base | REJECTED | Rejected capability remains inactive. |
| project-scoped `.claude` harness | accepted candidate `2c2b0cc4a5f3d82a929eedfa053b5cc46478215f`; parent `c16d6db8cd5b7d7a7048462e367339218d178a11`; accepted Builder base `295e483b4f9adcdc3fb58bfb3aa025e2e3f4779b` | ACCEPTED_CANDIDATE | Sixth independent adversarial review accepted it for the next gate. Acceptance explicitly did **not** activate project `.claude/` files or modify account/global settings. |
| OpenAI Symphony reuse | exact upstream pin not yet evidenced complete in canonical source | PROPOSED | P1 reuse source for reconciliation loop, deterministic workspaces, bounded concurrency, retry/recovery and stale-result handling. Explicit line-by-line Symphony-vs-Orchestrator import gate is not yet evidenced complete. Do not make Symphony authoritative state. |
| OpenClaw runtime reuse | exact upstream pin/audit not yet recorded in canonical source | DISCOVERED | Audit/pilot only behind `WorkerRuntime`; no production install. Must explicitly configure sandboxing, session visibility, agent-to-agent access, tools/paths/network/secrets before any isolated pilot. |
| CLIVE native control plane | candidate `e8830c44bcae917b7c711b081a8adf003832bc9d` on `claude/control-plane-vnext-phase1-repair2-2026-09-21` | PROPOSED | Not independently accepted. Authoring Claude correctly declared itself INELIGIBLE to review. Progress branch must not reconcile onto it until eligible exact-SHA review exists. |

## Harness reconciliation

`HARNESS_ACCEPTANCE_2C2B0CC.md` is authoritative evidence that `2c2b0cc4a5f3d82a929eedfa053b5cc46478215f` received **ACCEPT FOR NEXT GATE**. Its evidence includes 558 new repair regressions passed, 896 prior harness regressions passed, pinned gitleaks 8.30.1 clean, and an exact two-file repair diff. The same record explicitly states that no project `.claude/` activation occurred. Therefore any `CURRENT_TRUTH.md` wording that describes this candidate only as an older rejected harness state is stale and must be reconciled; acceptance must not be rewritten as activation.

## Symphony reconciliation

`ENGINEERING_STACK_REUSE_PLAN.md` defines Symphony as a P1 pattern source, not an approved runtime dependency. Required mechanisms to compare/import selectively are issue/task intake, authoritative assignment state, deterministic per-task workspaces, bounded concurrency, heartbeat/reconciliation, stale completion rejection, retry/backoff, and drain/cutover watermark. CLIVE retains immutable task revisions, exact evidence/SHA binding, reviewer identity, owner gates and release verification. Until a durable line-by-line comparison is committed with evidence, the Symphony import gate remains incomplete.

## Unresolved identity rule

The owner's prior "awesome design" referent is **UNRESOLVED** at this registry base. No capability name is assigned to it without a concrete prior source.

For every row whose exact upstream pin is unresolved, the next safe action is research/reconciliation only. Do not fabricate a commit, path, hash, installation state or activation state.

## Consistency invariant

Canonical truth must never silently regress an accepted capability/harness state. Any future reconciliation should enforce at minimum:

1. every `ACCEPTED_CANDIDATE`, `INSTALLED`, `ACTIVE`, `DISABLED`, `REJECTED`, or `DEPRECATED` registry entry has a durable evidence reference or exact source identity;
2. `CURRENT_TRUTH.md` may be less detailed than this registry but must not contradict its status;
3. `ACCEPTED_CANDIDATE != INSTALLED != ACTIVE`;
4. upstream source review does not grant tools, network, secrets, production authority, business-write authority or owner approval;
5. supersession records the previous identity rather than silently replacing it.

A deterministic consistency test should be added only after the registry format is reviewed; the test should parse structured status/identity fields rather than natural-language prose.