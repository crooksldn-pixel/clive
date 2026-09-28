"""The golden scenarios: what the tablet is asked, and what must be true afterwards.

Each one drives real turns through the real runtime and then asserts. The assertions are
ordered the way the brief orders its oracle, and that order is load-bearing:

    1. structural   the right kind of surface exists, with the fields it must carry
    2. grounding    the values on it are the values the golden world holds
    3. mechanical   the thing can be tapped, walked, gone back from
    4. semantic     the words are reasonable

Only the first three appear here, because only the first three can be decided without an
opinion. A semantic grader can add to this and can never overturn it: a scenario that fails a
structural check has failed, whatever anything thinks of the prose.

The rule that gives this file its point is `prose_only`. A turn that answers a question about
an order and shows nothing is a failure even when the sentence is perfect and the answer
arrived in nine milliseconds — that combination is exactly what was reported from the tablet,
and it is what §29 of the brief requires a test to catch.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from experience.fixtures import data, world
from experience.harness import Harness


@dataclass
class Check:
    what: str
    ok: bool
    detail: str = ""

    def __bool__(self) -> bool:
        return self.ok


@dataclass
class Result:
    name: str
    title: str
    checks: list[Check] = field(default_factory=list)
    captures: list[Any] = field(default_factory=list)
    error: str = ""

    @property
    def status(self) -> str:
        if self.error:
            return "FAIL"
        if not self.checks:
            return "PARTIAL"
        if all(c.ok for c in self.checks):
            return "PASS"
        return "FAIL"

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.name, "title": self.title, "status": self.status,
            "error": self.error,
            "checks": [{"what": c.what, "ok": c.ok, "detail": c.detail} for c in self.checks],
            "captures": [c.as_dict() for c in self.captures],
        }


def check(what: str, ok: Any, detail: str = "") -> Check:
    return Check(what, bool(ok), detail)


# Scenarios that mean anything against a REAL shop. The others name a fixture record — order
# 1938, Mia Jones — and asserting those against the owner's own store would fail for the
# right reason and tell nobody anything. What a live run is for is the shapes: that a real
# order still produces an order surface with items and a rail, that a real inbox still
# correlates, that the cards fit real data.
LIVE_SCENARIOS: frozenset[str] = frozenset({
    "today_orders", "needs_reply", "next_previous", "back", "tabs",
})


def grounded(h: Harness) -> bool:
    """Whether the golden world's own values may be asserted. False against a real shop."""
    return not getattr(h, "live", False)


# --------------------------------------------------------------------------- shared assertions


def a_surface(capture: Any, ui_type: str, *, what: str = "") -> list[Check]:
    """The check this whole pass exists for: something to look at, of the right kind."""
    label = what or f"shows a {ui_type}"
    checks = [check(f"{label} rather than prose", not capture.prose_only,
                    f"surfaces={capture.surface_types} answer={capture.answer[:60]!r}")]
    checks.append(check(f"{label}", capture.surface(ui_type) is not None,
                        f"surfaces={capture.surface_types}"))
    return checks


def deterministic(capture: Any) -> Check:
    """A tap: a button that names what it does is answered without the model."""
    return check("answered without the model", capture.model_calls == 0,
                 f"model_calls={capture.model_calls}")


def a_model_turn(capture: Any) -> Check:
    """A sentence: every one is the model's, asked once, with nothing answered in front of it
    (app/routes/turn.py). The owner removed the word-matching lane on 28 September 2026.

    What this does NOT show is what the model decided. The harness's model calls what the
    scenario scripted (`Harness.ask`), so a check that a card appeared after `abandoned_window`
    scripted `days=7`, or that a composer holds the address `compose_open` handed it, is a check
    of the gate and the presenters given that call — a scripted gate/presenter test (the
    2026-09-28 deploy review, round 9, H-02). The capture carries the scripted tools
    (`Capture.scripted`) and the report prints them beside the result."""
    return check("the sentence went to the model, once", capture.model_calls == 1 and capture.lane == "NORMAL",
                 f"model_calls={capture.model_calls} lane={capture.lane!r}")


