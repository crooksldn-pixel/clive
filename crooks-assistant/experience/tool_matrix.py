"""The tool and intent-family audit (§32) — derived, never asserted.

The brief's instruction is the whole design of this file: *do not claim a tool works because
unit tests pass.* So every column is read from the thing that decides it, and where a column
cannot be decided it says so rather than being filled in optimistically:

    REGISTERED        the tool is in app/tools/registry.py
    ROUTABLE          something other than the model's free choice reaches it — a fast-path
                      recipe's read primitives, a semantic command, or a capability family
    DIRECTLY TESTED   a test or a golden scenario NAMES this tool. The citation is printed;
                      a tool with no citation is reported untested, which is honest
    AUTH-SCOPE        the Shopify or Gmail scope its capability family declares
    READ-WRITE        read, write or batch, from the spec
    STAGING           a write's WriteSpec is complete: prepare, observe, execute, present
    VERIFICATION      how a write is proven — a predicate, or the default exact re-read
    VISIBLE UI        app/presentation.py names it, so its result becomes a card
    ERROR UI          its failure is drawn as a named service rather than a generic error
    GOLDEN SCENARIO   a golden scenario exercises it — either by naming it, or by asking
                      a question whose recipe names it as a read primitive

Nothing here runs a tool. The audit is a read of registries and of source text — it must be
able to run against a shop it may not touch, and a matrix that had to execute a mutation to
fill a column would be a matrix that mutates production to describe itself.

The citation columns are text SEARCHES rather than a hand-kept mapping, which has one honest
weakness and one honest strength. The weakness: a test that exercises a tool without naming
it is not counted. The strength: nothing here can claim coverage that is not written down
somewhere a person can open.
"""

from __future__ import annotations

import pathlib
import re
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
    import app.fastpath.library  # noqa: F401
    import app.tools.analytics_tools  # noqa: F401
    import app.tools.batch_tools  # noqa: F401
    import app.tools.engineering_tools  # noqa: F401
    import app.tools.gmail_tools  # noqa: F401
    import app.tools.gmail_writes  # noqa: F401
    import app.tools.shopify_tools  # noqa: F401
    import app.tools.shopify_writes  # noqa: F401
    from app.families import load_all

    load_all()


# ------------------------------------------------------------------ what reaches a tool


def _recipe_tools() -> dict[str, list[str]]:
    """Tool name -> the recipes whose read primitives name it."""
    from app.fastpath.recipes import RECIPES

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
    fixture that answers it. Or it may ask a question the fast lane answers with a recipe
    whose read primitives include the tool, in which case running the scenario runs the tool
    whether it says so or not; `experience/matrix.py::COVERAGE` is the repository's own
    mapping of which scenario exercises which intent family, and this walks it through to the
    tools. A write tool also counts its OPERATION name, which is what a scenario asserting on
    a staged change writes down.

    Deriving it this way keeps the one property that matters: a tool with no route from any
    scenario is REPORTED as uncovered rather than assumed covered because its unit tests pass.
    """
    from app.fastpath.recipes import recipe_for
    from app.tools import registry
    from experience.matrix import COVERAGE
    from experience.scenarios import BY_NAME

    out: dict[str, set[str]] = {}
    for operation, scenarios in COVERAGE.items():
        named = [s for s in scenarios if s in BY_NAME]
        if not named:
            continue
        recipe = recipe_for(operation)
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


def _family_scenarios() -> dict[str, list[str]]:
    """Intent family -> the golden scenarios that exercise it, from the repository's own map."""
    from experience.matrix import COVERAGE
    from experience.scenarios import BY_NAME

    return {name: [s for s in scenarios if s in BY_NAME] for name, scenarios in COVERAGE.items()}


# ------------------------------------------------------------------ the rows


def tools() -> list[dict[str, Any]]:
    """One row per registered tool."""
    from app.tools import registry

    by_recipe, by_command, by_family = _recipe_tools(), _command_tools(), _family_tools()
    by_scenario = _scenario_tools()
    sources = _sources()
    rows: list[dict[str, Any]] = []
    for spec in registry.all_specs():
        name = spec.name
        family = by_family.get(name, {})
        reached = [f"recipe:{r}" for r in by_recipe.get(name, ())] + \
                  [f"command:{c}" for c in by_command.get(name, ())] + \
                  ([f"family:{family['family']}"] if family else [])
        tested_by = sorted(path for path, text in sources["test"].items() if _named(name, text))
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


