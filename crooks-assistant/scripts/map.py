#!/usr/bin/env python3
"""MAP.md's tables, written from the code, the pages, the settings and the deploy records.

Why this exists: ``MAP.md`` is the one page every session reads before any code. Its frozen
parts (where CLIVE started, the rules that never bend, a turn end to end, what is parked) are
written by hand. Its tables are not: they are generated here, so they can be regenerated
instead of drifting the way CURRENT_TRUTH and the README drifted.

    live       production and the deploys before it, from reports/deploy-<sha>.md, newest first
    parts      one row per app package: its lines, whether the running app loads it, its doc
    pages      one row per HTML page in web/: the address that serves it and the scripts it loads
    stores     one row per file CLIVE writes, from STORES below, each found in the code it names
    switches   every on/off setting: its default in code, the template, production as recorded
    words      the read-first word count, before (at BEFORE_REF) and after

What it promises:
- It rewrites only the text between a section's two markers in MAP.md, and nothing else.
- ``--check`` changes nothing and exits 1 when MAP.md is not what it would write.
- A package with no OWNER_DOCS row, an owner doc that does not exist, or a STORES row whose
  file or literal is gone is an error, never a quietly stale row.
- It runs no app code and imports nothing from ``app/``. Whether a module is loaded is read from
  the import statements, and from the loaders that import a package's modules by name
  (``pkgutil.iter_modules``), the way an import graph is.

    python scripts/map.py            # rewrite MAP.md's generated sections
    python scripts/map.py --check    # exit 1 if any of them is stale
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]          # crooks-assistant/
REPO = ROOT.parent
MAP = ROOT / "MAP.md"
APP = ROOT / "app"
WEB = ROOT / "web"
REPORTS = ROOT / "reports"
SETTINGS = ROOT / "config" / "settings.py"
TEMPLATE = ROOT / "deploy" / "env.production.example"
TOOL_MATRIX = ROOT / "docs" / "phase4" / "TOOL_MATRIX.md"
SOURCE_DIRS = ("app", "config", "scripts", "experience", "bench")

TOP_LEVEL = "(top-level modules)"

# The doc that owns each app package, relative to crooks-assistant/, with an optional note;
# None where no document is about it, which the map then says plainly. A package missing from
# here stops the run, so a new package cannot slip onto the map without a decision about it.
OWNER_DOCS: dict[str, tuple[str, str | None] | None] = {
    TOP_LEVEL: None,
    "actions": ("docs/product-memory/DECISIONS.md", "DEC-005–007"),
    "analytics": None,
    "anticipation": None,
    "builds": None,
    "capabilities": None,
    "clients": ("docs/DEPLOY_LINUX.md", "their keys"),
    "connections": ("docs/CONNECTIONS.md", None),
    "context": None,
    "customers": None,
    "digest": ("docs/product-memory/KNOWLEDGE_DIGESTER_V1.md", None),
    "displays": None,
    "engineering_bridge": ("docs/product-memory/REMOTE_ENGINEERING_CONTROL_V1.md", None),
    "families": None,
    "kb": ("docs/product-memory/OWNER_DECISIONS_2026-10-01.md", "the voice spec"),
    "logging": None,
    "memory": None,
    "objectives": None,
    "observability": ("docs/RECORDING.md", None),
    "orchestrator": ("docs/product-memory/ENGINEERING_DISPATCHER_V1.md", None),
    "people": ("docs/TEAM.md", None),
    "providers": None,
    "reads": None,
    "release": ("docs/RELEASE_SERVICE.md", None),
    "remote_engineering": ("docs/product-memory/REMOTE_ENGINEERING_CONTROL_V1.md", None),
    "returns": None,
    "routes": None,
    "scenes": ("docs/product-memory/GENERATIVE_UI_V1.md", None),
    "secrets": ("docs/DEPLOY_LINUX.md", None),
    "session": None,
    "shipping": None,
    "skills": ("docs/product-memory/SOURCE_ASSIMILATION_V1.md", None),
    "speech": None,
    "support": ("docs/product-memory/SUPPORT_INVESTIGATOR_V1.md", None),
    "tools": ("docs/phase4/TOOL_MATRIX.md", None),
    "work": ("docs/TEAM.md", None),
}

# A package the running app loads but that does nothing unless a switch is on. The switch's
# value is read (production as recorded, else the template, else the code's default), never
# assumed here.
SWITCHED_PACKAGES = {"scenes": "CLIVE_SCENES"}

# Every file CLIVE writes: (what it is, the file as the code names it, the module that writes it,
# the switch that turns it on or None, and proofs). Each proof is (a file, a literal it must hold):
# the writer's own mark, and the file's name where the path is handed to the writer (runtime.py).
STORES: tuple[tuple[str, str, str, str | None, tuple[tuple[str, str], ...]], ...] = (
    ("Objectives", "obj_*.json", "app/objectives/store.py", None, (("app/objectives/store.py", "obj_"),)),
    ("Capability gaps", "gaps.json", "app/objectives/gaps.py", None, (("app/runtime.py", '"gaps.json"'),)),
    ("Screens", "displays.json", "app/displays/store.py", None, (("app/displays/store.py", '"displays.json"'),)),
    ("Instagram token state", "instagram.json", "app/clients/instagram.py", None,
     (("app/runtime.py", '"instagram.json"'), ("app/clients/instagram.py", "def _save_state"))),
    ("People cards", "people.json", "app/people/store.py", None, (("app/runtime.py", '"people.json"'),)),
    ("Work list", "work/items/, routines.json, record.jsonl", "app/work/store.py", None,
     (("app/work/store.py", '"record.jsonl"'), ("app/work/store.py", '"routines.json"'))),
    ("Team access", "access.json", "app/people/access.py", None, (("app/people/access.py", '"access.json"'),)),
    ("Passkeys", "passkeys.json", "app/connections/passkeys.py", None,
     (("app/connections/passkeys.py", '"passkeys.json"'),)),
    ("Connections ledger", "changes.jsonl", "app/connections/ledger.py", None,
     (("app/connections/ledger.py", '"changes.jsonl"'),)),
    ("Voice choice", "voice.json", "app/speech/voice_prefs.py", None, (("app/speech/voice_prefs.py", '"voice.json"'),)),
    ("Action audit", "actions.jsonl", "app/actions/ledger.py", None, (("app/actions/ledger.py", '"actions.jsonl"'),)),
    ("Owner judgments", "owner-judgments.jsonl", "app/builds/decisions.py", None,
     (("app/builds/decisions.py", '"owner-judgments.jsonl"'),)),
    ("Interaction record", "logs/interactions/", "app/observability/interactions.py", "CROOKS_INTERACTION_RECORD",
     (("app/observability/interactions.py", '"interactions"'),)),
    ("Test sessions", "logs/test-sessions/", "app/observability/session.py", "CROOKS_TEST_SESSION_ALWAYS",
     (("app/observability/session.py", '"test-sessions"'),)),
    ("Experience recordings", "logs/experience-recordings/", "app/observability/recorder.py",
     "CROOKS_RECORD_EXPERIENCE", (("app/observability/recorder.py", '"experience-recordings"'),)),
    ("Turn log", "logs/turns.jsonl", "app/logging/turnlog.py", None, (("app/logging/turnlog.py", '"turns.jsonl"'),)),
    ("Capability manifest", "capabilities.json", "app/capabilities/delta.py", None,
     (("app/capabilities/delta.py", '"capabilities.json"'),)),
    ("Anticipation", "anticipation/transitions.json", "app/anticipation/learning.py", None,
     (("app/anticipation/learning.py", '"transitions.json"'),)),
    ("Keys stored from the app", "<secret dir>/app/<key>.cred", "app/secrets/vault.py", None,
     (("app/secrets/vault.py", '".cred"'),)),
    ("Digest store", "one folder per artifact", "app/digest/store.py", None, (("app/digest/store.py", "units.jsonl"),)),
    # Written by the release service on the server (/var/lib/clive-release), not by the running app.
    ("Release service", "status.json, deploys/, failed/, HALT", "app/release/state.py", "CLIVE_RELEASE_ENABLED",
     (("app/release/state.py", '"status.json"'), ("app/release/state.py", '"HALT"'))),
)

# Read first: what a new session was pointed at before this map (at BEFORE_REF), and now.
BEFORE_REF = "b33ccbc2"
DOCTRINE = (
    "PRODUCT_BRAIN", "CLIVE_INTENT_TO_EXECUTION_PHILOSOPHY",
    "CLIVE_ADAPTATION_AND_ORGANISATIONAL_INTELLIGENCE", "CLIVE_IDENTITY_AND_HOME_SURFACE",
    "CONTINUOUS_PRODUCT_EVALUATION_AND_DYNAMIC_UI", "EVOLUTION_POLICY", "GENERATIVE_UI_V1",
    "DIRECTOR_PROTOCOL", "CLIVE_SELF_KNOWLEDGE",
)
MEMORY = "crooks-assistant/docs/product-memory"
READ_FIRST_BEFORE = (
    "README.md", "crooks-assistant/README.md", f"{MEMORY}/CURRENT_TRUTH.md", f"{MEMORY}/DECISIONS.md",
    *(f"{MEMORY}/{name}.md" for name in DOCTRINE),
)
READ_FIRST_AFTER = ("CLAUDE.md", "crooks-assistant/MAP.md", f"{MEMORY}/CURRENT_TRUTH.md")

SECTIONS = ("live", "parts", "pages", "stores", "switches", "words")


class MapError(Exception):
    """Something the map would have to guess. Said, never printed as a row."""


# --- the import graph ------------------------------------------------------------------------


@dataclass(frozen=True)
class Module:
    name: str
    path: Path
    is_package: bool


def _modules() -> dict[str, Module]:
    found: dict[str, Module] = {}
    for top in SOURCE_DIRS:
        for path in sorted((ROOT / top).rglob("*.py")):
            parts = list(path.relative_to(ROOT).with_suffix("").parts)
            is_package = parts[-1] == "__init__"
            if is_package:
                parts = parts[:-1]
            found[".".join(parts)] = Module(".".join(parts), path, is_package)
    return found


def _parents(name: str) -> list[str]:
    parts = name.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts))]


def _resolve_from(module: Module, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    package = module.name if module.is_package else module.name.rpartition(".")[0]
    for _ in range(node.level - 1):
        package = package.rpartition(".")[0]
    return f"{package}.{node.module}" if node.module else package


def _imports(module: Module, known: dict[str, Module]) -> set[str]:
    """Every known module this one imports, anywhere in its body, plus what it loads by name."""
    source = module.path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module.path))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = _resolve_from(module, node)
            targets.add(base)
            targets.update(f"{base}.{alias.name}" for alias in node.names)
    if module.name.startswith("scripts."):   # a script imports its siblings by their bare name
        targets |= {f"scripts.{name}" for name in list(targets)}
    if "iter_modules" in source:              # families/__init__, digest's intakes and adapters
        packages = {node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in known}
        if "__path__" in source and module.is_package:
            packages.add(module.name)
        for package in packages:
            targets |= {name for name in known if name.rpartition(".")[0] == package}
    out: set[str] = set()
    for target in targets:
        for name in (*_parents(target), target):
            if name in known:
                out.add(name)
    out.discard(module.name)
    return out


def _reach(roots: list[str], graph: dict[str, set[str]]) -> set[str]:
    seen = set(roots)
    queue = deque(roots)
    while queue:
        for name in graph.get(queue.popleft(), ()):
            if name not in seen:
                seen.add(name)
                queue.append(name)
    return seen


def import_graph() -> tuple[dict[str, Module], set[str], set[str]]:
    """The known modules, those the running app loads (from app.main), and those a script loads."""
    known = _modules()
    graph = {name: _imports(module, known) for name, module in known.items()}
    live = _reach(["app.main"], graph)
    cli = _reach([name for name in known if name.startswith("scripts.")], graph)
    return known, live, cli


# --- settings, the template and the deploy records ------------------------------------------


@dataclass(frozen=True)
class Switch:
    env: str
    default: str


def _is_settings_class(node: ast.ClassDef) -> bool:
    return any(isinstance(base, ast.Name) and base.id == "BaseSettings" for base in node.bases)


def _env_prefix(node: ast.ClassDef) -> str:
    for item in node.body:
        if isinstance(item, ast.Assign) and any(getattr(t, "id", "") == "model_config" for t in item.targets):
            for keyword in getattr(item.value, "keywords", []):
                if keyword.arg == "env_prefix" and isinstance(keyword.value, ast.Constant):
                    return str(keyword.value.value)
    raise MapError(f"settings class {node.name} has no env_prefix")


def switches() -> list[Switch]:
    """Every on/off setting: a bool field of a BaseSettings class, or a name whose default is "off"."""
    found: list[Switch] = []
    for path in [SETTINGS, *sorted(APP.rglob("*.py"))]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.ClassDef) and _is_settings_class(node)):
                continue
            prefix = _env_prefix(node)
            for item in node.body:
                if not (isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)):
                    continue
                kind = getattr(item.annotation, "id", "")
                value = getattr(item.value, "value", None)
                if kind == "bool":
                    found.append(Switch(f"{prefix}{item.target.id}".upper(), "on" if value else "off"))
                elif kind == "str" and value == "off":
                    found.append(Switch(f"{prefix}{item.target.id}".upper(), "off"))
    return sorted(found, key=lambda switch: switch.env)


def template_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in TEMPLATE.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^(#\s*)?([A-Z][A-Z0-9_]+)=(.*)$", line.strip())
        if match and match.group(2) not in values:
            values[match.group(2)] = "unset" if match.group(1) else (match.group(3).strip() or "empty")
    return values


@dataclass(frozen=True)
class Deploy:
    sha: str
    when: str           # "2026-10-03 17:48"
    path: Path

    @property
    def link(self) -> str:
        return f"[`reports/{self.path.name}`](reports/{self.path.name})"


_MONTHS = {name: number for number, name in enumerate(
    ("January", "February", "March", "April", "May", "June", "July", "August", "September",
     "October", "November", "December"), start=1)}
_ISO_WHEN = re.compile(r"(\d{4})-(\d{2})-(\d{2})[^\n]*?\b(\d{2}):(\d{2})")
_LONG_WHEN = re.compile(r"\b(\d{1,2}) (" + "|".join(_MONTHS) + r") (\d{4})[^\n]*?\b(\d{2}):(\d{2})")
_WORDISH = re.compile(r"[^\W_]")
_SWITCH_LINE = re.compile(r"^ {4}((?:CROOKS|CLIVE)_[A-Z0-9_]+)(?:=(\S+)| +(unset))\s*$")
_UNTOUCHED = re.compile(r"(?i)switch[^\n]{0,60}untouched")


def _when(text: str, path: Path) -> str:
    found = []
    iso = _ISO_WHEN.search(text)
    if iso:
        found.append((iso.start(), f"{iso[1]}-{iso[2]}-{iso[3]} {iso[4]}:{iso[5]}"))
    long = _LONG_WHEN.search(text)
    if long:
        found.append((long.start(), f"{long[3]}-{_MONTHS[long[2]]:02d}-{int(long[1]):02d} {long[4]}:{long[5]}"))
    if not found:
        raise MapError(f"{path.name} says no deploy date and time")
    return min(found)[1]


def deploys() -> list[Deploy]:
    """The deploy records, newest first. The SHA is the file's name; the time is the first one it states."""
    records = []
    for path in sorted(REPORTS.glob("deploy-*.md")):
        match = re.fullmatch(r"deploy-([0-9a-f]{8})\.md", path.name)
        if match:
            records.append(Deploy(match[1], _when(path.read_text(encoding="utf-8"), path), path))
    if not records:
        raise MapError("no deploy record in reports/")
    return sorted(records, key=lambda deploy: deploy.when, reverse=True)