def entity_is(capture: Any, kind: str, ref: str = "") -> Check:
    got = capture.entity or {}
    ok = got.get("kind") == kind and (not ref or got.get("ref") == ref)
    return check(f"the current entity is the {kind}", ok, f"entity={got}")


# --------------------------------------------------------------------------- the scenarios


def _money(value: Any) -> float | None:
    """A displayed amount as a number, or None when it is not one. Currency symbols, thousands
    separators and a stray minus all survive; anything else is not silently read as zero."""
    text = str(value or "").strip().replace(",", "")
    for symbol in ("£", "$", "€", "GBP", "USD", "EUR"):
        text = text.replace(symbol, "")
    text = text.strip()
    try:
        return float(text)
    except ValueError:
        return None


async def order_lookup(h: Harness) -> Result:
    """The regression the whole pass exists to prevent (brief §29).

    Every check here would have passed on the build that was reported as broken EXCEPT the
    ones about the surface, the items and the actions — the answer was fast and correct and
    there was nothing on the screen. The sentence is the model's; the card is drawn from what
    the model read, and the order it shows is where the owner now is.
    """
    r = Result("order_lookup", "Show me order 1938")
    spec = world.order("1938")
    c = await h.open_order("1938", scenario="order_lookup")
    r.captures.append(c)
    r.checks += a_surface(c, "order", what="shows the order surface")
    r.checks.append(a_model_turn(c))
    r.checks.append(entity_is(c, "order", spec.order_id))
    card = c.data("order")
    r.checks.append(check("the card is the full order, not the brief one", card.get("detail") is True,
                          f"detail={card.get('detail')}"))
    r.checks.append(check("names the order", str(card.get("order_number")) == spec.name,
                          f"order_number={card.get('order_number')}"))
    r.checks.append(check("names the customer", str(card.get("customer_name")) == spec.person.name,
                          f"customer_name={card.get('customer_name')}"))
    # Not "the total is £84.00". The card's own arithmetic is the thing worth holding: the
    # fixture used to state a total that excluded the £5 of postage it also displayed, so every
    # order card read Subtotal £84.00 + Shipping £5.00 + Tax £0.00 = Total £84.00. A magic
    # number in a test cannot see that; a sum can.
    money = card.get("money") if isinstance(card.get("money"), dict) else {}
    parts = {k: _money(money.get(k)) for k in ("subtotal", "shipping", "tax")}
    total = _money(card.get("total"))
    r.checks.append(check("carries a total", total is not None, f"total={card.get('total')}"))
    r.checks.append(check(
        "and the money on it adds up",
        total is not None and all(v is not None for v in parts.values())
        and abs(sum(parts.values()) - total) < 0.005,
        f"{parts} -> {card.get('total')}"))
    r.checks.append(check("the goods come to what the items cost",
                          parts["subtotal"] is not None and abs(parts["subtotal"] - float(spec.total)) < 0.005,
                          f"subtotal={money.get('subtotal')} items={spec.total}"))
    items = card.get("items") or []
    r.checks.append(check("the items are reachable", len(items) == len(spec.items),
                          f"{len(items)} items, expected {len(spec.items)}"))
    if items:
        first = items[0]
        r.checks.append(check("an item carries its variant", bool(first.get("variant")),
                              f"variant={first.get('variant')!r}"))
        r.checks.append(check("an item carries its sku", bool(first.get("sku")),
                              f"sku={first.get('sku')!r}"))
    # The full address is on the card, so the shipping tab can show it without another read.
    address = card.get("shipping_address") or {}
    lines = " ".join(str(x) for x in (address.get("lines") or []))
    r.checks.append(check("the card carries the street", spec.address["address1"] in lines,
                          f"lines={address.get('lines')}"))
    r.checks.append(check("the card carries the postcode", address.get("zip") == spec.address["zip"],
                          f"zip={address.get('zip')}"))
    r.checks.append(check("offers actions for the order", len(c.action_ids) >= 3,
                          f"actions={c.action_ids}"))
    r.checks.append(check("offers a note", "order_note_append" in c.action_ids, f"actions={c.action_ids}"))
    # And the controls on it work, because the Mac knows which order is open.
    bound = await h.touch("voice.bind", scenario="order_lookup:add_note", family="order.add_note")
    r.captures.append(bound)
    r.checks.append(check("Add a note on the card binds to this order",
                          bound.raw.get("ok") is True
                          and ((bound.raw.get("changed") or {}).get("listening_for") or {}).get("label") == spec.name,
                          f"raw={ {k: bound.raw.get(k) for k in ('ok', 'code', 'answer')} }"))
    return r


