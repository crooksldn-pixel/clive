#!/usr/bin/env python3
"""The owner's door for engineering objectives, and the dispatcher that carries them.

    engineering_dispatcher.py --store <engineering/> --repo <dispatcher clone> VERB ...

    objective      record one owner objective and its task revision 1 (the only intake)
    tick           one deterministic pass: every objective advances by what its records allow
    run            tick until every objective is COMPLETE, BLOCKED or at OWNER_GATE
    status         task / revision / attempt, worker process, progress, candidate, review, blocker, next action
    submit-review  (relay reviewer only) hand the dispatcher a typed clive.review_result.v1 a person carried back
    stops          why each stopped build stopped, in full: the reviewer's findings, the failing output, the
                   builder's report (private: printed here and served over the tailnet, never pushed)
    probe-launch   launch a builder exactly as an attempt would, read its init event, stop it before it does any
                   work, and say whether this CLI passes the launch check (run it before a re-pin, and after a
                   deliberate CLI update); with --skill-turn NAME, after a re-pin, let it answer one prompt that
                   loads that skill, to prove a builder can use the owner's skills under dontAsk
    probe-review   launch the Claude reviewer exactly as a review would, in a throwaway read-only room, and say
                   whether its launch passes (read-only tools, no server, no skill, the owner's plan, never an API
                   key); with --turn, let it answer one tiny prompt on its token to prove a review can finish
    skill-entry    the config/builder_skills.json entry for a skill folder: the sha256 of every file in it

Example:

    engineering_dispatcher.py --store /srv/clive-state/engineering --repo /opt/crooks-dispatcher \\
        objective --title "Support queue" \\
        --objective "Show unanswered Crooks order enquiries ..." \\
        --base-ref origin/claude/support-investigator-v1-2026-09-23 \\
        --allowed-path crooks-assistant/app/support --allowed-path crooks-assistant/tests/test_support_queue.py \\
        --acceptance "lists every thread with no reply from us, newest first" \\
        --check 'tests=.venv/bin/python -m pytest -q tests/test_support_queue.py' --check-cwd tests=crooks-assistant

    engineering_dispatcher.py --store ... --repo ... run

A candidate is reviewed, accepted and integrated only once GitHub's ``acceptance`` run is green
on its exact SHA (app/orchestrator/github_acceptance.py), asked with the credential git already
holds for the publish remote. The loop then lands it on clive/trunk itself, under the same gates
asked again (OWNER_DECISIONS_2026-09-30); ``tick --no-land`` and ``run --no-land`` switch that off. Nothing here deploys, restarts a service, changes runtime, grants a
permission or lifts an owner gate. Every stage is a kernel record (app/orchestrator/lifecycle.py,
unchanged); the dispatcher's own files under --runtime-root are execution notes.
Exit status: 0 done, 2 refused, 4 another dispatcher is running.
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import socket
import sys
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.orchestrator.checks import NamespaceSandbox  # noqa: E402
from app.orchestrator.contracts import TaskStatus  # noqa: E402
from app.orchestrator.dispatcher import Dispatcher, DispatcherBusy, DispatcherConfig  # noqa: E402
from app.orchestrator.github_acceptance import GitHubAcceptance, git_remote_token  # noqa: E402
from app.orchestrator.lifecycle import (  # noqa: E402
    GitFacts,
    JournalError,
    Kernel,
    LifecycleError,
    LifecycleStore,
    PrincipalRegistry,
)
from app.orchestrator.objectives import (  # noqa: E402
    DEFAULT_PROHIBITED_ACTIONS,
    Check,
    Objective,
    ObjectiveStore,
    accepted_candidates,
    intake,
    integration_scope,
    owner_entry_from_host,
    slug,
)
from app.orchestrator.reviewers import (  # noqa: E402
    DEFAULT_REVIEWER,
    GPT_DEFAULT_EFFORT,
    GPT_DEFAULT_MODEL,
    REVIEWERS,
    RelayReviewer,
    ReviewContext,
    ReviewResult,
    probe_review,
    reviewers_for,
)
from app.orchestrator.store import RecordConflictError, StateConflictError  # noqa: E402
from app.orchestrator.workers import ClaudeCodeWorker  # noqa: E402
from app.orchestrator.workers import skills as builder_skills  # noqa: E402
from app.orchestrator.workers.base import LaunchSpec  # noqa: E402

DEFAULT_REGISTRY = ROOT / "config" / "review_principals.json"
TERMINAL = {"COMPLETE", "BLOCKED", "OWNER_GATE", "UNKNOWN", "NO_TASK"}
# Canonical product memory lives on the trunk since the 2026-09-25 consolidation (owner's loop update).
PRODUCT_MEMORY_REF = "origin/clive/trunk"


# The 2026-09-26 re-pin review, F-02: the loop is GitHub-gated, and GitHub only sees what is pushed.
NO_PUBLISH_REMOTE = (
    "candidates are published nowhere without --publish-remote, so GitHub never runs acceptance on them "
    "and every one would wait and then block; a GitHub-gated loop needs an explicit publication remote "
    "(normally origin)"
)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--store", required=True, help="the kernel's store root (engineering/)")
    p.add_argument("--repo", required=True, help="the dispatcher's own clone; never a production checkout")
    p.add_argument("--registry", default=str(DEFAULT_REGISTRY))
    p.add_argument("--runtime-root", default="/opt/crooks-workers/runtime")
    p.add_argument("--workspace-root", default="/opt/crooks-workers")
    p.add_argument("--operator", default=f"clive-dispatcher@{socket.gethostname()}")
    p.add_argument("--no-journal", action="store_true")
    p.add_argument("--publish-remote", default=None,
                   help="push candidates to this remote's target branch, so GitHub runs acceptance on them; "
                        "tick and run refuse to start without it")
    _add_reviewer_args(p, choices=(*REVIEWERS, "relay"))
    p.add_argument("--worker-cli", default="claude")
    p.add_argument("--worker-model", default=None)
    p.add_argument("--worker-effort", default=None)
    p.add_argument("--worker-max-turns", type=int, default=200)
    p.add_argument("--worker-token-file", default=None, help="host-side file holding CLAUDE_CODE_OAUTH_TOKEN")
    p.add_argument("--worker-bash-prefix", action="append", default=[],
                   help="allow Bash commands with this prefix (off by default; a prefix is not a sandbox)")
    p.add_argument("--sandbox-browsers", default=None,
                   help="where Playwright's browsers are installed on this host (PLAYWRIGHT_BROWSERS_PATH): checks may "
                        "then drive Chromium, read-only, inside the same sandbox")
    p.add_argument("--sandbox-node-path", default=None,
                   help="the node_modules folder holding playwright-core for browser checks (NODE_PATH), read-only")
    p.add_argument("--check-ro-path", action="append", default=[],
                   help="a host directory the check sandbox binds read-only (e.g. the interpreter's virtualenv); "
                        "nothing else of the host is visible to a check")
    p.add_argument("--lease-s", type=int, default=1800)
    p.add_argument("--stall-s", type=int, default=1200)
    p.add_argument("--init-timeout-s", type=int, default=180)
    p.add_argument("--max-concurrent", type=int, default=1)
    _add_skill_args(p)
    sub = p.add_subparsers(dest="verb", required=True)

    o = sub.add_parser("objective", help="record one owner objective (and its task r1)")
    o.add_argument("--title", required=True)
    o.add_argument("--objective", required=True, help="the requested outcome, in the owner's words")
    o.add_argument("--id", default=None, help="objective id (default: from the title)")
    o.add_argument("--base-ref", required=True, help="branch, tag or SHA the work starts from")
    o.add_argument("--target-branch", default=None, help="default clive/objective/<id>")
    o.add_argument("--allowed-path", action="append", required=True)
    o.add_argument("--acceptance", action="append", default=[])
    o.add_argument("--check", action="append", default=[], help="NAME=COMMAND (no shell)")
    o.add_argument("--check-cwd", action="append", default=[], help="NAME=DIR inside the workspace")
    o.add_argument("--prohibited", action="append", default=[], help="an extra prohibited action")
    o.add_argument("--max-repair-rounds", type=int, default=2)
    o.add_argument("--repository", default="crooksldn-pixel/clive")
    o.add_argument("--product-memory-ref", default=PRODUCT_MEMORY_REF)

    g = sub.add_parser("integrate", help="an integration objective: CLIVE merges the accepted candidates of "
                                         "several objectives, runs whole-product checks, and the independent "
                                         "reviewer judges the result")
    g.add_argument("--title", required=True)
    g.add_argument("--id", default=None)
    g.add_argument("--from", dest="sources", action="append", required=True,
                   help="an objective id whose verified, accepted candidate is integrated (repeat)")
    g.add_argument("--base-ref", required=True, help="the line the candidates are integrated onto")
    g.add_argument("--target-branch", default=None)
    g.add_argument("--acceptance", action="append", default=[])
    g.add_argument("--check", action="append", default=[], help="NAME=COMMAND (no shell): whole-product checks")
    g.add_argument("--check-cwd", action="append", default=[])
    g.add_argument("--repository", default="crooksldn-pixel/clive")
    g.add_argument("--product-memory-ref", default=PRODUCT_MEMORY_REF)

    t = sub.add_parser("tick", help="one deterministic pass")
    r = sub.add_parser("run", help="tick until every objective is terminal")
    r.add_argument("--interval", type=float, default=15.0)
    r.add_argument("--max-ticks", type=int, default=0, help="0: no limit")
    for verb in (t, r):
        verb.add_argument("--no-land", action="store_true",
                          help="never land on clive/trunk: the loop as it was before the owner's decision of "
                               "2026-09-30 that it lands its own work (landing is on by default)")
    s = sub.add_parser("status", help="what the records and the host say")
    s.add_argument("--json", action="store_true")
    v = sub.add_parser("submit-review", help="relay only: a typed review result carried back by a person")
    v.add_argument("--file", required=True)
    st = sub.add_parser("stops", help="why each stopped build stopped, in full (private: never pushed)")
    st.add_argument("--json", action="store_true")
    pl = sub.add_parser("probe-launch", help="launch a builder as an attempt would, read its init event, stop it, "
                                             "and say whether the launch check passes")
    pl.add_argument("--base-ref", default=PRODUCT_MEMORY_REF, help="the commit the repository's skills are read at")
    pl.add_argument("--without-checks", action="store_true",
                    help="probe the launch of a build with no declared checks (default: with CLIVE's check server, "
                         "as every build CLIVE files has)")
    pl.add_argument("--timeout-s", type=float, default=90.0)
    pl.add_argument("--skill-turn", default=None, metavar="NAME",
                    help="after a re-pin: let the probed builder answer one real prompt (on the worker's token) "
                         "that loads this owner's skill with the Skill tool, and say whether it could")
    pr = sub.add_parser("probe-review", help="launch the Claude reviewer as a review would, read its init event, stop "
                                             "it, and say whether its launch passes")
    pr.add_argument("--turn", action="store_true",
                    help="after a re-pin: let it answer one tiny prompt on its token, to prove a review can finish")
    pr.add_argument("--timeout-s", type=float, default=90.0)
    se = sub.add_parser("skill-entry", help="print the config/builder_skills.json entry for a skill folder")
    se.add_argument("--name", required=True)
    se.add_argument("--folder", required=True, help="the skill's folder (an installed skill: <dir>/<name>/skill)")
    se.add_argument("--repo-path", default=None, help="for a skill vendored in the repository: its repository path")
    return p


def _add_reviewer_args(p: argparse.ArgumentParser, *, choices: tuple[str, ...]) -> None:
    """Which reviewer judges each candidate (the owner's ruling of 8 Oct 2026, DEC-071 ruling 10; DEC-076)."""
    p.add_argument("--reviewer", choices=list(choices), default=DEFAULT_REVIEWER,
                   help="claude (default): Claude on the owner's plan through the claude CLI, read-only, in a session and "
                        "review room of its own; gpt: the programmatic GPT reviewer (needs --gpt-api-key-file, else the "
                        "task blocks with the gap), kept so a re-pin can fall back"
                        + ("; relay: a person carries packet and typed result (courier)" if "relay" in choices else ""))
    p.add_argument("--reviewer-cli", default=None, help="the claude CLI the reviewer runs (default: --worker-cli)")
    p.add_argument("--reviewer-token-file", default=None,
                   help="host-side file (mode 600) holding the CLAUDE_CODE_OAUTH_TOKEN the reviewer runs on (default: "
                        "--worker-token-file); an API key is refused")
    p.add_argument("--reviewer-model", default=None, help="the reviewer's model (default: the CLI's own)")
    p.add_argument("--reviewer-effort", default=None)
    p.add_argument("--reviewer-max-turns", type=int, default=None)
    p.add_argument("--gpt-api-key-file", default=None,
                   help="host-side file (mode 600, outside git and every workspace) holding the OpenAI API key "
                        "for the programmatic GPT reviewer; read only by the reviewer process. With --reviewer claude it "
                        "only lets reviews already dispatched to GPT finish")
    p.add_argument("--gpt-model", default=GPT_DEFAULT_MODEL)
    p.add_argument("--gpt-effort", default=GPT_DEFAULT_EFFORT)


def loop_reviewers(args, runtime: Path) -> list:
    """The reviewer drivers this loop runs, from its flags (reviewers/choice.py)."""
    return reviewers_for(args.reviewer, runtime=runtime, repo=Path(args.repo), gpt_key_file=args.gpt_api_key_file,
                         gpt_model=args.gpt_model, gpt_effort=args.gpt_effort,
                         claude_cli=args.reviewer_cli or args.worker_cli,
                         claude_token_file=args.reviewer_token_file or args.worker_token_file,
                         claude_model=args.reviewer_model, claude_effort=args.reviewer_effort,
                         claude_max_turns=args.reviewer_max_turns)


def _add_skill_args(p: argparse.ArgumentParser) -> None:
    """The owner's curated skills for builders (app/orchestrator/workers/skills.py): on unless switched off."""
    p.add_argument("--no-builder-skills", action="store_true",
                   help="launch builders with no skills at all, exactly as before config/builder_skills.json")
    p.add_argument("--builder-skills-dir", default=None,
                   help="where the skill installer put the curated skills on this host (<dir>/<name>/skill); "
                        "a listed skill of source 'installed' is read from here, and withheld without it")


def _parts(args):
    store = LifecycleStore(Path(args.store))
    kernel = Kernel(store=store, registry=PrincipalRegistry.load(Path(args.registry)), git=GitFacts(Path(args.repo)),
                    operator=args.operator, journal=not args.no_journal)
    objectives = ObjectiveStore(store, journal=not args.no_journal)
    runtime = Path(args.runtime_root)
    reviewers = loop_reviewers(args, runtime)
    worker = ClaudeCodeWorker(cli=args.worker_cli, model=args.worker_model, effort=args.worker_effort,
                              max_turns=args.worker_max_turns, bash_prefixes=tuple(args.worker_bash_prefix),
                              oauth_token_file=Path(args.worker_token_file) if args.worker_token_file else None)
    config = DispatcherConfig(runtime_root=runtime, workspace_root=Path(args.workspace_root), repo=Path(args.repo),
                              publish_remote=args.publish_remote, lease_s=args.lease_s, stall_s=args.stall_s,
                              init_timeout_s=args.init_timeout_s, max_concurrent=args.max_concurrent,
                              land=not getattr(args, "no_land", False), builder_skills=not args.no_builder_skills,
                              installed_skills_dir=Path(args.builder_skills_dir) if args.builder_skills_dir else None)
    sandbox = NamespaceSandbox(ro_paths=tuple(args.check_ro_path), browsers=args.sandbox_browsers,
                               node_path=args.sandbox_node_path)
    # The GitHub acceptance gate asks with the credential git already holds for the remote candidates go to.
    acceptance = GitHubAcceptance(git_remote_token(Path(args.repo), args.publish_remote or "origin"))
    return kernel, objectives, Dispatcher(kernel, objectives, worker, reviewers, config, checks=sandbox,
                                          acceptance=acceptance)


def _objective(args, kernel: Kernel) -> Objective:
    base = kernel.git.rev_parse(args.base_ref)
    if base is None:
        raise LifecycleError(f"base ref {args.base_ref!r} does not resolve to a commit in {args.repo}")
    memory = kernel.git.rev_parse(args.product_memory_ref)
    if memory is None:
        raise LifecycleError(f"product-memory ref {args.product_memory_ref!r} does not resolve")
    objective_id = args.id or slug(args.title)
    cwds = dict(item.split("=", 1) for item in args.check_cwd)
    checks = []
    for item in args.check:
        if "=" not in item:
            raise SystemExit(f"--check {item!r}: expected NAME=COMMAND")
        name, command = item.split("=", 1)
        checks.append(Check(name=name, argv=tuple(shlex.split(command)), cwd=cwds.get(name, ".")))
    return Objective(
        objective_id=objective_id, title=args.title, requested_outcome=args.objective,
        acceptance_criteria=tuple(args.acceptance), checks=tuple(checks), repository=args.repository,
        base_ref=args.base_ref, base_sha=base, target_branch=args.target_branch or f"clive/objective/{objective_id}",
        product_memory_sha=memory, allowed_paths=tuple(args.allowed_path),
        prohibited_actions=(*DEFAULT_PROHIBITED_ACTIONS, *args.prohibited), max_repair_rounds=args.max_repair_rounds,
        owner=owner_entry_from_host(), created_at=datetime.now(UTC),
    )


def _integration(args, kernel: Kernel) -> Objective:
    sources = tuple(args.sources)
    shas = accepted_candidates(kernel, sources)
    base = kernel.git.rev_parse(args.base_ref)
    if base is None:
        raise LifecycleError(f"base ref {args.base_ref!r} does not resolve to a commit in {args.repo}")
    args.allowed_path = list(integration_scope(kernel, base, shas))
    args.objective = (f"Integrate the accepted candidates of {', '.join(sources)} "
                      f"({', '.join(shas)}) onto {args.base_ref} ({base}); the integrated SHA must pass the "
                      "whole-product checks and an independent review.")
    args.prohibited, args.max_repair_rounds = [], 0
    args.acceptance = [*args.acceptance, "every integrated candidate's change is present, unaltered, at the integrated SHA",
                       "the whole-product checks pass at the integrated SHA"]
    fields = _objective(args, kernel).model_dump()
    fields.update(builder="integrator", integrates=shas)
    return Objective.model_validate(fields)


def _print_status(items: list[dict]) -> None:
    for s in items:
        print(f"{s['objective_id']}  {s.get('stage')}  r{s.get('revision')} {s.get('attempt_id') or '-'}")
        print(f"    {s.get('stage_reason') or ''}")
        proc = s.get("process") or {}
        if proc:
            print(f"    process alive: {proc.get('alive')} {proc.get('pids') or ''}; last observed event "
                  f"{proc.get('last_observed_event_at')}; last heartbeat {s.get('last_heartbeat')}; "
                  f"last progress {s.get('last_progress')}")
        if s.get("candidate_sha"):
            print(f"    candidate {s['candidate_sha']}")
        gate = s.get("github_acceptance") or {}
        if gate:
            print(f"    GitHub acceptance on {gate.get('sha')}: {gate.get('state')} ({gate.get('detail')}); "
                  f"asked {gate.get('checked_at')}")
        review = s.get("review_mechanism") or {}
        if review:
            print(f"    review: {review.get('principal_id')} via {review.get('mechanism')}"
                  f"{' (COURIER)' if review.get('courier') else ''}")
        if s.get("blocker"):
            print(f"    blocker ({s.get('blocker_class')}): {s['blocker']}")
        print(f"    next: {s.get('next_action')}")


def _print_stops(reports: list[dict]) -> None:
    """Each stopped build, in full, for the operator on the loop host (private: this is never pushed)."""
    for r in reports:
        print(f"{r.get('objective_id')}  {r.get('stage')}  {r.get('cause')}  r{r.get('revision')} {r.get('attempt_id') or '-'}")
        print(f"    {r.get('blocker')}")
        for rnd in r.get("review_rounds") or []:
            print(f"    review r{rnd.get('revision')} on {rnd.get('candidate_sha')} by {rnd.get('reviewer')}:")
            for f in rnd.get("findings") or []:
                print(f"      [{f.get('finding_id')}] {f.get('finding')}")
                print(f"        evidence: {f.get('evidence_ref')}")
                print(f"        required repair: {f.get('required_repair')}")
        for c in r.get("failed_checks") or []:
            print(f"    failed {c.get('what')} {c.get('name')} (exit {c.get('exit_code')}) on {c.get('attempt_id')}:")
            print("      " + str(c.get("tail") or "").strip().replace("\n", "\n      ")[-1500:])
        red = r.get("github_failure") or {}
        if red:
            print(f"    red GitHub run on {red.get('sha')}: {red.get('summary')}")
        report = r.get("builder_report") or {}
        if report:
            print(f"    builder ({report.get('status')}): {report.get('summary')} {report.get('reason') or ''}")


SKILL_TURN_PROMPT = ("Load the skill {skill} with the Skill tool. Then stop: report status 'completed' with the "
                     "skill's own one-line description as the summary. Change no file and use no other tool.")


def skill_turn_problems(log_text: str, skill: str) -> tuple[list[str], dict]:
    """What one real turn's stream shows of the Skill tool (review of the loop branch, N8): a call naming the skill,
    its result not an error, no call denied under dontAsk, and the turn finished. Read from the stream itself."""
    calls: dict[str, dict] = {}
    errors: dict[str, bool] = {}
    denied, finished = 0, None
    for line in log_text.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        blocks = (event.get("message") or {}).get("content") if kind in ("assistant", "user") else None
        for block in blocks if isinstance(blocks, list) else ():
            if not isinstance(block, dict):
                continue
            if kind == "assistant" and block.get("type") == "tool_use" and block.get("name") == "Skill":
                calls[str(block.get("id"))] = block.get("input") if isinstance(block.get("input"), dict) else {}
            elif kind == "user" and block.get("type") == "tool_result":
                errors[str(block.get("tool_use_id"))] = bool(block.get("is_error"))
        if kind == "system" and event.get("subtype") == "permission_denied":
            denied += 1
        elif kind == "result":
            finished = event
    names = {skill, skill.split(":", 1)[-1]}
    named = [cid for cid, given in calls.items() if names & {str(v) for v in given.values()}]
    denied += len((finished or {}).get("permission_denials") or ())
    problems = []
    if not named:
        problems.append(f"the builder never called Skill({skill})")
    elif not any(errors.get(cid) is False for cid in named):
        problems.append(f"Skill({skill}) returned no result, or an error")
    if denied:
        problems.append(f"{denied} tool call(s) denied under dontAsk")
    if finished is None:
        problems.append("the turn did not finish before the timeout")
    elif finished.get("is_error"):
        problems.append(f"the turn ended in error ({finished.get('subtype')})")
    return problems, {"skill_calls": len(named), "denied": denied,
                      "finished": None if finished is None else finished.get("subtype"),
                      "report": None if finished is None else finished.get("structured_output")}


def probe_launch(args, kernel: Kernel, dispatcher: Dispatcher) -> int:
    """A builder launched exactly as an attempt would be, stopped at its init event: does this CLI pass the check?"""
    base = kernel.git.rev_parse(args.base_ref)
    if base is None:
        raise LifecycleError(f"base ref {args.base_ref!r} does not resolve to a commit in {args.repo}")
    root = Path(tempfile.mkdtemp(prefix="clive-probe-"))
    workspace, home = root / "workspace", root / "home"
    workspace.mkdir()
    home.mkdir()
    config = dispatcher.config
    try:
        skills = {"provided": (), "withheld": (), "folder": None, "settings": ""}
        if config.builder_skills:
            allow = builder_skills.load_allow_list(config.builder_skills_file or builder_skills.ALLOW_LIST)
            built = builder_skills.build_plugin(allow, home / builder_skills.PLUGIN_NAME, repo=config.repo,
                                                base_sha=base, installed_dir=config.installed_skills_dir)
            skills = {"provided": built.provided, "withheld": built.withheld, "folder": built.folder,
                      "settings": builder_skills.settings_json(allow) if built.folder else ""}
        check_config = None
        if not args.without_checks:
            check_config = root / "checks" / "config.json"
            check_config.parent.mkdir()
            check_config.write_text(json.dumps({
                "workspace": str(workspace), "scratch": str(root / "checks" / "runs"),
                "checks": [{"name": "probe", "argv": ["/bin/true"], "cwd": ".", "timeout_s": 30}],
                "sandbox": {"ro_paths": list(args.check_ro_path), "browsers": args.sandbox_browsers,
                            "node_path": args.sandbox_node_path}}))
            check_config.chmod(0o600)
        turn = args.skill_turn
        if turn is not None and turn not in skills["provided"]:
            print(json.dumps({"verdict": "REFUSED", "problems": [
                f"the skill {turn!r} is not one this builder would be given (given: "
                f"{', '.join(skills['provided']) or 'none'}), so there is no turn to prove"]}, indent=2))
            return 2
        prompt = (SKILL_TURN_PROMPT.format(skill=builder_skills.skill_id(turn)) if turn is not None
                  else "Reply with the single word: probe.")
        spec = LaunchSpec(task_id="probe", task_revision=1, attempt_id=f"probe-{uuid.uuid4().hex[:8]}", fencing_token=1,
                          session_id=str(uuid.uuid4()), workspace=workspace, home=home, log_path=root / "log.jsonl",
                          stderr_path=root / "stderr.txt", prompt=prompt,
                          check_config=check_config, skills_dir=skills["folder"], skills=tuple(skills["provided"]),
                          skills_settings=skills["settings"])
        started, problems, stderr = dispatcher.worker.probe(spec, timeout_s=args.timeout_s, turn=turn is not None)
        said = None
        if turn is not None and not problems:
            try:
                log_text = spec.log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                log_text = ""
            turn_problems, said = skill_turn_problems(log_text, builder_skills.skill_id(turn))
            problems = [*problems, *turn_problems]
        # Every command by name, so a new CLI version's own list can be pinned (BUILTIN_SLASH_COMMANDS) from this.
        print(json.dumps({
            "verdict": "PASS" if not problems else "REFUSED", "problems": problems,
            "cli_version": started.cli_version if started is not None else None,
            "skills": {"given": list(skills["provided"]), "withheld": [list(w) for w in skills["withheld"]]},
            "roster": None if started is None else {
                "tools": list(started.tools), "mcp_servers": list(started.mcp_server_status),
                "plugins": [list(p) for p in started.plugin_origins], "skills": list(started.skill_names),
                "slash_commands": list(started.slash_command_names), "permission_mode": started.permission_mode,
                "api_key_source": started.api_key_source},
            "skill_turn": said,
            "stderr_tail": stderr.strip()[-300:] if started is None else None,
        }, indent=2))
        return 0 if not problems else 2
    finally:
        builder_skills.remove_plugin(home / builder_skills.PLUGIN_NAME)
        shutil.rmtree(root, ignore_errors=True)


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    kernel, objectives, dispatcher = _parts(args)
    try:
        if args.verb == "probe-launch":
            return probe_launch(args, kernel, dispatcher)
        if args.verb == "probe-review":
            said = probe_review(cli=args.reviewer_cli or args.worker_cli,
                                token_file=Path(args.reviewer_token_file or args.worker_token_file)
                                if (args.reviewer_token_file or args.worker_token_file) else None,
                                model=args.reviewer_model, effort=args.reviewer_effort, timeout_s=args.timeout_s,
                                turn=args.turn)
            print(json.dumps(said, indent=2))
            return 0 if said["verdict"] == "PASS" else 2
        if args.verb == "skill-entry":
            entry = builder_skills.entry_for(args.name, Path(args.folder), source="repo" if args.repo_path else "installed",
                                             path=args.repo_path or "")
            print(json.dumps(entry, indent=2))
            return 0
        if args.verb == "objective":
            print(json.dumps(intake(_objective(args, kernel), kernel=kernel, objectives=objectives), indent=2))
        elif args.verb == "integrate":
            print(json.dumps(intake(_integration(args, kernel), kernel=kernel, objectives=objectives), indent=2))
        elif args.verb in ("tick", "run") and not args.publish_remote:
            raise LifecycleError(NO_PUBLISH_REMOTE)
        elif args.verb == "tick":
            for line in dispatcher.tick():
                print(line)
        elif args.verb == "run":
            ticks = 0
            while True:
                for line in dispatcher.tick():
                    print(line, flush=True)
                ticks += 1
                items = dispatcher.status()
                stages = {s["objective_id"]: s.get("stage") for s in items}
                # A completed objective still waiting to land, or being refreshed onto the trunk, is not finished.
                landing = any((s.get("landing") or {}).get("state") in ("waiting", "refreshing") for s in items)
                if all(stage in TERMINAL for stage in stages.values()) and not landing:
                    print(json.dumps(stages, indent=2))
                    break
                if args.max_ticks and ticks >= args.max_ticks:
                    print(json.dumps(stages, indent=2))
                    break
                time.sleep(args.interval)
        elif args.verb == "stops":
            reports = dispatcher.stop_reports()
            if args.json:
                print(json.dumps(reports, indent=2, default=str))
            else:
                _print_stops(reports)
        elif args.verb == "status":
            items = dispatcher.status()
            if args.json:
                print(json.dumps(items, indent=2, default=str))
            else:
                _print_status(items)
        elif args.verb == "submit-review":
            if args.reviewer != "relay":
                raise SystemExit("submit-review exists only for --reviewer relay")
            payload = Path(args.file).read_bytes()
            typed = ReviewResult.model_validate_json(payload)  # refuse malformed input at the door
            state = kernel.store.read_task_state(typed.task_id, typed.task_revision)
            dispatches = kernel.store.read_dispatches(typed.task_id, typed.attempt_id)
            if state is None or state.status is not TaskStatus.REVIEWING or not dispatches:
                raise LifecycleError(f"{typed.task_id} r{typed.task_revision} {typed.attempt_id} is not under review")
            last = dispatches[-1]
            ctx = ReviewContext(typed.task_id, typed.task_revision, typed.attempt_id, last.dispatch_seq,
                                last.candidate_sha, kernel.store.root / last.packet_path)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            print(RelayReviewer(Path(args.runtime_root) / "relay").submit(ctx, payload, stamp=stamp))
    except DispatcherBusy as exc:
        print(f"BUSY: {exc}", file=sys.stderr)
        return 4
    except (LifecycleError, RecordConflictError, StateConflictError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except JournalError as exc:
        print(f"JOURNAL FAILED: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(run())
