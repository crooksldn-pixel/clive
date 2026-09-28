"""Bulk changes: one card, one gesture, many proposals — each prepared from a fresh read by
the same write tool, each committed and proven by the same engine, and the result counted
rather than claimed. Shopify is a fake store with several orders; Gmail a fake inbox."""

from __future__ import annotations

import asyncio
import json
import time

import httpx
import pytest

from app import readonly
from app.actions import batch as batch_module
from app.actions import engine as engine_module
from app.actions.batch import (
    DRAG_MIN,
    MAX_BATCH,
    TAP_MAX,
    BatchEngine,
    BatchStatus,
    batch_gesture,
    batch_risk,
    spoken_for,
)
from app.actions.engine import ActionEngine
from app.actions.ledger import ActionLedger, NullLedger
from app.actions.models import ActionStatus
from app.analytics import sets
from app.clients.shopify import ShopifyError
from app.presentation import present, present_batch_state
from app.providers.base import ToolCall
from app.providers.max_agent_sdk import withheld_tools
from app.session.models import Session
from app.tools import batch_tools, gmail_writes, registry, shopify_tools
from app.tools.dispatch import dispatch
from app.tools.gate import Disposition, Tier, classify
from tests.test_actions import Clock, FakeStore
from tests.test_gmail_writes import FakeGmail, Policy, msg

# The admitted owner calling tools directly, as a request the door let through would: every tool
# call here is his (the 2026-09-27 deploy review, round 8, F-A2-FIXTURE). Production's default,
# and every test's that does not say this, is no authority at all.
pytestmark = pytest.mark.usefixtures("owner_asking")

BATCH_TOOLS = ("batch_order_tags_add", "batch_order_tags_remove", "batch_email_archive", "batch_email_drafts")


def gid(n: int) -> str:
    return f"gid://shopify/Order/{n}"


class ManyStore(FakeStore):
    """Several orders with tags, each answering the tag read and the tag mutations by id, with
    per-order refusals, lies and drift so the batch has to count rather than assume."""

    def __init__(self, orders: dict[str, list[str]]) -> None:
        super().__init__(note="")
        self.orders = {oid: {"name": f"#{oid.rsplit('/', 1)[-1]}", "tags": list(tags)} for oid, tags in orders.items()}
        self.refuse: set[str] = set()                   # the mutation is refused for these
        self.lie: set[str] = set()                      # accepted and not applied for these
        self.drift: dict[str, list[str]] = {}           # tags change after the staging read
        self.tag_reads: dict[str, int] = {}

    async def graphql(self, query: str, variables: dict | None = None) -> dict:
        self.reads += 1
        if "CrooksScopes" in query:
            return {"data": {"currentAppInstallation": {"accessScopes": [{"handle": h} for h in sorted(self.scopes)]}}}
        oid = str((variables or {}).get("id") or "")
        order = self.orders.get(oid)
        if order is None:
            return {"data": {"order": None}}
        if "CrooksOrderTags" in query:
            n = self.tag_reads[oid] = self.tag_reads.get(oid, 0) + 1
            if oid in self.drift and n >= 2:
                order["tags"] = list(self.drift.pop(oid))
            return {"data": {"order": {"id": oid, "name": order["name"], "tags": list(order["tags"])}}}
        node = self._order()
        node.update({"id": oid, "name": order["name"], "tags": list(order["tags"])})
        return {"data": {"order": node}}

    async def mutate(self, name: str, variables: dict) -> dict:
        self.mutations.append((name, dict(variables)))
        oid = variables["id"]
        if oid in self.refuse:
            raise ShopifyError("Shopify refused it.")
        order = self.orders[oid]
        if oid not in self.lie:
            if name == "order_tags_add":
                for t in variables["tags"]:
                    if t.lower() not in {x.lower() for x in order["tags"]}:
                        order["tags"].append(t)
            elif name == "order_tags_remove":
                order["tags"] = [t for t in order["tags"] if t.lower() not in {x.lower() for x in variables["tags"]}]
        key = "tagsAdd" if name == "order_tags_add" else "tagsRemove"
        return {"data": {key: {"node": {"id": oid}, "userErrors": []}}}


@pytest.fixture()
def clock():
    return Clock(1_000.0)


