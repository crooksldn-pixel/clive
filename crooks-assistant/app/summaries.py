"""Task-specific result surfaces — §13, and §18's guarantee about the tap on them.

    turn_be1b384ca420   "Has anyone bought today that has bought before, a returning customer?"
    answer: one.        rendered: seven full customer cards, 265 px each, 1,949 px of deck.

The generated report filed that as DUPLICATE_RENDER. It is not: the seven ids are seven
different customers. The defect is that a **summary question was answered with entity
profiles**. A full customer card is the surface for a DRILLDOWN — "expand his customer page",
which is a different turn (D-5) and which workstream B owns. A summary question wants:

    RETURNING CUSTOMERS TODAY · 1
    Daniel Stub
    Order #1962
    Previous order: 31 Aug
    Lifetime: £120.00
    2 orders

— one surface, one row per person, and a tap on the row that opens the full workspace. Which
is the other half of this file. §18: *a row that offers a tap must have a resolvable
destination before it is drawn.* D-6 was a control posted into `open.entity` and refused
`not_held`, with `half_empty` drawn underneath it: a dead control. So `destination_for` below
answers the same question `app/commands.py::_open_entity` will be asked — has this
conversation been shown this id, is it an id of that kind, is there a tool that can re-read
it — BEFORE the row is drawn, and a row whose destination does not resolve is drawn without a
tap rather than with a dead one.

Three rules hold through every builder here:

* **No id on a normal surface** (§26). Every display string goes through `_human`, which
  refuses anything carrying a `gid://`; `assert_human` checks the finished surface again and
  raises rather than shipping one. `ref` is the one key allowed to hold an id, it is never
  drawn as text (web/ui.js `renderSummaryList` puts it in `data-ref` only), and it is there
  because the tablet has to be able to name the record back to the Mac — "the tablet names
  ids only" — not because anybody reads it.
* **Bounded.** A summary carries at most `MAX_ROWS` rows and says so when it truncated; the
  headline count is the whole truth even when the rows are not.
* **It carries no value the Mac did not measure.** Everything comes from
  app/analytics/summarise.py, which reads the order rows the cache already holds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.surfaces import Entity, Freshness, Surface, SurfaceError

# The one component this module draws with. Registered in app/presentation.py UI_TYPES and
# web/ui.js RENDERERS, and identified by app/render.py KEY_OF — a compact, row-based surface
# for a question whose answer is a count and a few lines each, not a deck of pages.
SUMMARY_UI = "summary_list"

# What a summary is. Not one of the entity surfaces: `surface_type` answers "which interface
# is this?", and a returning-customers summary is not a customer_list any more than it is a
# customer.
SUMMARY_SURFACE = "summary"

MAX_ROWS = 12
MAX_LINES = 4
MAX_TEXT = 80
MAX_NOTE = 200

# The kinds a compact row may hand off to, and the argument each is named by. Exactly the
# kinds app/commands.py REPLAY_TOOL can re-read — a row offering any other kind would post
# `open.entity` and be told "I cannot open a <kind> on its own".
TAPPABLE_KINDS: dict[str, str] = {
    "order": "order_id",
    "customer": "customer_id",
    "email_thread": "thread_id",
}

_CURRENCY_SYMBOL = {"GBP": "£", "USD": "$", "EUR": "€"}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class NotHuman(SurfaceError):
    """A display string carried an id. §26: the owner reads "#1962", never a gid."""


# --------------------------------------------------------------------------- words


def _human(value: Any, limit: int = MAX_TEXT) -> str:
    """A display string, or "" — never an id.

    A `gid://` in a name is not a formatting problem to be tidied, it is a value that came
    from the wrong field, so it becomes nothing and the caller's fallback speaks instead.
    That is deliberate: silently printing the tail of the gid would put "7975" on the glass
    as though it were a person.
    """
    text = " ".join(str(value if value is not None else "").split())
    if not text or "gid://" in text:
        return ""
    return text[:limit]


def order_words(value: Any) -> str:
    """The store names orders "CROOKS-1962" and older ones "#1036"; a row says #1962.

    The same rule as app/presentation.py `_order_number`, written here because this module
    must not import the entity presentation layer to format a number.
    """
    text = _human(value, 40)
    digits = text.rsplit("-", 1)[-1].lstrip("#").strip()
    return f"#{digits}" if digits.isdigit() else text


def money_words(amount: Any, currency: str = "GBP") -> str:
    try:
        number = float(amount)
    except (TypeError, ValueError):
        return ""
    symbol = _CURRENCY_SYMBOL.get(str(currency or "").upper())
    return f"{symbol}{number:,.2f}" if symbol else f"{number:,.2f} {currency}".strip()


def day_words(stamp: Any) -> str:
    """"31 Aug" — the shape the brief's own example uses. Empty when there is no date."""
    text = str(stamp or "").strip()
    if not text:
        return ""
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return f"{when.day} {_MONTHS[when.month - 1]}"


