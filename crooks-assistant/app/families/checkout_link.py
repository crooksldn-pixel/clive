"""A checkout link sent to a customer: the draft Shopify prices, the email he reads, his hold.

George, 2 October: "Clive still cannot send a checkout link for a customer."

    "Send Alicia a checkout link for the black tee, size M"
        shopify_checkout_link_send     PREPARE: the customer read again, the item found in the
                                       catalogue (one variant, for sale, or a question), a DRAFT
                                       order made and read back with the link Shopify holds for it
        the card                       the email exactly as it will go: to, items, Shopify's price,
                                       the link, his words — and "hold to send"
        his hold                       the email is sent from the shop's own Gmail
        the proof                      the sent message read back from Gmail by its own id

Which way it is sent, and why. Shopify can email a draft's invoice itself (`draftOrderInvoiceSend`),
but that mutation is not one of the reviewed documents this project may send
(app/clients/shopify.py REVIEWED_MUTATIONS), and adding one is the Director's change with the
owner's approval. CLIVE's own approved path for a new email to a customer already exists — the
Gmail send behind the owner's hold, proven by reading the sent message back
(app/tools/gmail_writes.py) — so that is the path: one more email through the one engine, with
the link the shop made in it.

What is decided where. The price is Shopify's: the card prints the draft's own lines and totals as
Shopify priced them, never a figure of ours or the model's. The link is Shopify's: the draft's
`invoiceUrl`, read back after the draft is made, handed on exactly as it is, and refused unless it
is on the shop's own domain. The recipient is Shopify's: the customer's own address, read by id.
The model gives the customer, the items and a line or two of words; nothing else it says reaches
the email.

The draft is made at PREPARE, as an order being built makes its draft
(app/families/order_create.py): a draft is not an order, nobody is charged, and it is the only
thing that can print a true price and a real link on the card before the hold. It is tagged
"CROOKS assistant" and "checkout link" in Admin; preparing the same link again reuses it rather
than making another. Nothing is sent, and nobody is told anything, until the hold.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from typing import Any
from urllib.parse import urlparse

from app.actions.models import Observed, Prepared
from app.capabilities.families import CapabilityFamily
from app.capabilities.families import register as register_family
from app.clients.shopify import ShopifyError
from app.tools import gmail_writes
from app.tools.context import current_session
from app.tools.gate import Tier
from app.tools.registry import ToolError, WriteSpec, tool
from app.tools.shopify_tools import _c, catalogue_candidates
from app.tools.shopify_writes import VARIANT_FOR_EDIT_QUERY

log = logging.getLogger("crooks.families.checkout_link")

TOOL = "shopify_checkout_link_send"
OPERATION = "checkout_link_send"
MAX_ITEMS = 5
MAX_QUANTITY = 10
MAX_MESSAGE_CHARS = 400
TAGS = ["CROOKS assistant", "checkout link"]
SUBJECT = "Your CROOKS checkout link"
# How long a draft this process made for a link is reused for the same customer and items.
REUSE_S = 6 * 3600
MAX_REMEMBERED = 50

CUSTOMER_QUERY = """
query CrooksCheckoutCustomer($id: ID!) {
  customer(id: $id) { id displayName firstName defaultEmailAddress { emailAddress } }
}
"""

DRAFT_QUERY = """
query CrooksCheckoutDraft($id: ID!) {
  draftOrder(id: $id) {
    id
    name
    status
    invoiceUrl
    email
    customer { id displayName }
    order { id name }
    totalPriceSet { shopMoney { amount currencyCode } }
    subtotalPriceSet { shopMoney { amount currencyCode } }
    totalShippingPriceSet { shopMoney { amount currencyCode } }
    totalTaxSet { shopMoney { amount currencyCode } }
    lineItems(first: 10) {
      edges { node { title variantTitle quantity variant { id } discountedTotalSet { shopMoney { amount currencyCode } } } }
    }
  }
}
"""

# (customer id, lines) -> (draft id, when made). This process's own memory: a restart forgets
# it, and then one more draft is made, tagged like the first.
_made: dict[tuple[str, tuple[tuple[str, int], ...]], tuple[str, float]] = {}

register_family(CapabilityFamily(
    key="checkout_link", label="Sending a checkout link", area="customers",
    what="send a customer a link to pay for items, priced by Shopify, from the shop's Gmail",
    operations=(OPERATION,), scopes=("gmail.compose",), state="READY",
))


# --------------------------------------------------------------------------- the reads


async def _customer(customer_id: str) -> dict[str, str]:
    payload = await _c().graphql(CUSTOMER_QUERY, {"id": customer_id})
    node = (payload.get("data") or {}).get("customer")
    if not isinstance(node, dict) or node.get("id") != customer_id:
        raise ToolError(f"No customer with id {customer_id}.")
    email = str((node.get("defaultEmailAddress") or {}).get("emailAddress") or "").strip().lower()
    name = str(node.get("displayName") or "")
    if not email or not gmail_writes.EMAIL_ADDRESS.match(email):
        raise ToolError(f"{name or 'That customer'} has no email address in Shopify to send a link to.")
    return {"id": customer_id, "name": name, "first": str(node.get("firstName") or name.split(" ")[0]), "email": email}


async def _variant(variant_id: str) -> dict[str, Any]:
    payload = await _c().graphql(VARIANT_FOR_EDIT_QUERY, {"id": variant_id})
    node = (payload.get("data") or {}).get("productVariant")
    if not isinstance(node, dict) or node.get("id") != variant_id:
        raise ToolError(f"No variant with id {variant_id}.")
    product = node.get("product") or {}
    title = str(product.get("title") or "")
    if str(product.get("status") or "ACTIVE").upper() != "ACTIVE" or not node.get("availableForSale"):
        raise ToolError(f"{title} {node.get('title') or ''} is not for sale, so there is nothing to send a link for.".replace("  ", " "))
    return {"variant_id": variant_id, "title": title, "variant": str(node.get("title") or "")}


async def _resolve(item: Any) -> dict[str, Any]:
    """One item asked for: exactly one variant, for sale — or a question, never a guess."""
    if not isinstance(item, dict):
        raise ToolError("Each item needs words (and a size), or a variant_id.")
    try:
        quantity = int(item.get("quantity") or 1)
    except (TypeError, ValueError):
        raise ToolError("A quantity is a whole number.") from None
    if not 1 <= quantity <= MAX_QUANTITY:
        raise ToolError(f"A quantity is 1 to {MAX_QUANTITY}.")
    variant_id = str(item.get("variant_id") or "").strip()
    if variant_id:
        session = current_session()
        if session is None or variant_id not in getattr(session, "issued_ids", set()):
            raise ToolError(f"variant_id {variant_id!r} is not one this conversation has looked up; find it with shopify_variant_search.")
        return {**await _variant(variant_id), "quantity": quantity}
    words = [" ".join(str(item.get(k) or "").split())[:60] for k in ("item", "colour", "size")]
    if not words[0]:
        raise ToolError("Say which item: its words and size, or a variant_id.")
    found, _wanted = await catalogue_candidates(_c(), *words)
    for_sale = [c for c in found if c.get("for_sale")]
    if not for_sale:
        said = " ".join(w for w in words if w)
        raise ToolError(f"Nothing for sale in the catalogue matches {said!r}." if not found else
                        f"{found[0]['title']} {found[0]['variant']} is not for sale.")
    if len(for_sale) > 1:
        options = "; ".join(f"{c['title']} {c['variant']}" for c in for_sale[:6])
        raise ToolError(f"{len(for_sale)} match {words[0]!r}: {options}. Ask which, then prepare it again with the colour and size.")
    one = for_sale[0]
    return {"variant_id": one["variant_id"], "title": one["title"], "variant": one["variant"], "quantity": quantity}


async def _read_draft(draft_id: str) -> dict[str, Any]:
    payload = await _c().graphql(DRAFT_QUERY, {"id": draft_id})
    node = (payload.get("data") or {}).get("draftOrder")
    if not isinstance(node, dict) or node.get("id") != draft_id:
        raise ToolError("Shopify did not give the draft back, so there is no link to send.")
    return node


def _lines_of(node: dict[str, Any]) -> list[tuple[str, int]]:
    out = []
    for edge in ((node.get("lineItems") or {}).get("edges") or []):
        line = (edge or {}).get("node") or {}
        out.append((str((line.get("variant") or {}).get("id") or ""), int(line.get("quantity") or 0)))
    return sorted(out)


def draft_fingerprint(node: dict[str, Any]) -> str:
    """What the hold sends a link to: its state, its lines, its price and the link itself."""
    total = ((node.get("totalPriceSet") or {}).get("shopMoney") or {}).get("amount")
    canonical = "|".join([str(node.get("status") or ""), str((node.get("order") or {}).get("id") or ""), str(total or ""),
                          str(node.get("invoiceUrl") or ""), ",".join(f"{v}x{q}" for v, q in _lines_of(node))])
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _link_ok(url: str) -> bool:
    """The shop's own link: https, on the shop's myshopify domain or a domain the store links to."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    settings = gmail_writes._settings()
    allowed = {h.strip().lower() for h in str(getattr(settings, "gmail_link_hosts", "") or "").split(",") if h.strip()}
    allowed |= {str(getattr(settings, "shopify_shop_domain", "") or "").lower(), str(getattr(_c(), "shop_domain", "") or "").lower()}
    return any(host == a or host.endswith("." + a) for a in allowed if a)