@pytest.fixture()
def engine(clock, monkeypatch):
    e = ActionEngine(ledger=NullLedger(), clock=clock)
    monkeypatch.setattr(engine_module, "_engine", e)
    return e


@pytest.fixture()
def batches(engine, clock, monkeypatch):
    b = BatchEngine(engine, clock=clock)
    monkeypatch.setattr(batch_module, "_batches", b)
    return b


@pytest.fixture()
def session():
    s = Session(session_id="b1")
    s.epoch = 1
    s.turn_id = "turn_b"
    return s


def store_of(n: int = 6, tagged: dict[int, list[str]] | None = None) -> ManyStore:
    store = ManyStore({gid(1000 + i): (tagged or {}).get(i, []) for i in range(1, n + 1)})
    shopify_tools.bind(store)
    return store


def orders_set(session, store: ManyStore, *, members: list[str] | None = None, clock=None):
    ids = members or list(store.orders)
    return sets.create(session, kind="orders", members=ids, label="delayed orders", labels={oid: store.orders[oid]["name"] for oid in ids if oid in store.orders}, clock=clock or time.time)


def lookup(name):
    try:
        return registry.get(name)
    except KeyError:
        return None


async def stage(session, tool, **args):
    calls: list = []
    text = await dispatch(tool, args, session=session, timeout_s=10, calls=calls)
    batch = session.batches[calls[-1].proposal_id] if calls and calls[-1].proposal_id else None
    return text, batch, calls


async def gesture(batches, batch, *, nonce: bool | None = None):
    """The gesture the batch asks for: a tap as it is; a hold armed on the Mac first."""
    if batch.interaction in ("tap_commit", "swipe_commit") and nonce is None:
        return await batches.commit(batch.batch_id, batch.session_id, caller="o", spec_lookup=lookup)
    armed, code = batches.arm(batch.batch_id, batch.session_id)
    assert code == "", code
    armed.armed_at -= 1.0
    return await batches.commit(batch.batch_id, batch.session_id, caller="o", spec_lookup=lookup, nonce=armed.arm_nonce)


# ----------------------------------------------------------------------------- policy


@pytest.mark.parametrize("name", BATCH_TOOLS)
def test_every_batch_tool_is_declared_on_a_reviewed_write_and_gated_on_an_issued_set(name):
    spec = registry.get(name)
    assert spec.batch is not None and spec.batch.complete and spec.write is None and spec.tier is Tier.AMBER
    assert spec.issued_id_args == ("set_id",)
    child = registry.get(spec.batch.child_tool)
    assert child.write is not None and child.write.complete, "every mutation is the child's, already reviewed"
    assert name in withheld_tools(registry.all_specs(), writes_enabled=False), "not offered while changes are off"
    assert name not in withheld_tools(registry.all_specs(), writes_enabled=True)
    args = {"set_id": "set_abcdef123456"}
    if "tags" in name:
        args["tags"] = ["hold"]
    if "drafts" in name:
        args.update({"subject": "Hi", "body": "Hello {first_name}"})
    assert classify(name, args, issued_ids={"set_abcdef123456"}).disposition is Disposition.STAGE_FOR_OWNER
    assert classify(name, args).disposition is Disposition.DENY, "an unissued set"
    assert classify(name, {**args, "set_id": "gid://shopify/Order/1"}, issued_ids={"gid://shopify/Order/1"}).disposition is Disposition.DENY, "not a set id"
    assert classify(name, {**args, "extra": 1}, issued_ids={"set_abcdef123456"}).disposition is Disposition.DENY
    if "tags" in name:
        assert classify(name, {**args, "tags": "hold"}, issued_ids={"set_abcdef123456"}).disposition is Disposition.DENY
        assert classify(name, {**args, "tags": ["x"] * 6}, issued_ids={"set_abcdef123456"}).disposition is Disposition.DENY


