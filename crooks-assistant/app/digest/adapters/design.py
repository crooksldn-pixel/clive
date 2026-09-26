"""The design adapter: web front ends, Shopify themes and design systems, decomposed into Units.

It reads, and only reads. CSS custom properties, design-token files (tokens.json, *.tokens,
*.tokens.json, and JSON in a tokens/ directory) and the theme object of a Tailwind
configuration become design_token Units, one per group — colour, typography, spacing, radius,
shadow, motion — per file. A Tailwind configuration is JavaScript: it is scanned as text for
its literal theme object and never evaluated, so a theme that only code could produce is
reported as not read rather than run. Each Shopify section and snippet becomes a pattern Unit,
its {% schema %} an interface Unit, and each group of config/settings_schema.json an interface
Unit. Each HTML page becomes a pattern Unit of its structure — landmarks, headings, forms, and
the components its class names and custom elements name — with its scripts passed over
unread; each .jsx, .tsx, .vue and .svelte file becomes a pattern Unit of its props, where the
source states them.

Nothing read is executed, imported or installed, and nothing is written. Links are not
followed. Files, counts, tokens and bodies are bounded by the limits below. Units come back in
path order, and in a fixed order within a file, with exact line spans. What cannot be read —
a file, or a part of one whose comments, blocks or brackets are never closed or do not pair —
does not raise: it becomes a knowledge Unit tagged 'unparsed' that says why."""

from __future__ import annotations

import bisect
import json
import os
import re
import stat
from html.parser import HTMLParser
from pathlib import Path

from app.digest.model import ARTIFACT_ID_PATTERN, MAX_BODY, MAX_TAG, MAX_TITLE, Location, Unit

NAME = "design"
HANDLES = ("web_app", "theme", "design_system")

MAX_FILES = 2_000             # files read from one artifact
MAX_ENTRIES = 50_000          # directory entries looked at to find them
MAX_FILE_BYTES = 512 * 1024   # one file
MAX_UNITS = 5_000             # from one artifact
MAX_TOKENS = 2_000            # design tokens from one file
MAX_DEPTH = 32                # nesting followed in a token file or a theme object
MAX_LISTED = 100              # items in any one list in a body
MAX_COMPONENTS = 50           # components, and declared types, read from one file

GROUPS = ("colour", "typography", "spacing", "radius", "shadow", "motion")


class _Skipped(Exception):
    """A file this adapter will not read; the message says why."""


def decompose(root: Path, artifact_id: str) -> list[Unit]:
    """The Units of the quarantined artifact at root, in path order. It reads and never raises
    on what it reads: what it cannot read comes back as a knowledge Unit tagged 'unparsed'.
    An artifact_id that is not one is the caller's mistake, and is refused."""
    if not isinstance(artifact_id, str) or not re.fullmatch(ARTIFACT_ID_PATTERN, artifact_id):
        raise ValueError(f"not an artifact id: {artifact_id!r}")
    try:
        base = Path(root)
        if not base.is_dir():
            return [_unparsed(artifact_id, ".", "the artifact is not a directory that can be read")]
        files, notes = _walk(base)
    except Exception as exc:  # the artifact cannot even be listed: say so, do not raise
        return [_unparsed(artifact_id, ".", f"the artifact could not be listed: {_reason(exc)}")]
    units: list[Unit] = []
    for rel, path, kind in files:
        try:
            units.extend(_READERS[kind](artifact_id, rel, _read(path)))
        except _Skipped as skipped:
            units.append(_unparsed(artifact_id, rel, str(skipped)))
        except Exception as exc:  # malformed input is reported, never raised
            units.append(
                _unparsed(artifact_id, rel, f"not readable as {_LABELS[kind]}: {_reason(exc)}")
            )
        if len(units) > MAX_UNITS:
            units = units[:MAX_UNITS]
            notes.append(
                f"stopped at {MAX_UNITS} units: {rel} and the files after it were not read in full"
            )
            break
    units.extend(_unparsed(artifact_id, ".", note) for note in notes)
    return _distinct(units)


# --- finding and reading files ---------------------------------------------------------------

_SKIPPED_DIRS = frozenset(("node_modules", "bower_components", "__pycache__"))
_TAILWIND = re.compile(r"tailwind\.config\.(?:js|cjs|mjs|ts|cts|mts)")
_TOKEN_DIRS = frozenset(("tokens", "design-tokens"))


def _kind(rel: str) -> str | None:
    """Which reader a file is for, from its path alone; None for files this adapter leaves."""
    parts = rel.lower().split("/")
    name, parent = parts[-1], (parts[-2] if len(parts) > 1 else "")
    if name.endswith(".liquid") and parent in ("sections", "snippets"):
        return "liquid"
    if name == "settings_schema.json" and parent == "config":
        return "settings_schema"
    if _TAILWIND.fullmatch(name):
        return "tailwind"
    if name.endswith((".json", ".tokens")):
        if (name in ("tokens.json", "design-tokens.json") or name.endswith((".tokens.json", ".tokens"))
                or _TOKEN_DIRS.intersection(parts[:-1])):
            return "tokens"
        return None
    if name.endswith((".css", ".scss", ".less", ".css.liquid", ".scss.liquid")):
        return "css"
    if name.endswith((".html", ".htm")):
        return "html"
    if name.endswith((".jsx", ".tsx", ".vue", ".svelte")):
        return "component"
    return None


def _walk(root: Path) -> tuple[list[tuple[str, Path, str]], list[str]]:
    """The files to read, sorted by path, and notes on what the bounds or the names left out.
    Directories are listed in path order, each in full or not at all, and every entry listed —
    a directory as much as a file — counts towards MAX_ENTRIES: the directory that would take
    the count past it, and every one after it, is not looked at. Hidden and dependency
    directories are passed over, and links are not followed."""
    found: list[tuple[str, Path, str]] = []
    notes: list[str] = []
    budget = MAX_ENTRIES
    pending = [root]
    while pending:
        directory = pending.pop()
        where = directory.relative_to(root).as_posix()
        try:
            with os.scandir(directory) as listing:
                entries: list[tuple[str, bool]] = []
                for entry in listing:
                    if len(entries) >= budget:
                        notes.append(
                            f"more than {MAX_ENTRIES} directory entries in the artifact: {where} "
                            "and the directories after it were not looked at"
                        )
                        return sorted(found), notes
                    entries.append((entry.name, entry.is_dir(follow_symlinks=False)))
        except OSError as exc:
            if directory == root:
                raise
            if len(notes) < MAX_LISTED:
                notes.append(f"a directory could not be listed: {where}: {_reason(exc)}")
            continue
        budget -= len(entries)
        subdirs: list[Path] = []
        for name, is_dir in sorted(entries):
            path = directory / name
            if is_dir:
                if not name.startswith(".") and name not in _SKIPPED_DIRS:
                    subdirs.append(path)
                continue
            rel = path.relative_to(root).as_posix()
            kind = _kind(rel)
            if kind is None:
                continue
            try:
                rel.encode("utf-8")
                Location(rel)
            except ValueError:
                if len(notes) < MAX_LISTED:
                    notes.append(f"a file whose name cannot be recorded was not read: {ascii(rel)}")
                continue
            if len(found) >= MAX_FILES:
                notes.append(f"more than {MAX_FILES} design files: only the first {MAX_FILES} found were read")
                return sorted(found), notes
            found.append((rel, path, kind))
        pending.extend(reversed(subdirs))
    return sorted(found), notes


