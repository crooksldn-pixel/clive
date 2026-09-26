"""The analytic cards: what the tablet shows for a read-layer result. The result's view (the
model's intent, checked) or the shape of the data chooses the component; every value is
formatted here, as text, so the tablet only ever draws strings the Mac made. The
vocabulary is small and fixed: metric_group, ranking, table, comparison, variant_matrix,
trend — and the order list the tablet already has."""

from __future__ import annotations

from typing import Any

MAX_ROWS = 25
MAX_CELLS = 64
MAX_POINTS = 31
MAX_TITLE = 60
MAX_LABEL = 80

LABELS = {
    "units": "units", "revenue": "revenue", "orders": "orders", "customers": "customers", "aov": "avg order", "refunded": "refunded",
    "unfulfilled_units": "to ship", "unfulfilled_value": "unfulfilled value", "share": "share", "stock": "in stock", "velocity": "a day",
    "days_cover": "days cover", "lifetime_orders": "orders, all time", "lifetime_spent": "spent, all time", "last_order_at": "last order",
    "first_order_at": "first order", "age_days": "days old",
}
MONEY = frozenset({"revenue", "aov", "refunded", "unfulfilled_value", "lifetime_spent"})
GROUP_LABELS = {"product": "Product", "product_type": "Type", "variant": "Variant", "size": "Size", "colour": "Colour", "day": "Day", "week": "Week", "month": "Month", "customer": "Customer", "country": "Country", "fulfillment": "Status", "payment": "Payment"}


