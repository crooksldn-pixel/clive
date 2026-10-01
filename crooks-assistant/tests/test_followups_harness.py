"""Follow-ups from the round-12 deploy review (30 September 2026): the experience harness, the TV
browser gate and the tool audit, each made able to fail when it should.

* **X1-01** — `model_could_make` holds a scripted call to its tool's schema all the way down: a
  nested object's required field, an array's items, a number's bounds, a string's length.
* **X1-02** — run live, `needs_reply` passes a healthy inbox with nobody waiting, said as such;
  the fixture run still needs exactly the world's waiting threads.
* **R9-H-experience1-H-05** — a queue that lists a waiting thread twice fails the oracle.
* **X1-04** — a matrix row is live-read-safe only when every scenario under it runs live and
  stages no write; the model_turn row is not.
* **X2-02** — `abandoned_window` holds the week's count and value to the golden world exactly,
  and reads the seven-day filter off the request Shopify was sent.
* **X2-01** — `tv_flow` fails a driver that exits non-zero or leaves a mode or a change out.
* **SC1-01** — `tv_flow.js`'s verdict fails on a page error, an unreadable change or a time over
  its limit (tests/web/followups-tv-flow.test.js, run here under Node).
* **R9-I-tests5-I-05** — a dispatch in a helper is a citation only when a test calls the helper.
* **R9-H-experience1-H-06** — a tool name a scenario holds only as data is not coverage.
* **R9-H-experience1-F-A2-FIXTURE** — the harness leaves `app.state` and every binding as it
  found them, the housekeeper included.
* **DOC2-02** — the tool matrix says what "read" means there and names the screen tools that
  change what a screen shows.

Every name, address and order here is invented.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from experience import harness as harness_module
from experience import matrix, tool_matrix, tv_flow
from experience.fixtures import data, world
from experience.harness import Capture, model_could_make
from experience.scenario_packs import abandoned
from experience.scenarios import LIVE_SCENARIOS, needs_reply

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed here")


def _check(result, prefix: str):
    found = [c for c in result.checks if c.what.startswith(prefix)]
    assert found, f"no check starting {prefix!r}: {[c.what for c in result.checks]}"
    return found[0]


# ====================================================================== X1-01: the whole schema


PROBE = "probe_nested_order"


@pytest.fixture()
def probe_tool(monkeypatch):
    """A tool of the shapes a real one takes, in the registry for this test only."""
    from app.tools import registry
    from app.tools.gate import Tier

    async def handler(**_kwargs):
        return {}

    schema = {
        "type": "object",
        "properties": {
            "order": {
                "type": "object",
                "properties": {
                    "lines": {"type": "array", "items": {
                        "type": "object",
                        "properties": {"title": {"type": "string"}, "quantity": {"type": "integer", "minimum": 1}},
                        "required": ["title", "quantity"],
                    }},
                },
                "required": ["lines"],
            },
            "tags": {"type": "array", "items": {"type": "string", "maxLength": 12}, "maxItems": 3},
            "percent": {"type": "number", "minimum": 1, "maximum": 100},
            "note": {"type": "string", "maxLength": 40},
        },
        "required": ["order"],
    }
    spec = registry.ToolSpec(name=PROBE, description="A probe.", input_schema=schema, tier=Tier.GREEN, handler=handler)
    monkeypatch.setitem(registry._REGISTRY, PROBE, spec)
    return spec


def _runtime(writes: bool = False):
    return SimpleNamespace(settings=SimpleNamespace(writes_enabled=writes), withheld_by_family=lambda: set())


GOOD = {"order": {"lines": [{"title": "Field Jacket", "quantity": 2}]}, "tags": ["gift"], "percent": 20, "note": "Leave by the gate."}


@pytest.mark.parametrize("args, said", [
    ({**GOOD, "order": {"lines": [{"title": "Field Jacket"}]}}, "order: lines: item 0: it requires 'quantity'"),
    ({**GOOD, "order": {}}, "order: it requires 'lines'"),
    ({**GOOD, "tags": ["gift", 7]}, "tags: item 1: int where the schema says string"),
    ({**GOOD, "order": {"lines": [{"title": "Field Jacket", "quantity": "2"}]}},
     "order: lines: item 0: quantity: str where the schema says integer"),
    ({**GOOD, "percent": 150}, "percent: 150 is outside the schema's maximum of 100"),
    ({**GOOD, "percent": 0}, "percent: 0 is outside the schema's minimum of 1"),
    ({**GOOD, "order": {"lines": [{"title": "Field Jacket", "quantity": 0}]}},
     "order: lines: item 0: quantity: 0 is outside the schema's minimum of 1"),
    ({**GOOD, "note": "x" * 41}, "note: 41 characters where the schema allows at most 40"),
    ({**GOOD, "tags": ["a-very-long-tag-name"]}, "tags: item 0: 20 characters where the schema allows at most 12"),
    ({**GOOD, "tags": ["a", "b", "c", "d"]}, "tags: 4 items where the schema allows at most 3"),
])
def test_a_call_the_schema_refuses_below_its_top_level_is_named_with_the_reason(probe_tool, args, said):
    assert model_could_make(_runtime(), PROBE, GOOD) == "", "the same call, admitted all the way down, could be made"
    assert model_could_make(_runtime(), PROBE, args) == said


def test_an_integer_is_any_number_with_no_fractional_part(probe_tool):
    """JSON Schema's `integer`, not Python's `int` (the 2026-10-01 repair, F-01): 2.0 is an
    integer and 2.5 is not, and a boolean is never one."""
    def quantity(value):
        return {**GOOD, "order": {"lines": [{"title": "Field Jacket", "quantity": value}]}}

    assert model_could_make(_runtime(), PROBE, quantity(2.0)) == ""
    assert model_could_make(_runtime(), PROBE, quantity(2.5)) == (
        "order: lines: item 0: quantity: float where the schema says integer")
    assert model_could_make(_runtime(), PROBE, quantity(True)) == (
        "order: lines: item 0: quantity: bool where the schema says integer")
    assert model_could_make(_runtime(), PROBE, quantity(0.0)) == (
        "order: lines: item 0: quantity: 0.0 is outside the schema's minimum of 1")


def test_a_real_tools_array_items_are_held_to_its_schema():
    import app.tools.shopify_tools  # noqa: F401 — registers the tool asked about

    runtime = _runtime(writes=True)
    assert model_could_make(runtime, "shopify_order_tags_add", {"order_id": "gid://shopify/Order/1", "tags": ["hold"]}) == ""
    assert "tags: item 0: int where the schema says string" == model_could_make(
        runtime, "shopify_order_tags_add", {"order_id": "gid://shopify/Order/1", "tags": [5]})


# ====================================================================== X1-02 and H-05: needs_reply


class _Inbox:
    """A harness that answers the Inbox tap with one capture, live or against the fixture."""

    def __init__(self, capture: Capture, *, live: bool) -> None:
        self.capture, self.live = capture, live

    async def touch(self, command, **_kwargs):
        return self.capture


RECENT = {"type": "email_list", "data": {"threads": [{"from": "Ada Quill", "subject": "Sizes"}], "count": 1}}


def _tapped(ui, answer) -> Capture:
    return Capture(scenario="needs_reply", kind="touch", command="open.area", model_calls=0, ui=ui, answer=answer)


def _queue(rows) -> dict:
    return {"type": "work_queue", "surface": "work_queue",
            "data": {"title": "Waiting on a reply", "count": len(rows), "threads": rows}}


def _waiting_rows() -> list[dict]:
    def last(thread):
        return max(thread.messages, key=lambda m: (-m.days_ago, m.hour)).sender.split("<")[0].strip()

    return [{"thread_id": t.thread_id, "from": last(t)} for t in world.needs_reply()]


def _named(rows) -> str:
    names = [row["from"] for row in rows]
    return f"{len(rows)} people are waiting on a reply in the inbox's last 30 days: {', '.join(names[:-1])} and {names[-1]}."


async def test_live_an_inbox_with_nobody_waiting_passes_when_it_is_said_so():
    said = "Nobody is waiting on a reply in the inbox's last 30 days — 14 threads from people checked."
    result = await needs_reply(_Inbox(_tapped([RECENT], said), live=True))
    assert result.status == "PASS", [(c.what, c.detail) for c in result.failures]
    assert _check(result, "and the answer says nobody is waiting").ok


async def test_live_an_empty_queue_with_an_answer_that_does_not_say_so_fails():
    result = await needs_reply(_Inbox(_tapped([RECENT], "3 threads from people this week."), live=True))
    assert result.status == "FAIL"
    assert not _check(result, "and the answer says nobody is waiting").ok


async def test_live_an_empty_queue_card_that_counts_somebody_fails():
    queue = _queue([])
    queue["data"]["count"] = 2
    said = "Nobody is waiting on a reply in the inbox's last 30 days — 14 threads from people checked."
    result = await needs_reply(_Inbox(_tapped([queue, RECENT], said), live=True))
    assert result.status == "FAIL"
    assert not _check(result, "an empty queue counts nobody").ok


async def test_a_queue_that_repeats_a_waiting_thread_fails_the_oracle_and_the_fixture_run_needs_each_once():
    """H-05: the rows are compared as a list, so a thread listed twice is a wrong queue even
    though the set of its ids is the world's. And X1-02's other half: the fixture run still
    needs exactly the world's waiting threads — not none of them, not some."""
    rows = _waiting_rows()
    assert len(rows) >= 2, "the golden world has people waiting"
    passed = await needs_reply(_Inbox(_tapped([_queue(rows), RECENT], _named(rows)), live=False))
    assert passed.status == "PASS", [(c.what, c.detail) for c in passed.failures]
    said = "Nobody is waiting on a reply in the inbox's last 30 days — 14 threads from people checked."
    empty = await needs_reply(_Inbox(_tapped([RECENT], said), live=False))
    assert empty.status == "FAIL", "an empty queue is wrong against a world with people waiting"
    short = await needs_reply(_Inbox(_tapped([_queue(rows[:-1]), RECENT], _named(rows[:-1])), live=False))
    assert not _check(short, "the queue holds exactly the threads").ok
    doubled = [rows[0], *rows]
    result = await needs_reply(_Inbox(_tapped([_queue(doubled), RECENT], _named(doubled)), live=False))
    assert result.status == "FAIL"
    assert not _check(result, "the queue holds exactly the threads").ok