def _read(path: Path) -> str:
    """A regular file's text, within the size bound. Links and special files are refused."""
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode):
        raise _Skipped("not a regular file: links and special files are not followed")
    if info.st_size > MAX_FILE_BYTES:
        raise _Skipped(f"{info.st_size} bytes, over the {MAX_FILE_BYTES}-byte limit for one file")
    with path.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise _Skipped(f"over the {MAX_FILE_BYTES}-byte limit for one file")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _Skipped("not UTF-8 text") from None


# --- making Units ------------------------------------------------------------------------------


def _clean(text: str) -> str:
    """Text as it can be stored: a lone surrogate, which a JSON escape can produce, cannot."""
    return text.encode("utf-8", "replace").decode("utf-8")


def _clip(text: str, limit: int) -> str:
    text = _clean(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _squash(text: str) -> str:
    return " ".join(text.split())


def _show(value: object, limit: int = 120) -> str:
    """A value read from JSON, as one short line."""
    try:
        shown = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError, RecursionError):
        shown = repr(value)
    return _clip(_squash(shown), limit)


def _reason(exc: BaseException) -> str:
    return _clip(f"{type(exc).__name__}: {exc}", 500)


def _listed(heading: str, items: list[str]) -> list[str]:
    if not items:
        return []
    shown = items[:MAX_LISTED]
    if len(items) > MAX_LISTED:
        shown.append(f"- … and {len(items) - MAX_LISTED} more")
    return [f"{heading}:", *shown]


def _counted(counts: dict[str, int]) -> list[str]:
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [f"- {name} ({count})" for name, count in ordered]


def _unit(artifact_id: str, kind: str, title: str, body: str, location: Location,
          tags: tuple[str, ...]) -> Unit:
    return Unit(
        artifact_id=artifact_id, kind=kind, title=_clip(title, MAX_TITLE),
        body=_clip(body, MAX_BODY), location=location,
        tags=tuple(dict.fromkeys(_clip(tag, MAX_TAG) for tag in tags)),
    )


def _unparsed(artifact_id: str, path: str, reason: str,
              span: tuple[int, int] | None = None) -> Unit:
    """What could not be read, and why: a knowledge Unit tagged 'unparsed'."""
    location = Location(path, *span) if span else Location(path)
    title = "Not read: part of the artifact" if path == "." else f"Not read: {path}"
    return _unit(artifact_id, "knowledge", title, reason, location, (NAME, "unparsed"))


def _distinct(units: list[Unit]) -> list[Unit]:
    seen: set[str] = set()
    kept: list[Unit] = []
    for unit in units:
        if unit.id not in seen:
            seen.add(unit.id)
            kept.append(unit)
    return kept


# --- reading source text without running it ----------------------------------------------------


class _Lines:
    """Offsets in a text to 1-based line numbers."""

    def __init__(self, text: str) -> None:
        self._starts = [0] + [match.end() for match in re.finditer("\n", text)]
        self.last = max(1, len(self._starts) - (1 if text.endswith("\n") else 0))

    def line(self, offset: int) -> int:
        return min(bisect.bisect_right(self._starts, offset), self.last)


_MASK_SCRIPT = re.compile(r"/\*|//|['\"`]")
_MASK_STYLE = re.compile(r"/\*|['\"]")
_NOT_NEWLINE = re.compile(r"[^\n]")


def _fill(out: list[str], text: str, start: int, end: int, char: str) -> None:
    out[start:end] = _NOT_NEWLINE.sub(char, text[start:end])


def _mask(text: str, *, script: bool) -> tuple[str, tuple[str, int] | None]:
    """text with its comments blanked to spaces and the contents of its strings to underscores,
    line breaks kept: offsets and line numbers still hold, and a bracket, colon or comma in a
    comment or a string is not taken for code. `script` adds // comments and template strings.
    Also what, if anything, runs on unclosed to the end — a /* comment or a template string —
    and where it opens."""
    out = list(text)
    finder = _MASK_SCRIPT if script else _MASK_STYLE
    index, size = 0, len(text)
    unclosed: tuple[str, int] | None = None
    while True:
        found = finder.search(text, index)
        if found is None:
            break
        start, token = found.start(), found.group()
        if token == "/*":
            end = text.find("*/", start + 2)
            if end < 0:
                unclosed = ("a /* comment", start)
            end = size if end < 0 else end + 2
            _fill(out, text, start, end, " ")
        elif token == "//":
            end = text.find("\n", start)
            end = size if end < 0 else end
            _fill(out, text, start, end, " ")
        else:
            end = start + 1
            while end < size and text[end] != token and (token == "`" or text[end] != "\n"):
                end += 2 if text[end] == "\\" else 1
            if token == "`" and end >= size:
                unclosed = ("a template string", start)
            _fill(out, text, start + 1, min(end, size), "_")
            end += 1
        index = end
    return "".join(out), unclosed


def _blank(match: re.Match[str]) -> str:
    return _NOT_NEWLINE.sub(" ", match.group())


class _Unbalanced(ValueError):
    """Brackets that do not pair: the bracket opened at `opened`, and what was found at `found`
    — the wrong kind of closing bracket, or, when closer is None, the end with it still open."""

    def __init__(self, opened: int, found: int, closer: str | None) -> None:
        super().__init__("unbalanced brackets")
        self.opened, self.found, self.closer = opened, found, closer


class _Code:
    """Source text, read and never run: the text itself, the same text masked, its lines, and
    the parts of it that could not be read — each why, and its first and last line."""

    def __init__(self, text: str, *, script: bool) -> None:
        self.text = text
        self.masked, unclosed = _mask(text, script=script)
        self.lines = _Lines(text)
        self.problems: list[tuple[str, int, int]] = []
        if unclosed:
            self.problem(
                f"{unclosed[0]} on line {self.lines.line(unclosed[1])} is never closed: "
                "the rest of the file is not read", unclosed[1], len(text),
            )

    def problem(self, reason: str, start: int, end: int) -> None:
        """Records that text[start:end] could not be read, and why."""
        if len(self.problems) < MAX_LISTED:
            self.problems.append((reason, self.lines.line(start), self.lines.line(max(start, end))))

    def unbalanced(self, what: str, start: int, exc: _Unbalanced) -> None:
        """Records that what starts at start could not be read, because its brackets do not pair."""
        where = f"the '{self.masked[exc.opened]}' on line {self.lines.line(exc.opened)}"
        why = (
            f"{where} is closed by '{exc.closer}' on line {self.lines.line(exc.found)}"
            if exc.closer else f"{where} is never closed"
        )
        self.problem(f"{what} cannot be read: {why}", start, exc.found)

    def unparsed(self, artifact_id: str, rel: str) -> list[Unit]:
        return [_unparsed(artifact_id, rel, reason, (first, last)) for reason, first, last in self.problems]


