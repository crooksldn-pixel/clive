"""objective_list stays small however many objectives there are (9 Oct 2026).

Each objective's summary is about 1.25 KB as the model reads it, with lines as long as real ones.
Every live objective, or every closed one ever, was listed whole: forty passed the size at which the
claude CLI starts counting a tool's result (50,000 characters), and the closed list only ever grows.
These hold it to MAX_LIST_BYTES, the most recently changed first, with every other one counted and
found by `search`, and objective_show still reading any one whole. Invented objectives only.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest

from app.objectives import store as store_module
from app.objectives import tools
from app.session.models import Session
from app.tools.dispatch import dispatch

CLI_UNCOUNTED_CHARS = 50_000   # tests/test_engineering_status_bounds.py says where this comes from


@pytest.fixture
def s(tmp_path, monkeypatch):
    """A store of its own, on a clock a minute a change, so "most recently changed" is never a tie."""
    fresh = store_module.ObjectiveStore(tmp_path / "objectives")
    monkeypatch.setattr(store_module, "_STORE", fresh)
    ticks = iter(range(1, 1_000_000))
    start = datetime(2026, 9, 1, tzinfo=UTC)
    monkeypatch.setattr(store_module, "_now",
                        lambda: (start + timedelta(minutes=next(ticks))).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return fresh


def run(coro):
    return asyncio.run(coro)


def _line(n: int, words: int = 24) -> str:
    base = ("the sample round for the drop moved on once the factory confirmed the fabric weight and the trims "
            "came on the Tuesday van with the corrected care labels").split()
    return " ".join(base[(n + i) % len(base)] for i in range(words)).capitalize() + "."


def _objective(s, n: int):
    """An invented objective with lines as long as real ones: three blockers, three items, a question."""
    obj = s.create(title=f"Invented objective {n:03d}: the drop sampling", request=_line(n, 30), kind="project",
                   stages=["Sampling", "Approval", "Production", "Delivery"], stage="Sampling",
                   waiting_on="the factory", deadline="2026-12-01")
    for i in range(3):
        s.add_blocker(obj.id, _line(n + i), kind="external")
        s.propose(obj.id, _line(n + i + 5, 16), needs_owner=i == 0)
    s.ask_owner(obj.id, _line(n + 9, 14))
    return obj


async def _read(args: dict) -> tuple[str, dict]:
    text = await dispatch("objective_list", args, session=Session(session_id="obj-list"), timeout_s=10)
    return text, json.loads(text)


@pytest.mark.usefixtures("owner_asking")
def test_sixty_closed_objectives_stay_under_the_ceiling_newest_first_and_the_rest_are_searched(s):
    made = [_objective(s, n) for n in range(60)]
    for obj in made:
        s.close(obj.id, "complete", note="Done, as he said.")
    whole = [o.summary() for o in s.closed()]
    assert len(json.dumps({"closed": True, "objectives": whole}, ensure_ascii=False)) > CLI_UNCOUNTED_CHARS, \
        "listed whole, as before, it is past the size the CLI counts"

    text, out = run(_read({"closed": True}))

    assert len(text.encode("utf-8")) <= tools.MAX_LIST_BYTES
    named = [o["id"] for o in out["objectives"]]
    assert 0 < len(named) <= tools.MAX_LISTED
    assert named == [o.id for o in reversed(made)][: len(named)], "the most recently changed first"
    assert out["not_listed"] == (f"{60 - len(named)} more closed objectives not listed, the least recently "
                                 "changed: search finds one by anything in its record.")
    # The oldest is not listed, and is found by its words, and read whole by its id.
    oldest = made[0]
    assert oldest.id not in named
    found = run(_read({"closed": True, "search": "objective 000"}))[1]
    assert [o["id"] for o in found["objectives"]] == [oldest.id] and "not_listed" not in found
    shown = run(tools.objective_show(oldest.id))
    assert len(shown["blockers"]) == 3 and shown["blockers"][0]["text"] == _line(0)


@pytest.mark.usefixtures("owner_asking")
def test_forty_five_live_objectives_stay_under_the_ceiling(s):
    made = [_objective(s, n) for n in range(45)]

    text, out = run(_read({}))

    assert len(text.encode("utf-8")) <= tools.MAX_LIST_BYTES and "closed" not in out
    named = [o["id"] for o in out["objectives"]]
    assert named == [o.id for o in reversed(made)][: len(named)]
    assert out["not_listed"].startswith(f"{45 - len(named)} more objectives not listed")


def test_a_few_objectives_are_listed_as_before(s):
    made = [_objective(s, n) for n in range(4)]
    out = run(tools.objective_list())
    assert {o["id"] for o in out["objectives"]} == {o.id for o in made} and "not_listed" not in out
    assert out["objectives"][0] == s.get(made[-1].id).summary(), "short lines are as the summary says them"


def test_an_objective_with_lines_at_their_longest_is_listed_with_each_line_cut(s):
    obj = s.create(title="Invented " + "t" * 1990, request="r", kind="business")
    for i in range(3):
        s.add_blocker(obj.id, f"{i} " + "b" * 1990, kind="external")
        s.propose(obj.id, f"{i} " + "n" * 1990, needs_owner=False)
    for i in range(10):
        s.ask_owner(obj.id, f"{i} " + "q" * 1990)

    out = run(tools.objective_list())

    (row,) = out["objectives"]
    assert len(json.dumps(out).encode("utf-8")) <= tools.MAX_LIST_BYTES
    assert len(row["title"]) <= tools.MAX_LINE, "the store keeps a title shorter still"
    assert [len(line) for line in row["blocked_by"]] == [tools.MAX_LINE] * 3
    assert all(line.endswith("...") for line in row["blocked_by"] + row["next"] + row["needs_you"])
    assert len(row["needs_you"]) == tools.MAX_NEEDS_YOU and row["needs_you_more"] == 7
    whole = run(tools.objective_show(obj.id))
    assert len(whole["attention"]) == 10 and len(whole["attention"][0]["text"]) == 1992, "the record is whole"
