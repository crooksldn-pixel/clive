"""The structured workspace: a form the MAC owns, for the changes that make a new thing.

Three of Phase 3's families create something that does not exist yet — a discount code
(§12), an order (§11), a credit on a customer's account (§13) — and all three failed Phase 2
the same way: asked for one, the assistant held a conversation about it. "What percentage?"
"And when does it start?" "And is there a limit?" Four turns of interrogation, each one a
round trip to a language model, and at the end of it a change proposed from words the model
was holding in its head.

A workspace is the answer to that, and it is deliberately not a questionnaire:

* It is a CONTEXT ON THE BRANCH (`Branch.workspace`), like the composer. Opening one reads
  what it needs to read and stages nothing; it cannot, because nothing has been proposed.
* It is FILLABLE FROM THREE SIDES. Voice puts values in when the family's read tool is
  called with them; a tap puts a value in through a `choose` command; a thumb types into a
  precision field, which posts the FIELD'S NAME and the characters and nothing else.
* The MAC decides what a value means. Every keystroke goes through the field's own `clean`
  function into the Mac's copy, and the card that comes back shows what the Mac made of it —
  ok, uncertain, or invalid, with the reason in the owner's words.
* Nothing on it is an argument to a mutation. When a gesture asks for the change, the
  family's staging command hands the ACTION ENGINE a registered write tool's name and the
  workspace's id; the write tool reads the Mac's copy, reads the shop again, and builds the
  execution arguments itself (app/actions/engine.py). The tablet has never posted one.

One workspace stands per half of the orb at a time, for the same reason one composer does:
the execution arguments are built from this dictionary, and a workspace left open this
morning is not what a gesture means this afternoon.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.surfaces import Surface

log = logging.getLogger("crooks.families.workspace")

# How long a workspace stands. Long enough to say the code, type the amount, look at the
# window and think about it; short enough that yesterday's cannot be authorised today.
WORKSPACE_TTL_S = 1800.0

MAX_FACTS = 10
MAX_NOTES = 4
MAX_ACTIONS = 4
MAX_VALUE_CHARS = 500
# The rows of a thing being built (an order's lines) and the choices offered for one ("which
# of these hoodies?"). An order made from here carries at most twenty lines.
MAX_ROWS = 20
MAX_PICKS = 8

# What a typed value may come back as, and what each one means to the owner. The same three
# the composer uses, and the same three rings in web/ui.js: ok, uncertain (heard rather than
# typed — look at it), invalid.
STATUSES = ("ok", "uncertain", "invalid")


@dataclass(frozen=True, slots=True)
class Field:
    """One precision field on a workspace, and the Mac's own rule for what may go in it.

    `clean` is the whole of the validation and it runs on the MAC: (raw) -> (value, status,
    hint). A field with no `clean` takes bounded plain text. Nothing on the tablet decides
    whether a value is good — a mis-typed discount code is a perfectly well-formed code
    belonging to a discount somebody else made, and only a read of the shop can tell.
    """

    name: str
    label: str
    kind: str = "text"                 # a kind of web/ui.js FIELD_KINDS
    placeholder: str = ""
    maxlength: int = 80
    rows: int = 0
    clean: Callable[[str], tuple[str, str, str]] | None = None


@dataclass(frozen=True, slots=True)
class Choice:
    """A small closed set the owner picks from with a finger: percentage or fixed amount,
    paid or unpaid. Closed on the MAC — an option id the family did not declare is refused,
    so the tablet cannot name a state the family has no meaning for."""

    name: str
    label: str
    options: tuple[tuple[str, str], ...]     # (id, label)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(i for i, _ in self.options)


def new_id(prefix: str) -> str:
    return f"{prefix}_{os.urandom(5).hex()}"


def _now() -> float:
    return time.time()


def open_workspace(
    branch: Any,
    *,
    kind: str,
    workspace_id: str,
    values: dict[str, str] | None = None,
    choices: dict[str, str] | None = None,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Start a workspace on this half and return it. Reads nothing; stages nothing.

    `facts` is the family's own working note — the customer it resolved, the draft order it
    made, the balance it read — and it never reaches the tablet except through the family's
    own `present`. `values` and `choices` are what voice put in before the card was drawn.
    """
    workspace: dict[str, Any] = {
        "workspace_id": str(workspace_id),
        "kind": str(kind),
        "values": {str(k): str(v or "") for k, v in (values or {}).items()},
        "status": {},
        "hints": {},
        "choices": {str(k): str(v or "") for k, v in (choices or {}).items()},
        "facts": dict(facts or {}),
        "staged": "",
        "at": _now(),
    }
    branch.workspace = workspace
    _LIVE.pop(str(workspace_id), None)
    _LIVE[str(workspace_id)] = workspace
    while len(_LIVE) > MAX_LIVE:
        _LIVE.pop(next(iter(_LIVE)))
    return workspace


