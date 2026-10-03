"""What a tap means, named once.

A tap posts which command it was and which record it was on; the Mac decides the rest. Back,
Next, a tab, an expanded row, opening a record the Mac already holds: each is named here and
`POST /command` runs it. `POST /branches/{id}/back` survives as a position-only endpoint for a
caller that wants where the trail is and no card — it moves through `move_nav`, this file's
arithmetic, so it cannot drift from the command; it simply does not draw.

Words never reach this file. A sentence — typed or spoken, "go back" as much as "order 1047" —
is a model turn (app/routes/turn.py), and nothing matches its words to a command first. That
is the owner's decision of 28 September 2026: a lane that matched words in front of the model
kept answering a different question from the one he asked.

Three properties hold for everything in this file, and the tests hold them:

- **Deterministic.** No command here consults the model. Back, Next, a tab, an expanded row and
  opening a record the Mac already holds are all answerable from state the Mac already has, and
  putting a language model on that path buys nothing and costs a second.
- **Read-only.** Nothing here changes anything in the shop or the inbox. A command that would
  is not a command, it is a proposal, and proposals go through the action engine
  (`app/actions/engine.py`) with its staging, its gesture and its verification — untouched by
  this module.
- **Argument-free in the sense that matters.** A tap posts which command and which record, and
  the Mac decides what that means. It cannot post what the command should do.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.surfaces import ENTITY_KINDS
from app.workspace import SECTIONS as WORKSPACE_SECTIONS

log = logging.getLogger("crooks.commands")

# Which tool re-reads a record of each kind, for rebuilding a card from what the Mac still
# holds rather than asking the shop again. A kind absent from here cannot be replayed and the
# command says so instead of drawing an empty card.
REPLAY_TOOL = {
    "order": "shopify_order_detail",
    "customer": "shopify_customer_history",
    "email_thread": "gmail_read_thread",
}

# The tabs each surface offers. Held here rather than in the renderer because the Mac keeps
# which tab is showing — it survives a reload, a branch switch and a Back — and READ from
# app/workspace.py rather than written out again, because a composed surface's sections and
# the tabs the owner may open are the same list said twice. A customer's Inbox is "inbox"
# there and was "email" here: the quiet kind of mismatch §18 calls a control with no
# destination.
TABS: dict[str, tuple[str, ...]] = {
    "order": WORKSPACE_SECTIONS["order"],
    # "email" stays beside "inbox" on a customer: it is the word the owner says for that tab,
    # and `_select_tab` must not refuse a word that has somewhere to go.
    "customer": (*WORKSPACE_SECTIONS["customer"], "email"),
    "capability": ("orders", "customers", "products", "email", "analytics", "system"),
}


@dataclass
class Outcome:
    """What a command did."""

    ok: bool = True
    answer: str = ""
    code: str = ""                                  # set when ok is False
    detail: str = ""
    calls: list[Any] = field(default_factory=list)  # ToolCalls, so present() draws the card
    surfaces: list[Any] = field(default_factory=list)
    changed: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def refused(cls, code: str, detail: str, *, changed: dict[str, Any] | None = None) -> Outcome:
        """A refusal, and — where there is one — what the owner can do instead.

        `changed` is how a refusal carries a way forward. The live session refused a forked
        half twice in five seconds with sentences it could only read, and the owner concluded
        the feature did not work. A refusal with nothing to tap is a dead control.
        """
        return cls(ok=False, code=code, detail=detail, answer=detail, changed=dict(changed or {}))


@dataclass(frozen=True)
class Command:
    """One named thing the owner can mean."""

    name: str
    what: str
    run: Callable[[Any], Outcome]
    # Whether words can reach it. None can: a sentence is a model turn and nothing matches
    # its words to a command. Kept, and always false, because the command table on
    # /commands and the feature matrix have always carried the column.
    voice: bool = False
    touch: bool = True
    # What has to be open for the command to mean anything.
    needs_entity: tuple[str, ...] = ()
    needs_workflow: bool = False


@dataclass
class Ctx:
    """Everything a command may read."""

    runtime: Any
    session: Any
    branch: Any
    args: dict[str, Any] = field(default_factory=dict)

    def arg(self, name: str, default: str = "") -> str:
        return str(self.args.get(name) or default).strip()


REGISTRY: dict[str, Command] = {}


def register(command: Command) -> Command:
    if command.name in REGISTRY:
        raise ValueError(f"the command {command.name!r} is already registered")
    REGISTRY[command.name] = command
    return command


def get(name: str) -> Command | None:
    return REGISTRY.get(name)


def run(name: str, ctx: Ctx) -> Outcome:
    """Resolve one semantic command. Never raises: an unknown command is a refusal, because
    an unrecognised tap must not be able to take the backend down."""
    command = REGISTRY.get(name)
    if command is None:
        return Outcome.refused("unknown_command", f"There is no command called {name!r}.")
    if command.needs_entity:
        entity = getattr(ctx.branch, "entity", None) or {}
        if entity.get("kind") not in command.needs_entity:
            return Outcome.refused("no_entity", "There is nothing open to do that to.")
    if command.needs_workflow and getattr(ctx.branch, "workflow", None) is None:
        return Outcome.refused("no_set", "There is no list open to move through.")
    return command.run(ctx)


# --------------------------------------------------------------------- a way forward

# The four places the dock offers, in the words the dock uses. A refusal names them so that a
# half holding nothing has somewhere to go from the refusal itself.
DOCK_AREAS = (("orders", "Orders"), ("email", "Inbox"), ("sales", "Sales"), ("products", "Products"))
MAX_OFFER = 5


def _holds(branch: Any) -> dict[str, Any]:
    """What the half has, if it is a half that can say. Guarded because commands are run
    against stand-ins in a dozen tests and a refusal must never be the thing that raises."""
    describe = getattr(branch, "holds", None)
    return describe() if callable(describe) else {}


def offer_for(branch: Any) -> list[dict[str, str]]:
    """What a half can do from here, as commands the tablet can post unchanged.

    Each entry is a registered command name and its identities — never an instruction about
    what the command should do, which is the same rule the whole touch surface keeps. The
    record the half already holds comes first, because on a forked half that is the thing its
    owner was reaching for when he was told `not_held`.
    """
    out: list[dict[str, str]] = []
    entity = getattr(branch, "entity", None) or {}
    kind, ref = str(entity.get("kind") or ""), str(entity.get("ref") or "")
    if kind and ref:
        label = str(entity.get("label") or ref)
        out.append({"command": "open.entity", "kind": kind, "ref": ref, "label": label, "words": f"Open {label}"})
    for area, words in DOCK_AREAS:
        out.append({"command": "open.area", "area": area, "words": words})
    return out[:MAX_OFFER]


# --------------------------------------------------------------------------- replay


def may_open(ctx: Ctx, kind: str, ref: str) -> bool:
    """Whether THIS conversation is allowed to see that record at all.

    Kept apart from whether the Mac happens to hold it, because they are different questions
    with different answers. An empty `replay()` used to mean both — "I have not got it" and
    "it is not yours" — so a caller that wanted to READ a record it did not hold could not tell
    a cache miss from a refusal. Opening a row from a list is exactly that caller: a listing
    holds summaries, so the record is legitimately not cached, and the tap must read it. Only
    this check may turn that into a refusal.
    """
    from app.tools.gate import id_kind_ok

    argument = f"{kind}_id" if kind != "email_thread" else "thread_id"
    issued = getattr(ctx.session, "issued_ids", None) or frozenset()
    if ref in issued and id_kind_ok(argument, ref):
        return True
    log.warning("refused: %s %s was not issued to this conversation", kind, ref)
    return False


def replay(ctx: Ctx, kind: str, ref: str) -> list[Any]:
    """The card for a record the Mac already holds, rebuilt without asking the shop.

    This is what makes Back and Next feel instant and what makes them free: the read happened
    when the record was first opened, and going back to it is not a new question. Nothing is
    drawn that memory cannot supply — a stale entry produces no card rather than a wrong one.

    "Already holds" is not enough on its own, though, and this is the one rule of this file.
    The entity cache is process-global and shared by every conversation, because read data is
    immutable and caching it twice would be waste. Permission is not: a record is replayable to
    a conversation only if THAT conversation was shown it, which is what `session.issued_ids`
    records and what every tool call is checked against in `app/tools/gate.py`. Reading the
    cache is a way to reach a record without a tool call, so it is checked here too — the same
    rule `app/routes/context.py:41` keeps for the same data, and without it a ref is a guess
    away (`gid://shopify/Order/<n>`) from another conversation's customer, address and items.
    """
    from app.memory import ENTITY
    from app.memory import current as memory
    from app.providers.base import ToolCall

    tool = REPLAY_TOOL.get(kind, "")
    if not tool or not ref or not may_open(ctx, kind, ref):
        return []
    argument = f"{kind}_id" if kind != "email_thread" else "thread_id"
    held = memory().get(ENTITY, f"{kind}:{ref}", allow_stale=True)
    if held is None:
        return []
    return [ToolCall(name=tool, args={argument: ref}, ok=True, result=held.value)]


def _landed(ctx: Ctx, moved: dict[str, Any], *, words: str) -> Outcome:
    """Draw the workspace the trail landed on.

    Three kinds of stop, three ways of drawing one, and no fourth:

      a record the Mac holds       replayed from the entity cache, free and instant
      a record it has dropped      `needs_read` names it and the caller reads it
      a listing or a landing       the cards kept with the stop, or — if the tablet never
                                   sent them, or they have been dropped — the landing recipe
                                   for its area, read again deterministically

    Announcing a move and leaving the screen where it was is the failure this whole pass is
    about, so every branch here ends in something to look at.
    """
    from app.session.branch import LANDING_KIND

    branch = ctx.branch
    entry = branch.here
    changed: dict[str, Any] = {**moved, "workspace": branch.where()}
    if entry is not None and entry.is_workspace:
        if entry.ui:
            return Outcome(answer=words or entry.answer, surfaces=[AsUi(u) for u in entry.ui],
                           changed={**changed, "replayed": True})
        # Nothing kept: draw the place again from its own reads. A landing is a fixed shape
        # whatever was said before it, so this cannot come back as a different screen.
        recipe = LANDING_FOR.get(entry.area or "")
        if recipe:
            return Outcome(answer="", changed={**changed, "replayed": False, "recipe": recipe,
                                               "area": entry.area, "kind": LANDING_KIND})
        return Outcome(answer=words, changed={**changed, "replayed": False})
    kind, ref = str(moved.get("kind") or ""), str(moved.get("ref") or "")
    calls = replay(ctx, kind, ref)
    changed.update({"entity": {"kind": kind, "ref": ref, "label": str(moved.get("label") or "")},
                    "replayed": bool(calls)})
    if not calls and kind in REPLAY_TOOL:
        changed["needs_read"] = {"kind": kind, "ref": ref, "set_kind": _SET_KIND.get(kind, "")}
    return Outcome(answer=words, calls=calls, changed=changed)


# The working-set word for each entity kind, so a needs_read from a navigation move and one
# from a cursor move are read the same way.
_SET_KIND = {"order": "orders", "customer": "customers", "email_thread": "emails"}


# --------------------------------------------------------------------------- navigation


# Which way each navigation command moves the branch's trail. Home is deliberately absent:
# it is not a move along the trail at all (see `_home`), and while it was one it walked to
# `nav[0]` and replayed whatever record happened to be oldest.
NAV_MOVES = {"navigation.back": "back", "navigation.forward": "forward"}

# The dock's places, by area, to the recipe that draws each one. Filled in by
# `app/families/landings.py` at import — the landings own their own shapes, and this file
# stays free of them, because a command must not depend on a family.
LANDING_FOR: dict[str, str] = {}
# Where "back to the assistant" goes on a half that has never been anywhere.
DEFAULT_LANDING = "orders"


def home_target(branch: Any) -> tuple[str, str]:
    """The area a Home on this half lands in, and the recipe that draws it.

    One implementation: `POST /command` runs the recipe this names, so the Assistant chip and
    a Back that lands on a landing cannot reach two different screens.
    """
    area = str(getattr(branch, "home_area", "") or DEFAULT_LANDING)
    recipe = LANDING_FOR.get(area) or LANDING_FOR.get(DEFAULT_LANDING, "")
    return (area if recipe and area in LANDING_FOR else DEFAULT_LANDING), recipe


def move_nav(branch: Any, direction: str) -> dict[str, Any]:
    """Move the trail and say where it landed. Reads nothing.

    Separated from the drawing so the position-only `POST /branches/{id}/back` and the
    command move the trail by the same arithmetic.
    """
    entry = None
    if direction == "back":
        entry = branch.back()
    elif direction == "forward":
        entry = branch.forward()
    if entry is None:
        return {"landed": False, "direction": direction}
    return {"landed": True, "direction": direction, "kind": entry.kind, "ref": entry.ref,
            "label": entry.label, "tab": entry.tab, "area": entry.area,
            "set_id": entry.set_id, "position": entry.position, "total": entry.total}


def _navigate(ctx: Ctx, direction: str, *, nowhere: str, words) -> Outcome:
    moved = move_nav(ctx.branch, direction)
    if direction == "back" and moved.get("landed"):
        # Back off something being built puts it away, as "close that" does: it stays held,
        # and it is not what the next sentence changes (app/families/_workspace.py `put_away`).
        # The screen it was on is still the one the Mac last drew: the route draws the new one.
        from app.families import _workspace as workspaces

        workspaces.put_away(ctx.branch)
    if not moved.get("landed"):
        # Nowhere to go, and the branch has not moved. Said rather than refused: the owner
        # tapped something that does not apply, which is not a fault.
        return Outcome(answer=nowhere, changed={**moved, "workspace": ctx.branch.where()})
    return _landed(ctx, moved, words=words(moved["label"]))


def _back(ctx: Ctx) -> Outcome:
    """The workspace the owner came from — all of it.

    Not a render popped off a stack and not the previous member of the open list: the stop
    behind this one, put back the way it was. `Branch._land` is where that happens, and what
    it restores is the point of the whole defect: the record, the part of it showing, how far
    down, the working set, the cursor's place in it, the rows opened in place, and which
    record this one was reached from.
    """
    return _navigate(ctx, "back", nowhere="That is as far back as this conversation goes.",
                     words=lambda label: f"Back to {label}." if label else "Back.")


def _forward(ctx: Ctx) -> Outcome:
    return _navigate(ctx, "forward", nowhere="There is nothing forward of here.",
                     words=lambda label: f"Forward to {label}." if label else "Forward.")


def _home(ctx: Ctx) -> Outcome:
    """Back to the assistant: this half's LANDING workspace.

    This is the eight-Homes-in-twenty-two-seconds defect. Home used to walk the trail to
    `nav[0]` and replay the record it found there, and since every read leaves a stop, the
    record it found was the oldest thing the branch had looked at — an email thread from nine
    minutes earlier. It answered `ok=True` and drew that thread, eight times, while the owner
    pressed the button again because nothing useful was happening.

    A landing is a PLACE: a fixed shape, whatever was said before it, read deterministically
    by the same recipe the dock icon reaches (app/families/landings.py). So Home cannot
    replay a stale record, cannot depend on the trail having anything on it, and cannot
    answer differently the second time. The recipe is named here and run by the caller,
    because a command is synchronous by design and a landing is three reads.
    """
    area, recipe = home_target(ctx.branch)
    if not recipe:
        return Outcome.refused("no_landing", "I have no landing to go back to.")
    # Home off something being built puts it away, as "close that" does.
    from app.families import _workspace as workspaces

    workspaces.put_away(ctx.branch)
    return Outcome(answer="", changed={"recipe": recipe, "area": area, "home": True})


def _home_screen(ctx: Ctx) -> Outcome:
    """The page's Home chip: the home, not a landing (design pass, 3 Oct, and its review).

    The chip used to post `navigation.home` and draw the orders landing. It now goes to the
    home, which the page draws by itself, and posts this so the Mac's copy of the screen goes
    with it, as "close that" takes it (`close_screen`): put away, still on `shown_before` for
    "pull that back up", the trail and the cursor untouched. Without it a reload of the page
    redrew the order that had been up before Home. Reads nothing and draws nothing.
    """
    from app.families import _workspace as workspaces

    workspaces.put_away(ctx.branch)
    ctx.branch.cleared("", "")
    return Outcome(answer="", changed={"home": True, "cleared": True})


register(Command("navigation.back", "The workspace you came from", _back))
register(Command("navigation.forward", "The workspace you came back from", _forward))
register(Command("navigation.home", "This half's landing workspace", _home))
register(Command("screen.home", "The home: this half's screen put away", _home_screen))


# --------------------------------------------------------------------------- the cursor


def _member_words(ctx: Ctx, label: str) -> str:
    workflow = ctx.branch.workflow
    where = f"{workflow.position} of {workflow.total}"
    return f"{label}. {where}." if label else f"{where}."


def _position(ctx: Ctx) -> int:
    workflow = getattr(ctx.branch, "workflow", None)
    return int(workflow.position) if workflow is not None else 0


# Which tool reads one member of a set of each kind, and what that kind of record is called.
MEMBER_READ = {
    "orders": ("shopify_order_detail", "order_id", "order"),
    "customers": ("shopify_customer_history", "customer_id", "customer"),
    "emails": ("gmail_read_thread", "thread_id", "email_thread"),
}


def move_cursor(session: Any, branch: Any, *, forward: bool) -> dict[str, Any]:
    """The cursor move, and nothing else.

    This is the whole of what Next means, and it is arithmetic. Reads nothing. Returns what
    happened.
    """
    from app.analytics import sets as working_sets

    workflow = getattr(branch, "workflow", None)
    if workflow is None:
        return {"moved": False, "code": "no_set"}
    ws = working_sets.get(session, workflow.set_id)
    if ws is None or not ws.members:
        return {"moved": False, "code": "empty_set"}
    total = len(ws.members)
    workflow.total = total
    # The cursor starts at -1, before the first member, so the first "next" lands on 0.
    target = workflow.cursor + (1 if forward else -1)
    if target >= total:
        return {"moved": False, "code": "at_end", "cursor": workflow.cursor, "total": total}
    if target < 0:
        return {"moved": False, "code": "at_start", "cursor": workflow.cursor, "total": total}
    workflow.cursor = target
    ref = ws.members[target]
    label = ws.labels.get(ref) or ref
    _, _, kind = MEMBER_READ.get(ws.kind, ("", "", "order"))
    if ref not in workflow.visited:
        workflow.visited.append(ref)
    return {"moved": True, "cursor": target, "total": total, "ref": ref, "label": label,
            "kind": kind, "set_kind": ws.kind, "set_id": ws.set_id}


# What the end of a list sounds like, said rather than refused: the owner walking a queue of
# eleven must be able to tell the eleventh from the end.
BOUND_WORDS = {"at_end": "That is the last one.", "at_start": "That is the first one."}


def _step_cursor(ctx: Ctx, *, forward: bool) -> Outcome:
    """Move the cursor and show what it now points at.

    Bounds are the point: a cursor that runs off the end and reports the last member again is
    worse than one that says it has finished, because the owner walking a queue of eleven has
    no way to tell the eleventh from the end.
    """
    moved = move_cursor(ctx.session, ctx.branch, forward=forward)
    if not moved.get("moved"):
        code = str(moved.get("code") or "")
        if code in BOUND_WORDS:
            return Outcome(answer=BOUND_WORDS[code], changed={**moved, "position": _position(ctx),
                                                              "workspace": ctx.branch.where()})
        return Outcome.refused(code or "no_set", "There is no list open to move through.")
    kind, ref, label = str(moved["kind"]), str(moved["ref"]), str(moved["label"])
    ctx.branch.visit(kind, ref, label, set_id=str(moved.get("set_id") or ""))
    calls = replay(ctx, kind, ref)
    # The position as a number as well as in the sentence. The chip on the glass draws "3 of
    # 10" and used to parse it out of the prose, which meant it was right only for as long as
    # the wording stayed the same.
    outcome = Outcome(answer=_member_words(ctx, label), calls=calls,
                      changed={**moved, "replayed": bool(calls), "position": _position(ctx),
                               "workspace": ctx.branch.where()})
    if not calls:
        # Memory does not hold this member. The caller reads it: the route can await.
        outcome.changed["needs_read"] = {"kind": kind, "ref": ref, "set_kind": moved.get("set_kind")}
    return outcome


# Next is the CURRENT SET under the CURSOR and nothing else. `needs_workflow` is what keeps
# it from becoming "the next historical item": with no list open it refuses rather than
# walking the trail, which is the muddle the owner was reporting when he said Back and Next
# had both regressed — one pair of buttons over two different cursors.
register(Command("workflow.next", "The next one in the open list",
                 lambda ctx: _step_cursor(ctx, forward=True), needs_workflow=True))
register(Command("workflow.previous", "The one before it in the open list",
                 lambda ctx: _step_cursor(ctx, forward=False), needs_workflow=True))


# --------------------------------------------------------------------------- opening


def _open_entity(ctx: Ctx) -> Outcome:
    """Open a record the current screen linked to.

    The tablet posts the kind and the ref it was already given on the card — it does not have
    to describe the record, and the model is not asked to find it again.

    When the Mac already holds the record this is a replay and costs nothing. When it does not,
    it is READ, the way a cursor move onto an unheld member is: `needs_read` names it and the
    route reads it through the gate. It used to refuse instead — "ask for it and I will read it
    again" — which is a reasonable sentence in a conversation and a dead end under a finger. A
    list of today's orders holds summaries, not full records, so tapping any row on any list
    fell into exactly that case: the one route from a list to an order was to say its number.
    """
    kind, ref = ctx.arg("kind"), ctx.arg("ref")
    if kind not in ENTITY_KINDS:
        return Outcome.refused("unknown_kind", f"I do not know how to open a {kind or 'record'}.")
    if not ref:
        return Outcome.refused("no_ref", "That link does not say which record it points at.")
    label = ctx.arg("label") or ref
    if not may_open(ctx, kind, ref):
        # Never shown to this conversation. Refused before anything is read, which is both the
        # safe answer and the cheap one — and with somewhere to go, because on a divided orb
        # this refusal reached a half whose owner had no way to find out what it did have.
        return Outcome.refused(
            "not_held", "That one was not opened in this conversation. Open the list it is on and tap it there.",
            changed={"offer": offer_for(ctx.branch), "holds": _holds(ctx.branch)},
        )
    calls = replay(ctx, kind, ref)
    if not calls and kind not in REPLAY_TOOL:
        return Outcome.refused(
            "not_held", f"I cannot open a {kind} on its own. Open the list it is on and tap it there.",
            changed={"offer": offer_for(ctx.branch), "holds": _holds(ctx.branch)},
        )
    ctx.branch.visit(kind, ref, label)
    changed: dict[str, Any] = {
        "entity": {"kind": kind, "ref": ref, "label": label}, "replayed": bool(calls),
    }
    if not calls:
        changed["needs_read"] = {"kind": kind, "ref": ref, "set_kind": _SET_KIND.get(kind, "")}
    return Outcome(answer=f"{label}.", calls=calls, changed=changed)


register(Command("open.entity", "Open a linked record", _open_entity, voice=False))


# --------------------------------------------------------------------------- the surface


def _select_tab(ctx: Ctx) -> Outcome:
    """Which part of the open record is showing.

    The selected tab is held on the Mac rather than in the DOM alone, so it survives a
    reload, a branch switch and a Back, and so "show me the shipping" and a tap on Shipping
    are the same operation.

    It is held against the RECORD, not the half (D-2): a tab is a fact about the thing the
    owner is reading, and treating it as a fact about the branch put every later card on the
    last tab he happened to tap. `mark` files it under the record this half is standing on.
    """
    surface, tab = ctx.arg("surface"), ctx.arg("tab").lower()
    allowed = TABS.get(surface or _surface_of(ctx), ())
    if not allowed:
        return Outcome.refused("no_tabs", "That screen has no tabs.")
    if tab not in allowed:
        return Outcome.refused("unknown_tab", f"That screen has no {tab!r} tab.")
    ctx.branch.mark(tab=tab)
    return Outcome(answer="", changed={"tab": tab})


def _surface_of(ctx: Ctx) -> str:
    entity = getattr(ctx.branch, "entity", None) or {}
    return str(entity.get("kind") or "")


def _expand_row(ctx: Ctx) -> Outcome:
    """A row opened in place. Recorded on the branch so a Back that returns here returns to
    the same shape of screen, rather than to a list that has forgotten what was open."""
    ref = ctx.arg("ref")
    if not ref:
        return Outcome.refused("no_ref", "That row does not say which record it is.")
    expanded = list(getattr(ctx.branch, "expanded", []) or [])
    if ref in expanded:
        expanded.remove(ref)
    else:
        expanded.append(ref)
    ctx.branch.mark(expanded=expanded[-12:])
    return Outcome(answer="", changed={"expanded": list(ctx.branch.expanded)})


def _scrolled(ctx: Ctx) -> Outcome:
    """How far down the screen is, kept against the stop it belongs to.

    A depth is the same sort of thing a tab is: a small value about the screen, not an
    execution argument, and the Mac decides what it means. It is here because the brief asks
    Back to restore the position "where practical", and the tablet is the only thing that
    knows how far down a thumb pushed the cards. Nothing is read and nothing changes.
    """
    raw = ctx.arg("depth") or ctx.arg("scroll")
    try:
        depth = max(0, min(int(float(raw)), 100_000))
    except ValueError:
        return Outcome.refused("no_depth", "That does not say how far down the screen is.")
    ctx.branch.mark(scroll=depth)
    return Outcome(answer="", changed={"scroll": depth})


register(Command("surface.tab", "Show one part of the open record", _select_tab))
register(Command("surface.expand", "Open a row where it sits", _expand_row, voice=False))
register(Command("surface.scroll", "How far down the screen is", _scrolled, voice=False))
# Shortcuts on the order and customer cards. Each is the tab command with its argument fixed,
# so there is one implementation of "show the shipping".
register(Command("order.open_shipping", "The shipping on this order",
                 lambda ctx: _select_tab(Ctx(ctx.runtime, ctx.session, ctx.branch, {"surface": "order", "tab": "shipping"})),
                 needs_entity=("order",)))
register(Command("order.open_items", "What is on this order",
                 lambda ctx: _select_tab(Ctx(ctx.runtime, ctx.session, ctx.branch, {"surface": "order", "tab": "items"})),
                 needs_entity=("order",)))
register(Command("customer.open_orders", "What this customer has ordered",
                 lambda ctx: _select_tab(Ctx(ctx.runtime, ctx.session, ctx.branch, {"surface": "customer", "tab": "orders"})),
                 needs_entity=("customer",)))


# --------------------------------------------------------------------------- the halves


def _branch_show(ctx: Ctx) -> Outcome:
    """What a half is looking at, drawn again.

    Tapping a half is switching workspaces: the Mac focuses it AND the tablet draws that
    half's screen. The screen is what the half last presented (`Branch.last_ui`) — the cards
    it answered with, the sentence, the question — so a half that finished while the owner
    was talking to the other one shows its answer the moment it is tapped, and a reloaded
    tablet gets its place back. Nothing is read and nothing is staged: this is presentation
    the Mac already made, handed over again.

    A half that has never presented anything draws NOTHING, and this is the whole of D-3. It
    used to rebuild its parent's record from memory, which is how a fork produced two screens
    the owner could not tell apart — he tapped between them six times in nine seconds and then
    said the feature did not work. What it returns instead is what this half holds and what can
    be done with it, and the tablet draws that: a header, and controls.

    The headline goes out on every answer, empty or not, because an identical pair of cards on
    two halves is legitimate — two views of the same order — and the identity of the half must
    be unmistakable even then.
    """
    wanted = ctx.arg("branch_id") or ctx.branch.branch_id
    branch = ctx.session.branches.get(wanted) if isinstance(getattr(ctx.session, "branches", None), dict) else None
    if branch is None:
        return Outcome.refused("unknown_branch", "There is no such half in this conversation.")
    if branch.status in ("MERGED", "CANCELLED"):
        return Outcome.refused("branch_closed", f"That half is {branch.status.lower()}.")
    common = {"branch_id": branch.branch_id, "headline": branch.headline(),
              "state": branch.state(), "status": branch.status,
              "task": dict(branch.task) if branch.task else None}
    ui = list(branch.last_ui)
    if not ui and not branch.last_answer:
        return Outcome(answer=_empty_words(branch),
                       changed={**common, "empty": True, "holds": _holds(branch), "offer": offer_for(branch)})
    # `common` already carries the task, the headline, the state and the status.
    return Outcome(answer=branch.last_answer, surfaces=[AsUi(u) for u in ui],
                   changed={**common, "question": branch.last_question})


def _empty_words(branch: Any) -> str:
    """What a half with nothing on it says, and it says what it HAS — the sentence the forked
    half never got to say in the live session, where it refused twice instead."""
    entity = getattr(branch, "entity", None) or {}
    label = str(entity.get("label") or "").strip()
    if label:
        return f"This half holds nothing on screen yet. It starts from {label}."
    return "This half holds nothing yet. Open a place, or ask it something."


class AsUi:
    """A presented card handed back as it was. `present()` is not run again on it."""

    __slots__ = ("item",)

    def __init__(self, item: dict[str, Any]) -> None:
        self.item = item

    def as_ui(self) -> dict[str, Any]:
        return dict(self.item)


register(Command("branch.show", "What that half is looking at", _branch_show, voice=False))


# --------------------------------------------------------------------------- touch, then voice

# The controls that expect words rather than a decision. Tapping one of these does not do
# anything on its own — it says what the next sentence is about, and starts listening. The
# sentence then goes to the model with the control and its record beside it
# (app/routes/turn.py), and the model decides whether the words are for that control.
SPOKEN_CONTROLS: dict[str, tuple[str, str]] = {
    "email.rewrite": ("email_thread", "Rewrite this"),
    "email.reply": ("email_thread", "Reply to this"),
    "order.add_note": ("order", "Add a note"),
    "order.change_address": ("order", "Change the address"),
    "customer.ask": ("customer", "Ask about this customer"),
    "set.filter": ("set", "Narrow these"),
}

# What the screen says while it listens: what the NEXT SENTENCE will do, and to whom. Short,
# because it sits on an 8-inch screen beside the control that was tapped; never the thread's
# subject line, which is what clipped on the bench ("Reply to this · Order #1938 — can I add
# to it?" in a band that could not wrap).
_PHRASES: dict[str, str] = {
    "email.reply": "Replying to {who}",
    "email.rewrite": "Rewriting the draft",
    "order.add_note": "Adding a note to {label}",
    "order.change_address": "Changing the address on {label}",
    "customer.ask": "Asking about {who}",
    "set.filter": "Narrowing these",
}


def _first_name(text: str) -> str:
    word = str(text or "").strip().split(",")[0].strip().split(" ")[0].strip(" <>\"'")
    return word if word and "@" not in word else ""


def _who_for(kind: str, ref: str, label: str) -> str:
    """Who the sentence is for, in one word, from what the Mac already holds."""
    from app.memory import ENTITY
    from app.memory import current as memory

    held = memory().get(ENTITY, f"{kind}:{ref}", allow_stale=True)
    value = held.value if held is not None and isinstance(getattr(held, "value", None), dict) else {}
    if kind == "email_thread":
        messages = [m for m in (value.get("messages") or []) if isinstance(m, dict)]
        for m in reversed(messages):
            if not m.get("outbound") and m.get("from"):
                return _first_name(str(m["from"]))
        if messages and messages[-1].get("from"):
            return _first_name(str(messages[-1]["from"]))
        return ""
    if kind == "customer":
        return _first_name(str(value.get("name") or label or ""))
    if kind == "order":
        return _first_name(str(value.get("customer_name") or ""))
    return ""


def listening_phrase(family: str, *, kind: str, ref: str, label: str) -> str:
    template = _PHRASES.get(family, "Listening")
    who = _who_for(kind, ref, label) if "{who}" in template else ""
    if "{who}" in template and not who:
        return template.replace(" {who}", " this email" if kind == "email_thread" else " them")
    return template.format(who=who, label=(label if str(label).startswith("#") else (f"#{label}" if str(label).isdigit() else label or "this")))


def _same_record(kind: str, one: str, other: str) -> bool:
    """One record however its id arrived: a gid and the same gid said another way are one."""
    from app import entities

    return bool(one and other) and (entities.key(kind, one) or f"{kind}:{one}") == (entities.key(kind, other) or f"{kind}:{other}")


def _bound_label(kind: str, ref: str, entity: dict[str, Any]) -> str:
    """The Mac's own name for the record a tap bound — the words the glass says it is listening
    for, and the name the model is handed beside the id.

    The cursor's label when the tap bound the cursor; otherwise the label of the copy the Mac
    holds of the record named, in the form its card uses ("#1940", a name, a subject); otherwise
    nothing, and the phrase says "this". Never the cursor's label for another record, and never a
    word the tablet posted: either could put one order's name on a binding to another."""
    if str(entity.get("kind") or "") == kind and _same_record(kind, ref, str(entity.get("ref") or "")):
        return str(entity.get("label") or "")
    from app.memory import ENTITY
    from app.memory import current as memory

    held = memory().get(ENTITY, f"{kind}:{ref}", allow_stale=True)
    value = held.value if held is not None and isinstance(getattr(held, "value", None), dict) else {}
    if kind == "order":
        digits = re.search(r"(\d+)\s*$", str(value.get("order_number") or ""))
        return f"#{digits.group(1)}" if digits else ""
    return str(value.get({"customer": "name", "email_thread": "subject"}.get(kind, "")) or "")[:120]


