"""CROOKS Returns in CLIVE (app/clients/crooks_returns.py, app/returns/views.py, app/tools/returns_tools.py,
the Connections card, the home's row, the order card and the customer's story).

Every call goes to a stand-in service (tests/returns_stub.py) through an httpx MockTransport: nothing
reaches returns.crooksldn.com, and the keys are fakes assembled at runtime. What is held here, from
the owner's brief (section 6 of the service's BRIEF_CLIVE.md):

- reads are the owner's, carry the read key in the header and never in an address, and say a
  refusal in words;
- a write is a proposal: the card IS the service's preview, its will lines and money as returned;
  a refused preview stages nothing; only his gesture executes, with a fresh idempotency key made
  for that card and actor "clive for George", and the result is verified or the service's error;
- money-moving actions are always his hold, the rest his swipe;
- nothing here calls the customers' portal or anything of Shopify's.
The service's own code is the other half of the proof: tests/test_crooks_returns_contract.py.
"""

from __future__ import annotations

from datetime import timedelta

import httpx
import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.clients import crooks_returns as rc
from app.returns import views
from app.secrets import keychain
from app.session.models import Session
from app.tools import authority, registry, returns_tools
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.returns_stub import NOW, READ, WRITE, StubReturns, iso, ret
from tests.test_actions_routes import client  # noqa: F401 - the app, which `world` stands on
from tests.test_connections_routes import (  # noqa: F401 - `world` is a fixture
    HEADERS,
    PROXIED,
    register,
    save,
    world,
)

BASE = "https://returns.example.com"
RID = "ret_0a1b2c3d4e"


@pytest.fixture()
def keys(monkeypatch):
    held = {rc.READ_KEY: READ, rc.WRITE_KEY: WRITE}
    monkeypatch.setattr(keychain, "get_optional", lambda key: held.get(key))
    return held


@pytest.fixture()
def stub(monkeypatch, keys):
    service = StubReturns([ret(RID, 2131)])
    transport = service.transport()
    monkeypatch.setattr(rc, "http_client", lambda timeout_s: httpx.AsyncClient(transport=transport))
    rc.configure(base_url=BASE)
    rc.forget()
    yield service
    rc.configure(base_url=rc.DEFAULT_BASE_URL)
    rc.forget()


@pytest.fixture()
def engine(monkeypatch):
    e = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


@pytest.fixture()
def session():
    s = Session(session_id="r1")
    s.epoch = 1
    return s


def lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def stage(session, **args):
    session.issue(args.get("return_id", RID))
    text = await dispatch("return_action", {"return_id": RID, **args}, session=session, timeout_s=5)
    return text, (session.proposals[-1] if session.proposals else None)


async def gesture(engine, proposal, *, hold=True):
    nonce = ""
    if hold:
        _, code = engine.arm(proposal.proposal_id, "r1")
        assert code == ""
        proposal.armed_at -= 1.0   # the dwell passes
        nonce = proposal.arm_nonce
    return await engine.commit(proposal.proposal_id, "r1", caller="owner@example.com", spec_lookup=lookup, nonce=nonce)


# ------------------------------------------------------------------ the client


async def test_reads_carry_the_read_key_in_the_header_and_never_in_an_address(stub):
    rows = await rc.list_returns(open_only=True)
    assert [r["id"] for r in rows] == [RID]
    (call,) = stub.calls
    assert call["url"].startswith(f"{BASE}/api/v1/returns?") and call["query"]["open"] == "true"
    assert call["headers"]["authorization"] == f"Bearer {READ}"
    assert READ not in call["url"] and WRITE not in str(stub.calls)


async def test_with_only_the_write_key_stored_reads_carry_it(stub, keys):
    keys.pop(rc.READ_KEY)
    await rc.get_return(RID)
    assert stub.calls[-1]["headers"]["authorization"] == f"Bearer {WRITE}"


async def test_with_no_key_returns_are_not_connected_and_nothing_is_asked(stub, keys):
    keys.clear()
    with pytest.raises(rc.ReturnsUnavailable) as caught:
        await rc.list_returns()
    assert caught.value.kind == "no_key" and "Connections screen" in str(caught.value)
    assert stub.calls == []