def held(branch: Any, kind: str = "", workspace_id: str = "") -> dict[str, Any] | None:
    """This half's workspace, when it is the one named, of the kind asked for, and not stale.

    All three checks matter. The kind, because `discount.stage` must not be able to reach the
    order-creation workspace that replaced it. The id, because a workspace belongs to the
    half it was started on and a tap posted from a screen that has moved on must not reach
    the other half's. The clock, because the execution arguments are built from this
    dictionary.
    """
    workspace = getattr(branch, "workspace", None)
    if not isinstance(workspace, dict) or not workspace.get("workspace_id"):
        return None
    if kind and str(workspace.get("kind")) != str(kind):
        return None
    if workspace_id and str(workspace_id) != str(workspace["workspace_id"]):
        return None
    if _now() - float(workspace.get("at") or 0) > WORKSPACE_TTL_S:
        branch.workspace = None
        return None
    return workspace


def discard(branch: Any) -> None:
    branch.workspace = None


def put_away(branch: Any) -> None:
    """He has put this half's workspace away himself — "close that" (`close_screen`), his own
    Back off it, Home — and it was the card on his screen. It is still held, so "pull that back
    up" brings it back with everything on it (`drawn`); until then it is not the thing being
    built, and a sentence is not quietly applied to a card he chose to close (round 12's third
    check). Another card taking its place on the glass is NOT this: a stock question in the
    middle of an order leaves the order being built (the fourth)."""
    workspace = held(branch)
    if workspace is not None and on_glass(branch, workspace):
        workspace["facts"]["_put_away"] = True


def is_put_away(workspace: dict[str, Any] | None) -> bool:
    return bool(((workspace or {}).get("facts") or {}).get("_put_away"))


def on_glass(branch: Any, workspace: dict[str, Any] | None) -> bool:
    """Whether this workspace is the card on this half's screen — what the Mac last drew there
    (`Branch.last_ui`), or opened, changed or brought back since it last drew anything. Read off
    the same record of his screen that the turn reports as `screen`."""
    if not isinstance(workspace, dict):
        return False
    if float(workspace.get("at") or 0) >= float(getattr(branch, "last_at", 0.0) or 0.0):
        return True
    ident = str(workspace.get("workspace_id") or "")
    return any(isinstance(item, dict) and item.get("type") == "workspace"
               and str((item.get("data") or {}).get("workspace_id") or "") == ident
               for item in (getattr(branch, "last_ui", None) or []))


# The family that draws each kind of workspace, by module, for the two places that draw one
# again without being that family: the answer to a gesture (app/screen.py `after_gesture`) and
# "bring it back" (app/tools/show_again.py). Each module has `workspace_surface(workspace)`.
_DRAWN_BY = {"order_draft": "app.families.order_create", "discount": "app.families.discounts",
             "store_credit": "app.families.store_credit"}


def drawn(branch: Any, workspace_id: str = "") -> dict[str, Any] | None:
    """This half's workspace drawn as its family draws it now, as a `ui` item — or None when
    the half holds no such workspace, or its family cannot draw it. Drawn means put back on the
    glass: from now it is the card on his screen again (`on_glass`)."""
    workspace = held(branch, workspace_id=workspace_id)
    module = _DRAWN_BY.get(str((workspace or {}).get("kind") or ""))
    if workspace is None or module is None:
        return None
    workspace["at"] = _now()
    workspace.get("facts", {}).pop("_put_away", None)
    import importlib

    try:
        return importlib.import_module(module).workspace_surface(workspace).as_ui()
    except Exception as exc:  # noqa: BLE001 — a card not redrawn is the card as it was
        log.warning("could not draw the workspace again: %s", type(exc).__name__)
        return None


