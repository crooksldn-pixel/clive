"""Adding an item to an order (brief §10), driven the way the tablet drives it.

Phase 2's `unsupported_edit` scenario is the reason this file exists: "add a Black Convict
hoodie to this order" had to be refused, and the check was that it was refused honestly. What
is checked here is the other half — that it can now be done, and that doing it goes through
the picker, the priced card and the hold, in that order, with nothing applied until the last.

The sentence does not open the picker: it is the model's, like every sentence, and nothing
is prepared on the way to it; the picker is reached by touch from the order card's own
control. `order_add_item_sentence_defers` scripts what Claude then does — reads the catalogue
and stages the add — and holds it to the same boundary the picker meets.

A custom item (the owner's decision 8, 1 October 2026) is spoken only — there is no picker for
what the shop does not list — and `order_add_custom_item_sentence` holds it to the same card,
the same hold and the same "nothing applied" as the variant.
"""

from __future__ import annotations

import re

from experience.fixtures import data
from experience.harness import Harness
from experience.scenarios import Result, a_model_turn, a_surface, check, deterministic, grounded

ORDER = data.BY_NAME["#1938"]                    # Mia Jones, two lines, £89.00, unfulfilled
CANCELLED = data.BY_NAME["#1929"]                # David Randall, cancelled twelve days ago
HOODIE = "gid://shopify/ProductVariant/9102"     # Convict Hoodie, Black / M, £60.00


def _ok(c) -> bool:
    return bool(c.raw.get("ok", True))


def _code(c) -> str:
    return str(c.raw.get("code") or "")


def _detail(c) -> str:
    return str(c.raw.get("detail") or "")


def _amount(value) -> float | None:
    """The money in a fact, as a number. The card's facts are sentences — "£60.00 to the
    order", "£60.00 after this" — so this takes the figure and leaves the words, and returns
    None rather than 0.0 when there is no figure at all."""
    found = re.search(r"£\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", str(value or ""))
    if found is None:
        return None
    try:
        return float(found.group(1).replace(",", ""))
    except ValueError:
        return None


def _facts(c) -> dict[str, str]:
    return {str(f.get("label")): str(f.get("value")) for f in (c.data("confirmation").get("facts") or [])}


async def _open_order(h: Harness, session: str, number: str) -> None:
    await h.open_order(number, scenario=f"order_edit:open:{number}", session_id=session)


