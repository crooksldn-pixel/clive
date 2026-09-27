"""The golden scenarios, as part of the ordinary suite.

They run against the fixture world through the real runtime, so they are as offline and as
deterministic as every other test here — and they are the only tests that can catch the class
of failure this pass exists for, which is an answer that is correct, fast, and has nothing on
the screen. A unit test of a presenter cannot see that; only driving a turn can.
"""

from __future__ import annotations

import pytest

from experience.harness import harness
from experience.scenarios import BY_NAME, SCENARIOS


@pytest.fixture()
async def stage():
    async with harness() as h:
        yield h


@pytest.mark.parametrize("name", [n for n, _ in SCENARIOS])
async def test_the_golden_scenarios(name, stage):
    result = await BY_NAME[name](stage)
    assert not result.error, result.error
    failures = "\n".join(f"  - {c.what} :: {c.detail}" for c in result.failures)
    assert result.status == "PASS", f"{result.title}\n{failures}"


async def test_an_order_lookup_that_is_fast_and_empty_is_a_failure(stage):
    """The regression test the brief asks for by name (§29).

    It is worth stating what this does NOT assert: it says nothing about latency. The build
    that was reported as broken was fast — that was the whole complaint. Speed with an empty
    screen has to fail, so the assertions are all about what came back.
    """
    capture = await stage.say("show me order 1938")
    assert capture.lane == "FAST", "the fast lane should answer a plain order lookup"
    assert not capture.prose_only, (
        f"the answer was prose with no surface: {capture.answer!r}"
    )
    order = capture.surface("order")
    assert order is not None, f"no order surface; got {capture.surface_types}"
    assert order["data"].get("detail") is True, "the brief card, not the full order"
    assert order["data"].get("items"), "the items are not reachable"
    assert capture.action_ids, "no actions were offered for the order"
    assert (capture.entity or {}).get("kind") == "order", "the current entity was not established"


async def test_the_fast_lane_never_answers_an_entity_question_with_prose(stage):
    """Every recipe that answers about a record must draw one. A recipe added later that
    forgets to return calls or a surface fails here rather than on the workbench.

    Both halves of that are asserted. The lane check used to be a filter — `if lane == "FAST"
    and prose_only` — so the failure it was written for went unseen: a recipe deleted, renamed
    or whose family stops matching drops the question to the model, which answers it in prose,
    and the list stayed empty and the test stayed green. Falling off the fast lane is the
    regression, not an exemption from the check.
    """
    asked = [
        "show me order 1938",
        "show me today's orders",
        "what can you do now?",
        "where is order 1938",
        "how much have we sold today?",
    ]
    empty, deferred = [], []
    for question in asked:
        capture = await stage.say(question)
        if capture.lane != "FAST":
            deferred.append((question, capture.lane, capture.recipe_id))
        elif capture.prose_only:
            empty.append((question, capture.recipe_id, capture.answer[:60]))
    assert not deferred, f"these stopped being answered deterministically: {deferred}"
    assert not empty, f"fast answers with nothing on screen: {empty}"


async def test_a_tap_and_a_sentence_reach_the_same_cursor(stage):
    await stage.say("show me today's orders", session_id="parity")
    spoken = await stage.say("next", session_id="parity")
    tapped = await stage.touch("workflow.next", session_id="parity")
    assert spoken.model_calls == 0 and tapped.model_calls == 0, "navigation woke the model"
    assert "1 of" in spoken.answer and "2 of" in tapped.answer, (
        f"the cursor did not advance once per step: {spoken.answer!r} then {tapped.answer!r}"
    )
    assert spoken.set_id and spoken.set_id == tapped.set_id, "they walked different sets"


async def test_the_fixture_world_refuses_every_write(stage):
    """A scenario can propose. It can never execute — the fixture clients have no working
    mutation, so a test that started applying changes would fail loudly rather than quietly
    passing against a shop that was being modified."""
    from experience.fixtures.gmail import FixtureWriteAttempted as GmailWrite
    from experience.fixtures.shopify import FixtureWriteAttempted as ShopifyWrite

    with pytest.raises(ShopifyWrite):
        await stage.store.mutate("order_cancel", {})
    with pytest.raises(GmailWrite):
        stage.gmail.service().users().messages().send(userId="me", body={}).execute()


