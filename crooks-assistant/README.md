# CROOKS Assistant

A voice assistant for CROOKS LDN. You hold a button on a tablet, ask a question out loud, and it
answers out loud — reading from the Shopify store and the email inbox, and proposing changes
you apply with a gesture on the tablet. It never writes on its own.

Everything runs on your own Mac except the two services it talks to: Claude, on the Max
subscription you already pay for, and ElevenLabs, which hears and speaks on credit. No
database, no server anywhere else. Claude is reached through the Agent SDK on the Claude Max subscription;
speech-to-text is ElevenLabs Scribe v2, with whisper.cpp on this Mac as the automatic fallback
whenever ElevenLabs cannot answer; the answer is spoken back by Derek, an ElevenLabs voice
generated on this Mac, with the tablet's own Android voice as that fallback.

Built to the fifteen-milestone plan in *CROOKS Assistant Build Plan* (Rev 3, 7 Sept 2026).

## Start here

Every day:

```bash
cd ~/crooks-assistant/crooks-assistant
make up          # everything the tablet needs, in this window; prints the address to open
```

Or `make install` once, and the Mac starts it at login with no window at all (`make status`
tells you how it is doing).

### Or no Terminal at all: CROOKS Control

```bash
make control-app     # builds the menu-bar app and puts it in /Applications (macOS 13 or later)
```

The menu bar then reads `CROOKS — Online` in one of four colours — green live, blue
recording, amber read-only or degraded, red something to look at — and under it are the rows
(`crooks-status`, in a list) and the buttons: open CROOKS OS, restart, check for update,
update, run tests, run UI tests, start and stop a recording, generate and open a report, open
the logs, open the folder. The update shows both build ids and waits for a click, and only
offers itself when it would be a fast-forward onto a clean tree.

Record the build that is working before the first update, so the app has somewhere to go back
to: `crooks-control mark-good`. See `mac/CrooksControl/README.md`.

### Three words, from anywhere

Run `make commands` once and these work from any folder, in any Terminal:

```bash
crooks-status    # one screen: build, voice, Claude, Shopify, Gmail, orders, the tablet's address
crooks-update    # pull, install what changed, restart, verify — and stop rather than lose work
crooks-watch     # what it is doing right now, one line per thing
crooks-control   # the same answers as JSON, which is what the Mac app reads
```

`crooks-update` fast-forwards only. It will not merge, rebase, reset or force anything; if the
tree is dirty or the branch has commits the remote does not, it says so, changes nothing, and
tells you what to do. It never touches `.env`, `logs/` or any credential. Nothing inside
CROOKS OS runs it — it updates when you type it, and not otherwise.

The first time on a new Mac, before either of those: `make doctor`, then `make venv`, then
`make secrets`, then the console steps under *Setup on the Mac*. `make help` lists every command.

---

## Setup on the Mac

Every step is the same shape: open Terminal, `cd ~/crooks-assistant/crooks-assistant`, type
one line. You never run a Python file directly; `make` does it. `make help` prints this list.

| Step | You type | Then |
|---|---|---|
| Check the Mac | `make doctor` | Install whatever it names, the way it says |
| Install | `make venv` then `make test` | Expect every test to pass |
| Run it | `make up` | One window: backend, speech and the HTTPS route. Prints the address |
| Or forget about it | `make install` | Once. The Mac starts everything at login; `make status` to check |
| Speech | `make whisper-server` | Only to build it: prints the build steps the first time |
| Keys | `make secrets` | Asks for the Shopify Client ID and secret and the ElevenLabs key, one at a time, hidden |
| Prove Shopify | `make shopify` | Shop name, `Europe/London`, one recent order, cache reused |
| Gmail | `make gmail` | A browser opens once. Then `make gmail-verify` |
| Everything at once | `make check` | Doctor, Shopify, Gmail in one go |
| Ask questions | `make chat` | Typed, so it does not use the tablet or much allowance |
| Day 1 test | `make acceptance SPOKEN=1` | From the tablet, at your working distance |
| Three words on the PATH | `make commands` | `crooks-status`, `crooks-update`, `crooks-watch`, `crooks-control` from any folder |
| The menu bar instead | `make control-app` | Builds CROOKS Control into /Applications; then `crooks-control mark-good` once |
| Prove it here | `make accept` | Lint, Node, the offline suite, a server of its own, latency medians, page sizes, and the page in a real Chromium (when Playwright is installed). No store, no inbox, no credit |

The console work (Tailscale, Shopify Dev Dashboard, Google Cloud) is the only part that is
not a `make` line, and it is described step by step below.

Then, in order:

1. **Tailscale** — install on Mac and tablet, same account. Admin console → DNS → enable
   MagicDNS, then HTTPS. Rename the Mac to something unrevealing: the hostname lands in public
   Certificate Transparency logs. `make up` sets the route itself (`tailscale serve --bg
   8000`, which persists) and prints the `https://<machine>.<tailnet>.ts.net/` address; open
   it on the tablet and add it to the home screen.
   *It must be that address, not the LAN IP* — the microphone and speech APIs both require a
   trusted secure context, and the LAN IP is not one.

