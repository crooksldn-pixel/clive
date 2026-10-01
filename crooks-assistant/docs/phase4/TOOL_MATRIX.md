# Tool matrix

Every registered tool, audited against §32 of the
Phase 4 brief. **Generated** by `experience/tool_matrix.py` — regenerate with
`make tool-matrix`; `tests/test_tool_matrix.py` fails if this file and the registries
disagree.

Every column is read from the thing that decides it. **DIRECTLY TESTED** means a test
RUNS the tool — its code hands the tool's name to the dispatcher, to `registry.invoke`
or to the SDK provider's callback (itself or through a helper of its own), or calls the
tool's handler — in code that runs: a test, a fixture a test asks for, a helper a test
calls, directly or through other helpers, or a class (a model double) such code makes —
and the file that does is cited. A dispatch in a helper no test calls is not counted.
Looking the tool up in the registry,
asking the gate to classify a call, drawing a card from a made-up tool call, a comment,
a docstring, an assertion about a list of names, a monkeypatch that replaces it, or the
provider's callback in a test that replaced the dispatcher behind it does not count, so a
tool whose unit tests pass but which no test runs is reported as
untested. **GOLDEN SCENARIO** is read the same way from the scenarios' code: a scenario
counts when it hands the tool to the model it scripts as a call's tool or to the
dispatcher, or taps a control that reads or stages it — never for naming it in an
assertion, a description, a label or a reply, or holding it in a constant, dict or list
it never hands on — and a write is reported as staged, because nothing in the fixture
world can apply one.
There are no intent families: every sentence is a model turn, so what a
sentence reaches is what the model calls. Tests are read as syntax trees and never run; nothing
here runs a tool, and nothing here can reach a mutation: the audit is a read of
registries and of source text, so it is safe against a shop it may not touch.

73 tools — 48 reads, 20 writes, 5 bulk.

## Tools

