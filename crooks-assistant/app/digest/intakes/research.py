"""Intake handler: one research file George gave CLIVE, as the Markdown it holds.

Why this exists: research (KNOWLEDGE_DIGESTER_V1.md; docs/RESEARCH.md) comes as a PDF, a Word
file, Markdown, text, a saved web page or a ChatGPT export, and the digester reads only text. This
handler reads the file once (app/research/convert.py), and writes what it says, as Markdown (or the
page's HTML), into the quarantine tree, so the scanner scans, and the documents adapter reads,
exactly what the model is later shown.

What it promises:
- It is used only when named (kind="research"): it claims nothing on its own, so digesting any
  other file is as it was.
- The pin is the digest of the file's bytes as given; the origin is the file's own name, never
  a folder on the server.
- What it could not read stops the intake with George's words (SourceRefused); what it left out
  is in the intake's notes."""

from __future__ import annotations

import hashlib
import os
import stat

from app.digest.intake import IntakeError, Pinned, Request, SourceRefused, TreeWriter, is_url, shown

NAME = "research"
ORIGIN_KIND = "upload"


def claims(request: Request) -> int:
    return 0


def materialise(request: Request, writer: TreeWriter) -> Pinned:
    from app.research.convert import MAX_FILE_BYTES, ConvertError, convert

    if is_url(request.source):
        raise SourceRefused("research is taken as a file, not a link: save the page or export the report, then give the file")
    path = os.path.abspath(request.source)
    name = os.path.basename(path)
    with open(path, "rb") as reader:
        info = os.fstat(reader.fileno())
        if not stat.S_ISREG(info.st_mode):
            raise IntakeError(f"{shown(path)} is not a regular file")
        data = reader.read(MAX_FILE_BYTES + 1)
    try:
        converted = convert(name, data)
    except ConvertError as exc:
        raise SourceRefused(str(exc)) from None
    for rel, text in converted.files:
        writer.file(rel, text.encode("utf-8"))
    pinned = "sha256:" + hashlib.sha256(data).hexdigest()
    return Pinned(origin=f"research:{name}", pinned_ref=pinned, notes=tuple(converted.notes))
