"""The Knowledge Digester's quarantine scanner: what an artifact would do to us if we trusted it.

An artifact — a repository, an agent skill, a document set, an API spec, a theme — arrives in a
quarantined directory and is read here before anything else touches it. Reading is all this
module does: files are opened as bytes, never imported, executed, installed, rendered or
followed out of the tree. Symbolic links are reported and not followed; pipes, sockets and
devices are reported and not opened; binaries are skipped; and limits on file size and on the
number of entries walked mean a hostile or merely enormous artifact cannot stall the scan.

Five kinds of finding come back, each with a severity (info, warn, block), a path and a line
(line 0 means the file as a whole) and a plain explanation:

- ``injection.*``  text aimed at an AI agent rather than a human reader, including where it is
  hidden (HTML comments, link titles, alt text, front matter) or encoded (base64, hex);
- ``deceptive.*``  invisible or misleading characters: zero-width, bidi controls, tag
  characters, look-alike letters mixed into an identifier;
- ``secret.*``     credentials in known shapes;
- ``execute.*``    files that would run if the artifact were installed, built or opened;
- ``licence.*``    the artifact's licence as an SPDX identifier, and whether it allows reuse.

A finding never quotes what it found. A secret's value would be copied into every report that
carries the finding, and a quoted instruction would carry the injection into the context of
whoever reads the report — which is exactly where it was trying to get. Findings name the kind
of thing and where it is; the text stays in quarantine.
"""

from __future__ import annotations

import base64
import bisect
import configparser
import json
import os
import re
import stat
import tomllib
import unicodedata
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass

INFO = "info"
WARN = "warn"
BLOCK = "block"
_RANK = {BLOCK: 0, WARN: 1, INFO: 2}

UNKNOWN = "unknown"

# Bounds on one scan. Entries counts files, directories and links alike, so a tree of a
# million empty directories stops as surely as a million files.
MAX_FILES = 5000
MAX_FILE_BYTES = 1_000_000
_BINARY_PROBE = 8192
_MAX_DECODE_DEPTH = 3
_MAX_PER_RULE = 25


@dataclass(frozen=True)
class Finding:
    """One thing the scanner saw. ``line`` is 1-based; 0 means the file (or path) as a whole."""

    severity: str
    rule: str
    path: str
    line: int
    message: str


def scan_tree(
    root: str | os.PathLike[str],
    *,
    max_files: int = MAX_FILES,
    max_file_bytes: int = MAX_FILE_BYTES,
) -> list[Finding]:
    """Every finding for the quarantined directory at ``root``, most severe first, then by path."""
    base = os.fspath(root)
    if not os.path.isdir(base):
        raise NotADirectoryError(base)
    findings: list[Finding] = []
    licensed = False
    for kind, rel in _walk(base, max_files):
        path = _display(rel)
        if kind == "limit":
            findings.append(Finding(
                WARN, "scan.limit", path, 0,
                f"Stopped after {max_files} files and directories: the rest of the artifact was "
                "not scanned, so its contents are unknown.",
            ))
        elif kind == "unreadable":
            findings.append(_unreadable(path))
        elif kind == "link":
            findings.append(_link_finding(base, rel, path))
        elif kind == "other":
            findings.append(_special(path))
        else:
            found, has_licence = _scan_file(base, rel, path, max_file_bytes)
            findings.extend(found)
            licensed = licensed or has_licence
    if not licensed:
        findings.append(Finding(
            WARN, "licence.unknown", ".", 0,
            "No licence found: no LICENSE or COPYING file and no licence in a package manifest. "
            "The licence is 'unknown', and without one nothing grants the right to reuse it.",
        ))
    return sorted(set(findings), key=_order)


def _order(finding: Finding) -> tuple:
    return (_RANK.get(finding.severity, 3), finding.path, finding.line, finding.rule, finding.message)


# --- walking the tree ---------------------------------------------------------------------


def _walk(base: str, max_files: int) -> Iterator[tuple[str, str]]:
    """(kind, relative path) for each entry, breadth first so the top of the artifact — where its
    licence and manifests live — is read before a limit can cut in. Links are never followed."""
    queue: deque[str] = deque([""])
    seen = 0
    while queue:
        folder = queue.popleft()
        try:
            with os.scandir(os.path.join(base, folder)) as listing:
                entries = []
                for entry in listing:
                    entries.append(entry)
                    if len(entries) > max_files:
                        break
        except OSError:
            yield "unreadable", folder or "."
            continue
        entries.sort(key=lambda entry: entry.name)
        for entry in entries:
            seen += 1
            if seen > max_files:
                yield "limit", folder or "."
                return
            rel = f"{folder}/{entry.name}" if folder else entry.name
            try:
                kind = _kind(entry)
            except OSError:
                kind = "unreadable"
            if kind != "dir":
                yield kind, rel
            elif entry.name == ".git":
                # Git's object store is not the artifact. Only what git would run from is read.
                if _is_regular(os.path.join(base, rel, "config")):
                    yield "file", f"{rel}/config"
                if _is_real_dir(os.path.join(base, rel, "hooks")):
                    queue.append(f"{rel}/hooks")
            else:
                queue.append(rel)


def _kind(entry: os.DirEntry[str]) -> str:
    if entry.is_symlink():
        return "link"
    if entry.is_dir(follow_symlinks=False):
        return "dir"
    if entry.is_file(follow_symlinks=False):
        return "file"
    return "other"


def _is_regular(path: str) -> bool:
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def _is_real_dir(path: str) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode)
    except OSError:
        return False


def _display(rel: str) -> str:
    """The path as it can be shown: anything unprintable (a bidi override in a file name, say)
    is written as an escape so the path cannot rearrange the report it appears in."""
    if rel.isprintable():
        return rel
    return "".join(ch if ch.isprintable() else _escape(ch) for ch in rel)


def _escape(ch: str) -> str:
    code = ord(ch)
    return f"\\u{code:04x}" if code <= 0xFFFF else f"\\U{code:08x}"


def _unreadable(path: str) -> Finding:
    return Finding(WARN, "scan.unreadable", path, 0, "Could not be read, so its contents are unknown.")


def _special(path: str) -> Finding:
    return Finding(
        WARN, "scan.special", path, 0,
        "Not a regular file (a pipe, socket or device), so it was not opened.",
    )


def _link_finding(base: str, rel: str, path: str) -> Finding:
    try:
        target = os.readlink(os.path.join(base, rel))
    except OSError:
        target = ""
    resolved = os.path.normpath(os.path.join(os.path.dirname(rel), target))
    outside = (
        not target or os.path.isabs(target)
        or resolved == ".." or resolved.startswith(".." + os.sep)
    )
    if not outside:
        return Finding(INFO, "scan.symlink", path, 0, "Symbolic link, not followed.")
    return Finding(
        WARN, "scan.symlink", path, 0,
        "Symbolic link pointing outside the artifact, not followed: whatever reads the artifact "
        "next must not follow it either.",
    )


# --- reading one file ---------------------------------------------------------------------


class _NotRegular(OSError):
    """The path turned out not to be a regular file by the time it was opened."""


