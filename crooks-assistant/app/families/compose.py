"""Writing an email to anybody, and the draft→send correction (brief §7, §8).

Two bench failures, one family.

    "Write an email to a model asking if they're free for a shoot next Sunday. Their email
     is 1232candlestickhorse@gmail.com. Don't send it yet."

was refused, because every recipient this build could reach was a Shopify customer. The
address the owner says out loud is the one recipient the shop cannot supply, and refusing it
is refusing the job — a shoot is booked with models, not with people who have bought a hoodie.

    "No, don't save a draft. You want it sent."

spent twenty-five seconds in Claude and failed. It is a correction, not a new instruction:
the draft is on the Mac already, with its recipient, its subject and its words decided, and
turning it into a send is arithmetic on state the Mac holds.

WHAT IS NEW HERE, AND WHAT IS NOT. The composer is a *context on the branch*
(`Branch.compose`), not a change. Opening it reads nothing and stages nothing; typing into it
posts `compose.field` — a compose id, a field NAME from a closed set, and the typed value —
and the Mac validates that into its own copy; only a gesture on Save draft or Send stages, and
staging calls the one registered write tool through the one action engine with the execution
arguments built from the Mac's copy. So the hybrid precision input of §7 changes nothing about
the write boundary: the tablet still never supplies an argument of a mutation, it supplies a
value the Mac decides what to do with. That distinction is the whole design, and the tests
hold it.

An arbitrary address is admitted by `gmail_draft_new`/`gmail_send_new` only alongside the
`compose_id` of a composer this conversation was handed, which the gate checks against
`session.issued_ids` like any other id — so an address can only be staged from a composer
whose card the owner has already read. The address itself could never carry that check: an
address is not a well-formed id (`gate._ID_SHAPE` has no "@").

And the address has to be one the owner has CHECKED. An address the model writes into a
composer is its transcription of what the owner said, so it arrives `uncertain` however cleanly
it reads (`check_said_address`), and both the tap (`_ready_to_stage`) and the write tools
themselves (`owner_checked`, asked by `gmail_writes._recipient`) refuse it until his finger has
been on the field. An address read off a record — a thread's sender, an order's or a customer's
email — is `ok` from the start, because the shop or the mailbox served it.

SAID OUT LOUD, IT IS THE MODEL'S. "Write an email to 1232candlestickhorse@gmail.com asking if
they're free on Sunday" and "no, send it instead" are model turns like every other sentence:
Claude opens the composer with `gmail_compose_open`, writes into it with `gmail_compose_fill`,
and the gesture on the card is still the owner's. The commands below are the touch path —
Reply and Email on a card, typing into a field, Save draft and Send.
"""

from __future__ import annotations

import logging
import os
import re
import time
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.capabilities.families import CapabilityFamily
from app.capabilities.families import register as register_capability
from app.commands import Command, Outcome
from app.commands import Ctx as CommandCtx
from app.commands import register as register_command
from app.surfaces import Surface
from app.tools.gate import Tier
from app.tools.gmail_writes import (
    EMAIL_ADDRESS,
    MAX_ADDRESS_CHARS,
    MAX_BODY_CHARS,
    MAX_SUBJECT_CHARS,
)
from app.tools.registry import ToolError, tool

log = logging.getLogger("crooks.families.compose")

# The shop's clock. Every relative date the owner speaks is his own working week, and the
# fixture world is stamped in this zone too (experience/fixtures/data.py) — a date resolved in
# UTC is the wrong day for the hour either side of midnight, which is a bug that passes all
# day and fails at eleven at night.
SHOP_TZ = ZoneInfo("Europe/London")

# How long a composer stands. Long enough to dictate, read it back, correct an address and
# think about it; short enough that a composer left open this morning cannot be what "send
# it" means this afternoon.
COMPOSE_TTL_S = 1800.0
# How far back "send it instead" will look for the draft it converts. A draft proposed
# seconds ago is what "it" means; one from ten minutes ago is not, and guessing would send an
# email the owner had moved on from.
CONVERT_WINDOW_S = 300.0
MAX_ABOUT_CHARS = 200
PLACEHOLDER_SUBJECT = "the assistant is writing this"

# What may be typed into the composer, and nothing else. A field name outside this set is
# refused: the tablet must not be able to name a key of the Mac's own context.
FIELDS = ("to", "to_name", "subject", "body")
# And which of them a REPLY will accept. A reply's recipient and subject belong to the thread
# — `gmail_draft_reply` re-reads both there — so the card shows them and will not take a
# keystroke for either. The card says so (`editable: False`) and this enforces it, because a
# closed set is only closed if the Mac closes it.
REPLY_FIELDS = ("body",)
# The one line the composer says about itself. D-9: the owner asked "how do I type a separate
# hall for you?" over a build whose only typing surface was this card, and nothing on it, or
# anywhere else, said that a field could be tapped. Two lines, because an empty box and a
# written one need different instructions — and the second is where "rewrite" lives, which
# was reachable only by knowing the sentence.
HOW_TO_WRITE = "Tap the box to type, or hold the dock and say it."
HOW_TO_CHANGE = "Tap the box to edit it, or hold the dock and say how to change it."


def how_to_write(compose: dict[str, Any]) -> str:
    return HOW_TO_CHANGE if str(compose.get("body") or "").strip() else HOW_TO_WRITE


def _now() -> float:
    return time.time()


# --------------------------------------------------------------------------- the address


# Lead-in words a dictated address arrives wrapped in: "their email is 1232 candlestick horse
# at gmail dot com". "at" is deliberately absent — it is the @.
_LEAD_IN = frozenset({
    "their", "her", "his", "its", "it's", "the", "email", "e-mail", "mail", "address",
    "is", "to", "and", "on", "an", "a", "send", "write", "compose", "it", "this",
})
_DICTATED = re.compile(r"\s+(?:at|@)\s+|\s+dot\s+|\s+underscore\s+|\s+dash\s+|\s+hyphen\s+", re.I)


def looks_dictated(value: str) -> bool:
    """Whether this reads as an address a microphone heard rather than one a finger typed."""
    return bool(_DICTATED.search(f" {str(value or '').strip()} "))


def normalise_address(said: str) -> str:
    """A spoken address as characters: "1232 candlestick horse at gmail dot com" →
    "1232candlestickhorse@gmail.com".

    Word by word rather than by substitution, because the pieces of a local part arrive as
    separate words and every space inside an address is a space the speaker did not mean. The
    lead-in ("their email is") is dropped from the FRONT only: a word that is filler in front
    of the address is part of the address anywhere inside it.
    """
    words = [w for w in re.split(r"\s+", str(said or "").strip().lower()) if w]
    while words and words[0] in _LEAD_IN:
        words.pop(0)
    swap = {"at": "@", "@": "@", "dot": ".", "underscore": "_", "dash": "-", "hyphen": "-"}
    return "".join(swap.get(word, word) for word in words)[:MAX_ADDRESS_CHARS]


