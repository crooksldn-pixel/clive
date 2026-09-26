"""Knowledge Digester, stage one: recognising what an artifact is.

The Knowledge Digester (SOURCE_ASSIMILATION_V1.md; NEXT_PHASE_2026-09-25.md §2) takes in an
external artifact that has already been copied into quarantine — a repository, a skill, a
document, a specification, a dataset, a theme, media — and turns it into provenance-tagged,
reversible knowledge. Before anything can be digested somebody has to say what it *is*, and it
is usually several things at once: a Python package that is also a skill collection with CI
workflows. `detect_kinds(root)` names every one of them, ranked by confidence, each with the
evidence it rests on, and a census of the tree that later stages can plan from.

Digesting is reading, and recognising is the smallest kind of reading:

* **Names and heads only.** A recogniser sees the tree's file and directory names and, through
  `Tree.head`, at most the first HEAD_BYTES of a regular file inside the root. Nothing is
  imported, run, unpacked or fetched. Symlinks are listed and never read through.
* **Bounded.** The walk stops at MAX_ENTRIES files, one detection reads at most MAX_HEADS
  heads, and a recogniser opens a small fixed number of files of one sort (usually
  CANDIDATES), shallowest first.
* **Extensible.** Each kind is one small recogniser in a registry: a function from a `Tree` to
  a `Match`, and one `@register(...)` line. Adding a kind changes no other recogniser.
"""

from __future__ import annotations

import os
import re
import stat
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

HEAD_BYTES = 4096
MAX_ENTRIES = 50_000
MAX_HEADS = 2_000
CANDIDATES = 40
MAX_EVIDENCE = 12
UNKNOWN = "unknown"
NO_EXTENSION = "(none)"
_BOM = chr(0xFEFF)

# Walked past, not into: version-control internals, installed dependencies and caches. They
# are named in the census as skipped, and a recogniser can still see that they exist.
PRUNED = frozenset({
    ".git", ".hg", ".svn", "node_modules", "bower_components", "__pycache__", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".gradle",
})


# --- what a detection says ------------------------------------------------------------------


@dataclass(frozen=True)
class Evidence:
    """One thing found: where, what, and how strongly that alone says the kind."""

    path: str
    signal: str
    weight: float


@dataclass(frozen=True)
class Match:
    """What a recogniser returns when its kind is present."""

    confidence: float
    evidence: tuple[Evidence, ...]


class Findings:
    """Evidence for one kind as a recogniser gathers it. `match()` turns it into a Match whose
    confidence is the strongest single signal, raised a little by corroborating ones."""

    def __init__(self) -> None:
        self._evidence: dict[tuple[str, str], Evidence] = {}

    def add(self, path: str, signal: str, weight: float) -> None:
        path = path or "."
        current = self._evidence.get((path, signal))
        if current is None or current.weight < weight:
            self._evidence[(path, signal)] = Evidence(path, signal, round(weight, 3))

    def __bool__(self) -> bool:
        return bool(self._evidence)

    def match(self) -> Match | None:
        if not self._evidence:
            return None
        ranked = sorted(self._evidence.values(), key=lambda e: (-e.weight, e.path, e.signal))
        corroborating = sum(1 for e in ranked[1:] if e.weight >= 0.5)
        confidence = min(0.99, ranked[0].weight + 0.02 * min(corroborating, 3))
        return Match(round(confidence, 3), tuple(ranked))


@dataclass(frozen=True)
class Detection:
    kind: str
    label: str
    confidence: float
    evidence: tuple[Evidence, ...]
    more_evidence: int = 0


@dataclass(frozen=True)
class Census:
    """The shape of the tree, for the stages after this one."""

    files: int
    dirs: int
    symlinks: int
    by_extension: dict[str, int]
    top_level: dict[str, dict[str, Any]]
    skipped: tuple[str, ...]
    truncated: bool
    unreadable: int
    heads_read: int


@dataclass(frozen=True)
class DetectionReport:
    root: str
    kinds: tuple[Detection, ...]
    census: Census
    failures: dict[str, str] = field(default_factory=dict)

    def names(self) -> list[str]:
        return [detection.kind for detection in self.kinds]

    def get(self, kind: str) -> Detection | None:
        return next((detection for detection in self.kinds if detection.kind == kind), None)

    def __contains__(self, kind: object) -> bool:
        return any(detection.kind == kind for detection in self.kinds)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- what a recogniser may look at ----------------------------------------------------------


def extension_of(rel: str) -> str:
    return os.path.splitext(_name(rel).lower())[1] or NO_EXTENSION


def _name(rel: str) -> str:
    return rel.rpartition("/")[2]


def _parent(rel: str) -> str:
    return rel.rpartition("/")[0]


def _shallow_first(paths: Iterable[str]) -> list[str]:
    return sorted(set(paths), key=lambda rel: (rel.count("/"), rel))


