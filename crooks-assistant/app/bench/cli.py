"""`python -m app.bench`: the bench from a terminal on worker-01 (docs/BENCH.md has the commands).

    personas    who asks, from app/bench/personas/
    generate    write a question set (the model is asked once per persona)
    run         ask CLIVE every question in a set, against the fake shop; --judge to judge at the end
    judge       score a run's results
    report      a run's report, written beside it and printed

Every command that asks a model asks George's Max plan through the claude CLI (its own login on this
host, or --token-file, a file holding the plan's token as the build loop's workers are given theirs),
and refuses to start with an Anthropic API key in the environment. --dry-run asks no model at all:
the questions are the persona files' own examples, CLIVE's answers are the harness's fixed sentence,
and nothing is scored. It proves the pipeline and the seal, and costs nothing.

Nothing is imported from CLIVE until the command knows what it needs: a run must set the process's
settings to the fake shop's before CLIVE's first module reads them.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
import tempfile
from pathlib import Path


def _bench(args: argparse.Namespace):
    from app.bench.store import Bench, root_for
    from config.settings import get_settings

    if args.data_dir:
        return Bench(Path(args.data_dir).expanduser().resolve() / "bench")
    return Bench(root_for(get_settings()))


def _model(args: argparse.Namespace, default_model: str):
    from app.bench.models import MaxPlanModel, dry_run

    if args.dry_run:
        return dry_run()
    return MaxPlanModel(model=args.claude_model or default_model, cli_path=args.cli_path or "")


def _seal(args: argparse.Namespace, *, latch: bool, scratch: Path | None = None):
    from app.bench.isolation import Seal

    token = Path(args.token_file).expanduser() if getattr(args, "token_file", "") else None
    if token is not None and not token.is_file():
        raise SystemExit(f"--token-file {token} is not a file")
    return Seal(token_file=token, latch=latch, scratch=scratch)


def _people(names: str = ""):
    from app.bench import persona

    return persona.load(only=[n.strip() for n in names.split(",") if n.strip()])


def _default_model() -> str:
    from config.settings import get_settings

    return get_settings().claude_model


# ------------------------------------------------------------------ the commands


def cmd_personas(args: argparse.Namespace) -> int:
    for p in _people():
        mix = ", ".join(f"{k} {v}" for k, v in p.mix.items())
        print(f"{p.id:24} {p.access:6} {p.name}  ·  {mix}")
        print(f"{'':24} {Path(p.path).name}  ·  {p.role}")
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    from app.bench.generate import generate

    bench, people = _bench(args), _people(args.personas)
    model = _model(args, _default_model())
    with _seal(args, latch=False):
        made = asyncio.run(generate(people, model, bench=bench, per_persona=args.per_persona,
                                    concurrency=args.concurrency))
    print(f"question set {made['set_id']}: {len(made['questions'])} questions from {len(people)} personas "
          f"({made['model']}, {made['generator']})")
    for note in made["notes"]:
        if note.get("error"):
            print(f"  {note['persona']}: {note['error']}")
    if made["stopped"]:
        print(f"stopped early: {made['stopped']}")
    print(f"saved: {bench.set_path(made['set_id'])}")
    return 0 if made["questions"] and not made["stopped"] else 1


def cmd_run(args: argparse.Namespace) -> int:
    from app.bench.runner import Caps, Run, world_environment

    bench = _bench(args)
    question_set = bench.load_set(args.set)
    by_id = {p.id: p for p in _people()}
    claude_model = args.claude_model or _default_model()
    caps = Caps(max_questions=args.max_questions, concurrency=args.concurrency,
                budget_s=args.budget_minutes * 60.0, question_timeout_s=args.question_timeout)
    only = [n.strip() for n in args.personas.split(",") if n.strip()]
    scratch = Path(tempfile.mkdtemp(prefix="clive-bench-world-"))
    try:
        world_environment(scratch, claude_model=claude_model, cli_path=args.cli_path or "")
        with _seal(args, latch=True, scratch=scratch) as seal:
            run = Run(question_set, bench=bench, seal=seal, caps=caps, mode="scripted" if args.dry_run else "max",
                      people=by_id)
            run_id = asyncio.run(run.go(only))
            if args.judge:
                _judge(args, bench, run_id, by_id, claude_model)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return _print_report(bench, run_id)


def _judge(args: argparse.Namespace, bench, run_id: str, people: dict, claude_model: str) -> dict:
    from app.bench.judge import judge_run

    model = _model(args, claude_model)
    outcome = asyncio.run(judge_run(bench, run_id, model, people=people, concurrency=args.concurrency,
                                    budget_s=getattr(args, "judge_budget_minutes", 60) * 60.0,
                                    redo=getattr(args, "redo", False)))
    print(f"judged {outcome['judged']} of {outcome['asked']}" + (f", {outcome['errors']} judge errors" if outcome["errors"] else "")
          + (f", {outcome['not_judged']} not judged (dry run)" if outcome["not_judged"] else "")
          + (f"; stopped: {outcome['stopped']}" if outcome["stopped"] else ""))
    return outcome


def cmd_judge(args: argparse.Namespace) -> int:
    bench = _bench(args)
    run_id = bench.latest_run() if args.run == "latest" else args.run
    with _seal(args, latch=False):
        outcome = _judge(args, bench, run_id, {p.id: p for p in _people()}, _default_model())
    _print_report(bench, run_id)
    return 0 if not outcome["stopped"] else 1


def cmd_report(args: argparse.Namespace) -> int:
    bench = _bench(args)
    return _print_report(bench, bench.latest_run() if args.run == "latest" else args.run)


def _print_report(bench, run_id: str) -> int:
    from app.bench import report

    made = report.write(bench, run_id)
    print(report.markdown(made))
    print(f"files: {bench.run_dir(run_id)}")
    stopped = (made["run"] or {}).get("status") == "stopped"
    unsafe = any(made["safety"][k] for k in ("executions", "shop_changes", "committed", "breaches"))
    return 1 if stopped or unsafe else 0


# ------------------------------------------------------------------ the arguments


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="python -m app.bench", description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = top.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, *, model: bool = True) -> None:
        p.add_argument("--data-dir", default="", help="the data directory (bench/ goes under it); default: beside CLIVE's objectives")
        if model:
            p.add_argument("--dry-run", action="store_true", help="ask no model: the pipeline and the seal, at no cost")
            p.add_argument("--claude-model", default="", help="the model alias for the claude CLI (default: CROOKS_CLAUDE_MODEL, else sonnet)")
            p.add_argument("--cli-path", default="", help="the claude CLI, when it is not on PATH")
            p.add_argument("--token-file", default="", help="a file holding the Max plan's token (claude setup-token); default: the CLI's own login")
            p.add_argument("--concurrency", type=int, default=2, help="model calls in flight at once (default 2)")

    p = sub.add_parser("personas", help="list the personas")
    p.set_defaults(func=cmd_personas)

    p = sub.add_parser("generate", help="write a question set")
    common(p)
    p.add_argument("--per-persona", type=int, default=8, help="questions per persona (default 8, at most 30)")
    p.add_argument("--personas", default="", help="only these persona ids, comma-separated")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("run", help="ask CLIVE every question in a set")
    common(p)
    p.add_argument("--set", default="latest", help="the question set id (default: the latest)")
    p.add_argument("--personas", default="", help="only these persona ids, comma-separated")
    p.add_argument("--max-questions", type=int, default=60, help="at most this many questions (default 60)")
    p.add_argument("--budget-minutes", type=float, default=90, help="no question starts after this (default 90)")
    p.add_argument("--question-timeout", type=float, default=300, help="seconds for one question, follow-ups included (default 300)")
    p.add_argument("--judge", action="store_true", help="judge the run when it finishes")
    p.add_argument("--judge-budget-minutes", type=float, default=60)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("judge", help="score a run's results")
    common(p)
    p.add_argument("--run", default="latest", help="the run id (default: the latest)")
    p.add_argument("--judge-budget-minutes", type=float, default=60)
    p.add_argument("--redo", action="store_true", help="judge again results already judged at this version")
    p.set_defaults(func=cmd_judge)

    p = sub.add_parser("report", help="a run's report")
    common(p, model=False)
    p.add_argument("--run", default="latest", help="the run id (default: the latest)")
    p.set_defaults(func=cmd_report)
    return top


def _refused_for_billing(exc: BaseException) -> bool:
    """Whether this is the pay-as-you-go guard's refusal. Only looked for once a command has run, so
    nothing of CLIVE is imported to ask (a run sets its settings before CLIVE's first import)."""
    guard = sys.modules.get("app.providers.max_agent_sdk")
    return guard is not None and isinstance(exc, guard.BillingGuardError)


def main(argv: list[str] | None = None) -> int:
    """Every refusal is one plain line on stderr and a non-zero exit, never a traceback."""
    args = parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (FileNotFoundError, ValueError) as exc:
        print(f"bench: {exc}", file=sys.stderr)
        return 2
    except PermissionError as exc:
        where = exc.filename or "a file it needs"
        print(f"bench: not allowed to use {where} as this user: run it as the user that owns it, or give "
              f"--data-dir a folder this user can write", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        if not _refused_for_billing(exc):
            raise
        print(f"bench: refused: {' '.join(str(exc).split())}", file=sys.stderr)
        return 2
