"""What is on the owner's screen, and keeping it there (round 12).

George, 29 September: "A task is asked, a screen is shown, an edit is asked, the edit succeeds,
however the screen disappears. This is a persistent issue."

It was persistent because nothing held the screen. Every answer was drawn from its own cards
and nothing else, so an answer whose only card was the change — the note waiting for his tap,
the refusal, the proof — drew that card alone and the order he was working on went with the
screen before it. An answer in words drew nothing at all, and the tablet went home.

The rule here is the owner's own, and it is the whole of this module:

    The only things that clear the screen are his own close or back, a genuinely new subject
    that replaces it, and the privacy rules that already exist.

So an answer CONTINUES the screen the half is showing when it brings no new subject: when every
record card it has is a record already on that screen, and every change card it has — the card
before the gesture, a refusal, a step towards a change — is about something on that screen (or,
like a refusal, about nothing in particular). A continuation is sent as the change cards first,
where his eye goes, and then the screen as it stood: the cards the answer did not touch marked
`kept` (the card already on the glass; the tablet leaves its node exactly where it is) and a
record the answer read again marked `refreshed` (drawn again in its own place). A change card
about some other record is not a continuation: an order must never stand over a card that
changes a different one.

What the half is showing is the Mac's own copy of it (`Branch.last_ui`, written by every turn,
tap and gesture that draws), and it is only trusted while it is recent: the tablet forgets its
cards after thirty minutes without use (web/app.js `DECK_IDLE_MS`) and so does this. Nothing
here reads the shop, stages anything or decides what may be shown: every card it carries was
already drawn for this conversation, and a record redrawn after a proven change is the read the
action engine made to prove it.
"""

from __future__ import annotations

import copy
import logging
import re
import time
from collections.abc import Mapping
from typing import Any

from app.render import render_id

log = logging.getLogger("crooks.screen")

# How long a half's screen is still his screen with nothing done on it. The tablet's own rule,
# said once more here: web/app.js `DECK_IDLE_MS`, thirty minutes, after which the deck is
# cleared so that a customer's name and address do not stay on a desk-top tablet all night.
SCREEN_IDLE_S = 30 * 60

# The cards that record a change — the card waiting for the gesture, the proof after it, a
# refusal — and the one step towards a change that is drawn as a card of its own (which
# variant). None of them is a subject: each is ABOUT a record, and the record is the screen.
CHANGE_CARDS = frozenset({
    "confirmation", "batch_action", "success", "batch_result", "error", "email_draft", "variant_picker",
})
# Cards that are the tablet's bookkeeping rather than something on the glass.
BOOKKEEPING = frozenset({"context_stack", "workspace_plan"})

# Where a card keeps the id of what it is about. Read as plain strings: a gid on one card and the
# same gid on another are the same record, and a thread id, a set id and a workspace id are each
# unique in their own shape.
_ID_FIELDS = ("order_id", "customer_id", "thread_id", "ref", "workspace_id", "compose_id", "set_id",
              "objective_id", "for", "product_id")
# The lists a card carries its rows in, and the id each row keeps.
_ROWS = ("orders", "customers", "threads", "rows", "products", "members")
MAX_KEPT = 6


# --------------------------------------------------------------------------- what a card is


def kind(item: Any) -> str:
    return str(item.get("type") or "") if isinstance(item, dict) else ""


def is_subject(item: Any) -> bool:
    """A card that is a screen of its own: a record, a list, a workspace, a summary. Everything
    that is not a change card and not bookkeeping."""
    return bool(kind(item)) and kind(item) not in CHANGE_CARDS and kind(item) not in BOOKKEEPING


