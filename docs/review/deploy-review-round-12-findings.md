# Deploy review, round 12 — 361b01380737f8f48020dd30cef1e5f750e700bb

**Deployed: no. Production still runs 6a29e31013b0b9e543d90434e14ed65deea1ce30.**

Nothing on the server was changed. No staging copy was raised, no phone check was asked of
George, the checkout stayed at 6a29e310 with 0 dirty entries, the unit was not touched, the
`.env` was not touched, and the parked engineering credential was never opened.

| | |
|---|---|
| Candidate | `361b01380737f8f48020dd30cef1e5f750e700bb` — clive/trunk head, PR #57's merge commit |
| Production | `6a29e31013b0b9e543d90434e14ed65deea1ce30` — deployed 27 Sep under George's waiver |
| Range | 6a29e310..361b0138, seven PRs (#51–#57), 378 changed paths |
| Blocking findings | **62** (35 from the parts, 27 from the evidence packets) |
| Follow-ups | 69 |
| Open findings settled | 53 of 100 |
| Parts | 40, zero omissions, all within the 300 KB budget |
| Evidence packets | 40, covering all 100 index entries, one slot each |
| Follow-up packets | 25 (18 for the parts, 7 for the evidence), the one round the rule allows |
| Dispatches | 106 |
| Packet bytes | 21,151,479 |

## George's ship rule, as it was applied

Running the round-12 prompt is George confirming this rule, and the prompt says so in terms.
It is unchanged from rounds 9 and 10:

> A part BLOCKS the deploy only when it has a material finding that meets at least one of
> these, on production as it is actually configured tonight: it can be exploited; it would
> lose data; it would leak data. "As configured" means Tailscale-only access, George's login
> on the allow-list, the switches as they stand, and writes as they are.
> Every other material finding is a FOLLOW-UP.

Every reviewer was given that rule and told to label every material finding BLOCKS or
FOLLOW-UP with one sentence on why. Every label was then checked by the deploy owner. Where
the owner disagreed with a label, or could not tell, the finding was treated as BLOCKS and
that is said in its row.

## Why this did not deploy

Fifteen of the parts' findings are not "I cannot tell" — they are asserted defects in the
code, in the two categories the rule names. The deploy owner independently read the code
behind two of them and confirmed both:

**`S2Ba/F-01` — one customer's order confirmation can go to another customer's address.**
`app/families/order_create.py:_choose_customer` refreshes `facts.customer` on every customer
change, but fills the typed `email` field only `if not ws.value(workspace, "email")`. Open a
workspace for Alice and the field is filled with Alice's address. Then
`shopify_order_build(customer_id=Bob)` reaches `_customer_by_id` → `_choose_customer`, which
now leaves the typed field alone because it is no longer empty. At Prepare, `_draft_input`
builds the draft with `"customerId": Bob` and `body["email"] = ws.value(workspace, "email")`
— Alice's. Shopify then sends Bob's order confirmation, with his purchase details, to Alice.
That is a leak of one customer's data to another, on production as configured, with writes
enabled. **Verified in the code by the deploy owner, not taken on the reviewer's word.**

**`F/F-01` — correcting one part of an address can silently shorten another part.**
`app/families/address.py:_from_order` truncates every field as it loads the existing address
(`name` to 80, `address1`/`address2`/`city` to MAX_LINE, `postcode` to 12, `province_code`
to 5, `country_code` to 2). Those truncated values become the workspace's starting values,
and `_stage` submits every field, not only the edited one. An existing street longer than
MAX_LINE is therefore shortened on the customer's order when the owner only corrects the
postcode. That is data loss, with writes enabled. **Verified in the code by the deploy owner.**

Either one on its own stops tonight's deploy under the rule. There are thirteen more asserted
defects of the same two kinds, listed in section C, plus 20 part findings and 27 evidence
findings that survived their one follow-up packet unsettled and are BLOCKS for that reason.

## What the review was, this round

Two halves, as the prompt set out.

**The parts.** The whole range 6a29e310..361b0138 — 378 changed paths — re-planned into 40
parts on round 10's packing: the security surfaces together, tests in sibling parts, each
split half given the signatures and docstrings of what it calls across the split. Every
changed path is in at least one part, and that was verified **independently after the packets
were built**, by reading the built packets rather than trusting the planner: 378 of 378, zero
omitted. The 15 PNG screenshots under `docs/screens/r12-objectives/` were put in a
metadata-only part — their bytes are not text and would have consumed 4.25 MB of budget — and
the deploy owner opened and read all fifteen instead (see section D).

**The evidence packets.** The index at `crooks-assistant/docs/review/evidence/` holds 100
entries across seven files. Its completeness was checked first, against round 10's record:
every round-9 material finding not ruled REPAIRED (78 of them) and every round-10 new material
finding (14) has an entry. **Nothing is missing.** Four ids appear twice on purpose — the same
finding raised from two sides, client and server, or by two parts with different doubts — so
96 distinct ids carry 100 entries. Each packet carried the finding as every record worded it
with its `required_repair`, the entry's question, the entry's answer plainly labelled
**THE AUTHOR'S CLAIM, NOT EVIDENCE**, every named file whole at the candidate (or, for
`web/app.js`, the named functions cut out whole with their real line numbers), and the source
of every named test. Every packet was leak-checked.

**The instruction round 10 found missing** was added to every packet: `required_repair` must
never be empty, and a REPAIRED ruling says "None." and why. **No finding came back with an
empty `required_repair`** — 0 of 207.


## A. The parts — new findings over the whole range

40 parts over 378 changed paths, zero omissions. Each part's label is the reviewer's own,
checked by the deploy owner; where a part said CANNOT TELL and named a file, that file was
sent in one follow-up packet and the label below is the answer to it. What was still not
settled after that one follow-up is BLOCKS, as the rule requires.

### S1 — the door and authority — identity, admission, the local CLI, health, and the whole tool-authority chain

10 path(s) · 2 material finding(s): **1 BLOCKS**, 0 FOLLOW-UP, 1 settled as not a defect.

**`S1-NEW-01` — NOT A DEFECT**  
_settled by follow-up: no defect_

BLOCKS — I cannot rule out an exploitable or data-losing immediate tool call on writes-enabled
  production without the missing handlers and registrations. CANNOT TELL: the gate allows
  `shopify_order_build`, `show_again` and `close_screen` to execute as reads, but the supplied files
  do not establish what their handlers do or whether `show_again` requires an issued `ref`.

- evidence: `Packet section CANDIDATE FILES: app/tools/gate.py (`_KNOWN_TOOLS`, `classify`) and app/tools/dispatch.py (`dispatch`)`
- required repair: Supply app/tools/registry.py, app/families/order_create.py, app/tools/show_again.py and
  app/tools/close_screen.py for review; ensure each immediately executed tool stays within its
  claimed effects and enforces its required issued ID.

**`S1-NEW-02` — BLOCKS**  
_settled by follow-up: defect, BLOCKS_

BLOCKS — Production's always-on timeline may leak personal data, and I cannot settle whether
  downstream redaction prevents that leak without the missing files. CANNOT TELL: `_spoken_fields`
  retains strings under unrecognised nested keys before arguments are emitted, while `_result_shape`
  emits a read result's `name` verbatim; whether the subsequent redactor or timeline removes those
  values is not shown.

- evidence: `Packet section CANDIDATE FILES: app/tools/dispatch.py (`loggable_args`, `_spoken_fields`, `_result_shape`, `_Trace`)`
- required repair: Supply app/logging/turnlog.py and app/observability/timeline.py to establish what reaches disk.
  If either path retains personal text, shape or redact nested argument values and result names
  before emission, with a production-recording regression test.

### S1T — the door's tests

11 path(s) · 2 material finding(s): **0 BLOCKS**, 0 FOLLOW-UP, 2 settled as not a defect.

**`S1T-N01` — NOT A DEFECT**  
_settled by follow-up: no defect_

BLOCKS — An unverified owner-door setting could be exploited, so this configuration gap cannot be
  cleared from the supplied files. CANNOT TELL whether forged forwarding headers are refused in
  production: the new real-door tests explicitly set `tailscale_verify=True`, while production
  leaves `CROOKS_TAILSCALE_VERIFY` unset; the setting's default and the door's behavior are outside
  this packet.

- evidence: `crooks-assistant/tests/test_turn_authority_path.py:production fixture; REVIEW PACKET: George's ship rule`
- required repair: Supply crooks-assistant/config/settings.py and crooks-assistant/app/routes/actions.py at this
  SHA to establish the unset setting's behavior; add a forged-header /turn test using the
  production default rather than forcing verification on.

**`S1T-N02` — NOT A DEFECT**  
_settled by follow-up: no defect_

BLOCKS — Whether bounded service work can run the new screen or order-building tools could not be
  settled; unintended screen changes or order edits would be exploitable. CANNOT TELL whether those
  tools are excluded: the changed gate test checks their allow-list membership and count, while the
  service-authority refusal cases omit `show_again`, `close_screen` and `shopify_order_build`. Their
  gate and authority implementations were not supplied.

- evidence: `crooks-assistant/tests/test_gate.py:test_the_allow_list_gained_engineering_status_the_screens_and_nothing_else; crooks-assistant/tests/test_tool_boundary.py:NOT_THE_SERVICES`
- required repair: Supply crooks-assistant/app/tools/gate.py, crooks-assistant/app/tools/authority.py, crooks-
  assistant/app/tools/show_again.py, crooks-assistant/app/tools/close_screen.py and crooks-
  assistant/app/families/order_create.py at this SHA; test each new tool under a derived service
  authority and assert that none can change an order workspace or screen.

### S2a — the turn and the write boundary — the turn itself and the action engine

5 path(s) · 3 material finding(s): **2 BLOCKS**, 1 FOLLOW-UP, 0 settled as not a defect.

**`S2a-01` — BLOCKS**

BLOCKS — A wrong-order write can lose existing order data on production, where writes are enabled.
  If the owner asks to set #1940’s note to text that itself mentions #1940, but the model prepares
  the change for #1938, `_written_numbers` removes #1940 from the named targets and `_off_target`
  lets the mismatched proposal reach its hold card.

- evidence: `CANDIDATE FILES — crooks-assistant/app/routes/turn.py, `_orders_named`, `_written_numbers`, `_off_target` and `_answer``
- required repair: Do not subtract every occurrence of a number in the proposed content from the owner’s target.
  Distinguish the requested target from quoted content; refuse an ambiguous target rather than
  delivering a mismatched proposal. Test a note that repeats its target number while the
  proposal names another order.

**`S2a-02` — FOLLOW-UP**

FOLLOW-UP — This can replace the owner’s current screen and cursor, but the supplied code does not
  establish a direct exploit, shop-data loss or leak. `_answer` checks whether its turn was
  abandoned before awaiting `_hold_to_the_screen`; a gated read in `_draw_held` can then let a newer
  turn start or finish before the older answer resumes and calls `branch.visit` and `branch.shown`.

- evidence: `CANDIDATE FILES — crooks-assistant/app/routes/turn.py, `_answer`, `_hold_to_the_screen` and `_draw_held``
- required repair: Recheck the branch instruction sequence and cancellation state after the awaited screen read and
  before delivering proposals or changing the cursor, stored screen or progressive workspace.
  Test two overlapping turns with the older screen read delayed.

**`S2a-03` — BLOCKS**  
_settled by follow-up: defect, BLOCKS_

BLOCKS — CANNOT TELL whether the made-once write boundary prevents duplicate orders or credits; if
  it does not, production writes could lose data. The commit route calls `workspaces.commit_refused`
  and `before_commit` before the engine’s atomic claim, but the supplied packet omits `crooks-
  assistant/app/families/_workspace.py`, whose body is needed to judge how those calls behave for
  concurrent, unarmed and retried commits.

- evidence: `CANDIDATE FILES — crooks-assistant/app/routes/actions.py, `commit`; crooks-assistant/app/actions/engine.py, `commit`; REVIEW PACKET — sibling-file contracts (no `_workspace.py` body)`
- required repair: Supply `crooks-assistant/app/families/_workspace.py` and evidence for concurrent, unarmed and
  retried workspace commits; if its reservation is not atomic and correctly released after
  refusals, repair that boundary.

### S2b — the turn and the write boundary — the writing families and the mail writes

4 path(s) · 4 material finding(s): **3 BLOCKS**, 1 FOLLOW-UP, 0 settled as not a defect.

**`S2b-01` — BLOCKS**

BLOCKS — A deceptive Reply-To on an inbound email can cause the owner to authorise a reply to a
  different mailbox than the fixed recipient shown in the composer, leaking the reply despite owner-
  only Tailscale access. `_thread_sender` displays the last inbound From address and marks it
  checked, while `thread_context` directs the eventual reply to Reply-To when present; the final
  hold card names the actual address, but does not remove the contradictory earlier assurance.

- evidence: `CANDIDATE FILES: crooks-assistant/app/families/compose.py (_thread_sender, gmail_compose_open, _stage_args); crooks-assistant/app/tools/gmail_writes.py (thread_context, gmail_send_reply)`
- required repair: Show the effective reply recipient, including Reply-To, on the composer; refuse to open a reply
  if it cannot be established, and refuse staging if the recipient subsequently differs from the
  one shown.

**`S2b-02` — BLOCKS**  
_still not settled after the one follow-up -> BLOCKS_

BLOCKS — An unexcluded second store-credit mutation on tonight's write-enabled production could lose
  money. CANNOT TELL whether an ambiguous Shopify result or a second prepared proposal leaves the
  workspace locked against another credit: the new protection relies on `ws.sending`, `ws.note`,
  `ws.finished`, and `ws.prepared`, whose bodies were not supplied in `crooks-
  assistant/app/families/_workspace.py`.

- evidence: `CANDIDATE FILES: crooks-assistant/app/families/store_credit.py (_execute, given, shopify_store_credit_add); missing crooks-assistant/app/families/_workspace.py`
- required repair: Supply crooks-assistant/app/families/_workspace.py and the relevant commit behavior from crooks-
  assistant/app/actions/engine.py for review; ensure an ambiguous credit remains locked and that
  two proposals for one workspace cannot each credit the account.

**`S2b-03` — BLOCKS**  
_settled by follow-up: defect, BLOCKS_

BLOCKS — A still-committable proposal addressed to the old recipient after an owner edits a composer
  could leak the email on this write-enabled deployment. CANNOT TELL whether `compose.field`
  withdraws an already prepared send: `_compose_field` changes the composer without revoking
  proposals, while the missing `crooks-assistant/app/routes/command.py` may or may not perform that
  revocation; the mail proposal's observed token state does not check composer contents.

- evidence: `CANDIDATE FILES: crooks-assistant/app/families/compose.py (_compose_field, _compose_stage); crooks-assistant/app/tools/gmail_writes.py (_observe_token); missing crooks-assistant/app/routes/command.py`
- required repair: Supply crooks-assistant/app/routes/command.py for review. If it does not revoke pending
  proposals on a real composer edit, add that revocation or bind each proposal to a checked
  composer revision at commit.

**`S2b-04` — FOLLOW-UP**

FOLLOW-UP — A false discard confirmation neither exploits the configured service nor loses or leaks
  the draft, but misinforms the owner. `_latest_draft` accepts VERIFIED drafts, whereas
  `_draft_discard` calls `revoke_ids`—which withdraws only waiting proposals—and then says
  “Forgotten. Nothing was saved” even when the draft is already in Gmail.

- evidence: `CANDIDATE FILES: crooks-assistant/app/families/compose.py (_latest_draft, _draft_discard); CONTRACT ONLY: crooks-assistant/app/actions/engine.py (revoke_ids)`
- required repair: Distinguish verified drafts from pending proposals: accurately say that the saved draft remains,
  or perform and confirm its supported deletion before saying it was forgotten.

### S2T — the turn's and the write boundary's tests

11 path(s) · 2 material finding(s): **2 BLOCKS**, 0 FOLLOW-UP, 0 settled as not a defect.

**`S2T-01` — BLOCKS**  
_settled by follow-up: defect, BLOCKS_

BLOCKS — The missing turn implementation leaves a possible wrong-record write unresolved on
  production with writes enabled, and the packet's uncertainty rule makes that blocking. CANNOT TELL
  whether the round-12 on-screen claim check rejects a model answer claiming one order is displayed
  after reading another: the supplied test scripts the correct order read, but the body of crooks-
  assistant/app/routes/turn.py is not supplied.

- evidence: `CANDIDATE FILES — tests/test_turn_boundary.py::test_a_number_that_is_not_the_open_order_is_drawn_from_what_was_read_for_it; sibling-file contract — app/routes/turn.py::_hold_to_the_screen`
- required repair: Supply crooks-assistant/app/routes/turn.py at this SHA and an adversarial test in which the
  model claims one order is on screen after reading another; verify the wrong record is not
  substituted or made the target of an action, and repair the route if it is.

**`S2T-02` — BLOCKS**  
_still not settled after the one follow-up -> BLOCKS_

BLOCKS — An unverified live model-to-write path could allow an unapproved change and lose data on
  production with writes enabled, so this uncertainty blocks. CANNOT TELL whether live Claude tool
  calls preserve the prepare-only boundary: tests/test_turn_boundary.py substitutes Scripted, which
  calls dispatch directly, while the bodies of crooks-assistant/app/providers/max_agent_sdk.py and
  crooks-assistant/app/tools/dispatch.py are absent.

- evidence: `CANDIDATE FILES — tests/test_turn_boundary.py::Scripted.turn and reads; REVIEW PACKET — sibling-file contract for app/routes/turn.py::_provider_turn`
- required repair: Supply crooks-assistant/app/providers/max_agent_sdk.py and crooks-
  assistant/app/tools/dispatch.py at this SHA, and verify the live provider's write calls pass
  through the gate and stage a proposal without executing a mutation before the owner's gesture;
  repair any bypass found.

### S2Ba — orders by voice — building the order: the family, its sizes and its workspace

4 path(s) · 4 material finding(s): **2 BLOCKS**, 2 FOLLOW-UP, 0 settled as not a defect.

**`F-01` — BLOCKS**

BLOCKS — On production as configured, this can leak one customer's order confirmation and purchase
  details to another customer's email address. When an open order is changed from Alice to Bob,
  `_choose_customer` replaces the customer but fills the confirmation email only if the field is
  empty; Alice's existing email survives, and `_draft_input` puts it on Bob's draft. The draft
  comparison accepts that same stale email as expected.

- evidence: `CANDIDATE FILES — crooks-assistant/app/families/order_create.py, `_choose_customer`, `shopify_order_build`, `expected_card`, `_draft_input``
- required repair: On a change of customer identity, clear or replace the previous customer's confirmation email.
  Require an explicit fresh choice before retaining an independently entered address for the new
  customer, and test both name- and ID-based switches through Prepare.

**`F-02` — BLOCKS**

BLOCKS — On production as configured, this can leak a new customer's order contents by delivering
  them to the previous customer's address. Opening from Alice's order selects its shipping address;
  a subsequent `shopify_order_build(customer_id=Bob)` changes the customer without clearing that
  source or address choice. Prepare then builds a draft for Bob with Alice's shipping address and
  verifies it against that same stale choice.

