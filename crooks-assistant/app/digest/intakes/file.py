"""Intake handler: one local file, placed alone in a quarantine directory under its own name.

An archive is taken by the archive handler, which claims it first; name this handler (kind
"file") to keep an archive as one opaque file instead. The pin is the digest of the file's
bytes, which are copied once, without following a link past the name the operator gave."""

from __future__ import annotations

import os
import stat

from app.digest.intake import IntakeError, Pinned, Request, SourceRefused, TreeWriter, is_url, shown

NAME = "file"
ORIGIN_KIND = "file"


def claims(request: Request) -> int:
    if is_url(request.source):
        return 0
    return 10 if os.path.isfile(request.source) else 0


def materialise(request: Request, writer: TreeWriter) -> Pinned:
    path = os.path.abspath(request.source)
    name = os.path.basename(path)
    if not os.path.isfile(path) or not name:
        raise SourceRefused(f"{shown(path)} is not a file")
    with open(path, "rb") as reader:
        if not stat.S_ISREG(os.fstat(reader.fileno()).st_mode):
            raise IntakeError(f"{shown(path)} is not a regular file")
        pinned = writer.file(name, reader, executable=bool(os.fstat(reader.fileno()).st_mode & 0o111))
    return Pinned(origin=path, pinned_ref=pinned)
