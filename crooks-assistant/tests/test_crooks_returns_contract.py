"""CLIVE's CROOKS Returns client against the service's OWN code, offline: the true contract.

The returns service is George's (branch claude/compassionate-dirac-44hnee, folder crooks-returns/);
nothing of it is copied into CLIVE. This test takes that folder from the repository's history with
`git archive` (or from CROOKS_RETURNS_SRC, a checkout of crooks-returns/), and runs its FastAPI app
in this process, with the service's own fake Shopify (returns/fake.py) and its own simulated
Parcel2Go (tests/test_parcel2go.py FakeParcel2Go, the sandbox's answers of 3 October). CLIVE's
client reaches it through an ASGI transport: the same requests it sends to returns.crooksldn.com,
answered by the code that answers them there. Nothing reaches a network.

What it proves, through CLIVE's own tools and action engine:
  - preview equals execute: the card's will lines are the service's preview, word for word; what
    the owner's hold then does is what they said (one label bought, at the price the preview gave);
    and an action the preview refuses is refused by execute in the same words;
  - an approved action carries a fresh idempotency key and "clive for George", and sent again with
    that key it is replayed: never a second label, never a second Shopify return;
  - a refusal comes back in words, and an error the service records is said as the service said it.

Skipped, saying why, where the service's code is not in this repository's history (a shallow
clone): the acceptance workflow checks out with full history, so it runs there.
"""

from __future__ import annotations

import types
from datetime import UTC, datetime

import httpx
import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.clients import crooks_returns as rc
from app.secrets import keychain
from app.session.models import Session
from app.tools import registry, returns_tools
from app.tools.dispatch import dispatch
from tests import returns_service
from tests.fake_credentials import bearer_token

READ = bearer_token("contract-read", length=32)
WRITE = bearer_token("contract-write", length=32)
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
TEE = "gid://shopify/FulfillmentLineItem/1"

pytestmark = pytest.mark.usefixtures("owner_asking")


@pytest.fixture(scope="module")
def service_code(tmp_path_factory):
    loaded = returns_service.load(tmp_path_factory.mktemp("crooks-returns"))
    if loaded is None:
        pytest.skip(returns_service.WHY_NOT)
    yield loaded
    returns_service.unload(loaded)


@pytest.fixture()
def world(service_code, tmp_path, monkeypatch):
    """The service as deployed, but on its own fakes: Parcel2Go labels (simulated), fake Shopify."""
    s = service_code
    settings = returns_service.settings(s, tmp_path, read_key=READ, write_key=WRITE)
    parcel2go = s.p2g.FakeParcel2Go()
    labels = s.parcel2go.Parcel2Go(settings, http=httpx.Client(transport=httpx.MockTransport(parcel2go)))
    shop = s.fake.FakeShopify(s.fake.sample_orders(NOW))
    svc = s.service.ReturnsService(settings, s.store.Store(settings.db_path), shop, labels, clock=lambda: NOW)
    app = s.app.create_app(settings, svc)
    held = {rc.READ_KEY: READ, rc.WRITE_KEY: WRITE}
    monkeypatch.setattr(keychain, "get_optional", lambda key: held.get(key))
    monkeypatch.setattr(rc, "http_client", lambda timeout_s: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), timeout=timeout_s))
    rc.configure(base_url="https://returns.example.com")
    rc.forget()
    engine = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", engine)
    yield types.SimpleNamespace(svc=svc, shop=shop, parcel2go=parcel2go, engine=engine, s=s, keys=held)
    rc.configure(base_url=rc.DEFAULT_BASE_URL)
    rc.forget()


def _ask_for_a_return(world, resolution="store_credit", courier="evri"):
    """What the customer does on crooksldn.com/pages/returns, by the service's own flow."""
    m = world.s.models
    session, _ = world.svc.lookup("1939", "customer@example.com", "1.2.3.4")
    order = world.svc.order_for_session(session)
    picked = [m.Selection(fulfillment_line_item_id=TEE, quantity=1, reason=m.Reason.changed_mind)]
    return world.svc.submit(order, picked, m.Resolution(resolution), m.Postage.free_label, {}, courier)


def _lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def _stage(session, rid, **args):
    session.issue(rid)
    text = await dispatch("return_action", {"return_id": rid, **args}, session=session, timeout_s=10)
    return text, (session.proposals[-1] if session.proposals else None)


async def _approve(world, proposal, *, hold):
    nonce = ""
    if hold:
        world.engine.arm(proposal.proposal_id, "k1")
        proposal.armed_at -= 1.0
        nonce = proposal.arm_nonce
    return await world.engine.commit(proposal.proposal_id, "k1", caller="owner@example.com", spec_lookup=_lookup, nonce=nonce)


