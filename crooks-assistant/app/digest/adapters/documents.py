"""The documents adapter: markdown, reStructuredText, plain text and HTML, read into Units.

Each section under a heading becomes a knowledge Unit titled with its heading path; bullet
items that tell the reader what to do become rules, checklist items become checks, fenced code
becomes examples tagged with their language, and sentences that assert something checkable — a
number, a date, 'always' or 'never', a comparison — become claims, because what a source
asserts must be verified before it is trusted. Links stay in the body where they appear.

Digesting is reading: files are opened read-only without following links and are never run,
imported or installed; HTML is parsed as text by the standard library, its scripts and styles
dropped unread. The walk, each file, the bytes read in all, the text an HTML page may give and
the output are bounded, and no pattern backtracks without bound; the order is fixed (names in
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
MAX_TOTAL_BYTES = 32_000_000 # bytes read from one artifact; documents past it are not read
MAX_DOCUMENTS = 1_000        # documents read from one artifact
MAX_ENTRIES = 20_000         # files and folders looked at, in all and in any one folder
MAX_DEPTH = 32               # folders nested deeper than this are not entered
MAX_UNITS = 10_000           # Units returned, besides the one saying the rest were cut
MAX_SENTENCE = 2_000         # a longer run without a full stop is not read as one claim
_MAX_PROBLEMS = 20           # malformed places named in one HTML page's report; the rest counted
_MAX_OPEN = 256              # HTML elements open at once; markup nested deeper is not checked
# Characters of text an HTML page may give for each character of it (and a few thousand more):
# a link left open across many blocks repeats its target in each, and without a bound a small
# page could be made to give gigabytes.
_HTML_TEXT_FACTOR = 2
_HTML_TEXT_SLACK = 10_000

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

# A sentence's end: a run of stops, closing marks after it, then space. It begins only where a
# run of stops begins and gives nothing back, so a long run with no space after it is passed
# over in one step rather than tried again from each of its characters.
_SENTENCE_END = re.compile(r"(?<![.!?])[.!?]++[\"')\]*_]*+(?=\s)")
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
# An ASCII comparison spaced as prose spaces it ('Primary > secondary', 'Minimum <= maximum'),
# read once tags, autolinks and comments are taken out; arrows ('->', '=>') and quote markers
# are not spaced so, and are not read as one.
_OPERATOR = re.compile(r"(?<=\s)[<>]=?(?=\s)")
_TAG = re.compile(r"<[A-Za-z/!?][^<>]*>")

_MODAL = re.compile(
    r"\b(?:must|mustn't|should|shouldn't|shall|needs? to|has to|have to)\b", re.IGNORECASE
)
_LABEL = re.compile(r"\W*[A-Za-z'-]+\W*:")
_WORDS = re.compile(r"[A-Za-z][A-Za-z']*")
# Verbs that open a command. The list is a help, not a limit: a word outside it still opens one
# when it is not shaped like a noun, adjective or participle and an object follows it, bare or
# not ('Rotate keys', 'Escalate incident'; see _imperative).
_VERBS = frozenset("""
    accept activate add adjust allow always apply archive ask assign attach audit automate avoid
    back backup benchmark bring build bump call cancel capture change check choose clean clear
    clone close collect combine comment commit compare compile comply compress configure confirm
    connect consider contact convert copy create decide decrypt define delete deploy describe
    detect disable do document don't download drop edit embed enable encrypt enforce ensure
    enter escape estimate evaluate examine execute explain export extract fetch fill find fix
    flag follow format generate get give go grant guard handle hide identify ignore implement
    import include inform inspect install isolate keep launch leave let limit lock log make
    mark measure merge migrate minimise minimize mirror monitor mount move never note notify
    only open organise organize pass patch pause pick pin ping please prefer prepare preserve
    prevent print prioritise prioritize protect provide publish pull purge push put query quote
    raise read rebuild record recover reduce refactor refresh refuse register reject release
    reload rely remember remove rename renew repair repeat replace reply report request require
    rerun reset resize resolve restart restore restrict resume retain retry return reuse revert
    review revoke run sanitise sanitize save scan schedule search secure see select send set
    share show sign simplify skip snapshot sort split start stop store submit summarise summarize
    supply switch sync tag take tell test throttle track transfer translate treat trim try turn
    uninstall unlock update upgrade upload use validate verify wait watch wipe wrap write
