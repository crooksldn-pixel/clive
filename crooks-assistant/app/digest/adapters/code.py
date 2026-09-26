"""The code adapter: a source repository — Python, JavaScript and TypeScript, and the manifests
beside them — read into Units.

Reading is all it does. Python is parsed with the ast module, which reads source without
importing or running a line of it; JavaScript and TypeScript are read by pattern, with comments
set aside first so that commented-out code is not mistaken for code, and a file whose comments,
strings or brackets do not close, or an export that cannot be made out, is reported
rather than guessed at; pyproject.toml, setup.cfg, requirements files and package.json are
parsed as the data they are, and an entry of the wrong shape is reported, not recorded as one.
Nothing found is imported, installed or run — a package.json script is recorded as a script and
left there — and nothing outside the artifact is followed: symbolic links are noted, never
walked.

What comes out:
  capability  a public module, function or command that can be called from outside: a
              command-line entry (a __main__ block, a console script, an argparse parser or
              subcommand, a click or typer command, a package.json bin) or an exported function
  pattern     a public module, class or function that is not an entry point
  dependency  a declared requirement, with its version constraint as written
  script      a package.json script, as written
  check       a test file, naming what it tests and the tests in it
  knowledge   the repository map, first; and, tagged 'unparsed', everything that could not be
              read, with the reason

Every read is bounded — files walked, entries looked at, directories and their depth, bytes per
file and in all, Units made — and meeting a bound is itself reported as 'unparsed'; and every
pattern is written to take time in proportion to the text it reads, however that text is made. The same tree gives the same
Units in the same order wherever it is on disk: nothing about the machine, the clock or the
absolute path goes into a Unit. Malformed input never raises; only a malformed artifact id,
which is the caller's mistake rather than the artifact's, does."""

from __future__ import annotations

import ast
import configparser
import json
import os
import re
import stat
import sys
import tomllib
import warnings
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from app.digest.model import ARTIFACT_ID_PATTERN, MAX_BODY, MAX_TAG, MAX_TITLE, Location, Unit

NAME = "code"
HANDLES = ("source_code", "python_package", "node_package")

MAX_FILES = 5_000               # files walked; the rest are not read
MAX_DIRECTORIES = 2_000
MAX_ENTRIES = 50_000            # files, directories, links and the rest looked at, in all
MAX_DEPTH = 24
MAX_FILE_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_UNITS = 5_000
MAX_LISTED = 60                 # lines one list in a body takes before the rest are counted
MAX_SIGNATURE = 600

