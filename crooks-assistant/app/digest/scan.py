"""The Knowledge Digester's quarantine scanner: what an artifact would do to us if we trusted it.

An artifact — a repository, an agent skill, a document set, an API spec, a theme — arrives in a
quarantined directory and is read here before anything else touches it. Reading is all this
module does: files are opened as bytes, never imported, executed, installed, rendered or
followed out of the tree. Symbolic links are reported and not followed; hard-linked files, whose
data may belong to a file outside the tree, are reported and not read; pipes, sockets and
devices are reported and not opened; binaries are skipped; and limits on file size, on the
number of entries walked and on the bytes read in all mean a hostile or merely enormous
artifact cannot stall the scan. What could not be read is never passed as clean.

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
import functools
import hashlib
import html
import json
import os
import re
import stat
import tomllib
import unicodedata
from collections import deque
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, replace
from typing import NamedTuple

INFO = "info"
WARN = "warn"
BLOCK = "block"
_RANK = {BLOCK: 0, WARN: 1, INFO: 2}

UNKNOWN = "unknown"

# Bounds on one scan. Entries counts files, directories and links alike, so a tree of a
# million empty directories stops as surely as a million files; total bytes bounds what is read
# across all of them, so five thousand files each just under the size limit stop too.
MAX_FILES = 5000
MAX_FILE_BYTES = 1_000_000
MAX_TOTAL_BYTES = 32_000_000
_BINARY_PROBE = 8192
_MAX_DECODE_DEPTH = 3
_MAX_PER_RULE = 25
# Credential values remembered so that no path repeats one. Past this many the scanner cannot
# check every path against every value cheaply, so it withholds the paths instead.
_MAX_EXPOSED = 4096
_WITHHELD = "[withheld]"


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
    max_total_bytes: int = MAX_TOTAL_BYTES,
) -> list[Finding]:
    """Every finding for the quarantined directory at ``root``, most severe first, then by path."""
    base = os.fspath(root)
    if not os.path.isdir(base):
        raise NotADirectoryError(base)
    findings: list[Finding] = []
    exposed = _Exposed()  # credential values found, so no path can repeat one
    budget = _Budget(max_total_bytes)
    seen: dict[bytes, list[Finding]] = {}  # content findings by the digest of the bytes read
    licensed = False
    for entry in _walk(base, max_files):
        path = _display(entry.rel)
        if entry.kind == "limit":
            findings.append(Finding(
                WARN, "scan.limit", path, 0,
                f"Stopped after {max_files} files and directories: the rest of the artifact was "
                "not scanned, so its contents are unknown.",
            ))
        elif entry.kind == "unreadable":
            findings.append(_unreadable(path))
        elif entry.kind == "link":
            findings.append(_link_finding(base, entry, path))
        elif entry.kind == "other":
            findings.append(_special(path))
        else:
            found, has_licence = _scan_file(base, entry, path, max_file_bytes, budget, exposed, seen)
            findings.extend(found)
            # Only a licence at the top of the artifact is the artifact's: one further down belongs
            # to whatever is vendored or bundled there.
            licensed = licensed or (has_licence and "/" not in entry.rel)
    if budget.skipped:
        findings.append(Finding(
            WARN, "scan.limit", budget.first_skipped, 0,
            f"Stopped reading after {max_total_bytes} bytes: {budget.skipped} further file(s), from "
            "this one on, were not read, so their contents are unknown.",
        ))
    if not licensed:
        findings.append(Finding(
            WARN, "licence.unknown", ".", 0,
            "No licence found at the top of the artifact: no LICENSE or COPYING file and no licence "
            "in a package manifest there (one further down covers only what is bundled with it). "
            "The licence is 'unknown', and without one nothing grants the right to reuse it.",
        ))
    findings = _withhold(findings, exposed)
    return sorted(set(findings), key=_order)


class _Exposed:
    """Credential values found anywhere in the tree, so that no path can repeat one — a value a
    name does not give away by its shape, such as a password."""

    def __init__(self) -> None:
        self.values: set[str] = set()
        self.overflowed = False

    def add(self, value: str) -> None:
        if value in self.values:
            return
        if len(self.values) >= _MAX_EXPOSED:
            self.overflowed = True
        else:
            self.values.add(value)

    def update(self, values: Iterable[str]) -> None:
        for value in values:
            self.add(value)


def _withhold(findings: list[Finding], exposed: _Exposed) -> list[Finding]:
    """The findings with every credential value found taken out of their paths. Each distinct
    path is checked once against at most ``_MAX_EXPOSED`` values, longest first and then in
    order, so the result never depends on the order a set happens to iterate in. Past that many
    values, paths are withheld altogether rather than checked against some of them: each distinct
    path becomes a numbered placeholder, so findings about one file still read together."""
    if exposed.overflowed:
        number = {path: index for index, path in enumerate(sorted({f.path for f in findings}), 1)}
        return [replace(f, path=f"{_WITHHELD[:-1]} {number[f.path]:05}]") for f in findings] + [Finding(
            WARN, "scan.withheld", _WITHHELD, 0,
            f"More than {_MAX_EXPOSED} distinct credential values were found, so every path is "
            "withheld: the scanner cannot vouch that none of them repeats one.",
        )]
    if not exposed.values:
        return findings
    values = sorted(exposed.values, key=lambda value: (-len(value), value))
    shown: dict[str, str] = {}
    out: list[Finding] = []
    for finding in findings:
        path = shown.get(finding.path)
        if path is None:
            path = finding.path
            for value in values:
                if value in path:
                    path = path.replace(value, "[redacted]")
            shown[finding.path] = path
        out.append(finding if path == finding.path else replace(finding, path=path))
    return out


class _Budget:
    """Bytes read so far against the limit on the whole scan."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.spent = 0
        self.skipped = 0
        self.first_skipped = ""

    def exhausted(self, path: str) -> bool:
        if self.spent < self.limit:
            return False
        if not self.skipped:
            self.first_skipped = path
        self.skipped += 1
        return True


def _order(finding: Finding) -> tuple:
    return (_RANK.get(finding.severity, 3), finding.path, finding.line, finding.rule, finding.message)


# --- walking the tree ---------------------------------------------------------------------


class _Entry(NamedTuple):
    """One entry of the tree. ``parent`` is an open descriptor for the directory it was listed in
    (valid only until the walk moves on), ``ident`` the (device, inode) it had when listed."""

    kind: str
    rel: str
    parent: int | None = None
    name: str = ""
    ident: tuple[int, int] | None = None


# Directories are opened and listed through descriptors, and files opened relative to the
# descriptor of the directory they were listed in, so no path is resolved twice: a directory
# swapped for a link to somewhere else between being listed and being read is caught by its
# inode, and a file is never reached through a path at all.
_FD_WALK = (
    os.scandir in os.supports_fd and os.open in os.supports_dir_fd and hasattr(os, "O_DIRECTORY")
)
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
_FILE_FLAGS = (
    os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
)
# Inside a git directory only what git runs from is read: its config files and hooks, and the
# same again for each submodule's git directory under modules/. Its object store is not the
# artifact, and neither are these.
_GIT_INTERNALS = frozenset(("objects", "refs", "logs", "info", "branches", "lfs", "worktrees", "rr-cache", "svn"))
_GIT_READ = frozenset(("config", "config.worktree"))


class _Moved(OSError):
    """The entry is no longer the one that was listed."""


def _walk(base: str, max_files: int) -> Iterator[_Entry]:
    """Each entry of the tree, breadth first so the top of the artifact — where its licence and
    manifests live — is read before a limit can cut in. Links are never followed."""
    try:
        root = _ident(os.stat(base))
    except OSError:
        yield _Entry("unreadable", ".")
        return
    queue: deque[tuple[str, tuple[int, int] | None, bool]] = deque([("", root, False)])
    seen = 0
    while queue:
        folder, ident, in_git = queue.popleft()
        try:
            fd = _open_dir(base, folder, ident)
        except OSError:
            yield _Entry("unreadable", folder or ".")
            continue
        try:
            try:
                entries = _list(base, folder, fd, max_files)
            except OSError:
                yield _Entry("unreadable", folder or ".")
                continue
            for entry in entries:
                rel = f"{folder}/{entry.name}" if folder else entry.name
                try:
                    kind = _kind(entry)
                    entry_ident = _ident(entry.stat(follow_symlinks=False))
                except OSError:
                    kind, entry_ident = "unreadable", None
                if in_git and not (
                    entry.name in _GIT_READ or (kind == "dir" and entry.name not in _GIT_INTERNALS)
                    or (kind == "link" and entry.name == "hooks")
                ):
                    continue
                seen += 1
                if seen > max_files:
                    yield _Entry("limit", folder or ".")
                    return
                if kind == "dir":
                    # A git directory's hooks are ordinary files to read; anything else in it is
                    # searched only for more of what git runs from.
                    git = entry.name == ".git" or (in_git and entry.name != "hooks")
                    queue.append((rel, entry_ident, git))
                else:
                    yield _Entry(kind, rel, fd, entry.name, entry_ident)
        finally:
            if fd is not None:
                os.close(fd)


