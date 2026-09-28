"""Two halves of the orb think at once (brief section 3F).

The provider keeps one Claude conversation per half, with its own lock and its own turn
state; the route addresses the half's conversation and judges "moved on" per half; the
tablet's cancel names the half. What is NOT concurrent is unchanged: two questions to the
same half still queue, and the action engine still stages and commits exactly as before.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from app.providers.base import TurnResult
from app.session.models import Session

# ---------------------------------------------------------------------------- the provider


class GatedSDKClient:
    """A fake `claude` subprocess whose answer waits on a gate, so a test can hold one turn
    open while another starts."""

    instances: list = []

    def __init__(self, options=None):
        self.options = options
        self.connected = False
        self.closed = False
        self.queries: list[str] = []
        self.gate = asyncio.Event()
        self.interrupted = 0
        GatedSDKClient.instances.append(self)

    async def connect(self):
        self.connected = True

    async def disconnect(self):
        self.closed = True

    async def interrupt(self):
        self.interrupted += 1
        self.gate.set()

    async def get_server_info(self):
        return {"account": {"apiKeySource": "claude.ai", "apiProvider": "firstParty"}}

    async def query(self, text):
        self.queries.append(text)

    async def receive_response(self):
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

        await self.gate.wait()
        yield AssistantMessage(content=[TextBlock(text=f"answer to {self.queries[-1]}")], model="fake")
        yield ResultMessage(subtype="success", duration_ms=1, duration_api_ms=1, is_error=False, num_turns=1, session_id="cli")


@pytest.fixture()
def provider(monkeypatch):
    pytest.importorskip("claude_agent_sdk")
    import claude_agent_sdk

    from app.providers.max_agent_sdk import MaxAgentSDKProvider
    from app.tools import mock  # noqa: F401 — registers tools

    GatedSDKClient.instances = []
    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", GatedSDKClient)
    sessions: dict[str, Session] = {}

    def lookup(session_id):
        return sessions.setdefault(session_id, Session(session_id=session_id))

    p = MaxAgentSDKProvider(system_prompt="sys", cli_path=sys.executable, session_lookup=lookup, max_concurrent_turns=2)
    p._started, p._auth_mode = True, "cli"
    p.sessions = sessions
    return p


async def _settled(task: asyncio.Task, *, within: float = 0.2) -> bool:
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=within)
        return True
    except TimeoutError:
        return False


async def test_two_halves_think_at_once(provider):
    session = provider.sessions.setdefault("s", Session(session_id="s"))
    left = session.branch().branch_id
    from app.session.branch import Branch

    session.branches["b_right"] = Branch(branch_id="b_right", session_id="s")

    first = asyncio.create_task(provider.turn_on_branch("s", "left question", branch_id=left))
    await asyncio.sleep(0.02)
    second = asyncio.create_task(provider.turn_on_branch("s", "right question", branch_id="b_right"))
    await asyncio.sleep(0.02)
    # Both subprocesses have been asked; neither has answered. This is the point: the right
    # half's question was not queued behind the left half's thinking.
    asked = [c for c in GatedSDKClient.instances if c.queries]
    assert sorted(c.queries[0] for c in asked) == ["left question", "right question"]
    assert not first.done() and not second.done()
    # The right half answers first, though it was asked second.
    next(c for c in asked if c.queries[0] == "right question").gate.set()
    assert await _settled(second)
    assert second.result().text == "answer to right question" and not first.done()
    next(c for c in asked if c.queries[0] == "left question").gate.set()
    assert await _settled(first)
    assert first.result().text == "answer to left question"
    # Two conversations, keyed by half; the session's own key is not one of them.
    assert sorted(provider._conversations) == sorted([f"s/{left}", "s/b_right"])
    await provider.stop()


async def test_the_same_half_still_queues(provider):
    session = provider.sessions.setdefault("s", Session(session_id="s"))
    left = session.branch().branch_id
    first = asyncio.create_task(provider.turn_on_branch("s", "one", branch_id=left))
    await asyncio.sleep(0.02)
    second = asyncio.create_task(provider.turn_on_branch("s", "two", branch_id=left))
    await asyncio.sleep(0.02)
    only = next(c for c in GatedSDKClient.instances if c.queries)
    assert only.queries == ["one"]              # "two" waits for the conversation's lock
    only.gate.set()
    assert await _settled(first)
    await asyncio.sleep(0.02)
    assert only.queries == ["one", "two"]       # then runs on the same conversation
    assert await _settled(second)
    assert len([c for c in GatedSDKClient.instances if c.queries]) == 1
    await provider.stop()


async def test_a_third_turn_waits_for_a_slot(provider):
    """Two at once is the ceiling: a third half — there is no third half, but a second
    session's question counts the same — waits for a subprocess to finish."""
    for sid in ("a", "b", "c"):
        provider.sessions.setdefault(sid, Session(session_id=sid))
    tasks = [asyncio.create_task(provider.turn_on_branch(sid, f"q{sid}", branch_id="x")) for sid in ("a", "b", "c")]
    await asyncio.sleep(0.05)
    asked = [c for c in GatedSDKClient.instances if c.queries]
    assert len(asked) == 2
    asked[0].gate.set()
    await asyncio.sleep(0.05)
    asked = [c for c in GatedSDKClient.instances if c.queries]
    assert len(asked) == 3
    for c in asked:
        c.gate.set()
    for t in tasks:
        assert await _settled(t)
    await provider.stop()