def _scan_file(base: str, rel: str, path: str, max_bytes: int) -> tuple[list[Finding], bool]:
    found: list[Finding] = []
    if any(_is_hidden_char(ch) for ch in rel):
        found.append(Finding(
            BLOCK, "deceptive.filename", path, 0,
            "The file name contains invisible or direction-changing characters, so it can "
            "display as a different name from the one it has.",
        ))
    text: str | None = None
    try:
        data, oversized = _read(os.path.join(base, rel), max_bytes)
    except _NotRegular:
        return [*found, _special(path)], False
    except OSError:
        found.append(_unreadable(path))
    else:
        if _looks_binary(data):
            found.append(Finding(INFO, "scan.binary", path, 0, "Binary file, skipped: only text is scanned."))
        elif oversized:
            found.append(Finding(
                WARN, "scan.too_large", path, 0,
                f"Larger than the {max_bytes}-byte limit, so it was not scanned and its contents "
                "are unknown.",
            ))
        else:
            text = _decode(data)
    found.extend(_execution_findings(rel, path, text))
    licence, has_licence = _licence_findings(rel, path, text)
    found.extend(licence)
    if text is not None:
        found.extend(_content_findings(path, text))
    return found, has_licence


def _read(path: str, max_bytes: int) -> tuple[bytes, bool]:
    """The file's bytes (only a probe's worth if it is over the limit) and whether it is. Opened
    without following a link and without blocking, and checked to be a regular file before a
    byte is read, so a link or a pipe swapped in after the walk cannot be read through."""
    flags = (
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_BINARY", 0)
    )
    fd = os.open(path, flags)
    chunks: list[bytes] = []
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _NotRegular(path)
        oversized = info.st_size > max_bytes
        remaining = _BINARY_PROBE if oversized else max_bytes + 1
        while remaining > 0:
            chunk = os.read(fd, min(remaining, 1 << 16))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    return data, oversized or len(data) > max_bytes


def _looks_binary(data: bytes) -> bool:
    head = data[:_BINARY_PROBE]
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    if b"\x00" in head:
        return True
    decoded = head.decode("utf-8", errors="replace")
    return decoded.count("\ufffd") > max(4, len(decoded) // 10)


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    return data.decode("utf-8", errors="replace")


def _content_findings(path: str, text: str) -> list[Finding]:
    # Characters are judged on the text as written; phrases and secrets on the text as a model
    # would read it, with invisible characters gone and tag characters spelled out, so neither
    # can be split or smuggled past the patterns. Both keep every newline, so lines agree.
    clean = _clean(text)
    starts = _line_starts(clean)
    found = _character_findings(path, text)
    found.extend(_injection_findings(path, clean, starts))
    found.extend(_secret_findings(path, clean, starts))
    return _capped(path, found)


def _capped(path: str, found: list[Finding]) -> list[Finding]:
    kept: list[Finding] = []
    counts: dict[str, int] = {}
    for finding in sorted(set(found), key=_order):
        counts[finding.rule] = counts.get(finding.rule, 0) + 1
        if counts[finding.rule] <= _MAX_PER_RULE:
            kept.append(finding)
    kept.extend(
        Finding(INFO, "scan.truncated", path, 0,
                f"{count - _MAX_PER_RULE} further '{rule}' findings in this file are not listed.")
        for rule, count in counts.items() if count > _MAX_PER_RULE
    )
    return kept


_NEWLINE = re.compile("\n")


def _line_starts(text: str) -> list[int]:
    return [0, *(match.end() for match in _NEWLINE.finditer(text))]


def _line_at(starts: list[int], offset: int) -> int:
    return bisect.bisect_right(starts, offset)


def _line_of(text: str, pattern: str | re.Pattern[str]) -> int:
    match = re.search(pattern, text)
    return text.count("\n", 0, match.start()) + 1 if match else 0


# --- invisible and deceptive characters ---------------------------------------------------

_ZERO_WIDTH = frozenset((
    0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064,
    0xFEFF, 0x180E, 0x061C,
))
_JOINERS = frozenset((0x200C, 0x200D))
_BIDI_CONTROLS = frozenset((*range(0x202A, 0x202F), *range(0x2066, 0x206A)))
_BLACK_FLAG = 0x1F3F4
_TAG_RUN = re.compile(r"[\U000e0000-\U000e007f]+")
_INVISIBLE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\u180e\u061c\u00ad]")
# Letters from other scripts that render like Latin ones: Cyrillic, Greek and Armenian.
_CONFUSABLES = frozenset(
    "\u0430\u0435\u043e\u0440\u0441\u0443\u0445\u0456\u0458\u0455\u0501\u04bb\u051b\u051d\u04cf"
    "\u0410\u0412\u0415\u041a\u041c\u041d\u041e\u0420\u0421\u0422\u0425\u0405\u0406\u0408"
    "\u03b1\u03bf\u03bd\u03b9\u03ba\u03c1\u03c5"
    "\u0391\u0392\u0395\u0396\u0397\u0399\u039a\u039c\u039d\u039f\u03a1\u03a4\u03a5\u03a7"
    "\u0585\u057d"
)
_WORD = re.compile(r"\w+")


def _is_hidden_char(ch: str) -> bool:
    code = ord(ch)
    return code in _ZERO_WIDTH or code in _BIDI_CONTROLS or 0xE0000 <= code <= 0xE007F


def _clean(text: str) -> str:
    """Text as a model reads it: tag characters become the ASCII they encode, invisible
    characters go, and compatibility forms (fullwidth letters and the like) fold to plain."""
    text = _TAG_RUN.sub(_untag, text)
    return unicodedata.normalize("NFKC", _INVISIBLE.sub("", text))


def _untag(match: re.Match[str]) -> str:
    return "".join(chr(ord(ch) - 0xE0000) for ch in match.group() if 0xE0020 <= ord(ch) <= 0xE007E)


def _names(codes: list[int]) -> str:
    return ", ".join(f"U+{code:04X} {unicodedata.name(chr(code), 'unnamed')}" for code in sorted(set(codes)))


def _character_findings(path: str, text: str) -> list[Finding]:
    found: list[Finding] = []
    for number, line in enumerate(text.split("\n"), 1):
        if line.isascii():
            continue
        invisible: list[int] = []
        bidi: list[int] = []
        tags = 0
        in_flag = False
        for index, ch in enumerate(line):
            code = ord(ch)
            if code < 0x80:
                in_flag = False
                continue
            if 0xE0000 <= code <= 0xE007F:
                # A black flag followed by tags is a subdivision flag (England, Scotland, Wales).
                if not in_flag:
                    tags += 1
                continue
            in_flag = code == _BLACK_FLAG
            if code in _BIDI_CONTROLS:
                bidi.append(code)
            elif code in _ZERO_WIDTH:
                if code == 0xFEFF and number == 1 and index == 0:
                    continue  # a byte-order mark
                if code in _JOINERS and not _between_ascii(line, index):
                    continue  # joining emoji or a script that needs it
                invisible.append(code)
        if invisible:
            found.append(Finding(
                WARN, "deceptive.invisible", path, number,
                f"{len(invisible)} invisible character(s) ({_names(invisible)}): they can split "
                "words to slip past filters, or carry content a reader cannot see.",
            ))
        if bidi:
            found.append(Finding(
                BLOCK, "deceptive.bidi", path, number,
                f"{len(bidi)} bidirectional control character(s) ({_names(bidi)}): they reorder "
                "how the line displays, so what a reviewer sees is not what a machine reads.",
            ))
        if tags:
            found.append(Finding(
                BLOCK, "deceptive.tag", path, number,
                f"{tags} Unicode tag character(s): invisible on screen, and able to spell out "
                "hidden text that a model still reads.",
            ))
        for token in _WORD.findall(line):
            if token.isascii():
                continue
            lookalikes = [ch for ch in token if ch in _CONFUSABLES]
            if lookalikes and any(ch.isascii() and ch.isalpha() for ch in token):
                scripts = sorted({unicodedata.name(ch, "OTHER").split()[0].title() for ch in lookalikes})
                found.append(Finding(
                    WARN, "deceptive.homoglyph", path, number,
                    f"An identifier mixes Latin letters with {len(lookalikes)} look-alike "
                    f"{'/'.join(scripts)} letter(s), so it can pass for a familiar name while "
                    "being a different one.",
                ))
    return found


