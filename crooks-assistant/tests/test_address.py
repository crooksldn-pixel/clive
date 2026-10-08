"""Changing the shipping address: RED always, a hold then a tap, the evidence read on the Mac
and checked against what the model says, the diff printed, a reprint note in the same write,
proven by re-reading the address. The store and the inbox are fakes; nothing reaches a network."""

from __future__ import annotations

import base64
import copy
from unittest.mock import MagicMock

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.grammar import gesture_for, words_for
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.clients.shopify import REVIEWED_MUTATIONS, ShopifyError
from app.session.models import Session
from app.tools import gmail_tools, registry, shopify_tools, shopify_writes
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from app.tools.registry import ToolError
from app.tools.shopify_writes import REPRINT_NOTE, address_hash, address_input
from tests.test_actions import ORDER, FakeStore

# The admitted owner calling tools directly, as a request the door let through would: every tool
# call here is his (the 2026-09-27 deploy review, round 8, F-A2-FIXTURE). Production's default,
# and every test's that does not say this, is no authority at all.
pytestmark = pytest.mark.usefixtures("owner_asking")

TOOL = "shopify_order_shipping_address_set"
EVIDENCE = "18f3a9c2b1d4e5f6"
OLD = {
    "firstName": "Daniel", "lastName": "Stub", "company": None, "address1": "12 Somewhere Street", "address2": "Flat 3",
    "city": "Windsor", "province": None, "provinceCode": None, "zip": "SL4 1AA", "country": "United Kingdom",
    "countryCodeV2": "GB", "phone": "+44 7700 900000",
}
BODY = "Hi, I've moved since ordering. Could you send order 1930 to 4 Example Row, London EC1A 1AA instead?\nThanks, Daniel"


class Inbox:
    """The one read the address tool makes of Gmail: a message by id."""

    def __init__(self) -> None:
        self.messages: dict[str, dict] = {
            EVIDENCE: {
                "message_id": EVIDENCE, "thread_id": "t1", "from": "Daniel Stub", "from_email": "daniel@example.com",
                "date": "Tue, 8 Sep 2026 10:12:00 +0100", "subject": "Order 1930 — new address", "authenticated": True, "body": BODY,
            },
        }
        self.reads: list[str] = []

    async def __call__(self, message_id: str) -> dict:
        self.reads.append(message_id)
        if message_id not in self.messages:
            raise ToolError("Could not read that email: not found")
        return dict(self.messages[message_id])


class AddressStore(FakeStore):
    """An order with a full address and a note, whose address and note change together in
    one reviewed write. Optionally an open fulfilment order with a destination of its own."""

    def __init__(self) -> None:
        super().__init__(note="Gift wrap please")
        self.address = dict(OLD)
        self.fulfillment = "UNFULFILLED"
        self.cancelled_at: str | None = None
        self.email = "daniel@example.com"
        self.destination: dict | None = None      # a fixed destination the fulfilment order keeps
        self.destination_follows = False          # or one that follows the order's address
        self.destination_error = False
        self.address_after_mutation: dict | None = None

    def _order(self) -> dict:
        node = super()._order()
        node.update({
            "email": self.email, "cancelledAt": self.cancelled_at, "displayFulfillmentStatus": self.fulfillment,
            "shippingAddress": dict(self.address),
            "fulfillments": [{"id": "gid://shopify/Fulfillment/1", "status": "SUCCESS"}] if self.fulfillment == "FULFILLED" else [],
        })
        return node

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        if "CrooksFulfillmentDestination" in query:
            self.reads += 1
            if self.destination_error:
                raise ShopifyError("Shopify returned errors: ACCESS_DENIED on fulfillmentOrders")
            place = None
            if self.destination_follows:
                a = self.address
                place = {"address1": a["address1"], "address2": a["address2"], "city": a["city"], "zip": a["zip"], "countryCode": a["countryCodeV2"]}
            elif self.destination:
                place = dict(self.destination)
            edges = [{"node": {"id": "gid://shopify/FulfillmentOrder/1", "status": "OPEN", "destination": place}}] if place else []
            return {"data": {"order": {"id": ORDER, "fulfillmentOrders": {"edges": edges}}}}
        return await super().graphql(query, variables)

    async def mutate(self, name: str, variables: dict) -> dict:
        reviewed = REVIEWED_MUTATIONS[name]
        assert set(variables) == set(reviewed.variables), "the reviewed variable set, exactly"
        assert reviewed.validate("address", variables["address"]), "the nested shape, checked as the client would"
        self.mutations.append((name, copy.deepcopy(variables)))
        if self.fail_mutation:
            raise ShopifyError("Shopify refused it.")
        if self.address_after_mutation is not None:
            self.address = dict(self.address_after_mutation)
        else:
            sent = variables["address"]
            self.address = {**{k: None for k in OLD}, **{("countryCodeV2" if k == "countryCode" else k): v for k, v in sent.items()}}
        self.note = variables["note"]
        if self.lose_answer:
            raise ShopifyError("timed out")
        return {"data": {"orderUpdate": {"order": {"id": variables["id"], "name": "#1930"}, "userErrors": []}}}


