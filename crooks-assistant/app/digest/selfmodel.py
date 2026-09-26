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
    feature           the FEAT-nnn rows of docs/product-memory/FEATURES.md, with their status
    idea              the IDEA-nnn headings of docs/product-memory/IDEAS.md, with their status
    builder_skill     every SKILL.md one level under a skills directory (.claude/skills or
                      skills, at the repository root or beside the app), if there is one

The registries can only be read by importing CLIVE's own code — importing is what runs their
decorators — which is CLIVE reading itself, not an artifact's content. They are read only when
the running code is the repository's own; otherwise they are left out and `sources` says so.
The documents and skills are read as text and never executed.

The entries are ordered by kind and key, and the model carries a digest of them, so a relation
can cite exactly which self-model it was made against."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

SELF_KINDS = ("tool", "intent_family", "scene_primitive", "feature", "idea", "builder_skill")
ACCESS = ("read", "write")

MAX_NAME = 200
MAX_DESCRIPTION = 1_200
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024   # FEATURES.md and IDEAS.md, each
MAX_SKILL_BYTES = 64 * 1024            # the head of a SKILL.md: its front matter is at the top
MAX_SKILLS = 500                       # skill folders looked at, in all skills directories
MAX_FRONT_MATTER_LINES = 200

PRODUCT_MEMORY = Path("docs") / "product-memory"
FEATURES_FILE = "FEATURES.md"
IDEAS_FILE = "IDEAS.md"
SKILL_DIRECTORIES = (Path(".claude") / "skills", Path("skills"))
APP_DIRECTORY = "crooks-assistant"     # where the app lives inside the git repository

_FEATURE_ID = re.compile(r"^FEAT-\d{3,}$")
_IDEA_HEADING = re.compile(r"^##\s+(IDEA-\d{3,})\s*[—–-]+\s*(.+?)\s*$")
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
        if self.status is not None and self.kind not in ("feature", "idea"):
            raise ValueError("only a feature or an idea has a status")

    @property
    def present(self) -> bool:
        """Whether CLIVE has this now, rather than plans or imagines it: every tool, intent
        family, scene primitive and builder skill, and a feature that has shipped or is merged
        and testing. An idea is never something CLIVE has."""
        if self.kind in ("tool", "intent_family", "scene_primitive", "builder_skill"):
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
    if app_root is None:
        return False
    import app

    return Path(app.__file__).resolve().parent == (app_root / "app").resolve()


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


def _read_text(path: Path, limit: int) -> str:
    with path.open("rb") as handle:
        data = handle.read(limit)
    return data.decode("utf-8", errors="replace")


def _features(path: Path, origin: str) -> list[SelfEntry]:
    entries: list[SelfEntry] = []
    for line in _read_text(path, MAX_DOCUMENT_BYTES).split("\n"):
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


def _ideas(path: Path, origin: str) -> list[SelfEntry]:
    entries: list[SelfEntry] = []
    current: tuple[str, str] | None = None
    meta: dict[str, str] = {}
    body: list[str] = []

    def close() -> None:
        if current is None:
            return
        idea_id, title = current
        status = _status(meta.get("status", ""))
        text = " ".join(line for line in body if line and line != "---")
        theme = meta.get("theme", "")
        description = f"Theme: {theme}. {text}" if theme else text
        entries.append(SelfEntry(
            key=f"idea:{idea_id}", kind="idea", name=_one_line(title, MAX_NAME),
            description=_one_line(description, MAX_DESCRIPTION), origin=origin,
            status=status,
        ))

    for raw in _read_text(path, MAX_DOCUMENT_BYTES).split("\n"):
        line = raw.strip()
        heading = _IDEA_HEADING.match(line)
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


def _skills(folder: Path, repo_root: Path, budget: list[int]) -> list[SelfEntry]:
    entries = []
    for skill_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
        if budget[0] <= 0:
            break
        path = skill_dir / "SKILL.md"
        if not path.is_file():
            continue
        budget[0] -= 1
        meta = _front_matter(_read_text(path, MAX_SKILL_BYTES))
        name = _one_line(meta.get("name") or skill_dir.name, MAX_NAME)
        entries.append(SelfEntry(
            key=f"builder_skill:{name}", kind="builder_skill", name=name,
            description=_one_line(meta.get("description", ""), MAX_DESCRIPTION),
            origin=_relative(path, repo_root),
        ))
    return entries


# --- the model -------------------------------------------------------------------------------


def build_self_model(repo_root: Path) -> SelfModel:
    """Generate CLIVE's self-model from the repository at repo_root (the git root, or the app
    directory inside it)."""
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

    memory = (app_root or repo_root) / PRODUCT_MEMORY
    for name, filename, reader in (("features", FEATURES_FILE, _features),
                                   ("ideas", IDEAS_FILE, _ideas)):
        path = memory / filename
        where = _relative(path, repo_root)
        if path.is_file():
            add(name, where, reader(path, where))
        else:
            add(name, where, [], "not found")

    budget = [MAX_SKILLS]
    seen: set[Path] = set()
    roots = [repo_root] + ([app_root] if app_root is not None and app_root != repo_root else [])
    for root in roots:
        for relative in SKILL_DIRECTORIES:
            folder = root / relative
            if not folder.is_dir() or folder.resolve() in seen:
                continue
            seen.add(folder.resolve())
            add("builder skills", _relative(folder, repo_root), _skills(folder, repo_root, budget))
    if not seen:
        add("builder skills", " or ".join(str(p) for p in SKILL_DIRECTORIES), [],
            "no skills directory")

    return SelfModel(entries=tuple(entries.values()), sources=tuple(sources))
