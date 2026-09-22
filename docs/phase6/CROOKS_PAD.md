# CROOKS PAD — the Samsung's native shell

## What it is

A hardened window onto one page, and nothing else.

CROOKS Pad is an Android application that shows the existing CROOKS web UI full-screen with no
browser chrome, no URL bar, no tabs, and no way to navigate anywhere else. It contains **no
business logic**: no Shopify, no Gmail, no action engine, no proposal semantics. Everything it
knows how to do is about the *device* — boot, kiosk, network, microphone, crash recovery, and
saying whether it is alive.

That is not modesty, it is the requirement. A UI change that meant pushing a new APK to a
tablet in a shop is a UI change that does not happen. The web layer stays deployable; the
shell stays still.

Target: **Samsung Galaxy Tab A 8.0 (2019), SM-T290, Android 11, API 30**, portrait 601×889 CSS
at DPR ≈ 1.33.

## The shape of it

```
  :core   pure Kotlin, no Android imports.  Every decision.       ← unit-tested on the JVM
  :app    Activity, WebView, receivers, res. Draws the core.      ← needs a device
```

The split is the same one CROOKS Control uses and for the same reason: the judgements are the
part that can be wrong in ways nobody notices — is a load that failed a load that succeeded, is
a route a connection, is an origin trusted — and they belong where a test can drive them. What
is left in `:app` is plumbing.

This matters more here than anywhere else in the phase, because **there is no emulator on the
build machine and no attached tablet**, so `:core` is the only part of CROOKS Pad that has ever
been executed. `:app` has been compiled into a real APK and never run.

## The eight states

Each state exists because it asks something **different** of the person holding the tablet.
That is the test for whether a state deserves to exist: if two situations ask the same thing,
they are one state with two causes, and splitting them only makes the pad harder to read across
a workroom.

| state | what happened | what the owner does |
|---|---|---|
| `CONNECTING` | trying; the Mac has not said no | wait — and the card says when the next try is |
| `ONLINE` | CROOKS is up and in use | **nothing native is drawn at all** |
| `MAC_OFFLINE` | tablet has a network, Mac is not answering | turn the Mac on |
| `NETWORK_OFFLINE` | the tablet has no network | fix the Wi-Fi. **Beats `MAC_OFFLINE` always** |
| `CROOKS_OS_STARTING` | the Mac says it has only just come up | wait |
| `CROOKS_OS_UNHEALTHY` | process alive, application not serving | the §26 state, by name |
| `MIC_*` | the microphone is refused | one button |
| renderer gone | the WebView's render process died | automatic recovery |

Two of these are worth dwelling on.

**`NETWORK_OFFLINE` beats `MAC_OFFLINE` always.** A pad that accuses the Mac of being off when
it cannot see anything at all is a pad that sends the owner upstairs for nothing.

**`CROOKS_OS_UNHEALTHY` exists because the pad is the only thing positioned to notice it.** The
Mac answers `/ping` — the process is alive — and the workspace will not load. §26 names that
trap in its own vocabulary ("process reported started vs genuinely healthy"); this is the state
that has a name for it.

And §17's rule holds over every one of them: **either it retries by itself and shows when the
next attempt is, or it offers exactly one thing to press.** A spinner with no countdown is
indistinguishable from a hang, and after about fifteen seconds a reasonable person concludes
the thing is broken. A state that does neither is a bug.

`RecoveryCards.forState()` is total — it answers for `ONLINE` too, which is never drawn — so a
new state cannot be added without deciding what its card is.

## The invisible shell

§19: when the pad is ONLINE, **the WebView is the whole screen.** No banner, no badge, no
toast, no title bar, no version string in a corner. If you can see the shell, something is
wrong.

## A failed load must not become a good one

This is the defect this phase found in CROOKS Pad, and it is worth recording in full because
the shape of it recurs.

Chromium delivers `onReceivedHttpError`, `onReceivedError` and `onReceivedSslError` **before**
`onPageFinished`. A naive shell records the error, and then the page-finished callback arrives
and re-arms the readiness probe, and the state machine promotes the load to **ONLINE**. The
owner is looking at a 502 — or a blank rectangle — and the Mac's control panel says the tablet
is fine.

So a main-frame failure **poisons that load**: `onPageFinished` cannot promote a poisoned load.
The poison is scoped to the load and not to the WebView, so a subsequent successful load
recovers normally.

The test that was supposed to catch this stopped exactly one callback too early — it fired the
error and asserted the state, and never fired the `onPageFinished` that undid it. **A test that
replays a callback sequence must replay the whole sequence, in the order the platform actually
delivers it**, or it is testing a program that does not exist.

## The heartbeat

The pad POSTs `/pad/heartbeat` on a timer:

