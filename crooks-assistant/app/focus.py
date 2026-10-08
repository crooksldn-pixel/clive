"""What the answer is about — and only that — on the screen (DEC-069, 7 October 2026).

George, 7 October: "today I asked for the email reply to [a customer] and it showed [a customer]'s
total orders as a customer, then some random email from someone else, today's email threads and
today's orders when all I wanted to see was the reply to [a customer]."

`present()` draws a card for every read a turn made. Most of those reads are how CLIVE found the
thing — the customer looked up for his address, the inbox searched for his thread, today's
orders checked for a match — and the answer is about one of them, or about a change prepared
from them. This module takes the answer's cards out of that deck, by three rules over the cards
themselves and never over the words (MAP rule 7: nothing matches what was said), in order:

1. A CHANGE wins. A card waiting for his gesture, a step towards one (which variant), an email
   being written, a form being built: those are the screen, and nothing read on the way to them
   is. "The reply to [a customer] and nothing else." The change comes first, on top of whatever
   stays beside it (DEC-069). Two kinds of card stay beside it, because they are about the
   change and not how it was found: the attention lines of the record the
   change is to ("Chargeback open" beside a refund of that order), and a screen's remote. And
   when the change is to a record he already had up as the turn began, that screen is his and
   not this turn's finds: the records on it this turn drew again stay beside the change (with
   their lines), and `app/screen.py` `carry` keeps the rest of it (`his_screen`).
2. Otherwise, a RECORD read in full wins over the searches that found it: an order read whole,
   a thread opened, a customer's history, an objective, or a workspace composed over a record
   that a read this turn returned whole. The lists and the one-line finds that led there are set
   aside; numbers and summaries stay beside the record. An order asked for by its own id or
   number is never one of those finds, even drawn as its line ("put 1938 and 1940 side by side":
   `records_asked_for`). A workspace composed over a record that only came up on a listing is
   not a record read in full: there the listings are the answer.
3. Otherwise the answer IS the listings and the numbers ("how many orders today"), and every
   card stays.

What it never sets aside, whatever the rule: an error (a failure is always said — `present()`
adds those after this has run, so they cannot reach it), any change card (rule 1 keeps them
all), and the tablet's bookkeeping. Nothing here reads, stages or invents: it only chooses among
cards `present()` already built from what the tools returned.

What he ASKED for comes before all three (DEC-073, his ruling 25 of 8 October): "asking to see
todays orders and to show a specific order s different to asking to see a specific order and
seeing the specific order + todays orders ... clive can infer but inferring needs stronger
relation". When the model says what he asked to see (`asked_for`, app/tools/asked_for.py — the
model knows what he asked; nothing here reads his words), the cards are chosen by `_as_asked`:

- every card he asked for shows, a list and a record together ("today's orders and open 1940");
- a card he did not ask for shows only when it is a record in its own right (never a search, a
  list or a one-line find) about the same customer, order or thread as what he asked for or the
  change being made: the same id, order number, email address or full name, followed from card
  to card (`about`). That customer's tracking or Instagram message beside their email stays;
  other people's emails today, and today's orders when he asked about one customer, do not;
- a change waiting for his hold still comes first, the records he had up still stay beside a
  change to one of them, and errors are still never set aside.

When the model says nothing, or names nothing this turn drew, the three rules above decide.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("crooks.focus")

# The cards that are a change, or the thing a change is being made from: rule 1.
TASK = frozenset({"confirmation", "batch_action", "variant_picker", "email_compose", "workspace"})
# Cards that are the tablet's bookkeeping rather than an answer, and errors: never set aside.
ALWAYS = frozenset({"context_stack", "workspace_plan", "error"})
# Cards that are how a record was found: a listing, a one-line find, a choice between matches.
LISTINGS = frozenset({"order_list", "email_list", "customer_list", "order_match", "working_set"})
# Composed or opened records that are one thing in full.
WHOLE = frozenset({"email_thread", "customer_workspace", "order_workspace", "objective", "screen_remote"})
# The composed ones: a record in full only when a read returned that record whole this turn.
COMPOSED = frozenset({"customer_workspace", "order_workspace"})

CHANGE, RECORD, LISTING = "change", "record", "listing"


def _data(item: dict[str, Any]) -> dict[str, Any]:
    data = item.get("data")
    return data if isinstance(data, dict) else {}


def _kind(item: Any) -> str:
    return str(item.get("type") or "") if isinstance(item, dict) else ""


def in_full(item: dict[str, Any], read_whole: frozenset[str] | None = None) -> bool:
    """Whether this card is one record read in full — what rule 2 stands on. `read_whole`, when
    given, is the records a read returned whole this turn (`records_read_whole`): a composed
    workspace counts only over one of them, not over a record it found on a listing."""
    kind, data = _kind(item), _data(item)
    if data.get("empty") or data.get("shell"):
        return False
    if kind == "order":
        return bool(data.get("detail"))
    if kind == "customer":
        return bool(data.get("history") or data.get("timeline"))
    if kind in COMPOSED and read_whole is not None:
        return str(data.get("ref") or "") in read_whole
    return kind in WHOLE


def records_read_whole(items: list[dict[str, Any]]) -> frozenset[str]:
    """The records a read returned whole, from the cards it drew before any workspace was
    composed over them: an order's detail, a customer's history, an opened thread."""
    refs = set()
    for item in items or []:
        if isinstance(item, dict) and _kind(item) in ("order", "customer", "email_thread") and in_full(item):
            data = _data(item)
            refs.add(str(data.get("order_id") or data.get("customer_id") or data.get("thread_id") or ""))
    return frozenset(refs - {""})


def _beside_a_change(item: dict[str, Any], refs: set[str]) -> bool:
    """Whether a card stays beside a change waiting for him (rule 1): the attention lines of the
    record a change is to — the risk he reads before he holds it — and a screen's remote, which
    is a control and not a search. `refs` is what the changes on the screen are to."""
    kind = _kind(item)
    if kind == "screen_remote":
        return True
    return kind == "attention" and str(_data(item).get("for") or "") in refs


def his_screen(changes: list[dict[str, Any]], before: list[dict[str, Any]] | None) -> frozenset[str]:
    """The records he had on screen when the turn began — as canonical record keys — when a
    change this turn staged is to something on that screen (rule 1). Empty otherwise: a change
    to a record that was not up (the reply to a customer found by searching) has nothing of his
    screen beside it. `before` is the half's screen as the turn found it (`app/screen.py`
    `showing`); "to something on that screen" is the test `screen.carry` makes."""
    from app import screen

    up = [item for item in before or [] if isinstance(item, dict)]
    targets: set[str] = set()
    for change in changes:
        data = _data(change)
        targets |= {str(data.get("entity_ref") or ""), str(data.get("workspace_id") or "")}
    if not up or not (targets - {""}) & screen.refs_on(up):
        return frozenset()
    return frozenset(record[1] for record in (screen.record_of(item) for item in up) if record)


def _was_up(item: dict[str, Any], records: frozenset[str]) -> bool:
    """Whether this turn's card is of a record he had on screen when it began (`his_screen`), or
    is that record's attention lines: his screen, read again, and not one of this turn's finds."""
    if not records:
        return False
    from app import entities, screen

    if _kind(item) == "attention":
        return entities.key("order", _data(item).get("for")) in records
    record = screen.record_of(item)
    return record is not None and record[1] in records


def records_asked_for(calls: Any) -> frozenset[str]:
    """The orders a read this turn asked for by the order's own id or number, whatever card
    `present()` drew for each: one read whole (`shopify_order_detail`), or one looked up by its
    number and found alone (`shopify_find_order` matched on `name:<number>`, one order back).
    "Put 1938 and 1940 side by side" asks for both, and one of them may be drawn as its line
    without detail: it is still what the answer is about, not a search that found something
    else (rule 2). Read from the calls the model made and what they returned, never from his
    words (MAP rule 7)."""
    out: set[str] = set()
    for call in calls or []:
        result = getattr(call, "result", None)
        if not getattr(call, "ok", False) or not isinstance(result, dict):
            continue
        name = str(getattr(call, "name", "") or "")
        if name == "shopify_order_detail":
            out.add(str(result.get("order_id") or ""))
        elif name == "shopify_find_order" and str(result.get("matched_on") or "").startswith("name:"):
            orders = [o for o in result.get("orders") or [] if isinstance(o, dict)]
            if len(orders) == 1:
                out.add(str(orders[0].get("order_id") or ""))
    return frozenset(out - {""})


def _found_on_the_way(item: dict[str, Any], kept_orders: set[str]) -> bool:
    """Whether a card is one of the searches a record read in full was found by (rule 2).
    `kept_orders` is every order this answer is about: read in full, or asked for by its own
    id or number (`records_asked_for`) — an order of those is never a find, drawn whole or as
    its line."""
    kind, data = _kind(item), _data(item)
    if kind in ALWAYS or kind in TASK:
        return False
    if data.get("empty"):
        return True
    if kind in LISTINGS:
        return True
    if kind == "order" and str(data.get("order_id") or "") in kept_orders:
        return False
    if kind in ("order", "customer"):
        return not in_full(item)
    if kind == "attention":
        return str(data.get("for") or "") not in kept_orders
    return False


# ------------------------------------------------------------- what he asked for (DEC-073)

ASKED = "asked"
# The model's word for what he asked to see (app/tools/asked_for.py ASKED_TOOL).
ASKED_TOOL = "asked_for"
# Lists by the kind the model names them (app/tools/asked_for.py LISTS), card by card.
_LIST_OF = {
    "order_list": "orders", "order_match": "orders", "email_list": "emails", "customer_list": "customers",
    "sales_summary": "numbers", "metric_group": "numbers", "ranking": "numbers", "table": "numbers",
    "comparison": "numbers", "trend": "numbers", "variant_matrix": "products", "product": "products",
    "inventory": "products",
}
# The cards drawn as one view of a list or one record, by their `view` (web/messages.js,
# web/shipping.js, web/returns.js): the record's view, and the list kind every other view is.
_ONE_VIEW = {"messages": ("thread", "messages"), "shipping": ("one", "shipments"), "returns": ("one", "returns")}

_GID = re.compile(r"^gid://shopify/[a-z]+/([\w-]+)")
# An order number as it is written: "1940", "#1940", "CROOKS-1940".
_NUMBER = re.compile(r"^#?(?:[a-z]+-)?(\d{3,7})$")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# What a conversation is called when the app gave no name (app/messaging/contacts.py `name_for`):
# a phrase about nobody in particular, never a person's name.
_NOBODY = re.compile(r"^(?:someone on|a wecom member)\b")


@dataclass(frozen=True)
class Asked:
    """What the model said he asked to see: records by id or number, lists by kind."""

    records: frozenset[str]
    lists: frozenset[str]


def asked_by_the_model(calls: Any) -> Asked | None:
    """What the model said he asked for this turn (`asked_for`), from what the tool handed back —
    or None when it said nothing. Read from the turn's calls, never from his words (MAP rule 7)."""
    records: set[str] = set()
    lists: set[str] = set()
    said = False
    for call in calls or []:
        result = getattr(call, "result", None)
        if getattr(call, "name", "") != ASKED_TOOL or not getattr(call, "ok", False) or not isinstance(result, dict):
            continue
        said = True
        records |= {_norm(r) for r in result.get("records") or [] if isinstance(r, str)}
        lists |= {str(k) for k in result.get("lists") or [] if isinstance(k, str)}
    return Asked(frozenset(records - {""}), frozenset(lists)) if said else None


