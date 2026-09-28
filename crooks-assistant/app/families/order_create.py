"""Making an order from nothing (brief §11): a workspace, a draft, and one reviewed complete.

"Create an order for Poppy De-Witt" was refused all through Phase 2, and the reason it is
hard is not the mutation — it is that an order has about nine facts in it and a conversation
is the wrong instrument for collecting nine facts. Phase 2's shape would have been: who is
it for? what is on it? how many? is it paid? — four round trips to a language model, each
one a place to mishear a name, and at the end a change proposed from what the model was
holding in its head.

So the shape here is a WORKSPACE, not a questionnaire:

    "create an order for Poppy"   →  shopify_order_open   a read: which customer is that?
    typing, tapping, speaking     →  order.field/.choose/.additem
    Prepare                       →  draftOrderCreate     Shopify prices a DRAFT
    the hold on the card          →  draftOrderComplete   the one mutation

Four things about it are deliberate.

**The draft is the reviewable intermediate, and that is the whole reason to use it.** PREPARE
runs `draftOrderCreate`, which makes a draft order: a real object, visible in Admin, priced
by Shopify, for which nobody is charged and which is not an order. So every number on the
card the owner holds — the line prices, the postage, the total — is Shopify's own arithmetic
on the thing about to become the order, and not ours and never the model's. The draft is
tagged so it is findable, and the card says it exists: a prepare the owner walks away from
leaves a draft in Admin, which is exactly what building an order in Admin leaves too.

**An ambiguous customer is refused, not guessed.** Two people called Jones is the commonest
real case, and the wrong one is a stranger's order with somebody else's address on it. So
the read finds the candidates, the workspace names them, and the button that would prepare
anything stays off until one of them is chosen. The same rule applies to an item: four
hoodies match "hoodie", and none of them is added.

**Nothing that reaches the mutation comes from the tablet.** The tablet posts a workspace id,
a field name and characters. The variant ids, the prices, the customer id, the postage and
the payment state are read and built on the Mac from the Mac's own copy of the workspace.

**The order is never created because the model thinks it has enough.** `shopify_order_create`
refuses to prepare a workspace `_blocked` says is not ready, whoever asks; and the model
cannot reach the mutation at all — it can open a workspace and fill it, and the gesture is
the owner's.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from app.actions.models import Observed, Prepared
from app.capabilities.families import CapabilityFamily
from app.capabilities.families import register as register_family
from app.clients.shopify import MAX_DRAFT_LINES, MAX_DRAFT_QUANTITY, ShopifyClient, ShopifyError
from app.commands import Command, Outcome
from app.commands import Ctx as CommandCtx
from app.commands import register as register_command
from app.families import _workspace as ws
from app.reads.scheduler import Read, ReadPlan, ReadResult
from app.recipes import CACHE_NONE, Ctx, Recipe, RecipeAnswer, register
from app.tools.gate import Tier
from app.tools.registry import ToolError, WriteSpec, tool
from app.tools.shopify_tools import _c
from app.tools.shopify_writes import VARIANT_FOR_EDIT_QUERY, address_line

log = logging.getLogger("crooks.families.order_create")

KIND = "order_draft"
WORKSPACE_PREFIX = "ord"
OPEN_TOOL = "shopify_order_open"
WRITE_TOOL = "shopify_order_create"
SEARCH_TOOL = "shopify_variant_search"
OPERATION = "draft_order_complete"
SCOPE = "write_draft_orders"
READ_SCOPE = "read_draft_orders"

MAX_CANDIDATES = 5
MAX_NOTE_CHARS = 300
DRAFT_TAG = "CROOKS assistant"


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

DRAFT_ORDER_QUERY = """
query CrooksDraftOrder($id: ID!) {
  draftOrder(id: $id) {
    id
    name
    status
    totalPriceSet { shopMoney { amount currencyCode } }
    subtotalPriceSet { shopMoney { amount currencyCode } }
    totalShippingPriceSet { shopMoney { amount currencyCode } }
    order { id name }
    customer { id displayName }
    email
    lineItems(first: 20) {
      edges { node { title quantity variantTitle originalUnitPriceSet { shopMoney { amount currencyCode } } } }
    }
  }
}
"""


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


def draft_fingerprint(node: dict[str, Any]) -> dict[str, Any]:
    """What the draft must still look like for this completion to be the one prepared.

    `order` is the whole precondition: a draft already completed has an order on it, and
    completing it again is what "execute at most once" is about at Shopify's end as well as
    at ours. `status` catches a draft cancelled or invoiced in Admin meanwhile; `total`
    catches a line changed there, which would make the money on the card a lie.
    """
    total = _money(node.get("totalPriceSet"))
    return {
        "status": str(node.get("status") or ""),
        "order": str(((node.get("order") or {}).get("id")) or ""),
        "total": f"{total:.2f}" if total is not None else "",
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


def _clean_decimal(raw: str) -> tuple[str, str, str]:
    said = str(raw or "").strip().replace(",", "").lstrip("£$€").rstrip("%")
    if not said:
        return "", "ok", ""
    try:
        amount = round(float(said), 2)
    except ValueError:
        return said[:10], "invalid", f"{said[:20]!r} is not a number."
    if amount < 0:
        return f"{amount:g}", "invalid", "It cannot be negative."
    return f"{amount:g}", "ok", ""


def _clean_note(raw: str) -> tuple[str, str, str]:
    return str(raw or "").replace("\r\n", "\n")[:MAX_NOTE_CHARS], "ok", ""


FIELDS: tuple[ws.Field, ...] = (
    ws.Field(name="customer", label="For", kind="text", placeholder="the customer's name", maxlength=80, rows=1, clean=_clean_name),
    ws.Field(name="email", label="Confirmation to", kind="email", placeholder="their address", maxlength=254, clean=_clean_email),
    ws.Field(name="item", label="Add an item", kind="sku", placeholder="a SKU, or the words", maxlength=60, clean=_clean_words),
    ws.Field(name="quantity", label="How many", kind="quantity", placeholder="1", maxlength=4, clean=_clean_quantity),
    ws.Field(name="discount", label="Per cent off", kind="money", placeholder="none", maxlength=6, clean=_clean_decimal),
    ws.Field(name="postage", label="Postage", kind="money", placeholder="none", maxlength=8, clean=_clean_decimal),
    ws.Field(name="note", label="Note", kind="text", placeholder="on the order", maxlength=MAX_NOTE_CHARS, rows=2, clean=_clean_note),
)
FIELD_NAMES = tuple(f.name for f in FIELDS)

CHOICES: tuple[ws.Choice, ...] = (
    ws.Choice(name="payment", label="Payment",
              options=(("pending", "Not paid — invoice it"), ("paid", "Already paid"))),
    ws.Choice(name="address", label="Where it goes",
              options=(("customer", "The customer's own address"), ("none", "No address"))),
)


def _lines(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    lines = ws.fact(workspace, "lines")
    return [dict(line) for line in lines] if isinstance(lines, list) else []


def _chosen_customer(workspace: dict[str, Any]) -> dict[str, Any] | None:
    found = ws.fact(workspace, "customer")
    return dict(found) if isinstance(found, dict) and found.get("customer_id") else None


def _blocked(workspace: dict[str, Any]) -> str:
    """Why this cannot be prepared yet, in the owner's words. Empty when it can.

    The two that matter are the two the brief names: an ambiguous customer, and no items.
    Neither is a thing to guess at — the first would put a stranger's address on somebody
    else's order, and the second would make an empty order nobody asked for.
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
    if ws.status(workspace, "email") != "ok":
        return "That is not an address the confirmation could go to."
    lines = _lines(workspace)
    if not lines:
        return "It has nothing on it. Add an item."
    if len(lines) > MAX_DRAFT_LINES:
        return f"An order made from here carries at most {MAX_DRAFT_LINES} lines."
    for name in ("discount", "postage", "quantity"):
        if ws.status(workspace, name) != "ok":
            return f"The {name} is not a number I can use."
    discount = _decimal(ws.value(workspace, "discount"))
    if discount is not None and not 0 < discount <= 100:
        return "A discount is a percentage between 1 and 100."
    return ""


