# CROOKS PAD — the kiosk path

## The shape of the problem

A kiosk lock on a managed fleet is a setting. A kiosk lock on one unmanaged £130 consumer
tablet is a **one-way door**, and the thing on the other side of it is a brick — on a device
nobody in the building can reflash, discovered a week after the fact.

So this phase implements the stage that is always reversible, and *writes down the pathway* to
the two that are not, without walking through either. Every higher stage is detected, described
in the diagnostics screen, and deliberately switched off.

`§34` forbids, without the owner's explicit approval: factory reset, irreversible Device Owner
state, external MDM enrolment, permanently suppressing recovery access, wiping user data, or
anything touching the bootloader. **None of those has been done, and none of them can be
triggered by the shipped build.** Stage 3 below is the boundary; the work stops at it.

## The three stages

| | mechanism | what it costs to get out | shipped |
|---|---|---|---|
| **Stage 1** | sticky immersive fullscreen | nothing — recents key, ADB, everything still works | **yes** |
| **Stage 2** | `startLockTask()` (screen pinning) | the pinning gesture, plus the device lock if one is set | pathway only |
| **Stage 3** | Device Owner ("dedicated device") | a factory reset | pathway only |

### Stage 1 — immersive. This is what ships.

Fullscreen, sticky immersive, no status bar, no navigation bar, screen kept on while CROOKS is
showing, back handled by the shell. Ordinary Android is still underneath it: the recents key
exists, the app can be left, ADB works, and **anybody can recover the tablet at any time**.

It gets the product 90% of the way to "feels like an appliance" for 0% of the risk.

### Stage 2 — lock task. Detected, off.

`startLockTask()` on an unmanaged device is Android's ordinary screen pinning. It does not need
Device Owner and it is genuinely reversible. It is off for one specific reason, and it is worth
stating precisely because it is not obvious:

> Combined with the HOME alias, it produces a tablet whose only route back to Settings is
> through an admin PIN that this shell stores as a hash it cannot recover — and **that
> combination has never been rehearsed on the real device.**

Either one alone is fine. Together, on hardware nobody has tested them on, they are how you
lose the tablet. `KioskCapability.ENABLED_STAGE` is a single constant so that turning this on
is a deliberate, greppable, reviewable edit in one place.

### Stage 3 — Device Owner. Detected, off, and at the §34 boundary.

Android Enterprise "dedicated device": boots straight into the app, no way out without a factory
reset. It requires provisioning the app as device owner on a **freshly reset tablet with no
Google account**, over ADB or NFC.

That first clause is the whole issue. Reaching stage 3 *begins* with a factory reset, which §34
forbids without the owner's explicit approval. It is therefore not a thing this phase could
have done even if it were desirable. The pathway is written down; the door is not opened.

### Knox is detected, never assumed

The SM-T290 is a consumer Galaxy Tab A. Samsung's Knox SDK is present on Samsung **enterprise**
devices, and on consumer devices only partially and inconsistently by firmware. `if (isSamsung)
useKnox()` produces an app that crashes on exactly the device it was written for.

`KioskFacts.knoxPresent` is filled in by a class lookup on
`com.samsung.android.knox.EnterpriseDeviceManager` and is **reported honestly in diagnostics
including when it is false**. Nothing in the shell depends on it.

## The way out — and why it is a pair of volume keys

The obvious admin gesture is a hidden hit region: five taps in a corner, a long press on the
wordmark, a two-finger hold. **Every one of those is the Phase 4 defect with a smaller
rectangle.**

In Phase 4, sixty-three ordinary control taps became voice recordings because an invisible
surface sat where the controls were. The lesson recorded in `web/touch.js` is explicit that the
fix "is not a bigger hit region with more exceptions". Putting a new invisible rectangle into
the *native shell* — where it sits **above the WebView, and therefore above every control in
the product** — would be committing that same error in the one layer JavaScript cannot argue
with.

So the gesture consumes no touch events at all:

```
  VOLUME_DOWN · VOLUME_UP · VOLUME_DOWN · VOLUME_UP · VOLUME_DOWN · VOLUME_UP
  six presses, alternating, each within 1,200 ms of the one before
```

Three properties fall out of that, and each is worth having:

* **The WebView never sees a volume key.** No CROOKS control can be stolen by the gesture, ever,
  under any layout, at any density. The class of defect is *unreachable* rather than avoided.
* **The presses are not consumed.** The volume genuinely goes down and up, so an owner adjusting
  the volume is not fighting the shell — and the sequence is volume-neutral: six alternating
  presses end where they began.
* **It is not discoverable by a customer leaning on the tablet**, and it works from any screen —
  the recovery card, the workspace, a modal in the web layer.