_BRACKET = re.compile(r"[{}\[\]()]")
_CLOSER = {"{": "}", "[": "]", "(": ")"}
_KEY = re.compile(r"[A-Za-z_$][\w$-]*|\d+(?:\.\d+)?|'[^'\n]*'|\"[^\"\n]*\"")


def _closing(masked: str, start: int, end: int | None = None) -> int:
    """The offset of the bracket that closes the one at start, before end. Brackets pair by
    kind: one closed by the wrong kind, or not closed before end, raises _Unbalanced."""
    end = len(masked) if end is None else end
    opened: list[int] = []
    for match in _BRACKET.finditer(masked, start, end):
        char = match.group()
        if char in _CLOSER:
            opened.append(match.start())
            continue
        if not opened or _CLOSER[masked[opened[-1]]] != char:
            raise _Unbalanced(opened[-1] if opened else match.start(), match.start(), char)
        opened.pop()
        if not opened:
            return match.start()
    raise _Unbalanced(start, end, None)


def _trim(masked: str, start: int, end: int) -> tuple[int, int]:
    while start < end and masked[start].isspace():
        start += 1
    while end > start and masked[end - 1].isspace():
        end -= 1
    return start, end


def _is_object(code: _Code, start: int, end: int) -> bool:
    """Whether text[start:end] is exactly one object literal."""
    if not (start < end and code.masked[start] == "{"):
        return False
    try:
        return _closing(code.masked, start, end) == end - 1
    except _Unbalanced:
        return False


def _entries(code: _Code, open_at: int, close_at: int) -> list[tuple[str, int, int, int]]:
    """The `key: value` entries of the object literal from open_at to close_at: each key, where
    it is, and where its value starts and ends. Spreads, methods and computed keys are left."""
    entries: list[tuple[str, int, int, int]] = []
    masked = code.masked
    depth, piece, colon = 0, open_at + 1, -1
    for index in range(open_at + 1, close_at + 1):
        char = masked[index]
        if index == close_at or (char == "," and depth == 0):
            if colon >= 0:
                key_at, key_end = _trim(masked, piece, colon)
                value_at, value_end = _trim(masked, colon + 1, index)
                key = code.text[key_at:key_end]
                if value_at < value_end and _KEY.fullmatch(key):
                    key = key[1:-1] if key[0] in "'\"" else key
                    entries.append((key, key_at, value_at, value_end))
            piece, colon = index + 1, -1
        elif char in "{[(":
            depth += 1
        elif char in "}])":
            depth -= 1
        elif char == ":" and depth == 0 and colon < 0:
            colon = index
    return entries


def _members(code: _Code, open_at: int, close_at: int) -> list[str]:
    """The members between the bracket at open_at and its closing one at close_at — the names
    a parameter destructures, the members of a type, the keys of an object or the items of an
    array — each as written, with its line."""
    members: list[str] = []
    masked = code.masked
    depth = angle = 0
    piece = open_at + 1
    for index in range(open_at + 1, close_at + 1):
        char = masked[index]
        if index == close_at or (depth == 0 and angle == 0 and char in ",;\n"):
            start, end = _trim(masked, piece, index)
            if start < end and len(members) < MAX_LISTED:
                member = _clip(_squash(code.text[start:end]), 120)
                members.append(f"line {code.lines.line(start)}: {member}")
            piece = index + 1
        elif char in "{[(":
            depth += 1
        elif char in "}])":
            depth -= 1
        elif char == "<":
            angle += 1
        elif char == ">" and masked[index - 1] != "=":
            angle = max(0, angle - 1)
    return members


# --- design tokens -----------------------------------------------------------------------------

_SOURCES = {
    "css": "CSS custom properties",
    "tokens_json": "a design-token file",
    "tailwind": "the theme object of a Tailwind configuration",
}
_TYPE_GROUPS = {
    "color": "colour", "colour": "colour",
    "fontfamily": "typography", "fontfamilies": "typography", "fontweight": "typography",
    "fontweights": "typography", "fontsize": "typography", "fontsizes": "typography",
    "lineheight": "typography", "lineheights": "typography", "letterspacing": "typography",
    "typography": "typography", "textcase": "typography", "textdecoration": "typography",
    "paragraphspacing": "typography",
    "spacing": "spacing", "space": "spacing",
    "borderradius": "radius", "radius": "radius", "radii": "radius",
    "shadow": "shadow", "boxshadow": "shadow", "dropshadow": "shadow",
    "duration": "motion", "cubicbezier": "motion", "transition": "motion", "easing": "motion",
    "animation": "motion",
}
_NAME_GROUPS = (
    ("shadow", frozenset(("shadow", "shadows", "elevation"))),
    ("radius", frozenset(("radius", "radii", "rounded", "corner", "corners"))),
    ("motion", frozenset((
        "motion", "duration", "durations", "easing", "ease", "transition", "transitions",
        "animation", "animations", "timing", "delay", "keyframes",
    ))),
    ("colour", frozenset((
        "color", "colors", "colour", "colours", "palette", "bg", "background", "foreground",
        "fg", "fill", "stroke",
    ))),
    ("typography", frozenset((
        "font", "fonts", "typography", "text", "type", "leading", "tracking", "weight",
        "family", "lineheight", "letterspacing",
    ))),
    ("spacing", frozenset((
        "space", "spaces", "spacing", "gap", "gutter", "gutters", "padding", "margin", "inset",
        "size", "sizes", "sizing",
    ))),
)
_TYPOGRAPHY_PAIRS = (" line height", " letter spacing")
_COLOUR_FUNCTIONS = r"(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|color-mix)\("
_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}|" + _COLOUR_FUNCTIONS + r".*\)", re.S)
_HAS_COLOUR = re.compile(r"#[0-9a-fA-F]{3,8}\b|(?<![\w-])" + _COLOUR_FUNCTIONS)
_DURATION = re.compile(r"-?(?:\d+\.?\d*|\.\d+)m?s", re.I)
_EASING = re.compile(r"cubic-bezier\(|steps\(", re.I)
_LENGTH = re.compile(r"(?<![\w.#-])-?(?:\d+\.?\d*|\.\d+)(?:px|rem|em)?(?![\w%.])")
_PARENTHESISED = re.compile(r"\([^()]*\)")


def _group_by_name(name: str) -> str | None:
    spaced = " " + " ".join(
        re.split(r"[^a-z0-9]+", re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name).lower())
    ).strip()
    if any(pair in spaced for pair in _TYPOGRAPHY_PAIRS):
        return "typography"
    words = set(spaced.split())
    for group, vocabulary in _NAME_GROUPS:
        if words & vocabulary:
            return group
    return None


