"""Two of the owner's rulings of 8 October (DEC-071) on the inbox, as staged email changes beside the
rest of them (app/tools/gmail_writes.py, whose parts these use):

- ruling 27, junk: a thread to Spam (Gmail's Report spam), singly here and for a set of threads on one
  card through the batch engine (app/tools/batch_tools.py batch_email_junk). A hold even for one
  thread, never a customer's, proven by reading its labels back; undo is Gmail's Not spam.
- ruling 34, a draft waiting in Gmail sent exactly as Gmail holds it, by George or by a member of the
  team on their own hold, its card saying whose words they are and who sends them.

Like everything in gmail_writes, nothing here reaches Gmail's write methods except through the action
engine's commit, and nothing a customer wrote is ever an instruction.
"""

from __future__ import annotations

import asyncio
from email.utils import getaddresses, parseaddr

from app.actions.models import Observed, Prepared
from app.tools import gmail_drafts
from app.tools.gate import Tier
from app.tools.gmail_writes import (
    _entity_email,
    _execute_archive,
    _execute_send,
    _first_name,
    _g,
    _new_email_held_to_the_orders_it_names,
    _observe_thread,
    _present_email,
    _replaces,
    _settle_send,
    _the_one_draft,
    _thread_fingerprint,
    _verify_sent,
    _with_replaces,
    thread_context,
)
from app.tools.registry import ToolError, WriteSpec, tool

# ------------------------------------------------------------------------- junk (ruling 27)
#
# George, 8 October (DEC-071, ruling 27): archive or junk many threads at once, on one card and one
# hold. Junk is Gmail's own "Report spam": the thread leaves the inbox for Spam, and Gmail learns from
# it — its sender's next email may land in Spam too, and Gmail empties Spam after 30 days. So it is a
# hold even for one thread (RED), and it is never done to a customer of the shop: a thread in which
# anyone who wrote (any inbound From) or any Reply-To has orders, or could not be checked against the
# shop, is refused here (and so left out of a batch, with that reason on the card). Undo is Gmail's
# "Not spam": back in the inbox.


async def _observe_junk(execution: dict) -> Observed:
    labels = await asyncio.to_thread(_g().thread_labels, str(execution["thread_id"]))
    return Observed(fingerprint={"inbox": "INBOX" in labels, "spam": "SPAM" in labels}, entity=None)


def _present_junk(proposal) -> dict:
    s = proposal.summary
    if proposal.undo_of:
        return {"title": "Not junk: back in the inbox", "summary": "", "detail": "", "confirm_label": "Tap to undo", "undone_title": "Back in the inbox"}
    return {
        "title": "Junk the thread", "summary": "",
        "detail": "Moves it to Spam. Gmail learns from it, so their next email may go to Spam too; Gmail empties Spam after 30 days. Undo puts it back.",
        "facts": [{"label": "Thread", "value": str(s.get("subject") or "")}, {"label": "From", "value": str(s.get("from_line") or "")}],
        "done_title": "Junked",
    }


async def junk_refusal(email: str) -> str:
    """Why a thread from this address is not junked from CLIVE, or "" when it may be: a customer of
    the shop never is, and nor is someone the shop could not be asked about (unknown is RED)."""
    from app.tools.gmail_tools import _known_customer

    if not email:
        return "That thread has no sender to judge, so it is not junked from here."
    known = await _known_customer(email)
    if known is None:
        return "That thread could not be checked against the shop's customers just now, so it is not junked."
    if known:
        return "That thread is from a customer of the shop, so it is not junked from here: archive it instead."
    return ""


def everyone_writing(inbound: list[dict], me: str) -> list[str]:
    """Every address in a thread that a junk would teach Gmail about: each inbound message's From
    and its Reply-To, not only the latest's. A contact form's mailer (mailer@shopify.com) writes the
    From and puts the customer in Reply-To, and a customer who wrote first is still in the thread
    when someone else wrote last (the review of 8 October, note 1)."""
    out: list[str] = []
    for m in inbound:
        for header in ("from", "reply-to"):
            for _name, address in getaddresses([str(m["headers"].get(header, "") or "")]):
                address = address.strip().lower()
                if address and address != me and address not in out:
                    out.append(address)
    return out


async def junk_refusal_for(addresses: list[str]) -> str:
    """Why a thread is not junked, or "" when it may be: refused when ANY sender or Reply-To in it is
    a customer of the shop, or could not be checked against the shop (unknown is RED)."""
    if not addresses:
        return await junk_refusal("")
    said = await asyncio.gather(*(junk_refusal(address) for address in addresses))
    return next((why for why in said if why), "")