def check_address(said: str) -> tuple[str, str, str]:
    """(value, status, hint) for an address as it was given.

    Three statuses, and they mean three different things to the owner:

        ok          it is an address, typed or written cleanly, and it may be staged
        uncertain   it was DICTATED. It is normalised and shown, and the owner is asked to
                    look at it — because a microphone that hears "candlestick" as "candle
                    stick" produces a perfectly valid address belonging to somebody else,
                    and no check on this side of the wire can tell the difference.
        invalid     it is not an address at all

    A dictated address is never `ok`, even when it validates. That is the point:
    `compose.stage` refuses anything but `ok`, so the correction is a tap on the field rather
    than an email to a stranger.
    """
    raw = " ".join(str(said or "").split())
    if not raw:
        return "", "invalid", "no address yet"
    if looks_dictated(raw):
        value = normalise_address(raw)
        if not EMAIL_ADDRESS.match(value):
            return value, "invalid", "I could not make an address out of that — type it in"
        return value, "uncertain", "heard, not typed — check it before this goes anywhere"
    value = raw.lower()[:MAX_ADDRESS_CHARS]
    if not EMAIL_ADDRESS.match(value):
        return value, "invalid", "that is not an email address"
    return value, "ok", ""


# What the card says under an address the MODEL wrote into the composer in canonical form. It
# came from what the owner said — out loud or typed into a sentence, and the Mac cannot tell
# which — by way of the model, and neither step is a check: a recogniser that heard
# "candlestick" as "candle stick" and a model that tidied it produce a perfectly valid address
# belonging to somebody else.
FROM_WORDS_HINT = "written from what you said, not typed here — check it before this goes anywhere"


def check_said_address(said: str) -> tuple[str, str, str]:
    """(value, status, hint) for an address the model supplied, which is never `ok`.

    `check_address` answers for characters a finger typed into the box, where an address that
    reads cleanly is the owner's own. An address the model hands over is a different thing: the
    owner said it, the model wrote it down, and nothing on this side of the wire can tell a
    clean transcription from a clean mistake. The deleted spoken composer ran its address
    through `looks_dictated` and marked it `uncertain`; the model normalises the words before
    this sees them, so the dictation shape is gone and that test alone would pass a mis-heard
    address as typed (the 2026-09-28 deploy review, round 9, E-02). So every address that
    arrives this way is `uncertain` until the owner puts a finger on it (`compose.field`), and
    `_ready_to_stage` — and the write tool, `gmail_writes._recipient` — refuse it until then.
    """
    value, status, hint = check_address(said)
    if status == "ok":
        return value, "uncertain", FROM_WORDS_HINT
    return value, status, hint


# --------------------------------------------------------------------------- the date

_WEEKDAYS = {
    "monday": 0, "mondays": 0, "tuesday": 1, "tuesdays": 1, "wednesday": 2, "wednesdays": 2,
    "thursday": 3, "thursdays": 3, "friday": 4, "fridays": 4, "saturday": 5, "saturdays": 5,
    "sunday": 6, "sundays": 6,
}
_WHEN = re.compile(
    r"\b(?:(?:on|next|this|coming)\s+)?(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\b"
    r"|\b(today|tomorrow|tonight)\b"
    r"|\b(next|this)\s+(week|weekend|month)\b",
    re.I,
)


def resolve_when(text: str, *, now: datetime | None = None) -> dict[str, str]:
    """The first relative date in the words, as a date and as the owner said it.

    One rule, written down here rather than guessed at each call site: **a named weekday is
    the soonest one strictly after today.** "Next Sunday" and "on Sunday" resolve the same,
    because on a workbench they mean the same thing and pretending to tell them apart would
    be a guess printed as a fact. Today's own weekday therefore means a week away, which is
    what "next Sunday" said on a Sunday means.

    Empty when the words name no date, and the composer then says nothing about a date. That
    is the failure that matters: an email proposing a day the owner never said.
    """
    moment = now or datetime.now(SHOP_TZ)
    today = moment.date()
    found = _WHEN.search(str(text or ""))
    if not found:
        return {}
    phrase = " ".join(found.group(0).split()).lower()
    weekday, plain, relative, unit = found.group(1), found.group(2), found.group(3), found.group(4)
    if weekday:
        ahead = (_WEEKDAYS[weekday.lower()] - today.weekday()) % 7
        when = today + timedelta(days=ahead or 7)
    elif plain:
        when = today + timedelta(days=1) if plain.lower() == "tomorrow" else today
    elif unit.lower() == "weekend":
        ahead = (5 - today.weekday()) % 7                      # the coming Saturday
        when = today + timedelta(days=ahead or 7)
    elif unit.lower() == "month":
        when = today + timedelta(days=30)
    else:
        when = today + timedelta(days=7 if relative.lower() == "next" else 0)
    return {"date": when.isoformat(), "phrase": phrase}


# --------------------------------------------------------------------------- the context


def new_compose_id() -> str:
    return f"cmp_{os.urandom(5).hex()}"


def open_compose(
    branch: Any,
    *,
    kind: str = "new",
    to: str = "",
    to_name: str = "",
    subject: str = "",
    body: str = "",
    thread_id: str = "",
    about: str = "",
    origin_text: str = "",
    resolved_when: dict[str, str] | None = None,
    to_from_words: bool = False,
) -> str:
    """Start a composer on this half and return its id. Reads nothing; stages nothing.

    The context this creates is the ONLY place the recipient, subject and body live until a
    gesture asks for them. That is what makes a typed value on the tablet safe: it is an
    input to this dictionary, not an argument to a mutation.

    `to_from_words` says the address came from the owner's words by way of the model rather
    than from a record or a keyboard, and it is then marked for him to check whatever shape it
    arrives in (`check_said_address`).
    """
    value, status, hint = (check_said_address if to_from_words else check_address)(to)
    compose: dict[str, Any] = {
        "compose_id": new_compose_id(),
        "kind": "reply" if kind == "reply" else "new",
        "to": value, "to_status": status, "to_hint": hint,
        "to_name": " ".join(str(to_name or "").split())[:80],
        "subject": " ".join(str(subject or "").split())[:MAX_SUBJECT_CHARS],
        "subject_status": "ok" if str(subject or "").strip() else "uncertain",
        "body": str(body or "").replace("\r\n", "\n")[:MAX_BODY_CHARS],
        "body_status": "ok" if str(body or "").strip() else "uncertain",
        "thread_id": str(thread_id or "")[:120],
        "about": " ".join(str(about or "").split())[:MAX_ABOUT_CHARS],
        "original": " ".join(str(origin_text or "").split())[:MAX_ABOUT_CHARS],
        "resolved_when": dict(resolved_when or {}),
        "converts": "",
        "at": _now(),
    }
    branch.compose = compose
    return str(compose["compose_id"])


def held(branch: Any, compose_id: str = "") -> dict[str, Any] | None:
    """This half's composer, when it is the one named and it has not gone stale.

    Both checks matter. The id, because a composer belongs to the half it was started on and
    a tap posted from a screen that has moved on must not reach the other half's. The clock,
    because the execution arguments are built from this dictionary, and an address that has
    been sitting on the Mac since this morning is not what the owner is looking at.
    """
    compose = getattr(branch, "compose", None)
    if not isinstance(compose, dict) or not compose.get("compose_id"):
        return None
    if compose_id and str(compose_id) != str(compose["compose_id"]):
        return None
    if _now() - float(compose.get("at") or 0) > COMPOSE_TTL_S:
        branch.compose = None
        return None
    return compose


def _composer_anywhere(session: Any, compose_id: str) -> dict[str, Any] | None:
    """The composer with this id on any half of this conversation, while it stands.

    Any half rather than the acting one, because the write tool can be called on a turn
    spoken to either half and the composer is where it was opened; a stale or discarded one is
    not found, which is the point — the address the owner checked has to be on a card he can
    still see.
    """
    for branch in list((getattr(session, "branches", None) or {}).values()):
        found = held(branch, compose_id)
        if found is not None:
            return found
    return None


