"""The turn and the write boundary, followed from what the owner says to what the shop is sent.

Round 11 of the 2026-09-28 deploy review. Parts S2 and S2T — the turn route, the tap route, the
branch routes and the staging path under them, and their tests — were never reviewed in round
10, and the reviewers of the parts around them kept asking for exactly these files. Each test
names the finding it answers. They drive the real /turn, /command, /branches and /actions
routes, the real gate, dispatcher, action engine and presentation, against a fake shop that can
take one change — an order note — so that a tapped change is followed through its commit to the
mutation it sends. The only stand-in for Claude is a scripted model that makes real tool calls
through the real dispatcher; where the model's choice matters, the script says so and the
assertion is about what the Mac does with that choice, never about the script's own words.
"""

from __future__ import annotations

import asyncio
import re

import pytest

from app.actions.ledger import ActionLedger
from app.main import app
from app.session.manager import SessionManager
from app.tools import shopify_tools
from app.tools.dispatch import dispatch
from tests.test_context import inbox
from tests.test_turn_boundary import (
    DANIEL,
    MIA,
    OWNER,
    PROXIED,
    A,
    B,
    Scripted,
    Shop,
    _customer,
    dictated_note,
    found_customer,
    found_order,
    note_chip,
    reads,
    records,
    say,
    show_order,
    tap,
)

# A second Mia: "what has Mia ordered" names two people in this shop.
MIA_JONES = "gid://shopify/Customer/9"
THREAD = "18c2a0f1e9b7d3a4"


class Till(Shop):
    """The two orders and two customers of tests/test_turn_boundary.py, a second Mia, store
    credit, and one change the shop will actually take — setting an order's note — so a tapped
    note can be followed through its commit. Any other change still fails the test."""

    def __init__(self) -> None:
        super().__init__()
        self.customers[MIA_JONES] = _customer(MIA_JONES, "Mia Jones", "mia.jones@example.com", B, "1940")
        self.credit = {DANIEL: [], MIA: [{"currency": "GBP", "balance": 15.0}], MIA_JONES: []}
        # (id, reached, release): a read that asks the shop by that id waits for the test.
        self.hold: tuple[str, asyncio.Event, asyncio.Event] | None = None

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        variables = variables or {}
        if self.hold is not None and variables.get("id") == self.hold[0]:
            _, reached, release = self.hold
            reached.set()
            await release.wait()
        if "CrooksScopes" in query:
            self.queries.append((query, variables))
            scopes = ("read_orders", "write_orders", "read_customers", "write_customers",
                      "read_store_credit_accounts", "write_store_credit_account_transactions")
            return {"data": {"currentAppInstallation": {"accessScopes": [{"handle": h} for h in scopes]}}}
        if "CrooksStoreCredit" in query:
            self.queries.append((query, variables))
            person = self.customers.get(str(variables.get("id") or ""))
            if person is None:
                return {"data": {"customer": None}}
            accounts = [{"node": {"id": f"gid://shopify/StoreCreditAccount/{i + 1}",
                                  "balance": {"amount": f"{a['balance']:.2f}", "currencyCode": a["currency"]}}}
                        for i, a in enumerate(self.credit.get(person["id"], []))]
            return {"data": {"customer": {"id": person["id"], "displayName": person["displayName"],
                                          "defaultEmailAddress": person["defaultEmailAddress"],
                                          "storeCreditAccounts": {"edges": accounts}}}}
        return await super().graphql(query, variables)

    async def mutate(self, name: str, variables: dict) -> dict:
        if name != "order_note_set":
            return await super().mutate(name, variables)     # fails the test, as it should
        self.mutations.append((name, dict(variables)))
        node = self.orders[variables["id"]]
        node["note"] = variables["note"]
        return {"data": {"orderUpdate": {"order": {"id": node["id"], "name": node["name"], "note": node["note"]}, "userErrors": []}}}


@pytest.fixture()
async def desk(monkeypatch, tmp_path):
    import httpx

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
        store = Till()
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


# ------------------------------------------------------------------------------ helpers


def owner_words(prompt: str) -> str:
    """What the owner said, as the model is handed it: the line after the clock."""
    return prompt.split("\n")[1]


def the_number_said(text: str) -> str:
    """The order number in the owner's words — what Claude reads the request for."""
    return re.search(r"\b(\d{4})\b", owner_words(text)).group(1)


def reads_what_was_asked():
    """Claude doing what the words ask: find the order the owner said, and read it. Nothing in
    it is fixed to an order; which one it reads is whichever number he said."""
    async def step(session, calls, text):
        number = the_number_said(text)
        await show_order(number)(session, calls, text)
        return f"Order {number} is paid and not yet sent."
    return step


def notes_what_was_asked(note: str):
    """Claude taking "add a note to #N: …" as asked: the note goes on the order he said."""
    async def step(session, calls, text):
        number = the_number_said(text)
        await dispatch("shopify_find_order", {"query": number}, session=session, timeout_s=5, calls=calls)
        await dispatch("shopify_order_note_append", {"order_id": found_order(calls), "note": note},
                       session=session, timeout_s=5, calls=calls)
        return "The note is ready on the card."
    return step


def notes(order_ref: str, note: str, *, looked_up: str = ""):
    """Claude putting a note on this order, whatever was said — a model getting it wrong."""
    async def step(session, calls, text):
        if looked_up:
            await dispatch("shopify_find_order", {"query": looked_up}, session=session, timeout_s=5, calls=calls)
        await dispatch("shopify_order_note_append", {"order_id": order_ref, "note": note}, session=session, timeout_s=5, calls=calls)
        return "The note is ready on the card."
    return step


def refunds(number: str, amount: str = "20.00"):
    return reads(("shopify_find_order", {"query": number}), ("shopify_refund_create", {"order_id": found_order, "amount": amount}))


def confirmation(body: dict) -> dict:
    (card,) = [i["data"] for i in body["ui"] if i["type"] == "confirmation"]
    return card


def no_confirmation(body: dict) -> bool:
    return not [i for i in body["ui"] if i["type"] == "confirmation"]


async def commit(client, proposal_id: str, session_id: str):
    return await client.post(f"/actions/{proposal_id}/commit", data={"session_id": session_id}, headers=PROXIED)


async def fork(client, session_id: str) -> str:
    response = await client.post("/branches/fork", data={"session_id": session_id}, headers=PROXIED)
    assert response.status_code == 200, response.text
    return response.json()["branch_id"]


async def bind_note(client, session_id: str, **named) -> dict:
    """The tablet's Add a note: `voice.bind` with the half's entity (web/app.js primeAction),
    or with the record a tap named."""
    bound = await tap(client, "voice.bind", session_id, family="order.add_note", **named)
    return bound


# ============================== a tapped write acts on the record displayed (R9-D1-D1-02)