def _norm(value: Any) -> str:
    """One id or order number however it was written: a gid's own id, an order's number."""
    text = str(value or "").strip().lower()
    found = _GID.match(text) or _NUMBER.match(text)
    return found.group(1) if found else text


def _name(value: Any) -> str:
    """A person's full name as words ("priya raman"), from a name, a "Name <address>" or an
    Instagram handle ("@priya.raman"); "" for one word, which anyone can share, and for "someone
    on Instagram". A full name is the only evidence a conversation carries of who it is with."""
    text = re.sub(r"<[^>]*>", " ", str(value or "")).strip().lstrip("@")
    words = re.findall(r"[^\W\d_]+", re.sub(r"[._-]+", " ", text).lower())
    joined = " ".join(words)
    return joined if len(words) >= 2 and not _NOBODY.match(joined) else ""


def list_kind(item: Any) -> str:
    """The kind of list a card is, as `asked_for` names lists; "" for a card that is no list."""
    kind, data = _kind(item), _data(item) if isinstance(item, dict) else {}
    if kind in _ONE_VIEW:
        one, word = _ONE_VIEW[kind]
        return "" if data.get("view") == one else word
    if kind == "summary_list":
        return "customers" if str(data.get("task") or "") == "returning_customers" else "orders"
    if kind == "working_set":
        set_kind = str(data.get("kind") or "")
        return next((word for word in ("orders", "emails", "customers") if word[:-1] in set_kind or word in set_kind), "")
    return _LIST_OF.get(kind, "")