def record_of(item: Any) -> tuple[str, str] | None:
    """(kind, canonical id) of the one record a card is, or None for a card that is not one.

    An order card and the order's workspace are the same record, as `app/routes/turn.py` holds
    for the half's cursor; so are a customer card and the customer's workspace, and a thread.
    """
    from app import entities

    if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
        return None
    data, card = item["data"], kind(item)
    if data.get("empty"):
        return None
    if card == "order":
        found = ("order", data.get("order_id") or data.get("order_number"))
    elif card == "customer":
        found = ("customer", data.get("customer_id"))
    elif card == "email_thread":
        found = ("email_thread", data.get("thread_id"))
    elif card in ("order_workspace", "customer_workspace"):
        found = (str(data.get("kind") or ""), data.get("ref"))
    else:
        return None
    key = entities.key(found[0], found[1]) if found[0] and found[1] else ""
    return (found[0], key) if key else None


def identity(item: dict[str, Any]) -> str:
    """Which card this is on the glass: the record for a record card, else its render id."""
    record = record_of(item)
    return f"record:{record[1]}" if record else render_id(item)


def recallable(item: Any) -> bool:
    """A card worth bringing back: something he was looking at or working in — a record, a
    workspace, a list, a composer — or the draft a change saved. Not a card about a change
    still to come or already refused, and never an empty answer or a placeholder."""
    if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
        return False
    data = item["data"]
    if data.get("empty") or data.get("shell"):
        return False
    return is_subject(item) or kind(item) == "email_draft"


def refs_on(items: list[dict[str, Any]]) -> set[str]:
    """Every id the cards on a screen are about, their rows' included. What a change card has
    to be about for the screen to be the screen it belongs on."""
    out: set[str] = set()

    def take(data: Any) -> None:
        if not isinstance(data, dict):
            return
        for name in _ID_FIELDS:
            value = data.get(name)
            if isinstance(value, (str, int)) and str(value).strip():
                out.add(str(value).strip())
        for name in _ROWS:
            rows = data.get(name)
            # `orders` is a list of rows on a list card and a count on a customer's.
            for row in rows if isinstance(rows, list) else []:
                if isinstance(row, dict):
                    for field in ("order_id", "customer_id", "thread_id", "ref", "product_id"):
                        value = row.get(field)
                        if isinstance(value, (str, int)) and str(value).strip():
                            out.add(str(value).strip())

    for item in items or []:
        data = item.get("data") if isinstance(item, dict) else None
        take(data)
        if isinstance(data, dict):
            for section in (data.get("sections") or {}).values() if isinstance(data.get("sections"), dict) else []:
                for row in (section.get("rows") or []) if isinstance(section, dict) else []:
                    take(row)
            take(data.get("set"))
    return out


def about(change: dict[str, Any], session: Any = None) -> set[str]:
    """What a change card is about, as ids. Empty for a card about nothing in particular — a
    refusal says what went wrong, not which record it went wrong on."""
    data = change.get("data") if isinstance(change.get("data"), dict) else {}
    card = kind(change)
    if card == "confirmation":
        return ({str(data.get("entity_ref") or "")} | _prepared_from(data, session)) - {""}
    if card == "batch_action":
        scope = data.get("set") if isinstance(data.get("set"), dict) else {}
        return {str(scope.get("set_id") or "")} - {""}
    if card == "variant_picker":
        return {str(data.get("order_id") or "")} - {""}
    if card == "success" and session is not None:
        proposal = session.proposal(str(data.get("proposal_id") or ""))
        return ({str(getattr(proposal, "entity_ref", "") or "")} | _prepared_from(data, session)) - {""}
    return set()


def _prepared_from(data: dict[str, Any], session: Any) -> set[str]:
    """The workspace a change was prepared from, when it was one. A new order is priced as a
    draft, and its hold card is about that draft — which no card on the screen shows — so,
    taken at its word, the card was "about something else" and replaced the order being built
    (round 12's independent check, H). It is as much about the card it was prepared from."""
    if session is None:
        return set()
    proposal = session.proposal(str(data.get("proposal_id") or ""))
    execution = getattr(proposal, "execution", None)
    return {str(execution.get("workspace_id") or "")} if isinstance(execution, Mapping) else set()


# ---------------------------------------------------------------------- what the half shows


