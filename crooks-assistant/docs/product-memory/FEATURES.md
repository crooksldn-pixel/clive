# CROOKS OS — Feature Register

**Last consolidated:** 2026-09-25 (product-memory consolidation: statuses corrected to production `clive/trunk` `ce791d03`, deployed 2026-09-25, and to the remote engineering loop; FEAT-060 to FEAT-070 added). Earlier consolidations: 2026-09-23 (rows FEAT-010 to FEAT-014 updated and FEAT-055 to FEAT-059 added from the 2026-09-23 engineering state) and 2026-09-19 (all other rows). Where a status changed, the note keeps what the row said before.

This file tracks features that are approved, planned, building, testing, or shipped. Brainstorming that has not been accepted belongs in `IDEAS.md`.

| ID | Feature | Status | Phase | Notes |
|---|---|---|---|---|
| FEAT-001 | Existing FastAPI CROOKS backend | SHIPPED | V1 | Current core runtime. |
| FEAT-002 | Claude Agent SDK / Max integration | SHIPPED | V1 | Current reasoning provider path. |
| FEAT-003 | Shopify read/write capability layer | SHIPPED / HARDENING | V1 | Existing action safeguards remain canonical. |
| FEAT-004 | Gmail integration | SHIPPED / HARDENING | V1 | Gmail OAuth provisioned by the owner on the production host on 2026-09-24, stored outside every checkout, unattended refresh verified (OWNER_DECISIONS_2026-09-24). Writes remain behind the action gate. Was: "Linux token persistence being formalised." |
| FEAT-005 | ElevenLabs Scribe STT | SHIPPED | V1 | Primary STT. It uses the same ElevenLabs account whose credits were exhausted on 2026-09-25 (see FEAT-006); its live state on the server is not recorded here, so verify before relying on it. |
| FEAT-006 | Derek TTS | NOT SHIPPED ON THE SERVER | V1 | The Derek voice is unavailable on the production server because the ElevenLabs credits are exhausted (2026-09-25). Restoring it is an owner spend decision. The honest wording and health for this outage are in the trunk, not yet deployed (FEAT-066). Was: SHIPPED, "Existing voice output" (2026-09-19 register, Mac-era runtime). |
| FEAT-007 | Proposal/action/verification system | SHIPPED | V1 | Safety-critical; preserve semantics. |
| FEAT-008 | Samsung browser/PWA client | SHIPPED / POLISH | V1 | Needs UX/UI refinement. Samsung verification on the Linux runtime is still outstanding. |
| FEAT-009 | CROOKS Control Mac app | SHIPPED / POLISH | Phase 6 | Exists but still engineering-like. |
| FEAT-010 | Always-on Hetzner deployment | SHIPPED | NOW | Production `/opt/crooks-os` runs `clive/trunk` `ce791d03`, deployed 2026-09-25 after a green GitHub acceptance run on that exact SHA and an independent exact-SHA review with zero findings; deploys now come from the trunk. History: ratified at `1cf3a0f3…` on 2026-09-19 (DEC-048); mobile alpha `ca388cee` on 2026-09-23. Was, 2026-09-19: BUILDING, "Linux/systemd/Tailscale migration in review". |
| FEAT-011 | Linux secret architecture | SHIPPED / HARDENING | NOW | Static and mutable secrets in use on the production host; Gmail OAuth provisioned 2026-09-24. Synthetic credentials in tests are assembled at runtime through one shared helper, never baselined (OWNER_DECISIONS_2026-09-25). New secret provisioning remains owner-gated. Was: TESTING, "Gmail OAuth still outstanding" (2026-09-23); "Static vs mutable secret handling under review" (2026-09-19). |
| FEAT-012 | Tailscale private HTTPS runtime | SHIPPED | NOW | Tailnet-only HTTPS active and ratified (DEC-048). Was, 2026-09-19: TESTING, "Code path prepared; live activation pending". |
| FEAT-013 | Claude GitHub inbox/outbox bridge | SUPERSEDED | NOW | Superseded by the remote engineering loop (FEAT-063); the bridge watcher that drove it was retired on 2026-09-25 (DEC-058). Was: SHIPPED / HARDENING, "Manual bridge works." |
| FEAT-014 | Automatic Claude inbox watcher | RETIRED | NOW | Retired on 2026-09-25 by owner decision; the remote engineering loop does its job (OWNER_DECISIONS_2026-09-24, DEC-058). History, 2026-09-23: SHIPPED / HARDENING, installed and enabled with the hourly supervisor disabled; reviewed source `5ada7b47…` pinned `claude-fable-5-1` at high effort, but a read-only live-host probe on 2026-09-23 found the loaded unit carrying `claude-opus-5`. 2026-09-19: TESTING, "Built; review required before install." |
| FEAT-015 | iPhone responsive access | SHIPPED / POLISH | NOW | The phone surface is the mobile alpha (FEAT-060), in production; native later (FEAT-047). Was: PLANNED, "Initial via web/PWA; native later." |
| FEAT-016 | Current UI polish pass | BUILDING | NOW | Carried by Generative UI V1 (FEAT-068). Was: PLANNED, "Highest product priority after deployment." |
| FEAT-017 | Response-quality/latency pass | PLANNED | NOW | Entity focus, verbosity, tool routing, speed. First fix, needs-reply routing (FEAT-064), is in the trunk, not yet deployed. |
| FEAT-018 | Structured real-world test backlog | PLANNED | NEXT | Convert telemetry into engineering issues. |
| FEAT-019 | CROOKS World entity graph | PLANNED | NEXT | Persistent business state. |
| FEAT-020 | Event Ledger | PLANNED | NEXT | Durable provenance/event history. |
| FEAT-021 | Expectations/deadline extraction | PLANNED | NEXT | Casual statements become monitored expectations. |
| FEAT-022 | Attention engine | PLANNED | NEXT | “What needs my attention?” V1 semantics shipped as derived truth and attention (FEAT-061); the full engine remains planned. |
| FEAT-023 | Selective notifications | PLANNED | NEXT | Material exceptions only. |
| FEAT-024 | Automation/Objectives engine | PLANNED | NEXT | Scheduled/event/conditional/stateful/goal-based. Objective V0 is live in the mobile alpha (FEAT-060). |
| FEAT-025 | Earned autonomy | PLANNED | NEXT/LATER | Narrow action-class autonomy after evidence. |
| FEAT-026 | WhatsApp integration | CAPTURED | NEXT/LATER | Supplier/customer messaging and triggers. |
| FEAT-027 | Click & Drop integration | CAPTURED | NEXT/LATER | Labels, tracking, fulfilment verification. |
| FEAT-028 | Resend integration | CAPTURED | NEXT/LATER | Transactional outbound email. See IDEA-082. |
| FEAT-029 | Stripe integration | PLANNED | NEXT/LATER | Payment/refund context and events. |
| FEAT-030 | Drive/Notes/document context | CAPTURED | NEXT/LATER | Linked business documents. |
| FEAT-031 | Base44 capability integration | CAPTURED | NEXT/LATER | Bring internal apps behind CROOKS. |
| FEAT-032 | Model Gateway | PLANNED | LATER | Provider fallback/routing/model independence. |
| FEAT-033 | Anticipation engine | PLANNED | LATER | Detect important missing/abnormal events. |
| FEAT-034 | Scene compiler | PLANNED | LATER | Contextual UI generation. Now being built as Generative UI V1 (FEAT-068). |
| FEAT-035 | Multi-user/staff roles | CAPTURED | LATER | Scoped interfaces/capabilities. |
| FEAT-036 | Nightly Observer | PLANNED | LATER | Evidence-backed issue discovery. |
| FEAT-037 | Historical replay framework | PLANNED | LATER | Before/after regression evidence. |
| FEAT-038 | Builder/staging worktree system | PLANNED | LATER | Isolated candidate development. Isolated builder workspaces now exist inside the remote engineering loop (FEAT-063); staging/preview is IDEA-073. |
| FEAT-039 | Morning self-improvement report | CAPTURED | LATER | Owner-facing summary of overnight engineering. |
| FEAT-040 | Claude Dev Manager | CAPTURED | LATER | Decompose broad objectives. |
| FEAT-041 | Specialist dev agents | CAPTURED | LATER | UI/UX/debug/feature/QA/perf/security/integration. |
| FEAT-042 | Independent specialist reviewers | CAPTURED | LATER | “Voice of reason” at each layer. |
| FEAT-043 | GPT Director | CAPTURED | LATER | Independent top-level engineering reviewer. The exact-SHA GPT reviewer runs in the loop; the runtime Director is not implemented (IDEA-065). |
| FEAT-044 | Automatic GPT ↔ Claude loop | SHIPPED | LATER | Delivered as the remote engineering loop (FEAT-063): Claude builders, exact-SHA GPT review, bounded repair, no owner courier. Was: CAPTURED, "Iterative engineering without owner message ferrying." |
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
| FEAT-055 | Repository-only lifecycle kernel (engineering control plane) | SHIPPED / FROZEN | NOW | Frozen at `18c3153a…` (packet 14 READY); byte-identical in `clive/trunk`; it is the lifecycle authority inside the running remote engineering loop (FEAT-063). Further kernel work only on dogfood evidence of a core-invariant failure. Was, 2026-09-23: TESTING, "Not deployed as a service." |
| FEAT-056 | Judgment ledger, exact-SHA review contract and CI acceptance provenance | SHIPPED | NOW | The judgment ledger CI stream and corrections are in production (`ce791d03`); the `acceptance` workflow runs its gates on every push; mechanical gates produce evidence, not permission. The ledger is still read-only: nothing writes owner decisions yet (IDEA-086). Was, 2026-09-23: TESTING, on the CI stream at `b68e6e82…`. |
| FEAT-057 | Agent Environment authoritative state | TESTING | NOW | Read-only projection of kernel records; truth repairs accepted at `84e12e77…`. In `clive/trunk` since 2026-09-24 (OWNER_DECISIONS_2026-09-24); it is not among the production contents recorded for `ce791d03`, so its deployed state is not claimed here. |
| FEAT-058 | Customer Support Investigator V1 (read-only) | SHIPPED | NOW | Accepted at r5 `2dbb97bc…` (2026-09-23) after packets 15–18; the revisions are in production (`ce791d03`) and on the phone through the mobile alpha. Cannot write. The owner's verification of the two real cases and a first live run on the server are not recorded here. Was, 2026-09-23: TESTING, "owner verification, first live run, CI-stream landing and deployment pending". |
| FEAT-059 | CLIVE Live Experience V0.5 | SHIPPED | NOW | In production: merged into the production line at `d9621337…` and part of `ce791d03`. Was, 2026-09-23: BUILDING, "integration candidate owner-gated; not accepted, not deployed". |
| FEAT-060 | CLIVE mobile alpha (conversation, Objective V0, Support Investigator on the phone) | SHIPPED | NOW | Private, read-only phone surface ([MOBILE_ALPHA.md](./MOBILE_ALPHA.md)); in production since `ca388cee` (2026-09-23) and part of `ce791d03`. |
| FEAT-061 | Derived truth and attention V1 | SHIPPED | NOW | Accepted at `cc5b6751…`; in production (`ce791d03`). First shipped slice of FEAT-022. |
| FEAT-062 | Mobile dogfood voice rules | SHIPPED | NOW | Accepted at `2bd13957…`; in production (`ce791d03`). |
| FEAT-063 | Remote engineering loop (Remote Engineering Control V1 + Objective Intake and Engineering Dispatcher V1) | SHIPPED / HARDENING | NOW | Runs on three machines, all builders on `claude-opus-5-5`: the production host (two builders), `clive-worker-01` (HPE, eight builders) and the owner's Mac (being set up). Exact-SHA independent review, bounded repair; the one-trunk rule decides what is finished. Approved 2026-09-25 and in force only after the owner-gated re-pin: builders run declared checks, green GitHub acceptance before acceptance and landing, protected loop and safety-core paths; engineering moves off the production host once clive-worker-01 has proven itself. See [REMOTE_ENGINEERING_CONTROL_V1.md](./REMOTE_ENGINEERING_CONTROL_V1.md), [ENGINEERING_DISPATCHER_V1.md](./ENGINEERING_DISPATCHER_V1.md), [INFRASTRUCTURE_2026-09-25.md](./INFRASTRUCTURE_2026-09-25.md). |
| FEAT-064 | Needs-reply routing | TESTING | NOW | Merged to `clive/trunk`, not yet deployed. Fixes the 2026-09-24 misreading of "customers who need a reply" (GENERATIVE_UI_V1 §2). |
| FEAT-065 | Microphone permission fix | TESTING | NOW | Merged to `clive/trunk`, not yet deployed. Permission requested only on the first hold-to-speak (GENERATIVE_UI_V1 §4). |
| FEAT-066 | Voice-credits wording and health | TESTING | NOW | Merged to `clive/trunk`, not yet deployed. Explains the ElevenLabs credits outage in plain words with its cause and fix (IDEA-083). |
| FEAT-067 | Remote-engineering journal-safe repair | TESTING | NOW | Merged to `clive/trunk`, not yet deployed. Removes the loop's dependence on a host-local exclude line (REMOTE_ENGINEERING_CONTROL_V1, journal-safe adapter records). |
| FEAT-068 | Generative UI V1 | BUILDING | NOW | Approved 2026-09-24 ([GENERATIVE_UI_V1.md](./GENERATIVE_UI_V1.md)). On the trunk by 2026-09-26: objective 1 (scenes, renderer, gallery), 2a (renderer), 2b (owner settings) and 3a (the scene planner, behind `CLIVE_SCENES`, off by default). The capability-gap bridge (objective 4) remains. |
| FEAT-069 | Source Assimilation V1 | APPROVED | NEXT | Approved 2026-09-24 ([SOURCE_ASSIMILATION_V1.md](./SOURCE_ASSIMILATION_V1.md)); step 3 of the approved next phase, after the finish list. |
| FEAT-070 | Engineering Team Activation V1 | SUPERSEDED | NOW | Accepted at `e41e80b4…` on its own branch, then blocked from 2026-09-23 for want of an eligible independent reviewer; superseded by the remote engineering loop (FEAT-063) and closed by owner decision (OWNER_DECISIONS_2026-09-24). |
| FEAT-071 | Knowledge Digester V1 | BUILDING | NOW | Owner direction 2026-09-26: digest every kind of artifact, reversibly ([KNOWLEDGE_DIGESTER_V1.md](./KNOWLEDGE_DIGESTER_V1.md)); the working form of FEAT-069. Waves 1–4 on the trunk (PRs #25, #26, #28): intake into a read-only quarantine (git, archives, folders, files, URLs, npm and PyPI packages), scan, recognition, six adapters, the self-model, relation, ranked licence-aware proposals with removal handles, and self mode for CLIVE's why-index; two command-line entries. Nothing is absorbed yet and none of it reaches the phone: wave 5 (absorbers, phone scenes, "digest this"). First digestions: [DIGESTIONS_2026-09-26.md](./DIGESTIONS_2026-09-26.md). |
| FEAT-072 | Build objectives from CLIVE | BUILDING | NOW | Owner direction 2026-09-26: build objectives filed in CLIVE go to the engineering loop instead of stopping at "GitHub isn't connected". An objective of kind `build`; `submit_engineering_request` needs only the title, the outcome, what done looks like and the parts of CLIVE it may change (`engineering_status` lists them), and fills in the base (the trunk's head, by SHA), the id and the checks (the named tests, or one it adds, and ruff, with the builders' interpreter); it files to `CROOKS_ENGINEERING_HOST`'s own inbox (default clive-worker-01) on the owner's tap, then links the request to its objective. The phone shows build objectives with their progress. Needs the owner's GitHub token (`github_engineering_inbox_token`) and changes switched on. Next: the capability-gap record (which gaps recur, which were built, whether they stopped recurring). |

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
