"""The action engine: the model proposes, the Mac owns the action, the owner authorises an id,
the Mac executes once and verifies. Every test here is a reason to trust that sentence.

Shopify is a fake store with one order and a mutable note. Nothing touches the network.
"""

from __future__ import annotations

import asyncio
from types import MappingProxyType
from zoneinfo import ZoneInfo

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import ActionLedger, NullLedger
from app.actions.models import PROPOSAL_TTL_S, UNDO_TTL_S, ActionStatus, Prepared
from app.clients.shopify import REVIEWED_MUTATIONS, ShopifyClient, ShopifyError
from app.session.models import Session
from app.tools import mock, registry, shopify_tools  # noqa: F401 — mock registers the echo tool
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from app.tools.registry import ToolSpec, WriteSpec

# The admitted owner calling tools directly, as a request the door let through would: every tool
# call here is his (the 2026-09-27 deploy review, round 8, F-A2-FIXTURE). Production's default,
# and every test's that does not say this, is no authority at all.
pytestmark = pytest.mark.usefixtures("owner_asking")

ORDER = "gid://shopify/Order/1930"
TOOL = "shopify_order_note_append"


class FakeStore(ShopifyClient):
    """One order, one note, and a record of every mutation that reaches it."""

    def __init__(self, note: str = "") -> None:
        super().__init__("fake.myshopify.com", "2025-07")
        self.note = note
        self.mutations: list[tuple[str, dict]] = []
        self.scopes = {"read_orders", "write_orders"}
        self.fail_mutation = False
        self.note_after_mutation: str | None = None   # what the store shows afterwards, if not the note sent
        self.reads = 0
        self.gate_reads_after_mutation: asyncio.Event | None = None   # hold the proving re-read
        self.lose_answer = False          # apply the note, then fail the request: the answer was lost
        self.fail_reads_after_mutation = False
        self._shop = {"name": "CROOKS LDN", "myshopifyDomain": "fake.myshopify.com", "ianaTimezone": "Europe/London", "currencyCode": "GBP"}
        self._tz = ZoneInfo("Europe/London")

    def _order(self) -> dict:
        return {
            "id": ORDER, "name": "#1930", "createdAt": "2026-09-08T10:00:00Z", "processedAt": "2026-09-08T10:00:00Z",
            "displayFulfillmentStatus": "UNFULFILLED", "displayFinancialStatus": "PAID",
            "currentTotalPriceSet": {"shopMoney": {"amount": "60.00", "currencyCode": "GBP"}},
            "customer": {"id": "gid://shopify/Customer/7", "displayName": "Daniel Sear", "defaultEmailAddress": {"emailAddress": "daniel@example.com"}},
            "note": self.note, "cancelledAt": None, "lineItems": {"edges": []}, "fulfillments": [], "shippingAddress": {"city": "Windsor", "country": "United Kingdom"},
        }

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        self.reads += 1
        if self.mutations and self.gate_reads_after_mutation is not None:
            await self.gate_reads_after_mutation.wait()
        if self.mutations and self.fail_reads_after_mutation:
            raise ShopifyError("Shopify is not answering.")
        if "CrooksScopes" in query:
            return {"data": {"currentAppInstallation": {"accessScopes": [{"handle": h} for h in sorted(self.scopes)]}}}
        if (variables or {}).get("id") != ORDER:
            return {"data": {"order": None}}
        return {"data": {"order": self._order()}}

    async def mutate(self, name: str, variables: dict) -> dict:
        reviewed = REVIEWED_MUTATIONS[name]
        assert set(variables) == set(reviewed.variables), "the reviewed variable set, exactly"
        self.mutations.append((name, dict(variables)))
        if self.fail_mutation:
            raise ShopifyError("Shopify refused it.")
        self.note = variables["note"] if self.note_after_mutation is None else self.note_after_mutation
        if self.lose_answer:
            raise ShopifyError("timed out")
        return {"data": {"orderUpdate": {"order": {"id": variables["id"], "name": "#1930", "note": self.note}, "userErrors": []}}}


class Clock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def store():
    s = FakeStore(note="Gift wrap please")
    shopify_tools.bind(s)
    return s


@pytest.fixture()
def clock():
    return Clock()


@pytest.fixture()
def engine(clock, monkeypatch):
    e = ActionEngine(ledger=NullLedger(), clock=clock)
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