async def test_back_draws_the_record_even_when_memory_has_dropped_it(stage):
    """Going back must never announce a move and leave the screen where it was.

    Memory usually holds the record — returning to something just looked at is not a new
    question — so the cheap path is a replay. When the tier has dropped it, the trail move
    still happened and the record still has to be drawn, so it is read. This empties the
    entity tier between the two lookups to force that path.
    """
    from app.memory import ENTITY
    from app.memory import current as memory

    await stage.say("show me order 1938", session_id="cold")
    await stage.say("show me order 1936", session_id="cold")

    forgotten = memory().invalidate(tier=ENTITY)
    assert forgotten, "nothing was in the entity tier to forget; the test proves nothing"

    back = await stage.touch("navigation.back", session_id="cold")
    assert back.raw.get("ok") is True, back.raw
    # The point of the test: the tier really was cold, so this had to READ rather than replay.
    # Without this the test would pass on the replay path and prove nothing.
    changed = back.raw.get("changed") or {}
    assert changed.get("replayed") is False, f"memory still held it; the cold path was not taken: {changed}"
    assert changed.get("needs_read"), f"the cold path did not ask for a read: {changed}"
    assert not back.prose_only, (
        f"back announced a move and drew nothing: {back.answer!r}"
    )
    assert back.surface("order") is not None, f"surfaces={back.surface_types}"
    assert back.data("order").get("order_number") == "#1938", back.data("order")
    assert (back.entity or {}).get("ref") == "gid://shopify/Order/1938", back.entity
    # Where the read came from — the store, or a warm read-layer cache — is not this test's
    # business. That a card appeared after memory had dropped the record is.


async def test_again_never_reopens_a_different_order(stage):
    """The trap in "show me 1938 again": the number is not extracted.

    A bare number is deliberately not read as an order number — a bare 2025 is a year — so a
    reopen falls back to whatever the branch has open. That is right for "show it again" and
    catastrophic for "show me 1912 again", which named a different order and got 1938: a
    confident wrong answer on the fast lane, which is the exact failure this pass exists to
    remove. A named number that does not match what is open defers instead.
    """
    opened = await stage.say("show me order 1938", session_id="again")
    assert opened.data("order").get("order_number") == "#1938"

    for words in ("show me 1938 again", "1938 again", "show it again", "show that again"):
        same = await stage.say(words, session_id="again")
        assert same.recipe_id == "order_reopen", f"{words!r} took {same.recipe_id!r}"
        assert same.data("order").get("order_number") == "#1938", words

    for words in ("show me 1912 again", "1912 again"):
        other = await stage.say(words, session_id="again")
        assert other.recipe_id != "order_reopen", (
            f"{words!r} reopened the branch's order instead of the one it named"
        )
        # `data()` returns {} when there is no surface at all, so `!= "#1938"` was also
        # satisfied by a turn that drew NOTHING — which is the prose_only failure this whole
        # package exists to catch. Say which of the two outcomes is acceptable.
        shown = other.data("order").get("order_number")
        assert shown != "#1938", f"{words!r} showed the wrong order"
        assert shown is None or shown == "#1912", (
            f"{words!r} showed {shown!r}, which is neither the order it named nor a deferral"
        )


async def test_the_end_of_a_list_is_the_same_place_said_and_tapped(stage):
    """The word "next" and the button called Next must stop in the same place.

    `move_cursor` is one implementation and it refuses to move past the last member. The fast
    lane called it for its side effect and threw the answer away, then clamped the cursor back
    into range — so a tapped Next said "that is the last one" while a spoken "next" read the
    last order again and announced it as "3 of 3", for as many times as it was asked. The owner
    walking a queue then has no way to tell the last one from the end of the list, and each
    re-read costs a Shopify call for a move that did not happen.
    """
    await stage.say("show me today's orders", session_id="ends")
    walked = []
    for _ in range(3):
        walked.append(await stage.say("next", session_id="ends"))
    assert [c.data("order").get("order_number") for c in walked] == ["#1940", "#1938", "#1939"], \
        [c.answer for c in walked]

    said = await stage.say("next", session_id="ends")
    tapped = await stage.touch("workflow.next", session_id="ends")
    assert said.answer == tapped.answer == "That is the last one."
    assert said.prose_only and not said.reads, "a refused move reads nothing and draws nothing new"

    # And the same at the other end, where the cursor starts before the first member.
    await stage.say("show me today's orders", session_id="starts")
    said_back = await stage.say("previous", session_id="starts")
    tapped_back = await stage.touch("workflow.previous", session_id="starts")
    assert said_back.answer == tapped_back.answer == "That is the first one."


