# CROOKS OS — Phase 6 — The Appliance Layer

## What Phase 6 is for

> Turn the Mac on. Turn the Samsung on. Do nothing else.

Phase 5 delivered a working business engine and a working web interface. It did not deliver a
product, because operating it required a human being who knew that Terminal existed, that
`make up` was a thing, that a URL had to be typed into a browser, and that when something
stopped answering the way to find out why was to read a log file.

Phase 6 does not touch the engine. It builds the layer around it that makes it an appliance:
something that starts by itself, stays started, reports honestly on its own health, updates
itself, and rolls itself back — and a tablet that shows CROOKS and nothing else.

The appliance layer owns **lifecycle, hardware, connectivity, boot, recovery, deployment,
testing and diagnostics**. It owns no business logic at all.

## The layering

```
  CROOKS CONTROL  (native macOS app)
        │            lifecycle · updates · rollback · tests · diagnostics
        │            knows one command: scripts/control.py
        ▼
  scripts/control.py + scripts/service.py     (the ops layer, Python)
        │            launchd · health · git · known-good builds
        ▼
  CROOKS OS BACKEND  (FastAPI — unchanged from Phase 5)
        │            /health · /pad/heartbeat · /turn · the action engine
        ▼
  Tailscale HTTPS   https://crooks-assistant.taildfb357.ts.net/
        ▼
  CROOKS PAD  (native Android shell)
        │            boot · kiosk · WebView hardening · heartbeat · mic permission
        ▼
  the existing CROOKS web UI   (web/ — unchanged from Phase 5)
```

Read it downwards and it is a chain of custody. Read it upwards and it is a chain of evidence:
every claim the Control app makes about the tablet has to have come from the tablet.

## The rule that shapes everything

**The business engine is not rewritten in Swift or Kotlin.** Not one line of Shopify logic,
Gmail logic, action-engine logic, proposal semantics or execution verification moves into a
native app. There are two reasons and they are both load-bearing:

1. **The V2 kernel replaces the engine.** Anything native that duplicated engine logic would
   have to be rewritten again, in two languages, by hand. The appliance layer is built to
   survive that replacement untouched, because it knows nothing about what the engine does.
2. **The web UI must stay deployable without rebuilding an APK.** A UI change that required
   pushing a new Android package to a tablet in a shop is a UI change that does not happen.
   The Pad is a hardened window onto a page; changing the page changes the product.

So the native apps are deliberately, almost insultingly thin. CROOKS Control knows the name of
one Python script. CROOKS Pad knows one origin and one heartbeat route. Everything either of
them can do is something the layer beneath already knew how to do.

## The three cross-workstream contracts

Four workstreams built the four halves of this layer in parallel, and all four had to agree on
three things without waiting for each other. They did not, entirely. These are the decisions
that settled it, and they are binding on all four.

### Contract 1 — the heartbeat has exactly one producer

The §26 trap that had to be avoided: **"tablet connected" must not mean "backend reachable"**.
A Tailscale route being served says a door is open. It says nothing about whether the Samsung
is switched on, in the shop or in a drawer, on the same network, or showing a crashed page.
Every one of those can be false with the route perfectly green.

So the only thing that counts as connected is the pad *itself* having checked in recently.

```
  CROOKS PAD  ──POST /pad/heartbeat──▶  PadRegistry
                {app_version, device_model,        │
                 os_version, at, boot_id,          │
                 events?}                          ▼
                                          GET /health → pad {…}
                                                     │
                                          scripts/control.py pad_status()
                                                     │
                                          CROOKS CONTROL → PadPresence
```

* The **cadence is not a Kotlin constant.** The pad reads `interval_s` off every heartbeat
  response, so the number lives in one place on the backend rather than being copied into
  Kotlin and going stale.
* **`/telemetry` is not the heartbeat.** `/telemetry` is the *web page's* account of itself and
  it is silent unless a test session is running — which is right for it, and exactly wrong for
  liveness, which has to be true at three in the morning with nothing recording.
* The **`pad` block on `/health` is the one authoritative wire shape.** `control.py` reads the
  key names the backend actually emits; the Swift app reads the key names `control.py` actually
  prints. No layer invents a field the layer beneath it has never written.
