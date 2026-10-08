"""What the assistant could already do, said in the same words as what is new (§29).

The capability FAMILY table was built for Phase 3's additions — order editing, discount codes,
store credit — and started empty, so `/health families` returned nothing and the settings
sheet's "What I can do" had nothing to say about the fourteen write operations and seventeen
read tools that already worked. A manifest that lists only the new things is not a manifest.

So every capability that exists today is registered here, one family per thing the owner would
name: reading orders, the inbox, the numbers, cancelling, refunding, fulfilling, tagging,
noting, changing an address, adjusting stock, drafting and sending email, archiving a thread.
Their states are DERIVED, not declared: `families.states()` reads the per-operation table
`runtime.capabilities()` already builds — which knows whether writes are switched off, whether
the scope is granted, and whether the store answered — so a family here says READ_ONLY when
changes are off and MISSING_SCOPE when Shopify has not granted the scope, without this file
knowing anything about either.

A read-only family has no operations to derive from, so it declares READY and means it: the
tool is registered, the client is bound, and `/health` reports separately whether Shopify and
Gmail are answering at all. Nothing here withholds a tool the model had before —
`runtime.withheld_by_family()` only withholds what is not READY, and everything in this file
is READY unless the operation table says otherwise.
"""

from __future__ import annotations

from app.capabilities.families import CapabilityFamily, register

# Shopify's own scope names, as SHOPIFY_SCOPES.md records them. Named per family so the
# settings sheet can tell the owner which one to grant when a write is blocked.
_ORDERS_W = ("write_orders",)
_INVENTORY_W = ("write_inventory",)
_GMAIL_COMPOSE = ("gmail.compose",)
_GMAIL_MODIFY = ("gmail.modify",)

FAMILIES = (
    # ------------------------------------------------------------------ reading
    CapabilityFamily(
        key="order_reads", label="Reading orders", area="orders",
        what="find an order, read it in full, its address, its items, its customer",
        tools=("shopify_find_order", "shopify_order_detail", "shopify_order_address", "shopify_list_orders"),
        state="READY", detail="ready",
    ),
    CapabilityFamily(
        key="customer_reads", label="Reading customers", area="customers",
        what="find a customer and what they have ordered before",
        tools=("shopify_find_customer", "shopify_customer_history"),
        state="READY", detail="ready",
    ),
    CapabilityFamily(
        key="product_reads", label="Reading products and stock", area="products",
        what="a product, its variants, what is in stock",
        tools=("shopify_product_info", "shopify_inventory", "inventory_query"),
        state="READY", detail="ready",
    ),
    CapabilityFamily(
        key="analytics", label="Sales and analysis", area="analytics",
        what="sales, best sellers, a period against the one before, orders waiting too long",
        tools=("commerce_query", "commerce_aggregate", "shopify_sales_summary"),
        state="READY", detail="ready",
    ),
    CapabilityFamily(
        key="email_reads", label="Reading email", area="email",
        what="search the inbox, read a thread, find who is waiting on a reply",
        tools=("gmail_search", "gmail_read_thread", "gmail_find_in_email", "email_query", "gmail_unsent"),
        state="READY", detail="ready",
    ),
    CapabilityFamily(
        key="capability_reads", label="What I can do", area="system",
        what="this list, and what changed since the last build",
        tools=("commerce_capabilities",),
        state="READY", detail="ready",
    ),
    # ------------------------------------------------------------------ changing
    CapabilityFamily(
        key="order_cancel", label="Cancelling an order", area="orders",
        what="cancel an order, with or without a refund, and say why",
        operations=("order_cancel",), tools=(), scopes=_ORDERS_W, state="READY",
    ),
    CapabilityFamily(
        key="order_refund", label="Refunding", area="orders",
        what="refund an order, in part or in full",
        operations=("refund_create",), scopes=_ORDERS_W, state="READY",
    ),
    CapabilityFamily(
        key="order_fulfil", label="Fulfilling and tracking", area="orders",
        what="mark an order fulfilled, and set or correct its tracking number",
        operations=("fulfillment_create", "fulfillment_tracking_set"), scopes=_ORDERS_W, state="READY",
    ),
    CapabilityFamily(
        key="order_address", label="Changing a shipping address", area="orders",
        what="correct the address on an order that has not gone out — tap Address and type it",
        operations=("order_shipping_address_set",), scopes=_ORDERS_W, state="READY",
        # Said out loud in the capability answer, because the owner asked how to type and
        # nothing on the screen or in the sentence could tell him (app/families/address.py).
        detail="the Address chip opens the address as fields, with the current one in them",
    ),
    CapabilityFamily(
        key="order_notes", label="Notes and tags", area="orders",
        what="add a note to an order, add or remove its tags",
        operations=("order_note_append", "order_tags_add", "order_tags_remove"), scopes=_ORDERS_W, state="READY",
    ),
    CapabilityFamily(
        key="inventory_set", label="Adjusting stock", area="products",
        what="set the stock of one variant at one location",
        operations=("inventory_set",), scopes=_INVENTORY_W, state="READY",
    ),
    CapabilityFamily(
        key="email_drafts", label="Drafting a reply", area="email",
        what="draft a reply to a thread, or a new message to a customer",
        operations=("gmail_draft_reply", "gmail_draft_new"), scopes=_GMAIL_COMPOSE, state="READY",
    ),
    CapabilityFamily(
        key="email_sends", label="Sending email", area="email",
        what="send a reply, or a new message to a customer, or a draft waiting in Gmail as it is",
        operations=("gmail_send_reply", "gmail_send_new", "gmail_send_draft"), scopes=_GMAIL_COMPOSE, state="READY",
    ),
    CapabilityFamily(
        key="email_archive", label="Archiving a thread", area="email",
        what="take a thread out of the inbox once it is dealt with",
        operations=("gmail_thread_archive",), scopes=_GMAIL_MODIFY, state="READY",
    ),
    # Ruling 27 (DEC-071): junk, singly or a set at once on one hold; never a customer's thread.
    CapabilityFamily(
        key="email_junk", label="Junking a thread", area="email",
        what="move a thread, or a set of threads at once, to Spam; never a customer's",
        operations=("gmail_thread_junk",), scopes=_GMAIL_MODIFY, state="READY",
    ),
)

for family in FAMILIES:
    register(family)
