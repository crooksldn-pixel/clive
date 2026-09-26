"""The Knowledge Digester's adapter for agent skills and agent or harness configuration.

It reads a quarantined artifact and says what is in it as Units, and does nothing else: no
file it reads is executed, imported or installed, nothing is written, and no link that leads
out of the artifact is followed. What it reads:

  SKILL.md           the front matter's name and description are a knowledge Unit; each list
                     of steps is a procedure; imperative guidance ("always", "never", "must",
                     "do not") is a rule; a stated verification step is a check; and each file
                     the skill references is a script or an example by its extension, its
                     content bounded and never run. A folder of skills yields every skill.
  harness files      CLAUDE.md, AGENTS.md, GEMINI.md, .cursorrules, .cursor/rules/, ...: rules
                     and procedures, read the same way.
  prompt libraries   prompts.md, *.prompt, prompts/*.json, .claude/commands/, ...: one example
                     Unit per prompt.

Everything is bounded — the files looked at, the bytes read from each, the references
followed and the Units returned — and ordered by path and then by line, so the same artifact
gives the same Units. What cannot be read is not an exception: it is a knowledge Unit tagged
'unparsed' that says why."""

from __future__ import annotations

import json
import os
import posixpath
import re
import stat
import textwrap
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from app.digest.model import ARTIFACT_ID_PATTERN, MAX_BODY, MAX_TAG, MAX_TITLE, Location, Unit

NAME = "skills"
HANDLES = (
    "skill", "skill collection", "agent configuration", "harness configuration", "prompt library",
)

MAX_FILES = 5_000              # files looked at in one artifact
MAX_DEPTH = 24                 # directories entered below the root
MAX_FILE_BYTES = 512 * 1024    # bytes read from any one file
MAX_REFERENCES = 100           # files followed from one skill
MAX_UNITS = 10_000             # Units returned for one artifact, the last saying it stopped
MAX_FRONT_MATTER_LINES = 500

SKIPPED_DIRECTORIES = frozenset(
    {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".tox"}
)
HARNESS_FILES = frozenset({
    "claude.md", "claude.local.md", "agents.md", "agent.md", "gemini.md", ".cursorrules",
    ".windsurfrules", ".clinerules", ".goosehints", "copilot-instructions.md",
})
HARNESS_FOLDERS = (
    (".cursor", "rules"), (".windsurf", "rules"), (".clinerules",), (".claude", "agents"),
    (".github", "instructions"),
)
HARNESS_SUFFIXES = frozenset({".md", ".mdc", ".markdown", ".txt", ""})
COMMAND_FOLDERS = ((".claude", "commands"), (".cursor", "commands"))   # one prompt per file
PROMPT_FOLDERS = frozenset({"prompts", "prompt-library", "prompt_library"})
PROMPT_SUFFIXES = frozenset(
    {".md", ".markdown", ".txt", ".prompt", ".json", ".jsonl", ".yaml", ".yml"}
)
SCRIPT_SUFFIXES = frozenset({
    ".py", ".sh", ".bash", ".zsh", ".fish", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl", ".php",
    ".ps1", ".psm1", ".bat", ".cmd", ".lua", ".r", ".go", ".rs", ".java", ".kt", ".swift",
    ".applescript", ".scpt",
})
PROMPT_KEYS = ("prompt", "template", "content", "text", "body", "system", "instructions", "messages")
PROMPT_TITLE_KEYS = ("name", "title", "act", "id", "key")

