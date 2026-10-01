"""Making an order and crediting an account (brief §11 and §13), the way the tablet does it.

Two scenarios per family, and what they are for is what a unit test cannot show: the OWNER's
own path. He is somewhere in the app, he taps a control, and what he gets is a form with what
the Mac has read on it — including, when the shop holds two people of the same name, both of
them and a button that will not light.

`order_new_ambiguous` is the one that matters most. The golden world holds two customers whose
names both match "Jones", and the whole of §11's "MUST detect duplicate/ambiguous customers
and refuse to guess" is visible in one capture: the card names them, the answer reads them
back, the button is off, and the gesture is refused if it is posted anyway.
"""

from __future__ import annotations

import re

from experience.fixtures import data
from experience.harness import Harness
from experience.scenarios import Result, a_surface, check, deterministic, grounded

POPPY = data.MILLIE          # one match for "Millie": the unambiguous case
MIA = data.MIA               # "Jones" matches Mia; the golden world has one Jones
CAP = "gid://shopify/ProductVariant/9301"     # Crooks Cap, £18.00 — the one-match item


def _ok(c) -> bool:
    return bool(c.raw.get("ok", True))


def _code(c) -> str:
    return str(c.raw.get("code") or "")


def _detail(c) -> str:
    return str(c.raw.get("detail") or "")


def _ws(c) -> dict:
    return c.data("workspace")


def _facts(c) -> list[dict]:
    return [f for f in (_ws(c).get("facts") or []) if isinstance(f, dict)]


def _labelled(c, label: str) -> list[str]:
    return [str(f.get("value")) for f in _facts(c) if f.get("label") == label]


def _card_facts(c) -> dict[str, str]:
    return {str(f.get("label")): str(f.get("value")) for f in (c.data("confirmation").get("facts") or [])}


def _amount(value) -> float | None:
    found = re.search(r"£\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)", str(value or ""))
    return float(found.group(1).replace(",", "")) if found else None


def _red_enabled(c) -> list[bool]:
    return [bool(a.get("enabled")) for a in (_ws(c).get("actions") or []) if a.get("risk") == "red"]


async def _start(h: Harness, session: str, scenario: str, command: str):
    """From a fresh tablet, the way the tablet gets there: a dock landing (the only command
    `POST /command` will start a conversation for), then the control."""
    await h.touch("open.area", scenario=scenario, session_id=session, area="orders")
    return await h.touch(command, scenario=scenario, session_id=session)


# --------------------------------------------------------------------------- making an order


