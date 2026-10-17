"""George's three ready labels (shipping_label_buy, shipping_label_print), through the real /actions routes.

He asked why buying and printing three labels was slow, why he couldn't print right after buying, and
why the #2202 label broke:

- each buy tap took nine to eleven seconds to answer with nothing shown while it worked: the tap is now
  answered at once, in flight, before CLIVE Shipping has answered, and the tablet asks how it stands;
- the #2202 buy was "unverified" and was retried blind: the card says the specific reason, whole, and
  the next buy card for the same label says it first;
- a label proven bought offers its print on the same screen, staged for his own gesture, without a
  separate request;
- nothing else about shipping changes: a print is answered as it always was, and nothing is printed or
  bought by any of this without its own gesture.

Every call to CLIVE Shipping goes to a stand-in through an httpx MockTransport; the keys are fakes.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from app.actions.ledger import NullLedger
from app.clients import crooks_shipping as sc
from app.main import app
from app.secrets import keychain
from app.session.manager import SessionManager
from app.tools import shipping_tools, shopify_tools
from app.tools.dispatch import dispatch
from tests.fake_credentials import bearer_token
from tests.test_actions import FakeStore
from tests.test_actions_routes import FakeProvider

pytestmark = pytest.mark.usefixtures("owner_asking")

OWNER = "owner@example.com"
PROXIED = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.9"}
READ = bearer_token("shipping-feedback-read", length=32)
WRITE = bearer_token("shipping-feedback-write", length=32)
SID = "shp_2202abcdef01"
LABEL = {"provider": "Parcel2Go", "service": "Parcelforce", "tracking_number": "QF2202GB"}
WEB = Path(__file__).resolve().parent.parent / "web"


def shipment(**over):
    row = {"id": SID, "order": "CROOKS-2202", "order_id": "gid://shopify/Order/2202", "country": "GG", "stage": "ready",
           "status": "Ready", "reasons": [], "payment": "Paid", "service": "Parcel2Go · Parcelforce", "price": "£11.79",
           "tracking_number": None, "print": None, "carrier": None, "updated_at": "2026-10-16T09:00:00+00:00",
           "label": None, "print_status": None, "can_buy": True}
    return row | over


class Service:
    """CLIVE Shipping, standing in: the order, its preview, a buy that can be held at the door, a print."""

    def __init__(self, *, buy_answer: dict | None = None, bought: bool = True):
        self.state = "ready"
        self.seen: list[httpx.Request] = []
        self.buy_arrived, self.buy_release = asyncio.Event(), asyncio.Event()
        self.buy_release.set()
        self.buy_answer = buy_answer
        self.bought = bought

    def order(self) -> dict:
        if self.state == "ready":
            return shipment()
        printing = {"state": "not_printed", "label": "Not printed", "history": [], "first_print_available": True}
        if self.state == "printed":
            printing = {"state": "printing", "label": "Printing", "first_print_available": False,
                        "history": [{"state": "printing", "via": "PrintNode", "reprint": False}]}
        return shipment(stage="bought", status="Bought", tracking_number=LABEL["tracking_number"], label=dict(LABEL),
                        print_status=printing, can_buy=False)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        path = request.url.path
        if request.method == "POST" and path.endswith("/preview"):
            return httpx.Response(200, json={"will": ["Buy the Parcelforce label for CROOKS-2202."], "basis": "b1_2202",
                                             "money": {"shipping_minor": 1179, "currency": "GBP"},
                                             "service": {"carrier": "Parcel2Go", "name": "Parcelforce"},
                                             "charged": "Charged to the shop's Parcel2Go account."})
        if request.method == "POST" and path.endswith("/buy"):
            self.buy_arrived.set()
            await self.buy_release.wait()
            if self.bought:
                self.state = "bought"
            return httpx.Response(200, json=self.buy_answer or {"charged": True, "status": "fulfilled",
                                                                "shipment": self.order()})
        if request.method == "POST" and path.endswith("/print"):
            self.state = "printed"
            return httpx.Response(200, json={"print_intent": {"state": "printing", "provider_job_id": 7, "error": None},
                                             "sent_to_printer": True})
        if request.method == "GET" and path.endswith(f"/shipments/{SID}"):
            return httpx.Response(200, json=self.order())
        return httpx.Response(404, json={"detail": {"message": "not here", "code": "not_found"}})

    def posted(self) -> list[str]:
        return [r.url.path.rsplit("/", 1)[-1] for r in self.seen if r.method == "POST"]


@pytest.fixture()
async def client(monkeypatch):
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))
    held = {sc.READ_KEY: READ, sc.WRITE_KEY: WRITE}
    monkeypatch.setattr(keychain, "get_optional", lambda key: held.get(key))
    monkeypatch.setattr(shipping_tools, "_UNCONFIRMED", type(shipping_tools._UNCONFIRMED)())

    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = FakeProvider()
        store = FakeStore(note="")
        runtime.shopify = store
        shopify_tools.bind(store)
        runtime.actions.ledger = NullLedger()
        runtime.sessions = SessionManager()
        runtime.settings = runtime.settings.model_copy(update={
            "writes_enabled": True, "allowed_logins": OWNER, "writes_local_owner": False, "tailscale_verify": False})
        app.state.allowed_logins = runtime.allowed_logins
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.runtime = runtime
            yield c
    sc.configure(base_url=sc.DEFAULT_BASE_URL)


def serve(monkeypatch, service: Service) -> Service:
    monkeypatch.setattr(sc, "http_client", lambda timeout_s: httpx.AsyncClient(transport=httpx.MockTransport(service)))
    sc.configure(base_url="https://returns.example.com/shipping")
    return service


async def buy_card(client, session_id: str = "s1"):
    session = client.runtime.sessions.get_or_create(session_id)
    session.issue(SID)
    session.epoch = max(session.epoch, 1)
    text = await dispatch(shipping_tools.BUY, {"shipment_id": SID}, session=session, timeout_s=10)
    assert text.startswith("PROPOSED"), text
    return session.proposals[-1]


async def hold_and_tap(client, proposal, session_id: str = "s1") -> httpx.Response:
    """His hold on the buy card, then the tap: the commit carries the hold's token."""
    armed = await client.post(f"/actions/{proposal.proposal_id}/arm", data={"session_id": session_id}, headers=PROXIED)
    assert armed.status_code == 200, armed.text
    proposal.armed_at -= 1.0
    return await client.post(f"/actions/{proposal.proposal_id}/commit", data={"session_id": session_id},
                             headers={**PROXIED, "X-Crooks-Arm": armed.json()["nonce"]})


