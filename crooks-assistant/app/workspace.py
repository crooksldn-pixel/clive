"""The screen represents the TASK, not the last tool that returned (§3, §12, §26).

What this replaces, in one line from the forensics:

    TOOL RETURNS X → DRAW X CARD

D-3 is what that rule costs. `turn_1e7f630eae7e`, the owner: *"Pull up the history of [name]
and his orders. See how many times he's ordered, see how much he's spent, and see if he's in
Gmail anywhere."* The only NEW read was `gmail_search`; the Mac already held the orders and the
lifetime value, and the spoken answer used all of it and was right. The screen showed an email
list, twice, because the presentation layer drew the most recent tool result and nothing else.

The chain here is the replacement:

    USER INTENT → DESIRED WORKSPACE → DATA REQUIREMENTS → HELD/CACHED/NEW READS
               → PROGRESSIVE WORKSPACE HYDRATION

`desired()` is the first two arrows: what kind of workspace this task wants, which entity it is
about, which sections it needs, and which tab it implies. `compose()` is the last two: the
workspace filled from `app/entities.py` — one canonical entity, whatever reads touched it —
with every section carrying its own state, so a new read ENRICHES the workspace and never
replaces it.

Four rules, and each is a test in `tests/test_workspaces.py`:

- **A section owns its own state (§27).** `ready`, `empty`, `loading`, `error`, `unread`. EMPTY
  IS NOT ERROR: an inbox with nothing in it says "No messages found" and the customer stays on
  the screen. An error in one section never destroys the others.
- **The first viewport answers WHAT IS THIS / WHAT MATTERS / WHAT CAN I DO (§26).** Identity
  and standing; the facts that decide something; offers that go somewhere.
- **Human language, never raw ids (§26).** "Order #1962", never `gid://shopify/Order/…`. The
  ids are still on the wire as refs, because a tap needs them — `REF_KEYS` is the line between
  the two and it is the only place a technical id may sit.
- **Nothing interactive without a destination (§18).** A row is tappable only when its ref is
  a shape the gate accepts, its kind can actually be opened, and the conversation has been
  issued it. Otherwise it is drawn, and drawn disabled, with the reason on it.

This module reads nothing and changes nothing: it is a fold over entities the read layer
already produced. It does not decide WHERE the chosen tab is remembered — that is per-entity
tab state, which is workstream E's; it names the tab the task implies and why, in the payload.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app import entities

# ------------------------------------------------------------------------------ the shapes

# The sections each workspace has, in the order they are offered. This is the authority:
# `app/commands.py:TABS` reads it, so "show me the shipping" spoken and a thumb on Shipping
# cannot disagree about which tabs exist.
SECTIONS: dict[str, tuple[str, ...]] = {
    "customer": ("overview", "orders", "inbox", "activity"),
    "order": ("overview", "items", "shipping", "customer", "email"),
}

# What a section says about itself. Five states, because the four obvious ones cannot tell
# "the inbox has nothing in it" from "nobody has looked in the inbox", and a workspace that
# claims the second is empty is lying to the owner about his own shop.
STATES = frozenset({"ready", "empty", "loading", "error", "unread"})

# What the owner reads on the tab.
LABELS = {
    "overview": "Overview", "orders": "Orders", "inbox": "Inbox", "activity": "Activity",
    "items": "Items", "shipping": "Shipping", "customer": "Customer", "email": "Email",
}

# The keys that carry a REF rather than words. A ref is the shop's own id — a gid, a Gmail
# thread id — and it is what a tap posts to `open.entity`; §26's rule is about everything
# else, which is what a person reads. Anything not named here and holding a string is display
# text and may never contain a technical id.
REF_KEYS = frozenset({
    "ref", "key", "entity_key", "order_id", "customer_id", "thread_id", "product_id",
    "variant_id", "line_item_id", "message_id", "set_id", "batch_id", "proposal_id",
    "workspace_id", "compose_id", "last_order_key", "command", "kind", "state", "name",
    "tab", "tab_intended", "workspace", "image", "url",
})

# Bounds. The tablet is eight inches wide; a workspace is a BIGGER card, not an unbounded one.
# §12's complaint is that the UI is sparse AND too tall at once, so every one of these is a
# decision about the first viewport rather than a safety limit.
MAX_TITLE_CHARS = 80
MAX_VALUE_CHARS = 160
MAX_ROWS = 8
MAX_HEADER_FACTS = 5
MAX_FACTS = 8
MAX_ACTIONS = 4
MAX_ATTENTION = 3

# Which kinds `open.entity` can actually open. The same three `app/commands.py:REPLAY_TOOL`
# names — checked against it at run time in `_openable`, so this cannot drift.
OPENABLE = ("order", "customer", "email_thread")


# --------------------------------------------------------------- intent → desired workspace

# The words that name each section, per workspace kind: which sections of one record the
# owner asked about, once the model's reads have said which record it is. This shapes the
# cards a model turn is drawn with; it never decides what the turn does.
_WANTS: dict[str, dict[str, tuple[str, ...]]] = {
    "customer": {
        "orders": ("order", "orders", "ordered", "bought", "buys", "buying", "purchase",
                   "purchases", "purchased", "history", "spent", "spend", "spending", "lifetime",
                   "value", "times", "basket", "baskets"),
        "inbox": ("email", "emails", "emailed", "emailing", "gmail", "inbox", "mail", "message",
                  "messages", "messaged", "wrote", "written", "writing", "replied", "reply",
                  "replies", "correspondence", "thread", "threads"),
        "activity": ("activity", "lately", "recently", "recent", "timeline", "since", "when"),
    },
    "order": {
        "items": ("item", "items", "whats", "contents", "line", "lines", "size",
                  "sizes", "product", "products", "quantity", "bought"),
        "shipping": ("shipping", "ship", "ships", "shipped", "delivery", "deliver",
                     "delivered", "tracking", "track", "tracked", "address", "post", "postage",
                     "courier", "dispatch", "dispatched", "where", "going", "arrive",
                     "arriving", "arrived"),
        "email": ("email", "emails", "emailed", "gmail", "inbox", "mail", "message", "messages",
                  "wrote", "replied", "reply", "replies", "chased", "chasing"),
        "customer": ("customer", "who", "whose", "buyer", "client", "person"),
    },
}

# "Expand his customer page", "bring up a UI for the customer's page", "everything about" —
# an explicit request for the whole record. D-5 is three attempts at exactly this, and the
# first produced a thousand-pixel list of what the system can do.
#
# Kept to the words that can only mean the WHOLE record. "full", "all" and "details" were in
# here and should not have been: "read me the full shipping address" is a request for one
# part of one order, and taking it as a request for the whole record replaced the card that
# carries the address with a workspace that summarises it. Measured — the golden scenario
# `full_address` went red on exactly that.
_WHOLE = frozenset({"expand", "page", "workspace", "everything", "profile", "dashboard", "ui"})

# A question about a POPULATION rather than about one record. §13 is workstream D's and this
# layer must not take its surfaces: "Has anyone bought today that has bought before?" is
# answered with one number, not with seven profile pages (D-4).
_POPULATION = frozenset({"anyone", "anybody", "everyone", "everybody", "nobody", "somebody",
                         "someone", "which", "whos", "customers", "people", "orders'",
                         "average", "total", "totals", "top", "best", "worst", "compare",
                         "comparison", "revenue", "sales", "aov", "many"})

# The words that make a sentence about ONE record, whoever it is: a possessive, a pronoun, a
# name the conversation already knows. This is what separates "how much has HE spent" (one
# customer) from "how much have we sold" (an aggregate).
_ONE_RECORD = frozenset({"his", "her", "hers", "him", "hes", "she", "he", "their", "theirs",
                         "them", "this", "that", "its", "it"})


@dataclass(frozen=True, slots=True)
class Plan:
    """The workspace a task wants, before anything is filled in."""

    kind: str
    key: str                            # the canonical entity key, "customer:7"
    ref: str                            # the technical ref a tap posts
    wants: tuple[str, ...] = ()         # the sections the task named
    tab: str = "overview"               # the tab the TASK implies (§3/§12, D-2's fix)
    tab_reason: str = ""
    whole: bool = False                 # "expand his page": every section was asked for

    @property
    def sections(self) -> tuple[str, ...]:
        return SECTIONS.get(self.kind, ())

    @property
    def composes(self) -> bool:
        """Whether this task is a WORKSPACE rather than one record looked up.

        The threshold is the task's own data requirements, which is §3's third arrow. A task
        that needs one thing — "show me order 1930" — is answered by the one card, and that
        card already is its workspace; composing there would be change for its own sake. A
        task that needs two or more things about one entity is the D-3 shape, and it is the
        one the last-tool-wins rule cannot serve: "his orders" AND "in Gmail anywhere" is two,
        and the screen showed only the second.
        """
        return self.whole or len(self.wants) >= 2


def _hit(pool: set[str], *names: str) -> bool:
    """Whether a read touching any of these names is in this pool. `names` carries the
    section's own name first and the requirement names that fill it after."""
    return bool(pool & set(names))


