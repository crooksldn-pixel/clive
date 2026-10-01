"""The tool audit (§32).

Every registered tool gets a row, and every column is read from the thing that decides it
rather than from a claim. (There are no intent families any more: every sentence is a model
turn since 28 September 2026.) The two rules this file exists to
keep:

* a tool is not "tested" because a test imports it or mentions it — DIRECTLY TESTED means a
  test's code actually calls that tool: passes its name to a call, or calls its handler;
* the checked-in document is generated, so it cannot drift from the registries.
"""

from __future__ import annotations

import pathlib
import textwrap

from experience import tool_matrix

DOC = pathlib.Path(__file__).resolve().parents[1] / "docs" / "phase4" / "TOOL_MATRIX.md"


def test_every_registered_tool_has_a_row():
    from app.tools import registry

    tool_matrix.load()
    rows = {row["name"]: row for row in tool_matrix.tools()}
    assert set(rows) == set(registry.names())
    for row in rows.values():
        assert row["registered"] is True
        for column in tool_matrix.COLUMNS:
            assert column in row, f"{row['name']} has no {column!r}"


def test_a_write_tool_declares_staging_and_verification():
    tool_matrix.load()
    for row in tool_matrix.tools():
        if row["read_write"] == "write":
            assert row["staging"], f"{row['name']} is a write with no staging"
            assert row["verification"], f"{row['name']} is a write with no verification"
        if row["read_write"] == "read":
            assert not row["staging"] and not row["verification"]


def test_no_tool_is_called_tested_because_a_unit_test_imported_it():
    """The column is derived from a test CALLING the tool, and the matrix says which test. A
    tool with no citation is reported as untested, which is honest."""
    tool_matrix.load()
    for row in tool_matrix.tools():
        assert bool(row["directly_tested"]) == bool(row["tested_by"]), row["name"]


# A tool name for the fixtures below, which the registry does not hold.
PROBE = "probe_tool"


def _reads(source: str, constants: dict | None = None) -> tool_matrix.Citations:
    constants = constants or {}
    return tool_matrix.read_test(textwrap.dedent(source), lambda m, n: constants.get((m, n)))


def test_a_test_that_only_mentions_a_tool_does_not_test_it():
    """The reported defect: a test file that merely named a tool — in a comment, a docstring,
    an assertion about names, a count of a registry's names, or a monkeypatch replacing the
    tool — was counted as testing it."""
    only_mentions = _reads(f'''
        """This file is about {PROBE}, and says so in its docstring."""
        import pytest
        from app.tools import gate, probes

        NAMES = ("{PROBE}", "other_tool")

        def test_names(monkeypatch):
            """{PROBE} again."""
            # {PROBE} is mentioned in a comment
            assert "{PROBE}" in NAMES
            assert len(NAMES) == 2 and sorted(NAMES)[1] == "{PROBE}"
            assert len(gate.KNOWN) > 0
            monkeypatch.setattr(probes, "{PROBE}", lambda: None)
            spec = f"tool:{{NAMES[0]}}"
    ''', {("app.tools.gate", "KNOWN"): frozenset({PROBE})})
    assert not only_mentions.calls_tool(PROBE, "app.tools.probes", PROBE)


DISPATCH = "from app.tools.dispatch import dispatch\nfrom app.tools import registry\n"


