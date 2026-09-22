# THE UPDATE SYSTEM

## What it is for

An appliance that cannot be updated is a museum piece; an appliance that can update itself into
a brick is worse than one that cannot update at all. So the whole of this design turns on one
sentence:

> **An update that finished is not an update that worked.**

Everything below exists to keep those two facts apart.

## The eight stages

`crooks-update` (`scripts/update.py`) runs eight stages. Any one of them stops the run, and each
reports itself into a document the Control app renders.

| # | stage | what it does |
|---|---|---|
| 1 | **find** | locate the checkout this command belongs to |
| 2 | **branch** | it is the branch you meant, and the tree is clean enough to move |
| 3 | **fetch** | from the remote |
| 4 | **pull** | **FAST-FORWARD ONLY** — never a merge, never a rebase, never a reset |
| 5 | **deps** | only when the dependency files actually changed |
| 6 | **tests** | the offline suite — **nothing restarts if it fails** |
| 7 | **restart** | the backend and whisper-server, through launchd |
| 8 | **verify** | read `/health` back, with the build id |

Stage 6 is the one that makes this safe rather than merely convenient: a build that does not
pass the suite **never becomes the running build**. It is run between the fast-forward and the
restart, so the failure mode is "your checkout moved and the old code is still serving", which
is recoverable, rather than "the new code is serving and it is broken", which is an outage.

## What it will not do, by construction

* **It will not discard local work.** A dirty tree or a diverged branch stops the update and
  says so. There is no `--force` and no `reset`.
* **It will not touch `.env`, `logs/`, `reports/` or `.venv`.** They are not in git and nothing
  in the updater writes them. Credentials cannot be lost to an update because the updater has
  never been able to see them.
* **It will not decide to update itself.** Nothing in CROOKS OS calls it. It runs when the
  owner asks, and `crooks-control apply` is the same rule wearing a button: on a click, never
  on a timer and never on a boot.

That last one is worth defending because it will be questioned. An appliance that updates
itself unattended is an appliance that can be broken by a push at 3am with nobody in the
building. The brief's §32 forbids deploying a breaking build automatically; the simplest way to
honour that is never to deploy automatically at all.

## The known-good record — and who may write it

`logs/last_known_good.json` is the only thing standing between a bad update and a manual
recovery. It records the sha, the branch, the subject, the build id `/health` reported, when it
was recorded, and by which command.

It is written **whole and renamed into place, 0600 in a 0700 directory** — the same way the
test session's own files are written — so a crash mid-write cannot leave a half-record that
reads as valid. It lives in `logs/`, which `NEVER_TOUCH` keeps the updater away from.

**It is written after `/health` has been read back, never before.** That ordering is the whole
value of the record: a build marked good because a command exited 0 is a build marked good
because a process started, which is the §26 trap with the highest cost, because it is the fact
you fall back to when everything else has failed.

**Exactly two commands may write it:** `crooks-control apply` (on success, after the health
read) and `crooks-control mark-good`. That is enforced by a test, and the enforcement matters
more than it looks: the first version of that test was rewritten during this phase from a
string scan into an identifier scan, and **stopped catching a second writer** — a file dropped
into `scripts/` that wrote the record by path passed it. It has been restored to a gate that
catches a writer by any route.

## Rollback

`rollback_decision()` answers two questions and never guesses at either:

* **Is a rollback available?** The recorded commit must exist in this checkout and must be a
  different commit from the one running. If no known-good build has ever been recorded, it says
  so, and says how one gets recorded.
* **Is it safe?** The tree must be clean. Local changes stop it: going back would carry them
  onto an older build. Nothing is thrown away and the message says so.

The rollback is a `git checkout` of the recorded sha, which leaves the checkout on a detached
HEAD. That is deliberate — nothing is moved and nothing is lost — and it is the one place where
the design and the no-Terminal claim rub against each other, because *coming forward again* was
described to the owner as a git command he would have to type. See **Known gap** below.

## How the Control app reads all this — and why it ignores `ok`

`crooks-control apply` returns `ok: true` when it did everything it was asked: fetched,
fast-forwarded, tested, restarted. **If the backend then fails to answer `/health`, `ok` is
still true and the process still exits 0.** That is not a bug; `ok` means "the command
completed", and the command did.

So the app does not read `ok`. It reads three other fields:

```
  next          "done" | "verify_by_hand" | "up_to_date" | "rollback" | "blocked" | "click_to_apply"
  marked_good   the record, or null
  stages[]      what each of the eight actually did
```

`next: "verify_by_hand"` with `marked_good: null` is **UPDATE FAILED**, drawn in red, with
**ROLL BACK** beside it — an update that moved the build and did not come back. A control panel
that read `ok` would have shown a green tick over a dead backend.

## The document contract

`--json` prints one document and no lines, carrying a `contract` integer. The Swift app checks
that version **before** decoding anything else, out of a one-field probe, so that a script one
version ahead fails as *"build the app again from this checkout"* rather than as *"answered
something I could not read"*.

The app understands version 2 and reads the range {1, 2}; the script is at `CONTRACT = 2` with
`compatible_clients = [1, 2]`. An equality check on either side is a deadlock waiting for the
next additive field — and was one, for a day, in this phase. See `ARCHITECTURE.md`, Contract 2.

## Known gap at the time of writing

The §5.2 gate (`tests/test_no_terminal.py`) is committed **red**. It names **eleven** strings
that leave a shell as the owner's only remedy — six in `scripts/update.py`, five in
`scripts/control.py` — of which the sharpest belongs to this document:

> the rollback button exists, and the way back **from** a rollback is a sentence telling the
> owner to type `git checkout <branch>`.

Until that gate is green, the update system is Terminal-free on its happy path and not on its
unhappy ones — which is the half that matters, because the unhappy path is the only one the
owner reads while something is wrong.
