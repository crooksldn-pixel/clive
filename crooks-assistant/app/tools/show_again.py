"""Bringing a screen back: "pull that up again", "show me the order again", "bring back the draft".

George, 29 September: "sometimes closed the screen without a way to pull it up again, pulling up
the screen again is not something you can say to clive". Every sentence is the model's, and the
model had no hands for this: its reads draw a record it looks up by name or number, and nothing
drew back a WORKSPACE, a draft being written, or "the one I had up" by the words the owner uses.

One tool, `show_again`, and it is a read. It puts back something this conversation has already
shown him — by the id the conversation was issued, by the kind of thing ("the draft", "the
order"), or, with neither, the last thing this half showed that is not on the screen now — and
it reads the record again first, so what comes back is the order as it is now and not as it was
an hour ago. If that read fails it says so and draws the copy the Mac holds, marked as such.

What it may show is decided by the same rule as every read (app/tools/gate.py): an id handed to
it must be one this conversation was issued, which the gate checks before this runs; what it
finds by kind or as "the last one" is on this half's own record of what it drew
(`Branch.shown_before`), every card of which was drawn for this conversation. A draft or a note
card the owner's own next sentence withdrew is not something a read can put back — a change is
only ever staged by its write tool — so for those the model is told exactly what to call to
prepare it again, and the card that comes back is a new one, waiting for his gesture.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app import screen
from app.capabilities.families import CapabilityFamily, register
from app.tools.context import acting_branch, current_session
from app.tools.gate import Tier
from app.tools.registry import ToolError, tool

log = logging.getLogger("crooks.tools.show_again")

AGAIN_TOOL = "show_again"

# Named in the family table like every read the model is offered (tests/test_families.py): /health
# and the settings sheet list it, and the manifest's delta sees it.
register(CapabilityFamily(
    key="recall", label="Bring it back", area="system",
    what="put back on your screen something this conversation already showed you, read again so it is current",
    tools=(AGAIN_TOOL,),
    state="READY", detail="ready",
))

# The words the model may use for what to bring back, and the cards each one means.
KINDS = ("order", "customer", "email", "draft", "objective", "building", "list")
_CARDS_OF: dict[str, tuple[str, ...]] = {
    "order": ("order", "order_workspace", "workspace", "variant_picker"),
    "customer": ("customer", "customer_workspace"),
    "email": ("email_thread", "reply_state"),
    "draft": ("email_compose", "email_draft"),
    "building": ("workspace",),
}
# The read that brings each kind of record back as it is now, and where its id is.
_REREAD: dict[str, tuple[str, str]] = {
    "order": ("shopify_order_detail", "order_id"),
    "customer": ("shopify_customer_history", "customer_id"),
    "email_thread": ("gmail_read_thread", "thread_id"),
}
# The operations whose card is a draft, for "bring back the draft" after it was withdrawn.
_DRAFT_TOOLS = ("gmail_draft_reply", "gmail_draft_new", "gmail_send_reply", "gmail_send_new")
READ_TIMEOUT_S = 6.0


# ------------------------------------------------------------------------------- finding it


def _entries(branch: Any) -> list[dict[str, Any]]:
    return [e for e in (getattr(branch, "shown_before", None) or []) if isinstance(e, dict) and isinstance(e.get("card"), dict)]


def _matches_kind(card: dict[str, Any], wanted: str) -> bool:
    data = card.get("data") if isinstance(card.get("data"), dict) else {}
    if wanted == "objective":
        return bool(data.get("objective_id"))
    if wanted == "list":
        return screen.record_of(card) is None and screen.kind(card) not in ("workspace", "email_compose", "email_draft") \
            and not data.get("objective_id")
    if wanted == "order" and screen.kind(card) == "workspace":
        return str(data.get("kind") or "") == "order_draft"
    return screen.kind(card) in _CARDS_OF.get(wanted, ())


def find(branch: Any, *, ref: str = "", wanted: str = "") -> dict[str, Any] | None:
    """The card this half drew for what is asked for, most recent first — or None.

    With neither `ref` nor `wanted` it is "the last one": the most recent thing this half had
    up that is not on its screen now, which is what "pull that up again" means once the screen
    has moved on; and when everything it drew is still up, the first of them, read again.
    """
    entries = _entries(branch)
    if ref:
        for entry in entries:
            if ref in screen.refs_on([entry["card"]]):
                return entry["card"]
        return None
    if wanted:
        return next((e["card"] for e in entries if _matches_kind(e["card"], wanted)), None)
    up = {screen.identity(card) for card in screen.showing(branch)}
    for entry in entries:
        if entry.get("identity") not in up:
            return entry["card"]
    return entries[0]["card"] if entries else None


def _record_by_ref(session: Any, ref: str) -> tuple[str, str] | None:
    """(kind, ref) of a record this conversation was issued but this half never drew: an order
    on a list's row, a thread the other half opened. By the shape of the id alone."""
    from app.tools.gate import id_kind_ok

    for kind, (_tool, argument) in _REREAD.items():
        if id_kind_ok(argument, ref) and ref in (getattr(session, "issued_ids", None) or ()):
            if kind == "email_thread" and (ref.startswith("gid://") or ref.startswith("obj_")):
                continue
            return kind, ref
    return None


