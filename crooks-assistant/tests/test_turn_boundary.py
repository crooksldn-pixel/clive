"""The turn path and the write boundary, now that every sentence is a model turn.

The round-9 deploy review (2026-09-28) read the turn route after the fast lane went and found
the places where what the owner is looking at, what he said and what a tap would act on could
come apart. Each test here drives the real /turn and /command routes, the real gate, the real
action engine and the real presentation against a fake shop. The only stand-in is Claude: a
scripted model that makes real tool calls through the real dispatcher, as Claude does, and
the assertions are about what the Mac does with those calls — never about the script's own
output.
"""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from app.actions.ledger import ActionLedger
from app.clients.shopify import ShopifyClient
from app.main import app
from app.providers.base import TurnResult
from app.session.manager import SessionManager
from app.tools import shopify_tools
from app.tools.dispatch import dispatch
from tests.test_context import CUSTOMER_NODE, ORDER_NODE, inbox

OWNER = "owner@example.com"
PROXIED = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.9"}

# Two orders for two people, and the first person's customer record. Built from the order read
# model's own fixture so every field the cards and the rail read is there.
A, B = "gid://shopify/Order/1938", "gid://shopify/Order/1940"
DANIEL, MIA = "gid://shopify/Customer/7", "gid://shopify/Customer/8"


def _order(ref: str, number: str, customer: str, name: str, email: str) -> dict:
    node = copy.deepcopy(ORDER_NODE)
    node.update({"id": ref, "name": f"CROOKS-{number}"})
    node["customer"] = {**node["customer"], "id": customer, "displayName": name,
                        "defaultEmailAddress": {"emailAddress": email}}
    first, _, last = name.partition(" ")
    node["shippingAddress"] = {**node["shippingAddress"], "firstName": first, "lastName": last}
    return node


def _customer(ref: str, name: str, email: str, order_ref: str, number: str) -> dict:
    node = copy.deepcopy(CUSTOMER_NODE)
    node.update({"id": ref, "displayName": name, "defaultEmailAddress": {"emailAddress": email},
                 "lastOrder": {"id": order_ref, "name": f"CROOKS-{number}"}})
    for edges in (node["openOrders"]["edges"], node["orders"]["edges"]):
        edges[0]["node"] = {**edges[0]["node"], "id": order_ref, "name": f"CROOKS-{number}"}
    return node


class Shop(ShopifyClient):
    """Two orders, their two customers, and every mutation that reaches it (there must be none)."""

    def __init__(self) -> None:
        super().__init__("fake.myshopify.com", "2025-07")
        from zoneinfo import ZoneInfo

        self._shop = {"name": "CROOKS LDN", "myshopifyDomain": "fake.myshopify.com", "ianaTimezone": "Europe/London", "currencyCode": "GBP"}
        self._tz = ZoneInfo("Europe/London")
        self.orders = {
            A: _order(A, "1938", DANIEL, "Daniel Sear", "daniel@example.com"),
            B: _order(B, "1940", MIA, "Mia Kowalski", "mia@example.com"),
        }
        self.customers = {
            DANIEL: _customer(DANIEL, "Daniel Sear", "daniel@example.com", A, "1938"),
            MIA: _customer(MIA, "Mia Kowalski", "mia@example.com", B, "1940"),
        }
        self.queries: list[tuple[str, dict]] = []
        self.mutations: list[tuple[str, dict]] = []

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        variables = variables or {}
        self.queries.append((query, variables))
        if "CrooksScopes" in query:
            scopes = ("read_orders", "write_orders", "read_customers", "write_customers")
            return {"data": {"currentAppInstallation": {"accessScopes": [{"handle": h} for h in scopes]}}}
        if "CrooksOrderByName" in query:
            digits = str(variables.get("q", "")).split(":")[-1]
            found = [n for n in self.orders.values() if digits and n["name"].endswith(digits)]
            return {"data": {"orders": {"edges": [{"node": n} for n in found]}}}
        if "CrooksCustomerOrders" in query:
            return {"data": {"customer": self.customers.get(variables.get("id"))}}
        if "CrooksSuggestedRefund" in query:
            # Shopify's own suggestion for a refund: back to the card it was paid with.
            money = lambda v: {"shopMoney": {"amount": f"{v:.2f}", "currencyCode": "GBP"}}  # noqa: E731
            amount = 60.0 if variables.get("full") else float(variables.get("shippingAmount") or 0) or 20.0
            node = self.orders.get(variables.get("id"))
            return {"data": {"order": node and {"id": node["id"], "name": node["name"], "suggestedRefund": {
                "amountSet": money(amount), "subtotalSet": money(amount), "totalTaxSet": money(0), "maximumRefundableSet": money(60.0),
                "shipping": {"amountSet": money(0), "maximumRefundableSet": money(5.0)},
                "suggestedTransactions": [{"amountSet": money(amount), "maximumRefundableSet": money(60.0), "gateway": "shopify_payments",
                                           "kind": "SUGGESTED_REFUND", "parentTransaction": {"id": "gid://shopify/OrderTransaction/1"}}],
                "refundLineItems": [],
            }}}}
        if "FindCustomers" in query:
            said = str(variables.get("q") or "").lower()
            found = [c for c in self.customers.values() if said and said in c["displayName"].lower()]
            return {"data": {"customers": {"edges": [{"node": c} for c in found]}}}
        if variables.get("id") in self.orders:
            return {"data": {"order": self.orders[variables["id"]]}}
        return {"data": {"order": None}}

    async def mutate(self, name: str, variables: dict) -> dict:
        self.mutations.append((name, dict(variables)))
        raise AssertionError(f"nothing in these tests may reach the shop with a change ({name})")


