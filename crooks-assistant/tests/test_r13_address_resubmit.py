"""Round 13, F/F-01: the address card sends what the owner changed, and nothing else.

The round-12 review found it, and the code at production has it too: the address workspace
handed the write tool all seven fields on every change. Two things were lost that way.

* The recipient. The tool splits a name on its first space, so a postcode fix on an order for
  "Mary Ann" "Smith" rewrote it as "Mary" "Ann Smith", and a recipient with only a surname
  came back with it as a first name. The owner had not touched the name.
* Anything too long for its box. A name of 81 to 100 characters was cut to 80 on the way in,
  shown as fine, and sent back cut.

Every test here is the owner's own taps through the real `POST /command`: open the address
from the order, type into a field, and Prepare. What is asserted is what the Mac put in front
of the write tool (the proposal's arguments) and what the shop would be sent (its execution).
The shop is the address test's fake; every name and address is invented.
"""

from __future__ import annotations

import httpx
import pytest

from app.actions.ledger import ActionLedger
from app.context.order import shape_address
from app.main import app
from app.session.manager import SessionManager
from app.tools import shopify_tools, shopify_writes
from tests.test_actions import ORDER
from tests.test_address import AddressStore
from tests.test_context import inbox

OWNER = "owner@example.com"
PROXIED = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.9"}
SESSION = "adr13"
TOO_LONG = "too long to edit here"

MARY_ANN = {
    "firstName": "Mary Ann", "lastName": "Smith", "company": None, "address1": "12 Quarry Lane", "address2": "Flat 3",
    "city": "Windsor", "province": None, "provinceCode": None, "zip": "SL4 1AA", "country": "United Kingdom",
    "countryCodeV2": "GB", "phone": None,
}


@pytest.fixture()
async def desk(monkeypatch, tmp_path):
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
    monkeypatch.setattr(shopify_writes, "_destination_reads", True)

    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        store = AddressStore()
        store.address = dict(MARY_ANN)
        runtime.shopify = store
        # No mail about the address: the owner typed it, and no inbox is reached.
        shopify_tools.bind(store, threads_for=inbox(threads=[]))
        runtime.actions.ledger = ActionLedger(tmp_path)
        runtime.sessions = SessionManager()
        runtime.sessions.on_drop.append(runtime.actions.forget_session)
        runtime.settings = runtime.settings.model_copy(
            update={"writes_enabled": True, "allowed_logins": OWNER, "writes_local_owner": False, "tailscale_verify": False}
        )
        app.state.allowed_logins = runtime.allowed_logins
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
            client.runtime, client.store = runtime, store
            yield client


def _hold(desk, address: dict) -> None:
    """The order as the Mac holds it after the owner opened it: the context shape, whose
    delivery address is `shape_address` of what Shopify answered."""
    from app.memory import ENTITY
    from app.memory import current as memory

    desk.store.address = dict(address)
    memory().put(ENTITY, f"order:{ORDER}", {
        "order_id": ORDER, "order_number": "#1930", "fulfillment": "UNFULFILLED", "fulfillments": [],
        "shipping_address": shape_address(address),
    }, source="shopify")
    desk.runtime.sessions.get_or_create(SESSION).issue(ORDER)


async def _tap(desk, command: str, **fields) -> dict:
    response = await desk.post("/command", data={"session_id": SESSION, "command": command, **fields}, headers=PROXIED)
    assert response.status_code == 200, response.text
    return response.json()


def _card(body: dict) -> dict:
    return next(i for i in body["ui"] if i.get("type") == "workspace")["data"]


def _fields(body: dict) -> dict[str, dict]:
    return {f["name"]: f for f in _card(body)["fields"]}


async def _open(desk, address: dict) -> tuple[str, dict]:
    _hold(desk, address)
    body = await _tap(desk, "address.open", order_id=ORDER)
    assert body["ok"], body
    return body["changed"]["workspace_id"], body


async def _type(desk, ident: str, **typed: str) -> dict:
    body = {}
    for field, value in typed.items():
        body = await _tap(desk, "address.field", workspace_id=ident, field=field, value=value)
        assert body["ok"], body
    return body


async def _prepare(desk, ident: str):
    body = await _tap(desk, "address.stage", workspace_id=ident)
    if not body["ok"]:
        return body, None
    return body, desk.runtime.actions.find(body["changed"]["proposal_id"])