# ====================================================================== X1-04: the live column


def test_the_model_turn_row_is_not_live_read_safe():
    rows = {row["operation"]: row for row in matrix.build()}
    turn = rows["model_turn"]
    assert turn["fixture_test"], "the row has scenarios"
    assert turn["live_read_test"] is False, "scenarios under it stage writes, and a live run runs none of them"


def test_a_row_is_live_read_safe_only_when_every_scenario_runs_live_and_stages_nothing(monkeypatch):
    assert {"today_orders", "needs_reply"} <= LIVE_SCENARIOS
    assert matrix.live_read_safe("x", ("today_orders", "needs_reply"), staging=set()) is True
    assert matrix.live_read_safe("x", ("today_orders", "order_lookup"), staging=set()) is False, "not run live"
    assert matrix.live_read_safe("x", ("today_orders",), staging={"today_orders"}) is False, "stages a write"
    assert matrix.live_read_safe("x", (), staging=set()) is False, "no scenario"
    # And through the matrix itself, both ways.
    monkeypatch.setitem(matrix.COVERAGE, "model_turn", ("today_orders", "needs_reply"))
    assert {r["operation"]: r for r in matrix.build()}["model_turn"]["live_read_test"] is True
    monkeypatch.setitem(matrix.COVERAGE, "model_turn", ("today_orders", "compose_send_spoken"))
    assert {r["operation"]: r for r in matrix.build()}["model_turn"]["live_read_test"] is False