def owner_checked(compose_id: str, address: str) -> str:
    """Why this address may NOT be prepared from this composer, in words; empty when it may.

    The last word on an arbitrary recipient, asked by the write tools themselves
    (`app/tools/gmail_writes.py::_recipient`) — not only by the tap on Save draft or Send.
    The model can call `gmail_draft_new`/`gmail_send_new` with a `compose_id` directly, and
    before this the address it passed beside that id was taken as it came, whatever the card
    said about it (the 2026-09-28 deploy review, round 9, E-02). Three things must hold: the
    composer is still open on this conversation, the address is the one on its card, and the
    card says the owner has checked it — typed it, or had it put there from a record the shop
    or the mailbox served.
    """
    from app.tools.context import CURRENT_SESSION

    session = CURRENT_SESSION.get()
    compose = _composer_anywhere(session, str(compose_id or "")) if session is not None else None
    if compose is None:
        return "That email is no longer open on the screen, so there is no checked address to send to. Open it again."
    if compose.get("kind") != "new":
        return "That composer is a reply; a reply goes back into its own thread."
    if str(compose.get("to") or "").strip().lower() != " ".join(str(address or "").split()).lower():
        return "That is not the address on the email the owner is looking at. The address on the card is the one he checks."
    if compose.get("to_status") != "ok":
        return ("The owner has not checked that address yet: it came from what he said, not from his typing or "
                "a record. Ask him to tap the address on the card and check it; nothing was prepared.")
    return ""


def _thread_sender(thread_id: str) -> dict[str, str] | None:
    """Who a reply in a thread the Mac holds goes to (`_reply_recipient`), or None.

    Read off the entity cache only — the thread this conversation was shown — never fetched:
    opening a composer reads nothing. A miss is not an error; the card then says who decides.
    """
    from app.memory import ENTITY
    from app.memory import current as memory

    if not thread_id:
        return None
    entry = memory().get(ENTITY, f"email_thread:{thread_id}", allow_stale=True)
    thread = getattr(entry, "value", None) if entry is not None else None
    if not isinstance(thread, dict):
        return None
    return _reply_recipient(_last_inbound(thread))


# --------------------------------------------------------------------------- where a reply goes
#
# Round 13 (the round-12 deploy review, S2b-01). A message can ask for replies somewhere other
# than its sender, with a Reply-To header: a storefront contact form does it honestly, and a
# spoofed message does it to take the answer. The write tools have always answered the Reply-To
# (`gmail_writes.thread_context`); the reply composer showed the From, marked checked, and only the
# final hold card named where the reply was really going. Now the composer decides the recipient
# as the tool does, shows both addresses when they differ, and will not prepare anything until the
# owner has confirmed the Reply-To on the card. The tools hold the same line (`reply_as_shown`):
# a reply goes only to the address the card on the screen shows.

CONFIRM_TO_LABEL = "Yes, reply to this address"


def _reply_recipient(message: dict[str, Any]) -> dict[str, str] | None:
    """Who a reply to this message goes to, decided as the write tool decides it: the address its
    Reply-To names, when the thread read says it names one other than its sender, and otherwise
    its From. {"to", "to_name", "sender"}; None when that is not an address."""
    sender = str(message.get("from_email") or "").strip().lower()
    asked = message.get("reply_to") if isinstance(message.get("reply_to"), dict) else {}
    reply_to = str(asked.get("email") or "").strip().lower()
    if reply_to and "@" in reply_to:
        to, name = reply_to, str(asked.get("name") or "")
    else:
        to, name = sender, str(message.get("from") or "")
    if not to or not EMAIL_ADDRESS.match(to):
        return None
    return {"to": to, "to_name": " ".join(name.split())[:80], "sender": sender}


def _show_recipient(compose: dict[str, Any], recipient: dict[str, str]) -> None:
    """The recipient on a reply composer: read off a record Gmail served, so `ok` — unless it is
    a Reply-To that is not the sender, when the card shows both and waits for the owner to
    confirm it (`compose.confirm_to`)."""
    compose.update({"to": recipient["to"], "to_name": recipient["to_name"] or compose.get("to_name", ""),
                    "sender": recipient["sender"], "confirmed_to": ""})
    if _elsewhere(compose):
        compose.update({"to_status": "uncertain",
                        "to_hint": f"sent by {recipient['sender']}, asking for replies here — confirm it below"})
    else:
        compose.update({"to_status": "ok", "to_hint": ""})


def _elsewhere(compose: dict[str, Any]) -> bool:
    """Whether this reply goes somewhere other than the sender of the message it answers."""
    sender = str(compose.get("sender") or "").strip().lower()
    return compose.get("kind") == "reply" and bool(sender) and sender != str(compose.get("to") or "").strip().lower()


def _awaiting_confirmation(compose: dict[str, Any]) -> bool:
    return _elsewhere(compose) and str(compose.get("confirmed_to") or "") != str(compose.get("to") or "")


def _composers(session: Any) -> list[dict[str, Any]]:
    """Every composer still open on this conversation, the acting half's first."""
    from app.tools.context import acting_branch

    branches = dict(getattr(session, "branches", None) or {})
    first = acting_branch(session)
    order = sorted(branches, key=lambda ident: ident != first)
    return [found for found in (held(branches[ident]) for ident in order) if found is not None]


def reply_as_shown(thread_id: str, ctx: dict[str, Any]) -> tuple[str, str]:
    """(the composer a reply in this thread is prepared from, why it may not be), asked by the
    reply tools themselves (`app/tools/gmail_writes.py`) with the thread as Gmail holds it now.

    When a reply composer for the thread is open on the owner's screen, the reply goes to the
    address its card shows or it is not prepared — and when that address is a Reply-To that is
    not the sender, only once he has confirmed it there. With no composer for the thread there is
    no card to hold it to, and the final hold card names the recipient as it always has."""
    from app.tools.context import CURRENT_SESSION

    session = CURRENT_SESSION.get()
    if session is None:
        return "", ""
    mine = [c for c in _composers(session)
            if c.get("kind") == "reply" and str(c.get("thread_id") or "") == str(thread_id or "")]
    if not mine:
        return "", ""
    to = str(ctx.get("to_email") or "").strip().lower()
    sender = str(ctx.get("from_email") or "").strip().lower()
    for compose in mine:
        shown = str(compose.get("to") or "").strip().lower()
        if shown != to:
            where = " (where its last message asks replies to go)" if to != sender else ""
            return str(compose["compose_id"]), (
                f"That reply would go to {to or 'nobody'}{where}, not {shown or 'the address'} as the reply on the "
                "owner's screen shows. Nothing was prepared. Read the thread again and open the reply from it, so "
                "the card shows who it goes to.")
        if to != sender and str(compose.get("confirmed_to") or "") != to:
            return str(compose["compose_id"]), (
                f"The last message in that thread was sent by {sender} and asks for replies to go to {to}. The owner "
                f"has not confirmed that address on the reply card, so nothing was prepared; he taps "
                f"“{CONFIRM_TO_LABEL}” there first.")
    return str(mine[0]["compose_id"]), ""


# --------------------------------------------------------------------------- what was prepared from it
#
# Round 13 (the round-12 deploy review, S2b-03). Send on the composer prepares a hold card that
# carries the email as it read at that moment. An edit afterwards changed the composer and not the
# hold card, so holding it sent the old words to the old address. Now an edit that changes what
# would be sent withdraws every change still waiting that was prepared from the composer — by his
# tap or by the model, a send or a draft — and a Send being prepared while an edit lands is
# withdrawn as it arrives (`moved_since`, asked by `POST /command`).