def _group_by_value(value: str) -> str | None:
    value = value.strip()
    if _DURATION.fullmatch(value) or _EASING.search(value):
        return "motion"
    if not _HAS_COLOUR.search(value):
        return None
    if len(_LENGTH.findall(_PARENTHESISED.sub(" ", value))) >= 2:
        return "shadow"
    return "colour" if _COLOUR.fullmatch(value) else None


def _group(name: str, value: object, declared: object = None) -> str | None:
    """Which of GROUPS a token belongs to: by its declared type, then its name, then its value.
    None for a token in none of them — a z-index, a breakpoint — which is left out."""
    if isinstance(declared, str):
        group = _TYPE_GROUPS.get(re.sub(r"[^a-z]", "", declared.lower()))
        if group:
            return group
    by_name = _group_by_name(name)
    if by_name:
        return by_name
    return _group_by_value(value) if isinstance(value, str) else None


# A design token as read: its group, name and value, and the first and last line it is written on.
_Token = tuple[str, str, str, int, int]


def _span(first: int, last: int) -> str:
    return f"line {first}" if first == last else f"lines {first}-{last}"


def _token_units(artifact_id: str, rel: str, source: str,
                 tokens: list[_Token], *, truncated: bool) -> list[Unit]:
    """One design_token Unit per group found in the file, spanning every line of its tokens."""
    units: list[Unit] = []
    for group in GROUPS:
        found = [token for token in tokens if token[0] == group]
        if not found:
            continue
        listed = "\n".join(
            f"- {name}: {_clip(value, 200)} ({_span(first, last)})"
            for _, name, value, first, last in found
        )
        body = f"{len(found)} {group} token(s) in {rel}, read as text from {_SOURCES[source]}.\n{listed}"
        units.append(_unit(
            artifact_id, "design_token", f"{group.capitalize()} tokens: {rel}", body,
            Location(rel, min(token[3] for token in found), max(token[4] for token in found)),
            (NAME, group, source),
        ))
    if truncated:
        units.append(_unparsed(
            artifact_id, rel, f"more than {MAX_TOKENS} design tokens: the rest of the file was not read"
        ))
    return units


_CUSTOM_PROPERTY = re.compile(r"(?<![\w-])(--[\w-]+)\s*:([^;{}]*)")
_LIQUID_TAG = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
_BRACE = re.compile(r"[{}]")


def _check_braces(code: _Code) -> None:
    """Records the first brace in a stylesheet that does not pair: a '}' that closes no block,
    or a '{' never closed."""
    depth = outer = 0
    for match in _BRACE.finditer(code.masked):
        if match.group() == "{":
            if depth == 0:
                outer = match.start()
            depth += 1
        elif depth:
            depth -= 1
        else:
            line = code.lines.line(match.start())
            code.problem(f"the stylesheet's braces do not pair: the '}}' on line {line} closes no block",
                         match.start(), match.start())
            return
    if depth:
        line = code.lines.line(outer)
        code.problem(f"the stylesheet's braces do not pair: the '{{' on line {line} is never closed",
                     outer, len(code.masked))


def _read_css(artifact_id: str, rel: str, text: str) -> list[Unit]:
    """The custom properties of a stylesheet, and what in it does not scan: an unclosed comment
    or a brace that does not pair."""
    code = _Code(text, script=False)
    if rel.lower().endswith(".liquid"):
        code.masked = _LIQUID_TAG.sub(_blank, code.masked)
    _check_braces(code)
    tokens: list[_Token] = []
    truncated = False
    for match in _CUSTOM_PROPERTY.finditer(code.masked):
        name = text[match.start(1):match.end(1)]
        raw = text[match.start(2):match.end(2)]
        value = _squash(raw)
        group = _group(name, value)
        if value and group:
            if len(tokens) >= MAX_TOKENS:
                truncated = True
                break
            last = match.start(2) + len(raw.rstrip()) - 1
            tokens.append((group, name, value, code.lines.line(match.start(1)), code.lines.line(last)))
    return [
        *_token_units(artifact_id, rel, "css", tokens, truncated=truncated),
        *code.unparsed(artifact_id, rel),
    ]


def _json_spans(text: str) -> dict[tuple, list[int]]:
    """For JSON that json.loads has accepted: the first and last line of each value, by its path
    of keys and indices. A value in an object starts on the line of its key."""
    spans: dict[tuple, list[int]] = {}
    frames: list[list] = []   # [is an object, its current key or index, awaiting a key]
    line, index, size = 1, 0, len(text)

    def here() -> tuple:
        return tuple(frame[1] for frame in frames)

    def begin() -> None:
        if not frames or not frames[-1][0]:
            spans[here()] = [line, line]

    def finish() -> None:
        spans.setdefault(here(), [line, line])[1] = line

    while index < size:
        char = text[index]
        if char == "\n":
            line += 1
        elif char == '"':
            end = index + 1
            while end < size and text[end] != '"':
                end += 2 if text[end] == "\\" else 1
            if frames and frames[-1][0] and frames[-1][2]:
                frames[-1][1] = json.loads(text[index:end + 1])
                frames[-1][2] = False
                spans[here()] = [line, line]
            else:
                begin()
                finish()
            index = end
        elif char in "{[":
            begin()
            frames.append([char == "{", None if char == "{" else 0, char == "{"])
        elif char in "}]":
            if frames:
                frames.pop()
            finish()
        elif char == ",":
            if frames and frames[-1][0]:
                frames[-1][2] = True
            elif frames:
                frames[-1][1] += 1
        elif char not in " \t\r:":
            begin()
            while index + 1 < size and text[index + 1] not in ",]} \t\r\n":
                index += 1
            finish()
        index += 1
    return spans


def _json_tokens(node: object, path: tuple, declared: object, spans: dict[tuple, list[int]],
                 tokens: list[_Token], depth: int) -> bool:
    """Collects the tokens under node, in document order: W3C design tokens ($value, $type,
    inherited from the group) and Style Dictionary or Tokens Studio ones (value, type). True
    when MAX_TOKENS cut the collection short."""
    if not isinstance(node, dict) or depth > MAX_DEPTH:
        return False
    declared = node.get("$type", declared)
    is_token = "$value" in node or (
        "value" in node and ("type" in node or not isinstance(node["value"], dict))
    )
    if is_token:
        key = "$value" if "$value" in node else "value"
        value = node[key]
        name = ".".join(str(part) for part in path) or "(root)"
        group = _group(name, value, node.get("$type") or node.get("type") or declared)
        if group:
            if len(tokens) >= MAX_TOKENS:
                return True
            shown = _squash(value) if isinstance(value, str) else _show(value, 200)
            first = spans.get(path, [1, 1])[0]           # the line of the token's name
            last = spans.get((*path, key), [first, first])[1]   # where its value ends
            tokens.append((group, name, shown, first, max(first, last)))
        return False
    for key, child in node.items():
        if not key.startswith("$") and _json_tokens(
            child, (*path, key), declared, spans, tokens, depth + 1
        ):
            return True
    return False


