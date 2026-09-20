# Engineering Orchestrator V1 — Research Traceability Matrix

**Status:** FREEZE CANDIDATE companion to `ORCHESTRATOR_V1_FREEZE_CONTRACT.md`  
**Date:** 2026-09-20

Purpose: prevent important findings from Symphony, ECC/skills, CLIVE incidents, contract trials and self-improvement research from disappearing during implementation.

Status values:
- **V1 MUST** — normative in the freeze contract;
- **V1 SHOULD** — recommended but not correctness-critical;
- **DEFER V1.x/V2** — intentionally not in V1;
- **REJECT** — intentionally not adopted.

| Origin | Finding / mechanism | V1 disposition | Contract destination / rationale |
| --- | --- | --- | --- |
| OpenAI Symphony | single authoritative orchestration state | **V1 MUST** | deterministic kernel + SQLite state store + single-controller epoch |
| Symphony | deterministic per-task workspace | **V1 MUST** | external standalone attempt workspace |
| Symphony | bounded concurrency | **V1 MUST** | one implementation slot initially; measured expansion only |
| Symphony | heartbeat and reconciliation | **V1 MUST** | lease/liveness + restart reconciliation |
| Symphony | stale-completion rejection | **V1 MUST** | monotonic fencing token + controller epoch |
| Symphony | exponential retry/backoff | **V1 MUST** | typed retry taxonomy; transient only |
| Symphony | drain/cutover watermark | **V1 MUST** | DRAINING mode + persisted cutover watermark |
| Symphony | continuous operator-visible state | **V1 MUST** | structured journal + minimum metrics/logs |
| Symphony | repo-owned workflow policy | **V1 SHOULD** | task/context/policy are versioned in Git; kernel policy remains deterministic |
| Symphony | tracker-driven restart recovery without durable DB | **REJECT for CLIVE** | CLIVE needs durable task/attempt/review authority beyond tracker/workspace inference |
| Symphony | agent may perform tracker writes through provider-native tools | **REJECT as authority model** | CLIVE kernel owns authoritative workflow state; models cannot write approval/task DB directly |
| Symphony | workspace hooks as generic shell extension | **DEFER / narrow only** | V1 prefers typed controlled operations; arbitrary hooks expand authority surface |
| CLIVE stronger contract | immutable task revision | **V1 MUST** | task contract + state schema |
| CLIVE stronger contract | exact base/candidate/evidence identity | **V1 MUST** | SHA-authoritative identity; evidence digest |
| CLIVE stronger contract | independent reviewer identities | **V1 MUST** | review record + independence rule |
| CLIVE stronger contract | integration gate | **V1 MUST** | exact accepted SHAs; fresh integration evidence |
| CLIVE stronger contract | owner-only authority classes | **V1 MUST** | structured AuthorityGrant + explicit owner-only list |
| CLIVE stronger contract | release verification separate from implementation | **V1 MUST** | deployment controller outside V1 |
| Builder/watch incident | deterministic precondition retried eight times | **V1 MUST** | deterministic BLOCKED vs transient RETRY |
| Builder/watch incident | nested worker worktree dirtied canonical Builder | **V1 MUST** | external `/opt/crooks-workers/<task>/<attempt>` attempts; first V1 uses standalone clones with independent Git metadata |
| DEC-012 original wording | every autonomous worker gets its own worktree | **V1 MUST outcome preserved; implementation form strengthened** | preserve one-writer/one-isolated-workspace invariant; first V1 standalone clones avoid the nested-worktree parent-dirty failure. This supersedes the literal `worktree` mechanism without weakening isolation |
| Bridge verification 2026-09-20 | prompt/unit branch differed from actual checkout | **V1 MUST** | branches are labels; measured SHA/ancestry is authority; mismatch blocks writes |
| Bridge verification 2026-09-20 | actual process proved Opus request while self-report alone would be weaker | **V1 MUST** | launcher/process evidence outranks model self-report |
| Bridge verification 2026-09-20 | `--allowed-tools` did not remove inherited business MCP tools | **V1 MUST** | effective runtime roster assertion; fail closed on unexpected connector surface |
| Harness adversarial review | production path/redirect/command parsing bypasses | **V1 MUST** | retain reviewed fail-closed command/path guard methodology where shell is unavoidable |
| Harness acceptance `2c2b0cc...` | multiple independent repair/review rounds caught adjacent bypasses | **V1 MUST** | implementers never self-certify; fresh review after candidate mutation |
| ECC audit `07756cee...` | agent architecture audit methodology | **V1 SHOULD** | use as static review reference, not imported runtime |
| ECC audit | agent harness construction methodology | **V1 SHOULD** | project-scoped reviewed harness patterns |
| ECC audit | agent-eval methodology | **V1 SHOULD** | evidence-based provider/model benchmark |
| ECC audit | AI regression testing | **V1 SHOULD** | replay/eval layer after deterministic kernel |
| ECC audit | automation-audit-ops | **V1 SHOULD** | translate useful checks into CI/fault tests |
| ECC audit | selected TDD/RED evidence rules | **V1 SHOULD** | reproduction-before-fix and exact evidence |
| ECC audit | GateGuard destructive-Git decision table | **V1 MUST, reimplement** | small CLIVE-specific fail-closed guard; do not import plugin graph |
| ECC audit | full ECC plugin/runtime/MCP graph | **REJECT** | excessive executable/tool surface; duplicates governed CLIVE state |
| ECC audit | unified-memory | **REJECT for V1** | canonical Git + Orchestrator store own governed state |
| ECC audit | autonomous loops/harness | **DEFER as pattern source** | mine contracts only; no external authority |
| SkillSpector/manual audit | security-scan third-party skills before adoption | **V1 SHOULD** | dependency/skill provenance gate |
| Claude Code harness research | project-scoped CLAUDE.md/rules/skills/hooks | **V1 SHOULD** | only reviewed isolated engineering workspace harness |
| Claude Code harness | SessionStart task/base/context injection | **V1 SHOULD** | generated from kernel record; never authority source |
| Claude Code harness | PreToolUse destructive/path/secret guard | **V1 MUST where shell/tool surface exists** | deterministic guard + tests |
| Claude Code harness | PostToolUse deterministic lint/format gates | **V1 SHOULD** | fast evidence, not acceptance by itself |
| Claude Code harness | PreCompact/Stop state persistence | **DEFER if kernel already persists state** | model lifecycle hook cannot replace kernel state |
| Harness research | subagent context != workspace isolation | **V1 MUST** | each mutable writer gets its own filesystem/Git/process boundary |
| Stack reuse | exact-SHA independent CI | **V1 MUST for material candidates** | CI checks out SHA; worker cannot self-label accepted |
| Stack reuse | CodeQL/equivalent | **V1 SHOULD risk-based** | security-sensitive code classes |
| Stack reuse | SBOM + artifact attestation | **DEFER to releasable artifact lane / V1.x** | not necessary for every repository-only candidate |
| Stack reuse | OpenTelemetry-compatible tracing | **V1 SHOULD** | stable event schema mandatory; OTEL exporter optional |
| Stack reuse | de-identified regression datasets | **V1 SHOULD** | response/behavioral changes; not kernel correctness |
| Stack reuse | Renovate-style dependency/skill proposals | **DEFER V1.x** | proposals only; same normal review gates |
| Stack reuse | stronger sandbox substrate (container/Daytona/Dagger-like) | **DEFER pending measured need** | V1 first proves host/process/workspace isolation |
| Stack reuse | Cedar/policy-as-code engine | **DEFER** | typed native default-deny table first; adopt engine only if complexity warrants |
| DEV_TEAM trial CG-01 | evidence manifest lacks identity | **V1 MUST — resolved** | canonical JSON, SHA-256 digest, independently addressable raw artifacts |
| DEV_TEAM trial CG-02 | evidence invalidation granularity undefined | **V1 MUST — resolved conservatively** | any candidate SHA change invalidates evidence/reviews; reuse deferred |
| DEV_TEAM trial CG-03 | candidate without outbox/result invisible | **V1 MUST — resolved** | Candidate record independent of Delivery record |
| DEV_TEAM trial CG-04 | whole-task BLOCKED hides partial progress | **V1 MUST — resolved** | per-finding lifecycle + task-level state |
| DEV_TEAM trial CG-05 | clean reconstruction was underspecified | **V1 MUST — resolved** | freeze contract §22A + acceptance EN-01..EN-04 require allow-listed egress, immutable pins, integrity checks, disposable/fresh environment and fingerprint equality |
| DEV_TEAM trial CG-06 | prose approval unenforceable | **V1 MUST — resolved** | structured AuthorityGrant |
| SELF_IMPROVEMENT | Observer -> Triage -> Reproduction -> Builder -> Review -> QA -> Integration -> Director | **V1-compatible, mostly DEFER observer/triage automation** | V1 must not preclude later upstream Observer/Triage; Builder onward is foundation |
| SELF_IMPROVEMENT | historical replay | **V1 SHOULD** | task-specific proof/review gate |
| SELF_IMPROVEMENT | behavioral quality signals | **DEFER to product-quality lanes** | not kernel state authority |
| SELF_IMPROVEMENT | nightly autonomous production change | **REJECT for V1** | candidates only; no deployment authority |
| SELF_IMPROVEMENT | rollback after deployment | **DEFER to deployment controller** | V1 release candidate records rollback plan only |
| Role research | Opus for architecture/security/integration/high-scrutiny | **V1 SHOULD default** | evidence-based router, actual model pinned per attempt |
| Role research | Sonnet for bounded implementation | **V1 MAY** | only with objective proof + independent review |
| Role research | Fable Experience Director | **V1 MUST when meaningful UI/UX contract requires it** | adapter may remain blocked until verified |
| Role research | GPT Director | **V1 MUST as external independent gate initially** | supported automation may come later |
| Role research | UI engineer / debugger / feature / QA / performance / security roles | **V1 MAY on demand** | responsibilities, not permanent daemons |
| Role research | separate Scheduler role/agent | **REJECT as model role** | scheduler is deterministic kernel module |
| Role research | separate Release Manager agent | **REJECT for V1** | release authority belongs to future deterministic privileged controller |
| Distributed systems review | single writer/controller epoch | **V1 MUST** | OS lock + persisted epoch |
| Distributed systems review | idempotency for every retryable mutation | **V1 MUST** | unique keys + duplicate-safe responses |
| Distributed systems review | DB corruption/restore policy | **V1 MUST** | integrity check, independent backup destination, restore rehearsal, epoch invalidation and no-dispatch reconciliation |
| Distributed systems review | provider 429/5xx/auth/quota distinctions | **V1 MUST** | typed failure taxonomy |
| Distributed systems review | orphan child process cleanup | **V1 MUST** | cgroup/process-group ownership and quarantine |
| Distributed systems review | clock skew | **V1 MUST** | monotonic local lease timing; worker clocks non-authoritative |
| Distributed systems review | disk exhaustion | **V1 MUST** | admission high-watermark + safe GC |
| Distributed systems review | upgrade/drain/schema rollback | **V1 MUST** | deterministic DRAINING + backup/migration/reconcile |
| Supply-chain review | workers cannot rewrite protected verification policy unilaterally | **V1 MUST** | review changed tests/config against protected baseline |
| Supply-chain review | dependency/tool pins and integrity | **V1 MUST where external artifacts are used** | manifest digest and provenance checks |
| Repository housekeeping | preserve Shopify theme but separate it from CLIVE control plane | **DEFER separate bounded task** | no need to destabilise V1 freeze/first kernel slice |
| Product-memory discipline | history must not ossify current architecture | **V1 MUST** | Active Context compiler classifies active/historical/superseded constraints |
| Product-memory discipline | CURRENT_TRUTH/ROADMAP drift misleads workers | **V1 MUST before freeze** | candidate reconciles current Opus/harness state; sequencing changes still require explicit owner adoption in DECISIONS by exact SHA |

## Freeze interpretation

The matrix is complete for the V1-relevant findings currently recorded in canonical Git plus the 2026-09-20 Symphony/distributed-systems readiness review.

Any newly rediscovered recommendation must receive one of the four dispositions above before the frozen commit may move. Silence is not a disposition.
