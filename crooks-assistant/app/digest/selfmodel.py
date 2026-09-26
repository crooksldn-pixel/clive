"""CLIVE's self-model: what CLIVE already has, generated from the things that decide it.

The Knowledge Digester relates what it reads to what CLIVE already is (KNOWLEDGE_DIGESTER_V1.md
section 5). That picture is generated here, never kept by hand, so it cannot drift from the
code:

    tool              every tool in the registry (app/tools/registry.py), loaded the way the
                      tool matrix loads it (experience/tool_matrix.py), with whether it reads
                      or writes. The diagnostic mock_ tools are left out, as the runtime's own
                      lists leave them out.
    intent_family     every intent family the fast lane routes (app/fastpath/intent.py, with
                      those app/families adds), with its signals and its recipe's reads
    scene_primitive   the Generative UI scene elements a plan may use (app/scenes/scene.py)
    review_check      every acceptance gate (the gate_* functions of
                      scripts/acceptance_provenance.py, read as source and never run): the
                      automated checks every candidate passes
    design_token      the Generative UI's tokens (the :root custom properties of
                      web/style.css), one entry per family (--bg-*, --glass-*, --radius-*, ...)
    builder_skill     every SKILL.md one level under a skills directory (.claude/skills or
                      skills, at the repository root or beside the app), if there is one
    absorption        every absorption the owner has decided to take (from a digest store's
                      ledger, when one is given): what the digester has already added
    feature           the FEAT-nnn rows of docs/product-memory/FEATURES.md, with their status
    idea              the IDEA-nnn headings of docs/product-memory/IDEAS.md, with their status
    decision          the DEC-nnn headings of docs/product-memory/DECISIONS.md, with their
                      status: why CLIVE is as it is, for the why-index

The registries can only be read by importing CLIVE's own code — importing is what runs their
decorators — which is CLIVE reading itself, not an artifact's content. They are read only when
the running code is the repository's own; otherwise they are left out and `sources` says so.
The documents, gates, tokens and skills are read as text and never executed.

Nothing is cut silently: a document read only in part is read to its last whole line and its
source says so, and so does a skills directory with more skills than are read.

The entries are ordered by kind and key, and the model carries a digest of them, so a relation
can cite exactly which self-model it was made against."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

SELF_KINDS = (
    "tool", "intent_family", "scene_primitive", "review_check", "design_token", "builder_skill",
    "absorption", "feature", "idea", "decision",
)
# What CLIVE has now, whatever else is said of it; a feature has it only once shipped or testing.
PRESENT_KINDS = frozenset(
    ("tool", "intent_family", "scene_primitive", "review_check", "design_token", "builder_skill",
     "absorption")
)
# The product memory: what CLIVE plans, has thought of and decided — what the why-index traces to.
MEMORY_KINDS = ("feature", "idea", "decision")
REGISTRY_SOURCES = ("tool registry", "intent families", "scene primitives")
ACCESS = ("read", "write")

MAX_NAME = 200
MAX_DESCRIPTION = 1_200
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024   # FEATURES.md and IDEAS.md, each
MAX_SKILL_BYTES = 64 * 1024            # the head of a SKILL.md: its front matter is at the top
MAX_SKILLS = 500                       # skill folders looked at, in all skills directories
MAX_FRONT_MATTER_LINES = 200
MAX_SOURCE_BYTES = 512 * 1024          # the acceptance script and the token sheet, each
MAX_ABSORPTIONS = 2_000                # decided absorptions read from a ledger

PRODUCT_MEMORY = Path("docs") / "product-memory"
FEATURES_FILE = "FEATURES.md"
IDEAS_FILE = "IDEAS.md"
DECISIONS_FILE = "DECISIONS.md"
GATES_FILE = Path("scripts") / "acceptance_provenance.py"
TOKEN_SHEET = Path("web") / "style.css"
SKILL_DIRECTORIES = (Path(".claude") / "skills", Path("skills"))
APP_DIRECTORY = "crooks-assistant"     # where the app lives inside the git repository

_FEATURE_ID = re.compile(r"^FEAT-\d{3,}$")
_IDEA_HEADING = re.compile(r"^##\s+(IDEA-\d{3,})\s*[—–-]+\s*(.+?)\s*$")
_DECISION_HEADING = re.compile(r"^##\s+(DEC-\d{3,})\s*[—–-]+\s*(.+?)\s*$")
_ROOT_BLOCK = re.compile(r":root\s*\{")
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_CUSTOM_PROPERTY = re.compile(r"--([A-Za-z][\w-]*)\s*:\s*([^;{}]{1,200});")
_HEADING = re.compile(r"^#{1,2}\s")
_META = re.compile(r"^\*\*([A-Za-z][A-Za-z ]*):\*\*\s*(.*?)\s*$")
_SPACE = re.compile(r"\s+")
_STATUS = re.compile(r"^[A-Z][A-Z /]*[A-Z]")


def _one_line(text: Any, limit: int) -> str:
    text = _SPACE.sub(" ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _status(text: str) -> str | None:
    """The status word or words a register row opens with — "CAPTURED", "SHIPPED / HARDENING",
    "APPROVED DIRECTION" — without the note that may follow them."""
    match = _STATUS.match(_one_line(text, MAX_NAME))
    return match.group(0).strip() if match else None


@dataclass(frozen=True)
class SelfEntry:
    """One thing CLIVE has, planned or thought of. `access` is set for a tool only; `status`
    for a feature or an idea only; `origin` says where the entry was read from."""

    key: str
    kind: str
    name: str
    description: str
    origin: str
    access: str | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in SELF_KINDS:
            raise ValueError(f"self-model kind must be one of {SELF_KINDS}, not {self.kind!r}")
        for name, value in (("key", self.key), ("name", self.name), ("origin", self.origin)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"self-model entry {name} must be a non-empty string")
        if not self.key.startswith(f"{self.kind}:"):
            raise ValueError(f"self-model key {self.key!r} must start with {self.kind!r}")
        if not isinstance(self.description, str):
            raise ValueError("self-model entry description must be a string")
        if (self.kind == "tool") != (self.access is not None):
            raise ValueError("a tool says whether it reads or writes, and nothing else does")
        if self.access is not None and self.access not in ACCESS:
            raise ValueError(f"tool access must be one of {ACCESS}, not {self.access!r}")
        if self.status is not None and self.kind not in MEMORY_KINDS:
            raise ValueError("only a feature, an idea or a decision has a status")

    @property
    def present(self) -> bool:
        """Whether CLIVE has this now, rather than plans, imagines or decided it: every tool,
        intent family, scene primitive, review check, design token family, builder skill and
        absorption, and a feature that has shipped or is merged and testing. An idea or a
        decision is never something CLIVE has."""
        if self.kind in PRESENT_KINDS:
            return True
        if self.kind == "feature" and self.status:
            return self.status.upper().startswith(("SHIPPED", "TESTING"))
        return False

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "kind": self.kind,
            "name": self.name,
            "description": self.description,
            "origin": self.origin,
            "access": self.access,
            "status": self.status,
        }


@dataclass(frozen=True)
class SelfSource:
    """Where part of the self-model was read from, how many entries it gave, and anything the
    reader could not do there."""

    name: str
    where: str
    entries: int
    note: str = ""

    def to_dict(self) -> dict:
        return {"name": self.name, "where": self.where, "entries": self.entries, "note": self.note}


@dataclass(frozen=True)
class SelfModel:
    """What CLIVE has, planned and thought of, ordered by kind and key, with where each part
    was read from. `digest` names exactly this self-model."""

    entries: tuple[SelfEntry, ...]
    sources: tuple[SelfSource, ...] = ()

    def __post_init__(self) -> None:
        if not all(isinstance(entry, SelfEntry) for entry in self.entries):
            raise ValueError("a self-model is made of SelfEntry records")
        entries = tuple(sorted(self.entries, key=_order))
        keys = [entry.key for entry in entries]
        if len(set(keys)) != len(keys):
            raise ValueError("self-model keys must be unique")
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "sources", tuple(self.sources))

    @property
    def digest(self) -> str:
        """sha256 of the entries in their canonical form: the same CLIVE, the same digest."""
        canonical = json.dumps(
            [entry.to_dict() for entry in self.entries],
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )
        return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get(self, key: str) -> SelfEntry | None:
        for entry in self.entries:
            if entry.key == key:
                return entry
        return None

    def of_kind(self, kind: str) -> tuple[SelfEntry, ...]:
        return tuple(entry for entry in self.entries if entry.kind == kind)

    def counts(self) -> dict[str, int]:
        return {kind: len(self.of_kind(kind)) for kind in SELF_KINDS}

    @property
    def unread(self) -> tuple[str, ...]:
        """The registries this self-model could not read. Relating against it cannot tell
        whether CLIVE has a tool, an intent family or a scene primitive: a unit that seems to
        be missing from it may be there."""
        return tuple(source.name for source in self.sources
                     if source.name in REGISTRY_SOURCES and not source.entries
                     and source.note.startswith("not read"))

    def to_dict(self) -> dict:
        return {
            "digest": self.digest,
            "counts": self.counts(),
            "entries": [entry.to_dict() for entry in self.entries],
            "sources": [source.to_dict() for source in self.sources],
        }


def _order(entry: SelfEntry) -> tuple[int, str]:
    return (SELF_KINDS.index(entry.kind), entry.key)


# --- where things are ------------------------------------------------------------------------


def _roots(repo_root: Path) -> tuple[Path, Path | None]:
    """The repository root and the folder holding the app package. Given the app directory
    inside the repository, the repository is its parent, so that either path gives the same
    self-model."""
    if repo_root.name == APP_DIRECTORY and (repo_root / "app").is_dir():
        return repo_root.parent, repo_root
    for candidate in (repo_root / APP_DIRECTORY, repo_root):
        if (candidate / "app").is_dir():
            return repo_root, candidate
    return repo_root, None


def _running_code_is(app_root: Path | None) -> bool:
    """Whether the code that would be imported to read the registries is this repository's:
    the app package, and the experience package the tool matrix is loaded from."""
    if app_root is None:
        return False
    import app

    if Path(app.__file__).resolve().parent != (app_root / "app").resolve():
        return False
    try:
        import experience
    except ImportError:
        return False
    location = getattr(experience, "__file__", None) or next(iter(getattr(experience, "__path__", [])), "")
    folder = Path(location).resolve()
    folder = folder.parent if folder.is_file() or folder.suffix == ".py" else folder
    return folder == (app_root / "experience").resolve()


def _relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


# --- the registries, read as the app reads them ----------------------------------------------


def _tools() -> list[SelfEntry]:
    from experience import tool_matrix

    tool_matrix.load()
    from app.tools import registry

    entries = []
    for spec in registry.all_specs():
        if spec.name.startswith("mock_"):
            continue
        writes = spec.write is not None or spec.batch is not None
        module = getattr(spec.handler, "__module__", None) or "app.tools.registry"
        entries.append(SelfEntry(
            key=f"tool:{spec.name}", kind="tool", name=spec.name,
            description=_one_line(spec.description, MAX_DESCRIPTION),
            origin=f"tool registry ({module})", access="write" if writes else "read",
        ))
    return entries


def _families() -> list[SelfEntry]:
    from experience import tool_matrix

    tool_matrix.load()
    from app.fastpath.intent import all_families
    from app.fastpath.recipes import recipe_for

    entries = []
    for family in all_families():
        recipe = recipe_for(family.name)
        parts = [f"{family.kind} intent {family.name.replace('_', ' ')}"]
        if family.needs:
            parts.append("needs " + ", ".join(family.needs))
        if family.boosts:
            parts.append("boosted by " + ", ".join(family.boosts))
        if family.entities:
            parts.append("resolves " + ", ".join(family.entities))
        if recipe is not None:
            reads = ", ".join(recipe.read_primitives) or "nothing"
            parts.append(f"answered by recipe {recipe.recipe_id} reading {reads}")
        else:
            parts.append("answered by the model")
        entries.append(SelfEntry(
            key=f"intent_family:{family.name}", kind="intent_family", name=family.name,
            description=_one_line("; ".join(parts), MAX_DESCRIPTION),
            origin="intent families (app.fastpath.intent)",
        ))
    return entries


def _scene_primitives() -> list[SelfEntry]:
    import inspect

    from app.scenes.scene import Answer, Element

    union = get_args(Element)[0]
    entries = []
    for element in (Answer, *get_args(union)):
        name = element.model_fields["type"].default
        fields = [f for f in element.model_fields if f not in ("type", "justification")]
        doc = inspect.cleandoc(element.__doc__ or "")
        description = f"{doc} Fields: {', '.join(fields)}." if fields else doc
        entries.append(SelfEntry(
            key=f"scene_primitive:{name}", kind="scene_primitive", name=name,
            description=_one_line(description, MAX_DESCRIPTION),
            origin="Generative UI scene plan (app.scenes.scene)",
        ))
    return entries


# --- product memory, read as text ------------------------------------------------------------


def _read_text(path: Path, limit: int) -> tuple[str, str]:
    """The file's text up to limit bytes — ended at its last whole line when it is longer, so
    no row is ever cut in two — and a note saying so when it is; "" when it was read whole."""
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) <= limit:
        return data.decode("utf-8", errors="replace"), ""
    data = data[:limit]
    whole = data[: data.rfind(b"\n") + 1]
    return whole.decode("utf-8", errors="replace"), (
        f"only its first {len(whole)} bytes (to the last whole line within {limit}) were read: "
        "what follows is not in the model"
    )


def _features(text: str, origin: str) -> list[SelfEntry]:
    entries: list[SelfEntry] = []
    for line in text.split("\n"):
        if not line.startswith("| FEAT-"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3 or not _FEATURE_ID.match(cells[0]) or not cells[1]:
            continue
        feature_id, name, status = cells[0], cells[1], cells[2]
        phase = cells[3] if len(cells) > 3 else ""
        notes = "|".join(cells[4:]).strip()
        description = f"{notes} Phase: {phase}." if phase else notes
        entries.append(SelfEntry(
            key=f"feature:{feature_id}", kind="feature", name=_one_line(name, MAX_NAME),
            description=_one_line(description, MAX_DESCRIPTION), origin=origin,
            status=_status(status),
        ))
    return entries


def _ideas(text: str, origin: str) -> list[SelfEntry]:
    return _headed(text, origin, _IDEA_HEADING, "idea")


def _decisions(text: str, origin: str) -> list[SelfEntry]:
    return _headed(text, origin, _DECISION_HEADING, "decision")


def _headed(text: str, origin: str, pattern: re.Pattern[str], kind: str) -> list[SelfEntry]:
    """Entries headed "## ID — title" with **Field:** lines (status, theme) and a body."""
    entries: list[SelfEntry] = []
    current: tuple[str, str] | None = None
    meta: dict[str, str] = {}
    body: list[str] = []

    def close() -> None:
        if current is None:
            return
        entry_id, title = current
        status = _status(meta.get("status", ""))
        words = " ".join(line for line in body if line and line != "---")
        theme = meta.get("theme", "")
        description = f"Theme: {theme}. {words}" if theme else words
        entries.append(SelfEntry(
            key=f"{kind}:{entry_id}", kind=kind, name=_one_line(title, MAX_NAME),
            description=_one_line(description, MAX_DESCRIPTION), origin=origin,
            status=status,
        ))

    for raw in text.split("\n"):
        line = raw.strip()
        heading = pattern.match(line)
        if heading or _HEADING.match(line):
            close()
            current, meta, body = (heading.group(1), heading.group(2)) if heading else None, {}, []
            continue
        if current is None:
            continue
        field = _META.match(line)
        if field:
            meta[field.group(1).strip().lower()] = field.group(2)
        else:
            body.append(line)
    close()
    return entries


# --- builder skills, read as text ------------------------------------------------------------


def _front_matter(text: str) -> dict[str, str]:
    """The top-level scalar keys of a SKILL.md's YAML front matter: `key: value`, a quoted
    value, or a folded or literal block. Nothing else of YAML is needed, or trusted."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    found: dict[str, str] = {}
    key: str | None = None
    block: list[str] = []
    for line in lines[1:MAX_FRONT_MATTER_LINES]:
        if line.strip() == "---":
            break
        match = re.match(r"^([A-Za-z_][\w-]*):\s*(.*?)\s*$", line)
        if match:
            if key is not None and block:
                found[key] = " ".join(block)
            key, value = match.group(1).lower(), match.group(2)
            block = []
            if value in ("", ">", "|", ">-", "|-", ">+", "|+"):
                continue
            found[key] = value.strip("'\"")
            key = None
        elif key is not None and line.startswith((" ", "\t")):
            block.append(line.strip())
    if key is not None and block:
        found[key] = " ".join(block)
    return found


