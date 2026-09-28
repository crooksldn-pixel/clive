"""The tool audit (§32) — derived, never asserted.

The brief's instruction is the whole design of this file: *do not claim a tool works because
unit tests pass.* So every column is read from the thing that decides it, and where a column
cannot be decided it says so rather than being filled in optimistically:

    REGISTERED        the tool is in app/tools/registry.py
    ROUTABLE          something other than the model's free choice reaches it — a tap
                      recipe's read primitives, a semantic command, or a capability family
    DIRECTLY TESTED   a test CALLS this tool: its code — not a comment, not a docstring —
                      passes the tool's name to a call (registry.get, dispatch, classify, the
                      action engine; directly, through a variable or loop variable holding it,
                      or inside a literal argument such as a tool-call fixture), or calls the
                      tool's handler function by name. The citation is printed; a test that
                      only mentions a tool — in a comment, a docstring, an assertion about a
                      list of names, or a monkeypatch that replaces it — does not count, and a
                      tool with no citation is reported untested, which is honest
    AUTH-SCOPE        the Shopify or Gmail scope its capability family declares
    READ-WRITE        read, write or batch, from the spec
    STAGING           a write's WriteSpec is complete: prepare, observe, execute, present
    VERIFICATION      how a write is proven — a predicate, or the default exact re-read
    VISIBLE UI        app/presentation.py names it, so its result becomes a card
    ERROR UI          its failure is drawn as a named service rather than a generic error
    GOLDEN SCENARIO   a golden scenario exercises it — either by naming it, or by tapping
                      a control whose recipe names it as a read primitive

There are no intent families any more: every sentence is a model turn (the owner had the
word-matching lane removed on 28 September 2026), so what a sentence reaches is what the
model chooses to call, and the tool rows are the whole of it.

Nothing here runs a tool. The audit is a read of registries and of source text — it must be
able to run against a shop it may not touch, and a matrix that had to execute a mutation to
fill a column would be a matrix that mutates production to describe itself.

The citation columns are read from source text rather than a hand-kept mapping, which has one
honest weakness and one honest strength. The weakness: a test that exercises a tool without
naming it — through a recipe, a scenario or a sentence the model answers — is not counted.
The strength: nothing here can claim coverage that is not written down somewhere a person can
open. Tests are read as Python syntax trees and never imported or run.
"""

from __future__ import annotations

import ast
import pathlib
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]

COLUMNS = (
    "registered", "routable", "directly_tested", "auth_scope", "read_write",
    "staging", "verification", "visible_ui", "error_ui", "golden_scenario",
)

# Where a citation may come from.
TEST_DIR = ROOT / "tests"
SCENARIO_SOURCES = (ROOT / "experience" / "scenarios.py", ROOT / "experience" / "scenario_packs")
PRESENTATION = ROOT / "app" / "presentation.py"
ANALYTICS_PRESENT = ROOT / "app" / "analytics" / "present.py"

# A word boundary around the tool's own name: `shopify_find_order` must not be matched by
# `shopify_find_order_thing`, and a comment naming the tool counts — a comment is a person
# writing the name down, which is the claim being made.
def _named(name: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(name)}\b", text) is not None


# ------------------------------------------------------------------ what a test's code does

# Calls that hold, count or compare names rather than call what they name — and a monkeypatch
# that REPLACES a tool, which is the opposite of testing it.
_NOT_CALLING = frozenset({
    "setattr", "delattr", "setitem", "delitem", "patch", "object",
    "len", "set", "frozenset", "sorted", "list", "tuple", "dict", "isinstance", "print",
    "str", "repr", "format", "join", "startswith", "endswith",
})


@dataclass
class Citations:
    """What one test file's code does with names, read from its syntax tree: the strings that
    reach a call as an argument, and the functions it calls (as module and name)."""

    call_strings: set[str] = field(default_factory=set)
    calls: set[tuple[str, str]] = field(default_factory=set)

    def calls_tool(self, name: str, module: str, function: str) -> bool:
        """Whether the test calls the tool: passes its name to a call, or calls its handler."""
        return name in self.call_strings or (module, function) in self.calls


