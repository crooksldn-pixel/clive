"""The tool and intent-family audit (§32).

Every registered tool and every routable intent family gets a row, and every column is read
from the thing that decides it rather than from a claim. The two rules this file exists to
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


def test_every_routable_intent_family_has_a_row():
    from app.fastpath.intent import all_families

    tool_matrix.load()
    rows = {row["name"]: row for row in tool_matrix.families()}
    assert set(rows) == {f.name for f in all_families()}


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


def test_a_test_that_calls_a_tool_tests_it():
    cases = {
        "by name": 'registry.get("probe_tool")',
        "through a constant": 'TOOL = "probe_tool"\nasync def go():\n    await dispatch(TOOL, {})',
        "through a loop": 'for name in ("probe_tool", "other"):\n    classify(name)',
        "through a list it iterates": 'NAMES = ["probe_tool"]\nfor n in NAMES:\n    registry.get(n)',
        "in a tool-call fixture": 'present([{"name": "probe_tool", "args": {}}])',
        "through an app constant": 'from app.tools import probes\nWRITE = probes.WRITE_TOOL\n'
                                   'dispatch(WRITE, {})',
        "its handler, imported": 'from app.tools.probes import probe_tool\nprobe_tool(query="x")',
        "its handler, by module": 'from app.tools import probes\nprobes.probe_tool()',
        "its handler, aliased": 'import app.tools.probes as p\np.probe_tool()',
    }
    for case, body in cases.items():
        code = _reads(body, {("app.tools.probes", "WRITE_TOOL"): PROBE})
        assert code.calls_tool(PROBE, "app.tools.probes", PROBE), case
    parametrized = _reads('''
        import pytest

        @pytest.mark.parametrize("name, limit", [("probe_tool", 1), ("other", 2)])
        def test_it(name, limit):
            registry.get(name)
    ''')
    assert parametrized.calls_tool(PROBE, "app.tools.probes", PROBE)
    assert not _reads("this is not python (").calls_tool(PROBE, "m", PROBE)


def test_a_family_counts_only_when_test_code_names_it():
    assert _reads('assert route("where is my order") == "probe_family"').names("probe_family")
    assert _reads('assert "intent_family:probe_family" in keys').names("probe_family")
    mentioned = _reads('''
        """probe_family, in a docstring."""
        # probe_family, in a comment
        FAMILY = "probe_" + "family_not"
    ''')
    assert not mentioned.names("probe_family")


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