- evidence: `CANDIDATE FILES — crooks-assistant/app/families/order_create.py, `_from_order`, `_customer_by_id`, `shopify_order_build`, `_going_to`, `_draft_input``
- required repair: Bind an order-derived address to its source customer. When the customer changes, clear that
  address choice and require a fresh shipping choice; reject conflicting customer and source-
  order arguments on open. Test that Prepare cannot combine Bob's customer ID with Alice's
  order-derived address by default.

**`F-03` — FOLLOW-UP**

FOLLOW-UP — This prevents a valid next-size request but does not itself exploit the owner-only
  service or lose or leak data. `_read_product_of` fetches only the first 100 product variants and
  discards the separately returned starting variant's options; for a product whose requested variant
  or next size is beyond that page, `sizes.step` incorrectly reports that the variant or size does
  not exist.

- evidence: `CANDIDATE FILES — crooks-assistant/app/families/order_create.py, `VARIANT_SIBLINGS_QUERY` and `_read_product_of`; crooks-assistant/app/families/_sizes.py, `step``
- required repair: Fetch all relevant variant pages, with a safe bound and an explicit incomplete-result refusal,
  and retain the starting variant from the direct lookup. Test a starting variant and a target
  size beyond the first 100.

**`F-04` — FOLLOW-UP**

FOLLOW-UP — This can build the wrong garment for an owner-only next-size request, but the shown path
  does not establish exploitation, data loss or data leakage. When both `order_id` and `variant_id`
  are supplied, `_fill_opened` reads the source order but never checks whether the variant is on one
  of its lines; `_step_size` will step a variant from an unrelated issued product.

- evidence: `CANDIDATE FILES — crooks-assistant/app/families/order_create.py, `ORDER_FOR_NEW_ORDER_QUERY`, `_fill_opened`, `_step_size``
- required repair: Check that the starting variant belongs to the named source order before stepping it. Page the
  source lines or refuse an incomplete read, and ask which line is meant when the request
  remains ambiguous.

### S2Bb — orders by voice — the Shopify tools, the client, and the batch/branch routes

6 path(s) · 3 material finding(s): **0 BLOCKS**, 3 FOLLOW-UP, 0 settled as not a defect.

**`S2Bb-01` — FOLLOW-UP**

FOLLOW-UP — With only George admitted, this is a false-uniqueness defect, with no demonstrated
  exploit, data loss or leak under the configured deployment. `_find_by_evidence` checks only the
  first 25 orders per search but sets `one` from those matches even when Shopify reports another
  page; for a name-only search it also gives no coverage warning. An older matching order can
  therefore be omitted while the result calls the remaining order a clear answer.

- evidence: `CANDIDATE FILES: crooks-assistant/app/tools/shopify_tools.py (`ORDER_EVIDENCE_QUERY`, `_find_by_evidence`)`
- required repair: Paginate sufficiently to establish uniqueness, or mark the result incomplete and never set `one`
  or infer a unique customer when any relevant order page remains unread.

**`S2Bb-02` — FOLLOW-UP**

FOLLOW-UP — On the configured owner-only deployment, this can mislead item selection, but the
  supplied code does not establish an exploit, data loss or leak. `catalogue_candidates` reads at
  most ten products and 50 variants per product, ignores pagination, and stops searching after its
  first nonempty candidate set; `shopify_variant_search` nevertheless sets `confident` when that set
  contains one variant. Other matching variants may not have been examined.

- evidence: `CANDIDATE FILES: crooks-assistant/app/tools/shopify_tools.py (`VARIANT_SEARCH_QUERY`, `catalogue_candidates`, `shopify_variant_search`)`
- required repair: Carry product and variant pagination or incompleteness through candidate resolution; set
  `confident` only when the search has established that exactly one variant matches.

**`S2Bb-03` — FOLLOW-UP**

FOLLOW-UP — With only George able to call these routes, this is broken branch lifecycle behavior,
  not a demonstrated exploit, data loss or leak. `/merge` permits merging the sole focused live
  branch, leaving no live branch and keeping the merged one focused. Separately, `/background` can
  change a merged or cancelled branch back to `BACKGROUND`, after which `/focus` can activate it
  despite the new closed-branch check.

- evidence: `CANDIDATE FILES: crooks-assistant/app/routes/branches.py (`background`, `merge`, `focus`)`
- required repair: Require an appropriate live branch status on merge and background; refuse merging the sole live
  branch, and prevent any route from reviving a merged or cancelled branch.

### S2BT — the order-by-voice tests

3 path(s) · 2 material finding(s): **0 BLOCKS**, 0 FOLLOW-UP, 2 settled as not a defect.

**`S2BT-01` — NOT A DEFECT**  
_settled by follow-up: no defect_

BLOCKS — A full-priced draft missing its ordered items could lose order data, and the missing
  implementation prevents ruling that out for production with writes enabled. CANNOT TELL: the fake
  store can drop every draft line while retaining the full total, but no test enables that case; the
  assertion comparing proposal line values does not by itself establish that the draft matches the
  owner's intended items.

- evidence: `crooks-assistant/tests/test_order_create.py:84,185-225,514-543; packet CONTRACT ONLY: app/families/order_create.py`
- required repair: Supply app/families/order_create.py and any existing regression in tests/test_r12_orders.py.
  Exercise OrderStore.drop_lines=True and establish that preparation refuses a draft missing
  intended lines before offering a hold card; repair the family check if it does not.

**`S2BT-02` — NOT A DEFECT**  
_settled by follow-up: no defect_

BLOCKS — A second completion of one finished workspace could corrupt order and inventory data, and
  the missing write-path bodies prevent ruling it out in production. CANNOT TELL: the tests check
  reuse before completion and replay of the same proposal after completion, but not a fresh Prepare
  or Build on that workspace after its order was verified.

- evidence: `crooks-assistant/tests/test_order_create.py:574-585,625-645; packet CONTRACT ONLY: app/families/order_create.py`
- required repair: Supply app/families/order_create.py and app/actions/engine.py, plus tests/test_r12_orders.py if
  it covers this case. Add or identify an assertion that a verified workspace refuses a fresh
  Build and Prepare without creating another draft or completing another order; fix that guard
  if absent.

### S3 — the screens, server side

10 path(s) · 3 material finding(s): **3 BLOCKS**, 0 FOLLOW-UP, 0 settled as not a defect.

**`S3-01` — BLOCKS**

BLOCKS — This can leak an order’s customer details to a different screen on production. A hold
  validates the requested screen ID, but dispatches `screen_show` using only its name; if that
  screen is forgotten and a replacement is approved under the same name before the tool resolves it,
  the order goes to the replacement while the response reports the original ID.

- evidence: `CANDIDATE FILES — app/displays/put.py:_put; app/tools/display_tools.py:screen_show`
- required repair: Bind the drop to the requested screen ID through the tool and store operation, and refuse it if
  that ID is no longer the approved target.

**`S3-02` — BLOCKS**

BLOCKS — This can lose packing progress that the owner was told was saved if the host restarts after
  a directory-sync failure. For a non-deletion such as a remote tick, `_write` raises `NotFlushed`,
  but `_commit` returns success despite the new file not being confirmed durable; `remote_tick` then
  returns a successful response.

- evidence: `CANDIDATE FILES — app/displays/store.py:DisplayStore._write and DisplayStore._commit; app/routes/displays.py:remote_tick`
- required repair: Do not acknowledge a mutating screen-record write as successful until it is durable; return a
  retryable failure for an unconfirmed tick or approval, with retry behavior that cannot apply
  the action twice.

**`S3-03` — BLOCKS**  
_still not settled after the one follow-up -> BLOCKS_

BLOCKS — Whether the new hold route can be exploited or leak data on production cannot be settled
  without the missing authority code. `put_held` calls `dispatch` without passing its request, while
  `screen_show` requires current OWNER authority; the supplied files do not establish how that
  authority is granted or constrained for this route. CANNOT TELL.

- evidence: `CANDIDATE FILES — app/displays/put.py:_put; app/tools/display_tools.py:_owners_own; app/routes/displays.py:show_held`
- required repair: Supply app/routes/actions.py, app/tools/dispatch.py, and app/tools/authority.py so the admitted-
  request-to-dispatch authority path can be verified; if it does not bind this route to the
  requesting owner, add that binding before dispatch.

### S3P — the screens, the pages

6 path(s) · 1 material finding(s): **1 BLOCKS**, 0 FOLLOW-UP, 0 settled as not a defect.

**`S3P-NEW-01` — BLOCKS**  
_settled by follow-up: defect, BLOCKS_

BLOCKS — This can leak data by putting a removed private pane back on the owner's remote. In
  remote.js, a GET started before a successful screen-off action can finish afterward: sync()
  accepts its older panes because the action does not advance R.gen, overwriting the cleared view
  rendered by act(). The old pane remains eligible for display until another poll. CANNOT TELL from
  the supplied files whether /remote/off returns panes for act() to render immediately; the response
  body in app/routes/displays.py is needed to settle that part of the sequence.

- evidence: `CANDIDATE FILES — crooks-assistant/web/remote.js, sync(), act(), and render(); sibling contract — crooks-assistant/app/routes/displays.py:remote_off()`
- required repair: Supply app/routes/displays.py to establish the action response shape. Fence remote GET and
  action responses by request generation or screen version so a response begun before a newer
  removal cannot restore its panes; test the delayed-GET/POST-off ordering.

### S3T1 — the screens' server tests

5 path(s) · 1 material finding(s): **1 BLOCKS**, 0 FOLLOW-UP, 0 settled as not a defect.

**`S3T1-01` — BLOCKS**  
_still not settled after the one follow-up -> BLOCKS_

BLOCKS — An unverified session-and-record check on the new hold-to-screen route could leak an order
  or objective to the wrong screen in production as configured. CANNOT TELL whether POST
  /displays/{id}/show checks that the supplied session and reference belong together and that the
  target screen is approved: the tests exercise this route only for refused callers, not for an
  admitted owner supplying an unrelated session or record. The bodies needed to settle this are
  crooks-assistant/app/routes/displays.py, crooks-assistant/app/tools/dispatch.py, and crooks-
  assistant/app/tools/gate.py.

- evidence: `CANDIDATE FILES: crooks-assistant/tests/test_screen_paths.py, _every_screen_route and test_a_refused_caller_reaches_no_screen_route_and_no_screen_tool`
- required repair: Supply the named route, dispatcher, and gate bodies for review. Add route-level tests for an
  admitted owner showing an issued record and for refusal of an unissued or wrong-session
  reference and a pending screen, asserting that no slip is sent or put up on refusal.

### S3T2 — the screens' page tests and screen privacy

4 path(s) · 1 material finding(s): **0 BLOCKS**, 0 FOLLOW-UP, 1 settled as not a defect.

**`S3T2-01` — NOT A DEFECT**  
_settled by follow-up: no defect_

BLOCKS — CANNOT TELL whether a refusal during a round-12 screen replacement leaves customer details
  in the real dots canvas, which could leak data on a production TV. The mid-change refusal test
  checks DOM text and a stand-in dots engine, not frames from the real engine; the bodies of crooks-
  assistant/web/display.js and crooks-assistant/web/dots.js are needed to settle the behaviour.

- evidence: `crooks-assistant/tests/web/display.test.js: test 'a refusal in the middle of a change takes the old slip and the new one down at once, dots and all'; page() and engines() test helpers`
- required repair: Supply crooks-assistant/web/display.js and crooks-assistant/web/dots.js for review of the
  refusal and canvas-clearing paths. Add a frame-by-frame mid-replacement refusal test using the
  real dots engine; repair either path if customer pixels survive.

### S4 — live voice and the words on the page

9 path(s) · 2 material finding(s): **0 BLOCKS**, 2 FOLLOW-UP, 0 settled as not a defect.

**`S4-N01` — FOLLOW-UP**

FOLLOW-UP — This is not exploitable and does not lose authoritative data or leak data tonight,
  because the batch recording still supplies the question. On a first hold, live voice starts
  recording while `openTap()` awaits worklet loading; speech during that delay never reaches the
  live transcriber, so the displayed words can omit the beginning of the question.

- evidence: `DIFF 6a29e310..361b0138 — web/live-voice.js, openTap() and start(); tests/web/live-voice.test.js, AudioWorklet test`
- required repair: Attach an immediately available tap before presenting the hold as listening, or buffer
  microphone audio while the worklet loads. Add a test that speaks while addModule is pending
  and checks that the initial audio reaches the socket.

**`S4-N02` — FOLLOW-UP**

FOLLOW-UP — This is not exploitable and does not lose authoritative data or leak data tonight,
  because the separate batch recording remains intact. The worklet posts only complete 1,024-frame
  buffers, but release immediately disables its message handler and stops it; buffered tail frames
  and already-posted messages awaiting delivery are discarded before the live transcript is
  committed.

- evidence: `DIFF 6a29e310..361b0138 — web/live-voice.js, WORKLET_SOURCE, openTap().quiet(), and handle.release()`
- required repair: Drain or explicitly flush and acknowledge the worklet’s remaining frames and queued messages
  before sending the final committed chunk, with a bounded wait. Test a release partway through
  a worklet buffer and a queued message at release.

### S4A — the app page itself

1 path(s) · 2 material finding(s): **0 BLOCKS**, 2 FOLLOW-UP, 0 settled as not a defect.

**`S4A-01` — FOLLOW-UP**

FOLLOW-UP — This can leave the owner unable to ask another question, but on the configured private
  deployment it does not itself enable exploitation, data loss, or data leakage. If the first turn
  starts before a branch is known, noteBranch moves its in-flight entry from `_` to the new branch
  ID; submit’s finally block deletes only `_`. syncBusy then finds the stranded entry and keeps the
  page permanently busy, blocking further holds and actions.

- evidence: `CANDIDATE FILES — crooks-assistant/web/app.js: noteBranch(), submit() and syncBusy()`
- required repair: Keep the in-flight entry’s key consistent through branch assignment and completion, or delete
  the entry by its controller in submit’s finally block. Test a first turn submitted before
  branch restoration finishes.

**`S4A-02` — FOLLOW-UP**

FOLLOW-UP — A delayed state poll can draw an earlier turn’s cards over the current turn, but this
  demonstrated fault does not itself exploit, lose, or leak data on the configured deployment.
  stopStatePolling clears the interval without invalidating a request already in flight; when that
  response arrives during a new turn, the tick checks only the global busy flag and data.known
  before passing its workspace to applyWorkspace, which can clear the current cards.

- evidence: `CANDIDATE FILES — crooks-assistant/web/app.js: startStatePolling(), stopStatePolling() and applyWorkspace()`
- required repair: Give each polling run a generation and expected branch/turn identity, discard replies after that
  run stops or focus changes, and test an old poll response arriving after the next turn starts.

### S5 — records, observability and shutdown

13 path(s) · 4 material finding(s): **1 BLOCKS**, 3 FOLLOW-UP, 0 settled as not a defect.

**`S5-01` — BLOCKS**

BLOCKS — A failed install can lose the existing unit-file data on production. `install()` reads the
  old unit, then overwrites it with `Path.write_text()` outside the rollback-protected steps; a
  partial write or write error can leave the old unit truncated and exit without restoring it.

- evidence: `crooks-assistant/scripts/install_systemd.py:install (Before.read and target.write_text)`
- required repair: Write the replacement unit to a temporary file, flush it, and atomically replace the target;
  handle write and permission errors by preserving or restoring the previous unit before
  returning failure. Test a partial-write failure against an existing unit.

**`S5-02` — FOLLOW-UP**

FOLLOW-UP — This read-only scheduling defect does not itself exploit, lose data, or leak data under
  the configured owner-only access. A read with `after=("missing",)` runs anyway: `_layers()`
  ignores dependencies absent from `by_name`, and the runnable check does the same, contrary to the
  scheduler's stated guarantee that a missing dependency is skipped.

- evidence: `crooks-assistant/app/reads/scheduler.py:_layers and run_plan runnable check`
- required repair: Treat an unknown dependency as a skipped read, propagate that skip to dependants, and add a plan
  test with an absent dependency that asserts its tool is never dispatched.

**`S5-03` — FOLLOW-UP**

FOLLOW-UP — Retained anticipation state is an availability and accounting defect, not an exploit,
  data loss, or data leak under this configuration. `on_signal()` stores positions under
  `scope|branch_id`, but `forget(scope)` removes only `scope`; ended conversations therefore retain
  their positions indefinitely and can contribute a false transition if reused.

- evidence: `crooks-assistant/app/anticipation/engine.py:on_signal (`where`) and forget`
- required repair: Remove every `_last` entry for the forgotten scope and its branches; test that forgetting a two-
  branch conversation clears both positions before another signal.

**`S5-04` — FOLLOW-UP**

FOLLOW-UP — Misreporting filing readiness causes owner friction, but none of exploitation, data
  loss, or data leakage in production as configured. With `CROOKS_ENGINEERING_HOST` unset, `build()`
  binds the disabled engineering inbox, while `write_status()` still returns `ready` for every
  registered GitHub operation.

- evidence: `crooks-assistant/app/runtime.py:build (engineering_switch.inbox_for) and Runtime.write_status`
- required repair: Make the GitHub-operation status reflect the configured filing switch before reporting it ready,
  and test the unset-host production case.

### S6 — objectives with a shape: the records, their cards and their tools

4 path(s) · 5 material finding(s): **4 BLOCKS**, 1 FOLLOW-UP, 0 settled as not a defect.

**`S6-01` — BLOCKS**

BLOCKS — A power loss can lose objective design data on production. The three-step write replaces
  the pending design and record without flushing either file or their directories; the new record
  can survive while its pending design does not, leaving the older, still-agreeing design to be
  loaded instead.

- evidence: `crooks-assistant/app/objectives/store.py:ObjectiveStore._atomic, ObjectiveStore._write, ObjectiveStore._design_for`
- required repair: Make each step durable in order by flushing the temporary file and its directory before
  advancing, and test recovery when power is lost after the record replacement.

**`S6-02` — BLOCKS**

BLOCKS — This can lose tasks and people the owner asked to record. Creation silently takes only the
  first 60 tasks and `_people` silently takes only the first 12 people, while the objective-open
  schema sets no corresponding input limits or reports omissions.

- evidence: `crooks-assistant/app/objectives/store.py:ObjectiveStore.create, ObjectiveStore._people; crooks-assistant/app/objectives/tools.py:objective_open input_schema`
- required repair: Reject over-limit requests without creating an objective, or explicitly obtain the owner's
  agreement to omit entries; enforce the limits at the tool boundary too.

**`S6-03` — BLOCKS**

BLOCKS — An existing task's newly supplied due date can be lost. `_add_task` returns an open task
  with the same person and text without applying or rejecting a different `due`; `task` then records
  a successful event despite keeping the old date.

- evidence: `crooks-assistant/app/objectives/store.py:ObjectiveStore._add_task, ObjectiveStore.task`
- required repair: When a matching task has a different supplied date, update that task and record the change, or
  refuse the ambiguous addition instead of reporting it as recorded.