def plural(count: int, one: str, many: str = "") -> str:
    return one if count == 1 else (many or f"{one}s")


def customer_words(name: Any, email: Any, order_number: Any) -> str:
    """Who a row is about, in words. Never an id, and never blank.

    A guest checkout or a customer record with no display name used to leave a row labelled
    "—", which is a row nobody can act on. The order they placed names them instead: the
    owner knows who #1962 is, or can find out by tapping it.
    """
    return (
        _human(name)
        or _human(email)
        or (f"Whoever placed {order_words(order_number)}" if order_words(order_number) else "")
        or "A customer with no name on record"
    )


# ------------------------------------------------------------------ §18: the destination


def destination_for(session: Any, kind: str, ref: str) -> str:
    """The command a tap on this row would post, or "" when there is nowhere to go.

    Asks exactly what `app/commands.py::_open_entity` will ask, in the same order:

      1  is `kind` something that can be opened at all (TAPPABLE_KINDS == REPLAY_TOOL)
      2  is `ref` an id of that kind (app/tools/gate.py `id_kind_ok`)
      3  has this conversation been SHOWN that id (`session.issued_ids`)

    (3) is the one that matters and the one D-6 failed. It is a permission, not a cache
    check: the entity cache is shared by every conversation and a ref is one guess away from
    another conversation's customer, so a row may only offer a tap for a record this
    conversation has been given. `issue` below is how a builder gives one — the Mac drawing
    the row IS the showing, the same way app/presentation.py issues the ids on an email
    thread's order strip.
    """
    argument = TAPPABLE_KINDS.get(str(kind or ""), "")
    ref = str(ref or "").strip()
    if not argument or not ref:
        return ""
    from app.tools.gate import id_kind_ok

    if not id_kind_ok(argument, ref):
        return ""
    issued = getattr(session, "issued_ids", None) or frozenset()
    if ref not in issued:
        return ""
    return "open.entity"


def issue(session: Any, *refs: str) -> None:
    """Tell the conversation it has been shown these records.

    Called by a builder for the ids it is about to draw, and only for ids the Mac read from
    the shop in this conversation. It is not a widening of the gate: `id_kind_ok` still
    types them, the entity still has to be re-readable, and nothing here can issue an id that
    did not come out of a read.
    """
    give = getattr(session, "issue", None)
    if not callable(give):
        return
    give(*[str(r) for r in refs if str(r or "").strip()])


# --------------------------------------------------------------------------- the rows


@dataclass(slots=True)
class Row:
    """One compact row: a name, a line under it, a few facts, and somewhere to go.

    `tap` is never set by a caller. `as_dict` asks `destination_for` and sets it, so there is
    one place where "may this row be tapped" is decided and no way for a builder to promise a
    destination it has not checked.
    """

    label: str
    sub: str = ""
    lines: list[dict[str, str]] = field(default_factory=list)
    badge: str = ""
    tone: str = ""                      # "", "red", "amber", "good"
    ref: str = ""
    kind: str = ""

    def as_dict(self, session: Any) -> dict[str, Any]:
        command = destination_for(session, self.kind, self.ref) if self.ref and self.kind else ""
        out: dict[str, Any] = {
            "label": _require_human(self.label, "label") or "—",
            "sub": _require_human(self.sub, "sub"),
            "lines": [
                {"label": _require_human(line.get("label"), "line label"),
                 "value": _require_human(line.get("value"), "line value")}
                for line in self.lines[:MAX_LINES]
                if isinstance(line, dict) and (line.get("label") or line.get("value"))
            ],
            "badge": _require_human(self.badge, "badge", 24),
            "tone": self.tone if self.tone in ("red", "amber", "good") else "",
            "tap": bool(command),
        }
        if command:
            # The ref rides with the row because the tablet has to name the record back to
            # the Mac. It is the only value here that is not for reading, and the renderer
            # puts it in an attribute rather than in text.
            out["ref"] = str(self.ref)
            out["kind"] = str(self.kind)
            out["command"] = command
        return out


