"""The acceptance flows, end to end through the real routes with fakes behind them: the
owner asks in words, a scripted Claude reaches for the read layer, the working sets, the
inbox and the batch tools, the tablet's gesture goes through /batches, and the test session's
report reads it all back — including what the assistant declined that it could have done.

  A  analytics: best sellers, by size, this week against last, average order value
  B  delayed orders → a working set → who has emailed → a draft to each of the rest → saved
  C  customers: the top spenders → a draft to each
  D  stock: what needs restocking, days of cover
  E  bulk tag: tag all of the delayed orders → one hold → counted
  +  a false unsupported claim, a rejected query dimension, a bulk ask with no batch
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.actions.ledger import NullLedger
from app.clients.shopify import REVIEWED_MUTATIONS, ShopifyError
from app.main import app
from app.observability.claims import registered as registered_now
from app.observability.proposals import candidates
from app.observability.report import build_report, reconstruct
from app.observability.session import TestSessions
from app.observability.timeline import Timeline, install, read_events
from app.providers.base import TurnResult
from app.session.manager import SessionManager
from app.tools import (  # noqa: F401 — the registrations
    analytics_tools,
    batch_tools,
    gmail_writes,
    shopify_tools,
)
from app.tools.dispatch import dispatch
from tests.test_actions_routes import PROXIED, FakeProvider, configure
from tests.test_analytics_tools import ORDER_NODES, Store, london_now
from tests.test_gmail_writes import FakeGmail, Policy


class FlowStore(Store):
    """The analytics fake, plus what a batch of tags and a draft need: the tag read and the
    tag mutations by id, the order read the hydrator makes, and the scope check."""

    def __init__(self) -> None:
        super().__init__(ORDER_NODES)
        self.mutations: list[tuple[str, dict]] = []
        self.refuse: set[str] = set()

    def _by_id(self, oid: str) -> dict | None:
        return next((n for n in self.nodes if n["id"] == oid), None)

    async def graphql(self, query, variables=None):
        v = variables or {}
        if "CrooksScopes" in query:
            return {"data": {"currentAppInstallation": {"accessScopes": [{"handle": "read_orders"}, {"handle": "write_orders"}]}}}
        if "CrooksOrderTags" in query:
            n = self._by_id(str(v.get("id")))
            return {"data": {"order": {"id": n["id"], "name": n["name"], "tags": list(n["tags"])} if n else None}}
        if "CrooksOrderContext" in query or "CrooksOrderByName" in query:
            n = self._by_id(str(v.get("id") or ""))
            if n is None:
                return {"data": {"order": None, "orders": {"edges": []}}}
            node = {**n, "processedAt": n["createdAt"], "note": "", "email": n["customer"]["defaultEmailAddress"]["emailAddress"], "shippingAddress": {"city": "London", "country": "United Kingdom"}}
            return {"data": {"order": node}}
        if "CrooksCustomerOrders" in query:
            return {"data": {"customer": None}}
        return await super().graphql(query, variables)

    async def mutate(self, name: str, variables: dict) -> dict:
        assert set(variables) == set(REVIEWED_MUTATIONS[name].variables)
        self.mutations.append((name, dict(variables)))
        n = self._by_id(variables["id"])
        if variables["id"] in self.refuse:
            raise ShopifyError("Shopify refused it.")
        if name == "order_tags_add":
            for t in variables["tags"]:
                if t.lower() not in {x.lower() for x in n["tags"]}:
                    n["tags"].append(t)
            return {"data": {"tagsAdd": {"node": {"id": n["id"]}, "userErrors": []}}}
        raise AssertionError(name)


class Inbox:
    """The Gmail read side for email_query: two of the delayed customers have written."""

    def __init__(self) -> None:
        self.threads = {
            "flo@example.com": [{"thread_id": "18f0000000000002", "from_email": "flo@example.com", "subject": "Order 1007", "date": "Sun, 6 Sep 2026 10:00:00 +0100", "snippet": "any news", "likely_bulk": False, "authenticated": True}],
        }
        self.calls: list[dict] = []

    async def threads_for(self, **kwargs):
        self.calls.append(kwargs)
        return {"available": True, "threads": list(self.threads.get(kwargs.get("sender", ""), []))}

    async def replied(self, thread_id):
        return False


async def customer_of(order_id: str = "", customer_id: str = "") -> dict:
    n = next((x for x in ORDER_NODES if x["id"] == order_id or x["customer"]["id"] == customer_id), None)
    assert n is not None, (order_id, customer_id)
    return {"name": n["customer"]["displayName"], "email": n["customer"]["defaultEmailAddress"]["emailAddress"], "label": n["name"] if order_id else ""}


class ScriptedClaude(FakeProvider):
    """What Claude calls and says, from the words it is asked. It remembers the ids the Mac
    handed it (a set id, a derived set id) the way the real one would from the results."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.sets: dict[str, str] = {}

    async def turn(self, session_id: str, text: str) -> TurnResult:
        session = self.runtime.sessions.get_or_create(session_id)
        session.turns += 1
        calls: list = []
        lines = text.split("\n")
        words = (lines[1] if len(lines) > 1 and lines[0].startswith("[Now:") else lines[0]).lower()

        async def call(name, args):
            out = await dispatch(name, args, session=session, timeout_s=10, calls=calls)
            result = calls[-1].result if calls and isinstance(calls[-1].result, dict) else {}
            for key in ("set", "set_not_contacted", "set_contacted", "set_threads"):
                if isinstance(result.get(key), dict) and result[key].get("set_id"):
                    self.sets[key] = result[key]["set_id"]
            return out

        if "best sellers" in words:
            await call("commerce_aggregate", {"period": "this_month", "group_by": ["product"], "metrics": ["units", "revenue"], "view": "ranking"})
            answer = "This month the joggers lead on units and the jeans on revenue."
        elif words.startswith("by size"):
            await call("commerce_aggregate", {"period": "this_month", "entity": "variants", "group_by": ["size"], "metrics": ["units"]})
            answer = "Medium sells most, then large."
        elif "compare" in words or "against last" in words:
            await call("commerce_aggregate", {"period": "this_week", "metrics": ["orders", "revenue", "aov"], "compare": True, "view": "comparison"})
            answer = "This week is behind last week on orders and revenue."
        elif "average order" in words:
            await call("commerce_aggregate", {"period": "last_30_days", "metrics": ["orders", "revenue", "aov"], "view": "metrics"})
            answer = "The average order over the last thirty days is about ninety pounds."
        elif "spent over" in words:
            answer = "I can't pick customers out by what they have spent from here."   # the false claim
        elif "by material" in words:
            await call("commerce_aggregate", {"period": "this_month", "group_by": ["material"], "metrics": ["units"]})
            answer = "The Mac can't group sales by material; it can do product, size and colour."
        elif "older than" in words:
            await call("commerce_query", {"entity": "orders", "period": "last_90_days", "filters": {"fulfillment": "unfulfilled", "older_than_days": 5}, "title": "Delayed orders"})
            answer = "Two orders are older than five days and still to ship: 1007 and 1009."
        elif "emailed us" in words:
            await call("email_query", {"set_id": self.sets["set"], "days": 30})
            answer = "One of the two has emailed: Flo about order 1007. Gus has not."
        elif "draft" in words and "haven't" in words:
            await call("batch_email_drafts", {"set_id": self.sets["set_not_contacted"], "subject": "Your order {order_number}", "body": "Hi {first_name},\n\nOrder {order_number} has been with us {order_age_days} days and ships this week. Sorry for the wait."})
            answer = "One draft is ready on the card, for Gus; tapping the card saves it."
        elif "refund all" in words:
            answer = "I can't refund them all at once from here; I can prepare them one at a time."
        elif "top customers" in words:
            await call("commerce_aggregate", {"entity": "customers", "period": "last_90_days", "metrics": ["lifetime_spent", "lifetime_orders"], "limit": 3, "title": "Top customers"})
            answer = "Cy Cole, then Ann Able, then Ben Bold."
        elif "thank" in words:
            await call("batch_email_drafts", {"set_id": self.sets["set"], "subject": "Thank you", "body": "Hi {first_name},\n\nThank you for shopping with us this season."})
            answer = "Three drafts are ready on one card; tapping it saves them."
        elif "restock" in words:
            await call("inventory_query", {"period": "last_30_days", "limit": 5})
            answer = "The black joggers in a large are the first to run out."
        elif "days of cover" in words:
            await call("inventory_query", {"period": "last_30_days", "product": "joggers", "limit": 5})
            answer = "About four days on the black large joggers."
        elif "tag all" in words:
            await call("batch_order_tags_add", {"set_id": self.sets["set"], "tags": ["delayed-sept"]})
            answer = "Both delayed orders are ready to tag on one card; hold the card, then tap."
        elif words.startswith("just this week"):
            await call("commerce_aggregate", {"period": "this_week", "group_by": ["product"], "metrics": ["units", "revenue"], "view": "ranking"})
            answer = "This week the joggers still lead."
        else:
            answer = "I'm not sure what you mean."
        return TurnResult(text=answer, tool_calls=calls, session_id=session_id)


