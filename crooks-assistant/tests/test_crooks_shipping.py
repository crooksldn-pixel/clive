"""CLIVE Shipping in CLIVE (app/clients/crooks_shipping.py, app/tools/shipping_views.py,
app/tools/shipping_tools.py, the Connections card, the "shipping" card).

Every call here goes to a stand-in through an httpx MockTransport: nothing reaches
returns.crooksldn.com, and the keys are fakes assembled at runtime. The service's own code is the
other half of the proof (tests/test_crooks_shipping_contract.py). What is held here:

- exactly three shipping changes exist, each staged for the owner's gesture and sent only to the
  service (never Shopify, never PrintNode), and CLIVE holds no PrintNode key of its own;
- the reads are allowed reads (GREEN, the owner's alone), the changes need an issued shipment id;
- the read key alone reads, in a header, never in an address; no key is no request; a buy whose
  answer was lost is asked again with the SAME key; the server's buying authorisation is a
  refusal, not a bad key;
- without keys the model is told once why shipping is unavailable, and the parked Easyship row
  stops saying labels are disconnected once CLIVE Shipping is;
- the Connections card asks for the two keys by their server settings' names and tests the read
  key with a read that changes nothing;
- what the service wrote is scrubbed of anything shaped like a customer's detail, and what it
  filled in (a tracking number, a date) is kept as it is.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from app.clients import crooks_shipping as sc
from app.secrets import keychain
from app.tools import gate, shipping_tools, shipping_views
from tests.fake_credentials import bearer_token

READ = bearer_token("shipping-unit-read", length=32)
WRITE = bearer_token("shipping-unit-write", length=32)
SID = "shp_0a1b2c3d4e5f"
# A card's idempotency key, in plain words: a hex one reads to the secret scanner as a key.
CARD = "clive-buy-this-one-card"
ROOT = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.usefixtures("owner_asking")


@pytest.fixture()
def keys(monkeypatch):
    held = {sc.READ_KEY: READ, sc.WRITE_KEY: WRITE}
    monkeypatch.setattr(keychain, "get_optional", lambda key: held.get(key))
    return held


def answering(monkeypatch, handler):
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(sc, "http_client", lambda timeout_s: httpx.AsyncClient(transport=httpx.MockTransport(record)))
    sc.configure(base_url="https://returns.example.com/shipping")
    return seen


@pytest.fixture(autouse=True)
def _base_back():
    yield
    sc.configure(base_url=sc.DEFAULT_BASE_URL)


def summary(**over):
    row = {"id": SID, "order": "CROOKS-2142", "order_id": "gid://shopify/Order/2142", "country": "GG", "stage": "ready",
           "status": "Ready", "reasons": [], "payment": "Paid", "service": "Parcel2Go · Parcelforce", "price": "£11.79",
           "tracking_number": None, "print": None, "carrier": None, "updated_at": "2026-10-07T09:00:00+00:00"}
    return row | over


# ------------------------------------------------------------------ the guard


def test_exactly_three_shipping_changes_exist_each_sent_only_to_the_service():
    """The check that fails if a shipping change is added without being named here: the label bought,
    printed, printed again, each a complete write sent to CLIVE Shipping's own API ("shipping:"), each
    staged for the owner's gesture. Nothing else registered buys, prints, voids or fulfils a label:
    the tool modules' writes and the families' (app/families/*, checkout links, discount codes, draft
    orders, store credit among them), loaded first as tests/test_registry.py loads them, so this holds
    run alone as in the whole suite."""
    import app.tools.batch_tools  # noqa: F401
    import app.tools.gmail_writes  # noqa: F401
    import app.tools.returns_tools  # noqa: F401
    import app.tools.shopify_writes  # noqa: F401
    from app.families import load_all
    from app.tools import registry

    load_all()
    specs = registry.all_specs()
    family_writes = {"checkout_link_send", "discount_code_create", "draft_order_complete", "store_credit_credit"}
    assert family_writes <= {s.write.operation for s in specs if s.write is not None}, "the families' writes are in"
    shipping = sorted(s.write.operation for s in specs if s.write is not None and s.write.mutation.startswith("shipping:"))
    assert shipping == ["shipping_label_buy", "shipping_label_print", "shipping_label_reprint"]
    assert {s.write.operation: s.write.mutation for s in specs if s.write is not None and s.write.mutation.startswith("shipping:")} == {
        "shipping_label_buy": "shipping:buy", "shipping_label_print": "shipping:print", "shipping_label_reprint": "shipping:reprint"}
    operations = {s.write.operation for s in specs if s.write is not None} | {s.batch.operation for s in specs if s.batch is not None}
    expected = {"label": shipping, "print": ["shipping_label_print", "shipping_label_reprint"],
                "shipment": [], "postage": [], "void": [], "courier": []}
    for word, ops in expected.items():
        assert sorted(op for op in operations if word in op) == ops, word
    assert sorted(op for op in operations if op.startswith("shipping")) == shipping
    for name in shipping:
        write = registry.get(name).write
        assert write.complete and write.service == sc.NAME and write.says_failure and write.entity_kind == "shipment"
        assert registry.get(name).issued_id_args == ("shipment_id",)
    assert registry.get("shipping_label_buy").write.op_class == "money", "buying moves money: the owner's hold"
    assert sorted(s.name for s in specs if s.name.startswith(("shipment", "shipping_"))) == sorted(shipping_tools.TOOLS)
    # Nor through Shopify: no reviewed Shopify mutation's document buys or prints a label, or books postage.
    from app.clients.shopify import REVIEWED_MUTATIONS

    words = ("label", "print", "postage", "parcel")
    assert not [name for name, reviewed in REVIEWED_MUTATIONS.items()
                if any(word in reviewed.document.lower() for word in words)], "a Shopify label mutation is reviewed"


def test_clive_holds_no_printnode_key_printing_is_the_services():
    from app.connections import catalog
    from app.secrets import linux_store

    assert not [k for k in keychain.KNOWN_KEYS if "printnode" in k.lower()]
    assert not [k for k in linux_store.STATIC_KEYS if "printnode" in k.lower()]
    assert not [f.key for c in catalog.CONNECTIONS for f in c.fields if "printnode" in f.key.lower()]
    source = (ROOT / "app" / "clients" / "crooks_shipping.py").read_text()
    assert "api.printnode.com" not in source and "PRINTNODE_API_KEY" in source, "named only as the service's own"


def test_the_reads_are_allowed_reads_and_the_changes_need_an_issued_shipment():
    for name in shipping_tools.READS:
        assert name in gate._KNOWN_TOOLS and not gate._looks_like_mutation(name)
        decision = gate.classify(name, {})
        assert decision.executes and decision.tier is gate.Tier.GREEN, name
    for name in shipping_tools.WRITES:
        assert name not in gate._KNOWN_TOOLS
        assert not gate.classify(name, {"shipment_id": SID}).allowed, "an id this session was not shown is refused"
        decision = gate.classify(name, {"shipment_id": SID}, issued_ids=[SID])
        assert decision.stages and decision.tier is gate.Tier.AMBER, name
        assert not gate.classify(name, {"shipment_id": "ret_0a1b2c3d4e"}, issued_ids=["ret_0a1b2c3d4e"]).allowed


def test_the_team_and_background_work_never_reach_shipping():
    from app.people import staff
    from app.tools import authority

    assert not set(shipping_tools.TOOLS) & set(staff.TOOLS)
    assert not set(shipping_tools.TOOLS) & set(authority.SERVICE_READS)


# ------------------------------------------------------------------ the client


async def test_no_key_is_no_request(monkeypatch):
    monkeypatch.setattr(keychain, "get_optional", lambda key: None)
    seen = answering(monkeypatch, lambda r: httpx.Response(200, json={}))
    with pytest.raises(sc.ShippingUnavailable) as no:
        await sc.list_shipments()
    assert no.value.kind == "no_key" and "Connections screen" in str(no.value) and seen == []
    with pytest.raises(sc.ShippingUnavailable) as no_write:
        await sc.buy(SID, basis="b1", idempotency_key="clive-buy-0000000000000000")
    assert no_write.value.kind == "no_key" and seen == []


async def test_the_read_key_alone_reads_in_a_header_never_an_address(monkeypatch, keys):
    seen = answering(monkeypatch, lambda r: httpx.Response(200, json={"stage": "all", "shipments": [summary()]}))
    rows = await sc.list_shipments(stage="all")
    assert rows[0]["id"] == SID
    (request,) = seen
    assert request.headers["authorization"] == f"Bearer {READ}" and READ not in str(request.url)
    assert str(request.url).startswith("https://returns.example.com/shipping/api/v1/shipments?")
    assert WRITE not in str(request.headers)


def test_the_address_is_https_or_the_services_own():
    assert sc.clean_base("http://returns.crooksldn.com/shipping") == sc.DEFAULT_BASE_URL
    assert sc.clean_base("returns.crooksldn.com") == sc.DEFAULT_BASE_URL
    assert sc.clean_base("https://example.com/shipping/") == "https://example.com/shipping"
    # The contract's own way of naming it (CLIVE_OPERATIONS.md "Base"): the same service, never /api/v1 twice.
    assert sc.clean_base("https://returns.crooksldn.com/shipping/api/v1/") == sc.DEFAULT_BASE_URL
    assert sc.DEFAULT_BASE_URL == "https://returns.crooksldn.com/shipping"


async def test_a_buy_whose_answer_was_lost_is_asked_again_with_the_same_key(monkeypatch, keys):
    calls = []

    def handler(request):
        calls.append(request.read())
        if len(calls) == 1:
            raise httpx.ReadTimeout("lost", request=request)
        return httpx.Response(200, json={"charged": True, "replayed": True, "status": "fulfilled", "shipment": {}})

    seen = answering(monkeypatch, handler)
    answer = await sc.buy(SID, basis="b1_abc", idempotency_key=CARD)
    assert answer["replayed"] is True and len(calls) == 2 and calls[0] == calls[1], "the same request, the same key"
    assert all(r.headers["authorization"] == f"Bearer {WRITE}" for r in seen)
    assert f'"idempotency_key":"{CARD}"'.encode() in calls[0].replace(b" ", b"")
    assert b'"actor":"George"' in calls[0].replace(b" ", b"")


@pytest.mark.parametrize("status, detail, kind, says", [
    (403, {"message": "Buying the label for CROOKS-2142 isn't authorised yet. Nothing was bought.", "code": "not_authorised"},
     "refused", "isn't authorised yet"),
    (403, {"message": "This key cannot act on shipping.", "code": "forbidden"}, "rejected", "took CLIVE's key to read but not to act"),
    (409, {"message": "This order changed since you saw the price. Nothing was bought.", "code": "stale"}, "refused", "changed since"),
    (409, {"message": "Label printing (PrintNode) is not switched on.", "code": "printing_disabled"}, "refused",
     "is not switched on. Set PRINTNODE_* in clive-shipping/.env on the server."),
    (503, {"message": "Shopify didn't answer just now.", "code": "shopify_unavailable"}, "trouble", "Shopify didn't answer"),
])
async def test_each_refusal_is_said_in_the_services_words_and_a_bad_key_is_named(monkeypatch, keys, status, detail, kind, says):
    answering(monkeypatch, lambda r: httpx.Response(status, json={"detail": detail}))
    with pytest.raises(sc.ShippingUnavailable) as refused:
        await sc.buy(SID, basis="b1", idempotency_key=CARD)
    assert refused.value.kind == kind and says in str(refused.value) and refused.value.code == detail["code"]
    assert refused.value.refused is (kind in ("refused", "rejected")), "a 503 during a buy is unknown, never 'nothing changed'"
    assert len(str(refused.value)) <= 140


def test_what_the_service_wrote_is_scrubbed_and_what_it_filled_in_is_kept():
    d = summary(stage="bought", tracking_number="123456789012", print="Print failed")
    d.update({"label": {"provider": "Parcel2Go", "service": "Parcelforce", "tracking_number": "123456789012",
                        "tracking_url": "javascript:alert(1)", "purchased_at": "2026-10-07T09:00:00+00:00"},
              "print_status": {"state": "failed", "label": "Print failed", "error": "PrintNode: call 07700 900123", "history": [{}]},
              "alerts": ["Ring jo@example.com on +44 7700 900123 at SL8 5AS"], "last_error": "Address SL8 5AS refused",
              "payment": {"label": "Paid", "note": ""}, "carrier": None, "can_buy": False})
    d["carrier"] = {"stage": "in_transit", "label": "In transit", "note": "Arrived at SL8 5AS depot"}
    one = shipping_views.detail(d)
    assert (one["payment"], one["carrier"]) == ("Paid", "In transit"), "a detail's payment and carrier are its words"
    assert one["carrier_view"]["note"] == "Arrived at [postcode] depot"
    assert one["tracking_number"] == "123456789012" and one["label"]["purchased_at"] == "2026-10-07T09:00:00+00:00"
    assert one["label"]["tracking_url"] == "", "only an https address is kept"
    assert one["alerts"] == ["Ring [email] on [number] at [postcode]"] and one["error"] == "Address [postcode] refused"
    assert one["printing"]["error"] == "PrintNode: call [number]" and one["tone"] == "bad"
    assert shipping_views.row(summary(stage="attention"))["tone"] == "warn"
    assert shipping_views.row(summary(stage="in_transit"))["tone"] == "quiet"


async def test_what_a_buy_proof_says_names_no_tracking_number(monkeypatch, keys):
    """The proof's note is the ledger's reason and the timeline's: whether the number is in, and the
    service's own sentence with the order's number taken out of it."""
    number = "QF123456789GB"
    shipment = summary(stage="bought") | {"label": {"provider": "Parcel2Go", "service": "Parcelforce",
                                                    "tracking_number": number}}
    answering(monkeypatch, lambda r: httpx.Response(200, json={
        "charged": True, "status": "fulfillment_failed", "shipment": shipment,
        "error": f"The label is bought (no need to buy again). Shopify refused {number}."}))
    execution = {"shipment_id": SID, "basis": "b1", "idempotency_key": CARD}
    await shipping_tools._execute_buy(execution)
    before = shipping_tools.fingerprint(summary() | {"label": None})
    observed = shipping_tools.fingerprint(shipment)
    assert observed["tracking"] is True and "tracking_number" not in observed
    ok, note = shipping_tools.verify_buy(before, observed, execution)
    assert ok and note == ("Tracking number in. The label is bought, but: The label is bought (no need to buy again). "
                           "Shopify refused [tracking number].")
    assert number not in note


@pytest.mark.parametrize("state", ["requested", "submitting", "unknown", "", "failed"])
async def test_a_print_still_being_sent_is_never_called_refused(monkeypatch, keys, state):
    """Only the service's "failed" is a definite no. A print it was still sending when it answered
    (CLIVE's wait ran out, and the same key was answered from the attempt in flight) may yet come
    out of the printer: George is told to check it, never that PrintNode refused it."""
    from app.tools import registry

    error = "PrintNode request failed (HTTP 400)." if state == "failed" else None
    answering(monkeypatch, lambda r: httpx.Response(200, json={
        "print_intent": {"state": state, "provider_job_id": None, "error": error}, "sent_to_printer": False}))
    execution = {"shipment_id": SID, "idempotency_key": "clive-print-this-one-card"}
    write = registry.get(shipping_tools.PRINT).write
    await write.execute(execution)
    held = {"bought": True, "prints": 0, "reprints": 0, "print": "not_printed"}
    ok, note = write.verify(held, held | {"prints": 1, "print": "sending"}, execution)
    assert not ok
    if state == "failed":
        assert note == "The label didn't go to the printer: PrintNode request failed (HTTP 400)."
    else:
        assert note.endswith("Check the printer before printing again.") and "refused" not in note
    assert sc.PRINT_TIMEOUT_S >= 45, "longer than the service's two PrintNode waits (tests/test_crooks_shipping_contract.py)"


# ------------------------------------------------------------------ the tools, refused before staging


async def test_a_label_is_not_prepared_for_an_order_that_is_not_ready(monkeypatch, keys):
    attention = summary(stage="attention", reasons=["Payment pending", "Missing HS code"], status="Payment pending")
    answering(monkeypatch, lambda r: httpx.Response(200, json=attention | {"label": None, "print_status": None, "can_buy": False}))
    from app.tools.registry import ToolError

    with pytest.raises(ToolError) as refused:
        await shipping_tools.shipping_label_buy(SID)
    assert str(refused.value) == "#2142 isn't ready for a label: Payment pending · Missing HS code. Nothing was prepared."


async def test_a_print_needs_a_bought_label_and_a_copy_needs_a_first_print(monkeypatch, keys):
    from app.tools.registry import ToolError

    answering(monkeypatch, lambda r: httpx.Response(200, json=summary() | {"label": None, "print_status": None}))
    with pytest.raises(ToolError, match="no label bought yet, so there is nothing to print"):
        await shipping_tools.shipping_label_print(SID)
    bought = summary(stage="bought") | {"label": {"provider": "Parcel2Go", "service": "Parcelforce", "tracking_number": "CI1GB"},
                                        "print_status": {"state": "not_printed", "label": "Not printed", "history": [],
                                                         "first_print_available": True}}
    answering(monkeypatch, lambda r: httpx.Response(200, json=bought))
    with pytest.raises(ToolError, match="hasn't been printed yet"):
        await shipping_tools.shipping_label_reprint(SID)
    prepared = await shipping_tools.shipping_label_print(SID)
    assert prepared.execution["idempotency_key"].startswith("clive-print-") and prepared.before["prints"] == 0


async def test_a_first_print_that_definitely_failed_is_printed_again_not_copied(monkeypatch, keys):
    """The service's line: a first print stays available until an attempt might have printed. One
    that definitely failed is printed again as a first print, never sent as an "extra copy"."""
    from app.tools.registry import ToolError

    failed = summary(stage="bought") | {
        "label": {"provider": "Parcel2Go", "service": "Parcelforce", "tracking_number": "CI1GB"},
        "print_status": {"state": "failed", "label": "Print failed", "first_print_available": True,
                         "history": [{"state": "failed", "via": "PrintNode", "reprint": False}]}}
    answering(monkeypatch, lambda r: httpx.Response(200, json=failed))
    with pytest.raises(ToolError, match=r"hasn't been printed yet \(Print failed\): ask to print it"):
        await shipping_tools.shipping_label_reprint(SID)
    prepared = await shipping_tools.shipping_label_print(SID)
    assert prepared.before["prints"] == 1 and prepared.before["print"] == "failed"


# ------------------------------------------------------------------ what the model is told


async def test_without_keys_the_model_is_told_once_and_the_parked_row_follows_clive_shipping(monkeypatch):
    from app.capabilities import families
    from app.families import load_all
    from app.shipping import current, install
    from app.shipping.easyship import EasyshipProvider

    load_all()
    before = current()
    install(EasyshipProvider())                         # as app/runtime.py installs it: never connected
    try:
        await _the_rows_follow_the_keys(monkeypatch, families)
    finally:
        install(before)


async def _the_rows_follow_the_keys(monkeypatch, families):
    monkeypatch.setattr(keychain, "get_optional", lambda key: None)
    table = await families.states(None)
    assert table["shipping_reads"]["state"] == table["shipping_labels"]["state"] == "DISCONNECTED"
    lines = families.words({k: table[k] for k in ("shipping_reads", "shipping_labels")})
    assert lines == ["- DISCONNECTED — no CLIVE Shipping keys stored: Buying and printing labels, Reading shipping"]
    assert table["shipping_provider"]["state"] == "DISCONNECTED"
    held = {sc.READ_KEY: READ}
    monkeypatch.setattr(keychain, "get_optional", lambda key: held.get(key))
    table = await families.states(None)
    assert table["shipping_reads"]["state"] == "READY"
    assert table["shipping_labels"]["detail"] == "no CLIVE Shipping write key stored"
    assert table["shipping_provider"]["state"] == "READY", "the parked Easyship row no longer says labels are disconnected"


async def test_a_change_is_blocked_on_a_server_without_the_write_key(monkeypatch):
    from app.runtime import build
    from config.settings import Settings

    runtime = build(Settings(writes_enabled=True, allowed_logins="owner@example.com"))
    monkeypatch.setattr(keychain, "get_optional", lambda key: {sc.READ_KEY: READ}.get(key))
    status = await runtime.write_status("shipping_label_buy")
    assert (status.state, status.detail) == ("blocked", "blocked — CLIVE Shipping has no write key on this server")
    monkeypatch.setattr(keychain, "get_optional", lambda key: {sc.READ_KEY: READ, sc.WRITE_KEY: WRITE}.get(key))
    assert (await runtime.write_status("shipping_label_print")).state == "ready"


# ------------------------------------------------------------------ Connections


def test_the_connections_card_asks_for_the_two_keys_by_their_server_names():
    from app.connections import catalog

    card = catalog.get("shipping")
    assert card.label == "CLIVE Shipping" and card.requires == (sc.READ_KEY, sc.WRITE_KEY)
    assert [(f.key, f.env) for f in card.fields] == [(sc.READ_KEY, "SHIPPING_CLIVE_READ_KEYS"),
                                                     (sc.WRITE_KEY, "SHIPPING_CLIVE_WRITE_KEYS")]
    assert all("/opt/clive/clive-shipping/.env" in f.hint or f.hint.startswith("Same command") for f in card.fields)
    assert card.unlocks == ("shipping_reads", "shipping_labels")
    assert {sc.READ_KEY, sc.WRITE_KEY} <= set(keychain.KNOWN_KEYS)


@pytest.mark.parametrize("health, caps, ok, says", [
    ((200, {"ok": True}), (200, {"service": "CLIVE Shipping"}), True, "accepted the read key"),
    ((502, {}), (200, {}), False, "didn't answer at returns.example.com/shipping"),
    ((200, {"ok": True}), (403, {"detail": {"message": "This key cannot read shipping.", "code": "forbidden"}}), False,
     "refused the read key. Check SHIPPING_CLIVE_READ_KEYS is set in /opt/clive/clive-shipping/.env"),
    ((200, {"ok": True}), (200, {"service": "CROOKS Returns"}), False, "it isn't CLIVE Shipping"),
])
async def test_the_read_key_is_tested_with_a_read_that_changes_nothing(monkeypatch, health, caps, ok, says):
    from app.connections import testers

    seen: list[httpx.Request] = []

    def handler(request):
        seen.append(request)
        status, body = health if request.url.path.endswith("/health") else caps
        return httpx.Response(status, json=body)

    monkeypatch.setattr(testers, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))

    class Settings:
        shipping_base_url = "https://returns.example.com/shipping"

    outcome = await testers.run("shipping", {sc.READ_KEY: READ, sc.WRITE_KEY: WRITE}, Settings())
    assert outcome.ok is ok and says in outcome.detail, outcome.detail
    assert all(r.method == "GET" for r in seen) and all(READ not in str(r.url) for r in seen)
    assert all(WRITE not in str(r.headers) for r in seen), "the write key is never sent to test"
    if len(seen) > 1:
        assert seen[1].url.path == "/shipping/api/v1/capabilities" and seen[1].headers["authorization"] == f"Bearer {READ}"


# ------------------------------------------------------------------ the cards


def test_a_read_is_drawn_as_the_shipping_card_and_a_failure_names_the_service():
    from app.presentation import UI_TYPES, _from_result

    assert "shipping" in UI_TYPES
    opened = shipping_views.open_view([summary(), summary(id="shp_0a1b2c3d4e60", order="CROOKS-2134", stage="attention",
                                                      reasons=["Missing weight"])], checked_at="2026-10-07T21:00:00Z")
    (item,) = _from_result("shipments_open", opened)
    assert item["type"] == "shipping" and item["data"]["view"] == "open" and item["data"]["key"] == "open all"
    assert [r["stage"] for r in item["data"]["shipments"]] == ["attention", "ready"], "in the service's tab order"
    assert item["data"]["needs_you"] == 2
    from app.render import KEY_OF

    assert KEY_OF["shipping"] == ("key",)


def test_the_drawings_under_node():
    node = shutil.which("node") or ("/opt/node22/bin/node" if Path("/opt/node22/bin/node").exists() else None)
    if node is None:
        pytest.skip("node is not installed here")
    result = subprocess.run([node, "--test", str(ROOT / "tests" / "web" / "shipping.test.js")],
                            capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout
