# KNOWN LIMITATIONS

Two things belong in this document and they are different. First: the **§4 non-regression
boundary** — the twelve invariants Phase 5 established, and where each one is enforced now that
there is an appliance layer around the engine. Second: **what is still not true**, which is the
part that matters to whoever picks this up next.

---

## Part 1 — the twelve invariants, and where they live now

The rule from the brief: *"If Phase 6 requires changing any of these: STOP and explain why
before changing them."* **None of the twelve was changed.** Several are enforced in more places
than before; none is enforced in fewer.

| # | invariant | what the appliance layer does to it |
|---|---|---|
| 1 | the model never directly performs privileged writes | **untouched** — neither native app gives the model a path it did not have. The Pad's bridge is read-only; Control executes only the argv the server's own actions document names. |
| 2 | the server owns the exact immutable staged action | **untouched** — neither native app stages anything, holds a nonce, or carries a mutation. |
| 3 | client gestures never supply mutation arguments | **strengthened by construction.** The Pad's admin gesture is volume keys, which the WebView never sees; the bridge has no method that takes an argument at all. Control's buttons carry an action **id** and nothing else — the argv comes from the server side. |
| 4 | the server executes at most once | **untouched.** |
| 5 | writes use authoritative precondition rereads | **untouched.** |
| 6 | success requires deterministic verification | **reinforced.** `apply` marks a build good only after `/health` has been read back; `start` reports ONLINE only after `/health` answers, never because `launchctl` exited 0. The appliance layer adopted the engine's rule rather than inventing a weaker one. |
| 7 | unknown mutations fail closed | **extended to two new vocabularies.** An unrecognised `pad_*` event kind is rejected **and counted**; an actions document naming a shell as its executable has that button drawn grey with the reason on it. |
| 8 | no arbitrary model HTML or JS | **untouched, and the new surface is closed.** The bridge is one annotated read-only method. There is no dispatcher, no `eval` path, and nothing that takes a name and acts on it. |
| 9 | the service worker never replays writes | **untouched** — the web layer is unchanged. |
| 10 | PII stays scrubbed from telemetry where designed | **extended** to the pad's own identity strings (`device_model`, `os_version`, `app_version`), which reach `/health`, the Control app and reports. This one had an **ordering defect** in this phase: the character filter ran before the scrub, so an e-mail in `device_model` arrived with only its `@` removed. Fixed, and the test that was supposed to catch it asserted on a literal the filter had already made impossible. |
| 11 | explicitly spoken entities outrank incidental screen focus | **untouched.** |
| 12 | no fake UI or control may be shown if the server cannot perform it | **enforced rather than restated — after being found decorative.** Control's missing-controls list was declared, supplied, and never read. It is now wired, and tested in the Foundation-only core where the decision lives rather than in a view that cannot be built here. |

**Nothing on the "may not rewrite" list was rewritten**: not the action engine, the Shopify
connector, the Gmail connector, proposal semantics, execution verification, the business safety
invariants, Phase 5 workspace logic, entity resolution, the existing FAST recipes, or the
browser presentation architecture.

---

## Part 2 — what is not true yet

### The largest one: two of the three surfaces have never been drawn

| surface | ever rendered? |
|---|---|
| the CROOKS web UI | yes — headless Chromium at 601×889 |
| **CROOKS Control** | **no. Not once, by anyone.** |
| **CROOKS Pad** | **no. Not once, by anyone.** |

For CROOKS Control the exposure is larger than "unseen", because nothing has type-checked it
either. Verified directly on this machine: Swift 6.0.3 for Linux answers `no such module
'SwiftUI'`. `swiftc -parse` proves the view files are valid Swift and **will pass a view that
calls a method that does not exist.** The first `xcodebuild` on a Mac is the first moment anyone
learns whether this app compiles, and finding compile errors then would not mean the design is
wrong.

The mitigation is the target split — every decision in `CrooksControlCore`, which builds and is
tested here; only layout in the views — so a first-build failure is *expected* to be a layout
fix rather than a logic fix. **That is a prediction, recorded as one so it can be checked.**

For CROOKS Pad: there is no `/dev/kvm`, so no emulator, and no SM-T290 is attached. `:core` is
the only part that has ever executed. `:app` compiles into a real APK that has never been run.

### Physical behaviour that is reasoned, not measured

* **PIN derivation cost.** 120,000 PBKDF2 iterations is expected to be about a second on the
  Exynos 7904. Reasoned from the chip, never timed on it. Whoever runs it first should time it.
* **Boot on One UI.** That an activity started from a boot broadcast may be silently dropped is
  documented Samsung behaviour, not an observation made here. The HOME alias exists because of
  it and ships disabled.
* **`BOOT_COMPLETED` and the lock screen.** A tablet with a secure lock screen does not start
  CROOKS Pad until somebody unlocks it. No app can change that; it is a device setting.
* **Cold-boot timing** — from power button to ONLINE, on either machine — has never been
  measured. There is no target because there is no baseline.

### Kiosk stops at stage 1, deliberately

Stage 2 (lock task) and stage 3 (device owner) are detected, described in diagnostics, and off.
Stage 3 *begins* with a factory reset, which §34 forbids without the owner's explicit approval,
so it was not reachable in this phase even in principle. Stage 2 is off because combined with
the HOME alias it produces a tablet whose only route back to Settings is an admin PIN this
shell stores as a hash it cannot recover — **and that combination has never been rehearsed on
the real device.**

### The admin PIN is not hardware-backed

PBKDF2 with 120,000 iterations keeps a customer, a curious member of staff or a child out of
the admin screen on a tablet sitting on a counter. It does **not** defend against someone who
has taken the tablet away and opened it up: a six-digit PIN is a hundred thousand
possibilities, and an attacker who has extracted the preferences file can grind it offline
whatever the iteration count. The upgrade, if it ever matters, is an Android Keystore-backed
key.

### The heartbeat is trusted exactly as far as the tailnet

Anyone the middleware admits could post a heartbeat and be believed. That is the same trust
model `/telemetry` has had since Phase 5. The honest claim it supports is *"something on the
owner's private network, speaking the appliance's protocol, is checking in"* — a great deal
more than "a route resolves", and rather less than a signed device identity. Nothing is
authorised by it. If a reason ever appears to make it stronger, the place is the middleware,
not a secret in the route.

### No certificate pinning

A decision, not an omission. `tailscale serve` issues and rotates the certificate; a pin would
turn a routine rotation into a dead tablet in a workroom with no laptop, and buys nothing
against an attacker already inside the tailnet.

### What `verify.sh` cannot do

It builds the core and runs its tests, which is real. Its third check parses the view sources
and proves only that they are valid Swift. **A green run off a Mac is not evidence that the app
builds**, and the script must not exit 0 while saying "NOT RUN".

### The engine is untouched — including its own limits

Phase 6 did not begin the V2 kernel rewrite, as instructed. Every limitation Phase 5 recorded
about the engine is still there, unchanged, and is not restated here.