# ====================================================================== X2-02: abandoned_window


class _Shop:
    """A harness whose model answers the week's question with the figures given, and whose store
    records the request the read sent."""

    live = False

    def __init__(self, *, count: str, value: str, query: str) -> None:
        self.store = SimpleNamespace(queries=[])
        self.count, self.value, self.query = count, value, query

    def configure(self, **_kwargs) -> None: ...

    async def ask(self, text, *tools, **_kwargs):
        self.store.queries.append(("CrooksAbandonedCheckouts", {"q": self.query, "n": 25}))
        metrics = [{"label": "checkouts abandoned", "value": self.count}, {"label": "not taken", "value": self.value},
                   {"label": "average each", "value": "£1.00"}]
        return Capture(scenario="abandoned_window", command=text, model_calls=1, lane="NORMAL",
                       ui=[{"type": "metric_group", "data": {"subtitle": "in the last week", "metrics": metrics}}],
                       reads=["CrooksAbandonedCheckouts"])


def _week() -> tuple[str, str]:
    week = abandoned._window(7)
    return str(len(week)), f"£{sum(data.abandoned_total(x) for x in week):,.2f}"


def _filter() -> str:
    from app.families.abandoned import _since

    return f"created_at:>='{_since(7)}'"


async def test_the_weeks_exact_figures_pass_and_zero_where_the_week_has_checkouts_fails():
    count, value = _week()
    assert int(count) > 0, "the golden world has checkouts in the week"
    exact = await abandoned.abandoned_window(_Shop(count=count, value=value, query=_filter()))
    assert exact.status == "PASS", [(c.what, c.detail) for c in exact.failures]
    zero = await abandoned.abandoned_window(_Shop(count="0", value=value, query=_filter()))
    assert zero.status == "FAIL"
    assert not _check(zero, "the count is the golden world's own for the week").ok