""".split())
# Words after which no command follows: 'Test is flaky' states, 'Test the backup' commands.
_NOT_AFTER_VERB = frozenset(
    "is are was were has have had can could will would does did may might".split()
)
# Words that do not open a command: articles, pronouns, quantifiers, prepositions, conjunctions.
_NOT_COMMANDS = frozenset("""
    a an the this that these those it its there here i we you he she they me us them my our your
    his her their some any all each every no none one many most few several both either neither
    everything everyone anything anyone nothing nobody something someone when if while because
    although though since unless until as by for from in of on to with without and or but not
    what which who whose why how where
""".split())
# Words that open the object of a command: 'Rotate the keys', 'Defragment every disk'.
_OBJECTS = frozenset("""
    a an the this that these those it its all any each every your our their my them everything
    anything both either
""".split())
# Particles that go with a verb before its object: 'Shut down idle servers'.
_PARTICLES = frozenset("up down out off away over".split())
# Verbs that follow a bare subject in a statement: 'Data lives in memory', 'Config goes in etc'.
_FINITE = frozenset("""
    applies belongs comes depends exists goes happens holds lasts lies lives looks means remains
    resides runs seems sits stays works
""".split())
# Endings of nouns and adjectives, so a word with one names a thing rather than a command:
# 'Configuration files', 'Critical alerts', 'Traffic spikes at noon'.
_DESCRIBING = (
    "tion", "sion", "ment", "ness", "ity", "ship", "hood", "ism", "ogy", "al", "ic", "ous", "ful",
    "less", "able", "ible", "tive", "sive", "ary", "ory",
)
# Endings that make a verb, so a word with one commands even a bare singular object: 'Rotate
# key', 'Escalate incident', 'Normalise path'. The words sharing an ending that name or describe
# a thing are listed apart: 'Private key', 'Certificate chain', 'State machine'.
_ACTING = ("ate", "ise", "ize", "ify", "yse", "yze")
_NOT_ACTING = frozenset("""
    accurate adequate appropriate candidate certificate climate concise corporate debate delicate
    desperate enterprise estate exercise expertise franchise immediate intermediate legitimate
    merchandise otherwise plate precise premise private promise senate separate state surprise
    template ultimate
