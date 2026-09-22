# CROOKS Pad

The native Android shell for the Samsung Galaxy Tab A 8.0 (SM-T290, Android 11). It is not a
rewrite of CROOKS OS — it is the frame between Android's hardware and the CROOKS OS web UI the
Mac already serves. It owns launch, fullscreen, the WebView's lifecycle and hardening, trusted
navigation, the microphone permission, device and connectivity state, wake behaviour, crash
recovery, the native recovery screens, kiosk readiness, the admin escape and appliance
telemetry. It owns no business logic whatsoever: no Shopify, no Gmail, no proposals, no
actions, no voice pipeline.

When CROOKS is healthy, **this application draws nothing at all**. That is the point of it.

## Build

```
export ANDROID_HOME=/opt/android-sdk        # or wherever the SDK is
./gradlew assembleDebug                     # app/build/outputs/apk/debug/app-debug.apk
./gradlew test                              # every JVM unit test in both modules
./gradlew assembleRelease                   # unsigned; there is no signing key in this repo
```

Requires JDK 17 or later and Android platform 30 plus 34, build-tools 34.0.0.

## The shape of it

```
android/
  core/     a plain JVM Kotlin library — NO Android dependency, by construction
  app/      the Android application
  docs/     DECISIONS.md: every decision, and what has not been proved
```

The split is the most important thing about this module and it is not tidy-mindedness.

`:core` holds **every decision the shell makes**: which origins are trusted, what state the
connection is in, when to retry, whether a microphone request may be granted, which single
layer is on screen, what a telemetry event is allowed to say, whether a PIN was right, which
kiosk stage is in force. It is a plain JVM library, so all of that **runs and is tested on the
build machine** — which matters enormously here, because the build machine has no emulator and
no tablet, and anything that needs a device cannot be checked at all. The Gradle plugin
enforces the boundary: reach for `android.*` inside `:core` and it does not compile.

`:app` is lifecycle, views and hardware. It decides nothing, and it is deliberately boring.

## What is actually verified here, and what is not

`android/docs/DECISIONS.md` has the full list; the summary is that **the APK is real and the
decisions are tested, and nothing has ever been rendered or touched**. There is no `/dev/kvm`
on the build machine, so there is no emulator; there is no SM-T290 attached, so there is no
device. No screenshot of any native screen in this module exists. No button has been pressed,
no microphone opened, no boot observed, no renderer crash seen, and the APK has never been
installed.

Four tests are worth knowing about because they check things people usually only assert:

- **`ConnectionMachineTest`, "a 502 is not a successful load, through the whole Chromium
  callback sequence"** — replays the real order Chromium delivers for a main-frame 502:
  `onPageStarted`, then `onReceivedHttpError`, **then `onPageFinished`**. That third callback is
  the one an earlier version of this test never delivered, and it was the one through which a
  reverse-proxy error page reached ONLINE while the owner's tablet showed a broken page. The
  rule that a failed load is poisoned lives in `PageLoadGuard` in `:core`, where it can be run.
- **`HeartbeatTest`, "the backend's interval_s becomes the cadence"** — the §16 heartbeat's
  cadence is not a constant in this APK. The built-in number is used for the first beat and is
  then replaced by whatever the Mac put on the answer, so a fleet's cadence can be changed
  without a cable and a tablet in somebody's hand.
- **`PadTelemetryTest`** — the Mac admits a fixed vocabulary of pad_* names and keeps only the
  fields its table names, dropping the rest silently, so a pad can emit a perfectly good event
  and have the one field that explained an outage thrown away at the door. The test holds the
  set of kinds this shell can emit against a hand-written copy of that table, **for equality in
  both directions**, and every field of every kind against the fields it keeps.
- **`PadLayoutTest`** — parses `activity_pad.xml` and fails if any view above the WebView ships
  without `android:visibility="gone"`, or without an opaque background. That is Phase 4's
  63-taps-became-recordings defect, made unshippable in the one layer where JavaScript could
  not argue with it. It does **not** prove a button is tappable; only a finger can do that.

## Where a pad_* event goes

Not to `POST /telemetry`. That endpoint is the **web page's** account of itself and is silent
unless a test session is running on the Mac, so an appliance whose liveness travelled on it
would be invisible for almost all of its life. The pad posts `POST /pad/heartbeat` instead —
`{app_version, device_model, os_version, at, boot_id, events?}` — and its queued events ride
along. The answer carries `interval_s`, which is the cadence for the next beat, and
`test_session`, which the pad hands to the page through the device bridge so that the page's own
telemetry can be turned on and off within one beat instead of by a second clock polling
`/health`. Everything else stays in a 200-event ring buffer on the tablet, which is the copy
that still works when the Mac is the thing that is broken.

## Admin

Six alternating volume presses — **down, up, down, up, down, up**, each within 1.2 seconds of
the last — then a PIN. The gesture uses hardware keys and no touch at all, which is why it
cannot steal a CROOKS control under any layout. The presses are not consumed, so the volume
genuinely moves and the sequence is volume-neutral.

There is **no PIN in the source and no default**. The first time the gesture is performed on an
unprovisioned tablet, it offers to set one. Once set, the only reset is clearing the app's data
from Android Settings.

Admin offers: reconnect, reload CROOKS, clear cache, take or give up the home-screen role,
leave CROOKS, and the diagnostics screen. Diagnostics is **also reachable from every recovery
card without a PIN** — the one screen that explains why nothing is working must not be behind
the thing that is not working.

## The eight states (§17)

| State | Means | Owner does |
|---|---|---|
| CONNECTING | trying; the Mac has not said no | nothing; it counts down |
| ONLINE | working — **the shell is invisible** | uses CROOKS |
| MAC OFFLINE | the tablet has a network, the Mac does not answer | turns the Mac on |
| NETWORK OFFLINE | the tablet has no network at all | fixes the Wi-Fi |
| CROOKS OS STARTING | the Mac answered and has just come up | waits a few seconds |
| CROOKS OS UNHEALTHY | the Mac answers `/ping` but will not serve | Retry, or Diagnostics |
| UPDATE REQUIRED | this shell is older than the Mac supports | installs a new one |
| APP ERROR | this tablet's own installation is wrong | Diagnostics |

Every one of them either counts down to its own next attempt, in seconds, on screen, or offers
something to press. A state that did neither would be the infinite spinner §17 forbids, and
`ConnectionMachineTest` drives the machine into all eight and checks it.
