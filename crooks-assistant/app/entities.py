"""One id, one entity: the canonical presentation graph (§6).

The live session drew the same customer twice inside one interface. The owner said it himself,
turn_541df4c7a2b6: *"You just pulled up two in the same UI"*. The cause was not a renderer
bug and it was not a duplicate render — it was that every tool result became its own card:

    shopify_find_customer   -> a customer card
    shopify_customer_history-> a customer card
    gmail_search            -> an email card

Three reads about one person, three surfaces. The fix cannot live in a renderer, because by
the time a renderer sees two payloads the identity has already been lost. So it lives here,
upstream of presentation: every read is folded into an entity keyed by CANONICAL IDENTITY, and
a later read PATCHES the entity it belongs to.

    one customer id   = one customer entity
    one order id      = one order entity
    one thread id     = one email entity

Canonical identity is the id with the transport stripped off it. Shopify hands back
`gid://shopify/Customer/7`; a cache row, a working set and a tap hand back `7`; the owner says
"#1962" and the store calls it "CROOKS-1962". All of those are one entity, and a graph that
disagrees draws two cards.

Three rules, and each is a test in `tests/test_entities.py`:

- **Patch, never replace.** A read supplies the fields it knows. A field already known is not
  blanked by a later, thinner read of the same record — `shopify_find_order` returns a summary
  and `shopify_order_detail` returns everything, and they arrive in either order.
- **Empty is not erasure (§27).** A Gmail search that matched nothing is a fact about the
  inbox. It is never a reason to forget who the customer is.
- **Provenance is kept.** Which tool supplied which field stays on the entity, because a wrong
  number on a card has to be traceable. Presentation deduplicates identity; the record keeps
  the trail.

Nothing here reads anything. It is a fold over results the read layer already produced, so it
cannot issue a request, cannot mutate and cannot be a reason for a turn to be slower. And
nothing here decides what is drawn: `app/workspace.py` composes, `app/presentation.py` bounds,
`web/ui.js` draws.
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

# The kinds that have a canonical identity worth folding on. A kind outside this set is not a
# new feature, it is a caller's bug: the tablet routes a tap by kind and an unknown kind is a
# tap that does nothing. (The same set `app/surfaces.py:ENTITY_KINDS` keeps, minus the ones
# that are not records — a working set is a query, not a thing with an id.)
KINDS = frozenset({"customer", "order", "email_thread", "product"})

# What a Shopify gid says about the kind of thing it names. An id of the wrong kind is refused
# rather than folded: a customer gid handed in as an order is a bug, not a new order.
_GID = re.compile(r"^gid://shopify/(?P<kind>[A-Za-z]+)/(?P<id>[\w-]+)")
_GID_KIND = {"customer": "Customer", "order": "Order", "product": "Product"}

# How many entities one conversation may hold. An hour on the workbench touches tens of
# records; this is generous for that and still bounded, because the graph outlives a turn.
MAX_ENTITIES = 240
# How many conversations keep a graph in this process. Beyond it the least recently used goes.
MAX_GRAPHS = 64
# How many orders / threads one entity links to. Both are presentation lists in the end and
# `app/workspace.py` caps them again for the screen; this is the memory bound.
MAX_LINKS = 24
# How many reads back the graph remembers what each one was ABOUT.
MAX_SUBJECTS = 40


def short_id(ref: Any) -> str:
    """The canonical id inside whatever shape it arrived in.

    `gid://shopify/Order/1962` -> `1962`; `CROOKS-1962` -> `1962`; `#1962` -> `1962`;
    a Gmail thread id is already canonical and comes back unchanged.
    """
    text = str(ref or "").strip()
    if not text:
        return ""
    found = _GID.match(text)
    if found:
        return found.group("id")
    # "CROOKS-1962" and "#1962" are the same order said two ways.
    tail = text.rsplit("/", 1)[-1].rsplit("-", 1)[-1].lstrip("#").strip()
    return tail or text


def kind_of(ref: Any) -> str:
    """The kind a gid names, lowercased, or "" for an id that does not say."""
    found = _GID.match(str(ref or "").strip())
    if not found:
        return ""
    named = found.group("kind").lower()
    return named if named in KINDS else named


def key(kind: str, ref: Any) -> str:
    """The canonical key for a record: its kind and its id, with the transport stripped.

    This is the whole of §6 in one line. Two reads that produce this same string are one
    entity, whatever shape their ids arrived in.
    """
    ident = short_id(ref)
    return f"{kind}:{ident}" if ident else ""


def _kind_matches(kind: str, ref: Any) -> bool:
    """Whether a ref may be folded in as this kind. A gid that names a different kind may
    not; an id that names no kind (a thread id, a bare number) may."""
    named = kind_of(ref)
    if not named:
        return True
    return named == kind


@dataclass(slots=True)
class Entity:
    """One record, as this conversation has come to know it.

    `ident` is the canonical id. `ref` is the technical id the rest of the system uses — the
    gid, the thread id — and it is what a tap posts to `open.entity`. It is never display
    text: §26 says the screen says "Order #1962", never "gid://shopify/Order/…", and the one
    place that rule can be kept honestly is where the two are told apart, which is here.
    """

    kind: str
    ident: str
    ref: str = ""
    fields: dict[str, Any] = field(default_factory=dict)
    # field name -> the tool that last supplied it. Internal: provenance stays available, and
    # presentation does not carry it to the glass.
    provenance: dict[str, str] = field(default_factory=dict)
    # Every read that touched this entity, in order, deduplicated consecutively. What makes a
    # ten-read turn legible after the fact.
    sources: tuple[str, ...] = ()
    # Canonical keys of the entities this one owns: its orders, its threads.
    links: dict[str, tuple[str, ...]] = field(default_factory=dict)
    first_seen: float = field(default_factory=time.time)
    touched_at: float = field(default_factory=time.time)

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.ident}"

    def get(self, name: str, default: Any = None) -> Any:
        return self.fields.get(name, default)


class EntityGraph:
    """One conversation's canonical records.

    Held per conversation rather than per turn, because that is exactly what D-3 turned on:
    the customer's history was read in an earlier turn and was still true. A turn whose only
    new read is Gmail must still be able to compose the workspace the task asked for.
    """

    __slots__ = ("session_id", "_by_key", "_subjects")

    def __init__(self, session_id: str = "") -> None:
        self.session_id = str(session_id or "")
        self._by_key: OrderedDict[str, Entity] = OrderedDict()
        # The SUBJECT of each read, newest last: the record the read was about, as opposed to
        # the records it mentioned on the way. `shopify_customer_history` touches a customer
        # and then his orders, and the orders are touched later — so "the most recently
        # touched entity" answers "which record is this conversation on?" with the wrong one.
        # The subject answers it with the right one, which is what "his orders" refers to.
        self._subjects: list[str] = []

    # ------------------------------------------------------------------ reading it

    def __len__(self) -> int:
        return len(self._by_key)

    def get(self, kind: str, ref: Any) -> Entity | None:
        return self._by_key.get(key(kind, ref))

    def by_key(self, entity_key: str) -> Entity | None:
        return self._by_key.get(str(entity_key or ""))

    def of_kind(self, kind: str) -> list[Entity]:
        """Every entity of a kind, most recently touched LAST — insertion order, because the
        order the shop returned records in is the order the owner asked about them."""
        return [e for e in self._by_key.values() if e.kind == kind]

    def newest(self, kind: str) -> Entity | None:
        """The entity of a kind this conversation touched most recently. What "he" means."""
        found = sorted((e for e in self._by_key.values() if e.kind == kind),
                       key=lambda e: e.touched_at)
        return found[-1] if found else None

    def linked(self, entity_key: str, relation: str) -> list[Entity]:
        owner = self._by_key.get(str(entity_key or ""))
        if owner is None:
            return []
        out = []
        for child in owner.links.get(relation, ()):  # in the order the read supplied them
            found = self._by_key.get(child)
            if found is not None:
                out.append(found)
        return out

    def orders_of(self, entity_key: str) -> list[Entity]:
        return self.linked(entity_key, "orders")

    def threads_of(self, entity_key: str) -> list[Entity]:
        return self.linked(entity_key, "threads")

    def customer_of(self, entity_key: str) -> Entity | None:
        found = self.linked(entity_key, "customer")
        return found[0] if found else None

    def find_by_email(self, kind: str, address: str) -> Entity | None:
        wanted = str(address or "").strip().lower()
        if not wanted:
            return None
        for entity in self._by_key.values():
            if entity.kind != kind:
                continue
            if str(entity.get("email") or "").strip().lower() == wanted:
                return entity
        return None

    # ------------------------------------------------------------------ writing it

    def patch(self, kind: str, ref: Any, fields: dict[str, Any] | None = None, *,
              source: str = "") -> Entity | None:
        """Fold one read's knowledge of one record in.

        Returns the entity, or None when the ref cannot be an entity of this kind. A field
        whose value is empty does not overwrite one that is known: that is the rule that lets
        a summary read land after a detail read without losing the detail.
        """
        if kind not in KINDS:
            return None
        ident = short_id(ref)
        if not ident or not _kind_matches(kind, ref):
            return None
        entity_key = f"{kind}:{ident}"
        entity = self._by_key.get(entity_key)
        if entity is None:
            entity = Entity(kind=kind, ident=ident, ref=str(ref or "") or ident)
            self._by_key[entity_key] = entity
        elif _GID.match(str(ref or "")) and not _GID.match(entity.ref):
            # A gid is a better ref than a bare number: it is what `open.entity` posts.
            entity.ref = str(ref)
        for name, value in (fields or {}).items():
            if _blank(value) and name in entity.fields and not _blank(entity.fields[name]):
                continue        # a thinner later read never blanks what is known
            if _blank(value) and name not in entity.fields:
                entity.fields[name] = value
                continue
            entity.fields[name] = value
            if source:
                entity.provenance.setdefault(name, source)
        if source and (not entity.sources or entity.sources[-1] != source):
            entity.sources = (*entity.sources, source)
        entity.touched_at = time.time()
        self._by_key.move_to_end(entity_key)
        self._evict()
        return entity

    def link(self, owner_key: str, relation: str, child_key: str) -> None:
        """One entity owns another: a customer's orders, an order's threads. Deduplicated and
        capped, and in the order the read supplied them."""
        owner = self._by_key.get(str(owner_key or ""))
        if owner is None or not child_key or child_key == owner_key:
            return
        held = owner.links.get(relation, ())
        if child_key in held:
            return
        owner.links[relation] = (*held, child_key)[:MAX_LINKS]

    def _evict(self) -> None:
        while len(self._by_key) > MAX_ENTITIES:
            self._by_key.popitem(last=False)

    # ------------------------------------------------------------------ the fold

    def ingest(self, name: str, result: dict[str, Any] | None) -> list[str]:
        """Fold one tool result in. Returns the canonical keys it touched, in order.

        Every read the presentation layer draws from is here. A tool this does not know
        touches nothing and is not an error: the old per-tool cards still draw it, and a
        workspace simply has one less section to fill.
        """
        if not isinstance(result, dict):
            return []
        handler = _INGEST.get(str(name or ""))
        if handler is None:
            return []
        touched: list[str] = []
        handler(self, str(name), result, touched)
        if touched:
            # Every handler adds its primary record first, which is what makes this the
            # SUBJECT and not simply the first thing it happened to see.
            self._subjects.append(touched[0])
            del self._subjects[:-MAX_SUBJECTS]
        return touched

    def subject_kind(self, kinds: tuple[str, ...]) -> str:
        """The kind of the most recent read whose subject was one of these kinds.

        What answers "which record is this conversation on?" across turns — and across a turn
        whose only read was about something else, which is D-3: the Gmail search's subject is
        a thread, and the conversation was still on the customer.
        """
        for entity_key in reversed(self._subjects):
            entity = self._by_key.get(entity_key)
            if entity is not None and entity.kind in kinds:
                return entity.kind
        return ""

    def subject(self, kinds: tuple[str, ...]) -> Entity | None:
        for entity_key in reversed(self._subjects):
            entity = self._by_key.get(entity_key)
            if entity is not None and entity.kind in kinds:
                return entity
        return None


def _blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _seen(touched: list[str], entity: Entity | None) -> Entity | None:
    if entity is not None and entity.key not in touched:
        touched.append(entity.key)
    return entity


# --------------------------------------------------------------------------- per tool
#
# One function per read, and each of them says only what that read knows. This is the table
# §6 asks for: `shopify_find_customer` -> customer shell; `shopify_customer_history` ->
# enrich .orders; `gmail_search` -> enrich .email.


def _customer_fields(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": c.get("name"),
        "email": c.get("email"),
        "orders": c.get("orders"),
        "spent": c.get("spent"),
        "currency": c.get("currency"),
    }


def _order_fields(o: dict[str, Any]) -> dict[str, Any]:
    return {
        "order_number": o.get("order_number"),
        "placed_at": o.get("placed_at") or o.get("created_at"),
        "fulfillment": o.get("fulfillment"),
        "payment": o.get("payment"),
        "total": o.get("total"),
        "currency": o.get("currency"),
        "cancelled_at": o.get("cancelled_at"),
        "items": o.get("items"),
        "items_truncated": o.get("items_truncated"),
        "fulfillments": o.get("fulfillments"),
        "note": o.get("note"),
        "ships_to": o.get("ships_to"),
        "shipping_address": o.get("shipping_address"),
        "shipping_method": o.get("shipping_method"),
        "attention": o.get("attention"),
        "money": o.get("money"),
        "items_brief": o.get("items_brief"),
        "customer_name": o.get("customer_name"),
        "customer_email": o.get("customer_email"),
    }


def _thread_fields(t: dict[str, Any]) -> dict[str, Any]:
    return {
        "subject": t.get("subject"),
        "from": t.get("from"),
        "from_email": t.get("from_email"),
        "date": t.get("date"),
        "snippet": t.get("snippet"),
        "unread": t.get("unread"),
        "message_count": t.get("message_count"),
        "awaiting_reply": t.get("awaiting_reply"),
        "latest_direction": t.get("latest_direction"),
        "age_s": t.get("age_s"),
    }


def _join_customer(graph: EntityGraph, row: dict[str, Any], order: Entity | None,
                   source: str, touched: list[str]) -> Entity | None:
    """The customer an order names, so the order has somewhere to belong."""
    customer = _seen(touched, graph.patch("customer", row.get("customer_id"), {
        "name": row.get("customer_name"), "email": row.get("customer_email"),
    }, source=source))
    if customer is not None and order is not None:
        graph.link(customer.key, "orders", order.key)
        graph.link(order.key, "customer", customer.key)
    return customer


def _in_find_customer(graph: EntityGraph, source: str, result: dict[str, Any], touched: list[str]) -> None:
    for row in result.get("customers") or []:
        if isinstance(row, dict):
            _seen(touched, graph.patch("customer", row.get("customer_id") or row.get("id"),
                                       _customer_fields(row), source=source))


def _in_customer_history(graph: EntityGraph, source: str, result: dict[str, Any], touched: list[str]) -> None:
    if result.get("available") is False:
        # The customer exists and the read failed. Recorded as a fact about the read, not as
        # a blank customer: "no customer here" and "I could not load them" are different.
        person = graph.patch("customer", result.get("customer_id"), {"history_failed": True},
                             source=source)
        _seen(touched, person)
        return
    person = _seen(touched, graph.patch("customer", result.get("customer_id"), {
        **_customer_fields(result),
        "standing": result.get("standing"),
        "since": result.get("since"),
        "first_order_at": result.get("first_order_at"),
        "tags": result.get("tags"),
        "other_unfulfilled": result.get("other_unfulfilled"),
        "recent_truncated": result.get("recent_truncated"),
        "history_failed": False,
        "history_read": True,
        # Their whole story, newest first (app/customers/history.py), for the Activity section.
        **({"timeline": result["timeline"]} if isinstance(result.get("timeline"), dict) else {}),
    }, source=source))
    if person is None:
        return
    last = result.get("last_order") if isinstance(result.get("last_order"), dict) else None
    if last:
        order = _seen(touched, graph.patch("order", last.get("order_id"),
                                           {"order_number": last.get("order_number")}, source=source))
        if order is not None:
            graph.link(person.key, "orders", order.key)
            graph.link(order.key, "customer", person.key)
            person.fields["last_order_key"] = order.key
    for row in result.get("recent") or []:
        if not isinstance(row, dict):
            continue
        order = _seen(touched, graph.patch("order", row.get("order_id"), {
            **_order_fields(row), "current": row.get("current"),
        }, source=source))
        if order is not None:
            graph.link(person.key, "orders", order.key)
            graph.link(order.key, "customer", person.key)
    _in_related_email(graph, source, result.get("email_threads"), person, touched)


def _in_related_email(graph: EntityGraph, source: str, block: Any, owner: Entity | None,
                      touched: list[str]) -> None:
    if not isinstance(block, dict):
        return
    for row in block.get("threads") or []:
        if not isinstance(row, dict):
            continue
        thread = _seen(touched, graph.patch("email_thread", row.get("thread_id"),
                                            _thread_fields(row), source=source))
        if thread is not None and owner is not None:
            graph.link(owner.key, "threads", thread.key)


def _in_find_order(graph: EntityGraph, source: str, result: dict[str, Any], touched: list[str]) -> None:
    for row in result.get("orders") or []:
        if not isinstance(row, dict):
            continue
        order = _seen(touched, graph.patch("order", row.get("order_id"), _order_fields(row), source=source))
        _join_customer(graph, row, order, source, touched)
    for row in result.get("customers_matched") or []:
        if isinstance(row, dict):
            _seen(touched, graph.patch("customer", row.get("customer_id") or row.get("id"),
                                       _customer_fields(row), source=source))


def _in_order_detail(graph: EntityGraph, source: str, result: dict[str, Any], touched: list[str]) -> None:
    order = _seen(touched, graph.patch("order", result.get("order_id"), {
        **_order_fields(result), "detail_read": True,
    }, source=source))
    _join_customer(graph, result, order, source, touched)
    history = result.get("history")
    if isinstance(history, dict) and history.get("customer_id"):
        _in_customer_history(graph, source, history, touched)
    email = result.get("email")
    if isinstance(email, dict) and order is not None:
        _in_related_email(graph, source, email, order, touched)


def _in_gmail_search(graph: EntityGraph, source: str, result: dict[str, Any], touched: list[str]) -> None:
    for row in result.get("threads") or []:
        if not isinstance(row, dict):
            continue
        thread = _seen(touched, graph.patch("email_thread", row.get("thread_id"),
                                            _thread_fields(row), source=source))
        if thread is None:
            continue
        # Whose inbox thread this is, by the one piece of evidence `app/context/graph.py`
        # accepts for it: the sender's address, matched EXACTLY against a customer this
        # conversation already knows. A name is not evidence — anyone can be called Sam.
        owner = graph.find_by_email("customer", row.get("from_email"))
        if owner is not None:
            graph.link(owner.key, "threads", thread.key)
            graph.link(thread.key, "customer", owner.key)


def _in_read_thread(graph: EntityGraph, source: str, result: dict[str, Any], touched: list[str]) -> None:
    messages = [m for m in (result.get("messages") or []) if isinstance(m, dict)]
    first = messages[0] if messages else {}
    thread = _seen(touched, graph.patch("email_thread", result.get("thread_id"), {
        "subject": next((m.get("subject") for m in messages if m.get("subject")), None),
        "from": first.get("from"),
        "from_email": first.get("from_email"),
        "date": first.get("date"),
        "snippet": first.get("body") or first.get("snippet"),
        "message_count": result.get("message_count") or (len(messages) or None),
        "awaiting_reply": result.get("awaiting_reply"),
        "latest_direction": result.get("latest_direction"),
        "messages": messages or None,
        "thread_read": True,
    }, source=source))
    if thread is None:
        return
    linked = result.get("linked_order")
    if isinstance(linked, dict) and linked.get("order_id"):
        order = _seen(touched, graph.patch("order", linked.get("order_id"), _order_fields(linked), source=source))
        if order is not None:
            graph.link(thread.key, "orders", order.key)
            graph.link(order.key, "threads", thread.key)
    bridged = result.get("linked_customer")
    if isinstance(bridged, dict) and bridged.get("customer_id"):
        person = _seen(touched, graph.patch("customer", bridged.get("customer_id"),
                                            _customer_fields(bridged), source=source))
        if person is not None:
            graph.link(person.key, "threads", thread.key)
            graph.link(thread.key, "customer", person.key)
    owner = graph.find_by_email("customer", first.get("from_email"))
    if owner is not None:
        graph.link(owner.key, "threads", thread.key)


def _in_product(graph: EntityGraph, source: str, result: dict[str, Any], touched: list[str]) -> None:
    for row in result.get("products") or []:
        if not isinstance(row, dict):
            continue
        _seen(touched, graph.patch("product", row.get("product_id"), {
            "title": row.get("title"),
            "subtitle": row.get("subtitle"),
            "status": row.get("status"),
            "total_inventory": row.get("total_inventory"),
            "variants": row.get("variants"),
            "image": row.get("image"),
        }, source=source))


_INGEST = {
    "shopify_find_customer": _in_find_customer,
    "shopify_customer_history": _in_customer_history,
    "shopify_find_order": _in_find_order,
    "shopify_list_orders": _in_find_order,
    "shopify_order_detail": _in_order_detail,
    "gmail_search": _in_gmail_search,
    "gmail_read_thread": _in_read_thread,
    "shopify_product_info": _in_product,
    "shopify_inventory": _in_product,
}

# Which read fills which section of a workspace. Read by `app/workspace.py` to turn "this
# section is still empty" into "this section's read has not landed", which is the difference
# between §27's EMPTY and a lie.
FILLS = {
    "shopify_find_customer": ("identity",),
    "shopify_customer_history": ("identity", "orders"),
    "shopify_find_order": ("orders",),
    "shopify_list_orders": ("orders",),
    "shopify_order_detail": ("order", "items", "shipping"),
    "gmail_search": ("email",),
    "gmail_read_thread": ("email",),
    "shopify_product_info": ("product",),
    "shopify_inventory": ("product",),
}


# --------------------------------------------------------------- one graph per conversation

# Per conversation, not per turn: that is the whole of D-3. `Session` is a slotted dataclass
# and cannot carry it, so it is held here, keyed by session id, and bounded the same way.
_GRAPHS: OrderedDict[str, EntityGraph] = OrderedDict()


def graph_for(session: Any) -> EntityGraph:
    """This conversation's graph, made on first use. Two conversations never share one: a
    record is known to the conversation that was shown it, which is the rule
    `app/commands.py:may_open` keeps for the same data."""
    session_id = str(getattr(session, "session_id", "") or session or "")
    found = _GRAPHS.get(session_id)
    if found is None:
        found = EntityGraph(session_id)
        _GRAPHS[session_id] = found
        while len(_GRAPHS) > MAX_GRAPHS:
            _GRAPHS.popitem(last=False)
    else:
        _GRAPHS.move_to_end(session_id)
    return found


def forget(session_id: str = "") -> None:
    """Drop one conversation's graph, or all of them. Used when a session ends and by tests."""
    if session_id:
        _GRAPHS.pop(str(session_id), None)
    else:
        _GRAPHS.clear()