def _words(said: str) -> list[str]:
    """The sentence as words, apostrophes removed: "he's" is "hes" and "what's" is "whats",
    so one spelling of each word appears in the tables below rather than two."""
    out, current = [], []
    for ch in str(said or "").lower():
        if ch.isalnum():
            current.append(ch)
        elif ch == "\u2019" or ch == "'":
            continue                      # an apostrophe joins, it does not separate
        elif current:
            out.append("".join(current))
            current = []
    if current:
        out.append("".join(current))
    return out


def desired(said: str, *, graph: entities.EntityGraph, calls: Any = ()) -> Plan | None:
    """The workspace this task wants, or None when it does not want one.

    None is the honest answer more often than not: an aggregate question wants a summary
    (§13, workstream D), a stock question wants the stock surface, and a conversation that has
    not established an entity has nothing to build a workspace about.
    """
    words = _words(said)
    if not words:
        return None
    have = set(words)
    whole = bool(have & _WHOLE)
    about_one = bool(have & _ONE_RECORD) or _named_number(words)
    if (have & _POPULATION) and not about_one and not whole:
        # A population question. The answer is a number or a list, and this layer does not
        # own either of them.
        return None

    kind = _kind_of(words, graph=graph)
    if not kind:
        return None
    entity = _subject(kind, words, graph)
    if entity is None:
        return None

    wants = tuple(name for name in SECTIONS[kind]
                  if name != "overview" and _named(name, kind, have))
    tab, reason = _tab_for(kind, words, wants, whole)
    return Plan(kind=kind, key=entity.key, ref=entity.ref, wants=wants, tab=tab,
                tab_reason=reason, whole=whole)


def _named(section: str, kind: str, have: set[str]) -> bool:
    return bool(have & set(_WANTS.get(kind, {}).get(section, ())))


def _named_number(words: list[str]) -> bool:
    return any(w.isdigit() and 4 <= len(w) <= 5 for w in words)


def _kind_of(words: list[str], *, graph: entities.EntityGraph) -> str:
    """Which kind of record this task is about.

    In order: a number the conversation holds an order for settles it; then a word about a
    person, because "his orders" is a customer workspace with an Orders section and reading it
    as an order workspace is precisely the mistake the live session made; then a bare word
    about orders; then the SUBJECT of the most recent read, which is what "he", "that" and
    "expand his page" refer to.

    Not the most recently TOUCHED entity: `shopify_customer_history` touches the customer and
    then each of his orders, so the most recent touch of that read is an order and the record
    the conversation is on is the customer.
    """
    have = set(words)
    for word in words:
        if word.isdigit() and 4 <= len(word) <= 5 and graph.get("order", word) is not None:
            return "order"
    if _PERSON_WORDS & have:
        return "customer"
    if {"order", "orders"} & have and graph.newest("order") is not None:
        return "order"
    return graph.subject_kind(("customer", "order"))