# Version control, caches and vendored trees: noted in the map, not entered.
_NOT_WALKED = frozenset((
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".nox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "site-packages",
))
_JS_SUFFIXES = frozenset((".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".mts", ".cts"))
_LANGUAGES = {
    ".py": "Python", ".pyi": "Python",
    ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript", ".jsx": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".mts": "TypeScript", ".cts": "TypeScript",
    ".go": "Go", ".rs": "Rust", ".java": "Java", ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP",
    ".c": "C", ".h": "C", ".cc": "C++", ".cpp": "C++", ".hpp": "C++", ".cs": "C#",
    ".swift": "Swift", ".scala": "Scala", ".dart": "Dart", ".lua": "Lua", ".sh": "Shell",
    ".bash": "Shell", ".sql": "SQL", ".html": "HTML", ".css": "CSS", ".scss": "CSS",
    ".vue": "Vue", ".svelte": "Svelte",
}
_TEST_TOOLS = frozenset(("__future__", "pytest", "unittest", "hypothesis", "mock"))
_JS_TEST_DIRS = frozenset(("test", "tests", "__tests__"))
_NPM_DEPENDENCIES = ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies")

# A requirement is one line (a newline in one is refused before this is tried), and the name
# and the space around it give nothing back, so no requirement makes the match backtrack.
_REQUIREMENT = re.compile(
    r"\s*+(?P<name>(?>[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?))\s*+(?P<extras>\[[^\]]*\])?"
    r"\s*+(?P<rest>[^;]*)(?:;(?P<marker>.*))?"
)
# Where a comment starts on a requirements or setup.cfg line: at a # after a space. Found by
# one scan, where splitting on \s+# tried each space of a long run afresh.
_COMMENT = re.compile(r"\s#")
_OPTION_TAIL = re.compile(r"\s--")
_TOML_HEADER = re.compile(r"^\s*\[\[?[^\[\],=]+\]\]?\s*(?:#.*)?$")
# A table's [header], its dotted parts one by one, and a key at the start of a line: written
# bare, in double quotes or in single quotes.
_TOML_TABLE_LINE = re.compile(r"\s*+\[(?!\[)(?P<inside>[^\[\]\n]*+)\]\s*+(?:#.*)?")
_TOML_PART = re.compile(r"""\s*+(?:"([^"\n]*)"|'([^'\n]*)'|([^\s."'\[\]#]++))\s*+""")
_TOML_KEY = re.compile(r"""\s*+(?:"([^"\n]*)"|'([^'\n]*)'|([A-Za-z0-9_-]++))\s*+=""")
_QUOTED = re.compile(r""""([^"\n]*)"|'([^'\n]*)'""")
_INI_HEADER = re.compile(r"^\s*\[[^\]]*\]\s*$")
# An entry point's object reference, as importlib.metadata reads one: module[:attr] [extras].
_ENTRY_POINT = re.compile(r"[\w.]+\s*(?::\s*[\w.]+\s*)?(?:\[.*\]\s*)?")
# What a Poetry dependency table takes its version or its source from.
_POETRY_SOURCES = ("version", "git", "path", "url", "file")

# Patterns here are written so that no text makes them backtrack without bound: where two
# parts could match the same characters, the first takes them all and gives none back (*+, ++),
# and the alternatives inside a repeat never match the same character. A pattern read over a
# long line of spaces or backslashes must take time in proportion to it, not its square or more.
_JS_NAME = r"[A-Za-z_$][\w$]*"
_JS_WHOLE_NAME = r"[A-Za-z_$][\w$]*+"      # the name and all of it: nothing given back
_JS_IDENTIFIER = re.compile(_JS_NAME)
_JS_TAIL = rf"[ \t]*=[ \t]*(?:async\b[ \t]*)?(?P<form>function\b|\(|<|{_JS_NAME}[ \t]*=>)"
_JS_FUNCTION = re.compile(
    r"^[ \t]*export[ \t]+(?:declare[ \t]+)?(?P<default>default[ \t]+)?(?:async[ \t]+)?"
    rf"function\b[ \t]*\*?[ \t]*(?P<name>{_JS_NAME})?",
    re.M,
)
_JS_CLASS = re.compile(
    r"^[ \t]*export[ \t]+(?:declare[ \t]+)?(?P<default>default[ \t]+)?(?:abstract[ \t]+)?"
    rf"class\b[ \t]*(?P<name>{_JS_NAME})?",
    re.M,
)
_JS_CONST = re.compile(
    rf"^[ \t]*export[ \t]+(?:const|let|var)[ \t]+(?P<name>{_JS_WHOLE_NAME})[^=\n]*+{_JS_TAIL}",
    re.M,
)
_JS_COMMONJS = re.compile(rf"^[ \t]*(?:module\.)?exports\.(?P<name>{_JS_NAME}){_JS_TAIL}", re.M)
# Declarations at the left margin — top level, by the usual layout — that an export list names.
_JS_LOCAL = re.compile(
    rf"^(?:async[ \t]+)?(?P<what>function|class)\b[ \t]*+\*?[ \t]*+(?P<name>{_JS_NAME})", re.M
)
_JS_LOCAL_CONST = re.compile(
    rf"^(?:const|let|var)[ \t]+(?P<name>{_JS_WHOLE_NAME})[^=\n]*+{_JS_TAIL}", re.M
)
_JS_EXPORT_LIST = re.compile(r"^[ \t]*export[ \t]*\{(?P<names>[^}]*)\}", re.M)
_JS_MODULE_EXPORTS = re.compile(r"^[ \t]*module\.exports[ \t]*=[ \t]*\{(?P<names>[^}]*)\}", re.M)
_JS_EXPORT_DEFAULT_NAME = re.compile(
    rf"^[ \t]*export[ \t]+default[ \t]+(?P<name>{_JS_WHOLE_NAME})[ \t]*+;?[ \t]*+$", re.M
)
_JS_MODULE_EXPORTS_NAME = re.compile(
    rf"^[ \t]*module\.exports[ \t]*=[ \t]*(?P<name>{_JS_WHOLE_NAME})[ \t]*+;?[ \t]*+$", re.M
)
_JS_ALIAS = re.compile(rf"(?:type[ \t]+)?(?P<local>{_JS_NAME})(?:\s+as\s+(?P<alias>{_JS_NAME}))?")
_JS_PROPERTY = re.compile(rf"(?P<alias>{_JS_NAME})(?:\s*:\s*(?P<local>{_JS_NAME}))?")
_ARROW = re.compile(r"\s*(?::[^=;{]*)?=>")
_JS_TEST_CALL = re.compile(
    r"""\b(?P<fn>describe|it|test)(?:\.(?:only|skip|todo|concurrent))?\s*+\(\s*+"""
    r"""(?P<q>['"`])(?P<title>(?:\\.|(?!(?P=q))[^\\\n])*+)(?P=q)"""
)
_JS_IMPORT = re.compile(
    r"""(?:\bfrom|\bimport|\brequire)\s*+(?:\(\s*+)?(?P<q>['"])(?P<spec>[^'"\n]++)(?P=q)"""
)
# What a well-formed class must have after its name, within _CLASS_HEADING characters: a body,
# before any line that begins a declaration of its own.
_CLASS_HEADING = 2_000
_JS_CLASS_STOP = re.compile(r"[;{}]")
_JS_DECLARATION_WORD = re.compile(r"\b(?:export|import|class|function|const|let|var)\b")
# A function expression's generator star and name, before its parameters.
_JS_FUNCTION_NAME = re.compile(rf"\s*\*?\s*(?:{_JS_NAME})?")
# An export by keyword; the keywords an export may begin with.
_JS_EXPORT_WORD = re.compile(rf"^[ \t]*export[ \t]+(?P<word>{_JS_NAME})", re.M)
_JS_EXPORT_WORDS = frozenset((
    "default", "function", "async", "class", "abstract", "declare", "interface", "type", "enum",
    "namespace", "module", "import", "as", "const", "let", "var",
))
# Words that begin a declaration, not a value: after `=`, one of these means the value is missing.
_NOT_A_VALUE = frozenset(("export", "const", "let", "var"))
# What must come next for an export begun with one of these keywords to be complete.
_JS_NAMED = re.compile(rf"\s*{_JS_NAME}")
_JS_EXPORT_FOLLOWS = {
    "default": re.compile(r"""\s*[\w$'"`(\[{!~+\-/<@.]"""),
    "async": re.compile(r"\s+function\b"),
    "abstract": re.compile(r"\s+class\b"),
    "as": re.compile(r"\s+namespace\b"),
    "type": re.compile(rf"\s*(?:[{{*]|{_JS_NAME})"),
    "namespace": re.compile(rf"""\s*(?:{_JS_NAME}|['"])"""),
    "module": re.compile(rf"""\s*(?:{_JS_NAME}|['"])"""),
    "declare": _JS_NAMED, "interface": _JS_NAMED, "enum": _JS_NAMED, "import": _JS_NAMED,
}
# Words that join TypeScript types, after which a type is still wanted.
_TYPE_OPERATORS = frozenset((
    "keyof", "typeof", "infer", "readonly", "unique", "asserts", "is", "extends", "new",
    "abstract",
))
_RETURN_TYPE = re.compile(r"\s*:")
_BRACKETS = {"(": ")", "[": "]", "{": "}"}
# A / after one of these, or after one of these words, opens a regular expression; else it divides.
_REGEX_AFTER = frozenset("(,=:[!&|?{};+-*%>~^")
_REGEX_KEYWORDS = frozenset((
    "return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw",
    "yield", "await", "instanceof",
))
# A / that may open a regular expression is followed to its close, to the end of its line or
# _REGEX_REACH characters on; the following, over the whole file, is bounded by its length, so a
# long line of [/ cannot be walked a thousand times over. A file that needs more is not read.
_REGEX_REACH = 1_000
_REGEX_SCAN_FACTOR = 4
_REGEX_SCAN_SLACK = 10_000
_TOO_MANY_SLASHES = (
    "more / that may open regular expressions than this reader follows, so its strings and "
    "brackets cannot be told apart"
)


class _Malformed(ValueError):
    """Input that parsed but is not the shape its format requires."""


def decompose(root: Path, artifact_id: str) -> list[Unit]:
    """The Units of the quarantined repository at root, read and never run: the repository map
    first, then everything else in path and line order. What cannot be read is skipped and said
    so in a knowledge Unit tagged 'unparsed'; nothing in the artifact makes this raise."""
    if not isinstance(artifact_id, str) or not re.fullmatch(ARTIFACT_ID_PATTERN, artifact_id):
        raise ValueError(f"artifact_id does not match {ARTIFACT_ID_PATTERN}: {artifact_id!r}")
    units = _Units(artifact_id)
    digest = _Digest(os.fspath(root), units)
    for step in (digest.run, digest.repository_map):
        try:
            step()
        except Exception as exc:  # the backstop: whatever went wrong is said, never raised
            units.add(
                "knowledge", "Unparsed: .",
                f"the adapter stopped part-way ({type(exc).__name__}); what it read before then "
                "is kept", ".", tags=("unparsed",), force=True,
            )
    return units.ordered()


# --- the Units made ----------------------------------------------------------------------------


class _Units:
    """The one place Units are made: every title, body and tag is held to the model's bounds
    here, and their number to MAX_UNITS."""

    def __init__(self, artifact_id: str) -> None:
        self.artifact_id = artifact_id
        self.made: list[Unit] = []
        self.head: list[Unit] = []
        self.full = False

    def add(self, kind: str, title: str, body: str, path: str, start: int | None = None,
            end: int | None = None, tags: tuple[str, ...] = (), *, first: bool = False,
            force: bool = False) -> None:
        if not force and len(self.made) >= MAX_UNITS:
            self.full = True
            return
        if start is None:
            end = None
        else:
            start = max(1, start)
            end = max(start, end if end is not None else start)
        where = Location(path if _safe(path) == path else ".", start, end)
        unit = Unit(
            artifact_id=self.artifact_id, kind=kind, title=_title(_safe(title)),
            body=_clip(_safe(body)), location=where, tags=_tags(tuple(_safe(tag) for tag in tags)),
        )
        (self.head if first else self.made).append(unit)

    def unparsed(self, path: str, reason: str, line: int | None = None) -> None:
        self.add("knowledge", f"Unparsed: {path}", reason, path, line, line, ("unparsed",))

    def ordered(self) -> list[Unit]:
        if self.full:
            self.add(
                "knowledge", "Unparsed: .",
                f"stopped at {MAX_UNITS} Units; the rest of the artifact was not decomposed",
                ".", tags=("unparsed", "limit"), force=True,
            )
            self.full = False
        units: list[Unit] = []
        seen: set[str] = set()
        for unit in [*self.head, *sorted(self.made, key=_order)]:
            if unit.id not in seen:
                seen.add(unit.id)
                units.append(unit)
        return units


def _order(unit: Unit) -> tuple:
    where = unit.location
    return (where.path, where.line_start or 0, where.line_end or 0, unit.kind, unit.title,
            unit.body, unit.tags)


def _safe(text: str) -> str:
    """Text that can be written as UTF-8, and so be given an id and stored: a lone surrogate —
    which a JSON or Python escape, or a file name that is not UTF-8, can put in a string — is
    shown escaped instead."""
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def _clip(text: str, limit: int = MAX_BODY) -> str:
    if len(text) <= limit:
        return text
    marker = "\n… (cut here: longer than a Unit may hold)"
    return text[: limit - len(marker)] + marker


def _title(text: str) -> str:
    title = " ".join(text.split()) or "untitled"
    return title if len(title) <= MAX_TITLE else title[: MAX_TITLE - 1] + "…"


def _tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    kept: list[str] = []
    for tag in tags:
        clean = " ".join(tag.split())[:MAX_TAG]
        if clean and clean not in kept:
            kept.append(clean)
    return tuple(kept)


def _listed(items: list[str]) -> list[str]:
    if len(items) <= MAX_LISTED:
        return items
    return [*items[:MAX_LISTED], f"- … and {len(items) - MAX_LISTED} more"]


def _reason(exc: Exception) -> str:
    if isinstance(exc, (RecursionError, MemoryError)):
        return f"nested too deeply to be read ({type(exc).__name__}); skipped"
    if isinstance(exc, SyntaxError):
        where = f" at line {exc.lineno}" if exc.lineno else ""
        return f"not valid Python{where}: {exc.msg}; skipped"
    if isinstance(exc, (ValueError, configparser.Error)):
        return f"could not be parsed: {exc}; skipped"
    return f"could not be read ({type(exc).__name__}); skipped"


# --- the walk and the reads --------------------------------------------------------------------


class _Digest:
    def __init__(self, root: str, units: _Units) -> None:
        self.root = root
        self.base = root                    # the directory the relative paths are under
        self.units = units
        self.files: list[str] = []          # relative POSIX paths, sorted
        self.links: list[str] = []
        self.not_walked: list[str] = []
        self.bytes_read = 0
        self.entry_points: list[str] = []
        self.console_scripts: list[tuple[str, str, str]] = []    # (module, function, script)

    def run(self) -> None:
        self._walk()
        manifests: dict[str, Callable[[str, str], None]] = {
            "pyproject.toml": self._pyproject,
            "setup.cfg": self._setup_cfg,
            "package.json": self._package_json,
        }
        # Manifests first: a console script marks the function it names as a command-line entry.
        for path in self.files:
            name = _name(path)
            if name in manifests:
                self._read(path, manifests[name])
            elif _is_requirements(path):
                self._read(path, self._requirements)
        for path in self.files:
            suffix = _suffix(path)
            if suffix == ".py":
                self._read(path, self._python)
            elif suffix in _JS_SUFFIXES and not _name(path).endswith(".min.js"):
                self._read(path, self._javascript)

    def _walk(self) -> None:
        """Every regular file under the root, in a fixed order. Links are noted and not
        followed, the root among them; caches and vendored trees are noted and not entered; a
        name that is not UTF-8 is noted and not read. A root that is one regular file is read as
        a repository of that file. Every entry looked at counts towards MAX_ENTRIES, and a
        directory holding more than that is passed over whole, so what is read never depends on
        the order the disk lists entries in."""
        try:
            info = os.lstat(self.root)
        except OSError as exc:
            self.units.unparsed(".", f"the artifact could not be read ({type(exc).__name__})")
            return
        if stat.S_ISLNK(info.st_mode):
            self.units.unparsed(".", "the artifact is a symbolic link; not followed")
            return
        if stat.S_ISREG(info.st_mode):
            name = os.path.basename(self.root)
            if _safe(name) != name:
                self.units.unparsed(".", f"a name that is not UTF-8 was not read: {name!r}")
            else:
                self.base = os.path.dirname(self.root)
                self.files.append(name)
            return
        if not stat.S_ISDIR(info.st_mode):
            self.units.unparsed(".", "the artifact is neither a directory nor a regular file")
            return
        stack: list[tuple[str, int]] = [("", 0)]
        directories = looked = 0
        while stack:
            rel, depth = stack.pop()
            directories += 1
            if directories > MAX_DIRECTORIES:
                self.units.unparsed(
                    ".", f"stopped after {MAX_DIRECTORIES} directories; the rest were not read"
                )
                break
            entries = self._listing(rel)
            below: list[str] = []
            for entry in entries:
                looked += 1
                if looked > MAX_ENTRIES:
                    self.units.unparsed(
                        ".", f"stopped after {MAX_ENTRIES} files, directories and links; the "
                        "rest were not read",
                    )
                    stack.clear()
                    below.clear()
                    break
                path = f"{rel}/{entry.name}" if rel else entry.name
                if _safe(entry.name) != entry.name:
                    self.units.unparsed(
                        rel or ".", f"a name that is not UTF-8 was not read: {entry.name!r}"
                    )
                    continue
                try:
                    if entry.is_symlink():
                        self.links.append(path)
                    elif entry.is_dir(follow_symlinks=False):
                        if entry.name in _NOT_WALKED:
                            self.not_walked.append(path)
                        elif depth >= MAX_DEPTH:
                            self.units.unparsed(path, f"deeper than {MAX_DEPTH} directories; not read")
                        else:
                            below.append(path)
                    elif entry.is_file(follow_symlinks=False):
                        if len(self.files) >= MAX_FILES:
                            self.units.unparsed(
                                ".", f"stopped after {MAX_FILES} files; the rest were not read"
                            )
                            stack.clear()
                            below.clear()
                            break
                        self.files.append(path)
                except OSError as exc:
                    self.units.unparsed(path, f"could not be examined ({type(exc).__name__})")
            stack.extend((sub, depth + 1) for sub in reversed(below))
        self.files.sort()

    def _listing(self, rel: str) -> list[os.DirEntry[str]]:
        """A directory's entries by name; none, and said so, when it cannot be listed or holds
        more than MAX_ENTRIES — which are not all read into memory to find that out."""
        entries: list[os.DirEntry[str]] = []
        try:
            with os.scandir(os.path.join(self.base, rel)) as listing:
                for entry in listing:
                    entries.append(entry)
                    if len(entries) > MAX_ENTRIES:
                        self.units.unparsed(
                            rel or ".", f"holds more than {MAX_ENTRIES} entries; not read"
                        )
                        return []
        except OSError as exc:
            self.units.unparsed(rel or ".", f"could not be listed ({type(exc).__name__})")
            return []
        return sorted(entries, key=lambda entry: entry.name)

    def _text(self, path: str) -> tuple[str | None, str]:
        """The file's text, or None and why not. The file is opened without following a link
        or waiting on a pipe — whatever it was when the walk saw it — and is checked as opened,
        so nothing swapped in after the walk is read in its place."""
        full = os.path.join(self.base, *path.split("/"))
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        allowance = MAX_TOTAL_BYTES - self.bytes_read
        spent = f"the {MAX_TOTAL_BYTES}-byte reading budget was spent; not read"
        try:
            with open(os.open(full, flags), "rb") as handle:
                info = os.fstat(handle.fileno())
                if not stat.S_ISREG(info.st_mode):
                    return None, "not a regular file; not read"
                if info.st_size > MAX_FILE_BYTES:
                    return None, f"larger than {MAX_FILE_BYTES} bytes; not read"
                if info.st_size > allowance:
                    return None, spent
                data = handle.read(min(MAX_FILE_BYTES, allowance) + 1)
        except OSError as exc:
            return None, f"could not be read ({type(exc).__name__})"
        self.bytes_read += len(data)
        if len(data) > MAX_FILE_BYTES:
            return None, f"larger than {MAX_FILE_BYTES} bytes; not read"
        if len(data) > allowance:
            return None, spent
        try:
            return data.decode("utf-8-sig"), ""
        except UnicodeDecodeError:
            return None, "not UTF-8 text; not read"

    def _read(self, path: str, read: Callable[[str, str], None]) -> None:
        text, reason = self._text(path)
        if text is None:
            self.units.unparsed(path, reason)
            return
        try:
            read(path, text)
        except Exception as exc:
            line = None
            if isinstance(exc, SyntaxError) and isinstance(exc.lineno, int) and exc.lineno > 0:
                line = exc.lineno
            self.units.unparsed(path, _reason(exc), line)

    # --- Python ----------------------------------------------------------------------------

    def _python(self, path: str, text: str) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            tree = ast.parse(text, filename=path)
        if _is_python_test(path):
            self._python_checks(path, text, tree)
            return
        module = _module_name(path)
        public = _public_module(path)
        exported = _dunder_all(tree)
        guard = _main_guard(tree)
        called: set[str] = set()
        if guard is not None:
            called = {_dotted(node.func) for node in ast.walk(guard) if isinstance(node, ast.Call)}
            self.entry_points.append(f'{path}: runs as a script (if __name__ == "__main__")')
        is_main = _name(path) == "__main__.py"
        package = module.removesuffix(".__main__")
        if is_main:
            self.entry_points.append(f"{path}: python -m {package}")
        scripts = self._scripts_for(module)
        definitions = [
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        ]

        if public:
            entry: list[str] = []
            if guard is not None:
                lines = f"{guard.lineno}–{guard.end_lineno or guard.lineno}"
                entry.append('an `if __name__ == "__main__":` block at lines ' + lines)
            if is_main:
                entry.append(f"runs as `python -m {package}`")
            for function, names in scripts.items():
                entry.append(f"console script {', '.join(names)} calls {function or 'it'}")
            names = [
                node.name for node in definitions
                if not node.name.startswith("_") and (exported is None or node.name in exported)
            ]
            parts = [f"module {module}", ast.get_docstring(tree) or "(no module docstring)"]
            if entry:
                parts.append("Command-line entry: " + "; ".join(entry) + ".")
            if exported is not None:
                parts.append("__all__: " + (", ".join(sorted(exported)) or "(empty)"))
            if names:
                parts.append("Public names: " + ", ".join(names))
            self.units.add(
                "capability" if entry else "pattern", f"module {module}", "\n\n".join(parts),
                path, 1, _line_count(text), ("python", "module", *(("cli",) if entry else ())),
            )

        for node in definitions:
            self._python_definition(
                path, module, node, public=public, exported=exported, called=called,
                scripts=scripts,
            )

        for parser in _argparse(tree):
            kind = parser["kind"]
            label = parser["name"] or (module if kind == "parser" else "(unnamed)")
            parts = [f"argparse {kind} `{label}` in module {module}; read, not run."]
            if parser["help"]:
                parts.append(parser["help"])
            if parser["arguments"]:
                parts.append("Arguments:\n" + "\n".join(_listed(parser["arguments"])))
            self.units.add(
                "capability", f"command-line {kind} {label}", "\n\n".join(parts), path,
                parser["start"], parser["end"], ("python", "cli", "argparse"),
            )

    def _python_definition(self, path: str, module: str,
                           node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, *,
                           public: bool, exported: set[str] | None, called: set[str],
                           scripts: dict[str, list[str]]) -> None:
        name = node.name
        start = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
        end = node.end_lineno or node.lineno
        signature = _signature(node)
        doc = ast.get_docstring(node) or "(no docstring)"
        visible = public and not name.startswith("_")

        if isinstance(node, ast.ClassDef):
            if not visible:
                return
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
                    not item.name.startswith("_") or item.name == "__init__"
                ):
                    summary = (ast.get_docstring(item) or "").strip().split("\n")[0]
                    methods.append(f"- {_signature(item)}" + (f" — {summary}" if summary else ""))
            parts = [signature, doc]
            if methods:
                parts.append("Methods:\n" + "\n".join(_listed(methods)))
            self.units.add(
                "pattern", f"class {module}.{name}", "\n\n".join(parts), path, start, end,
                ("python", "class"),
            )
            return

        command = _click_command(node)
        entry: list[str] = []
        if command is not None:
            what = "group" if command["group"] else "command"
            entry.append(f"click {what} `{command['name']}` (@{command['via']})")
        if name in scripts:
            entry.append(f"console script {', '.join(scripts[name])}")
        if name in called:
            entry.append("called from the module's __main__ block")
        if not (entry or visible):
            return
        is_exported = visible and (exported is None or name in exported)
        notes = []
        if is_exported and exported is not None:
            notes.append(f"Exported: listed in {module}.__all__.")
        elif is_exported:
            notes.append(f"Exported: a public name of {module}, which has no __all__.")
        elif visible:
            notes.append(f"Public, but not in {module}.__all__.")
        if entry:
            notes.append("Command-line entry: " + "; ".join(entry) + ".")
        if command is not None and command["options"]:
            notes.append("Options and arguments: " + ", ".join(command["options"]))
        tags = ("python", "function", *(("cli",) if entry else ()),
                *(("click",) if command is not None else ()))
        self.units.add(
            "capability" if entry or is_exported else "pattern",
            f"command {command['name']}" if command is not None else f"function {module}.{name}",
            "\n\n".join([signature, doc, *notes]), path, start, end, tags,
        )

    def _python_checks(self, path: str, text: str, tree: ast.Module) -> None:
        tests: list[str] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
                tests.append(f"- {node.name} (line {node.lineno})")
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test"):
                        tests.append(f"- {node.name}.{item.name} (line {item.lineno})")
        self._check(path, text, "python", _python_subjects(tree), tests)

    def _check(self, path: str, text: str, language: str, subjects: list[str],
               tests: list[str]) -> None:
        subject = _test_subject(path)
        parts = [
            f"Tests in {path}, checking {subject}.",
            "What they exercise: " + (
                "; ".join(subjects) if subjects
                else "nothing imported from the code under test was found"
            ),
        ]
        if tests:
            parts.append(f"Tests ({len(tests)}):\n" + "\n".join(_listed(tests)))
        else:
            parts.append("No test functions were found.")
        self.units.add(
            "check", f"tests for {subject}", "\n\n".join(parts), path, 1, _line_count(text),
            (language, "test"),
        )

    def _scripts_for(self, module: str) -> dict[str, list[str]]:
        found: dict[str, list[str]] = {}
        for target, function, script in self.console_scripts:
            if target and (module == target or module.endswith("." + target)):
                found.setdefault(function, []).append(script)
        return found

    # --- JavaScript and TypeScript ---------------------------------------------------------

    def _javascript(self, path: str, text: str) -> None:
        code, skeleton, blocks, unclosed = _set_aside_comments(text)
        starts = _line_starts(text)
        language = _LANGUAGES[_suffix(path)]
        tag = language.lower()
        # A file cut short or broken — a comment or template string left open, brackets that do
        # not pair — cannot be measured by its brackets: said where it breaks, and not read.
        broken = unclosed or _unbalanced(skeleton)
        if broken is not None:
            offset, what = broken
            lead = "not read" if what == _TOO_MANY_SLASHES else f"not well-formed {language}"
            self.units.unparsed(path, f"{lead}: {what}; skipped", _line_of(starts, offset))
            return

        # Every export is measured whole — test files' too — before anything is made of it: one
        # that does not end as its declaration must is said where it is, and is not read on past.
        pairs = _pairs(skeleton)
        typescript = language == "TypeScript"
        ambient = typescript and _name(path).endswith((".d.ts", ".d.mts", ".d.cts"))
        found: list[tuple[int, int, str, str, str, str]] = []
        problems: list[tuple[int, str]] = []
        for match in _JS_FUNCTION.finditer(skeleton):
            name = match.group("name") or ("default" if match.group("default") else "")
            if not name:
                problems.append((match.start(), "an exported function with no name"))
                continue
            try:
                end, signature = _function_extent(code, skeleton, pairs, match.start(), match.end(),
                                                  typescript=typescript, ambient=ambient)
            except _Malformed as exc:
                problems.append((match.start(), f"exported function {name} {exc}"))
                continue
            found.append((match.start(), end, "function", name, signature, _default_note(match)))
        for match in _JS_CLASS.finditer(skeleton):
            name = match.group("name")
            if name in (None, "extends", "implements"):
                name = "default" if match.group("default") else ""
            if not name:
                problems.append((match.start(), "an exported class with no name"))
                continue
            try:
                end, signature = _class_extent(code, skeleton, pairs, match.start(), match.end())
            except _Malformed as exc:
                problems.append((match.start(), f"exported class {name} {exc}"))
                continue
            found.append((match.start(), end, "class", name, signature, _default_note(match)))
        for match in _JS_EXPORT_WORD.finditer(skeleton):
            word = match.group("word")
            follows = _JS_EXPORT_FOLLOWS.get(word)
            reason = None
            if word not in _JS_EXPORT_WORDS or (
                follows is not None and not follows.match(skeleton, match.end("word"))
            ):
                reason = "an export this reader cannot make out"
            elif word in ("const", "let", "var"):
                reason = _binding_problem(skeleton, pairs, word, match.end("word"))
            if reason is not None:
                written = _one_line(code[match.start():_end_of_line(code, match.start())])
                problems.append((match.start(), f"{reason}: {written}"))
        for pattern in (_JS_CONST, _JS_COMMONJS):
            for match in pattern.finditer(skeleton):
                try:
                    extent = _bound_extent(code, skeleton, pairs, match)
                except _Malformed as exc:
                    problems.append((match.start(), f"exported function {match.group('name')} {exc}"))
                    continue
                if extent is not None:
                    found.append((match.start(), extent[0], "function", match.group("name"),
                                  extent[1], ""))

        declared: dict[str, tuple[int, int, str, str]] = {}
        faulty: dict[str, tuple[int, str]] = {}     # declarations that do not end as they must
        for match in _JS_LOCAL.finditer(skeleton):
            what, name = match.group("what"), match.group("name")
            try:
                if what == "function":
                    end, signature = _function_extent(
                        code, skeleton, pairs, match.start(), match.end(), typescript=typescript,
                        ambient=ambient,
                    )
                else:
                    end, signature = _class_extent(code, skeleton, pairs, match.start(), match.end())
            except _Malformed as exc:
                faulty.setdefault(name, (match.start(), f"{what} {name}, exported by name, {exc}"))
                continue
            declared.setdefault(name, (match.start(), end, what, signature))
        for match in _JS_LOCAL_CONST.finditer(skeleton):
            name = match.group("name")
            try:
                extent = _bound_extent(code, skeleton, pairs, match)
            except _Malformed as exc:
                faulty.setdefault(name, (match.start(), f"function {name}, exported by name, {exc}"))
                continue
            if extent is not None:
                declared.setdefault(name, (match.start(), extent[0], "function", extent[1]))
        for note, local in _export_lists(skeleton):
            if local in declared:
                begin, end, what, signature = declared[local]
                found.append((begin, end, what, local, signature, note))
            elif local in faulty:
                problems.append(faulty[local])

        malformed = {offset for offset, _ in problems}
        for offset, what in sorted(set(problems)):
            self.units.unparsed(path, f"{what}; skipped", _line_of(starts, offset))
        if _is_js_test(path):
            tests = [
                f"- {match.group('fn')}: {match.group('title')} "
                f"(line {_line_of(starts, match.start())})"
                for match in _JS_TEST_CALL.finditer(code)
            ]
            specs = list(dict.fromkeys(match.group("spec") for match in _JS_IMPORT.finditer(code)))
            relative = [spec for spec in specs if spec.startswith(".")]
            self._check(path, text, tag, relative or specs, tests)
            return

        docs = {
            _line_of(starts, end - 1): _jsdoc(text[start:end])
            for start, end in blocks if text.startswith("/**", start)
        }
        for begin, end, what, name, signature, note in sorted(found):
            if begin in malformed:
                continue
            first = _line_of(starts, begin)
            doc = docs.get(first - 1) or docs.get(first) or "(no doc comment)"
            where = f"Exported from {path}" + (f" ({note})" if note else "") + "."
            self.units.add(
                "capability" if what == "function" else "pattern", f"{what} {name} ({path})",
                "\n\n".join((signature, doc, where)), path, first, _line_of(starts, end),
                (tag, what, "exported"),
            )

    # --- manifests -------------------------------------------------------------------------

    def _package_json(self, path: str, text: str) -> None:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise _Malformed("package.json is not a JSON object")
        keys = _json_keys(text)
        last = _line_count(text)
        name = data.get("name")
        package = name.strip() if isinstance(name, str) and name.strip() else (
            _parent_name(path) or "package"
        )

        bins = data.get("bin")
        if isinstance(bins, str):
            self._bin(path, package, package.rpartition("/")[2], bins, _json_line(keys, "bin"), last)
        elif isinstance(bins, dict):
            for command, target in bins.items():
                self._bin(path, package, command, target, _json_line(keys, "bin", command), last)
        elif bins is not None:
            self.units.unparsed(
                path, "bin is neither a path nor an object of paths; skipped", _json_line(keys, "bin")
            )

        scripts = data.get("scripts")
        if isinstance(scripts, dict):
            for script, command in scripts.items():
                line = _json_line(keys, "scripts", script)
                if not isinstance(command, str):
                    self.units.unparsed(
                        path, f"script {script!r} is {_json_shape(command)}, not a command; "
                        "skipped", line,
                    )
                    continue
                start, end = _at(line, last)
                self.units.add(
                    "script", f"script {script}",
                    f"{command}\n\nnpm script `{script}` of {package} in {path}: "
                    "recorded as written, never run.",
                    path, start, end, ("javascript", "npm-script"),
                )
        elif scripts is not None:
            self.units.unparsed(path, "scripts is not an object; skipped", _json_line(keys, "scripts"))

        for section in _NPM_DEPENDENCIES:
            declared = data.get(section)
            if isinstance(declared, dict):
                for dependency, constraint in declared.items():
                    line = _json_line(keys, section, dependency)
                    if not dependency.strip() or not isinstance(constraint, str):
                        self.units.unparsed(
                            path, f"{section} entry {dependency!r} is {_json_shape(constraint)}, "
                            "not a package name and its version constraint; skipped", line,
                        )
                        continue
                    start, end = _at(line, last)
                    self.units.add(
                        "dependency", f"dependency {dependency}",
                        f"{dependency} {constraint}\n\nDeclared in {path} under "
                        f"{section}. Recorded, not installed.",
                        path, start, end, ("javascript", section),
                    )
            elif declared is not None:
                self.units.unparsed(
                    path, f"{section} is not an object; skipped", _json_line(keys, section)
                )

        main = data.get("main")
        if isinstance(main, str) and main.strip():
            self.entry_points.append(f"{main.strip()}: main module of {package} ({path})")

    def _bin(self, path: str, package: str, command: str, target: object, line: int | None,
             last: int) -> None:
        if not command.strip() or not isinstance(target, str) or not target.strip():
            self.units.unparsed(
                path, f"bin entry {command!r} is {_json_shape(target)}, not a command name and "
                "the path it runs; skipped", line,
            )
            return
        start, end = _at(line, last)
        self.entry_points.append(f"{command}: bin → {target} ({path})")
        self.units.add(
            "capability", f"command {command}",
            f"`{command}` runs {target}: a bin entry of {package} in {path}. Recorded, not run.",
            path, start, end, ("javascript", "cli", "bin"),
        )

    def _pyproject(self, path: str, text: str) -> None:
        data = tomllib.loads(text)
        lines = _Lines(text)
        last = _line_count(text)
        for table, tag in (("project.scripts", "console-script"),
                           ("project.gui-scripts", "gui-script"),
                           ("tool.poetry.scripts", "console-script")):
            for script, target in self._table(path, lines, data, table).items():
                reference = target.get("reference") if isinstance(target, dict) else target
                line = lines.toml(table, script)
                # A Poetry script of type "file" names a file to run, not a module:function.
                is_file = isinstance(target, dict) and target.get("type") == "file"
                if not script.strip() or script != script.strip() or "=" in script:
                    problem = f"{table} entry {script!r} is not a script name"
                elif not isinstance(reference, str):
                    problem = f"{table}.{script} is not a module:function reference"
                elif not (reference.strip() if is_file else _ENTRY_POINT.fullmatch(reference.strip())):
                    problem = f"{table}.{script} = {reference!r} is not a module:function reference"
                else:
                    self._console_script(path, script, reference, line, last, tag)
                    continue
                self.units.unparsed(path, f"{problem}; skipped", line)

        project = self._table(path, lines, data, "project")
        self._requirement_list(path, lines, last, "project", "dependencies",
                               project.get("dependencies"), "dependencies")
        for extra, items in self._table(path, lines, data, "project.optional-dependencies").items():
            self._requirement_list(path, lines, last, "project.optional-dependencies", extra,
                                   items, f"extra {extra}")
        build = self._table(path, lines, data, "build-system")
        self._requirement_list(path, lines, last, "build-system", "requires",
                               build.get("requires"), "build")

        poetry = [("tool.poetry.dependencies", "poetry"),
                  ("tool.poetry.dev-dependencies", "poetry dev")]
        for group, table in self._table(path, lines, data, "tool.poetry.group").items():
            if isinstance(table, dict):
                poetry.append((f"tool.poetry.group.{group}.dependencies", f"poetry {group}"))
        for table, group in poetry:
            for dependency, spec in self._table(path, lines, data, table).items():
                if dependency == "python":
                    continue
                line = lines.toml(table, dependency)
                constraint = _poetry_constraint(spec)
                if not dependency.strip() or constraint is None:
                    self.units.unparsed(
                        path, f"{table}.{dependency} = {spec!r} is not a version constraint or a "
                        "dependency table this adapter can read; skipped", line,
                    )
                    continue
                self._declared(path, dependency, constraint, "", line, last, group)

    def _table(self, path: str, lines: _Lines, data: dict, dotted: str) -> dict:
        value: object = data
        for key in dotted.split("."):
            if not isinstance(value, dict) or key not in value:
                return {}
            value = value[key]
        if isinstance(value, dict):
            return value
        self.units.unparsed(path, f"{dotted} is not a table; skipped", lines.toml(dotted))
        return {}

    def _requirement_list(self, path: str, lines: _Lines, last: int, table: str, key: str,
                          items: object, group: str) -> None:
        if items is None:
            return
        anchor = lines.toml(table, key)
        if not isinstance(items, list):
            self.units.unparsed(path, f"{table}.{key} is not a list of requirements; skipped", anchor)
            return
        cursor = anchor or 1
        for item in items:
            if not isinstance(item, str):
                self.units.unparsed(
                    path, f"{table}.{key} holds a {type(item).__name__}, not a requirement; skipped",
                    anchor,
                )
                continue
            line = lines.quoted(item, cursor)
            if line:
                cursor = line
            self._dependency(path, item, line or anchor, last, group)

    def _setup_cfg(self, path: str, text: str) -> None:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(text, source=path)
        lines = _Lines(text)
        last = _line_count(text)
        section = "options.entry_points"
        for option, tag in (("console_scripts", "console-script"), ("gui_scripts", "gui-script")):
            for entry in _ini_values(parser, section, option):
                script, sep, reference = entry.partition("=")
                if not sep or not script.strip() or not reference.strip():
                    self.units.unparsed(
                        path, f"not an entry point: {entry!r}; skipped", lines.ini(section)
                    )
                    continue
                line = lines.ini(section, key=script.strip())
                self._console_script(path, script.strip(), reference.strip(), line, last, tag)
        for entry in _ini_values(parser, "options", "install_requires"):
            self._dependency(path, entry, lines.ini("options", entry=entry), last,
                             "install_requires")
        extras = "options.extras_require"
        if parser.has_section(extras):
            for extra in parser.options(extras):
                for entry in _ini_values(parser, extras, extra):
                    self._dependency(path, entry, lines.ini(extras, entry=entry),
                                     last, f"extra {extra}")

    def _requirements(self, path: str, text: str) -> None:
        last = _line_count(text)
        for number, raw in enumerate(text.split("\n"), 1):
            line = _before(_before(raw.strip(), _COMMENT), _OPTION_TAIL).rstrip("\\").strip()
            # Comments, and options and includes (-r, -e, --index-url): not requirements by name.
            if not line or line.startswith(("#", "-")):
                continue
            self._dependency(path, line, number, last, "requirements")

    def _console_script(self, path: str, script: str, reference: str, line: int | None,
                        last: int, tag: str) -> None:
        reference = reference.strip()
        module, _, attr = reference.partition(":")
        function = attr.split("[")[0].strip().split(".")[0]
        self.console_scripts.append((module.strip(), function, script))
        self.entry_points.append(f"{script}: console script → {reference} ({path})")
        start, end = _at(line, last)
        self.units.add(
            "capability", f"console script {script}",
            f"`{script}` runs {reference}: a {tag} declared in {path}. Recorded, not installed "
            "or run.",
            path, start, end, ("python", "cli", tag),
        )

    def _dependency(self, path: str, requirement: str, line: int | None, last: int,
                    group: str) -> None:
        one_line = "\n" not in requirement and "\r" not in requirement
        parsed = _REQUIREMENT.fullmatch(requirement) if one_line else None
        rest = parsed.group("rest").strip() if parsed else ""
        if parsed is None or (rest and rest[0] not in "<>=!~@("):
            self.units.unparsed(
                path, f"not a requirement this adapter can read: {requirement!r}; skipped", line
            )
            return
        self._declared(path, parsed.group("name") + (parsed.group("extras") or ""), rest,
                       (parsed.group("marker") or "").strip(), line, last, group)

    def _declared(self, path: str, name: str, constraint: str, marker: str, line: int | None,
                  last: int, group: str) -> None:
        parts = [f"{name} {constraint or '(any version)'}"]
        if marker:
            parts.append(f"Only when: {marker}")
        parts.append(f"Declared in {path} ({group}). Recorded, not installed.")
        start, end = _at(line, last)
        self.units.add(
            "dependency", f"dependency {name.split('[')[0]}", "\n\n".join(parts), path, start,
            end, ("python", group),
        )

    # --- the map ---------------------------------------------------------------------------

    def repository_map(self) -> None:
        top: Counter[str] = Counter()
        loose: list[str] = []
        for path in self.files:
            head, sep, _ = path.partition("/")
            if sep:
                top[head] += 1
            else:
                loose.append(path)
        layout = [
            f"- {name}/ ({top[name]} file{'' if top[name] == 1 else 's'})" if name in top
            else f"- {name}"
            for name in sorted({*top, *loose})
        ]
        languages = Counter(_LANGUAGES[_suffix(p)] for p in self.files if _suffix(p) in _LANGUAGES)
        by_count = [
            f"- {language}: {count}"
            for language, count in sorted(languages.items(), key=lambda item: (-item[1], item[0]))
        ]
        homes = Counter(path.rpartition("/")[0] or "." for path in self.files if _is_test_file(path))
        tests = [
            f"- {home}/ ({count} test file{'' if count == 1 else 's'})" if home != "."
            else f"- the top level ({count} test file{'' if count == 1 else 's'})"
            for home, count in sorted(homes.items())
        ]
        entries = [f"- {entry}" for entry in dict.fromkeys(self.entry_points)]
        parts = [
            f"Repository map: {len(self.files)} files found; read, never run.",
            "Top-level layout:\n" + ("\n".join(_listed(layout)) or "- (empty)"),
            "Languages by file count:\n" + ("\n".join(by_count) or "- no source files recognised"),
            "Entry points:\n" + ("\n".join(_listed(entries)) or "- none found"),
            "Tests live in:\n" + ("\n".join(_listed(tests)) or "- no test files found"),
        ]
        aside = [f"- {path}/ (not walked: vendored or cache)" for path in self.not_walked]
        aside += [f"- {path} (symbolic link, not followed)" for path in self.links]
        if aside:
            parts.append("Set aside:\n" + "\n".join(_listed(aside)))
        self.units.add(
            "knowledge", "repository map", "\n\n".join(parts), ".", tags=("repository-map",),
            first=True, force=True,
        )


# --- paths -------------------------------------------------------------------------------------


def _name(path: str) -> str:
    return path.rpartition("/")[2]


def _parent_name(path: str) -> str:
    return path.rpartition("/")[0].rpartition("/")[2]


def _suffix(path: str) -> str:
    name = _name(path)
    dot = name.rfind(".")
    return name[dot:].lower() if dot > 0 else ""


def _line_count(text: str) -> int:
    return max(1, text.count("\n") + (0 if text.endswith("\n") else 1))


def _at(line: int | None, last: int) -> tuple[int, int]:
    """A found line, or the whole file when the line could not be found."""
    return (line, line) if line else (1, last)


def _is_requirements(path: str) -> bool:
    name = _name(path).lower()
    return _suffix(path) in (".txt", ".in") and (
        "requirements" in name or _parent_name(path) == "requirements"
    )


def _is_python_test(path: str) -> bool:
    name = _name(path)
    return name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def _is_js_test(path: str) -> bool:
    stem = _name(path).rsplit(".", 1)[0]
    return stem.endswith((".test", ".spec")) or any(
        part in _JS_TEST_DIRS for part in path.split("/")[:-1]
    )


def _is_test_file(path: str) -> bool:
    suffix = _suffix(path)
    return (suffix == ".py" and _is_python_test(path)) or (suffix in _JS_SUFFIXES and _is_js_test(path))


def _test_subject(path: str) -> str:
    stem = _name(path).rsplit(".", 1)[0]
    for affix in (".test", ".spec", "_test"):
        stem = stem.removesuffix(affix)
    return stem.removeprefix("test_") or stem or path


def _module_name(path: str) -> str:
    parts = path[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts.pop()
    if len(parts) > 1 and parts[0] == "src":
        parts = parts[1:]
    return ".".join(parts) or "__init__"


def _public_module(path: str) -> bool:
    parts = path[: -len(".py")].split("/")
    if parts[-1] in ("__init__", "__main__"):
        parts = parts[:-1]
    return not any(part.startswith("_") for part in parts)


# --- Python, read with ast ---------------------------------------------------------------------


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    if isinstance(node, ast.Call):
        return _dotted(node.func)
    return ""


def _strings(nodes: list[ast.expr]) -> list[str]:
    return [node.value for node in nodes if isinstance(node, ast.Constant) and isinstance(node.value, str)]


def _first_str(call: ast.Call) -> str | None:
    first = call.args[0] if call.args else None
    return first.value if isinstance(first, ast.Constant) and isinstance(first.value, str) else None


def _keyword_str(call: ast.Call, name: str) -> str | None:
    for keyword in call.keywords:
        value = keyword.value
        if keyword.arg == name and isinstance(value, ast.Constant) and isinstance(value.value, str):
            return value.value
    return None


def _signature(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
    if isinstance(node, ast.ClassDef):
        bases = [ast.unparse(base) for base in node.bases]
        bases += [ast.unparse(keyword) for keyword in node.keywords]
        text = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"
    else:
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
        text = f"{prefix} {node.name}({ast.unparse(node.args)}){returns}"
    return text[:MAX_SIGNATURE]


def _dunder_all(tree: ast.Module) -> set[str] | None:
    """The module's __all__ when it is written out as a literal; None when there is none."""
    names: set[str] | None = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        ):
            value, extend = node.value, False
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)) and isinstance(node.target, ast.Name) \
                and node.target.id == "__all__" and node.value is not None:
            value, extend = node.value, isinstance(node, ast.AugAssign)
        else:
            continue
        if isinstance(value, (ast.List, ast.Tuple)) and all(
            isinstance(item, ast.Constant) and isinstance(item.value, str) for item in value.elts
        ):
            found = {item.value for item in value.elts}
            names = (names | found) if extend and names is not None else found
    return names