def _skills(folder: Path, repo_root: Path, budget: list[int]) -> tuple[list[SelfEntry], str]:
    """The skills one level under folder, and a note of any left unread past the budget.
    A folder or SKILL.md that is a link is not followed."""
    entries = []
    skipped = 0
    for skill_dir in sorted(p for p in folder.iterdir() if p.is_dir() and not p.is_symlink()):
        path = skill_dir / "SKILL.md"
        if not path.is_file() or path.is_symlink():
            continue
        if budget[0] <= 0:
            skipped += 1
            continue
        budget[0] -= 1
        meta = _front_matter(_read_text(path, MAX_SKILL_BYTES)[0])
        name = _one_line(meta.get("name") or skill_dir.name, MAX_NAME)
        entries.append(SelfEntry(
            key=f"builder_skill:{name}", kind="builder_skill", name=name,
            description=_one_line(meta.get("description", ""), MAX_DESCRIPTION),
            origin=_relative(path, repo_root),
        ))
    note = (f"{skipped} more skill folder(s) past the limit of {MAX_SKILLS} were not read"
            if skipped else "")
    return entries, note


# --- review checks, tokens and the ledger ----------------------------------------------------


def _gates(path: Path, origin: str) -> tuple[list[SelfEntry], str]:
    """Each acceptance gate: a gate_* function of the acceptance script, by its name and
    docstring. The script is parsed, never run."""
    text, note = _read_text(path, MAX_SOURCE_BYTES)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [], "not read: it does not parse as Python"
    entries = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("gate_"):
            name = node.name[len("gate_"):]
            doc = ast.get_docstring(node) or f"the {name.replace('_', ' ')} acceptance gate"
            entries.append(SelfEntry(
                key=f"review_check:gate_{name}", kind="review_check", name=f"gate_{name}",
                description=_one_line(f"Acceptance gate {name.replace('_', ' ')}: {doc}",
                                      MAX_DESCRIPTION),
                origin=origin,
            ))
    return entries, note


