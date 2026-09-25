"""The general read tools: one bounded query language over the store's recent orders instead
of a tool for every question. `commerce_aggregate` counts and totals by product, size, colour,
day, customer…; `commerce_query` lists orders or customers that match; `inventory_query`
ranks variants by how soon they run out; `commerce_capabilities` says, concisely, what the
language can express. All of them read; none of them can change anything."""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from typing import Any

from app.analytics import engine
from app.analytics import sets as working_sets
from app.analytics.cache import OrderCache
from app.analytics.periods import MAX_DAYS, NAMED, Period
from app.analytics.query import (
    ALIASES,
    ENTITIES,
    FILTERS,
    GROUPS,
    LISTING_SORT_KEYS,
    MAX_COST,
    MAX_LIMIT,
    METRICS,
    TRACKING_UNAVAILABLE,
    TURN_COST,
    VIEWS,
    Query,
    QueryError,
    parse,
    shop_country_from,
)
from app.observability import timeline
from app.reads import fanout
from app.tools.context import current_session
from app.tools.gate import Tier
from app.tools.registry import ToolError, tool

log = logging.getLogger("crooks.analytics")

_cache: OrderCache | None = None
READ_TIMEOUT_S = 6.0
# The reads a unit of work may compose several of, within its bounds, and never the same
# one twice — app/analytics/plan.py hands back the earlier answer instead. A summary is
# one of them (app/families/summaries.py): it reads the same cache view a listing does,
# and the model asking the same summary question twice in one turn should cost one read.
PLANNED = frozenset({"commerce_aggregate", "commerce_query", "inventory_query",
                     "commerce_summary"})
# What the model reads of a result: never the membership lists the Mac keeps for itself.
_MODEL_HIDDEN = ("member_ids", "variant_ids")


def bind(cache: OrderCache | None) -> None:
    global _cache
    _cache = cache


def cache() -> OrderCache:
    if _cache is None:
        raise ToolError("The order cache is not configured on this backend.")
    return _cache


async def _now_and_zone() -> tuple[datetime, Any]:
    client = cache()._client()
    zone = await client.timezone()
    return datetime.now(zone), zone


async def _shop_country() -> str:
    """Where the shop ships from, for the "international" filter.

    No extra read: `timezone()` above has already made the client hold the shop, so this is a
    dictionary lookup with a settings override behind it. A shop that cannot be read at all
    falls back to the setting rather than failing the query — an unreadable shop is not a
    reason to refuse to list orders.
    """
    from config.settings import get_settings

    override = str(getattr(get_settings(), "shop_country_code", "") or "")
    try:
        shop = await cache()._client().shop()
    except Exception:  # noqa: BLE001 — the shop is a detail of one filter, not of the query
        shop = None
    return shop_country_from(shop if isinstance(shop, dict) else None, override)


def _error_words(exc: QueryError) -> str:
    """The refusal, with the schema that would have worked, short enough to be read.

    The tablet's planner met "sort by : not one of the metrics or groups asked for" three
    times in a row and each time invented another shape, because nothing in the refusal said
    what a right one looked like. This is the whole fix from the model's side: the accepted
    keys and one spec it can copy, in one line, under 500 characters with the prefix.
    """
    help_ = getattr(exc, "schema_help", None) or {}
    if not help_:
        return ""
    keys = [str(k) for k in (help_.get("accepted_sort_keys") or [])[:8]]
    example = json.dumps(help_.get("example") or {}, separators=(",", ":"))[:220]
    # The keys only when the refusal has not already named them — a sort refusal has, a bad
    # filter has not, and repeating them costs a third of the budget the whole error has.
    named = "" if keys and all(key in str(exc) for key in keys) else f" Sort keys: {', '.join(keys)}."
    return f"{named} Retry ONCE with this shape: {example}"


def sets_for(session: Any) -> dict[str, frozenset[str]]:
    """The working sets the conversation holds, as the engine wants them."""
    if session is None:
        return {}
    return working_sets.members_by_id(session)


def _model_view(result: Any) -> Any:
    if not isinstance(result, dict):
        return result
    out = {k: v for k, v in result.items() if k not in _MODEL_HIDDEN}
    if isinstance(out.get("rows"), list):
        out["rows"] = [{k: v for k, v in r.items() if k not in _MODEL_HIDDEN} for r in out["rows"] if isinstance(r, dict)]
    if isinstance(out.get("compare"), dict) and isinstance(out["compare"].get("rows"), list):
        out["compare"] = {**out["compare"], "rows": [{k: v for k, v in r.items() if k not in _MODEL_HIDDEN} for r in out["compare"]["rows"] if isinstance(r, dict)]}
    return out


def _sets_in(query: Query) -> None:
    session = current_session()
    for key in ("in_set", "not_in_set"):
        set_id = query.filters.get(key)
        if set_id and (session is None or working_sets.get(session, set_id) is None):
            raise ToolError(f"There is no working set {set_id} in this conversation. Use the set id the last listing gave you.")