@pytest.mark.parametrize(("asked", "drawn"), [
    ("show me order 1940", "order"),
    ("show me the items and the shipping on order 1940", "order_workspace"),
])
async def test_a_note_tapped_after_order_b_replaced_order_a_lands_on_b_through_the_commit(desk, asked, drawn):
    """R9-D1-D1-02. #1938 is shown, then #1940 — as its own card, or as the workspace `present()`
    composes over it. The tablet's Add a note binds the half's cursor; the words are dictated;
    the card is tapped. The one mutation the shop receives is #1940's note, and #1938 is
    untouched. Followed to the commit, not only to the card."""
    desk.model.steps = [show_order("1938"), show_order("1940"), dictated_note("Gift wrap it")]
    await say(desk, "show me order 1938", "tapB")
    shown = await say(desk, asked, "tapB")
    assert [i["type"] for i in shown["ui"]][0] == drawn
    entity = shown["branch"]["entity"]
    assert entity["ref"] == B, f"the cursor stayed on {entity}"

    assert (await bind_note(desk, "tapB", kind=entity["kind"], ref=entity["ref"]))["ok"] is True
    noted = await say(desk, "gift wrap it", "tapB")
    card = confirmation(noted)
    applied = await commit(desk, card["proposal_id"], "tapB")

    assert applied.status_code == 200 and applied.json()["status"] == "verified", applied.text
    ((name, sent),) = desk.store.mutations
    assert name == "order_note_set" and sent["id"] == B and sent["note"].endswith("Gift wrap it")
    assert desk.store.orders[A]["note"] == "Leave with the neighbour", "#1938 was touched"


async def test_a_late_answer_about_a_does_not_take_the_tapped_note_back_to_a(desk):
    """R9-D1-D1-02 with R9-D2-D2-01. The #1938 answer finishes after the #1940 one replaced it.
    It publishes nothing, so the cursor is still #1940 when Add a note is tapped, and the note
    that is committed is #1940's."""
    gate, read = asyncio.Event(), asyncio.Event()

    async def slow_1938(session, calls, text):
        await show_order("1938")(session, calls, text)
        read.set()
        await gate.wait()
        return "Order 1938."

    desk.model.steps = [slow_1938, show_order("1940"), dictated_note("Fragile")]
    older = asyncio.create_task(say(desk, "show me order 1938", "late"))
    await asyncio.wait_for(read.wait(), 5)
    newer = await say(desk, "show me order 1940", "late")
    gate.set()
    late = await asyncio.wait_for(older, 5)
    assert late["ui"] == [] and newer["branch"]["entity"]["ref"] == B

    branch = desk.runtime.sessions.get("late").branch()
    assert branch.entity["ref"] == B, "the late answer put #1938 back under the owner's thumb"
    assert (await bind_note(desk, "late", kind="order", ref=branch.entity["ref"]))["ok"] is True
    card = confirmation(await say(desk, "fragile", "late"))
    assert (await commit(desk, card["proposal_id"], "late")).json()["status"] == "verified"
    assert [(n, v["id"]) for n, v in desk.store.mutations] == [("order_note_set", B)]


async def _glass(desk, sid: str, branch_id: str) -> dict:
    """What /state hands the tablet for this half's workspace — what the glass draws mid-turn."""
    state = await desk.get(f"/state/{sid}", params={"branch_id": branch_id}, headers=PROXIED)
    assert state.status_code == 200, state.text
    return state.json()["workspace"] or {}


async def test_a_read_that_lands_after_its_turn_was_replaced_puts_nothing_on_the_newer_turn_s_glass(desk):
    """R9-D2-D2-01, on the progressive glass. The #1938 read is out when the owner asks about
    #1940 instead; the #1940 turn begins its own workspace and is still answering when the #1938
    read comes back. What that read found went onto the NEWER workspace — #1938's card on the
    glass the tablet was polling for #1940. A read now lands only on the workspace it was issued
    into, while that is still the one on the half's glass; a replaced turn's read goes nowhere."""
    import json

    reached, release = asyncio.Event(), asyncio.Event()
    newer_ready, newer_gate = asyncio.Event(), asyncio.Event()

    async def newer(session, calls, text):
        await show_order("1940")(session, calls, text)
        newer_ready.set()
        await newer_gate.wait()
        return "Order 1940."

    desk.model.steps = [show_order("1938"), newer]
    # #1938's detail read asks the shop for its customer's orders last; that is where it waits.
    desk.store.hold = (DANIEL, reached, release)
    older = asyncio.create_task(say(desk, "show me order 1938", "landing"))
    await asyncio.wait_for(reached.wait(), 5)                   # #1938's own read is out
    asking = asyncio.create_task(say(desk, "show me order 1940", "landing"))
    await asyncio.wait_for(newer_ready.wait(), 5)               # the newer turn has read #1940
    desk.store.hold = None
    release.set()
    late = await asyncio.wait_for(older, 5)                     # #1938's read lands; its turn ends

    branch = desk.runtime.sessions.get("landing").branch()
    glass = await _glass(desk, "landing", branch.branch_id)
    assert glass.get("turn_id") and glass["turn_id"] != late["turn_id"], glass.get("turn_id")
    assert B in json.dumps(glass), "the newer turn's own read is on its glass"
    assert A not in json.dumps(glass), "the replaced turn's read was staged on the newer turn's glass"
    newer_gate.set()
    body = await asyncio.wait_for(asking, 5)
    assert ("order", B) in records(body) and ("order", A) not in records(body)


async def test_a_read_by_the_half_put_aside_is_not_staged_on_the_focused_half_s_glass(desk):
    """R9-D2-D2-03, on the progressive glass. The left half is focused and answering; the right
    half, asked something at the same time, reads #1940. The read's cards were staged on the
    FOCUSED half's workspace — the one the tablet polls — so #1940 appeared under the left half's
    question. They go on the right half's own workspace now."""
    import json

    desk.model.steps = [show_order("1938")]
    await say(desk, "show me order 1938", "aside")
    session = desk.runtime.sessions.get("aside")
    left = session.focused_branch
    right = await fork(desk, "aside")
    ready, gate = asyncio.Event(), asyncio.Event()
    desk.model.steps = [held(gate, ready, reads(), reads()), show_order("1940")]

    asking_left = asyncio.create_task(say(desk, "how are sales today?", "aside", branch_id=left))
    await asyncio.wait_for(ready.wait(), 5)
    right_body = await say(desk, "show me order 1940", "aside", branch_id=right)
    assert ("order", B) in records(right_body)

    assert B not in json.dumps(await _glass(desk, "aside", left)), "the right half's read is on the left half's glass"
    assert B in json.dumps(await _glass(desk, "aside", right))
    gate.set()
    await asyncio.wait_for(asking_left, 5)


async def test_two_orders_and_no_cursor_leave_nothing_to_bind_and_a_bind_naming_nothing_is_refused(desk):
    """R9-D1-D1-02: ambiguous multi-record selection is refused. Two orders drawn on a fresh
    half are a list: no cursor is chosen, no card keeps a listening chip, and a `voice.bind` the
    tablet posts without naming a record is refused as having nothing open — so nothing the
    owner says next can be bound to either order by the Mac's guess."""
    desk.model.steps = [reads(("shopify_find_order", {"query": "1938"}), ("shopify_order_detail", {"order_id": found_order}),
                              ("shopify_find_order", {"query": "1940"}), ("shopify_order_detail", {"order_id": found_order}))]
    both = await say(desk, "show me 1938 and 1940", "list")

    assert {("order", A), ("order", B)} <= set(records(both))
    assert both["branch"]["entity"] is None, both["branch"]["entity"]
    assert note_chip(both, A)["family"] == "" and note_chip(both, B)["family"] == ""
    refused = await bind_note(desk, "list")
    assert refused["ok"] is False and refused["code"] == "no_target", refused
    assert desk.runtime.sessions.get("list").branch().voice_target() is None
    assert desk.runtime.sessions.get("list").proposals == []


# ====================== money through the model path: a held card, the right target (R9-D1-D1-03)