@pytest.fixture()
def inbox():
    box = Inbox()
    shopify_writes.bind_evidence(box)
    yield box
    shopify_writes.bind_evidence(None)


@pytest.fixture()
def store(monkeypatch):
    s = AddressStore()
    shopify_tools.bind(s)
    monkeypatch.setattr(shopify_writes, "_destination_reads", True)
    return s


@pytest.fixture()
def engine(monkeypatch):
    e = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


@pytest.fixture()
def session():
    s = Session(session_id="c1")
    s.issue(ORDER, EVIDENCE)
    s.epoch = 1
    return s


def lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def stage(session, **args):
    text = await dispatch(TOOL, {"order_id": ORDER, **args}, session=session, timeout_s=5)
    return text, (session.proposals[-1] if session.proposals else None)


async def commit(engine, proposal):
    armed, code = engine.arm(proposal.proposal_id, "c1")
    assert code == ""
    proposal.armed_at -= 1.0   # the dwell passes
    return await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)


MOVE = {"evidence_message_id": EVIDENCE, "address1": "4 Example Row", "city": "London", "postcode": "EC1A 1AA"}


# --------------------------------------------------------------------------- declaration


def test_address_change_is_red_irreversible_and_a_hold_then_a_tap():
    spec = registry.get(TOOL)
    assert spec.tier is Tier.RED and spec.write.complete and spec.write.kind == "irreversible" and not spec.write.reversible
    assert spec.write.undo is None, "no undo card: change it back is a fresh instruction"
    assert gesture_for("RED", spec.write.kind) == "hold_to_arm"
    reviewed = REVIEWED_MUTATIONS["order_shipping_address_set"]
    assert reviewed.scope == "write_orders" and reviewed.idempotent and reviewed.root == "orderUpdate"
    assert "address1" not in reviewed.document and "zip" not in reviewed.document, "the selection carries ids only"
    good = {"firstName": "Daniel", "address1": "4 Example Row", "city": "London", "zip": "EC1A 1AA", "countryCode": "GB", "phone": "+44 7700 900000"}
    assert reviewed.validate("address", good)
    assert not reviewed.validate("address", {**good, "email": "x@y"}), "unknown keys refused"
    assert not reviewed.validate("address", {**good, "countryCode": "gb"})
    assert not reviewed.validate("address", {**good, "address1": ""})
    assert not reviewed.validate("address", {**good, "city": "x" * 101})
    assert not reviewed.validate("address", {**good, "address1": "<script>"})
    assert not reviewed.validate("note", good), "the note is a string, not a shape"