@pytest.mark.parametrize("status, kind, words", [
    (403, "rejected", "RETURNS_CLIVE_READ_KEYS"),
    (409, "refused", "Refused by the stub."),
    (429, "rate_limited", "slow down"),
    (503, "trouble", "couldn't reach Shopify"),
    (500, "trouble", "having trouble"),
])
async def test_a_refusal_is_said_in_words(stub, status, kind, words):
    stub.fail["/returns"] = status
    with pytest.raises(rc.ReturnsUnavailable) as caught:
        await rc.list_returns()
    assert caught.value.kind == kind and words in str(caught.value)
    assert READ not in str(caught.value)


async def test_no_answer_is_said_and_never_guessed(stub, monkeypatch):
    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)

    monkeypatch.setattr(rc, "http_client", lambda timeout_s: httpx.AsyncClient(transport=httpx.MockTransport(slow)))
    with pytest.raises(rc.ReturnsUnavailable) as caught:
        await rc.get_return(RID)
    assert caught.value.kind == "timeout" and str(caught.value) == "CROOKS Returns did not answer in time."


def test_a_detail_the_service_wrote_loses_anything_shaped_like_a_customers_detail():
    said = rc.scrub("Parcel2Go answered 400 to /orders: sam@example.com at E1 6AN, phone +44 7700 900123")
    assert "sam@example.com" not in said and "E1 6AN" not in said and "7700" not in said
    assert said.startswith("Parcel2Go answered 400 to /orders:")


def test_money_is_integer_pence_and_shown_as_pounds():
    assert rc.pounds(12550) == "£125.50" and rc.pounds(-300) == "-£3.00" and rc.pounds(5) == "£0.05"
    assert rc.pounds(25.0) == "" and rc.pounds(True) == "" and rc.pounds(None) == ""
    assert rc.pounds(123456789) == "£1,234,567.89"


@pytest.mark.parametrize("said", ["2131", "#2131", "CROOKS-2131", "crooks 2131"])
async def test_an_order_in_any_spelling_is_one_order(stub, said):
    found = await rc.order_returns(said)
    assert [r["id"] for r in found] == [RID]
    assert stub.calls[-1]["path"] == "/api/v1/orders/CROOKS-2131/returns"


async def test_a_return_id_is_checked_before_it_goes_in_an_address(stub):
    for bad in ("../stats", "ret_XYZ", "ret_0a1b/../../x", ""):
        with pytest.raises(rc.ReturnsUnavailable):
            await rc.get_return(bad)
    assert stub.calls == []


async def test_the_open_returns_are_asked_once_a_minute_and_then_by_what_changed(stub, monkeypatch):
    clock = [1000.0]
    held = rc.OpenReturns(clock=lambda: clock[0])
    rows, _ = await held.get()
    assert [r["id"] for r in rows] == [RID] and stub.calls[-1]["query"] == {"limit": "500", "open": "true"}
    await held.get()
    assert len(stub.calls) == 1, "within the minute nothing is asked"
    stub.returns[RID]["status"] = "declined"
    stub.returns[RID]["updated_at"] = iso(NOW + timedelta(minutes=5))
    clock[0] += 61
    rows, _ = await held.get()
    assert stub.calls[-1]["query"] == {"limit": "500", "since": iso(NOW - timedelta(days=1))}, "only what changed since"
    assert held.watermark == iso(NOW + timedelta(minutes=5))
    assert rows == [], "a return no longer open leaves"
    clock[0] += rc.FULL_READ_EVERY_S
    await held.get()
    assert stub.calls[-1]["query"].get("open") == "true", "read whole again every ten minutes"


async def test_an_action_with_no_answer_is_asked_once_more_with_the_same_key(stub, monkeypatch):
    seen: list[dict] = []
    real = stub.transport()

    def flaky(request):
        seen.append(dict(request.headers))
        if len(seen) == 1:
            raise httpx.ConnectError("dropped", request=request)
        return real.handle_request(request)

    monkeypatch.setattr(rc, "http_client", lambda timeout_s: httpx.AsyncClient(transport=httpx.MockTransport(flaky)))
    answer = await rc.execute(RID, "note", {"text": "rang her"}, idempotency_key="clive-note-1")
    assert answer["status"] == "requested" and len(seen) == 2
    assert [c["body"]["idempotency_key"] for c in stub.requests("POST")] == ["clive-note-1"]