async def test_the_fortnights_figures_for_the_week_fail():
    fortnight = abandoned._window(14)
    assert len(fortnight) != len(abandoned._window(7))
    value = f"£{sum(data.abandoned_total(x) for x in fortnight):,.2f}"
    result = await abandoned.abandoned_window(_Shop(count=str(len(fortnight)), value=value, query=_filter()))
    assert not _check(result, "the count is the golden world's own for the week").ok
    assert not _check(result, "and the value is the arithmetic over the week's checkouts").ok


async def test_a_read_without_the_seven_day_filter_fails_though_its_name_says_abandoned():
    count, value = _week()
    for query in ("", "created_at:>='2001-01-01T00:00:00Z'"):
        result = await abandoned.abandoned_window(_Shop(count=count, value=value, query=query))
        assert result.status == "FAIL", query
        assert not _check(result, "the seven-day window reached Shopify as its date filter").ok, query


# ====================================================================== X2-01: tv_flow.run's verdict


STAND_IN = textwrap.dedent('''
    import json, sys
    report, status = sys.argv[1], int(sys.argv[2])
    if report:
        print(json.dumps({"note": "a line before the report"}))
        print(report)
    sys.exit(status)
''')


def _results(modes: dict[str, tuple[str, ...]]) -> list[dict]:
    return [{"mode": mode, "step": step, "replace": True, "ready_ms": 900, "limit_ms": 2500}
            for mode, steps in modes.items() for step in steps]


async def _drive(tmp_path, report: dict | None, status: int, modes: str = "full,weak,calm") -> dict:
    script = tmp_path / "stand_in_driver.py"
    script.write_text(STAND_IN, encoding="utf-8")
    return await tv_flow.drive([sys.executable, str(script), json.dumps(report) if report else "", str(status)], modes=modes)


WHOLE = {"full": tv_flow.FULL_WALK, "weak": tv_flow.SHORT_WALK, "calm": tv_flow.SHORT_WALK}


async def test_a_driver_that_measured_everything_and_exited_cleanly_is_ok(tmp_path):
    got = await _drive(tmp_path, {"ok": True, "results": _results(WHOLE), "errors": []}, 0)
    assert got["ok"] is True, got.get("errors")
    assert not got["errors"]


async def test_a_driver_that_exits_non_zero_is_not_ok_whatever_it_printed(tmp_path):
    got = await _drive(tmp_path, {"ok": True, "results": _results(WHOLE), "errors": []}, 3)
    assert got["ok"] is False
    assert "the driver exited with status 3" in got["errors"]


async def test_a_mode_left_out_of_the_results_is_not_ok(tmp_path):
    partial = {mode: steps for mode, steps in WHOLE.items() if mode != "calm"}
    got = await _drive(tmp_path, {"ok": True, "results": _results(partial), "errors": []}, 0)
    assert got["ok"] is False
    assert "calm: no change was measured" in got["errors"]


