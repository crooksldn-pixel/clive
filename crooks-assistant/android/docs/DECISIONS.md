# CROOKS Pad — the decisions, and what has not been proved

Phase 6, workstream C. Every decision below was a real fork with a cost on both sides, and
this file exists so that the next person can disagree with the reasoning rather than guess at
it. The last section is the honest one: what this build machine could not check.

---

## minSdk 26, targetSdk 30, compileSdk 34

Three numbers, three different jobs, and only one of them is about the device.

**minSdk 26 (Android 8.0).** Not lower, because `WebViewClient.onRenderProcessGone` arrived in
API 26, and §11 requires a WebView renderer crash to be survivable. Without that callback,
Android terminates the process when the renderer dies — the owner finds the tablet on the
launcher, and the appliance promise is broken by an event that is entirely recoverable. Not
higher, because nothing in the shell needs a newer API and there is no reason to exclude an
older spare tablet from the fleet.

**targetSdk 30 (Android 11).** This is the one the brief asked to be justified either way.

The decisive fact is that **behaviour changes gated on targetSdk take effect only on devices
running that API level or above**. The fleet is one SM-T290 running Android 11. Declaring
targetSdk 34 on an API 30 tablet changes nothing at runtime on that tablet: the notification
runtime permission (33), foreground service types (34), exported-component enforcement (31),
PendingIntent mutability (31) and the rest simply never engage, because the platform code that
enforces them is not on the device. So targetSdk 34 would buy no behaviour the owner could
experience, while adding a behaviour contract that nobody here can test — there is no
emulator on the build machine and no second tablet.

Against that, the usual argument for a high targetSdk is Play's distribution floor, and it
does not apply: this app is sideloaded onto a tablet on a tailnet and is never published.

So targetSdk is 30, which is exactly the behaviour of the one device that exists.

**When that has to change, and what will break.** The day the fleet gains a tablet newer than
Android 11, or the day distribution goes through Play, targetSdk must rise, and these are the
things that will then need attention — written down now so the migration is a checklist rather
than an afternoon of surprises:

| API | What engages | Where it bites this shell |
|---|---|---|
| 31 | Every exported component must declare `android:exported` | already declared on all three |
| 31 | `PendingIntent` must state mutability | the shell creates none today |
| 33 | `POST_NOTIFICATIONS` becomes a runtime permission | the shell posts none today |
| 34 | Dynamically registered receivers must pass an export flag | `DeviceFacts.start` already uses `ContextCompat.registerReceiver(..., RECEIVER_NOT_EXPORTED)` for exactly this reason |
| 34 | Foreground services must declare a type | the shell runs none; see "no foreground service" below |

**compileSdk 34.** Compiling against 34 while targeting 30 is deliberate: it lets the shell
*call* newer APIs behind `Build.VERSION.SDK_INT` guards — `WindowInsetsController` for
immersive mode on API 30, for instance — without declaring that it wants API 34's behaviour.

**AGP 8.6.1.** Pinned rather than latest because AGP 8.7 and above default to build-tools
35.0.0, and the build machine has 34.0.0. A version that resolves with what is on disk beats a
version that needs a download that may not be available.

---

## Fixed portrait

`android:screenOrientation="portrait"`, and the orientation is not offered as a setting.

The web layer is designed for 601×889 at DPR 1.33125. The dock, the orb, the branch rail and
the card density in `web/style.css` are all measured against that viewport, and Phase 3 spent
real effort on it. Rotating the pad would not produce a landscape design; it would produce the
portrait design stretched, with the dock in the wrong place and half the fixtures below the
fold.

More to the point: on an appliance, a rotation is almost always an *accident* — someone picks
the tablet up to read it and the screen flips. A fixture that changes shape when it is handled
is a fixture the owner stops trusting. The second viewport the product supports, 800×1280, is
also portrait.

`configChanges` includes `orientation` and `screenSize` anyway, so that a forced rotation from
some system path cannot recreate the activity and throw away a loaded workspace mid-turn.

---

## Voice: who owns it now, and what the native path would be