def credits_mia(amount: float = 20.0):
    """Claude asked to give Mia store credit: find her, open the credit, prepare it."""
    async def step(session, calls, text):
        await dispatch("shopify_find_customer", {"query": "Kowalski"}, session=session, timeout_s=5, calls=calls)
        await dispatch("shopify_store_credit", {"customer_id": found_customer(calls), "amount": amount},
                       session=session, timeout_s=5, calls=calls)
        opened = calls[-1].result or {}
        await dispatch("shopify_store_credit_add", {"workspace_id": opened.get("workspace_id", "")},
                       session=session, timeout_s=5, calls=calls)
        return "The credit is on the card."
    return step


MONEY = {
    "refund": ("refund twenty pounds on order 1940", refunds("1940"), "shopify_refund_create", B),
    "cancel": ("cancel order 1940", reads(("shopify_find_order", {"query": "1940"}), ("shopify_order_cancel", {"order_id": found_order})),
               "shopify_order_cancel", B),
    "store credit": ("give Mia Kowalski twenty pounds of store credit", credits_mia(), "shopify_store_credit_add", MIA),
}


@pytest.mark.parametrize("kind", list(MONEY))
async def test_money_asked_for_out_loud_is_a_held_card_on_the_right_record_that_a_spoken_yes_cannot_apply(desk, kind):
    """R9-D1-D1-03 and R9-I-tests3-I-03 (refund was deferred in round 10). Every change that moves
    money reaches the shop by one path — the model's tool call, the gate, the tool's own prepare
    from a fresh read, the engine's stage — and the removed fast lane never wrote at all (its
    recipes were read-only by assertion), so no write lost a check when it went. Driven from a
    sentence: the change is a RED card on the record the model read, held to a gesture graver
    than a tap; a commit without that gesture is refused, a spoken yes applies nothing and is
    never sent to a model that could act on it, and the shop is not asked to change."""
    said, step, tool, target = MONEY[kind]
    sid = f"money-{kind.replace(' ', '-')}"
    desk.model.steps = [step]
    body = await say(desk, said, sid)
    assert all(c["ok"] for c in body["tool_calls"]), body["tool_calls"]

    card = confirmation(body)
    proposal = desk.runtime.actions.find(card["proposal_id"])
    assert proposal.tool_name == tool and proposal.entity_ref == target, (proposal.tool_name, proposal.entity_ref)
    assert card["risk"] == "red" and card["status"] == "pending"
    assert card["interaction"]["kind"] not in ("tap_commit", "", None), "money is never a plain tap"

    refused = await commit(desk, card["proposal_id"], sid)
    assert refused.status_code == 409 and refused.json()["code"] == "not_armed", refused.text
    asked = len(desk.model.prompts)
    yes = await say(desk, "yes", sid)
    assert len(desk.model.prompts) == asked, "a spoken yes reached the model"
    assert "Nothing happens until you" in yes["answer"] and yes["revoked"] == []
    assert desk.runtime.actions.find(card["proposal_id"]).status.value == "PENDING"
    assert desk.store.mutations == []


class Cli:
    """The `claude` subprocess, as far as `MaxAgentSDKProvider` can tell. It is asked the question
    the provider sends; for each tool call its turn makes, it does what the Agent SDK does — runs
    the provider's own PreToolUse hook, and unless that denies the call, the provider's own
    in-process MCP tool — on a task that carries none of the request's context, as the SDK's
    reader task does not; then it answers. Everything behind those two callbacks is the Mac's."""

    turns: list = []
    asked: list = []

    def __init__(self, options=None) -> None:
        from app.tools.registry import MCP_SERVER_NAME

        self.options = options
        self.tools = {t.name: t for t in options.mcp_servers[MCP_SERVER_NAME]["tools"]}
        self.hook = options.hooks["PreToolUse"][0].hooks[0]
        self.queries: list[str] = []

    async def connect(self) -> None: ...
    async def disconnect(self) -> None: ...
    async def interrupt(self) -> None: ...

    async def get_server_info(self) -> dict:
        return {"account": {"apiKeySource": "claude.ai", "apiProvider": "firstParty"}}

    async def query(self, text: str) -> None:
        self.queries.append(text)
        Cli.asked.append(text)

    async def call(self, name: str, args: dict) -> str:
        import contextvars

        from app.tools.registry import MCP_SERVER_NAME

        async def as_the_sdk_does() -> str:
            said = await self.hook({"tool_name": f"mcp__{MCP_SERVER_NAME}__{name}", "tool_input": args}, None, None)
            decided = said.get("hookSpecificOutput") or {}
            if decided.get("permissionDecision") == "deny":
                return f"DENIED: {decided.get('permissionDecisionReason')}"
            out = await self.tools[name].handler(args)
            return out["content"][0]["text"]
        return await asyncio.get_running_loop().create_task(as_the_sdk_does(), context=contextvars.Context())

    async def receive_response(self):
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

        answer = await Cli.turns.pop(0)(self, self.queries[-1])
        yield AssistantMessage(content=[TextBlock(text=answer)], model="fake")
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="cli")


@pytest.fixture()
async def sdk(desk, monkeypatch):
    """The desk, answered by the real provider: /turn → `turn_on_branch` → the SDK's callbacks →
    `_dispatch` → the dispatcher, the gate, the tool's prepare and the action engine."""
    import sys

    import claude_agent_sdk

    from app.providers.max_agent_sdk import MaxAgentSDKProvider

    real = claude_agent_sdk.create_sdk_mcp_server

    def keeping_the_tools(name, version="1.0.0", tools=None):
        return {**real(name=name, version=version, tools=tools), "tools": list(tools or [])}

    monkeypatch.setattr(claude_agent_sdk, "create_sdk_mcp_server", keeping_the_tools)
    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", Cli)
    Cli.turns, Cli.asked = [], []
    provider = MaxAgentSDKProvider(system_prompt="sys", cli_path=sys.executable, writes_enabled=True,
                                   session_lookup=desk.runtime.sessions.get_or_create)
    provider._started, provider._auth_mode = True, "cli"
    desk.runtime.provider = provider
    yield desk
    await provider.stop()


def _json(text: str) -> dict:
    """A read's result as the model reads it: JSON, after the line that frames any email text."""
    import json

    return json.loads(text[text.index("{"):])


async def _sdk_refund(cli, text):
    order = _json(await cli.call("shopify_find_order", {"query": "1940"}))["orders"][0]["order_id"]
    await cli.call("shopify_refund_create", {"order_id": order, "amount": "20.00"})
    return "The refund is on the card."


async def _sdk_cancel(cli, text):
    order = _json(await cli.call("shopify_find_order", {"query": "1940"}))["orders"][0]["order_id"]
    await cli.call("shopify_order_cancel", {"order_id": order})
    return "The cancellation is on the card."


async def _sdk_credit(cli, text):
    person = _json(await cli.call("shopify_find_customer", {"query": "Kowalski"}))["customers"][0]["customer_id"]
    opened = _json(await cli.call("shopify_store_credit", {"customer_id": person, "amount": 20.0}))
    await cli.call("shopify_store_credit_add", {"workspace_id": opened["workspace_id"]})
    return "The credit is on the card."


SDK_MONEY = {
    "refund": ("refund twenty pounds on order 1940", _sdk_refund, "shopify_refund_create", B,
               ("shopify_refund_create", {"order_id": B, "amount": "20.00"})),
    "cancel": ("cancel order 1940", _sdk_cancel, "shopify_order_cancel", B, ("shopify_order_cancel", {"order_id": B})),
    "store credit": ("give Mia Kowalski twenty pounds of store credit", _sdk_credit, "shopify_store_credit_add", MIA,
                     ("shopify_store_credit_add", {"workspace_id": "ws_the_model_made_up"})),
}