async def test_a_change_left_out_of_a_mode_is_not_ok(tmp_path):
    short = {**WHOLE, "weak": tuple(s for s in tv_flow.SHORT_WALK if s != "off")}
    got = await _drive(tmp_path, {"ok": True, "results": _results(short), "errors": []}, 0)
    assert got["ok"] is False
    assert "weak: no result for off" in got["errors"]


async def test_a_driver_that_printed_no_report_is_not_ok(tmp_path):
    got = await _drive(tmp_path, None, 1, modes="full")
    assert got["ok"] is False
    assert "the driver exited with status 1" in got["errors"]


@needs_node
def test_the_walks_python_checks_are_the_walks_the_script_runs():
    shown = subprocess.run(
        [NODE, "-e", "const w = require('./scripts/browser/tv_flow.js').WALK;"
                     "process.stdout.write(JSON.stringify({full: w.full.map((s) => s.name), short: w.short.map((s) => s.name)}))"],
        capture_output=True, text=True, timeout=60, cwd=ROOT,
    )
    assert shown.returncode == 0, shown.stderr[-2000:]
    walks = json.loads(shown.stdout)
    assert tuple(walks["full"]) == tv_flow.FULL_WALK
    assert tuple(walks["short"]) == tv_flow.SHORT_WALK


# ====================================================================== SC1-01: tv_flow.js's verdict


@needs_node
def test_the_screen_flows_verdict_under_node():
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "followups-tv-flow.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


# ====================================================================== I-05: only what runs is cited


DISPATCH = "from app.tools.dispatch import dispatch\n"


def _cites(source: str) -> bool:
    return tool_matrix.read_test(textwrap.dedent(source)).calls_tool("probe_tool", "app.tools.probes", "probe_tool")


def test_a_dispatch_in_a_helper_is_a_citation_only_when_a_test_calls_the_helper():
    assert not _cites(DISPATCH + 'TOOL = "probe_tool"\nasync def go():\n    await dispatch(TOOL, {})\n')
    assert not _cites(DISPATCH + 'async def go():\n    await dispatch("probe_tool", {})\n'
                                 'async def via():\n    await go()\ndef test_unrelated():\n    assert True\n')
    assert not _cites('from app.tools.probes import probe_tool\nasync def go():\n    await probe_tool()\n')
    assert _cites(DISPATCH + 'TOOL = "probe_tool"\nasync def go():\n    await dispatch(TOOL, {})\n'
                             'async def test_it():\n    await go()\n')
    assert _cites(DISPATCH + 'async def go():\n    await dispatch("probe_tool", {})\n'
                             'async def via():\n    await go()\nasync def test_it():\n    await via()\n')


def test_a_dispatch_in_a_nested_helper_the_test_never_calls_is_not_a_citation():
    """A function a test defines runs only when the test calls it or hands it on (the
    2026-10-01 repair, F-01): defining `go` inside the test, and nothing more, runs no tool."""
    assert not _cites(DISPATCH + 'async def test_it():\n    async def go():\n        await dispatch("probe_tool", {})\n')
    assert not _cites(DISPATCH + 'async def test_it():\n    async def go():\n        await dispatch("probe_tool", {})\n'
                                 '    async def via():\n        await go()\n')
    assert not _cites(DISPATCH + 'async def helper():\n    async def go():\n        await dispatch("probe_tool", {})\n'
                                 'async def test_it():\n    await helper()\n')
    assert _cites(DISPATCH + 'async def test_it():\n    async def go():\n        await dispatch("probe_tool", {})\n'
                             '    await go()\n')
    assert _cites(DISPATCH + 'import anyio\ndef test_it():\n    async def go():\n        await dispatch("probe_tool", {})\n'
                             '    anyio.run(go)\n')
    assert _cites(DISPATCH + 'async def test_it():\n    async def go():\n        await dispatch("probe_tool", {})\n'
                             '    async def via():\n        await go()\n    await via()\n')