# The words that make a task about a person rather than about an order. A possessive pronoun
# is one: "his orders" is a customer workspace with an Orders section, which is precisely the
# distinction the live session got wrong.
_PERSON_WORDS = frozenset({"customer", "customers", "client", "his", "her", "hers", "him",
                           "hes", "she", "he", "person", "buyer", "someone", "history",
                           "spent", "spend", "lifetime", "profile"})


def _subject(kind: str, words: list[str], graph: entities.EntityGraph) -> entities.Entity | None:
    """Which record. A number in the sentence names one; otherwise it is the one this
    conversation touched most recently, which is what "he" and "that" mean."""
    if kind == "order":
        for word in words:
            if word.isdigit() and 4 <= len(word) <= 5:
                found = graph.get("order", word)
                if found is not None:
                    return found
    return graph.subject((kind,)) or graph.newest(kind)


def _tab_for(kind: str, words: list[str], wants: tuple[str, ...], whole: bool) -> tuple[str, str]:
    """The tab the TASK implies, and why.

    D-2 is the reason this exists. Every customer card in the live session opened on Email,
    because the chosen tab was a single value per BRANCH handed to every card that had tabs:
    the owner tapped Email once, early, on one customer, and from then on a request for a
    customer's orders and history opened an empty inbox. His words: "there's none of that
    here." It was there, one tab away.

    Where the choice is REMEMBERED is workstream E's (per-entity tab state). Which tab the
    task implies is this layer's, and the rule is the order he said it in: the first section
    he named is what he led with, and that is the one he is looking for.
    """
    if not wants:
        return "overview", "the request named no part of the record, so it opens where the answers are"
    table = _WANTS.get(kind, {})
    first, position = wants[0], len(words) + 1
    for name in wants:
        vocabulary = set(table.get(name, ()))
        for index, word in enumerate(words):
            if word in vocabulary and index < position:
                first, position = name, index
                break
    return first, f"the request named {LABELS.get(first, first).lower()} first"


# --------------------------------------------------------------------- workspace → payload


def compose(plan: Plan, *, graph: entities.EntityGraph, session: Any = None,
            filled: Any = (), failed: Any = (), pending: Any = ()) -> dict[str, Any] | None:
    """The workspace, filled from the canonical entity — and from nothing else.

    `filled` names the requirements a read satisfied this turn, `failed` the ones whose read
    fell over, `pending` the ones still in flight. A section with content is `ready` whatever
    those say: a held fact is a fact, which is the whole of D-3.
    """
    entity = graph.by_key(plan.key)
    if entity is None or entity.kind != plan.kind:
        return None
    builder = _BUILD.get(plan.kind)
    if builder is None:
        return None
    # A caller may name these by SECTION ("inbox") or by the requirement a read satisfies
    # ("email", from `app/entities.py:FILLS`). Both are accepted, because /turn knows which
    # tool is in flight and a test knows which section it is talking about, and neither should
    # have to translate.
    filled, failed, pending = set(filled or ()), set(failed or ()), set(pending or ())
    built = builder(plan, entity, graph, session, filled, failed, pending)
    if built is None:
        return None
    return {"type": f"{plan.kind}_workspace", "data": built}


# ------------------------------------------------------------------------- the customer


def _customer_workspace(plan: Plan, person: entities.Entity, graph: entities.EntityGraph,
                        session: Any, filled: set[str], failed: set[str],
                        pending: set[str]) -> dict[str, Any] | None:
    name = _text(person.get("name"), MAX_TITLE_CHARS)
    if not name and not person.get("email"):
        # No identity, no workspace: the old cards are better than an empty header, and a
        # workspace with a ref for a title would be §26 broken in its first line.
        return None
    orders = graph.orders_of(person.key)
    threads = graph.threads_of(person.key)
    count = _int(person.get("orders"))
    if count is None and orders:
        count = len(orders)
    last = _last_order(orders, person, graph)

    sections = {
        "overview": _rows_section(
            "overview", [], facts=_customer_facts(person, orders, threads, last),
            read=True, failed=False, pending=False,
            empty_note="Nothing else is known about them yet.",
            unread_note="", error_note=""),
        "orders": _rows_section(
            "orders", [_order_row(o, session) for o in orders], count=count,
            read=_hit(filled, "orders") or bool(person.get("history_read")),
            failed=_hit(failed, "orders"), pending=_hit(pending, "orders"),
            empty_note="No orders on this account.",
            unread_note="Ask for their orders to fill this in.",
            error_note="Their order history could not be read.",
        ),
        "inbox": _rows_section(
            "inbox", [_thread_row(t, session) for t in threads],
            read=_hit(filled, "inbox", "email"), failed=_hit(failed, "inbox", "email"),
            pending=_hit(pending, "inbox", "email"),
            empty_note="No messages found.",
            unread_note="Ask whether they have emailed to fill this in.",
            error_note="The inbox could not be read.",
        ),
        "activity": _rows_section(
            "activity", _activity_rows(orders, threads, person.get("timeline")),
            read=bool(orders or threads or person.get("timeline")), failed=False, pending=False,
            empty_note="Nothing recorded yet.",
            unread_note="Nothing recorded yet.",
            error_note="",
        ),
    }
    header = _customer_header(person, count, last)
    attention = _customer_attention(person, orders, threads)
    # `customer=person` matters: without it the workspace ABOUT a person offered nothing
    # about that person — only its two doors out, to their last order and their newest
    # thread. That is what "the customer surface has no write" meant when the §32 matrix
    # reported shot 10 MISSING, and what the owner meant by "I want to also be seeing his
    # orders and his history and like an email write box". The `open.entity` offer for the
    # customer is suppressed inside `_actions_for` when the workspace IS that customer's, so
    # this adds the write without adding a door to the screen you are already on.
    actions = _actions_for(session, last, threads[0] if threads else None, customer=person,
                           about=("customer", _ref(person)))
    tab, tab_note = _resolve_tab(plan, sections)
    return {
        "workspace": "customer",
        "kind": "customer",
        "ref": _ref(person),
        "title": name or _text(person.get("email"), MAX_TITLE_CHARS),
        "subtitle": _text(person.get("email"), MAX_TITLE_CHARS) if name else "",
        "status": _standing(person, count),
        "header": header,
        "attention": attention,
        "tab": tab,
        "tab_intended": plan.tab,
        "tab_reason": _text(plan.tab_reason if tab == plan.tab else tab_note, MAX_VALUE_CHARS),
        "tabs": _tab_bar(plan.kind, sections),
        "sections": sections,
        "actions": actions,
    }


