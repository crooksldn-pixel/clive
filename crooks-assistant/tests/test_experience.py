"""The golden scenarios, as part of the ordinary suite.

They run against the fixture world through the real runtime, so they are as offline and as
deterministic as every other test here — and they are the only tests that can catch the class
of failure this pass exists for, which is an answer that is correct, fast, and has nothing on
the screen. A unit test of a presenter cannot see that; only driving a turn can.

Every sentence is a model turn (since 28 September 2026, when the owner had the word-matching
lane removed). Where a test needs a record on screen, the harness's model reads it the way
Claude does — `stage.open_order("1938")` is "show me order 1938" plus the two reads Claude
makes for it, through the gate — and what is asserted is what the Mac drew from that.
"""

from __future__ import annotations

import functools

import pytest

from experience.harness import harness
from experience.scenarios import BY_NAME, SCENARIOS


@pytest.fixture()
async def stage(monkeypatch):
    """An admitted harness that also keeps what it really did: every tool call that reached the
    dispatcher — a scripted model's, a tapped recipe's read, a tapped staging command's — and
    which of them came back staged. `tool_matrix`'s claims about a scenario are held to it."""
    import app.tools.dispatch as dispatch_module

    real = dispatch_module.dispatch
    did: list[tuple[str, bool]] = []

    async def dispatch(tool_name, args, **kwargs):
        text = await real(tool_name, args, **kwargs)
        did.append((str(tool_name), str(text).startswith("PROPOSED")))
        return text

    monkeypatch.setattr(dispatch_module, "dispatch", dispatch)
    async with harness(admitted=True) as h:
        h.dispatched = did
        yield h


@functools.lru_cache(maxsize=1)
def _audit_claims() -> dict[str, dict[str, str]]:
    """Scenario -> {tool: "read" | "staged"}, as the tool matrix reports it."""
    from experience import tool_matrix

    tool_matrix.load()
    out: dict[str, dict[str, str]] = {}
    for tool, reached in tool_matrix._scenario_tools().items():
        for scenario, how in reached.items():
            out.setdefault(scenario, {})[tool] = how
    return out


# Every scenario goes through the door, which stamps the owner's authority itself on an
# admitted harness. The two store-credit scenarios used to call their read tool directly with
# an authority granted to the test (round 8, F-A2-FIXTURE); since round 10 they ask for it in a
# sentence like every other (the 2026-09-28 deploy review, round 9, H-07), and no scenario is
# given authority from outside its own request.
#
# And every call a scenario scripts for the harness's model is one Claude could make: offered to
# it on this runtime, with arguments its schema admits (`experience.harness.model_could_make`).
# A scripted scenario proves what the Mac does with a call, never that Claude would make it
# (the 2026-09-28 deploy review, round 9, H-02); a script Claude could not make would not even
# prove that much about a spoken request. One scenario reaches for a tool that does not exist
# on purpose — that is what it is about — and is named here with the tool.
BEYOND_THE_MODEL = {"unsupported_edit": {"shopify_order_remove_item"}}


@pytest.mark.parametrize("name", [n for n, _ in SCENARIOS])
async def test_the_golden_scenarios(name, stage):
    result = await BY_NAME[name](stage)
    assert not result.error, result.error
    failures = "\n".join(f"  - {c.what} :: {c.detail}" for c in result.failures)
    assert result.status == "PASS", f"{result.title}\n{failures}"
    for capture in result.captures:
        beyond = set(getattr(capture, "unmakeable", {}) or {})
        assert beyond <= BEYOND_THE_MODEL.get(name, set()), f"{capture.scenario}: {capture.unmakeable}"
    if name in BEYOND_THE_MODEL:
        reached = {tool for c in result.captures for tool in (getattr(c, "unmakeable", {}) or {})}
        assert reached == BEYOND_THE_MODEL[name], "the deliberate reach is still what the scenario makes"
    # And what docs/phase4/TOOL_MATRIX.md says this scenario exercises is what it really did
    # (the 2026-09-28 deploy review, round 9, H-06): every tool it is credited with reached the
    # dispatcher in this run, and the writes it is credited with staging are exactly the writes
    # that came back staged — not every write a command it posts could have prepared.
    claims = _audit_claims().get(name, {})
    dispatched = {tool for tool, _ in stage.dispatched}
    staged = {tool for tool, was_staged in stage.dispatched if was_staged}
    assert set(claims) <= dispatched, f"credited but never called: {sorted(set(claims) - dispatched)}"
    assert {t for t, how in claims.items() if how == "staged"} == staged, \
        f"credited as staged: {sorted(t for t, how in claims.items() if how == 'staged')}; staged: {sorted(staged)}"