def _read_tokens(artifact_id: str, rel: str, text: str) -> list[Unit]:
    data = json.loads(text)
    tokens: list[_Token] = []
    truncated = _json_tokens(data, (), None, _json_spans(text), tokens, 0)
    return _token_units(artifact_id, rel, "tokens_json", tokens, truncated=truncated)


_THEME = re.compile(r"(?<![\w$.])theme\s*:\s*\{")
_TAILWIND_GROUPS = {
    "colors": "colour", "textColor": "colour", "backgroundColor": "colour",
    "borderColor": "colour", "accentColor": "colour", "ringColor": "colour", "fill": "colour",
    "stroke": "colour",
    "fontFamily": "typography", "fontSize": "typography", "fontWeight": "typography",
    "lineHeight": "typography", "letterSpacing": "typography",
    "spacing": "spacing", "padding": "spacing", "margin": "spacing", "gap": "spacing",
    "space": "spacing", "inset": "spacing",
    "borderRadius": "radius",
    "boxShadow": "shadow", "dropShadow": "shadow",
    "transitionDuration": "motion", "transitionTimingFunction": "motion",
    "transitionDelay": "motion", "animation": "motion", "keyframes": "motion",
}


def _read_tailwind(artifact_id: str, rel: str, text: str) -> list[Unit]:
    """The literal theme object, and its extend, read as text. Values that are code — a
    function, a spread, a require — are recorded as written, not run."""
    code = _Code(text, script=True)
    found = _THEME.search(code.masked)
    if found is None:
        return [_unparsed(
            artifact_id, rel,
            "no literal theme object to read: a Tailwind configuration is read as text and never evaluated",
        ), *code.unparsed(artifact_id, rel)]
    open_at = found.end() - 1
    try:
        close_at = _closing(code.masked, open_at)
    except _Unbalanced as exc:
        code.unbalanced("the theme object", found.start(), exc)
        return code.unparsed(artifact_id, rel)
    tokens: list[_Token] = []
    for entry in _entries(code, open_at, close_at):
        if entry[0] == "extend" and _is_object(code, entry[2], entry[3]):
            for inner in _entries(code, entry[2], entry[3] - 1):
                _theme_entry(code, ("extend",), inner, tokens)
        else:
            _theme_entry(code, (), entry, tokens)
    return [
        *_token_units(
            artifact_id, rel, "tailwind", tokens[:MAX_TOKENS], truncated=len(tokens) > MAX_TOKENS
        ),
        *code.unparsed(artifact_id, rel),
    ]


def _theme_entry(code: _Code, prefix: tuple[str, ...], entry: tuple[str, int, int, int],
                 tokens: list[_Token]) -> None:
    group = _TAILWIND_GROUPS.get(entry[0])
    if group is not None:
        _flatten(code, group, (*prefix, entry[0]), entry, tokens, 0)


def _flatten(code: _Code, group: str, path: tuple[str, ...], entry: tuple[str, int, int, int],
             tokens: list[_Token], depth: int) -> None:
    _, key_at, value_at, value_end = entry
    if len(tokens) > MAX_TOKENS:
        return
    if depth < MAX_DEPTH and _is_object(code, value_at, value_end):
        for inner in _entries(code, value_at, value_end - 1):
            _flatten(code, group, (*path, inner[0]), inner, tokens, depth + 1)
    else:
        value = _squash(code.text[value_at:value_end])
        tokens.append((
            group, ".".join(path), value, code.lines.line(key_at), code.lines.line(value_end - 1),
        ))


# --- Shopify themes ----------------------------------------------------------------------------

_SCHEMA = re.compile(r"\{%-?\s*schema\s*-?%\}(.*?)\{%-?\s*endschema\s*-?%\}", re.S)
_SCHEMA_OPEN = re.compile(r"\{%-?\s*schema\s*-?%\}")
_LIQUID_BLOCK = re.compile(
    r"\{%-?\s*(schema|javascript|stylesheet|style|comment)\s*-?%\}.*?\{%-?\s*end\1\s*-?%\}", re.S
)
_BLOCK_OPEN = re.compile(r"\{%-?\s*(javascript|stylesheet|style|comment)\s*-?%\}")
_LIQUID_STATEMENT = re.compile(r"\{%.*?%\}", re.S)
_JAVASCRIPT = re.compile(r"\{%-?\s*javascript\s*-?%\}")
_RENDER = re.compile(r"\{%-?\s*(render|include|section)\s+['\"]([^'\"]+)['\"]")
_LIQUID_FORM = re.compile(r"\{%-?\s*form\s+['\"]([^'\"]+)['\"]")
_SETTING = re.compile(r"(?<![\w.])(?:(?:section|block)\.)?settings\.[A-Za-z_]\w*")


def _settings_lines(settings: object) -> list[str]:
    if not isinstance(settings, list):
        return []
    lines = []
    for setting in settings:
        if isinstance(setting, dict):
            parts = [
                f"{key} {_show(setting[key])}"
                for key in ("id", "type", "label", "default", "content") if key in setting
            ]
            lines.append(("- " + ", ".join(parts)) if parts else "- (empty)")
    return lines


def _schema_summary(schema: dict) -> str:
    counts = {
        key: len(schema[key]) if isinstance(schema.get(key), list) else 0
        for key in ("settings", "blocks", "presets")
    }
    return (
        f"named {_show(schema.get('name', ''))}: {counts['settings']} setting(s), "
        f"{counts['blocks']} block type(s), {counts['presets']} preset(s)"
    )


def _schema_lines(schema: dict) -> list[str]:
    lines = [
        f"{key}: {_show(schema[key])}"
        for key in ("name", "tag", "class", "limit", "max_blocks", "enabled_on", "disabled_on")
        if key in schema
    ]
    lines += _listed("Settings", _settings_lines(schema.get("settings")))
    blocks = []
    for block in schema.get("blocks") if isinstance(schema.get("blocks"), list) else []:
        if isinstance(block, dict):
            settings = block.get("settings")
            ids = [
                str(setting["id"]) for setting in settings
                if isinstance(setting, dict) and "id" in setting
            ] if isinstance(settings, list) else []
            line = f"- type {_show(block.get('type'))}, name {_show(block.get('name'))}"
            blocks.append(line + (f"; settings: {', '.join(ids)}" if ids else ""))
    lines += _listed("Blocks", blocks)
    presets = schema.get("presets") if isinstance(schema.get("presets"), list) else []
    lines += _listed(
        "Presets", [f"- {_show(preset.get('name'))}" for preset in presets if isinstance(preset, dict)]
    )
    return lines


