"""Making an order from nothing (brief §11): a workspace, a draft, and one reviewed complete.

"Create an order for Poppy De-Witt" was refused all through Phase 2, and the reason it is
hard is not the mutation — it is that an order has about nine facts in it and a conversation
is the wrong instrument for collecting nine facts. Phase 2's shape would have been: who is
it for? what is on it? how many? is it paid? — four round trips to a language model, each
one a place to mishear a name, and at the end a change proposed from what the model was
holding in its head.

So the shape here is a WORKSPACE, not a questionnaire:

    "create an order for Poppy"   →  shopify_order_open    a read: which customer is that?
    "add a hoodie, 10% off it"    →  shopify_order_build   the same card, changed
    typing, tapping               →  order.field/.choose/.additem
    Prepare                       →  draftOrderCreate      Shopify prices a DRAFT
    the hold on the card          →  draftOrderComplete    the one mutation

Round 12 (the owner, 29 September: "it couldn't add the item, or a custom item for that
matter, it couldn't add a line discount or percent discount") is why the middle line exists.
Until then the model could OPEN a workspace and nothing else: an item it was given was typed
into the "Add an item" field and never added, and every later change was a tap. Now each
spoken change is one `shopify_order_build` call that changes the Mac's copy and redraws the
same card: a catalogue item from words, a SKU or a variant a search returned; a custom item
with the owner's own title and price; a quantity; a line taken off; a discount on a line or
on the whole order, as a percentage or an amount; the postage, the note, the customer, where
it goes. And an order can be opened FROM another order ("the customer who ordered the black
hoodie to SL4 — a new one in the next size up"): its customer, its delivery address and the
next size of its item, worked out from the product's own sizes (app/families/_sizes.py).

Five things about it are deliberate.

**The draft is the reviewable intermediate, and that is the whole reason to use it.** PREPARE
runs `draftOrderCreate`, which makes a draft order: a real object, visible in Admin, priced
by Shopify, for which nobody is charged and which is not an order. So every number on the
card the owner holds — the line prices, the discounts, the postage, the total — is Shopify's
own arithmetic on the thing about to become the order, and not ours and never the model's.
And the draft Shopify made is checked against the card before the card is offered — the same
lines, quantities and discounts, the same customer, confirmation address, delivery address and
postage — or nothing is offered at all; the hold completes it only while it still says all of
that, and the order it made is held to the card once more afterwards.

**An ambiguous customer is refused, not guessed.** Two people called Jones is the commonest
real case, and the wrong one is a stranger's order with somebody else's address on it. So
the read finds the candidates, the workspace names them, and the button that would prepare
anything stays off until one of them is chosen. The same rule applies to an item: four
hoodies match "hoodie", none of them is added, and the four are offered as a choice.

**Nothing that reaches the mutation comes from the tablet.** The tablet posts a workspace id,
a field name and characters, or the key of a row the Mac drew. The variant ids, the prices,
the customer id, the postage and the payment state are read and built on the Mac from the
Mac's own copy of the workspace. A custom line's price is the one exception to "read, never
said", because the catalogue has no price for a thing it does not sell: it is the owner's
figure, bounded, and on the card he holds.

**The order is never created because the model thinks it has enough.** `shopify_order_create`
refuses to prepare a workspace `_blocked` says is not ready, whoever asks, and it only ever
PREPARES: the completion is the owner's hold.

**A card makes one order.** Once the hold has made it — or once the completion has left for
Shopify and no answer came back — the card IS that order: drawn with its number, its fields and
buttons gone, and every way back into building it (a spoken change, a tap, Prepare, "bring it
back") refused with the order's number (`finished`). Anything more is a new order. Until round
12's independent check the card stayed "not created" with Prepare live after the hold, and the
next "now add a cap to it" made a second draft of the same order, which a second hold made.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import re
from typing import Any

from app.actions.models import Observed, Prepared
from app.capabilities.families import CapabilityFamily
from app.capabilities.families import register as register_family
from app.clients.shopify import (
    MAX_CUSTOM_LINE_PRICE,
    MAX_CUSTOM_TITLE_CHARS,
    MAX_DRAFT_LINES,
    MAX_DRAFT_QUANTITY,
    ShopifyClient,
    ShopifyError,
    mailing_address_ok,
)
from app.commands import Command, Outcome
from app.commands import Ctx as CommandCtx
from app.commands import register as register_command
from app.families import _sizes as sizes
from app.families import _workspace as ws
from app.reads.scheduler import Read, ReadPlan, ReadResult
from app.recipes import CACHE_NONE, Ctx, Recipe, RecipeAnswer, register
from app.tools.gate import Tier
from app.tools.registry import ToolError, WriteSpec, tool
from app.tools.shopify_tools import _c, catalogue_candidates
from app.tools.shopify_writes import VARIANT_FOR_EDIT_QUERY, address_line

log = logging.getLogger("crooks.families.order_create")

KIND = "order_draft"
WORKSPACE_PREFIX = "ord"
OPEN_TOOL = "shopify_order_open"
BUILD_TOOL = "shopify_order_build"
WRITE_TOOL = "shopify_order_create"
SEARCH_TOOL = "shopify_variant_search"
OPERATION = "draft_order_complete"
SCOPE = "write_draft_orders"
READ_SCOPE = "read_draft_orders"

MAX_CANDIDATES = 5
MAX_NOTE_CHARS = 300
MAX_PICKS = 8
# One spoken change adds at most this many things; more than that is a list to read back,
# not a sentence.
MAX_ADDS = 5
DRAFT_TAG = "CROOKS assistant"
# The drafts a card has made that are read again before it prepares another: each could have
# become the order since (`shopify_order_create`). A card is rarely prepared more than twice.
MAX_DRAFTS_CHECKED = 5
# What the card says when a hold card prepared from it was withdrawn because it changed.
CHANGED = "The order changed — prepare it again."


# --------------------------------------------------------------------------- the reads

CUSTOMER_CANDIDATES_QUERY = """
query CrooksCustomerCandidates($q: String!, $n: Int!) {
  customers(first: $n, query: $q) {
    edges {
      node {
        id
        displayName
        numberOfOrders
        defaultEmailAddress { emailAddress }
      }
    }
  }
}
"""

CUSTOMER_FOR_ORDER_QUERY = """
query CrooksCustomerForOrder($id: ID!) {
  customer(id: $id) {
    id
    displayName
    numberOfOrders
    defaultEmailAddress { emailAddress }
    defaultAddress { address1 address2 city provinceCode zip country countryCodeV2 }
  }
}
"""

# Validated against the Admin API schema (round 12). The lines, the discounts, who it is for,
# where the confirmation goes and where the parcel goes are read so that what Shopify holds can
# be compared with what the owner is authorising (`expected_card`, `draft_card`).
DRAFT_ORDER_QUERY = """
query CrooksDraftOrder($id: ID!) {
  draftOrder(id: $id) {
    id
    name
    status
    totalPriceSet { shopMoney { amount currencyCode } }
    subtotalPriceSet { shopMoney { amount currencyCode } }
    totalShippingPriceSet { shopMoney { amount currencyCode } }
    appliedDiscount { title value valueType }
    order { id name }
    customer { id displayName }
    email
    shippingAddress { address1 address2 city zip countryCodeV2 }
    lineItems(first: 20) {
      edges { node { title quantity custom variantTitle variant { id } appliedDiscount { title value valueType } originalUnitPriceSet { shopMoney { amount currencyCode } } discountedTotalSet { shopMoney { amount currencyCode } } } }
    }
  }
}
"""

# A variant and all of its product's variants: what "the next size up" is worked out from. A
# page at a time (`_read_product_of`): a product can have far more variants than one page, and
# the size one up from the variant asked about may be on any of them.
VARIANT_SIBLINGS_QUERY = """
query CrooksVariantSiblings($id: ID!, $after: String) {
  productVariant(id: $id) {
    id
    title
    selectedOptions { name value }
    product {
      id
      title
      status
      options { name values }
      variants(first: 100, after: $after) {
        edges { node { id title sku price availableForSale inventoryQuantity selectedOptions { name value } } }
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
# How many pages of a product's variants are read before the read is called incomplete: 1,000
# variants, more than any garment in sizes and colours has.
MAX_VARIANT_PAGES = 10

# The order a new one is made from: whose it is, where it went, and what was on it. Its lines a
# page at a time (`_source_has_variant`).
ORDER_FOR_NEW_ORDER_QUERY = """
query CrooksOrderForNewOrder($id: ID!, $after: String) {
  order(id: $id) {
    id
    name
    customer { id displayName }
    shippingAddress { firstName lastName company address1 address2 city provinceCode zip countryCodeV2 phone }
    lineItems(first: 50, after: $after) {
      edges { node { title variantTitle quantity variant { id } } }
      pageInfo { hasNextPage endCursor }
    }
  }
}
"""
# How many pages of an order's lines are read looking for the line a size is stepped from: 250.
MAX_SOURCE_LINE_PAGES = 5


def _money(node: Any) -> float | None:
    try:
        return round(float(((node or {}).get("shopMoney") or {})["amount"]), 2)
    except (TypeError, KeyError, ValueError):
        return None


def _currency(node: Any) -> str:
    try:
        return str(((node or {}).get("shopMoney") or {}).get("currencyCode") or "GBP")
    except AttributeError:
        return "GBP"


def display(amount: float | None, currency: str = "GBP") -> str:
    if amount is None:
        return "—"
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency.upper())
    return f"{symbol}{amount:,.2f}" if symbol else f"{amount:,.2f} {currency}"


# Said and typed alike (`shopify_order_build`, `_clean_postage`).
POSTAGE_BOUND = f"Postage is an amount between £0 and {display(MAX_CUSTOM_LINE_PRICE)}."


async def _candidates(client: ShopifyClient, name: str) -> list[dict[str, Any]]:
    """Who in the shop could be meant by that name. A LIST, always: the point of this read is
    to be able to say "there are two", and a function that returned the best match could not."""
    term = " ".join(str(name or "").split())[:80]
    if not term:
        return []
    query = f'email:"{term}"' if "@" in term else term
    payload = await client.graphql(CUSTOMER_CANDIDATES_QUERY, {"q": query, "n": MAX_CANDIDATES})
    out = []
    for edge in (((payload.get("data") or {}).get("customers") or {}).get("edges") or []):
        node = (edge or {}).get("node") or {}
        if node.get("id"):
            out.append({
                "customer_id": str(node["id"]),
                "name": str(node.get("displayName") or ""),
                "email": str(((node.get("defaultEmailAddress") or {}).get("emailAddress")) or ""),
                "orders": str(node.get("numberOfOrders") or "0"),
            })
    return out


async def _customer(client: ShopifyClient, customer_id: str) -> dict[str, Any]:
    payload = await client.graphql(CUSTOMER_FOR_ORDER_QUERY, {"id": customer_id})
    node = (payload.get("data") or {}).get("customer")
    if not isinstance(node, dict) or node.get("id") != customer_id:
        raise ToolError(f"No customer with id {customer_id}.")
    return node


async def _variant(client: ShopifyClient, variant_id: str) -> dict[str, Any]:
    payload = await client.graphql(VARIANT_FOR_EDIT_QUERY, {"id": variant_id})
    node = (payload.get("data") or {}).get("productVariant")
    if not isinstance(node, dict) or node.get("id") != variant_id:
        raise ToolError(f"No product variant with id {variant_id}.")
    return node


async def _read_draft(client: ShopifyClient, draft_id: str) -> dict[str, Any]:
    payload = await client.graphql(DRAFT_ORDER_QUERY, {"id": draft_id})
    node = (payload.get("data") or {}).get("draftOrder")
    if not isinstance(node, dict) or node.get("id") != draft_id:
        raise ToolError(f"No draft order with id {draft_id}.")
    return node


async def _read_source(client: ShopifyClient, order_id: str) -> dict[str, Any]:
    payload = await client.graphql(ORDER_FOR_NEW_ORDER_QUERY, {"id": order_id})
    node = (payload.get("data") or {}).get("order")
    if not isinstance(node, dict) or node.get("id") != order_id:
        raise ToolError(f"No order with id {order_id}.")
    return node


def _next_cursor(connection: Any) -> tuple[bool, str]:
    """(whether there is more past this page, the cursor to read it from). A page that does not
    say whether there is more is taken as having more and no way to read it — an incomplete
    read — because a page taken for the last one is how "there is no such size" gets said about
    a size on the page after it."""
    info = (connection or {}).get("pageInfo") if isinstance(connection, dict) else None
    if not isinstance(info, dict) or not isinstance(info.get("hasNextPage"), bool):
        return True, ""
    return info["hasNextPage"], str(info.get("endCursor") or "") if info["hasNextPage"] else ""


async def _read_product_of(client: ShopifyClient, variant_id: str) -> dict[str, Any]:
    """The product a variant belongs to, with every variant and its options, as `_sizes.step`
    takes it, and the variant asked about as its own lookup returned it (`start`), so where it
    starts from never depends on which page it fell on.

    The variants are read a page at a time up to MAX_VARIANT_PAGES. `complete` is False when
    the read stopped with more still to read — at the bound, or on a page that did not say —
    and then nothing may be concluded from what is missing."""
    variants: list[dict[str, Any]] = []
    after = ""
    head: dict[str, Any] = {}
    complete = False
    for _ in range(MAX_VARIANT_PAGES):
        payload = await client.graphql(VARIANT_SIBLINGS_QUERY, {"id": variant_id, "after": after or None})
        node = (payload.get("data") or {}).get("productVariant")
        if not isinstance(node, dict) or node.get("id") != variant_id or not isinstance(node.get("product"), dict):
            raise ToolError(f"No product variant with id {variant_id}.")
        head = head or node
        connection = node["product"].get("variants") or {}
        variants += [(e or {}).get("node") or {} for e in connection.get("edges") or []]
        more, after = _next_cursor(connection)
        if not more:
            complete = True
            break
        if not after:
            break
    product = head["product"]
    return {
        "id": str(product.get("id") or ""), "title": str(product.get("title") or ""),
        "status": str(product.get("status") or ""),
        "options": [o for o in product.get("options") or [] if isinstance(o, dict)],
        "start": {"id": str(head["id"]), "title": str(head.get("title") or ""),
                  "selectedOptions": [o for o in head.get("selectedOptions") or [] if isinstance(o, dict)]},
        "variants": variants,
        "complete": complete,
    }


async def _source_has_variant(client: ShopifyClient, source: dict[str, Any], variant_id: str) -> bool | None:
    """Whether the order `source` (as `_read_source` returned it) has a line of `variant_id`:
    True, False — or None when its lines could not all be read (past MAX_SOURCE_LINE_PAGES, or a
    page that did not say whether there was more), which is neither answer."""
    connection = source.get("lineItems") or {}
    after = ""
    for _ in range(MAX_SOURCE_LINE_PAGES):
        if after:
            payload = await client.graphql(ORDER_FOR_NEW_ORDER_QUERY, {"id": source["id"], "after": after})
            node = (payload.get("data") or {}).get("order")
            if not isinstance(node, dict) or node.get("id") != source["id"]:
                return None
            connection = node.get("lineItems") or {}
        for edge in connection.get("edges") or []:
            if str((((edge or {}).get("node") or {}).get("variant") or {}).get("id") or "") == variant_id:
                return True
        more, after = _next_cursor(connection)
        if not more:
            return False
        if not after:
            return None
    return None


def _mailing(address: dict[str, Any]) -> dict[str, str]:
    """A shipping address as Shopify's MailingAddressInput takes it: its own ten fields, the
    empty ones left out (an empty string is not an address line)."""
    fields = {
        "firstName": address.get("firstName"), "lastName": address.get("lastName"),
        "company": address.get("company"), "address1": address.get("address1"),
        "address2": address.get("address2"), "city": address.get("city"),
        "provinceCode": address.get("provinceCode"), "zip": address.get("zip"),
        "countryCode": address.get("countryCode") or address.get("countryCodeV2"),
        "phone": address.get("phone"),
    }
    return {k: " ".join(str(v).split())[:100] for k, v in fields.items() if str(v or "").strip()}


def draft_fingerprint(node: dict[str, Any]) -> dict[str, Any]:
    """What the draft must still look like for this completion to be the one prepared.

    `order` is the whole precondition for "execute at most once": a draft already completed
    has an order on it. `status` catches a draft cancelled or invoiced in Admin meanwhile,
    `lines` a line or a discount changed there, and `card` its customer, confirmation address,
    delivery address or postage — the owner authorised THIS order, and a draft that no longer
    carries it is not what his hold means. `total` is on the fingerprint for
    the proof, not the precondition: a total that moved is said after the fact.
    """
    total = _money(node.get("totalPriceSet"))
    return {
        "status": str(node.get("status") or ""),
        "order": str(((node.get("order") or {}).get("id")) or ""),
        "total": f"{total:.2f}" if total is not None else "",
        "lines": _digest(draft_signature(node)),
        # Who, where to and the postage (`draft_card`), part by part, so the proof can say which.
        "card": _card_digest(draft_card(node)),
    }


# --------------------------------------------------------------------------- the workspace


def _clean_name(raw: str) -> tuple[str, str, str]:
    value = " ".join(str(raw or "").split())[:80]
    if not value:
        return "", "invalid", "Whose order is it?"
    return value, "ok", ""


_EMAIL = re.compile(r"^[^@\s]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,24}$")


def _clean_email(raw: str) -> tuple[str, str, str]:
    value = "".join(str(raw or "").split()).lower()[:254]
    if not value:
        return "", "ok", ""
    if not _EMAIL.match(value):
        return value, "invalid", "That is not an address the confirmation could go to."
    return value, "ok", ""


def _clean_words(raw: str) -> tuple[str, str, str]:
    return " ".join(str(raw or "").split())[:60], "ok", ""


def _clean_quantity(raw: str) -> tuple[str, str, str]:
    said = re.sub(r"[^0-9]", "", str(raw or ""))
    if not said:
        return "1", "ok", ""
    quantity = int(said)
    if not 1 <= quantity <= MAX_DRAFT_QUANTITY:
        return said[:4], "invalid", f"Between 1 and {MAX_DRAFT_QUANTITY}."
    return str(quantity), "ok", ""


def _typed_amount(raw: str) -> tuple[str, float | None, str]:
    """(what was typed, the amount, why it is not one). An amount is a finite number: "nan",
    "inf" and "1e400" all parse as floats and none of them is money — "nan" reached the card
    as "nan% off" and the Prepare as a raw AssertionError before round 12's independent check."""
    said = str(raw or "").strip().replace(",", "").lstrip("£$€").rstrip("%").strip()
    if not said:
        return "", None, ""
    try:
        amount = float(said)
    except ValueError:
        return said[:10], None, f"{said[:20]!r} is not a number."
    if not math.isfinite(amount):
        return said[:10], None, "That is not a number."
    return said[:10], round(amount, 2), ""


def _clean_postage(raw: str) -> tuple[str, str, str]:
    """Postage, typed: the bound a spoken postage is held to (`shopify_order_build`), so the
    thumb cannot send what the voice may not."""
    said, amount, why = _typed_amount(raw)
    if not said:
        return "", "ok", ""
    if amount is None:
        return said, "invalid", why
    if not 0 <= amount <= MAX_CUSTOM_LINE_PRICE:
        return said, "invalid", POSTAGE_BOUND
    return f"{amount:g}", "ok", ""


def _clean_discount(raw: str) -> tuple[str, str, str]:
    """A discount on the order, typed: a percentage or an amount (the basis is a choice of its
    own, and `_blocked` holds a percentage to 100), never more than a spoken one may be."""
    said, amount, why = _typed_amount(raw)
    if not said:
        return "", "ok", ""
    if amount is None:
        return said, "invalid", why
    if amount < 0:
        return said, "invalid", "It cannot be negative."
    if amount > MAX_CUSTOM_LINE_PRICE:
        return said, "invalid", f"A discount is at most {display(MAX_CUSTOM_LINE_PRICE)} off, or 100%."
    return f"{amount:g}", "ok", ""


def _clean_note(raw: str) -> tuple[str, str, str]:
    return str(raw or "").replace("\r\n", "\n")[:MAX_NOTE_CHARS], "ok", ""


FIELDS: tuple[ws.Field, ...] = (
    ws.Field(name="customer", label="For", kind="text", placeholder="the customer's name", maxlength=80, rows=1, clean=_clean_name),
    ws.Field(name="email", label="Confirmation to", kind="email", placeholder="their address", maxlength=254, clean=_clean_email),
    ws.Field(name="item", label="Add an item", kind="sku", placeholder="a SKU, or the words", maxlength=60, clean=_clean_words),
    ws.Field(name="quantity", label="How many", kind="quantity", placeholder="1", maxlength=4, clean=_clean_quantity),
    ws.Field(name="discount", label="Discount on the order", kind="money", placeholder="none", maxlength=8, clean=_clean_discount),
    ws.Field(name="postage", label="Postage", kind="money", placeholder="none", maxlength=8, clean=_clean_postage),
    ws.Field(name="note", label="Note", kind="text", placeholder="on the order", maxlength=MAX_NOTE_CHARS, rows=2, clean=_clean_note),
)
FIELD_NAMES = tuple(f.name for f in FIELDS)

PAYMENT = ws.Choice(name="payment", label="Payment",
                    options=(("pending", "Not paid — invoice it"), ("paid", "Already paid")))
DISCOUNT_BASIS = ws.Choice(name="discount_basis", label="The order discount is",
                           options=(("percent", "Per cent"), ("amount", "Money off")))
# Where it goes. "order" and "given" are offered only on a workspace that has one — an order
# it was made from, an address the owner said — so the card never offers a choice with
# nothing behind it (`_choices`).
_ADDRESS_OPTIONS = (
    ("customer", "The customer's own address"),
    ("order", "As on the order it came from"),
    ("given", "The address you gave"),
    ("none", "No address"),
)
CHOICES: tuple[ws.Choice, ...] = (
    PAYMENT,
    ws.Choice(name="address", label="Where it goes",
              options=tuple(o for o in _ADDRESS_OPTIONS if o[0] in ("customer", "none"))),
    DISCOUNT_BASIS,
)


def _choices(workspace: dict[str, Any]) -> tuple[ws.Choice, ...]:
    """The choices this workspace offers: the address options it actually has something
    behind, named for what they are ("As on #1938")."""
    source = ws.fact(workspace, "source") or {}
    options = []
    for ident, label in _ADDRESS_OPTIONS:
        if ident == "order":
            if not source.get("address"):
                continue
            label = f"As on {source.get('order_number') or 'the order it came from'}"
        if ident == "given" and not ws.fact(workspace, "given_address"):
            continue
        options.append((ident, label))
    return (PAYMENT, ws.Choice(name="address", label="Where it goes", options=tuple(options)), DISCOUNT_BASIS)


# --------------------------------------------------------------------------- the lines
#
# A line is one of two kinds. A CATALOGUE line names a variant; its price is the catalogue's,
# read when it was added and read again when the order is prepared. A CUSTOM line is a title
# and the owner's own unit price — a print, a repair, anything the shop does not list. Either
# may carry a discount of its own: a percentage, or an amount off each one. Every line has a
# `key` the card and the tablet name it by, so a tap on "Remove" says WHICH line and nothing
# about what is on it.


def _key_for_variant(variant_id: str) -> str:
    return "v" + str(variant_id).rsplit("/", 1)[-1]


def _normal(line: dict[str, Any]) -> dict[str, Any]:
    out = dict(line)
    if out.get("variant_id"):
        out.setdefault("kind", "variant")
        out.setdefault("key", _key_for_variant(out["variant_id"]))
    else:
        out.setdefault("kind", "custom")
        out.setdefault("key", "c0")
    out["quantity"] = int(out.get("quantity") or 1)
    return out


def _lines(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    lines = ws.fact(workspace, "lines")
    return [_normal(line) for line in lines] if isinstance(lines, list) else []


def _set_lines(workspace: dict[str, Any], lines: list[dict[str, Any]]) -> None:
    """The lines, stored — and anything priced from the old ones forgotten."""
    workspace["facts"]["lines"] = lines
    _changed(workspace)


def _changed(workspace: dict[str, Any]) -> None:
    """Something the draft is built from moved: a draft already made no longer is this order,
    and the workspace is fresh for as long as the owner is still working on it."""
    workspace["facts"].pop("draft", None)
    workspace["at"] = ws._now()


def _unit(line: dict[str, Any]) -> float:
    try:
        return round(float(line.get("price") or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _off(line: dict[str, Any]) -> dict[str, Any] | None:
    off = line.get("off")
    return off if isinstance(off, dict) and off.get("type") in ("percent", "amount") and float(off.get("value") or 0) > 0 else None


def _cut(line: dict[str, Any]) -> float:
    """What the line's own discount takes off ONE of it: a percentage of the unit price, or
    a fixed amount off each, which is how the card words it ("£5.00 off each"). This is the
    workspace's own working, for the form; the money the owner authorises is the draft's, on
    the card that follows, and what is checked against the draft is the discount itself —
    its kind and its value — never a total worked out here."""
    off = _off(line)
    if off is None:
        return 0.0
    value = float(off["value"])
    return round(_unit(line) * value / 100.0, 2) if off["type"] == "percent" else round(min(value, _unit(line)), 2)


def _line_total(line: dict[str, Any]) -> float:
    return round((_unit(line) - _cut(line)) * int(line["quantity"]), 2)


def _off_words(off: dict[str, Any] | None, *, each: bool) -> str:
    if off is None:
        return ""
    value = float(off["value"])
    if off["type"] == "percent":
        return f"{value:g}% off"
    return f"{display(value)} off{' each' if each else ''}"


def _line_words(line: dict[str, Any]) -> str:
    variant = f" ({line['variant']})" if line.get("variant") else ""
    custom = " (custom)" if line["kind"] == "custom" else ""
    off = _off_words(_off(line), each=True)
    return f"{line['quantity']} x {line['title']}{variant}{custom}" + (f", {off}" if off else "")


def _chosen_customer(workspace: dict[str, Any]) -> dict[str, Any] | None:
    found = ws.fact(workspace, "customer")
    return dict(found) if isinstance(found, dict) and found.get("customer_id") else None


def _decimal(value: str) -> float | None:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    return round(amount, 2) if math.isfinite(amount) else None


def _goods(workspace: dict[str, Any]) -> float:
    """The lines, each after its own discount. Before any discount on the whole order."""
    return round(sum(_line_total(line) for line in _lines(workspace)), 2)


def _order_off(workspace: dict[str, Any]) -> dict[str, Any] | None:
    if ws.status(workspace, "discount") != "ok":
        return None                  # what was typed is not a discount; the field says why
    value = _decimal(ws.value(workspace, "discount"))
    if value is None or value <= 0:
        return None
    return {"type": ws.chosen(workspace, "discount_basis", "percent"), "value": f"{value:g}"}


def _blocked(workspace: dict[str, Any]) -> str:
    """Why this cannot be prepared yet, in the owner's words. Empty when it can.

    The two that matter most are the two the brief names: an ambiguous customer, and no
    items. Neither is a thing to guess at — the first would put a stranger's address on
    somebody else's order, and the second would make an empty order nobody asked for. The
    rest are the money: a discount bigger than what it is off, an item that is not for sale.
    """
    candidates = ws.fact(workspace, "candidates") or []
    chosen = _chosen_customer(workspace)
    if chosen is None:
        if not ws.value(workspace, "customer"):
            return "It needs a customer."
        if len(candidates) > 1:
            # The refusal FIRST, then the names: this sentence is bounded when it reaches the
            # card (app/families/_workspace.py), and five candidates would otherwise push
            # "I will not guess" off the end of the one line that has to survive.
            names = ", ".join(f"{c['name']} ({c['email'] or 'no address'})" for c in candidates[:MAX_CANDIDATES])
            return f"{len(candidates)} customers match that name and I will not guess which — {names}."
        if not candidates:
            return f"Nobody in the shop is called {ws.value(workspace, 'customer')!r}. Check the spelling, or make the customer in Admin first."
        return "The customer has not been chosen yet."
    if ws.status(workspace, "email") == "uncertain":
        # An address he typed for the customer before, taken off when this one was chosen
        # (`_set_customer`): the hint names who it is for now.
        return str((workspace.get("hints") or {}).get("email") or "") or _TYPE_IT_AGAIN.format(name=chosen["name"])
    if ws.status(workspace, "email") != "ok":
        return "That is not an address the confirmation could go to."
    not_theirs = _not_theirs(workspace, chosen)
    if not_theirs:
        return not_theirs
    lines = _lines(workspace)
    if not lines:
        return "It has nothing on it. Add an item."
    if len(lines) > MAX_DRAFT_LINES:
        return f"An order made from here carries at most {MAX_DRAFT_LINES} lines."
    for name in ("discount", "postage", "quantity"):
        if ws.status(workspace, name) != "ok":
            hint = str((workspace.get("hints") or {}).get(name) or "")
            label = {"discount": "The discount", "postage": "The postage", "quantity": "How many"}[name]
            return f"{label}: {hint}" if hint else f"{label} is not a number I can use."
    for line in lines:
        if line["kind"] == "variant" and line.get("for_sale") is False:
            return f"{line['title']} ({line.get('variant') or 'that one'}) is not for sale, so it cannot go on an order. Take it off or choose another."
        off = _off(line)
        if off and off["type"] == "percent" and float(off["value"]) > 100:
            return f"The discount on {line['title']} is more than 100%."
        if off and off["type"] == "amount" and float(off["value"]) > _unit(line):
            return f"The discount on {line['title']} is more than its price."
    order_off = _order_off(workspace)
    if order_off and order_off["type"] == "percent" and float(order_off["value"]) > 100:
        return "A discount is a percentage between 1 and 100."
    if order_off and order_off["type"] == "amount" and float(order_off["value"]) > _goods(workspace):
        return f"The discount on the order is more than the goods ({display(_goods(workspace))})."
    ship = ws.chosen(workspace, "address", "customer")
    if ship == "order" and not (ws.fact(workspace, "source") or {}).get("address"):
        return "The order it came from has no delivery address to send this to."
    if ship == "given" and not ws.fact(workspace, "given_address"):
        return "There is no address given to send it to."
    return ""


# --------------------------------------------------------------------------- whose it is
#
# Round 13 (the round-12 deploy review, S2Ba/F-01 and S2Ba/F-02). What the card carries about a
# person — where the confirmation goes, the door the parcel goes to, the name on it — belongs to
# one customer, and the customer can change: by voice, by id or by name, or by retyping the name
# on the card. Before this, the confirmation address was filled in from the first customer and
# only while it was empty, and an order's delivery address and a spoken address's name stayed
# whoever's they were: a change to Bob made Bob's order with Alice's email on it (Shopify's
# confirmation and shipping mails for his order in her inbox) or with his goods going to her
# door, and the draft check called that consistent because it compared the draft with the card.
#
# So each of those facts records whose it is, every change of customer goes through
# `_set_customer`, and `_blocked` — which every Prepare, tapped or said, runs — refuses a card
# where one of them is not the chosen customer's. The invariants:
#
#   * a draft's email is the chosen customer's own, or one typed after that customer was chosen;
#   * an address taken off an order is used only for that order's customer;
#   * the name on an address he said is the name of whoever the order is for.

_TYPE_IT_AGAIN = ("Type the confirmation address for {name}: the one typed was for the customer "
                  "before, so it was taken off.")


def _set_customer(workspace: dict[str, Any], customer: dict[str, Any] | None) -> list[str]:
    """Who the order is for — None while nobody is — and every fact on the card that came from
    whoever it was for before, made the new customer's or taken off. The one way the customer
    changes: the model's open and build, the card's own lookup (`choose_row`), the re-read at
    Prepare and the name retyped on the card all come here. Returns what it changed besides
    the customer, in words the model can read back."""
    if customer is None:
        workspace["facts"].pop("customer", None)
    else:
        workspace["facts"]["customer"] = customer
    return _email_for_customer(workspace, customer) + _address_for_customer(workspace, customer)


def _email_for_customer(workspace: dict[str, Any], customer: dict[str, Any] | None) -> list[str]:
    """The confirmation address, as whose it is (`email_for`: the customer it was read off or
    typed for, and which). Read off the customer before: replaced with the new one's own. Typed
    for the customer before: taken off, and the card waits for him to type one for this one —
    unless what he typed IS this customer's own address."""
    held = dict(ws.fact(workspace, "email_for") or {})
    value = ws.value(workspace, "email")
    if customer is None:
        if held.get("how") == "read":
            # Theirs, not whoever the card turns out to be for next.
            ws.type_into(workspace, FIELDS, "email", "")
            workspace["facts"].pop("email_for", None)
        return []
    new_id = str(customer.get("customer_id") or "")
    own = str(customer.get("email") or "").strip().lower()
    if held.get("customer_id") == new_id and held.get("how") in ("read", "typed", "cleared"):
        return []                              # already this customer's, or already waiting for theirs
    if held.get("how") == "cleared" or (held.get("how") != "read" and value and value != own):
        # Typed for somebody else (or typed before anybody was chosen): not this customer's.
        ws.type_into(workspace, FIELDS, "email", "")
        workspace["status"]["email"] = "uncertain"
        workspace["hints"]["email"] = _TYPE_IT_AGAIN.format(name=customer.get("name") or "this customer")[:160]
        workspace["facts"]["email_for"] = {"customer_id": new_id, "how": "cleared"}
        return [] if held.get("how") == "cleared" else [
            f"the confirmation address typed for the customer before was taken off; the owner types "
            f"{customer.get('name') or 'the new customer'}'s on the card"]
    ws.type_into(workspace, FIELDS, "email", own)
    workspace["facts"]["email_for"] = {"customer_id": new_id, "how": "read"}
    if held.get("how") == "read" and value and value != own:
        return [f"the confirmation goes to {customer.get('name') or 'the new customer'}'s own address"]
    return []


def _address_for_customer(workspace: dict[str, Any], customer: dict[str, Any] | None) -> list[str]:
    """Where it goes, as whose it is. The order it was made from is that order's customer's: for
    anybody else it is taken off, with its "as on the order" choice, and the parcel goes to the
    new customer's own address. An address he said stands — it is where he said — with the new
    customer's name on it. Nothing changes while nobody is chosen: the same customer chosen
    again keeps both."""
    if customer is None:
        return []
    new_id = str(customer.get("customer_id") or "")
    said: list[str] = []
    source = ws.fact(workspace, "source") or {}
    if source and str(source.get("customer_id") or "") != new_id:
        workspace["facts"].pop("source", None)
        if ws.chosen(workspace, "address", "customer") == "order":
            ws.choose(workspace, _choices(workspace), "address", "customer")
            said.append(f"it goes to {customer.get('name') or 'the new customer'}'s own address, not the address on "
                        f"{source.get('order_number') or 'the order it was made from'}")
    given = ws.fact(workspace, "given_address")
    if isinstance(given, dict) and str(ws.fact(workspace, "given_for") or "") != new_id:
        workspace["facts"]["given_address"] = _named(given, customer)
        workspace["facts"]["given_for"] = new_id
    return said


def _named(address: dict[str, Any], customer: dict[str, Any]) -> dict[str, str]:
    """An address the owner said, with the name of the customer it goes to on it."""
    first, _, last = str(customer.get("name") or "").partition(" ")
    return _mailing({**{k: v for k, v in address.items() if k not in ("firstName", "lastName")},
                     "firstName": first, "lastName": last})


def _not_theirs(workspace: dict[str, Any], chosen: dict[str, Any]) -> str:
    """Why what the card carries about a person is not the chosen customer's, in the owner's
    words; empty when it all is. `_set_customer` keeps it so; this is the floor under it, so a
    card that got here any other way is refused rather than prepared."""
    ident = str(chosen.get("customer_id") or "")
    who = chosen.get("name") or "the customer"
    held = ws.fact(workspace, "email_for") or {}
    if ws.value(workspace, "email") and not (held.get("customer_id") == ident and held.get("how") in ("read", "typed")):
        return _TYPE_IT_AGAIN.format(name=who)
    ship = ws.chosen(workspace, "address", "customer")
    source = ws.fact(workspace, "source") or {}
    if ship == "order" and str(source.get("customer_id") or "") != ident:
        return (f"{source.get('order_number') or 'The order it was made from'} is not {who}'s order, so its "
                f"delivery address is not theirs to send to. Choose where it goes.")
    if ship == "given" and str(ws.fact(workspace, "given_for") or "") != ident:
        return f"The address you gave carries another customer's name. Say it again for {who}."
    return ""


def _address_fact(workspace: dict[str, Any], chosen: dict[str, Any]) -> dict[str, Any]:
    ship = ws.chosen(workspace, "address", "customer")
    if ship == "none":
        return {"label": "Address", "value": "none — the order carries no shipping address"}
    if ship == "order":
        source = ws.fact(workspace, "source") or {}
        return {"label": "Address", "value": f"as on {source.get('order_number')}: {source.get('line') or ''}".strip()}
    if ship == "given":
        return {"label": "Address", "value": address_line(ws.fact(workspace, "given_address") or {}), "tone": "warn"}
    if chosen.get("address"):
        return {"label": "Address", "value": str(chosen["address"])}
    if "address" in chosen:
        # Read, and there is none. Different from "not read yet", which is the case below.
        return {"label": "Address", "value": "none on file — it will be made without one", "tone": "warn"}
    return {"label": "Address", "value": "the customer's own, read when you prepare it"}


def _facts(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    """What the Mac has read and worked out, for the form. Deliberately NOT the total the
    owner will authorise: that number is Shopify's, it comes off the draft, and it appears on
    the confirmation card. A total computed here and printed beside Shopify's would be two
    numbers that can disagree. The lines are drawn as rows of their own (`_rows`)."""
    rows: list[dict[str, Any]] = []
    chosen = _chosen_customer(workspace)
    candidates = ws.fact(workspace, "candidates") or []
    if chosen:
        rows.append({"label": "Customer", "value": f"{chosen['name']} · {chosen.get('email') or 'no address on file'}", "tone": "ok"})
        rows.append(_address_fact(workspace, chosen))
    elif len(candidates) > 1:
        for candidate in candidates[:MAX_CANDIDATES]:
            rows.append({"label": "Could be", "value": f"{candidate['name']} · {candidate.get('email') or 'no address'} · {candidate['orders']} orders", "tone": "warn"})
    source = ws.fact(workspace, "source") or {}
    if source.get("order_number"):
        rows.append({"label": "Made from", "value": f"order {source['order_number']}"})
    if _lines(workspace):
        rows.append({"label": "Goods", "value": display(_goods(workspace))})
    order_off = _order_off(workspace)
    if order_off:
        rows.append({"label": "Discount", "value": f"{_off_words(order_off, each=False)} the order"})
    if ws.value(workspace, "postage") and ws.status(workspace, "postage") == "ok":
        rows.append({"label": "Postage", "value": display(_decimal(ws.value(workspace, "postage")))})
    rows.append({"label": "Payment", "value": "already paid" if ws.chosen(workspace, "payment", "pending") == "paid" else "not paid — invoice it"})
    if ws.fact(workspace, "item_note"):
        rows.append({"label": "That item", "value": str(ws.fact(workspace, "item_note")), "tone": "warn"})
    draft = ws.fact(workspace, "draft") or {}
    if draft.get("name"):
        rows.append({"label": "Draft", "value": f"{draft['name']} is in Admin, priced and not an order yet"})
    return rows


def _stock_words(available: Any, for_sale: Any) -> tuple[str, str]:
    """What the card says about stock, and its tone. Out of stock is SHOWN, never hidden: the
    owner may know a restock is coming, and a line quietly dropped is worse than one flagged."""
    if for_sale is False:
        return "not for sale", "bad"
    if isinstance(available, int) and not isinstance(available, bool):
        if available <= 0:
            return "out of stock", "warn"
        return f"{available} in stock", ""
    return "", ""


def _rows(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    """The lines as the card draws them, numbered as the owner will refer to them."""
    out = []
    for number, line in enumerate(_lines(workspace), start=1):
        off = _off(line)
        stock, tone = ("custom item", "") if line["kind"] == "custom" else _stock_words(line.get("available"), line.get("for_sale"))
        out.append({
            "key": line["key"], "number": number, "title": line["title"],
            "detail": " · ".join(p for p in (line.get("variant"), line.get("sku")) if p),
            "quantity": f"× {line['quantity']}",
            "amount": display(_line_total(line)),
            "was": display(round(_unit(line) * line["quantity"], 2)) if off else "",
            "discount": _off_words(off, each=True),
            "stock": stock, "tone": tone,
            "button": {"label": "Remove", "command": "order.removeitem", "args": {"line": line["key"]}},
        })
    return out


def _pick_rows(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for pick in ws.fact(workspace, "picks") or []:
        stock, tone = _stock_words(pick.get("available"), pick.get("for_sale"))
        out.append({
            "key": _key_for_variant(pick["variant_id"]), "title": pick.get("title") or "",
            "detail": " · ".join(p for p in (pick.get("variant"), pick.get("sku")) if p),
            "amount": display(_decimal(pick.get("price"))), "stock": stock, "tone": tone,
            "button": {"label": "Add", "command": "order.additem", "args": {"variant_id": pick["variant_id"]}},
        })
    return out


def _notes(workspace: dict[str, Any]) -> list[str]:
    notes = []
    if ws.failed(workspace):
        # The last hold did not make it (Shopify refused it, or it never left): said, and the
        # card is his to prepare again.
        notes.append(f"The order was not created: {ws.failed(workspace)}. Nothing was made; prepare it again.")
    notes += [
        "Shopify prices it as a draft order when you tap Prepare. The draft is not an order "
        f"and nobody is charged for it; it is tagged {DRAFT_TAG!r} so you can find it in Admin.",
    ]
    if ws.chosen(workspace, "payment", "pending") == "paid":
        notes.append("Marked as already paid, so Shopify will not send an invoice and will record the money as taken.")
    else:
        notes.append("Not paid: the order is created owing its total, and the invoice is yours to send.")
    return notes


ACTIONS: tuple[ws.Action, ...] = (
    ws.Action(id="additem", label="Add the item", command="order.additem"),
    ws.Action(id="prepare", label="Prepare the order", command="order.stage", risk="red"),
    ws.Action(id="discard", label="Discard", command="order.discard"),
)


def workspace_surface(workspace: dict[str, Any]):
    made = finished(workspace)
    if made is not None:
        return _made_surface(workspace, made)
    chosen = _chosen_customer(workspace)
    blocked = _blocked(workspace)
    lines = _lines(workspace)
    picks = ws.fact(workspace, "picks") or []
    return ws.surface(
        workspace, fields=FIELDS, choices=_choices(workspace),
        kicker="A new order · not created",
        title=(chosen["name"] if chosen else ws.value(workspace, "customer")) or "A new order",
        subtitle=(f"{len(lines)} line{'s' if len(lines) != 1 else ''}, {display(_goods(workspace))} of goods"
                  if lines else "nothing on it yet"),
        facts=_facts(workspace), notes=_notes(workspace), actions=ACTIONS,
        field_command="order.field", blocked=blocked,
        rows=_rows(workspace), picks=_pick_rows(workspace),
        picks_title=(f"Which one? {len(picks)} match {ws.fact(workspace, 'picks_for')!r}" if picks else ""),
        spoken="Nothing is created until you hold the card that follows.",
    )


def _made_surface(workspace: dict[str, Any], made: dict[str, str]):
    """The card once it has made its order: the order, by its number, with what is on it — and
    nothing to type, tap or prepare. The same card in the same place, so the glass does not jump;
    only what it says has changed. What it says is the card as the draft that became the order
    was made from it, not a change tapped in after that."""
    snapshot = (ws.fact(workspace, "prepared") or {}).get(str(made.get("draft_id") or ""))
    if isinstance(snapshot, dict):
        workspace = {**workspace, "values": {**(workspace.get("values") or {}), **snapshot["values"]},
                     "choices": {**(workspace.get("choices") or {}), **snapshot["choices"]},
                     "facts": {**(workspace.get("facts") or {}), "lines": snapshot["lines"],
                               **({"customer": snapshot["customer"]} if snapshot.get("customer") else {})}}
    chosen = _chosen_customer(workspace) or {}
    lines = _lines(workspace)
    created = made.get("state") == "created"
    number = made.get("order_number") or "The order"
    facts = [{"label": "Customer", "value": f"{chosen.get('name') or ''} · {ws.value(workspace, 'email') or 'no address'}"}]
    if chosen:
        facts.append(_address_fact(workspace, chosen))
    discount = _discount_words(workspace)
    if discount:
        facts.append({"label": "Discount", "value": discount})
    if ws.value(workspace, "postage") and ws.status(workspace, "postage") == "ok":
        facts.append({"label": "Postage", "value": display(_decimal(ws.value(workspace, "postage")))})
    facts.append({"label": "Payment", "value": "already paid" if ws.chosen(workspace, "payment", "pending") == "paid"
                  else "not paid — invoice it"})
    if created:
        facts.append({"label": "Order", "value": f"{number} is created", "tone": "ok"})
    else:
        facts.append({"label": "Order", "value": "sent to Shopify; it has not said whether it made it", "tone": "warn"})
    rows = [{k: v for k, v in row.items() if k != "button"} for row in _rows(workspace)]
    return ws.surface(
        workspace, fields=(), choices=(),
        kicker="Order created" if created else "Sent · not confirmed",
        title=number if created else (chosen.get("name") or "The new order"),
        subtitle=(f"for {chosen.get('name') or 'the customer'} · {len(lines)} line{'s' if len(lines) != 1 else ''}, "
                  f"{display(_goods(workspace))} of goods"),
        facts=facts,
        notes=["Anything more is a new order: say 'a new order for …'."] if created else
        ["Look at it in Admin before making it again."],
        actions=(), rows=rows, settled="created" if created else "unconfirmed",
        spoken=f"Order {number} is created." if created else "Sent to Shopify, not confirmed.",
    )


def _spoken(workspace: dict[str, Any]) -> str:
    """The grounded half of the answer: what the Mac read and what it is waiting for. When a
    recipe draws this workspace it LEADS the answer and Claude's words follow it."""
    if already_made(workspace):
        return already_made(workspace)
    blocked = _blocked(workspace)
    chosen = _chosen_customer(workspace)
    candidates = ws.fact(workspace, "candidates") or []
    if chosen is None and len(candidates) > 1:
        return (
            f"{len(candidates)} customers match {ws.value(workspace, 'customer')!r}: "
            + "; ".join(f"{c['name']}, {c.get('email') or 'no address'}, {c['orders']} orders" for c in candidates[:MAX_CANDIDATES])
            + ". I will not guess which. Nothing is created."
        )
    if chosen is None and not candidates and ws.value(workspace, "customer"):
        return f"Nobody in the shop is called {ws.value(workspace, 'customer')!r}. Nothing is created."
    who = chosen["name"] if chosen else "nobody yet"
    lines = _lines(workspace)
    what = ", ".join(_line_words(line) for line in lines) or "nothing on it yet"
    tail = f" {blocked}" if blocked else " Tap Prepare, then hold the card to create it."
    return f"An order for {who}: {what}, {display(_goods(workspace))} of goods.{tail}"


# --------------------------------------------------------------------------- made once
#
# A card makes one order, and what happened to its completion is kept where every workspace's
# is (app/families/_workspace.py "made once"): `sending` from the moment before it leaves,
# `done` once Shopify has said which order it made or a re-read shows one, `unconfirmed` when it
# left and could not be proven, `failed` — back to his to build, with the reason — when Shopify
# refused it or it never left.


def finished(workspace: dict[str, Any] | None) -> dict[str, str] | None:
    """The order this card has made — {"state": "created", "order_id", "order_number"} — or, when
    the completion left for Shopify and nothing proved it either way, {"state": "sending",
    "draft_name"}; None while it is still being built. Either way it is not built on again."""
    made = ws.finished(workspace)
    if made is None:
        return None
    if made.get("state") == ws.DONE:
        return {**made, "state": "created"}
    return {**made, "state": "sending"}


def already_made(workspace: dict[str, Any] | None) -> str:
    """Why nothing more may be done to this card, in the owner's words — or "" while it is still
    his to build."""
    made = finished(workspace)
    if made is None:
        return ""
    if made.get("state") == "created":
        return f"{made.get('order_number') or 'That order'} is already created; say 'a new order for …' to start another."
    draft = f" ({made['draft_name']})" if made.get("draft_name") else ""
    return (f"This order was sent to Shopify and it has not said whether it made it{draft}; look in Admin before "
            "making it again, or say 'a new order for …' to start another.")


def _put_away(workspace: dict[str, Any]) -> str:
    """What the model is told when it reaches for an order he put away himself."""
    chosen = _chosen_customer(workspace) or {}
    who = f" for {chosen['name']}" if chosen.get("name") else ""
    return (f"Nothing is being built on the owner's screen: the order{who} was put away, and it changes only "
            "once he asks for it back (show_again). Ask which order he means, or open a new one with "
            f"{OPEN_TOOL}.")


def where_line(branch: Any) -> str:
    """One clause for the turn's "where we are" (app/routes/turn.py): that a new order is being
    built on this half, for whom, and how it is changed — so a sentence about it goes to the
    card on the screen rather than starting another. Once the card has made its order it says
    THAT, so "now add a cap to it" is not taken for a change to an order still being built."""
    workspace = ws.held(branch, KIND)
    if workspace is None or ws.is_put_away(workspace):
        # Nothing, or one he put away himself: not the thing being built, and not offered as it.
        return ""
    chosen = _chosen_customer(workspace)
    who = chosen["name"] if chosen else (ws.value(workspace, "customer") or "nobody yet")
    made = finished(workspace)
    if made is not None:
        what = (f"is CREATED as order {made.get('order_number') or '(number not read)'}"
                + (f" (order_id {made['order_id']})" if made.get("order_id") else "")
                if made.get("state") == "created" else "was sent to Shopify, not confirmed")
        return (f"the new order{' on screen' if ws.on_glass(branch, workspace) else ''} ({workspace['workspace_id']}) "
                f"for {who} {what} — it cannot be changed; anything more is a new order ({OPEN_TOOL})")
    count = len(_lines(workspace))
    if not ws.on_glass(branch, workspace):
        # Another card took its place (a stock question, an order looked up): still the order
        # being built, and a change to it puts it back on his screen (round 12's fourth check).
        return (f"building a new order ({workspace['workspace_id']}) for {who}, {count} line{'s' if count != 1 else ''}, "
                f"not created — not on his screen at the moment; changing it with {BUILD_TOOL} puts it back")
    return (f"building a new order ({workspace['workspace_id']}) for {who}, {count} line{'s' if count != 1 else ''}, "
            f"not created — change it with {BUILD_TOOL}")


# --------------------------------------------------------------------------- adding things


def _variant_line(candidate: dict[str, Any], quantity: int) -> dict[str, Any]:
    return {
        "key": _key_for_variant(candidate["variant_id"]), "kind": "variant",
        "variant_id": str(candidate["variant_id"]), "product_id": str(candidate.get("product_id") or ""),
        "title": str(candidate.get("title") or ""), "variant": str(candidate.get("variant") or ""),
        "sku": str(candidate.get("sku") or ""),
        "price": f"{float(candidate.get('price') or 0):.2f}", "quantity": int(quantity),
        "available": candidate.get("available"), "for_sale": bool(candidate.get("for_sale", True)),
    }


def add_variant(workspace: dict[str, Any], candidate: dict[str, Any], quantity: int) -> dict[str, Any]:
    """A catalogue variant onto the order, or one more of a line already there — never a second
    line saying the same thing. Returns the line as it now stands."""
    lines = _lines(workspace)
    key = _key_for_variant(candidate["variant_id"])
    # Whatever was being chosen between has been chosen.
    for name in ("picks", "picks_for", "picks_quantity", "item_note"):
        workspace["facts"].pop(name, None)
    for line in lines:
        if line["key"] == key:
            line["quantity"] = min(MAX_DRAFT_QUANTITY, int(line["quantity"]) + int(quantity))
            line.update({k: v for k, v in _variant_line(candidate, 1).items() if k in ("available", "for_sale")})
            _set_lines(workspace, lines)
            return line
    line = _variant_line(candidate, quantity)
    lines.append(line)
    _set_lines(workspace, lines)
    return line


def _next_custom_key(workspace: dict[str, Any]) -> str:
    seq = int(ws.fact(workspace, "custom_seq") or 0) + 1
    workspace["facts"]["custom_seq"] = seq
    return f"c{seq}"


def offer(workspace: dict[str, Any], candidates: list[dict[str, Any]], words: str, quantity: int) -> dict[str, Any]:
    """What a catalogue search for `words` means for this order.

    One variant matches every word: it goes on, whatever its stock — out of stock is shown on
    its line, and one that is not for sale at all stops the Prepare with the reason. Several
    match: none goes on, and they are offered as a choice on the card. None: said so.
    Returns {"added": line} or {"choices": [...]} or {"none": why}.
    """
    workspace["facts"].pop("item_note", None)
    if not candidates:
        workspace["facts"]["item_note"] = f"nothing in the catalogue matches {words!r}"
        return {"none": f"Nothing in the catalogue matches {words!r}."}
    if len(candidates) > 1:
        picks = candidates[:MAX_PICKS]
        workspace["facts"]["picks"] = picks
        workspace["facts"]["picks_for"] = words[:60]
        # "Two black hoodies" and then a tap on the one he meant: the tap adds two.
        workspace["facts"]["picks_quantity"] = int(quantity)
        workspace["facts"]["item_note"] = (
            f"{len(candidates)} match {words!r}: "
            + "; ".join(f"{c.get('title')} {c.get('variant') or ''}".strip() for c in picks[:4])
            + ". Be more specific, or tap one."
        )
        workspace["at"] = ws._now()
        return {"choices": picks}
    return {"added": add_variant(workspace, candidates[0], quantity)}


def _clean_title(raw: str) -> str:
    return " ".join(str(raw or "").replace("<", "").split())[:MAX_CUSTOM_TITLE_CHARS]


def add_custom(workspace: dict[str, Any], title: str, price: float, quantity: int) -> dict[str, Any]:
    """A custom line: the owner's title and unit price, because the catalogue has neither."""
    lines = _lines(workspace)
    line = {"key": _next_custom_key(workspace), "kind": "custom", "title": _clean_title(title),
            "price": f"{round(float(price), 2):.2f}", "quantity": int(quantity)}
    lines.append(line)
    _set_lines(workspace, lines)
    return line


def _number(value: Any) -> float | None:
    """A number the model sent, or None when it is not one. A yes/no is not a number, and nor
    is "nan" or an infinity, which `float` takes and every comparison after it gets wrong."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 2) if math.isfinite(number) else None


def _quantity(value: Any) -> tuple[int, str]:
    """How many, as said: (the number, why it cannot be used). Never clamped — sixty said is
    not fifty meant, and a quantity changed without saying so is a change nobody asked for."""
    if value is None:
        return 1, ""
    number = _number(value)
    if number is None or number != int(number) or not 1 <= number <= MAX_DRAFT_QUANTITY:
        return 0, f"How many is a whole number from 1 to {MAX_DRAFT_QUANTITY}."
    return int(number), ""


def _discount(percent: Any, amount: Any) -> tuple[dict[str, Any] | None, str]:
    """A discount as said: (the discount, or None to clear it; why it cannot be used)."""
    if percent is not None and amount is not None:
        return None, "Say a percentage or an amount, not both."
    if percent is not None:
        value = _number(percent)
        if value is None or value < 0 or value > 100:
            return None, "A percentage is between 0 and 100."
        return ({"type": "percent", "value": f"{value:g}"} if value > 0 else None), ""
    if amount is not None:
        value = _number(amount)
        if value is None or value < 0 or value > MAX_CUSTOM_LINE_PRICE:
            return None, f"An amount off is between £0 and {display(MAX_CUSTOM_LINE_PRICE)}."
        return ({"type": "amount", "value": f"{value:g}"} if value > 0 else None), ""
    return None, ""


async def _add_by_words(workspace: dict[str, Any], words: str, quantity: int) -> dict[str, Any]:
    candidates, _wanted = await catalogue_candidates(_c(), words[:60])
    return offer(workspace, candidates, words, quantity)


async def _candidate_for(variant_id: str) -> dict[str, Any]:
    """One variant by id, read now, in the shape a catalogue search returns."""
    node = await _variant(_c(), variant_id)
    product = node.get("product") or {}
    if str(product.get("status") or "ACTIVE").upper() != "ACTIVE":
        raise ToolError(f"{product.get('title') or 'That item'} is not a live product, so it cannot go on an order.")
    quantity = node.get("inventoryQuantity")
    return {
        "variant_id": str(node["id"]), "product_id": str(product.get("id") or ""),
        "title": str(product.get("title") or ""), "variant": str(node.get("title") or ""),
        "sku": str(node.get("sku") or ""), "price": str(node.get("price") or "0"),
        "available": quantity if isinstance(quantity, int) and not isinstance(quantity, bool) else None,
        "for_sale": bool(node.get("availableForSale")),
    }


async def _step_size(variant_id: str, by: int) -> tuple[dict[str, Any] | None, str]:
    """The variant `by` sizes from this one, in the same colour: (candidate, "") or (None, why).
    A read of the product's variants that stopped short is said as that, never as a size the
    product does not come in: the size may be on the page that was not read."""
    product = await _read_product_of(_c(), variant_id)
    if product["status"] and product["status"].upper() != "ACTIVE":
        return None, f"{product['title']} is not a live product any more."
    if not product["complete"]:
        return None, (f"I could not read all of {product['title'] or 'that item'}'s variants (I read "
                      f"{len(product['variants'])} and there are more), so I cannot say which is the next size. "
                      "Nothing was added; say the size and it can be found by a search.")
    found = sizes.step(product, variant_id, by)
    if not found["ok"]:
        return None, str(found["why"])
    variant = found["variant"]
    quantity = variant.get("inventoryQuantity")
    return {
        "variant_id": str(variant["id"]), "product_id": product["id"], "title": product["title"],
        "variant": str(variant.get("title") or ""), "sku": str(variant.get("sku") or ""),
        "price": str(variant.get("price") or "0"),
        "available": quantity if isinstance(quantity, int) and not isinstance(quantity, bool) else None,
        "for_sale": bool(variant.get("availableForSale")),
        "size_from": found["from"], "size_to": found["to"],
    }, ""


# --------------------------------------------------------------------------- the read tools


def _session_and_branch() -> tuple[Any, Any]:
    from app.tools.context import CURRENT_SESSION, acting_branch

    session = CURRENT_SESSION.get()
    if session is None:
        raise ToolError("There is no conversation to build an order in.")
    return session, session.branch(acting_branch(session))


async def _resolve_customer(workspace: dict[str, Any]) -> list[str]:
    """Who the name means, if it means exactly one person. Never a best guess: the
    candidates are stored as they came back, and `_blocked` refuses everything until the
    owner has picked one."""
    name = ws.value(workspace, "customer")
    _set_customer(workspace, None)
    workspace["facts"].pop("candidates", None)
    if not name:
        return []
    try:
        found = await _candidates(_c(), name)
    except (ShopifyError, ToolError) as exc:
        log.info("the customer lookup did not answer: %s", exc)
        return []
    workspace["facts"]["candidates"] = found
    if len(found) == 1:
        return await _choose_customer(workspace, found[0]["customer_id"])
    return []


def choose_row(workspace: dict[str, Any], row: dict[str, Any]) -> list[str]:
    """One of the candidates, chosen. Synchronous, and that is not an accident: a recipe's
    `render` runs synchronously (app/recipes.py), so a tapped read can only ever choose from
    what it has already read. The `address` key is deliberately ABSENT here
    rather than empty — "not read yet" and "none on file" are different facts, and the card
    says which."""
    return _set_customer(workspace, {
        "customer_id": str(row["customer_id"]),
        "name": str(row.get("name") or ""),
        "email": str(row.get("email") or ""),
        "orders": str(row.get("orders") or "0"),
    })


async def _choose_customer(workspace: dict[str, Any], customer_id: str) -> list[str]:
    """The same customer, read authoritatively by id: their address as the shop holds it now.

    Run when the workspace is opened and again at the moment of preparing — never from a
    recipe, which cannot await — so the address on the confirmation card is a fresh read and
    not something carried from a search."""
    node = await _customer(_c(), customer_id)
    address = node.get("defaultAddress") or {}
    return _set_customer(workspace, {
        "customer_id": str(node["id"]),
        "name": str(node.get("displayName") or ""),
        "email": str(((node.get("defaultEmailAddress") or {}).get("emailAddress")) or ""),
        "orders": str(node.get("numberOfOrders") or "0"),
        "address": address_line(address) if address.get("address1") else "",
        # The same address as Shopify takes one, for holding the draft to it (`expected_card`).
        "postal": _mailing(address) if address.get("address1") else {},
    })


async def _customer_by_id(workspace: dict[str, Any], customer_id: str) -> list[str]:
    """A customer named by id — one a search or an order already showed this conversation —
    is who the order is for. There is no name to be ambiguous about, so there are no
    candidates to choose from: the one is the one."""
    moved = await _choose_customer(workspace, customer_id)
    chosen = _chosen_customer(workspace) or {}
    ws.type_into(workspace, FIELDS, "customer", chosen.get("name") or "")
    workspace["facts"]["candidates"] = [{k: chosen.get(k, "") for k in ("customer_id", "name", "email", "orders")}]
    workspace["facts"]["by_id"] = True
    return moved


async def _from_order(workspace: dict[str, Any], order_id: str) -> dict[str, Any]:
    """The order this one is made from: whose it is and where it went, read now. The address is
    that customer's and nobody else's (`_address_for_customer`)."""
    node = await _read_source(_c(), order_id)
    customer = node.get("customer") or {}
    if not customer.get("id"):
        raise ToolError(f"Order {node.get('name')} has no customer record, so a new order cannot be made for them from here.")
    address = _mailing(node.get("shippingAddress") or {})
    workspace["facts"]["source"] = {
        "order_id": str(node["id"]), "order_number": str(node.get("name") or ""),
        "customer_id": str(customer["id"]),
        "address": address if mailing_address_ok(address) else {},
        "line": address_line(address) if mailing_address_ok(address) else "",
    }
    if workspace["facts"]["source"]["address"]:
        ws.choose(workspace, _choices(workspace), "address", "order")
    return node


def _registered_lines(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    """The lines as the model is told them: numbered as the card numbers them."""
    rows = _rows(workspace)
    return [{"line": n, "title": line["title"], "variant": line.get("variant") or "", "custom": line["kind"] == "custom",
             "quantity": line["quantity"], "unit_price": f"{_unit(line):.2f}",
             "discount": _off_words(_off(line), each=True), "stock": rows[n - 1]["stock"],
             **({"variant_id": line["variant_id"]} if line.get("variant_id") else {})}
            for n, line in enumerate(_lines(workspace), start=1)]


def _state(workspace: dict[str, Any], session: Any) -> dict[str, Any]:
    """What an open or a change hands back: the order as it now stands, and its card."""
    chosen = _chosen_customer(workspace)
    if chosen:
        session.remember_pii(*[v for v in (chosen.get("name"), chosen.get("email"), chosen.get("address")) if v])
    for candidate in (ws.fact(workspace, "candidates") or []):
        session.remember_pii(*[v for v in (candidate.get("name"), candidate.get("email")) if v])
    source = ws.fact(workspace, "source") or {}
    if source.get("line"):
        session.remember_pii(source["line"])
    candidates = ws.fact(workspace, "candidates") or []
    picks = ws.fact(workspace, "picks") or []
    order_off = _order_off(workspace)
    return {
        "workspace_id": str(workspace["workspace_id"]),
        "customer_name": (chosen or {}).get("name") or "",
        "customer_id": (chosen or {}).get("customer_id") or "",
        "candidates": [] if (chosen and ws.fact(workspace, "by_id")) else
        [{"customer_name": c["name"], "email": c["email"], "orders": c["orders"]} for c in candidates],
        "ambiguous": chosen is None and len(candidates) > 1,
        "items": _registered_lines(workspace),
        "choices": [{"variant_id": p["variant_id"], "title": p.get("title"), "variant": p.get("variant"),
                     "price": p.get("price"), "stock": _stock_words(p.get("available"), p.get("for_sale"))[0]}
                    for p in picks],
        "goods": display(_goods(workspace)),
        "order_discount": _off_words(order_off, each=False),
        "postage": ws.value(workspace, "postage"),
        "ships_to": ws.chosen(workspace, "address", "customer"),
        "paid": ws.chosen(workspace, "payment", "pending") == "paid",
        "blocked": _blocked(workspace),
        "_surfaces": [workspace_surface(workspace).as_ui()],
        "staged": False,
    }


def _issued(session: Any, value: str) -> bool:
    return str(value or "") in (getattr(session, "issued_ids", None) or frozenset())


@tool(
    name=OPEN_TOOL,
    description=(
        "Put a new order on the owner's screen and return its workspace_id; creates nothing. "
        "For a customer by name or email, or customer_id, or order_id (their order: its "
        "customer and delivery address). item (words or SKU) or variant_id adds a line; "
        "size_step 1 with variant_id is the next size up. Several matches are named, never picked."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "customer": {"type": "string", "description": "Their name, or an email address."},
            "customer_id": {"type": "string"},
            "order_id": {"type": "string"},
            "item": {"type": "string"},
            "variant_id": {"type": "string"},
            "size_step": {"type": "integer", "minimum": -3, "maximum": 3},
            "quantity": {"type": "integer"},
            "note": {"type": "string"},
        },
    },
    # It names people. The assistant reads the identifying detail back rather than acting on
    # it, which is exactly what an ambiguous name needs.
    tier=Tier.AMBER,
    issued_id_args=("customer_id", "order_id", "variant_id"),
)
async def shopify_order_open(customer: str = "", item: str = "", quantity: int = 1, note: str = "",
                             customer_id: str = "", order_id: str = "", variant_id: str = "",
                             size_step: int = 0) -> dict[str, Any]:
    """The workspace, opened from what the owner said. A READ tool: the shop is asked who
    that is and what the item is, and nothing is created.

    "Who" is a name (which may be several people, and then none is chosen), a customer id a
    search already returned, or an ORDER of theirs — which also says where the last parcel
    went, and that is where this one goes unless he says otherwise. "What" is words, a SKU or
    a variant id; with `size_step` the variant is one of a found order's lines and the line
    added is the same garment that many sizes along (app/families/_sizes.py), or nothing, with
    the reason, when there is no such size.

    The `workspace_id` it returns is issued to the conversation, and that is what lets
    `shopify_order_create` be staged at all — so an order can only be prepared from a
    workspace whose card the owner has already read.
    """
    if not (str(customer or "").strip() or customer_id or order_id):
        raise ToolError("Say who the order is for: a name, an email, a customer_id or an order_id of theirs.")
    if size_step and not variant_id:
        raise ToolError("size_step steps from a variant: pass the variant_id of the line it is the next size of.")
    if not -3 <= int(size_step or 0) <= 3:
        raise ToolError("size_step is how many sizes along: 1 is the next size up, -1 the next down.")
    quantity, why = _quantity(quantity)
    if why:
        raise ToolError(why)
    session, branch = _session_and_branch()
    before = getattr(branch, "workspace", None)
    workspace = ws.open_workspace(
        branch, kind=KIND, workspace_id=ws.new_id(WORKSPACE_PREFIX),
        values={"customer": "", "email": "", "item": "", "quantity": "1", "discount": "", "postage": "", "note": ""},
        choices={"payment": "pending", "address": "customer", "discount_basis": "percent"},
        facts={"lines": []},
    )
    try:
        outcome = await _fill_opened(workspace, customer=customer, customer_id=customer_id, order_id=order_id,
                                     item=item, variant_id=variant_id, size_step=int(size_step or 0),
                                     quantity=quantity, note=note)
    except BaseException:
        # A read that failed half-way (the order gone, the shop not answering) leaves the
        # screen's own order as it was, rather than an empty form in its place.
        branch.workspace = before
        raise
    session.issue(str(workspace["workspace_id"]))
    return {
        **_state(workspace, session), **outcome,
        "note": (
            "The order is on the owner's screen and nothing is created. Change it with "
            f"{BUILD_TOOL}, lines by their number; Prepare the order is his tap, then a hold. "
            "If several customers or items matched, read them back and let him choose."
        ),
    }


async def _fill_opened(workspace: dict[str, Any], *, customer: str, customer_id: str, order_id: str, item: str,
                       variant_id: str, size_step: int, quantity: int, note: str) -> dict[str, Any]:
    """Who the new order is for and what is on it, read into a workspace just opened. Returns
    what the model should be told beyond the order itself: the size step's outcome, or why an
    item the owner named is not on it."""
    if order_id:
        source = await _from_order(workspace, str(order_id))
        owner = str((source.get("customer") or {}).get("id") or "")
        if customer_id and str(customer_id) != owner:
            raise ToolError(f"Order {source.get('name')} is not that customer's, so I will not mix them. Say which.")
        if variant_id and size_step:
            # The variant stepped from is "the line it is the next size of" (the tool's own
            # words): one on this order. Which line is the model's choice; that its choice is on
            # the order is checked here, so a variant of some other product is never stepped
            # and put on this customer's order (round 13, S2Ba/F-04).
            on_it = await _source_has_variant(_c(), source, str(variant_id))
            if on_it is None:
                raise ToolError(f"I could not read all of order {source.get('name')}'s lines, so I cannot check that "
                                "item is on it. Nothing was opened.")
            if not on_it:
                raise ToolError(f"That item is not on order {source.get('name')}, so I will not step its size for this "
                                "order. Use the variant_id of one of that order's lines.")
        customer_id = owner
    if customer_id:
        await _customer_by_id(workspace, str(customer_id))
    else:
        ws.type_into(workspace, FIELDS, "customer", customer)
        await _resolve_customer(workspace)
    if note:
        ws.type_into(workspace, FIELDS, "note", note)
    if variant_id and size_step:
        stepped, why = await _step_size(str(variant_id), size_step)
        if stepped is None:
            workspace["facts"]["item_note"] = why
            return {"size": {"ok": False, "why": why}}
        add_variant(workspace, stepped, quantity)
        return {"size": {"ok": True, "from": stepped["size_from"], "to": stepped["size_to"],
                         "stock": _stock_words(stepped.get("available"), stepped.get("for_sale"))[0]}}
    if variant_id:
        add_variant(workspace, await _candidate_for(str(variant_id)), quantity)
    elif item:
        found = await _add_by_words(workspace, str(item), quantity)
        if "none" in found:
            return {"item": found["none"]}
    return {}


_ADDRESS_SCHEMA = {
    "type": "object",
    "properties": {k: {"type": "string"} for k in ("address1", "address2", "city", "zip", "country_code")},
    "required": ["address1", "city", "zip", "country_code"],
}
# A discount said with a line or with an item: one of the two, never both.
_OFF = {"percent_off": {"type": "number"}, "amount_off": {"type": "number"}}


@tool(
    name=BUILD_TOOL,
    description=(
        "Change the new order on the owner's screen (from shopify_order_open); the card redraws, "
        "nothing is created. add: catalogue items (item words, SKU or variant_id) or custom "
        "(title, price). lines: by card number, quantity (0 removes) or a discount. "
        "percent_off/amount_off: on a line, amount_off is off each; at top level, off the "
        "order. Also postage, note, customer, ship_to or a new address, paid."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "string"},
            "add": {"type": "array", "items": {"type": "object", "properties": {
                "item": {"type": "string"}, "variant_id": {"type": "string"}, "title": {"type": "string"},
                "price": {"type": "number"}, "quantity": {"type": "integer"}, **_OFF}}},
            "lines": {"type": "array", "items": {"type": "object", "properties": {
                "line": {"type": "integer"}, "quantity": {"type": "integer"}, **_OFF}}},
            **_OFF,
            "postage": {"type": "number"},
            "note": {"type": "string"},
            "customer": {"type": "string"},
            "customer_id": {"type": "string"},
            "ship_to": {"type": "string", "enum": ["customer", "order", "none"]},
            "address": _ADDRESS_SCHEMA,
            "paid": {"type": "boolean"},
        },
    },
    tier=Tier.AMBER,
    issued_id_args=("workspace_id", "customer_id"),
)
async def shopify_order_build(workspace_id: str = "", add: list | None = None, lines: list | None = None,
                              percent_off: float | None = None, amount_off: float | None = None,
                              postage: float | None = None, note: str | None = None,
                              customer: str | None = None, customer_id: str = "",
                              ship_to: str | None = None, address: dict | None = None,
                              paid: bool | None = None) -> dict[str, Any]:
    """Every spoken change to the order being built, into the Mac's own copy, and the same
    card back. A READ tool: nothing outside the Mac moves, and nothing is staged.

    Each part of the request is applied on its own and reported on its own — `done` and
    `not_done` — because "add the hoodie and a print at twelve pounds" where the hoodie is
    four hoodies should still add the print, and should still say which four. Lines are named
    by the number the card shows them with, as the owner sees them; changes to lines are
    applied before new ones are added, so those numbers mean what he was looking at.
    """
    session, branch = _session_and_branch()
    workspace = ws.held(branch, KIND, str(workspace_id or ""))
    if workspace is None:
        raise ToolError("There is no order being built on this half. Open one with shopify_order_open.")
    if ws.is_put_away(workspace):
        raise ToolError(_put_away(workspace))
    made = already_made(workspace)
    if made:
        raise ToolError(made)
    if not any(v not in (None, "", []) for v in (add, lines, percent_off, amount_off, postage, note, customer,
                                                 customer_id, ship_to, address, paid)):
        raise ToolError("Say what to change on the order.")
    # A hold card prepared from the card as it was is for that; whether this changes what the
    # card would make is decided once every part of the request has been applied (below).
    before = ws.card_state(workspace)
    done: list[str] = []
    not_done: list[dict[str, Any]] = []

    if customer_id:
        moved = await _customer_by_id(workspace, str(customer_id))
        workspace["facts"].pop("draft", None)
        done.append(f"the customer is {(_chosen_customer(workspace) or {}).get('name')}")
        done += moved
    elif customer:
        ws.type_into(workspace, FIELDS, "customer", customer)
        workspace["facts"].pop("by_id", None)
        moved = await _resolve_customer(workspace)
        workspace["facts"].pop("draft", None)
        chosen = _chosen_customer(workspace)
        if chosen:
            done.append(f"the customer is {chosen['name']}")
            done += moved
        else:
            not_done.append({"asked": "customer", "why": _blocked(workspace)})

    _edit_lines(workspace, lines or [], done, not_done)

    for index, wanted in enumerate(add or []):
        if index >= MAX_ADDS:
            not_done.append({"asked": "the rest", "why": f"At most {MAX_ADDS} things are added in one go; say the rest again."})
            break
        await _add_one(workspace, wanted if isinstance(wanted, dict) else {}, session, done, not_done)

    if percent_off is not None or amount_off is not None:
        off, why = _discount(percent_off, amount_off)
        if why:
            not_done.append({"asked": "order discount", "why": why})
        else:
            ws.type_into(workspace, FIELDS, "discount", off["value"] if off else "")
            ws.choose(workspace, _choices(workspace), "discount_basis", off["type"] if off else "percent")
            _changed(workspace)
            done.append(f"{_off_words(off, each=False)} the order" if off else "no discount on the order")
    if postage is not None:
        amount = _number(postage)
        if amount is None or not 0 <= amount <= MAX_CUSTOM_LINE_PRICE:
            not_done.append({"asked": "postage", "why": POSTAGE_BOUND})
        else:
            ws.type_into(workspace, FIELDS, "postage", f"{round(amount, 2):g}" if amount > 0 else "")
            _changed(workspace)
            done.append(f"postage {display(amount)}" if amount > 0 else "no postage")
    if note is not None:
        ws.type_into(workspace, FIELDS, "note", note)
        _changed(workspace)
        done.append("the note" if str(note).strip() else "no note")
    if address:
        _given_address(workspace, address, done, not_done)
    elif ship_to:
        ok, why = ws.choose(workspace, _choices(workspace), "address", str(ship_to))
        if ok:
            _changed(workspace)
            done.append({"customer": "to the customer's own address", "order": "to the address on the order it came from",
                         "none": "with no delivery address"}[str(ship_to)])
        else:
            not_done.append({"asked": "ship_to", "why": "There is no order this was made from to take an address off."
                             if ship_to == "order" else why})
    if paid is not None:
        ws.choose(workspace, _choices(workspace), "payment", "paid" if paid else "pending")
        _changed(workspace)
        done.append("marked as already paid" if paid else "not paid — to be invoiced")
    _touch(session, workspace, before)
    return {
        **_state(workspace, session), "done": done, "not_done": not_done,
        "note": "On the owner's screen; nothing is created. Prepare the order is his tap, then a hold.",
    }


def _edit_lines(workspace: dict[str, Any], edits: list, done: list[str], not_done: list[dict[str, Any]]) -> None:
    """Quantities and discounts on lines already there, by the numbers the card shows."""
    current = _lines(workspace)
    keyed = {n: line["key"] for n, line in enumerate(current, start=1)}
    changed = False
    for edit in edits:
        edit = edit if isinstance(edit, dict) else {}
        number = edit.get("line")
        key = keyed.get(number) if isinstance(number, int) and not isinstance(number, bool) else None
        if key is None:
            not_done.append({"asked": f"line {number}", "why": f"There is no line {number}; the order has {len(current)}."})
            continue
        line = next((kept for kept in current if kept["key"] == key), None)
        if line is None:
            not_done.append({"asked": f"line {number}", "why": f"Line {number} was already taken off."})
            continue
        if "quantity" in edit and edit["quantity"] is not None:
            if _number(edit["quantity"]) == 0:
                current = [kept for kept in current if kept["key"] != key]
                done.append(f"took off {line['title']}")
                changed = True
                continue
            quantity, why = _quantity(edit["quantity"])
            if why:
                not_done.append({"asked": f"line {number}", "why": why})
                continue
            line["quantity"] = quantity
            done.append(f"{line['quantity']} x {line['title']}")
            changed = True
        if edit.get("percent_off") is not None or edit.get("amount_off") is not None:
            off, why = _discount(edit.get("percent_off"), edit.get("amount_off"))
            if not why and off and off["type"] == "amount" and float(off["value"]) > _unit(line):
                why = f"{display(float(off['value']))} off each is more than {line['title']} costs ({display(_unit(line))})."
            if why:
                not_done.append({"asked": f"discount on line {number}", "why": why})
                continue
            if off:
                line["off"] = off
            else:
                line.pop("off", None)
            done.append(f"{_off_words(off, each=True)} {line['title']}" if off else f"no discount on {line['title']}")
            changed = True
    if changed:
        _set_lines(workspace, current)


async def _add_one(workspace: dict[str, Any], wanted: dict[str, Any], session: Any,
                   done: list[str], not_done: list[dict[str, Any]]) -> None:
    """One thing onto the order: a catalogue variant by id, a catalogue item by words or SKU,
    or a custom item — then its own discount, if one was said with it."""
    quantity, why = _quantity(wanted.get("quantity"))
    if not why:
        off, why = _discount(wanted.get("percent_off"), wanted.get("amount_off"))
    if why:
        not_done.append({"asked": wanted.get("item") or wanted.get("title") or "an item", "why": why})
        return
    line: dict[str, Any] | None = None
    if len(_lines(workspace)) >= MAX_DRAFT_LINES:
        not_done.append({"asked": "an item", "why": f"An order made from here carries at most {MAX_DRAFT_LINES} lines."})
        return
    if wanted.get("variant_id") or str(wanted.get("item") or "").strip():
        try:
            line = await _catalogue_line(workspace, wanted, quantity, session, not_done)
        except ShopifyError:
            # The catalogue did not answer. Said, and the rest of the request still applies:
            # the card stays up with everything else he asked for on it.
            not_done.append({"asked": wanted.get("item") or "that item",
                             "why": "The shop did not answer about that item, so nothing was added for it. Ask again."})
            return
        except ToolError as exc:
            not_done.append({"asked": wanted.get("item") or "that item", "why": str(exc)})
            return
        if line is None:
            return
    elif wanted.get("title") is not None or wanted.get("price") is not None:
        title = _clean_title(wanted.get("title") or "")
        if not title or wanted.get("price") is None:
            not_done.append({"asked": title or "a custom item", "why": "A custom item needs a name and a price."})
            return
        price = _number(wanted["price"])
        if price is None or not 0 <= price <= MAX_CUSTOM_LINE_PRICE:
            not_done.append({"asked": title, "why": f"A custom item's price is between £0 and {display(MAX_CUSTOM_LINE_PRICE)}."})
            return
        line = add_custom(workspace, title, price, quantity)
    else:
        not_done.append({"asked": "an item", "why": "Say the item, its SKU, or a custom item's name and price."})
        return
    if off is not None:
        if off["type"] == "amount" and float(off["value"]) > _unit(line):
            not_done.append({"asked": f"discount on {line['title']}", "why": f"More than it costs ({display(_unit(line))})."})
        else:
            lines = _lines(workspace)
            for kept in lines:
                if kept["key"] == line["key"]:
                    kept["off"] = off
            _set_lines(workspace, lines)
    done.append(f"added {_line_words(next(k for k in _lines(workspace) if k['key'] == line['key']))}")


async def _catalogue_line(workspace: dict[str, Any], wanted: dict[str, Any], quantity: int, session: Any,
                          not_done: list[dict[str, Any]]) -> dict[str, Any] | None:
    """A catalogue item onto the order: a variant a read in this conversation returned, or the
    one variant the words describe. Several are left on the card as a choice, and none said."""
    if wanted.get("variant_id"):
        variant_id = str(wanted["variant_id"])
        if not _issued(session, variant_id):
            not_done.append({"asked": variant_id, "why": "That is not an item this conversation has looked up; search for it first."})
            return None
        return add_variant(workspace, await _candidate_for(variant_id), quantity)
    words = " ".join(str(wanted["item"]).split())[:60]
    found = await _add_by_words(workspace, words, quantity)
    if "none" in found:
        not_done.append({"asked": words, "why": found["none"]})
        return None
    if "choices" in found:
        not_done.append({"asked": words, "why": f"{len(found['choices'])} items match; they are on the card to choose from.",
                         "choices": [{"variant_id": c["variant_id"], "title": c.get("title"), "variant": c.get("variant"),
                                      "price": c.get("price")} for c in found["choices"]]})
        return None
    return found["added"]


def _given_address(workspace: dict[str, Any], said: dict[str, Any], done: list[str], not_done: list[dict[str, Any]]) -> None:
    """A delivery address the owner said, to the customer by name. Held to the same shape the
    draft's `shippingAddress` is (app/clients/shopify.py mailing_address_ok) before the card
    offers it, so what he reads is what can be sent."""
    chosen = _chosen_customer(workspace) or {}
    first, _, last = str(chosen.get("name") or "").partition(" ")
    address = _mailing({
        "firstName": first, "lastName": last, "address1": said.get("address1"), "address2": said.get("address2"),
        "city": said.get("city"), "zip": str(said.get("zip") or "").upper(),
        "countryCode": str(said.get("country_code") or "").upper(),
    })
    if not mailing_address_ok(address) or not address.get("zip") or not address.get("city"):
        not_done.append({"asked": "the address", "why": "That is not an address I can send: it needs a street, a town, a postcode and a two-letter country."})
        return
    workspace["facts"]["given_address"] = address
    # Whose name is on it: a change of customer puts the new one's there (`_address_for_customer`).
    workspace["facts"]["given_for"] = str(chosen.get("customer_id") or "")
    ws.choose(workspace, _choices(workspace), "address", "given")
    _changed(workspace)
    done.append(f"to {address_line(address)}")


# --------------------------------------------------------------------------- the write


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _off_input(off: dict[str, Any] | None) -> dict[str, Any] | None:
    if off is None:
        return None
    return {"title": "Discount", "value": float(off["value"]),
            "valueType": "PERCENTAGE" if off["type"] == "percent" else "FIXED_AMOUNT"}


def _off_sign(off: Any) -> tuple[str, float] | None:
    """A discount as a comparable pair, whichever side it came from: (valueType, value)."""
    if not isinstance(off, dict) or not off.get("valueType"):
        return None
    try:
        return str(off["valueType"]), round(float(off.get("value") or 0), 2)
    except (TypeError, ValueError):
        return None


def expected_signature(workspace: dict[str, Any]) -> list[Any]:
    """What the draft must carry for it to be this card: each line (the variant, or the custom
    title and price), its quantity and its discount, and the discount on the order."""
    lines = sorted(
        [[line["variant_id"] if line["kind"] == "variant" else f"custom:{line['title']}:{_unit(line):.2f}",
          int(line["quantity"]), _off_sign(_off_input(_off(line)))] for line in _lines(workspace)],
        key=lambda row: json.dumps(row, default=str),
    )
    return [lines, _off_sign(_off_input(_order_off(workspace)))]


def draft_signature(node: dict[str, Any]) -> list[Any]:
    """The same, read off the draft Shopify holds."""
    lines = []
    for edge in ((node.get("lineItems") or {}).get("edges") or []):
        line = (edge or {}).get("node") or {}
        variant = str(((line.get("variant") or {}).get("id")) or "")
        ident = variant or f"custom:{line.get('title')}:{_money(line.get('originalUnitPriceSet')) or 0:.2f}"
        lines.append([ident, int(line.get("quantity") or 0), _off_sign(line.get("appliedDiscount"))])
    lines.sort(key=lambda row: json.dumps(row, default=str))
    return [lines, _off_sign(node.get("appliedDiscount"))]


# The rest of what the owner reads on the card and holds, beside the lines: who it is for, where
# the confirmation goes, where the parcel goes, and the postage. Before round 12's independent
# check only the lines were held to the card, and a draft for somebody else, or to somewhere
# else, would have been offered as if it were the one he read.
_CARD_PARTS = (("customer", "the customer"), ("email", "the confirmation email"),
               ("address", "the delivery address"), ("postage", "the postage"))


def _address_key(address: Any) -> list[str] | None:
    """An address as it is compared: the street, the town, the postcode and the country, with
    case, spacing and the postcode's own space set aside — Shopify tidies those — and nothing
    else. None for no address."""
    if not isinstance(address, dict) or not str(address.get("address1") or "").strip():
        return None

    def fold(value: Any) -> str:
        return " ".join(str(value or "").split()).casefold()

    return [fold(address.get("address1")), fold(address.get("address2")), fold(address.get("city")),
            "".join(str(address.get("zip") or "").split()).upper(),
            str(address.get("countryCode") or address.get("countryCodeV2") or "").upper()]


def _going_to(workspace: dict[str, Any]) -> dict[str, Any] | None:
    """The address the card says the parcel goes to, as the Mac read it."""
    ship = ws.chosen(workspace, "address", "customer")
    if ship == "order":
        return (ws.fact(workspace, "source") or {}).get("address") or None
    if ship == "given":
        return ws.fact(workspace, "given_address") or None
    if ship == "customer":
        return (_chosen_customer(workspace) or {}).get("postal") or None
    return None


def expected_card(workspace: dict[str, Any]) -> dict[str, Any]:
    chosen = _chosen_customer(workspace) or {}
    postage = _decimal(ws.value(workspace, "postage")) if ws.status(workspace, "postage") == "ok" else None
    return {
        "customer": str(chosen.get("customer_id") or ""),
        # The confirmation address on the card. Left empty, the draft is sent none and Shopify
        # may give it the customer's own — which is then what the card says (`_present`).
        "email": ws.value(workspace, "email").strip().lower(),
        "email_if_none": str(chosen.get("email") or "").strip().lower(),
        "address": _address_key(_going_to(workspace)),
        "postage": f"{postage or 0.0:.2f}",
    }


def draft_card(node: dict[str, Any]) -> dict[str, Any]:
    """The same, read off the draft Shopify holds."""
    return {
        "customer": str(((node.get("customer") or {}).get("id")) or ""),
        "email": str(node.get("email") or "").strip().lower(),
        "address": _address_key(node.get("shippingAddress")),
        "postage": f"{_money(node.get('totalShippingPriceSet')) or 0.0:.2f}",
    }


def card_differences(expected: dict[str, Any], got: dict[str, Any]) -> list[str]:
    out = []
    for key, words in _CARD_PARTS:
        if key == "email" and not expected.get("email") and got.get("email") in ("", expected.get("email_if_none")):
            continue
        if expected.get(key) != got.get(key):
            out.append(words)
    return out


def _card_digest(card: dict[str, Any]) -> dict[str, str]:
    """Each part as a digest: what the proof compares, and never an address kept in the clear
    on a proposal."""
    return {key: _digest(card.get(key)) for key, _words in _CARD_PARTS}


def _joined(parts: list[str]) -> str:
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def _makes(workspace: dict[str, Any]) -> dict[str, Any]:
    """What this card would make (app/families/_workspace.py `makes`): who it is for, where the
    confirmation and the parcel go, every line and discount, the postage, the note and whether it
    is paid. Not what is typed into "Add an item" — a search is not an order — and not how the
    chosen customer's own address was last read, which Prepare reads again."""
    chosen = _chosen_customer(workspace) or {}
    return {
        "customer": chosen.get("customer_id"),
        "email": ws.value(workspace, "email"),
        "lines": expected_signature(workspace),
        "postage": ws.value(workspace, "postage"),
        "note": ws.value(workspace, "note"),
        "address": ws.chosen(workspace, "address", "customer"),
        "source": (ws.fact(workspace, "source") or {}).get("address"),
        "given": ws.fact(workspace, "given_address"),
        "paid": ws.chosen(workspace, "payment", "pending"),
    }


ws.makes(KIND, _makes)


def _line_fingerprint(workspace: dict[str, Any]) -> str:
    """A hash of everything a draft is built from, so a draft already made can be REUSED
    when nothing has changed and never when something has. Without this, preparing twice —
    a card that expired, a second epoch — leaves two drafts in Admin and completes one."""
    body = {k: v for k, v in _makes(workspace).items() if k != "paid"}
    # The customer's own address as read at this prepare: moved in Admin since the last
    # draft, it is a different draft.
    body["postal"] = (_chosen_customer(workspace) or {}).get("postal")
    return _digest(body)


def _draft_input(workspace: dict[str, Any]) -> dict[str, Any]:
    """The DraftOrderInput, built entirely from the Mac's copy. A catalogue line is a variant
    id and a quantity and Shopify prices it; a custom line is the owner's title and price,
    because the catalogue has none. Discounts are the owner's, as a percentage or an amount."""
    chosen = _chosen_customer(workspace) or {}
    items = []
    for line in _lines(workspace):
        if line["kind"] == "variant":
            entry: dict[str, Any] = {"variantId": str(line["variant_id"]), "quantity": int(line["quantity"])}
        else:
            entry = {"title": line["title"], "originalUnitPrice": f"{_unit(line):.2f}", "quantity": int(line["quantity"])}
        off = _off_input(_off(line))
        if off:
            entry["appliedDiscount"] = off
        items.append(entry)
    ship = ws.chosen(workspace, "address", "customer")
    body: dict[str, Any] = {
        "customerId": str(chosen["customer_id"]),
        "lineItems": items,
        "tags": [DRAFT_TAG],
        "useCustomerDefaultAddress": ship == "customer",
    }
    if ship == "order":
        body["shippingAddress"] = dict((ws.fact(workspace, "source") or {}).get("address") or {})
    elif ship == "given":
        body["shippingAddress"] = dict(ws.fact(workspace, "given_address") or {})
    email = ws.value(workspace, "email")
    if email:
        body["email"] = email
    note = ws.value(workspace, "note")
    if note:
        body["note"] = note
    postage = _decimal(ws.value(workspace, "postage"))
    if postage is not None and postage > 0:
        body["shippingLine"] = {"title": "Postage", "price": f"{postage:.2f}"}
    order_off = _off_input(_order_off(workspace))
    if order_off:
        body["appliedDiscount"] = order_off
    return body


async def _observe(execution: dict) -> Observed:
    node = await _read_draft(_c(), str(execution["draft_id"]))
    order = node.get("order") or {}
    if order.get("id"):
        # However it got there — this hold, a hold whose answer was lost, Admin — the draft is
        # an order now, and the card it was prepared from has made it (`finished`).
        ws.note(str(execution.get("workspace_id") or ""), ws.DONE, order_id=str(order["id"]),
                order_number=str(order.get("name") or ""), draft_id=str(execution.get("draft_id") or ""))
    return Observed(fingerprint={**draft_fingerprint(node), "as_prepared": ws.still_as_prepared(execution)}, entity={
        "draft_id": str(node.get("id") or ""), "draft_name": str(node.get("name") or ""),
        "status": str(node.get("status") or ""),
        "order_id": str(order.get("id") or ""), "order_number": str(order.get("name") or ""),
        "total": display(_money(node.get("totalPriceSet")), _currency(node.get("totalPriceSet"))),
        "customer_name": str((node.get("customer") or {}).get("displayName") or ""),
    })


async def _execute(execution: dict) -> dict:
    """The completion, and only the completion. The draft was made and priced at PREPARE
    time; this turns it into an order. `paymentPending` is what the owner chose on the
    workspace, decided on the Mac, and nothing new is decided here.

    The card is marked as sending BEFORE the mutation leaves: from then on Shopify may have
    made the order whether or not its answer arrives, and a card that could be prepared again
    in that state is how an order is made twice (`finished`). A completion Shopify refused, or
    one that never left, is noted as failed, and the card is his to prepare again
    (`ws.sending`)."""
    workspace_id = str(execution.get("workspace_id") or "")
    payload = await ws.sending(workspace_id, _c().mutate("draft_order_complete", {
        "id": str(execution["draft_id"]),
        "paymentPending": bool(execution["payment_pending"]),
    }), draft_name=str(execution.get("draft_name") or ""))
    body = ((payload.get("data") or {}).get("draftOrderComplete") or {}).get("draftOrder") or {}
    order = body.get("order") or {}
    if not order.get("id"):
        raise ShopifyError("Shopify did not confirm which order it created.")
    ws.note(workspace_id, ws.DONE, order_id=str(order["id"]), order_number=str(order.get("name") or ""),
            draft_id=str(execution.get("draft_id") or ""))
    return {"order_id": str(order["id"])}


def _verify(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    """Proof, by re-reading the draft: it is completed, and it now has an order on it.

    "Completed" alone would not do — a draft invoiced in Admin also leaves OPEN — so the
    order's own id is what is checked. The lines, who it is for, where it goes, the postage and
    the total are compared with the card because any of them moved means what the owner agreed
    to is not what was made: the order exists, and he is told what differs and to look at it.
    """
    if not str(observed.get("order") or ""):
        return False, ""
    if str(observed.get("status") or "").upper() != "COMPLETED":
        return False, ""
    differs = []
    if execution.get("lines") and str(observed.get("lines") or "") != str(execution["lines"]):
        differs.append("the lines")
    wanted, seen = execution.get("card") or {}, observed.get("card") or {}
    differs += [words for key, words in _CARD_PARTS if key in wanted and wanted.get(key) != seen.get(key)]
    if differs:
        return True, f"the order is not what the card said ({_joined(differs)}); check the order."
    if str(observed.get("total") or "") != str(execution.get("total") or ""):
        return True, "the order's total is not the figure on the card; check the order."
    return True, ""


def _present(proposal) -> dict:
    """The card, in EIGHT facts at most, because `app/presentation.py` carries eight and a
    ninth is silently dropped. The eight are chosen in the order they matter to somebody
    about to authorise a sale: who, where, what, what it costs, what they owe, and the draft
    it was priced as. The confirmation address rides on the customer's line rather than
    taking one of its own, and the postage rides on the goods."""
    s = proposal.summary
    currency = str(s.get("currency") or "GBP")
    postage = float(s.get("postage") or 0)
    goods = display(float(s.get("subtotal") or 0), currency)
    facts = [
        {"label": "Customer", "value": f"{s.get('customer') or ''} · {s.get('email') or 'no address'}"},
        {"label": "Going to", "value": str(s.get("address") or "no address on file"),
         "tone": "" if s.get("address") else "warn"},
        {"label": "Items", "value": str(s.get("lines") or "")},
        {"label": "Goods", "value": goods + (f" + {display(postage, currency)} postage" if postage else "")},
        {"label": "Total", "value": display(float(s.get("amount") or 0), currency), "tone": "warn"},
        {"label": "Payment", "value": str(s.get("payment_words") or ""), "tone": "bad" if s.get("owing") else ""},
        {"label": "Priced as", "value": f"draft {s.get('draft_name')}, which is in Admin now"},
    ]
    if s.get("discount_words"):
        facts.insert(4, {"label": "Discount", "value": str(s.get("discount_words")), "tone": "warn"})
    return {
        "title": "Create the order",
        "summary": "",
        "detail": (
            "Turns the draft Shopify has already priced into a real order. It cannot be undone "
            "from here; an order can be cancelled, which is a different change."
        ),
        "facts": facts,
        "done_title": "Order created",
    }


def _address_for_card(workspace: dict[str, Any], chosen: dict[str, Any]) -> str:
    ship = ws.chosen(workspace, "address", "customer")
    if ship == "order":
        return address_line((ws.fact(workspace, "source") or {}).get("address") or {})
    if ship == "given":
        return address_line(ws.fact(workspace, "given_address") or {})
    if ship == "none":
        return ""
    return str(chosen.get("address") or "")


def _discount_words(workspace: dict[str, Any]) -> str:
    """Every discount on the card, in one line: the order's, then each line's."""
    parts = []
    order_off = _order_off(workspace)
    if order_off:
        parts.append(f"{_off_words(order_off, each=False)} the order")
    parts += [f"{_off_words(_off(line), each=True)} {line['title']}" for line in _lines(workspace) if _off(line)]
    return "; ".join(parts)


@tool(
    name=WRITE_TOOL,
    description="Prepare the order the owner has on screen: Shopify prices it as a draft. Needs the workspace_id from shopify_order_open.",
    input_schema={
        "type": "object",
        "properties": {"workspace_id": {"type": "string", "description": "From shopify_order_open."}},
        "required": ["workspace_id"],
    },
    tier=Tier.RED,
    issued_id_args=("workspace_id",),
    write=WriteSpec(
        operation=OPERATION,
        entity_kind="draft_order",
        entity_arg="workspace_id",
        mutation="draft_order_complete",
        observe=_observe,
        execute=_execute,
        present=_present,
        verify=_verify,
        # Money: an order is created and either owed or taken. RED and money is the gravest
        # gesture this build has — a hold and a drag onto the target.
        op_class="money",
        reversible=False,
        # The precondition is the draft's state, its order, its lines and the rest of what the
        # card said (who, where to, postage), not its total: the total is on the fingerprint
        # for the proof, and a courtesy reading must not make a draft that has not moved look
        # changed.
        precondition_keys=("status", "order", "lines", "card", "as_prepared"),
        # Not "Order {label}": the label is the DRAFT's name ("#D12"), which is not the order's
        # number, and the card he held it from now shows the order's own number (`_made_surface`).
        spoken_success="The order is created, {amount}.",
        spoken_failure="I couldn't confirm the order was created. Look at the draft in Admin before asking again.",
        # The draft changed in Admin, or the card it was prepared from changed (`as_prepared`).
        spoken_stale="The order or its draft changed since this was prepared, so I haven't created it. Prepare it again.",
    ),
)
async def shopify_order_create(workspace_id: str) -> Prepared:
    """Prepare, never complete: re-read the customer, every catalogue variant and the address
    it goes to, ask Shopify to make and price the DRAFT, check the draft carries exactly what
    the card says, and hand the engine a change to hold.

    The draft is the reason the card can be honest. It is a real object in Admin — priced,
    tagged, not an order, nobody charged — so the total, the postage and what the customer
    will owe are Shopify's arithmetic on the thing about to become the order. The one
    mutation the gesture authorises is `draftOrderComplete`.
    """
    _session, branch = _session_and_branch()
    workspace = ws.held(branch, KIND, str(workspace_id))
    if workspace is None:
        raise ToolError("There is no order open on this half to create.")
    if ws.is_put_away(workspace):
        raise ToolError(_put_away(workspace))
    made = already_made(workspace)
    if made:
        raise ToolError(made)
    blocked = _blocked(workspace)
    if blocked:
        raise ToolError(blocked)

    client = _c()
    # A draft this card made that has become an order since — completed in Admin, or by a hold
    # whose answer never came back — means the order exists. Preparing again would make a second
    # draft of the same order, and a second hold a second order.
    for draft_id in list(ws.fact(workspace, "drafts_made") or [])[-MAX_DRAFTS_CHECKED:]:
        try:
            earlier = await _read_draft(client, str(draft_id))
        except ToolError:
            continue                 # deleted in Admin: it made nothing
        order = earlier.get("order") or {}
        if order.get("id"):
            ws.note(str(workspace["workspace_id"]), ws.DONE, order_id=str(order["id"]),
                    order_number=str(order.get("name") or ""), draft_id=str(draft_id))
            raise ToolError(already_made(workspace))
    chosen = _chosen_customer(workspace) or {}
    if not ws.fact(workspace, "by_id"):
        # The customer, re-read at the moment of preparing. A name that has become two people
        # since the workspace was opened — a duplicate made in Admin — must not be guessed at
        # now either, so the candidates are read again and a second match refuses it. (A
        # customer chosen BY ID, off an order or a search, has no name to be ambiguous about.)
        again = await _candidates(client, ws.value(workspace, "customer"))
        if len(again) > 1 and not any(c["customer_id"] == chosen.get("customer_id") for c in again):
            workspace["facts"]["candidates"] = again
            _set_customer(workspace, None)
            raise ToolError(f"{len(again)} customers now match that name; nothing was created. Choose one.")
    try:
        await _choose_customer(workspace, str(chosen["customer_id"]))
    except ToolError:
        # Read by id and gone: merged, deleted, or a request for erasure carried out. The
        # order must not be made for an id the shop no longer has.
        _set_customer(workspace, None)
        raise ToolError(
            f"{chosen.get('name') or 'That customer'} is not in the shop any more; nothing was created."
        ) from None
    chosen = _chosen_customer(workspace) or {}
    # Everything on the card that is about a person is this customer's, as re-read just now.
    not_theirs = _not_theirs(workspace, chosen)
    if not_theirs:
        raise ToolError(not_theirs)

    # Every catalogue line, priced by Shopify and checked for sale. A variant withdrawn since
    # it was added is refused here rather than making an order with a line nobody can fulfil.
    for line in _lines(workspace):
        if line["kind"] != "variant":
            continue
        variant = await _variant(client, str(line["variant_id"]))
        product = variant.get("product") or {}
        if str(product.get("status") or "ACTIVE").upper() != "ACTIVE" or not variant.get("availableForSale"):
            raise ToolError(f"{line['title']} is not for sale any more, so it cannot go on an order.")
    source = ws.fact(workspace, "source") or {}
    if ws.chosen(workspace, "address", "customer") == "order":
        # Where the last parcel went, read again: an address corrected on that order since
        # this one was opened is the address the owner means.
        node = await _read_source(client, str(source["order_id"]))
        if str((node.get("customer") or {}).get("id") or "") != str(chosen.get("customer_id") or ""):
            # Reassigned or merged in Admin since: its door is somebody else's now.
            raise ToolError(f"Order {source.get('order_number')} is not {chosen.get('name') or 'the customer'}'s order "
                            "any more, so its delivery address is not theirs to send to; nothing was created. "
                            "Choose where it goes.")
        address = _mailing(node.get("shippingAddress") or {})
        if not mailing_address_ok(address):
            raise ToolError(f"Order {source.get('order_number')} has no delivery address any more; nothing was created.")
        source["address"], source["line"] = address, address_line(address)
        workspace["facts"]["source"] = source

    fingerprint = _line_fingerprint(workspace)
    draft = ws.fact(workspace, "draft") or {}
    node: dict[str, Any] | None = None
    if draft.get("id") and draft.get("fingerprint") == fingerprint:
        # A draft this workspace already made, for exactly these lines. Reused rather than
        # duplicated: preparing twice must not leave two drafts in Admin.
        try:
            existing = await _read_draft(client, str(draft["id"]))
            if str(existing.get("status") or "").upper() == "OPEN" and not (existing.get("order") or {}).get("id"):
                node = existing
        except (ShopifyError, ToolError) as exc:
            log.info("the draft this workspace made could not be re-read: %s", exc)
    if node is None:
        payload = await client.mutate("draft_order_create", {"input": _draft_input(workspace)})
        node = ((payload.get("data") or {}).get("draftOrderCreate") or {}).get("draftOrder") or {}
        if not node.get("id"):
            raise ShopifyError("Shopify did not make the draft, so nothing has been priced.")
        workspace["facts"]["drafts_made"] = [*(ws.fact(workspace, "drafts_made") or []), str(node["id"])][-MAX_DRAFTS_CHECKED:]
    differs = (["the lines and discounts"] if draft_signature(node) != expected_signature(workspace) else []) \
        + card_differences(expected_card(workspace), draft_card(node))
    if differs:
        # Shopify made a draft that is not the card: a line it dropped, a discount it did not
        # apply, another customer, somewhere else to send it. The hold would authorise something
        # the owner has not read, so there is no hold. The draft is in Admin, tagged, and is
        # not an order.
        workspace["facts"].pop("draft", None)
        raise ToolError(
            f"Shopify's draft {node.get('name') or ''} does not carry exactly {_joined(differs)} on the card, "
            "so I have not offered it. Nothing was created; the draft is in Admin to look at."
        )
    workspace["facts"]["draft"] = {"id": str(node["id"]), "name": str(node.get("name") or ""), "fingerprint": fingerprint}
    # The card as this draft was made from it. The hold makes THIS draft, and the card may be
    # changed with a tap before it is held: once the order exists, it is drawn from this.
    prepared = dict(ws.fact(workspace, "prepared") or {})
    prepared[str(node["id"])] = {"lines": copy.deepcopy(_lines(workspace)), "values": dict(workspace.get("values") or {}),
                                 "choices": dict(workspace.get("choices") or {}),
                                 "customer": copy.deepcopy(ws.fact(workspace, "customer"))}
    workspace["facts"]["prepared"] = dict(list(prepared.items())[-MAX_DRAFTS_CHECKED:])

    currency = _currency(node.get("totalPriceSet"))
    total = _money(node.get("totalPriceSet"))
    subtotal = _money(node.get("subtotalPriceSet"))
    postage = _money(node.get("totalShippingPriceSet")) or 0.0
    if total is None:
        raise ShopifyError("Shopify did not price the draft; nothing was created.")
    pending = ws.chosen(workspace, "payment", "pending") != "paid"
    lines_words = ", ".join(_line_words(line) for line in _lines(workspace))
    read_back = (
        f"create an order for {chosen.get('name')}: {lines_words}, "
        f"{display(total, currency)}{', not paid' if pending else ', already paid'}"
    )
    lines_digest = _digest(draft_signature(node))
    card_digest = _card_digest(draft_card(node))
    ws.prepared(workspace)
    return Prepared(
        execution={
            "workspace_id": str(workspace["workspace_id"]),
            "draft_id": str(node["id"]),
            "draft_name": str(node.get("name") or ""),
            "payment_pending": pending,
            "total": f"{total:.2f}",
            "lines": lines_digest,
            "card": card_digest,
            # The card as it said when this was prepared: a hold card is held to it, and a card
            # changed since is stale (`_observe`, `ws.still_as_prepared`).
            "prepared_as": ws.card_state(workspace),
        },
        before={**draft_fingerprint(node), "as_prepared": "same"},
        expected_after={"status": "COMPLETED", "order": "", "total": f"{total:.2f}", "lines": lines_digest,
                        "card": card_digest},
        # The workspace is what the gate held to this conversation, and the draft is what the
        # mutation names; the entity the OWNER is authorising is the order about to exist, and
        # the draft's own name is how a person finds it.
        entity_ref=str(node["id"]),
        entity_label=str(node.get("name") or "the order"),
        summary={
            "customer": str(chosen.get("name") or ""),
            # Where the confirmation goes as the DRAFT says it, which `card_differences` has held
            # to the card: the one typed, or the customer's own when none was.
            "email": str(node.get("email") or ws.value(workspace, "email")),
            "address": _address_for_card(workspace, chosen),
            "lines": lines_words,
            "subtotal": f"{subtotal:.2f}" if subtotal is not None else "0.00",
            "postage": f"{postage:.2f}",
            # `amount` is what the spoken success line reads out (engine._spoken_amount).
            "amount": f"{total:.2f}",
            "currency": currency,
            "discount_words": _discount_words(workspace),
            "payment_words": ("not paid — it will owe the whole total" if pending else "marked as already paid"),
            "owing": pending,
            "draft_name": str(node.get("name") or ""),
            "read_back": read_back,
            "spoken_to": display(total, currency),
            "ledger": {"lines": len(_lines(workspace)), "total": f"{total:.2f}", "currency": currency[:24],
                       "pending": pending},
        },
    )


# --------------------------------------------------------------------------- the commands


def _no_workspace() -> Outcome:
    return Outcome.refused("no_workspace", "There is no order being built on this half.")


def _touch(session: Any, workspace: dict[str, Any], before: str) -> list[str]:
    """After a change: when the card would now make something else, the hold card prepared from
    it is withdrawn (`ws.touched`); and when the draft priced for it no longer carries what the
    card says, it is not this order any more. Paid or not is the completion's and not the
    draft's, so a draft outlives it and Prepare reuses it: no draft in Admin for nothing."""
    draft = ws.fact(workspace, "draft") or {}
    if draft and draft.get("fingerprint") != _line_fingerprint(workspace):
        workspace["facts"].pop("draft", None)
    return ws.touched(session, workspace, CHANGED, before=before)


def _withdrew(gone: list[str], changed: dict[str, Any]) -> dict[str, Any]:
    """A command's `changed`, naming the hold cards its change withdrew (`ws.touched`) and the
    line the tablet settles them with."""
    return {**changed, "withdrawn": gone, "withdrawn_words": CHANGED} if gone else changed


def _made(workspace: dict[str, Any]) -> Outcome:
    """A tap on a card that has made its order — one drawn before it did, still on a screen.
    Nothing it posts may build on the order again (`finished`)."""
    return Outcome.refused("already_created", already_made(workspace))


def _open(ctx: CommandCtx) -> Outcome:
    """A control. Opens an EMPTY workspace and reads nothing — a command is synchronous by
    design — so the customer is looked up by the recipe when a name is typed."""
    workspace = ws.open_workspace(
        ctx.branch, kind=KIND, workspace_id=ws.new_id(WORKSPACE_PREFIX),
        values={"customer": "", "email": "", "item": "", "quantity": "1", "discount": "", "postage": "", "note": ""},
        choices={"payment": "pending", "address": "customer", "discount_basis": "percent"},
        facts={"lines": []},
    )
    ctx.session.issue(str(workspace["workspace_id"]))
    return Outcome(answer="A new order, with nothing on it. Type who it is for.",
                   surfaces=[workspace_surface(workspace)],
                   changed={"workspace_id": str(workspace["workspace_id"]), "kind": KIND})


def _field(ctx: CommandCtx) -> Outcome:
    """A precision field, typed. The customer's name needs a read — who is that? — and a
    command cannot read, so it names the recipe and the route runs it."""
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id") or ctx.arg("compose_id"))
    if workspace is None:
        return _no_workspace()
    if already_made(workspace):
        return _made(workspace)
    name = ctx.arg("field")
    before, was = ws.card_state(workspace), ws.value(workspace, name)
    ok, why = ws.type_into(workspace, FIELDS, name, str(ctx.args.get("value") or ""))
    if not ok:
        return Outcome.refused("unknown_field", why)
    if name == "email":
        # Typed for whoever the order is for now; a change of customer takes it off
        # (`_email_for_customer`).
        chosen = _chosen_customer(workspace) or {}
        workspace["facts"]["email_for"] = {"customer_id": str(chosen.get("customer_id") or ""), "how": "typed"}
    if name == "customer" and ws.value(workspace, "customer") != was:
        # The name moved: whoever the card said it was is now about the old one, and so is
        # the address read off them.
        _set_customer(workspace, None)
        workspace["facts"].pop("candidates", None)
        workspace["facts"].pop("by_id", None)
        gone = _touch(ctx.session, workspace, before)
        if ws.value(workspace, "customer"):
            return Outcome(answer="", changed=_withdrew(gone, {"recipe": "order_customer",
                                                               "workspace_id": str(workspace["workspace_id"]), "field": name}))
    # Whether the hold card waiting still stands is what the card would MAKE: the same email
    # again, or a word typed into "Add an item", makes nothing else. (A draft already made is
    # reused only while it is exactly this card — `_line_fingerprint` at Prepare — so nothing
    # here has to throw it away.)
    gone = _touch(ctx.session, workspace, before)
    if name == "email" and ws.value(workspace, "email"):
        ctx.session.remember_pii(ws.value(workspace, "email"))
    return Outcome(answer="", surfaces=[workspace_surface(workspace)],
                   changed=_withdrew(gone, {"workspace_id": str(workspace["workspace_id"]), "field": name,
                                            "status": ws.status(workspace, name)}))


def _choose(ctx: CommandCtx) -> Outcome:
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    if already_made(workspace):
        return _made(workspace)
    before = ws.card_state(workspace)
    ok, why = ws.choose(workspace, _choices(workspace), ctx.arg("field"), ctx.arg("option"))
    if not ok:
        return Outcome.refused("unknown_choice", why)
    gone = _touch(ctx.session, workspace, before)
    return Outcome(answer="", surfaces=[workspace_surface(workspace)],
                   changed=_withdrew(gone, {"workspace_id": str(workspace["workspace_id"]), "chose": ctx.arg("option")}))


def _pick_customer(ctx: CommandCtx) -> Outcome:
    """One of the candidates, chosen by the owner. THIS is the answer to an ambiguous name,
    and it needs a read of its own — the address as the shop holds it — so it names the
    recipe rather than guessing from the row the tablet posted."""
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    if already_made(workspace):
        return _made(workspace)
    wanted = ctx.arg("customer_id")
    candidates = ws.fact(workspace, "candidates") or []
    if not any(c["customer_id"] == wanted for c in candidates):
        # Fail closed. The tablet may only choose one of the people the Mac itself found;
        # a posted id that was not among them is not a choice, it is a guess.
        return Outcome.refused("unknown_customer", "That is not one of the customers I found.")
    # The recipe reads who that is and chooses them, and says whether that changed the card.
    workspace["facts"]["chose_customer"] = wanted
    return Outcome(answer="", changed={"recipe": "order_customer", "workspace_id": str(workspace["workspace_id"]),
                                       "customer_id": wanted})


def _add_item(ctx: CommandCtx) -> Outcome:
    """Add an item. Two taps reach here: "Add the item" under the field, which needs the
    catalogue read and so names the recipe; and "Add" on one of the choices the card offered,
    which is a row the Mac itself read a moment ago and is added from that row. A posted
    variant that was not one of those choices is not a choice, and is refused."""
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    if already_made(workspace):
        return _made(workspace)
    if len(_lines(workspace)) >= MAX_DRAFT_LINES:
        return Outcome.refused("too_many", f"An order made from here carries at most {MAX_DRAFT_LINES} lines.")
    wanted = ctx.arg("variant_id")
    if wanted:
        pick = next((p for p in ws.fact(workspace, "picks") or [] if str(p.get("variant_id")) == wanted), None)
        if pick is None:
            return Outcome.refused("not_offered", "That is not one of the items this order offered; search for it again.")
        before = ws.card_state(workspace)
        quantity = int(ws.fact(workspace, "picks_quantity") or 1)
        add_variant(workspace, pick, quantity)
        ws.type_into(workspace, FIELDS, "item", "")
        ws.type_into(workspace, FIELDS, "quantity", "1")
        gone = _touch(ctx.session, workspace, before)
        return Outcome(answer=_spoken(workspace), surfaces=[workspace_surface(workspace)],
                       changed=_withdrew(gone, {"workspace_id": str(workspace["workspace_id"]), "added": wanted}))
    if not ws.value(workspace, "item"):
        return Outcome.refused("no_item", "Type a SKU, or the words for the item, first.")
    # Only a search so far: the recipe reads the catalogue, and an item it adds is the change.
    return Outcome(answer="", changed={"recipe": "order_line", "workspace_id": str(workspace["workspace_id"]),
                                       "slots": {"product": ws.value(workspace, "item")}})


def _remove_item(ctx: CommandCtx) -> Outcome:
    """A line taken off, named by its key on the card (or, as older cards did, its variant)."""
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    if already_made(workspace):
        return _made(workspace)
    key = ctx.arg("line") or (_key_for_variant(ctx.arg("variant_id")) if ctx.arg("variant_id") else "")
    current = _lines(workspace)
    lines = [line for line in current if line["key"] != key]
    if not key or len(lines) == len(current):
        return Outcome.refused("no_line", "There is no line for that on this order.")
    before = ws.card_state(workspace)
    _set_lines(workspace, lines)
    gone = _touch(ctx.session, workspace, before)
    return Outcome(answer="", surfaces=[workspace_surface(workspace)],
                   changed=_withdrew(gone, {"workspace_id": str(workspace["workspace_id"]), "removed": key}))


def _stage(ctx: CommandCtx) -> Outcome:
    """Prepare the order, tapped. Prepares the change; creates no order."""
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    if already_made(workspace):
        return _made(workspace)
    blocked = _blocked(workspace)
    if blocked:
        return Outcome.refused("not_ready", blocked)
    ident = str(workspace["workspace_id"])
    if ident not in (getattr(ctx.session, "issued_ids", None) or frozenset()):
        return Outcome.refused("not_held", "That is not an order this conversation opened.")
    return Outcome(answer="", changed={
        "workspace_id": ident,
        "stage": {"tool": WRITE_TOOL, "args": {"workspace_id": ident}, "what": "create the order"},
    })


def _discard(ctx: CommandCtx) -> Outcome:
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    draft = ws.fact(workspace, "draft") or {}
    made = finished(workspace)
    # A hold card for a card thrown away is not something to hold.
    gone = ws.withdraw(ctx.session, workspace, "The order was discarded.")
    ws.discard(ctx.branch)
    if made is not None:
        # The card goes; the order it made does not.
        return Outcome(answer=f"The card is put away; order {made.get('order_number') or ''} stays created."
                       if made.get("state") == "created" else "The card is put away. Look in Admin for the order it was sending.",
                       changed={"workspace": None, "discarded": str(workspace["workspace_id"])})
    tail = f" Draft {draft['name']} is still in Admin; delete it there if you do not want it." if draft.get("name") else ""
    return Outcome(answer=f"Gone. No order was created.{tail}",
                   changed={"workspace": None, "discarded": str(workspace["workspace_id"]),
                            "draft": draft.get("name") or None,
                            **({"withdrawn": gone, "withdrawn_words": "The order was discarded."} if gone else {})})


register_command(Command("order.open", "Start a new order", _open, voice=False))
register_command(Command("order.field", "Type into the order being built", _field, voice=False))
register_command(Command("order.choose", "Pick how the order is paid or where it goes", _choose, voice=False))
register_command(Command("order.customer", "Say which customer the order is for", _pick_customer, voice=False))
register_command(Command("order.additem", "Add the item named on the order being built", _add_item, voice=False))
register_command(Command("order.removeitem", "Take a line off the order being built", _remove_item, voice=False))
register_command(Command("order.stage", "Prepare the order for authorising", _stage, voice=False))
register_command(Command("order.discard", "Throw away the order being built", _discard, voice=False))


# --------------------------------------------------------------------------- the recipes
#
# Two reads, each run for a tap, and neither can stage: a recipe naming a write tool is a
# crash at start-up (app/recipes.py assert_read_only).


def _customer_plan(ctx: Ctx) -> ReadPlan | None:
    """Who the name means. The read is `shopify_find_customer`, the same tool the model uses
    to find Poppy, so the answer here and the answer there cannot disagree."""
    workspace = ws.held(ctx.branch, KIND)
    slots = ctx.slots or {}
    name = (ws.value(workspace, "customer") if workspace else "") or str(slots.get("customer") or "").strip()
    if not name:
        return None
    return ReadPlan([Read("customer", "shopify_find_customer", {"query": name[:80]},
                          source="shopify", cost=90.0, optional=False)], label="order_customer")


def _customer_render(ctx: Ctx, result: ReadResult) -> RecipeAnswer:
    workspace = ws.held(ctx.branch, KIND)
    if workspace is None:
        return RecipeAnswer(answer="", defer="the order was closed while the customer was being looked up")
    if already_made(workspace):
        # Made while this was being read: nothing read now goes onto it.
        return RecipeAnswer(answer=already_made(workspace), calls=list(result.calls), drawn=[],
                            surfaces=[workspace_surface(workspace)], partial=result.partial)
    body = result.values.get("customer")
    if not isinstance(body, dict):
        return RecipeAnswer(answer="", defer="the shop did not answer about that customer")
    before = ws.card_state(workspace)
    found = [c for c in (body.get("customers") or []) if isinstance(c, dict) and c.get("customer_id")]
    workspace["facts"]["candidates"] = [
        {"customer_id": str(c["customer_id"]), "name": str(c.get("name") or ""),
         "email": str(c.get("email") or ""), "orders": str(c.get("orders") or "0")}
        for c in found[:MAX_CANDIDATES]
    ]
    wanted = str(ws.fact(workspace, "chose_customer") or "")
    workspace["facts"].pop("chose_customer", None)
    _set_customer(workspace, None)
    workspace["facts"].pop("by_id", None)
    one = next((c for c in workspace["facts"]["candidates"] if c["customer_id"] == wanted), None)
    if one is None and len(workspace["facts"]["candidates"]) == 1:
        one = workspace["facts"]["candidates"][0]
    if one is not None:
        choose_row(workspace, one)
    # Another customer is another order; the one already chosen, chosen again, is not.
    _touch(ctx.session, workspace, before)
    chosen = _chosen_customer(workspace)
    if chosen:
        ctx.session.remember_pii(*[v for v in (chosen.get("name"), chosen.get("email"), chosen.get("address")) if v])
    for candidate in workspace["facts"]["candidates"]:
        ctx.session.remember_pii(*[v for v in (candidate.get("name"), candidate.get("email")) if v])
    return RecipeAnswer(
        answer=_spoken(workspace), calls=list(result.calls), drawn=[],
        surfaces=[workspace_surface(workspace)], partial=result.partial,
        trace={"candidates": len(workspace["facts"]["candidates"]), "chosen": bool(chosen)},
    )


def _line_plan(ctx: Ctx) -> ReadPlan | None:
    workspace = ws.held(ctx.branch, KIND)
    slots = ctx.slots or {}
    words = (str(slots.get("product") or "") or (ws.value(workspace, "item") if workspace else "")).strip()
    if not words:
        return None
    return ReadPlan([Read("variants", SEARCH_TOOL, {"product": words[:60], "limit": 8},
                          source="shopify", cost=90.0, optional=False)], label="order_line")


def _line_render(ctx: Ctx, result: ReadResult) -> RecipeAnswer:
    """Add the line when exactly one variant matches, and never when several do.

    Four hoodies match "hoodie", and choosing one of them for the owner is the same mistake
    as choosing one of two customers called Jones — it is just cheaper to discover. So the
    candidates go on the card as a choice, each with its own Add, and nothing is added.
    """
    workspace = ws.held(ctx.branch, KIND)
    if workspace is None:
        return RecipeAnswer(answer="", defer="the order was closed while the catalogue was being read")
    if already_made(workspace):
        # Made while this was being read: nothing read now goes onto it.
        return RecipeAnswer(answer=already_made(workspace), calls=list(result.calls), drawn=[],
                            surfaces=[workspace_surface(workspace)], partial=result.partial)
    body = result.values.get("variants")
    if not isinstance(body, dict):
        return RecipeAnswer(answer="", defer="the catalogue did not answer")
    candidates = [c for c in (body.get("candidates") or []) if isinstance(c, dict) and c.get("variant_id")]
    words = str((ctx.slots or {}).get("product") or ws.value(workspace, "item"))
    quantity = int(ws.value(workspace, "quantity", "1") or 1) if ws.status(workspace, "quantity") == "ok" else 1
    before = ws.card_state(workspace)
    found = offer(workspace, candidates, words, quantity)
    if "added" in found:
        ws.type_into(workspace, FIELDS, "item", "")
        ws.type_into(workspace, FIELDS, "quantity", "1")
    # An item added is a change to what the card makes; a choice offered is not yet.
    _touch(ctx.session, workspace, before)
    return RecipeAnswer(
        answer=_spoken(workspace), calls=list(result.calls), drawn=[],
        surfaces=[workspace_surface(workspace)], partial=result.partial,
        trace={"lines": len(_lines(workspace)), "matched": len(candidates)},
    )


register(Recipe(
    recipe_id="order_customer",
    read_primitives=("shopify_find_customer",), parallel_nodes=(("customer",),), ui="workspace",
    cache_policy=CACHE_NONE, target_ms=1200,
    plan=_customer_plan, render=_customer_render,
))

register(Recipe(
    recipe_id="order_line",
    read_primitives=(SEARCH_TOOL,), parallel_nodes=(("variants",),), ui="workspace",
    cache_policy=CACHE_NONE, target_ms=1200,
    plan=_line_plan, render=_line_render,
))

# --------------------------------------------------------------------------- the capability


async def _probe(runtime: Any) -> dict[str, Any]:
    """Whether this Mac could create an order right now. One read — the scopes the store has
    granted — and never a mutation.

    `write_draft_orders` covers both halves of the change, and `read_draft_orders` is what
    lets the completion be PROVEN: without it the draft cannot be re-read, and a change that
    cannot be verified is not one this build offers.
    """
    try:
        granted = set(await runtime.shopify.access_scopes())
    except Exception as exc:  # noqa: BLE001 — Shopify not answering is not a missing grant
        return {"state": "TEMPORARILY_UNAVAILABLE",
                "detail": f"the Shopify scope check did not answer ({type(exc).__name__})", "scope": SCOPE}
    if SCOPE not in granted:
        return {"state": "MISSING_SCOPE",
                "detail": f"the store has not granted {SCOPE}; add it on the Dev Dashboard and approve it in the store admin",
                "scope": SCOPE}
    if READ_SCOPE not in granted:
        return {"state": "MISSING_SCOPE",
                "detail": (f"the store has granted {SCOPE} but not {READ_SCOPE}, so the order could be created "
                           "and not proven — which is not a change this build will make"),
                "scope": READ_SCOPE}
    return {"state": "READY", "detail": "ready — an order can be made from a priced draft", "scope": SCOPE}


register_family(CapabilityFamily(
    key="order_create",
    label="Making an order",
    area="orders",
    what=("Build an order for a customer — catalogue or custom items, quantities, discounts on a line or the "
          "order, postage, paid or not — priced by Shopify as a draft before you authorise it"),
    operations=(OPERATION,),
    tools=(OPEN_TOOL, BUILD_TOOL, WRITE_TOOL),
    scopes=(SCOPE,),
    state="READY",
    probe=_probe,
))

__all__ = [
    "BUILD_TOOL", "CHOICES", "DRAFT_TAG", "FIELDS", "FIELD_NAMES", "KIND", "OPEN_TOOL", "OPERATION",
    "SCOPE", "WRITE_TOOL", "display", "draft_fingerprint", "draft_signature", "expected_signature",
    "where_line", "workspace_surface",
]
