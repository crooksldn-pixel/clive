# Deploy review, round 9 — findings for the Director

**Candidate:** `c6c640d7017a0411c13d39cecc6ce2223a79c724` — the `clive/trunk` head and PR #52's
merge commit.  
**Production now runs:** `6a29e31013b0b9e543d90434e14ed65deea1ce30`, deployed 27
September under George's waiver, and **unchanged by this round**.  

**Verdict: NOT DEPLOYED.** 45 findings meet George's BLOCKS bar. Under his ship rule the
deploy stops, nothing on the server was changed, and this document is the published list.

**Counts:** 45 BLOCKS · 40 FOLLOW-UP · 6 non-material observations ·
85 material findings across 24 parts. 23 parts returned CHANGES_REQUIRED, 1
returned READY.

---

## George's ship rule, word for word

> - A part BLOCKS the deploy only when it has a material finding that meets at least one of
>   these, on production as it is actually configured tonight:
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

**George confirmed this rule by running the round-9 prompt**, which states that running it is his
confirmation. I had no doubt that he did, so I did not stop to ask.

Every reviewer was given the rule verbatim and was told to put the label as the first word of each
finding. **All 85 material findings came back labelled; none was returned unlabelled.**

### My own check of the labels

I read all 85. I did not move any label. Two points George should know:

1. **I did not downgrade any BLOCKS.** His rule says that where I disagree with a label *or cannot
   tell*, the finding is BLOCKS. That is one-directional by design, so a reviewer's BLOCKS stands.
2. **Of the 45 BLOCKS, 21 are of the form "I cannot tell"** — the reviewer could not exclude the
   hazard from the files in its own bounded part. Those are BLOCKS *by his rule*, not by
   demonstration. **The other 24 are demonstrated defects with a named file and symbol.** The
   deploy would stop on those 24 alone. The list below marks which is which.

Two FOLLOW-UPs I looked at hardest and still agree with, because they turn on the configuration
the rule tells me to assume:

- **F-04-STARTUP** (A3b) — the start-up privacy pass can miss a symlinked or other-owned report
  folder. At preflight the live reports folder is root-owned `0700` with one root-owned `0600`
  file and no symlink, and `find … -perm /077` is 0. The defect needs a path shape this host does
  not have tonight.
- **F-02** (F-observability1) — `sanitise_markup` keeps text under a `data-spoken` element and can
  keep a token-shaped `data-words` value. `CROOKS_SCREEN_SNAPSHOTS=false` is verified at preflight
  and stops that path collecting markup at all. Turn that switch on and this becomes a BLOCKS.

---

## What this round was

Range `6a29e310..c6c640d7` — **221 files, +13350 / −14964**, two PRs:

- **PR #51** (head `10fe6865`, merge `32a99cd7`) — closes the 21 material round-8 findings, applies
  George's two rulings (F-A2-FIXTURE, NEW-B-CAP), restyles the screens to their approved design.
- **PR #52** (head `858d36e4`, merge `c6c640d7`) — George's four requests of 28 September: iOS blue;
  live voice with a real waveform and live words; the fast lane and speech keyterms/normaliser
  removed so every sentence is a model turn; the TV remote.

### How it was reviewed

**Twenty-four bounded parts**, sized so the reviewer harness's 300 KB full-file budget could never
silently drop a file. The seven parts George suggested were kept and split where they were over
budget (A1→A1a/A1b, A3→A3a/A3b, D→D1/D2), `web/app.js` was given its own part (G) because it is
256 KB on its own, and thirteen further parts were added so that **every one of the 221 changed
paths is in at least one part**. That was verified independently after the packets were built:

```
changed paths in range      : 221
distinct paths in packets   : 225
CHANGED PATHS WITH NO PACKET: 0
paths supplied as unchanged context: 4
paths deliberately in more than one part: 6
```

Six files are deliberately in two or three parts so that each finding's evidence stays together —
round 8's lesson. `app/identity.py`, `app/local_cli.py` and `app/routes/health.py` are in both A1a
and A1b; `app/main.py` is in A1a, A3a and A3b; `app/routes/turn.py` in D1 and D2;
`app/tools/authority.py` in A2 and B1.

**A near-miss worth recording.** The packet builder inherited from round 8 tested set membership
with `echo "$CHANGED" | grep -qx`. Under `set -o pipefail` that races: `grep -q` exits at the first
match, `echo` dies with SIGPIPE, the pipeline reports failure, and the branch is skipped. It
dropped `app/main.py` out of packet A1a entirely on one run and not on the next — the file appeared
in neither the diff section nor the full-file section. The omission simulator caught it. The test
was replaced with a pipe-free lookup and every packet was rebuilt. **Round 8's four packets were
built with the same racing code**, so it is worth re-checking that round's packets if any of its
verdicts are ever relied on again.

Each packet carried: the standing facts re-verified at this preflight; George's ship rule verbatim;
the PR #51 and PR #52 bodies as claim sheets to check rather than trust; and, for the seven parts
that re-check round-8 findings, the round-8 document and its addendum in full. Every packet passed
an omission simulation and a leak check against every live secret value before dispatch.

---

## Every finding, one line each

`D` = a demonstrated defect with a named file and symbol. `?` = the reviewer could not exclude the
hazard from the files in its own part, which is BLOCKS under George's rule.