def _between_ascii(line: str, index: int) -> bool:
    before = line[index - 1] if index > 0 else " "
    after = line[index + 1] if index + 1 < len(line) else " "
    return before.isascii() and after.isascii()


# --- instructions aimed at an AI agent ----------------------------------------------------


@dataclass(frozen=True)
class _Phrase:
    name: str
    severity: str
    patterns: tuple[re.Pattern[str], ...]
    explanation: str

    def search(self, text: str) -> re.Match[str] | None:
        for pattern in self.patterns:
            match = pattern.search(text)
            if match:
                return match
        return None

    def finditer(self, text: str) -> Iterator[re.Match[str]]:
        for pattern in self.patterns:
            yield from pattern.finditer(text)


_PHRASES = (
    _Phrase("override", BLOCK, (
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass|abandon)\s+"
            r"(?:(?:all|any|every|the|of|these|those|my|what|you|were|was|have|been|told|given)\s+){0,4}"
            r"(?:previous|prior|above|earlier|preceding|foregoing|former|original|initial|existing"
            r"|system|developer|safety|your)\s+"
            r"(?:\w+\s+)?"
            r"(?:instructions?|prompts?|directions?|directives?|rules|guidelines|guardrails"
            r"|messages?|constraints|programming)\b",
            re.I,
        ),
        re.compile(r"\b(?:ignore|disregard|forget)\s+all\s+(?:instructions|prompts|directives|guidelines)\b", re.I),
        re.compile(
            r"\b(?:ignore|disregard|forget)\s+(?:everything|anything|all)\s+"
            r"(?:(?:written|said|stated)\s+)?(?:above|before|previously|so\s+far)\b",
            re.I,
        ),
        re.compile(r"\b(?:your|the)\s+(?:new|real|actual|updated)\s+(?:instructions|task|role|objective|orders)\s+(?:is|are)\b", re.I),
    ), "tells an AI agent to ignore or replace the instructions it was given"),
    _Phrase("conceal", BLOCK, (
        re.compile(r"\b(?:do\s+not|don[\u2019']?t|never)\s+(?:tell|inform|alert|notify|warn)\s+(?:the\s+)?(?:user|human|owner|operator)s?\b", re.I),
        re.compile(
            r"\b(?:do\s+not|don[\u2019']?t|never)\s+(?:mention|reveal|disclose|show)\s+(?:this|these|it|that)\s+"
            r"(?:\w+\s+){0,3}?to\s+(?:the\s+)?(?:user|human|owner|operator)s?\b",
            re.I,
        ),
        re.compile(r"\bwithout\s+(?:telling|informing|alerting|notifying)\s+(?:the\s+)?(?:user|human|owner|operator)s?\b", re.I),
    ), "tells an AI agent to keep what it does from the person it works for"),
    _Phrase("address", WARN, (
        re.compile(
            r"\b(?:hey|dear|note\s+to|message\s+(?:to|for)|instructions?\s+(?:to|for))(?:\s+the)?,?\s+"
            r"(?:ai|assistants?|llms?|language\s+models?|models?|chatbots?|ai\s+agents?|agents?"
            r"|claude|chatgpt|gpt|copilot|gemini)\b",
            re.I,
        ),
        re.compile(
            r"\bif\s+you\s+are\s+(?:an?\s+)?(?:ai|llm|(?:large\s+)?language\s+model|(?:ai\s+)?assistant"
            r"|ai\s+agent|agent|chatbot|bot)\b",
            re.I,
        ),
        re.compile(r"\b(?:ai|llm)\s+(?:agents?|assistants?|models?)\s+(?:reading|processing|parsing|summari[sz]ing|ingesting|digesting)\s+(?:this|these)\b", re.I),
        re.compile(r"\byou\s+are\s+now\s+(?:an?\s+)?(?:\w+\s+){0,2}?(?:ai|assistant|model|agent|bot|jailbroken|unrestricted|unfiltered|dan)\b", re.I),
        re.compile(r"\bfrom\s+now\s+on,?\s+you\s+(?:are|will|must|should)\b", re.I),
    ), "speaks directly to an AI assistant or model rather than to a human reader"),
    _Phrase("marker", WARN, (
        re.compile(r"<\|(?:im_start|im_end|im_sep|system|user|assistant|endoftext|eot_id|start_header_id|end_header_id)\|>", re.I),
        re.compile(r"\[/?(?:INST|SYS)\]|<</?SYS>>"),
        re.compile(
            r"</?(?:system|system[-_]reminder|system[-_]prompt|tool[-_]call|tool[-_]use|tool[-_]result"
            r"|function[-_]calls|function[-_]results|antml:[a-z_]+)\b[^<>\n]{0,200}>",
            re.I,
        ),
        re.compile(r"^[ \t>*#]*(?:Human|Assistant|SYSTEM|System prompt)[ \t]*:", re.M),
    ), "imitates a system-prompt, chat-role or tool-call marker that a model could mistake for real conversation structure"),
)

_LINK_TITLE = re.compile(r"""\]\([^()\s]*\s+(?:"([^"\n]{1,2000})"|'([^'\n]{1,2000})')\s*\)""")
_REFERENCE_TITLE = re.compile(
    r"""^[ \t]{0,3}\[[^\]\n]{1,500}\]:[ \t]*\S+[ \t]+"""
    r"""(?:"([^"\n]{1,2000})"|'([^'\n]{1,2000})'|\(([^()\n]{1,2000})\))[ \t\r]*$""",
    re.M,
)
_IMAGE_ALT = re.compile(r"!\[([^\]\n]{1,2000})\]")
_HTML_ATTRIBUTE = re.compile(r"""\b(?:alt|title|aria-label)[ \t]*=[ \t]*(?:"([^"]{1,2000})"|'([^']{1,2000})')""", re.I)
_CARRIERS = (
    (_LINK_TITLE, "a markdown link title"),
    (_REFERENCE_TITLE, "a markdown link title"),
    (_IMAGE_ALT, "image alt text"),
    (_HTML_ATTRIBUTE, "an HTML alt or title attribute"),
)
_FRONT_MATTER = re.compile(r"(?:---|\+\+\+)[ \t]*\r?\n")
_FENCE_CLOSE = {
    "-": re.compile(r"^---[ \t\r]*$", re.M),
    "+": re.compile(r"^\+\+\+[ \t\r]*$", re.M),
}


