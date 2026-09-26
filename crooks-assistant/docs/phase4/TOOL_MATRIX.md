# Tool matrix

Every registered tool and every routable intent family, audited against §32 of the
Phase 4 brief. **Generated** by `experience/tool_matrix.py` — regenerate with
`make tool-matrix`; `tests/test_tool_matrix.py` fails if this file and the registries
disagree.

Every column is read from the thing that decides it. **DIRECTLY TESTED** means a test
CALLS the tool — its code passes the tool's name to a call, or calls the tool's handler
— and the file that does is cited. A test that only mentions the tool, in a comment, a
docstring, an assertion about a list of names or a monkeypatch that replaces it, does
not count, so a tool whose unit tests pass but which no test calls is reported as
untested. An intent family is reached by routing a sentence to it rather than by a
call, so for a family the column is **NAMED IN TEST CODE**: a test's code, not a
comment or a docstring, names it. Tests are read as syntax trees and never run; nothing
here runs a tool, and nothing here can reach a mutation: the audit is a read of
registries and of source text, so it is safe against a shop it may not touch.

55 tools — 31 reads, 19 writes, 5 bulk — and 50 intent families.

## Tools

| Tool | Tier | Registered | Routable | Directly tested | Auth scope | Read/write | Staging | Verification | Visible UI | Error UI | Golden scenario |
|---|---|:-:|:-:|:-:|---|---|---|---|---|---|:-:|
| `batch_email_archive` | AMBER | yes | — | yes | — | batch | one proposal per member, through gmail_thread_archive | each member proven by gmail_thread_archive | the change's own card | — | — |
| `batch_email_drafts` | AMBER | yes | — | yes | — | batch | one proposal per member, through gmail_draft_new | each member proven by gmail_draft_new | the change's own card | — | — |
| `batch_email_send` | RED | yes | — | yes | — | batch | one proposal per member, through gmail_send_new | each member proven by gmail_send_new | the change's own card | — | — |
| `batch_order_tags_add` | AMBER | yes | — | yes | — | batch | one proposal per member, through shopify_order_tags_add | each member proven by shopify_order_tags_add | the change's own card | — | — |
| `batch_order_tags_remove` | AMBER | yes | — | yes | — | batch | one proposal per member, through shopify_order_tags_remove | each member proven by shopify_order_tags_remove | the change's own card | — | — |
| `commerce_aggregate` | GREEN | yes | yes | yes | none needed | read | — | — | the read layer's cards | — | yes |
| `commerce_capabilities` | GREEN | yes | yes | yes | none needed | read | — | — | — | — | — |
| `commerce_query` | AMBER | yes | yes | yes | none needed | read | — | — | the read layer's cards | — | yes |
| `commerce_summary` | GREEN | yes | yes | yes | read_orders, read_customers | read | — | — | — | — | — |
| `email_query` | AMBER | yes | yes | yes | none needed | read | — | — | the read layer's cards | — | yes |
| `engineering_status` | GREEN | yes | yes | yes | none needed | read | — | — | — | — | — |
| `gmail_compose_fill` | GREEN | yes | yes | yes | https://www.googleapis.com/auth/gmail.compose | read | — | — | presentation.py | gmail | — |
| `gmail_compose_open` | GREEN | yes | yes | yes | https://www.googleapis.com/auth/gmail.compose | read | — | — | presentation.py | gmail | — |
| `gmail_draft_new` | AMBER | yes | yes | yes | https://www.googleapis.com/auth/gmail.compose | write | prepared from a fresh read, held as gmail_draft_new, tap_commit | a predicate over the re-read, after settling | the change's own card | gmail | yes |
| `gmail_draft_reply` | AMBER | yes | yes | yes | gmail.compose | write | prepared from a fresh read, held as gmail_draft_reply, tap_commit | a predicate over the re-read, after settling | the change's own card | gmail | yes |
| `gmail_find_in_email` | AMBER | yes | yes | yes | none needed | read | — | — | — | gmail | — |
| `gmail_read_thread` | AMBER | yes | yes | yes | none needed | read | — | — | presentation.py | gmail | yes |
| `gmail_search` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | gmail | yes |
| `gmail_send_new` | RED | yes | yes | yes | https://www.googleapis.com/auth/gmail.compose | write | prepared from a fresh read, held as gmail_send_new, tap_commit | a predicate over the re-read, after settling | the change's own card | gmail | — |
| `gmail_send_reply` | RED | yes | yes | yes | gmail.compose | write | prepared from a fresh read, held as gmail_send_reply, tap_commit | a predicate over the re-read, after settling | the change's own card | gmail | — |
| `gmail_thread_archive` | AMBER | yes | yes | yes | gmail.modify | write | prepared from a fresh read, held as gmail_thread_archive, tap_commit | the re-read must equal what was expected | the change's own card | gmail | — |
| `inventory_query` | GREEN | yes | yes | yes | none needed | read | — | — | the read layer's cards | — | yes |
| `objective_list` | GREEN | yes | yes | yes | none needed | read | — | — | — | — | — |
| `objective_note` | GREEN | yes | yes | yes | none needed | read | — | — | — | — | — |
| `objective_open` | GREEN | yes | yes | yes | none needed | read | — | — | — | — | — |
| `objective_show` | GREEN | yes | yes | yes | none needed | read | — | — | — | — | — |
| `shopify_abandoned_checkouts` | AMBER | yes | yes | yes | read_orders | read | — | — | — | shopify | yes |
| `shopify_customer_history` | AMBER | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | yes |
| `shopify_discount_check` | GREEN | yes | yes | yes | write_discounts | read | — | — | — | shopify | yes |
| `shopify_discount_create` | RED | yes | yes | yes | write_discounts | write | prepared from a fresh read, held as discount_code_create, tap_commit | a predicate over the re-read | the change's own card | shopify | yes |
| `shopify_discount_open` | GREEN | yes | yes | yes | write_discounts | read | — | — | a workspace | shopify | — |
| `shopify_find_customer` | AMBER | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | yes |
| `shopify_find_order` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | yes |
| `shopify_fulfillment_tracking_set` | RED | yes | yes | yes | write_orders | write | prepared from a fresh read, held as fulfillment_tracking_set, tap_commit | a predicate over the re-read | the change's own card | shopify | — |
| `shopify_inventory` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | — |
| `shopify_inventory_adjust` | RED | yes | yes | yes | write_inventory | write | prepared from a fresh read, held as inventory_set, tap_commit | a predicate over the re-read | the change's own card | shopify | — |
| `shopify_list_orders` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | — |
| `shopify_order_add_item` | RED | yes | yes | yes | write_order_edits | write | prepared from a fresh read, held as order_edit_add_line, tap_commit | a predicate over the re-read | the change's own card | shopify | yes |
| `shopify_order_address` | AMBER | yes | yes | yes | none needed | read | — | — | — | shopify | — |
| `shopify_order_cancel` | RED | yes | yes | yes | write_orders | write | prepared from a fresh read, held as order_cancel, tap_commit | a predicate over the re-read, after settling | the change's own card | shopify | — |
| `shopify_order_create` | RED | yes | yes | yes | write_draft_orders | write | prepared from a fresh read, held as draft_order_complete, tap_commit | a predicate over the re-read | the change's own card | shopify | yes |
| `shopify_order_detail` | AMBER | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | yes |
| `shopify_order_fulfil` | RED | yes | yes | yes | write_orders | write | prepared from a fresh read, held as fulfillment_create, tap_commit | a predicate over the re-read | the change's own card | shopify | — |
| `shopify_order_note_append` | AMBER | yes | yes | yes | write_orders | write | prepared from a fresh read, held as order_note_append, tap_commit | the re-read must equal what was expected | the change's own card | shopify | yes |
| `shopify_order_open` | AMBER | yes | yes | yes | write_draft_orders | read | — | — | a workspace | shopify | — |
| `shopify_order_shipping_address_set` | RED | yes | yes | yes | write_orders | write | prepared from a fresh read, held as order_shipping_address_set, tap_commit | a predicate over the re-read | the change's own card | shopify | — |
| `shopify_order_tags_add` | AMBER | yes | yes | yes | write_orders | write | prepared from a fresh read, held as order_tags_add, tap_commit | the re-read must equal what was expected | the change's own card | shopify | — |
| `shopify_order_tags_remove` | AMBER | yes | yes | yes | write_orders | write | prepared from a fresh read, held as order_tags_remove, tap_commit | the re-read must equal what was expected | the change's own card | shopify | — |
| `shopify_product_info` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | — |
| `shopify_refund_create` | RED | yes | yes | yes | write_orders | write | prepared from a fresh read, held as refund_create, tap_commit | a predicate over the re-read | the change's own card | shopify | — |
| `shopify_sales_summary` | GREEN | yes | yes | yes | none needed | read | — | — | presentation.py | shopify | — |
| `shopify_store_credit` | AMBER | yes | yes | yes | write_store_credit_account_transactions | read | — | — | a workspace | shopify | — |
| `shopify_store_credit_add` | RED | yes | yes | yes | write_store_credit_account_transactions | write | prepared from a fresh read, held as store_credit_credit, tap_commit | a predicate over the re-read | the change's own card | shopify | yes |
| `shopify_variant_search` | GREEN | yes | yes | yes | write_order_edits | read | — | — | presentation.py | shopify | yes |
| `submit_engineering_request` | RED | yes | yes | yes | — | write | prepared from a fresh read, held as engineering_request_file, tap_commit | a predicate over the re-read | the change's own card | — | — |

