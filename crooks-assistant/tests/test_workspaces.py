"""The screen represents the TASK, not the last tool that returned (§3, §6, §12).

D-3, verbatim from `docs/phase5/LIVE_SESSION_FORENSICS.md`. Turn `turn_1e7f630eae7e`:

    "Pull up the history of [name] and his orders. See how many times he's ordered, see how
     much he's spent, and see if he's in Gmail anywhere."

    tools:   ['gmail_search']          ← the only NEW read
    renders: [['email_list'], ['email_list']]

The spoken answer was complete and correct — two orders, sixty pounds each, £120 lifetime. The
Mac held all of it. The screen showed an email list, because the presentation layer drew the
most recent tool result and nothing else.

The chain this file holds is the replacement:

    USER INTENT → DESIRED WORKSPACE → DATA REQUIREMENTS → HELD/CACHED/NEW READS
               → PROGRESSIVE WORKSPACE HYDRATION

A new read ENRICHES the workspace it belongs to. It never replaces it. An empty section is an
empty section (§27) and an error in one section never destroys the others.
"""

from __future__ import annotations

import json

from app import entities, workspace
from app.presentation import UI_TYPES, present
from app.providers.base import ToolCall
from app.session.models import Session
from app.tools import (
    shopify_tools,  # noqa: F401 — registers the specs the rails are built from
)

CUSTOMER = "gid://shopify/Customer/7"
ORDER_A = "gid://shopify/Order/1962"
ORDER_B = "gid://shopify/Order/1930"

D3 = ("Pull up the history of Daniel and his orders. See how many times he's ordered, "
      "see how much he's spent, and see if he's in Gmail anywhere.")

HISTORY = {
    "customer_id": CUSTOMER, "name": "Daniel Stub", "email": "daniel@example.com",
    "orders": 2, "spent": "120.00 GBP", "standing": "returning", "since": "2026-03-01",
    "last_order": {"order_id": ORDER_A, "order_number": "CROOKS-1962"},
    "recent": [
        {"order_id": ORDER_A, "order_number": "CROOKS-1962", "total": "60.00 GBP",
         "placed_at": "2026-09-01T10:00:00Z", "fulfillment": "FULFILLED", "payment": "PAID"},
        {"order_id": ORDER_B, "order_number": "CROOKS-1930", "total": "60.00 GBP",
         "placed_at": "2026-08-02T10:00:00Z", "fulfillment": "FULFILLED", "payment": "PAID"},
    ],
}
THREAD_ID = "18f3a2b9c4d5e6f7"      # the shape Gmail actually returns, and the gate accepts
THREADS = {
    "query": "daniel@example.com",
    "threads": [{"thread_id": THREAD_ID, "from": "Daniel Stub", "from_email": "daniel@example.com",
                 "subject": "Where is my order", "date": "Mon", "snippet": "Any news?"}],
}
ORDER_DETAIL = {
    "order_id": ORDER_A, "order_number": "CROOKS-1962", "placed_at": "2026-09-01T10:00:00Z",
    "fulfillment": "UNFULFILLED", "payment": "PAID", "total": "60.00 GBP",
    "customer_name": "Daniel Stub", "customer_id": CUSTOMER, "customer_email": "daniel@example.com",
    "items": [{"title": "Yard Jeans", "variant": "Blue Wash / M", "sku": "YJ-M", "quantity": 1,
               "total": "60.00 GBP"}],
    "items_truncated": False,
    "ships_to": "London, United Kingdom",
    "shipping_address_full": "12 Somewhere Street, E1 6AN",  # must never reach the screen
}


def ok(name: str, result: dict) -> ToolCall:
    return ToolCall(name=name, args={}, ok=True, result=result)


def bad(name: str, code: str = "gmail_error") -> ToolCall:
    return ToolCall(name=name, args={}, ok=False, error=code, result=None)


def types(items: list[dict]) -> list[str]:
    return [i["type"] for i in items]


def only(items: list[dict], kind: str) -> dict:
    found = [i for i in items if i["type"] == kind]
    assert len(found) == 1, f"expected exactly one {kind}, got {types(items)}"
    return found[0]["data"]


def session(said: str, sid: str = "ws") -> Session:
    # A new conversation. Each conversation's entity graph lives in a process-wide table keyed
    # by its id (app/entities.py graph_for), so a fresh Session under an id another test used
    # (tests/test_r11_turn.py also has an "inbox") inherited that test's orders and customers:
    # run after it, the inbox row below found two orders and offered no order link.
    entities.forget(sid)
    live = Session(session_id=sid)
    live.heard = said
    return live


