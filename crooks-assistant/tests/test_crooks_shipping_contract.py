"""CLIVE's CLIVE Shipping client and tools against the service's OWN code, offline: the true contract.

The shipping service is George's (branch claude/n2-service-fixes, folder clive-shipping/); nothing
of it is copied into CLIVE. This test takes that folder from the repository's history at one pinned
commit (tests/shipping_service.py SERVICE_SHA, 8f15b796, the reviewed commit to deploy) and runs its
FastAPI app in this process with its own fake Shopify and its own fake courier ("behaves like
Parcel2Go, including charging again on re-pay"). CLIVE's client reaches it through an ASGI transport: the same requests
it sends to returns.crooksldn.com/shipping, answered by the code that answers them there. Nothing
reaches a network.

What it proves, through CLIVE's own tools and action engine:
  - the reads carry the read key alone, in the header, and name no customer;
  - the buy card IS the service's preview, word for word; preparing it buys nothing; only the
    owner's hold buys, once, with the preview's basis and a key made for that card, recorded by the
    service as "George (CLIVE)"; the same key again replays and never charges twice;
  - the server's own buying authorisation still decides: unauthorised, CLIVE stages nothing and says
    which setting allows it; a payment that changed since the card buys nothing;
  - printing goes through the service's PrintNode: refused in its words while PrintNode is off, then
    one first print, never a second, and an extra copy only as a confirmed reprint; never a purchase;
  - what changed and the carrier's tracking come back as the service holds them.
"""

from __future__ import annotations

import types
from unittest.mock import Mock

import httpx
import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import NullLedger
from app.clients import crooks_shipping as sc
from app.secrets import keychain
from app.session.models import Session
from app.tools import registry, shipping_tools
from app.tools.dispatch import dispatch
from tests import shipping_service
from tests.fake_credentials import bearer_token

READ = bearer_token("shipping-contract-read", length=32)
WRITE = bearer_token("shipping-contract-write", length=32)
# What the service's fake shop knows of the customer: none of it may reach CLIVE's results.
CUSTOMER = ("Max Muster", "Torstrasse", "max@example.com", "+4915112345678", "10115")

pytestmark = pytest.mark.usefixtures("owner_asking")


@pytest.fixture(scope="module")
def service_code(tmp_path_factory):
    missing = shipping_service.missing_libraries()
    if missing:
        shipping_service.not_here(missing)
    loaded = shipping_service.load(tmp_path_factory.mktemp("clive-shipping"))
    if loaded is None:
        shipping_service.not_here(shipping_service.WHY_NOT)
    yield loaded
    shipping_service.unload(loaded)


def _world(service_code, tmp_path, monkeypatch, *, buying: bool = True):
    from datetime import UTC, datetime

    w = shipping_service.world(service_code, tmp_path, read_key=READ, write_key=WRITE, buying=buying)
    w.clock.now = datetime.now(UTC).replace(microsecond=0)     # "what changed" is asked in real hours
    held = {sc.READ_KEY: READ, sc.WRITE_KEY: WRITE}
    seen: list[tuple[str, str, str]] = []

    class Recording(httpx.ASGITransport):
        async def handle_async_request(self, request):
            seen.append((request.method, request.url.path, request.headers.get("authorization", "")))
            return await super().handle_async_request(request)

    monkeypatch.setattr(keychain, "get_optional", lambda key: held.get(key))
    monkeypatch.setattr(sc, "http_client", lambda timeout_s: httpx.AsyncClient(
        transport=Recording(app=w.reached), timeout=timeout_s))
    sc.configure(base_url="https://returns.example.com/shipping")
    engine = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", engine)
    return types.SimpleNamespace(**vars(w), engine=engine, keys=held, seen=seen, s=service_code)


@pytest.fixture()
def world(service_code, tmp_path, monkeypatch):
    yield _world(service_code, tmp_path, monkeypatch)
    sc.configure(base_url=sc.DEFAULT_BASE_URL)


def _lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def _stage(session, tool, sid):
    session.issue(sid)
    before = len(session.proposals)
    text = await dispatch(tool, {"shipment_id": sid}, session=session, timeout_s=30)
    return text, (session.proposals[-1] if len(session.proposals) > before else None)


async def _approve(world, proposal, *, hold):
    nonce = ""
    if hold:
        world.engine.arm(proposal.proposal_id, "k1")
        proposal.armed_at -= 1.0
        nonce = proposal.arm_nonce
    return await world.engine.commit(proposal.proposal_id, "k1", caller="owner@example.com", spec_lookup=_lookup,
                                     nonce=nonce)


def _session() -> Session:
    session = Session(session_id="k1")
    session.epoch = 1
    return session


def _no_customer(value) -> None:
    text = repr(value)
    for detail in CUSTOMER:
        assert detail not in text, f"a customer's detail reached CLIVE: {detail}"


