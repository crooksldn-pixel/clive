"""The summary read — D-4, §13, §14, §36.

    turn_be1b384ca420   "Has anyone bought today that has bought before, a returning customer?"
      12,895 ms, of which 12,116 ms was the model
      tools:   shopify_customer_history x 7, one per candidate customer
      rendered: seven full customer profile cards, 1,949 px of deck
      answer:   one. Correct.

The question is a filter over rows the Mac already holds and the answer is a count, so the
model gets ONE read tool for it: `commerce_summary` — the cache view the question needed and
nothing else, with the aggregation done on the Mac (app/analytics/summarise.py). The model
asks the question with one call instead of seven.

What is NOT here: the full customer workspace. A tap on a row posts `open.entity` and the Mac
reads that ONE record — the drilldown happens for the one the owner asked about, not for all
seven before he has said which.
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from typing import Any

from app.analytics import sets as working_sets
from app.analytics import summarise
from app.analytics.periods import Period, PeriodError, resolve
from app.capabilities.families import CapabilityFamily
from app.capabilities.families import register as register_family
from app.summaries import (
    customer_words,
    day_words,
    order_words,
)
from app.tools.context import current_session
from app.tools.gate import Tier
from app.tools.registry import ToolError, tool

log = logging.getLogger("crooks.families.summaries")

READ_TOOL = "commerce_summary"
READ_TIMEOUT_S = 6.0

# One read answers any of these. The bound is the point of the file: D-4 spent seven.
MAX_READS = 1

# The tasks, and what each one is called in the owner's words.
TASKS: dict[str, str] = {
    "returning_customers": "who bought in the period and had bought before it",
    "orders_attention": "the orders that need something doing",
    "order_list": "the period's orders, as rows",
}

# How far back a task looks BEYOND its own period, so that "had bought before" has something
# to be before. Ninety days is the cache's own warm window (app/analytics/cache.py
# WARM_DAYS), so this asks for what the Mac already keeps and adds no provider call in the
# ordinary case. A customer whose previous order is older than that is still counted as
# returning — Shopify's own lifetime count says so — and the row says the date is not held
# rather than inventing one.
LOOKBACK_DAYS: dict[str, int] = {"returning_customers": 90, "orders_attention": 90, "order_list": 0}

MAX_ROWS = 25


def _without_members(result: Any) -> Any:
    """What the MODEL is told. Never the membership list: it is the Mac's to hold, it can be
    five hundred long, and the model has the set's id if it wants to act on the whole of it —
    the same line app/tools/analytics_tools.py `_model_view` draws for `member_ids`."""
    if not isinstance(result, dict):
        return result
    return {k: v for k, v in result.items() if k != "members"}


def _period_of(period: Any, now, zone):
    try:
        return resolve(period or "today", now=now)
    except PeriodError as exc:
        raise ToolError(f"Period not understood: {exc}") from exc


@tool(
    name=READ_TOOL,
    # Terse on purpose. The tool block is what every turn on the model path pays for
    # (tests/test_registry.py), and that test's rule for the read layer is that the DETAIL
    # belongs in `commerce_capabilities`, called on demand — so the account of why this beats
    # a listing plus a read per row is there, under "summaries", and what stays here is the
    # one sentence that changes what the model does.
    description=(
        "A period summarised in one call: returning_customers (bought in it, having bought "
        "before), orders_attention, order_list. Never read each customer or order on a list "
        "to answer one of these."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "returning_customers, orders_attention or order_list."},
            "period": {"description": "today (default), yesterday, this_week, last_week, this_month, last_month, last_7_days."},
            "limit": {"type": "integer", "description": f"rows shown, 1-{MAX_ROWS}, default 12; the count is always the whole count."},
        },
        "required": ["task"],
    },
    tier=Tier.GREEN,
    model_view=_without_members,
)
async def commerce_summary(task: str, period: Any = None, limit: int = 12) -> dict:
    """One cache view, one pass of pure aggregation, no per-entity read.

    The cache is the same one `commerce_query` uses, so a turn that has already listed the
    period is answered from a warm view and this costs no Shopify call at all.
    """
    from app.tools import analytics_tools

    task = str(task or "").strip()
    if task not in TASKS:
        raise ToolError(f"task is one of {', '.join(sorted(TASKS))}.")
    limit = max(1, min(int(limit or 12), MAX_ROWS))
    started = time.perf_counter()
    now, zone = await analytics_tools._now_and_zone()
    window = _period_of(period, now, zone)
    start, end = summarise.window_for(window)
    lookback = LOOKBACK_DAYS.get(task, 0)
    # ONE view, wide enough for the comparison the task needs. A wider window is not a
    # second read: the cache keeps ninety days warm (app/analytics/cache.py WARM_DAYS) and
    # serves this from memory.
    read_from = window.start - timedelta(days=lookback) if lookback else window.start
    view = await analytics_tools.cache().view(
        Period(read_from, window.end, window.label, window.kind), timeout_s=READ_TIMEOUT_S,
    )
    rows = view.rows
    if task == "returning_customers":
        found = summarise.returning_customers(rows, start=start, end=end, zone=zone, limit=limit)
        kind = "customers"
    elif task == "orders_attention":
        found = summarise.orders_needing_attention(
            summarise.in_window(rows, start=start, end=end) if period else rows,
            now=now.timestamp(), zone=zone, limit=limit,
        )
        kind = "orders"
    else:
        found = summarise.order_rows(rows, start=start, end=end, now=now.timestamp(), zone=zone, limit=limit)
        kind = "orders"

    found.update({
        "task": task,
        "period": {"label": window.label, "start": window.start.isoformat(), "end": window.end.isoformat()},
        # Whether the OWNER named a period. "Which orders need attention" names none and is
        # answered over everything the Mac holds, so its surface must not be titled "today"
        # merely because `today` is this tool's default window.
        "period_asked": bool(period),
        "coverage": {"complete": view.complete, "covered_days": view.covered_days,
                     "read_age_s": (round(view.age_s, 1) if view.age_s is not None else None)},
        "complete": bool(view.complete),
        "source": f"Shopify orders the server holds, read {'just now' if not view.age_s else f'{round(view.age_s)} s ago'}",
        "reads": 1,
        "_ms": round((time.perf_counter() - started) * 1000 + view.served_ms, 1),
    })
    if task == "orders_attention" and not period:
        # Asked of no period, the attention question is answered over the lookback, which is
        # a window too: an order placed before it that still needs something is not in this,
        # and the answer and its card say so rather than speaking for every order (the
        # round-12 deploy review, F/F-02). app/summaries.py `attention_rows` draws the words.
        found["read_from"] = read_from.isoformat()
        found["note"] = (f"Only orders placed since {day_words(found['read_from'])} were read; "
                         f"an order placed before then is not in this. {found.get('note') or ''}").strip()
    if view.note:
        found["note"] = (str(found.get("note") or "") + " " + view.note).strip()
    # EVERY match as a set, so "next", "the third one" and a tap on a row are one cursor on
    # one list and the cursor can reach the last of twenty-five while the surface shows
    # twelve. The Mac owns membership; the tablet only ever names an id back.
    session = current_session()
    members = [m for m in (found.get("members") or []) if m.get("ref")]
    if session is not None and members:
        made = working_sets.create(
            session, kind=kind, members=[str(m["ref"]) for m in members],
            label=f"{TASKS[task]}, {window.label}"[:80],
            provenance={"tool": READ_TOOL, "step": "query", "query": {"task": task, "period": window.label}},
            sample=[], totals={}, labels=_labels_for(task, members),
        )
        found["set_id"] = made.set_id
    return found


def _labels_for(task: str, members: list[dict[str, Any]]) -> dict[str, str]:
    """How a person names each member, for the batch card and for the cursor's words.

    EVERY member, not only the drawn ones. `app/commands.py::move_cursor` falls back to the
    ref when a member has no label — `ws.labels.get(ref) or ref` — so a set with labels for
    twelve of twenty-five members would eventually say a `gid://` out loud and draw it (§26).
    The words come from the same helpers the rows use, so the cursor and the row agree about
    what each one is called.
    """
    if task == "returning_customers":
        return {str(m["ref"]): customer_words(m.get("name"), m.get("email"), m.get("order_number"))
                for m in members}
    return {str(m["ref"]): (order_words(m.get("order_number")) or "an order")
            for m in members}


register_family(CapabilityFamily(
    key="summary_surfaces",
    label="Summary answers",
    area="analytics",
    what=(
        "Answer a summary question about a period in one read and one compact surface: who "
        "bought having bought before, which orders need attention, a period's orders as rows"
    ),
    tools=(READ_TOOL,),
    scopes=("read_orders", "read_customers"),
    state="READY",
))