### What cites each tool

| Tool | Reached by | Called in tests | Named in scenarios |
|---|---|---|---|
| `batch_email_archive` | the model only | test_batch.py | — |
| `batch_email_drafts` | the model only | test_batch.py, test_flows.py | — |
| `batch_email_send` | the model only | test_gaps.py | — |
| `batch_order_tags_add` | the model only | test_batch.py, test_council_fixes.py, test_flows.py, test_memory.py, test_read_budget.py, test_reads.py | — |
| `batch_order_tags_remove` | the model only | test_batch.py | — |
| `commerce_aggregate` | recipe:navigation_back, recipe:navigation_home, recipe:best_sellers_period, recipe:sales_breakdown_period, recipe:landing_sales, recipe:landing_products, recipe:ui_area_workspace, family:analytics | test_analytics_present.py, test_analytics_tools.py, test_council_fixes.py, test_experience_analyser.py, test_flows.py, test_progressive.py, test_scene_payload.py, test_scenes.py, test_working_sets.py | back, landing_products, landing_sales, nav_branch_isolation, nav_click_path, nav_home_landing |
| `commerce_capabilities` | family:capability_reads | test_analytics_tools.py | — |
| `commerce_query` | recipe:navigation_back, recipe:navigation_home, recipe:order_list_period, recipe:delayed_orders, recipe:landing_orders, recipe:order_latest, recipe:unfulfilled_orders, recipe:international_waiting_orders, recipe:ui_area_workspace, family:analytics | test_analytics_present.py, test_analytics_tools.py, test_council_fixes.py, test_flows.py, test_n_plus_one.py, test_navigation.py, test_needs_reply_inbox.py, test_query_engine_p3.py, test_read_budget.py, test_read_dedupe.py, test_recorder.py, test_scene_payload.py, test_scenes.py, test_working_sets.py | back, landing_orders, nav_branch_isolation, nav_click_path, nav_home_landing, next_previous, query_international_waiting, query_language.py, query_undelivered, spoken_latest, today_orders |
| `commerce_summary` | recipe:returning_customers, recipe:returning_customers_before, recipe:orders_attention, recipe:order_list_summary, family:summary_surfaces | test_n_plus_one.py, test_summaries.py | — |
| `email_query` | recipe:navigation_back, recipe:navigation_home, recipe:needs_reply, recipe:landing_inbox, recipe:ui_area_workspace, family:email_reads | test_council_fixes.py, test_flows.py, test_graph.py, test_n_plus_one.py, test_needs_reply_inbox.py, test_scene_payload.py, test_scene_planner.py, test_scenes.py, test_working_sets.py | back, landing_inbox, nav_branch_isolation, nav_click_path, nav_home_landing, needs_reply |
| `engineering_status` | family:engineering | test_build_from_clive.py, test_capability_gaps.py, test_engineering_bridge.py, test_gate.py | — |
| `gmail_compose_fill` | family:email_compose | test_compose.py | — |
| `gmail_compose_open` | family:email_compose | test_compose.py | — |
| `gmail_draft_new` | command:a tapped control, family:email_compose | test_compose.py, test_gmail_writes.py | compose.py |
| `gmail_draft_reply` | command:a tapped control, family:email_drafts | test_action_state.py, test_compose.py, test_email_workspace.py, test_experience_analyser.py, test_gmail_writes.py, test_recorder.py | graph.py |
| `gmail_find_in_email` | family:email_reads | test_gaps.py, test_scenes.py | — |
| `gmail_read_thread` | recipe:navigation_back, recipe:working_set_next, recipe:working_set_previous, recipe:order_email_reply, recipe:order_email_waiting, command:cursor:emails, family:email_reads | test_address.py, test_analyser.py, test_entities.py, test_gate.py, test_gmail_tools.py, test_graph.py, test_presentation.py, test_progressive_states.py, test_recorder.py, test_registry.py, test_scene_planner.py, test_scenes.py, test_watch_lines.py, test_workspaces.py | back, graph.py, graph_compound_reply, graph_no_email_about_this_order, graph_order_to_email, nav_branch_isolation, nav_click_path, nav_next_position, next_previous |
| `gmail_search` | recipe:navigation_back, recipe:navigation_home, recipe:inbox_state, recipe:landing_inbox, recipe:order_email_reply, recipe:order_email_waiting, recipe:ui_area_workspace, family:email_reads | test_analyser.py, test_entities.py, test_gate.py, test_gmail_tools.py, test_observability.py, test_presentation.py, test_progressive.py, test_progressive_states.py, test_provider.py, test_read_dedupe.py, test_reads.py, test_registry.py, test_routes.py, test_scene_planner.py, test_scenes.py, test_split.py, test_workspaces.py | back, graph.py, graph_compound_reply, graph_no_email_about_this_order, graph_order_to_email, landing_inbox, nav_branch_isolation, nav_click_path, nav_home_landing |
| `gmail_send_new` | command:a tapped control, family:email_compose | test_compose.py, test_gmail_writes.py | — |
| `gmail_send_reply` | command:a tapped control, family:email_sends | test_actions_routes.py, test_compose.py, test_email_workspace.py, test_gmail_writes.py, test_owner_feedback.py, test_watch_lines.py | — |
| `gmail_thread_archive` | command:a tapped control, family:email_archive | test_action_state.py, test_council_fixes.py, test_email_workspace.py, test_experience_analyser.py, test_gmail_writes.py | — |
| `inventory_query` | recipe:navigation_back, recipe:navigation_home, recipe:stock_cover_analysis, recipe:landing_products, recipe:ui_area_workspace, family:product_reads | test_analytics_present.py, test_analytics_tools.py, test_flows.py | back, landing_products, nav_branch_isolation, nav_click_path, nav_home_landing |
| `objective_list` | family:objectives | test_objectives.py | — |
| `objective_note` | family:objectives | test_objectives.py | — |
| `objective_open` | family:objectives | test_objectives.py | — |
| `objective_show` | family:objectives | test_objectives.py | — |
| `shopify_abandoned_checkouts` | recipe:abandoned_checkouts, family:abandoned_checkouts | test_abandoned.py | abandoned_checkouts, abandoned_window |
| `shopify_customer_history` | recipe:navigation_back, recipe:working_set_next, recipe:working_set_previous, recipe:customer_history_lookup, recipe:customer_purchase_lookup, recipe:customer_workspace, command:cursor:customers, family:customer_reads | test_anticipation.py, test_branches.py, test_context.py, test_entities.py, test_n_plus_one.py, test_observability.py, test_reads.py, test_workspaces.py | back, customer_history, nav_branch_isolation, nav_click_path, nav_next_position, next_previous |
| `shopify_discount_check` | recipe:discount_code, family:discount_create | test_discounts.py | discount_code_taken, discount_new_code |
| `shopify_discount_create` | command:a tapped control, family:discount_create | test_discounts.py | discounts.py |
| `shopify_discount_open` | family:discount_create | test_discounts.py | — |
| `shopify_find_customer` | recipe:customer_purchase_lookup, recipe:order_customer, recipe:customer_workspace, family:customer_reads | test_entities.py, test_gate.py, test_observability.py, test_observability_redaction.py, test_presentation.py, test_reads.py, test_scenes.py, test_shopify_tools.py, test_workspaces.py | order_new, order_new_ambiguous |
| `shopify_find_order` | recipe:order_lookup, recipe:order_status_lookup, recipe:order_address_lookup, family:order_reads | test_actions_routes.py, test_analyser.py, test_anticipation.py, test_entities.py, test_observability.py, test_presentation.py, test_progressive.py, test_provider.py, test_read_dedupe.py, test_reads.py, test_registry.py, test_routes.py, test_scenes.py, test_shopify_tools.py | enrichment, full_address, graph.py, order_lookup |
| `shopify_fulfillment_tracking_set` | family:order_fulfil | test_tracking.py | — |
| `shopify_inventory` | family:product_reads | test_n_plus_one.py, test_observability.py, test_presentation.py, test_scenes.py, test_shopify_tools.py | — |
| `shopify_inventory_adjust` | family:inventory_set | test_inventory.py | — |
| `shopify_list_orders` | family:order_reads | test_gate.py, test_presentation.py, test_progressive.py, test_progressive_states.py, test_provider.py, test_scene_planner.py, test_scenes.py, test_session.py, test_shopify_tools.py | — |
| `shopify_order_add_item` | command:a tapped control, family:order_edit | test_order_edit.py | order_edit.py |
| `shopify_order_address` | family:order_reads | test_gaps.py, test_operations.py, test_scenes.py, test_watch_lines.py | — |
| `shopify_order_cancel` | family:order_cancel | test_cancel.py, test_read_budget.py | — |
| `shopify_order_create` | command:a tapped control, family:order_create | test_order_create.py | commerce.py |
| `shopify_order_detail` | recipe:navigation_back, recipe:working_set_next, recipe:working_set_previous, recipe:order_lookup, recipe:order_status_lookup, recipe:order_address_lookup, recipe:order_reopen, recipe:customer_history_lookup, recipe:order_tab_show, recipe:order_latest, recipe:order_email_reply, recipe:order_email_waiting, recipe:customer_workspace, command:cursor:orders, family:order_reads | test_actions.py, test_analyser.py, test_anticipation.py, test_attention.py, test_capability_gaps.py, test_context.py, test_entities.py, test_gate.py, test_memory.py, test_observability_redaction.py, test_presentation.py, test_progressive.py, test_read_dedupe.py, test_reads.py, test_routes.py, test_scene_planner.py, test_scenes.py, test_shopify_tools.py, test_workspaces.py | back, customer_history, enrichment, full_address, graph.py, graph_compound_reply, graph_no_email_about_this_order, graph_order_to_email, nav_branch_isolation, nav_click_path, nav_next_position, next_previous, order_lookup, repeat_order, spoken_latest, spoken_tab |
| `shopify_order_fulfil` | family:order_fulfil | test_fulfil.py | — |
| `shopify_order_note_append` | family:order_notes | test_actions.py, test_analyser.py, test_anticipation.py, test_branches.py, test_engine_hooks.py, test_fastpath.py, test_memory.py, test_observability.py, test_presentation.py, test_read_budget.py, test_read_dedupe.py, test_reads.py | scenarios.py |
| `shopify_order_open` | family:order_create | test_order_create.py | — |
| `shopify_order_shipping_address_set` | command:a tapped control, family:order_address | test_address.py, test_address_typing.py | — |
| `shopify_order_tags_add` | family:order_notes | test_council_fixes.py, test_tags.py | — |
| `shopify_order_tags_remove` | family:order_notes | test_tags_remove.py | — |
| `shopify_product_info` | family:product_reads | test_observability.py, test_reads.py, test_shopify_tools.py | — |
| `shopify_refund_create` | family:order_refund | test_refund.py | — |
| `shopify_sales_summary` | family:analytics | test_presentation.py, test_scenes.py, test_shopify_tools.py | — |
| `shopify_store_credit` | family:store_credit | test_store_credit.py | — |
| `shopify_store_credit_add` | command:a tapped control, family:store_credit | test_store_credit.py | commerce.py |
| `shopify_variant_search` | recipe:order_line, recipe:order_add_item, family:order_edit | test_order_edit.py | order_add_item_ambiguous, order_add_item_cancelled, order_add_item_picker |
| `submit_engineering_request` | family:engineering | test_build_from_clive.py, test_capability_gaps.py, test_engineering_bridge.py, test_gate.py | — |