Step = Callable[[Any, list, str], Awaitable[str]]


class Scripted:
    """Claude, as far as the routes are concerned. Each turn runs the step the test queued —
    real tool calls, through the real dispatcher and gate, on the request's own task, as the
    provider runs them — and answers with what the step returns."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.prompts: list[str] = []
        self.steps: list[Step] = []

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def health(self): return True, "fake"
    async def reset_session(self, session_id): ...
    async def set_system_prompt(self, prompt): ...
    async def interrupt(self, session_id): return True

    async def turn(self, session_id: str, text: str) -> TurnResult:
        self.prompts.append(text)
        session = self.runtime.sessions.get_or_create(session_id)
        calls: list = []
        step = self.steps.pop(0) if self.steps else None
        answer = await step(session, calls, text) if step is not None else "the model answered"
        return TurnResult(text=answer, tool_calls=calls, session_id=session_id)


def reads(*steps: tuple[str, dict]) -> Step:
    """A step that makes these tool calls in order. An argument given as a callable is worked
    out from the calls before it, as the model reads an id off the last result."""
    async def step(session, calls, text):
        for name, args in steps:
            resolved = {k: (v(calls) if callable(v) else v) for k, v in args.items()}
            await dispatch(name, resolved, session=session, timeout_s=5, calls=calls)
        return "Here it is."
    return step


def found_order(calls) -> str:
    """The id of the order the last find returned — what Claude reads off the result."""
    return str((((calls[-1].result or {}).get("orders") or [{}])[0]).get("order_id") or "")


def found_customer(calls) -> str:
    return str((((calls[-1].result or {}).get("customers") or [{}])[0]).get("customer_id") or "")


def show_order(number: str) -> Step:
    return reads(("shopify_find_order", {"query": number}), ("shopify_order_detail", {"order_id": found_order}))


@pytest.fixture()
async def shop(monkeypatch, tmp_path):
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))

    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        store = Shop()
        runtime.shopify = store
        shopify_tools.bind(store, threads_for=inbox())
        runtime.actions.ledger = ActionLedger(tmp_path)
        runtime.sessions = SessionManager()
        runtime.sessions.on_drop.append(runtime.actions.forget_session)
        runtime.provider = Scripted(runtime)
        runtime.settings = runtime.settings.model_copy(
            update={"writes_enabled": True, "allowed_logins": OWNER, "writes_local_owner": False, "tailscale_verify": False}
        )
        app.state.allowed_logins = runtime.allowed_logins
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            client.runtime, client.store, client.model = runtime, store, runtime.provider
            yield client


async def say(client, text: str, session_id: str, **extra) -> dict:
    response = await client.post("/turn", json={"text": text, "session_id": session_id, **extra}, headers=PROXIED)
    assert response.status_code == 200, response.text
    return response.json()


async def tap(client, command: str, session_id: str, **fields) -> dict:
    response = await client.post("/command", data={"session_id": session_id, "command": command, **fields}, headers=PROXIED)
    assert response.status_code == 200, response.text
    return response.json()


def records(body: dict) -> list[tuple[str, str]]:
    """The records the cards show, by type and id."""
    out = []
    for item in body.get("ui") or []:
        data = item.get("data") or {}
        ref = data.get("order_id") or data.get("customer_id") or data.get("thread_id") or (data.get("ref") if item["type"].endswith("_workspace") else "")
        if ref:
            out.append((item["type"], ref))
    return out


# ------------------------------------------------------------------ a spoken yes (D2-02)


def stage_cancel(order_ref: str) -> Step:
    """Claude proposing a cancellation: find the order, then the write — staged, never sent."""
    number = order_ref.rsplit("/", 1)[-1]
    return reads(("shopify_find_order", {"query": number}), ("shopify_order_cancel", {"order_id": found_order}))


async def _pending_cancel(shop, session_id: str) -> str:
    shop.model.steps.append(stage_cancel(A))
    body = await say(shop, "cancel order 1938", session_id)
    (card,) = [i["data"] for i in body["ui"] if i["type"] == "confirmation"]
    assert card["status"] == "pending" and card["risk"] == "red", card
    return card["proposal_id"]


@pytest.mark.parametrize("said", ["yes, #1938", "yes 1938", "yes, the one for Sam", "Yes #1940", "go ahead with 1940", "yes £60"])
async def test_a_yes_that_says_anything_more_is_an_instruction_and_withdraws_the_waiting_card(shop, said):
    """Closes D2-02. "Yes, #1938" used to have its digits and symbols deleted and be read as a
    bare yes: the model was never asked, the waiting cancellation was not withdrawn, and the
    number he said was dropped at the write boundary. Anything beyond the fixed words is an
    instruction: the model is asked (and sees what was said), and the waiting card goes, as
    every new instruction withdraws it."""
    session_id = f"yes-{abs(hash(said)) % 10_000}"
    proposal_id = await _pending_cancel(shop, session_id)
    asked = len(shop.model.prompts)

    body = await say(shop, said, session_id)

    assert len(shop.model.prompts) == asked + 1, f"{said!r} did not reach the model"
    assert shop.model.prompts[-1].split("\n")[1] == said, "the model is handed exactly what was said"
    assert body["revoked"] == [proposal_id], f"{said!r} left the cancellation waiting"
    assert shop.runtime.actions.find(proposal_id).status.value == "REVOKED"
    assert not [i for i in body["ui"] if i["type"] == "confirmation" and i["data"].get("status") == "pending"]
    assert shop.store.mutations == []


@pytest.mark.parametrize("said", ["yes", "Yes please.", "go ahead", "OK, go ahead!", "okay"])
async def test_a_bare_yes_still_answers_from_the_card_and_withdraws_nothing(shop, said):
    """The interlock the write boundary keeps: a bare yes with a card waiting is not sent to the
    model (which would withdraw the very card) and applies nothing."""
    session_id = f"bare-{abs(hash(said)) % 10_000}"
    proposal_id = await _pending_cancel(shop, session_id)
    asked = len(shop.model.prompts)

    body = await say(shop, said, session_id)

    assert len(shop.model.prompts) == asked, f"{said!r} went to the model"
    assert body["revoked"] == [] and shop.runtime.actions.find(proposal_id).status.value == "PENDING"
    assert "Nothing happens until you" in body["answer"]
    assert shop.store.mutations == []


# -------------------------------------------------------- an answer that finished late (D2-01)


def held_until(gate: asyncio.Event, read: asyncio.Event, number: str) -> Step:
    """Claude reading an order and then taking its time over the sentence: the reads are done,
    and the answer lands only when the test says so."""
    async def step(session, calls, text):
        await show_order(number)(session, calls, text)
        read.set()
        await gate.wait()
        return f"Order {number}."
    return step


async def test_an_answer_replaced_by_a_newer_question_moves_nothing_when_it_finishes_last(shop):
    """Closes D2-01. The owner asks about #1938, then about #1940 while the first answer is
    still being written; the #1940 answer lands, and then the #1938 one does. The late answer
    used to redraw the half, move its cursor back to #1938 and reconcile #1938's cards into the
    live workspace — so "cancel it", a tapped Add a note and the next prompt's "where we are"
    all pointed at an order the owner had moved off. It publishes nothing now."""
    from app import progressive

    gate, read = asyncio.Event(), asyncio.Event()
    shop.model.steps = [held_until(gate, read, "1938"), show_order("1940")]

    older = asyncio.create_task(say(shop, "show me order 1938", "late"))
    await asyncio.wait_for(read.wait(), 5)
    newer = await say(shop, "show me order 1940", "late")
    gate.set()
    late = await asyncio.wait_for(older, 5)

    session = shop.runtime.sessions.get("late")
    branch = session.branch()
    assert ("order", B) in records(newer), newer["ui"]
    # The half stands where the NEWER answer put it.
    assert branch.entity["ref"] == B, f"the late answer moved the cursor back to {branch.entity}"
    assert {(u["type"], u["data"].get("order_id")) for u in branch.last_ui if u["type"] == "order"} == {("order", B)}
    newest_order = next(c for c in session.context if c["kind"] == "order")
    assert newest_order["ref"] == B, "the context stack was handed the old order as though it were new"
    assert session.context[0]["ref"] in (B, MIA), session.context[0]
    # The late answer published no cards, and says which turn it was.
    assert late["ui"] == [] and late["turn_id"] != newer["turn_id"] and late["turn_id"].startswith("turn_")
    # The live workspace on this half is the newer turn's, and the old order's cards were not
    # reconciled into it.
    workspace = progressive.current("late", branch.branch_id)
    assert workspace is not None and workspace.turn_id == newer["turn_id"]
    assert A not in json.dumps([p.public() for p in workspace.patches], default=str)
    # Nothing is left saying the half is still working, and the next question is told where
    # the owner actually is.
    assert branch.in_flight == 0 and branch.state() != "WORKING"
    await say(shop, "and when was it paid?", "late")
    where = [line for line in shop.model.prompts[-1].split("\n") if line.startswith("[Where we are:")]
    assert where and "1940" in where[0] and "1938" not in where[0], where


async def test_a_late_answer_does_not_end_the_newer_turn_still_running_on_its_half(shop):
    """The newer turn reset the half's count of turns in flight when it began; an older answer
    finishing in the middle of it must not count it down, or the chip stops saying WORKING
    while the newer question is still being answered."""
    first_gate, first_read = asyncio.Event(), asyncio.Event()
    second_gate, second_read = asyncio.Event(), asyncio.Event()
    shop.model.steps = [held_until(first_gate, first_read, "1938"), held_until(second_gate, second_read, "1940")]

    older = asyncio.create_task(say(shop, "show me order 1938", "count"))
    await asyncio.wait_for(first_read.wait(), 5)
    newer = asyncio.create_task(say(shop, "show me order 1940", "count"))
    await asyncio.wait_for(second_read.wait(), 5)
    first_gate.set()
    await asyncio.wait_for(older, 5)

    branch = shop.runtime.sessions.get("count").branch()
    assert branch.in_flight == 1 and branch.state() == "WORKING", "the late answer ended the running turn"
    second_gate.set()
    body = await asyncio.wait_for(newer, 5)
    assert ("order", B) in records(body) and branch.entity["ref"] == B
    assert branch.in_flight == 0


async def test_a_cancelled_answer_ends_its_own_turn_and_moves_nothing(shop):
    """A hold that cancels the question, with nothing asked after it: the turn still ends (the
    half stops saying WORKING and the session says READY), and the order it read is not put on
    the half."""
    gate, read = asyncio.Event(), asyncio.Event()
    shop.model.steps = [show_order("1940"), held_until(gate, read, "1938")]
    await say(shop, "show me order 1940", "cancel")
    branch = shop.runtime.sessions.get("cancel").branch()

    asked = asyncio.create_task(say(shop, "show me order 1938", "cancel"))
    await asyncio.wait_for(read.wait(), 5)
    cancelled = await shop.post("/cancel", data={"session_id": "cancel", "branch_id": branch.branch_id}, headers=PROXIED)
    assert cancelled.status_code == 200
    gate.set()
    body = await asyncio.wait_for(asked, 5)

    assert body["ui"] == [] and branch.entity["ref"] == B
    assert branch.in_flight == 0 and branch.state() != "WORKING"
    assert shop.runtime.sessions.get("cancel").state == "READY"


# ---------------------------------------- the cursor follows one record, and only one (D2-04, D1-02)


def chips(body: dict, card_type: str, ref: str) -> list[dict]:
    """The rail on the card of this type showing this record."""
    for item in body["ui"]:
        data = item.get("data") or {}
        if item["type"] == card_type and ref in (data.get("order_id"), data.get("customer_id"), data.get("thread_id"), data.get("ref")):
            return list(data.get("actions") or [])
    raise AssertionError(f"no {card_type} card for {ref}: {[i['type'] for i in body['ui']]}")


def note_chip(body: dict, ref: str) -> dict:
    (chip,) = [a for a in chips(body, "order", ref) if a.get("id") == "note"]
    return chip


def dictated_note(said_note: str) -> Step:
    """Claude taking dictation for a tapped Add a note: the note goes on the record the tapped
    control named in the prompt — the id the Mac put beside the words — and nowhere else."""
    import re

    async def step(session, calls, text):
        bound = re.search(r"id (gid://shopify/Order/\d+)\. If these words are for that", text)
        assert bound, f"the prompt carried no bound record: {text[-300:]!r}"
        await dispatch("shopify_order_note_append", {"order_id": bound.group(1), "note": said_note},
                       session=session, timeout_s=5, calls=calls)
        return "The note is ready on the card."
    return step


async def test_a_workspace_moves_the_cursor_and_the_tapped_note_lands_on_the_order_shown(shop):
    """Closes D1-02. When the task asks for more than one thing about an order, present() draws
    an order workspace in place of the order card, and the cursor used to look only for the
    card — so it stayed on the order before. The tablet binds Add a note to the half's cursor,
    so the note dictated over #1940's workspace was staged against #1938. The whole path, as
    the tablet drives it: the answer, the tap that binds the words, the words, the card."""
    shop.model.steps = [show_order("1938"), show_order("1940"), dictated_note("Gift wrap it")]
    await say(shop, "show me order 1938", "ws")
    shown = await say(shop, "show me the items and the shipping on order 1940", "ws")

    assert [i["type"] for i in shown["ui"]][0] == "order_workspace", [i["type"] for i in shown["ui"]]
    assert ("order_workspace", B) in records(shown)
    assert shown["branch"]["entity"]["ref"] == B, f"the cursor stayed on {shown['branch']['entity']}"

    # The tablet's Add a note: `voice.bind` with the half's entity, exactly as web/app.js posts it.
    entity = shown["branch"]["entity"]
    bound = await tap(shop, "voice.bind", "ws", family="order.add_note", kind=entity["kind"], ref=entity["ref"])
    assert bound["ok"] is True, bound
    noted = await say(shop, "gift wrap it", "ws")

    prompt = shop.model.prompts[-1]
    assert B in prompt and A not in prompt.split("[Just before saying this", 1)[1].split("]")[0]
    (card,) = [i["data"] for i in noted["ui"] if i["type"] == "confirmation"]
    proposal = shop.runtime.actions.find(card["proposal_id"])
    assert proposal.entity_ref == B and proposal.entity_label.endswith("1940"), (proposal.entity_ref, proposal.entity_label)
    assert shop.store.mutations == []


async def test_two_orders_on_one_screen_move_nothing_and_neither_card_can_bind_the_other(shop):
    """Closes D2-04 for the case it names. Two orders on the screen are a list: the cursor
    stays where it was, on #1938. A listening chip binds the CURSOR, so #1940's Add a note used
    to arm the microphone for #1938. Only the card that is the cursor keeps a listening chip;
    #1940's still offers the note, as words that name #1940."""
    shop.model.steps = [
        show_order("1938"),
        reads(("shopify_order_detail", {"order_id": A}), ("shopify_find_order", {"query": "1940"}),
              ("shopify_order_detail", {"order_id": found_order})),
    ]
    await say(shop, "show me order 1938", "two")
    both = await say(shop, "put 1938 and 1940 side by side", "two")

    assert {("order", A), ("order", B)} <= set(records(both)), records(both)
    assert both["branch"]["entity"]["ref"] == A
    assert note_chip(both, A)["family"] == "order.add_note", "the card that IS the cursor keeps its listening chip"
    other = note_chip(both, B)
    assert other["family"] == "", "a chip on #1940 would bind the cursor, #1938"
    assert "1940" in other["instruction"] and other["mode"] == "ask", other