def recorded_switches(records: list[Deploy]) -> tuple[dict[str, str], Deploy | None, list[Deploy]]:
    """Production's switches from the newest record that lists them, and the later records that say
    they left them untouched."""
    for index, record in enumerate(records):
        values = {}
        for line in record.path.read_text(encoding="utf-8").splitlines():
            match = _SWITCH_LINE.match(line)
            if match:
                values[match[1]] = match[2] or match[3]
        if values:
            later = [r for r in records[:index] if _UNTOUCHED.search(r.path.read_text(encoding="utf-8"))]
            return values, record, later
    return {}, None, []


# --- the sections ----------------------------------------------------------------------------


def _lines(paths: list[Path]) -> int:
    return sum(path.read_text(encoding="utf-8").count("\n") for path in paths)


def _value_word(value: str | None) -> str:
    return {"true": "on", "false": "off"}.get(value or "", value or "")


def _switch_value(env: str, production: dict[str, str], template: dict[str, str], default: str) -> tuple[str, str]:
    if env in production:
        return _value_word(production[env]), "production"
    if env in template:
        return _value_word(template[env]), "template"
    return default, "default"


def section_live(records: list[Deploy]) -> str:
    newest, *before = records
    matrix = next((line for line in TOOL_MATRIX.read_text(encoding="utf-8").splitlines()
                   if re.match(r"^\d+ tools — ", line)), None)
    if matrix is None:
        raise MapError("TOOL_MATRIX.md has no 'N tools — …' line")
    earlier = "; ".join(f"`{r.sha}` {r.when} UTC ({r.link})" for r in before)
    return "\n".join([
        f"**Production:** `{newest.sha}`, deployed {newest.when} UTC ({newest.link}). "
        f"**Before it:** {earlier}.",
        f"**Tools:** {matrix.rstrip('.')} ([`TOOL_MATRIX.md`](docs/phase4/TOOL_MATRIX.md)).",
    ])


