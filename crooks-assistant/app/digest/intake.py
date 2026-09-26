"""The Knowledge Digester's intake: bring an artifact into quarantine, pin it, and say where from.

    taken = intake(source, quarantine_root, ref=None, kind=None)
    result = pipeline.digest(taken.path, taken.source, store)

Intake is the first stage of KNOWLEDGE_DIGESTER_V1.md section 3 and the only one allowed the
network, and only to fetch. It takes an artifact — a git repository by URL, an archive, a local
directory, a single file, a file by URL, and whatever kinds are added later — and leaves a
read-only copy of it in a directory of its own under the quarantine root, with the Source that
pins it: the commit SHA or the digest of the bytes fetched, the content digest of the copy
(pipeline.tree_digest), the licence the copy declares at its top, and the time of intake.

Kinds of source are an open registry, as adapters are. Every module in the app.digest.intakes
namespace that keeps the handler contract is found at every call (pkgutil.iter_modules), never
from a list kept here, so a new kind of source is a new module, not an edit to this one:

    NAME          the handler's name (default: the module's); `kind=` picks a handler by it
    ORIGIN_KIND   one of model.ORIGIN_KINDS: what the Source records the origin as
    claims(request) -> int       how surely this handler is the one for the source (0: not it)
    materialise(request, writer) -> Pinned
                  fetch or read the source, and write the artifact's tree through the writer

Everything a handler writes goes through a TreeWriter, which is where the quarantine is kept
safe whatever the source holds: no name that is absolute, holds '..' or passes through a link or
a file; no file written through a link; no device, pipe or socket ever created (they are
withheld, and said so); a symbolic link kept as a link only when, followed through every other
link in the tree, it stays inside the tree — otherwise withheld; a hard link written as an
independent copy; and bounds on entries, bytes per file and bytes in all. Nothing fetched or
unpacked is executed, imported or installed, and nothing is followed out of the tree.

The copy is built in a private staging directory. Only when it is complete — written, links
checked, digested, licence read and every file and directory made read-only (a-w) — is it
renamed, in one step, to its final place, named by the artifact id its content digest derives.
So a directory there is complete by construction; a failure raises one of the IntakeError types
below and leaves no final directory behind. The same content taken in again is the same
directory: it is reused when its digest still matches, and replaced cleanly when it does not.
Beside each copy, and outside it, ART_ID.intake.json records the intakes that produced it, so
the same intake repeated gives the same Source, taken_at included."""

from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import ipaddress
import json
import os
import pkgutil
import re
import shutil
import tempfile
import time
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlsplit, urlunsplit

from app.digest import scan
from app.digest.model import ORIGIN_KINDS, Source, utc_now
from app.digest.pipeline import TreeTooLarge, tree_digest

HANDLERS_PACKAGE = "app.digest.intakes"

STAGING_PREFIX = ".staging-"
WORK_PREFIX = ".work-"
TRASH_PREFIX = ".trash-"
RECORD_SUFFIX = ".intake.json"
MAX_RECORDS = 50                  # intakes remembered beside one copy
STALE_SECONDS = 24 * 3600         # staging and work directories older than this are debris
_CHUNK = 1 << 20
_MAX_LINK_HOPS = 40               # as the kernel's own limit on following links
_MAX_COMPONENT = 255              # bytes in one name
_MAX_LINK_TARGET = 4095


# --- failures ---------------------------------------------------------------------------------


class IntakeError(Exception):
    """The artifact could not be taken in. Nothing was left in quarantine looking complete."""


class SourceRefused(IntakeError):
    """The source itself is not one intake takes: not https, credentials in the URL, a private
    host, a malformed reference, an encrypted or unsupported archive."""


class NoHandler(SourceRefused):
    """No handler claims the source, or the named handler does not exist."""


class FetchFailed(IntakeError):
    """The network fetch did not complete: unreachable, not found, refused or timed out."""


class LimitExceeded(IntakeError):
    """The artifact is past a bound: too many entries, too many bytes, too long a name."""