| Tool | Tier | Registered | Routable | Directly tested | Auth scope | Read/write | Staging | Verification | Visible UI | Error UI | Golden scenario |
|---|---|:-:|:-:|:-:|---|---|---|---|---|---|:-:|
| `batch_email_archive` | AMBER | yes | — | yes | — | batch | one proposal per member, through gmail_thread_archive | each member proven by gmail_thread_archive | the change's own card | — | — |
| `batch_email_drafts` | AMBER | yes | — | yes | — | batch | one proposal per member, through gmail_draft_new | each member proven by gmail_draft_new | the change's own card | — | — |
| `batch_email_send` | RED | yes | — | yes | — | batch | one proposal per member, through gmail_send_new | each member proven by gmail_send_new | the change's own card | — | — |
| `batch_order_tags_add` | AMBER | yes | — | yes | — | batch | one proposal per member, through shopify_order_tags_add | each member proven by shopify_order_tags_add | the change's own card | — | — |
| `batch_order_tags_remove` | AMBER | yes | — | yes | — | batch | one proposal per member, through shopify_order_tags_remove | each member proven by shopify_order_tags_remove | the change's own card | — | — |
| `close_screen` | GREEN | yes | yes | yes | none needed | read | — | — | — | — | — |
| `commerce_aggregate` | GREEN | yes | yes | yes | none needed | read | — | — | the read layer's cards | — | read |
| `commerce_capabilities` | GREEN | yes | yes | — | none needed | read | — | — | — | — | — |
| `commerce_query` | AMBER | yes | yes | yes | none needed | read | — | — | the read layer's cards | — | read |
| `commerce_summary` | GREEN | yes | yes | yes | read_orders, read_customers | read | — | — | presentation.py | — | — |
| `email_query` | AMBER | yes | yes | yes | none needed | read | — | — | the read layer's cards | — | read |
| `engineering_status` | GREEN | yes | yes | yes | none needed | read | — | — | — | — | — |
| `gmail_compose_fill` | GREEN | yes | yes | yes | https://www.googleapis.com/auth/gmail.compose | read | — | — | presentation.py | gmail | — |
| `gmail_compose_open` | GREEN | yes | yes | yes | https://www.googleapis.com/auth/gmail.compose | read | — | — | presentation.py | gmail | read |
| `gmail_draft_new` | AMBER | yes | yes | yes | https://www.googleapis.com/auth/gmail.compose | write | prepared from a fresh read, held as gmail_draft_new, tap_commit | a predicate over the re-read, after settling | the change's own card | gmail | staged, never applied |
| `gmail_draft_reply` | AMBER | yes | yes | yes | gmail.compose | write | prepared from a fresh read, held as gmail_draft_reply, tap_commit | a predicate over the re-read, after settling | the change's own card | gmail | — |
| `gmail_find_in_email` | AMBER | yes | yes | yes | none needed | read | — | — | — | gmail | — |
| `gmail_read_thread` | AMBER | yes | yes | yes | none needed | read | — | — | presentation.py | gmail | — |
| `gmail_search` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | gmail | read |
| `gmail_send_new` | RED | yes | yes | yes | https://www.googleapis.com/auth/gmail.compose | write | prepared from a fresh read, held as gmail_send_new, tap_commit | a predicate over the re-read, after settling | the change's own card | gmail | staged, never applied |
| `gmail_send_reply` | RED | yes | yes | yes | gmail.compose | write | prepared from a fresh read, held as gmail_send_reply, tap_commit | a predicate over the re-read, after settling | the change's own card | gmail | — |
| `gmail_thread_archive` | AMBER | yes | yes | yes | gmail.modify | write | prepared from a fresh read, held as gmail_thread_archive, tap_commit | the re-read must equal what was expected | the change's own card | gmail | — |
| `instagram_comments` | AMBER | yes | yes | yes | none needed | read | — | — | — | — | — |
| `instagram_inbox` | AMBER | yes | yes | yes | none needed | read | — | — | — | — | — |
| `instagram_thread` | AMBER | yes | yes | yes | none needed | read | — | — | — | — | — |
| `inventory_query` | GREEN | yes | yes | yes | none needed | read | — | — | the read layer's cards | — | read |
| `objective_list` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | — | — |
| `objective_note` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | — | — |
| `objective_open` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | — | — |
| `objective_show` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | — | — |
| `people_list` | AMBER | yes | yes | yes | none needed | read | — | — | — | — | — |
| `person_note` | GREEN | yes | yes | yes | none needed | read | — | — | — | — | — |
| `screen_list` | GREEN | yes | yes | yes | none needed | read | — | — | — | — | — |
| `screen_off` | GREEN | yes | yes | yes | none needed | read | — | — | — | — | — |
| `screen_pair` | GREEN | yes | yes | yes | none needed | read | — | — | — | — | — |
| `screen_play` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | — | — |
| `screen_remote` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | — | — |
| `screen_show` | AMBER | yes | yes | yes | none needed | read | — | — | — | — | — |
| `screen_video` | GREEN | yes | yes | yes | none needed | read | — | — | — | — | — |
| `shopify_abandoned_checkouts` | AMBER | yes | yes | yes | read_orders | read | — | — | presentation.py | shopify | read |
| `shopify_customer_history` | AMBER | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | read |
| `shopify_discount_check` | GREEN | yes | yes | yes | write_discounts | read | — | — | — | shopify | read |
| `shopify_discount_create` | RED | yes | yes | yes | write_discounts | write | prepared from a fresh read, held as discount_code_create, tap_commit | a predicate over the re-read | the change's own card | shopify | staged, never applied |
| `shopify_discount_open` | GREEN | yes | yes | yes | write_discounts | read | — | — | a workspace | shopify | read |
| `shopify_find_customer` | AMBER | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | — |
| `shopify_find_order` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | read |
| `shopify_fulfillment_tracking_set` | RED | yes | yes | yes | write_orders | write | prepared from a fresh read, held as fulfillment_tracking_set, tap_commit | a predicate over the re-read | the change's own card | shopify | — |
| `shopify_inventory` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | — |
| `shopify_inventory_adjust` | RED | yes | yes | yes | write_inventory | write | prepared from a fresh read, held as inventory_set, tap_commit | a predicate over the re-read | the change's own card | shopify | — |
| `shopify_list_orders` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | read |
| `shopify_order_add_custom_item` | RED | yes | yes | yes | write_order_edits | write | prepared from a fresh read, held as order_edit_add_custom_line, tap_commit | a predicate over the re-read | the change's own card | shopify | staged, never applied |
| `shopify_order_add_item` | RED | yes | yes | yes | write_order_edits | write | prepared from a fresh read, held as order_edit_add_line, tap_commit | a predicate over the re-read | the change's own card | shopify | staged, never applied |
| `shopify_order_address` | AMBER | yes | yes | — | none needed | read | — | — | — | shopify | — |
| `shopify_order_build` | AMBER | yes | yes | yes | write_draft_orders | read | — | — | a workspace | shopify | read |
| `shopify_order_cancel` | RED | yes | yes | yes | write_orders | write | prepared from a fresh read, held as order_cancel, tap_commit | a predicate over the re-read, after settling | the change's own card | shopify | — |
| `shopify_order_create` | RED | yes | yes | yes | write_draft_orders | write | prepared from a fresh read, held as draft_order_complete, tap_commit | a predicate over the re-read | the change's own card | shopify | staged, never applied |
| `shopify_order_detail` | AMBER | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | read |
| `shopify_order_fulfil` | RED | yes | yes | yes | write_orders | write | prepared from a fresh read, held as fulfillment_create, tap_commit | a predicate over the re-read | the change's own card | shopify | — |
| `shopify_order_note_append` | AMBER | yes | yes | yes | write_orders | write | prepared from a fresh read, held as order_note_append, tap_commit | the re-read must equal what was expected | the change's own card | shopify | — |
| `shopify_order_open` | AMBER | yes | yes | yes | write_draft_orders | read | — | — | a workspace | shopify | read |
| `shopify_order_shipping_address_set` | RED | yes | yes | yes | write_orders | write | prepared from a fresh read, held as order_shipping_address_set, tap_commit | a predicate over the re-read | the change's own card | shopify | — |
| `shopify_order_tags_add` | AMBER | yes | yes | yes | write_orders | write | prepared from a fresh read, held as order_tags_add, tap_commit | the re-read must equal what was expected | the change's own card | shopify | — |
| `shopify_order_tags_remove` | AMBER | yes | yes | yes | write_orders | write | prepared from a fresh read, held as order_tags_remove, tap_commit | the re-read must equal what was expected | the change's own card | shopify | — |
| `shopify_product_info` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | — |
| `shopify_refund_create` | RED | yes | yes | yes | write_orders | write | prepared from a fresh read, held as refund_create, tap_commit | a predicate over the re-read | the change's own card | shopify | — |
| `shopify_sales_summary` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | — |
| `shopify_store_credit` | AMBER | yes | yes | yes | write_store_credit_account_transactions | read | — | — | a workspace | shopify | read |
| `shopify_store_credit_add` | RED | yes | yes | yes | write_store_credit_account_transactions | write | prepared from a fresh read, held as store_credit_credit, tap_commit | a predicate over the re-read | the change's own card | shopify | staged, never applied |
| `shopify_variant_search` | GREEN | yes | yes | yes | write_order_edits | read | — | — | presentation.py | shopify | read |
| `show_again` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | — | — |
| `submit_engineering_request` | RED | yes | yes | yes | — | write | prepared from a fresh read, held as engineering_request_file, tap_commit | a predicate over the re-read | the change's own card | — | — |
| `work_list` | AMBER | yes | yes | yes | none needed | read | — | — | — | — | — |
| `work_note` | GREEN | yes | yes | yes | none needed | read | — | — | — | — | — |