@pytest.fixture()
async def client(monkeypatch, tmp_path):
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
    london_now(monkeypatch)
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        # The owner's server: the test session is started from the server itself (F-05A).
        configure(runtime_client := type("C", (), {"runtime": runtime})(), local=True)
        store = FlowStore()
        box = FakeGmail()
        inbox = Inbox()
        runtime.shopify = store
        runtime.gmail = box
        shopify_tools.bind(store)
        gmail_writes.bind(box, customer=customer_of, policy=lambda: Policy())
        analytics_tools.bind_email(inbox.threads_for, inbox.replied)
        runtime.provider = ScriptedClaude(runtime)
        runtime.actions.ledger = NullLedger()
        runtime.batches.ledger = NullLedger()
        runtime.sessions = SessionManager()
        runtime.tests = TestSessions(tmp_path / "logs")
        runtime.timeline = install(Timeline(runtime.tests))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.runtime = runtime
            c.store = store
            c.box = box
            c.inbox = inbox
            c.tmp = tmp_path
            yield c
        runtime.timeline.stop()
        analytics_tools.bind_email(None, None)
        gmail_writes.bind(None)
        del runtime_client


async def ask(client, text: str, session_id: str = "tab") -> dict:
    response = await client.post("/turn", json={"text": text, "session_id": session_id}, headers=PROXIED)
    assert response.status_code == 200, response.text
    return response.json()