# --------------------------------------------------------------- D-3, the whole defect


def test_the_d3_request_renders_a_customer_workspace_not_an_email_list():
    """The turn from the timeline, with the history HELD from an earlier turn and Gmail the
    only new read. What was drawn was an email list, twice. What must be drawn is the
    customer."""
    live = session(D3, "d3")
    # Turn one: the owner asked about the customer, and the Mac read his history.
    present([ok("shopify_customer_history", HISTORY)], session=live)
    # Turn two: the D-3 question. gmail_search is the only NEW read.
    items = present([ok("gmail_search", THREADS)], session=live)

    assert "email_list" not in types(items), (
        "the last tool result became the screen again: " + str(types(items)))
    data = only(items, "customer_workspace")
    assert data["title"] == "Daniel Stub"
    # Everything the spoken answer got right is on the screen too.
    assert data["sections"]["orders"]["state"] == "ready"
    assert [r["order_number"] for r in data["sections"]["orders"]["rows"]] == ["#1962", "#1930"]
    assert any("120" in str(f["value"]) for f in data["header"]), data["header"]
    assert any("2" == str(f["value"]) for f in data["header"]), data["header"]
    # And the new read enriched the workspace's Inbox rather than becoming the screen.
    assert data["sections"]["inbox"]["state"] == "ready"
    assert [r["subject"] for r in data["sections"]["inbox"]["rows"]] == ["Where is my order"]


def test_the_same_request_in_one_turn_is_one_workspace_not_three_cards():
    """The same task when every read lands in the same turn: still one surface. §6's own
    words — `shopify_find_customer` → shell, `shopify_customer_history` → enrich .orders,
    `gmail_search` → enrich .email. NOT three cards."""
    items = present([
        ok("shopify_find_customer", {"query": "daniel", "customers": [
            {"customer_id": CUSTOMER, "name": "Daniel Stub", "email": "daniel@example.com",
             "orders": 2, "spent": "120.00 GBP"}]}),
        ok("shopify_customer_history", HISTORY),
        ok("gmail_search", THREADS),
    ], session=session(D3, "one-turn"))
    assert types(items).count("customer_workspace") == 1
    for gone in ("customer", "customer_list", "email_list"):
        assert gone not in types(items), f"{gone} is a second surface for the same person"


def test_ten_reads_touching_one_customer_produce_one_customer_surface():
    """His words, turn_541df4c7a2b6: "You just pulled up two in the same UI". Ten reads of one
    person are one person."""
    calls = []
    for _ in range(4):
        calls.append(ok("shopify_find_customer", {"query": "daniel", "customers": [
            {"customer_id": CUSTOMER, "name": "Daniel Stub", "email": "daniel@example.com",
             "orders": 2, "spent": "120.00 GBP"}]}))
        calls.append(ok("shopify_customer_history", HISTORY))
    calls.append(ok("gmail_search", THREADS))
    calls.append(ok("gmail_read_thread", {"thread_id": THREAD_ID, "message_count": 1, "messages": [
        {"message_id": "m1", "from": "Daniel Stub", "from_email": "daniel@example.com",
         "subject": "Where is my order", "body": "Any news?", "date": "Mon"}]}))
    items = present(calls, session=session(D3, "ten"))
    surfaces = [t for t in types(items) if t in ("customer_workspace", "customer", "customer_list")]
    assert surfaces == ["customer_workspace"], types(items)


# ---------------------------------------------------------------- §27, empty and error


def test_an_empty_gmail_section_preserves_the_rest_of_the_workspace():
    """EMPTY IS NOT ERROR, and an empty read is not a reason to throw the workspace away.
    The Inbox section says "No messages found" and the customer stays on screen."""
    items = present([
        ok("shopify_customer_history", HISTORY),
        ok("gmail_search", {"query": "daniel@example.com", "threads": []}),
    ], session=session(D3, "empty"))
    data = only(items, "customer_workspace")
    inbox = data["sections"]["inbox"]
    assert inbox["state"] == "empty"
    assert "no messages found" in inbox["note"].lower(), inbox["note"]
    assert inbox["rows"] == []
    # Nothing else moved.
    assert data["title"] == "Daniel Stub"
    assert data["sections"]["orders"]["state"] == "ready"
    assert len(data["sections"]["orders"]["rows"]) == 2
    assert data["sections"]["overview"]["state"] == "ready"


