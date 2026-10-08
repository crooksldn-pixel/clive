"""The email the assistant can prepare: a reply drafted or sent in a customer's thread, a
new email drafted or sent to an order's (or a customer's) address, a thread archived. Every
one is a staged change on the action engine — the card on the tablet IS the email, printed
whole, and a gesture on it is what sends. Nothing here reaches Gmail's write methods except
through the engine's commit. (DEC-071's inbox rulings use these parts: junk, and a draft
waiting in Gmail sent as it is, are app/tools/gmail_inbox.py; CLIVE taking away its own unsent
drafts is app/tools/gmail_drafts.py — inside a held send here, or on its own clock there, and
only ever a draft CLIVE's own record says it made.)

The recipient is never the model's to choose: a reply goes to the person the message it
answers came from (its Reply-To when it names one, otherwise its From), read from the
thread on the Mac; a new email goes to the customer on the order or the customer record,
read from Shopify. When an order is named on a reply, the recipient must be that order's
customer or nothing is staged; a thread with more than one person in it needs the order
named. "Send the draft" sends the one draft in the thread exactly as Gmail holds it — its
recipient, subject and text are read from the draft and printed, and an edit made in Gmail
after the card was staged makes the card stale. A message is found again by its
Message-ID (minted here, or Gmail's own) and by the id Gmail hands back, so whether it was
drafted or sent is a fact read back from the thread, and a send happens at most once.

Email text is untrusted: what a customer wrote is evidence the owner can read on the card,
never an instruction. The body of anything sent is the assistant's own words, plain text,
bounded, with links only to hosts the store allows.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import re
import time
import unicodedata
import uuid
from email.message import EmailMessage
from email.utils import formataddr, parseaddr, parsedate_to_datetime
from typing import Any

from app.actions.models import Observed, Prepared
from app.clients.gmail import GmailClient, GmailError
from app.tools.gate import Tier
from app.tools.gmail_tools import _extract_body, authenticated
from app.tools.registry import ToolError, WriteSpec, tool

log = logging.getLogger("crooks.tools.gmail_writes")

MAX_BODY_CHARS = 2000
MAX_SUBJECT_CHARS = 120
SETTLE_S = 6.0
SETTLE_POLL_S = 0.5
_URL = re.compile(r"https?://([^\s/]+)", re.I)
_MESSAGE_ID = re.compile(r"^<[^\s<>@]+@[^\s<>@]+>$")

# An address the owner dictated rather than one Shopify supplied (app/families/compose.py).
# Strict on purpose: one address, no display name, no comma, no space, a real dotted domain
# and a letters-only TLD. It is the last check before an address becomes a To header, and a
# lenient one here would let "4417lighthousepony at example" through as a recipient.
MAX_ADDRESS_CHARS = 254
EMAIL_ADDRESS = re.compile(
    r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
    r"@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$",
    re.I,
)

_client: GmailClient | None = None
_customer = None      # async (order_id, customer_id) -> {"name", "email", "label"}: read from Shopify
_policy = None        # () -> settings


def bind(client: GmailClient | None, *, customer=None, policy=None) -> None:
    global _client, _customer, _policy
    _client = client
    _customer = customer
    _policy = policy
    # [inbox, ruling 28] CLIVE's record of its own drafts reads and tidies through the same client.
    from app.tools import gmail_drafts

    gmail_drafts.bind(client)


def _g() -> GmailClient:
    if _client is None:
        raise ToolError("Gmail is not configured on this backend.")
    return _client


def _settings():
    return _policy() if _policy is not None else None


async def _order_customer(order_id: str = "", customer_id: str = "") -> dict[str, str]:
    """Who a new email goes to, read from Shopify now: the customer on the order (the
    address the order was placed with), or the customer record when there is no visible
    order. The only recipient a new email may have."""
    if _customer is not None:
        return await _customer(order_id, customer_id)
    from app.tools.shopify_tools import _c, hydrator

    if order_id:
        order = await hydrator().order(str(order_id), budget_s=0.0)
        return {
            "name": str(order.get("customer_name") or ""), "email": str(order.get("customer_email") or "").strip().lower(),
            "label": str(order.get("order_number") or ""),
        }
    payload = await _c().graphql(
        "query CrooksCustomerAddress($id: ID!) { customer(id: $id) { id displayName defaultEmailAddress { emailAddress } } }",
        {"id": str(customer_id)},
    )
    node = (payload.get("data") or {}).get("customer")
    if not isinstance(node, dict) or node.get("id") != str(customer_id):
        raise ToolError(f"No customer with id {customer_id}.")
    return {
        "name": str(node.get("displayName") or ""), "email": str((node.get("defaultEmailAddress") or {}).get("emailAddress") or "").strip().lower(),
        "label": "",
    }


# ------------------------------------------------------------------- the message


def clean_body(body: object) -> str:
    """The assistant's words as they will be sent: plain text, bounded, links only to hosts
    the store allows, the store's sign-off on the end."""
    settings = _settings()
    text = str(body or "").replace("\r\n", "\n").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    if not text:
        raise ToolError("The email has no text.")
    if "<" in text or any(ord(ch) < 32 and ch not in "\n\t" for ch in text):
        raise ToolError("The email must be plain text.")
    if len(text) > MAX_BODY_CHARS:
        raise ToolError(f"The email is longer than {MAX_BODY_CHARS} characters; shorten it.")
    allowed = [h.strip().lower() for h in str(getattr(settings, "gmail_link_hosts", "") or "").split(",") if h.strip()]
    for host in _URL.findall(text):
        host = host.lower().split(":")[0]
        if not any(host == a or host.endswith("." + a) for a in allowed):
            raise ToolError(f"The email links to {host}, which is not a site the store links to. Leave the link out.")
    signature = str(getattr(settings, "gmail_signature", "") or "").strip()
    if signature and not text.rstrip().endswith(signature):
        text = f"{text}\n\n{signature}"
    return text


def clean_subject(subject: object) -> str:
    text = " ".join(str(subject or "").split())
    if not text:
        raise ToolError("The email needs a subject.")
    if len(text) > MAX_SUBJECT_CHARS or "<" in text:
        raise ToolError("The subject must be one plain line.")
    return text


def reply_subject(subject: str) -> str:
    text = " ".join(str(subject or "").split())
    return text if re.match(r"^re\s*:", text, re.I) else f"Re: {text}" if text else "Re: your order"


def new_token(address: str) -> str:
    """A Message-ID minted here: how the message is found again in the thread, whatever
    happened to the answer that was meant to say it had gone."""
    domain = address.split("@", 1)[1] if "@" in address else "crooks.local"
    return f"<crooks-{uuid.uuid4().hex}@{domain}>"


def build_raw(*, sender: str, sender_name: str, to: str, to_name: str, subject: str, body: str, token: str, in_reply_to: str = "", references: str = "") -> str:
    """The exact bytes Gmail will be handed, base64url as its API wants them."""
    message = EmailMessage()
    message["From"] = formataddr((sender_name, sender)) if sender_name else sender
    message["To"] = formataddr((to_name, to)) if to_name else to
    message["Subject"] = subject
    message["Message-ID"] = token
    if in_reply_to:
        message["In-Reply-To"] = in_reply_to
        message["References"] = " ".join(x for x in (references, in_reply_to) if x).strip()
    message.set_content(body)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def _when(date_header: str) -> str:
    try:
        return parsedate_to_datetime(date_header).strftime("%-d %b %H:%M")
    except (TypeError, ValueError, IndexError):
        return str(date_header or "")[:16]


def _first_name(name: str, email: str) -> str:
    return (name.split() or [email.split("@", 1)[0] or "them"])[0]