def _set_from(result: dict[str, Any], query: Query, *, tool: str) -> dict[str, Any] | None:
    """The rows as a working set, when they are things with ids: a listing's orders or
    customers, a ranking's products, variants or customers. A narrowing of a set is a new
    set that remembers its parent."""
    session = current_session()
    if session is None:
        return None
    kind = None
    members: list[str] = []
    sample: list[dict[str, Any]] = []
    labels: dict[str, str] = {}
    if query.entity == "orders":
        kind = "orders"
        members = [str(m) for m in result.get("member_ids") or []]
        rows = [r for r in result.get("rows") or [] if isinstance(r, dict)]
        sample = [{"ref": r.get("order_id"), "label": r.get("order_number")} for r in rows][:5]
        labels = {str(r.get("order_id")): str(r.get("order_number") or "") for r in rows if r.get("order_id") and r.get("order_number")}
        labels.update({str(m): str(n) for m, n in (result.get("member_labels") or {}).items() if n})
    elif query.entity in ("customers", "products", "variants"):
        id_key = {"customers": "customer_id", "products": "product_id", "variants": "variant_id"}[query.entity]
        kind = query.entity
        # Every member the ranking matched (the engine's member_ids), not only the rows shown
        # — unless the model asked for a number, when the set is exactly those rows.
        members = [str(m) for m in result.get("member_ids") or []]
        labels = {str(m): str(n) for m, n in (result.get("member_labels") or {}).items() if n}
        for r in result.get("rows") or []:
            key = r.get("key") if isinstance(r, dict) and isinstance(r.get("key"), dict) else {}
            if key.get(id_key):
                if not members or str(key[id_key]) not in labels:
                    labels[str(key[id_key])] = str(r.get("label") or "")
                if str(key[id_key]) not in members:
                    members.append(str(key[id_key]))
                if len(sample) < 5:
                    sample.append({"ref": key[id_key], "label": r.get("label")})
    if kind is None or not members:
        return None
    label = query.title or _describe(query)
    totals = {k: v for k, v in (result.get("totals") or {}).items() if k in ("orders", "revenue", "units", "customers", "unfulfilled_value")}
    parent_id = query.filters.get("in_set")
    parent = working_sets.get(session, parent_id) if parent_id else None
    if parent is not None:
        ws = working_sets.derive(session, parent, members=members, label=label, step="filter", kind=kind if kind == parent.kind else kind, detail={"tool": tool, "filters": {k: v for k, v in query.filters.items() if k != "in_set"}, "entity": query.entity}, sample=sample, totals=totals, labels={**{m: parent.labels[m] for m in members if m in parent.labels}, **labels})
    else:
        ws = working_sets.create(session, kind=kind, members=members, label=label, provenance={"tool": tool, "step": "query", "query": {"entity": query.entity, "period": query.period.label, "filters": dict(query.filters), "group_by": list(query.group_by)}}, sample=sample, totals=totals, labels=labels)
    timeline.emit("working_set", session_id=getattr(session, "session_id", None), turn_id=getattr(session, "turn_id", None) or None, set_id=ws.set_id, set_kind=ws.kind, count=ws.count, label=ws.label, parent=ws.parent, step=ws.step, tool=tool)
    return ws.public()


def _describe(query: Query) -> str:
    """A label for a set from its query, in plain words: "unfulfilled orders older than 5 days, last 90 days"."""
    words = []
    f = query.filters
    if f.get("fulfillment") and f["fulfillment"] != "any":
        words.append(f["fulfillment"])
    if f.get("payment") and f["payment"] != "any":
        words.append(f["payment"].replace("_", " "))
    words.append(query.entity.replace("_", " "))
    if f.get("product"):
        words.append(f"with {f['product']}")
    if f.get("older_than_days"):
        words.append(f"older than {f['older_than_days']} days")
    if f.get("country_code"):
        words.append(f"from {f['country_code']}")
    if f.get("international") is True:
        words.append("going abroad")
    elif f.get("international") is False:
        words.append("staying in the country")
    if f.get("min_spent"):
        words.append(f"over {f['min_spent']:.0f} spent")
    if f.get("min_orders"):
        words.append(f"{f['min_orders']}+ orders")
    return (" ".join(words) + f", {query.period.label}")[:80]


