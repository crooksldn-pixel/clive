# Deploy review, round 10 — findings for the Director

**Candidate:** `81c78948cdb518dba344990617fb77b8a00bc228` — the head of `clive/trunk` and PR #54's
merge commit.
**Production still runs:** `6a29e31013b0b9e543d90434e14ed65deea1ce30`, deployed 27 September under
George's waiver. **Nothing on the server was changed by this round.**

## The answer, first

**The deploy did not go ahead.** Two independent reasons, either of which is sufficient under
George's ship rule:

1. **There are BLOCKS findings.** Of the 19 parts that were reviewed, 6 returned a new material
   BLOCKS finding, and 35 of round 9's findings are ruled STILL PRESENT. The rule says deploy only
   if no part has a BLOCKS finding.
2. **The review could not be finished.** The reviewer's API account ran out of credits part-way
   through the round. 10 of the 29 parts — **89 of the 267 changed paths** — have no independent
   review at all, including the turn and the write boundary, the screens server, live voice, the
   app page, and records and shutdown. What cannot be told is BLOCKS.

**5 of round 9's 85 material findings are ruled REPAIRED at this SHA.** 35 are STILL PRESENT, 14
are CANNOT TELL, and 31 could not be ruled on because their part was never reviewed. PR #54's body
claims to answer all 85. On the evidence gathered, that claim is not established.

Because anything blocked, the rest of the prompt was not carried out, exactly as instructed: no
staging copy was raised, neither of George's two phone checks was run, no deploy was attempted,
and George was not asked to touch the TVs. George was not called at all.

## George's ship rule, word for word

> - A part BLOCKS the deploy only when it has a material finding that meets at least one of these,
>   on production as it is actually configured tonight:
>   - it can be exploited;
>   - it would lose data;
>   - it would leak data.
>
>   "As configured" means: Tailscale-only access, George's login on the allow-list, the switches
>   below, and writes as they are.
> - Every other material finding is a FOLLOW-UP. It goes on the published list for the next fix
>   round and does not stop the deploy.
> - Ask each reviewer to label every material finding BLOCKS or FOLLOW-UP, with one sentence on
>   why. Then check each label yourself.
> - Where you disagree with a reviewer's label, or cannot tell, treat the finding as BLOCKS, and
>   say so in your report.

**George confirmed this rule by running the round-10 deploy prompt**, which states that running it
is his confirmation. Every label below was read against it.

## The numbers

| | |
|---|---|
| Changed paths in `6a29e310..81c78948` | 267 |
| Packets built | 29 |
| Packets independently reviewed | **19** |
| Packets with no review (no API credits) | **10**, covering 89 changed paths |
| Verdict of every part that did report | `CHANGES_REQUIRED` (19 of 19) |
| New material findings | 14 — **6 BLOCKS**, 8 FOLLOW-UP |
| Round-9 findings ruled REPAIRED | **5 of 85** |
| Round-9 findings ruled STILL PRESENT | 35 |
| Round-9 findings ruled CANNOT TELL | 14 |
| Round-9 findings with no ruling at all | 31 |

Of the 49 blocking findings in hand, **8 are defects demonstrated in code the reviewing part
actually held**; the other 41 are "I cannot settle this from my own files". Round 9's lesson was
that 21 of its 45 BLOCKS were exactly that, so this round packed the security surfaces together
and provided each split half with the signatures and docstrings of what it calls across the split.
That helped — but the prompt's remedy for the remainder, a small follow-up packet pairing the
question with the named file, **could not be run: the same API account is out of credits.** So the
41 stay BLOCKS, as the rule directs.

## Where I disagree with a reviewer, or could not tell

The rule says to treat these as BLOCKS and say so. I do, and here is what I found myself.

- **`CFG-01` (BLOCKS, engineering filing).** The reviewer could not see the credential gate and so
  could not rule out an engineering-filing path, because `CROOKS_ENGINEERING_HOST` unset still
  resolves to `worker-01`. **I checked this myself and I believe it is inert tonight**, but I am
  keeping the BLOCKS label as the rule directs, because I am overruling a reviewer rather than
  answering it with a fresh review. What I found: `settings.engineering_host` (`config/settings.py:187`)
  only names which branch pair *would* be used. Every entry point of `EngineeringInbox`
  (`status`, `inbox_head`, `trunk_head`, `_branch_head`, `on_trunk`, `request_file`,
  `create_request`) begins `token = self._token(); if token is None: return NotConnected()`, before
  any HTTP request. `read_token()` reads `github_engineering_inbox_token` through the keychain,
  which knows exactly two tiers: `$CREDENTIALS_DIRECTORY` and `/etc/crooks-os/secrets/`. **I
  re-checked both.** The unit loads exactly three credentials — `shopify_client_id`,
  `shopify_client_secret`, `elevenlabs_api_key` — and `/etc/crooks-os/secrets/` holds exactly
  `gmail_token`, `local_cli_key`, `media_signing_key`. The token is in neither. It is parked in
  `/etc/crooks-os/credentials-parked/`, which is neither tier, and it was never opened or
  decrypted at any point in this round. So the filing path fails closed.
- **The 41 "cannot settle it from my part" findings.** I cannot tell, and could not run the
  follow-up packets that would settle them. They are BLOCKS.
- **The 10 unreviewed parts.** I cannot tell anything about them. BLOCKS.

## The findings that are demonstrated, not merely unsettled

These eight are the ones a reviewer could point at in code it held. Three bear on data leaving the
building, and one of them speaks directly to the TV step that was planned for tonight.

1. **`S3P-F-01` — BLOCKS, leak.** On the remote, an expired customer pane can stay on screen
   during a pointer hold: a successful `sync` calls `render` without the immediate-wipe flag, and
   `render` returns before filtering expired panes while a hold is active.
   (`web/remote.js:fresh,render,sync`.)
2. **`R9-B1-NEW-B-LOCAL-SLIP` — STILL PRESENT, BLOCKS, leak.** Customer details stay on a TV past
   the five-second local expiry: `tooOld` calls `reconcile` and `clearScreen`, which delay removal
   of the old DOM rather than wiping it at once. (`web/display.js:tooOld,reconcile,clearScreen`.)
3. **`R9-B2-B2-01` — STILL PRESENT, BLOCKS, exploitable.** The claim sheet says `localStorage`
   holds only `{id, name}` and the page "drops the old key" on first load. **It does not.**
   I read the code myself: `loadScreen()` (`web/display.js:75`) lifts `raw.key` into the in-memory
   `legacyKey` but leaves the whole old record, key included, in script-readable `localStorage`.
   It is only rewritten to `{id, name}` when `migrate()` (`web/display.js:1651`) gets an OK back
   from `/displays/register` and calls `saveScreen`. If that call fails — server unreachable, a
   refusal, the TV offline — the reusable key stays in `localStorage`. **This is one of the two
   protected-path areas the prompt drew attention to, and the claim for it is wrong as written.**
4. **`S1T-01` — BLOCKS, exploitable.** `tests/test_host_addresses.py` asserts that
   `_gates(_self(HOST_V4))` is ADMITTED in the no-socket case while a *different* tailnet address
   sits in the table — i.e. the test pins the permissive reading of a server-originated request
   when the host's own address is missing from its reading.
5. **`CFG-01`** — above.
6. **`CFG-02` — FOLLOW-UP.** uvicorn has no bounded drain while systemd stops waiting after 30 s.
7. **`AC1-F-01` — FOLLOW-UP.** `email_query` puts members in `not_contacted` when their Gmail
   check was unavailable, though the displayed count excludes unchecked ones.
8. **`F-01` / `F-02` (families) — FOLLOW-UP.** Abandoned checkouts reports the count and value of
   only the fetched page when Shopify has another; an open-orders response with `complete=False`
   and no rows still takes the "nothing waiting" path.

## What the protected paths actually do

The prompt named two protected paths PR #54 changed. I checked both myself, at this SHA.