async def today_orders(h: Harness) -> Result:
    r = Result("today_orders", "Show me today's orders")
    c = await h.list_todays_orders(scenario="today_orders")
    r.captures.append(c)
    r.checks += a_surface(c, "order_list", what="shows the order list")
    r.checks.append(a_model_turn(c))
    card = c.data("order_list")
    rows = card.get("orders") or card.get("rows") or []
    if grounded(h):
        expected = world.today()
        r.checks.append(check("lists today's orders", len(rows) == len(expected),
                              f"{len(rows)} rows, expected {len(expected)} ({[o.name for o in expected]})"))
        r.checks.append(check("each row can be opened", all(row.get("order_id") for row in rows),
                              f"{[row.get('order_id') for row in rows]}"))
    else:
        # A real shop may genuinely have had no orders today. What is being checked live is
        # that the surface exists, not how many rows are in it.
        r.checks.append(check("the rows are shaped like orders",
                              all(isinstance(x, dict) for x in rows), f"{len(rows)} rows"))
    return r


async def next_and_previous(h: Harness) -> Result:
    """Next and Previous walk the list the Orders landing opened (brief §13 and §16).

    Tapped. The word "next" said out loud is a sentence like any other and goes to the model;
    the buttons are what walk a list.
    """
    r = Result("next_previous", "Next and previous, tapped")
    listing = await h.touch("open.area", area="orders", scenario="next:list", session_id="cursor")
    one = await h.touch("workflow.next", scenario="next:one", session_id="cursor")
    two = await h.touch("workflow.next", scenario="next:two", session_id="cursor")
    p = await h.touch("workflow.previous", scenario="previous", session_id="cursor")
    r.captures += [listing, one, two, p]
    r.checks.append(check("the landing opened a set", bool(listing.set_id), f"set_id={listing.set_id!r}"))
    r.checks += a_surface(one, "order", what="tapping next opens the member")
    r.checks.append(deterministic(one))
    r.checks.append(deterministic(two))
    r.checks.append(check("the cursor moved once per step",
                          "1 of" in one.answer and "2 of" in two.answer,
                          f"one={one.answer!r} two={two.answer!r}"))
    r.checks.append(check("previous goes back one", "1 of" in p.answer, f"previous={p.answer!r}"))
    r.checks.append(check("every step walks the same set",
                          one.set_id == two.set_id == p.set_id == listing.set_id,
                          f"{listing.set_id} / {one.set_id} / {two.set_id} / {p.set_id}"))
    return r


async def back_navigation(h: Harness) -> Result:
    """Several levels deep, then back out, deterministically (brief §15)."""
    r = Result("back", "Back, more than once")
    one = await h.open_order("1938", scenario="back:1", session_id="nav")
    two = await h.open_order("1936", scenario="back:2", session_id="nav")
    b1 = await h.touch("navigation.back", scenario="back:tap1", session_id="nav")
    b2 = await h.touch("navigation.back", scenario="back:tap2", session_id="nav")
    r.captures += [one, two, b1, b2]
    r.checks.append(check("the second order opened", (two.entity or {}).get("ref") == world.order("1936").order_id,
                          f"entity={two.entity}"))
    r.checks += a_surface(b1, "order", what="back redraws the record it lands on")
    r.checks.append(deterministic(b1))
    r.checks.append(check("back lands on the first order",
                          (b1.entity or {}).get("ref") == world.order("1938").order_id,
                          f"entity={b1.entity}"))
    r.checks.append(check("back again reports the end rather than inventing one",
                          b2.raw.get("ok") is not False or "as far back" in b2.answer,
                          f"answer={b2.answer!r}"))
    return r