def _main_guard(tree: ast.Module) -> ast.If | None:
    for node in tree.body:
        if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
            continue
        test = node.test
        if len(test.ops) != 1 or not isinstance(test.ops[0], ast.Eq):
            continue
        sides = [test.left, *test.comparators]
        if any(isinstance(side, ast.Name) and side.id == "__name__" for side in sides) and any(
            isinstance(side, ast.Constant) and side.value == "__main__" for side in sides
        ):
            return node
    return None


def _click_command(node: ast.FunctionDef | ast.AsyncFunctionDef) -> dict | None:
    """A click or typer command: a decorator ending .command or .group, with the options and
    arguments the other decorators declare."""
    command: dict | None = None
    options: list[str] = []
    for decorator in node.decorator_list:
        call = decorator if isinstance(decorator, ast.Call) else None
        dotted = _dotted(call.func if call is not None else decorator)
        last = dotted.rpartition(".")[2]
        if last in ("command", "group"):
            label = (_first_str(call) or _keyword_str(call, "name")) if call is not None else None
            command = {"name": label or node.name.replace("_", "-"), "group": last == "group",
                       "via": dotted}
        elif last in ("option", "argument") and call is not None:
            options.extend(_strings(call.args))
    if command is not None:
        command["options"] = options
    return command