def _injection_findings(path: str, text: str, starts: list[int]) -> list[Finding]:
    found: list[Finding] = []
    hidden_lines: set[int] = set()
    for offset, body, carrier in _hidden_carriers(text):
        for phrase in _PHRASES:
            for match in phrase.finditer(body):
                line = _line_at(starts, offset + match.start())
                hidden_lines.add(line)
                found.append(Finding(
                    BLOCK, "injection.hidden", path, line,
                    f"Text hidden in {carrier}, where a human reader will not see it, "
                    f"{phrase.explanation}.",
                ))
    for phrase in _PHRASES:
        for match in phrase.finditer(text):
            line = _line_at(starts, match.start())
            if line not in hidden_lines:
                found.append(Finding(
                    phrase.severity, f"injection.{phrase.name}", path, line,
                    f"Text here {phrase.explanation}.",
                ))
    for offset, decoded, encoding in _decodings(text):
        phrase = _decoded_instruction(decoded, 1)
        if phrase is not None:
            found.append(Finding(
                BLOCK, "injection.encoded", path, _line_at(starts, offset),
                f"A {encoding} blob here decodes to text that {phrase.explanation}; the encoding "
                "hides it from a human reader, not from a model that decodes it.",
            ))
    return found


def _hidden_carriers(text: str) -> Iterator[tuple[int, str, str]]:
    """(offset, body, what it is) for each place text can sit unseen by a human reader."""
    start = text.find("<!--")
    while start >= 0:
        # Found by hand rather than by a lazy regex, so unclosed comments cost one pass, not many.
        end = text.find("-->", start + 4)
        yield start + 4, text[start + 4:end if end >= 0 else len(text)], "an HTML comment"
        if end < 0:
            break
        start = text.find("<!--", end + 3)
    for pattern, carrier in _CARRIERS:
        for match in pattern.finditer(text):
            offset, body = _first_group(match)
            yield offset, body, carrier
    opening = _FRONT_MATTER.match(text)
    if opening:
        closing = _FENCE_CLOSE[opening.group()[0]].search(text, opening.end())
        if closing:
            yield opening.end(), text[opening.end():closing.start()], "front matter"


def _first_group(match: re.Match[str]) -> tuple[int, str]:
    for index in range(1, match.re.groups + 1):
        if match.group(index) is not None:
            return match.start(index), match.group(index)
    return match.start(), match.group()


_UPPER = re.compile(r"[A-Z]")
_LOWER = re.compile(r"[a-z]")
_WORDISH = re.compile(r"[A-Za-z]{3}")


def _as_text(raw: bytes) -> str | None:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if len(text) < 8 or not _WORDISH.search(text):
        return None
    printable = sum(1 for ch in text if ch.isprintable() or ch in "\t\r\n")
    return text if printable >= 0.9 * len(text) else None


def _from_base64(blob: str) -> str | None:
    if not (_UPPER.search(blob) and _LOWER.search(blob)):
        return None  # identifiers and hex digests, not base64 of text
    core = blob.rstrip("=").replace("-", "+").replace("_", "/")
    if len(core) % 4 == 1:
        core = core[:-1]
    try:
        raw = base64.b64decode(core + "=" * (-len(core) % 4), validate=True)
    except ValueError:
        return None
    return _as_text(raw)


def _from_hex(blob: str) -> str | None:
    try:
        return _as_text(bytes.fromhex(blob.replace("\\x", "").replace("%", "")))
    except ValueError:
        return None


# Matches never overlap within one pattern, so decoding is linear in the size of the text.
_ENCODINGS = (
    ("base64", re.compile(r"[A-Za-z0-9+/_-]{20,}={0,2}"), _from_base64),
    ("hex", re.compile(r"(?:[0-9A-Fa-f]{2}){16,}"), _from_hex),
    ("escaped-byte", re.compile(r"(?:\\x[0-9A-Fa-f]{2}){8,}|(?:%[0-9A-Fa-f]{2}){8,}"), _from_hex),
)


def _decodings(text: str) -> Iterator[tuple[int, str, str]]:
    for encoding, pattern, decode in _ENCODINGS:
        for match in pattern.finditer(text):
            decoded = decode(match.group())
            if decoded is not None:
                yield match.start(), decoded, encoding


def _decoded_instruction(decoded: str, depth: int) -> _Phrase | None:
    clean = _clean(decoded)
    for phrase in _PHRASES:
        if phrase.search(clean):
            return phrase
    if depth < _MAX_DECODE_DEPTH:
        for _offset, inner, _encoding in _decodings(clean):
            phrase = _decoded_instruction(inner, depth + 1)
            if phrase is not None:
                return phrase
    return None


# --- credentials --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Secret:
    slug: str
    label: str
    pattern: re.Pattern[str]
    severity: str = BLOCK
    group: int = 0
    generic: bool = False  # a guess from context, so placeholders are not reported


# Specific shapes first: a line that has one does not also get the generic guess.
_SECRETS = (
    _Secret("aws_access_key", "an AWS access key ID", re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")),
    _Secret("aws_secret_key", "an AWS secret access key",
            re.compile(r"(?i)aws.{0,20}secret.{0,20}[:=][ \t]*[\"']?([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])"), group=1),
    _Secret("google_api_key", "a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])")),
    _Secret("azure_storage_key", "an Azure storage account key",
            re.compile(r"AccountKey=([A-Za-z0-9+/]{80,}={0,2})"), group=1),
    _Secret("stripe_key", "a Stripe secret or restricted key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,}")),
    _Secret("stripe_webhook_secret", "a Stripe webhook signing secret", re.compile(r"\bwhsec_[0-9A-Za-z]{24,}")),
    _Secret("shopify_token", "a Shopify access token", re.compile(r"\bshp(?:at|ca|pa|ss)_[0-9a-fA-F]{32}\b")),
    _Secret("slack_token", "a Slack token", re.compile(r"\bxox[abposr]-[0-9A-Za-z-]{10,}")),
    _Secret("slack_webhook", "a Slack incoming-webhook URL",
            re.compile(r"hooks\.slack\.com/services/T[0-9A-Z]+/B[0-9A-Z]+/[0-9A-Za-z]+")),
    _Secret("discord_webhook", "a Discord webhook URL",
            re.compile(r"discord(?:app)?\.com/api/webhooks/\d+/[0-9A-Za-z_-]{20,}")),
    _Secret("telegram_bot_token", "a Telegram bot token", re.compile(r"\b\d{8,10}:AA[0-9A-Za-z_-]{33}(?![0-9A-Za-z_-])")),
    _Secret("github_token", "a GitHub token", re.compile(r"\b(?:gh[pousr]_[0-9A-Za-z]{36,}|github_pat_[0-9A-Za-z_]{50,})")),
    _Secret("gitlab_token", "a GitLab token", re.compile(r"\bglpat-[0-9A-Za-z_-]{20,}")),
    _Secret("npm_token", "an npm access token", re.compile(r"\bnpm_[0-9A-Za-z]{36}\b")),
    _Secret("pypi_token", "a PyPI upload token", re.compile(r"\bpypi-AgEIcHlwaS5vcmc[0-9A-Za-z_-]{20,}")),
    _Secret("anthropic_key", "an Anthropic API key", re.compile(r"\bsk-ant-[0-9A-Za-z_-]{20,}")),
    _Secret("openai_key", "an OpenAI API key",
            re.compile(r"\bsk-(?:proj|svcacct|admin)-[0-9A-Za-z_-]{20,}|\bsk-[0-9A-Za-z]{20}T3BlbkFJ[0-9A-Za-z]{20}")),
    _Secret("sendgrid_key", "a SendGrid API key", re.compile(r"\bSG\.[0-9A-Za-z_-]{22}\.[0-9A-Za-z_-]{43}(?![0-9A-Za-z_-])")),
    _Secret("twilio_key", "a Twilio API key", re.compile(r"\bSK[0-9a-f]{32}\b")),
    _Secret("private_key", "a private key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----")),
    _Secret("jwt", "a JSON web token",
            re.compile(r"\beyJ[0-9A-Za-z_-]{10,}\.eyJ[0-9A-Za-z_-]{10,}\.[0-9A-Za-z_-]{10,}"), severity=WARN),
    _Secret("npm_auth", "an npm registry credential", re.compile(r"_auth(?:Token)?[ \t]*=[ \t]*([^\s$'\"{]{8,})"), group=1),
    _Secret("url_password", "a password inside a connection URL",
            re.compile(r"\b[a-z][a-z0-9+.-]{1,20}://[^\s:/@'\"]{1,64}:([^\s@/'\"]{3,128})@[\w.-]+"),
            severity=WARN, group=1, generic=True),
    _Secret("assignment", "a hard-coded password or secret",
            re.compile(
                r"(?i)(?<![A-Za-z0-9])(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token"
                r"|client[_-]?secret)[\"']?[ \t]*[:=][ \t]*[\"']([^\"'\s]{8,})[\"']"
            ),
            severity=WARN, group=1, generic=True),
)
_PLACEHOLDER = re.compile(
    r"example|sample|dummy|placeholder|changeme|change[_-]me|your[_-]|xxxx|\*{3}|\.\.\.|[<>{}$%]|redacted|fake|password",
    re.I,
)


