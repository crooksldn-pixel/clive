"""The anticipation layer (§18) and the learned layer behind it (§19).

Every hard rule in those two sections is an oracle here, and each one can fail: a speculative
read that is not cancelled when the owner speaks, a prediction that fires below the confidence
threshold, a table that learns from three observations, a decay that does not decay, a reset
that leaves rows behind, a predicted read that looks like a requested one, or any path at all
from this layer to a write — each of those breaks a test in this file.
"""

from __future__ import annotations

import asyncio

import pytest

from app.anticipation import engine as engine_mod
from app.anticipation import rules as rules_mod
from app.anticipation.learning import (
    HALF_LIFE_S,
    MIN_OBSERVATIONS,
    THRESHOLD,
    Learner,
)
from app.anticipation.models import P1, P2, PREDICTED, REQUESTED, Prediction, Signal, clean_state
from app.memory import ENTITY, Memory
from app.memory.prefetch import Prefetcher
from app.providers.base import ToolCall
from app.session.models import Session


@pytest.fixture()
def session():
    s = Session(session_id="s1", login="owner@example.com")
    s.turn_id = "turn_x"
    return s


@pytest.fixture()
def learner():
    return Learner(clock=_clock())


def _clock(start: float = 1_000_000.0):
    """A clock a test can move. Decay is a fact about elapsed time, so it has to be steerable
    rather than waited for."""

    state = {"now": start}

    def clock() -> float:
        return state["now"]

    clock.advance = lambda seconds: state.__setitem__("now", state["now"] + seconds)  # type: ignore[attr-defined]
    return clock


@pytest.fixture()
def anticipator(learner):
    return engine_mod.Anticipator(learner=learner, prefetcher=Prefetcher(), memory=Memory())


def order_signal(**over) -> Signal:
    base = dict(
        event="order_opened", session_id="s1", login="owner@example.com", branch_id="b1",
        kind="order", ref="gid://shopify/Order/1", features=("unfulfilled", "international", "old"),
        ids={"order_id": "gid://shopify/Order/1", "customer_id": "gid://shopify/Customer/9",
             "email": "jo@example.com"},
        neighbours=("gid://shopify/Order/2",),
    )
    base.update(over)
    return Signal(**base)


@pytest.fixture()
def dispatched(monkeypatch):
    """Every read the layer makes, with a delay long enough to be caught in flight."""
    import app.tools.gmail_tools  # noqa: F401 — registered so the plan can name them
    import app.tools.shopify_tools  # noqa: F401

    seen: list[str] = []

    async def fake_dispatch(name, args, *, session, timeout_s, calls=None):  # noqa: ARG001
        seen.append(name)
        await asyncio.sleep(0.05)
        if calls is not None:
            calls.append(ToolCall(name=name, args=args, ok=True, duration_ms=50.0, result={"read": name}))
        return "{}"

    monkeypatch.setattr("app.tools.dispatch.dispatch", fake_dispatch)
    return seen


# --------------------------------------------------------------------- §18 the bounds


async def test_opening_an_order_starts_the_background_reads_and_one_guess(anticipator, session, dispatched):
    decision = await anticipator.on_signal(order_signal(), session=session)
    started = {p.why: p for p in decision.started}
    assert "order.customer_history" in started and started["order.customer_history"].tier == P1
    assert "order.shipping_state" in started
    # Three at a time is the bound, so the fourth rule is skipped with a reason rather than run.
    assert len(decision.started) <= anticipator.max_anticipated
    assert all(reason for reason in decision.skipped.values())
    await asyncio.sleep(0.1)


async def test_bounded_to_nothing_the_layer_reads_nothing_at_all(session, dispatched, learner):
    """The off switch. Bounding the source-spending reads to nothing while the Mac's own
    internal reads carried on would be a layer that says it is off and is not — and the bench
    half that measures "without anticipation" would be measuring with some of it."""
    off = engine_mod.Anticipator(learner=learner, prefetcher=Prefetcher(), memory=Memory(),
                                 max_anticipated=0, max_speculative=0)
    decision = await off.on_signal(order_signal(), session=session)
    assert decision.started == []
    assert set(decision.skipped.values()) == {"anticipation is switched off"}
    assert dispatched == []


