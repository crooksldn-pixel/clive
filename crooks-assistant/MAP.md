# CLIVE: the map

Read this before any code. The hand-written parts change only with a decision. The tables between `map:` markers come from `scripts/map.py`: rerun it after a change, and `--check` says whether one is stale.

<!-- map:live -->
**Production:** `b33ccbc2`, deployed 2026-10-03 17:48 UTC ([`reports/deploy-b33ccbc2.md`](reports/deploy-b33ccbc2.md)). **Before it:** `cac1a9e7` 2026-10-03 13:01 UTC ([`reports/deploy-cac1a9e7.md`](reports/deploy-cac1a9e7.md)); `66d3e05d` 2026-10-02 13:49 UTC ([`reports/deploy-66d3e05d.md`](reports/deploy-66d3e05d.md)).
**Tools:** 93 tools — 62 reads, 26 writes, 5 bulk ([`TOOL_MATRIX.md`](docs/phase4/TOOL_MATRIX.md)).
<!-- /map:live -->

## Where we started (7 September 2026)

Quotation marks mark George's own words. The rest is as recorded from what he said.

1. **A voice assistant for CROOKS LDN, a "real-world Jarvis" for the office.** Hold a button, ask out loud, hear the answer. Sources: his 7 Sep brief and Day 1 spec (his Claude artifacts), and the first commit `c4d9e64f`. Of the voice spec he later wrote for CLIVE: "i created this for the personality i want clive to have" (DEC-065).
2. **Reliable and simple before fashionable.** Something reliable and free that answers in 3–5 seconds beats a theoretical sub-second one, at £0 a month. Source: the 7 Sep brief.
3. **Never pretend an action worked when a tool failed.** Sources: the 7 Sep brief, the founding README of `c4d9e64f`, and DEC-005.
4. **Reads are automatic; refunds, cancellations, price changes and money need his explicit yes.** That is green, amber and red. Sources: the 7 Sep brief, `app/tools/gate.py` since the first commit, and DEC-005 to DEC-007.
5. **He stops being the "human terminal courier".** CLIVE becomes the one business entity behind the scenes, a "human API" that works alongside him and takes over wherever it can. Sources: his statements of September and October, DEC-015 and DEC-051.

## The rules that never bend

1. **Verified, or it is an error.** A change is proved by reading it back. A failed tool is reported as a failure, never as success (DEC-005; `app/actions/engine.py`).
2. **Anything outward waits for a gesture on its card.** Nothing spends money, messages a customer or outsider, or changes the shop without that gesture, and a spoken "yes" never applies a change. Make the gesture faster to give; never skip it (DEC-006; `app/actions/grammar.py`).
3. **Unknown is RED.** An unregistered tool or write fails closed (DEC-007; `app/tools/gate.py`).
4. **Customer details stay private.** They never go into logs, URLs, attributes, telemetry or build requests. Every recorded event passes one redaction seam, `observability/timeline.scrub` (`docs/RECORDING.md`).
5. **No pay-as-you-go billing.** The app refuses to start with an Anthropic API key in its environment (`assert_no_payg_credentials`).
6. **Finished means on `clive/trunk` and green** on full acceptance at that exact SHA. Deploys come only from the trunk (DEC-058).
7. **Every typed or spoken sentence is a model turn.** Nothing matches phrases in front of the model; taps stay deterministic (DEC-063). One exception is open: `web/today-say.js` (Parked).
8. **Never weaken** a test assertion, an approval, the gate, the kernel, secret scanning or the acceptance machinery (DEC-064).

## A turn, end to end

```
phone or tablet (web/index.html) · a team phone (/today)
  hold → live-voice.js → POST /voice/live (the words while he holds)  ·  type → POST /turn (text)
  release → POST /turn (audio) → speech/decode → ElevenLabs Scribe → words
routes/turn.py → session/ · system prompt (kb/loader: who CLIVE is, his voice spec, the rules)
  → providers/max_agent_sdk.py: Claude through the Agent SDK on his Max plan; the tools as in-process MCP
  → every tool call, through a PreToolUse hook: tools/gate.py GREEN/AMBER/RED · tools/authority.py owner or staff
  → tools/dispatch.py → reads: Shopify, Gmail, analytics, Instagram, Ship24, the screens
                      → writes: STAGED as a proposal in actions/engine.py, never executed here
  → presentation.py + focus.py (only what the answer is about; words, not cards, while it works: DEC-069)
    + screen.py → cards (web/ui.js draws them); a scene too only if CLIVE_SCENES is on
  → speech/speakable → POST /speak → the ElevenLabs voice
he holds the card → POST /actions/{id}/arm → /commit → identity.py (Tailscale whois) → re-read → execute → verify → actions.jsonl
every step → observability/timeline.scrub → the interaction record (logs/interactions/)
```