**CURRENT OWNERSHIP — THE WEB LAYER, ENTIRELY.** Capture, VAD, the hold gesture, arbitration,
transcription, playback and every piece of state around them live in `web/` and talk to the
Mac's `/turn` and `/speak`. The shell contributes exactly two things: it grants the microphone
permission to the trusted origin and nothing else (`MicPermissionPolicy`), and it explains a
refusal that the page cannot explain (§8). It has no audio code, no recorder, no wake word, no
`AudioRecord`, no `MediaRecorder`.

**AND IT DELIBERATELY HAS NO TOUCH SURFACE OF ITS OWN.** This is §7, and it is the single most
important constraint on this workstream.

In Phase 4, on 11 September, 63 ordinary control taps became voice recordings in one evening.
The cause is written up in `web/touch.js`: a transparent voice target the size of the viewport
(`body[data-mode="orb"] .talk{inset:0}`) sat over branch chips trapped in a lower stacking
context, so every tap on Split, Merge or Close became a recording. The speech pipeline reported
them as "too short"; the analyser then named speech as the product's top improvement candidate
during a session in which speech was the one thing working. One layering defect produced a
false engineering priority.

In the native shell the same shape would be worse, because a view here sits above the WebView
and would swallow every control in the entire product at once, with nothing in any log to say
why. So the shell is built so that the defect is **unrepresentable**, not merely avoided:

- `ShellVisibility.layerFor` returns ONE `ShellLayer`. There is no set of booleans, no z-order,
  no "show this over that". Two layers at once cannot be expressed.
- Every overlay is `View.GONE` when it is not the named layer — never `INVISIBLE`, never alpha
  0. `PadLayoutTest` parses `activity_pad.xml` on every build and fails if any sibling above
  `web_host` ships without `android:visibility="gone"`, or without an opaque background.
- The admin gesture uses **hardware volume keys**, not touch. Six alternating presses. It
  consumes no pointer events at all, at any density, under any layout, so it cannot steal a
  CROOKS control in principle rather than by good arrangement. See below.
- The only thing the shell puts over a *working* workspace uninvited is the microphone card,
  and it is opaque, deliberate and dismissible in one tap.

**THE FUTURE NATIVE VOICE PATH, if it is ever taken.** `PLAN-TABLET-APP.md` sizes it: a
foreground service keeping the microphone alive with the screen off, and an on-device wake word
("Crooks…") that hands the page a "start listening" event. If that is built, three rules
follow from the above and should be treated as binding:

1. **The wake word hands the page an EVENT. It does not open a stream the page cannot see.**
   The web layer stays the owner of what a recording means; the native side says only "someone
   said the word".
2. **That event crosses in the direction the bridge does not currently allow** — native to
   page, not page to native — so it must be a `WebView.evaluateJavascript` call dispatching a
   `CustomEvent`, never a new `@JavascriptInterface` method. The bridge stays one read-only
   method wide.
3. **No new touch surface, ever.** If a native voice affordance is wanted on screen, it is a
   bounded, opaque, visible control with a real size, and `web/touch.js`'s `covering()`
   arithmetic is the rule it has to satisfy.

A foreground service is not shipped in Phase 6. On targetSdk 34 it would need a declared
service type (`microphone`), which is part of the migration table above.

---

## The admin escape is a pair of volume keys

Six presses, alternating, starting with volume down, each within 1.2 seconds of the last:
**DOWN, UP, DOWN, UP, DOWN, UP**.

The obvious design — five taps in a corner, a long press on the wordmark, a two-finger hold —
is the Phase 4 defect with a smaller rectangle, and §7 says explicitly that the fix "is not a
bigger hit region with more exceptions". Volume keys give three properties that a touch gesture
cannot:

- The WebView never sees a volume key, so no CROOKS control can be stolen by the gesture.
- The presses are **observed and not consumed** (`super.onKeyDown` is still called and its
  answer returned), so the volume genuinely changes and an owner adjusting it is not fighting
  the shell. Six alternating presses are volume-neutral: the sequence ends where it began.
- It works from any screen — the workspace, a recovery card, a modal inside the page.

An accidental trigger costs nothing: a PIN sheet with a Close button and no information on it.