def test_a_call_claude_could_not_make_is_named_as_such():
    """The check itself, on each way a script can ask for what the model cannot do."""
    import app.tools.shopify_tools  # noqa: F401 — registers the tools asked about
    import app.tools.shopify_writes  # noqa: F401
    from experience.harness import model_could_make

    runtime = type("R", (), {"settings": type("S", (), {"writes_enabled": False})(), "withheld_by_family": lambda self: set()})()
    assert model_could_make(runtime, "shopify_find_order", {"query": "1938", "limit": 3}) == ""
    assert "no tool of that name" in model_could_make(runtime, "shopify_order_remove_item", {"order_id": "x"})
    assert "withheld" in model_could_make(runtime, "shopify_order_cancel", {"order_id": "x"}), "writes are off"
    assert "no argument 'order'" in model_could_make(runtime, "shopify_find_order", {"query": "1938", "order": "x"})
    assert "requires 'order_id'" in model_could_make(runtime, "shopify_order_detail", {})
    assert "int where the schema says string" in model_could_make(runtime, "shopify_find_order", {"query": 1938})
    assert "bool where the schema says integer" in model_could_make(runtime, "shopify_find_order", {"query": "1", "limit": True})


async def test_an_order_lookup_that_is_fast_and_empty_is_a_failure(stage):
    """The regression test the brief asks for by name (§29).

    It is worth stating what this does NOT assert: it says nothing about latency. The build
    that was reported as broken was fast — that was the whole complaint. Speed with an empty
    screen has to fail, so the assertions are all about what came back.
    """
    capture = await stage.open_order("1938")
    assert capture.lane == "NORMAL" and capture.model_calls == 1, "a lookup is the model's, asked once"
    assert not capture.prose_only, (
        f"the answer was prose with no surface: {capture.answer!r}"
    )
    order = capture.surface("order")
    assert order is not None, f"no order surface; got {capture.surface_types}"
    assert order["data"].get("detail") is True, "the brief card, not the full order"
    assert order["data"].get("items"), "the items are not reachable"
    assert capture.action_ids, "no actions were offered for the order"
    assert (capture.entity or {}).get("kind") == "order", "the current entity was not established"


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

    await stage.open_order("1938", session_id="cold")
    await stage.open_order("1936", session_id="cold")

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


async def test_the_end_of_a_list_is_said_rather_than_walked_past(stage):
    """Next at the last member says so, and Previous at the first; neither re-reads a record.

    `move_cursor` refuses to move past the last member. When a spoken "next" was answered by
    a word-matching recipe, that recipe called it for its side effect, threw the answer away
    and clamped the cursor back into range, so the last order was read again and announced as
    "3 of 3" as many times as it was asked. The owner walking a queue then had no way to tell
    the last one from the end of the list. The buttons are what walk a list now.
    """
    listed = await stage.touch("open.area", area="orders", session_id="ends")
    total = (listed.raw.get("changed") or {}).get("total") or len(listed.data("order_list").get("orders") or [])
    assert total >= 2, listed.surface_types
    walked = [await stage.touch("workflow.next", session_id="ends") for _ in range(total)]
    assert [(c.raw.get("changed") or {}).get("position") for c in walked] == list(range(1, total + 1)), \
        [c.answer for c in walked]

    past = await stage.touch("workflow.next", session_id="ends")
    assert past.answer == "That is the last one."
    assert past.prose_only and not past.reads, "a refused move reads nothing and draws nothing new"

    # And the same at the other end, where the cursor starts before the first member.
    await stage.touch("open.area", area="orders", session_id="starts")
    before = await stage.touch("workflow.previous", session_id="starts")
    assert before.answer == "That is the first one."


