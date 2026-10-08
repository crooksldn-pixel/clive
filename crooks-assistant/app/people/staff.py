"""What a staff member may see and do, decided here and nowhere else (the owner, 1 October 2026).

His answers:
  sign-in   each on their own phone, with their own Tailscale login;
  see       everything but his own conversations with CLIVE;
  do        without his OK: mark orders packed, fulfil in Shopify (with tracking), send email
            replies, and adjust stock from their counts.

So a staff member's tools are every read except the owner's own records (his objectives, his
screens, the engineering loop), the work list, and exactly these writes, each confirmed on the
staff member's own card and recorded as theirs: the fulfilment and its tracking, a reply drafted
and sent, a stock adjustment. Nothing else that changes the shop or sends a message on CROOKS'
behalf is offered to them: a refund, a cancellation, a new email to anyone, a discount.

Routes are the same: the chat (in words), its cards, the work list and its page, and nothing of the
owner's own (Connections, his objectives and screens, his voice, the test session, the engineering
status).
"""

from __future__ import annotations

# Every read a staff member may call. Named one by one, like the gate's allow-list: a tool added
# later is the owner's until it is written here. Not the tools that work the owner's own screen
# (show_again, close_screen, the store-credit workspace): the team's page has no screen to work.
READS = frozenset({
    "shopify_find_order", "shopify_list_orders", "shopify_order_detail", "shopify_order_address",
    "shopify_find_customer", "shopify_customer_history", "shopify_product_info", "shopify_variant_search",
    "shopify_inventory", "shopify_sales_summary", "shopify_abandoned_checkouts", "shopify_discount_check",
    "commerce_query", "commerce_aggregate", "commerce_summary", "commerce_capabilities", "inventory_query",
    "email_query", "gmail_search", "gmail_read_thread", "gmail_find_in_email",
    "instagram_inbox", "instagram_thread", "instagram_comments",
    "people_list", "work_list", "work_note",
    # [routines, DEC-074] Their own named routines: a step is refused unless it is one of these tools
    # (app/work/routine_tools.py), and each step runs through their own authority like any call.
    "routine_list", "routine_note", "routine_run",
})

# The writes the owner allowed without his OK, by tool. Each is still staged as a card and made
# only when the staff member confirms it (app/routes/actions.py), and the engine records them as
# the one who did (app/actions/engine.py `caller`).
WRITES = frozenset({
    "shopify_order_fulfil",              # fulfil in Shopify
    "shopify_fulfillment_tracking_set",  # ... with its tracking number
    "gmail_draft_reply",                 # a reply, drafted
    "gmail_send_reply",                  # ... and sent
    "shopify_inventory_adjust",          # stock, from their count
})

TOOLS = READS | WRITES

# The same writes as the engine names them on a staged card (WriteSpec.operation), and the undo
# the engine offers straight after one of them: a staff member may take back their own change.
OPERATIONS = frozenset({
    "fulfillment_create", "fulfillment_tracking_set", "gmail_draft_reply", "gmail_send_reply", "inventory_set",
})
OPERATIONS_WITH_UNDO = OPERATIONS | frozenset(f"{operation}_undo" for operation in OPERATIONS)

# work_note actions only the owner may take: handing out jobs and setting up routines.
OWNER_WORK_ACTIONS = frozenset({"assign", "routine", "cancel"})

# Routes a staff member's request may reach, by method and path (a prefix ends in "/"). Every other
# route stays the owner's alone, by the door's one rule (app/main.py).
ROUTES: tuple[tuple[str, str], ...] = (
    ("POST", "/turn"),
    ("POST", "/actions/"),
    ("GET", "/actions/"),
    ("GET", "/today"),
    ("GET", "/today/"),
    ("POST", "/today/"),
)


def route_allowed(method: str, path: str) -> bool:
    method = str(method or "").upper()
    for allowed_method, allowed in ROUTES:
        if method != allowed_method:
            continue
        if allowed.endswith("/") and path.startswith(allowed):
            return True
        if path == allowed:
            return True
    return False


def may_call(tool_name: str) -> bool:
    from app.tools.registry import normalise_tool_name

    return normalise_tool_name(str(tool_name or "")) in TOOLS


def may_commit(operation: str) -> bool:
    """Whether a staff member's tap may make this staged change (the commit route asks), by the
    operation the engine recorded on the card."""
    return str(operation or "") in OPERATIONS_WITH_UNDO