# Greedy groups, trimmed afterwards: a lazy group before optional trailing whitespace is
# quadratic on a long line of spaces, and what is read here is not trusted.
_HEADING = re.compile(r" {0,3}(#{1,6})[ \t]+(.*)")
_ITEM = re.compile(r"([ \t]*)(?:(\d{1,9})[.)]|[-*+])[ \t]+(\S.*)")
_FENCE = re.compile(r"[ \t]*(`{3,}|~{3,})")
_DIVIDER = re.compile(r" {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*")
_KEY = re.compile(r"([A-Za-z_][\w.-]*)[ \t]*:(?:[ \t]+(.*))?")
_SENTENCE = re.compile(r"\S.*?(?:[.!?](?=\s|$)|$)", re.S)
_RULE = re.compile(
    r"\b(?:always|never|must|mustn['’]t|do not|don['’]t|shall|should not|shouldn['’]t)\b", re.I
)
_CHECK = re.compile(
    r"[\s*_`>]*(?:verify|verif(?:ies|ication)|checks?(?!\s+out\b)|confirm|validate|assert"
    r"|test that|run\b[^.\n]*?\b(?:tests?|checks?|linters?|lint|pytest|ruff|mypy))\b",
    re.I,
)
_RUN = re.compile(r"[\s*_`>]*(?:(?:you[ \t]+)?(?:always|must)[ \t]+)?(?:run|execute)\b", re.I)
_CHECK_HEADING = re.compile(
    r"\b(?:verif\w*|validat\w*|checks?|checklist|tests?|testing|acceptance|confirm\w*"
    r"|done when|definition of done|quality gates?)\b",
    re.I,
)
_RULE_HEADING = re.compile(
    r"\b(?:rules?|guidelines?|constraints?|conventions?|principles?|guardrails?|polic(?:y|ies)"
    r"|requirements?|don['’]?ts|never|always|must|important)\b",
    re.I,
)
_STEPS_HEADING = re.compile(
    r"\b(?:steps?|procedures?|workflows?|process(?:es)?|how[ -]to)\b", re.I
)
_LINK =re.compile(r"\]\(\s*<?([^()<>\s]+)>?(?:\s+(?:\"[^\"]*\"|'[^']*'))?\s*\)")
_PATH = re.compile(
    r"(?<![\w/.~$-])((?:\./)?[\w-][\w.-]*(?:/[\w.-]+)*\.[A-Za-z0-9]{1,10})(?![\w/-])"
)
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")


# --- the Units, as they are found ------------------------------------------------------------


def _title(text: str, fallback: str) -> str:
    words = " ".join(text.split()) or " ".join(fallback.split()) or "untitled"
    return words if len(words) <= MAX_TITLE else words[: MAX_TITLE - 1] + "…"


def _tag(tag: str) -> str:
    return " ".join(tag.split())[:MAX_TAG].strip()


class _Units:
    """The Units read so far, in order: each once, and never more than MAX_UNITS."""

    def __init__(self, artifact_id: str) -> None:
        self.artifact_id = artifact_id
        self.units: list[Unit] = []
        self.ids: set[str] = set()
        self.referenced: set[str] = set()    # files already read as a skill's reference
        self.full = False

    def add(self, kind: str, title: str, body: str, path: str,
            span: tuple[int, int] | None = None, tags: tuple[str, ...] = ()) -> None:
        if self.full:
            return
        if len(self.units) >= MAX_UNITS - 1:
            self.full = True
            kind, title, path, span = "knowledge", "Unparsed: the rest of the artifact", ".", None
            body, tags = f"stopped after {MAX_UNITS - 1} units; the rest is not digested", ("unparsed",)
        cut = ("truncated",) if len(body) > MAX_BODY else ()
        tags = tuple(dict.fromkeys(tag for tag in (_tag(t) for t in (*tags, *cut)) if tag))
        try:
            location = Location(path, *span) if span else Location(path)
        except ValueError:
            location = Location(".")
        unit = Unit(self.artifact_id, kind, _title(title, path), body[:MAX_BODY], location, tags)
        if unit.id not in self.ids:
            self.ids.add(unit.id)
            self.units.append(unit)

    def unparsed(self, path: str, span: tuple[int, int] | None, reason: str) -> None:
        self.add("knowledge", f"Unparsed: {path}", reason, path, span, ("unparsed",))


# --- finding and reading files ---------------------------------------------------------------