def families() -> list[dict[str, Any]]:
    """One row per intent family: what a sentence can reach without the model."""
    from app.fastpath.intent import all_families
    from app.fastpath.recipes import recipe_for

    sources = _sources()
    covered = _family_scenarios()
    rows: list[dict[str, Any]] = []
    for family in all_families():
        recipe = recipe_for(family.name)
        primitives = list(recipe.read_primitives) if recipe is not None else []
        tested_by = sorted(path for path, text in sources["test"].items() if _named(family.name, text))
        scenarios = sorted(set(covered.get(family.name, ())) | {
            path for path, text in sources["scenario"].items() if _named(family.name, text)
        })
        rows.append({
            "name": family.name,
            "kind": family.kind,
            "registered": True,
            "routable": True,
            "recipe": recipe.recipe_id if recipe is not None else "",
            "read_primitives": primitives,
            "serves_mutation_words": family.serves_mutation_words,
            "directly_tested": bool(tested_by),
            "tested_by": tested_by,
            "golden_scenario": bool(scenarios),
            "scenarios": scenarios,
        })
    return rows


# ------------------------------------------------------------------ the document


def _tick(value: Any) -> str:
    return "yes" if value else "—"


def gaps() -> dict[str, list[str]]:
    """What the matrix cannot vouch for. Printed in the document, because a matrix whose only
    job is to look complete is worse than no matrix."""
    rows = tools()
    return {
        "no test names it": [r["name"] for r in rows if not r["directly_tested"]],
        "no golden scenario names it": [r["name"] for r in rows if not r["golden_scenario"]],
        "nothing but the model reaches it": [r["name"] for r in rows if not r["routable"]],
        "no card is drawn from it": [r["name"] for r in rows if not r["visible_ui"]],
        "no named error card": [r["name"] for r in rows if not r["error_ui"]],
        "intent families with no scenario": [r["name"] for r in families() if not r["golden_scenario"]],
    }


def markdown() -> str:
    load()
    rows, family_rows, missing = tools(), families(), gaps()
    reads = sum(1 for r in rows if r["read_write"] == "read")
    writes = sum(1 for r in rows if r["read_write"] == "write")
    batches = sum(1 for r in rows if r["read_write"] == "batch")
    out = [
        "# Tool matrix",
        "",
        "Every registered tool and every routable intent family, audited against §32 of the",
        "Phase 4 brief. **Generated** by `experience/tool_matrix.py` — regenerate with",
        "`make tool-matrix`; `tests/test_tool_matrix.py` fails if this file and the registries",
        "disagree.",
        "",
        "Every column is read from the thing that decides it. **DIRECTLY TESTED** means a test",
        "or a golden scenario NAMES the tool, and the file that does is cited; a tool whose",
        "unit tests pass but which nothing calls by name is reported as untested. Nothing here",
        "runs a tool, and nothing here can reach a mutation: the audit is a read of registries",
        "and of source text, so it is safe against a shop it may not touch.",
        "",
        f"{len(rows)} tools — {reads} reads, {writes} writes, {batches} bulk — and "
        f"{len(family_rows)} intent families.",
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
        "| Tool | Reached by | Named in tests | Named in scenarios |",
        "|---|---|---|---|",
    ]
    for r in rows:
        out.append(
            f"| `{r['name']}` | {', '.join(r['reached_by']) or 'the model only'} "
            f"| {', '.join(r['tested_by']) or '—'} | {', '.join(r['scenarios']) or '—'} |"
        )
    out += [
        "",
        "## Intent families",
        "",
        "| Family | For | Recipe | Reads | Serves mutation words | Directly tested | Golden scenario |",
        "|---|---|---|---|:-:|:-:|:-:|",
    ]
    for r in family_rows:
        out.append(
            f"| `{r['name']}` | {r['kind']} | {r['recipe'] or '— (the model answers it)'} "
            f"| {', '.join(f'`{t}`' for t in r['read_primitives']) or '—'} "
            f"| {_tick(r['serves_mutation_words'])} | {_tick(r['directly_tested'])} "
            f"| {_tick(r['golden_scenario'])} |"
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
