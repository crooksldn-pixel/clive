# CROOKS Engineering Stack Reuse / Leverage Plan

**Status:** RESEARCH / PROPOSED — not an approval to install external services, spend money, widen privileges, expose secrets, change production, or supersede active safety contracts  
**Date:** 2026-09-19  
**Purpose:** maximise engineering power by owning CROOKS-specific policy/evidence semantics while reusing mature public agent infrastructure instead of rebuilding commodity machinery.

## Strategic conclusion

Do not build a generic coding-agent platform from first principles.

CROOKS should own:
- owner authority and approval semantics;
- canonical product/current-truth discipline;
- immutable task/revision and scope contracts;
- exact candidate/evidence identity binding;
- independent-review and integration semantics;
- separation between engineering authority and CROOKS business-write authority;
- product-specific acceptance, device and experience evidence;
- controlled release/runtime verification.

Prefer proven public machinery beneath those contracts where it is objectively better:
- Claude Code native skills, rules, hooks and subagents for worker harness behaviour;
- OpenAI Symphony patterns for ticket polling, deterministic workspaces, bounded concurrency, retry/reconciliation and continuous operation;
- GitHub Issues/PR/checks/rulesets as human-visible work/evidence surfaces;
- multiple interchangeable worker providers (Claude, Codex, optionally Factory) measured on CROOKS tasks;
- stronger sandbox substrates where needed instead of inventing isolation;
- OpenTelemetry-compatible tracing/evaluation rather than proprietary ad-hoc logs;
- GitHub/Sigstore attestations for releasable artifacts;
- Renovate-style update proposals for pinned tools/skills;
- policy-as-code for deterministic permission decisions if/when the current explicit decision table becomes hard to maintain.

## Priority integration candidates

### P0 — native Claude Code harness hardening
Move invariant worker rules out of repeated bridge prose and into reviewed project-scoped harness primitives:
- minimal CLAUDE.md;
- on-demand skills for repeatable procedures;
- read-only specialist subagents for analysis/review;
- PreToolUse hooks for destructive/path/production/secret restrictions;
- PostToolUse hooks for fast format/lint checks where deterministic;
- SessionStart injection of task identity/base/context digest;
- PreCompact/Stop persistence of bounded task state/evidence references.

A subagent context is not a mutable-workspace boundary. Parallel writers still require separate workspaces/branches.

Engineering workers should receive only engineering tools. CROOKS business MCP/connectors (Shopify, Gmail, Omnisend, etc.) must not be implicitly available to a coding worker. Prove the effective MCP/tool surface at launch rather than trusting prompt text.

### P0 — evidence-based model/worker benchmark
Build a small frozen CROOKS benchmark from real historical tasks:
- watcher installer upgrade defect;
- Builder provenance/bootstrap repair;
- a bounded backend change;
- security review;
- mobile/UX task;
- integration/review task.

Run multiple trials per worker/model on exact base SHAs. Record deterministic pass/fail, correction count, time, token/cost where available, reviewer findings, and consistency. Use results to drive routing rather than assuming one provider/model is always best.

### P0 — selective ECC adoption, never wholesale blind install
Candidate upstream: affaan-m/ECC. Pin an exact commit and security-review each selected skill/hook before adoption.

Audited at ECC commit `07756cee15788a54506031462794ad645719b028`:
- **ADOPT STATIC:** `agent-architecture-audit` (with reviewer tools narrowed) and `agent-harness-construction` as reference content;
- **ADAPT / REIMPLEMENT:** `agent-eval` methodology, `ai-regression-testing`, `automation-audit-ops`, selected `tdd-workflow` RED/evidence rules, and a small CROOKS-specific security checklist;
- **REIMPLEMENT, DO NOT IMPORT:** the useful destructive-Git decision table from ECC GateGuard as a small fail-closed CROOKS project hook with ported tests;
- **REJECT FOR ENGINEERING:** `benchmark-methodology` (marketing rubric), `verification-loop` (duplicates existing gates and its secret-grep pattern can expose values), and the full ECC plugin/runtime/hook graph;
- **DEFER / EFFECTIVELY REJECT FOR V1:** `unified-memory`, because canonical Git and the Orchestrator task store already own governed state.

The audit found 8/10 shortlisted skills with zero SkillSpector findings; the two HIGH findings were manually verified false-positive prose matches. Full ECC installation remains unjustified because it would add a large global executable/plugin/MCP surface for little incremental value.

Useful methodology but higher integration surface:
- unified-memory — only for unreviewed cross-harness handoffs; never replace canonical Git product memory or the task store;
- autonomous-loops / autonomous-agent-harness — mine contracts/patterns rather than granting them authority.

Hook ideas worth adapting after code review:
- destructive Git/path GateGuard;
- pre-commit secret/debug/quality checks;
- deterministic post-edit quality checks;
- lifecycle state persistence.

Do not copy the entire ECC plugin, MCP set, hooks graph, memory runtime or user settings into the server. They would create an unnecessarily broad executable/tool surface and can conflict with CROOKS-specific authority contracts.

### P1 — Symphony-inspired orchestration core
Mine OpenAI Symphony's minimal public orchestration pattern instead of reinventing generic scheduling:
- issue/task intake;
- authoritative assignment state;
- deterministic per-task workspace;
- bounded concurrency;
- heartbeat/reconciliation;
- stale completion rejection;
- retry/backoff;
- drain/cutover watermark.