### What cites each tool

| Tool | Reached by | Called in tests | Reached in scenarios |
|---|---|---|---|
| `batch_email_archive` | the model only | test_batch.py | — |
| `batch_email_drafts` | the model only | test_batch.py | — |
| `batch_email_send` | the model only | test_tool_boundary.py | — |
| `batch_order_tags_add` | the model only | test_batch.py, test_council_fixes.py | — |
| `batch_order_tags_remove` | the model only | test_batch.py | — |
| `close_screen` | family:put_away | test_r12_surfaces.py | — |
| `commerce_aggregate` | recipe:landing_sales, recipe:landing_products, family:analytics | test_analytics_tools.py, test_council_fixes.py, test_r13_timeline_names.py, test_working_sets.py | landing_products, landing_sales |
| `commerce_capabilities` | family:capability_reads | — | — |
| `commerce_query` | recipe:landing_orders, family:analytics | test_analytics_tools.py, test_council_fixes.py, test_n_plus_one.py, test_needs_reply_inbox.py, test_query_engine_p3.py, test_r11_families.py, test_r13_timeline_names.py, test_read_budget.py, test_working_sets.py | landing_orders, next_previous |
| `commerce_summary` | family:summary_surfaces | test_n_plus_one.py, test_summaries.py | — |
| `email_query` | recipe:landing_inbox, family:email_reads | test_council_fixes.py, test_graph.py, test_n_plus_one.py, test_needs_reply_inbox.py, test_r11_families.py, test_working_sets.py | graph_thread_to_order, landing_inbox, needs_reply |
| `engineering_status` | family:engineering | test_build_from_clive.py, test_capability_gaps.py, test_engineering_bridge.py, test_engineering_bridge_bounds.py, test_r11_engineering_off.py | — |
| `gmail_compose_fill` | family:email_compose | test_compose.py, test_r13_compose_edit.py | — |
| `gmail_compose_open` | family:email_compose | test_compose.py, test_compose_provenance.py | compose_dictated, compose_open, compose_send_instead, compose_send_spoken, compose_stage |
| `gmail_draft_new` | command:a tapped control, family:email_compose | test_compose_provenance.py, test_gmail_writes.py | compose_send_instead, compose_send_spoken, compose_stage |
| `gmail_draft_reply` | command:a tapped control, family:email_drafts | test_gmail_writes.py, test_reply_order_binding.py | — |
| `gmail_find_in_email` | family:email_reads | test_gaps.py, test_tool_args_redaction.py | — |
| `gmail_read_thread` | command:cursor:emails, family:email_reads | test_address.py, test_gmail_tools.py | — |
| `gmail_search` | recipe:landing_inbox, family:email_reads | test_gmail_tools.py, test_read_dedupe.py, test_tool_args_redaction.py | graph_thread_to_order, landing_inbox, needs_reply |
| `gmail_send_new` | command:a tapped control, family:email_compose | test_compose_provenance.py, test_gmail_writes.py, test_r13_new_email_order_content.py | compose_send_instead, compose_send_spoken |
| `gmail_send_reply` | command:a tapped control, family:email_sends | test_gmail_writes.py, test_reply_order_binding.py, test_tool_boundary.py | — |
| `gmail_thread_archive` | command:a tapped control, family:email_archive | test_gmail_writes.py | — |
| `instagram_comments` | family:instagram | test_instagram.py | — |
| `instagram_inbox` | family:instagram | test_instagram.py | — |
| `instagram_thread` | family:instagram | test_instagram.py | — |
| `inventory_query` | recipe:landing_products, family:product_reads | test_analytics_tools.py | landing_products |
| `objective_list` | family:objectives | test_displays.py, test_let_objectives_marked_complete_or_removed_2.py, test_tool_boundary.py | — |
| `objective_note` | family:objectives | test_let_objectives_marked_complete_or_removed_2.py, test_objective_design.py, test_objectives.py, test_tool_boundary.py | — |
| `objective_open` | family:objectives | test_objective_design.py, test_r13_objective_design_rules.py | — |
| `objective_show` | family:objectives | test_let_objectives_marked_complete_or_removed_2.py, test_objective_design.py | — |
| `people_list` | family:people | test_people.py | — |
| `person_note` | family:people | test_people.py | — |
| `screen_list` | family:screens | test_displays.py, test_r11_screens_server.py, test_screens_r10.py, test_tool_boundary.py | — |
| `screen_off` | family:screens | test_displays.py, test_screens_r10.py | — |
| `screen_pair` | family:screens | test_displays.py, test_r13_screens.py | — |
| `screen_play` | family:screens | test_screen_video.py | — |
| `screen_remote` | family:screens | test_displays.py | — |
| `screen_show` | family:screens | test_displays.py, test_r13_screens.py, test_screens_r10.py, test_tool_boundary.py | — |
| `screen_video` | family:screens | test_r11_screens_server.py, test_screen_video.py | — |
| `shopify_abandoned_checkouts` | family:abandoned_checkouts | test_abandoned.py, test_r11_families.py | abandoned_checkouts, abandoned_window |
| `shopify_customer_history` | command:cursor:customers, family:customer_reads | test_context.py, test_n_plus_one.py | customer_history, linked_entities, nav_home_landing, store_credit_give, store_credit_not_on_this_store |
| `shopify_discount_check` | recipe:discount_code, family:discount_create | test_discounts.py | discount_code_taken, discount_new_code |
| `shopify_discount_create` | command:a tapped control, family:discount_create | test_discounts.py | discount_new_code, discount_sentence_defers |
| `shopify_discount_open` | family:discount_create | test_discounts.py | discount_sentence_defers |
| `shopify_find_customer` | recipe:order_customer, family:customer_reads | test_r11_turn.py, test_shopify_tools.py, test_tool_args_redaction.py | — |
| `shopify_find_order` | family:order_reads | test_context.py, test_experience.py, test_expose_draft_order_s_payment_link_2.py, test_progressive_turn.py, test_r11_turn.py, test_r13_timeline_names.py, test_read_dedupe.py, test_shopify_tools.py, test_tap_reads_only.py, test_tool_args_redaction.py, test_tool_boundary.py, test_turn_boundary.py, test_write_walkthrough.py | back, customer_history, enrichment, graph_order_to_email, linked_entities, nav_branch_isolation, nav_home_landing, order_add_custom_item_sentence, order_add_item_ambiguous, order_add_item_cancelled, order_add_item_picker, order_add_item_sentence_defers, order_add_item_stale_picker, order_by_voice, order_lookup, recording_is_observability, split_branches, store_credit_give, store_credit_not_on_this_store, tabs, unsupported_edit |
| `shopify_fulfillment_tracking_set` | family:order_fulfil | test_tracking.py | — |
| `shopify_inventory` | family:product_reads | test_n_plus_one.py, test_shopify_tools.py, test_tool_args_redaction.py | — |
| `shopify_inventory_adjust` | family:inventory_set | test_inventory.py | — |
| `shopify_list_orders` | family:order_reads | test_shopify_tools.py | today_orders |
| `shopify_order_add_custom_item` | command:a tapped control, family:order_edit | test_order_custom_item.py | order_add_custom_item_sentence |
| `shopify_order_add_item` | command:a tapped control, family:order_edit | test_order_edit.py | order_add_item_picker, order_add_item_sentence_defers |
| `shopify_order_address` | family:order_reads | — | — |
| `shopify_order_build` | family:order_create | test_r12_orders.py | order_by_voice |
| `shopify_order_cancel` | family:order_cancel | test_cancel.py, test_tap_reads_only.py, test_tool_boundary.py, test_turn_boundary.py | — |
| `shopify_order_create` | command:a tapped control, family:order_create | test_order_create.py | order_by_voice, order_new |
| `shopify_order_detail` | command:cursor:orders, family:order_reads | test_capability_gaps.py, test_context.py, test_gate.py, test_progressive_turn.py, test_shopify_tools.py, test_tool_boundary.py, test_turn_authority_path.py, test_turn_boundary.py | back, customer_history, enrichment, graph_order_to_email, linked_entities, nav_branch_isolation, nav_home_landing, order_add_custom_item_sentence, order_add_item_ambiguous, order_add_item_cancelled, order_add_item_picker, order_add_item_sentence_defers, order_add_item_stale_picker, order_lookup, recording_is_observability, split_branches, store_credit_give, store_credit_not_on_this_store, tabs, unsupported_edit |
| `shopify_order_fulfil` | family:order_fulfil | test_fulfil.py | — |
| `shopify_order_note_append` | family:order_notes | test_actions.py, test_engine_hooks.py, test_r11_no_authority.py, test_r11_turn.py, test_r12_surfaces.py, test_turn_boundary.py | — |
| `shopify_order_open` | family:order_create | test_order_create.py | order_by_voice |
| `shopify_order_shipping_address_set` | command:a tapped control, family:order_address | test_address.py | — |
| `shopify_order_tags_add` | family:order_notes | test_tags.py | — |
| `shopify_order_tags_remove` | family:order_notes | test_tags_remove.py | — |
| `shopify_product_info` | family:product_reads | test_shopify_tools.py | — |
| `shopify_refund_create` | family:order_refund | test_refund.py | — |
| `shopify_sales_summary` | family:analytics | test_shopify_tools.py | — |
| `shopify_store_credit` | family:store_credit | test_r11_turn.py, test_r13_off_target.py, test_store_credit.py | store_credit_give, store_credit_not_on_this_store |
| `shopify_store_credit_add` | command:a tapped control, family:store_credit | test_r11_turn.py, test_r13_off_target.py, test_store_credit.py | store_credit_give |
| `shopify_variant_search` | recipe:order_line, recipe:order_add_item, family:order_edit | test_order_edit.py | order_add_item_ambiguous, order_add_item_cancelled, order_add_item_picker, order_add_item_sentence_defers |
| `show_again` | family:recall | test_r12_surfaces.py | — |
| `submit_engineering_request` | family:engineering | test_build_from_clive.py, test_capability_gaps.py, test_engineering_bridge.py, test_r11_engineering_off.py | — |
| `work_list` | family:work | test_work.py | — |
| `work_note` | family:work | test_work.py | — |

