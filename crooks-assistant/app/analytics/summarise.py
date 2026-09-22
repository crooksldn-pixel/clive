"""Deterministic answers to the summary questions — §13's data half, and §14's whole.

D-4 in docs/phase5/LIVE_SESSION_FORENSICS.md is one turn:

    turn_be1b384ca420   "Has anyone bought today that has bought before, a returning customer?"
    answer: one.        rendered: SEVEN full customer cards.
    tools:  shopify_customer_history x 7 — one per candidate.

Two defects in one turn. The one the generated report saw is not there at all: the seven ids
are seven DIFFERENT customers (…6343, …4807, …5015, …4055, …7975, …2855, …8887), so nothing
was drawn twice. The two that are there:

  §13  a SUMMARY question was answered with seven ENTITY PROFILES. "How many of today's
       buyers have bought before" wants one line and one row per person, not seven pages.
  §14  an N+1 READ. Seven `shopify_customer_history` calls to learn a fact the Mac already
       held: the order cache stores `numberOfOrders` and `amountSpent` on every order row
       (app/analytics/cache.py ORDERS_QUERY `customer { numberOfOrders amountSpent }`), so
       "has this buyer bought before" is a comparison, not a lookup.

So this module is pure functions over the rows the cache already has. No client, no clock
beyond the one passed in, no reads at all — which is what makes the read count one (the
cache view the question needed anyway) instead of one plus one per candidate.

The brief's rule, quoted: **do not push complexity into Claude if deterministic aggregation
works.** Every function here is the deterministic aggregation for one question the tablet
asked that evening and got a deck of profiles for.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.analytics.engine import age_days_tenths

# How many rows a summary carries. A summary that needs a fortieth row is a listing, and a
# listing has its own surface with its own cursor.
MAX_ROWS = 25

# Every match, for the working set the cursor walks — as distinct from `rows`, which is what
# the surface SHOWS. They are different numbers on purpose: "twenty-five returning customers"
# shows twelve and "next" must still be able to reach the twenty-fifth, because a list that
# stops at twelve while its own headline says twenty-five is a list that lies about its end
# (app/commands.py BOUND_WORDS). The cap is the working sets' own
# (app/analytics/sets.py MAX_MEMBERS), written here so this file imports nothing.
MAX_MEMBERS = 500

# What counts as "bought before": the customer's lifetime order count, as Shopify counts it,
# is more than the one they placed in the period. Two orders in the window is also returning —
# `lifetime_orders` covers both, because Shopify counts every order they have ever placed.
RETURNING_AT = 2

# When an order is old enough to be worth naming, in days. The same two-and-five as
# app/context/attention.py, held apart because that module reads a full order detail and this
# one reads a cache row: the numbers must agree, and the reason they are written twice is
# that one file must not import the other's read model.
AGING_AMBER_DAYS = 2.0
AGING_RED_DAYS = 5.0

_UNPAID = frozenset({"PENDING", "AUTHORIZED", "PARTIALLY_PAID", "EXPIRED"})


def _day(ts: float, zone: ZoneInfo) -> datetime:
    return datetime.fromtimestamp(float(ts or 0), UTC).astimezone(zone)


def _customer_of(order: dict[str, Any]) -> dict[str, Any]:
    found = order.get("customer")
    return found if isinstance(found, dict) and found.get("customer_id") else {}


def _live(order: dict[str, Any]) -> bool:
    """An order that happened. A cancelled one is not a purchase, and counting it as one is
    how "anyone bought today" comes back yes on a checkout that was undone."""
    return not order.get("cancelled")


def in_window(rows: list[dict[str, Any]], *, start: float, end: float) -> list[dict[str, Any]]:
    """The rows placed in [start, end). Bounded by the caller's period, never by a guess."""
    return [r for r in rows if start <= float(r.get("ts") or 0) < end and _live(r)]


# --------------------------------------------------------------- returning customers