async def _run(spec: dict[str, Any], *, default_entity: str, tool: str = "commerce_aggregate") -> dict[str, Any]:
    now, zone = await _now_and_zone()
    country = await _shop_country()
    try:
        query = parse(spec, now=now, tz=zone, default_entity=default_entity, shop_country=country)
    except QueryError as exc:
        # What was asked for and does not exist in the language (a filter, a group, a metric)
        # is a dimension the report counts as worth adding — never something to bend to.
        session = current_session()
        timeline.emit(
            "query_rejected", session_id=getattr(session, "session_id", None), turn_id=(getattr(session, "turn_id", "") or None) if session is not None else None,
            tool=tool, entity=str(spec.get("entity") or default_entity)[:40], unknown=[str(u)[:40] for u in exc.unknown][:8] or None, reason=str(exc)[:200],
        )
        raise ToolError(f"Query not understood: {exc}{_error_words(exc)}") from exc
    _sets_in(query)
    session = current_session()
    if session is not None:
        try:
            session.last_query = {"tool": tool, "entity": query.entity, "period": query.period.label, "filters": dict(query.filters), "group_by": list(query.group_by), "metrics": list(query.metrics), "sort": [list(x) for x in query.sort], "limit": query.limit, "compare": query.compare}
        except AttributeError:
            pass
    started = time.perf_counter()
    window = query.period.previous().start if query.compare else query.period.start
    view = await cache().view(Period(window, query.period.end, query.period.label, query.period.kind), timeout_s=READ_TIMEOUT_S)
    stock: dict[str, dict[str, Any]] = {}
    if query.needs_stock:
        selected = engine.select(view.rows, query.period, query.filters, now=now.timestamp(), sets=sets_for(current_session()), shop_country=country)
        wanted = {i["variant_id"] for o in selected for i in engine.matching_items(o, query.filters) if i.get("variant_id")}
        stock = await cache().stock(sorted(wanted)[:400], timeout_s=READ_TIMEOUT_S)
    result = engine.aggregate(query, view.rows, now=now.timestamp(), tz=zone, stock=stock, sets=sets_for(current_session()))
    result["complete"] = view.complete and not result.get("truncated", False) or (view.complete and result.get("truncated", False))
    result["coverage"] = {"complete": view.complete, "covered_days": view.covered_days, "read_age_s": (round(view.age_s, 1) if view.age_s is not None else None), "note": view.note or None}
    result["source"] = "Shopify orders created in the period" + (f", as read by the server {round(view.age_s)} s ago" if view.age_s is not None else "")
    result["cost"] = query.cost
    result["_ms"] = round((time.perf_counter() - started) * 1000 + view.served_ms, 1)
    if view.note:
        result["note"] = (result.get("note") + " " if result.get("note") else "") + view.note
    if query.entity in ("orders", "customers", "products", "variants") and not query.compare:
        made = _set_from(result, query, tool=tool)
        if made is not None:
            result["set"] = made
    return result


# --------------------------------------------------------------------------- the tools

_PERIOD_DESC = "today, yesterday, this_week, last_week, this_month, last_month, last_7_days, last_30_days, last_90_days, since_launch, {\"days\": N} or {\"start\",\"end\"}. Default last_30_days."
_FILTERS_LIST = (
    "fulfillment (unfulfilled|partial|fulfilled), payment (paid|unpaid|pending|refunded), "
    "international (true = outside the shop's country), country_code, city, older_than_days "
    "(= age_days), has_tracking, min_total, tags, product ('pink joggers'), customer_id, in_set; "
    "customers: min_orders, min_spent, repeat, no_later_order. No delivered/undelivered filter: "
    "no carrier is connected."
)
_FILTERS_GROUPED = (
    "product ('pink joggers'), variant, sku, size, colour, product_type, fulfillment, payment, "
    "international, country_code, older_than_days, tags, min_units, in_set. "
    "commerce_capabilities lists every filter and its aliases."
)
_SORT_DESC = (
    "created_at, total, age_days, or \"oldest\"/\"newest\"/\"waiting longest\"/\"highest value\"; "
    "\"total desc\", {metric, direction}, or a list. Default newest first."
)
_VIEW_DESC = "auto (default), ranking, table, comparison, matrix, metrics, trend or list."


@tool(
    name="commerce_aggregate",
    description=(
        "Count and total orders over a period, grouped and sorted as asked: best sellers by units "
        "or revenue, sales by size, colour or day, customers by spend, average order value, this "
        "period against the one before. Nearly any question about what sold, to whom, when, is one call."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "entity": {"type": "string", "description": "order_line_items (default; what sold), orders, customers, products or variants."},
            "period": {"description": _PERIOD_DESC},
            "filters": {"type": "object", "description": _FILTERS_GROUPED},
            "group_by": {"type": "array", "items": {"type": "string"}, "description": "Up to two of product, product_type, variant, size, colour, day, week, month, customer, country, fulfillment, payment."},
            "metrics": {"type": "array", "items": {"type": "string"}, "description": "units, revenue, orders, customers, aov, refunded, unfulfilled_value, share; variants/products: stock, velocity, days_cover; customers: lifetime_orders, lifetime_spent."},
            "sort": {"description": "{metric, direction} or \"units desc\": a metric or group asked for. Default the first, descending."},
            "limit": {"type": "integer", "description": f"1-{MAX_LIMIT}, default 10."},
            "compare": {"type": "boolean", "description": "Also the period before, with the change."},
            "view": {"type": "string", "description": _VIEW_DESC},
            "title": {"type": "string", "description": "A short card title in the owner's words."},
        },
    },
    tier=Tier.GREEN,
    model_view=_model_view,
)
async def commerce_aggregate(entity: str = "order_line_items", period: Any = None, filters: dict | None = None, group_by: Any = None, metrics: Any = None, sort: Any = None, limit: int = 10, compare: bool = False, view: str = "auto", title: str = "") -> dict:
    return await _run({"entity": entity, "period": period, "filters": filters or {}, "group_by": group_by, "metrics": metrics, "sort": sort, "limit": limit, "compare": compare, "view": view, "title": title}, default_entity="order_line_items")