async def test_a_cancel_names_the_half_it_stops(provider):
    session = provider.sessions.setdefault("s", Session(session_id="s"))
    left = session.branch().branch_id
    from app.session.branch import Branch

    session.branches["b_right"] = Branch(branch_id="b_right", session_id="s")
    first = asyncio.create_task(provider.turn_on_branch("s", "left question", branch_id=left))
    second = asyncio.create_task(provider.turn_on_branch("s", "right question", branch_id="b_right"))
    await asyncio.sleep(0.05)
    by_question = {c.queries[0]: c for c in GatedSDKClient.instances if c.queries}
    assert await provider.interrupt("s", branch_id="b_right") is True
    assert by_question["right question"].interrupted == 1
    assert by_question["left question"].interrupted == 0      # the other half thinks on
    assert await _settled(second) and not first.done()
    # Without a half, the whole session — as /cancel always did.
    assert await provider.interrupt("s") is True
    assert by_question["left question"].interrupted == 1
    assert await _settled(first)
    # Nothing running: nothing to interrupt.
    assert await provider.interrupt("s") is False
    await provider.stop()


async def test_reset_session_drops_every_half(provider):
    session = provider.sessions.setdefault("s", Session(session_id="s"))
    left = session.branch().branch_id
    convs = [await provider._conversation_for("s", left), await provider._conversation_for("s", "b_right"), await provider._conversation_for("t", "")]
    await provider.reset_session("s")
    assert list(provider._conversations) == ["t"]
    assert convs[0].client.closed and convs[1].client.closed and not convs[2].client.closed
    assert convs[0].holder.conversation is None
    await provider.stop()


async def test_a_turn_without_a_half_keeps_the_plain_session_key(provider):
    provider.sessions.setdefault("s", Session(session_id="s"))
    task = asyncio.create_task(provider.turn("s", "plain"))
    await asyncio.sleep(0.02)
    assert "s" in provider._conversations
    next(c for c in GatedSDKClient.instances if c.queries).gate.set()
    assert await _settled(task)
    await provider.stop()


# ------------------------------------------------------------------------------- the route


def test_moved_on_is_judged_per_half():
    from app.routes.turn import _moved_on
    from app.session.branch import Branch

    session = Session(session_id="s")
    left = session.branch()
    right = Branch(branch_id="b_right", session_id="s")
    session.branches[right.branch_id] = right
    left.instruction_seq = 2
    # The right half speaks: the epoch moves, the left half's turn is not abandoned.
    session.epoch += 1
    assert _moved_on(session, left, epoch=session.epoch - 1, seq=2) is False
    # The left half is spoken to again.
    left.instruction_seq = 3
    assert _moved_on(session, left, epoch=session.epoch, seq=2) is True
    # A cancel aimed at the left half.
    left.instruction_seq = 2
    left.abandoned = True
    assert _moved_on(session, left, epoch=session.epoch, seq=2) is True
    left.abandoned = False
    # A turn that knows no half keeps the session-wide rule.
    assert _moved_on(session, None, epoch=session.epoch - 1, seq=None) is True
    assert _moved_on(session, None, epoch=session.epoch, seq=None) is False
    # A session-wide cancel abandons everything.
    session.abandoned = True
    assert _moved_on(session, left, epoch=session.epoch, seq=2) is True