@pytest.fixture()
def session():
    s = Session(session_id="t1")
    s.issue(ORDER)
    s.epoch = 1
    return s


def spec_lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def stage(session, note="Customer asked for an exchange"):
    text = await dispatch(TOOL, {"order_id": ORDER, "note": note}, session=session, timeout_s=5)
    return text, session.proposals[-1]


# --------------------------------------------------------------------------- policy


def test_read_tools_keep_their_behaviour():
    assert classify("mock_echo", {"word": "x"}).disposition is Disposition.EXECUTE_NOW
    assert classify("mock_echo", {"word": "x"}).tier is Tier.GREEN
    decision = classify("shopify_order_detail", {"order_id": ORDER}, issued_ids={ORDER})
    assert decision.tier is Tier.AMBER and decision.disposition is Disposition.EXECUTE_NOW


@pytest.mark.parametrize("name", ["nope", "shopify_update_order", "shopify_refund_order", "gmail_send_message", "approve_proposal", "execute_proposal", "confirm_action"])
def test_unknown_and_undeclared_writes_are_denied(name):
    decision = classify(name, {"order_id": ORDER}, issued_ids={ORDER})
    assert decision.tier is Tier.RED and decision.disposition is Disposition.DENY


def test_the_registered_write_is_amber_and_staged():
    decision = classify(TOOL, {"order_id": ORDER, "note": "hello"}, issued_ids={ORDER})
    assert decision.tier is Tier.AMBER
    assert decision.disposition is Disposition.STAGE_FOR_OWNER


def test_the_write_needs_an_issued_order_id():
    assert classify(TOOL, {"order_id": ORDER, "note": "hello"}).disposition is Disposition.DENY
    assert classify(TOOL, {"order_id": "gid://shopify/Order/999", "note": "hello"}, issued_ids={ORDER}).disposition is Disposition.DENY
    assert classify(TOOL, {"note": "hello"}, issued_ids={ORDER}).disposition is Disposition.DENY


@pytest.mark.parametrize("note", ["", "   ", "x" * 301])
def test_an_empty_or_oversized_note_is_denied(note):
    assert classify(TOOL, {"order_id": ORDER, "note": note}, issued_ids={ORDER}).disposition is Disposition.DENY


def test_an_argument_the_schema_does_not_know_is_denied():
    decision = classify(TOOL, {"order_id": ORDER, "note": "hi", "tags": ["x"]}, issued_ids={ORDER})
    assert decision.disposition is Disposition.DENY


def test_a_write_registered_without_a_write_definition_is_denied():
    """Declaring a tool with a mutation-looking name is not enough; without a complete
    WriteSpec the gate has nothing to stage and fails closed."""
    registry.tool(
        name="shopify_update_test_thing", description="d",
        input_schema={"type": "object", "properties": {"order_id": {"type": "string"}}},
        tier=Tier.AMBER, issued_id_args=("order_id",),
    )(lambda order_id: None)
    try:
        decision = classify("shopify_update_test_thing", {"order_id": ORDER}, issued_ids={ORDER})
        assert decision.disposition is Disposition.DENY and "reviewed write definition" in decision.reason
    finally:
        registry._REGISTRY.pop("shopify_update_test_thing", None)


def test_a_green_write_is_denied():
    incomplete = ToolSpec(
        name="shopify_update_green", description="d", input_schema={"type": "object", "properties": {}},
        tier=Tier.GREEN, handler=lambda: None, issued_id_args=("order_id",),
        write=WriteSpec(operation="x", entity_kind="order", entity_arg="order_id", mutation="order_note_set",
                        observe=lambda e: None, execute=lambda e: None, present=lambda p: {}),
    )
    registry._REGISTRY["shopify_update_green"] = incomplete
    try:
        assert classify("shopify_update_green", {"order_id": ORDER}, issued_ids={ORDER}).disposition is Disposition.DENY
    finally:
        registry._REGISTRY.pop("shopify_update_green", None)


def test_the_write_tool_is_declared_completely():
    spec = registry.get(TOOL)
    assert spec.write is not None and spec.write.complete
    assert spec.write.mutation in REVIEWED_MUTATIONS
    assert REVIEWED_MUTATIONS[spec.write.mutation].scope == "write_orders"
    assert spec.tier is Tier.AMBER and spec.issued_id_args == ("order_id",)
    assert spec.write.interaction == "tap_commit" and spec.write.reversible