def test_a_helper_only_the_files_top_level_code_calls_is_not_a_citation():
    """The file's top-level code is not a test: a helper reached from it alone credits nothing,
    whether it dispatches itself or forwards the tool a call names (the 2026-10-01 repair, F-02)."""
    assert not _cites(DISPATCH + 'import asyncio\nasync def go():\n    await dispatch("probe_tool", {})\n'
                                 'asyncio.run(go())\ndef test_unrelated():\n    assert True\n')
    assert not _cites(DISPATCH + 'async def go():\n    await dispatch("probe_tool", {})\n'
                                 'async def via():\n    await go()\nvia()\ndef test_unrelated():\n    assert True\n')
    assert not _cites(DISPATCH + 'async def stage(session, tool):\n    await dispatch(tool, {}, session=session)\n'
                                 'stage(s, "probe_tool")\ndef test_unrelated():\n    assert True\n')
    assert _cites(DISPATCH + 'async def stage(session, tool):\n    await dispatch(tool, {}, session=session)\n'
                             'async def test_it(s):\n    await stage(s, "probe_tool")\n')


MODEL_DOUBLE = DISPATCH + (
    'import pytest\nclass Model:\n    async def turn(self, session_id, text):\n'
    '        await dispatch("probe_tool", {})\n')


def test_a_model_double_a_test_makes_runs_its_methods_and_one_nobody_makes_does_not():
    """The application calls a double's `turn` once a test has put it in the runtime
    (tests/test_turn_authority_path.py's Witness): made by a fixture a test asks for, its dispatch
    runs. A double nothing makes runs nothing."""
    assert _cites(MODEL_DOUBLE + '@pytest.fixture\ndef model():\n    return Model()\n'
                                 'async def test_it(model):\n    pass\n')
    assert not _cites(MODEL_DOUBLE + 'async def test_it():\n    pass\n')


NESTED_DOUBLE = (
    '    class Fake:\n'
    '        async def turn(self):\n'
    '            await dispatch("probe_tool", {})\n'
)


def test_a_class_nested_in_a_test_runs_its_methods_only_once_the_test_uses_it():
    """A double a test defines and never names again runs nothing, as a nested function does
    (the landing review of 1 October 2026: such a class was credited for being defined). Made,
    handed on or returned, its methods run."""
    assert not _cites(DISPATCH + 'async def test_it():\n' + NESTED_DOUBLE + '    assert True\n')
    assert not _cites(DISPATCH + 'import pytest\n@pytest.fixture\ndef model():\n' + NESTED_DOUBLE
                      + '    return None\nasync def test_it(model):\n    pass\n')
    assert _cites(DISPATCH + 'async def test_it():\n' + NESTED_DOUBLE + '    await Fake().turn()\n')
    assert _cites(DISPATCH + 'async def test_it(runtime):\n' + NESTED_DOUBLE + '    runtime.provider = Fake\n')
    assert _cites(DISPATCH + 'import pytest\n@pytest.fixture\ndef model():\n' + NESTED_DOUBLE
                  + '    return Fake()\nasync def test_it(model):\n    pass\n')


def test_a_lambda_kept_under_a_name_runs_only_once_the_name_is_used():
    """`f = lambda: dispatch(...)` and nothing more runs no tool (the landing review of
    1 October 2026). Called, or handed on by its name or written straight into a call, it does."""
    assert not _cites(DISPATCH + 'def test_it():\n    f = lambda: dispatch("probe_tool", {})\n    assert True\n')
    assert not _cites(DISPATCH + 'from typing import Callable\n'
                                 'def test_it():\n    f: Callable = lambda: dispatch("probe_tool", {})\n')
    assert _cites(DISPATCH + 'def test_it():\n    f = lambda: dispatch("probe_tool", {})\n    f()\n')
    assert _cites(DISPATCH + 'def test_it(monkeypatch, provider):\n    f = lambda: dispatch("probe_tool", {})\n'
                             '    monkeypatch.setattr(provider, "step", f)\n')
    assert _cites(DISPATCH + 'def test_it(loop):\n    loop.run(lambda: dispatch("probe_tool", {}))\n')


# ====================================================================== H-06: data is not coverage


