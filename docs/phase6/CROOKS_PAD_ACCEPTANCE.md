# CROOKS PAD ACCEPTANCE

**Status: NOT RUN. Nothing in this document has been observed.**

There is no `/dev/kvm` on the build machine, so there is no Android emulator, and no SM-T290 is
attached. **No screenshot of CROOKS Pad exists anywhere.** Every behaviour below is unit-tested
logic on the JVM and untested pixels on glass. This document is what a person with the tablet
must do to turn the first into the second.

Target: **Samsung Galaxy Tab A 8.0 (2019), SM-T290, Android 11, API 30.** Portrait viewport
601×889 CSS at DPR ≈ 1.33.

---

## Part 0 — install it

**One step at a time. Do each one and look at the result before reading the next.**

### Step 0.1

On the Mac, plug the Samsung in with a USB cable. On the tablet, a dialog will ask whether to
allow USB debugging. If no dialog appears, USB debugging is not switched on yet — that is
Settings → About tablet → tap **Build number** seven times, then Settings → Developer options →
**USB debugging**.

Tick "Always allow from this computer" and press **Allow**.

*Stop here. Did the dialog appear and did you press Allow?*

### Step 0.2

Install the app. This is the **only** step in the whole of Phase 6 that needs a cable, and it
is a once-per-tablet step, not an operating step.

Record which build you installed — **release, not debug.** A debug build has WebView contents
debugging switched on, which opens the page to anything that can reach ADB. The release build
has it off; that is a build-config difference, not a runtime setting, so a debug build cannot
be made safe by changing something on the tablet.

### Step 0.3

Unplug the cable. **Everything from here happens with no cable attached.** If you find yourself
reaching for the cable, write down why.

---

## Part 1 — the first run

### Step 1.1 — open CROOKS Pad from the launcher

Watch what happens and write down which of these it is:

* CROOKS appears → good, go to 1.2.
* A **recovery card** appears → read it. Which of the eight states does it name? Write it down
  verbatim. Then check the Mac: is CROOKS OS actually running? A card that correctly says the
  Mac is off is a **pass**, not a failure.
* A **blank rectangle**, white or black → photograph it. This is the most important failure in
  this document. Do not reload. Go to Part 5.

### Step 1.2 — is the shell invisible?

§19: when the pad is ONLINE, the WebView is the whole screen. **Nothing native is drawn — no
banner, no badge, no toast, no title bar, no version string in a corner.**

Look at all four edges of the screen. If you can see anything that is not CROOKS, write down
what and where.

### Step 1.3 — can you reach every control?

This is the Phase 5 collision gate, performed by hand at the real density, and it is the
question the automated gate could not answer: the automated one measures rectangles in a
headless browser at 601×889; **you are measuring a finger on glass.**

Go through the workspace and **press every visible control with one finger**, the way an owner
would — not carefully, not with a fingernail. For each one write down: did it do what it said,
or did something else happen?

The specific thing to watch for: **did pressing a control start a voice recording?** That was
Phase 4's defect — sixty-three ordinary control taps became voice recordings because an
invisible surface sat where the controls were. It is fixed and gated in the web layer. **The
native shell adds a new chance to reintroduce it**, because anything the shell draws sits
*above* the WebView. That is why the admin gesture is volume keys and not a hidden corner. If
any tap starts a recording, that is a P0 and the whole acceptance stops.

### Step 1.4 — the microphone

Ask CROOKS something out loud. Something ordinary and read-only:

> "What came in today?"

Android will ask for the microphone the first time. Press **Allow**.

Now the part that matters. **Deny it deliberately** and see what the product does:

1. Settings → Apps → CROOKS Pad → Permissions → Microphone → **Don't allow**.
2. Go back into CROOKS Pad and try to speak.

**PASS** requires a **CROOKS card**, in CROOKS' own design, explaining that the microphone is
off, with **one button** that fixes it. A silent failure is a defect. A bare Android dialog
with no context is a defect. Write down exactly what appeared.

Then put the permission back.

---

## Part 2 — the way out

### Step 2.1 — the admin gesture

**Volume DOWN, UP, DOWN, UP, DOWN, UP.** Six presses, alternating, each within about a second
of the one before.