def test_the_gesture_grows_with_the_batch():
    assert batch_risk(["AMBER"], "AMBER", TAP_MAX) == "AMBER" and batch_risk(["AMBER"], "AMBER", TAP_MAX + 1) == "RED"
    assert batch_risk(["AMBER", "RED"], "AMBER", 2) == "RED" and batch_risk([], "RED", 1) == "RED"
    assert batch_gesture("AMBER", "reversible", 3) == "tap_commit"
    assert batch_gesture("AMBER", "irreversible", 3) == "swipe_commit"
    assert batch_gesture("RED", "reversible", 10) == "hold_to_arm"
    assert batch_gesture("AMBER", "reversible", DRAG_MIN) == "hold_drag_target"
    assert batch_gesture("nonsense", "reversible", 1) == "hold_drag_target"
    assert spoken_for("Tagged", "orders", {"requested": 23, "eligible": 21, "verified": 20, "failed": 1, "excluded": 2}) == "Tagged 20 of the 21 orders. 1 could not be applied.", "the denominator is what was gestured for; the excluded were named on the card"


# ---------------------------------------------------------------------------- staging


async def test_staging_reads_each_order_afresh_and_excludes_the_ones_the_change_does_not_apply_to(engine, batches, session):
    store = store_of(6, tagged={2: ["hold"], 5: ["Hold", "vip"]})
    ws = orders_set(session, store)
    text, batch, calls = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    assert text.startswith("PROPOSED BATCH") and "4 of the 6 orders" in text and "2 excluded (already has those tags: 2)" in text and "tapping the card applies it" in text
    assert "It has NOT happened" in text
    assert batch is not None and batch.status is BatchStatus.PENDING and batch.requested == 6 and len(batch.eligible) == 4
    assert [c.label for c in batch.excluded] == ["#1002", "#1005"] and {c.excluded for c in batch.excluded} == {"already has those tags"}
    assert batch.members == tuple(store.orders) and batch.set_id == ws.set_id and batch.set_label == "delayed orders"
    assert batch.risk == "AMBER" and batch.interaction == "tap_commit" and batch.reversible
    for child in batch.eligible:
        proposal = session.proposal(child.proposal_id)
        assert proposal is not None and proposal.status is ActionStatus.PENDING and proposal.batch_id == batch.batch_id
        assert dict(proposal.execution)["add"] == ["hold"] and proposal.expires_at == batch.expires_at
    assert store.mutations == [] and store.tag_reads == {oid: 1 for oid in store.orders}, "one fresh read per member, nothing sent"
    # The card: counts, scope, the excluded by name and reason, every member to inspect —
    # and no member id.
    items = present(calls, session=session)
    card = next(i for i in items if i["type"] == "batch_action")["data"]
    assert card["batch_id"] == batch.batch_id and card["requested"] == 6 and card["eligible"] == 4 and card["excluded_count"] == 2
    assert card["set"] == {"set_id": ws.set_id, "label": "delayed orders", "kind": "orders", "count": 6}
    assert card["excluded"] == [{"label": "#1002", "reason": "already has those tags"}, {"label": "#1005", "reason": "already has those tags"}]
    assert card["members"] == ["#1001", "#1003", "#1004", "#1006"] and card["title"] == "Add tags to 4 orders" and card["summary"] == "hold"
    assert card["interaction"]["kind"] == "tap_commit" and card["ttl_s"] >= 0 and card["commit"] == {"allowed": True}
    assert "gid://shopify" not in json.dumps(card)
    # The same ask again is the same batch.
    again, same, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    assert same is batch and "already waiting" in again and len(session.batches) == 1


async def test_nothing_eligible_is_an_error_not_a_card(engine, batches, session):
    store = store_of(3, tagged={1: ["hold"], 2: ["hold"], 3: ["hold"]})
    ws = orders_set(session, store)
    text, batch, calls = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    assert text.startswith("ERROR") and "Nothing to do for any of the 3 orders" in text and "already has those tags: 3" in text
    assert batch is None and session.batches == {} and session.proposals == [] and store.mutations == []