def types(data: dict) -> list[str]:
    return [i["type"] for i in data["ui"]]


async def test_the_flows_run_end_to_end_and_the_report_reads_them_back(client):
    started = (await client.post("/test-session/start", json={"name": "flows"})).json()
    assert started["started"]
    ids: dict[str, str] = {}

    # ---- A. analytics
    data = await ask(client, "what were our best sellers this month")
    ids["best"] = data["turn_id"]
    assert types(data) == ["ranking"], "a product ranking is a ranking; the sets come from listings and customer rankings"
    data = await ask(client, "by size")
    assert "ranking" in types(data) or "table" in types(data)
    data = await ask(client, "how does this week compare against last week")
    assert "comparison" in types(data)
    data = await ask(client, "what's the average order value")
    assert "metric_group" in types(data)
    ids["aov"] = data["turn_id"]

    # ---- the false claim, the unknown dimension, the bulk ask with no batch
    data = await ask(client, "which customers have spent over two hundred pounds")
    ids["false"] = data["turn_id"]
    data = await ask(client, "split this month by material")
    ids["material"] = data["turn_id"]
    assert "error" in types(data) or not data["tool_calls"][0]["ok"]

    # ---- B. delayed orders → set → who has emailed → drafts for the rest
    data = await ask(client, "which orders are older than five days and still to ship")
    ids["delayed"] = data["turn_id"]
    assert "order_list" in types(data) and "working_set" in types(data)
    delayed = next(i["data"] for i in data["ui"] if i["type"] == "working_set")
    assert delayed["count"] == 2 and delayed["kind"] == "orders"
    data = await ask(client, "which of them have emailed us")
    ids["emailed"] = data["turn_id"]
    assert types(data)[:2] == ["metric_group", "table"] and sum(1 for t in types(data) if t == "working_set") == 1, "one set card for the correlation, not one per derived set"
    assert client.inbox.calls, "the inbox was read per customer"
    data = await ask(client, "draft an email to each of the ones who haven't")
    ids["drafts"] = data["turn_id"]
    card = next(i["data"] for i in data["ui"] if i["type"] == "batch_action")
    assert card["eligible"] == 1 and card["requested"] == 1 and card["preview"]["subject"] == "Your order 1009" and card["preview"]["body"].startswith("Hi Gus,")
    assert card["interaction"]["kind"] == "tap_commit" and card["commit"] == {"allowed": True}
    assert client.box.drafts == {}
    done = await client.post(f"/batches/{card['batch_id']}/commit", data={"session_id": "tab"}, headers=PROXIED)
    assert done.status_code == 200 and done.json()["status"] == "done" and done.json()["counts"]["verified"] == 1, done.text
    assert done.json()["ui"][0]["type"] == "batch_result" and done.json()["all_verified"] is True
    assert len(client.box.drafts) == 1 and "Hi Gus," in next(iter(client.box.drafts.values()))["parsed"]["body"]
    data = await ask(client, "refund all of them")
    ids["refund_all"] = data["turn_id"]

    # ---- C. customers
    data = await ask(client, "who are our top customers")
    ids["customers"] = data["turn_id"]
    assert "ranking" in types(data) and next(i["data"] for i in data["ui"] if i["type"] == "working_set")["kind"] == "customers"
    data = await ask(client, "send each of them a thank you draft")
    ids["thanks"] = data["turn_id"]
    card = next(i["data"] for i in data["ui"] if i["type"] == "batch_action")
    assert card["eligible"] == 3 and card["title"] == "Save 3 drafts"
    done = await client.post(f"/batches/{card['batch_id']}/commit", data={"session_id": "tab"}, headers=PROXIED)
    assert done.json()["counts"]["verified"] == 3 and len(client.box.drafts) == 4

    # ---- D. stock
    data = await ask(client, "what needs restocking")
    ids["restock"] = data["turn_id"]
    assert "ranking" in types(data)
    data = await ask(client, "how many days of cover on the joggers")
    assert "ranking" in types(data)

    # ---- E. bulk tag (a fresh set, then one gesture for both)
    data = await ask(client, "which orders are older than five days and still to ship")
    data = await ask(client, "tag all of those delayed-sept")
    ids["tag"] = data["turn_id"]
    card = next(i["data"] for i in data["ui"] if i["type"] == "batch_action")
    assert card["eligible"] == 2 and card["members"] == ["CROOKS-1007", "CROOKS-1009"] and card["interaction"]["kind"] == "tap_commit"
    done = await client.post(f"/batches/{card['batch_id']}/commit", data={"session_id": "tab"}, headers=PROXIED)
    body = done.json()
    assert body["status"] == "done" and body["counts"] == {"requested": 2, "eligible": 2, "excluded": 0, "verified": 2, "unverified": 0, "stale": 0, "failed": 0, "not_attempted": 0}
    assert body["spoken"] == "Tagged 2 of the 2 orders." and body["undo"]["batch_id"]
    assert sorted(v["id"] for _, v in client.store.mutations) == ["gid://shopify/Order/1007", "gid://shopify/Order/1009"]
    # a follow-up shape, three times, for the report
    for _ in range(3):
        data = await ask(client, "just this week")
    ids["follow"] = data["turn_id"]

    stopped = (await client.post("/test-session/stop")).json()
    assert stopped["stopped"]
    client.runtime.timeline.flush()
    path = Path(stopped["path"])
    events = read_events(path)
    kinds = {e.get("kind") for e in events}
    assert {"working_set", "cross_source", "unsupported_claim", "query_rejected", "batch_proposed", "batch_done", "batch_commit"} <= kinds, sorted(kinds)

    # ---- the report reads it back
    rec = reconstruct(events)
    turn = rec.turn(ids["false"])
    assert turn is not None and turn.classes == ["FALSE_UNSUPPORTED"] and turn.outcome == "failed"
    honest = rec.turn(ids["refund_all"])
    assert honest is not None and "FALSE_UNSUPPORTED" not in honest.classes, "a bulk refund is not something the Mac composes"
    _, markdown = build_report(path, tools_registered=sorted(registered_now()))
    assert "## 13. Intelligence" in markdown
    section = markdown.split("## 13. Intelligence", 1)[1]
    assert ids["false"] in section.split("### Composable but failed", 1)[0], "the false claim cites its turn"
    assert "material" in section.split("### Potential new query dimensions", 1)[1].split("### Potential new actions", 1)[0]
    assert ids["material"] in section
    bulk = section.split("### Bulk workflows requested", 1)[1].split("### Repeated follow-up", 1)[0]
    assert "| refund | 1 |" in bulk and ids["refund_all"] in bulk and "| tags | 1 |" in bulk and "| yes |" in bulk and "| drafts |" in bulk
    follow = section.split("### Repeated follow-up patterns", 1)[1].split("### Potential UI", 1)[0]
    assert "| period | 3 |" in follow and ids["follow"] in follow
    assert "commerce_query → email_query" in section or "Working sets:" in section
    assert "Batches run: 3" in section
    # the candidates cite the same turns and apply nothing
    cands = candidates(rec, registered=sorted(registered_now()))
    kinds_of = {c["kind"] for c in cands}
    assert {"FALSE_UNSUPPORTED", "QUERY_DIMENSION", "NEW_BULK_ACTION", "FOLLOW_UP_SHORTCUT"} <= kinds_of, kinds_of
    false_cand = next(c for c in cands if c["kind"] == "FALSE_UNSUPPORTED")
    assert false_cand["evidence"] == [ids["false"]] and "commerce_aggregate" in false_cand["change"]
    from app.observability.proposals import write_proposals

    written = write_proposals(path, client.tmp / "reports", registered=sorted(registered_now()))
    text = written.read_text()
    assert "IMPROVEMENT CANDIDATES" in text and "PROPOSED — not applied" in text and ids["false"] in text
    assert "gus@example.com" not in text and "Gus Gee" not in text, "no customer detail in a proposal"