Keep CROOKS's stronger contracts above it: immutable task revisions, exact evidence SHA binding, independent reviewer identities, Integrator gate, owner-only authority classes, and release verification.

### P1 — independent CI/evidence outside the implementer's host
Make a candidate prove itself twice:
1. worker-local tests;
2. independent CI/check execution from the exact pushed SHA.

Add security and provenance where eligible:
- existing Ruff/pytest/Playwright/axe/gitleaks/Trivy gates;
- CodeQL or equivalent static analysis;
- SBOM generation for releasable artifacts;
- GitHub artifact attestations / Sigstore provenance for release artifacts;
- branch/ruleset requirements so a worker cannot self-label a candidate accepted.

### P1 — OpenTelemetry + evaluation layer
Instrument both the engineering control plane and CROOKS assistant with structured traces:
- task/attempt/worker/model/effort/base SHA;
- tool calls and deterministic gate outcomes;
- latency/retry/failure class;
- candidate/review/evidence IDs;
- product assistant model/tool/retrieval latency and failure paths.

Prefer OpenTelemetry as the transport. Langfuse is a candidate UI/eval backend, ideally isolated/self-hosted or privacy-filtered; do not place a heavyweight observability stack on the current production VM without resource review.

Create de-identified regression datasets from real CROOKS conversations and incidents. Product response changes should be evaluated against them before release.

### P1 — safe dependency/skill updates
Use Renovate (or an equivalent proposer) to detect new versions/releases for:
- Python/npm dependencies;
- Builder tool pins;
- selected skill/repository commit pins;
- GitHub release assets.

Automation opens a candidate PR only. It never auto-promotes. Each proposal reruns provenance/security scans and acceptance gates.

### P2 — stronger worker sandboxes
Current isolated Git clones/worktrees remain valid for trusted bounded workers. Evaluate a sandbox substrate for untrusted/parallel execution:
- local/container option for low-cost reproducibility;
- Daytona or equivalent for dedicated filesystem/network/kernel/resource boundaries and secret-proxy patterns;
- Dagger as a candidate for portable containerized acceptance/eval pipelines.

External services/spend/credentials require separate owner approval. Benchmark cold start, runtime, browser support, isolation, secret exposure, failure recovery and cost before adoption.

### P2 — deterministic policy engine
Keep model reasoning out of authorization decisions. Represent worker authority as principal/action/resource/context with default deny and explicit owner gates.

Start with a small typed decision table and exhaustive negative tests. Consider Cedar when policy complexity justifies it; its default-deny / forbid-overrides-permit model maps well to CROOKS worker and release permissions. Do not introduce a policy engine merely for architectural fashion.

## Things explicitly not to outsource

Do not delegate these to Factory, GitHub, Claude, Codex, ECC, Symphony or another platform:
- the meaning of owner approval;
- CROOKS business write authority;
- what counts as VERIFIED;
- canonical current truth;
- release acceptance;
- candidate/evidence identity requirements;
- production promotion authority;
- secrets/privilege policy.

Providers are replaceable workers beneath these rules.

## Immediate research gates before installation

1. Security-audit the selected ECC commit and shortlist with SkillSpector plus manual review.
2. Prove a minimal project-scoped Claude hook/settings layout in an isolated branch; DEC-049 authorises the project-scoped files. The experiment must not alter account/global connector configuration, and must separately specify/prove how production/business MCP exposure will be removed before unattended worker operation.
3. Build the first frozen multi-worker benchmark and establish baseline Claude/Fable results before adding alternatives.
4. Compare Symphony state/recovery semantics line-by-line against ENGINEERING_ORCHESTRATOR_V1 and import only the missing commodity mechanisms.
5. Design the independent CI evidence envelope and candidate attestation format.
6. Prototype OTEL event schema locally/no-op before choosing Langfuse hosting.
7. Only then evaluate paid/external sandboxes or Factory against measured gaps.

## Success measure

The target is not maximum agent count. It is:
- higher pass-at-first-review;
- fewer false-success claims;
- less owner intervention per accepted candidate;
- faster deterministic gates;
- safe parallelism without shared-state races;
- lower context/tool pollution;
- provider replaceability;
- exact, independently verifiable release provenance.

Any added tool that does not improve one of those measures should not become permanent infrastructure.


## Verified ECC audit result — 2026-09-19

Read-only audit completed against exact ECC commit `07756cee15788a54506031462794ad645719b028`.

Material findings:
- do **not** install ECC wholesale;
- selective static/adapted content captures the useful value with far less executable surface;
- the most valuable code concept is ECC's destructive-Git classification table, to be reimplemented as a small CROOKS fail-closed project hook rather than imported with ECC runtime;
- current headless Claude engineering sessions inherit the owner's claude.ai connector/plugin roster, including business connectors such as Gmail, Shopify, Google Drive, Resend and Omnisend. Current unattended connector invocation was permission-denied, but mere exposure is unnecessary context/attack surface and is not an acceptable long-term isolation boundary;
- worker launch should therefore move toward strict MCP/plugin isolation plus a deterministic launch-time roster assertion that fails closed on unexpected tools;
- project-scoped `.claude/` harness files remain the preferred integration shape. **The owner explicitly approved creating/modifying them in isolated engineering workspaces for the reviewed harness experiment (DEC-049).** This does not extend to `/root/.claude`, account settings, connector/MCP grants, production, secrets, privileges, business writes, spend or destructive actions.

Audit evidence lives in the bridge outbox that processed inbox blob `4f5bfb5eaa32ef151a02c153a0ecbb548ea110b8`.
