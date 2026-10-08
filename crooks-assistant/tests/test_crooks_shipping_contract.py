"""CLIVE's CLIVE Shipping client and tools against the service's OWN code, offline: the true contract.

The shipping service is George's (branch claude/n2-service-fixes, folder clive-shipping/); nothing
of it is copied into CLIVE. This test takes that folder from the repository's history at one pinned
commit (tests/shipping_service.py SERVICE_SHA, 36881977, the reviewed commit to deploy) and runs its
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

import re
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


def _answers_lost(world, monkeypatch, ending: str, first) -> None:
    """Every POST to …{ending} loses its answer, both CLIVE's request and the one asked again with
    the same key; `first(transport, request)` runs before the first is lost (the request landing,
    or the Shipping screen acting instead of it)."""
    calls: list[str] = []

    class Losing(httpx.ASGITransport):
        async def handle_async_request(self, request):
            if request.method == "POST" and request.url.path.endswith(ending):
                calls.append(request.url.path)
                await first(self, request, len(calls))
                raise httpx.ReadTimeout("the answer was lost on the way back", request=request)
            return await super().handle_async_request(request)

    monkeypatch.setattr(sc, "http_client", lambda timeout_s: httpx.AsyncClient(
        transport=Losing(app=world.reached), timeout=timeout_s))


@pytest.mark.parametrize("whose", ["clive", "the Shipping screen"])
@pytest.mark.parametrize("tool", [shipping_tools.BUY, shipping_tools.PRINT])
async def test_a_lost_answer_is_clives_only_when_the_orders_history_says_so(world, monkeypatch, tool, whose):
    """Both answers lost, and the order re-read shows a label (or a print): it is CLIVE's, and said as
    done, only when the order's newest entry of that kind is by "George (CLIVE)". The Shipping screen
    acting meanwhile, as George himself, is not CLIVE's change: unverified, and George is told to look."""
    ready = shipping_service.ready_order(world.s, world)
    session = _session()
    sender = Mock()
    sender.print_pdf.side_effect = range(7000, 7100)
    if tool == shipping_tools.PRINT:
        _, buy = await _stage(session, shipping_tools.BUY, ready.id)
        assert (await _approve(world, buy, hold=True)).code == "verified"
        shipping_service.real_label(world.s, world, ready.id)
        world.app.state.operations.physical.provider = sender
        session.epoch += 1
    _, proposal = await _stage(session, tool, ready.id)
    basis = dict(proposal.execution).get("basis")

    async def first(transport, request, n):
        if whose == "clive":
            await httpx.ASGITransport.handle_async_request(transport, request)   # it lands; its answer is lost
        elif n == 1 and tool == shipping_tools.BUY:
            world.svc.buy(world.shop, ready.id, basis, "George", "shipping-screen-buy")
        elif n == 1:
            world.app.state.operations.physical.print_label(world.shop, ready.id, "George", "shipping-screen-print")

    _answers_lost(world, monkeypatch, "/buy" if tool == shipping_tools.BUY else "/print", first)
    result = await _approve(world, proposal, hold=tool == shipping_tools.BUY)
    what = "label" if tool == shipping_tools.BUY else "print"
    if whose == "clive":
        assert result.code == "verified", result.spoken
        assert f"the order's history shows the {what} as CLIVE's" in result.spoken
    else:
        assert result.code == "unverified", result.spoken
        assert f"CLIVE lost CLIVE Shipping's answer and can't see the {what} as CLIVE's on the order" in result.spoken
        assert "Label bought" not in result.spoken and "Sent the label" not in result.spoken
    assert len(world.provider.charges) == 1 and sender.print_pdf.call_count == (tool == shipping_tools.PRINT)


def test_clive_waits_for_a_print_longer_than_the_service_waits_on_printnode(service_code):
    """The service's print asks PrintNode twice in turn (the printer, then the job), each with its own
    wait. CLIVE's wait covers both and the label's own work after them, so a slow print that works is
    answered rather than asked again while it is still being sent."""
    import importlib

    printnode = importlib.import_module("shipping.print_provider").PrintNodeProvider("not-a-key", 1)
    try:
        each = printnode._client.timeout.read
    finally:
        printnode._client.close()
    assert each and sc.PRINT_TIMEOUT_S >= max(45.0, 2 * each + 10), (each, sc.PRINT_TIMEOUT_S)


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