**`S6-04` — BLOCKS**

BLOCKS — Reordering stages can subsequently lose recorded completion state and timestamps. `_stages`
  keeps each stage's old state in its new position without restoring the done/current/upcoming
  ordering; a later `move_stage('next')` operates by position, potentially marking an upcoming stage
  done and clearing a previously completed stage's `done_at`.

- evidence: `crooks-assistant/app/objectives/store.py:ObjectiveStore._stages, ObjectiveStore._stage_index, ObjectiveStore._move`
- required repair: Reject a reorder that makes the progression inconsistent, or reconcile stage state by stage
  identity before allowing positional moves; test a reorder across the current stage followed by
  `next`.

**`S6-05` — FOLLOW-UP**

FOLLOW-UP — This refusal neither exploits the configured service nor loses or leaks data. The
  owner's create route accepts `kind='project'` or `kind='tasks'` but has no fields for their
  required stages or tasks, so both advertised kinds always fail creation through that route.

- evidence: `crooks-assistant/app/routes/objectives.py:CreateBody, create_objective; crooks-assistant/app/objectives/store.py:ObjectiveStore.create`
- required repair: Add validated stages and tasks to the create-route body and pass them to the store, or do not
  offer those kinds on that route.

### AC1 — the rest of the application, part 1 of 2

5 path(s) · 2 material finding(s): **0 BLOCKS**, 1 FOLLOW-UP, 1 settled as not a defect.

**`AC1-NEW-01` — FOLLOW-UP**

FOLLOW-UP — This produces an incorrect working set, but the read-only path shown does not itself
  establish exploitation, data loss, or data leakage in production. `inventory_query` applies
  `max_days_cover` after `_run` has created and attached the working set, so the returned rows
  exclude variants that remain in the set referred to as “these.”

- evidence: `CANDIDATE FILES — crooks-assistant/app/tools/analytics_tools.py, `_run`, `_set_from`, and `inventory_query``
- required repair: Apply the cover filter before creating the working set, and make its members, labels, and totals
  reflect the filtered variants; test that every set member satisfies the requested bound.

**`AC1-NEW-02` — NOT A DEFECT**  
_settled by follow-up: no defect_

BLOCKS — Without the missing authorization code, I cannot rule out a data leak through redisplayed
  order, customer, or email records on production as configured. CANNOT TELL whether `show_again`
  restricts `_reads` and `_surfaces` to records shown to this conversation: `present()` accepts
  those surfaces and treats each supplied read as a successful tool call, but
  app/tools/show_again.py was not provided.

- evidence: `CANDIDATE FILES — crooks-assistant/app/presentation.py, `_with_redraws` and `_from_result` (`AGAIN_TOOL`)`
- required repair: Provide app/tools/show_again.py at this exact SHA and evidence that it validates conversation-
  specific authority for every returned read and surface; add that validation if absent.

### AC2 — the rest of the application, part 2 of 2

29 path(s) · 2 material finding(s): **0 BLOCKS**, 2 FOLLOW-UP, 0 settled as not a defect.

**`AC2-01` — FOLLOW-UP**

FOLLOW-UP — This leaves screen information stale, but the code shown does not establish an exploit,
  data loss, or data leak in tonight’s configuration. RenderLedger compares only `data` and selected
  visual keys, so changing a card’s visible `title` or `subtitle`, links, or freshness while keeping
  `data` unchanged produces no patch.

- evidence: `CANDIDATE FILES — app/render.py: fingerprint, visual_print, RenderLedger.stage; app/surfaces.py: Surface.as_ui`
- required repair: Include screen-visible envelope fields in patch comparison and emit a patch when they change;
  test a same-data card whose subtitle and freshness change.

**`AC2-02` — FOLLOW-UP**

FOLLOW-UP — Duplicate cards are a screen defect, with no exploit, data loss, or data leak
  established for tonight’s configuration. An order keyed by `order_id` and the same order keyed
  only by `order_number` receive different render IDs, despite the stated same-card contract.

- evidence: `CANDIDATE FILES — app/render.py: KEY_OF, key_of, render_id`
- required repair: Give both representations of an order one canonical render identity, or reconcile their
  identities before staging; test successive renders with a GID and then only the same order
  number.

### ASSET — the binary assets (screenshots) — listed, not sent as text

15 path(s) · 1 material finding(s): **0 BLOCKS**, 1 FOLLOW-UP, 0 settled as not a defect.

**`ASSET-01` — FOLLOW-UP**  
_settled by the deploy owner: all 15 images read; no customer data, no credential; private repo_

BLOCKS — The unseen screenshots could leak data if any contains customer information or a
  credential, so leakage cannot be ruled out. CANNOT TELL whether the 15 committed PNGs are safe:
  their bytes were not supplied, and the deploy owner's report covers only three representative
  images.

- evidence: `Review packet: “THESE PATHS ARE BINARY IMAGES” and “THE DEPLOY OWNER'S OWN INSPECTION OF THESE 15 IMAGES”`
- required repair: Provide the image contents for independent inspection of every listed PNG:
  docs/screens/r12-objectives/phone-10-home.png, phone-11-project-sheet.png, phone-12-tasks-
  sheet.png, phone-13-older-objective-sheet.png, phone-20-project-card.png, phone-21-tasks-
  card.png, tablet-01-project-card.png, tablet-02-tasks-card.png, tablet-03-task-ticked.png,
  tablet-04-project-moved-on.png, tablet-05-home.png, tablet-10-home.png, tablet-11-project-
  sheet.png, tablet-12-tasks-sheet.png, and tablet-13-older-objective-sheet.png. Remove or
  redact any sensitive content found before committing the images.

### CFG — settings, the unit template and the deploy documents

5 path(s) · 0 material finding(s): **0 BLOCKS**, 0 FOLLOW-UP, 0 settled as not a defect.

### DOC1 — the documents, part 1 of 2

7 path(s) · 2 material finding(s): **0 BLOCKS**, 2 FOLLOW-UP, 0 settled as not a defect.

**`DOC1-01` — FOLLOW-UP**

FOLLOW-UP — On production as configured, this inaccurate access guidance does not itself permit
  exploitation, lose data, or leak data. The active README says requests made on the host are always
  allowed, while the stated production configuration leaves local-owner access off and the evidence
  index says direct server requests are refused.

- evidence: `crooks-assistant/README.md, “Who may ask”; crooks-assistant/docs/product-memory/CURRENT_TRUTH.md, “Production switches”; crooks-assistant/docs/review/evidence/door.json, R9-A2-F-NEW-TOOLS-PATH`
- required repair: Update the README’s current access guidance to distinguish the Linux production rules from the
  Mac instructions: state that direct local requests are not owner requests with local-owner
  access off, and describe the verified Tailscale owner allow-list and restricted local command
  key.

**`DOC1-02` — FOLLOW-UP**

FOLLOW-UP — On production as configured, this documentation omission does not itself permit
  exploitation, lose data, or leak data. The README presents its change-action list as the
  assistant’s available proposals but omits the newly documented voice order-creation workflow,
  despite writes being enabled in production.

- evidence: `crooks-assistant/README.md, “Changes to the store and the inbox”; crooks-assistant/docs/product-memory/CURRENT_TRUTH.md, “Round 12, the owner’s list of 29 September”; review packet, production switches`
- required repair: Bring the README’s active change-action list and count up to date with voice order creation.
  Document its owner gesture and verification using the implemented workflow rather than
  inferring those details from the claim sheet.

### DOC2 — the documents, part 2 of 2

9 path(s) · 2 material finding(s): **0 BLOCKS**, 2 FOLLOW-UP, 0 settled as not a defect.

**`DOC2-01` — FOLLOW-UP**

FOLLOW-UP — This documentation error cannot itself be exploited or lose or leak data on tonight’s
  deployment. The Linux deploy guide says writes to the store and inbox stay off as a safeguard for
  running the service as root, but production is configured with writes enabled.

- evidence: `CANDIDATE FILES — docs/DEPLOY_LINUX.md, “Running as root — temporary”; REVIEW PACKET — George’s ship rule`
- required repair: Update the root-risk explanation to state that production writes are enabled; distinguish any
  switches that remain off instead of presenting disabled writes as a safeguard.

**`DOC2-02` — FOLLOW-UP**

FOLLOW-UP — The inaccurate audit description cannot itself be exploited or lose or leak data on
  tonight’s deployment. The tool matrix classifies screen_show and screen_off as reads and says
  reads never mutate, although those tools change what is displayed; a reader could mistake the
  audit’s read classification for a guarantee of no state change.

- evidence: `CANDIDATE FILES — docs/phase4/TOOL_MATRIX.md, “Tools” and “The rules the audit itself keeps”; REVIEW PACKET — PR #52 claim sheet, “The TV remote”`
- required repair: State explicitly that the matrix’s read classification concerns the write-spec/read-scheduler
  boundary, not all state changes, and identify screen tools that change display state.

### F — the families

13 path(s) · 4 material finding(s): **1 BLOCKS**, 3 FOLLOW-UP, 0 settled as not a defect.

**`F-01` — BLOCKS**

BLOCKS — With writes enabled, correcting one part of an order address can lose data from another
  part of that address. `_from_order` silently truncates the existing recipient, street, town and
  codes; `_open` treats those shortened values as the original address, and `_stage` submits every
  field, including fields the owner did not edit. An existing street longer than 120 characters can
  therefore be shortened when the owner only corrects its postcode.

- evidence: `CANDIDATE FILES — crooks-assistant/app/families/address.py: _from_order, _open, _stage`
- required repair: Preserve the full existing address when opening the workspace. Refuse or explicitly resolve any
  overlong field before staging; never submit a silently shortened value for an unedited field.

**`F-02` — FOLLOW-UP**

FOLLOW-UP — These bounded reads do not delete, leak or expose data to another caller, but they can
  give the owner a false operational answer. The Orders landing searches only `last_30_days` yet can
  say “Nothing is waiting to go out”; `commerce_summary` likewise searches a 90-day lookback for an
  unqualified `orders_attention` request. Older unfulfilled orders can be absent from both answers.

- evidence: `CANDIDATE FILES — crooks-assistant/app/families/landings.py: _orders_plan, _orders_render; crooks-assistant/app/families/summaries.py: LOOKBACK_DAYS, commerce_summary`
- required repair: Read the full outstanding-order scope for unqualified requests, or make both results and their
  spoken or displayed claims explicitly conditional on their lookback windows.

**`F-03` — FOLLOW-UP**

FOLLOW-UP — This can mislead the owner about the inbox, but does not itself exploit the configured
  service, lose data or leak it. The recent-inbox search requests at most 12 threads;
  `_recent_render` can nevertheless say “Nothing from a person in the inbox this week” when those 12
  are bulk mail and a person's thread is farther back. Its empty branch also drops `result.partial`.

- evidence: `CANDIDATE FILES — crooks-assistant/app/families/landings.py: _inbox_plan, _recent_render`
- required repair: Check whether the search covered the claimed week before asserting that nobody wrote; paginate
  sufficiently or state the narrower checked scope, and propagate partial-read status on the
  empty branch.

**`F-04` — FOLLOW-UP**

FOLLOW-UP — The resulting ranking can be wrong, but this read does not itself exploit the configured
  service, lose data or leak it. Each abandoned checkout fetches only its first 20 line items, while
  `rank` and `cards` can present the resulting item ranking as complete. An item consistently in
  position 21 is never counted.

- evidence: `CANDIDATE FILES — crooks-assistant/app/families/abandoned.py: ABANDONED_QUERY, _lines, rank, cards`
- required repair: Paginate each checkout's line items before claiming a complete ranking, or carry a separate
  item-ranking completeness flag and visibly qualify rankings built from truncated checkouts.

### O1 — observability, part 1 of 2

3 path(s) · 2 material finding(s): **1 BLOCKS**, 1 FOLLOW-UP, 0 settled as not a defect.

**`O1-01` — BLOCKS**  
_settled by follow-up: defect, BLOCKS_

BLOCKS — This can lose already-written production timeline data if two writers append to the same
  session, and I cannot rule out that condition from the files supplied. Writers hold shared locks,
  so if one has a partial write, another appends a complete event, and the first then calls
  `_take_back`, truncation from the file’s current end removes the second writer’s bytes even though
  it counted that event as written. CANNOT TELL whether production session isolation prevents this
  interleaving without `crooks-assistant/app/observability/session.py` and `crooks-
  assistant/app/main.py`.

- evidence: `crooks-assistant/app/observability/timeline.py:234-244, 470-493, 558-573`
- required repair: Supply the named session and startup files to establish whether writers can share a timeline
  path. If they can, serialize append and partial-write recovery exclusively per file, and test
  an interleaved short write so recovery cannot truncate another writer’s event.

**`O1-02` — FOLLOW-UP**

FOLLOW-UP — This misdiagnoses a screen event but does not itself permit exploitation, lose data, or
  leak data on the configured host. `_whole` converts malformed page counts to zero, so a composer
  field reporting a nonnumeric `chars` value after a valid positive count is classified as having
  lost its contents; malformed scroll depths can likewise be treated as a return to the top.

- evidence: `crooks-assistant/app/observability/visible.py:1151-1170, 1173-1225`
- required repair: Represent malformed counts as unknown, and emit `FOCUS_LOST` only when both the prior and
  current measurements needed for that inference are valid; add malformed-field and malformed-
  scroll cases.

### O2 — observability, part 2 of 2

8 path(s) · 3 material finding(s): **2 BLOCKS**, 1 FOLLOW-UP, 0 settled as not a defect.

**`O2-N-01` — BLOCKS**

BLOCKS — This would lose data on production with always-on test sessions: a manually named session
  whose slug contains `-always-on` is given the short automatic-session retention period.
  `TestSessions._prune` classifies by substring rather than by the session's actual name, so, for
  example, `review-always-on` can be deleted after 14 days instead of the configured 90-day named-
  session period.

- evidence: `crooks-assistant/app/observability/session.py:TestSessions._prune`
- required repair: Identify automatic sessions exactly, rather than searching for `-always-on` anywhere in a
  filename; test retention of a named `review-always-on` session and its screens.

**`O2-N-02` — BLOCKS**

BLOCKS — This can lose data: `_tidy_reports` follows a symlink at the configured reports path and
  prunes its target before `tighten` detects and reports the link. An aged `ts-*` file in that
  target can therefore be deleted despite the subsequent privacy refusal.

- evidence: `crooks-assistant/app/observability/session.py:TestSessions._tidy_reports; session.py:prune_reports; session.py:tighten`
- required repair: Reject a symlinked reports root before either pruning pass, and test that a reports-root symlink
  leaves aged files in its target untouched.

**`O2-N-03` — FOLLOW-UP**  
_settled by follow-up: defect, FOLLOW-UP_

FOLLOW-UP — This is an incorrect screen claim with no demonstrated exploit, data loss or leak:
  `claims_on_screen` does not recognise a present-tense assertion such as “Order #1938 is open in
  the app now.” The on-screen claim helper therefore cannot flag that wording when nothing was
  drawn. CANNOT TELL whether another route-side check catches it without `crooks-
  assistant/app/routes/turn.py`.

- evidence: `crooks-assistant/app/observability/claims.py:ON_SCREEN_RE; claims.py:claims_on_screen`
- required repair: Cover unambiguous present-tense claims using “in the app” in the claim detector, with positive
  and non-claim tests; supply `crooks-assistant/app/routes/turn.py` to establish the route-side
  outcome.

### SC1 — the remaining scripts, part 1 of 2

12 path(s) · 2 material finding(s): **0 BLOCKS**, 2 FOLLOW-UP, 0 settled as not a defect.

**`SC1-01` — FOLLOW-UP**

FOLLOW-UP — An inaccurate browser-gate result does not itself enable exploitation, data loss, or
  data leakage in tonight’s configuration. The TV-flow script leaves `report.ok` true when page
  errors occur or a new view never becomes readable: it records the errors and null `ready_ms`
  values but marks the run failed only if an exception is thrown.

- evidence: `crooks-assistant/scripts/browser/tv_flow.js:main; crooks-assistant/scripts/browser/tv_flow.js:walkMode`
- required repair: Make the reported verdict fail for page errors and any step without a readable result; enforce
  the claimed flow limits rather than merely recording their measurements.

**`SC1-02` — FOLLOW-UP**

FOLLOW-UP — A misleading verbose diagnostic does not itself enable exploitation, data loss, or data
  leakage in tonight’s configuration. `Watch.lines` removes both `claim` and `drew` because they are
  absent from `SAFE`, so the new `on_screen` branch is unreachable and an unsupported screen claim
  is instead described as a capability claim.

- evidence: `crooks-assistant/scripts/watch.py:SAFE; crooks-assistant/scripts/watch.py:Watch.lines; crooks-assistant/scripts/watch.py:434-439`
- required repair: Retain the controlled `claim` value through the allow-list and validate `drew` before printing
  it; add a test that passes an `on_screen` event through `Watch.lines`.

### SC2 — the remaining scripts, part 2 of 2

7 path(s) · 3 material finding(s): **0 BLOCKS**, 2 FOLLOW-UP, 1 settled as not a defect.

**`SC2-01` — NOT A DEFECT**  
_settled by follow-up: no defect_

BLOCKS — Whether the advertised read-only live run could lose production shop or inbox data cannot
  be settled from the supplied files. CANNOT TELL: `experience.py` runs scenarios with
  `harness(live=True, admitted=True)` but contains no write prohibition, while production writes are
  enabled; the answer depends on `crooks-assistant/experience/harness.py`, `crooks-
  assistant/experience/live.py`, and `crooks-assistant/experience/scenarios.py`.

- evidence: `CANDIDATE FILES: crooks-assistant/scripts/experience.py (run and --live option)`
- required repair: Supply the three named files to establish that every live scenario is prevented from executing
  writes; if they do not establish that, add and test an enforced live-mode write guard.

**`SC2-02` — FOLLOW-UP**

FOLLOW-UP — With live transcription disabled on configured production, this defect does not enable
  exploitation, data loss, or data leakage tonight. `open_once` calls a transport error a refusal,
  and `check` treats a refusal on the second connection or expiry attempt as proof that the token is
  single-use or expired; a network failure can therefore yield a false passing verdict.

- evidence: `CANDIDATE FILES: crooks-assistant/scripts/live_key_check.py (open_once and check)`
- required repair: Distinguish an explicit token/authentication refusal from connection, timeout, and service
  failures; return NOT ASKED (exit 2) for inconclusive attempts and test those cases.

**`SC2-03` — FOLLOW-UP**

FOLLOW-UP — No coexistence of the two secret tiers or resulting exploitation, data loss, or data
  leakage on configured production is established. A key can be stored with `--plain` while its
  encrypted credential remains, but `remove_one` deletes the encrypted credential and returns
  without deleting the writable copy, so `--remove` does not necessarily remove the secret.

- evidence: `CANDIDATE FILES: crooks-assistant/scripts/provision_secrets.py (store_one and remove_one)`
- required repair: Make removal clear both tiers for the named key, with a test that stores both copies and
  confirms neither remains after `--remove`.

### T1 — the remaining tests, part 1 of 7

