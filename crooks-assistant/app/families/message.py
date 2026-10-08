"""The message card: one card, the words editable on it, one hold that sends (DEC-068).

George, 7 October: "I also don't want to have to click save draft and then send — why do I have
to click save draft and then say send it and then it pulls up a send it screen to send." So a
message he asked for is ONE card: who it goes to, the subject if it has one, the words — which
he may change right there — and the hold that sends it. No Save draft step, no second screen.

This is not a second mutation system. The card is the action engine's own confirmation card,
carrying a `message` block (built by `app/presentation.py` `_message_block` from what the write
tool's `present()` says). The hold is the engine's: staged, armed, committed, proven by reading
the sent message back, exactly as before. What this module adds is the one command a finger on
that card can post, `message.stage`, in two forms:

* an EDIT — `key`, a field NAME from the card's own closed list, and the typed value. The
  waiting change is withdrawn first, then the same write tool is prepared again with that one
  argument changed, through `POST /command`'s staging (`app/routes/command.py` `_stage_change`):
  the gate holds every id to this conversation, the tool re-reads the thread and checks the new
  words (the orders they name, the links in them), and a new card takes the old one's place. So
  the hold always sends exactly the words on the card, and a refused edit leaves nothing that
  could send the old ones. A second edit that arrives while the first is still being prepared
  is answered "busy" (the tablet sends it again once the first has its answer), and an edit
  after a refused one is prepared from the card the refused edit withdrew.
* the OTHER WAY — `key` and `other=1`: the same words prepared as the write the card names as
  its alternative (an email's "Save as draft", a draft's "Send instead"), then the card withdrawn.
* AGAIN — `key` and `again=1`, offered only on the card of a send that provably did not go (the
  engine settled it FAILED: the service refused it, or it never left): the same words, as they
  were on the card when he held it, prepared again as a new card to hold. Never after an
  outcome that is not known (UNVERIFIED: it may have gone), never over a newer card of the same
  message, and never after the thread moved (STALE: there is something new to read first).

The tablet supplies a field name and characters, never an argument: which argument a field is,
and which tool the other way is, are the write tool's own words, read here on the Mac.

THE CONTRACT, for any write that wants this card (the messaging tools for WeCom, WhatsApp and
Instagram among them): its `WriteSpec.present(proposal)` returns, beside its title and facts,

    "message": {
        "channel":  "email" | "wecom" | "whatsapp" | "instagram",
        "kind":     a short word the card may show ("reply", "new"),
        "to":       the recipient line, as the card prints it,
        "subject":  a subject line, or "" for a chat message,
        "body":     the words the hold sends, as given (what a keystroke edits),
        "sign_off": what is added to them when they go (an email's signature), or "",
        "editable": the fields he may change on the card, from ("subject", "body"),
        "args":     {field: the tool argument that field is prepared again with},
        "other":    {"tool": a registered write, "label": "Save as draft"} or None,
        "sending":  true when the hold sends it (false for a draft or a save),
    }

and its tool must be preparable again from its own arguments with that one argument changed —
which every write tool already is, since `stage` is a call with arguments. Its tier is the
tool's own (sending to a customer or an outsider is RED, so the gesture is the hold).
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from collections import OrderedDict
from typing import Any

from app.commands import Command, Outcome
from app.commands import Ctx as CommandCtx
from app.commands import register as register_command

log = logging.getLogger("crooks.families.message")

COMMAND = "message.stage"
CHANNELS = frozenset({"email", "wecom", "whatsapp", "instagram"})
FIELDS = ("subject", "body")
EDITED = "The words were changed on the card, so the card is prepared again."
MAX_VALUE_CHARS = 4000
# The outcomes after which a send provably did not go (app/actions/engine.py): the service said
# no, or nothing left this process. Only these offer "Try again".
NOT_SENT = frozenset({"refused", "service_unavailable", "failed"})
AGAIN_LABEL = "Try again"

# The latest edit of each message, so a slower preparing of an earlier edit is never the card
# left waiting (`moved_since`). Bounded: a key is one message on one half of one conversation.
_EDITS: OrderedDict[str, int] = OrderedDict()
MAX_TRACKED = 256

# Which message each card is: the card it began as. A card the model (or the composer) prepared
# begins a message of its own; a card prepared FROM one — an edit, the other way, Try again — is
# the same message, linked here by the route that prepared it (`prepared`). So two replies to one
# thread, or a draft and a separate send to one order, are two messages with two keys, and an
# edit of one never re-prepares or withdraws the other. Bounded: a link outlives its card only
# for as long as the engine keeps that card.
_BEGAN_AS: OrderedDict[str, str] = OrderedDict()
MAX_LINKED = 1024

# The edit of each message being prepared right now, and since when. Between an edit's withdrawal
# of the waiting card and the new card existing, nothing waits under that message, so a second
# edit arriving then is told to wait ("busy") rather than that the message has gone. Cleared by
# the route once the preparing is over (`prepared`); a mark it never cleared stops counting after
# PREPARING_S, which is longer than any tool may take.
_PREPARING: dict[str, tuple[int, float]] = {}
PREPARING_S = 60.0
BUSY = "The words typed before these are still being prepared. These follow them."
_clock = time.monotonic


def began_as(proposal: Any) -> str:
    """The id of the card this message began as: the proposal's own, unless it was prepared from
    another card of the same message."""
    proposal_id = str(getattr(proposal, "proposal_id", "") or "")
    return _BEGAN_AS.get(proposal_id, proposal_id)


def key_of(proposal: Any) -> str:
    """One message's id on the card, the same across every edit of it and across its other way
    (a draft and its send are one message): its conversation, what kind of thing it goes to and
    which one, and which message on it — the card it began as (`began_as`), so two messages to
    the same thread never share a card. Minted here and opaque: nothing of who it is to is in
    it, so it can sit in an attribute on the tablet. Which half it belongs to is the proposal's
    own (`waiting`)."""
    named = [str(getattr(proposal, name, "") or "") for name in ("session_id", "entity_kind", "entity_ref")]
    parts = "|".join([*named, began_as(proposal)])
    return "msg_" + hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


def prepared(staging: dict[str, Any], proposal_id: str) -> None:
    """What `POST /command` tells this module once it has prepared what a finger on the card asked
    for (`app/routes/command.py`), whether or not a card came of it: an edit is no longer being
    prepared, and the new card, when there is one, is the same message as the card it was
    prepared from."""
    key, seq = str(staging.get("message_key") or ""), staging.get("edit_seq")
    if seq and _PREPARING.get(key, (None, 0.0))[0] == seq:
        del _PREPARING[key]
    origin = str(staging.get("message_origin") or "")
    if proposal_id and origin:
        _BEGAN_AS.pop(proposal_id, None)
        _BEGAN_AS[proposal_id] = origin
        while len(_BEGAN_AS) > MAX_LINKED:
            _BEGAN_AS.popitem(last=False)


def preparing(key: str) -> bool:
    """Whether an edit of this message is being prepared right now."""
    held = _PREPARING.get(key)
    if held is None:
        return False
    if _clock() - held[1] > PREPARING_S:
        del _PREPARING[key]
        return False
    return True


def words_of(proposal: Any) -> dict[str, Any]:
    """The write tool's own `present()` for this proposal, or nothing."""
    from app.tools import registry

    try:
        write = registry.get(str(proposal.tool_name)).write
        words = write.present(proposal) if write is not None else None
    except Exception:  # noqa: BLE001 — a card with no words offers nothing to edit
        return {}
    return words if isinstance(words, dict) else {}