def _customer_header(person: entities.Entity, count: int | None,
                     last: entities.Entity | None) -> list[dict[str, Any]]:
    """WHAT MATTERS, as facts and not prose: lifetime value, how many orders, the last one."""
    facts = [
        {"key": "Lifetime", "value": _money(person.get("spent")) or "—"},
        {"key": "Orders", "value": "—" if count is None else str(count)},
    ]
    if last is not None:
        when = _when(last.get("placed_at"))
        number = _number(last)
        facts.append({"key": "Last order", "value": f"{number} · {when}" if when else number})
    elif person.get("history_read"):
        facts.append({"key": "Last order", "value": "None"})
    since = _when(person.get("since") or person.get("first_order_at"))
    if since:
        facts.append({"key": "Customer since", "value": since})
    return facts[:MAX_HEADER_FACTS]


def _customer_facts(person: entities.Entity, orders: list[entities.Entity],
                    threads: list[entities.Entity], last: entities.Entity | None) -> list[dict[str, Any]]:
    """The Overview panel: what is already known, on the screen at once (§3's worked example
    — "Overview shows cached known facts immediately")."""
    facts: list[dict[str, Any]] = []
    if person.get("email"):
        facts.append({"key": "Email", "value": _text(person.get("email"), MAX_VALUE_CHARS)})
    if orders:
        shipped = sum(1 for o in orders if str(o.get("fulfillment") or "").upper() == "FULFILLED")
        facts.append({"key": "Orders held", "value": f"{len(orders)} read · {shipped} shipped"})
    if last is not None and last.get("total"):
        facts.append({"key": "Last order value", "value": _money(last.get("total"))})
    waiting = [n for n in (person.get("other_unfulfilled") or []) if isinstance(n, str)][:3]
    if waiting:
        facts.append({"key": "Not shipped", "value": ", ".join(_number_text(n) for n in waiting)})
    if threads:
        facts.append({"key": "Email relationship",
                      "value": f"{len(threads)} thread{'s' if len(threads) != 1 else ''} found"})
    tags = [_text(t, 40) for t in (person.get("tags") or []) if isinstance(t, str)][:4]
    if tags:
        facts.append({"key": "Tags", "value": ", ".join(tags)})
    return facts[:MAX_FACTS]


def _customer_attention(person: entities.Entity, orders: list[entities.Entity],
                        threads: list[entities.Entity]) -> list[dict[str, Any]]:
    """Attention only where it is MEANINGFUL (§12's own word). A customer with nothing waiting
    gets no red line, because a badge that is always there is furniture."""
    out: list[dict[str, Any]] = []
    owed = [t for t in threads if t.get("awaiting_reply")]
    if owed:
        out.append({"kind": "reply_owed", "level": "amber",
                    "title": f"No reply from us on {len(owed)} thread{'s' if len(owed) != 1 else ''}",
                    "detail": _text(owed[0].get("subject"), MAX_VALUE_CHARS)})
    unshipped = [o for o in orders
                 if str(o.get("fulfillment") or "").upper() in ("UNFULFILLED", "PARTIALLY_FULFILLED")
                 and not o.get("cancelled_at")]
    if unshipped:
        out.append({"kind": "unfulfilled", "level": "amber",
                    "title": f"{len(unshipped)} order{'s' if len(unshipped) != 1 else ''} not shipped",
                    "detail": ", ".join(_number(o) for o in unshipped[:3])})
    if person.get("history_failed"):
        out.append({"kind": "read_failed", "level": "red", "title": "Their history could not be read",
                    "detail": "The numbers above are what was already held."})
    return out[:MAX_ATTENTION]


# ---------------------------------------------------------------------------- the order