def _rows(data: dict[str, Any], *names: str) -> list[dict[str, Any]]:
    """The dict rows under these keys; a count or a string under one of them is no rows."""
    if not isinstance(data, dict):
        return []
    return [row for name in names if isinstance(data.get(name), list) for row in data[name] if isinstance(row, dict)]


def identity(item: Any) -> frozenset[str]:
    """The ids and order numbers of the record a card IS — what `asked_for`'s records name. A
    list is not the records on its rows: asking for #1940 is not asking for today's orders."""
    from app import screen

    kind, data = _kind(item), _data(item) if isinstance(item, dict) else {}
    if not data or data.get("shell"):
        return frozenset()
    found: list[Any] = []
    if kind == "order":
        found = [data.get("order_id"), data.get("order_number")]
    elif kind == "customer":
        found = [data.get("customer_id")]
    elif kind in ("email_thread", "reply_state", "email_draft"):
        found = [data.get("thread_id"), data.get("draft_id")]
    elif kind in COMPOSED:
        # A workspace is its record and the records it holds: asked for the thread it took in, it
        # is the card that thread is on now.
        found = [data.get("ref"), *(re.findall(r"\d{3,7}", str(data.get("title") or ""))[-1:]), *screen.refs_on([item])]
    elif kind == "objective":
        found = [data.get("objective_id")]
    elif kind in _ONE_VIEW and not list_kind(item):
        thread = data.get("thread") if isinstance(data.get("thread"), dict) else {}
        found = [thread.get("chat_id"), data.get("order_number")]
        found += [row.get(k) for row in _rows(data, "shipments", "returns")
                  for k in ("shipment_id", "return_id", "order_id", "order_number")]
    elif kind in ("confirmation", "batch_action", "variant_picker", "email_compose", "workspace"):
        found = [data.get("entity_ref"), data.get("thread_id"), data.get("order_id"), data.get("workspace_id")]
    elif kind == "product":
        found = [row.get("product_id") for row in _rows(data, "products")]
    return frozenset(_norm(v) for v in found if isinstance(v, (str, int)) and str(v).strip()) - {""}