def _packages() -> dict[str, list[Path]]:
    groups: dict[str, list[Path]] = {TOP_LEVEL: sorted(APP.glob("*.py"))}
    for directory in sorted(p for p in APP.iterdir() if p.is_dir() and p.name != "__pycache__"):
        files = sorted(directory.rglob("*.py"))
        if files:
            groups[directory.name] = files
    return groups


def _owner_doc(package: str) -> str:
    if package not in OWNER_DOCS:
        raise MapError(f"app/{package} has no OWNER_DOCS row: add one (None when no document owns it)")
    entry = OWNER_DOCS[package]
    if entry is None:
        return "none"
    doc, note = entry
    if not (ROOT / doc).is_file():
        raise MapError(f"the owner doc of app/{package}, {doc}, does not exist")
    text = f"[`{Path(doc).name}`]({doc})"
    return f"{text} {note}" if note else text


def section_parts(known: dict[str, Module], live: set[str], cli: set[str], switch_value) -> str:
    rows = ["| Package | Lines | State | Not loaded by the app | Owner doc |", "|---|---:|---|---|---|"]
    by_path = {module.path: name for name, module in known.items()}
    for package, files in _packages().items():
        names = [by_path[path] for path in files]
        loaded = [name for name in names if name in live]
        if loaded:
            state = "live"
        elif any(name in cli for name in names):
            state = "CLI"
        else:
            state = "not loaded"
        if package in SWITCHED_PACKAGES:
            env = SWITCHED_PACKAGES[package]
            value, where = switch_value(env)
            if value != "on":
                state = f"off (`{env}` {value}, {where})"
        missing = sorted(name.rpartition(".")[2] for name in names if name not in live)
        if not loaded or not missing:
            gaps = "—" if loaded else "all"
        elif len(missing) <= 3:
            gaps = ", ".join(f"`{name}`" for name in missing)
        else:
            gaps = f"{len(missing)} modules"
        label = TOP_LEVEL if package == TOP_LEVEL else f"`{package}`"
        rows.append(f"| {label} | {_lines(files):,} | {state} | {gaps} | {_owner_doc(package)} |")
    return "\n".join(rows)