**The PIN is not in the source and has no default.** A tablet that has not been provisioned has
*no* admin, not a known one; the first performance of the gesture offers to set a PIN instead of
asking for one. Storage is PBKDF2-HMAC-SHA256, 120,000 iterations, a random 16-byte salt, the
iteration count carried inside the encoded value so the cost can be raised later without
stranding an existing tablet. Verification is constant-time. Backup and device transfer are off
in the manifest.

**What that does not defend against, stated plainly.** It is not hardware-backed. A six-digit
PIN is a hundred thousand possibilities, and anyone who has extracted the preferences file —
which needs root, an unlocked bootloader, or ADB on an already-trusted device — can grind it
offline whatever the iteration count. The iteration count buys minutes, not safety. What this
honestly defends is: a customer, a member of staff or a child getting into the admin screen on
a tablet sitting on a counter. The upgrade, if it ever matters, is an Android Keystore-backed
key. The 120,000 figure is **reasoned from the Exynos 7904, not timed on it** — there is no
tablet attached to this build machine. Whoever first runs this on the real device should time a
verification and correct the number here.

---

## Kiosk: stage 1 only, and why the others are doors that do not open twice

| Stage | What it is | Status |
|---|---|---|
| 1 — immersive | Sticky immersive fullscreen, screen kept on, Back inert, recoverable by anybody | **shipped** |
| 2 — lock task | `startLockTask()`; on an unmanaged device this is Android screen pinning | detected, **off** |
| 3 — device owner | Android Enterprise dedicated device; boots into the app, no way out but a factory reset | detected, **off** |

`KioskCapability.assess` reports what the tablet could support and `KioskCapability.ENABLED_STAGE`
is `STAGE_1_IMMERSIVE`, hard-coded in one greppable place. `KioskCapabilityTest` asserts that a
*fully capable* tablet still comes back as stage 1 — that test is the point, because a detection
routine which promotes itself the moment it meets a capable device is how a one-way door gets
opened by accident, on a £130 tablet nobody in the building can reflash, and noticed a week
later.

**Knox is detected, never assumed.** The SM-T290 is a consumer Galaxy Tab A. Samsung's Knox SDK
is present on enterprise devices and only partially and inconsistently on consumer ones by
firmware, so `if (isSamsung) useKnox()` would produce an app that crashes on exactly the device
it was written for. `DeviceFacts.kioskFacts()` does a class lookup for
`com.samsung.android.knox.EnterpriseDeviceManager` and reports the answer honestly, including
when it is false. Nothing in the shell uses Knox.

---

## Boot: what it can and cannot promise on an unmanaged tablet

`BOOT_COMPLETED`, `LOCKED_BOOT_COMPLETED` and `MY_PACKAGE_REPLACED` are received; the decision
is `BootPolicy` in `:core`, which is tested. Three honest limits:

1. **`BOOT_COMPLETED` is delivered only after the user has unlocked the device at least once**,
   if a secure lock screen is set. A tablet with a PIN on its lock screen does NOT start CROOKS
   by itself after a power cut; it starts CROOKS the moment somebody unlocks it. The fix is a
   *device* setting — no secure lock screen on a fixture — not something an app can do.
2. **Samsung's One UI is aggressive about background start-ups.** An activity started from a
   receiver at boot is not guaranteed to come to the front on every firmware. This is
   best-effort and the diagnostics screen says so rather than promising it.
3. **The reliable mechanism is the HOME role**, because the system starts the home activity
   itself rather than being asked to. `PadHomeAlias` carries `CATEGORY_HOME` and **ships
   disabled**; it is enabled from the admin screen by someone who has typed the PIN, and
   disabled again from the same button. Android will not silently make an app the launcher, so
   enabling the alias only makes it eligible and the shell sends the owner to Android's home
   settings to choose — which is the honest thing to do rather than leaving them wondering why
   nothing happened.

---

## UPDATE REQUIRED is implemented and currently unreachable

`UpdatePolicy` and the `UPDATE_REQUIRED` state are built and tested. **No endpoint in the
current backend carries a minimum pad version**, and `app/routes/**` is inside Phase 6's
non-regression boundary, so this workstream could not add one. `UpdatePolicy.verdict(current,
null)` returns `UP_TO_DATE`, which is what happens in production today.