@tool(
    name="commerce_query",
    description=(
        "List the orders or customers that match: unfulfilled orders older than five days, customers "
        "who bought the pink joggers and nothing since. The list becomes a working set ('these'): its "
        "set_id is in the result, and later calls narrow it with filters.in_set."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "entity": {"type": "string", "description": "orders (default) or customers."},
            "period": {"description": _PERIOD_DESC},
            "filters": {"type": "object", "description": _FILTERS_LIST},
            "sort": {"description": _SORT_DESC},
            "limit": {"type": "integer", "description": f"Rows shown (1-{MAX_LIMIT}). Unset, the set holds every match; set, just these rows."},
            "metrics": {"type": "array", "items": {"type": "string"}, "description": "Customers only: orders, revenue, lifetime_orders, lifetime_spent."},
            "title": {"type": "string", "description": "A short name for the set, in the owner's words."},
        },
    },
    tier=Tier.AMBER,
    model_view=_model_view,
)
async def commerce_query(entity: str = "orders", period: Any = None, filters: dict | None = None, sort: Any = None, limit: int = 25, metrics: Any = None, title: str = "") -> dict:
    spec = {"entity": entity, "period": period, "filters": filters or {}, "sort": sort, "limit": limit, "metrics": metrics, "view": "list", "title": title}
    if str(entity or "").strip().lower() not in ("orders", "order", "customers", "customer"):
        raise ToolError("commerce_query lists orders or customers; for products, sizes or sales use commerce_aggregate.")
    return await _run(spec, default_entity="orders", tool="commerce_query")


@tool(
    name="inventory_query",
    description=(
        "Which variants are running out: stock beside units sold over the period, with the velocity "
        "(units a day) and estimated days of cover derived from them, soonest out first. Narrow to a "
        "product, colour or size. Cover is an estimate, not a forecast."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "period": {"description": "The sales window for the velocity; default last_7_days."},
            "product": {"type": "string", "description": "Words that name the product(s), e.g. 'joggers'."},
            "colour": {"type": "string"}, "size": {"type": "string"},
            "limit": {"type": "integer", "description": f"1-{MAX_LIMIT}, default 10."},
            "max_days_cover": {"type": "number", "description": "Only variants with this much cover or less."},
            "title": {"type": "string"},
        },
    },
    tier=Tier.GREEN,
    model_view=_model_view,
)
async def inventory_query(period: Any = None, product: str = "", colour: str = "", size: str = "", limit: int = 10, max_days_cover: float | None = None, title: str = "") -> dict:
    filters: dict[str, Any] = {}
    if product:
        filters["product"] = product
    if colour:
        filters["colour"] = colour
    if size:
        filters["size"] = size
    spec = {"entity": "variants", "period": period or "last_7_days", "filters": filters, "group_by": ["variant"], "metrics": ["stock", "units", "velocity", "days_cover"], "sort": [{"metric": "days_cover", "direction": "asc"}], "limit": limit, "view": "ranking", "title": title or "Restock priority"}
    result = await _run(spec, default_entity="variants", tool="inventory_query")
    if max_days_cover is not None:
        try:
            bound = float(max_days_cover)
        except (TypeError, ValueError) as exc:
            raise ToolError("max_days_cover is a number of days.") from exc
        result["rows"] = [r for r in result["rows"] if r.get("days_cover") is not None and r["days_cover"] <= bound]
    result["note"] = (
        f"Velocity is units sold over the last {int(round(float(result['period']['days'])))} day(s) divided by the days; cover is stock divided by that — "
        "an estimate from recent sales, not a forecast. A variant with no sales in the period has no cover to estimate; one Shopify does not track has no stock figure."
    ) + (" " + result["note"] if result.get("note") else "")
    result["mode"] = "restock_priority"
    return result


# --------------------------------------------------------------------- the inbox beside a set

_threads_for = None       # gmail_tools.threads_for, or a test's stand-in
_replied = None           # async (thread_id) -> bool | None
_email_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}
EMAIL_CACHE_S = 300.0
# As many customers as a batch takes members (app/actions/batch.py MAX_BATCH): the flow
# "who has emailed → a draft to the rest" must not break at the size a batch allows.
EMAIL_MAX_CUSTOMERS = 50
EMAIL_VIEW_DAYS = 90
# How many of these inbox reads run at once is NOT decided here: it is
# app/reads/budget.py SOURCE_SLOTS["gmail"], read through app/reads/fanout.py, so that this
# tool and the read scheduler cannot disagree about how much of Gmail there is.
EMAIL_TIMEOUT_S = 7.0
EMAIL_THREADS_PER_CUSTOMER = 3


_reply_state = None       # async (thread_id) -> the thread's own direction and stamps, or None
# Our own mailbox address (a string, or a callable that gives one), when the runtime binds it.
# A thread whose latest message is ours is outbound however it was found; without the address
# the SENT label on the message still says so, so this is belt and braces, not a requirement.
_own_address = None
# A sender that is a machine: nobody there is waiting on a reply, and a thread from one is
# not "the customer emailed us" however neatly it mentions an order number. Shopify's own
# abandoned-checkout and shipping notifications come from addresses like these.
_NOISE_SENDER = re.compile(
    r"(no[-_.]?reply|do[-_.]?not[-_.]?reply|notifications?@|mailer(?:-daemon)?@|bounce|newsletter|marketing@|"
    r"abandoned|checkout@|shipping-updates|postmaster@)",
    re.I,
)


def bind_email(threads_for=None, replied=None, reply_state=None, own_address=None) -> None:
    global _threads_for, _replied, _reply_state, _own_address
    _threads_for = threads_for
    _replied = replied
    _reply_state = reply_state
    _own_address = own_address
    _email_cache.clear()


def _own() -> str:
    try:
        value = _own_address() if callable(_own_address) else _own_address
    except Exception:  # noqa: BLE001 — a profile read that fails is "unknown", not a crash
        return ""
    return str(value or "").strip().lower()