def showing(branch: Any, *, clock=time.time) -> list[dict[str, Any]]:
    """The cards this half has on the owner's screen, as the Mac last drew them — or nothing,
    when that was long enough ago that the tablet has cleared them itself."""
    if branch is None:
        return []
    last_at = float(getattr(branch, "last_at", 0.0) or 0.0)
    if not last_at or clock() - last_at > SCREEN_IDLE_S:
        return []
    return [item for item in (getattr(branch, "last_ui", None) or [])
            if isinstance(item, dict) and kind(item) and kind(item) not in BOOKKEEPING]


def _still_live(item: dict[str, Any], session: Any) -> bool:
    """A change card that is still something the owner can act on: a card waiting for his
    gesture, a step towards a change, or a proof that still offers its undo. A refusal, a
    withdrawn card and a proof whose undo has lapsed are over, and a new answer lets them go."""
    if session is None:
        return False
    data = item.get("data") if isinstance(item.get("data"), dict) else {}
    card = kind(item)
    if card == "confirmation":
        proposal = session.proposal(str(data.get("proposal_id") or ""))
        return proposal is not None and proposal.status.value == "PENDING" and not proposal.expired()
    if card == "batch_action":
        batch = (getattr(session, "batches", None) or {}).get(str(data.get("batch_id") or ""))
        return batch is not None and getattr(batch.status, "value", "") == "PENDING"
    if card == "success":
        proposal = session.proposal(str(data.get("proposal_id") or ""))
        undo = session.proposal(str(getattr(proposal, "undo_id", "") or "")) if proposal is not None else None
        return undo is not None and undo.status.value == "PENDING" and not undo.expired()
    return card == "variant_picker"


def _flagged(item: dict[str, Any], flag: str) -> dict[str, Any]:
    """A copy of a card with its continuation flag. A copy, because the half's own record of
    its screen is not to be changed by what is sent."""
    out = {k: v for k, v in copy.deepcopy(item).items() if k not in ("kept", "refreshed")}
    out[flag] = True
    return out


def plain(item: dict[str, Any]) -> dict[str, Any]:
    """A card without its continuation flags, as the half keeps it."""
    return {k: v for k, v in item.items() if k not in ("kept", "refreshed")}


def _fuller(fresh: dict[str, Any], shown: dict[str, Any]) -> bool:
    """Whether the answer's card of a record says at least as much as the one on the screen.
    An order found by a search is a line; the same order read in full, or composed as its
    workspace, is the screen he was working on, and a search must not shrink it. The other way
    round holds too: the record he had up as its card, composed by this answer as its workspace
    ("her orders, and is she in Gmail"), is the workspace he asked for."""
    if kind(fresh) in _WORKSPACE_READ and kind(shown) != kind(fresh):
        return True
    if kind(fresh) != kind(shown):
        return False
    if kind(fresh) == "order":
        return bool((fresh.get("data") or {}).get("detail")) or not bool((shown.get("data") or {}).get("detail"))
    return True


# ---------------------------------------------------------------------------- the rule


def carry(ui: list[dict[str, Any]], *, branch: Any, session: Any = None, calls: Any = None,
          named: frozenset[str] | set[str] = frozenset(), clock=time.time) -> list[dict[str, Any]]:
    """The answer, continuing the half's screen when it brings no new subject (module docstring).

    Returns `ui` itself, untouched, whenever the answer is a screen of its own: a record the
    half is not showing, a list, a change about something else — or when the half shows
    nothing to continue. Never raises: a screen that cannot be continued is drawn as the
    answer alone, which is what it always was.

    Two more things make an answer about something else, and both are what was DONE, checked
    after the model (`app/routes/turn.py` computes `named` for its own write boundary): the
    owner named an order that is not on the screen ("where is 1940" with #1938 up), or the
    model read a record that is not on it and drew no card for it. An answer about #1940 in
    words must not stand over #1938's card, where it would read as #1938's (round 9, D2-05).
    """
    try:
        return _carry(ui, branch=branch, session=session, calls=calls, named=named, clock=clock)
    except Exception as exc:  # noqa: BLE001 — never at the cost of the turn
        log.warning("the screen could not be carried: %s", type(exc).__name__)
        return ui