class UnsafeArtifact(IntakeError):
    """The artifact's content is hostile or tampered with: a name that escapes the tree, an
    entry written through a link, a decompression bomb, a tree that is not the commit's."""


class ArchiveUnreadable(IntakeError):
    """The archive is corrupt or truncated, and could not be read to the end."""


def shown(text: Any, limit: int = 160) -> str:
    """Text from an artifact as it may appear in a message: control, format and other
    invisible characters escaped, and cut to limit. Names in archives are chosen by whoever
    made them, and a message is read on a terminal."""
    out = []
    for ch in str(text):
        if ch.isprintable() and ch != "\\":
            out.append(ch)
        elif ch == "\\":
            out.append("\\\\")
        else:
            code = ord(ch)
            out.append(f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}" if code < 0x10000 else f"\\U{code:08x}")
    joined = "".join(out)
    return joined if len(joined) <= limit else joined[: limit - 1] + "…"


# --- bounds -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Limits:
    """The bounds on one intake. The defaults sit inside what pipeline.tree_digest will pin."""

    max_entries: int = 50_000           # files, directories, links and withheld entries
    max_total_bytes: int = 512 << 20    # written into quarantine, in all
    max_file_bytes: int = 256 << 20     # one file
    max_ratio: float = 250.0            # expanded to compressed, once past ratio_floor
    ratio_floor: int = 32 << 20         # below this many bytes expanded no ratio is a bomb
    max_download_bytes: int = 1 << 30   # fetched: a git pack, or a file by URL
    timeout: float = 600.0              # seconds for one fetch
    max_name_bytes: int = 4096          # one path inside the artifact

    def __post_init__(self) -> None:
        for name in ("max_entries", "max_total_bytes", "max_file_bytes", "ratio_floor",
                     "max_download_bytes", "max_name_bytes"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive whole number")
        if not self.max_ratio > 1 or not self.timeout > 0:
            raise ValueError("max_ratio must be above 1 and timeout above 0")


# --- what a handler is given and gives back ---------------------------------------------------


Fetcher = Callable[..., Any]


@dataclass(frozen=True)
class Request:
    """One intake, as a handler sees it. `scratch` is a private work directory outside the
    tree being written (None while handlers are only asked whether they claim the source);
    it and everything in it are removed when the intake ends."""

    source: str
    ref: str | None = None
    kind: str | None = None
    limits: Limits = field(default_factory=Limits)
    fetchers: Mapping[str, Fetcher] = field(default_factory=dict)
    scratch: Path | None = None

    def fetcher(self, name: str, default: Fetcher) -> Fetcher:
        """The network step a handler uses: injected by name (tests, an offline host), or the
        handler's own live one."""
        return self.fetchers.get(name, default)


@dataclass(frozen=True)
class Pinned:
    """What a handler says about what it wrote: the origin as the Source records it (never with
    credentials), the pin (a commit SHA, or the digest of the bytes fetched; None to pin by the
    content digest of the tree), and notes worth keeping about the intake."""

    origin: str
    pinned_ref: str | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Intake:
    """An artifact in quarantine: its Source, the read-only directory that is its copy, the
    handler that took it in, what was written and what was withheld (with why), and whether
    an identical copy already there was reused."""

    source: Source
    path: Path
    handler: str
    entries: int
    bytes: int
    withheld: tuple[tuple[str, str], ...]
    notes: tuple[str, ...]
    reused: bool

    @property
    def artifact_id(self) -> str:
        return self.source.artifact_id


# --- names ------------------------------------------------------------------------------------

_DRIVE = re.compile(r"[A-Za-z]:(?:/|$)")


def clean_name(name: Any, *, backslash_is_separator: bool = False, max_bytes: int = 4096) -> str:
    """A path inside the artifact, relative and normalised ('' is the top), or UnsafeArtifact:
    absolute, a drive, a '..' anywhere, or a NUL. '.' and empty parts are dropped."""
    if not isinstance(name, str) or "\x00" in name:
        raise UnsafeArtifact(f"an entry's name is not a name: {shown(name)}")
    text = name.replace("\\", "/") if backslash_is_separator else name
    if text.startswith("/") or _DRIVE.match(text):
        raise UnsafeArtifact(f"entry {shown(name)} is an absolute path: it would be written outside the quarantine")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if ".." in parts:
        raise UnsafeArtifact(f"entry {shown(name)} climbs out with '..': it would be written outside the quarantine")
    cleaned = "/".join(parts)
    encoded = os.fsencode(cleaned)
    if len(encoded) > max_bytes or any(len(os.fsencode(part)) > _MAX_COMPONENT for part in parts):
        raise LimitExceeded(f"entry {shown(name)} has a name longer than can be written")
    return cleaned


# --- the writer -------------------------------------------------------------------------------


@dataclass
class Entry:
    """One entry written (or to be written) into the tree."""

    kind: str                        # "dir", "file", "link" or "withheld"
    size: int = 0
    executable: bool = False
    blob_id: str | None = None       # the git object id of the content, when asked for
    target: str | None = None        # a link's target
    reason: str | None = None        # why it was withheld


class TreeWriter:
    """Writes one artifact's tree into a fresh, private staging directory, and keeps it safe
    whatever it is asked to write (see the module's docstring). Handlers write only through it.

    With blob_hash ("sha1" or "sha256") each file's and link's git object id is computed as it
    is written, so a git handler can check the tree against the commit's."""

    def __init__(self, root: Path, limits: Limits, *, blob_hash: str | None = None) -> None:
        self.root = Path(root)
        self.limits = limits
        self.blob_hash = blob_hash
        self.entries: dict[str, Entry] = {}
        self.count = 0
        self.bytes = 0
        self._finished = False

    # -- what handlers call

    def name(self, name: Any, *, backslash_is_separator: bool = False) -> str:
        return clean_name(name, backslash_is_separator=backslash_is_separator,
                          max_bytes=self.limits.max_name_bytes)

    def directory(self, name: str) -> None:
        rel = self.name(name)
        if not rel:
            return                                     # the top of the tree: already there
        current = self.entries.get(rel)
        if current is not None:
            if current.kind == "dir":
                return
            raise UnsafeArtifact(f"entry {shown(rel)} appears twice, once as a directory")
        self._parents(rel)
        self._admit(rel)
        os.mkdir(self._path(rel), 0o700)
        self.entries[rel] = Entry("dir")

    def file(self, name: str, data: BinaryIO | bytes, *, size: int | None = None,
             executable: bool = False) -> str:
        """Write a regular file from bytes or a binary reader, and return the content's
        "sha256:<hex>". A size, when given, must be what the reader holds."""
        rel = self._new(name)
        if size is not None and size > self.limits.max_file_bytes:
            raise LimitExceeded(f"{shown(rel)} is {size} bytes, over the {self.limits.max_file_bytes}-byte limit on one file")
        if size is not None and self.bytes + size > self.limits.max_total_bytes:
            raise LimitExceeded(f"the artifact is over the {self.limits.max_total_bytes}-byte limit (at {shown(rel)})")
        if self.blob_hash is not None and size is None:
            raise ValueError("a git object id needs the file's size before its content")
        reader: BinaryIO = io.BytesIO(data) if isinstance(data, (bytes, bytearray)) else data
        self._admit(rel)
        self.entries[rel] = Entry("file", executable=executable)   # claimed before any byte
        content = hashlib.sha256()
        blob = self._blob(size) if self.blob_hash is not None else None
        written = 0
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(self._path(rel), flags, 0o600)
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = reader.read(_CHUNK)
                if not chunk:
                    break
                written += len(chunk)
                if written > self.limits.max_file_bytes:
                    raise LimitExceeded(f"{shown(rel)} is over the {self.limits.max_file_bytes}-byte limit on one file")
                if self.bytes + written > self.limits.max_total_bytes:
                    raise LimitExceeded(f"the artifact is over the {self.limits.max_total_bytes}-byte limit (at {shown(rel)})")
                if size is not None and written > size:
                    raise UnsafeArtifact(f"{shown(rel)} holds more than the {size} bytes it declares")
                out.write(chunk)
                content.update(chunk)
                if blob is not None:
                    blob.update(chunk)
        if size is not None and written != size:
            raise UnsafeArtifact(f"{shown(rel)} holds {written} bytes, not the {size} it declares")
        self.bytes += written
        entry = self.entries[rel]
        entry.size = written
        entry.blob_id = blob.hexdigest() if blob is not None else None
        return "sha256:" + content.hexdigest()

    def symlink(self, name: str, target: Any) -> None:
        """A symbolic link, created at finish() if it stays inside the tree; withheld if not."""
        rel = self._new(name)
        self._admit(rel)
        if not isinstance(target, str) or "\x00" in target:
            self.entries[rel] = Entry("withheld", reason="a symbolic link whose target is not a name")
            return
        encoded = os.fsencode(target)
        entry = Entry("link", target=target)
        if self.blob_hash is not None:
            blob = self._blob(len(encoded))
            blob.update(encoded)
            entry.blob_id = blob.hexdigest()
        self.entries[rel] = entry

    def copy(self, name: str, existing: Any, *, backslash_is_separator: bool = False) -> str:
        """A hard link, written as an independent copy of a file already written: a hard link in
        quarantine would share its data with whatever else it names."""
        source = self.name(existing, backslash_is_separator=backslash_is_separator)
        entry = self.entries.get(source)
        if entry is None or entry.kind != "file":
            raise UnsafeArtifact(
                f"entry {shown(name)} is a hard link to {shown(existing)}, which is not a file written earlier in the artifact"
            )
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        with os.fdopen(os.open(self._path(source), flags), "rb") as reader:
            return self.file(name, reader, size=entry.size, executable=entry.executable)

    def withhold(self, name: str, reason: str) -> None:
        """An entry that is not written — a device, a pipe, version-control internals — and why."""
        rel = self._new(name)
        self._admit(rel)
        self.entries[rel] = Entry("withheld", reason=reason)

    @property
    def withheld(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((rel, entry.reason or "") for rel, entry in self.entries.items()
                            if entry.kind == "withheld"))

    def finish(self) -> None:
        """Create every link that, followed through the tree's other links, stays inside the
        tree; withhold the rest. Called once, after the last entry."""
        if self._finished:
            return
        self._finished = True
        links = {rel: entry.target for rel, entry in self.entries.items() if entry.kind == "link"}
        for rel in sorted(links):
            target = links[rel]
            reason = _link_problem(rel, target, links)
            if reason is not None:
                self.entries[rel] = Entry("withheld", blob_id=self.entries[rel].blob_id,
                                          target=target, reason=reason)
                continue
            os.symlink(target, self._path(rel))

    def seal(self) -> None:
        """Make every file and directory written read-only (a-w), deepest first, the top last.
        Links are left alone: their own modes mean nothing, and chmod would follow them."""
        for rel in sorted(self.entries, key=lambda rel: (-rel.count("/"), rel)):
            entry = self.entries[rel]
            if entry.kind == "file":
                os.chmod(self._path(rel), 0o555 if entry.executable else 0o444)
            elif entry.kind == "dir":
                os.chmod(self._path(rel), 0o555)
        os.chmod(self.root, 0o555)

    # -- inside

    def _path(self, rel: str) -> bytes:
        return os.path.join(os.fsencode(self.root), os.fsencode(rel))

    def _new(self, name: Any) -> str:
        if self._finished:
            raise RuntimeError("the tree is finished")
        rel = self.name(name)
        if not rel:
            raise UnsafeArtifact("an entry names the top of the artifact itself")
        if rel in self.entries:
            raise UnsafeArtifact(f"entry {shown(rel)} appears more than once")
        self._parents(rel)
        return rel

    def _parents(self, rel: str) -> None:
        """Every directory above rel, made if it is not there; refused if any is not one."""
        parts = rel.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            prefix = "/".join(parts[:depth])
            entry = self.entries.get(prefix)
            if entry is None:
                self._admit(prefix)
                os.mkdir(self._path(prefix), 0o700)
                self.entries[prefix] = Entry("dir")
            elif entry.kind != "dir":
                what = {"file": "a file", "link": "a symbolic link", "withheld": "a withheld entry"}[entry.kind]
                raise UnsafeArtifact(f"entry {shown(rel)} would be written through {what} ({shown(prefix)})")

    def _admit(self, rel: str) -> None:
        self.count += 1
        if self.count > self.limits.max_entries:
            raise LimitExceeded(f"the artifact has more than {self.limits.max_entries} entries (at {shown(rel)})")

    def _blob(self, size: int | None) -> Any:
        blob = hashlib.new(self.blob_hash or "sha1")
        blob.update(b"blob %d\x00" % (size or 0))
        return blob


def _link_problem(rel: str, target: str, links: Mapping[str, str]) -> str | None:
    """Why the link at rel may not be created, or None if, followed through every link in the
    tree, it stays inside it. Lexical checks alone are not enough: a/l -> .. is inside, and so
    is b -> a/l/a/l/.. on paper, but on disk it is the directory above the tree."""
    if not target:
        return "a symbolic link with an empty target"
    if target.startswith("/"):
        return "a symbolic link to an absolute path, outside the artifact"
    if len(os.fsencode(target)) > _MAX_LINK_TARGET:
        return "a symbolic link with a target longer than can be written"
    stack = rel.split("/")[:-1]
    parts = deque(target.split("/"))
    hops = 0
    while parts:
        part = parts.popleft()
        if part in ("", "."):
            continue
        if part == "..":
            if not stack:
                return "a symbolic link that leads outside the artifact"
            stack.pop()
            continue
        here = "/".join([*stack, part])
        if here in links:
            hops += 1
            if hops > _MAX_LINK_HOPS:
                return "a symbolic link that goes round in a loop"
            onward = links[here]
            if onward.startswith("/") or not onward:
                return "a symbolic link that leads, through another, outside the artifact"
            parts.extendleft(reversed(onward.split("/")))
            continue
        stack.append(part)
    return None


# --- network sources --------------------------------------------------------------------------

_LOCAL_NAMES = ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback")
_NUMERIC_HOST = re.compile(r"[0-9.]+|0x[0-9a-fx.]+", re.I)


def https_url(text: Any) -> str:
    """The URL, normalised, if intake may fetch from it: https only — never file://, ssh, git://,
    ext:: or a local path — with no credentials in it, no fragment, and a host that is not this
    machine or a private network (by name or as an address literal). SourceRefused otherwise.
    A name that resolves to a private address is not caught here; the fetch goes through the
    host's proxy."""
    if not isinstance(text, str) or not text.strip():
        raise SourceRefused("the source is empty")
    if len(text) > 2048 or any(ch.isspace() or not ch.isprintable() for ch in text):
        raise SourceRefused(f"the source is not a plain URL: {shown(text)}")
    parts = urlsplit(text)
    scheme = parts.scheme.lower()
    if scheme != "https":
        what = f"'{shown(scheme)}'" if scheme else "a local path or scp-style address"
        raise SourceRefused(f"only https is fetched, and {shown(text)} is {what}")
    if "@" in parts.netloc or parts.username is not None or parts.password is not None:
        raise SourceRefused("the URL carries credentials: intake fetches only what is public, and never sends a secret")
    if parts.fragment:
        raise SourceRefused("the URL has a fragment, which is not part of anything fetched")
    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise SourceRefused(f"the URL has no host: {shown(text)}")
    try:
        port = parts.port
    except ValueError:
        raise SourceRefused(f"the URL's port is not a number: {shown(text)}") from None
    if _private_host(host):
        raise SourceRefused(f"{shown(host)} is this machine or a private network, and intake fetches only from the public internet")
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and port != 443:
        netloc += f":{port}"
    return urlunsplit(("https", netloc.lower(), parts.path or "/", parts.query, ""))


def _private_host(host: str) -> bool:
    lowered = host.lower()
    if lowered in _LOCAL_NAMES or lowered.endswith((".localhost", ".local", ".internal", ".localdomain")):
        return True
    try:
        address = ipaddress.ip_address(lowered)
    except ValueError:
        if _NUMERIC_HOST.fullmatch(lowered):
            return True       # 127.1, 2130706433, 0x7f.1: an address in a form fetchers read loosely
        return False
    return not address.is_global or address.is_multicast


def is_url(text: str) -> bool:
    """Whether the source is written as a URL (any scheme) rather than a path."""
    return bool(re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", text)) and not _DRIVE.match(text)


# --- the handler registry ---------------------------------------------------------------------


@dataclass(frozen=True)
class Handler:
    module: str
    name: str
    origin_kind: str
    claims: Callable[[Request], int]
    materialise: Callable[[Request, TreeWriter], Pinned]


def discover_handlers() -> tuple[tuple[Handler, ...], tuple[tuple[str, str], ...]]:
    """Every intake handler in the namespace, in module-name order, and every module that could
    not be imported or does not keep the contract, as (module, reason). Modules whose names
    start with an underscore are helpers and are passed over, as is a module with none of the
    contract's names."""
    importlib.invalidate_caches()
    package = importlib.import_module(HANDLERS_PACKAGE)
    handlers: list[Handler] = []
    broken: list[tuple[str, str]] = []
    for info in sorted(pkgutil.iter_modules(package.__path__), key=lambda found: found.name):
        if info.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"{HANDLERS_PACKAGE}.{info.name}")
        except Exception as error:
            broken.append((info.name, f"could not be imported ({type(error).__name__})"))
            continue
        claims = getattr(module, "claims", None)
        materialise = getattr(module, "materialise", None)
        origin_kind = getattr(module, "ORIGIN_KIND", None)
        if claims is None and materialise is None and origin_kind is None:
            continue
        if not callable(claims) or not callable(materialise):
            broken.append((info.name, "does not keep the handler contract (claims and materialise)"))
            continue
        if origin_kind not in ORIGIN_KINDS:
            broken.append((info.name, f"names an origin kind the model does not know ({shown(origin_kind)})"))
            continue
        name = getattr(module, "NAME", None)
        handlers.append(Handler(
            module=info.name, name=name if isinstance(name, str) and name.strip() else info.name,
            origin_kind=origin_kind, claims=claims, materialise=materialise,
        ))
    return tuple(handlers), tuple(broken)


def choose_handler(request: Request, handlers: Iterable[Handler]) -> Handler:
    """The named handler when request.kind names one; otherwise the one that claims the source
    most surely (ties go to the first by module name). NoHandler when none does."""
    handlers = tuple(handlers)
    if request.kind is not None:
        for handler in handlers:
            if request.kind in (handler.name, handler.module):
                return handler
        names = ", ".join(sorted(handler.name for handler in handlers)) or "none"
        raise NoHandler(f"there is no intake handler named {shown(request.kind)} (there are: {names})")
    best: tuple[int, Handler] | None = None
    for handler in handlers:
        try:
            score = handler.claims(request)
        except Exception:
            continue                                   # a handler that cannot tell does not claim
        if isinstance(score, int) and not isinstance(score, bool) and score > 0 and (best is None or score > best[0]):
            best = (score, handler)
    if best is None:
        if is_url(request.source):
            try:
                https_url(request.source)
            except SourceRefused as refused:
                raise NoHandler(str(refused)) from None     # the reason, not just "no handler"
        raise NoHandler(
            f"no intake handler takes {shown(request.source)}: give an https URL, an archive, a "
            "directory or a file, or name a handler with kind="
        )
    return best[1]


# --- intake -----------------------------------------------------------------------------------


def intake(source: str | os.PathLike[str], quarantine_root: str | os.PathLike[str], *,
           ref: str | None = None, kind: str | None = None, limits: Limits | None = None,
           fetchers: Mapping[str, Fetcher] | None = None, taken_at: str | None = None) -> Intake:
    """Take the source into quarantine under quarantine_root and pin it. See the module's
    docstring. Raises an IntakeError type on every failure, and then nothing is left there that
    looks complete."""
    text = os.fspath(source) if isinstance(source, os.PathLike) else source
    if not isinstance(text, str) or not text:
        raise SourceRefused("the source is empty")
    limits = limits or Limits()
    request = Request(source=text, ref=ref, kind=kind, limits=limits, fetchers=dict(fetchers or {}))
    handlers, broken = discover_handlers()
    handler = choose_handler(request, handlers)
    root = _quarantine_root(quarantine_root)
    _clear_debris(root)
    try:
        staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=root))
        scratch = Path(tempfile.mkdtemp(prefix=WORK_PREFIX, dir=root))
    except OSError as error:
        raise IntakeError(f"the quarantine root cannot be written: {type(error).__name__}") from None
    stage = f"the {handler.name} intake"
    try:
        writer = TreeWriter(staging, limits)
        pinned = handler.materialise(replace(request, scratch=scratch), writer)
        writer.finish()
        if not isinstance(pinned, Pinned):
            raise IntakeError(f"the {handler.name} handler did not say what it pinned")
        stage = "pinning the copy"
        digest = tree_digest(staging, max_entries=max(limits.max_entries, 1),
                             max_bytes=max(limits.max_total_bytes, 1))
        licence = scan.artifact_licence(staging)
        stage = "sealing the copy"
        writer.seal()
        probe = Source(origin=pinned.origin, origin_kind=handler.origin_kind,
                       pinned_ref=pinned.pinned_ref or digest, licence=licence,
                       taken_at=taken_at or utc_now(), content_digest=digest)
        stage = "moving the copy into place"
        final, reused = _settle(staging, root / probe.artifact_id, digest)
        withheld = writer.withheld
        notes = tuple(pinned.notes) + tuple(
            f"the intake handler module '{module}' {reason}" for module, reason in broken
        )
        source_record = _record(root, probe, handler.name, writer, withheld, notes, keep_time=taken_at is None)
        return Intake(source=source_record, path=final, handler=handler.name, entries=writer.count,
                      bytes=writer.bytes, withheld=withheld, notes=notes, reused=reused)
    except IntakeError:
        raise
    except TreeTooLarge as error:
        raise LimitExceeded(str(error)) from None
    except Exception as error:
        # Whatever else happens is still a failure of this intake, and is said as one.
        raise IntakeError(f"{stage} stopped: {type(error).__name__}: {shown(error)}") from error
    finally:
        remove_tree(staging)
        remove_tree(scratch)