def _noise(thread: dict[str, Any], own: str) -> str:
    """Why this thread does not count on the INBOUND side, or empty when it does.

    The September queue offered an automated carrier report as a customer waiting on a
    reply, and would have offered an abandoned-checkout nudge the same way: the listing found
    them by the order number in the subject, and nothing asked who wrote them.
    """
    sender = str(thread.get("from_email") or "").strip().lower()
    if thread.get("likely_bulk"):
        return "bulk"
    if sender and _NOISE_SENDER.search(sender):
        return "automated"
    if own and sender == own:
        return "ours"
    return ""


def _confidence(thread: dict[str, Any], email: str, terms: list[str]) -> str:
    """How sure it is that THIS thread is this customer writing about their order: their own
    address, vouched for by the receiving server or carrying their order number, is confident;
    anything else the listing turned up is possible. Never inferred from a name."""
    sender = str(thread.get("from_email") or "").strip().lower()
    theirs = bool(email) and sender == email.strip().lower()
    mentions = bool(_related_orders([thread], terms))
    if theirs and (thread.get("authenticated") or mentions):
        return "confident"
    return "possible"


def _related_orders(threads: list[dict[str, Any]], terms: list[str]) -> list[str]:
    """The customer's own order numbers that appear in these threads' subjects and snippets."""
    from app.context.graph import order_numbers_in

    wanted = {str(t).rsplit("-", 1)[-1].lstrip("#") for t in terms if t}
    found: list[str] = []
    for t in threads:
        for n in order_numbers_in(f"{t.get('subject', '')} {t.get('snippet', '')}"):
            if n in wanted and n not in found:
                found.append(n)
    return found


async def _customer_threads(email: str, terms: list[str], days: int, *, clock) -> dict[str, Any]:
    key = (email, days)
    held = _email_cache.get(key)
    now = clock()
    if held is not None and now - held[0] < EMAIL_CACHE_S:
        return held[1]
    found = await _threads_for(sender=email, terms=terms, days=days)
    own = _own()
    threads: list[dict[str, Any]] = []
    ignored: list[str] = []
    for t in found.get("threads") or []:
        if not isinstance(t, dict):
            continue
        why = _noise(t, own)
        if why:
            ignored.append(why)
        else:
            threads.append(t)
    looked_at = threads[:EMAIL_THREADS_PER_CUSTOMER]
    replied = None
    states: list[dict[str, Any]] = []
    checked_ids: list[str] = []
    if found.get("available") and looked_at:
        for t in looked_at:
            thread_id = str(t.get("thread_id") or "")
            if not thread_id:
                continue
            state = None
            if _reply_state is not None:
                try:
                    state = await _reply_state(thread_id)
                except Exception:  # noqa: BLE001 — unknown is an honest answer
                    state = None
            if state is not None:
                states.append(state)
                checked_ids.append(thread_id)
            elif _replied is not None:
                # No per-message view of this thread: fall back to "did anything go out",
                # which is weaker, and is recorded as weaker (no stamps to fold).
                try:
                    flag = await _replied(thread_id)
                except Exception:  # noqa: BLE001
                    flag = None
                if flag is not None:
                    replied = bool(replied) or bool(flag)
    folded = _fold_reply_states(states)
    if folded["checked_threads"]:
        replied = folded["has_reply_after_latest_inbound"]
    confidences = [_confidence(t, email, terms) for t in looked_at]
    confidence = "confident" if "confident" in confidences else ("possible" if confidences else "none")
    related = _related_orders(looked_at, terms)
    # Why the row says what it says, in one place, so the queue can print it and a test can
    # hold it: which threads were looked at, the stamps the answer turned on, and how sure the
    # link between this person and these threads is.
    provenance = {
        "threads_checked": len(states), "thread_ids": checked_ids,
        "latest_inbound_at": folded["latest_inbound_at"], "latest_outbound_at": folded["latest_outbound_at"],
        "latest_direction": folded["latest_direction"], "related_orders": related, "confidence": confidence,
        "ignored": len(ignored), "ignored_why": sorted(set(ignored)),
    }
    out = {
        "available": bool(found.get("available")), "reason": found.get("reason"), "threads": looked_at,
        "count": len(threads), "replied": replied, **folded,
        "related_orders": related, "confidence": confidence, "provenance": provenance,
    }
    _email_cache[key] = (now, out)
    return out


def _fold_reply_states(states: list[dict[str, Any]]) -> dict[str, Any]:
    """Several threads, one customer, one answer — WITHOUT merging the threads.

    A reply we sent in one thread does not answer a newer message that arrived in another.
    So the fold takes the latest inbound across all of them and the latest outbound across
    all of them, and asks whether we have spoken since they last did. That is the question
    "who is waiting on a reply" actually asks, and the September session showed the
    per-thread answer getting it wrong.
    """
    inbound = [s["latest_inbound_at"] for s in states if s.get("latest_inbound_at")]
    outbound = [s["latest_outbound_at"] for s in states if s.get("latest_outbound_at")]
    latest_in = max(inbound) if inbound else None
    latest_out = max(outbound) if outbound else None
    answered = bool(latest_in is not None and latest_out is not None and latest_out >= latest_in)
    if latest_in is None and latest_out is None:
        direction = "none"
    elif latest_out is None:
        direction = "inbound"
    elif latest_in is None:
        direction = "outbound"
    else:
        direction = "inbound" if latest_in > latest_out else "outbound"
    return {
        "checked_threads": len(states),
        "thread_count": len(states),
        "latest_inbound_at": latest_in,
        "latest_outbound_at": latest_out,
        "latest_direction": direction,
        "has_reply_after_latest_inbound": answered,
        "needs_reply": bool(latest_in is not None and not answered),
    }