2. **whisper.cpp** — the fallback recogniser, and still required: it is what answers when
   ElevenLabs cannot. `make whisper-server` prints the exact build commands if it is not built
   yet. On the M4 Max the working configuration is `large-v3-turbo` on a build made with
   `-DWHISPER_COREML=OFF` (Metal only): the Core ML path crashed on models without a matching
   encoder, and Metal alone is fast enough. Settings live in a `.env` file next to this
   README: `cp .env.example .env` once, then put `CROOKS_WHISPER_MODEL=large-v3-turbo` in it
   so plain `make whisper-server` starts the right model. A Silero VAD model must be present;
   the launcher refuses to start without one, because a server without it rejects every
   request that asks for voice detection while the tablet still says "connected".

3. **ElevenLabs** — `make secrets` and paste the API key at the hidden prompt (a key scoped to
   speech-to-text is enough; `/health` says "quota unreadable (restricted key)" for one of
   those, which is not a fault). Nothing else is needed: Scribe becomes the recogniser and
   whisper.cpp becomes the fallback. Without a key the assistant listens entirely locally, as
   it did before — set `CROOKS_STT_PRIMARY=whisper` to choose that on purpose.

4. **Claude** — run `claude` and sign in with `/login` if you have not. That login is
   what the assistant uses (`auth=cli`); no token needs storing. If a turn ever says the
   login is not working, run `claude` and `/login` again.

5. **Shopify** — `make secrets` for the Client ID and secret, then `make shopify` to prove
   it. It either works or names `shop_not_permitted`, which means the app and the store are
   in different Shopify organisations; the fix for that is the `shpat_` fallback described
   in `SHOPIFY_SCOPES.md`, which also lists the scopes.

6. **Gmail** — Google Cloud project → enable the Gmail API → Branding → Audience: External
   → Data Access: `gmail.modify` (read mail, change labels) and `gmail.compose` (drafts, and
   sending) → **Publish app** → Clients → Desktop app → save the JSON as `credentials.json`
   in this folder. Then `make gmail`. `make gmail-verify` prints what Google says the stored
   token may do — read, draft, send, labels — and `/health` says the same, per change. The
   assistant never asks you to re-authorise unless Google itself has refused the token.
   **Skip "Publish app" and your token dies every seven days.**

7. **Content** — `kb/terminology.md` already holds the live catalogue with spoken aliases for
   the stylised names; correct the aliases to how you actually say them (five minutes). The
   policy and sizing files are written from the store's own published content; the one thing
   only you can write is the discretion section of `kb/cs-rules.md`.

8. **Fallback voice** — Derek needs no choosing. In the tablet's settings sheet, pick the
   Android voice that stands in when ElevenLabs cannot answer. If none show "offline",
   install the en-GB voice data: Settings → General management → Text-to-speech → Install
   voice data.

   A `.env` line wins over the default: a `CROOKS_TTS_VOICE_ID` copied from an older
   `.env.example` keeps that older voice speaking while the health page says "Derek". The
   health page now asks ElevenLabs what it calls the configured id, once an hour, and says
   so when they disagree; `make voice` prints the same. `grep TTS .env` and delete or
   correct the lines, then `make restart`.

9. **Run at login** — `make install`. It fills in the templates in `launchd/`, loads
   them, sets the Tailscale route and reads `/health` back. `make status`, `make restart`,
   `make uninstall` from then on.

---

## Running it day to day

One line, one window:

```bash
cd ~/crooks-assistant/crooks-assistant && make up
```

That starts the backend and whisper-server as children of one process, prefixes their output
so the window stays readable, makes sure Tailscale is serving port 8000 over HTTPS (set once,
in the background, where it survives restarts), waits for `/health` and prints the address to
open on the tablet. Ctrl-C stops everything; a service that dies is restarted with a short
back-off. If whisper.cpp is not built, `make up` says so and runs without the fallback
recogniser rather than refusing to start.

Or no window at all:

```bash
make install     # once: the Mac starts both services at login, and now
make status      # running? what /health says, the tablet's address
make restart     # after a git pull
make uninstall   # stop and remove
make logs        # follow their output
```

These are launchd agents in your login session, so the claude CLI's own login and the Keychain
work as they do in a Terminal. The Mac must be logged in; stop it sleeping in System Settings
→ Energy rather than leaving a Terminal open.

Then open the ts.net address on the tablet and add it to the home screen: it opens
full-screen, portrait, as its own app. Hold the orb, speak, release. If a question is taking
too long, hold again: after a second the tablet abandons it, tells the Mac to stop thinking
about it, and listens for the next one. The page reloads itself, when idle, whenever the Mac
starts serving a newer build. The microphone
stays open while the page is showing, so the first word is not lost to start-up; it is
released when the page is hidden and reopened when it returns.