async def tabs_and_drilldown(h: Harness) -> Result:
    r = Result("tabs", "Shipping, tapped")
    await h.open_order("1938", scenario="tabs:open", session_id="tabs")
    tapped = await h.touch("surface.tab", surface="order", tab="shipping",
                           scenario="tabs:tap", session_id="tabs")
    named = await h.touch("order.open_shipping", scenario="tabs:named_control", session_id="tabs")
    bad = await h.touch("surface.tab", surface="order", tab="nonsense",
                        scenario="tabs:unknown", session_id="tabs")
    r.captures += [tapped, named, bad]
    r.checks.append(check("tapping a tab records it as state",
                          (tapped.raw.get("changed") or {}).get("tab") == "shipping",
                          f"changed={tapped.raw.get('changed')}"))
    r.checks.append(check("the named shipping control reaches the same tab",
                          (named.raw.get("changed") or {}).get("tab") == "shipping",
                          f"changed={named.raw.get('changed')}"))
    r.checks.append(check("an unknown tab is refused, not guessed",
                          bad.raw.get("ok") is False and bad.raw.get("code") == "unknown_tab",
                          f"raw={ {k: bad.raw.get(k) for k in ('ok', 'code')} }"))
    r.checks.append(deterministic(tapped))
    return r


async def customer_history(h: Harness) -> Result:
    r = Result("customer_history", "What else has this customer ordered?")
    opened = await h.open_order("1938", scenario="history:open", session_id="hist")
    c = await h.customer_history(str(opened.data("order").get("customer_id") or ""),
                                 scenario="customer_history", session_id="hist")
    r.captures.append(c)
    r.checks += a_surface(c, "customer", what="shows the customer surface")
    r.checks.append(a_model_turn(c))
    r.checks.append(entity_is(c, "customer", data.MIA.customer_id))
    card = c.data("customer")
    mine = world.orders_of(data.MIA)
    # The customer card nests the trading history under `history` — see _history() in
    # app/presentation.py. Reading it from the top level found nothing and said so, which is
    # the assertion being wrong rather than the card.
    history = card.get("history") if isinstance(card.get("history"), dict) else {}
    r.checks.append(check("names the customer",
                          data.MIA.name in (str(card.get("name") or ""), str(history.get("name") or "")),
                          f"name={card.get('name')!r} history.name={history.get('name')!r}"))
    r.checks.append(check("counts their orders",
                          (card.get("orders") or history.get("orders")) == len(mine),
                          f"orders={card.get('orders') or history.get('orders')}, expected {len(mine)}"))
    recent = history.get("recent") or card.get("recent") or []
    r.checks.append(check("lists what they bought before", len(recent) >= 2,
                          f"recent={[o.get('order_number') for o in recent]}"))
    return r