async def _the_draft(customer: dict[str, str], lines: list[dict[str, Any]]) -> dict[str, Any]:
    """A draft for exactly these lines for this customer: the one this process made a moment ago
    if it is still open and unchanged, otherwise a new one. Read back either way."""
    key = (customer["id"], tuple(sorted((line["variant_id"], line["quantity"]) for line in lines)))
    held = _made.get(key)
    if held and time.time() - held[1] < REUSE_S:
        try:
            node = await _read_draft(held[0])
            if str(node.get("status") or "").upper() == "OPEN" and not (node.get("order") or {}).get("id") and _lines_of(node) == sorted(key[1]):
                return node
        except (ToolError, ShopifyError) as exc:
            log.info("the draft made for this link could not be re-read: %s", type(exc).__name__)
    draft_input = {"customerId": customer["id"], "email": customer["email"], "tags": list(TAGS),
                   "lineItems": [{"variantId": line["variant_id"], "quantity": line["quantity"]} for line in lines]}
    payload = await _c().mutate("draft_order_create", {"input": draft_input})
    made = ((payload.get("data") or {}).get("draftOrderCreate") or {}).get("draftOrder") or {}
    if not made.get("id"):
        raise ShopifyError("Shopify did not make the draft, so there is no price and no link.")
    _made[key] = (str(made["id"]), time.time())
    while len(_made) > MAX_REMEMBERED:
        _made.pop(next(iter(_made)))
    return await _read_draft(str(made["id"]))