@pytest.mark.parametrize("kind", list(SDK_MONEY))
async def test_money_through_the_real_provider_is_held_on_the_right_record_and_a_stranger_record_is_denied_first(sdk, kind):
    """R9-D1-D1-03, end to end on the model's own path: /turn, `MaxAgentSDKProvider.turn_on_branch`,
    the SDK's PreToolUse hook and in-process tool (run as the SDK runs them, on a task that has
    none of the request's context), `_dispatch`, the dispatcher, the gate, the tool's prepare and
    the engine. A refund, a cancellation and a store credit the owner asks for are each a red card
    on the record the model read, filed against the half that asked, held to a gesture graver than
    a tap; a commit without it is refused, a spoken yes applies nothing and never reaches the
    model. The same change reached for on a record this conversation was never shown is denied by
    the hook before any handler runs, and nothing is staged. The fast lane this replaced never
    wrote, so none of this is weaker than what it had."""
    said, step, tool, target, stranger = SDK_MONEY[kind]
    sid = f"sdk-{kind.replace(' ', '-')}"
    Cli.turns = [step]
    body = await say(sdk, said, sid)
    assert all(c["ok"] for c in body["tool_calls"]), body["tool_calls"]

    card = confirmation(body)
    proposal = sdk.runtime.actions.find(card["proposal_id"])
    session = sdk.runtime.sessions.get(sid)
    assert (proposal.tool_name, proposal.entity_ref) == (tool, target)
    assert proposal.branch_id == session.focused_branch, "the change was not filed against the half that asked"
    assert card["risk"] == "red" and card["interaction"]["kind"] not in ("tap_commit", "", None)
    refused = await commit(sdk, card["proposal_id"], sid)
    assert refused.status_code == 409 and refused.json()["code"] == "not_armed", refused.text
    asked = len(Cli.asked)
    yes = await say(sdk, "yes", sid)
    assert len(Cli.asked) == asked, "a spoken yes reached the model"
    assert "Nothing happens until you" in yes["answer"]
    assert sdk.runtime.actions.find(card["proposal_id"]).status.value == "PENDING"

    # Another conversation, shown only #1938, reaching for the same change on a record it never saw.
    told: list[str] = []

    async def reach(cli, text):
        await cli.call("shopify_find_order", {"query": "1938"})
        told.append(await cli.call(*stranger))
        return "Done."

    Cli.turns = [reach]
    other = await say(sdk, said, f"{sid}-stranger")
    assert told and told[0].startswith("DENIED"), told
    assert no_confirmation(other) and sdk.runtime.sessions.get(f"{sid}-stranger").proposals == []
    assert sdk.store.mutations == []


# ============================== "yes, #1940" over a waiting refund on #1938 (R9-D2-D2-02)


@pytest.mark.parametrize("model_stages_on", ["the order he said", "the order that was waiting"])
async def test_yes_with_another_order_number_over_a_waiting_refund_is_an_instruction_about_that_order(desk, model_stages_on):
    """R9-D2-D2-02. A refund for #1938 is waiting. "Yes, #1940" is not a bare yes: the model is
    asked, with those words exactly, and the #1938 refund is withdrawn. A model that then
    prepares #1940's refund gives a card for #1940; one that prepares #1938's again — the digits
    lost, as the old `is_affirmation` lost them — gets nothing staged: a change to an order other
    than the one he named is withdrawn before it is shown, and he is told so."""
    sid = "yes-number" + ("-b" if model_stages_on == "the order he said" else "-a")
    desk.model.steps = [refunds("1938")]
    waiting = confirmation(await say(desk, "refund twenty pounds on 1938", sid))
    desk.model.steps = [refunds("1940") if model_stages_on == "the order he said" else refunds("1938")]
    asked = len(desk.model.prompts)

    body = await say(desk, "yes, #1940", sid)

    assert len(desk.model.prompts) == asked + 1 and owner_words(desk.model.prompts[-1]) == "yes, #1940"
    assert body["revoked"] == [waiting["proposal_id"]]
    assert desk.runtime.actions.find(waiting["proposal_id"]).status.value == "REVOKED"
    session = desk.runtime.sessions.get(sid)
    latest = session.proposals[-1]
    if model_stages_on == "the order he said":
        card = confirmation(body)
        assert card["proposal_id"] == latest.proposal_id and latest.entity_ref == B and latest.status.value == "PENDING"
    else:
        assert no_confirmation(body) and latest.entity_ref == A
        assert latest.status.value == "REVOKED" and latest.delivered_at is None
        assert body["answer"] == ("You said #1940, but the change I'd prepared was for #1938, so I've withdrawn it. "
                                  "Say which order you want it on.")
    assert desk.store.mutations == []


# =================== two halves staging at once, each against its own half (R9-D2-D2-03)


def held(gate: asyncio.Event, ready: asyncio.Event, before, after):
    """A model turn that does `before`, waits for the test, then does `after` — so the test can
    put another request in between the read and the stage."""
    async def step(session, calls, text):
        await before(session, calls, text)
        ready.set()
        await gate.wait()
        return await after(session, calls, text)
    return step


async def test_two_halves_staging_changes_at_once_each_file_theirs_against_their_own_half(desk):
    """R9-D2-D2-03. The right half is asked to note #1940 and the left to cancel #1938; both are
    thinking at once, and each stages while the session's shared `acting_branch` names the OTHER
    half (a sentence to the left, then a tap on the right, land in between). Each proposal is
    stamped with the half whose request staged it — CURRENT_BRANCH, held per request — and
    everything that reads the stamp agrees: each answer draws only its own card, a yes on each
    half is answered from its own card, and a new instruction to one half withdraws only its own."""
    desk.model.steps = [show_order("1938")]
    await say(desk, "show me order 1938", "two")
    session = desk.runtime.sessions.get("two")
    left = session.focused_branch
    right = await fork(desk, "two")

    r_gate, r_ready, l_gate, l_ready = asyncio.Event(), asyncio.Event(), asyncio.Event(), asyncio.Event()
    right_step = held(r_gate, r_ready, reads(("shopify_find_order", {"query": "1940"})), notes(B, "Call her back"))
    left_step = held(l_gate, l_ready, reads(("shopify_find_order", {"query": "1938"})),
                     reads(("shopify_order_cancel", {"order_id": A})))
    desk.model.steps = [right_step, left_step]

    asking_right = asyncio.create_task(say(desk, "note 1940: call her back", "two", branch_id=right))
    await asyncio.wait_for(r_ready.wait(), 5)
    asking_left = asyncio.create_task(say(desk, "cancel 1938", "two", branch_id=left))
    await asyncio.wait_for(l_ready.wait(), 5)
    assert session.acting_branch == left, "the left half spoke last"
    r_gate.set()
    right_body = await asyncio.wait_for(asking_right, 5)
    # A tap on the right half, landing while the left is still thinking: the shared field now
    # says right, and the left half stages under it.
    assert (await tap(desk, "surface.scroll", "two", branch_id=right, depth="40"))["ok"] is True
    assert session.acting_branch == right
    l_gate.set()
    left_body = await asyncio.wait_for(asking_left, 5)

    right_card, left_card = confirmation(right_body), confirmation(left_body)
    right_change = desk.runtime.actions.find(right_card["proposal_id"])
    left_change = desk.runtime.actions.find(left_card["proposal_id"])
    assert (right_change.branch_id, right_change.entity_ref) == (right, B), right_change.branch_id
    assert (left_change.branch_id, left_change.entity_ref) == (left, A), left_change.branch_id

    # A yes on each half is answered from that half's card, and sends nothing to the model.
    asked = len(desk.model.prompts)
    yes_right = await say(desk, "yes", "two", branch_id=right)
    yes_left = await say(desk, "yes", "two", branch_id=left)
    assert len(desk.model.prompts) == asked
    assert [i["data"]["proposal_id"] for i in yes_right["ui"] if i["type"] == "confirmation"] == [right_change.proposal_id]
    assert [i["data"]["proposal_id"] for i in yes_left["ui"] if i["type"] == "confirmation"] == [left_change.proposal_id]
    # A new instruction to the right half withdraws the right half's card and nothing else.
    desk.model.steps = [reads()]
    moved_on = await say(desk, "never mind", "two", branch_id=right)
    assert moved_on["revoked"] == [right_change.proposal_id]
    assert left_change.status.value == "PENDING"
    assert desk.store.mutations == []