def _decimal(value: str) -> float | None:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _goods(workspace: dict[str, Any]) -> float:
    return round(sum(float(line["price"]) * int(line["quantity"]) for line in _lines(workspace)), 2)


def _facts(workspace: dict[str, Any]) -> list[dict[str, Any]]:
    """What the Mac has read and worked out, for the form. Deliberately NOT the total the
    owner will authorise: that number is Shopify's, it comes off the draft, and it appears on
    the confirmation card. A total computed here and printed beside Shopify's would be two
    numbers that can disagree."""
    rows: list[dict[str, Any]] = []
    chosen = _chosen_customer(workspace)
    candidates = ws.fact(workspace, "candidates") or []
    if chosen:
        rows.append({"label": "Customer", "value": f"{chosen['name']} · {chosen.get('email') or 'no address on file'}", "tone": "ok"})
        if ws.chosen(workspace, "address", "customer") != "customer":
            rows.append({"label": "Address", "value": "none — the order carries no shipping address"})
        elif chosen.get("address"):
            rows.append({"label": "Address", "value": str(chosen["address"])})
        elif "address" in chosen:
            # Read, and there is none. Different from "not read yet", which is the case below.
            rows.append({"label": "Address", "value": "none on file — it will be made without one", "tone": "warn"})
        else:
            rows.append({"label": "Address", "value": "the customer's own, read when you prepare it"})
    elif len(candidates) > 1:
        for candidate in candidates[:MAX_CANDIDATES]:
            rows.append({"label": "Could be", "value": f"{candidate['name']} · {candidate.get('email') or 'no address'} · {candidate['orders']} orders", "tone": "warn"})
    for line in _lines(workspace):
        variant = f" ({line['variant']})" if line.get("variant") else ""
        rows.append({"label": "Item", "value": f"{line['quantity']} x {line['title']}{variant} at {display(float(line['price']))}"})
    if _lines(workspace):
        rows.append({"label": "Goods", "value": display(_goods(workspace))})
    if ws.value(workspace, "postage"):
        rows.append({"label": "Postage", "value": display(_decimal(ws.value(workspace, "postage")))})
    if ws.value(workspace, "discount"):
        rows.append({"label": "Discount", "value": f"{_decimal(ws.value(workspace, 'discount')):g}% off", "tone": "warn"})
    rows.append({"label": "Payment", "value": "already paid" if ws.chosen(workspace, "payment", "pending") == "paid" else "not paid — invoice it"})
    if ws.fact(workspace, "item_note"):
        rows.append({"label": "That item", "value": str(ws.fact(workspace, "item_note")), "tone": "warn"})
    draft = ws.fact(workspace, "draft") or {}
    if draft.get("name"):
        rows.append({"label": "Draft", "value": f"{draft['name']} is in Admin, priced and not an order yet"})
    return rows