def read_test(text: str, constant: Callable[[str, str], Any] | None = None) -> Citations:
    """Read a test file's source into its Citations. Nothing in it is imported or run. A file
    that is not valid Python cites nothing.

    A test often holds a tool's name in a constant of the app module that defines the tool
    (`WRITE = discounts.WRITE_TOOL`, then `dispatch(WRITE, ...)`); `constant(module, name)`
    gives the value of such a constant, or None, and is how those names are followed."""
    code = Citations()
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return code
    nodes = list(ast.walk(tree))

    imported: dict[str, tuple[str, str]] = {}   # alias -> (module, name)
    modules: dict[str, str] = {}                # alias -> module
    for node in nodes:
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                as_name = alias.asname or alias.name
                imported[as_name] = (node.module, alias.name)
                modules[as_name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    modules[alias.asname] = alias.name
                else:
                    top = alias.name.split(".")[0]
                    modules[top] = top

    def module_of(node: ast.AST) -> str | None:
        dotted = _dotted(node)
        if dotted is None:
            return None
        head, _, rest = dotted.partition(".")
        if head not in modules:
            return None
        return modules[head] + (f".{rest}" if rest else "")

    def held(module: str, name: str) -> set[str]:
        """An app constant holding ONE name. A constant holding many — a registry's list of
        tool names — passed to a call is counted, compared or checked, not each tool called."""
        value = constant(module, name) if constant is not None else None
        return {value} if isinstance(value, str) else set()

    # Names bound to strings, anywhere in the file. A name holds one string at a time
    # (NAME = "tool", NAME = module.CONSTANT, a loop variable, a parametrize argument) or a
    # collection of them (NAMES = ("a", "b")), which counts only where it is iterated.
    one: dict[str, set[str]] = {}
    many: dict[str, set[str]] = {}

    def strings(node: ast.AST | None, *, iterated: bool = False) -> set[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return set().union(*(strings(item) for item in node.elts)) if node.elts else set()
        if isinstance(node, ast.Dict):
            return set().union(*(strings(v) for v in node.values)) if node.values else set()
        if isinstance(node, ast.Name):
            found = set(one.get(node.id, ()))
            if iterated:
                found |= many.get(node.id, set())
            if node.id in imported and node.id not in one:
                found |= held(*imported[node.id])
            return found
        if isinstance(node, ast.Attribute):
            module = module_of(node.value)
            return held(module, node.attr) if module is not None else set()
        return set()

    def bind(target: ast.AST, value: ast.AST | None, *, iterated: bool = False) -> None:
        if isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                bind(item, value, iterated=iterated)
            return
        if not isinstance(target, ast.Name):
            return
        if iterated:
            found = strings(value, iterated=True)
            if found:
                one.setdefault(target.id, set()).update(found)
        elif isinstance(value, (ast.Tuple, ast.List, ast.Set)):
            found = strings(value)
            if found:
                many.setdefault(target.id, set()).update(found)
        elif isinstance(value, ast.Name) and value.id in many:
            many.setdefault(target.id, set()).update(many[value.id])
        else:
            found = strings(value)
            if found:
                one.setdefault(target.id, set()).update(found)

    for _ in range(2):       # twice, so a name bound from another bound name is followed
        for node in nodes:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    bind(target, node.value)
            elif isinstance(node, ast.AnnAssign) and node.value is not None:
                bind(node.target, node.value)
            elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
                bind(node.target, node.iter, iterated=True)
            elif (isinstance(node, ast.Call) and _callee(node.func) == "parametrize"
                  and len(node.args) >= 2 and isinstance(node.args[0], ast.Constant)
                  and isinstance(node.args[0].value, str)):
                values = strings(node.args[1], iterated=True)
                for argname in node.args[0].value.split(","):
                    if argname.strip() and values:
                        one.setdefault(argname.strip(), set()).update(values)

    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        if _callee(node.func) not in _NOT_CALLING:
            for argument in [*node.args, *(keyword.value for keyword in node.keywords)]:
                code.call_strings.update(strings(argument))
        if isinstance(node.func, ast.Name) and node.func.id in imported:
            code.calls.add(imported[node.func.id])
        elif isinstance(node.func, ast.Attribute):
            module = module_of(node.func.value)
            if module is not None:
                code.calls.add((module, node.func.attr))
    return code


def _callee(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base is not None else None
    return None


def _loaded_constant(module: str, name: str) -> Any:
    """A constant of an app module that load() has already imported, or None: nothing is
    imported to find it."""
    loaded = sys.modules.get(module)
    return getattr(loaded, name, None) if loaded is not None else None


@lru_cache(maxsize=1)
def _test_code() -> dict[str, Citations]:
    """Every test file, read once into what its code does."""
    return {path: read_test(text, _loaded_constant) for path, text in _sources()["test"].items()}


@lru_cache(maxsize=1)
def _sources() -> dict[str, dict[str, str]]:
    """Every file that can cite a tool, read once, as {kind: {path: text}}."""
    out: dict[str, dict[str, str]] = {"test": {}, "scenario": {}, "presentation": {}}
    for path in sorted(TEST_DIR.glob("test_*.py")):
        out["test"][path.name] = path.read_text(encoding="utf-8", errors="ignore")
    for where in SCENARIO_SOURCES:
        paths = sorted(where.glob("*.py")) if where.is_dir() else [where]
        for path in paths:
            if path.name != "__init__.py":
                out["scenario"][path.name] = path.read_text(encoding="utf-8", errors="ignore")
    for path in (PRESENTATION, ANALYTICS_PRESENT):
        out["presentation"][path.name] = path.read_text(encoding="utf-8", errors="ignore")
    return out


def load() -> None:
    """Import everything that registers a tool, a recipe, a command or a family.

    Importing is the only way to know what is registered — the registries are built by the
    decorators in these modules — and it is also the only thing this audit does that has any
    effect at all.
    """
    import app.families  # noqa: F401
    import app.tools.analytics_tools  # noqa: F401
    import app.tools.batch_tools  # noqa: F401
    import app.tools.display_tools  # noqa: F401
    import app.tools.engineering_tools  # noqa: F401
    import app.tools.gmail_tools  # noqa: F401
    import app.tools.gmail_writes  # noqa: F401
    import app.tools.shopify_tools  # noqa: F401
    import app.tools.shopify_writes  # noqa: F401
    from app.families import load_all

    load_all()


# ------------------------------------------------------------------ what reaches a tool


def _recipe_tools() -> dict[str, list[str]]:
    """Tool name -> the tap recipes whose read primitives name it."""
    from app.recipes import RECIPES

    out: dict[str, list[str]] = {}
    for recipe in RECIPES.values():
        for tool in recipe.read_primitives or ():
            out.setdefault(str(tool), []).append(recipe.recipe_id)
    return out


def _command_tools() -> dict[str, list[str]]:
    """Tool name -> the semantic commands that reach it.

    Two ways a tap reaches a tool: the member read a cursor move makes
    (app/commands.py MEMBER_READ), and a command that stages a change, whose tool the
    command's own registration names.
    """
    from app import commands

    out: dict[str, list[str]] = {}
    for kind, (tool, _arg, _entity) in getattr(commands, "MEMBER_READ", {}).items():
        if tool:
            out.setdefault(str(tool), []).append(f"cursor:{kind}")
    # A command that PROPOSES a change names the write tool the Mac prepares it with, in the
    # command's own module rather than in the registry — so the citation is the module text,
    # as it is for tests and scenarios.
    from app.tools import registry

    command_source = (ROOT / "app" / "commands.py").read_text(encoding="utf-8", errors="ignore")
    for path in sorted((ROOT / "app" / "families").glob("*.py")):
        command_source += path.read_text(encoding="utf-8", errors="ignore")
    for spec in registry.all_specs():
        if (spec.write is not None or spec.batch is not None) and _named(spec.name, command_source):
            out.setdefault(spec.name, []).append("a tapped control")
    return out


def _family_tools() -> dict[str, dict[str, Any]]:
    """Tool name -> the capability family that owns it, with its declared scopes and state."""
    from app.capabilities import families as family_mod

    out: dict[str, dict[str, Any]] = {}
    for family in family_mod.REGISTRY.values():
        for tool in (*family.tools, *_write_tools_of(family)):
            out.setdefault(str(tool), {
                "family": family.key, "scopes": list(family.scopes), "state": family.state,
            })
    return out


def _write_tools_of(family: Any) -> list[str]:
    """The registered write tools whose operation this family declares."""
    from app.tools import registry

    wanted = set(family.operations or ())
    return [
        spec.name for spec in registry.all_specs()
        if spec.write is not None and spec.write.operation in wanted
    ]


def _scenario_tools() -> dict[str, set[str]]:
    """Tool name -> the golden scenarios that exercise it.

    Two ways a scenario counts. It may NAME the tool — an assertion about what was read, a
    fixture that answers it, the read the harness's model makes. Or it may tap a control whose
    recipe's read primitives include the tool, in which case running the scenario runs the
    tool whether it says so or not; `experience/matrix.py::COVERAGE` is the repository's own
    mapping of which scenario exercises which operation, and this walks it through to the
    tools. A write tool also counts its OPERATION name, which is what a scenario asserting on
    a staged change writes down.

    Deriving it this way keeps the one property that matters: a tool with no route from any
    scenario is REPORTED as uncovered rather than assumed covered because its unit tests pass.
    """
    from app.recipes import RECIPES
    from app.tools import registry
    from experience.matrix import COVERAGE
    from experience.scenarios import BY_NAME

    out: dict[str, set[str]] = {}
    for operation, scenarios in COVERAGE.items():
        named = [s for s in scenarios if s in BY_NAME]
        if not named:
            continue
        recipe = RECIPES.get(operation)
        for tool in (recipe.read_primitives if recipe is not None else ()):
            out.setdefault(str(tool), set()).update(named)
    sources = _sources()["scenario"]
    for spec in registry.all_specs():
        terms = [spec.name] + ([spec.write.operation] if spec.write is not None else []) + \
                ([spec.batch.operation] if spec.batch is not None else [])
        for path, text in sources.items():
            if any(_named(term, text) for term in terms if term):
                out.setdefault(spec.name, set()).add(path)
    return out


# ------------------------------------------------------------------ the rows


def tools() -> list[dict[str, Any]]:
    """One row per registered tool."""
    from app.tools import registry

    by_recipe, by_command, by_family = _recipe_tools(), _command_tools(), _family_tools()
    by_scenario = _scenario_tools()
    sources, tests = _sources(), _test_code()
    rows: list[dict[str, Any]] = []
    for spec in registry.all_specs():
        name = spec.name
        family = by_family.get(name, {})
        reached = [f"recipe:{r}" for r in by_recipe.get(name, ())] + \
                  [f"command:{c}" for c in by_command.get(name, ())] + \
                  ([f"family:{family['family']}"] if family else [])
        handler = (getattr(spec.handler, "__module__", ""), getattr(spec.handler, "__name__", ""))
        tested_by = sorted(path for path, code in tests.items() if code.calls_tool(name, *handler))
        scenarios = sorted(by_scenario.get(name, ()))
        kind = "batch" if spec.batch is not None else ("write" if spec.write is not None else "read")
        rows.append({
            "name": name,
            "registered": True,
            "tier": spec.tier.value,
            "routable": bool(reached),
            "reached_by": reached,
            "directly_tested": bool(tested_by),
            "tested_by": tested_by,
            "auth_scope": ", ".join(family.get("scopes") or ()) or ("none needed" if kind == "read" else ""),
            "read_write": kind,
            "staging": _staging(spec),
            "verification": _verification(spec),
            "visible_ui": _visible_ui(name, kind, sources),
            "error_ui": _error_ui(name),
            "golden_scenario": bool(scenarios),
            "scenarios": scenarios,
            "capability_family": family.get("family", ""),
            "capability_state": family.get("state", ""),
        })
    return rows


def _staging(spec: Any) -> str:
    """What happens between the model asking and the shop changing. Empty for a read."""
    if spec.batch is not None:
        return f"one proposal per member, through {spec.batch.child_tool}"
    if spec.write is None:
        return ""
    if not spec.write.complete:
        return "INCOMPLETE — registered as a write with a missing step"
    return f"prepared from a fresh read, held as {spec.write.operation}, {spec.write.interaction}"


def _verification(spec: Any) -> str:
    if spec.batch is not None:
        return f"each member proven by {spec.batch.child_tool}"
    if spec.write is None:
        return ""
    if spec.write.verify is not None:
        return "a predicate over the re-read" + (", after settling" if spec.write.settle else "")
    return "the re-read must equal what was expected"


def _visible_ui(name: str, kind: str, sources: dict[str, dict[str, str]]) -> str:
    """Which presenter draws this tool's result. A write's card is the confirmation the
    action engine builds, which every staged change gets."""
    if kind in ("write", "batch"):
        return "the change's own card"
    from app.presentation import ANALYTIC_TOOLS, WORKSPACE_TOOLS

    if name in ANALYTIC_TOOLS:
        return "the read layer's cards"
    if name in WORKSPACE_TOOLS:
        return "a workspace"
    where = [path for path, text in sources["presentation"].items() if _named(name, text)]
    return ", ".join(where) if where else ""


def _error_ui(name: str) -> str:
    """What the owner sees when this tool fails: the named service, or nothing.

    The same division `app/presentation.py::_tool_error` makes. A tool outside both prefixes
    draws the generic "Lookup failed", which is a card but not a NAMED one, and this column
    is about whether the owner is told which thing is unavailable.
    """
    if name.startswith("shopify_"):
        return "shopify"
    if name.startswith("gmail_"):
        return "gmail"
    return ""


# ------------------------------------------------------------------ the document


def _tick(value: Any) -> str:
    return "yes" if value else "—"


def gaps() -> dict[str, list[str]]:
    """What the matrix cannot vouch for. Printed in the document, because a matrix whose only
    job is to look complete is worse than no matrix."""
    rows = tools()
    return {
        "no test calls it": [r["name"] for r in rows if not r["directly_tested"]],
        "no golden scenario names it": [r["name"] for r in rows if not r["golden_scenario"]],
        "nothing but the model reaches it": [r["name"] for r in rows if not r["routable"]],
        "no card is drawn from it": [r["name"] for r in rows if not r["visible_ui"]],
        "no named error card": [r["name"] for r in rows if not r["error_ui"]],
    }


def markdown() -> str:
    load()
    rows, missing = tools(), gaps()
    reads = sum(1 for r in rows if r["read_write"] == "read")
    writes = sum(1 for r in rows if r["read_write"] == "write")
    batches = sum(1 for r in rows if r["read_write"] == "batch")
    out = [
        "# Tool matrix",
        "",
        "Every registered tool, audited against §32 of the",
        "Phase 4 brief. **Generated** by `experience/tool_matrix.py` — regenerate with",
        "`make tool-matrix`; `tests/test_tool_matrix.py` fails if this file and the registries",
        "disagree.",
        "",
        "Every column is read from the thing that decides it. **DIRECTLY TESTED** means a test",
        "CALLS the tool — its code passes the tool's name to a call, or calls the tool's handler",
        "— and the file that does is cited. A test that only mentions the tool, in a comment, a",
        "docstring, an assertion about a list of names or a monkeypatch that replaces it, does",
        "not count, so a tool whose unit tests pass but which no test calls is reported as",
        "untested. There are no intent families: every sentence is a model turn, so what a",
        "sentence reaches is what the model calls. Tests are read as syntax trees and never run; nothing",
        "here runs a tool, and nothing here can reach a mutation: the audit is a read of",
        "registries and of source text, so it is safe against a shop it may not touch.",
        "",
        f"{len(rows)} tools — {reads} reads, {writes} writes, {batches} bulk.",
        "",
        "## Tools",
        "",
        "| Tool | Tier | Registered | Routable | Directly tested | Auth scope | Read/write | Staging | Verification | Visible UI | Error UI | Golden scenario |",
        "|---|---|:-:|:-:|:-:|---|---|---|---|---|---|:-:|",
    ]
    for r in rows:
        out.append(
            f"| `{r['name']}` | {r['tier']} | {_tick(r['registered'])} | {_tick(r['routable'])} "
            f"| {_tick(r['directly_tested'])} | {r['auth_scope'] or '—'} | {r['read_write']} "
            f"| {r['staging'] or '—'} | {r['verification'] or '—'} | {r['visible_ui'] or '—'} "
            f"| {r['error_ui'] or '—'} | {_tick(r['golden_scenario'])} |"
        )
    out += [
        "",
        "### What cites each tool",
        "",
        "| Tool | Reached by | Called in tests | Named in scenarios |",
        "|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| `{r['name']}` | {', '.join(r['reached_by']) or 'the model only'} "
            f"| {', '.join(r['tested_by']) or '—'} | {', '.join(r['scenarios']) or '—'} |"
        )
    out += ["", "## What this matrix cannot vouch for", ""]
    for heading, names in missing.items():
        out.append(f"**{heading} ({len(names)})**")
        out.append("")
        out.append(", ".join(f"`{n}`" for n in names) if names else "none")
        out.append("")
    out += [
        "## The rules the audit itself keeps",
        "",
        "- Reads never mutate: `app/reads/scheduler.py::assert_reads_only` refuses a plan",
        "  naming a write tool, in every lane, and `app/reads/dedupe.py` refuses to hold,",
        "  join or reuse one.",
        "- No arbitrary GraphQL from the model: the model reaches only the tools above, each",
        "  of which builds its own document.",
        "- Speculation may never write or commit: a prediction's tool is checked against the",
        "  registry (`write is None and batch is None`) and then run through the same plan",
        "  assertion.",
        "- Unknown writes fail closed: `app/tools/gate.py` denies an unregistered tool and",
        "  denies any mutation-shaped name without a complete `WriteSpec`.",
        "- Nothing in this audit executed a tool, so no fixture and no shop was changed to",
        "  produce it.",
        "",
    ]
    return "\n".join(out)


def write(path: pathlib.Path | None = None) -> pathlib.Path:
    target = pathlib.Path(path) if path is not None else ROOT / "docs" / "phase4" / "TOOL_MATRIX.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown(), encoding="utf-8")
    return target
