# CROOKS Control

The Mac's control centre for CROOKS OS. Turn the Mac on; this is open. Everything that has to
be done to CROOKS OS is a button on it, and there is no Terminal in normal ownership.

The first viewport answers five questions and asks nothing:

    IS CROOKS OS RUNNING?      ONLINE / STARTING / STOPPING / OFFLINE / ERROR, in one word
    IS THE TABLET CONNECTED?   CROOKS Pad, with when it was last heard from
    ARE SERVICES HEALTHY?      backend, hearing, Claude, ElevenLabs, Shopify, Gmail, Tailscale
    WHAT VERSION?              the running build, the checkout, the last known-good build
    IS A TEST SESSION ACTIVE?  a band, while one is

## The shape of it, and why

The package is two targets and the split is the point.

    Sources/CrooksControlCore   Foundation only. EVERY decision the app makes.
    Sources/CrooksControl       SwiftUI and AppKit. Draws the core. Decides nothing.

`CrooksControlCore` builds and its tests run on any machine with a Swift toolchain, macOS or
not — which is where they were written and where they run in CI. `CrooksControl` can only be
built on a Mac, and `Package.swift` declares it only when the manifest is compiled on one.

The reason for the split is not tidiness. It is that the app's judgements are the part that
can be wrong in ways nobody notices: whether a process that started is a system that is up,
whether a route to the tablet is a tablet on the end of it, whether an update that finished is
a build that works. Those live in the core, where a test can drive them from a real document.
What is left in the view layer is layout.

## What it does, and what it will not do

The app is a renderer. Every colour, every row, every refusal and every command comes from one
place:

    crooks-control status      the state, every row, both build ids   (no network)
    crooks-control plan        what an update would do: current vs candidate SHA
    crooks-control apply --yes the update itself
    crooks-control rollback --yes  back to the last known-good build, where that is safe
    crooks-control actions     the buttons, and the command behind each
    crooks-control contract    what every field of every document above means

Try any of them in Terminal; the app sees exactly what you see. The app runs no command of its
own — no version control, no service manager, no test runner of its own idea. It does not even
know what a start command looks like: if `crooks-control actions` lists an action with the id
`start`, there is a START button; if it does not, there is no START button and the app says so
in words. **A control that cannot do anything is never drawn.**

It also refuses to run a shell. The commands in the actions document are executed with an argv
array and no shell anywhere, and a document that named `/bin/sh` as the executable would have
that button drawn grey with the reason on it.

## The three things it is careful about

**Starting is not running.** `launchctl kickstart` returns 0 the moment launchd accepts the
job. The app shows STARTING when you press START and moves to ONLINE only when a status
document reads back as answering — never because a command succeeded, and never because a
process has a pid. STARTING also does not last forever: after two minutes it becomes ERROR
with a sentence, because a spinner that never resolves is the most dishonest thing a control
panel can do.

**A route is not a connection.** The status document carries a Tailscale hostname. That is a
door being open. It says nothing about whether the Samsung is switched on, in the shop, or
running CROOKS Pad. So CROOKS CONNECTED is shown only when the pad itself has checked in
within ninety seconds; when the control script does not report the pad's own check-in, the
card says NOT REPORTED and explains the difference, rather than showing the route and calling
it a connection.

**An update that finished is not an update that worked.** `crooks-control apply` returns
`ok: true` when it did everything it was asked — fetched, fast-forwarded, tested, restarted. If
the backend then fails to answer /health, the script says so (`next` becomes `verify_by_hand`,
`marked_good` stays null) but `ok` is still true and the process still exits 0. The app reads
those three fields and not the `ok`: an update that moved the build and did not come back is
UPDATE FAILED, in red, with ROLL BACK beside it.

## Developer Mode

Off, and a sheet rather than a section, so it cannot crowd the front page (§5.7). It holds
every row the control script sent rather than the seven the front page shows, the exact argv
behind each button, the last failure with its exit code and its traceback, the contract
version, the loopback port, and the uncommitted files. One thing is withheld from it and is
not negotiable: credentials. Every string in this app, in either mode, has been through
`Redaction`, which uses the same shapes `scripts/control.py` redacts by.