# --------------------------------------------------------------------------- made once
#
# A workspace makes ONE thing: an order, a code, a credit. Round 12's independent check found an
# order card that stayed "not created" with Prepare live after its hold — the next change and a
# second hold made the order twice — and then, fixed for orders alone, a credit card that did the
# same with money: redrawn after a verified £20 as "Store credit · not given", Prepare enabled,
# and a second hold gave another £20. So it is a property of every workspace, kept here.
#
# What happened to the one change a workspace was prepared for is noted by the workspace's id:
#
#     sending      a hold is applying it: reserved by that hold's commit (`before_commit`, which
#                  names the proposal), and from the moment the family sends it, left or leaving
#     done         proven made (or, for an order, Shopify said which order it made)
#     unconfirmed  it left and it could not be proven either way — which includes an answer that
#                  never came back and a re-read, made at once, that still shows nothing changed:
#                  Shopify may yet apply a request it was sent (round 13)
#     failed       it certainly did not happen — Shopify answered and refused it, it never left
#                  the Mac, or the commit failed before sending it — and the card is his to build
#                  and prepare again
#
# `done` is final: nothing later un-makes a thing that exists; and `unconfirmed` becomes nothing
# but `done`, since nothing later can prove that a request Shopify was sent was not applied.
# `sending`, `done` and `unconfirmed` all mean the card is finished (`finished`): drawn as what it
# made, or as sent and not confirmed, and every later change to it refused by its family in its
# own words; more of the same is a new card. Only the commit that reserved the card settles it:
# another hold card's commit — one withdrawn, expired or long settled, posted meanwhile — leaves it
# as it is (round 13). Noted by id rather than on the workspace itself because the engine sends the
# change knowing only the execution, and the commit route settles it knowing only the proposal
# (app/routes/actions.py). Bounded: the oldest are let go long after their workspaces have lapsed
# (WORKSPACE_TTL_S).

SENDING, DONE, UNCONFIRMED, FAILED = "sending", "done", "unconfirmed", "failed"
MAX_NOTED = 512
_NOTED: dict[str, dict[str, str]] = {}
# The workspaces themselves, by id, as they stand now — for a change about to be applied to ask
# whether the card it was prepared from still says what it said then (`card_state`).
MAX_LIVE = 256
_LIVE: dict[str, dict[str, Any]] = {}


def note(workspace_id: str, state: str, **info: Any) -> None:
    """What happened to the change a workspace was prepared for (see above)."""
    ident = str(workspace_id or "")
    if not ident or state not in (SENDING, DONE, UNCONFIRMED, FAILED):
        return
    now = _NOTED.get(ident) or {}
    if now.get("state") == DONE and state != DONE:
        return                           # made is made
    if now.get("state") == UNCONFIRMED and state not in (DONE, UNCONFIRMED):
        return                           # sent is sent: only proof that it was made moves it on
    if state == DONE and now.get("state") == DONE:
        info = {**now, **{k: v for k, v in info.items() if v}}
    _NOTED.pop(ident, None)
    _NOTED[ident] = {"state": state, **{str(k): str(v or "")[:160] for k, v in info.items() if k != "state"}}
    while len(_NOTED) > MAX_NOTED:
        _NOTED.pop(next(iter(_NOTED)))


def noted(workspace: dict[str, Any] | None) -> dict[str, str] | None:
    if not isinstance(workspace, dict):
        return None
    made = (workspace.get("facts") or {}).get("_made")
    if isinstance(made, dict):
        return dict(made)
    now = _NOTED.get(str(workspace.get("workspace_id") or ""))
    if now is not None and now.get("state") == DONE:
        workspace.setdefault("facts", {})["_made"] = dict(now)
    return dict(now) if now is not None else None