def _secret_findings(path: str, text: str, starts: list[int]) -> list[Finding]:
    found: list[Finding] = []
    specific_lines: set[int] = set()
    for secret in _SECRETS:
        for match in secret.pattern.finditer(text):
            value = match.group(secret.group) or ""
            line = _line_at(starts, match.start())
            if secret.generic:
                if line in specific_lines or _PLACEHOLDER.search(value):
                    continue
            else:
                specific_lines.add(line)
            found.append(Finding(
                secret.severity, f"secret.{secret.slug}", path, line,
                f"Looks like {secret.label} ({len(value)} characters; the value is withheld). "
                "Treat it as exposed: it is never digested, and its owner should revoke it.",
            ))
    return found


# --- things that would run ----------------------------------------------------------------

_GIT_HOOK = re.compile(r"(?:^|/)\.git/hooks/[^/]+$")
_HOOK_MANAGERS = re.compile(r"(?:^|/)\.(?:husky|githooks)/")
_GIT_CONFIG = re.compile(r"(?:^|/)\.git/config$")
_GIT_CONFIG_COMMANDS = re.compile(r"^[ \t]*(?:fsmonitor|hookspath|sshcommand|askpass|clean|smudge|process)[ \t]*=", re.I | re.M)
_CI_FILES = re.compile(
    r"(?:^|/)(?:\.github/workflows/[^/]+\.ya?ml|\.gitlab-ci\.ya?ml|\.circleci/config\.ya?ml"
    r"|azure-pipelines\.ya?ml|Jenkinsfile|\.travis\.ya?ml|bitbucket-pipelines\.ya?ml|\.drone\.ya?ml"
    r"|\.buildkite/[^/]+\.ya?ml)$"
)
_HARNESS_SETTINGS = re.compile(
    r"(?:^|/)(?:\.claude/settings(?:\.local)?\.json|\.gemini/settings\.json|\.cursor/hooks\.json|\.codex/config\.toml)$"
)
_MCP_FILES = re.compile(r"(?:^|/)(?:\.mcp\.json|mcp\.json|mcp_config\.json|claude_desktop_config\.json)$")
_MCP_COMMAND = re.compile(r'"command"\s*:')
_VSCODE_TASKS = re.compile(r"(?:^|/)\.vscode/tasks\.json$")
_AUTO_TASK = re.compile(r'"runOn"\s*:\s*"folderOpen"')
_JSON_KEY = re.compile(r'"([A-Za-z-]+)"\s*:')
_SCRIPT_SUFFIXES = (".sh", ".bash", ".zsh", ".ksh", ".fish", ".command", ".ps1", ".psm1", ".bat", ".cmd", ".vbs")

# Settings keys that make an agent harness run a command, or approve servers, when it loads.
_HARNESS_COMMAND_KEYS = tuple(
    "hooks statusLine apiKeyHelper awsAuthRefresh awsCredentialExport otelHeadersHelper "
    "enableAllProjectMcpServers enabledMcpjsonServers".split()
)
_DEVCONTAINER_COMMANDS = tuple(
    "initializeCommand onCreateCommand updateContentCommand postCreateCommand postStartCommand "
    "postAttachCommand".split()
)
_NPM_SCRIPTS = {
    "preinstall": (BLOCK, "on install"),
    "install": (BLOCK, "on install"),
    "postinstall": (BLOCK, "on install"),
    "prepare": (BLOCK, "on install from a folder or a git URL"),
    "prepublish": (WARN, "on install and publish"),
    "prepublishOnly": (WARN, "before publishing"),
    "prepack": (WARN, "when the package is packed"),
    "postpack": (WARN, "when the package is packed"),
    "preuninstall": (WARN, "on uninstall"),
    "uninstall": (WARN, "on uninstall"),
    "postuninstall": (WARN, "on uninstall"),
}
_COMPOSER_SCRIPTS = {
    "pre-install-cmd": (BLOCK, "on install"),
    "post-install-cmd": (BLOCK, "on install"),
    "pre-update-cmd": (BLOCK, "on update"),
    "post-update-cmd": (BLOCK, "on update"),
    "post-autoload-dump": (BLOCK, "on install and update"),
    "post-root-package-install": (BLOCK, "when the project is created"),
    "post-create-project-cmd": (BLOCK, "when the project is created"),
}
_BUILD_SCRIPTS = {
    "setup.py": (BLOCK, "setup.py is Python that runs whenever the package is built or installed from source."),
    "build.rs": (BLOCK, "build.rs is a Cargo build script: it is compiled and run before the crate is built."),
    "extconf.rb": (BLOCK, "extconf.rb runs when RubyGems installs a gem with a native extension."),
    "binding.gyp": (WARN, "binding.gyp makes npm compile native code with node-gyp when the package is installed."),
}
_PYPROJECT_HOOKS = (
    (re.compile(r"(?m)^[ \t]*backend-path[ \t]*="),
     "pyproject.toml builds with a backend from inside this artifact (backend-path), so the artifact's "
     "own code runs whenever the package is built or installed."),
    (re.compile(r"(?m)^\[tool\.hatch\.build(?:\.targets\.[^\]\n]+)?\.hooks\b"),
     "pyproject.toml declares Hatch build hooks, which run code whenever the package is built."),
    (re.compile(r"(?m)^\[tool\.poetry\.build\]"),
     "pyproject.toml names a Poetry build script, which runs whenever the package is built."),
)