def _sha(text: str) -> str:
    return hashlib.sha256(str(text or "").replace("\r\n", "\n").strip().encode("utf-8")).hexdigest()[:16]


# ----------------------------------------------------------------------- the thread


async def thread_context(thread_id: str) -> dict[str, Any]:
    """The thread as it is: who to answer and where (Reply-To first, then From), who else
    has written into it, what was sent from here already, and the drafts waiting in it."""
    client = _g()
    messages = await asyncio.to_thread(client.thread_messages, thread_id)
    if not messages:
        raise ToolError("That thread is empty or could not be read.")
    me = (await asyncio.to_thread(client.address)) or ""

    def sender(m: dict) -> str:
        return parseaddr(m["headers"].get("from", ""))[1].strip().lower()

    inbound = [m for m in messages if "DRAFT" not in m["labels"] and "SENT" not in m["labels"] and sender(m) != me]
    real = [m for m in messages if "DRAFT" not in m["labels"]]
    sent_ids = {m["id"] for m in messages if "SENT" in m["labels"]}
    tokens_sent = {m["headers"].get("message-id", "").strip() for m in messages if "SENT" in m["labels"] and m["headers"].get("message-id", "").strip()}
    drafts = []
    for m in messages:
        # A draft of ours in this thread. Its Message-ID is kept when it is well formed —
        # that is how a draft is matched to the proposal that made it — but a draft whose
        # header Gmail rewrote is still a draft, and is listed with an empty token so the
        # proof can match it by the id Gmail handed back instead. A send never guesses
        # between drafts: `_the_one_draft` still refuses when there is more than one.
        if "DRAFT" in m["labels"] and sender(m) == me:
            header = m["headers"].get("message-id", "").strip()
            to_name, to_email = parseaddr(m["headers"].get("to", ""))
            drafts.append({"message_id": m["id"], "token": header if _MESSAGE_ID.match(header) else "", "to": to_email.strip().lower(), "to_name": to_name.strip(), "subject": m["headers"].get("subject", "")})
    last_in = inbound[-1] if inbound else None
    head = (last_in or (real[-1] if real else messages[-1]))["headers"]
    from_name, from_email = parseaddr(head.get("from", ""))
    reply_name, reply_email = parseaddr(head.get("reply-to", ""))
    reply_email = reply_email.strip().lower()
    to_email = reply_email if reply_email and "@" in reply_email else from_email.strip().lower()
    to_name = (reply_name or from_name).strip() if to_email == reply_email else from_name.strip()
    return {
        "thread_id": thread_id, "subject": head.get("subject", ""), "last": (real[-1]["id"] if real else ""),
        "to_name": to_name, "to_email": to_email, "from_email": from_email.strip().lower(), "reply_to": reply_email,
        "senders": sorted({sender(m) for m in inbound if sender(m)}), "date": head.get("date", ""),
        "in_reply_to": head.get("message-id", "").strip(), "references": head.get("references", "").strip(),
        "authenticated": authenticated(head, from_email),
        "has_inbound": last_in is not None, "tokens_sent": tokens_sent, "sent_ids": sent_ids, "drafts": drafts,
    }


def _thread_fingerprint(ctx: dict[str, Any], token: str, sent_message_id: str = "", drafted_message_id: str = "") -> dict[str, Any]:
    """The thread reduced to what a proof needs: what its last real message is, whether OUR
    draft is in it, and whether OUR message has gone.

    A draft is ours by the Message-ID we generated, or — once Gmail has answered the create
    with an id of its own — by that id. Gmail may rewrite a Message-ID header on the way in;
    a draft it told us it made, sitting in the thread it told us it is in, is stronger proof
    than the header, not weaker. Before the change there is no such id, so the precondition
    counts nothing: this can only ever prove a draft that this commit actually created.
    """
    sent = token in ctx["tokens_sent"] or (bool(sent_message_id) and sent_message_id in ctx["sent_ids"])
    ours = [d for d in ctx["drafts"] if (d["token"] and d["token"] == token) or (drafted_message_id and d.get("message_id") == drafted_message_id)]
    return {"last": ctx["last"], "drafts": len(ours), "sent": 1 if sent else 0}


async def _draft_text(draft_id: str) -> tuple[str, dict[str, str]]:
    """A draft's body and headers, as Gmail holds them now."""
    draft = await asyncio.to_thread(_g().get_draft, draft_id)
    payload = (draft.get("message") or {}).get("payload") or {}
    headers: dict[str, str] = {}
    for h in payload.get("headers") or []:
        headers.setdefault(str(h.get("name", "")).lower(), str(h.get("value", "")))
    return _extract_body(payload, limit=MAX_BODY_CHARS * 2), headers


async def _observe_thread(execution: dict) -> Observed:
    ctx = await thread_context(str(execution["thread_id"]))
    fingerprint = _thread_fingerprint(ctx, str(execution["token"]), str(execution.get("sent_message_id") or ""), str(execution.get("drafted_message_id") or ""))
    if execution.get("draft_id"):
        # The card printed the draft's text; the draft must still be that text when it goes.
        try:
            body, _ = await _draft_text(str(execution["draft_id"]))
            fingerprint["draft_sha"] = _sha(body)
        except (ToolError, GmailError):
            fingerprint["draft_sha"] = ""
    return Observed(fingerprint=fingerprint, entity=None)


async def _token_state(token: str, sent_message_id: str = "", drafted_draft_id: str = "") -> dict[str, int]:
    """For a message outside any thread: how many drafts and how many sent messages carry
    this token, by Gmail's own search on the Message-ID — and, once Gmail has answered a
    send (or a draft) with an id, that record's own existence.

    The id fallback exists because Gmail may rewrite the Message-ID header it was given. A
    draft Gmail says it created, which Gmail still holds when asked for it by that id, is
    proof; the fallback is only ever consulted for an id THIS commit was handed back."""
    client = _g()
    drafts, sent = await asyncio.gather(
        asyncio.to_thread(client.list_drafts, f"rfc822msgid:{token.strip('<>')}"),
        asyncio.to_thread(client.find_messages, f"rfc822msgid:{token.strip('<>')} in:sent"),
    )
    held = len(drafts)
    if not held and drafted_draft_id:
        try:
            found = await asyncio.to_thread(client.get_draft, drafted_draft_id)
            held = 1 if (found or {}).get("id") else 0
        except GmailError:
            held = 0
    gone = 1 if sent else 0
    if not gone and sent_message_id:
        try:
            gone = 1 if "SENT" in await asyncio.to_thread(client.message_labels, sent_message_id) else 0
        except GmailError:
            gone = 0
    return {"drafts": held, "sent": gone}


async def _observe_token(execution: dict) -> Observed:
    fingerprint = await _token_state(str(execution["token"]), str(execution.get("sent_message_id") or ""), str(execution.get("drafted_draft_id") or ""))
    if execution.get("draft_id"):
        try:
            body, _ = await _draft_text(str(execution["draft_id"]))
            fingerprint["draft_sha"] = _sha(body)
        except (ToolError, GmailError):
            fingerprint["draft_sha"] = ""
    return Observed(fingerprint=fingerprint, entity=None)


