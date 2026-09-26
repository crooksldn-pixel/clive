"""The documents adapter: markdown, reStructuredText, plain text and HTML, read into Units.

Each section under a heading becomes a knowledge Unit titled with its heading path; bullet
items that tell the reader what to do become rules, checklist items become checks, fenced code
becomes examples tagged with their language, and sentences that assert something checkable — a
number, a date, 'always' or 'never', a comparison — become claims, because what a source
asserts must be verified before it is trusted. Links stay in the body where they appear.

Digesting is reading: files are opened read-only without following links and are never run,
imported or installed; HTML is parsed as text by the standard library, its scripts and styles
dropped unread. The walk, the files and the output are bounded, the order is fixed (names in
code-point order, then document order), and nothing malformed raises: what cannot be read is
skipped and said so in a knowledge Unit tagged 'unparsed'."""

from __future__ import annotations

import os
import re
import stat
from bisect import bisect_right
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path

from app.digest.model import ARTIFACT_ID_PATTERN, MAX_BODY, MAX_TAG, MAX_TITLE, Location, Unit

NAME = "documents"
HANDLES = ("document", "markdown", "restructuredtext", "text", "html")

MAX_FILE_BYTES = 2_000_000   # a document larger than this is not read
MAX_DOCUMENTS = 1_000        # documents read from one artifact
MAX_ENTRIES = 20_000         # files and folders looked at, in all and in any one folder
MAX_DEPTH = 32               # folders nested deeper than this are not entered
MAX_UNITS = 10_000           # Units returned, besides the one saying the rest were cut
MAX_SENTENCE = 2_000         # a longer run without a full stop is not read as one claim

_FLAVOURS = {
    ".md": "markdown", ".markdown": "markdown", ".mdown": "markdown", ".mkd": "markdown",
    ".rst": "rst", ".rest": "rst",
    ".txt": "text", ".text": "text",
    ".html": "html", ".htm": "html", ".xhtml": "html",
}
_SKIPPED_FOLDERS = frozenset((".git", ".hg", ".svn"))   # version-control internals

# One logical line: the first and last source lines it came from, and its text.
_Line = tuple[int, int, str]

_FENCE_OPEN = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
_FENCE_CLOSE = re.compile(r" {0,3}(`{3,}|~{3,})[ \t]*")
_ATX = re.compile(r" {0,3}(#{1,6})(?=[ \t]|$)")
_SETEXT = re.compile(r" {0,3}(?:=+|-+)[ \t]*")
_BREAK = re.compile(r" {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*")
_BULLET = re.compile(r"[ \t]*[-*+][ \t]+(.*)")
_CHECKBOX = re.compile(r"\[([ xX])\](?:[ \t]+(.*))?")
_ORDERED = re.compile(r"[ \t]*\d{1,9}[.)](?:[ \t]+|$)")
_QUOTE = re.compile(r"^[ \t]*(?:>[ \t]?)+")
_ADORN = re.compile(r"([!-/:-@\[-`{-~])\1+[ \t]*")
_RST_CODE = re.compile(r"\.\.[ \t]+(?:code-block|code|sourcecode)::[ \t]*(\S*)")
_OPTION = re.compile(r":[\w-]+:.*")

_SENTENCE_END = re.compile(r"[.!?]+[\"')\]*_]*(?=\s)")
_LINK_TARGET = re.compile(r"\]\([^)]*\)|<[^<>\s]+>`_*")
_URL = re.compile(r"\b(?:https?|ftp)://\S+|\bwww\.\S+")
_CODE_SPAN = re.compile(r"`[^`]*`")
_MONTH = (
    r"(?:January|February|March|April|May|June|July|August|September|October|November|"
    r"December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?"
)
_DATE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    rf"|\b{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}(?:\s+\d{{4}})?\b"
    rf"|\b{_MONTH}\s+\d{{4}}\b"
)
_DIGIT = re.compile(r"\d")
_COMPARISON = re.compile(
    r"\b(?:(?:more|less|fewer|greater|higher|lower|larger|smaller|bigger|faster|slower|better|"
    r"worse|cheaper|older|newer|longer|shorter)(?:\s+\w+)?\s+than|at\s+(?:least|most)|"
    r"exceed(?:s|ed|ing)?|outperform(?:s|ed|ing)?|the\s+(?:best|worst|fastest|slowest|"
    r"cheapest|largest|smallest|highest|lowest))\b|[≤≥]",
    re.IGNORECASE,
)