def _bind_voice(ctx: Ctx) -> Outcome:
    """A control was tapped that expects words. Bind what they will apply to, and listen.

    Nothing is changed and nothing is proposed here. The owner has said what he is about to
    talk about, which is a fact about the conversation, not an instruction — the instruction
    is the sentence that follows, and it goes through /turn like every other sentence.

    What is bound is the record the tap named, else the half's cursor — and only a record this
    conversation was shown (`may_open`, the rule `open.entity` and every tool call keep). It took
    any id the tablet posted: the next sentence was armed for a record the conversation was never
    issued, and the listening phrase was built from the Mac's process-wide copy of it. And it is
    called by its own name (`_bound_label`): a tap naming #1940 while the cursor was #1938 took the
    cursor's name, so the glass said "Adding a note to #1938" over a binding to #1940 and the model
    was told the same (the 2026-09-28 deploy review, round 9, D1-02 and D2-04).
    """
    family = ctx.arg("family")
    if family not in SPOKEN_CONTROLS:
        return Outcome.refused("unknown_control", f"There is no spoken control called {family!r}.")
    wants_kind, label = SPOKEN_CONTROLS[family]
    entity = getattr(ctx.branch, "entity", None) or {}
    kind = ctx.arg("kind") or str(entity.get("kind") or "")
    ref = ctx.arg("ref") or str(entity.get("ref") or "")
    if wants_kind == "set":
        entity_label = ctx.arg("label") or str(entity.get("label") or "")
    else:
        if kind != wants_kind or not ref:
            return Outcome.refused("no_target", f"There is no {wants_kind.replace('_', ' ')} open to do that to.")
        if not may_open(ctx, kind, ref):
            # Refused before the record is looked at, so the refusal says nothing about it.
            return Outcome.refused(
                "not_held", "That one was not opened in this conversation, so there is nothing to say it to.",
                changed={"offer": offer_for(ctx.branch), "holds": _holds(ctx.branch)},
            )
        entity_label = _bound_label(kind, ref, entity)
    phrase = listening_phrase(family, kind=kind, ref=ref, label=entity_label)
    bound = ctx.branch.bind_voice(family, kind=kind, ref=ref, label=entity_label, prompt=label, phrase=phrase)
    return Outcome(answer="", changed={"listening_for": {"family": family, "label": bound.get("label", ""),
                                                         "prompt": label, "phrase": phrase}, "expires_at": bound.get("expires_at")})


def _release_voice(ctx: Ctx) -> Outcome:
    ctx.branch.release_voice()
    return Outcome(answer="", changed={"listening_for": None})


register(Command("voice.bind", "Say what the next sentence is about", _bind_voice, voice=False))
register(Command("voice.cancel", "Stop waiting for words", _release_voice, voice=False))


def public() -> list[dict[str, Any]]:
    """The command table, for the capability manifest and the feature matrix. Derived from the
    registry so the matrix cannot claim a command that does not exist."""
    return [
        {"name": c.name, "what": c.what, "voice": c.voice, "touch": c.touch,
         "needs_entity": list(c.needs_entity), "needs_workflow": c.needs_workflow,
         # A control that binds a continuation is reached by touch and completed by voice.
         "touch_then_voice": c.name == "voice.bind"}
        for c in sorted(REGISTRY.values(), key=lambda c: c.name)
    ]