def finished(workspace: dict[str, Any] | None) -> dict[str, str] | None:
    """What the card made — {"state": "done", …} — or that its change left and was not proven
    ("sending", "unconfirmed"); None while it is still his to build. Either way a finished card
    is not built on again."""
    now = noted(workspace)
    return now if now is not None and now.get("state") in (SENDING, DONE, UNCONFIRMED) else None


def failed(workspace: dict[str, Any] | None) -> str:
    """Why the last attempt to make it did not, when it did not — for the card to say."""
    now = noted(workspace)
    return str(now.get("why") or "it was not made") if now is not None and now.get("state") == FAILED else ""


def live(workspace_id: str) -> dict[str, Any] | None:
    return _LIVE.get(str(workspace_id or ""))


# What each kind of workspace would MAKE, as its family says it (`makes`): the lines and the
# money, who it is for and where it goes — never a word typed into a search box. A hold card is
# for exactly that, so that and nothing else decides whether a change to the card has made the
# hold card stale (round 12's third check: re-tapping the choice already made, re-posting the
# same email or typing "cap" into "Add an item" each withdrew the hold card, and each Prepare
# after it made another draft in Admin, for no change at all).
_MAKES: dict[str, Callable[[dict[str, Any]], Any]] = {}


def makes(kind: str, what: Callable[[dict[str, Any]], Any]) -> None:
    """A family's word on what its workspace would make — anything JSON can carry."""
    _MAKES[str(kind)] = what


def card_state(workspace: dict[str, Any] | None) -> str:
    """What the card would make, as one short digest. A change carries the digest of the card it
    was prepared from (`prepared_as`), and before it is applied the card is read again: a card
    that would now make something else is a change nobody has authorised. A family that has not
    said what its card makes is held to every value, every choice and its lines."""
    if not isinstance(workspace, dict):
        return ""
    import hashlib
    import json

    what = _MAKES.get(str(workspace.get("kind") or ""))
    body = what(workspace) if what is not None else {
        "values": workspace.get("values") or {}, "choices": workspace.get("choices") or {},
        "lines": (workspace.get("facts") or {}).get("lines")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]


def still_as_prepared(execution: Any) -> str:
    """For a change's `observe`: "same" while the card it was prepared from still says what it
    said then, "moved" once it does not (or it is gone). Held as a precondition, so a hold card
    for what the card USED to say is stale and nothing is sent."""
    wanted = str((execution or {}).get("prepared_as") or "")
    if not wanted:
        return "same"                     # prepared before this was carried: nothing to hold it to
    return "same" if card_state(live(str((execution or {}).get("workspace_id") or ""))) == wanted else "moved"


def prepared(workspace: dict[str, Any]) -> None:
    """A change has just been prepared from this card: its hold card is what the card says."""
    workspace["facts"]["_prepared"] = card_state(workspace)
    workspace["facts"].pop("_withdrawn", None)
    _clear_failure(workspace)


def _clear_failure(workspace: dict[str, Any]) -> None:
    ident = str(workspace.get("workspace_id") or "")
    if (_NOTED.get(ident) or {}).get("state") == FAILED:
        _NOTED.pop(ident, None)


def touched(session: Any, workspace: dict[str, Any] | None, words: str, *, before: str) -> list[str]:
    """The card has just been changed, by a tap or by voice; `before` is what it would have made
    just before (`card_state`). When it would now make something else, a hold card still waiting
    that was prepared from it is for what it USED to make — holding it would make that — so it is
    withdrawn, and the card says so in `words` until it is prepared again. When it would make the
    same thing — the choice already made tapped again, the same email, a word typed into a search
    — nothing is withdrawn and the hold card stands. Returns the ids of the hold cards withdrawn,
    for the tablet to settle (round 12's second and third checks).

    A spoken change has usually been beaten to it — every new instruction withdraws what was
    waiting (app/routes/turn.py) — and the line on the card is said all the same."""
    if not isinstance(workspace, dict) or card_state(workspace) == before:
        return []
    return withdraw(session, workspace, words)