EDITED = "The email changed on the screen, so what was prepared from it before was withdrawn."


def revision(compose: dict[str, Any]) -> str:
    """What a gesture on this composer would send, as one short digest: where, to whom, under
    which subject, and the words."""
    import hashlib
    import json

    what = [compose.get(k) for k in ("kind", "thread_id", "to", "to_name", "subject", "body")]
    return hashlib.sha256(json.dumps(what, default=str).encode()).hexdigest()[:16]


def withdraw_prepared(session: Any, compose: dict[str, Any], words: str = EDITED) -> list[str]:
    """Withdraw every email change still waiting that was prepared from this composer: one named
    by its id (a new email, or a reply that carries it), and any reply waiting in its thread.
    Returns the ids, for the tablet to settle."""
    from collections.abc import Mapping

    ident = str(compose.get("compose_id") or "")
    thread = str(compose.get("thread_id") or "")
    ids = []
    for proposal in list(getattr(session, "proposals", None) or []):
        operation = str(getattr(proposal, "operation", "") or "")
        if (getattr(getattr(proposal, "status", None), "value", "") != "PENDING" or getattr(proposal, "undo_of", None)
                or not operation.startswith(("gmail_draft_", "gmail_send_"))):
            continue
        execution = getattr(proposal, "execution", None)
        execution = execution if isinstance(execution, Mapping) else {}
        if (str(getattr(proposal, "entity_ref", "") or "") == ident or str(execution.get("compose_id") or "") == ident
                or (compose.get("kind") == "reply" and thread and operation.endswith("_reply")
                    and str(execution.get("thread_id") or "") == thread)):
            ids.append(str(proposal.proposal_id))
    if ids:
        from app.actions.engine import current

        current().revoke_ids(ids, words)
    return ids


def moved_since(session: Any, staging: dict[str, Any]) -> str:
    """Why a change a tap on the composer has just prepared is not the email on the screen any
    more — it was edited, or closed, while the change was being prepared — or "" when it still is."""
    ident = str(staging.get("compose_id") or "")
    if not ident:
        return ""
    compose = _composer_anywhere(session, ident)
    if compose is None:
        return "The email was closed while it was being prepared, so nothing is waiting to be sent."
    if revision(compose) != str(staging.get("revision") or ""):
        return "The email changed while it was being prepared, so nothing is waiting to be sent. Tap it again."
    return ""


ACTIONS: tuple[dict[str, Any], ...] = (
    {"id": "save_draft", "label": "Save draft", "mode": "stage"},
    {"id": "send", "label": "Send", "mode": "stage", "risk": "red"},
    {"id": "discard", "label": "Discard"},
)


def editable_fields(compose: dict[str, Any]) -> tuple[str, ...]:
    """Which fields of THIS composer a keystroke may reach."""
    return REPLY_FIELDS if compose.get("kind") == "reply" else FIELDS


def compose_actions(compose: dict[str, Any]) -> list[dict[str, Any]]:
    """The buttons on this composer, with the command each one posts.

    Every button carries a command NAME and its own arguments, built here — so the card has
    one shape whatever is on it and the tablet decides nothing (web/ui.js:renderEmailCompose).
    A reply gets one more than a new email: **Dictate**, which binds `email.reply` to this
    thread so the next sentence is the reply. Typing and dictating are then two visible
    controls on one card, which is what §20 asks for and what the live session had neither of.
    """
    ident = str(compose["compose_id"])
    out: list[dict[str, Any]] = []
    thread_id = str(compose.get("thread_id") or "")
    if _awaiting_confirmation(compose):
        # The one thing standing between this reply and Send: the owner saying the Reply-To
        # on the card is where it should go (`_compose_confirm_to`).
        out.append({"id": "confirm_to", "label": CONFIRM_TO_LABEL, "command": "compose.confirm_to",
                    "args": f"compose_id={ident}"})
    if compose.get("kind") == "reply" and thread_id:
        out.append({
            "id": "dictate", "label": "Dictate", "mode": "arm", "command": "voice.bind",
            "args": f"family=email.reply&kind=email_thread&ref={thread_id}",
        })
    for action in ACTIONS:
        entry = dict(action)
        if entry["id"] == "discard":
            entry.update({"label": "Cancel", "command": "compose.discard", "args": f"compose_id={ident}"})
        else:
            mode = "send" if entry["id"] == "send" else "draft"
            entry.update({"command": "compose.stage", "args": f"compose_id={ident}&mode={mode}"})
        out.append(entry)
    return out


def compose_surface(compose: dict[str, Any]) -> Surface:
    """The composer as a card. Every value copied key by key and bounded, which is
    `app/presentation.py`'s rule kept here because this card is built outside it.

    `editable` on each field is the Mac saying which boxes have a keyboard. It is not advice:
    `compose.field` refuses a field this says is fixed, so the card and the wire agree.
    """
    typable = editable_fields(compose)
    return Surface(
        surface_type="email_compose",
        ui_type="email_compose",
        title="Reply" if compose["kind"] == "reply" else "New email",
        data={
            "compose_id": str(compose["compose_id"]),
            "kind": str(compose["kind"]),
            "to": {"value": str(compose.get("to") or ""),
                   "status": str(compose.get("to_status") or "invalid"),
                   "hint": str(compose.get("to_hint") or "")[:120],
                   "editable": "to" in typable},
            "to_name": str(compose.get("to_name") or "")[:80],
            "subject": {"value": str(compose.get("subject") or "")[:MAX_SUBJECT_CHARS],
                        "status": str(compose.get("subject_status") or "uncertain"),
                        "placeholder": PLACEHOLDER_SUBJECT,
                        "editable": "subject" in typable},
            "body": {"value": str(compose.get("body") or "")[:MAX_BODY_CHARS],
                     "status": str(compose.get("body_status") or "uncertain"),
                     "placeholder": PLACEHOLDER_SUBJECT,
                     "editable": "body" in typable},
            "thread_id": str(compose.get("thread_id") or "")[:120],
            "about": str(compose.get("about") or "")[:MAX_ABOUT_CHARS],
            "resolved_when": (dict(compose.get("resolved_when") or {}) or None),
            "original": str(compose.get("original") or "")[:MAX_ABOUT_CHARS],
            "how": how_to_write(compose),
            "actions": compose_actions(compose),
        },
        spoken_summary="Nothing is saved or sent until you tap.",
    )


def _spoken(compose: dict[str, Any]) -> str:
    who = compose.get("to") or "nobody yet"
    line = f"Writing to {who}" if compose["kind"] == "new" else f"Replying to {who}"
    when = (compose.get("resolved_when") or {}).get("date") or ""
    if when:
        line += f", about {when}"
    if _awaiting_confirmation(compose):
        return (f"{line}. The message came from {compose.get('sender')} and asks for replies to go to this "
                "address instead — confirm it on the card. Nothing is saved or sent.")
    if compose.get("to_status") == "uncertain":
        return f"{line}. That address is from what you said, not typed — check it. Nothing is saved or sent."
    return f"{line}. Nothing is saved or sent until you tap."


# --------------------------------------------------------------------------- the read tools


def _session_and_branch() -> tuple[Any, Any]:
    from app.tools.context import CURRENT_SESSION, acting_branch

    session = CURRENT_SESSION.get()
    if session is None:
        raise ToolError("There is no conversation to compose in.")
    return session, session.branch(acting_branch(session))