# --------------------------------------------------------------------------- the email


def _money(node: Any) -> tuple[float | None, str]:
    shop = (node or {}).get("shopMoney") or {} if isinstance(node, dict) else {}
    try:
        return round(float(shop.get("amount")), 2), str(shop.get("currencyCode") or "GBP")
    except (TypeError, ValueError):
        return None, str(shop.get("currencyCode") or "GBP")


def _shown(amount: float | None, currency: str) -> str:
    if amount is None:
        return ""
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency.upper())
    return f"{symbol}{amount:,.2f}" if symbol else f"{amount:,.2f} {currency}"


def _clean_message(message: Any) -> str:
    """His words, as the model wrote them: plain, short, and with no link — the link is the
    shop's, and CLIVE puts it in."""
    text = "\n".join(line.rstrip() for line in str(message or "").replace("\r\n", "\n").strip().splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text)
    if not text:
        raise ToolError("Write a line or two for the email; the items, the price and the link are added.")
    if "<" in text or any(ord(ch) < 32 and ch not in "\n\t" for ch in text):
        raise ToolError("The message must be plain text.")
    if re.search(r"https?://|www\.", text, re.I):
        raise ToolError("Leave the link out of the message; CLIVE adds the shop's own link.")
    if len(text) > MAX_MESSAGE_CHARS:
        raise ToolError(f"The message is longer than {MAX_MESSAGE_CHARS} characters; shorten it.")
    return text