def test_a_tool_name_a_scenario_holds_only_as_data_is_not_handed_on():
    strings = tool_matrix.scenario_strings(textwrap.dedent('''
        UNUSED = "probe_unused_constant"
        LABELS = {"shopify_order_cancel": "Cancel the order"}
        PLANNED = [("probe_planned_list", {})]

        def _scripted():
            return ("probe_from_helper", {"tool": "probe_in_helper_arguments"})

        async def scenario(h):
            note = "probe_message"
            kept = {"probe_local_dict": 1}
            later = ["probe_local_list"]
            r.checks.append(check("described", True, "probe_detail"))
            c = await h.ask("say probe_said", ("probe_scripted", {"tool": "probe_argument"}), _scripted(),
                            reply="probe_reply", scenario="probe_keyword")
            print(LABELS, PLANNED, kept, later, note, c)
            await h.touch("probe.stage", session_id="s")
    '''))["scenario"]
    assert {"probe_scripted", "probe_from_helper", "probe.stage"} <= strings
    for data_only in ("probe_unused_constant", "shopify_order_cancel", "Cancel the order", "probe_planned_list",
                      "probe_message", "probe_local_dict", "probe_local_list", "probe_detail", "probe_said",
                      "probe_argument", "probe_in_helper_arguments", "probe_reply", "probe_keyword"):
        assert data_only not in strings, data_only
    # And a name held in a constant, a local name or a helper's parameter that IS handed on
    # still counts.
    strings = tool_matrix.scenario_strings(textwrap.dedent('''
        WRITE = "probe_write"

        async def _tap(h, command):
            return await h.touch(command, session_id="s")

        async def scenario(h):
            tools = ("probe_local_call", {})
            await h.ask("say it", (WRITE, {}), tools)
            await _tap(h, "probe.stage")
            await dispatch("probe_dispatched", {})
    '''))["scenario"]
    assert {"probe_write", "probe_local_call", "probe.stage", "probe_dispatched"} <= strings


# ====================================================================== F-A2-FIXTURE: put back


async def test_the_harness_puts_back_everything_its_lifespan_and_build_set():
    from app.clients import instagram
    from app.connections import ledger, passkeys
    from app.main import app
    from app.people import access as staff_access
    from app.people.store import people as people_store
    from app.tools import engineering_tools
    from app.work import tools as work_tools
    from app.work.store import work as work_store

    state_before = dict(app.state._state)
    bound_before = harness_module._tool_bindings()
    engineering_before = (engineering_tools._inbox, engineering_tools._check_python)
    instagram_before = (dict(instagram._CONFIG), dict(instagram._STATE))
    work_runtime_before = list(work_tools._RUNTIME)
    stores_before = (people_store._path, work_store._folder, work_store._archived_on)
    folders_before = (dict(passkeys._CONFIG), dict(ledger._CONFIG), dict(staff_access._CONFIG))
    async with harness_module.harness(admitted=True) as h:
        inside = dict(app.state._state)
        assert inside.get("runtime") is h.runtime
        assert inside["housekeeper"].runtime is h.runtime, "the lifespan's housekeeper holds the harness's runtime"
        # What trunk's build binds since the team and Connections landed (PR #73): the work list's
        # runtime is the harness's own, so leaving it there would be the housekeeper again.
        assert work_tools._RUNTIME[0] is h.runtime, "the work list reads through the harness's runtime"
        assert people_store._path is not None and work_store._folder is not None
        assert passkeys._CONFIG["state_dir"] is not None and staff_access._CONFIG["state_dir"] is not None
    after = dict(app.state._state)
    assert after.keys() == state_before.keys(), sorted(set(after) ^ set(state_before))
    for name, value in state_before.items():
        assert after[name] is value, name
    assert "housekeeper" not in after or after["housekeeper"] is state_before["housekeeper"]
    assert (engineering_tools._inbox, engineering_tools._check_python) == engineering_before
    assert engineering_tools._inbox is engineering_before[0]
    assert (dict(instagram._CONFIG), dict(instagram._STATE)) == instagram_before
    assert len(work_tools._RUNTIME) == len(work_runtime_before)
    assert all(a is b for a, b in zip(work_tools._RUNTIME, work_runtime_before, strict=True)), "the work list's runtime"
    assert (people_store._path, work_store._folder, work_store._archived_on) == stores_before
    assert (dict(passkeys._CONFIG), dict(ledger._CONFIG), dict(staff_access._CONFIG)) == folders_before
    bound_after = harness_module._tool_bindings()
    assert bound_after.keys() == bound_before.keys()
    in_place = {(m, n) for m, names in harness_module._TOOL_CONFIG for n in names}
    for key, value in bound_before.items():
        assert (bound_after[key] == value) if key in in_place else (bound_after[key] is value), key