async def test_an_order_beside_a_customer_is_not_a_record_the_cursor_can_choose(shop):
    """Closes D2-04. An order and a customer on one screen are two records, and the Mac cannot
    say which one the owner means; it used to take whichever card came first. It moves nothing
    now, and the order's listening chip — which would bind the cursor — stands down."""
    shop.model.steps = [
        show_order("1938"),
        reads(("shopify_find_order", {"query": "1940"}), ("shopify_order_detail", {"order_id": found_order}),
              ("shopify_customer_history", {"customer_id": MIA})),
    ]
    await say(shop, "show me order 1938", "mixed")
    mixed = await say(shop, "order 1940 and her account", "mixed")

    kinds = {kind for kind, _ in records(mixed)}
    assert {"order", "customer"} <= kinds, records(mixed)
    assert mixed["branch"]["entity"]["ref"] == A, f"the cursor chose {mixed['branch']['entity']} from a mixed screen"
    assert note_chip(mixed, B)["family"] == ""


async def test_one_record_on_the_screen_is_still_where_the_owner_now_is(shop):
    """What must not get worse: one order drawn, however it was reached, is where the cursor
    goes, and its Add a note binds that order."""
    shop.model.steps = [show_order("1938"), show_order("1940")]
    await say(shop, "show me order 1938", "one")
    moved = await say(shop, "and 1940?", "one")
    assert moved["branch"]["entity"]["ref"] == B
    assert note_chip(moved, B)["family"] == "order.add_note"