def _execution_findings(rel: str, path: str, text: str | None) -> list[Finding]:
    """Findings that come from what a file is: its name and place say it would run."""
    name = rel.rsplit("/", 1)[-1]
    lower = name.lower()
    found: list[Finding] = []

    def flag(severity: str, rule: str, message: str, line: int = 0) -> None:
        found.append(Finding(severity, rule, path, line, message))

    if _GIT_HOOK.search(rel):
        if not name.endswith(".sample"):
            flag(BLOCK, "execute.git_hook",
                 "A git hook: git runs it automatically on commits, checkouts or merges in this repository.")
        return found
    if _HOOK_MANAGERS.search(rel):
        flag(WARN, "execute.git_hook",
             "A hook-manager script (husky or a hooks directory): once installed as a git hook it runs on every commit.")
    if name == ".pre-commit-config.yaml":
        flag(WARN, "execute.git_hook",
             "pre-commit configuration: once installed, it fetches and runs the listed hooks on every commit.")
    if text is not None and _GIT_CONFIG.search(rel):
        line = _line_of(text, _GIT_CONFIG_COMMANDS)
        if line:
            flag(BLOCK, "execute.git_config",
                 "Git configuration naming a program (fsmonitor, hooksPath, sshCommand, askpass or a "
                 "clean/smudge filter) that git runs during ordinary commands such as status.", line)
    if text is not None and name == "package.json":
        found.extend(_lifecycle_findings(path, text, "package.json", "npm, yarn and pnpm run", _NPM_SCRIPTS))
    if text is not None and name == "composer.json":
        found.extend(_lifecycle_findings(path, text, "composer.json", "Composer runs", _COMPOSER_SCRIPTS))
    if name in _BUILD_SCRIPTS:
        severity, message = _BUILD_SCRIPTS[name]
        flag(severity, "execute.build", message)
    if text is not None and name == "pyproject.toml":
        for pattern, message in _PYPROJECT_HOOKS:
            line = _line_of(text, pattern)
            if line:
                flag(BLOCK, "execute.build", message, line)
    if name in ("sitecustomize.py", "usercustomize.py"):
        flag(BLOCK, "execute.startup",
             f"{name}: Python imports it automatically at start-up whenever it is on the path.")
    if lower.endswith(".pth"):
        imports = _line_of(text, r"(?m)^[ \t]*import[ \t]") if text is not None else 0
        flag(BLOCK if imports or text is None else WARN, "execute.startup",
             "A .pth file: installed into site-packages, its 'import' lines run every time Python starts.",
             imports)
    if lower in ("makefile", "gnumakefile") or lower.endswith(".mk"):
        flag(WARN, "execute.makefile", "A Makefile: its recipes are shell commands that run when someone types make.")
    if lower.endswith(_SCRIPT_SUFFIXES) or (text is not None and text.startswith("#!")):
        flag(WARN, "execute.script",
             "An executable script: it runs with the user's rights if it is started or double-clicked.")
    if _HARNESS_SETTINGS.search(rel):
        found.extend(_harness_findings(rel, path, text))
    if text is not None and lower.endswith(".json") and (_MCP_FILES.search(rel) or '"mcpServers"' in text):
        found.extend(_mcp_findings(path, text, _MCP_FILES.search(rel) is not None))
    if text is not None and lower.endswith(".ipynb"):
        found.extend(_notebook_findings(path, text))
    if _CI_FILES.search(rel):
        flag(WARN, "execute.ci",
             "A CI workflow: its commands run on a build server whenever the repository is pushed "
             "or receives a pull request.")
    if text is not None and name in ("devcontainer.json", ".devcontainer.json"):
        for key in _present_keys(text, _DEVCONTAINER_COMMANDS):
            where = " on the host machine itself, outside the container" if key == "initializeCommand" else ""
            flag(BLOCK, "execute.devcontainer",
                 f"Sets '{key}', which dev-container tools run automatically{where} when this folder is opened.",
                 _line_of(text, rf'"{key}"\s*:'))
    if text is not None and _VSCODE_TASKS.search(rel):
        line = _line_of(text, _AUTO_TASK)
        if line:
            flag(BLOCK, "execute.editor_task",
                 "A VS Code task set to run automatically when the folder is opened (runOn: folderOpen).", line)
    return found


def _lifecycle_findings(path: str, text: str, manifest: str, runner: str, table: dict) -> list[Finding]:
    data = _load_json(text)
    scripts = _dig(data, "scripts")
    if isinstance(scripts, dict):
        declared = set(scripts)
    elif data is None:
        declared = set(_JSON_KEY.findall(text))  # unparseable: any key of that name counts
    else:
        declared = set()
    found = []
    for script, (severity, when) in table.items():
        if script in declared:
            found.append(Finding(
                severity, "execute.install_script", path, _line_of(text, rf'"{re.escape(script)}"\s*:'),
                f"{manifest} declares a '{script}' script, which {runner} automatically {when}, "
                "with the rights of whoever runs it.",
            ))
    return found


def _harness_findings(rel: str, path: str, text: str | None) -> list[Finding]:
    found = [Finding(
        WARN, "execute.agent_settings", path, 0,
        "Agent-harness settings: an AI agent started in this directory would load this file as its "
        "own configuration.",
    )]
    if text is None:
        return found
    if rel.endswith(".toml"):
        data = _load_toml(text)
        keys = [key for key in ("hooks", "notify", "mcp_servers") if _dig(data, key)]
    else:
        keys = _present_keys(text, _HARNESS_COMMAND_KEYS)
    for key in keys:
        found.append(Finding(
            BLOCK, "execute.agent_hook", path, _line_of(text, rf'(?m)"{key}"\s*:|^\[?{key}\b'),
            f"Sets '{key}', which makes the agent harness run commands or start servers as soon as "
            "it loads this file.",
        ))
    if not rel.endswith(".toml") and _present_keys(text, ("permissions",)):
        found.append(Finding(
            WARN, "execute.agent_permissions", path, _line_of(text, r'"permissions"\s*:'),
            "Grants the agent tool permissions, widening what it may do without asking.",
        ))
    return found


def _mcp_findings(path: str, text: str, mcp_file: bool) -> list[Finding]:
    data = _load_json(text)
    if data is None:
        launched = len(_MCP_COMMAND.findall(text))
    else:
        launched = 0
        for key in (("mcpServers", "servers", "mcp_servers") if mcp_file else ("mcpServers",)):
            servers = _dig(data, key)
            if isinstance(servers, dict):
                launched += sum(1 for server in servers.values() if _dig(server, "command"))
    if not launched:
        return []
    return [Finding(
        BLOCK, "execute.mcp", path, _line_of(text, r'"(?:mcpServers|servers|mcp_servers)"\s*:'),
        f"Declares {launched} MCP server(s) started by a local command, which an agent harness "
        "launches with the user's rights as soon as it loads this configuration.",
    )]


def _notebook_findings(path: str, text: str) -> list[Finding]:
    cells = _dig(_load_json(text), "cells")
    if not isinstance(cells, list):
        return []
    code = [cell for cell in cells if _dig(cell, "cell_type") == "code" and _dig(cell, "source")]
    found: list[Finding] = []
    if code:
        found.append(Finding(
            WARN, "execute.notebook", path, 0,
            f"A notebook with {len(code)} code cell(s), which run in a live kernel when the notebook "
            "is executed.",
        ))
    for cell in code:
        outputs = _dig(cell, "outputs")
        for output in outputs if isinstance(outputs, list) else []:
            data = _dig(output, "data")
            if isinstance(data, dict) and (
                "application/javascript" in data or "<script" in str(data.get("text/html", "")).lower()
            ):
                found.append(Finding(
                    BLOCK, "execute.notebook_script", path, 0,
                    "A stored cell output carries JavaScript, which notebook viewers can run as soon "
                    "as the notebook is opened.",
                ))
                return found
    return found


