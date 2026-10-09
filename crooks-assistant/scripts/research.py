#!/usr/bin/env python3
"""Read George's research now, from the server: the same way in as the Builds screen.

    python scripts/research.py                 take everything in the research folder and read it
    python scripts/research.py FILE [FILE...]  take these files and read them
    python scripts/research.py --list          say what each document became, and read nothing
    python scripts/research.py --try FILE      read one file into a throwaway store and print what CLIVE
                                               made of it: the live Max-plan check, nothing kept, nothing
                                               on his screen

Learning from research as ideas (DEC-078, app/research/synthesis, docs/RESEARCH.md):

    python scripts/research.py --synthesise    a new generation of ideas from every document read: not
                                               live; prints progress, then the eight-item report
    python scripts/research.py --synthesise --resume   carry on the run that stopped
    python scripts/research.py --export-synthesis PATH [--generation GEN]
                                               one generation (the newest, unless named) as a .tgz at
                                               PATH, never inside the repository
    python scripts/research.py --apply GEN     make GEN live, taking in what was read since its run; it
                                               refuses when an answer of his wouldn't stay with its idea
    python scripts/research.py --apply GEN --accept-unmatched   make it live anyway
    python scripts/research.py --ideas         the live ideas, with their four answers
    --call-timeout SECONDS                     one time limit for every model call of a run

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
    if args.ideas:
        return _ideas(research)
    if args.export_synthesis:
        return _export(research, args.export_synthesis, args.generation)
    try:
        assert_no_payg_credentials()
    except BillingGuardError as exc:
        print(f"research: {exc}", file=sys.stderr)
        return 2
    if args.synthesise:
        return await _synthesise(research, resume=args.resume, timeout_s=args.call_timeout)
    if args.apply:
        return await _apply(research, args.apply, accept_unmatched=getattr(args, "accept_unmatched", False))
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


def _print(text: str) -> None:
    print(text, flush=True)


async def _synthesise(research, *, resume: bool, timeout_s: float | None) -> int:
    from app.research import model as model_module
    from app.research.rules import read_map
    from app.research.synthesis import run as run_module
    from app.research.synthesis.store import synthesis_store

    try:
        gen = await run_module.synthesise(research, model=model_module.current(), the_map=read_map(), resume=resume,
                                          timeout_s=timeout_s, say=_print)
    except run_module.Stopped as exc:
        print(f"research: {exc}", file=sys.stderr)
        return 1
    run = synthesis_store(research).run(gen) or {}
    _print(f"\nGeneration {gen} is ready, not live. {run.get('calls', 0)} model calls; "
           f"{len(run.get('errors') or [])} problems said in its run.json.")
    for line in run_module.report_lines(run.get("report") or {}):
        _print(line)
    return 0


async def _apply(research, gen: str, *, accept_unmatched: bool = False) -> int:
    from app.research import model as model_module
    from app.research.rules import read_map
    from app.research.synthesis.apply import apply
    from app.research.synthesis.ask import SynthesisError
    from app.research.synthesis.run import Stopped

    try:
        done = await apply(research, gen, model=model_module.current(), the_map=read_map(), say=_print,
                           accept_unmatched=accept_unmatched)
    except (SynthesisError, Stopped, BlockingIOError) as exc:
        print(f"research: {gen} was not made live: {exc or 'another reader holds the research store'}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - a model failure while taking in a new document: nothing went live
        print(f"research: {gen} was not made live: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if done.get("already"):
        _print(f"{gen} is already live.")
        return 0
    _print(f"{gen} is live{', replacing ' + done['previous'] if done.get('previous') else ''}. "
           f"Took in {len(done['taken_in'])} document(s) read since its run; {done['kept_ids']} idea(s) kept an earlier id, "
           f"with {done['history_carried']} line(s) of their history.")
    for lost in done.get("unmatched") or []:
        _print(f"  Accepted: {lost['said']}")
    for gone in done.get("missing") or []:
        _print(f"  Not in it: {gone['name']}: {gone['why']}")
    return 0


def _export(research, path: str, gen: str) -> int:
    from app.research.synthesis.apply import export
    from app.research.synthesis.ask import SynthesisError
    from app.research.synthesis.store import ReadProblem, synthesis_store

    synth = synthesis_store(research)
    gen = gen or (synth.generations() or [""])[-1]
    try:
        written = export(research, gen, path)
    except (SynthesisError, OSError) as exc:
        print(f"research: nothing exported: {exc}", file=sys.stderr)
        return 1
    _print(f"{gen} exported to {written}")
    try:
        missing = list(((synth.run(gen) or {}).get("failed") or {}).values())
    except ReadProblem as exc:
        _print(f"Which documents are missing from it couldn't be read: {exc}")
        return 0
    _print(f"Not in it: {len(missing)} document(s) Claude couldn't read." if missing else "Every document read is in it.")
    for gone in missing:
        _print(f"  - {gone['name']}: {gone['why']}")
    return 0


def _ideas(research) -> int:
    from app.builds import decisions
    from app.research.synthesis import answers as idea_answers
    from app.research.synthesis.ideas import documents_backing
    from app.research.synthesis.store import synthesis_store
    from app.research.synthesis.words import words

    synth = synthesis_store(research)
    gen = synth.live()
    if not gen:
        _print("No synthesis is live yet.")
        return 0
    try:
        answered = idea_answers.keys(decisions.ledger().effective())
    except decisions.DecisionError:
        answered = {}
    yours = {"go": "you approved the work", "later": "you said not now", "no": "you said not for CLIVE"}
    for idea in synth.ideas(gen).values():
        if idea.get("status") != "active":
            continue
        a = idea.get("answers") or {}
        execution = yours.get(answered.get(idea["id"]), "not approved")
        _print(f"{idea['id']} {idea['name']} (backed by {len(documents_backing(idea))}): "
               f"{words('judgment', a.get('judgment', ''))} / {words('relationship', a.get('relationship', ''))} / "
               f"{words('timing', a.get('timing', ''))} / {execution}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read George's research now, as the Builds screen would.")
    parser.add_argument("files", nargs="*", help="research files to take in; none takes the research folder's")
    parser.add_argument("--list", action="store_true", help="say what each document became, and read nothing")
    parser.add_argument("--try", dest="try_file", metavar="FILE",
                        help="read one file into a throwaway store and print what CLIVE made of it; nothing is kept")
    parser.add_argument("--synthesise", action="store_true", help="a new generation of ideas from every document read (not live)")
    parser.add_argument("--resume", action="store_true", help="with --synthesise: carry on the run that stopped")
    parser.add_argument("--export-synthesis", metavar="PATH", help="one generation as a .tgz, outside the repository")
    parser.add_argument("--generation", default="", help="with --export-synthesis: which generation (the newest by default)")
    parser.add_argument("--apply", metavar="GEN", help="make a generation live")
    parser.add_argument("--accept-unmatched", action="store_true",
                        help="with --apply: make it live even when an answer of his won't stay with its idea")
    parser.add_argument("--ideas", action="store_true", help="the live ideas with their four answers")
    parser.add_argument("--call-timeout", type=float, default=None, metavar="SECONDS",
                        help="one time limit for every model call of a synthesis run")
    args = parser.parse_args(argv)
    if args.resume and not args.synthesise:
        parser.error("--resume goes with --synthesise")
    if args.accept_unmatched and not args.apply:
        parser.error("--accept-unmatched goes with --apply")
    return asyncio.run(_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
