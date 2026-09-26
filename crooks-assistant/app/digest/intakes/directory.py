"""Intake handler: a local directory, copied into quarantine.

The directory named is the top of the artifact (it is what the operator gave); inside it
nothing is followed. Directories are listed and opened through descriptors checked to be the
ones listed, and files opened relative to them without following links, so a directory or file
swapped for a link while the copy is made is refused, never followed. Symbolic links are copied
as links when they stay inside the copy, and withheld when they lead out; pipes, sockets and
devices are withheld; a hard-linked file is copied as an independent file.

Version-control internals (.git, .hg, .svn) are not copied: they are withheld, and said so. A
working tree's history is not the artifact, and git is never run in a directory intake did not
make — its config could name a program to run. To pin a commit, take the repository by its
URL. The pin here is the copy's content digest."""

from __future__ import annotations

import os
import stat

from app.digest.intake import (
    IntakeError,
    Pinned,
    Request,
    SourceRefused,
    TreeWriter,
    is_url,
    shown,
)

NAME = "directory"
ORIGIN_KIND = "directory"

VCS_DIRECTORIES = frozenset((".git", ".hg", ".svn"))
_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)


def claims(request: Request) -> int:
    if is_url(request.source):
        return 0
    return 50 if os.path.isdir(request.source) else 0


def materialise(request: Request, writer: TreeWriter) -> Pinned:
    top = os.path.abspath(request.source)
    if not os.path.isdir(top):
        raise SourceRefused(f"{shown(top)} is not a directory")
    fd = os.open(top, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))
    pending: list[tuple[str, int, tuple[int, int]]] = []
    info = os.fstat(fd)
    pending.append(("", fd, (info.st_dev, info.st_ino)))
    try:
        while pending:
            rel, folder, _ident = pending.pop()
            try:
                children = _copy_folder(rel, folder, writer)
            finally:
                os.close(folder)
            pending.extend(children)
    finally:
        for _rel, folder, _ident in pending:
            os.close(folder)
    return Pinned(origin=top, pinned_ref=None)


def _copy_folder(rel: str, folder: int, writer: TreeWriter) -> list[tuple[str, int, tuple[int, int]]]:
    children: list[tuple[str, int, tuple[int, int]]] = []
    with os.scandir(folder) as listing:
        entries = sorted(listing, key=lambda entry: os.fsencode(entry.name))
    try:
        for entry in entries:
            name = f"{rel}/{entry.name}" if rel else entry.name
            if entry.name in VCS_DIRECTORIES:
                writer.withhold(name, "version-control internals are not copied: take the repository by its URL to pin a commit")
            elif entry.is_symlink():
                writer.symlink(name, os.readlink(entry.name, dir_fd=folder))
            elif entry.is_dir(follow_symlinks=False):
                listed = entry.stat(follow_symlinks=False)
                child = os.open(entry.name, _DIR_FLAGS, dir_fd=folder)
                opened = os.fstat(child)
                if (opened.st_dev, opened.st_ino) != (listed.st_dev, listed.st_ino):
                    os.close(child)
                    raise IntakeError(f"{shown(name)} changed while it was being copied")
                writer.directory(name)
                children.append((name, child, (opened.st_dev, opened.st_ino)))
            elif entry.is_file(follow_symlinks=False):
                _copy_file(name, entry.name, folder, writer)
            else:
                writer.withhold(name, "a pipe, socket or device: never created in quarantine")
    except BaseException:
        for _name, child, _ident in children:
            os.close(child)
        raise
    return children


def _copy_file(name: str, entry_name: str, folder: int, writer: TreeWriter) -> None:
    try:
        fd = os.open(entry_name, _FILE_FLAGS, dir_fd=folder)
    except OSError as error:
        raise IntakeError(f"{shown(name)} could not be opened: {type(error).__name__}") from None
    with os.fdopen(fd, "rb") as reader:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise IntakeError(f"{shown(name)} is no longer a regular file")
        writer.file(name, reader, executable=bool(info.st_mode & 0o111))