async def needs_reply(h: Harness) -> Result:
    """Who is waiting on a reply: the Inbox landing's own queue, tapped from the dock."""
    r = Result("needs_reply", "Who is waiting on a reply?")
    c = await h.touch("open.area", area="email", scenario="needs_reply")
    r.captures.append(c)
    r.checks.append(check("shows something rather than prose", not c.prose_only,
                          f"surfaces={c.surface_types}"))
    r.checks.append(deterministic(c))
    queue = next((item for item in c.surfaces if item.get("surface") == "work_queue"), None)
    card = (queue or {}).get("data") or {}
    rows = [t for t in card.get("threads") or [] if isinstance(t, dict)]
    r.checks.append(check("the queue is drawn", queue is not None, f"surfaces={c.surface_types}"))

    # The answer itself, entry by entry. This scenario once checked only that a card was drawn
    # and that the newsletter sender was absent from it — both trivially true of a card
    # offering NOBODY, which is what it was drawing. Then it looked for each waiting person's
    # first name anywhere in the stringified card, which a subject line could satisfy, and for
    # the answered people's full names, which a misleading answer could avoid (the 2026-09-28
    # deploy review, round 9, H-05). Now the queue's rows are matched to the world's threads by
    # id, each row must name who wrote last in its thread, and the spoken answer must name
    # exactly the people on the card — the waiting clause is its first sentence; the rest may
    # mention the newest thread, which is a different fact about a different list.
    said = c.answer.split(". ")[0]
    on_card = {str(row.get("from") or "") for row in rows}
    r.checks.append(check("the count on the card is its own rows", card.get("count") == len(rows),
                          f"count={card.get('count')} rows={len(rows)}"))
    r.checks.append(check("the answer names everyone the card says is waiting, and how many",
                          bool(rows) and all(name and name in said for name in on_card) and str(len(rows)) in said,
                          f"said={said!r} on_card={sorted(on_card)}"))
    r.checks.append(check("the automated sender is not offered as a customer",
                          data.NEWSLETTER_SENDER not in str(rows) and data.NEWSLETTER_SENDER not in said,
                          "newsletter sender present"))
    if not grounded(h):
        return r

    expected = world.needs_reply()
    answered = [t for t in world.threads if t not in expected]
    r.checks.append(check("the golden world has both kinds to tell apart",
                          bool(expected) and bool(answered),
                          f"{len(expected)} waiting, {len(answered)} not"))

    def _last_sender(thread: Any) -> str:
        return max(thread.messages, key=lambda m: (-m.days_ago, m.hour)).sender.split("<")[0].strip()

    wanted = {t.thread_id: _last_sender(t) for t in expected}
    queued = {str(row.get("thread_id") or ""): str(row.get("from") or "") for row in rows}
    r.checks.append(check("the queue holds exactly the threads the world says are waiting, and no other",
                          set(queued) == set(wanted), f"queued={sorted(queued)} expected={sorted(wanted)}"))
    r.checks.append(check("and each row names who wrote last in its own thread",
                          all(queued.get(tid) == who for tid, who in wanted.items()),
                          f"rows={queued} expected={wanted}"))
    others = {p.name for p in world.people.values() if p.name and p.name not in set(wanted.values())}
    r.checks.append(check("and the answer names nobody the world says is not waiting",
                          not [name for name in others if name in said],
                          f"named anyway: {sorted(name for name in others if name in said)}"))
    return r


async def unsupported_edit(h: Harness) -> Result:
    """It must never claim to have done what it cannot do (brief §30).

    Adding a line is supported now (app/families/order_edit.py); taking one OFF is not, and is a
    stated limitation (app/observability/contract.py). Scripted: the harness's model reaches for
    a removal tool that does not exist, as a model left to guess might, and then answers
    honestly. What is asserted is the Mac's side, which the script cannot supply: the model was
    handed the limitation in words, the gate refused the invented write, nothing was staged or
    changed, and the answer is held to the report's own FALSE_SUCCESS rule — the false-claim
    check this scenario lost when it stopped scripting anything (the 2026-09-28 deploy review,
    round 9, H-03).
    """
    from app.observability import contract

    r = Result("unsupported_edit", "Remove a line from this order")
    await h.open_order("1938", scenario="unsupported:open", session_id="unsup")
    said = "remove the Yard Jeans from this order"
    c = await h.ask(said, ("shopify_order_remove_item", {"order_id": world.order("1938").order_id}),
                    reply="I can't take a line off an order. I can put a note on it, or cancel and refund it.",
                    scenario="unsupported_edit", session_id="unsup")
    r.captures.append(c)
    r.checks.append(a_model_turn(c))
    prompt = h.provider.calls[-1] if h.provider.calls else ""
    r.checks.append(check("the Mac told the model, in words, that this is a limitation",
                          "The Mac cannot change what is ON an order" in prompt, "no limitation line in the prompt"))
    tried = [t for t in (c.raw.get("tool_calls") or []) if isinstance(t, dict)]
    r.checks.append(check("the invented write was refused at the gate",
                          [t.get("name") for t in tried] == ["shopify_order_remove_item"] and tried[0].get("ok") is False,
                          f"tool_calls={[(t.get('name'), t.get('ok'), str(t.get('error') or '')[:80]) for t in tried]}"))
    r.checks.append(check("nothing was staged", not h.runtime.sessions.get("unsup").proposals,
                          f"proposals={[p.operation for p in h.runtime.sessions.get('unsup').proposals]}"))
    r.checks.append(check("nothing was changed in the shop", getattr(h.store, "mutations_sent", -1) == 0,
                          f"mutations_sent={getattr(h.store, 'mutations_sent', 'NO COUNTER')}"))
    r.checks.append(check("no success card was drawn", c.surface("success") is None,
                          f"surfaces={c.surface_types}"))
    r.checks.append(check("and the answer does not claim it was done (the report's own FALSE_SUCCESS rule)",
                          not contract.reports_success(c.answer) and contract.reports_success("I've removed the jeans from the order."),
                          f"answer={c.answer[:120]!r}"))
    return r