* `connected` is `now - last_seen < STALE_AFTER_S`, computed at answer time and never served
  from the health cache — a pad block frozen into a ninety-second cache would go on saying
  connected for longer than the staleness window it exists to enforce.

How far it can be trusted: exactly as far as the tailnet. Anyone the middleware admits could
post a heartbeat and be believed. That is the same trust model `/telemetry` has had since
Phase 5, and the honest claim it supports is *"something on the owner's private network,
speaking the appliance's protocol, is checking in"* — a great deal more than "a route
resolves", and rather less than a signed device identity. Nothing is authorised by it: it
moves no money, stages no action and unlocks no route.

### Contract 2 — the document version is a range, not a number

`scripts/control.py` stamps every document it prints with a `contract` integer and declares the
clients it is compatible with. The Swift app checks that version **before** decoding the rest,
out of a one-field probe — because the first version of the app decoded the whole document and
only then looked at the version, which turned "the script is one version ahead" into "answered
something I could not read", a dead end, when the true answer was "build the app again from
this checkout".

The app understands version **2** and reads the range **{1, 2}**. The script is at `CONTRACT = 2`
with `compatible_clients = [1, 2]`. An equality check on either side is a deadlock waiting for
the next additive field, so the parity test asserts both halves: that the app's understood
version is the script's current one, and that the script's compatible list covers everything
the app can read.

### Contract 3 — one event vocabulary

Sixteen `pad_*` kinds, spelled one way, admitted by the backend and emitted by the pad:

| kind | what it records |
|---|---|
| `pad_app_started` | the appliance came up (carries `boot_id`, `app_version`) |
| `pad_app_foreground` / `pad_app_background` | the shell's own lifecycle |
| `pad_webview_loaded` / `pad_webview_error` | whether CROOKS is actually on the screen |
| `pad_renderer_crash` | the WebView's render process died |
| `pad_network_changed` | the tablet moved network |
| `pad_backend_reachable` / `pad_backend_unreachable` | what the pad found at the other end |
| `pad_mic_permission` | the microphone grant state |
| `pad_admin_entered` / `pad_admin_exited` | the owner got behind the kiosk |
| `pad_version` | which build is on the tablet |
| `pad_battery` | percent and charging |
| `pad_kiosk_stage` | how far into kiosk the device actually is |
| `pad_navigation_blocked` | a top-level navigation off-origin was refused |

Anything else is rejected — and the rejection is **counted and visible** in
`events.rejected`, never silently dropped. A vocabulary that quietly swallows unknown names is
a vocabulary that will drift and never tell you.

## What this layer is NOT allowed to be

The Phase 5 non-regression boundary survives Phase 6 intact. The twelve invariants are
restated in `KNOWN_LIMITATIONS.md` with, for each, where in the appliance layer it is enforced.
Two of them constrain this layer directly:

* **Invariant 8 — no arbitrary model HTML/JS.** The Pad's JavaScript bridge is read-only and
  typed: `@JavascriptInterface` methods that answer questions. There is deliberately no
  `runNativeCommand(String)` and nothing shaped like one.
* **Invariant 12 — no fake control.** A control that the server cannot perform is not drawn as
  a working button anywhere, in the web UI or in CROOKS Control. Where the Control app cannot
  offer something, it says in words that it is absent and why.

And the security constraints of §28: no Shopify token, Gmail OAuth material, ElevenLabs key,
credential, environment content, admin PIN or arbitrary shell is reachable from either app.
CROOKS Control may say *"Shopify connected"*; it may never print what connected it.

## Where the seams are for V2

When the kernel is replaced, these are the only things the appliance layer touches and
therefore the only things that must keep their shape:

| seam | contract |
|---|---|
| `scripts/control.py` | the document versions and the `actions` list — the Control app draws the buttons the script names and hard-codes no command of its own |
| `GET /health` | `checks`, `observability`, `pad` |
| `POST /pad/heartbeat` | the body and the `interval_s` answer |
| the web origin | one HTTPS origin the Pad will load and no other |

Everything else — every route the engine serves, every tool it calls, every proposal it
stages — the appliance layer neither knows nor cares about.