@tool(
    name="gmail_compose_open",
    description=(
        "Put an email to an address the owner gave (a model, a supplier, a venue — not a Shopify "
        "customer) on their screen as editable fields, and return its compose_id. Stages nothing "
        "and sends nothing. For a customer's own address use gmail_draft_new or gmail_send_new."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string", "maxLength": MAX_ADDRESS_CHARS, "description": "The address, as the owner gave it."},
            "subject": {"type": "string", "maxLength": MAX_SUBJECT_CHARS, "description": "One plain line."},
            "body": {"type": "string", "maxLength": MAX_BODY_CHARS, "description": "The email, plainly."},
            "to_name": {"type": "string", "maxLength": 80, "description": "Their name, if said."},
            "about": {"type": "string", "maxLength": MAX_ABOUT_CHARS, "description": "What it is about, in the owner's words."},
            "thread_id": {"type": "string", "description": "Only for a reply in a thread already read."},
        },
        "required": ["to", "subject", "body"],
    },
    tier=Tier.GREEN,
    issued_id_args=("thread_id",),
)
async def gmail_compose_open(to: str, subject: str, body: str, to_name: str = "", about: str = "", thread_id: str = "") -> dict[str, Any]:
    """The composer, opened by the model. A read tool because it reads and changes nothing
    outside the Mac: the branch gets a context, the session is issued its id, the card goes
    up. That id is what lets `gmail_draft_new`/`gmail_send_new` accept an address at all
    (`app/tools/gmail_writes.py::_recipient`), and the gate holds it to this conversation."""
    session, branch = _session_and_branch()
    compose_id = open_compose(
        branch, kind="reply" if thread_id else "new", to=to, to_name=to_name, subject=subject,
        body=body, thread_id=thread_id, about=about or subject, origin_text=about or subject,
        resolved_when=resolve_when(f"{about} {subject} {body}"),
        # The address is the model's transcription of the owner's words, never a checked one.
        to_from_words=True,
    )
    compose = held(branch, compose_id) or {}
    if compose.get("to_status") == "invalid":
        branch.compose = None
        raise ToolError(f"{str(to)[:80]!r} is not an address I can send to, so no composer was opened.")
    if compose.get("kind") == "reply":
        # A reply's recipient is not the model's to give: the write tool re-reads the thread
        # and answers whoever wrote last there, at the address they asked for. When the Mac
        # holds that thread, the card shows that address — read off a record Gmail served, so
        # `ok`, or waiting for the owner to confirm a Reply-To that is not the sender
        # (`_show_recipient`). When it does not, the card shows the address the model gave and
        # says so, and the write tool prepares the reply only if the thread's own recipient is
        # that address (`reply_as_shown`).
        recipient = _thread_sender(thread_id)
        if recipient:
            _show_recipient(compose, recipient)
        else:
            compose["to_hint"] = ("the reply goes to whoever wrote last in the thread; it is prepared only if that "
                                  "is this address")
    # The id becomes an id this conversation has been handed, which is the whole permission
    # story for the address behind it. The address is remembered as personal data so the turn
    # log scrubs it.
    session.issue(compose_id)
    session.remember_pii(*[v for v in (compose.get("to"), compose.get("to_name"), compose.get("sender")) if v])
    return {
        "compose_id": compose_id, "kind": compose.get("kind"), "to": compose.get("to"),
        "to_status": compose.get("to_status"), "to_hint": compose.get("to_hint"),
        "subject": compose.get("subject"), "body": compose.get("body"),
        "resolved_when": dict(compose.get("resolved_when") or {}),
        "_surfaces": [compose_surface(compose).as_ui()],
        "staged": False,
        "note": "The composer is on the owner's screen. Nothing is saved or sent; the owner's gesture on Save draft or Send does that.",
    }


@tool(
    name="gmail_compose_fill",
    description=(
        "Write the subject and body into an open composer. Nothing is saved or sent; this only "
        "changes what the owner is reading."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "compose_id": {"type": "string", "description": "From gmail_compose_open."},
            "subject": {"type": "string", "maxLength": MAX_SUBJECT_CHARS, "description": "One plain line."},
            "body": {"type": "string", "maxLength": MAX_BODY_CHARS, "description": "The email, plainly."},
        },
        "required": ["compose_id", "subject", "body"],
    },
    tier=Tier.GREEN,
    issued_id_args=("compose_id",),
)
async def gmail_compose_fill(compose_id: str, subject: str, body: str) -> dict[str, Any]:
    """The words, into the Mac's own copy. The recipient is not touched: the model may write
    the email and may not change who it goes to."""
    session, branch = _session_and_branch()
    compose = held(branch, compose_id)
    if compose is None:
        raise ToolError("That composer is closed. Open one with gmail_compose_open.")
    line = " ".join(str(subject or "").split())[:MAX_SUBJECT_CHARS]
    text = str(body or "").replace("\r\n", "\n")[:MAX_BODY_CHARS]
    if not line or not text.strip():
        raise ToolError("A composer needs both a subject and a body.")
    before = revision(compose)
    compose.update({"subject": line, "subject_status": "ok", "body": text, "body_status": "ok", "at": _now()})
    # Rewritten: what was prepared from the words before is not this email (round 13, S2b-03).
    withdrawn = withdraw_prepared(session, compose) if revision(compose) != before else []
    return {
        "compose_id": str(compose["compose_id"]), "subject": line, "body": text,
        "_surfaces": [compose_surface(compose).as_ui()], "staged": False,
        **({"withdrawn": withdrawn} if withdrawn else {}),
        "note": "On screen. Save draft or Send is the owner's gesture, not yours.",
    }


# --------------------------------------------------------------------------- the drafts


def _latest_draft(session: Any, branch: Any) -> Any:
    """The most recent email DRAFT this half prepared, recently enough to be what "it" means.
    Pending, verified, or revoked.

    REVOKED is in the list on purpose: `POST /turn` advances the epoch and withdraws this
    half's pending cards for every new sentence (app/routes/turn.py), so a draft the owner said
    something over is REVOKED by the time he asks for it as a send. VERIFIED is in the list
    because the draft may really be sitting in Gmail by now.
    """
    from app.actions.models import ActionStatus

    # Order matters: a draft still waiting for a tap is what "it" means, and one already
    # withdrawn is only a fallback. Without the ranking, converting a draft twice would find
    # the withdrawn one first and prepare a second send of the same email.
    usable = (ActionStatus.PENDING, ActionStatus.VERIFIED, ActionStatus.REVOKED)
    return _latest(session, branch, lambda op: op.startswith("gmail_draft_"), usable)


def _latest_send(session: Any, branch: Any) -> Any:
    """A send this half has already prepared and not yet applied. Its card is on the screen,
    so a second "send it instead" is a repetition rather than a new instruction."""
    from app.actions.models import ActionStatus

    return _latest(session, branch, lambda op: op.startswith("gmail_send_"), (ActionStatus.PENDING,))


def _latest(session: Any, branch: Any, matches, usable) -> Any:
    branch_id = str(getattr(branch, "branch_id", "") or "")
    cutoff = _now() - CONVERT_WINDOW_S
    best = None
    best_rank = ()
    for proposal in getattr(session, "proposals", None) or ():
        if not matches(str(getattr(proposal, "operation", "") or "")):
            continue
        if getattr(proposal, "undo_of", None) or str(getattr(proposal, "branch_id", "") or "") not in ("", branch_id):
            continue
        status = getattr(proposal, "status", None)
        if status not in usable or float(getattr(proposal, "created_at", 0)) < cutoff:
            continue
        rank = (-usable.index(status), float(proposal.created_at))
        if best is None or rank >= best_rank:
            best, best_rank = proposal, rank
    return best