def about(item: Any) -> frozenset[str]:
    """Who and what a card is about, as marks two cards share when they are about the same
    customer, order or thread: `id:` an order's, customer's, thread's or conversation's id, `n:`
    an order number, `e:` an email address, `p:` a full name (`_name`). Read from the card alone:
    an order's customer and the email about it, a thread's sender and the order it is linked to,
    a conversation's name, a shipment's or a return's order."""
    out: set[str] = set()
    data = _data(item) if isinstance(item, dict) else {}

    def ident(value: Any) -> None:
        if isinstance(value, (str, int)) and str(value).strip():
            out.add(f"id:{_norm(value)}")

    def number(value: Any) -> None:
        found = _NUMBER.match(str(value or "").strip().lower())
        if found:
            out.add(f"n:{found.group(1)}")

    def emails(value: Any) -> None:
        text = value.get("value") if isinstance(value, dict) else value
        out.update(f"e:{a.lower()}" for a in _EMAIL.findall(str(text or "")))

    def person(value: Any) -> None:
        if _name(value):
            out.add(f"p:{_name(value)}")

    def record(row: Any) -> None:
        """The fields every shape names a record by, on the card or one of its rows."""
        if not isinstance(row, dict):
            return
        for field in ("order_id", "customer_id", "thread_id", "chat_id", "return_id", "shipment_id",
                      "objective_id", "for", "entity_ref"):
            ident(row.get(field))
        number(row.get("order_number"))
        for field in ("customer_email", "from_email", "to"):
            emails(row.get(field))
        for field in ("customer_name", "who"):
            person(row.get(field))

    kind = _kind(item)
    record(data)
    if kind in ("customer", "customer_list"):
        emails(data.get("email"))
        person(data.get("name"))
    if kind == "email_thread":
        for message in _rows(data, "messages"):
            if not message.get("outbound"):          # what we sent says who we are, not who they are
                emails(message.get("from_email"))
                person(message.get("from"))
        record(data.get("linked_order"))
        record(data.get("linked_customer"))
        if isinstance(data.get("linked_customer"), dict):
            person(data["linked_customer"].get("name"))
    history = data.get("history") if isinstance(data.get("history"), dict) else {}
    record(history)
    person(history.get("name"))
    record(history.get("last_order"))
    for row in _rows(history, "recent"):
        record(row)
    for block in (data.get("email"), data.get("related_email")):
        for row in _rows(block if isinstance(block, dict) else {}, "threads"):
            ident(row.get("thread_id"))
    record(data.get("thread"))
    for row in _rows(data, "threads", "shipments", "returns", "rows"):
        record(row)
    record(data.get("message"))
    if kind in COMPOSED:
        for ref in identity(item):
            ident(ref)
    return frozenset(out)