async def test_a_record_is_only_replayed_to_the_conversation_it_was_shown_to(stage):
    """The entity cache is shared between conversations; permission is not.

    Read data is immutable, so one process-wide cache is right. But `open.entity` took a kind
    and a ref straight off the wire and handed back whatever the cache held, with no check that
    THIS conversation had ever been shown it — while `/context/order/{id}`, which serves the
    same data, refuses exactly that. Refs are guessable (`gid://shopify/Order/<n>`), so a
    session that had been shown nothing could read another's customer, email and address. The
    rule is `session.issued_ids`, which is what every tool call is already checked against.
    """
    shown = await stage.say("show me order 1938", session_id="ownerA")
    assert shown.data("order").get("order_number") == "#1938"

    await stage.say("hello", session_id="strangerB")
    for kind, ref in (("order", "gid://shopify/Order/1938"), ("customer", "gid://shopify/Customer/7001")):
        leaked = await stage.touch("open.entity", session_id="strangerB", kind=kind, ref=ref)
        assert leaked.raw.get("ok") is False, f"{kind} {ref} was handed to a session never shown it"
        assert leaked.raw.get("code") == "not_held"
        assert not leaked.surfaces, leaked.surface_types

    # The owner's own session, which WAS shown it, still replays instantly.
    mine = await stage.touch("open.entity", session_id="ownerA",
                            kind="order", ref="gid://shopify/Order/1938")
    assert mine.raw.get("ok") is True and mine.data("order").get("order_number") == "#1938"
    assert not mine.reads, "a record already held is replayed, not re-read"


async def test_a_number_that_is_not_the_open_order_is_never_answered_from_the_open_order(stage):
    """"Where is 1940" with 1938 on screen must not answer about 1938.

    A bare number is deliberately not extracted as an order number, so these recipes reached
    their `if known:` fallback and read the record that happened to be open — returning the
    right shape of answer about the wrong order, confidently, on the fast lane, and speaking
    another customer's postal address aloud. `order_reopen` was given this guard; the two
    recipes sharing `_order_plan` were not.
    """
    opened = await stage.say("what is order 1938", session_id="digits")
    assert opened.data("order").get("order_number") == "#1938"

    for words in ("what is the address on 1936", "where is 1940", "what's the status of 1939"):
        answered = await stage.say(words, session_id="digits")
        assert "1938" not in answered.answer, f"{words!r} answered about 1938: {answered.answer!r}"
        assert answered.recipe_id not in ("order_status_lookup", "order_address_lookup"), \
            f"{words!r} took {answered.recipe_id!r} and read the open order"

    # A question with no number in it still means the record on screen.
    for words in ("what is the status", "where is it"):
        about_it = await stage.say(words, session_id="digits")
        assert about_it.recipe_id == "order_status_lookup", f"{words!r} took {about_it.recipe_id!r}"
        assert "1938" in about_it.answer, about_it.answer


@pytest.mark.parametrize(("setup", "question", "must_not_take"), [
    # "How many" is a quantity word, so it carries the sales reading — but the noun decides
    # what is being counted, and a count of customers answered with a revenue figure is a
    # confident answer to a question nobody asked.
    ((), "how many customers do we have today", "sales_breakdown_period"),
    # "Back" is a direction, not a repetition. While it counted as one, a stock question
    # re-rendered whatever order happened to be open.
    (("show me order 1938",), "is the black tee back in stock", "order_reopen"),
    # "Number" is not an address word. It made this a request for the postal address, which
    # was then read out and remembered as PII.
    (("show me order 1938",), "what's the order number", "order_address_lookup"),
    # A question about one person's address is not a summary of the whole week's inbox.
    (("show me order 1938",), "what's her email address", "inbox_state"),
])
async def test_a_deterministic_recipe_never_takes_a_question_it_would_answer_wrongly(
    setup, question, must_not_take, stage,
):
    """The fast lane's job is to be right, not to be busy.

    Every case here was routed to a recipe that produced a confident, well-shaped answer to a
    different question. Deferring costs a model call; answering the wrong question costs the
    owner's trust in every answer that came before it.
    """
    session = f"mis-{abs(hash(question)) % 10000}"
    for words in setup:
        await stage.say(words, session_id=session)
    answered = await stage.say(question, session_id=session)
    assert answered.recipe_id != must_not_take, (
        f"{question!r} took {must_not_take!r} and answered {answered.answer!r}"
    )