async def order_add_item_picker(h: Harness) -> Result:
    """The whole path: the words, the picker, the priced card, and nothing applied."""
    r = Result("order_add_item_picker", "Add a black medium Convict hoodie to this order")
    session = "edit1"
    await _open_order(h, session, "1938")

    # The words as the tablet's own control carries them, with the order that is on screen.
    c = await h.touch("order_edit.find", scenario="order_add_item_picker", session_id=session,
                      order_id=ORDER.order_id, product="convict hoodie", colour="black", size="medium")
    r.captures.append(c)
    r.checks.append(check("the tap succeeds", c.status == 200 and _ok(c), f"status={c.status} code={_code(c)!r} detail={_detail(c)!r}"))
    r.checks += a_surface(c, "variant_picker", what="draws the picker")
    r.checks.append(deterministic(c))
    picker = c.data("variant_picker")
    candidates = picker.get("candidates") or []
    r.checks.append(check("exactly one candidate, and it is named as the confident one",
                          len(candidates) == 1 and picker.get("confident_variant_id") == candidates[0].get("variant_id"),
                          f"count={len(candidates)} confident={picker.get('confident_variant_id')!r}"))
    r.checks.append(check("the picker is about the order on screen", picker.get("order_id") == ORDER.order_id,
                          f"order_id={picker.get('order_id')!r}"))
    r.checks.append(check("choosing stages nothing", not c.surface("confirmation") and c.raw.get("changed", {}).get("proposal_id") is None,
                          f"surfaces={c.surface_types}"))
    if grounded(h):
        first = candidates[0] if candidates else {}
        r.checks.append(check("it is the black medium hoodie, priced from the catalogue",
                              first.get("variant_id") == HOODIE and _amount(first.get("price")) == 60.0
                              and first.get("options") == ["Black", "M"],
                              f"candidate={first}"))

    # The gesture that asks the Mac to prepare it: ids and a number, nothing else.
    d = await h.touch("order_edit.stage", scenario="order_add_item_picker", session_id=session,
                      order_id=ORDER.order_id, variant_id=HOODIE, quantity=1)
    r.captures.append(d)
    r.checks.append(check("the Mac prepares it", d.status == 200 and _ok(d), f"status={d.status} code={_code(d)!r} detail={_detail(d)!r}"))
    r.checks += a_surface(d, "confirmation", what="draws the card that has to be authorised")
    card = d.data("confirmation")
    r.checks.append(check("it is this change, waiting, at the graver tier",
                          card.get("operation") == "order_edit_add_line" and card.get("status") == "pending" and card.get("risk") == "red",
                          f"operation={card.get('operation')!r} status={card.get('status')!r} risk={card.get('risk')!r}"))
    r.checks.append(check("a spoken yes cannot apply it: the gesture is a hold",
                          (card.get("interaction") or {}).get("kind") == "hold_to_arm",
                          f"interaction={(card.get('interaction') or {}).get('kind')!r}"))
    r.checks.append(check("and it says it cannot be undone", "cannot be undone" in str(card.get("detail") or "").lower() and card.get("reversible") is False,
                          f"detail={card.get('detail')!r} reversible={card.get('reversible')}"))
    facts = _facts(d)
    r.checks.append(check("the card names the variant and how many",
                          "Convict Hoodie" in facts.get("Adding", "") and "Black" in facts.get("Adding", "") and facts.get("Adding", "").startswith("1 x"),
                          f"adding={facts.get('Adding')!r}"))
    if grounded(h):
        # The consequence, checked as arithmetic rather than as a magic number: the order was
        # £89.00 and fully paid, a £60.00 hoodie goes on, so the total becomes £149.00 and the
        # customer owes the £60.00. Every one of those figures came from Shopify's own
        # CalculatedOrder — the fixture computes them from the catalogue's prices — and a
        # scenario that accepted the tool's arithmetic instead would prove nothing about it.
        was = 84.0 + data.SHIPPING
        adds = _amount(facts.get("Adds"))
        total = _amount(facts.get("New total"))
        owed = _amount(facts.get("Customer owes"))
        r.checks.append(check("what the line adds", adds == 60.0, f"adds={facts.get('Adds')!r}"))
        r.checks.append(check("the new total is the old one plus the line",
                              total is not None and adds is not None and abs(total - (was + adds)) < 0.005,
                              f"was={was} adds={adds} total={facts.get('New total')!r}"))
        r.checks.append(check("and what the customer will owe is what was added",
                              owed is not None and abs(owed - 60.0) < 0.005, f"owes={facts.get('Customer owes')!r}"))
        r.checks.append(check("the customer is not emailed by the change", facts.get("Customer emailed", "").startswith("no"),
                              f"emailed={facts.get('Customer emailed')!r}"))

    # Nothing has been applied. The two mutations that ran are the two that change nothing;
    # the fixture refuses `order_edit_commit` outright, so a prepare that tried to commit
    # would have failed here rather than passing quietly.
    ran = [name for name, _ in getattr(h.store, "calculations", [])]
    r.checks.append(check("only the two calculation mutations ran",
                          ran == ["order_edit_begin", "order_edit_add_variant"], f"mutations={ran}"))
    r.checks.append(check("nothing was changed in the shop", getattr(h.store, "mutations_sent", -1) == 0,
                          f"mutations_sent={getattr(h.store, 'mutations_sent', 'NO COUNTER')}"))
    e = await h.open_order("1938", said="show me order 1938 again", scenario="order_add_item_picker", session_id=session)
    r.captures.append(e)
    r.checks.append(check("and the order still reads what it did", _amount(e.data("order").get("total")) == 89.0,
                          f"total={e.data('order').get('total')!r}"))
    return r