def _schema_unit(artifact_id: str, rel: str, kind: str, name: str, schema: dict,
                 span: tuple[int, int]) -> Unit:
    body = [
        f"The {{% schema %}} of the Shopify {kind} '{name}' in {rel}: "
        "what it offers the theme editor.",
        *_schema_lines(schema),
        "JSON:",
        json.dumps(schema, ensure_ascii=False, indent=2),
    ]
    return _unit(
        artifact_id, "interface", f"Schema of Shopify {kind}: {name}", "\n".join(body),
        Location(rel, *span), (NAME, "shopify", "schema"),
    )


def _read_liquid(artifact_id: str, rel: str, text: str) -> list[Unit]:
    """A section or snippet as a pattern Unit — what it renders, the settings it uses and the
    outline of its markup — and its {% schema %} as an interface Unit."""
    kind = "section" if rel.lower().split("/")[-2] == "sections" else "snippet"
    name = rel.rsplit("/", 1)[-1][: -len(".liquid")]
    lines = _Lines(text)
    units: list[Unit] = []
    schemas: list[str] = []
    for match in _SCHEMA.finditer(text):
        span = (lines.line(match.start()), lines.line(match.end() - 1))
        try:
            schema = json.loads(match.group(1))
            if not isinstance(schema, dict):
                raise ValueError("it is not a JSON object")
            units.append(_schema_unit(artifact_id, rel, kind, name, schema, span))
            schemas.append(f"lines {span[0]}-{span[1]}, {_schema_summary(schema)}")
        except (ValueError, RecursionError) as exc:
            units.append(_unparsed(
                artifact_id, rel,
                f"the {{% schema %}} of {rel} is not a JSON object that can be read: {_reason(exc)}",
                span,
            ))
            schemas.append(f"lines {span[0]}-{span[1]}, not readable (see its 'unparsed' unit)")
    opened = _SCHEMA_OPEN.search(text)
    if not schemas and opened:
        span = (lines.line(opened.start()), lines.last)
        units.append(_unparsed(artifact_id, rel, f"the {{% schema %}} of {rel} is never closed", span))
        schemas.append(f"line {span[0]}, never closed (see its 'unparsed' unit)")

    without_blocks = _LIQUID_BLOCK.sub(_blank, text)
    body = [
        f"The Shopify {kind} '{name}' in {rel} ({lines.last} lines). Its scripts are not read.",
        "Schema: " + ("; ".join(schemas) if schemas else "none"),
    ]
    unclosed = _BLOCK_OPEN.search(without_blocks)
    if unclosed:   # nothing after it is read: it may be a script
        span = (lines.line(unclosed.start()), lines.last)
        units.append(_unparsed(
            artifact_id, rel,
            f"a {{% {unclosed.group(1)} %}} block in {rel} is never closed: nothing after it is read",
            span,
        ))
        body.append(f"Not read: lines {span[0]}-{span[1]}, an unclosed {{% {unclosed.group(1)} %}} "
                    "block (see its 'unparsed' unit)")
        without_blocks = without_blocks[:unclosed.start()] + _NOT_NEWLINE.sub(
            " ", without_blocks[unclosed.start():]
        )
    body += _listed("Renders", [
        f"- line {lines.line(match.start())}: {match.group(1)} '{match.group(2)}'"
        for match in _RENDER.finditer(without_blocks)
    ])
    body += _listed("Liquid forms", [
        f"- line {lines.line(match.start())}: form '{match.group(1)}'"
        for match in _LIQUID_FORM.finditer(without_blocks)
    ])
    used = sorted({match.group() for match in _SETTING.finditer(without_blocks)})
    body += _listed("Settings used", [f"- {setting}" for setting in used])
    scripts = len(_JAVASCRIPT.findall(text))
    if scripts:
        body.append(f"{{% javascript %}} blocks: {scripts}, not read or run")
    body.append("Markup structure:")
    try:
        body += _structure_lines(_LIQUID_STATEMENT.sub(_blank, without_blocks))
    except Exception as exc:  # markup past what the parser tolerates: say so, do not raise
        body.append("- not readable (see its 'unparsed' unit)")
        units.append(_unparsed(
            artifact_id, rel, f"the markup of {rel} cannot be read: {_reason(exc)}", (1, lines.last)
        ))
    pattern = _unit(
        artifact_id, "pattern", f"Shopify {kind}: {name}", "\n".join(body),
        Location(rel, 1, lines.last), (NAME, "shopify", kind),
    )
    return [pattern, *units]


def _read_settings_schema(artifact_id: str, rel: str, text: str) -> list[Unit]:
    """Each group of the theme's global settings as an interface Unit."""
    groups = json.loads(text)
    if not isinstance(groups, list):
        raise _Skipped(f"{rel} is not a JSON array of setting groups")
    spans = _json_spans(text)
    last = _Lines(text).last
    units: list[Unit] = []
    for index, group in enumerate(groups[:MAX_LISTED]):
        start, end = spans.get((index,), [1, last])
        if not isinstance(group, dict):
            units.append(_unparsed(
                artifact_id, rel, f"setting group {index + 1} is not a JSON object", (start, end)
            ))
            continue
        name = group.get("name")
        name = name if isinstance(name, str) and name.strip() else f"group {index + 1}"
        body = [f"Setting group {index + 1} of the theme's global settings in {rel}: '{name}'."]
        body += [f"{key}: {_show(value)}" for key, value in group.items() if key not in ("name", "settings")]
        body += _listed("Settings", _settings_lines(group.get("settings")))
        body += ["JSON:", json.dumps(group, ensure_ascii=False, indent=2)]
        units.append(_unit(
            artifact_id, "interface", f"Theme settings: {name}", "\n".join(body),
            Location(rel, start, end), (NAME, "shopify", "settings_schema"),
        ))
    if len(groups) > MAX_LISTED:
        units.append(_unparsed(
            artifact_id, rel, f"more than {MAX_LISTED} setting groups: the rest were not read"
        ))
    return units


# --- web pages and components ------------------------------------------------------------------

_HEADINGS = ("h1", "h2", "h3", "h4", "h5", "h6")
_LANDMARK_TAGS = ("header", "nav", "main", "aside", "footer", "section", "article", "search")
_LANDMARK_ROLES = (
    "banner", "navigation", "main", "complementary", "contentinfo", "search", "region", "form",
)
_FIELDS = ("input", "select", "textarea", "button")
_CLASS_BLOCK = re.compile(r"[A-Za-z][\w-]*")
_BEM = re.compile(r"__|--")


def _describe(tag: str, values: dict[str, str], extra: tuple[str, ...] = ()) -> str:
    parts = [tag]
    for key in ("id", "role", "aria-label", *extra):
        value = _squash(values.get(key, ""))
        if value:
            parts.append(f'{key}="{_clip(value, 80)}"')
    return " ".join(parts)