def _route(page: str) -> str:
    for path in sorted(APP.rglob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        for index, line in enumerate(lines):
            if f'"{page}"' not in line:
                continue
            for above in reversed(lines[:index]):
                match = re.search(r"@\w+\.get\(\"([^\"]+)\"", above)
                if match:
                    return f"`{match[1]}`"
    return f"no route (only `/static/{page}`)"


def section_pages() -> str:
    rows = ["| Address | Page | Scripts it loads |", "|---|---|---|"]
    for page in sorted(WEB.glob("*.html")):
        scripts = re.findall(r"<script[^>]*\bsrc=\"/static/([^\"?]+)", page.read_text(encoding="utf-8"))
        listed = ", ".join(scripts) if scripts else "none"
        rows.append(f"| {_route(page.name)} | `{page.name}` | {len(scripts)}: {listed} |")
    return "\n".join(rows)


def section_stores(live: set[str], cli: set[str], switch_value) -> str:
    rows = ["| Store | File | Written by | On |", "|---|---|---|---|"]
    for store, file, writer, switch, proofs in STORES:
        if not (ROOT / writer).is_file():
            raise MapError(f"the writer of {store}, {writer}, does not exist")
        for proof_file, literal in proofs:
            path = ROOT / proof_file
            if not path.is_file() or literal not in path.read_text(encoding="utf-8"):
                raise MapError(f"{proof_file} no longer holds {literal!r}, so the {store} row cannot be stated")
        module = ".".join(Path(writer).with_suffix("").parts)
        if switch:
            value, where = switch_value(switch)
            state = f"`{switch}` {value} ({where})"
        elif module in live:
            state = "always"
        elif module in cli:
            state = "CLI only"
        else:
            state = "not loaded"
        rows.append(f"| {store} | `{file}` | `{writer.removeprefix('app/')}` | {state} |")
    return "\n".join(rows)


def section_switches(production: dict[str, str], record: Deploy | None, later: list[Deploy],
                     template: dict[str, str]) -> str:
    if record is None:
        note = "No deploy record lists production's switches."
    else:
        note = f"Production is as recorded by {record.link} ({record.when} UTC)"
        if later:
            note += "; " + ", ".join(f"`{r.sha}`" for r in later) + " left the switches untouched"
        note += ". \"not recorded\" means no record says."
    rows = [note, "", "| Switch | Code default | Template | Production |", "|---|---|---|---|"]
    for switch in switches():
        shown = template.get(switch.env, "absent")
        prod = production.get(switch.env)
        rows.append(f"| `{switch.env}` | {switch.default} | {_value_word(shown)} | "
                    f"{_value_word(prod) if prod else 'not recorded'} |")
    return "\n".join(rows)


def _words(text: str) -> int:
    """Words: whitespace-separated tokens holding a letter or a digit, so a table's pipes and
    rules, an arrow or a dash standing alone, are not counted as words."""
    return sum(1 for token in text.split() if _WORDISH.search(token))


def _text_at(ref: str, rel: str) -> str:
    done = subprocess.run(["git", "-C", str(REPO), "show", f"{ref}:{rel}"], capture_output=True, text=True)
    if done.returncode != 0:
        raise MapError(f"cannot read {rel} at {ref}: {done.stderr.strip()}")
    return done.stdout


def _words_sentence(before: int, after: int) -> str:
    """The footer. It has the same number of words whatever the two numbers are."""
    return (
        f"**Read first, before → after: {before:,} → {after:,} words** (a word is a "
        f"whitespace-separated token with a letter or digit in it, so table pipes do not count). "
        f"Before, at `{BEFORE_REF}`: both READMEs, "
        f"CURRENT_TRUTH, DECISIONS and the {len(DOCTRINE)} doctrine documents of DEC-039's start "
        f"set (listed in `scripts/map.py`). After: `CLAUDE.md`, this map and CURRENT_TRUTH."
    )


def section_words(map_text: str) -> str:
    before = sum(_words(_text_at(BEFORE_REF, rel)) for rel in READ_FIRST_BEFORE)
    after = 0
    for rel in READ_FIRST_AFTER:
        if rel == "crooks-assistant/MAP.md":
            after += _words(map_text)
        else:
            path = REPO / rel
            if not path.is_file():
                raise MapError(f"{rel} is on the read-first list but does not exist")
            after += _words(path.read_text(encoding="utf-8"))
    return _words_sentence(before, after)


# --- writing ---------------------------------------------------------------------------------


def _replace(text: str, name: str, body: str) -> str:
    start, end = f"<!-- map:{name} -->", f"<!-- /map:{name} -->"
    if text.count(start) != 1 or text.count(end) != 1 or text.index(start) > text.index(end):
        raise MapError(f"MAP.md must hold exactly one {start} … {end} pair")
    head, rest = text.split(start, 1)
    _, tail = rest.split(end, 1)
    return f"{head}{start}\n{body}\n{end}{tail}"


def render(current: str) -> str:
    known, live, cli = import_graph()
    records = deploys()
    production, record, later = recorded_switches(records)
    template = template_values()
    defaults = {switch.env: switch.default for switch in switches()}

    def switch_value(env: str) -> tuple[str, str]:
        if env not in defaults:
            raise MapError(f"{env} is not a setting the code reads")
        return _switch_value(env, production, template, defaults[env])

    text = current
    text = _replace(text, "live", section_live(records))
    text = _replace(text, "parts", section_parts(known, live, cli, switch_value))
    text = _replace(text, "pages", section_pages())
    text = _replace(text, "stores", section_stores(live, cli, switch_value))
    text = _replace(text, "switches", section_switches(production, record, later, template))
    # The count includes this map, so it is taken with the count's own sentence in place: the
    # sentence has the same number of words whatever the numbers in it are.
    text = _replace(text, "words", section_words(_replace(text, "words", _words_sentence(0, 0))))
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="change nothing; exit 1 if MAP.md is stale")
    args = parser.parse_args(argv)
    current = MAP.read_text(encoding="utf-8")
    try:
        wanted = render(current)
    except MapError as exc:
        print(f"map: {exc}", file=sys.stderr)
        return 2
    if args.check:
        stale = [name for name in SECTIONS if _section(current, name) != _section(wanted, name)]
        if stale:
            print(f"map: MAP.md is stale in {', '.join(stale)}; run python scripts/map.py", file=sys.stderr)
            return 1
        print("map: MAP.md is current")
        return 0
    if wanted != current:
        MAP.write_text(wanted, encoding="utf-8")
        print("map: MAP.md rewritten")
    else:
        print("map: MAP.md already current")
    return 0


def _section(text: str, name: str) -> str:
    start, end = f"<!-- map:{name} -->", f"<!-- /map:{name} -->"
    return text.split(start, 1)[1].split(end, 1)[0] if start in text and end in text else ""


if __name__ == "__main__":
    sys.exit(main())
