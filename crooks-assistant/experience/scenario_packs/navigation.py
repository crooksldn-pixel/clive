"""The click path, driven end to end (brief §5, §31; defect D-10).

`tests/test_navigation.py` holds the semantics against the branch and the command registry.
These run the whole thing — the route, the landings, the read scheduler, the presenters —
against the golden world, and assert what the owner would actually be looking at afterwards.
A list is opened from the dock, as the owner opens one; a record by asking for it, which is a
model turn like every sentence.

Every check here is about the SCREEN. None of them reads `ok`, because in the live session
twelve navigation commands in twenty-two seconds all returned `ok=True` while the owner was
lost: eight Homes that redrew the same email thread and four Backs that went nowhere he
wanted. A navigation command returning true is not evidence of anything.
"""

from __future__ import annotations

from typing import Any

from experience.fixtures import world
from experience.harness import Harness
from experience.scenarios import Result, a_surface, check, deterministic


def _rows(capture: Any, ui_type: str = "order_list") -> list[dict[str, Any]]:
    card = capture.data(ui_type)
    return [r for r in (card.get("orders") or card.get("rows") or []) if isinstance(r, dict)]


def _ref(row: dict[str, Any]) -> str:
    return str(row.get("order_id") or row.get("ref") or "")


async def click_path(h: Harness) -> Result:
    """Orders → an order → its Customer tab → a prior order → Back → Back.

    The brief's own worked example, which the forensics gave a name: Back must return to the
    customer ON that order, and the Back after it to the list, at about the place it was left.
    """
    r = Result("nav_click_path", "Orders, an order, a prior order, and back out")
    session = "nav_path"
    listing = await h.touch("open.area", area="orders", scenario="nav:list", session_id=session)
    r.captures.append(listing)
    r.checks += a_surface(listing, "order_list", what="the list opens")
    rows = _rows(listing)
    r.checks.append(check("the list has rows to tap", len(rows) >= 2, f"{len(rows)} rows"))
    if len(rows) < 2:
        return r
    first, second = _ref(rows[0]), _ref(rows[1])

    # Where the owner had scrolled the list to. Reported the way the tablet reports it.
    await h.touch("surface.scroll", session_id=session, depth=310)
    opened = await h.touch("open.entity", session_id=session, kind="order", ref=first,
                           label="first", scenario="nav:open")
    r.captures.append(opened)
    r.checks += a_surface(opened, "order", what="tapping a row opens the order")
    r.checks.append(deterministic(opened))

    await h.touch("surface.tab", session_id=session, surface="order", tab="customer")
    prior = await h.touch("open.entity", session_id=session, kind="order", ref=second,
                          label="prior", scenario="nav:prior")
    r.captures.append(prior)
    r.checks += a_surface(prior, "order", what="the prior order opens")

    back = await h.touch("navigation.back", session_id=session, scenario="nav:back1")
    r.captures.append(back)
    r.checks.append(deterministic(back))
    r.checks += a_surface(back, "order", what="Back redraws the order it came from")
    r.checks.append(check("Back lands on the order the prior one was reached from",
                          (back.entity or {}).get("ref") == first, f"entity={back.entity}"))
    stop = (back.raw.get("changed") or {}).get("workspace") or {}
    r.checks.append(check("and on the part of it that was showing — the customer tab",
                          stop.get("tab") == "customer", f"workspace={stop}"))
    r.checks.append(check("the card drawn is that order", h_ref(back) == first,
                          f"card={h_ref(back)!r} wanted={first!r}"))

    out = await h.touch("navigation.back", session_id=session, scenario="nav:back2")
    r.captures.append(out)
    r.checks += a_surface(out, "order_list", what="another Back returns to the list itself")
    r.checks.append(deterministic(out))
    where = (out.raw.get("changed") or {}).get("workspace") or {}
    r.checks.append(check("the list comes back as a list, with its set", where.get("kind") == "list"
                          and where.get("set_id") == listing.set_id,
                          f"workspace={where} set={listing.set_id!r}"))
    r.checks.append(check("at about the position it was left", where.get("scroll") == 310,
                          f"scroll={where.get('scroll')}"))
    r.checks.append(check("the rows are the same rows, not a re-run of the search",
                          [_ref(x) for x in _rows(out)] == [_ref(x) for x in rows],
                          f"{[_ref(x) for x in _rows(out)]} vs {[_ref(x) for x in rows]}"))
    return r