def returning_customers(
    rows: list[dict[str, Any]], *, start: float, end: float, zone: ZoneInfo,
    limit: int = MAX_ROWS,
) -> dict[str, Any]:
    """Who bought in the window and had bought before it — the whole of turn_be1b384ca420.

    One pass over the rows the cache holds. For each buyer in the window:

      * their order IN the window, by number — what the owner will tap
      * whether they are returning: `lifetime_orders >= 2`, measured by Shopify
      * their PREVIOUS order, when the Mac holds it, by number and by date
      * their lifetime orders and lifetime spend, measured by Shopify

    `previous_known` says whether the previous order is one the Mac holds. The cache's window
    is ninety days (app/analytics/cache.py WARM_DAYS), so a customer whose last order was in
    March is returning and their previous order is not here — and the row says "before the
    Mac's window" rather than inventing a date or spending a read to find one. That is the
    honest end of it: the fact that was ASKED for (are they returning) is measured; the fact
    that is merely nice (when exactly) is stated as held or not held.
    """
    window = in_window(rows, start=start, end=end)
    earlier: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not _live(row) or float(row.get("ts") or 0) >= start:
            continue
        customer_id = _customer_of(row).get("customer_id")
        if customer_id:
            earlier.setdefault(str(customer_id), []).append(row)

    # Newest order in the window per customer, so a buyer with two orders today is one row.
    by_customer: dict[str, dict[str, Any]] = {}
    guests = 0
    for row in sorted(window, key=lambda r: float(r.get("ts") or 0), reverse=True):
        customer = _customer_of(row)
        customer_id = str(customer.get("customer_id") or "")
        if not customer_id:
            guests += 1
            continue
        by_customer.setdefault(customer_id, row)

    out: list[dict[str, Any]] = []
    for customer_id, row in by_customer.items():
        customer = _customer_of(row)
        lifetime_orders = int(customer.get("orders") or 0)
        held_before = sorted(earlier.get(customer_id, ()), key=lambda r: float(r.get("ts") or 0), reverse=True)
        # Returning on Shopify's own count, or on the Mac's own rows — whichever knows. A
        # shop that has just imported its history has customers with numberOfOrders at 1 and
        # three orders in the cache; the cache is then the better witness and is not ignored.
        returning = lifetime_orders >= RETURNING_AT or bool(held_before)
        if not returning:
            continue
        previous = held_before[0] if held_before else None
        out.append({
            "customer_id": customer_id,
            "name": str(customer.get("name") or ""),
            "email": str(customer.get("email") or ""),
            "order_id": str(row.get("order_id") or ""),
            "order_number": str(row.get("order_number") or ""),
            "placed_at": _day(row.get("ts") or 0, zone).isoformat(),
            "previous_order_number": str(previous.get("order_number") or "") if previous else "",
            "previous_order_id": str(previous.get("order_id") or "") if previous else "",
            "previous_at": _day(previous.get("ts") or 0, zone).isoformat() if previous else "",
            "previous_known": previous is not None,
            "lifetime_orders": max(lifetime_orders, len(held_before) + 1),
            "lifetime_spent": round(float(customer.get("spent") or 0.0), 2),
            "currency": str(row.get("currency") or "GBP"),
            "orders_in_window": sum(1 for r in window if _customer_of(r).get("customer_id") == customer_id),
        })
    out.sort(key=lambda r: (-float(r["lifetime_spent"]), str(r["name"] or r["email"])))
    return {
        "rows": out[: max(1, int(limit))],
        # Every match, so the cursor can reach the last one however few are drawn. Names
        # rather than ids alone: whoever labels the set has to be able to say who each one is
        # without a second read, and the cursor's words must never fall back to a gid.
        "members": [{"ref": r["customer_id"], "name": r["name"], "email": r["email"],
                     "order_number": r["order_number"]} for r in out[:MAX_MEMBERS]],
        "count": len(out),
        "truncated": len(out) > max(1, int(limit)),
        "buyers": len(by_customer) + guests,
        "guests": guests,
        "orders_in_window": len(window),
        "currency": next((str(r.get("currency")) for r in window if r.get("currency")), "GBP"),
    }