async def order_new(h: Harness) -> Result:
    """An order built on a form and priced by Shopify as a draft before anything is agreed."""
    r = Result("order_new", "Create an order for Millie Fenwick")
    session = "onew1"
    h.configure()

    c = await _start(h, session, "order_new", "order.open")
    r.captures.append(c)
    r.checks.append(check("the tap succeeds", c.status == 200 and _ok(c), f"status={c.status} code={_code(c)!r} detail={_detail(c)!r}"))
    r.checks += a_surface(c, "workspace", what="draws the form")
    r.checks.append(deterministic(c))
    r.checks.append(check("it is empty and says what it needs",
                          "It needs a customer" in str(_ws(c).get("blocked") or ""),
                          f"blocked={_ws(c).get('blocked')!r}"))
    ident = str(_ws(c).get("workspace_id") or "")
    r.checks.append(check("the form has an id of its own", ident.startswith("ord_"), f"id={ident!r}"))

    # Who it is for. One person matches, so the Mac resolves it and reads their address.
    d = await h.touch("order.field", scenario="order_new", session_id=session,
                      workspace_id=ident, field="customer", value="Millie")
    r.captures.append(d)
    r.checks += a_surface(d, "workspace", what="redraws the form")
    r.checks.append(deterministic(d))
    if grounded(h):
        r.checks.append(check("the one customer of that name is resolved",
                              any(POPPY.name in v for v in _labelled(d, "Customer")),
                              f"facts={_facts(d)}"))
        r.checks.append(check("and the confirmation address came from the shop, not from the words",
                              any(POPPY.email in v for v in _labelled(d, "Customer")),
                              f"facts={_facts(d)}"))
    r.checks.append(check("it still cannot be prepared: there is nothing on it",
                          "nothing on it" in str(_ws(d).get("blocked") or "") and _red_enabled(d) == [False],
                          f"blocked={_ws(d).get('blocked')!r} actions={_ws(d).get('actions')}"))

    # What is on it. "cap" matches one variant, so the line goes on at the catalogue's price.
    await h.touch("order.field", scenario="order_new", session_id=session,
                  workspace_id=ident, field="item", value="cap")
    await h.touch("order.field", scenario="order_new", session_id=session,
                  workspace_id=ident, field="quantity", value="2")
    e = await h.touch("order.additem", scenario="order_new", session_id=session, workspace_id=ident)
    r.captures.append(e)
    r.checks += a_surface(e, "workspace", what="redraws the form with the line on it")
    r.checks.append(deterministic(e))
    if grounded(h):
        price = float(data.VARIANTS[CAP]["price"])
        # The order's lines are rows of their own on the card (round 12), each with its
        # quantity and its money; the facts beneath them are the order's.
        lines = [r for r in (_ws(e).get("rows") or []) if isinstance(r, dict)]
        r.checks.append(check("the line is on it at the catalogue's price",
                              any(line.get("title") == "Crooks Cap" and line.get("quantity") == "× 2"
                                  and _amount(line.get("amount")) == round(price * 2, 2) for line in lines),
                              f"lines={[(line.get('title'), line.get('quantity'), line.get('amount')) for line in lines]}"))
        r.checks.append(check("and the goods add up",
                              _amount(next(iter(_labelled(e, "Goods")), "")) == round(price * 2, 2),
                              f"goods={_labelled(e, 'Goods')}"))
    r.checks.append(check("now it can be prepared", not str(_ws(e).get("blocked") or "") and _red_enabled(e) == [True],
                          f"blocked={_ws(e).get('blocked')!r} actions={_ws(e).get('actions')}"))

    # The gesture that asks the Mac to prepare it: one id, and nothing else.
    f = await h.touch("order.stage", scenario="order_new", session_id=session, workspace_id=ident)
    r.captures.append(f)
    r.checks.append(check("the Mac prepares it", f.status == 200 and _ok(f), f"status={f.status} code={_code(f)!r} detail={_detail(f)!r}"))
    r.checks += a_surface(f, "confirmation", what="draws the card that has to be authorised")
    card = f.data("confirmation")
    r.checks.append(check("it is this change, waiting, at the graver tier",
                          card.get("operation") == "draft_order_complete" and card.get("status") == "pending"
                          and card.get("risk") == "red",
                          f"operation={card.get('operation')!r} status={card.get('status')!r} risk={card.get('risk')!r}"))
    r.checks.append(check("and the gesture is the gravest this build has: a hold and a drag",
                          (card.get("interaction") or {}).get("kind") == "hold_drag_target",
                          f"interaction={(card.get('interaction') or {}).get('kind')!r}"))
    facts = _card_facts(f)
    r.checks.append(check("the card names the customer and what is on the order",
                          POPPY.name in facts.get("Customer", "") and "2 x Crooks Cap" in facts.get("Items", ""),
                          f"customer={facts.get('Customer')!r} items={facts.get('Items')!r}"))
    r.checks.append(check("it says the money is Shopify's, priced as a draft that exists now",
                          facts.get("Priced as", "").startswith("draft #D") and "in Admin now" in facts.get("Priced as", ""),
                          f"priced={facts.get('Priced as')!r}"))
    r.checks.append(check("and whether the order will be owed or taken",
                          "not paid" in facts.get("Payment", ""), f"payment={facts.get('Payment')!r}"))
    if grounded(h):
        price = float(data.VARIANTS[CAP]["price"])
        r.checks.append(check("the total is the draft's own arithmetic",
                              _amount(facts.get("Total")) == round(price * 2, 2),
                              f"total={facts.get('Total')!r} expected={price * 2:.2f}"))

    # A DRAFT was made — a real object in the shop, which is the point — and no order was.
    drafts = getattr(h.store, "drafts", None)
    r.checks.append(check("exactly one draft was made, and it carries no price of ours",
                          isinstance(drafts, list) and len(drafts) == 1
                          and "originalUnitPrice" not in str(drafts),
                          f"drafts={drafts}"))
    r.checks.append(check("it is tagged so the owner can find it in Admin",
                          isinstance(drafts, list) and bool(drafts) and drafts[0].get("tags") == ["CROOKS assistant"],
                          f"tags={(drafts or [{}])[0].get('tags')}"))
    r.checks.append(check("and no order was created: the fixture refuses the completion outright",
                          getattr(h.store, "mutations_sent", -1) == 0,
                          f"mutations_sent={getattr(h.store, 'mutations_sent', 'NO COUNTER')}"))
    return r