def _order_workspace(plan: Plan, order: entities.Entity, graph: entities.EntityGraph,
                     session: Any, filled: set[str], failed: set[str],
                     pending: set[str]) -> dict[str, Any] | None:
    number = _number(order)
    if not number:
        return None
    person = graph.customer_of(order.key)
    threads = graph.threads_of(order.key)
    items = [i for i in (order.get("items") or []) if isinstance(i, dict)]
    fulfillments = [f for f in (order.get("fulfillments") or []) if isinstance(f, dict)]
    detail = bool(order.get("detail_read"))

    sections = {
        "overview": _rows_section(
            "overview", [], facts=_order_facts(order, person), read=True, failed=False,
            pending=False, empty_note="Nothing read about this order yet.",
            unread_note="", error_note=""),
        "items": _rows_section(
            "items", [_item_row(i) for i in items],
            read=detail or _hit(filled, "items"), failed=_hit(failed, "items"),
            pending=_hit(pending, "items"),
            empty_note="Nothing on this order.",
            unread_note="Ask what is on it to fill this in.",
            error_note="What is on the order could not be read.",
        ),
        "shipping": _rows_section(
            "shipping", [_shipment_row(f) for f in fulfillments],
            facts=_shipping_facts(order),
            read=detail or _hit(filled, "shipping"), failed=_hit(failed, "shipping"),
            pending=_hit(pending, "shipping"),
            empty_note="Not shipped yet.",
            unread_note="Ask where it is to fill this in.",
            error_note="The shipping could not be read.",
        ),
        "customer": _section(
            "customer", facts=_order_customer_facts(person),
            rows=[_customer_row(person, session)] if person is not None else [],
            state="ready" if person is not None else ("unread" if not detail else "empty"),
            note="" if person is not None else ("No customer on this order." if detail else "Ask who placed it to fill this in."),
        ),
        "email": _rows_section(
            "email", [_thread_row(t, session) for t in threads],
            read=_hit(filled, "email"), failed=_hit(failed, "email"),
            pending=_hit(pending, "email"),
            empty_note="No messages found.",
            unread_note="Ask whether they have emailed about it to fill this in.",
            error_note="The inbox could not be read.",
        ),
    }
    tab, tab_note = _resolve_tab(plan, sections)
    return {
        "workspace": "order",
        "kind": "order",
        "ref": _ref(order),
        "title": f"Order {number}",
        "subtitle": _text(order.get("customer_name") or (person.get("name") if person else ""), MAX_TITLE_CHARS),
        "status": _order_status(order),
        "header": _order_header(order),
        "attention": _order_attention(order, threads),
        "tab": tab,
        "tab_intended": plan.tab,
        "tab_reason": _text(plan.tab_reason if tab == plan.tab else tab_note, MAX_VALUE_CHARS),
        "tabs": _tab_bar(plan.kind, sections),
        "sections": sections,
        "actions": _actions_for(session, None, threads[0] if threads else None, customer=person),
    }


def _order_header(order: entities.Entity) -> list[dict[str, Any]]:
    """§12's ORDER first viewport: value, payment, fulfilment, date — before any tab."""
    return [
        {"key": "Value", "value": _money(order.get("total")) or "—"},
        {"key": "Payment", "value": _status(order.get("payment"))},
        {"key": "Fulfilment", "value": _status(order.get("fulfillment"))},
        {"key": "Placed", "value": _when(order.get("placed_at")) or "—"},
    ][:MAX_HEADER_FACTS]


def _order_facts(order: entities.Entity, person: entities.Entity | None) -> list[dict[str, Any]]:
    """The order's Overview panel.

    It must never be blank. §12's complaint about the live session is that the UI was sparse
    AND too tall at the same time, and a "ready" panel with nothing in it is the sparse half
    exactly — measured on an order with no money breakdown and no note, this came back
    `ready(0 rows, 0 facts)`. So the contents line is derived from the items where the shop
    did not send one, and who placed it is a fact about the order rather than only a subtitle.
    """
    facts: list[dict[str, Any]] = []
    if person is not None and _text(person.get("name")):
        facts.append({"key": "Customer", "value": _text(person.get("name"), MAX_VALUE_CHARS)})
    elif _text(order.get("customer_name")):
        facts.append({"key": "Customer", "value": _text(order.get("customer_name"), MAX_VALUE_CHARS)})
    contents = _text(order.get("items_brief"), MAX_VALUE_CHARS) or _contents_of(order)
    if contents:
        facts.append({"key": "Contents", "value": contents})
    money = order.get("money") if isinstance(order.get("money"), dict) else {}
    for key, name in (("subtotal", "Subtotal"), ("shipping", "Shipping"), ("refunded", "Refunded"),
                      ("outstanding", "Outstanding")):
        value = _money(money.get(key)) if money else ""
        if value:
            facts.append({"key": name, "value": value})
    if order.get("ships_to"):
        facts.append({"key": "Ships to", "value": _text(order.get("ships_to"), MAX_VALUE_CHARS)})
    if order.get("note"):
        facts.append({"key": "Note", "value": _text(order.get("note"), MAX_VALUE_CHARS)})
    if person is not None and _int(person.get("orders")) is not None:
        facts.append({"key": "Their orders", "value": str(_int(person.get("orders")))})
    return facts[:MAX_FACTS]


def _contents_of(order: entities.Entity) -> str:
    """"1 x Yard Jeans, 2 x Cap" — from the lines the order already holds, where the shop sent
    no summary of its own. Three at most: this is the Overview, and the Items tab has them."""
    parts: list[str] = []
    for item in (order.get("items") or [])[:3]:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"), 40)
        if not title:
            continue
        quantity = _int(item.get("quantity")) or 1
        parts.append(f"{quantity} \u00d7 {title}" if quantity > 1 else title)
    return ", ".join(parts)[:MAX_VALUE_CHARS]


def _shipping_facts(order: entities.Entity) -> list[dict[str, Any]]:
    """Where it is going, in the shape the order card has always sent it: the town and the
    country, then the address itself where the read supplied one — the same fields, so a
    question about the address is answered the same way whichever surface it lands on."""
    facts: list[dict[str, Any]] = []
    if order.get("ships_to"):
        facts.append({"key": "Ships to", "value": _text(order.get("ships_to"), MAX_VALUE_CHARS)})
    address = order.get("shipping_address")
    if isinstance(address, dict):
        lines = [_text(line, MAX_VALUE_CHARS) for line in (address.get("lines") or [])[:4]
                 if isinstance(line, str)]
        if lines:
            facts.append({"key": "Address", "value": ", ".join([x for x in lines if x])})
        for key, name in (("zip", "Postcode"), ("city", "City"), ("country", "Country"),
                          ("name", "Addressed to"), ("phone", "Phone")):
            value = _text(address.get(key), MAX_VALUE_CHARS)
            if value and not (key in ("city", "country") and order.get("ships_to")):
                facts.append({"key": name, "value": value})
    if order.get("shipping_method"):
        facts.append({"key": "Method", "value": _text(order.get("shipping_method"), MAX_VALUE_CHARS)})
    return facts[:MAX_FACTS]