async def order_add_item_ambiguous(h: Harness) -> Result:
    """"Add a hoodie" — four of them. A picker, not a guess, and nothing prepared."""
    r = Result("order_add_item_ambiguous", "Add a hoodie to this order")
    session = "edit2"
    await _open_order(h, session, "1938")
    c = await h.touch("order_edit.find", scenario="order_add_item_ambiguous", session_id=session, product="hoodie")
    r.captures.append(c)
    r.checks += a_surface(c, "variant_picker", what="draws the picker")
    r.checks.append(deterministic(c))
    picker = c.data("variant_picker")
    candidates = picker.get("candidates") or []
    r.checks.append(check("several to choose from", len(candidates) > 1, f"count={len(candidates)}"))
    r.checks.append(check("and none of them is called confident", picker.get("confident_variant_id") is None,
                          f"confident={picker.get('confident_variant_id')!r}"))
    r.checks.append(check("nothing is prepared and no card is waiting",
                          c.surface("confirmation") is None and not [p for p in h.runtime.sessions.get(session).proposals if p.status.value == "PENDING"],
                          f"surfaces={c.surface_types}"))
    r.checks.append(check("the answer asks for the choice rather than making it",
                          "choose from" in c.answer.lower(), c.answer[:120]))
    if grounded(h):
        hoodies = [v for v in data.VARIANTS.values() if "hoodie" in v["product"]["title"].lower()]
        r.checks.append(check("every hoodie variant in the catalogue is offered",
                              len(candidates) == len(hoodies), f"{len(candidates)} offered, {len(hoodies)} exist"))
    return r


async def order_add_item_cancelled(h: Harness) -> Result:
    """A cancelled order cannot be added to, and is refused in words at the point it matters."""
    r = Result("order_add_item_cancelled", "Add an item to a cancelled order")
    session = "edit3"
    await _open_order(h, session, "1929")
    c = await h.touch("order_edit.find", scenario="order_add_item_cancelled", session_id=session, product="crooks cap")
    r.captures.append(c)
    r.checks.append(check("the catalogue still answers", c.status == 200 and _ok(c), f"code={_code(c)!r} detail={_detail(c)!r}"))
    cap = next((x.get("variant_id") for x in (c.data("variant_picker").get("candidates") or []) if x.get("variant_id")), "")
    r.checks.append(check("a variant to try", bool(cap), f"candidates={c.data('variant_picker').get('candidates')}"))
    d = await h.touch("order_edit.stage", scenario="order_add_item_cancelled", session_id=session,
                      order_id=CANCELLED.order_id, variant_id=cap, quantity=1)
    r.captures.append(d)
    r.checks.append(check("it is refused, not attempted", d.status == 200 and not _ok(d) and _code(d) == "not_prepared",
                          f"status={d.status} code={_code(d)!r}"))
    r.checks.append(check("and the refusal says why, in words", "cancelled" in _detail(d).lower() and CANCELLED.name.lstrip("#") in _detail(d),
                          f"detail={_detail(d)!r}"))
    r.checks.append(check("no card was drawn and nothing is waiting",
                          not d.surfaces and not [p for p in h.runtime.sessions.get(session).proposals if p.status.value == "PENDING"],
                          f"surfaces={d.surface_types}"))
    r.checks.append(check("not one mutation was sent, calculation or otherwise",
                          not getattr(h.store, "calculations", []) and getattr(h.store, "mutations_sent", -1) == 0,
                          f"calculations={getattr(h.store, 'calculations', None)}"))
    return r


async def order_add_item_stale_picker(h: Harness) -> Result:
    """A picker left on the glass after the owner has moved to another order (the 2026-09-28
    deploy review, round 9, E-01). Its Add still carries the first order's id, and the first
    order WAS issued to this conversation — so only the check that it is the order on screen
    stands between that tap and a change to an order he is not looking at."""
    r = Result("order_add_item_stale_picker", "Add, tapped on a picker for an order no longer on screen")
    session = "edit5"
    other = data.BY_NAME["#1936"]
    await _open_order(h, session, "1938")
    c = await h.touch("order_edit.find", scenario="order_add_item_stale_picker", session_id=session,
                      order_id=ORDER.order_id, product="convict hoodie", colour="black", size="medium")
    r.captures.append(c)
    picker = c.data("variant_picker")
    chosen = next((x.get("variant_id") for x in (picker.get("candidates") or []) if x.get("variant_id")), "")
    r.checks.append(check("the picker was drawn for the first order", picker.get("order_id") == ORDER.order_id and bool(chosen),
                          f"order_id={picker.get('order_id')!r} chosen={chosen!r}"))
    # The owner moves on, on the same half.
    await _open_order(h, session, "1936")
    r.checks.append(check("the half is on the second order now",
                          (h.branch(session).entity or {}).get("ref") == other.order_id,
                          f"entity={h.branch(session).entity}"))
    d = await h.touch("order_edit.stage", scenario="order_add_item_stale_picker", session_id=session,
                      order_id=ORDER.order_id, variant_id=chosen, quantity=1)
    r.captures.append(d)
    r.checks.append(check("the old picker's Add is refused, in words",
                          d.status == 200 and not _ok(d) and _code(d) == "wrong_order" and "picker" in _detail(d).lower(),
                          f"status={d.status} code={_code(d)!r} detail={_detail(d)!r}"))
    r.checks.append(deterministic(d))
    r.checks.append(check("no card was drawn and nothing is waiting, on either order",
                          not d.surfaces and not [p for p in h.runtime.sessions.get(session).proposals if p.status.value == "PENDING"],
                          f"surfaces={d.surface_types}"))
    r.checks.append(check("not one mutation was sent, calculation or otherwise",
                          not getattr(h.store, "calculations", []) and getattr(h.store, "mutations_sent", -1) == 0,
                          f"calculations={getattr(h.store, 'calculations', None)}"))
    return r


