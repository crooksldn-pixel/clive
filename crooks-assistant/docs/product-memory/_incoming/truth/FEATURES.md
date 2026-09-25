# CROOKS OS — Feature Register

**Last consolidated:** 2026-09-23 (rows FEAT-010 to FEAT-014 updated and FEAT-055 to FEAT-059 added from the 2026-09-23 engineering state; earlier rows as consolidated on 2026-09-19)

This file tracks features that are approved, planned, building, testing, or shipped. Brainstorming that has not been accepted belongs in `IDEAS.md`.

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| FEAT-001 | Existing FastAPI CROOKS backend | SHIPPED | V1 | Current core runtime. |
| FEAT-002 | Claude Agent SDK / Max integration | SHIPPED | V1 | Current reasoning provider path. |
| FEAT-003 | Shopify read/write capability layer | SHIPPED / HARDENING | V1 | Existing action safeguards remain canonical. |
| FEAT-004 | Gmail integration | SHIPPED / HARDENING | V1 | Linux token persistence being formalised. |
| FEAT-005 | ElevenLabs Scribe STT | SHIPPED | V1 | Primary STT. |
| FEAT-006 | Derek TTS | SHIPPED | V1 | Existing voice output. |
| FEAT-007 | Proposal/action/verification system | SHIPPED | V1 | Safety-critical; preserve semantics. |
| FEAT-008 | Samsung browser/PWA client | SHIPPED / POLISH | V1 | Needs UX/UI refinement. |
| FEAT-009 | CROOKS Control Mac app | SHIPPED / POLISH | Phase 6 | Exists but still engineering-like. |
| FEAT-010 | Always-on Hetzner deployment | SHIPPED | NOW | Linux production ratified at `1cf3a0f3…` on 2026-09-19 (DEC-048); no deployment since. |
| FEAT-011 | Linux secret architecture | TESTING | NOW | Gmail OAuth still outstanding; new secret provisioning remains separately gated. |
| FEAT-012 | Tailscale private HTTPS runtime | SHIPPED | NOW | Tailnet-only HTTPS active and ratified (DEC-048). |
| FEAT-013 | Claude GitHub inbox/outbox bridge | SHIPPED / HARDENING | NOW | Manual bridge works. |
| FEAT-014 | Automatic Claude inbox watcher | SHIPPED / HARDENING | NOW | Installed and enabled; the hourly supervisor is disabled. Reviewed source revision `5ada7b47…` pins the installer's runtime to `claude-fable-5-1` at high effort, but the most recent verified live probe, a read-only live-host review on 2026-09-23 reported in the packet-20 review verdict relayed by the owner, found the loaded systemd unit (no drop-ins) carrying `Environment=CROOKS_BRIDGE_CLAUDE_MODEL=claude-opus-5`. Runtime truth comes from probes, not from this register; the model and effort in force are whatever the next probe shows. |
| FEAT-015 | iPhone responsive access | PLANNED | NOW | Initial via web/PWA; native later. |
| FEAT-016 | Current UI polish pass | PLANNED | NOW | Highest product priority after deployment. |
| FEAT-017 | Response-quality/latency pass | PLANNED | NOW | Entity focus, verbosity, tool routing, speed. |
| FEAT-018 | Structured real-world test backlog | PLANNED | NEXT | Convert telemetry into engineering issues. |
| FEAT-019 | CROOKS World entity graph | PLANNED | NEXT | Persistent business state. |
| FEAT-020 | Event Ledger | PLANNED | NEXT | Durable provenance/event history. |
| FEAT-021 | Expectations/deadline extraction | PLANNED | NEXT | Casual statements become monitored expectations. |
| FEAT-022 | Attention engine | PLANNED | NEXT | “What needs my attention?” |
| FEAT-023 | Selective notifications | PLANNED | NEXT | Material exceptions only. |
| FEAT-024 | Automation/Objectives engine | PLANNED | NEXT | Scheduled/event/conditional/stateful/goal-based. |
| FEAT-025 | Earned autonomy | PLANNED | NEXT/LATER | Narrow action-class autonomy after evidence. |
| FEAT-026 | WhatsApp integration | CAPTURED | NEXT/LATER | Supplier/customer messaging and triggers. |
| FEAT-027 | Click & Drop integration | CAPTURED | NEXT/LATER | Labels, tracking, fulfilment verification. |
| FEAT-028 | Resend integration | CAPTURED | NEXT/LATER | Transactional outbound email. |
| FEAT-029 | Stripe integration | PLANNED | NEXT/LATER | Payment/refund context and events. |
| FEAT-030 | Drive/Notes/document context | CAPTURED | NEXT/LATER | Linked business documents. |
| FEAT-031 | Base44 capability integration | CAPTURED | NEXT/LATER | Bring internal apps behind CROOKS. |
| FEAT-032 | Model Gateway | PLANNED | LATER | Provider fallback/routing/model independence. |
| FEAT-033 | Anticipation engine | PLANNED | LATER | Detect important missing/abnormal events. |
| FEAT-034 | Scene compiler | PLANNED | LATER | Contextual UI generation. |
| FEAT-035 | Multi-user/staff roles | CAPTURED | LATER | Scoped interfaces/capabilities. |
| FEAT-036 | Nightly Observer | PLANNED | LATER | Evidence-backed issue discovery. |
| FEAT-037 | Historical replay framework | PLANNED | LATER | Before/after regression evidence. |
| FEAT-038 | Builder/staging worktree system | PLANNED | LATER | Isolated candidate development. |
| FEAT-039 | Morning self-improvement report | CAPTURED | LATER | Owner-facing summary of overnight engineering. |
| FEAT-040 | Claude Dev Manager | CAPTURED | LATER | Decompose broad objectives. |
| FEAT-041 | Specialist dev agents | CAPTURED | LATER | UI/UX/debug/feature/QA/perf/security/integration. |
| FEAT-042 | Independent specialist reviewers | CAPTURED | LATER | “Voice of reason” at each layer. |
| FEAT-043 | GPT Director | CAPTURED | LATER | Independent top-level engineering reviewer. |
| FEAT-044 | Automatic GPT ↔ Claude loop | CAPTURED | LATER | Iterative engineering without owner message ferrying. |
| FEAT-045 | CROOKS-managed Claude Code | CAPTURED | SOMEDAY | User no longer directly operates Claude Code. |
| FEAT-046 | Product-memory auto-capture | CAPTURED | SOMEDAY | Detect/capture important product ideas. |
| FEAT-047 | Native CROOKS Phone | CAPTURED | SOMEDAY | Mobile-first native client. |
| FEAT-048 | CROOKS Pad hardened/native shell | CAPTURED | SOMEDAY | Dedicated tablet client. |
| FEAT-049 | Subscriber CROOKS OS | APPROVED | SOMEDAY | Configurable ecommerce/small-business product. |
| FEAT-050 | Simple subscriber onboarding | APPROVED | SOMEDAY | Connect tools, auto-build business model. |
| FEAT-051 | Multi-user subscriber permissions | CAPTURED | SOMEDAY | Role-based business operation. |
| FEAT-052 | Capability graph | CAPTURED | LATER | Explicit scopes/risk/reversibility/verification. |
| FEAT-053 | Rollback-aware autonomous maintenance | CAPTURED | LATER | Post-deploy monitoring and rollback. |
| FEAT-054 | Skill/environment inventory | CAPTURED | NOW/NEXT | Durable record of Claude/server tools and skills. |
| FEAT-055 | Repository-only lifecycle kernel (engineering control plane) | TESTING | NOW | Accepted and frozen at `18c3153a…` (packet 14 READY); records on `clive/engineering-state`; further kernel work only on dogfood evidence of a core-invariant failure. Not deployed as a service. |
| FEAT-056 | Judgment ledger, exact-SHA review contract and CI acceptance provenance | TESTING | NOW | On the CI stream at `b68e6e82…`; the `acceptance` workflow runs five gates on every push; mechanical gates produce evidence, not permission. |
| FEAT-057 | Agent Environment authoritative state | TESTING | NOW | Read-only projection of kernel records; truth repairs accepted at `84e12e77…`. |
| FEAT-058 | Customer Support Investigator V1 (read-only) | TESTING | NOW | COMPLETE in the kernel at `2dbb97bc…` after packets 15–18; two real cases verified read-only; owner verification, first live run, CI-stream landing and deployment pending. Cannot write. |
| FEAT-059 | CLIVE Live Experience V0.5 | BUILDING | NOW | Implementation stream `chatgpt/clive-live-experience-v0-5`; production-lineage integration candidate `d9621337…` is owner-gated (fixture baseline authorisation and two product answers outstanding); not accepted, not deployed. |

## Feature promotion rule

A feature should move from CAPTURED to APPROVED only when the owner explicitly commits to the direction.

A feature should move to PLANNED only when:
- sequencing is agreed,
- dependencies are understood,
- and it does not displace a higher-priority NOW item without an explicit decision.

A feature should move to SHIPPED only after:
- implementation,
- tests,
- deployment,
- and real verification.
