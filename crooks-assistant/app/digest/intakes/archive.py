"""Intake handler: an archive file — zip, tar, and tar compressed with gzip, bzip2 or xz.

The archive is first copied into the intake's private scratch directory (bounded, and hashed as
it is copied), so what is unpacked is exactly what was pinned, whatever happens to the original
afterwards. Its format is read from its first bytes, never from its name. Then it is unpacked
entry by entry through the TreeWriter, which refuses names that escape and entries written
through links, withholds devices, pipes and links that lead out, and copies hard links; this
module adds what only an archive can do wrong:

- a decompression bomb: the bytes expanded are counted as they are read, and past
  Limits.ratio_floor they may not exceed Limits.max_ratio times the archive's size; a zip entry
  that declares more is refused before it is read, and so are zip entries whose data overlaps
  (the "overlapping files" bomb, many entries sharing one compressed kernel);
- a header bomb: a tar pax or GNU long-name header is read into memory by tarfile, so one that
  declares more than MAX_HEADER_BYTES is refused before it is read;
- too many entries, or too many bytes in all, from the zip's central directory before any is
  read, and as they are read for tar;
- encryption: an encrypted zip entry is refused plainly — no password is ever asked for;
- a lie: an entry that holds other than the size it declares, or fails its checksum.

The unpackers (unpack_file, unpack_tar_stream, unpack_zip) are used by the other handlers too:
git materialises a commit through unpack_tar_stream, and url unpacks what it downloads."""

from __future__ import annotations

import bz2
import gzip
import io
import lzma
import os
import stat
import tarfile
import zipfile
import zlib
from pathlib import Path
from typing import BinaryIO

from app.digest.intake import (
    ArchiveUnreadable,
    LimitExceeded,
    Limits,
    Pinned,
    Request,
    SourceRefused,
    TreeWriter,
    UnsafeArtifact,
    copy_bounded,
    is_url,
    shown,
)

NAME = "archive"
ORIGIN_KIND = "archive"

MAX_HEADER_BYTES = 1 << 20      # a pax or GNU long-name header read into memory
_HEADER_SLACK = 2048            # tar header and padding bytes allowed per entry
_PROBE = 512 + 8

# Formats by their first bytes. A tar holds "ustar" at offset 257 (POSIX and GNU alike).
_MAGIC = (
    ("zip", 0, b"PK\x03\x04"),
    ("zip", 0, b"PK\x05\x06"),          # an empty zip
    ("gzip", 0, b"\x1f\x8b"),
    ("bzip2", 0, b"BZh"),
    ("xz", 0, b"\xfd7zXZ\x00"),
    ("tar", 257, b"ustar"),
)
_UNSUPPORTED = (
    ("zstd", 0, b"\x28\xb5\x2f\xfd"),
    ("7z", 0, b"7z\xbc\xaf\x27\x1c"),
    ("rar", 0, b"Rar!\x1a\x07"),
)
_OPENERS = {
    "gzip": lambda raw: gzip.GzipFile(fileobj=raw, mode="rb"),
    "bzip2": lambda raw: bz2.BZ2File(raw, mode="rb"),
    "xz": lambda raw: lzma.LZMAFile(raw, mode="rb"),
    "tar": lambda raw: raw,
}
_READ_ERRORS = (tarfile.TarError, zipfile.BadZipFile, EOFError, zlib.error, lzma.LZMAError, OSError, ValueError)


def archive_format(path: str | os.PathLike[str]) -> str | None:
    """"zip", "tar", "gzip", "bzip2" or "xz" by the file's first bytes (a compressed stream is
    taken to hold a tar), or None; SourceRefused for a format known but not supported."""
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    with os.fdopen(os.open(path, flags), "rb") as reader:
        head = reader.read(_PROBE)
    for name, offset, magic in _UNSUPPORTED:
        if head[offset:offset + len(magic)] == magic:
            raise SourceRefused(f"{name} archives are not supported yet")
    for name, offset, magic in _MAGIC:
        if head[offset:offset + len(magic)] == magic:
            return name
    return None


def claims(request: Request) -> int:
    if is_url(request.source) or not os.path.isfile(request.source):
        return 0
    try:
        return 80 if archive_format(request.source) else 0
    except SourceRefused:
        return 80           # an archive of a format not read yet: say so, rather than keep it opaque
    except OSError:
        return 0