def test_a_test_that_runs_a_tool_tests_it():
    """DIRECTLY TESTED is a test RUNNING the tool (the 2026-09-28 deploy review, round 9,
    I-tests5 I-05): handing its name to the dispatcher or to `registry.invoke`, however the name
    gets there, or calling its handler."""
    cases = {
        "dispatched by name": DISPATCH + 'dispatch("probe_tool", {}, session=s, timeout_s=5)',
        "dispatched through a constant": DISPATCH + 'TOOL = "probe_tool"\nasync def test_go():\n    await dispatch(TOOL, {})',
        # A helper credits its dispatch only when a test calls it, directly or through another
        # helper (the round-12 deploy review's follow-up of round 9's I-05); the same helper with
        # nothing calling it is among the negatives below.
        "dispatched in a helper a test calls": DISPATCH + (
            'TOOL = "probe_tool"\nasync def go():\n    await dispatch(TOOL, {})\n'
            'async def via():\n    await go()\nasync def test_it():\n    await via()'),
        "dispatched in a helper a test's fixture calls": DISPATCH + (
            'import pytest\nTOOL = "probe_tool"\nasync def go():\n    await dispatch(TOOL, {})\n'
            '@pytest.fixture\nasync def staged():\n    await go()\nasync def test_it(staged):\n    pass'),
        "dispatched in a test method's own helper": DISPATCH + (
            'class TestIt:\n    async def _go(self):\n        await dispatch("probe_tool", {})\n'
            '    async def test_it(self):\n        await self._go()'),
        "dispatched through a loop": DISPATCH + 'for name in ("probe_tool", "other"):\n    dispatch(name, {})',
        "dispatched through a list it iterates": DISPATCH + 'NAMES = ["probe_tool"]\nfor n in NAMES:\n    dispatch(n, {})',
        "dispatched through an app constant": DISPATCH + 'from app.tools import probes\nWRITE = probes.WRITE_TOOL\n'
                                              'dispatch(WRITE, {})',
        "dispatched through the module": 'import app.tools.dispatch as dispatch_module\n'
                                         'dispatch_module.dispatch("probe_tool", {})',
        "dispatched by keyword": DISPATCH + 'dispatch(tool_name="probe_tool", args={})',
        "dispatched through the test's own helper": DISPATCH + (
            'async def stage(session, tool, **args):\n    return await dispatch(tool, args, session=session)\n'
            'async def run(session, which):\n    return await stage(session, which)\n'
            'stage(s, "probe_tool", x=1)\nrun(s, "probe_tool")'),
        "invoked by the registry": DISPATCH + 'registry.invoke("probe_tool", {}, timeout_s=1)',
        "through the provider's callback": 'provider._dispatch("probe_tool", {}, holder=h)',
        "its handler, imported": 'from app.tools.probes import probe_tool\nprobe_tool(query="x")',
        "its handler, by module": 'from app.tools import probes\nprobes.probe_tool()',
        "its handler, aliased": 'import app.tools.probes as p\np.probe_tool()',
    }
    for case, body in cases.items():
        code = _reads(body, {("app.tools.probes", "WRITE_TOOL"): PROBE})
        assert code.calls_tool(PROBE, "app.tools.probes", PROBE), case
    parametrized = _reads(DISPATCH + '''
import pytest

@pytest.mark.parametrize("name, limit", [("probe_tool", 1), ("other", 2)])
async def test_it(name, limit):
    await dispatch(name, {})
''')
    assert parametrized.calls_tool(PROBE, "app.tools.probes", PROBE)
    assert not _reads("this is not python (").calls_tool(PROBE, "m", PROBE)