## Intent families

| Family | For | Recipe | Reads | Serves mutation words | Named in test code | Golden scenario |
|---|---|---|---|:-:|:-:|:-:|
| `working_set_next` | work | working_set_next | `shopify_order_detail`, `shopify_customer_history`, `gmail_read_thread` | — | yes | yes |
| `working_set_previous` | work | working_set_previous | `shopify_order_detail`, `shopify_customer_history`, `gmail_read_thread` | — | yes | yes |
| `navigation_back` | work | navigation_back | `shopify_order_detail`, `shopify_customer_history`, `gmail_read_thread`, `commerce_query`, `email_query`, `gmail_search`, `commerce_aggregate`, `inventory_query` | — | yes | yes |
| `navigation_home` | work | navigation_home | `commerce_query`, `email_query`, `gmail_search`, `commerce_aggregate`, `inventory_query` | — | — | yes |
| `capability_delta` | capability | capability_delta | — | — | yes | yes |
| `capability_summary` | capability | capability_summary | — | — | yes | yes |
| `order_lookup` | work | order_lookup | `shopify_find_order`, `shopify_order_detail` | — | yes | yes |
| `order_list_period` | work | order_list_period | `commerce_query` | — | yes | yes |
| `order_reopen` | work | order_reopen | `shopify_order_detail` | — | yes | yes |
| `customer_history_lookup` | work | customer_history_lookup | `shopify_order_detail`, `shopify_customer_history` | — | yes | yes |
| `order_status_lookup` | work | order_status_lookup | `shopify_find_order`, `shopify_order_detail` | — | yes | — |
| `order_address_lookup` | work | order_address_lookup | `shopify_find_order`, `shopify_order_detail` | — | yes | yes |
| `customer_purchase_lookup` | work | customer_purchase_lookup | `shopify_find_customer`, `shopify_customer_history` | — | yes | — |
| `best_sellers_period` | work | best_sellers_period | `commerce_aggregate` | — | yes | — |
| `sales_breakdown_period` | work | sales_breakdown_period | `commerce_aggregate` | — | yes | — |
| `delayed_orders` | work | delayed_orders | `commerce_query` | — | yes | yes |
| `stock_cover_analysis` | work | stock_cover_analysis | `inventory_query` | — | yes | — |
| `needs_reply` | work | needs_reply | `email_query` | — | yes | yes |
| `inbox_state` | work | inbox_state | `gmail_search` | — | yes | — |
| `abandoned_checkouts` | work | abandoned_checkouts | `shopify_abandoned_checkouts` | — | yes | yes |
| `email_compose_any` | work | email_compose_any | — | yes | yes | yes |
| `draft_send_instead` | work | draft_send_instead | — | yes | yes | yes |
| `compose_rewrite` | work | compose_rewrite | — | yes | yes | — |
| `discount_code` | work | discount_code | `shopify_discount_check` | yes | yes | yes |
| `interaction_stop` | status | interaction_stop | — | — | yes | — |
| `greeting` | status | greeting | — | — | yes | — |
| `assistant_status` | status | assistant_status | — | — | yes | — |
| `landing_orders` | work | landing_orders | `commerce_query` | — | yes | yes |
| `landing_inbox` | work | landing_inbox | `email_query`, `gmail_search` | — | yes | yes |
| `landing_sales` | work | landing_sales | `commerce_aggregate` | — | — | yes |
| `landing_products` | work | landing_products | `commerce_aggregate`, `inventory_query` | — | yes | yes |
| `order_tab_show` | work | order_tab_show | `shopify_order_detail` | — | yes | yes |
| `order_latest` | work | order_latest | `commerce_query`, `shopify_order_detail` | — | yes | yes |
| `branch_switch` | work | branch_switch | — | — | yes | yes |
| `order_new` | work | order_customer | `shopify_find_customer` | yes | yes | yes |
| `order_new_line` | work | order_line | `shopify_variant_search` | — | yes | — |
| `order_add_item` | work | order_add_item | `shopify_variant_search` | — | yes | yes |
| `order_email_draft` | work | order_email_reply | `shopify_order_detail`, `gmail_search`, `gmail_read_thread` | — | yes | yes |
| `order_email_waiting` | work | order_email_waiting | `shopify_order_detail`, `gmail_search`, `gmail_read_thread` | — | yes | yes |
| `owner_feedback` | work | owner_feedback | — | yes | yes | — |
| `unfulfilled_orders` | work | unfulfilled_orders | `commerce_query` | — | yes | yes |
| `international_orders` | work | international_waiting_orders | `commerce_query` | — | yes | yes |
| `ui_semantics` | work | ui_semantics | — | yes | yes | — |
| `screen_state` | work | screen_state | — | yes | yes | — |
| `returning_customers` | work | returning_customers | `commerce_summary` | — | yes | — |
| `returning_customers_before` | work | returning_customers_before | `commerce_summary` | — | yes | — |
| `orders_attention` | work | orders_attention | `commerce_summary` | — | yes | — |
| `order_list_summary` | work | order_list_summary | `commerce_summary` | — | yes | — |
| `customer_workspace` | work | customer_workspace | `shopify_find_customer`, `shopify_customer_history`, `shopify_order_detail` | — | yes | — |
| `ui_area_workspace` | work | ui_area_workspace | `commerce_query`, `commerce_aggregate`, `inventory_query`, `email_query`, `gmail_search` | — | yes | — |