_MODAL = re.compile(
    r"\b(?:must|mustn't|should|shouldn't|shall|needs? to|has to|have to)\b", re.IGNORECASE
)
_LABEL = re.compile(r"\W*[A-Za-z'-]+\W*:")
_WORDS = re.compile(r"[A-Za-z][A-Za-z']*")
_VERBS = frozenset("""
    add allow always apply ask avoid build bump call check choose clean close commit configure
    consider copy create define delete deploy disable do don't enable ensure escape explain
    export fix follow give handle hide ignore include install keep leave let limit lock log
    make mark merge move never only open pass pick pin please prefer print publish pull push
    put quote raise read record reduce refuse reject release remember remove rename replace
    report request require reset restart return review run save see select send set show sign
    skip sort split start stop store tag take tell treat try turn update upgrade use validate
    verify wait watch wrap write
""".split())
_NOT_AFTER_VERB = frozenset(
    "is are was were has have had can could will would does did may might".split()
)

_CUT = "\n[… cut: longer than a Unit body allows]"


def decompose(root: Path, artifact_id: str) -> list[Unit]:
    """Every document under root (or root itself, when it is one) read into Units, in a fixed
    order. The artifact id is the caller's, not the input's: one that is not an artifact id is
    refused at once, since no Unit could carry it."""
    if not isinstance(artifact_id, str) or not re.fullmatch(ARTIFACT_ID_PATTERN, artifact_id):
        raise ValueError(f"artifact_id does not match {ARTIFACT_ID_PATTERN}: {artifact_id!r}")
    units: list[Unit] = []
    cut = False
    try:
        for found in _walk(Path(root)):
            if len(units) >= MAX_UNITS:
                cut = True
                break
            if isinstance(found, _Skipped):
                units.append(_unparsed(artifact_id, found.path, found.reason))
                continue
            read, stopped = _read(artifact_id, found, MAX_UNITS - len(units))
            units.extend(read)
            cut = cut or stopped
    except Exception as exc:  # noqa: BLE001 — a fault in the walk is reported, never raised
        units.append(_unparsed(artifact_id, ".", f"reading stopped early: {type(exc).__name__}: {exc}"))
    if cut:
        units.append(_unparsed(
            artifact_id, ".", f"stopped after {MAX_UNITS} units; the rest of the artifact was not read"
        ))
    return list({unit.id: unit for unit in units}.values())


# --- finding and loading the documents -------------------------------------------------------


@dataclass(frozen=True)
class _Document:
    path: str               # relative to the artifact, as a Location takes it
    file: Path
    flavour: str


@dataclass(frozen=True)
class _Skipped:
    path: str
    reason: str


class _Unreadable(Exception):
    """A document that was not read, and why."""


def _flavour(name: str) -> str | None:
    return _FLAVOURS.get(os.path.splitext(name)[1].lower())


def _why(exc: OSError) -> str:
    return exc.strerror or type(exc).__name__