async def test_preview_equals_execute_and_the_owners_hold_buys_one_label(world):
    asked = _ask_for_a_return(world)
    opened = await returns_tools.returns_open()
    (row,) = opened["returns"]
    assert row["return_id"] == asked.id and row["attention_words"] == ["to approve"]
    assert [(m["label"], m["shown"]) for m in row["money"]] == [("Items", "£25.00"), ("Store credit", "£30.00"),
                                                                ("of which bonus", "£5.00")]

    session = Session(session_id="k1")
    session.epoch = 1
    text, proposal = await _stage(session, asked.id, action="approve", postage_mode="label_now")
    assert text.startswith("PROPOSED") and proposal.interaction == "hold_to_arm"
    said = world.svc.preview(asked.id, "approve", {"postage_mode": "label_now"})
    assert proposal.summary["will"] == said["will"], "the card is the service's own preview, word for word"
    assert any("Book Evri (Evri Parcelshop) for £2.39" in w for w in said["will"])
    assert world.parcel2go.orders == [] and world.shop.calls == [], "preparing the card bought nothing and asked Shopify nothing"

    result = await _approve(world, proposal, hold=True)
    assert result.code == "verified", result.spoken
    after = world.svc.store.get(asked.id)
    assert after.status.value == "awaiting_shipment" and after.postage.label_price_pence == 239, "what the preview said"
    assert len(world.parcel2go.orders) == 1 and len(world.shop.called("returnCreate")) == 1
    assert [e.actor for e in after.timeline if e.type == "approved"] == ["clive for George"]
    key = dict(proposal.execution)["idempotency_key"]
    assert key.startswith("clive-approve-")

    # The same key again is the first outcome replayed: no second label, no second Shopify return.
    replayed = await rc.execute(asked.id, "approve", {"postage_mode": "label_now"}, idempotency_key=key)
    assert replayed["replayed"] is True and replayed["status"] == "awaiting_shipment"
    assert len(world.parcel2go.orders) == 1 and len(world.shop.called("returnCreate")) == 1

    # A fresh key for an action the return has moved past: refused, in the service's own words, by
    # preview and execute alike.
    with pytest.raises(rc.ReturnsUnavailable) as by_execute:
        await rc.execute(asked.id, "approve", {"postage_mode": "label_now"}, idempotency_key="clive-approve-fresh")
    with pytest.raises(rc.ReturnsUnavailable) as by_preview:
        await rc.preview(asked.id, "approve", {"postage_mode": "label_now"})
    assert str(by_execute.value) == str(by_preview.value) == "This return is awaiting_shipment; that needs requested."
    assert by_execute.value.kind == "refused" and len(world.parcel2go.orders) == 1

    staged = len(session.proposals)
    text, _ = await _stage(session, asked.id, action="complete")
    assert text.startswith("ERROR: This return is awaiting_shipment; that needs received.")
    assert len(session.proposals) == staged, "a refused preview stages nothing"


async def test_receiving_it_moves_the_money_once_and_says_where_it_is(world):
    asked = _ask_for_a_return(world)
    world.svc.execute(asked.id, "approve", {"postage_mode": "self_ship"}, "staff", "approve-1")
    session = Session(session_id="k1")
    session.epoch = 1
    _, tracking = await _stage(session, asked.id, action="tracking", tracking="rm 1234 5678 9gb")
    assert (await _approve(world, tracking, hold=False)).code == "verified"
    found = await returns_tools.return_find(order="#1939")
    (one,) = found["returns"]
    assert one["status"] == "in_transit" and one["postage"]["tracking"] == "RM123456789GB"
    assert one["where"].startswith("#1939 is on its way back; last: on its way back on 3 Oct; tracking RM123456789GB")

    _, receive = await _stage(session, asked.id, action="receive")
    assert dict(receive.execution)["params"] == {"condition": "ok", "restock": True}
    assert receive.interaction == "hold_to_arm"
    assert (await _approve(world, receive, hold=False)).code == "not_armed" and not world.shop.called("returnProcess")
    result = await _approve(world, receive, hold=True)
    assert result.code == "verified", result.spoken
    assert world.svc.store.get(asked.id).status.value == "completed"
    assert len(world.shop.called("returnProcess")) == 1 and len(world.shop.called("storeCreditAccountCredit")) == 1
    stats = await returns_tools.returns_stats(days=30)
    assert stats["returns"] == 1 and stats["kept_share"] == "100%" and stats["bonus_given"] == "£5.00"


async def test_an_error_the_service_records_is_said_in_its_words(world):
    asked = _ask_for_a_return(world)
    world.svc.execute(asked.id, "approve", {"postage_mode": "self_ship"}, "staff", "approve-1")
    world.shop.fail.add("process_return")
    session = Session(session_id="k1")
    session.epoch = 1
    _, receive = await _stage(session, asked.id, action="receive", condition="ok")
    result = await _approve(world, receive, hold=True)
    assert result.code == "unverified" and receive.status is ActionStatus.UNVERIFIED
    assert result.spoken.endswith("CROOKS Returns recorded it, but part of it failed: Shopify did not process the return: "
                                  "process_return refused (test)")
    opened = await returns_tools.returns_open()
    assert opened["returns"][0]["attention_words"][0] == "has an error"


async def test_a_note_is_proven_by_the_timeline_and_the_write_key_is_the_only_one_that_acts(world):
    asked = _ask_for_a_return(world)
    session = Session(session_id="k1")
    session.epoch = 1
    _, note = await _stage(session, asked.id, action="note", text="Rang her: posting it Monday")
    assert note.interaction == "swipe_commit"
    world.keys[rc.WRITE_KEY] = READ
    refused = await _approve(world, note, hold=False)
    assert refused.code == "refused" and "refused CLIVE's write key" in refused.spoken
    world.keys[rc.WRITE_KEY] = WRITE
    session.epoch += 1
    _, again = await _stage(session, asked.id, action="note", text="Rang her: posting it Monday")
    assert (await _approve(world, again, hold=False)).code == "verified"
    last = world.svc.store.get(asked.id).timeline[-1]
    assert (last.type, last.actor, last.detail["text"]) == ("note", "clive for George", "Rang her: posting it Monday")