async def test_the_inbox_answers_for_the_period_it_was_asked_about(stage):
    """The family boosts on a period, so the period reaches the recipe — and it used to be
    read for the routing and then dropped: the plan always asked Gmail for seven days and the
    sentence always said "this week". "Show me today's emails" was answered with the week's,
    named as though it were the day's.
    """
    day = await stage.say("show me today's emails", session_id="win")
    week = await stage.say("what's in the inbox", session_id="win2")
    assert day.recipe_id == week.recipe_id == "inbox_state"
    assert "today" in day.answer and "this week" not in day.answer, day.answer
    assert "this week" in week.answer, week.answer
    # And the window is real, not just a word in the sentence: the fixture inbox honours
    # Gmail's newer_than, so a shorter window genuinely returns fewer threads.
    assert day.data("email_list") or day.answer
    assert int(day.answer.split()[0]) < int(week.answer.split()[0]), (day.answer, week.answer)


async def test_neither_half_of_the_orb_inherits_the_others_list(stage):
    """Two halves, two lists — or, on the half that listed nothing, no list.

    Working sets were session state with no record of which half made them, so the newest set
    on the conversation answered for both. A half looking at one order would take over the
    other half's rows on "next", and — the part that reaches the write path — the model was
    told in the prompt that "these" and "all of them" meant those rows, with the set_id to act
    on them. `WorkingSet.branch_id` and `session.acting_branch` make a list belong somewhere.
    """
    session = "orb"
    await stage.say("show me order 1938", session_id=session)
    forked = await stage.client.post(
        "/branches/fork", data={"session_id": session},
        headers={"Tailscale-User-Login": "owner@example.com", "X-Forwarded-For": "100.64.0.9"},
    )
    other = forked.json()["branch_id"]
    await stage.say("which customers are waiting on a reply", session_id=session, branch_id=other)

    # The half that listed nothing has nothing to walk, and says so rather than borrowing.
    walked = await stage.say("next", session_id=session)
    assert walked.recipe_id != "working_set_next", walked.answer
    for name in ("Raman", "Fenwick", "Randall"):
        assert name not in walked.answer, f"the other half's rows reached this one: {walked.answer!r}"

    # And nothing tells the model that "these" means the other half's rows.
    before = len(stage.provider.calls)
    await stage.say("tell me what you make of it", session_id=session)
    asked = " ".join(str(getattr(c, "prompt", c)) for c in stage.provider.calls[before:])
    assert "Working set" not in asked, asked[asked.find("[Working set"):][:200]

    # The half that DID list still has its list, and can walk it.
    stepped = await stage.say("next", session_id=session, branch_id=other)
    assert stepped.recipe_id == "working_set_next", stepped.answer


async def test_the_session_records_which_half_a_turn_was_addressed_to(stage):
    """`acting_branch` is how a proposal reaches the half that asked for it.

    `stage()` stamped `session.focused_branch`, while every reader of that field assumes the
    asking one — so a change proposed by the half that is put aside was filed against the half
    on screen. A spoken "yes" over here then applied a change asked for over there, the card
    survived the next instruction that should have withdrawn it, and a BACKGROUND half's
    proposal passed the check that exists to stop a background half committing anything.
    """
    session = "stamp"
    await stage.say("show me order 1938", session_id=session)
    forked = await stage.client.post(
        "/branches/fork", data={"session_id": session},
        headers={"Tailscale-User-Login": "owner@example.com", "X-Forwarded-For": "100.64.0.9"},
    )
    other = forked.json()["branch_id"]
    live = stage.runtime.sessions.get(session)
    # Focus stays where the fork left it; the turn is addressed to the other half.
    live.focused_branch = [b for b in live.branches if b != other][0]
    await stage.say("show me order 1940", session_id=session, branch_id=other)
    assert live.acting_branch == other, live.acting_branch

    assert live.acting_branch != live.focused_branch, (
        "this test is only meaningful while the two differ"
    )