async def test_a_set_that_is_too_big_the_wrong_kind_unissued_or_gone_is_refused_before_any_read(engine, batches, session):
    store = store_of(2)
    big = sets.create(session, kind="orders", members=[gid(i) for i in range(MAX_BATCH + 1)], label="all")
    text, batch, _ = await stage(session, "batch_order_tags_add", set_id=big.set_id, tags=["hold"])
    assert text.startswith("ERROR") and f"at most {MAX_BATCH}" in text and "Narrow it" in text
    customers = sets.create(session, kind="customers", members=["gid://shopify/Customer/1"], label="vips")
    text, _, _ = await stage(session, "batch_order_tags_add", set_id=customers.set_id, tags=["hold"])
    assert text.startswith("ERROR") and "applies to orders" in text
    text, _, _ = await stage(session, "batch_order_tags_add", set_id="set_000000000000", tags=["hold"])
    assert text.startswith("NOT YET") or text.startswith("REFUSED")
    session.issue("set_000000000001")
    text, _, _ = await stage(session, "batch_order_tags_add", set_id="set_000000000001", tags=["hold"])
    assert text.startswith("ERROR") and "no working set" in text
    assert store.reads == 0 and session.batches == {} and session.proposals == []


# ------------------------------------------------------------------------------ commit


async def test_the_gesture_applies_each_member_once_and_the_count_is_what_was_proven(engine, batches, session):
    store = store_of(6)
    store.refuse.add(gid(1002))          # Shopify says no
    store.lie.add(gid(1003))             # Shopify says yes and does nothing
    store.drift[gid(1004)] = ["admin"]   # someone edited the tags after staging
    ws = orders_set(session, store)
    _, batch, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["delayed"])
    assert len(batch.eligible) == 6 and batch.risk == "RED" and batch.interaction == "hold_to_arm", "more than a handful takes a hold"
    # Without the hold, nothing.
    bare = await batches.commit(batch.batch_id, "b1", caller="o", spec_lookup=lookup)
    assert bare.code == "not_armed" and store.mutations == [] and batch.status is BatchStatus.PENDING
    result = await gesture(batches, batch)
    assert result.code == "done" and batch.status is BatchStatus.DONE
    assert batch.counts == {"requested": 6, "eligible": 6, "excluded": 0, "verified": 3, "unverified": 1, "stale": 1, "failed": 1, "not_attempted": 0}
    assert result.spoken == "Tagged 3 of the 6 orders. 1 changed meanwhile and was left alone. 1 could not be applied. 1 could not be confirmed."
    sent = sorted(v["id"] for _, v in store.mutations)
    assert sent == [gid(1001), gid(1002), gid(1003), gid(1005), gid(1006)], "the stale one was never sent; each other member exactly once"
    outcomes = {c.label: c.code for c in batch.children}
    assert outcomes == {"#1001": "verified", "#1002": "service_unavailable", "#1003": "unverified", "#1004": "stale", "#1005": "verified", "#1006": "verified"}
    assert store.orders[gid(1001)]["tags"] == ["delayed"] and store.orders[gid(1004)]["tags"] == ["admin"]
    # Once. A second gesture answers with the settled outcome and sends nothing.
    again = await batches.commit(batch.batch_id, "b1", caller="o", spec_lookup=lookup, nonce=batch.arm_nonce)
    assert again.code == "already_executed" and len(store.mutations) == 5
    # The result card: counts and each member, and never "all done".
    card = present_batch_state(batch, session=session, code="done")[0]
    assert card["type"] == "batch_result" and card["data"]["title"] == "Tags added: 3 of 6" and card["data"]["all_verified"] is False
    assert card["data"]["counts"]["verified"] == 3 and {r["label"]: r["outcome"] for r in card["data"]["rows"]}["#1004"] == "changed meanwhile, left alone"
    assert "The 3 marked not applied were left as they were" in card["data"]["note"] and card["data"]["summary"] == "3 applied, 3 not"
    # The undo is a batch of exactly the proven members.
    undo = session.batches[batch.undo_id]
    assert undo.undo_of == batch.batch_id and sorted(c.label for c in undo.children) == ["#1001", "#1005", "#1006"] and undo.interaction == "hold_to_arm"
    back = await gesture(batches, undo)
    assert back.code == "done" and back.spoken == "Undid 3 of the 3 orders." and undo.counts["verified"] == 3
    assert all(store.orders[gid(n)]["tags"] == [] for n in (1001, 1005, 1006)) and store.orders[gid(1003)]["tags"] == []


