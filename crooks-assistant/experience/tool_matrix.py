"""The tool audit (§32) — derived, never asserted.

The brief's instruction is the whole design of this file: *do not claim a tool works because
unit tests pass.* So every column is read from the thing that decides it, and where a column
cannot be decided it says so rather than being filled in optimistically:

    REGISTERED        the tool is in app/tools/registry.py
    ROUTABLE          something other than the model's free choice reaches it — a tap
                      recipe's read primitives, a semantic command, or a capability family
    DIRECTLY TESTED   a test RUNS this tool: its code — not a comment, not a docstring —
                      hands the tool's name to the dispatcher (app/tools/dispatch.py), to
                      `registry.invoke` or to the SDK provider's callback, directly, through a
                      variable, loop variable or app constant holding it, or through a helper
                      of the test's own that hands it on; or calls the tool's handler function
                      by name — in code that runs: a test, a fixture a test asks for, a helper
                      a test calls, directly or through other helpers, or a class (a model
                      double) such code makes (a dispatch in a helper nothing calls is not
                      run). The citation is printed. Nothing else
                      counts (the 2026-09-28
                      deploy review, round 9, I-tests5 I-05): looking the tool up in the
                      registry, asking the gate to classify a call, drawing a card from a tool
                      call the test made up, a mention in a comment, a docstring or an
                      assertion about names, a monkeypatch that replaces it, or the provider's
                      callback in a test that has replaced the dispatcher behind it. A tool
                      with no citation is reported untested, which is honest
    AUTH-SCOPE        the Shopify or Gmail scope its capability family declares
    READ-WRITE        read, write or batch, from the spec. "Read" is the write boundary's word
                      (no WriteSpec, no BatchSpec), not "changes nothing": the screen tools
                      (`SCREEN_CHANGERS`) are reads that change what a screen shows
    STAGING           a write's WriteSpec is complete: prepare, observe, execute, present
    VERIFICATION      how a write is proven — a predicate, or the default exact re-read
    VISIBLE UI        app/presentation.py names it, so its result becomes a card
    ERROR UI          its failure is drawn as a named service rather than a generic error
    GOLDEN SCENARIO   a golden scenario's CODE reaches it — the scenario (or a helper in its
                      own file, or a harness helper such as `open_order`) hands the tool's name
                      to the model it scripts as a call's tool or to the dispatcher, or taps a
                      control whose recipe reads it or whose staging command prepares it. A
                      mention in a check's description, an assertion comparing an operation
                      name, a label, a reply, a comment, a docstring, or a constant, dict or
                      list the code never hands on does not count, and the row names the
                      SCENARIO, not the file.
                      A write is reported as STAGED: no golden scenario can apply a change —
                      the fixture world refuses every mutation — so none is claimed as applied

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

# The tools classed as reads here that change what a screen shows (app/tools/display_tools.py,
# app/tools/close_screen.py). "Read" is the write boundary's word — no WriteSpec, no BatchSpec —
# and the document says so and names these, because "reads never mutate" read as a claim that
# nothing changes, and these change the owner's screens (the 2026-09-30 deploy review, DOC2-02).
SCREEN_CHANGERS: dict[str, str] = {
    "screen_show": "puts a packing slip, an objective or a list on a screen, or clears it",
    "screen_off": "takes everything, or one pane, off a screen",
    "screen_play": "puts a video on a screen",
    "screen_video": "plays, pauses, mutes, skips or sets the volume of a screen's video",
    "screen_pair": "approves a newly named screen, which then leaves its pairing code",
    "close_screen": "closes what is on the owner's own screen and goes back to the orb",
}

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

# The calls that RUN a tool named by their first argument: the dispatcher every tool call goes
# through (app/tools/dispatch.py), and the registry's own invocation of a handler. Nothing else
# a test does with a tool's name runs it — looking its spec up (`registry.get`), asking the
# gate about a call (`classify`), drawing a card from a tool call the test made up (`present`),
# counting or comparing names, or monkeypatching the tool away — and none of those counts (the
# 2026-09-28 deploy review, round 9, I-tests5 I-05 and H-06).
_RUNS_A_TOOL = frozenset({("app.tools.dispatch", "dispatch"), ("app.tools.registry", "invoke")})
# The Agent SDK provider's callback, which hands the SDK's tool call to the dispatcher
# (app/providers/max_agent_sdk.py `MaxAgentSDKProvider._dispatch`); a method, so it is known
# by its name on whatever object holds it.
_RUNS_A_TOOL_METHODS = frozenset({"_dispatch"})
# Where a call to one of those names the tool.
_TOOL_KEYWORDS = frozenset({"tool_name", "name"})


@dataclass
class Citations:
    """What one test file's code does with names, read from its syntax tree: the strings it
    hands to the dispatcher or to `registry.invoke` as the tool to run, and the functions it
    calls (as module and name)."""

    call_strings: set[str] = field(default_factory=set)
    calls: set[tuple[str, str]] = field(default_factory=set)

    def calls_tool(self, name: str, module: str, function: str) -> bool:
        """Whether the test RUNS the tool: hands its name to the dispatcher or to the registry's
        invocation, or calls its handler function itself."""
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

    def runs_a_tool(func: ast.AST) -> bool:
        """The dispatcher, `registry.invoke` or the provider's callback — however it was
        imported: by name, through its module, or through an alias of either."""
        if isinstance(func, ast.Name):
            return imported.get(func.id) in _RUNS_A_TOOL
        if isinstance(func, ast.Attribute):
            if func.attr in _RUNS_A_TOOL_METHODS:
                return True
            module = module_of(func.value)
            return module is not None and (module, func.attr) in _RUNS_A_TOOL
        return False

    # A test's own helper that hands one of its parameters to the dispatcher as the tool
    # (`async def stage(session, tool, **args): ... await dispatch(tool, args, ...)`) runs the
    # tool a call to it names: helper -> the positions and names of those parameters. Followed
    # through helpers of helpers; only the file's module-level functions, so a nested function
    # of the same name elsewhere is not mistaken for one.
    helpers = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    forwards: dict[str, set[tuple[int, str]]] = {}

    def tool_arguments(call: ast.Call) -> list[ast.AST]:
        """The arguments of this call that name the tool it runs; none if it runs none. The
        arguments the tool is given are not tools, whatever strings they hold."""
        if runs_a_tool(call.func):
            return [*call.args[:1], *(k.value for k in call.keywords if k.arg in _TOOL_KEYWORDS)]
        if isinstance(call.func, ast.Name) and call.func.id in forwards:
            held_at = forwards[call.func.id]
            positions = {i for i, _ in held_at}
            names = {n for _, n in held_at}
            return [*(a for i, a in enumerate(call.args) if i in positions),
                    *(k.value for k in call.keywords if k.arg in names)]
        return []

    changed = True
    while changed:
        changed = False
        for name, fn in helpers.items():
            params = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
            keyword_only = {a.arg for a in fn.args.kwonlyargs}
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                for argument in tool_arguments(node):
                    if not isinstance(argument, ast.Name):
                        continue
                    if argument.id in params:
                        entry = (params.index(argument.id), argument.id)
                    elif argument.id in keyword_only:
                        entry = (-1, argument.id)
                    else:
                        continue
                    if entry not in forwards.setdefault(name, set()):
                        forwards[name].add(entry)
                        changed = True

    # The provider's callback hands the call on to the dispatcher its own module imported. A test
    # that replaces that dispatcher (`monkeypatch.setattr(max_agent_sdk, "dispatch", stub)`) is
    # testing the callback's own refusals, and no tool runs behind it: a call to the callback in
    # the function that does so does not count (tests/test_provider.py's cancelled-turn tests).
    not_run: set[int] = set()
    for fn in nodes:
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and "dispatch" in _replaced(fn):
            not_run |= {id(n) for n in ast.walk(fn) if isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute) and n.func.attr in _RUNS_A_TOOL_METHODS}

    ran, in_tests = _calls_that_run(tree)
    for node in nodes:
        if not isinstance(node, ast.Call) or id(node) not in ran:
            continue
        # A call to the file's own forwarding helper is the helper's dispatch at one remove: it
        # credits the tool it names only where a test makes it, never from the top-level code.
        through_a_helper = not runs_a_tool(node.func)
        if id(node) not in not_run and (id(node) in in_tests or not through_a_helper):
            for argument in tool_arguments(node):
                code.call_strings.update(strings(argument))
        if isinstance(node.func, ast.Name) and node.func.id in imported:
            code.calls.add(imported[node.func.id])
        elif isinstance(node.func, ast.Attribute):
            module = module_of(node.func.value)
            if module is not None:
                code.calls.add((module, node.func.attr))
    return code


# What pytest runs of a test file without being asked by name: every `test*` function and
# method, and the set-up and tear-down hooks.
_HOOKS = ("setup", "teardown")


def _targets(node: ast.Assign | ast.AnnAssign) -> list[ast.AST]:
    """What an assignment binds: its targets, or an annotated one's single target."""
    return list(node.targets) if isinstance(node, ast.Assign) else [node.target]