async def linked_entities(h: Harness) -> Result:
    """An order names its customer, and the customer can be opened from it (brief §11)."""
    r = Result("linked_entities", "From the order to the customer")
    c = await h.open_order("1938", scenario="linked:open", session_id="link")
    card = c.data("order")
    customer_id = str(card.get("customer_id") or "")
    r.captures.append(c)
    r.checks.append(check("the order names its customer by id", bool(customer_id),
                          f"customer_id={customer_id!r}"))
    # Reading the customer is what puts them in memory; opening a link never reads the shop.
    await h.customer_history(customer_id, scenario="linked:read", session_id="link")
    await h.touch("navigation.back", scenario="linked:back", session_id="link")
    opened = await h.touch("open.entity", kind="customer", ref=customer_id, label=data.MIA.name,
                           scenario="linked:tap", session_id="link")
    r.captures.append(opened)
    r.checks += a_surface(opened, "customer", what="tapping the link opens the customer")
    r.checks.append(deterministic(opened))
    r.checks.append(check("the branch followed the link",
                          (opened.entity or {}).get("ref") == customer_id, f"entity={opened.entity}"))
    missing = await h.touch("open.entity", kind="order", ref="gid://shopify/Order/999999",
                            scenario="linked:missing", session_id="link")
    r.captures.append(missing)
    r.checks.append(check("a record the Mac no longer holds is refused, not half-drawn",
                          missing.raw.get("ok") is False, f"raw={ {k: missing.raw.get(k) for k in ('ok','code')} }"))
    return r


async def split_branches(h: Harness) -> Result:
    """Two halves of the orb keep their own entity (brief §21)."""
    r = Result("split_branches", "Two halves, two records")
    session = "split"
    left = await h.open_order("1938", scenario="split:left", session_id=session)
    fork = await h.client.post("/branches/fork", data={"session_id": session, "label": "right"},
                               headers={"Tailscale-User-Login": "owner@example.com",
                                        "X-Forwarded-For": "100.64.0.9"})
    body = fork.json() if fork.content else {}
    right_id = str(((body.get("branch") or {}).get("branch_id")) or body.get("branch_id") or "")
    r.checks.append(check("a second half was opened", bool(right_id), f"fork={str(body)[:140]}"))
    if not right_id:
        return r
    right = await h.open_order("1936", scenario="split:right", session_id=session, branch_id=right_id)
    r.captures += [left, right]
    left_branch = h.branch(session, left.branch_id)
    right_branch = h.branch(session, right_id)
    r.checks.append(check("the two halves hold different records",
                          (left_branch.entity or {}).get("ref") != (right_branch.entity or {}).get("ref"),
                          f"left={left_branch.entity} right={right_branch.entity}"))
    r.checks.append(check("the first half still holds the order it was left on",
                          (left_branch.entity or {}).get("ref") == world.order("1938").order_id,
                          f"left={left_branch.entity}"))
    r.checks.append(check("the second half holds its own",
                          (right_branch.entity or {}).get("ref") == world.order("1936").order_id,
                          f"right={right_branch.entity}"))
    return r