async def settled(client, proposal, answer: dict, session_id: str = "s1") -> dict:
    """What the tablet ends up with: the commit's own answer, or, when that was in flight, what it is
    told when it asks how the change stands (web/app.js `followInFlight`)."""
    for _ in range(200):
        if answer.get("status") not in ("executing", "executed"):
            return answer
        await asyncio.sleep(0.02)
        asked = await client.get(f"/actions/{proposal.proposal_id}", params={"session_id": session_id}, headers=PROXIED)
        assert asked.status_code == 200, asked.text
        answer = asked.json()
    raise AssertionError(f"never settled: {answer}")


def cards(answer: dict, kind: str) -> list[dict]:
    return [item for item in answer.get("ui") or [] if item.get("type") == kind]


# ------------------------------------------------------------------ the tap answers at once


async def test_a_buy_tap_is_answered_in_flight_before_the_provider_answers(client, monkeypatch):
    service = serve(monkeypatch, Service())
    proposal = await buy_card(client)
    service.buy_release.clear()   # the courier takes its time

    tap = asyncio.create_task(hold_and_tap(client, proposal))
    response = await asyncio.wait_for(tap, timeout=5)
    answer = response.json()
    assert response.status_code == 200, response.text
    assert service.buy_arrived.is_set() and service.posted() == ["preview", "buy"], "the buy is with the service"
    assert not service.buy_release.is_set(), "and the service has not answered it yet"
    assert answer["code"] == "in_progress" and answer["status"] == "executing", answer
    assert answer["in_flight"]["label"] == "Buying the label…"
    assert answer["in_flight"]["wait_s"] >= sc.BUY_TIMEOUT_S, "the tablet keeps asking for as long as a buy may take"
    assert answer["spoken"] == "" and answer["ui"] == [], "nothing is said to have happened yet"

    # The tablet asks how it stands: still being made, never "not applied".
    asked = (await client.get(f"/actions/{proposal.proposal_id}", params={"session_id": "s1"}, headers=PROXIED)).json()
    assert asked["status"] == "executing" and cards(asked, "error")[0]["data"]["kind"] == "in_progress"

    service.buy_release.set()
    done = await settled(client, proposal, asked)
    assert done["code"] == "verified" and done["status"] == "verified", done
    assert done["spoken"].startswith("Label bought for order 2202, ")
    assert cards(done, "success")[0]["data"]["operation"] == shipping_tools.BUY
    assert service.posted() == ["preview", "buy"], "bought once; nothing printed"