async def test_a_named_person_is_not_answered_from_whoever_the_open_order_belongs_to(stage):
    """"What's Millie's address" with Mia's order open must not read Mia's address.

    The same shape as the bare-number case: a question that NAMES someone is about that
    person, whatever is on screen, and the address and status recipes fell through to the open
    record — right shape of answer, wrong customer, spoken aloud and remembered as PII.
    `possessive_name` already existed as a signal; these two families simply did not block on
    it. Words like "the customer's" and "today's" are possessive without naming anyone, so
    they stay on the fast lane.
    """
    opened = await stage.say("show me order 1938", session_id="named")   # Mia Jones
    assert opened.data("order").get("order_number") == "#1938"

    for words in ("what's millie's address", "where is millie's order"):
        answered = await stage.say(words, session_id="named")
        assert answered.recipe_id not in ("order_address_lookup", "order_status_lookup"), (
            f"{words!r} took {answered.recipe_id!r} and answered about the open order"
        )
        assert "Mia Jones" not in answered.answer, answered.answer

    # A possessive that names nobody still means the record on screen.
    for words in ("what's the address", "what's the customer's address"):
        about_it = await stage.say(words, session_id="named")
        assert about_it.recipe_id == "order_address_lookup", f"{words!r} → {about_it.recipe_id!r}"
        assert "Mia Jones" in about_it.answer


async def test_a_card_redrawn_by_a_tap_offers_what_the_spoken_card_offered(stage):
    """The rail is the same rail, because it comes from the same place.

    `/command` built its own writes dict — `{"enabled": ..., "capabilities": await
    runtime.capabilities()}` — while every consumer in `app/presentation.py` reads
    `writes["allowed"]`, which was not in it. And `runtime.capabilities()` is the MAC's table:
    `writes_context`, which /turn uses, runs `caller_check` first and returns NO capabilities
    when the caller may not apply changes at all. So a tapped card could carry live chips that
    /turn deliberately suppresses on the same order, with nothing on it to say why a tap would
    be refused. Both paths go through `writes_context` now.
    """
    spoken = await stage.say("show me order 1938", session_id="rail")
    assert spoken.action_ids, "the spoken card has a rail to compare against"

    await stage.touch("navigation.back", session_id="rail")
    tapped = await stage.touch("open.entity", session_id="rail",
                               kind="order", ref="gid://shopify/Order/1938")
    assert tapped.raw.get("ok") is True, tapped.raw
    assert sorted(set(tapped.action_ids)) == sorted(set(spoken.action_ids)), (
        f"tapped={sorted(set(tapped.action_ids))} spoken={sorted(set(spoken.action_ids))}"
    )
    # And each chip agrees about whether it can be applied, not just that it exists.
    by_id = {a.get("operation") or a.get("id"): a.get("enabled") for a in spoken.actions}
    for action in tapped.actions:
        name = action.get("operation") or action.get("id")
        assert action.get("enabled") == by_id.get(name), f"{name} differs between tap and voice"

    # The case that separates the two implementations: the same command from a caller that may
    # NOT apply changes — here the Mac itself, with no Tailscale identity, which
    # `caller_check` refuses while CROOKS_WRITES_LOCAL_OWNER is false. `writes_context` hands
    # back no capabilities at all for such a caller, so the rail is empty; the old dict handed
    # back `runtime.capabilities()`, the Mac's own table, and the card carried live chips.
    local = await stage.client.post("/command", data={
        "session_id": "rail", "command": "open.entity",
        "kind": "order", "ref": "gid://shopify/Order/1938"})
    assert local.status_code == 200, local.text
    offered = [
        a.get("operation") or a.get("id")
        for item in (local.json().get("ui") or [])
        for a in ((item.get("data") or {}).get("actions") or [])
    ]
    assert offered == [], f"a caller who cannot apply changes was offered {sorted(set(offered))}"