def materialise(request: Request, writer: TreeWriter) -> Pinned:
    source = Path(request.source)
    if not source.is_file():
        raise SourceRefused(f"{shown(source)} is not a file")
    assert request.scratch is not None
    copy = request.scratch / "archive"
    with open(source, "rb") as reader, open(copy, "xb") as out:
        pinned = copy_bounded(reader, out, request.limits.max_download_bytes, f"the archive {shown(source.name)}")
    kind = archive_format(copy)
    if kind is None:
        raise SourceRefused(f"{shown(source.name)} is not an archive intake can read (zip, tar, tar.gz, tar.bz2, tar.xz)")
    unpack_file(copy, kind, writer)
    return Pinned(origin=os.path.abspath(source), pinned_ref=pinned,
                  notes=(f"unpacked from a {kind} archive",))


def unpack_file(path: Path, kind: str, writer: TreeWriter) -> None:
    """Unpack the archive at path, of the format archive_format named, through the writer."""
    if kind == "zip":
        unpack_zip(path, writer)
        return
    size = os.path.getsize(path)
    try:
        with open(path, "rb") as raw, _OPENERS[kind](raw) as expanded:
            unpack_tar_stream(expanded, writer, compressed_size=size if kind != "tar" else None)
    except (LimitExceeded, UnsafeArtifact, SourceRefused, ArchiveUnreadable):
        raise
    except _READ_ERRORS as error:
        raise ArchiveUnreadable(f"the {kind} archive could not be read to its end: {type(error).__name__}") from None


# --- tar ---------------------------------------------------------------------------------------


class _Bounded(io.RawIOBase):
    """The expanded stream, counted: past its budget, or past the ratio a bomb would show, a read
    is refused before it is made."""

    def __init__(self, raw: BinaryIO, limits: Limits, compressed_size: int | None) -> None:
        self._raw = raw
        self._limits = limits
        self._compressed = compressed_size
        self._budget = limits.max_total_bytes + limits.max_entries * _HEADER_SLACK + (1 << 20)
        self.count = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        remaining = self._budget - self.count
        if size is None or size < 0 or size > remaining + 1:
            size = remaining + 1        # never ask for more than would already be too much
        data = self._raw.read(size)
        self.count += len(data)
        if self.count > self._budget:
            raise LimitExceeded(f"the archive expands past the {self._limits.max_total_bytes}-byte limit")
        if (
            self._compressed is not None and self.count > self._limits.ratio_floor
            and self.count > self._limits.max_ratio * max(self._compressed, 1)
        ):
            raise UnsafeArtifact(
                f"the archive expands more than {self._limits.max_ratio:g} times its size: a decompression bomb"
            )
        return data

    def readinto(self, buffer) -> int:  # type: ignore[override]
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


_LONG_HEADERS = frozenset((tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.SOLARIS_XHDTYPE,
                           tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK))


class _GuardedTarInfo(tarfile.TarInfo):
    """A tar header that refuses, before tarfile reads it into memory, an extended header larger
    than MAX_HEADER_BYTES."""

    def _proc_member(self, tarfile_: tarfile.TarFile):  # type: ignore[override]
        if self.type in _LONG_HEADERS and self.size > MAX_HEADER_BYTES:
            raise UnsafeArtifact(f"a tar header declares {self.size} bytes of names or attributes: a header bomb")
        return super()._proc_member(tarfile_)


def unpack_tar_stream(stream: BinaryIO, writer: TreeWriter, *, compressed_size: int | None = None) -> None:
    """Unpack an uncompressed tar stream (read once, front to back) through the writer."""
    bounded = _Bounded(stream, writer.limits, compressed_size)
    try:
        with tarfile.open(fileobj=bounded, mode="r|", tarinfo=_GuardedTarInfo) as archive:
            for member in archive:
                _tar_member(archive, member, writer)
    except (LimitExceeded, UnsafeArtifact, SourceRefused, ArchiveUnreadable):
        raise
    except _READ_ERRORS as error:
        raise ArchiveUnreadable(f"the tar stream could not be read to its end: {type(error).__name__}") from None