def test_no_model_facing_tool_can_approve_or_execute():
    for name in registry.names():
        assert not any(verb in name for verb in ("approve", "confirm", "execute", "commit")), name


# --------------------------------------------------------------------------- staging


async def test_calling_the_tool_stages_and_sends_nothing(store, engine, session):
    text, proposal = await stage(session)
    assert text.startswith("PROPOSED (prop_")
    assert "NOT happened" in text and "tap" in text.lower()
    assert store.mutations == []
    assert proposal.status is ActionStatus.PENDING
    assert proposal.epoch == session.epoch == 1
    assert proposal.entity_ref == ORDER and proposal.entity_label == "#1930"
    assert proposal.execution["desired_note"] == "Gift wrap please\nCustomer asked for an exchange"
    assert proposal.execution["previous_note"] == "Gift wrap please"
    assert proposal.before != proposal.expected_after
    assert engine.ledger.read()[-1]["event"] == "PROPOSED"


async def test_the_stored_arguments_are_immutable(store, engine, session):
    _, proposal = await stage(session)
    assert isinstance(proposal.execution, MappingProxyType) and isinstance(proposal.model_args, MappingProxyType)
    with pytest.raises(TypeError):
        proposal.execution["desired_note"] = "EVIL"   # type: ignore[index]
    with pytest.raises(TypeError):
        proposal.model_args["note"] = "EVIL"   # type: ignore[index]


async def test_the_same_request_twice_is_one_proposal(store, engine, session):
    first, p1 = await stage(session)
    second, p2 = await stage(session)
    assert p1 is p2 and len(session.proposals) == 1
    assert "already waiting" in second and "NOT happened" in second
    assert store.mutations == []
    _, p3 = await stage(session, note="A different note")
    assert p3 is not p1 and len(session.proposals) == 2


async def test_the_model_is_never_told_it_happened(store, engine, session):
    text, _ = await stage(session)
    for claim in ("added", "done", "applied", "updated"):
        assert f"note {claim}" not in text.lower()
    assert "spoken yes" in text


async def test_the_note_is_appended_never_replaced(store, engine, session):
    store.note = "Line one\nLine two"
    _, proposal = await stage(session, note="Line three")
    assert proposal.execution["desired_note"] == "Line one\nLine two\nLine three"
    store.note = ""
    _, fresh = await stage(session, note="First note")
    assert fresh.execution["desired_note"] == "First note"


async def test_html_and_control_characters_are_refused(store, engine, session):
    text = await dispatch(TOOL, {"order_id": ORDER, "note": "<b>bold</b>"}, session=session, timeout_s=5)
    assert text.startswith("ERROR") and "plain text" in text
    text = await dispatch(TOOL, {"order_id": ORDER, "note": "bad\x00note"}, session=session, timeout_s=5)
    assert text.startswith("ERROR")
    assert session.proposals == [] and store.mutations == []


async def test_a_missing_order_cannot_be_staged(store, engine, session):
    session.issue("gid://shopify/Order/404")
    text = await dispatch(TOOL, {"order_id": "gid://shopify/Order/404", "note": "hi"}, session=session, timeout_s=5)
    assert text.startswith("ERROR") and "No order" in text
    assert session.proposals == []


# --------------------------------------------------------------------------- commit


async def test_a_tap_executes_once_verifies_and_offers_undo(store, engine, session):
    _, proposal = await stage(session)
    result = await engine.commit(proposal.proposal_id, "t1", caller="owner@example.com", spec_lookup=spec_lookup)
    assert result.code == "verified" and proposal.status is ActionStatus.VERIFIED
    assert result.spoken == "Note added to order 1930."
    assert store.mutations == [("order_note_set", {"id": ORDER, "note": "Gift wrap please\nCustomer asked for an exchange"})]
    assert store.note == "Gift wrap please\nCustomer asked for an exchange"
    assert proposal.verified is True and proposal.caller == "owner@example.com"
    assert proposal.entity and proposal.entity["note"].endswith("exchange")
    events = [e["event"] for e in engine.ledger.read()]
    assert events == ["PROPOSED", "EXECUTING", "EXECUTED", "VERIFIED", "PROPOSED"]
    undo = session.proposal(proposal.undo_id)
    assert undo is not None and undo.undo_of == proposal.proposal_id and undo.status is ActionStatus.PENDING
    assert undo.execution["desired_note"] == "Gift wrap please"