## What this matrix cannot vouch for

**no test calls it (2)**

`commerce_capabilities`, `shopify_order_address`

**no golden scenario reaches it (49)**

`batch_email_archive`, `batch_email_drafts`, `batch_email_send`, `batch_order_tags_add`, `batch_order_tags_remove`, `close_screen`, `commerce_capabilities`, `commerce_summary`, `engineering_status`, `gmail_compose_fill`, `gmail_draft_reply`, `gmail_find_in_email`, `gmail_read_thread`, `gmail_send_reply`, `gmail_thread_archive`, `instagram_comments`, `instagram_inbox`, `instagram_thread`, `objective_list`, `objective_note`, `objective_open`, `objective_show`, `people_list`, `person_note`, `screen_list`, `screen_off`, `screen_pair`, `screen_play`, `screen_remote`, `screen_show`, `screen_video`, `shopify_find_customer`, `shopify_fulfillment_tracking_set`, `shopify_inventory`, `shopify_inventory_adjust`, `shopify_order_address`, `shopify_order_cancel`, `shopify_order_fulfil`, `shopify_order_note_append`, `shopify_order_shipping_address_set`, `shopify_order_tags_add`, `shopify_order_tags_remove`, `shopify_product_info`, `shopify_refund_create`, `shopify_sales_summary`, `show_again`, `submit_engineering_request`, `work_list`, `work_note`