# ------------------------------------------------------------------------------ reading it


async def _read(session: Any, tool_name: str, args: dict[str, Any], *, draws: bool) -> dict[str, Any] | None:
    """One read, through the read scheduler and the registered read tool, as a tap's is
    (app/routes/command.py `_read_member`): the gate checks the id again, and a failure is an
    answer of its own rather than an exception."""
    from app.reads.scheduler import Read, ReadPlan, run_plan

    plan = ReadPlan([Read("again", tool_name, dict(args), source="gmail" if tool_name.startswith("gmail_") else "shopify",
                          draws=draws)], label="show_again")
    try:
        result = await run_plan(plan, session=session, timeout_s=READ_TIMEOUT_S, turn_id=getattr(session, "turn_id", ""))
    except Exception as exc:  # noqa: BLE001 — a read that could not be made is said, not raised
        log.info("show_again could not read %s: %s", tool_name, type(exc).__name__)
        return None
    body = result.values.get("again") if hasattr(result, "values") else None
    return body if isinstance(body, dict) else None


def _held(kind: str, ref: str) -> dict[str, Any] | None:
    """The record as the Mac last read it, when a fresh read could not be made."""
    from app.memory import ENTITY
    from app.memory import current as memory

    try:
        held = memory().get(ENTITY, f"{kind}:{ref}", allow_stale=True)
    except Exception:  # noqa: BLE001 — nothing held is an answer
        return None
    value = getattr(held, "value", None) if held is not None else None
    return value if isinstance(value, dict) else None


def _keep(kind: str, ref: str, body: dict[str, Any], tool_name: str) -> None:
    """What was read, kept where Back and a replay find it — as every read of a record is."""
    from app.memory import ENTITY
    from app.memory import current as memory

    try:
        memory().put(ENTITY, f"{kind}:{ref}", body, source="gmail" if kind == "email_thread" else "shopify",
                     query=f"model:{AGAIN_TOOL}", provenance={"tool": tool_name, "ref": ref})
    except Exception as exc:  # noqa: BLE001 — a cold cache is a slower Back, not a failed answer
        log.debug("could not keep what show_again read: %s", exc)


def _label(card: dict[str, Any]) -> str:
    """What the owner calls the thing brought back, in a few words for the model's sentence."""
    data = card.get("data") if isinstance(card.get("data"), dict) else {}
    kind = screen.kind(card)
    if kind == "order":
        return f"order {data.get('order_number') or ''}".strip()
    if kind in ("order_workspace", "customer_workspace"):
        return str(data.get("title") or data.get("label") or kind.replace("_", " "))
    if kind == "customer":
        return f"the customer {data.get('name') or ''}".strip()
    if kind == "email_thread":
        return "the email thread" + (f" “{data.get('subject')}”" if data.get("subject") else "")
    if kind == "email_compose":
        return "the email being written"
    if kind == "email_draft":
        return "the saved draft"
    if kind == "workspace":
        return str(data.get("title") or "the one being built")
    return str(data.get("title") or kind.replace("_", " "))