async def test_the_thread_a_reply_would_need_is_read_on_a_hunch(anticipator, session, dispatched):
    """The "likely action prerequisite" of §18: writing a reply needs the thread read, and so
    does the tablet's own drilldown into it. Speculative, because most orders with an email on
    them never get a reply written."""
    signal = order_signal(ids={
        "order_id": "gid://shopify/Order/1", "customer_id": "gid://shopify/Customer/9",
        "email": "jo@example.com", "thread_id": "t_991",
    })
    decision = await anticipator.on_signal(signal, session=session)
    started = {p.why: p for p in decision.started}
    assert "order.email_thread" in started
    assert started["order.email_thread"].tier == P2 and started["order.email_thread"].tool == "gmail_read_thread"
    # Two of Gmail is the per-source bound, and this is the second.
    assert anticipator.prefetcher.in_flight_for(signal.scope, source="gmail") <= anticipator.max_per_source
    await asyncio.sleep(0.15)


async def test_the_bound_counts_what_spends_a_sources_rate_and_not_the_macs_own_reads(anticipator, session, dispatched):
    """The internal shipping read asks a provider that is not connected and returns a
    dictionary: it spends no Shopify or Gmail rate, so counting it against the four would cost
    a real read for nothing. It is still bounded by the prefetcher's own wall."""
    signal = order_signal(ids={
        "order_id": "gid://shopify/Order/1", "customer_id": "gid://shopify/Customer/9",
        "email": "jo@example.com", "thread_id": "t_991",
    })
    decision = await anticipator.on_signal(signal, session=session)
    spending = [p for p in decision.started if p.source != "mac"]
    internal = [p for p in decision.started if p.source == "mac"]
    assert len(spending) <= anticipator.max_anticipated
    assert internal, "the shipping context was not read at all"
    assert len(decision.started) > anticipator.max_anticipated - 1
    for source in ("shopify", "gmail"):
        assert len([p for p in spending if p.source == source]) <= anticipator.max_per_source
    await asyncio.sleep(0.15)


async def test_a_prediction_whose_answer_is_already_held_does_not_run(anticipator, session, dispatched):
    anticipator.memory.put(ENTITY, "customer:gid://shopify/Customer/9", {"held": True}, source="shopify")
    decision = await anticipator.on_signal(order_signal(), session=session)
    assert decision.skipped.get("history:gid://shopify/Customer/9") == "already held, and fresh"
    assert "order.customer_history" not in {p.why for p in decision.started}
    await asyncio.sleep(0.1)


async def test_the_same_read_is_not_started_twice(anticipator, session, dispatched):
    first = await anticipator.on_signal(order_signal(), session=session)
    assert first.started
    again = await anticipator.on_signal(order_signal(), session=session)
    assert not again.started
    assert all("in flight" in why or "already" in why or "full" in why for why in again.skipped.values())
    await asyncio.sleep(0.1)


async def test_the_speculative_lane_has_its_own_smaller_bound(session, dispatched, learner):
    a = engine_mod.Anticipator(learner=learner, prefetcher=Prefetcher(), memory=Memory(),
                               max_anticipated=6, max_speculative=1)
    signal = order_signal(neighbours=("gid://shopify/Order/2", "gid://shopify/Order/3"))
    decision = await a.on_signal(signal, session=session)
    speculative = [p for p in decision.started if p.tier == P2]
    assert len(speculative) <= 1
    await asyncio.sleep(0.1)


