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
from collections.abc import Callable
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
) -> Surface:
    """The workspace as a card. Every value copied key by key and bounded, which is
    `app/presentation.py`'s rule kept here because this card is built outside it: nothing
    from the shop, from the inbox or from the model reaches the tablet except through one of
    these copies.

    `rows` are the things on it (an order's lines) and `picks` the choices offered for one
    ("which of these?"), each with at most one button — a command name and its arguments,
    which the MAC put there, and which say which row and nothing of what to do with it.
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
            "notes": [str(n)[:220] for n in (notes or [])[:MAX_NOTES] if str(n or "").strip()],
            "rows": [_row(r, ident) for r in (rows or [])[:MAX_ROWS] if isinstance(r, dict)],
            "picks": [_row(r, ident) for r in (picks or [])[:MAX_PICKS] if isinstance(r, dict)],
            "picks_title": str(picks_title or "")[:80],
            "blocked": str(blocked or "")[:220],
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
