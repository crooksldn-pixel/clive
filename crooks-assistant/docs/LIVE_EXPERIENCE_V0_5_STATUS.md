# CLIVE LIVE EXPERIENCE V0.5 — STATUS

Companion to `LIVE_EXPERIENCE_V0_5.md`, which is the contract and is not modified here.
Branch: `claude/v05-parallel-worker-20260921`. Not production. No deploy, no connector or
credential change, no write authorised by anything in this stream.

Read this for two things: what the contract's slices actually have behind them now, and the
short list of items that are blocked on a decision rather than on work.

## Where each slice stands

### A · Retire Split without destroying concurrency — done

The user-facing Split is gone: no Split chip, no gesture that divides, no halves on the glass.
`#branch-zone` still exists, hidden and labelled "Internal concurrency", and `splitOrb` and the
branch APIs are untouched — invariant 1 says stop inviting the owner to drive concurrency, not
delete the primitive.

Four tests that asserted the retired shell were replaced rather than left red
(`test_pwa`, `test_routes`, `test_web`, `test_touch`), which is what the evidence gate asks for.

### B · One continuous voice state — done

`web/live-state.js` is the single state authority: the contract's seven canonical states plus
`INTERRUPTED`, `FAULT` and `RECOVERING`, a written table of what may follow what, and refusals
counted rather than silently applied. It reads no DOM and writes none; a contract test strips
its comments and fails on `document`, `dataset`, `textContent`, `window` or `navigator`
appearing anywhere in the file's body.

`setState()` in `app.js` no longer decides anything — it translates through one table and
paints. Pointer-down, release, final transcript, a question that was never spoken, and a
barge-in are all explicit events.

**Partial speech (invariant 4) is honest but thin.** This tablet records audio and the Mac
transcribes after the release, so there are no interim words to show. `HEARING` is driven by
microphone energy crossing a floor — real evidence that CLIVE is hearing something, and enough
that no interval goes unexplained, but it is not partial text. See the open item below.

### C · Progressive job strip — done

`web/jobs.js` plus the `#job-zone` band. Stable identity, a verb and an object in the owner's
words, `QUEUED → WORKING → DONE | FAILED`, a result summary, and a failure that survives the
turn because a failure nobody has read is not finished. A finished job whose result is on
screen collapses; the strip hides itself when there is nothing worth a surface; `endTurn()`
stops it becoming a dashboard.

Jobs are derived from the one running tool `/state` reports: a tool that was running and is
not any more has finished. That is the whole rule, and it is what makes two reads read as two
jobs completing in the order they really completed.

The table that turns a tool into words covered twelve of the Mac's forty-nine tools, two of
which no longer existed — so on a turn of four reads, three showed as no work at all. Every
shipped tool now has a verb and an object, and whether it changes anything is **copied** from
the Mac's own `ToolSpec.write` rather than judged on the tablet; a test compares both
directions and found five rows wrong on the first attempt. The table is gated against the live
registry, so the next tool added on the Mac cannot land silently mute here.

**No retry is drawn.** `jobs.js` can draw one and is tested doing so; the page does not ask it
to, because the Mac has no endpoint that re-runs a single read. See the open item below.

### D · Layout / liquid glass — partly done

Done: the central Split CTA and its copy are gone; the four service pills left the idle footer
for Diagnostics in the settings sheet (invariant 8), with contextual fault presentation kept on
the connection chip and the notification band; the new band follows the glass rules — one
translucent pane for the group, the same restrained `--blur-surface` the nav and dock already
use, a thin highlight, depth from opacity and border and shadow, nothing moving at rest, and no
blur at all on lite devices.

Not done: no measured pass over idle dead space or competing labels. That wants the device
evidence below, which cannot be taken in this environment.

### E · Acceptance scenario — done as a labelled fixture

`tests/web/acceptance-v05.test.js` drives §E end to end against the two modules the tablet
owns. The contract permits a fixture where live Gmail and the model are gated, on condition it
is labelled; it is labelled in its header, it answers `FIXTURE` to anything that asks, and a
contract test walks every test name in it and fails on one claiming to be live, real, on a
device, or measured.

**Its timings are invented and prove nothing about how fast the Mac is.** Real numbers come
from the `live_marks` the page posts.

### Evidence gates