4 path(s) · 4 material finding(s): **2 BLOCKS**, 2 FOLLOW-UP, 0 settled as not a defect.

**`T1-01` — BLOCKS**  
_still not settled after the one follow-up -> BLOCKS_

BLOCKS — CANNOT TELL whether editing an order after Prepare invalidates its old hold card, so a
  write on production could create an order with stale lines or delivery details; the missing files
  are app/families/order_create.py, app/routes/actions.py and app/actions/engine.py. The supplied
  tests change a Shopify draft after Prepare or prepare a different order, but do not edit the
  prepared workspace and attempt to commit its old proposal.

- evidence: `CANDIDATE FILES: tests/test_r12_orders.py, test_a2_a_draft_changed_after_it_was_offered and test_h_prepare_keeps_the_order_being_built_on_the_glass`
- required repair: Supply the named files for review and add a route-level regression that prepares an order, edits
  that same workspace by voice and by tap, then proves the old proposal cannot complete a draft.

**`T1-02` — BLOCKS**  
_settled by follow-up: defect, BLOCKS_

BLOCKS — CANNOT TELL whether production search handles orders beyond its first result page before
  declaring a match unique or absent, which could misdirect a subsequent order write; the missing
  file is app/tools/shopify_tools.py. The fake shop truncates results to the requested count while
  always reporting that no next page exists, so these tests cannot exercise that boundary.

- evidence: `CANDIDATE FILES: tests/test_r12_orders.py, Counter.graphql CrooksOrderEvidence branch and Counter._orders`
- required repair: Supply app/tools/shopify_tools.py for review and make the fake return truthful page information;
  test a matching order beyond the first page and an incomplete search that must not claim a
  unique or exhaustive result.

**`T1-03` — FOLLOW-UP**

FOLLOW-UP — This test-fixture defect does not itself exploit, lose or leak production data. The
  order dated 30 days before 29 September is generated as `2026-09--1T10:00:00Z`, an invalid
  timestamp, so the search tests use an unrealistic Shopify order without checking that its date is
  usable.

- evidence: `CANDIDATE FILES: tests/test_r12_orders.py, ORDERS entry 2102 and order_node createdAt/processedAt`
- required repair: Generate fixture dates with datetime subtraction across month boundaries and assert that order
  2102 receives a valid August timestamp.

**`T1-04` — FOLLOW-UP**

FOLLOW-UP — This assertion gap does not itself exploit, lose or leak data on production as
  configured. The limited-health helper accepts a response with no housekeeping check: its key-set
  assertion allows omission, and its default value makes the subsequent shape assertion pass.

- evidence: `CANDIDATE FILES: tests/test_pad.py, _limited_to_liveness`
- required repair: Require `housekeeping` to be present in the limited checks and assert the shape of the actual
  returned housekeeping value, including a failing-check case.

### T2 — the remaining tests, part 2 of 7

6 path(s) · 3 material finding(s): **0 BLOCKS**, 3 FOLLOW-UP, 0 settled as not a defect.

**`F-01` — FOLLOW-UP**

FOLLOW-UP — This test-isolation defect does not itself let configured production be exploited, lose
  data, or leak data. The on-screen-claim test replaces the process timeline and unconditionally
  leaves a NullTimeline installed, rather than restoring the timeline it displaced; later tests can
  therefore run without the observability state they expect.

- evidence: `tests/test_r12_surfaces.py:test_the_claim_is_written_to_the_timeline_beside_the_decline_claims; tests/test_observability.py:test_the_null_timeline_is_silent_and_the_process_default`
- required repair: Save the previous timeline before installing the test timeline, then restore that exact timeline
  in the finally block after stopping the test writer.

**`F-02` — FOLLOW-UP**

FOLLOW-UP — This assertion defect does not establish an exploit, data loss, or data leak on
  configured production. The malformed video-report test disables server-exception propagation and
  accepts any status of 400 or higher, so an HTTP 500 passes its stated rejection check.

- evidence: `tests/test_r11_screens_server.py:test_a_screens_word_on_its_video_is_a_state_numbers_and_true_or_false_and_nothing_else`
- required repair: Require the intended client-error status for each NaN and infinity case, and retain the
  assertion that rejected reports do not change playback state.

**`F-03` — FOLLOW-UP**

FOLLOW-UP — The missing assertions do not by themselves demonstrate that configured production can
  be exploited, lose data, or leak data. The test claiming an unissued-order note was refused checks
  only that the existing order remains visible; it would also pass if a note for order 9999 were
  staged, or if no refusal reason were given.

- evidence: `tests/test_r12_surfaces.py:test_a_change_that_could_not_be_prepared_keeps_the_record_and_says_why`
- required repair: Assert the note tool call was refused, no proposal or shop mutation was made, and the response
  gives the owner a refusal reason.

### T3 — the remaining tests, part 3 of 7

8 path(s) · 2 material finding(s): **2 BLOCKS**, 0 FOLLOW-UP, 0 settled as not a defect.

**`T3-01` — BLOCKS**  
_still not settled after the one follow-up -> BLOCKS_

BLOCKS — On writes-enabled production, applying a stale store-credit hold could duplicate a money-
  moving credit, and the missing write-path files prevent ruling out that loss. CANNOT TELL whether
  the independent stale-card check demonstrated for orders also protects credits and discount codes:
  their tests check withdrawal after a normal field edit, but do not change workspace state without
  withdrawal and then attempt a commit.

- evidence: `CANDIDATE FILES — tests/test_r12_made_once.py, tests test_2_a_hold_card_whose_card_moved_is_never_applied_whatever_the_path and test_2_a_credit_or_a_code_changed_after_prepare_withdraws_its_hold_card`
- required repair: Supply app/actions/engine.py, app/routes/actions.py and app/families/_workspace.py to settle the
  independent commit check; add direct stale-commit tests for both credit and code, and repair
  any path that accepts one.

**`T3-02` — BLOCKS**  
_still not settled after the one follow-up -> BLOCKS_

BLOCKS — Misclassifying an attempted order completion as safe to retry could make two orders in
  production, and the missing engine implementation prevents ruling out that data loss. CANNOT TELL
  whether the claimed never-reached-completion path is safe: the test sets reads_fail before the
  hold, so a draft precondition read can fail before the completion mutation is attempted, yet the
  test never asserts which operation failed.

- evidence: `CANDIDATE FILES — tests/test_r12_made_once.py, Shop.graphql and test_3_a_completion_that_never_left_gives_the_card_back`
- required repair: Supply app/actions/engine.py and app/routes/actions.py; make the test allow precondition reads,
  fail specifically when draft_order_complete is attempted, assert that attempt, and verify that
  only a provably unsent completion returns a retriable card.

### T4 — the remaining tests, part 4 of 7

10 path(s) · 2 material finding(s): **2 BLOCKS**, 0 FOLLOW-UP, 0 settled as not a defect.

**`T4-01` — BLOCKS**  
_still not settled after the one follow-up -> BLOCKS_

BLOCKS — An unintended Shopify write could lose data with production writes enabled, and the
  supplied files do not establish that this test detects one. CANNOT TELL whether the harness store
  has a `mutations_sent` ledger: the test compares `getattr(..., None)` before and after, so it
  passes if that ledger does not exist. The missing files are `crooks-
  assistant/experience/harness.py` and `crooks-assistant/experience/fixtures.py`.

- evidence: `CANDIDATE FILES — tests/test_objective_design.py, test_nothing_an_objective_holds_reaches_the_shop`
- required repair: Supply the named harness and fixture files. Make the test require an instrumented Shopify
  mutation ledger, then assert that opening and changing an objective leave it empty.

**`T4-02` — BLOCKS**  
_settled by follow-up: defect, BLOCKS_

BLOCKS — A failed objective-design write or incompatible rollback could lose owner records, and that
  risk cannot be settled from the supplied tests. CANNOT TELL whether the claimed three-step write
  and pre-round-12 readability hold: the old-record test exercises only a successful write and
  reload, while `crooks-assistant/app/objectives/store.py` and the `crooks-
  assistant/tests/fixtures/objectives/` JSON files were not supplied.

- evidence: `PR #56 — Objectives with a shape; CANDIDATE FILES — tests/test_objective_design.py, test_a_record_written_before_round_12_reads_exactly_as_it_did`
- required repair: Supply the named store and fixture files, plus the pre-round-12 store reader for the rollback
  claim. Add failure-injection and reload tests at each persistence step that verify existing
  records survive and damaged or disagreeing designs are set aside.

### T5 — the remaining tests, part 5 of 7

14 path(s) · 1 material finding(s): **1 BLOCKS**, 0 FOLLOW-UP, 0 settled as not a defect.

**`T5-01` — BLOCKS**  
_still not settled after the one follow-up -> BLOCKS_

BLOCKS — An owner-check bypass on the new screen-show route could leak customer order details on
  tonight’s tailnet, and the supplied files cannot rule it out. CANNOT TELL whether a drop is
  refused before reading an unissued record or changing a screen: the test asserts those outcomes
  using an imported fixture, but the route, dispatcher and fixture implementations are absent.

- evidence: `CANDIDATE FILES — crooks-assistant/tests/test_r12_put_on_screen.py, test_nobody_but_the_owner_reaches_the_drop and test_a_record_this_conversation_was_not_issued_is_refused_before_anything_is_read`
- required repair: Supply app/main.py, app/routes/displays.py, app/displays/put.py, app/tools/dispatch.py,
  app/tools/gate.py and tests/test_screen_paths.py at this exact SHA for review. If the route
  does not enforce owner and issued-record checks before reads and screen writes, repair it and
  add a route-level regression test.

### T6 — the remaining tests, part 6 of 7

19 path(s) · 2 material finding(s): **1 BLOCKS**, 1 FOLLOW-UP, 0 settled as not a defect.

**`T6-01` — BLOCKS**  
_settled by follow-up: defect, BLOCKS_

BLOCKS — CANNOT TELL whether an interrupted objective write or rollback would lose data on the
  configured host because the objective store implementation and rollback fixture were not supplied.
  The round-12 tests inject exceptions at `os.replace` calls but do not simulate a restart or check
  durable write ordering; their state comparison also discards stage and task IDs. Those tests alone
  cannot establish the claimed crash and rollback guarantees.

- evidence: `CANDIDATE FILES — crooks-assistant/tests/test_objective_design_file.py (`_break_at`, `_same`, `test_a_write_cut_short_is_still_readable_by_the_store_production_rolls_back_to`)`
- required repair: Supply crooks-assistant/app/objectives/store.py and crooks-
  assistant/tests/test_objective_rollback.py at this SHA for review; verify restart recovery,
  write durability and exact preservation of existing stage and task IDs after each interrupted
  step.

**`T6-02` — FOLLOW-UP**

FOLLOW-UP — This test-fixture defect is not shown to be exploitable or to lose or leak data in the
  production service as configured tonight. The offline fixture promises to isolate logs, secrets,
  objectives and reports, but `setdefault` preserves inherited `CROOKS_*` directory values and
  `_offline_environment` restores those same values for every offline test; a run with real
  directories exported is therefore not isolated.

- evidence: `crooks-assistant/tests/conftest.py:8-48, 76-94`
- required repair: Make offline directory settings unconditionally point to test-owned temporary paths before app
  imports, or reject inherited paths outside a verified test-owned directory.

### T7 — the remaining tests, part 7 of 7

50 path(s) · 2 material finding(s): **1 BLOCKS**, 1 FOLLOW-UP, 0 settled as not a defect.

**`T7-01` — BLOCKS**  
_still not settled after the one follow-up -> BLOCKS_

BLOCKS — Rollback compatibility cannot be settled from the supplied files, and a mismatch could lose
  objective data. CANNOT TELL whether production’s previous store can read and update round-12
  records: the test executes a fixture for 547f652f, while its claim that production’s 6a29e310
  store is identical is not verified by the supplied files.

- evidence: `crooks-assistant/tests/test_objective_rollback.py:21-46,69-117`
- required repair: Supply crooks-assistant/tests/fixtures/objectives/store_547f652f.py.txt, the candidate’s crooks-
  assistant/app/objectives/store.py, and the store source at production SHA 6a29e310; verify the
  rollback read-and-write test against the actual production source.

**`T7-02` — FOLLOW-UP**

FOLLOW-UP — This test-oracle defect cannot itself be exploited or lose or leak production data
  tonight. The browser test’s fake draft completion returns the same successful order #1999 on every
  invocation, and the Python test never asserts how many completions occurred, so this harness can
  mask an unintended second completion request.

- evidence: `crooks-assistant/tests/test_r12_orders_browser.py:35-40,54-90`
- required repair: Count completion invocations in the fake and assert exactly one after the initial hold and no
  additional invocation after the attempted repeat; make an unexpected repeat return a distinct
  result or fail the test.

### TW — the remaining page tests

13 path(s) · 2 material finding(s): **0 BLOCKS**, 1 FOLLOW-UP, 1 settled as not a defect.

**`TW-01` — FOLLOW-UP**  
_settled by follow-up: defect, FOLLOW-UP_

BLOCKS — An exploitable injection on the owner-accessible page cannot be ruled out because the
  renderer is missing and two safety assertions cannot detect the elements they purport to exclude.
  CANNOT TELL whether externally sourced working-set or batch-card text can create executable nodes:
  dom-shim.js supports only a single simple selector, while ui.test.js queries `script, img`, which
  matches neither tag in that shim.

- evidence: `CANDIDATE FILES: crooks-assistant/tests/web/dom-shim.js, Element.querySelectorAll; crooks-assistant/tests/web/ui.test.js, working-set and batch-card tests`
- required repair: Make those assertions check `script` and `img` separately, or implement comma-separated
  selectors in the shim; test hostile text on both card types. Supply crooks-assistant/web/ui.js
  to settle the renderer's behavior.

**`TW-02` — NOT A DEFECT**  
_settled by follow-up: no defect_

BLOCKS — A replacement TV view could leak the previous customer's details, and the missing
  production files prevent that risk from being settled. CANNOT TELL whether the real display calls
  `forget` before `swap`: dots.test.js explicitly calls them in sequence rather than exercising the
  display's replacement path.

- evidence: `CANDIDATE FILES: crooks-assistant/tests/web/dots.test.js, test 'swap: after forget the new page comes straight out of the orb'; REVIEW PACKET: PR #56 TV replacement claim`
- required repair: Supply crooks-assistant/web/display.js and crooks-assistant/web/dots.js, and test successive
  customer-bearing views through the real replacement path, checking that no old-view dots
  appear during the transition.

### W1 — the remaining pages, part 1 of 3

1 path(s) · 2 material finding(s): **0 BLOCKS**, 2 FOLLOW-UP, 0 settled as not a defect.

**`W1-01` — FOLLOW-UP**  
_settled by follow-up: defect, FOLLOW-UP_

BLOCKS — The missing-file rule applies because the supplied code cannot establish whether objective-
  card rendering could be exploited or leak data in production. CANNOT TELL whether objectives
  render safely or at all: `renderObjective` delegates the entire card to `CliveObjectiveCards.card`
  and returns nothing when that dependency is absent; neither the renderer nor the page that loads
  it was supplied.

- evidence: `CANDIDATE FILES: crooks-assistant/web/ui.js, renderObjective and RENDERERS`
- required repair: Supply crooks-assistant/web/objective-cards.js and crooks-assistant/web/index.html in a follow-
  up packet to verify the renderer and its loading order; fix the integration if it does not
  load and render objective cards safely.

**`W1-02` — FOLLOW-UP**

FOLLOW-UP — The demonstrated failure aborts read-only UI patching; it does not establish
  exploitation, data loss, or data leakage on production as configured. `surfaceId` can put a title
  or subject into a render ID, but `byRender` inserts that ID unescaped into a CSS attribute
  selector. A normal double quote in the ID makes `querySelectorAll` throw, aborting `applyPatches`
  and any later patches in that batch.

- evidence: `CANDIDATE FILES: crooks-assistant/web/ui.js, KEY_OF, surfaceId, byRender and applyPatches`
- required repair: Find nodes by comparing `dataset.render` directly, or escape the ID correctly for a CSS
  selector; test patch IDs containing quotes and selector metacharacters.

### W2 — the remaining pages, part 2 of 3

5 path(s) · 4 material finding(s): **1 BLOCKS**, 2 FOLLOW-UP, 1 settled as not a defect.

**`W2-01` — NOT A DEFECT**  
_settled by follow-up: no defect_

BLOCKS — Without the server bodies, a leak of a record to a TV cannot be ruled out on production as
  configured. CANNOT TELL whether the new show route checks the admitted owner, verifies that the
  submitted record was shown in the submitted conversation, and passes the request through dispatch
  and the gate: `lift.js` sends client-controlled `session_id`, `kind`, and `ref`, but `crooks-
  assistant/app/routes/displays.py` and `crooks-assistant/app/displays/put.py` were not supplied.

- evidence: `CANDIDATE FILES — crooks-assistant/web/lift.js, bodyFor and put; PR #56 claim sheet, “Hold to put it on a TV”`
- required repair: Supply `crooks-assistant/app/routes/displays.py` and `crooks-assistant/app/displays/put.py` for
  review; if those checks are absent, enforce them before showing a record.

**`W2-02` — FOLLOW-UP**  
_settled by follow-up: defect, FOLLOW-UP_

BLOCKS — A wrong order reference on a holdable row could put customer data on a TV, and the missing
  renderer prevents ruling that out. CANNOT TELL whether order rows, cards, and workspaces carry the
  correct `data-kind` and `data-ref` values required by `holdableAt`, because `crooks-
  assistant/web/ui.js` was not supplied.

- evidence: `CANDIDATE FILES — crooks-assistant/web/lift.js, ORDERS and holdableAt`
- required repair: Supply `crooks-assistant/web/ui.js` for review and verify that each holdable order surface
  carries its own correct, canonical order reference.

**`W2-03` — BLOCKS**

BLOCKS — Setting the wrong live objective to done can lose its active status and pending work with
  writes enabled. Two `openObjective` requests can finish out of order: the older response
  unconditionally replaces the newer sheet, and its Mark done button posts `status: 'done'` for the
  older response’s `o.id`; the confirmation does not name that objective.

- evidence: `crooks-assistant/web/alpha.js:330-337,435-445`
- required repair: Track the most recently requested objective and discard older responses before drawing; name the
  objective in the Mark done confirmation.

**`W2-04` — FOLLOW-UP**

FOLLOW-UP — A failed status request shows no demonstrated persisted-data loss, exploit, or leak, but
  it closes the objective sheet as though the change succeeded. Mark done catches an API failure,
  then unconditionally closes the sheet and refreshes.

- evidence: `crooks-assistant/web/alpha.js:435-445`
- required repair: Keep the sheet open on a failed status request; close and refresh only after a confirmed
  success.

### W3 — the remaining pages, part 3 of 3

10 path(s) · 5 material finding(s): **1 BLOCKS**, 3 FOLLOW-UP, 1 settled as not a defect.

**`W3-01` — NOT A DEFECT**  
_settled by follow-up: no defect_