class Tree:
    """A quarantined directory, or a single file, as names plus bounded heads.

    Paths are relative, '/'-separated, and relative to the root (to its parent when the root
    is a single file). Nothing here follows a symlink or reads past HEAD_BYTES."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self.root = Path(root)
        self.files: list[str] = []
        self.dirs: set[str] = set()
        self.symlinks: list[str] = []
        self.pruned: list[str] = []
        self.unreadable = 0
        self.truncated = False
        self.heads_read = 0
        self._heads: dict[str, bytes] = {}
        self._only: str | None = None
        if os.path.islink(self.root):
            raise ValueError(f"{self.root} is a symlink: detection reads a quarantined copy")
        if self.root.is_file():
            self.base = self.root.parent
            self._only = self.root.name
            self.files.append(self.root.name)
        elif self.root.is_dir():
            self.base = self.root
            self._walk()
        else:
            raise FileNotFoundError(f"{self.root} is not a file or directory")
        self.files.sort()
        self._by_name: dict[str, list[str]] = {}
        for rel in self.files:
            self._by_name.setdefault(_name(rel).lower(), []).append(rel)

    def _walk(self) -> None:
        def failed(_error: OSError) -> None:
            self.unreadable += 1

        for current, dirnames, filenames in os.walk(self.base, onerror=failed):
            rel_dir = os.path.relpath(current, self.base)
            prefix = "" if rel_dir == "." else rel_dir.replace(os.sep, "/") + "/"
            descend = []
            for name in sorted(dirnames):
                rel = prefix + name
                if os.path.islink(os.path.join(current, name)):
                    self.symlinks.append(rel)
                    continue
                self.dirs.add(rel)
                if name in PRUNED:
                    self.pruned.append(rel)
                else:
                    descend.append(name)
            dirnames[:] = descend
            for name in sorted(filenames):
                if len(self.files) >= MAX_ENTRIES:
                    self.truncated = True
                    break
                rel = prefix + name
                if os.path.islink(os.path.join(current, name)):
                    self.symlinks.append(rel)
                else:
                    self.files.append(rel)
            if self.truncated:
                break

    # names

    def named(self, *names: str) -> list[str]:
        """Files with one of these names, in any folder, case-insensitively."""
        return _shallow_first(rel for name in names for rel in self._by_name.get(name.lower(), []))

    def suffixed(self, *suffixes: str) -> list[str]:
        wanted = tuple(suffix.lower() for suffix in suffixes)
        return _shallow_first(rel for rel in self.files if rel.lower().endswith(wanted))

    def matching(self, pattern: str) -> list[str]:
        """Files whose relative path matches this regular expression, case-insensitively."""
        compiled = re.compile(pattern, re.IGNORECASE)
        return _shallow_first(rel for rel in self.files if compiled.search(rel))

    def under(self, directory: str) -> list[str]:
        prefix = directory.rstrip("/") + "/"
        return [rel for rel in self.files if rel.startswith(prefix)]

    def dirs_named(self, *names: str) -> list[str]:
        wanted = {name.lower() for name in names}
        return _shallow_first(rel for rel in self.dirs if _name(rel).lower() in wanted)

    def dirs_suffixed(self, *suffixes: str) -> list[str]:
        wanted = tuple(suffix.lower() for suffix in suffixes)
        return _shallow_first(rel for rel in self.dirs if rel.lower().endswith(wanted))

    # heads

    def head_bytes(self, rel: str, size: int = HEAD_BYTES) -> bytes:
        """At most the first `size` (never more than HEAD_BYTES) bytes of a regular file."""
        size = max(0, min(size, HEAD_BYTES))
        if rel not in self._heads:
            if self.heads_read >= MAX_HEADS:
                return b""
            self._heads[rel] = self._read_head(rel)
        return self._heads[rel][:size]

    def head(self, rel: str, size: int = HEAD_BYTES) -> str:
        text = self.head_bytes(rel, size).decode("utf-8", errors="replace")
        return text[1:] if text.startswith(_BOM) else text

    def _read_head(self, rel: str) -> bytes:
        path = PurePosixPath(rel)
        if path.is_absolute() or not path.parts or ".." in path.parts:
            return b""
        if self._only is not None and rel != self._only:
            return b""
        current = self.base
        mode = 0
        for part in path.parts:
            current = current / part
            try:
                mode = os.lstat(current).st_mode
            except OSError:
                return b""
            if stat.S_ISLNK(mode):
                return b""
        if not stat.S_ISREG(mode):
            return b""
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        try:
            fd = os.open(current, flags)
        except OSError:
            self.unreadable += 1
            return b""
        self.heads_read += 1
        chunks: list[bytes] = []
        remaining = HEAD_BYTES
        try:
            while remaining > 0:
                chunk = os.read(fd, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
        except OSError:
            self.unreadable += 1
        finally:
            os.close(fd)
        return b"".join(chunks)

    # the census

    def census(self) -> Census:
        counts = Counter(extension_of(rel) for rel in self.files)
        by_extension = dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))
        top: dict[str, dict[str, Any]] = {}
        if self._only is not None:
            top[self._only] = {"type": "file"}
        else:
            for rel in self.dirs:
                if "/" not in rel:
                    top[rel] = {"type": "dir", "files": 0, "skipped": rel in self.pruned}
            for rel in self.files:
                first, sep, _ = rel.partition("/")
                if sep:
                    top.setdefault(first, {"type": "dir", "files": 0, "skipped": False})
                    top[first]["files"] += 1
                else:
                    top[rel] = {"type": "file"}
            for rel in self.symlinks:
                if "/" not in rel:
                    top[rel] = {"type": "symlink"}
        return Census(
            files=len(self.files),
            dirs=len(self.dirs),
            symlinks=len(self.symlinks),
            by_extension=by_extension,
            top_level=dict(sorted(top.items())),
            skipped=tuple(sorted(self.pruned)),
            truncated=self.truncated,
            unreadable=self.unreadable,
            heads_read=self.heads_read,
        )


# --- the registry ---------------------------------------------------------------------------

Recogniser = Callable[[Tree], Match | None]


@dataclass(frozen=True)
class Registration:
    kind: str
    label: str
    recognise: Recogniser


_REGISTRY: dict[str, Registration] = {}


def register(
    kind: str, label: str | None = None, *, replace: bool = False
) -> Callable[[Recogniser], Recogniser]:
    """Decorator: `@register("haiku", "haiku collection")` on a `(Tree) -> Match | None`."""
    if not kind or kind == UNKNOWN:
        raise ValueError(f"{kind!r} cannot be registered as a kind")

    def decorate(recognise: Recogniser) -> Recogniser:
        if kind in _REGISTRY and not replace:
            raise ValueError(f"a recogniser for {kind!r} is already registered")
        _REGISTRY[kind] = Registration(kind, label or kind.replace("_", " "), recognise)
        return recognise

    return decorate


def unregister(kind: str) -> None:
    _REGISTRY.pop(kind, None)


def registered() -> list[Registration]:
    return list(_REGISTRY.values())


def detect_kinds(
    root: str | os.PathLike[str], *, recognisers: Iterable[Registration] | None = None
) -> DetectionReport:
    """Every kind `root` is, most confident first, with evidence, and the tree's census.

    A recogniser that raises does not stop the others: its error is kept in `failures`. When
    nothing matches, the one kind is 'unknown', and its evidence is the file-type census."""
    tree = Tree(root)
    found: list[Detection] = []
    failures: dict[str, str] = {}
    for registration in registered() if recognisers is None else recognisers:
        try:
            match = registration.recognise(tree)
        except Exception as error:
            failures[registration.kind] = f"{type(error).__name__}: {error}"
            continue
        if match is None or not match.evidence:
            continue
        evidence = tuple(match.evidence)
        found.append(Detection(
            kind=registration.kind,
            label=registration.label,
            confidence=max(0.0, min(1.0, float(match.confidence))),
            evidence=evidence[:MAX_EVIDENCE],
            more_evidence=max(0, len(evidence) - MAX_EVIDENCE),
        ))
    census = tree.census()
    if not found:
        found.append(_unknown(tree, census))
    found.sort(key=lambda d: (-d.confidence, -(len(d.evidence) + d.more_evidence), d.kind))
    return DetectionReport(str(tree.root), tuple(found), census, failures)


def _unknown(tree: Tree, census: Census) -> Detection:
    if not tree.files:
        evidence: tuple[Evidence, ...] = (Evidence(".", "no files to recognise", 0.0),)
    else:
        first: dict[str, str] = {}
        for rel in tree.files:
            first.setdefault(extension_of(rel), rel)
        evidence = tuple(
            Evidence(first[ext], f"{count} file(s) with extension {ext}; no recogniser matched", 0.0)
            for ext, count in census.by_extension.items()
        )
    return Detection(
        UNKNOWN, "unknown", 0.0, evidence[:MAX_EVIDENCE], max(0, len(evidence) - MAX_EVIDENCE)
    )


# --- small helpers the recognisers share ----------------------------------------------------


def _prefer(paths: list[str], pattern: str) -> list[str]:
    """Paths whose relative path matches `pattern` first, then shallowest first."""
    compiled = re.compile(pattern, re.IGNORECASE)
    return sorted(paths, key=lambda rel: (not compiled.search(rel), rel.count("/"), rel))


def _aggregate(found: Findings, paths: list[str], noun: str, weight: float) -> None:
    if paths:
        found.add(paths[0], f"{len(paths)} {noun}", weight)


def _common_parent(paths: list[str]) -> str:
    common: list[str] = []
    for level in zip(*(rel.split("/")[:-1] for rel in paths), strict=False):
        if len(set(level)) != 1:
            break
        common.append(level[0])
    return "/".join(common) or "."


def _typed_files(
    tree: Tree,
    found: Findings,
    table: dict[str, tuple[str, bytes | None]],
    verified: float,
    unverified: float,
) -> None:
    """Files known by extension, confirmed by the signature at the start of their head."""
    paths = tree.suffixed(*table)
    for rel in paths[:CANDIDATES]:
        ext = os.path.splitext(rel.lower())[1]
        noun, magic = table[ext] if ext in table else ("file", None)
        if magic is None:
            found.add(rel, noun, unverified)
        elif tree.head_bytes(rel, len(magic)) == magic:
            found.add(rel, f"{noun} (file signature verified)", verified)
        else:
            found.add(rel, f"named {ext} but its head is not a {noun}", 0.3)
    rest = paths[CANDIDATES:]
    if rest:
        found.add(rest[0], f"{len(rest)} more by extension, not opened", unverified)


# --- the recognisers ------------------------------------------------------------------------

_GIT_HEAD = re.compile(r"\A(ref: refs/\S+|[0-9a-f]{40,64})\s*\Z")


@register("git_repository", "git repository")
def _git_repository(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.dirs_named(".git"):
        nested = "/" in rel
        head = tree.head(f"{rel}/HEAD", 256).strip()
        if _GIT_HEAD.match(head):
            found.add(rel, f"git metadata, HEAD is {head[:60]!r}", 0.7 if nested else 0.99)
        else:
            found.add(rel, ".git directory", 0.6 if nested else 0.8)
    for rel in tree.named(".git"):
        if tree.head(rel, 256).startswith("gitdir:"):
            found.add(rel, "git worktree or submodule pointer (gitdir:)", 0.6 if "/" in rel else 0.9)
    if "HEAD" in tree.files and {"objects", "refs"} <= tree.dirs:
        if _GIT_HEAD.match(tree.head("HEAD", 256).strip()):
            found.add("HEAD", "bare git repository (HEAD, objects/, refs/)", 0.9)
    return found.match()


# Front matter is closed by a second `---` inside the head; an unterminated block is not one.
_FRONT_MATTER = re.compile(r"\A---[ \t]*\r?\n(?:(.*?)\r?\n)?---[ \t]*(?:\r?\n|\Z)", re.S)
_FRONT_MATTER_KEY = re.compile(r"^([A-Za-z_][\w-]*)[ \t]*:[ \t]*(.*)$")
_SKILL_LIMIT = 200


def _front_matter(text: str) -> dict[str, str] | None:
    match = _FRONT_MATTER.match(text)
    if match is None:
        return None
    keys: dict[str, str] = {}
    for line in (match.group(1) or "").splitlines():
        key = _FRONT_MATTER_KEY.match(line)
        if key:
            keys.setdefault(key.group(1).lower(), key.group(2).strip())
    return keys


def _skills(tree: Tree) -> list[tuple[str, dict[str, str] | None]]:
    return [(rel, _front_matter(tree.head(rel))) for rel in tree.named("SKILL.md")[:_SKILL_LIMIT]]


@register("agent_skill", "agent skill")
def _agent_skill(tree: Tree) -> Match | None:
    found = Findings()
    skills = _skills(tree)
    # Front matter is the defining signal: a plain SKILL.md is only weak evidence beside one.
    if all(meta is None for _, meta in skills):
        return None
    for rel, meta in skills:
        at_root = "/" not in rel
        if meta is None:
            found.add(rel, "SKILL.md without front matter", 0.3)
        elif meta.get("name") and meta.get("description"):
            found.add(
                rel,
                f"SKILL.md front matter: name {meta['name'][:60]!r} with a description",
                0.95 if at_root else 0.85,
            )
        else:
            found.add(rel, "SKILL.md front matter without name and description", 0.7 if at_root else 0.6)
    return found.match()


@register("skill_collection", "agent skill collection")
def _skill_collection(tree: Tree) -> Match | None:
    found = Findings()
    homes = sorted({_parent(rel) for rel, meta in _skills(tree) if meta is not None and "/" in rel})
    groups: dict[str, list[str]] = {}
    for home in homes:
        groups.setdefault(_parent(home), []).append(_name(home))
    for parent, names in groups.items():
        listed = ", ".join(names[:8]) + (", ..." if len(names) > 8 else "")
        if len(names) >= 2:
            found.add(parent, f"{len(names)} skill folders with SKILL.md front matter: {listed}", 0.9)
        elif _name(parent).lower() == "skills":
            found.add(parent, f"skills/ folder with one skill: {listed}", 0.6)
    if len(homes) >= 2:
        found.add(".", f"{len(homes)} skills in one tree", 0.85)
    if homes:
        for rel in tree.matching(r"(^|/)\.claude-plugin/(plugin|marketplace)\.json$"):
            found.add(rel, "Claude plugin manifest", 0.85)
    return found.match()


_AGENT_FILES = {
    "claude.md": ("Claude Code project instructions", 0.9),
    "claude.local.md": ("Claude Code local instructions", 0.85),
    "agents.md": ("AGENTS.md agent instructions", 0.9),
    "gemini.md": ("Gemini CLI context file", 0.9),
    ".cursorrules": ("Cursor rules file", 0.9),
    ".windsurfrules": ("Windsurf rules file", 0.9),
    ".clinerules": ("Cline rules file", 0.9),
    "copilot-instructions.md": ("GitHub Copilot instructions", 0.85),
    ".mcp.json": ("MCP client configuration", 0.7),
}
_AGENT_PATHS = (
    (r"(^|/)\.cursor/rules/[^/]+$", "Cursor project rule", 0.9),
    (r"(^|/)\.claude/settings(\.local)?\.json$", "Claude Code settings", 0.85),
    (r"(^|/)\.claude/(commands|agents|hooks)/[^/]+$", "Claude Code command, agent or hook", 0.85),
    (r"(^|/)\.clinerules/[^/]+$", "Cline rule", 0.85),
    (r"(^|/)\.github/(prompts|instructions)/[^/]+\.md$", "Copilot prompt or instructions", 0.8),
    (r"\.prompt(\.md|\.ya?ml)?$|\.prompty$", "prompt file", 0.6),
)
_PROMPT_SUFFIXES = (".md", ".txt", ".prompt", ".yaml", ".yml", ".json", ".j2", ".jinja")


@register("agent_config", "agent or harness configuration")
def _agent_config(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.named(*_AGENT_FILES)[:CANDIDATES]:
        signal, weight = _AGENT_FILES[_name(rel).lower()]
        found.add(rel, signal, weight)
    for pattern, signal, weight in _AGENT_PATHS:
        for rel in tree.matching(pattern)[:CANDIDATES]:
            found.add(rel, signal, weight)
    for directory in tree.dirs_named("prompts", "prompt-library", "prompt_library"):
        prompts = [rel for rel in tree.under(directory) if rel.lower().endswith(_PROMPT_SUFFIXES)]
        if len(prompts) >= 2:
            found.add(directory, f"prompt library: {len(prompts)} prompts", 0.6)
    return found.match()


_MCP_NODE_SDK = "@modelcontextprotocol/sdk"
_MCP_PY_QUOTED = re.compile(r"""["'](?:mcp|fastmcp)(?:\[[^\]"']*\])?\s*(?:[<>=!~][^"']*)?["']""")
_MCP_PY_LINE = re.compile(r"(?m)^\s*(?:mcp|fastmcp)(?:\[[^\]]*\])?\s*(?:[<>=!~].*)?$")
# The MCP SDKs are client libraries too, so only the server half of their API says "server":
# mcp.server.*, fastmcp's FastMCP, the TypeScript SDK's server/ entry points and McpServer.
_MCP_SERVER_API = re.compile(
    r"(?m)^\s*from\s+(?:mcp|fastmcp)\.server(?:\.[\w.]+)?\s+import\b"
    r"|^\s*import\s+(?:mcp|fastmcp)\.server\b"
    r"|^\s*from\s+fastmcp\s+import\b[^\n]*\bFastMCP\b"
    r"|@modelcontextprotocol/sdk/server\b|\bFastMCP\s*\(|\bMcpServer\s*\("
)