def test_the_gate_wants_issued_ids_of_the_right_kind_and_nothing_extra():
    assert classify(TOOL, {"order_id": ORDER, **MOVE}, issued_ids={ORDER, EVIDENCE}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify(TOOL, {"order_id": ORDER, "postcode": "SL4 1AB"}, issued_ids={ORDER}).disposition is Disposition.STAGE_FOR_OWNER, "evidence is optional"
    unissued = classify(TOOL, {"order_id": ORDER, **MOVE}, issued_ids={ORDER})
    assert unissued.disposition is Disposition.DENY and unissued.recoverable, "an email the conversation never saw"
    assert classify(TOOL, {"order_id": ORDER, "evidence_message_id": ORDER}, issued_ids={ORDER}).disposition is Disposition.DENY, "an order id is not a message id"
    assert classify(TOOL, {"order_id": ORDER}).disposition is Disposition.DENY
    assert classify(TOOL, {"order_id": ORDER, "notify": True}, issued_ids={ORDER}).disposition is Disposition.DENY
    assert classify(TOOL, {"order_id": ORDER, "country_code": "GBR"}, issued_ids={ORDER}).disposition is Disposition.DENY, "schema bounds"


# --------------------------------------------------------------------------- preparing


async def test_preparing_reads_the_order_and_the_email_merges_the_change_and_sends_nothing(store, engine, session, inbox):
    text, proposal = await stage(session, **MOVE)
    assert text.startswith("PROPOSED") and words_for("hold_to_arm")["verb"] in text
    assert "change the address on order 1930 to 4 Example Row, London, EC1A 1AA" in text
    assert store.mutations == [] and inbox.reads == [EVIDENCE]
    assert proposal.risk == "RED" and proposal.interaction == "hold_to_arm" and not proposal.reversible
    ex = dict(proposal.execution)
    assert ex["address"] == {
        "firstName": "Daniel", "lastName": "Stub", "address1": "4 Example Row", "city": "London", "zip": "EC1A 1AA",
        "countryCode": "GB", "phone": "+44 7700 900000",
    }, "the name and phone kept, the old flat number dropped with the old street"
    assert ex["note"] == f"Gift wrap please\n{REPRINT_NOTE}"
    assert proposal.before == {
        "address": address_hash(address_input(OLD)), "note": shopify_writes._note_hash("Gift wrap please"),
        "fulfillment": "UNFULFILLED", "cancelled": False, "destination": "none",
    }
    assert "Somewhere" not in str(proposal.before) and "Example" not in str(proposal.before)
    words = registry.get(TOOL).write.present(proposal)
    assert words["title"] == "Change the address" and words["done_title"] == "Address changed"
    facts = {f["label"]: f["value"] for f in words["facts"]}
    assert facts["Customer"] == "Daniel Stub"
    assert facts["From"] == "12 Somewhere Street, Flat 3, Windsor, SL4 1AA"
    assert facts["To"] == "4 Example Row, London, EC1A 1AA"
    assert facts["Changes"] == "street, second line cleared, town, postcode"
    assert facts["Cited"] == "Email from daniel@example.com, 8 Sep 10:12 · verified sender · postcode, street and town found in the message"
    assert facts["Note"] == REPRINT_NOTE
    assert [f["tone"] for f in words["facts"] if f["label"] == "To"] == ["warn"]
    assert [f["tone"] for f in words["facts"] if f["label"] == "Cited"] == [""]
    line = engine.ledger.read()[-1]
    assert line["event"] == "PROPOSED"
    assert line["facts"] == {"line1": True, "post": True, "town": True, "country": "GB", "evidence": True, "verified_sender": True, "destination_known": True}
    assert "Somewhere" not in str(line) and "Example" not in str(line) and "Daniel" not in str(line)
    assert {"12 Somewhere Street", "Flat 3", "SL4 1AA", "4 Example Row", "EC1A 1AA"} <= session.pii_seen


async def test_an_email_from_someone_else_is_refused(store, engine, session, inbox):
    inbox.messages[EVIDENCE]["from_email"] = "someone@else.com"
    text, proposal = await stage(session, **MOVE)
    assert text.startswith("ERROR") and "not the customer on order #1930" in text and "someone@else.com" in text
    assert proposal is None and store.mutations == []


async def test_an_email_that_does_not_say_that_address_is_refused(store, engine, session, inbox):
    inbox.messages[EVIDENCE]["body"] = "Hi, please could you send it to my new place? I'll call with the details."
    text, proposal = await stage(session, **MOVE)
    assert text.startswith("ERROR") and "does not contain the new postcode or street" in text
    assert proposal is None
    inbox.messages[EVIDENCE]["body"] = "Send it to 4 Example Row please — postcode to follow"
    text, proposal = await stage(session, **MOVE)
    assert "does not contain the new postcode" in text and " or street" not in text


async def test_an_abbreviated_street_still_matches(store, engine, session, inbox):
    inbox.messages[EVIDENCE]["body"] = "new address: 4 Example Rw, London, ec1a1aa"
    text, proposal = await stage(session, **MOVE)
    assert text.startswith("PROPOSED"), text


async def test_an_unverified_sender_is_printed_not_softened(store, engine, session, inbox):
    inbox.messages[EVIDENCE]["authenticated"] = False
    text, proposal = await stage(session, **MOVE)
    assert text.startswith("PROPOSED") and proposal.risk == "RED"
    facts = {f["label"]: f["value"] for f in registry.get(TOOL).write.present(proposal)["facts"]}
    assert "sender not verified" in facts["Cited"]
    assert engine.ledger.read()[-1]["facts"]["verified_sender"] is False


async def test_a_dictated_address_is_staged_and_says_it_was_dictated(store, engine, session, inbox):
    text, proposal = await stage(session, address1="4 Example Row", city="London", postcode="EC1A 1AA")
    assert text.startswith("PROPOSED") and inbox.reads == []
    words = registry.get(TOOL).write.present(proposal)
    cited = [f for f in words["facts"] if f["label"] == "Cited"][0]
    assert cited["value"] == "none — given by the owner" and cited["tone"] == "warn"
    assert engine.ledger.read()[-1]["facts"]["evidence"] is False


async def test_an_email_the_conversation_never_saw_is_not_read(store, engine, inbox):
    session = Session(session_id="c1")
    session.issue(ORDER)
    session.epoch = 1
    text, proposal = await stage(session, **MOVE)
    assert proposal is None and inbox.reads == [] and "not an id this conversation has looked up" in text


@pytest.mark.parametrize("state,args,words", [
    ({"fulfillment": "FULFILLED"}, MOVE, "has shipped"),
    ({"fulfillment": "PARTIALLY_FULFILLED"}, MOVE, "has shipped"),
    ({"cancelled_at": "2026-09-01T00:00:00Z"}, MOVE, "is cancelled"),
    ({}, {"postcode": "SL4 1AA"}, "already on order #1930"),
    ({}, {"postcode": "sl4  1aa"}, "already on order #1930"),
    ({}, {"country_code": "G1"}, "two letters"),
    ({}, {"phone": "call me"}, "phone number"),
    ({}, {"address1": "<b>4 Example Row</b>"}, "plain text"),
])
async def test_refusals_stage_nothing(store, engine, session, inbox, state, args, words):
    for key, value in state.items():
        setattr(store, key, value)
    text, proposal = await stage(session, **args)
    assert text.startswith("ERROR") and words in text, text
    assert proposal is None and store.mutations == []


async def test_a_second_line_alone_keeps_the_street(store, engine, session, inbox):
    _, proposal = await stage(session, address2="Flat 4")
    ex = dict(proposal.execution)
    assert ex["address"]["address1"] == "12 Somewhere Street" and ex["address"]["address2"] == "Flat 4"
    assert proposal.summary["changes"] == ["second line"]


async def test_a_new_country_drops_the_old_region_and_is_printed(store, engine, session, inbox):
    store.address["provinceCode"] = "ENG"
    _, proposal = await stage(session, address1="1 Example Quay", city="Dublin", postcode="D02 X285", country_code="ie")
    ex = dict(proposal.execution)
    assert ex["address"]["countryCode"] == "IE" and "provinceCode" not in ex["address"]
    assert proposal.summary["to_line"] == "1 Example Quay, Dublin, D02 X285, IE"
    assert "country" in proposal.summary["changes"] and "region cleared" in proposal.summary["changes"]


async def test_the_reprint_note_is_not_added_twice(store, engine, session, inbox):
    store.note = f"Gift wrap please\n{REPRINT_NOTE}"
    _, proposal = await stage(session, **MOVE)
    assert dict(proposal.execution)["note"] == store.note


# --------------------------------------------------------------------------- committing


async def test_a_hold_then_a_tap_changes_it_once_and_proves_it(store, engine, session, inbox):
    _, proposal = await stage(session, **MOVE)
    result = await commit(engine, proposal)
    assert result.code == "verified", result
    assert result.spoken == "Changed the address on order 1930. Reprint the label if one is printed."
    assert len(store.mutations) == 1
    name, variables = store.mutations[0]
    assert name == "order_shipping_address_set" and variables["id"] == ORDER
    assert variables["address"]["address1"] == "4 Example Row" and variables["note"].endswith(REPRINT_NOTE)
    assert store.address["address1"] == "4 Example Row" and store.address["address2"] is None
    assert proposal.status is ActionStatus.VERIFIED and proposal.verified and proposal.note == ""
    assert proposal.undo_id is None, "no undo card"
    assert proposal.entity["shipping_address"]["lines"] == ["4 Example Row"] and proposal.entity["shipping_address"]["zip"] == "EC1A 1AA"
    events = [line["event"] for line in engine.ledger.read()]
    assert events[-3:] == ["EXECUTING", "EXECUTED", "VERIFIED"] and "ARMED" in events
    again = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce=proposal.arm_nonce)
    assert again.code == "already_executed" and len(store.mutations) == 1