class _Structure(HTMLParser):
    """The outline of a page: its landmarks, headings and forms, and the components its class
    names (BEM blocks) and custom elements name. The standard library's parser only tokenises:
    nothing is fetched, and what is inside script and style elements is passed over unread."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.scripts = 0
        self.landmarks: list[str] = []
        self.headings: list[str] = []
        self.forms: list[tuple[str, list[str]]] = []
        self.loose: list[str] = []
        self.blocks: dict[str, int] = {}
        self.elements: dict[str, int] = {}
        self._hidden: str | None = None
        self._title: list[str] | None = None
        self._heading: tuple[int, str, list[str]] | None = None
        self._fields: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._hidden:
            return
        line = self.getpos()[0]
        values = {name: value or "" for name, value in attrs}
        if tag in ("script", "style"):
            if tag == "script":
                self.scripts += 1
            self._hidden = tag
            return
        if tag == "title" and not self.title:
            self._title = []
        elif tag in _HEADINGS:
            self._heading = (line, tag, [])
        role = values.get("role", "").strip().lower()
        if tag in _LANDMARK_TAGS or role in _LANDMARK_ROLES:
            self.landmarks.append(f"- line {line}: {_describe(tag, values)}")
        if tag == "form":
            self._fields = []
            self.forms.append(
                (f"- line {line}: {_describe(tag, values, ('action', 'method'))}", self._fields)
            )
        elif tag in _FIELDS:
            name = values.get("name", "")
            field = _clip(" ".join(
                part for part in (tag, values.get("type", ""), f"name={name}" if name else "") if part
            ), 120)
            if self._fields is not None:
                self._fields.append(field)
            else:
                self.loose.append(f"- line {line}: {field}")
        for name in values.get("class", "").split():
            if "__" in name or "--" in name:
                block = _BEM.split(name)[0]
                if _CLASS_BLOCK.fullmatch(block):
                    self.blocks[block] = self.blocks.get(block, 0) + 1
        if "-" in tag:
            self.elements[tag] = self.elements.get(tag, 0) + 1

    def handle_endtag(self, tag: str) -> None:
        if self._hidden:
            if tag == self._hidden:
                self._hidden = None
            return
        if tag == "title" and self._title is not None:
            self.title = _clip(_squash("".join(self._title)), 120)
            self._title = None
        elif self._heading is not None and tag == self._heading[1]:
            line, level, parts = self._heading
            text = _clip(_squash("".join(parts)), 120) or "(no text)"
            self.headings.append(f"- line {line}: {level} {text}")
            self._heading = None
        elif tag == "form":
            self._fields = None

    def handle_data(self, data: str) -> None:
        if self._hidden:
            return
        if self._title is not None:
            self._title.append(data)
        if self._heading is not None:
            self._heading[2].append(data)

    def summary(self, *, scripts: bool = True) -> list[str]:
        lines = [f"Scripts: {self.scripts} <script> element(s), not read or run"] if scripts else []
        if self.title:
            lines.append(f"Title: {self.title}")
        lines += _listed("Landmarks", self.landmarks)
        lines += _listed("Headings", self.headings)
        lines += _listed("Forms", [
            f"{header}; fields: {', '.join(fields[:MAX_LISTED]) or 'none'}"
            for header, fields in self.forms
        ])
        lines += _listed("Fields outside forms", self.loose)
        lines += _listed("Components (by class naming)", _counted(self.blocks))
        lines += _listed("Custom elements", _counted(self.elements))
        return lines


def _structure_lines(markup: str, *, scripts: bool = True) -> list[str]:
    """The outline of markup; raises on markup past what the parser tolerates."""
    parser = _Structure()
    parser.feed(markup)
    parser.close()
    return parser.summary(scripts=scripts)


def _read_html(artifact_id: str, rel: str, text: str) -> list[Unit]:
    parser = _Structure()
    parser.feed(text)
    parser.close()
    lines = _Lines(text)
    body = [
        f"The structure of the page {rel} ({lines.last} lines): its landmarks, headings, forms "
        "and components. Its scripts are not read.",
        *parser.summary(),
    ]
    title = f"Page {rel}: {parser.title}" if parser.title else f"Page {rel}"
    return [_unit(
        artifact_id, "pattern", title, "\n".join(body), Location(rel, 1, lines.last),
        (NAME, "page"),
    )]


_COMPONENT_FUNCTION = re.compile(r"(?<![\w$])function\s*\*?\s*([A-Z][\w$]*)\s*(?:<[^()]*?>)?\s*\(")
_COMPONENT_CONST = re.compile(
    r"(?<![\w$])(?:const|let|var)\s+([A-Z][\w$]*)\s*(?::[^=;]*)?=\s*"
    r"(?:[\w$.]+\s*(?:<[^()]*?>)?\s*\(\s*)?(?:async\s+)?(?:function\s*[\w$]*\s*)?\("
)
_ARROW_OR_BODY = re.compile(r"\s*(?::[^=;{]*)?(?:=>|\{)")
_TYPED_PARAM = re.compile(r"\s*[A-Za-z_$][\w$]*\s*:\s*([A-Za-z_$][\w$]*)")
_TYPE_DECLARATION = re.compile(
    r"(?<![\w$])(?:interface\s+([A-Za-z_$][\w$]*)\s*(?:<[^{]*?>)?\s*(?:extends\s+[^{]*?)?\{"
    r"|type\s+([A-Za-z_$][\w$]*)\s*(?:<[^=]*?>)?\s*=\s*\{)"
)
_PROP_TYPES = re.compile(r"(?<![\w$])([A-Z][\w$]*)\.propTypes\s*=\s*\{")
_SCRIPT_BLOCK = re.compile(r"<script\b[^>]*>(.*?)</script\s*>", re.S | re.I)
_SCRIPT_OPEN = re.compile(r"<script\b", re.I)
_DEFINE_PROPS = re.compile(r"(?<![\w$])defineProps\s*(?:<\s*([A-Za-z_$][\w$]*|\{)|\(\s*([\[{]))")
_OPTIONS_PROPS = re.compile(r"(?<![\w$.])props\s*:\s*[\[{]")
_EXPORT_LET = re.compile(r"(?<![\w$])export\s+let\s+([^;\n]+)")
_RUNES_PROPS = re.compile(r"(?<![\w$])let\s*\{")
_RUNES_TAIL = re.compile(r"\s*(?::[^=]*)?=\s*\$props\s*\(")


def _declared_types(code: _Code, start: int, end: int) -> dict[str, tuple[int, list[str]]]:
    """The interfaces and object type aliases declared between start and end: their lines and
    members."""
    types: dict[str, tuple[int, list[str]]] = {}
    for match in _TYPE_DECLARATION.finditer(code.masked, start, end):
        name = match.group(1) or match.group(2)
        if name in types or len(types) >= MAX_COMPONENTS:
            continue
        try:
            close_at = _closing(code.masked, match.end() - 1, end)
        except _Unbalanced as exc:
            code.unbalanced(f"the type {_clip(name, 80)}", match.start(), exc)
            continue
        types[name] = (code.lines.line(match.start()), _members(code, match.end() - 1, close_at))
    return types


def _literal_members(code: _Code, start: int, open_at: int, what: str,
                     end: int | None = None) -> list[str]:
    """The members of the literal whose bracket is at open_at, for what starts at start; none,
    and a problem recorded, if its brackets do not pair before end."""
    try:
        close_at = _closing(code.masked, open_at, end)
    except _Unbalanced as exc:
        code.unbalanced(what, start, exc)
        return []
    return _members(code, open_at, close_at)


def _params(code: _Code, open_at: int, close_at: int,
            types: dict[str, tuple[int, list[str]]]) -> tuple[str, list[str]]:
    """A component's props from its parameter list: what it destructures, or the members of
    the type it declares for them."""
    start, end = _trim(code.masked, open_at + 1, close_at)
    if start == end:
        return ": no props", []
    if code.masked[start] == "{":
        inner = _closing(code.masked, start)
        if start < inner < close_at:
            return "", _members(code, start, inner)
    typed = _TYPED_PARAM.match(code.masked, open_at + 1, close_at)
    if typed and typed.group(1) in types:
        return f": props typed as {typed.group(1)}", types[typed.group(1)][1]
    return ": props taken whole, so not listed", []


def _jsx_props(code: _Code) -> list[str]:
    types = _declared_types(code, 0, len(code.masked))
    found = sorted(
        [(match.start(), match, False) for match in _COMPONENT_FUNCTION.finditer(code.masked)]
        + [(match.start(), match, True) for match in _COMPONENT_CONST.finditer(code.masked)],
        key=lambda item: item[0],
    )
    lines: list[str] = []
    named: set[str] = set()
    for _, match, is_const in found:
        name = match.group(1)
        if name in named or len(named) >= MAX_COMPONENTS:
            continue
        open_at = match.end() - 1
        line = code.lines.line(match.start(1))
        try:
            close_at = _closing(code.masked, open_at)
        except _Unbalanced as exc:
            named.add(name)
            code.unbalanced(f"the parameters of {_clip(name, 80)}", match.start(), exc)
            lines.append(f"- {name} (line {line}): parameters not readable (see its 'unparsed' unit)")
            continue
        if is_const and not _ARROW_OR_BODY.match(code.masked, close_at + 1):
            continue
        named.add(name)
        note, members = _params(code, open_at, close_at, types)
        lines.append(f"- {name} (line {line}){note}")
        lines += [f"  - {member}" for member in members[:MAX_LISTED]]
    for match in list(_PROP_TYPES.finditer(code.masked))[:MAX_COMPONENTS]:
        members = _literal_members(
            code, match.start(), match.end() - 1, f"the propTypes of {_clip(match.group(1), 80)}"
        )
        lines.append(f"- {match.group(1)}.propTypes (line {code.lines.line(match.start())})")
        lines += [f"  - {member}" for member in members[:MAX_LISTED]]
    body = ["Components:", *lines] if lines else ["Components: none found"]
    declared = [(name, line, members) for name, (line, members) in types.items() if name.endswith("Props")]
    if declared:
        body.append("Prop types:")
        for name, line, members in declared:
            body.append(f"- {name} (line {line})")
            body += [f"  - {member}" for member in members[:MAX_LISTED]]
    return body


def _sfc_props(code: _Code, framework: str) -> list[str]:
    """The props a Vue or Svelte single-file component declares in its script blocks."""
    props: list[str] = []
    masked = code.masked
    after = 0
    for block in _SCRIPT_BLOCK.finditer(masked):
        start, end = block.start(1), block.end(1)
        after = block.end()
        types = _declared_types(code, start, end)
        if framework == "vue":
            for match in _DEFINE_PROPS.finditer(masked, start, end):
                named = match.group(1)
                if named and named != "{":
                    declared = types.get(named)
                    props += declared[1] if declared else [
                        f"line {code.lines.line(match.start())}: typed as {named}, declared elsewhere"
                    ]
                else:
                    props += _literal_members(code, match.start(), match.end() - 1, "defineProps", end)
            for match in _OPTIONS_PROPS.finditer(masked, start, end):
                props += _literal_members(code, match.start(), match.end() - 1, "the props option", end)
        else:
            for match in _EXPORT_LET.finditer(masked, start, end):
                prop = _clip(_squash(code.text[match.start(1):match.end(1)]), 120)
                props.append(f"line {code.lines.line(match.start(1))}: {prop}")
            for match in _RUNES_PROPS.finditer(masked, start, end):
                open_at = match.end() - 1
                try:
                    close_at = _closing(masked, open_at, end)
                except _Unbalanced as exc:
                    code.unbalanced("a destructuring let", match.start(), exc)
                    continue
                if _RUNES_TAIL.match(masked, close_at + 1, end):
                    props += _members(code, open_at, close_at)
    unclosed = _SCRIPT_OPEN.search(masked, after)
    if unclosed:
        code.problem(
            f"the <script> on line {code.lines.line(unclosed.start())} is never closed: it is not read",
            unclosed.start(), len(masked),
        )
    if not props:
        return ["Props: none readable from the source"]
    return _listed("Props", [f"- {prop}" for prop in props])


def _read_component(artifact_id: str, rel: str, text: str) -> list[Unit]:
    """A component file as a pattern Unit: its components and their props where the source
    states them, and for Vue and Svelte the outline of its markup."""
    name, _, framework = rel.rsplit("/", 1)[-1].rpartition(".")
    framework = framework.lower()
    code = _Code(text, script=True)
    body = [
        f"The {framework} component file {rel} ({code.lines.last} lines): its props, read from "
        "the source as text. Nothing in it is run."
    ]
    if framework in ("jsx", "tsx"):
        body += _jsx_props(code)
    else:
        body += _sfc_props(code, framework)
        body.append("Markup structure:")
        try:
            body += _structure_lines(text, scripts=False)
        except Exception as exc:  # markup past what the parser tolerates: say so, do not raise
            body.append("- not readable (see its 'unparsed' unit)")
            code.problem(f"the markup cannot be read: {_reason(exc)}", 0, len(text))
    if code.problems:
        body.append(f"Not read: {len(code.problems)} part(s), each in an 'unparsed' unit")
    return [_unit(
        artifact_id, "pattern", f"Component {name}: {rel}", "\n".join(body),
        Location(rel, 1, code.lines.last), (NAME, "component", framework),
    ), *code.unparsed(artifact_id, rel)]


_READERS = {
    "css": _read_css,
    "tokens": _read_tokens,
    "tailwind": _read_tailwind,
    "liquid": _read_liquid,
    "settings_schema": _read_settings_schema,
    "html": _read_html,
    "component": _read_component,
}
_LABELS = {
    "css": "a stylesheet",
    "tokens": "a design-token file",
    "tailwind": "a Tailwind configuration",
    "liquid": "a Liquid template",
    "settings_schema": "theme settings",
    "html": "an HTML page",
    "component": "a component",
}