**nothing but the model reaches it (5)**

`batch_email_archive`, `batch_email_drafts`, `batch_email_send`, `batch_order_tags_add`, `batch_order_tags_remove`

**no card is drawn from it (18)**

`close_screen`, `commerce_capabilities`, `engineering_status`, `gmail_find_in_email`, `instagram_comments`, `instagram_inbox`, `instagram_thread`, `people_list`, `person_note`, `screen_list`, `screen_off`, `screen_pair`, `screen_show`, `screen_video`, `shopify_discount_check`, `shopify_order_address`, `work_list`, `work_note`

**no named error card (33)**

`batch_email_archive`, `batch_email_drafts`, `batch_email_send`, `batch_order_tags_add`, `batch_order_tags_remove`, `close_screen`, `commerce_aggregate`, `commerce_capabilities`, `commerce_query`, `commerce_summary`, `email_query`, `engineering_status`, `instagram_comments`, `instagram_inbox`, `instagram_thread`, `inventory_query`, `objective_list`, `objective_note`, `objective_open`, `objective_show`, `people_list`, `person_note`, `screen_list`, `screen_off`, `screen_pair`, `screen_play`, `screen_remote`, `screen_show`, `screen_video`, `show_again`, `submit_engineering_request`, `work_list`, `work_note`