async def order_new_ambiguous(h: Harness) -> Result:
    """Two people whose name matches. Named, not guessed at — the whole of §11's rule."""
    r = Result("order_new_ambiguous", "Create an order for someone whose name is not unique")
    session = "onew2"
    h.configure()
    c = await _start(h, session, "order_new_ambiguous", "order.open")
    ident = str(_ws(c).get("workspace_id") or "")

    # Two of the golden world's people begin with these letters: Mia Jones and Millie
    # Fenwick. Two, not five, because two is the case a shop actually meets — and because a
    # scenario that produced every customer in the world would be testing the search.
    d = await h.touch("order.field", scenario="order_new_ambiguous", session_id=session,
                      workspace_id=ident, field="customer", value="mi")
    r.captures.append(d)
    r.checks += a_surface(d, "workspace", what="redraws the form")
    r.checks.append(deterministic(d))
    could_be = _labelled(d, "Could be")
    blocked = str(_ws(d).get("blocked") or "")
    r.checks.append(check("several people match and every one of them is named",
                          len(could_be) > 1, f"could_be={could_be}"))
    r.checks.append(check("the form says it will not guess", "I will not guess" in blocked, f"blocked={blocked!r}"))
    r.checks.append(check("and the answer reads them back rather than choosing",
                          "will not guess" in d.answer and "customers match" in d.answer, d.answer[:220]))
    r.checks.append(check("the button that would prepare it is off", _red_enabled(d) == [False],
                          f"actions={_ws(d).get('actions')}"))
    if grounded(h):
        r.checks.append(check("each candidate is named with something to tell them apart by",
                              all("·" in row and "orders" in row for row in could_be), f"could_be={could_be}"))

    # And the Mac refuses the gesture too, so the greyed button is not the only guard.
    e = await h.touch("order.stage", scenario="order_new_ambiguous", session_id=session, workspace_id=ident)
    r.captures.append(e)
    r.checks.append(check("the gesture is refused, not attempted",
                          e.status == 200 and not _ok(e) and _code(e) == "not_ready",
                          f"status={e.status} code={_code(e)!r}"))
    r.checks.append(check("and the refusal names them and says it will not guess",
                          "will not guess" in _detail(e), f"detail={_detail(e)!r}"))
    r.checks.append(check("no card is waiting and no draft was made",
                          e.surface("confirmation") is None
                          and not getattr(h.store, "drafts", [])
                          and not [p for p in h.runtime.sessions.get(session).proposals if p.status.value == "PENDING"],
                          f"drafts={getattr(h.store, 'drafts', None)}"))
    return r


# ------------------------------------------------------- the same, said (round 12)

THE_SENTENCE = ("find the customer who ordered the black medium hoodie to SL4 1QN and make a new order "
                "for them in the next size up")
HOODIE_L = "gid://shopify/ProductVariant/9103"   # Convict Hoodie, Black / L — one up from #1938's M


def _found_then_opened(calls):
    """Claude reading the found order off the search, as it reads any id off a result: the
    order, and the variant of the line that matched, one size up."""
    order = calls[0].result["orders"][0]
    return {"order_id": order["order_id"], "variant_id": order["matched_items"][0]["variant_id"], "size_step": 1}