def _argparse(tree: ast.Module) -> list[dict]:
    """argparse parsers and subcommands, in source order, each with the arguments added to the
    name it was assigned to."""
    nodes = sorted(
        (node for node in ast.walk(tree) if isinstance(node, (ast.Assign, ast.Call))),
        key=lambda node: (node.lineno, node.col_offset),
    )
    records: list[dict] = []
    named: dict[str, dict] = {}
    claimed: set[int] = set()
    for node in nodes:
        if isinstance(node, ast.Assign):
            target = node.targets[0] if len(node.targets) == 1 else None
            if isinstance(target, ast.Name) and isinstance(node.value, ast.Call):
                record = _parser_record(node.value)
                if record is not None:
                    claimed.add(id(node.value))
                    records.append(record)
                    named[target.id] = record
            continue
        if id(node) in claimed:
            continue
        record = _parser_record(node)
        if record is not None:
            records.append(record)
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "add_argument" \
                and isinstance(func.value, ast.Name) and func.value.id in named:
            owner = named[func.value.id]
            flags = " / ".join(_strings(node.args)) or "(unnamed)"
            text = _keyword_str(node, "help")
            owner["arguments"].append(f"- {flags}: {text}" if text else f"- {flags}")
            owner["end"] = max(owner["end"], node.end_lineno or node.lineno)
    return records