async def test_the_same_change_asked_in_both_halves_is_two_proposals_each_filed_where_it_was_asked(desk):
    """R9-D2-D2-03, at the engine. The same note on #1938, asked in both halves while both are
    thinking, is the same fingerprint in the same conversation position. The engine used to hand
    the second half the FIRST half's proposal as "the same change already waiting": drawn on the
    right, stamped left, withdrawn by the left half's next question and never by the right's. Each
    half's request is now its own proposal, filed where it was asked (app/actions/engine.py
    `stage`)."""
    desk.model.steps = [show_order("1938")]
    await say(desk, "show me order 1938", "same")
    session = desk.runtime.sessions.get("same")
    left = session.focused_branch
    right = await fork(desk, "same")

    l_gate, l_ready, r_gate, r_ready = asyncio.Event(), asyncio.Event(), asyncio.Event(), asyncio.Event()
    nothing = reads()
    desk.model.steps = [held(l_gate, l_ready, nothing, notes(A, "Fragile")), held(r_gate, r_ready, nothing, notes(A, "Fragile"))]
    asking_left = asyncio.create_task(say(desk, "note 1938: fragile", "same", branch_id=left))
    await asyncio.wait_for(l_ready.wait(), 5)
    asking_right = asyncio.create_task(say(desk, "note 1938: fragile", "same", branch_id=right))
    await asyncio.wait_for(r_ready.wait(), 5)
    l_gate.set()
    left_body = await asyncio.wait_for(asking_left, 5)
    r_gate.set()
    right_body = await asyncio.wait_for(asking_right, 5)

    left_card, right_card = confirmation(left_body), confirmation(right_body)
    assert left_card["proposal_id"] != right_card["proposal_id"], "the right half was handed the left half's card"
    assert desk.runtime.actions.find(left_card["proposal_id"]).branch_id == left
    assert desk.runtime.actions.find(right_card["proposal_id"]).branch_id == right
    # Each half's next instruction withdraws its own, and only its own.
    desk.model.steps = [reads()]
    assert (await say(desk, "never mind", "same", branch_id=right))["revoked"] == [right_card["proposal_id"]]
    assert desk.runtime.actions.find(left_card["proposal_id"]).status.value == "PENDING"


async def test_a_change_staged_through_the_sdk_callback_belongs_to_its_conversation_s_half(desk):
    """R9-D2-D2-03, on the real provider's path. The Agent SDK calls a tool back on a task of its
    own, which carries nothing of the request — here, worse, a task whose context and whose
    session both name the other half. `MaxAgentSDKProvider._dispatch` sets CURRENT_BRANCH from
    the conversation the call belongs to, and the real dispatcher and engine stamp the change
    with that half."""
    from app.providers.max_agent_sdk import (
        MaxAgentSDKProvider,
        _Conversation,
        _Holder,
        conversation_key,
    )
    from app.tools import authority
    from app.tools.context import CURRENT_BRANCH

    desk.model.steps = [show_order("1938")]
    await say(desk, "show me order 1938", "sdk")
    session = desk.runtime.sessions.get("sdk")
    left = session.focused_branch
    right = await fork(desk, "sdk")
    session.acting_branch = right

    provider = MaxAgentSDKProvider(system_prompt="sys")
    holder = _Holder()
    conv = _Conversation(key=conversation_key("sdk", left), session_id="sdk", branch_id=left, client=object(), holder=holder)
    holder.conversation = conv
    conv.begin(session, authority=authority.for_owner(OWNER))
    token = CURRENT_BRANCH.set(right)
    try:
        told = await provider._dispatch("shopify_order_note_append", {"order_id": A, "note": "Fragile"}, holder=holder)
    finally:
        CURRENT_BRANCH.reset(token)
        conv.running = False

    assert told.startswith("PROPOSED"), told
    (proposal,) = session.proposals
    assert proposal.branch_id == left and proposal.entity_ref == A


class Mailbox:
    """Gmail, as far as archiving one thread needs it."""

    def thread_labels(self, thread_id: str) -> list[str]:
        return ["INBOX"]

    def thread_messages(self, thread_id: str) -> list[dict]:
        return [{"headers": {"from": "Mia Kowalski <mia@example.com>", "subject": "Where is it"}}]


async def test_a_row_archived_in_one_half_is_filed_there_whoever_spoke_last(desk, monkeypatch):
    """R9-D2-D2-03, the tap route that stages without a turn: Archive beside a row. It focused
    the row's half and staged — and the engine, finding no request half on the task, took the
    session's `acting_branch`, which named the half that last had a sentence. The left half's
    Archive was filed against the right half: the right half's next question withdrew it and
    the left half's did not. The row's half is now held on the request's own task."""
    from app.runtime import WriteStatus
    from app.tools import gmail_writes

    monkeypatch.setattr(gmail_writes, "_client", Mailbox())

    async def ready(operation=None):
        return WriteStatus("ready", "ready")

    monkeypatch.setattr(desk.runtime, "write_status", ready)
    desk.model.steps = [reads()]
    await say(desk, "anything in the inbox?", "rows")
    session = desk.runtime.sessions.get("rows")
    left = session.focused_branch
    right = await fork(desk, "rows")
    session.issue(THREAD)
    desk.model.steps = [reads()]
    await say(desk, "and sales today?", "rows", branch_id=right)
    assert session.acting_branch == right

    tapped = await desk.post("/actions/row", data={"session_id": "rows", "action": "email_archive", "ref": THREAD, "branch_id": left},
                             headers=PROXIED)
    assert tapped.status_code == 200 and tapped.json()["staged"] is True, tapped.text
    proposal = desk.runtime.actions.find(tapped.json()["proposal_id"])
    assert proposal.branch_id == left, f"the left half's Archive was filed against {proposal.branch_id}"

    desk.model.steps = [reads(), reads()]
    assert proposal.proposal_id not in (await say(desk, "what else?", "rows", branch_id=right))["revoked"]
    assert (await say(desk, "leave it", "rows", branch_id=left))["revoked"] == [proposal.proposal_id]


async def test_a_store_credit_opened_on_one_half_cannot_be_prepared_from_the_other(desk):
    """R9-D2-D2-03 and R9-D1-D1-03. A store credit is decided on the half it was opened on (its
    workspace is held by that half). The other half, asked to prepare it by id, is refused before
    anything is read or staged."""
    desk.model.steps = [reads()]
    await say(desk, "hello", "credit")
    session = desk.runtime.sessions.get("credit")
    right = await fork(desk, "credit")
    opened: dict = {}

    async def open_credit(session_, calls, text):
        await dispatch("shopify_find_customer", {"query": "Kowalski"}, session=session_, timeout_s=5, calls=calls)
        await dispatch("shopify_store_credit", {"customer_id": found_customer(calls), "amount": 20.0}, session=session_, timeout_s=5, calls=calls)
        opened.update(calls[-1].result or {})
        return "It's on the screen."

    async def prepare_there(session_, calls, text):
        await dispatch("shopify_store_credit_add", {"workspace_id": opened["workspace_id"]}, session=session_, timeout_s=5, calls=calls)
        return "Done."

    desk.model.steps = [open_credit, prepare_there]
    await say(desk, "store credit for Mia Kowalski, twenty pounds", "credit")
    body = await say(desk, "prepare it", "credit", branch_id=right)

    (call,) = [c for c in body["tool_calls"] if c["name"] == "shopify_store_credit_add"]
    assert call["ok"] is False and call["proposal_id"] is None
    assert session.proposals == [] and desk.store.mutations == []