def _carry(ui, *, branch, session, calls, named, clock) -> list[dict[str, Any]]:
    answer = [item for item in (ui or []) if isinstance(item, dict)]
    screen = showing(branch, clock=clock)
    screen_subjects = [item for item in screen if is_subject(item)]
    if not screen_subjects:
        return ui
    held = {identity(item): item for item in screen_subjects}
    fresh: dict[str, dict[str, Any]] = {}
    for item in answer:
        if not is_subject(item):
            continue
        who = identity(item)
        if who not in held:
            return ui                      # a new subject: it is the screen now
        fresh[who] = item
    changes = [item for item in answer if kind(item) in CHANGE_CARDS]
    on_screen = refs_on(screen)
    for change in changes:
        wanted = about(change, session)
        if wanted and not (wanted & on_screen):
            return ui                      # a change to something else is not drawn over this
    if _named_elsewhere(named, screen) or _read_elsewhere(calls, on_screen):
        return ui
    new_ids = {render_id(item) for item in changes}
    changed_refs: set[str] = set()
    for change in changes:
        changed_refs |= about(change, session)
    kept: list[dict[str, Any]] = []
    for item in screen:
        if is_subject(item):
            counterpart = fresh.get(identity(item))
            if counterpart is not None and _fuller(counterpart, item):
                kept.append(_flagged(counterpart, "refreshed"))
            elif counterpart is not None:
                kept.append(_recomposed(item, counterpart, session) or _flagged(item, "kept"))
            else:
                kept.append(_flagged(item, "kept"))
        elif render_id(item) not in new_ids and _still_live(item, session):
            if kind(item) == "variant_picker" and changed_refs & refs_on([item]):
                continue                   # the step is done: its change is the card now
            kept.append(_flagged(item, "kept"))
    bookkeeping = [item for item in answer if kind(item) in BOOKKEEPING]
    return changes + kept[:MAX_KEPT] + bookkeeping


_NUMBER = re.compile(r"(\d{3,7})\s*$")


def numbers_on(screen: list[dict[str, Any]]) -> set[str]:
    """The order NUMBERS a screen shows — "1940" from "#1940", "CROOKS-1940" or "Order #1940" —
    on a card, a workspace's title or a list's rows. A number, never an order's id: the id is
    the shop's own and is not the number the owner says."""
    out: set[str] = set()

    def number(value: Any) -> None:
        found = _NUMBER.search(str(value or ""))
        if found:
            out.add(found.group(1))

    for item in screen or []:
        data = item.get("data") if isinstance(item, dict) and isinstance(item.get("data"), dict) else {}
        if kind(item) == "order":
            number(data.get("order_number"))
        elif kind(item) == "order_workspace":
            number(data.get("title"))
        rows = data.get("orders") if isinstance(data.get("orders"), list) else data.get("rows")
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict):
                number(row.get("order_number"))
    return out


def _named_elsewhere(named: Any, screen: list[dict[str, Any]]) -> bool:
    """Whether the owner named an order (by its number) that this screen does not show."""
    return bool(named) and bool(set(named) - numbers_on(screen))


# The kinds of record a screen of this module shows, and where a read's result names one.
_RECORD_FIELDS = ("order_id", "customer_id", "thread_id")


def _read_elsewhere(calls: Any, on_screen: set[str]) -> bool:
    """Whether this answer's reads were about a record the screen does not show. A change being
    prepared is not a read, and a read of the record on the screen, or of one its cards name
    (the order's customer, the thread's order), is still about this screen."""
    for call in calls or []:
        result = getattr(call, "result", None)
        if not getattr(call, "ok", False) or getattr(call, "proposal_id", None) or not isinstance(result, dict):
            continue
        for field in _RECORD_FIELDS:
            value = result.get(field)
            if isinstance(value, str) and value.strip() and value.strip() not in on_screen:
                return True
    return False