def _order_customer_facts(person: entities.Entity | None) -> list[dict[str, Any]]:
    if person is None:
        return []
    facts = [{"key": "Name", "value": _text(person.get("name"), MAX_VALUE_CHARS) or "—"}]
    if person.get("email"):
        facts.append({"key": "Email", "value": _text(person.get("email"), MAX_VALUE_CHARS)})
    if _int(person.get("orders")) is not None:
        facts.append({"key": "Orders", "value": str(_int(person.get("orders")))})
    if person.get("spent"):
        facts.append({"key": "Lifetime", "value": _money(person.get("spent"))})
    return facts[:MAX_FACTS]


def _order_attention(order: entities.Entity, threads: list[entities.Entity]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for a in (order.get("attention") or [])[:MAX_ATTENTION]:
        if isinstance(a, dict) and a.get("title"):
            out.append({"kind": _text(a.get("kind"), 20), "title": _text(a.get("title"), 80),
                        "detail": _text(a.get("detail"), MAX_VALUE_CHARS),
                        "level": a.get("level") if a.get("level") in ("red", "amber", "green") else "amber"})
    if not out and any(t.get("awaiting_reply") for t in threads):
        out.append({"kind": "reply_owed", "level": "amber", "title": "They are waiting on a reply",
                    "detail": _text(threads[0].get("subject"), MAX_VALUE_CHARS)})
    return out[:MAX_ATTENTION]


def _order_status(order: entities.Entity) -> str:
    if order.get("cancelled_at"):
        return "Cancelled"
    return "Shipped" if str(order.get("fulfillment") or "").upper() == "FULFILLED" else "To ship"


# ------------------------------------------------------------------------------- sections


def _section(name: str, *, state: str = "unread", note: str = "",
             facts: list[dict[str, Any]] | None = None,
             rows: list[dict[str, Any]] | None = None,
             count: int | None = None, truncated: bool = False) -> dict[str, Any]:
    """One section, in the one shape every section has. Uniform so that a renderer has one
    path through it and a test has one place to look."""
    return {
        "name": name,
        "label": LABELS.get(name, name.title()),
        "state": state if state in STATES else "unread",
        "note": _text(note, MAX_VALUE_CHARS),
        "facts": (facts or [])[:MAX_FACTS],
        "rows": (rows or [])[:MAX_ROWS],
        "count": count,
        "truncated": bool(truncated) or len(rows or []) > MAX_ROWS,
    }


def _rows_section(name: str, rows: list[dict[str, Any]], *, read: bool, failed: bool,
                  pending: bool, empty_note: str, unread_note: str, error_note: str,
                  facts: list[dict[str, Any]] | None = None,
                  count: int | None = None) -> dict[str, Any]:
    """§27, in one function.

    Content wins over everything: a held fact is a fact, and a failed Gmail read does not make
    the two orders the Mac already has unknown. Then error, then loading, then — only when the
    read actually landed — empty. A section nobody has read is `unread`, which is not the same
    claim as empty and must not be dressed up as one.
    """
    rows = [r for r in rows if r]
    if rows or facts:
        return _section(name, state="ready", rows=rows, facts=facts,
                        count=count if count is not None else (len(rows) or None),
                        truncated=len(rows) > MAX_ROWS)
    if failed:
        return _section(name, state="error", note=error_note or "That could not be read.")
    if pending:
        return _section(name, state="loading", note="Reading…")
    if read:
        return _section(name, state="empty", note=empty_note)
    return _section(name, state="unread", note=unread_note)


def _tab_bar(kind: str, sections: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"name": name, "label": sections[name]["label"], "state": sections[name]["state"],
             "count": sections[name]["count"]}
            for name in SECTIONS.get(kind, ()) if name in sections]


def _resolve_tab(plan: Plan, sections: dict[str, dict[str, Any]]) -> tuple[str, str]:
    """The tab that actually opens, which is not always the one the task implied.

    This is the live failure in one line: a request for orders and history landed on an empty
    Email panel. A tab whose section has nothing behind it cannot be the one that opens, so
    the intended tab is kept in the payload (`tab_intended`) and the workspace opens on the
    first section that can answer something.
    """
    wanted = plan.tab if plan.tab in sections else "overview"
    if sections.get(wanted, {}).get("state") == "ready":
        return wanted, plan.tab_reason
    for name in SECTIONS.get(plan.kind, ()):
        if sections.get(name, {}).get("state") == "ready":
            return name, f"{LABELS.get(wanted, wanted)} has nothing behind it yet, so this opened on {LABELS.get(name, name)}"
    return "overview", "nothing has been read yet"


# ----------------------------------------------------------------------------------- rows


def _order_row(order: entities.Entity, session: Any) -> dict[str, Any]:
    when = _when(order.get("placed_at"))
    row = {
        "order_id": _ref(order),
        "order_number": _number(order),
        "when": when,
        "total": _money(order.get("total")),
        "state": _order_status(order).lower().replace(" ", "-"),
        "payment": _status(order.get("payment")),
        "fulfilment": _status(order.get("fulfillment")),
        "items_brief": _text(order.get("items_brief"), MAX_VALUE_CHARS),
    }
    return {**row, **_open(session, "order", _ref(order))}


def _thread_row(thread: entities.Entity, session: Any) -> dict[str, Any]:
    row = {
        "thread_id": _ref(thread),
        "subject": _text(thread.get("subject"), MAX_VALUE_CHARS) or "(no subject)",
        "from": _text(thread.get("from"), MAX_VALUE_CHARS),
        "when": _text(thread.get("date"), 40),
        "needs_reply": bool(thread.get("awaiting_reply")),
        "snippet": _text(thread.get("snippet"), MAX_VALUE_CHARS),
    }
    return {**row, **_open(session, "email_thread", _ref(thread))}