def _priced_lines(node: dict[str, Any]) -> list[dict[str, str]]:
    out = []
    for edge in ((node.get("lineItems") or {}).get("edges") or []):
        line = (edge or {}).get("node") or {}
        amount, currency = _money(line.get("discountedTotalSet"))
        out.append({"title": str(line.get("title") or ""), "variant": str(line.get("variantTitle") or ""),
                    "quantity": str(line.get("quantity") or 1), "price": _shown(amount, currency)})
    return out


def _body(message: str, lines: list[dict[str, str]], total: str, link: str) -> str:
    listed = "\n".join(f"{line['title']}{' — ' + line['variant'] if line['variant'] else ''}"
                       f"{' × ' + line['quantity'] if line['quantity'] != '1' else ''}: {line['price']}" for line in lines)
    signature = str(getattr(gmail_writes._settings(), "gmail_signature", "") or "").strip()
    parts = [message, listed, f"Total: {total}", f"Pay here: {link}"] + ([signature] if signature else [])
    return "\n\n".join(p for p in parts if p)


# --------------------------------------------------------------------------- the change


async def _observe(execution: dict) -> Observed:
    state = await gmail_writes._token_state(str(execution["token"]), str(execution.get("sent_message_id") or ""))
    try:
        state["draft"] = draft_fingerprint(await _read_draft(str(execution["checkout_draft_id"])))
    except (ToolError, ShopifyError):
        state["draft"] = ""
    return Observed(fingerprint=state, entity=None)