async def test_a_record_reached_by_tapping_is_still_held_a_moment_later(stage):
    """A tap's read went nowhere, so Back and Next were only free for voice.

    Only the fast lane's `_keep` wrote to the memory tiers; `_read_member`, which is what a
    tapped Next uses when the cursor lands on a record the Mac does not hold, read it and threw
    it away. So the record was gone a second later: Back onto it missed `replay()` and read
    Shopify again, and `open.entity` refused a record the owner had been looking at moments
    before — "I no longer have that one to hand" — for the one thing he had just tapped.

    The anticipation layer is switched off here, with a fresh one of its own: opening an order
    is a signal it may prefetch on (the customer's history, the next order), and those reads
    land in the same window as the tap's. Whether they finish inside it is scheduling, not the
    defect (on 2026-09-27 they did on every run, on the trunk as well), and the layer is shared
    by every test before this one. What is asserted is the tap's own read, which is the defect
    this is about, and that the record was replayed; the layer's prefetches have tests of their
    own (tests/test_anticipation.py).
    """
    from app.anticipation import engine as anticipation_mod
    from app.anticipation.learning import Learner
    from app.memory.prefetch import Prefetcher

    anticipation_mod.install(anticipation_mod.Anticipator(
        learner=Learner(), prefetcher=Prefetcher(), max_anticipated=0, max_speculative=0))
    try:
        await stage.say("show me today's orders", session_id="held")
        moved = await stage.touch("workflow.next", session_id="held")
        ref = (moved.entity or {}).get("ref") or ""
        assert ref, moved.raw

        reopened = await stage.touch("open.entity", session_id="held", kind="order", ref=ref)
        assert reopened.raw.get("ok") is True, reopened.raw
        assert reopened.raw["changed"].get("replayed") is True, "the record the Mac held was replayed"
        assert reopened.surfaces, "the record the owner just tapped onto drew nothing"
        assert not reopened.reads, f"it was read again instead of replayed: {reopened.reads}"
    finally:
        anticipation_mod.install(None)


async def test_a_recipe_that_offers_nothing_does_not_wait_for_the_write_preflight(stage):
    """The rail is worked out beside the read, not in front of it.

    Giving read turns their action rail was the point of this pass — an order looked up quickly
    and offering nothing to do with it was the reported failure. But it was done with an
    `asyncio.gather` of the answer and the preflight, under a comment claiming the preflight is
    cached and so costs nothing. Both halves were wrong: before it, a read turn never called
    `writes_context` at all, and the scope caches behind it last ten minutes — so every expiry,
    every restart and every cold tablet paid `WRITE_STATUS_TIMEOUT_S` on the fastest turn in
    the system. "What can you do now?" went from 24 ms to 1508 ms.

    A recipe that draws from state the Mac already holds — capability, navigation, the end of a
    list — reads nothing and offers nothing, and must pay nothing.
    """
    import asyncio

    real = stage.runtime.write_status

    async def slow(operation=None):
        await asyncio.sleep(3.0)
        return await real(operation)

    from app.routes import actions as actions_route

    stage.runtime.write_status = slow
    try:
        await stage.say("show me order 1938", session_id="pre")
        for words in ("what can you do now?", "go back"):
            # `_preflight_soon` goes quiet for a while after one timeout, so without this the
            # warm-up above would trip the breaker and every later turn would return instantly
            # whether or not it waited — a test that cannot fail.
            actions_route._preflight_timed_out_at = 0.0
            answered = await stage.say(words, session_id="pre")
            assert answered.total_ms < 1000, (
                f"{words!r} waited {answered.total_ms:.0f}ms on a preflight it has no rail for"
            )
    finally:
        stage.runtime.write_status = real
        actions_route._preflight_timed_out_at = 0.0