def test_an_error_in_one_section_does_not_destroy_the_others():
    """Gmail fell over. The customer, his lifetime value and his two orders are all still
    known, so all of them are still on the screen; the Inbox says what went wrong."""
    items = present([
        ok("shopify_customer_history", HISTORY),
        bad("gmail_search"),
    ], session=session(D3, "err"))
    data = only(items, "customer_workspace")
    assert data["sections"]["inbox"]["state"] == "error"
    assert data["sections"]["inbox"]["note"], "an error section that says nothing is a blank region"
    assert data["sections"]["orders"]["state"] == "ready"
    assert len(data["sections"]["orders"]["rows"]) == 2
    assert data["sections"]["overview"]["state"] == "ready"
    assert data["title"] == "Daniel Stub"
    # The failed service still gets its own error card; that is what it always did.
    assert "error" in types(items)


def test_a_section_still_being_read_is_loading_and_not_empty():
    """Progressive hydration: a section whose read has not landed says so. Marking it empty
    would be a lie the owner acts on."""
    plan = workspace.desired(D3, graph=_graph_with_history("hydrate"))
    assert plan is not None
    built = workspace.compose(plan, graph=_graph_with_history("hydrate"), pending=("inbox",))
    inbox = built["data"]["sections"]["inbox"]
    assert inbox["state"] == "loading" and inbox["note"]
    assert built["data"]["sections"]["orders"]["state"] == "ready"


# ------------------------------------------------------------------- §26, first viewport


def test_a_customer_first_viewport_answers_the_three_questions():
    """WHAT IS THIS / WHAT MATTERS / WHAT CAN I DO, from the payload and before any tab is
    opened. The live session's customer card answered none of them: it opened on an empty
    Email panel."""
    items = present([ok("shopify_customer_history", HISTORY), ok("gmail_search", THREADS)],
                    session=session(D3, "viewport"))
    data = only(items, "customer_workspace")

    # WHAT IS THIS — identity, and whether this person is new or returning.
    assert data["title"] == "Daniel Stub"
    assert data["subtitle"] == "daniel@example.com"
    assert data["status"].lower() in ("returning", "regular", "first order", "new", "no orders yet")

    # WHAT MATTERS — lifetime value, order count and the last order, as facts, not prose.
    keys = {f["key"].lower(): str(f["value"]) for f in data["header"]}
    assert "lifetime" in keys and "120" in keys["lifetime"]
    assert "orders" in keys and keys["orders"] == "2"
    assert "last order" in keys and "#1962" in keys["last order"]

    # WHAT CAN I DO — at least one offer, each of them a real destination (§18).
    assert data["actions"], "a workspace with nothing to do is a picture"
    for action in data["actions"]:
        assert action["label"] and action["command"]
        assert action.get("enabled") is True or action.get("reason"), action


def test_an_order_first_viewport_leads_with_the_order_not_with_its_items():
    """§12's ORDER list: number, customer, value, payment, fulfilment, date, primary attention,
    primary next actions — before Items, Shipping, Customer or Email are opened."""
    items = present([ok("shopify_order_detail", ORDER_DETAIL)],
                    session=session("Pull up order 1962 — what's on it, and where is it going?", "order-vp"))
    data = only(items, "order_workspace")
    assert data["title"] == "Order #1962"
    assert data["subtitle"] == "Daniel Stub"
    keys = {f["key"].lower(): str(f["value"]) for f in data["header"]}
    assert "60" in keys["value"]
    assert keys["payment"].lower() == "paid"
    assert keys["fulfilment"].lower() in ("unfulfilled", "not shipped", "to ship")
    assert keys["placed"]
    assert [s for s in data["sections"]] == list(workspace.SECTIONS["order"])
    assert data["sections"]["items"]["rows"][0]["title"] == "Yard Jeans"
    # The full street address is not an order fact the screen carries — it never was.
    assert "Somewhere Street" not in json.dumps(data)


# ------------------------------------------------------------------------- §26, no gids