async def test_the_owner_asking_for_something_stands_the_speculation_down(anticipator, session, dispatched):
    engine_mod.install(anticipator)
    try:
        decision = await anticipator.on_signal(order_signal(), session=session)
        assert any(p.tier == P2 for p in decision.started), "no speculative read to cancel"
        in_flight_before = anticipator.prefetcher.in_flight_for(engine_mod.scope_of(session))
        # The owner asks for something. A REQUESTED plan is what the scheduler runs for a
        # question, a tap or a recipe, and that is where the stand-down happens.
        from app.reads.scheduler import Read, ReadPlan, run_plan

        await run_plan(ReadPlan([Read("wanted", "shopify_find_order", {"query": "1938"})], label="asked"), session=session)
        assert anticipator.prefetcher.in_flight_for(engine_mod.scope_of(session), lane=P2) == 0
        assert anticipator.prefetcher.in_flight_for(engine_mod.scope_of(session)) < in_flight_before
        assert any(row["outcome"] == "cancelled" for row in anticipator.explain())
    finally:
        engine_mod.install(None)
        await asyncio.sleep(0.1)


async def test_a_predicted_plan_does_not_cancel_itself(anticipator, session, dispatched):
    engine_mod.install(anticipator)
    try:
        await anticipator.on_signal(order_signal(), session=session)
        before = anticipator.prefetcher.in_flight_for(engine_mod.scope_of(session), lane=P2)
        from app.reads.scheduler import Read, ReadPlan, run_plan

        await run_plan(
            ReadPlan([Read("guess", "shopify_order_detail", {"order_id": "x"})], label="anticipate:x", origin=PREDICTED),
            session=session,
        )
        assert anticipator.prefetcher.in_flight_for(engine_mod.scope_of(session), lane=P2) == before
    finally:
        engine_mod.install(None)
        await asyncio.sleep(0.1)


async def test_a_question_asked_of_one_half_leaves_the_other_halfs_reads_alone(session, dispatched, learner, monkeypatch):
    """Branch-safe (§18). The split workspace is two places the owner works; a question asked
    of one is not a reason to throw away what was being read for the other.

    The bounds are deliberately loosened here: they are per conversation, because a source's
    rate is shared by both halves, and this test is about the cancellation rather than the
    budget — with the shipped bounds the second half's Shopify reads are refused for the right
    reason and there would be nothing to prove.
    """
    from app.memory import prefetch as prefetch_mod

    monkeypatch.setattr(prefetch_mod, "MAX_IN_FLIGHT", 12)
    anticipator = engine_mod.Anticipator(
        learner=learner, prefetcher=Prefetcher(), memory=Memory(),
        max_anticipated=8, max_speculative=4, max_per_source=4,
    )
    engine_mod.install(anticipator)
    try:
        left = await anticipator.on_signal(order_signal(branch_id="b_left"), session=session)
        right = await anticipator.on_signal(
            order_signal(branch_id="b_right", ref="gid://shopify/Order/5",
                         ids={"order_id": "gid://shopify/Order/5", "customer_id": "gid://shopify/Customer/5"},
                         neighbours=("gid://shopify/Order/6",)),
            session=session,
        )
        assert any(p.tier == P2 for p in left.started) and any(p.tier == P2 for p in right.started)
        assert right.cancelled == 0, "opening a record on the other half cancelled this one's reads"
        # The owner speaks to the right-hand half: `acting_branch` is which half a turn is
        # addressed to, and it is the only one that stands down.
        session.acting_branch = "b_right"
        anticipator.owner_read(session)
        scope = engine_mod.scope_of(session)
        assert anticipator.prefetcher.in_flight_for(scope, lane=P2) >= 1, "the other half was cancelled too"
        left_over = [r for r in anticipator.explain() if r["outcome"] == "cancelled"]
        assert left_over and all(r["read"] for r in left_over)
    finally:
        engine_mod.install(None)
        await asyncio.sleep(0.15)


async def test_moving_to_another_record_cancels_what_was_read_about_the_last_one(anticipator, session, dispatched):
    await anticipator.on_signal(order_signal(), session=session)
    assert anticipator.prefetcher.in_flight_for(engine_mod.scope_of(session)) > 0
    moved = await anticipator.on_signal(order_signal(ref="gid://shopify/Order/77", ids={"order_id": "gid://shopify/Order/77"}), session=session)
    assert moved.cancelled > 0
    await asyncio.sleep(0.1)