def _ident(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _open_dir(base: str, folder: str, ident: tuple[int, int] | None) -> int | None:
    """A descriptor for the directory, checked to be the very one that was listed."""
    path = os.path.join(base, folder) if folder else base
    if not _FD_WALK:
        if ident is not None and _ident(os.lstat(path) if folder else os.stat(path)) != ident:
            raise _Moved(path)
        return None
    fd = os.open(path, _DIR_FLAGS | (getattr(os, "O_NOFOLLOW", 0) if folder else 0))
    try:
        if ident is not None and _ident(os.fstat(fd)) != ident:
            raise _Moved(path)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _list(base: str, folder: str, fd: int | None, max_files: int) -> list[os.DirEntry]:
    entries = []
    with os.scandir(fd if fd is not None else os.path.join(base, folder) if folder else base) as listing:
        for entry in listing:
            entries.append(entry)
            if len(entries) > max_files:
                break
    entries.sort(key=lambda entry: entry.name)
    return entries


def _kind(entry: os.DirEntry) -> str:
    if entry.is_symlink():
        return "link"
    if entry.is_dir(follow_symlinks=False):
        return "dir"
    if entry.is_file(follow_symlinks=False):
        return "file"
    return "other"


def _display(rel: str) -> str:
    """The path as it can be shown: anything shaped like a credential, in any component, is
    replaced by the kind of credential it is, and anything unprintable (a bidi override in a
    file name, say) is written as an escape so the path cannot rearrange the report it appears in."""
    for pattern, slug in _PATH_SECRETS:
        rel = pattern.sub(f"[redacted {slug}]", rel)
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


def _link_finding(base: str, entry: _Entry, path: str) -> Finding:
    rel = entry.rel
    try:
        if entry.parent is not None and os.readlink in os.supports_dir_fd:
            target = os.readlink(entry.name, dir_fd=entry.parent)
        else:
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


class _HardLinked(OSError):
    """The file has more than one name, and the others may be outside the artifact."""


# Native executables: ELF, PE (a DOS stub followed by binary header fields) and Mach-O.
_NATIVE = (
    (b"\x7fELF", "ELF"), (b"\xfe\xed\xfa\xce", "Mach-O"), (b"\xfe\xed\xfa\xcf", "Mach-O"),
    (b"\xce\xfa\xed\xfe", "Mach-O"), (b"\xcf\xfa\xed\xfe", "Mach-O"),
)


def _scan_file(
    base: str, entry: _Entry, path: str, max_bytes: int, budget: _Budget, exposed: _Exposed,
    seen: dict[bytes, list[Finding]] | None = None,
) -> tuple[list[Finding], bool]:
    rel = entry.rel
    found: list[Finding] = []
    if any(_is_hidden_char(ch) for ch in rel):
        found.append(Finding(
            BLOCK, "deceptive.filename", path, 0,
            "The file name contains invisible or direction-changing characters, so it can "
            "display as a different name from the one it has.",
        ))
    text: str | None = None
    if not budget.exhausted(path):
        try:
            data, oversized = _read(base, entry, max_bytes, rel)
        except _NotRegular:
            return [*found, _special(path)], False
        except _HardLinked:
            found.append(Finding(
                WARN, "scan.hardlink", path, 0,
                "Hard-linked: this file's data also has another name, which may be outside the "
                "artifact, so it was not read and its contents are unknown.",
            ))
        except OSError:
            found.append(_unreadable(path))
        else:
            budget.spent += len(data)
            found.extend(_binary_findings(rel, path, data))
            if _looks_binary(data, rel):
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
        # The same bytes give the same content findings wherever they are (vendored copies,
        # templates repeated per folder), so they are worked out once and given each path.
        key = hashlib.sha256(data).digest() + (b"source" if _is_source(rel) else b"")
        if seen is not None and key in seen:
            content = [replace(finding, path=path) for finding in seen[key]]
        else:
            content = _content_findings(path, text, exposed)
            if seen is not None:
                seen[key] = content
        found.extend(_as_fixture(content) if _is_test_source(rel) else content)
    return found, has_licence


# --- test source ------------------------------------------------------------------------------
#
# In a Python or Go test file, an instruction to an AI, a credential or a deceptive character is
# almost always a fixture: it is how a scanner, a redactor or a prompt guard is tested (CLIVE's
# own tests are full of them). There it is reported as a warning, not a block. That is safe only
# because nothing of such a file's text reaches a Unit: the code adapter reads a Python test file
# for its test names and imports alone, and no adapter reads Go. JavaScript tests are not
# included, because the code adapter keeps their test titles, which are strings. A file name
# that deceives is judged as ever: it is not the file's content.
_TEST_SOURCE = re.compile(r"(?:^|/)(?:test_[^/]*\.py|[^/]*_test\.py|[^/]*_test\.go)$")
_FIXTURE_FAMILIES = ("injection.", "deceptive.", "secret.")
_FIXTURE_NOTE = (
    " It is in test source code, where such text is almost always a test fixture, and nothing of "
    "a test file's text is read into a Unit, so it is reported rather than blocking."
)


def _is_test_source(rel: str) -> bool:
    return bool(_TEST_SOURCE.search(rel))


def _as_fixture(found: list[Finding]) -> list[Finding]:
    return [
        replace(finding, severity=WARN, message=finding.message + _FIXTURE_NOTE)
        if finding.severity == BLOCK and finding.rule.startswith(_FIXTURE_FAMILIES) else finding
        for finding in found
    ]


def _binary_findings(rel: str, path: str, data: bytes) -> list[Finding]:
    found = []
    for magic, kind in _NATIVE:
        if data.startswith(magic):
            found.append(Finding(
                WARN, "execute.binary", path, 0,
                f"A native {kind} executable: it runs with the user's rights if it is started.",
            ))
            break
    if data.startswith(b"MZ") and len(data) >= 64 and b"\x00" in data[2:64]:
        found.append(Finding(
            WARN, "execute.binary", path, 0,
            "A native Windows (PE) executable: it runs with the user's rights if it is started.",
        ))
    masked = not data.startswith((b"\xff\xfe", b"\xfe\xff")) and (
        b"\x00" in data or data.startswith(_BINARY_MAGIC)
    )
    if masked and not _looks_binary(data, rel):
        found.append(Finding(
            WARN, "deceptive.binary_mask", path, 0,
            "Text disguised as binary (NUL bytes, or a binary file signature at the start), so "
            "tools that sniff content hide it from review while a model reading it still sees the "
            "text. It was scanned as text.",
        ))
    return found


def _read(base: str, entry: _Entry, max_bytes: int, rel: str = "") -> tuple[bytes, bool]:
    """The file's bytes (only a probe's worth if it is over the limit, or if the probe is
    binary: whether a file is binary is decided on its probe alone, so reading the rest of a
    binary would only spend the scan's byte budget) and whether it is over the limit. Opened
    relative to the directory it was listed in, without following a link and without blocking,
    and checked to be the regular file that was listed, with no other name, before a byte is
    read: a link, a pipe or another file swapped in after the walk cannot be read through."""
    if entry.parent is not None:
        fd = os.open(entry.name, _FILE_FLAGS, dir_fd=entry.parent)
    else:
        fd = os.open(os.path.join(base, entry.rel), _FILE_FLAGS)
    chunks: list[bytes] = []
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise _NotRegular(entry.rel)
        if entry.ident is not None and _ident(info) != entry.ident:
            raise _Moved(entry.rel)
        if info.st_nlink > 1:
            raise _HardLinked(entry.rel)
        oversized = info.st_size > max_bytes
        remaining = _BINARY_PROBE if oversized else max_bytes + 1
        probed = 0
        while remaining > 0:
            want = min(remaining, 1 << 16)
            if probed < _BINARY_PROBE:
                want = min(want, _BINARY_PROBE - probed)
            chunk = os.read(fd, want)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
            if probed < _BINARY_PROBE:
                probed += len(chunk)
                if probed >= _BINARY_PROBE and _looks_binary(b"".join(chunks), rel):
                    break
    finally:
        os.close(fd)
    data = b"".join(chunks)
    return data, oversized or len(data) > max_bytes


# Signatures of binary formats. They decide only for a file whose name does not say it is text:
# a README.md that starts with a PNG signature is text dressed up to be skipped.
_BINARY_MAGIC = (
    b"\x7fELF", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe", b"\x89PNG", b"\xff\xd8\xff", b"GIF87a", b"GIF89a", b"PK\x03\x04", b"PK\x05\x06",
    b"\x1f\x8b", b"%PDF-", b"\x00asm", b"SQLite format 3\x00", b"7z\xbc\xaf", b"Rar!\x1a", b"\xfd7zXZ",
    b"wOFF", b"wOF2", b"OggS", b"fLaC", b"\x1aE\xdf\xa3",
)
_TEXT_SUFFIXES = frozenset((
    "md markdown mdx txt text rst adoc org tex json jsonc json5 jsonl ndjson yaml yml toml ini cfg conf env "
    "properties py pyi js mjs cjs ts mts cts tsx jsx sh bash zsh fish ps1 psm1 bat cmd html htm xhtml xml svg "
    "css scss sass less csv tsv sql rb php go rs java kt kts c h cc cpp hpp cs swift lua pl pm r ipynb lock "
    "gradle tf hcl vue svelte dart scala ex exs erl hs clj el vim nix"
).split())
_CONTROL = re.compile(r"[\x01-\x08\x0e-\x1a\x1c-\x1f\x7f]")


def _looks_binary(data: bytes, rel: str = "") -> bool:
    """Whether the bytes are something other than text. NUL bytes alone do not make a file
    binary — a single one would otherwise hide a whole text file from every other rule — so
    they are set aside and the rest is judged as text."""
    head = data[:_BINARY_PROBE]
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return False
    name = rel.rsplit("/", 1)[-1]
    suffix = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if head.startswith(_BINARY_MAGIC) and suffix not in _TEXT_SUFFIXES:
        return True
    stripped = head.replace(b"\x00", b"")
    if not stripped:
        return bool(head)
    decoded = stripped.decode("utf-8", errors="replace")
    bad = decoded.count("\ufffd") + len(_CONTROL.findall(decoded))
    return bad > max(4, len(decoded) // 10)


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    return data.replace(b"\x00", b"").decode("utf-8", errors="replace")


# Source code, where a line "name: value" is a typed name or an argument, not a chat turn.
_SOURCE_SUFFIXES = frozenset((
    "py pyi js mjs cjs ts tsx jsx mts cts swift kt kts java go rs rb php cs scala c h cc cpp hpp "
    "m mm dart lua ex exs vue svelte"
).split())


def _is_source(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return "." in name and name.rsplit(".", 1)[-1].lower() in _SOURCE_SUFFIXES


def _content_findings(path: str, text: str, exposed: _Exposed) -> list[Finding]:
    # Characters are judged on the text as written; phrases and secrets on the text as a model
    # would read it, with invisible characters gone and tag characters spelled out, so neither
    # can be split or smuggled past the patterns. Both keep every newline, so lines agree.
    clean = _clean(text)
    starts = _line_starts(clean)
    found = _character_findings(path, text)
    found.extend(_injection_findings(path, clean, starts, code=_is_source(path)))
    found.extend(_secret_findings(path, clean, starts, exposed))
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
    0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0x2060, 0x2061, 0x2062, 0x2063, 0x2064, 0x2065,
    0xFEFF, 0x180E, 0x061C,
    # Characters that render as nothing but count as letters, so they can stand inside an
    # identifier or split a word: the Hangul fillers, the combining grapheme joiner, the Khmer
    # inherent vowels, Mongolian variation selectors, the deprecated format characters, the
    # interlinear annotation marks and the invisible musical formatting characters.
    0x034F, 0x115F, 0x1160, 0x3164, 0xFFA0, 0x17B4, 0x17B5, 0x180B, 0x180C, 0x180D, 0x180F,
    *range(0x206A, 0x2070), *range(0xFFF9, 0xFFFC), *range(0x1D173, 0x1D17B),
))
_JOINERS = frozenset((0x200C, 0x200D))
_BIDI_CONTROLS = frozenset((*range(0x202A, 0x202F), *range(0x2066, 0x206A)))
_TAG_RUN = re.compile(r"[\U000e0000-\U000e007f]+")
_TAG_CHAR = re.compile(r"[\U000e0000-\U000e007f]")
# A subdivision flag (England, Scotland, Wales): a black flag, a short lower-case region and
# subdivision code in tag letters and digits, and a cancel tag. Anything else in tags is hidden text.
_FLAG = re.compile("\U0001f3f4[\U000e0030-\U000e0039\U000e0061-\U000e007a]{2,7}\U000e007f")
# Variation selectors choose how the character before them is drawn; one after an emoji is
# ordinary. Two or more in a row select nothing, and are how bytes are hidden after a character.
_VARIATION_RUN = re.compile(r"[\ufe00-\ufe0f\U000e0100-\U000e01ef]{2,}")
_INVISIBLE = re.compile(
    "[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\u180e\u061c\u00ad\u034f\u115f\u1160\u3164"
    "\uffa0\u17b4\u17b5\u180b-\u180d\u180f\ufe00-\ufe0f\ufff9-\ufffb\U000e0100-\U000e01ef"
    "\U0001d173-\U0001d17a]"
)
# Control characters (newlines included) and undecodable bytes, as they are replaced inside a
# line: by a space, so a line never gains or loses a break.
_NOISE = re.compile(r"[\x00-\x1f\x7f-\x9f\ufffd]+")
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
    """Text as a model reads it: tag characters become the ASCII they encode, runs of variation
    selectors the bytes they encode, invisible characters go, and compatibility forms (fullwidth
    letters and the like) fold to plain. Every newline is kept, and no new one is made."""
    text = _TAG_RUN.sub(_untag, text)
    text = _VARIATION_RUN.sub(_unvary, text)
    return _NON_ASCII.sub(_fold, _INVISIBLE.sub("", text))


def _untag(match: re.Match[str]) -> str:
    return "".join(chr(ord(ch) - 0xE0000) for ch in match.group() if 0xE0020 <= ord(ch) <= 0xE007E)


def _unvary(match: re.Match[str]) -> str:
    """The bytes a run of variation selectors encodes (VS1–16 are 0–15, VS17–256 are 16–255),
    read as text."""
    data = bytes(ord(ch) - 0xFE00 if ord(ch) <= 0xFE0F else ord(ch) - 0xE0100 + 16 for ch in match.group())
    return _NOISE.sub(" ", data.decode("utf-8", errors="replace"))


_NON_ASCII = re.compile(r"[^\x00-\x7f]+")


def _fold(match: re.Match[str]) -> str:
    """NFKC, but never more than four characters for one: a few characters expand eighteenfold,
    and a file of them would multiply the work of every pattern after."""
    run = match.group()
    folded = unicodedata.normalize("NFKC", run)
    if len(folded) <= 4 * len(run):
        return folded
    return "".join(_fold_char(ch) for ch in run)


@functools.lru_cache(maxsize=4096)
def _fold_char(ch: str) -> str:
    folded = unicodedata.normalize("NFKC", ch)
    return folded if len(folded) <= 4 else ch


def _names(codes: list[int]) -> str:
    return ", ".join(f"U+{code:04X} {unicodedata.name(chr(code), 'unnamed')}" for code in sorted(set(codes)))


def _character_findings(path: str, text: str) -> list[Finding]:
    found: list[Finding] = []
    for number, line in enumerate(text.split("\n"), 1):
        if line.isascii():
            continue
        invisible: list[int] = []
        bidi: list[int] = []
        tags = len(_TAG_CHAR.findall(_FLAG.sub("", line)))
        smuggled = sum(len(run.group()) for run in _VARIATION_RUN.finditer(line))
        for index, ch in enumerate(line):
            code = ord(ch)
            if code < 0x80 or 0xE0000 <= code <= 0xE007F:
                continue
            if code in _BIDI_CONTROLS:
                bidi.append(code)
            elif code in _ZERO_WIDTH:
                if code == 0xFEFF and number == 1 and index == 0:
                    continue  # a byte-order mark
                if code in _JOINERS and _joins(line, index):
                    continue  # joining emoji or a script that needs it
                invisible.append(code)
            elif _is_variation(code) and index and line[index - 1].isascii() and line[index - 1].isalpha():
                invisible.append(code)  # selects nothing: no letter has a variant to select
        if smuggled:
            found.append(Finding(
                BLOCK, "deceptive.variation", path, number,
                f"{smuggled} variation selectors in a row: invisible on screen, and able to encode "
                "hidden bytes that a model can be told to decode.",
            ))
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


def _joins(line: str, index: int) -> bool:
    """Whether the joiner at ``index`` joins two visible characters that are not both ASCII, as
    in an emoji sequence or a script that needs one. A joiner beside another invisible character
    joins nothing: runs of them are how bits are hidden in text."""
    if index == 0 or index + 1 >= len(line):
        return False
    before, after = line[index - 1], line[index + 1]
    if _is_variation(ord(before)) and index >= 2:
        before = line[index - 2]  # an emoji's presentation selector, as in a rainbow flag
    if before.isascii() and after.isascii():
        return False
    return not any(_is_hidden_char(ch) or _is_variation(ord(ch)) for ch in (before, after))


def _is_variation(code: int) -> bool:
    return 0xFE00 <= code <= 0xFE0F or 0xE0100 <= code <= 0xE01EF


# --- instructions aimed at an AI agent ----------------------------------------------------


@dataclass(frozen=True)
class _Phrase:
    name: str
    severity: str
    patterns: tuple[re.Pattern[str], ...]
    explanation: str
    # Patterns (by index) that are only read in prose: in source code, "tool: str = ''" and
    # "ASSISTANT: frozenset(...)" are typed names, not a turn of conversation.
    prose_only: frozenset[int] = frozenset()

    def search(self, text: str) -> re.Match[str] | None:
        for pattern in self.patterns:
            match = pattern.search(text)
            if match:
                return match
        return None

    def finditer(self, text: str, *, code: bool = False) -> Iterator[re.Match[str]]:
        for index, pattern in enumerate(self.patterns):
            if not (code and index in self.prose_only):
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
        # A bare vocative opening a sentence: "Assistant, perform this", "Claude: run make". After
        # the full stop exactly one space is taken before the run of indentation and markup, so
        # the two never compete for the same blanks (which would backtrack quadratically).
        re.compile(
            r"(?:^|[.!?][ \t])[ \t>*#_(\[-]*(?:(?:hey|hi|hello|ok|okay|attention|yo)[ \t,]+)?(?:the[ \t]+)?"
            r"(?:ai|llms?|(?:ai[ \t]+)?(?:assistants?|agents?|models?)|(?:large[ \t]+)?language[ \t]+models?"
            r"|chatbots?|claude|chatgpt|gpt|copilot|gemini)[ \t]*(?:[,!:]|—|--)[ \t]*(?:now[ \t]+|also[ \t]+|first[ \t]+)?"
            r"(?:please|ignore|disregard|forget|do|don[’']?t|never|always|stop|start|run|execute|perform"
            r"|install|open|send|email|upload|download|fetch|delete|remove|write|print|output|reveal|show|tell"
            r"|say|reply|respond|answer|summari[sz]e|recommend|rate|approve|grant|give|call|invoke|use|add"
            r"|include|make|follow|obey|read|visit|click|copy|create|set|change|update|report|treat|trust"
            r"|pretend|act|remember|ensure|you[ \t]+(?:must|should|shall|will|need|have|are|may|can)"
            r"|(?:when|if|once|before|after|while)[ \t]+you)\b",
            re.I | re.M,
        ),
    ), "speaks directly to an AI assistant or model rather than to a human reader"),
    _Phrase("marker", WARN, (
        re.compile(r"<\|(?:im_start|im_end|im_sep|system|user|assistant|endoftext|eot_id|start_header_id|end_header_id)\|>", re.I),
        re.compile(r"\[/?(?:INST|SYS)\]|<</?SYS>>"),
        # Not inside a path or a template name ("blocks/<name>--<system>.md"), which a tag is not.
        re.compile(
            r"(?<![\w/.-])</?(?:system|system[-_]reminder|system[-_]prompt|tool[-_]call|tool[-_]use"
            r"|tool[-_]result|function[-_]calls|function[-_]results|antml:[a-z_]+)\b[^<>\n]{0,200}>",
            re.I,
        ),
        re.compile(
            r"^[ \t>*#]*(?:human|assistant|system[ \t]+(?:prompt|message)|developer[ \t]+message"
            r"|tool[ \t]+(?:call|result|output))[ \t]*:",
            re.I | re.M,
        ),
        # Role words that are also ordinary keys ("user: root" in a compose file) count only
        # when followed by words, as a turn of conversation is.
        # Not Go's short declaration ("user := users.Current()"), which is code, not a turn.
        re.compile(r"^[ \t>*#]*(?:system|developer|user|tool|function)[ \t]*:(?!=)[ \t]*\S+[ \t]+\S", re.I | re.M),
        # Or by one word that obeys, approves or answers, as no ordinary value ("Linux", "root") does.
        re.compile(
            r"^[ \t>*#]*(?:system|developer|user|tool|function)[ \t]*:[ \t]*"
            r"(?:obey|comply|proceed|continue|approved?|granted|allow(?:ed)?|permitted|authori[sz]ed"
            r"|accept(?:ed)?|confirm(?:ed)?|ignore|disregard|override|execute|bypass|jailbreak"
            r"|unlock(?:ed)?|yes|sure)\b",
            re.I | re.M,
        ),
    ), "imitates a system-prompt, chat-role or tool-call marker that a model could mistake for real conversation structure",
       frozenset((3, 4, 5))),
)