def _customer_row(person: entities.Entity | None, session: Any) -> dict[str, Any]:
    if person is None:
        return {}
    row = {
        "customer_id": _ref(person),
        "name": _text(person.get("name"), MAX_VALUE_CHARS) or "—",
        "when": "",
        "subtitle": _text(person.get("email"), MAX_VALUE_CHARS),
    }
    return {**row, **_open(session, "customer", _ref(person))}


def _item_row(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _text(item.get("title"), MAX_VALUE_CHARS) or "Item",
        "variant": _text(item.get("variant"), MAX_VALUE_CHARS),
        "sku": _text(item.get("sku"), 60),
        "quantity": _int(item.get("quantity")),
        "total": _money(item.get("total")),
        "open": False,
        "open_note": "",
    }


def _shipment_row(shipment: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _status(shipment.get("status")) or "Shipment",
        "variant": _text(shipment.get("carrier"), 60),
        "sku": _text(shipment.get("number"), 60),
        "when": _when(shipment.get("shipped_at")),
        "open": False,
        "open_note": "",
    }


def _activity_rows(orders: list[entities.Entity], threads: list[entities.Entity],
                   timeline: Any = None) -> list[dict[str, Any]]:
    """A plain chronology of what is known, newest first. Derived, never read for. When the
    customer's own timeline was read (app/customers/history.py) it IS that chronology — with
    shipping, refunds, email both ways and what CLIVE recorded — and is used as it is."""
    if isinstance(timeline, dict) and isinstance(timeline.get("rows"), list) and timeline["rows"]:
        return [{"what": _text(r.get("what"), MAX_VALUE_CHARS), "when": _text(r.get("when"), 40),
                 "detail": _text(r.get("detail"), MAX_VALUE_CHARS)}
                for r in timeline["rows"] if isinstance(r, dict)][:MAX_ROWS]
    rows: list[tuple[str, dict[str, Any]]] = []
    for order in orders:
        stamp = str(order.get("placed_at") or "")
        rows.append((stamp, {"what": f"Ordered {_number(order)}", "when": _when(stamp),
                             "detail": _money(order.get("total"))}))
    for thread in threads:
        rows.append(("", {"what": f"Emailed: {_text(thread.get('subject'), 60) or '(no subject)'}",
                          "when": _text(thread.get("date"), 40), "detail": ""}))
    rows.sort(key=lambda r: r[0], reverse=True)
    return [row for _stamp, row in rows][:MAX_ROWS]


# ----------------------------------------------------------------------- §18, destinations


def _still_held(kind: str, ref: str) -> bool:
    """Whether the Mac's own COPY of the record is still there, not merely its permission.

    `_open` answers a permission question and issues the ref, which is the right check for an
    `open.entity` offer: that command re-reads. A WRITE does not re-read —
    `compose.to_person` takes the address off the Mac's cached copy and refuses `no_address`
    or `customer_not_held` when it has gone — so an offer resting on permission alone would
    outlive the record it is about and become the refusal-under-a-finger §18 forbids.

    So this asks the same store, with the same key, that the command will ask. Never raises:
    an offer that cannot be proved good is not drawn, which is the safe direction.
    """
    try:
        from app.memory import ENTITY
        from app.memory import current as memory

        held = memory().get(ENTITY, f"{kind}:{ref}", allow_stale=True)
        return isinstance(getattr(held, "value", None), dict)
    except Exception:  # noqa: BLE001 — a missing cache is "not held", not a broken workspace
        return False


def _open(session: Any, kind: str, ref: str) -> dict[str, Any]:
    """Whether this row may be shown as tappable — decided BEFORE it is shown.

    §18: no `open.entity` that returns `not_held`. `turn_dd093f86b92d` posted one, was refused
    `not_held`, and the half drew `half_empty`. So the three things that refusal checks are
    checked here: the kind can be opened at all, the ref is a shape the gate accepts, and the
    conversation has been issued it — and where the ref is good, it is issued now, because the
    card showing the row IS the conversation being shown the record (the rule
    `app/presentation.py:_remember` already keeps for the email strip's links).
    """
    from app.commands import REPLAY_TOOL
    from app.tools.gate import id_kind_ok

    if kind not in REPLAY_TOOL:
        return {"open": False, "open_note": f"A {kind.replace('_', ' ')} cannot be opened on its own."}
    if not ref:
        return {"open": False, "open_note": "This one has no id to open."}
    argument = "thread_id" if kind == "email_thread" else f"{kind}_id"
    if not id_kind_ok(argument, ref):
        return {"open": False, "open_note": "This one has no id the shop would accept."}
    if session is None:
        return {"open": False, "open_note": "Not opened in this conversation."}
    session.issue(ref)
    return {"open": True, "open_note": ""}


def link_for(session: Any, kind: str, entity: entities.Entity | None) -> dict[str, Any]:
    """A link to another record, or {} — never a link that would be refused (§18).

    Used by the inbox list as well as by the workspaces, so a thread's customer and order
    links obey the same rule wherever the thread is drawn. The label is human (§26): a name,
    or "Order #1962", and never the ref the tap posts — which rides beside it.
    """
    if entity is None:
        return {}
    ref = _ref(entity)
    state = _open(session, kind, ref)
    if not state["open"]:
        return {}
    label = _number(entity) if kind == "order" else _text(entity.get("name") or entity.get("subject"), 40)
    if not label:
        return {}
    return {"kind": kind, "ref": ref, "label": label, "command": "open.entity"}