def test_the_service_code_is_the_pinned_commit_not_the_branch_tip(service_code):
    import subprocess

    if not service_code.sha:
        pytest.skip("CLIVE_SHIPPING_SRC names the service's code; it is whatever that checkout is")
    assert service_code.sha == shipping_service.SERVICE_SHA and len(service_code.sha) == 40
    for path in ("shipping/api.py", "shipping/purchase.py", "shipping/physical_printing.py"):
        pinned = subprocess.run(["git", "-C", str(shipping_service.ROOT), "show",
                                 f"{shipping_service.SERVICE_SHA}:clive-shipping/{path}"], capture_output=True, check=True).stdout
        assert (service_code.src / path).read_bytes() == pinned, path


async def test_the_reads_carry_the_read_key_alone_and_name_no_customer(world):
    ready = shipping_service.ready_order(world.s, world)
    caps = await sc.capabilities()
    assert caps["service"] == sc.NAME and list(caps["stages"]) == list(sc.STAGES)
    assert {(o["method"], o["path"]) for o in caps["operations"]} >= {
        ("POST", "/api/v1/shipments/{id}/buy"), ("POST", "/api/v1/shipments/{id}/print"),
        ("POST", "/api/v1/shipments/{id}/reprint"), ("POST", "/api/v1/shipments/{id}/preview")}

    opened = await shipping_tools.shipments_open()
    (row,) = opened["shipments"]
    assert (row["shipment_id"], row["order_number"], row["stage"], row["payment"]) == (ready.id, "#2145", "ready", "Paid")
    assert row["tone"] == "ask" and row["price"].startswith("£") and opened["needs_you"] == 1
    assert opened["counts"] == [{"stage": "ready", "words": "Ready to ship", "count": 1}]
    found = await shipping_tools.shipment_find(order="CROOKS-2145")
    (one,) = found["shipments"]
    assert one["can_buy"] is True and one["label"] is None and one["order_id"] == "gid://shopify/Order/2145"
    assert (one["payment"], one["carrier"], one["carrier_view"]) == ("Paid", "", None), "the detail's words, not its shape"
    nothing = await shipping_tools.shipment_find(order="9999")
    assert nothing["shipments"] == [] and "international orders only" in nothing["note"]
    _no_customer([opened, found])
    assert world.seen and all(auth == f"Bearer {READ}" for _m, _p, auth in world.seen), "reads carry the read key only"
    assert all(READ not in path for _m, path, _a in world.seen), "a key never travels in an address"


async def test_the_card_is_the_services_preview_and_only_the_hold_buys_once(world):
    ready = shipping_service.ready_order(world.s, world)
    session = _session()
    text, proposal = await _stage(session, shipping_tools.BUY, ready.id)
    assert text.startswith("PROPOSED") and proposal.interaction == "hold_to_arm"
    said = world.svc.preview(world.shop, ready.id)
    assert proposal.summary["will"] == said["will"], "the card is the service's own preview, word for word"
    assert proposal.summary["price"] == str(world.store.get(world.shop, ready.id).quote.amount)
    assert dict(proposal.execution)["basis"] == said["basis"]
    assert world.provider.charges == [], "preparing the card bought nothing"
    card = registry.get(shipping_tools.BUY).write.present(proposal)
    assert card["body"].splitlines() == said["will"] and card["title"] == "Buy the label for #2145"
    assert {"label": "Moves money", "value": "yes: hold the card, then tap", "tone": "bad"} in card["facts"]
    _no_customer([proposal.summary, card])

    assert (await _approve(world, proposal, hold=False)).code == "not_armed" and world.provider.charges == []
    result = await _approve(world, proposal, hold=True)
    assert result.code == "verified", result.spoken
    assert result.spoken.startswith(f"Label bought for order 2145, {proposal.summary['price']}.")
    assert len(world.provider.charges) == 1
    after = world.store.get(world.shop, ready.id)
    assert after.label is not None and any(e.actor == "George (CLIVE)" for e in after.timeline)
    key = dict(proposal.execution)["idempotency_key"]
    assert key.startswith("clive-buy-")
    write_calls = [(m, p) for m, p, auth in world.seen if auth == f"Bearer {WRITE}"]
    assert write_calls == [("POST", f"/shipping/api/v1/shipments/{ready.id}/buy")], "the write key went with the buy alone"

    # The same key again is the first outcome replayed: never a second charge.
    replayed = await sc.buy(ready.id, basis=said["basis"], idempotency_key=key)
    assert replayed["replayed"] is True and len(world.provider.charges) == 1
    # A second card for the same order is refused before anything is staged.
    staged = len(session.proposals)
    text, _ = await _stage(session, shipping_tools.BUY, ready.id)
    assert text.startswith("ERROR: #2145 already has a label bought") and len(session.proposals) == staged