def _quarantine_root(path: str | os.PathLike[str]) -> Path:
    root = Path(path)
    if root.is_symlink():
        raise SourceRefused(f"the quarantine root {shown(root)} is a symbolic link: give the directory itself")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not root.is_dir():
        raise SourceRefused(f"the quarantine root {shown(root)} is not a directory")
    return root.resolve()


def _clear_debris(root: Path) -> None:
    """Remove what an interrupted intake left: trash always, staging and work directories once
    they are old enough that no intake still running can own them."""
    now = time.time()
    with contextlib.suppress(OSError), os.scandir(root) as listing:
        for entry in listing:
            if not entry.is_dir(follow_symlinks=False):
                continue
            if entry.name.startswith(TRASH_PREFIX):
                remove_tree(Path(entry.path))
            elif entry.name.startswith((STAGING_PREFIX, WORK_PREFIX)):
                with contextlib.suppress(OSError):
                    if now - entry.stat(follow_symlinks=False).st_mtime > STALE_SECONDS:
                        remove_tree(Path(entry.path))


def _settle(staging: Path, final: Path, digest: str) -> tuple[Path, bool]:
    """Move the sealed staging tree to its final place in one rename. An identical copy already
    there is kept (and the staging tree dropped); anything else there is replaced."""
    for _ in range(3):
        if final.is_symlink() or final.exists():
            if not final.is_symlink() and final.is_dir():
                try:
                    if tree_digest(final) == digest:
                        return final, True
                except (OSError, TreeTooLarge):
                    pass
            trash = Path(tempfile.mkdtemp(prefix=TRASH_PREFIX, dir=final.parent))
            os.rename(final, trash / "old")
            remove_tree(trash)
        try:
            os.rename(staging, final)
            return final, False
        except OSError as error:
            if not final.exists():
                raise IntakeError(f"the copy could not be moved into place: {type(error).__name__}") from None
    raise IntakeError("another intake kept replacing the same copy")