def test_looking_a_tool_up_asking_the_gate_or_drawing_a_made_up_call_does_not_test_it():
    """The round-9 I-05 negatives: none of these runs the tool's handler, so none is a test of
    it — a registry lookup, the gate's classification, a synthetic tool call handed to the
    presenters, a tool's name among another dispatched tool's ARGUMENTS, a helper that only looks
    the tool up, a function of the same name as the dispatcher that is not it, and the provider's
    callback in a test that replaced the dispatcher behind it (tests/test_provider.py's
    cancelled-turn tests, which test the callback's refusals and run no tool)."""
    cases = {
        "a registry lookup": DISPATCH + 'registry.get("probe_tool")',
        "a registry lookup in a loop": DISPATCH + 'NAMES = ["probe_tool"]\nfor n in NAMES:\n    registry.get(n).write',
        "the gate's classification": DISPATCH + 'from app.tools.gate import classify\n'
                                     'for name in ("probe_tool", "other"):\n    classify(name, {})',
        "a synthetic tool call, presented": DISPATCH + 'from app.presentation import present\n'
                                            'present([{"name": "probe_tool", "args": {}}])\n'
                                            'present([ToolCall(name="probe_tool", args={}, ok=True)])',
        "the name among another tool's arguments": DISPATCH + 'dispatch("other_tool", {"tool": "probe_tool"}, session=s)',
        "a helper that only looks it up": DISPATCH + 'def spec(name):\n    return registry.get(name)\nspec("probe_tool")',
        # Moved here from the positive cases, where it stood as "dispatched through a constant":
        # no test calls `go`, so nothing runs it.
        "a dispatch in a helper no test calls": DISPATCH + 'TOOL = "probe_tool"\nasync def go():\n    await dispatch(TOOL, {})',
        "a dispatch in a helper only another uncalled helper calls": DISPATCH + (
            'async def go():\n    await dispatch("probe_tool", {})\nasync def via():\n    await go()\n'
            'def test_other():\n    assert True'),
        "a dispatch in a fixture no test asks for": DISPATCH + (
            'import pytest\n@pytest.fixture\nasync def staged():\n    await dispatch("probe_tool", {})\n'
            'def test_other():\n    assert True'),
        "a local function called dispatch": 'def dispatch(name, args):\n    return name\ndispatch("probe_tool", {})',
        "a monkeypatch replacing it": 'from app.tools import probes\nmonkeypatch.setattr(probes, "probe_tool", None)',
        "the provider's callback, its dispatcher replaced": (
            'from app.providers import max_agent_sdk\n'
            'async def test_x(monkeypatch):\n    monkeypatch.setattr(max_agent_sdk, "dispatch", stub)\n'
            '    await provider._dispatch("probe_tool", {}, holder=h)'),
        "the provider's callback, its dispatcher replaced by path": (
            'async def test_x(monkeypatch):\n    monkeypatch.setattr("app.providers.max_agent_sdk.dispatch", stub)\n'
            '    await provider._dispatch("probe_tool", {}, holder=h)'),
    }
    for case, body in cases.items():
        code = _reads(body, {("app.tools.probes", "WRITE_TOOL"): PROBE})
        assert not code.calls_tool(PROBE, "app.tools.probes", PROBE), case


def test_the_matrix_does_not_cite_a_test_that_only_looks_tools_up():
    """tests/test_digest_relate.py names the read tool it looks up in the self-model and never
    calls it; the file that does call it is cited."""
    tool_matrix.load()
    rows = {row["name"]: row for row in tool_matrix.tools()}
    relate_test = pathlib.Path(__file__).with_name("test_digest_relate.py").read_text(encoding="utf-8")
    assert 'READ_TOOL = "shopify_find_order"' in relate_test
    row = rows["shopify_find_order"]
    assert "test_digest_relate.py" not in row["tested_by"]
    assert "test_shopify_tools.py" in row["tested_by"]


def test_the_checked_in_document_is_the_generated_one():
    """Generated in a FRESH interpreter, which is how `make tool-matrix` runs it.

    Not in this one. Several tests register a tool of their own and do not take it away
    again, so by the time the suite reaches here the registry holds four that the shipped
    application does not — and a document compared against that is a document that can never
    be made to match. Spawning the generator also proves it works from a cold start, which is
    the only way anybody actually runs it.
    """
    import subprocess
    import sys

    root = DOC.resolve().parents[2]
    generated = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, '.'); from experience import tool_matrix; "
         "sys.stdout.write(tool_matrix.markdown())"],
        cwd=root, capture_output=True, text=True, timeout=180, check=False,
    )
    assert generated.returncode == 0, generated.stderr[-2000:]
    assert DOC.exists(), f"{DOC} has not been written"
    assert DOC.read_text(encoding="utf-8") == generated.stdout, (
        "docs/phase4/TOOL_MATRIX.md is out of date; regenerate it with `make tool-matrix`"
    )


def test_the_audit_never_mutates_anything():
    """Building the matrix reads registries and files. It must not call a handler."""
    from app.tools import registry

    tool_matrix.load()
    before = registry.names()
    tool_matrix.markdown()
    assert registry.names() == before