def withdraw(session: Any, workspace: dict[str, Any] | None, words: str) -> list[str]:
    """Withdraw every hold card still waiting that was prepared from this card, whatever the
    card says now — for a card that has changed (`touched`) or been thrown away."""
    if not isinstance(workspace, dict):
        return []
    ident = str(workspace.get("workspace_id") or "")
    ids = []
    for proposal in list(getattr(session, "proposals", None) or []):
        execution = getattr(proposal, "execution", None)
        status = getattr(getattr(proposal, "status", None), "value", "")
        if status == "PENDING" and isinstance(execution, Mapping) and str(execution.get("workspace_id") or "") == ident:
            ids.append(str(proposal.proposal_id))
    if ids:
        from app.actions.engine import current

        current().revoke_ids(ids, "the card it was prepared from changed")
    if workspace["facts"].pop("_prepared", None) is not None or ids:
        workspace["facts"]["_withdrawn"] = str(words)[:120]
    _clear_failure(workspace)
    return ids


def withdrawn(workspace: dict[str, Any] | None) -> str:
    return str(((workspace or {}).get("facts") or {}).get("_withdrawn") or "")


def never_left(exc: BaseException) -> bool:
    """Whether a failed send certainly changed nothing: Shopify answered and refused it, or it
    was refused before it left this Mac (read-only, a shape the reviewed document does not
    take, a connection that was never made)."""
    from app.readonly import WriteRefused

    return bool(getattr(exc, "refused", False) or getattr(exc, "unsent", False) or isinstance(exc, WriteRefused))


async def sending(workspace_id: str, send: Any, **info: Any) -> Any:
    """Send the one change a workspace was prepared for, noting it: `sending` and `left` before it
    leaves — from then on it may have been made whether or not an answer comes back — and
    `failed`, with Shopify's own reason, when it certainly was not. The hold whose commit reserved
    the card (`before_commit`) is carried on both, so that commit, and no other, settles it."""
    ident = str(workspace_id or "")
    now = _NOTED.get(ident) or {}
    holder = now.get("proposal", "") if now.get("state") == SENDING else ""
    note(ident, SENDING, **info, left="1", proposal=holder)
    try:
        return await send
    except Exception as exc:
        if never_left(exc):
            note(ident, FAILED, why=_reason(exc), unsent="1", proposal=holder)
        raise


def _reason(exc: BaseException) -> str:
    text = " ".join(str(exc).split())
    return text[:140] if text else type(exc).__name__


def commit_refused(proposal: Any) -> str:
    """Why this hold card may not be applied, when the card it was prepared from has already
    made its one thing (or is making it) with ANOTHER hold card. A commit retried on the hold
    card that made it is the engine's to answer, and is not refused here."""
    ident = _workspace_of(proposal)
    if not ident or str(getattr(getattr(proposal, "status", None), "value", "")) != "PENDING":
        return ""
    if (_NOTED.get(ident) or {}).get("state") in (SENDING, DONE, UNCONFIRMED):
        return "That card has already made what it was for, so nothing was sent. Anything more is a new one."
    workspace = live(ident)
    if workspace is not None and (workspace.get("facts") or {}).get("_prepared") != card_state(workspace):
        # The card has changed since this was prepared from it (`touched` withdraws the hold
        # card as it changes; this is the floor under that): what it would make is not what
        # the card says now.
        return "The card changed since this was prepared, so nothing was sent. Prepare it again."
    return ""


def before_commit(proposal: Any) -> None:
    """The owner's gesture is about to apply a change prepared from a workspace: until the
    engine has an answer the card is finished, so a second Prepare meanwhile cannot make a
    second one. The reservation names the proposal whose commit made it: only that commit's
    outcome settles or releases it (`after_commit`). What a failed card said before is kept with
    it, for the card to say again if nothing is sent after all."""
    ident = _workspace_of(proposal)
    if not ident:
        return
    now = _NOTED.get(ident) or {}
    if now.get("state") not in (None, FAILED):
        return
    was = {"was_why": now.get("why"), "was_unsent": now.get("unsent")} if now.get("state") == FAILED else {}
    note(ident, SENDING, by="commit", proposal=str(getattr(proposal, "proposal_id", "") or ""), **was)