def message_of(proposal: Any) -> dict[str, Any] | None:
    """The proposal's message block as its tool wrote it, when it has a well-formed one."""
    if getattr(proposal, "undo_of", None):
        return None
    message = words_of(proposal).get("message")
    if not isinstance(message, dict) or str(message.get("channel") or "") not in CHANNELS:
        return None
    return message


def editable(message: dict[str, Any]) -> list[str]:
    """The fields of this message a keystroke may reach: named by the tool, from the closed
    set, and each with the argument it is prepared again with."""
    args = message.get("args") if isinstance(message.get("args"), dict) else {}
    named = message.get("editable") if isinstance(message.get("editable"), list) else []
    return [f for f in FIELDS if f in named and isinstance(args.get(f), str) and args[f]]


def other_way(message: dict[str, Any]) -> dict[str, str] | None:
    other = message.get("other")
    if not isinstance(other, dict) or not other.get("tool") or not other.get("label"):
        return None
    return {"tool": str(other["tool"]), "label": str(other["label"])}


def waiting(session: Any, branch: Any, key: str) -> Any:
    """The change still waiting on this half whose card is this message, newest first."""
    branch_id = str(getattr(branch, "branch_id", "") or "")
    for proposal in reversed(list(getattr(session, "proposals", None) or [])):
        status = getattr(getattr(proposal, "status", None), "value", "")
        if status != "PENDING" or getattr(proposal, "undo_of", None) or getattr(proposal, "batch_id", ""):
            continue
        if str(getattr(proposal, "branch_id", "") or "") not in ("", branch_id):
            continue
        expired = getattr(proposal, "expired", None)
        if callable(expired) and expired():
            continue
        if key_of(proposal) == key and message_of(proposal) is not None:
            return proposal
    return None