def h_ref(capture: Any) -> str:
    return str(capture.data("order").get("order_id") or "")


async def home_is_a_landing(h: Harness) -> Result:
    """Home from a deep record is the branch's landing — never the record.

    This is the eight-presses-in-twenty-two-seconds defect, and the fixture reproduces its
    exact shape: a thread open, a trail behind it, and a button that used to redraw the
    thread because the thread was the oldest thing on the trail.
    """
    r = Result("nav_home_landing", "Back to the assistant, from three records deep")
    session = "nav_home"
    await h.touch("open.area", area="orders", scenario="nav_home:list", session_id=session)
    spec = world.order("1938")
    await h.open_order("1938", scenario="nav_home:order", session_id=session)
    deep = await h.customer_history(spec.person.customer_id, scenario="nav_home:customer", session_id=session)
    r.captures.append(deep)
    r.checks.append(check("three records deep", (deep.entity or {}).get("kind") == "customer",
                          f"entity={deep.entity}"))

    home = await h.touch("navigation.home", session_id=session, scenario="nav_home:home")
    r.captures.append(home)
    r.checks.append(deterministic(home))
    r.checks += a_surface(home, "order_list", what="Home draws the landing")
    r.checks.append(check("it is the landing and says so", (home.raw.get("changed") or {}).get("home") is True
                          and (home.raw.get("changed") or {}).get("area") == "orders",
                          f"changed={ {k: (home.raw.get('changed') or {}).get(k) for k in ('home', 'area', 'recipe')} }"))
    r.checks.append(check("and NOT a replay of the record that was open",
                          home.surface("customer") is None and h_ref(home) != spec.order_id,
                          f"surfaces={home.surface_types}"))

    # Pressed again, and again. Eight presses in twenty-two seconds is what the owner actually
    # did, so the second and third must be the same place as the first — not an empty landing
    # built from a spent read budget, and not another stop on the trail.
    branch = h.branch(session, home.branch_id)
    depth = len(branch.nav)
    again = await h.touch("navigation.home", session_id=session, scenario="nav_home:again")
    third = await h.touch("navigation.home", session_id=session, scenario="nav_home:third")
    r.captures += [again, third]
    r.checks.append(check("pressed twice, it is the same place both times",
                          again.surface_types == home.surface_types
                          and third.surface_types == home.surface_types,
                          f"{home.surface_types} then {again.surface_types} then {third.surface_types}"))
    r.checks.append(check("and every press has something on it",
                          not again.prose_only and not third.prose_only,
                          f"2nd={again.answer[:60]!r} 3rd={third.answer[:60]!r}"))
    r.checks.append(check("and it does not pile stops onto the trail",
                          len(branch.nav) == depth,
                          f"nav={[(e.kind, e.area) for e in branch.nav]}"))
    r.checks.append(check("the half knows where its home is", getattr(branch, "home_area", "") == "orders",
                          f"landing={getattr(branch, 'landing', '')!r}"))
    return r