## What this matrix cannot vouch for

**no test calls it (0)**

none

**no golden scenario names it (35)**

`batch_email_archive`, `batch_email_drafts`, `batch_email_send`, `batch_order_tags_add`, `batch_order_tags_remove`, `commerce_capabilities`, `commerce_summary`, `engineering_status`, `gmail_compose_fill`, `gmail_compose_open`, `gmail_find_in_email`, `gmail_send_new`, `gmail_send_reply`, `gmail_thread_archive`, `objective_list`, `objective_note`, `objective_open`, `objective_show`, `shopify_discount_open`, `shopify_fulfillment_tracking_set`, `shopify_inventory`, `shopify_inventory_adjust`, `shopify_list_orders`, `shopify_order_address`, `shopify_order_cancel`, `shopify_order_fulfil`, `shopify_order_open`, `shopify_order_shipping_address_set`, `shopify_order_tags_add`, `shopify_order_tags_remove`, `shopify_product_info`, `shopify_refund_create`, `shopify_sales_summary`, `shopify_store_credit`, `submit_engineering_request`

**nothing but the model reaches it (5)**

`batch_email_archive`, `batch_email_drafts`, `batch_email_send`, `batch_order_tags_add`, `batch_order_tags_remove`

**no card is drawn from it (11)**