## Proving it on the Mac and the tablet

What Linux could not verify, in the order to try it. Ten minutes.

1. `make test` — every test passes on the Mac too.
2. `make up`, then Ctrl-C, then `make up` again — the second run prints the address while
   the first is still down; with `make install` in place it says the running copy is
   answering and prints the address anyway.
3. `make voice` — Derek speaks on the Mac. One ElevenLabs request.
4. On the tablet, Settings → "Show timings" on → Preview voice. The voice should start within
   about a second. `logs/assistant.log` shows `tts ok`; `/health`'s `voice` block counts
   "answers ready before asked" once you have asked a real question.
5. Ask "how many orders today?" — the transcript appears under the orb while the orb is
   thinking, before the answer.
6. Ask something slow (a sales summary over a month), and hold the orb through "keep holding
   to ask something else" — the question is dropped, the orb listens, the Mac's log shows
   the interrupt.
7. Hold the orb while Derek is mid-sentence — he stops at once and the orb listens.
8. Turn the screen off for a minute, turn it on, ask again — the first word is not clipped
   and the answer is heard, not silent. If it is silent once, the next answer is in the
   Android voice and the log says `audio context suspended`: that is the guard working;
   tell me, because it means the tablet needs the whole-file path by default.
9. `touch web/app.js`, restart the backend — the tablet reloads itself when idle.
10. In Chrome's menu, "Install app" (older Chrome: "Add to Home screen") — a CROOKS OS icon
    lands on the home screen and opens full-screen, portrait, straight into the assistant. Put
    the Mac to sleep: the app shows SYSTEM OFFLINE and waits; wake it: the app comes back on
    its own.
11. Ask "how were sales each day this week" — the log shows one `shopify_sales_summary`
    call, not seven, and the card lists a row per day.

## Working on it

```bash
make dev          # backend alone, with auto-reload (stop the launchd agent first: make uninstall)
make chat         # terminal REPL — use this, not voice, for repeat testing
make test         # every test, all offline; the two live API ones skip without credentials
make lint
make bench        # M3 model comparison, on tablet audio
make acceptance   # M14, 18 commands
```

**The acceptance script has not been run against real Claude.** It could have been — the store
was readable and the CLI was logged in — but eighteen live turns come out of your Max allowance
and nobody had authorised that spend. It is a five-minute decision that is yours: once M6 is
done, `make acceptance` in typed mode fills the placeholders from the store, costs
about eighteen turns, and turns "the gate holds" into an answer-accuracy score with the
questions it fumbled listed.

**Test through `make chat`, not through the tablet.** The build and the assistant draw from the
same Max allowance, and a long day of voice testing can exhaust the weekly window. Tool logic is
testable directly in Python without spending anything.

### An hour with the tablet, written down

A test session records everything the Mac and the tablet do into one timeline, and a report
is read back from it. Nothing restarts: the backend notices a session within a second, and
the page joins it at its next health poll or its next answer.

```bash
make test-session-start NAME="first hour"   # prints the session id (ts-…)
make test-session-status                    # what is running, events so far
make test-session-stop
make test-session-report                    # writes reports/<session>.md; SESSION=ts-… for an older one
make test-session-proposals                 # writes reports/<session>-proposals.md: improvement candidates, never applied
```

The timeline is `logs/test-sessions/<session>.jsonl`, one JSON line per event, each with the
time, a sequence number, the test session, its source (`mac` or `tablet`) and the ids that
join it to the rest: `session_id`, `turn_id`, `tool_call_id`, `proposal_id`,
`context_request_id`. The Mac writes what it heard (as the recogniser returned it, which
recogniser, how long), what Claude answered and how long it took, every tool it asked for and what came
back (shape and timing, never content), every proposal's life on the action engine, every
context read, every voice line's first byte. The tablet writes what it actually showed —
screen, card types, sections, rail chips and whether they were enabled, viewport and scroll
sizes, clipping — and what the owner did: navigation, tabs, holds, taps on cards, failed
images, failed context requests, exceptions, going offline and back. Structure, never the
words on the cards; batched every two seconds, never waited for.

The report (`reports/<session>.md`) stands on its own: a summary; latency averages, medians
and P95s by stage with the ten slowest turns; the requests clustered; tool usage; every
failed or partial turn with what was said, answered, attempted and shown, filed under a
named class; the capabilities asked for that do not exist, counted; what the screens showed
and what was used; every proposal's staging, gesture, commit and proof; the gaps in context;
deterministic response-quality signals; the attention surfaces; a ranked list of what to
fix next, each with its evidence; and an intelligence section — false unsupported claims
(the assistant said it could not, and the read layer or a batch tool could have), composable
requests that failed, the multi-tool workflows and follow-up shapes the session repeated,
query dimensions, actions, bulk actions and card types asked for that do not exist yet —
every line citing its turn ids. `make test-session-proposals` writes those as IMPROVEMENT
CANDIDATES for a person to pick up; nothing applies them (see `docs/ENGINEERING_LOOP.md`). Both files hold what the owner said about customers: they
are created 0600 and are never committed (`logs/` and `reports/` are ignored).