def _money(value: Any, currency: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "—"
    symbol = {"GBP": "£", "USD": "$", "EUR": "€"}.get(currency, f"{currency} ")
    return f"{symbol}{number:,.2f}"


def fmt(metric: str, value: Any, currency: str) -> str:
    if value is None:
        return "—"
    if metric in MONEY:
        return _money(value, currency)
    if metric == "share":
        return f"{float(value):.0f}%"
    if metric == "velocity":
        return f"{float(value):.2f}"
    if metric == "days_cover":
        return f"{float(value):.1f}"
    if metric in ("last_order_at", "first_order_at"):
        return str(value)[:10]
    if metric == "age_days":
        return f"{float(value):.0f}"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        return f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    return str(value)[:MAX_LABEL]


def _text(value: Any, limit: int = MAX_LABEL) -> str:
    return " ".join(str(value if value is not None else "").split())[:limit]


def _subtitle(result: dict[str, Any]) -> str:
    period = result.get("period") if isinstance(result.get("period"), dict) else {}
    parts = [str(period.get("label") or "")]
    coverage = result.get("coverage") if isinstance(result.get("coverage"), dict) else {}
    if coverage and coverage.get("complete") is False:
        parts.append("partial")
    filters = result.get("filters") if isinstance(result.get("filters"), dict) else {}
    named = [f"{k.replace('_', ' ')} {v}" for k, v in filters.items() if k in ("product", "size", "colour", "country_code", "fulfillment", "payment") and v]
    if named:
        parts.append(", ".join(named)[:60])
    return " · ".join(p for p in parts if p)[:120]


def _ref(key: dict[str, Any]) -> tuple[str, str]:
    for kind, name in (("product", "product_id"), ("variant", "variant_id"), ("customer", "customer_id")):
        if key.get(name):
            return _text(key[name], 120), kind
    return "", ""


def choose_view(result: dict[str, Any]) -> str:
    view = str(result.get("view") or "auto")
    if view not in ("auto", "list"):
        return view
    entity = str(result.get("entity") or "")
    groups = [str(g) for g in result.get("group_by") or []]
    if result.get("compare"):
        return "comparison"
    if entity == "orders" and result.get("rows") and result.get("mode") != "restock_priority" and view == "list":
        return "list"
    if entity == "orders" and not groups:
        return "metrics" if view == "auto" else "list"
    if groups and groups[0] in ("day", "week", "month"):
        return "trend"
    if len(groups) == 2 and set(groups) <= {"size", "colour", "product", "product_type"} and "size" in groups:
        return "matrix"
    return "ranking"


def build(result: dict[str, Any], *, tool: str) -> list[dict[str, Any]]:
    """The ui items for a read-layer result: usually one card."""
    if not isinstance(result, dict) or result.get("reused"):
        return []
    if tool == "email_query":
        return correlation(result)
    currency = str(result.get("currency") or "GBP")
    view = choose_view(result)
    if view == "list":
        return _order_list(result, currency)
    if view == "comparison" and result.get("compare"):
        return [_ui("comparison", _comparison(result, currency))]
    if view == "metrics":
        return [_ui("metric_group", _metric_group(result, currency))]
    if view == "trend":
        return [_ui("trend", _trend(result, currency))]
    if view == "matrix":
        return [_ui("variant_matrix", _matrix(result, currency))]
    if view == "table":
        return [_ui("table", _table(result, currency))]
    return [_ui("ranking", _ranking(result, currency))]


def _ui(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"type": kind, "data": data}


def _title(result: dict[str, Any], default: str) -> str:
    return _text(result.get("title") or default, MAX_TITLE)


def _note(result: dict[str, Any]) -> str:
    return _text(result.get("note") or "", 300)


def _metric_group(result: dict[str, Any], currency: str) -> dict[str, Any]:
    totals = result.get("totals") if isinstance(result.get("totals"), dict) else {}
    measured = set(result.get("measured") or [])
    metrics = [m for m in (result.get("metrics") or []) if m in totals] or [m for m in totals if m in LABELS]
    return {
        "title": _title(result, "Sales"), "subtitle": _subtitle(result),
        "metrics": [{"key": m, "label": LABELS.get(m, m), "value": fmt(m, totals.get(m), currency), "measured": m in measured} for m in metrics[:6]],
        "note": _note(result), "complete": (result.get("coverage") or {}).get("complete", True) is not False,
    }


def _ranking(result: dict[str, Any], currency: str) -> dict[str, Any]:
    metrics = [str(m) for m in result.get("metrics") or []]
    measured = set(result.get("measured") or [])
    derived = set(result.get("derived") or [])
    restock = result.get("mode") == "restock_priority"
    primary = "days_cover" if restock else (metrics[0] if metrics else "units")
    secondary = "stock" if restock else next((m for m in metrics[1:] if m not in ("share",)), None)
    rows = []
    totals = result.get("totals") if isinstance(result.get("totals"), dict) else {}
    top = 0.0
    for r in (result.get("rows") or [])[:MAX_ROWS]:
        if isinstance(r, dict) and isinstance(r.get(primary), (int, float)) and not isinstance(r.get(primary), bool):
            top = max(top, float(r[primary]))
    for index, r in enumerate((result.get("rows") or [])[:MAX_ROWS], 1):
        if not isinstance(r, dict):
            continue
        key = r.get("key") if isinstance(r.get("key"), dict) else {}
        ref, kind = _ref(key)
        value = r.get(primary)
        pct = None
        if r.get("share") is not None:
            pct = max(0, min(100, int(round(float(r["share"])))))
        elif top and isinstance(value, (int, float)) and not isinstance(value, bool) and not restock:
            pct = max(0, min(100, int(round(100 * float(value) / top))))
        lines = []
        if restock:
            for m in ("stock", "units", "velocity", "days_cover"):
                if m in r:
                    lines.append({"key": m, "label": "sold in period" if m == "units" else LABELS[m], "value": fmt(m, r.get(m), currency), "derived": m in derived})
        rows.append({
            "rank": index, "label": _text(r.get("label") or "—"), "sublabel": _text(key.get("customer_email") or "", 80) if kind == "customer" else "",
            "ref": ref, "kind": kind,
            "primary": {"key": primary, "label": LABELS.get(primary, primary), "value": fmt(primary, value, currency)},
            "secondary": ({"key": secondary, "label": LABELS.get(secondary, secondary), "value": fmt(secondary, r.get(secondary), currency)} if secondary and secondary in r else None),
            "pct": pct, "lines": lines, "known": bool(r.get("stock_known", True)),
        })
    period = _text((result.get("period") if isinstance(result.get("period"), dict) else {}).get("label") or "the period")
    return {
        "title": _title(result, "Restock priority" if restock else "Best sellers"), "subtitle": _subtitle(result),
        "rows": rows, "mode": "restock" if restock else "",
        "totals": [{"key": m, "label": LABELS.get(m, m), "value": fmt(m, totals.get(m), currency)} for m in metrics if m in totals and m not in ("share", "days_cover", "velocity", "stock")][:4],
        # The totals under the list are the period's (app/analytics/engine.py). Where the rows
        # are not all of it — a limit, a customer filter — they say so, rather than standing
        # under 25 customers as though those 25 had placed the whole month's 272 orders.
        "totals_label": f"Whole period ({period}), not just this list" if result.get("totals_scope") == "period" else "",
        "measured": [m for m in metrics if m in measured], "derived": [m for m in metrics if m in derived],
        "note": _note(result), "complete": (result.get("coverage") or {}).get("complete", True) is not False, "truncated": bool(result.get("truncated")),
    }


def _table(result: dict[str, Any], currency: str) -> dict[str, Any]:
    groups = [str(g) for g in result.get("group_by") or []]
    metrics = [str(m) for m in result.get("metrics") or []]
    columns = [{"key": g, "label": GROUP_LABELS.get(g, g), "numeric": False} for g in groups] or [{"key": "label", "label": "", "numeric": False}]
    columns += [{"key": m, "label": LABELS.get(m, m), "numeric": True} for m in metrics]
    rows = []
    for r in (result.get("rows") or [])[:MAX_ROWS]:
        if not isinstance(r, dict):
            continue
        key = r.get("key") if isinstance(r.get("key"), dict) else {}
        cells = [_text(key.get(g) or "—") for g in groups] if groups else [_text(r.get("label") or "—")]
        cells += [fmt(m, r.get(m), currency) for m in metrics]
        rows.append({"ref": _ref(key)[0], "cells": cells[:8]})
    return {"title": _title(result, "Table"), "subtitle": _subtitle(result), "columns": columns[:8], "rows": rows, "note": _note(result), "truncated": bool(result.get("truncated")), "complete": (result.get("coverage") or {}).get("complete", True) is not False}


def _comparison(result: dict[str, Any], currency: str) -> dict[str, Any]:
    compare = result.get("compare") if isinstance(result.get("compare"), dict) else {}
    metrics = [str(m) for m in result.get("metrics") or []]
    now_totals = result.get("totals") if isinstance(result.get("totals"), dict) else {}
    then_totals = compare.get("totals") if isinstance(compare.get("totals"), dict) else {}
    change = compare.get("change") if isinstance(compare.get("change"), dict) else {}
    changes = []
    for m in metrics:
        c = change.get(m)
        if not isinstance(c, dict):
            continue
        delta = c.get("delta")
        pct = c.get("pct")
        direction = "flat" if not delta else ("up" if float(delta) > 0 else "down")
        changes.append({"key": m, "label": LABELS.get(m, m), "delta": ("+" if direction == "up" else "") + fmt(m, delta, currency), "pct": (f"{'+' if float(pct) > 0 else ''}{float(pct):.1f}%" if pct is not None else "—"), "direction": direction})
    return {
        "title": _title(result, "Compared"), "subtitle": _subtitle(result),
        "current": {"label": _text((result.get("period") or {}).get("label") or "this period"), "metrics": [{"key": m, "label": LABELS.get(m, m), "value": fmt(m, now_totals.get(m), currency)} for m in metrics[:4]]},
        "previous": {"label": _text((compare.get("period") or {}).get("label") or "the period before"), "metrics": [{"key": m, "label": LABELS.get(m, m), "value": fmt(m, then_totals.get(m), currency)} for m in metrics[:4]]},
        "changes": changes[:4], "note": _note(result), "complete": (result.get("coverage") or {}).get("complete", True) is not False,
    }


def _matrix(result: dict[str, Any], currency: str) -> dict[str, Any]:
    groups = [str(g) for g in result.get("group_by") or []]
    metric = str((result.get("metrics") or ["units"])[0])
    col_key = "size" if "size" in groups else groups[-1]
    row_key = next(g for g in groups if g != col_key)
    rows: list[str] = []
    cols: list[str] = []
    cells = []
    for r in (result.get("rows") or [])[:MAX_CELLS]:
        if not isinstance(r, dict):
            continue
        key = r.get("key") if isinstance(r.get("key"), dict) else {}
        row_label, col_label = _text(key.get(row_key) or "—", 40), _text(key.get(col_key) or "—", 20)
        if row_label not in rows:
            rows.append(row_label)
        if col_label not in cols:
            cols.append(col_label)
        cells.append({"row": row_label, "col": col_label, "value": r.get(metric) if isinstance(r.get(metric), (int, float)) else None, "display": fmt(metric, r.get(metric), currency)})
    cols = sorted(cols, key=_size_order)
    return {"title": _title(result, f"{LABELS.get(metric, metric).title()} by {GROUP_LABELS.get(row_key, row_key).lower()} and {GROUP_LABELS.get(col_key, col_key).lower()}"), "subtitle": _subtitle(result),
            "row_label": GROUP_LABELS.get(row_key, row_key), "col_label": GROUP_LABELS.get(col_key, col_key), "rows": rows[:12], "cols": cols[:10], "cells": cells, "metric": LABELS.get(metric, metric), "note": _note(result)}


_SIZES = ["XXS", "XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL"]


def _size_order(label: str) -> tuple[int, str]:
    upper = label.upper()
    if upper in _SIZES:
        return (_SIZES.index(upper), "")
    try:
        return (100 + int(float(upper)), "")
    except ValueError:
        return (200, upper)


def _trend(result: dict[str, Any], currency: str) -> dict[str, Any]:
    metric = str((result.get("metrics") or ["units"])[0])
    points = []
    for r in sorted((r for r in (result.get("rows") or []) if isinstance(r, dict)), key=lambda r: str(r.get("label") or ""))[:MAX_POINTS]:
        value = r.get(metric)
        points.append({"label": _text(r.get("label") or "", 24), "value": float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0, "display": fmt(metric, value, currency)})
    totals = result.get("totals") if isinstance(result.get("totals"), dict) else {}
    return {"title": _title(result, f"{LABELS.get(metric, metric).title()} by {str((result.get('group_by') or ['day'])[0])}"), "subtitle": _subtitle(result), "metric": LABELS.get(metric, metric), "points": points,
            "total": fmt(metric, totals.get(metric), currency), "note": _note(result)}


def _order_list(result: dict[str, Any], currency: str) -> list[dict[str, Any]]:
    from app.presentation import MAX_ORDERS, _order

    rows = []
    for r in (result.get("rows") or [])[:MAX_ORDERS]:
        if not isinstance(r, dict):
            continue
        shaped = dict(r)
        if isinstance(shaped.get("total"), (int, float)):
            shaped["total"] = f"{float(shaped['total']):.2f} {shaped.get('currency') or currency}"
        rows.append(_order(shaped))
    if not rows:
        return []
    totals = result.get("totals") if isinstance(result.get("totals"), dict) else {}
    return [{"type": "order_list", "data": {
        "title": _title(result, "Orders"), "query": _subtitle(result), "orders": rows, "count": int(totals.get("orders") or len(rows)), "truncated": bool(result.get("truncated")),
        "value": _money(totals.get("revenue"), currency) if totals.get("revenue") is not None else "",
    }}]


# --------------------------------------------------------------------------- working sets


def working_set_card(public: dict[str, Any]) -> dict[str, Any] | None:
    """The set as the tablet shows it: what it is, how many, where it came from."""
    if not isinstance(public, dict) or not public.get("set_id"):
        return None
    totals = public.get("totals") if isinstance(public.get("totals"), dict) else {}
    lines = []
    if isinstance(totals.get("revenue"), (int, float)):
        lines.append({"label": "value", "value": _money(totals["revenue"], "GBP")})
    if isinstance(totals.get("unfulfilled_value"), (int, float)) and totals.get("unfulfilled_value") != totals.get("revenue"):
        lines.append({"label": "unfulfilled", "value": _money(totals["unfulfilled_value"], "GBP")})
    return _ui("working_set", {
        "set_id": _text(public.get("set_id"), 40), "kind": _text(public.get("kind"), 20), "count": int(public.get("count") or 0), "label": _text(public.get("label"), 80),
        "parent_label": _text(public.get("parent_label") or "", 80), "step": _text(public.get("step") or "query", 20),
        "sample": [{"ref": _text(s.get("ref"), 120), "label": _text(s.get("label"), 60)} for s in (public.get("sample") or [])[:5] if isinstance(s, dict)],
        "truncated": bool(public.get("truncated")), "lines": lines[:3],
    })


def working_set_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Every set a result made, as cards after it: a listing's set; a correlation's contacted
    and not-contacted sets."""
    if not isinstance(result, dict):
        return []
    out = []
    card = working_set_card(result.get("set"))
    if card is not None:
        out.append(card)
    derived = [(key, result.get(key)) for key in ("set_contacted", "set_not_contacted", "set_replied") if isinstance(result.get(key), dict)]
    if derived:
        # One card for the correlation: the set the owner asked about, with the three
        # counts on it. The derived sets are the model's to name; three cards each saying
        # "these" would be three claims to the same word.
        counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
        out.append(_ui("working_set", {
            "set_id": _text(result.get("set_id"), 40), "kind": _text(result.get("kind"), 20), "count": int(result.get("customers") or 0), "label": _text(result.get("set_label"), 80),
            "parent_label": "", "step": "correlate", "sample": [], "truncated": False,
            "lines": [{"label": "emailed us", "value": str(int(counts.get("contacted") or 0))}, {"label": "no contact", "value": str(int(counts.get("not_contacted") or 0))}, {"label": "we replied", "value": str(int(counts.get("replied") or 0))}],
        }))
    return out


def correlation(result: dict[str, Any]) -> list[dict[str, Any]]:
    """The email query's answer: the counts, then each customer with whether they wrote and
    whether we replied."""
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    # The inbox read (no set) has no "no contact": everyone on it wrote. Its three numbers are
    # who wrote, who is waiting on us, and who we have answered.
    shown = (("people", "wrote to us"), ("needs_reply", "waiting on us"), ("replied", "we replied")) if result.get("scope") == "inbox" \
        else (("contacted", "emailed us"), ("not_contacted", "no contact"), ("replied", "we replied"))
    rows = []
    for r in (result.get("rows") or [])[:MAX_ROWS]:
        if not isinstance(r, dict):
            continue
        rows.append({"ref": _text(r.get("customer_id"), 120), "cells": [
            _text(r.get("customer_name") or r.get("customer_email") or "—", 40), ", ".join(str(o).rsplit("-", 1)[-1] for o in (r.get("orders") or [])[:3]),
            ("yes" if r.get("emailed") else ("no" if r.get("checked") else "?")), ("yes" if r.get("replied") else ("no" if r.get("replied") is False else "—")), _text(r.get("last_subject") or "", 60),
        ]})
    return [
        _ui("metric_group", {"title": _text(result.get("set_label") or "Email", MAX_TITLE), "subtitle": f"the last {int(result.get('days') or 30)} days of email",
                             "metrics": [{"key": key, "label": label, "value": str(int(counts.get(key) or 0)), "measured": True} for key, label in shown],
                             "note": _note(result), "complete": not counts.get("unchecked")}),
        _ui("table", {"title": "Who has written", "subtitle": _text(result.get("set_label") or "", 80), "columns": [{"key": "customer", "label": "Customer", "numeric": False}, {"key": "orders", "label": "Orders", "numeric": False}, {"key": "emailed", "label": "Emailed", "numeric": False}, {"key": "replied", "label": "Replied", "numeric": False}, {"key": "subject", "label": "Last subject", "numeric": False}],
                      "rows": rows, "note": "", "truncated": len(result.get("rows") or []) > MAX_ROWS, "complete": True}),
    ]