def _walk(root: Path) -> tuple[list[str], bool, int]:
    """Every file under root as a relative POSIX path, sorted; whether the walk stopped at
    MAX_FILES; and how many names were skipped for not being UTF-8. Links to directories are
    not entered."""
    found: list[str] = []
    unnamed = 0
    for here, directories, files in os.walk(root):
        relative = os.path.relpath(here, root)
        parts = () if relative == os.curdir else tuple(relative.split(os.sep))
        directories[:] = (
            sorted(d for d in directories if d not in SKIPPED_DIRECTORIES)
            if len(parts) < MAX_DEPTH else []
        )
        for name in sorted(files):
            rel = "/".join((*parts, name))
            try:
                rel.encode("utf-8")
            except UnicodeEncodeError:
                unnamed += 1
                continue
            if len(found) == MAX_FILES:
                return sorted(found), True, unnamed
            found.append(rel)
    return sorted(found), False, unnamed


def _within(folders: tuple[str, ...], sequence: tuple[str, ...]) -> bool:
    size = len(sequence)
    return any(folders[i:i + size] == sequence for i in range(len(folders) - size + 1))


def _classify(rel: str) -> str | None:
    path = PurePosixPath(rel)
    name, suffix = path.name.lower(), path.suffix.lower()
    folders = tuple(part.lower() for part in path.parts[:-1])
    if name == "skill.md":
        return "skill"
    if name in HARNESS_FILES or (
        suffix in HARNESS_SUFFIXES and any(_within(folders, f) for f in HARNESS_FOLDERS)
    ):
        return "harness"
    if suffix in PROMPT_SUFFIXES and (
        "prompt" in name or bool(PROMPT_FOLDERS & set(folders))
        or any(_within(folders, f) for f in COMMAND_FOLDERS)
    ):
        return "prompts"
    return None