# ------------------------------------------- two halves thinking at once, one proposal (D2-03)


async def test_a_change_staged_by_one_half_belongs_to_it_while_the_other_half_is_asked_something(shop):
    """Closes D2-03. The session's `acting_branch` is one field for both halves: a question to
    the right half that starts while the left half is still working overwrites it, and a
    change the left half then staged on its own request's task was filed against the right
    half. The right half's next instruction then withdrew it, and a "yes" to the right half
    was answered as though the left's card were waiting there. Each request now holds its own
    half (app/tools/context.py `CURRENT_BRANCH`)."""
    shop.model.steps = [show_order("1938")]
    await say(shop, "show me order 1938", "halves")
    session = shop.runtime.sessions.get("halves")
    left = session.focused_branch
    forked = await shop.post("/branches/fork", data={"session_id": "halves"}, headers=PROXIED)
    assert forked.status_code == 200, forked.text
    right = forked.json()["branch_id"]
    assert right != left

    gate, read = asyncio.Event(), asyncio.Event()

    async def left_notes(session, calls, text):
        await dispatch("shopify_order_detail", {"order_id": A}, session=session, timeout_s=5, calls=calls)
        read.set()
        await gate.wait()
        await dispatch("shopify_order_note_append", {"order_id": A, "note": "Called about sizing"},
                       session=session, timeout_s=5, calls=calls)
        return "The note is ready on the card."

    async def right_reads(session, calls, text):
        await dispatch("shopify_find_order", {"query": "1940"}, session=session, timeout_s=5, calls=calls)
        return "Order 1940."

    shop.model.steps = [left_notes, right_reads]
    asking_left = asyncio.create_task(say(shop, "add a note to 1938: called about sizing", "halves", branch_id=left))
    await asyncio.wait_for(read.wait(), 5)
    await say(shop, "what about 1940?", "halves", branch_id=right)
    assert session.acting_branch == right, "the right half spoke last; the session's own field says so"
    gate.set()
    noted = await asyncio.wait_for(asking_left, 5)

    (card,) = [i["data"] for i in noted["ui"] if i["type"] == "confirmation"]
    proposal = shop.runtime.actions.find(card["proposal_id"])
    assert proposal.branch_id == left, f"the left half's change was filed against {proposal.branch_id}"

    # The right half's next instruction is not an instruction to the left half's card …
    shop.model.steps = [reads()]
    after = await say(shop, "and how are sales today?", "halves", branch_id=right)
    assert card["proposal_id"] not in after["revoked"]
    assert shop.runtime.actions.find(card["proposal_id"]).status.value == "PENDING"
    # … a yes to the right half is not a yes to it …
    asked = len(shop.model.prompts)
    await say(shop, "yes", "halves", branch_id=right)
    assert len(shop.model.prompts) == asked + 1, "a yes over here was answered from the card over there"
    # … and a yes to the left half is, and applies nothing.
    asked = len(shop.model.prompts)
    yes_left = await say(shop, "yes", "halves", branch_id=left)
    assert len(shop.model.prompts) == asked and "Nothing happens until you" in yes_left["answer"]
    assert shop.store.mutations == []


