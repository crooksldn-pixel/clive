#!/usr/bin/env python3
"""The owner's two measures of the build system, from records that already exist.

Hours from asking to seeing the change on the phone, and minutes of the owner's attention
per change (NEXT_PHASE_2026-09-25.md section 3.7), per objective and per day. The logic
lives in ``app.engineering_measures``; this reads the inputs and prints the report.

    python scripts/engineering_measures.py --status status.json
    python scripts/engineering_measures.py --status a/status.json --status b/status.json \\
        --deploy-log deploys.jsonl --attention-log attention.jsonl \\
        --json measures.json --markdown measures.md

The loop's own records are the second source, instead of or as well as ``--status``: the
kernel's store (its ``engineering/`` directory) and the dispatcher's runtime, whose
``landings/`` it reads. Deploys and owner attention are recorded in neither, so that report
leaves them empty.

    python scripts/engineering_measures.py --store engineering \\
        --runtime-root /opt/crooks-workers/runtime --json loop.json --markdown loop.md

The trunk history is read with ``git log`` on the first-parent history of ``--trunk-ref``
(default ``clive/trunk``) in ``--repo``, plus the parents of every commit reachable from it.
When that ref cannot be read, or with ``--no-trunk``, the trunk and production columns
stay empty and the reason is printed; they are never estimated.

Read-only: it reads files and runs ``git log``. It writes only the output files named; it
never writes to, creates anything in or takes the lock of the store or the runtime.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# The script runs standalone (python scripts/engineering_measures.py); it must find the app package.
if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engineering_measures import (  # noqa: E402
    GRAPH_LOG_FORMAT,
    TRUNK_LOG_FORMAT,
    MeasuresError,
    measure,
    measure_loop,
    parse_graph_log,
    parse_trunk_log,
    read_json_lines,
    read_loop_records,
    render_loop_markdown,
    render_markdown,
)

ASSISTANT = Path(__file__).resolve().parents[1]
DEFAULT_TRUNK_REF = "clive/trunk"
DEFAULT_RUNTIME_ROOT = Path("/opt/crooks-workers/runtime")


class TrunkUnavailable(RuntimeError):
    """The trunk history could not be read; its columns stay empty."""


def _git_log(repo: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), "log", *args], capture_output=True, text=True
        )
    except OSError as exc:
        raise TrunkUnavailable(f"could not run git: {exc}") from exc
    if completed.returncode != 0:
        raise TrunkUnavailable(f"git log {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def read_trunk(repo: Path, ref: str) -> tuple[list, dict]:
    """The first-parent history of ``ref``, newest first, and every reachable commit's parents."""
    first_parent = _git_log(repo, "--first-parent", f"--format={TRUNK_LOG_FORMAT}", ref, "--")
    graph = _git_log(repo, f"--format={GRAPH_LOG_FORMAT}", ref, "--")
    return parse_trunk_log(first_parent), parse_graph_log(graph)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", type=Path, action="append",
                        help="a loop's published status.json; repeat for several loops")
    parser.add_argument("--store", type=Path, help="the kernel's engineering store (its engineering/ directory)")
    parser.add_argument("--runtime-root", type=Path, default=DEFAULT_RUNTIME_ROOT,
                        help=f"the dispatcher's runtime, whose landings/ is read (default {DEFAULT_RUNTIME_ROOT})")
    parser.add_argument("--repo", type=Path, default=ASSISTANT, help="the repository holding the trunk")
    parser.add_argument("--trunk-ref", default=DEFAULT_TRUNK_REF, help="the trunk ref (default clive/trunk)")
    parser.add_argument("--no-trunk", action="store_true", help="do not read the trunk history")
    parser.add_argument("--deploy-log", type=Path, help="JSON Lines of {sha, deployed_at}")
    parser.add_argument("--attention-log", type=Path, help="JSON Lines of {at, minutes, about}")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown",
                        help="what to print (default markdown)")
    parser.add_argument("--json", type=Path, dest="json_out", help="also write the JSON report here")
    parser.add_argument("--markdown", type=Path, dest="markdown_out", help="also write the markdown here")
    args = parser.parse_args(argv)
    if not args.status and args.store is None:
        parser.error("one of --status or --store is required")
    if not args.status and (args.deploy_log or args.attention_log):
        parser.error("--deploy-log and --attention-log go with --status; the loop's records hold neither")
    if args.store is not None:
        # The reader never writes into the trees it reads: refuse before any directory is made.
        for path in (args.json_out, args.markdown_out):
            if path is None:
                continue
            for name, root in (("store", args.store), ("runtime", args.runtime_root)):
                if path.resolve().is_relative_to(root.resolve()):
                    print(f"engineering_measures: refusing to write {path} inside the {name} {root}",
                          file=sys.stderr)
                    return 2

    report = loop_report = None
    try:
        projections = [json.loads(path.read_text(encoding="utf-8")) for path in args.status or ()]
        deploy_log = (
            read_json_lines(args.deploy_log.read_text(encoding="utf-8"), what="deploy log")
            if args.deploy_log
            else None
        )
        attention_log = (
            read_json_lines(args.attention_log.read_text(encoding="utf-8"), what="attention log")
            if args.attention_log
            else None
        )
        loop_records = read_loop_records(args.store, args.runtime_root) if args.store is not None else None
        trunk, graph, trunk_note = None, None, "not read (--no-trunk)"
        if not args.no_trunk:
            try:
                trunk, graph = read_trunk(args.repo, args.trunk_ref)
                trunk_note = f"{args.trunk_ref} ({len(trunk)} first-parent commits)"
            except TrunkUnavailable as exc:
                trunk_note = f"unavailable: {exc}"
                print(f"engineering_measures: trunk history {trunk_note}", file=sys.stderr)
        if args.status:
            report = measure(
                status_projections=projections,
                trunk=trunk,
                graph=graph,
                deploy_log=deploy_log,
                attention_log=attention_log,
            )
        if loop_records is not None:
            loop_report = measure_loop(loop_records, trunk=trunk)
    except (OSError, json.JSONDecodeError, MeasuresError) as exc:
        print(f"engineering_measures: {exc}", file=sys.stderr)
        return 2
    if loop_report is not None:
        loop_report["inputs"]["trunk_source"] = trunk_note
    if report is None:
        report, rendered_markdown = loop_report, render_loop_markdown(loop_report)
    else:
        report["inputs"]["trunk_source"] = trunk_note
        rendered_markdown = render_markdown(report)
        if loop_report is not None:
            report["loop_records"] = loop_report
            rendered_markdown += "\n" + render_loop_markdown(loop_report)

    rendered_json = json.dumps(report, indent=2, sort_keys=True)
    print(rendered_json if args.format == "json" else rendered_markdown.rstrip("\n"))
    for path, text in ((args.json_out, rendered_json + "\n"), (args.markdown_out, rendered_markdown)):
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
