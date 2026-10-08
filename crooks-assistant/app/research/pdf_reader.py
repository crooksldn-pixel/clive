"""A PDF's words, read in a process of its own: app/research/convert.py runs this file, never calls it.

Why this exists: pypdf is the one part of reading research that parses a hostile binary format, and
bugs that make a parser loop or eat memory keep being found in it (49 advisories fixed from 6.0.0
to 6.19.0, the last published 1 Oct 2026). So a PDF George gives is never parsed in the app's
process (review note 3, 8 Oct): convert.py runs this file with the app's own Python in isolated
mode (-I: no user site, no PYTHON* variables, not even this folder on the path) and an environment
holding only a locale, hands it the bytes on stdin, and kills it when it runs past PDF_SECONDS.

What it promises:
- It imports nothing from CLIVE, so nothing of the app's (settings, keys, open connections) is in
  reach of the file it reads.
- Before pypdf is imported it caps its own address space and CPU time (resource.setrlimit), so a
  PDF that would eat memory or spin is stopped by the kernel as well as by the parent's timeout.
  Where a limit can't be set (macOS takes no address-space limit) the timeout still holds.
- It writes one JSON object to stdout and exits 0: {"pages": [...], "total": n, "unread": k}, or
  {"error": "missing" | "locked" | "unreadable" | "memory", "type": "..."}. Anything else (killed,
  crashed) the parent reports as a PDF that couldn't be read.

Usage (by convert.py): python -I pdf_reader.py <max pages> <memory bytes> <cpu seconds> < file.pdf
"""

import io
import json
import resource
import sys


def limit(memory: int, seconds: int) -> None:
    """Cap this process's address space and CPU time, never above a hard limit already set."""
    for which, value in ((resource.RLIMIT_AS, memory), (resource.RLIMIT_CPU, seconds)):
        try:
            _soft, hard = resource.getrlimit(which)
            resource.setrlimit(which, (value if hard == resource.RLIM_INFINITY else min(value, hard), hard))
        except (ValueError, OSError):
            pass


def read(data: bytes, max_pages: int) -> dict:
    """The text of each page, up to max_pages; a page that can't be read is counted, not fatal."""
    try:
        from pypdf import PdfReader
    except ImportError:
        return {"error": "missing"}
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            return {"error": "locked"}
        pages = list(reader.pages)
    except MemoryError:
        raise
    except Exception as exc:  # noqa: BLE001 - whatever the parser raised, the file couldn't be read
        return {"error": "unreadable", "type": type(exc).__name__}
    out: list[str] = []
    unread = 0
    for page in pages[:max_pages]:
        try:
            out.append(page.extract_text() or "")
        except MemoryError:
            raise
        except Exception:  # noqa: BLE001 - one bad page is a note, not the whole file lost
            unread += 1
            out.append("")
    return {"pages": out, "total": len(pages), "unread": unread}


def main(argv: list[str]) -> int:
    max_pages, memory, seconds = (int(x) for x in argv[1:4])
    data = sys.stdin.buffer.read()
    limit(memory, seconds)
    try:
        said = read(data, max_pages)
    except MemoryError:
        said = {"error": "memory"}
    sys.stdout.write(json.dumps(said))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