async def test_the_same_record_wanted_by_two_conversations_is_one_request(anticipator, dispatched, monkeypatch):
    """Dedupe identical in-flight reads, coalesce callers (§18). The prefetch TASKS are per
    conversation — one may be cancelled without the other losing its answer — but the flight
    underneath is keyed by the read, and so is the cache it lands in."""
    from app.memory import coalesce

    coalesce.install(coalesce.Coalescer())
    one = Session(session_id="s1", login="owner@example.com")
    two = Session(session_id="s2", login="owner@example.com")
    monkeypatch.setattr(rules_mod, "deterministic", lambda s: [
        Prediction(key="history:shared", tier=P1, tool="shopify_customer_history",
                   args={"customer_id": "c1"}, why="order.customer_history",
                   memory=(ENTITY, "customer:c1")),
    ])
    first = await anticipator.on_signal(order_signal(session_id="s1"), session=one)
    second = await anticipator.on_signal(order_signal(session_id="s2"), session=two)
    assert first.started, "the first conversation predicted nothing"
    await asyncio.sleep(0.15)
    # Either the second was refused because the read was already in flight, or it joined that
    # flight. Both are one request, which is the property; which one happens depends on
    # whether the first task had reached the coalescer yet.
    assert dispatched.count("shopify_customer_history") == 1, dispatched
    assert coalesce.current().joined + len(second.skipped) >= 1
    # And the answer is in the ONE shared cache, for whichever conversation asks for it next.
    held = anticipator.memory.get(ENTITY, "customer:c1")
    assert held is not None and held.provenance["origin"] == PREDICTED


async def test_two_conversations_never_cancel_or_count_against_each_other(anticipator, dispatched):
    one = Session(session_id="s1", login="owner@example.com")
    two = Session(session_id="s2", login="somebody@else")
    await anticipator.on_signal(order_signal(session_id="s1"), session=one)
    await anticipator.on_signal(order_signal(session_id="s2", login="somebody@else"), session=two)
    scope_one, scope_two = engine_mod.scope_of(one), engine_mod.scope_of(two)
    assert scope_one != scope_two
    assert anticipator.prefetcher.in_flight_for(scope_one) > 0
    assert anticipator.prefetcher.in_flight_for(scope_two) > 0
    anticipator.owner_read(one)
    assert anticipator.prefetcher.in_flight_for(scope_two) > 0
    await asyncio.sleep(0.1)


# --------------------------------------------------------------------- §18 no writes, ever


def test_no_rule_can_ever_name_a_write():
    """Structural, not a spot check: every registered rule's prediction is either a registered
    read tool or a name in the closed internal table. A rule that named a write tool, or a tool
    that later gained one, fails here."""
    import app.tools.gmail_writes  # noqa: F401
    import app.tools.shopify_writes  # noqa: F401
    from app.anticipation import internal
    from app.tools import registry

    signal = order_signal()
    for rule in rules_mod.all_rules():
        prediction = rule.build(signal)
        if prediction is None:
            continue
        if prediction.internal:
            assert internal.known(prediction.internal)
            continue
        spec = registry.get(prediction.tool)
        assert spec.write is None and spec.batch is None, f"{rule.rule_id} names {prediction.tool}"


async def test_a_prediction_naming_a_write_is_refused_and_never_dispatched(anticipator, session, monkeypatch):
    import app.tools.shopify_writes  # noqa: F401

    called: list[str] = []

    async def fake_dispatch(name, args, *, session, timeout_s, calls=None):  # noqa: ARG001
        called.append(name)
        return "{}"

    monkeypatch.setattr("app.tools.dispatch.dispatch", fake_dispatch)
    monkeypatch.setattr(rules_mod, "deterministic", lambda _s: [
        Prediction(key="bad", tier=P1, tool="shopify_order_note_append", args={"order_id": "1"}, why="a_write"),
    ])
    decision = await anticipator.on_signal(order_signal(), session=session)
    assert decision.skipped.get("bad") == "not a read"
    assert not decision.started and called == []
    assert anticipator.counts()["refused_writes"] == 1


