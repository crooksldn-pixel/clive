"""Research George gives CLIVE, turned into text the digester can read.

Why this exists: George's research arrives as whatever ChatGPT or a browser gave him — a PDF, a
Word file, Markdown, plain text, a saved share page, or ChatGPT's own export (conversations.json,
or the zip it comes in). The digester's documents adapter reads Markdown, text and HTML only, and
its scanner reads only what is text. So each file is turned into Markdown here, once, at intake,
and the quarantined copy is that Markdown: what the scanner scans is exactly what the model is
later shown.

What it promises:
- Reading only. Nothing in a file is run: a PDF is parsed by pypdf (the one dependency) in a
  process of its own with a time and memory limit (app/research/pdf_reader.py), a Word file is unzipped and its XML read with the standard library as it
  streams, one paragraph or table at a time (any DOCTYPE or ENTITY refused before parsing), a
  saved page is read for the words it shows (its scripts and styles dropped unread), a ChatGPT
  export is read as JSON.
- Bounded: the file, each part unzipped, the values in a ChatGPT export, the pages read, the text
  made and the conversations taken. Past a bound it says so in words (ConvertError), or notes
  what it left out.
- Every section it makes stays under SECTION_CHARS, so no part of a long file is cut off by the
  adapter's own limit on one section: a page or a long run of paragraphs becomes its own heading.
- What it cannot read it says plainly; it never returns an empty document as if it were one.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import PurePosixPath
from xml.etree import ElementTree
from xml.parsers import expat

MAX_FILE_BYTES = 25 << 20        # one file George gives
MAX_PAGES = 500                  # pages read from one PDF
# One PDF is read in its own process (app/research/pdf_reader.py, review note 3, 8 Oct), killed past
# PDF_SECONDS and held to PDF_MEMORY_BYTES of address space. Measured 8 Oct: 100 ordinary pages read
# in 0.6 s, so 500 take about 3 s; an 8 KB page of 300,000 one-letter runs took 9 s of CPU. The
# reader starts at 45 MB, and pypdf decompresses at most 75 MB of one stream.
PDF_SECONDS = 60
PDF_MEMORY_BYTES = 512 << 20
_PDF_ENV = {"LC_ALL": "C.UTF-8"}  # all the reader's process is given: no keys, no settings
MAX_TEXT_CHARS = 1_500_000       # Markdown made from one file (the adapter reads 2 MB a file)
# A Word file's text (word/document.xml) or a ChatGPT export's JSON, unpacked (review note 2, 8 Oct).
# 8 MB already holds more text than CLIVE takes from one file: Word writes about 5 bytes of XML for
# each character of an ordinary paragraph with its fonts, sizes and revision marks (measured 8 Oct:
# 8 MB of them carried the 1,500,000 characters of MAX_TEXT_CHARS), and an export shaped like
# ChatGPT's, of 25 chats of 60 long messages each, came to 2.8 MB. At this bound the worst Word file (8 MB of empty paragraphs, a 12 KB download) cost 2.8 s
# of CPU and 16 MB, read as it streams; built as a whole tree it took 126 MB (64 MB of it: 1 GB).
MAX_PART_BYTES = 8 << 20
# Values in a ChatGPT export, counted before it is parsed: every value but the first in a list or an
# object follows a comma, and every list or object opens with a bracket, so commas plus brackets bound
# how many objects json.loads can make. An export runs at about 32,000 a megabyte (measured 8 Oct), so
# about 255,000 at MAX_PART_BYTES; 500,000 is twice that. At the bound the worst JSON measured (short
# strings) cost 32 MB and 0.1 s; 8 MB of empty lists, unbounded, cost 217 MB.
MAX_JSON_VALUES = 500_000
MAX_CONVERSATIONS = 25           # conversations taken from one ChatGPT export
SECTION_CHARS = 12_000           # under the adapter's 16,000-character section body

SUFFIXES = {
    ".pdf": "pdf", ".docx": "docx", ".md": "markdown", ".markdown": "markdown", ".txt": "text",
    ".text": "text", ".html": "html", ".htm": "html", ".json": "chatgpt", ".zip": "chatgpt_zip",
}
# What the screen and the docs say George can give, in his words.
ACCEPTED = "PDF, Word (.docx), Markdown, text, a saved web page, or a ChatGPT export (conversations.json or its zip)"

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_SPACE = re.compile(r"[ \t ]+")
_BLANKS = re.compile(r"\n{3,}")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


_ONE_AT_A_TIME = ("Give the research chats one at a time instead: export the report as PDF, Word or Markdown, "
                  "or save the shared chat's page.")


class ConvertError(Exception):
    """A file that could not be read as research, said in words for George."""


@dataclass
class Converted:
    """What a file became: (name, Markdown) files, and notes on anything left out."""

    kind: str
    files: list[tuple[str, str]]
    notes: list[str] = field(default_factory=list)


def kind_of(name: str) -> str:
    """The kind of research a file name says it is, or "" when it is not one CLIVE takes."""
    return SUFFIXES.get(PurePosixPath(str(name or "")).suffix.lower(), "")


def convert(name: str, data: bytes) -> Converted:
    """The file `name` with these bytes, as Markdown: a saved page as the words it shows."""
    kind = kind_of(name)
    if not kind:
        raise ConvertError(f"{_short(name)} isn't a kind of file CLIVE takes as research. It takes {ACCEPTED}.")
    if len(data) > MAX_FILE_BYTES:
        raise ConvertError(f"{_short(name)} is {len(data) >> 20} MB; research files are taken up to {MAX_FILE_BYTES >> 20} MB.")
    if not data.strip():
        raise ConvertError(f"{_short(name)} is empty.")
    stem = _stem(name)
    notes: list[str] = []
    if kind == "pdf":
        text = _sectioned(_pdf(data, notes), "Page")
    elif kind == "docx":
        text = _docx(data, notes)
    elif kind == "text":
        text = _sectioned([_text(data)], "Part")
    elif kind == "markdown":
        text = _text(data)
    elif kind == "html":
        text = _chunked_markdown(_html(_text(data)))
    elif kind == "chatgpt":
        text = _chatgpt(_json(data, name), notes)
    else:
        text = _chatgpt(_json(_from_zip(data), "conversations.json"), notes)
    text = _BLANKS.sub("\n\n", _CONTROL.sub("", text)).strip()
    if not _has_words(text):
        why = ("A page saved before the chat loaded holds the page's code, not the chat: let it load, then save it, "
               "or export the report as PDF, Word or Markdown." if kind == "html" else
               "A scanned PDF has pictures of words, not words: export the research as text, Markdown or Word instead.")
        raise ConvertError(f"No text could be read from {_short(name)}. {why}")
    if len(text) > MAX_TEXT_CHARS:
        notes.append(f"Only the first {MAX_TEXT_CHARS:,} characters were taken; the rest of the file was left out.")
        text = text[:MAX_TEXT_CHARS].rsplit("\n", 1)[0]
    return Converted(kind, [(f"{stem}.md", text + "\n")], notes)


# ------------------------------------------------------------------ each kind


def _pdf(data: bytes, notes: list[str]) -> list[str]:
    said = _pdf_in_its_own_process(data)
    error = said.get("error")
    if error == "missing":
        raise ConvertError("PDF reading isn't installed on this server (the pypdf package). "
                           "Give the research as Word, Markdown or text, or install pypdf.")
    if error == "locked":
        raise ConvertError("That PDF is locked with a password, so CLIVE can't read it.")
    if error == "memory":
        raise ConvertError(f"That PDF needs more than the {PDF_MEMORY_BYTES >> 20} MB CLIVE gives reading one PDF, so it "
                           "wasn't read. Export the research as Word, Markdown or text instead.")
    if error:
        raise ConvertError(f"That PDF couldn't be read ({str(said.get('type') or 'unreadable')[:40]}).")
    out = [p if isinstance(p, str) else "" for p in said.get("pages") or []][:MAX_PAGES]
    total, unread = int(said.get("total") or len(out)), int(said.get("unread") or 0)
    if total > MAX_PAGES:
        notes.append(f"Only the first {MAX_PAGES} of its {total} pages were read.")
    if unread:
        notes.append(f"{unread} page{'s' if unread != 1 else ''} couldn't be read and {'were' if unread != 1 else 'was'} left out.")
    return out


def _pdf_in_its_own_process(data: bytes) -> dict:
    """What app/research/pdf_reader.py said of these bytes, run as its own process with the app's Python."""
    import subprocess
    import sys

    from app.research import pdf_reader

    if not sys.executable:
        raise ConvertError("That PDF couldn't be read: this server has no Python to read it with.")
    command = [sys.executable, "-I", pdf_reader.__file__, str(MAX_PAGES), str(PDF_MEMORY_BYTES), str(PDF_SECONDS + 5)]
    try:
        done = subprocess.run(command, input=data, capture_output=True, timeout=PDF_SECONDS, env=_PDF_ENV, check=False)
    except subprocess.TimeoutExpired:
        raise ConvertError(f"Reading that PDF took more than {PDF_SECONDS} seconds, so CLIVE stopped. "
                           "Export the research as Word, Markdown or text instead.") from None
    except OSError as exc:
        raise ConvertError(f"That PDF couldn't be read: its reader couldn't start ({type(exc).__name__}).") from None
    try:
        said = json.loads(done.stdout.decode("ascii")) if done.returncode == 0 else None
    except (UnicodeDecodeError, ValueError):
        said = None
    if not isinstance(said, dict):
        raise ConvertError("That PDF couldn't be read: reading it stopped before it finished, as one that needs more "
                           "time or memory than CLIVE gives a PDF would.")
    return said