def _tokens(path: Path, origin: str) -> tuple[list[SelfEntry], str]:
    """The Generative UI's tokens: the custom properties of the sheet's :root blocks, one
    entry per family (the word before the first hyphen), read as text."""
    text, note = _read_text(path, MAX_SOURCE_BYTES)
    text = _CSS_COMMENT.sub(" ", text)
    families: dict[str, list[str]] = {}
    for opening in _ROOT_BLOCK.finditer(text):
        end = text.find("}", opening.end())
        block = text[opening.end(): end if end >= 0 else len(text)]
        for match in _CUSTOM_PROPERTY.finditer(block):
            name, value = match.group(1), _one_line(match.group(2), 80)
            families.setdefault(name.split("-", 1)[0].lower(), []).append(f"--{name}: {value}")
    entries = [
        SelfEntry(
            key=f"design_token:{family}", kind="design_token", name=f"{family} tokens",
            description=_one_line(f"Generative UI {family} tokens: " + "; ".join(tokens),
                                  MAX_DESCRIPTION),
            origin=origin,
        )
        for family, tokens in sorted(families.items())
    ]
    return entries, note


def _absorptions(store: Any) -> tuple[list[SelfEntry], str]:
    """Every absorption the owner decided to take, from the store's ledgers, bounded."""
    from app.digest.model import ADDING_TARGETS, DECIDER

    entries: list[SelfEntry] = []
    left = 0
    for artifact_id in store.ids():
        decided = [record for record in store.absorptions(artifact_id)
                   if record.decided_by == DECIDER and record.target in ADDING_TARGETS]
        if not decided:
            continue
        units = {unit.id: unit for unit in store.load(artifact_id).units}
        for record in decided:
            if len(entries) >= MAX_ABSORPTIONS:
                left += 1
                continue
            unit = units.get(record.unit_id)
            title = unit.title if unit is not None else record.unit_id
            entries.append(SelfEntry(
                key=f"absorption:{record.id}", kind="absorption",
                name=_one_line(f"{record.target}: {title}", MAX_NAME),
                description=_one_line(unit.body if unit is not None else record.reasoning,
                                      MAX_DESCRIPTION),
                origin=f"absorption ledger ({artifact_id})",
            ))
    note = f"{left} more decided absorption(s) past the limit of {MAX_ABSORPTIONS} were not read" if left else ""
    return entries, note