def others_waiting(session: Any, key: str, *, keep: str) -> list[str]:
    """Every other change still waiting under this message's card: what an edit that raced a
    slower one leaves behind, withdrawn once the newest card exists."""
    out = []
    for proposal in list(getattr(session, "proposals", None) or []):
        if (getattr(getattr(proposal, "status", None), "value", "") == "PENDING" and str(proposal.proposal_id) != keep
                and not getattr(proposal, "undo_of", None) and key_of(proposal) == key):
            out.append(str(proposal.proposal_id))
    return out


def _next_edit(key: str) -> int:
    seq = _EDITS.pop(key, 0) + 1
    _EDITS[key] = seq
    while len(_EDITS) > MAX_TRACKED:
        _EDITS.popitem(last=False)
    return seq


def moved_since(session: Any, staging: dict[str, Any]) -> str:
    """Why a card an edit has just prepared is not the newest words on the card, or "" when it is.
    Asked by `POST /command` after the preparing, as the composer's `moved_since` is."""
    seq = staging.get("edit_seq")
    if not seq:
        return ""
    return "A later edit is being prepared." if _EDITS.get(str(staging.get("message_key") or "")) != seq else ""


def not_sent(proposal: Any) -> bool:
    """Whether this is the card of a send that provably did not go: FAILED, with an outcome the
    engine only records when nothing left or the service refused it, and a message that sends."""
    status = str(getattr(getattr(proposal, "status", None), "value", ""))
    if status != "FAILED" or str(getattr(proposal, "code", "") or "") not in NOT_SENT:
        return False
    message = message_of(proposal)
    return bool(message and message.get("sending"))


def why_not_sent(proposal: Any) -> str:
    """Why a send that provably did not go did not go, as he is told it: the service's own
    reason when it gave one (a Google error's quoted words, without the exception's type or the
    request), else that it could not be reached. One sentence; "" when it did go or may have."""
    if not not_sent(proposal):
        return ""
    from app.actions.engine import service_name
    from app.tools import registry

    try:
        write = registry.get(str(proposal.tool_name)).write
    except KeyError:
        write = None
    service = service_name(str(proposal.tool_name), write)
    reason = str(getattr(proposal, "reason", "") or "")
    quoted = re.search(r'returned "([^"]{1,120})"', reason)
    reason = quoted.group(1) if quoted else re.sub(r"^[A-Z][A-Za-z]*: ", "", reason)
    reason = " ".join(reason.split())[:120].rstrip(". ")
    if str(proposal.code) == "refused" and reason:
        return f"{service} refused it: {reason}."
    return f"It did not leave: {service} could not be reached."


def again_offer(proposal: Any) -> dict[str, str] | None:
    """The quiet "Try again" a not-sent message's card carries: the command and the card's key."""
    if not not_sent(proposal):
        return None
    return {"label": AGAIN_LABEL, "command": COMMAND, "args": f"key={key_of(proposal)}&again=1"}


def latest(session: Any, branch: Any, key: str) -> Any:
    """The newest change of this message on this half, whatever became of it."""
    branch_id = str(getattr(branch, "branch_id", "") or "")
    for proposal in reversed(list(getattr(session, "proposals", None) or [])):
        if getattr(proposal, "undo_of", None) or getattr(proposal, "batch_id", ""):
            continue
        if str(getattr(proposal, "branch_id", "") or "") not in ("", branch_id):
            continue
        if key_of(proposal) == key:
            return proposal
    return None


def withdrawn_by_an_edit(session: Any, branch: Any, key: str) -> Any:
    """The card an edit withdrew and nothing replaced — the edit's words were refused — when it
    is still the newest card of this message on this half and still within its wait: what the
    next edit is prepared from. None otherwise (it went, was declined, ran out, or has a newer)."""
    proposal = latest(session, branch, key)
    if proposal is None or str(getattr(getattr(proposal, "status", None), "value", "")) != "REVOKED":
        return None
    if str(getattr(proposal, "reason", "") or "") != EDITED or message_of(proposal) is None:
        return None
    expired = getattr(proposal, "expired", None)
    return None if callable(expired) and expired() else proposal