async def progressive_enrichment(h: Harness) -> Result:
    """The order goes up before the inbox has answered (brief §8)."""
    r = Result("enrichment", "The card first, the inbox after")
    c = await h.open_order("1938", scenario="enrichment")
    r.captures.append(c)
    r.checks += a_surface(c, "order", what="the order surface arrives with the turn")
    card = c.data("order")
    order_id = str(card.get("order_id") or "")
    r.checks.append(check("the core of the order is there at once",
                          bool(card.get("order_number")) and bool(card.get("items")),
                          f"items={len(card.get('items') or [])}"))
    if order_id:
        ms, extension = await h.enrich(order_id)
        c.enrichment_ms = round(ms, 1)
        r.checks.append(check("the rest is collected separately", isinstance(extension, dict),
                              f"enrichment={ms:.0f}ms keys={sorted(extension)[:6]}"))
        # Three numbers that have to be three numbers. This check used to be
        # `c.first_ui_ms is not None`, which restated the surface check eleven lines above and
        # could not fail — because first_ui_ms WAS total_ms, assigned from the same variable.
        r.checks.append(check("the card, the round trip and the enrichment are three measurements",
                              c.first_ui_ms is not None and c.first_ui_ms < c.total_ms
                              and c.enrichment_ms is not None,
                              f"card={c.first_ui_ms}ms round_trip={c.total_ms:.1f}ms enrichment={c.enrichment_ms}ms"))
    return r


async def forged_owner_headers(h: Harness) -> Result:
    """The owner's headers, sent by something that is not Tailscale (the 2026-09-28 deploy
    review, round 9, F-A2-FIXTURE).

    Every other scenario runs admitted: the harness stands in for a device Tailscale has
    vouched for. This one switches that off and runs the production identity check exactly —
    CROOKS_TAILSCALE_VERIFY on — against the very headers every scenario sends. From this
    process they are a claim nobody confirmed, so a sentence and a tap are both refused at the
    door: no model call, no read, no conversation, nothing staged.
    """
    r = Result("forged_owner_headers", "The owner's headers, from a process Tailscale never saw")
    was = h.admitted
    session = "forged"
    before_model = len(h.provider.calls)
    before_reads = len(getattr(h.store, "queries", []))
    h.configure(admitted=False)
    try:
        said = await h.say("show me order 1938", scenario="forged_owner_headers", session_id=session)
        tapped = await h.touch("open.area", area="orders", scenario="forged_owner_headers", session_id=session)
        # Without the forwarding headers: made on the server itself, to a public path.
        ping = await h.client.get("/ping")
    finally:
        h.configure(admitted=was)
    r.captures += [said, tapped]
    for what, capture in (("a sentence", said), ("a tap", tapped)):
        r.checks.append(check(f"{what} with forged owner headers is refused at the door",
                              capture.status == 403 and not capture.surfaces,
                              f"status={capture.status} raw={ {k: capture.raw.get(k) for k in ('error', 'who', 'code')} }"))
    r.checks.append(check("the model was never asked", len(h.provider.calls) == before_model,
                          f"model calls={len(h.provider.calls) - before_model}"))
    r.checks.append(check("and nothing was read", len(getattr(h.store, "queries", [])) == before_reads,
                          f"reads={len(getattr(h.store, 'queries', [])) - before_reads}"))
    r.checks.append(check("no conversation was made for the forger", not h.runtime.sessions.exists(session),
                          f"exists={h.runtime.sessions.exists(session)}"))
    r.checks.append(check("a public path asked directly still answers, so this is the identity check and not a dead server",
                          ping.status_code == 200, f"/ping → {ping.status_code}"))
    return r