def _load_json(text: str) -> object:
    try:
        return json.loads(text)
    except (ValueError, RecursionError):
        return None


def _load_toml(text: str) -> object:
    try:
        return tomllib.loads(text)
    except (ValueError, RecursionError):
        return None


def _dig(data: object, *keys: str) -> object:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _present_keys(text: str, keys: tuple[str, ...]) -> list[str]:
    """Top-level keys with a value. Files that allow comments (devcontainer.json, VS Code's)
    are not strict JSON, so an unparseable file is searched for the key names instead."""
    data = _load_json(text)
    if isinstance(data, dict):
        return [key for key in keys if data.get(key)]
    return [key for key in keys if re.search(rf'"{re.escape(key)}"\s*:', text)]


# --- licence ------------------------------------------------------------------------------

_PROPRIETARY = "LicenseRef-Proprietary"
_COMMONS_CLAUSE = "LicenseRef-Commons-Clause"
_KNOWN_LICENCES = (
    "0BSD", "AGPL-3.0-only", "AGPL-3.0-or-later", "Apache-1.1", "Apache-2.0", "Artistic-2.0",
    "BSD-2-Clause", "BSD-3-Clause", "BSL-1.0", "BUSL-1.1", "CC-BY-3.0", "CC-BY-4.0",
    "CC-BY-NC-3.0", "CC-BY-NC-4.0", "CC-BY-NC-ND-3.0", "CC-BY-NC-ND-4.0", "CC-BY-NC-SA-3.0",
    "CC-BY-NC-SA-4.0", "CC-BY-ND-3.0", "CC-BY-ND-4.0", "CC-BY-SA-3.0", "CC-BY-SA-4.0", "CC0-1.0",
    "Elastic-2.0", "EPL-1.0", "EPL-2.0", "GPL-2.0-only", "GPL-2.0-or-later", "GPL-3.0-only",
    "GPL-3.0-or-later", "ISC", "LGPL-2.0-only", "LGPL-2.0-or-later", "LGPL-2.1-only",
    "LGPL-2.1-or-later", "LGPL-3.0-only", "LGPL-3.0-or-later", "MIT", "MIT-0", "MPL-2.0",
    "OFL-1.1", "PolyForm-Noncommercial-1.0.0", "PolyForm-Strict-1.0.0", "PSF-2.0", "Python-2.0",
    "SSPL-1.0", "Unlicense", "WTFPL", "Zlib", _PROPRIETARY, _COMMONS_CLAUSE,
)
_ALIASES = {spdx.lower(): spdx for spdx in _KNOWN_LICENCES}
_ALIASES.update({
    "mit license": "MIT", "the mit license": "MIT", "expat": "MIT",
    "apache 2.0": "Apache-2.0", "apache 2": "Apache-2.0", "apache-2": "Apache-2.0", "apache2": "Apache-2.0",
    "apache license 2.0": "Apache-2.0", "apache license, version 2.0": "Apache-2.0",
    "apache software license": "Apache-2.0",
    "bsd-3": "BSD-3-Clause", "bsd 3-clause": "BSD-3-Clause", "new bsd": "BSD-3-Clause",
    "bsd-2": "BSD-2-Clause", "bsd 2-clause": "BSD-2-Clause", "simplified bsd": "BSD-2-Clause",
    "gpl-2.0": "GPL-2.0-only", "gpl-2.0+": "GPL-2.0-or-later", "gplv2": "GPL-2.0-only",
    "gpl-3.0": "GPL-3.0-only", "gpl-3.0+": "GPL-3.0-or-later", "gplv3": "GPL-3.0-only",
    "lgpl-2.1": "LGPL-2.1-only", "lgpl-2.1+": "LGPL-2.1-or-later",
    "lgpl-3.0": "LGPL-3.0-only", "lgpl-3.0+": "LGPL-3.0-or-later",
    "agpl-3.0": "AGPL-3.0-only", "agpl-3.0+": "AGPL-3.0-or-later", "agplv3": "AGPL-3.0-only",
    "mpl 2.0": "MPL-2.0", "cc0": "CC0-1.0",
    # npm's word for "no licence granted" — not the Unlicense, which is its opposite.
    "unlicensed": _PROPRIETARY, "proprietary": _PROPRIETARY, "commercial": _PROPRIETARY,
    "all rights reserved": _PROPRIETARY,
})
# Checked in order, against the text lowercased with its whitespace collapsed: the more
# specific of two texts that share wording comes first (AGPL and LGPL before GPL, say).
_LICENCE_TEXTS = tuple((spdx, re.compile(pattern)) for spdx, pattern in (
    (_COMMONS_CLAUSE, r"commons clause"),
    ("BUSL-1.1", r"business source license"),
    ("SSPL-1.0", r"server side public license"),
    ("Elastic-2.0", r"elastic license 2\.0|elastic license, version 2"),
    ("PolyForm-Noncommercial-1.0.0", r"polyform noncommercial license"),
    ("PolyForm-Strict-1.0.0", r"polyform strict license"),
    ("CC-BY-NC-ND-4.0", r"attribution-noncommercial-noderivatives 4\.0"),
    ("CC-BY-NC-SA-4.0", r"attribution-noncommercial-sharealike 4\.0"),
    ("CC-BY-NC-4.0", r"attribution-noncommercial 4\.0"),
    ("CC-BY-ND-4.0", r"attribution-noderivatives 4\.0"),
    ("CC-BY-SA-4.0", r"attribution-sharealike 4\.0"),
    ("CC-BY-4.0", r"attribution 4\.0 international"),
    ("CC0-1.0", r"cc0 1\.0 universal"),
    ("AGPL-3.0-only", r"gnu affero general public license.*version 3"),
    ("LGPL-3.0-only", r"gnu lesser general public license.*version 3"),
    ("LGPL-2.1-only", r"gnu lesser general public license.*version 2\.1"),
    ("LGPL-2.0-only", r"gnu library general public license"),
    ("GPL-3.0-only", r"gnu general public license.*version 3"),
    ("GPL-2.0-only", r"gnu general public license.*version 2"),
    ("MPL-2.0", r"mozilla public license,? (?:version|v\.?) ?2\.0"),
    ("EPL-2.0", r"eclipse public license(?: -)? v(?:ersion)? ?2\.0"),
    ("EPL-1.0", r"eclipse public license(?: -)? v(?:ersion)? ?1\.0"),
    ("Apache-2.0", r"apache license,? version 2\.0"),
    ("BSL-1.0", r"boost software license - version 1\.0"),
    ("Unlicense", r"this is free and unencumbered software released into the public domain"),
    ("ISC", r"distribute this software for any purpose with or without fee is hereby granted, provided that"),
    ("0BSD", r"distribute this software for any purpose with or without fee is hereby granted"),
    ("MIT", r"permission is hereby granted, free of charge, to any person obtaining a copy"),
    ("BSD-3-Clause", r"redistribution and use in source and binary forms.*neither the name"),
    ("BSD-2-Clause", r"redistribution and use in source and binary forms"),
    ("Zlib", r"altered source versions must be plainly marked as such"),
))
_PROPRIETARY_TEXT = re.compile(
    r"all rights reserved|proprietary|confidential|may not be (?:copied|reproduced|distributed|modified|used)"
    r"|no licen[cs]e is granted"
)
_FORBIDS_REUSE = frozenset((
    _PROPRIETARY, _COMMONS_CLAUSE, "PolyForm-Noncommercial-1.0.0", "PolyForm-Strict-1.0.0", "BUSL-1.1",
))
_CONDITIONAL = frozenset(("MPL-2.0", "SSPL-1.0", "Elastic-2.0"))
_LICENCE_FILE = re.compile(r"(?:licen[cs]e|copying|unlicense)(?:[-_][\w.-]+)?(?:\.(?:md|txt|rst|markdown))?", re.I)
_EXPRESSION_TOKEN = re.compile(r"[()]|[^\s()]+")
_OPERATORS = ("AND", "OR", "WITH")
_EXCEPTION = re.compile(r"[A-Za-z0-9.+-]*exception[A-Za-z0-9.+-]*", re.I)
_FRONT_MATTER_BLOCK = re.compile(r"---[ \t]*\r?\n(.*?)^---[ \t\r]*$", re.S | re.M)