""".split())
# Verbs that take a clause, so a verb soon after them still reads as a command: 'Ensure backups
# are encrypted'. After any other first word it reads as a statement: 'Release notes are here'.
_CLAUSAL = frozenset("assume check confirm ensure expect make note remember see verify".split())

_CUT = "\n[… cut: longer than a Unit body allows]"


def decompose(root: Path, artifact_id: str) -> list[Unit]:
    """Every document under root (or root itself, when it is one) read into Units, in a fixed
    order. The artifact id is the caller's, not the input's: one that is not an artifact id is
    refused at once, since no Unit could carry it."""
    if not isinstance(artifact_id, str) or not re.fullmatch(ARTIFACT_ID_PATTERN, artifact_id):
        raise ValueError(f"artifact_id does not match {ARTIFACT_ID_PATTERN}: {artifact_id!r}")
    units: list[Unit] = []
    cut = False
    spent = 0
    try:
        for found in _walk(Path(root)):
            if len(units) >= MAX_UNITS:
                cut = True
                break
            if isinstance(found, _Skipped):
                units.append(_unparsed(artifact_id, found.path, found.reason))
                continue
            read, stopped, size = _read(artifact_id, found, MAX_UNITS - len(units),
                                        MAX_TOTAL_BYTES - spent)
            units.extend(read)
            spent += size
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
    """A document that was not read, and why; and how many of its bytes were read to find out."""

    def __init__(self, reason: str, size: int = 0) -> None:
        super().__init__(reason)
        self.size = size


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
        info = root.lstat()
    except OSError as exc:
        yield _Skipped(".", f"the artifact could not be read: {_why(exc)}")
        return
    if stat.S_ISLNK(info.st_mode):
        yield _Skipped(".", "the artifact is a symbolic link, not followed")
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


def _load(file: Path, allowance: int) -> tuple[str, int]:
    """The document's text, and how many bytes were read for it: never more than the file bound,
    nor than the allowance left of the artifact's reading budget."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    spent = f"the {MAX_TOTAL_BYTES}-byte reading budget for the artifact was spent; not read"
    try:
        descriptor = os.open(file, flags)
        with open(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise _Unreadable("not a regular file; not read")
            if info.st_size > MAX_FILE_BYTES:
                raise _Unreadable(f"larger than {MAX_FILE_BYTES} bytes; not read")
            if info.st_size > allowance:
                raise _Unreadable(spent)
            data = handle.read(max(0, min(MAX_FILE_BYTES, allowance)) + 1)
    except OSError as exc:
        raise _Unreadable(f"could not be read: {_why(exc)}") from None
    size = len(data)
    if size > MAX_FILE_BYTES:
        raise _Unreadable(f"larger than {MAX_FILE_BYTES} bytes; not read", size)
    if size > allowance:
        raise _Unreadable(spent, size)
    if b"\x00" in data:
        raise _Unreadable("holds NUL bytes, so it is binary rather than a text document; not read", size)
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise _Unreadable(f"not UTF-8 text: byte {exc.start} cannot be decoded; not read", size) from None
    return text.replace("\r\n", "\n").replace("\r", "\n"), size


def _read(artifact_id: str, document: _Document, budget: int,
          allowance: int) -> tuple[list[Unit], bool, int]:
    """One document's Units, whether the Unit budget cut them short, and the bytes read."""
    size = 0
    try:
        text, size = _load(document.file, allowance)
        problems: list[tuple[int, str]] = []
        prose: frozenset[int] = frozenset()
        if document.flavour == "html":
            lines, problems, prose = _html_lines(text)
        else:
            lines = [(number, number, line) for number, line in enumerate(text.split("\n"), 1)]
            if lines and not lines[-1][2]:
                lines.pop()
        reader = _Reader(artifact_id, document.path, lines, document.flavour,
                         budget - 1 if problems else budget, prose)
        units = reader.run()
        if problems:
            reason = (
                "The HTML is malformed in ways its parser lets pass, so part of it may be missing "
                "or misread: " + "; ".join(note for _, note in problems) + "."
            )
            units.append(_unparsed(artifact_id, document.path, reason, problems[0][0],
                                   max(line for line, _ in problems)))
        return units, reader.cut, size
    except _Unreadable as exc:
        return [_unparsed(artifact_id, document.path, str(exc))], False, exc.size
    except Exception as exc:  # noqa: BLE001 — a parser fault is reported as unparsed, never raised
        reason = f"could not be parsed: {type(exc).__name__}: {exc}"
        return [_unparsed(artifact_id, document.path, reason)], False, size


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


def _plural(word: str) -> bool:
    return word.endswith("s") and not word.endswith(("ss", "us", "is"))


def _imperative(text: str) -> bool:
    """Whether a bullet item tells the reader what to do: it opens with a verb in the imperative,
    or says what must or should be done. A 'Label: value' item does not, nor one that opens
    with a noun and its verb ('Backups run nightly', 'Release notes are in the wiki'). A word
    not known as a verb opens a command when its object follows: one led by a determiner or a
    particle, a bare plural ('Rotate keys'), a bare singular after a word with a verb's ending
    ('Rotate key'), or any when the item is a sentence ('Quarantine unknown files.'); a bare
    noun phrase ('Offline support', 'Private key') is not a command."""
    head = text[:300].replace("’", "'")
    if _LABEL.match(head):
        return False
    if _MODAL.search(head):
        return True
    words = [word.lower() for word in _WORDS.findall(head)[:3]]
    if not words or words[0] in _NOT_COMMANDS:
        return False
    if len(words) > 1 and words[1] in _NOT_AFTER_VERB:
        return False
    if (len(words) > 2 and words[1] not in _OBJECTS and words[2] in _NOT_AFTER_VERB
            and words[0] not in _CLAUSAL):
        return False
    first = words[0]
    if first in _VERBS:
        return True
    if (first.endswith(("ing", "ly")) or (first.endswith("ed") and not first.endswith("eed"))
            or _plural(first)):
        return False   # a gerund, participle, adverb or plural: not a command
    if len(words) < 2 or words[1] in _FINITE:
        return False   # a lone word, or a subject and its verb
    if words[1] in _OBJECTS or words[1] in _PARTICLES:
        return True
    if len(first) > 4 and first.endswith(_DESCRIBING) and not first.endswith("eal"):
        return False   # a noun or adjective before a noun
    if _plural(words[1]):
        return len(words) < 3 or words[2] not in _OBJECTS   # 'Cache stores the index' states
    if len(first) > 4 and first.endswith(_ACTING) and first not in _NOT_ACTING:
        return True    # a verb by its shape before a bare object: 'Rotate key'
    return text.rstrip().endswith((".", "!"))


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
    unmarked = _CODE_SPAN.sub(" ", _URL.sub(" ", _TAG.sub(" ", _LINK_TARGET.sub("]", sentence))))
    if _COMPARISON.search(plain) or _OPERATOR.search(unmarked):
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
    A section's Unit holds its place from its heading and is written when the section ends.
    Prose lines — an HTML page's own text, as against the structure its tags were written
    as — are read as prose however they begin: a paragraph that opens with '#' or '```' is not a heading
    or a fence."""

    def __init__(self, artifact_id: str, path: str, lines: list[_Line], flavour: str,
                 budget: int, prose: frozenset[int] = frozenset()) -> None:
        self.artifact_id = artifact_id
        self.path = path
        self.lines = lines
        self.flavour = flavour
        self.prose = prose
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
        if i in self.prose:
            self.in_list = False
            self.paragraph.append((start, end, text))
            return i + 1, False
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


def _html_lines(text: str) -> tuple[list[_Line], list[tuple[int, str]], frozenset[int]]:
    """The page's lines, what was malformed in it — the line and a plain account of each — and
    which lines are the page's own text rather than structure written as markdown. The text is
    bounded by the page's length (see _HTML_TEXT_FACTOR)."""
    parser = _HTMLText(_HTML_TEXT_FACTOR * len(text) + _HTML_TEXT_SLACK)
    parser.feed(text)
    parser.close()
    return parser.finish(), parser.problems, frozenset(parser.prose)


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
    _VOID = frozenset((
        "area", "base", "br", "col", "embed", "hr", "img", "input", "keygen", "link", "meta",
        "param", "source", "track", "wbr",
    ))
    # Elements whose end tag HTML lets be left out, and the start tags that end them when it is.
    _CELL_ENDS = frozenset(("td", "th", "tr", "tbody", "thead", "tfoot"))
    _RUBY_ENDS = frozenset(("rb", "rp", "rt", "rtc"))
    _ENDED_BY = {
        "p": frozenset((
            "address", "article", "aside", "blockquote", "dd", "details", "dialog", "div", "dl",
            "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
            "h5", "h6", "header", "hgroup", "hr", "li", "main", "menu", "nav", "ol", "p", "pre",
            "search", "section", "table", "ul",
        )),
        "li": frozenset(("li",)),
        "dt": frozenset(("dd", "dt")),
        "dd": frozenset(("dd", "dt")),
        "option": frozenset(("optgroup", "option")),
        "optgroup": frozenset(("optgroup",)),
        "rb": _RUBY_ENDS, "rp": _RUBY_ENDS, "rt": _RUBY_ENDS, "rtc": frozenset(("rb", "rtc")),
        "colgroup": frozenset(("colgroup", "tbody", "tfoot", "thead", "tr")),
        "td": _CELL_ENDS, "th": _CELL_ENDS,
        "tr": frozenset(("tbody", "tfoot", "thead", "tr")),
        "thead": frozenset(("tbody", "tfoot")),
        "tbody": frozenset(("tbody", "tfoot")),
        "tfoot": frozenset(("tbody",)),
        "head": frozenset(("body",)),
        "body": frozenset(),
        "html": frozenset(),
    }
    # Elements whose start tag HTML lets be left out, so their end tag alone closes nothing amiss
    # where the element is implied (see _implied).
    _START_OPTIONAL = frozenset(("body", "colgroup", "head", "html", "tbody"))
    # Elements that may stand before the body begins.
    _HEAD_CONTENT = frozenset((
        "base", "head", "html", "link", "meta", "noscript", "script", "style", "template", "title",
    ))

    def __init__(self, budget: int) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[_Line] = []
        self.prose: set[int] = set()                # the lines that are the page's own text
        self._budget = budget                       # characters of text the page may give
        self._size = 0
        self._full = False                          # the budget is spent: nothing more is read
        self._words: list[str] = []
        self._first = 0
        self._last = 0
        self._prefix = ""
        self._dropped = 0
        self._dropped_at = ("", 0)                  # the script or style being dropped, and its line
        self._open: list[tuple[str, int]] = []      # the elements open, and the line of each
        self._too_deep = False                      # nesting passed _MAX_OPEN: no longer tracked
        self._body = False                          # whether the body's content has begun
        self._ended: set[str] = set()               # the start-optional elements closed
        self._links: list[tuple[str, int]] = []     # each open link's target, and its first word
        self._pre: list[str] | None = None
        self._pre_line = 0
        self._pre_language = ""
        self.problems: list[tuple[int, str]] = []   # malformed markup the parser let pass
        self._unreported = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._DROPPED:
            if not self._dropped:
                self._dropped_at = (tag, self.getpos()[0])
            self._dropped += 1
            return
        if self._dropped:
            return
        attributes = dict(attrs)
        if tag not in self._HEAD_CONTENT:
            self._body = True
        if self._pre is not None:
            if tag == "code" and not self._pre_language:
                self._pre_language = _html_language(attributes.get("class"))
            elif tag == "br":
                self._pre.append("\n")
            return
        tracked = self._begin_element(tag)
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
        elif tag == "li":
            self._flush()
            self._prefix = "1. " if self._list() == "ol" else "- "
        elif tag == "input":
            if ((attributes.get("type") or "").lower() == "checkbox" and self._prefix == "- "
                    and not "".join(self._words).strip()):
                self._prefix = "- [x] " if "checked" in attributes else "- [ ] "
        elif tag == "a":
            if tracked:
                self._links.append((attributes.get("href") or "", len(self._words)))
        elif tag in ("td", "th"):
            self._words.append(" ")
        elif tag in self._BLOCKS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in self._DROPPED:
            if self._dropped:
                self._dropped -= 1
            else:
                self._stray(tag)
            return
        if self._dropped:
            return
        if self._pre is not None:
            if tag == "pre":
                self._end_pre()
            return
        if tag == "pre":
            self._stray(tag)
        elif tag not in self._VOID:
            self._end_element(tag)
        if tag in self._HEADINGS or tag == "li":
            self._flush()
            self._prefix = ""
        elif tag in self._LISTS or tag in self._BLOCKS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._dropped or self._full:
            return
        if self._pre is not None:
            self._pre.append(data)
            return
        if not data.strip():
            if self._words:
                self._words.append(" ")
            return
        if not self._open or self._open[-1][0] != "title":
            self._body = True
        line = self.getpos()[0]
        if not self._first:
            self._first = line + data.count("\n", 0, len(data) - len(data.lstrip()))
        self._last = max(self._last, line + data.rstrip().count("\n"))
        self._words.append(data)

    def finish(self) -> list[_Line]:
        """The page's lines, once all of it has been fed and closed. What is still open at the
        end, which the parser lets pass without complaint, is noted in problems."""
        if self._dropped:
            tag, line = self._dropped_at
            self._problem(line, f"<{tag}> opened at line {line} is never closed, so everything "
                                "after it was dropped unread")
        if self._pre is not None:
            self._problem(self._pre_line, f"<pre> opened at line {self._pre_line} is never "
                                          "closed, so everything after it was read as code")
            self._end_pre()
        if not self._too_deep:
            for tag, line in self._open:
                if tag not in self._ENDED_BY:
                    self._problem(line, f"<{tag}> opened at line {line} is never closed")
        if self.rawdata.strip() and not self._dropped:
            line = self.getpos()[0]
            self._problem(line, f"the page ends at line {line} inside markup that is never "
                                "finished, which was not read")
        self._flush()
        self.problems.sort()
        if self._unreported:
            self.problems.append((self.problems[-1][0], f"and {self._unreported} more"))
        return self.lines

    def _problem(self, line: int, note: str) -> None:
        if len(self.problems) < _MAX_PROBLEMS:
            self.problems.append((max(line, 1), note))
        else:
            self._unreported += 1

    def _stray(self, tag: str) -> None:
        line = self.getpos()[0]
        self._problem(line, f"</{tag}> at line {line} closes nothing that is open")

    def _begin_element(self, tag: str) -> bool:
        """Notes tag as open, first ending the open elements whose left-out end tag it implies;
        whether it is now tracked. Void elements and <pre>, read apart, are never tracked."""
        if self._too_deep:
            return False
        while self._open and tag in self._ENDED_BY.get(self._open[-1][0], ()):
            self._open.pop()
        if tag in self._VOID or tag == "pre":
            return False
        line = self.getpos()[0]
        if len(self._open) >= _MAX_OPEN:
            self._too_deep = True
            self._problem(line, f"elements nest more than {_MAX_OPEN} deep at line {line}, so the "
                                "markup from there on was not checked")
            return False
        self._open.append((tag, line))
        return True

    def _end_element(self, tag: str) -> None:
        """Closes the innermost open tag, and the elements still open inside it: those whose end
        tag may be left out silently, the rest as never closed."""
        if self._too_deep:
            return
        if all(name != tag for name, _ in self._open):
            if tag in self._START_OPTIONAL and self._implied(tag):
                self._ended.add(tag)
            else:
                self._stray(tag)
            return
        while self._open:
            name, opened = self._open.pop()
            if name in self._START_OPTIONAL:
                self._ended.add(name)
            if name == "a":
                self._end_link()
            if name == tag:
                return
            if name not in self._ENDED_BY:
                line = self.getpos()[0]
                self._problem(opened, f"<{name}> opened at line {opened} is never closed before "
                                      f"</{tag}> at line {line}")

    def _implied(self, tag: str) -> bool:
        """Whether an end tag whose start tag was left out closes an element HTML implies where
        it stands: a table's body inside a table, its column group right inside one, the head
        before the body has begun, and the body or the page until they have ended."""
        if tag == "tbody":
            return any(name == "table" for name, _ in self._open)
        if tag == "colgroup":
            return bool(self._open) and self._open[-1][0] == "table"
        if tag in self._ended or "html" in self._ended:
            return False
        if tag == "head":
            return not self._body and all(name == "html" for name, _ in self._open)
        return True

    def _list(self) -> str:
        for name, _ in reversed(self._open):
            if name in self._LISTS:
                return name
        return ""

    def _end_link(self) -> None:
        if self._links:
            self._mark_link(*self._links.pop())

    def _mark_link(self, href: str, at: int) -> None:
        """The words from at on written as a link to href."""
        if not href.strip():
            return
        inner = "".join(self._words[at:])
        text = " ".join(inner.split())
        if text:
            lead = " " if inner[:1].isspace() else ""
            tail = " " if inner[-1:].isspace() else ""
            self._words[at:] = [f"{lead}[{text}]({href.strip()}){tail}"]

    def _room(self, size: int) -> bool:
        """Whether size more characters of text fit the page's budget. Once they do not, the
        rest of the page is not read, and that is noted where it happened."""
        if not self._full and self._size + size <= self._budget:
            self._size += size
            return True
        if not self._full:
            self._full = True
            line = self.getpos()[0]
            self._problem(line, f"its text runs past {self._budget} characters at line {line} — "
                                "a link left open across blocks repeats its target in each — so "
                                "the rest was not read")
        return False

    def _flush(self) -> None:
        if self._full:
            self._words = []
            self._prefix = ""
            self._first = self._last = 0
            return
        # A link still open spans blocks: its text in each line it reaches is marked with it.
        for index in range(len(self._links) - 1, -1, -1):
            href, at = self._links[index]
            self._mark_link(href, at)
            self._links[index] = (href, 0)
            if self._words and len(self._words[-1]) > self._budget - self._size:
                break                       # past the budget already: _room below says so
        text = " ".join("".join(self._words).split())
        self._words = []
        if text:
            line = self._prefix + text
            if self._room(len(line) + 2):
                first = self._first or self.getpos()[0]
                last = max(self._last, first)
                if not self._prefix:
                    self.prose.add(len(self.lines))
                self.lines.append((first, last, line))
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
        if not self._room(len(code) + 2 * len(fence) + 4 + len(self._pre_language)):
            return
        self.lines.append((self._pre_line, self._pre_line, fence + self._pre_language))
        for offset, text in enumerate(code.split("\n") if code else []):
            number = min(first + offset, end)
            self.lines.append((number, number, text))
        self.lines.append((end, end, fence))
        self.lines.append((end, end, ""))
