# CROOKS OS — Feature Register

**Last consolidated:** 2026-09-25

- 2026-09-25: product memory was consolidated into `clive/trunk`, and statuses were corrected against production `ce791d03`. FEAT-060 to FEAT-064 were added. Superseded and retired rows are kept as history.
- 2026-09-23: rows FEAT-010 to FEAT-014 were updated, and FEAT-055 to FEAT-059 were added, from the 2026-09-23 engineering state.
- Earlier rows are as consolidated on 2026-09-19.

This file tracks features that are approved, planned, building, testing, or shipped. Brainstorming that has not been accepted belongs in `IDEAS.md`.

Production as of 2026-09-25: `/opt/crooks-os` runs `clive/trunk` at `ce791d03`, deployed on 2026-09-25 after GitHub acceptance and an independent exact-SHA review with zero findings. Merged to the trunk since, and **not yet deployed**:
- needs-reply routing;
- the microphone permission fix;
- the voice-credits wording and health;
- the remote-engineering journal-safe repair.

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| FEAT-001 | Existing FastAPI CROOKS backend | SHIPPED | V1 | Current core runtime. |
| FEAT-002 | Claude Agent SDK / Max integration | SHIPPED | V1 | Current reasoning provider path. |
| FEAT-003 | Shopify read/write capability layer | SHIPPED / HARDENING | V1 | Existing action safeguards remain canonical. |
| FEAT-004 | Gmail integration | SHIPPED / HARDENING | V1 | Gmail OAuth was provisioned on the production host on 2026-09-24 for team@crooksldn.com, with scopes gmail.modify and gmail.compose. The refresh token is in the Linux secret store outside every checkout, and unattended refresh was verified. Writes remain behind the existing action gate (DEC-058). History, 2026-09-19: Linux token persistence was being formalised. |
| FEAT-005 | ElevenLabs Scribe STT | SHIPPED | V1 | Primary STT. The ElevenLabs credits were exhausted by 2026-09-25 (see FEAT-006). This register holds no fresh evidence either way on whether server STT is affected; verify before relying on it. |
| FEAT-006 | Derek TTS | NOT SHIPPED ON SERVER | V1 | The Derek voice is unavailable on the production server because the ElevenLabs credits are exhausted (2026-09-25). The voice-credits wording and health change is merged to the trunk, not yet deployed. Restoring the voice needs credits, which is an owner spend decision. History: listed as SHIPPED ("existing voice output") on the 2026-09-19 register. |
| FEAT-007 | Proposal/action/verification system | SHIPPED | V1 | Safety-critical; preserve semantics. |
| FEAT-008 | Samsung browser/PWA client | SHIPPED / POLISH | V1 | Needs UX/UI refinement. Samsung verification is still outstanding. |
| FEAT-009 | CROOKS Control Mac app | SHIPPED / POLISH | Phase 6 | Exists but still engineering-like. |
| FEAT-010 | Always-on Hetzner deployment | SHIPPED | NOW | Production `/opt/crooks-os` runs `clive/trunk` at `ce791d03`, deployed 2026-09-25 after GitHub acceptance and an independent exact-SHA review with zero findings. History: ratified at `1cf3a0f3…` on 2026-09-19 (DEC-048), then the mobile alpha `ca388cee` on 2026-09-23. |
| FEAT-011 | Linux secret architecture | SHIPPED | NOW | The Gmail refresh token was provisioned on 2026-09-24 in the Linux secret store outside every checkout (DEC-058). Any new secret provisioning remains owner-gated. History, 2026-09-23: Gmail OAuth still outstanding. |
| FEAT-012 | Tailscale private HTTPS runtime | SHIPPED | NOW | Tailnet-only HTTPS active and ratified (DEC-048). |
| FEAT-013 | Claude GitHub inbox/outbox bridge | SUPERSEDED | NOW | Superseded by the remote engineering loop's bounded inbox (FEAT-063). Its watcher was retired on 2026-09-25 (DEC-058), and `crooks-ai-bridge` stays in history (DEC-028). History: "Manual bridge works." |
| FEAT-014 | Automatic Claude inbox watcher | RETIRED | NOW | Retired on 2026-09-25 (DEC-058); the remote engineering loop (FEAT-063) does its job. The history below is kept as written on 2026-09-23. The watcher was installed and enabled, and the hourly supervisor was disabled. Reviewed source revision `5ada7b47…` pinned the installer's runtime to `claude-fable-5-1` at high effort. A read-only live-host review on 2026-09-23 found the loaded systemd unit carrying `Environment=CROOKS_BRIDGE_CLAUDE_MODEL=claude-opus-5`. |
| FEAT-015 | iPhone responsive access | SHIPPED (ALPHA) | NOW | The private read-only phone alpha is in production (FEAT-060), and iPhone activity has been observed on the Linux runtime. A native client comes later (FEAT-047). History: PLANNED, "Initial via web/PWA; native later." |
| FEAT-016 | Current UI polish pass | BUILDING | NOW | Now carried by Generative UI V1 (FEAT-064). |
| FEAT-017 | Response-quality/latency pass | BUILDING | NOW | Entity focus, verbosity, tool routing and speed. Needs-reply routing, the repair for the 2026-09-24 misreading of "customers who need a reply", is merged to the trunk, not yet deployed. |
| FEAT-018 | Structured real-world test backlog | PLANNED | NEXT | Convert telemetry into engineering issues. |
| FEAT-019 | CROOKS World entity graph | PLANNED | NEXT | Persistent business state. |
| FEAT-020 | Event Ledger | PLANNED | NEXT | Durable provenance/event history. |
| FEAT-021 | Expectations/deadline extraction | PLANNED | NEXT | Casual statements become monitored expectations. |
| FEAT-022 | Attention engine | BUILDING | NEXT | “What needs my attention?” V1 is in production as derived truth and attention V1 (FEAT-061). The broader engine remains planned. |
| FEAT-023 | Selective notifications | PLANNED | NEXT | Material exceptions only. |
| FEAT-024 | Automation/Objectives engine | BUILDING | NEXT | Scheduled, event, conditional, stateful and goal-based. Objective V0 is in production in the mobile alpha (FEAT-060). Objectives do not yet act on their own between conversations. |
| FEAT-025 | Earned autonomy | PLANNED | NEXT/LATER | Narrow action-class autonomy after evidence. |
| FEAT-026 | WhatsApp integration | CAPTURED | NEXT/LATER | Supplier/customer messaging and triggers. |
| FEAT-027 | Click & Drop integration | CAPTURED | NEXT/LATER | Labels, tracking, fulfilment verification. |
| FEAT-028 | Resend integration | CAPTURED | NEXT/LATER | Transactional outbound email. |
| FEAT-029 | Stripe integration | PLANNED | NEXT/LATER | Payment/refund context and events. |
| FEAT-030 | Drive/Notes/document context | CAPTURED | NEXT/LATER | Linked business documents. |
| FEAT-031 | Base44 capability integration | CAPTURED | NEXT/LATER | Bring internal apps behind CROOKS. |
| FEAT-032 | Model Gateway | PLANNED | LATER | Provider fallback/routing/model independence. |
| FEAT-033 | Anticipation engine | PLANNED | LATER | Detect important missing/abnormal events. |
| FEAT-034 | Scene compiler | BUILDING | LATER | Contextual UI generation, now pursued as Generative UI V1 (FEAT-064). |
| FEAT-035 | Multi-user/staff roles | CAPTURED | LATER | Scoped interfaces/capabilities. |
| FEAT-036 | Nightly Observer | PLANNED | LATER | Evidence-backed issue discovery. |
| FEAT-037 | Historical replay framework | PLANNED | LATER | Before/after regression evidence. |
| FEAT-038 | Builder/staging worktree system | PLANNED | LATER | Isolated candidate development. The remote engineering loop (FEAT-063) already gives each builder attempt an isolated workspace. |
| FEAT-039 | Morning self-improvement report | CAPTURED | LATER | Owner-facing summary of overnight engineering. |
| FEAT-040 | Claude Dev Manager | CAPTURED | LATER | Decompose broad objectives. |
| FEAT-041 | Specialist dev agents | CAPTURED | LATER | UI/UX/debug/feature/QA/perf/security/integration. |
| FEAT-042 | Independent specialist reviewers | CAPTURED | LATER | “Voice of reason” at each layer. |
| FEAT-043 | GPT Director | CAPTURED | LATER | Independent top-level engineering reviewer. Not yet implemented: GPT currently serves as the exact-SHA independent reviewer only ([OPUS_5_5_HANDOFF_2026-09-24.md](./OPUS_5_5_HANDOFF_2026-09-24.md) §13). |
| FEAT-044 | Automatic GPT ↔ Claude loop | SUPERSEDED | LATER | Realised by the remote engineering loop (FEAT-063): builders, exact-SHA GPT review and bounded repair, with no owner message ferrying. |
| FEAT-045 | CROOKS-managed Claude Code | BUILDING | NOW | User no longer directly operates Claude Code. The remote engineering loop (FEAT-063) implements the bounded repository-only form: Claude Code (`claude-opus-5-5`) runs as an internal builder launched by the dispatcher (ROADMAP Y2). Broader product-managed engineering is not yet done: natural-language requests from inside the product (ROADMAP Y1), the GPT Director runtime (FEAT-043), and Termius only for emergency/admin access. History: CAPTURED / SOMEDAY on the 2026-09-19 register. |
| FEAT-046 | Product-memory auto-capture | CAPTURED | SOMEDAY | Detect/capture important product ideas. |
| FEAT-047 | Native CROOKS Phone | CAPTURED | SOMEDAY | Mobile-first native client. |
| FEAT-048 | CROOKS Pad hardened/native shell | CAPTURED | SOMEDAY | Dedicated tablet client. |
| FEAT-049 | Subscriber CROOKS OS | APPROVED | SOMEDAY | Configurable ecommerce/small-business product. |
| FEAT-050 | Simple subscriber onboarding | APPROVED | SOMEDAY | Connect tools, auto-build business model. |
| FEAT-051 | Multi-user subscriber permissions | CAPTURED | SOMEDAY | Role-based business operation. |
| FEAT-052 | Capability graph | CAPTURED | LATER | Explicit scopes/risk/reversibility/verification. |
| FEAT-053 | Rollback-aware autonomous maintenance | CAPTURED | LATER | Post-deploy monitoring and rollback. |
| FEAT-054 | Skill/environment inventory | CAPTURED | NOW/NEXT | Durable record of Claude/server tools and skills. |
| FEAT-055 | Repository-only lifecycle kernel (engineering control plane) | SHIPPED (ENGINEERING LOOP) | NOW | Accepted and frozen at `18c3153a…` (packet 14 READY), with records on `clive/engineering-state`. It is used unchanged by the dispatcher inside the remote engineering loop (FEAT-063). Further kernel work happens only on dogfood evidence of a core-invariant failure. It is not a product-runtime service. |
| FEAT-056 | Judgment ledger, exact-SHA review contract and CI acceptance provenance | SHIPPED | NOW | The judgment ledger CI stream and corrections are in production `ce791d03` (2026-09-25). The `acceptance` workflow gates the trunk. Mechanical gates produce evidence, not permission. History: on the CI stream at `b68e6e82…`. |
| FEAT-057 | Agent Environment authoritative state | TESTING | NOW | Read-only projection of kernel records, with truth repairs accepted at `84e12e77…`. The trunk holds the state view ([OWNER_DECISIONS_2026-09-24.md](./OWNER_DECISIONS_2026-09-24.md)). The 2026-09-25 production record does not list it, so it is not claimed shipped until verified. |
| FEAT-058 | Customer Support Investigator V1 (read-only) | SHIPPED | NOW | COMPLETE in the kernel at `2dbb97bc…` after packets 15–18. Its revisions are in production `ce791d03`, and it is on the phone through the mobile alpha (FEAT-060). Still open: the owner's live verification of the two real cases and the dogfood week. It cannot write. |
| FEAT-059 | CLIVE Live Experience V0.5 | SHIPPED | NOW | In production: merged into the production line at `d9621337` and included in `ce791d03`. History, 2026-09-23: BUILDING, with the integration candidate owner-gated and not deployed. |
| FEAT-060 | CLIVE Mobile Alpha: conversation, Objective V0 and the Support Investigator on the phone | SHIPPED | NOW | Private, read-only phone surface ([MOBILE_ALPHA.md](./MOBILE_ALPHA.md)). First in production at `ca388cee` (2026-09-23), and included in `ce791d03`. No business writes. |
| FEAT-061 | Derived truth and attention V1 | SHIPPED | NOW | Accepted at `cc5b6751…` (`clive/objective/derived-truth-attention-v1`). In production `ce791d03`. |
| FEAT-062 | Mobile dogfood voice rules | SHIPPED | NOW | Accepted at `2bd13957…` (`clive/objective/mobile-dogfood-voice-v1`). In production `ce791d03`. |
| FEAT-063 | Remote engineering loop (Objective Intake + Engineering Dispatcher V1 + Remote Engineering Control V1) | SHIPPED (ENGINEERING LOOP) | NOW | See the note below the table. |
| FEAT-064 | Generative UI V1 | BUILDING | NOW | Approved on 2026-09-24 ([GENERATIVE_UI_V1.md](./GENERATIVE_UI_V1.md), DEC-058). The microphone permission fix is merged to the trunk, not yet deployed. Objectives 2 to 4 and the capability-gap bridge were not yet done at the 2026-09-24 audit. |

**FEAT-063 in detail.** The loop is repository-only and has no deploy, secret or business-write authority ([REMOTE_ENGINEERING_CONTROL_V1.md](./REMOTE_ENGINEERING_CONTROL_V1.md), [ENGINEERING_DISPATCHER_V1.md](./ENGINEERING_DISPATCHER_V1.md)).
- It runs on three machines:
  - the production host, with two builders;
  - `clive-worker-01`, an HPE server with eight builders;
  - the owner's Mac, which is being set up.
- All builders run `claude-opus-5-5`.
- Every candidate gets an exact-SHA independent review.
- The owner's one-trunk rule (DEC-058) governs what counts as finished.
- The journal-safe repair is merged to the trunk, not yet deployed.
- It supersedes FEAT-013, FEAT-014 and FEAT-044, and the `engineering-team-activation-v1` objective.

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