def after_commit(proposal: Any, session: Any = None) -> None:
    """What the gesture came to, noted for the card it was prepared from (see above) — and the
    records a proven change made, issued to the conversation like any id a read returned, so
    "add a note to it" can follow the order the hold just made.

    Proof that it was made is taken from any commit. Anything else is taken only from the commit
    that reserved the card: a commit of another hold card of the same card — withdrawn, expired
    or long settled, posted by a page that had not caught up — came to nothing the card is
    waiting on, and neither frees it nor says it failed (round 13: such a commit used to free a
    card whose own hold was still at Shopify, and a second credit went through)."""
    ident = _workspace_of(proposal)
    if not ident:
        return
    status = str(getattr(getattr(proposal, "status", None), "value", "") or "")
    entity = getattr(proposal, "entity", None) if isinstance(getattr(proposal, "entity", None), dict) else {}
    now = _NOTED.get(ident) or {}
    reason = str(getattr(proposal, "reason", "") or "")
    if status == "VERIFIED":
        note(ident, DONE, **{k: entity.get(k) for k in _MADE_KEYS if entity.get(k)})
        if session is not None:
            from app.tools.gate import id_kind_ok

            for key in ("order_id", "customer_id"):
                if id_kind_ok(key, entity.get(key)):
                    session.issue(str(entity[key]))
        return
    holder = str(now.get("proposal") or "")
    if now.get("state") not in (SENDING, FAILED) or not holder or holder != str(getattr(proposal, "proposal_id", "") or ""):
        return
    if now.get("state") == FAILED and now.get("unsent"):
        # It never left, or Shopify answered and refused it: proven not made, whatever the
        # engine's re-read then said. The card is his again, with the reason.
        note(ident, FAILED, why=now.get("why") or reason or "it was not made", unsent="1")
    elif now.get("left") or status in ("EXECUTED", "UNVERIFIED"):
        # It left, and it is not proven made: the answer was lost, or one re-read made at once
        # still shows nothing changed — which is not proof, since Shopify may yet apply a request
        # it was sent (round 13). Sent, not confirmed; the card makes nothing more.
        note(ident, UNCONFIRMED, why=reason or "the answer never came back", proposal=holder)
    elif status == "FAILED":
        # It failed before it was sent — the precondition read, a cancellation before sending:
        # nothing left this Mac. The card is his again, with the reason.
        note(ident, FAILED, why=reason or now.get("was_why") or "it was not made")
    elif now.get("was_why") or now.get("was_unsent"):
        # Nothing was sent after all — not armed, stale, withdrawn, read-only — on a card whose
        # last attempt had failed: it says that again.
        note(ident, FAILED, why=now.get("was_why"), unsent=now.get("was_unsent"))
    else:
        # Nothing was sent after all: the reservation is let go.
        _NOTED.pop(ident, None)


# What the owner is told — by the hold card, the result card and the voice alike — about a change
# that left for Shopify and was not proven made. The engine settles such a send as failed with
# "Nothing was changed" when its one re-read still shows the thing as it was; the card it was
# prepared from knows it left (`sending`), and nothing on the screen may say otherwise (round 13).
SENT_NOT_CONFIRMED = "Sent to Shopify, not confirmed. Check it in Shopify Admin before asking again."


def sent_not_confirmed(proposal: Any) -> bool:
    """Whether this hold card's own commit sent its change and nothing proved it made: the card
    it was prepared from is noted unconfirmed, by this proposal and no other."""
    ident = _workspace_of(proposal)
    if not ident or str(getattr(getattr(proposal, "status", None), "value", "") or "") == "VERIFIED":
        return False
    now = _NOTED.get(ident) or {}
    return now.get("state") == UNCONFIRMED and bool(now.get("proposal")) and now.get("proposal") == str(getattr(proposal, "proposal_id", "") or "")


# What of a proven change's re-read the finished card may say: numbers and names the owner
# reads on it, never an address.
_MADE_KEYS = ("order_id", "order_number", "draft_id", "draft_name", "total", "code", "status", "takes_off", "balance",
              "customer_name")


def _workspace_of(proposal: Any) -> str:
    execution = getattr(proposal, "execution", None)
    return str(execution.get("workspace_id") or "") if isinstance(execution, Mapping) else ""


