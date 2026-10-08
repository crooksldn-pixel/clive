# CROOKS OS — Phase 3 engineering pass

**Not deployed.** Nothing in this pass has been applied to the running build. The branch is
pushed for the owner to test physically on the Samsung first; the deployment steps are at the
end of this report and none of them has been run.

- **Starting SHA** `644be75` (the Phase 2 report's final commit)
- **Final SHA** `461a8b4` — the commit before this line was written; §16 has the test set as run
- **Branch** `claude/crooks-assistant-build-lgxlau`
- **Coding environment** Linux, no Keychain, no Shopify or Gmail credentials, no Claude
  subscription for the assistant's own provider. Everything below was proved against the
  golden fixture world, the offline suite, and a real Chromium at the tablet's own viewport.
  What could not be proved here is listed under *Blocked by credentials*, with what to run on
  the Mac instead.

---

## 1. What the live test found, and what happened to each finding

The Phase 2 live tablet test (`ts-20260910-125946`, 601 × 889, DPR 1.33) is the input to this
pass. Each row says whether the failure is now impossible **by a test that can fail**, or still
possible.

| The live failure | Now | Held by |
| --- | --- | --- |
| Two fingers on the orb produced a blank speech turn, six times | **Impossible** | `scripts/browser/tablet.js` — a CDP two-finger spread forks the branch and asserts **zero** `/turn` posts and no hearing error |
| Split depended on a secret gesture | **Impossible** | The same gate asserts a visible `Split` control that reaches the same backend command |
| Tapping the other half changed who was listening, not what was on screen | **Impossible** | `tests/test_split_workspaces.py` plus a browser check that switching halves changes the visible cards |
| A half finished a ten-second turn with nothing on the tablet | **Impossible** | `branch.ready(...)` when the focus is elsewhere, asserted in `tests/test_split_workspaces.py` |
| The dock was decorative unless already in an interaction | **Impossible** | `experience/scenario_packs/landings.py` — four landings, each tapped from an idle tablet, no model; the tablet gate asserts the tap lands by command, not by sentence |
| `commerce_query` failed three times running with "sort by :" | **Impossible** | §11.3 — the six reconstructed live attempts, each of which now parses or carries a `schema_help` whose offered example is itself parsed by the test |
| An email thread showed no linked order | **Impossible** | §11.4 — `tests/test_graph.py` and `experience/scenario_packs/graph.py`, and the thread says *why* it belongs to that order |
| "Add a black hoodie to this order" refused | **Built** | §11.1 — `shopify_order_add_item` on the action engine, with a variant picker that never guesses. Needs the `write_order_edits` scope |
| Discount code, store credit, abandoned checkouts refused | _see §12_ | The commerce-writes family; state at the end of this report |
| An email to an address that is not a customer refused | **Built** | §11.2 — the composer, and the gate's own id rule is what keeps an arbitrary address safe |
| "No, don't save a draft, you want it sent" took 25 s and failed | **Built on the touch path** | §11.2 — the draft is loaded into the composer as a send, one gesture away. Not staged from the spoken path, by construction |
| The armed state was clipped in a dock pill 788 px below the finger | **Impossible** | The armed pill is drawn on the control; the tablet gate asserts it is unclipped, inside the card, with a 44 px Cancel |
| A failed customer read was drawn as "no customer" | **Impossible** | `tests/web/ui.test.js` and `tests/test_context.py` — a failed region says so and the tab is marked |
| The compound turn — "have they emailed about this … and draft the reply" — took 35 s | **One turn** | §11.5 — the recipe draws the workspace and Claude writes the words in the same turn; the recipe's grounded sentence leads |
| Compound surfaces over 3,300 CSS px | **Reduced, measured** | §22 below: the three compound landings now fit one screen at 601 × 889 |

---

## 2. Architecture changes

### 2.1 One Claude conversation per half of the orb (§3F)

The provider kept **one client per session** and **one process-wide turn lock**, with the
turn's state — the session it was for, its tool calls, its steps, the conversation position it
answered — in fields on the provider itself. Two halves thinking at once would have shared all
of it.

- `app/providers/max_agent_sdk.py`: a `_Conversation` per `conversation_key(session_id,
  branch_id)`, each holding its own client, its own `asyncio.Lock` and its own turn state. A
  client's MCP tool server and PreToolUse hook look through a `_Holder` to find whose turn they
  are serving, so a tool call can never be filed against the wrong half.
- Turns on **one** half still serialise. Turns on **different** halves run together, up to
  `MAX_CONCURRENT_TURNS` (two — one per half).
- `interrupt(session_id, branch_id=...)` stops one half's turn and leaves the other thinking.

Two things had to become per-half for this to be *safe* rather than merely parallel:

1. **Which half a proposal belongs to.** `session.acting_branch` is one field for both halves
   and holds whichever spoke last. The branch now travels on the task the tool call runs in
   (`app/tools/context.py:CURRENT_BRANCH`, read through `acting_branch(session)`), so with two
   calls in flight the engine cannot stamp the left half's proposal with the right half's id.
2. **"The owner has moved on."** This was judged by the session's epoch, which moves for
   *either* half's instruction — so every slower answer would have been called abandoned,
   unspoken, its proposals withdrawn, because the owner asked the other half something
   meanwhile. Each half now counts its own instructions (`Branch.instruction_seq`) and carries
   its own cancel flag; `/cancel` takes a `branch_id`.

**The mutation boundary is untouched.** Staging and commit are the action engine's, on its own
terms; a background half still cannot commit; a proposal is still bound to session, epoch,
turn and branch. Nothing about concurrency lets two writes overlap: the engine serialises
commits as it always did.

On the tablet, `busy` was one flag for the page. It is now a map of in-flight turns by half,
and `busy` means "the half on screen is thinking" — switching halves switches what it means.
An answer that lands for a half the owner has left is not drawn over the conversation he is
having now; its chip says READY and the Mac holds its screen for `branch.show`.

### 2.2 The dock's landings (§4)

Each icon asked a sentence through the whole turn pipeline, so "show me today's orders" on a
quiet afternoon drew an empty list. A landing is now a place with a fixed shape, in
`app/families/landings.py`:

| Icon | What it draws |
| --- | --- |
| Orders | what has to go out, oldest first and a set to walk, plus what came in today |
| Inbox | who is waiting on a reply, then what else people have written |
| Sales | the week against the week before, today so far, and what is selling |
| Products | the month's best sellers and what is closest to running out |

Four FAST recipes — deterministic reads through the read scheduler, no model — reached two ways
that resolve to the same recipe: the tap posts the semantic command `open.area` (which area,
nothing else; the Mac decides the rest), and "open orders" / "open the inbox" / "open sales" /
"show me stock" spoken resolve to the same recipes. A sentence that names a period still gets
the period's list. A tap the Mac cannot draw falls back to the sentence, so the icon always
does something.

Two supporting changes in `app/routes/command.py`: a command may name a FAST recipe for the
route to run (`changed["recipe"]`), and every posted form field reaches the command, bounded
(24 fields, 8,000 chars) — which is also what makes precision input work without a route change
per field. A fresh tablet may tap the dock before it has said anything: `open.area` creates the
conversation, as a sentence would.

### 2.3 Capability families as a seam (§29)

`app/families/` is a package where each capability is one module: its tools, commands, recipes,
intent families and capability state register on import. Adding a capability is adding a file,
so parallel work never edits the same table.

`runtime.withheld_by_family()` now hides from the model every tool of a family that is not
READY — all of them for NOT_SUPPORTED_BY_STORE, DISCONNECTED or NOT_IMPLEMENTED, the write
tools for MISSING_SCOPE or READ_ONLY. The live test spent fifteen seconds of Claude attempting
operations the store could only refuse; a tool that is not offered is not tried. The same table
reaches the model as one context line and the tablet as the settings sheet's "What I can do",
where an unavailable family says which kind of unavailable it is and names the scope to grant.

---

## 3. Density: measured, then reorganised (§22)

Measured with a real Chromium at 601 × 889, DPR 1.33, against the fixture world, before and
after. `screens` is the deck's scroll height over the viewport.

| Surface | Before | After |
| --- | --- | --- |
| Orders landing | 1,112 px · 1.25 screens · two lists and **two** "these" cards | **671 px · 0.75** |
| Inbox landing | 952 px · 1.07 screens · two email lists stacked | **671 px · 0.75** |
| Products landing | 1,498 px · 1.69 screens · two full rankings | **736 px · 0.83** |
| Order card | 796 px · 0.90 | unchanged (physically judged good) |
| Capability card | 1,132 px · 1.27 | unchanged |
| Stock ranking | 1,013 px · 1.14 | unchanged (one card, legitimately long) |

`compact()` in `app/presentation.py` applies two rules to the **whole screen**, after a recipe's
own cards have been put in front of the tool cards — which is why it is not part of `_merge`:
`_merge` runs inside `present()` and can only see the tool cards, so the Inbox landing's two
lists never met until afterwards.

1. **One cursor per turn.** Two cards each saying "these" are two claims to the same word.
2. **One headline per kind.** The second card of one analytic kind is marked `secondary`, and
   the tablet folds it behind its own title (`web/ui.js:folded`: a real button with
   `aria-expanded`, the card inside complete and untouched). Nothing is removed. An order card
   is never folded — two orders in one turn are two records, both wanted open — and two
   *different* kinds are both headlines, so Sales keeps its numbers beside its ranking.

---

## 4. Latency: three numbers where there was one (§25)

`turn_performance` now carries `facts_ms` (when the Mac held the authoritative data the cards
are drawn from — the last read to land), `workspace_ms` (when the cards existed) and
`prose_wait_ms` (the rest: what the owner waited *after* the facts were in hand). The third is
the number to attack, and the old single `turn_total_ms` could not see it: a turn that read an
order in 400 ms and then spent eight seconds writing a sentence about it looked the same as one
that spent eight seconds reading. `enrichment_pending` names the regions a card left loading,
so final enrichment pairs with the `/context/order` request that finishes it.

Bench (`make bench-lanes`, 200 orders, 40 ms per source request; re-run on the merged build.
The "then" column is the real session of 9 September 2026):

| Asked | Then, on the tablet | Now, the Mac's own work | Target |
| --- | --- | --- | --- |
| What more can you do now? | 76.6 s (75.5 s of it Claude, 0 tool calls) | **0 ms**, FAST | 50 ms |
| Read me the full address | 36.8 s (35.2 s of it Claude, 1 tool call) | **41 ms**, FAST | 1.0 s |
| Next · Next again | 30.4 s each (29.4 s of it Claude) | **0 ms**, FAST | 750 ms |
| Which customers are waiting on a reply | 29.0 s (28.1 s of it Claude, 0 tool calls) | **85 ms**, FAST | 4.0 s |
| Order 1938, cold · again | not asked in that session | 84 ms · 41 ms, FAST | 1.0 s |
| Which orders are late | not asked in that session | **944 ms**, FAST | 2.5 s |
| What sold best this month | not asked in that session | 126 ms, FAST | 2.5 s |
| Tap Orders · Sales · Products | not asked in that session | 2 ms each, FAST | 1.5–2.5 s |
| Go back | not asked in that session | 0 ms, FAST | 100 ms |

**17 of 17 bench rows answer with no model call.** Four of those rows are sentences the live
session actually said and waited 29 to 77 seconds for; three of the four made **no tool call at
all** in that session, which is to say the whole wait was the model deciding it had nothing to
look up.

The landing figures are warm: their reads go through the order cache, which the Mac warms at
start-up, so this is what the second tap of the day costs. The first tap pays the warm.

**The slowest recipe, and why it is worth naming:** `delayed_orders` is 944 ms, an order of
magnitude above every other row. It is inside its target and it is not new — but it got slower
in this pass, because the golden world gained an order that has been waiting fourteen days and
the recipe now has more to sort and more to draw. That is the shape to watch on the real store,
where "what is late" is the question with the most rows behind it. Nothing else exceeds 130 ms.

### 2.4 The capability manifest, made user-useful (§29)

Fifteen families are registered for what already worked — reading orders, customers, products
and email, the analytics, and the ten write operations (cancel, refund, fulfil, tracking,
address, notes, tags, stock, drafts, sends, archive). A manifest that lists only the new
things is not a manifest, and `/health families` returned nothing before this.

Their states are **derived, not declared**: `families.states()` reads the per-operation table
`runtime.capabilities()` already builds, so a family says READ_ONLY when changes are switched
off and MISSING_SCOPE when Shopify has not granted the scope, without `app/families/core.py`
knowing anything about either. Two tests hold the seam: every registered write operation and
every model-facing read tool must be named by some family, so a capability cannot be added
without appearing in the manifest.

What the model is told changed with it. The line used to list every family; with fifteen
registered that is **420 characters of prompt on every turn** to say that reading orders
works. It now carries only what the Mac **cannot** do:

| | Lines | Characters per turn |
| --- | --- | --- |
| Every family (the old shape) | 15 | 420 |
| Only the unavailable ones, all ready | 0 | **0** |
| Only the unavailable ones, one blocked | 1 | 117 |

The ready families are the tools the model is offered — `withheld_by_family` takes the rest
away — so the tool list already says what is available. The owner's surfaces still ask for
the whole list (`words(table, only_unavailable=False)`), and the settings sheet shows it.

### 2.5 A family brings its own word to the router (§17)

The brief's section 17 names the requests that should avoid the model. Run against the router,
three of its own examples resolved to no family at all — not because the fast lane could not
answer them, but because the router had no word for *shipping*, *latest* or *half*, and its
signal vocabulary was a fixed dataclass every family would have had to edit at once.

`app.fastpath.intent.signal(name, predicate)` is now a seam: a family registers its own word
and `score` looks it up like any other. A core signal can never be shadowed. Three families
use it (`app/families/navigation_extras.py`): the tab move goes through the same
`surface.tab` command the tap reaches, the latest order names which order it turned out to
be, and the switch moves the focus and draws what that half was looking at.

The routing table now, with an order open and a set being walked:

| Said | Lane | Family |
| --- | --- | --- |
| order 1938 | FAST | order_lookup |
| show me today's orders | FAST | order_list_period |
| read me the full address | FAST | order_address_lookup |
| where is order 1938 | FAST | order_status_lookup |
| show me the shipping / the items / the customer | **FAST** | order_tab_show |
| show me the latest order · the most recent order | **FAST** | order_latest |
| switch to the other half · the other half | **FAST** | branch_switch |
| next · go back | FAST | working_set_next · navigation_back |
| open orders · open the inbox · open sales · show me stock | FAST | the four landings |
| what can you do? | FAST | capability_summary |
| what else has this customer ordered? | FAST | customer_history_lookup |
| what sold best this month · which orders are late | FAST | best_sellers_period · delayed_orders |

Two collisions were found by the tests and fixed, both of which had made a previously fast
sentence slow: "address" as a shipping-tab word stole the sentence that reads the address
out, and "last" as a latest word stole the cursor's "the last one". One the router was right
about: with an order open, a bare "show me the email" is genuinely ambiguous between this
order's Email tab and the inbox (0.96 against 0.90, inside the margin), so the inbox keeps
the bare word and the tab is reached by a sentence that says which order.

---

## 5. Blocked by credentials or configuration

This machine has no Keychain, no Shopify token, no Gmail credential and no Claude
subscription for the assistant's own provider, and by the brief's own rule no automated run
may make a real Shopify or Gmail write. So four things could not be proved here, and each has
an exact command to run on the Mac instead.

| What | Why it could not run here | Run this on the Mac |
| --- | --- | --- |
| Live read-only scenarios against the real store | No token; the harness refuses to read a real shop unless the read-only guard is armed, which needs the credential | `make experience-live` |
| Whether Shopify has granted the new scopes | `access_scopes()` needs the token; the probes are written and tested against a fake | `crooks-status`, then the settings sheet's "What I can do" |
| Any real mutation | Forbidden by the brief, and the fixture Shopify raises on every mutation so a test can only ever exercise prepare, observe, present and verify | The owner's own gesture on the tablet, once he has read the card |
| The model's own behaviour on the new prompts | No subscription here; the fixture harness stubs the provider | Ask the questions on the tablet and read `make watch` |

The offline suite reports this itself rather than hiding it: **two tests skip, loudly**, and
they are the only two —

    SKIPPED tests/test_gmail_tools.py:175  no Gmail token.json
    SKIPPED tests/test_shopify_tools.py:190  no Shopify credentials in the Keychain

— and the browser gate skips the same way when Chromium is absent (it is not absent here; it
ran, 61 checks at both viewports). A check that cannot run has proved nothing, and saying so
is the difference between a suite that is green and a suite that is honest.

Nothing in this pass depends on a credential to be *correct* — every write's prepare,
precondition, verification and refusal path is exercised against the fixture, and the fixture
refuses every mutation, which is what makes those tests able to fail.

## 6. Deployment steps — for later, not now

**None of this has been run.** The running build is untouched. When the owner has tested the
branch physically and accepts it:

1. **On the Mac, in the project:** `git fetch origin` then
   `git log --oneline HEAD..origin/claude/crooks-assistant-build-lgxlau` to read what is
   coming.
2. **Check before applying:** `make update CHECK=1` — or `crooks-update --check`, the same
   script. It reports the current and candidate SHA, whether it is a fast-forward, whether
   the tree is dirty and whether dependencies changed, and changes nothing. A dirty tree or a
   diverged branch **stops** the update; there is no `--force` and no reset.
3. **Apply:** `make update`. That fast-forwards, installs dependencies if they changed,
   restarts through the existing launchd agents, and verifies `/health`.
4. **Verify on the Mac:** `crooks-status` — or the Control app's status view — and check that
   the build id moved, every check is green, and the capability families read as expected.
5. **Verify on the tablet:** open CROOKS OS, confirm the dock lands, and read the settings
   sheet's "What I can do".
6. **Before the first app-driven update, once:** `make commands` (this is what installs the
   `crooks-control` wrapper), then **`crooks-control mark-good`**. That records the build
   that is running and working as the one to come back to. Nothing has ever recorded one, so
   until you do, there is no rollback target and the Control app's Roll back stays hidden.
7. **If it does not come up:** `make restart` once. If it is still unhealthy,
   `crooks-control rollback --yes` returns to the last recorded good build — it refuses a
   dirty tree, refuses without the explicit `--yes`, and refuses a commit that is not already
   in the checkout. Failing that, by hand: the SHA to go back to is the one step 2 printed as
   the current build, and `git checkout <that sha> && make restart` returns to it. Nothing in
   this pass moves a branch destructively, and the update never discards uncommitted work.
8. **The Control app instead of any of the above:** once built (§14), the menu bar carries
   Update, Check for update, Restart, Run tests, Start/Stop recording, Generate report, Open
   logs and Roll back, each running the same command this list names. It is a renderer, not a
   second implementation — a test asserts no Swift file contains a git, launchctl, pytest or
   network call of its own.

Scopes: any family whose state reads MISSING_SCOPE needs its scope granted in the Shopify
admin before it will work. The families table names the scope; §6 above lists the new ones.

---

## 7. Does any of this weaken the mutation security model?

**No, and two of the changes strengthen it.** Taken one at a time against the twenty-four
invariants:

- **Concurrency (§3F).** Two halves think at once; nothing about writes changed. A proposal is
  still staged by the Mac from arguments the Mac built, still bound to session, epoch, turn and
  branch, still committed at most once by the action engine, still verified by an authoritative
  re-read. A background half still cannot commit. What changed is that the branch a proposal
  belongs to now travels on the task the tool call runs in rather than in one field the two
  halves shared — **without** that, two halves staging at once would have mis-stamped each
  other's proposals, which is a security bug this pass removes rather than adds.
- **The dock's landings (§4).** Four recipes that read. `assert_read_only` holds for them, and
  the command that opens one carries an area name from a fixed table of four.
- **Every posted field reaching a command (§7).** Bounded at 24 fields and 8,000 characters,
  and a command is a read or a move by construction. This is the precision-input path and it
  keeps the rule exactly: the tablet posts identity and typed text to a Mac command that
  validates it into a Mac-held context; staging then builds execution from that context. The
  tablet still cannot post an execution argument.
- **Withholding tools by family state (§29).** Strictly subtractive: it can only take a tool
  away from the model, never offer one. A test holds that no family which already worked
  withholds anything.
- **The compaction (§22) and the fold.** Presentation only; the folded card is the whole card
  and the actions on it are the same server-decided actions.
- **The signal seam (§17).** Routing only, and a core signal cannot be shadowed. A recipe
  reached this way is read-only like every other.

One thing to watch, recorded as a weakness rather than dismissed: the per-half turn state made
`_Conversation` the holder of what used to be provider fields, and the PreToolUse hook now
finds its session through that holder. If a future change gave a client to two conversations,
the hook would gate against the wrong session. `_Holder` is deliberately one slot, filled when
a conversation adopts a client and emptied when it lets it go, and `test_a_hook_event_with_no_turn_behind_it_touches_nothing`
holds the empty case — but this is the place to be careful.

---

## 8. What to test physically on the Samsung, in order

Everything here was proved against fixtures and a real Chromium at 601 × 889. What a browser
cannot prove is a thumb, a microphone and a real store. In rough order of what would be most
embarrassing to have got wrong:

1. **Two fingers on the orb.** Spread them. It must divide, buzz once, and say "Divided" — and
   the assistant must not say it could not hear you. Then pinch to merge.
2. **The Split control.** With one half, tap `Split` in the rail. Same outcome as the gesture.
3. **Switch halves.** Ask each half a different question, then tap between them. The cards on
   screen must change, not just who is listening. Then say "switch to the other half".
4. **Both halves at once.** Ask the left half something slow ("how were sales last week"), and
   while it is thinking ask the right half something quick ("order 1938"). The quick answer
   should arrive first, and the slow one should land on its own half without stepping on it.
5. **The dock, from the idle screen.** Tap Orders, Inbox, Sales, Products in turn, with nothing
   said first. Each must draw a workspace, fast, and the second card of a kind should be folded
   with a title you can tap open.
6. **Hold to talk after typing.** Open a composer, type in a field, then hold the dock and
   speak. Typing must never start a recording, and the hold must still work.
7. **The armed state.** Tap Reply on an email. The pill must sit on the card, unclipped, with a
   Cancel you can hit. Speak the reply; then do it again and tap Cancel, and check the next
   question is not swallowed.
8. **A failed read.** Hard to force deliberately; if the Mac loses Gmail mid-turn, an order's
   Email tab must say it could not check rather than saying there is no email.
9. **Settings → What I can do.** Read it. Every family should say READY or say exactly why not,
   and any missing scope should name itself.
10. **Reload while on an order.** Pull down to refresh. The workspace must come back.

Say `make watch` on the Mac while testing: every turn's lane, recipe, timings and the three
new latency numbers are printed live, and `crooks-status` shows the family states.

---

## 9. The thirty-two acceptance scenarios (§31), and what covers each

`experience/scenario_packs/` collects golden scenarios one file per family; 24 are registered
— 55 of them now (`make experience-list`), and all 55 pass in the shared-harness runner as
well as one-per-test under pytest, which was not true until the reset below was rebuilt.
Browser checks are the 61 at both viewports.

| # | Scenario | Covered by |
| --- | --- | --- |
| 1 | "Show me order 1938" → rich workspace | `order_lookup` |
| 2 | Tap Shipping / Items / Customer | `tabs`, and `spoken_tab` for the spoken form |
| 3 | "Show me the full shipping address" | `full_address` |
| 4 | "What else has this customer ordered?" | `customer_history` |
| 5 | Tap previous order → Back | `back` |
| 6 | "Show me today's orders" | `today_orders` |
| 7 | Next twice → Back → voice "Next" | `next_previous` |
| 8 | Tap a random order row | browser check (a row opens its order) |
| 9 | "Which customers need replying to?" | `needs_reply` |
| 10 | Open email → linked order visible | `linked_entities`; the graph pack when it lands |
| 11 | Tap Reply → unclipped armed state | tablet gate `06-armed-reply` |
| 12 | Speak reply → correct thread and draft state | `unsupported_edit` covers the refusal path; the compose family covers the rest |
| 13 | Cancel reply → next question not swallowed | tablet gate (Cancel clears, the next hold posts) |
| 14 | Order → email | `linked_entities` |
| 15 | Email → order | the graph work (`tests/test_graph.py`) |
| 16 | Two-finger split → ZERO speech turn | tablet gate, the CDP two-finger spread |
| 17 | Visible Split button | tablet gate |
| 18 | Switch left/right → visibly different workspaces | tablet gate, `split_branches`, `spoken_switch` |
| 19 | Aside task completes → result retrievable | `tests/test_split_workspaces.py` (READY + `branch.show`) |
| 20 | Merge → structured result, no proposal approved | tablet gate (pinch merges), `tests/test_branches.py` |
| 21 | "Add a black medium Convict hoodie" | the order-edit family |
| 22 | "Create an order for …" | **not built** — see the unresolved list |
| 23 | "Create a 15% discount called TEST15" | the commerce-writes family |
| 24 | "Add £10 store credit" | the commerce-writes family |
| 25 | Arbitrary external email | the compose family |
| 26 | Deliberately mis-transcribed email | the compose family's precision input |
| 27 | "Send it instead" | the compose family |
| 28 | The compound order → email → draft | the graph family's compound recipe |
| 29 | Old international unfulfilled order | the query-engine family |
| 30 | Reload while on an order | tablet gate (the workspace comes back) |
| 31 | Failed customer read → FAILED, not "no customer" | `tests/web/ui.test.js`, `tests/test_context.py` |
| 32 | 601 × 889 → no clipped armed UI | tablet gate, and the density measurements above |

---

## 10. Screenshots at 601 × 889

Taken by the tablet gate against the fixture world, at the Samsung's own viewport and DPR
(`docs/screens/phase3/`, regenerated by `make experience-ui`, which now shoots both viewports):

| File | What it shows |
| --- | --- |
| `tab-01-idle.png` | the idle screen, with the dock reachable — nothing overlaying it |
| `tab-02-dock-orders.png` | the Orders landing: what has to go out, one "these" card, and today's list **folded** behind its title |
| `tab-03-divided.png` | after a two-finger spread: two halves, and no speech turn |
| `tab-04-second-half.png` | the other half, showing its own workspace rather than the first half's |
| `tab-05-reloaded.png` | after a reload: the workspace comes back |
| `tab-06-armed-reply.png` | the armed pill on the card — "Replying to Mia", unclipped, 44 px Cancel |

And seven at 800 × 1280, the size the interaction language was designed against, so a change
that reads well on one and badly on the other is visible: `01-home`, `02-order-detail`,
`03-order-list`, `04-capabilities`, `05-list-walk`, `06-armed`, `07-email-thread`.

**All thirteen were retaken against the merged build**, not the build they were first shot
from — four merges landed between, and the Orders landing genuinely differs now that the
golden world holds an order that has been waiting fourteen days. A screenshot of a build
nobody is shipping is worse than none.

The header in these reads "cannot hear you" because this machine has no whisper server and no
ElevenLabs key; that is the environment, not the build.

---

## 11. The capability families, one at a time

Each of these is one module under `app/families/`, registering its own tools, commands,
recipes, intent families and capability state on import. Adding a capability is adding a file.

### 11.1 Order item editing (§10) — `order_edit`

The live session asked *"add a black medium Convict hoodie to this order"* and was refused. It
is now a named reviewed mutation, `shopify_order_add_item`, on the existing action engine:
`orderEditBegin` → `orderEditAddVariant` → `orderEditCommit`, with the calculated order read
back before the commit so the card can say what the customer will owe.

It needs a read the build did not have — `shopify_variant_search`, words to a variant id — and
that read is where the ambiguity lives. "A black medium Convict hoodie" may match one variant,
several, or none, and the family never guesses: a new UI type, `variant_picker`, draws the
candidates with their SKU, price and stock, and **Add** is disabled until the owner picks one.
A confident single match is pre-selected and *still* needs the tap.

What travels back from the tablet when Add is pressed is `{order_id, variant_id, quantity}` and
nothing else — asserted key by key in `tests/web/ui.test.js`, because a price or a total coming
back from the tablet would be the write boundary leaking. The Mac builds the execution
arguments from its own fresh read.

- **Scope required:** `write_order_edits`. Absent, the family is MISSING_SCOPE and says so.
- **Not done:** there is no "Add item" chip on the order card's rail, so the picker is reached
  by the sentence rather than from the card; and there is no spoken route to the commit — the
  mutation guard makes the whole path touch, which is the design, not a gap.

### 11.2 An email to any address, and precision input (§7, §8) — `compose`

Two live failures, one cause. *"Write an email to a model asking if they're free for a shoot
next Sunday, their email is …"* was refused because every recipient in the build came from
Shopify. And *"no, don't save a draft, you want it sent"* took 25 seconds and failed.

The composer is the first card on the tablet with **editable fields** on it, and it is still not
a way round the write boundary. A keystroke posts `compose.field` — a composer id, a field
*name*, and the typed value — the Mac validates the characters into its own copy, and the
execution arguments are built from that copy when a gesture asks for them. `field()` in
`web/ui.js` is one generic component for the values a microphone gets wrong (email, address,
SKU, tracking number, variant, quantity, code, amount), so every family's field behaves the
same way and there is one place where a keystroke's route to the Mac is decided.

Three statuses, three rings: **ok**, **uncertain**, **invalid**. `uncertain` exists because a
mis-heard address is a perfectly valid address belonging to somebody else, and only the owner
can tell — so a dictated "4417 lighthouse pony at example dot com" is normalised, marked
uncertain, and **cannot be staged** until the owner has looked at it.

The gate turned out to enforce the safety property for free. Its write rule requires at least
one issued id, and an email address can never be one (`_ID_SHAPE` has no `@`), so `to` is
admitted only alongside `compose_id` — which the Mac minted and issued. An arbitrary address
can therefore only be staged from a composer whose card the owner has already read.

**The mutation guard was not lifted.** `intent.resolve` refused to score any sentence carrying
a mutation verb, and both bench sentences carry one ("write", "send"). A `Family` may now
declare `serves_mutation_words`, and `resolve` narrows the candidate set to families that
declared it when the sentence has one — so a family that has not opted in is unreachable by a
mutation sentence however well its signals match, and "cancel it" still returns no family with
the reason *asks for a change*. All three compose families that opted in are read-only:
`read_primitives=()`, and `assert_read_only` is run over them in a test.

- **Scope required:** none new. `gmail.compose` was already granted.
- **Not done:** "send it instead" does not stage from the *voice* path. The fast lane cannot
  stage, by construction, so spoken it draws the composer loaded from the draft's own stored
  execution with **Send** (red) on it, and the stage happens on that gesture. The one-gesture
  behaviour §8 asks for is complete on the touch path.

### 11.3 The read language, and every sort shape a planner sends (§15) — `query_language`

`commerce_query` failed three times running in the live session, once printing the empty
`sort by :`. The failures were reconstructed from the session and each is now a test that can
fail: nineteen sort shapes a planner actually sends, the empty key, unknown-versus-known sort
keys, and what counts as a missing dimension rather than a spec to fix.

Every refusal now carries `schema_help` — attached in the `parse()` wrapper, so it is on the
refusals raised before the metrics were even in scope — and the offered example **is itself
parsed by a test**, because a refusal that suggests a shape which does not work is worse than a
bare refusal. Measured at 350–460 characters including the dispatcher's suffix.

Two operational questions no longer reach the model at all: *"can you see if any of our orders
are undelivered or unfulfilled"* (0.79 FAST) and *"find a real international order that has
been waiting too long and hasn't been fulfilled"* (0.79 FAST). "International" means *not this
country*, read from the shop where the shop reports it.

And *undelivered* is answered honestly rather than approximately: **no carrier is connected**,
so whether a parcel arrived is not a fact this Mac holds — only fulfilled/unfulfilled, and
whether a tracking number exists. That is a registered DISCONNECTED capability family, which
is what puts the one standing line on every model prompt telling it not to try.

- **Scope required:** none — reads only, no new GraphQL, no model-generated queries. One new
  setting, `CROOKS_SHOP_COUNTRY_CODE` (default GB).
- **Not done:** an enum filter takes one value, not a list. The Shop GraphQL query is
  deliberately *not* extended to ask Shopify for its own country: that one query is where the
  timezone comes from, and a field the token's scopes may not cover would fail all of it.

### 11.4 Email ↔ order, both directions (§5, §6) — `graph`

An email thread showed no linked order on the tablet even though the backend had the
correlation — which the Phase 2 analyser reported as "email correlation missing: never". The
link is now on the card, in both directions, and a thread says *why* it belongs to an order:
the address and the order number, not the customer's name.

The needs-reply queue also stopped counting things that are not customers waiting. An
automated carrier report was offered as somebody awaiting a reply, because the listing found it
by the order number in its subject and nothing asked who wrote it.

### 11.5 The compound turn (§16) — one workspace, one sentence, one turn

The worst real turn was *"check whether they've emailed us about this, tell me what they're
waiting for, and draft the reply"* — roughly 35 seconds, almost all of it Claude rediscovering
mechanics it rediscovers every time.

A `FastAnswer` may now be `partial` and carry a **continuation**: an instruction to the model
that `app/routes/turn.py` appends to the prompt *instead of ending the turn*. The recipe's
cards are kept, its reads are on the log, and one answer comes back in two halves —

> **the recipe's grounded sentence leads, and the model's follows it.**

The order is the point. A fact that was *read* cannot be displaced by one that was *generated*,
and the grounded half is what the owner still hears if the model fails. The continuation prompt
is told not to repeat the mechanical half, so nobody hears who wrote and whether we replied
twice in one breath.

It is handed over only when the thing being asked for can actually be done: while changes are
off, the owner is told so plainly and the model is never asked for a draft the gate would
refuse. The continuation is never written to the timeline and never reaches the tablet — the
timeline keeps the tool name and a character count, because the prompt quotes a customer.

`facts_ms` takes the recipe's reads over the model's last tool step on such a turn. Reading a
draft being *composed* as "when the facts arrived" would report a twenty-second turn as twenty
seconds of reading and nothing waited, which is the inverse of the number §25 asks for.

---

## 12. What changed, counted

Phase 2 ended at `644be75`. Every number here is read from the code at both SHAs, not from
memory.

| | End of Phase 2 | Now | New |
| --- | --- | --- | --- |
| Intent families (a sentence the router can act on) | 19 | **34** | 15 |
| Fast-path recipes | 19 | **34** | 15 |
| Registered tools | 48 | **55** | 7 |
| Reviewed write operations | 20 | **21** | 1 |
| Capability families in the manifest | **0** | **18** | 18 |
| Semantic commands the tablet may post | 13 | **22** | 9 |
| UI types the tablet can draw | 26 | **29** | 3 |
| Golden scenarios | 15 | **40** | 25 |
| Offline tests | 1,465 | **2,040** | 575 |
| Golden scenarios in the shared runner | 15 | **55**, all passing | 40 |
| Browser checks | 61 at one viewport | **61 at both** | the 601 × 889 gate |
| Node tests (renderer, folding, service worker, telemetry) | 92 | **115** | 23 |
| Tool schema bytes offered to the model | 24,300 | **27,357** | +3,057 |

Two rows deserve reading twice.

**One new write operation.** `order_edit_add_line` is the only mutation this pass adds, and
that is the point: the brief says *do not create a second mutation system*, so everything else
new here either reads, moves the screen, or stages through the write path that already existed
and was already reviewed. The seven new tools are five reads and two that write only into the
Mac's own copy of an email that has not been prepared yet.

**The capability manifest went from zero to eighteen.** It was not that the manifest was
incomplete — it was **empty**, so `/health families` returned nothing and the settings sheet
could say nothing about the fourteen write operations that already worked. Fifteen of the
eighteen are for capabilities that already existed. Two coverage tests now make it a test
failure to add a write operation or a model-facing read tool that no family names, so the
manifest cannot go stale the way it went empty.

**And the tool block is a cost, not a win.** 3,057 bytes more on every model-path turn. The
arithmetic is written into `tests/test_registry.py` beside the ceiling — order editing about
1,050, the composer 2,085 measured, and the read language came out *smaller* than it went in.
It is also the worst case: `runtime.withheld_by_family()` takes a family's tools away when the
store or the connection cannot serve it, so a Mac missing a scope pays less. Set against it,
the family line on the prompt went from 420 characters a turn to 0 when everything is ready.

### The feature matrix

`make matrix` derives what can be reached and how from the registries rather than from a
document. It had a bug worth naming: `build()` iterated only the **core** family tuple, so not
one of Phase 3's fifteen families appeared in it — a matrix whose only job is to look complete
is worse than no matrix, and this one was quietly incomplete by fifteen rows. It now reads
`all_families()` and looks recipes up by family rather than by name (a Phase 3 family's recipe
is often named for what it does, so `order_email_draft` is answered by `order_email_reply`, and
looking it up by name reported "no fast path" for recipes that plainly have one).

| | Count |
| --- | --- |
| Operations in the matrix | 56 |
| Intent families | 34 — all 34 with a fast path |
| Families exercised by a golden scenario | 25 |
| Operations no scenario exercises | 24, listed by `uncovered()` rather than hidden |

The 24 uncovered ones are mostly pre-existing commands (`surface.expand`, `voice.cancel`,
`workflow.next`) and four read families that have unit tests but no scenario. `compose_rewrite`
is deliberately among them: the rewrite is asserted in `tests/test_compose.py`, where the words
handed to the model can be read without a customer's email going through a transcript.

---

## 13. Scope requirements, in one place

| Capability | Scope | On this machine | On the Mac |
| --- | --- | --- | --- |
| Order item editing | `write_order_edits` | `TEMPORARILY_UNAVAILABLE` — there is no token here, so the scope check cannot answer | `MISSING_SCOPE` until the scope is granted, naming it; `READY` after. The probe reads `access_scopes()` and never sends a mutation |
| Writing an email to any address | `gmail.compose` | `READY` | Already granted — no action |
| Delivery status | — | `DISCONNECTED` | `DISCONNECTED`. No carrier is integrated; this is a state, not a failure, and it is what stops the model attempting it |
| Everything else this pass added | — | `READY` | Reads and screen moves; no scope |

The distinction in those first two columns is worth keeping straight: `TEMPORARILY_UNAVAILABLE`
means *the question could not be asked*, and `MISSING_SCOPE` means *it was asked and the answer
was no*. Collapsing them would let a Shopify outage read as a permissions problem, and the
owner would go looking in the admin for something that was never wrong.

One new setting: `CROOKS_SHOP_COUNTRY_CODE`, default `GB`, which is how "international" means
*not this country*. No credential is touched by anything in this pass.

**How to grant `write_order_edits`:** it is a scope on the app the Mac's Admin API token belongs
to, so it is granted in the Shopify admin and the token re-issued. Until it is, the family says
so in the settings sheet, its tools are withheld from the model, and *"add a black hoodie to
this order"* is answered with the reason rather than attempted — which is the behaviour the
brief asks for: **do not claim the feature is ready when permission is absent.**

---

## 14. CROOKS Control — the Mac without Terminal (§28)

The brief's own words: *"The owner does not want to operate CROOKS OS from Terminal… This app
does not need extravagant visuals. It needs to remove Terminal from normal ownership."*

**It is built in two halves, deliberately, because this machine is Linux.** There is no
`swift`, no Xcode and no macOS here, so anything written in Swift could not be compiled, let
alone run. Rather than hand over a thousand lines of unverifiable UI, every decision the app
makes is in a Python command that IS tested here, and the Swift layer only draws its JSON.

### The tested half — `scripts/control.py`

| Command | What it answers |
| --- | --- |
| `crooks-control status` | The four-colour roll-up and fourteen rows, no network fetch. What the menu bar polls |
| `crooks-control plan` | Current and candidate SHA, fast-forward or not, dirty or not, deps or not |
| `crooks-control apply --yes` | The update, plus the three stages `crooks-update` has not got: verify the tablet route, mark successful, decide a rollback if it failed |
| `crooks-control rollback --yes` | Back to the last recorded good build |
| `crooks-control mark-good` | Record the running, healthy build as the one to return to |
| `crooks-control actions` | The thirteen buttons, each with its exact argv — so the app hard-codes no command |
| `crooks-control contract` | Every field every document returns, which a test holds the app's decoder against |

**The colours are earned, not asserted.** RED when nothing is answering or speech, Claude or
Shopify is down; BLUE while a test session is recording; AMBER read-only or degraded or no
tablet route; GREEN everything answering, changes ready, tablet routed. Each of the four is
driven from the right input by its own test, and one test asserts all four are reachable and
that there is no fifth.

**AMBER is the Mac's normal state today**, and that is the point: writes are off by default,
so every write family reads READ_ONLY and the menu bar says *CROOKS — Read only*. The owner
can see at a glance that the tablet cannot change anything.

**Mutation readiness is read from the capability table** (§2.3) off `/health`, not from a
second notion of whether writes are on — so it says MISSING_SCOPE and names the scope, the
same words the settings sheet uses.

### Two bugs found in `scripts/update.py` while extending it

- `git()` stripped its whole output, so an unstaged change on the **first** line of
  `git status --porcelain` arrived without its leading space and the path parser ate the first
  character. A hand-edited `.env` became `env`, which is not in `NEVER_TOUCH` — so the update
  **stopped when it should have proceeded**. Status letters are read positionally now, with
  ten parametrised cases and an end-to-end test.
- The `--quiet` flag was a module global that leaked between runs and silenced three unrelated
  tests. Restored in a `finally`, with a regression test.

### Verified here, independently of the agent's own tests

- **Nothing in CROOKS OS can invoke the updater.** Grepping `app/`, `config/`, `web/` and
  `experience/` for `scripts.update`, `crooks-update`, `scripts.control` and `crooks-control`
  returns nothing. It runs when George types it, and not otherwise.
- **A real-shaped credential in the environment does not reach the output.** Run with
  `CROOKS_SHOPIFY_TOKEN=shpat_…` set, `crooks-control status` contains zero occurrences of it.
- **The click is a rule of the command, not just the UI.** `rollback` without `--yes` returns
  `ok: false, next: blocked` and moves nothing.
- `crooks-control status` runs on this machine and correctly reports **RED — CROOKS
  Offline**, because no backend is running here.

### What is NOT verified, and must be read as such

**No Swift was compiled.** `Package.swift` and roughly 900 lines across four `.swift` files
have never been type-checked, built or seen on a screen. Expect the first build on the Mac to
surface compile errors, and read them as compile errors rather than design faults. The known
risks, named by the engineer who wrote them: `MenuBarExtra`'s label may render only part of an
`HStack`; the `@MainActor`/`Sendable` hops compile in Swift 5 mode but will warn or error under
Swift 6; `.onChange(of:)` uses the macOS 13 single-parameter form, deprecated on 14+.

Also unexercised here: `build.sh` (it parses, but has never assembled a `.app`), `launchctl`
(stubbed in every test — so the Restart button and the update's restart stage are unverified on
a real Mac), Tailscale (no CLI here, so the tablet-route check is stub-tested only), a real
`/health` document, and a real update end to end.

`logs/last_known_good.json` is **new in this build**, written 0600 in a 0700 directory, and
only by `apply` after `/health` read back healthy or by `mark-good`. It is deliberately never
written when the backend is not answering, when an essential check is down, or from a detached
HEAD — a "known good" that was never good is worse than none, because it is what a rollback
would choose.

### What the owner runs, once, on the Mac

```
cd ~/crooks-assistant/crooks-assistant
make update CHECK=1          # read what is coming; changes nothing
make update                  # fast-forward, deps, restart, verify /health
make commands                # installs the crooks-control wrapper
crooks-control mark-good     # record this build as the one to fall back to
xcode-select --install       # once per Mac, if `swift` is missing
make control-app             # builds and installs "CROOKS Control.app"
open "/Applications/CROOKS Control.app"
```

The menu bar should then read **CROOKS — Read only**, which is correct while
`CROOKS_WRITES_ENABLED` is false. If it cannot find the project, click *Project folder…* and
choose the directory holding `scripts/control.py`.

---

## 15. The brief's closing questions, answered directly

### 15.1 Which Phase 2 live failures are now impossible by regression test, and which remain possible?

**Impossible** — each held by a test that fails if the behaviour returns:

| The live failure | What makes it impossible |
| --- | --- |
| Two fingers on the orb produced a blank speech turn, six times | `scripts/browser/tablet.js` — a CDP two-finger spread asserts **zero** `/turn` posts and no hearing error |
| Split depended on a secret gesture | The same gate asserts a visible `Split` control reaching the same backend command |
| Tapping the other half changed who was listening, not what was on screen | `tests/test_split_workspaces.py` + a browser check that switching halves changes the visible cards |
| A half finished a slow turn with nothing on the tablet | `branch.ready(...)`, asserted in `tests/test_split_workspaces.py` |
| The dock was decorative unless already in an interaction | Four landing scenarios, each tapped from an idle tablet, no model |
| `commerce_query` failed three times with "sort by :" | The six reconstructed live attempts, each parsing or carrying a `schema_help` whose offered example is itself parsed |
| An email thread showed no linked order | `tests/test_graph.py` + the graph pack, and the thread says *why* it belongs |
| An automated carrier report was offered as a customer awaiting reply | The noise filter, now actually bound to our own address in production |
| The armed state was clipped 788 px below the finger | The tablet gate asserts it unclipped, on the card, with a 44 px Cancel |
| A failed customer read was drawn as "no customer" | `tests/web/ui.test.js` + `tests/test_context.py` |
| Six gesture collisions classified as `STT_ERROR` | `tests/test_analyser.py::test_a_a_gesture_that_ended_the_recording_is_not_a_failure_of_speech` |
| "Potential new actions: none" while three were asked for aloud | Two analyser tests, driven from the capability table |
| "Refund status" read as a requested mutation | `tests/test_analyser.py::test_d_a_noun_or_a_state_is_not_a_requested_mutation` |
| 27 command events unread by the report | `tests/test_analyser.py::test_e_the_report_reads_the_command_and_navigation_events` |
| The 35-second compound turn | One turn now (§11.5), asserted by `compound()` in three scenarios |

**Still possible, and honestly so:**

1. **A slow model turn.** Anticipation removes *reads* from the critical path; `prose_wait_ms`
   was unchanged in the bench, and §25 names prose as the number to attack. A NORMAL-lane
   question still waits on Claude. What changed is how many questions reach that lane.
2. **A mis-heard address that looks plausible.** The composer marks a dictated value
   `uncertain` and refuses to stage it, so it cannot be sent unseen — but only the owner can
   tell a wrong-but-valid address from a right one.
3. **Anything requiring a scope the store has not granted.** Order editing needs
   `write_order_edits` and will say so rather than work.
4. **A tablet-side failure no browser can reproduce** — a real thumb, a real microphone, real
   Tailscale. §8 lists what to test on the glass, in order.

### 15.2 Which capability requests still cannot be performed, and why?

| Asked for | State | Why |
| --- | --- | --- |
| Add an item to an order | **Built, needs a scope** | `write_order_edits` is not granted. The family says so and withholds its tool from the model |
| Create a discount code | **Built** | Reachable by voice (§11.3 fix) and by the model; needs `write_discounts` + `read_discounts` |
| Create an order | **Built** | Voice-initiated as §11 asks; needs `write_draft_orders` + `read_draft_orders` |
| Store credit | **Built, conditional** | Needs the grant AND the store to have store credit — a per-store Shopify setting. The probe now asks a real question rather than reporting READY-unproven |
| Abandoned **checkouts** | **Built** | Reads, ranks by occurrence, windows by date. No new scope |
| Abandoned **carts** | **Impossible** | Shopify's Admin API has no cart resource. Said in the tool description, the result, both cards, every spoken line and the family's `what`, from one constant so the five cannot drift |
| Delivery status ("has it arrived?") | **Impossible today** | No carrier is integrated. DISCONNECTED, and the model is told not to attempt it |
| Shipping labels / tracking from a provider | **Adapter only** | Easyship is not integrated and there is no credential. Fixture implementation, DISCONNECTED state, and a test that nothing can report "checked Easyship" unless it did |
| Returns, exchanges, replacements, resends | **Contracts only** | Four scopes ungranted and the mutations deliberately unwritten. A test fails if any such mutation is ever registered |
| Store credit **removal** | **Not built** | `storeCreditAccountDebit` is not a reviewed mutation, so a credit cannot be taken back from here. The card says so |
| Editing or deactivating an existing discount | **Not built** | The card says so |
| A new customer during order creation | **Not built** | An unknown or ambiguous name is refused with "make the customer in Admin first" |
| "Send it instead" spoken | **Touch path only** | The fast lane cannot stage, by construction. Spoken, it draws the composer with **Send** on it; the gesture stages |
| A tablet button for "New order" / "New discount code" | **Not built** | Both are reachable by voice and by the model; there is no tap route yet |

### 15.3 Which need new Shopify permissions?

Six scopes are named by this build and **not granted**. `SHOPIFY_SCOPES.md` carries the table;
in priority order:

| Scope | Unlocks | Without it |
| --- | --- | --- |
| `write_order_edits` | Adding an item to an order | MISSING_SCOPE, named, tool withheld |
| `write_discounts` + `read_discounts` | Discount codes. Both: a family that cannot say whether a code is taken is not ready | MISSING_SCOPE, and the collision read still works on `read_discounts` alone |
| `write_draft_orders` + `read_draft_orders` | Order creation. Both: a change that cannot be verified is not offered | MISSING_SCOPE, nothing drafted |
| `write_store_credit_account_transactions` + `read_store_credit_accounts` | Store credit | MISSING_SCOPE, or NOT_SUPPORTED_BY_STORE if the grants are there and the store is not |
| `write_returns`, `read_returns`, `write_merchant_managed_fulfillment_orders` | Returns and resends — **not needed yet**, since the mutations are deliberately unwritten | NOT_IMPLEMENTED, scope named |

Not a scope: `CROOKS_EASYSHIP_TOKEN`, and an Easyship HTTP client that this build does not
contain.

### 15.4 Does any feature weaken the mutation security model?

**No, and three of the changes strengthen it.** Four new write operations were added
(`order_edit_add_line`, `discount_code_create`, `draft_order_complete`,
`store_credit_credit`), all through the action engine that already existed — the model or a
touch command proposes, the Mac stores the exact immutable arguments, the tablet posts
identity only, the precondition is re-read immediately before the write, success means
VERIFIED by authoritative re-read, and an unknown write fails closed.

The three that strengthen it:

1. **Per-branch proposal attribution.** `session.acting_branch` was one field for both halves.
   With two halves thinking at once the engine could have stamped the left half's proposal
   with the right half's id. The branch now travels on the task the tool call runs in.
2. **The gate's id rule made the arbitrary recipient safe for free.** A write needs at least
   one issued id and an email address can never be one, so `to` is admitted only beside a
   `compose_id` the Mac minted — an arbitrary address can only be staged from a composer whose
   card the owner has already read.
3. **Tools are withheld by capability state.** A family that is DISCONNECTED,
   NOT_IMPLEMENTED or NOT_SUPPORTED_BY_STORE has *no tools offered to the model*, and
   MISSING_SCOPE or READ_ONLY withholds the write tools. The model cannot attempt what the
   store would refuse.

One thing to watch, stated as a risk rather than a defect: the composer is the first card with
**editable fields**. A keystroke posts a field *name* and a value into the Mac's own copy, and
the execution arguments are still built from that copy on the Mac when a gesture asks for
them — so the tablet is not the data authority. But it is the largest surface the tablet has
ever had for putting text into something that will later be staged, and it deserves the
Samsung test in §8 before it is trusted with a real recipient.

---

## 16. The final test set, as run

Every number here is from one sequence on the final tree, not collected from different points
in the pass.

| | Result |
| --- | --- |
| `ruff check app config scripts tests experience bench` | clean |
| `pytest tests` | **2,040 passed, 2 skipped, 0 failed** (3m05s) |
| The two skips | `tests/test_gmail_tools.py:175` no Gmail token; `tests/test_shopify_tools.py:190` no Shopify Keychain entry — printed, not hidden |
| `make experience` (one shared harness, as a person runs it) | **55/55 scenarios** |
| Browser gate, 800 × 1280 and 601 × 889 | **61 checks, 0 failures** |
| `node --test` × 4 (renderer, folding, service worker, telemetry) | **115 passed, 0 failed** |
| `node --check` on `app.js`, `ui.js`, `telemetry.js`, `sw.js` | parses |
| `make bench-lanes` | **17 of 17 rows answered with no model call** |
| Screenshots | 13, retaken against this tree, 7 at 800 × 1280 and 6 at 601 × 889 |

### The one defect I got wrong twice, written down because it is the useful part

`make experience` runs every scenario through **one** harness; `tests/test_experience.py` builds
one per test. The two disagreed, and pytest is the runner that says the build is fine while
`make experience` is the one a person runs on the Mac.

- **First time:** three scenarios failed in the shared runner and passed under pytest, reading
  the previous scenario's calculation log. Fixed by clearing the fields — **from the runner**,
  in a different file from the declarations. Green.
- **Second time, the same day:** two agents added `drafts`, `drafts_by_id`, `draft_number` and
  an anticipation layer. The reset went stale, `make experience` fell to 52/55, and an
  order-creation scenario failed with a previous scenario's draft in its detail. The identical
  defect in a new field.
- **The fix that holds** changes the shape rather than the list: `FixtureShopify.forget_scenario()`
  sits under its own field declarations, the anticipation layer is replaced rather than partly
  reset, the tiered cache is emptied — because a read already held is one the layer rightly
  declines to predict, which reads as "nothing was predicted" in the next scenario — and the
  runner asks instead of reaching in.
- **The guard** is what makes it stop: a used-then-forgotten shop is compared field by field
  against a fresh one, so a field recorded per scenario and not cleared fails in the file that
  adds it. Proven able to fail — removing one `.clear()` makes it name exactly `['drafts']`.

The lesson worth keeping: a reset that enumerates somebody else's fields is a defect with a
delay on it, and "the suite is green" is not the same claim as "the thing a person runs is
green".

---

**Final SHA `461a8b4`**, on `claude/crooks-assistant-build-lgxlau`.

**Not deployed.** The running build is untouched, no real Shopify or Gmail write was made from
this machine at any point, and none of the deployment steps in §6 has been run. They are yours
to run when you have tested the branch on the Samsung.