def _display_strings(value, key: str = "", trail: str = "") -> list[tuple[str, str]]:
    """Every string in a payload that a renderer could print, with where it came from.

    A ref is not a display string: `ref`, `*_id` and `thread_id` are what a tap posts to
    `open.entity`, and they have to be the shop's own ids. Everything else is words a person
    reads.
    """
    out: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for k, v in value.items():
            out += _display_strings(v, str(k), f"{trail}.{k}")
    elif isinstance(value, list):
        for n, v in enumerate(value):
            out += _display_strings(v, key, f"{trail}[{n}]")
    elif isinstance(value, str):
        if key not in workspace.REF_KEYS:
            out.append((trail, value))
    return out


def test_no_raw_gid_reaches_a_non_debug_surface():
    """§26: "Order #1962", never "gid://shopify/Order/…". The ids stay on the wire as refs,
    because a tap needs them; no field a renderer prints may carry one."""
    hostile = {
        # The worst case: a shop whose order_number IS the gid, and a customer with no name.
        "order_id": ORDER_A, "order_number": ORDER_A, "total": "60.00 GBP",
        "payment": "PAID", "fulfillment": "UNFULFILLED", "placed_at": "2026-09-01T10:00:00Z",
        "customer_id": CUSTOMER, "customer_name": "", "customer_email": "",
        "items": [{"title": "", "variant": "", "quantity": 1, "total": "60.00 GBP"}],
    }
    items = present([ok("shopify_order_detail", hostile)],
                    session=session("Pull up order 1962", "gids"))
    for item in items:
        for where, value in _display_strings(item["data"]):
            assert "gid://" not in value, f"{item['type']}{where} would print {value!r}"


def test_the_refs_are_still_there_for_a_tap():
    """The other half of the rule: hiding the id from the reader must not take away the
    destination. A row that names a record still carries the ref the tap posts."""
    items = present([ok("shopify_customer_history", HISTORY)], session=session(D3, "refs"))
    data = only(items, "customer_workspace")
    assert data["ref"] == CUSTOMER
    assert [r["order_id"] for r in data["sections"]["orders"]["rows"]] == [ORDER_A, ORDER_B]


# --------------------------------------------------------------------------- §18, no fake UI


def test_a_row_the_mac_cannot_open_is_drawn_disabled_with_a_reason():
    """§18: a visible interactive element must have a valid server-backed destination BEFORE
    it is shown. `turn_dd093f86b92d` posted `open.entity`, was refused `not_held`, and drew an
    empty half. A row whose ref this conversation was never issued is not tappable."""
    live = session(D3, "fake-ui")
    data = only(present([ok("shopify_customer_history", HISTORY), ok("gmail_search", THREADS)],
                        session=live), "customer_workspace")
    for row in data["sections"]["orders"]["rows"] + data["sections"]["inbox"]["rows"]:
        assert row["open"] is True, row
        # And the Mac issued the ref, so `open.entity` cannot refuse it `not_held`.
        assert (row.get("order_id") or row.get("thread_id")) in live.issued_ids
    for action in data["actions"]:
        assert action["ref"] in live.issued_ids, action

    # A thread id that is not a shape the gate accepts is still SHOWN — the message is real
    # and hiding it would lose it — and shown as unopenable, with the reason on the row.
    odd = {"query": "x", "threads": [{**THREADS["threads"][0], "thread_id": "t-1"}]}
    live2 = session(D3, "fake-ui-2")
    data = only(present([ok("shopify_customer_history", HISTORY), ok("gmail_search", odd)],
                        session=live2), "customer_workspace")
    row = data["sections"]["inbox"]["rows"][0]
    assert row["subject"] == "Where is my order"
    assert row["open"] is False and row["open_note"], row
    assert "t-1" not in live2.issued_ids, "a ref that cannot be opened was issued anyway"


# ------------------------------------------------------- the tab the task implies (D-2)


def test_the_task_names_the_tab_it_implies_and_says_why():
    """D-2: every customer card in the live session opened on Email because the tab was a
    per-BRANCH value. The workspace names the tab the TASK implies and the reason for it.
    Where that state LIVES is workstream E's; naming it is this layer's.
    """
    orders = workspace.desired("Pull up his orders and his history", graph=_graph_with_history("tab-a"))
    assert orders.tab == "orders" and orders.tab_reason

    inbox = workspace.desired("Has Daniel emailed us about anything", graph=_graph_with_history("tab-b"))
    assert inbox.tab == "inbox"

    plain = workspace.desired("Pull up Daniel", graph=_graph_with_history("tab-c"))
    assert plain.tab == "overview", "a request that names nothing opens where the answers are"

    # And it is never a tab the workspace does not have.
    for plan in (orders, inbox, plain):
        assert plan.tab in workspace.SECTIONS[plan.kind]