def plain(limit: int) -> Callable[[str], tuple[str, str, str]]:
    """The default rule: one line of bounded text, always acceptable, never uncertain."""

    def clean(raw: str) -> tuple[str, str, str]:
        return " ".join(str(raw or "").split())[:limit], "ok", ""

    return clean


def type_into(workspace: dict[str, Any], fields: tuple[Field, ...], name: str, raw: str) -> tuple[bool, str]:
    """A keystroke, validated into the Mac's own copy. Returns (accepted, why not).

    Fails closed on the field NAME. The tablet must not be able to name a key of the Mac's
    own dictionary — "facts", "staged" and "at" are all in there and none of them is
    something a keystroke may set.
    """
    spec = next((f for f in fields if f.name == name), None)
    if spec is None:
        log.warning("a workspace field was refused: %r is not a field of %s", name, workspace.get("kind"))
        return False, f"There is no field called {name!r} on this."
    rule = spec.clean or plain(spec.maxlength)
    value, status, hint = rule(str(raw or "")[:MAX_VALUE_CHARS])
    workspace["values"][spec.name] = str(value)[: spec.maxlength]
    workspace["status"][spec.name] = status if status in STATUSES else "ok"
    workspace["hints"][spec.name] = str(hint or "")[:160]
    workspace["at"] = _now()
    return True, ""


def choose(workspace: dict[str, Any], choices: tuple[Choice, ...], name: str, option: str) -> tuple[bool, str]:
    """A tap on one of a closed set. The set is the family's; an option outside it is
    refused rather than stored, so a posted state the family has no meaning for cannot
    reach the input a mutation is built from."""
    spec = next((c for c in choices if c.name == name), None)
    if spec is None:
        log.warning("a workspace choice was refused: %r is not a choice of %s", name, workspace.get("kind"))
        return False, f"There is nothing called {name!r} to choose on this."
    if option not in spec.ids:
        return False, f"{option!r} is not one of {', '.join(spec.ids)}."
    workspace["choices"][spec.name] = option
    workspace["at"] = _now()
    return True, ""


def value(workspace: dict[str, Any], name: str, default: str = "") -> str:
    return str((workspace.get("values") or {}).get(name) or default)


def status(workspace: dict[str, Any], name: str) -> str:
    return str((workspace.get("status") or {}).get(name) or "ok")


def chosen(workspace: dict[str, Any], name: str, default: str = "") -> str:
    return str((workspace.get("choices") or {}).get(name) or default)


def fact(workspace: dict[str, Any], name: str, default: Any = None) -> Any:
    return (workspace.get("facts") or {}).get(name, default)


@dataclass(frozen=True, slots=True)
class Action:
    """A button on a workspace: which semantic command it posts, and the arguments the MAC
    put on it. Identities and small words only — never a value of the change."""

    id: str
    label: str
    command: str
    args: dict[str, str] = field(default_factory=dict)
    risk: str = ""                 # "red" draws it as the graver kind
    enabled: bool = True