def _record(root: Path, source: Source, handler: str, writer: TreeWriter,
            withheld: tuple[tuple[str, str], ...], notes: tuple[str, ...], *, keep_time: bool) -> Source:
    """Record this intake beside the copy and return its Source: the one recorded before, taken_at
    and all, when the same origin, kind, pin and licence were taken in before."""
    path = root / f"{source.artifact_id}{RECORD_SUFFIX}"
    records: list[dict] = []
    with contextlib.suppress(OSError, ValueError):
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict) and isinstance(loaded.get("intakes"), list):
            records = [item for item in loaded["intakes"] if isinstance(item, dict)]
    same = (source.origin, source.origin_kind, source.pinned_ref, source.licence, source.content_digest)
    for item in records:
        with contextlib.suppress(Exception):
            earlier = Source.from_dict(item.get("source"))
            if keep_time and (earlier.origin, earlier.origin_kind, earlier.pinned_ref, earlier.licence,
                              earlier.content_digest) == same:
                return earlier
    entry = {
        "source": source.to_dict(), "handler": handler, "entries": writer.count,
        "bytes": writer.bytes, "withheld": [list(item) for item in withheld], "notes": list(notes),
    }
    records = [entry, *records][:MAX_RECORDS]
    data = json.dumps({"artifact_id": source.artifact_id, "intakes": records}, indent=2, ensure_ascii=True)
    fd, temporary = tempfile.mkstemp(prefix=".record-", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(data + "\n")
        os.chmod(temporary, 0o444)
        os.replace(temporary, path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(temporary)
    return source


def intake_records(quarantine_root: str | os.PathLike[str], artifact_id: str) -> list[dict]:
    """The intakes recorded beside a copy, newest first."""
    path = Path(quarantine_root) / f"{artifact_id}{RECORD_SUFFIX}"
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in loaded.get("intakes", []) if isinstance(item, dict)] if isinstance(loaded, dict) else []


def remove_tree(path: Path) -> None:
    """Remove a quarantined or staging tree: make its directories writable again (never
    following a link), then remove it without following links."""
    target = os.fspath(path)
    if not os.path.lexists(target):
        return
    if os.path.islink(target) or not os.path.isdir(target):
        with contextlib.suppress(OSError):
            os.unlink(target)
        return
    for folder, dirs, _files in os.walk(target, topdown=True, followlinks=False):
        with contextlib.suppress(OSError):
            os.chmod(folder, 0o700)
        for name in dirs:
            child = os.path.join(folder, name)
            if not os.path.islink(child):
                with contextlib.suppress(OSError):
                    os.chmod(child, 0o700)
    shutil.rmtree(target, ignore_errors=True)


def sha256_file(path: Path) -> str:
    """The "sha256:<hex>" of a file's bytes, read without following a link."""
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    with os.fdopen(os.open(path, flags), "rb") as reader:
        while chunk := reader.read(_CHUNK):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def copy_bounded(reader: BinaryIO, out: BinaryIO, limit: int, what: str) -> str:
    """Copy at most limit bytes from reader to out, and return their "sha256:<hex>";
    LimitExceeded past the limit."""
    digest = hashlib.sha256()
    total = 0
    while chunk := reader.read(_CHUNK):
        total += len(chunk)
        if total > limit:
            raise LimitExceeded(f"{what} is over the {limit}-byte limit")
        out.write(chunk)
        digest.update(chunk)
    return "sha256:" + digest.hexdigest()