async def test_the_servers_authorisation_decides_and_a_card_says_which_setting(service_code, tmp_path, monkeypatch):
    world = _world(service_code, tmp_path, monkeypatch, buying=False)
    try:
        ready = shipping_service.ready_order(world.s, world)
        session = _session()
        text, proposal = await _stage(session, shipping_tools.BUY, ready.id)
        assert proposal is None and text.startswith("ERROR: Buying isn't authorised for #2145 on the shipping server")
        assert "SHIPPING_AUTHORISED_ORDERS" in text and "SHIPPING_BUYING_ENABLED" in text and "£" in text
        assert world.provider.charges == []
    finally:
        sc.configure(base_url=sc.DEFAULT_BASE_URL)


async def test_a_payment_that_changed_since_the_card_buys_nothing(world):
    ready = shipping_service.ready_order(world.s, world)
    session = _session()
    _, proposal = await _stage(session, shipping_tools.BUY, ready.id)
    world.shopify.fos[ready.fulfillment_order_id].financial_status = "PENDING"
    result = await _approve(world, proposal, hold=True)
    assert result.code in ("refused", "unverified"), result.spoken
    assert "Payment pending" in result.spoken or "payment" in result.spoken.lower(), result.spoken
    assert world.provider.charges == [] and world.store.get(world.shop, ready.id).label is None


async def test_printing_is_the_services_printnode_once_then_a_confirmed_copy(world):
    ready = shipping_service.ready_order(world.s, world)
    session = _session()
    _, buy = await _stage(session, shipping_tools.BUY, ready.id)
    assert (await _approve(world, buy, hold=True)).code == "verified"
    shipping_service.real_label(world.s, world, ready.id)
    charges = list(world.provider.charges)

    # PrintNode is off on this server: the service says so, and nothing was printed.
    session.epoch += 1
    text, first = await _stage(session, shipping_tools.PRINT, ready.id)
    assert text.startswith("PROPOSED") and first.interaction == "swipe_commit"
    refused = await _approve(world, first, hold=False)
    assert refused.code == "refused" and "Label printing (PrintNode) is not switched on" in refused.spoken

    sender = Mock()
    sender.print_pdf.side_effect = range(7000, 7100)
    world.app.state.operations.physical.provider = sender              # PrintNode switched on, on the server
    session.epoch += 1
    _, first = await _stage(session, shipping_tools.PRINT, ready.id)
    result = await _approve(world, first, hold=False)
    assert result.code == "verified", result.spoken
    assert "once PrintNode says the printer has finished" in result.spoken
    assert sender.print_pdf.call_count == 1
    found = (await shipping_tools.shipment_find(shipment_id=ready.id))["shipments"][0]
    assert found["printing"]["label"] == "Printing…" and found["stage"] == "bought", "sent is not printed"

    session.epoch += 1
    text, again = await _stage(session, shipping_tools.PRINT, ready.id)
    assert again is None and "already gone to the printer" in text
    text, copy = await _stage(session, shipping_tools.REPRINT, ready.id)
    assert text.startswith("PROPOSED") and copy.interaction == "swipe_commit"
    assert (await _approve(world, copy, hold=False)).code == "verified"
    assert sender.print_pdf.call_count == 2 and world.provider.charges == charges, "printing never buys"
    assert [e.actor for e in world.store.get(world.shop, ready.id).timeline if e.type == "label_reprinted"] == ["George (CLIVE)"]


async def test_what_changed_and_the_tracking_are_the_services(world):
    ready = shipping_service.ready_order(world.s, world)
    session = _session()
    _, buy = await _stage(session, shipping_tools.BUY, ready.id)
    assert (await _approve(world, buy, hold=True)).code == "verified"
    changed = await shipping_tools.shipping_events(hours=24)
    bought = next(e for e in changed["events"] if e["type"] == "label_purchased")
    assert bought["order_number"] == "#2145" and bought["by"] == "George (CLIVE)" and bought["verified"] is True
    assert bought["what"] == "Label purchased"
    assert changed["events"][0]["at"] >= changed["events"][-1]["at"], "newest first"
    tracked = await shipping_tools.shipment_tracking(order="2145")
    (one,) = tracked["shipments"]
    assert one["label"]["tracking_number"] and one["carrier_view"] is not None
    _no_customer([changed, tracked])


async def test_the_write_key_is_the_only_one_that_acts(world):
    ready = shipping_service.ready_order(world.s, world)
    session = _session()
    _, proposal = await _stage(session, shipping_tools.BUY, ready.id)
    world.keys[sc.WRITE_KEY] = READ
    refused = await _approve(world, proposal, hold=True)
    assert refused.code == "refused" and "took CLIVE's key to read but not to act" in refused.spoken
    assert "Paste SHIPPING_CLIVE_WRITE_KEYS again on Connections. Nothing was changed." in refused.spoken
    assert world.provider.charges == []