def test_a_tab_with_nothing_behind_it_is_never_the_one_that_opens():
    """The live failure in one line: a request for orders and history landed on an empty
    Email panel. A tab whose section is empty cannot be the one the workspace opens on."""
    plan = workspace.desired("Has Daniel emailed us about anything", graph=_graph_with_history("tab-d"))
    assert plan.tab == "inbox"
    built = workspace.compose(plan, graph=_graph_with_history("tab-d"))
    data = built["data"]
    # Nobody has looked in the inbox, which is `unread` and not `empty`: claiming a section is
    # empty when no read has landed is a lie the owner acts on. Either way there is nothing
    # behind the tab, so it is not the one that opens.
    assert data["sections"]["inbox"]["state"] == "unread"
    assert data["tab"] != "inbox"
    assert data["tab_intended"] == "inbox", "what the task asked for is still recorded"
    assert data["sections"][data["tab"]]["state"] == "ready", data["tab"]
    assert data["tab_reason"], "a tab the system chose has to say why"


# --------------------------------------------------------------------------- the bounds


def test_the_workspace_types_are_in_the_vocabulary_on_both_sides():
    """The rule this repository has always kept: a card type is a hand-written renderer with
    its own bounds, named on both sides. `tests/test_web.py` holds the equality; this says
    which names this pass added."""
    import re
    from pathlib import Path

    for kind in ("customer_workspace", "order_workspace"):
        assert kind in UI_TYPES
    ui_js = (Path(__file__).resolve().parent.parent / "web" / "ui.js").read_text(encoding="utf-8")
    renderers = set(re.findall(r"^\s{4}(\w+): render\w+,$", ui_js, re.M))
    assert {"customer_workspace", "order_workspace"} <= renderers


def test_a_workspace_is_bounded():
    """Every list capped, every string truncated — the same two rules the rest of the
    vocabulary keeps. A workspace is a bigger card, not an unbounded one."""
    huge = {
        **HISTORY,
        "name": "N" * 500,
        "recent": [{"order_id": f"gid://shopify/Order/{n}", "order_number": f"CROOKS-{n}",
                    "total": "60.00 GBP", "placed_at": "2026-09-01T10:00:00Z",
                    "fulfillment": "FULFILLED", "payment": "PAID"} for n in range(80)],
    }
    many = {"query": "x", "threads": [
        {"thread_id": f"t-{n}", "from": "Daniel Stub", "from_email": "daniel@example.com",
         "subject": "S" * 400, "date": "Mon", "snippet": "z" * 900} for n in range(60)]}
    data = only(present([ok("shopify_customer_history", huge), ok("gmail_search", many)],
                        session=session(D3, "bounds")), "customer_workspace")
    assert len(data["title"]) <= workspace.MAX_TITLE_CHARS
    assert len(data["sections"]["orders"]["rows"]) <= workspace.MAX_ROWS
    assert len(data["sections"]["inbox"]["rows"]) <= workspace.MAX_ROWS
    assert len(data["header"]) <= workspace.MAX_HEADER_FACTS
    assert len(data["actions"]) <= workspace.MAX_ACTIONS
    for _where, value in _display_strings(data):
        assert len(value) <= workspace.MAX_VALUE_CHARS, _where


def test_no_section_claims_to_be_ready_with_nothing_in_it():
    """§12's complaint about the live session is that the UI was sparse AND too tall at once.
    A panel marked `ready` and holding neither a fact nor a row is the sparse half exactly —
    measured on an order with no money breakdown and no note, the Overview came back
    `ready(0 rows, 0 facts)`, which is a tab the owner opens for nothing.
    """
    live = session("Pull up order 1962 \u2014 what's on it, and where is it going?", "sparse")
    data = only(present([ok("shopify_order_detail", ORDER_DETAIL)], session=live), "order_workspace")
    for name, sec in data["sections"].items():
        if sec["state"] == "ready":
            assert sec["rows"] or sec["facts"], f"{name} is ready and empty"
        else:
            assert sec["note"], f"{name} is {sec['state']} and says nothing"

    live2 = session(D3, "sparse-2")
    data = only(present([ok("shopify_customer_history", HISTORY), ok("gmail_search", THREADS)],
                        session=live2), "customer_workspace")
    for name, sec in data["sections"].items():
        if sec["state"] == "ready":
            assert sec["rows"] or sec["facts"], f"{name} is ready and empty"
        else:
            assert sec["note"], f"{name} is {sec['state']} and says nothing"
    # And the tab bar says which is which before a finger opens any of them.
    assert {t["name"] for t in data["tabs"]} == set(workspace.SECTIONS["customer"])
    for tab in data["tabs"]:
        assert tab["state"] == data["sections"][tab["name"]]["state"]