@tool(
    name="email_query",
    description=(
        "For a working set of orders or customers: which of them have emailed us (recent inbox "
        "threads from the customer, mentioning their order), and which we have replied to. Makes "
        "derived sets: contacted and not contacted, so 'draft an apology to the rest' has an exact list."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "set_id": {"type": "string", "description": "The working set (orders or customers)."},
            "days": {"type": "integer", "description": "How far back to look in the inbox, default 30."},
        },
        "required": ["set_id"],
    },
    tier=Tier.AMBER,
    issued_id_args=("set_id",),
)
async def email_query(set_id: str, days: int = 30) -> dict:

    session = current_session()
    ws = working_sets.get(session, set_id) if session is not None else None
    if ws is None:
        raise ToolError(f"There is no working set {set_id} in this conversation.")
    if _threads_for is None:
        raise ToolError("Gmail is not configured on this backend.")
    if ws.kind not in ("orders", "customers"):
        raise ToolError(f"email_query takes a set of orders or customers; {set_id} is {ws.kind}.")
    days = max(1, min(int(days or 30), 365))
    now, zone = await _now_and_zone()
    # The window the listings read (never a year's backfill for an inbox question): a member
    # the Mac does not hold, or one with no customer record (a guest checkout), is counted as
    # unchecked and said so — never silently left out of "the rest".
    rows_view = await cache().view(Period(now - __import__("datetime").timedelta(days=EMAIL_VIEW_DAYS), now, "held", "days"), timeout_s=READ_TIMEOUT_S)
    by_customer: dict[str, dict[str, Any]] = {}
    held: set[str] = set()
    guests: list[str] = []
    for o in rows_view.rows:
        c = o.get("customer") or {}
        if ws.kind == "orders" and o["order_id"] not in ws.members:
            continue
        if ws.kind == "customers" and c.get("customer_id") not in ws.members:
            continue
        held.add(o["order_id"] if ws.kind == "orders" else str(c.get("customer_id")))
        if not c.get("customer_id"):
            guests.append(o["order_id"])
            continue
        entry = by_customer.setdefault(c["customer_id"], {"customer_id": c["customer_id"], "name": c.get("name"), "email": c.get("email"), "orders": [], "order_ids": []})
        entry["orders"].append(o.get("order_number"))
        entry["order_ids"].append(o["order_id"])
    missing = [m for m in ws.members if m not in held]
    if len(by_customer) > EMAIL_MAX_CUSTOMERS:
        raise ToolError(f"That set has {len(by_customer)} customers; the inbox is checked for at most {EMAIL_MAX_CUSTOMERS} at a time. Narrow the set first.")
    clock = cache().clock
    started = time.perf_counter()

    async def look(entry: dict[str, Any]) -> dict[str, Any]:
        if not entry.get("email"):
            return {"available": True, "threads": [], "count": 0, "replied": None, "reason": "no email address"}
        terms = [str(n).rsplit("-", 1)[-1].lstrip("#") for n in entry["orders"] if n]
        return await _customer_threads(entry["email"], terms[:3], days, clock=clock)

    # §14. This read really IS one per customer — Gmail has no query that answers "which of
    # these people have written to us" in one — so what is bounded is the concurrency, and it
    # is bounded by the SOURCE's own slots (app/reads/budget.py SOURCE_SLOTS["gmail"]) through
    # the global throttle, not by a semaphore of its own beside this call.
    #
    # It had one: `asyncio.Semaphore(EMAIL_CONCURRENCY)`, four, while SOURCE_SLOTS said three
    # — so this tool could hold four Gmail slots while the read scheduler believed three was
    # the whole of Gmail, and two bounds on one thing is how they come to disagree. One table,
    # read in one place (app/reads/fanout.py), which also reports what did not come back
    # instead of each entry catching its own exception into a reason string.
    entries = list(by_customer.values())
    landed, unreachable = await fanout.gather_with_failures(
        range(len(entries)), lambda index: look(entries[index]),
        source="gmail", timeout_s=EMAIL_TIMEOUT_S, limit=EMAIL_MAX_CUSTOMERS,
    )
    for index, entry in enumerate(entries):
        mail = landed[index] if index < len(landed) else None
        if isinstance(mail, dict):
            entry["mail"] = mail
        else:
            entry["mail"] = {"available": False, "threads": [], "count": 0, "replied": None,
                             "reason": str(unreachable.get(index) or "the inbox could not be checked")[:160]}
    rows = []
    contacted: list[str] = []
    not_contacted: list[str] = []
    replied: list[str] = []
    unavailable = 0
    for entry in by_customer.values():
        mail = entry["mail"]
        members = entry["order_ids"] if ws.kind == "orders" else [entry["customer_id"]]
        if not mail.get("available"):
            unavailable += 1
        has_mail = bool(mail.get("count"))
        (contacted if has_mail else not_contacted).extend(members)
        if mail.get("replied"):
            replied.extend(members)
        last = mail["threads"][0] if mail.get("threads") else {}
        rows.append({
            "customer_id": entry["customer_id"], "customer_name": entry.get("name"), "customer_email": entry.get("email"), "orders": entry["orders"][:5],
            "emailed": has_mail, "threads": int(mail.get("count") or 0), "replied": mail.get("replied"), "last_subject": str(last.get("subject") or "")[:80], "last_date": str(last.get("date") or "")[:32],
            "last_thread_id": str(last.get("thread_id") or ""), "checked": bool(mail.get("available")),
            # Across every thread this customer has with us, never merged: who spoke last,
            # when, and whether we have answered since they did.
            "thread_count": int(mail.get("thread_count") or 0),
            "latest_inbound_at": mail.get("latest_inbound_at"),
            "latest_outbound_at": mail.get("latest_outbound_at"),
            "latest_direction": mail.get("latest_direction") or ("none" if not has_mail else "unknown"),
            "has_reply_after_latest_inbound": mail.get("has_reply_after_latest_inbound"),
            "needs_reply": bool(mail.get("needs_reply")),
            # The customer's own order numbers found in their threads, how sure the link is,
            # and the whole account of how the row was decided (app/tools/analytics_tools.py
            # `_customer_threads`). The queue prints the first two; the report keeps the third.
            "related_orders": list(mail.get("related_orders") or []),
            "confidence": str(mail.get("confidence") or ("none" if not has_mail else "unknown")),
            "provenance": dict(mail.get("provenance") or {}),
        })
    # Waiting on us first: that is what the question is usually for.
    rows.sort(key=lambda r: (not r.get("needs_reply"), not r["emailed"], str(r.get("customer_name") or "")))
    unchecked = unavailable + len(missing) + len(guests)
    notes = []
    if unavailable:
        notes.append(f"{unavailable} customer(s) could not be checked in Gmail")
    if missing:
        notes.append(f"{len(missing)} of the set's {ws.kind} are outside the {EMAIL_VIEW_DAYS} days of orders the server holds")
    if guests:
        notes.append(f"{len(guests)} order(s) have no customer record to look up")
    result: dict[str, Any] = {
        "set_id": ws.set_id, "set_label": ws.label, "kind": ws.kind, "days": days, "customers": len(by_customer),
        "counts": {"contacted": sum(1 for r in rows if r["emailed"]), "not_contacted": sum(1 for r in rows if not r["emailed"] and r["checked"]), "replied": sum(1 for r in rows if r["replied"]), "needs_reply": sum(1 for r in rows if r.get("needs_reply")), "unchecked": unchecked},
        "rows": rows, "source": f"Gmail threads from each customer in the last {days} days, mentioning their order", "_ms": round((time.perf_counter() - started) * 1000, 1),
        "note": ("; ".join(notes) + "; they are counted in neither set." if notes else ""),
    }
    waiting = [m for r in rows if r.get("needs_reply") for m in ([r["customer_id"]] if ws.kind == "customers" else by_customer[r["customer_id"]]["order_ids"])]
    for name, members, words in (("contacted", contacted, "who have emailed us"), ("not_contacted", not_contacted, "who have not emailed us"), ("replied", replied, "we have replied to"), ("needs_reply", waiting, "waiting on a reply from us")):
        if members:
            # Side sets beside the parent: "these" stays the set the owner asked about; the
            # model names a derived set by its id when the owner says "the rest".
            made = working_sets.derive(session, ws, members=members, label=f"{ws.label} — {words}"[:80], step="correlate", detail={"tool": "email_query", "which": name, "days": days}, focus=False)
            result[f"set_{name}"] = made.public()
            if name == "needs_reply":
                result["needs_reply_set_id"] = made.set_id
            timeline.emit("working_set", session_id=session.session_id, turn_id=session.turn_id or None, set_id=made.set_id, set_kind=made.kind, count=made.count, label=made.label, parent=ws.set_id, step="correlate", tool="email_query", which=name)
    # The threads themselves, as a set of emails: what "archive those" would act on.
    thread_ids: list[str] = []
    thread_labels: dict[str, str] = {}
    for entry in by_customer.values():
        for t in (entry["mail"].get("threads") or []):
            tid = str(t.get("thread_id") or "")
            if tid and tid not in thread_labels:
                thread_ids.append(tid)
                thread_labels[tid] = str(t.get("subject") or "")[:60] or "(no subject)"
    if thread_ids:
        made = working_sets.derive(session, ws, members=thread_ids, label=f"{ws.label} — their emails"[:80], step="correlate", kind="emails", detail={"tool": "email_query", "which": "threads", "days": days}, labels=thread_labels, focus=False)
        result["set_threads"] = made.public()
        timeline.emit("working_set", session_id=session.session_id, turn_id=session.turn_id or None, set_id=made.set_id, set_kind=made.kind, count=made.count, label=made.label, parent=ws.set_id, step="correlate", tool="email_query", which="threads")
    timeline.emit("cross_source", session_id=session.session_id, turn_id=session.turn_id or None, set_id=ws.set_id, customers=len(by_customer), counts=result["counts"], ms=result["_ms"])
    return result