_LINK_TITLE = re.compile(r"""\]\([^()\s]*\s+(?:"([^"\n]{1,2000})"|'([^'\n]{1,2000})')\s*\)""")
_REFERENCE_TITLE = re.compile(
    r"""^[ \t]{0,3}\[[^\]\n]{1,500}\]:[ \t]*\S+[ \t]+"""
    r"""(?:"([^"\n]{1,2000})"|'([^'\n]{1,2000})'|\(([^()\n]{1,2000})\))[ \t\r]*$""",
    re.M,
)
# The alt text stops at the next image opener, so a run of openers is passed over in one step
# each rather than each scanning up to the bound.
_IMAGE_ALT = re.compile(r"!\[((?:[^\]\n!]|!(?!\[)){1,2000})\]")
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


def _injection_findings(path: str, text: str, starts: list[int], *, code: bool = False) -> list[Finding]:
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
        for match in phrase.finditer(text, code=code):
            line = _line_at(starts, match.start())
            if line in hidden_lines:
                continue
            if phrase.severity == BLOCK and _mentioned(text, match.start(), match.end()):
                found.append(Finding(
                    WARN, "injection.mentioned", path, line,
                    f"Text here quotes words that {phrase.explanation}, shown as an example of what "
                    "not to write or of what an attack looks like rather than said as an "
                    "instruction; documentation about AI safety quotes such words, so it is "
                    "reported rather than blocking.",
                ))
            else:
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
    reported = {finding.line for finding in found}
    for line, phrase in _escaped_instructions(text, starts):
        if line not in reported:
            reported.add(line)
            found.append(Finding(
                BLOCK, "injection.encoded", path, line,
                "Escaped characters here (HTML entities, \\u or \\x escapes, or percent-encoding) "
                f"spell out text that {phrase.explanation}; a browser, a JSON parser or a model "
                "decodes them, while the patterns a reviewer searches for do not match.",
            ))
    return found