def _read(root: Path, rel: str) -> tuple[str | None, bool, str]:
    """The file as text, whether it was cut at MAX_FILE_BYTES, and — when the text is None —
    why it could not be read. Only regular files are opened: never a link, pipe or device."""
    path = root / rel
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return None, False, "not a regular file (links and devices are not followed)"
        with path.open("rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        return None, False, f"could not be read ({type(exc).__name__})"
    truncated = len(data) > MAX_FILE_BYTES
    data = data[:MAX_FILE_BYTES]
    if b"\x00" in data:
        return None, truncated, "binary content, not text"
    for cut in range(4 if truncated else 1):   # a cut may fall inside a character
        try:
            text = data[: len(data) - cut].decode("utf-8")
            break
        except UnicodeDecodeError:
            continue
    else:
        return None, truncated, "not UTF-8 text"
    return text.removeprefix("﻿").replace("\r\n", "\n"), truncated, ""


def _lines(text: str) -> list[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def _span(text: str) -> tuple[int, int] | None:
    if not text:
        return None
    return 1, text.count("\n") + (0 if text.endswith("\n") else 1)


def _inside(root: Path, rel: str) -> bool:
    """True when no link on the way to rel leads anywhere else."""
    return os.path.realpath(os.path.join(root, rel)) == os.path.join(os.path.realpath(root), rel)


# --- front matter ----------------------------------------------------------------------------


def _front_matter(lines: list[str]) -> tuple[dict[str, str] | None, int, str]:
    """(fields, the lines it takes, a problem). No front matter is (None, 0, ""); front matter
    never closed is (None, 0, why); a line that is not 'key: value' is ({}, lines, why)."""
    if not lines or lines[0].strip() != "---":
        return None, 0, ""
    for end in range(1, min(len(lines), MAX_FRONT_MATTER_LINES + 1)):
        if lines[end].strip() in ("---", "..."):
            break
    else:
        return None, 0, "the front matter is opened with '---' and never closed"
    entries: list[tuple[str, str, list[str]]] = []
    for index in range(1, end):
        line = lines[index]
        if line.startswith("#"):
            continue
        if not line.strip() or line[:1] in (" ", "\t") or line.startswith("- "):
            if entries:
                entries[-1][2].append(line)
            elif line.strip():
                return {}, end + 1, f"line {index + 1} of the front matter belongs to no key"
            continue
        key = _KEY.fullmatch(line)
        if key is None:
            return {}, end + 1, f"line {index + 1} of the front matter is not 'key: value'"
        entries.append((key.group(1), (key.group(2) or "").strip(), []))
    return {key: _scalar(value, more) for key, value, more in entries}, end + 1, ""


def _scalar(value: str, more: list[str]) -> str:
    block = textwrap.dedent("\n".join(more)).strip("\n")
    if re.fullmatch(r"[|>][-+]?\d?", value):
        if value[0] == ">":
            return re.sub(r"(?<!\n)\n(?!\n)", " ", block).strip()
        return block.strip()
    if not value:
        return block.strip()
    text = " ".join([value, *(line.strip() for line in more if line.strip())])
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        if text[0] == "'":
            return text[1:-1].replace("''", "'")
        try:
            decoded = json.loads(text)
        except ValueError:
            return text[1:-1]
        return decoded if isinstance(decoded, str) else text[1:-1]
    return text


# --- markdown: steps, rules and checks -------------------------------------------------------


@dataclass
class _Block:
    kind: str           # "heading", "item", "paragraph" or "break"
    start: int          # 1-based, inclusive
    end: int
    lines: list[str] = field(default_factory=list)
    text: str = ""      # a heading's words
    numbered: bool = False


def _heading_text(text: str) -> str:
    """A heading's words, without the closing #s some headings carry ("## Steps ##")."""
    text = text.strip()
    bare = text.rstrip("#")
    return bare.strip() if bare != text and (not bare or bare[-1] in " \t") else text


def _blocks(lines: list[str], first: int) -> list[_Block]:
    """Headings, list items (with their continuation lines, fenced code included), paragraphs
    and breaks, from lines[first:]. Nothing inside a fence is taken for a heading or an item."""
    blocks: list[_Block] = []
    item: _Block | None = None
    paragraph: _Block | None = None
    fence: str | None = None
    fence_in_item = False
    blank = False
    for index in range(first, len(lines)):
        line, number = lines[index], index + 1
        if fence is not None:
            if item is not None and fence_in_item:
                item.end = number
                item.lines.append(line)
            closing = line.strip()
            if closing.startswith(fence) and set(closing) == {fence[0]}:
                fence = None
            continue
        opening = _FENCE.match(line)
        if opening:
            paragraph = None
            fence = opening.group(1)
            fence_in_item = item is not None and line[:1] in (" ", "\t")
            if item is not None and fence_in_item:
                item.end = number
                item.lines.append(line)
            else:
                item = None
                blocks.append(_Block("break", number, number))
            blank = False
            continue
        if not line.strip():
            paragraph = None
            blank = True
            continue
        heading = _HEADING.fullmatch(line)
        title = _heading_text(heading.group(2)) if heading else ""
        if title:
            item = paragraph = None
            blocks.append(_Block("heading", number, number, [line], title))
            blank = False
            continue
        if _DIVIDER.fullmatch(line):
            item = paragraph = None
            blocks.append(_Block("break", number, number, [line]))
            blank = False
            continue
        marker = _ITEM.fullmatch(line)
        if marker:
            paragraph = None
            item = _Block("item", number, number, [line], numbered=marker.group(2) is not None)
            blocks.append(item)
            blank = False
            continue
        if item is not None and (line[:1] in (" ", "\t") or not blank):
            item.end = number
            item.lines.append(line)
            blank = False
            continue
        item = None
        if paragraph is None:
            paragraph = _Block("paragraph", number, number, [line])
            blocks.append(paragraph)
        else:
            paragraph.end = number
            paragraph.lines.append(line)
        blank = False
    return blocks


def _section(heading: str | None) -> str:
    if heading and _CHECK_HEADING.search(heading):
        return "check"
    if heading and _RULE_HEADING.search(heading):
        return "rule"
    return ""


def _item_text(block: _Block) -> str:
    marker = _ITEM.fullmatch(block.lines[0])
    first = marker.group(3) if marker else block.lines[0]
    return " ".join(" ".join([first, *block.lines[1:]]).split())


def _kinds(rule: bool, check: bool) -> tuple[str, ...]:
    """What some guidance is: a rule, a check, both — an imperative verification step is
    each — or neither."""
    return (("rule",) if rule else ()) + (("check",) if check else ())


def _item_kinds(text: str, section: str) -> tuple[str, ...]:
    """rule and check, either, or neither for a plain step."""
    return _kinds(section == "rule" or bool(_RULE.search(text)),
                  section == "check" or bool(_CHECK.match(text)))


def _guidance(lines: list[str], first: int, units: _Units, rel: str, context: str,
              tags: tuple[str, ...]) -> None:
    """Procedures, rules and checks from the markdown in lines[first:]."""
    blocks = _blocks(lines, first)
    heading: str | None = None
    section = ""
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if block.kind == "item":
            run: list[_Block] = []
            while index < len(blocks) and blocks[index].kind == "item":
                run.append(blocks[index])
                index += 1
            _list_units(lines, run, heading, section, units, rel, context, tags)
            continue
        if block.kind == "heading":
            heading, section = block.text, _section(block.text)
        elif block.kind == "paragraph":
            _paragraph_units(block, section, units, rel, tags)
        index += 1


def _list_units(lines: list[str], run: list[_Block], heading: str | None, section: str,
                units: _Units, rel: str, context: str, tags: tuple[str, ...]) -> None:
    items = [(block, _item_text(block)) for block in run]
    kinds = [_item_kinds(text, section) for _, text in items]
    steps = bool(heading and _STEPS_HEADING.search(heading))    # a steps section, whatever its items
    if steps or (not section and (any(block.numbered for block in run) or () in kinds)):
        start, end = run[0].start, run[-1].end
        body = "\n".join(lines[start - 1:end])
        units.add("procedure", heading or f"{context}: steps", body, rel, (start, end), tags)
    for (block, text), found in zip(items, kinds, strict=True):
        for kind in found:
            units.add(kind, text, text, rel, (block.start, block.end), tags)


def _paragraph_units(block: _Block, section: str, units: _Units, rel: str,
                     tags: tuple[str, ...]) -> None:
    text = "\n".join(block.lines)
    line, position = block.start, 0         # counted as we go: a line per sentence is linear
    for match in _SENTENCE.finditer(text):
        line += text.count("\n", position, match.start())
        position = match.start()
        words = " ".join(match.group().split())
        found = _kinds(bool(_RULE.search(words)),
                       bool(_CHECK.match(words) or (section == "check" and _RUN.match(words))))
        last = line + text.count("\n", match.start(), match.end() - 1)
        for kind in found:
            units.add(kind, words, words, rel, (line, last), tags)


# --- skills and the files they reference -----------------------------------------------------


def _skill(root: Path, rel: str, units: _Units, documents: dict[str, str]) -> None:
    text, truncated, problem = _read(root, rel)
    if text is None:
        units.unparsed(rel, None, problem)
        return
    if truncated:
        units.unparsed(rel, None, f"only the first {MAX_FILE_BYTES} bytes were read")
    lines = _lines(text)
    fields, taken, problem = _front_matter(lines)
    if fields is None and problem:
        units.unparsed(rel, (1, 1), f"{problem}; the skill is not read")
        return
    fields = fields or {}
    name = fields.get("name", "").strip() if not problem else ""
    description = fields.get("description", "").strip() if not problem else ""
    skill_name = name or posixpath.basename(posixpath.dirname(rel)) or "skill"
    tags = ("skill", f"skill:{skill_name}")
    if taken == 0:
        units.unparsed(rel, None, "SKILL.md has no front matter: no name or description")
    elif problem:
        units.unparsed(rel, (1, taken), problem)
    elif name and description:
        others = [f"{key}: {value}" for key, value in fields.items()
                  if key not in ("name", "description")]
        units.add("knowledge", name, "\n\n".join([description, *others]) if others else description,
                  rel, (1, taken), tags)
    else:
        missing = " and ".join(key for key, value in (("name", name), ("description", description))
                               if not value)
        units.unparsed(rel, (1, taken), f"the front matter has no {missing}")
    _guidance(lines, taken, units, rel, skill_name, tags)
    _references(root, rel, lines, taken, units, documents, tags)


def _target(folder: str, target: str) -> tuple[str | None, str]:
    """The artifact path a reference names, or None and — when it matters — why not."""
    target = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not target or _SCHEME.match(target):
        return None, ""         # an anchor in the same file, a URL or an address
    if target.startswith("/") or "\\" in target or "\x00" in target:
        return None, "an absolute path, not followed"
    joined = posixpath.normpath(posixpath.join(folder, target))
    if joined == "..":
        return None, "outside the artifact, not followed"
    if joined.startswith("../"):
        return None, "outside the artifact, not followed"
    return (None, "") if joined == "." else (joined, "")


def _references(root: Path, rel: str, lines: list[str], first: int, units: _Units,
                documents: dict[str, str], tags: tuple[str, ...]) -> None:
    """Each file the skill names — by a link, or as a path that is there — once, in the order
    they are first named. A link to nothing, or out of the artifact, is said so."""
    folder = posixpath.dirname(rel)
    named: dict[str, tuple[int, bool]] = {}      # path: the line first naming it, by a link?
    problems: list[tuple[int, str]] = []
    for index in range(first, len(lines)):
        for match in _LINK.finditer(lines[index]):
            target, problem = _target(folder, match.group(1))
            if problem:
                problems.append((index + 1, f"{match.group(1)}: {problem}"))
            elif target is not None and target not in named:
                named[target] = (index + 1, True)
        for match in _PATH.finditer(lines[index]):
            target, _ = _target(folder, match.group(1))
            if target is not None and target not in named:
                named[target] = (index + 1, False)
    followed = 0
    for target, (number, linked) in named.items():
        if target == rel or target in documents:
            continue             # a skill, harness file or prompt library is read as itself
        full = os.path.join(root, target)
        if not os.path.lexists(full):
            if linked:
                problems.append((number, f"{target}: the referenced file is not in the artifact"))
            continue
        if not _inside(root, target):
            problems.append((number, f"{target}: a link that leads out of the artifact, not followed"))
            continue
        if os.path.isdir(full) or target in units.referenced:
            continue
        if followed == MAX_REFERENCES:
            problems.append((number, f"only the first {MAX_REFERENCES} referenced files are read"))
            break
        followed += 1
        _referenced(root, target, units, tags)
    for number, reason in sorted(problems):
        units.unparsed(rel, (number, number), reason)


def _referenced(root: Path, rel: str, units: _Units, tags: tuple[str, ...]) -> None:
    """A referenced file as a script or an example, by its extension — or by a #! line, since
    either way it would run. Its content is recorded, bounded; it is never run."""
    units.referenced.add(rel)
    text, truncated, problem = _read(root, rel)
    if text is None:
        units.unparsed(rel, None, problem)
        return
    script = PurePosixPath(rel).suffix.lower() in SCRIPT_SUFFIXES or text.startswith("#!")
    body = text[:MAX_BODY]
    cut = ("truncated",) if truncated or len(text) > MAX_BODY else ()
    units.add("script" if script else "example", rel, body, rel, _span(body),
              (*tags, "referenced", *cut))


# --- harness configuration -------------------------------------------------------------------


def _harness(root: Path, rel: str, units: _Units, documents: dict[str, str]) -> None:
    text, truncated, problem = _read(root, rel)
    if text is None:
        units.unparsed(rel, None, problem)
        return
    if truncated:
        units.unparsed(rel, None, f"only the first {MAX_FILE_BYTES} bytes were read")
    lines = _lines(text)
    tags = ("harness",)
    fields, taken, problem = _front_matter(lines)
    if fields is None and problem:
        units.unparsed(rel, (1, 1), f"{problem}; the file is not read")
        return
    if problem:
        units.unparsed(rel, (1, taken), problem)
    elif fields:
        title = fields.get("name") or fields.get("description") or rel
        body = "\n".join(f"{key}: {value}" for key, value in fields.items())
        units.add("knowledge", title, body, rel, (1, taken), tags)
    _guidance(lines, taken, units, rel, posixpath.basename(rel), tags)


# --- prompt libraries ------------------------------------------------------------------------


def _prompts(root: Path, rel: str, units: _Units, documents: dict[str, str]) -> None:
    suffix = PurePosixPath(rel).suffix.lower()
    if suffix in (".yaml", ".yml"):
        units.unparsed(rel, None, "YAML is not read: the standard library has no YAML parser")
        return
    text, truncated, problem = _read(root, rel)
    if text is None:
        units.unparsed(rel, None, problem)
        return
    if truncated:
        units.unparsed(rel, None, f"only the first {MAX_FILE_BYTES} bytes were read")
    tags = ("prompt",)
    if suffix == ".json":
        _json_prompts(text, rel, units, tags)
    elif suffix == ".jsonl":
        _jsonl_prompts(_lines(text), rel, units, tags)
    else:
        folders = tuple(part.lower() for part in PurePosixPath(rel).parts[:-1])
        whole = any(_within(folders, f) for f in COMMAND_FOLDERS)
        _text_prompts(_lines(text), rel, units, tags, whole)


def _text_prompts(lines: list[str], rel: str, units: _Units, tags: tuple[str, ...],
                  whole: bool) -> None:
    """One prompt per section under a heading; without headings, one per part between
    dividers ('---'); without either — or for a command, which is one prompt — the file."""
    _, taken, problem = _front_matter(lines)
    if problem:
        taken = 0      # a leading '---' that opens no front matter: a divider, and all prompt
    blocks = [] if whole else _blocks(lines, taken)
    headings = [block for block in blocks if block.kind == "heading"]
    parts: list[tuple[int, int, str | None]] = []       # first line, last line, title
    if whole:
        name = PurePosixPath(rel).name.split(".")[0]
        parts.append((taken + 1, len(lines), f"/{name}" if name else None))
    elif headings:
        parts.append((taken + 1, headings[0].start - 1, None))
        for block, after in zip(headings, [*headings[1:], None], strict=True):
            parts.append((block.start + 1, after.start - 1 if after else len(lines), block.text))
    else:
        start = taken + 1
        for block in blocks:
            if block.kind == "break" and block.lines:     # a divider, not a fence
                parts.append((start, block.start - 1, None))
                start = block.start + 1
        parts.append((start, len(lines), None))
    for start, end, title in parts:
        while start <= end and not lines[start - 1].strip():
            start += 1
        while end >= start and not lines[end - 1].strip():
            end -= 1
        if start > end:
            continue
        body = "\n".join(lines[start - 1:end])
        units.add("example", title or lines[start - 1], body, rel, (start, end), tags)


def _prompt(value: object, key: str | None) -> tuple[str | None, str | None]:
    """The prompt text in a JSON value, and its title."""
    if isinstance(value, str):
        return (value if value.strip() else None), key
    if not isinstance(value, dict):
        return None, key
    title = next((str(value[k]) for k in PROMPT_TITLE_KEYS
                  if isinstance(value.get(k), (str, int)) and str(value[k]).strip()), key)
    for name in PROMPT_KEYS:
        if name in value:
            found = value[name]
            text = found if isinstance(found, str) else json.dumps(found, ensure_ascii=False, indent=2)
            if text.strip():
                return text, title
    return None, title


def _skip(text: str, index: int) -> int:
    while index < len(text) and text[index] in " \t\n\r":
        index += 1
    return index


def _members(text: str, start: int) -> list[tuple[str | None, object, int, int]] | None:
    """The members of the JSON array or object at text[start]: each key (None in an array),
    value, and where it starts and ends, so that every prompt has its exact lines."""
    decoder = json.JSONDecoder()
    opening = text[start:start + 1]
    if opening not in ("[", "{"):
        return None
    closing = "]" if opening == "[" else "}"
    members: list[tuple[str | None, object, int, int]] = []
    index = _skip(text, start + 1)
    if text[index:index + 1] == closing:
        return members
    while True:
        begin, key = index, None
        if opening == "{":
            key, index = decoder.raw_decode(text, index)
            index = _skip(text, index)
            if text[index:index + 1] != ":":
                return None
            index = _skip(text, index + 1)
        value, end = decoder.raw_decode(text, index)
        members.append((key if isinstance(key, str) else None, value, begin, end))
        index = _skip(text, end)
        mark = text[index:index + 1]
        if mark != ",":
            return members if mark == closing else None
        index = _skip(text, index + 1)


def _json_prompts(text: str, rel: str, units: _Units, tags: tuple[str, ...]) -> None:
    try:
        data = json.loads(text)
    except (ValueError, RecursionError) as exc:
        units.unparsed(rel, None, f"not valid JSON: {exc}")
        return
    start = _skip(text, 0)
    if isinstance(data, dict) and isinstance(data.get("prompts"), (list, dict)):
        starts = [begin for key, _, begin, _ in _members(text, start) or () if key == "prompts"]
        if not starts:
            units.unparsed(rel, None, "the prompts could not be located in the file")
            return
        # the member's start is its key: the list or object is after the colon
        start = _skip(text, _skip(text, json.JSONDecoder().raw_decode(text, starts[-1])[1]) + 1)
        data = data["prompts"]
    if isinstance(data, dict) and any(isinstance(data.get(k), str) for k in PROMPT_KEYS):
        members: list[tuple[str | None, object, int, int]] | None = [(None, data, start, len(text.rstrip()))]
    elif isinstance(data, (list, dict)):
        members = _members(text, start)
    else:
        units.unparsed(rel, None, "a JSON prompt library is a list or an object of prompts")
        return
    if members is None:
        units.unparsed(rel, None, "the prompts could not be located in the file")
        return
    first, position = 1, 0                  # members are in order: count lines as we go
    for number, (key, value, begin, end) in enumerate(members, 1):
        first += text.count("\n", position, begin)
        position = begin
        last = first + text.count("\n", begin, max(begin, end - 1))
        prompt, title = _prompt(value, key)
        if prompt is None:
            units.unparsed(rel, (first, last), f"entry {number} has no prompt text")
            continue
        units.add("example", title or prompt, prompt, rel, (first, last), tags)


def _jsonl_prompts(lines: list[str], rel: str, units: _Units, tags: tuple[str, ...]) -> None:
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except (ValueError, RecursionError) as exc:
            units.unparsed(rel, (number, number), f"line {number} is not valid JSON: {exc}")
            continue
        prompt, title = _prompt(value, None)
        if prompt is None:
            units.unparsed(rel, (number, number), f"line {number} has no prompt text")
            continue
        units.add("example", title or prompt, prompt, rel, (number, number), tags)


# --- the adapter -----------------------------------------------------------------------------

_READERS = {"skill": _skill, "harness": _harness, "prompts": _prompts}


def decompose(root: Path, artifact_id: str) -> list[Unit]:
    """The Units in the artifact at root, in a fixed order. Nothing read raises: what cannot be
    read is an 'unparsed' Unit. An artifact id that is not one is the caller's mistake, and is
    refused with ValueError."""
    if not isinstance(artifact_id, str) or not re.fullmatch(ARTIFACT_ID_PATTERN, artifact_id):
        raise ValueError(f"not an artifact id: {artifact_id!r}")
    units = _Units(artifact_id)
    root = Path(root)
    if not os.path.isdir(root):
        units.unparsed(".", None, "the artifact is not a directory of files")
        return units.units
    files, stopped, unnamed = _walk(root)
    documents = {rel: kind for rel in files if (kind := _classify(rel)) is not None}
    for rel, kind in documents.items():
        if units.full:
            break
        try:
            _READERS[kind](root, rel, units, documents)
        except Exception as exc:  # whatever is in what is read: say so, and never raise
            units.unparsed(rel, None, f"could not be read: {type(exc).__name__}: {str(exc)[:200]}")
    if stopped:
        units.unparsed(".", None, f"only the first {MAX_FILES} files were looked at")
    if unnamed:
        units.unparsed(".", None, f"{unnamed} file names that are not UTF-8 were skipped")
    return units.units