## Parts

One row per package in `app/`. **Live**: the running app imports it, from `app.main`. **CLI**: only a script does.

<!-- map:parts -->
| Package | Lines | State | Not loaded by the app | Owner doc |
|---|---:|---|---|---|
| (top-level modules) | 12,264 | live | `engineering_measures` | none |
| `actions` | 3,045 | live | — | [`DECISIONS.md`](docs/product-memory/DECISIONS.md) DEC-005–007 |
| `analytics` | 2,930 | live | — | none |
| `anticipation` | 1,501 | live | — | none |
| `bench` | 2,300 | live | 5 modules | [`BENCH.md`](docs/BENCH.md) |
| `builds` | 1,424 | live | — | none |
| `capabilities` | 759 | live | `surface` | none |
| `clients` | 6,429 | live | — | [`DEPLOY_LINUX.md`](docs/DEPLOY_LINUX.md) their keys |
| `connections` | 2,005 | live | — | [`CONNECTIONS.md`](docs/CONNECTIONS.md) |
| `context` | 1,211 | live | — | none |
| `customers` | 1,596 | live | — | none |
| `digest` | 18,960 | live | 19 modules | [`KNOWLEDGE_DIGESTER_V1.md`](docs/product-memory/KNOWLEDGE_DIGESTER_V1.md) |
| `displays` | 2,363 | live | — | none |
| `engineering_bridge` | 742 | live | — | [`REMOTE_ENGINEERING_CONTROL_V1.md`](docs/product-memory/REMOTE_ENGINEERING_CONTROL_V1.md) |
| `families` | 10,246 | live | — | none |
| `kb` | 445 | live | — | [`OWNER_DECISIONS_2026-10-01.md`](docs/product-memory/OWNER_DECISIONS_2026-10-01.md) the voice spec |
| `logging` | 195 | live | — | none |
| `memory` | 586 | live | — | none |
| `messaging` | 2,309 | live | — | [`WECOM.md`](docs/WECOM.md) WeCom; WhatsApp in WHATSAPP.md, Instagram DMs in INSTAGRAM_DMS.md |
| `objectives` | 3,316 | live | — | none |
| `observability` | 11,308 | live | `proposals` | [`RECORDING.md`](docs/RECORDING.md) |
| `orchestrator` | 10,626 | live | — | [`ENGINEERING_DISPATCHER_V1.md`](docs/product-memory/ENGINEERING_DISPATCHER_V1.md) |
| `people` | 777 | live | — | [`TEAM.md`](docs/TEAM.md) |
| `providers` | 1,029 | live | `anthropic_api` | none |
| `reads` | 1,451 | live | — | none |
| `release` | 2,088 | live | 9 modules | [`RELEASE_SERVICE.md`](docs/RELEASE_SERVICE.md) |
| `remote_engineering` | 2,506 | live | — | [`REMOTE_ENGINEERING_CONTROL_V1.md`](docs/product-memory/REMOTE_ENGINEERING_CONTROL_V1.md) |
| `returns` | 818 | live | — | none |
| `routes` | 8,468 | live | — | none |
| `scenes` | 2,579 | off (`CLIVE_SCENES` off, default) | — | [`GENERATIVE_UI_V1.md`](docs/product-memory/GENERATIVE_UI_V1.md) |
| `secrets` | 960 | live | — | [`DEPLOY_LINUX.md`](docs/DEPLOY_LINUX.md) |
| `session` | 1,242 | live | — | none |
| `shipping` | 335 | live | `fixture` | none |
| `skills` | 979 | CLI | all | [`SOURCE_ASSIMILATION_V1.md`](docs/product-memory/SOURCE_ASSIMILATION_V1.md) |
| `speech` | 844 | live | — | none |
| `support` | 1,693 | live | `redact` | [`SUPPORT_INVESTIGATOR_V1.md`](docs/product-memory/SUPPORT_INVESTIGATOR_V1.md) |
| `tools` | 15,107 | live | — | [`TOOL_MATRIX.md`](docs/phase4/TOOL_MATRIX.md) |
| `work` | 1,374 | live | — | [`TEAM.md`](docs/TEAM.md) |
<!-- /map:parts -->

## Pages

<!-- map:pages -->
| Address | Page | Scripts it loads |
|---|---|---|
| `/bench/cards` | `bench-cards.html` | 2: ui.js, bench-cards.js |
| `/bench` | `bench.html` | 1: bench.js |
| `/connections` | `connections.html` | 3: connections-view.js, connections-voice.js, connections.js |
| `/display` | `display.html` | 2: dots.js, display.js |
| `/` | `index.html` | 29: dots.js, startup.js, orb.js, audio-viz.js, live-voice.js, collide.js, touch.js, telemetry.js, notify.js, action-state.js, live-state.js, jobs.js, objective-touch.js, objective-number.js, objective-cards.js, customers.js, returns.js, messages.js, shipping.js, ui.js, app.js, horizon.js, distances.js, builds.js, alpha.js, remote.js, lift.js, edges.js, dots-app.js |
| no route (only `/static/scenes-gallery.html`) | `scenes-gallery.html` | 2: scenes.js, scene-fixtures.js |
| `/today` | `today.html` | 6: orb.js, objective-touch.js, today-say.js, today-voice.js, today.js, today-owner.js |
<!-- /map:pages -->

