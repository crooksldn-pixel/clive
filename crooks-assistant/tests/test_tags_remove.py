"""Tags taken off an order: AMBER, a tap, only the tags the order actually has, proven by
re-reading, and the undo puts back exactly those."""

from __future__ import annotations

from app.actions.models import ActionStatus
from app.clients.shopify import REVIEWED_MUTATIONS
from app.tools import registry
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.test_actions import ORDER
from tests.test_tags import (  # noqa: F401 — the fixtures
    AS_THE_OWNER,
    NO_AUTHORITY,
    TagStore,
    engine,
    lookup,
    session,
)

# The admitted owner calling tools directly, as a request the door let through would — granted
# per test, to the tests that call a tool, and to no others (the 2026-09-28 deploy review, round
# 9, F-A2-FIXTURE and I-tests5 I-04; `AS_THE_OWNER` in tests/test_tags.py says why).

TOOL = "shopify_order_tags_remove"


def test_removing_tags_is_amber_reversible_and_a_tap():
    spec = registry.get(TOOL)
    assert spec.tier is Tier.AMBER and spec.write.complete and spec.write.reversible and spec.write.kind == "reversible"
    assert spec.write.mutation == "order_tags_remove" and REVIEWED_MUTATIONS["order_tags_remove"].idempotent
    assert classify(TOOL, {"order_id": ORDER, "tags": ["hold"]}, issued_ids={ORDER}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify(TOOL, {"order_id": ORDER, "tags": ["hold"]}).disposition is Disposition.DENY
    assert classify(TOOL, {"order_id": ORDER, "tags": []}, issued_ids={ORDER}).disposition is Disposition.DENY
    assert classify(TOOL, {"order_id": ORDER, "tags": ["a"] * 6}, issued_ids={ORDER}).disposition is Disposition.DENY


@AS_THE_OWNER
async def test_only_tags_the_order_has_come_off_and_the_undo_puts_them_back(engine, session):  # noqa: F811
    from app.tools import shopify_tools

    store = TagStore(tags=["vip", "hold", "priority"])
    shopify_tools.bind(store)
    text = await dispatch(TOOL, {"order_id": ORDER, "tags": ["HOLD", "exchange-requested"]}, session=session, timeout_s=5)
    assert text.startswith("PROPOSED") and "take hold off order 1930" in text
    proposal = session.proposals[-1]
    assert proposal.interaction == "tap_commit" and proposal.risk == "AMBER"
    assert dict(proposal.execution) == {"order_id": ORDER, "remove": ["hold"], "add": [], "previous_tags": ["vip", "hold", "priority"]}
    assert store.mutations == []
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=lookup)
    assert result.code == "verified" and result.spoken == "Took the tags off order 1930."
    assert store.mutations == [("order_tags_remove", {"id": ORDER, "tags": ["hold"]})] and store.tags == ["vip", "priority"]
    assert proposal.entity and proposal.entity["tags"] == ["vip", "priority"]
    undo = session.proposal(proposal.undo_id)
    assert undo is not None and dict(undo.execution)["add"] == ["hold"] and dict(undo.execution)["remove"] == []
    words = registry.get(TOOL).write.present(undo)
    assert words["title"] == "Put the tags back" and words["undone_title"] == "Tags put back"
    back = await engine.commit(undo.proposal_id, "t1", caller="o", spec_lookup=lookup)
    assert back.code == "verified" and sorted(store.tags) == ["hold", "priority", "vip"] and back.spoken == "Tags put back on order 1930."


@AS_THE_OWNER
async def test_tags_the_order_does_not_have_are_not_a_change(engine, session):  # noqa: F811
    from app.tools import shopify_tools

    store = TagStore(tags=["vip"])
    shopify_tools.bind(store)
    text = await dispatch(TOOL, {"order_id": ORDER, "tags": ["hold"]}, session=session, timeout_s=5)
    assert text.startswith("ERROR") and "has none of those tags" in text and session.proposals == [] and store.mutations == []


@AS_THE_OWNER
async def test_tags_changed_in_admin_meanwhile_are_left_alone(engine, session):  # noqa: F811
    from app.tools import shopify_tools

    store = TagStore(tags=["vip", "hold"])
    shopify_tools.bind(store)
    await dispatch(TOOL, {"order_id": ORDER, "tags": ["hold"]}, session=session, timeout_s=5)
    proposal = session.proposals[-1]
    store.tags = ["vip", "hold", "priority"]
    result = await engine.commit(proposal.proposal_id, "t1", caller="o", spec_lookup=lookup)
    assert result.code == "stale" and store.mutations == [] and proposal.status is ActionStatus.STALE


@AS_THE_OWNER
async def test_the_card_names_the_tags_and_the_ledger_keeps_only_their_count(engine, session):  # noqa: F811
    from app.presentation import present
    from app.providers.base import ToolCall
    from app.tools import shopify_tools

    store = TagStore(tags=["vip", "hold"])
    shopify_tools.bind(store)
    await dispatch(TOOL, {"order_id": ORDER, "tags": ["hold"]}, session=session, timeout_s=5)
    proposal = session.proposals[-1]
    card = present([ToolCall(name=TOOL, args={}, ok=True, proposal_id=proposal.proposal_id)], session=session)[0]["data"]
    assert card["title"] == "Remove tags" and card["summary"] == "hold" and card["interaction"]["kind"] == "tap_commit" and card["reversible"] is True
    line = engine.ledger.read()[-1]
    assert line["event"] == "PROPOSED" and line["facts"] == {"tags": 1} and "hold" not in str({k: v for k, v in line.items() if k != "payload_len"})


async def test_with_no_authority_stamped_nothing_runs(engine, session, monkeypatch):  # noqa: F811
    """F-A2-FIXTURE's regression for this tool, with NO `owner_asking` (I-tests5 I-04): taking a
    tag the order HAS off it — a call the owner gets a card for — made with no authority is
    refused before the gate; no handler runs, the shop is not read and nothing is prepared.
    The owner's identical call then is prepared, so the refusal was for want of authority."""
    from app.tools import authority, shopify_tools

    store = TagStore(tags=["vip", "hold"])
    shopify_tools.bind(store)
    ran: list[str] = []
    real = registry.invoke

    async def invoke(name, args, *, timeout_s):
        ran.append(name)
        return await real(name, args, timeout_s=timeout_s)

    monkeypatch.setattr(registry, "invoke", invoke)
    assert authority.current() is None, "this test was given no authority"
    text = await dispatch(TOOL, {"order_id": ORDER, "tags": ["hold"]}, session=session, timeout_s=5)
    assert text.startswith(NO_AUTHORITY), text
    assert ran == [] and store.reads == 0 and store.mutations == [] and session.proposals == [] and store.tags == ["vip", "hold"]

    with authority.acting_as(authority.for_owner("owner@example.com")):
        asked = await dispatch(TOOL, {"order_id": ORDER, "tags": ["hold"]}, session=session, timeout_s=5)
    assert asked.startswith("PROPOSED") and len(session.proposals) == 1 and store.mutations == [], asked