# ------------------------------------------------------------------- needs attention


def _attention_for_row(row: dict[str, Any], *, now: float) -> tuple[str, str, str] | None:
    """(level, headline, detail) for one cache row, or None when it needs nothing.

    From the ROW and nothing else: no order detail, no customer history, no inbox. That is
    the point — "which orders need attention" was a question the model answered by reading
    every order in turn, and every fact below is already on the row the listing read.
    """
    age_days = max(0.0, (now - float(row.get("ts") or now)) / 86400.0)
    payment = str(row.get("financial") or "").upper()
    fulfillment = str(row.get("fulfillment") or "").upper()
    refunded = float(row.get("refunded") or 0.0)
    outstanding = float(row.get("outstanding") or 0.0)
    total = float(row.get("total") or 0.0)
    shipped = fulfillment == "FULFILLED"

    if row.get("cancelled"):
        return None
    if payment in _UNPAID and (outstanding > 0 or total > refunded):
        # Money still owing. `outstanding` is the better witness where Shopify populates it,
        # but it is not always populated (an order read through a lean query, an older
        # order), so the order's own total against what has been given back is the fallback
        # rather than a silent "nothing owing".
        return ("red", "Not paid for", f"{_days_words(age_days)} old and still owing")
    if refunded > 0 and not shipped:
        return ("amber", "Refunded, not shipped", "money back on an order still here")
    if not shipped and age_days >= AGING_RED_DAYS:
        return ("red", "Waiting to go out", f"{_days_words(age_days)} old")
    if not shipped and age_days >= AGING_AMBER_DAYS:
        return ("amber", "Waiting to go out", f"{_days_words(age_days)} old")
    if shipped and not row.get("has_tracking"):
        return ("amber", "Shipped with no tracking", "nothing for the customer to follow")
    return None


def _days_words(days: float) -> str:
    whole = int(days)
    if whole <= 0:
        return "today"
    return "1 day" if whole == 1 else f"{whole} days"


_LEVEL_RANK = {"red": 0, "amber": 1}


def orders_needing_attention(
    rows: list[dict[str, Any]], *, now: float, zone: ZoneInfo, limit: int = MAX_ROWS,
) -> dict[str, Any]:
    """The orders that need something, worst first — one pass, no per-order read.

    Bounded by `limit` for the surface and counted in full, so the headline is the truth
    ("four need attention") while the deck stays one screen.
    """
    found: list[dict[str, Any]] = []
    for row in rows:
        verdict = _attention_for_row(row, now=now)
        if verdict is None:
            continue
        level, headline, detail = verdict
        customer = _customer_of(row)
        found.append({
            "order_id": str(row.get("order_id") or ""),
            "order_number": str(row.get("order_number") or ""),
            "level": level,
            "headline": headline,
            "detail": detail,
            "placed_at": _day(row.get("ts") or 0, zone).isoformat(),
            "age_days": age_days_tenths(max(0.0, now - float(row.get("ts") or now))),
            "total": round(float(row.get("total") or 0.0), 2),
            "currency": str(row.get("currency") or "GBP"),
            "customer_id": str(customer.get("customer_id") or ""),
            "customer_name": str(customer.get("name") or ""),
            "customer_email": str(customer.get("email") or ""),
        })
    found.sort(key=lambda r: (_LEVEL_RANK.get(r["level"], 2), -float(r["age_days"])))
    capped = max(1, int(limit))
    return {
        "rows": found[:capped],
        "members": [{"ref": r["order_id"], "order_number": r["order_number"]}
                    for r in found[:MAX_MEMBERS]],
        "count": len(found),
        "truncated": len(found) > capped,
        "red": sum(1 for r in found if r["level"] == "red"),
        "amber": sum(1 for r in found if r["level"] == "amber"),
        "considered": sum(1 for r in rows if _live(r)),
        "currency": next((str(r.get("currency")) for r in rows if r.get("currency")), "GBP"),
    }


# -------------------------------------------------------------------- a compact listing