async def test_a_tap_without_the_hold_does_nothing(store, engine, session, inbox):
    _, proposal = await stage(session, **MOVE)
    result = await engine.commit(proposal.proposal_id, "c1", caller="o", spec_lookup=lookup, nonce="")
    assert result.code == "not_armed" and store.mutations == [] and proposal.status is ActionStatus.PENDING


async def test_an_address_changed_in_admin_meanwhile_makes_it_stale(store, engine, session, inbox):
    _, proposal = await stage(session, **MOVE)
    store.address["address1"] = "99 Other Road"
    result = await commit(engine, proposal)
    assert result.code == "stale" and store.mutations == [] and result.spoken == "The order changed since this was prepared. Nothing was sent."


async def test_a_note_edited_in_admin_meanwhile_makes_it_stale(store, engine, session, inbox):
    _, proposal = await stage(session, **MOVE)
    store.note = "Gift wrap please\nCustomer called: hold until Friday"
    result = await commit(engine, proposal)
    assert result.code == "stale" and store.mutations == []


async def test_a_lost_answer_is_settled_by_looking(store, engine, session, inbox):
    _, proposal = await stage(session, **MOVE)
    store.lose_answer = True
    result = await commit(engine, proposal)
    assert result.code == "verified" and len(store.mutations) == 1 and store.address["address1"] == "4 Example Row"