async def next_walks_the_set(h: Harness) -> Result:
    """Next is the set under the cursor, with a position, and is not Back."""
    r = Result("nav_next_position", "Next, with a position on it")
    session = "nav_next"
    listing = await h.touch("open.area", area="orders", scenario="nav_next:list", session_id=session)
    r.captures.append(listing)
    total = len(_rows(listing))
    # The scenario walks a list, so it needs one. An empty listing here used to reach `seen[-2]`
    # below and raise IndexError, which reports as a crash in whatever ran the scenario rather
    # than as the thing that is actually wrong. It is a failed CHECK now, and it names what it
    # got: the last time this happened the list was empty because another test had left a
    # frozen clock in the process and "today" was a day the fixture world has no orders on.
    r.checks.append(check("the Orders landing is a list with something in it to walk",
                          total >= 2, f"rows={total} answer={listing.answer!r}"))
    if total < 2:
        return r
    seen = []
    for step in range(1, min(total, 3) + 1):
        moved = await h.touch("workflow.next", session_id=session, scenario=f"nav_next:{step}")
        r.captures.append(moved)
        changed = moved.raw.get("changed") or {}
        seen.append(h_ref(moved))
        r.checks.append(check(f"step {step} moves to a new order and says where it is",
                              changed.get("position") == step and changed.get("total") == total
                              and f"{step} of {total}" in moved.answer,
                              f"position={changed.get('position')} total={changed.get('total')} answer={moved.answer!r}"))
        r.checks.append(deterministic(moved))
    r.checks.append(check("each step is a different order", len(set(seen)) == len(seen), f"{seen}"))

    # Back is not Previous: it returns to the workspace before this one, which here is the
    # member before it, with the cursor restored rather than merely decremented.
    back = await h.touch("navigation.back", session_id=session, scenario="nav_next:back")
    r.captures.append(back)
    r.checks.append(check("Back returns to the previous workspace with the cursor it had",
                          h_ref(back) == seen[-2] and ((back.raw.get("changed") or {}).get("workspace") or {}).get("position") == len(seen) - 1,
                          f"card={h_ref(back)!r} workspace={(back.raw.get('changed') or {}).get('workspace')}"))
    onward = await h.touch("workflow.next", session_id=session, scenario="nav_next:onward")
    r.captures.append(onward)
    r.checks.append(check("and Next carries on from there rather than from the top",
                          (onward.raw.get("changed") or {}).get("position") == len(seen),
                          f"position={(onward.raw.get('changed') or {}).get('position')}"))
    return r


async def halves_keep_their_own_trail(h: Harness) -> Result:
    """The right half's Back must not move the left half's screen (D-3's other half)."""
    r = Result("nav_branch_isolation", "Two halves, two trails")
    session = "nav_halves"
    await h.touch("open.area", area="orders", scenario="nav_halves:left", session_id=session)
    left_deep = await h.open_order("1938", scenario="nav_halves:left_order", session_id=session)
    r.captures.append(left_deep)
    fork = await h.client.post("/branches/fork", data={"session_id": session, "label": "right"},
                               headers={"Tailscale-User-Login": "owner@example.com", "X-Forwarded-For": "100.64.0.9"})
    body = fork.json() if fork.content else {}
    other = str(((body.get("branch") or {}).get("branch_id")) or body.get("branch_id") or "")
    r.checks.append(check("the orb divides", bool(other), f"branch_id={other!r}"))
    if not other:
        return r

    right_first = await h.open_order("1936", scenario="nav_halves:right", session_id=session, branch_id=other)
    r.captures.append(right_first)
    left, right = h.branch(session, left_deep.branch_id), h.branch(session, other)
    before = (left.nav_index, dict(left.entity or {}), [e.entry_id for e in left.nav])

    stepped = await h.touch("navigation.back", session_id=session, branch_id=other, scenario="nav_halves:back")
    r.captures.append(stepped)
    after = (left.nav_index, dict(left.entity or {}), [e.entry_id for e in left.nav])
    r.checks.append(check("a Back on the right leaves the left exactly as it was",
                          before == after, f"{before} -> {after}"))
    r.checks.append(check("the halves hold different stacks", left.nav is not right.nav,
                          "one stack object between two halves"))
    r.checks.append(check("and the left half is still looking at its own order",
                          (left.entity or {}).get("ref") == world.order("1938").order_id,
                          f"left={left.entity}"))
    return r


SCENARIOS = (
    ("nav_click_path", click_path),
    ("nav_home_landing", home_is_a_landing),
    ("nav_next_position", next_walks_the_set),
    ("nav_branch_isolation", halves_keep_their_own_trail),
)
