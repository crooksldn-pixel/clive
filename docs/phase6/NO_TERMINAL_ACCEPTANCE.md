# NO-TERMINAL ACCEPTANCE

**Status: PARTIALLY AUTOMATED, PHYSICALLY NOT RUN.**

The automated half is `crooks-assistant/tests/test_no_terminal.py` and it runs here. The
physical half needs a Mac and cannot be run here. Both halves are described below, because
neither alone answers the question.

## The question

Not "is there a button for everything". The question is:

> Could a man who has never seen this repository, and does not know Terminal exists, run CROOKS
> OS day to day?

That is §37, and it is answered by *the sentences the product says when something goes wrong* —
not by the buttons it shows when everything is fine. Anyone can build a control panel that
works on a good day.

## The automated half — what a machine can check

`tests/test_no_terminal.py` builds the control layer's real documents and reads every string in
them, then extracts every refusal message out of the source and reads those too. It fails if
any sentence leaves a shell as the owner's only remedy.

It measures two things and is explicit about which is which:

* **Behavioural.** The `actions` and `contract` documents, and the `status` document on its RED
  path — built for real, string by string. These are the literal bytes the Control app renders.
  The RED path matters most: it is the only sentence the owner reads *while something is
  wrong*.
* **Static.** Every `Stopped(...)` literal, pulled out of the AST. Reaching these behaviourally
  would need a git repository in seven different broken states. A test that cannot reach them
  would report success while they sat there — which is the §26 failure this phase exists to
  avoid — so they are read from the source, and the module says so rather than implying more
  coverage than it has.

Two exemptions, each narrow, each with its own test in both directions: a sentence that offers
a control *as well as* a command is fine, and an equivalence note ("the same as `make
restart`") documents a button rather than substituting for one. The exemptions are keyed on
the language of offering and equivalence, **never on the file or the field** — an exemption by
location would swallow the next real defect written in the same place.

**What it cannot check.** It reads the control layer's own strings. It cannot read a sentence
that only exists in a SwiftUI view, because no Swift view on this machine can be built or run
(no macOS SDK). If CROOKS Control itself contains a hardcoded sentence telling the owner to
open Terminal, **this test will not find it.** Someone with a Mac must look.

## The physical half — what only a person can check

Work through this list on the Mac, using **only CROOKS Control**. The rule is absolute: if you
open Terminal for any reason, stop and write down what made you.

| # | the owner needs to… | pass condition |
|---|---|---|
| 1 | see whether CROOKS OS is running | one word on the front page, without scrolling |
| 2 | **start** CROOKS OS when it is off | a button, and the word changes to ONLINE by itself |
| 3 | **stop** CROOKS OS | a button, and the word changes to OFFLINE |
| 4 | **stop it and start it again** | *see the note below — this is the one that breaks* |
| 5 | restart it when it is behaving oddly | a button |
| 6 | update to the latest version | a button, with what it will do shown first |
| 7 | undo an update that went wrong | a button, without being asked for a commit id |
| 8 | run the tests | a button, with a result he can read |
| 9 | see why something is broken | a button; the answer must not be a stack trace |
| 10 | see whether the tablet is alive | a row that says CONNECTED / DISCONNECTED with a time |
| 11 | see whether Shopify and Gmail are connected | rows — **and no credential anywhere on screen** |
| 12 | make it all start when the Mac starts | a button, once, never a command |

**Step 4 is the one to be careful about.** Stop, then start, is the most ordinary sequence an
owner ever performs and it was broken in this phase's first build: the code decided "already
running" from whether a file existed on disk rather than from whether launchd had the job
loaded, and the file is still there after a stop. It was invisible because the test's stand-in
for launchd returned success unconditionally — a double that always succeeds measures the
double, not the product. **Perform step 4 three times in a row.**

For each row, write down: *did I press a button, or did I know what to do because I built it?*
That second one is the failure mode this whole phase is about.

## The failure that does not look like a failure

The dangerous outcome is not a missing button. It is a button that is **there and grey**, or a
sentence that is **true but useless**:

* "CROOKS OS is not running." — true, useless. What do I press?
* "The backend did not come back healthy within 90 seconds." — true, and then what?
* A STARTING that never becomes anything.

Read every sentence the panel shows you and ask: *if I knew nothing, what would I do next?* If
the answer is "ask someone", that sentence is a defect, and it is worth more than another
feature.

## Known gap at the time of writing

The automated gate is committed **red**. It names eight strings — six in `scripts/update.py`,
two in `scripts/control.py` — that send the owner to a shell. The workstream review had found
one of them. They are fixed as part of integration; until the gate is green, **this acceptance
document's answer to §37 is NO**, and the report must say so rather than pointing at the
buttons that do work.