BLOCKS — Without the missing hold implementation, I cannot rule out a record being sent to the wrong
  TV and leaking data in the configured deployment. CANNOT TELL whether the new hold gesture
  identifies the intended record and display or handles a failed drop safely: this part contains its
  stylesheet and script tag, but not `crooks-assistant/web/lift.js`.

- evidence: `PR #56 body, “Hold to put it on a TV”; crooks-assistant/web/index.html, lift.js script tag`
- required repair: Supply `crooks-assistant/web/lift.js` at this exact SHA for review of record selection, display
  selection, request handling and failure paths; repair any demonstrated misrouting.

**`W3-02` — BLOCKS**  
_still not settled after the one follow-up -> BLOCKS_

BLOCKS — The missing callers leave the effect of an owner’s task edit unsettled, so data loss cannot
  be ruled out. CANNOT TELL whether conversation cards and home sheets supply a refresh callback:
  after a successful tick, `toggle` redraws only when `opts.onChange` exists, while a button without
  a redraw retains its original closed-over `done` value and a second tap sends that same value
  again. The callers are in the missing `crooks-assistant/web/ui.js` and `crooks-
  assistant/web/alpha.js`.

- evidence: `crooks-assistant/web/objective-cards.js, taskRow/toggle/card/shape; packet sibling-file contract for ui.js`
- required repair: Supply `crooks-assistant/web/ui.js` and `crooks-assistant/web/alpha.js` at this SHA to establish
  how both surfaces refresh. If either can omit the callback, update the checkbox state used by
  subsequent taps or require a verified redraw, and test two successive toggles.

**`W3-03` — FOLLOW-UP**  
_settled by follow-up: defect, FOLLOW-UP_

BLOCKS — The missing renderer prevents settling whether the owner’s rejected startup flash remains;
  under the packet’s rule, that unresolved requirement blocks review even though the visual defect
  alone would not exploit, lose or leak data. CANNOT TELL how `crooks-assistant/web/dots.js` uses
  the `glints` still constructed and passed to `E.boot` by the full startup.

- evidence: `crooks-assistant/web/startup.js, runFull/spec.glints; PR #56 body, “The start-up star”`
- required repair: Supply `crooks-assistant/web/dots.js` at this SHA and verify its full-startup rendering against
  the no-flash/no-flare requirement; remove any remaining rejected effect if it renders.

**`W3-04` — FOLLOW-UP**  
_settled by follow-up: defect, FOLLOW-UP_

BLOCKS — The missing animation implementation leaves the claimed card behavior unsettled under the
  packet’s CANNOT TELL rule; the visual requirement itself does not imply exploitation, data loss or
  leakage. `dots-app.css` defines a forming-card animation, but neither it nor the script tag
  establishes that arriving cards invoke it or that departing dots are handled: `crooks-
  assistant/web/dots-app.js` was not supplied.

- evidence: `crooks-assistant/web/dots-app.css:1-17; crooks-assistant/web/index.html, dots-app.js script tag`
- required repair: Supply `crooks-assistant/web/dots-app.js` at this SHA for review of card arrival, removal and
  reduced-motion behavior; repair any unimplemented claimed transition.

**`W3-05` — FOLLOW-UP**

FOLLOW-UP — This scroll-edge defect does not enable exploitation, data loss or data leakage in the
  configured deployment. A long Displays tray has a fixed mask fading both ends even when scrolled
  fully to either end, contrary to the new rule that an edge fades only while content remains beyond
  it; `.lift-list` is also absent from the dynamically measured areas.

- evidence: `crooks-assistant/web/lift.css:65-75; crooks-assistant/web/edges.js:39-57`
- required repair: Use a scroll-position-aware mask for `.lift-list` and remove its fixed two-ended mask; test a
  long tray at the top, middle and bottom.

### X1 — the experience harness, part 1 of 2

11 path(s) · 4 material finding(s): **0 BLOCKS**, 4 FOLLOW-UP, 0 settled as not a defect.

**`X1-01` — FOLLOW-UP**

FOLLOW-UP — This can give offline scenarios a false eligibility result, but does not itself enable
  exploitation, lose data, or leak data in production as configured. `model_could_make` claims to
  check whether Claude can supply a scripted call, yet `_fits` checks only the top-level type and
  enum: it accepts an object missing nested required fields, an invalid array item, or a number
  outside its schema bounds.

- evidence: `Packet DIFF: experience/harness.py, _fits and model_could_make`
- required repair: Validate nested objects and arrays and applicable schema constraints, or narrow the reported
  claim to what the checker actually verifies; add tests with invalid nested arguments and
  bounds.

**`X1-02` — FOLLOW-UP**

FOLLOW-UP — This is a false live-test failure, not an exploit or a production data-loss or leak
  path. `needs_reply` is selected for live runs but requires `bool(rows)` before its live/fixture
  split, so a healthy real inbox with nobody awaiting a reply fails the scenario.

- evidence: `Packet DIFF: experience/scenarios.py, LIVE_SCENARIOS and needs_reply`
- required repair: Allow an empty live queue and check that its count and answer accurately report nobody waiting;
  retain the nonempty, exact-thread assertions for the golden fixture.

**`X1-03` — FOLLOW-UP**

FOLLOW-UP — This weakens offline coverage of an order-making flow but does not demonstrate
  exploitation, data loss, or leakage in the configured production service. `order_by_voice` calls
  its draft check exact while asserting only line items, postcode and total; it can pass with the
  wrong or absent draft customer and email, or different postage.

- evidence: `Packet DIFF: experience/scenario_packs/commerce.py, order_by_voice; experience/fixtures/shopify.py, _draft_order_create`
- required repair: Assert that exactly one stored draft has the discovered customer's ID and email, the complete
  intended shipping address and postage, as well as the existing line and discount checks.

**`X1-04` — FOLLOW-UP**

FOLLOW-UP — This mislabels audit coverage rather than directly enabling exploitation, data loss, or
  leakage in production as configured. The feature matrix marks the entire `model_turn` row live-
  read-safe merely because it has scenarios, although that row includes scenarios that stage
  discount, order-edit and email writes; the actual live scenario allow-list is narrower.

- evidence: `Packet DIFF: experience/matrix.py, COVERAGE['model_turn'] and build; experience/scenarios.py, LIVE_SCENARIOS`
- required repair: Derive live-read eligibility from the scenarios actually permitted in live mode and their
  operations, or mark the aggregate model-turn row as mixed rather than live-read-safe.

### X2 — the experience harness, part 2 of 2

8 path(s) · 2 material finding(s): **0 BLOCKS**, 2 FOLLOW-UP, 0 settled as not a defect.

**`X2-01` — FOLLOW-UP**  
_settled by follow-up: defect, FOLLOW-UP_

BLOCKS — I cannot determine whether the claimed TV browser gate detects home or blank frames because
  its driver was not supplied, and the packet requires an unsettled material question to block.
  CANNOT TELL: `run()` forwards the driver's final JSON without checking the Node exit status or
  whether every mode and change was measured; the frame and timing checks are in the missing
  `scripts/browser/tv_flow.js`.

- evidence: `experience/tv_flow.py:111-145; missing scripts/browser/tv_flow.js`
- required repair: Supply scripts/browser/tv_flow.js for review. Make run() reject a nonzero driver exit and
  incomplete per-mode results, and verify that the driver asserts the no-home/no-blank and time-
  to-readable claims.

**`X2-02` — FOLLOW-UP**

FOLLOW-UP — This weak fixture assertion does not itself exploit, lose or leak production data as
  configured, but it can give a false-green result for an incorrect seven-day checkout answer.
  `abandoned_window` accepts any count at or below the fortnight count, including zero, and treats a
  read mentioning “abandoned” as proof that the seven-day filter reached Shopify.

- evidence: `experience/scenario_packs/abandoned.py:116-129`
- required repair: Compare the seven-day count and value against `_window(7)`, and assert that the recorded Shopify
  request contains the intended seven-day date filter.


## B. The evidence packets — one row per open finding

All 100 entries of `crooks-assistant/docs/review/evidence/`, each ruled at this SHA from the
files that settle it. `Author said` is the claim the index carries; `Ruling` is what the
reviewer found in the code. A CANNOT TELL that survived its one follow-up is BLOCKS.

