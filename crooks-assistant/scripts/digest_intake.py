#!/usr/bin/env python3
"""Take an artifact into quarantine, then digest it: intake, recognise, scan and decompose.

    python scripts/digest_intake.py SOURCE [--ref REF] [--kind HANDLER] --quarantine DIR
        [--store DIR] [--report FILE] [--no-relate | --self-model-root ROOT] [--self] [--curated]

SOURCE is an https URL (a git repository, or a single file or archive to download), a package
by its registry name (npm:<name>[@<version>], pypi:<name>[==<version>]), an archive, a
directory or a file. Intake (app/digest/intake.py) is the only step that uses the network,
and only to fetch: it pins the source (the commit SHA, or the digest of the bytes fetched),
copies it read-only into a directory of its own under --quarantine, which must be outside this
repository, and records its Source. The quarantined copy is then digested exactly as
scripts/digest.py digests one — nothing in it is executed, imported or installed. --ref picks a
branch, tag or full commit SHA of a git repository, or a package's version; --kind names the
intake handler when the source could be taken more than one way (git, url, package, archive,
directory, file, or any handler added to app/digest/intakes). The Units are related to CLIVE's
self-model and CLIVE's proposals made exactly as scripts/digest.py does it, with the same
arguments: --no-relate skips both, --self-model-root generates the self-model from another
checkout of CLIVE, and --self takes the artifact as CLIVE itself: traced to its product memory,
nothing proposed. --curated says the owner listed this artifact's skills himself, as
scripts/digest.py takes it, and is refused with --self or --no-relate. What intake withheld and noted is carried into the digest's result and report.

One line is printed, as scripts/digest.py prints it; what intake pinned, where the copy is and
anything it withheld are said on standard error.

Exit status: 0 digested; 2 blocked — refused in quarantine as unsafe (a name that escapes, a
decompression bomb, a tree that is not its commit's) or stopped there by a block-severity
finding before decomposition; 1 could not digest (bad arguments, a source refused or not
fetched, past a limit, a different record already stored under this artifact's id, or a file
that cannot be written)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The script runs standalone (python scripts/digest_intake.py); it must find the app package.
_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from app.digest.intake import IntakeError, UnsafeArtifact, intake, shown  # noqa: E402
from app.digest.model import Source  # noqa: E402
from app.digest.pipeline import digest  # noqa: E402
from app.digest.store import ArtifactConflict, DigestStore  # noqa: E402
from scripts.digest import (  # noqa: E402
    BLOCKED,
    FAILED,
    add_relating,
    finish,
    purpose_of,
    relating_problem,
    self_model_for,
)

# The repository this script belongs to: third-party content must never land inside it.
REPOSITORY = _APP_ROOT.parent


class _Parser(argparse.ArgumentParser):
    """Bad arguments exit 1, so that 2 always means blocked."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(FAILED, f"{self.prog}: error: {message}\n")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(description="Take an artifact into quarantine and digest it.")
    parser.add_argument("source", help="an https URL, a package (npm:<name>, pypi:<name>), an "
                                       "archive, a directory or a file")
    parser.add_argument("--ref", help="a git repository's branch, tag or full commit SHA")
    parser.add_argument("--kind", help="the intake handler to use (default: the one that claims the source)")
    parser.add_argument("--quarantine", type=Path, required=True,
                        help="the quarantine root, outside this repository")
    parser.add_argument("--store", type=Path, help="digest store directory to write to")
    parser.add_argument("--report", type=Path, help="file to write the Markdown report to")
    add_relating(parser)
    return parser


def inside_repository(path: Path) -> bool:
    resolved = path.resolve()
    return resolved == REPOSITORY or REPOSITORY in resolved.parents


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    problem = relating_problem(args)
    if problem is not None:
        print(f"digest_intake: {problem}", file=sys.stderr)
        return FAILED
    if inside_repository(args.quarantine):
        print(f"digest_intake: the quarantine {shown(args.quarantine)} is inside this repository; "
              "put it outside, so no third-party content can be committed", file=sys.stderr)
        return FAILED
    try:
        taken = intake(args.source, args.quarantine, ref=args.ref, kind=args.kind)
    except UnsafeArtifact as error:
        print(f"digest_intake: blocked in quarantine: {error}", file=sys.stderr)
        return BLOCKED
    except IntakeError as error:
        print(f"digest_intake: {type(error).__name__}: {error}", file=sys.stderr)
        return FAILED
    source = taken.source
    print(
        f"intake: {taken.handler} {shown(source.origin)} pinned {shown(source.pinned_ref)}; "
        f"licence {shown(source.licence or 'none found')}; {taken.entries} entries, {taken.bytes} bytes"
        f"{', reused' if taken.reused else ''} -> {taken.path}",
        file=sys.stderr,
    )
    for path, reason in taken.withheld:
        print(f"intake: withheld {shown(path)}: {reason}", file=sys.stderr)
    for note in taken.notes:
        print(f"intake: {note}", file=sys.stderr)
    try:
        store = DigestStore(args.store) if args.store is not None else None
        if store is not None and store.has(source.artifact_id):
            stored = store.load(source.artifact_id).source
            if _same_intake(stored, source):
                source = stored
        result = digest(taken.path, source, store, self_model=self_model_for(args),
                        purpose=purpose_of(args), withheld=taken.withheld, notes=taken.notes,
                        curated=args.curated)
    except ArtifactConflict as error:
        print(f"digest_intake: {shown(error, 2000)}", file=sys.stderr)
        return FAILED
    except (OSError, ValueError) as error:
        print(f"digest_intake: {type(error).__name__}: {shown(error, 2000)}", file=sys.stderr)
        return FAILED
    return finish(result, args.report, "digest_intake", args.curated)


def _same_intake(stored: Source, source: Source) -> bool:
    return (stored.origin, stored.origin_kind, stored.pinned_ref, stored.licence) == (
        source.origin, source.origin_kind, source.pinned_ref, source.licence,
    )


if __name__ == "__main__":
    sys.exit(main())