async def order_by_voice(h: Harness) -> Result:
    """The owner's own sentence (29 September): find who ordered it from an item and a
    postcode, and make them a new order in the next size up — then a custom item, a line
    discount and postage said onto the same card, and the draft Shopify is asked for is exactly
    that."""
    r = Result("order_by_voice", "Find the customer from what they ordered and where, and order the next size up")
    session = "ovoice1"
    h.configure()

    a = await h.ask(THE_SENTENCE, ("shopify_find_order", {"item": "black medium hoodie", "address": "SL4 1QN"}),
                    ("shopify_order_open", _found_then_opened), reply="Mia Jones, #1938. A new order in the large is on screen.",
                    scenario="order_by_voice", session_id=session)
    r.captures.append(a)
    r.checks.append(check("every call is one Claude could make", not a.unmakeable, f"unmakeable={a.unmakeable}"))
    r.checks += a_surface(a, "workspace", what="lands on the new order")
    r.checks.append(check("the new order is the first thing on the screen, not a customer screen",
                          a.surface_types[:1] == ["workspace"] and "customer" not in a.surface_types,
                          f"surfaces={a.surface_types}"))
    lines = [x for x in (_ws(a).get("rows") or []) if isinstance(x, dict)]
    ident = str(_ws(a).get("workspace_id") or "")
    if grounded(h):
        r.checks.append(check("it is for the customer who ordered it, going where that order went",
                              _ws(a).get("title") == MIA.name
                              and any("as on #1938" in v for v in _labelled(a, "Address")),
                              f"title={_ws(a).get('title')!r} address={_labelled(a, 'Address')}"))
        r.checks.append(check("with the same hoodie one size up — M was ordered, L is on it",
                              [x.get("detail", "").split(" · ")[0] for x in lines] == ["Black / L"], f"lines={lines}"))
    r.checks.append(check("and it is ready for Prepare", not str(_ws(a).get("blocked") or "") and _red_enabled(a) == [True],
                          f"blocked={_ws(a).get('blocked')!r}"))

    b = await h.ask("add a custom back print at twelve pounds, take ten percent off the hoodie, and four pounds postage",
                    ("shopify_order_build", {"add": [{"title": "Custom back print", "price": 12}],
                                             "lines": [{"line": 1, "percent_off": 10}], "postage": 4}),
                    reply="Added.", scenario="order_by_voice", session_id=session)
    r.captures.append(b)
    r.checks.append(check("every call is one Claude could make", not b.unmakeable, f"unmakeable={b.unmakeable}"))
    r.checks += a_surface(b, "workspace", what="redraws the same order")
    rows = [x for x in (_ws(b).get("rows") or []) if isinstance(x, dict)]
    r.checks.append(check("the same order, with the print on it and the discount on the hoodie",
                          _ws(b).get("workspace_id") == ident and len(rows) == 2
                          and rows[0].get("discount") == "10% off" and rows[1].get("title") == "Custom back print",
                          f"rows={[(x.get('title'), x.get('discount'), x.get('amount')) for x in rows]}"))

    f = await h.touch("order.stage", scenario="order_by_voice", session_id=session, workspace_id=ident)
    r.captures.append(f)
    r.checks += a_surface(f, "confirmation", what="draws the card that has to be authorised")
    drafts = getattr(h.store, "drafts", None) or []
    sent = drafts[-1] if drafts else {}
    # Exact means every part of the draft the card speaks for, not only the lines: one draft, for
    # the customer the order was found for, confirmed to her own address, delivered to the whole
    # of the address that order went to, with the postage he said (round 13, X1-03).
    r.checks.append(check("exactly one draft was made in the shop", isinstance(drafts, list) and len(drafts) == 1,
                          f"drafts={len(drafts)}"))
    if grounded(h):
        parcel = data.BY_NAME["#1938"].address
        r.checks.append(check("the draft carries exactly those lines and that discount",
                              sent.get("lineItems") == [
                                  {"variantId": HOODIE_L, "quantity": 1,
                                   "appliedDiscount": {"title": "Discount", "value": 10.0, "valueType": "PERCENTAGE"}},
                                  {"title": "Custom back print", "originalUnitPrice": "12.00", "quantity": 1}],
                              f"lineItems={sent.get('lineItems')}"))
        r.checks.append(check("it is for the customer the order was found for, confirmed to her own address",
                              sent.get("customerId") == MIA.customer_id and sent.get("email") == MIA.email,
                              f"customerId={sent.get('customerId')!r} email={sent.get('email')!r}"))
        r.checks.append(check("and goes to the whole of the address on the order it came from",
                              sent.get("shippingAddress") == {
                                  "firstName": parcel["firstName"], "lastName": parcel["lastName"],
                                  "address1": parcel["address1"], "city": parcel["city"], "zip": parcel["zip"],
                                  "countryCode": parcel["countryCodeV2"]}
                              and sent.get("useCustomerDefaultAddress") is False,
                              f"shippingAddress={sent.get('shippingAddress')}"))
        r.checks.append(check("with the postage he said",
                              sent.get("shippingLine") == {"title": "Postage", "price": "4.00"},
                              f"shippingLine={sent.get('shippingLine')}"))
        r.checks.append(check("the card's total is the draft's own arithmetic: £54 + £12 + £4 postage",
                              _amount(_card_facts(f).get("Total")) == 70.0, f"total={_card_facts(f).get('Total')!r}"))
    r.checks.append(check("and no order was created: the fixture refuses the completion outright",
                          getattr(h.store, "mutations_sent", -1) == 0,
                          f"mutations_sent={getattr(h.store, 'mutations_sent', 'NO COUNTER')}"))
    return r