async def test_shopify_keeping_a_different_address_is_not_verified(store, engine, session, inbox):
    _, proposal = await stage(session, **MOVE)
    store.address_after_mutation = dict(OLD)
    result = await commit(engine, proposal)
    assert result.code == "unverified" and proposal.status is ActionStatus.UNVERIFIED
    assert result.spoken == "I couldn't confirm the address change. Check the order before asking again."


async def test_a_fulfilment_destination_that_did_not_follow_is_said_out_loud(store, engine, session, inbox):
    store.destination = {"address1": "12 Somewhere Street", "address2": "Flat 3", "city": "Windsor", "zip": "SL4 1AA", "countryCode": "GB"}
    _, proposal = await stage(session, **MOVE)
    assert proposal.before["destination"] not in ("none", "unknown")
    result = await commit(engine, proposal)
    assert result.code == "verified"
    assert result.spoken.endswith("The fulfilment destination still shows the old address; check it before printing the label.")


async def test_a_fulfilment_destination_that_followed_needs_no_caveat(store, engine, session, inbox):
    store.destination_follows = True
    _, proposal = await stage(session, **MOVE)
    result = await commit(engine, proposal)
    assert result.code == "verified" and result.spoken == "Changed the address on order 1930. Reprint the label if one is printed."


async def test_a_store_without_the_fulfilment_scope_is_asked_once(store, engine, session, inbox):
    store.destination_error = True
    _, proposal = await stage(session, **MOVE)
    assert proposal.before["destination"] == "unknown" and engine.ledger.read()[-1]["facts"]["destination_known"] is False
    reads = store.reads
    result = await commit(engine, proposal)
    assert result.code == "verified" and shopify_writes._destination_reads is False
    assert store.reads - reads <= 4, "the destination was not asked for again"


# --------------------------------------------------------------------------- the evidence read


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


async def test_message_evidence_reads_the_whole_message_and_its_authentication():
    fake = MagicMock()
    body = ("Hello, " * 400) + "\nMy new address is 4 Example Row, London EC1A 1AA."
    fake.users().messages().get().execute.return_value = {
        "id": EVIDENCE, "threadId": "t1",
        "payload": {
            "headers": [
                {"name": "From", "value": "Daniel Stub <Daniel@Example.com>"}, {"name": "Date", "value": "Tue, 8 Sep 2026 10:12:00 +0100"},
                {"name": "Subject", "value": "New address"}, {"name": "Authentication-Results", "value": "mx.google.com; dkim=pass header.i=@example.com; spf=pass"},
            ],
            "mimeType": "text/plain", "body": {"data": _b64(body)},
        },
    }
    client = gmail_tools.GmailClient()
    client._service = fake
    gmail_tools.bind(client)
    out = await gmail_tools.message_evidence(EVIDENCE)
    assert out["message_id"] == EVIDENCE and out["thread_id"] == "t1" and out["from_email"] == "daniel@example.com"
    assert out["authenticated"] is True and out["body"].endswith("EC1A 1AA.") and "truncated" not in out["body"]
    fake.users().messages().get.assert_called_with(userId="me", id=EVIDENCE, format="full")
    fake.users().messages().get().execute.return_value = {}
    with pytest.raises(ToolError):
        await gmail_tools.message_evidence(EVIDENCE)
    with pytest.raises(ToolError):
        await gmail_tools.message_evidence("")