# ------------------------------------------------------------------ the recipient's name


async def test_a_postcode_fix_sends_the_postcode_and_leaves_the_recipient_as_it_was(desk):
    """The review's own case. He types a postcode; the name is not his to lose."""
    ident, _ = await _open(desk, MARY_ANN)
    await _type(desk, ident, postcode="sl4 1ab")
    body, proposal = await _prepare(desk, ident)
    assert proposal is not None, body
    assert set(proposal.model_args) == {"order_id", "postcode", "from_owner"}, dict(proposal.model_args)
    sent = proposal.execution["address"]
    assert (sent["firstName"], sent["lastName"]) == ("Mary Ann", "Smith")
    assert (sent["address1"], sent["address2"], sent["zip"]) == ("12 Quarry Lane", "Flat 3", "SL4 1AB")
    assert proposal.summary["changes"] == ["postcode"]


async def test_a_recipient_with_only_a_surname_keeps_it_as_a_surname(desk):
    ident, _ = await _open(desk, dict(MARY_ANN, firstName=None, lastName="Okafor"))
    await _type(desk, ident, city="Eton")
    _, proposal = await _prepare(desk, ident)
    assert proposal is not None
    assert "name" not in proposal.model_args
    sent = proposal.execution["address"]
    assert sent.get("lastName") == "Okafor" and not sent.get("firstName"), sent
    assert proposal.summary["changes"] == ["town"]


async def test_a_name_the_owner_types_is_sent(desk):
    ident, _ = await _open(desk, MARY_ANN)
    await _type(desk, ident, name="Maryanne Smith")
    _, proposal = await _prepare(desk, ident)
    assert proposal is not None
    assert proposal.model_args["name"] == "Maryanne Smith"
    assert set(proposal.model_args) == {"order_id", "name", "from_owner"}
    assert proposal.summary["changes"] == ["name"]


# ------------------------------------------------------------------ too long, never cut


async def test_a_name_too_long_for_its_box_is_shown_whole_and_marked_not_cut(desk):
    first, last = "Maximiliana Theodora Wilhelmina Anastasia", "Featherstonehaugh-Cholmondeley-Marjoribanks"
    ident, body = await _open(desk, dict(MARY_ANN, firstName=first, lastName=last))
    name = _fields(body)["name"]
    assert len(f"{first} {last}") > 80
    assert name["value"] == f"{first} {last}", "the box shows the name as it stands, not a shorter one"
    assert name["status"] == "invalid" and TOO_LONG in name["hint"] and "Shopify Admin" in name["hint"]
    # Left alone it is not part of the change, so the postcode can still be put right.
    await _type(desk, ident, postcode="SL4 1AB")
    _, proposal = await _prepare(desk, ident)
    assert proposal is not None
    assert "name" not in proposal.model_args
    sent = proposal.execution["address"]
    assert (sent["firstName"], sent["lastName"]) == (first, last)


async def test_a_value_typed_past_its_limit_is_refused_not_cut(desk):
    ident, _ = await _open(desk, MARY_ANN)
    body = await _type(desk, ident, name="A" * 81)
    assert _fields(body)["name"]["status"] == "invalid"
    refused, proposal = await _prepare(desk, ident)
    assert proposal is None and refused["code"] == "not_ready", refused
    assert "Recipient" in refused["detail"]
    street = await _type(desk, ident, name="Mary Ann Smith", address1="1 " + "Long " * 25)
    assert _fields(street)["address1"]["status"] == "invalid"
    refused, proposal = await _prepare(desk, ident)
    assert proposal is None and "Number and street" in refused["detail"]
    assert desk.store.mutations == []


async def test_a_street_too_long_to_edit_here_is_left_alone_and_never_resent(desk):
    long_street = "The Old Coach House, Upper Quarry Lane Industrial Estate, Behind The Former Wheelwright Works, Unit 7B"
    assert 100 < len(long_street) <= 120
    ident, body = await _open(desk, dict(MARY_ANN, address1=long_street))
    street = _fields(body)["address1"]
    assert street["value"] == long_street and street["status"] == "invalid" and TOO_LONG in street["hint"]
    await _type(desk, ident, postcode="SL4 1AB")
    _, proposal = await _prepare(desk, ident)
    assert proposal is not None
    assert "address1" not in proposal.model_args and "address2" not in proposal.model_args
    assert proposal.execution["address"]["address1"] == long_street


async def test_clearing_the_second_line_under_a_street_too_long_to_resend_is_refused(desk):
    """Clearing a second line means re-sending the street (the tool clears it only with one);
    a street too long to send cannot be re-sent, so the card says so rather than cut it."""
    long_street = "The Old Coach House, Upper Quarry Lane Industrial Estate, Behind The Former Wheelwright Works, Unit 7B"
    ident, _ = await _open(desk, dict(MARY_ANN, address1=long_street))
    await _type(desk, ident, address2="")
    refused, proposal = await _prepare(desk, ident)
    assert proposal is None and refused["code"] == "not_ready"
    assert "Number and street" in refused["detail"] and TOO_LONG in refused["detail"]


async def test_a_new_street_under_a_second_line_too_long_to_resend_is_refused(desk):
    long_flat = "Flat 3, The Old Coach House Annexe, Rear Entrance Beside The Former Wheelwright Works Yard Gate, Door B"
    assert 100 < len(long_flat) <= 120
    ident, _ = await _open(desk, dict(MARY_ANN, address2=long_flat))
    await _type(desk, ident, address1="14 Quarry Lane")
    refused, proposal = await _prepare(desk, ident)
    assert proposal is None and "Second line" in refused["detail"] and TOO_LONG in refused["detail"]


# ------------------------------------------------------------------ the street and its second line


async def test_a_new_street_carries_the_second_line_with_it(desk):
    """The tool drops the old second line when the street changes (an old flat on a new street
    is a wrong address), so the second line on the card always goes with a new street."""
    ident, _ = await _open(desk, MARY_ANN)
    await _type(desk, ident, address1="14 Quarry Lane")
    _, proposal = await _prepare(desk, ident)
    assert proposal is not None
    assert set(proposal.model_args) == {"order_id", "address1", "address2", "from_owner"}
    assert proposal.model_args["address2"] == "Flat 3"
    sent = proposal.execution["address"]
    assert (sent["address1"], sent["address2"]) == ("14 Quarry Lane", "Flat 3")
    assert (sent["firstName"], sent["lastName"]) == ("Mary Ann", "Smith")


async def test_a_second_line_changed_alone_goes_alone(desk):
    ident, _ = await _open(desk, MARY_ANN)
    await _type(desk, ident, address2="Flat 4")
    _, proposal = await _prepare(desk, ident)
    assert proposal is not None
    assert set(proposal.model_args) == {"order_id", "address2", "from_owner"}
    assert proposal.execution["address"]["address1"] == "12 Quarry Lane"
    assert proposal.execution["address"]["address2"] == "Flat 4"


async def test_a_second_line_cleared_is_cleared(desk):
    ident, _ = await _open(desk, MARY_ANN)
    await _type(desk, ident, address2="")
    _, proposal = await _prepare(desk, ident)
    assert proposal is not None
    assert proposal.model_args["address1"] == "12 Quarry Lane" and proposal.model_args["address2"] == ""
    assert "address2" not in proposal.execution["address"]
    assert proposal.execution["address"]["address1"] == "12 Quarry Lane"
    assert proposal.summary["changes"] == ["second line cleared"]


# ------------------------------------------------------------------ nothing changed


async def test_retyping_what_is_there_is_not_a_change(desk):
    ident, _ = await _open(desk, dict(MARY_ANN, provinceCode="ENG"))
    await _type(desk, ident, postcode="sl4  1aa", province_code="eng")
    refused, proposal = await _prepare(desk, ident)
    assert proposal is None and refused["code"] == "not_ready", refused
    assert "nothing has changed" in refused["detail"].lower()


async def test_an_untouched_card_with_a_region_code_is_not_a_change(desk):
    """The old check compared two strings joined in different orders, so an address with a
    region code was never "unchanged" and went to the tool whole."""
    ident, _ = await _open(desk, dict(MARY_ANN, provinceCode="ENG"))
    refused, proposal = await _prepare(desk, ident)
    assert proposal is None and refused["code"] == "not_ready", refused
    assert "nothing has changed" in refused["detail"].lower()