def order_rows(
    rows: list[dict[str, Any]], *, start: float, end: float, now: float, zone: ZoneInfo,
    limit: int = MAX_ROWS, newest_first: bool = True,
) -> dict[str, Any]:
    """A period's orders as ROWS — the answer to "show yesterday's orders".

    The same facts a person reads off a row and no more: its number, whose it is, when, what
    it came to, whether it has gone. Not an order's page thirty times over.
    """
    window = in_window(rows, start=start, end=end)
    window.sort(key=lambda r: float(r.get("ts") or 0), reverse=bool(newest_first))
    capped = max(1, int(limit))
    out = []
    for row in window[:capped]:
        customer = _customer_of(row)
        out.append({
            "order_id": str(row.get("order_id") or ""),
            "order_number": str(row.get("order_number") or ""),
            "placed_at": _day(row.get("ts") or 0, zone).isoformat(),
            "age_days": age_days_tenths(max(0.0, now - float(row.get("ts") or now))),
            "total": round(float(row.get("total") or 0.0), 2),
            "currency": str(row.get("currency") or "GBP"),
            "fulfillment": str(row.get("fulfillment") or ""),
            "payment": str(row.get("financial") or ""),
            "customer_id": str(customer.get("customer_id") or ""),
            "customer_name": str(customer.get("name") or ""),
        })
    return {
        "rows": out,
        "members": [{"ref": str(r.get("order_id") or ""), "order_number": str(r.get("order_number") or "")}
                    for r in window[:MAX_MEMBERS] if r.get("order_id")],
        "count": len(window),
        "truncated": len(window) > capped,
        "to_ship": sum(1 for r in window if str(r.get("fulfillment") or "").upper() != "FULFILLED"),
        "value": round(sum(float(r.get("total") or 0.0) for r in window), 2),
        "currency": next((str(r.get("currency")) for r in window if r.get("currency")), "GBP"),
    }


# ------------------------------------------------------------------ lifetime metrics


def customer_lifetime(
    rows: list[dict[str, Any]], customer_ids: list[str] | tuple[str, ...], *, zone: ZoneInfo,
) -> dict[str, dict[str, Any]]:
    """Lifetime orders, lifetime spend, first and last order, for several customers at once.

    §14's second named workflow. It used to be one `shopify_customer_history` per customer;
    every value here is on the order rows the Mac already holds, so N reads become none. The
    ones the cache cannot see are reported missing rather than guessed — a caller that needs
    the full history for a customer outside the window reads that ONE customer.
    """
    wanted = [str(c) for c in customer_ids if str(c)]
    out: dict[str, dict[str, Any]] = {}
    for customer_id in wanted:
        mine = [r for r in rows if _live(r) and _customer_of(r).get("customer_id") == customer_id]
        if not mine:
            out[customer_id] = {"held": False}
            continue
        mine.sort(key=lambda r: float(r.get("ts") or 0))
        customer = _customer_of(mine[-1])
        out[customer_id] = {
            "held": True,
            "name": str(customer.get("name") or ""),
            "email": str(customer.get("email") or ""),
            "lifetime_orders": max(int(customer.get("orders") or 0), len(mine)),
            "lifetime_spent": round(float(customer.get("spent") or 0.0), 2),
            "orders_held": len(mine),
            "first_order_at": _day(mine[0].get("ts") or 0, zone).isoformat(),
            "last_order_at": _day(mine[-1].get("ts") or 0, zone).isoformat(),
            "first_order_number": str(mine[0].get("order_number") or ""),
            "last_order_number": str(mine[-1].get("order_number") or ""),
            "currency": str(mine[-1].get("currency") or "GBP"),
        }
    return out


def window_for(period: Any) -> tuple[float, float]:
    """(start, end) as epoch seconds, from an app/analytics/periods.py Period."""
    start = getattr(period, "start", None)
    end = getattr(period, "end", None)
    if isinstance(start, datetime) and isinstance(end, datetime):
        return start.timestamp(), end.timestamp()
    raise TypeError("a period with a start and an end is needed to summarise a window")