async def _check_order(order_id: str, ctx: dict[str, Any]) -> dict[str, str]:
    """A reply named with an order goes to that order's customer, in a thread that is about
    that order, or it is not staged. The recipient is the address the reply would actually go
    to; the thread is judged by `_about_this_order`."""
    customer = await _order_customer(order_id)
    if not customer.get("email") or customer["email"] != ctx["to_email"]:
        who = f"{ctx['to_email'] or 'an unknown address'}"
        if ctx.get("reply_to") and ctx.get("from_email") == customer.get("email"):
            who = f"{ctx['reply_to']} (the message asks for replies there, not to the customer's own address)"
        raise ToolError(f"That reply would go to {who}, not the customer on order {customer.get('label') or order_id}. Nothing was prepared.")
    confidence, other, why = _about_this_order(ctx, customer, order_id)
    if confidence != "confident":
        # The right person is not enough: the thread has to be about THIS order. A reply filed
        # in a thread she opened about another of her orders — or in one that could be about
        # any of them — carries this order's number on its card and reads to her as an answer
        # about whatever she asked. The deleted order→email family replied only from a
        # CONFIDENT link and showed a possible one without arming anything
        # (`order_email._choose`: "possible is never good enough to reply from"); the model
        # path keeps that rule here, where every reply naming an order passes (the 2026-09-28
        # deploy review, round 9, E-04 and I-tests3 I-02).
        label = str(customer.get("label") or order_id).lstrip("#")
        if other:
            raise ToolError(
                f"That thread is about order {other}, not order {label}. Nothing was prepared. Write a new email about "
                f"order {label}, or reply in that thread without naming an order."
            )
        raise ToolError(
            f"I can't tell that thread is about order {label}: {why}. Nothing was prepared. Reply in it without "
            f"naming an order, or write a new email about order {label}."
        )
    return customer


def _digits(number: Any) -> str:
    return str(number or "").rsplit("-", 1)[-1].lstrip("#").strip()


def _as_the_card_shows(thread_id: str, ctx: dict[str, Any]) -> str:
    """A reply goes only to the address the reply card on the owner's screen shows, and a
    Reply-To that is not the sender only once he has confirmed it there (round 13, S2b-01).
    Returns the id of the composer it is prepared from, "" when none is open for the thread."""
    from app.families.compose import reply_as_shown

    compose_id, why = reply_as_shown(str(thread_id), ctx)
    if why:
        raise ToolError(why)
    return compose_id


# Every run of digits in what an email says, however it is written: the round-13 check found
# "order1938" (a letter before it) and "#１９３８" (full-width digits) both passing the order
# pattern the thread card uses, so another customer's order could still be named to this one.
_DIGIT_RUN = re.compile(r"[0-9]+")


def _numbers_written(text: str) -> set[str]:
    """The numbers the words carry, as the reader sees them: any script's digits as ASCII (NFKC,
    then each decimal digit by its value), invisible format characters (a zero-width space
    between two digits) taken out, and a number with a letter or a sign before it still a number.
    Only whole runs: "19380" is not 1938, and "£19.38" is two numbers, 19 and 38."""
    plain = unicodedata.normalize("NFKC", "".join(ch for ch in str(text or "") if unicodedata.category(ch) != "Cf"))
    plain = "".join(str(unicodedata.decimal(ch)) if ch.isdecimal() else ch for ch in plain)
    return set(_DIGIT_RUN.findall(plain))


def _orders_named_in(text: str) -> dict[str, str]:
    """{number: order id} for every order this conversation holds whose number the words name:
    on its context stack, under a half's cursor, on a change it staged, read into the entity
    cache, or in the order cache — and always an id issued to this conversation."""
    from app.tools.context import CURRENT_SESSION

    named = _numbers_written(text)
    session = CURRENT_SESSION.get()
    if not named or session is None:
        return {}
    issued = {str(i) for i in (getattr(session, "issued_ids", None) or ()) if str(i).startswith("gid://shopify/Order/")}
    held: dict[str, str] = {}

    def hold(label: Any, ref: Any) -> None:
        if str(ref or "") in issued and _digits(label) in named:
            held.setdefault(_digits(label), str(ref))

    for entry in getattr(session, "context", None) or []:
        if isinstance(entry, dict) and entry.get("kind") == "order":
            hold(entry.get("label"), entry.get("ref"))
    for branch in (getattr(session, "branches", None) or {}).values():
        entity = getattr(branch, "entity", None) or {}
        if isinstance(entity, dict) and entity.get("kind") == "order":
            hold(entity.get("label"), entity.get("ref"))
    for proposal in getattr(session, "proposals", None) or []:
        if getattr(proposal, "entity_kind", "") == "order":
            hold(getattr(proposal, "entity_label", ""), getattr(proposal, "entity_ref", ""))
    for row in _warm_rows():
        hold(row.get("order_number"), row.get("order_id"))
    try:
        from app.memory import ENTITY
        from app.memory import current as memory

        for ref in sorted(issued):
            entry = memory().get(ENTITY, f"order:{ref}", allow_stale=True)
            value = getattr(entry, "value", None) if entry is not None else None
            if isinstance(value, dict):
                hold(value.get("order_number"), ref)
    except Exception:  # noqa: BLE001 — no memory bound (a unit test, a cold start) is fewer orders held
        pass
    return held


async def _held_to_the_orders_it_names(text: str, ctx: dict[str, Any]) -> None:
    """A reply whose words name an order this conversation holds goes to that order's customer,
    or it is not prepared — whether or not the model said which order it was about (round 13,
    R9-E-families1-E-04 / R9-I-tests3-I-02). Before, the order was held to the reply only when
    the model passed `order_id`, so another customer's order could be answered in anyone's
    thread with no check but the owner's hold. The refusal names the order and the recipient,
    never whose order it is."""
    number = await _an_order_not_theirs(text, str(ctx["to_email"] or ""))
    if number:
        raise ToolError(
            f"That reply names order {number}, and it would go to {ctx['to_email'] or 'an unknown address'}, who is "
            "not the customer on that order. Nothing was prepared. Take the order out of the reply, or answer "
            "that order's customer in their own thread."
        )


async def _new_email_held_to_the_orders_it_names(text: str, customer: dict[str, Any]) -> None:
    """The same for a new email: its subject and body name only orders whose customer it goes
    to (round 13, integration). The orders builder closed the reply and left the new email: an
    email to David, written from his own order or from an address the owner dictated, could
    carry "#1938 is packed" — Mia's order, read a moment ago — with nothing between it and
    David's inbox but the owner's hold."""
    number = await _an_order_not_theirs(text, str(customer.get("email") or ""))
    if number:
        raise ToolError(
            f"That email names order {number}, and it would go to {customer.get('email') or 'an unknown address'}, who "
            "is not the customer on that order. Nothing was prepared. Take the order out of the email, or write to "
            "that order's customer."
        )


async def _an_order_not_theirs(text: str, email: str) -> str:
    """The first order, by number, that the words name, that this conversation holds, and whose
    customer is not `email`; "" when every order named is theirs (or none is named)."""
    for number, order_id in sorted(_orders_named_in(text).items()):
        customer = await _order_customer(order_id)
        if not customer.get("email") or customer["email"] != email.strip().lower():
            return number
    return ""


def _held_messages(thread_id: str) -> list[dict[str, Any]]:
    """The thread's messages as this conversation was shown them, when the Mac holds the
    thread (`gmail_read_thread` puts it in the entity cache); empty otherwise. Read, never
    fetched: the words are evidence of which order the thread is about, and a missing copy
    only means there is less of it."""
    try:
        from app.memory import ENTITY
        from app.memory import current as memory

        entry = memory().get(ENTITY, f"email_thread:{thread_id}", allow_stale=True)
    except Exception:  # noqa: BLE001 — no memory bound (a unit test, a cold start) is no copy
        return []
    thread = getattr(entry, "value", None) if entry is not None else None
    messages = thread.get("messages") if isinstance(thread, dict) else None
    return [m for m in messages if isinstance(m, dict)] if isinstance(messages, list) else []