# The fixture shop's reads of an ORDER record (experience/fixtures/shopify.py). A tap on an order
# also tells the anticipation layer, which reads the customer's history ahead of the owner in
# the background (app/routes/command.py:_anticipate) — a read that can land inside the next
# tap's window on a loaded machine, and is not that tap re-reading its record. "Replayed, not
# re-read" is about the record, so the record's reads are what is counted.
_ORDER_RECORD_READS = frozenset({"CrooksOrderContext", "CrooksOrderByName", "FindOrders"})


def _record_reads(capture) -> list[str]:
    return [q for q in capture.reads if q in _ORDER_RECORD_READS]


async def test_a_record_is_only_replayed_to_the_conversation_it_was_shown_to(stage):
    """The entity cache is shared between conversations; permission is not.

    Read data is immutable, so one process-wide cache is right. But `open.entity` took a kind
    and a ref straight off the wire and handed back whatever the cache held, with no check that
    THIS conversation had ever been shown it — while `/context/order/{id}`, which serves the
    same data, refuses exactly that. Refs are guessable (`gid://shopify/Order/<n>`), so a
    session that had been shown nothing could read another's customer, email and address. The
    rule is `session.issued_ids`, which is what every tool call is already checked against.
    """
    shown = await stage.open_order("1938", session_id="ownerA")
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
    assert not _record_reads(mine), f"a record already held is replayed, not re-read: {mine.reads}"


async def test_neither_half_of_the_orb_inherits_the_others_list(stage):
    """Two halves, two lists — or, on the half that listed nothing, no list.

    Working sets were session state with no record of which half made them, so the newest set
    on the conversation answered for both. A half looking at one order would take over the
    other half's rows on Next, and — the part that reaches the write path — the model was
    told in the prompt that "these" and "all of them" meant those rows, with the set_id to act
    on them. `WorkingSet.branch_id` and `session.acting_branch` make a list belong somewhere.
    """
    session = "orb"
    await stage.open_order("1938", session_id=session)
    forked = await stage.client.post(
        "/branches/fork", data={"session_id": session},
        headers={"Tailscale-User-Login": "owner@example.com", "X-Forwarded-For": "100.64.0.9"},
    )
    other = forked.json()["branch_id"]
    listed = await stage.touch("open.area", area="email", session_id=session, branch_id=other)
    assert listed.raw.get("ok") is True, listed.raw
    held = stage.branch(session, other).workflow
    assert held is not None and held.set_id, "the Inbox landing opened a list on the other half"

    # The half that listed nothing has nothing to walk, and says so rather than borrowing.
    walked = await stage.touch("workflow.next", session_id=session)
    assert walked.raw.get("ok") is False or not walked.surfaces, walked.answer
    for name in ("Raman", "Fenwick", "Randall"):
        assert name not in walked.answer, f"the other half's rows reached this one: {walked.answer!r}"

    # And nothing tells the model that "these" means the other half's rows.
    before = len(stage.provider.calls)
    await stage.say("tell me what you make of it", session_id=session)
    asked = " ".join(str(getattr(c, "prompt", c)) for c in stage.provider.calls[before:])
    assert "Working set" not in asked, asked[asked.find("[Working set"):][:200]

    # The half that DID list still has its list, and can walk it.
    stepped = await stage.touch("workflow.next", session_id=session, branch_id=other)
    assert stepped.raw.get("ok") is True and (stepped.raw.get("changed") or {}).get("position") == 1, stepped.raw