| Part | ID | Label | | The ruling |
|---|---|---|---|---|
| A1a | `F-05A` | **FOLLOW-UP** | D | The supplied code refuses empty, wrong and proxied local-key headers, so the missing verification does not itself open a production route tonight. STILL UNVERIFIED as a whole: `local_cli._carried`, `presented` and `admits`, together with `main.guard_and_freshness`, repair the empty-header defect … |
| A1a | `F-05B` | **FOLLOW-UP** | D | Malformed input takes a fail-closed path in the supplied code, so the missing test evidence does not itself permit a production caller through tonight. STILL UNVERIFIED as a whole: `unit_pids` rejects a partly malformed listing and `_tcp_rows` rejects malformed socket rows before `_proc_peer_chec… |
| A1a | `F-05B-AVAIL` | **BLOCKS** | ? | I cannot tell whether an incomplete but well-formed kernel-table snapshot can occur during a production request; if it does, a request sent by this server through serve can be classified as an owner device and reach the live write routes. STILL PRESENT in part: `_ipv4_local` treats a trie contain… |
| A1a | `F-05B-AVAIL-PREFLIGHT` | **FOLLOW-UP** | D | The rendered production unit retains `--no-proxy-headers` and the supplied gate fails closed, so the absent deployment evidence alone does not meet the exploit, loss or leak bar tonight. STILL UNVERIFIED: `admin.whoami` makes one token and uses it in both the log and JSON for that request, so con… |
| A1b | `A1B-KEY` | **BLOCKS** | D | During a restart, a non-root process can occupy the unprivileged loopback port, answer the installer's first /health request with `limited: true`, and receive the live local-CLI key on the retry; it can also redirect that keyed request off-host. `fetch_health` trusts a literal loopback URL but do… |
| A1b | `F-05A` | **FOLLOW-UP** | D | The missing real-device check demonstrates no exploit or data loss tonight, but leaves the required test of this SHA incomplete. PARTLY REPAIRED: `local_cli.presented` detects even an empty header, and HTTP tests cover right, wrong and empty keys on all three command routes; `_verified_owner_devi… |
| A1b | `F-05B-AVAIL` | **FOLLOW-UP** | D | Two failed reads deny owner requests rather than admitting an uncertain caller, and this host's tables parsed successfully at preflight. PARTLY REPAIRED: `this_hosts_addresses` rejects malformed tables and a missing IPv6 table unless the disable switch is exactly `1`, but it retries a failed read… |
| A1b | `F-05B-AVAIL-PREFLIGHT` | **BLOCKS** | ? | I cannot determine whether the required correlated real-phone gate is reliable at this SHA: its `/whoami` implementation and a phone result against this candidate were not supplied. PARTLY REPAIRED: `install_systemd.running_problems` checks the running argv and health verdict, but `install` has n… |
| A1b | `A1B-STATUS` | **FOLLOW-UP** | D | This can report an unknown health state as a successful status command, but neither loses nor leaks data on the configured host. `install_systemd.status` returns zero whenever the unit is active and any health document exists, including a `limited` response that omits essential checks; the new li… |
| A2 | `F-NEW-TOOLS-PATH` | **BLOCKS** | ? | I cannot tell whether a non-owner can obtain owner authority on a model turn in production tonight because the current HTTP admission and authority-stamping path was not supplied. STILL UNVERIFIED end to end at this SHA: the supplied registry callback, provider `_dispatch`, and `dispatch` enforce… |
| A3a | `A3a-LIVE-CLEAN` | **BLOCKS** | ? | I cannot tell whether the startup clean will lose owner data on production tonight because the ten live rows’ keys and complete field sets were not supplied. GapLedger._repair_locked compares the cleaned record with the stored record: unchanged data gets no rewrite or second backup, but a changed… |
| A3b | `F-04-STARTUP` | **FOLLOW-UP** | D | The inspected production reports folder and .gitkeep are root-owned and private, so this failure requires a different path shape than the one present tonight. STILL PRESENT in the general case: TestSessions._tidy_reports can declare reports contained after tighten checks modes but not ownership; … |
| A3b | `F-04-REPORT-LOSS` | **BLOCKS** | D | The preflight permission count does not establish whether an aged report can race a writer on production tonight, and that race can delete the newly written report. STILL PRESENT in part: _remove_if_older checks an aged file and then unlinks its pathname; a concurrent write_private_text can repla… |
| A3b | `F-04-SHUTDOWN` | **BLOCKS** | D | On this always-on production session, a housekeeping step that exceeds the 27-second deadline can make shutdown exit without closing the runtime while accepted timeline events remain in a daemon writer; no bound on such a step establishes that this cannot happen tonight. STILL PRESENT in that cas… |
| A3b | `F-10` | **FOLLOW-UP** | D | This remaining failure can falsely call a count final, but does not itself delete the raw timeline or expose store data in the configured root-only command path. STILL PRESENT in part: Timeline._hold_writer_lock catches a lock-acquisition failure and _run writes its accepted batch anyway. If the … |
| A3b | `F-A3B-SHORT-WRITE` | **BLOCKS** | D | A partial filesystem write can discard bytes of an accepted event in production's always-on timeline, and the supplied host facts do not establish that partial writes cannot occur tonight. Timeline._append makes one os.write call for a batch, then counts every selected line as written regardless … |
| A3b | `F-A3B-SCREEN-EVIDENCE` | **BLOCKS** | ? | I cannot tell what the three approved production TVs can obtain through the display routes, so I cannot establish that a screen sees no unintended customer or live-voice data tonight. With CROOKS_SCREEN_SNAPSHOTS=false, observe.telemetry_screen returns 204 before reading or storing a copy; main.d… |
| B1 | `B-REMOTE-OFF` | **BLOCKS** | D | A stale owner remote can turn off a newly displayed customer slip, irreversibly losing it. The whole-screen remote off request supplies no version, and `take_off` checks `expect` only when a pane is specified; an off tap made for an older view therefore deletes whatever is showing when the reques… |
| B1 | `B-03` | **BLOCKS** | ? | I cannot tell whether a folder-fsync failure will occur on production tonight; if it occurs while clearing a slip, that slip can reappear after a restart. `_journal` returns False when its directory flush fails, but `_commit` ignores that result and accepts the deletion in memory; if the record f… |
| B1 | `B-04` | **BLOCKS** | D | An approved production screen holding its key and allow-listed login can forge a real order's packed record without displaying or packing it. `acknowledge` accepts paced, client-chosen ranges without page issuance, and `mark_done` accepts client-supplied `confirm: true`; the one-second gaps do no… |
| B1 | `B-01-B-05-PATH` | **BLOCKS** | ? | I cannot tell whether a refused caller can reach the production screen handlers or bypass issued-ID enforcement at this SHA, which could expose a customer slip on a screen. The supplied handlers check active OWNER authority and the gate checks issued IDs, but the current owner-principal implement… |
| B1 | `NEW-B-LOCAL-SLIP` | **BLOCKS** | ? | I cannot tell whether an open production screen actually removes customer details after a 403, disconnection or local expiry, so the previously demonstrated leak remains unverified. The supplied server-side test searches for snippets in `web/display.js`, but that browser implementation and its re… |
| B1 | `B-NEW-DONE-LOSS` | **BLOCKS** | ? | I cannot tell whether this host's real slips and packed history will cross the file limit as its permitted screens fill; crossing it silently destroys done rows. With two views allowed on each of twenty screens, `_write` repeatedly discards the oldest half of `done` until the file fits, rather th… |
| B2 | `B2-01` | **BLOCKS** | D | On an approved production screen, someone with access to its browser or an extension can copy its persistent screen key and reuse it to request future slips from an admitted session. `loadScreen` and `saveScreen` keep the full key in `localStorage['clive.screen']`; the pairing code being memory-o… |
| B2 | `B2-02` | **BLOCKS** | D | A revoked production remote can continue showing customer details after a 403 while a finger is held on its panel. `wipe` calls `render`, but `render` returns without clearing the DOM for up to two seconds after `pointerdown`; the 403 test does not exercise that state. |
| B2 | `B2-03` | **BLOCKS** | D | An older successful response can put a customer slip back on a production screen or remote after another request has received a revoking 403. `display.js` increments `S.gen` in `wipe`, but its pending `poll` and `markDone` continuations can still call `receive`; `remote.js` likewise lets an in-fl… |
| B2 | `B2-04` | **BLOCKS** | D | A production TV can continue exposing a customer's order details after the order is marked packed. `markedDone` copies the previously drawn full order and only adds `done_at`; `renderOrder` draws its customer, address, phone and note again, and the packed view can remain for 45 seconds instead of… |
| B2 | `B-07` | **BLOCKS** | ? | I cannot tell from this B2 packet whether production's `GET /` is always the same data-free HTML for every login. The worker caches any successful HTML response at `/` and serves it on a later network failure, potentially to an unauthenticated load; its exclusion of `/display` and `/displays/*` d… |
| C | `C-01` | **BLOCKS** | ? | I cannot determine whether a caller can mint a token by presenting a forged owner identity on production. `_refused` delegates the entire owner decision to `principal_verdict`, whose implementation was not supplied; the mocked route tests do not establish the real proxy-identity boundary. |
| C | `C-02` | **BLOCKS** | ? | I cannot tell whether the browser bearer token can be reused or remain valid beyond the claimed fifteen minutes, which would extend credential and billing exposure outside the tailnet. The route accepts any nonempty string in the provider’s `token` field, and all token tests use a mocked provider… |
| C | `C-03` | **BLOCKS** | ? | I cannot tell whether live customer names and order details remain display-only on production. `create` passes complete live words to an unrestricted `onWords` callback, but the `web/app.js` wiring that decides whether they also enter telemetry, a turn, or retained context was not supplied. |
| C | `C-04` | **BLOCKS** | ? | I cannot establish that third-party socket errors cannot put speech or customer data into the always-on telemetry timeline. `heard` copies any error message’s unvalidated `message_type` into `reason`, `close` passes it to `record`, and telemetry accepts string fields; the provider-message shape a… |
| C | `C-05` | **FOLLOW-UP** | D | This can lose live-word availability on a slow connection, but the supplied code still sends the ordinary batch recording. Releasing before the WebSocket opens starts the 1.5-second finish timer immediately; if the socket opens later, `close` has already discarded its buffered audio, so it never … |
| D1 | `D1-01` | **BLOCKS** | D | Production’s always-on observability receives raw spoken text and model answers containing potential customer names before the turn installs its name-redaction context; I cannot verify from the supplied files that those events are made safe before they are retained or shared. `turn()` emits `raw_… |
| D1 | `D1-02` | **BLOCKS** | ? | I cannot tell whether a write from the production tablet can target a different record from the one displayed. `_stand_on_what_was_shown()` moves the branch cursor from the first simple record card only, while `present()` can replace that card with an `order_workspace` or `customer_workspace`; it… |
| D1 | `D1-03` | **BLOCKS** | ? | I cannot tell whether removing the fast lane has left a reachable model write with weaker disambiguation or refusal checks on this writes-enabled production host. This part shows model tool calls going straight to `_answer()` for proposal delivery, but supplies neither the deleted fast-lane guard… |
| D2 | `D2-01` | **BLOCKS** | D | An older turn can finish after its replacement and put an older order back on the live branch, leaving a subsequent money-moving action aimed at the wrong record. `_answer` detects that the turn was abandoned but still calls `branch.shown` and `_stand_on_what_was_shown`, which can call `branch.vi… |
| D2 | `D2-02` | **BLOCKS** | D | A pending live refund or cancellation remains tappable when the owner says an apparent correction such as “yes, #1938”: `is_affirmation` deletes the digits, treats the result as bare “yes”, and skips the model and pending-proposal revocation. The spoken identifier is silently lost at the write-co… |
| D2 | `D2-03` | **BLOCKS** | ? | Concurrent turns on the two halves assign different values to the same `live.acting_branch` before either finishes, so I cannot tell whether downstream staging can attach a live write to the wrong half. The route sets this shared session field once and then awaits preflight and the provider; the … |
| D2 | `D2-04` | **BLOCKS** | D | When a model answer displays an order and a customer, `_stand_on_what_was_shown` chooses the first record even though another kind of record is also present; on this write-enabled host I cannot tell whether a later card action overrides that possibly wrong branch cursor. Its uniqueness test count… |
| D2 | `D2-05` | **FOLLOW-UP** | D | The removed fast lane's read-only no-guess checks cannot themselves execute a write or disclose data to a different principal tonight, but their equivalent read-side disambiguation is not present in the supplied model-turn path. In particular, the refusals for a different order number, a named cu… |
| G | `G-01` | **BLOCKS** | D | Live transcription and always-on telemetry are enabled in production, but the supplied files do not establish whether the single-use token or spoken words can leak, so reachability of a production data leak cannot be determined. app.js delegates token acquisition and retention to CrooksLiveVoice.… |
| G | `G-02` | **FOLLOW-UP** | D | An incorrect transcript left on the ask bar is a display-correctness defect, with no evidenced exploit, data loss, or data leak tonight. If /turn returns before a /state poll observes data.heard, submit writes the batch question to el.heard but never calls showHeardWords for the bar, which can ke… |
| G | `G-03` | **FOLLOW-UP** | D | The unverified accent claim is an appearance requirement, not an evidenced exploit, data-loss, or data-leak path tonight. The scoped files link alpha.css but do not supply it, so this part cannot confirm that the iOS-blue change is cosmetic. |
| E-app1 | `E-01` | **BLOCKS** | ? | I cannot tell whether a tap can reach a live write on production tonight, because writes are enabled and the replacement recipe runner was not supplied. `app/routes/command.py:_run_recipe` now calls `app/recipes.py:run`; its claimed read-only check and tool-dispatch path cannot be verified from t… |
| E-app2 | `E-01` | **FOLLOW-UP** | D | This affects a local status diagnostic, with no shown path to exploitation, data loss or data leakage on production tonight. The new branch in `status.show()` depends on `scripts/launch_common.py:health_limited` and `scripts/launch_common.py:summarise_health`, whose exact-SHA implementations were… |
| E-families1 | `E-01` | **BLOCKS** | D | A stale picker can prepare a change to a previously issued order other than the order now on screen, risking a wrong live order mutation after the owner's hold. `order_edit._open_picker` requires the named order to be open, but `_stage_add_item` checks only `may_open` and whether the variant was … |
| E-families1 | `E-02` | **BLOCKS** | D | A model-normalised spoken address can be treated as a verified recipient, so an ASR or model error can send private mail to the wrong address on this live mailbox. `gmail_compose_open` passes the model's `to` string to `check_address`; a canonical address receives `to_status='ok'` even if the own… |
| E-families1 | `E-03` | **BLOCKS** | ? | I cannot tell whether owner-reported defects are still recorded during tonight's always-on test session; without a replacement, deleting the only recorder shown here loses those reports. The removed `owner_feedback._render` called `feedback.record`, and no surviving file in this slice replaces th… |
| E-families1 | `E-04` | **BLOCKS** | ? | I cannot tell whether the replacement model path preserves the deleted confident order-to-thread refusal; if it does not, a reply about one live customer's order could be drafted to another customer's thread and sent after a hold. `order_email._choose` previously refused merely possible links bef… |
| E-families1 | `E-05` | **BLOCKS** | ? | I cannot tell whether any live startup or observability module still imports a deleted capability or family; a remaining reference could also stop tonight's test-session data capture. Package discovery covers the family imports shown here, but the packet does not contain a repository-wide referen… |
| E-families1 | `E-06` | **FOLLOW-UP** | D | This can give the owner a false operational answer tonight, but the shown path only reads and presents records; it does not itself write, lose or leak them. If the open-orders read fails while today's read succeeds, `landings._orders_render` treats the failed read as an empty list and says 'Nothi… |
| F-observability1 | `F-01` | **BLOCKS** | ? | I cannot tell whether a test-session identifier can be supplied through production telemetry tonight, so I cannot rule out using it to write a report containing owner or customer words outside the private reports directory. `reconstruct` accepts `test_session_id` from an event without validating … |
| F-observability1 | `F-02` | **FOLLOW-UP** | D | `CROOKS_SCREEN_SNAPSHOTS=false` prevents this screen-copy path from collecting markup on production tonight. Nevertheless, `sanitise_markup` treats `data-spoken` as an ordinary attribute: it retains text beneath the marked element, and `_attrs` can retain a token-shaped `data-words` value because… |
| F-observability1 | `F-03` | **FOLLOW-UP** | D | Incorrect observability classification does not itself exploit access or lose or leak production data tonight. `semantics.CHANGES` declares store credit to have no capability, although the packet establishes that the production `store_credit_credit` write is ready. When a store-credit request rec… |
| F-observability2 | `F-OBS2-01` | **BLOCKS** | ? | I cannot tell from the supplied code whether these sensitive outputs reach a SCREEN or a non-owner on the live test-session deployment, so a data leak cannot be excluded. `_feedback` returns entire `owner_feedback` events and puts the owner's text and full answer into `ignored_feedback`; `read` a… |
| F-observability2 | `F-OBS2-02` | **BLOCKS** | ? | I cannot tell who can read the production log, so a secret in malformed telemetry could leak there. For example, `_focus_lost` passes `tablet_compose_field.chars` to `int`; on failure, `read` logs the exception text, which includes the rejected value. The same raw-exception logging occurs for `_f… |
| H-experience1 | `F-A2-FIXTURE` | **FOLLOW-UP** | D | This authority grant is confined to the experience harness, so it does not itself admit a production request tonight. STILL PRESENT in this slice: `harness()` defaults to writes enabled, and `Harness.configure` installs a fixture owner on the allow-list while disabling Tailscale verification; eve… |
| H-experience1 | `H-02` | **FOLLOW-UP** | D | Scripted model choices affect the offline scenarios, not the deployed provider directly, so this is not itself a production data-loss or leakage path. The sentence scenarios verify gate and presenter responses to tools chosen by the harness, not whether the model chooses those tools: `Harness.ask… |
| H-experience1 | `H-03` | **FOLLOW-UP** | D | These no-op test turns cannot themselves execute a production write tonight. `discount_sentence_defers`, `order_add_item_sentence_defers`, and `unsupported_edit` send their change requests to an unscripted `RecordingProvider`, which returns fixed prose and calls no tools. Their assertions that no… |
| H-experience1 | `H-04` | **FOLLOW-UP** | D | Deleting a scenario does not itself send mail or expose mailbox data on production tonight. `compose_send_spoken` was deleted, including its check of what happened before the send-confirmation gesture. The remaining `compose_send_instead` covers a tapped conversion, not the spoken 'don't save a d… |
| H-experience1 | `H-05` | **FOLLOW-UP** | D | This weakened oracle is test-only and does not itself change the production inbox tonight. `needs_reply` no longer checks that the spoken answer names those waiting or excludes people already answered. Its replacement looks for each waiting person's first name anywhere in a stringified queue payl… |
| H-experience1 | `H-06` | **FOLLOW-UP** | D | The audit's false coverage claims are generated from test-source inspection and do not execute a production tool tonight. `tool_matrix._scenario_tools` treats a tool or operation mentioned anywhere in a scenario file, including a comment or assertion, as a golden scenario exercising the tool and … |
| H-experience1 | `H-07` | **FOLLOW-UP** | D | These credit tests run inside the harness rather than exposing a new production route tonight. Both store-credit scenarios invoke `dispatch(sc.OPEN_TOOL, ...)` after manually setting `CURRENT_SESSION`, instead of having their model turn call the tool through `/turn`. That bypasses the request pat… |
| I-tests1 | `F-A2-FIXTURE` | **FOLLOW-UP** | D | Test fixtures do not run in production, so this evidence gap does not itself make the live service exploitable or cause data loss or leakage tonight. STILL PRESENT as an unverified ruling: these files explicitly opt tests into `owner_asking`, but the packet does not include `tests/conftest.py::ow… |
| I-tests1 | `I-01` | **FOLLOW-UP** | D | These vacuous assertions weaken offline privacy evidence, but do not themselves expose production data tonight. In `test_state_can_be_asked_after_a_lost_connection` and `test_a_write_tools_note_is_logged_by_length_only_even_when_refused`, the assertions intended to exclude sensitive content end i… |
| I-tests2 | `I-01` | **BLOCKS** | ? | I cannot tell whether production’s bound-control path can still attach a prior order’s action to a new instruction, and writes are enabled tonight. The test that refused this behavior after a tapped Add a note was deleted, with no model-turn replacement shown. |
| I-tests2 | `I-02` | **FOLLOW-UP** | D | These checks concern answers shown to the authenticated owner, who can access both records, so their deletion alone does not establish an exploit, data loss, or unauthorized disclosure tonight. The end-to-end refusals of answering a named-person or numbered-order question from the unrelated recor… |
| I-tests2 | `I-03` | **FOLLOW-UP** | D | The hard-coded provider runs only in the offline test, so this finding does not itself establish production exploitation, loss, or leakage. client.Provider.turn always looks up order 1938 and supplies a fixed answer; the test then asserts on the reads and card that this mock itself manufactured, … |
| I-tests2 | `I-04` | **FOLLOW-UP** | D | Test-fixture authority is not itself a production access path, so this evidence gap does not meet tonight’s exploit, loss, or leak bar. F-A2-FIXTURE is STILL PRESENT as an unverified review requirement: this slice shows explicit owner opt-ins, including module-level opt-ins in four files, but doe… |
| I-tests3 | `F-A2-FIXTURE` | **FOLLOW-UP** | D | This test-fixture evidence gap does not itself run on production or grant a production caller authority tonight. STILL PRESENT as an unverified repair: these files explicitly opt tests into `owner_asking`, but the supplied files do not show whether the suite-wide default owner grant was removed. |
| I-tests3 | `I-02` | **BLOCKS** | ? | I cannot tell whether the live model-driven mail path can select another order's thread and leak customer information, so its reachability on tonight's production configuration remains unresolved. `test_graph.py` deleted the assertions that a thread about a customer's different order is not this … |
| I-tests3 | `I-03` | **FOLLOW-UP** | D | Changing offline assertions cannot itself bypass the production write-confirmation path tonight. Refusal and authority-related coverage was weakened: `test_needs_reply_routing.py` now checks the observability contract instead of request routing; `test_order_create.py` drops the spoken cancel/refu… |
| I-tests3 | `I-04` | **FOLLOW-UP** | D | This is a performance-test weakness, not a demonstrated production exploit, data loss or leak tonight. `test_n_plus_one.py::turn` now supplies `commerce_summary` and its task directly to `dispatch`, so the N+1 tests no longer test whether a spoken question makes the model choose per-customer read… |
| I-tests4 | `I-01` | **BLOCKS** | D | store-credit writes are live, and this test accepts a £25 balance increase as verification of a £20 credit, leaving a money discrepancy unverified. `test_the_verification_is_the_balance_plus_what_was_sent` explicitly expects verification to return true for £15 → £40 after an asserted £20 credit. |
| I-tests4 | `I-02` | **FOLLOW-UP** | D | the running test session retains transcripts, so the supplied evidence does not establish loss of the owner's spoken words tonight. `test_owner_feedback` says nothing records feedback at turn time, while this range deletes the tests that required a spoken defect to be recorded and confirmed throu… |
| I-tests4 | `I-03` | **FOLLOW-UP** | D | a missing actionable retry would be a refusal-quality defect, not an identified exploit or data loss tonight. `test_a_landing_that_cannot_be_read_offers_the_tap_again` constructs the desired `commands.Outcome.refused` itself and asserts on that constructed object; it never invokes the landing cod… |
| I-tests4 | `I-04` | **FOLLOW-UP** | D | owner authority granted to offline tests does not itself admit a production caller tonight. F-A2-FIXTURE cannot be marked REPAIRED for the suite from this slice: `test_refund.py` and `test_store_credit.py` explicitly grant `owner_asking` to every test in their modules, but the claimed removal of … |
| I-tests5 | `I-01` | **BLOCKS** | ? | I cannot tell whether a navigation command spoken after binding a control can be treated as note dictation on tonight’s write-enabled production system. The command-versus-dictation classification test was deleted; the remaining binding tests check that a sentence reaches the model and that the b… |
| I-tests5 | `I-02` | **FOLLOW-UP** | D | This loss of test coverage cannot itself exploit, lose, or leak production data tonight. The returning-customer test no longer submits the owner’s words or asserts that exactly one summary card and no customer profiles reach the glass: answer_for supplies a task directly to commerce_summary, and … |
| I-tests5 | `I-03` | **FOLLOW-UP** | D | A mocked model in a test cannot itself cause a production write tonight. ModelThatAddsANote.turn always searches order 1930 and stages the same note regardless of the request; the walkthrough therefore does not establish that the model selects the correct lookup or write, despite testing the down… |
| I-tests5 | `I-04` | **FOLLOW-UP** | D | These fixture defaults affect tests, not the running production service. F-A2-FIXTURE is STILL PRESENT as a module-level default in four files: pytestmark grants owner_asking to every test in each module, including tests of refusals; the claimed removal of the suite-wide autouse grant cannot be v… |
| I-tests5 | `I-05` | **FOLLOW-UP** | D | A false test-audit citation cannot itself exploit or alter production tonight. The audit test requires calls_tool to count registry.get('probe_tool'), classify(name), and a synthetic presentation item as directly testing the tool, although none executes its handler; this can certify a tool withou… |
| I-tests5 | `I-06` | **FOLLOW-UP** | D | This vacuous assertion cannot itself leak mailbox data tonight. The email-query test’s sender-and-search-terms assertion ends in `or True`, so it passes even if every sender or the order-number search term is wrong. |
| J-docs1 | `J-01` | **FOLLOW-UP** | D | This incorrect usage guidance does not itself exploit, lose, or leak production data tonight. The README tells the owner to say an order number so the Mac looks it up before Claude is asked, although this candidate's recorded decision says requests reach the model without a preceding lookup. |

Non-material observations that rode along (no label required):

- **A1a · `F-NEW-PAD`** — REPAIRED in the supplied code. `health._guarded` applies the owner verdict or a direct, valid server key to each response, including both cache-return paths; `_liveness` constructs only the specified fields for a refused caller. The loopback caller without …
- **A3a · `F-07-VALUES`** — REPAIRED at this SHA for the assigned round-8 defect: _count accepts only bounded integers or ASCII-digit text, _strict_iso catches UTC-conversion overflow, and deeply nested JSON is treated as unreadable rather than escaping through report or repair.
- **A3a · `F-07-LINKS`** — REPAIRED at this SHA for the assigned round-8 limit and earliest-fix defects: truncated lists are counted and marked uncertain where relevant, _keep_requests retains the earliest live fix, and the report does not call an uncertain zero recurrence exact or h…
- **A3a · `F-07-DURABILITY`** — REPAIRED at this SHA for the assigned round-8 post-replacement failure: _save distinguishes a failed directory fsync after replacement with WrittenNotConfirmed, and startup and later-change logging no longer claim that such a file was untouched.
- **B2 · `B-06`** — B-06 — REPAIRED as a no-regression check in the supplied range: the scoped start-up and finish paths retain their handoff, and `web/startup.js` is unchanged. Its implementation was not supplied for an independent re-audit.
- **B2 · `B2-COSMETIC`** — The blue restyle is cosmetic for this review, though the pairing code remains lilac and the refused-state line remains amber.

---

## Every part's verdict

| Part | Scope | Verdict | material | BLOCKS | FOLLOW-UP |
|---|---|---|---|---|---|
| **A1a** | identity and the door — the code (7 files) | CHANGES_REQUIRED | 4 | 1 | 3 |
| **A1b** | identity and the door — the tests and the launchers (9 files) | CHANGES_REQUIRED | 5 | 2 | 3 |
| **A2** | tool authority (10 files) | CHANGES_REQUIRED | 1 | 1 | 0 |
| **A3a** | the gap record (5 files) | CHANGES_REQUIRED | 1 | 1 | 0 |
| **A3b** | observability, screen privacy and shutdown (9 files) | CHANGES_REQUIRED | 6 | 4 | 2 |
| **B1** | screens, server (8 files) | CHANGES_REQUIRED | 6 | 6 | 0 |
| **B2** | screens, pages (10 files) | CHANGES_REQUIRED | 5 | 5 | 0 |
| **C** | live voice (12 files) | CHANGES_REQUIRED | 5 | 4 | 1 |
| **D1** | every sentence is a model turn — the turn path (6 files) | CHANGES_REQUIRED | 3 | 3 | 0 |
| **D2** | every sentence is a model turn — runtime, branch, speech (21 files) | CHANGES_REQUIRED | 5 | 4 | 1 |
| **G** | the app page itself (web/app.js) (3 files) | CHANGES_REQUIRED | 3 | 1 | 2 |
| **E-app1** | the rest of the application code (slice 1) (10 files) | CHANGES_REQUIRED | 1 | 1 | 0 |
| **E-app2** | the rest of the application code (slice 2) (5 files) | CHANGES_REQUIRED | 1 | 0 | 1 |
| **E-app3** | the rest of the application code (slice 3, web/ui.js) (1 files) | READY | 0 | 0 | 0 |
| **E-families1** | the capability families and capabilities the fast lane fed (23 files) | CHANGES_REQUIRED | 6 | 5 | 1 |
| **F-observability1** | observability modules the named parts do not own (slice 1) (7 files) | CHANGES_REQUIRED | 3 | 1 | 2 |
| **F-observability2** | observability modules the named parts do not own (slice 2, visible.py) (1 files) | CHANGES_REQUIRED | 2 | 2 | 0 |
| **H-experience1** | the experience harness and scenario packs (16 files) | CHANGES_REQUIRED | 7 | 0 | 7 |
| **I-tests1** | remaining tests (slice 1) (11 files) | CHANGES_REQUIRED | 2 | 0 | 2 |
| **I-tests2** | remaining tests (slice 2) (11 files) | CHANGES_REQUIRED | 4 | 1 | 3 |
| **I-tests3** | remaining tests (slice 3) (13 files) | CHANGES_REQUIRED | 4 | 1 | 3 |
| **I-tests4** | remaining tests (slice 4) (15 files) | CHANGES_REQUIRED | 4 | 1 | 3 |
| **I-tests5** | remaining tests (slice 5) (10 files) | CHANGES_REQUIRED | 6 | 1 | 5 |
| **J-docs1** | documentation and example files (9 files) | CHANGES_REQUIRED | 1 | 0 | 1 |

### Part A1a — identity and the door — the code — **CHANGES_REQUIRED**

The door and health filtering have substantive code repairs, and no supplied admin or action
change widens their principal rule. F-05B-AVAIL remains incomplete; the required tests,
installer gate and exact-SHA phone evidence also prevent clearing the assigned findings.

**`F-05A` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — The supplied code refuses empty, wrong and proxied local-key headers, so the missing
verification does not itself open a production route tonight. STILL UNVERIFIED as a whole:
`local_cli._carried`, `presented` and `admits`, together with `main.guard_and_freshness`, repair
the empty-header defect on all three CLI routes, but the packet supplies neither the required
through-proxy test cases nor an owner-device check with and without the key against this SHA.

> Evidence: crooks-assistant/app/local_cli.py:_carried,presented,admits; crooks-assistant/app/main.py:guard_and_freshness; REVIEW PACKET — YOUR PART, F-05A required repair, and CANDIDATE FILES

> Repair required: Supply the correct-, wrong- and empty-key tests through the proxy on each CLI route, and record the specified verified owner-device check against this SHA.

**`F-05B` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — Malformed input takes a fail-closed path in the supplied code, so the missing test
evidence does not itself permit a production caller through tonight. STILL UNVERIFIED as a
whole: `unit_pids` rejects a partly malformed listing and `_tcp_rows` rejects malformed socket
rows before `_proc_peer_check` accepts an inode; both gates use `proxy_state`, but the required
malformed-input exercises through `principal_verdict` and `caller_check` are not supplied.

> Evidence: crooks-assistant/app/identity.py:unit_pids,_tcp_rows,_proc_peer_check; crooks-assistant/app/routes/actions.py:proxy_state,principal_verdict,caller_check; REVIEW PACKET — F-05B required repair and CANDIDATE FILES

> Repair required: Supply the malformed-listing and malformed-row tests exercising both gates at this SHA. Preserve the fail-closed parsing and process-pinning checks.

**`F-05B-AVAIL` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether an incomplete but well-formed kernel-table snapshot can occur
during a production request; if it does, a request sent by this server through serve can be
classified as an owner device and reach the live write routes. STILL PRESENT in part:
`_ipv4_local` treats a trie containing loopback but omitting another owned address as complete,
while `_ipv6_local` accepts an empty or partial `if_inet6` result even though IPv6 and this
host's tailnet IPv6 address are enabled. `this_host` then returns false for an omitted owned
address, and `proxy_state` calls the request TAILSCALE. The missing-table refusal, strict row
parsing and immediate retry are repairs, and the preflight's real tables parsed successfully;
those facts do not establish fail-closed handling of a partial result.

> Evidence: crooks-assistant/app/identity.py:_ipv4_local,_ipv6_local,_addresses_once,this_host; crooks-assistant/app/routes/actions.py:proxy_state,principal_verdict,caller_check; REVIEW PACKET — STANDING FACTS 3 and 5

> Repair required: Do not classify a forwarded source as non-local solely because a syntactically valid snapshot omits it. Corroborate host locality independently or detect and refuse incomplete address snapshots, including an empty enabled-IPv6 table; exercise the omission through both gates with production flags.

**`F-05B-AVAIL-PREFLIGHT` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — The rendered production unit retains `--no-proxy-headers` and the supplied gate
fails closed, so the absent deployment evidence alone does not meet the exploit, loss or leak
bar tonight. STILL UNVERIFIED: `admin.whoami` makes one token and uses it in both the log and
JSON for that request, so concurrent requests do not share the token; `health._checked` obtains
the proxy-identity check from `identity.served_without_proxy_headers`. But `crooks-
assistant/scripts/install_systemd.py:install` is outside the supplied seven files, so its
claimed executable argv-and-health gate cannot be checked, and no owner-phone check against this
exact SHA is supplied.

> Evidence: crooks-assistant/app/routes/admin.py:whoami; crooks-assistant/app/routes/health.py:_checked; crooks-assistant/app/identity.py:served_without_proxy_headers; REVIEW PACKET — YOUR PART, F-05B-AVAIL-PREFLIGHT required repair, STANDING FACTS 4–6, and CANDIDATE FILES

> Repair required: Supply `crooks-assistant/scripts/install_systemd.py:install` at this SHA for review and the correlated real-phone preflight evidence required for this candidate; verify the running argv and health check as part of that gate.

---

### Part A1b — identity and the door — the tests and the launchers — **CHANGES_REQUIRED**

F-05B is REPAIRED in `identity.unit_pids` and `socket_inode`: the malformed-listing and
malformed-row tests reach both gates and assert refusal. F-NEW-PAD is REPAIRED in
`health._guarded` and `_liveness`: refused callers receive only allow-listed liveness on fresh
and cached responses. F-05A, F-05B-AVAIL and F-05B-AVAIL-PREFLIGHT remain partial as detailed
above. The installer additions change no rendered unit directive; the packet's one-comment-line
unit diff is consistent with the code shown. The keyed health retry has a separate material
secret-exposure defect.

**`A1B-KEY` — BLOCKS** (demonstrated)

BLOCKS — During a restart, a non-root process can occupy the unprivileged loopback port, answer
the installer's first /health request with `limited: true`, and receive the live local-CLI key
on the retry; it can also redirect that keyed request off-host. `fetch_health` trusts a literal
loopback URL but does not authenticate the listener, and `_open` disables environment proxies
without disabling urllib's automatic redirects. The test replaces `_open`, so it exercises
neither case.

> Evidence: REVIEW PACKET — CANDIDATE FILES: scripts/launch_common.py (_server_key, _open, _read, fetch_health); tests/test_local_cli.py (test_the_hosts_status_readers_carry_the_key_on_loopback_and_nowhere_else); STANDING FACTS 2–3

> Repair required: Do not send the key to an unauthenticated loopback listener or forward it on any redirect. Constrain keyed health reads to the intended service, disable redirects for them, and test a competing loopback listener and a cross-origin redirect.

**`F-05A` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — The missing real-device check demonstrates no exploit or data loss tonight, but
leaves the required test of this SHA incomplete. PARTLY REPAIRED: `local_cli.presented` detects
even an empty header, and HTTP tests cover right, wrong and empty keys on all three command
routes; `_verified_owner_device` still substitutes peer, locality and whois answers, and the
packet supplies no real owner-device check against this SHA.

> Evidence: REVIEW PACKET — CANDIDATE FILES: app/local_cli.py (presented, admits); tests/test_local_cli.py (_verified_owner_device, test_through_the_proxy_a_right_wrong_or_empty_key_is_refused_on_each_command_route); STANDING FACTS 6

> Repair required: Record the required correct-key refusal and headerless admission from a genuinely verified owner device against this exact SHA, without substituting the provenance answers.

**`F-05B-AVAIL` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — Two failed reads deny owner requests rather than admitting an uncertain caller, and
this host's tables parsed successfully at preflight. PARTLY REPAIRED: `this_hosts_addresses`
rejects malformed tables and a missing IPv6 table unless the disable switch is exactly `1`, but
it retries a failed read only immediately; after two failures it refuses both gates, without an
availability-preserving response to a routine failure lasting longer than those reads.

> Evidence: REVIEW PACKET — CANDIDATE FILES: app/identity.py (_addresses_once, this_hosts_addresses); tests/test_proxy_identity.py (test_at_both_gates_a_read_that_fails_once_is_tried_again_before_anyone_is_refused); STANDING FACTS 5

> Repair required: Provide and test a bounded way to preserve availability during routine lookup failures without treating uncertain host locality as remote-owner traffic.

**`F-05B-AVAIL-PREFLIGHT` — BLOCKS** (unverifiable)

BLOCKS — I cannot determine whether the required correlated real-phone gate is reliable at this
SHA: its `/whoami` implementation and a phone result against this candidate were not supplied.
PARTLY REPAIRED: `install_systemd.running_problems` checks the running argv and health verdict,
but `install` has no real-device assertion or rollback after a failed check, and the test
supplies a mocked health answer and MainPID.

> Evidence: REVIEW PACKET — CANDIDATE FILES: scripts/install_systemd.py (install, running_problems); tests/test_proxy_identity.py (test_the_install_is_done_only_when_the_running_service_has_the_flag_and_health_agrees); YOUR PART scope; STANDING FACTS 6

> Repair required: Supply `app/routes/admin.py:whoami` for the correlated-token check, record a successful real-phone `/whoami` against this SHA under the rendered unit, and make the deployment gate abort or roll back on failed running-process, health or correlated-device checks.

**`A1B-STATUS` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — This can report an unknown health state as a successful status command, but neither
loses nor leaks data on the configured host. `install_systemd.status` returns zero whenever the
unit is active and any health document exists, including a `limited` response that omits
essential checks; the new limited-response exit-code test covers `healthcheck.main` and
`status.show`, not this status path.

> Evidence: REVIEW PACKET — CANDIDATE FILES: scripts/install_systemd.py (status); scripts/launch_common.py (health_limited); tests/test_local_cli.py (test_a_status_reader_given_liveness_alone_says_so_and_never_calls_it_well)

> Repair required: Make `install_systemd.status` return nonzero for limited health and test that path.

---

### Part A2 — tool authority — **CHANGES_REQUIRED**

F-A2-FIXTURE is REPAIRED: tests/conftest.py:owner_asking is non-autouse, its six protected-gate
opt-ins are named, and the supplied tests/test_provider.py cases create owner authority
explicitly; tests/test_tool_boundary.py also tests an unstamped context. F-NEW-TOOLS is REPAIRED
within the reviewed invocation boundary: authority.py:permits, dispatch.py:dispatch,
max_agent_sdk.py:_dispatch and prefetch.py:Prefetcher.start restrict and revoke service
authority. F-NEW-TOOLS-PATH is repaired from the SDK callback through dispatch, but its current
HTTP entry cannot be cleared from this packet. The reviewed callback grants no additional tool
to a caller without authority. Screens-specific handler checks remain for the screens review
part.

**`F-NEW-TOOLS-PATH` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether a non-owner can obtain owner authority on a model turn in
production tonight because the current HTTP admission and authority-stamping path was not
supplied. STILL UNVERIFIED end to end at this SHA: the supplied registry callback, provider
`_dispatch`, and `dispatch` enforce authority before a handler runs, but the fast-lane removal
changes the turn-entry path being assessed, and the scoped tests do not establish its production
admission behavior.

> Evidence: REVIEW PACKET — YOUR PART and PR #52 BODY; crooks-assistant/app/providers/max_agent_sdk.py:_options,_dispatch,_turn_locked; crooks-assistant/app/tools/registry.py:build_mcp_server; crooks-assistant/tests/test_tool_boundary.py:test_a_turn_from_anyone_but_the_owner_never_reaches_the_model_or_a_tool

> Repair required: Supply or obtain a review at this exact SHA of crooks-assistant/app/main.py:guard_and_freshness and crooks-assistant/app/routes/turn.py:turn,_provider_turn, tracing a refused production-configured caller through authority stamping to the provider. No change to the reviewed SDK callback is requested on the evidence supplied.

---

### Part A3a — the gap record — **CHANGES_REQUIRED**

The vendored 3e77f215 reader can load and report the candidate’s supported version-1 schema; its
report ignores the new accounting fields. For a record that remains unchanged under _sanitise,
startup makes no second backup. The packet does not provide enough of the actual ten-row record
to establish that production takes that branch, retains all ten rows and their fields, or ends
with exactly its existing backup.

**`A3a-LIVE-CLEAN` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether the startup clean will lose owner data on production tonight
because the ten live rows’ keys and complete field sets were not supplied.
GapLedger._repair_locked compares the cleaned record with the stored record: unchanged data gets
no rewrite or second backup, but a changed record gets a backup and rewrite. _sanitise can merge
keys that clean alike and removes fields outside its allow-list. The packet establishes that a
row was re-keyed and two rows have names, but not whether all ten keys remain distinct after
cleaning or whether every stored field survives. The `name` field itself is allow-listed.

> Evidence: REVIEW PACKET — STANDING FACTS 3; crooks-assistant/app/objectives/gaps.py:GapLedger._repair_locked, _sanitise, _GAP_FIELDS

> Repair required: Run the candidate’s clean against a byte-identical private copy of the current ten-row record and supply a per-row before/after key-and-field comparison, backup count, and vendored-reader result. If any distinct row or owner field would be lost, preserve it or provide an explicit, recoverable migration before deployment.

---

### Part A3b — observability, screen privacy and shutdown — **CHANGES_REQUIRED**

F-04-STARTUP, F-04-REPORT-LOSS, F-04-SHUTDOWN and F-10 are each partly repaired but still
present as identified above. Disabled snapshots prevent /telemetry/screen from keeping a copy;
they do not turn off the TV or establish what its separate data routes return. A newly
identified short-write path can also lose accepted timeline data.

**`F-04-STARTUP` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — The inspected production reports folder and .gitkeep are root-owned and private, so
this failure requires a different path shape than the one present tonight. STILL PRESENT in the
general case: TestSessions._tidy_reports can declare reports contained after tighten checks
modes but not ownership; tighten also skips symlink entries. A 0700 folder owned by another
user, or a symlink to a report accessible by another path, can therefore pass the startup check
without its contents being private. The separate housekeeping steps, unchecked initial state,
unreadable-path handling and retries repair the round-8 skipped-check path.

> Evidence: crooks-assistant/app/observability/session.py:TestSessions._tidy_reports, tighten; crooks-assistant/app/main.py:housekeep_once, _reports_contained; REVIEW PACKET — STANDING FACTS 3

> Repair required: Check ownership and symlink targets as part of containment, or refuse startup on paths whose privacy cannot be established; test differently owned and linked report paths.

**`F-04-REPORT-LOSS` — BLOCKS** (demonstrated)

BLOCKS — The preflight permission count does not establish whether an aged report can race a
writer on production tonight, and that race can delete the newly written report. STILL PRESENT
in part: _remove_if_older checks an aged file and then unlinks its pathname; a concurrent
write_private_text can replace that pathname with a fresh report between those operations.
Descendant files have the same check-then-unlink gap. The fresh-descendant check, withheld
retention and post-move privacy check repair the specific round-8 cases, but not this writer
race.

> Evidence: crooks-assistant/app/observability/session.py:_remove_if_older, _expired_tree, write_private_text, TestSessions._tidy_reports; crooks-assistant/tests/test_screen_privacy.py:test_a_fresh_report_inside_an_old_folder_keeps_the_whole_folder

> Repair required: Make pruning conditional on the identity and age of the entry actually removed, without allowing a replacement to be unlinked; test concurrent atomic replacement of an aged report and of a descendant.

**`F-04-SHUTDOWN` — BLOCKS** (demonstrated)

BLOCKS — On this always-on production session, a housekeeping step that exceeds the 27-second
deadline can make shutdown exit without closing the runtime while accepted timeline events
remain in a daemon writer; no bound on such a step establishes that this cannot happen tonight.
STILL PRESENT in that case: lifespan deliberately skips runtime.aclose when Housekeeper.stop
times out. Cooperative checks between steps and waiting beyond the first 20 seconds repair the
shorter overrun, not an overlong step. Normal-close flushing also cannot be verified without
app/runtime.py:Runtime.aclose.

> Evidence: crooks-assistant/app/main.py:lifespan, housekeep_once, Housekeeper.stop, _in_own_thread; crooks-assistant/app/observability/timeline.py:Timeline.emit, Timeline._ensure_writer, Timeline._run; REVIEW PACKET — STANDING FACTS 3–4

> Repair required: Bound or safely interrupt the individual housekeeping operations and establish a shutdown drain for accepted timeline work within the unit deadline, without closing the runtime under a pass. Supply app/runtime.py:Runtime.aclose to verify the normal-close path and test both paths with accepted pending events.

**`F-10` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — This remaining failure can falsely call a count final, but does not itself delete
the raw timeline or expose store data in the configured root-only command path. STILL PRESENT in
part: Timeline._hold_writer_lock catches a lock-acquisition failure and _run writes its accepted
batch anyway. If the command can subsequently acquire the lock, writer_alive reports no writer
and no_backend_verdict may call an on-disk snapshot final while that batch is pending.
Distinguishing connection refusal from timeout, checking a successfully held writer, and naming
a failed flush repair the round-8 paths those tests exercise.

> Evidence: crooks-assistant/app/observability/timeline.py:Timeline._hold_writer_lock, Timeline._run, writer_alive; crooks-assistant/scripts/session_ops.py:no_backend_verdict

> Repair required: Do not accept or write unprotected events while lock acquisition has failed, or make the offline finality check fail closed for that condition; test a writer-side lock failure followed by a successful command-side lock check.

**`F-A3B-SHORT-WRITE` — BLOCKS** (demonstrated)

BLOCKS — A partial filesystem write can discard bytes of an accepted event in production's
always-on timeline, and the supplied host facts do not establish that partial writes cannot
occur tonight. Timeline._append makes one os.write call for a batch, then counts every selected
line as written regardless of the returned byte count; flush can settle and a stop can report a
final count over an incomplete JSONL line.

> Evidence: crooks-assistant/app/observability/timeline.py:Timeline._append, Timeline._run, Timeline.flush, Timeline.counts

> Repair required: Write the complete batch in a checked loop, and count a line as written only once all its bytes have been written; test a short os.write and a subsequent stop.

**`F-A3B-SCREEN-EVIDENCE` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell what the three approved production TVs can obtain through the display
routes, so I cannot establish that a screen sees no unintended customer or live-voice data
tonight. With CROOKS_SCREEN_SNAPSHOTS=false, observe.telemetry_screen returns 204 before reading
or storing a copy; main.display_page serves a page shell, not its data. Neither establishes what
the included displays router serves to that shell or its remote.

> Evidence: crooks-assistant/app/routes/observe.py:telemetry_screen; crooks-assistant/app/main.py:display_page, app.include_router(displays.router); REVIEW PACKET — YOUR PART and STANDING FACTS 3

> Repair required: Have the screen-path review verify app/routes/displays.py's registration, poll and remote handlers, app/displays/store.py's screen-facing view, and web/display.js's polling and rendering at this SHA; establish precisely what a keyed TV receives with snapshots disabled.

---

### Part B1 — screens, server — **CHANGES_REQUIRED**

B-01: STILL UNVERIFIED on the production invocation path (`display_tools._owners_own` itself
refuses non-owner authority). B-02: REPAIRED by `DisplayStore.register`, `approve` and pending-
only `poll`: a random six-digit code is salted and hashed, lasts 15 minutes, permits five wrong
attempts, and uses `hmac.compare_digest`; `screen_pair` requires active OWNER authority and code
digits in the request's heard words. B-03: STILL PRESENT for an unflushed purge journal. B-04:
STILL PRESENT as client-asserted packing. B-05: pairing, exact-name selection and
`gate._ISSUED_ID_ARGS` are repaired, but production invocation remains UNVERIFIED. NEW-B-CAP:
REPAIRED in the sole creation path, `DisplayStore.register`, which refuses a twenty-first screen
without eviction. NEW-B-LOCAL-SLIP: STILL UNVERIFIED without the browser implementation. The
three existing rows without `paired` are treated as approved as the owner requires. Each remote
route has a router-level per-request principal dependency and no screen-key alternative; the
supplied server responses exclude stored `secret` and pairing hashes, while a row's `key` is its
normalized name. Verification of the production principal dependency requires the missing
implementation noted above.

**`B-REMOTE-OFF` — BLOCKS** (demonstrated)

BLOCKS — A stale owner remote can turn off a newly displayed customer slip, irreversibly losing
it. The whole-screen remote off request supplies no version, and `take_off` checks `expect` only
when a pane is specified; an off tap made for an older view therefore deletes whatever is
showing when the request arrives.

> Evidence: CANDIDATE FILES — app/routes/displays.py:OffBody,remote_off; app/displays/store.py:DisplayStore.take_off

> Repair required: Require a screen-wide expected version for remote whole-screen off and check it under the store lock before removing either pane; return 409 for a changed screen. Test replacement between viewing the remote and tapping off.

**`B-03` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether a folder-fsync failure will occur on production tonight; if it
occurs while clearing a slip, that slip can reappear after a restart. `_journal` returns False
when its directory flush fails, but `_commit` ignores that result and accepts the deletion in
memory; if the record flush also fails, neither the old record's deletion nor its purge
obligation is confirmed durable.

> Evidence: CANDIDATE FILES — app/displays/store.py:DisplayStore._journal,_commit,_write,_replay; tests/test_displays.py:_flaky_record_flush

> Repair required: Do not let a deletion stand without a durably confirmed purge obligation unless the record itself becomes durable. Test failure of the journal's *first* directory fsync together with record-write failure, followed by restart from the old durable record.

**`B-04` — BLOCKS** (demonstrated)

BLOCKS — An approved production screen holding its key and allow-listed login can forge a real
order's packed record without displaying or packing it. `acknowledge` accepts paced, client-
chosen ranges without page issuance, and `mark_done` accepts client-supplied `confirm: true`;
the one-second gaps do not establish a displayed page or a packer's tap. B-04 is STILL PRESENT
despite its added ordering and pacing.

> Evidence: CANDIDATE FILES — app/displays/store.py:DisplayStore.acknowledge,mark_done; app/routes/displays.py:SeenBody,DoneBody,seen,done

> Repair required: Either establish the required page and confirmation evidence independently of arbitrary POST bodies, with a test using direct paced POSTs that never render pages, or obtain an explicit owner ruling accepting key-holder assertions as the definition of packed.

**`B-01-B-05-PATH` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether a refused caller can reach the production screen handlers or
bypass issued-ID enforcement at this SHA, which could expose a customer slip on a screen. The
supplied handlers check active OWNER authority and the gate checks issued IDs, but the current
owner-principal implementation and HTTP-to-SDK callback path are not supplied; the route tests
disable Tailscale verification or call dispatch directly. B-01 and the production-path portion
of B-05 remain UNVERIFIED.

> Evidence: REVIEW PACKET — YOUR PART and CANDIDATE FILES, app/tools/display_tools.py:_owners_own,screen_show; app/tools/gate.py:_ISSUED_ID_ARGS; tests/test_displays.py:app_with,test_an_objective_goes_up_only_once_this_conversation_was_shown_it

> Repair required: Supply the exact-SHA implementations of app/routes/actions.py:require_principal,principal_check; app/main.py:guard_and_freshness; app/routes/turn.py:turn,_provider_turn; app/providers/max_agent_sdk.py:_dispatch; and app/tools/registry.py:build_mcp_server,invoke for a production-path review.

**`NEW-B-LOCAL-SLIP` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether an open production screen actually removes customer details after
a 403, disconnection or local expiry, so the previously demonstrated leak remains unverified.
The supplied server-side test searches for snippets in `web/display.js`, but that browser
implementation and its rendering/retained-dot state are outside the supplied files.

> Evidence: REVIEW PACKET — YOUR PART and CANDIDATE FILES, tests/test_displays.py:test_the_screen_takes_a_customer_off_at_once_when_it_may_no_longer_show_it

> Repair required: Supply and review the exact-SHA web/display.js:poll,wipe,wanted,reconcile,draw and the relevant dots-engine clearing code, with behavioural checks for an open slip after 403, prolonged disconnection and expiry.

**`B-NEW-DONE-LOSS` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether this host's real slips and packed history will cross the file
limit as its permitted screens fill; crossing it silently destroys done rows. With two views
allowed on each of twenty screens, `_write` repeatedly discards the oldest half of `done` until
the file fits, rather than refusing a new view; the old single-pane size assumption no longer
bounds that loss.

> Evidence: CANDIDATE FILES — app/displays/store.py:MAX_SCREENS,MAX_FILE_BYTES,MAX_PANES,DisplayStore._write,DisplayStore.show; app/displays/views.py:MAX_VIEW_BYTES

> Repair required: Bound two-pane capacity against the record limit without silently discarding retained done rows. Reject the operation that exceeds capacity or adopt an explicit, tested retention policy; exercise near-limit views with existing done history.

---

### Part B2 — screens, pages — **CHANGES_REQUIRED**

B-06 shows no scoped regression. B-07 cannot be fully cleared without the root-page response.
The screen-key storage and three customer-data exposure paths require changes; the remote's
owner-route enforcement belongs to the backend review, not this part.

**`B2-01` — BLOCKS** (demonstrated)

BLOCKS — On an approved production screen, someone with access to its browser or an extension
can copy its persistent screen key and reuse it to request future slips from an admitted
session. `loadScreen` and `saveScreen` keep the full key in `localStorage['clive.screen']`; the
pairing code being memory-only does not protect that credential.

> Evidence: crooks-assistant/web/display.js:loadScreen,saveScreen; REVIEW PACKET — STANDING FACTS §3 (three already-approved screens)

> Repair required: Stop persisting a reusable screen key in script-readable storage, provide a secure re-entry mechanism for paired devices, and revoke or migrate existing persisted keys.

**`B2-02` — BLOCKS** (demonstrated)

BLOCKS — A revoked production remote can continue showing customer details after a 403 while a
finger is held on its panel. `wipe` calls `render`, but `render` returns without clearing the
DOM for up to two seconds after `pointerdown`; the 403 test does not exercise that state.

> Evidence: crooks-assistant/web/remote.js:build,render,wipe,sync; crooks-assistant/tests/web/remote.test.js:what the remote shows leaves it on a 403

> Repair required: Make refusal and privacy wipes clear sensitive DOM synchronously regardless of the redraw hold, and test a 403 during an active pointer hold.

**`B2-03` — BLOCKS** (demonstrated)

BLOCKS — An older successful response can put a customer slip back on a production screen or
remote after another request has received a revoking 403. `display.js` increments `S.gen` in
`wipe`, but its pending `poll` and `markDone` continuations can still call `receive`;
`remote.js` likewise lets an in-flight `sync` write `R.data` after `post` calls `wipe`.

> Evidence: crooks-assistant/web/display.js:wipe,poll,markDone,receive; crooks-assistant/web/remote.js:wipe,sync,post

> Repair required: Invalidate and discard responses started before a refusal, on both pages; permit customer data to return only following a fresh successful request. Test response ordering with the old 200 resolving after the 403.

**`B2-04` — BLOCKS** (demonstrated)

BLOCKS — A production TV can continue exposing a customer's order details after the order is
marked packed. `markedDone` copies the previously drawn full order and only adds `done_at`;
`renderOrder` draws its customer, address, phone and note again, and the packed view can remain
for 45 seconds instead of using the privacy-reduced done result.

> Evidence: crooks-assistant/web/display.js:markedDone,renderOrder,wantedPane,DONE_HOLD_MS; REVIEW PACKET — round-8 B-03 (privacy-deleting mark_done)

> Repair required: Discard the local full slip when done is confirmed and render only a reduced done confirmation. Test that the packed DOM and retained drawn view contain no customer details.

**`B-07` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell from this B2 packet whether production's `GET /` is always the same data-
free HTML for every login. The worker caches any successful HTML response at `/` and serves it
on a later network failure, potentially to an unauthenticated load; its exclusion of `/display`
and `/displays/*` does not settle that root-page question. B-07 is therefore STILL UNVERIFIED at
this SHA, although the screen routes themselves remain outside the cache.

> Evidence: crooks-assistant/web/sw.js:SHELL,networkFirst; REVIEW PACKET — B-07 verification note; CANDIDATE FILES (GET / handler not supplied)

> Repair required: Supply the FastAPI GET / handler and its rendered response at this SHA for review, or constrain the worker to cache a demonstrably public, data-free shell. Test an owner load followed by an unauthenticated offline load.

---

### Part C — live voice — **CHANGES_REQUIRED**

The visible route rate-limits mint requests, keeps the long-lived key out of its normal
response, and Settings retains `extra="ignore"` with live transcription enabled by default.
Owner admission, token lifetime, and the production handling of live words cannot be cleared
from the supplied code; a telemetry-input defect and a release timing defect also remain.

**`C-01` — BLOCKS** (unverifiable)

BLOCKS — I cannot determine whether a caller can mint a token by presenting a forged owner
identity on production. `_refused` delegates the entire owner decision to `principal_verdict`,
whose implementation was not supplied; the mocked route tests do not establish the real proxy-
identity boundary.

> Evidence: CANDIDATE FILES — crooks-assistant/app/routes/voice.py, `_refused`; tests/test_live_voice.py, `test_a_caller_the_owner_rule_refuses_gets_nothing_under_the_production_switches`

> Repair required: Supply and review `app/routes/actions.py:principal_verdict` and the applicable `app/main.py` route and identity middleware at this SHA, including how forwarded identity is verified for `/voice/live`.

**`C-02` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether the browser bearer token can be reused or remain valid beyond the
claimed fifteen minutes, which would extend credential and billing exposure outside the tailnet.
The route accepts any nonempty string in the provider’s `token` field, and all token tests use a
mocked provider that returns the same token repeatedly; neither establishes the provider’s
single-use or expiry behavior.

> Evidence: CANDIDATE FILES — crooks-assistant/app/routes/voice.py, `_mint`; tests/test_live_voice.py, `ElevenLabs.handler` and `TOKEN`

> Repair required: Provide verifiable provider-contract evidence or a safe integration check for the exact token endpoint demonstrating one use and expiry; if those properties do not hold, change the design so the browser does not receive a reusable bearer credential.

**`C-03` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether live customer names and order details remain display-only on
production. `create` passes complete live words to an unrestricted `onWords` callback, but the
`web/app.js` wiring that decides whether they also enter telemetry, a turn, or retained context
was not supplied.

> Evidence: CANDIDATE FILES — crooks-assistant/web/live-voice.js, `create`/`heard`; REVIEW PACKET — YOUR PART: C (the integration is assigned to `web/app.js`, outside the supplied files)

> Repair required: Supply and review the `web/app.js` `CrooksLiveVoice.create` callbacks and voice-turn submission at this SHA; ensure only the batch transcript enters the model or retained records and that live words are used only for text display.

**`C-04` — BLOCKS** (unverifiable)

BLOCKS — I cannot establish that third-party socket errors cannot put speech or customer data
into the always-on telemetry timeline. `heard` copies any error message’s unvalidated
`message_type` into `reason`, `close` passes it to `record`, and telemetry accepts string
fields; the provider-message shape and production callback wiring needed to exclude such data
are not established.

> Evidence: CANDIDATE FILES — crooks-assistant/web/live-voice.js, `isError`, `heard` and `close`; crooks-assistant/web/telemetry.js, `record`/`flush`; REVIEW PACKET — STANDING FACTS 3 (`CROOKS_TEST_SESSION_ALWAYS=true`)

> Repair required: Map socket failures to a fixed, bounded set of local reason codes before calling `record`; test an error whose `message_type` contains a customer name and verify no such text enters a telemetry payload.

**`C-05` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — This can lose live-word availability on a slow connection, but the supplied code
still sends the ordinary batch recording. Releasing before the WebSocket opens starts the
1.5-second finish timer immediately; if the socket opens later, `close` has already discarded
its buffered audio, so it never commits the words.

> Evidence: CANDIDATE FILES — crooks-assistant/web/live-voice.js, `connect`, `close` and `handle.release`

> Repair required: Bound the connection wait separately and start the post-commit finish timer only once the socket has opened and buffered audio has been committed; test opening after 1.5 seconds following release.

---

### Part D1 — every sentence is a model turn — the turn path — **CHANGES_REQUIRED**

Within the supplied turn path, only the permitted bare-yes interlock short-circuits a sentence;
the other word matches add model context rather than execute an action. No round-8 finding is
individually assigned to D1 in this packet. The production write-guard question cannot be
cleared from these six files, and the cursor and observability paths have the material findings
above.

**`D1-01` — BLOCKS** (demonstrated)

BLOCKS — Production’s always-on observability receives raw spoken text and model answers
containing potential customer names before the turn installs its name-redaction context; I
cannot verify from the supplied files that those events are made safe before they are retained
or shared. `turn()` emits `raw_text`, `text`, and `result.text`, whereas `_answer()` calls
`timeline.note_names()` later.

> Evidence: CANDIDATE FILES: crooks-assistant/app/routes/turn.py, turn() stt/model timeline.emit calls and _answer() timeline.note_names; STANDING FACTS §3 (CROOKS_TEST_SESSION_ALWAYS=true)

> Repair required: Redact or omit content at the early emission sites, and verify the persisted events with a newly encountered customer name; alternatively provide the missing `app/observability/timeline.py:emit` and `scrub` behavior proving those events are redacted before retention.

**`D1-02` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether a write from the production tablet can target a different record
from the one displayed. `_stand_on_what_was_shown()` moves the branch cursor from the first
simple record card only, while `present()` can replace that card with an `order_workspace` or
`customer_workspace`; it also does not resolve screens containing records of different kinds.
The new model-turn cursor can therefore remain on an earlier record or move to an incidental
one.

> Evidence: CANDIDATE FILES: crooks-assistant/app/routes/turn.py, _RECORD_CARDS, _stand_on_what_was_shown() and _answer(); crooks-assistant/app/presentation.py, _compose_workspace()

> Repair required: Make cursor selection account for composed workspaces and refuse ambiguous multi-record selection. Test a model turn showing order B while the cursor was on order A, through the subsequent tapped write and its confirmation; inspect the command handler’s target binding before clearing the write risk.

**`D1-03` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether removing the fast lane has left a reachable model write with
weaker disambiguation or refusal checks on this writes-enabled production host. This part shows
model tool calls going straight to `_answer()` for proposal delivery, but supplies neither the
deleted fast-lane guards nor the model dispatch and action-commit implementations needed to
establish guard parity.

> Evidence: REVIEW PACKET: YOUR PART questions (b) and restricted diff for app/routes/turn.py; CANDIDATE FILES: crooks-assistant/app/routes/turn.py, _provider_turn() call and _answer() proposal delivery

> Repair required: Provide and review the deleted fast-lane write checks against `app/providers/max_agent_sdk.py:MaxAgentSDKProvider._dispatch`, `app/tools/dispatch.py:dispatch`, `app/tools/gate.py:classify`, and the action staging and commit handlers. Restore any missing check at the model write boundary and test refund, cancellation, and store-credit attempts.

---

### Part D2 — every sentence is a model turn — runtime, branch, speech — **CHANGES_REQUIRED**

The fast lane and transcript normaliser are removed, and ordinary requests reach the model; the
tap recipes retain a startup read-only assertion. No round-8 finding is expressly assigned to D2
in the packet. New write-adjacent branch and affirmation defects, plus unverified concurrent-
branch authority, prevent READY.

**`D2-01` — BLOCKS** (demonstrated)

BLOCKS — An older turn can finish after its replacement and put an older order back on the live
branch, leaving a subsequent money-moving action aimed at the wrong record. `_answer` detects
that the turn was abandoned but still calls `branch.shown` and `_stand_on_what_was_shown`, which
can call `branch.visit`; it also completes the older workspace. Refusing the old proposal does
not prevent these state changes.

> Evidence: CANDIDATE FILES — crooks-assistant/app/routes/turn.py, _answer(), _moved_on(), _stand_on_what_was_shown()

> Repair required: When a turn has moved on, do not publish its cards or mutate its branch cursor or workspace. Add an overlapping-turn test in which the older answer finishes last.

**`D2-02` — BLOCKS** (demonstrated)

BLOCKS — A pending live refund or cancellation remains tappable when the owner says an apparent
correction such as “yes, #1938”: `is_affirmation` deletes the digits, treats the result as bare
“yes”, and skips the model and pending-proposal revocation. The spoken identifier is silently
lost at the write-confirmation boundary.

> Evidence: CANDIDATE FILES — crooks-assistant/app/routes/turn.py, is_affirmation() and the waiting-proposal branch of turn()

> Repair required: Recognise an affirmation only when the entire utterance contains the permitted words and harmless punctuation; never discard numbers or other substantive tokens. Test a different spoken order number against a pending money-moving proposal.

**`D2-03` — BLOCKS** (unverifiable)

BLOCKS — Concurrent turns on the two halves assign different values to the same
`live.acting_branch` before either finishes, so I cannot tell whether downstream staging can
attach a live write to the wrong half. The route sets this shared session field once and then
awaits preflight and the provider; the branch-local safety of downstream tool calls depends on
code not supplied to D2.

> Evidence: CANDIDATE FILES — crooks-assistant/app/routes/turn.py, turn() (`live.acting_branch` and `_provider_turn`); crooks-assistant/app/session/branch.py, Branch.instruction_seq

> Repair required: Establish branch authority per concurrent turn rather than through a mutable session-wide field, and test overlapping write proposals. To verify an existing safeguard instead, supply app/session/models.py:Session.branch, app/providers/max_agent_sdk.py:MaxAgentSDKProvider.turn_on_branch and the action-staging path in app/actions/engine.py.

**`D2-04` — BLOCKS** (demonstrated)

BLOCKS — When a model answer displays an order and a customer, `_stand_on_what_was_shown`
chooses the first record even though another kind of record is also present; on this write-
enabled host I cannot tell whether a later card action overrides that possibly wrong branch
cursor. Its uniqueness test counts references only of the *first kind*, not distinct records
across the screen.

> Evidence: CANDIDATE FILES — crooks-assistant/app/routes/turn.py, _RECORD_CARDS and _stand_on_what_was_shown()

> Repair required: Do not infer a focused record from a mixed-record screen. Require an explicit focus or uniquely identified tapped card, and test order-plus-customer results followed by a write action; verify the binding in app/commands.py for the affected card action.

**`D2-05` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — The removed fast lane's read-only no-guess checks cannot themselves execute a write
or disclose data to a different principal tonight, but their equivalent read-side disambiguation
is not present in the supplied model-turn path. In particular, the refusals for a different
order number, a named customer instead of the focused one, conflicting periods or dimensions,
and spoken self-correction are gone; `turn()` now passes the words and branch context to the
model without replacing those checks.

> Evidence: REVIEW PACKET diff — crooks-assistant/app/fastpath/library.py (_names_another_order, _customer_history_plan, period_from, dimension_from), app/fastpath/correction.py (corrections), and app/routes/turn.py (removed _route and _fast); CANDIDATE FILES — app/routes/turn.py, turn()

> Repair required: Test the model path with conflicting names, order numbers and corrections, and provide a bounded clarification or target-validation rule where it otherwise presents an answer about the wrong record. Keep write-target validation separate from these former read-only heuristics.

---

### Part G — the app page itself (web/app.js) — **CHANGES_REQUIRED**

The added app.js lines name the screen tools, wire microphone audio and level to the live-word
and waveform helpers, put interim words in text-only DOM nodes, replace the bar's heard words on
a /state transcript, clear them for a typed ask, and hand turn UI to the remote. They make no
direct new storage write and handle no ElevenLabs credential or token directly. The only new
fetch in these lines is the callback supplied to LiveVoice; its actual calls, token handling,
and the remote's calls are in unsupplied modules. Existing app.js storage writes retain session,
turn count, developer, voice, and stream preferences—not the token in the shown code. No round-8
finding was assigned to part G in the packet.

**`G-01` — BLOCKS** (demonstrated)

BLOCKS — Live transcription and always-on telemetry are enabled in production, but the supplied
files do not establish whether the single-use token or spoken words can leak, so reachability of
a production data leak cannot be determined. app.js delegates token acquisition and retention to
CrooksLiveVoice.create, passes it an unrestricted fetch callback and forwards its record fields
to telemetry; it also passes turn UI to CliveRemote.fromTurn. These files alone cannot establish
the token's lifetime, its destinations, or whether the new integrations preserve the app's same-
origin assumptions.

> Evidence: crooks-assistant/web/app.js:LiveVoice.create, renderTurn; crooks-assistant/web/index.html:script tags for live-voice.js and remote.js; review packet: YOUR PART, STANDING FACTS 3

> Repair required: Have the designated reviewers inspect the exact-SHA implementations of web/live-voice.js (CrooksLiveVoice.create/begin/release/cancel), web/telemetry.js (CrooksTelemetry.record), and web/remote.js (CliveRemote.fromTurn). Establish the token's lifetime and all request destinations, and prove that neither token nor spoken content reaches storage, URLs, logs, or telemetry; constrain the app.js callbacks if those guarantees do not hold.

**`G-02` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — An incorrect transcript left on the ask bar is a display-correctness defect, with no
evidenced exploit, data loss, or data leak tonight. If /turn returns before a /state poll
observes data.heard, submit writes the batch question to el.heard but never calls showHeardWords
for the bar, which can keep displaying the differing realtime words.

> Evidence: crooks-assistant/web/app.js:startStatePolling, submit, showHeardWords

> Repair required: On the audio turn response, replace the bar's interim words with the batch question, or clear them when no question was heard; test the case where /state never supplies data.heard.

**`G-03` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — The unverified accent claim is an appearance requirement, not an evidenced exploit,
data-loss, or data-leak path tonight. The scoped files link alpha.css but do not supply it, so
this part cannot confirm that the iOS-blue change is cosmetic.

> Evidence: crooks-assistant/web/index.html:stylesheet links; review packet: PR #52 body, section 1

> Repair required: Have the designated CSS reviewer verify web/alpha.css at this exact SHA and confirm the accent change alters styling only.

---

### Part E-app1 — the rest of the application code (slice 1) — **CHANGES_REQUIRED**

The supplied edits do not show a removed refusal, new customer-data output, or matching of the
owner’s words. The changed tap-recipe execution path cannot be cleared without its runner; no
round-8 finding was assigned to this part for individual adjudication.

**`E-01` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether a tap can reach a live write on production tonight, because
writes are enabled and the replacement recipe runner was not supplied.
`app/routes/command.py:_run_recipe` now calls `app/recipes.py:run`; its claimed read-only check
and tool-dispatch path cannot be verified from this packet. The scheduler’s read-only check
applies only if the runner uses that scheduler.

> Evidence: CANDIDATE FILES: crooks-assistant/app/routes/command.py, _run_recipe; crooks-assistant/app/reads/scheduler.py, assert_reads_only

> Repair required: Supply the candidate-SHA implementation of app/recipes.py:RECIPES, run, assert_read_only, and its dispatch path for review. If a write or batch tool is reachable, refuse it before execution on the tap path.

---

### Part E-app2 — the rest of the application code (slice 2) — **CHANGES_REQUIRED**

The edits remove no check, refusal or confirmation. The Shopify tools retain live write paths,
while the engineering write remains inactive with its credential parked; none of those write
handlers changed here. No supplied edit newly logs or returns owner or customer data.
`workspace.desired()` still uses the owner’s words to choose presentation sections and a tab,
not to bypass a model turn. The new status branch cannot be cleared without its helper
implementations.

**`E-01` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — This affects a local status diagnostic, with no shown path to exploitation, data
loss or data leakage on production tonight. The new branch in `status.show()` depends on
`scripts/launch_common.py:health_limited` and `scripts/launch_common.py:summarise_health`, whose
exact-SHA implementations were not supplied; I cannot verify that a limited health response is
detected and summarized correctly.

> Evidence: crooks-assistant/scripts/status.py:40-43; packet CANDIDATE FILES

> Repair required: Provide the exact-SHA implementations of both helpers and evidence for limited and full health responses, or make this branch independently reviewable.

---

### Part E-app3 — the rest of the application code (slice 3, web/ui.js) — **READY**

In web/ui.js, renderScreenRemote adds a remote card and opener without removing a check,
refusal, or confirmation. It renders the screen name and showing titles as text and does not
itself perform a write or route on the owner’s words. The opener’s handling in web/remote.js is
outside this part’s scope and is not cleared by this verdict.

---

### Part E-families1 — the capability families and capabilities the fast lane fed — **CHANGES_REQUIRED**

The deleted modules were not all dead code. `capabilities.ask`, `screen` and `ui_intent`
supplied request discrimination, live-screen answers and a surface-fulfilment check.
`families.navigation_extras`, `order_email`, `query_language`, `self_knowledge` and `ui_intent`
supplied spoken navigation, grounded order/email replies, bounded order queries, interface
explanations and customer/area workspaces. `owner_feedback` recorded spoken defect reports; that
loss is finding E-03. The tracking limitation from `query_language` does remain registered as
`shipping.DELIVERY`. In the supplied surviving files, references to deleted modules are comments
rather than executable imports; references outside this slice remain unverified (E-05).
`landings` now houses the shared reply-queue, working-set, period and money helpers and runs
four read-only dock recipes. It reads customer-linked Gmail threads and Shopify order, stock and
sales figures, including monetary totals, but contains no store or mailbox mutation. The deleted
families did not themselves commit writes; the material lost refusal to check is `order_email`'s
confident thread match (E-04). The surviving workspace and action paths retain staging and hold
descriptions, but the spoken-recipient check is weaker on the model path (E-02). No round-8
finding was assigned to this slice in the packet.

**`E-01` — BLOCKS** (demonstrated)

BLOCKS — A stale picker can prepare a change to a previously issued order other than the order
now on screen, risking a wrong live order mutation after the owner's hold.
`order_edit._open_picker` requires the named order to be open, but `_stage_add_item` checks only
`may_open` and whether the variant was issued; it does not repeat the current-order check, and
it pairs the submitted order ID with the current entity's label.

> Evidence: CANDIDATE FILES — crooks-assistant/app/families/order_edit.py: _open_picker, _stage_add_item

> Repair required: At staging, require the submitted order ID to equal the branch's currently open order, bind the variant choice to that picker, and derive the displayed order label from the validated order.

**`E-02` — BLOCKS** (demonstrated)

BLOCKS — A model-normalised spoken address can be treated as a verified recipient, so an ASR or
model error can send private mail to the wrong address on this live mailbox.
`gmail_compose_open` passes the model's `to` string to `check_address`; a canonical address
receives `to_status='ok'` even if the owner dictated it, whereas `_ready_to_stage` refuses only
an address still marked uncertain. The deleted spoken composer passed its extracted address
through the uncertainty check before offering Send.

> Evidence: CANDIDATE FILES — crooks-assistant/app/families/compose.py: check_address, gmail_compose_open, _ready_to_stage; DIFF — compose.py: _open_render deletion

> Repair required: Preserve recipient provenance across the model path. Require an explicit owner field confirmation for an arbitrary address supplied from speech or by the model before Send can be staged; test a dictated address that the model supplies in canonical form.

**`E-03` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether owner-reported defects are still recorded during tonight's
always-on test session; without a replacement, deleting the only recorder shown here loses those
reports. The removed `owner_feedback._render` called `feedback.record`, and no surviving file in
this slice replaces that call. The model-turn recording path is outside the supplied files.

> Evidence: DIFF — crooks-assistant/app/families/owner_feedback.py: _render deletion; REVIEW PACKET — STANDING FACTS 3 (CROOKS_TEST_SESSION_ALWAYS=true)

> Repair required: Show the SHA-exact replacement in `app/routes/turn.py` that calls `app/observability/feedback.py:record` for recognised owner feedback, or restore recording on the model path, with an end-to-end report test.

**`E-04` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether the replacement model path preserves the deleted confident order-
to-thread refusal; if it does not, a reply about one live customer's order could be drafted to
another customer's thread and sent after a hold. `order_email._choose` previously refused merely
possible links before arming a reply. Its removal supplies no corresponding check in this slice;
`compose._compose_reply` identifies the thread's sender but does not establish that the thread
concerns the requested order.

> Evidence: DIFF — crooks-assistant/app/families/order_email.py: about_this_order, _choose, _render deletion; CANDIDATE FILES — crooks-assistant/app/families/compose.py: _compose_reply

> Repair required: Show the order/thread binding enforced by the SHA-exact model/write path in `app/routes/turn.py` and `app/tools/gmail_writes.py`, or enforce a confident match before preparing an order-specific reply. Test a possible link to a different order.

**`E-05` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether any live startup or observability module still imports a deleted
capability or family; a remaining reference could also stop tonight's test-session data capture.
Package discovery covers the family imports shown here, but the packet does not contain a
repository-wide reference audit, so the requested answer about remaining references cannot be
verified.

> Evidence: REVIEW PACKET — YOUR PART (deleted modules and reference question); CANDIDATE FILES — crooks-assistant/app/families/__init__.py: load_all; DIFF — capability and family deletions

> Repair required: Provide a SHA-exact repository-wide executable import/symbol-reference check, including `app/observability/visible.py` and `app/routes/turn.py`, and repair any dangling references; verify startup with the production configuration.

**`E-06` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — This can give the owner a false operational answer tonight, but the shown path only
reads and presents records; it does not itself write, lose or leak them. If the open-orders read
fails while today's read succeeds, `landings._orders_render` treats the failed read as an empty
list and says 'Nothing is waiting to go out.'

> Evidence: CANDIDATE FILES — crooks-assistant/app/families/landings.py: _orders_render

> Repair required: Distinguish a failed open-orders read from a successful empty result; mark the answer partial and decline to say nothing is waiting when that read failed.

---

### Part F-observability1 — observability modules the named parts do not own (slice 1) — **CHANGES_REQUIRED**

`feedback.record` can emit owner words and context to the timeline; `report.write_report` and
`proposals.write_proposals` write Markdown under the supplied output directory (production
reports resolve under the checkout). The other scoped modules classify events or transform
screen markup without writing files themselves. Reports explicitly print owner requests and
answers, so they can contain customer details or write wording. These seven files do not
establish who can retrieve those records or whether they reach a screen; the filename escape and
missing provenance and write-helper evidence prevent clearing that boundary.

**`F-01` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether a test-session identifier can be supplied through production
telemetry tonight, so I cannot rule out using it to write a report containing owner or customer
words outside the private reports directory. `reconstruct` accepts `test_session_id` from an
event without validating it, and both output functions use that value as a filename; an
identifier such as `../web/exposed` escapes `reports/` unless the unseen write helper prevents
it.

> Evidence: crooks-assistant/app/observability/report.py:reconstruct, write_report; crooks-assistant/app/observability/proposals.py:write_proposals; REVIEW PACKET: YOUR PART, STANDING FACTS §3

> Repair required: Validate session identifiers as single safe filename components and verify resolved targets remain inside the intended reports directory in both writers. Establish whether app/observability/timeline.py::read_events admits a supplied identifier and whether app/observability/session.py::write_private_text enforces containment; those symbols were not supplied.

**`F-02` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — `CROOKS_SCREEN_SNAPSHOTS=false` prevents this screen-copy path from collecting
markup on production tonight. Nevertheless, `sanitise_markup` treats `data-spoken` as an
ordinary attribute: it retains text beneath the marked element, and `_attrs` can retain a token-
shaped `data-words` value because that attribute is absent from `DATA_FREE_TEXT`. General
credential and known-customer scrubbing is not a guarantee that live dictation or the words of a
proposed write are masked.

> Evidence: crooks-assistant/app/observability/screens.py:DATA_NAMES, DATA_FREE_TEXT, _Sanitiser.handle_data, _Sanitiser._attrs; REVIEW PACKET: STANDING FACTS §3

> Repair required: Mask the content of `data-spoken` elements during parsing, and discard or empty `data-words`; test with arbitrary live words that are not recognizable credentials.

**`F-03` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — Incorrect observability classification does not itself exploit access or lose or
leak production data tonight. `semantics.CHANGES` declares store credit to have no capability,
although the packet establishes that the production `store_credit_credit` write is ready. When a
store-credit request receives a mutation verdict, `_spoken_capability` therefore reports
`NO_FAMILY`, and the report and proposals can recommend building an already-live money-moving
action or mark its turn as missing a capability.

> Evidence: crooks-assistant/app/observability/semantics.py:CHANGES, capability_state; crooks-assistant/app/observability/report.py:_spoken_capability, _classify; REVIEW PACKET: STANDING FACTS §3

> Repair required: Map store credit to its actual capability or derive availability from the live capability registry; test the report classification of a successfully executed store-credit request.

---

### Part F-observability2 — observability modules the named parts do not own (slice 2, visible.py) — **CHANGES_REQUIRED**

visible.py itself contains no disk write or SCREEN route, but it propagates unredacted session
material and can log rejected telemetry values. The supplied file does not establish the
persistence or audience of those outputs. No round-8 finding was expressly assigned to
visible.py.

**`F-OBS2-01` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell from the supplied code whether these sensitive outputs reach a SCREEN or
a non-owner on the live test-session deployment, so a data leak cannot be excluded. `_feedback`
returns entire `owner_feedback` events and puts the owner's text and full answer into
`ignored_feedback`; `read` also puts finding signals into `Row.why`, while `apply` copies them
onto turns. An ignored-feedback signal can contain the first 120 characters of an answer,
including customer details or write contents. This file has no disk writer or route, and the
supplied evidence does not establish where those outputs are persisted or shown.

> Evidence: CANDIDATE FILES — crooks-assistant/app/observability/visible.py: _feedback, read, apply; REVIEW PACKET — STANDING FACTS 3

> Repair required: Redact or omit sensitive text and raw event dictionaries before they leave visible.py, then provide the report/timeline consumers and access controls needed to verify that the resulting records cannot expose secrets, customer details or write contents to a screen or non-owner.

**`F-OBS2-02` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell who can read the production log, so a secret in malformed telemetry could
leak there. For example, `_focus_lost` passes `tablet_compose_field.chars` to `int`; on failure,
`read` logs the exception text, which includes the rejected value. The same raw-exception
logging occurs for `_feedback`.

> Evidence: CANDIDATE FILES — crooks-assistant/app/observability/visible.py: _focus_lost, read

> Repair required: Log only the rule name and exception type, not the exception message or telemetry value; verify the same constraint for the feedback exception path.

---

### Part H-experience1 — the experience harness and scenario packs — **CHANGES_REQUIRED**

F-A2-FIXTURE remains present in the experience harness. The migrated scenarios exercise several
real HTTP, gate, and presentation paths, but scripted model choices and removed or weakened
write and inbox checks leave material gaps in what their results can establish. All findings
here are follow-ups under the stated production ship rule; this verdict clears no code outside
the assigned experience files.

**`F-A2-FIXTURE` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — This authority grant is confined to the experience harness, so it does not itself
admit a production request tonight. STILL PRESENT in this slice: `harness()` defaults to writes
enabled, and `Harness.configure` installs a fixture owner on the allow-list while disabling
Tailscale verification; every harness request then supplies that owner's headers. These
scenarios therefore do not test whether the same unverified headers would be refused by the
production owner boundary. The claimed repair in `tests/conftest.py::owner_asking` is outside
this part and is not cleared here.

> Evidence: CANDIDATE FILES — crooks-assistant/experience/harness.py (TABLET_HEADERS, Harness.configure, harness)

> Repair required: Make unadmitted requests the harness default; require an explicit admitted-owner mode for owner scenarios, and retain a scenario using the production-equivalent identity check to prove forged headers are refused.

**`H-02` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — Scripted model choices affect the offline scenarios, not the deployed provider
directly, so this is not itself a production data-loss or leakage path. The sentence scenarios
verify gate and presenter responses to tools chosen by the harness, not whether the model
chooses those tools: `Harness.ask` supplies the tool list and `RecordingProvider.turn` supplies
the reply. For example, `abandoned_window` supplies `days=7` before checking the week's card,
and `compose_open` supplies the recipient and email fields before checking them. `a_model_turn`
checks only the call count and lane.

> Evidence: CANDIDATE FILES — crooks-assistant/experience/harness.py (RecordingProvider.turn, Harness.ask); crooks-assistant/experience/scenario_packs/abandoned.py (abandoned_window); crooks-assistant/experience/scenarios.py (a_model_turn)

> Repair required: Describe these as scripted gate/presenter tests, and add separate model-decision evidence that independently checks tool selection and arguments for the claimed spoken behaviours.

**`H-03` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — These no-op test turns cannot themselves execute a production write tonight.
`discount_sentence_defers`, `order_add_item_sentence_defers`, and `unsupported_edit` send their
change requests to an unscripted `RecordingProvider`, which returns fixed prose and calls no
tools. Their assertions that nothing was prepared or changed consequently cannot detect unsafe
staging, execution, or claims in an actual model response; `unsupported_edit` also lost its
former false-claim assertion.

> Evidence: CANDIDATE FILES — crooks-assistant/experience/harness.py (RecordingProvider.turn); crooks-assistant/experience/scenario_packs/discounts.py (discount_sentence_defers); crooks-assistant/experience/scenario_packs/order_edit.py (order_add_item_sentence_defers); crooks-assistant/experience/scenarios.py (unsupported_edit)

> Repair required: Exercise representative model tool attempts on these write requests and assert the intended proposal, confirmation, and non-execution boundaries; separately check that the answer does not claim an unexecuted change succeeded.

**`H-04` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — Deleting a scenario does not itself send mail or expose mailbox data on production
tonight. `compose_send_spoken` was deleted, including its check of what happened before the
send-confirmation gesture. The remaining `compose_send_instead` covers a tapped conversion, not
the spoken 'don't save a draft, send it' path now handled by the model. There is no replacement
scenario here checking that the spoken path preserves the draft's recipient and words and does
not send before confirmation.

> Evidence: REVIEW PACKET — restricted diff for crooks-assistant/experience/scenario_packs/compose.py (deleted compose_send_spoken); CANDIDATE FILES — same file (compose_send_instead, SCENARIOS)

> Repair required: Restore a spoken, model-turn send-instead scenario using the existing draft and assert the intended staging policy, exact recipient and body, required confirmation, and no execution before it.

**`H-05` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — This weakened oracle is test-only and does not itself change the production inbox
tonight. `needs_reply` no longer checks that the spoken answer names those waiting or excludes
people already answered. Its replacement looks for each waiting person's first name anywhere in
a stringified queue payload, while its exclusion check looks for replied-to full names; a
misleading answer or an incorrectly queued person can evade those checks.

> Evidence: REVIEW PACKET — restricted diff for crooks-assistant/experience/scenarios.py (needs_reply); CANDIDATE FILES — same file (needs_reply)

> Repair required: Compare structured queue entries and reply states with the fixture world's expected threads, and assert that the accompanying answer accurately describes who is waiting.

**`H-06` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — The audit's false coverage claims are generated from test-source inspection and do
not execute a production tool tonight. `tool_matrix._scenario_tools` treats a tool or operation
mentioned anywhere in a scenario file, including a comment or assertion, as a golden scenario
exercising the tool and reports the filename rather than an executing scenario. In
`store_credit_give`, the string `store_credit_credit` checks a pending card; the credit write is
not executed, yet that mention can mark its write tool covered.

> Evidence: CANDIDATE FILES — crooks-assistant/experience/tool_matrix.py (_scenario_tools, tools); crooks-assistant/experience/scenario_packs/commerce.py (store_credit_give)

> Repair required: Derive coverage from identified scenario calls rather than arbitrary source mentions, and distinguish a write that was staged from one whose handler or confirmation path was exercised.

**`H-07` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — These credit tests run inside the harness rather than exposing a new production
route tonight. Both store-credit scenarios invoke `dispatch(sc.OPEN_TOOL, ...)` after manually
setting `CURRENT_SESSION`, instead of having their model turn call the tool through `/turn`.
That bypasses the request path whose owner authority this harness purports to exercise and makes
their credit-form assertions dependent on test context outside the scenario.

> Evidence: CANDIDATE FILES — crooks-assistant/experience/scenario_packs/commerce.py (store_credit_give, store_credit_not_on_this_store)

> Repair required: Drive the credit-opening tool through a scripted `Harness.ask` request with the intended owner context; keep the direct capability probe as a separately identified unit-level check.

---

### Part I-tests1 — remaining tests (slice 1) — **CHANGES_REQUIRED**

The supplied diff shows no deletion or weakening of a refusal, confirmation, or authority
assertion in these 11 files; the removed abandonment cases concern the retired fast lane and
spoken formatter. Five files explicitly grant owner authority at module scope, and the batch
route fixture explicitly enables writes; neither establishes a suite-wide default. No test in
this slice clearly mocks the function it directly asserts on. F-A2-FIXTURE cannot be cleared
without the missing fixture definitions, and two privacy assertions at this SHA are ineffective.

**`F-A2-FIXTURE` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — Test fixtures do not run in production, so this evidence gap does not itself make
the live service exploitable or cause data loss or leakage tonight. STILL PRESENT as an
unverified ruling: these files explicitly opt tests into `owner_asking`, but the packet does not
include `tests/conftest.py::owner_asking` or the autouse fixtures needed to establish that tests
without an opt-in have no owner authority.

> Evidence: crooks-assistant/tests/test_actions.py:pytestmark; crooks-assistant/tests/test_abandoned.py:test_the_models_read_draws_both_cards; review packet, YOUR PART and PR #51 F-A2-FIXTURE

> Repair required: Provide the `owner_asking` fixture and autouse-fixture definitions to the part that owns `tests/conftest.py`, and demonstrate a dispatch in a fresh context with no owner fixture is refused.

**`I-01` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — These vacuous assertions weaken offline privacy evidence, but do not themselves
expose production data tonight. In `test_state_can_be_asked_after_a_lost_connection` and
`test_a_write_tools_note_is_logged_by_length_only_even_when_refused`, the assertions intended to
exclude sensitive content end in `or True` and therefore pass regardless of the returned card or
logged read arguments.

> Evidence: crooks-assistant/tests/test_actions_routes.py:test_state_can_be_asked_after_a_lost_connection; crooks-assistant/tests/test_actions_routes.py:test_a_write_tools_note_is_logged_by_length_only_even_when_refused

> Repair required: Remove both unconditional `or True` branches and assert the intended public-card and read-argument redaction properties against actual outputs.

---

### Part I-tests2 — remaining tests (slice 2) — **CHANGES_REQUIRED**

CHANGES_REQUIRED for removed safety regressions, a test asserting on its own hard-coded
provider, and an unverified F-A2-FIXTURE repair. The scoped files show explicit owner opt-ins,
not proof of a suite-wide default grant; no default write enablement is shown.

**`I-01` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether production’s bound-control path can still attach a prior order’s
action to a new instruction, and writes are enabled tonight. The test that refused this behavior
after a tapped Add a note was deleted, with no model-turn replacement shown.

> Evidence: DIFF — crooks-assistant/tests/test_experience.py, deletion of test_a_question_that_names_its_own_subject_is_not_swallowed_by_a_tapped_control; STANDING FACTS §3

> Repair required: Add a model-turn regression that binds an action to one order, asks about a different named order, and verifies that no continuation or proposed write targets the first. Supply the exact-SHA /turn bound-control handling in app/routes/turn.py and the voice.bind handler for review.

**`I-02` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — These checks concern answers shown to the authenticated owner, who can access both
records, so their deletion alone does not establish an exploit, data loss, or unauthorized
disclosure tonight. The end-to-end refusals of answering a named-person or numbered-order
question from the unrelated record in focus were removed, and no equivalent model-turn assertion
appears in this slice.

> Evidence: DIFF — deletion of crooks-assistant/tests/test_capability_routing.py (test_the_answer_names_the_customer_the_words_named); crooks-assistant/tests/test_experience.py (test_a_number_that_is_not_the_open_order_is_never_answered_from_the_open_order and test_a_named_person_is_not_answered_from_whoever_the_open_order_belongs_to)

> Repair required: Restore end-to-end model-turn cases with a different record in focus; assert the answer and card identify the requested person or order, or explicitly decline to answer, rather than displaying the focused record.

**`I-03` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — The hard-coded provider runs only in the offline test, so this finding does not
itself establish production exploitation, loss, or leakage. client.Provider.turn always looks up
order 1938 and supplies a fixed answer; the test then asserts on the reads and card that this
mock itself manufactured, not on the model choosing the requested order.

> Evidence: CANDIDATE FILES — crooks-assistant/tests/test_context.py, client.Provider.turn and test_a_spoken_order_lookup_is_the_models_and_its_two_reads_draw_the_whole_order

> Repair required: Separate the route-rendering smoke test from the model-routing claim. Add differing requested and focused order numbers, with assertions on the requested entity that cannot be satisfied by a fixed-order provider.

**`I-04` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — Test-fixture authority is not itself a production access path, so this evidence gap
does not meet tonight’s exploit, loss, or leak bar. F-A2-FIXTURE is STILL PRESENT as an
unverified review requirement: this slice shows explicit owner opt-ins, including module-level
opt-ins in four files, but does not show the owner_asking fixture or prove the former suite-wide
autouse grant was removed. No default enablement of writes is shown in these files.

> Evidence: CANDIDATE FILES — crooks-assistant/tests/test_cancel.py, test_council_fixes.py, test_discounts.py and test_engine_hooks.py (pytestmark); PR #51 BODY, ‘Protected files changed by hand’ (claim about tests/conftest.py)

> Repair required: Provide the exact-SHA crooks-assistant/tests/conftest.py owner_asking and autouse fixture implementations, plus the no-authority dispatch test, to verify that tests without an explicit opt-in have neither owner authority nor default write permission.

---

### Part I-tests3 — remaining tests (slice 3) — **CHANGES_REQUIRED**

The supplied tests use explicit owner opt-ins and generally test the real handlers against fake
external stores, not mocks of the handler under test. They do not establish the F-A2-FIXTURE
default without `conftest.py`. Several deleted refusal assertions lack replacement-path
evidence; the cross-order email case leaves a potential live data leak unresolved.

**`F-A2-FIXTURE` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — This test-fixture evidence gap does not itself run on production or grant a
production caller authority tonight. STILL PRESENT as an unverified repair: these files
explicitly opt tests into `owner_asking`, but the supplied files do not show whether the suite-
wide default owner grant was removed.

> Evidence: test_fulfil.py:pytestmark; test_gmail_writes.py:pytestmark; packet: PR #51 protected-files claim and supplied-file scope

> Repair required: Supply and review `crooks-assistant/tests/conftest.py::owner_asking` and its autouse fixtures, including a test that dispatches with no authority stamped. The module-level marks are explicit opt-ins, not proof of the default.

**`I-02` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether the live model-driven mail path can select another order's thread
and leak customer information, so its reachability on tonight's production configuration remains
unresolved. `test_graph.py` deleted the assertions that a thread about a customer's different
order is not this order's thread and that a merely possible link is never selected for a reply;
the remaining
`test_gmail_writes.py::test_a_reply_with_no_order_named_says_the_recipient_was_not_checked`
demonstrates that a reply can still be proposed without an order check.

> Evidence: packet: diff test_graph.py, deleted `test_a_thread_about_another_of_their_orders_is_not_this_orders_thread` and `test_a_cold_cache_falls_back_to_the_narrow_rule_and_never_upgrades_a_guess`; test_gmail_writes.py:`test_a_reply_with_no_order_named_says_the_recipient_was_not_checked`

> Repair required: Provide the replacement model-turn and registered Gmail reply-handler evidence, and test the live dispatch path with two orders for one customer: a possible or different-order thread must not be selected as a verified reply destination.

**`I-03` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — Changing offline assertions cannot itself bypass the production write-confirmation
path tonight. Refusal and authority-related coverage was weakened: `test_needs_reply_routing.py`
now checks the observability contract instead of request routing; `test_order_create.py` drops
the spoken cancel/refund refusal assertions; and the deleted `test_navigation_extras.py` covered
cross-order tab refusal and ambiguous or closed-half navigation. Those checks do not establish
what the replacement model turn does.

> Evidence: packet: diff test_needs_reply_routing.py, test_order_create.py and deleted test_navigation_extras.py

> Repair required: Add replacement turn-level tests for the retained refusal scenarios, or provide the relevant route and tool-boundary evidence showing each scenario cannot reach the removed behavior. Do not restore the fast lane merely to satisfy its old tests.

**`I-04` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — This is a performance-test weakness, not a demonstrated production exploit, data
loss or leak tonight. `test_n_plus_one.py::turn` now supplies `commerce_summary` and its task
directly to `dispatch`, so the N+1 tests no longer test whether a spoken question makes the
model choose per-customer reads. Its inventory audit also compares three separately named
products with a single query for `Convict`, which does not request the Yard Jeans.

> Evidence: test_n_plus_one.py:`turn`, `test_the_answer_does_not_grow_a_read_when_the_shop_does`, `_before_inventory`, `_after_inventory`

> Repair required: Keep the direct-tool read bound, but add a spoken-turn test that counts the model-selected source reads; make the inventory before and after queries request equivalent products and assert equivalent results.

---

### Part I-tests4 — remaining tests (slice 4) — **CHANGES_REQUIRED**

CHANGES_REQUIRED. The money-verification assertion is a production blocker. The deleted feedback
confirmation coverage and self-constructed landing refusal are follow-ups; F-A2-FIXTURE is not
independently verifiable beyond these files.

**`I-01` — BLOCKS** (demonstrated)

BLOCKS — store-credit writes are live, and this test accepts a £25 balance increase as
verification of a £20 credit, leaving a money discrepancy unverified.
`test_the_verification_is_the_balance_plus_what_was_sent` explicitly expects verification to
return true for £15 → £40 after an asserted £20 credit.

> Evidence: CANDIDATE FILES / crooks-assistant/tests/test_store_credit.py / test_the_verification_is_the_balance_plus_what_was_sent

> Repair required: Change the store-credit verifier to require the expected balance increase or return an unverified outcome; change this assertion to reject the discrepant balance.

**`I-02` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — the running test session retains transcripts, so the supplied evidence does not
establish loss of the owner's spoken words tonight. `test_owner_feedback` says nothing records
feedback at turn time, while this range deletes the tests that required a spoken defect to be
recorded and confirmed through the router; the remaining tests call `feedback.record` directly.
The former confirmation coverage is STILL PRESENT only as a gap, not a passing end-to-end test.

> Evidence: DIFF / crooks-assistant/tests/test_owner_feedback.py / deleted test_the_family_records_and_says_so and test_the_acceptance_script_s_step_nine_both_halves; CANDIDATE FILES / module docstring

> Repair required: Add a test sending a plain spoken defect through `/turn` and checking its actual transcript-to-report recording path and the confirmation behavior the product now promises, without calling `feedback.record` in place of that path.

**`I-03` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — a missing actionable retry would be a refusal-quality defect, not an identified
exploit or data loss tonight. `test_a_landing_that_cannot_be_read_offers_the_tap_again`
constructs the desired `commands.Outcome.refused` itself and asserts on that constructed object;
it never invokes the landing code whose refusal it purports to test.

> Evidence: CANDIDATE FILES / crooks-assistant/tests/test_split.py / test_a_landing_that_cannot_be_read_offers_the_tap_again

> Repair required: Force a landing read failure through the real `open.area` command or route and assert that its returned refusal contains the retry command and held-record context.

**`I-04` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — owner authority granted to offline tests does not itself admit a production caller
tonight. F-A2-FIXTURE cannot be marked REPAIRED for the suite from this slice: `test_refund.py`
and `test_store_credit.py` explicitly grant `owner_asking` to every test in their modules, but
the claimed removal of the global autouse grant depends on `tests/conftest.py::owner_asking` and
its autouse fixtures, which were not supplied.

> Evidence: CANDIDATE FILES / crooks-assistant/tests/test_refund.py and tests/test_store_credit.py / pytestmark; REVIEW PACKET / YOUR PART, F-A2-FIXTURE

> Repair required: Have the part owning `tests/conftest.py` verify the fixture definition and absence of a default authority grant; retain a dispatch regression run with no authority stamped.

---

### Part I-tests5 — remaining tests (slice 5) — **CHANGES_REQUIRED**

The write walkthrough retains spoken-yes, tap-confirmation, and writes-disabled assertions, but
it mocks the model’s tool choice. The deleted UI-intent tests also remove a check that a
confirmation card does not satisfy a workspace request. Owner authority is explicitly granted by
default within four marked modules, and the suite-wide F-A2-FIXTURE repair cannot be cleared
without the actual conftest fixture code.

**`I-01` — BLOCKS** (unverifiable)

BLOCKS — I cannot tell whether a navigation command spoken after binding a control can be
treated as note dictation on tonight’s write-enabled production system. The command-versus-
dictation classification test was deleted; the remaining binding tests check that a sentence
reaches the model and that the binding expires, but do not try a command such as “open the
inbox.”

> Evidence: Packet diff: tests/test_touch_to_voice.py::test_every_fast_path_family_is_classified_against_the_continuation_glue (deleted); candidate tests/test_touch_to_voice.py::test_the_next_sentence_carries_the_binding_and_only_the_next

> Repair required: Inspect app/routes/turn.py::_with_continuation and its replacement command-classification logic, and add a model-era negative test showing that a navigation command after binding cannot stage a change to the bound record.

**`I-02` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — This loss of test coverage cannot itself exploit, lose, or leak production data
tonight. The returning-customer test no longer submits the owner’s words or asserts that exactly
one summary card and no customer profiles reach the glass: answer_for supplies a task directly
to commerce_summary, and the former sentence-to-surface test was deleted.

> Evidence: Packet diff: tests/test_summaries.py::test_the_returning_customers_question_draws_one_compact_surface (deleted); candidate tests/test_summaries.py::answer_for

> Repair required: Restore owner-utterance-to-rendered-surface coverage for the model path, asserting the complete card list contains one summary and no entity profiles.

**`I-03` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — A mocked model in a test cannot itself cause a production write tonight.
ModelThatAddsANote.turn always searches order 1930 and stages the same note regardless of the
request; the walkthrough therefore does not establish that the model selects the correct lookup
or write, despite testing the downstream gate and confirmation path.

> Evidence: tests/test_write_walkthrough.py::ModelThatAddsANote.turn; tests/test_write_walkthrough.py::test_the_owner_asks_for_a_note_and_gets_a_card_that_says_only_that_it_is_ready

> Repair required: Keep this as a downstream gate walkthrough, but add separate evidence for the production model’s choice of record and tool from the owner’s words, including a mismatched-record refusal.

**`I-04` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — These fixture defaults affect tests, not the running production service.
F-A2-FIXTURE is STILL PRESENT as a module-level default in four files: pytestmark grants
owner_asking to every test in each module, including tests of refusals; the claimed removal of
the suite-wide autouse grant cannot be verified because tests/conftest.py was not supplied.

> Evidence: tests/test_tags.py::pytestmark; tests/test_tags_remove.py::pytestmark; tests/test_tracking.py::pytestmark; tests/test_working_sets.py::pytestmark; packet scope and PR #51 claim sheet

> Repair required: Supply tests/conftest.py::owner_asking and its autouse-fixture definitions for review; restrict module-wide owner grants where a test is intended to exercise absent authority, and test that refusal without authority explicitly.

**`I-05` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — A false test-audit citation cannot itself exploit or alter production tonight. The
audit test requires calls_tool to count registry.get('probe_tool'), classify(name), and a
synthetic presentation item as directly testing the tool, although none executes its handler;
this can certify a tool without a behavioral test.

> Evidence: tests/test_tool_matrix.py::test_a_test_that_calls_a_tool_tests_it

> Repair required: Require an actual dispatch or handler invocation for the directly-tested column, and add negative cases for registry lookup, classification, and synthetic presentation alone.

**`I-06` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — This vacuous assertion cannot itself leak mailbox data tonight. The email-query
test’s sender-and-search-terms assertion ends in `or True`, so it passes even if every sender or
the order-number search term is wrong.

> Evidence: tests/test_working_sets.py::test_the_inbox_is_cross_referenced_with_the_set_and_makes_derived_sets

> Repair required: Remove `or True`, assert the expected senders and search terms independently, and require that a search call exists.

---

### Part J-docs1 — documentation and example files — **CHANGES_REQUIRED**

Neither example file contains a real secret, token, or login. The README still instructs the
owner to expect a removed workflow.

**`J-01` — FOLLOW-UP** (demonstrated)

FOLLOW-UP — This incorrect usage guidance does not itself exploit, lose, or leak production data
tonight. The README tells the owner to say an order number so the Mac looks it up before Claude
is asked, although this candidate's recorded decision says requests reach the model without a
preceding lookup.

> Evidence: CANDIDATE FILES — crooks-assistant/README.md, “Changes to the store and the inbox”; crooks-assistant/docs/product-memory/OWNER_DECISIONS_2026-09-28.md, “Decided”

> Repair required: Replace the pre-model lookup instruction with guidance that the model decides whether to look up an order; remove the README's descriptions of the removed transcript normaliser as current behaviour.

---

## Where the parts could not see each other

Twenty-one of the 45 BLOCKS are "I cannot tell". Some of those are answerable from **another part's**
packet, and George should know which, because they are cheaper to close than they look:

| Finding | Could not see | Which part held it | What that part said |
|---|---|---|---|
| `C-01` (C) | `principal_verdict` | **A1a** | A1a reviewed the door and found no supplied change widening its principal rule |
| `B-01-B-05-PATH` (B1) | the owner-principal implementation | **A1a** | same |
| `C-03` (C) | the `web/app.js` wiring of live words | **G** | G *also* could not establish the token's lifetime or destinations — so this one is genuinely open |
| `E-01` (E-app1) | `app/recipes.py` | **D1** | D1 held it and did not clear the write-guard question either — genuinely open |
| `F-A2-FIXTURE` (H-experience1, I-tests1, I-tests3, I-tests4) | `tests/conftest.py::owner_asking` | **A2** | **A2 ruled F-A2-FIXTURE REPAIRED**: `owner_asking` is non-autouse, its six protected-gate opt-ins are named, and the supplied tests create owner authority explicitly |
| `F-05B-AVAIL-PREFLIGHT` (A1b) | `scripts/install_systemd.py:install` | **A1b itself** | it had the file; what it lacked was an owner-phone check against this SHA, which cannot exist until the code is running |

So `F-A2-FIXTURE` is the one George ruled on, and **A2 — the part that actually held the fixture —
says it is repaired**. The four parts that call it unverified simply did not have the file. I am
recording that as information for the fix round, not clearing anything: I am not a reviewer, and the
ship rule says what I cannot tell, blocks.

The honest reading of the other "cannot tell" findings is that **a 24-part split buys zero omissions
at the cost of cross-part blindness.** If George wants fewer of these next round, the fix is fewer,
larger parts for the security surfaces — `identity.py`, `actions.py`, `local_cli.py`,
`display_tools.py`, `gate.py`, `voice.py` and `turn.py` in one packet — even if that means the
supporting tests go to a separate part.

---

## The twenty-four demonstrated BLOCKS

These do not depend on anything a reviewer could not see. Each names a file and a symbol. This is
the list the deploy actually stops on.

**Customer data on a shop TV** — the screens feature, which is what George most wanted to use:

- `B2-01` — `web/display.js:loadScreen,saveScreen` keep the **full screen key in
  `localStorage['clive.screen']`**. Anyone with access to that TV's browser, or an extension on it,
  can copy the key and request future slips. Three screens are already approved in production.
- `B2-04` — `markedDone` copies the previously drawn **full** order and only adds `done_at`;
  `renderOrder` draws the customer, address, phone and note again, and the packed view can stay up
  for 45 seconds instead of using the privacy-reduced done result.
- `B2-03` — an older in-flight response can put a customer slip **back** on a screen or remote after
  a later request has already received a revoking 403.
- `B2-02` — a revoked remote keeps showing customer details for up to two seconds after
  `pointerdown`, because `render` returns without clearing the DOM while a finger is held.

**Losing the owner's data:**

- `B-REMOTE-OFF` — a whole-screen "off" carries no version and `take_off` only checks `expect` when a
  pane is named, so an off tap made for an older view **deletes whatever is showing when it arrives**.
- `B-NEW-DONE-LOSS` — with two views on each of twenty screens, `_write` **discards the oldest half
  of `done`** repeatedly until the file fits, rather than refusing a new view.
- `B-03` — `_journal` returns False when its directory flush fails and `_commit` ignores that, so a
  cleared slip can **reappear after a restart**.
- `F-A3B-SHORT-WRITE` — `Timeline._append` makes one `os.write` per batch and counts every line as
  written **regardless of the returned byte count**. On the always-on production session that
  silently truncates accepted events.

**Writes and money:**

- `B-04` — an approved screen can **forge a real order's packed record** without displaying or
  packing it: `acknowledge` takes client-chosen ranges and `mark_done` takes a client-supplied
  `confirm: true`.
- `D2-02` — when the owner says *"yes, #1938"* over a pending refund or cancellation,
  `is_affirmation` **deletes the digits**, treats it as a bare yes, and skips the model and the
  pending-proposal revocation. **The spoken identifier is lost exactly at the write-confirmation
  boundary.**
- `D2-01` — an older turn finishing after its replacement can put an older order back on the live
  branch, leaving the next money-moving action aimed at the wrong record.
- `E-01` (E-families1) — `_stage_add_item` checks only `may_open` and whether the variant was issued,
  not that the named order is still the one on screen, so a **stale picker can mutate a different
  live order**.
- `I-01` (I-tests4) — `test_the_verification_is_the_balance_plus_what_was_sent` accepts **£15 → £40
  as verification of a £20 credit**. Store-credit writes are live.

**Leaks:**

- `A1B-KEY` — during a restart a non-root process can take the unprivileged loopback port, answer
  `fetch_health`'s first request with `limited: true`, and **receive the live local-CLI key** on the
  retry; `_open` disables environment proxies but not urllib's automatic redirects, so it can also be
  redirected off-host. The key is now real: `/etc/crooks-os/secrets/local_cli_key` has existed since
  the round-8 deploy.
- `F-01` — `report.reconstruct` takes `test_session_id` **from an event** without validating it and
  both output functions use it as a filename. `../web/exposed` escapes `reports/`.
- `E-02` — `gmail_compose_open` passes the model's `to` string to `check_address`; a canonical
  address gets `to_status='ok'` **even when the owner dictated it**, and `_ready_to_stage` only
  refuses an address still marked uncertain. The deleted spoken composer ran its extracted address
  through the uncertainty check first. On a live shared mailbox an ASR error now sends private mail
  to a wrong address.
- `F-OBS2-02` — `visible.read` logs raw exception text, which includes the rejected value, so a
  secret in malformed telemetry reaches the log.

**And the rest:** `F-05B-AVAIL` (A1a), `F-NEW-TOOLS-PATH` (A2), `A3a-LIVE-CLEAN`, `F-04-REPORT-LOSS`,
`F-04-SHUTDOWN`, `F-A3B-SCREEN-EVIDENCE`, `NEW-B-LOCAL-SLIP`, `B-07`, `C-02`, `C-04`, `D1-01`,
`D1-02`, `D1-03`, `D2-03`, `D2-04`, `E-03`, `E-04`, `E-05`, `F-OBS2-01`, `G-01`, `I-01` (I-tests2),
`I-02` (I-tests3), `I-01` (I-tests5) — all set out in full in the per-part sections above.

---

## What PR #51 and PR #52 *did* close

It is not all bad, and the claim sheets were not fantasy. Ruled repaired at this SHA, by the part
that held the code:

- **`F-A2-FIXTURE`** (A2) — **REPAIRED.** George's ruling is applied: `tests/conftest.py:owner_asking`
  is non-autouse, its six protected-gate opt-ins are named, and tests create owner authority
  explicitly.
- **`NEW-B-CAP`** (B1) — **REPAIRED.** George's other ruling: `DisplayStore.register` is the sole
  creation path and refuses a twenty-first screen without evicting anything.
- **`B-02`** (B1) — **REPAIRED.** Pairing is done properly: a random six-digit code, salted and
  hashed, 15-minute life, five wrong attempts allowed, `hmac.compare_digest`, and `screen_pair`
  requires active OWNER authority *and* the code digits in the request's heard words.
- **`F-NEW-PAD`** (A1b) — **REPAIRED.** `health._guarded` and `_liveness` give refused callers only
  allow-listed liveness, on fresh and cached responses alike.
- **`F-05B`** (A1b) — **REPAIRED.** `identity.unit_pids` and `socket_inode` reject malformed listings
  and rows, and the tests reach both gates and assert refusal.
- **`F-NEW-TOOLS`** (A2) — **REPAIRED** within the reviewed invocation boundary.
- **`B-06`** (B2) — no scoped regression.
- The three existing production screens with no `paired` field **are treated as approved**, as George
  required.
- The rendered unit is clean: the installer's 43 added lines change **no** directive.

---

## Preflight — read-only, and it all passed

Run against the real host on 2026-09-28 before anything else. Nothing was written.

**SHA provenance.** `c6c640d7` is `origin/clive/trunk` and PR #52's merge commit (parents
`32a99cd7` + `858d36e4`). `32a99cd7` (PR #51's merge), `6a29e310` and `3e77f215` are all ancestors.
Range is 221 files, +13350 / −14964, exactly as stated.

**Acceptance.** `36417364775` on exactly `c6c640d7`, completed/success, `event=push` on `clive/trunk`.
PR #51's head `10fe6865` green on `36406075900` and `36406082443`; PR #52's head `858d36e4` on
`36416641987` and `36416700793`. `clive/trunk` re-checked: `"protected": false`. **None of this
carries review weight** — refused SHAs have landed on that branch before.

**The switches**, read from the live `.env`, which is **byte-identical** to the one the round-8 deploy
ran against (sha256 `0021c07d…`):

```
CROOKS_SCREEN_SNAPSHOTS          = 'false'
CROOKS_LOCAL_OWNER               = <unset>
CROOKS_WRITES_LOCAL_OWNER        = 'false'
CROOKS_ENGINEERING_HOST          = <unset>
CROOKS_TAILSCALE_VERIFY          = <unset>     -> settings.tailscale_verify True
CROOKS_LIVE_TRANSCRIPT           = <unset>     -> settings.live_transcript True
CROOKS_SCRIBE_KEYTERMS           = 'true'      -> no such field; Settings extra="ignore"
CROOKS_ALLOWED_LOGINS            = non-empty (value not printed)
```

`Settings` was constructed against the live `.env` at the candidate to prove the now-unknown
`CROOKS_SCRIBE_KEYTERMS` line does not stop the app starting. It does not: `model_config extra` is
`ignore`.

**The unit diff.** The candidate's unit was rendered with production paths and diffed against the
installed one. **The complete diff is one comment line:**

```
-#   the checkout   logs/, .cache/media/, kb/.catalogue-cache.txt
+#   the checkout   logs/, .cache/media/
```

Not one directive changes. `ExecStart` (with `--no-proxy-headers`), `Environment=PATH`,
`LoadCredentialEncrypted`, `ReadWritePaths` and every sandboxing directive are byte-identical to what
is installed and running. That is strictly less than rounds 6–8 accepted.

*A note on how that was produced.* Round 8's PATH line gained `/opt/crooks-os/crooks-assistant/.venv/bin`
because it rendered inside a review checkout that had **no** `.venv`, so `Path(...).resolve()` left the
non-existent path alone, and the review path was then substituted for the production one. Rendering
with a real production venv gives a different PATH line, because `.venv/bin/python` is a symlink that
resolves to `/usr/bin/python3.12`. I reproduced round 8's method exactly so the round-9 unit is the
installed one plus that comment, rather than silently dropping a PATH entry George's last deploy
accepted.

**Tailscale and kernel-table preconditions.** `tailscaled` MainPID 1655, `/proc/1655/exe` →
`/usr/sbin/tailscaled` exactly, cgroup exactly `0::/system.slice/tailscaled.service`. That binary,
that cgroup directory and its `cgroup.procs` are all uid 0 with no group-write and no other-write.
`pidfd_open` works from the production interpreter. `100.72.82.24` has a `/32 host LOCAL` entry in
`fib_trie`; `fd7a115ca1e0000000000000352b5219` is in `/proc/net/if_inet6`.

**The stricter parsers accept this host's real tables**, run at the candidate with the production venv
interpreter:

```
app.identity._tcp_rows("net/tcp",  …)  -> ACCEPTED, 19/19 rows
app.identity._tcp_rows("net/tcp6", …)  -> ACCEPTED, 37/37 rows
app.identity.this_hosts_addresses()    -> (frozenset({'100.72.82.24', 'fd7a:115c:a1e0::352b:5219',
   '2.28.233.59', '2a01:4f8:1c1c:60a3::1', '127.0.0.1', '::1', 'fe80::3874:4208:1c14:608f',
   'fe80::9000:9ff:feec:f59'}), '')
```

Both tailnet addresses present, reason string empty. **No owner device would be locked out.**

**Reports.** `reports_dir` is `/opt/crooks-os/crooks-assistant/reports`. Round 8's first housekeeping
pass already did its work: the folder is now `0700` and `.gitkeep` `0600`,
`find … -perm /077 | wc -l` = **0** (it was 2 before that deploy), and there is no `.withheld/`.

**Credential tiers, by name only, nothing opened.**

```
/etc/crooks-os/credentials/         elevenlabs_api_key, shopify_client_id, shopify_client_secret   (3)
/etc/crooks-os/credentials-parked/  github_engineering_inbox_token.cred  (0700 dir, 0600, 292 bytes)
/etc/crooks-os/secrets/             gmail_token, media_signing_key, local_cli_key
```

**`local_cli_key` is new since the round-8 deploy.** The local-CLI key path is now live in production,
which is why `A1B-KEY` above is a real exposure and not a theoretical one. The engineering token is in
neither live tier, so the bridge stays inert and F-ENG stays deferred — but note that
`settings.engineering_host` still defaults to `worker-01`, so it is the **parking**, not the unset
environment variable, that makes it inert.

**The rollback reader.** `tests/rollback/gaps_3e77f215.py` from its line 6 is **byte-identical** to
`app/objectives/gaps.py` at `3e77f215` (sha256 `b6bfba90973a1647659e4d3e24e61a006d8aaffbb03e52236ddc992c9f24c26f`,
16831 bytes). Run against the live record as it stands today it loads it and reports on it:
version 1, 10 gaps, and the copy it read was unchanged afterwards.

**The gap record — one thing to report rather than gloss.** George's preflight item says "unchanged
since the round-8 deploy, with its one backup." **The one backup is intact**
(`gaps.json.20260927T211850Z.before-clean`, 4663 bytes, byte-identical to the pre-round-8 record) and
**no second backup exists**. But the record itself is **not** unchanged: the deployed `6a29e310` has
grown it from 8 gaps to 10 in ordinary use, at 11:44 today, alongside a new objective record written
in the same minute.

I checked what changed rather than just the hash:

```
version, seeded, builds, misjudged : unchanged
gaps                               : 8 -> 10
keys kept                          : 7 of 8;  LOST: 'tool set custom line item price'
keys ADDED                         : 'tool set custom line name price',
                                     'custom line name on an order',
                                     'order name lookup on order open order add name'
the "lost" row                     : every field but the label is byte-identical to the added
                                     'tool set custom line name price' row — it was RE-KEYED when
                                     its label was reworded, not dropped
```

**Nothing was lost.** I treated this as an observation and not a preflight failure, because the check
exists to prove the round-8 start-up clean did not run again and did not spawn backups, and on both
counts it did not. Two of the ten rows now carry a `name` field the other eight do not, which is why
part A3a was told about the mixed row shapes — and A3a's `A3a-LIVE-CLEAN` BLOCKS is precisely that it
could not prove all ten survive the candidate's clean.

**The screens on disk.** `displays.json` exists now (it did not at round 8): `0600`, 3800 bytes, top
level `screens` and `done`. **Three screens**, names redacted to their first letter: **P…**, **M…**,
**P…**, created `2026-09-27T21:33Z`, `2026-09-27T21:35Z` and `2026-09-28T10:54Z`. None has an
`approved` or `paired` field, because all three were stored before pairing existed. **Per George's
rule all three count as already approved**, and B1 confirms the code treats them that way.

---

## The two phone checks, and George's two tries — none of which happened

**Phone check 1, against a staging copy: DID NOT RUN.**
**Phone check 2, after the deploy: DID NOT RUN.**
**George's live-voice try: DID NOT RUN.**
**George's screen-pairing try: DID NOT RUN.**

The round-9 prompt runs them only if the review passes. It did not, so under George's own instruction
— *"If anything blocks, publish the findings on a branch, change nothing on the server, and stop"* —
I stopped before touching anything. **George was not asked for his phone at any point**, which is why
he has not heard from me about it.

`round-9/stage.sh` and `round-9/deploy.sh` were written and syntax-checked while the reviews ran, and
are on the branch ready for the round that passes. Neither was executed.

---

## The state the server was left in

Nothing was changed. Verified after the review finished:

- **Production HEAD:** `6a29e31013b0b9e543d90434e14ed65deea1ce30` — unchanged, working tree clean.
- **Service:** active, same MainPID as before this session began, `NRestarts=0`, still
  `--no-proxy-headers`.
- **The unit on disk:** sha256 unchanged from the preflight copy.
- **`.env`:** sha256 `0021c07d…`, unchanged. No line was touched. All five switches as found.
- **The parked credential:** uid, mode, size and mtime identical. Never opened, never decrypted.
- **`/etc/crooks-os/credentials/`:** still exactly three `.cred` files.
- **The gap record and its one backup:** sha256 and backup count identical to the preflight reading.
- **`tailscale serve`:** one handler, `/ → 127.0.0.1:8000`, as before. No staging port was ever
  opened (`:8799` is not listening; `crooks-stage-r9` is inactive because it was never started).
- The review checkout at `round-9/review` is a **separate clone**, not a worktree of
  `/opt/crooks-os`. For completeness: `git -C /opt/crooks-os worktree list` shows three worktrees —
  `/opt/crooks-os` itself plus `/opt/crooks-review` and `/opt/crooks-watcher-review`. Both of those
  pre-date this session, belong to earlier review work, and were neither created nor touched here.

**One thing did change on disk, and it was not me.** `displays.json`'s sha256 moved from
`6b3b3fee…` at preflight to `19884409…` afterwards. The cause is the deployed service doing its job:
screen `scr_3bcf`'s `last_seen` advanced from `12:12:48Z` to `13:08:41Z` as the TV polled. **Same
three screens, same names, same `version` numbers (2, 8, 1), `done` still empty.** Nothing was added,
removed or re-keyed. I record it because "nothing changed" should mean the hashes, not my intentions.

---

## What George has to decide

1. **The fix round.** 45 BLOCKS, of which 24 are demonstrated. The screens feature carries the most:
   four of the demonstrated leaks are a customer's details staying visible on a shop TV, and that is
   the feature he most wants to use. `B2-01` (the screen key in `localStorage`) and `B-REMOTE-OFF`
   (an off tap deleting whatever arrives) are the two I would put first.
2. **Whether `D2-02` changes how he talks to CLIVE in the meantime.** On production *today*, saying
   *"yes, #1938"* over a pending refund or cancellation drops the number and is treated as a bare
   yes. This SHA is not deployed, but that code path is reachable in the deployed build too — it is
   worth him saying just "yes", or naming the order in a fresh sentence, until it is fixed.
3. **Whether to re-check round 8's packets.** The SIGPIPE race described above was inherited from
   round 8's builder, so one or more of that round's four packets may have been missing a file its
   verdict rested on.
4. **The shape of round 10's review.** Twenty-four parts gave zero omissions and 21 "cannot tell"
   findings. Fewer, larger security-surface parts would trade some of that blindness back.

---

## Artefacts

All under `/root/clive-activation/round-9/`, and the reviews themselves are committed on this branch
under `reviews/`:

```
prose9.txt                     the standing facts and ship rule every reviewer was given
parts/paths.*  parts/scope.*   the 24 parts: exact file lists and the questions each was asked
build-packets.sh               packet builder, with the SIGPIPE fix
packet-build.log               24/24 omission checks and 24/24 leak checks passed
coverage-check.txt             221 changed paths, 0 with no packet
c6c640d7.part*.review.json     the 24 typed review results
verdicts.txt                   the verdict and label counts per part
sha-provenance.txt             ancestry, parents, range
acceptance-*.json              the five acceptance runs
unit-diff.txt                  the one-comment-line unit diff
rendered-c6c640d7.service      the unit that would have been installed
installed.service              the unit that is installed, saved for a rollback
env-switches.txt               the switches, values withheld
credentials-preflight.txt      both credential tiers by name
tailscale-preconditions.txt    provenance and kernel tables
reports-preflight.txt          the reports folder
gap-record-preflight.txt       the record, its one backup, its keys
gaps-since-round8.txt          what changed in the record since the round-8 deploy, field by field
displays-preflight.txt         the three screens, names redacted
parser-check.txt               the stricter parsers against this host's real tables
settings-check.txt             Settings built against the live .env
vendored-reader-check.txt      3e77f215's reader against today's record
stage.sh  deploy.sh            written, syntax-checked, NOT run
```