def _recomposed(shown: dict[str, Any], read: dict[str, Any], session: Any) -> dict[str, Any] | None:
    """A record the half shows as its workspace, read again as a plain card: the workspace,
    composed again from what the conversation now holds of it — this turn's read is already in
    the conversation's graph (`present()` folds every read in) — rather than the workspace
    swapped for a plainer card of the same record. None when it cannot be."""
    if kind(shown) not in _WORKSPACE_READ or session is None:
        return None
    if kind(read) == "order" and not (read.get("data") or {}).get("detail"):
        return None                        # a search's line says less than the workspace does
    rebuilt = recompose(shown, None, session=session)
    return _flagged(rebuilt, "refreshed") if rebuilt is not None else None


# The read each composed workspace is made from, and where that read keeps the record's id.
_WORKSPACE_READ = {
    "order_workspace": ("shopify_order_detail", "order_id"),
    "customer_workspace": ("shopify_customer_history", "customer_id"),
}


def recompose(shown: dict[str, Any], read: dict[str, Any] | None, *, session: Any) -> dict[str, Any] | None:
    """A record's workspace composed again, on the sections and the tab it was showing, from
    the conversation's graph — with `read` folded in first when it is a fresh read of the
    record as its read tool returns it (the action engine's proving read of an order, or a
    read `show_again` made). None when the workspace cannot be composed, and the caller then
    draws what it has."""
    from app import entities, workspace

    card = kind(shown)
    if card not in _WORKSPACE_READ:
        return None
    tool_name, field = _WORKSPACE_READ[card]
    data = shown.get("data") if isinstance(shown.get("data"), dict) else {}
    ref, record_kind = str(data.get("ref") or ""), str(data.get("kind") or card.removesuffix("_workspace"))
    if not ref or (read is not None and ref != str(read.get(field) or "")):
        return None
    try:
        graph = entities.graph_for(session)
        if isinstance(read, dict):
            graph.ingest(tool_name, read)
        sections = data.get("sections") if isinstance(data.get("sections"), dict) else {}
        filled = {name for name, section in sections.items()
                  if isinstance(section, dict) and section.get("state") in ("ready", "empty")}
        filled |= set(entities.FILLS.get(tool_name, ()))
        plan = workspace.Plan(kind=record_kind, key=entities.key(record_kind, ref), ref=ref,
                              tab=str(data.get("tab_intended") or data.get("tab") or "overview"),
                              tab_reason=str(data.get("tab_reason") or ""), whole=True)
        return workspace.compose(plan, graph=graph, session=session, filled=filled)
    except Exception as exc:  # noqa: BLE001 — the plainer card still says what is true
        log.warning("could not compose the workspace again: %s", type(exc).__name__)
        return None


# ------------------------------------------------------------------ after the gesture


#: What an answer does to the half's screen, said to the tablet on every /turn (`screen`).
SCREEN_KEPT, SCREEN_NEW, SCREEN_CLEARED = "kept", "new", "cleared"


def state_of(ui: list[dict[str, Any]]) -> str:
    """Whether the half's screen stands, is replaced, or goes, from the answer as it will be
    sent (round 12, the second pass). The tablet obeys this and guesses nothing.

      kept     the answer carries the screen on: cards it kept or read again are in it;
      new      the answer's cards are a screen of their own;
      cleared  the answer drew nothing and carries nothing on — words about another order
               (round 9's D2-05), a screen he closed, or nothing up to begin with.
    """
    cards = [item for item in ui or [] if isinstance(item, dict) and kind(item) and kind(item) not in BOOKKEEPING]
    if not cards:
        return SCREEN_CLEARED
    if any(item.get("kept") or item.get("refreshed") for item in cards):
        return SCREEN_KEPT
    return SCREEN_NEW