def test_a_workspace_needs_an_identity_before_it_is_drawn():
    """No identity, no workspace: the old cards are better than an empty header. A read that
    found nobody still says so, the way it always did."""
    items = present([ok("shopify_find_customer", {"query": "nobody", "customers": []})],
                    session=session("Pull up Nobody", "none"))
    assert "customer_workspace" not in types(items)
    assert types(items) == ["customer_list"] and items[0]["data"]["empty"] is True


def test_an_analytic_question_is_not_turned_into_an_entity_workspace():
    """§13 is workstream D's, and this layer must not take its surfaces. "How many returning
    customers today" is a summary question; a customer workspace is not the answer to it."""
    items = present([ok("shopify_customer_history", HISTORY)],
                    session=session("Has anyone bought today that has bought before, a returning customer?", "d4"))
    assert "customer_workspace" not in types(items), types(items)


# ------------------------------------------------------------------ §12, the inbox list


def test_an_inbox_row_says_who_and_what_it_is_about():
    """§12's INBOX list: sender, subject, customer link, order link, needs-reply, age,
    priority. A row that carries only a sender and a snippet is a picture of an inbox; these
    are what make it somewhere to work from — and every one of them comes from what the Mac
    already holds, so the list costs no extra read.
    """
    live = session("Anything in the inbox?", "inbox")
    # The customer and his one order are already held, from an earlier turn.
    present([ok("shopify_customer_history", {**HISTORY, "orders": 1,
                                             "recent": [HISTORY["recent"][0]],
                                             "last_order": HISTORY["last_order"]})], session=live)
    items = present([ok("gmail_search", {**THREADS, "threads": [
        {**THREADS["threads"][0], "awaiting_reply": True, "known_customer": True}]})], session=live)
    row = only(items, "email_list")["threads"][0]

    assert row["from"] == "Daniel Stub" and row["subject"] == "Where is my order"
    assert row["date"] == "Mon"                                   # age
    assert row["needs_reply"] is True
    assert row["priority"] == "high"
    assert row["customer_link"] == {"kind": "customer", "ref": CUSTOMER,
                                    "label": "Daniel Stub", "command": "open.entity"}
    assert row["order_link"] == {"kind": "order", "ref": ORDER_A,
                                 "label": "#1962", "command": "open.entity"}
    # §18: both refs were issued before the links were offered, so neither tap is refused.
    assert CUSTOMER in live.issued_ids and ORDER_A in live.issued_ids


def test_an_inbox_row_offers_no_link_it_cannot_stand_behind():
    """Two rules from `app/context/graph.py`, kept: a name is not evidence, and several
    recent orders are "possible" rather than confident. A stranger gets no customer link and
    a customer with two orders in hand gets no order link — §18 would rather show nothing
    than a control that opens the wrong record."""
    stranger = session("Anything in the inbox?", "inbox-2")
    items = present([ok("gmail_search", {"query": "x", "threads": [
        {"thread_id": THREAD_ID, "from": "Daniel Stub", "from_email": "someone@example.com",
         "subject": "Hello", "date": "Mon", "snippet": ""}]})], session=stranger)
    row = only(items, "email_list")["threads"][0]
    assert "customer_link" not in row and "order_link" not in row
    assert row["priority"] == "unknown"

    # Known sender, two orders held: the customer is certain, the order is not.
    live = session("Anything in the inbox?", "inbox-3")
    present([ok("shopify_customer_history", HISTORY)], session=live)
    row = only(present([ok("gmail_search", THREADS)], session=live), "email_list")["threads"][0]
    assert row["customer_link"]["label"] == "Daniel Stub"
    assert "order_link" not in row, "two held orders is a guess, and a guess is not a link"