# --------------------------------------------------------------------------- store credit


async def store_credit_give(h: Harness) -> Result:
    """A credit onto an account that already has some: the balance read, the consequence
    shown, and nothing given until the card is held."""
    r = Result("store_credit_give", "Put £20 of store credit on Mia's account")
    session = "cred1"
    h.configure()
    # Her record has to be one this conversation has looked up: the read below takes a
    # customer id and the gate holds it to ids the conversation was handed. So the scenario
    # asks the question that reads her, as the owner would.
    await h.open_order("1938", scenario="store_credit_give", session_id=session)
    looked = await h.customer_history(MIA.customer_id, scenario="store_credit_give", session_id=session)
    r.captures.append(looked)
    r.checks += a_surface(looked, "customer", what="reads her record")
    r.checks.append(check("looking her up hands this conversation her id",
                          MIA.customer_id in (h.runtime.sessions.get(session).issued_ids or set()),
                          f"lane={looked.lane} surfaces={looked.surface_types}"))

    # The way in is the model calling the read tool, because opening this form needs a READ
    # of the balance and a command reads nothing. So it is asked for in a sentence, through
    # `POST /turn` with the owner's own request, and the harness's model makes the call Claude
    # makes for it — through the gate, with the authority the door stamped on this request
    # and nothing set up around it (the 2026-09-28 deploy review, round 9, H-07).
    asked = await h.ask("put twenty pounds of store credit on Mia's account",
                        ("shopify_store_credit", {"customer_id": MIA.customer_id, "amount": 20}),
                        reply="It's on the form; Prepare the credit when you're happy with it.",
                        scenario="store_credit_give", session_id=session)
    r.captures.append(asked)
    called = [t for t in (asked.raw.get("tool_calls") or []) if isinstance(t, dict)]
    r.checks.append(check("the read is allowed for a customer this conversation looked up",
                          [t.get("name") for t in called] == ["shopify_store_credit"] and all(t.get("ok") for t in called),
                          f"tool_calls={[(t.get('name'), t.get('ok'), str(t.get('error') or '')[:80]) for t in called]}"))
    r.checks += a_surface(asked, "workspace", what="draws the credit form from that read")
    from app.families import store_credit as sc

    conversation = h.runtime.sessions.get(session)
    from app.families import _workspace as ws

    workspace = ws.held(conversation.branch(), sc.KIND)
    r.checks.append(check("and a form is open on the Mac", workspace is not None,
                          f"workspace={None if workspace is None else workspace.get('kind')}"))
    if workspace is None:
        return r
    ident = str(workspace["workspace_id"])
    if grounded(h):
        r.checks.append(check("the balance on it was read from the shop", sc._balance(workspace) == 15.0,
                              f"balance={sc._balance(workspace)}"))

    # A keystroke on the form, through the same command the tablet posts.
    c = await h.touch("credit.field", scenario="store_credit_give", session_id=session,
                      workspace_id=ident, field="reason", value="the late parcel")
    r.captures.append(c)
    r.checks += a_surface(c, "workspace", what="redraws the form")
    r.checks.append(deterministic(c))
    facts = {str(f.get("label")): str(f.get("value")) for f in _facts(c)}
    r.checks.append(check("the form shows what they have, what is being added, and the result",
                          {"Has now", "Adding", "Would have"} <= set(facts), f"facts={facts}"))
    if grounded(h):
        r.checks.append(check("and the consequence is arithmetic over what was read",
                              _amount(facts.get("Has now")) == 15.0 and _amount(facts.get("Adding")) == 20.0
                              and _amount(facts.get("Would have")) == 35.0, f"facts={facts}"))

    d = await h.touch("credit.stage", scenario="store_credit_give", session_id=session, workspace_id=ident)
    r.captures.append(d)
    r.checks.append(check("the Mac prepares it", d.status == 200 and _ok(d), f"status={d.status} code={_code(d)!r} detail={_detail(d)!r}"))
    r.checks += a_surface(d, "confirmation", what="draws the card that has to be authorised")
    card = d.data("confirmation")
    r.checks.append(check("it is this change, waiting, at the gravest tier",
                          card.get("operation") == "store_credit_credit" and card.get("status") == "pending"
                          and card.get("risk") == "red"
                          and (card.get("interaction") or {}).get("kind") == "hold_drag_target",
                          f"operation={card.get('operation')!r} interaction={(card.get('interaction') or {}).get('kind')!r}"))
    money = _card_facts(d)
    r.checks.append(check("the card says what they have and what they will have",
                          _amount(money.get("Has now")) == 15.0 and _amount(money.get("Will have")) == 35.0,
                          f"facts={money}"))
    r.checks.append(check("that it is spendable at once", "immediately" in money.get("Spendable", ""),
                          f"spendable={money.get('Spendable')!r}"))
    r.checks.append(check("and it says it cannot be taken back",
                          "cannot be taken back" in str(card.get("detail") or "").lower(),
                          f"detail={card.get('detail')!r}"))
    r.checks.append(check("nothing was credited", getattr(h.store, "mutations_sent", -1) == 0,
                          f"mutations_sent={getattr(h.store, 'mutations_sent', 'NO COUNTER')}"))
    return r


