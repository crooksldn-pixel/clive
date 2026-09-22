# COLD BOOT ACCEPTANCE

**Status: NOT RUN. This test cannot be performed on the machine that built it.**

There is no Mac here, no Samsung here, and no `/dev/kvm` to run an emulator. Every step below
is a physical action on physical hardware. Nothing in this document has been observed. It is
written so that the person holding the hardware can perform it without knowing anything about
the repository, and so that a pass is a pass rather than an impression.

## What this test is actually asking

> Turn the Mac on. Turn the Samsung on. Do nothing else.

Not "does it start" — *does it start when nobody helps it.* The failure this catches is the
one that hides behind a developer's hands: a system that works perfectly every time the person
who built it is standing there, because they unconsciously do the one step that is missing.

So the rule for the whole procedure is: **if you find yourself about to do something that is
not in the script, stop and write down what it was.** That thing is the finding.

## Before you begin

Both machines must be genuinely cold, not asleep:

* The Mac: Apple menu → Shut Down. Wait until the screen is black and the fan is silent.
* The Samsung: hold the power button → Power off. Wait until the screen is black.

Do not close CROOKS Control first. Do not stop anything first. **Shutting down with everything
running is the test** — an appliance is not allowed to require a tidy shutdown.

Write down the time. Leave both off for at least two minutes, so that nothing is resumed from
memory.

---

## Step 1 — press the Mac's power button

Then **take your hands off the keyboard** and start a timer.

Do not log in faster than you normally would. Do not open anything. Do not check anything.

**Watch for, and write down the time of each:**

| | what to watch for |
|---|---|
| a | the login screen appears |
| b | you log in (note: if the Mac does not auto-login, that is itself a finding — record it) |
| c | CROOKS Control appears on screen **by itself** |
| d | the big word on it settles on something that is not STARTING |

**PASS** requires (c) to happen without you opening anything, and (d) to settle on **ONLINE**.

**These are FAILURES, and each is a different one — record which:**

* CROOKS Control never appears → it is not set to open at login.
* CROOKS Control appears but says **OFFLINE** → the app started, CROOKS OS did not.
* It says **STARTING** and stays there → note how long. After two minutes it must turn itself
  into **ERROR** with a sentence. **A STARTING that never resolves is a failure even if CROOKS
  OS comes up later** — the panel lied for the duration.
* It says **ERROR** → write down the whole sentence, exactly, including punctuation. That
  sentence is the product; if it does not tell you what to do next without a terminal, that is
  the finding.

Record the time from power button to ONLINE. There is no target — this is a baseline nobody
has ever measured.

---

## Step 2 — do not touch the Mac again

Everything from here is on the tablet. If at any point you touch the Mac, the test is over and
the result is a fail; write down what made you reach for it.

---

## Step 3 — press the Samsung's power button

Then put it down and start a timer.

**Watch for, and write down the time of each:**

| | what to watch for |
|---|---|
| a | the Samsung's own boot animation ends |
| b | whether you have to swipe or type a PIN to get past the lock screen |
| c | CROOKS Pad appears **by itself** |
| d | CROOKS itself — the actual workspace, not the launch screen — is on the tablet |

**PASS** requires (c) and (d) without you opening any app.

**(b) is the known limit and is not automatically a failure — but it must be recorded.**
`BOOT_COMPLETED` is only delivered after the device has been unlocked at least once when a
secure lock screen is set. If this tablet has a lock-screen PIN, CROOKS Pad **will not** start
until somebody unlocks it, and no app can change that. If you had to unlock it:

* Record it.
* Then decide, with the owner, whether this tablet should have a lock-screen PIN at all. For a
  fixture on a counter the answer is usually no, and removing it is a **device setting**, done
  once, in Android Settings — not a code change.
* Then **repeat step 3 from a cold boot** with the PIN removed, and record that result too.
  That second result is the one that answers the acceptance question.

**Failures, each distinct:**

* The tablet lands on the Android launcher and stays there → the shell did not come to the
  front. This is the known One UI behaviour: an activity started from a boot broadcast is not
  guaranteed to be brought forward. The remedy is the HOME alias, which ships **disabled** and
  is switched on from the admin screen. If you turn it on, **record that you did**, and repeat
  step 3 — the pass with the alias on and the pass with it off are different results and the
  report must say which one this is.
* CROOKS Pad opens and shows a **recovery card** → read the card and write down which one.
  Each of the eight states means something different and the card names it.
* CROOKS Pad opens and shows a **blank white or black rectangle** → this is the worst outcome
  and the most important to capture. Photograph it. Do not reload. Go to step 6.

---

## Step 4 — read the Mac from across the room

Do not walk over. Do not pick anything up. Look at CROOKS Control from where you are standing.

**It must say CROOKS PAD: CONNECTED.**

This is the §26 check and the one most likely to be quietly wrong. **CONNECTED must mean the
tablet checked in, not that the Mac is serving a route.** To prove it does:

1. Note that it says CONNECTED.
2. **Switch the Samsung off** — hold power, Power off, wait for black.
3. Watch CROOKS Control. Within about ninety seconds it must change to **DISCONNECTED** with a
   "last seen" time.
4. **If it still says CONNECTED after three minutes with the tablet switched off, that is a
   failure**, and it is the most serious one in this document — it means the control panel
   reports a tablet that is not there, which is worse than reporting nothing.
5. Switch the Samsung back on and confirm it returns to CONNECTED on its own.

Record the time it took to notice the tablet had gone, and the time it took to notice it was
back.

---

## Step 5 — ask CROOKS something

Out loud, on the tablet, the way the owner would. Something read-only and ordinary:

> "What came in today?"

**PASS** requires: it hears you, it answers, and the answer appears on the tablet.

If the microphone is refused, the tablet must show a **CROOKS card explaining it with one
button**, never a silent failure and never an Android dialog with no context. Record what it
showed.

---

## Step 6 — if anything above failed

Do not fix it yet. First, **capture the evidence**, because the state you are in will be gone
the moment you touch anything:

1. **Photograph the tablet screen.** Whatever is on it, including a blank rectangle.
2. **Photograph the Mac screen** showing CROOKS Control as it is now.
3. On the tablet, perform the admin gesture — **volume DOWN, UP, DOWN, UP, DOWN, UP**, six
   presses, alternating, each within about a second of the one before — and open
   **Diagnostics**. Photograph it. Diagnostics needs no PIN, deliberately, because it is the
   one screen you need when nothing works.
4. On the Mac, in CROOKS Control, open **Developer Mode** and photograph it.

Only then start fixing. And write down, for each thing you did to fix it, whether CROOKS
Control could have done it. **Every "no" is a Phase 6 defect**, not a note for the owner.

---

## What a PASS means, and what it does not

A pass here means: *this hardware, in this building, on this day, came up by itself.*

It does not mean the appliance will come up every time. Cold boot is a race — launchd, the
network, Tailscale, the tablet's Wi-Fi association, all coming up at once — and a race that
passes once has not been shown to be a race that passes. **Run this three times before
believing it**, and run it once with the network switched off at the router to see what the
tablet says when the Mac is up but unreachable.

Record all three. Three passes is evidence. One pass is an anecdote.