**Handoff:** whoever owns the backend should add a `pad` object to `/health` carrying
`min_app_version`. The pad already reads `/health` every three minutes while ONLINE (for the
test-session id) and the parsing is one line.

**And one deliberate inversion of the house rule.** This gate **fails OPEN**: an unparseable
minimum returns `UNKNOWN` and the pad carries on. Everywhere else in CROOKS an unknown answer
fails closed — invariant 7 — but invariant 7 is about *mutations*, and nothing is being mutated
here. What is being decided is whether the pad **refuses to work**, and the harms are not
symmetrical: one typo in a field nobody looks at would otherwise stop every tablet in the
building with nothing the owner could do from the tablet, whereas failing open leaves a pad
running a slightly old shell around the Mac's own current page. `PadVersionTest` says so where
somebody would find it.

---

## Two things the shell deliberately does not do

**It does not police sub-resources.** The origin allow-list governs *navigation*: the address
the top-level document is being asked to become. Images, fonts and XHR are the page's
Content-Security-Policy's business on the Mac, where the rule can be tested against the real
page. A second, blunter copy of that rule inside the shell would be untestable here and would
eventually break rendering in a way nobody could reproduce. The shell owns the door; the
backend owns the furniture.

**It does not second-guess the page's connection.** A failed `/ping` while the workspace is up
changes nothing: the page has its own connection, its own poll and its own SYSTEM OFFLINE
state, and one missed poll while the owner is mid-sentence is not an outage. The shell takes
the workspace away only when the *page* fails — a renderer crash, an HTTP error, a transport
failure, a certificate problem.

**It does not pin certificates.** `tailscale serve` issues and rotates the certificate; a pin
would turn a routine rotation into a dead tablet in a workroom with no laptop. The tailnet is
the trust boundary. Cleartext is refused by the network security config, and
`onReceivedSslError` calls `handler.cancel()` with no branch and no setting — `handler.proceed()`
appears nowhere in the source and `PadHardeningTest` checks that it stays that way.

---

## A failed load poisons the load, not the WebView

Chromium does not stop at the error callback. For a main-frame 502 it fires `onPageStarted`,
then `onReceivedHttpError(502)`, **then `onPageFinished`** — the same `onPageFinished` it fires
for a real page, because from the WebView's point of view a 502 is a document that arrived and
parsed. The shell recorded the error, settled the connection at CROOKS OS UNHEALTHY, and then
one callback later treated the page as a fresh successful load: it armed the readiness probe,
asked the 502's error body whether the CROOKS workspace was in it, got no for six seconds, and
took READY_ASSUMED — which reaches ONLINE. The owner's tablet showed a reverse-proxy error page
while the Mac said the pad was fine. That is §26's lie in its purest form.

**The fork.** The obvious fix is a boolean on the WebView: "this WebView has failed, stop
believing it". That is worse than the bug. One bad gateway during a Mac restart would leave a
pad that never comes back until somebody power-cycles it, and an appliance that needs a manual
recovery from a transient error is not an appliance.

**What was done instead.** `PageLoadGuard` in `:core` numbers each load the shell starts and
poisons *that number*. `onPageFinished` for a poisoned load is ignored; so is a readiness answer
that arrives for one, which also covers the reverse ordering, where the error lands while the
poll is already running. `shellStartedLoad()` — and nothing else — lifts the poison, so the
ordinary recovery path (probe succeeds, `loadWorkspace()`, page loads cleanly) reaches ONLINE
exactly as before. `onPageStarted` deliberately does **not** lift it: Chromium fires that for
the error page it substitutes after a failed navigation, so treating it as "a fresh load has
begun" would hand the poison straight back to the sequence that created it.

The rule lives in `:core` because a rule about a WebView callback that lives in an Activity is a
rule this build machine cannot run — which is exactly how the defect survived review the first
time. `ConnectionMachineTest` now replays all three callbacks in Chromium's order, and
`PadHardeningTest` reads `PadActivity.kt` to check that the Activity still asks rather than
deciding for itself.