# ------------------------------------------------ what a golden scenario really reaches (H-06)


def test_a_scenario_counts_only_what_its_code_hands_on():
    """The 2026-09-28 deploy review, round 9, H-06: a tool or operation named anywhere in a
    scenario file — a check's description, an assertion about a card — used to mark the tool
    as exercised, and the row named the FILE. Now only what the code hands on counts: the tool
    a scripted model is told to call, a tool a helper builds that call from, a command a tap
    posts."""
    strings = tool_matrix.scenario_strings(textwrap.dedent('''
        WRITE = "probe_write"

        def _opens(to):
            return ("probe_open", {"to": to})

        async def scenario(h):
            """Mentions probe_docstring in its docstring."""
            c = await h.ask("say it", _opens("a@b.co"), ("probe_scripted", {}))
            t = await h.touch("probe.stage", session_id="s")
            r.checks.append(check("probe_described is on the card", c.data("x").get("op") == "probe_compared"))
            r.checks.append(check("described", "probe_contained" in c.action_ids))
            r.checks.append(check("formatted", True, f"{WRITE} probe_fstring"))
            await h.open_order("1938")
    '''))["scenario"]
    assert {"probe_open", "probe_scripted", "probe.stage", "@open_order"} <= strings
    for claimed in ("probe_docstring", "probe_described", "probe_compared", "probe_contained", "probe_fstring"):
        assert claimed not in strings, claimed
    assert "probe_write" not in strings, "a constant only an f-string reads is not handed on"


def test_a_write_a_scenario_reaches_is_reported_staged_and_the_scenario_is_named():
    from experience.scenarios import BY_NAME

    tool_matrix.load()
    rows = {row["name"]: row for row in tool_matrix.tools()}
    credit = rows["shopify_store_credit_add"]
    assert "store_credit_give" in credit["scenarios"], "the tap on Prepare stages it"
    assert credit["scenario_reach"] == "staged, never applied"
    for row in rows.values():
        assert set(row["scenarios"]) <= set(BY_NAME), f"{row['name']} cites a file, not a scenario"
        if row["read_write"] != "read" and row["scenarios"]:
            assert row["scenario_reach"] == "staged, never applied", row["name"]


def test_every_staging_command_names_the_registered_write_it_prepares():
    from app import commands
    from app.families import load_all
    from app.tools import registry
    from experience.matrix import STAGES

    load_all()
    staging = {name for name in commands.REGISTRY if name.endswith(".stage") or name == "draft.send_instead"}
    assert staging == set(STAGES), staging ^ set(STAGES)
    for command, tools in STAGES.items():
        for name in tools:
            spec = registry.get(name)
            assert spec.write is not None, f"{command} names {name}, which is not a write"


def test_posting_a_staging_command_is_not_evidence_that_its_write_was_staged():
    """H-06's second half: a write is credited only where the scenario really prepares it. The
    stale-picker and cancelled-order scenarios post `order_edit.stage` and are refused by
    design; the composer's Save draft prepares a draft of a NEW email, not a reply or a send.
    Before round 10 each of those was reported as staging every write its command could
    prepare. `tests/test_experience.py` holds every credit to a real run."""
    from experience.matrix import STAGES, TAP_STAGED

    tool_matrix.load()
    rows = {row["name"]: row for row in tool_matrix.tools()}
    add = set(rows["shopify_order_add_item"]["scenarios"])
    assert "order_add_item_picker" in add
    assert not add & {"order_add_item_stale_picker", "order_add_item_cancelled"}, add
    for reply in ("gmail_draft_reply", "gmail_send_reply"):
        assert "compose_stage" not in rows[reply]["scenarios"], reply
    assert "compose_stage" not in rows["gmail_send_new"]["scenarios"]
    # A declaration can only name a write some staging command can prepare.
    can = {tool for tools in STAGES.values() for tool in tools}
    for scenario, tools in TAP_STAGED.items():
        assert set(tools) <= can, (scenario, set(tools) - can)