def _docx(data: bytes, notes: list[str]) -> str:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        info = archive.getinfo("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError):
        raise ConvertError("That Word file couldn't be opened: it has no document inside it.") from None
    xml = _bounded_read(archive, info, f"That Word file's text unpacks to more than {MAX_PART_BYTES >> 20} MB, more than "
                                       "CLIVE reads from one file. Split it, or export it as PDF or Markdown.")
    _refuse_declarations(xml)
    return _chunked_markdown(_WordBody().read(xml))


class _WordBody:
    """A Word file's document.xml, read as it streams: each paragraph or table directly in the body is
    built as a small tree, turned into its Markdown line(s) and let go, so memory holds one block at a
    time however many blocks the file has (review note 2, 8 Oct)."""

    def __init__(self) -> None:
        self.lines: list[str] = []
        self.depth = 0
        self.has_body = False
        self.in_body = False
        self.block: ElementTree.TreeBuilder | None = None

    def read(self, xml: bytes) -> list[str]:
        parser = self.parser()
        try:
            parser.Parse(xml, True)
        except expat.ExpatError:
            raise ConvertError("That Word file's text couldn't be read.") from None
        if not self.has_body:
            raise ConvertError("That Word file has no body to read.")
        return self.lines

    def parser(self):
        parser = expat.ParserCreate(namespace_separator="}")
        parser.buffer_text = True
        parser.StartElementHandler = self.start
        parser.EndElementHandler = self.end
        parser.CharacterDataHandler = self.data
        return parser

    def start(self, name: str, attrs: dict[str, str]) -> None:
        self.depth += 1
        tag = _clark(name)
        if self.depth == 2 and tag == f"{_W}body":
            self.has_body = self.in_body = True
        elif self.depth == 3 and self.in_body:
            self.block = ElementTree.TreeBuilder()
        if self.block is not None:
            self.block.start(tag, {_clark(k): v for k, v in attrs.items()})

    def end(self, name: str) -> None:
        if self.block is not None:
            self.block.end(_clark(name))
            if self.depth == 3:
                self.take(self.block.close())
                self.block = None
        elif self.depth == 2:
            self.in_body = False
        self.depth -= 1

    def data(self, text: str) -> None:
        if self.block is not None:
            self.block.data(text)

    def take(self, block) -> None:
        if block.tag == f"{_W}p":
            line = _paragraph(block)
            if line:
                self.lines.append(line)
        elif block.tag == f"{_W}tbl":
            for row in block.iter(f"{_W}tr"):
                cells = [" ".join(_runs(p) for p in cell.iter(f"{_W}p")).strip() for cell in row.iter(f"{_W}tc")]
                if any(cells):
                    self.lines.append("| " + " | ".join(cells) + " |")


def _clark(name: str) -> str:
    """expat's "uri}local" as ElementTree's "{uri}local"."""
    return "{" + name if "}" in name else name


def _paragraph(p) -> str:
    words = _runs(p).strip()
    if not words:
        return ""
    props = p.find(f"{_W}pPr")
    style = ""
    if props is not None:
        named = props.find(f"{_W}pStyle")
        style = (named.get(f"{_W}val") or "") if named is not None else ""
        if props.find(f"{_W}numPr") is not None and not style.lower().startswith("heading"):
            return f"- {words}"
    level = _heading_level(style)
    return f"{'#' * level} {words}" if level else words


def _heading_level(style: str) -> int:
    low = style.lower().replace(" ", "")
    if low == "title":
        return 1
    match = re.fullmatch(r"heading([1-6])", low)
    return int(match.group(1)) + 1 if match and int(match.group(1)) < 6 else (6 if match else 0)


def _runs(node) -> str:
    parts: list[str] = []
    for el in node.iter():
        if el.tag == f"{_W}t" and el.text:
            parts.append(el.text)
        elif el.tag in (f"{_W}tab",):
            parts.append(" ")
        elif el.tag in (f"{_W}br", f"{_W}cr"):
            parts.append(" ")
    return _SPACE.sub(" ", "".join(parts))


class _Page(HTMLParser):
    """A saved page's visible words, as Markdown lines: headings, paragraphs and list items. Scripts,
    styles and everything else a page carries but does not show are dropped unread, so the scanner
    and the model see the page as he read it, never its machinery."""

    SKIP = frozenset(("script", "style", "noscript", "svg", "template", "head", "iframe", "object"))
    BLOCK = frozenset(("p", "div", "section", "article", "br", "tr", "pre", "blockquote", "li", "ul", "ol", "table",
                       "h1", "h2", "h3", "h4", "h5", "h6"))

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.current: list[str] = []
        self.prefix = ""
        self.skipping = 0
        self.size = 0

    def flush(self) -> None:
        words = _SPACE.sub(" ", "".join(self.current)).strip()
        if words and self.size < MAX_TEXT_CHARS:
            self.lines.append(f"{self.prefix}{words}")
            self.size += len(words)
        self.current, self.prefix = [], ""

    def handle_starttag(self, tag, attrs) -> None:
        if tag in self.SKIP:
            self.skipping += 1
        elif not self.skipping and tag in self.BLOCK:
            self.flush()
            if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                self.prefix = "#" * int(tag[1]) + " "
            elif tag == "li":
                self.prefix = "- "

    def handle_endtag(self, tag) -> None:
        if tag in self.SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif not self.skipping and tag in self.BLOCK:
            self.flush()

    def handle_data(self, data) -> None:
        if not self.skipping:
            self.current.append(data)


def _html(text: str) -> list[str]:
    page = _Page()
    try:
        page.feed(text)
        page.close()
    except Exception:  # noqa: BLE001 - malformed markup gives what was read before it
        pass
    page.flush()
    return page.lines


def _chatgpt(data, notes: list[str]) -> str:
    conversations = data if isinstance(data, list) else [data] if isinstance(data, dict) else None
    if not conversations or not all(isinstance(c, dict) for c in conversations):
        raise ConvertError("That JSON isn't a ChatGPT export: it holds no conversations.")
    if len(conversations) > MAX_CONVERSATIONS:
        raise ConvertError(
            f"That ChatGPT export holds {len(conversations)} chats: the whole account, not one piece of research. "
            + _ONE_AT_A_TIME)
    out: list[str] = []
    empty = 0
    for convo in conversations:
        turns = _thread(convo)
        if not turns:
            empty += 1
            continue
        title = _one_line(convo.get("title")) or "A ChatGPT chat"
        out.append(f"# {title}")
        for role, words in turns:
            out.append(f"## {'Asked' if role == 'user' else 'ChatGPT said'}")
            out.append(words)
    if empty:
        notes.append(f"{empty} chat{'s' if empty != 1 else ''} in the export had no text and {'were' if empty != 1 else 'was'} left out.")
    return _chunked_markdown(out)


def _thread(convo: dict) -> list[tuple[str, str]]:
    """The chat's main line, oldest first: from its current message back through each parent.
    Only what George asked and what ChatGPT said; tools, system notes and pictures are left out."""
    mapping = convo.get("mapping")
    if not isinstance(mapping, dict):
        return []
    node_id = convo.get("current_node")
    if not isinstance(node_id, str) or node_id not in mapping:
        node_id = next(iter(mapping), None)
    seen: set[str] = set()
    turns: list[tuple[str, str]] = []
    while isinstance(node_id, str) and node_id in mapping and node_id not in seen and len(seen) < 10_000:
        seen.add(node_id)
        node = mapping[node_id] if isinstance(mapping[node_id], dict) else {}
        message = node.get("message") if isinstance(node.get("message"), dict) else {}
        role = (message.get("author") or {}).get("role") if isinstance(message.get("author"), dict) else None
        content = message.get("content") if isinstance(message.get("content"), dict) else {}
        parts = content.get("parts") if isinstance(content.get("parts"), list) else []
        words = "\n".join(p for p in parts if isinstance(p, str)).strip()
        if role in ("user", "assistant") and words:
            turns.append((role, words))
        node_id = node.get("parent")
    turns.reverse()
    return turns


# ------------------------------------------------------------------ helpers


def _json(data: bytes, name: str):
    """A ChatGPT export's JSON, refused in words before it is parsed when it is bigger, or holds more
    values, than research chats come to (review note 2, 8 Oct)."""
    if len(data) > MAX_PART_BYTES or data.count(b",") + data.count(b"{") + data.count(b"[") > MAX_JSON_VALUES:
        raise ConvertError(f"{_short(name)} holds more than research chats come to, most likely the whole account. "
                           + _ONE_AT_A_TIME)
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ConvertError(f"{_short(name)} isn't readable JSON.") from None


def _from_zip(data: bytes) -> bytes:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        names = [n for n in archive.namelist() if PurePosixPath(n).name == "conversations.json"]
        if not names:
            raise ConvertError("That zip isn't a ChatGPT export: there is no conversations.json in it.")
        return _bounded_read(archive, archive.getinfo(sorted(names, key=len)[0]),
                             f"Its conversations.json unpacks to more than {MAX_PART_BYTES >> 20} MB: more than research "
                             "chats come to, most likely the whole account. " + _ONE_AT_A_TIME)
    except zipfile.BadZipFile:
        raise ConvertError("That zip couldn't be opened.") from None


def _bounded_read(archive: zipfile.ZipFile, info: zipfile.ZipInfo, too_big: str) -> bytes:
    """One part of a zip, unpacked to MAX_PART_BYTES at most; past that, `too_big` says why not."""
    if info.flag_bits & 0x1:
        raise ConvertError("That file is locked with a password, so CLIVE can't read it.")
    if info.file_size > MAX_PART_BYTES:
        raise ConvertError(too_big)
    with archive.open(info) as handle:
        data = handle.read(MAX_PART_BYTES + 1)
    if len(data) > MAX_PART_BYTES:
        raise ConvertError(too_big)
    return data


def _refuse_declarations(xml: bytes) -> None:
    head = xml[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in xml.upper():
        raise ConvertError("That Word file declares its own XML entities, which CLIVE doesn't read.")


def _text(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="replace").replace("\r\n", "\n").replace("\r", "\n")


def _sectioned(chunks: list[str], word: str) -> str:
    """Pages (or one long text) as sections the adapter keeps whole: '## Page 3', and a long page
    split again at paragraph breaks ('## Page 3, continued')."""
    out: list[str] = []
    for number, chunk in enumerate(chunks, 1):
        body = chunk.strip()
        if not body:
            continue
        label = f"{word} {number}" if len(chunks) > 1 or word == "Page" else "Text"
        for i, piece in enumerate(_pieces(body)):
            out.append(f"## {label}{', continued' if i else ''}\n\n{piece}")
    return "\n\n".join(out)


def _chunked_markdown(lines: list[str]) -> str:
    """Markdown lines as written, with a 'continued' heading wherever a section would pass
    SECTION_CHARS, so the adapter never cuts one short."""
    out: list[str] = []
    heading = "Text"
    size = 0
    for line in lines:
        match = re.match(r"(#{1,6}) (.*)", line)
        if match:
            heading, size = match.group(2)[:120], 0
            out.append(line)
            continue
        for piece in _pieces(line):
            if size and size + len(piece) > SECTION_CHARS:
                out.append(f"## {heading}, continued")
                size = 0
            out.append(piece)
            size += len(piece) + 2
    return "\n\n".join(out)


def _pieces(text: str) -> list[str]:
    if len(text) <= SECTION_CHARS:
        return [text]
    pieces: list[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", text):
        while len(para) > SECTION_CHARS:
            cut = para.rfind(" ", 0, SECTION_CHARS)
            cut = cut if cut > SECTION_CHARS // 2 else SECTION_CHARS
            if current:
                pieces.append(current)
                current = ""
            pieces.append(para[:cut])
            para = para[cut:].lstrip()
        if current and len(current) + len(para) + 2 > SECTION_CHARS:
            pieces.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        pieces.append(current)
    return pieces


def _has_words(text: str) -> bool:
    return len(re.findall(r"[A-Za-z]{2,}", text)) >= 5


def _stem(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", PurePosixPath(str(name)).stem).strip("-._")[:80]
    return stem or "research"


def _one_line(value) -> str:
    return _SPACE.sub(" ", str(value or "")).replace("\n", " ").strip()[:200]


def _short(name: str) -> str:
    text = _one_line(PurePosixPath(str(name or "")).name)
    return f"“{text[:80]}”" if text else "That file"