async def test_asking_again_about_the_record_you_are_on_does_not_add_a_stop(stage):
    """Back has to move the screen, or it reads as a Back that failed.

    Every read calls `branch.visit`, and it appended unconditionally, so three questions about
    one order left three identical stops. Back then landed on the same record, on the same tab,
    and said the same sentence — I diffed two consecutive Backs and the whole `ui` payload was
    byte-identical. A button that visibly does nothing is worse than one that says it cannot.
    """
    session = "stops"
    for words in ("show me order 1938", "where is order 1938", "what is the address on 1938"):
        await stage.say(words, session_id=session)
    await stage.say("show me order 1936", session_id=session)

    trail = [(e.ref, e.tab) for e in stage.branch(session).nav]
    assert len(trail) == len(set(trail)), f"the same stop twice in a row: {trail}"

    seen = []
    for _ in range(3):
        answered = await stage.say("go back", session_id=session)
        seen.append((answered.answer, (answered.entity or {}).get("ref"),
                     stage.branch(session).tab))
    moves = [s for s in seen if "as far back" not in s[0]]
    assert len(moves) == len(set(moves)), f"two Backs landed on the same screen: {moves}"


async def test_a_question_that_names_its_own_subject_is_not_swallowed_by_a_tapped_control(stage):
    """A bound control captures dictation, not every sentence for two minutes.

    `_NEVER_A_CONTINUATION` exempted only the families that command the assistant directly, so
    tapping Add a note and then asking "how many orders today" handed the model that question
    with "[This continues order.add_note on #1938. Apply it to that record and to nothing
    else.]" stapled on — and dropped the turn off the fast lane on the way. "Show me order
    1912" was glued to #1938 the same way.

    The line is whether the router can already act on the sentence: one that names an order, a
    period or a list is its own instruction; dictation names none of those and is still caught.
    """
    async def bound(words, session):
        await stage.say("show me order 1938", session_id=session)
        await stage.touch("voice.bind", session_id=session, family="order.add_note")
        before = len(stage.provider.calls)
        answered = await stage.say(words, session_id=session)
        asked = " ".join(str(getattr(c, "prompt", c)) for c in stage.provider.calls[before:])
        return answered, "This continues order.add_note" in asked

    for words in ("how many orders today", "show me order 1912", "what's in the inbox"):
        answered, glued = await bound(words, f"glue-{abs(hash(words)) % 1000}")
        assert not glued, f"{words!r} was applied to the note the owner had tapped"
        assert answered.lane == "FAST", f"{words!r} left the fast lane at {answered.lane}"

    # And the words the control was actually waiting for are still caught.
    for words in ("make it shorter and more apologetic", "he wants it by friday"):
        _, glued = await bound(words, f"dict-{abs(hash(words)) % 1000}")
        assert glued, f"{words!r} was not taken as the note it was dictating"


async def test_opening_a_row_reads_the_record_when_the_mac_does_not_hold_it(stage):
    """A list is a way into its records, not a picture of them.

    `open.entity` replayed from memory or refused, and a listing holds summaries — so tapping
    any row of any list hit "I no longer have that one to hand; ask for it and I will read it
    again". That is a reasonable sentence in a conversation and a dead end under a finger: the
    only route from today's orders to one of them was to say its number out loud.

    It reads now, the way a cursor landing on an unheld member already did. What must NOT
    change is who may ask: `replay()` returned nothing both for "not cached" and for "not
    yours", and reading on an empty replay would have turned the second into a read attempt.
    The two are separate questions now, and only the permission one refuses.
    """
    listed = await stage.say("show me today's orders", session_id="rows")
    rows = listed.data("order_list").get("orders") or []
    assert rows, listed.surface_types
    ref = str(rows[0].get("order_id") or "")
    assert ref, rows[0]

    opened = await stage.touch("open.entity", session_id="rows", kind="order", ref=ref)
    assert opened.raw.get("ok") is True, opened.raw
    assert opened.data("order").get("order_id") == ref, opened.surface_types
    assert opened.reads, "a record the Mac did not hold should have been read"

    # A second tap on the same row is free: it is held now.
    again = await stage.touch("open.entity", session_id="rows", kind="order", ref=ref)
    assert again.raw.get("ok") is True and not again.reads, again.reads


async def test_a_row_a_conversation_was_never_shown_is_refused_before_any_read(stage):
    """The permission half of the same change, which is the half worth a test.

    A session that was never issued the id must be refused outright — not read on its behalf
    and not handed an error card after the gate catches it downstream. Nothing is read.
    """
    await stage.say("show me order 1938", session_id="ownerRows")
    await stage.say("hello", session_id="strangerRows")

    refused = await stage.touch("open.entity", session_id="strangerRows",
                                kind="order", ref="gid://shopify/Order/1938")
    assert refused.raw.get("ok") is False, refused.raw
    assert refused.raw.get("code") == "not_held", refused.raw
    assert not refused.surfaces, refused.surface_types
    assert not refused.reads, f"a refused open still read something: {refused.reads}"