@register("mcp_server", "MCP server")
def _mcp_server(tree: Tree) -> Match | None:
    found = Findings()
    sources = _prefer(tree.suffixed(".py", ".ts", ".js", ".mjs", ".cjs"), r"mcp|server")
    for rel in sources[:CANDIDATES]:
        if _MCP_SERVER_API.search(tree.head(rel)):
            found.add(rel, "uses the MCP server API", 0.85)
    for rel in tree.named("server.json")[:CANDIDATES]:
        if "modelcontextprotocol" in tree.head(rel):
            found.add(rel, "MCP registry server manifest", 0.85)
    for rel in tree.named("smithery.yaml", "smithery.yml"):
        found.add(rel, "Smithery MCP server configuration", 0.8)
    # A dependency on an SDK only corroborates: a client depends on the same packages.
    if not found:
        return None
    for rel in tree.named("package.json")[:CANDIDATES]:
        if _MCP_NODE_SDK in tree.head(rel):
            found.add(rel, "depends on the MCP TypeScript SDK", 0.6)
    for rel in tree.named("pyproject.toml", "setup.py")[:CANDIDATES]:
        if _MCP_PY_QUOTED.search(tree.head(rel)):
            found.add(rel, "depends on the MCP Python SDK", 0.6)
    for rel in tree.matching(r"(^|/)(requirements[^/]*\.txt|setup\.cfg)$")[:CANDIDATES]:
        if _MCP_PY_LINE.search(tree.head(rel)):
            found.add(rel, "depends on the MCP Python SDK", 0.6)
    return found.match()