def _safe(text: str) -> str:
    """Text that can be written as UTF-8: a name that is not UTF-8 is shown escaped."""
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def _walk(root: Path) -> Iterator[_Document | _Skipped]:
    """The documents under root in a fixed order — a folder's files by name, then its folders
    by name — without following links, with what was passed over said so."""
    try:
        info = root.stat()
    except OSError as exc:
        yield _Skipped(".", f"the artifact could not be read: {_why(exc)}")
        return
    if stat.S_ISREG(info.st_mode):
        flavour = _flavour(root.name)
        if flavour and _safe(root.name) != root.name:
            yield _Skipped(".", f"a name that is not UTF-8 was not read: {root.name!r}")
        elif flavour:
            yield _Document(root.name, root, flavour)
        return
    if not stat.S_ISDIR(info.st_mode):
        yield _Skipped(".", "the artifact is neither a folder nor a regular file")
        return
    looked = documents = 0
    folders: list[tuple[Path, str, int]] = [(root, "", 0)]
    while folders:
        folder, prefix, depth = folders.pop()
        entries = _listing(folder)
        if isinstance(entries, str):
            yield _Skipped(prefix or ".", entries)
            continue
        inner: list[tuple[Path, str, int]] = []
        for entry in entries:
            looked += 1
            if looked > MAX_ENTRIES:
                yield _Skipped(".", f"more than {MAX_ENTRIES} files and folders; the rest were not looked at")
                return
            path = f"{prefix}/{entry.name}" if prefix else entry.name
            if _safe(path) != path:
                yield _Skipped(".", f"a name that is not UTF-8 was not read: {path!r}")
                continue
            try:
                flavour = _flavour(entry.name)
                if entry.is_symlink():
                    if flavour:
                        yield _Skipped(path, "a symbolic link, not followed")
                elif entry.is_dir(follow_symlinks=False):
                    if entry.name in _SKIPPED_FOLDERS:
                        continue
                    if depth >= MAX_DEPTH:
                        yield _Skipped(path, f"nested more than {MAX_DEPTH} folders deep; not entered")
                    else:
                        inner.append((Path(entry.path), path, depth + 1))
                elif flavour:
                    if not entry.is_file(follow_symlinks=False):
                        yield _Skipped(path, "not a regular file; not read")
                        continue
                    documents += 1
                    if documents > MAX_DOCUMENTS:
                        yield _Skipped(".", f"more than {MAX_DOCUMENTS} documents; the rest were not read")
                        return
                    yield _Document(path, Path(entry.path), flavour)
            except OSError as exc:
                yield _Skipped(path, f"could not be examined: {_why(exc)}")
        folders.extend(reversed(inner))


def _listing(folder: Path) -> list[os.DirEntry[str]] | str:
    """A folder's entries by name, or why they were not listed. A folder with too many entries
    is passed over whole, so which entries are read never depends on the order the disk gives."""
    try:
        with os.scandir(folder) as found:
            entries = []
            for entry in found:
                entries.append(entry)
                if len(entries) > MAX_ENTRIES:
                    return f"the folder has more than {MAX_ENTRIES} entries and was not read"
    except OSError as exc:
        return f"the folder could not be listed: {_why(exc)}"
    return sorted(entries, key=lambda entry: entry.name)


