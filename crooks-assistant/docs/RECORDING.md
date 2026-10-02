# CLIVE recording what it does, and looking at it

George, 2 October 2026: *"Clive needs to actually look at how it responds to my queries … so it can
be used as part of building itself better."* And: *"I just need to say 'look at our interaction and
see how that happened'."*

## What is recorded

The **interaction record** (`app/observability/interactions.py`) runs whenever the service runs. It is
not a test session and is never reported as one: `/health` says `recording`, and
`/test-session/status` says `active: false` with the record beside it, so "is a test running?" has a
true answer.

For every turn and gesture it keeps:

- what was asked, typed or heard, and what the recogniser heard against what the turn used;
- which tools ran, how long each took, and which failed;
- what was drawn: each card's type, which tool drew it, its rows, its controls (on or off), its
  order numbers, and whether it was new, kept or read again;
- **why the screen is what it is**: the rule of `app/screen.py` that decided (nothing was up, a new
  subject, a change to another record, an order he named that was not up, the screen carried on),
  the change a card waits on, the reads used only for words, and, when a record's workspace was
  composed, which of its sections the words named (`app/workspace.py desired`);
- what the tablet itself reported drawing, what he tapped and held, what was refused, and how long
  each step took (the page's own account, `web/telemetry.js`, sent whenever the record is on).

## Switches, bounds and privacy

| Setting | Default | |
|---|---|---|
| `CROOKS_INTERACTION_RECORD` | `true` | `false` turns it off. |
| `CROOKS_INTERACTION_RECORD_KEEP_DAYS` | `7` | A day older than this is deleted when the next day starts. |
| `CROOKS_INTERACTION_RECORD_DAY_MB` | `16` | A day's file stops growing here (one line says so). |
| `CROOKS_INTERACTION_RECORD_WORDS` | `false` | `true` keeps his words and the cards' titles as said. |

On the production host it is on after the next deploy with no `.env` change. To turn it off, add
`CROOKS_INTERACTION_RECORD=false` to `/opt/crooks-os/crooks-assistant/.env` (the service reads that
file itself) and restart the service. `make test-session-status` says whether it is on, apart from
any test.

So the folder holds at most eight days of sixteen MB each. It is `logs/interactions/`, one JSONL a
day, files `0600` in a `0700` folder, on the server only.

Every line passes the timeline's own redaction, the same code a test session uses: credentials,
email addresses, card numbers, postcodes and phone numbers by shape, and every customer name this
process has been shown. The owner's own words and the cards' titles are written by their shape (a
length and a digest), exactly as the day's automatic test session writes them, because a name he
says that no read returned cannot be found and taken out. `CROOKS_INTERACTION_RECORD_WORDS=true` keeps
them, still scrubbed; that is his decision.

While the process lives, the last turns of each conversation are also held **in memory** with their
words (what was asked and heard, the cards' titles and lines), so "why did you show me that" can be
answered in his words. Never written down; gone at a restart.

## Asking CLIVE

"What's on my screen?", "why aren't you showing me bulk actions?", "look at our interaction": CLIVE
calls `interaction_review` (`app/tools/interaction_tools.py`), a read of its own records, and answers
from it:

- `on_screen`: each half's screen as the Mac drew it (`Branch.last_ui`), word for word: titles, the
  rows' lines, each workspace section's facts, the controls and why one is off;
- `turns`: the recent turns, what drew each card and why each screen was chosen;
- `tablet_last_drew`: what the tablet itself last reported drawing, overlaps included;
- `friction`: what fought him, found mechanically (`app/observability/friction.py`), each with
  the easier way:
  - `REPEATED_TAP`: the same control tapped again and again inside seconds. A row action tapped
    over and over names the bulk tool that does the same change in one hold.
  - `SCREEN_CHANGED_UNASKED`: the cards were replaced with no tap and no question in flight.
  - `ACTION_FAILED`: a tap, hold or tool refused, failed or unanswered; retried, or then gone through.
  - `SPELLED_OUT`: a name spelled letter by letter, a correction, or the same thing said again.
  - `LONG_WAIT`: a turn over eight seconds, a read over six, a tap over four, with where the time went.
  - `UNRELATED_SCENE`: a request answered with the wrong scene ("who needs a reply" shown a plain
    inbox), a close that left the screen up, an order named and another drawn.
  - `MISSING_CAPABILITY`: a bulk change asked for and no bulk card, or CLIVE saying it could not.
- `about`: for "why aren't you showing me X": whether X is on the screen now, which tools do it and
  what card each draws, and whether any turn called one;
- `excerpt`: the same window with nothing anyone said and no names, for a build request.

When he agrees it should be fixed, CLIVE files it the way it files any build of itself
(`engineering_status`, then `submit_engineering_request` with the excerpt in `requested_outcome`).
Nothing is filed until he holds the card.

## Spelling names: measured, and what would fix it

The record counts, on every turn, the names spelled out letter by letter, the letters, the
corrections ("no, I said…") and the sentences said again (`speech` in `interaction_review`). A week of
use says how often it happens and in which turns.

Not built tonight, on purpose: passing the names in play to Scribe as `keyterms`. It would send
customer names from the shop to ElevenLabs, which is data leaving the server, and the owner removed
`keyterms` on 28 September because biasing the recogniser made it mishear ("Clive" heard as "Plaid").

What would fix it without either:

1. **Find a heard name by how it sounds.** When a customer search by a spoken name finds nobody, or
   several, match the heard words against the names already in play: this order's customer, the
   customers read in this conversation, and the order cache. Use a phonetic key, such as Double
   Metaphone, written in plain Python with no dependency. Offer the candidates as a list to tap.
   This is in the customers lane (`shopify_find_customer`, `app/reads`).
2. **Join a spelled name before searching.** "Z O E, Q U I L L" becomes the letters ZOE and QUILL and is
   matched against the same names, letters only. `friction.spelled` already finds the runs.
3. **Only if he chooses it:** `keyterms` limited to the names in play, per request, off by default,
   accepting that those names go to ElevenLabs.

Nothing needs installing for any of this.