# YAML: only an unindented (top-level) key on its own line; `[ \t]` never crosses a newline.
_OPENAPI = re.compile(r"""(?m)^["']?(openapi|swagger)["']?[ \t]*:[ \t]*["']?(\d+(?:\.\d+)*)""")
_OPENAPI_JSON = re.compile(r'"(openapi|swagger)"\s*:\s*"?(\d+(?:\.\d+)*)')


def _json_top_level(text: str, index: int) -> bool:
    """Whether `index` in JSON text sits directly inside the outermost object, outside strings."""
    depth = 0
    in_string = escaped = False
    for char in text[:index]:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "{[":
            depth += 1
        elif char in "}]":
            depth -= 1
    return depth == 1 and not in_string


def _openapi_version(head: str) -> re.Match[str] | None:
    """The version marker in a head. JSON properties are unordered, so in a JSON object it is
    any top-level `openapi`/`swagger` property within the head, not only the first one."""
    if head.lstrip().startswith("{"):
        markers = _OPENAPI_JSON.finditer(head)
        return next((m for m in markers if _json_top_level(head, m.start())), None)
    return _OPENAPI.search(head)


@register("openapi_spec", "OpenAPI or Swagger specification")
def _openapi_spec(tree: Tree) -> Match | None:
    found = Findings()
    for rel in _prefer(tree.suffixed(".json", ".yaml", ".yml"), r"openapi|swagger|api")[: CANDIDATES * 2]:
        match = _openapi_version(tree.head(rel))
        if match:
            found.add(rel, f"{match.group(1)} {match.group(2)} document", 0.95)
        elif re.search(r"openapi|swagger", _name(rel), re.IGNORECASE):
            found.add(rel, "named as an OpenAPI/Swagger document, no version key in its head", 0.45)
    return found.match()