def _tar_member(archive: tarfile.TarFile, member: tarfile.TarInfo, writer: TreeWriter) -> None:
    name = member.name
    if member.isdir():
        writer.directory(name)
    elif member.isreg():
        if member.size > writer.limits.max_file_bytes:
            raise LimitExceeded(f"{shown(name)} is {member.size} bytes, over the {writer.limits.max_file_bytes}-byte limit on one file")
        reader = archive.extractfile(member)
        if reader is None:
            raise ArchiveUnreadable(f"{shown(name)} could not be read from the archive")
        with reader:
            writer.file(name, reader, size=member.size, executable=bool(member.mode & 0o111))
    elif member.issym():
        writer.symlink(name, member.linkname)
    elif member.islnk():
        writer.copy(name, member.linkname)
    elif member.ischr() or member.isblk():
        writer.withhold(name, "a device file: never created in quarantine")
    elif member.isfifo():
        writer.withhold(name, "a named pipe: never created in quarantine")
    else:
        writer.withhold(name, f"an entry of a tar type intake does not write ({shown(member.type)})")


# --- zip ---------------------------------------------------------------------------------------

_ZIP_ENCRYPTED = 0x1
_LOCAL_HEADER = 30


def unpack_zip(path: Path, writer: TreeWriter) -> None:
    """Unpack the zip at path through the writer, after checking its central directory for
    encryption, overlap, and the counts, sizes and ratios a bomb would show."""
    limits = writer.limits
    size = os.path.getsize(path)
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            _check_zip(infos, size, limits)
            for info in infos:
                _zip_member(archive, info, writer)
    except (LimitExceeded, UnsafeArtifact, SourceRefused, ArchiveUnreadable):
        raise
    except NotImplementedError:
        raise SourceRefused("the zip uses a compression method intake cannot read") from None
    except RuntimeError as error:                        # zipfile's word for "needs a password"
        raise SourceRefused(f"the zip could not be read without a password ({type(error).__name__})") from None
    except _READ_ERRORS as error:
        raise ArchiveUnreadable(f"the zip could not be read to its end: {type(error).__name__}") from None


def _check_zip(infos: list[zipfile.ZipInfo], size: int, limits: Limits) -> None:
    if len(infos) > limits.max_entries:
        raise LimitExceeded(f"the zip has {len(infos)} entries, more than the {limits.max_entries} allowed")
    declared = 0
    for info in infos:
        if info.flag_bits & _ZIP_ENCRYPTED:
            raise SourceRefused(
                f"the zip is encrypted (at {shown(info.filename)}): intake never asks for a password, "
                "so an encrypted archive cannot be taken in"
            )
        if info.file_size > limits.max_file_bytes:
            raise LimitExceeded(f"{shown(info.filename)} declares {info.file_size} bytes, over the {limits.max_file_bytes}-byte limit on one file")
        if info.file_size > limits.ratio_floor and info.file_size > limits.max_ratio * max(info.compress_size, 1):
            raise UnsafeArtifact(
                f"{shown(info.filename)} expands more than {limits.max_ratio:g} times: a decompression bomb"
            )
        declared += info.file_size
    if declared > limits.max_total_bytes:
        raise LimitExceeded(f"the zip declares {declared} bytes, over the {limits.max_total_bytes}-byte limit")
    if declared > limits.ratio_floor and declared > limits.max_ratio * max(size, 1):
        raise UnsafeArtifact(f"the zip expands more than {limits.max_ratio:g} times its size: a decompression bomb")
    ordered = sorted(infos, key=lambda info: info.header_offset)
    for this, following in zip(ordered, ordered[1:], strict=False):
        if this.header_offset + _LOCAL_HEADER + this.compress_size > following.header_offset:
            raise UnsafeArtifact(
                f"zip entries {shown(this.filename)} and {shown(following.filename)} share their data: "
                "overlapping entries are how zip bombs multiply one compressed kernel"
            )


def _zip_member(archive: zipfile.ZipFile, info: zipfile.ZipInfo, writer: TreeWriter) -> None:
    name = writer.name(info.filename, backslash_is_separator=True)
    mode = (info.external_attr >> 16) & 0xFFFF if info.create_system == 3 else 0
    kind = stat.S_IFMT(mode)
    if kind == stat.S_IFLNK:
        if info.file_size > 4096:
            writer.withhold(name, "a symbolic link with a target longer than can be written")
            return
        target = archive.read(info).decode("utf-8", "surrogateescape")
        writer.symlink(name, target)
    elif info.is_dir() or kind == stat.S_IFDIR:
        writer.directory(name)
    elif kind in (0, stat.S_IFREG):
        with archive.open(info) as reader:
            writer.file(name, reader, size=info.file_size, executable=bool(mode & 0o111))
    else:
        writer.withhold(name, "a device, pipe or socket: never created in quarantine")