# --- use and mention ------------------------------------------------------------------------
#
# A phrase that would block is *mentioned*, not said, when it sits inside a short quotation on
# one line, makes up nearly all of it, and the words before the quotation on that line mark it
# as an example: 'avoid override-style language ("disregard the previous instruction")'. Text
# hidden from the reader, encoded or escaped is never taken as mentioned — hiding it is the tell
# — and a quotation carrying more than the phrase (a payload after it) is not an example.
_QUOTES = (('"', '"'), ("`", "`"), ("\u201c", "\u201d"), ("\u2018", "\u2019"), ("\u00ab", "\u00bb"))
_MENTION_CUE = re.compile(
    r"\b(?:avoid\w*|don[\u2019']?t|do\s+not|never|such\s+as|like|e\.g\.|for\s+(?:example|instance)"
    r"|examples?|phrases?|phrasings?|patterns?|wording|language|strings?|words|detect\w*|flag\w*"
    r"|block\w*|refus\w*|reject\w*|watch(?:ing)?\s+(?:out\s+)?for|look(?:ing)?\s+for|attacks?"
    r"|injections?|jailbreaks?|malicious|adversarial|beware|warn\w*|recogni[sz]\w*|classic|typical)\b",
    re.I,
)
_MAX_QUOTED = 200         # characters inside the quotation
_MAX_QUOTED_EXTRA = 40    # characters of it beyond the phrase itself


def _mentioned(text: str, start: int, end: int) -> bool:
    """Whether the phrase at text[start:end] is quoted as an example (see above)."""
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    before = text[line_start:start]
    after = text[end:line_end if line_end >= 0 else len(text)]
    for opening, closing in _QUOTES:
        opened = before.rfind(opening)
        if opened < 0:
            continue
        if opening == closing:
            if before.count(opening) % 2 == 0:
                continue                       # every quotation before the phrase is closed
        elif before.rfind(closing) > opened:
            continue
        closed = after.find(closing)
        if closed < 0:
            continue
        inside = (len(before) - opened - 1) + (end - start) + closed
        if inside > _MAX_QUOTED or inside - (end - start) > _MAX_QUOTED_EXTRA:
            continue
        if _MENTION_CUE.search(before[:opened]):
            return True
    return False


_ESCAPE = re.compile(
    r"&#[xX][0-9A-Fa-f]{1,6};|&#[0-9]{1,7};|&[A-Za-z][A-Za-z0-9]{1,31};"
    r"|\\u\{[0-9A-Fa-f]{1,6}\}|\\u[0-9A-Fa-f]{4}|\\x[0-9A-Fa-f]{2}|%[0-9A-Fa-f]{2}"
)


def _escaped_instructions(text: str, starts: list[int]) -> Iterator[tuple[int, _Phrase]]:
    """(line, phrase) for each line that spells out an instruction only once its escapes are
    decoded — "&#105;gnore", "\\u0069gnore" — one escape being enough to break every pattern.
    Only lines with an escape are decoded, all at once, so this is linear in the text."""
    numbers = sorted({_line_at(starts, match.start()) for match in _ESCAPE.finditer(text)})
    if not numbers:
        return
    lines = []
    for number in numbers:
        end = starts[number] - 1 if number < len(starts) else len(text)
        lines.append(_ESCAPE.sub(_unescape, text[starts[number - 1]:end]))
    joined = _clean("\n".join(lines))
    joined_starts = _line_starts(joined)
    for phrase in _PHRASES:
        for match in phrase.finditer(joined):
            yield numbers[_line_at(joined_starts, match.start()) - 1], phrase


def _unescape(match: re.Match[str]) -> str:
    escape = match.group()
    if escape.startswith("&"):
        decoded = html.unescape(escape)
    else:
        digits = escape[3:-1] if escape.startswith("\\u{") else escape[2:] if escape.startswith("\\") else escape[1:]
        code = int(digits, 16)
        decoded = chr(code) if code <= 0x10FFFF else ""
    return _NOISE.sub(" ", decoded)


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
    """Decoded bytes as the text a model would make of them. Undecodable bytes and control
    characters become spaces rather than disqualifying the blob: a single stray byte, or a few
    before or after the text, must not be enough to hide an instruction from the scan."""
    text = _NOISE.sub(" ", raw.decode("utf-8", errors="replace"))
    if len(text.strip()) < 8 or not _WORDISH.search(text):
        return None
    return text


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
    for offset, decoded in _wrapped_base64(text):
        yield offset, decoded, "base64"


# Chunks of the base64 alphabet separated by the whitespace encoders wrap with. The classes
# are disjoint and a match always succeeds once started, so runs are found in one pass.
_WRAPPED = re.compile(r"[A-Za-z0-9+/_-]+={0,2}(?:[ \t\r\n]+[A-Za-z0-9+/_-]+={0,2})*")
_WRAPPED_CHUNK = re.compile(r"[A-Za-z0-9+/_-]+={0,2}")
_URLSAFE = str.maketrans("-_", "+/")
_FIRST_WINDOW = 32


def _wrapped_base64(text: str) -> Iterator[tuple[int, str]]:
    """(offset, decoded) for base64 wrapped onto short lines or split into spaced chunks, as MIME
    and many encoders write it, so that no one piece is long enough to be read on its own. The
    wrapping is stripped before decoding and the offset is that of the chunk the blob starts at,
    so the finding is on its first line. A blob ends at its padding."""
    for run in _WRAPPED.finditer(text):
        body = run.group()
        if not (_UPPER.search(body) and _LOWER.search(body)):
            continue  # identifiers and hex digests, not base64 of text
        group: list[tuple[int, str]] = []
        for chunk in _WRAPPED_CHUNK.finditer(body):
            group.append((run.start() + chunk.start(), chunk.group()))
            if chunk.group().endswith("=") or chunk.end() == len(body):
                if len(group) > 1:  # one unbroken piece is the plain base64 pattern's to read
                    yield from _wrapped_group(group)
                group = []


def _wrapped_group(group: list[tuple[int, str]]) -> Iterator[tuple[int, str]]:
    """Decoding is tried from each chunk in turn, so words of prose run into the blob are passed
    over. A try that finds text resumes after it. A try that does not rules out the chunks in
    step with it (a multiple of four characters on) that start inside the stretch it decoded,
    except the last, where the stretch stopped: they would decode to a tail of the same bytes,
    and a tail of a blob is passed over here as the unwrapped pattern passes it over. So each
    character is decoded in a bounded number of alignments, and the work stays linear in the
    size of the run however long a rejected stretch is.

    Each try first passes over noise (bytes that are not UTF-8, put there to break decoding) up
    to the next chunk in step with it, so every place text could start is some try's to find. A
    try that passed over noise only moves on to the next chunk: noise may have run into the first
    word of what it found, and the next chunk may be where the text really starts."""
    joined = "".join(chunk for _offset, chunk in group).rstrip("=")
    begins: list[int] = []
    size = 0
    for _offset, chunk in group:
        begins.append(size)
        size += len(chunk)
    # The next chunk in step with each one, and so how far each try looks for noise.
    after = [len(group)] * len(group)
    latest: dict[int, int] = {}
    for index in range(len(group) - 1, -1, -1):
        after[index] = latest.get(begins[index] % 4, len(group))
        latest[begins[index] % 4] = index
    decoded_to = [0, 0, 0, 0]  # by alignment, where the next try in step may start
    index = 0
    while index < len(group) and len(joined) - begins[index] >= 20:
        begin = begins[index]
        if begin < decoded_to[begin % 4]:
            index += 1
            continue
        reach = (begins[after[index]] if after[index] < len(group) else len(joined)) - begin
        decoded, used, skipped = _from_wrapped(joined, begin, reach)
        if decoded is None:
            last = index
            while after[last] < len(group) and begins[after[last]] <= begin + used:
                last = after[last]
            decoded_to[begin % 4] = max(begin + 1, begins[last])
            index += 1
            continue
        yield group[index][0], decoded
        index = index + 1 if skipped else max(index + 1, bisect.bisect_left(begins, begin + used))