async def test_a_refusal_before_anything_leaves_is_answered_as_it_always_was(client, monkeypatch):
    """A tap without its hold is refused at once, not answered in flight."""
    service = serve(monkeypatch, Service())
    proposal = await buy_card(client)
    response = await client.post(f"/actions/{proposal.proposal_id}/commit", data={"session_id": "s1"}, headers=PROXIED)
    assert response.status_code == 409 and response.json()["code"] == "not_armed"
    assert service.posted() == ["preview"] and proposal.status.value == "PENDING"


def test_the_tablet_shows_the_work_under_way_and_asks_until_it_has_settled():
    """The tap's surface says "Applying…" the moment it is tapped (web/ui.js), and the Mac's in-flight
    answer puts what is under way on it and asks how it stands, never tapping again (web/app.js)."""
    ui_js = (WEB / "ui.js").read_text(encoding="utf-8")
    app_js = (WEB / "app.js").read_text(encoding="utf-8")
    commit = ui_js[ui_js.index("    const commit = () => {"):]
    commit = commit[:commit.index("    };")]
    assert commit.index("setState('committing');") < commit.index("opts.onCommit(")
    settle = app_js[app_js.index("function settleAction(node, payload, status)"):]
    settle = settle[:settle.index("\n}")]
    assert "payload.in_flight" in settle and "String(flight.label)" in settle
    assert "followInFlight(node.dataset.proposal || '', flight.wait_s)" in settle
    follow = app_js[app_js.index("async function followInFlight(proposalId, waitS)"):]
    follow = follow[:follow.index("\n}")]
    assert "fetch(`/actions/${encodeURIComponent(proposalId)}?session_id=" in follow
    assert "/commit" not in follow and "method: 'POST'" not in follow, "it asks; it never sends the change again"
    assert "signal: controller.signal" in follow


# ------------------------------------------------------------------ the print, offered once the label is bought


async def test_a_label_proven_bought_offers_its_print_on_the_same_screen(client, monkeypatch):
    service = serve(monkeypatch, Service())
    proposal = await buy_card(client)
    service.buy_release.clear()
    answer = (await hold_and_tap(client, proposal)).json()
    service.buy_release.set()
    done = await settled(client, proposal, answer)

    assert done["code"] == "verified", done
    (offer,) = cards(done, "confirmation")
    data = offer["data"]
    assert data["operation"] == shipping_tools.PRINT and data["status"] == "pending"
    assert data["title"] == "Print the label for #2202" and data["interaction"]["kind"] == "swipe_commit"
    assert "print" not in service.posted(), "offered, not printed: the print waits for his own gesture"
    order = cards(done, "shipping")[0]["data"]
    assert order["shipments"][0]["label"]["provider"] == "Parcel2Go", "the order as it now is, beside the offer"

    # Asked again, the same offer: never a second print card.
    again = (await client.get(f"/actions/{proposal.proposal_id}", params={"session_id": "s1"}, headers=PROXIED)).json()
    assert cards(again, "confirmation")[0]["data"]["proposal_id"] == data["proposal_id"]

    # His swipe on it prints the label, answered as a print always was.
    printed = await client.post(f"/actions/{data['proposal_id']}/commit", data={"session_id": "s1"}, headers=PROXIED)
    body = printed.json()
    assert printed.status_code == 200 and body["code"] == "verified", body
    assert "in_flight" not in body
    assert service.posted() == ["preview", "buy", "print"]
    # Once used, it is not offered again.
    later = (await client.get(f"/actions/{proposal.proposal_id}", params={"session_id": "s1"}, headers=PROXIED)).json()
    assert not cards(later, "confirmation") and service.posted() == ["preview", "buy", "print"]


async def test_a_buy_answered_at_once_offers_the_print_too(client, monkeypatch):
    """A buy the service answers within the moment is answered by the tap itself, print offer and all."""
    service = serve(monkeypatch, Service())
    monkeypatch.setattr("app.routes.actions.IN_FLIGHT_AFTER_S", 5.0)
    proposal = await buy_card(client)
    answer = (await hold_and_tap(client, proposal)).json()
    assert answer["code"] == "verified" and "in_flight" not in answer, answer
    assert cards(answer, "confirmation")[0]["data"]["operation"] == shipping_tools.PRINT
    assert service.posted() == ["preview", "buy"]


async def test_no_print_is_offered_when_the_buy_is_not_confirmed(client, monkeypatch):
    serve(monkeypatch, Service(bought=False, buy_answer={"charged": False, "may_have_been_charged": True,
                                                         "status": "unverified", "shipment": shipment()}))
    proposal = await buy_card(client)
    done = await settled(client, proposal, (await hold_and_tap(client, proposal)).json())
    assert done["code"] == "unverified" and not cards(done, "confirmation"), done


# ------------------------------------------------------------------ the reason, said once, on the card