## Stores

<!-- map:stores -->
| Store | File | Written by | On |
|---|---|---|---|
| Objectives | `obj_*.json` | `objectives/store.py` | always |
| Capability gaps | `gaps.json` | `objectives/gaps.py` | always |
| Screens | `displays.json` | `displays/store.py` | always |
| Instagram token state | `instagram.json` | `clients/instagram.py` | always |
| People cards | `people.json` | `people/store.py` | always |
| Work list | `work/items/, routines.json, record.jsonl` | `work/store.py` | always |
| Team access | `access.json` | `people/access.py` | always |
| Passkeys | `passkeys.json` | `connections/passkeys.py` | always |
| Connections ledger | `changes.jsonl` | `connections/ledger.py` | always |
| Voice choice | `voice.json` | `speech/voice_prefs.py` | always |
| Action audit | `actions.jsonl` | `actions/ledger.py` | always |
| Owner judgments | `owner-judgments.jsonl` | `builds/decisions.py` | always |
| Interaction record | `logs/interactions/` | `observability/interactions.py` | `CROOKS_INTERACTION_RECORD` on (template) |
| Test sessions | `logs/test-sessions/` | `observability/session.py` | `CROOKS_TEST_SESSION_ALWAYS` off (template) |
| Experience recordings | `logs/experience-recordings/` | `observability/recorder.py` | `CROOKS_RECORD_EXPERIENCE` off (template) |
| Turn log | `logs/turns.jsonl` | `logging/turnlog.py` | always |
| Capability manifest | `capabilities.json` | `capabilities/delta.py` | always |
| Anticipation | `anticipation/transitions.json` | `anticipation/learning.py` | always |
| Keys stored from the app | `<secret dir>/app/<key>.cred` | `secrets/vault.py` | always |
| Digest store | `one folder per artifact` | `digest/store.py` | always |
| Release service | `status.json, deploys/, failed/, HALT` | `release/state.py` | `CLIVE_RELEASE_ENABLED` off (default) |
| Bench sets and runs | `bench/questions/, bench/runs/` | `bench/runner.py` | CLI only |
| Bench ratings | `bench/ratings.jsonl` | `bench/store.py` | always |
| Messages (90 days) | `messaging/threads/, cursors.json` | `messaging/store.py` | always |
<!-- /map:stores -->

## Switches

<!-- map:switches -->
Production is as recorded by [`reports/deploy-66d3e05d.md`](reports/deploy-66d3e05d.md) (2026-10-02 13:49 UTC); `b33ccbc2`, `cac1a9e7` left the switches untouched. "not recorded" means no record says.

| Switch | Code default | Template | Production |
|---|---|---|---|
| `CLIVE_RELEASE_DRY_RUN` | on | absent | not recorded |
| `CLIVE_RELEASE_ENABLED` | off | absent | not recorded |
| `CLIVE_RELEASE_RULE` | off | absent | not recorded |
| `CLIVE_SCENES` | off | absent | not recorded |
| `CROOKS_CANCEL_NOTIFY` | on | on | not recorded |
| `CROOKS_CANCEL_REFUND` | on | on | not recorded |
| `CROOKS_CANCEL_RESTOCK` | on | on | not recorded |
| `CROOKS_ENGINEERING_HOST` | off | unset | worker-01 |
| `CROOKS_ENGINEERING_PRIVATE_URL` | off | absent | not recorded |
| `CROOKS_FULFIL_NOTIFY` | off | off | not recorded |
| `CROOKS_INTERACTION_RECORD` | on | on | not recorded |
| `CROOKS_INTERACTION_RECORD_WORDS` | off | off | not recorded |
| `CROOKS_LIVE_TRANSCRIPT` | on | on | not recorded |
| `CROOKS_LOCAL_OWNER` | off | unset | unset |
| `CROOKS_RECORD_EXPERIENCE` | off | off | not recorded |
| `CROOKS_RECORD_TRANSCRIPTS` | off | off | not recorded |
| `CROOKS_REFUND_NOTIFY` | on | on | not recorded |
| `CROOKS_SAVE_CAPTURES` | off | off | not recorded |
| `CROOKS_SCREEN_SNAPSHOTS` | off | off | off |
| `CROOKS_TAILSCALE_VERIFY` | on | unset | unset |
| `CROOKS_TEST_SESSION_ALWAYS` | off | off | not recorded |
| `CROOKS_TTS_ENABLED` | on | on | not recorded |
| `CROOKS_TTS_PREFETCH` | on | on | not recorded |
| `CROOKS_WHISPER_ENABLED` | on | off | not recorded |
| `CROOKS_WRITES_ENABLED` | off | off | on |
| `CROOKS_WRITES_LOCAL_OWNER` | off | off | off |
<!-- /map:switches -->