def _require_human(value: Any, what: str, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(value if value is not None else "").split())
    if "gid://" in text:
        raise NotHuman(f"a compact row's {what} carried an id ({text[:60]!r}); §26: #1962, never a gid")
    return text[:limit]


# ------------------------------------------------------------------------ the surface


def summary(
    *, task: str, title: str, rows: list[Row], count: int, count_label: str,
    session: Any = None, kicker: str = "", subtitle: str = "", note: str = "",
    truncated: bool = False, spoken: str = "", empty_words: str = "",
    entity: Entity | None = None, freshness: Freshness | None = None, set_id: str = "",
) -> Surface:
    """One compact surface for one task. The only way a summary reaches the glass.

    `count` is the WHOLE count and `rows` may be fewer: "four need attention" stays true on a
    surface that shows three of them and says so.

    `empty_words` is what the card says when the answer is none of them. It is the Mac's
    sentence and not the renderer's, because "no returning customers" and "nothing needs
    attention" are different sentences about different questions and the second one is not
    "no orders" — there were plenty of orders. D-15: an empty answer is an answer and gets a
    card; this is what is written on it.
    """
    drawn = [row.as_dict(session) for row in rows[:MAX_ROWS]]
    data: dict[str, Any] = {
        "task": str(task)[:40],
        "title": _require_human(title, "title"),
        "kicker": _require_human(kicker or "", "kicker", 40),
        "count": int(count),
        "count_label": _require_human(count_label, "count label", 40),
        "subtitle": _require_human(subtitle, "subtitle"),
        "rows": drawn,
        "note": _require_human(note, "note", MAX_NOTE),
        "truncated": bool(truncated) or len(rows) > MAX_ROWS,
        "empty": not drawn,
        "empty_words": _require_human(empty_words or f"No {count_label}.", "empty words", MAX_NOTE),
        "tappable": sum(1 for row in drawn if row.get("tap")),
    }
    if set_id:
        data["set_id"] = str(set_id)[:40]
    built = Surface(
        surface_type=SUMMARY_SURFACE, ui_type=SUMMARY_UI, data=data,
        title=data["title"], subtitle=data["subtitle"], entity=entity,
        freshness=freshness, spoken_summary=spoken,
    )
    assert_human(built)
    return built


def assert_human(surface: Surface | dict[str, Any]) -> None:
    """No id in anything the owner can read. Raised at build time, never shipped.

    Walks the whole payload and refuses a `gid://` anywhere except the two keys that exist to
    carry one — so a builder that puts a customer id in a subtitle, or a later change that
    adds a field and forgets `_human`, is a crash in the tests rather than a gid on the glass.
    """
    data = surface.data if isinstance(surface, Surface) else (surface.get("data") if isinstance(surface, dict) else surface)
    _walk(data, path="data")


_REF_KEYS = frozenset({"ref", "set_id"})