# --------------------------------------------------------------------------- the commands


def _no_composer() -> Outcome:
    return Outcome.refused("no_composer", "There is no email open on this half to do that to.")


def _compose_field(ctx: CommandCtx) -> Outcome:
    """A precision field on the composer, typed.

    THIS is the hybrid input of §7, and the reason it is not a way round the write boundary:
    the tablet posts a compose id, a field NAME from a closed set, and the characters the
    owner typed. It does not post an execution argument, and nothing it posts is sent
    anywhere — the Mac validates the value into its own copy of the composer and answers with
    the card again. When the gesture comes, the arguments are built from the Mac's copy.
    """
    compose = held(ctx.branch, ctx.arg("compose_id"))
    if compose is None:
        return _no_composer()
    name = ctx.arg("field")
    if name not in FIELDS:
        # Fail closed. The tablet must not be able to name a key of the Mac's own context —
        # "at", "converts" and "thread_id" are all in that dictionary and none of them is
        # something a keystroke may set.
        log.warning("compose.field refused: %r is not a field of the composer", name)
        return Outcome.refused("unknown_field", f"There is no field called {name!r} on the composer.")
    if name not in editable_fields(compose):
        # A reply's recipient and subject. The card draws them fixed; this is why they are.
        return Outcome.refused(
            "not_editable",
            "A reply goes back to whoever wrote last in the thread, at the address their message "
            "asks for, under the thread's own subject. I read both there when the reply is prepared.",
        )
    raw = str(ctx.args.get("value") or "")
    before = revision(compose)
    if name == "to":
        value, status, hint = check_address(raw)
        compose.update({"to": value, "to_status": status, "to_hint": hint})
    elif name == "to_name":
        compose["to_name"] = " ".join(raw.split())[:80]
    elif name == "subject":
        line = " ".join(raw.split())[:MAX_SUBJECT_CHARS]
        compose.update({"subject": line, "subject_status": "ok" if line else "uncertain"})
    else:
        text = raw.replace("\r\n", "\n")[:MAX_BODY_CHARS]
        compose.update({"body": text, "body_status": "ok" if text.strip() else "uncertain"})
    compose["at"] = _now()
    ctx.session.remember_pii(*[v for v in (compose.get("to"), compose.get("to_name")) if v])
    # A hold card prepared from the email as it read before this keystroke would send that, not
    # this: withdrawn now, and named so the tablet settles it (round 13, S2b-03). A keystroke
    # that leaves the email as it was withdraws nothing.
    withdrawn = withdraw_prepared(ctx.session, compose) if revision(compose) != before else []
    return Outcome(answer="", surfaces=[compose_surface(compose)],
                   changed={"compose_id": str(compose["compose_id"]), "field": name,
                            "status": str(compose.get(f"{name}_status") or "ok"),
                            **({"withdrawn": withdrawn, "withdrawn_words": EDITED} if withdrawn else {})})


def _held_record(ctx: CommandCtx, kind: str, ref: str) -> tuple[dict[str, Any] | None, Outcome | None]:
    """A record this conversation was shown and the Mac still holds, or the refusal to say so.

    Two checks, two different refusals, and they must not be one. `may_open` is permission —
    the entity cache is process-global and a ref is a guess away from another conversation's
    customer — and a miss is a cache miss, which is a different sentence to the owner and a
    different thing for him to do about it.
    """
    from app.commands import may_open
    from app.memory import ENTITY
    from app.memory import current as memory

    if not ref:
        return None, Outcome.refused("no_record", "Nothing was named to do that to.")
    if not may_open(ctx, kind, ref):
        return None, Outcome.refused(
            "not_this_conversation",
            "That is not something this conversation has been shown.",
        )
    held = memory().get(ENTITY, f"{kind}:{ref}", allow_stale=True)
    value = getattr(held, "value", None) if held is not None else None
    if not isinstance(value, dict):
        word = "thread" if kind == "email_thread" else kind
        return None, Outcome.refused(
            f"{'thread' if kind == 'email_thread' else kind}_not_held",
            f"I am not holding that {word} any more — open it again and I'll write the reply.",
        )
    return value, None


def _last_inbound(thread: dict[str, Any]) -> dict[str, Any]:
    """The most recent message in the thread that came IN.

    Replying to our own last message is the failure this exists to stop: the newest message in
    a thread the shop has already answered is the shop's. `outbound` is the read model's own
    flag where it has one; failing that, the newest message is the fallback, which is what the
    thread card itself shows as the latest.
    """
    messages = [m for m in (thread.get("messages") or []) if isinstance(m, dict)]
    for message in reversed(messages):
        # A draft of ours waiting in the thread is not a message that came in, and the write
        # tool never answers one (`gmail_writes.thread_context`).
        if not message.get("outbound") and not message.get("draft") and (message.get("from_email") or message.get("from")):
            return message
    return messages[-1] if messages else {}


def _stand_on(ctx: CommandCtx, kind: str, ref: str, label: str, *, tab: str = "") -> None:
    """Where the owner is, once a composer is open over a record: still on the record.

    The composer is a context on the branch, not a stop on the trail, so Back from it returns
    to the thread or the order the reply is about. `visit` does not push a second stop for the
    record the owner is already on, which is the usual case — he tapped Reply on its card.
    """
    ctx.branch.visit(kind, ref, label, tab=tab)
    remember = getattr(ctx.session, "remember_context", None)
    if callable(remember):
        remember(kind, label, ref)
    focus = getattr(ctx.session, "set_focus", None)
    if callable(focus):
        focus(kind, ref)


def _compose_reply(ctx: CommandCtx) -> Outcome:
    """Reply, tapped on an email thread. Opens the reply; stages nothing; reads nothing.

    The tablet posts a thread id and nothing else. Everything on the card is read off the
    Mac's own copy of that thread: who wrote in last, where they asked for the answer to go,
    under what subject, in which thread. The recipient is shown and is NOT editable, because it
    is not the composer's to decide — the write tool re-reads the thread when the gesture comes
    and replies to the address the last message asks for (its Reply-To, else its From), which is
    the address this card shows (`_reply_recipient`) and the only one it will prepare to
    (`reply_as_shown`).

    D-11: Reply was rendered on twenty-four email cards in the live session and used on none.
    It armed the microphone and wrote a label to the dock, 788 pixels below the finger, which
    the act of speaking then overwrote. A chip called Reply now produces a reply.
    """
    thread_id = ctx.arg("thread_id") or ctx.arg("ref")
    thread, refused = _held_record(ctx, "email_thread", thread_id)
    if refused is not None:
        return refused
    assert thread is not None
    message = _last_inbound(thread)
    recipient = _reply_recipient(message)
    if recipient is None:
        return Outcome.refused(
            "no_sender",
            "I cannot tell who to reply to in that thread, so I have not opened a reply.",
        )
    subject = next((str(m.get("subject") or "") for m in reversed(thread.get("messages") or [])
                    if isinstance(m, dict) and m.get("subject")), "")
    from app.tools.gmail_writes import reply_subject

    compose_id = open_compose(
        ctx.branch, kind="reply", to=recipient["to"], to_name=recipient["to_name"],
        subject=reply_subject(subject), body="", thread_id=thread_id,
        about=f"a reply to {_first_word(str(message.get('from') or '')) or 'them'}",
        origin_text="",
    )
    compose = held(ctx.branch, compose_id) or {}
    # This address came off a thread Gmail served, not out of a microphone: `ok`, unless it is a
    # Reply-To that is not the sender, which the owner confirms on the card (`_show_recipient`).
    _show_recipient(compose, recipient)
    ctx.session.issue(compose_id)
    ctx.session.remember_pii(*[v for v in (compose.get("to"), compose.get("to_name"), compose.get("sender")) if v])
    _stand_on(ctx, "email_thread", thread_id, subject[:80], tab="")
    return Outcome(answer=_spoken(compose), surfaces=[compose_surface(compose)],
                   changed={"compose_id": compose_id, "thread_id": thread_id, "kind": "reply"})


