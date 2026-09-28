"""The typed envelope around a card: what it is, what it is about, and what can be done next.

`app/presentation.py` already decides *what a card contains*, key by key, bounded, from a tool
result. That discipline is the reason no model-invented value has ever reached the tablet and
it is not changed here. What was missing is everything *around* the payload: which version of
the contract this is, which entity the card is about, what else it links to, which regions are
still loading, how fresh it is, and what should be said aloud about it.

Those lived in three places before — sniffed downstream from data keys (`app/routes/turn.py`
recovered the entity by trying `order_id`, then `customer_id`, then `thread_id`), hardcoded in
the renderer, or nowhere. A card built by a recipe that read no tool could not exist
at all: the only channel into the `ui` list was a `ToolCall`, so "what can you do now?" — which
reads nothing — answered in prose and drew no card. That is the regression this module exists
to close.

The wire shape stays what the tablet already parses: `{"type": ..., "data": {...}}`. The
envelope adds sibling keys. An older tablet ignores them; a card that predates this module
still renders. Nothing here can widen what reaches the screen — a Surface carries the payload
`presentation.py` built and cannot invent a field of its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The contract's version. Bumped when the meaning of an existing key changes — never for a
# key that is merely added, because adding one cannot break a tablet that ignores it. The
# tablet reports the version it understands on every turn so a mismatch is visible in the
# health page rather than as a blank card.
SURFACE_VERSION = 1

# What a surface is for. This is the answer to "which interface is this?", which is a
# different question from "which component renders it" — an order detail and an order list are
# both built from orders and are not the same surface.
SURFACE_TYPES = frozenset({
    "order_detail", "order_list", "customer", "customer_list", "product", "inventory",
    "analytics", "email_list", "email_thread", "email_draft", "email_queue", "work_queue",
    "capability", "attention", "confirmation", "batch", "result", "error", "context",
    "assistant",
    # the answer to a SUMMARY question (app/summaries.py): a count and one compact row each,
    # with a tap on the row that opens the full workspace. D-4: "has anyone bought today that
    # has bought before" was answered with seven full customer profiles, which is the
    # drilldown surface for a question nobody asked.
    "summary",
    # who is waiting on whom in one thread (app/families/order_email.py)
    "reply_state",
    # which variant the owner means, before anything is staged (app/families/order_edit.py):
    # candidate rows, a quantity, and one button that asks the Mac to prepare the change.
    "variant_picker",
    # an email being written, before anything is prepared (app/families/compose.py): the
    # fields, their status, and the two gestures that could stage it
    "email_compose",
    # something being BUILT before anything is proposed (app/families/_workspace.py): the
    # discount code being written, the order being assembled, the credit being decided. One
    # component for all three, so that a precision field behaves the same way wherever it
    # appears and there is one place where a keystroke's route to the Mac is decided.
    "workspace",
})

# Which entity kinds may be named. A kind outside this set is a bug in a builder, not a new
# feature: the tablet routes a tap on a linked entity by kind, and an unknown kind is a tap
# that does nothing.
ENTITY_KINDS = frozenset({"order", "customer", "product", "variant", "email_thread", "draft", "set"})

# How one entity relates to another. Named rather than free text so the tablet can label a
# link without the server sending display words for every language of relationship.
RELATIONS = frozenset({
    "customer_of", "orders_of", "emails_of", "order_of", "products_of", "thread_of",
    "member_of", "previous", "next",
})

MAX_LINKED = 12
MAX_LOADING = 6
MAX_TITLE_CHARS = 80
MAX_SPOKEN_CHARS = 400


class SurfaceError(ValueError):
    """A builder produced something outside the contract. Raised at build time, in tests and
    in development, so it can never be a blank region on the tablet at the workbench."""


@dataclass(frozen=True, slots=True)
class Entity:
    """What a surface is about. `ref` is the id the rest of the system already uses — a
    Shopify gid, a Gmail thread id, a working-set id — never a display string."""

    kind: str
    ref: str
    label: str = ""

    def __post_init__(self) -> None:
        if self.kind not in ENTITY_KINDS:
            raise SurfaceError(f"unknown entity kind {self.kind!r}; known: {', '.join(sorted(ENTITY_KINDS))}")
        if not str(self.ref or "").strip():
            raise SurfaceError(f"an entity of kind {self.kind!r} with no ref cannot be navigated to")

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "ref": self.ref, "label": self.label[:MAX_TITLE_CHARS]}


@dataclass(frozen=True, slots=True)
class Linked:
    """Another surface this one can reach. Carrying the kind and the ref means a tap opens it
    without asking the model to rediscover what the server already knew."""

    entity: Entity
    relation: str
    label: str = ""
    count: int | None = None

    def __post_init__(self) -> None:
        if self.relation not in RELATIONS:
            raise SurfaceError(f"unknown relation {self.relation!r}; known: {', '.join(sorted(RELATIONS))}")

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {**self.entity.as_dict(), "relation": self.relation}
        if self.label:
            out["label"] = self.label[:MAX_TITLE_CHARS]
        if self.count is not None:
            out["count"] = int(self.count)
        return out


@dataclass(frozen=True, slots=True)
class Loading:
    """A region of the surface that is still being read.

    The point of naming these is that the rest of the surface does not wait. An order card
    goes up with its number, customer, total, status and items while the inbox is still being
    asked whether anyone wrote in about it; `region` is what the tablet greys, and `note` is
    what it says there meanwhile.
    """

    region: str
    note: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"region": self.region[:40], "note": self.note[:MAX_TITLE_CHARS]}


@dataclass(frozen=True, slots=True)
class Freshness:
    """Where the values came from and how old they are.

    A card that is showing a cached read must say so, because the owner is about to make a
    decision on it. This is presentation only: a write never trusts it and rereads
    authoritative state regardless (see app/actions/engine.py).
    """

    source: str = ""            # "shopify" | "gmail" | "cache" | "memory"
    age_s: float | None = None
    complete: bool = True
    caveat: str = ""

    def as_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"complete": bool(self.complete)}
        if self.source:
            out["source"] = self.source[:24]
        if self.age_s is not None:
            out["age_s"] = round(float(self.age_s), 1)
        if self.caveat:
            out["caveat"] = self.caveat[:MAX_TITLE_CHARS]
        return out


@dataclass(slots=True)
class Surface:
    """One interface on the tablet.

    `ui_type` is the renderer's name for it — the existing 25-name vocabulary in
    `presentation.UI_TYPES`, which the tablet dispatches on and which is deliberately
    unchanged. `surface_type` is what the interface is *for*. They are usually the same word
    and sometimes are not: an order list built from an analytic query and one built from
    `shopify_list_orders` render with the same component and are the same surface.
    """

    surface_type: str
    ui_type: str
    data: dict[str, Any]
    entity: Entity | None = None
    title: str = ""
    subtitle: str = ""
    actions: list[dict[str, Any]] = field(default_factory=list)
    linked: list[Linked] = field(default_factory=list)
    loading: list[Loading] = field(default_factory=list)
    freshness: Freshness | None = None
    spoken_summary: str = ""

    def __post_init__(self) -> None:
        if self.surface_type not in SURFACE_TYPES:
            raise SurfaceError(f"unknown surface_type {self.surface_type!r}; known: {', '.join(sorted(SURFACE_TYPES))}")
        if not isinstance(self.data, dict):
            raise SurfaceError(f"surface {self.surface_type!r} data must be a dict, not {type(self.data).__name__}")
        if len(self.linked) > MAX_LINKED:
            raise SurfaceError(f"surface {self.surface_type!r} links to {len(self.linked)} entities; the cap is {MAX_LINKED}")
        if len(self.loading) > MAX_LOADING:
            raise SurfaceError(f"surface {self.surface_type!r} names {len(self.loading)} loading regions; the cap is {MAX_LOADING}")

    def as_ui(self) -> dict[str, Any]:
        """The item as it goes on the wire.

        `type` and `data` are exactly what the tablet has always read. Everything else is a
        sibling key it may ignore, which is what makes this contract addable to a build that
        is already installed on the tablet at the workbench.
        """
        item: dict[str, Any] = {
            "type": self.ui_type,
            "data": self.data,
            "surface": self.surface_type,
            "surface_version": SURFACE_VERSION,
        }
        if self.entity is not None:
            item["entity"] = self.entity.as_dict()
        if self.title:
            item["title"] = self.title[:MAX_TITLE_CHARS]
        if self.subtitle:
            item["subtitle"] = self.subtitle[:MAX_TITLE_CHARS]
        if self.linked:
            item["linked_entities"] = [x.as_dict() for x in self.linked[:MAX_LINKED]]
        if self.loading:
            item["loading_regions"] = [x.as_dict() for x in self.loading[:MAX_LOADING]]
        if self.freshness is not None:
            item["freshness"] = self.freshness.as_dict()
        if self.spoken_summary:
            item["spoken_summary"] = self.spoken_summary[:MAX_SPOKEN_CHARS]
        return item


def entity_of(item: dict[str, Any]) -> dict[str, str] | None:
    """The entity a `ui` item is about.

    Prefers the envelope. Falls back to the key-sniffing that `app/routes/turn.py` did before
    this module existed, so a card built by a path not yet carrying an envelope still
    establishes the current entity rather than silently failing to.
    """
    named = item.get("entity")
    if isinstance(named, dict) and named.get("kind") and named.get("ref"):
        return {"kind": str(named["kind"]), "ref": str(named["ref"]), "label": str(named.get("label") or "")}
    data = item.get("data")
    if not isinstance(data, dict):
        return None
    for key, kind, label_key in (
        ("order_id", "order", "order_number"),
        ("customer_id", "customer", "customer_name"),
        ("thread_id", "email_thread", "subject"),
        ("product_id", "product", "title"),
    ):
        ref = data.get(key)
        if ref:
            return {"kind": kind, "ref": str(ref), "label": str(data.get(label_key) or "")}
    return None