async def test_two_concurrent_taps_send_one_mutation(store, engine, session):
    _, proposal = await stage(session)
    a, b = await asyncio.gather(
        engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup),
        engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup),
    )
    assert len(store.mutations) == 1, "exactly once"
    assert sorted([a.code, b.code]) == ["already_executed", "verified"]
    assert engine.executions == 1


async def test_a_retry_after_success_does_not_mutate_again(store, engine, session):
    _, proposal = await stage(session)
    await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    for _ in range(3):
        again = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
        assert again.code == "already_executed"
    assert len(store.mutations) == 1


async def test_a_changed_order_is_not_overwritten(store, engine, session):
    _, proposal = await stage(session)
    store.note = "Someone edited this in Admin"
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert result.code == "stale" and proposal.status is ActionStatus.STALE
    assert store.mutations == []
    assert store.note == "Someone edited this in Admin"
    assert result.spoken == "The order changed since this was prepared. I haven't applied the note."
    assert engine.ledger.read()[-1]["event"] == "STALE"


async def test_verification_failure_is_not_success(store, engine, session):
    _, proposal = await stage(session)
    store.note_after_mutation = "Gift wrap please"   # Shopify said yes but the note did not change
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert len(store.mutations) == 1
    assert result.code == "unverified" and proposal.status is ActionStatus.UNVERIFIED
    assert proposal.verified is False
    assert result.spoken == "I couldn't confirm that change."
    assert proposal.undo_id is None, "no undo for a change that was not proven"
    events = [e["event"] for e in engine.ledger.read()]
    assert events == ["PROPOSED", "EXECUTING", "EXECUTED", "UNVERIFIED"]


async def test_a_refused_mutation_is_a_failure_with_a_calm_line(store, engine, session):
    _, proposal = await stage(session)
    store.fail_mutation = True
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert result.code == "service_unavailable" and proposal.status is ActionStatus.FAILED
    assert result.spoken == "I couldn't confirm that change."
    assert "Shopify refused" in result.detail and "refused" not in result.spoken


async def test_a_proposal_expires_and_cannot_be_resurrected(store, engine, session, clock):
    _, proposal = await stage(session)
    assert proposal.ttl_s(clock.now) == 60
    clock.now += 61
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert result.code == "expired" and proposal.status is ActionStatus.EXPIRED
    clock.now -= 61   # a lying client clock changes nothing: the server has already settled it
    again = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert again.code == "expired"
    assert store.mutations == []


async def test_a_new_instruction_withdraws_the_proposal(store, engine, session):
    _, proposal = await stage(session)
    engine.advance_epoch(session, "new instruction")
    assert proposal.status is ActionStatus.REVOKED
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert result.code == "revoked" and store.mutations == []


async def test_an_epoch_mismatch_is_caught_even_if_revocation_was_missed(store, engine, session):
    _, proposal = await stage(session)
    session.epoch += 1   # moved on without going through the engine
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert result.code == "revoked" and store.mutations == []


async def test_the_wrong_session_cannot_commit(store, engine, session):
    _, proposal = await stage(session)
    result = await engine.commit(proposal.proposal_id, "someone-else", caller="o", spec_lookup=spec_lookup)
    assert result.code == "wrong_session" and result.proposal is None
    assert store.mutations == [] and proposal.status is ActionStatus.PENDING


async def test_an_unknown_proposal_is_unknown(engine):
    result = await engine.commit("prop_doesnotexist", "t1", caller="o", spec_lookup=spec_lookup)
    assert result.code == "unknown" and result.proposal is None