def _compose_to_customer(ctx: CommandCtx) -> Outcome:
    """Email, tapped on an order. Opens a new email to that order's customer.

    The same shape as the reply and for the same reason: the tablet posts the ORDER, and the
    address is read off the Mac's own copy of it. Here the recipient IS editable — it is a new
    email and the owner may be writing to somebody else about the order — so it goes through
    `check_address` on every keystroke like any other typed address.
    """
    order_id = ctx.arg("order_id") or ctx.arg("ref")
    order, refused = _held_record(ctx, "order", order_id)
    if refused is not None:
        return refused
    assert order is not None
    address = str(order.get("customer_email") or "").strip()
    if not address or not EMAIL_ADDRESS.match(address):
        return Outcome.refused("no_address", "That order has no email address on it.")
    number = str(order.get("order_number") or "").lstrip("#")
    compose_id = open_compose(
        ctx.branch, kind="new", to=address, to_name=str(order.get("customer_name") or ""),
        subject=f"Your order {number}".strip() if number else "", body="",
        about=f"an email about order {number}" if number else "an email to the customer",
        origin_text="",
    )
    compose = held(ctx.branch, compose_id) or {}
    compose["to_status"], compose["to_hint"] = "ok", ""
    ctx.session.issue(compose_id)
    ctx.session.remember_pii(*[v for v in (compose.get("to"), compose.get("to_name")) if v])
    _stand_on(ctx, "order", order_id, f"#{number}" if number else "", tab="email")
    return Outcome(answer=_spoken(compose), surfaces=[compose_surface(compose)],
                   changed={"compose_id": compose_id, "order_id": order_id, "kind": "new"})


def _compose_to_person(ctx: CommandCtx) -> Outcome:
    """Email, tapped on a CUSTOMER. Opens a new email to the person the workspace is about.

    The owner asked for this in as many words, looking at a customer card that had his orders
    and his inbox and no way to write to him:

        "I want to also be seeing his orders and his history and like an email write box"

    §12's rich workspace is not only what is on the screen; it is whether the thing the
    screen is about can be acted on from there. Without this the customer workspace was a
    reading surface with two doors out of it and no way to do the one thing a person looking
    at a customer usually wants to do.

    The same shape as the order's Email and for the same reasons: the tablet posts the
    CUSTOMER, the address is read off the Mac's own copy of that record, and nothing is
    staged — a composer is a draft on the screen until a gesture says otherwise. The
    recipient IS editable here, because a new email to a person may be about anything, so it
    goes through `check_address` on every keystroke like any other typed address.
    """
    customer_id = ctx.arg("customer_id") or ctx.arg("ref")
    customer, refused = _held_record(ctx, "customer", customer_id)
    if refused is not None:
        return refused
    assert customer is not None
    address = str(customer.get("email") or customer.get("customer_email") or "").strip()
    if not address or not EMAIL_ADDRESS.match(address):
        return Outcome.refused(
            "no_address", "I do not have an email address for them, so I have not opened one.")
    name = str(customer.get("name") or customer.get("customer_name") or "").strip()
    compose_id = open_compose(
        ctx.branch, kind="new", to=address, to_name=name,
        subject="", body="",
        about=f"an email to {_first_word(name) or 'them'}",
        origin_text="",
    )
    compose = held(ctx.branch, compose_id) or {}
    # From a record the shop served, not out of a microphone — same as the reply.
    compose["to_status"], compose["to_hint"] = "ok", ""
    ctx.session.issue(compose_id)
    ctx.session.remember_pii(*[v for v in (compose.get("to"), compose.get("to_name")) if v])
    _stand_on(ctx, "customer", customer_id, name[:80], tab="email")
    return Outcome(answer=_spoken(compose), surfaces=[compose_surface(compose)],
                   changed={"compose_id": compose_id, "customer_id": customer_id, "kind": "new"})


def _first_word(who: str) -> str:
    word = str(who or "").strip().split(",")[0].strip().split(" ")[0].strip(" <>\"'")
    return word if word and "@" not in word else ""


# Which write tool each gesture on the composer reaches. Server-owned: the tablet posts
# "draft" or "send" and the Mac decides what that is a call to.
_STAGE_TOOL = {
    ("new", "draft"): "gmail_draft_new",
    ("new", "send"): "gmail_send_new",
    ("reply", "draft"): "gmail_draft_reply",
    ("reply", "send"): "gmail_send_reply",
}


def _stage_args(compose: dict[str, Any], mode: str) -> tuple[str, dict[str, Any]]:
    """(tool, arguments) for this composer, built entirely from the Mac's copy of it."""
    kind = "reply" if compose.get("thread_id") else "new"
    tool_name = _STAGE_TOOL[(kind, mode)]
    if kind == "reply":
        # A reply's recipient and subject are re-read from the thread by the tool itself, as
        # they always have been. Passing them would be the model's-recipient bug in a new hat.
        # The tool holds the recipient it reads to the one this card shows (`reply_as_shown`).
        return tool_name, {"thread_id": str(compose["thread_id"]), "body": str(compose["body"])}
    return tool_name, {
        "compose_id": str(compose["compose_id"]), "to": str(compose["to"]),
        "to_name": str(compose.get("to_name") or ""), "subject": str(compose["subject"]),
        "body": str(compose["body"]),
    }


def _ready_to_stage(compose: dict[str, Any]) -> str:
    """Why this composer cannot be prepared yet, in the owner's words. Empty when it can."""
    if compose["kind"] == "new" and compose.get("to_status") != "ok":
        if compose.get("to_status") == "uncertain":
            return "That address came from what you said, not from your typing. Tap it, check it, and then I'll prepare this."
        return "There is no address I can send to yet."
    if _awaiting_confirmation(compose):
        return (f"This message was sent by {compose.get('sender')} and asks for replies to go to {compose.get('to')}. "
                f"Tap “{CONFIRM_TO_LABEL}” if that is right; otherwise write a new email to {compose.get('sender')}.")
    # A reply's subject is the thread's, read there when the change is prepared; a thread with
    # no subject line at all is not a reason to refuse to answer it.
    if compose["kind"] == "new" and not str(compose.get("subject") or "").strip():
        return "It has no subject yet."
    if not str(compose.get("body") or "").strip():
        return "It has no words in it yet. Tap the box and type, or hold the dock and say it."
    return ""


