#!/usr/bin/env python3
"""Digest a quarantined directory: recognise, scan and decompose it, and say what it holds.

    python scripts/digest.py PATH --origin ORIGIN [--origin-kind directory]
        [--pinned-ref REF] [--licence L] [--store DIR] [--report FILE]

PATH is the quarantined copy, already in place: this reads it and never executes, imports or
installs anything in it, and uses no network. The content digest is computed from the tree
itself (pipeline.tree_digest: sorted relative paths and bytes, symbolic links named and never
followed, bounded) and pins the Source when --pinned-ref is not given. With --store the source,
artifact, units and findings are written to that digest store; the same intake digested again
(same origin, kind, pinned reference and licence) keeps the time it was first taken, so a
re-run changes nothing. With --report the Markdown report is written to FILE.

One line is printed: the artifact, its Units, its findings by severity and its kinds.

Exit status: 0 digested; 2 blocked in quarantine by a block-severity finding, before
decomposition; 1 could not digest (bad arguments, not a directory, too large to pin, a
different record already stored under this artifact's id, or a file that cannot be written).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The script runs standalone (python scripts/digest.py); it must find the app package.
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.digest.model import ORIGIN_KINDS, SEVERITIES, Source, utc_now  # noqa: E402
from app.digest.pipeline import DigestResult, digest, tree_digest  # noqa: E402
from app.digest.report import render  # noqa: E402
from app.digest.store import ArtifactConflict, DigestStore  # noqa: E402

DIGESTED = 0
FAILED = 1
BLOCKED = 2


class _Parser(argparse.ArgumentParser):
    """Bad arguments exit 1, so that 2 always means blocked."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(FAILED, f"{self.prog}: error: {message}\n")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description="Digest a quarantined directory into Units, findings and a report.")
    parser.add_argument("path", type=Path, help="the quarantined directory to digest")
    parser.add_argument("--origin", required=True, help="where the artifact came from: a URL or path, as given")
    parser.add_argument("--origin-kind", default="directory", choices=ORIGIN_KINDS)
    parser.add_argument("--pinned-ref", help="commit SHA or other pin (default: the content digest)")
    parser.add_argument("--licence", help="the artifact's licence, when known")
    parser.add_argument("--store", type=Path, help="digest store directory to write to")
    parser.add_argument("--report", type=Path, help="file to write the Markdown report to")
    return parser


def summary(result: DigestResult) -> str:
    counts = {severity: 0 for severity in SEVERITIES}
    for finding in result.findings:
        counts[finding.severity] += 1
    by_severity = ", ".join(f"{severity} {counts[severity]}" for severity in reversed(SEVERITIES))
    return (
        f"{'blocked' if result.blocked else 'digested'} {result.artifact.id}: "
        f"{len(result.artifact.units)} units; findings: {by_severity}; "
        f"kinds: {', '.join(result.artifact.kinds) or 'none'}"
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        pinned = tree_digest(args.path)
        source = Source(
            origin=args.origin, origin_kind=args.origin_kind, pinned_ref=args.pinned_ref or pinned,
            licence=args.licence, taken_at=utc_now(), content_digest=pinned,
        )
        store = DigestStore(args.store) if args.store is not None else None
        if store is not None and store.has(source.artifact_id):
            stored = store.load(source.artifact_id).source
            if _same_intake(stored, source):
                source = stored
        result = digest(args.path, source, store)
        if args.report is not None:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(render(result), encoding="utf-8")
    except ArtifactConflict as error:
        print(f"digest: {error}", file=sys.stderr)
        return FAILED
    except (OSError, ValueError) as error:
        print(f"digest: {type(error).__name__}: {error}", file=sys.stderr)
        return FAILED
    print(summary(result))
    return BLOCKED if result.blocked else DIGESTED


def _same_intake(stored: Source, source: Source) -> bool:
    return (stored.origin, stored.origin_kind, stored.pinned_ref, stored.licence) == (
        source.origin, source.origin_kind, source.pinned_ref, source.licence,
    )


if __name__ == "__main__":
    sys.exit(main())