@tool(
    name="commerce_capabilities",
    description="What the read language can express: entities, periods, filters, groupings, metrics, views, examples. Call it before saying a question about sales, products, customers or stock cannot be answered.",
    input_schema={"type": "object", "properties": {}},
    tier=Tier.GREEN,
)
async def commerce_capabilities() -> dict:
    return catalogue()


def catalogue() -> dict[str, Any]:
    """The language, concisely, for the model and for the report."""
    return {
        "read_only": True,
        "entities": list(ENTITIES),
        "periods": list(NAMED) + ["{\"days\": N}", "{\"days\": N, \"days_ago\": M}", "{\"start\": \"YYYY-MM-DD\", \"end\": \"YYYY-MM-DD\"}"],
        "timezone": "Europe/London", "max_days": MAX_DAYS,
        "filters": {name: {"type": kind.split(":", 1)[0], "values": kind.split(":", 1)[1].split(",") if ":" in kind else None, "entities": list(entities), "aliases": list(aliases)} for name, (kind, entities, aliases) in FILTERS.items()},
        # Every other name that resolves to one of the filters above, so the model reads the
        # whole vocabulary rather than guessing at half of it.
        "filter_aliases": dict(sorted(ALIASES.items())),
        "sort_keys": {"orders": list(LISTING_SORT_KEYS) + ["oldest", "newest", "waiting_longest", "highest_value", "lowest_value"],
                      "grouped": "any metric or group_by asked for"},
        # What this Mac cannot answer, said once, here, so it is not discovered a query at a
        # time. `commerce_capabilities` is the answer to "can you?", and this is part of it.
        "not_available": {"delivery_status": TRACKING_UNAVAILABLE},
        # The summary read, and the read pattern it replaces. It lives here rather than in
        # `commerce_summary`'s own description because this file's byte budget
        # (tests/test_registry.py) says the detail belongs in the tool that is called on
        # demand, and because this is where a model that is about to compose a listing plus a
        # read per row will be looking. The numbers are measured in tests/test_n_plus_one.py.
        "summaries": {
            "tool": "commerce_summary",
            "tasks": {
                "returning_customers": "who bought in the period having bought before it, with each one's previous order, lifetime orders and lifetime spend",
                "orders_attention": "the orders that need something doing, worst first, with what is wrong with each",
                "order_list": "the period's orders as rows",
            },
            "instead_of": (
                "listing the period and then reading each customer's or each order's record. "
                "Every order row the server holds already carries that customer's lifetime order "
                "count and lifetime spend, so 'has this buyer bought before' is a comparison "
                "and not a lookup: one call in place of one plus one per row."
            ),
        },
        "group_by": list(GROUPS), "metrics": list(METRICS), "views": list(VIEWS),
        "bounds": {"limit": MAX_LIMIT, "group_by": 2, "cost_per_query": MAX_COST, "cost_per_turn": TURN_COST},
        "examples": [
            {"ask": "best sellers this month", "call": {"tool": "commerce_aggregate", "period": "this_month", "group_by": ["product"], "metrics": ["units", "revenue"], "view": "ranking"}},
            {"ask": "which size of the black joggers sells most", "call": {"tool": "commerce_aggregate", "entity": "variants", "filters": {"product": "black joggers"}, "group_by": ["size"], "metrics": ["units"]}},
            {"ask": "compare this week with last week", "call": {"tool": "commerce_aggregate", "entity": "orders", "period": "this_week", "metrics": ["orders", "revenue", "aov"], "compare": True, "view": "comparison"}},
            {"ask": "what needs restocking", "call": {"tool": "inventory_query", "period": "last_7_days"}},
            {"ask": "unfulfilled orders older than five days", "call": {"tool": "commerce_query", "entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled", "older_than_days": 5}}},
            {"ask": "international orders waiting too long", "call": {"tool": "commerce_query", "entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled", "international": True}, "sort": "oldest"}},
            {"ask": "are any orders undelivered", "call": {"tool": "commerce_query", "entity": "orders", "filters": {"fulfillment": "unfulfilled"}, "sort": "oldest"}, "note": TRACKING_UNAVAILABLE},
            {"ask": "customers who spent over £250", "call": {"tool": "commerce_aggregate", "entity": "customers", "period": "last_90_days", "filters": {"min_spent": 250}, "metrics": ["lifetime_spent", "lifetime_orders"]}},
            {"ask": "revenue tied up in unfulfilled orders", "call": {"tool": "commerce_aggregate", "entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled"}, "metrics": ["orders", "unfulfilled_value"], "view": "metrics"}},
        ],
    }


def cost_of(name: str, args: dict[str, Any]) -> int:
    """The estimate the plan charges before the tool runs; a query the language refuses costs one."""
    try:
        spec = dict(args)
        if name == "inventory_query":
            spec = {"entity": "variants", "period": spec.get("period") or "last_7_days", "metrics": ["days_cover"], "limit": spec.get("limit", 10)}
        elif name == "commerce_summary":
            # A summary's arguments are not the query language's — it takes a task and a
            # period — so they are priced as what it actually reads: the period's orders,
            # which is the same view a listing takes. Falling through to `parse` would raise
            # on `task` and charge one point for a ninety-day view.
            spec = {"entity": "orders", "period": spec.get("period") or "today",
                    "limit": spec.get("limit", 12)}
        return parse(spec, default_entity="orders" if name in ("commerce_query", "commerce_summary") else "order_line_items").cost
    except QueryError:
        return 1