# ------------------------------------------------------------------ the reads


def _label_return(rid: str, number: int, *, bought_days: int, stage: str | None = None) -> dict:
    bought = NOW - timedelta(days=bought_days)
    return ret(rid, number, status="awaiting_shipment", resolution="store_credit", days_ago=bought_days + 1,
               postage={"label_ref": "p2g:26633:45693:hash", "label_price_pence": 298, "carrier": "Evri",
                        "service_name": "Evri ParcelShop", "courier_stage": stage, "tracking": "H01ABC"},
               timeline=[{"at": iso(bought), "type": "label_bought", "actor": "staff",
                          "detail": {"service": "Evri ParcelShop", "cost": "£2.98", "ref": "26633"}, "verified": True}])


def test_the_open_returns_put_what_needs_the_owner_first_in_words():
    rows = [ret("ret_000000000a", 2100, status="in_transit", attention=[]),
            ret("ret_000000000b", 2101),
            ret("ret_000000000c", 2102, status="received", attention=["error", "needs_decision"], last_error="Shopify did not process the return: x")]
    view = views.open_view(rows, now=NOW)
    assert [r["return_id"] for r in view["returns"]] == ["ret_000000000c", "ret_000000000b", "ret_000000000a"]
    assert view["returns"][0]["attention_words"] == ["has an error", "needs a decision"]
    assert view["needs_you"] == 2 and view["counts"] == {"error": 1, "needs_decision": 1, "needs_approval": 1}
    assert view["returns"][1]["money"] == [{"key": "items_pence", "label": "Items", "pence": 2500, "shown": "£25.00"},
                                           {"key": "refund_pence", "label": "Refund", "pence": 2500, "shown": "£25.00"}]
    assert "customer_email" not in str(view) and "sam@example.com" not in str(view)


def test_a_label_paid_for_and_never_posted_after_fourteen_days_is_to_cancel():
    rows = [_label_return("ret_00000000aa", 2110, bought_days=15), _label_return("ret_00000000bb", 2111, bought_days=10),
            _label_return("ret_00000000cc", 2112, bought_days=20, stage="DroppedOff")]
    (unused,) = views.unused_labels(rows, now=NOW)
    assert unused["return_id"] == "ret_00000000aa" and unused["days"] == 15
    assert unused["parcel2go_order"] == "26633" and unused["paid"] == "£2.98" and "hash" not in str(unused)
    assert views.brief(rows, now=NOW)["words"] == "1 unused label to cancel"


@pytest.mark.usefixtures("owner_asking")
async def test_where_is_my_return_is_answered_from_status_tracking_and_timeline(stub, session):
    stub.returns[RID] = _label_return(RID, 2131, bought_days=2, stage="DroppedOff") | {"status": "in_transit", "attention": []}
    stub.returns[RID]["postage"]["tracking_url"] = "https://www.evri.com/track/H01ABC"
    text = await dispatch("return_find", {"order": "#2131"}, session=session, timeout_s=5)
    assert text.startswith("AMBER") and RID in text
    found = await returns_tools.return_find(order="CROOKS-2131")
    (one,) = found["returns"]
    assert one["where"] == "#2131 is on its way back; last: label bought on 1 Oct; tracking H01ABC with Evri; the courier last said DroppedOff."
    assert one["postage"]["tracking_url"] == "https://www.evri.com/track/H01ABC"
    assert RID in session.issued_ids, "the return a read showed is one a write may act on"