def _verify(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    return bool(observed.get("sent")), ""


def _present(proposal) -> dict:
    s = proposal.summary
    facts = [
        {"label": "To", "value": str(s.get("to_line") or "")},
        {"label": "Items", "value": str(s.get("items_line") or "")},
        {"label": "Total", "value": str(s.get("total") or ""), "tone": "bad"},
        {"label": "Postage", "value": str(s.get("postage") or "")},
        {"label": "Link", "value": str(s.get("link") or "")},
        {"label": "Draft", "value": str(s.get("draft_line") or "")},
        {"label": "From", "value": str(s.get("from_line") or "")},
    ]
    return {
        "title": "Send a checkout link", "summary": "", "body": str(s.get("body") or ""), "facts": facts,
        "detail": "Sends the email now. It cannot be unsent; the draft stays in Shopify until it is paid or deleted.",
        "done_title": "Checkout link sent",
    }


@tool(
    name=TOOL,
    description=(
        "Prepare an email to a customer with a link to pay for items, priced by Shopify as a draft "
        "order; the owner's hold sends it. Items by words and size, or a variant_id. `message`: "
        "your own line or two; items, price and link are added."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "customer_id": {"type": "string"},
            "items": {
                "type": "array", "minItems": 1, "maxItems": MAX_ITEMS,
                "items": {"type": "object", "properties": {
                    "item": {"type": "string"}, "size": {"type": "string"}, "variant_id": {"type": "string"},
                    "quantity": {"type": "integer", "minimum": 1, "maximum": MAX_QUANTITY}}},
            },
            "message": {"type": "string", "maxLength": MAX_MESSAGE_CHARS},
        },
        "required": ["customer_id", "items", "message"],
    },
    tier=Tier.RED,
    issued_id_args=("customer_id",),
    write=WriteSpec(
        operation=OPERATION, entity_kind="customer", entity_arg="customer_id", mutation="gmail:send",
        observe=_observe, execute=gmail_writes._execute_send, present=_present, entity=gmail_writes._entity_email,
        verify=_verify, settle=gmail_writes._settle_send, reversible=False, op_class="irreversible",
        # The email not already gone, and the draft it links to still the one on the card.
        precondition_keys=("sent", "draft"),
        spoken_success="Checkout link sent to {to}.",
        spoken_failure="I couldn't confirm the email went. Check Sent in Gmail before sending again.",
        spoken_stale="The draft or the email changed since this was prepared. Nothing was sent.",
    ),
)
async def shopify_checkout_link_send(customer_id: str, items: list, message: str) -> Prepared:
    """Prepare, never send: the customer, the items, Shopify's draft and link, the exact email."""
    text = _clean_message(message)
    if not isinstance(items, list) or not 1 <= len(items) <= MAX_ITEMS:
        raise ToolError(f"Give one to {MAX_ITEMS} items.")
    customer = await _customer(str(customer_id))
    lines = [await _resolve(item) for item in items]
    node = await _the_draft(customer, lines)
    link = str(node.get("invoiceUrl") or "").strip()
    if str((node.get("customer") or {}).get("id") or "") != customer["id"]:
        raise ToolError(f"Shopify's draft {node.get('name') or ''} is not for {customer['name']}, so no link is offered.")
    if _lines_of(node) != sorted((line["variant_id"], line["quantity"]) for line in lines):
        raise ToolError(f"Shopify's draft {node.get('name') or ''} does not carry exactly those items, so no link is offered.")
    if str(node.get("status") or "").upper() != "OPEN" or (node.get("order") or {}).get("id"):
        raise ToolError(f"Draft {node.get('name') or ''} is not open any more, so its link cannot be sent.")
    if not link:
        raise ToolError(f"Shopify holds no payment link for draft {node.get('name') or ''}, so there is nothing to send.")
    if not _link_ok(link):
        raise ToolError(f"The link Shopify gave is not on the shop's own domain ({urlparse(link).hostname}), so it is not sent.")
    total_amount, currency = _money(node.get("totalPriceSet"))
    if total_amount is None:
        raise ToolError("Shopify did not price the draft, so no link is offered.")
    total = _shown(total_amount, currency)
    postage_amount, _ = _money(node.get("totalShippingPriceSet"))
    priced = _priced_lines(node)
    body = _body(text, priced, total, link)
    if len(body) > gmail_writes.MAX_BODY_CHARS:
        raise ToolError("The email would be too long; shorten the message.")
    client = gmail_writes._g()
    sender = await asyncio.to_thread(client.address)
    token = gmail_writes.new_token(sender)
    subject = gmail_writes.clean_subject(SUBJECT)
    raw = gmail_writes.build_raw(sender=sender, sender_name=str(getattr(gmail_writes._settings(), "gmail_from_name", "") or ""),
                                 to=customer["email"], to_name=customer["name"], subject=subject, body=body, token=token)
    before = await gmail_writes._token_state(token)
    before["draft"] = draft_fingerprint(node)
    items_line = "; ".join(f"{line['title']}{' ' + line['variant'] if line['variant'] else ''}"
                           f"{' ×' + line['quantity'] if line['quantity'] != '1' else ''} · {line['price']}" for line in priced)
    draft_name = str(node.get("name") or "")
    # `draft_id` is a GMAIL draft to the shared send path (empty: this is a fresh message); the
    # Shopify draft the link belongs to is `checkout_draft_id`, which `_observe` re-reads.
    execution = {"thread_id": "", "token": token, "raw": raw, "draft_id": "", "to": customer["email"], "to_name": customer["name"],
                 "subject": subject, "body": body, "state": "sent", "checkout_draft_id": str(node["id"])}
    return Prepared(
        execution=execution,
        before=before,
        expected_after={"sent": 1},
        entity_ref=customer["id"],
        entity_label=customer["name"] or "customer",
        summary={
            "title": "Send a checkout link", "sending": True, "spoken_to": customer["first"] or customer["name"],
            "to_line": f"{customer['name']} <{customer['email']}>" if customer["name"] else customer["email"],
            "subject": subject, "body": body, "items_line": items_line, "total": total,
            "postage": _shown(postage_amount, currency) if postage_amount else "none on the draft",
            "link": link, "draft_line": f"{draft_name} in Shopify — a draft, not an order; nobody is charged until they pay",
            "from_line": sender, "read_back": f"send {customer['first'] or customer['name']} a checkout link for {items_line}, {total} in all",
            "pii": [v for v in (customer["email"], customer["name"]) if v],
            "ledger": {"kind": "checkout_link", "lines": len(priced), "chars": len(body), "to_checked": True},
        },
    )
