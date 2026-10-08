#!/usr/bin/env python3
"""Read George's research now, from the server: the same way in as the Builds screen.

    python scripts/research.py                 take everything in the research folder and read it
    python scripts/research.py FILE [FILE...]  take these files and read them
    python scripts/research.py --list          say what each document became, and read nothing
    python scripts/research.py --try FILE      read one file into a throwaway store and print what CLIVE
                                               made of it: the live Max-plan check, nothing kept, nothing
                                               on his screen

Why this exists: the server folder (<research dir>/inbox/, docs/RESEARCH.md) is otherwise swept
when George opens the Builds screen's Research section. This reads it at once, with the same flow
(app/research/flow.py): quarantine, the digester's scan, then Claude on the Max plan weighs each
recommendation against MAP.md, DECISIONS, what is live and what is parked. The proposals then wait
on the Builds screen for his answer; nothing here answers, files or builds anything.

It refuses to run with an Anthropic API key in its environment (the Max plan only, MAP.md rule 5).
Exit status: 0 when every document was read or stopped by the safety scan with its reason, 1 when one
failed, 2 for bad arguments.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from app.research import flow  # noqa: E402
from app.research.store import store  # noqa: E402


def _say(record: dict) -> str:
    head = f"{record.get('name')}: {record.get('state')}"
    if record.get("why"):
        head += f" ({record['why']})"
    lines = [head]
    for p in record.get("proposals") or []:
        tail = f" [repeats {p['duplicate_of']}]" if p.get("duplicate_of") else ""
        lines.append(f"  - {p.get('verdict')}: {p.get('title')} — {p.get('reason')} ({', '.join(p.get('cites') or [])}){tail}")
    for d in record.get("dropped") or []:
        lines.append(f"  · left out: {d.get('title')} — {d.get('why')}")
    return "\n".join(lines)


async def _main(args: argparse.Namespace) -> int:
    from app.providers.max_agent_sdk import BillingGuardError, assert_no_payg_credentials

    if args.try_file:
        return await _try(Path(args.try_file))
    research = store()
    if args.list:
        for record in research.documents():
            print(_say(record))
        return 0
    try:
        assert_no_payg_credentials()
    except BillingGuardError as exc:
        print(f"research: {exc}", file=sys.stderr)
        return 2
    for name in args.files:
        path = Path(name)
        try:
            flow.receive(research, path.name, path.read_bytes(), via="script")
        except (OSError, ValueError) as exc:
            print(f"research: {path.name} was not taken in: {exc}", file=sys.stderr)
            return 2
    if not args.files:
        flow.sweep(research)
    ended = await flow.run_pending(research)
    for record in ended:
        print(_say(record))
    if not ended:
        print(f"research: nothing to read (put files in {research.inbox})")
    return 1 if any(r.get("state") == "failed" for r in ended) else 0


async def _try(path: Path) -> int:
    """One file, the whole way, into a store that is deleted afterwards: proves the Max-plan call on this
    server without putting anything on the Builds screen."""
    import tempfile

    from app.providers.max_agent_sdk import BillingGuardError, assert_no_payg_credentials
    from app.research.store import ResearchStore

    try:
        assert_no_payg_credentials()
    except BillingGuardError as exc:
        print(f"research: {exc}", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory(prefix="research-try-", ignore_cleanup_errors=True) as folder:
        throwaway = ResearchStore(folder)
        try:
            flow.receive(throwaway, path.name, path.read_bytes(), via="script")
        except (OSError, ValueError) as exc:
            print(f"research: {path.name} was not taken in: {exc}", file=sys.stderr)
            return 2
        ended = await flow.run_pending(throwaway)
        for record in ended:
            print(_say(record))
        _make_removable(Path(folder))
    return 1 if any(r.get("state") == "failed" for r in ended) else 0


def _make_removable(folder: Path) -> None:
    """The quarantine is read-only by design; the throwaway store is opened up so it can be deleted."""
    import os

    for root, dirs, files in os.walk(folder):
        for name in dirs + files:
            try:
                os.chmod(os.path.join(root, name), 0o700, follow_symlinks=False)
            except (OSError, NotImplementedError):
                pass
    os.chmod(folder, 0o700)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read George's research now, as the Builds screen would.")
    parser.add_argument("files", nargs="*", help="research files to take in; none takes the research folder's")
    parser.add_argument("--list", action="store_true", help="say what each document became, and read nothing")
    parser.add_argument("--try", dest="try_file", metavar="FILE",
                        help="read one file into a throwaway store and print what CLIVE made of it; nothing is kept")
    return asyncio.run(_main(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