# A tracking number is the customer's parcel: shaped like Royal Mail's, Parcelforce's or the
# service's fake courier's (…GB), UPS's (1Z…) or Yodel's and DHL Parcel's (JD…).
TRACKING_SHAPED = re.compile(r"\b(?:[A-Z]{1,2}\d[0-9A-Z]{4,12}GB|1Z[0-9A-Z]{16}|JD\d{16,18})\b")


async def test_no_tracking_number_reaches_the_action_ledger_or_the_timeline(world, tmp_path):
    """The ledger (actions.jsonl) and the timeline (exported, handed to engineering agents) carry
    whether a label has its tracking number, never the number: through a buy, its proof and what is
    said, a first print, a copy, and a second buy refused at staging. George still sees the number
    on the order's card."""
    from app.actions import ledger as ledger_module
    from app.actions.ledger import ActionLedger
    from app.observability import hooks
    from app.observability import timeline as timeline_module
    from app.observability.session import TestSessions
    from app.observability.timeline import Timeline

    world.engine.ledger = ledger = ActionLedger(tmp_path / "logs")
    sessions = TestSessions(tmp_path / "logs")
    recording, was = Timeline(sessions), timeline_module.current()
    observed_already = hooks.ledger_observer in ledger_module._observers
    timeline_module.install(recording)
    ledger_module.observe(hooks.ledger_observer)
    try:
        test_session = recording.start("tracking numbers")
        ready = shipping_service.ready_order(world.s, world)
        session = _session()
        _, buy = await _stage(session, shipping_tools.BUY, ready.id)
        bought = await _approve(world, buy, hold=True)
        assert bought.code == "verified", bought.spoken
        shipping_service.real_label(world.s, world, ready.id)
        sender = Mock()
        sender.print_pdf.side_effect = range(7000, 7100)
        world.app.state.operations.physical.provider = sender
        said = [bought.spoken]
        for tool in (shipping_tools.PRINT, shipping_tools.REPRINT):
            session.epoch += 1
            _, card = await _stage(session, tool, ready.id)
            printed = await _approve(world, card, hold=False)
            assert printed.code == "verified", printed.spoken
            said.append(printed.spoken)
        session.epoch += 1
        text, again = await _stage(session, shipping_tools.BUY, ready.id)
        assert again is None and text.startswith("ERROR: #2145 already has a label bought")
        said.append(text)
        assert recording.flush()
        written = sessions.timeline_path(test_session).read_text()
    finally:
        if not observed_already:
            ledger_module.unobserve(hooks.ledger_observer)
        recording.stop()
        timeline_module.install(was)
    number = world.store.get(world.shop, ready.id).label.tracking_number
    assert number and TRACKING_SHAPED.fullmatch(number), "the shapes would see this courier's number"
    assert bought.proposal.entity["label"]["tracking_number"] == number, "the order's card still shows it"
    kept = ledger.path.read_text()
    assert '"event": "VERIFIED"' in kept and '"action_verified"' in written, "both records were written"
    for where, text in (("actions.jsonl", kept), ("the timeline", written), ("what CLIVE said", " ".join(said))):
        assert number not in text and not TRACKING_SHAPED.search(text), f"a tracking number reached {where}"
    assert '"tracking": true' in kept, "the ledger says the number is in, not what it is"


async def test_the_write_key_is_the_only_one_that_acts(world):
    ready = shipping_service.ready_order(world.s, world)
    session = _session()
    _, proposal = await _stage(session, shipping_tools.BUY, ready.id)
    world.keys[sc.WRITE_KEY] = READ
    refused = await _approve(world, proposal, hold=True)
    assert refused.code == "refused" and "took CLIVE's key to read but not to act" in refused.spoken
    assert "Paste SHIPPING_CLIVE_WRITE_KEYS again on Connections. Nothing was changed." in refused.spoken
    assert world.provider.charges == []