## Parked

Unwired, off or dropped, but still in the code or the repository. By the expiry date each one is wired in, deleted, or re-decided with a new date.

| What | Why it is parked | The decision | Expires |
|---|---|---|---|
| **Split**: fork, focus, background, merge and cancel in `routes/branches.py`, plus the Split code in `web/app.js` | Retired 20 Sep (DEC-050) but never deleted. `web/alpha.css` hides it, and `splitOrb()` has no caller | Delete, once he confirms DEC-050 | 19 Oct |
| **Scenes**: `app/scenes/` and `web/scenes*` | Generative UI V1 was approved 24 Sep (DEC-058), but `CLIVE_SCENES` is off and no page loads the renderer | His call: ten real questions, cards against scenes; keep the winner | 19 Oct |
| **The Mac runtime**: `mac/` (the menu-bar app), `launchd/`, `install_launchd.py`, `whisper_server.py`, `clients/whisper.py` | The Mac is not a production or rollback host (DEC-058), and Whisper is off in production (DEC-022) | Delete, on his yes | 19 Oct |
| **The experience recorder**: `observability/recorder.py`, `scripts/record.py` | Off; the interaction record does its job | Delete | 19 Oct |
| **The returns stub**: `app/returns/`, `families/returns.py` | It says returns are not implemented, but CROOKS Returns is live (DEC-066) | Delete with PR #96 | 19 Oct |
| **Easyship**: `app/shipping/`, `families/shipping.py` | Disconnected. Tracking is Ship24, and return labels are Parcel2Go through CROOKS Returns | Delete until he chooses a label provider | 19 Oct |
| **`capabilities/surface.py`** | Nothing imports it, and nothing reads what changed between builds | Wire up "what's new since the last build", or delete it | 19 Oct |
| **CROOKS Pad**: `android/`, `observability/pad.py`, `routes/pad.py` | The APK was never installed; the heartbeat has no other sender | Install it on the SM-T290, or archive it | 19 Oct |
| **`web/today-say.js`** | Acts on "packed 2106" without the model, against DEC-063 | His call: write an exception, or send the words to the team's CLIVE | 19 Oct |
| **`docs/product-memory/_incoming/`** (51 files) | Staging copies kept since 25 Sep "for the Director to remove" | Delete | 19 Oct |
| **The venture engine**: branch `claude/venture-engine-v1-2026-09-29` | His direction of 29 Sep, never landed. Finish first (DEC-018) | Stays parked until the finish list is clear | 19 Oct |

## Where the rest lives

- **What is live now:** [`CURRENT_TRUTH.md`](docs/product-memory/CURRENT_TRUTH.md).
- **Every decision and its reason:** [`DECISIONS.md`](docs/product-memory/DECISIONS.md). Add a new decision; never edit an old one's text.
- **Deploy, the server, secrets and rollback:** [`docs/DEPLOY_LINUX.md`](docs/DEPLOY_LINUX.md). Each deploy's record is in `reports/`.
- **Deploys done by a program instead (built, switched off, DEC-067):** [`docs/RELEASE_SERVICE.md`](docs/RELEASE_SERVICE.md).
- **Doctrine:** [`PRODUCT_BRAIN.md`](docs/product-memory/PRODUCT_BRAIN.md), and the product-memory [index](docs/product-memory/README.md).
- **The team, keys and recording:** [`TEAM.md`](docs/TEAM.md), [`CONNECTIONS.md`](docs/CONNECTIONS.md) and [`RECORDING.md`](docs/RECORDING.md).
- **The build loop:** [`ENGINEERING_DISPATCHER_V1.md`](docs/product-memory/ENGINEERING_DISPATCHER_V1.md). Its live status is on the branch `clive/control/worker-01-status`.
- **History:** [`docs/history/`](docs/history/): CURRENT_TRUTH before 5 Oct, and the Mac-era README.

---

<!-- map:words -->
**Read first, before → after: 34,804 → 3,368 words** (a word is a whitespace-separated token with a letter or digit in it, so table pipes do not count). Before, at `b33ccbc2`: both READMEs, CURRENT_TRUTH, DECISIONS and the 9 doctrine documents of DEC-039's start set (listed in `scripts/map.py`). After: `CLAUDE.md`, this map and CURRENT_TRUTH.
<!-- /map:words -->