async def test_two_gestures_at_once_are_one_run(engine, batches, session):
    store = store_of(4)
    ws = orders_set(session, store)
    _, batch, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    assert batch.interaction == "tap_commit"
    first, second = await asyncio.gather(
        batches.commit(batch.batch_id, "b1", caller="o", spec_lookup=lookup),
        batches.commit(batch.batch_id, "b1", caller="o", spec_lookup=lookup),
    )
    assert {first.code, second.code} == {"done", "already_executed"}
    assert len(store.mutations) == 4 and batch.counts["verified"] == 4 and batch.all_verified


async def test_a_member_cannot_be_committed_or_armed_on_its_own(engine, batches, session):
    store = store_of(3)
    ws = orders_set(session, store)
    _, batch, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    child = batch.eligible[0].proposal_id
    alone = await engine.commit(child, "b1", caller="o", spec_lookup=lookup)
    assert alone.code == "batch_member" and store.mutations == [] and session.proposal(child).status is ActionStatus.PENDING
    _, code = engine.arm(child, "b1")
    assert code == "batch_member"
    # And a forged batch id on a member is not the batch either.
    forged = await engine.commit(child, "b1", caller="o", spec_lookup=lookup, via_batch="batch_000000000000")
    assert forged.code == "batch_member" and store.mutations == []


async def test_a_batch_expires_with_its_children_and_a_new_instruction_withdraws_it(engine, batches, session, clock):
    store = store_of(3)
    ws = orders_set(session, store)
    _, batch, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    batches.deliver(batch.batch_id)
    clock.now += batches.ttl_s + 1
    late = await batches.commit(batch.batch_id, "b1", caller="o", spec_lookup=lookup)
    assert late.code == "expired" and batch.status is BatchStatus.EXPIRED and store.mutations == []
    assert all(session.proposal(c.proposal_id).status in (ActionStatus.EXPIRED, ActionStatus.REVOKED) for c in batch.eligible)
    clock.now += 1
    _, second, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    assert second is not batch and second.status is BatchStatus.PENDING
    revoked = engine.revoke_pending(session, "new instruction") + batches.revoke_pending(session, "new instruction")
    engine.advance_epoch(session, "new instruction")
    batches.advance_epoch(session)
    assert second.batch_id in revoked and second.status is BatchStatus.REVOKED
    gone = await batches.commit(second.batch_id, "b1", caller="o", spec_lookup=lookup)
    assert gone.code == "revoked" and store.mutations == []


async def test_the_wrong_session_and_an_unknown_batch_are_refused(engine, batches, session):
    store = store_of(2)
    ws = orders_set(session, store)
    _, batch, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    assert (await batches.commit(batch.batch_id, "someone-else", caller="o", spec_lookup=lookup)).code == "wrong_session"
    assert (await batches.commit("batch_000000000000", "b1", caller="o", spec_lookup=lookup)).code == "unknown"
    assert batches.arm(batch.batch_id, "someone-else") == (None, "wrong_session")
    assert store.mutations == [] and batch.status is BatchStatus.PENDING


async def test_a_batch_that_runs_out_of_time_says_not_attempted_and_withdraws_the_rest(engine, batches, session, monkeypatch):
    store = store_of(3)
    ws = orders_set(session, store)
    _, batch, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    monkeypatch.setattr(batch_module, "COMMIT_BUDGET_S", 0.0)
    result = await gesture(batches, batch)
    assert result.code == "done" and batch.counts["not_attempted"] == 3 and batch.counts["verified"] == 0
    assert result.spoken == "Tagged 0 of the 3 orders. 3 were not attempted."
    assert store.mutations == [] and all(session.proposal(c.proposal_id).status is ActionStatus.REVOKED for c in batch.eligible)
    assert batch.undo_id is None, "nothing was done, so there is nothing to undo"


async def test_bulk_remove_takes_off_only_what_each_order_has(engine, batches, session):
    store = store_of(4, tagged={1: ["hold", "vip"], 2: ["vip"], 3: ["HOLD"], 4: []})
    ws = orders_set(session, store)
    text, batch, _ = await stage(session, "batch_order_tags_remove", set_id=ws.set_id, tags=["hold"])
    assert "2 of the 4 orders" in text and "has none of those tags: 2" in text
    result = await gesture(batches, batch)
    assert result.spoken == "Took the tags off 2 of the 2 orders."
    assert store.orders[gid(1001)]["tags"] == ["vip"] and store.orders[gid(1003)]["tags"] == [] and store.orders[gid(1002)]["tags"] == ["vip"]


