# CROOKS CONTROL — the Mac's control centre

Turn the Mac on; this is open. Everything that has to be done to CROOKS OS is a button on it,
and there is no Terminal in normal ownership.

## The first viewport answers five questions and asks nothing

```
  IS CROOKS OS RUNNING?      ONLINE / STARTING / STOPPING / OFFLINE / ERROR — one word
  IS THE TABLET CONNECTED?   CROOKS PAD, with when it was last heard from
  ARE SERVICES HEALTHY?      backend · hearing · Claude · ElevenLabs · Shopify · Gmail · Tailscale
  WHAT VERSION?              the running build, the checkout, the last known-good build
  IS A TEST SESSION ACTIVE?  a band, while one is
```

No scrolling. No login. No configuration on first run beyond pointing it at the folder, and it
looks in the usual places first.

## Two targets, and the split is the point

```
  Sources/CrooksControlCore   Foundation only.  EVERY decision the app makes.
  Sources/CrooksControl       SwiftUI + AppKit. Draws the core. Decides nothing.
```

`CrooksControlCore` builds and its tests run on any machine with a Swift toolchain, macOS or
not — which is where they were written and where they run. `CrooksControl` can only be built on
a Mac, and `Package.swift` declares it only when the manifest is compiled on one.

The reason is not tidiness. The app's *judgements* are the part that can be wrong in ways
nobody notices:

* whether a process that started is a system that is up,
* whether a route to the tablet is a tablet on the end of it,
* whether an update that finished is a build that works.

Those live in the core, where a test can drive them from a real document. What is left in the
view layer is layout.

This also happens to be the only architecture that could be built honestly on a Linux box with
no macOS SDK — but it would be the right architecture on a Mac too, and it is worth saying so,
because an architecture adopted for a build-machine limitation is one that gets quietly undone
the first time somebody has a Mac.

## It is a renderer, and it runs one command

Every colour, every row, every refusal and every command comes from one place:

```
  crooks-control status          the state, every row, both build ids   (no network)
  crooks-control plan            what an update would do: current vs candidate SHA
  crooks-control apply --yes     the update itself
  crooks-control rollback --yes  back to the last known-good build, where that is safe
  crooks-control actions         the buttons, and the command behind each
  crooks-control contract        what every field of every document above means
```

Run any of them in a terminal and the app sees exactly what you see.

**The app runs no command of its own.** No version control, no service manager, no test runner
of its own idea. It does not even know what a start command looks like: if `crooks-control
actions` lists an action with the id `start`, there is a START button; if it does not, there is
no START button **and the app says so in words**. A control that cannot do anything is never
drawn — that is Phase 5's invariant 12, enforced here rather than restated.

That enforcement had to be built rather than assumed: the "missing controls" list was
*declared*, *supplied*, and *never read* — invariant 12 as decoration. Wiring it was one of
this phase's fixes, and it is tested in `CrooksControlCore`, where the decision lives, not in
the view.

**It refuses to run a shell.** Commands from the actions document are executed with an argv
array and no shell anywhere. A document naming `/bin/sh` as the executable has that button
drawn grey with the reason on it.

## The three things it is careful about

### Starting is not running

`launchctl kickstart` returns 0 the moment launchd *accepts* the job — including for a service
that then dies on its first import. So the app shows **STARTING** when you press START and
moves to **ONLINE** only when a status document reads back as answering. Never because a
command succeeded. Never because a process has a pid.

And STARTING does not last forever: after two minutes it becomes **ERROR** with a sentence,
because a spinner that never resolves is the most dishonest thing a control panel can do.

The same principle bit the layer underneath during this phase, in the most ordinary sequence
there is. `start()` decided "already registered" from whether the **plist file existed** rather
than from what launchd said, and the file is still on disk after a stop — so **stop, then
start, did not start.** It was invisible because the test's stand-in for launchd returned
success from `kickstart` unconditionally. **A double that always succeeds measures the double.**

### A route is not a connection

The status document carries a Tailscale hostname. That is a door being open. It says nothing
about whether the Samsung is switched on, in the shop, or running CROOKS Pad.

So **CONNECTED is shown only when the pad itself has checked in recently.** When the control
script does not report the pad's own check-in, the card says **NOT REPORTED** and explains the
difference, rather than showing the route and calling it a connection.

`PadPresence` has six cases and the two at the end are the honest ones: `noRoute` (Tailscale is
not serving, so the pad could not reach this Mac even if it wanted to) and `cannotTell` (the
script does not report it, and not knowing is not a fault — but it must not be drawn as one,
and it must not be drawn as a connection either).

### An update that finished is not an update that worked

`crooks-control apply` returns `ok: true` when it did everything it was asked, and exits 0 even
if the backend then fails to answer `/health`. The app reads `next`, `marked_good` and the
stages — **not `ok`**. An update that moved the build and did not come back is **UPDATE
FAILED**, in red, with **ROLL BACK** beside it. See `UPDATE_SYSTEM.md`.

## The version check comes first

The first version of this app decoded the whole document and *then* looked at `contract`. That
got the order exactly wrong: a script one version ahead, with a field moved, failed as
"answered something I could not read" — a dead end — when the true answer was "build the app
again from this checkout".

So the version is read on its own first, out of a probe with one field in it, which therefore
cannot fail for any other reason. The app understands version 2 and reads the range {1, 2};
`scriptIsNewer` and `scriptIsOlder` each produce a sentence naming the fix. Everything else in
the document decodes **leniently** — one added or renamed field in Python must not leave the
owner looking at an app that draws nothing at all.

## Developer Mode

Off by default, and a **sheet rather than a section**, so it cannot crowd the front page. It
holds every row the control script sent rather than the seven the front page shows, the exact
argv behind each button, the last failure with its exit code, the contract version, the
loopback port, and the uncommitted files.

One thing is withheld and is not negotiable: **credentials.** Every string in this app, in
either mode, has been through `Redaction`, which uses the same shapes `scripts/control.py`
redacts by — and there is now a test that fails if the two drift, because byte-identical today
is not a property, it is a coincidence.

CROOKS Control may say *"Shopify connected"*. It may never print what connected it.

## Building it

```
  cd crooks-assistant
  make commands        # put crooks-control on the PATH
  make control-app     # test the core, build the app, move it to /Applications
```

`make control-app` runs `mac/CrooksControl/build.sh --install`, which runs the core's tests
first. `sh mac/CrooksControl/build.sh --login` also has it open at login.

## What `verify.sh` does and does not prove

`./verify.sh` builds the core, runs its tests, and parses the Mac app's sources.

`swiftc -parse` proves the SwiftUI files are **valid Swift and nothing more**. It does not
type-check them and it does not resolve SwiftUI or AppKit, **so it will pass a view that calls
a method that does not exist.**

A green run of `verify.sh` off a Mac is therefore not evidence that the app builds — and the
script must not exit 0 while saying so. That it did, printing "the Mac app builds — NOT RUN"
and returning success, was a defect found in this phase. **A check that cannot measure
something must not report a pass**, which is the single rule §26 is made of.

**Nothing in this app has ever been compiled against SwiftUI or AppKit.** Verified directly on
this machine: Swift 6.0.3 for Linux answers `no such module 'SwiftUI'`. The first `xcodebuild`
on a real Mac is the first moment anyone learns whether CROOKS Control compiles.