def _addable(item: dict[str, Any], read_whole: frozenset[str] | None) -> bool:
    """Whether a card he did not ask for may be added for being about the same subject: a record
    in its own right — an order or a customer read in full, a thread, a conversation, a shipment,
    a return, an objective. Never a search or a list, a one-line find, an empty answer, or a card
    about no customer, order or thread (numbers, products)."""
    kind, data = _kind(item), _data(item)
    if data.get("empty") or data.get("shell") or kind in LISTINGS or kind == "summary_list":
        return False
    if kind in ("order", "customer") or kind in COMPOSED:
        return in_full(item, read_whole)
    if kind == "messages":
        return True                                  # one conversation, or all of them one person's
    if kind in _ONE_VIEW:
        return not list_kind(item)
    return kind in ("email_thread", "reply_state", "email_draft", "objective")


def _related(item: dict[str, Any], subject: set[str]) -> bool:
    """Whether a card is about the subject. A card of several conversations is, only when every
    one of them is: one person's messages, not the inbox of messages."""
    data = _data(item)
    if _kind(item) == "messages" and list_kind(item):
        threads = _rows(data, "threads")
        return bool(threads) and all(about({"data": t}) & subject for t in threads)
    return bool(about(item) & subject)


def _matches(item: dict[str, Any], said: Asked) -> bool:
    return bool(identity(item) & said.records) or bool(list_kind(item) and list_kind(item) in said.lists)


def _as_asked(cards: list[dict[str, Any]], said: Asked, *, read_whole: frozenset[str] | None,
              before: list[dict[str, Any]] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]] | None:
    """The cards by what he asked for (module docstring, DEC-073): (kept, added), or None when
    the model named nothing this turn drew — then DEC-069's three rules decide."""
    asked = [item for item in cards if _kind(item) not in ALWAYS and _matches(item, said)]
    if not asked:
        return None
    changes = [item for item in cards if _kind(item) in TASK]
    # The subject: what he asked for that is a record, and what is being changed. A list he asked
    # for is not the subject of everything on its rows.
    subject: set[str] = set()
    for item in changes + [item for item in asked if not list_kind(item)]:
        subject |= about(item)
    # What he did not ask for, added when it is about that subject — and then it is part of it:
    # the order his email is about brings the order's customer, and that customer's messages.
    added: list[dict[str, Any]] = []
    grew = True
    while grew:
        grew = False
        for item in cards:
            if _among(item, asked + changes + added) or not _addable(item, read_whole):
                continue
            if _related(item, subject):
                added.append(item)
                subject |= about(item)
                grew = True
    # Beside a change, as rule 1 keeps them: a screen's remote, and the records he had up when the
    # turn began, drawn again (their attention lines follow them below).
    refs = {str(_data(item).get("entity_ref") or "") for item in changes} - {""}
    his = his_screen(changes, before)
    for item in cards:
        if _among(item, asked + changes + added) or _kind(item) == "attention":
            continue
        if _kind(item) == "screen_remote" or _was_up(item, his):
            added.append(item)
    shown = asked + added
    orders: set[str] = {_norm(ref) for ref in refs}
    for item in shown:
        if _kind(item) in ("order", "order_workspace"):
            orders |= identity(item)
    lines = [item for item in cards if _kind(item) == "attention" and _norm(_data(item).get("for")) in orders
             and not _among(item, shown)]
    # The change first (DEC-069), then what he asked for, then what is about the same subject:
    # each in the order the turn drew it, an order's attention lines straight under the order.
    kept = list(changes)
    for group in (asked, added):
        for item in [i for i in cards if _among(i, group) and not _among(i, kept)]:
            kept.append(item)
            mine = identity(item) if _kind(item) in ("order", "order_workspace") else frozenset()
            kept.extend(line for line in lines if _norm(_data(line).get("for")) in mine and not _among(line, kept))
    kept.extend(line for line in lines if not _among(line, kept))
    kept.extend(item for item in cards if _kind(item) in ALWAYS and not _among(item, kept))
    return kept, [item for item in kept if _among(item, added) or _among(item, lines)]