def test_the_internal_reads_are_a_closed_table():
    from app.anticipation import internal

    assert set(internal.READS) == {"shipping_status"}
    assert not internal.known("shopify_order_note_append")


# --------------------------------------------------------------------- §19 what is learned


def test_a_state_cannot_carry_an_identifier():
    assert clean_state("order_opened", ("unfulfilled", "international")) == "order_opened[international,unfulfilled]"
    # Anything not in the vocabulary is dropped rather than recorded.
    assert clean_state("order_opened", ("jo@example.com", "1938", "unfulfilled")) == "order_opened[unfulfilled]"
    with pytest.raises(ValueError):
        clean_state("order_1938_opened")


def test_a_signals_state_is_all_the_learner_is_given(learner):
    signal = order_signal()
    learner.observe(signal.state, "email_checked")
    rows = learner.inspect()["rows"]
    assert rows and all("Order" not in row["state"] and "@" not in row["state"] for row in rows)
    assert rows[0]["state"] == "order_opened[international,old,unfulfilled]"


def test_nothing_is_learned_below_the_minimum_number_of_observations(learner):
    state = order_signal().state
    for _ in range(MIN_OBSERVATIONS - 1):
        learner.observe(state, "tracking_checked")
    assert learner.likely(state) == []
    learner.observe(state, "tracking_checked")
    assert [e.event for e in learner.likely(state)] == ["tracking_checked"]


def test_a_transition_below_the_confidence_threshold_does_not_predict(learner):
    state = order_signal().state
    # Seen often enough, but a coin toss between two next steps: neither clears the bar.
    for _ in range(MIN_OBSERVATIONS + 2):
        learner.observe(state, "tracking_checked")
        learner.observe(state, "email_checked")
    assert learner.likely(state) == []
    assert 0.4 < learner.confidence(state, "tracking_checked") < THRESHOLD
    for _ in range(12):
        learner.observe(state, "tracking_checked")
    assert [e.event for e in learner.likely(state)] == ["tracking_checked"]


def test_old_patterns_decay(learner):
    state = order_signal().state
    for _ in range(8):
        learner.observe(state, "tracking_checked")
    before = learner.inspect()["rows"][0]
    assert before["predicts"] is True
    learner.clock.advance(HALF_LIFE_S * 3)      # a season and a half later
    after = learner.inspect()["rows"][0]
    assert after["weight"] < before["weight"] / 4
    assert after["observations"] == before["observations"], "the history is kept; the weight is what decays"
    assert after["predicts"] is False and learner.likely(state) == []


def test_a_reset_empties_the_table(learner, tmp_path):
    kept = Learner(path=tmp_path / "transitions.json", clock=learner.clock)
    state = order_signal().state
    for _ in range(6):
        kept.observe(state, "tracking_checked")
    kept.save()
    assert (tmp_path / "transitions.json").exists()
    assert kept.reset() > 0
    assert kept.inspect()["rows"] == [] and kept.likely(state) == []
    assert not (tmp_path / "transitions.json").exists()
    # And a fresh learner over the same path finds nothing.
    assert Learner(path=tmp_path / "transitions.json", clock=learner.clock).inspect()["rows"] == []


def test_the_table_survives_a_restart_but_refuses_a_hand_edited_identifier(tmp_path):
    path = tmp_path / "transitions.json"
    first = Learner(path=path, clock=_clock())
    state = order_signal().state
    for _ in range(5):
        first.observe(state, "email_checked")
    first.save()
    again = Learner(path=path, clock=first.clock)
    assert [e.event for e in again.likely(state)] == ["email_checked"]
    path.write_text(path.read_text().replace(state, "order_opened[unfulfilled]_1938"), encoding="utf-8")
    third = Learner(path=path, clock=first.clock)
    assert third.inspect()["rows"] == [] and third.rejected >= 1


