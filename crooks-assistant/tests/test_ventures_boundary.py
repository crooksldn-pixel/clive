"""The venture engine's authority boundary, proved from its source.

The package is arithmetic: standard library and its own modules only, no network, no process,
no file writes, no dynamic code. Only the command line reads a file, the one it is handed. And
nothing in CLIVE can reach it yet: no venture tool is in the gate's list, so exposing it to the
model is a deliberate owner change to a protected file (VENTURE_ENGINE_V1.md)."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import app.ventures
from app.tools import gate

PACKAGE = Path(app.ventures.__file__).parent
FORBIDDEN_MODULES = {"subprocess", "socket", "http", "urllib", "ssl", "httpx", "requests", "asyncio",
                     "os", "shutil", "tempfile", "pickle", "importlib", "runpy", "ctypes",
                     "multiprocessing", "threading", "sqlite3", "claude_agent_sdk"}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "open", "breakpoint", "input"}
FORBIDDEN_METHODS = {"system", "popen", "write", "write_text", "write_bytes", "unlink", "remove",
                     "rename", "replace_file", "rmdir", "mkdir", "makedirs", "touch", "chmod",
                     "symlink_to", "import_module", "urlopen", "request", "send", "connect"}


def _walk(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules, calls, methods = set(), set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            calls.add(node.func.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            methods.add(node.func.attr)
    return modules, calls, methods


def test_the_package_is_standard_library_and_itself_only():
    files = sorted(PACKAGE.glob("*.py"))
    assert len(files) >= 9
    for path in files:
        modules, calls, methods = _walk(path)
        roots = {module.split(".")[0] for module in modules}
        assert roots <= set(sys.stdlib_module_names) | {"__future__", "app"}, path.name
        assert all(m == "app.ventures" or m.startswith("app.ventures.") for m in modules if m.split(".")[0] == "app"), path.name
        assert not {m.split(".")[0] for m in modules} & FORBIDDEN_MODULES, path.name
        assert not calls & FORBIDDEN_CALLS, path.name
        assert not methods & FORBIDDEN_METHODS, path.name


def test_only_the_command_line_reads_a_file():
    for path in sorted(PACKAGE.glob("*.py")):
        _, _, methods = _walk(path)
        reads = methods & {"read_text", "read_bytes", "open"}
        assert not reads or path.name == "__main__.py", path.name


def test_no_venture_tool_is_reachable_by_the_model():
    assert not [name for name in gate._KNOWN_TOOLS if "venture" in name]


def test_nothing_else_in_clive_imports_the_package():
    app_root = PACKAGE.parent
    importers = []
    for path in sorted(app_root.rglob("*.py")):
        if PACKAGE in path.parents:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module] + [f"{node.module}.{alias.name}" for alias in node.names]
            else:
                continue
            if any(name == "app.ventures" or name.startswith("app.ventures.") for name in names):
                importers.append(str(path.relative_to(app_root)))
    assert len(list(app_root.rglob("*.py"))) > 50
    assert importers == []