_JSON_SCHEMA = re.compile(r'"\$schema"\s*:\s*"https?://json-schema\.org/')


@register("json_schema_set", "JSON Schema set")
def _json_schema_set(tree: Tree) -> Match | None:
    found = Findings()
    schemas: list[str] = []
    for rel in _prefer(tree.suffixed(".json"), r"schema")[: CANDIDATES * 2]:
        if _JSON_SCHEMA.search(tree.head(rel)):
            schemas.append(rel)
            found.add(rel, "declares a json-schema.org $schema", 0.6)
        elif _name(rel).lower().endswith(".schema.json"):
            found.add(rel, "named *.schema.json", 0.4)
    if len(schemas) >= 2:
        found.add(_common_parent(schemas), f"{len(schemas)} JSON Schema documents", 0.85)
    return found.match()


_GRAPHQL_SDL = re.compile(
    r"(?m)^[ \t]*(?:extend[ \t]+)?"
    r"(?:(?:type|interface|input|enum|union|scalar)[ \t]+[_A-Za-z]"
    r"|schema[ \t]*\{|directive[ \t]+@)"
)


@register("graphql_schema", "GraphQL schema")
def _graphql_schema(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.suffixed(".graphql", ".graphqls", ".gql")[:CANDIDATES]:
        if _GRAPHQL_SDL.search(tree.head(rel)):
            found.add(rel, "GraphQL type definitions (SDL)", 0.9)
    for rel in tree.matching(r"(^|/)(schema|introspection)[^/]*\.json$")[:CANDIDATES]:
        if '"__schema"' in tree.head(rel):
            found.add(rel, "GraphQL introspection result", 0.75)
    return found.match()


_PY_PROJECT_TABLE = re.compile(r"(?m)^\[(project|tool\.poetry|tool\.flit\.metadata|tool\.pdm)\]")


@register("python_package", "Python package")
def _python_package(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.named("pyproject.toml")[:CANDIDATES]:
        head = tree.head(rel)
        if _PY_PROJECT_TABLE.search(head):
            found.add(rel, "pyproject.toml declares a Python project", 0.95)
        elif "[build-system]" in head:
            found.add(rel, "pyproject.toml declares a build system", 0.85)
        else:
            found.add(rel, "pyproject.toml (tool configuration only)", 0.5)
    for rel in tree.named("setup.py")[:CANDIDATES]:
        found.add(rel, "setup.py (named only, never run)", 0.85)
    for rel in tree.named("setup.cfg")[:CANDIDATES]:
        found.add(rel, "setup.cfg", 0.85 if "[metadata]" in tree.head(rel) else 0.6)
    packages = {_parent(rel) for rel in tree.named("__init__.py")}
    for package in _shallow_first(p for p in packages if _parent(p) not in packages or not p)[:8]:
        found.add(package, "Python package directory (__init__.py)", 0.55)
    for rel in tree.matching(r"(^|/)(requirements[^/]*\.txt|pipfile)$")[:CANDIDATES]:
        found.add(rel, "Python dependency list", 0.4)
    _aggregate(found, tree.suffixed(".py"), "Python source files", 0.3)
    return found.match()


_NODE_MANIFEST = re.compile(r'"(name|version|dependencies|devDependencies|main|exports)"\s*:')


@register("node_package", "Node package")
def _node_package(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.named("package.json")[:CANDIDATES]:
        if _NODE_MANIFEST.search(tree.head(rel)):
            found.add(rel, "package.json manifest", 0.9)
        else:
            found.add(rel, "package.json", 0.5)
    lockfiles = ("package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml", "bun.lockb", "bun.lock")
    for rel in tree.named(*lockfiles)[:CANDIDATES]:
        found.add(rel, "Node lockfile", 0.6)
    return found.match()


@register("swift_project", "Swift or Xcode project")
def _swift_project(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.dirs_suffixed(".xcodeproj")[:CANDIDATES]:
        found.add(rel, "Xcode project", 0.95)
    for rel in tree.dirs_suffixed(".xcworkspace")[:CANDIDATES]:
        found.add(rel, "Xcode workspace", 0.9)
    for rel in tree.named("Package.swift")[:CANDIDATES]:
        if "PackageDescription" in tree.head(rel):
            found.add(rel, "Swift package manifest", 0.95)
        else:
            found.add(rel, "Package.swift", 0.75)
    for rel in tree.named("Podfile", "Cartfile")[:CANDIDATES]:
        found.add(rel, "CocoaPods or Carthage dependencies", 0.6)
    _aggregate(found, tree.suffixed(".swift"), "Swift source files", 0.5)
    return found.match()


@register("go_project", "Go project")
def _go_project(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.named("go.mod")[:CANDIDATES]:
        head = tree.head(rel)
        found.add(rel, "go.mod module definition", 0.95 if re.search(r"(?m)^module\s+\S", head) else 0.7)
    for rel in tree.named("go.work")[:CANDIDATES]:
        found.add(rel, "Go workspace", 0.9)
    _aggregate(found, tree.suffixed(".go"), "Go source files", 0.5)
    return found.match()


@register("rust_project", "Rust project")
def _rust_project(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.named("Cargo.toml")[:CANDIDATES]:
        if re.search(r"(?m)^\[(package|workspace)\]", tree.head(rel)):
            found.add(rel, "Cargo manifest", 0.95)
        else:
            found.add(rel, "Cargo.toml", 0.7)
    _aggregate(found, tree.suffixed(".rs"), "Rust source files", 0.5)
    return found.match()


@register("java_project", "Java or JVM project")
def _java_project(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.named("pom.xml")[:CANDIDATES]:
        found.add(rel, "Maven project (pom.xml)", 0.95 if "<project" in tree.head(rel) else 0.7)
    for rel in tree.named(
        "build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts"
    )[:CANDIDATES]:
        found.add(rel, "Gradle build", 0.9)
    for rel in tree.named("gradlew", "mvnw")[:CANDIDATES]:
        found.add(rel, "build wrapper script (named only, never run)", 0.7)
    _aggregate(found, tree.suffixed(".java", ".kt", ".scala", ".groovy"), "JVM source files", 0.5)
    return found.match()


_THEME_DIRS = frozenset({"layout", "templates", "sections", "snippets", "assets", "config", "locales", "blocks"})


@register("shopify_theme", "Shopify theme")
def _shopify_theme(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.matching(r"(^|/)layout/theme\.liquid$"):
        found.add(rel, "theme layout (layout/theme.liquid)", 0.95)
    for rel in tree.matching(r"(^|/)config/settings_schema\.json$"):
        found.add(rel, "theme settings schema", 0.85)
    liquid = tree.suffixed(".liquid")
    by_parent: dict[str, set[str]] = {}
    for rel in tree.dirs:
        if _name(rel).lower() in _THEME_DIRS:
            by_parent.setdefault(_parent(rel), set()).add(_name(rel).lower())
    for parent, names in sorted(by_parent.items()):
        if len(names) >= 4 and liquid:
            found.add(parent, f"theme folder layout: {', '.join(sorted(names))}", 0.85)
    _aggregate(found, liquid, "Liquid templates", 0.4)
    return found.match()


_WEB_CONFIGS = (
    ("vite.config.", "Vite"), ("next.config.", "Next.js"), ("nuxt.config.", "Nuxt"),
    ("svelte.config.", "SvelteKit"), ("astro.config.", "Astro"), ("remix.config.", "Remix"),
    ("gatsby-config.", "Gatsby"), ("webpack.config.", "webpack"), ("vue.config.", "Vue CLI"),
    ("angular.json", "Angular"),
)


@register("website", "static website or web app")
def _website(tree: Tree) -> Match | None:
    found = Findings()
    html = tree.suffixed(".html", ".htm")
    entries = [page for page in html if _name(page).lower() in ("index.html", "index.htm")]
    for rel in entries[:CANDIDATES]:
        head = tree.head(rel, 1024).lower()
        if "<html" in head or "<!doctype html" in head:
            found.add(rel, "HTML entry page", 0.8)
        else:
            found.add(rel, "index.html", 0.55)
    for rel in tree.files:
        name = _name(rel).lower()
        for prefix, framework in _WEB_CONFIGS:
            if name.startswith(prefix):
                found.add(rel, f"{framework} configuration", 0.85)
    if len(html) >= 3:
        _aggregate(found, html, "HTML pages", 0.6)
    for rel in tree.named("manifest.webmanifest", "site.webmanifest"):
        found.add(rel, "web app manifest", 0.6)
    return found.match()


_MANIFEST_VERSION = re.compile(r'"manifest_version"\s*:\s*(\d+)')


@register("browser_extension", "browser extension")
def _browser_extension(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.named("manifest.json")[:CANDIDATES]:
        match = _MANIFEST_VERSION.search(tree.head(rel))
        if match:
            found.add(rel, f"extension manifest (manifest_version {match.group(1)})", 0.95)
    return found.match()


_IOS_PLIST_KEYS = re.compile(
    r"<key>(UIApplication\w*|LSRequiresIPhoneOS|UILaunchStoryboardName"
    r"|UIRequiredDeviceCapabilities|UISupportedInterfaceOrientations)</key>"
)


@register("mobile_app", "mobile app project")
def _mobile_app(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.named("AndroidManifest.xml")[:CANDIDATES]:
        found.add(rel, "Android manifest", 0.95)
    for rel in tree.named("pubspec.yaml")[:CANDIDATES]:
        if re.search(r"(?m)^\s*flutter\s*:", tree.head(rel)):
            found.add(rel, "Flutter app (pubspec.yaml)", 0.95)
    for rel in tree.named("package.json")[:CANDIDATES]:
        head = tree.head(rel)
        if '"react-native"' in head:
            found.add(rel, "React Native dependency", 0.9)
        if re.search(r'"expo"\s*:', head):
            found.add(rel, "Expo dependency", 0.9)
    for rel in tree.named("app.json")[:CANDIDATES]:
        if '"expo"' in tree.head(rel):
            found.add(rel, "Expo app configuration", 0.8)
    for rel in tree.matching(r"(^|/)capacitor\.config\.(json|ts|js)$|(^|/)ionic\.config\.json$"):
        found.add(rel, "Capacitor or Ionic configuration", 0.85)
    for rel in tree.named("Info.plist")[:CANDIDATES]:
        if _IOS_PLIST_KEYS.search(tree.head(rel)):
            found.add(rel, "iOS app Info.plist", 0.85)
    android = {_parent(rel) for rel in tree.dirs_named("android")}
    for parent in sorted(android & {_parent(rel) for rel in tree.dirs_named("ios")}):
        found.add(parent, "android/ and ios/ app folders side by side", 0.75)
    return found.match()


@register("jupyter_notebooks", "Jupyter notebooks")
def _jupyter_notebooks(tree: Tree) -> Match | None:
    found = Findings()
    notebooks = tree.suffixed(".ipynb")
    for rel in notebooks[:CANDIDATES]:
        head = tree.head(rel)
        if '"nbformat"' in head or '"cells"' in head:
            found.add(rel, "Jupyter notebook (nbformat JSON)", 0.95)
        else:
            found.add(rel, ".ipynb whose head is not notebook JSON", 0.5)
    _aggregate(found, notebooks[CANDIDATES:], "more notebooks, not opened", 0.7)
    return found.match()


_DOC_SUFFIXES = (".md", ".mdx", ".markdown", ".rst", ".adoc", ".asciidoc")
_NOT_DOCS = re.compile(
    r"(^|/)(readme|changelog|changes|history|license|licence|copying|contributing"
    r"|code_of_conduct|security|notice|authors|skill|claude|claude\.local|agents|gemini)"
    r"(\.[^/]*)?$|(^|/)\.(github|claude|cursor|clinerules|claude-plugin)/",
    re.IGNORECASE,
)
_DOC_GENERATORS = (
    (r"(^|/)mkdocs\.ya?ml$", "MkDocs configuration"),
    (r"(^|/)book\.toml$", "mdBook configuration"),
    (r"(^|/)docusaurus\.config\.[cm]?[jt]s$", "Docusaurus configuration"),
    (r"(^|/)docs?/(source/)?conf\.py$", "Sphinx configuration (named only, never run)"),
    (r"(^|/)antora\.ya?ml$", "Antora component"),
    (r"(^|/)\.readthedocs\.ya?ml$", "Read the Docs configuration"),
    (r"(^|/)_toc\.ya?ml$", "Jupyter Book table of contents"),
    (r"(^|/)\.vitepress/config\.[cm]?[jt]s$", "VitePress configuration"),
)
_DOC_DIRS = ("docs", "doc", "documentation", "wiki", "guides", "manual", "handbook")


@register("documentation_set", "documentation set")
def _documentation_set(tree: Tree) -> Match | None:
    found = Findings()
    for pattern, signal in _DOC_GENERATORS:
        for rel in tree.matching(pattern)[:CANDIDATES]:
            found.add(rel, signal, 0.9)
    docs = [rel for rel in tree.suffixed(*_DOC_SUFFIXES) if not _NOT_DOCS.search(rel)]
    for directory in tree.dirs_named(*_DOC_DIRS):
        inside = [rel for rel in docs if rel.startswith(directory + "/")]
        if inside:
            found.add(directory, f"{len(inside)} document(s) under {directory}/", 0.75 if len(inside) >= 2 else 0.5)
    if len(docs) >= 3:
        share = len(docs) / len(tree.files)
        _aggregate(found, docs, "prose documents (Markdown, reStructuredText, AsciiDoc)", 0.75 if share >= 0.5 else 0.55)
    elif docs and len(docs) == len(tree.files):
        _aggregate(found, docs, "prose document(s) and nothing else", 0.6)
    return found.match()


_ZIP = b"PK\x03\x04"
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_OFFICE: dict[str, tuple[str, bytes | None]] = {
    ".docx": ("Word document", _ZIP),
    ".xlsx": ("Excel workbook", _ZIP),
    ".pptx": ("PowerPoint presentation", _ZIP),
    ".odt": ("OpenDocument text", _ZIP),
    ".ods": ("OpenDocument spreadsheet", _ZIP),
    ".odp": ("OpenDocument presentation", _ZIP),
    ".pdf": ("PDF document", b"%PDF-"),
    ".doc": ("legacy Word document", _OLE),
    ".xls": ("legacy Excel workbook", _OLE),
    ".ppt": ("legacy PowerPoint presentation", _OLE),
    ".rtf": ("RTF document", b"{\\rtf"),
}


@register("office_documents", "office documents")
def _office_documents(tree: Tree) -> Match | None:
    found = Findings()
    _typed_files(tree, found, _OFFICE, verified=0.9, unverified=0.6)
    return found.match()


_DATA_BINARY: dict[str, tuple[str, bytes | None]] = {
    ".parquet": ("Parquet table", b"PAR1"),
    ".sqlite": ("SQLite database", b"SQLite format 3\x00"),
    ".sqlite3": ("SQLite database", b"SQLite format 3\x00"),
    ".db3": ("SQLite database", b"SQLite format 3\x00"),
    ".arrow": ("Arrow table", b"ARROW1"),
    ".feather": ("Feather table", b"ARROW1"),
}


@register("dataset", "dataset")
def _dataset(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.suffixed(".csv", ".tsv", ".tab")[:CANDIDATES]:
        lines = [line for line in tree.head(rel).splitlines() if line.strip()][:2]
        delimiter = "," if rel.lower().endswith(".csv") else "\t"
        columns = [line.count(delimiter) for line in lines]
        if len(columns) == 2 and columns[0] and columns[0] == columns[1]:
            found.add(rel, f"delimited table, {columns[0] + 1} columns", 0.85)
        elif lines:
            found.add(rel, "delimited text", 0.55)
    for rel in tree.suffixed(".jsonl", ".ndjson")[:CANDIDATES]:
        first = next((line.strip() for line in tree.head(rel).splitlines() if line.strip()), "")
        if first[:1] in ("{", "["):
            found.add(rel, "JSON lines", 0.85)
        else:
            found.add(rel, "named as JSON lines", 0.5)
    _typed_files(tree, found, _DATA_BINARY, verified=0.9, unverified=0.6)
    for rel in tree.suffixed(".db")[:CANDIDATES]:
        if tree.head_bytes(rel, 16) == b"SQLite format 3\x00":
            found.add(rel, "SQLite database (file signature verified)", 0.9)
    return found.match()


_TOKEN_FILES = r"(^|/)((design[-_])?tokens|[^/]+\.tokens)\.(json|ya?ml)$|(^|/)[^/]+\.tokens$"
_TOKEN_VALUE = re.compile(r'"\$?(value|type)"\s*:|^\s*\$?value\s*:', re.MULTILINE)
_CUSTOM_PROPERTY = re.compile(r"(?<![\w-])--[A-Za-z][\w-]*\s*:")
_SASS_VARIABLE = re.compile(r"(?m)^\s*\$[A-Za-z][\w-]*\s*:")


@register("design_tokens", "design tokens and style system")
def _design_tokens(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.matching(_TOKEN_FILES)[:CANDIDATES]:
        if _TOKEN_VALUE.search(tree.head(rel)):
            found.add(rel, "design token file with token values", 0.9)
        else:
            found.add(rel, "design token file", 0.65)
    for directory in tree.dirs_named("tokens", "design-tokens", "design_tokens"):
        if any(rel.lower().endswith((".json", ".yaml", ".yml")) for rel in tree.under(directory)):
            found.add(directory, "tokens/ folder", 0.7)
    for rel in tree.matching(r"(^|/)tailwind\.config\.[cm]?[jt]s$"):
        found.add(rel, "Tailwind configuration", 0.85)
    for rel in tree.matching(r"(^|/)(style-dictionary|sd)\.config\.([cm]?[jt]s|json)$"):
        found.add(rel, "Style Dictionary configuration", 0.85)
    styles = tree.suffixed(".css", ".scss", ".sass", ".less", ".pcss")
    for rel in _prefer(styles, r"token|var|theme|root|base|global")[:CANDIDATES]:
        head = tree.head(rel)
        properties = len(_CUSTOM_PROPERTY.findall(head))
        if properties >= 3:
            weight = 0.65 if ":root" in head else 0.55
            found.add(rel, f"{properties} CSS custom properties in its head", weight)
        elif re.search(r"(?m)^\s*@theme\b", head):
            found.add(rel, "Tailwind @theme block", 0.75)
        elif len(_SASS_VARIABLE.findall(head)) >= 5:
            found.add(rel, "Sass variables", 0.5)
    return found.match()


_IMAGES = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".tif", ".tiff", ".ico", ".heic",
    ".heif", ".avif", ".psd",
)
_AUDIO = (
    ".mp3", ".wav", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".aac", ".aif", ".aiff", ".wma",
    ".mid", ".midi",
)
_VIDEO = (".mp4", ".m4v", ".mov", ".mkv", ".webm", ".avi", ".wmv", ".mpg", ".mpeg", ".flv", ".3gp")


def _media(noun: str, suffixes: tuple[str, ...]) -> Recogniser:
    """Media are known by extension; how much of the tree they are decides the confidence."""

    def recognise(tree: Tree) -> Match | None:
        paths = tree.suffixed(*suffixes)
        if not paths:
            return None
        found = Findings()
        share = len(paths) / len(tree.files)
        weight = min(0.95, 0.35 + 0.6 * share)
        first: dict[str, str] = {}
        for rel in paths:
            first.setdefault(extension_of(rel), rel)
        for ext, count in Counter(extension_of(rel) for rel in paths).most_common():
            found.add(first[ext], f"{count} {ext} {noun} file(s), {share:.0%} of the tree's files", weight)
        return found.match()

    return recognise


register("images", "images")(_media("image", _IMAGES))
register("audio", "audio")(_media("audio", _AUDIO))
register("video", "video")(_media("video", _VIDEO))


_DOCKERFILE = r"(^|/)(dockerfile|containerfile)(\.[^/]*)?$|\.dockerfile$"
_DOCKER_FROM = re.compile(r"(?im)^\s*FROM\s+\S")
_COMPOSE = r"(^|/)(docker-)?compose(\.[\w-]+)?\.ya?ml$"
_SYSTEMD_SECTION = re.compile(r"(?m)^\[(Unit|Service|Timer|Socket|Mount|Path|Install)\]")
_TERRAFORM_BLOCK = re.compile(r"(?m)^\s*(resource|provider|module|terraform|variable|output|data|locals)\b")
_K8S_API = re.compile(r"(?m)^apiVersion:\s*\S")
_K8S_KIND = re.compile(r"(?m)^kind:\s*(\w+)")


@register("infrastructure", "container and infrastructure definitions")
def _infrastructure(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.matching(_DOCKERFILE)[:CANDIDATES]:
        found.add(rel, "container image definition", 0.95 if _DOCKER_FROM.search(tree.head(rel)) else 0.7)
    for rel in tree.matching(_COMPOSE)[:CANDIDATES]:
        found.add(rel, "Compose services", 0.95 if "services:" in tree.head(rel) else 0.7)
    units = tree.suffixed(".service", ".timer", ".socket", ".mount", ".path", ".target")
    for rel in units[:CANDIDATES]:
        if _SYSTEMD_SECTION.search(tree.head(rel)):
            found.add(rel, "systemd unit", 0.9)
    for rel in tree.suffixed(".tf", ".tf.json")[:CANDIDATES]:
        found.add(rel, "Terraform configuration", 0.9 if _TERRAFORM_BLOCK.search(tree.head(rel)) else 0.7)
    for rel in tree.suffixed(".tfvars")[:CANDIDATES]:
        found.add(rel, "Terraform variables", 0.6)
    for rel in tree.named("Chart.yaml")[:CANDIDATES]:
        found.add(rel, "Helm chart", 0.9 if "apiVersion" in tree.head(rel) else 0.6)
    manifests = _prefer(tree.suffixed(".yaml", ".yml"), r"k8s|kube|deploy|manifest|helm|chart")
    for rel in manifests[:CANDIDATES]:
        head = tree.head(rel)
        kind = _K8S_KIND.search(head)
        if kind and _K8S_API.search(head):
            found.add(rel, f"Kubernetes manifest (kind: {kind.group(1)})", 0.8)
    return found.match()


_CI = (
    (r"(^|/)\.gitlab-ci\.ya?ml$", "GitLab CI pipeline", 0.95),
    (r"(^|/)\.circleci/config\.ya?ml$", "CircleCI configuration", 0.95),
    (r"(^|/)jenkinsfile$", "Jenkins pipeline", 0.9),
    (r"(^|/)azure-pipelines\.ya?ml$", "Azure Pipelines", 0.9),
    (r"(^|/)\.travis\.ya?ml$", "Travis CI configuration", 0.9),
    (r"(^|/)bitbucket-pipelines\.ya?ml$", "Bitbucket Pipelines", 0.9),
    (r"(^|/)\.buildkite/[^/]+\.ya?ml$", "Buildkite pipeline", 0.9),
    (r"(^|/)\.woodpecker(\.ya?ml|/[^/]+\.ya?ml)$", "Woodpecker CI pipeline", 0.9),
    (r"(^|/)\.drone\.ya?ml$", "Drone CI pipeline", 0.9),
)


@register("ci_workflows", "CI workflows")
def _ci_workflows(tree: Tree) -> Match | None:
    found = Findings()
    for rel in tree.matching(r"(^|/)\.github/workflows/[^/]+\.ya?ml$")[:CANDIDATES]:
        head = tree.head(rel)
        has_jobs = re.search(r"(?m)^jobs\s*:", head) is not None
        found.add(rel, "GitHub Actions workflow", 0.95 if has_jobs else 0.8)
    for pattern, signal, weight in _CI:
        for rel in tree.matching(pattern)[:CANDIDATES]:
            found.add(rel, signal, weight)
    return found.match()