def _calls_that_run(tree: ast.Module) -> tuple[set[int], set[int]]:
    """The ids of the calls in a test file that run when its tests do, and of those among them
    that a test reaches (every one but the file's top-level code).

    The file's own code at the top runs when it is imported, but a helper it calls is not taken
    to run: only a test reaching a helper credits the helper's dispatch, so a top-level call to a
    helper no test calls credits nothing. A test function or method runs,
    and so do the set-up and tear-down hooks, every autouse fixture, and every fixture a running
    function asks for by name. Any other function of the file runs only when something that
    runs calls it — directly, or through other functions of the file, by name or as a method of
    `self` or `cls`. A class of the file that running code makes (a model double a test puts in
    the runtime, whose `turn` the application then calls) is taken to run its methods. A
    dispatch inside a helper nothing that runs calls (an `async def go()` no test awaits) runs no
    tool, and is not a citation (the 2026-09-28 deploy review, round 9, I-tests5 I-05, still
    present at round 12). A function nested inside one that runs is held to the same rule: it
    runs only when the running code around it uses it: calls it (`asyncio.run(go())`), hands it
    to a call (`anyio.run(go)`) or returns it to a caller that will (a model step a test
    builds). One it defines and never names again runs nothing (the 2026-10-01 repair, F-01).
    The same holds for a class nested in running code — its methods run once that code makes
    it, hands it on or returns it, as a class of the file's do once it is made — and for a
    lambda kept under a name, whose body runs once that name is used; a class never named again
    and a lambda never called run nothing (the landing review of 1 October 2026). A lambda
    written straight into a call, a return or a container is handed on, and runs."""
    units: dict[str, list[ast.AST]] = {}
    classes: dict[str, list[ast.AST]] = {}
    loose: list[ast.AST] = []            # statements that run on import
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            units.setdefault(node.name, []).append(node)
        elif isinstance(node, ast.ClassDef):
            loose.extend(node.decorator_list)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    units.setdefault(item.name, []).append(item)
                    classes.setdefault(node.name, []).append(item)
                else:
                    loose.append(item)
        else:
            loose.append(node)

    def is_fixture(fn: ast.AST) -> tuple[bool, bool]:
        """(a fixture, an autouse one)"""
        for decorator in getattr(fn, "decorator_list", []):
            target = decorator.func if isinstance(decorator, ast.Call) else decorator
            if _callee(target) == "fixture":
                autouse = isinstance(decorator, ast.Call) and any(
                    k.arg == "autouse" and isinstance(k.value, ast.Constant) and k.value.value is True
                    for k in decorator.keywords)
                return True, autouse
        return False, False

    fixtures = {name for name, fns in units.items() if any(is_fixture(fn)[0] for fn in fns)}

    def runs_with(root: ast.AST) -> list[ast.AST]:
        """The nodes of `root` that run when it does: its own code, and a function nested in it
        only once that code names the function again."""
        out: list[ast.AST] = []
        nested: dict[str, list[ast.AST]] = {}

        def visit(children) -> None:
            stack = list(children)
            while stack:
                node = stack.pop()
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Defining it runs its decorators and defaults, not its body.
                    nested.setdefault(node.name, []).append(node)
                    stack.extend(node.decorator_list)
                    stack.extend(node.args.defaults)
                    stack.extend(d for d in node.args.kw_defaults if d is not None)
                    continue
                if isinstance(node, ast.ClassDef):
                    # Defining it runs its decorators, its bases and its body's own statements,
                    # not its methods: those run once the code around it uses the class — makes
                    # it, hands it on or returns it — as a class of the file runs its methods
                    # once it is made.
                    nested.setdefault(node.name, []).append(node)
                    stack.extend([*node.decorator_list, *node.bases, *node.keywords])
                    stack.extend(item for item in node.body
                                 if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)))
                    continue
                if (isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Lambda)
                        and all(isinstance(t, ast.Name) for t in _targets(node))):
                    # A lambda kept under a name is a nested function by another spelling: its
                    # body runs once the code uses that name, and not before. A lambda written
                    # straight into a call, a return or a container is handed on, and runs.
                    out.append(node)
                    for target in _targets(node):
                        nested.setdefault(target.id, []).append(node.value)
                    stack.extend(node.value.args.defaults)
                    stack.extend(d for d in node.value.args.kw_defaults if d is not None)
                    continue
                out.append(node)
                stack.extend(ast.iter_child_nodes(node))

        def reaches() -> set[str]:
            # A name the running code reads: a call, an argument, a return, a list entry.
            return {node.id for node in out if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}

        visit(ast.iter_child_nodes(root))
        entered: set[str] = set()
        while waiting := (reaches() & nested.keys()) - entered:
            for name in waiting:
                entered.add(name)
                for fn in nested[name]:
                    out.append(fn)
                    if isinstance(fn, ast.ClassDef):
                        for item in fn.body:
                            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                                out.append(item)
                                visit(ast.iter_child_nodes(item))
                    elif isinstance(fn, ast.Lambda):
                        visit([fn.body])
                    else:
                        visit(fn.body)
        return out

    def called(within: ast.AST) -> set[str]:
        out: set[str] = set()
        for node in runs_with(within):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                out.add(node.func.id)
            elif (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                  and node.func.value.id in ("self", "cls")):
                out.add(node.func.attr)
        return out

    def asked_for(fn: ast.AST) -> set[str]:
        args = getattr(fn, "args", None)
        if args is None:
            return set()
        return {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)} & fixtures

    # Only a test, a hook or a fixture is a root. The file's top-level code runs, but the helpers
    # it calls are not followed from it: a helper credits a dispatch only when a test function of
    # the file reaches it (the 2026-10-01 repair of the round-12 follow-up, F-02).
    todo = [name for name, fns in units.items()
            if name.startswith("test") or name.lower().startswith(_HOOKS) or any(is_fixture(fn)[1] for fn in fns)]
    reached: set[str] = set()
    running: list[ast.AST] = []
    while todo:
        name = todo.pop()
        if name in reached or (name not in units and name not in classes):
            continue
        reached.add(name)
        # A function of that name runs; a class of that name, made, runs its methods.
        for fn in [*units.get(name, ()), *classes.get(name, ())]:
            running.append(fn)
            todo.extend(called(fn))
            todo.extend(asked_for(fn))
    in_tests: set[int] = set()
    for root in running:
        in_tests |= {id(node) for node in runs_with(root) if isinstance(node, ast.Call)}
    at_top = {id(node) for root in loose for node in ast.walk(root) if isinstance(node, ast.Call)}
    return in_tests | at_top, in_tests


