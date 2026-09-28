"""The email the assistant can prepare: a reply drafted or sent in a customer's thread, a
new email drafted or sent to an order's (or a customer's) address, a thread archived. Every
one is a staged change on the action engine — the card on the tablet IS the email, printed
whole, and a gesture on it is what sends. Nothing here reaches Gmail's write methods except
through the engine's commit.

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
# lenient one here would let "1232candlestickhorse at gmail" through as a recipient.
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
    """A reply named with an order goes to that order's customer, or it is not staged. The
    recipient is the address the reply would actually go to."""
    customer = await _order_customer(order_id)
    if not customer.get("email") or customer["email"] != ctx["to_email"]:
        who = f"{ctx['to_email'] or 'an unknown address'}"
        if ctx.get("reply_to") and ctx.get("from_email") == customer.get("email"):
            who = f"{ctx['reply_to']} (the message asks for replies there, not to the customer's own address)"
        raise ToolError(f"That reply would go to {who}, not the customer on order {customer.get('label') or order_id}. Nothing was prepared.")
    other = _another_of_theirs(ctx, customer, order_id)
    if other:
        # The right person, the wrong conversation: a thread she opened about another of her
        # orders is not this order's thread, and a reply filed there with this order's number
        # on its card would read to her as an answer about the parcel she asked after. The
        # deleted order→email family refused exactly this before arming a reply
        # (`order_email.about_this_order`); the model path keeps the refusal here, where every
        # reply the model or a tap prepares passes (the 2026-09-28 deploy review, round 9,
        # E-04 and I-02).
        label = str(customer.get("label") or order_id).lstrip("#")
        raise ToolError(
            f"That thread is about order {other}, not order {label}. Nothing was prepared. Write a new email about "
            f"order {label}, or reply in that thread without naming an order."
        )
    return customer


def _another_of_theirs(ctx: dict[str, Any], customer: dict[str, str], order_id: str) -> str:
    """Another order of THIS customer's that the thread's subject names, when the subject does
    not name this one; empty otherwise.

    Read from the order cache the Mac already holds, through the same graph the thread card's
    linked-order strip uses (`app/context/graph.py`), so a number counts only when it is an
    order whose customer is the person the reply goes to — a year or a tracking fragment in a
    subject is never an order. A cold cache names nothing, and the recipient check above still
    stands on its own.
    """
    from app.context import graph

    subject = str(ctx.get("subject") or "")
    named = graph.order_numbers_in(subject)
    this = str(customer.get("label") or "").rsplit("-", 1)[-1].lstrip("#").strip()
    if not named or (this and this in named):
        return ""
    try:
        from app.tools.analytics_tools import cache

        held = cache()
        rows = list(held.rows() or []) if held.status().get("synced_at") is not None else []
    except Exception:  # noqa: BLE001 — no cache bound (a Mac without Shopify, a unit test) is a cold cache
        return ""
    found = graph.linked_orders_for_thread({"subject": subject, "from_email": customer.get("email", "")}, rows=rows)
    for linked in found.get("linked") or []:
        digits = str(linked.get("order_number") or "").rsplit("-", 1)[-1].lstrip("#").strip()
        if digits in named and str(linked.get("order_id") or "") != str(order_id):
            return digits
    return ""


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
                    return
            elif (await _token_state(str(execution["token"]), str(execution.get("sent_message_id") or "")))["sent"]:
                return
        except (ToolError, GmailError) as exc:
            log.info("settle: %s", exc)
        await asyncio.sleep(SETTLE_POLL_S)


async def _settle_draft(execution: dict, created: dict) -> None:
    """Gmail lists a new draft a moment after answering the create. Wait for it, bounded, so
    the proving read looks at a thread that has it — rather than calling a draft that exists
    "not created". The ids Gmail handed back are kept for the proof.

    Nothing here can make an absent draft look present: if the poll never sees it, the proof
    runs on the same read it would have run on, and the change settles UNVERIFIED."""
    if created.get("message_id"):
        execution["drafted_message_id"] = str(created["message_id"])
    if created.get("draft_id"):
        execution["drafted_draft_id"] = str(created["draft_id"])
    if execution.get("delete"):
        return
    deadline = time.monotonic() + SETTLE_S
    while time.monotonic() < deadline:
        try:
            if execution.get("thread_id"):
                ctx = await thread_context(str(execution["thread_id"]))
                if _thread_fingerprint(ctx, str(execution["token"]), "", str(execution.get("drafted_message_id") or ""))["drafts"] == 1:
                    return
            elif (await _token_state(str(execution["token"]), "", str(execution.get("drafted_draft_id") or "")))["drafts"] == 1:
                return
        except (ToolError, GmailError) as exc:
            log.info("settle draft: %s", exc)
        await asyncio.sleep(SETTLE_POLL_S)


def _verify_drafted(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    return observed.get("drafts") == 1 and not observed.get("sent"), ""


def _verify_sent(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    return bool(observed.get("sent")), ""


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
    if sending:
        facts.append({"label": "From", "value": str(s.get("from_line") or "")})
    return {
        "title": str(s.get("title") or ("Send the email" if sending else "Save a draft")),
        "summary": "", "body": str(s.get("body") or ""), "facts": facts,
        "detail": "Sends now. It cannot be unsent." if sending else "Saved in Gmail drafts; nothing is sent until you say so.",
        "done_title": ("Reply sent" if s.get("in_reply_to") else "Email sent") if sending else "Draft saved",
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
    description=(
        "Save a reply in a customer's thread as a Gmail draft, addressed to the sender of the message "
        "it answers. Write it yourself, plainly. Nothing is sent."
    ),
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
    customer = await _check_order(order_id, ctx) if order_id else None
    text = clean_body(body)
    sender = await asyncio.to_thread(client.address)
    token = new_token(sender)
    subject = reply_subject(ctx["subject"])
    raw = build_raw(sender=sender, sender_name=str(getattr(_settings(), "gmail_from_name", "") or ""), to=ctx["to_email"], to_name=ctx["to_name"],
                    subject=subject, body=text, token=token, in_reply_to=ctx["in_reply_to"], references=ctx["references"])
    execution = {"thread_id": str(thread_id), "token": token, "raw": raw, "to": ctx["to_email"], "to_name": ctx["to_name"], "subject": subject, "body": text, "state": "draft"}
    before = _thread_fingerprint(ctx, token)
    return _prepared_email(execution=execution, before=before, expected_after={**before, "drafts": 1}, entity_ref=str(thread_id), ctx=ctx, customer=customer,
                           sending=False, title="Save a draft reply", sender=sender, kind="draft_reply")


@tool(
    name="gmail_send_reply",
    description=(
        "Send a reply in a customer's thread to the sender of the message it answers. Give the reply "
        "in your own plain words, or leave body empty to send the one draft waiting in that thread, "
        "exactly as Gmail holds it."
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
    before = _thread_fingerprint(ctx, execution["token"])
    if before["sent"]:
        raise ToolError("That was already sent.")
    if execution["draft_id"]:
        before["draft_sha"] = draft["sha"]
    return _prepared_email(execution=execution, before=before, expected_after={**before, "drafts": 0, "sent": 1}, entity_ref=str(thread_id), ctx=ctx, customer=customer,
                           sending=True, title="Send the reply", sender=sender, kind="send_reply")


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

    The bench refused "write an email to a model … their email is 1232candlestickhorse@
    gmail.com" because a recipient had to be a Shopify customer. It does not any more — but
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
        "Save a new email to an order's customer (or a customer with no visible order) as a Gmail "
        "draft; the address comes from Shopify. Write it yourself, plainly. Nothing is sent."
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
        "Send a new email to an order's customer (or a customer with no visible order); the address "
        "comes from Shopify. Give subject and body in your own plain words, or leave both empty to "
        "send the one draft waiting for that customer, as Gmail holds it."
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