async def test_an_unconfirmed_buy_says_its_specific_reason_on_the_card(client, monkeypatch):
    service = serve(monkeypatch, Service(bought=False, buy_answer={"charged": False, "may_have_been_charged": True,
                                                                   "status": "unverified", "shipment": shipment()}))
    proposal = await buy_card(client)
    done = await settled(client, proposal, (await hold_and_tap(client, proposal)).json())

    assert done["code"] == "unverified" and done["status"] == "unverified", done
    (failed,) = cards(done, "error")
    reason = failed["data"]["recovery"]
    assert reason == ("Not confirmed: The courier may have taken the payment, and CLIVE Shipping is checking it. "
                      "Don't buy again: look at the order in Shipping.")
    assert "could not be confirmed" not in reason, "the specific reason, not the generic line"
    assert "may have taken the payment" in done["spoken"], "and the voice says the same reason"
    assert service.posted() == ["preview", "buy"]

    # The same card cannot be tapped into a second buy: it is settled, and says so again.
    retried = await client.post(f"/actions/{proposal.proposal_id}/commit", data={"session_id": "s1"}, headers=PROXIED)
    assert retried.json()["code"] == "unverified" and service.posted() == ["preview", "buy"]


async def test_the_next_buy_card_for_that_label_says_why_the_last_was_not_confirmed(client, monkeypatch):
    serve(monkeypatch, Service(bought=False, buy_answer={"charged": False, "may_have_been_charged": True,
                                                         "status": "unverified", "shipment": shipment()}))
    first = await buy_card(client)
    await settled(client, first, (await hold_and_tap(client, first)).json())

    from app.presentation import present_proposal_state

    second = await buy_card(client)
    assert second.proposal_id != first.proposal_id
    (card,) = present_proposal_state(second)
    data = card["data"]
    assert data["facts"][0] == {"label": "Last try", "value": "Not confirmed: read why before holding", "tone": "bad"}
    assert data["summary"] == ("Not confirmed: The courier may have taken the payment, and CLIVE Shipping is checking "
                               "it. Don't buy again: look at the order in Shipping. Charged to the shop's Parcel2Go "
                               "account."), "why, whole, before the price check's own line"
    assert {"label": "Moves money", "value": "yes: hold the card, then tap", "tone": "bad"} in data["facts"]
    # A label nothing went wrong with is carded as it always was.
    shipping_tools._UNCONFIRMED.clear()
    session = client.runtime.sessions.get_or_create("s2")
    session.issue(SID)
    session.epoch = 1
    await dispatch(shipping_tools.BUY, {"shipment_id": SID}, session=session, timeout_s=10)
    (plain,) = present_proposal_state(session.proposals[-1])
    assert plain["data"]["summary"] == "Charged to the shop's Parcel2Go account."
    assert plain["data"]["facts"][0] == {"label": "Order", "value": "#2202", "tone": ""}


def test_every_unconfirmed_reason_says_not_to_buy_again_blind():
    said = shipping_tools.unconfirmed_reason("CLIVE Shipping answered, but the order shows no label: Parcel2Go timed out.")
    assert said == ("Not confirmed: CLIVE Shipping answered, but the order shows no label: Parcel2Go timed out. "
                    "Don't buy it again until Shipping shows whether it was bought.")
    lost = shipping_tools.unconfirmed_reason("CLIVE lost CLIVE Shipping's answer and can't see the label as CLIVE's on "
                                             "the order. Look at it in Shipping before asking again.")
    assert lost.count("again") == 1, "said once"


def test_a_label_confirmed_bought_clears_the_last_reason(monkeypatch):
    monkeypatch.setattr(shipping_tools, "_UNCONFIRMED", type(shipping_tools._UNCONFIRMED)({SID: "Not confirmed: x"}))
    execution = {"shipment_id": SID, "idempotency_key": "clive-buy-cleared-card"}
    shipping_tools._remember(execution["idempotency_key"], {"charged": True, "may_have_been_charged": False,
                                                             "replayed": False, "status": "fulfilled", "error": ""})
    ok, _note = shipping_tools.verify_buy({"bought": False}, {"bought": True, "tracking": True}, execution)
    assert ok and SID not in shipping_tools._UNCONFIRMED


# ------------------------------------------------------------------ nothing else changes


def test_only_the_buy_is_answered_in_flight_and_only_it_offers_a_next_step():
    assert shipping_tools.in_flight(shipping_tools.BUY) is not None
    for other in (shipping_tools.PRINT, shipping_tools.REPRINT, "order_note_append", "gmail_send_reply"):
        assert shipping_tools.in_flight(other) is None
    assert shipping_tools.NEXT_STEP == {shipping_tools.BUY: shipping_tools.PRINT}
