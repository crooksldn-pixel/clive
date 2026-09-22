#!/usr/bin/env python3
"""Structural consistency checks for the canonical product-memory Markdown.

These documents are the durable source of product intent, and they are written
as often by a model through a JSON or shell layer as by a person in an editor.
That is how ``DEC-052`` arrived as one 3788-character line whose paragraph
breaks were the two characters ``\\n`` rather than newlines: the prose was
right and the file was corrupt, and nothing in the repository noticed.

So this checks the shape of the files, never their opinions. It reads the
directory, reports every violation it finds, and prints machine-readable JSON
on request so an acceptance run can carry the result as evidence.

    python scripts/product_memory_check.py           # human-readable
    python scripts/product_memory_check.py --json    # one JSON object

Exit status is 0 only when every check passes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs" / "product-memory"
INDEX = "README.md"

# A literal backslash followed by one of these is escape corruption in Markdown
# prose: Markdown has no such escapes, so their presence means some layer wrote
# a string it never unescaped.
_ESCAPES = {
    r"\n": "newline",
    r"\r": "carriage return",
    r"\t": "tab",
}

_LINK_RE = re.compile(r"\]\(\./([A-Za-z0-9_.-]+\.md)\)")
_FENCE_RE = re.compile(r"^\s*```")


@dataclass(frozen=True, slots=True)
class Violation:
    check: str
    path: str
    line: int | None
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "check": self.check,
            "path": self.path,
            "line": self.line,
            "detail": self.detail,
        }


def _outside_fences(text: str):
    """Yield ``(line_number, line)`` for lines that are not inside a code fence.

    Escaped quotes and backslashes are legitimate *inside* a fenced block — it
    may be quoting JSON or shell. Outside one they are corruption.
    """

    in_fence = False
    for number, line in enumerate(text.split("\n"), start=1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield number, line


def check_escaped_control_characters(path: Path, text: str) -> list[Violation]:
    """No literal ``\\n``/``\\r``/``\\t`` anywhere in canonical Markdown.

    This one is deliberately not fence-aware. A code fence may quote a string
    containing ``\\n``, but the corruption this guards against fuses whole
    documents onto one line — including their fences — so a fence-aware reader
    would be reading a fence that the corruption had already destroyed.
    """

    found: list[Violation] = []
    for number, line in enumerate(text.split("\n"), start=1):
        for escape, name in _ESCAPES.items():
            if escape in line:
                found.append(
                    Violation(
                        "escaped_control_character",
                        path.name,
                        number,
                        f"literal {escape!r} ({name}) in Markdown prose; "
                        f"line is {len(line)} characters long",
                    )
                )
    return found


def check_escaped_quotes(path: Path, text: str) -> list[Violation]:
    """No literal ``\\"`` outside a code fence."""

    return [
        Violation(
            "escaped_quote",
            path.name,
            number,
            'literal \'\\"\' outside a code fence',
        )
        for number, line in _outside_fences(text)
        if '\\"' in line
    ]


def check_has_title(path: Path, text: str) -> list[Violation]:
    """Every canonical document opens with a level-1 heading."""

    first = next((line for line in text.split("\n") if line.strip()), "")
    if first.startswith("# "):
        return []
    return [Violation("missing_title", path.name, 1, f"first non-blank line is {first[:60]!r}")]


def check_no_carriage_returns(path: Path, text: str) -> list[Violation]:
    if "\r" not in text:
        return []
    return [Violation("carriage_return", path.name, None, "file contains CR characters")]


def check_index(docs: Path, names: list[str]) -> list[Violation]:
    """``README.md`` indexes every document, and indexes nothing missing."""

    index = docs / INDEX
    if not index.is_file():
        return [Violation("missing_index", INDEX, None, "canonical index is absent")]

    linked = set(_LINK_RE.findall(index.read_text(encoding="utf-8")))
    expected = {name for name in names if name != INDEX}

    found = [
        Violation("unindexed_document", name, None, f"{name} is not linked from {INDEX}")
        for name in sorted(expected - linked)
    ]
    found += [
        Violation("dangling_index_link", INDEX, None, f"{INDEX} links {name}, which does not exist")
        for name in sorted(linked - expected)
    ]
    return found


def run(docs: Path = DOCS) -> dict[str, object]:
    """Run every structural check and return a machine-readable report."""

    if not docs.is_dir():
        return {
            "check": "product_memory_structure",
            "ok": False,
            "documents": 0,
            "violations": [
                Violation("missing_directory", str(docs), None, "not a directory").as_dict()
            ],
        }

    paths = sorted(docs.glob("*.md"))
    names = [path.name for path in paths]

    violations: list[Violation] = []
    for path in paths:
        # Read bytes, not text: ``read_text`` applies universal newlines and
        # would silently swallow the carriage returns one of these checks is
        # looking for.
        text = path.read_bytes().decode("utf-8")
        violations += check_escaped_control_characters(path, text)
        violations += check_escaped_quotes(path, text)
        violations += check_has_title(path, text)
        violations += check_no_carriage_returns(path, text)
    violations += check_index(docs, names)

    return {
        "check": "product_memory_structure",
        "ok": not violations,
        "documents": len(paths),
        "violations": [violation.as_dict() for violation in violations],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    parser.add_argument("--docs", type=Path, default=DOCS, help="directory to check")
    args = parser.parse_args(argv)

    report = run(args.docs)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        violations = report["violations"]
        assert isinstance(violations, list)
        for violation in violations:
            where = violation["path"]
            if violation["line"] is not None:
                where = f"{where}:{violation['line']}"
            print(f"{where}: {violation['check']}: {violation['detail']}")
        verdict = "ok" if report["ok"] else f"{len(violations)} violation(s)"
        print(f"{report['documents']} canonical document(s) checked — {verdict}")

    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