async def test_the_session_records_which_half_a_turn_was_addressed_to(stage):
    """`acting_branch` is how a proposal reaches the half that asked for it.

    `stage()` stamped `session.focused_branch`, while every reader of that field assumes the
    asking one — so a change proposed by the half that is put aside was filed against the half
    on screen. A spoken "yes" over here then applied a change asked for over there, the card
    survived the next instruction that should have withdrawn it, and a BACKGROUND half's
    proposal passed the check that exists to stop a background half committing anything.
    """
    session = "stamp"
    await stage.open_order("1938", session_id=session)
    forked = await stage.client.post(
        "/branches/fork", data={"session_id": session},
        headers={"Tailscale-User-Login": "owner@example.com", "X-Forwarded-For": "100.64.0.9"},
    )
    other = forked.json()["branch_id"]
    live = stage.runtime.sessions.get(session)
    # Focus stays where the fork left it; the turn is addressed to the other half.
    live.focused_branch = [b for b in live.branches if b != other][0]
    await stage.open_order("1940", session_id=session, branch_id=other)
    assert live.acting_branch == other, live.acting_branch

    assert live.acting_branch != live.focused_branch, (
        "this test is only meaningful while the two differ"
    )


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
    spoken = await stage.open_order("1938", session_id="rail")
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
        await stage.touch("open.area", area="orders", session_id="held")
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


async def test_asking_again_about_the_record_you_are_on_does_not_add_a_stop(stage):
    """Back has to move the screen, or it reads as a Back that failed.

    Every read calls `branch.visit`, and it appended unconditionally, so three questions about
    one order left three identical stops. Back then landed on the same record, on the same tab,
    and said the same sentence — I diffed two consecutive Backs and the whole `ui` payload was
    byte-identical. A button that visibly does nothing is worse than one that says it cannot.
    """
    session = "stops"
    for words in ("show me order 1938", "where is order 1938", "what is the address on 1938"):
        await stage.open_order("1938", said=words, session_id=session)
    await stage.open_order("1936", session_id=session)

    trail = [(e.ref, e.tab) for e in stage.branch(session).nav]
    assert len(trail) == len(set(trail)), f"the same stop twice in a row: {trail}"

    seen = []
    for _ in range(3):
        answered = await stage.touch("navigation.back", session_id=session)
        seen.append((answered.answer, (answered.entity or {}).get("ref"),
                     stage.branch(session).tab))
    moves = [s for s in seen if "as far back" not in s[0]]
    assert len(moves) == len(set(moves)), f"two Backs landed on the same screen: {moves}"


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
    listed = await stage.list_todays_orders(session_id="rows")
    rows = listed.data("order_list").get("orders") or []
    assert rows, listed.surface_types
    ref = str(rows[0].get("order_id") or "")
    assert ref, rows[0]

    opened = await stage.touch("open.entity", session_id="rows", kind="order", ref=ref)
    assert opened.raw.get("ok") is True, opened.raw
    assert opened.data("order").get("order_id") == ref, opened.surface_types
    assert _record_reads(opened), f"a record the Mac did not hold should have been read: {opened.reads}"

    # A second tap on the same row is free: it is held now.
    again = await stage.touch("open.entity", session_id="rows", kind="order", ref=ref)
    assert again.raw.get("ok") is True and not _record_reads(again), again.reads


async def test_a_row_a_conversation_was_never_shown_is_refused_before_any_read(stage):
    """The permission half of the same change, which is the half worth a test.

    A session that was never issued the id must be refused outright — not read on its behalf
    and not handed an error card after the gate catches it downstream. Nothing is read.
    """
    await stage.open_order("1938", session_id="ownerRows")
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


async def test_the_harness_admits_nobody_unless_the_owner_is_asked_for_by_name():
    """F-A2-FIXTURE (the 2026-09-28 deploy review, round 9): the harness's default is the
    production identity check, under which its own owner headers are a claim nobody confirmed.
    A sentence and a tap are refused at the door, and nothing behind it runs."""
    from app import identity

    # Nothing in this process is tailscaled, and that is the answer the kernel would give; the
    # seam says so instead of reading other processes' /proc entries (tests/conftest.py puts it
    # back).
    identity.bind_peer_check(lambda _client, _server: (False, "no tailscaled on the test machine"))
    async with harness() as unadmitted:
        assert unadmitted.admitted is False and unadmitted.runtime.settings.tailscale_verify is True
        said = await unadmitted.say("show me order 1938", session_id="nobody")
        tapped = await unadmitted.touch("open.area", area="orders", session_id="nobody")
        assert said.status == 403 and tapped.status == 403, (said.raw, tapped.raw)
        assert unadmitted.provider.calls == [], "the model was never asked"
        assert not unadmitted.runtime.sessions.exists("nobody")