def _among(item: dict[str, Any], cards: list[dict[str, Any]]) -> bool:
    """Whether this very card (not an equal one) is among these."""
    return any(item is card for card in cards)


def answer_cards(items: list[dict[str, Any]], why: dict[str, Any] | None = None, *,
                 read_whole: frozenset[str] | None = None,
                 asked: frozenset[str] | None = None,
                 before: list[dict[str, Any]] | None = None,
                 said: Asked | None = None) -> list[dict[str, Any]]:
    """The cards this answer is about, in the order `present()` built them, except that under
    rule 1 the change cards come first and what stays beside them follows. `why`, when given,
    is told which rule decided and the kinds of the cards set aside (for the interaction record:
    app/observability/interactions.py). `read_whole` is `records_read_whole` of the cards before
    a workspace was composed (see `in_full`). `asked` is `records_asked_for` of the turn's
    calls: an order in it is never set aside as a find by rule 2. `before` is the half's screen
    as the turn found it: beside a change to one of its records, the records on it that this
    turn drew again stay (rule 1, `his_screen`). `said` is what the model said he asked for
    (`asked_by_the_model`): when it names a card this turn drew, that decides (`_as_asked`), and
    `why` is also told the kinds it added for being about the same subject."""
    cards = [item for item in items or [] if isinstance(item, dict)]
    chosen = None
    if said is not None:
        try:
            chosen = _as_asked(cards, said, read_whole=read_whole, before=before)
        except Exception as exc:  # noqa: BLE001 — never at the cost of the turn: DEC-069's rules decide
            log.warning("what he asked for could not be chosen by: %s", type(exc).__name__)
    if chosen is not None:
        kept, added = chosen
        if why is not None:
            aside = [_kind(item) for item in cards if not _among(item, kept)]
            why.update({"rule": ASKED, "set_aside": aside[:12], "added": [_kind(item) for item in added][:12]})
        return kept
    if any(_kind(item) in TASK for item in cards):
        rule = CHANGE
        changes = [item for item in cards if _kind(item) in TASK]
        refs = {str(_data(item).get("entity_ref") or "") for item in changes} - {""}
        his = his_screen(changes, before)
        beside = [item for item in cards if _kind(item) not in TASK and (
            _kind(item) in ALWAYS or _beside_a_change(item, refs) or _was_up(item, his))]
        # The change comes first (8 October, flow's second review, note 1): DEC-069's "the change
        # card stays on top" holds when `carry` replaces his screen with this answer, as it does
        # when it continues it. Otherwise a record he had up, drawn in full, would sit over the
        # card he holds and push it below the fold of the 601x889 tablet.
        kept = changes + beside
    elif any(in_full(item, read_whole) for item in cards):
        rule = RECORD
        orders = {str(_data(item).get("order_id") or "") for item in cards if _kind(item) == "order" and in_full(item)}
        kept = [item for item in cards if not _found_on_the_way(item, (orders | set(asked or ())) - {""})]
    else:
        rule = LISTING
        kept = cards
    if why is not None:
        aside = [_kind(item) for item in cards if not any(item is k for k in kept)]
        why.update({"rule": rule, "set_aside": aside[:12]})
    return kept