def _actions_for(session: Any, order: entities.Entity | None, thread: entities.Entity | None,
                 *, customer: entities.Entity | None = None,
                 about: tuple[str, str] | None = None) -> list[dict[str, Any]]:
    """WHAT CAN I DO, and every one of them a real destination.

    Two kinds of offer, and every one of them a real destination. `open.entity`, for refs
    this function has just issued; and ONE write — an email to the person the workspace is
    about — offered only where the Mac is holding an address for them. An offer whose server
    side would refuse it is exactly the fake UI §18 forbids, and a workspace with nothing
    openable offers nothing, which is honest: it is not a reason to draw a button.
    """
    out: list[dict[str, Any]] = []
    for kind, entity, label in (
        ("order", order, lambda e: f"Open order {_number(e)}"),
        ("customer", customer, lambda e: f"Open {_text(e.get('name'), 40) or 'the customer'}"),
        ("email_thread", thread, lambda e: f"Open “{_text(e.get('subject'), 40) or 'the message'}”"),
    ):
        if entity is None:
            continue
        # A door to the screen you are already standing on is not a way forward (§25). The
        # customer workspace passes its own person in so the WRITE can be offered, and this
        # is what stops that also drawing "Open Daniel Sear" on Daniel Sear's own workspace.
        if about is not None and about == (kind, _ref(entity)):
            continue
        state = _open(session, kind, _ref(entity))
        if not state["open"]:
            continue
        out.append({"label": _text(label(entity), MAX_VALUE_CHARS), "command": "open.entity",
                    "kind": kind, "ref": _ref(entity), "enabled": True, "reason": ""})
    # And the one thing to DO, which the owner asked for in as many words while looking at a
    # customer card that had his orders and his inbox and no way to write to him:
    #
    #   "I want to also be seeing his orders and his history and like an email write box"
    #
    # §12's rich workspace is not only what is on the screen, it is whether the record the
    # screen is about can be acted on from there. Offered only where the Mac HOLDS an address
    # — `compose.to_person` reads it off its own copy and refuses `no_address` otherwise, so a
    # button drawn without one would be §18's refusal under a finger.
    if customer is not None and _ref(customer):
        address = str(customer.get("email") or customer.get("customer_email") or "").strip()
        if address and "@" in address and _open(session, "customer", _ref(customer))["open"] \
                and _still_held("customer", _ref(customer)):
            who = _text(customer.get("name"), 24)
            out.append({"label": f"Email {who}".strip() if who else "Write an email",
                        "command": "compose.to_person", "kind": "customer",
                        "ref": _ref(customer), "enabled": True, "reason": ""})
    return out[:MAX_ACTIONS]


# -------------------------------------------------------------------------------- helpers
#
# §26 lives here: every one of these turns a stored value into words a person reads, and none
# of them can pass a technical id through. `_number` is the one that matters — a shop whose
# order_number IS the gid used to put `gid://shopify/Order/9` in a card title.


def _ref(entity: entities.Entity) -> str:
    return str(entity.ref or "")


def _text(value: Any, limit: int = MAX_VALUE_CHARS) -> str:
    if value is None or isinstance(value, (dict, list, bool)):
        return ""
    out = " ".join(str(value).split())
    return out[: max(0, limit)]


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


_SYMBOL = {"GBP": "£", "USD": "$", "EUR": "€"}


def _money(value: Any) -> str:
    """"60.00 GBP" -> "£60.00". The same shape the rest of the vocabulary shows."""
    text = _text(value, 40)
    if not text:
        return ""
    parts = text.split()
    if len(parts) == 2 and parts[1].upper() in _SYMBOL:
        try:
            return f"{_SYMBOL[parts[1].upper()]}{float(parts[0]):,.2f}"
        except ValueError:
            return text
    return text


def _status(value: Any) -> str:
    """"PARTIALLY_FULFILLED" -> "Partially fulfilled". Never SHOUTED at the owner."""
    text = _text(value, 40)
    return text.replace("_", " ").capitalize() if text else ""


def _number(entity: entities.Entity | None) -> str:
    """§26: "Order #1962", never "gid://shopify/Order/1962".

    The store names orders "CROOKS-1962" and older ones "#1036". Where the value is a gid — or
    missing — the canonical id carries the digits, so the card still says a number a person
    recognises rather than a URL.
    """
    if entity is None:
        return ""
    said = _text(entity.get("order_number"), 40)
    number = _number_text(said)
    if number:
        return number
    return f"#{entity.ident}" if str(entity.ident).isdigit() else ""


def _number_text(said: Any) -> str:
    text = _text(said, 40)
    if not text or "gid://" in text:
        return ""
    digits = text.rsplit("-", 1)[-1].lstrip("#").strip()
    return f"#{digits}" if digits.isdigit() else text


def _when(value: Any) -> str:
    """"2026-09-01T10:00:00Z" -> "1 Sep". A date the owner reads, never a timestamp."""
    text = _text(value, 40)
    if not text:
        return ""
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    return f"{moment.day} {moment.strftime('%b')}"


def _standing(person: entities.Entity, count: int | None) -> str:
    """Returning or new, in one word (§12). Taken from the shop's own standing where the
    history read supplied one, and from the order count where it did not."""
    said = _text(person.get("standing"), 20)
    if said:
        return said.replace("_", " ").capitalize()
    if count is None:
        return "Customer"
    if count == 0:
        return "No orders yet"
    if count == 1:
        return "First order"
    return "Regular" if count >= 4 else "Returning"


def _last_order(orders: list[entities.Entity], person: entities.Entity,
                graph: entities.EntityGraph) -> entities.Entity | None:
    named = person.get("last_order_key")
    if named:
        found = graph.by_key(str(named))
        if found is not None:
            return found
    if not orders:
        return None
    return sorted(orders, key=lambda o: str(o.get("placed_at") or ""), reverse=True)[0]


_BUILD = {"customer": _customer_workspace, "order": _order_workspace}