async def test_a_large_batch_takes_a_hold_and_a_drag(engine, batches, session):
    store = store_of(DRAG_MIN)
    ws = orders_set(session, store)
    _, batch, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    assert batch.interaction == "hold_drag_target" and batch.risk == "RED"
    result = await gesture(batches, batch)
    assert result.code == "done" and batch.counts["verified"] == DRAG_MIN and len(store.mutations) == DRAG_MIN


# ---------------------------------------------------------------------------- the ledger


async def test_the_ledger_records_the_batch_by_ids_and_counts_never_by_name(engine, batches, session, tmp_path):
    ledger = ActionLedger(tmp_path)
    engine.ledger = ledger
    batches.ledger = ledger
    store = store_of(3, tagged={2: ["hold"]})
    ws = orders_set(session, store)
    _, batch, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["hold"])
    await gesture(batches, batch)
    entries = ledger.read()
    lines = [e for e in entries if e.get("batch_id") == batch.batch_id and "proposal_id" not in e]
    assert [e["event"] for e in lines] == ["PROPOSED", "EXECUTING", "DONE"]
    assert lines[0]["requested"] == 3 and lines[0]["eligible"] == 2 and lines[0]["excluded"] == 1 and lines[0]["reason"] == "already has those tags: 1"
    assert set(lines[0]["children"]) == {c.proposal_id for c in batch.eligible} and lines[0]["set_id"] == ws.set_id
    assert lines[-1]["counts"]["verified"] == 2 and lines[-1]["caller"] == "o"
    children = [e for e in entries if e.get("proposal_id") in {c.proposal_id for c in batch.eligible}]
    assert children and all(e["batch_id"] == batch.batch_id for e in children)
    assert "#1001" not in json.dumps(lines) and "delayed orders" not in json.dumps(lines)


# ------------------------------------------------------------------------------ the inbox

THREADS = {
    "18f0000000000001": [msg("m1", from_="Ben <ben@example.com>", subject="Order 1001", mid="<a@x>", labels=["INBOX"])],
    "18f0000000000002": [msg("m2", from_="Flo <flo@example.com>", subject="Order 1002", mid="<b@x>", labels=["INBOX", "UNREAD"])],
    "18f0000000000003": [msg("m3", from_="Gus <gus@example.com>", subject="Order 1003", mid="<c@x>", labels=["SENT"])],
}


@pytest.fixture()
def box():
    inbox = FakeGmail()
    inbox.threads = {tid: [dict(m) for m in ms] for tid, ms in THREADS.items()}

    async def customer_of(order_id: str = "", customer_id: str = "") -> dict:
        n = str(order_id or customer_id).rsplit("/", 1)[-1]
        return {"name": {"1001": "Ben Ade", "1002": "Flo Okoro"}.get(n, "Gus Lee"), "email": f"c{n}@example.com", "label": f"#{n}" if order_id else ""}

    gmail_writes.bind(inbox, customer=customer_of, policy=lambda: Policy())
    yield inbox
    gmail_writes.bind(None)


async def test_bulk_archive_leaves_the_inbox_and_the_undo_puts_them_back(engine, batches, session, box):
    ws = sets.create(session, kind="emails", members=list(THREADS), label="email: order", labels={tid: ms[0]["headers"]["subject"] for tid, ms in THREADS.items()})
    text, batch, calls = await stage(session, "batch_email_archive", set_id=ws.set_id)
    assert "2 of the 3 emails" in text and "1 excluded (not in the inbox: 1)" in text
    assert batch.interaction == "tap_commit" and [c.label for c in batch.excluded] == ["Order 1003"]
    card = present(calls, session=session)[0]["data"]
    assert card["title"] == "Archive 2 threads" and card["members"] == ["Order 1001", "Order 1002"], "the set's own names for the threads"
    result = await gesture(batches, batch)
    assert result.spoken == "Archived 2 of the 2 threads."
    assert "INBOX" not in box.thread_labels("18f0000000000001") and "INBOX" not in box.thread_labels("18f0000000000002")
    undo = session.batches[batch.undo_id]
    back = await gesture(batches, undo)
    assert back.code == "done" and "INBOX" in box.thread_labels("18f0000000000001") and "INBOX" in box.thread_labels("18f0000000000002")