def _notes(workspace: dict[str, Any]) -> list[str]:
    notes = [
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
    chosen = _chosen_customer(workspace)
    blocked = _blocked(workspace)
    lines = _lines(workspace)
    return ws.surface(
        workspace, fields=FIELDS, choices=CHOICES,
        kicker="A new order · not created",
        title=(chosen["name"] if chosen else ws.value(workspace, "customer")) or "A new order",
        subtitle=(f"{len(lines)} line{'s' if len(lines) != 1 else ''}, {display(_goods(workspace))} of goods"
                  if lines else "nothing on it yet"),
        facts=_facts(workspace), notes=_notes(workspace), actions=ACTIONS,
        field_command="order.field", blocked=blocked,
        spoken="Nothing is created until you hold the card that follows.",
    )


def _spoken(workspace: dict[str, Any]) -> str:
    """The grounded half of the answer: what the Mac read and what it is waiting for. When a
    recipe draws this workspace it LEADS the answer and Claude's words follow it."""
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
    what = ", ".join(f"{line['quantity']} x {line['title']}" for line in lines) or "nothing on it yet"
    tail = f" {blocked}" if blocked else " Hold the card to create it."
    return f"An order for {who}: {what}, {display(_goods(workspace))} of goods.{tail}"


# --------------------------------------------------------------------------- the read tool


def _session_and_branch() -> tuple[Any, Any]:
    from app.tools.context import CURRENT_SESSION, acting_branch

    session = CURRENT_SESSION.get()
    if session is None:
        raise ToolError("There is no conversation to build an order in.")
    return session, session.branch(acting_branch(session))


async def _resolve_customer(workspace: dict[str, Any]) -> None:
    """Who the name means, if it means exactly one person. Never a best guess: the
    candidates are stored as they came back, and `_blocked` refuses everything until the
    owner has picked one."""
    name = ws.value(workspace, "customer")
    workspace["facts"].pop("customer", None)
    workspace["facts"].pop("candidates", None)
    if not name:
        return
    try:
        found = await _candidates(_c(), name)
    except (ShopifyError, ToolError) as exc:
        log.info("the customer lookup did not answer: %s", exc)
        return
    workspace["facts"]["candidates"] = found
    if len(found) == 1:
        await _choose_customer(workspace, found[0]["customer_id"])


def choose_row(workspace: dict[str, Any], row: dict[str, Any]) -> None:
    """One of the candidates, chosen. Synchronous, and that is not an accident: a recipe's
    `render` runs synchronously (app/recipes.py), so a tapped read can only ever choose from
    what it has already read. The `address` key is deliberately ABSENT here
    rather than empty — "not read yet" and "none on file" are different facts, and the card
    says which."""
    workspace["facts"]["customer"] = {
        "customer_id": str(row["customer_id"]),
        "name": str(row.get("name") or ""),
        "email": str(row.get("email") or ""),
        "orders": str(row.get("orders") or "0"),
    }
    if not ws.value(workspace, "email") and row.get("email"):
        ws.type_into(workspace, FIELDS, "email", str(row["email"]))


async def _choose_customer(workspace: dict[str, Any], customer_id: str) -> None:
    """The same customer, read authoritatively by id: their address as the shop holds it now.

    Run when the workspace is opened and again at the moment of preparing — never from a
    recipe, which cannot await — so the address on the confirmation card is a fresh read and
    not something carried from a search."""
    node = await _customer(_c(), customer_id)
    address = node.get("defaultAddress") or {}
    workspace["facts"]["customer"] = {
        "customer_id": str(node["id"]),
        "name": str(node.get("displayName") or ""),
        "email": str(((node.get("defaultEmailAddress") or {}).get("emailAddress")) or ""),
        "orders": str(node.get("numberOfOrders") or "0"),
        "address": address_line(address) if address.get("address1") else "",
    }
    if not ws.value(workspace, "email"):
        ws.type_into(workspace, FIELDS, "email", workspace["facts"]["customer"]["email"])


@tool(
    name=OPEN_TOOL,
    description=(
        "Put a new order on the owner's screen as fields, having first looked the customer up, "
        "and return its workspace_id. Creates nothing. If several customers match the name it "
        "says so and picks none."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "customer": {"type": "string", "maxLength": 80, "description": "Their name, or an email address."},
            "item": {"type": "string", "maxLength": 60, "description": "A SKU or the words for one item."},
            "quantity": {"type": "integer", "minimum": 1, "maximum": MAX_DRAFT_QUANTITY},
            "note": {"type": "string", "maxLength": MAX_NOTE_CHARS},
        },
        "required": ["customer"],
    },
    # It names people. The assistant reads the identifying detail back rather than acting on
    # it, which is exactly what an ambiguous name needs.
    tier=Tier.AMBER,
)
async def shopify_order_open(customer: str, item: str = "", quantity: int = 1, note: str = "") -> dict[str, Any]:
    """The workspace, opened from what the owner said. A READ tool: the shop is asked who
    that name means and nothing is created.

    The `workspace_id` it returns is issued to the conversation, and that is what lets
    `shopify_order_create` be staged at all — so an order can only be prepared from a
    workspace whose card the owner has already read.
    """
    session, branch = _session_and_branch()
    workspace = ws.open_workspace(
        branch, kind=KIND, workspace_id=ws.new_id(WORKSPACE_PREFIX),
        values={"customer": "", "email": "", "item": "", "quantity": "1", "discount": "", "postage": "", "note": ""},
        choices={"payment": "pending", "address": "customer"},
        facts={"lines": []},
    )
    ws.type_into(workspace, FIELDS, "customer", customer)
    if note:
        ws.type_into(workspace, FIELDS, "note", note)
    if item:
        ws.type_into(workspace, FIELDS, "item", item)
        ws.type_into(workspace, FIELDS, "quantity", str(quantity))
    await _resolve_customer(workspace)
    chosen = _chosen_customer(workspace)
    session.issue(str(workspace["workspace_id"]))
    if chosen:
        session.remember_pii(*[v for v in (chosen.get("name"), chosen.get("email"), chosen.get("address")) if v])
    for candidate in (ws.fact(workspace, "candidates") or []):
        session.remember_pii(*[v for v in (candidate.get("name"), candidate.get("email")) if v])
    return {
        "workspace_id": str(workspace["workspace_id"]),
        "customer_name": (chosen or {}).get("name") or "",
        "customer_id": (chosen or {}).get("customer_id") or "",
        "candidates": [{"customer_name": c["name"], "email": c["email"], "orders": c["orders"]}
                       for c in (ws.fact(workspace, "candidates") or [])],
        "ambiguous": len(ws.fact(workspace, "candidates") or []) > 1,
        "blocked": _blocked(workspace),
        "_surfaces": [workspace_surface(workspace).as_ui()],
        "staged": False,
        "note": (
            "The order is on the owner's screen and nothing is created. Add items with "
            "order.additem on the card; the owner's gesture on Prepare the order stages it, "
            "and a hold on the card that follows creates it. If several customers matched, "
            "read the names back and let the owner choose — do not pick one."
        ),
    }