| # | Finding | Index file | Author said | Ruling at 361b0138 | Label | Why |
|---|---|---|---|---|---|---|
| 1 | `S1T-01` | door | FIXED | **REPAIRED** | — | REPAIRED — A reading with a tailnet-range IPv4 decoy but without tailscale0’s IPv4 address no longer admits the server’s own request; a whole reading still admits the phone. |
| 2 | `R9-A1a-F-05B-AVAIL` | door | FIXED | **STILL PRESENT** | BLOCKS | STILL PRESENT BLOCKS — The completeness check does not cover every address tailscale0 may hold: IPv4 checks one ioctl result, while IPv6 accepts any tailnet address on tailscale0 from the incomplete table itself. If a reading reta |
| 3 | `R9-A1b-F-05B-AVAIL` | door | EVIDENCED | **REPAIRED** | — | REPAIRED — The implementation makes at most four reads with bounded pauses, requires two consecutive matching results, and turns exhausted or unreadable locality into refusal at both gates. |
| 4 | `R9-A1b-F-05B-AVAIL` | door | LEFT | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT FOLLOW-UP — A routine table failure lasting beyond the four reads denies the owner rather than exploiting, losing, or leaking data; there is no longer-lived bounded availability strategy. |
| 5 | `CFG-01` | door | FIXED | **REPAIRED** | — | REPAIRED — An unset engineering host resolves to off, and the runtime binds the filing tools to an inbox that refuses reads and writes without reading a token or making an HTTP request. |
| 6 | `S1-KEY-SENDER` | door | FIXED | **CANNOT TELL** | BLOCKS | CANNOT TELL — BLOCKS: These callers delegate health requests to launch_common, whose implementation is not supplied, so the connected-peer, redirect, and proxy protections for key transmission remain unverified. |
| 7 | `R9-A1b-A1B-KEY` | door | EVIDENCED | **REPAIRED** | — | REPAIRED — The keyed health request uses the socket whose far end was checked as held by the service; neither its HTTP client nor the plain fallback follows redirects. |
| 8 | `R9-A1a-F-05A` | door | DEPLOY-TIME | **DEPLOY-TIME** | by the live check |  |
| 9 | `R9-A1b-F-05A` | door | DEPLOY-TIME | **DEPLOY-TIME** | by the live check |  |
| 10 | `R9-A1a-F-05B` | door | EVIDENCED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT FOLLOW-UP — Not every malformed socket row is rejected: _tcp_rows accepts the two-field tail used by short-lived sockets even when the row’s state is ESTABLISHED. A shortened established row retaining its inode can t |
| 11 | `R9-A1a-F-05B-AVAIL-PREFLIGHT` | door | DEPLOY-TIME | **DEPLOY-TIME** | by the live check |  |
| 12 | `R9-A1b-F-05B-AVAIL-PREFLIGHT` | door | DEPLOY-TIME | **DEPLOY-TIME** | by the live check |  |
| 13 | `R9-A1b-A1B-STATUS` | door | EVIDENCED | **REPAIRED** | — | REPAIRED — install_systemd.status returns nonzero for limited health, including when the unit is active. |
| 14 | `R9-A2-F-NEW-TOOLS-PATH` | door | EVIDENCED | **REPAIRED** | — | REPAIRED — With production's unset verification switch resolving to true, the middleware refuses callers who fail the owner rule before /turn runs. It stamps owner authority only after that rule passes; the provider carries that a |
| 15 | `R9-C-C-01` | door | EVIDENCED | **REPAIRED** | — | REPAIRED — /voice/live is owner-gated at the door and again in the route; with production's identity verification enabled, a request bearing forged forwarding headers is refused before a key is read or minted. |
| 16 | `R9-C-C-02` | door | DEPLOY-TIME | **DEPLOY-TIME** | by the live check |  |
| 17 | `R9-C-C-04` | door | EVIDENCED | **REPAIRED** | — | REPAIRED — Provider error types select fixed reason codes, close reasons are not copied, and telemetryFields restricts what the live-voice callback receives. The route additionally drops other fields from live_transcript events. |
| 18 | `R9-E-app2-E-01` | door | EVIDENCED | **REPAIRED** | — | REPAIRED — status.show identifies a limited answer through health_limited, prints summarise_health’s limited-answer explanation and returns 1. For full answers it returns 0 only when all essentials are reported and healthy, naming |
| 19 | `SC-GAPCHECK-DEFAULT` | door | FIXED | **REPAIRED** | — | REPAIRED — A bare run uses an explicitly configured objectives directory rather than the checkout's default .state directory, and a missing record returns exit code 2, not 0. |
| 20 | `AC1-F-01` | families | FIXED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT — FOLLOW-UP — The remaining misclassification is not shown to be exploitable or to lose or leak data on production as configured. When a customer record has no email address, `look` returns `available: True` without  |
| 21 | `F-01` | families | FIXED | **REPAIRED** | — | REPAIRED — The read follows Shopify’s cursor through the window; if it stops before the end, the result labels the figures as partial and the cards mark freshness incomplete. |
| 22 | `F-02` | families | FIXED | **REPAIRED** | — | REPAIRED — `_orders_render` reserves the definitive empty answer for a complete open-orders read and marks an incomplete answer partial. |
| 23 | `R9-E-families1-E-04` | families | EVIDENCED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS: With writes enabled, the model can put one customer's order details in a reply to another customer's thread while omitting the optional order_id; both reply handlers then skip _check_order, so the confident |
| 24 | `R9-I-tests3-I-02` | families | EVIDENCED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS: The supplied dispatch and /turn tests establish refusal only when the call supplies order_id; they do not close the optional-argument path that can stage an order-specific reply to a wrong thread and leak i |
| 25 | `R9-E-families1-E-01` | families | EVIDENCED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT — FOLLOW-UP: With only George allowed to stage changes and a confirmation card requiring his hold, this gap does not itself establish a data-loss or leak path in tonight’s configuration. The posted order must now mat |
| 26 | `R9-E-families1-E-02` | families | EVIDENCED | **REPAIRED** | — | REPAIRED — A canonical address supplied by the model remains uncertain until the owner types it into the recipient field. Both the composer’s staging command and the Gmail write tools refuse an unchecked address. |
| 27 | `R9-E-app1-E-01` | families | EVIDENCED | **REPAIRED** | — | REPAIRED — The recipe runner refuses declared write tools and undeclared plan tools before dispatch; the scheduler independently rejects write and batch tools in a plan. |
| 28 | `R9-I-tests4-I-01` | families | EVIDENCED | **REPAIRED** | — | REPAIRED — The verifier requires the balance to rise by exactly the credited amount in the credited currency; a £15-to-£40 rise after a £20 credit is not verified. |
| 29 | `R9-I-tests5-I-06` | families | EVIDENCED | **REPAIRED** | — | REPAIRED — The test requires search calls and asserts their count, distinct senders, per-sender order terms, and 30-day window without `or True`. |
| 30 | `R9-J-docs1-J-01` | families | FIXED | **REPAIRED** | — | REPAIRED — The README no longer promises an order lookup before Claude is asked and describes the transcript normaliser as removed. |
| 31 | `S3P-F-01` | pages | FIXED | **REPAIRED** | — | REPAIRED — Expiry is checked before the redraw hold, and the expiry timer triggers a render even when no ask completes. |
| 32 | `R9-B1-NEW-B-LOCAL-SLIP` | pages | FIXED | **REPAIRED** | — | REPAIRED — Local expiry checks run before animation deferral; expiry, refusal and prolonged disconnection use wipe(), which removes the drawn DOM and pane references and destroys and blanks the dots engine. |
| 33 | `R9-B2-B2-01` | pages | FIXED | **CANNOT TELL** | BLOCKS | CANNOT TELL — loadScreen removes a legacy key from localStorage before migration, but the supplied files do not establish whether successful registration rotates and invalidates that old key. The missing file is crooks-assistant/a |
| 34 | `R9-B2-B2-04` | pages | FIXED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS: Customer details remain retrievable from the production TV’s DOM after packing during a two-pane-to-one-pane swap. With no fresh pane, swap() marks the screen shown after 520–680 ms, but leaveNow() retains  |
| 35 | `R9-B2-B2-02` | pages | EVIDENCED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS — A refused change can leave customer panes visible after its 403 arrives because `post()` awaits the response body before calling `wipe()`, permitting a leak on the configured remote if that body stalls. |
| 36 | `R9-B2-B-07` | pages | EVIDENCED | **REPAIRED** | — | REPAIRED — GET / serves the same static index.html with only the build ID substituted for every admitted caller. The worker caches that page only after checking its build mark, and an offline load therefore cannot reveal owner-spe |
| 37 | `R9-G-G-01` | pages | EVIDENCED | **CANNOT TELL** | BLOCKS | CANNOT TELL BLOCKS — index.html loads the live-voice, telemetry, and app scripts, but the supplied files do not establish the live-words token’s lifetime or destination, or every destination for live words and telemetry. |
| 38 | `R9-G-G-02` | pages | EVIDENCED | **REPAIRED** | — | REPAIRED — An audio /turn response passes its question to settleLiveWords even if no /state poll saw heard; that function removes the interim words and displays the question or clears the bar. |
| 39 | `R9-G-G-03` | pages | EVIDENCED | **CANNOT TELL** | BLOCKS | CANNOT TELL — FOLLOW-UP: This does not block production as configured because the unverified claim concerns the accent’s appearance, not an identified exploit, data-loss or data-leak path. The current alpha.css has blue accent tok |
| 40 | `R9-C-C-03` | pages | EVIDENCED | **CANNOT TELL** | BLOCKS | CANNOT TELL — The shown onWords callback displays text, but the excerpts omit sendAudio and the visibility/navigation handlers. They cannot establish that live words are never submitted or that navigation clears them. |
| 41 | `R9-C-C-05` | pages | EVIDENCED | **REPAIRED** | — | REPAIRED — Release before socket open starts a separate five-second open wait. On opening, finish clears that timer, pumps buffered audio with a commit, and only then starts the 1.5-second finish timer. |
| 42 | `W1-01` | pages | FIXED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT — FOLLOW-UP — renderOrder now passes the order ID to rail, and railChip uses it for an enabled staged chip, but the required regression test is not found at this SHA. Missing test coverage does not itself create an e |
| 43 | `F-01` | pages | EVIDENCED | **REPAIRED** | — | REPAIRED — `screen_remote` has a renderer that puts the name and titles into text content and attaches a remote-screen identifier only when it matches the screen-ID pattern. |
| 44 | `R9-A3b-F-04-SHUTDOWN` | records | FIXED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS — On the configured always-on server, a housekeeping filesystem call can outlast the five-second stop deadline while a stalled writer leaves accepted events pending beyond the four-second drain. Lifespan the |
| 45 | `CFG-02` | records | FIXED | **REPAIRED** | — | REPAIRED — The rendered unit bounds uvicorn's graceful request drain at ten seconds, and the stated application shutdown budget fits within TimeoutStopSec=30. The held-connection test exercises the lifespan after uvicorn cancels t |
| 46 | `O1-F-01` | records | FIXED | **REPAIRED** | — | REPAIRED — emit acquires the shared writer lock before queuing an event, rejects a busy lock it cannot acquire within the wait, and rechecks the active session after acquisition. |
| 47 | `R9-A3b-F-10` | records | FIXED | **REPAIRED** | — | REPAIRED — Failed or busy shared-lock acquisition makes emit reject the event, and the writer also refuses to write a batch without its hold. |
| 48 | `O1-F-02` | records | EVIDENCED | **REPAIRED** | — | REPAIRED — Executable tests assert retention of a concurrently replaced top-level report and descendant, and assert whole lines and final counts after short writes and stop. |
| 49 | `R9-A3b-F-04-REPORT-LOSS` | records | EVIDENCED | **REPAIRED** | — | REPAIRED — Pruning moves a report aside and checks the moved entry’s identity and age before unlinking it; the same safeguard applies to descendants of aged folders. |
| 50 | `R9-A3b-F-A3B-SHORT-WRITE` | records | EVIDENCED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS — Although ordinary short writes are completed in a loop, a subsequent write failure followed by a failed truncation can leave an incomplete accepted JSONL line that a stop counts as final. _take_back ignore |
| 51 | `R9-A3b-F-04-STARTUP` | records | EVIDENCED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT — FOLLOW-UP — The configured production reports folder is described as a real, private folder, so this path shape is not present tonight. A reports-folder symlink with a missing target makes os.stat raise FileNotFoun |
| 52 | `R9-F-observability1-F-01` | records | EVIDENCED | **REPAIRED** | — | REPAIRED — Both writers pass the session identifier to report_target, which requires a single-component identifier and rejects a target that resolves outside the reports folder. |
| 53 | `R9-F-observability1-F-03` | records | FIXED | **REPAIRED** | — | REPAIRED — The no-router request ‘Give Alice £15 of store credit’ is recognized as a write, mapped to the registered store_credit family, and classified READY rather than NO_FAMILY. |
| 54 | `O2-F-02` | records | FIXED | **REPAIRED** | — | REPAIRED — Credit-grant requests are classified as writes with a store_credit change, while the listed balance questions remain reads. |
| 55 | `R9-F-observability2-F-OBS2-01` | records | FIXED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT — FOLLOW-UP — On the configured single-owner deployment, this reaches an owner-only report rather than a screen or non-owner, so it does not block tonight's deploy. A page-supplied customer name shaped like an identi |
| 56 | `R9-F-observability1-F-02` | records | FIXED | **REPAIRED** | — | REPAIRED — The sanitiser masks text inside a data-spoken element and empties both data-spoken and data-words attribute values. |
| 57 | `O2-F-01` | records | FIXED | **REPAIRED** | — | REPAIRED — “Show me the log for order #1938” matches neither the narrowed log instruction rule nor a defect-shape rule, so recognise returns None. |
| 58 | `R9-E-families1-E-03` | records | EVIDENCED | **REPAIRED** | — | REPAIRED — POST /turn captures recognised feedback against its turn, writes the event after the model call, and the end-to-end test checks that the report lists it as recorded rather than ignored. |
| 59 | `R9-I-tests4-I-02` | records | FIXED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT — FOLLOW-UP: Missing confirmation coverage is a test gap, not an exploitable, data-losing or data-leaking failure as configured. The /turn tests check the feedback event, report and instruction given to the model, bu |
| 60 | `R9-E-families1-E-05` | records | EVIDENCED | **CANNOT TELL** | BLOCKS | CANNOT TELL — BLOCKS — The two supplied modules show no obvious fast-lane import, but they cannot establish that every module imports successfully or that test-session capture runs at this SHA. |
| 61 | `R9-D1-D1-01` | records | FIXED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS. A newly spoken customer name remains in the always-on timeline if the turn's reads do not return that customer: written_heard() emits the STT text after note_names(live.pii_seen), but that set has no new na |
| 62 | `R9-A3a-A3a-LIVE-CLEAN` | records | EVIDENCED | **CANNOT TELL** | BLOCKS | CANNOT TELL — BLOCKS: The ten-row startup test uses stand-in rows, and the packet supplies neither the live record nor the claimed deploy-check result; on production, an unverified field removal or key merge could lose owner data  |
| 63 | `R9-A3b-F-A3B-SCREEN-EVIDENCE` | screens-server | FIXED | **REPAIRED** | — | REPAIRED — Registration returns the screen identity and pairing state with the key confined to a cookie; the keyed poll returns only that screen’s panes, cut to kind-specific fields. Snapshots being off does not change the display |
| 64 | `R9-B1-B-01-B-05-PATH` | screens-server | EVIDENCED | **CANNOT TELL** | BLOCKS | CANNOT TELL — BLOCKS — put_held checks issued IDs for drops, but the supplied files do not show how screen routes authenticate callers or how screen tool calls pass through the gate; the production-path test source has no executio |
| 65 | `R9-B1-B-03` | screens-server | EVIDENCED | **REPAIRED** | — | REPAIRED — A deletion is retained as owed after a durable journal flush; if neither journal nor record is durable, _commit restores the previous record and refuses the deletion. Restart replay and retry preserve an owed deletion. |
| 66 | `R9-B1-NEW-B-LOCAL-SLIP` | screens-server | EVIDENCED | **REPAIRED** | — | REPAIRED — For the server-side question in this packet, a refused device gets a 403 before the poll handler serves a pane, and poll expires an old slip before returning its answer. This ruling does not establish what an already-op |
| 67 | `R9-B1-B-REMOTE-OFF` | screens-server | EVIDENCED | **REPAIRED** | — | REPAIRED — A remote whole-screen off must supply the screen version, which the store checks under its lock before removing either pane. |
| 68 | `R9-B1-B-NEW-DONE-LOSS` | screens-server | EVIDENCED | **REPAIRED** | — | REPAIRED — _write no longer discards done rows to fit the file. _commit refuses a size-increasing overflow before writing, while done-row removal is limited to the stated age and count retention rules. |
| 69 | `R9-B1-B-04` | screens-server | FIXED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS: An approved production TV can falsify a packed record and remove its slip without showing a page or packing the order. Direct paced /seen requests followed by confirm:true still create a done row. The attem |
| 70 | `R9-B2-B2-01` | screens-server | FIXED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS: A rotation can return the fresh cookie after the record rename but before its directory flush succeeds; a power cut can then restore the old key hash, reviving a copied legacy key and potentially exposing f |
| 71 | `S3-SCREEN-VIDEO` | screens-server | EVIDENCED | **REPAIRED** | — | REPAIRED — This ID has no prior reviewer wording. For the question raised by the evidence index, the route accepts only typed, bounded player fields; the store requires the screen key and current video version, then retains a fixe |
| 72 | `R9-I-tests1-F-A2-FIXTURE` | tests | EVIDENCED | **REPAIRED** | — | REPAIRED — The owner fixture is opt-in, and dispatch refuses an unstamped call before the gate or a handler. |
| 73 | `R9-I-tests2-I-04` | tests | EVIDENCED | **REPAIRED** | — | SETTLED — NO DEFECT. The owner grants in the supplied tests do not mask the refusal tests: those tests exercise refusals that an authorized owner should encounter. test_discounts.py grants authority per test and explicitly checks  |
| 74 | `R9-I-tests3-F-A2-FIXTURE` | tests | EVIDENCED | **REPAIRED** | — | REPAIRED — There is no suite-wide owner fixture, and fresh-context dispatch refusals cover fulfilment and the listed Gmail writes. |
| 75 | `R9-I-tests4-I-04` | tests | EVIDENCED | **REPAIRED** | — | REPAIRED — The default grant is absent, and unstamped dispatch is tested for refunds and store credit. |
| 76 | `R9-I-tests5-I-04` | tests | FIXED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT — FOLLOW-UP — test_tracking still grants owner authority to every test, including a declaration-only test that does not need it, so its grant has not been restricted as the question requires; the separate no-authorit |
| 77 | `R9-H-experience1-F-A2-FIXTURE` | tests | FIXED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT — FOLLOW-UP. The harness now defaults to refusing unverified owner headers and restores the app’s runtime and allow-list, but its lifespan leaves `app.state.housekeeper` holding the fixture runtime, and `runtime.buil |
| 78 | `R9-I-tests1-I-01` | tests | EVIDENCED | **REPAIRED** | — | REPAIRED — The unconditional assertions are gone. The tests check the GET response and the turn-log record produced by a real turn, including redacted read arguments and a refused note logged by length. |
| 79 | `R9-I-tests3-I-04` | tests | EVIDENCED | **REPAIRED** | — | REPAIRED — Spoken-turn tests count shop reads for both the summary and per-buyer read patterns; the inventory test compares equivalent results. The model's choice is scripted, not a test of what Claude would choose. |
| 80 | `R9-I-tests5-I-02` | tests | EVIDENCED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT — FOLLOW-UP — The test sends the owner’s words through /turn and checks that the final UI has one summary, but its workspace assertion checks only a set of patch types; two distinct summary cards staged before the an |
| 81 | `R9-I-tests5-I-05` | tests | FIXED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT — FOLLOW-UP — The audit can count a dispatcher call inside a helper that no test invokes: the positive regression case explicitly accepts an uncalled `go()` function, and `read_test` collects calls from every functio |
| 82 | `R9-H-experience1-H-06` | tests | EVIDENCED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT — FOLLOW-UP — `scenario_strings` still collects any string literal in a scenario function outside its few excluded syntax forms, and `_scenario_tools` treats a collected tool name as coverage. Thus a tool name in a ` |
| 83 | `R9-H-experience1-H-02` | tests | EVIDENCED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT — FOLLOW-UP. Captures and reports now correctly identify scripted choices, but the separate model-decision evidence the original finding required is absent: `a_model_turn` checks only count and lane, while the named  |
| 84 | `R9-H-experience1-H-03` | tests | EVIDENCED | **REPAIRED** | — | REPAIRED — The three scenarios now script change attempts and check their staging or refusal, non-execution, and answers; a separate test requires them to fail when the model attempts nothing. |
| 85 | `R9-H-experience1-H-04` | tests | EVIDENCED | **CANNOT TELL** | BLOCKS | CANNOT TELL — The harness’s ask method does drive POST /turn through say, but the local SCENARIOS tuple does not list the restored scenario, and the supplied files do not show whether scenario_packs.collect includes it or verify i |
| 86 | `R9-H-experience1-H-05` | tests | EVIDENCED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT — FOLLOW-UP: This is a test-oracle defect, not a production exploit, data-loss path, or leak under the stated configuration. The oracle compares sets of thread IDs, so duplicate queue rows can pass as the expected th |
| 87 | `R9-H-experience1-H-07` | tests | EVIDENCED | **REPAIRED** | — | REPAIRED — Both credit scenarios open the form through h.ask and inspect that turn's tool calls; the capability probe is separately identified as unit-level. |
| 88 | `R9-D1-D1-02` | turn | FIXED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS — A note dictated after a tap naming order B can be staged on previously focused order A and committed, losing data on the wrong record. The binding is only a prompt to the model: when the spoken words name  |
| 89 | `R9-D1-D1-03` | turn | EVIDENCED | **CANNOT TELL** | BLOCKS | CANNOT TELL — BLOCKS: The supplied dispatcher and gate show that writes are staged, but do not establish whether refund, cancellation, and store-credit refusal and disambiguation remain as strong as the removed fast lane's; the pa |
| 90 | `R9-D2-D2-01` | turn | FIXED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS — A superseded answer can still replace the newer screen and cursor, leaving a subsequent write aimed at the wrong order. `_answer` checks `abandoned` once, then can await `_hold_to_the_screen` while `_draw_ |
| 91 | `R9-D2-D2-02` | turn | EVIDENCED | **REPAIRED** | — | REPAIRED — `is_affirmation` accepts only complete phrases from its fixed list: digits and `#` make “yes, #1938” a new instruction, so the waiting card is revoked and the words reach the model. |
| 92 | `R9-D2-D2-03` | turn | FIXED | **REPAIRED** | — | REPAIRED — `row` binds `CURRENT_BRANCH` to the row's half during dispatch, and `command` binds it to the tapped half through `_stage_change`; neither staging path relies on the shared `acting_branch` field. |
| 93 | `R9-D2-D2-04` | turn | FIXED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS — The mixed order-and-customer screen no longer selects a new cursor, but its uniquely identified tap is not enforced at the write boundary, so a model that stages a change on the old cursor's order can leav |
| 94 | `R9-D2-D2-05` | turn | FIXED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS — A named customer's wrong-record money change can still lose data: the post-model target check handles order proposals only and expressly skips other entity kinds. The named-customer tests script a correct  |
| 95 | `R9-I-tests2-I-01` | turn | FIXED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS — A note bound to #1938 can be proposed and committed there after the owner explicitly directs it to #1940 if the note text also mentions #1940. `_off_target` subtracts every number in the proposed note from |
| 96 | `R9-I-tests2-I-02` | turn | FIXED | **STILL PRESENT** | FOLLOW-UP | STILL PRESENT — FOLLOW-UP — With another record in focus, the positive order and named-person tests accept the spoken answer “Here it is,” which neither identifies the requested record nor explicitly declines; the turn route check |
| 97 | `R9-I-tests2-I-03` | turn | FIXED | **REPAIRED** | — | REPAIRED — The separate, parameterized turn test asks for #1940 with #1938 open and vice versa, derives the lookup from the owner's words, and asserts the requested card and cursor while excluding a read of the open order; a provi |
| 98 | `R9-I-tests3-I-03` | turn | FIXED | **REPAIRED** | — | REPAIRED — Turn-level tests cover spoken refund, cancellation and store credit as held red cards, refusal of an unarmed commit, and a spoken yes applying nothing. Other turn tests cover cross-order tabs and spoken half navigation; |
| 99 | `R9-I-tests5-I-01` | turn | EVIDENCED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS: On tonight’s write-enabled system, “open the inbox” can be taken as dictation and staged as a note on the bound order; the resulting pending card can apply that unintended change if tapped. The negative tes |
| 100 | `R9-I-tests5-I-03` | turn | FIXED | **STILL PRESENT** | BLOCKS | STILL PRESENT — BLOCKS: an explicitly named target can be removed from the target check merely because its number also appears in the note being written, leaving a wrong-order proposal available for confirmation and a data-losing  |


## C. The blocking findings, in one list

### From the parts