def _parser_record(call: ast.Call) -> dict | None:
    func = call.func
    if _dotted(func).rpartition(".")[2] == "ArgumentParser":
        kind, name = "parser", _keyword_str(call, "prog")
        text = _keyword_str(call, "description")
    elif isinstance(func, ast.Attribute) and func.attr == "add_parser":
        kind, name = "subcommand", _first_str(call) or _keyword_str(call, "name")
        text = _keyword_str(call, "help") or _keyword_str(call, "description")
    else:
        return None
    return {"kind": kind, "name": name, "help": text, "start": call.lineno,
            "end": call.end_lineno or call.lineno, "arguments": []}


def _python_subjects(tree: ast.Module) -> list[str]:
    """What a test file imports, less the standard library and the test tools."""
    imported: dict[str, list[str]] = {}
    nodes = sorted(
        (node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))),
        key=lambda node: (node.lineno, node.col_offset),
    )
    for node in nodes:
        if isinstance(node, ast.ImportFrom):
            source = "." * node.level + (node.module or "")
            entries = [(source, alias.name) for alias in node.names]
        else:
            entries = [(alias.name, "") for alias in node.names]
        for module, name in entries:
            top = module.split(".")[0]
            if not module.startswith(".") and (top in sys.stdlib_module_names or top in _TEST_TOOLS):
                continue
            names = imported.setdefault(module, [])
            if name and name not in names:
                names.append(name)
    return [f"{module} ({', '.join(names)})" if names else module for module, names in imported.items()]