## The rules the audit itself keeps

- **Read** in this matrix is the write boundary's word, not a promise that nothing
  changes: a read is a tool with no `WriteSpec` and no `BatchSpec`, so it is never
  staged, held for the owner's gesture or proven by a re-read, and it is what the read
  scheduler may run. `app/reads/scheduler.py::assert_reads_only` refuses a plan naming a
  write tool, in every lane, and `app/reads/dedupe.py` refuses to hold, join or reuse one.
  No read changes the shop or the inbox. These reads change what a screen shows: `screen_show` (puts a packing slip, an objective or a list on a screen, or clears it); `screen_off` (takes everything, or one pane, off a screen); `screen_play` (puts a video on a screen); `screen_video` (plays, pauses, mutes, skips or sets the volume of a screen's video); `screen_pair` (approves a newly named screen, which then leaves its pairing code); `close_screen` (closes what is on the owner's own screen and goes back to the orb).
- No arbitrary GraphQL from the model: the model reaches only the tools above, each
  of which builds its own document.
- Speculation may never write or commit: a prediction's tool is checked against the
  registry (`write is None and batch is None`) and then run through the same plan
  assertion.
- Unknown writes fail closed: `app/tools/gate.py` denies an unregistered tool and
  denies any mutation-shaped name without a complete `WriteSpec`.
- Nothing in this audit executed a tool, so no fixture and no shop was changed to
  produce it.