async def order_add_item_sentence_defers(h: Harness) -> Result:
    """The spoken form: the model's, and the model's own attempt at the change is held to the
    same boundary as the picker (the 2026-09-28 deploy review, round 9, H-03).

    Scripted: the harness's model searches the catalogue with the words it heard and stages
    `shopify_order_add_item`, as the family's own docstring says Claude does. What is asserted
    is the Mac's side — the change comes back as the priced card at the graver tier, only the
    two calculation mutations ran, nothing was applied, and the answer does not say it was
    added. Before round 10 this sent the sentence to a model that called nothing, so none of
    that could fail.
    """
    from app.observability import contract

    r = Result("order_add_item_sentence_defers", "“Add a black hoodie to this order”, spoken")
    session = "edit4"
    await _open_order(h, session, "1938")

    def _chosen(calls):
        found = next((c.result for c in calls if c.name == "shopify_variant_search" and isinstance(c.result, dict)), {})
        first = next((x for x in (found.get("candidates") or []) if isinstance(x, dict)), {})
        return {"order_id": ORDER.order_id, "variant_id": str(first.get("variant_id") or ""), "quantity": 1}

    c = await h.ask("add a black medium Convict hoodie to this order",
                    ("shopify_variant_search", {"product": "convict hoodie", "colour": "black", "size": "medium"}),
                    ("shopify_order_add_item", _chosen),
                    reply="It's on the card with what it costs — hold it to add the hoodie.",
                    scenario="order_add_item_sentence_defers", session_id=session)
    r.captures.append(c)
    r.checks.append(a_model_turn(c))
    r.checks += a_surface(c, "confirmation", what="the model's change comes back as the priced card")
    card = c.data("confirmation")
    r.checks.append(check("it is this change, waiting, held to the graver gesture",
                          card.get("operation") == "order_edit_add_line" and card.get("status") == "pending"
                          and (card.get("interaction") or {}).get("kind") == "hold_to_arm",
                          f"operation={card.get('operation')!r} status={card.get('status')!r} "
                          f"interaction={(card.get('interaction') or {}).get('kind')!r}"))
    ran = [name for name, _ in getattr(h.store, "calculations", [])]
    r.checks.append(check("only the two calculation mutations ran, and nothing was applied",
                          ran == ["order_edit_begin", "order_edit_add_variant"] and getattr(h.store, "mutations_sent", -1) == 0
                          and all(p.executed_at is None for p in h.runtime.sessions.get(session).proposals),
                          f"calculations={ran} mutations_sent={getattr(h.store, 'mutations_sent', 'NO COUNTER')}"))
    r.checks.append(check("and the answer does not say it was added (the report's own FALSE_SUCCESS rule)",
                          not contract.reports_success(c.answer), f"answer={c.answer[:120]!r}"))
    return r