# --- the model -------------------------------------------------------------------------------


def build_self_model(repo_root: Path, *, memory: Path | None = None,
                     store: Any = None) -> SelfModel:
    """Generate CLIVE's self-model from the repository at repo_root (the git root, or the app
    directory inside it). `memory` reads the product memory (FEATURES.md, IDEAS.md,
    DECISIONS.md) from another folder instead of the repository's; `store`, a DigestStore,
    adds the absorptions the owner has decided to take."""
    repo_root, app_root = _roots(Path(repo_root))
    entries: dict[str, SelfEntry] = {}
    sources: list[SelfSource] = []

    def add(name: str, where: str, found: list[SelfEntry], note: str = "") -> None:
        # the first entry with a key is the one that counts; a repeat is said, not kept
        fresh = []
        for entry in found:
            if entry.key not in entries:
                entries[entry.key] = entry
                fresh.append(entry)
        if len(fresh) < len(found):
            extra = f"{len(found) - len(fresh)} repeated key(s) kept once"
            note = f"{note}; {extra}" if note else extra
        sources.append(SelfSource(name, where, len(fresh), note))

    registries = (
        ("tool registry", "app/tools/registry.py", _tools),
        ("intent families", "app/fastpath/intent.py and app/families", _families),
        ("scene primitives", "app/scenes/scene.py", _scene_primitives),
    )
    running = _running_code_is(app_root)
    for name, where, reader in registries:
        if running:
            add(name, where, reader())
        else:
            add(name, where, [], "not read: the running CLIVE code is not this repository's, "
                                 "and a registry can only be read by importing it")

    base = app_root or repo_root
    for name, relative, reader in (("review checks", GATES_FILE, _gates),
                                   ("design tokens", TOKEN_SHEET, _tokens)):
        path = base / relative
        where = _relative(path, repo_root)
        if path.is_file() and not path.is_symlink():
            add(name, where, *reader(path, where))
        else:
            add(name, where, [], "not found")

    folder = Path(memory) if memory is not None else base / PRODUCT_MEMORY
    for name, filename, reader in (("features", FEATURES_FILE, _features),
                                   ("ideas", IDEAS_FILE, _ideas),
                                   ("decisions", DECISIONS_FILE, _decisions)):
        path = folder / filename
        where = _relative(path, repo_root)
        if path.is_file():
            text, note = _read_text(path, MAX_DOCUMENT_BYTES)
            add(name, where, reader(text, where), note)
        else:
            add(name, where, [], "not found")

    if store is not None:
        add("absorption ledger", str(getattr(store, "root", "the digest store")), *_absorptions(store))
    else:
        add("absorption ledger", "a digest store", [], "none given: no decided absorption is known")

    budget = [MAX_SKILLS]
    seen: set[Path] = set()
    roots = [repo_root] + ([app_root] if app_root is not None and app_root != repo_root else [])
    for root in roots:
        for relative in SKILL_DIRECTORIES:
            folder = root / relative
            if not folder.is_dir() or folder.resolve() in seen:
                continue
            seen.add(folder.resolve())
            add("builder skills", _relative(folder, repo_root), *_skills(folder, repo_root, budget))
    if not seen:
        add("builder skills", " or ".join(str(p) for p in SKILL_DIRECTORIES), [],
            "no skills directory")

    return SelfModel(entries=tuple(entries.values()), sources=tuple(sources))