def _replaced(fn: ast.AST) -> set[str]:
    """The names a function replaces with `setattr` (a monkeypatch's, or the builtin): the
    attribute named by `setattr(target, "name", value)`, or the last part of a dotted
    `setattr("module.name", value)`."""
    names: set[str] = set()
    for node in ast.walk(fn):
        if not (isinstance(node, ast.Call) and _callee(node.func) == "setattr" and node.args):
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            names.add(first.value.rsplit(".", 1)[-1])
        elif len(node.args) >= 2 and isinstance(node.args[1], ast.Constant) and isinstance(node.args[1].value, str):
            names.add(node.args[1].value)
    return names


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
    import app.people.tools  # noqa: F401
    import app.tools.analytics_tools  # noqa: F401
    import app.tools.batch_tools  # noqa: F401
    import app.tools.close_screen  # noqa: F401
    import app.tools.display_tools  # noqa: F401
    import app.tools.engineering_tools  # noqa: F401
    import app.tools.gmail_tools  # noqa: F401
    import app.tools.gmail_writes  # noqa: F401
    import app.tools.instagram_tools  # noqa: F401
    import app.tools.interaction_tools  # noqa: F401
    import app.tools.returns_tools  # noqa: F401
    import app.tools.ship24_tools  # noqa: F401
    import app.tools.shopify_tools  # noqa: F401
    import app.tools.shopify_writes  # noqa: F401
    import app.tools.show_again  # noqa: F401
    import app.tools.skill_tools  # noqa: F401
    import app.work.tools  # noqa: F401
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