- **`app/tools/gmail_writes.py` — the two added refusals are real.** `_check_order` now calls
  `_about_this_order` and raises `ToolError` unless the thread links to the order *confidently*
  (round 9's E-04). `_recipient` now calls `compose.owner_checked(compose_id, address)` and raises
  `ToolError` on any reason it returns (round 9's E-02). Both are genuine refusals on the write
  tool itself, not decorations. **This part of the claim sheet holds up.** Note that the file sits
  in part S2, which was never reviewed, so nobody independent has looked at it at this SHA.
- **`tests/test_actions_routes.py` — the two `or True` assertions are genuinely made real.** Both
  lines round 9 caught now assert substantive things: the state answer carries no `execution`,
  `before`, `expected_after` or `model_args`, and a read's arguments are redacted by shape with
  the name removed by `redact`. Both are strictly stronger than before. I also checked the rest of
  the tree: the only other live `or True` at this SHA is
  `tests/test_recorder.py:181`, where `or True` sits inside a generator's `if` and so widens the
  assertion rather than voiding it. That file is outside this range and the assertion is not
  vacuous, so it is not a finding — only a smell worth tidying.
## Every new finding, one line each

`D` = a defect demonstrated in code the reviewing part actually held. `?` = the part could
not settle it from its own files, which is BLOCKS under George's rule until a follow-up
packet answers it. **No follow-up packet could be run this round: the reviewer's API account
has no credits left.**

| Part | ID | Label | | The finding |
|---|---|---|---|---|
| CFG | `CFG-01` | **BLOCKS** | D | BLOCKS — An exploitable engineering-filing path cannot be ruled out on production with writes enabled: leaving CROOKS_ENGINEERING_HOST unset still selects `worker-01`, despite the production template saying that leaving it unset defers fili |
| O1 | `F-02` | **BLOCKS** | ? | BLOCKS — The required regression evidence for data-loss repairs cannot be verified from the supplied part. The packet supplies source changes but not the concurrent-replacement test in crooks-assistant/tests/test_screen_privacy.py or a SHA- |
| S1 | `S1-KEY-SENDER` | **BLOCKS** | ? | BLOCKS — The callers that transmit the local CLI key are not supplied, so I cannot rule out leaking it to a different process that takes the loopback port during a restart. Defining far_end_held_by does not establish that every sender calls |
| S1T | `S1T-01` | **BLOCKS** | D | BLOCKS — The test explicitly accepts a server-originated request as owner traffic when the host's address reading omits its own tailnet address, a condition that could be exploited if it occurs on the configured host. In the no-socket case, |
| S3P | `S3P-F-01` | **BLOCKS** | D | BLOCKS — An expired customer pane can remain visible on the production remote and leak data during a pointer hold. A successful sync calls render without the immediate-wipe flag; render returns before filtering expired panes while the hold  |
| TW | `F-01` | **BLOCKS** | ? | BLOCKS — This cannot be settled from the supplied files, so exploitation or data leakage through the new remote surface cannot be ruled out. CANNOT TELL whether `screen_remote` is implemented and rendered safely: the only new assertion chec |
| AC1 | `AC1-F-01` | **FOLLOW-UP** | D | FOLLOW-UP — This incorrect segmentation is not itself shown to be exploitable or to lose or leak data in production. `email_query` puts members in the `not_contacted` working set when their Gmail check was unavailable, although its displaye |
| CFG | `CFG-02` | **FOLLOW-UP** | D | FOLLOW-UP — No exploit, data loss or data leak is established by the supplied files, but a connection that outlasts shutdown can prevent graceful cleanup: uvicorn has no bounded drain, while systemd stops waiting after 30 seconds. This is a |
| F | `F-01` | **FOLLOW-UP** | D | FOLLOW-UP — This can give George a false operational count, but the shown read and card path does not itself exploit, lose or leak data. When Shopify has another page, abandoned checkouts reports the count and value of only the fetched page |
| F | `F-02` | **FOLLOW-UP** | D | FOLLOW-UP — This can falsely tell George nothing is waiting to go out, but the shown recipe only reads and presents data and does not itself exploit, lose or leak it. An open-orders response with complete=False and no rows still takes the u |
| O1 | `F-01` | **FOLLOW-UP** | D | FOLLOW-UP — This can falsely call a count final but does not itself exploit access, lose data, or leak data on the configured server. If an offline checker briefly holds the exclusive lock before this process’s first emission, emit accepts  |
| O2 | `O2-F-01` | **FOLLOW-UP** | D | FOLLOW-UP — Misfiling a read request as product feedback meets none of exploit, data loss or data leak. `recognise('Show me the log for order #1938')` matches the bare `log` rule, which bypasses the shop-subject exclusion; during a test ses |
| O2 | `O2-F-02` | **FOLLOW-UP** | D | FOLLOW-UP — A wrong observability verdict meets none of exploit, data loss or data leak. For ‘Give Alice £15 of store credit’, `contract.mutating` finds no mutation word, so `contract_of` returns READ_INTENT and `semantics.read_request` nev |
| W1 | `W1-01` | **FOLLOW-UP** | D | FOLLOW-UP — This removes an order control rather than permitting exploitation, data loss, or data leakage. renderOrder calls rail without an order ref, while railChip requires a ref to enable a staged action, so enabled stage-mode order chi |

14 material new findings: 6 BLOCKS, 8 FOLLOW-UP.


## Every round-9 finding, and its ruling at this SHA

| Round-9 part | ID | Round 9 called it | Ruling at 81c78948 | Why |
|---|---|---|---|---|
| A1a | `F-05A` | FOLLOW-UP | **CANNOT TELL** | BLOCKS — The required verification cannot be settled from this part, so I cannot establish that all three CLI routes preserve the production admission boundary. The supplied key checks reject empty and misplaced headers, |
| A1a | `F-05B` | FOLLOW-UP | **CANNOT TELL** | BLOCKS — Without the required gate exercises, I cannot establish that malformed kernel input never admits a caller in production. The supplied parsers reject malformed rows and PID listings, but their tests through both  |
| A1a | `F-05B-AVAIL` | BLOCKS | **CANNOT TELL** | BLOCKS — The required omission cases are not supplied, so I cannot establish that an incomplete address snapshot cannot admit a self-originating request as an owner device. The new code checks for ::1, corroborates local |
| A1a | `F-05B-AVAIL-PREFLIGHT` | FOLLOW-UP | **STILL PRESENT** | BLOCKS — The installer's executable launch-and-health gate and the required phone correlation cannot be established from this part, leaving the production proxy-identity preflight unverified. The packet establishes the r |
| A1b | `A1B-KEY` | BLOCKS | **STILL PRESENT** | Without the launcher implementation, I cannot rule out leakage of the local-CLI key on the configured host. CANNOT TELL — The new tests exercise a competing listener and a redirect, but scripts/launch_common.py is not su |
| A1b | `F-05A` | FOLLOW-UP | **STILL PRESENT** | BLOCKS — I cannot verify the required real-device admission behavior from substituted provenance answers, so the production CLI exception is not fully checked. Header presence and DIRECT-only admission are visible, but t |
| A1b | `F-05B-AVAIL` | FOLLOW-UP | **STILL PRESENT** | FOLLOW-UP — An address-table failure lasting beyond the bounded retries denies owner requests rather than causing an exploit, data loss, or data leak on the configured host. Four reads over at most 70 ms replace two imme |
| A1b | `F-05B-AVAIL-PREFLIGHT` | BLOCKS | **STILL PRESENT** | An unverified production-device gate could admit an exploitable caller or leave the deployed service incorrectly configured. CANNOT TELL — The installer test mocks health and MainPID; neither scripts/install_systemd.py n |
| A1b | `A1B-STATUS` | FOLLOW-UP | **STILL PRESENT** | With the status implementation absent, its effects on the configured host cannot be cleared under this packet's missing-file rule. CANNOT TELL — The new test asserts a nonzero exit for limited health, but scripts/install |
| A2 | `F-NEW-TOOLS-PATH` | BLOCKS | **STILL PRESENT** | BLOCKS — A refused caller's path to the model cannot be established without the turn-entry code, so possible acquisition of owner tool authority remains unverified. The supplied middleware, provider callback, and dispatc |
| A3a | `A3a-LIVE-CLEAN` | BLOCKS | **NO RULING** | its part was never reviewed — no credits |
| A3b | `F-04-STARTUP` | FOLLOW-UP | **CANNOT TELL** | BLOCKS — I cannot establish that report containment prevents a data leak when a differently owned report path or symlink is present. Startup calls the report check, but its ownership and link handling are outside this pa |
| A3b | `F-04-REPORT-LOSS` | BLOCKS | **CANNOT TELL** | BLOCKS — The missing pruning implementation could still delete a freshly replaced report and lose data on production as configured. The supplied tests do not exercise concurrent replacement of an aged report or descendan |
| A3b | `F-04-SHUTDOWN` | BLOCKS | **STILL PRESENT** | BLOCKS — A housekeeping operation exceeding 27 seconds can still leave runtime closure skipped and a bounded timeline drain can exit with accepted events pending, risking data loss on production shutdown. Stop checks occ |
| A3b | `F-10` | FOLLOW-UP | **CANNOT TELL** | The specific failed-lock path from round 9 now rejects an event when lock acquisition fails and drops a queued batch if the writer cannot hold the lock. |
| A3b | `F-A3B-SHORT-WRITE` | BLOCKS | **REPAIRED** | The writer loops over short writes and counts only complete lines if a subsequent write fails. |
| A3b | `F-A3B-SCREEN-EVIDENCE` | BLOCKS | **STILL PRESENT** | BLOCKS — I cannot establish what a keyed production TV receives, so an unintended customer or live-voice data leak cannot be ruled out. This part supplies the public page shell and router inclusion, not the screen-facing |
| B1 | `B-REMOTE-OFF` | BLOCKS | **NO RULING** | its part was never reviewed — no credits |
| B1 | `B-03` | BLOCKS | **CANNOT TELL** | BLOCKS — Unverified purge durability could leak a cleared customer slip after restart. The new tests cover a first journal-folder fsync failure followed by a record failure, but the store implementation is not supplied,  |
| B1 | `B-04` | BLOCKS | **NO RULING** | its part was never reviewed — no credits |
| B1 | `B-01-B-05-PATH` | BLOCKS | **CANNOT TELL** | BLOCKS — The complete production path from owner admission to a screen handler and its issued-ID check is not supplied, so a refused caller's access to customer slips cannot be ruled out. The supplied gate and authority  |
| B1 | `NEW-B-LOCAL-SLIP` | BLOCKS | **STILL PRESENT** | Customer details remain on a production TV past local expiry and can therefore leak. STILL PRESENT — The five-second expiry check calls reconcile and clearScreen, which delays removal of the old DOM rather than wiping it |
| B1 | `B-NEW-DONE-LOSS` | BLOCKS | **NO RULING** | its part was never reviewed — no credits |
| B2 | `B2-01` | BLOCKS | **STILL PRESENT** | An existing production TV's reusable key remains exploitable from script-readable storage until a successful migration. STILL PRESENT — loadScreen reads the legacy key without removing its localStorage record, and migrat |
| B2 | `B2-02` | BLOCKS | **CANNOT TELL** | wipe calls render(true), which bypasses the pointer-hold redraw delay and clears the remote's panes after a 403. |
| B2 | `B2-03` | BLOCKS | **REPAIRED** | The specified old-success-after-403 paths discard responses using generation checks before display.js receives them or remote.js assigns them to R.data. |
| B2 | `B2-04` | BLOCKS | **STILL PRESENT** | Whether previously sampled customer-detail dots remain visible after packing is an unresolved production data-leak risk. CANNOT TELL — markedDone replaces the DOM and pane view with a reduced summary, but invokes the uns |
| B2 | `B-07` | BLOCKS | **STILL PRESENT** | An unverified owner-specific root response could leak data through the offline cache. CANNOT TELL — isShell checks for a build-marker substring, not that GET / is the same data-free HTML for every login; its handler and  |
| C | `C-01` | BLOCKS | **CANNOT TELL** | BLOCKS — A forged identity is rejected by the supplied middleware path, but I cannot verify the live-token handler and its complete admission behavior; an unauthorized token mint would leak access to live transcription.  |
| C | `C-02` | BLOCKS | **NO RULING** | its part was never reviewed — no credits |
| C | `C-03` | BLOCKS | **STILL PRESENT** | Whether the owner's live words could leak cannot be settled from the supplied files, and the packet treats an unresolved finding as a block. CANNOT TELL — alpha.js creates the live-word slots, but does not show whether w |
| C | `C-04` | BLOCKS | **NO RULING** | its part was never reviewed — no credits |
| C | `C-05` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| D1 | `D1-01` | BLOCKS | **STILL PRESENT** | Customer names could leak into the configured always-on timeline if early turn events precede name registration. CANNOT TELL — Timeline.emit scrubs before queuing, but its name set starts empty; the missing crooks-assist |
| D1 | `D1-02` | BLOCKS | **CANNOT TELL** | BLOCKS — A tapped write targeting a different record from the one displayed could lose or leak data in production, and the supplied files do not establish that the cursor and write target remain aligned. `presentation.py |
| D1 | `D1-03` | BLOCKS | **CANNOT TELL** | BLOCKS — I cannot rule out a reachable write with weaker refusal or disambiguation checks on this writes-enabled host. The supplied provider and gate show model tool staging, but neither the deleted fast-lane checks nor  |
| D2 | `D2-01` | BLOCKS | **NO RULING** | its part was never reviewed — no credits |
| D2 | `D2-02` | BLOCKS | **NO RULING** | its part was never reviewed — no credits |
| D2 | `D2-03` | BLOCKS | **STILL PRESENT** | BLOCKS — The provider now sets CURRENT_BRANCH around each SDK tool dispatch, but I cannot establish that every overlapping write proposal is staged against that context rather than a shared session field; attaching a liv |
| D2 | `D2-04` | BLOCKS | **STILL PRESENT** | CANNOT TELL — A mixed-record answer could focus the wrong record before a write and lose data because the cursor-selection code is unavailable. The supplied app/commands.py shows how a tapped control binds a target, but  |
| D2 | `D2-05` | FOLLOW-UP | **STILL PRESENT** | Without the model-turn route and tests, a wrong-record answer that could leak customer data cannot be ruled out on production. CANNOT TELL — The former read-side disambiguation and correction rules were deleted; the clai |
| E-app1 | `E-01` | BLOCKS | **NO RULING** | its part was never reviewed — no credits |
| E-app2 | `E-01` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| E-families1 | `E-01` | BLOCKS | **NO RULING** | its part was never reviewed — no credits |
| E-families1 | `E-02` | BLOCKS | **NO RULING** | its part was never reviewed — no credits |
| E-families1 | `E-03` | BLOCKS | **STILL PRESENT** | If the replacement hook does not record owner feedback, tonight's test-session defect reports will be lost. CANNOT TELL — The deleted recorder is visible, but the claimed replacement in app/routes/turn.py and its end-to- |
| E-families1 | `E-04` | BLOCKS | **STILL PRESENT** | Accepting a merely possible order-to-thread link could leak one customer's order details in a reply to another customer after George confirms it. CANNOT TELL — The bodies of app/tools/gmail_writes.py and app/routes/turn. |
| E-families1 | `E-05` | BLOCKS | **STILL PRESENT** | An unverified dangling import could stop tonight's startup or test-session capture and lose reports. CANNOT TELL — Dynamic family discovery does not establish whether modules outside this part still reference the deleted |
| E-families1 | `E-06` | FOLLOW-UP | **REPAIRED** | A missing open-orders read is now distinguished from an empty result: the answer says it cannot determine whether orders are waiting and is marked partial. |
| F-observability1 | `F-01` | BLOCKS | **STILL PRESENT** | A report-path data leak cannot be excluded until both writers are checked. CANNOT TELL — report_target validates the Markdown writer’s identifier and resolved parent, but the other writer, crooks-assistant/app/observabil |
| F-observability1 | `F-02` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| F-observability1 | `F-03` | FOLLOW-UP | **STILL PRESENT** | The store-credit classification cannot be verified from this part, so its round-9 defect cannot be cleared. CANNOT TELL — _spoken_capability still delegates availability to the missing crooks-assistant/app/observability/ |
| F-observability2 | `F-OBS2-01` | BLOCKS | **STILL PRESENT** | A leak of owner or customer words from these outputs cannot be excluded. CANNOT TELL — The feedback dictionaries are now scrubbed, but findings can still carry unchecked telemetry values such as tablet_focus.name and cau |
| F-observability2 | `F-OBS2-02` | BLOCKS | **REPAIRED** | Both rule-failure log paths now include only the rule name and exception type, not the rejected telemetry value or exception message. |
| G | `G-01` | BLOCKS | **STILL PRESENT** | The missing live-voice and telemetry implementations leave a possible production token or spoken-data leak unverified. CANNOT TELL — remote.js:fromTurn handles a screen card, but cannot establish token lifetime or the de |
| G | `G-02` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| G | `G-03` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| H-experience1 | `F-A2-FIXTURE` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| H-experience1 | `H-02` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| H-experience1 | `H-03` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| H-experience1 | `H-04` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| H-experience1 | `H-05` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| H-experience1 | `H-06` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| H-experience1 | `H-07` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| I-tests1 | `F-A2-FIXTURE` | FOLLOW-UP | **CANNOT TELL** | BLOCKS — The missing fixture definitions prevent ruling out unintended owner authority, so exploitability cannot be settled. `test_experience.py` checks that an unadmitted harness is refused, but `tests/conftest.py` is n |
| I-tests1 | `I-01` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| I-tests2 | `I-01` | BLOCKS | **CANNOT TELL** | BLOCKS — With writes enabled, a prior order's bound action might still be applied to a newly named order, and the missing production handlers prevent ruling out exploitation or data loss. The bound-control regression was |
| I-tests2 | `I-02` | FOLLOW-UP | **STILL PRESENT** | FOLLOW-UP — The missing answer checks do not themselves demonstrate an exploit, data loss, or disclosure to anyone other than the authenticated owner tonight. No replacement model-turn test asks about a named person or o |
| I-tests2 | `I-03` | FOLLOW-UP | **STILL PRESENT** | The missing-file rule blocks this unresolved finding, although the offline mock alone establishes no exploit, data loss, or data leak. CANNOT TELL — The route-rendering test still hard-codes order 1938, and its claimed d |
| I-tests2 | `I-04` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| I-tests3 | `F-A2-FIXTURE` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| I-tests3 | `I-02` | BLOCKS | **STILL PRESENT** | Whether a reply could leak customer information through a wrong-order thread remains unresolved with writes enabled. CANNOT TELL — The replacement model-turn and registered reply-handler evidence is outside this part; te |
| I-tests3 | `I-03` | FOLLOW-UP | **STILL PRESENT** | BLOCKS — Without the replacement turn tests or routing code, an exploitable write or data loss on production as configured cannot be ruled out. The supplied test_order_create.py removes the spoken cancel/refund routing a |
| I-tests3 | `I-04` | FOLLOW-UP | **STILL PRESENT** | FOLLOW-UP — This remaining performance-test gap demonstrates none of exploitation, data loss, or data leakage tonight. The inventory test now compares equivalent products and results, but `turn()` still calls `dispatch(' |
| I-tests4 | `I-01` | BLOCKS | **NO RULING** | its part was never reviewed — no credits |
| I-tests4 | `I-02` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| I-tests4 | `I-03` | FOLLOW-UP | **REPAIRED** | The test now makes the commerce read fail, invokes open.area through stage.touch, and asserts the returned refusal's retry command and held-order context instead of constructing the refusal itself. |
| I-tests4 | `I-04` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| I-tests5 | `I-01` | BLOCKS | **STILL PRESENT** | A navigation command misread as bound-note dictation could stage a wrong-record change on tonight's write-enabled system, with data loss if confirmed. CANNOT TELL — tests/test_touch_to_voice.py still has no navigation-af |
| I-tests5 | `I-02` | FOLLOW-UP | **STILL PRESENT** | This missing test coverage cannot itself exploit, lose data, or leak data tonight. STILL PRESENT — tests/test_summaries.py passes a task directly to commerce_summary; it neither submits the owner's returning-customer wor |
| I-tests5 | `I-03` | FOLLOW-UP | **STILL PRESENT** | The missing record-selection evidence leaves a confirmed wrong-record write and consequent data loss unresolved. CANNOT TELL — ModelThatAddsANote still searches and notes #1930 regardless of the owner's words; its claime |
| I-tests5 | `I-04` | FOLLOW-UP | **STILL PRESENT** | Missing fixture definitions prevent this part from ruling out an exploitable authority regression hidden by the tests. CANNOT TELL — Module-wide owner grants remain visible in the tag tests, while tests/conftest.py, test |
| I-tests5 | `I-05` | FOLLOW-UP | **STILL PRESENT** | A misleading offline audit citation cannot itself be exploited, lose data, or leak data on production as configured. STILL PRESENT — The positive audit test still counts registry.get, classify and a synthetic presentatio |
| I-tests5 | `I-06` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |
| J-docs1 | `J-01` | FOLLOW-UP | **NO RULING** | its part was never reviewed — no credits |

| Ruling | Count |
|---|---|
| REPAIRED | 5 |
| STILL PRESENT | 35 |
| CANNOT TELL | 14 |
| NO RULING | 31 |

**5 of round 9's 85 material findings are ruled REPAIRED at this SHA.**
## Every part's verdict, finding by finding

29 parts were built. 19 were reviewed. The reviewer's account ran out of API credits
part-way through, so 10 parts — 89 changed paths — carry no independent review at all.
Those 10 are listed at the end of this section.


### S1 — the door and authority — identity, admission, the local CLI, health, and the whole tool-authority chain

Files (10):

- `app/identity.py`
- `app/main.py`
- `app/routes/actions.py`
- `app/routes/health.py`
- `app/local_cli.py`
- `app/tools/authority.py`
- `app/tools/dispatch.py`
- `app/tools/gate.py`
- `app/providers/max_agent_sdk.py`
- `app/tools/registry.py`

**Verdict: CHANGES_REQUIRED**

#### New findings (1 material)

- **`S1-KEY-SENDER` — BLOCKS** _(unverifiable from this part)_
  - BLOCKS — The callers that transmit the local CLI key are not supplied, so I cannot rule out leaking it to a different process that takes the loopback port during a restart. Defining far_end_held_by does not establish that every sender calls it before sending headers().
  - Evidence: `app/identity.py:far_end_held_by; app/local_cli.py:headers; REVIEW PACKET — PR #54 BODY, A1B-KEY claim`
  - Repair asked for: Supply and review the exact-SHA key-sending paths in scripts/healthcheck.py, scripts/status.py, scripts/install_systemd.py, and scripts/test_session.py; ensure each checks the connected far end before sending the key and does not forward it on redirects.

#### Round-9 rulings from this part (14)

- **`R9-A1a-F-05A` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — The required verification cannot be settled from this part, so I cannot establish that all three CLI routes preserve the production admission boundary. The supplied key checks reject empty and misplaced headers, but the through-proxy tests and exact-SHA owner-device check are not supplied.
  - Evidence: `app/local_cli.py:presented,admits; app/main.py:guard_and_freshness; REVIEW PACKET — R9-A1a-F-05A`
- **`R9-A1a-F-05B` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — Without the required gate exercises, I cannot establish that malformed kernel input never admits a caller in production. The supplied parsers reject malformed rows and PID listings, but their tests through both gates are not supplied.
  - Evidence: `app/identity.py:_tcp_rows,unit_pids,_proc_peer_check; app/routes/actions.py:proxy_state,principal_verdict,caller_check; REVIEW PACKET — R9-A1a-F-05B`
- **`R9-A1a-F-05B-AVAIL` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — The required omission cases are not supplied, so I cannot establish that an incomplete address snapshot cannot admit a self-originating request as an owner device. The new code checks for ::1, corroborates locality against sockets, and requires a family-matched tailnet address, but two equal readings are not proof that neither omitted an address.
  - Evidence: `app/identity.py:host_addresses,bound_here,this_host; app/routes/actions.py:proxy_state; REVIEW PACKET — R9-A1a-F-05B-AVAIL`
- **`R9-A1a-F-05B-AVAIL-PREFLIGHT` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — The installer's executable launch-and-health gate and the required phone correlation cannot be established from this part, leaving the production proxy-identity preflight unverified. The packet establishes the rendered unit flag, not the installer's behavior.
  - Evidence: `app/identity.py:served_without_proxy_headers; app/routes/health.py:_checked; REVIEW PACKET — PACKET FACTS and R9-A1a-F-05B-AVAIL-PREFLIGHT`
- **`R9-A1b-F-05A` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — I cannot verify the required real-device admission behavior from substituted provenance answers, so the production CLI exception is not fully checked. Header presence and DIRECT-only admission are visible, but the owner-device evidence and cited tests are absent.
  - Evidence: `app/local_cli.py:presented,admits; REVIEW PACKET — R9-A1b-F-05A and PR #54 BODY`
- **`R9-A1b-F-05B-AVAIL` → STILL PRESENT**
  - STILL PRESENT — FOLLOW-UP — An address-table failure lasting beyond the bounded retries denies owner requests rather than causing an exploit, data loss, or data leak on the configured host. Four reads over at most 70 ms replace two immediate reads, but no availability-preserving response is provided for a routine lookup failure lasting longer.
  - Evidence: `app/identity.py:ADDRESS_READS,ADDRESS_PAUSES_S,host_addresses,this_host`
- **`R9-A2-F-NEW-TOOLS-PATH` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — A refused caller's path to the model cannot be established without the turn-entry code, so possible acquisition of owner tool authority remains unverified. The supplied middleware, provider callback, and dispatcher do not show the entire HTTP-to-turn path.
  - Evidence: `app/main.py:guard_and_freshness; app/providers/max_agent_sdk.py:_dispatch,_turn_locked; app/tools/registry.py:build_mcp_server; REVIEW PACKET — R9-A2-F-NEW-TOOLS-PATH`
- **`R9-A3b-F-04-STARTUP` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — I cannot establish that report containment prevents a data leak when a differently owned report path or symlink is present. Startup calls the report check, but its ownership and link handling are outside this part.
  - Evidence: `app/main.py:_reports_contained,housekeep_once,lifespan; REVIEW PACKET — R9-A3b-F-04-STARTUP`
- **`R9-A3b-F-04-SHUTDOWN` → STILL PRESENT**
  - STILL PRESENT — BLOCKS — A housekeeping operation exceeding 27 seconds can still leave runtime closure skipped and a bounded timeline drain can exit with accepted events pending, risking data loss on production shutdown. Stop checks occur between operations, not within an overlong operation; the normal close and flush guarantees also cannot be verified from this part.
  - Evidence: `app/main.py:housekeep_once,Housekeeper.stop,lifespan,drain_timelines`
- **`R9-A3b-F-A3B-SCREEN-EVIDENCE` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — I cannot establish what a keyed production TV receives, so an unintended customer or live-voice data leak cannot be ruled out. This part supplies the public page shell and router inclusion, not the screen-facing data path.
  - Evidence: `app/main.py:display_page,app.include_router(displays.router); REVIEW PACKET — R9-A3b-F-A3B-SCREEN-EVIDENCE`
- **`R9-B1-B-01-B-05-PATH` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — The complete production path from owner admission to a screen handler and its issued-ID check is not supplied, so a refused caller's access to customer slips cannot be ruled out. The supplied gate and authority chain alone do not establish what the screen handlers expose.
  - Evidence: `app/routes/actions.py:principal_verdict,require_principal; app/main.py:guard_and_freshness; app/tools/gate.py:_ISSUED_ID_ARGS; app/providers/max_agent_sdk.py:_dispatch; REVIEW PACKET — R9-B1-B-01-B-05-PATH`
- **`R9-C-C-01` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — A forged identity is rejected by the supplied middleware path, but I cannot verify the live-token handler and its complete admission behavior; an unauthorized token mint would leak access to live transcription. The voice route implementation is absent.
  - Evidence: `app/main.py:guard_and_freshness,app.include_router(voice.router); app/routes/actions.py:proxy_state,principal_verdict; REVIEW PACKET — R9-C-C-01`
- **`R9-D1-D1-03` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — I cannot rule out a reachable write with weaker refusal or disambiguation checks on this writes-enabled host. The supplied provider and gate show model tool staging, but neither the deleted fast-lane checks nor the complete turn and action-staging implementations are in this part.
  - Evidence: `app/providers/max_agent_sdk.py:_dispatch; app/tools/dispatch.py:dispatch,_stage; app/tools/gate.py:classify; REVIEW PACKET — R9-D1-D1-03`
- **`R9-D2-D2-03` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — The provider now sets CURRENT_BRANCH around each SDK tool dispatch, but I cannot establish that every overlapping write proposal is staged against that context rather than a shared session field; attaching a live write to the wrong half could lose data. The turn and staging implementations are absent.
  - Evidence: `app/providers/max_agent_sdk.py:_dispatch,turn_on_branch; app/tools/dispatch.py:_stage; REVIEW PACKET — R9-D2-D2-03`


### S1T — the door's tests

Files (11):

- `tests/test_turn_authority_path.py`
- `tests/test_health_key.py`
- `tests/test_host_addresses.py`
- `tests/test_proxy_identity.py`
- `tests/test_local_cli.py`
- `tests/test_tool_boundary.py`
- `tests/test_gate.py`
- `tests/test_registry.py`
- `tests/test_engineering_bridge.py`
- `tests/test_engineering_bridge_bounds.py`
- `tests/test_routes.py`

**Verdict: CHANGES_REQUIRED**

#### New findings (1 material)

- **`S1T-01` — BLOCKS** _(demonstrated in code this part held)_
  - BLOCKS — The test explicitly accepts a server-originated request as owner traffic when the host's address reading omits its own tailnet address, a condition that could be exploited if it occurs on the configured host. In the no-socket case, the test puts a different tailnet address in the table yet asserts that _gates(_self(HOST_V4)) is ADMITTED.
  - Evidence: `crooks-assistant/tests/test_host_addresses.py:test_a_socket_on_this_host_holding_the_address_makes_it_this_hosts`
  - Repair asked for: Make that incomplete-reading case fail closed at both gates and change the regression test to require refusal; supply app/identity.py and app/routes/actions.py to review the repair.

#### Round-9 rulings from this part (6)

- **`R9-A1b-A1B-KEY` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Without the launcher implementation, I cannot rule out leakage of the local-CLI key on the configured host. CANNOT TELL — The new tests exercise a competing listener and a redirect, but scripts/launch_common.py is not supplied, so I cannot verify that the connection check and no-redirect rule protect the keyed request.
  - Evidence: `crooks-assistant/tests/test_health_key.py:test_a_competitor_answering_limited_on_the_port_is_never_sent_the_key; test_a_redirect_is_never_followed_with_the_key_or_without_it; REVIEW PACKET — YOUR PART`
- **`R9-A1b-F-05A` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — The missing real-device result leaves exploitation of the local-key admission path unresolved on the configured host. CANNOT TELL — Both owner-device tests substitute provenance or Tailscale answers; no result from a genuinely verified owner device against this SHA is supplied, and app/main.py and app/routes/actions.py are outside this part.
  - Evidence: `crooks-assistant/tests/test_local_cli.py:_verified_owner_device; crooks-assistant/tests/test_turn_authority_path.py:production; REVIEW PACKET — PR #54 BODY, Deploy-time steps`
- **`R9-A1b-F-05B-AVAIL` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Without the locality implementation, I cannot rule out exploitation by a server-originated request mistaken for George's device. CANNOT TELL — Tests assert bounded retries and refusal after four failed reads, but app/identity.py and the gate in app/routes/actions.py are not supplied as bodies.
  - Evidence: `crooks-assistant/tests/test_host_addresses.py:test_a_failure_that_outlasts_an_immediate_reread_is_waited_out_within_a_bound; REVIEW PACKET — sibling contracts and YOUR PART`
- **`R9-A1b-F-05B-AVAIL-PREFLIGHT` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — An unverified production-device gate could admit an exploitable caller or leave the deployed service incorrectly configured. CANNOT TELL — The installer test mocks health and MainPID; neither scripts/install_systemd.py nor app/routes/admin.py:whoami nor a correlated real-phone result against this SHA is supplied.
  - Evidence: `crooks-assistant/tests/test_proxy_identity.py:test_the_install_is_done_only_when_the_running_service_has_the_flag_and_health_agrees; test_every_whoami_carries_its_own_token_and_the_line_that_says_so; REVIEW PACKET — PR #54 BODY, Deploy-time steps`
- **`R9-A1b-A1B-STATUS` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — With the status implementation absent, its effects on the configured host cannot be cleared under this packet's missing-file rule. CANNOT TELL — The new test asserts a nonzero exit for limited health, but scripts/install_systemd.py:status is outside this part.
  - Evidence: `crooks-assistant/tests/test_health_key.py:test_make_status_is_well_only_on_a_health_answer_that_carries_its_checks; REVIEW PACKET — YOUR PART`
- **`R9-A2-F-NEW-TOOLS-PATH` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Missing production admission code prevents ruling out exploitation through owner authority granted to a non-owner. CANNOT TELL — The new HTTP tests use a model double and force tailscale_verify=True; app/main.py:guard_and_freshness, app/routes/turn.py:turn and _provider_turn, app/routes/actions.py, and config/settings.py are not supplied as implementations.
  - Evidence: `crooks-assistant/tests/test_turn_authority_path.py:production; Witness; REVIEW PACKET — sibling contracts and YOUR PART`


### S2 — the turn and the write boundary

Files (7):

- `app/routes/turn.py`
- `app/routes/command.py`
- `app/recipes.py`
- `app/tools/gmail_writes.py`
- `app/families/compose.py`
- `app/families/order_edit.py`
- `app/families/store_credit.py`

**NOT REVIEWED.** The reviewer's API account had no credits remaining when this part
was dispatched (`insufficient_quota` / `credit_balance_exhausted`). Nothing in this
part has been independently reviewed at this SHA. Under George's rule, what cannot be
told is BLOCKS.


### S2T — the turn's and the write boundary's tests

Files (10):

- `tests/test_turn_boundary.py`
- `tests/test_tap_reads_only.py`
- `tests/test_reply_order_binding.py`
- `tests/test_compose_provenance.py`
- `tests/test_store_credit.py`
- `tests/test_actions_routes.py`
- `tests/test_recipes.py`
- `tests/test_every_turn_is_the_model.py`
- `tests/test_order_edit_picker_binding.py`
- `tests/test_gmail_writes.py`

**NOT REVIEWED.** The reviewer's API account had no credits remaining when this part
was dispatched (`insufficient_quota` / `credit_balance_exhausted`). Nothing in this
part has been independently reviewed at this SHA. Under George's rule, what cannot be
told is BLOCKS.


### S3 — the screens, server side

Files (6):

- `app/routes/displays.py`
- `app/displays/store.py`
- `app/tools/display_tools.py`
- `app/displays/views.py`
- `app/clients/youtube.py`
- `app/observability/screens.py`

**NOT REVIEWED.** The reviewer's API account had no credits remaining when this part
was dispatched (`insufficient_quota` / `credit_balance_exhausted`). Nothing in this
part has been independently reviewed at this SHA. Under George's rule, what cannot be
told is BLOCKS.


### S3P — the screens, the pages

Files (6):

- `web/display.js`
- `web/remote.js`
- `web/sw.js`
- `web/display.html`
- `web/display.css`
- `web/remote.css`

**Verdict: CHANGES_REQUIRED**

#### New findings (1 material)

- **`S3P-F-01` — BLOCKS** _(demonstrated in code this part held)_
  - BLOCKS — An expired customer pane can remain visible on the production remote and leak data during a pointer hold. A successful sync calls render without the immediate-wipe flag; render returns before filtering expired panes while the hold is active.
  - Evidence: `crooks-assistant/web/remote.js:fresh,render,sync; crooks-assistant/web/remote.js:build pointerdown handler`
  - Repair asked for: On local pane expiry, clear its sensitive DOM and retained data synchronously regardless of pointer hold, and test expiry during an active hold.

#### Round-9 rulings from this part (8)

- **`R9-A3b-F-A3B-SCREEN-EVIDENCE` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — The missing screen-route bodies leave a possible production customer-data leak unverified. CANNOT TELL — display.js renders customer, address, phone and note fields, but this packet does not establish what a keyed TV can obtain with snapshots disabled.
  - Evidence: `crooks-assistant/web/display.js:renderOrder,receive; REVIEW PACKET — THE CONTRACT OF THE SIBLING FILES YOU CALL BUT CANNOT SEE`
- **`R9-B1-NEW-B-LOCAL-SLIP` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Customer details remain on a production TV past local expiry and can therefore leak. STILL PRESENT — The five-second expiry check calls reconcile and clearScreen, which delays removal of the old DOM rather than wiping it immediately.
  - Evidence: `crooks-assistant/web/display.js:tooOld,reconcile,clearScreen; crooks-assistant/web/display.css:.cs-ui.is-dissolving`
- **`R9-B2-B2-01` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — An existing production TV's reusable key remains exploitable from script-readable storage until a successful migration. STILL PRESENT — loadScreen reads the legacy key without removing its localStorage record, and migrate leaves that record intact while the server is unreachable.
  - Evidence: `crooks-assistant/web/display.js:loadScreen,saveScreen,migrate`
- **`R9-B2-B2-02` → REPAIRED**
  - REPAIRED — wipe calls render(true), which bypasses the pointer-hold redraw delay and clears the remote's panes after a 403.
  - Evidence: `crooks-assistant/web/remote.js:wipe,render,sync`
- **`R9-B2-B2-03` → REPAIRED**
  - REPAIRED — The specified old-success-after-403 paths discard responses using generation checks before display.js receives them or remote.js assigns them to R.data.
  - Evidence: `crooks-assistant/web/display.js:asked,poll,markDone,wipe; crooks-assistant/web/remote.js:sync,act,tick,control,wipe`
- **`R9-B2-B2-04` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Whether previously sampled customer-detail dots remain visible after packing is an unresolved production data-leak risk. CANNOT TELL — markedDone replaces the DOM and pane view with a reduced summary, but invokes the unseen dots engine's packOut on the prior drawing.
  - Evidence: `crooks-assistant/web/display.js:sampleUi,push,markedDone; REVIEW PACKET — YOUR PART`
- **`R9-B2-B-07` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — An unverified owner-specific root response could leak data through the offline cache. CANNOT TELL — isShell checks for a build-marker substring, not that GET / is the same data-free HTML for every login; its handler and template are absent.
  - Evidence: `crooks-assistant/web/sw.js:keepShell,networkFirst,isShell`
- **`R9-G-G-01` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — The missing live-voice and telemetry implementations leave a possible production token or spoken-data leak unverified. CANNOT TELL — remote.js:fromTurn handles a screen card, but cannot establish token lifetime or the destinations of live words and telemetry.
  - Evidence: `crooks-assistant/web/remote.js:fromTurn,open; REVIEW PACKET — R9-G-G-01`


### S3T1 — the screens' server tests

Files (5):

- `tests/test_displays.py`
- `tests/test_screens_r10.py`
- `tests/test_screen_cookie.py`
- `tests/test_screen_paths.py`
- `tests/test_screen_video.py`

**Verdict: CHANGES_REQUIRED**

#### Round-9 rulings from this part (3)

- **`R9-B1-B-03` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — Unverified purge durability could leak a cleared customer slip after restart. The new tests cover a first journal-folder fsync failure followed by a record failure, but the store implementation is not supplied, so they cannot establish that every deletion and retry preserves the required durability invariant.
  - Evidence: `tests/test_screens_r10.py:test_a_deletion_whose_journal_is_not_durable_and_whose_record_is_not_either_is_not_made; REVIEW PACKET — CONTRACT ONLY app/displays/store.py`
- **`R9-B1-B-01-B-05-PATH` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — An unverified production authority path could be exploited to put a customer slip on a screen or expose one to a refused caller. The new test exercises a scripted path, but its fixture forces tailscale_verify=True while tonight's CROOKS_TAILSCALE_VERIFY is unset; the implementations deciding whether that represents production, and whether issued IDs survive the HTTP-to-tool path, are not supplied.
  - Evidence: `tests/test_screen_paths.py:world,test_a_refused_caller_reaches_no_screen_route_and_no_screen_tool,test_screen_show_puts_up_only_an_order_this_conversation_was_issued; REVIEW PACKET — production switches and CONTRACT ONLY`
- **`R9-B1-NEW-B-LOCAL-SLIP` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — An open TV retaining a slip after refusal, disconnection or expiry could leak customer details. The supplied server test checks what an HTTP response contains and another test checks strings in the page source; neither establishes what the open page or dots engine actually clears, and their implementations are not supplied.
  - Evidence: `tests/test_screen_paths.py:test_a_screen_whose_device_is_refused_or_whose_slip_is_past_its_time_is_given_nothing; tests/test_displays.py:test_the_screen_takes_a_customer_off_at_once_when_it_may_no_longer_show_it`


### S3T2 — the screens' page tests and screen privacy

Files (4):

- `tests/test_screen_privacy.py`
- `tests/web/display.test.js`
- `tests/web/remote.test.js`
- `tests/web/sw.test.js`

**Verdict: CHANGES_REQUIRED**

#### Round-9 rulings from this part (2)

- **`R9-A3b-F-04-REPORT-LOSS` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — The missing pruning implementation could still delete a freshly replaced report and lose data on production as configured. The supplied tests do not exercise concurrent replacement of an aged report or descendant, so the round-9 race cannot be ruled out.
  - Evidence: `Round-9 finding R9-A3b-F-04-REPORT-LOSS; crooks-assistant/tests/test_screen_privacy.py:test_a_fresh_report_inside_an_old_folder_keeps_the_whole_folder`
- **`R9-B2-B2-02` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — Without the remote implementation, a revoked remote may still leak customer details after a 403 while a finger is held on the panel. The new test exercises that state, but cannot establish that the production wipe clears the DOM synchronously.
  - Evidence: `crooks-assistant/tests/web/remote.test.js:test('a refusal takes what the remote shows away at once, even with a finger on the panel'); contract-only crooks-assistant/web/remote.js:render,wipe`


### S4 — live voice and the words on the page

Files (9):

- `app/routes/voice.py`
- `app/routes/observe.py`
- `web/live-voice.js`
- `web/telemetry.js`
- `tests/test_live_voice.py`
- `tests/test_live_voice_owner.py`
- `tests/test_live_transcript_telemetry.py`
- `tests/web/live-voice.test.js`
- `tests/web/live-words-page.test.js`

**NOT REVIEWED.** The reviewer's API account had no credits remaining when this part
was dispatched (`insufficient_quota` / `credit_balance_exhausted`). Nothing in this
part has been independently reviewed at this SHA. Under George's rule, what cannot be
told is BLOCKS.


### S4A — the app page itself

Files (1):

- `web/app.js`

**NOT REVIEWED.** The reviewer's API account had no credits remaining when this part
was dispatched (`insufficient_quota` / `credit_balance_exhausted`). Nothing in this
part has been independently reviewed at this SHA. Under George's rule, what cannot be
told is BLOCKS.


### S5 — records, observability and shutdown

Files (11):

- `app/objectives/gaps.py`
- `scripts/gap_clean_check.py`
- `scripts/launch_common.py`
- `scripts/install_systemd.py`
- `scripts/status.py`
- `app/reads/scheduler.py`
- `app/anticipation/engine.py`
- `tests/test_gaps.py`
- `tests/test_gap_clean_property.py`
- `tests/test_housekeeping_round9.py`
- `tests/test_standdown_branch.py`

**NOT REVIEWED.** The reviewer's API account had no credits remaining when this part
was dispatched (`insufficient_quota` / `credit_balance_exhausted`). Nothing in this
part has been independently reviewed at this SHA. Under George's rule, what cannot be
told is BLOCKS.


### AC1 — the rest of the application, part 1 of 3

Files (4):

- `app/presentation.py`
- `app/tools/analytics_tools.py`
- `app/tools/shopify_tools.py`
- `app/workspace.py`

**Verdict: CHANGES_REQUIRED**

#### New findings (1 material)

- **`AC1-F-01` — FOLLOW-UP** _(demonstrated in code this part held)_
  - FOLLOW-UP — This incorrect segmentation is not itself shown to be exploitable or to lose or leak data in production. `email_query` puts members in the `not_contacted` working set when their Gmail check was unavailable, although its displayed count excludes unchecked members and its note says they belong to neither set.
  - Evidence: `CANDIDATE FILES: crooks-assistant/app/tools/analytics_tools.py, email_query() (`not_contacted.extend(members)` and the derived-set loop)`
  - Repair asked for: Add members to `not_contacted` only after a successful mail check; keep unchecked members separate and test an unavailable Gmail read.

#### Round-9 rulings from this part (1)

- **`R9-D1-D1-02` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — A tapped write targeting a different record from the one displayed could lose or leak data in production, and the supplied files do not establish that the cursor and write target remain aligned. `presentation.py` composes workspaces, but this part does not include the cursor-selection or command-binding code.
  - Evidence: `Round-9 finding R9-D1-D1-02; CANDIDATE FILES: crooks-assistant/app/presentation.py, _compose_workspace() and _remember()`


### AC2 — the rest of the application, part 2 of 3

Files (11):

- `app/clients/elevenlabs.py`
- `app/commands.py`
- `app/digest/selfmodel.py`
- `app/kb/loader.py`
- `app/progressive.py`
- `app/render.py`
- `app/routes/branches.py`
- `app/runtime.py`
- `app/session/branch.py`
- `app/surfaces.py`
- `app/tools/engineering_tools.py`

**Verdict: CHANGES_REQUIRED**

#### Round-9 rulings from this part (3)

- **`R9-A3b-F-04-SHUTDOWN` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — CANNOT TELL — Accepted timeline events may be lost on shutdown because the shutdown and writer-drain paths cannot be verified. Runtime.aclose closes the provider and clients but contains no timeline drain; whether lifespan safely stops housekeeping and drains pending events depends on missing app/main.py and app/observability/timeline.py.
  - Evidence: `crooks-assistant/app/runtime.py:Runtime.aclose; REVIEW PACKET — R9-A3b-F-04-SHUTDOWN`
- **`R9-D2-D2-03` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — CANNOT TELL — A live write could attach to the wrong half and lose data because per-turn branch authority cannot be verified. Branch.instruction_seq exists, but the claimed CURRENT_BRANCH binding and downstream staging are outside the supplied files: app/routes/turn.py, app/session/models.py, app/providers/max_agent_sdk.py and app/actions/engine.py are missing.
  - Evidence: `crooks-assistant/app/session/branch.py:Branch.instruction_seq; REVIEW PACKET — R9-D2-D2-03`
- **`R9-D2-D2-04` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — CANNOT TELL — A mixed-record answer could focus the wrong record before a write and lose data because the cursor-selection code is unavailable. The supplied app/commands.py shows how a tapped control binds a target, but missing app/routes/turn.py contains _stand_on_what_was_shown, so the claimed mixed-record safeguard cannot be checked.
  - Evidence: `crooks-assistant/app/commands.py:_bind_voice; REVIEW PACKET — R9-D2-D2-04`


### AC3 — the rest of the application, part 3 of 3

Files (23):

- `app/capabilities/__init__.py`
- `app/capabilities/ask.py`
- `app/capabilities/delta.py`
- `app/capabilities/screen.py`
- `app/capabilities/surface.py`
- `app/capabilities/ui_intent.py`
- `app/clients/whisper.py`
- `app/fastpath/__init__.py`
- `app/fastpath/correction.py`
- `app/fastpath/intent.py`
- `app/fastpath/lanes.py`
- `app/fastpath/library.py`
- `app/fastpath/models.py`
- `app/fastpath/recipes.py`
- `app/fastpath/runner.py`
- `app/memory/coalesce.py`
- `app/memory/prefetch.py`
- `app/routes/admin.py`
- `app/secrets/keychain.py`
- `app/secrets/linux_store.py`
- `app/session/models.py`
- `app/speech/normalise.py`
- `app/speech/transcribe.py`

**Verdict: CHANGES_REQUIRED**

#### Round-9 rulings from this part (4)

- **`R9-A1a-F-05B-AVAIL-PREFLIGHT` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — The missing deployment gate and phone evidence leave a potentially exploitable proxy-identity failure unverified on production. CANNOT TELL — `whoami` creates one token for its log line and response, but `scripts/install_systemd.py` and a correlated real-phone result for this SHA were not supplied.
  - Evidence: `crooks-assistant/app/routes/admin.py:whoami; REVIEW PACKET — R9-A1a-F-05B-AVAIL-PREFLIGHT and YOUR PART scope`
- **`R9-A1b-F-05B-AVAIL-PREFLIGHT` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Without the installer and device check, an exploitable failure of the production identity gate cannot be ruled out. CANNOT TELL — The supplied `whoami` code correlates its log and response tokens, but whether installation aborts or rolls back after failed running-process, health, or device checks requires `scripts/install_systemd.py`, which is outside this part; no real-phone result is supplied.
  - Evidence: `crooks-assistant/app/routes/admin.py:whoami; REVIEW PACKET — R9-A1b-F-05B-AVAIL-PREFLIGHT and YOUR PART scope`
- **`R9-D2-D2-03` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Missing write-path files prevent ruling out an exploitable cross-branch write on production. CANNOT TELL — `Session.acting_branch` remains shared and mutable; its comment claims request-local authority, but the route, provider, context, and action-staging implementations are not supplied.
  - Evidence: `crooks-assistant/app/session/models.py:Session.acting_branch, Session.branch, Session.stage; REVIEW PACKET — R9-D2-D2-03`
- **`R9-D2-D2-05` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Without the model-turn route and tests, a wrong-record answer that could leak customer data cannot be ruled out on production. CANNOT TELL — The former read-side disambiguation and correction rules were deleted; the claimed replacement for named orders and customers cannot be checked in the files assigned to this part.
  - Evidence: `REVIEW PACKET — diff deleting app/fastpath/library.py and app/fastpath/correction.py; R9-D2-D2-05; YOUR PART scope`


### CFG — settings, the unit template and the deploy documents

Files (5):

- `.env.example`
- `Makefile`
- `config/settings.py`
- `deploy/env.production.example`
- `deploy/systemd/crooks-assistant.service`

**Verdict: CHANGES_REQUIRED**

#### New findings (2 material)

- **`CFG-01` — BLOCKS** _(demonstrated in code this part held)_
  - BLOCKS — An exploitable engineering-filing path cannot be ruled out on production with writes enabled: leaving CROOKS_ENGINEERING_HOST unset still selects `worker-01`, despite the production template saying that leaving it unset defers filing. Whether the tool or credential gate prevents filing cannot be determined without `app/tools/engineering_tools.py` and `scripts/provision_secrets.py`.
  - Evidence: `CANDIDATE FILES: config/settings.py, `engineering_host`; deploy/env.production.example, “build objectives”`
  - Repair asked for: Make the unset production setting resolve to a disabled value, verify that filing refuses that value, and provide the missing tool and credential-gate evidence.
- **`CFG-02` — FOLLOW-UP** _(demonstrated in code this part held)_
  - FOLLOW-UP — No exploit, data loss or data leak is established by the supplied files, but a connection that outlasts shutdown can prevent graceful cleanup: uvicorn has no bounded drain, while systemd stops waiting after 30 seconds. This is also identified as an outstanding unit change in the earlier PR claim sheet.
  - Evidence: `CANDIDATE FILES: deploy/systemd/crooks-assistant.service, `ExecStart` and `TimeoutStopSec`; REVIEW PACKET: PR #51 “Residuals” (uvicorn drain)`
  - Repair asked for: Set a finite graceful-drain limit and coordinate `TimeoutStopSec` with that limit and the application's shutdown budget; test a restart with a held connection.


### DOC — the documents

Files (7):

- `README.md`
- `docs/DEPLOY_LINUX.md`
- `docs/phase4/TOOL_MATRIX.md`
- `docs/product-memory/CURRENT_TRUTH.md`
- `docs/product-memory/OWNER_DECISIONS_2026-09-28.md`
- `docs/product-memory/README.md`
- `kb/terminology.md`

**NOT REVIEWED.** The reviewer's API account had no credits remaining when this part
was dispatched (`insufficient_quota` / `credit_balance_exhausted`). Nothing in this
part has been independently reviewed at this SHA. Under George's rule, what cannot be
told is BLOCKS.


### F — the families

Files (15):

- `app/families/__init__.py`
- `app/families/abandoned.py`
- `app/families/address.py`
- `app/families/discounts.py`
- `app/families/interaction.py`
- `app/families/landings.py`
- `app/families/navigation_extras.py`
- `app/families/order_create.py`
- `app/families/order_email.py`
- `app/families/owner_feedback.py`
- `app/families/query_language.py`
- `app/families/self_knowledge.py`
- `app/families/shipping.py`
- `app/families/summaries.py`
- `app/families/ui_intent.py`

**Verdict: CHANGES_REQUIRED**

#### New findings (2 material)

- **`F-01` — FOLLOW-UP** _(demonstrated in code this part held)_
  - FOLLOW-UP — This can give George a false operational count, but the shown read and card path does not itself exploit, lose or leak data. When Shopify has another page, abandoned checkouts reports the count and value of only the fetched page while its figures card marks freshness complete.
  - Evidence: `CANDIDATE FILES — app/families/abandoned.py:shopify_abandoned_checkouts and cards`
  - Repair asked for: Paginate to obtain window-wide totals, or explicitly label the count and value as the fetched subset whenever more is true; mark the card incomplete in that case.
- **`F-02` — FOLLOW-UP** _(demonstrated in code this part held)_
  - FOLLOW-UP — This can falsely tell George nothing is waiting to go out, but the shown recipe only reads and presents data and does not itself exploit, lose or leak it. An open-orders response with complete=False and no rows still takes the unconditional 'Nothing is waiting to go out' branch; the appended completeness note does not qualify that claim.
  - Evidence: `CANDIDATE FILES — app/families/landings.py:_orders_render and _hedge`
  - Repair asked for: Reserve the definitive empty answer for a complete open-orders read; on an incomplete read, say that no waiting orders are held so far but more may exist, and mark the answer partial.

#### Round-9 rulings from this part (4)

- **`R9-E-families1-E-03` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — If the replacement hook does not record owner feedback, tonight's test-session defect reports will be lost. CANNOT TELL — The deleted recorder is visible, but the claimed replacement in app/routes/turn.py and its end-to-end test are not supplied.
  - Evidence: `REVIEW PACKET — R9-E-families1-E-03; DIFF — app/families/owner_feedback.py deletion; CONTRACT ONLY — app/routes/turn.py`
- **`R9-E-families1-E-04` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Accepting a merely possible order-to-thread link could leak one customer's order details in a reply to another customer after George confirms it. CANNOT TELL — The bodies of app/tools/gmail_writes.py and app/routes/turn.py are missing, so their contract signatures cannot establish that an order-specific reply requires a confident link.
  - Evidence: `REVIEW PACKET — R9-E-families1-E-04; DIFF — app/families/order_email.py deletion; CONTRACT ONLY — app/tools/gmail_writes.py and app/routes/turn.py`
- **`R9-E-families1-E-05` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — An unverified dangling import could stop tonight's startup or test-session capture and lose reports. CANNOT TELL — Dynamic family discovery does not establish whether modules outside this part still reference the deleted families, and no SHA-exact repository-wide check or production-config startup result was supplied.
  - Evidence: `REVIEW PACKET — R9-E-families1-E-05 and PR #54 BODY, 'E-05'; CANDIDATE FILES — app/families/__init__.py:load_all`
- **`R9-E-families1-E-06` → REPAIRED**
  - REPAIRED — A missing open-orders read is now distinguished from an empty result: the answer says it cannot determine whether orders are waiting and is marked partial.
  - Evidence: `CANDIDATE FILES — app/families/landings.py:_orders_render`


### O1 — observability, part 1 of 2

Files (4):

- `app/observability/report.py`
- `app/observability/session.py`
- `app/observability/timeline.py`
- `app/observability/visible.py`

**Verdict: CHANGES_REQUIRED**

#### New findings (2 material)

- **`F-01` — FOLLOW-UP** _(demonstrated in code this part held)_
  - FOLLOW-UP — This can falsely call a count final but does not itself exploit access, lose data, or leak data on the configured server. If an offline checker briefly holds the exclusive lock before this process’s first emission, emit accepts an event on _LOCK_BUSY; the checker can release its lock and report no writer before the blocked writer has acquired its shared lock or written the accepted event.
  - Evidence: `crooks-assistant/app/observability/timeline.py:Timeline.emit, Timeline._hold_writer_lock, Timeline._run, writer_alive; REVIEW PACKET — R9-A3b-F-10`
  - Repair asked for: Do not accept an event without a held writer lock, or make the offline finality check account for events accepted while its exclusive lock was held; test that interleaving.
- **`F-02` — BLOCKS** _(unverifiable from this part)_
  - BLOCKS — The required regression evidence for data-loss repairs cannot be verified from the supplied part. The packet supplies source changes but not the concurrent-replacement test in crooks-assistant/tests/test_screen_privacy.py or a SHA-exact timeline short-write-and-stop test file.
  - Evidence: `REVIEW PACKET — R9-A3b-F-04-REPORT-LOSS and R9-A3b-F-A3B-SHORT-WRITE required repairs; PR #54 claim sheet`
  - Repair asked for: Supply executable SHA-exact tests for concurrent replacement of an aged report and descendant, and for a short os.write followed by stop, with assertions on retained files and final counts.

#### Round-9 rulings from this part (11)

- **`R9-A3b-F-04-STARTUP` → REPAIRED**
  - REPAIRED — The reports check now tests ownership, identifies links, and refuses to call the folder contained when either prevents establishing privacy.
  - Evidence: `crooks-assistant/app/observability/session.py:TestSessions._tidy_reports, tighten, _open_to_others`
- **`R9-A3b-F-04-REPORT-LOSS` → REPAIRED**
  - REPAIRED — Pruning moves a candidate aside before unlinking it, then checks the moved entry’s identity and age; a fresh replacement at the original pathname is not unlinked.
  - Evidence: `crooks-assistant/app/observability/session.py:_unlink_if_aged, _remove_if_older, _expired_tree`
- **`R9-A3b-F-04-SHUTDOWN` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Losing accepted timeline events during shutdown cannot be ruled out on the configured always-on server. CANNOT TELL — The files that decide whether an overlong housekeeping pass prevents the runtime and its pending writer from closing are not supplied: crooks-assistant/app/main.py and crooks-assistant/app/runtime.py.
  - Evidence: `REVIEW PACKET — R9-A3b-F-04-SHUTDOWN; crooks-assistant/app/observability/timeline.py:Timeline._run, Timeline.flush`
- **`R9-A3b-F-10` → REPAIRED**
  - REPAIRED — The specific failed-lock path from round 9 now rejects an event when lock acquisition fails and drops a queued batch if the writer cannot hold the lock.
  - Evidence: `crooks-assistant/app/observability/timeline.py:Timeline.emit, Timeline._hold_writer_lock, Timeline._run`
- **`R9-A3b-F-A3B-SHORT-WRITE` → REPAIRED**
  - REPAIRED — The writer loops over short writes and counts only complete lines if a subsequent write fails.
  - Evidence: `crooks-assistant/app/observability/timeline.py:_write_all, Timeline._append`
- **`R9-D1-D1-01` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Customer names could leak into the configured always-on timeline if early turn events precede name registration. CANNOT TELL — Timeline.emit scrubs before queuing, but its name set starts empty; the missing crooks-assistant/app/routes/turn.py is needed to establish when names are registered relative to the first STT and model emissions.
  - Evidence: `crooks-assistant/app/observability/timeline.py:Timeline.emit, note_names, _names; REVIEW PACKET — R9-D1-D1-01`
- **`R9-E-families1-E-05` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — A dangling import could prevent configured test-session capture, and its absence cannot be established from this part. CANNOT TELL — The requested repository-wide check and the missing crooks-assistant/app/routes/turn.py and crooks-assistant/app/families/__init__.py have not been supplied.
  - Evidence: `REVIEW PACKET — R9-E-families1-E-05 and YOUR PART; crooks-assistant/app/observability/visible.py:imports`
- **`R9-F-observability1-F-01` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — A report-path data leak cannot be excluded until both writers are checked. CANNOT TELL — report_target validates the Markdown writer’s identifier and resolved parent, but the other writer, crooks-assistant/app/observability/proposals.py, is not supplied.
  - Evidence: `crooks-assistant/app/observability/session.py:report_target; crooks-assistant/app/observability/report.py:write_report; REVIEW PACKET — R9-F-observability1-F-01`
- **`R9-F-observability1-F-03` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — The store-credit classification cannot be verified from this part, so its round-9 defect cannot be cleared. CANNOT TELL — _spoken_capability still delegates availability to the missing crooks-assistant/app/observability/semantics.py.
  - Evidence: `crooks-assistant/app/observability/report.py:_spoken_capability; REVIEW PACKET — R9-F-observability1-F-03`
- **`R9-F-observability2-F-OBS2-01` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — A leak of owner or customer words from these outputs cannot be excluded. CANNOT TELL — The feedback dictionaries are now scrubbed, but findings can still carry unchecked telemetry values such as tablet_focus.name and cause into report tables; the missing crooks-assistant/app/main.py and crooks-assistant/scripts/session_ops.py are needed to settle downstream access.
  - Evidence: `crooks-assistant/app/observability/visible.py:_focus_lost, read, apply; crooks-assistant/app/observability/report.py:render, _two_outcomes`
- **`R9-F-observability2-F-OBS2-02` → REPAIRED**
  - REPAIRED — Both rule-failure log paths now include only the rule name and exception type, not the rejected telemetry value or exception message.
  - Evidence: `crooks-assistant/app/observability/visible.py:read, _whole`


### O2 — observability, part 2 of 2

Files (6):

- `app/observability/contract.py`
- `app/observability/feedback.py`
- `app/observability/proposals.py`
- `app/observability/semantics.py`
- `app/observability/touch.py`
- `app/observability/ui_semantics.py`

**Verdict: CHANGES_REQUIRED**

#### New findings (2 material)

- **`O2-F-01` — FOLLOW-UP** _(demonstrated in code this part held)_
  - FOLLOW-UP — Misfiling a read request as product feedback meets none of exploit, data loss or data leak. `recognise('Show me the log for order #1938')` matches the bare `log` rule, which bypasses the shop-subject exclusion; during a test session `at_turn` therefore records a false defect and tells the model to say it was logged.
  - Evidence: `REVIEW PACKET — CANDIDATE FILES: feedback.py, KINDS["log"], recognise and at_turn`
  - Repair asked for: Require an instruction to record feedback or a product-defect context for the `log` rule; add a negative test for requests to read an order log.
- **`O2-F-02` — FOLLOW-UP** _(demonstrated in code this part held)_
  - FOLLOW-UP — A wrong observability verdict meets none of exploit, data loss or data leak. For ‘Give Alice £15 of store credit’, `contract.mutating` finds no mutation word, so `contract_of` returns READ_INTENT and `semantics.read_request` never assigns the store-credit change despite the new capability mapping.
  - Evidence: `REVIEW PACKET — CANDIDATE FILES: contract.py, MUTATION and contract_of; semantics.py, CHANGES and read_request`
  - Repair asked for: Recognise store-credit grants as writes in context without treating balance questions as writes; test both request forms through the contract and semantic verdicts.

#### Round-9 rulings from this part (3)

- **`R9-E-families1-E-03` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Owner-reported defects could be lost from tonight’s test-session report because the replacement recording path cannot be verified. CANNOT TELL — `feedback.at_turn` calls `record`, but this part does not include `app/routes/turn.py` to show that it is invoked before the model turn, or the end-to-end test.
  - Evidence: `REVIEW PACKET — R9-E-families1-E-03; CANDIDATE FILES — feedback.py, at_turn`
- **`R9-F-observability1-F-01` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — An unverified report filename boundary could leak owner or customer words outside the private reports directory. CANNOT TELL — `write_proposals` now calls `report_target`, but the bodies that determine identifier admission, target containment and the other report writer are outside this part.
  - Evidence: `REVIEW PACKET — R9-F-observability1-F-01; CANDIDATE FILES — proposals.py, write_proposals`
- **`R9-F-observability1-F-03` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Classification alone meets none of exploit, data loss or data leak, but the packet requires an unresolved finding to block. CANNOT TELL — `semantics.CHANGES` now names `store_credit`, yet this part cannot establish that the live registry contains that key or that the report classifies a successful store-credit turn correctly.
  - Evidence: `REVIEW PACKET — R9-F-observability1-F-03; CANDIDATE FILES — semantics.py, CHANGES and capability_state`


### SC — the remaining scripts

Files (9):

- `bench/anticipation.py`
- `scripts/bench_lanes.py`
- `scripts/bench_whisper.py`
- `scripts/doctor.py`
- `scripts/experience.py`
- `scripts/healthcheck.py`
- `scripts/provision_secrets.py`
- `scripts/session_ops.py`
- `scripts/test_session.py`

**Verdict: CHANGES_REQUIRED**

#### Round-9 rulings from this part (1)

- **`R9-A3b-F-10` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — Whether this can lose data on production as configured cannot be verified without the writer implementation. `no_backend_verdict` still calls a count final when `writer_alive` returns false, but the supplied files do not show whether a writer whose lock acquisition failed can still have events pending or write them.
  - Evidence: `crooks-assistant/scripts/session_ops.py:no_backend_verdict; Round-9 finding R9-A3b-F-10; missing crooks-assistant/app/observability/timeline.py`


### T1 — the remaining tests, part 1 of 5

Files (6):

- `tests/test_capability_gaps.py`
- `tests/test_digest_relate.py`
- `tests/test_discounts.py`
- `tests/test_observability.py`
- `tests/test_order_create.py`
- `tests/test_pad.py`

**Verdict: CHANGES_REQUIRED**

#### Round-9 rulings from this part (1)

- **`R9-I-tests3-I-03` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — Without the replacement turn tests or routing code, an exploitable write or data loss on production as configured cannot be ruled out. The supplied test_order_create.py removes the spoken cancel/refund routing assertions, and none of the six files supplies turn-level tests for those refusals or the removed cross-order and navigation scenarios.
  - Evidence: `packet: R9-I-tests3-I-03; diff tests/test_order_create.py`


### T2 — the remaining tests, part 2 of 5

Files (8):

- `tests/test_actions.py`
- `tests/test_analyser.py`
- `tests/test_batch.py`
- `tests/test_compose.py`
- `tests/test_experience.py`
- `tests/test_n_plus_one.py`
- `tests/test_needs_reply_inbox.py`
- `tests/test_voice_credits.py`

**Verdict: CHANGES_REQUIRED**

#### Round-9 rulings from this part (4)

- **`R9-I-tests1-F-A2-FIXTURE` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — The missing fixture definitions prevent ruling out unintended owner authority, so exploitability cannot be settled. `test_experience.py` checks that an unadmitted harness is refused, but `tests/conftest.py` is not supplied; the direct-dispatch tests' `owner_asking` marks do not establish what happens without that fixture.
  - Evidence: `crooks-assistant/tests/test_actions.py:pytestmark; crooks-assistant/tests/test_experience.py:test_the_harness_admits_nobody_unless_the_owner_is_asked_for_by_name; review packet: YOUR PART`
- **`R9-I-tests2-I-01` → CANNOT TELL**
  - CANNOT TELL — BLOCKS — With writes enabled, a prior order's bound action might still be applied to a newly named order, and the missing production handlers prevent ruling out exploitation or data loss. The bound-control regression was deleted and no replacement appears in this file; `app/routes/turn.py` and the `voice.bind` handler are not supplied.
  - Evidence: `DIFF — crooks-assistant/tests/test_experience.py:deletion of test_a_question_that_names_its_own_subject_is_not_swallowed_by_a_tapped_control; review packet: YOUR PART`
- **`R9-I-tests2-I-02` → STILL PRESENT**
  - STILL PRESENT — FOLLOW-UP — The missing answer checks do not themselves demonstrate an exploit, data loss, or disclosure to anyone other than the authenticated owner tonight. No replacement model-turn test asks about a named person or order while a different record is in focus; the remaining `open_order` calls script the record to read rather than testing that choice.
  - Evidence: `crooks-assistant/tests/test_experience.py:test_asking_again_about_the_record_you_are_on_does_not_add_a_stop; DIFF — crooks-assistant/tests/test_experience.py:deletion of test_a_number_that_is_not_the_open_order_is_never_answered_from_the_open_order and test_a_named_person_is_not_answered_from_whoever_the_open_order_belongs_to`
- **`R9-I-tests3-I-04` → STILL PRESENT**
  - STILL PRESENT — FOLLOW-UP — This remaining performance-test gap demonstrates none of exploitation, data loss, or data leakage tonight. The inventory test now compares equivalent products and results, but `turn()` still calls `dispatch('commerce_summary', ...)` with a predetermined task; no spoken turn measures the reads selected by the model.
  - Evidence: `crooks-assistant/tests/test_n_plus_one.py:turn; crooks-assistant/tests/test_n_plus_one.py:test_the_one_inventory_read_answers_exactly_what_the_per_product_reads_did`


### T3 — the remaining tests, part 3 of 5

Files (11):

- `tests/test_address.py`
- `tests/test_context.py`
- `tests/test_graph.py`
- `tests/test_navigation.py`
- `tests/test_order_edit.py`
- `tests/test_owner_facing_wording.py`
- `tests/test_progressive.py`
- `tests/test_progressive_states.py`
- `tests/test_query_engine_p3.py`
- `tests/test_split.py`
- `tests/test_summaries.py`

**Verdict: CHANGES_REQUIRED**

#### Round-9 rulings from this part (4)

- **`R9-I-tests2-I-03` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — The missing-file rule blocks this unresolved finding, although the offline mock alone establishes no exploit, data loss, or data leak. CANNOT TELL — The route-rendering test still hard-codes order 1938, and its claimed differing-requested-order test is in tests/test_turn_boundary.py, which was not supplied.
  - Evidence: `tests/test_context.py:client.Provider.turn; tests/test_context.py:test_the_models_two_reads_of_an_order_draw_the_whole_order`
- **`R9-I-tests3-I-02` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Whether a reply could leak customer information through a wrong-order thread remains unresolved with writes enabled. CANNOT TELL — The replacement model-turn and registered reply-handler evidence is outside this part; tests/test_gmail_writes.py and app/tools/gmail_writes.py were not supplied.
  - Evidence: `packet: diff tests/test_graph.py, deleted different-order and possible-link tests; PR #54 claim sheet, E-04 / I-tests3 I-02`
- **`R9-I-tests4-I-03` → REPAIRED**
  - REPAIRED — The test now makes the commerce read fail, invokes open.area through stage.touch, and asserts the returned refusal's retry command and held-order context instead of constructing the refusal itself.
  - Evidence: `tests/test_split.py:test_a_landing_that_cannot_be_read_offers_the_tap_again`
- **`R9-I-tests5-I-02` → STILL PRESENT (labelled FOLLOW-UP)**
  - FOLLOW-UP — This missing test coverage cannot itself exploit, lose data, or leak data tonight. STILL PRESENT — tests/test_summaries.py passes a task directly to commerce_summary; it neither submits the owner's returning-customer words through a model turn nor asserts that the complete rendered card list contains exactly one summary and no customer profiles.
  - Evidence: `tests/test_summaries.py:answer_for; tests/test_summaries.py:test_the_compact_row_carries_what_the_brief_asks_for; packet: diff tests/test_summaries.py, deleted test_the_returning_customers_question_draws_one_compact_surface`


### T4 — the remaining tests, part 4 of 5

Files (18):

- `tests/conftest.py`
- `tests/test_abandoned.py`
- `tests/test_analytics_tools.py`
- `tests/test_branches.py`
- `tests/test_build_from_clive.py`
- `tests/test_cancel.py`
- `tests/test_council_fixes.py`
- `tests/test_engine_hooks.py`
- `tests/test_fulfil.py`
- `tests/test_owner_feedback.py`
- `tests/test_provider.py`
- `tests/test_read_budget.py`
- `tests/test_refund.py`
- `tests/test_scribe.py`
- `tests/test_session_ops.py`
- `tests/test_tracking.py`
- `tests/test_visible_privacy.py`
- `tests/test_working_sets.py`

**NOT REVIEWED.** The reviewer's API account had no credits remaining when this part
was dispatched (`insufficient_quota` / `credit_balance_exhausted`). Nothing in this
part has been independently reviewed at this SHA. Under George's rule, what cannot be
told is BLOCKS.


### T5 — the remaining tests, part 5 of 5

Files (37):

- `tests/fake_credentials.py`
- `tests/test_action_state.py`
- `tests/test_branch_concurrency.py`
- `tests/test_capability_routing.py`
- `tests/test_fastpath.py`
- `tests/test_fixture_wiring.py`
- `tests/test_inventory.py`
- `tests/test_landings_unread.py`
- `tests/test_multi_intent.py`
- `tests/test_n_plus_one_turn.py`
- `tests/test_navigation_extras.py`
- `tests/test_needs_reply_routing.py`
- `tests/test_no_dangling_imports.py`
- `tests/test_normalise.py`
- `tests/test_operations.py`
- `tests/test_owner_feedback_turn.py`
- `tests/test_progressive_turn.py`
- `tests/test_read_dedupe.py`
- `tests/test_self_correction.py`
- `tests/test_self_knowledge.py`
- `tests/test_spoken_refusals.py`
- `tests/test_spoken_screen_copy.py`
- `tests/test_spoken_send_steering.py`
- `tests/test_stop.py`
- `tests/test_tags.py`
- `tests/test_tags_remove.py`
- `tests/test_tool_args_redaction.py`
- `tests/test_tool_matrix.py`
- `tests/test_touch_to_voice.py`
- `tests/test_transcribe.py`
- `tests/test_turn_scene.py`
- `tests/test_turn_surfaces.py`
- `tests/test_ui_intent.py`
- `tests/test_web_js.py`
- `tests/test_whisper_disabled.py`
- `tests/test_worker_page_mark.py`
- `tests/test_write_walkthrough.py`

**Verdict: CHANGES_REQUIRED**

#### Round-9 rulings from this part (6)

- **`R9-I-tests2-I-02` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — The missing turn tests leave the risk of disclosing the wrong record's data unresolved. CANNOT TELL — The supplied replacement scripts a different-order lookup and checks its card, but does not check the spoken answer or a named-person request; tests/test_turn_boundary.py and tests/test_experience.py were not supplied.
  - Evidence: `tests/test_spoken_refusals.py::test_what_the_model_reads_for_another_order_is_drawn_as_that_order; packet: ROUND-9 FINDINGS, R9-I-tests2-I-02`
- **`R9-I-tests3-I-03` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Missing refusal and route evidence leaves the possibility of an unintended write and data loss unresolved. CANNOT TELL — The new turn tests cover spoken cancellation, but expressly defer refund coverage; tests/test_refund.py, tests/test_order_create.py, app/routes/turn.py, app/routes/command.py and app/routes/branches.py were not supplied to settle the remaining refusal and navigation claims.
  - Evidence: `tests/test_spoken_refusals.py::test_a_spoken_cancel_is_a_held_card_that_a_spoken_yes_cannot_apply; packet: ROUND-9 FINDINGS, R9-I-tests3-I-03`
- **`R9-I-tests5-I-01` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — A navigation command misread as bound-note dictation could stage a wrong-record change on tonight's write-enabled system, with data loss if confirmed. CANNOT TELL — tests/test_touch_to_voice.py still has no navigation-after-binding negative case, and app/routes/turn.py, which contains _with_continuation, was not supplied.
  - Evidence: `tests/test_touch_to_voice.py::test_the_next_sentence_carries_the_binding_and_only_the_next; packet: ROUND-9 FINDINGS, R9-I-tests5-I-01`
- **`R9-I-tests5-I-03` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — The missing record-selection evidence leaves a confirmed wrong-record write and consequent data loss unresolved. CANNOT TELL — ModelThatAddsANote still searches and notes #1930 regardless of the owner's words; its claimed separate mismatched-record evidence is in the unsupplied tests/test_turn_boundary.py.
  - Evidence: `tests/test_write_walkthrough.py::ModelThatAddsANote.turn; packet: ROUND-9 FINDINGS, R9-I-tests5-I-03`
- **`R9-I-tests5-I-04` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Missing fixture definitions prevent this part from ruling out an exploitable authority regression hidden by the tests. CANNOT TELL — Module-wide owner grants remain visible in the tag tests, while tests/conftest.py, tests/test_tracking.py and tests/test_working_sets.py were not supplied to settle the fixture and absent-authority claims.
  - Evidence: `tests/test_tags.py::pytestmark; tests/test_tags_remove.py::pytestmark; packet: ROUND-9 FINDINGS, R9-I-tests5-I-04`
- **`R9-I-tests5-I-05` → STILL PRESENT (labelled FOLLOW-UP)**
  - FOLLOW-UP — A misleading offline audit citation cannot itself be exploited, lose data, or leak data on production as configured. STILL PRESENT — The positive audit test still counts registry.get, classify and a synthetic presentation item as directly testing probe_tool without dispatching it or invoking its handler.
  - Evidence: `tests/test_tool_matrix.py::test_a_test_that_calls_a_tool_tests_it`


### TW — the remaining page tests

Files (1):

- `tests/web/ui.test.js`

**Verdict: CHANGES_REQUIRED**

#### New findings (1 material)

- **`F-01` — BLOCKS** _(unverifiable from this part)_
  - BLOCKS — This cannot be settled from the supplied files, so exploitation or data leakage through the new remote surface cannot be ruled out. CANNOT TELL whether `screen_remote` is implemented and rendered safely: the only new assertion checks membership in `UI.TYPES`, and the implementation it imports was not supplied.
  - Evidence: `crooks-assistant/tests/web/ui.test.js:12-14,24-44; packet section “THE FILES IN YOUR PART”`
  - Repair asked for: Supply `crooks-assistant/web/ui.js` at this exact SHA so the new type and its rendering can be reviewed.


### W1 — the remaining pages, part 1 of 2

Files (3):

- `web/alpha.js`
- `web/dots.js`
- `web/ui.js`

**Verdict: CHANGES_REQUIRED**

#### New findings (1 material)

- **`W1-01` — FOLLOW-UP** _(demonstrated in code this part held)_
  - FOLLOW-UP — This removes an order control rather than permitting exploitation, data loss, or data leakage. renderOrder calls rail without an order ref, while railChip requires a ref to enable a staged action, so enabled stage-mode order chips are omitted.
  - Evidence: `CANDIDATE FILES — crooks-assistant/web/ui.js, renderOrder(), rail(), and railChip()`
  - Repair asked for: Pass the order's ref to rail in renderOrder and test that an enabled staged order action renders and posts that ref.

#### Round-9 rulings from this part (1)

- **`R9-C-C-03` → STILL PRESENT (labelled BLOCKS)**
  - BLOCKS — Whether the owner's live words could leak cannot be settled from the supplied files, and the packet treats an unresolved finding as a block. CANNOT TELL — alpha.js creates the live-word slots, but does not show whether words remain display-only or are cleared when the turn ends.
  - Evidence: `CANDIDATE FILES — crooks-assistant/web/alpha.js, ask-words and ask-heard; web/app.js contract, liveEnd and settleLiveWords`


### W2 — the remaining pages, part 2 of 2

Files (3):

- `web/alpha.css`
- `web/audio-viz.js`
- `web/index.html`

**NOT REVIEWED.** The reviewer's API account had no credits remaining when this part
was dispatched (`insufficient_quota` / `credit_balance_exhausted`). Nothing in this
part has been independently reviewed at this SHA. Under George's rule, what cannot be
told is BLOCKS.


### X — the experience harness

Files (17):

- `experience/fixtures/live_states.py`
- `experience/harness.py`
- `experience/matrix.py`
- `experience/report.py`
- `experience/scenario_packs/abandoned.py`
- `experience/scenario_packs/commerce.py`
- `experience/scenario_packs/compose.py`
- `experience/scenario_packs/discounts.py`
- `experience/scenario_packs/graph.py`
- `experience/scenario_packs/landings.py`
- `experience/scenario_packs/navigation.py`
- `experience/scenario_packs/navigation_extras.py`
- `experience/scenario_packs/order_edit.py`
- `experience/scenario_packs/query_language.py`
- `experience/scenario_packs/recording.py`
- `experience/scenarios.py`
- `experience/tool_matrix.py`

**NOT REVIEWED.** The reviewer's API account had no credits remaining when this part
was dispatched (`insufficient_quota` / `credit_balance_exhausted`). Nothing in this
part has been independently reviewed at this SHA. Under George's rule, what cannot be
told is BLOCKS.


### The ten parts with no review at all

| Part | What it holds | Changed paths |
|---|---|---|
| `S2` | the turn and the write boundary | 7 |
| `S2T` | the turn's and the write boundary's tests | 10 |
| `S3` | the screens, server side | 6 |
| `S4` | live voice and the words on the page | 9 |
| `S4A` | the app page itself | 1 |
| `S5` | records, observability and shutdown | 11 |
| `DOC` | the documents | 7 |
| `T4` | the remaining tests, part 4 of 5 | 18 |
| `W2` | the remaining pages, part 2 of 2 | 3 |
| `X` | the experience harness | 17 |

## Preflight — read-only, and it all passed

Every step-1 check passed before any review began. Nothing in this section is a reason the deploy
stopped; the review is.

    ==============================================================================================
    STEP 1 — PREFLIGHT, ROUND 10. Read-only. Every check below passed.
    ==============================================================================================
    
    1.1 SHA PROVENANCE
      origin/clive/trunk                     = 81c78948cdb518dba344990617fb77b8a00bc228
      candidate                              = 81c78948cdb518dba344990617fb77b8a00bc228  (they match)
      parents                                = a7cd2be7 (trunk) + 036c71c4 (PR #54 head)
      PR #54 merge commit per GitHub          = 81c78948   head = 036c71c4   base = clive/trunk   MERGED
      ancestors of the candidate, all present: a7cd2be7 YES  c6c640d7 YES  32a99cd7 YES
                                               6a29e310 YES  3e77f215 YES
      first-parent range 6a29e310..81c78948 is exactly four merges:
         81c78948  Round 10: close the round-9 review's findings (PR #54)
         a7cd2be7  Screens: YouTube on a screen ... (PR #53)
         c6c640d7  Round 9 features: iOS blue, live voice, ... (PR #52)
         32a99cd7  Deploy review round 8: close the 21 material findings ... (PR #51)
      NOTE: the local clone's origin/clive/trunk was stale at c6c640d7 and was fetched read-only
      before any of the above. Nothing was written to the production checkout.
    
      ACCEPTANCE RUNS — all three completed/success:
         36460922500  pull_request  claude/r10-integrate  036c71c4  success
         36460913922  push          claude/r10-integrate  036c71c4  success
         36461705974  push          clive/trunk           81c78948  success   <- on the candidate itself
      This carries no review weight. clive/trunk is unprotected and a green run is not a review.
    
    1.2 THE SWITCHES — exactly as required, and .env byte-identical to round 9
         CROOKS_SCREEN_SNAPSHOTS          = 'false'
         CROOKS_LOCAL_OWNER               = <unset>
         CROOKS_WRITES_LOCAL_OWNER        = 'false'
         CROOKS_ENGINEERING_HOST          = <unset>
         CROOKS_TAILSCALE_VERIFY          = <unset>
         CROOKS_LIVE_TRANSCRIPT           = <unset>   (new this range; defaults to true)
         CROOKS_SCRIBE_KEYTERMS           = 'true'
         CROOKS_WRITES_ENABLED            = 'true'
         CROOKS_TEST_SESSION_ALWAYS       = 'true'
         CROOKS_REPORTS_DIR               = <unset>
         CROOKS_ALLOWED_LOGINS            = non-empty (value never printed)
         40 keys, no duplicate key
      .env sha256 0021c07d9c523d4112420537698eae50c51945f5966d3b0d01501def035693ce
                 — IDENTICAL to round 9's recorded value.  mode 600, 3513 bytes.
      No .env line was changed at any point in this review.
    
    1.3 THE UNIT DIFF — only what rounds 6-9 accepted
      First, the renderer was proved faithful: install_systemd.py --print run from a checkout of
      6a29e310 reproduces the INSTALLED unit BYTE FOR BYTE. So the diff below is exactly what this
      range does to the unit and nothing else.
      installed unit sha256 3808af03c0bb0dcfc083ab519b33be3a82299ba92cc418a73678ba60c826722b
      Rendered at 81c78948, the only difference from the installed unit is one comment line:
         -#   the checkout   logs/, .cache/media/, kb/.catalogue-cache.txt
         +#   the checkout   logs/, .cache/media/
      No directive changes at all. This is the same one-line diff round 9 accepted at c6c640d7.
      --no-proxy-headers is present in the rendered ExecStart.
      LoadCredentialEncrypted lines are identical to the installed unit's (three credentials).
    
    1.4 TAILSCALE AND KERNEL-TABLE PRECONDITIONS
      tailscaled MainPID 1655, exe exactly /usr/sbin/tailscaled,
      cgroup exactly 0::/system.slice/tailscaled.service
      /usr/sbin/tailscaled, the cgroup, and its cgroup.procs: all uid 0, no group-write, no
      other-write  -> PASS (computed in python, not shell arithmetic)
      pidfd_open(1) from the production venv interpreter (Python 3.12.3): OK
      tailscale ip -4 = 100.72.82.24        present in /proc/net/fib_trie as /32 host LOCAL
      tailscale ip -6 = fd7a:115c:a1e0::352b:5219  present in /proc/net/if_inet6 (hex)
      disable_ipv6 = 0
    
    1.4b PARSER CHECK AT THE CANDIDATE (production venv interpreter, real host tables)
      net/tcp  : ACCEPTED, 16 of 16 data rows parsed
      net/tcp6 : ACCEPTED, 42 of 42 data rows parsed
      identity.this_hosts_addresses() returned BOTH tailnet addresses, reason EMPTY.  parser-rc=0
    
    1.5 REPORTS
      CROOKS_REPORTS_DIR unset -> /opt/crooks-os/crooks-assistant/reports, uid 0, mode 700
      2 entries total (the directory and .gitkeep). Others-reachable count: 0. No .withheld/.
      Unchanged from round 9.
    
    1.6 THE GAP RECORD AND ITS ONE BACKUP
      /var/lib/crooks-assistant/objectives/gaps.json  uid 0, mode 600, 5866 bytes
      sha256 7f1a7f6b86a708d0b3872b12b8e75c52ed2a197122f01697359c4f798f8eaf48
             — BYTE-IDENTICAL to round 9. version 1, 10 gaps, 0 builds, 0 misjudged.
      Backups matching gaps.json.*: exactly 1 (gaps.json.20260927T211850Z.before-clean).
      Round 9 established: 8 -> 10 gaps on 28 Sep, one row re-keyed, nothing lost. There has been
      NO further change since: the record is the same bytes. No row is gone.
    
    1.6b THE CANDIDATE'S OWN GAP CHECK — scripts/gap_clean_check.py, as root, at 81c78948
      Run bare it resolves to the review checkout's own empty .state/objectives and exits 0 on
      "no gap record" — a vacuous pass. It was therefore run against the live record by path.
      Against /var/lib/crooks-assistant/objectives/gaps.json it reported:
         record: 10 gap row(s) before, 10 after; file unchanged; 0 copies of the original kept
         rows 1-10 each: "kept as it was"
         rollback code (3e77f215) reads and reports the result: yes
         VERDICT: nothing lost          exit 0
      The live record was untouched: same bytes, mode, size and mtime before and after. Backups
      still exactly 1. No temporary folder was left behind. Because the clean rewrites nothing
      that is already clean, the deploy should create NO new backup.
    
    1.7 THE VENDORED ROLLBACK READER
      tests/rollback/gaps_3e77f215.py loaded; 3e77f215's GapLedger.load() reads the live record
      (10 gaps, version 1); report() run against a byte-identical COPY returned gaps/misjudged/
      summary and left the copy unchanged; the live record was never written.  PASS
    
    1.8 displays.json
      uid 0, mode 600, 3079 bytes, sha256 97e9ee7bd3f4b832f6d5bef6e68c6451bc8ba65692b5caee027aa755c5454768
      SCREEN COUNT: 3 — the same three ids round 9 recorded.
         scr_e32d   name P…   created 2026-09-27T21:33:51Z  version 2
         scr_59ec   name M…   created 2026-09-27T21:35:53Z  version 9
         scr_3bcf   name P…   created 2026-09-28T10:54:05Z  version 1
      None carries an `approved` or `paired` field, and all three were created before pairing
      existed -> all three count as ALREADY APPROVED, as in round 9.
      OBSERVATION, not a failure: the file has changed since round 9 (3800 -> 3079 bytes, last_seen
      advanced, scr_59ec's version 8 -> 9). That is the live service recording what each screen is
      showing. No screen was lost and none was added.
    
    1.9 THE PARKED ENGINEERING CREDENTIAL
      /etc/crooks-os/credentials-parked/github_engineering_inbox_token.cred
      uid 0, mode 600, 292 bytes, mtime 27 Sep 01:55 — unchanged. NEVER opened or decrypted.
      Both secret tiers re-checked (see engineering-bridge-tiers.txt): neither the unit's three
      systemd credentials nor /etc/crooks-os/secrets/ holds the key, so read_token() is None and
      every EngineeringInbox entry point returns NotConnected before any HTTP request.
      /etc/crooks-os/credentials/ holds exactly 3 .cred files.
    
    1.10 NOTE FOR THE RECORD
      /opt/crooks-os has three worktrees registered: /opt/crooks-os itself (6a29e310, the
      production checkout), /opt/crooks-review and /opt/crooks-watcher-review. Both extras predate
      this round and were not touched. The review checkout for this round is a separate clone at
      /root/clive-activation/round-10/review, detached at 81c78948, tree 26c70c81 — which matches
      the candidate's tree in /opt/crooks-os exactly. Production stayed at 6a29e310, 0 dirty.

### The candidate's own gap check, in full

Run as root from a review checkout at `81c78948`, against the live record by path:

```
record: 10 gap row(s) before, 10 after; file unchanged; 0 copy/copies of the original kept, 0 byte-identical
  row 1 -> "tool exposes draft order's invoice checkout": kept as it was
  row 2 -> 'tool set custom line name price': kept as it was
  row 3 -> "visibility into how machine's access networking": kept as it was
  row 4 -> 'concept multiple users member accounts invite': kept as it was
  row 5 -> 'display tool project expanded view onto': kept as it was
  row 6 -> 'log manual physically done state task': kept as it was
  row 7 -> 'web research tool look up trend': kept as it was
  row 8 -> 'mac read only shopify gmail writes': kept as it was
  row 9 -> 'order name lookup on order open order add name': kept as it was
  row 10 -> 'custom line name on an order': kept as it was
  rollback code (3e77f215) reads and reports the result: yes
VERDICT: nothing lost          exit 0
```

The live record was untouched — identical bytes, mode, size and mtime before and after — and the
backup count stayed at exactly 1.

**One thing to fix in the tool itself (FOLLOW-UP, `SC-GAPCHECK-DEFAULT`):** run with no argument,
`scripts/gap_clean_check.py` resolves the gap record relative to its own checkout
(`<checkout>/.state/objectives/gaps.json`), finds nothing there, prints `no gap record at …` and
**exits 0**. On a review checkout that is a silent pass that looks like a real one. The deploy
prompt says to run it "on the server", and a reader following that literally from a checkout would
get a green result that means nothing. It should either exit non-zero when the record it was
pointed at does not exist, or default to the configured objectives directory rather than the
checkout's. This round it was run with the live path given explicitly, which is why the output
above is real.

## How the review was built, so the next round can repeat it

- The 300 KB budget held for all 29 parts, and **zero omissions were verified independently** after
  the packets were built: a separate checker read the 29 `packet.txt` files off disk, worked out
  which paths each reviewer would really receive (diff headers inside the 300 KB auto-file window,
  plus manually embedded unchanged files), and compared that against the range's changed paths
  taken fresh from git. Result: 267 of 267 changed paths delivered to at least one part, 0 never
  seen, 0 pushed past the window. `app/tools/registry.py` was supplied manually to S1 as unchanged
  context.
- **Round 9's lesson was acted on.** The security surfaces travel together: S1 holds
  `app/identity.py`, `app/main.py`, `app/routes/actions.py`, `app/routes/health.py`,
  `app/local_cli.py`, `app/tools/authority.py`, `app/tools/dispatch.py`, `app/tools/gate.py`,
  `app/providers/max_agent_sdk.py` and `app/tools/registry.py` in one part (244,675 bytes, inside
  budget). S2 holds the whole turn-and-write-boundary group. Tests went to sibling parts, and every
  split half was given the signatures and docstring first lines of what it calls across the split.
- The packet builder is round 9's, retargeted, **with the pipe-free membership test kept** — the
  `grep -qxF` against a file rather than `echo | grep -qx`, which under `pipefail` raced on SIGPIPE
  and silently dropped files from packets through round 8.
- Every packet was leak-checked against every production secret value. No secret was injected into
  any packet. `CROOKS_SCRIBE_MODEL` and `CROOKS_ALLOWED_LOGINS` appear in some packets only because
  they are already committed in the code under review, not because this round put them there.

### The failure that stopped the review, exactly

Twelve parts first failed on a schema fault of my own making: the reviewer returned
`required_repair: ""` on REPAIRED rulings, and `clive.review_result.v1` requires a non-empty string,
so the harness threw the whole review away. That was a gap in my instructions, not a reviewer
fault. I added an explicit instruction that `required_repair` must never be empty, rebuilt those
twelve packets (zero omissions and leak checks re-verified on all twelve) and re-dispatched.

Two came back. The other ten failed with:

```
"message": "You have no credits remaining. Add credits to continue using the API at
            https://platform.openai.com/settings/organization/billing/.",
"type": "insufficient_quota",
"code": "credit_balance_exhausted"
```

That is the blocking failure. The account behind
`/root/.config/clive-engineering/openai_api_key` has no credits, so neither the ten remaining
parts nor any follow-up packet could be reviewed. The key was never printed or copied anywhere.

## The state everything was left in

Nothing on the server was changed. Verified after the review stopped:

- **Production checkout:** `/opt/crooks-os` at `6a29e31013b0b9e543d90434e14ed65deea1ce30`, 0 dirty
  entries. The candidate was never checked out into production.
- **The service:** untouched. No stop, no start, no restart, no `daemon-reload`.
- **The unit:** `/etc/systemd/system/crooks-assistant.service`, sha256
  `3808af03c0bb0dcfc083ab519b33be3a82299ba92cc418a73678ba60c826722b` — the value recorded at
  preflight. Not rewritten.
- **`.env`:** sha256 `0021c07d9c523d4112420537698eae50c51945f5966d3b0d01501def035693ce`, mode 600,
  3513 bytes — byte-identical to round 9. No line changed. Every switch exactly as found.
- **The parked credential:** `github_engineering_inbox_token.cred`, uid 0, mode 600, 292 bytes,
  mtime 27 Sep 01:55 — unchanged. Never opened, never decrypted.
- **The gap record:** sha256 `7f1a7f6b86a708d0b3872b12b8e75c52ed2a197122f01697359c4f798f8eaf48`,
  exactly 1 backup. No row lost. The read-only check wrote nothing.
- **`displays.json`:** not written by this round. The three screens are the three round 9 recorded.
- **Tailscale `serve`:** untouched. No staging handler was added, because no staging copy was
  raised. Nothing was bound to :8443 or :8799.
- **The reports directory:** mode 700, 2 entries, 0 others-reachable. Unchanged.
- **The review checkout** is a separate clone at `/root/clive-activation/round-10/review`, detached
  at `81c78948` (tree `26c70c81`, matching the candidate exactly). The staging clone and staging
  state directory were never created.


### The same, as the commands reported it

```
=== FINAL STATE, verified after the review stopped ===
2026-09-28T19:47:28Z

--- production checkout ---
HEAD  : 6a29e31013b0b9e543d90434e14ed65deea1ce30
dirty : 0 entries

--- the service (must be untouched) ---
is-active : active
MainPID   : 3068091
NRestarts : 0
ActiveEnterTimestamp: Sun 2026-09-27 21:18:49 UTC
args      : /opt/crooks-os/crooks-assistant/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers

--- the unit ---
3808af03c0bb0dcfc083ab519b33be3a82299ba92cc418a73678ba60c826722b  /etc/systemd/system/crooks-assistant.service
preflight value: 3808af03c0bb0dcfc083ab519b33be3a82299ba92cc418a73678ba60c826722b  /etc/systemd/system/crooks-assistant.service

--- .env ---
0021c07d9c523d4112420537698eae50c51945f5966d3b0d01501def035693ce  /opt/crooks-os/crooks-assistant/.env
preflight value: 0021c07d9c523d4112420537698eae50c51945f5966d3b0d01501def035693ce  /opt/crooks-os/crooks-assistant/.env
stat now: 600 3513 1790471216   preflight: 600 3513 1790471216

--- parked credential ---
uid=0 mode=600 size=292 mtime=1790474150
(expected uid=0 mode=600 size=292 mtime=1790474150)
/etc/crooks-os/credentials/ .cred count: 3

--- gap record ---
7f1a7f6b86a708d0b3872b12b8e75c52ed2a197122f01697359c4f798f8eaf48  /var/lib/crooks-assistant/objectives/gaps.json
backups: 1

--- displays.json ---
97e9ee7bd3f4b832f6d5bef6e68c6451bc8ba65692b5caee027aa755c5454768  /var/lib/crooks-assistant/objectives/displays.json

--- tailscale serve (no staging handler must exist) ---
https://crooks-os-prod-1.taildfb357.ts.net (tailnet only)
|-- / proxy http://127.0.0.1:8000

8443 handlers: []

--- staging must not exist ---
stage dir      : absent
stage-state dir: absent
stage unit     : inactive

--- reports ---
mode=700 /opt/crooks-os/crooks-assistant/reports
entries: 2  others-reachable: 0
```

## What George has to decide

1. **The reviewer's API account needs credits** before round 10's review can be finished. Ten parts
   and every follow-up packet are waiting on that, and nothing else is blocking the *review* — the
   packets are built, verified for zero omissions, and ready to dispatch unchanged.
2. **`R9-B2-B2-01` needs a real fix**, not a re-claim. The old screen key genuinely survives in
   `localStorage` until a successful `/displays/register`. `loadScreen()` should rewrite the record
   to `{id, name}` the moment it lifts the key into memory, so a failed or deferred migration
   cannot leave a reusable key on the TV.
3. **The two demonstrated leak findings on the pages** (`S3P-F-01` and `R9-B1-NEW-B-LOCAL-SLIP`)
   both come down to the same shape: an expiry path that schedules a redraw instead of wiping the
   DOM at once. Both are on TVs in the shop.
4. **`B-04` is still waiting on his ruling.** PR #54's own body says so: whether a screen's own tap
   should count as packed is his call, not the code's. Nothing in this round settled it.
5. **The `gap_clean_check.py` default path** should not exit 0 on a record it never found.

## Artefacts

Everything is under `/root/clive-activation/round-10/` on the server:

| File | What it is |
|---|---|
| `preflight.txt` | Every step-1 check and its result |
| `engineering-bridge-tiers.txt` | Both secret tiers re-checked for the parked token |
| `gap-clean-check.txt` | The candidate's own gap check against the live record |
| `parts/plan.json`, `parts/paths.*`, `parts/scope.*` | The 29 parts, their files and their remits |
| `zero-omission-check.txt` | The independent zero-omission proof |
| `packet-build.log`, `packet-rebuild.log` | Packet builds, budget simulation and leak checks |
| `collected.json`, `r9-rulings.txt`, `blocking-classified.txt` | Every finding and ruling, as collected |
| `dispatch-logs/` | One log per part, including the credit-exhaustion failures |
| `rendered-81c78948.service`, `unit-diff.txt` | The unit as this candidate renders it, and its diff |
| `stage.sh`, `deploy.sh` | Retargeted to `81c78948`, **never run** |