Never in either: a token, a key, an Authorization header, a cookie, a request's headers.
Keys that name one are withheld and strings shaped like one are scrubbed before a line is
written, whoever wrote it.

---

## Changes to the store and the inbox

The assistant can propose nine changes. Each is off by default, and each follows the one
pattern rather than being a feature of its own:

    Claude calls a narrow tool → the gate stages it → the Mac reads the entity and decides
    every argument → a card appears on the tablet with the facts the gesture authorises →
    you make the gesture → the Mac checks the entity has not changed, sends the one reviewed
    mutation once, reads the entity again to prove it → the card says what happened, Derek
    says it, and where there is an undo, an undo waits.

| Change | Tier | Gesture | Proven by |
|---|---|---|---|
| Order note | AMBER, undo | tap | the note re-read |
| Tags | AMBER, undo | tap | the tags re-read |
| Cancel (with refund, restock, email per policy) | RED money | hold, then drag onto "Drop to cancel and refund £X" | `cancelledAt` set after Shopify's job finishes |
| Refund (an amount, the items, the postage — priced by Shopify) | RED money | hold, then drag onto "Drop to refund £X" | `totalRefunded` moved by exactly the amount |
| Address (the customer's email read on the Mac; the postcode and street must be in it) | RED | hold, then tap | the address re-read and hashed |
| Fulfil (from the order's own fulfilment orders; carrier as Shopify spells it) | RED | hold, then tap | the remaining quantities dropped to what was expected |
| Stock (one variant, one location, ±100, compare-and-swap) | RED, undo | hold, then tap | the level re-read |
| Email: draft a reply / a new email | AMBER, undo | tap | the draft found in the thread by the Message-ID minted here |
| Email: send a reply / a new email | RED | hold, then tap | the sent message found the same way |
| Archive a thread | AMBER, undo | tap | the INBOX label gone |

Say the order number and the Mac looks the order up before Claude is asked — items with
images, money, address, the customer's history and their email, and what the order needs
(unshipped for days, oversold, cancelled but not refunded, an email from the customer read
for what it is about). The card's rail offers only the changes that make sense for that
order and that the store has granted this Mac. Say "yes" or "go ahead" while a card is
waiting and the Mac answers, without Claude, that nothing happens until the gesture; the
card stays. If a gesture from where you are would be refused, the card says so first.

What holds it together, and what the tests hold:

- **The tool call is the proposal.** Calling the tool changes nothing. Claude is told
  PROPOSED and which gesture applies it. A spoken "yes" cannot.
- **The Mac's copy is the action.** The tablet sends a proposal id, the session and — for a
  hold — the nonce the hold earned. The arguments come from what the Mac stored when it
  staged the proposal; a refund amount, an address, an email body never travel with a tap.
- **The recipient is never the model's.** A reply goes to the sender of the message it
  answers; a new email to the customer on the order; an address change to the order whose
  customer wrote the email — all read on the Mac.
- **Once.** Two taps, a retry, a double request: one mutation. A lost answer asks the
  entity what happened rather than sending again.
- **Bound to now.** A proposal waits a minute and dies with the next instruction, a cancel
  or a reset. The entity is re-read before the write; if it changed, nothing is sent. A
  stock change is held to the old number by Shopify itself.
- **Proven.** A 200 is not success; the re-read is. What could not be proven is said as
  "check the order", never as done.
- **Recorded.** `logs/actions.jsonl` is an append-only ledger of every proposal and outcome:
  identities, hashes, amounts and flags — never a note, a name or a street.
- **Email is evidence.** What a customer wrote is quoted on the card with who sent it and
  whether the receiving server vouched for them; it never becomes an instruction, and
  nothing is ever sent because an email asked.

To switch it on, in `.env`:

```
CROOKS_WRITES_ENABLED=true
CROOKS_ALLOWED_LOGINS=you@example.com     # open /whoami on the tablet to see the exact login
```

and grant the Shopify app the scope each change needs (`SHOPIFY_SCOPES.md`); the Gmail
changes take their scopes from the Gmail credential itself. The settings sheet's "Changes"
row and `/health` say, per change, what is ready and what is still waiting on a scope.

## How it is put together

```
tablet (Chrome)  ──HTTPS via tailscale serve──▶  FastAPI on 127.0.0.1:8000
                                                  │
                    ┌─────────────────────────────┼────────────────────┐
                    ▼                             ▼                    ▼
        ElevenLabs Scribe v2             Claude Agent SDK        knowledge base
       ↳ whisper.cpp fallback            (Max subscription)         (system prompt)
          (local, port 8910)
        ElevenLabs TTS (Derek)
       ↳ Android voice fallback
                                                  │
                                        in-process MCP server
                                                  │
                                          ┌───────┴───────┐
                                          ▼               ▼
                                    Shopify Admin      Gmail API
                                  (reads; reviewed    (modify, compose;
                                   writes, staged)     writes staged)
```

`app/tools/gate.py` is the security architecture. Every tool call passes through it, including
auto-approved ones — that is why the gating lives in a `PreToolUse` hook rather than in
`can_use_tool`, which auto-approved tools never reach. Three rules make it fail closed:

- an unregistered tool is RED, so adding a tool without adding a rule grants nothing;
- any tool whose *name* reads as a mutation is RED before the rule table is consulted;
- detail tools accept only ids issued by a search earlier in the same session.

`tests/test_gate.py` proves a RED tool's handler never executes, via a module-level counter. If
that test ever fails, stop and fix it before anything else.

### Hearing you

Two recognisers, one job. Every recording is decoded and level-checked here first — silence and
distortion never reach a paid API — then sent to **ElevenLabs Scribe v2**, audio and nothing
else. Nothing tells either recogniser which words to expect: a term list drawn from the Shopify
catalogue used to, and it made "Clive" come back as "Plaid", so it was removed on 28 September
2026.

Every way Scribe can fail — no key, a rejected key, no credit, a timeout, no network, a reply
that is not a transcript — falls through to **whisper.cpp** on port 8910 and the speaker is
never told. What comes back from either engine goes through the same hallucination blocklist
and is trimmed, never rewritten: the words reach Claude exactly as they were heard, and every
sentence is Claude's to answer. A rejected
key or an exhausted account also opens a five-minute cooldown, so a broken account costs one
round trip rather than one per sentence.

Before any of that, the recording has to be worth transcribing: at least 0.3 s long, above the
noise floor, and not distorted. Distortion is measured as the *proportion* of samples sitting on
the rail, never the single highest one — a plosive or a knock on the desk reaches full scale in a
recording that is perfectly intelligible, and gating on the peak refused a third of everything
the tablet ever recorded. `clipped_ratio` and `clipped_ms` are in the stats and on the
`/audio-test` page, so a rejection can be argued with rather than guessed at.

Correction is deliberately conservative, because a wrong correction turns a transcript the
recogniser got right into a wrong answer. Ordinary English is never corrected towards a
catalogue term — the live catalogue contributes the store's colour options as one-word terms,
and "what" is one character-pair away from "White", "back" from "Black", "and" from "Sand". A
short one-word term needs near-exact evidence; an equal phonetic code corroborates a match but
can never invent one; and a match may not swallow an ordinary word at its edge. Anything below
that bar keeps the words as spoken.

Which engine actually answered is in the turn log and in the console (`recognised via scribe_v2
in 1413ms`), and `/health` carries a `speech` block naming the primary, the effective recogniser
and how many Scribe attempts have succeeded. Scribe being down is `degraded`, never dead: the
Mac still hears you. `CROOKS_STT_PRIMARY=whisper` turns Scribe off entirely.

### Answering you

The answer text is on the tablet's screen the moment the agent finishes. Only then does the
tablet post it to `/speak`, which is a separate request for exactly that reason: making `/turn`
wait for an MP3 would delay the thing that matters for the sake of the thing that does not.

`/speak` sends the text to **ElevenLabs** — voice *Derek*, model `eleven_flash_v2_5`, format
`mp3_44100_128` — and forwards the MP3 to the tablet as it arrives, so the audio is not copied
into memory on the Mac before it starts moving. The tablet plays it through one `<audio>`
element that lives for the life of the page. The ElevenLabs key never leaves this Mac: the
tablet sends text and receives audio, and `tests/test_web.py` reads every file in `web/` to
prove no credential, key header or ElevenLabs URL is served to the browser.

Before the text is sent it passes through `app/speech/speakable.py`, which is deliberately
small. The system prompt already asks Claude for spoken-shaped answers; this is the safety net
for the two things a synthesiser reliably gets wrong here — `£430.50` becomes "four hundred and
thirty pounds fifty", `order #1930` becomes "order nineteen thirty" — plus the removal of
markdown, links and HTML. It never rewrites what the answer says.

Every way ElevenLabs can fail is a 503 with a short reason, and the tablet reads that as "use
your own voice", not as "say nothing": a bad key, no credit, a timeout, an empty body, or a
player that will not play all end in Android's speechSynthesis with the reason in the console.
A rejected key or an exhausted account opens the same five-minute cooldown Scribe uses. A
broken voice never breaks a turn — Shopify, Gmail and Claude do not depend on it.

Two things shorten the wait before the voice starts. `/turn` is told by the tablet whether it
will ask `/speak` for this answer (`speak=1`), and when it will, the backend starts synthesising
the moment it knows the answer, so the MP3 is generating while the JSON crosses the tailnet;
`/speak` then serves it whole (`X-Crooks-Prefetched: 1`) — the same single request, a round
trip earlier, never an extra one. And the tablet plays the MP3 as it streams, through Media
Source Extensions, so the first sentence is heard while the last is still being generated;
anything that goes wrong mid-stream replays the bytes already received, then falls back to
Android. Every external client keeps one HTTPS connection open between calls — ElevenLabs
twice, Shopify, whisper-server — so no sentence pays a TLS handshake, and an email search
fetches its messages in one batched Google request rather than one request each.

Fixed lines — "I did not catch that", the usage-limit notice — are synthesised once and
kept for the life of the process, so the moments the owner is already irritated cost nothing
and start at once. A prefetch that fails is remembered, so `/speak` reports it immediately
rather than sitting through the same timeout twice, and abandoning a question (below) stops
any synthesis nobody will hear. `CROOKS_TTS_PREFETCH=false` turns the prefetch off; the
settings sheet's "Start speaking before the whole answer has arrived" turns streaming off;
either way the older whole-file path is what runs.

Gmail is the one client that is not async: googleapiclient runs in worker threads, and its
HTTP layer must not be shared between them — the health check and a search on one connection
once took the whole backend down with a `malloc: double free`. Each thread now builds its own
service around the one refreshed credential. The Gmail tools also carry a ceiling of their
own (fifteen seconds; a search is a listing, a batched fetch and, cold, a token refresh)
where every other tool keeps the eight-second default.

The log is for reading: a line per question, tool call and fault. The tablet's polls of
`/state` and `/health`, the static files and the Mac's own outbound requests are not logged
unless they fail.

Holding the orb stops Derek before the recorder starts, so the assistant can never be
recorded answering itself, and a new answer cancels the previous one's request and playback.
`/health` carries a `voice` block and a `tts` check naming the voice, the model and the last
request's latency and size; it is a key and configuration check only, because a health page
that synthesises a sentence every fifteen seconds is a bill rather than a check.

### Showing you

The tablet is one dark surface with the orb at its centre: hold anywhere on it to speak, and
the cards for what you asked about appear beneath as the answer is read out. What appears is
never decided from the prose. `/turn` carries a `ui` list — `[{type, data}, …]` — built by
`app/presentation.py` from the tool results of that turn: an `order`, an `order_list`, a
`customer`, `customer_list`, `product`, `inventory`, `sales_summary`, `email_list`,
`email_thread`, an `error` per failed service, and a `context_stack` once the conversation has
touched more than one thing. Every item is whitelisted key by key and bounded (ten orders, six
messages, two thousand characters of email body); a field reaches the screen only when a line
in that module carries it. `email_draft` is produced after a proven email change — a draft
saved in Gmail, a reply sent — and says which. `attention` exists in the vocabulary and the
renderer, with fixtures, and is produced by the attention scan. `confirmation` and `success`
are produced by the action engine (see "Changes to the store" above): a staged proposal, and
a change that was verified.

`web/ui.js` renders exactly those types and nothing else, through `textContent` and safe DOM
construction — a customer's name arriving as `<img onerror>` is shown as that text. Claude
cannot ask for a component, supply markup, or put a value on screen that a tool did not
return. `tests/test_presentation.py` holds the contract on the Mac side; `tests/web/ui.test.js`
(run by `tests/test_web_js.py` under Node, skipped without it) holds it in the renderer.

The orb is a 2D canvas (`web/orb.js`), drawn once at full size and scaled by CSS when it
recedes for cards. It reacts to the real audio: one `AudioContext` (`web/audio-viz.js`),
created on the first touch, with an analyser on the warm microphone stream while LISTENING and
one `MediaElementAudioSourceNode` on the single player — created once, only after the context
is confirmed running, and connected on to the destination — while the ElevenLabs voice
speaks. If either analyser is unavailable the orb approximates; the audio itself is never
delayed or rerouted for it. Open the page with `?dev=1` for a developer section in Settings
that renders every component from invented data (marked "Fixture · not live") and lets you ask
by typing; `?dev=0` hides it again. Production renders only what the backend returns.

### Who may ask

Nothing here has a password: the backend binds to loopback on the Mac and is reached only
through the owner's own tailnet. That is the intended trust boundary and it is written down
here so that it is a decision, not an oversight. To narrow it, set `CROOKS_ALLOWED_LOGINS` in
`.env` to the Tailscale logins that may ask (`you@example.com`); `tailscale serve` stamps every
proxied request with the caller's login and any other login is refused with a 403. A proxied
request that carries no login at all — Funnel, a tagged node — is refused whether or not the
list is set. Requests made on the Mac itself carry no login and are always allowed. The Mac
logs a warning at start while the list is empty.

Recordings are not kept: the tablet's audio is decoded, recognised and dropped. Set
`CROOKS_SAVE_CAPTURES=true` to keep them under `bench/audio/` while diagnosing a mis-hearing.
The operational log records how long a transcript was, never the words.

### Layout

```
app/
  main.py            FastAPI app; loopback only
  runtime.py         composition root — everything is wired here
  presentation.py    the `ui` list: cards chosen from tool results, bounded and whitelisted
  identity.py        the tablet's login confirmed with `tailscale whois` before a change
  media.py           signed same-origin image paths for the tablet; never a raw CDN URL
  routes/            health · turn · speak · admin · actions (arm, commit) · context · media
  actions/           engine (stage · arm · commit · prove · undo) · grammar · available · ledger
  context/           order (one document per order) · attention (what the order needs)
  providers/         base.py (ABC) · max_agent_sdk.py · anthropic_api.py (stub, deliberately)
  tools/             registry · gate · dispatch · shopify_tools · shopify_writes · gmail_tools ·
                     gmail_writes · mock
  clients/           shopify · gmail · whisper · elevenlabs (Scribe) · elevenlabs_tts (Derek)
  speech/            decode · transcribe · speakable (text for a mouth)
  session/           manager · models (issued-id ledger)
  kb/                loader + the system prompt
  secrets/           keyring wrapper
  logging/           redacted JSONL with rotation
config/settings.py   non-secret configuration
web/                 the tablet client: index.html · style.css (tokens) · app.js (voice,
                     state, deck) · orb.js (canvas) · audio-viz.js · ui.js (renderer) ·
                     fixtures.js (dev only, loaded with ?dev=1)
scripts/             up (one window) · install_launchd (login-time agents) · launch_common
                     doctor · set_secrets · gmail_auth · shopify_check · whisper_server
                     bench_whisper · chat · acceptance
tests/               gate · turnlog · shopify_tools · gmail_tools · bench_decision
launchd/             templates for the login-time agents; `make install` fills them in
```

whisper.cpp itself lives outside the repo at `~/tools/whisper.cpp` — it is a large third-party
build tree and does not belong in this history.

---

## Status

The portable code is written and tested. The machine-specific work — the parts that need your
Mac, your tablet, and your console access — is not, and cannot be done from anywhere else.

| Milestone | State |
|---|---|
| M0 Environment | Repo, packaging, `make doctor`. **Run `make doctor` on the Mac.** |
| M1 Transport | FastAPI + `/health` + the tablet page. **Tailscale setup is yours.** |
| M2 Microphone | Capture UI, `/audio-test`, decode + level stats. **Needs the tablet.** |
| M3 Speech | Pipeline **passed against a real whisper-server** here. Normaliser tuned on the real catalogue. **Benchmark needs the Mac and tablet audio.** |
| M4 Claude provider | **Passed against real Claude.** Billing guard; runs on the CLI's own login (`auth=cli`), from a Terminal or the login-time agents alike. |
| M5 Tools + gate | **Passed against real Claude** — hook denied a RED call live. Proven by tests on every run. |
| M6 Shopify auth | Client with token cache and the `shpat_` fallback. **Needs your credentials.** |
| M7 Shopify tools | Seven tools; queries validated against the schema and search syntax verified on the live store. **Needs your credentials to run.** |
| M8 Gmail auth | Auth script and refresh handling. **Needs the Google Cloud console work.** |
| M9 Gmail | Two read tools; five staged changes (draft, send, archive) on the action engine, scoped by the credential itself. |
| M10 Typed agent | System prompt, KB loader, `scripts/chat.py`, redacted logging. **KB written from the store's own policies and metafields**; one discretion section is yours. |
| M11 Voice in | `/turn` takes audio or text; the tablet polls `/state` so the screen shows the tool actually running. |
| M12 Voice out | Chunking, unlock, voice picker — all three Android guardrails. |
| M13 Reliability | Named failures incl. usage-limit reset time and "lost the thread"; per-subsystem `/health` with Core ML check, cached for 90 s; `make up` / `make install`; log rotation; capture cap. |
| M14 Acceptance | 18-command script; placeholders fill themselves from the live store. **Run it from the tablet.** |

What has actually been verified — here, on Linux, and against the real store:

```
every test passes, 2 skipped (live Shopify/Gmail), all offline  make test
ruff clean                                                       make lint
8/8 GraphQL queries validated against the Shopify Admin schema
```

**Against the live CROOKSLDN store** (read-only, through the developer connector — never
through the assistant): shop domain, timezone, order-name format, order search syntax, product
search syntax, customer search behaviour, variant title shapes and the real 23-product catalogue.
Each of these corrected something the plan assumed. See *What the live data changed* below.

**Against whisper.cpp, built and run here** (CPU only, no Core ML): a PyAV-encoded
`audio/webm;codecs=opus` blob — what the tablet's MediaRecorder sends — decodes to 16 kHz mono,
transcribes correctly through `app/clients/whisper.py`, and silence stops at the level gate
before whisper is called. Two server-API mistakes were found and fixed. The Linux timing
(~6 s for 11 s of speech, no acceleration) is not representative of the M4 Max and is not
quoted anywhere as if it were.

**Against real Claude on subscription auth** (`bench/results/m4-m5-*.txt`): the plan's M4 and
M5 success tests pass. With a deliberately bland tool description Claude *attempts* the RED
tool, the `PreToolUse` hook logs `tier=RED`, the SDK denies it, the handler's counter stays at
zero, a proposal id is staged, and Claude reports the refusal honestly. No API key was present.

Not verified, because it cannot be from here: the tablet microphone (M2), Core ML timings (M3),
your Keychain, Tailscale, launchd, and the live Shopify/Gmail tools with your credentials.

---

## The review

Eight independent reviewers each took one lens — gate security, Agent SDK correctness, Shopify
API, Gmail API, Chrome-on-Android, speech, plan conformance, unattended operation — and produced
63 findings. Every finding was triaged against the current tree; the ones that stood were fixed
in commit `cebccbe`. The most serious: transcripts were reaching the stdout log unredacted,
`POST /reload-kb` changed nothing the model saw, the billing guard ran inside a caught start-up,
Gmail calls blocked the event loop so the tool timeout could never fire, and a stalled Claude
turn would have held the turn lock forever. The full list is in that commit's message.

Findings that were refuted stayed refuted: "token.json is a secret in a file" was the plan's own
choice (the Gmail credential can now live in the Keychain instead); caller-chosen session ids are
accepted on a single-user tailnet.

---

## What the live data changed

The build plan was written from the spec. Running the code against the real store, a real
whisper-server and real Claude changed these things — each one would have cost time on the Mac.

| Plan assumed | Reality | What changed |
|---|---|---|
| Shop domain `crooksldn.myshopify.com` | `5wn03t-nm.myshopify.com` | Settings default |
| Orders named `#4832`, searched as `name:#4832` | Orders are `CROOKS-1928` (older ones `#1036`); bare `name:1928` matches both | Search uses the bare number; "crooks 1928", "CROOKS-1928", "#1928" all resolve |
| Variant title is the size | Multi-option variants are `Black / XS` | Size filter matches one segment |
| Stock is ≥ 0 | `inventoryQuantity` can be `-1` | Reported as "oversold by 1", never as minus one |
| Product options are Size | Sets have options like `Grey Convict Hoodie (Size)`; socks have `Quantity: 1pc` | Live catalogue takes only Colour values, so `XS`/`1pc`/`V2` never become terms |
| A name search finds the customer | "Noah" returns three other Noahs before the buyer | `find_order` flags ambiguity with the candidates; `find_customer` flags truncation |
| Product names are pronounceable | `CRXST★RZ T-SHIRT`, `MOTIONTEC™️` | Terminology file supports `spoken form => Canonical` aliases; the seed ships with the real catalogue |
| whisper-server takes `vad_filter` | The field is `vad` | Client fixed; VAD was silently off per request |
| A bare term list is the right Whisper prompt | It strips capitals and punctuation from transcripts | Prompt is display-case and ends with a period — measured before and after |
| The Keychain is always reachable | Not on Linux, not from a system daemon | Provider uses the CLI's own login; the login-time agents `make install` sets up run in the user session, where both work |

---

## Two deviations from the build plan

Both were forced by things that only show up when the code is actually run.

**1. `secrets/` is `app/secrets/`.** A top-level package named `secrets` shadows the standard
library's `secrets` module, and FastAPI imports `token_hex` from it during startup. The result
is an `ImportError` before a single line of our code runs — verified, not theorised. Nesting it
under `app/` keeps the same shape and cannot shadow anything.

**2. Metaphone, not Double Metaphone.** `jellyfish` removed Double Metaphone in 1.0. Metaphone is
the closest maintained equivalent and is what the normaliser's thresholds were tuned against.

---

## Rules this codebase is built on

- **Read-only by default, and a write is a proposal.** With writes off (the default) there is
  no send, no draft, no label, no edit, no refund, no inventory write: the gate denies mutation
  verbs by name, the Gmail scope cannot write, and the Shopify client refuses any mutation
  document. With writes on, the one declared write is staged for the owner's tap, executed
  once from the Mac's stored copy through a single reviewed mutation, and proved by a re-read.
  There is no path from a model's call to a mutation.
- **Never report success that was not verified.** A tool error is reported as an error. This is
  the one failure mode that is not negotiable, because it is the one that destroys trust.
- **Ask rather than guess.** Two customers called John produce a question, not a choice.
- **No pay-as-you-go billing, ever.** The process refuses to start if `ANTHROPIC_API_KEY` or
  `ANTHROPIC_AUTH_TOKEN` is set. Do not remove that check.
- **Secrets live in the Keychain.** Typed at a local prompt, never in a file, never in an
  argument, never echoed, never logged.
- **Logs carry no personal data.** Addresses, phone numbers, emails, postcodes, card numbers and
  message bodies are redacted before anything is written. `tests/test_turnlog.py` opens a real
  log file and checks.

---

## Out of scope for Day 1

Wake word, Android APK, VPS hosting, scheduled triage, and shipping-label integration. The
write actions arrived with the operational expansion (see "Changes to the store and the
inbox"); shipping labels are still Click & Drop's.