async def test_bulk_drafts_fill_the_template_per_customer_and_preview_the_first(engine, batches, session, box, monkeypatch):
    store = store_of(2)
    ws = orders_set(session, store)
    monkeypatch.setattr(batch_tools, "_age_days", lambda placed_at, **kw: 8)
    text, batch, calls = await stage(
        session, "batch_email_drafts", set_id=ws.set_id, subject="Your order {order_number}",
        body="Hi {first_name},\n\nOrder {order_number} has been with us {order_age_days} days. Sorry for the wait.",
    )
    assert "2 of the 2 orders" in text and batch.interaction == "tap_commit"
    card = present(calls, session=session)[0]["data"]
    assert card["title"] == "Save 2 drafts" and card["summary"] == "" and "{first_name}" in card["body"] and "One draft per order" in card["detail"]
    assert card["preview"]["to"] == "Ben Ade <c1001@example.com>" and card["preview"]["subject"] == "Your order 1001"
    assert card["preview"]["body"].startswith("Hi Ben,\n\nOrder 1001 has been with us 8 days.") and card["preview"]["body"].rstrip().endswith("CROOKS")
    assert box.drafts == {}, "nothing saved before the gesture"
    result = await gesture(batches, batch)
    assert result.spoken == "Saved drafts for 2 of the 2 orders.", "a set of orders gets a draft per order, and says so"
    bodies = sorted(d["parsed"]["body"] for d in box.drafts.values())
    assert bodies[0].startswith("Hi Ben,\n\nOrder 1001 has been with us 8 days") and bodies[1].startswith("Hi Flo,\n\nOrder 1002 has been with us 8 days")
    assert sorted(d["parsed"]["to"] for d in box.drafts.values()) == ["Ben Ade <c1001@example.com>", "Flo Okoro <c1002@example.com>"]
    assert not any(m["labels"] == ["SENT"] for ms in box.threads.values() for m in ms if m["id"].startswith("s")), "drafts, never sent"


async def test_a_draft_template_is_checked_before_any_customer_is_read(engine, batches, session, box):
    store = store_of(2)
    ws = orders_set(session, store)
    text, batch, _ = await stage(session, "batch_email_drafts", set_id=ws.set_id, subject="Hi", body="Dear {surname}, hello.")
    assert text.startswith("ERROR") and "{surname} is not a placeholder" in text and batch is None
    customers = sets.create(session, kind="customers", members=["gid://shopify/Customer/7"], label="vips")
    text, _, _ = await stage(session, "batch_email_drafts", set_id=customers.set_id, subject="Hi", body="Your order {order_number}")
    assert text.startswith("ERROR") and "{order_number} is not a placeholder" in text
    text, _, _ = await stage(session, "batch_email_drafts", set_id=ws.set_id, subject="Hi", body="See <b>this</b>")
    assert text.startswith("ERROR") and "plain text" in text
    assert store.reads == 0 and box.calls == [] and session.batches == {}


def test_placeholders_are_filled_only_from_what_the_mac_read():
    assert batch_tools.fill("Hi {first_name}, {order_number} {nope}", {"first_name": "Ben", "order_number": "1001"}) == "Hi Ben, 1001 {nope}"
    assert batch_tools._age_days("2026-09-01T10:00:00Z") is not None and batch_tools._age_days("not a date") is None


# --------------------------------------------------------------------------- the routes

OWNER = "owner@example.com"
PROXIED = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.9"}


@pytest.fixture()
async def client(monkeypatch):
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.main import app
    from app.providers import max_agent_sdk
    from app.session.manager import SessionManager
    from tests.test_actions_routes import FakeProvider

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = FakeProvider()
        store = store_of(3, tagged={3: ["hold"]})
        runtime.shopify = store
        runtime.actions.ledger = NullLedger()
        runtime.batches.ledger = NullLedger()
        runtime.sessions = SessionManager()
        runtime.settings = runtime.settings.model_copy(update={"writes_enabled": True, "allowed_logins": OWNER, "writes_local_owner": False, "tailscale_verify": False})
        app.state.allowed_logins = runtime.allowed_logins
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.store = store
            c.runtime = runtime
            yield c