def _imported_names(tree: ast.AST) -> dict[str, str]:
    """Each name an import binds in this tree -> the dotted path it stands for."""
    names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                names[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                names[alias.asname or alias.name.split(".")[0]] = alias.name if alias.asname else alias.name.split(".")[0]
    return names


def test_every_module_runtime_build_binds_into_is_one_the_harness_puts_back():
    """Every `x.bind…(` and `x.configure(` in `runtime.build`, whatever `x` is called — a tool
    module, a service, a store — names something the harness records and puts back. A binding
    added to `build` later fails here until the harness learns it."""
    from app import runtime

    source = inspect.getsource(runtime.build)
    called = set(re.findall(r"\b([A-Za-z_]\w*)\.(?:bind\w*|configure)\(", source))
    assert called >= {"shopify_tools", "gmail_tools", "gmail_writes", "shopify_writes", "analytics_tools",
                      "engineering_tools", "instagram_tools", "connections_service", "staff_access",
                      "people_store", "work_store", "work_tools"}, called
    imported = _imported_names(ast.parse(inspect.getsource(runtime)))
    unresolved = sorted(name for name in called if name not in imported)
    assert not unresolved, f"bound or configured, but not imported by name: {unresolved}"

    recorded = {module for module, _ in harness_module._TOOL_BINDINGS}
    recorded |= {module for module, _ in harness_module._TOOL_CONFIG}
    recorded |= {f"{module}.{instance}" for module, instance, _ in harness_module._STORE_CONFIG}
    for through, targets in harness_module.CONFIGURED_THROUGH.items():
        assert set(targets) <= {module for module, _ in harness_module._TOOL_CONFIG}, through
        recorded.add(through)
    missing = sorted(f"{name} ({imported[name]})" for name in called if imported[name] not in recorded)
    assert not missing, f"runtime.build binds or configures what the harness does not put back: {missing}"


def test_every_global_a_bind_in_build_sets_is_one_the_harness_records():
    """Within a recorded module, a `bind…` or `configure` that `build` calls and that starts
    setting another global would leave it set after the harness: every name such a function
    declares `global` is recorded."""
    import importlib

    from app import runtime

    imported = _imported_names(ast.parse(inspect.getsource(runtime)))
    calls = set(re.findall(r"\b([A-Za-z_]\w*)\.(bind\w*|configure)\(", inspect.getsource(runtime.build)))
    recorded = dict(harness_module._TOOL_BINDINGS)
    checked = set()
    for alias, function in sorted(calls):
        module_name = imported.get(alias, "")
        if module_name not in recorded:
            continue
        tree = ast.parse(inspect.getsource(importlib.import_module(module_name)))
        fn = next(n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == function)
        declared = {name for node in ast.walk(fn) if isinstance(node, ast.Global) for name in node.names}
        assert declared <= set(recorded[module_name]), (
            f"{module_name}.{function} sets {sorted(declared - set(recorded[module_name]))}, not put back")
        checked.add(module_name)
    assert checked == set(recorded), sorted(set(recorded) - checked)


# ====================================================================== DOC2-02: what "read" means


def test_the_matrix_says_read_is_the_write_boundarys_word_and_names_the_screen_tools():
    text = tool_matrix.markdown()
    assert "Reads never mutate" not in text
    rule = next(line for line in text.split("\n## The rules the audit itself keeps", 1)[1].split("\n- ")
                if "**Read** in this matrix" in line)
    rule = " ".join(rule.split())
    assert "not a promise that nothing changes" in rule
    assert "no `WriteSpec` and no `BatchSpec`" in rule
    assert "No read changes the shop or the inbox" in rule
    for tool in ("screen_show", "screen_off", "screen_play", "screen_video", "screen_pair", "close_screen"):
        assert f"`{tool}`" in rule, tool