# --- JavaScript and TypeScript, read by pattern ------------------------------------------------


def _set_aside_comments(
    text: str,
) -> tuple[str, str, list[tuple[int, int]], tuple[int, str] | None]:
    """Two copies of the text with every offset and newline kept: code, with comments blanked,
    and a skeleton that also blanks the inside of strings and regular expressions — so neither
    a commented-out export nor a brace in a string is taken for code. And the block comments,
    as offsets; and the first comment or string left open, as (offset, what)."""
    code = list(text)
    skeleton = list(text)
    blocks: list[tuple[int, int]] = []
    unclosed: tuple[int, str] | None = None
    size = len(text)
    index = 0
    last = -1                     # the last character of code before index
    allowance = _REGEX_SCAN_FACTOR * size + _REGEX_SCAN_SLACK
    while index < size:
        char = text[index]
        if text.startswith("//", index):
            end = text.find("\n", index)
            end = size if end == -1 else end
            _blank(code, index, end)
            _blank(skeleton, index, end)
            index = end
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            if end == -1:
                unclosed = unclosed or (index, "a /* comment that is never closed")
                end = size
            else:
                end += 2
            blocks.append((index, end))
            _blank(code, index, end)
            _blank(skeleton, index, end)
            index = end
        elif char in "'\"`":
            close = _string_end(text, index)
            if close is not None:
                _blank(skeleton, index + 1, close)
                last = close
                index = close + 1
            elif char == "`":
                unclosed = unclosed or (index, "a ` template string that is never closed")
                _blank(skeleton, index + 1, size)
                index = size
            elif _literal_expected(text, last):     # only a string can begin here: left open
                unclosed = unclosed or (index, f"a {char} string that is never closed on its line")
                last = index
                index += 1
            else:                 # a quote alone on its line: an apostrophe in JSX text, say
                last = index
                index += 1
        elif char == "/" and _regex_may_follow(text, last):
            if allowance < 0:
                unclosed = unclosed or (index, _TOO_MANY_SLASHES)
                break
            close, reached = _regex_end(text, index)
            allowance -= reached - index
            if close is not None:
                _blank(skeleton, index + 1, close)
                index = close
            last = index
            index += 1
        else:
            if not char.isspace():
                last = index
            index += 1
    return "".join(code), "".join(skeleton), blocks, unclosed


def _string_end(text: str, start: int) -> int | None:
    """The offset of the quote closing the string opened at start; None when a quoted string
    meets the end of its line, or a template string the end of the text, first."""
    quote = text[start]
    index = start + 1
    while index < len(text):
        char = text[index]
        if char == quote:
            return index
        if char == "\\":
            index += 3 if text.startswith("\r\n", index + 1) else 2
            continue
        if char == "\n" and quote != "`":
            return None
        index += 1
    return None


def _literal_expected(text: str, last: int) -> bool:
    """Whether a quote after the code character at last can only open a string — where an
    expression is wanted, as after an operator, an opening bracket or return — so that one not
    closed on its line is a string left open. After a word, a > or a } the quote may be JSX
    text instead: Don't, <p>'Tis, {name}'s."""
    if last >= 0 and (text[last] == "}" or (text[last] == ">" and text[last - 1:last] != "=")):
        return False
    return _regex_may_follow(text, last)


def _regex_may_follow(text: str, last: int) -> bool:
    """Whether a / after the code character at last opens a regular expression rather than
    divides: at the start, after an operator or an opening bracket, or after a word such as
    return."""
    if last < 0 or text[last] in _REGEX_AFTER:
        return True
    start = last
    while start > 0 and last - start < 12 and (text[start - 1].isalnum() or text[start - 1] in "_$"):
        start -= 1
    return text[start:last + 1] in _REGEX_KEYWORDS


def _regex_end(text: str, start: int) -> tuple[int | None, int]:
    """The offset of the / closing a regular expression opened at start — None when its line,
    or _REGEX_REACH characters, end first: a division after all — and how far was read."""
    in_class = False
    index = start + 1
    stop = min(len(text), start + _REGEX_REACH)
    while index < stop:
        char = text[index]
        if char == "\n":
            return None, index
        if char == "\\":
            index += 2
            continue
        if char == "[":
            in_class = True
        elif char == "]":
            in_class = False
        elif char == "/" and not in_class:
            return index, index
        index += 1
    return None, index