def _warm_rows() -> list[dict[str, Any]]:
    """The order cache's rows when it has synced; empty when it has not or is not bound."""
    try:
        from app.tools.analytics_tools import cache

        held = cache()
        return list(held.rows() or []) if held.status().get("synced_at") is not None else []
    except Exception:  # noqa: BLE001 — no cache bound (a Mac without Shopify, a unit test) is a cold cache
        return []


def _about_this_order(ctx: dict[str, Any], customer: dict[str, str], order_id: str) -> tuple[str, str, str]:
    """(confidence, another order of hers it is about, why) that this thread is about this
    order, for a reply already proven to go to the order's customer.

    `order_email.about_this_order`'s rule, which the model path lost with that family and
    keeps here. The strong reading is the graph the thread card's linked-order strip uses
    (`app/context/graph.py`) over the order cache the Mac already holds: it knows her OTHER
    orders, so it tells "she wrote about #1930" from "she wrote about #1931", and a year or a
    tracking fragment is never taken for an order. A thread it links confidently to another
    order is not this order's thread; one it links only possibly — several recent orders and
    nothing saying which — is not confidently this order's either. A cold cache, or an order
    too old to be in it, falls back to the narrow rule: this order's number in the thread is
    confident, another number is not this order, and no number at all is only possible.
    """
    from app.context import graph

    this = _digits(customer.get("label"))
    email = str(customer.get("email") or "").strip().lower()
    subject = str(ctx.get("subject") or "")
    messages = _held_messages(str(ctx.get("thread_id") or ""))
    rows = _warm_rows()
    if rows:
        found = graph.linked_orders_for_thread({"subject": subject, "from_email": email, "messages": messages}, rows=rows)
        linked = [o for o in found.get("linked") or [] if isinstance(o, dict)]
        confidence = str(found.get("confidence") or "none")
        if any(str(o.get("order_id") or "") == str(order_id) for o in linked):
            if confidence == "confident":
                return "confident", "", ""
            return "possible", "", "; ".join(str(r) for r in found.get("provenance") or []) or "the link is only possible"
        if confidence == "confident" and linked:
            return "none", _digits(linked[0].get("order_number")) or "another order", ""
    text = " ".join([subject] + [f"{m.get('subject') or ''} {m.get('body') or m.get('snippet') or ''}" for m in messages])
    named = graph.order_numbers_in(text)
    if this and this in named:
        return "confident", "", ""
    if named:
        return "none", "", f"it names {named[0]}, not {this or 'this order'}"
    return "possible", "", "it does not name an order, and nothing I hold says which of the customer's orders it is about"


def _provenance(ctx: dict[str, Any]) -> str:
    line = f"{ctx['from_email']}, {_when(ctx['date'])} · {'verified sender' if ctx['authenticated'] else 'sender not verified'}"
    if ctx.get("reply_to") and ctx["reply_to"] != ctx["from_email"]:
        line += f" · replies go to {ctx['reply_to']}"
    return line


async def _the_one_draft(ctx: dict[str, Any], where: str) -> dict[str, Any]:
    """Exactly one draft waiting from this mailbox, as Gmail holds it: its recipient, subject
    and text are read from the draft itself, never assumed. A send never guesses between two."""
    drafts = ctx["drafts"]
    if not drafts:
        raise ToolError(f"There is no draft waiting {where}. Say what the email should say.")
    if len(drafts) > 1:
        raise ToolError(f"There are {len(drafts)} drafts waiting {where}; delete the extra ones in Gmail first.")
    token = drafts[0]["token"]
    listed = await asyncio.to_thread(_g().list_drafts, f"rfc822msgid:{token.strip('<>')}")
    if len(listed) != 1:
        raise ToolError("That draft could not be found in Gmail.")
    body, headers = await _draft_text(listed[0]["draft_id"])
    to_name, to_email = parseaddr(headers.get("to", ""))
    if "@" not in to_email or headers.get("cc") or headers.get("bcc"):
        raise ToolError("That draft has no single recipient; fix it in Gmail or say what the email should say.")
    return {
        "draft_id": listed[0]["draft_id"], "token": token, "body": body, "to": to_email.strip().lower(), "to_name": to_name.strip(),
        "subject": " ".join(str(headers.get("subject") or "").split()), "sha": _sha(body),
    }


# ----------------------------------------------------------------------- executing


async def _execute_draft(execution: dict) -> dict:
    client = _g()
    if execution.get("delete"):
        drafts = await asyncio.to_thread(client.list_drafts, f"rfc822msgid:{str(execution['token']).strip('<>')}")
        for draft in drafts:
            await asyncio.to_thread(client.delete_draft, draft["draft_id"])
        return {"deleted": len(drafts)}
    return await asyncio.to_thread(client.create_draft, str(execution["raw"]), execution.get("thread_id") or None)


async def _execute_send(execution: dict) -> dict:
    client = _g()
    if execution.get("draft_id"):
        return await asyncio.to_thread(client.send_draft, str(execution["draft_id"]))
    return await asyncio.to_thread(client.send_message, str(execution["raw"]), execution.get("thread_id") or None)


async def _settle_send(execution: dict, sent: dict) -> None:
    """Gmail lists a sent message a moment after the answer; wait for the thread (or the
    search) to show it, bounded, so the proof reads what is there. The id Gmail handed back
    is kept for the proof: a message Gmail says it sent is proven by its own labels even if
    the Message-ID header was rewritten on the way."""
    if sent.get("message_id"):
        execution["sent_message_id"] = str(sent["message_id"])
    deadline = time.monotonic() + SETTLE_S
    while time.monotonic() < deadline:
        try:
            if execution.get("thread_id"):
                ctx = await thread_context(str(execution["thread_id"]))
                if _thread_fingerprint(ctx, str(execution["token"]), str(execution.get("sent_message_id") or ""))["sent"]:
                    await _after_sent(execution)
                    return
            elif (await _token_state(str(execution["token"]), str(execution.get("sent_message_id") or "")))["sent"]:
                await _after_sent(execution)
                return
        except (ToolError, GmailError) as exc:
            log.info("settle: %s", exc)
        await asyncio.sleep(SETTLE_POLL_S)


# [inbox, ruling 28] What a proven send says after its success line about CLIVE's own drafts it
# replaced, by the send's Message-ID: written by the settle step, read once by the proof.
_AFTER_SENT_NOTES: dict[str, str] = {}


async def _after_sent(execution: dict) -> None:
    """The send is proven in Gmail. A draft it was (CLIVE's own, sent as Gmail held it) is settled in
    CLIVE's record as sent, and CLIVE's own unsent drafts that the card said this reply replaces are
    taken away — only those, and only now. Never raises: the send has happened whatever follows."""
    from app.tools import gmail_drafts

    try:
        if execution.get("draft_id"):
            gmail_drafts.note_gone(str(execution["token"]), gmail_drafts.SENT, "sent")
        note = await gmail_drafts.replaced([str(d) for d in execution.get("replaces") or []])
        if note:
            _AFTER_SENT_NOTES[str(execution["token"])] = note
    except Exception as exc:  # noqa: BLE001
        log.warning("after a send, CLIVE's own drafts were not tidied (%s)", type(exc).__name__)