# ======================= a mixed screen, then a write: nothing is inferred (R9-D2-D2-04)


async def _mixed_screen(desk, sid: str) -> dict:
    """#1938 open, then an answer that draws #1940 beside Mia's account."""
    desk.model.steps = [
        show_order("1938"),
        reads(("shopify_find_order", {"query": "1940"}), ("shopify_order_detail", {"order_id": found_order}),
              ("shopify_customer_history", {"customer_id": MIA})),
    ]
    await say(desk, "show me order 1938", sid)
    mixed = await say(desk, "order 1940 and her account", sid)
    assert {"order", "customer"} <= {kind for kind, _ in records(mixed)}
    assert mixed["branch"]["entity"]["ref"] == A, "the mixed screen chose a record for the owner"
    return mixed


async def test_after_an_order_beside_a_customer_the_note_chip_s_words_land_only_on_the_order_they_name(desk):
    """R9-D2-D2-04. #1938 is open; the answer then draws #1940 beside Mia's account. The Mac does
    not choose between them: the cursor stays #1938. #1940's Add a note binds nothing and primes
    words that name #1940; said, they stage #1940's note, and the commit sends #1940's."""
    mixed = await _mixed_screen(desk, "mixed")
    chip = note_chip(mixed, B)
    assert chip["family"] == "" and "1940" in chip["instruction"]
    desk.model.steps = [notes_what_was_asked("Call her back")]
    card = confirmation(await say(desk, "Add a note to #1940: call her back", "mixed"))
    assert desk.runtime.actions.find(card["proposal_id"]).entity_ref == B
    assert (await commit(desk, card["proposal_id"], "mixed")).json()["status"] == "verified"
    assert [(n, v["id"]) for n, v in desk.store.mutations] == [("order_note_set", B)]


async def test_after_an_order_beside_a_customer_a_tap_that_names_its_record_binds_that_record(desk):
    """R9-D2-D2-04: a uniquely identified tap. After the mixed screen, a `voice.bind` that names
    #1940 itself binds #1940 — not the cursor, which the mixed screen left on #1938 — and the note
    dictated next is staged and committed on #1940 alone."""
    await _mixed_screen(desk, "mixed-tap")
    assert (await bind_note(desk, "mixed-tap", kind="order", ref=B))["ok"] is True
    branch = desk.runtime.sessions.get("mixed-tap").branch()
    assert branch.voice_target()["ref"] == B and branch.entity["ref"] == A
    desk.model.steps = [dictated_note("Call her back")]
    card = confirmation(await say(desk, "call her back", "mixed-tap"))
    assert desk.runtime.actions.find(card["proposal_id"]).entity_ref == B
    assert (await commit(desk, card["proposal_id"], "mixed-tap")).json()["status"] == "verified"
    assert [(n, v["id"]) for n, v in desk.store.mutations] == [("order_note_set", B)]


async def test_a_tap_that_names_a_record_other_than_the_cursor_is_called_by_that_record_s_own_name(desk):
    """R9-D2-D2-04 and R9-D1-D1-02: what the screen and the model are told a tap bound. A tap that
    names #1940 while the cursor is #1938 bound #1940 — but took its NAME from the cursor, so the
    glass said "Adding a note to #1938" over a binding to #1940, and the model was handed "the order
    he is looking at (#1938), id …/1940". The name now comes from the record bound: the cursor's
    own when the tap bound the cursor, else the Mac's copy of the record named — never the cursor's
    and never a word the tablet sent."""
    await _mixed_screen(desk, "named-tap")
    bound = await bind_note(desk, "named-tap", kind="order", ref=B, label="#1938")
    listening = bound["changed"]["listening_for"]
    assert (listening["label"], listening["phrase"]) == ("#1940", "Adding a note to #1940"), listening
    assert desk.runtime.sessions.get("named-tap").branch().public()["listening_for"]["label"] == "#1940"

    desk.model.steps = [dictated_note("Call her back")]
    await say(desk, "call her back", "named-tap")
    told = desk.model.prompts[-1].split("[Just before saying this", 1)[1].split("]", 1)[0]
    assert "#1940" in told and B in told, told
    assert "1938" not in told, f"the model was told the cursor's name for another record: {told!r}"
    # And a tap that binds the cursor is still called by the cursor's name.
    desk.model.steps = [show_order("1938")]
    await say(desk, "show me order 1938", "named-tap")
    on_cursor = await bind_note(desk, "named-tap", kind="order", ref=A)
    assert on_cursor["changed"]["listening_for"]["phrase"] == "Adding a note to #1938"


async def test_a_tap_naming_a_record_this_conversation_was_never_shown_binds_nothing_and_says_nothing_of_it(desk):
    """R9-D1-D1-02: a tapped control binds only a record the conversation was shown. `voice.bind`
    took whatever id the tablet posted: it armed the next sentence for a record this conversation
    was never issued, and the listening phrase was built from the Mac's process-wide copy of it —
    "Asking about Mia", from a read another conversation made. It is refused now, as `open.entity`
    refuses the same id, before anything about the record is looked at."""
    desk.model.steps = [
        reads(("shopify_find_customer", {"query": "Kowalski"}), ("shopify_customer_history", {"customer_id": found_customer})),
        show_order("1938"),
    ]
    await say(desk, "what has Mia Kowalski ordered?", "reader")
    await say(desk, "show me order 1938", "stranger")
    branch = desk.runtime.sessions.get("stranger").branch()

    for family, kind, ref in (("customer.ask", "customer", MIA), ("order.add_note", "order", B)):
        refused = await bind_note(desk, "stranger", kind=kind, ref=ref) if family == "order.add_note" else \
            await tap(desk, "voice.bind", "stranger", family=family, kind=kind, ref=ref)
        assert refused["ok"] is False and refused["code"] == "not_held", refused
        assert "Mia" not in str(refused) and "Kowalski" not in str(refused)
        assert branch.voice_target() is None and branch.public().get("listening_for") is None
    # The record it WAS shown still binds.
    assert (await bind_note(desk, "stranger", kind="order", ref=A))["ok"] is True
    assert branch.voice_target()["ref"] == A


# ============== what the owner named, not what was open (R9-D2-D2-05, R9-I-tests2-I-02)
#
# The model reading the order that was ASKED for, in either direction, with the other one open, is
# tests/test_turn_boundary.py::test_a_number_that_is_not_the_open_order_is_drawn_from_what_was_read_for_it
# (R9-I-tests2-I-03). These are the cases around it.


