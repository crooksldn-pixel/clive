"""The Knowledge Digester's code adapter: a source repository read into Units — Python with ast,
JavaScript and TypeScript by pattern, manifests as data — without importing, installing or
running any of it; with exact locations, the same Units every time, every read bounded, and
what it cannot read said in an 'unparsed' Unit rather than raised."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from app.digest import Artifact, Source, Unit, content_digest
from app.digest.adapters import code as adapter
from app.digest.model import ARTIFACT_KINDS, MAX_BODY, MAX_TITLE

SOURCE = Source(
    origin="https://example.invalid/demo.git",
    origin_kind="git",
    pinned_ref="0123456789abcdef0123456789abcdef01234567",
    licence="MIT",
    taken_at="2026-09-26T10:00:00+00:00",
    content_digest=content_digest(b"a demo repository"),
)
ARTIFACT_ID = SOURCE.artifact_id

# --- the fixture repository: every line number asserted below is a line of one of these ------

PYPROJECT = '''\
[project]
name = "clive-demo"
version = "1.0"
dependencies = [
    "requests>=2.31,<3",
    "rich",
    "tomli>=1.1; python_version < '3.11'",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
demo = "clive_demo.cli:main"
demo-tool = "clive_demo.tool:cli"
'''

SETUP_CFG = '''\
[metadata]
name = clive-demo

[options]
install_requires =
    click>=8.0
    PyYAML==6.0.1

[options.entry_points]
console_scripts =
    demo-legacy = clive_demo.cli:main
'''

REQUIREMENTS = '''\
# runtime pins
httpx==0.27.0  # the client
-r other.txt

uvicorn[standard]>=0.30
this is not a requirement!!
'''

PACKAGE_JSON = json.dumps({
    "name": "@clive/demo-web",
    "version": "1.0.0",
    "main": "web/index.js",
    "bin": {"demo-web": "bin/demo-web.js"},
    "scripts": {"build": "tsc -p .", "test": "vitest run", "postinstall": "touch SCRIPT_RAN"},
    "dependencies": {"express": "^4.19.0"},
    "devDependencies": {"vitest": "~1.6.0"},
}, indent=2) + "\n"

# Each of these would leave a file named EXECUTED beside itself if it were ever run or imported.
SETUP_PY = '''\
__import__("pathlib").Path(__file__).with_name("EXECUTED").write_text("ran")
from setuptools import setup
setup(name="clive-demo")
'''

CORE = '''\
"""Core arithmetic for the demo."""

__all__ = ["add", "Calculator"]


def add(a: int, b: int = 1) -> int:
    """Add two numbers."""
    return a + b


def subtract(a, b):
    """Public, but not exported."""
    return a - b


def _hidden():
    return None


class Calculator:
    """Keeps a running total."""

    def __init__(self, start: int = 0) -> None:
        self.total = start

    def push(self, value: int) -> int:
        """Add a value to the total."""
        self.total += value
        return self.total


__import__("pathlib").Path(__file__).with_name("EXECUTED").write_text("ran")
'''

CLI = '''\
"""The demo command line."""

import argparse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="demo", description="Run the demo.")
    parser.add_argument("--verbose", action="store_true", help="say more")
    commands = parser.add_subparsers(dest="command")
    serve = commands.add_parser("serve", help="serve the demo")
    serve.add_argument("--port", type=int, default=8000)
    return parser


def main(argv=None) -> int:
    """Entry point."""
    build_parser().parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''

TOOL = '''\
import click


@click.group()
def cli():
    """Demo tools."""


@cli.command("greet")
@click.option("--name", default="world")
@click.argument("times")
def greet_person(name, times):
    """Say hello."""
    click.echo(f"hello {name}")
'''

MAIN = '''\
from clive_demo.cli import main

raise SystemExit(main())
'''

INDEX_JS = '''\
// export function commentedOut() {}
/* export function alsoCommented() {} */

/**
 * Add two numbers.
 */
export function add(a, b = 1) {
  return a + b;
}

export const double = (x) => {
  return x * 2;
};

export default class Store {
  constructor() {
    this.items = "{ not a brace }";
  }
}

function internal() {
  return "export function fake() {}";
}

const notAFunction = (1 + 2);
'''

TYPES_TS = '''\
export interface Point {
  x: number;
}

export async function fetchPoint(id: string): Promise<Point> {
  return { x: Number(id) };
}

export declare function declared(a: number): void;

export class Shape {}
'''

MATH_TEST = '''\
import { describe, it, expect } from "vitest";
import { add } from "./index.js";

describe("add", () => {
  it("adds two numbers", () => {
    expect(add(1, 2)).toBe(3);
  });
});
'''

TEST_CORE = '''\
import pytest

from clive_demo.core import Calculator, add


def test_add():
    assert add(1, 2) == 3


class TestCalculator:
    def test_push(self):
        assert Calculator().push(2) == 2


def helper():
    return pytest
'''

REPO = {
    "README.md": "# Demo\n",
    "pyproject.toml": PYPROJECT,
    "setup.cfg": SETUP_CFG,
    "setup.py": SETUP_PY,
    "requirements.txt": REQUIREMENTS,
    "package.json": PACKAGE_JSON,
    "src/clive_demo/__init__.py": '"""The demo package."""\n',
    "src/clive_demo/__main__.py": MAIN,
    "src/clive_demo/_private.py": "def helper():\n    return 1\n",
    "src/clive_demo/cli.py": CLI,
    "src/clive_demo/core.py": CORE,
    "src/clive_demo/tool.py": TOOL,
    "web/index.js": INDEX_JS,
    "web/types.ts": TYPES_TS,
    "web/math.test.js": MATH_TEST,
    "tests/test_core.py": TEST_CORE,
    "node_modules/left-pad/index.js": "export function leftPad() {}\n",
}


def _write(root: Path, files: dict[str, str | bytes]) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return root


def _units(root: Path) -> list[Unit]:
    return adapter.decompose(root, ARTIFACT_ID)


def _titled(units: list[Unit], title: str) -> Unit:
    matches = [unit for unit in units if unit.title == title]
    assert len(matches) == 1, (title, [unit.title for unit in units])
    return matches[0]


def _span(unit: Unit) -> tuple:
    return (unit.location.path, unit.location.line_start, unit.location.line_end)


def _unparsed(units: list[Unit]) -> dict[str, list[Unit]]:
    found: dict[str, list[Unit]] = {}
    for unit in units:
        if "unparsed" in unit.tags:
            found.setdefault(unit.location.path, []).append(unit)
    return found


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    return _write(tmp_path / "repo", REPO)


# --- the contract ------------------------------------------------------------------------------


def test_the_adapter_follows_the_shared_contract():
    assert isinstance(adapter.NAME, str) and adapter.NAME
    assert isinstance(adapter.HANDLES, tuple) and adapter.HANDLES
    assert set(adapter.HANDLES) <= set(ARTIFACT_KINDS)
    assert callable(adapter.decompose)
    # A namespace package: sibling adapters add their own modules beside this one.
    assert not (Path(adapter.__file__).parent / "__init__.py").exists()


def test_units_are_valid_records_that_make_an_artifact(repo):
    units = _units(repo)
    artifact = Artifact(source=SOURCE, kinds=adapter.HANDLES, units=tuple(units))
    assert Artifact.from_dict(json.loads(json.dumps(artifact.to_dict()))) == artifact
    assert all(len(unit.body) <= MAX_BODY and len(unit.title) <= MAX_TITLE for unit in units)
    # The one thing in the fixture this adapter cannot read is the malformed requirement.
    assert set(_unparsed(units)) == {"requirements.txt"}


# --- Python, read with ast ---------------------------------------------------------------------


def test_python_functions_classes_and_modules_become_capabilities_and_patterns(repo):
    units = _units(repo)
    add = _titled(units, "function clive_demo.core.add")
    assert add.kind == "capability"
    assert _span(add) == ("src/clive_demo/core.py", 6, 8)
    assert "def add(a: int" in add.body and "-> int" in add.body
    assert "Add two numbers." in add.body and "__all__" in add.body

    subtract = _titled(units, "function clive_demo.core.subtract")
    assert subtract.kind == "pattern"
    assert _span(subtract) == ("src/clive_demo/core.py", 11, 13)

    calculator = _titled(units, "class clive_demo.core.Calculator")
    assert calculator.kind == "pattern"
    assert _span(calculator) == ("src/clive_demo/core.py", 20, 29)
    assert "Keeps a running total." in calculator.body
    assert "def push(self, value: int) -> int" in calculator.body

    core = _titled(units, "module clive_demo.core")
    assert core.kind == "pattern"
    assert _span(core) == ("src/clive_demo/core.py", 1, 32)
    assert "Core arithmetic for the demo." in core.body

    assert _titled(units, "module clive_demo").kind == "pattern"
    assert not [unit for unit in units if "_hidden" in unit.title]
    assert not [unit for unit in units if unit.location.path == "src/clive_demo/_private.py"]


def test_command_line_entries_are_capabilities(repo):
    units = _units(repo)
    cli = _titled(units, "module clive_demo.cli")
    assert cli.kind == "capability" and "__main__" in cli.body

    main = _titled(units, "function clive_demo.cli.main")
    assert main.kind == "capability" and "cli" in main.tags
    assert _span(main) == ("src/clive_demo/cli.py", 15, 18)
    assert "console script demo, demo-legacy" in main.body
    assert "__main__ block" in main.body

    parser = _titled(units, "command-line parser demo")
    assert parser.kind == "capability"
    assert _span(parser) == ("src/clive_demo/cli.py", 7, 8)
    assert "Run the demo." in parser.body and "--verbose: say more" in parser.body

    serve = _titled(units, "command-line subcommand serve")
    assert serve.kind == "capability"
    assert _span(serve) == ("src/clive_demo/cli.py", 10, 11)
    assert "--port" in serve.body and "serve the demo" in serve.body

    group = _titled(units, "command cli")
    assert group.kind == "capability" and "click" in group.tags
    assert _span(group) == ("src/clive_demo/tool.py", 4, 6)
    assert "console script demo-tool" in group.body

    greet = _titled(units, "command greet")
    assert greet.kind == "capability"
    assert _span(greet) == ("src/clive_demo/tool.py", 9, 14)
    assert "--name" in greet.body and "times" in greet.body and "Say hello." in greet.body

    assert _titled(units, "module clive_demo.__main__").kind == "capability"


def test_console_scripts_from_pyproject_and_setup_cfg(repo):
    units = _units(repo)
    demo = _titled(units, "console script demo")
    assert demo.kind == "capability" and "clive_demo.cli:main" in demo.body
    assert _span(demo) == ("pyproject.toml", 14, 14)
    assert _span(_titled(units, "console script demo-tool")) == ("pyproject.toml", 15, 15)
    legacy = _titled(units, "console script demo-legacy")
    assert legacy.kind == "capability" and _span(legacy) == ("setup.cfg", 11, 11)


def test_python_test_files_become_checks_naming_what_they_test(repo):
    units = _units(repo)
    checks = _titled(units, "tests for core")
    assert checks.kind == "check" and checks.location.path == "tests/test_core.py"
    assert "clive_demo.core (Calculator, add)" in checks.body
    assert "test_add (line 6)" in checks.body
    assert "TestCalculator.test_push (line 11)" in checks.body
    assert "pytest" not in checks.body.split("Tests (")[0].split("exercise:")[1]
    assert [unit.kind for unit in units if unit.location.path == "tests/test_core.py"] == ["check"]


# --- dependencies ------------------------------------------------------------------------------


def test_dependencies_carry_their_version_constraints(repo):
    units = _units(repo)
    requests = _titled(units, "dependency requests")
    assert requests.kind == "dependency" and ">=2.31,<3" in requests.body
    assert _span(requests) == ("pyproject.toml", 5, 5)
    rich = _titled(units, "dependency rich")
    assert "(any version)" in rich.body and _span(rich) == ("pyproject.toml", 6, 6)
    tomli = _titled(units, "dependency tomli")
    assert _span(tomli) == ("pyproject.toml", 7, 7) and "python_version < '3.11'" in tomli.body
    pytest_dependency = _titled(units, "dependency pytest")
    assert _span(pytest_dependency) == ("pyproject.toml", 11, 11)
    assert "extra dev" in pytest_dependency.tags

    assert _span(_titled(units, "dependency click")) == ("setup.cfg", 6, 6)
    pyyaml = _titled(units, "dependency PyYAML")
    assert _span(pyyaml) == ("setup.cfg", 7, 7) and "==6.0.1" in pyyaml.body

    httpx = _titled(units, "dependency httpx")
    assert _span(httpx) == ("requirements.txt", 2, 2) and "==0.27.0" in httpx.body
    uvicorn = _titled(units, "dependency uvicorn")
    assert _span(uvicorn) == ("requirements.txt", 5, 5)
    assert "[standard]" in uvicorn.body and ">=0.30" in uvicorn.body

    express = _titled(units, "dependency express")
    assert _span(express) == ("package.json", 14, 14) and "^4.19.0" in express.body
    vitest = _titled(units, "dependency vitest")
    assert _span(vitest) == ("package.json", 17, 17) and "~1.6.0" in vitest.body
    assert "devDependencies" in vitest.tags


def test_an_unreadable_requirement_line_is_reported_where_it_is(repo):
    bad = _unparsed(_units(repo))["requirements.txt"]
    assert len(bad) == 1
    assert bad[0].kind == "knowledge" and _span(bad[0]) == ("requirements.txt", 6, 6)
    assert "this is not a requirement!!" in bad[0].body


# --- JavaScript and TypeScript, read by pattern ------------------------------------------------


def test_package_json_bins_are_capabilities_and_scripts_are_scripts(repo):
    units = _units(repo)
    web = _titled(units, "command demo-web")
    assert web.kind == "capability" and "bin/demo-web.js" in web.body
    assert _span(web) == ("package.json", 6, 6)
    build = _titled(units, "script build")
    assert build.kind == "script" and "tsc -p ." in build.body
    assert _span(build) == ("package.json", 9, 9)
    assert _span(_titled(units, "script test")) == ("package.json", 10, 10)
    postinstall = _titled(units, "script postinstall")
    assert "touch SCRIPT_RAN" in postinstall.body and "never run" in postinstall.body
    assert _span(postinstall) == ("package.json", 11, 11)


def test_javascript_exports_are_read_and_comments_and_strings_are_not_code(repo):
    units = _units(repo)
    add = _titled(units, "function add (web/index.js)")
    assert add.kind == "capability" and _span(add) == ("web/index.js", 7, 9)
    assert "export function add(a, b = 1)" in add.body and "Add two numbers." in add.body
    double = _titled(units, "function double (web/index.js)")
    assert double.kind == "capability" and _span(double) == ("web/index.js", 11, 13)
    store = _titled(units, "class Store (web/index.js)")
    assert store.kind == "pattern" and _span(store) == ("web/index.js", 15, 19)
    assert "default export" in store.body
    # Commented-out exports, an export inside a string and unexported code are not Units.
    assert {unit.title for unit in units if unit.location.path == "web/index.js"} == {
        "function add (web/index.js)", "function double (web/index.js)",
        "class Store (web/index.js)",
    }


def test_typescript_exports_are_read(repo):
    units = _units(repo)
    fetch = _titled(units, "function fetchPoint (web/types.ts)")
    assert fetch.kind == "capability" and _span(fetch) == ("web/types.ts", 5, 7)
    assert "Promise<Point>" in fetch.body and "typescript" in fetch.tags
    assert _span(_titled(units, "function declared (web/types.ts)")) == ("web/types.ts", 9, 9)
    shape = _titled(units, "class Shape (web/types.ts)")
    assert shape.kind == "pattern" and _span(shape) == ("web/types.ts", 11, 11)


def test_javascript_test_files_become_checks(repo):
    units = _units(repo)
    checks = _titled(units, "tests for math")
    assert checks.kind == "check" and checks.location.path == "web/math.test.js"
    assert "./index.js" in checks.body
    assert "describe: add (line 4)" in checks.body
    assert "it: adds two numbers (line 5)" in checks.body


def test_vendored_trees_are_not_walked(repo):
    units = _units(repo)
    assert not [unit for unit in units if unit.location.path.startswith("node_modules")]


# --- the repository map ------------------------------------------------------------------------


def test_the_repository_map_comes_first_and_orients_a_reader(repo):
    units = _units(repo)
    first = units[0]
    assert first.kind == "knowledge" and first.title == "repository map"
    assert first.location.path == "." and first.location.line_start is None
    assert [unit for unit in units if unit.title == "repository map"] == [first]
    for expected in (
        "- src/ (6 files)", "- web/ (3 files)", "- tests/ (1 file)", "- package.json",
        "- README.md", "- Python: 8", "- JavaScript: 2", "- TypeScript: 1",
        "demo: console script → clive_demo.cli:main (pyproject.toml)",
        "demo-legacy: console script → clive_demo.cli:main (setup.cfg)",
        "demo-web: bin → bin/demo-web.js (package.json)",
        "src/clive_demo/__main__.py: python -m clive_demo",
        "src/clive_demo/cli.py: runs as a script",
        "- tests/ (1 test file)", "- web/ (1 test file)",
        "- node_modules/ (not walked",
    ):
        assert expected in first.body, expected


# --- read-only, deterministic, bounded, never raising ------------------------------------------


def test_nothing_is_run_imported_installed_or_written(repo):
    before = {path: path.read_bytes() for path in repo.rglob("*") if path.is_file()}
    _units(repo)
    after = {path: path.read_bytes() for path in repo.rglob("*") if path.is_file()}
    assert after == before
    assert not [path for path in repo.rglob("*") if path.name in ("EXECUTED", "SCRIPT_RAN")]
    assert not [name for name in sys.modules if name.split(".")[0] == "clive_demo"]


def test_the_same_tree_gives_the_same_units_wherever_it_is(repo, tmp_path):
    first = [unit.to_dict() for unit in _units(repo)]
    assert [unit.to_dict() for unit in _units(repo)] == first
    elsewhere = shutil.copytree(repo, tmp_path / "somewhere" / "else")
    assert [unit.to_dict() for unit in _units(elsewhere)] == first
    assert len({unit["id"] for unit in first}) == len(first)


def test_malformed_input_is_reported_as_unparsed_not_raised(tmp_path):
    root = _write(tmp_path / "broken", {
        "good.py": "def fine():\n    return 1\n",
        "broken.py": "def broken(:\n    pass\n",
        "latin1.py": b"name = '\xff'\n",
        "nul.py": b"x = 1\x00\n",
        "pyproject.toml": "[project\nname = \n",
        "package.json": "{not json",
        "list/package.json": "[1, 2]\n",
        "shapes/package.json": json.dumps({"scripts": ["not", "a", "map"], "dependencies": "no"}),
        "setup.cfg": "no section header here\n",
        "weird.js": "export function (((\nexport class {\n",
        "stray.js": "export function f() {}\n}\n",
        "open.ts": "export function f() {}\n/* never closed\nexport function g() {}\n",
        "nameless.js": "export function () {}\nexport class {}\nexport fnction f() {}\n"
                       "export const = 1;\nexport function ok() {}\n",
        "wrongtypes/pyproject.toml": '[project]\ndependencies = "requests"\nscripts = 3\n',
    })
    units = _units(root)
    unparsed = _unparsed(units)
    for path in (
        "broken.py", "latin1.py", "nul.py", "pyproject.toml", "package.json",
        "list/package.json", "shapes/package.json", "setup.cfg", "wrongtypes/pyproject.toml",
        "weird.js", "stray.js", "open.ts", "nameless.js",
    ):
        assert path in unparsed, path
    assert all(
        unit.kind == "knowledge" and unit.body for found in unparsed.values() for unit in found
    )
    assert _span(unparsed["broken.py"][0]) == ("broken.py", 1, 1)
    assert "not valid Python" in unparsed["broken.py"][0].body
    assert "UTF-8" in unparsed["latin1.py"][0].body
    assert len(unparsed["shapes/package.json"]) == 2
    assert len(unparsed["wrongtypes/pyproject.toml"]) == 2
    # JavaScript that does not hold together is said where it breaks, and nothing in it is read.
    assert [_span(unit) for unit in unparsed["weird.js"]] == [("weird.js", 1, 1)]
    assert "( that is never closed" in unparsed["weird.js"][0].body
    assert [_span(unit) for unit in unparsed["stray.js"]] == [("stray.js", 2, 2)]
    assert "} that closes nothing" in unparsed["stray.js"][0].body
    assert [_span(unit) for unit in unparsed["open.ts"]] == [("open.ts", 2, 2)]
    assert "comment that is never closed" in unparsed["open.ts"][0].body
    assert not [
        unit for unit in units
        if unit.location.path in ("weird.js", "stray.js", "open.ts") and "unparsed" not in unit.tags
    ]
    # An export that cannot be made out is skipped and said, and the rest of the file is read.
    assert [_span(unit)[1] for unit in unparsed["nameless.js"]] == [1, 2, 3, 4]
    assert "function with no name" in unparsed["nameless.js"][0].body
    assert "class with no name" in unparsed["nameless.js"][1].body
    assert "export fnction f()" in unparsed["nameless.js"][2].body
    assert "export const = 1;" in unparsed["nameless.js"][3].body
    ok = _titled(units, "function ok (nameless.js)")
    assert ok.kind == "capability" and _span(ok) == ("nameless.js", 5, 5)
    assert [unit for unit in units if unit.location.path == "nameless.js"
            and "unparsed" not in unit.tags] == [ok]
    # What could be read still is.
    assert _titled(units, "function good.fine").kind == "capability"
    assert units[0].title == "repository map"


def test_regular_expressions_and_jsx_text_are_not_taken_for_broken_code(tmp_path):
    root = _write(tmp_path / "valid", {
        "strip.js": 'export const strip = (s) => s.replace(/[({"]/g, "");\n',
        "view.jsx": "export function View({ name }) {\n  return <p>Don't forget {name}</p>;\n}\n",
    })
    units = _units(root)
    assert not _unparsed(units)
    assert _span(_titled(units, "function strip (strip.js)")) == ("strip.js", 1, 1)
    assert _span(_titled(units, "function View (view.jsx)")) == ("view.jsx", 1, 3)


BAD_VALUES = json.dumps({
    "name": "bad-values",
    "bin": {"good-cli": "bin/good.js", "list-cli": ["bin/a.js"], "": "bin/empty.js"},
    "scripts": {"build": "tsc", "object": {"run": "touch SCRIPT_RAN"}, "number": 3},
    "dependencies": {"left-pad": "^1.3.0", "nested": {"version": "1"}, "nothing": None},
}, indent=2) + "\n"


def test_malformed_package_json_entries_are_skipped_and_reported_where_they_are(tmp_path):
    units = _units(_write(tmp_path / "values", {"package.json": BAD_VALUES}))
    good = _titled(units, "command good-cli")
    assert good.kind == "capability" and _span(good) == ("package.json", 4, 4)
    assert _span(_titled(units, "script build")) == ("package.json", 11, 11)
    assert _span(_titled(units, "dependency left-pad")) == ("package.json", 18, 18)
    bad = _unparsed(units)["package.json"]
    assert [_span(unit)[1:] for unit in bad] == [(5, 5), (8, 8), (12, 12), (15, 15), (19, 19), (22, 22)]
    assert all(unit.kind == "knowledge" and "skipped" in unit.body for unit in bad)
    assert "'list-cli' is a list" in bad[0].body
    assert "'object' is an object" in bad[2].body and "'number' is a number" in bad[3].body
    assert "'nested' is an object" in bad[4].body and "'nothing' is null" in bad[5].body
    # Only the well-formed entries became Units: no false commands, scripts or dependencies.
    assert sorted(unit.title for unit in units if "unparsed" not in unit.tags) == [
        "command good-cli", "dependency left-pad", "repository map", "script build",
    ]
    assert "list-cli" not in units[0].body and "bin/empty.js" not in units[0].body


# Namesakes of the sections and entries the adapter reads, nested elsewhere and written first,
# and a section key spelled with an escape: the lines asserted are the top-level entries'.
NESTED_KEYS = '''\
{
  "name": "nested-keys",
  "config": {
    "scripts": {"build": "not this one"},
    "bin": {"tool": "not/this.js"},
    "dependencies": {"lodash": "0.0.1"}
  },
  "workspaces": [{"scripts": {"test": "nor this"}}],
  "b\\u0069n": {
    "tool": "bin/tool.js"
  },
  "scripts": {
    "lint": "eslint .",
    "nested": "echo \\"scripts\\": {}",
    "test": "vitest"
  },
  "dependencies": {
    "react": "^18.0.0",
    "lodash": "^4.17.21"
  }
}
'''


def test_package_json_locations_are_the_top_level_entries_not_nested_namesakes(tmp_path):
    units = _units(_write(tmp_path / "nested", {"package.json": NESTED_KEYS}))
    assert not _unparsed(units)
    tool = _titled(units, "command tool")
    assert _span(tool) == ("package.json", 10, 10) and "bin/tool.js" in tool.body
    assert _span(_titled(units, "script lint")) == ("package.json", 13, 13)
    assert _span(_titled(units, "script nested")) == ("package.json", 14, 14)
    test = _titled(units, "script test")
    assert _span(test) == ("package.json", 15, 15) and "vitest" in test.body
    assert _span(_titled(units, "dependency react")) == ("package.json", 18, 18)
    lodash = _titled(units, "dependency lodash")
    assert _span(lodash) == ("package.json", 19, 19) and "^4.17.21" in lodash.body
    assert not [unit for unit in units if unit.title == "script build"]


def test_a_missing_root_is_reported_not_raised(tmp_path):
    units = _units(tmp_path / "does-not-exist")
    assert units[0].title == "repository map"
    assert "." in _unparsed(units)


def test_an_invalid_artifact_id_is_refused(tmp_path):
    with pytest.raises(ValueError, match="artifact_id"):
        adapter.decompose(tmp_path, "not-an-artifact-id")


def test_symbolic_links_are_not_followed(tmp_path):
    outside = _write(tmp_path / "outside", {"secret.py": "def leaked():\n    return 1\n"})
    root = _write(tmp_path / "linked", {"inside.py": "def kept():\n    return 1\n"})
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
        (root / "file_link.py").symlink_to(outside / "secret.py")
    except OSError:
        pytest.skip("this filesystem cannot make symbolic links")
    units = _units(root)
    assert _titled(units, "function inside.kept")
    assert not [unit for unit in units if "leaked" in unit.title or "leaked" in unit.body]
    assert "- link (symbolic link, not followed)" in units[0].body


def test_a_file_over_the_size_bound_is_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "MAX_FILE_BYTES", 200)
    root = _write(tmp_path / "big", {
        "big.py": "x = 1\n" * 100,
        "small.py": "def ok():\n    return 1\n",
    })
    units = _units(root)
    big = [unit for unit in units if unit.location.path == "big.py"]
    assert len(big) == 1 and "unparsed" in big[0].tags
    assert "larger than 200 bytes" in big[0].body
    assert _titled(units, "function small.ok").kind == "capability"


def test_the_number_of_files_read_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "MAX_FILES", 3)
    files = {f"m{index:02d}.py": f"def f{index}():\n    return {index}\n" for index in range(10)}
    units = _units(_write(tmp_path / "many", files))
    assert {unit.location.path for unit in units if unit.kind == "capability"} == {
        "m00.py", "m01.py", "m02.py",
    }
    assert any("stopped after 3 files" in unit.body for unit in _unparsed(units)["."])


def test_the_number_of_units_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(adapter, "MAX_UNITS", 5)
    source = "".join(f"def f{index}():\n    return {index}\n\n\n" for index in range(20))
    units = _units(_write(tmp_path / "units", {"many.py": source}))
    assert len(units) <= 5 + 2          # the bound, the map and the note that the bound was met
    assert any("stopped at 5 Units" in unit.body for unit in _unparsed(units)["."])


def test_long_names_and_docstrings_are_held_to_the_model_bounds(tmp_path):
    name = "f" * 300
    doc = "word " * (MAX_BODY // 2)
    units = _units(_write(tmp_path / "long", {"long.py": f'def {name}():\n    """{doc}"""\n'}))
    functions = [unit for unit in units if unit.kind == "capability"]
    assert len(functions) == 1
    assert len(functions[0].title) <= MAX_TITLE and len(functions[0].body) <= MAX_BODY