async def store_credit_not_on_this_store(h: Harness) -> Result:
    """A shop that has not got store credit. The answer says what is unavailable, that the
    code for it is here, and that it is the store's own configuration — which is the
    difference between "we cannot" and "you have not let us"."""
    r = Result("store_credit_not_on_this_store", "Store credit on a shop that has not got it")
    session = "cred2"
    h.configure()
    await h.open_order("1938", scenario="store_credit_not_on_this_store", session_id=session)
    await h.customer_history(MIA.customer_id, scenario="store_credit_not_on_this_store", session_id=session)

    from app.families import _workspace as ws
    from app.families import store_credit as sc

    before = getattr(h.store, "store_credit", None)
    h.store.store_credit = None                 # a shop where Shopify does not serve the field
    try:
        # Asked for as the owner asks, through the door (H-07): the harness's model calls the
        # read tool Claude calls for it, with the authority the request was given.
        asked = await h.ask("put twenty pounds of store credit on Mia's account",
                            ("shopify_store_credit", {"customer_id": MIA.customer_id, "amount": 20}),
                            reply="This shop hasn't got store credit switched on.",
                            scenario="store_credit_not_on_this_store", session_id=session)
        # The capability probe, separately and named as what it is: a UNIT-level check of the
        # family's state, called directly because the capability table is read at start-up and
        # not by a request.
        probed = await sc._probe(type("R", (), {"shopify": h.store, "store_credit_sample": MIA.customer_id})())
    finally:
        h.store.store_credit = before
    r.captures.append(asked)
    conversation = h.runtime.sessions.get(session)
    called = [t for t in (asked.raw.get("tool_calls") or []) if isinstance(t, dict)]
    text = " ".join(str(t.get("error") or "") for t in called if t.get("name") == "shopify_store_credit")

    r.checks.append(check("the read says so rather than failing obscurely",
                          bool(called) and not called[0].get("ok") and "does not have store credit" in text, text[:200]))
    r.checks.append(check("it says the code for it exists",
                          "The code for it is here and reviewed" in text, text[:260]))
    r.checks.append(check("and that it is the store's own configuration",
                          "Shopify enables store credit per store" in text, text[-200:]))
    r.checks.append(check("no form is opened for a feature the store has not got",
                          ws.held(conversation.branch(), sc.KIND) is None, "a workspace was opened"))
    r.checks.append(check("(unit-level probe) the capability state is NOT_SUPPORTED_BY_STORE, not a missing scope",
                          probed.get("state") == "NOT_SUPPORTED_BY_STORE",
                          f"probed={probed}"))
    r.checks.append(check("nothing was sent to the shop", getattr(h.store, "mutations_sent", -1) == 0,
                          f"mutations_sent={getattr(h.store, 'mutations_sent', 'NO COUNTER')}"))
    return r


SCENARIOS = (
    ("order_new", order_new),
    ("order_new_ambiguous", order_new_ambiguous),
    ("order_by_voice", order_by_voice),
    ("store_credit_give", store_credit_give),
    ("store_credit_not_on_this_store", store_credit_not_on_this_store),
)