---

## The heartbeat's cadence belongs to the Mac, not to the APK

§16 asks the pad to say "I am here". The question was where, and how often.

**Where.** Not `POST /telemetry`. That endpoint is the **web page's** account of itself and
drops everything unless a test session is running on the Mac — by design, in
`app/routes/observe.py`, which is inside Phase 6's non-regression boundary and cannot be bent to
suit the pad. A pad whose liveness travelled on it would be invisible for the ninety-nine
percent of its life when no session is running. So the pad posts `POST /pad/heartbeat`, and its
pad_* events ride along with it.

**How often.** The tempting answer is a constant: `const val BEAT_MS = 20_000`. On this product
that constant is unreachable. The pad is sideloaded onto one tablet in a shop; changing the
number means a build, a cable and somebody's afternoon. So the cadence is read from the
response's `interval_s` on **every** beat, and the built-in default is used for the first beat
and for nothing else. The Mac can quieten a pad or speed it up while somebody is watching the
Control app, and the tablet needs no attention at all.

The only judgement the shell keeps is a pair of rails — five seconds to an hour — because a
backend bug that answered `interval_s: 0` should not turn an appliance into a packet storm, and
one that answered `interval_s: 86400` should not turn it into a tablet nobody hears from. Both
bounds are far outside any cadence anybody would choose on purpose, and
`PadHardeningTest` fails the build if a constant with `BEAT` or `HEARTBEAT` in its name
reappears in the Android module.

The answer also carries `test_session`, which the pad puts on the device-bridge snapshot. That
is how the page's own telemetry is turned on and off within one beat, instead of every pad
running a second clock that polls `/health` for a field the beat had already fetched.

---

## What this build machine could NOT verify

There is no `/dev/kvm` on the build machine, so there is **no emulator**, and no SM-T290 is
attached, so there is **no device**. That means:

- **No screenshot of any native screen exists.** The launch path, the recovery cards, the admin
  sheet and the diagnostics screen have been written and reviewed from their layout source and
  have never been rendered. Nothing in this workstream claims to "look right".
- **No touch has been tested.** `PadLayoutTest` proves that no overlay ships above the WebView
  without being GONE, and that declared control heights are at least 48dp. It does **not** prove
  that a button is tappable, that the WebView receives a pointer, or that §7's defect is
  actually absent on glass. That needs a finger.
- **No microphone has been tested.** `MicPermissionPolicy` is unit-tested on every input
  combination. Whether Android's prompt appears, whether `getUserMedia` then succeeds inside the
  WebView, and whether the SM-T290's microphone works are all unverified.
- **No sleep, wake, charger, Wi-Fi loss or Tailscale reconnect has been exercised.** The state
  machine's responses to all of them are unit-tested as *logic*; the events that would drive it
  have never been produced by real hardware.
- **No renderer crash has been observed.** `onRenderProcessGone` is implemented and returns
  true, and the circuit breaker is tested; a real renderer death has not happened here.
- **No boot has happened.** `BootPolicy` is tested; whether Samsung's firmware actually
  delivers the broadcast and lets the activity come to the front is unknown.
- **No APK has been installed.** `assembleDebug` and `assembleRelease` both produce real APKs
  for API 30 on this machine. Neither has been installed, launched, or run for one second.
- **The release APK is unsigned.** There is no signing key in this repository and there should
  not be one.
- **No heartbeat has ever reached a Mac.** `POST /pad/heartbeat` is implemented, its body and
  its cadence rule are unit-tested in `:core`, and the Android side is a single `probe.post`
  call. No beat has been sent over a network, no `interval_s` has been received from a running
  backend, and the endpoint itself belongs to another workstream. The seam — that `at` is epoch
  **milliseconds** and the Mac's `clock_skew_s` is in seconds, and that `test_session` is read
  at the TOP LEVEL of the response rather than nested under `observability` — is asserted on
  this side and has not been shaken hands on with the other.

The APK building is a real result and is reported as one. Everything in the list above is not,
and the physical checks belong in whoever owns the on-device scripts for this phase.