async def _settle_draft(execution: dict, created: dict) -> None:
    """Gmail lists a new draft a moment after answering the create. Wait for it, bounded, so
    the proving read looks at a thread that has it — rather than calling a draft that exists
    "not created". The ids Gmail handed back are kept for the proof.

    Nothing here can make an absent draft look present: if the poll never sees it, the proof
    runs on the same read it would have run on, and the change settles UNVERIFIED."""
    from app.tools import gmail_drafts

    if created.get("message_id"):
        execution["drafted_message_id"] = str(created["message_id"])
    if created.get("draft_id"):
        execution["drafted_draft_id"] = str(created["draft_id"])
    if execution.get("delete"):
        # [inbox, ruling 28] The undo of a draft CLIVE saved: it leaves CLIVE's record with it.
        gmail_drafts.note_gone(str(execution.get("token") or ""), gmail_drafts.DELETED, "undone")
        return
    deadline = time.monotonic() + SETTLE_S
    while time.monotonic() < deadline:
        try:
            if execution.get("thread_id"):
                ctx = await thread_context(str(execution["thread_id"]))
                if _thread_fingerprint(ctx, str(execution["token"]), "", str(execution.get("drafted_message_id") or ""))["drafts"] == 1:
                    break
            elif (await _token_state(str(execution["token"]), "", str(execution.get("drafted_draft_id") or "")))["drafts"] == 1:
                break
        except (ToolError, GmailError) as exc:
            log.info("settle draft: %s", exc)
        await asyncio.sleep(SETTLE_POLL_S)
    # [inbox, ruling 28] Gmail answered CLIVE's own create with a draft id: written down as CLIVE's,
    # which is the only thing that ever lets CLIVE take a draft away again (app/tools/gmail_drafts.py).
    await gmail_drafts.note_made(execution, created)