# --------------------------------------------- a name in what was heard, on the timeline (D1-01)


class Heard:
    """A recogniser that heard exactly this sentence."""

    def __init__(self, words: str) -> None:
        self.words = words

    async def from_blob(self, blob: bytes, filename_hint: str = ""):
        from app.speech.transcribe import SpeechResult

        return SpeechResult(ok=True, text=self.words, raw_text=self.words, engine="scribe_v2",
                            timings_ms={"transcribe": 420.0})


@pytest.fixture()
def recording(tmp_path):
    """A test session, running, as production's always-on one is (CROOKS_TEST_SESSION_ALWAYS)."""
    from pathlib import Path

    from app.observability import timeline
    from app.observability.session import TestSessions

    timeline.forget_names()
    store = TestSessions(Path(tmp_path) / "sessions")
    line = timeline.install(timeline.Timeline(store))
    session = line.start("a name heard before it was read")
    yield line, store, session
    line.stop()
    timeline.install(timeline.NullTimeline())
    timeline.forget_names()


# The events the turn itself writes. `tool_requested` is the dispatcher's: a search it runs
# BY a spoken name is written before any read has returned that name (see the report).
TURN_EVENTS = ("turn_started", "stt", "model", "turn_performance", "turn_finished", "unsupported_claim")