def test_a_product_that_keeps_coming_back_too_small_is_a_size_chart_finding():
    small = {"title": "Docket Tee", "variant_title": "S", "sku": "TEE-S", "quantity": 1, "reason": "too_small",
             "unit_paid_pence": 2500, "exchange_direction": "size_up", "exchange_variant_title": "M"}
    rows = [ret(f"ret_00000001{i}0", 2120 + i, resolution="exchange", lines=[small]) for i in range(3)]
    rows.append(ret("ret_0000000200", 2130, lines=[{**small, "title": "Yard Jeans", "reason": "faulty", "exchange_direction": None}]))
    view = views.stats_view({"returns": 4, "kept_share": 0.75, "by_reason": {"too_small": 3, "faulty": 1}}, rows, days=30, since="x")
    (finding,) = view["findings"]
    assert finding.startswith("Docket Tee: 3 came back too small (3 swapped a size up): check its size chart")
    assert view["kept_share"] == "75%" and view["reasons"][0] == {"reason": "too small", "count": 3}


async def test_the_reads_are_the_owners_alone(stub, session):
    from app.people import staff

    assert {"returns_open", "return_find", "returns_stats"} <= __import__("app.tools.gate", fromlist=["x"])._KNOWN_TOOLS
    assert not set(returns_tools.TOOLS) & staff.TOOLS and not set(returns_tools.TOOLS) & authority.SERVICE_READS
    member = authority.for_staff("person_1", "mia@example.com")
    with authority.acting_as(member):
        text = await dispatch("returns_open", {}, session=session, timeout_s=5)
    assert text.startswith("REFUSED") and stub.calls == []
    assert not staff.may_commit("return_action")


# ------------------------------------------------------------------ the write


@pytest.mark.usefixtures("owner_asking")
async def test_the_card_is_the_services_preview_exactly_and_nothing_is_sent(stub, engine, session):
    text, proposal = await stage(session, action="approve", postage_mode="label_now")
    assert text.startswith("PROPOSED") and "holding the card and then tapping it applies it" in text
    assert [(c["method"], c["path"]) for c in stub.calls] == [
        ("GET", f"/api/v1/returns/{RID}"), ("POST", f"/api/v1/returns/{RID}/actions/approve/preview")]
    assert stub.calls[-1]["body"] == {"params": {"postage_mode": "label_now"}}
    assert stub.calls[-1]["headers"]["authorization"] == f"Bearer {READ}", "a preview changes nothing: the read key"
    words = registry.get("return_action").write.present(proposal)
    assert words["body"] == ("Create Shopify return on CROOKS-2131 for: CROOKS-2131: 1x Docket Tee (M) [Too small]; refund £25.00.\n"
                             "Book Evri (Evri ParcelShop) for £2.98 from Parcel2Go PrePay, balance £50.00. The customer gets "
                             "the label by email and a QR code on the returns page.")
    assert {"label": "Refund", "value": "£25.00", "tone": "bad"} in words["facts"]
    assert words["title"] == "Approve the return · label bought now" and words["done_title"] == "Return approved"
    assert proposal.risk == "RED" and proposal.interaction == "hold_to_arm" and proposal.status is ActionStatus.PENDING


@pytest.mark.parametrize("status, args, gesture_kind", [
    ("requested", {"action": "approve", "postage_mode": "label_now"}, "hold_to_arm"),
    ("requested", {"action": "approve", "postage_mode": "no_return"}, "hold_to_arm"),
    ("requested", {"action": "approve", "postage_mode": "self_ship"}, "swipe_commit"),
    ("requested", {"action": "approve", "postage_mode": "label_later"}, "swipe_commit"),
    ("awaiting_label", {"action": "label"}, "hold_to_arm"),
    ("awaiting_label", {"action": "label", "tracking": "RM123456789GB"}, "swipe_commit"),
    ("in_transit", {"action": "receive"}, "hold_to_arm"),
    ("in_transit", {"action": "receive", "condition": "ok"}, "hold_to_arm"),
    ("in_transit", {"action": "receive", "condition": "damaged"}, "swipe_commit"),
    ("received", {"action": "complete"}, "hold_to_arm"),
    ("requested", {"action": "decline", "reason": "outside the window"}, "swipe_commit"),
    ("requested", {"action": "cancel"}, "swipe_commit"),
    ("awaiting_shipment", {"action": "tracking", "tracking": "rm 1234 5678"}, "swipe_commit"),
    ("in_transit", {"action": "note", "text": "rang her"}, "swipe_commit"),
])
@pytest.mark.usefixtures("owner_asking")
async def test_moving_money_is_always_the_hold_and_the_rest_the_owners_swipe(stub, engine, session, status, args, gesture_kind):
    stub.returns[RID]["status"] = status
    text, proposal = await stage(session, **args)
    assert text.startswith("PROPOSED"), text
    assert proposal.interaction == gesture_kind and proposal.risk == ("RED" if gesture_kind == "hold_to_arm" else "AMBER")
    assert not stub.requests("POST", f"/actions/{args['action']}"), "staging never executes"


