"""D-3 — the split, made real.

The Phase 3 live session, 00:23:01 to 00:25:53: a fork, six focus changes in nine seconds,
then `open.area` refused `landing_unavailable` and `open.entity` refused `not_held`, both on
the forked half. The owner: *"the split function doesn't work at all"*, *"it just so shows two
of the same thing"*.

Everything below fails on the code as it was that night, and each one is a sentence from that
session:

* two halves asked two different questions held one workspace between them;
* the fork drew its parent's record, so tapping between the halves redrew nothing;
* the clone never received what its parent held, so opening a place or a record was refused
  with a reason its owner could not act on;
* a half said what it was doing without saying which half it was;
* and a half put aside could be told it was "working" by a turn that had already died.

The gesture itself — two fingers that must never become a sentence — is asserted in the
browser (scripts/browser/split.js), where fingers are.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import commands
from app.session.branch import BRANCH_STATES, Branch, Workflow, fork_from
from app.session.models import Session
from experience.harness import harness
from tests.test_actions_routes import PROXIED, FakeProvider, commit, configure


@pytest.fixture()
async def stage():
    async with harness(admitted=True) as h:
        yield h


@pytest.fixture()
async def writes(monkeypatch):
    """The write boundary, on a real app with the store that records every mutation reaching it.

    The same shape `tests/test_actions_routes.py` uses, and its helpers (`configure`, `commit`,
    `PROXIED`) are imported from there rather than copied: "a half put aside cannot commit" has
    to be asserted against the boundary every other write test goes through, or it is asserting
    something else.
    """
    import httpx

    from app.actions.ledger import NullLedger
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.main import app
    from app.providers import max_agent_sdk
    from app.session.manager import SessionManager
    from app.tools import shopify_tools
    from tests.test_actions import FakeStore

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", lambda self: (True, "fake scribe"))
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = FakeProvider()
        store = FakeStore(note="Gift wrap please")
        runtime.shopify = store
        shopify_tools.bind(store)
        runtime.actions.ledger = NullLedger()
        runtime.sessions = SessionManager()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.store = store
            c.runtime = runtime
            yield c


# What Claude reads for "which orders are waiting to go out?".
WAITING_TO_GO_OUT = (("shopify_list_orders", {"days": 30, "unfulfilled_only": True}),)


def _ctx(session, branch, **args):
    return commands.Ctx(runtime=None, session=session, branch=branch, args=args)


class _Session:
    def __init__(self, *branches: Branch) -> None:
        self.session_id = "s1"
        self.branches = {b.branch_id: b for b in branches}
        self.focused_branch = branches[0].branch_id if branches else ""
        self.issued_ids: set[str] = set()


# ------------------------------------------------- two halves, two questions, two screens


async def test_two_halves_asked_different_questions_hold_different_workspaces(stage):
    """The test the brief asks for by name.

    The brief's own wording is "show yesterday's orders" on the left. The golden world has no
    orders yesterday, and a question that draws nothing proves nothing about two screens, so
    the left half is asked about the orders still to go out. Each question is the model's, and
    the harness's model makes the read Claude would; the point is unchanged: two questions,
    two halves, and two different things on the glass.
    """
    left = await stage.ask("which orders are waiting to go out?", *WAITING_TO_GO_OUT,
                           reply="Three orders are waiting to go out.", session_id="split")
    forked = await stage.client.post("/branches/fork", data={"session_id": "split"})
    right_id = forked.json()["branch_id"]

    right = await stage.ask("find emails needing replies", ("gmail_search", {"query": "", "days": 30}),
                            reply="Two people are waiting on a reply.", session_id="split", branch_id=right_id)
    assert left.surface_types and right.surface_types, "both halves must have drawn something"
    assert left.surface_types != right.surface_types, (
        f"both halves drew {left.surface_types}: the owner's 'two of the same thing'"
    )

    # And what the Mac hands back when each chip is tapped is that half's screen, not the
    # other's — which is what "switching between them redraws" means on the wire.
    shown_left = await stage.touch("branch.show", session_id="split", branch_id=left.branch_id)
    shown_right = await stage.touch("branch.show", session_id="split", branch_id=right_id)
    assert shown_left.surface_types == left.surface_types
    assert shown_right.surface_types == right.surface_types
    assert shown_left.surface_types != shown_right.surface_types
    assert shown_left.answer != shown_right.answer

    # Each carries its own header, and the two headers differ. This is the difference the
    # owner could not find by tapping.
    heads = [c.raw["changed"]["headline"] for c in (shown_left, shown_right)]
    assert heads[0]["title"] != heads[1]["title"], heads
    assert {h["area"] for h in heads} == {"ORDERS", "INBOX"}, heads


async def test_a_forked_half_draws_nothing_of_its_parents_screen(stage):
    """A fork used to rebuild its parent's record from memory. That is the defect: two cards,
    identical, one under each chip."""
    parent = await stage.open_order("1938", session_id="fork-draw")
    assert parent.surface("order") is not None
    forked = await stage.client.post("/branches/fork", data={"session_id": "fork-draw"})
    child_id = forked.json()["branch_id"]

    shown = await stage.touch("branch.show", session_id="fork-draw", branch_id=child_id)
    assert shown.raw["changed"].get("empty") is True, shown.raw["changed"]
    assert shown.surface_types == [], "the fresh half drew its parent's card"
    assert "1938" in shown.answer, f"it must say what it starts FROM: {shown.answer!r}"
    # And a way forward, as commands the tablet can post unchanged.
    offer = shown.raw["changed"]["offer"]
    assert offer and offer[0]["command"] == "open.entity" and offer[0]["ref"]
    assert [o["command"] for o in offer[1:]] == ["open.area"] * 4


def test_a_fork_inherits_what_its_parent_holds_and_none_of_what_it_shows():
    parent = Branch(branch_id="br_a", session_id="s1")
    parent.visit("order", "o1", "#1957", tab="items")
    parent.set_id = "set_abc"
    parent.workflow = Workflow(workflow_id="wf", set_id="set_abc", kind="orders", total=10, cursor=3, label="10 orders")
    parent.shown([{"type": "order", "data": {}}], "1957 is Millie's.", "show me 1957")
    parent.compose = {"compose_id": "cmp_1", "kind": "reply"}
    parent.bind_voice("email.reply", label="Millie")

    child = fork_from(parent)
    assert child.entity == parent.entity and child.set_id == "set_abc"
    assert [e["ref"] for e in child.recent_entities] == [e["ref"] for e in parent.recent_entities]
    assert child.inherited["from"] == "br_a" and child.inherited["entity"]["ref"] == "o1"
    # And nothing of the screen, nothing half-written, nothing armed, nothing appliable.
    assert child.last_ui == [] and child.last_answer == "" and child.last_question == ""
    assert child.compose is None and child.workspace is None and child.voice_context is None
    assert child.task is None and child.recent_actions == []
    # Its own trail, its own cursor, its own id.
    assert child.branch_id != parent.branch_id and child.nav_index == 0 and len(child.nav) == 1
    child.workflow.cursor += 1
    assert parent.workflow.cursor == 3


def test_a_half_that_holds_nothing_says_so_and_says_what_to_do():
    empty = Branch(branch_id="br_new", session_id="s1")
    out = commands.run("branch.show", _ctx(_Session(empty), empty))
    assert out.ok and out.changed["empty"] is True
    assert "nothing yet" in out.answer
    assert [o["command"] for o in out.changed["offer"]] == ["open.area"] * 4
    assert out.changed["holds"]["entity"] is None


# --------------------------------------------------------------- the header on each half


def test_a_half_is_named_by_what_it_is_on():
    """The MACHINE's three keys, unchanged, plus the GLASS's one.

    `words` was added in Phase 5 and these expectations grew a key rather than changing one:
    `area`, `detail`, `state` and `title` are all exactly what they were, and the branch
    protocol and every other test that reads them are untouched. What is new is that the Mac
    now also sends the line in language, because the tablet was translating the tokens itself
    and getting it half right — the band above the cards read "EMPTY Orders" over a focused
    empty half. See `Branch.SAID_ALOUD`.
    """
    branch = Branch(branch_id="br_a", session_id="s1")
    assert branch.headline() == {"area": "EMPTY", "detail": "nothing yet", "state": "ACTIVE",
                                "words": "Nothing yet", "title": "EMPTY · nothing yet"}
    branch.visit("order", "o1", "#1957")
    assert branch.headline()["title"] == "ORDER · #1957"
    assert branch.headline()["words"] == "ORDER · #1957", "a real place keeps its own word"
    branch.entity = None
    branch.shown([{"type": "email_list", "data": {}}], "4 threads.", "the inbox")
    branch.ready("there is an answer")
    assert branch.headline() == {"area": "INBOX", "detail": "READY", "state": "READY",
                                "words": "INBOX · READY", "title": "INBOX · READY"}


def test_a_half_that_holds_nothing_says_so_once_and_not_in_two_ways():
    """§26 · the band the visual pass caught: "EMPTY Orders".

    A fork inherits its parent's working set and trail (`fork_from`, deliberately), so an
    empty half's `detail` falls back to that set's label. On a half that is WORKING on the set
    that is the right answer; on one that holds nothing it is a line saying at once that there
    is nothing here and that this is about today's orders. `words` carries one or the other,
    never both, and the tablet draws no detail beside a state word.
    """
    branch = Branch(branch_id="br_a", session_id="s1")
    branch.set_id = "set_1"
    branch.workflow = Workflow(workflow_id="wf_1", set_id="set_1", kind="order", label="Orders")
    head = branch.headline()
    assert head["area"] == "EMPTY", "the token is unchanged: the machine's half of the line"
    assert head["detail"] == "Orders", "and so is the inherited label the trail needs"
    assert head["words"] == "Nothing yet", "but the GLASS says one thing, not both"
    assert "Orders" not in head["words"]


def test_the_two_copies_of_the_state_words_cannot_drift():
    """The tablet keeps a fallback copy of `SAID_ALOUD` for a Mac older than its own build.

    Two copies of a translation is a defect waiting to happen, so they are held equal here:
    the same keys, and the same words up to the stylesheet's uppercasing.
    """
    page = (Path(__file__).resolve().parents[1] / "web" / "app.js").read_text(encoding="utf-8")
    found = re.search(r"const AREA_WORDS = \{([^}]*)\}", page)
    assert found, "web/app.js no longer has an AREA_WORDS fallback"
    tablet = dict(re.findall(r"(\w+): '([^']*)'", found.group(1)))
    assert set(tablet) == set(Branch.SAID_ALOUD), (
        f"the tablet says {sorted(tablet)}; the Mac says {sorted(Branch.SAID_ALOUD)}")
    for token, said in Branch.SAID_ALOUD.items():
        assert tablet[token].upper() == said.upper(), f"{token}: {tablet[token]!r} vs {said!r}"


def test_the_headline_and_the_state_go_out_with_every_branch():
    session = Session(session_id="s1")
    branch = session.branch()
    branch.visit("customer", "c1", "Millie Rogers")
    public = branch.public()
    assert public["state"] == "ACTIVE" and public["headline"]["title"] == "CUSTOMER · Millie Rogers"
    assert public["status"] == "ACTIVE", "where it lives and what it is doing are two fields"


# ------------------------------------------------------------------- five words, no more


def test_a_half_is_in_one_of_five_states_and_never_says_working_without_work():
    branch = Branch(branch_id="br_a", session_id="s1")
    assert branch.state() == "ACTIVE"
    branch.working("reading the order")
    assert branch.state() == "ACTIVE", "a note that says WORKING is not work in flight"
    branch.begin_turn("reading the order")
    assert branch.state() == "WORKING"
    branch.waiting("Shopify has not answered")
    assert branch.state() == "WAITING"
    branch.end_turn()
    assert branch.state() == "ACTIVE", "the turn ended; nothing is working here"
    branch.ready("there is an answer")
    assert branch.state() == "READY", "an outcome stands on its own"
    branch.failed("Shopify would not answer")
    assert branch.state() == "FAILED"
    branch.idle()
    assert branch.state() == "ACTIVE"
    assert BRANCH_STATES == ("ACTIVE", "WORKING", "WAITING", "READY", "FAILED")


def test_a_turn_that_died_does_not_leave_a_half_working_for_ever():
    """D-1's shape, on a branch chip: the one state that can get stuck must be reachable from
    outside. A half whose turn never came back reads ACTIVE, never WORKING."""
    branch = Branch(branch_id="br_a", session_id="s1")
    branch.begin_turn("looking it up")
    assert branch.state() == "WORKING"
    branch.in_flight = 0                      # the turn went away without finishing
    assert branch.state() == "ACTIVE"


def test_nothing_a_half_says_about_itself_is_a_number_out_of_a_number():
    branch = Branch(branch_id="br_a", session_id="s1")
    branch.begin_turn("reading nine orders")
    for state in (branch.state(), branch.headline()["state"], branch.public()["state"]):
        assert state in BRANCH_STATES
    assert "%" not in branch.headline()["title"]


# ------------------------------------------------ the refusals a forked half used to get


async def test_open_area_is_served_on_a_forked_half(stage):
    """`open.area ok=False code=landing_unavailable br_29a02563cf`, 00:25:48."""
    await stage.open_order("1938", session_id="fork-area")
    forked = await stage.client.post("/branches/fork", data={"session_id": "fork-area"})
    child_id = forked.json()["branch_id"]

    opened = await stage.touch("open.area", session_id="fork-area", branch_id=child_id, area="orders")
    assert opened.raw.get("ok") is True, opened.raw
    assert opened.surface_types, "a landing on a forked half must draw its place"
    assert opened.raw["branch"]["branch_id"] == child_id, "and draw it on the half that was tapped"

    other = stage.branch("fork-area")
    assert other.branch_id != child_id
    assert other.last_ui and other.last_ui[0]["type"] == "order", "the other half did not move"


async def test_a_landing_that_cannot_be_read_offers_the_tap_again(stage, monkeypatch):
    """It is still possible for a source not to answer. What is not allowed is a refusal with
    nothing on it to act on — which is what the owner was given, twice, in five seconds.

    Through the real tap: `open.area`, its recipe and the read scheduler, with the two order
    reads made to fail and nothing else. This used to build the refusal it asserted on by hand
    and never reached the landing code at all (the 2026-09-28 deploy review, round 9, I-tests4
    I-03)."""
    from app.tools import registry
    from app.tools.registry import ToolError

    await stage.open_order("1938", session_id="unreadable")
    real = registry.invoke

    async def invoke(name, args, *, timeout_s):
        if name == "commerce_query":
            raise ToolError("Shopify did not answer in time.")
        return await real(name, args, timeout_s=timeout_s)

    monkeypatch.setattr(registry, "invoke", invoke)
    refused = await stage.touch("open.area", area="orders", session_id="unreadable")
    raw = refused.raw
    assert raw.get("ok") is False and raw.get("code") == "landing_unavailable", raw
    assert "Tap it again" in str(raw.get("detail") or ""), raw
    changed = raw.get("changed") or {}
    assert changed.get("retry") == {"command": "open.area", "area": "orders"}, changed
    # What the half holds rides on the refusal, so the owner can go back to it from there.
    assert (changed.get("holds") or {}).get("entity", {}).get("ref") == "gid://shopify/Order/1938", changed
    offer = changed.get("offer") or []
    assert offer and offer[0] == {"command": "open.entity", "kind": "order", "ref": "gid://shopify/Order/1938",
                                  "label": "#1938", "words": "Open #1938"}, offer


async def test_open_entity_on_a_forked_half_opens_what_its_parent_was_shown(stage):
    """`open.entity ok=False code=not_held br_29a02563cf`, 00:25:53."""
    listed = await stage.ask("which orders are waiting to go out?", *WAITING_TO_GO_OUT, session_id="fork-entity")
    rows = listed.data("order_list").get("orders") or []
    assert rows, listed.surface_types
    ref = str(rows[0]["order_id"])

    forked = await stage.client.post("/branches/fork", data={"session_id": "fork-entity"})
    child_id = forked.json()["branch_id"]
    opened = await stage.touch("open.entity", session_id="fork-entity", branch_id=child_id,
                              kind="order", ref=ref)
    assert opened.raw.get("ok") is True, opened.raw
    assert opened.surface("order") is not None, opened.surface_types
    assert opened.raw["branch"]["branch_id"] == child_id


async def test_a_record_this_conversation_was_never_shown_is_refused_with_somewhere_to_go(stage):
    await stage.say("show me today's orders", session_id="fork-refuse")
    refused = await stage.touch("open.entity", session_id="fork-refuse", kind="order",
                                ref="gid://shopify/Order/999999")
    assert refused.raw.get("ok") is False and refused.raw["code"] == "not_held"
    offer = refused.raw["changed"]["offer"]
    assert [o["command"] for o in offer] == ["open.area"] * 4, offer
    assert "tap it there" in refused.raw["detail"].lower()


def test_a_kind_that_cannot_be_opened_alone_says_what_to_do_instead():
    session = Session(session_id="s1")
    branch = session.branch()
    session.issue("gid://shopify/Product/1")
    out = commands.run("open.entity", _ctx(session, branch, kind="product", ref="gid://shopify/Product/1"))
    assert not out.ok and out.code == "not_held"
    assert "product" in out.detail and "tap it there" in out.detail.lower()
    assert [o["command"] for o in out.changed["offer"]] == ["open.area"] * 4


# -------------------------------------------------------------------------- isolation


def test_one_halfs_state_changes_never_touch_the_others():
    session = Session(session_id="s1")
    left = session.branch()
    left.visit("order", "o1", "#1957", tab="overview")
    left.workflow = Workflow(workflow_id="wf", set_id="set_a", kind="orders", total=10, cursor=2)
    right = fork_from(left)
    session.branches[right.branch_id] = right

    right.visit("customer", "c9", "Someone Else", tab="orders")
    right.mark(scroll=640)
    right.workflow.cursor = 7
    right.expanded = ["row-1"]
    right.compose = {"compose_id": "cmp_r", "kind": "reply"}
    right.workspace = {"workspace_id": "ws_r", "kind": "discount"}
    right.bind_voice("email.reply", label="Someone")
    right.begin_turn("reading")
    right.remember_action("prop_r", "order_note_append", "PENDING")

    assert left.entity["ref"] == "o1" and left.tab == "overview" and left.scroll == 0
    assert left.workflow.cursor == 2 and left.expanded == []
    assert left.compose is None and left.workspace is None and left.voice_context is None
    assert left.state() == "ACTIVE" and right.state() == "WORKING"
    assert left.recent_actions == []
    assert left.headline()["title"] != right.headline()["title"]
    assert left.nav_index == 0 and len(left.nav) == 1 and len(right.nav) == 2


# --------------------------------------- a half put aside may prepare; it may never apply


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_half_put_aside_may_read_and_stage_and_can_never_apply(writes):
    """The hard invariant, driven rather than grepped.

    A background half reads, searches, analyses and STAGES — it does all of that here — and
    the only route to a mutation refuses it twice: at the arm and at the commit. The store's
    own record of every mutation that reached it is the proof that the path is unreachable.
    """
    from app.actions.models import ActionStatus
    from app.tools.dispatch import dispatch
    from tests.test_actions import ORDER, TOOL

    configure(writes)
    session = writes.runtime.sessions.get_or_create("aside")
    session.issue(ORDER)
    session.epoch = 1
    here = session.branch()
    aside = fork_from(here)
    session.branches[aside.branch_id] = aside
    session.focused_branch = here.branch_id
    # The half is put aside, and it is the half that asks.
    aside.status = "BACKGROUND"
    session.acting_branch = aside.branch_id

    text = await dispatch(TOOL, {"order_id": ORDER, "note": "Customer asked for an exchange"},
                          session=session, timeout_s=5)
    assert text.startswith("PROPOSED"), "a half put aside must still be able to prepare a change"
    proposal = session.proposals[-1]
    assert proposal.branch_id == aside.branch_id and proposal.status is ActionStatus.PENDING
    assert writes.store.mutations == [], "preparing a change reads; it never writes"

    armed = await writes.post(f"/actions/{proposal.proposal_id}/arm",
                              data={"session_id": "aside"}, headers=PROXIED)
    assert armed.status_code == 409 and armed.json()["code"] == "branch_not_focused", armed.json()
    refused = await commit(writes, proposal.proposal_id, session_id="aside")
    assert refused.status_code == 409 and refused.json()["code"] == "branch_not_focused", refused.json()
    assert writes.store.mutations == [], "the mutation path is reachable from a half put aside"
    assert session.proposals[-1].status is ActionStatus.PENDING, "and the change is still waiting"

    # And it is the ASIDE that is refused, not the change: brought back, the same card applies.
    aside.status = "ACTIVE"
    session.focused_branch = aside.branch_id
    applied = await commit(writes, proposal.proposal_id, session_id="aside")
    assert applied.status_code == 200, applied.json()
    assert [name for name, _ in writes.store.mutations] == ["order_note_set"]


async def test_a_finished_aside_says_ready_and_gives_up_its_work_when_it_is_tapped(writes):
    """The other half of §6: work put aside must be RETRIEVABLE. The Phase 2 live test found a
    half that finished a ten-second turn with an answer nobody could ever read."""
    from app.commands import Ctx, run

    session = writes.runtime.sessions.get_or_create("finished")
    here = session.branch()
    aside = fork_from(here)
    session.branches[aside.branch_id] = aside
    session.focused_branch = here.branch_id
    here.visit("order", "o1", "#1957")
    here.shown([{"type": "order", "data": {"order_number": "#1957"}}], "1957 is Millie's.", "order 1957")

    aside.begin_turn("looking through the inbox")
    assert aside.state() == "WORKING"
    aside.status = "BACKGROUND"
    aside.end_turn()
    aside.shown([{"type": "email_list", "data": {}}], "4 threads need replies.", "emails needing replies")
    aside.ready("there is an answer")

    listed = (await writes.get("/branches", params={"session_id": "finished"})).json()
    states = {b["branch_id"]: b["state"] for b in listed["branches"]}
    assert states[aside.branch_id] == "READY" and states[here.branch_id] == "ACTIVE"
    heads = {b["branch_id"]: b["headline"]["title"] for b in listed["branches"]}
    assert heads[aside.branch_id] == "INBOX · READY" and heads[here.branch_id] == "ORDER · #1957"

    out = run("branch.show", Ctx(writes.runtime, session, here, {"branch_id": aside.branch_id}))
    assert out.ok and [s.as_ui()["type"] for s in out.surfaces] == ["email_list"]
    assert out.answer == "4 threads need replies."
    assert out.changed["state"] == "READY" and out.changed["headline"]["area"] == "INBOX"


# -------------------------------------------------------------------------- the merge


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
async def test_a_merge_brings_state_and_never_a_transcript_or_an_unresolved_change(writes):
    """Structured results and structured state; never a conversation, and never a change
    somebody has not looked at. A proposal staged over there stays over there, exact, PENDING
    and still bound to the half it was asked for in."""
    from app.actions.models import ActionStatus
    from app.tools.dispatch import dispatch
    from tests.test_actions import ORDER, TOOL

    configure(writes)
    session = writes.runtime.sessions.get_or_create("merge")
    session.issue(ORDER)
    session.epoch = 1
    keeper = session.branch()
    other = fork_from(keeper)
    session.branches[other.branch_id] = other
    other.visit("customer", "c1", "Millie Rogers")
    other.shown([{"type": "email_list", "data": {}}], "4 threads.", "who is waiting?")
    other.remember_result("gmail_search", summary="gmail_search: 4 threads", ref="", ms=90.0)
    session.acting_branch = other.branch_id
    await dispatch(TOOL, {"order_id": ORDER, "note": "Exchange agreed"}, session=session, timeout_s=5)
    staged_there = session.proposals[-1]

    merged = (await writes.post(f"/branches/{other.branch_id}/merge",
                                data={"session_id": "merge"})).json()["merged"]
    assert merged["headline"]["title"] == "CUSTOMER · Millie Rogers" and merged["state"] == "ACTIVE"
    assert merged["read"][0]["tool"] == "gmail_search"
    assert "answer" not in merged and "question" not in merged and "last_ui" not in merged
    assert merged["still_waiting"] == [staged_there.proposal_id], "the change is named, not moved"
    assert staged_there.status is ActionStatus.PENDING
    assert staged_there.branch_id == other.branch_id, "a change belongs to the half it was asked in"
    assert writes.store.mutations == [], "a merge is not a gesture"


def test_the_halves_share_only_what_is_safe_to_share():
    """Read caches and the issued-id ledger are the conversation's; a position, a proposal or
    an approval is one half's. Asserted on the objects, because this is the rule the whole
    file exists to keep."""
    session = Session(session_id="s1")
    left = session.branch()
    left.visit("order", "o1", "#1957")
    session.issue("gid://shopify/Order/1957")
    right = fork_from(left)
    session.branches[right.branch_id] = right
    assert "gid://shopify/Order/1957" in session.issued_ids, "one ledger for the conversation"
    assert not hasattr(right, "issued_ids"), "and it is not branch state"
    assert left.nav is not right.nav
    assert left.recent_entities is not right.recent_entities
    assert left.entity is not right.entity