async def test_an_answer_that_read_another_order_than_the_one_named_says_so_and_does_not_move_the_cursor(desk):
    """R9-D2-D2-05 and R9-I-tests2-I-02: the model gets it wrong. #1940 is open; the owner asks
    about #1938; the model reads #1940 again. The Mac cannot make the model read the right order,
    and it does not rewrite the model's sentence — but the answer ends by saying plainly which
    order that was, the card is that order's own (numbered #1940), and the cursor does not follow
    a read of an order he did not ask about."""
    desk.model.steps = [show_order("1938"), show_order("1940"), show_order("1940")]
    await say(desk, "show me order 1938", "wrong")
    await say(desk, "show me order 1940", "wrong")
    body = await say(desk, "what's the status of order 1938?", "wrong")

    assert body["answer"].endswith("That's #1940, not #1938.")
    assert [ref for kind, ref in records(body) if kind == "order"] == [B]
    assert body["branch"]["entity"]["ref"] == B
    # And a read of an order he did not name, on a half standing elsewhere, does not move it there.
    desk.model.steps = [show_order("1938"), show_order("1940")]
    await say(desk, "show me order 1938", "wrong2")
    moved = await say(desk, "what about #1941?", "wrong2")
    assert moved["answer"].endswith("That's #1940, not #1941.")
    assert moved["branch"]["entity"]["ref"] == A, "the cursor followed a read of an order he did not name"


async def test_a_named_person_with_another_customer_s_order_open_is_answered_from_that_person(desk):
    """R9-I-tests2-I-02. Daniel's order is open and the owner asks what Mia Kowalski has ordered.
    The words reach the model exactly; the customer drawn and the cursor are Mia's; neither Daniel
    nor his order is drawn under the answer; and the model's own answer is what he hears."""
    desk.model.steps = [
        show_order("1938"),
        reads(("shopify_find_customer", {"query": "Kowalski"}), ("shopify_customer_history", {"customer_id": found_customer})),
    ]
    await say(desk, "show me order 1938", "person")
    body = await say(desk, "what has Mia Kowalski ordered?", "person")
    shown = records(body)
    assert {ref for kind, ref in shown if kind in ("customer", "customer_workspace")} == {MIA}, shown
    assert DANIEL not in str(shown) and ("order", A) not in shown
    assert body["branch"]["entity"]["ref"] == MIA
    assert body["answer"] == "Here it is."


async def test_a_name_two_customers_share_moves_nothing_and_draws_neither_as_the_answer(desk):
    """R9-D2-D2-05: conflicting names. "Mia" is two people in this shop. A model that searches and
    then asks which one draws the search, and the Mac picks neither: no single customer is drawn
    as the answer, and the cursor stays on the order that was open."""
    desk.model.steps = [show_order("1938"), reads(("shopify_find_customer", {"query": "Mia"}))]
    await say(desk, "show me order 1938", "two-mias")
    body = await say(desk, "what has Mia ordered?", "two-mias")
    assert not [ref for kind, ref in records(body) if kind in ("customer", "customer_workspace")], records(body)
    assert body["branch"]["entity"]["ref"] == A


async def test_a_spoken_correction_withdraws_the_first_card_and_a_change_to_the_first_order_again_is_not_shown(desk):
    """R9-D2-D2-05: spoken corrections. A note is waiting on #1938; the owner says "no, order 1940".
    The waiting card is withdrawn as any new instruction withdraws it. A model that then notes
    #1940 gives #1940's card; one that notes #1938 again gets nothing shown — the change is
    withdrawn before it is delivered."""
    desk.model.steps = [notes_what_was_asked("Fragile")]
    first = confirmation(await say(desk, "add a note to 1938: fragile", "correct"))
    desk.model.steps = [notes(A, "Fragile", looked_up="1938")]
    wrong = await say(desk, "no, order 1940", "correct")
    assert wrong["revoked"] == [first["proposal_id"]] and no_confirmation(wrong)
    assert "withdrawn it" in wrong["answer"]
    desk.model.steps = [notes_what_was_asked("Fragile")]
    right = confirmation(await say(desk, "no — order 1940, I said", "correct"))
    assert desk.runtime.actions.find(right["proposal_id"]).entity_ref == B
    assert desk.store.mutations == []


async def test_a_spoken_period_correction_reaches_the_model_as_said_with_nothing_read_ahead_of_it(desk):
    """R9-D2-D2-05: periods. "Sales last week — no, this week" is not interpreted on the Mac: the
    model is handed exactly those words, nothing is read before it is asked, and nothing is drawn
    that it did not read."""
    desk.model.steps = [reads()]
    before = len(desk.store.queries)
    said = "sales last week, no sorry, this week"
    body = await say(desk, said, "period")
    assert owner_words(desk.model.prompts[-1]) == said
    assert desk.store.queries[before:] == [] or all("CrooksScopes" in q for q, _ in desk.store.queries[before:])
    assert records(body) == []


# ===================== a control bound to one order, then another named (R9-I-tests2-I-01)


async def _bound_to_1938(desk, sid: str) -> None:
    desk.model.steps.insert(0, show_order("1938"))
    shown = await say(desk, "show me order 1938", sid)
    entity = shown["branch"]["entity"]
    assert (await bind_note(desk, sid, kind=entity["kind"], ref=entity["ref"]))["ok"] is True


@pytest.mark.parametrize("said", ["add a note to order 1940: fragile", "#1940: fragile, handle with care"])
async def test_add_a_note_bound_to_1938_then_1940_named_stages_nothing_on_1938(desk, said):
    """R9-I-tests2-I-01. Add a note is tapped on #1938; the next sentence names #1940. The binding
    rides that sentence as a note beside the words — and a model that follows the binding anyway
    and notes #1938 gets nothing staged: the change is withdrawn before it is delivered and he is
    told which order it was for. The binding is spent, the next sentence carries none, and #1938
    is never sent a change."""
    sid = f"bound-{abs(hash(said)) % 1000}"
    await _bound_to_1938(desk, sid)
    desk.model.steps = [notes(A, "Fragile")]
    body = await say(desk, said, sid)

    assert "Just before saying this he tapped" in desk.model.prompts[-1] and A in desk.model.prompts[-1]
    session = desk.runtime.sessions.get(sid)
    (proposal,) = session.proposals
    assert proposal.entity_ref == A and proposal.status.value == "REVOKED" and proposal.delivered_at is None
    assert no_confirmation(body)
    assert body["answer"] == ("You'd tapped Add a note on #1938 and said #1940, so I haven't put it on either yet. "
                              "Say which order it's for."), body["answer"]
    assert session.branch().voice_target() is None
    desk.model.steps = [reads()]
    await say(desk, "and its shipping?", sid)
    assert "Just before saying this he tapped" not in desk.model.prompts[-1]
    assert desk.store.mutations == []


@pytest.mark.parametrize(("said", "note"), [
    ("exchange for order 1912, she wants a medium instead", "Exchange for order 1912, she wants a medium instead"),
    ("part of drop-007, send it with the others", "Part of drop-007, send it with the others"),
    ("replacement for #1936", "Replacement for #1936"),
])
async def test_a_note_that_mentions_another_order_is_asked_about_then_is_his_note(desk, said, note):
    """The round-11 independent check found Add a note tapped on #1938, then "exchange for order
    1912, she wants a medium instead" noted on #1938, withdrawn with "You said #1912, but the
    change I'd prepared was for #1938" — a correction he had not earned, and the note lost. Round
    13's independent checks found the other side: after the same tap, "no, put it on order 1940,
    fragile", copied onto #1938, stood as dictation. No rule over the words tells the two apart,
    so he is asked — neutrally, naming the order he tapped and the one he said — and "on this
    one" makes it #1938's note. The commit sends #1938's note and nothing else."""
    sid = f"content-{abs(hash(said)) % 1000}"
    await _bound_to_1938(desk, sid)
    desk.model.steps = [notes(A, note)]
    body = await say(desk, said, sid)
    assert no_confirmation(body) and body["answer"].startswith("You'd tapped Add a note on #1938 and said #"), body["answer"]
    assert "haven't put it on either" in body["answer"] and "withdrawn" not in body["answer"], body["answer"]
    desk.model.steps = [notes(A, note)]
    card = confirmation(await say(desk, "on this one", sid))
    assert (await commit(desk, card["proposal_id"], sid)).json()["status"] == "verified"
    assert [(n, v["id"]) for n, v in desk.store.mutations] == [("order_note_set", A)]