```
  {app_version, device_model, os_version, at, boot_id, events?}
```

The **cadence comes from the answer**, not from a Kotlin constant: every response carries
`interval_s`, so the number lives in one place on the backend. The answer also says whether a
test session is running, so the pad turns its own page telemetry on and off within one beat
without a second request.

This is what "CROOKS PAD: CONNECTED" on the Mac means — and the only thing it means. See
`ARCHITECTURE.md`, Contract 1, for why a Tailscale route is not allowed to mean it.

Sixteen event kinds ride along with the heartbeat, spelled one way (Contract 3). Anything else
is **rejected and counted** in `events.rejected` — never silently dropped, because a vocabulary
that quietly swallows unknown names will drift and never tell you.

## Security — §28, item by item

| requirement | how |
|---|---|
| narrow, typed WebView bridge | **one** `@JavascriptInterface` method: `String snapshot()`. That is the entire surface. |
| no arbitrary command execution | no `runNativeCommand(String)`, no `invoke(name, args)`, no dispatcher of any kind. **Nothing that mutates**: no reload, no navigate, no exit, no grant, no setting. The shell watches the page; the page does not drive the shell. |
| no credentials exposed | no token, cookie, credential, serial, IMEI, Android ID, advertising ID, account, SSID, BSSID, IP, MAC or location crosses the bridge. `DeviceSnapshot` is the exhaustive list of what does, and a test asserts none of those words appears in the encoded form. |
| production WebView debugging off | `WebView.setWebContentsDebuggingEnabled(BuildConfig.WEBVIEW_DEBUG)`; `false` in the release build type, `true` only in debug. A build-config difference, so a debug build **cannot** be made safe by changing a setting on the tablet. |
| admin PIN not hardcoded | no default, no fallback, no engineering code. PBKDF2-HMAC-SHA256, random salt, 120,000 iterations, iteration count carried inside the encoded value, constant-time verify, backup and device-transfer off. See `KIOSK_PATH.md` for the boundary it does and does not defend. |
| origin control | `allowFileAccess`, `allowFileAccessFromFileURLs`, `allowUniversalAccessFromFileURLs` all false; geolocation off; top-level navigation off-origin refused and recorded as `pad_navigation_blocked`. |
| transport | `usesCleartextTraffic="false"` plus a network security config with `cleartextTrafficPermitted="false"`, so an `http://` address that somehow got past the allow-list still could not leave the device in clear. |

**No certificate pinning — a decision, not an omission.** The CROOKS origin is served by
`tailscale serve`, whose certificate Tailscale issues and rotates. A pin would turn a routine
rotation into a dead tablet in a workroom with no laptop. The tailnet is the trust boundary; a
pin buys nothing against an attacker already inside it and costs an outage against nobody.

**Permissions requested, and one deliberately not.** `RECORD_AUDIO`, `INTERNET`,
`ACCESS_NETWORK_STATE`, `ACCESS_WIFI_STATE`, `RECEIVE_BOOT_COMPLETED`, `WAKE_LOCK`. **Not**
`ACCESS_FINE_LOCATION`: reading the Wi-Fi SSID would require it and would put a
place-identifying string into telemetry. Signal strength and transport type answer every
question the pad actually has.

## Who may switch the microphone on

The default implementation of `onPermissionRequest` in a naive shell is `request.grant(request
.resources)` — grant whatever was asked, to whoever asked. In a shell that only ever shows one
origin that looks harmless, right up to the moment a navigation guard is loosened, a redirect
is followed, or an iframe is added: at that point some other origin holds a live microphone in
a room where the business is discussed all day, and nothing on screen says so.

So the decision is made in `:core`, from four facts, and grants **exactly one resource to
exactly one origin**. It has three outcomes, and the third is the interesting one:

* `GRANT` — audio capture, to the trusted origin.
* `DENY_EXPLAIN` — Android has not given the app the microphone. **The owner's problem**: a
  CROOKS card with one button.
* `DENY_SILENT` — an untrusted origin asked, or something other than the microphone was asked
  for. **Not the owner's problem** — it is a security event. Silent to the owner, loud in
  telemetry. Showing him a microphone explanation for it would train him to grant it.

## What has never been run

Everything in `:app`. The APK builds; nothing has executed it. There is no `/dev/kvm` on the
build machine, so no emulator, and no SM-T290 is attached.

Concretely, **none of these has been observed even once**: the app opening, the immersive
fullscreen, any recovery card, the diagnostics screen, the PIN sheet, the admin gesture, a
real heartbeat leaving a real device, boot behaviour on One UI, or a single pixel of CROOKS
rendered on the tablet.

`CROOKS_PAD_ACCEPTANCE.md` is the procedure that closes this, and it needs a person.