def surface(
    workspace: dict[str, Any],
    *,
    fields: tuple[Field, ...],
    choices: tuple[Choice, ...] = (),
    kicker: str = "",
    title: str = "",
    subtitle: str = "",
    facts: list[dict[str, Any]] | None = None,
    notes: list[str] | None = None,
    actions: tuple[Action, ...] = (),
    field_command: str = "",
    blocked: str = "",
    spoken: str = "",
    rows: list[dict[str, Any]] | None = None,
    picks: list[dict[str, Any]] | None = None,
    picks_title: str = "",
    settled: str = "",
    settled_word: str = "",
) -> Surface:
    """The workspace as a card. Every value copied key by key and bounded, which is
    `app/presentation.py`'s rule kept here because this card is built outside it: nothing
    from the shop, from the inbox or from the model reaches the tablet except through one of
    these copies.

    `rows` are the things on it (an order's lines) and `picks` the choices offered for one
    ("which of these?"), each with at most one button — a command name and its arguments,
    which the MAC put there, and which say which row and nothing of what to do with it.

    `settled` is set once the workspace has made what it was for — "created", or "unconfirmed"
    when the change left and no answer came back — and the card then says so, in
    `settled_word` ("Created", "Given"), rather than "nothing is created until you authorise
    the card that follows".
    """
    ident = str(workspace["workspace_id"])
    return Surface(
        surface_type="workspace",
        ui_type="workspace",
        title=title,
        subtitle=subtitle,
        data={
            "workspace_id": ident,
            "kind": str(workspace.get("kind") or ""),
            "kicker": str(kicker or "")[:60],
            "title": str(title or "")[:80],
            "subtitle": str(subtitle or "")[:120],
            # Where a keystroke in one of these fields goes. Server-owned: the tablet reads
            # it off the card rather than knowing which command belongs to which family.
            "field_command": str(field_command or "")[:40],
            "fields": [
                {
                    "name": f.name, "label": f.label, "kind": f.kind,
                    "value": value(workspace, f.name),
                    "status": status(workspace, f.name),
                    "hint": str((workspace.get("hints") or {}).get(f.name) or "")[:160],
                    "placeholder": f.placeholder, "maxlength": int(f.maxlength),
                    "rows": int(f.rows) or None,
                }
                for f in fields
            ],
            "choices": [
                {
                    "name": c.name, "label": c.label,
                    "options": [
                        {"id": i, "label": label, "selected": chosen(workspace, c.name) == i}
                        for i, label in c.options
                    ],
                }
                for c in choices
            ],
            "facts": [
                {"label": str(f.get("label") or "")[:40], "value": str(f.get("value") or "")[:160],
                 "tone": str(f.get("tone") or "")[:8]}
                for f in (facts or [])[:MAX_FACTS]
            ],
            # A hold card withdrawn because the card changed (`touched`) says so here, first,
            # until the card is prepared again.
            "notes": [str(n)[:220] for n in ([withdrawn(workspace)] + list(notes or []))[:MAX_NOTES] if str(n or "").strip()],
            "rows": [_row(r, ident) for r in (rows or [])[:MAX_ROWS] if isinstance(r, dict)],
            "picks": [_row(r, ident) for r in (picks or [])[:MAX_PICKS] if isinstance(r, dict)],
            "picks_title": str(picks_title or "")[:80],
            "blocked": str(blocked or "")[:220],
            "settled": settled if settled in ("created", "unconfirmed") else "",
            "settled_word": str(settled_word or "")[:24] if settled in ("created", "unconfirmed") else "",
            "actions": [
                {"id": a.id, "label": a.label, "command": a.command,
                 "args": "&".join(f"{k}={v}" for k, v in {"workspace_id": ident, **a.args}.items()),
                 "risk": a.risk, "enabled": bool(a.enabled and not blocked) if a.risk else bool(a.enabled)}
                for a in actions[:MAX_ACTIONS]
            ],
        },
        spoken_summary=str(spoken or "Nothing is created until you authorise the card that follows.")[:200],
    )


def _row(row: dict[str, Any], ident: str) -> dict[str, Any]:
    """One row of a workspace, bounded key by key. Its button, when it has one, carries the
    workspace's id first and then the row's own identity — never a value of the change."""
    button = row.get("button") if isinstance(row.get("button"), dict) else None
    out = {
        "key": str(row.get("key") or "")[:40],
        "number": int(row["number"]) if isinstance(row.get("number"), int) and not isinstance(row.get("number"), bool) else None,
        "title": str(row.get("title") or "")[:80],
        "detail": str(row.get("detail") or "")[:120],
        "quantity": str(row.get("quantity") or "")[:8],
        "amount": str(row.get("amount") or "")[:24],
        "was": str(row.get("was") or "")[:24],
        "discount": str(row.get("discount") or "")[:40],
        "stock": str(row.get("stock") or "")[:40],
        "tone": str(row.get("tone") or "")[:8],
    }
    if button is not None:
        args = {"workspace_id": ident, **{str(k): str(v) for k, v in (button.get("args") or {}).items()}}
        out["button"] = {
            "label": str(button.get("label") or "")[:24],
            "command": str(button.get("command") or "")[:40],
            "args": "&".join(f"{k}={v}" for k, v in args.items())[:300],
        }
    return out