# --------------------------------------------------------------------------- the write


def _line_fingerprint(workspace: dict[str, Any]) -> str:
    """A hash of everything a draft is built from, so a draft already made can be REUSED
    when nothing has changed and never when something has. Without this, preparing twice —
    a card that expired, a second epoch — leaves two drafts in Admin and completes one."""
    chosen = _chosen_customer(workspace) or {}
    body = {
        "customer": chosen.get("customer_id"),
        "email": ws.value(workspace, "email"),
        "lines": [(line["variant_id"], int(line["quantity"])) for line in _lines(workspace)],
        "discount": ws.value(workspace, "discount"),
        "postage": ws.value(workspace, "postage"),
        "note": ws.value(workspace, "note"),
        "address": ws.chosen(workspace, "address", "customer"),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _draft_input(workspace: dict[str, Any]) -> dict[str, Any]:
    """The DraftOrderInput, built entirely from the Mac's copy. Not one price of ours is in
    it: every line is a variant id and a quantity, and Shopify prices the draft."""
    chosen = _chosen_customer(workspace) or {}
    body: dict[str, Any] = {
        "customerId": str(chosen["customer_id"]),
        "lineItems": [{"variantId": str(line["variant_id"]), "quantity": int(line["quantity"])} for line in _lines(workspace)],
        "tags": [DRAFT_TAG],
        "useCustomerDefaultAddress": ws.chosen(workspace, "address", "customer") == "customer",
    }
    email = ws.value(workspace, "email")
    if email:
        body["email"] = email
    note = ws.value(workspace, "note")
    if note:
        body["note"] = note
    postage = _decimal(ws.value(workspace, "postage"))
    if postage is not None and postage > 0:
        body["shippingLine"] = {"title": "Postage", "price": f"{postage:.2f}"}
    discount = _decimal(ws.value(workspace, "discount"))
    if discount is not None and discount > 0:
        body["appliedDiscount"] = {"title": "Discount", "value": float(discount), "valueType": "PERCENTAGE"}
    return body


async def _observe(execution: dict) -> Observed:
    node = await _read_draft(_c(), str(execution["draft_id"]))
    order = node.get("order") or {}
    return Observed(fingerprint=draft_fingerprint(node), entity={
        "draft_id": str(node.get("id") or ""), "draft_name": str(node.get("name") or ""),
        "status": str(node.get("status") or ""),
        "order_id": str(order.get("id") or ""), "order_number": str(order.get("name") or ""),
        "total": display(_money(node.get("totalPriceSet")), _currency(node.get("totalPriceSet"))),
        "customer_name": str((node.get("customer") or {}).get("displayName") or ""),
    })


async def _execute(execution: dict) -> dict:
    """The completion, and only the completion. The draft was made and priced at PREPARE
    time; this turns it into an order. `paymentPending` is what the owner chose on the
    workspace, decided on the Mac, and nothing new is decided here."""
    payload = await _c().mutate("draft_order_complete", {
        "id": str(execution["draft_id"]),
        "paymentPending": bool(execution["payment_pending"]),
    })
    body = ((payload.get("data") or {}).get("draftOrderComplete") or {}).get("draftOrder") or {}
    order = body.get("order") or {}
    if not order.get("id"):
        raise ShopifyError("Shopify did not confirm which order it created.")
    return {"order_id": str(order["id"])}


def _verify(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    """Proof, by re-reading the draft: it is completed, and it now has an order on it.

    "Completed" alone would not do — a draft invoiced in Admin also leaves OPEN — so the
    order's own id is what is checked, and the total is compared to what was on the card
    because a total that moved means the money the owner agreed to is not the money taken.
    """
    if not str(observed.get("order") or ""):
        return False, ""
    if str(observed.get("status") or "").upper() != "COMPLETED":
        return False, ""
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
        # The precondition is the draft's state and its order, not its total: the total is on
        # the fingerprint for the proof, and a courtesy reading must not make a draft that has
        # not moved look changed.
        precondition_keys=("status", "order"),
        spoken_success="Order {label} is created, {amount}.",
        spoken_failure="I couldn't confirm the order was created. Look at the draft in Admin before asking again.",
        spoken_stale="The draft changed since this was prepared, so I haven't completed it.",
    ),
)
async def shopify_order_create(workspace_id: str) -> Prepared:
    """Prepare, never complete: re-read the customer and every variant, ask Shopify to make
    and price the DRAFT, and hand the engine a change to hold.

    The draft is the reason the card can be honest. It is a real object in Admin — priced,
    tagged, not an order, nobody charged — so the total, the postage and what the customer
    will owe are Shopify's arithmetic on the thing about to become the order. The one
    mutation the gesture authorises is `draftOrderComplete`.
    """
    _session, branch = _session_and_branch()
    workspace = ws.held(branch, KIND, str(workspace_id))
    if workspace is None:
        raise ToolError("There is no order open on this half to create.")
    blocked = _blocked(workspace)
    if blocked:
        raise ToolError(blocked)

    client = _c()
    chosen = _chosen_customer(workspace) or {}
    # The customer, re-read at the moment of preparing. A name that has become two people
    # since the workspace was opened — a duplicate made in Admin — must not be guessed at now
    # either, so the candidates are read again and a second match refuses the preparation.
    again = await _candidates(client, ws.value(workspace, "customer"))
    if len(again) > 1 and not any(c["customer_id"] == chosen.get("customer_id") for c in again):
        # The name means several people now and none of them is the one on the card. Rare,
        # and cheap insurance: the alternative is an order for whoever the workspace happened
        # to resolve when it was opened.
        workspace["facts"]["candidates"] = again
        workspace["facts"].pop("customer", None)
        raise ToolError(f"{len(again)} customers now match that name; nothing was created. Choose one.")
    try:
        await _choose_customer(workspace, str(chosen["customer_id"]))
    except ToolError:
        # Read by id and gone: merged, deleted, or a request for erasure carried out. The
        # order must not be made for an id the shop no longer has.
        workspace["facts"].pop("customer", None)
        raise ToolError(
            f"{chosen.get('name') or 'That customer'} is not in the shop any more; nothing was created."
        ) from None
    chosen = _chosen_customer(workspace) or {}

    # Every line, priced by Shopify and checked for sale. A variant withdrawn since it was
    # added is refused here rather than making an order with a line nobody can fulfil.
    for line in _lines(workspace):
        variant = await _variant(client, str(line["variant_id"]))
        product = variant.get("product") or {}
        if str(product.get("status") or "ACTIVE").upper() != "ACTIVE" or not variant.get("availableForSale"):
            raise ToolError(f"{line['title']} is not for sale any more, so it cannot go on an order.")

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
    workspace["facts"]["draft"] = {"id": str(node["id"]), "name": str(node.get("name") or ""), "fingerprint": fingerprint}

    currency = _currency(node.get("totalPriceSet"))
    total = _money(node.get("totalPriceSet"))
    subtotal = _money(node.get("subtotalPriceSet"))
    postage = _money(node.get("totalShippingPriceSet")) or 0.0
    if total is None:
        raise ShopifyError("Shopify did not price the draft; nothing was created.")
    pending = ws.chosen(workspace, "payment", "pending") != "paid"
    lines_words = ", ".join(
        f"{line['quantity']} x {line['title']}" + (f" ({line['variant']})" if line.get("variant") else "")
        for line in _lines(workspace)
    )
    discount = _decimal(ws.value(workspace, "discount"))
    read_back = (
        f"create an order for {chosen.get('name')}: {lines_words}, "
        f"{display(total, currency)}{', not paid' if pending else ', already paid'}"
    )
    return Prepared(
        execution={
            "workspace_id": str(workspace["workspace_id"]),
            "draft_id": str(node["id"]),
            "draft_name": str(node.get("name") or ""),
            "payment_pending": pending,
            "total": f"{total:.2f}",
        },
        before=draft_fingerprint(node),
        expected_after={"status": "COMPLETED", "order": "", "total": f"{total:.2f}"},
        # The workspace is what the gate held to this conversation, and the draft is what the
        # mutation names; the entity the OWNER is authorising is the order about to exist, and
        # the draft's own name is how a person finds it.
        entity_ref=str(node["id"]),
        entity_label=str(node.get("name") or "the order"),
        summary={
            "customer": str(chosen.get("name") or ""),
            "email": ws.value(workspace, "email"),
            "address": str(chosen.get("address") or ""),
            "lines": lines_words,
            "subtotal": f"{subtotal:.2f}" if subtotal is not None else "0.00",
            "postage": f"{postage:.2f}",
            # `amount` is what the spoken success line reads out (engine._spoken_amount).
            "amount": f"{total:.2f}",
            "currency": currency,
            "discount_words": f"{discount:g}% off" if discount else "",
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


def _open(ctx: CommandCtx) -> Outcome:
    """A control. Opens an EMPTY workspace and reads nothing — a command is synchronous by
    design — so the customer is looked up by the recipe when a name is typed."""
    workspace = ws.open_workspace(
        ctx.branch, kind=KIND, workspace_id=ws.new_id(WORKSPACE_PREFIX),
        values={"customer": "", "email": "", "item": "", "quantity": "1", "discount": "", "postage": "", "note": ""},
        choices={"payment": "pending", "address": "customer"},
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
    name = ctx.arg("field")
    ok, why = ws.type_into(workspace, FIELDS, name, str(ctx.args.get("value") or ""))
    if not ok:
        return Outcome.refused("unknown_field", why)
    if name == "customer":
        # The name moved: whoever the card said it was is now about the old one.
        workspace["facts"].pop("customer", None)
        workspace["facts"].pop("candidates", None)
        workspace["facts"].pop("draft", None)
        if ws.value(workspace, "customer"):
            return Outcome(answer="", changed={"recipe": "order_customer", "workspace_id": str(workspace["workspace_id"]),
                                               "field": name})
    if name in ("item", "quantity", "discount", "postage", "email", "note"):
        # Anything that changes what the draft would be makes a draft already made stale.
        workspace["facts"].pop("draft", None)
    if name == "email" and ws.value(workspace, "email"):
        ctx.session.remember_pii(ws.value(workspace, "email"))
    return Outcome(answer="", surfaces=[workspace_surface(workspace)],
                   changed={"workspace_id": str(workspace["workspace_id"]), "field": name,
                            "status": ws.status(workspace, name)})


def _choose(ctx: CommandCtx) -> Outcome:
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    ok, why = ws.choose(workspace, CHOICES, ctx.arg("field"), ctx.arg("option"))
    if not ok:
        return Outcome.refused("unknown_choice", why)
    workspace["facts"].pop("draft", None)
    return Outcome(answer="", surfaces=[workspace_surface(workspace)],
                   changed={"workspace_id": str(workspace["workspace_id"]), "chose": ctx.arg("option")})


def _pick_customer(ctx: CommandCtx) -> Outcome:
    """One of the candidates, chosen by the owner. THIS is the answer to an ambiguous name,
    and it needs a read of its own — the address as the shop holds it — so it names the
    recipe rather than guessing from the row the tablet posted."""
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    wanted = ctx.arg("customer_id")
    candidates = ws.fact(workspace, "candidates") or []
    if not any(c["customer_id"] == wanted for c in candidates):
        # Fail closed. The tablet may only choose one of the people the Mac itself found;
        # a posted id that was not among them is not a choice, it is a guess.
        return Outcome.refused("unknown_customer", "That is not one of the customers I found.")
    workspace["facts"]["chose_customer"] = wanted
    workspace["facts"].pop("draft", None)
    return Outcome(answer="", changed={"recipe": "order_customer", "workspace_id": str(workspace["workspace_id"]),
                                       "customer_id": wanted})


def _add_item(ctx: CommandCtx) -> Outcome:
    """Add the item named in the `item` field. Needs the catalogue read, so it names the
    recipe; the recipe adds the line only when exactly one variant matches."""
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    if not ws.value(workspace, "item"):
        return Outcome.refused("no_item", "Type a SKU, or the words for the item, first.")
    if len(_lines(workspace)) >= MAX_DRAFT_LINES:
        return Outcome.refused("too_many", f"An order made from here carries at most {MAX_DRAFT_LINES} lines.")
    return Outcome(answer="", changed={"recipe": "order_line", "workspace_id": str(workspace["workspace_id"]),
                                       "slots": {"product": ws.value(workspace, "item")}})


def _remove_item(ctx: CommandCtx) -> Outcome:
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
    wanted = ctx.arg("variant_id")
    lines = [line for line in _lines(workspace) if line["variant_id"] != wanted]
    if len(lines) == len(_lines(workspace)):
        return Outcome.refused("no_line", "There is no line for that on this order.")
    workspace["facts"]["lines"] = lines
    workspace["facts"].pop("draft", None)
    return Outcome(answer="", surfaces=[workspace_surface(workspace)],
                   changed={"workspace_id": str(workspace["workspace_id"]), "removed": wanted})


def _stage(ctx: CommandCtx) -> Outcome:
    """Prepare the order, tapped. Prepares the change; creates no order."""
    workspace = ws.held(ctx.branch, KIND, ctx.arg("workspace_id"))
    if workspace is None:
        return _no_workspace()
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
    ws.discard(ctx.branch)
    tail = f" Draft {draft['name']} is still in Admin; delete it there if you do not want it." if draft.get("name") else ""
    return Outcome(answer=f"Gone. No order was created.{tail}",
                   changed={"workspace": None, "discarded": str(workspace["workspace_id"]),
                            "draft": draft.get("name") or None})


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
    body = result.values.get("customer")
    if not isinstance(body, dict):
        return RecipeAnswer(answer="", defer="the shop did not answer about that customer")
    found = [c for c in (body.get("customers") or []) if isinstance(c, dict) and c.get("customer_id")]
    workspace["facts"]["candidates"] = [
        {"customer_id": str(c["customer_id"]), "name": str(c.get("name") or ""),
         "email": str(c.get("email") or ""), "orders": str(c.get("orders") or "0")}
        for c in found[:MAX_CANDIDATES]
    ]
    wanted = str(ws.fact(workspace, "chose_customer") or "")
    workspace["facts"].pop("chose_customer", None)
    workspace["facts"].pop("customer", None)
    one = next((c for c in workspace["facts"]["candidates"] if c["customer_id"] == wanted), None)
    if one is None and len(workspace["facts"]["candidates"]) == 1:
        one = workspace["facts"]["candidates"][0]
    if one is not None:
        choose_row(workspace, one)
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
    candidates go on the card as words and nothing is added.
    """
    workspace = ws.held(ctx.branch, KIND)
    if workspace is None:
        return RecipeAnswer(answer="", defer="the order was closed while the catalogue was being read")
    body = result.values.get("variants")
    if not isinstance(body, dict):
        return RecipeAnswer(answer="", defer="the catalogue did not answer")
    candidates = [c for c in (body.get("candidates") or []) if isinstance(c, dict) and c.get("for_sale")]
    workspace["facts"].pop("item_note", None)
    if not candidates:
        workspace["facts"]["item_note"] = f"nothing for sale matches {ws.value(workspace, 'item')!r}"
    elif len(candidates) > 1:
        workspace["facts"]["item_note"] = (
            f"{len(candidates)} match {ws.value(workspace, 'item')!r}: "
            + "; ".join(f"{c.get('title')} {c.get('variant') or ''}".strip() for c in candidates[:4])
            + ". Be more specific."
        )
    else:
        one = candidates[0]
        quantity = int(ws.value(workspace, "quantity", "1") or 1)
        lines = _lines(workspace)
        for line in lines:
            if line["variant_id"] == str(one["variant_id"]):
                # One more of something already on it, not a second line saying the same.
                line["quantity"] = min(MAX_DRAFT_QUANTITY, int(line["quantity"]) + quantity)
                break
        else:
            lines.append({
                "variant_id": str(one["variant_id"]),
                "title": str(one.get("title") or ""),
                "variant": str(one.get("variant") or ""),
                "sku": str(one.get("sku") or ""),
                "price": f"{float(one.get('price') or 0):.2f}",
                "quantity": quantity,
            })
        workspace["facts"]["lines"] = lines
        workspace["facts"].pop("draft", None)
        ws.type_into(workspace, FIELDS, "item", "")
        ws.type_into(workspace, FIELDS, "quantity", "1")
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
    what="Build an order for a customer — items, quantities, postage, a discount, paid or not — priced by Shopify as a draft before you authorise it",
    operations=(OPERATION,),
    tools=(OPEN_TOOL, WRITE_TOOL),
    scopes=(SCOPE,),
    state="READY",
    probe=_probe,
))

__all__ = [
    "CHOICES", "DRAFT_TAG", "FIELDS", "FIELD_NAMES", "KIND", "OPEN_TOOL", "OPERATION",
    "SCOPE", "WRITE_TOOL", "display", "draft_fingerprint", "workspace_surface",
]