def listening_on_cursor(ui: list[dict[str, Any]], entity: Any) -> list[dict[str, Any]]:
    """The cards, with a listening control only on the card whose record is the half's cursor.

    A rail chip in "ask" mode that names a spoken control (`family`, e.g. order.add_note) binds
    the next sentence to the half's CURSOR, not to the card it is drawn on (web/app.js
    `primeAction`). On any other card it would bind a record other than the one under his
    thumb, so there it loses its `family`: a tap still primes its words, which name that card's
    own record ("Add a note to #1940"), and the model reads the record from the words. With no
    cursor, no card listens.

    Every path that hands the tablet cards goes through here — a sentence, a tap, a hold, a
    row's action — because each can change which card is the cursor's, or redraw a record
    with a fresh rail (the round-12 independent check, C3). And a card the glass keeps is never
    redrawn there, so one that loses its chip here is sent `refreshed` instead of `kept`: the
    live chip on the glass is replaced, not left bound to a record that is no longer the cursor.
    Returns new items; the ones it does not change are the same objects.
    """
    from app import entities

    here = entity if isinstance(entity, dict) else {}
    kind_here, ref_here = str(here.get("kind") or ""), str(here.get("ref") or "")
    cursor = (entities.key(kind_here, ref_here) or f"{kind_here}:{ref_here}") if kind_here and ref_here else ""
    out: list[dict[str, Any]] = []
    for item in ui or []:
        record = record_of(item)
        data = item.get("data") if isinstance(item, dict) and isinstance(item.get("data"), dict) else None
        actions = data.get("actions") if data is not None and isinstance(data.get("actions"), list) else []
        live = [a for a in actions if isinstance(a, dict) and a.get("family") and str(a.get("mode") or "ask") == "ask"]
        if record is None or not live or (cursor and record == (kind_here, cursor)):
            out.append(item)
            continue
        quiet = [{**a, "family": ""} if any(a is x for x in live) else a for a in actions]
        fixed = {k: v for k, v in item.items() if k not in ("kept", "refreshed")}
        fixed["data"] = {**data, "actions": quiet}
        if item.get("kept") or item.get("refreshed"):
            fixed["refreshed"] = True
        out.append(fixed)
    return out


def _focused(session: Any) -> Any:
    """The half the owner is on, when no half's screen holds the card a gesture was made on."""
    try:
        return session.branch()
    except Exception:  # noqa: BLE001 — no half means no cursor, and then nothing listens
        return None


def _holding(session: Any, targets: set[str]) -> Any:
    """The half whose screen holds the card a gesture was made on."""
    for branch in (getattr(session, "branches", None) or {}).values():
        if any(render_id(item) in targets for item in (getattr(branch, "last_ui", None) or []) if isinstance(item, dict)):
            return branch
    return None