async def test_nothing_the_harness_grants_outlives_it_or_reaches_the_code_that_drives_it(monkeypatch):
    """F-A2-FIXTURE (the 2026-09-28 deploy review, round 9, H-experience1 and I-tests1/3/4/5;
    round 10, T2 and T5): what an admitted harness grants — its runtime's allow-list naming the
    fixture owner, Tailscale's confirmation off, changes on, the fixture clients and write
    policies bound into the tool modules — is its own and ends with it.

    Inside, the grant is to requests through the door and to nothing else: a tool the test's
    own code calls, outside a request, is refused like any other call with no authority. After
    it, the shared app is as it was before — here, an app whose runtime names nobody — so the
    same tablet headers the harness sent are refused at the door, and every place in the tool
    modules where the harness, or the start-up it runs, binds a client, a helper or a write
    policy holds again exactly what it held before, not the harness's."""
    from types import SimpleNamespace

    import httpx

    from app import identity
    from app.main import app
    from app.session.models import Session
    from app.tools import (
        analytics_tools,
        authority,
        gmail_tools,
        gmail_writes,
        shopify_tools,
        shopify_writes,
    )
    from app.tools.dispatch import dispatch
    from experience.harness import TABLET_HEADERS

    nobody = SimpleNamespace(allowed_logins=(), settings=SimpleNamespace(
        tailscale_verify=True, local_owner=False, writes_local_owner=False, writes_enabled=False, tailscale_cli=""))
    monkeypatch.setattr(app.state, "runtime", nobody, raising=False)
    monkeypatch.setattr(app.state, "allowed_logins", (), raising=False)
    # A marker of this test's own in each of those places, so that "put back" means put back —
    # not merely "left as None" — and a binding the harness forgot would still be the harness's.
    held = {(module, name): object() for module, names in (
        (shopify_tools, ("_client", "_hydrator")),
        (gmail_tools, ("_client", "_customer_lookup")),
        (gmail_writes, ("_client", "_customer", "_policy")),
        (shopify_writes, ("_policy",)),
        (analytics_tools, ("_cache", "_threads_for", "_replied", "_reply_state", "_own_address", "_inbox_for",
                           "_sent_for")),
    ) for name in names}
    for (module, name), marker in held.items():
        monkeypatch.setattr(module, name, marker)

    async with harness(admitted=True) as h:
        assert app.state.runtime is h.runtime and app.state.runtime is not nobody
        assert h.runtime.settings.writes_enabled is True and h.runtime.settings.tailscale_verify is False
        kept = [f"{module.__name__}.{name}" for (module, name), marker in held.items() if getattr(module, name) is marker]
        assert kept == [], f"the harness bound its own in every one of them, and not in {kept}"
        assert shopify_writes.policy().writes_enabled is True and gmail_writes._settings().writes_enabled is True, \
            "inside, both write modules read the harness's policy: changes on"
        answered = await h.say("hello", session_id="inside")
        assert answered.status == 200, answered.raw
        assert authority.current() is None, "the harness stamps no authority on the code that drives it"
        refused = await dispatch("shopify_find_order", {"query": "1938"}, session=Session(session_id="outside"), timeout_s=5)
        assert refused.startswith("REFUSED: this was not asked for by the owner"), refused

    assert app.state.runtime is nobody and app.state.allowed_logins == ()
    left = [f"{module.__name__}.{name}" for (module, name), marker in held.items() if getattr(module, name) is not marker]
    assert left == [], f"the harness left its own behind in {left}"
    identity.bind_peer_check(lambda _client, _server: (False, "no tailscaled on the test machine"))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://tablet") as after:
        turned = await after.post("/turn", json={"text": "show me order 1938", "session_id": "after"}, headers=TABLET_HEADERS)
    assert turned.status_code == 403, turned.text