async def test_the_route_addresses_the_halfs_conversation(monkeypatch):
    """The turn route hands the provider the half it is speaking to, when the provider can
    take one; a test double without the method gets the plain turn."""
    from app.routes.turn import _provider_turn
    from app.session.branch import Branch

    class WithHalves:
        def __init__(self):
            self.seen = []

        async def turn(self, session_id, text):
            self.seen.append(("plain", session_id))
            return TurnResult(text="plain", session_id=session_id)

        async def turn_on_branch(self, session_id, text, *, branch_id=""):
            self.seen.append(("half", branch_id))
            return TurnResult(text="half", session_id=session_id)

    class Plain:
        async def turn(self, session_id, text):
            return TurnResult(text="plain", session_id=session_id)

    class R:
        pass

    runtime = R()
    runtime.provider = WithHalves()
    branch = Branch(branch_id="b_left", session_id="s")
    assert (await _provider_turn(runtime, "s", "hi", branch)).text == "half"
    assert runtime.provider.seen == [("half", "b_left")]
    runtime.provider = Plain()
    assert (await _provider_turn(runtime, "s", "hi", branch)).text == "plain"


# ------------------------------------------------------------------ section 25's three numbers


def test_the_workspace_timing_separates_the_facts_from_the_prose():
    """Brief section 25: time-to-first-useful-workspace measured APART from the whole turn.

    The number that matters is the third one — how long the owner waited AFTER the Mac held
    the data the cards are drawn from. On the live bench that was most of a twenty-five-second
    turn, and a report that only prints the total cannot see it.
    """
    from app.routes.turn import _workspace_timing

    # A model turn: two tool calls landed at 400 ms and 1,200 ms; the answer left at 9,000 ms.
    timings = {"step:tool:shopify_order_detail": 400.0, "step:tool:gmail_read_thread": 1200.0,
               "workspace": 9010.0, "total": 9020.0, "agent": 8800.0}
    facts, workspace, waited = _workspace_timing(timings, calls=[], measures={})
    assert facts == 1200.0, "the last read to land is when the workspace could have been drawn"
    assert workspace == 9010.0
    assert waited == 7820.0, "seven seconds of it was prose about data already read"

    # Neither: fall back to the reads themselves, which ran in parallel where they could.
    class _Call:
        def __init__(self, ms): self.duration_ms = ms

    facts, _, waited = _workspace_timing({"total": 900.0}, calls=[_Call(120.0), _Call(300.0)], measures={})
    assert facts == 300.0 and waited == 600.0

    # A turn that read nothing — a capability answer, a navigation move — is not slow prose.
    facts, workspace, waited = _workspace_timing({"workspace": 12.0, "total": 13.0}, calls=[], measures={})
    assert facts is None and waited is None and workspace == 12.0


def test_the_performance_record_names_the_regions_still_loading():
    """An order card that left with its history and inbox still reading says so in the record,
    so the report can pair it with the /context/order request that finishes the job."""
    from app.routes.turn import _performance

    ui = [
        {"type": "order", "data": {"order_number": "#1938", "pending": ["history", "email"]}},
        {"type": "context_stack", "data": {}},
    ]
    record = _performance({"total": 500.0, "workspace": 480.0}, branch=None, calls=[], session=None,
                          measures={}, ui=ui)
    assert record["enrichment_pending"] == ["email", "history"]
    assert record["workspace_ms"] == 480.0
    # And a turn whose cards are complete says nothing rather than an empty list.
    assert _performance({"total": 500.0}, branch=None, calls=[], session=None, measures={},
                        ui=[{"type": "order", "data": {}}])["enrichment_pending"] is None
    # Every turn is a model turn now, and the record says so rather than leaving it out.
    assert record["lane"] == "NORMAL" and record["model_calls"] == 1 and "recipe_id" not in record
