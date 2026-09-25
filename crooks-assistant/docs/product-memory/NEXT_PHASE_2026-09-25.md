# Next Phase and Captured Directions - 2026-09-25

**Status:** the order in section 2 was APPROVED by the owner on 2026-09-25 and starts when the finish list in section 1 is clear. Everything in section 3 is CAPTURED unless marked otherwise; nothing here is scheduled work until the owner approves it. Captured from the owner's messages and the Director's proposals in the 2026-09-24 and 2026-09-25 sessions.

## 1. Finish first (owner rule, 2026-09-25)

Finish everything already started before starting anything new. The finish list is PROJECT_AUDIT_2026-09-24.md section 7 plus what 2026-09-25 added: the trunk repair, the approved loop update (OWNER_DECISIONS_2026-09-25.md), deploy bundles, Generative UI V1 objectives 2 to 4, Build from CLIVE objective 2, the product-memory consolidation, the Mac loop, and moving engineering off the production host.

## 2. The next phase, in order (APPROVED)

1. **Eyes:** real-browser screenshots (Playwright CLI from the source shelf) of every user-interface and theme candidate, at phone and desktop sizes, as evidence for review and for the owner.
2. **Taste:** Taste Skill and Vercel's web design guidelines, frozen at pinned versions, loaded as skills for builders doing interface work and turned into automatic review checks.
3. **The absorbing machine:** Source Assimilation V1 (SOURCE_ASSIMILATION_V1.md): quarantine, inventory, compare with what CLIVE has, propose objectives, measure, prove or drop. Steps 1 and 2 are done semi-manually first so the machine is designed from real cases.
4. **The rest of the shelf** (SOURCE_SHELF.md), pulled in only when a real need appears; new keys, data leaving the host and spend stay owner-gated.

The owner's image for this is agar.io: CLIVE grows by absorbing what it meets. The rule that keeps it right is the game's own catch: mass makes you slow. Absorb the useful part, not the whole repository; measure it; drop what does not earn its place.

## 3. Captured directions and ideas

Each item below has its own entry in IDEAS.md, IDEA-060 to IDEA-089, in this order.

### 3.1 Building other projects through the loop
- **The Shopify theme** (Horizon 3.5.0, storefront roadmap: navigation, product page, homepage, lookbook, events, tracking and returns, Crack the Cuffs integration, performance pass) built by the loop: Shopify theme checks, screenshots, independent review, pushed to an unpublished preview theme, published only on the owner's tap with the previous version one tap away. Needs a theme access credential (owner step). Proposed as the first new project after the next phase. Base44 apps do not fit, because they are not in git.

### 3.2 Loop throughput and autonomy
- Automatic landing into the trunk once checks pass, the independent review is ready and GitHub acceptance is green on the exact SHA.
- Automatic follow-up: when an objective lands, its dependent objective is queued; blocked objectives are re-planned with their reason instead of waiting for the Director.
- A multi-loop router that spreads objectives across the loops by published capacity.
- The automatic job splitter (owner, 2026-09-25): failures in several parts are split into separate workers so each is fixed faster and more specifically.
- A continuous Director: today the Director acts only while the owner is in a chat, so finished work waits; landing, requeuing and next-step queuing should not depend on that.
- The status projection publishes the open review findings, failing check output and worker reports (objective `status-publishes-findings`, parked under the finish-first rule).

### 3.3 Builder efficiency (lessons from 2026-09-25)
- Builders run their declared checks (APPROVED, being built).
- Match the model to the job class (Opus for design and hard problems, Sonnet for routine changes, Haiku for lint and wording).
- Repository maps so builders do not rediscover the code each time; pre-warmed workspaces.
- Scope lessons for whoever writes objectives: include the tests and generators a change will obviously touch; builders cannot delete files or run commands; checks must be runnable inside the builder sandbox; a new base commit must have been fetched by the loop before it is used.

### 3.4 The local server's roles (clive-worker-01)
- Engineering host (APPROVED in OWNER_DECISIONS_2026-09-25.md) with builders' working copies in memory.
- Proving ground: the full suite in parallel on every candidate, clock-boundary sweeps (UK midnight, month end, clock changes), nightly mutation testing, replay of real sessions (IDEA-024), phone-screen screenshots.
- Preview stage: each finished objective runnable as a live CLIVE preview over Tailscale, the "preview, then ship" button.
- Field operations: browser agents for sites without APIs (courier tracking, supplier portals, marketplaces), the Nightly Observer (IDEA-022), brand media processing such as TikTok edits.
- Business memory: a local mirror of Shopify, Gmail metadata and analytics for instant answers, semantic search over the business's history, a local Whisper fallback for voice, encrypted off-site backups.

### 3.5 Capacity and ways of building
- For many parallel builders, the Claude API or a Team plan rather than stacked consumer subscriptions.
- Cloud-session credits for work that needs a command line or eyes.
- Hybrid building: the loop for anything that must be correct and safe; a direct session with a browser for visual design, landing through the same checks and trunk.

### 3.6 Product capabilities shown in the Generative UI examples
- "What needs me today": at most three ranked items across orders, email and stock, then one quiet line saying everything else is on track (IDEA-007, IDEA-049).
- Stock run-out prediction from sell-through rate, raised as a risk, with a waitlist proposal.
- Courier tracking (IDEA-002) to close the shipping-evidence gap, offered through the capability-gap bridge.
- A Resend connection (IDEA-003): read delivery events and resend published templates such as `shipped-today`, with the `ship-email-sent` tag as the duplicate guard, a last-moment recheck and delivery verification.
- Every capability outage explained in plain words with its cause and the owner's fix (shipped for voice credits on the trunk; general principle captured).

### 3.7 How the build system is judged (owner-agreed, 2026-09-25)
Two measures: hours from asking to seeing it on the phone, and minutes of the owner's attention per change. If the loop does not clearly beat asking a model directly on both, it is cut back to the one trunk, the tests and reviewed deploys.

### 3.8 From the external review of 2026-09-25
One kernel for engineering and business work, the Judgment Ledger as the record of the owner's authority, a local SQLite store, the blind self-audit, and hardening of the loop's service. Parked until the finish list is clear, apart from what the approved loop update already covers. See EXTERNAL_REVIEW_2026-09-25.md.