@pytest.mark.usefixtures("owner_asking")
async def test_a_default_the_service_has_is_written_out_so_execute_means_what_the_card_said(stub, engine, session):
    _, approve = await stage(session, action="approve")
    assert dict(approve.execution)["params"] == {"postage_mode": "label_now"}, "the customer chose a free label"
    stub.returns[RID]["postage"]["chosen"] = "self_ship"
    session.epoch += 1
    _, posted = await stage(session, action="approve")
    assert dict(posted.execution)["params"] == {"postage_mode": "self_ship"}
    stub.returns[RID]["status"] = "in_transit"
    _, receive = await stage(session, action="receive")
    assert dict(receive.execution)["params"] == {"condition": "ok", "restock": True}


@pytest.mark.usefixtures("owner_asking")
async def test_a_refused_preview_is_said_and_nothing_is_staged(stub, engine, session):
    stub.returns[RID]["status"] = "completed"
    text, proposal = await stage(session, action="approve", postage_mode="self_ship")
    assert text == ("ERROR: This return is completed; that needs requested. Say that this could not be prepared. "
                    "Nothing was changed.")
    assert proposal is None and not stub.requests("POST", "/actions/approve")


@pytest.mark.usefixtures("owner_asking")
async def test_only_the_owners_hold_executes_with_a_fresh_key_and_his_name(stub, engine, session):
    _, proposal = await stage(session, action="approve", postage_mode="label_now")
    refused = await gesture(engine, proposal, hold=False)
    assert refused.code == "not_armed" and not stub.requests("POST", "/actions/approve")
    result = await gesture(engine, proposal)
    (sent,) = stub.requests("POST", "/actions/approve")
    assert sent["headers"]["authorization"] == f"Bearer {WRITE}"
    assert sent["body"]["actor"] == "clive for George" and sent["body"]["params"] == {"postage_mode": "label_now"}
    assert sent["body"]["idempotency_key"].startswith("clive-approve-")
    assert result.code == "verified" and proposal.status is ActionStatus.VERIFIED
    assert result.spoken == ("Done, on the return for order 2131. It is now approved, waiting for the customer to post it. "
                             "Read back from Shopify.")
    # Another card for the same return is another key: never the first one again.
    stub.returns[RID]["status"] = "requested"
    session.epoch += 1
    _, again = await stage(session, action="decline", reason="duplicate")
    assert dict(again.execution)["idempotency_key"] != sent["body"]["idempotency_key"]


@pytest.mark.usefixtures("owner_asking")
async def test_an_error_the_service_reported_is_said_in_its_words(stub, engine, session):
    stub.returns[RID]["status"] = "received"
    stub.error_on = "complete"
    _, proposal = await stage(session, action="complete")
    result = await gesture(engine, proposal)
    assert result.code == "unverified" and proposal.status is ActionStatus.UNVERIFIED
    assert result.spoken == ("CROOKS Returns didn't confirm that. CROOKS Returns recorded it, but part of it failed: "
                             "Shopify did not process the return: refused (test)")
    from app.presentation import present_action

    (card,) = present_action(result)
    assert card["type"] == "error" and card["data"]["service"] == "returns"
    assert "Shopify did not process the return" in card["data"]["recovery"]


@pytest.mark.usefixtures("owner_asking")
async def test_a_refused_execute_says_who_refused_and_that_nothing_changed(stub, engine, session):
    _, proposal = await stage(session, action="note", text="rang her")
    stub.fail["/actions/note"] = 409
    result = await gesture(engine, proposal, hold=False)
    assert result.code == "refused" and result.spoken == "CROOKS Returns refused that: Refused by the stub. Nothing was changed."
    from app.presentation import present_action

    (card,) = present_action(result)
    assert card["data"]["recovery"] == "CROOKS Returns refused it: Refused by the stub. Nothing was changed."