def _load(file: Path) -> str:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        descriptor = os.open(file, flags)
        with open(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise _Unreadable("not a regular file; not read")
            if info.st_size > MAX_FILE_BYTES:
                raise _Unreadable(f"larger than {MAX_FILE_BYTES} bytes; not read")
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise _Unreadable(f"could not be read: {_why(exc)}") from None
    if len(data) > MAX_FILE_BYTES:
        raise _Unreadable(f"larger than {MAX_FILE_BYTES} bytes; not read")
    if b"\x00" in data:
        raise _Unreadable("holds NUL bytes, so it is binary rather than a text document; not read")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _Unreadable(f"not UTF-8 text: byte {exc.start} cannot be decoded; not read") from None
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _read(artifact_id: str, document: _Document, budget: int) -> tuple[list[Unit], bool]:
    """One document's Units, and whether the budget cut them short."""
    try:
        text = _load(document.file)
        if document.flavour == "html":
            lines = _html_lines(text)
        else:
            lines = [(number, number, line) for number, line in enumerate(text.split("\n"), 1)]
            if lines and not lines[-1][2]:
                lines.pop()
        reader = _Reader(artifact_id, document.path, lines, document.flavour, budget)
        return reader.run(), reader.cut
    except _Unreadable as exc:
        return [_unparsed(artifact_id, document.path, str(exc))], False
    except Exception as exc:  # noqa: BLE001 — a parser fault is reported as unparsed, never raised
        reason = f"could not be parsed: {type(exc).__name__}: {exc}"
        return [_unparsed(artifact_id, document.path, reason)], False


# --- making Units ----------------------------------------------------------------------------


def _clip_title(text: str) -> str:
    text = " ".join(text.split()) or "(untitled)"
    return text if len(text) <= MAX_TITLE else text[: MAX_TITLE - 1] + "…"


def _unit(artifact_id: str, kind: str, title: str, body: str, location: Location,
          tags: tuple[str, ...] = ()) -> Unit:
    if len(body) > MAX_BODY:
        body = body[: MAX_BODY - len(_CUT)] + _CUT
        tags = (*tags, "truncated")
    return Unit(artifact_id, kind, _clip_title(title), body, location, tuple(dict.fromkeys(tags)))


def _unparsed(artifact_id: str, path: str, reason: str, start: int | None = None,
              end: int | None = None) -> Unit:
    where = _safe(path)
    try:
        location = Location(where, start, end) if where == path else Location(".")
    except ValueError:
        location = Location(".")
    title = "Unparsed: the artifact" if location.path == "." else f"Unparsed: {where}"
    return _unit(artifact_id, "knowledge", title, _safe(reason), location, ("unparsed",))


def _language(token: str | None) -> str:
    word = (token or "").strip().strip("{}.").lower()
    for prefix in ("language-", "lang-"):
        word = word.removeprefix(prefix)
    return re.sub(r"[^a-z0-9+#._-]", "", word)[:MAX_TAG]


def _atx(text: str) -> tuple[int, str] | None:
    """A markdown '#' heading: its level and text, closing hashes removed."""
    found = _ATX.match(text)
    if not found:
        return None
    title = text[found.end():].strip()
    bare = title.rstrip("#")
    if bare != title and (not bare or bare[-1] in " \t"):
        title = bare.rstrip()
    return len(found.group(1)), title


def _imperative(text: str) -> bool:
    """Whether a bullet item tells the reader what to do: it opens with a verb in the imperative,
    or says what must or should be done. A 'Label: value' item does not."""
    head = text[:300].replace("’", "'")
    if _LABEL.match(head):
        return False
    if _MODAL.search(head):
        return True
    words = _WORDS.findall(head)[:2]
    if not words or words[0].lower() not in _VERBS:
        return False
    return len(words) == 1 or words[1].lower() not in _NOT_AFTER_VERB


def _sentences(text: str) -> list[tuple[int, int, str]]:
    found = []
    begin = 0
    for end in [match.end() for match in _SENTENCE_END.finditer(text)] + [len(text)]:
        piece = text[begin:end]
        stripped = piece.strip()
        if stripped:
            at = begin + len(piece) - len(piece.lstrip())
            found.append((at, at + len(stripped), stripped))
        begin = end
    return found


def _claim(sentence: str) -> tuple[str, ...]:
    """Why a sentence asserts something checkable, as tags; empty when it does not. Questions
    assert nothing, and link targets, bare URLs and code are not what a sentence asserts."""
    if len(sentence) > MAX_SENTENCE or sentence.rstrip("\"')]*_ ").endswith("?"):
        return ()
    plain = _CODE_SPAN.sub(" ", _URL.sub(" ", _LINK_TARGET.sub("]", sentence)))
    reasons = []
    if _DATE.search(plain):
        reasons.append("date")
    if _DIGIT.search(_DATE.sub(" ", plain)):
        reasons.append("number")
    for word in ("always", "never"):
        if re.search(rf"\b{word}\b", plain, re.IGNORECASE):
            reasons.append(word)
    if _COMPARISON.search(plain):
        reasons.append("comparison")
    return tuple(reasons)


# --- reading a document ----------------------------------------------------------------------


@dataclass
class _Section:
    slot: int | None
    title: str
    start: int | None = None     # the heading's lines; None for the text before any heading
    end: int | None = None
    body: list[_Line] = field(default_factory=list)


class _Reader:
    """One document's logical lines, read top to bottom into Units in the order they begin.
    A section's Unit holds its place from its heading and is written when the section ends."""

    def __init__(self, artifact_id: str, path: str, lines: list[_Line], flavour: str,
                 budget: int) -> None:
        self.artifact_id = artifact_id
        self.path = path
        self.lines = lines
        self.flavour = flavour
        self.budget = budget
        self.cut = False
        self.units: list[Unit | None] = []
        self.headings: list[tuple[int, str]] = []
        self.styles: list[tuple[str, bool]] = []   # reStructuredText title styles, as met
        self.paragraph: list[_Line] = []
        self.in_list = False
        self.literal = False                        # a reStructuredText '::' awaits its block
        self.section = _Section(self._slot(), path)

    @property
    def where(self) -> str:
        return " > ".join(text for _, text in self.headings) or self.path

    def run(self) -> list[Unit]:
        i = self._front_matter()
        while i < len(self.lines):
            following, heading = self._step(i)
            if not heading:
                self.section.body.extend(self.lines[i:following])
            i = following
        self._flush()
        self._close()
        return [unit for unit in self.units if unit is not None]

    # the Units

    def _slot(self) -> int | None:
        if len(self.units) >= self.budget:
            self.cut = True
            return None
        self.units.append(None)
        return len(self.units) - 1

    def _add(self, kind: str, body: str, start: int, end: int, tags: tuple[str, ...] = (),
             title: str | None = None) -> None:
        slot = self._slot()
        if slot is not None:
            self.units[slot] = _unit(
                self.artifact_id, kind, title or self.where, body, Location(self.path, start, end), tags
            )

    def _heading(self, level: int, text: str, start: int, end: int) -> None:
        self._flush()
        self._close()
        while self.headings and self.headings[-1][0] >= level:
            self.headings.pop()
        self.headings.append((level, " ".join(text.split()) or "(untitled)"))
        self.in_list = self.literal = False
        self.section = _Section(self._slot(), self.where, start, end)

    def _close(self) -> None:
        section = self.section
        body = section.body
        first, last = 0, len(body)
        while first < last and not body[first][2].strip():
            first += 1
        while last > first and not body[last - 1][2].strip():
            last -= 1
        kept = body[first:last]
        if section.slot is None or (section.start is None and not kept):
            return
        start = section.start if section.start is not None else kept[0][0]
        end = max([section.end or start, *(line[1] for line in kept)])
        self.units[section.slot] = _unit(
            self.artifact_id, "knowledge", section.title, "\n".join(line[2] for line in kept),
            Location(self.path, start, end),
        )

    def _flush(self) -> None:
        """The paragraph read so far, split into sentences; the checkable ones become claims."""
        lines, self.paragraph = self.paragraph, []
        if not lines:
            return
        texts = [_QUOTE.sub("", text, count=1).strip() for _, _, text in lines]
        starts = []
        offset = 0
        for text in texts:
            starts.append(offset)
            offset += len(text) + 1
        for begin, finish, sentence in _sentences(" ".join(texts)):
            reasons = _claim(sentence)
            if reasons:
                first = bisect_right(starts, begin) - 1
                last = bisect_right(starts, finish - 1) - 1
                self._add("claim", sentence, lines[first][0], lines[last][1], reasons)

    # the lines

    def _front_matter(self) -> int:
        if self.flavour != "markdown" or not self.lines or self.lines[0][2].strip() != "---":
            return 0
        for j in range(1, min(len(self.lines), 200)):
            if self.lines[j][2].strip() in ("---", "..."):
                self.section.body.extend(self.lines[: j + 1])
                return j + 1
        return 0

    def _step(self, i: int) -> tuple[int, bool]:
        """Reads the construct that begins at line i: the index after it, and whether it was
        a heading."""
        start, end, text = self.lines[i]
        if self.flavour == "rst":
            found = self._rst(i)
            if found is not None:
                return found
        else:
            fence = _FENCE_OPEN.fullmatch(text)
            if fence and not (fence.group(1)[0] == "`" and "`" in fence.group(2)):
                return self._fence(i, fence), False
        if self.flavour in ("markdown", "html"):
            atx = _atx(text)
            if atx:
                self._heading(atx[0], atx[1], start, end)
                return i + 1, True
        if self.flavour == "markdown" and self._setext(i):
            below = self.lines[i + 1]
            self._heading(1 if below[2].strip()[0] == "=" else 2, text, start, below[1])
            return i + 2, True
        if not text.strip():
            self._flush()
            return i + 1, False
        if (_BREAK.fullmatch(text) or text.lstrip().startswith("|")
                or (self.flavour == "rst" and _ADORN.fullmatch(text))):
            self._flush()
            return i + 1, False
        bullet = _BULLET.fullmatch(text)
        if bullet:
            return self._item(i, bullet.group(1)), False
        if (self.flavour == "markdown" and not self.paragraph and not self.in_list
                and text.startswith(("    ", "\t"))):
            return self._indented(i), False
        ordered = _ORDERED.match(text)
        if ordered:
            self._flush()
            self.in_list = True
            self.paragraph.append((start, end, text[ordered.end():]))
            return i + 1, False
        if not text[:1].isspace():
            self.in_list = False
        self.paragraph.append((start, end, text))
        if self.flavour == "rst" and text.rstrip().endswith("::"):
            self.literal = True
        return i + 1, False

    def _setext(self, i: int) -> bool:
        text = self.lines[i][2]
        return (
            i + 1 < len(self.lines) and not self.paragraph and bool(text.strip())
            and not text.startswith(("    ", "\t")) and not text.lstrip().startswith(("|", ">"))
            and _SETEXT.fullmatch(self.lines[i + 1][2]) is not None
            and not _BULLET.fullmatch(text) and not _ORDERED.match(text)
            and not _BREAK.fullmatch(text)
        )

    def _continues(self, text: str) -> bool:
        """Whether a line carries on the bullet item above it."""
        if (not text.strip() or _BULLET.fullmatch(text) or _ORDERED.match(text)
                or _BREAK.fullmatch(text) or _SETEXT.fullmatch(text)):
            return False
        if self.flavour == "rst":
            return not _ADORN.fullmatch(text) and not text.lstrip().startswith("..")
        return not _FENCE_OPEN.fullmatch(text) and not _atx(text)

    def _item(self, i: int, content: str) -> int:
        """A bullet item: a check when it has a box, a rule when it tells the reader what to do,
        otherwise a paragraph of its own."""
        start, end, _ = self.lines[i]
        item = [(start, end, content)]
        j = i + 1
        while j < len(self.lines) and self._continues(self.lines[j][2]):
            item.append(self.lines[j])
            j += 1
        self._flush()
        self.in_list = True
        texts = [line[2].strip() for line in item]
        end = item[-1][1]
        box = _CHECKBOX.fullmatch(texts[0])
        if box:
            texts[0] = box.group(2) or ""
            tags = ("done",) if box.group(1) in "xX" else ("open",)
            self._add("check", "\n".join(texts).strip(), start, end, tags)
        elif _imperative(" ".join(texts)):
            self._add("rule", "\n".join(texts), start, end)
        else:
            self.paragraph = [(s, e, text) for (s, e, _), text in zip(item, texts, strict=True)]
            self._flush()
        return j

    def _fence(self, i: int, opening: re.Match[str]) -> int:
        marker = opening.group(1)
        words = opening.group(2).split()
        language = _language(words[0]) if words else ""
        j = i + 1
        while j < len(self.lines):
            closing = _FENCE_CLOSE.fullmatch(self.lines[j][2])
            if closing and closing.group(1)[0] == marker[0] and len(closing.group(1)) >= len(marker):
                break
            j += 1
        closed = j < len(self.lines)
        content = self.lines[i + 1 : j]
        start = self.lines[i][0]
        end = self.lines[j][1] if closed else (content[-1][1] if content else self.lines[i][1])
        self._flush()
        self._add("example", "\n".join(line[2] for line in content), start, end,
                  (language,) if language else ())
        if closed:
            return j + 1
        self._add(
            "knowledge",
            f"The code fence opened at line {start} is never closed, so everything after it was "
            "read as code rather than as document structure.",
            start, end, ("unparsed",), title=f"Unparsed: {self.path}",
        )
        return j

    def _indented(self, i: int) -> int:
        """A markdown code block indented by four spaces: an example with no language."""
        last = i
        for j in range(i, len(self.lines)):
            text = self.lines[j][2]
            if text.strip():
                if not text.startswith(("    ", "\t")):
                    break
                last = j
        code = [
            text[4:] if text.startswith("    ") else text[1:] if text.startswith("\t") else ""
            for _, _, text in self.lines[i : last + 1]
        ]
        self._flush()
        self._add("example", "\n".join(code), self.lines[i][0], self.lines[last][1])
        return last + 1

    # reStructuredText

    def _rst(self, i: int) -> tuple[int, bool] | None:
        lines = self.lines
        start, _, text = lines[i]
        if not text.strip():
            return None
        indent = len(text) - len(text.lstrip())
        if self.literal:
            self.literal = False
            if indent:
                return self._block(i, i, 0, ""), False
        code = _RST_CODE.fullmatch(text.strip())
        if code:
            return self._block(i, i + 1, indent, _language(code.group(1))), False
        if text.strip() == "::":
            self._flush()
            self.literal = True
            return i + 1, False
        if text.lstrip().startswith(".."):
            self._flush()
            return i + 1, False
        below = lines[i + 1][2] if i + 1 < len(lines) else ""
        after = lines[i + 2][2] if i + 2 < len(lines) else ""
        if (_ADORN.fullmatch(text) and below.strip() and not _ADORN.fullmatch(below)
                and _ADORN.fullmatch(after) and after.strip()[0] == text.strip()[0]):
            self._heading(self._level(text.strip()[0], True), below, start, lines[i + 2][1])
            return i + 3, True
        if (not indent and not self.paragraph and _ADORN.fullmatch(below)
                and not _ADORN.fullmatch(text) and not _BULLET.fullmatch(text)
                and len(below.strip()) >= min(len(text.strip()), 3)):
            self._heading(self._level(below.strip()[0], False), text, start, lines[i + 1][1])
            return i + 2, True
        return None

    def _level(self, char: str, overlined: bool) -> int:
        style = (char, overlined)
        if style not in self.styles:
            self.styles.append(style)
        return self.styles.index(style) + 1

    def _block(self, i: int, first: int, indent: int, language: str) -> int:
        """A reStructuredText code directive at line i, or a literal block, whose code is the
        lines from first on that are indented further than indent."""
        lines = self.lines
        last = i
        for j in range(first, len(lines)):
            text = lines[j][2]
            if text.strip():
                if len(text) - len(text.lstrip()) <= indent:
                    break
                last = j
        body = [line[2] for line in lines[first : last + 1]]
        skip = 0
        if first != i:
            while skip < len(body) and (not body[skip].strip() or _OPTION.fullmatch(body[skip].strip())):
                skip += 1
        body = body[skip:]
        margin = min((len(text) - len(text.lstrip()) for text in body if text.strip()), default=0)
        self._flush()
        self._add("example", "\n".join(text[margin:] for text in body), lines[i][0],
                  lines[last][1], (language,) if language else ())
        return last + 1


# --- HTML ------------------------------------------------------------------------------------


def _html_language(classes: str | None) -> str:
    for name in (classes or "").split():
        if name.lower().startswith(("language-", "lang-")):
            return _language(name)
    return ""


def _html_lines(text: str) -> list[_Line]:
    parser = _HTMLText()
    parser.feed(text)
    parser.close()
    return parser.finish()


class _HTMLText(HTMLParser):
    """HTML read as text: tags stripped, scripts and styles dropped unread, links kept as
    [text](href), and the page's headings, lists, checkboxes and preformatted code written as
    the markdown the reader understands — each line carrying the source lines it came from."""

    _DROPPED = frozenset(("script", "style"))
    _HEADINGS = {f"h{level}": level for level in range(1, 7)}
    _LISTS = frozenset(("ul", "ol", "menu"))
    _BLOCKS = frozenset((
        "address", "article", "aside", "blockquote", "body", "br", "caption", "dd", "details",
        "dialog", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "head",
        "header", "hr", "html", "main", "nav", "p", "section", "summary", "table", "tbody",
        "tfoot", "thead", "title", "tr",
    ))

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[_Line] = []
        self._words: list[str] = []
        self._generation = 0
        self._first = 0
        self._last = 0
        self._prefix = ""
        self._dropped = 0
        self._lists: list[str] = []
        self._links: list[tuple[str, int, int]] = []
        self._pre: list[str] | None = None
        self._pre_line = 0
        self._pre_language = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._DROPPED:
            self._dropped += 1
            return
        if self._dropped:
            return
        attributes = dict(attrs)
        if self._pre is not None:
            if tag == "code" and not self._pre_language:
                self._pre_language = _html_language(attributes.get("class"))
            elif tag == "br":
                self._pre.append("\n")
            return
        if tag == "pre":
            self._flush()
            self._pre = []
            self._pre_line = self.getpos()[0]
            self._pre_language = _html_language(attributes.get("class"))
        elif tag in self._HEADINGS:
            self._flush()
            self._prefix = "#" * self._HEADINGS[tag] + " "
        elif tag in self._LISTS:
            self._flush()
            self._lists.append(tag)
        elif tag == "li":
            self._flush()
            self._prefix = "1. " if self._lists and self._lists[-1] == "ol" else "- "
        elif tag == "input":
            if ((attributes.get("type") or "").lower() == "checkbox" and self._prefix == "- "
                    and not "".join(self._words).strip()):
                self._prefix = "- [x] " if "checked" in attributes else "- [ ] "
        elif tag == "a":
            self._links.append((attributes.get("href") or "", self._generation, len(self._words)))
        elif tag in ("td", "th"):
            self._words.append(" ")
        elif tag in self._BLOCKS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in self._DROPPED:
            self._dropped = max(0, self._dropped - 1)
            return
        if self._dropped:
            return
        if self._pre is not None:
            if tag == "pre":
                self._end_pre()
            return
        if tag == "a":
            self._end_link()
        elif tag in self._HEADINGS or tag == "li":
            self._flush()
            self._prefix = ""
        elif tag in self._LISTS:
            self._flush()
            if self._lists:
                self._lists.pop()
        elif tag in self._BLOCKS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._dropped:
            return
        if self._pre is not None:
            self._pre.append(data)
            return
        if not data.strip():
            if self._words:
                self._words.append(" ")
            return
        line = self.getpos()[0]
        if not self._first:
            self._first = line + data.count("\n", 0, len(data) - len(data.lstrip()))
        self._last = max(self._last, line + data.rstrip().count("\n"))
        self._words.append(data)

    def finish(self) -> list[_Line]:
        if self._pre is not None:
            self._end_pre()
        self._flush()
        return self.lines

    def _end_link(self) -> None:
        if not self._links:
            return
        href, generation, at = self._links.pop()
        if generation != self._generation or not href.strip():
            return
        inner = "".join(self._words[at:])
        text = " ".join(inner.split())
        if text:
            lead = " " if inner[:1].isspace() else ""
            tail = " " if inner[-1:].isspace() else ""
            self._words[at:] = [f"{lead}[{text}]({href.strip()}){tail}"]

    def _flush(self) -> None:
        text = " ".join("".join(self._words).split())
        self._words = []
        self._generation += 1
        if text:
            first = self._first or self.getpos()[0]
            last = max(self._last, first)
            self.lines.append((first, last, self._prefix + text))
            self.lines.append((last, last, ""))
            self._prefix = ""
        self._first = self._last = 0

    def _end_pre(self) -> None:
        end = max(self.getpos()[0], self._pre_line)
        code = "".join(self._pre or [])
        self._pre = None
        first = self._pre_line + (1 if code.startswith("\n") else 0)
        code = code.removeprefix("\n").rstrip()
        run = max((len(ticks) for ticks in re.findall(r"`+", code)), default=0)
        fence = "`" * max(3, run + 1)
        self.lines.append((self._pre_line, self._pre_line, fence + self._pre_language))
        for offset, text in enumerate(code.split("\n") if code else []):
            number = min(first + offset, end)
            self.lines.append((number, number, text))
        self.lines.append((end, end, fence))
        self.lines.append((end, end, ""))