def _walk(value: Any, *, path: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _REF_KEYS:
                continue
            _walk(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _walk(item, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and "gid://" in value:
        raise NotHuman(f"{path} carries an id ({value[:60]!r}); §26: a normal surface says #1962")


# ------------------------------------------------------------- returning customers (D-4)


def returning_customers(found: dict[str, Any], *, session: Any = None, period: str = "today",
                        freshness: Freshness | None = None) -> Surface:
    """turn_be1b384ca420's surface: the count, and one row each.

    `found` is app/analytics/summarise.py `returning_customers` — measured from the order
    rows the Mac holds, at the cost of the one cache view the question needed anyway.
    """
    rows_in = [r for r in (found.get("rows") or []) if isinstance(r, dict)]
    if session is not None:
        # Drawn is shown: the ids of the records these rows point at are issued to this
        # conversation so the tap has somewhere to go (§18). Only the ids that came out of
        # the read — never a guess, never another conversation's.
        issue(session, *[r.get("customer_id") for r in rows_in])
    count = int(found.get("count") or len(rows_in))
    currency = str(found.get("currency") or "GBP")
    rows: list[Row] = []
    for r in rows_in:
        lifetime_orders = int(r.get("lifetime_orders") or 0)
        lines = [
            {"label": "Previous order",
             "value": day_words(r.get("previous_at")) if r.get("previous_known")
             else "before the server's window"},
            {"label": "Lifetime", "value": money_words(r.get("lifetime_spent"), currency)},
            {"label": plural(lifetime_orders, "Order"), "value": str(lifetime_orders)},
        ]
        rows.append(Row(
            label=customer_words(r.get("name"), r.get("email"), r.get("order_number")),
            sub=f"Order {order_words(r.get('order_number'))}" if order_words(r.get("order_number")) else "",
            lines=[line for line in lines if line["value"]],
            badge="Returning", tone="good",
            ref=str(r.get("customer_id") or ""), kind="customer",
        ))
    orders = int(found.get("orders_in_window") or 0)
    buyers = int(found.get("buyers") or 0)
    subtitle = f"{buyers} {plural(buyers, 'buyer')} · {orders} {plural(orders, 'order')} {period}" if buyers else ""
    note = ""
    if found.get("guests"):
        guests = int(found["guests"])
        note = f"{guests} {plural(guests, 'order')} {period} had no customer record, so cannot be checked."
    return summary(
        task="returning_customers", session=session,
        kicker="Returning customers",
        title=f"Returning customers {period}",
        count=count, count_label=plural(count, "returning customer"),
        subtitle=subtitle, note=note, rows=rows,
        truncated=bool(found.get("truncated")),
        spoken=_returning_words(count, period),
        empty_words=_returning_words(0, period),
        freshness=freshness,
    )


def _returning_words(count: int, period: str) -> str:
    if not count:
        return f"Nobody who bought {period} had bought before."
    if count == 1:
        return f"One — one of {period}'s buyers had bought before."
    return f"{count} of {period}'s buyers had bought before."


# ----------------------------------------------------------------- orders that need work


def attention_rows(found: dict[str, Any], *, session: Any = None, period: str = "",
                   freshness: Freshness | None = None) -> Surface:
    """"Which orders need attention?" — compact attention rows.

    From the cache rows alone (app/analytics/summarise.py `orders_needing_attention`), so the
    answer costs the listing's read and nothing per order.
    """
    rows_in = [r for r in (found.get("rows") or []) if isinstance(r, dict)]
    if session is not None:
        issue(session, *[r.get("order_id") for r in rows_in])
    count = int(found.get("count") or len(rows_in))
    currency = str(found.get("currency") or "GBP")
    rows: list[Row] = []
    for r in rows_in:
        who = _human(r.get("customer_name")) or _human(r.get("customer_email"))
        lines = [
            {"label": "Placed", "value": day_words(r.get("placed_at"))},
            {"label": "Value", "value": money_words(r.get("total"), currency)},
        ]
        rows.append(Row(
            label=order_words(r.get("order_number")) or "An order with no number on record",
            sub=" · ".join(p for p in (_human(r.get("headline"), 40), _human(r.get("detail"), 60)) if p),
            lines=[line for line in lines if line["value"]],
            badge=who, tone=str(r.get("level") or ""),
            ref=str(r.get("order_id") or ""), kind="order",
        ))
    considered = int(found.get("considered") or 0)
    red, amber = int(found.get("red") or 0), int(found.get("amber") or 0)
    parts = [f"{red} urgent" if red else "", f"{amber} worth a look" if amber else ""]
    where = f" {period}" if period else ""
    # A question asked of no period was read over a lookback, not the whole shop: the card and
    # the words say how far back, and an order older than that is never answered for (F-02).
    lookback = 0 if period else int(found.get("lookback_days") or 0)
    if lookback:
        note = (f"Read from the {considered} {plural(considered, 'order')} placed in the last {lookback} days; "
                if considered else f"No orders were placed in the last {lookback} days; ") + "older orders were not checked."
    else:
        note = f"Read from the {considered} {plural(considered, 'order')} the server holds." if considered else ""
    return summary(
        task="orders_attention", session=session,
        kicker="Needs attention",
        title=f"Orders that need attention{where}",
        count=count, count_label=plural(count, "order"),
        subtitle=" · ".join(p for p in parts if p),
        note=note,
        rows=rows, truncated=bool(found.get("truncated")),
        spoken=_attention_words(count, red, lookback),
        empty_words=_attention_words(0, 0, lookback),
        freshness=freshness,
    )


def _attention_words(count: int, red: int, days: int = 0) -> str:
    within = f" placed in the last {days} days" if days else ""
    if not count:
        return f"Nothing{within} needs attention."
    verb = "needs" if count == 1 else "need"
    if red:
        return f"{count} {plural(count, 'order')}{within} {verb} attention; {red} {'is' if red == 1 else 'are'} urgent."
    return f"{count} {plural(count, 'order')}{within} {verb} attention, none of them urgent."


# ------------------------------------------------------------------- a period's orders


def order_rows(found: dict[str, Any], *, session: Any = None, period: str = "today",
               set_id: str = "", freshness: Freshness | None = None) -> Surface:
    """"Show yesterday's orders" — rows, never a page each.

    The `order_list` card the Mac already had is compact and stays the surface for a listing
    the owner walks with a cursor. This is the surface for a listing that ANSWERS something:
    it carries the same rows with the question's own headline on them, one card, no second
    card saying the same count.
    """
    rows_in = [r for r in (found.get("rows") or []) if isinstance(r, dict)]
    if session is not None:
        issue(session, *[r.get("order_id") for r in rows_in])
    count = int(found.get("count") or len(rows_in))
    currency = str(found.get("currency") or "GBP")
    rows: list[Row] = []
    for r in rows_in:
        shipped = str(r.get("fulfillment") or "").upper() == "FULFILLED"
        rows.append(Row(
            label=order_words(r.get("order_number")) or "An order with no number on record",
            sub=customer_words(r.get("customer_name"), "", r.get("order_number")),
            lines=[line for line in (
                {"label": "Placed", "value": day_words(r.get("placed_at"))},
                {"label": "Total", "value": money_words(r.get("total"), currency)},
            ) if line["value"]],
            badge="Shipped" if shipped else "To ship",
            tone="good" if shipped else "amber",
            ref=str(r.get("order_id") or ""), kind="order",
        ))
    to_ship = int(found.get("to_ship") or 0)
    value = money_words(found.get("value"), currency)
    parts = [value, f"{to_ship} still to go out" if to_ship else ""]
    return summary(
        task="order_list", session=session,
        kicker="Orders",
        title=f"Orders {period}",
        count=count, count_label=plural(count, "order"),
        subtitle=" · ".join(p for p in parts if p),
        rows=rows, truncated=bool(found.get("truncated")), set_id=set_id,
        spoken=_order_list_words(count, period, to_ship),
        empty_words=_order_list_words(0, period, 0),
        freshness=freshness,
    )


def _order_list_words(count: int, period: str, to_ship: int) -> str:
    if not count:
        return f"No orders {period}."
    words = f"{count} {plural(count, 'order')} {period}"
    return f"{words}; {to_ship} still to go out." if to_ship else f"{words}."


# ------------------------------------------------------------------------- freshness


def freshness_of(coverage: Any, *, source: str = "shopify") -> Freshness:
    """Where a summary's figures came from and how old they are.

    A summary is a number the owner is about to act on, so the surface says whether the rows
    behind it are the whole period or as much of it as the Mac holds.

    Takes the `coverage` DICT a read tool publishes — `{complete, covered_days, read_age_s}` —
    rather than the cache's own view object. The object would otherwise have to ride on the
    tool result to reach here, and everything on a tool result is shown to the model and
    written to the turn log: a read's internal object has no business in either.
    """
    held = coverage if isinstance(coverage, dict) else {}
    complete = bool(held.get("complete", True))
    age = held.get("read_age_s")
    covered = held.get("covered_days")
    caveat = "" if complete else (
        f"the server holds {covered:.0f} days of orders; the rest of the period is not in this"
        if isinstance(covered, (int, float)) else "part of the period is not in this"
    )
    return Freshness(source=source, age_s=float(age) if isinstance(age, (int, float)) else None,
                     complete=complete, caveat=caveat)