def test_the_learned_vocabulary_holds_no_write(learner):
    """§19: no learned write execution, ever. The events the table can hold are reads and
    moves; there is no name in it that could be turned into a change."""
    from app.anticipation.models import EVENTS

    assert learner.observe(order_signal().state, "order_cancelled") is None
    assert learner.rejected == 1
    for event in EVENTS:
        assert not any(word in event for word in ("cancel", "refund", "send", "fulfil", "tag", "set", "create"))


# --------------------------------------------------------------------- §19 telling them apart


async def test_a_predicted_read_is_labelled_differently_from_a_requested_one(anticipator, session, dispatched, tmp_path):
    """The distinction rides on the record that was already there: the read plan's origin, and
    the memory entry's provenance — not on a parallel ledger kept by this layer."""
    from app.observability import session as sessions_mod
    from app.observability import timeline as timeline_mod

    timeline = timeline_mod.Timeline(sessions_mod.TestSessions(tmp_path))
    timeline_mod.install(timeline)
    timeline.start("anticipation")
    try:
        await anticipator.on_signal(order_signal(), session=session)
        await asyncio.sleep(0.2)
        from app.reads.scheduler import Read, ReadPlan, run_plan

        await run_plan(ReadPlan([Read("asked", "shopify_find_order", {"query": "1938"})], label="asked"), session=session)
        timeline.flush()
        events = timeline_mod.read_events(sessions_mod.TestSessions(tmp_path).timeline_path(timeline.active))
    finally:
        timeline.stop()
        timeline_mod.install(timeline_mod.NullTimeline())
    plans = [e for e in events if e["kind"] == "read_plan"]
    origins = {e.get("label"): e.get("origin") for e in plans}
    assert origins.get("asked") == REQUESTED
    assert any(label and label.startswith("anticipate:") and origin == PREDICTED for label, origin in origins.items())
    # Every prediction is logged, with what asked for it.
    predictions = [e for e in events if e["kind"] == "prediction"]
    assert predictions and all(e["origin"] == PREDICTED and e["why"] for e in predictions)
    # And what it filled in says so where the value is used.
    entry = anticipator.memory.get(ENTITY, "shipping:gid://shopify/Order/1")
    assert entry is not None and entry.public()["provenance"]["origin"] == PREDICTED


async def test_a_predicted_read_that_is_used_is_counted_as_such(anticipator, session, dispatched):
    await anticipator.on_signal(order_signal(), session=session)
    await asyncio.sleep(0.2)
    memory = anticipator.memory
    before = memory.counts()["predicted_hits"]
    assert memory.get(ENTITY, "customer:gid://shopify/Customer/9") is not None
    assert memory.counts()["predicted_hits"] == before + 1


async def test_the_debug_view_says_why_something_was_prefetched(anticipator, session, dispatched):
    await anticipator.on_signal(order_signal(), session=session)
    report = anticipator.report()
    assert report["counts"]["started"] >= 1
    rows = report["predictions"]
    assert rows and all(row["why"] and row["origin"] == PREDICTED for row in rows)
    assert {row["level"] for row in rows} <= {1, 2}
    assert report["learned"]["min_observations"] == MIN_OBSERVATIONS
    await asyncio.sleep(0.1)