async def test_a_note_naming_where_it_goes_is_still_held_to_that_order_whatever_it_mentions(desk):
    """The other side of the same rule: he names #1940 as where the note goes and mentions #1912
    in it; a model that notes #1938 still gets nothing staged, and he is asked which order."""
    await _bound_to_1938(desk, "content-held")
    desk.model.steps = [notes(A, "Exchange for order 1912")]
    body = await say(desk, "add a note to order 1940: exchange for order 1912", "content-held")
    assert no_confirmation(body)
    assert body["answer"] == ("You'd tapped Add a note on #1938 and said #1912 and #1940, so I haven't put it on "
                              "either yet. Say which order it's for."), body["answer"]
    assert desk.store.mutations == []


async def test_add_a_note_bound_to_1938_then_a_note_for_1940_as_asked_lands_on_1940(desk):
    """R9-I-tests2-I-01, the other way: the model reads the words and notes #1940. That card is
    #1940's, and the commit sends #1940's note and nothing to #1938."""
    await _bound_to_1938(desk, "bound-right")
    desk.model.steps = [notes_what_was_asked("Fragile")]
    card = confirmation(await say(desk, "add a note to order 1940: fragile", "bound-right"))
    assert (await commit(desk, card["proposal_id"], "bound-right")).json()["status"] == "verified"
    assert [(n, v["id"]) for n, v in desk.store.mutations] == [("order_note_set", B)]


# ======================= "open the inbox" after Add a note was tapped (R9-I-tests5-I-01)


async def test_open_the_inbox_after_add_a_note_was_tapped_stages_no_note_when_the_model_navigates(desk):
    """R9-I-tests5-I-01. Whether "open the inbox" is the note is the model's to judge (the owner's
    decision of 28 September 2026 took away the word list that used to judge it); the prompt tells
    it plainly that words asking for something else are that. A model that opens the inbox stages
    nothing on #1938, spends the binding, and draws the inbox. (A model that takes the words as
    the note gets a card that only a gesture applies, which the next sentence withdraws —
    tests/test_turn_boundary.py::test_a_navigation_command_after_a_tapped_note_cannot_become_a_change_by_itself.)"""
    await _bound_to_1938(desk, "inbox")
    desk.model.steps = [reads(("gmail_search", {"query": "in:inbox"}))]
    body = await say(desk, "open the inbox", "inbox")

    prompt = desk.model.prompts[-1]
    assert owner_words(prompt) == "open the inbox" and "if they ask for something else, do that instead" in prompt
    session = desk.runtime.sessions.get("inbox")
    assert session.proposals == [] and no_confirmation(body)
    assert session.branch().voice_target() is None
    assert desk.store.mutations == []


# ================================ a mismatched record at the write boundary (R9-I-tests5-I-03)


async def test_a_change_to_an_order_other_than_the_one_named_is_refused_at_the_write_boundary(desk):
    """R9-I-tests5-I-03. The model-choice counterpart of the fixed-model walkthrough
    (tests/test_write_walkthrough.py, which is downstream-gate evidence only). Asked to note #1940,
    a model that notes #1938 — an order this conversation holds, so the gate lets the call through —
    has its change withdrawn before it is delivered, drawn nowhere, and never sent; asked to note
    #1938, the same model's change is the card it always was."""
    desk.model.steps = [show_order("1938"), notes(A, "Fragile", looked_up="1940")]
    await say(desk, "show me order 1938", "boundary")
    refused = await say(desk, "add a note to order 1940: fragile", "boundary")
    session = desk.runtime.sessions.get("boundary")
    (withdrawn,) = session.proposals
    assert withdrawn.status.value == "REVOKED" and withdrawn.reason == "not the order the owner named"
    assert withdrawn.delivered_at is None and withdrawn.entity_ref == A
    assert no_confirmation(refused) and refused["writes"] is None
    assert ("order", A) not in records(refused)

    desk.model.steps = [notes(A, "Fragile")]
    accepted = confirmation(await say(desk, "add a note to order 1938: fragile", "boundary"))
    assert desk.runtime.actions.find(accepted["proposal_id"]).entity_ref == A
    assert desk.store.mutations == []


# ============ cross-order tabs, and closed or ambiguous halves (R9-I-tests3-I-03)


async def test_a_tab_sentence_about_another_order_moves_no_tab_of_the_open_one(desk):
    """R9-I-tests3-I-03: the cross-order tab refusal. #1938 is open on its Items tab. "Show me the
    shipping on order 1940" moves nothing before the model is asked; a model that calls nothing
    leaves the tab and the cursor alone; a model that reads #1940 draws #1940 and moves the cursor
    there, and #1938 is still on Items."""
    desk.model.steps = [show_order("1938"), reads(), reads_what_was_asked()]
    await say(desk, "show me order 1938", "tabs")
    assert (await tap(desk, "surface.tab", "tabs", surface="order", tab="items"))["ok"] is True
    branch = desk.runtime.sessions.get("tabs").branch()
    assert branch.tab_for("order", A) == "items"

    silent = await say(desk, "show me the shipping on order 1940", "tabs")
    assert records(silent) == [] and branch.entity["ref"] == A and branch.tab_for("order", A) == "items"
    read = await say(desk, "show me the shipping on order 1940", "tabs")
    assert read["branch"]["entity"]["ref"] == B
    assert branch.tab_for("order", A) == "items" and branch.tab_for("order", B) != "items"


async def test_a_closed_half_cannot_be_focused_and_the_other_half_said_out_loud_moves_nothing(desk):
    """R9-I-tests3-I-03: closed-half and ambiguous navigation. The right half is merged away. A
    stale tap on its chip used to make it the focused half again — the next sentence was then
    answered on a half nobody could see, and anything it staged could never be applied. The
    focus is refused now, as showing it and moving its trail already were, and the next sentence
    lands on the half that is open. "The other half", said, is the model's and moves no focus."""
    desk.model.steps = [show_order("1938")]
    await say(desk, "show me order 1938", "closed")
    session = desk.runtime.sessions.get("closed")
    left = session.focused_branch
    right = await fork(desk, "closed")
    merged = await desk.post(f"/branches/{right}/merge", data={"session_id": "closed"}, headers=PROXIED)
    assert merged.status_code == 200, merged.text
    assert session.branches[right].status == "MERGED"

    refused = await desk.post(f"/branches/{right}/focus", data={"session_id": "closed"}, headers=PROXIED)
    assert refused.status_code == 409 and refused.json()["code"] == "branch_closed"
    assert session.focused_branch == left
    shown = await desk.post("/command", data={"session_id": "closed", "command": "branch.show", "branch_id": right}, headers=PROXIED)
    assert shown.json()["ok"] is False and shown.json()["code"] == "branch_closed"

    desk.model.steps = [reads(), reads()]
    body = await say(desk, "switch to the other half", "closed")
    assert body["branch"]["branch_id"] == left and session.focused_branch == left
    body = await say(desk, "the other half", "closed")
    assert session.focused_branch == left and body["branch"]["branch_id"] == left