async def test_undo_restores_exactly_and_only_while_untouched(store, engine, session):
    _, proposal = await stage(session)
    await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    undo = session.proposal(proposal.undo_id)
    result = await engine.commit(undo.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert result.code == "verified" and result.spoken == "Note on order 1930 put back as it was."
    assert store.note == "Gift wrap please"
    assert len(store.mutations) == 2
    assert undo.undo_id is None, "an undo is not itself undoable"


async def test_undo_refuses_if_the_note_moved_on(store, engine, session):
    _, proposal = await stage(session)
    await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    undo = session.proposal(proposal.undo_id)
    store.note = "Gift wrap please\nCustomer asked for an exchange\nAnd then a human added this"
    result = await engine.commit(undo.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert result.code == "stale" and len(store.mutations) == 1
    assert store.note.endswith("added this")


async def test_undo_expires_with_its_own_clock(store, engine, session, clock):
    """Its own clock, and a longer one: deciding you want something back takes longer than
    deciding to do it, and nothing is waiting on the offer meanwhile (UNDO_TTL_S)."""
    _, proposal = await stage(session)
    await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    undo = session.proposal(proposal.undo_id)
    clock.now += PROPOSAL_TTL_S + 1
    assert engine.find(undo.proposal_id).status is ActionStatus.PENDING, "a card's minute is not the offer's"
    clock.now += UNDO_TTL_S
    assert (await engine.commit(undo.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)).code == "expired"


async def test_a_spoken_yes_has_no_path_to_execution(store, engine, session):
    """The only thing that moves a proposal is the commit path, which the model cannot reach:
    there is no tool for it, and calling anything named like one is denied."""
    _, proposal = await stage(session)
    for spoken in ("yes", "do it", "go ahead", "confirm", "sure"):
        out = await dispatch("mock_echo", {"word": spoken}, session=session, timeout_s=5)
        assert spoken in out
    for name in ("approve_proposal", "execute_proposal", "confirm_action", "commit_proposal"):
        out = await dispatch(name, {"proposal_id": proposal.proposal_id}, session=session, timeout_s=5)
        assert out.startswith("REFUSED")
    assert proposal.status is ActionStatus.PENDING and store.mutations == []


# --------------------------------------------------------------------------- ledger


async def test_the_ledger_records_the_lifecycle_and_no_content(store, engine, session, tmp_path):
    ledger = ActionLedger(tmp_path)
    engine.ledger = ledger
    _, proposal = await stage(session, note="Refund daniel@example.com at 07700 900123, SW1A 1AA")
    await engine.commit(proposal.proposal_id, "t1", caller="owner@example.com", spec_lookup=spec_lookup)
    raw = ledger.path.read_text(encoding="utf-8")
    entries = ledger.read()
    assert [e["event"] for e in entries] == ["PROPOSED", "EXECUTING", "EXECUTED", "VERIFIED", "PROPOSED"]
    first = entries[0]
    assert first["proposal_id"] == proposal.proposal_id and first["operation"] == "order_note_append"
    assert first["risk"] == "AMBER" and first["entity_kind"] == "order" and first["entity_ref"] == ORDER
    assert first["session_id"] == "t1" and first["epoch"] == 1 and first["payload_len"] > 0
    assert entries[3]["verified"] is True and entries[3]["caller"] == "owner@example.com"
    assert set(first["before"]) == {"sha", "len"}
    for forbidden in ("daniel@example.com", "07700", "SW1A", "Refund", "Gift wrap", "mutation ", "orderUpdate", "shpat_", "note\":"):
        assert forbidden not in raw, forbidden
    assert ledger.path.stat().st_mode & 0o077 == 0, "owner-only"


async def test_the_ledger_is_append_only_and_separate_from_the_log(store, engine, session, tmp_path):
    ledger = ActionLedger(tmp_path)
    engine.ledger = ledger
    _, proposal = await stage(session)
    before = ledger.path.read_text(encoding="utf-8")
    await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    after = ledger.path.read_text(encoding="utf-8")
    assert after.startswith(before) and len(after) > len(before)
    assert ledger.path.name == "actions.jsonl" and not (tmp_path / "assistant.log").exists()


# --------------------------------------------------------------------------- the prepare step


async def test_prepared_carries_a_fingerprint_not_the_note(store):
    prepared = await shopify_tools.shopify_order_note_append(ORDER, "Hello there")
    assert isinstance(prepared, Prepared)
    assert set(prepared.before) == {"sha", "len"} and prepared.before["len"] == len("Gift wrap please")
    assert prepared.summary == {"appended": "Hello there", "had_note": True, "payload_len": 11}
    assert store.mutations == []


# ------------------------------------------------- exactly once, under every timing


async def wait_until(predicate, *, timeout_s: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while not predicate():
        assert asyncio.get_running_loop().time() < deadline, "condition never held"
        await asyncio.sleep(0.005)


async def test_a_second_tap_while_the_change_is_being_proven_waits_for_the_outcome(store, engine, session):
    """The window between the mutation and the proving re-read. A second tap there must not
    re-claim the proposal, must not be judged stale, and must never overwrite the verdict."""
    _, proposal = await stage(session)
    store.gate_reads_after_mutation = asyncio.Event()
    first = asyncio.create_task(engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup))
    await wait_until(lambda: len(store.mutations) == 1)
    assert proposal.status is ActionStatus.EXECUTED
    second = asyncio.create_task(engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup))
    await asyncio.sleep(0.02)
    assert not second.done(), "the second tap waits; it does not decide"
    store.gate_reads_after_mutation.set()
    a, b = await asyncio.gather(first, second)
    assert (a.code, b.code) == ("verified", "already_executed")
    assert proposal.status is ActionStatus.VERIFIED and proposal.undo_id is not None
    assert len(store.mutations) == 1
    events = [e["event"] for e in engine.ledger.read()]
    assert events == ["PROPOSED", "EXECUTING", "EXECUTED", "VERIFIED", "PROPOSED"]
    assert events.count("EXECUTING") == 1


async def test_a_settled_proposal_cannot_be_reopened(store, engine, session):
    _, proposal = await stage(session)
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert result.code == "verified"
    engine._finish(proposal, ActionStatus.STALE, "stale", reason="a late caller")
    assert proposal.status is ActionStatus.VERIFIED and proposal.code == "verified"
    assert [e["event"] for e in engine.ledger.read()].count("STALE") == 0


async def test_a_mutation_whose_answer_was_lost_is_settled_by_looking(store, engine, session):
    """Shopify applied the note but the response never came back. The engine must not say
    'nothing was changed': it re-reads, sees the note, and reports it as applied."""
    _, proposal = await stage(session)
    store.lose_answer = True
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert len(store.mutations) == 1
    assert result.code == "verified" and proposal.status is ActionStatus.VERIFIED
    assert proposal.verified is True and proposal.undo_id is not None
    assert store.note == "Gift wrap please\nCustomer asked for an exchange"
    events = [e["event"] for e in engine.ledger.read()]
    assert events == ["PROPOSED", "EXECUTING", "EXECUTED", "VERIFIED", "PROPOSED"]
    # And a re-ask does not append the line a second time: the same request is one proposal
    # per epoch, and the previous one is settled.
    _, again = await stage(session)
    assert again is not proposal and again.before == proposal.after


async def test_a_mutation_that_never_landed_is_proven_unchanged(store, engine, session):
    _, proposal = await stage(session)
    store.fail_mutation = True
    reads_before = store.reads
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert result.code == "service_unavailable" and proposal.status is ActionStatus.FAILED
    assert store.reads > reads_before + 2, "the entity was looked at again before saying nothing changed"
    assert store.note == "Gift wrap please"
    assert [e["event"] for e in engine.ledger.read()] == ["PROPOSED", "EXECUTING", "FAILED"]


async def test_an_ambiguous_mutation_that_cannot_be_re_read_is_unverified_not_failed(store, engine, session):
    _, proposal = await stage(session)
    store.lose_answer = True
    store.fail_reads_after_mutation = True
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert result.code == "unverified" and proposal.status is ActionStatus.UNVERIFIED
    assert proposal.undo_id is None
    assert [e["event"] for e in engine.ledger.read()] == ["PROPOSED", "EXECUTING", "UNVERIFIED"]


async def test_a_precondition_read_that_fails_sends_nothing(store, engine, session):
    _, proposal = await stage(session)

    async def broken(query, variables=None):
        raise ShopifyError("Shopify is not answering.")

    store.graphql = broken
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert result.code == "service_unavailable" and proposal.status is ActionStatus.FAILED
    assert store.mutations == []


async def test_the_same_request_twice_is_one_ledger_line(store, engine, session):
    await stage(session)
    await stage(session)
    assert [e["event"] for e in engine.ledger.read()] == ["PROPOSED"]


async def test_the_undo_belongs_to_the_epoch_the_change_was_authorised_in(store, engine, session):
    _, proposal = await stage(session)
    store.gate_reads_after_mutation = asyncio.Event()
    commit = asyncio.create_task(engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup))
    await wait_until(lambda: len(store.mutations) == 1)
    engine.advance_epoch(session, "the owner moved on while it was applying")
    store.gate_reads_after_mutation.set()
    result = await commit
    assert result.code == "verified", "a change that was authorised is finished, not withdrawn"
    undo = session.proposal(proposal.undo_id)
    assert undo is not None and undo.epoch == proposal.epoch == 1 and session.epoch == 2
    undone = await engine.commit(undo.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert undone.code == "revoked" and len(store.mutations) == 1


async def test_a_dropped_session_takes_its_proposals_with_it(store, engine, session):
    from app.session.manager import SessionManager

    manager = SessionManager()
    manager.on_drop.append(engine.forget_session)
    live = manager.get_or_create("t1")
    live.issue(ORDER)
    live.epoch = 1
    _, proposal = await stage(live)
    assert engine.find(proposal.proposal_id) is proposal
    manager.drop("t1")
    assert proposal.status is ActionStatus.REVOKED
    assert engine.find(proposal.proposal_id) is None
    assert (await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)).code == "unknown"