@pytest.mark.usefixtures("owner_asking")
async def test_a_return_that_moved_since_the_card_is_not_touched(stub, engine, session):
    _, proposal = await stage(session, action="decline", reason="outside the window")
    stub.returns[RID]["status"] = "cancelled"
    result = await gesture(engine, proposal, hold=False)
    assert result.code == "stale" and not stub.requests("POST", "/actions/decline")


@pytest.mark.usefixtures("owner_asking")
async def test_a_write_key_the_service_refuses_asks_for_the_write_key_alone(stub, engine, session, monkeypatch):
    from app.connections import ledger

    recorded = {}
    monkeypatch.setattr(ledger, "tested", lambda name, outcome: recorded.update({name: outcome}))
    stub.write_keys = set()
    _, proposal = await stage(session, action="note", text="rang her")
    result = await gesture(engine, proposal, hold=False)
    assert result.code == "refused" and "refused CLIVE's write key" in result.spoken
    assert recorded["returns"]["refused"] == [rc.WRITE_KEY] and recorded["returns"]["fix"] == "key"


def test_the_write_is_declared_completely_and_nothing_reaches_the_portal_or_shopify():
    spec = registry.get("return_action")
    assert spec.write.complete and spec.tier is Tier.AMBER and spec.write.kind == "irreversible"
    assert spec.issued_id_args == ("return_id",) and spec.write.service == "CROOKS Returns"
    assert classify("return_action", {"return_id": RID, "action": "note"}, issued_ids={RID}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify("return_action", {"return_id": RID, "action": "note"}).disposition is Disposition.DENY
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for path in ("app/clients/crooks_returns.py", "app/tools/returns_tools.py", "app/returns/views.py"):
        source = (root / path).read_text()
        assert "/proxy/api" not in source.replace("(/proxy/api/*)", "") and "shopify_writes" not in source
        assert "returnCreate" not in source and "returnProcess" not in source and "sqlite" not in source.lower()


# ------------------------------------------------------------------ the order card and the story


async def test_the_order_card_carries_its_returns_for_the_owner_alone(stub):
    from app.tools import shopify_tools

    order = {"order_id": "gid://shopify/Order/2131", "order_number": "CROOKS-2131"}
    with authority.acting_as(authority.for_owner("owner@example.com")):
        shown = await shopify_tools._with_returns(order)
    assert shown["returns"][0]["status_words"] == "waiting for your approval" and "returns" not in order
    with authority.acting_as(authority.for_staff("person_1", "mia@example.com")):
        assert "returns" not in await shopify_tools._with_returns(order)
    from app.presentation import _order

    card = _order(shown, detail=True)
    assert card["returns"][0]["money"][1] == {"label": "Refund", "shown": "£25.00"}
    assert card["returns"][0]["attention_words"] == ["to approve"]


def test_the_customers_story_has_their_returns_when_the_owner_asks():
    from app.customers import history

    told = {"recent": [{"order_id": "gid://shopify/Order/2131", "order_number": "CROOKS-2131", "placed_at": iso(NOW - timedelta(days=9))}],
            "orders": 1, "customer_id": "gid://shopify/Customer/77"}
    moving = ret(RID, 2131, status="in_transit", attention=[], days_ago=3)
    moving["timeline"].append({"at": iso(NOW - timedelta(hours=2)), "type": "in_transit", "actor": "Parcel2Go",
                               "detail": {"stage": "DroppedOff"}, "verified": True})
    found = ([moving], "1 return")
    story = history.timeline(told, None, owner=True, returns=found)
    rows = [r for r in story["rows"] if r["source"] == "Returns"]
    assert [r["what"] for r in rows] == ["Return on #2131: on its way back", "Asked to return #2131"]
    assert story["sources"]["CROOKS Returns"] == "1 return"
    assert not [r for r in history.timeline(told, None, owner=False, returns=found)["rows"] if r["source"] == "Returns"]


# ------------------------------------------------------------------ the Connections card and the home


@pytest.fixture()
async def connected(world, monkeypatch):  # noqa: F811 - `world` is the Connections suite's fixture
    from app.connections import testers

    service = StubReturns([ret(RID, 2131), ret("ret_0a1b2c3d4f", 2132, status="received", attention=["needs_decision"])])
    transport = service.transport()
    monkeypatch.setattr(testers, "http_client", lambda: httpx.AsyncClient(transport=transport))
    monkeypatch.setattr(rc, "http_client", lambda timeout_s: httpx.AsyncClient(transport=transport))
    rc.forget()
    world.returns = service
    yield world
    rc.forget()


async def _card(http):
    answer = await http.get("/connections/state", headers=PROXIED)
    return next(c for c in answer.json()["connections"] if c["name"] == "returns")


async def test_the_card_asks_for_both_keys_tests_them_and_then_asks_for_nothing(connected):
    card = await _card(connected)
    assert (card["label"], card["state"], card["needs"]) == ("CROOKS Returns", "not_connected", [rc.READ_KEY, rc.WRITE_KEY])
    assert all("grep CLIVE /opt/clive/crooks-returns/.env" in f["hint"] or "Same command" in f["hint"] for f in card["fields"])
    assert card["without"].startswith("Without it") and [u["label"] for u in card["unlocks"]] == [
        "Reading returns", "Acting on returns"]
    await register(connected)
    saved = await save(connected, "returns", {rc.READ_KEY: f"RETURNS_CLIVE_READ_KEYS={READ},older", rc.WRITE_KEY: WRITE})
    assert saved.status_code == 200, saved.text
    asked = [(c["method"], c["path"], c["headers"].get("authorization", "")) for c in connected.returns.calls]
    assert asked == [("GET", "/health", ""), ("GET", "/api/v1/returns", f"Bearer {READ}"), ("GET", "/api/v1/returns", f"Bearer {WRITE}")]
    assert keychain.get_optional(rc.READ_KEY) == READ, "a line pasted as grep printed it is its value"
    card = await _card(connected)
    assert (card["state"], card["group"], card["needs"]) == ("connected", "working", [])
    assert READ not in str(card) and WRITE not in str(card)


async def test_a_refused_write_key_is_asked_for_alone(connected):
    await register(connected)
    assert (await save(connected, "returns", {rc.READ_KEY: READ, rc.WRITE_KEY: WRITE})).status_code == 200
    connected.returns.read_keys = {READ}
    tested = await connected.post("/connections/returns/test", json={}, headers=HEADERS)
    assert tested.status_code == 200
    card = await _card(connected)
    assert (card["state"], card["fix"], card["needs"]) == ("needs_attention", "key", [rc.WRITE_KEY])
    assert card["detail"].startswith("The write key was refused by CROOKS Returns.")


async def test_a_service_with_no_keys_for_clive_is_put_right_there_and_nothing_is_stored(connected):
    await register(connected)
    connected.returns.health_keys = False
    saved = await save(connected, "returns", {rc.READ_KEY: READ, rc.WRITE_KEY: WRITE})
    assert saved.status_code == 422 and "RETURNS_CLIVE_READ_KEYS" in saved.json()["detail"]
    assert keychain.get_optional(rc.READ_KEY) is None


async def test_the_home_says_how_many_returns_need_the_owner_and_never_who(connected):
    empty = (await connected.get("/returns/brief", headers=PROXIED)).json()
    assert empty == {"ok": True, "connected": False, "needs": 0, "words": "", "open": 0, "unused_labels": 0}
    await register(connected)
    await save(connected, "returns", {rc.READ_KEY: READ, rc.WRITE_KEY: WRITE})
    connected.returns.calls.clear()
    said = (await connected.get("/returns/brief", headers=PROXIED)).json()
    assert (said["needs"], said["open"], said["words"]) == (2, 2, "1 needs a decision · 1 to approve")
    assert "Sam Taylor" not in str(said)
    await connected.get("/returns/brief", headers=PROXIED)
    assert len(connected.returns.calls) == 1, "asked once a minute, however often the home is drawn"
    assert (await connected.get("/returns/brief")).status_code == 403, "the owner's alone"