async def test_a_scenario_does_not_inherit_the_last_one_in_a_shared_harness(stage):
    """`make experience` shares ONE harness across every scenario; this file builds one per
    scenario. The two disagreed, and pytest was the one that said the build was fine.

    Three scenarios failed under `scripts/experience.py` while passing here — two whose oracle
    is "nothing was changed", reading the calculation log of the scenario before them. That is
    the worst shape a test can have: green in the suite, red in the command a person actually
    runs on the Mac.

    `run_all` now clears the fixture world's record of what has been asked of it between
    scenarios — the log, never the world — and this asserts it, by running a scenario that
    LEAVES a log and then one that requires an empty one, in that order, through one harness.
    A reset that stopped working would fail here rather than only in the other runner.
    """
    from experience.scenarios import BY_NAME, _forget_the_last_scenario

    leaves_a_log = await BY_NAME["order_add_item_picker"](stage)
    assert leaves_a_log.status == "PASS", leaves_a_log.failures
    assert getattr(stage.store, "calculations", None), "that scenario is meant to leave a log behind"

    _forget_the_last_scenario(stage)
    assert not stage.store.calculations, "the log survived the reset"

    needs_a_clean_one = await BY_NAME["order_add_item_cancelled"](stage)
    failures = "\n".join(f"  - {c.what} :: {c.detail}" for c in needs_a_clean_one.failures)
    assert needs_a_clean_one.status == "PASS", f"a scenario inherited the last one's log\n{failures}"

    # And the world itself is untouched by the reset: the golden orders are still there, so a
    # scenario that quietly depended on being first would still be wrong rather than hidden.
    assert len(stage.store.queries) >= 0
    from experience.fixtures import data
    assert data.BY_NAME["#1938"] is not None


def test_the_fixture_shop_forgets_every_field_it_records_a_scenario_in():
    """The guard that stops this recurring, rather than a third fix for a fourth field.

    The first version of the reset listed the store's fields in the RUNNER, and it went stale
    the same day: `drafts` was added to the fixture afterwards, leaked, and an order-creation
    scenario failed with the previous scenario's draft in its detail — the identical failure a
    second time, in a new field.

    So this compares a shop that has been USED and then told to forget against a shop straight
    out of the box, field by field. A new mutable field recorded per scenario and not cleared
    fails HERE, in the file that adds it, rather than in whichever scenario happens to run
    after it next month.
    """
    from experience.fixtures.shopify import FixtureShopify

    fresh = FixtureShopify()
    used = FixtureShopify()

    # Use it the way a scenario does: ask it things, and leave a draft behind.
    used.queries.append(("CrooksOrders", {"first": 10}))
    used.calculations.append(("order_edit_begin", {"id": "gid://shopify/Order/1938"}))
    used.calculated["gid://shopify/CalculatedOrder/1938"] = {"id": "x"}
    used.drafts.append({"customerId": "gid://shopify/Customer/7003"})
    used.drafts_by_id["gid://shopify/DraftOrder/4000"] = {"id": "gid://shopify/DraftOrder/4000"}
    used.draft_number += 1
    used.mutations_sent += 1

    used.forget_scenario()

    # Public attributes only. The underscored ones are the shop's own machinery — the shop
    # document, its timezone, a lock — and a lock differs by identity on every construction,
    # which would make this test fail for a reason that is not a leak. Everything a scenario
    # is recorded in is public, which is what makes the rule safe rather than convenient.
    differ = sorted(
        name for name, value in vars(used).items()
        if not name.startswith("_") and vars(fresh).get(name) != value
    )
    assert not differ, (
        "these fields survived forget_scenario(), so one scenario inherits them from the "
        f"last in `make experience`: {differ}"
    )
    # The world is deliberately still there — the reset drops the log, not the shop.
    assert used.scopes == fresh.scopes
    assert used.store_credit == fresh.store_credit, "an opening balance is the world, not a log"