async def test_settled_proposals_leave_the_index_after_a_while(store, engine, session, clock):
    _, proposal = await stage(session)
    await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert engine.find(proposal.proposal_id) is proposal
    clock.now += engine_module.SETTLED_RETENTION_S + 1
    assert engine.prune() >= 1
    assert engine.find(proposal.proposal_id) is None
    assert (await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)).code == "unknown"


async def test_the_wait_for_the_tap_starts_when_the_card_is_delivered(store, engine, session, clock):
    _, proposal = await stage(session)
    assert proposal.expires_at == clock.now + engine.ttl_s
    clock.now += 25          # Claude wrote the answer; the voice said it
    delivered = engine.deliver(proposal.proposal_id)
    assert delivered is proposal and proposal.expires_at == clock.now + engine.ttl_s
    assert [e["event"] for e in engine.ledger.read()][-1] == "DELIVERED"
    clock.now += engine.ttl_s - 1
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=spec_lookup)
    assert result.code == "verified"
    # Delivery of a settled proposal changes nothing.
    assert engine.deliver(proposal.proposal_id) is proposal and proposal.status is ActionStatus.VERIFIED


async def test_a_wrong_turning_is_not_announced_to_the_owner(store, engine, session):
    """The model asked for a note on an order this conversation had not looked up. That is
    not a refusal to report; it is a step it skipped. The words it gets back say so — this is
    the last path by which "not allowed" could reach the owner's ears for a change that was
    only ever staged wrongly."""
    fresh = Session(session_id="t2")
    fresh.epoch = 1
    text = await dispatch(TOOL, {"order_id": ORDER, "note": "Customer called"}, session=fresh, timeout_s=5)
    assert text.startswith("NOT YET") and "Do this now, without mentioning it to the owner" in text
    assert "could not do this" not in text and "REFUSED" not in text
    assert store.mutations == [] and fresh.proposals == []
    # A rule, by contrast, is still reported plainly.
    denied = await dispatch("shopify_cancel_order", {"order_id": ORDER}, session=session, timeout_s=5)
    assert denied.startswith("REFUSED") and "Tell the user plainly" in denied


async def test_a_proposal_is_stamped_with_the_half_that_asked_not_the_half_in_focus(session):
    """`stage()` read `session.focused_branch`, and every reader of the field assumes the
    asking one — so a change proposed by the half put aside was filed against the half on
    screen. Four documented properties inverted at once: a spoken "yes" on the focused half
    applied the other half's change; `revoke_pending` on the asking half skipped the card, so
    it outlived the instruction that made it; `/branches/{id}/background` stopped seeing a
    half that had a change waiting; and a BACKGROUND half's proposal passed the check that
    exists to stop a background half committing anything, because it wore the ACTIVE half's
    id. The turn routes now set `acting_branch`, and this is what reads it."""
    session.focused_branch = "br_on_screen"
    session.acting_branch = "br_put_aside"
    _, proposal = await stage(session)
    assert proposal.branch_id == "br_put_aside"

    # And with nothing addressed — a caller that never set it — the focused half still serves.
    session.acting_branch = ""
    session.epoch += 1
    _, later = await stage(session, note="A second note, so it is a second proposal")
    assert later.branch_id == "br_on_screen"