async def test_the_routes_take_a_batch_id_and_a_session_and_nothing_else(client):
    runtime = client.runtime
    session = runtime.sessions.get_or_create("s1")
    session.epoch = max(session.epoch, 1)
    ws = orders_set(session, client.store, clock=None)
    calls: list = []
    text = await dispatch("batch_order_tags_add", {"set_id": ws.set_id, "tags": ["hold"]}, session=session, timeout_s=10, calls=calls)
    assert text.startswith("PROPOSED BATCH")
    batch_id = calls[-1].proposal_id
    # State before the gesture: the card, from the Mac, for this login only.
    seen = await client.get(f"/batches/{batch_id}", params={"session_id": "s1"}, headers=PROXIED)
    assert seen.status_code == 200 and seen.json()["ui"][0]["type"] == "batch_action" and seen.json()["eligible"] == 2
    stranger = await client.post(f"/batches/{batch_id}/commit", data={"session_id": "s1"}, headers={"Tailscale-User-Login": "x@example.com", "X-Forwarded-For": "100.64.0.8"})
    assert stranger.status_code == 403 and client.store.mutations == []
    missing = await client.post("/batches/batch_000000000000/commit", data={"session_id": "s1"}, headers=PROXIED)
    assert missing.status_code == 404
    # The body cannot choose members or tags: whatever it carries, the stored batch runs.
    done = await client.post(f"/batches/{batch_id}/commit", data={"session_id": "s1", "tags": "vip", "members": "gid://shopify/Order/9"}, headers=PROXIED)
    body = done.json()
    assert done.status_code == 200 and body["status"] == "done" and body["counts"]["verified"] == 2 and body["counts"]["excluded"] == 1
    assert body["ui"][0]["type"] == "batch_result" and body["undo"]["batch_id"] and body["spoken"] == "Tagged 2 of the 2 orders."
    assert sorted(v["tags"] for _, v in client.store.mutations) == [["hold"], ["hold"]]
    again = await client.post(f"/batches/{batch_id}/commit", data={"session_id": "s1"}, headers=PROXIED)
    assert again.status_code == 200 and again.json()["code"] == "already_executed" and len(client.store.mutations) == 2
    # A turn's answer carries the batch card, and a new instruction withdraws it.
    session2 = runtime.sessions.get_or_create("s2")
    session2.epoch = 1
    ws2 = orders_set(session2, client.store, clock=None)
    calls2: list = []
    await dispatch("batch_order_tags_add", {"set_id": ws2.set_id, "tags": ["late"]}, session=session2, timeout_s=10, calls=calls2)
    pending_id = calls2[-1].proposal_id
    ui = present([ToolCall(name="batch_order_tags_add", args={}, ok=True, proposal_id=pending_id)], session=session2)
    assert ui[0]["type"] == "batch_action"
    revoked = runtime.batches.revoke_pending(session2, "new instruction")
    assert revoked == [pending_id]
    after = await client.get(f"/batches/{pending_id}", params={"session_id": "s2"}, headers=PROXIED)
    assert after.json()["status"] == "revoked" and after.json()["ui"][0]["type"] == "error"


async def test_a_latched_backend_refuses_a_batch_before_claiming_it(engine, batches, session, monkeypatch):
    """Read-only has to be checked before the claim, not per child.

    Without the check the batch claimed itself, ran every child through an engine that refused
    each one, filed those refusals as "not attempted", finished DONE and spoke "Tagged 0 of the
    3 orders." So the owner was told a batch had run when none had, and the batch was terminal:
    the same gesture on a backend that may write could never commit it. Nothing may be claimed.
    """
    store = store_of(3)
    ws = orders_set(session, store)
    _, batch, _ = await stage(session, "batch_order_tags_add", set_id=ws.set_id, tags=["delayed"])
    assert batch is not None

    monkeypatch.setattr(readonly, "_engaged", True)
    monkeypatch.setattr(readonly, "_reason", "a test")
    result = await gesture(batches, batch)

    assert result.code == "read_only"
    assert result.spoken == "", "a refused batch says nothing about having run"
    assert batch.status is BatchStatus.PENDING, "the card is untouched and still committable"
    assert not batch.terminal
    assert store.mutations == [], "no Shopify change was sent"