async def _redraw(card: dict[str, Any], session: Any, branch: Any) -> dict[str, Any]:
    """The card brought back as it is now: a record read again, a workspace composed again
    from that read, a composer or a half-built workspace drawn from the Mac's own copy."""
    kind = screen.kind(card)
    data = card.get("data") if isinstance(card.get("data"), dict) else {}
    record = screen.record_of(card)
    label = _label(card)
    if record is not None:
        record_kind = record[0]
        ref = str((data.get("ref") if kind.endswith("_workspace") else data.get(_REREAD[record_kind][1])) or "")
        return await _reread(record_kind, ref, session, label=label, workspace=card if kind.endswith("_workspace") else None)
    if kind == "email_compose":
        compose = getattr(branch, "compose", None)
        if isinstance(compose, dict) and str(compose.get("compose_id") or "") == str(data.get("compose_id") or ""):
            from app.families.compose import compose_surface

            return {"shown": label, "fresh": True, "_surfaces": [compose_surface(compose).as_ui()]}
        return _withdrawn_draft(session, branch) or {"shown": "", "fresh": False, "note": "That email was discarded; nothing was saved from it."}
    if kind == "workspace":
        rebuilt = _building(branch, str(data.get("workspace_id") or ""))
        if rebuilt is not None:
            return {"shown": label, "fresh": True, "_surfaces": [rebuilt]}
        return {"shown": "", "fresh": False, "note": "That is no longer being built on this half; start it again to carry on."}
    if data.get("objective_id"):
        return await _objective(card, str(data["objective_id"]), label=label)
    # A list, a summary, a saved draft: drawn as it was shown. None of them has one record to
    # read again, and a listing re-run would be a different question.
    return {"shown": label, "fresh": False, "note": _as_shown(branch, card), "_surfaces": [screen.plain(card)]}


def _let_go_of_copies(kind: str, ref: str) -> None:
    """What the Mac holds of the record, let go before it is read again: the order a search
    handed over a moment ago, and the answer the read layer would serve twice inside its few
    seconds. He asked to see it again, and what he sees is the shop as it is now."""
    from app.reads import dedupe

    try:
        if kind == "order":
            from app.tools.shopify_tools import hydrator

            hydrator().forget(ref)
        dedupe.current().invalidate(ref=ref)
    except Exception as exc:  # noqa: BLE001 — a copy not let go is read again anyway when it ages
        log.debug("could not let go of what was held of %s: %s", kind, type(exc).__name__)


async def _reread(kind: str, ref: str, session: Any, *, label: str, workspace: dict[str, Any] | None = None) -> dict[str, Any]:
    tool_name, argument = _REREAD[kind]
    _let_go_of_copies(kind, ref)
    body = await _read(session, tool_name, {argument: ref}, draws=workspace is None)
    fresh = body is not None
    if body is None:
        body = _held(kind, ref)
    else:
        _keep(kind, ref, body, tool_name)
    if body is None:
        raise ToolError(f"{label.capitalize()} could not be read just now, and I hold no copy of it. Say so; do not describe it.")
    note = "" if fresh else f"{'Gmail' if kind == 'email_thread' else 'Shopify'} did not answer, so this is {label} as I last read it."
    if workspace is not None:
        rebuilt = screen.recompose(workspace, body, session=session)
        if rebuilt is not None:
            return {"shown": label, "fresh": fresh, "note": note, "_surfaces": [rebuilt]}
    return {"shown": label, "fresh": fresh, "note": note, "_reads": [{"tool": tool_name, "result": body}]}


async def _objective(card: dict[str, Any], objective_id: str, *, label: str) -> dict[str, Any]:
    """An objective, read again from CLIVE's own record of it."""
    from app.objectives.tools import objective_show
    from app.presentation import _family_cards, _from_result

    try:
        body = await objective_show(objective_id)
    except ToolError:
        return {"shown": label, "fresh": False, "note": "That objective could not be read; this is it as last shown.",
                "_surfaces": [screen.plain(card)]}
    drawn = _from_result("objective_show", body) + _family_cards("objective_show", body, None)
    # Its own card when the presentation layer draws one from the read; otherwise the card
    # that was shown, which is the only drawing of an objective there is.
    return {"shown": label, "fresh": True, "_reads": [{"tool": "objective_show", "result": body}]} if drawn else \
        {"shown": label, "fresh": False, "note": "", "_surfaces": [screen.plain(card)]}