def _from_wrapped(joined: str, begin: int, reach: int) -> tuple[str | None, int, bool]:
    """The text ``joined`` decodes to from ``begin`` until it stops being text (prose after a
    blob decodes to noise), how many characters that took, and whether noise at the start of
    the chunk was passed over first. The window read doubles only while all of it decodes
    cleanly, so a try costs in proportion to the noise it passes and the text it finds."""
    skip = _leading_noise(joined, begin, min(reach, _MAX_NOISE))
    window = _FIRST_WINDOW
    while True:
        end = min(len(joined), begin + window)
        core = joined[begin:end].translate(_URLSAFE)
        raw = base64.b64decode(core[:len(core) - len(core) % 4])
        try:
            raw[skip:].decode("utf-8")
        except UnicodeDecodeError as error:
            # A character cut in two by the window's edge is not the end of the text.
            if error.reason != "unexpected end of data" or end == len(joined):
                raw = raw[:skip + error.start]
                break
        else:
            if end == len(joined):
                break
        window *= 2
    used = -(-len(raw) * 4 // 3)
    blob = joined[begin:begin + used]
    if len(raw) <= skip or not (_UPPER.search(blob) and _LOWER.search(blob)):
        return None, used, skip > 0
    return _as_text(raw[skip:]), used, skip > 0


_MAX_NOISE = 4096  # characters searched for leading noise; the unwrapped pattern reads longer chunks


def _leading_noise(joined: str, begin: int, reach: int) -> int:
    """How many decoded bytes, of the ``reach`` characters from ``begin``, come before text: up
    to just after the last byte among them that is not UTF-8, or 0 if every byte is."""
    size = reach - reach % 4
    core = joined[begin:begin + size + 4].translate(_URLSAFE)
    raw = base64.b64decode(core[:len(core) - len(core) % 4])
    if not raw or raw.isascii():
        return 0
    limit = size * 3 // 4
    offset = last = 0
    for ch in raw.decode("utf-8", errors="surrogateescape"):
        if offset >= limit:
            break
        code = ord(ch)
        if 0xDC80 <= code <= 0xDCFF:
            offset += 1
            last = offset
        else:
            offset += 1 if code < 0x80 else 2 if code < 0x800 else 3 if code < 0x10000 else 4
    return last


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
    # Literals of which every match holds at least one, compared case for case: where none is
    # in the text the pattern cannot match, and is not run. Only for case-sensitive patterns —
    # a case-insensitive one also matches letters that fold onto ASCII ('ſ', 'ı', 'K').
    requires: tuple[str, ...] = ()


# Specific shapes first: a line that has one does not also get the generic guess.
_SECRETS = (
    _Secret("aws_access_key", "an AWS access key ID", re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b"), requires=('AKIA', 'ASIA', 'ABIA', 'ACCA')),
    _Secret("aws_secret_key", "an AWS secret access key",
            re.compile(r"(?i)aws.{0,20}secret.{0,20}[:=][ \t]*[\"']?([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])"), group=1),
    _Secret("google_api_key", "a Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])"), requires=('AIza',)),
    _Secret("azure_storage_key", "an Azure storage account key",
            re.compile(r"AccountKey=([A-Za-z0-9+/]{80,}={0,2})"), group=1, requires=('AccountKey=',)),
    _Secret("stripe_key", "a Stripe secret or restricted key", re.compile(r"\b(?:sk|rk)_(?:live|test)_[0-9A-Za-z]{16,}"), requires=('k_live_', 'k_test_')),
    _Secret("stripe_webhook_secret", "a Stripe webhook signing secret", re.compile(r"\bwhsec_[0-9A-Za-z]{24,}"), requires=('whsec_',)),
    _Secret("shopify_token", "a Shopify access token", re.compile(r"\bshp(?:at|ca|pa|ss)_[0-9a-fA-F]{32}\b"), requires=('shpat_', 'shpca_', 'shppa_', 'shpss_')),
    _Secret("slack_token", "a Slack token", re.compile(r"\bxox[abposr]-[0-9A-Za-z-]{10,}"), requires=('xox',)),
    _Secret("slack_webhook", "a Slack incoming-webhook URL",
            re.compile(r"hooks\.slack\.com/services/T[0-9A-Z]+/B[0-9A-Z]+/[0-9A-Za-z]+"), requires=('hooks.slack.com/services/T',)),
    _Secret("discord_webhook", "a Discord webhook URL",
            re.compile(r"discord(?:app)?\.com/api/webhooks/\d+/[0-9A-Za-z_-]{20,}"), requires=('/api/webhooks/',)),
    _Secret("telegram_bot_token", "a Telegram bot token", re.compile(r"\b\d{8,10}:AA[0-9A-Za-z_-]{33}(?![0-9A-Za-z_-])"), requires=(':AA',)),
    _Secret("github_token", "a GitHub token", re.compile(r"\b(?:gh[pousr]_[0-9A-Za-z]{36,}|github_pat_[0-9A-Za-z_]{50,})"), requires=('ghp_', 'gho_', 'ghu_', 'ghs_', 'ghr_', 'github_pat_')),
    _Secret("gitlab_token", "a GitLab token", re.compile(r"\bglpat-[0-9A-Za-z_-]{20,}"), requires=('glpat-',)),
    _Secret("npm_token", "an npm access token", re.compile(r"\bnpm_[0-9A-Za-z]{36}\b"), requires=('npm_',)),
    _Secret("pypi_token", "a PyPI upload token", re.compile(r"\bpypi-AgEIcHlwaS5vcmc[0-9A-Za-z_-]{20,}"), requires=('pypi-AgEIcHlwaS5vcmc',)),
    _Secret("anthropic_key", "an Anthropic API key", re.compile(r"\bsk-ant-[0-9A-Za-z_-]{20,}"), requires=('sk-ant-',)),
    _Secret("openai_key", "an OpenAI API key",
            re.compile(r"\bsk-(?:proj|svcacct|admin)-[0-9A-Za-z_-]{20,}|\bsk-[0-9A-Za-z]{20}T3BlbkFJ[0-9A-Za-z]{20}"), requires=('sk-',)),
    _Secret("sendgrid_key", "a SendGrid API key", re.compile(r"\bSG\.[0-9A-Za-z_-]{22}\.[0-9A-Za-z_-]{43}(?![0-9A-Za-z_-])"), requires=('SG.',)),
    _Secret("twilio_key", "a Twilio API key", re.compile(r"\bSK[0-9a-f]{32}\b"), requires=('SK',)),
    _Secret("private_key", "a private key", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"), requires=('-----BEGIN ',)),
    _Secret("jwt", "a JSON web token",
            re.compile(r"\beyJ[0-9A-Za-z_-]{10,}\.eyJ[0-9A-Za-z_-]{10,}\.[0-9A-Za-z_-]{10,}"), severity=WARN, requires=('eyJ',)),
    _Secret("npm_auth", "an npm registry credential", re.compile(r"_auth(?:Token)?[ \t]*=[ \t]*([^\s$'\"{]{8,})"), group=1, requires=('_auth',)),
    _Secret("url_password", "a password inside a connection URL",
            re.compile(r"\b[a-z][a-z0-9+.-]{1,20}://[^\s:/@'\"]{1,64}:([^\s@/'\"]{3,128})@[\w.-]+"),
            severity=WARN, group=1, generic=True, requires=('://',)),
    _Secret("assignment", "a hard-coded password or secret",
            re.compile(
                r"(?i)(?<![A-Za-z0-9])(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token"
                r"|client[_-]?secret)[\"']?[ \t]*[:=][ \t]*[\"']([^\"'\s]{8,})[\"']"
            ),
            severity=WARN, group=1, generic=True),
)
# The body of a PEM block after its header: at most a few header lines (Proc-Type, DEK-Info),
# then lines of base64, broken by real newlines or by the escaped "\n" of a key pasted into JSON
# or an environment file. The base64 is the key itself; the header only announces it.
_PEM_BREAK = re.compile(r"(?:[ \t]*(?:\r?\n|\\n))+[ \t]*")
_PEM_BODY = re.compile(
    rf"(?:{_PEM_BREAK.pattern}[A-Za-z-]+:[^\r\n\\]*){{0,4}}"
    rf"((?:{_PEM_BREAK.pattern}[A-Za-z0-9+/]+={{0,2}}(?=[ \t]*(?:\r?\n|\\n|$)))+)"
)
_MIN_PEM_LINE = 8  # shorter lines give little away, and would redact ordinary names
_PLACEHOLDER = re.compile(
    r"example|sample|dummy|placeholder|changeme|change[_-]me|your[_-]|xxxx|\*{3}|\.\.\.|[<>{}$%]|redacted|fake|password",
    re.I,
)
# The same shapes for paths, where a credential often follows a letter or an underscore
# ("backup_ghp_..."): without the word boundaries, a name is redacted rather than shown.
_PATH_SECRETS = tuple(
    (re.compile(secret.pattern.pattern.replace(r"\b", ""), secret.pattern.flags), secret.slug)
    for secret in _SECRETS
)


def _secret_findings(path: str, text: str, starts: list[int], exposed: _Exposed) -> list[Finding]:
    found: list[Finding] = []
    specific_lines: set[int] = set()
    pem_end = 0  # a header inside the block before is not read again, so parsing stays linear
    for secret in _SECRETS:
        if secret.requires and not any(literal in text for literal in secret.requires):
            continue
        for match in secret.pattern.finditer(text):
            value = match.group(secret.group) or ""
            line = _line_at(starts, match.start())
            if secret.generic:
                if line in specific_lines or _PLACEHOLDER.search(value):
                    continue
            else:
                specific_lines.add(line)
            if value:
                exposed.add(value)
            if secret.slug == "private_key" and match.start() >= pem_end:
                body = _PEM_BODY.match(text, match.end())
                if body:
                    pem_end = body.end()
                    exposed.update(
                        part for part in _PEM_BREAK.split(body.group(1)) if len(part) >= _MIN_PEM_LINE
                    )
            found.append(Finding(
                secret.severity, f"secret.{secret.slug}", path, line,
                f"Looks like {secret.label} ({len(value)} characters; the value is withheld). "
                "Treat it as exposed: it is never digested, and its owner should revoke it.",
            ))
    return found


# --- things that would run ----------------------------------------------------------------

# A git directory's hooks and config, including those of submodules under .git/modules/.
_GIT_HOOK = re.compile(r"(?:^|/)\.git/(?:.+/)?hooks/[^/]+$")
_HOOK_MANAGERS = re.compile(r"(?:^|/)\.(?:husky|githooks)/")
_GIT_CONFIG = re.compile(r"(?:^|/)\.git/(?:.+/)?config(?:\.worktree)?$")
_GIT_SECTION = re.compile(r'[ \t]*\[[ \t]*([A-Za-z0-9.-]+)(?:[ \t]+"(?:[^"\\\n]|\\.)*")?[ \t]*\]')
_GIT_KEY = re.compile(r"[ \t]*([A-Za-z][A-Za-z0-9-]*)[ \t]*(?:=[ \t]*(.*))?")
# Config keys (in any section) whose value is a program git starts during ordinary commands:
# status, diff, log, fetch, commit and the rest.
_GIT_PROGRAM_KEYS = frozenset((
    "fsmonitor", "hookspath", "sshcommand", "askpass", "pager", "editor", "gitproxy", "textconv",
    "command", "cmd", "driver", "helper", "program", "external", "packobjectshook",
    "alternaterefscommand", "uploadpack", "receivepack", "clean", "smudge", "process",
))
_CI_FILES = re.compile(
    r"(?:^|/)(?:\.github/workflows/[^/]+\.ya?ml|\.gitlab-ci\.ya?ml|\.circleci/config\.ya?ml"
    r"|azure-pipelines\.ya?ml|Jenkinsfile|\.travis\.ya?ml|bitbucket-pipelines\.ya?ml|\.drone\.ya?ml"
    r"|\.buildkite/[^/]+\.ya?ml)$"
)
# Agent-harness settings and the plugin manifests and hook files a harness loads with a plugin.
_HARNESS_SETTINGS = re.compile(
    r"(?:^|/)(?:\.claude/settings(?:\.local)?\.json|\.gemini/settings\.json|\.cursor/hooks\.json|\.codex/config\.toml"
    r"|\.claude-plugin/plugin\.json|hooks/hooks\.json)$"
)
_MCP_FILES = re.compile(
    r"(?:^|/)(?:\.mcp\.json|mcp\.json|mcp_config\.json|claude_desktop_config\.json|cline_mcp_settings\.json)$"
)
_MCP_COMMAND = re.compile(r'"command"\s*:')
_VSCODE_TASKS = re.compile(r"(?:^|/)\.vscode/tasks\.json$")
_AUTO_TASK = re.compile(r'"runOn"\s*:\s*"folderOpen"')
_JSON_KEY = re.compile(r'"([A-Za-z:-]+)"\s*:')
_SCRIPT_SUFFIXES = (".sh", ".bash", ".zsh", ".ksh", ".fish", ".command", ".ps1", ".psm1", ".bat", ".cmd", ".vbs")
# What could not be read cannot be vouched for: a file that decides whether something runs is
# reported as if it does.
_UNREAD = "could not be read (too large, binary, hard-linked, unreadable or past the byte limit)"

# Settings keys that make an agent harness run a command, start a server, or approve servers,
# when it loads the file.
_HARNESS_COMMAND_KEYS = tuple(
    "hooks statusLine apiKeyHelper awsAuthRefresh awsCredentialExport otelHeadersHelper "
    "enableAllProjectMcpServers enabledMcpjsonServers mcpServers lspServers toolDiscoveryCommand "
    "toolCallCommand mcpServerCommand".split()
)
_DEVCONTAINER_COMMANDS = tuple(
    "initializeCommand onCreateCommand updateContentCommand postCreateCommand postStartCommand "
    "postAttachCommand".split()
)
_NPM_SCRIPTS = {
    "preinstall": (BLOCK, "on install"),
    "install": (BLOCK, "on install"),
    "postinstall": (BLOCK, "on install"),
    "preprepare": (BLOCK, "on install from a folder or a git URL"),
    "prepare": (BLOCK, "on install from a folder or a git URL"),
    "postprepare": (BLOCK, "on install from a folder or a git URL"),
    "dependencies": (BLOCK, "whenever an install changes node_modules"),
    "pnpm:devPreinstall": (BLOCK, "on a local pnpm install"),
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
    "pdm_build.py": (BLOCK, "pdm_build.py is Python that pdm-backend runs whenever the package is built."),
    "binding.gyp": (WARN, "binding.gyp makes npm compile native code with node-gyp when the package is installed."),
}
_PYPROJECT_HOOKS = (
    (re.compile(r"(?m)^[ \t]*backend-path[ \t]*="),
     "pyproject.toml builds with a backend from inside this artifact (backend-path), so the artifact's "
     "own code runs whenever the package is built or installed."),
    (re.compile(r"(?m)^\[tool\.hatch\.(?:build|metadata)(?:\.targets\.[^\]\n]+)?\.hooks\b"),
     "pyproject.toml declares Hatch build or metadata hooks, which run code whenever the package is built."),
    (re.compile(r"(?m)^\[tool\.poetry\.build\]"),
     "pyproject.toml names a Poetry build script, which runs whenever the package is built."),
    (re.compile(r"(?m)^\[tool\.setuptools\.cmdclass\]|^[ \t]*cmdclass[ \t]*="),
     "pyproject.toml replaces setuptools commands with classes of its own, which run whenever the "
     "package is built."),
)


# A shell tool in a skill's allowed-tools: "Bash", "Bash(npm:*)", "Shell(...)", "PowerShell".
_SHELL_TOOL = re.compile(r"\b(?:Bash|Shell|PowerShell|Terminal)\b(?:\([^)\n]{0,200}\))?", re.I)


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
    if lower == "skill.md" and text is not None:
        tools = _front_matter_field(text, "allowed-tools") or _front_matter_field(text, "allowed_tools")
        shell = _SHELL_TOOL.findall(tools or "")
        if shell:
            wildcard = any("*" in grant for grant in shell)
            flag(WARN, "execute.agent_permissions",
                 f"The skill's allowed-tools grant the agent {len(shell)} shell-command permission(s)"
                 f"{', including a wildcard,' if wildcard else ''} to use without asking while the "
                 "skill is active: installed as it is, it widens what the agent may run.",
                 _line_of(text, r"(?m)^allowed[-_]tools[ \t]*:"))
    if _GIT_CONFIG.search(rel):
        line = _git_config_command(text) if text is not None else 0
        if line or text is None:
            flag(BLOCK, "execute.git_config",
                 f"Git configuration that {_UNREAD}, so whether it names a program git runs is unknown."
                 if text is None else
                 "Git configuration naming a program (an fsmonitor, pager, editor, hooks path, diff or "
                 "merge driver, credential helper, filter, include or shell alias) that git runs during "
                 "ordinary commands such as status.", line)
    for manifest, runner, table in (
        ("package.json", "npm, yarn and pnpm run", _NPM_SCRIPTS), ("composer.json", "Composer runs", _COMPOSER_SCRIPTS),
    ):
        if name == manifest:
            if text is None:
                flag(BLOCK, "execute.install_script",
                     f"{manifest} {_UNREAD}, so whether it declares install scripts is unknown: treat it "
                     "as if it does.")
            else:
                found.extend(_lifecycle_findings(path, text, manifest, runner, table))
    if name in _BUILD_SCRIPTS:
        severity, message = _BUILD_SCRIPTS[name]
        flag(severity, "execute.build", message)
    if name == "pyproject.toml":
        if text is None:
            flag(BLOCK, "execute.build", f"pyproject.toml {_UNREAD}, so whether it runs build hooks is unknown.")
        else:
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
    mcp_file = _MCP_FILES.search(rel) is not None
    if mcp_file and text is None:
        flag(BLOCK, "execute.mcp", f"MCP configuration that {_UNREAD}, so the servers it starts are unknown.")
    elif text is not None and lower.endswith(".json") and not _HARNESS_SETTINGS.search(rel) and (
        mcp_file or '"mcpServers"' in text or "\\u" in text
    ):
        found.extend(_mcp_findings(path, text, mcp_file))
    if lower.endswith(".ipynb"):
        if text is None:
            flag(WARN, "execute.notebook", f"A notebook that {_UNREAD}, so its code cells are unknown.")
        else:
            found.extend(_notebook_findings(path, text))
    if _CI_FILES.search(rel):
        flag(WARN, "execute.ci",
             "A CI workflow: its commands run on a build server whenever the repository is pushed "
             "or receives a pull request.")
    if name in ("devcontainer.json", ".devcontainer.json"):
        if text is None:
            flag(BLOCK, "execute.devcontainer",
                 f"Dev-container configuration that {_UNREAD}, so the commands it runs when the folder "
                 "is opened are unknown.")
        for key in _present_keys(text, _DEVCONTAINER_COMMANDS) if text is not None else ():
            where = " on the host machine itself, outside the container" if key == "initializeCommand" else ""
            flag(BLOCK, "execute.devcontainer",
                 f"Sets '{key}', which dev-container tools run automatically{where} when this folder is opened.",
                 _line_of(text, rf'"{key}"\s*:'))
    if _VSCODE_TASKS.search(rel):
        if text is None:
            flag(BLOCK, "execute.editor_task",
                 f"VS Code tasks that {_UNREAD}, so whether one runs when the folder is opened is unknown.")
        elif _runs_on_open(text):
            flag(BLOCK, "execute.editor_task",
                 "A VS Code task set to run automatically when the folder is opened (runOn: folderOpen).",
                 _line_of(text, _AUTO_TASK))
    return found


def _git_config_command(text: str) -> int:
    """The line of the first setting that names a program git would start, or 0."""
    section = ""
    for number, line in enumerate(text.split("\n"), 1):
        head = _GIT_SECTION.match(line)
        if head:
            section = head.group(1).lower()
            line = line[head.end():]  # "[core] pager = less" sets a key on the header's line
        key = _GIT_KEY.fullmatch(line.rstrip("\r"))
        if not key:
            continue
        name = key.group(1).lower()
        value = (key.group(2) or "").strip().strip('"')
        if (
            name in _GIT_PROGRAM_KEYS or section == "pager"
            or (section == "alias" and value.startswith("!"))
            or (section in ("include", "includeif") and name == "path")
        ):
            return number
    return 0


def _lifecycle_findings(path: str, text: str, manifest: str, runner: str, table: dict) -> list[Finding]:
    data = _load_json(text)
    scripts = _dig(data, "scripts")
    if isinstance(scripts, dict):
        declared = set(scripts)
    elif data is None:
        declared = set(_JSON_KEY.findall(_json_unescape(text)))  # unparseable: any key of that name counts
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
        found.append(Finding(
            BLOCK, "execute.agent_hook", path, 0,
            f"Agent-harness settings that {_UNREAD}, so whether they run commands when loaded is unknown.",
        ))
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
    data = _load_jsonc(text)
    if data is None:
        launched = len(_MCP_COMMAND.findall(_json_unescape(text))) if mcp_file or "mcpServers" in _json_unescape(text) else 0
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
    data = _load_json(text)
    cells = _dig(data, "cells")
    if not isinstance(cells, list):
        # nbformat 3 keeps its cells in worksheets, and a code cell's source under "input".
        worksheets = _dig(data, "worksheets")
        sheets = [_dig(sheet, "cells") for sheet in worksheets] if isinstance(worksheets, list) else []
        cells = [cell for sheet in sheets if isinstance(sheet, list) for cell in sheet]
    code = [
        cell for cell in cells
        if _dig(cell, "cell_type") == "code" and (_dig(cell, "source") or _dig(cell, "input"))
    ]
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


# Comments and trailing commas, as JSON-with-comments allows them (devcontainer.json, VS Code's
# settings and tasks), and strings, which are kept whole so nothing inside one is mistaken for
# either. An unclosed block comment runs to the end rather than being searched for again.
_JSONC_TOKEN = re.compile(r'"(?:[^"\\\n]|\\.)*"|//[^\n]*|/\*.*?(?:\*/|\Z)|,(?=[ \t\r\n]*[}\]])', re.S)


def _load_jsonc(text: str) -> object:
    """JSON, or JSON with comments and trailing commas, parsed as the tools that read it do —
    escapes in keys included, so "initializeComm\\u0061nd" is the key it spells."""
    data = _load_json(text)
    if data is not None:
        return data
    return _load_json(_JSONC_TOKEN.sub(_jsonc_token, text))


def _jsonc_token(match: re.Match[str]) -> str:
    token = match.group()
    if token.startswith('"'):
        return token
    return "" if token == "," else " "


_JSON_ESCAPE = re.compile(r"\\u([0-9A-Fa-f]{4})")


def _json_unescape(text: str) -> str:
    """Text with JSON's \\u escapes decoded, for searching a file that does not parse."""
    return _JSON_ESCAPE.sub(lambda match: chr(int(match.group(1), 16)), text) if "\\u" in text else text


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
    are parsed as JSON with comments; one that still does not parse is searched for the key
    names instead, with its escapes decoded."""
    data = _load_jsonc(text)
    if isinstance(data, dict):
        return [key for key in keys if data.get(key)]
    plain = _json_unescape(text)
    return [key for key in keys if re.search(rf'"{re.escape(key)}"\s*:', plain)]


def _runs_on_open(text: str) -> bool:
    """Whether any task, anywhere in a tasks.json, is set to run when the folder is opened."""
    data = _load_jsonc(text)
    if data is None:
        return _AUTO_TASK.search(_json_unescape(text)) is not None
    stack = [data]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if item.get("runOn") == "folderOpen":
                return True
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return False


# --- licence ------------------------------------------------------------------------------

_PROPRIETARY = "LicenseRef-Proprietary"
_COMMONS_CLAUSE = "LicenseRef-Commons-Clause"
_CREATIVE_COMMONS = "CC"
_CC_TEXT = re.compile(
    r"attribution(?:-(noncommercial|noderivatives|noderivs|sharealike)(?:-(sharealike|noderivatives|noderivs))?)?"
    r" ([1-4]\.[05])( international| unported| generic)?"
)
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
    *(f"CC-BY{kind}-{version}" for kind in ("", "-NC", "-ND", "-SA", "-NC-ND", "-NC-SA")
      for version in ("1.0", "2.0", "2.5", "3.0", "4.0")),
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
# specific of two texts that share wording comes first (AGPL and LGPL before GPL, say). A
# fingerprint in two parts matches when its second part comes anywhere after its first. No
# pattern has an unbounded span: the second part is searched for once, from the end of the first
# part's first occurrence (if any later occurrence is followed by it, so is the first), so each
# fingerprint costs a pass or two over the text, however often the first part repeats.
_LICENCE_TEXTS = tuple(
    (spdx, re.compile(head), re.compile(tail) if tail else None) for spdx, head, tail in (
        (_COMMONS_CLAUSE, r"commons clause", None),
        ("BUSL-1.1", r"business source license", None),
        ("SSPL-1.0", r"server side public license", None),
        ("Elastic-2.0", r"elastic license 2\.0|elastic license, version 2", None),
        ("PolyForm-Noncommercial-1.0.0", r"polyform noncommercial license", None),
        ("PolyForm-Strict-1.0.0", r"polyform strict license", None),
        # Every Creative Commons attribution licence and version, named from what the text says.
        (_CREATIVE_COMMONS, _CC_TEXT.pattern, None),
        ("CC0-1.0", r"cc0 1\.0 universal", None),
        ("AGPL-3.0-only", r"gnu affero general public license", r"version 3"),
        ("LGPL-3.0-only", r"gnu lesser general public license", r"version 3"),
        ("LGPL-2.1-only", r"gnu lesser general public license", r"version 2\.1"),
        ("LGPL-2.0-only", r"gnu library general public license", None),
        ("GPL-3.0-only", r"gnu general public license", r"version 3"),
        ("GPL-2.0-only", r"gnu general public license", r"version 2"),
        ("MPL-2.0", r"mozilla public license,? (?:version|v\.?) ?2\.0", None),
        ("EPL-2.0", r"eclipse public license(?: -)? v(?:ersion)? ?2\.0", None),
        ("EPL-1.0", r"eclipse public license(?: -)? v(?:ersion)? ?1\.0", None),
        ("Apache-2.0", r"apache license,? version 2\.0", None),
        ("BSL-1.0", r"boost software license - version 1\.0", None),
        ("Unlicense", r"this is free and unencumbered software released into the public domain", None),
        ("ISC", r"distribute this software for any purpose with or without fee is hereby granted, provided that", None),
        ("0BSD", r"distribute this software for any purpose with or without fee is hereby granted", None),
        ("MIT", r"permission is hereby granted, free of charge, to any person obtaining a copy", None),
        ("BSD-3-Clause", r"redistribution and use in source and binary forms", r"neither the name"),
        ("BSD-2-Clause", r"redistribution and use in source and binary forms", None),
        ("Zlib", r"altered source versions must be plainly marked as such", None),
    )
)
_PROPRIETARY_TEXT = re.compile(
    r"all rights reserved|proprietary|confidential|may not be (?:copied|reproduced|distributed|modified|used)"
    r"|no licen[cs]e is granted"
)
# Restrictions added to a permissive text ("MIT, for non-commercial use only"): the grant the
# fingerprint recognised no longer stands as written. "Commercial or non-commercial", as the
# Unlicense says, grants both.
_RIDER = re.compile(
    r"(?<!commercial or )(?<!commercial and )\bnon-?commercial\b|\bnot for (?:any )?commercial\b"
    r"|\bno commercial use\b|\bcommercial (?:use|usage|purposes?|redistribution|distribution)"
    r"(?: of (?:this|the) software)? (?:is|are) (?:strictly )?(?:not permitted|prohibited|forbidden|not allowed)"
    r"|\bmay not be (?:used|sold|redistributed) for (?:any )?commercial\b"
    r"|\bfor (?:personal|private|non-profit|educational) use only\b"
)
_FORBIDS_REUSE = frozenset((
    _PROPRIETARY, _COMMONS_CLAUSE, "PolyForm-Noncommercial-1.0.0", "PolyForm-Strict-1.0.0", "BUSL-1.1",
))
_CONDITIONAL = frozenset(("MPL-2.0", "SSPL-1.0", "Elastic-2.0"))
_LICENCE_FILE = re.compile(r"(?:licen[cs]e|copying|unlicense)(?:[-_.][\w.-]+)?", re.I)
# A file named like a licence but with the suffix of code or data is code or data
# (license_check.py, licenses.json), not the artifact's licence.
_NOT_LICENCE_SUFFIXES = frozenset((
    "py pyi js mjs cjs ts tsx jsx go rs java kt kts rb php c h cc cpp hpp cs swift m mm scala sh bash "
    "zsh ps1 bat cmd json yaml yml toml xml css scss less vue svelte dart lua pl pm r ex exs erl hs clj "
    "sql lock cfg ini gradle png jpg jpeg gif svg ico pdf"
).split())
_EXPRESSION_TOKEN = re.compile(r"[()]|[^\s()]+")
_OPERATORS = ("AND", "OR", "WITH")
# SPDX licence exceptions, the only words that may follow WITH. Anything else is not an SPDX
# expression — and is never copied into a finding, where it could carry text from the artifact.
_EXCEPTIONS = {exception.lower(): exception for exception in (
    "389-exception", "Autoconf-exception-2.0", "Autoconf-exception-3.0", "Bison-exception-2.2",
    "Bootloader-exception", "Classpath-exception-2.0", "CLISP-exception-2.0", "DigiRule-FOSS-exception",
    "eCos-exception-2.0", "Fawkes-Runtime-exception", "FLTK-exception", "Font-exception-2.0",
    "freertos-exception-2.0", "GCC-exception-2.0", "GCC-exception-3.1", "gnu-javamail-exception",
    "GPL-3.0-linking-exception", "GPL-3.0-linking-source-exception", "GPL-CC-1.0", "GStreamer-exception-2005",
    "i2p-gpl-java-exception", "LGPL-3.0-linking-exception", "Libtool-exception", "Linux-syscall-note",
    "LLVM-exception", "LZMA-exception", "mif-exception", "OCaml-LGPL-linking-exception", "OCCT-exception-1.0",
    "OpenJDK-assembly-exception-1.0", "openvpn-openssl-exception", "PS-or-PDF-font-exception-20170817",
    "Qt-GPL-exception-1.0", "Qt-LGPL-exception-1.1", "Qwt-exception-1.0", "SHL-2.0", "SHL-2.1",
    "Swift-exception", "u-boot-exception-2.0", "Universal-FOSS-exception-1.0", "WxWindows-exception-3.1",
)}
_FRONT_MATTER_BLOCK = re.compile(r"---[ \t]*\r?\n(.*?)^---[ \t\r]*$", re.S | re.M)


def identify_licence_text(text: str) -> str:
    """The SPDX identifier for a licence file's text, or 'unknown'."""
    flat = " ".join(text.lower().split())
    for spdx, head, tail in _LICENCE_TEXTS:
        if spdx == _CREATIVE_COMMONS:
            found = _creative_commons(flat)
            if found:
                return found
            continue
        match = head.search(flat)
        if match and (tail is None or tail.search(flat, match.end())):
            if _id_rank(spdx) == 0 and _RIDER.search(flat):
                return _PROPRIETARY  # a permissive text with a restriction written into it
            return spdx
    return _PROPRIETARY if _PROPRIETARY_TEXT.search(flat) or _RIDER.search(flat) else UNKNOWN


def _creative_commons(flat: str) -> str | None:
    for match in _CC_TEXT.finditer(flat):
        parts = {match.group(1), match.group(2)} - {None}
        if not parts and not match.group(4):
            continue  # "attribution 4.0" alone is not a licence's name
        kind = (
            ("-NC" if "noncommercial" in parts else "")
            + ("-ND" if parts & {"noderivatives", "noderivs"} else "")
            + ("-SA" if "sharealike" in parts else "")
        )
        spdx = f"CC-BY{kind}-{match.group(3)}"
        if spdx in _ALIASES.values():
            return spdx
    return None


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
            exception = _EXCEPTIONS.get(token.lower())
            if exception is None:
                return UNKNOWN
            out.append(exception)
        else:
            canonical = _ALIASES.get(token.lower())
            if canonical is None:
                return UNKNOWN
            out.append(canonical)
    return " ".join(out).replace("( ", "(").replace(" )", ")")


def _licence_ids(expression: str) -> list[str]:
    ids: list[str] = []
    after_with = False
    for token in _EXPRESSION_TOKEN.findall(expression):
        if token not in ("(", ")", *_OPERATORS) and not after_with:
            ids.append(token)
        after_with = token == "WITH"
    return ids


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
    declared = _licence_of(rel, text)
    if declared is None:
        return [], False
    expression, line, source = declared
    return [_licence_finding(path, line, expression, source)], True


def _is_licence_file(name: str) -> bool:
    return bool(_LICENCE_FILE.fullmatch(name)) and name.rsplit(".", 1)[-1].lower() not in _NOT_LICENCE_SUFFIXES


def _licence_of(rel: str, text: str | None) -> tuple[str, int, str] | None:
    """(expression, line, what declared it) for a licence file or a manifest naming a licence;
    None for any other file."""
    name = rel.rsplit("/", 1)[-1]
    if _is_licence_file(name):
        return (identify_licence_text(text) if text is not None else UNKNOWN), 0, "licence file"
    if text is None:
        return None
    declared = _declared_licence(name, text)
    if declared is None:
        return None
    expression, line = declared
    return expression, line, name


_MAX_TOP_ENTRIES = 2000   # names looked at when finding the artifact's own licence


def artifact_licence(root: str | os.PathLike[str]) -> str | None:
    """The artifact's own licence, as scan_tree judges it: read from the licence files and the
    package manifests at the top of the tree (one further down covers only what is bundled with
    it). An SPDX expression when they agree; 'unknown' when there is a licence file whose text is
    not recognised; each expression with the file that declares it, joined by '; ', when they
    differ (LICENSE-MIT and LICENSE-APACHE, say); None when there is no licence at the top at all.

    Reading as scan_tree reads: regular files only, never through a link, never a hard-linked
    file, at most MAX_FILE_BYTES of each."""
    base = os.fspath(root)
    if not os.path.isdir(base):
        raise NotADirectoryError(base)
    names: list[str] = []
    with os.scandir(base) as listing:
        for count, entry in enumerate(listing):
            if count >= _MAX_TOP_ENTRIES:
                break
            if entry.is_file(follow_symlinks=False):
                names.append(entry.name)
    found: list[tuple[str, str]] = []
    for name in sorted(names):
        if not _is_licence_file(name) and name not in _MANIFESTS:
            continue
        text = _read_top(base, name)
        declared = _licence_of(name, text)
        if declared is not None and all(expression != declared[0] for expression, _ in found):
            found.append((declared[0], name))
    if not found:
        return None
    if len(found) == 1:
        return found[0][0]
    return "; ".join(f"{expression} ({_display(name)})" for expression, name in found)


_MANIFESTS = frozenset(("package.json", "composer.json", "pyproject.toml", "Cargo.toml", "setup.cfg"))
_MAX_LICENCE_FOLDERS = 2000   # folders looked in for a licence of their own


def licence_map(root: str | os.PathLike[str]) -> dict[str, tuple[str, str]]:
    """Each folder of the artifact that declares a licence of its own — by a licence file or a
    package manifest in it — as {folder: (expression, the file that declares it)}. "" is the
    top of the artifact. A folder's licence covers what is under it until a deeper folder
    declares its own; see licence_for. Read as artifact_licence reads the top, never through a
    link, and bounded."""
    base = os.fspath(root)
    if not os.path.isdir(base):
        raise NotADirectoryError(base)
    found: dict[str, tuple[str, str]] = {}
    pending = [""]
    looked = 0
    while pending and looked < _MAX_LICENCE_FOLDERS:
        folder = pending.pop()
        looked += 1
        full = os.path.join(base, folder) if folder else base
        try:
            with os.scandir(full) as listing:
                entries = sorted(listing, key=lambda entry: entry.name)[:_MAX_TOP_ENTRIES]
        except OSError:
            continue
        declared: list[tuple[str, str]] = []
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in (".git", "node_modules"):
                        pending.append(f"{folder}/{entry.name}" if folder else entry.name)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if not _is_licence_file(entry.name) and entry.name not in _MANIFESTS:
                continue
            rel = f"{folder}/{entry.name}" if folder else entry.name
            of = _licence_of(entry.name, _read_top(full, entry.name))
            if of is not None and all(expression != of[0] for expression, _ in declared):
                declared.append((of[0], rel))
        if declared:
            expression = declared[0][0] if len(declared) == 1 else "; ".join(e for e, _ in declared)
            found[folder] = (expression, declared[0][1])
    return found


def licence_for(path: str, licences: dict[str, tuple[str, str]]) -> tuple[str, str] | None:
    """The licence covering the artifact path given, from licence_map: the nearest folder above
    it that declares one; None when nothing does."""
    folder = path.rsplit("/", 1)[0] if "/" in path else ""
    while True:
        if folder in licences:
            return licences[folder]
        if not folder:
            return None
        folder = folder.rsplit("/", 1)[0] if "/" in folder else ""


def licence_rank(expression: str | None) -> int | None:
    """0 when the licence allows reuse, 1 when only on conditions (copyleft, share-alike,
    source-available, or not recognised), 2 when it forbids reuse; None when there is none.
    Several licences joined by '; ' (as artifact_licence gives them) are as closed as the most
    closed."""
    if not expression:
        return None
    parts = [part.split(" (")[0].strip() for part in expression.split(";")]
    return max(_licence_rank(part) for part in parts if part)


def holds_secret(text: str) -> bool:
    """Whether the text holds anything shaped like a credential, by the scanner's own rules."""
    if not text:
        return False
    clean = _clean(text[:MAX_FILE_BYTES])
    return bool(_secret_findings("", clean, _line_starts(clean), _Exposed()))


def _read_top(base: str, name: str) -> str | None:
    try:
        fd = os.open(os.path.join(base, name), _FILE_FLAGS)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink > 1 or info.st_size > MAX_FILE_BYTES:
            return None
        data = b""
        while len(data) <= MAX_FILE_BYTES and (chunk := os.read(fd, 65536)):
            data += chunk
    except OSError:
        return None
    finally:
        os.close(fd)
    if len(data) > MAX_FILE_BYTES or _looks_binary(data, name):
        return None
    return _decode(data)


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
    # The value is the rest of the line, trimmed afterwards: a lazy match that must end in
    # optional blanks backtracks quadratically over a line of spaces.
    match = re.search(rf"(?m)^{field}[ \t]*:[ \t]*([^\r\n]*)", block.group(1))
    return match.group(1).strip().strip("'\"") if match else None