# The harness's own helpers that make the model read something (experience/harness.py): a
# scenario calling `h.open_order(...)` has the model call these, through the gate.
def _harness_reads() -> dict[str, set[str]]:
    from experience import harness as harness_mod

    return {
        "open_order": {name for name, _ in harness_mod.order_reads("1")},
        "list_todays_orders": {name for name, _ in harness_mod.todays_orders_reads()},
        "customer_history": {name for name, _ in harness_mod.customer_reads("")},
    }


# Where a scenario's code hands a name to something that acts on it, by the name of what it
# calls: (the first argument that does, whether every positional argument from there on does,
# the keywords that do, what the argument is). "calls" is a scripted call for the harness's
# model — `Harness.ask(said, *calls)` and `RecordingProvider.will(said, *calls)`, each call a
# (tool, arguments) pair — and "name" is a tool handed to the dispatcher or a command a tap posts
# (`Harness.touch`).
_HANDS_ON: dict[str, tuple[int, bool, tuple[str, ...], str]] = {
    "ask": (1, True, (), "calls"),
    "will": (1, True, (), "calls"),
    "dispatch": (0, False, ("tool_name", "name"), "name"),
    "touch": (0, False, ("command",), "name"),
}


def scenario_strings(text: str) -> dict[str, set[str]]:
    """Function name -> the names its code HANDS ON, for every function in one scenario file,
    with what the same file's helpers it calls hand on folded in. Read from the syntax tree;
    nothing is imported or run.

    A name is handed on when it reaches the scripted model as the tool of a call (`h.ask(said,
    (tool, args))`, directly or as what a helper of the file returns), the dispatcher as the
    tool to run, or a tap as the command it posts — written there, or held in a constant, a
    local name or a helper's parameter that reaches it. Nothing else counts, because nothing else
    is run (the 2026-09-28 deploy review, round 9, H-06, still present at round 12): a check's
    description, a reply, a label or message string, a string compared in an assertion, an
    f-string, a docstring, a constant nothing hands on, a tool named among another call's
    arguments, and a dict or list the code keeps without passing it to any of those. Names of the
    harness's reading helpers the function calls (`open_order` …) come back as `@open_order`, so
    the caller can turn them into the tools they read.
    """
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return {}
    constants: dict[str, set[str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    constants.setdefault(target.id, set()).add(node.value.value)
    functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    harness_helpers = {"open_order", "list_todays_orders", "customer_history"}

    # Each function's own names: what it binds to a value, and its parameters by position.
    bound: dict[str, dict[str, list[ast.AST]]] = {}
    params: dict[str, list[str]] = {}
    keyword_only: dict[str, set[str]] = {}
    for name, fn in functions.items():
        held: dict[str, list[ast.AST]] = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        held.setdefault(target.id, []).append(node.value)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                held.setdefault(node.target.id, []).append(node.value)
        bound[name] = held
        params[name] = [a.arg for a in (*fn.args.posonlyargs, *fn.args.args)]
        keyword_only[name] = {a.arg for a in fn.args.kwonlyargs}

    def names_of(expr: ast.AST | None, scope: str, depth: int = 0) -> set[str]:
        """The one name an expression stands for: a string written there, or held in a name."""
        if expr is None or depth > 8:
            return set()
        if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
            return {expr.value}
        if isinstance(expr, ast.IfExp):
            return names_of(expr.body, scope, depth + 1) | names_of(expr.orelse, scope, depth + 1)
        if isinstance(expr, ast.Name):
            if expr.id in bound.get(scope, {}):
                return set().union(*(names_of(v, scope, depth + 1) for v in bound[scope][expr.id]))
            return set(constants.get(expr.id, ()))
        return set()

    def calls_of(expr: ast.AST | None, scope: str, depth: int = 0) -> set[str]:
        """The tools of the scripted calls an expression stands for: the first of each (tool,
        arguments) pair — never the arguments — however the pairs are put together."""
        if expr is None or depth > 8:
            return set()
        if isinstance(expr, (ast.Tuple, ast.List)) and expr.elts:
            first = expr.elts[0]
            if isinstance(first, (ast.Tuple, ast.List, ast.Starred, ast.Call)):
                return set().union(*(calls_of(e, scope, depth + 1) for e in expr.elts))
            return names_of(first, scope, depth + 1)
        if isinstance(expr, ast.Starred):
            return calls_of(expr.value, scope, depth + 1)
        if isinstance(expr, ast.IfExp):
            return calls_of(expr.body, scope, depth + 1) | calls_of(expr.orelse, scope, depth + 1)
        if isinstance(expr, ast.Name) and expr.id in bound.get(scope, {}):
            return set().union(*(calls_of(v, scope, depth + 1) for v in bound[scope][expr.id]))
        if isinstance(expr, ast.Call) and isinstance(expr.func, ast.Name) and expr.func.id in functions:
            helper = expr.func.id
            returned = [n.value for n in ast.walk(functions[helper]) if isinstance(n, ast.Return) and n.value is not None]
            return set().union(set(), *(calls_of(v, helper, depth + 1) for v in returned))
        return set()

    # A helper of the file that hands one of its own parameters on (`async def _start(h, ...,
    # command): ... h.touch(command)`) hands on what a call to it puts there: helper -> the
    # (position, parameter, kind) of each. Followed through helpers of helpers.
    forwards: dict[str, set[tuple[int, str, str]]] = {}

    def handed(call: ast.Call) -> list[tuple[ast.AST, str]]:
        """The arguments of this call that are handed on, with what each is."""
        out: list[tuple[ast.AST, str]] = []
        callee = _callee(call.func)
        if callee in _HANDS_ON:
            start, every, keywords, kind = _HANDS_ON[callee]
            positional = call.args[start:] if every else call.args[start:start + 1]
            out += [(a, kind) for a in positional]
            out += [(k.value, kind) for k in call.keywords if k.arg in keywords]
        if isinstance(call.func, ast.Name) and call.func.id in forwards:
            for position, param, kind in forwards[call.func.id]:
                if 0 <= position < len(call.args):
                    out.append((call.args[position], kind))
                out += [(k.value, kind) for k in call.keywords if k.arg == param]
        return out

    changed = True
    while changed:
        changed = False
        for name, fn in functions.items():
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                for argument, kind in handed(node):
                    if not isinstance(argument, ast.Name) or argument.id in bound[name]:
                        continue
                    if argument.id in params[name]:
                        entry = (params[name].index(argument.id), argument.id, kind)
                    elif argument.id in keyword_only[name]:
                        entry = (-1, argument.id, kind)
                    else:
                        continue
                    if entry not in forwards.setdefault(name, set()):
                        forwards[name].add(entry)
                        changed = True

    def handed_on(name: str) -> tuple[set[str], set[str]]:
        found: set[str] = set()
        helpers: set[str] = set()
        for node in ast.walk(functions[name]):
            if not isinstance(node, ast.Call):
                continue
            callee = _callee(node.func)
            if isinstance(node.func, ast.Name) and node.func.id in functions:
                helpers.add(node.func.id)
            if isinstance(node.func, ast.Attribute) and callee in harness_helpers:
                found.add(f"@{callee}")
            for argument, kind in handed(node):
                found |= calls_of(argument, name) if kind == "calls" else names_of(argument, name)
        return found, helpers

    direct = {name: handed_on(name) for name in functions}
    out: dict[str, set[str]] = {}
    for name in functions:
        seen, todo, strings = set(), [name], set()
        while todo:
            current = todo.pop()
            if current in seen:
                continue
            seen.add(current)
            own, helpers = direct[current]
            strings |= own
            todo.extend(helpers)
        out[name] = strings
    return out


def _scenario_tools() -> dict[str, dict[str, str]]:
    """Tool name -> {golden scenario: how it reaches the tool}, derived from the scenarios' code.

    Three ways a scenario reaches a tool, and each is read off what its code does:

    * it hands the tool's name on (`scenario_strings`) — to the model it scripts as a call's
      tool (`h.ask(..., (tool, args))`), to `dispatch`, or through a helper that builds that
      call — or calls a harness helper whose reads are the tool's (`h.open_order` → the find
      and the detail read);
    * it taps a control whose recipe reads the tool (`experience/matrix.py::COVERAGE`, the
      repository's mapping of scenario to operation, walked to the recipe's read primitives);
    * its taps prepare a write it declares (`experience/matrix.py::TAP_STAGED`), and its code
      posts a staging command that can prepare that write (`experience/matrix.py::STAGES`).
      Posting the command alone credits nothing: which write a command prepares, and whether it
      is refused first, only a run can say — and `tests/test_experience.py` runs every scenario
      and holds these claims to what it really dispatched and staged.

    A write reached any of these ways has been staged and nothing more: the fixture world refuses
    every mutation, so no golden scenario applies one, and the value says "staged" so a reader
    cannot take it for more. A tool no scenario reaches is REPORTED as uncovered rather than
    assumed covered because its unit tests pass.
    """
    from app.recipes import RECIPES
    from app.tools import registry
    from experience.matrix import COVERAGE, STAGES, TAP_STAGED
    from experience.scenarios import SCENARIOS

    by_function: dict[str, set[str]] = {}
    for text in _sources()["scenario"].values():
        for function, strings in scenario_strings(text).items():
            by_function.setdefault(function, set()).update(strings)
    reads = _harness_reads()
    handed: dict[str, set[str]] = {}
    for name, fn in SCENARIOS:
        strings = set(by_function.get(getattr(fn, "__name__", ""), set()))
        for helper, tools_read in reads.items():
            if f"@{helper}" in strings:
                strings |= tools_read
        handed[name] = strings

    def kind(spec: Any) -> str:
        return "staged" if (spec.write is not None or spec.batch is not None) else "read"

    out: dict[str, dict[str, str]] = {}
    for operation, scenarios in COVERAGE.items():
        recipe = RECIPES.get(operation)
        for scenario in scenarios:
            if scenario not in handed:
                continue
            for tool in (recipe.read_primitives if recipe is not None else ()):
                out.setdefault(str(tool), {})[scenario] = "read"
    for scenario, declared in TAP_STAGED.items():
        if scenario not in handed:
            continue
        can = {tool for command, tools in STAGES.items() if command in handed[scenario] for tool in tools}
        for tool in declared:
            if tool in can:
                out.setdefault(tool, {})[scenario] = "staged"
    for spec in registry.all_specs():
        for scenario, strings in handed.items():
            if spec.name in strings:
                out.setdefault(spec.name, {})[scenario] = kind(spec)
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
        reached_in = by_scenario.get(name, {})
        scenarios = sorted(reached_in)
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
            # How far a scenario takes it: "read" for a read, "staged" for a write — prepared
            # through the action engine and never applied, because nothing in the fixture world
            # can apply a change.
            "scenario_reach": ("staged, never applied" if kind != "read" else "read") if scenarios else "",
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
    if name.startswith(("returns_", "return_")):
        return "returns"
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
        "no golden scenario reaches it": [r["name"] for r in rows if not r["golden_scenario"]],
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
        "RUNS the tool — its code hands the tool's name to the dispatcher, to `registry.invoke`",
        "or to the SDK provider's callback (itself or through a helper of its own), or calls the",
        "tool's handler — in code that runs: a test, a fixture a test asks for, a helper a test",
        "calls, directly or through other helpers, or a class (a model double) such code makes —",
        "and the file that does is cited. A dispatch in a helper no test calls is not counted.",
        "Looking the tool up in the registry,",
        "asking the gate to classify a call, drawing a card from a made-up tool call, a comment,",
        "a docstring, an assertion about a list of names, a monkeypatch that replaces it, or the",
        "provider's callback in a test that replaced the dispatcher behind it does not count, so a",
        "tool whose unit tests pass but which no test runs is reported as",
        "untested. **GOLDEN SCENARIO** is read the same way from the scenarios' code: a scenario",
        "counts when it hands the tool to the model it scripts as a call's tool or to the",
        "dispatcher, or taps a control that reads or stages it — never for naming it in an",
        "assertion, a description, a label or a reply, or holding it in a constant, dict or list",
        "it never hands on — and a write is reported as staged, because nothing in the fixture",
        "world can apply one.",
        "There are no intent families: every sentence is a model turn, so what a",
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
            f"| {r['error_ui'] or '—'} | {r['scenario_reach'] or '—'} |"
        )
    out += [
        "",
        "### What cites each tool",
        "",
        "| Tool | Reached by | Called in tests | Reached in scenarios |",
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
    registered = {r["name"] for r in rows}
    changers = [f"`{name}` ({what})" for name, what in SCREEN_CHANGERS.items() if name in registered]
    out += [
        "## The rules the audit itself keeps",
        "",
        "- **Read** in this matrix is the write boundary's word, not a promise that nothing",
        "  changes: a read is a tool with no `WriteSpec` and no `BatchSpec`, so it is never",
        "  staged, held for the owner's gesture or proven by a re-read, and it is what the read",
        "  scheduler may run. `app/reads/scheduler.py::assert_reads_only` refuses a plan naming a",
        "  write tool, in every lane, and `app/reads/dedupe.py` refuses to hold, join or reuse one.",
        "  No read changes the shop or the inbox. These reads change what a screen shows: "
        + ("; ".join(changers) if changers else "none") + ".",
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