def _unbalanced(skeleton: str) -> tuple[int, str] | None:
    """The first bracket that does not pair, as (offset, what): the file is broken or cut
    short there. None when every bracket pairs."""
    stack: list[int] = []
    for index, char in enumerate(skeleton):
        if char in _BRACKETS:
            stack.append(index)
        elif char in ")]}":
            if not stack:
                return index, f"a {char} that closes nothing"
            expected = _BRACKETS[skeleton[stack.pop()]]
            if char != expected:
                return index, f"a {char} where {expected} was expected"
    if stack:
        return stack[0], f"a {skeleton[stack[0]]} that is never closed"
    return None


def _blank(chars: list[str], start: int, end: int) -> None:
    for position in range(start, min(end, len(chars))):
        if chars[position] != "\n":
            chars[position] = " "


def _pairs(skeleton: str) -> dict[int, int]:
    pairs: dict[int, int] = {}
    stack: list[int] = []
    for index, char in enumerate(skeleton):
        if char in "{([":
            stack.append(index)
        elif char in "})]" and stack:
            pairs[stack.pop()] = index
    return pairs


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts.extend(match.end() for match in re.finditer("\n", text))
    return starts


def _line_of(starts: list[int], offset: int) -> int:
    return max(1, bisect_right(starts, offset))


def _end_of_line(text: str, position: int) -> int:
    end = text.find("\n", position)
    return len(text) if end == -1 else end


def _one_line(text: str) -> str:
    return " ".join(text.split())[:MAX_SIGNATURE]


def _skip_space(text: str, index: int) -> int:
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _parameter_list(skeleton: str, pairs: dict[int, int], at: int) -> int | None:
    """The offset of the ( opening the parameter list that begins at at, past any TypeScript
    type parameters — a balanced <…>, which may hold parentheses of its own; None when no
    parameter list begins there."""
    index = _skip_space(skeleton, at)
    if skeleton.startswith("<", index):
        end = _type_end(skeleton, pairs, index)
        if end is None:
            return None
        index = end
    return index if skeleton.startswith("(", index) and index in pairs else None


def _function_extent(code: str, skeleton: str, pairs: dict[int, int], begin: int, after: int,
                     *, typescript: bool = False, ambient: bool = False) -> tuple[int, str]:
    """Where a function declared at begin ends, and its signature as written: the brace closing
    its body, which must follow the signature directly; or, for a TypeScript signature with no
    body — ended by a ;, the block around it or the file, or by its line when it is declared
    (ambient) or an overload of the function that follows — the end of the signature. Raises
    _Malformed when it ends no such way, so that nothing is read on into the next declaration."""
    paren = _parameter_list(skeleton, pairs, after)
    if paren is None:
        raise _Malformed("has no parameter list")
    end = pairs[paren] + 1
    # A TypeScript return type comes before the body, and may hold braces of its own.
    returns = _RETURN_TYPE.match(skeleton, end)
    if returns is not None:
        found = _type_end(skeleton, pairs, returns.end())
        if found is None:
            raise _Malformed("has a return type that does not end")
        end = found
    while skeleton[end - 1].isspace():
        end -= 1                          # the signature ends at its last character
    body = _skip_space(skeleton, end)
    if skeleton.startswith("{", body):
        return pairs.get(body, body), _one_line(code[begin:body])
    if typescript:
        if skeleton.startswith(";", body):
            return body, _one_line(code[begin:body + 1])
        declared = ambient or "declare" in skeleton[begin:after].split()
        closed = body >= len(skeleton) or skeleton[body] == "}"
        if closed or ("\n" in skeleton[end:body] and (
            declared or _overload(skeleton, begin, after, body)
        )):
            return end - 1, _one_line(code[begin:end])
    raise _Malformed("has no body")


def _overload(skeleton: str, begin: int, after: int, at: int) -> bool:
    """Whether the function declared from begin to after is declared again at at: an overload
    signature, whose body is the later declaration's."""
    name = re.search(rf"function\b[ \t]*\*?[ \t]*({_JS_NAME})", skeleton[begin:after])
    if name is None:
        return False
    again = re.compile(
        r"(?:export\s++)?(?:default\s++)?(?:declare\s++)?(?:async\s++)?function\b\s*+\*?\s*+"
        + re.escape(name.group(1)) + r"(?![\w$])"
    )
    return again.match(skeleton, at) is not None


def _binding_problem(skeleton: str, pairs: dict[int, int], keyword: str, at: int) -> str | None:
    """What is wrong with the declaration an exported const, let or var begins, read from at,
    just past the keyword; None when it is whole. It must bind a name or a destructuring
    pattern, with a type if one is written, and then take a value after an = — which a const
    must — or end: at a ;, a comma, the end of its line or of the text. The first binding is
    the one read."""
    size = len(skeleton)
    index = _skip_space(skeleton, at)
    name = _JS_IDENTIFIER.match(skeleton, index)
    if name is not None:
        label, last = f"exported {keyword} {name.group()}", name.end()
    elif index < size and skeleton[index] in "{[" and index in pairs:
        label, last = f"an exported {keyword} pattern", pairs[index] + 1
    else:
        return "an export this reader cannot make out"
    index = _skip_space(skeleton, last)
    if keyword == "const" and name is not None and name.group() == "enum" \
            and _JS_IDENTIFIER.match(skeleton, index):
        return None                       # a TypeScript const enum
    if skeleton.startswith("!", index):   # TypeScript's definite assignment: let x!: T
        index = _skip_space(skeleton, index + 1)
    if skeleton.startswith(":", index):
        end = _type_end(skeleton, pairs, index + 1)
        if end is None:
            return f"{label} has a type that does not end"
        last = end
        while skeleton[last - 1].isspace():
            last -= 1
        index = _skip_space(skeleton, last)
    if skeleton.startswith("=", index) and not skeleton.startswith(("==", "=>"), index):
        value = _skip_space(skeleton, index + 1)
        word = _JS_IDENTIFIER.match(skeleton, value)
        if value >= size or skeleton[value] in ";,)]}=" or (
            word is not None and word.group() in _NOT_A_VALUE
        ):
            return f"{label} has no value after its ="
        return None
    if keyword == "const":
        return f"{label} has no value, which a const must be given"
    if index >= size or skeleton[index] in ";," or "\n" in skeleton[last:index]:
        return None
    return f"{label} does not end where its declaration must"


def _type_end(skeleton: str, pairs: dict[int, int], start: int) -> int | None:
    """Where a TypeScript type written from start ends: the offset of the first character past
    it, such as a function's body brace. A brace where a type is still wanted — first, or after
    |, &, =>, < or keyof — opens an object type and is part of it; a brace after a whole type is
    not; a whole type written to the end of the text ends there. None when the type does not
    end, or its brackets do not pair, within the bound."""
    stop = min(len(skeleton), start + 2_000)
    index, depth, wanted = start, 0, True       # depth: the < of type arguments still open
    while index < stop:
        char = skeleton[index]
        if char.isspace():
            index += 1
        elif skeleton.startswith("=>", index):
            index, wanted = index + 2, True
        elif char in "{([" and (wanted or depth or char == "["):
            close = pairs.get(index)
            if close is None:
                return None
            index, wanted = close + 1, False
        elif char == "<":
            index, depth, wanted = index + 1, depth + 1, True
        elif char == ">" and depth:
            index, depth, wanted = index + 1, depth - 1, False
        elif char in "|&?:.-+" or (char == "," and depth):
            index, wanted = index + 1, True
        elif char in "'\"`":
            close = skeleton.find(char, index + 1, stop)
            if close == -1:
                return None
            index, wanted = close + 1, False
        elif char.isalnum() or char in "_$":
            end = index + 1
            while end < stop and (skeleton[end].isalnum() or skeleton[end] in "_$"):
                end += 1
            word = skeleton[index:end]
            if word in _TYPE_OPERATORS:
                wanted = True
            elif wanted or depth:
                wanted = False
            else:
                return index              # a second type with nothing joining them: it ended
            index = end
        elif depth:
            index += 1
        else:
            return index                  # a body brace, a ; or anything else no type holds
    if index >= len(skeleton) and not depth and not wanted:
        return index
    return None


def _class_extent(code: str, skeleton: str, pairs: dict[int, int], begin: int,
                  after: int) -> tuple[int, str]:
    """Where a class declared at begin ends, and its heading as written. Raises _Malformed when
    no body follows its heading before the next declaration. Each character of the heading is
    looked at a bounded number of times, however the text around it is laid out."""
    stop = _JS_CLASS_STOP.search(skeleton, after, after + _CLASS_HEADING + 1)
    if stop is None or stop.group() != "{" or _declaration_line(skeleton, after, stop.start()):
        raise _Malformed("has no body")
    brace = stop.start()
    return pairs.get(brace, brace), _one_line(code[begin:brace])


def _declaration_line(skeleton: str, start: int, end: int) -> bool:
    """Whether a line from start to end begins, after its indent, with a declaration."""
    for word in _JS_DECLARATION_WORD.finditer(skeleton, start, end):
        at = word.start()
        while at > start and skeleton[at - 1] != "\n" and skeleton[at - 1].isspace():
            at -= 1
        if at > start and skeleton[at - 1] == "\n":
            return True
    return False


def _arrow_extent(code: str, skeleton: str, pairs: dict[int, int], begin: int,
                  at: int) -> tuple[int, str]:
    body = _skip_space(skeleton, at)
    if body >= len(skeleton) or skeleton[body] in ";,)]}":
        raise _Malformed("has no body after its =>")
    if skeleton[body] in "{(":
        end = pairs.get(body, body)
    else:
        end = _end_of_line(skeleton, body)
    return end, _one_line(code[begin:at])