- **`F/F-01`** — BLOCKS — With writes enabled, correcting one part of an order address can lose data from another part of that address. `_from_order` silently truncates the existing recipient, street, town and codes; `_open` treats those shortened values as the original addres
- **`O1/O1-01`** — BLOCKS — This can lose already-written production timeline data if two writers append to the same session, and I cannot rule out that condition from the files supplied. Writers hold shared locks, so if one has a partial write, another appends a complete event,
- **`O2/O2-N-01`** — BLOCKS — This would lose data on production with always-on test sessions: a manually named session whose slug contains `-always-on` is given the short automatic-session retention period. `TestSessions._prune` classifies by substring rather than by the session'
- **`O2/O2-N-02`** — BLOCKS — This can lose data: `_tidy_reports` follows a symlink at the configured reports path and prunes its target before `tighten` detects and reports the link. An aged `ts-*` file in that target can therefore be deleted despite the subsequent privacy refusa
- **`S1/S1-NEW-02`** — BLOCKS — Production's always-on timeline may leak personal data, and I cannot settle whether downstream redaction prevents that leak without the missing files. CANNOT TELL: `_spoken_fields` retains strings under unrecognised nested keys before arguments are em
- **`S2Ba/F-01`** — BLOCKS — On production as configured, this can leak one customer's order confirmation and purchase details to another customer's email address. When an open order is changed from Alice to Bob, `_choose_customer` replaces the customer but fills the confirmation
- **`S2Ba/F-02`** — BLOCKS — On production as configured, this can leak a new customer's order contents by delivering them to the previous customer's address. Opening from Alice's order selects its shipping address; a subsequent `shopify_order_build(customer_id=Bob)` changes the 
- **`S2T/S2T-01`** — BLOCKS — The missing turn implementation leaves a possible wrong-record write unresolved on production with writes enabled, and the packet's uncertainty rule makes that blocking. CANNOT TELL whether the round-12 on-screen claim check rejects a model answer cla
- **`S2T/S2T-02`** — BLOCKS — An unverified live model-to-write path could allow an unapproved change and lose data on production with writes enabled, so this uncertainty blocks. CANNOT TELL whether live Claude tool calls preserve the prepare-only boundary: tests/test_turn_boundar
- **`S2a/S2a-01`** — BLOCKS — A wrong-order write can lose existing order data on production, where writes are enabled. If the owner asks to set #1940’s note to text that itself mentions #1940, but the model prepares the change for #1938, `_written_numbers` removes #1940 from the 
- **`S2a/S2a-03`** — BLOCKS — CANNOT TELL whether the made-once write boundary prevents duplicate orders or credits; if it does not, production writes could lose data. The commit route calls `workspaces.commit_refused` and `before_commit` before the engine’s atomic claim, but the 
- **`S2b/S2b-01`** — BLOCKS — A deceptive Reply-To on an inbound email can cause the owner to authorise a reply to a different mailbox than the fixed recipient shown in the composer, leaking the reply despite owner-only Tailscale access. `_thread_sender` displays the last inbound 
- **`S2b/S2b-02`** — BLOCKS — An unexcluded second store-credit mutation on tonight's write-enabled production could lose money. CANNOT TELL whether an ambiguous Shopify result or a second prepared proposal leaves the workspace locked against another credit: the new protection rel
- **`S2b/S2b-03`** — BLOCKS — A still-committable proposal addressed to the old recipient after an owner edits a composer could leak the email on this write-enabled deployment. CANNOT TELL whether `compose.field` withdraws an already prepared send: `_compose_field` changes the com
- **`S3/S3-01`** — BLOCKS — This can leak an order’s customer details to a different screen on production. A hold validates the requested screen ID, but dispatches `screen_show` using only its name; if that screen is forgotten and a replacement is approved under the same name be
- **`S3/S3-02`** — BLOCKS — This can lose packing progress that the owner was told was saved if the host restarts after a directory-sync failure. For a non-deletion such as a remote tick, `_write` raises `NotFlushed`, but `_commit` returns success despite the new file not being 
- **`S3/S3-03`** — BLOCKS — Whether the new hold route can be exploited or leak data on production cannot be settled without the missing authority code. `put_held` calls `dispatch` without passing its request, while `screen_show` requires current OWNER authority; the supplied fi
- **`S3P/S3P-NEW-01`** — BLOCKS — This can leak data by putting a removed private pane back on the owner's remote. In remote.js, a GET started before a successful screen-off action can finish afterward: sync() accepts its older panes because the action does not advance R.gen, overwrit
- **`S3T1/S3T1-01`** — BLOCKS — An unverified session-and-record check on the new hold-to-screen route could leak an order or objective to the wrong screen in production as configured. CANNOT TELL whether POST /displays/{id}/show checks that the supplied session and reference belong
- **`S5/S5-01`** — BLOCKS — A failed install can lose the existing unit-file data on production. `install()` reads the old unit, then overwrites it with `Path.write_text()` outside the rollback-protected steps; a partial write or write error can leave the old unit truncated and 
- **`S6/S6-01`** — BLOCKS — A power loss can lose objective design data on production. The three-step write replaces the pending design and record without flushing either file or their directories; the new record can survive while its pending design does not, leaving the older, 
- **`S6/S6-02`** — BLOCKS — This can lose tasks and people the owner asked to record. Creation silently takes only the first 60 tasks and `_people` silently takes only the first 12 people, while the objective-open schema sets no corresponding input limits or reports omissions.
- **`S6/S6-03`** — BLOCKS — An existing task's newly supplied due date can be lost. `_add_task` returns an open task with the same person and text without applying or rejecting a different `due`; `task` then records a successful event despite keeping the old date.
- **`S6/S6-04`** — BLOCKS — Reordering stages can subsequently lose recorded completion state and timestamps. `_stages` keeps each stage's old state in its new position without restoring the done/current/upcoming ordering; a later `move_stage('next')` operates by position, poten
- **`T1/T1-01`** — BLOCKS — CANNOT TELL whether editing an order after Prepare invalidates its old hold card, so a write on production could create an order with stale lines or delivery details; the missing files are app/families/order_create.py, app/routes/actions.py and app/ac
- **`T1/T1-02`** — BLOCKS — CANNOT TELL whether production search handles orders beyond its first result page before declaring a match unique or absent, which could misdirect a subsequent order write; the missing file is app/tools/shopify_tools.py. The fake shop truncates result
- **`T3/T3-01`** — BLOCKS — On writes-enabled production, applying a stale store-credit hold could duplicate a money-moving credit, and the missing write-path files prevent ruling out that loss. CANNOT TELL whether the independent stale-card check demonstrated for orders also pr
- **`T3/T3-02`** — BLOCKS — Misclassifying an attempted order completion as safe to retry could make two orders in production, and the missing engine implementation prevents ruling out that data loss. CANNOT TELL whether the claimed never-reached-completion path is safe: the tes
- **`T4/T4-01`** — BLOCKS — An unintended Shopify write could lose data with production writes enabled, and the supplied files do not establish that this test detects one. CANNOT TELL whether the harness store has a `mutations_sent` ledger: the test compares `getattr(..., None)`
- **`T4/T4-02`** — BLOCKS — A failed objective-design write or incompatible rollback could lose owner records, and that risk cannot be settled from the supplied tests. CANNOT TELL whether the claimed three-step write and pre-round-12 readability hold: the old-record test exercis
- **`T5/T5-01`** — BLOCKS — An owner-check bypass on the new screen-show route could leak customer order details on tonight’s tailnet, and the supplied files cannot rule it out. CANNOT TELL whether a drop is refused before reading an unissued record or changing a screen: the tes
- **`T6/T6-01`** — BLOCKS — CANNOT TELL whether an interrupted objective write or rollback would lose data on the configured host because the objective store implementation and rollback fixture were not supplied. The round-12 tests inject exceptions at `os.replace` calls but do 
- **`T7/T7-01`** — BLOCKS — Rollback compatibility cannot be settled from the supplied files, and a mismatch could lose objective data. CANNOT TELL whether production’s previous store can read and update round-12 records: the test executes a fixture for 547f652f, while its claim
- **`W2/W2-03`** — BLOCKS — Setting the wrong live objective to done can lose its active status and pending work with writes enabled. Two `openObjective` requests can finish out of order: the older response unconditionally replaces the newer sheet, and its Mark done button posts
- **`W3/W3-02`** — BLOCKS — The missing callers leave the effect of an owner’s task edit unsettled, so data loss cannot be ruled out. CANNOT TELL whether conversation cards and home sheets supply a refresh callback: after a successful tick, `toggle` redraws only when `opts.onCha

### From the evidence packets

- **`R9-A1a-F-05B-AVAIL`** (STILL PRESENT) — STILL PRESENT BLOCKS — The completeness check does not cover every address tailscale0 may hold: IPv4 checks one ioctl result, while IPv6 accepts any tailnet address on tailscale0 from the incomplete table itself. If a reading reta
- **`S1-KEY-SENDER`** (CANNOT TELL) — CANNOT TELL — BLOCKS: These callers delegate health requests to launch_common, whose implementation is not supplied, so the connected-peer, redirect, and proxy protections for key transmission remain unverified.
- **`R9-E-families1-E-04`** (STILL PRESENT) — STILL PRESENT — BLOCKS: With writes enabled, the model can put one customer's order details in a reply to another customer's thread while omitting the optional order_id; both reply handlers then skip _check_order, so the confident
- **`R9-I-tests3-I-02`** (STILL PRESENT) — STILL PRESENT — BLOCKS: The supplied dispatch and /turn tests establish refusal only when the call supplies order_id; they do not close the optional-argument path that can stage an order-specific reply to a wrong thread and leak i
- **`R9-B2-B2-01`** (CANNOT TELL) — CANNOT TELL — loadScreen removes a legacy key from localStorage before migration, but the supplied files do not establish whether successful registration rotates and invalidates that old key. The missing file is crooks-assistant/a
- **`R9-B2-B2-04`** (STILL PRESENT) — STILL PRESENT — BLOCKS: Customer details remain retrievable from the production TV’s DOM after packing during a two-pane-to-one-pane swap. With no fresh pane, swap() marks the screen shown after 520–680 ms, but leaveNow() retains 
- **`R9-B2-B2-02`** (STILL PRESENT) — STILL PRESENT — BLOCKS — A refused change can leave customer panes visible after its 403 arrives because `post()` awaits the response body before calling `wipe()`, permitting a leak on the configured remote if that body stalls.
- **`R9-G-G-01`** (CANNOT TELL) — CANNOT TELL BLOCKS — index.html loads the live-voice, telemetry, and app scripts, but the supplied files do not establish the live-words token’s lifetime or destination, or every destination for live words and telemetry.
- **`R9-G-G-03`** (CANNOT TELL) — CANNOT TELL — FOLLOW-UP: This does not block production as configured because the unverified claim concerns the accent’s appearance, not an identified exploit, data-loss or data-leak path. The current alpha.css has blue accent tok
- **`R9-C-C-03`** (CANNOT TELL) — CANNOT TELL — The shown onWords callback displays text, but the excerpts omit sendAudio and the visibility/navigation handlers. They cannot establish that live words are never submitted or that navigation clears them.
- **`R9-A3b-F-04-SHUTDOWN`** (STILL PRESENT) — STILL PRESENT — BLOCKS — On the configured always-on server, a housekeeping filesystem call can outlast the five-second stop deadline while a stalled writer leaves accepted events pending beyond the four-second drain. Lifespan the
- **`R9-A3b-F-A3B-SHORT-WRITE`** (STILL PRESENT) — STILL PRESENT — BLOCKS — Although ordinary short writes are completed in a loop, a subsequent write failure followed by a failed truncation can leave an incomplete accepted JSONL line that a stop counts as final. _take_back ignore
- **`R9-E-families1-E-05`** (CANNOT TELL) — CANNOT TELL — BLOCKS — The two supplied modules show no obvious fast-lane import, but they cannot establish that every module imports successfully or that test-session capture runs at this SHA.
- **`R9-D1-D1-01`** (STILL PRESENT) — STILL PRESENT — BLOCKS. A newly spoken customer name remains in the always-on timeline if the turn's reads do not return that customer: written_heard() emits the STT text after note_names(live.pii_seen), but that set has no new na
- **`R9-A3a-A3a-LIVE-CLEAN`** (CANNOT TELL) — CANNOT TELL — BLOCKS: The ten-row startup test uses stand-in rows, and the packet supplies neither the live record nor the claimed deploy-check result; on production, an unverified field removal or key merge could lose owner data 
- **`R9-B1-B-01-B-05-PATH`** (CANNOT TELL) — CANNOT TELL — BLOCKS — put_held checks issued IDs for drops, but the supplied files do not show how screen routes authenticate callers or how screen tool calls pass through the gate; the production-path test source has no executio
- **`R9-B1-B-04`** (STILL PRESENT) — STILL PRESENT — BLOCKS: An approved production TV can falsify a packed record and remove its slip without showing a page or packing the order. Direct paced /seen requests followed by confirm:true still create a done row. The attem
- **`R9-B2-B2-01`** (STILL PRESENT) — STILL PRESENT — BLOCKS: A rotation can return the fresh cookie after the record rename but before its directory flush succeeds; a power cut can then restore the old key hash, reviving a copied legacy key and potentially exposing f
- **`R9-H-experience1-H-04`** (CANNOT TELL) — CANNOT TELL — The harness’s ask method does drive POST /turn through say, but the local SCENARIOS tuple does not list the restored scenario, and the supplied files do not show whether scenario_packs.collect includes it or verify i
- **`R9-D1-D1-02`** (STILL PRESENT) — STILL PRESENT — BLOCKS — A note dictated after a tap naming order B can be staged on previously focused order A and committed, losing data on the wrong record. The binding is only a prompt to the model: when the spoken words name 
- **`R9-D1-D1-03`** (CANNOT TELL) — CANNOT TELL — BLOCKS: The supplied dispatcher and gate show that writes are staged, but do not establish whether refund, cancellation, and store-credit refusal and disambiguation remain as strong as the removed fast lane's; the pa
- **`R9-D2-D2-01`** (STILL PRESENT) — STILL PRESENT — BLOCKS — A superseded answer can still replace the newer screen and cursor, leaving a subsequent write aimed at the wrong order. `_answer` checks `abandoned` once, then can await `_hold_to_the_screen` while `_draw_
- **`R9-D2-D2-04`** (STILL PRESENT) — STILL PRESENT — BLOCKS — The mixed order-and-customer screen no longer selects a new cursor, but its uniquely identified tap is not enforced at the write boundary, so a model that stages a change on the old cursor's order can leav
- **`R9-D2-D2-05`** (STILL PRESENT) — STILL PRESENT — BLOCKS — A named customer's wrong-record money change can still lose data: the post-model target check handles order proposals only and expressly skips other entity kinds. The named-customer tests script a correct 
- **`R9-I-tests2-I-01`** (STILL PRESENT) — STILL PRESENT — BLOCKS — A note bound to #1938 can be proposed and committed there after the owner explicitly directs it to #1940 if the note text also mentions #1940. `_off_target` subtracts every number in the proposed note from
- **`R9-I-tests5-I-01`** (STILL PRESENT) — STILL PRESENT — BLOCKS: On tonight’s write-enabled system, “open the inbox” can be taken as dictation and staged as a note on the bound order; the resulting pending card can apply that unintended change if tapped. The negative tes
- **`R9-I-tests5-I-03`** (STILL PRESENT) — STILL PRESENT — BLOCKS: an explicitly named target can be removed from the target check merely because its number also appears in the note being written, leaving a wrong-order proposal available for confirmation and a data-losing 


## D. The preflight, in full

Every preflight check passed. The deploy was stopped by the review, not by the preflight.

==============================================================================================
STEP 1 — PREFLIGHT, ROUND 12, at 361b01380737f8f48020dd30cef1e5f750e700bb. Read-only.
==============================================================================================