async def test_a_customer_named_aloud_is_redacted_from_what_the_turn_writes_even_before_a_read_names_her(shop, recording):
    """Closes D1-01. The words heard were written to the always-on timeline the moment they
    were heard, and the model's answer the moment it came back — both before the turn told
    the timeline which names its reads had returned. "What has Mia Kowalski ordered" put her
    name on disk twice, raw. The heard words now wait until the names are known, and keep the
    time they were heard; the answer is written after them."""
    line, store, session = recording
    shop.runtime.transcriber = Heard("What has Mia Kowalski ordered?")
    lookup = reads(("shopify_find_customer", {"query": "Kowalski"}),
                   ("shopify_customer_history", {"customer_id": found_customer}))

    async def answered(session_, calls, text):
        await lookup(session_, calls, text)
        return "Mia Kowalski has one order, #1940."

    shop.model.steps = [answered]
    response = await shop.post("/turn", data={"session_id": "heard"}, files={"audio": ("clip.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 64, "audio/webm")}, headers=PROXIED)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["question"] == "What has Mia Kowalski ordered?", "the owner still sees his own words"
    assert "Mia Kowalski" in shop.runtime.sessions.get("heard").pii_seen

    line.flush(2.0)
    events = [json.loads(x) for x in store.timeline_path(session).read_text(encoding="utf-8").splitlines() if x.strip()]
    mine = [e for e in events if e.get("kind") in TURN_EVENTS and e.get("session_id") == "heard"]
    kinds = [e["kind"] for e in mine]
    assert "stt" in kinds and "model" in kinds and "turn_finished" in kinds, kinds
    for event in mine:
        written = json.dumps(event)
        assert "Kowalski" not in written, f"{event['kind']} wrote the name raw: {written[:300]}"
    heard = next(e for e in mine if e["kind"] == "stt")
    assert "[name]" in heard["text"] and heard["audio_bytes"] > 0
    # Written late, it still reads in the order things happened: heard before it was answered.
    finished = next(e for e in mine if e["kind"] == "turn_finished")
    model = next(e for e in mine if e["kind"] == "model")
    assert heard["ts"] <= model["ts"] <= finished["ts"]


async def test_a_defect_report_naming_a_customer_only_this_turns_reads_find_is_written_redacted(shop, recording):
    """Closes the gap the round-11 records fixer left open on D1-01. A spoken defect was written
    to the always-on timeline before the model was asked — so a customer he named in it, whom
    only this turn's reads went on to find, was on disk raw: nothing had told the timeline her
    name yet. The feedback is still taken against the screen he was on before the model, and
    the model is still told it was logged, but the event is written once the reads' names are
    known, keeping the time he said it."""
    line, store, session = recording
    said = "log that the card for Mia Kowalski shows the wrong order"
    lookup = reads(("shopify_find_customer", {"query": "Kowalski"}),
                   ("shopify_customer_history", {"customer_id": found_customer}))
    shop.model.steps = [lookup]
    body = await say(shop, said, "fb-named")
    assert "Mia Kowalski" in shop.runtime.sessions.get("fb-named").pii_seen

    line.flush(2.0)
    events = [json.loads(x) for x in store.timeline_path(session).read_text(encoding="utf-8").splitlines() if x.strip()]
    recorded = [e for e in events if e.get("kind") == "owner_feedback" and e.get("session_id") == "fb-named"]
    assert len(recorded) == 1, [e.get("kind") for e in events]
    written = json.dumps(recorded[0])
    assert "Kowalski" not in written, f"the defect report wrote the name raw: {written[:300]}"
    assert "[name]" in recorded[0]["text"] and recorded[0]["shape"] == "log"
    assert recorded[0]["turn_id"] == body.get("turn_id")
    # Written late, it keeps the time he said it: before the model answered.
    model = next(e for e in events if e.get("kind") == "model" and e.get("session_id") == "fb-named")
    assert recorded[0]["ts"] <= model["ts"]


async def test_a_defect_report_is_written_even_when_the_model_fails(shop, recording):
    """The model failing is when a defect report matters most: the event is written in the
    route's `finally`, not after a successful answer."""
    line, store, session = recording

    async def broken(session_, calls, text):
        raise RuntimeError("the model fell over")

    shop.model.steps = [broken]
    try:
        await shop.post("/turn", json={"text": "log that the back button is broken", "session_id": "fb-broken"}, headers=PROXIED)
    except RuntimeError:
        pass   # however the route answers a model that raised, the report must already be written
    line.flush(2.0)
    events = [json.loads(x) for x in store.timeline_path(session).read_text(encoding="utf-8").splitlines() if x.strip()]
    assert [e.get("text") for e in events if e.get("kind") == "owner_feedback" and e.get("session_id") == "fb-broken"] == [
        "log that the back button is broken"]


# ------------------------------------ every write the model can reach, at the same boundary (D1-03)

# What the model can reach that moves money. The fast lane never wrote (its recipes were
# read-only by assertion, and its library said "Nothing here writes"), so these were always the
# model's alone, through app/providers/max_agent_sdk.py `_dispatch` → app/tools/dispatch.py
# `dispatch` → app/tools/gate.py `classify` → the tool's own prepare → app/actions/engine.py
# `stage`; none of those files changed when the lane went. These drive that path from /turn.
MONEY = [
    ("shopify_refund_create", {"order_id": B, "amount": "20.00"}),
    ("shopify_order_cancel", {"order_id": B}),
    ("shopify_store_credit_add", {"workspace_id": "ws_the_model_made_up"}),
]


@pytest.mark.parametrize(("tool", "args"), MONEY, ids=[t for t, _ in MONEY])
async def test_money_on_a_record_this_conversation_was_never_shown_is_refused_and_nothing_is_staged(shop, tool, args):
    """The model with #1938 open, reaching straight for #1940 (or for a credit workspace the Mac
    never opened): the gate refuses an id the conversation was not issued, before any handler,
    and nothing is staged, delivered or sent."""
    shop.model.steps = [show_order("1938"), reads((tool, args))]
    await say(shop, "show me order 1938", f"m-{tool}")
    body = await say(shop, "refund twenty pounds on 1940", f"m-{tool}")

    (call,) = [c for c in body["tool_calls"] if c["name"] == tool]
    assert call["ok"] is False and call["proposal_id"] is None, call
    assert not [i for i in body["ui"] if i["type"] == "confirmation"]
    assert shop.runtime.sessions.get(f"m-{tool}").proposals == []
    assert shop.store.mutations == []


@pytest.mark.parametrize(("tool", "args"), [("shopify_refund_create", {"amount": "20.00"}), ("shopify_order_cancel", {})],
                         ids=["refund", "cancel"])
async def test_money_the_model_prepares_is_a_card_naming_the_order_that_waits_for_the_hold(shop, tool, args):
    """Looked up first, the change is prepared — from a fresh read, on the order the model read
    — and it is a card: red, naming #1940, applied only by the owner's hold. A tap without the
    hold is refused, a spoken yes applies nothing, and the shop is never asked to change."""
    sid = f"hold-{tool}"
    shop.model.steps = [reads(("shopify_find_order", {"query": "1940"}), (tool, {"order_id": found_order, **args}))]
    body = await say(shop, "sort out 1940 for me", sid)
    assert all(c["ok"] for c in body["tool_calls"]), body["tool_calls"]

    (card,) = [i["data"] for i in body["ui"] if i["type"] == "confirmation"]
    proposal = shop.runtime.actions.find(card["proposal_id"])
    assert proposal.entity_ref == B and "1940" in proposal.entity_label
    assert card["risk"] == "red" and card["status"] == "pending"
    assert card["interaction"]["kind"] != "tap_commit", "money is never a plain tap"
    refused = await shop.post(f"/actions/{card['proposal_id']}/commit", data={"session_id": sid}, headers=PROXIED)
    assert refused.status_code in (403, 409), refused.text
    said_yes = await say(shop, "yes", sid)
    assert "Nothing happens until you" in said_yes["answer"]
    assert shop.runtime.actions.find(card["proposal_id"]).status.value == "PENDING"
    assert shop.store.mutations == []


async def test_a_change_staged_by_an_answer_the_owner_has_moved_on_from_is_withdrawn_unsent(shop):
    """The late answer of D2-01, carrying a change: it was staged into a conversation that had
    already moved on, so it is withdrawn, never delivered, and not drawn."""
    gate, read = asyncio.Event(), asyncio.Event()

    async def late_cancel(session, calls, text):
        await dispatch("shopify_find_order", {"query": "1938"}, session=session, timeout_s=5, calls=calls)
        read.set()
        await gate.wait()
        await dispatch("shopify_order_cancel", {"order_id": A}, session=session, timeout_s=5, calls=calls)
        return "The cancellation is ready."

    shop.model.steps = [late_cancel, show_order("1940")]
    older = asyncio.create_task(say(shop, "cancel 1938", "late-write"))
    await asyncio.wait_for(read.wait(), 5)
    await say(shop, "actually, show me 1940", "late-write")
    gate.set()
    late = await asyncio.wait_for(older, 5)

    session = shop.runtime.sessions.get("late-write")
    (proposal,) = session.proposals
    assert proposal.status.value == "REVOKED" and proposal.delivered_at is None
    assert late["ui"] == [] and late["writes"] is None
    assert shop.store.mutations == []


# ------------------------------- what the owner named, not what was open (D2-05, I-tests2 I-02)


def reads_the_number_said() -> Step:
    """Claude reading the order the owner's words name — whichever that is. Nothing in it is
    fixed to an order (round 9, I-tests2 I-03: a model that always read the same order could not
    show that the one ASKED for is what is read and drawn)."""
    import re

    async def step(session, calls, text):
        number = re.search(r"\b(\d{4})\b", text.split("\n")[1]).group(1)
        return await show_order(number)(session, calls, text)
    return step


@pytest.mark.parametrize(("open_number", "asked_number"), [("1938", "1940"), ("1940", "1938")])
async def test_a_number_that_is_not_the_open_order_is_drawn_from_what_was_read_for_it(shop, open_number, asked_number):
    """"What's the status of 1940" with #1938 open, and the other way round. The fast lane
    refused to answer that from the open order in code; the model is now told, beside the open
    record, that a number he says is the record he means — and the screen is drawn only from
    what the model read, so the card and the cursor are the asked-for order's, and nothing on
    the Mac read the open one for the sentence. The model reads whichever number was said, so
    the order drawn is the one requested, not one the script fixed (round 9, I-tests2 I-03)."""
    from app.routes.turn import NAMED_OUTRANKS_SHOWN

    refs = {"1938": A, "1940": B}
    sid = f"num-{asked_number}"
    shop.model.steps = [show_order(open_number), reads_the_number_said()]
    await say(shop, f"show me order {open_number}", sid)
    before = len(shop.store.queries)
    said = f"what's the status of {asked_number}"
    body = await say(shop, said, sid)

    prompt = shop.model.prompts[-1]
    assert prompt.split("\n")[1] == said
    assert NAMED_OUTRANKS_SHOWN in prompt
    assert ("order", refs[asked_number]) in records(body) and ("order", refs[open_number]) not in records(body)
    assert body["branch"]["entity"]["ref"] == refs[asked_number]
    assert body["answer"] == "Here it is.", "the model's answer about the order asked for is what he hears"
    turn_reads = json.dumps(shop.store.queries[before:])
    assert refs[open_number] not in turn_reads, "the Mac read the open order for a sentence about another"


async def test_a_question_the_model_answers_in_words_does_not_redraw_the_open_order(shop):
    """And when the model reads nothing, nothing is drawn from the record that was open: no
    card for #1938 under an answer about #1940, and the cursor does not move."""
    shop.model.steps = [show_order("1938"), reads()]
    await say(shop, "show me order 1938", "words")
    before = len(shop.store.queries)
    body = await say(shop, "where is 1940", "words")
    assert records(body) == [], body["ui"]
    assert len(shop.store.queries) == before
    assert body["branch"]["entity"]["ref"] == A


async def test_a_named_person_is_drawn_from_the_model_s_read_of_that_person_not_the_open_order_s_customer(shop):
    """"What has Mia ordered" with Daniel's order open: the customer on the screen is the one
    the model looked up, and neither Daniel nor his order is drawn under the answer."""
    shop.model.steps = [show_order("1938"),
                        reads(("shopify_find_customer", {"query": "Mia"}), ("shopify_customer_history", {"customer_id": found_customer}))]
    await say(shop, "show me order 1938", "named")
    body = await say(shop, "what has Mia ordered?", "named")
    shown = records(body)
    people = {ref for kind, ref in shown if kind in ("customer", "customer_workspace")}
    assert people == {MIA}, shown
    assert DANIEL not in json.dumps(shown) and ("order", A) not in shown
    assert body["branch"]["entity"]["ref"] == MIA


# ---------------------------------------- a control bound to one record (I-tests2 I-01, I-tests5 I-01)


async def _bound_to_1938(shop, sid: str) -> None:
    shop.model.steps.insert(0, show_order("1938"))
    shown = await say(shop, "show me order 1938", sid)
    entity = shown["branch"]["entity"]
    bound = await tap(shop, "voice.bind", sid, family="order.add_note", kind=entity["kind"], ref=entity["ref"])
    assert bound["ok"] is True and shop.runtime.sessions.get(sid).branch().voice_target()


async def test_a_question_about_another_order_after_a_tapped_note_stages_nothing_on_the_first(shop):
    """Add a note tapped on #1938, then "show me order 1940". Whether those words are the note
    is the model's to judge (the owner's decision of 28 September 2026 took the word list that
    used to decide it away); what the Mac guarantees is that the binding rides that one
    sentence and no further, that it is offered beside the words and never instead of them,
    and that a model which reads #1940 leaves #1938 with nothing staged against it."""
    await _bound_to_1938(shop, "other")
    shop.model.steps.append(show_order("1940"))
    body = await say(shop, "show me order 1940", "other")

    prompt = shop.model.prompts[-1]
    assert prompt.split("\n")[1] == "show me order 1940", "the words are the owner's, unchanged"
    assert "if they ask for something else, do that instead" in prompt
    session = shop.runtime.sessions.get("other")
    assert session.proposals == [] and not [i for i in body["ui"] if i["type"] == "confirmation"]
    assert ("order", B) in records(body) and body["branch"]["entity"]["ref"] == B
    # One sentence, one binding: the next sentence carries none.
    assert session.branch().voice_target() is None
    shop.model.steps.append(reads())
    await say(shop, "and what about its shipping?", "other")
    assert "Just before saying this he tapped" not in shop.model.prompts[-1]


async def test_a_navigation_command_after_a_tapped_note_cannot_become_a_change_by_itself(shop):
    """Add a note tapped on #1938, then "open the inbox". If the model nevertheless takes those
    words as the note, what exists is a card — naming #1938, carrying exactly those words, and
    applied only by the owner's gesture: a spoken yes does not apply it, the next thing he says
    withdraws it, and the shop is never asked to change. And the same words said to the OTHER
    half never pick the binding up at all."""
    await _bound_to_1938(shop, "nav")
    shop.model.steps.append(dictated_note("open the inbox"))
    body = await say(shop, "open the inbox", "nav")

    (card,) = [i["data"] for i in body["ui"] if i["type"] == "confirmation"]
    proposal = shop.runtime.actions.find(card["proposal_id"])
    assert proposal.entity_ref == A and card["summary"] == "open the inbox"
    assert card["status"] == "pending" and card["interaction"]["kind"] == "tap_commit"
    said_yes = await say(shop, "yes", "nav")
    assert "Nothing happens until you" in said_yes["answer"]
    shop.model.steps.append(reads())
    moved_on = await say(shop, "no, go to the inbox", "nav")
    assert moved_on["revoked"] == [card["proposal_id"]]
    assert shop.store.mutations == []

    # The other half: a binding armed on this half is not a binding over there.
    await _bound_to_1938(shop, "nav2")
    forked = await shop.post("/branches/fork", data={"session_id": "nav2"}, headers=PROXIED)
    other = forked.json()["branch_id"]
    shop.model.steps.append(reads())
    await say(shop, "open the inbox", "nav2", branch_id=other)
    assert "Just before saying this he tapped" not in shop.model.prompts[-1]
    assert shop.runtime.sessions.get("nav2").proposals == []