def _bound_extent(code: str, skeleton: str, pairs: dict[int, int],
                  match: re.Match) -> tuple[int, str] | None:
    """A name bound to a function or an arrow function — a TypeScript one perhaps generic, its
    type parameters before its parameters; None when what is bound is not one. Raises
    _Malformed when it is one that does not end as it must."""
    form = match.group("form")
    if form == "function":
        after = _JS_FUNCTION_NAME.match(skeleton, match.end()).end()
        return _function_extent(code, skeleton, pairs, match.start(), after)
    if form in ("(", "<"):
        paren = match.end() - 1 if form == "(" else _parameter_list(skeleton, pairs, match.end() - 1)
        close = pairs.get(paren) if paren is not None else None
        arrow = _ARROW.match(skeleton, close + 1) if close is not None else None
        if arrow is None:
            return None
        at = arrow.end()
    else:
        at = match.end()
    return _arrow_extent(code, skeleton, pairs, match.start(), at)


def _default_note(match: re.Match) -> str:
    return "the default export" if match.group("default") else ""


def _export_lists(skeleton: str) -> list[tuple[str, str]]:
    """(how it is exported, the local name) for names exported by list rather than in place."""
    found: list[tuple[str, str]] = []
    for match in _JS_EXPORT_LIST.finditer(skeleton):
        for item in match.group("names").split(","):
            alias = _JS_ALIAS.fullmatch(item.strip())
            if alias:
                local = alias.group("local")
                found.append((f"exported as {alias.group('alias') or local}", local))
    for match in _JS_MODULE_EXPORTS.finditer(skeleton):
        for item in match.group("names").split(","):
            prop = _JS_PROPERTY.fullmatch(item.strip())
            if prop:
                key = prop.group("alias")
                found.append((f"module.exports.{key}", prop.group("local") or key))
    for match in _JS_EXPORT_DEFAULT_NAME.finditer(skeleton):
        found.append(("the default export", match.group("name")))
    for match in _JS_MODULE_EXPORTS_NAME.finditer(skeleton):
        found.append(("module.exports", match.group("name")))
    return found


def _jsdoc(raw: str) -> str:
    inner = raw[3:-2] if raw.endswith("*/") else raw[3:]
    return "\n".join(re.sub(r"^\s*\*? ?", "", line).rstrip() for line in inner.split("\n")).strip()


# --- manifests ---------------------------------------------------------------------------------


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _poetry_constraint(spec: object) -> str | None:
    """What a Poetry dependency asks for, as written: a version constraint; a table with a
    version, or else a source to take it from (git, path, url or file); or a list of such
    tables, one for each set of conditions. None for any other shape."""
    if isinstance(spec, str):
        return spec if spec.strip() else None
    if isinstance(spec, list):
        whole = spec and all(
            isinstance(item, dict) and _poetry_constraint(item) is not None for item in spec
        )
        return _as_text(spec) if whole else None
    if not isinstance(spec, dict):
        return None
    given = [spec[key] for key in _POETRY_SOURCES if key in spec]
    if not given or not all(isinstance(value, str) and value.strip() for value in given):
        return None
    version = spec.get("version")
    return version if isinstance(version, str) else _as_text(spec)


def _first(lines: list[str], pattern: re.Pattern, start: int = 0) -> int | None:
    """The 1-based number of the first line from index start that matches."""
    for index in range(max(0, start), len(lines)):
        if pattern.search(lines[index]):
            return index + 1
    return None


def _json_shape(value: object) -> str:
    if isinstance(value, str):
        return "a string" if value.strip() else "an empty string"
    if isinstance(value, bool):
        return "a boolean"
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return "a number"
    return "a list" if isinstance(value, list) else "an object"


def _json_keys(text: str) -> dict[str, tuple[int, dict[str, int]]]:
    """Where the keys of a JSON object are written: each top-level key's line, with the line of
    each key of the object it holds, if it holds one. One pass over text that has already
    parsed, following the nesting, so a namesake deeper down is never taken for one of these,
    and keys are read as json reads them, escapes and all. A key written twice keeps its last
    line, as json.loads keeps its last value."""
    found: dict[str, tuple[int, dict[str, int]]] = {}
    open_: list[str] = []                 # the brackets open at this point, outermost first
    section: dict[str, int] = {}          # the keys under the top-level key last read
    wants_key = False
    line = 1
    index, size = 0, len(text)
    while index < size:
        char = text[index]
        if char == "\n":
            line += 1
        elif char == '"':
            end = index + 1
            while end < size and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            if wants_key:
                key = json.loads(text[index:end + 1])
                if open_ == ["{"]:
                    section = {}
                    found[key] = (line, section)
                elif open_ == ["{", "{"]:
                    section[key] = line
                wants_key = False
            index = end
        elif char in "{[":
            open_.append(char)
            wants_key = char == "{"
        elif char in "}]":
            if open_:
                open_.pop()
            wants_key = False
        elif char == ",":
            wants_key = bool(open_) and open_[-1] == "{"
        index += 1
    return found


def _json_line(keys: dict[str, tuple[int, dict[str, int]]], section: str,
               key: str | None = None) -> int | None:
    """The line of a top-level key, or of a key directly under it; the top-level key's line when
    the one under it is not found."""
    if section not in keys:
        return None
    line, children = keys[section]
    return line if key is None else children.get(key, line)


class _Lines:
    """A manifest's lines, and where its tables, keys and entries are written in them. Table
    headers, and the keys under each table or section, are read in one pass and then looked
    up, so a manifest of many thousand entries is placed in time in proportion to its length —
    not to its length times the number of its entries, as scanning afresh for each would be."""

    def __init__(self, text: str) -> None:
        self.lines = text.split("\n")
        self._headers: dict[tuple[str, ...], int] | None = None
        self._keys: dict[int, dict[str, int]] = {}
        self._quoted: dict[str, list[int]] | None = None
        self._sections: dict[str, int | None] = {}
        self._options: dict[int, tuple[dict[str, int], dict[str, int]]] = {}

    def toml(self, table: str, key: str | None = None) -> int | None:
        """The line of a key in a TOML table — the table's header, or the parent's key that
        holds it inline, when the key itself is not on a line of its own."""
        if self._headers is None:
            self._headers = {}
            for index, text in enumerate(self.lines):
                parts = _toml_header(text)
                if parts is not None:
                    self._headers.setdefault(parts, index + 1)
        anchor = self._headers.get(tuple(table.split(".")))
        if anchor is None and "." in table:
            parent, _, leaf = table.rpartition(".")
            base = self.toml(parent)
            if base is not None:
                anchor = self._toml_keys(base).get(leaf)
        if anchor is None or key is None:
            return anchor
        return self._toml_keys(anchor).get(key) or anchor

    def _toml_keys(self, anchor: int) -> dict[str, int]:
        """The keys written on lines of their own under the header at line anchor, each with
        the first line it is on."""
        keys = self._keys.get(anchor)
        if keys is None:
            keys = self._keys[anchor] = {}
            for index in range(anchor, len(self.lines)):
                if _TOML_HEADER.match(self.lines[index]):
                    break
                found = _TOML_KEY.match(self.lines[index])
                if found is not None:
                    written = next(part for part in found.groups() if part is not None)
                    keys.setdefault(written, index + 1)
        return keys

    def quoted(self, text: str, start: int) -> int | None:
        """The first line from start on where text is written as a quoted string."""
        if self._quoted is None:
            self._quoted = {}
            for index, line in enumerate(self.lines):
                for found in _QUOTED.finditer(line):
                    written = found.group(1) if found.group(1) is not None else found.group(2)
                    places = self._quoted.setdefault(written, [])
                    if not places or places[-1] != index + 1:
                        places.append(index + 1)
        places = self._quoted.get(text, [])
        at = bisect_left(places, start)
        return places[at] if at < len(places) else None

    def ini(self, section: str, *, key: str | None = None, entry: str | None = None) -> int | None:
        """The line of a setup.cfg section's header; or, when it can be found, of the option key
        assigned in that section, or of the entry written on a line of its own there."""
        if section not in self._sections:
            header = re.compile(r"^\s*\[\s*" + re.escape(section) + r"\s*\]")
            self._sections[section] = _first(self.lines, header)
        start = self._sections[section]
        if start is None or (key is None and entry is None):
            return start
        options = self._options.get(start)
        if options is None:
            keys: dict[str, int] = {}
            entries: dict[str, int] = {}
            for index in range(start, len(self.lines)):
                line = self.lines[index]
                if _INI_HEADER.match(line):
                    break
                name, sep, _ = line.partition("=")
                if sep:
                    keys.setdefault(name.strip(), index + 1)
                entries.setdefault(_before(line.strip(), _COMMENT), index + 1)
            options = self._options[start] = (keys, entries)
        found = options[0].get(key) if key is not None else options[1].get(entry or "")
        return found or start


def _toml_header(line: str) -> tuple[str, ...] | None:
    """The parts of the table a [header] line names, unquoted; None when the line is not one.
    An array of tables' [[header]] is not a table's."""
    found = _TOML_TABLE_LINE.fullmatch(line)
    if found is None:
        return None
    inside = found.group("inside")
    parts: list[str] = []
    at = 0
    while True:
        part = _TOML_PART.match(inside, at)
        if part is None:
            return None
        parts.append(next(piece for piece in part.groups() if piece is not None))
        at = part.end()
        if at == len(inside):
            return tuple(parts)
        if inside[at] != ".":
            return None
        at += 1


def _ini_values(parser: configparser.ConfigParser, section: str, option: str) -> list[str]:
    value = parser.get(section, option, fallback="")
    entries = []
    for line in value.split("\n"):
        entry = _before(line.strip(), _COMMENT).strip()
        if entry and not entry.startswith(("#", ";")):
            entries.append(entry)
    return entries


def _before(text: str, mark: re.Pattern) -> str:
    """The text before the first place mark matches, with the space before it taken off."""
    found = mark.search(text)
    return text if found is None else text[: found.start()].rstrip()


