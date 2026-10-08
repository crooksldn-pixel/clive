"""The loop's Claude reviewer (DEC-071 ruling 10, DEC-076) against a fake ``claude`` CLI.

Only the model is replaced: a fake ``claude`` executable that speaks the stream-json the real CLI writes (an
init event with its roster, tool events, a result with ``structured_output``), reads the review room it was
started in, and can misreport its roster, tamper with the room, die or name another SHA. The reviewer
process, the review room exported from git objects, the token file, the launch check, the typed result, the
dispatcher, the kernel, the builder processes and the loop scripts are the real ones.

What these hold: the review contract is the one GPT kept (the same packet, READY / CHANGES_REQUIRED with
numbered findings, exact-SHA binding, the repair loop and its limits, the private findings channel), and the
reviewer is independent of the builder (a principal, session and room of its own, read-only tools, never an
API key, a room it cannot change without the review being void).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.orchestrator.contracts import TaskStatus
from app.orchestrator.lifecycle import PrincipalRegistry
from app.orchestrator.reviewers import (
    DECISION_SCHEMA,
    GPT_GAP,
    ClaudeCodeReviewer,
    CollectOnly,
    GptResponsesReviewer,
    GptUnavailable,
    ReviewContext,
    ReviewResult,
    reviewers_for,
)
from app.orchestrator.reviewers.claude import (
    _safe_parts,
    export_candidate,
    git_blob_id,
    room_problems,
    seal,
    token_file_problem,
    unseal_and_remove,
)
from tests.fake_credentials import anthropic_key

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_engineering_dispatcher as dispatcher_tests  # noqa: E402
from test_engineering_dispatcher import (  # noqa: E402
    EDIT_HELLO,
    FINDING,
    REGISTRY,
    FakeReviewer,
    World,
    _git,
)

TOKEN = anthropic_key("claude-reviewer", kind="oat01")
READ_ONLY_FLAGS = ["--restricted", "--permission-mode", "dontAsk", "--strict-mcp-config", "--disable-slash-commands",
                   "--no-session-persistence"]
ALLOWED_ENV = {"PATH", "HOME", "LANG", "TMPDIR", "CLIVE_REVIEW_ID", "DISABLE_AUTOUPDATER", "CLAUDE_CODE_OAUTH_TOKEN"}

FAKE_REVIEWER = r'''
import hashlib, json, os, re, sys, time
from pathlib import Path
state = Path(__file__).resolve().parent / "review-state"
if sys.argv[1:] == ["--version"]:
    print("2.1.294 (Claude Code)"); sys.exit(0)
count = state / "invocations"
n = int(count.read_text()) if count.exists() else 0
count.write_text(str(n + 1))
scenarios = json.loads((state / "scenarios.json").read_text()) if (state / "scenarios.json").exists() else [{}]
sc = scenarios[min(n, len(scenarios) - 1)]
argv = sys.argv[1:]
def arg(flag):
    return argv[argv.index(flag) + 1] if flag in argv else None
granted = argv[argv.index("--allowedTools") + 1:] if "--allowedTools" in argv else []
granted = granted[:next((i for i, a in enumerate(granted) if a.startswith("--")), len(granted))]
token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN", "")
room = Path.cwd()
packet = (room / "REVIEW_PACKET.md").read_text() if (room / "REVIEW_PACKET.md").exists() else ""
files = {}
tree = room / "candidate"
if tree.is_dir():
    for p in sorted(tree.rglob("*")):
        if p.is_file() and not p.is_symlink():
            files[p.relative_to(tree).as_posix()] = {"text": p.read_bytes()[:300].decode(errors="replace"),
                                                     "mode": oct(p.stat().st_mode & 0o777)}
(state / f"seen.{n}.json").write_text(json.dumps({
    "argv": argv, "env": sorted(os.environ), "cwd": os.getcwd(), "allowed": granted, "prompt": arg("-p"),
    "token_sha256": hashlib.sha256(token.encode()).hexdigest() if token else None,
    "packet": packet, "files": files, "room_mode": oct(room.stat().st_mode & 0o777)}))
def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n"); sys.stdout.flush()
if sc.get("die_before_init"):
    sys.stderr.write(sc.get("stderr", "boom\n")); sys.exit(1)
servers = list(json.loads(arg("--mcp-config") or "{}").get("mcpServers", {}))
emit({"type": "system", "subtype": "init", "session_id": sc.get("session") or arg("--session-id"), "cwd": os.getcwd(),
      "tools": sc.get("tools") or (arg("--tools").split(",") + ["StructuredOutput"]),
      "mcp_servers": sc.get("mcp", [{"name": s, "status": "connected"} for s in servers]),
      "plugins": sc.get("plugins", [{"name": "cc-plugin-telemetry", "path": "builtin",
                                     "source": "cc-plugin-telemetry@builtin"}]),
      "skills": sc.get("skills", []), "slash_commands": sc.get("slash_commands", []),
      "permissionMode": sc.get("permission_mode", arg("--permission-mode")), "model": "fake-reviewer",
      "apiKeySource": sc.get("api_key_source", "none"), "claude_code_version": "2.1.294"})
time.sleep(sc.get("sleep_after_init", 0))
emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "r1", "name": "Read",
      "input": {"file_path": str(room / "REVIEW_PACKET.md")}}]}})
emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "r1"}]}})
for i, name in enumerate(sc.get("tool_calls", [])):
    emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"c{i}", "name": name, "input": {}}]}})
    emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"c{i}"}]}})
for rel, content in sc.get("tamper", {}).items():      # the room changed under the review (never through its tools)
    target = room / rel
    target.parent.chmod(0o755)
    if target.exists():
        target.chmod(0o644)
    target.write_text(content)
if sc.get("die"):
    sys.stderr.write(sc.get("stderr", "killed\n")); sys.exit(1)
time.sleep(sc.get("sleep_before_result", 0))
found = re.search(r'"candidate_sha": "([0-9a-f]{40})"', packet) or re.search(r"CANDIDATE SHA ([0-9a-f]{40})", arg("-p") or "")
sha = "1" * 40 if sc.get("wrong_sha") else (found.group(1) if found else "0" * 40)
hello = files.get("pkg/hello.txt", {}).get("text", "").strip()
decision = {"candidate_sha": sha, "verdict": sc.get("verdict", "READY"), "findings": sc.get("findings", []),
            "summary": f"read the packet; pkg/hello.txt at the candidate reads {hello!r}"}
(state / f"answered.{n}").write_text("1")
if "error" in sc:
    emit(dict({"type": "result", "subtype": "error_during_execution", "is_error": True}, **sc["error"]))
else:
    emit({"type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "session_id": arg("--session-id"),
          "structured_output": sc.get("structured_output", decision)})
time.sleep(sc.get("sleep_after_result", 0))
'''


class FakeReviewerCli:
    """The fake ``claude`` a review runs, and what it saw."""

    def __init__(self, tmp: Path) -> None:
        self.dir = tmp / "reviewer-cli"
        self.dir.mkdir()
        self.state = self.dir / "review-state"
        self.state.mkdir()
        self.path = self.dir / "claude"
        self.path.write_text(f"#!{sys.executable}\n{FAKE_REVIEWER}")
        self.path.chmod(0o755)

    def scenarios(self, *items: dict) -> None:
        (self.state / "scenarios.json").write_text(json.dumps(list(items)))

    def invocations(self) -> int:
        f = self.state / "invocations"
        return int(f.read_text()) if f.exists() else 0

    def seen(self, n: int = 0) -> dict:
        return json.loads((self.state / f"seen.{n}.json").read_text())

    def answered(self, n: int = 0) -> bool:
        return (self.state / f"answered.{n}").exists()


def token_file(tmp: Path, value: str = TOKEN, mode: int = 0o600) -> Path:
    path = tmp / "secrets" / "claude_token"
    path.parent.mkdir(exist_ok=True)
    path.write_text(value + "\n")
    path.chmod(mode)
    return path


def claude(tmp: Path, w: World, cli: FakeReviewerCli, **kw) -> ClaudeCodeReviewer:
    return ClaudeCodeReviewer(w.config.runtime_root / "claude-review", repo=w.repo, cli=str(cli.path),
                              token_file=kw.pop("token", None) or token_file(tmp), timeout_s=kw.pop("timeout_s", 30),
                              **kw)


@pytest.fixture
def fake(tmp_path) -> FakeReviewerCli:
    return FakeReviewerCli(tmp_path)


def wait_for(predicate, timeout: float = 20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError("timed out")


def every_file_under(root: Path) -> str:
    return "".join(p.read_text(errors="replace") for p in root.rglob("*") if p.is_file())


def admitted_result(w: World, revision: int = 1) -> ReviewResult:
    attempt = next(a for a in w.store.read_attempts("demo-objective") if a.task_revision == revision)
    admitted = w.store.read_admissions("demo-objective", attempt.attempt_id)[-1]
    return ReviewResult.model_validate_json((w.store.root / admitted.payload_path).read_bytes())


# ---------------------------------------------------------------- one review, end to end

def test_a_finished_candidate_goes_to_the_claude_reviewer_and_its_typed_verdict_completes_it(tmp_path, fake,
                                                                                             monkeypatch):
    # Whatever the dispatcher's own environment holds, none of it reaches the reviewer's CLI.
    monkeypatch.setenv("ANTHROPIC_API_KEY", anthropic_key("dispatcher-env"))
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-leak")
    w = World(tmp_path)
    w.reviewers[:] = [claude(tmp_path, w, fake)]
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(lambda: w.stage() == "COMPLETE")

    attempt = w.store.read_attempts("demo-objective")[0]
    dispatch = w.store.read_dispatches("demo-objective", attempt.attempt_id)[-1]
    sha = dispatch.candidate_sha
    assert dispatch.reviewer_principal_id == "claude-reviewer" and attempt.worker.principal.principal_id == "claude"
    seen = fake.seen()
    argv = seen["argv"]
    # the read-only launch: three file-reading tools, nothing else, no server, no setting, no skill, no persistence
    assert argv[argv.index("--tools") + 1] == "Read,Glob,Grep" and seen["allowed"] == ["Read", "Glob", "Grep"]
    assert all(flag in argv for flag in READ_ONLY_FLAGS)
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert json.loads(argv[argv.index("--json-schema") + 1]) == DECISION_SCHEMA
    # a session and a room of its own: never the builder's session, never a builder's workspace
    session = argv[argv.index("--session-id") + 1]
    assert session != attempt.worker.session.session_id
    room = Path(seen["cwd"])
    assert (w.config.runtime_root / "claude-review") in room.parents
    assert not str(room).startswith(str(w.config.workspace_root))
    # the environment is built from nothing; the token arrives only as the plan's OAuth variable
    assert set(seen["env"]) == ALLOWED_ENV
    assert seen["token_sha256"] == hashlib.sha256(TOKEN.encode()).hexdigest()
    # the same packet the dispatcher keeps, and the candidate's whole tree at that SHA, read-only
    assert seen["packet"].encode() == (w.store.root / dispatch.packet_path).read_bytes()
    assert sha in seen["prompt"] and "pkg/hello.txt reads 'hello'" in seen["packet"]
    assert seen["files"]["pkg/hello.txt"] == {"text": "hello\n", "mode": "0o444"}
    assert seen["files"]["README"]["text"] == "outside the scope\n" and seen["room_mode"] == "0o555"
    # the typed result is bound by the driver, and the kernel admitted it as an independent review
    result = admitted_result(w)
    assert (result.task_id, result.task_revision, result.attempt_id, result.candidate_sha) == (
        "demo-objective", 1, attempt.attempt_id, sha)
    facts = result.reviewer
    assert facts.principal_id == "claude-reviewer" and facts.session_id == f"claude-code:{session}"
    assert facts.workspace_head == sha and facts.read_only and facts.clean and facts.context_fresh
    assert facts.workspace_id != attempt.worker.workspace.workspace_id
    assert "pkg/hello.txt at the candidate reads 'hello'" in result.summary
    mechanism = w.dispatcher().status()[0]["review_mechanism"]
    assert mechanism["principal_id"] == "claude-reviewer" and mechanism["courier"] is False
    assert mechanism["mechanism"] == "claude-code-cli:default model"
    # the room is gone once the review is written; the token is nowhere the loop writes
    assert not room.exists()
    for root in (tmp_path / "runtime", tmp_path / "engineering", tmp_path / "workers", w.state):
        assert TOKEN not in every_file_under(root), root


def test_changes_required_routes_a_repair_whose_packet_carries_the_findings_and_whose_candidate_is_reviewed_again(
        tmp_path, fake):
    fake.scenarios({"verdict": "CHANGES_REQUIRED", "findings": [FINDING]}, {"verdict": "READY"})
    w = World(tmp_path)
    w.reviewers[:] = [claude(tmp_path, w, fake)]
    w.scenarios(EDIT_HELLO, {"edits": [["pkg/hello.txt", "hello!\n"]]})
    w.objective()
    w.run_until(lambda: w.stage() == "COMPLETE", timeout=40)

    repair = max(w.store.read_tasks(), key=lambda t: t.revision)
    assert repair.revision == 2 and "F-01" in repair.objective
    # the same packet as for GPT: the repair's packet names the earlier finding, and the reviewer read it
    assert "## Findings of earlier revisions" in fake.seen(1)["packet"] and "[F-01] the greeting is wrong" in \
        fake.seen(1)["packet"]
    assert fake.seen(1)["files"]["pkg/hello.txt"]["text"] == "hello!\n"
    first, second = admitted_result(w, 1), admitted_result(w, 2)
    assert first.verdict == "CHANGES_REQUIRED" and [f.finding_id for f in first.material_findings] == ["F-01"]
    assert second.verdict == "READY" and second.candidate_sha != first.candidate_sha


def test_the_repair_limit_still_holds_and_the_findings_reach_the_private_stop_report(tmp_path, fake):
    fake.scenarios({"verdict": "CHANGES_REQUIRED", "findings": [FINDING]})
    w = World(tmp_path, max_repair_rounds=1)
    w.reviewers[:] = [claude(tmp_path, w, fake)]
    w.scenarios(EDIT_HELLO, {"edits": [["pkg/hello.txt", "hello!\n"]]})
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED), timeout=40)
    assert "convergence limit: 1 repair round(s) used of 1" in w.state_of().blocker_reason
    [report] = w.dispatcher().stop_reports()
    assert report["cause"] == "review_limit"
    assert [r["reviewer"] for r in report["review_rounds"]] == ["claude-reviewer", "claude-reviewer"]
    assert report["review_rounds"][-1]["findings"][0] == {**FINDING}


# ---------------------------------------------------------------- refusals: every one an error, never a verdict

def _one_review(tmp_path: Path, fake: FakeReviewerCli, **kw) -> tuple[ClaudeCodeReviewer, ReviewContext]:
    w = World(tmp_path)
    packet = tmp_path / "packet.md"
    packet.write_text(f'## Header\n"candidate_sha": "{w.base}"\n')
    reviewer = claude(tmp_path, w, fake, **kw)
    return reviewer, ReviewContext("t", 1, "t-a1", 1, w.base, packet)


def test_a_model_that_names_another_sha_is_refused(tmp_path, fake):
    fake.scenarios({"wrong_sha": True})
    reviewer, ctx = _one_review(tmp_path, fake)
    reviewer.start(ctx)
    assert wait_for(lambda: reviewer.problem(ctx)).startswith("Claude review run 1 failed: the model reviewed '1111")
    assert reviewer.poll(ctx) == []


@pytest.mark.parametrize("deviation, refusal", [
    ({"tools": ["Read", "Glob", "Grep", "StructuredOutput", "Edit"]}, "tools beyond a read-only review: Edit"),
    ({"tools": ["Read", "Glob", "Grep", "StructuredOutput", "Bash"]}, "tools beyond a read-only review: Bash"),
    ({"tools": ["Glob", "Grep", "StructuredOutput"]}, "the Read tool is missing"),
    ({"mcp": [{"name": "gmail", "status": "connected"}]}, "MCP servers present: gmail"),
    ({"plugins": [{"name": "x", "path": "/home/x", "source": "x@market"}]}, "plugins beyond the builtin allowance"),
    ({"skills": ["design"], "slash_commands": ["design"]}, "1 skills and 1 slash commands loaded"),
    ({"permission_mode": "acceptEdits"}, "permission mode 'acceptEdits'"),
    ({"api_key_source": "ANTHROPIC_API_KEY"}, "API-key source 'ANTHROPIC_API_KEY': that is pay-as-you-go"),
    ({"session": "someone-elses-session"}, "is not the review's session"),
])
def test_a_launch_that_is_not_read_only_on_the_owners_plan_is_stopped_at_init(tmp_path, fake, deviation, refusal):
    fake.scenarios({**deviation, "sleep_after_init": 5})
    reviewer, ctx = _one_review(tmp_path, fake)
    reviewer.start(ctx)
    problem = wait_for(lambda: reviewer.problem(ctx))
    assert problem.startswith("Claude review run 1 failed: reviewer launch refused: ") and refusal in problem
    assert not fake.answered()                     # stopped at its init event, before it answered anything
    assert reviewer.poll(ctx) == []


def test_a_review_room_changed_during_the_review_voids_it(tmp_path, fake):
    fake.scenarios({"tamper": {"candidate/README": "rewritten\n"}}, {"tamper": {"candidate/pkg/extra.txt": "new\n"}})
    reviewer, ctx = _one_review(tmp_path, fake)
    reviewer.start(ctx)
    assert "README" in wait_for(lambda: reviewer.problem(ctx)) and "the review is void" in reviewer.problem(ctx)
    wait_for(lambda: (reviewer.start(ctx), "run 2" in (reviewer.problem(ctx) or ""))[1])
    assert "pkg/extra.txt" in reviewer.problem(ctx) and reviewer.poll(ctx) == []


def test_a_reviewer_that_calls_anything_but_a_read_only_tool_is_refused(tmp_path, fake):
    fake.scenarios({"tool_calls": ["Write"]})
    reviewer, ctx = _one_review(tmp_path, fake)
    reviewer.start(ctx)
    assert "called tools beyond a read-only review: Write" in wait_for(lambda: reviewer.problem(ctx))


def test_a_review_that_fails_every_run_blocks_with_the_reason_instead_of_waiting_for_ever(tmp_path, fake):
    fake.scenarios({"die": True, "stderr": "Not logged in · Please run /login\n"})
    w = World(tmp_path)
    w.reviewers[:] = [claude(tmp_path, w, fake)]
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED), timeout=60)
    reason = w.state_of().blocker_reason
    assert "could not be obtained: Claude review run 3 failed: the reviewer could not authenticate" in reason
    assert "(no further runs)" in reason and fake.invocations() == 3 and TOKEN not in reason


def test_the_reviewers_workspace_id_stays_within_the_routing_limit_for_the_longest_ids(tmp_path):
    # Review of the branch, N7: task and attempt ids may each be 120 characters (contracts.py). The workspace id the
    # result declares must still fit routing.Workspace, or party() raises after the payload is consumed and the
    # review is never admitted. A short id stays readable; a long one is hashed, one per task/attempt/dispatch/run.
    from app.orchestrator.reviewers.claude import Session, _result_of
    from app.orchestrator.routing import Workspace
    from app.orchestrator.workers.base import Started

    limit = next(m.max_length for m in Workspace.model_fields["workspace_id"].metadata if hasattr(m, "max_length"))
    started = Started(session_id="3f1c5b8e-1111-4222-8333-944445555666", cwd=str(tmp_path), model="m",
                      tools=("Read", "Glob", "Grep", "StructuredOutput"), mcp_servers=(), plugins=(), skills=0,
                      slash_commands=0, permission_mode="dontAsk", api_key_source="none", cli_version="2.1.294")
    done = Session(started, {"num_turns": 3}, [])
    decision = {"candidate_sha": "a" * 40, "verdict": "READY", "findings": [], "summary": "ok"}

    def facts(task: str, attempt: str, seq: int = 1, run: str = "run.1"):
        job = {"candidate_sha": "a" * 40, "task_id": task, "task_revision": 1, "attempt_id": attempt,
               "dispatch_seq": seq}
        result = _result_of(job, decision, done, datetime.now(UTC), run)
        result.reviewer.party()                        # what the kernel does on admission: must not raise
        return result.reviewer.workspace_id

    task, attempt = "t" * 120, ("t" * 114 + "-a1234")
    assert len(task) == len(attempt) == 120
    long_id = facts(task, attempt, 12, "run.3")
    assert len(long_id) <= limit and long_id.startswith("claude-review:")
    assert len({long_id, facts(task, attempt, 12, "run.2"), facts(task, attempt, 13, "run.3"),
                facts(task, "t" * 114 + "-a1235", 12, "run.3")}) == 4
    assert facts("demo-objective", "demo-objective-a1") == "claude-review:demo-objective/demo-objective-a1/dispatch.1/run.1"


# ---------------------------------------------------------------- the token: the owner's plan, never an API key

def test_the_token_file_must_be_private_and_never_an_api_key(tmp_path):
    assert token_file_problem(token_file(tmp_path)) is None
    for mode in (0o640, 0o604, 0o644):
        problem = token_file_problem(token_file(tmp_path, mode=mode))
        assert "chmod 600" in problem and TOKEN not in problem
    api_key = anthropic_key("not-the-plan")
    problem = token_file_problem(token_file(tmp_path, value=api_key))
    assert "pay-as-you-go" in problem and api_key not in problem
    assert "is empty" in token_file_problem(token_file(tmp_path, value=""))
    assert "not readable" in token_file_problem(tmp_path / "missing")


def test_an_api_key_in_the_token_file_makes_the_reviewer_unavailable_so_the_task_blocks_with_the_gap(tmp_path, fake):
    w = World(tmp_path)
    w.reviewers[:] = [claude(tmp_path, w, fake, token=token_file(tmp_path, value=anthropic_key("not-the-plan")))]
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    assert "claude-reviewer: reviewer token file" in w.state_of().blocker_reason
    assert "pay-as-you-go" in w.state_of().blocker_reason and fake.invocations() == 0


# ---------------------------------------------------------------- the review room

def _repo_with_traps(tmp: Path) -> tuple[Path, str]:
    repo = tmp / "traps"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "hello.txt").write_text("hello\n")
    (repo / "run.sh").write_text("#!/bin/sh\necho hi\n")
    (repo / "run.sh").chmod(0o755)
    (repo / "hidden.txt").write_text("a reviewer must still see this\n")
    (repo / ".gitattributes").write_text("hidden.txt export-ignore\npkg/hello.txt filter=nope\n")
    os.symlink("/etc/passwd", repo / "passwd-link")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "traps")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_the_room_is_the_commit_from_git_objects_links_are_notes_and_any_change_is_found(tmp_path):
    repo, sha = _repo_with_traps(tmp_path)
    room = tmp_path / "room"
    expected = export_candidate(repo, sha, room / "candidate")
    tree = room / "candidate"
    assert (tree / "hidden.txt").read_text() == "a reviewer must still see this\n"      # no attribute applies
    assert (tree / "pkg" / "hello.txt").read_text() == "hello\n"
    link = tree / "passwd-link"
    assert link.is_file() and not link.is_symlink() and "/etc/passwd" in link.read_text()
    assert "never followed" in link.read_text()
    blob = _git(repo, "rev-parse", f"{sha}:pkg/hello.txt")
    assert expected["pkg/hello.txt"] == blob == git_blob_id(b"hello\n")
    packet = b"the packet\n"
    (room / "REVIEW_PACKET.md").write_bytes(packet)
    seal(room)
    assert room_problems(room, expected, git_blob_id(packet)) == []
    assert all(not (p.stat().st_mode & 0o222) for p in [room, *room.rglob("*")])
    (tree / "pkg").chmod(0o755)
    (tree / "pkg" / "hello.txt").chmod(0o644)
    (tree / "pkg" / "hello.txt").write_text("goodbye\n")
    problems = room_problems(room, expected, git_blob_id(packet))
    assert any("writable" in p for p in problems) and any("pkg/hello.txt" in p for p in problems)
    unseal_and_remove(room)
    assert not room.exists()


def _tamper(repo: Path, oid: str, data: bytes) -> None:
    """Rewrite one loose object in place: its id stays, its bytes change (git does not check on an ordinary read)."""
    import zlib

    loose = repo / ".git" / "objects" / oid[:2] / oid[2:]
    loose.chmod(0o644)
    loose.write_bytes(zlib.compress(b"blob %d\0" % len(data) + data))


@pytest.mark.parametrize("path, altered", [("pkg/hello.txt", b"hullo\n"), ("passwd-link", b"/etc/shadow")])
def test_an_object_whose_bytes_are_not_its_tree_id_is_never_reviewed(tmp_path, path, altered):
    # Review of the branch, N6: the room is checked against the commit's own blob ids as it is written, so a corrupt
    # or altered object in the dispatcher's clone is refused, never reviewed (a file and a link alike).
    repo, sha = _repo_with_traps(tmp_path)
    oid = _git(repo, "rev-parse", f"{sha}:{path}")
    _tamper(repo, oid, altered)
    assert _git(repo, "cat-file", "blob", oid) == altered.decode().strip()   # what an unchecked export would write
    with pytest.raises(RuntimeError, match=f"blob {oid} does not hash to its id"):
        export_candidate(repo, sha, tmp_path / "room" / "candidate")


@pytest.mark.parametrize("path", [b"../escape", b"a/../../b", b"/etc/passwd", b".git/config", b"x/.GIT/hooks",
                                  b"a//b", b"./a"])
def test_a_tree_path_that_could_reach_outside_the_room_is_refused(path):
    with pytest.raises(ValueError, match="the review room refuses"):
        _safe_parts(path)


# ---------------------------------------------------------------- the choice, and the switch at a re-pin

def test_claude_is_the_default_and_gpt_is_selectable_so_a_repin_can_fall_back(tmp_path):
    key = tmp_path / "openai_key"
    key.write_text("x")
    key.chmod(0o600)
    claude_only = reviewers_for("claude", runtime=tmp_path, repo=tmp_path)
    assert [type(r) for r in claude_only] == [ClaudeCodeReviewer]
    with_key = reviewers_for("claude", runtime=tmp_path, repo=tmp_path, gpt_key_file=str(key))
    assert isinstance(with_key[1], CollectOnly) and isinstance(with_key[1].driver, GptResponsesReviewer)
    assert with_key[1].availability()[0] is False
    gpt = reviewers_for("gpt", runtime=tmp_path, repo=tmp_path, gpt_key_file=str(key))
    assert isinstance(gpt[0], GptResponsesReviewer) and isinstance(gpt[1].driver, ClaudeCodeReviewer)
    assert isinstance(reviewers_for("gpt", runtime=tmp_path, repo=tmp_path)[0], GptUnavailable)
    registry = PrincipalRegistry.load(REGISTRY)
    assert registry.may_review("claude-reviewer") and not registry.may_review("claude") and registry.may_review("gpt")
    assert "author" not in registry.principals["claude-reviewer"]["roles"]


def test_a_review_given_to_claude_before_a_switch_to_gpt_still_finishes_and_gpt_takes_the_next(tmp_path, fake):
    fake.scenarios({"sleep_before_result": 2})
    w = World(tmp_path, max_concurrent=2)
    loop = dict(runtime=w.config.runtime_root, repo=w.repo, claude_cli=str(fake.path),
                claude_token_file=str(token_file(tmp_path)))
    w.reviewers[:] = reviewers_for("claude", **loop)
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    w.reviewers[:] = reviewers_for("gpt", **loop)              # the re-pin falls back to GPT, with no key yet
    w.run_until(lambda: w.stage() == "COMPLETE", timeout=30)
    assert admitted_result(w).reviewer.principal_id == "claude-reviewer"
    w.objective(objective_id="second", target_branch="clive/objective/second")
    w.run_until(lambda: w.store.read_task_state("second", 1).status is TaskStatus.BLOCKED, timeout=30)
    reason = w.store.read_task_state("second", 1).blocker_reason
    assert GPT_GAP.split(":")[0] in reason and "claude-reviewer: collect-only" in reason
    assert fake.invocations() == 1


def test_a_review_given_to_gpt_before_the_repin_to_claude_still_finishes_and_claude_takes_the_next(tmp_path, fake):
    w = World(tmp_path, max_concurrent=2)
    old = FakeReviewer("gpt")
    w.reviewers[:] = [old]
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.REVIEWING))
    w.reviewers[:] = [claude(tmp_path, w, fake), CollectOnly(old, "claude")]
    old.answers.append(lambda ctx: dispatcher_tests.review(ctx))
    w.run_until(lambda: w.stage() == "COMPLETE")
    assert admitted_result(w).reviewer.principal_id == "gpt" and fake.invocations() == 0
    w.objective(objective_id="second", target_branch="clive/objective/second")
    w.run_until(lambda: any(i.task_id == "second" for i in w.store.read_integrations()), timeout=30)
    second = w.store.read_attempts("second")[0]
    assert w.store.read_dispatches("second", second.attempt_id)[-1].reviewer_principal_id == "claude-reviewer"


# ---------------------------------------------------------------- the loop scripts

def _flags(tmp: Path, fake: FakeReviewerCli, *extra: str) -> list[str]:
    return ["--store", str(tmp / "engineering"), "--repo", str(tmp), "--runtime-root", str(tmp / "runtime"),
            "--workspace-root", str(tmp / "workers"), "--worker-cli", str(fake.path),
            "--worker-token-file", str(token_file(tmp)), *extra]


def test_both_loop_scripts_run_the_claude_reviewer_by_default_on_the_workers_cli_and_token(tmp_path, fake):
    from scripts import engineering_dispatcher, remote_engineering

    args = engineering_dispatcher.build_parser().parse_args([*_flags(tmp_path, fake), "status"])
    [reviewer] = engineering_dispatcher._parts(args)[2].reviewers
    assert isinstance(reviewer, ClaudeCodeReviewer) and reviewer.cli == str(fake.path)
    assert reviewer.token_file == tmp_path / "secrets" / "claude_token"
    own = tmp_path / "own-token"
    own.write_text("x")
    args = engineering_dispatcher.build_parser().parse_args(
        [*_flags(tmp_path, fake, "--reviewer-cli", "/opt/claude", "--reviewer-token-file", str(own),
                 "--reviewer-model", "opus"), "status"])
    reviewer = engineering_dispatcher._parts(args)[2].reviewers[0]
    assert (reviewer.cli, reviewer.token_file, reviewer.model) == ("/opt/claude", own, "opus")
    args = engineering_dispatcher.build_parser().parse_args([*_flags(tmp_path, fake, "--reviewer", "gpt"), "status"])
    assert isinstance(engineering_dispatcher._parts(args)[2].reviewers[0], GptUnavailable)

    run = ["run", "--repository", "crooksldn-pixel/clive", "--product-memory-ref", "main"]
    args = remote_engineering.build_parser().parse_args([*_flags(tmp_path, fake, "--publish-remote", "origin"), *run])
    _store, kernel, objectives, _receipts = remote_engineering._kernel_parts(args)
    [reviewer] = remote_engineering._dispatcher(args, kernel, objectives).reviewers
    assert isinstance(reviewer, ClaudeCodeReviewer) and reviewer.cli == str(fake.path)
    key = tmp_path / "openai_key"
    args = remote_engineering.build_parser().parse_args(
        [*_flags(tmp_path, fake, "--publish-remote", "origin", "--gpt-api-key-file", str(key)), *run])
    reviewers = remote_engineering._dispatcher(args, kernel, objectives).reviewers
    assert isinstance(reviewers[0], ClaudeCodeReviewer) and isinstance(reviewers[1], CollectOnly)


def _probe(tmp_path: Path, fake: FakeReviewerCli, *extra: str) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "scripts" /
                                               "engineering_dispatcher.py"),
                           *_flags(tmp_path, fake), "--no-journal", "probe-review", *extra],
                          capture_output=True, text=True, timeout=60)
    return proc.returncode, json.loads(proc.stdout)


def test_probe_review_launches_the_reviewer_as_a_review_would_and_stops_it_at_init(tmp_path, fake):
    fake.scenarios({"sleep_after_init": 5})
    code, said = _probe(tmp_path, fake)
    assert code == 0 and said["verdict"] == "PASS" and said["problems"] == []
    assert said["roster"]["tools"] == ["Read", "Glob", "Grep", "StructuredOutput"]
    assert said["roster"]["api_key_source"] == "none" and said["turn"] is None
    assert not fake.answered(0)
    fake.scenarios({"api_key_source": "ANTHROPIC_API_KEY", "sleep_after_init": 5})
    code, said = _probe(tmp_path, fake)
    assert code == 2 and said["verdict"] == "REFUSED" and "pay-as-you-go" in said["problems"][0]
    assert said["roster"]["api_key_source"] == "ANTHROPIC_API_KEY"          # what the CLI showed, for the operator


def test_probe_review_turn_proves_a_review_can_finish_on_the_token(tmp_path, fake):
    code, said = _probe(tmp_path, fake, "--turn")
    assert code == 0 and said["verdict"] == "PASS" and said["turn"] == {"finished": "success", "num_turns": 3}
    assert fake.seen(0)["token_sha256"] == hashlib.sha256(TOKEN.encode()).hexdigest()
