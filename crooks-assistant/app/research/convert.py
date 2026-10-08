"""Research George gives CLIVE, turned into text the digester can read.

Why this exists: George's research arrives as whatever ChatGPT or a browser gave him — a PDF, a
Word file, Markdown, plain text, a saved share page, or ChatGPT's own export (conversations.json,
or the zip it comes in). The digester's documents adapter reads Markdown, text and HTML only, and
its scanner reads only what is text. So each file is turned into Markdown here, once, at intake,
and the quarantined copy is that Markdown: what the scanner scans is exactly what the model is
later shown.

What it promises:
- Reading only. Nothing in a file is run: a PDF is parsed by pypdf (the one dependency, loaded
  only for a PDF), a Word file is unzipped and its XML read with the standard library (any
  DOCTYPE or ENTITY refused before parsing), a ChatGPT export is read as JSON.
- Bounded: the file, each part unzipped, the pages read, the text made and the conversations
  taken. Past a bound it says so in words (ConvertError), or notes what it left out.
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
from pathlib import PurePosixPath
from xml.etree import ElementTree

MAX_FILE_BYTES = 25 << 20        # one file George gives
MAX_UNZIPPED_BYTES = 64 << 20    # one part read out of a Word file or a ChatGPT export zip
MAX_PAGES = 500                  # pages read from one PDF
MAX_TEXT_CHARS = 1_500_000       # Markdown made from one file (the adapter reads 2 MB a file)
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


class ConvertError(Exception):
    """A file that could not be read as research, said in words for George."""


@dataclass
class Converted:
    """What a file became: (name, Markdown or HTML text) files, and notes on anything left out."""

    kind: str
    files: list[tuple[str, str]]
    notes: list[str] = field(default_factory=list)


def kind_of(name: str) -> str:
    """The kind of research a file name says it is, or "" when it is not one CLIVE takes."""
    return SUFFIXES.get(PurePosixPath(str(name or "")).suffix.lower(), "")


def convert(name: str, data: bytes) -> Converted:
    """The file `name` with these bytes, as Markdown (or HTML for a saved page)."""
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
        return Converted(kind, [(f"{stem}.html", _text(data))], notes)
    elif kind == "chatgpt":
        text = _chatgpt(_json(data, name), notes)
    else:
        text = _chatgpt(_json(_from_zip(data), "conversations.json"), notes)
    text = _BLANKS.sub("\n\n", _CONTROL.sub("", text)).strip()
    if not _has_words(text):
        raise ConvertError(f"No text could be read from {_short(name)}. A scanned PDF has pictures of words, not words: "
                           "export the research as text, Markdown or Word instead.")
    if len(text) > MAX_TEXT_CHARS:
        notes.append(f"Only the first {MAX_TEXT_CHARS:,} characters were taken; the rest of the file was left out.")
        text = text[:MAX_TEXT_CHARS].rsplit("\n", 1)[0]
    return Converted(kind, [(f"{stem}.md", text + "\n")], notes)


# ------------------------------------------------------------------ each kind


def _pdf(data: bytes, notes: list[str]) -> list[str]:
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:
        raise ConvertError("PDF reading isn't installed on this server (the pypdf package). "
                           "Give the research as Word, Markdown or text, or install pypdf.") from None
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise ConvertError("That PDF is locked with a password, so CLIVE can't read it.")
        pages = list(reader.pages)
    except ConvertError:
        raise
    except (PdfReadError, ValueError, KeyError, TypeError, OSError) as exc:
        raise ConvertError(f"That PDF couldn't be read ({type(exc).__name__}).") from None
    if len(pages) > MAX_PAGES:
        notes.append(f"Only the first {MAX_PAGES} of its {len(pages)} pages were read.")
        pages = pages[:MAX_PAGES]
    out: list[str] = []
    unread = 0
    for page in pages:
        try:
            out.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - one bad page is a note, not the whole file lost
            unread += 1
            out.append("")
    if unread:
        notes.append(f"{unread} page{'s' if unread != 1 else ''} couldn't be read and {'were' if unread != 1 else 'was'} left out.")
    return out


def _docx(data: bytes, notes: list[str]) -> str:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        info = archive.getinfo("word/document.xml")
    except (zipfile.BadZipFile, KeyError, OSError):
        raise ConvertError("That Word file couldn't be opened: it has no document inside it.") from None
    xml = _bounded_read(archive, info)
    root = _parse_xml(xml)
    body = root.find(f"{_W}body")
    if body is None:
        raise ConvertError("That Word file has no body to read.")
    lines: list[str] = []
    for block in body:
        if block.tag == f"{_W}p":
            line = _paragraph(block)
            if line:
                lines.append(line)
        elif block.tag == f"{_W}tbl":
            for row in block.iter(f"{_W}tr"):
                cells = [" ".join(_runs(p) for p in cell.iter(f"{_W}p")).strip() for cell in row.iter(f"{_W}tc")]
                if any(cells):
                    lines.append("| " + " | ".join(cells) + " |")
    return _chunked_markdown(lines)


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


def _chatgpt(data, notes: list[str]) -> str:
    conversations = data if isinstance(data, list) else [data] if isinstance(data, dict) else None
    if not conversations or not all(isinstance(c, dict) for c in conversations):
        raise ConvertError("That JSON isn't a ChatGPT export: it holds no conversations.")
    if len(conversations) > MAX_CONVERSATIONS:
        raise ConvertError(
            f"That ChatGPT export holds {len(conversations)} chats: the whole account, not one piece of research. "
            "Give the research chats one at a time instead: export the report as PDF, Word or Markdown, "
            "or save the shared chat's page.")
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
        return _bounded_read(archive, archive.getinfo(sorted(names, key=len)[0]))
    except zipfile.BadZipFile:
        raise ConvertError("That zip couldn't be opened.") from None


def _bounded_read(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    if info.flag_bits & 0x1:
        raise ConvertError("That file is locked with a password, so CLIVE can't read it.")
    if info.file_size > MAX_UNZIPPED_BYTES:
        raise ConvertError(f"Part of that file unpacks to {info.file_size >> 20} MB, past the {MAX_UNZIPPED_BYTES >> 20} MB CLIVE reads.")
    with archive.open(info) as handle:
        data = handle.read(MAX_UNZIPPED_BYTES + 1)
    if len(data) > MAX_UNZIPPED_BYTES:
        raise ConvertError(f"Part of that file unpacks past the {MAX_UNZIPPED_BYTES >> 20} MB CLIVE reads.")
    return data


def _parse_xml(xml: bytes):
    head = xml[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in xml.upper():
        raise ConvertError("That Word file declares its own XML entities, which CLIVE doesn't read.")
    try:
        return ElementTree.fromstring(xml)
    except ElementTree.ParseError:
        raise ConvertError("That Word file's text couldn't be read.") from None


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
