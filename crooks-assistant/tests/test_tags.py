"""Order tags: the first change built on the engine's hooks at AMBER — read, merge, write
the union, prove by re-reading, and offer the removal of exactly what was added."""

from __future__ import annotations

import pytest

from app.actions import engine as engine_module
from app.actions.engine import ActionEngine
from app.actions.ledger import NullLedger
from app.actions.models import ActionStatus
from app.clients.shopify import REVIEWED_MUTATIONS, ShopifyError
from app.session.models import Session
from app.tools import registry, shopify_tools
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.test_actions import ORDER, FakeStore

# The admitted owner calling tools directly, as a request the door let through would — granted
# per test, to the tests that call a tool, and to no others (the 2026-09-28 deploy review, round
# 9, F-A2-FIXTURE and I-tests5 I-04). A refusal asserted under it is one the OWNER meets, so it
# cannot pass for want of authority; a test of the declaration runs with none, which is
# production's default; and `test_with_no_authority_stamped_nothing_runs` holds what a call with
# none gets.
AS_THE_OWNER = pytest.mark.usefixtures("owner_asking")
# What the dispatcher answers a call made with no authority (app/tools/dispatch.py). The gate's
# own refusals carry a refusal id — "REFUSED (ref_…):" — and this does not.
NO_AUTHORITY = "REFUSED: this was not asked for by the owner"

TOOL = "shopify_order_tags_add"


class TagStore(FakeStore):
    def __init__(self, tags: list[str] | None = None) -> None:
        super().__init__(note="")
        self.tags = list(tags or [])

    def _order(self) -> dict:
        node = super()._order()
        node["tags"] = list(self.tags)
        return node

    async def mutate(self, name: str, variables: dict) -> dict:
        reviewed = REVIEWED_MUTATIONS[name]
        assert set(variables) == set(reviewed.variables)
        self.mutations.append((name, dict(variables)))
        if self.fail_mutation:
            raise ShopifyError("Shopify refused it.")
        if name == "order_tags_add":
            for t in variables["tags"]:
                if t.lower() not in {x.lower() for x in self.tags}:
                    self.tags.append(t)
            return {"data": {"tagsAdd": {"node": {"id": variables["id"]}, "userErrors": []}}}
        if name == "order_tags_remove":
            self.tags = [t for t in self.tags if t.lower() not in {x.lower() for x in variables["tags"]}]
            return {"data": {"tagsRemove": {"node": {"id": variables["id"]}, "userErrors": []}}}
        return await super().mutate(name, variables)


@pytest.fixture()
def store():
    s = TagStore(tags=["vip"])
    shopify_tools.bind(s)
    return s


@pytest.fixture()
def engine(monkeypatch):
    e = ActionEngine(ledger=NullLedger())
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


@pytest.fixture()
def session():
    s = Session(session_id="t1")
    s.issue(ORDER)
    s.epoch = 1
    return s


def lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


def test_the_tags_tool_is_amber_reversible_and_a_tap():
    spec = registry.get(TOOL)
    assert spec.tier is Tier.AMBER and spec.write is not None and spec.write.complete and spec.write.reversible
    assert spec.write.kind == "reversible" and spec.write.mutation in REVIEWED_MUTATIONS
    assert REVIEWED_MUTATIONS["order_tags_add"].idempotent and REVIEWED_MUTATIONS["order_tags_remove"].idempotent
    assert classify(TOOL, {"order_id": ORDER, "tags": ["hold"]}, issued_ids={ORDER}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify(TOOL, {"order_id": ORDER, "tags": ["hold"]}).disposition is Disposition.DENY
    assert classify(TOOL, {"order_id": ORDER, "tags": "hold"}, issued_ids={ORDER}).disposition is Disposition.DENY
    assert classify(TOOL, {"order_id": ORDER, "tags": ["a"] * 6}, issued_ids={ORDER}).disposition is Disposition.DENY
    assert classify(TOOL, {"order_id": ORDER, "tags": ["x" * 41]}, issued_ids={ORDER}).disposition is Disposition.DENY


@AS_THE_OWNER
async def test_tags_are_merged_never_replaced_and_proven_by_re_reading(store, engine, session):
    text = await dispatch(TOOL, {"order_id": ORDER, "tags": ["exchange-requested", "VIP", " hold "]}, session=session, timeout_s=5)
    assert text.startswith("PROPOSED") and "tags exchange-requested, hold" in text and "tapping the card applies it" in text
    proposal = session.proposals[-1]
    assert proposal.interaction == "tap_commit" and proposal.risk == "AMBER"
    assert dict(proposal.execution) == {"order_id": ORDER, "add": ["exchange-requested", "hold"], "previous_tags": ["vip"]}
    assert store.mutations == []
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=lookup)
    assert result.code == "verified" and result.spoken == "Tagged order 1930."
    assert store.mutations == [("order_tags_add", {"id": ORDER, "tags": ["exchange-requested", "hold"]})]
    assert store.tags == ["vip", "exchange-requested", "hold"]
    assert proposal.entity and proposal.entity["tags"] == ["vip", "exchange-requested", "hold"], "the card shows the order as it now is"
    undo = session.proposal(proposal.undo_id)
    assert undo is not None and dict(undo.execution)["remove"] == ["exchange-requested", "hold"]
    back = await engine.commit(undo.proposal_id, "t1", caller="o", spec_lookup=lookup)
    assert back.code == "verified" and store.tags == ["vip"] and back.spoken == "Tags taken off order 1930 again."