async def order_add_custom_item_sentence(h: Harness) -> Result:
    """"Add a £15 rush alteration to this order", spoken: a custom item, which the catalogue
    does not list (the owner's decision 8, 1 October 2026).

    Scripted: the harness's model stages `shopify_order_add_custom_item` with the title and the
    price it heard, and never a currency — the tool has no such argument. What is asserted is
    the Mac's side: the change comes back as the priced card at the graver tier, the price went
    to Shopify in the order's own currency, only the two calculation mutations ran, nothing was
    applied, and the answer does not say it was added.
    """
    from app.observability import contract

    r = Result("order_add_custom_item_sentence", "“Add a £15 rush alteration to this order”, spoken")
    session = "edit6"
    await _open_order(h, session, "1938")
    c = await h.ask("add a £15 rush alteration to this order",
                    ("shopify_order_add_custom_item", {"order_id": ORDER.order_id, "title": "Rush alteration", "price": 15, "quantity": 1}),
                    reply="It's on the card with what it costs — hold it to add the alteration.",
                    scenario="order_add_custom_item_sentence", session_id=session)
    r.captures.append(c)
    r.checks.append(a_model_turn(c))
    r.checks += a_surface(c, "confirmation", what="the model's change comes back as the priced card")
    card = c.data("confirmation")
    r.checks.append(check("it is this change, waiting, at the graver tier, held to the graver gesture",
                          card.get("operation") == "order_edit_add_custom_line" and card.get("status") == "pending"
                          and card.get("risk") == "red" and (card.get("interaction") or {}).get("kind") == "hold_to_arm",
                          f"operation={card.get('operation')!r} status={card.get('status')!r} risk={card.get('risk')!r} "
                          f"interaction={(card.get('interaction') or {}).get('kind')!r}"))
    r.checks.append(check("and it says it cannot be undone", "cannot be undone" in str(card.get("detail") or "").lower() and card.get("reversible") is False,
                          f"detail={card.get('detail')!r} reversible={card.get('reversible')}"))
    facts = _facts(c)
    r.checks.append(check("the card names the custom item and how many", facts.get("Adding") == "1 x Rush alteration",
                          f"adding={facts.get('Adding')!r}"))
    if grounded(h):
        # The order was £89.00 and fully paid; a £15.00 custom line goes on, so Shopify's
        # calculated order is £104.00 and the customer owes the £15.00.
        was = 84.0 + data.SHIPPING
        adds = _amount(facts.get("Adds"))
        total = _amount(facts.get("New total"))
        owed = _amount(facts.get("Customer owes"))
        r.checks.append(check("what the line adds", adds == 15.0, f"adds={facts.get('Adds')!r}"))
        r.checks.append(check("the new total is the old one plus the line",
                              total is not None and abs(total - (was + 15.0)) < 0.005, f"was={was} total={facts.get('New total')!r}"))
        r.checks.append(check("and what the customer will owe is what was added",
                              owed is not None and abs(owed - 15.0) < 0.005, f"owes={facts.get('Customer owes')!r}"))
        r.checks.append(check("the customer is not emailed by the change", facts.get("Customer emailed", "").startswith("no"),
                              f"emailed={facts.get('Customer emailed')!r}"))
    calculations = list(getattr(h.store, "calculations", []))
    ran = [name for name, _ in calculations]
    r.checks.append(check("only the two calculation mutations ran, and nothing was applied",
                          ran == ["order_edit_begin", "order_edit_add_custom_item"] and getattr(h.store, "mutations_sent", -1) == 0
                          and all(p.executed_at is None for p in h.runtime.sessions.get(session).proposals),
                          f"calculations={ran} mutations_sent={getattr(h.store, 'mutations_sent', 'NO COUNTER')}"))
    sent = calculations[1][1] if len(calculations) > 1 else {}
    r.checks.append(check("the price went to Shopify in the order's own currency, as the owner said it",
                          sent.get("price") == {"amount": "15.00", "currencyCode": data.CURRENCY} and sent.get("title") == "Rush alteration",
                          f"sent={sent}"))
    r.checks.append(check("and the answer does not say it was added (the report's own FALSE_SUCCESS rule)",
                          not contract.reports_success(c.answer), f"answer={c.answer[:120]!r}"))
    e = await h.open_order("1938", said="show me order 1938 again", scenario="order_add_custom_item_sentence", session_id=session)
    r.captures.append(e)
    r.checks.append(check("and the order still reads what it did", _amount(e.data("order").get("total")) == 89.0,
                          f"total={e.data('order').get('total')!r}"))
    return r


SCENARIOS = (
    ("order_add_item_picker", order_add_item_picker),
    ("order_add_item_ambiguous", order_add_item_ambiguous),
    ("order_add_item_cancelled", order_add_item_cancelled),
    ("order_add_item_stale_picker", order_add_item_stale_picker),
    ("order_add_item_sentence_defers", order_add_item_sentence_defers),
    ("order_add_custom_item_sentence", order_add_custom_item_sentence),
)