@tool(
    name="gmail_thread_junk",
    description="Junk an email thread (Gmail's Report spam): it leaves the inbox for Spam. Never a customer's. Undo puts it back.",
    input_schema={"type": "object", "properties": {"thread_id": {"type": "string", "description": "From gmail_search."}}, "required": ["thread_id"]},
    tier=Tier.RED,
    issued_id_args=("thread_id",),
    write=WriteSpec(
        operation="gmail_thread_junk", entity_kind="thread", entity_arg="thread_id", mutation="gmail:labels",
        observe=_observe_junk, execute=_execute_archive, present=_present_junk,
        reversible=True, undo=lambda execution: {"thread_id": execution["thread_id"], "add": ["INBOX"], "remove": ["SPAM"]}, op_class="reversible",
        spoken_success="Junked.", spoken_undo_success="It's back in the inbox.",
        spoken_failure="I couldn't confirm the thread went to Spam.", spoken_stale="That thread isn't in the inbox any more.",
    ),
)
async def gmail_thread_junk(thread_id: str) -> Prepared:
    client = _g()
    labels = await asyncio.to_thread(client.thread_labels, str(thread_id))
    if "SPAM" in labels:
        raise ToolError("That thread is already in Spam.")
    if "INBOX" not in labels:
        raise ToolError("That thread is not in the inbox.")
    messages = await asyncio.to_thread(client.thread_messages, str(thread_id))
    me = str((await asyncio.to_thread(client.address)) or "").strip().lower()
    inbound = [m for m in messages if "SENT" not in m["labels"] and "DRAFT" not in m["labels"]]
    head = (inbound[-1] if inbound else messages[-1] if messages else {"headers": {}})["headers"]
    name, email = parseaddr(head.get("from", ""))
    email = email.strip().lower()
    if email and email == me:
        raise ToolError("That thread is our own mail, so it is not junked.")
    # Never a customer's: every sender and every Reply-To in the thread is checked, not the latest From.
    why = await junk_refusal_for(everyone_writing(inbound, me))
    if why:
        raise ToolError(why)
    subject = head.get("subject", "")
    return Prepared(
        execution={"thread_id": str(thread_id), "add": ["SPAM"], "remove": ["INBOX"]},
        before={"inbox": True, "spam": False}, expected_after={"inbox": False, "spam": True}, entity_ref=str(thread_id), entity_label="thread",
        summary={"subject": subject, "from_line": f"{name} <{email}>" if name else email, "read_back": f"junk the thread {subject[:60]}".strip(), "pii": [v for v in (name, email, subject) if v], "ledger": {"kind": "junk"}},
    )


# --------------------------------------------------------------- a draft as Gmail holds it (ruling 34)
#
# George, 8 October (DEC-071, ruling 34): a member of the team may send a draft he left, on their own
# hold. This sends the one draft waiting in a thread exactly as Gmail holds it — its words, its
# recipient, its subject; nothing in it is written or changed here — and its card says whose words
# they are and who sends them. It is the one email write a team member has beyond answering a
# thread themselves (app/people/staff.py), and it reaches only a draft that is George's (written in
# Gmail, or drafted with CLIVE on his hold) or the asker's own: a draft another team member drafted
# with CLIVE is theirs or George's to send. The engine records who held it (the confirming login);
# the work list records it as theirs (app/work/hooks.py).


@tool(
    name="gmail_send_draft",
    description="Send the one draft waiting in a thread exactly as Gmail holds it: its words and recipient, unchanged. thread_id from gmail_unsent.",
    input_schema={"type": "object", "properties": {"thread_id": {"type": "string", "description": "From gmail_unsent or gmail_search."}}, "required": ["thread_id"]},
    tier=Tier.RED,
    issued_id_args=("thread_id",),
    write=WriteSpec(
        operation="gmail_send_draft", entity_kind="email", entity_arg="thread_id", mutation="gmail:send",
        observe=_observe_thread, execute=_execute_send, present=_present_email, entity=_entity_email, verify=_verify_sent, settle=_settle_send,
        reversible=False, op_class="irreversible",
        spoken_success="Sent to {to}.",
        spoken_failure="I couldn't confirm the draft went. Check Sent in Gmail before sending again.",
        spoken_stale="That draft changed since this was prepared. Nothing was sent.",
    ),
)
async def gmail_send_draft(thread_id: str) -> Prepared:
    client = _g()
    ctx = await thread_context(str(thread_id))
    draft = await _the_one_draft(ctx, "in that thread")
    whose = gmail_drafts.whose_draft(draft, required=True)
    by, asker = whose["by"], whose["asker"]
    # The words that would leave name only orders whose customer they go to, as every email's do.
    await _new_email_held_to_the_orders_it_names(f"{draft['subject']}\n{draft['body']}", {"email": draft["to"]})
    sender = await asyncio.to_thread(client.address)
    execution = {
        "thread_id": str(thread_id), "token": draft["token"], "raw": "", "draft_id": draft["draft_id"], "to": draft["to"], "to_name": draft["to_name"],
        "subject": draft["subject"], "body": draft["body"], "state": "sent",
    }
    before = _thread_fingerprint(ctx, draft["token"])
    if before["sent"]:
        raise ToolError("That was already sent.")
    before["draft_sha"] = draft["sha"]
    reply = bool(ctx["has_inbound"])
    replaces = await _replaces(str(thread_id), execution) if reply else []
    if not reply:
        execution["replaces"] = []
    first = _first_name(draft["to_name"], draft["to"])
    words = whose["words_line"]
    prepared = Prepared(
        execution=execution, before=before, expected_after={**before, "drafts": 0, "sent": 1}, entity_ref=str(thread_id), entity_label="thread",
        summary={
            "title": "Send the draft", "sending": True, "reply": reply, "draft_used": True,
            "to_line": f"{draft['to_name']} <{draft['to']}>" if draft["to_name"] else draft["to"], "spoken_to": first,
            "subject": draft["subject"], "body": draft["body"], "from_line": sender,
            "words_line": words, "sender_line": whose["sender_line"],
            "read_back": f"send the draft waiting for {first}" + (f", {words.split(',')[0]} words" if not words.startswith("Yours") else ""),
            "pii": [v for v in (draft["to"], draft["to_name"], draft["subject"]) if v],
            "ledger": {
                "kind": "send_draft", "reply": reply, "draft_used": True, "chars": len(draft["body"]),
                "words": "gmail" if by == "" else ("owner" if by in ("owner", "clive") else "staff"),
                "sender": "owner" if asker == "owner" else "staff",
            },
        },
    )
    return _with_replaces(prepared, replaces)