`commerce_capabilities`, `commerce_summary`, `engineering_status`, `gmail_find_in_email`, `objective_list`, `objective_note`, `objective_open`, `objective_show`, `shopify_abandoned_checkouts`, `shopify_discount_check`, `shopify_order_address`

**no named error card (17)**

`batch_email_archive`, `batch_email_drafts`, `batch_email_send`, `batch_order_tags_add`, `batch_order_tags_remove`, `commerce_aggregate`, `commerce_capabilities`, `commerce_query`, `commerce_summary`, `email_query`, `engineering_status`, `inventory_query`, `objective_list`, `objective_note`, `objective_open`, `objective_show`, `submit_engineering_request`

**intent families with no scenario (20)**

`order_status_lookup`, `customer_purchase_lookup`, `best_sellers_period`, `sales_breakdown_period`, `stock_cover_analysis`, `inbox_state`, `compose_rewrite`, `interaction_stop`, `greeting`, `assistant_status`, `order_new_line`, `owner_feedback`, `ui_semantics`, `screen_state`, `returning_customers`, `returning_customers_before`, `orders_attention`, `order_list_summary`, `customer_workspace`, `ui_area_workspace`

## The rules the audit itself keeps

- Reads never mutate: `app/reads/scheduler.py::assert_reads_only` refuses a plan
  naming a write tool, in every lane, and `app/reads/dedupe.py` refuses to hold,
  join or reuse one.
- No arbitrary GraphQL from the model: the model reaches only the tools above, each
  of which builds its own document.
- Speculation may never write or commit: a prediction's tool is checked against the
  registry (`write is None and batch is None`) and then run through the same plan
  assertion.
- Unknown writes fail closed: `app/tools/gate.py` denies an unregistered tool and
  denies any mutation-shaped name without a complete `WriteSpec`.
- Nothing in this audit executed a tool, so no fixture and no shop was changed to
  produce it.