@AS_THE_OWNER
async def test_tags_already_there_are_not_a_change(store, engine, session):
    text = await dispatch(TOOL, {"order_id": ORDER, "tags": ["vip", "Vip"]}, session=session, timeout_s=5)
    assert text.startswith("ERROR") and "already has those tags" in text and session.proposals == []


@AS_THE_OWNER
@pytest.mark.parametrize("bad", [[""], ["<b>x</b>"], ["a|b"], ["x" * 41], [1]])
async def test_a_tag_that_is_not_a_tag_is_refused_before_anything_is_read(store, engine, session, bad):
    """Refused to the owner, by the gate or the tool, for what the tag is — never the refusal a
    call with no authority gets, which this test would otherwise pass on (I-tests5 I-04)."""
    text = await dispatch(TOOL, {"order_id": ORDER, "tags": bad}, session=session, timeout_s=5)
    assert text.startswith(("ERROR", "REFUSED (")) and not text.startswith(NO_AUTHORITY), text
    assert store.reads == 0 and session.proposals == []


@AS_THE_OWNER
async def test_tags_changed_in_admin_meanwhile_are_not_overwritten(store, engine, session):
    await dispatch(TOOL, {"order_id": ORDER, "tags": ["hold"]}, session=session, timeout_s=5)
    proposal = session.proposals[-1]
    store.tags = ["vip", "priority"]   # someone tagged it in Admin
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=lookup)
    assert result.code == "stale" and store.mutations == [] and proposal.status is ActionStatus.STALE
    assert result.spoken.startswith("The order's tags changed")


@AS_THE_OWNER
async def test_the_card_names_the_tags_and_the_ledger_keeps_only_their_length(store, engine, session):
    from app.presentation import present
    from app.providers.base import ToolCall

    await dispatch(TOOL, {"order_id": ORDER, "tags": ["hold"]}, session=session, timeout_s=5)
    proposal = session.proposals[-1]
    card = present([ToolCall(name=TOOL, args={}, ok=True, proposal_id=proposal.proposal_id)], session=session)[0]["data"]
    assert card["title"] == "Add tags" and card["summary"] == "hold" and card["facts"] == [{"label": "Tags", "value": "hold", "tone": ""}]
    assert card["interaction"]["kind"] == "tap_commit" and card["reversible"] is True
    line = engine.ledger.read()[-1]
    assert line["event"] == "PROPOSED" and line["payload_len"] == 4 and "hold" not in str({k: v for k, v in line.items() if k != "payload_len"})


def test_the_list_variable_is_bounded_by_the_client_too():
    import asyncio

    from app.clients.shopify import ShopifyClient

    client = ShopifyClient("x.myshopify.com", "2025-07")
    for bad in ([], ["x" * 41], [""], ["a"] * 21, [1], "hold"):
        with pytest.raises(ShopifyError, match="out of bounds|wrong type"):
            asyncio.run(client.mutate("order_tags_add", {"id": ORDER, "tags": bad}))


async def test_with_no_authority_stamped_nothing_runs(store, engine, session, monkeypatch):
    """F-A2-FIXTURE's regression for this tool, with NO `owner_asking` (I-tests5 I-04): the same
    call the owner gets a card for — a tag this order has not got, on an order this conversation
    was shown — made with no authority, as a call that did not come through the owner's door is.
    The dispatcher refuses it before the gate: no handler runs, the shop is not read, nothing is
    prepared. Then the owner asks, and the identical call is prepared, so the refusal was for
    want of authority and for nothing else."""
    from app.tools import authority

    ran: list[str] = []
    real = registry.invoke

    async def invoke(name, args, *, timeout_s):
        ran.append(name)
        return await real(name, args, timeout_s=timeout_s)

    monkeypatch.setattr(registry, "invoke", invoke)
    assert authority.current() is None, "this test was given no authority"
    calls: list = []
    text = await dispatch(TOOL, {"order_id": ORDER, "tags": ["hold"]}, session=session, timeout_s=5, calls=calls)
    assert text.startswith(NO_AUTHORITY), text
    assert [(c.name, c.ok, c.error) for c in calls] == [(TOOL, False, "no owner authority")]
    assert ran == [] and store.reads == 0 and store.mutations == [] and session.proposals == []

    with authority.acting_as(authority.for_owner("owner@example.com")):
        asked = await dispatch(TOOL, {"order_id": ORDER, "tags": ["hold"]}, session=session, timeout_s=5)
    assert asked.startswith("PROPOSED") and len(session.proposals) == 1 and store.mutations == [], asked