| Gate | State |
| --- | --- |
| Existing relevant tests green, or intentionally replaced | done — the four that encoded the retired shell were replaced, with the reason in each |
| The suite is stable enough to be evidence | done — a full `-n 4` run is now clean apart from item 5; the intermittent "ERROR at setup" was a real startup race, fixed |
| Deterministic tests: state transitions, interruption, out-of-order completion, one job failing, no Split | done — 27 + 23 + 11 Node tests, run from pytest |
| Browser/device evidence at 390x844 and the tablet target | **not taken** — see open item 4 |
| pointer-down → acknowledgement, release → transcript / first progress / first useful result | measured by the machine and posted as `live_marks`; the allow-list in `app/routes/observe.py` was stripping all five until it was fixed |
| No production deploy | held |
| No connector/credential expansion | held |

## Open items

### 1 · No endpoint re-runs a single read, so no retry is offered

The contract asks for a "failure/retry affordance where safe". Nothing on the Mac re-runs one
failed read: the options are to re-ask the whole question or to add such an endpoint. Drawing a
button that cannot do what it says would be worse than drawing none, so none is drawn and a
test holds that line.

**Needs:** a decision on whether a per-job retry endpoint is wanted in this stream. The client
half is written and tested.

### 2 · Partial speech has no recogniser behind it

Invariant 4 asks for partial speech feedback "where supported". On this tablet nothing supports
it today: the Mac transcribes after the release. Two ways forward — on-device `SpeechRecognition`
for the partial text only (a browser capability question, and a privacy question), or streaming
partials from the Mac's whisper server during the hold (a backend change).

**Needs:** an owner decision on which, if either. The state machine already has `partial()` and
takes a length, so either one is a wiring change rather than a redesign.

### 3 · The Mac-side ops layer is still called CROOKS OS

The tablet is CLIVE end to end now — title, manifest, launcher name, offline page, boot layer.
The Mac's own control layer is not: `scripts/service.py` and `scripts/control.py` say
"CROOKS OS is running", "Open CROOKS OS", and so on, and `tests/test_service.py` and
`tests/test_control.py` assert those exact strings.

That is a naming decision, not an oversight to fix quietly: CLIVE may be the assistant while
CROOKS OS remains the appliance, or the whole thing may be CLIVE.

**Needs:** the owner's answer. Nothing in this stream has touched those files.

### 4 · No browser or device evidence can be taken in this environment

`experience/browser.py` wants Node's `playwright-core` and a Chromium at
`/opt/pw-browsers/chromium-1194/…`. Neither is present here, so the 390x844 and tablet-target
shots the evidence gate asks for have not been taken, and the idle dead-space pass in slice D
that depends on them has not been done.

**Needs:** a run on a machine that has them, or the browsers installed here.

### 5 · The no-terminal contract is red, from before this branch

`tests/test_no_terminal.py` has three failures, and they are **not** from this stream — they
came in with the Phase 6 merge `d073a54b` and were already failing at the branch point
(`93dcd5da`). They are recorded here rather than repaired because each one needs a product
answer this stream is not entitled to give.

- `scripts/control.py`, the actions document: the Restart entry's detail reads "the same
  launchd agents `make restart` kicks…". This one is only phrasing — the test's equivalence
  exemption would accept "the same as `make restart`" — but it sits in another workstream's
  file and is left with its siblings.
- `scripts/update.py`: a detached HEAD or a wrong branch is answered with
  "`git checkout <branch>` first", a missing `.venv` with "Run `make venv` once", and a backend
  that did not come back healthy with "`make logs` shows why".
- `scripts/control.py`, mark-good on a detached HEAD: "`git checkout <branch>` first."

The last one is the real gap, and it is a behaviour gap rather than a copy one: a rollback
leaves the checkout detached on purpose, and from that state the Control app can neither
mark-good nor update — so there is no button to name, whatever the sentence says. Rewording it
without adding one would only hide that.

**Needs:** a decision on what the owner does after a rollback — a "come forward" action in
CROOKS Control, or an explicit "this needs someone else" register for the few states the app
cannot repair.

## How to check this branch

From `crooks-assistant/`, with the builder's venv:

    .venv/bin/ruff check app config scripts tests          # clean
    .venv/bin/pytest tests -m "not live" -q -n 4           # 2979 passed, 8 skipped, 3 failed
    node --test tests/web/live-state.test.js               # 27
    node --test tests/web/jobs.test.js                     # 25
    node --test tests/web/acceptance-v05.test.js           # 11

The three `test_no_terminal` failures are the only red, and they are red at the branch point
too (item 5).

`tests/test_branches.py`, `tests/test_experience.py` and an arbitrary one test per run used to
fail or ERROR under `-n 4`. That was one bug, not flakiness: `app/capabilities/delta.py` wrote
every capability record through one shared `capabilities.tmp`, so two starts against the same
log directory raced and the loser's `os.replace` raised FileNotFoundError out of the lifespan.
Each writer now names its own scratch file, and the run above is clean.