Do it at ordinary speed, standing up, the way you would if you needed it. Write down: *did it
work first time?* If it took you three attempts, the timing is too tight and that is a
finding, not user error.

Confirm the volume genuinely goes down and up as you press — the presses are not swallowed,
and six alternating presses end where they began.

### Step 2.2 — the PIN

The first time, it should offer to **set** a PIN, not ask for one. There is no default PIN in
the source and there is no engineering backdoor.

Set one. Write it down somewhere that is not the tablet.

**Then check the trap:** the only way to reset a forgotten PIN is clearing the app's data from
Android Settings. Confirm that Android Settings is still reachable — press the recents key and
the home key and get to Settings. At stage 1 this must work. **If you cannot get to Settings,
stop: the tablet is on its way to being a brick and something has gone wrong that this document
did not predict.**

### Step 2.3 — diagnostics with no PIN

From a recovery card, open **Diagnostics**. It must open **without** the PIN — deliberately,
because it is the one screen you need when nothing else works.

Read every line of it. **Nothing secret may be on it**: no Shopify token, no Gmail account, no
API key, no Wi-Fi SSID, no IP address, no MAC address, no serial number, no advertising ID. If
you see any of those, that is a security defect and it is a P0.

Confirm it says honestly whether Knox was found. "No Knox on this tablet" is the expected and
correct answer on an SM-T290 — the point is that it was **looked for** rather than assumed.

---

## Part 3 — the heartbeat, proved by disproof

A row on the Mac saying CONNECTED is worth nothing until you have seen it say DISCONNECTED
while the tablet was off.

1. With both running, confirm the Mac says **CROOKS PAD: CONNECTED**.
2. Put the tablet into **aeroplane mode**. Do not switch it off — this tests the network path
   specifically.
3. Watch the Mac. Within about ninety seconds it must say **DISCONNECTED**, with a "last seen"
   time that is roughly right.
4. Watch the *tablet*: it should show **NETWORK_OFFLINE**, not "the Mac is off". The tablet
   must not accuse the Mac of being off when it cannot see anything at all.
5. Turn aeroplane mode off. Both sides must recover **by themselves**, with no tap.

Write down all four times. If step 3 never happens, the Mac is reporting a tablet that is not
there, and that is worse than reporting nothing.

---

## Part 4 — the states nobody tests

Each of these is a real situation the owner will hit, and each must produce a card that names
the right thing:

| do this | the tablet must say |
|---|---|
| put the Mac to sleep | the Mac is not answering — **not** a network problem |
| switch the Wi-Fi off at the router | a network problem — **not** that the Mac is off |
| stop CROOKS OS from CROOKS Control | the Mac is not answering, and it must recover on its own when you start it again |
| leave the tablet alone for an hour | CROOKS still on screen, still responsive, **screen not gone black** |
| leave it a whole day | still working — record the battery percentage at both ends |

**The rule from §17 applies to every one of them:** either it retries by itself *and shows when
the next attempt is*, or it offers exactly one thing to press. A spinner with no countdown is
indistinguishable from a hang, and after about fifteen seconds a reasonable person concludes
the thing is broken. If you see a spinner with no countdown, write down which state.

---

## Part 5 — if you got a blank rectangle

This is the failure worth the most, because it is the one that reaches the owner as "the tablet
is broken" with nothing to go on.

1. **Photograph it.**
2. Do the admin gesture and open **Diagnostics**. Photograph it. What does it say the state is?
3. Look at the Mac. What does CROOKS Control say about the pad?
4. **Only then** reload.

The specific thing this is looking for: the shell must not report **ONLINE** while the screen is
blank. A load that failed — a 502, a TLS error, a dead render process — must poison that load so
it cannot be promoted to ONLINE by the page-finished callback that arrives afterwards. Chromium
fires the error callbacks *before* `onPageFinished`, which is exactly how a broken page gets
reported as a good one. If diagnostics says ONLINE while you are looking at a blank rectangle,
that is the bug, and it is a P0.

---

## What a pass means

It means this tablet, in this room, on this day, did these things once.

It does not mean the timings are right for the owner, that the gesture is findable under
pressure, or that the recovery cards read well to someone who did not write them. Those are
judgements, and they need the owner, not a tester. **Hand him the tablet with CROOKS OS
switched off and watch what he does.** Write down where he hesitates. That list is worth more
than everything above it.