1.1 SHA PROVENANCE
  origin/clive/trunk (fetched read-only from GitHub) = 361b01380737f8f48020dd30cef1e5f750e700bb
  candidate                                          = 361b01380737f8f48020dd30cef1e5f750e700bb  (they match)
  parents                    = 3f05f5f0 (trunk, PR #56) + 406ed2f7 (PR #57 head)
  PR #57 per GitHub          = merge commit 361b0138, head 406ed2f7, base clive/trunk, MERGED 2026-09-29T12:20:49Z
  PR #56 per GitHub          = merge commit 3f05f5f0, head 30ec0ce5, base clive/trunk, MERGED
  ancestors of the candidate, all present:
      3f05f5f0 YES   547f652f YES   81c78948 YES   a7cd2be7 YES
      c6c640d7 YES   32a99cd7 YES   6a29e310 YES   3e77f215 YES

  ACCEPTANCE RUNS — all five completed/success:
     36567654914  acceptance  push          clive/trunk          361b0138   <- ON THE CANDIDATE ITSELF
     36566643729  acceptance  pull_request  claude/r12-polish    406ed2f7
     36566622581  acceptance  push          claude/r12-polish    406ed2f7
     36564509363  acceptance  pull_request  claude/r12-integrate 30ec0ce5
     36564470572  acceptance  push          claude/r12-integrate 30ec0ce5
  This carries NO review weight. clive/trunk is unprotected and a green run is not a review.

  The review checkout is a separate clone at /root/clive-activation/round-12/review, detached at
  361b0138, tree 13e7b2e3. Production stayed at 6a29e310, 0 dirty, throughout.

1.2 THE SWITCHES — exactly as required, and .env BYTE-IDENTICAL to rounds 9 and 10
     CROOKS_SCREEN_SNAPSHOTS          = 'false'
     CROOKS_LOCAL_OWNER               = <unset>
     CROOKS_WRITES_LOCAL_OWNER        = 'false'
     CROOKS_ENGINEERING_HOST          = <unset>
     CROOKS_TAILSCALE_VERIFY          = <unset>
     CROOKS_LIVE_TRANSCRIPT           = <unset>
     CROOKS_SCRIBE_KEYTERMS           = 'true'
     CROOKS_WRITES_ENABLED            = 'true'
     CROOKS_TEST_SESSION_ALWAYS       = 'true'
     CROOKS_REPORTS_DIR               = <unset>
     CROOKS_ALLOWED_LOGINS            = non-empty (value never printed)
     40 keys, no duplicate key
  .env sha256 0021c07d9c523d4112420537698eae50c51945f5966d3b0d01501def035693ce
             — IDENTICAL to round 10's recorded value. mode 600, 3513 bytes.
  No .env line was changed at any point in this review.
  NEW AT THIS BUILD: config/settings.py:190 now reads `engineering_host: str = "off"` (it was
  "worker-01"). So CROOKS_ENGINEERING_HOST unset means filing is SWITCHED OFF, as the prompt says.

1.3 THE UNIT DIFF — the rendered unit at the candidate against the installed one
  The renderer was first proved faithful: install_systemd.py --print from a worktree of
  6a29e310 reproduces the INSTALLED unit BYTE FOR BYTE.
  installed unit sha256 3808af03c0bb0dcfc083ab519b33be3a82299ba92cc418a73678ba60c826722b
             — unchanged since round 10.

  DIRECTIVES: exactly ONE changed, and it is the expected one. 40 directives both sides.
     -ExecStart=... --host 127.0.0.1 --port 8000 --no-proxy-headers
     +ExecStart=... --host 127.0.0.1 --port 8000 --timeout-graceful-shutdown 10 --no-proxy-headers
  --timeout-graceful-shutdown 10 sits IMMEDIATELY BEFORE --no-proxy-headers, which STAYS LAST.
  TimeoutStopSec=30 on both sides. The three LoadCredentialEncrypted lines are identical.

  COMMENTS: the writable-paths comment round 10 already showed changes as before
     -#   the checkout   logs/, .cache/media/, kb/.catalogue-cache.txt
     +#   the checkout   logs/, .cache/media/
  and SEVEN further comment lines are added, all of them documenting the two changes above:
  three above ExecStart explaining the flag order and the 10 s drain, four above KillSignal
  explaining how the 30 s stop is now budgeted. They carry no systemd semantics.

  OBSERVATION FOR THE OWNER, NOT A PASS I GAVE MYSELF: the prompt said to expect "exactly two
  changes" and to stop on anything else. There are exactly two SUBSTANTIVE changes — the
  ExecStart directive and the writable-paths comment — and no third thing the unit does
  differently. The seven extra lines are comments explaining those two. I did not treat comment
  text that documents an approved change as a third change, and I am flagging it here so the
  owner can disagree.

1.4 TAILSCALE AND KERNEL-TABLE PRECONDITIONS
  tailscaled MainPID 1655, exe exactly /usr/sbin/tailscaled,
  cgroup exactly 0::/system.slice/tailscaled.service
  /usr/sbin/tailscaled, the cgroup and its cgroup.procs: all uid 0, no group-write, no
  other-write -> PASS (computed in python, not shell arithmetic)
  pidfd_open(1) from the production venv interpreter (Python 3.12.3): OK
  tailscale ip -4 = 100.72.82.24        present in /proc/net/fib_trie as /32 host LOCAL
  tailscale ip -6 = fd7a:115c:a1e0::352b:5219  present in /proc/net/if_inet6 (hex)
  disable_ipv6 = 0

1.4b PARSER CHECK AT THE CANDIDATE (production venv interpreter, real host tables)
  net/tcp  : ACCEPTED, 12 of 12 data rows parsed
  net/tcp6 : ACCEPTED, 39 of 39 data rows parsed
  identity.this_hosts_addresses() returned BOTH tailnet addresses, reason EMPTY.  parser-rc=0

1.4c THE TAILNET SELF-CHECK  *** NEW THIS ROUND ***
  As root, from the review checkout's crooks-assistant/, with the production venv interpreter:
      python -c "from app.identity import tailnet_self_check; print(tailnet_self_check())"
  printed:
      (True, "this host's own tailnet IPv4 and IPv6 addresses are on tailscale0 and in its
       address tables")
  PASS. The install's post-restart self-check will not roll the deploy back on this ground, and
  George's devices will not be refused.

1.5 REPORTS
  CROOKS_REPORTS_DIR unset -> /opt/crooks-os/crooks-assistant/reports, uid 0, mode 700
  2 entries total (the directory and .gitkeep). Others-reachable count: 0. No .withheld/.
  Unchanged from round 10.

1.6 THE GAP RECORD AND ITS ONE BACKUP
  /var/lib/crooks-assistant/objectives/gaps.json  uid 0, mode 600, 5866 bytes
  sha256 7f1a7f6b86a708d0b3872b12b8e75c52ed2a197122f01697359c4f798f8eaf48
         — BYTE-IDENTICAL to rounds 9 and 10. version 1, 10 gaps, 0 builds, 0 misjudged.
  Backups matching gaps.json.*: exactly 1 (gaps.json.20260927T211850Z.before-clean).
  No row has been lost. Nothing has changed since round 9.

1.6b THE GAP CHECK — WITH THE LIVE PATH GIVEN
  scripts/gap_clean_check.py /var/lib/crooks-assistant/objectives/gaps.json  ->  exit 0
     record: 10 gap row(s) before, 10 after; file unchanged; 0 copies of the original kept
     rows 1-10 each: "kept as it was"
     rollback code (3e77f215) reads and reports the result: yes
     VERDICT: nothing lost
  THE START-UP CLEAN KEEPS EVERY ROW.

1.6c THE GAP CHECK — RUN BARE  *** the defect round 10 found is fixed ***
  scripts/gap_clean_check.py with no argument  ->  exit 2
     "NOTHING CHECKED: no objectives directory is configured here (CROOKS_OBJECTIVES_DIR is not
      in the environment or in <checkout>/.env), so there is no record to check: give the
      record's path, e.g. python scripts/gap_clean_check.py /var/lib/.../gaps.json"
  Round 10 found this exiting 0 — a silent pass that looked like a real one. This build exits 2.

  The live record was untouched by BOTH runs: same mode, size, mtime and sha256 before and
  after. Backups still exactly 1.

1.7 THE VENDORED ROLLBACK READER
  tests/rollback/gaps_3e77f215.py loaded; 3e77f215's GapLedger.load() reads the live record
  (10 gaps, version 1, seeded 2026-09-27T01:07:06+00:00); report() run against a byte-identical
  COPY returned gaps/misjudged/summary and left the copy unchanged; the live record was never
  written.  PASS

1.8 displays.json  (/var/lib/crooks-assistant/objectives/displays.json)
  uid 0, mode 600, 1089 bytes, sha256 c7f28fa3e23a04e227c0ae336ed3af52c5be4ed526a33f1e7130763107613a80
  SCREEN COUNT: 3 — the same three ids rounds 9 and 10 recorded.
     scr_e32d9   name P…   created 2026-09-27T21:33:51Z  version 2
     scr_59ec7   name M…   created 2026-09-27T21:35:53Z  version 10
     scr_3bcf4   name P…   created 2026-09-28T10:54:05Z  version 2
  None carries an `approved` or `paired` field, and all three were created before pairing
  existed -> all three count as ALREADY APPROVED, as in rounds 9 and 10.
  OBSERVATION, not a failure: the file has shrunk (3079 -> 1089 bytes) because all three
  screens now have `showing` = null — nothing is on any TV. No screen was lost and none added.

1.9 THE PARKED ENGINEERING CREDENTIAL — BOTH TIERS RE-CHECKED
  /etc/crooks-os/credentials-parked/github_engineering_inbox_token.cred
  uid 0, mode 600, 292 bytes, mtime 27 Sep 01:55 — unchanged. NEVER opened or decrypted.
  Tier A (the unit's LoadCredentialEncrypted): shopify_client_id, shopify_client_secret,
          elevenlabs_api_key. github_engineering_inbox_token is NOT among them.
  Tier B (/etc/crooks-os/secrets/): gmail_token, local_cli_key, media_signing_key.
          github_engineering_inbox_token is NOT among them.
  credentials-parked/ is NEITHER tier. read_token() -> None, and every EngineeringInbox entry
  point returns NotConnected before any HTTP request.
  /etc/crooks-os/credentials/ holds exactly 3 .cred files.

1.10 THE OBJECTIVES FOLDER
  /var/lib/crooks-assistant/objectives/ holds 13 objective records (obj_*.json), plus
  displays.json, gaps.json and the one gaps backup.
  There is NO design/ folder yet, and no design/ file anywhere under it — as expected: round 12
  writes each objective's design there. The code before round 12 never reads that folder, so a
  rollback to 6a29e310 loses nothing.

1.11 THE LIVE-WORDS KEY (round 9, C-02)
  scripts/live_key_check.py --expiry, as root, from the review checkout, with the production
  venv interpreter. It reran itself inside a transient unit that loaded the service's own
  ElevenLabs credential and minted two live keys at ElevenLabs. Nothing on the server changed.
      ok     a fresh key opened one socket
      ok     the same key did not open a second socket: single-use
      wait   holding a fresh key unused for 16 minutes
      ok     a key held unused for 16 minutes opened nothing
      VERDICT: the key is what ElevenLabs says it is
      exit 0
  EXIT 0 -> C-02 IS SETTLED. It is not a leak finding and it does not block.

==============================================================================================
PREFLIGHT VERDICT: every check passed. Nothing on the server was changed by any of it.
==============================================================================================

### The 15 screenshots, read in full by the deploy owner

THE DEPLOY OWNER'S OWN INSPECTION OF ALL 15 SCREENSHOTS — read at the candidate SHA
====================================================================================
Every one of the 15 PNGs under crooks-assistant/docs/screens/r12-objectives/ was opened and
every word visible in it was read. Not a sample: all fifteen.

  phone-10-home            phone-11-project-sheet    phone-12-tasks-sheet
  phone-13-older-objective-sheet                     phone-20-project-card
  phone-21-tasks-card      tablet-01-project-card    tablet-02-tasks-card
  tablet-03-task-ticked    tablet-04-project-moved-on                tablet-05-home
  tablet-10-home           tablet-11-project-sheet   tablet-12-tasks-sheet
  tablet-13-older-objective-sheet

WHAT THEY CONTAIN
  - the owner's own first name in a greeting ("Morning, George.");
  - two staff first names against internal tasks (Rosa, Kit) and their two-letter initials;
  - one supplier name: "Northfield (factory)";
  - internal project names and stages: "AW drop" (Sampling / Approval / Production / Delivery),
    "Get the SS26 lookbook shot", "Rosa and Kit's tasks", "Shortlist three studios",
    "Book the studio", "Photograph the swatches", "Steam the AW samples",
    "Update the size chart";
  - a due date (2026-10-14) and history lines timestamped 09-29 02:01 attributed to
    "clive" or "owner";
  - UI chrome: Ask CLIVE, SPEECH OFFLINE, Done, Approve, Send, Mark done, New objective,
    "Investigate a customer enquiry — Paste their message. Read-only."

WHAT THEY DO NOT CONTAIN, in any of the fifteen
  no customer name, no customer message, no order number, no email address, no postal address,
  no postcode, no price or money amount, no tailnet address or hostname, no login, no API key,
  no token, no session id, no six-digit screen code, no QR code.
  The one customer-facing string present is the LABEL of an unused entry point
  ("Investigate a customer enquiry"), not a customer's data.

THE REPOSITORY IS PRIVATE — confirmed against GitHub at review time
  (crooksldn-pixel/clive: visibility PRIVATE, isPrivate true).

CONCLUSION ON ASSET-01
  The reviewer of the ASSET part rightly said it could not rule on bytes it was not sent, and
  labelled that CANNOT TELL / BLOCKS. The deploy owner has now read all fifteen images, which
  is strictly more than the text reviewer could have been given. Nothing in them leaks customer
  data or a credential. The staff first names and the supplier name are the owner's own
  business content, in the owner's own private repository. ASSET-01 is settled as a
  FOLLOW-UP at most, and does not block.

## E. Step 0 — the reviewer's API credits

Round 10 stopped here: its reviewer ran out of credits after 19 of 29 parts. This round the
same key file and the same harness were used to send one minimal request before anything else:

```
keyfile: ok (mode/owner/size checks passed)
status: completed
model: gpt-6-sol
usage: {"input_tokens": 18, "output_tokens": 5, "total_tokens": 23}
reply: OK
VERDICT: CREDITS OK
```

The key was never printed and never left the reviewer process. No dispatch failed for credits
at any point in this round: 106 of 106 dispatches were answered.

**Packet bytes and dispatches**

| | Packets | Bytes |
|---|---|---|
| The parts | 40 | 7,715,533 |
| The evidence packets | 40 | 10,270,886 |
| Follow-up packets, the parts | 18 | 2,385,216 |
| Follow-up packets, the evidence | 7 | 779,844 |
| **Total** | **105** | **21,151,479** |

One packet, `E01`, was dispatched twice: the first attempt was refused by the result schema
because the packet asked for two rulings under the same finding id (the intentional twin pair
`R9-A1b-F-05B-AVAIL`, one EVIDENCED and one LEFT). It was rebuilt with the two ids
disambiguated as `__EVIDENCED` and `__LEFT` and answered on the second attempt. That makes
106 dispatches against 105 packets.

## F. Steps 3, 4 and 5 — not run

Because the review returned blocking findings, and as the prompt requires:

- **Step 3, the staging copy and George's phone check 1: NOT RUN.** No staging clone was made,
  no transient unit was started, no `tailscale serve` handler was added, and George was not
  asked for anything. `stage.sh` was written and syntax-checked, retargeted to 361b0138 and
  extended with the three local-key commands (wrong key, empty header, no header) and the
  forged-forwarding-header check, and is ready for the round that does deploy.
- **Step 4, the deploy: NOT RUN.** `deploy.sh` was written and syntax-checked. It runs the
  candidate's own `make install` — which now also fails and rolls the unit back when
  `tailnet_self_check` fails after the restart — asserts the installed unit is byte-identical
  to the unit this review read, asserts the running `/proc/<MainPID>/cmdline` contains
  `--timeout-graceful-shutdown 10` and ends with `--no-proxy-headers`, holds the same MainPID
  for 30 s, and keeps round 10's ERR trap restoring both the code (to 6a29e310) and the saved
  unit on any failure. It was not executed.
- **Step 5, the TVs and George's tries: NOT RUN.** The TV pages were not reloaded, no YouTube
  key was asked for, offered or stored.

Because steps 3 and 4 did not run, four of the five DEPLOY-TIME evidence entries are still
open: `R9-A1a-F-05A` and `R9-A1b-F-05A` (the local-key check on the staging copy) and
`R9-A1a-F-05B-AVAIL-PREFLIGHT` and `R9-A1b-F-05B-AVAIL-PREFLIGHT` (the deploy's own asserts).
The fifth, `R9-C-C-02`, **is settled**: the live-words key check ran in the preflight, took
about 17 minutes, and exited 0 with `VERDICT: the key is what ElevenLabs says it is`.

## G. What the next fix round has to close

62 blocking findings, listed in section C, and 69 follow-ups, in sections A and B. They fall
into a few groups:

1. **The order-building family** (`app/families/order_create.py`) — a customer change does not
   clear the previous customer's confirmation email or their order-derived shipping address.
   Two confirmed leaks.
2. **The address family** (`app/families/address.py`) — silent truncation of the loaded
   address, submitted back whole.
3. **Records that are written without being flushed** — objectives designs, screen packing
   state, the unit file during install. Several data-loss findings of the same shape.
4. **Retention and housekeeping** — `TestSessions._prune` classifying by substring rather than
   by the session's real name; `_tidy_reports` following a symlink before the privacy check.
5. **47 findings that no reviewer could settle even with the file it named.** These are not
   claims that the code is wrong; they are claims that it cannot be shown right from the tree
   as it is split. The evidence index was built to end exactly this problem and it halved it
   — 52 entries came back REPAIRED — but it did not end it.

## H. How to repeat this round

Everything is under `/root/clive-activation/round-12/`:

| File | What it is |
|---|---|
| `step0-credits.txt` | the credits check and its output |
| `preflight.txt` | step 1 in full |
| `plan-parts.py` | the 40-part plan over the new range |
| `make-scopes.py` | one scope per part, with cross-split contracts |
| `build-packets.sh` | the packet builder, with round 10's pipe-free membership test |
| `build-evidence.py` | the 40 evidence packets from the index |
| `build-followup.py`, `build-ev-followup.py` | the one allowed follow-up round |
| `zero-omission-check.txt` | 378 of 378, verified from the built packets |
| `index-completeness.txt` | the index against round 10's record: 0 missing |
| `collected.json`, `followup-collected.json`, `final-tally.json` | every answer, and the labels |
| `stage.sh`, `deploy.sh` | written, syntax-checked, NOT run |
| `live-key-check.txt` | C-02, exit 0 |

The packet builder keeps the fix round 8 needed: the membership test is `grep -qxF` against a
file, never `echo | grep -q`, because that pipeline races on SIGPIPE under `pipefail` and
silently dropped files out of packets in an earlier round.

## I. The state everything was left in

```
=== FINAL STATE — nothing on the server was changed ===
production HEAD        : 6a29e31013b0b9e543d90434e14ed65deea1ce30
production dirty       : 0 entries
service                : active
MainPID                : 3068091
running cmdline        : /opt/crooks-os/crooks-assistant/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers 
installed unit sha256  : 3808af03c0bb0dcfc083ab519b33be3a82299ba92cc418a73678ba60c826722b
   preflight recorded  : 3808af03c0bb0dcfc083ab519b33be3a82299ba92cc418a73678ba60c826722b
.env sha256            : 0021c07d9c523d4112420537698eae50c51945f5966d3b0d01501def035693ce
   preflight recorded  : 0021c07d9c523d4112420537698eae50c51945f5966d3b0d01501def035693ce
.env mode/size         : 600 3513  (preflight: 600 3513)
gaps.json sha256       : 7f1a7f6b86a708d0b3872b12b8e75c52ed2a197122f01697359c4f798f8eaf48
   preflight recorded  : 7f1a7f6b86a708d0b3872b12b8e75c52ed2a197122f01697359c4f798f8eaf48
gaps backups           : 1 (preflight: 1)
parked credential      : 0 600 292 1790474150
   preflight recorded  : 0 600 292 1790474150 (2026-09-27 01:55:50 UTC) — IDENTICAL; never opened, never decrypted
/etc/crooks-os/credentials/ .cred files: 3 (preflight: 3)
tailscale serve :8443 handler present? 0 (must be 0 — no staging was raised)
transient stage unit?  inactive (must not be active)
reports dir entries    : 2 (preflight: 2)
displays.json screens  : 3, the same three ids
```

Read against the preflight's own recorded values: the production checkout is still 6a29e310
with nothing dirty, the service is up on its original MainPID, the installed unit, the `.env`
and the gap record are byte-identical, there is still exactly one gap backup, the parked
engineering credential is untouched and was never opened, no staging handler was added to
`tailscale serve`, and no transient staging unit exists.

## J. What can be deployed, and what needs vital repair

This section was added after the review, to answer two questions the findings list does not
answer on its own: is there anything here that *could* ship, and which repairs are vital.

### J.1 The test that matters: would deploying make it worse?

A finding that blocks under the ship rule is not automatically a reason to hold *this* deploy.
What matters operationally is whether the deploy **introduces** the defect or **newly exposes**
it, or whether it is already live at 6a29e310 and the hold changes nothing. Each of the 35
demonstrated blockers was therefore compared against production **at function level**, not file
level — a file can change for unrelated reasons while the defective function is untouched.

| | Count |
|---|---|
| Demonstrated blockers this range **introduces or newly exposes** | **33** |
| Demonstrated blockers **already live in production today** | **2** |
| Blockers that are unsettled doubt rather than a demonstrated defect | 27 |

The gate allow-list is the hinge for the worst of them. Production allows **36** tools; the
candidate allows **44**. The five newly exposed are `shopify_order_build`, `show_again`,
`close_screen`, `screen_off` and `screen_play`.

### J.2 Nothing in this range can be deployed

| Candidate | Verdict |
|---|---|
| `361b0138` (#57, the head) | **No** — 62 blocking, 33 of the 35 demonstrated ones newly introduced or exposed. |
| `3f05f5f0` (#56) | **No** — #57 changed only 3 files and 24 lines (`app.js`, `style.css`, `test_web.py`): the line over the cards and an amber→blue colour. Dropping it removes no blocker. |
| `547f652f` (#55, the round-10 fix round) | **No** — on a file-level check, 50 of the 62 blockers rest entirely on code already present there; and it has never been reviewed at that SHA, because the round-11 prompt was never run. Shipping it would be shipping an unreviewed SHA. |
| `81c78948` (#54) | **No** — round 10 reviewed it and it was blocked. |
| **Stay at `6a29e310`** | **Yes.** This is where production is, and it stays there. |

There is no smaller safe slice. The two customer-data leaks ride on `order_create.py`, which is
only reachable once `shopify_order_build` joins the allow-list — so the leaks arrive with the
"orders by voice" feature, not before it. But the objectives, screens and records defects are
spread across #51 through #56, so cutting the range does not isolate them.

### J.3 Two defects are ALREADY LIVE — holding the deploy does not protect against them

These are the most important lines in this document, because the decision not to deploy does
**nothing** about them. Both were checked function-by-function against production.

1. **`F/F-01` — customer order addresses can be silently shortened. LIVE NOW.**
   `app/families/address.py:_from_order` and `_stage` are **byte-identical at 6a29e310**.
   `_from_order` truncates every field it loads (`address1`/`address2`/`city` to `MAX_LINE`,
   `name` to 80, `postcode` to 12, `province_code` to 5, `country_code` to 2), those truncated
   values become the workspace's starting values, and `_stage` submits every field, not only the
   edited one. `_open` is a tablet command, not a gated model tool, so it is reachable today.
   Correcting a postcode on an order whose street is longer than `MAX_LINE` shortens that street
   on the customer's order, now.

2. **`O2/O2-N-01` — named test sessions can be pruned early. LIVE NOW.**
   `app/observability/session.py:_prune` is **byte-identical at 6a29e310**. It classifies a
   session by whether its slug *contains* `-always-on` rather than by the session's real name, so
   a manually named session such as `review-always-on-notes` is given the short automatic
   retention period and deleted early. `CROOKS_TEST_SESSION_ALWAYS=true` on production.

### J.4 The vital repairs, in the order they should be done

**Tier 0 — fix regardless of any deploy; these are live on production today.**

| | Finding | Where | Harm |
|---|---|---|---|
| 1 | `F/F-01` | `app/families/address.py` `_from_order`, `_stage` | loses customer address data |
| 2 | `O2/O2-N-01` | `app/observability/session.py` `_prune` | loses named test sessions early |

**Tier 1 — customer-data leaks; must close before this range can ship.**

| | Finding | Where | Harm |
|---|---|---|---|
| 3 | `S2Ba/F-01` | `order_create.py` `_choose_customer`, `_draft_input` | one customer's order confirmation to another customer's email |
| 4 | `S2Ba/F-02` | `order_create.py` `_from_order`, `_customer_by_id` | a new customer's order delivered to the previous customer's address |
| 5 | `S3/S3-03` | `app/displays/put.py`, `display_tools.py` | leak **and** exploitable |
| 6 | `S3/S3-01` | `app/displays/put.py` | order details to a replacement screen reusing a name |
| 7 | `S2b/S2b-01` | `compose.py` `_thread_sender` | a deceptive Reply-To sends the reply elsewhere |
| 8 | `S3P/S3P-NEW-01` | the screens pages | screen-side leak |
| 9 | `R9-B2-B2-02`, `R9-I-tests3-I-02` | evidence entries | leak / leak+loss |

Items 3 and 4 are gated behind `shopify_order_build`. **If the orders-by-voice feature were held
back — that one tool left off the allow-list — both leaks become unreachable.** That is the one
genuine partial-ship option in this range, and it is worth considering for the next round.

**Tier 2 — data loss in round-12's new code; close before shipping those features.**

`S6/S6-01`–`S6-04` (objectives: unflushed three-step write, silent 60-task and 12-people
truncation, a dropped due date, stage reorder losing completion state) · `O1/O1-01` (timeline
`_take_back` race) · `S3/S3-02` (`_commit` reports success after `NotFlushed`) · `S2a/S2a-01`
(`_off_target` lets a note land on the wrong order) · `S5/S5-01` (`install()` overwrites the unit
outside rollback protection) · `W2/W2-03` (out-of-order `openObjective` responses) ·
`O2/O2-N-02` (`_tidy_reports` follows a symlink before the privacy check).

**Tier 3 — the 27 unsettled blockers are a reviewability problem, not 27 defects.**

They block because the rule says unsettled is blocking, not because anyone showed the code is
wrong. The evidence index halved this problem — 52 of 100 entries came back REPAIRED — but did
not end it. The cheapest repair is not to the code: extend the index so these 27 carry the
bodies and tests that settle them, as was done for the 52 that closed.