async def test_a_learned_transition_reads_something_no_rule_would_have(anticipator, session, dispatched):
    """The brief's own example, mechanically: the owner checks the inbox on an old unfulfilled
    international order and then, again and again, looks at the tracking. No deterministic rule
    fires on "the inbox was checked" — so before the habit is learned nothing is read, and
    after it is, the tracking state is."""
    signal = Signal(
        event="email_checked", session_id="s1", login="owner@example.com", branch_id="b1",
        kind="order", ref="gid://shopify/Order/1", features=("unfulfilled", "international", "old"),
        ids={"order_id": "gid://shopify/Order/1"},
    )
    cold = await anticipator.on_signal(signal, session=session, learn=False)
    assert cold.started == [] and cold.skipped == {}
    for _ in range(8):
        anticipator.learner.observe(signal.state, "tracking_checked")
    warm = await anticipator.on_signal(signal, session=session, learn=False)
    learned = [p for p in warm.started if p.level == 2]
    assert learned, "the learned table predicted nothing"
    for prediction in learned:
        assert prediction.why == f"learned:{signal.state}->tracking_checked"
        assert prediction.tier == P2, "a learned read is speculative, whatever tier its rule is"
        assert prediction.observations >= MIN_OBSERVATIONS and prediction.confidence >= THRESHOLD
    await asyncio.sleep(0.1)


async def test_a_learned_habit_puts_the_read_it_is_about_first(anticipator, session, dispatched):
    """When a deterministic rule already makes the read, the habit does not add a second one —
    it moves that read to the front of the queue, which is what decides who gets the source's
    slots when four reads want two."""
    signal = order_signal()
    plain = anticipator._predictions(signal)
    assert [p.why for p in plain][0] == "order.customer_history"
    for _ in range(9):
        anticipator.learner.observe(signal.state, "tracking_checked")
    taught = anticipator._predictions(signal)
    first = taught[0]
    assert first.why == "order.shipping_state+learned"
    assert first.observations >= MIN_OBSERVATIONS and first.tier == P1
    assert len(taught) == len(plain), "a habit about a read already planned must not add a second"


async def test_a_suggestion_is_only_made_at_high_confidence_and_is_only_words(anticipator, session, dispatched):
    signal = order_signal()
    quiet = await anticipator.on_signal(signal, session=session, learn=False)
    assert quiet.suggestions == []
    for _ in range(10):
        anticipator.learner.observe(signal.state, "tracking_checked")
    loud = await anticipator.on_signal(signal, session=session, learn=False)
    assert loud.suggestions and loud.suggestions[0]["next"] == "tracking_checked"
    assert loud.suggestions[0]["confidence"] >= 0.8 and loud.suggestions[0]["level"] == 3
    # A suggestion is a sentence about a READ or a move. Nothing acts on it.
    assert all("cancel" not in s["why"] and "refund" not in s["why"] for s in loud.suggestions)
    await asyncio.sleep(0.1)


# --------------------------------------------------------------------- what a signal says


def test_the_shape_of_an_order_is_read_without_reading_the_order():
    from app.anticipation import signals

    features = signals.order_features({
        "fulfillment": "UNFULFILLED", "shipping_address": {"country_code": "IE"},
        "placed_at": "2020-01-01T00:00:00Z", "total": "£410.00",
        "email": {"available": True, "threads": [{"sender_match": True, "waiting_since": "5h"}]},
    })
    assert set(features) == {"unfulfilled", "international", "old", "high_value", "has_email",
                             "inbound_unanswered", "untracked"}
    # The inbox part is a dictionary whether or not anything correlated to the order, so what
    # counts is a thread. Read as the part's presence, every order in the shop has email on it.
    assert "no_email" in signals.order_features({"email": {"available": True, "threads": []}})
    home = signals.order_features({"fulfillment": "FULFILLED", "shipping_address": {"country_code": "GB"},
                                   "fulfillments": [{"tracking": "AB1"}]})
    assert "domestic" in home and "fulfilled" in home and "tracked" in home
    # Everything a signal carries has to survive the state's allow-list, or it is not learned.
    assert clean_state("order_opened", features)