def _no_message() -> Outcome:
    return Outcome.refused("no_message", "That message is no longer waiting. Ask for it again.")


def _message_stage(ctx: CommandCtx) -> Outcome:
    """A finger on the message card: an edit of one of its fields, or the other way."""
    key = (ctx.arg("key") or ctx.arg("compose_id")).strip()
    if ctx.arg("again"):
        return _again(ctx, key)
    proposal = waiting(ctx.session, ctx.branch, key) if key.startswith("msg_") else None
    message = message_of(proposal) if proposal is not None else None
    if proposal is None or message is None:
        if key.startswith("msg_") and preparing(key):
            # The edit before this one is between withdrawing the old card and making the new.
            return Outcome.refused("busy", BUSY)
        withdrawn = None if ctx.arg("other") or not key.startswith("msg_") else withdrawn_by_an_edit(ctx.session, ctx.branch, key)
        if withdrawn is not None:
            # The last edit was refused (a half-typed link, a "<"): the card he is typing on is
            # the one it withdrew, so this edit is prepared from that card's own arguments.
            return _edit(ctx, withdrawn, message_of(withdrawn) or {}, key, waiting=False)
        return _no_message()
    if ctx.arg("other"):
        return _the_other_way(proposal, message, key)
    return _edit(ctx, proposal, message, key)


def _the_other_way(proposal: Any, message: dict[str, Any], key: str) -> Outcome:
    other = other_way(message)
    if other is None:
        return Outcome.refused("no_other_way", "This message has no other way to be prepared.")
    # The waiting card stays until the other one exists: a failure to prepare it leaves him the
    # card he had rather than nothing (`_stage_change` withdraws `revoke` only after success).
    return Outcome(answer="", changed={"stage": {
        "tool": other["tool"], "args": dict(proposal.model_args), "revoke": [str(proposal.proposal_id)],
        "what": other["label"].lower(), "message_key": key, "message_origin": began_as(proposal),
    }})


def _again(ctx: CommandCtx, key: str) -> Outcome:
    """"Try again" on a send that did not go: the newest card of this message must be that one —
    a newer card, or one that went or may have gone, is never sent around."""
    proposal = latest(ctx.session, ctx.branch, key) if key.startswith("msg_") else None
    if proposal is None or not not_sent(proposal):
        return Outcome.refused("not_again", "That message is not one to send again from here. Ask for it again.")
    return Outcome(answer="", changed={"stage": {
        "tool": str(proposal.tool_name), "args": dict(proposal.model_args), "revoke": [],
        "what": "the message again", "message_key": key, "message_origin": began_as(proposal),
    }})


def _edit(ctx: CommandCtx, proposal: Any, message: dict[str, Any], key: str, *, waiting: bool = True) -> Outcome:
    """An edit of one field. `waiting` is False when `proposal` is the card a refused edit
    withdrew: nothing waits, so even the same words are prepared again, and there is nothing
    to withdraw first."""
    from app.providers.base import ToolCall

    field = ctx.arg("field").strip()
    if field not in editable(message):
        return Outcome.refused("not_editable", "That part of the message is not changed here.")
    value = str(ctx.args.get("value") or "").replace("\r\n", "\n")[:MAX_VALUE_CHARS]
    if waiting and value.strip() == str(message.get(field) or "").strip():
        # Nothing changed: the card as it stands, drawn again so the tablet stops waiting on it.
        return Outcome(answer="", calls=[ToolCall(name=str(proposal.tool_name), args=dict(proposal.model_args),
                                                  ok=True, proposal_id=str(proposal.proposal_id))],
                       changed={"message_key": key, "unchanged": True})
    if not value.strip():
        return Outcome.refused("empty", "A message needs words. Type them, or say “Not now”.")
    args = dict(proposal.model_args)
    args[str(message["args"][field])] = value
    # Withdrawn FIRST: whatever the preparing of the new words finds, the old words can no longer
    # be the ones a hold sends (the card on the glass now shows the new ones).
    if waiting:
        ctx.runtime.actions.revoke_ids([str(proposal.proposal_id)], EDITED)
    seq = _next_edit(key)
    _PREPARING[key] = (seq, _clock())
    return Outcome(answer="", changed={"stage": {
        "tool": str(proposal.tool_name), "args": args, "revoke": [], "what": "the message as edited",
        "message_key": key, "message_origin": began_as(proposal), "edit_seq": seq,
    }})


register_command(Command(COMMAND, "Change a message's words on its card, or prepare it the other way", _message_stage,
                         voice=False))
