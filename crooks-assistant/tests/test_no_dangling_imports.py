"""Nothing live still reaches for a module round 9 deleted.

The 2026-09-28 deploy review, round 9, E-05: the fast lane went (`app/fastpath/`), and with it
three capabilities and six families. Package discovery (`app.families.load_all`) swallows an
import error by design — a broken discount module must not cost the shop its order editing —
which is exactly why a dangling reference would not show at boot: it would show as a family
quietly missing, or as a lazy import inside a function failing the first time an owner's
request reached it. Round 9's reviewer could not see the whole repository, so could not say.

These say it, SHA-exact, every run:

* every module under `app/` imports — the observability modules and the turn route included;
* every import statement in the repository's own code — at the top of a file or inside a
  function, in `app/`, `experience/`, `scripts/`, `tests/` and `bench/` — names a module that
  exists, and every name it imports from one of this repository's modules is there;
* no dotted string names a deleted module (a patch target, an `import_module` argument);
* and boot loads every family, with none left out by a failed import.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
OURS = ("app", "experience", "scripts", "tests", "config")
SCANNED = ("app", "experience", "scripts", "tests", "bench")

# What round 9 deleted (git diff 4411adde^..a7cd2be7, status D), as module names.
DELETED = (
    "app.fastpath",
    "app.capabilities.ask", "app.capabilities.screen", "app.capabilities.ui_intent",
    "app.families.navigation_extras", "app.families.order_email", "app.families.owner_feedback",
    "app.families.query_language", "app.families.self_knowledge", "app.families.ui_intent",
    "app.speech.normalise",
    "experience.scenario_packs.navigation_extras", "experience.scenario_packs.query_language",
    "scripts.bench_lanes",
    # And what the owner's rulings of 8 October retired (DEC-071): the old Easyship code
    # (ruling 24), the Mac runtime (38), the local Whisper client (39) and the CROOKS Pad (40).
    # scripts.control went with the Mac runtime too; it is left off this list because
    # tests/test_update.py greps CROOKS OS for that name, to hold that nothing calls it.
    "app.shipping", "app.families.shipping",
    "app.clients.whisper", "scripts.whisper_server", "scripts.bench_whisper",
    "scripts.install_launchd", "tests.fake_launchd",
    "app.observability.pad", "app.routes.pad",
)
_DOTTED = re.compile(r"^(?:app|experience|scripts)(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")


def _files() -> list[Path]:
    out: list[Path] = []
    for top in SCANNED:
        base = ROOT / top
        if base.is_dir():
            out.extend(p for p in sorted(base.rglob("*.py")) if "__pycache__" not in p.parts)
    return out


def _package_of(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts[:-1])


def _imports(path: Path) -> list[tuple[int, str, tuple[str, ...]]]:
    """(line, module, names) for every import in the file that reaches one of OUR modules."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in OURS:
                    found.append((node.lineno, alias.name, ()))
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                package = _package_of(path).split(".")
                base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
                module = ".".join([*base, node.module] if node.module else base)
            else:
                module = node.module or ""
            if module.split(".")[0] in OURS:
                found.append((node.lineno, module, tuple(a.name for a in node.names if a.name != "*")))
    return found


def _exists(module: str) -> bool:
    """Whether this repository has the module: a file, a package, or a folder of modules.

    Read off the tree rather than asked of the import system, because the import system can
    answer from somewhere else — an editable install of another checkout, or a folder that
    holds nothing but a stale `__pycache__`, resolves as a namespace package and would make a
    deleted module look present."""
    path = ROOT.joinpath(*module.split("."))
    return path.with_suffix(".py").is_file() or (path.is_dir() and any(path.glob("*.py")))


def test_every_module_under_app_imports():
    failed: list[str] = []
    import app

    for info in pkgutil.walk_packages(app.__path__, prefix="app."):
        try:
            importlib.import_module(info.name)
        except Exception as exc:  # noqa: BLE001 — every failure is reported, not the first
            failed.append(f"{info.name}: {type(exc).__name__}: {exc}")
    assert not failed, "\n".join(failed)
    for named in ("app.observability.visible", "app.observability.report", "app.routes.turn", "app.main"):
        assert importlib.import_module(named) is not None


def test_every_import_of_our_own_code_resolves_to_something_that_exists():
    """Top-level and lazy alike: an import inside a function is the one that fails in front of
    the owner, on the first request that reaches it, rather than at boot."""
    missing: list[str] = []
    for path in _files():
        where = path.relative_to(ROOT)
        for line, module, names in _imports(path):
            if not _exists(module):
                missing.append(f"{where}:{line}: no module {module}")
                continue
            loaded = None
            for name in names:
                if _exists(f"{module}.{name}"):
                    continue
                if loaded is None:
                    loaded = importlib.import_module(module)
                if not hasattr(loaded, name):
                    missing.append(f"{where}:{line}: {module} has no {name}")
    assert not missing, "\n".join(missing)


def test_no_dotted_name_in_the_code_points_at_a_deleted_module():
    """A patch target or an `import_module` argument is a string, and an AST walk of imports
    does not see it. Prose that mentions a deleted file for its history has spaces in it and is
    not a dotted name."""
    found: list[str] = []
    for path in _files():
        if path == Path(__file__):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and _DOTTED.match(node.value):
                if any(node.value == gone or node.value.startswith(gone + ".") for gone in DELETED):
                    found.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.value}")
    assert not found, "\n".join(found)


@pytest.mark.parametrize("gone", DELETED)
def test_a_deleted_module_is_really_gone(gone):
    """So that the list above cannot go stale in the other direction: a module brought back
    would make these references live again, and that has to be a decision someone makes here."""
    assert not _exists(gone), f"{gone} exists again; take it off DELETED if it is meant to"


def test_boot_loads_every_family_and_none_is_lost_to_an_import_error():
    from app import families

    expected = sorted(m.name for m in pkgutil.iter_modules(families.__path__) if not m.name.startswith("_"))
    assert sorted(families.load_all()) == expected
    for gone in ("navigation_extras", "order_email", "owner_feedback", "query_language", "self_knowledge", "ui_intent"):
        assert gone not in expected
