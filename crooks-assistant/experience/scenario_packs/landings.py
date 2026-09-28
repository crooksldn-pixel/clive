"""The dock's landings, tapped from an idle tablet (brief §4).

Each icon is a place with a fixed shape. Tapped, it posts `open.area` and the Mac draws the
landing from deterministic reads — no model, a working set where there is a list to walk.
Said out loud, "open orders" is a sentence like any other and goes to the model (since
28 September 2026); the dock is the way to a landing.
"""

from __future__ import annotations

from experience.fixtures import data
from experience.harness import Harness

# `Result`, `check` and the shared assertions live in experience/scenarios.py, which collects
# the packs at the END of its own module body — so these names are bound by the time a pack
# is imported. Importing them from here rather than copying them keeps one definition of what
# a check is.
from experience.scenarios import Result, a_surface, check, grounded


def _ok(c) -> bool:
    return bool(c.raw.get("ok", True))


def _code(c) -> str:
    return str(c.raw.get("code") or "")


def _detail(c) -> str:
    return str(c.raw.get("detail") or "")


def _no_model(c) -> object:
    return check("no model on the path", c.model_calls == 0 and (c.lane in ("TOUCH", "")), f"lane={c.lane} model_calls={c.model_calls}")


async def landing_orders(h: Harness) -> Result:
    r = Result("landing_orders", "Tap Orders from idle")
    c = await h.touch("open.area", scenario="landing_orders", session_id="dock1", area="orders")
    r.captures.append(c)
    r.checks.append(check("a fresh tablet may tap the dock before it has said anything", c.status == 200 and _ok(c), f"status={c.status} code={_code(c)!r}"))
    r.checks += a_surface(c, "order_list", what="draws an order list")
    r.checks.append(_no_model(c))
    r.checks.append(check("opens a set to walk", bool(c.set_id), f"set_id={c.set_id!r}"))
    lists = [item for item in c.surfaces if item.get("type") == "order_list"]
    r.checks.append(check("the list to go out comes first, today's beside it", len(lists) == 2 and str(lists[0]["data"].get("title") or "").startswith("To go out"), f"titles={[str(x['data'].get('title')) for x in lists]}"))
    if grounded(h):
        waiting = [o for o in data.ORDERS if str(o.fulfillment).lower() == "unfulfilled"] if hasattr(data, "ORDERS") else []
        r.checks.append(check("says how many are waiting to go out", "to go out" in c.answer.lower(), c.answer[:100]))
        if waiting:
            rows = lists[0]["data"].get("orders") or lists[0]["data"].get("rows") or [] if lists else []
            r.checks.append(check("the oldest unfulfilled order is at the top", bool(rows) and int(rows[0].get("age_days") or 0) >= max(int(x.get("age_days") or 0) for x in rows), f"first={rows[0] if rows else None}"))
    return r


async def landing_inbox(h: Harness) -> Result:
    r = Result("landing_inbox", "Tap Inbox from idle")
    c = await h.touch("open.area", scenario="landing_inbox", session_id="dock2", area="email")
    r.captures.append(c)
    r.checks.append(check("the tap succeeds", c.status == 200 and _ok(c), f"status={c.status} code={_code(c)!r} detail={_detail(c)!r}"))
    r.checks += a_surface(c, "email_list", what="draws the inbox")
    r.checks.append(_no_model(c))
    queue = [item for item in c.surfaces if item.get("type") == "email_list" and item.get("surface") == "work_queue"]
    r.checks.append(check("the needs-reply queue is the first card", bool(queue) and c.surfaces and c.surfaces[0] is queue[0], f"surfaces={c.surface_types}"))
    r.checks.append(check("the answer says who is waiting and what else came in", "waiting" in c.answer.lower() or "reply" in c.answer.lower(), c.answer[:120]))
    return r


async def landing_sales(h: Harness) -> Result:
    r = Result("landing_sales", "Tap Sales from idle")
    c = await h.touch("open.area", scenario="landing_sales", session_id="dock3", area="sales")
    r.captures.append(c)
    r.checks.append(check("the tap succeeds", c.status == 200 and _ok(c), f"status={c.status} code={_code(c)!r} detail={_detail(c)!r}"))
    r.checks += a_surface(c, "metric_group", what="draws the week's numbers")
    r.checks += a_surface(c, "ranking", what="and what is selling")
    r.checks.append(_no_model(c))
    metrics = [str(m.get("label") or m.get("key") or "") for m in (c.data("metric_group").get("metrics") or [])]
    r.checks.append(check("the week's card carries revenue, orders and average together", len(metrics) >= 3, f"metrics={metrics}"))
    # The comparison is asked for in the read (`compare: True`) and rendered when there is
    # one. The golden world has no orders in the week before last, so the sentence itself is
    # exercised by a unit test on the renderer (tests/test_landings.py) rather than pretended
    # to here: a check that cannot fail in this world is not a check.
    r.checks.append(check("today so far is said, not drawn as a second card", "today" in c.answer.lower() and sum(1 for i in c.surfaces if i.get("type") == "metric_group") == 1, c.answer[:140]))
    return r


async def landing_products(h: Harness) -> Result:
    r = Result("landing_products", "Tap Products from idle")
    c = await h.touch("open.area", scenario="landing_products", session_id="dock4", area="products")
    r.captures.append(c)
    r.checks.append(check("the tap succeeds", c.status == 200 and _ok(c), f"status={c.status} code={_code(c)!r} detail={_detail(c)!r}"))
    r.checks += a_surface(c, "ranking", what="draws the best sellers")
    r.checks.append(_no_model(c))
    r.checks.append(check("says the best seller and what is running out", "best seller" in c.answer.lower() and "running out" in c.answer.lower(), c.answer[:160]))
    return r


async def landing_unknown(h: Harness) -> Result:
    r = Result("landing_unknown", "A tap on an area the dock does not have")
    c = await h.touch("open.area", scenario="landing_unknown", session_id="dock6", area="warehouse")
    r.captures.append(c)
    r.checks.append(check("is refused with the areas named", c.status == 200 and not _ok(c) and _code(c) == "unknown_area" and "orders" in _detail(c), f"code={_code(c)!r} detail={_detail(c)!r}"))
    r.checks.append(check("draws nothing", not c.surfaces, f"surfaces={c.surface_types}"))
    return r


SCENARIOS = (
    ("landing_orders", landing_orders),
    ("landing_inbox", landing_inbox),
    ("landing_sales", landing_sales),
    ("landing_products", landing_products),
    ("landing_unknown", landing_unknown),
)