async def test_thread_and_search_results_carry_message_ids_for_citing():
    fake = MagicMock()
    fake.users().threads().get().execute.return_value = {"messages": [
        {"id": "m1", "payload": {"headers": [{"name": "From", "value": "a@x.com"}], "mimeType": "text/plain", "body": {"data": _b64("one")}}},
    ]}
    client = gmail_tools.GmailClient()
    client._service = fake
    gmail_tools.bind(client)
    out = await gmail_tools.gmail_read_thread("t1")
    assert out["messages"][0]["message_id"] == "m1"
    summary = gmail_tools._summary("t1", {"from": "a@x.com"}, {"id": "m9", "snippet": "hi"})
    assert summary["message_id"] == "m9"


# --------------------------------------------------------------------------- what the evidence must say


async def test_a_different_street_in_the_email_is_refused_even_with_the_right_postcode(store, engine, session, inbox):
    inbox.messages[EVIDENCE]["body"] = "Please send it to 4 Oak Row, London EC1A 1AA"
    text, proposal = await stage(session, **MOVE)
    assert text.startswith("ERROR") and "does not contain the new street" in text and proposal is None


async def test_a_flat_change_alone_is_checked_against_the_email(store, engine, session, inbox):
    inbox.messages[EVIDENCE]["body"] = "It's flat 9 now, same building."
    text, proposal = await stage(session, evidence_message_id=EVIDENCE, address2="Flat 9")
    assert text.startswith("PROPOSED"), text
    facts = {f["label"]: f["value"] for f in registry.get(TOOL).write.present(proposal)["facts"]}
    assert facts["Cited"].endswith("second line found in the message")
    inbox.messages[EVIDENCE]["body"] = "Please leave it with the neighbour."
    text, proposal = await stage(session, evidence_message_id=EVIDENCE, address2="Flat 9")
    assert text.startswith("ERROR") and "does not contain the new second line" in text


async def test_a_new_street_needs_its_postcode_in_the_email(store, engine, session, inbox):
    inbox.messages[EVIDENCE]["body"] = "Send it to 4 Example Row please"
    text, proposal = await stage(session, evidence_message_id=EVIDENCE, address1="4 Example Row")
    assert text.startswith("ERROR") and "A new street needs its postcode" in text and proposal is None
    inbox.messages[EVIDENCE]["body"] = "Send it to 4 Example Row please, still SL4 1AA"
    text, proposal = await stage(session, evidence_message_id=EVIDENCE, address1="4 Example Row")
    assert text.startswith("PROPOSED"), text


async def test_what_the_email_cannot_be_checked_for_is_said_on_the_card(store, engine, session, inbox):
    inbox.messages[EVIDENCE]["body"] = "Send it to 1 Example Quay, Dublin D02 X285 — Ireland now!"
    _, proposal = await stage(session, evidence_message_id=EVIDENCE, address1="1 Example Quay", city="Dublin", postcode="D02 X285", country_code="IE")
    facts = {f["label"]: f["value"] for f in registry.get(TOOL).write.present(proposal)["facts"]}
    assert facts["Cited"].endswith("postcode, street and town found in the message · not checked: country")


async def test_an_email_about_the_address_that_the_model_did_not_cite_is_not_quietly_dictated(store, engine, session, inbox):
    async def threads_for(**kwargs):
        return {"available": True, "threads": [{"thread_id": "t9", "message_id": "9f9f9f9f9f9f", "from": "Daniel Stub", "from_email": "daniel@example.com", "subject": "New address for 1930", "date": "Tue, 8 Sep 2026 09:00:00 +0100", "snippet": "I've moved, please send to 4 Example Row", "likely_bulk": False, "authenticated": True}]}

    shopify_tools.bind(store, threads_for=threads_for)
    text, proposal = await stage(session, address1="4 Example Row", city="London", postcode="EC1A 1AA")
    assert text.startswith("ERROR") and "An email about this order's address is in the inbox (from daniel@example.com" in text and proposal is None
    text, proposal = await stage(session, address1="4 Example Row", city="London", postcode="EC1A 1AA", from_owner=True)
    assert text.startswith("PROPOSED"), text
    cited = [f for f in registry.get(TOOL).write.present(proposal)["facts"] if f["label"] == "Cited"][0]
    assert cited["value"] == "none — given by the owner; an email about the address from daniel@example.com was NOT checked" and cited["tone"] == "bad"