SCENARIOS: tuple[tuple[str, Callable[[Harness], Awaitable[Result]]], ...] = (
    ("order_lookup", order_lookup),
    ("today_orders", today_orders),
    ("next_previous", next_and_previous),
    ("back", back_navigation),
    ("tabs", tabs_and_drilldown),
    ("customer_history", customer_history),
    ("needs_reply", needs_reply),
    ("linked_entities", linked_entities),
    ("unsupported_edit", unsupported_edit),
    ("split_branches", split_branches),
    ("enrichment", progressive_enrichment),
    ("forged_owner_headers", forged_owner_headers),
)

# The Phase 3 families' scenarios, one pack per family (experience/scenario_packs/*), so a
# new family adds a file rather than a line to the tuple above.
from experience.scenario_packs import collect as _collect_packs  # noqa: E402

SCENARIOS = SCENARIOS + tuple(s for s in _collect_packs() if s[0] not in {n for n, _ in SCENARIOS})
BY_NAME = dict(SCENARIOS)


async def run_all(h: Harness, only: str = "") -> list[Result]:
    """Every scenario, or one by name. A scenario that raises is a FAIL with its reason, never
    an exception that stops the rest of the run from being reported.

    A live run is narrowed to LIVE_SCENARIOS: the rest name a fixture record and would fail
    against the owner's own shop for a reason that says nothing about the code.
    """
    chosen = [(n, fn) for n, fn in SCENARIOS if not only or n == only]
    if getattr(h, "live", False):
        chosen = [(n, fn) for n, fn in chosen if n in LIVE_SCENARIOS]
    out: list[Result] = []
    for name, fn in chosen:
        _forget_the_last_scenario(h)
        try:
            out.append(await fn(h))
        except Exception as exc:  # noqa: BLE001 — one broken scenario must not hide the others
            out.append(Result(name, name, error=f"{type(exc).__name__}: {exc}"))
    return out


def _forget_the_last_scenario(h: Harness) -> None:
    """Clear the fixture world's own record of what has been asked of it.

    `tests/test_experience.py` builds a harness per scenario; this runner shares ONE across all
    of them, and the two disagreed. A scenario whose oracle is "nothing was changed" read the
    calculation log of the scenario before it and failed here while passing under pytest —
    which is the worst shape a test can have, because `make experience` is the command a person
    runs on the Mac and pytest is the one that says the build is fine.

    Only the LOG is cleared, never the world: the orders, the inbox and the catalogue are the
    golden data and a scenario that depended on being first would still be wrong. What goes is
    the record of calls, which belongs to a scenario and not to the shop.

    Each owner clears its own. The first version of this listed the store's fields here, and it
    went stale within the day — `drafts` was added to the fixture afterwards and leaked, which
    is the same failure a second time. So: the store forgets its log
    (`FixtureShopify.forget_scenario`), the anticipation layer is replaced with a fresh one,
    and the tiered cache is emptied. A scenario that opens an order and predicts the reads
    around it must find nothing already held, or "something was predicted at all" is false
    through no fault of the code.
    """
    store = getattr(h, "store", None)
    forget = getattr(store, "forget_scenario", None)
    if callable(forget):
        forget()
    else:  # a store without the hook — clear what every fake has
        for name in ("calculations", "queries"):
            log = getattr(store, name, None)
            if isinstance(log, list):
                log.clear()
        if isinstance(getattr(store, "mutations_sent", None), int):
            store.mutations_sent = 0

    # The anticipation layer holds in-flight predictions, a position per conversation and
    # counters a scenario asserts on. A fresh one is cleaner than a partial reset.
    try:
        from app.anticipation import engine as anticipation

        anticipation.install(None)
    except Exception:  # noqa: BLE001 — a runner that cannot reset it still runs the scenarios
        pass
    # And the cache, because a read already held is a read the layer rightly declines to
    # predict — which reads as "nothing was predicted" in the scenario after it.
    try:
        from app.memory import current as memory

        memory().clear()
    except Exception:  # noqa: BLE001
        pass