def _building(branch: Any, workspace_id: str) -> dict[str, Any] | None:
    """A half-built discount, order or credit, drawn from the Mac's own copy of it — or, once it
    has made what it was for, drawn as that (an order card that has made its order comes back as
    the order, by its number, and never as something that could make it again)."""
    from app.families import _workspace as ws

    return ws.drawn(branch, workspace_id)


def _withdrawn_draft(session: Any, branch: Any) -> dict[str, Any] | None:
    """The last email this half prepared, when its card was withdrawn — by the owner's next
    sentence, as every new instruction withdraws a waiting card. A read cannot put a change
    back; its write tool can, and the model is told exactly what to call."""
    return _restage(session, branch, tools=_DRAFT_TOOLS, label="the draft")


def _restage(session: Any, branch: Any, *, tools: tuple[str, ...] = (), label: str = "that change") -> dict[str, Any] | None:
    half = str(getattr(branch, "branch_id", "") or "")
    for proposal in reversed(list(getattr(session, "proposals", None) or [])):
        if proposal.undo_of or (tools and proposal.tool_name not in tools):
            continue
        if half and str(getattr(proposal, "branch_id", "") or "") not in ("", half):
            continue
        if proposal.status.value not in ("REVOKED", "EXPIRED"):
            return None                    # a newer change is not withdrawn: nothing to restage
        return {"shown": "", "fresh": False,
                "restage": {"tool": proposal.tool_name, "args": dict(proposal.model_args)},
                "note": f"{label.capitalize()} was withdrawn when you were next spoken to; a read cannot put a change "
                        f"back. Call {proposal.tool_name} again with these arguments to prepare it again, and say it "
                        "is ready for his gesture."}
    return None


def _as_shown(branch: Any, card: dict[str, Any]) -> str:
    for entry in _entries(branch):
        if entry["card"] is card:
            at = float(entry.get("at") or 0.0)
            if at:
                return f"This is {_label(card)} as it was shown at {time.strftime('%H:%M', time.localtime(at))}; it was not read again."
    return f"This is {_label(card)} as it was shown; it was not read again."


# --------------------------------------------------------------------------------- the tool


def _for_the_model(result: Any) -> Any:
    """What the model reads: what went back on the screen, whether it is as it is now, and —
    for a change a read cannot bring back — what to call. Never the record's contents: the
    model has had them once, and the card shows them."""
    if not isinstance(result, dict):
        return result
    return {k: v for k, v in result.items() if k in ("shown", "fresh", "note", "restage") and v not in ("", None)}


@tool(
    name=AGAIN_TOOL,
    description=(
        "Put back on the owner's screen something this conversation showed him, read again so it is "
        "current: by ref (its id), by kind, or with neither the last thing he had up. For 'pull that "
        "up again', 'show me the order again', 'bring back the draft'."
    ),
    input_schema={
        "type": "object",
        "properties": {"ref": {"type": "string"}, "kind": {"type": "string", "enum": list(KINDS)}},
    },
    tier=Tier.GREEN,
    issued_id_args=("ref",),
    timeout_s=READ_TIMEOUT_S + 4.0,
    model_view=_for_the_model,
)
async def show_again(ref: str = "", kind: str = "") -> dict[str, Any]:
    session = current_session()
    if session is None:
        raise ToolError("There is no conversation to show anything from.")
    branch = session.branch(acting_branch(session))
    ref, kind = str(ref or "").strip(), str(kind or "").strip()
    card = find(branch, ref=ref, wanted=kind)
    if card is not None:
        return await _redraw(card, session, branch)
    if ref:
        record = _record_by_ref(session, ref)
        if record is not None:
            return await _reread(record[0], record[1], session, label=f"that {record[0].replace('_', ' ')}")
        if ref.startswith("obj_") and ref in (getattr(session, "issued_ids", None) or ()):
            return await _objective({"type": "objective", "data": {"objective_id": ref}}, ref, label="the objective")
    if kind == "draft":
        restaged = _withdrawn_draft(session, branch)
        if restaged is not None:
            return restaged
    restaged = _restage(session, branch) if not ref and not kind else None
    if restaged is not None:
        return restaged
    what = f"a {kind}" if kind else ("that" if ref else "anything")
    raise ToolError(f"This conversation has not shown {what} on this half, so there is nothing to put back. "
                    "Say so plainly; offer to look it up.")