def _graph_with_history(sid: str) -> entities.EntityGraph:
    g = entities.graph_for(Session(session_id=sid))
    g.ingest("shopify_customer_history", HISTORY)
    return g


# ------------------------------------------------------- §12, in the owner's own words


def test_a_customer_workspace_offers_a_way_to_write_to_them():
    """He was looking at a customer card that carried the orders and the inbox and said:

        "I'm not seeing any UI here except email where there's nothing. I want to also be
        seeing his orders and his history and like an email write box"

    The orders and the history landed in this pass. The write box did not, and the §32
    screenshot matrix said so precisely once its detector stopped naming card types by hand:
    shot 10 came back `MISSING — the customer surface has no write`. A rich workspace is not
    only what is ON the screen; it is whether the record the screen is ABOUT can be acted on
    from there, and a reading surface with two doors out of it and no way to do the obvious
    thing is the sparse half of §12.

    §18 is the other half and is asserted below: the control is offered only where the Mac is
    HOLDING an address, because `compose.to_person` reads the address off its own copy of the
    record and refuses `no_address` otherwise — so a button drawn without one would be a
    refusal under a finger.
    """
    from app import commands
    from app.commands import Ctx
    from app.families import compose as composer
    from app.memory import ENTITY
    from app.memory import current as memory

    live = session(D3, "write")
    items = present([ok("shopify_customer_history", HISTORY)], session=live)

    # §18, the first half, asserted by its absence. The offer rests on the Mac's own COPY of
    # the record and not merely on permission, because `compose.to_person` does not re-read:
    # it takes the address off that copy. Before the record is in the cache there is nothing
    # to write from, so there is no button — which is what the workspace draws here, and what
    # `_still_held` is for.
    assert not [a for a in (only(items, "customer_workspace").get("actions") or [])
                if a.get("command") == "compose.to_person"], (
        "a write was offered over a record the Mac is not holding")

    # And now the record is held, exactly as a real read leaves it.
    memory().put(ENTITY, f"customer:{HISTORY['customer_id']}", dict(HISTORY), source="shopify")
    items = present([ok("shopify_customer_history", HISTORY)], session=live)
    data = only(items, "customer_workspace")
    actions = data.get("actions") or []
    write = [a for a in actions if a.get("command") == "compose.to_person"]
    assert write, f"no way to write to them: {[a.get('command') for a in actions]}"
    offer = write[0]
    assert offer["enabled"] is True and offer["ref"] and offer["kind"] == "customer", offer
    # The label names the person, not the mechanism.
    assert "Email" in offer["label"] and "compose" not in offer["label"].lower(), offer["label"]

    # And the control works: a composer addressed to them, from the Mac's own copy of the
    # record rather than from anything the tablet posted.
    branch = live.branch()
    out = commands.run("compose.to_person", Ctx(None, live, branch, {"customer_id": offer["ref"]}))
    assert out.ok, out
    drawn = out.surfaces[0].as_ui()
    assert drawn["type"] == "email_compose" and drawn["data"]["kind"] == "new"
    # `to` is a FIELD on the composer, not a bare string: a value, its status and whether it
    # may be typed over. The address came off a record the shop served, so it is `ok` and not
    # `uncertain` — which is what lets the composer be staged at all.
    recipient = drawn["data"]["to"]
    assert composer.EMAIL_ADDRESS.match(str(recipient["value"])), recipient
    assert recipient["status"] == "ok", recipient
    assert recipient["editable"] is True, "a new email to a person may be about anything"
    assert branch.compose and branch.compose["compose_id"] == out.changed["compose_id"]

    # And the other direction: a customer the Mac is not holding gets a refusal, not a
    # composer. The offer and the command now read the same store with the same key, so the
    # pair cannot drift into a control that is drawn and then refused.
    refused = commands.run("compose.to_person", Ctx(None, live, branch, {"customer_id": "cust-0000"}))
    assert not refused.ok, refused
    # A record with no address on it is a different refusal, and also not a drawn button.
    nameless = dict(HISTORY, customer_id="gid://shopify/Customer/8", email="")
    memory().put(ENTITY, f"customer:{nameless['customer_id']}", nameless, source="shopify")
    live.issue(nameless["customer_id"])
    out2 = commands.run("compose.to_person", Ctx(None, live, branch, {"customer_id": nameless["customer_id"]}))
    assert not out2.ok and out2.code == "no_address", out2