## Build it on the Mac

    cd crooks-assistant
    make commands                    # put crooks-control on the PATH
    make control-app                 # test the core, build the app, move it to /Applications

`make control-app` runs `mac/CrooksControl/build.sh --install`, which runs the core's tests
first. To have the app open at login as well: `sh mac/CrooksControl/build.sh --login`.

The first run looks for the CROOKS OS folder in the usual places (`~/crooks-assistant`,
`~/Shopify-theme/crooks-assistant`, `~/Documents`, `~/Developer`, `~/code`). If it is
somewhere else, click **CROOKS OS folder…** and choose the folder holding `scripts/control.py`.

Nothing about the backend changes: the assistant and whisper-server still start at login
through the launchd agents `make install` wrote.

## Check it anywhere else

    ./verify.sh

Builds the core, runs its tests, and parses the Mac app's sources. Read the note at the top of
that script before trusting the third one: `swiftc -parse` proves the SwiftUI files are valid
Swift and nothing more. It does not type-check them and it does not resolve SwiftUI or AppKit,
so it will pass a view that calls a method that does not exist. **A green run of verify.sh off
a Mac is not evidence that the app builds.** The script says so itself, in the output, rather
than reporting four passes.

## The optional fields, for whoever extends control.py next

The app already reads three fields the control script does not send yet. Each is optional and
each has an honest fallback, so adding them is an improvement rather than a requirement:

    service      {state, detail, managed, pid, healthy}
                 The process truth. Only `healthy` — meaning /health answered — decides
                 anything; `pid` is shown in Developer Mode and is deliberately never read as
                 "CROOKS OS is up". Without it the app falls back to the `online` row.

    pad          {seen_at, agent, address, build}
                 The CROOKS Pad's own check-in. Without it the pad card says NOT REPORTED,
                 because there is no substitute for it. This is the single most valuable field
                 anyone could add.

    uptime_s     A number. The `online` row carries the uptime as prose ("up 2.1h") and the app
                 will not parse it back out of an English sentence; without a number the
                 uptime reads "not reported".

## Files

    Package.swift                     two targets; the app one is declared only on macOS
    Info.plist                        the bundle
    build.sh                          test, build, assemble the .app, install, login item
    verify.sh                         what can be checked off a Mac, and what cannot
    Sources/CrooksControlCore/
      Contract.swift                  the version check, run before the decode, and tolerance
      StatusDocument.swift            `status`, as types, and "is the backend answering"
      UpdateDocument.swift            `plan` / `apply` / `rollback`, as types
      ActionsDocument.swift           the buttons, the known ids, and what may be run
      Lifecycle.swift                 ONLINE/STARTING/STOPPING/OFFLINE/ERROR, and saying it once
      Pad.swift                       connected, idle, away, never seen, no route, cannot tell
      UpdateVerdict.swift             did the update actually work
      Humanising.swift                every failure, as a sentence a shopkeeper can act on
      Redaction.swift                 the same shapes control.py redacts by
      Formatting.swift                durations and "ago", written as control.py writes them
      Dashboard.swift                 the one value the app draws
      DashboardBuilder.swift          everything the app knows, turned into that value
    Sources/CrooksControl/
      CrooksControlApp.swift          the window, the menu-bar glance, the app's own clock
      Centre.swift                    runs the script, feeds the core, publishes the dashboard
      ControlRunner.swift             the subprocess, and where the checkout is
      Theme.swift                     web/style.css's tokens, transcribed
      DashboardView.swift             the first viewport
      ActionsView.swift               the controls
      UpdateView.swift                the two-click update
      DeveloperView.swift             the sheet, and the output window
    Tests/CrooksControlCoreTests/
      Fixtures.swift                  real documents, produced by the real control.py
      ContractTests.swift             version mismatch, decoding, tolerance
      LifecycleTests.swift            the state machine, the timeouts, no notification spam
      PadTests.swift                  connected vs merely reachable
      UpdateVerdictTests.swift        moved but unhealthy is a FAILURE
      ActionTests.swift               start/stop, ordering, grey buttons, what may be run
      DashboardTests.swift            the five questions, Developer Mode, no secrets on screen