def after_gesture(items: list[dict[str, Any]], *, session: Any, proposal_id: str, undo_of: str = "",
                  entity: Any = None, entity_kind: str = "", writes: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """The answer to a gesture, and the half's screen settled to match it.

    The answer keeps its shape — the proof or the refusal first, then the record as the proof
    re-read it — with two corrections. A record the half shows as its WORKSPACE comes back as
    that workspace, composed again from the proving read, not as a plainer card of the same
    record. And a re-read order carries its rail again (what can be done next is part of its
    new state), which the proof's card did not.

    The half's own copy of its screen then becomes what the tablet now draws: the card the
    gesture was made on replaced by the answer's new cards, in its place, and every record the
    answer re-read replaced where it stands. Nothing else on that screen moves. A gesture on a
    card no half is showing any more changes no half's screen.
    """
    if session is None:
        return items
    targets = {f"confirmation:{proposal_id}", f"batch_action:{proposal_id}"}
    if undo_of:
        # An undo is made on the proof of the change it reverses.
        targets |= {f"success:{undo_of}", f"batch_result:{undo_of}"}
    branch = _holding(session, targets)
    screen = list(getattr(branch, "last_ui", None) or []) if branch is not None else []
    out = [_with_rail(item, entity if entity_kind == "order" else None, writes) for item in items]
    built = _built_from(session, proposal_id, branch)
    if built is not None:
        # The card the change was prepared from, drawn again as it now is — a new order that has
        # made its order says so, by its number, where it stands (round 12, A1).
        out = [item for item in out if render_id(item) != render_id(built)] + [built]
    shown_workspace = next((item for item in screen if kind(item) == "order_workspace"), None)
    if shown_workspace is not None and entity_kind == "order" and isinstance(entity, dict):
        for index, item in enumerate(out):
            if kind(item) == "order" and str((item.get("data") or {}).get("order_id") or "") == str((shown_workspace.get("data") or {}).get("ref") or ""):
                rebuilt = recompose(shown_workspace, entity, session=session)
                if rebuilt is not None:
                    out[index] = rebuilt
    # A record re-read with a fresh rail listens only if it is the half's cursor (C3): #1940
    # redrawn after a note while #1938 is the cursor must not offer a chip that binds #1938.
    half = branch if branch is not None else _focused(session)
    out = listening_on_cursor(out, getattr(half, "entity", None))
    if branch is not None:
        settled = settle(screen, out, targets)
        if settled is not None:
            branch.shown(settled, branch.last_answer, branch.last_question)
    return out


def _built_from(session: Any, proposal_id: str, branch: Any) -> dict[str, Any] | None:
    """The workspace a gesture's change was prepared from, drawn by its family as it is after the
    gesture — or None when the change was not prepared from one, or its half no longer holds it."""
    proposal = session.proposal(proposal_id) if hasattr(session, "proposal") else None
    execution = getattr(proposal, "execution", None)
    ident = str(execution.get("workspace_id") or "") if isinstance(execution, Mapping) else ""
    if not ident:
        return None
    half = branch or (getattr(session, "branches", None) or {}).get(str(getattr(proposal, "branch_id", "") or ""))
    if half is None:
        return None
    from app.families import _workspace as ws

    return ws.drawn(half, ident)


def _with_rail(item: dict[str, Any], entity: Any, writes: dict[str, Any] | None) -> dict[str, Any]:
    """A re-read order card with what can be done with it now, decided from its new state and
    what this caller may do — exactly as the turn that first drew it decided."""
    if kind(item) != "order" or not isinstance(entity, dict) or not isinstance(writes, dict):
        return item
    data = item.get("data") if isinstance(item.get("data"), dict) else None
    if data is None or data.get("actions") or str(data.get("order_id") or "") != str(entity.get("order_id") or ""):
        return item
    from app.presentation import _actions, _attention_items

    capabilities = writes.get("capabilities") if isinstance(writes.get("capabilities"), dict) else {}
    try:
        fresh = {**data, "actions": _actions(entity, capabilities)}
        # And the one or two lines of what it needs, on the card, as the turn drew them
        # (app/presentation.py `present`): "Customer emailed…" does not vanish because a note
        # was added.
        attention = _attention_items(entity)
        if attention and not fresh.get("attention_top"):
            fresh["attention_top"] = [{"title": a["title"], "level": a["level"], "kind": a["kind"]}
                                      for a in sorted(attention, key=lambda a: 0 if a.get("level") == "red" else 1)[:2]]
        return {**item, "data": fresh}
    except Exception as exc:  # noqa: BLE001 — a card without its rail still says what is true
        log.debug("no rail for the re-read order: %s", type(exc).__name__)
        return item


def settle(screen: list[dict[str, Any]], answer: list[dict[str, Any]], targets: set[str]) -> list[dict[str, Any]] | None:
    """The screen after a gesture: the card it was made on replaced, in its place, by the
    answer's new cards; each record the answer re-read replaced where it stands. None when the
    screen does not hold that card, which leaves the screen as it is."""
    ids = [render_id(item) for item in screen]
    at = next((i for i, rid in enumerate(ids) if rid in targets), None)
    if at is None:
        return None
    by_record = {identity(item): item for item in answer if is_subject(item)}
    on_screen = {identity(item) for item in screen}
    arriving = [plain(item) for item in answer if identity(item) not in on_screen or not is_subject(item)]
    out: list[dict[str, Any]] = []
    for index, item in enumerate(screen):
        if index == at:
            out.extend(arriving)
            continue
        if render_id(item) in targets:
            continue
        out.append(plain(by_record.get(identity(item), item)))
    return out[:MAX_KEPT]