def test_the_neighbour_predicted_is_the_one_the_cursor_moves_to():
    """A working set's members are ORDERED and the cursor is an index into them. Read through
    `members_by_id`, which hands back a frozenset, the guess was the wrong record whenever the
    hash said so — and a prediction about the wrong record is worse than no prediction."""
    from app.analytics import sets as working_sets
    from app.anticipation import signals

    session = Session(session_id="s1", login="owner@example.com")
    held = working_sets.create(session, kind="orders", members=["o1", "o2", "o3"], label="to go out")
    branch = session.branch()
    branch.workflow = type("W", (), {"set_id": held.set_id, "cursor": 0})()
    assert signals.neighbours_of(session, branch)[0] == "o2"
    branch.workflow.cursor = 1
    assert signals.neighbours_of(session, branch) == ("o3", "o1")
    branch.workflow.cursor = 2
    assert signals.neighbours_of(session, branch) == ("o2",)


def test_a_signal_built_from_an_order_keeps_the_ids_out_of_what_is_learned():
    from app.anticipation import signals

    session = Session(session_id="s1", login="owner@example.com")
    signal = signals.for_order(
        "gid://shopify/Order/1", {
            "order_id": "gid://shopify/Order/1", "fulfillment": "UNFULFILLED",
            "customer_id": "gid://shopify/Customer/9", "customer_email": "Jo@Example.com",
            "shipping_address": {"country_code": "IE"},
        },
        session=session, branch=session.branch(),
    )
    assert signal.ids == {"order_id": "gid://shopify/Order/1",
                          "customer_id": "gid://shopify/Customer/9", "email": "jo@example.com"}
    assert "@" not in signal.state and "Order" not in signal.state
    assert signal.scope == "owner@example.com|s1"


# --------------------------------------------------------------------- the owner's own view


@pytest.fixture()
async def macs_client(monkeypatch):
    """The application, as the Mac itself reaches it. Enough of test_routes.py's fixture to
    ask the two /anticipation routes and no more."""
    import httpx

    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.main import app
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


async def test_the_debug_view_is_the_owners_own_and_the_reset_empties_the_table(macs_client):
    """Inspectable and resettable (§19), and the owner's alone (the 2026-09-27 deploy review,
    F-05A): this is his view of what his machine has been guessing about him."""
    engine_mod.install(engine_mod.Anticipator(learner=Learner(), prefetcher=Prefetcher(), memory=Memory()))
    try:
        learned = engine_mod.current().learner
        for _ in range(6):
            learned.observe("order_opened[old,unfulfilled]", "tracking_checked")
        from app.main import app
        from tests.test_actions_routes import as_owner

        # A server nobody has said is anyone's answers nobody (F-05A/B): not the server itself.
        runtime = app.state.runtime
        as_owner(runtime, logins="", local=True)
        assert (await macs_client.get("/anticipation")).status_code == 403
        assert (await macs_client.post("/anticipation/reset")).status_code == 403
        # The owner's: his own device may look, another login may not, and the server itself
        # only when he has said it is him.
        as_owner(runtime, logins="owner@example.com", local=False)
        tablet = {"Tailscale-User-Login": "owner@example.com", "X-Forwarded-For": "100.64.0.9"}
        stranger = {"Tailscale-User-Login": "other@example.com", "X-Forwarded-For": "100.64.0.3"}
        assert (await macs_client.get("/anticipation", headers=tablet)).status_code == 200
        assert (await macs_client.get("/anticipation", headers=stranger)).status_code == 403
        assert (await macs_client.post("/anticipation/reset", headers=stranger)).status_code == 403
        assert (await macs_client.post("/anticipation/reset")).status_code == 403
        as_owner(runtime, logins="owner@example.com", local=True)
        body = (await macs_client.get("/anticipation")).json()
        assert body["learned"]["rows"] and body["learned"]["rows"][0]["next"] == "tracking_checked"
        assert body["counts"]["max_per_source"] >= 1
        reset = await macs_client.post("/anticipation/reset")
        assert reset.status_code == 200 and reset.json()["transitions_dropped"] >= 1
        assert reset.json()["learned"]["rows"] == []
        assert (await macs_client.get("/anticipation")).json()["learned"]["rows"] == []
    finally:
        engine_mod.install(None)