def identify_licence_text(text: str) -> str:
    """The SPDX identifier for a licence file's text, or 'unknown'."""
    flat = " ".join(text.lower().split())
    for spdx, pattern in _LICENCE_TEXTS:
        if pattern.search(flat):
            return spdx
    return _PROPRIETARY if _PROPRIETARY_TEXT.search(flat) else UNKNOWN


def normalise_licence(value: str) -> str:
    """A licence name or SPDX expression from a manifest, as an SPDX expression, or 'unknown'
    if any part of it is not recognised."""
    text = " ".join(str(value).split())
    if not text:
        return UNKNOWN
    alias = _ALIASES.get(text.lower())
    if alias:
        return alias
    out: list[str] = []
    after_with = False
    for token in _EXPRESSION_TOKEN.findall(text):
        upper = token.upper()
        expecting_exception, after_with = after_with, False
        if token in ("(", ")"):
            out.append(token)
        elif upper in _OPERATORS:
            out.append(upper)
            after_with = upper == "WITH"
        elif expecting_exception:
            if not _EXCEPTION.fullmatch(token):
                return UNKNOWN
            out.append(token)
        else:
            canonical = _ALIASES.get(token.lower())
            if canonical is None:
                return UNKNOWN
            out.append(canonical)
    return " ".join(out).replace("( ", "(").replace(" )", ")")


def _licence_ids(expression: str) -> list[str]:
    return [
        token for token in _EXPRESSION_TOKEN.findall(expression)
        if token not in ("(", ")") and token not in _OPERATORS and not _EXCEPTION.fullmatch(token)
    ]


def _id_rank(spdx: str) -> int:
    if spdx in _FORBIDS_REUSE or spdx.startswith(("CC-BY-NC", "CC-BY-ND")):
        return 2
    if spdx in _CONDITIONAL or spdx.startswith(("GPL-", "AGPL-", "LGPL-", "CC-BY-SA-", "EPL-")):
        return 1
    return 0


def _licence_rank(expression: str) -> int:
    """0 permissive, 1 conditional, 2 forbids reuse. A choice (OR) is as open as its most open
    option; a combination (AND) as closed as its most closed part. Anything nested in brackets
    is judged by its most closed part, which is never wrong in the direction that matters."""
    if expression == UNKNOWN:
        return 1
    branches = [expression] if "(" in expression else expression.split(" OR ")
    return min(max((_id_rank(spdx) for spdx in _licence_ids(branch)), default=1) for branch in branches)


def _licence_finding(path: str, line: int, expression: str, source: str) -> Finding:
    if expression == UNKNOWN:
        return Finding(
            WARN, "licence.unknown", path, line,
            f"The licence in this {source} is not one the scanner recognises, so it is 'unknown': "
            "its terms need reading by a person before anything is reused.",
        )
    rank = _licence_rank(expression)
    if rank == 2:
        return Finding(
            BLOCK, "licence.forbids_reuse", path, line,
            f"Licence {expression} (from this {source}) forbids reuse: its terms are proprietary, "
            "non-commercial or no-derivatives, so this must not be digested into reusable knowledge "
            "without the owner's decision.",
        )
    if rank == 1:
        return Finding(
            WARN, "licence.conditional", path, line,
            f"Licence {expression} (from this {source}) allows reuse only on conditions (copyleft, "
            "share-alike or source-available terms) that travel with anything built from it.",
        )
    return Finding(
        INFO, "licence.permissive", path, line,
        f"Licence {expression} (from this {source}) is permissive: reuse is allowed with its notice kept.",
    )


def _licence_findings(rel: str, path: str, text: str | None) -> tuple[list[Finding], bool]:
    """The licence this file declares, if it is a licence file or a manifest that names one, and
    whether it is a licence source at all."""
    name = rel.rsplit("/", 1)[-1]
    if _LICENCE_FILE.fullmatch(name):
        expression = identify_licence_text(text) if text is not None else UNKNOWN
        return [_licence_finding(path, 0, expression, "licence file")], True
    if text is None:
        return [], False
    declared = _declared_licence(name, text)
    if declared is None:
        return [], False
    expression, line = declared
    return [_licence_finding(path, line, expression, name)], True


def _declared_licence(name: str, text: str) -> tuple[str, int] | None:
    if name in ("package.json", "composer.json"):
        data = _load_json(text)
        value = _dig(data, "license") or _dig(data, "licenses")
        line_pattern = r'"licen[cs]es?"\s*:'
    elif name in ("pyproject.toml", "Cargo.toml"):
        data = _load_toml(text)
        value = (
            _dig(data, "project", "license") or _dig(data, "tool", "poetry", "license")
            or _dig(data, "package", "license")
        )
        line_pattern = r"(?m)^[ \t]*license[ \t]*="
    elif name == "setup.cfg":
        parser = configparser.ConfigParser(interpolation=None)
        try:
            parser.read_string(text)
        except configparser.Error:
            return None
        value = parser.get("metadata", "license", fallback=None)
        line_pattern = r"(?m)^[ \t]*license[ \t]*[=:]"
    elif name == "SKILL.md":
        value = _front_matter_field(text, "license")
        line_pattern = r"(?m)^license[ \t]*:"
    else:
        return None
    expression = _licence_expression(value)
    # A skill's licence line is often a pointer ("terms in LICENSE.txt"), not a licence.
    if expression is None or (name == "SKILL.md" and expression == UNKNOWN):
        return None
    return expression, _line_of(text, line_pattern)


def _licence_expression(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("type") or value.get("text")
    if isinstance(value, list):
        parts = [part for part in (_licence_expression(item) for item in value) if part]
        if not parts:
            return None
        if UNKNOWN in parts:
            return UNKNOWN
        return " OR ".join(f"({part})" if " " in part else part for part in parts)
    if not isinstance(value, str) or not value.strip():
        return None
    if value.strip().upper().startswith("SEE LICEN"):
        return None  # a pointer to the licence file, which is read on its own
    if len(value) > 200:
        return identify_licence_text(value)  # the whole licence text pasted into the manifest
    return normalise_licence(value)


def _front_matter_field(text: str, field: str) -> str | None:
    block = _FRONT_MATTER_BLOCK.match(text.lstrip("\ufeff"))
    if not block:
        return None
    match = re.search(rf"(?m)^{field}[ \t]*:[ \t]*(.+?)[ \t\r]*$", block.group(1))
    return match.group(1).strip("'\"") if match else None