Held keys are ignored (a held volume key is someone changing the volume). A wrong key that is
also the sequence's first key restarts rather than kills the attempt, so a fumbled first press
does not lock the owner out for a second. An accidental trigger costs nothing: the PIN sheet
appears with a Close button and no information on it.

## The admin PIN

§28: *"Admin PIN must not be hardcoded in source."* There is none in source — no default, no
fallback, no engineering code.

A tablet with no PIN set has **not been provisioned**, and the first time the gesture is
performed it offers to *set* one rather than asking for one. That enrolment window closes the
moment a PIN exists and cannot be reopened from inside the app. The only reset is clearing the
app's data from Android Settings, which needs the same physical access to an unlocked tablet
that setting it did.

Storage is `pbkdf2_sha256$<iterations>$<b64 salt>$<b64 key>` — PBKDF2-HMAC-SHA256, random
16-byte salt, 120,000 iterations, in app-private shared preferences. The iteration count is
carried *inside* the encoded value so the cost can be raised later without stranding a tablet
provisioned at the old cost. Backup and device-transfer are both off in the manifest
(`allowBackup="false"`, `fullBackupContent="false"`, explicit `dataExtractionRules`): a hash
copied into a cloud backup is a hash that can be attacked by someone who never touched the
tablet. Verification is constant-time — an early return on the first wrong byte turns a hundred
thousand guesses into sixty.

**What this does not claim.** It is not hardware-backed. A six-digit PIN is a hundred thousand
possibilities, and an attacker who has extracted the preferences file — needing root, an
unlocked bootloader, or ADB on an already-trusted device — can grind it offline whatever the
iteration count. The honest boundary: *this PIN keeps a customer, a curious member of staff or
a child out of the admin screen on a tablet sitting on a counter. It does not defend against
someone who has taken the tablet away and opened it up.* The upgrade, if that ever matters, is
an Android Keystore-backed key.

**UNMEASURED:** 120,000 iterations is expected to be on the order of a second on the SM-T290's
Exynos 7904 — slow enough to be worth something, fast enough that an owner typing a PIN does
not think the tablet has hung. That figure is *reasoned from the chip, not timed on it.* This
repository has no attached device. The first person to run this on the real tablet should time
it and record the number.

## Boot — what is promised and what is not

`BootPolicy.decide()` is the whole of it, and the limits are stated rather than discovered
later:

| broadcast | decision | why |
|---|---|---|
| `BOOT_COMPLETED`, user unlocked | **START** | the normal path |
| `BOOT_COMPLETED`, user locked | SKIP | — |
| `LOCKED_BOOT_COMPLETED` | SKIP | app-private storage is unreadable and the WebView cannot be created; starting here produces a black screen and a crash |
| `MY_PACKAGE_REPLACED` | **START** | coming straight back is what makes an update invisible rather than a tablet found on the launcher |
| anything else | SKIP | — |

Autostart off short-circuits all of it.

Three honest limits:

1. **`BOOT_COMPLETED` is delivered only after the user has unlocked the device at least once,
   if a secure lock screen is set.** A tablet with a lock-screen PIN does *not* start CROOKS by
   itself after a power cut — it starts CROOKS the moment somebody unlocks it. The only way
   round that is to have no secure lock screen, which is the right setting for a fixture on a
   counter, and is a **device setting, not something an app can do.**
2. **Samsung's One UI is aggressive about background start-ups.** An activity started from a
   broadcast receiver at boot is not guaranteed to come to the front; on some firmware it is
   silently dropped.
3. Because of (2), the **HOME alias** exists — being the launcher is the only mechanism on an
   unmanaged tablet that reliably puts an app on screen after a boot, because the system starts
   the home activity itself rather than being asked to. It ships **disabled**
   (`android:enabled="false"`), is switched on from the admin screen by someone who has typed
   the PIN, and can be switched off again from the same screen. Nothing enables it by itself.

So out of the box, **boot behaviour is best-effort, and the diagnostics screen describes it as
best-effort rather than promising it.**

## What has not been proven

There is no `/dev/kvm` on the build machine, so there is no Android emulator, and no SM-T290 is
attached. Therefore:

* Every stage-1 immersive behaviour is **unrendered**. No screenshot of this shell exists.
* The volume-key gesture has **never been performed on hardware**.
* `BOOT_COMPLETED` delivery on One UI has **never been observed** — limits (1) and (2) above are
  documented Android behaviour and Samsung's known firmware behaviour, not measurements taken
  here.
* The PIN derivation time on the Exynos 7904 is **reasoned, not timed.**

All of it is logic that is unit-tested on the JVM, and none of it is physical evidence. See
`CROOKS_PAD_ACCEPTANCE.md` for what a person with the tablet in their hands must actually do.