def _verify_drafted(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    return observed.get("drafts") == 1 and not observed.get("sent"), ""


def _verify_sent(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    return bool(observed.get("sent")), _AFTER_SENT_NOTES.pop(str(execution.get("token") or ""), "")


def _undo_draft(execution: dict) -> dict:
    return {"thread_id": execution.get("thread_id", ""), "token": execution["token"], "delete": True}


def _draft_risk(prepared: Prepared):
    """A draft to a sender nobody vouched for, on a thread no order ties to a customer, is
    held like a send: the owner reads who it is to before it exists anywhere."""
    s = prepared.summary
    if s.get("in_reply_to") and not s.get("verified_sender") and not s.get("order_line"):
        return "RED"
    return None


async def _entity_email(execution: dict) -> dict:
    return {"kind": "email", "to": str(execution.get("to") or ""), "subject": str(execution.get("subject") or ""), "body": str(execution.get("body") or ""), "state": str(execution.get("state") or "")}


def _present_email(proposal) -> dict:
    s = proposal.summary
    sending = s.get("sending")
    if proposal.undo_of:
        return {"title": "Delete the draft", "summary": "", "detail": "Removes the draft from Gmail.", "confirm_label": "Tap to delete", "undone_title": "Draft deleted"}
    facts = [{"label": "To", "value": str(s.get("to_line") or "")}, {"label": "Subject", "value": str(s.get("subject") or "")}]
    if s.get("in_reply_to"):
        facts.append({"label": "Replying to", "value": str(s["in_reply_to"]), "tone": "" if s.get("verified_sender") else "warn"})
    if s.get("order_line"):
        facts.append({"label": "Order", "value": str(s["order_line"])})
    elif s.get("in_reply_to"):
        facts.append({"label": "Order", "value": "not checked — the reply goes to whoever wrote last in the thread", "tone": "warn"})
    if s.get("off_shopify"):
        # The whole point of the compose family, said on the card the gesture is on: this
        # address is nobody the shop knows, and the owner is the only check on it.
        facts.append({"label": "Recipient", "value": "not a Shopify customer — the address you gave", "tone": "warn"})
    if s.get("draft_used"):
        facts.append({"label": "Draft", "value": "the one waiting in Gmail, as it reads now"})
    if s.get("words_line"):
        # [inbox, ruling 34] A draft sent as Gmail holds it: whose words, and whose hold sends them.
        facts.append({"label": "Words", "value": str(s["words_line"])})
        facts.append({"label": "Sent by", "value": str(s.get("sender_line") or "")})
    if s.get("replaces_line"):
        # [inbox, ruling 28] CLIVE's own earlier draft in this thread, taken away once this goes.
        facts.append({"label": "Earlier draft", "value": str(s["replaces_line"])})
    if sending:
        facts.append({"label": "From", "value": str(s.get("from_line") or "")})
    return {
        "title": str(s.get("title") or ("Send the email" if sending else "Save a draft")),
        "summary": "", "body": str(s.get("body") or ""), "facts": facts,
        "detail": "Sends now. It cannot be unsent." if sending else "Saved in Gmail drafts; nothing is sent until you say so.",
        "done_title": ("Draft sent" if s.get("words_line") else "Reply sent" if s.get("in_reply_to") else "Email sent") if sending else "Draft saved",
        # [flow, DEC-069] The message card: the email as it would leave, its words editable on
        # the card, and the one gesture that sends it (app/presentation.py `_message_block`).
        "message": _message_words(proposal, s, sending=bool(sending)),
        **({"confirm_label": "Hold, then tap to send"} if sending else {}),
    }


# [flow, DEC-069] Which tool the same words are prepared as instead: the quiet second control on
# the message card. A send offers to keep it as a draft; a draft offers to send it instead.
_OTHER_WAY = {
    "gmail_send_reply": ("gmail_draft_reply", "Save as draft"),
    "gmail_send_new": ("gmail_draft_new", "Save as draft"),
    "gmail_draft_reply": ("gmail_send_reply", "Send instead"),
    "gmail_draft_new": ("gmail_send_new", "Send instead"),
}


def _message_words(proposal, s: dict, *, sending: bool) -> dict:
    """The email as the message card shows it (the contract is `app/presentation.py`
    `_message_block`): who it goes to, the subject, the words, which of them he may change on
    the card and the argument each change is prepared again with, and the other way to prepare
    the same words. A send of the draft already waiting in Gmail is that draft as Gmail holds
    it, so its words are not edited here and it has no other way."""
    tool = str(getattr(proposal, "tool_name", "") or "")
    # A draft sent as Gmail holds it is a reply when its thread has someone's message to answer.
    reply = tool.endswith("_reply") or bool(s.get("reply"))
    from_draft = bool(s.get("draft_used"))
    editable = [] if from_draft else (["body"] if reply else ["subject", "body"])
    other = None if from_draft else _OTHER_WAY.get(tool)
    sent = str(s.get("body") or "")
    # The words as they were given, which is what a keystroke edits: the text that goes is these
    # with their edges trimmed and the store's sign-off added (`clean_body`), and the sign-off is
    # shown under them as what it is rather than as words he typed.
    given = dict(getattr(proposal, "model_args", None) or {})
    words = str(given.get("body") or "") if editable and str(given.get("body") or "").strip() else sent
    signature = str(getattr(_settings(), "gmail_signature", "") or "").strip()
    sign_off = signature if signature and sent.rstrip().endswith(signature) and not words.rstrip().endswith(signature) else ""
    subject = str(given.get("subject") or "") if "subject" in editable and str(given.get("subject") or "").strip() else str(s.get("subject") or "")
    return {
        "channel": "email", "kind": "reply" if reply else "new",
        "to": str(s.get("to_line") or ""), "subject": subject, "body": words, "sign_off": sign_off,
        "editable": editable, "args": {field: field for field in editable},
        "other": {"tool": other[0], "label": other[1]} if other else None,
        "sending": sending,
    }


def _prepared_email(*, execution: dict, before: dict, expected_after: dict, entity_ref: str, ctx: dict | None, customer: dict | None, sending: bool, title: str, sender: str, kind: str) -> Prepared:
    to_email, to_name = execution["to"], execution.get("to_name", "")
    first = _first_name(to_name, to_email)
    to_line = f"{to_name} <{to_email}>" if to_name else to_email
    about = f" about order {customer['label'].lstrip('#')}" if customer and customer.get("label") else ""
    read_back = f"{'send' if sending else 'draft'} {'a reply' if ctx else 'an email'} to {first}{about}"
    if execution.get("draft_id"):
        read_back = f"send the draft waiting for {first}{about}"
    # An address the owner dictated has no Shopify record behind it, so it has no order line
    # and it must not be counted as a checked recipient — `to_checked` in the ledger means
    # "the address came from the shop", and a compose to a stranger would have claimed it.
    off_shopify = bool(customer and customer.get("off_shopify"))
    label = f"#{customer['label'].lstrip('#')}" if customer and customer.get("label") else "thread" if ctx else "new email" if off_shopify else "customer"
    order_line = ""
    if customer and customer.get("label"):
        order_line = f"#{customer['label'].lstrip('#')} · the customer on the order"
    elif customer and not off_shopify:
        order_line = "the customer's record in Shopify"
    return Prepared(
        execution=execution, before=before, expected_after=expected_after, entity_ref=entity_ref, entity_label=label,
        summary={
            "title": title, "sending": sending, "to_line": to_line, "spoken_to": first, "subject": execution["subject"], "body": execution["body"],
            "in_reply_to": _provenance(ctx) if ctx else "", "verified_sender": bool(ctx and ctx["authenticated"]),
            "order_line": order_line, "draft_used": bool(execution.get("draft_id")),
            "off_shopify": off_shopify,
            "from_line": sender, "read_back": read_back, "pii": [v for v in (to_email, to_name, execution["subject"]) if v],
            "ledger": {
                "kind": kind, "reply": bool(ctx), "draft_used": bool(execution.get("draft_id")), "chars": len(execution["body"]),
                "verified_sender": bool(ctx and ctx["authenticated"]), "to_checked": bool(customer) and not off_shopify,
            },
        },
    )


def _the_thread_for_a_reply(ctx: dict[str, Any], order_id: str) -> None:
    if not ctx["has_inbound"]:
        raise ToolError("There is no message from the customer in that thread to reply to.")
    if len(ctx["senders"]) > 1 and not order_id:
        raise ToolError(
            f"That thread has messages from {len(ctx['senders'])} people; say which order it is about, so the reply goes to its customer."
        )


# --------------------------------------------------------------------------- the tools

_REPLY_SCHEMA = {
    "thread_id": {"type": "string", "description": "From gmail_search or the order's email."},
    "body": {"type": "string", "maxLength": MAX_BODY_CHARS, "description": "The reply, plainly. The sign-off is added."},
    "order_id": {"type": "string", "description": "The order it is about, when the thread came from an order; the reply must go to its customer."},
}


@tool(
    name="gmail_draft_reply",
    description="Only when he asks to keep a reply as a Gmail draft, unsent. To reply, use gmail_send_reply.",
    input_schema={"type": "object", "properties": dict(_REPLY_SCHEMA), "required": ["thread_id", "body"]},
    tier=Tier.AMBER,
    issued_id_args=("thread_id", "order_id"),
    write=WriteSpec(
        operation="gmail_draft_reply", entity_kind="email", entity_arg="thread_id", mutation="gmail:draft",
        observe=_observe_thread, execute=_execute_draft, present=_present_email, entity=_entity_email, verify=_verify_drafted, settle=_settle_draft,
        reversible=True, undo=_undo_draft, op_class="reversible", risk=_draft_risk,
        spoken_success="Draft saved to {to}. It's in Gmail, not sent.", spoken_undo_success="Draft deleted.",
        spoken_failure="I couldn't confirm the draft was saved. Check Gmail's drafts.",
        spoken_stale="A new message arrived in that thread since this was prepared. Nothing was saved.",
    ),
)
async def gmail_draft_reply(thread_id: str, body: str, order_id: str = "") -> Prepared:
    client = _g()
    ctx = await thread_context(str(thread_id))
    _the_thread_for_a_reply(ctx, order_id)
    shown = _as_the_card_shows(str(thread_id), ctx)
    customer = await _check_order(order_id, ctx) if order_id else None
    text = clean_body(body)
    await _held_to_the_orders_it_names(text, ctx)
    sender = await asyncio.to_thread(client.address)
    token = new_token(sender)
    subject = reply_subject(ctx["subject"])
    raw = build_raw(sender=sender, sender_name=str(getattr(_settings(), "gmail_from_name", "") or ""), to=ctx["to_email"], to_name=ctx["to_name"],
                    subject=subject, body=text, token=token, in_reply_to=ctx["in_reply_to"], references=ctx["references"])
    execution = {"thread_id": str(thread_id), "token": token, "raw": raw, "to": ctx["to_email"], "to_name": ctx["to_name"], "subject": subject, "body": text, "state": "draft",
                 **({"compose_id": shown} if shown else {})}
    before = _thread_fingerprint(ctx, token)
    return _prepared_email(execution=execution, before=before, expected_after={**before, "drafts": 1}, entity_ref=str(thread_id), ctx=ctx, customer=customer,
                           sending=False, title="Save a draft reply", sender=sender, kind="draft_reply")


@tool(
    name="gmail_send_reply",
    description=(
        "Reply in a customer's thread to the sender of the message it answers, in your own plain words. "
        "The card is the reply: he can edit it there and his hold sends it. Empty body: send the one "
        "draft waiting in that thread, as Gmail holds it."
    ),
    input_schema={"type": "object", "properties": dict(_REPLY_SCHEMA), "required": ["thread_id"]},
    tier=Tier.RED,
    issued_id_args=("thread_id", "order_id"),
    write=WriteSpec(
        operation="gmail_send_reply", entity_kind="email", entity_arg="thread_id", mutation="gmail:send",
        observe=_observe_thread, execute=_execute_send, present=_present_email, entity=_entity_email, verify=_verify_sent, settle=_settle_send,
        reversible=False, op_class="irreversible",
        spoken_success="Reply sent to {to}.",
        spoken_failure="I couldn't confirm the reply went. Check Sent in Gmail before sending again.",
        spoken_stale="That thread or its draft changed since this was prepared. Nothing was sent.",
    ),
)
async def gmail_send_reply(thread_id: str, body: str = "", order_id: str = "") -> Prepared:
    client = _g()
    ctx = await thread_context(str(thread_id))
    _the_thread_for_a_reply(ctx, order_id)
    shown = _as_the_card_shows(str(thread_id), ctx)
    customer = await _check_order(order_id, ctx) if order_id else None
    sender = await asyncio.to_thread(client.address)
    if str(body or "").strip():
        text = clean_body(body)
        token = new_token(sender)
        subject = reply_subject(ctx["subject"])
        raw = build_raw(sender=sender, sender_name=str(getattr(_settings(), "gmail_from_name", "") or ""), to=ctx["to_email"], to_name=ctx["to_name"],
                        subject=subject, body=text, token=token, in_reply_to=ctx["in_reply_to"], references=ctx["references"])
        execution = {"thread_id": str(thread_id), "token": token, "raw": raw, "draft_id": "", "to": ctx["to_email"], "to_name": ctx["to_name"], "subject": subject, "body": text, "state": "sent"}
    else:
        draft = await _the_one_draft(ctx, "in that thread")
        if draft["to"] != ctx["to_email"]:
            raise ToolError(
                f"The draft in Gmail is addressed to {draft['to']}; the latest message is from {ctx['to_email']}. Say who this reply is to, or say what it should say."
            )
        execution = {
            "thread_id": str(thread_id), "token": draft["token"], "raw": "", "draft_id": draft["draft_id"], "to": draft["to"], "to_name": draft["to_name"] or ctx["to_name"],
            "subject": draft["subject"] or reply_subject(ctx["subject"]), "body": draft["body"], "state": "sent",
        }
    # The waiting draft's own subject is held too, unless it is the thread's: the customer's own
    # subject line ("Re: Order 1930 — is this mine?") names what they asked about, to them.
    own = {" ".join(str(ctx["subject"] or "").split()).casefold(), " ".join(reply_subject(ctx["subject"]).split()).casefold()}
    subject_written = "" if " ".join(str(execution["subject"] or "").split()).casefold() in own else str(execution["subject"] or "")
    await _held_to_the_orders_it_names(f"{subject_written}\n{execution['body']}", ctx)
    if shown:
        execution["compose_id"] = shown
    before = _thread_fingerprint(ctx, execution["token"])
    if before["sent"]:
        raise ToolError("That was already sent.")
    if execution["draft_id"]:
        before["draft_sha"] = draft["sha"]
    whose = _gmail_whose(draft) if execution["draft_id"] else None
    replaces = await _replaces(str(thread_id), execution)
    prepared = _prepared_email(execution=execution, before=before, expected_after={**before, "drafts": 0, "sent": 1}, entity_ref=str(thread_id), ctx=ctx, customer=customer,
                               sending=True, title="Send the reply", sender=sender, kind="send_reply")
    if whose is not None and whose["asker"]:
        # [inbox, ruling 34] The draft waiting in the thread, sent as Gmail holds it: whose words, whose hold.
        prepared.summary.update(words_line=whose["words_line"], sender_line=whose["sender_line"])
    return _with_replaces(prepared, replaces)


async def _replaces(thread_id: str, execution: dict) -> list[dict[str, Any]]:
    """[inbox, ruling 28] CLIVE's own unsent reply drafts in this thread that this reply replaces,
    checked in Gmail now; their ids go with the change, so the commit takes away only those."""
    from app.tools import gmail_drafts

    found = await gmail_drafts.replaceable(thread_id, besides=str(execution.get("draft_id") or ""))
    execution["replaces"] = [str(r["draft_id"]) for r in found]
    return found


def _gmail_whose(draft: dict[str, Any]) -> dict[str, str]:
    from app.tools import gmail_drafts

    return gmail_drafts.whose_draft(draft)


def _with_replaces(prepared: Prepared, replaces: list[dict[str, Any]]) -> Prepared:
    from app.tools import gmail_drafts

    if replaces:
        prepared.summary["replaces_line"] = gmail_drafts.replaces_line(replaces)
    return prepared


_NEW_SCHEMA = {
    "order_id": {"type": "string", "description": "The order whose customer this goes to."},
    "customer_id": {"type": "string", "description": "Or the customer, when there is no visible order."},
    "subject": {"type": "string", "maxLength": MAX_SUBJECT_CHARS, "description": "One plain line."},
    "body": {"type": "string", "maxLength": MAX_BODY_CHARS, "description": "The email, plainly. The sign-off is added."},
    # The third recipient, added in Phase 3 for arbitrary compose (app/families/compose.py).
    # An address is only admitted WITH the `compose_id` of a composer this conversation was
    # given, and the gate checks that id against `session.issued_ids` like any other — so an
    # address can only be staged from a composer whose card the owner has already seen, and
    # never from an address a model produced mid-sentence. Nothing like this can be done with
    # the address itself: an address is not a well-formed id (gate._ID_SHAPE has no "@").
    "compose_id": {"type": "string", "description": "From gmail_compose_open; required with `to`."},
    "to": {"type": "string", "maxLength": MAX_ADDRESS_CHARS, "description": "One address the owner gave, instead of an order or customer."},
    "to_name": {"type": "string", "maxLength": 80, "description": "Their name, if said."},
}


async def _recipient(order_id: str, customer_id: str, to: str = "", to_name: str = "", compose_id: str = "") -> dict[str, str]:
    """Who a new email is to. Three sources, exactly one of them: the order's customer, the
    customer record, or an address the owner dictated into an open composer.

    The bench refused "write an email to a model … their email is 4417lighthousepony@
    example.com" because a recipient had to be a Shopify customer. It does not any more — but
    the address is still not the model's to invent: it arrives with a `compose_id` the gate
    has already held to this conversation's issued ids, and `off_shopify` follows it onto the
    card so the owner reads "not a Shopify customer" before the gesture.
    """
    address = " ".join(str(to or "").split())
    if address:
        if order_id or customer_id:
            raise ToolError("Say which order — or which customer — or an address, not two of them.")
        if not str(compose_id or "").strip():
            raise ToolError("An email to an address is prepared from an open composer; call gmail_compose_open first.")
        if len(address) > MAX_ADDRESS_CHARS or not EMAIL_ADDRESS.match(address):
            raise ToolError(f"{address!r} is not an email address I can send to.")
        # The composer's own card decides, not the argument: the address must be the one on
        # it, and the owner must have checked it there. An issued compose id beside any
        # address the model chose was enough before, so a mis-heard address the model wrote
        # down cleanly could be staged without the owner ever touching it (the 2026-09-28
        # deploy review, round 9, E-02). Imported here because the family imports this module.
        from app.families.compose import owner_checked

        why = owner_checked(str(compose_id), address)
        if why:
            raise ToolError(why)
        return {"name": " ".join(str(to_name or "").split())[:80], "email": address.lower(), "label": "", "off_shopify": True}
    if bool(order_id) == bool(customer_id):
        raise ToolError("Say which order — or, without one, which customer — the email is to.")
    customer = await _order_customer(order_id, customer_id)
    if not customer.get("email"):
        raise ToolError(f"{customer.get('label') or customer.get('name') or 'That customer'} has no email address.")
    return customer


@tool(
    name="gmail_draft_new",
    description=(
        "Only when he asks to keep a new email as a Gmail draft, unsent; the address comes from "
        "Shopify. To email, use gmail_send_new."
    ),
    input_schema={"type": "object", "properties": dict(_NEW_SCHEMA), "required": ["subject", "body"]},
    tier=Tier.AMBER,
    issued_id_args=("order_id", "customer_id", "compose_id"),
    write=WriteSpec(
        operation="gmail_draft_new", entity_kind="email", entity_arg="order_id", mutation="gmail:draft",
        observe=_observe_token, execute=_execute_draft, present=_present_email, entity=_entity_email, verify=_verify_drafted, settle=_settle_draft,
        reversible=True, undo=_undo_draft, op_class="reversible",
        spoken_success="Draft saved to {to}. It's in Gmail, not sent.", spoken_undo_success="Draft deleted.",
        spoken_failure="I couldn't confirm the draft was saved. Check Gmail's drafts.",
        spoken_stale="That changed since it was prepared. Nothing was saved.",
    ),
)
async def gmail_draft_new(subject: str, body: str, order_id: str = "", customer_id: str = "", to: str = "", to_name: str = "", compose_id: str = "") -> Prepared:
    client = _g()
    customer = await _recipient(order_id, customer_id, to, to_name, compose_id)
    text = clean_body(body)
    line = clean_subject(subject)
    await _new_email_held_to_the_orders_it_names(f"{line}\n{text}", customer)
    sender = await asyncio.to_thread(client.address)
    token = new_token(sender)
    raw = build_raw(sender=sender, sender_name=str(getattr(_settings(), "gmail_from_name", "") or ""), to=customer["email"], to_name=customer.get("name", ""), subject=line, body=text, token=token)
    execution = {"thread_id": "", "token": token, "raw": raw, "to": customer["email"], "to_name": customer.get("name", ""), "subject": line, "body": text, "state": "draft"}
    before = {"drafts": 0, "sent": 0}
    return _prepared_email(execution=execution, before=before, expected_after={"drafts": 1, "sent": 0}, entity_ref=str(order_id or customer_id or compose_id), ctx=None, customer=customer,
                           sending=False, title="Save a draft", sender=sender, kind="draft_new")


@tool(
    name="gmail_send_new",
    description=(
        "A new email to an order's customer (or a customer with no visible order); the address comes "
        "from Shopify. Subject and body in your own plain words: the card is the email, he can edit it "
        "there and his hold sends it. Both empty: send the one draft waiting for that customer."
    ),
    input_schema={"type": "object", "properties": dict(_NEW_SCHEMA), "required": []},
    tier=Tier.RED,
    issued_id_args=("order_id", "customer_id", "compose_id"),
    write=WriteSpec(
        operation="gmail_send_new", entity_kind="email", entity_arg="order_id", mutation="gmail:send",
        observe=_observe_token, execute=_execute_send, present=_present_email, entity=_entity_email, verify=_verify_sent, settle=_settle_send,
        reversible=False, op_class="irreversible",
        spoken_success="Email sent to {to}.",
        spoken_failure="I couldn't confirm the email went. Check Sent in Gmail before sending again.",
        spoken_stale="That draft changed since it was prepared. Nothing was sent.",
    ),
)
async def gmail_send_new(subject: str = "", body: str = "", order_id: str = "", customer_id: str = "", to: str = "", to_name: str = "", compose_id: str = "") -> Prepared:
    client = _g()
    customer = await _recipient(order_id, customer_id, to, to_name, compose_id)
    sender = await asyncio.to_thread(client.address)
    draft = None
    if str(body or "").strip() or str(subject or "").strip():
        text = clean_body(body)
        line = clean_subject(subject)
        token = new_token(sender)
        raw = build_raw(sender=sender, sender_name=str(getattr(_settings(), "gmail_from_name", "") or ""), to=customer["email"], to_name=customer.get("name", ""), subject=line, body=text, token=token)
        execution = {"thread_id": "", "token": token, "raw": raw, "draft_id": "", "to": customer["email"], "to_name": customer.get("name", ""), "subject": line, "body": text, "state": "sent"}
    else:
        listed = await asyncio.to_thread(client.list_drafts, f"in:draft to:{customer['email']}")
        ours = []
        for d in listed:
            body_text, headers = await _draft_text(d["draft_id"])
            token = headers.get("message-id", "").strip()
            to_name, to_email = parseaddr(headers.get("to", ""))
            if _MESSAGE_ID.match(token) and not headers.get("in-reply-to") and to_email.strip().lower() == customer["email"] and not headers.get("cc") and not headers.get("bcc"):
                ours.append({"draft_id": d["draft_id"], "token": token, "subject": " ".join(str(headers.get("subject") or "").split()), "body": body_text, "to_name": to_name.strip(), "sha": _sha(body_text)})
        who = customer.get("name") or customer["email"]
        if not ours:
            raise ToolError(f"There is no draft waiting for {who}. Say what the email should say.")
        if len(ours) > 1:
            raise ToolError(f"There are {len(ours)} drafts waiting for {who}; delete the extra ones in Gmail first.")
        draft = ours[0]
        execution = {"thread_id": "", "token": draft["token"], "raw": "", "draft_id": draft["draft_id"], "to": customer["email"], "to_name": draft["to_name"] or customer.get("name", ""), "subject": draft["subject"], "body": draft["body"], "state": "sent"}
    # Fresh words or the draft Gmail holds, the words that would leave are held the same way.
    await _new_email_held_to_the_orders_it_names(f"{execution['subject']}\n{execution['body']}", customer)
    before = await _token_state(execution["token"])
    if before["sent"]:
        raise ToolError("That was already sent.")
    if draft is not None:
        before["draft_sha"] = draft["sha"]
    return _prepared_email(execution=execution, before=before, expected_after={"drafts": 0, "sent": 1}, entity_ref=str(order_id or customer_id or compose_id), ctx=None, customer=customer,
                           sending=True, title="Send the email", sender=sender, kind="send_new")


# ------------------------------------------------------------------------ the inbox


async def _observe_inbox(execution: dict) -> Observed:
    labels = await asyncio.to_thread(_g().thread_labels, str(execution["thread_id"]))
    return Observed(fingerprint={"inbox": "INBOX" in labels}, entity=None)


async def _execute_archive(execution: dict) -> dict:
    await asyncio.to_thread(_g().modify_thread, str(execution["thread_id"]), add=list(execution.get("add") or []), remove=list(execution.get("remove") or []))
    return {"thread_id": str(execution["thread_id"])}


def _present_archive(proposal) -> dict:
    s = proposal.summary
    if proposal.undo_of:
        return {"title": "Put it back in the inbox", "summary": "", "detail": "", "confirm_label": "Tap to undo", "undone_title": "Back in the inbox"}
    return {
        "title": "Archive the thread", "summary": "", "detail": "Leaves the inbox; still there in All Mail and in search. Undo puts it back.",
        "facts": [{"label": "Thread", "value": str(s.get("subject") or "")}, {"label": "From", "value": str(s.get("from_line") or "")}],
        "done_title": "Archived",
    }


@tool(
    name="gmail_thread_archive",
    description="Archive an email thread: it leaves the inbox and stays in All Mail. Undo puts it back.",
    input_schema={"type": "object", "properties": {"thread_id": {"type": "string", "description": "From gmail_search or the order's email."}}, "required": ["thread_id"]},
    tier=Tier.AMBER,
    issued_id_args=("thread_id",),
    write=WriteSpec(
        operation="gmail_thread_archive", entity_kind="thread", entity_arg="thread_id", mutation="gmail:labels",
        observe=_observe_inbox, execute=_execute_archive, present=_present_archive,
        reversible=True, undo=lambda execution: {"thread_id": execution["thread_id"], "add": ["INBOX"], "remove": []}, op_class="reversible",
        spoken_success="Archived.", spoken_undo_success="It's back in the inbox.",
        spoken_failure="I couldn't confirm the thread was archived.", spoken_stale="That thread isn't in the inbox any more.",
    ),
)
async def gmail_thread_archive(thread_id: str) -> Prepared:
    client = _g()
    labels = await asyncio.to_thread(client.thread_labels, str(thread_id))
    if "INBOX" not in labels:
        raise ToolError("That thread is not in the inbox.")
    messages = await asyncio.to_thread(client.thread_messages, str(thread_id))
    head = messages[-1]["headers"] if messages else {}
    name, email = parseaddr(head.get("from", ""))
    subject = head.get("subject", "")
    # The subject may carry a name; it stays on the card and never in the ledger's label.
    return Prepared(
        execution={"thread_id": str(thread_id), "add": [], "remove": ["INBOX"]},
        before={"inbox": True}, expected_after={"inbox": False}, entity_ref=str(thread_id), entity_label="thread",
        summary={"subject": subject, "from_line": f"{name} <{email}>" if name else email, "read_back": f"archive the thread {subject[:60]}".strip(), "pii": [v for v in (name, email, subject) if v], "ledger": {"kind": "archive"}},
    )


# [inbox, DEC-071] Registered with this module: the read that lists the drafts waiting in Gmail and says
# whose words each is (app/tools/gmail_drafts.py), and junk and a waiting draft sent as Gmail holds it
# (app/tools/gmail_inbox.py). Imported last: each reads this module's own parts.
from app.tools import gmail_drafts as _gmail_drafts  # noqa: E402, F401
from app.tools import gmail_inbox as _gmail_inbox  # noqa: E402, F401