def _compose_stage(ctx: CommandCtx) -> Outcome:
    """Save draft or Send, tapped. Prepares the change; applies nothing.

    The staging itself happens in `POST /command` (`changed["stage"]`), for the same reason
    `open.area` names a recipe rather than reading: a command is synchronous by design
    (app/commands.py) and preparing a change is a fresh read. What crosses that line is a
    registered write tool's NAME and the arguments the MAC built here — never anything the
    tablet posted, and never a value that has not been through `check_address`.
    """
    compose = held(ctx.branch, ctx.arg("compose_id"))
    if compose is None:
        return _no_composer()
    mode = ctx.arg("mode") or "draft"
    if mode not in ("draft", "send"):
        return Outcome.refused("unknown_mode", "A composer is saved as a draft or sent; there is no third thing.")
    why = _ready_to_stage(compose)
    if why:
        return Outcome.refused("not_ready", why)
    tool_name, args = _stage_args(compose, mode)
    # A composer loaded from a draft (`draft_send_instead`) carries the draft's proposal id.
    # Sending replaces that card; saving another draft does not.
    revoke = [str(compose["converts"])] if compose.get("converts") and mode == "send" else []
    return Outcome(answer="", changed={
        "compose_id": str(compose["compose_id"]),
        "stage": {"tool": tool_name, "args": args, "revoke": revoke,
                  "what": "send the email" if mode == "send" else "save the draft",
                  # Which email, as it reads now: the change prepared from it is withdrawn if it
                  # is edited or closed before the preparing is done (`moved_since`).
                  "compose_id": str(compose["compose_id"]), "revision": revision(compose)},
    })


def _compose_confirm_to(ctx: CommandCtx) -> Outcome:
    """"Yes, reply to this address", tapped on a reply that goes to a Reply-To other than the
    sender. The address confirmed is the one on the card, recorded as such: a thread that asks
    for replies somewhere else by the time it is prepared is refused there (`reply_as_shown`)."""
    compose = held(ctx.branch, ctx.arg("compose_id"))
    if compose is None:
        return _no_composer()
    if not _elsewhere(compose):
        return Outcome.refused("nothing_to_confirm", "This reply goes to the person who wrote; there is nothing to confirm.")
    compose.update({"confirmed_to": str(compose.get("to") or ""), "to_status": "ok",
                    "to_hint": f"sent by {compose.get('sender')}; you confirmed replies go here", "at": _now()})
    return Outcome(answer="", surfaces=[compose_surface(compose)],
                   changed={"compose_id": str(compose["compose_id"]), "field": "to", "status": "ok"})


def _compose_discard(ctx: CommandCtx) -> Outcome:
    compose = held(ctx.branch, ctx.arg("compose_id"))
    if compose is None:
        return _no_composer()
    ctx.branch.compose = None
    # A hold card prepared from an email he has just thrown away is not one to hold.
    withdrawn = withdraw_prepared(ctx.session, compose, "The email was cancelled.")
    return Outcome(answer="Gone. Nothing was saved.",
                   changed={"compose": None, "discarded": str(compose["compose_id"]),
                            **({"withdrawn": withdrawn, "withdrawn_words": "The email was cancelled."} if withdrawn else {})})


def _draft_send_instead(ctx: CommandCtx) -> Outcome:
    """"Send it instead", as a gesture: this half's draft, staged as a send, and the draft's
    own card withdrawn once the send is prepared.

    Everything comes from the Mac. The recipient, subject and body are read out of the draft
    proposal's stored `execution` — the arguments the Mac itself decided and would have sent
    — so the send carries exactly the email the owner read on the draft card. Which identity
    argument the send needs is decided from the proposal's `entity_ref`, which is what the
    Mac recorded the change as being about; the model's own arguments are not consulted.
    The withdrawal is ordered AFTER the staging (`POST /command` does it in that order),
    because a draft card taken away by a send that then failed to prepare leaves the owner
    with nothing at all.
    """
    already = _latest_send(ctx.session, ctx.branch)
    if already is not None:
        # The conversion has happened and its card is on the screen. Preparing a second send
        # of one email is how an email goes twice, and the words are the honest answer.
        return Outcome.refused("already_ready", "That one is already ready to send — hold the card.")
    found = _latest_draft(ctx.session, ctx.branch)
    if found is None:
        return Outcome.refused(
            "no_draft",
            "There is no draft of mine on this half to send. Say what the email should say and I'll write it.",
        )
    execution = dict(found.execution)
    thread_id = str(execution.get("thread_id") or "")
    body = str(execution.get("body") or "")
    if not body.strip():
        return Outcome.refused("no_draft_body", "That draft has no words in it that I can send.")
    if thread_id:
        tool_name = "gmail_send_reply"
        args: dict[str, Any] = {"thread_id": thread_id, "body": body}
    else:
        tool_name = "gmail_send_new"
        ref = str(getattr(found, "entity_ref", "") or "")
        args = {"subject": str(execution.get("subject") or ""), "body": body}
        if ref.startswith("cmp_"):
            args.update({"compose_id": ref, "to": str(execution.get("to") or ""),
                         "to_name": str(execution.get("to_name") or "")})
        elif ref.startswith("gid://shopify/Customer/"):
            args["customer_id"] = ref
        elif ref:
            args["order_id"] = ref
        else:
            return Outcome.refused("no_draft_recipient", "I cannot tell who that draft was to, so I have not prepared a send.")
    return Outcome(answer="", changed={
        "converts": found.proposal_id,
        "stage": {"tool": tool_name, "args": args, "revoke": [found.proposal_id], "what": "send it instead"},
    })


def _draft_discard(ctx: CommandCtx) -> Outcome:
    """"Forget the draft." Withdraws the card, which is synchronous and needs no read. A
    draft already saved in Gmail is removed by its own undo, which is the engine's business
    and not this command's."""
    found = _latest_draft(ctx.session, ctx.branch)
    if found is None:
        return Outcome.refused("no_draft", "There is no draft of mine on this half to forget.")
    withdrawn = ctx.runtime.actions.revoke_ids([found.proposal_id], "the owner said no draft")
    return Outcome(answer="Forgotten. Nothing was saved.",
                   changed={"discarded": found.proposal_id, "revoked": withdrawn})


# --------------------------------------------------------------------------- registration

# Reply and Email, tapped on a card. A spoken "reply to this" goes to the model with the
# thread named, which is a different thing to opening a box to type in. Neither reads
# anything and neither can stage.
register_command(Command("compose.reply", "Open a reply to this email thread", _compose_reply, voice=False))
register_command(Command("compose.to_customer", "Open an email to this order's customer", _compose_to_customer, voice=False))
register_command(Command("compose.to_person", "Open an email to this customer", _compose_to_person, voice=False))
register_command(Command("compose.field", "Type into the email being written", _compose_field, voice=False))
register_command(Command("compose.stage", "Save the email as a draft, or send it", _compose_stage, voice=False))
register_command(Command("compose.confirm_to", "Confirm where a reply goes when it is not the sender", _compose_confirm_to,
                         voice=False))
register_command(Command("compose.discard", "Throw away the email being written", _compose_discard, voice=False))
# Send and Discard on a draft card.
register_command(Command("draft.send_instead", "Send the draft instead of saving it", _draft_send_instead))
register_command(Command("draft.discard", "Forget the draft that is waiting", _draft_discard))

register_capability(CapabilityFamily(
    key="email_compose",
    label="Writing an email to any address",
    area="email",
    what="write, draft or send an email to an address you give me, not only to a customer",
    operations=("gmail_draft_new", "gmail_send_new"),
    tools=("gmail_compose_open", "gmail_compose_fill"),
    scopes=("https://www.googleapis.com/auth/gmail.compose",),
    state="READY",
    # The last clause is the answer to a question the owner asked out loud and got "that
    # didn't come through clearly" to: how do I type? Reply on an email and Email on an order
    # open this card, and every box on it takes a keyboard.
    detail="tap Reply on an email, or Email on an order, and type it; the draft and the send are gestures on the card",
))
