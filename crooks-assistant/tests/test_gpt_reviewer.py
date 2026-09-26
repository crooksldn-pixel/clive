"""The programmatic GPT reviewer, and several objectives at once, against a local Responses API double.

Only OpenAI is replaced, by an HTTP server on 127.0.0.1 that answers the documented
``POST /v1/responses`` shape. The reviewer process, the key file, the git object reads,
the typed result, the dispatcher, the kernel and the builder processes are the real ones.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.orchestrator.contracts import TaskStatus
from app.orchestrator.lifecycle import lifecycle_view
from app.orchestrator.reviewers import GptResponsesReviewer, ReviewContext, ReviewResult
from app.orchestrator.reviewers.gpt import key_file_problem, redact
from tests.fake_credentials import openai_key

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_engineering_dispatcher import EDIT_HELLO, FINDING, World, _git  # noqa: E402

KEY = openai_key("gpt-reviewer")


class FakeOpenAI:
    """Answers /v1/responses. ``hold`` names task ids whose review waits until released."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.headers: list[dict] = []
        self.verdict = "READY"
        self.wrong_sha = False
        self.status = 200
        self.hold: set[str] = set()
        self.released = threading.Event()
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                outer.headers.append(dict(self.headers))
                text = body["input"][0]["content"][0]["text"]
                sha = re.search(r"CANDIDATE SHA: ([0-9a-f]{40})", text).group(1)
                task = re.search(r"TASK: (\S+) ", text).group(1)
                if task in outer.hold:
                    outer.released.wait(30)
                if outer.status != 200:
                    self.send_response(outer.status)
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": {"message": f"Incorrect API key provided: {KEY[:12]}..."}}).encode())
                    return
                decision = {"candidate_sha": "0" * 40 if outer.wrong_sha else sha, "verdict": outer.verdict,
                            "findings": [FINDING] if outer.verdict == "CHANGES_REQUIRED" else [],
                            "summary": "checked the diff against the acceptance criteria"}
                payload = {"id": f"resp_{len(outer.requests)}", "status": "completed", "model": body["model"],
                           "output": [{"type": "reasoning", "summary": []},
                                      {"type": "message", "content": [{"type": "output_text",
                                                                       "text": json.dumps(decision)}]}],
                           "usage": {"input_tokens": 10, "output_tokens": 5}}
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.released.set()
        self.server.shutdown()


@pytest.fixture
def openai(monkeypatch):
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    fake = FakeOpenAI()
    yield fake
    fake.close()


def key_file(tmp: Path, mode: int = 0o600) -> Path:
    path = tmp / "secrets" / "openai_api_key"
    path.parent.mkdir(exist_ok=True)
    path.write_text(KEY + "\n")
    path.chmod(mode)
    return path


def gpt(tmp: Path, repo: Path, openai: FakeOpenAI, **kw) -> GptResponsesReviewer:
    return GptResponsesReviewer(tmp / "runtime" / "gpt", repo=repo, key_file=key_file(tmp), api_base=openai.base,
                                timeout_s=30, **kw)


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


# ---------------------------------------------------------------- the key

def test_the_key_file_must_be_private_and_is_never_echoed(tmp_path):
    assert key_file_problem(key_file(tmp_path)) is None
    for mode in (0o640, 0o604, 0o644):
        problem = key_file_problem(key_file(tmp_path, mode))
        assert problem and "chmod 600" in problem and KEY not in problem
    assert "not readable" in key_file_problem(tmp_path / "missing")
    assert KEY not in redact(f"Incorrect API key provided: {KEY}; Authorization: Bearer {KEY}")


def test_an_unusable_key_makes_the_reviewer_unavailable_so_the_task_blocks_with_the_gap(tmp_path, openai):
    w = World(tmp_path)
    reviewer = gpt(tmp_path, w.repo, openai)
    reviewer.key_file.chmod(0o644)
    w.reviewers[:] = [reviewer]
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED))
    assert "readable by group or others" in w.state_of().blocker_reason and openai.requests == []


# ---------------------------------------------------------------- one review, end to end

def test_a_finished_candidate_goes_to_gpt_without_a_courier_and_the_typed_verdict_completes_it(tmp_path, openai):
    w = World(tmp_path)
    w.reviewers[:] = [gpt(tmp_path, w.repo, openai)]
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(lambda: w.stage() == "COMPLETE")

    attempt = w.store.read_attempts("demo-objective")[0]
    dispatch = w.store.read_dispatches("demo-objective", attempt.attempt_id)[-1]
    assert dispatch.reviewer_principal_id == "gpt"
    request = openai.requests[0]
    # the documented Responses API shape: the loop's model at medium reasoning (owner decision
    # 2026-09-26), a strict schema, nothing stored
    assert request["model"] == "gpt-6-luna" and request["reasoning"] == {"effort": "medium"}
    assert request["text"]["format"]["type"] == "json_schema" and request["text"]["format"]["strict"] is True
    assert request["store"] is False and "previous_response_id" not in request
    text = request["input"][0]["content"][0]["text"]
    assert dispatch.candidate_sha in text and "pkg/hello.txt reads 'hello'" in text  # SHA and acceptance
    assert f"--- pkg/hello.txt at {dispatch.candidate_sha}\nhello" in text  # read from git objects at the SHA
    assert openai.headers[0]["Authorization"] == f"Bearer {KEY}"
    # the typed result is bound by the driver, not the model
    admitted = w.store.read_admissions("demo-objective", attempt.attempt_id)[-1]
    result = ReviewResult.model_validate_json((w.store.root / admitted.payload_path).read_bytes())
    assert (result.task_id, result.task_revision, result.attempt_id, result.candidate_sha) == (
        "demo-objective", 1, attempt.attempt_id, dispatch.candidate_sha)
    assert result.reviewer.principal_id == "gpt" and result.reviewer.session_id == "openai-response:resp_1"
    assert result.reviewer.workspace_head == dispatch.candidate_sha and result.reviewer.read_only
    status = w.dispatcher().status()[0]
    assert status["review_mechanism"]["courier"] is False
    # the key is nowhere the dispatcher, the kernel or a builder writes
    for root in (tmp_path / "runtime", tmp_path / "engineering", tmp_path / "workers", w.state):
        assert KEY not in every_file_under(root), root


def test_changes_required_from_gpt_routes_a_repair(tmp_path, openai):
    openai.verdict = "CHANGES_REQUIRED"
    w = World(tmp_path)
    w.reviewers[:] = [gpt(tmp_path, w.repo, openai)]
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(lambda: max(t.revision for t in w.store.read_tasks()) == 2)
    repair = max(w.store.read_tasks(), key=lambda t: t.revision)
    assert "F-01" in repair.objective


def test_a_model_that_names_another_sha_is_refused_and_a_failed_run_never_leaks_the_key(tmp_path, openai):
    w = World(tmp_path)
    base = w.base
    packet = tmp_path / "packet.md"
    packet.write_text("## Objective\nx\n")
    ctx = ReviewContext("t", 1, "t-a1", 1, base, packet)
    reviewer = gpt(tmp_path, w.repo, openai)
    openai.wrong_sha = True
    reviewer.start(ctx)
    assert wait_for(lambda: reviewer.problem(ctx)).startswith("GPT review run 1 failed: the model reviewed")
    assert reviewer.poll(ctx) == []
    openai.wrong_sha, openai.status = False, 401
    # every tick calls start(); once run 1's process has exited, run 2 begins
    wait_for(lambda: (reviewer.start(ctx), "run 2" in (reviewer.problem(ctx) or ""))[1])
    assert "HTTP 401" in reviewer.problem(ctx)
    assert KEY not in every_file_under(tmp_path / "runtime") and "[redacted]" in every_file_under(tmp_path / "runtime")


# ---------------------------------------------------------------- several objectives at once

def test_three_objectives_run_concurrently_and_one_under_review_never_holds_up_another(tmp_path, openai):
    w = World(tmp_path, max_concurrent=3)
    w.reviewers[:] = [gpt(tmp_path, w.repo, openai)]
    w.scenarios({**EDIT_HELLO, "sleep_before_result": 1.5})
    ids = ("obj-a", "obj-b", "obj-c")
    for oid in ids:
        w.objective(objective_id=oid, target_branch=f"clive/objective/{oid}")
    openai.hold.add("obj-a")  # GPT takes its time over obj-a

    def stage(oid):
        tasks = [t for t in lifecycle_view(w.store, now=w.clock())["tasks"] if t["task_id"] == oid]
        return max(tasks, key=lambda t: t["revision"])["stage"]

    def attempts():
        return [a for oid in ids for a in w.store.read_attempts(oid)]

    d = w.dispatcher()
    d.tick()
    # one controller, three builder processes alive at once, each its own attempt, session and workspace
    assert len(wait_for(lambda: len(_pids(tmp_path)) == 3 and _pids(tmp_path))) == 3
    got = attempts()
    assert len({a.task_id for a in got}) == 3 and len({a.attempt_id for a in got}) == 3
    assert len({a.worker.session.session_id for a in got}) == 3
    assert len({a.worker.workspace.workspace_id for a in got}) == 3
    assert len({Path(tmp_path / "runtime" / "homes" / a.attempt_id) for a in got}) == 3

    w.run_until(lambda: stage("obj-b") == "COMPLETE" and stage("obj-c") == "COMPLETE", dispatcher=d)
    assert w.store.read_task_state("obj-a", 1).status is TaskStatus.REVIEWING  # still with GPT
    openai.released.set()
    w.run_until(lambda: stage("obj-a") == "COMPLETE", dispatcher=d)
    # none overwrote another: three target branches, each at its own accepted candidate
    heads = {oid: _git(w.repo, "rev-parse", f"clive/objective/{oid}") for oid in ids}
    assert len(set(heads.values())) == 3
    for oid in ids:
        assert w.store.read_integrations() and any(i.integration_sha == heads[oid] for i in w.store.read_integrations())


def test_the_concurrency_limit_holds(tmp_path, openai):
    w = World(tmp_path, max_concurrent=2)
    w.reviewers[:] = [gpt(tmp_path, w.repo, openai)]
    w.scenarios({**EDIT_HELLO, "sleep_before_result": 1.0})
    for oid in ("obj-a", "obj-b", "obj-c"):
        w.objective(objective_id=oid, target_branch=f"clive/objective/{oid}")
    lines = w.dispatcher().tick()
    assert sum("assigned" in line for line in lines) == 2
    assert any("concurrent-worker limit" in line for line in lines)


def _pids(tmp: Path) -> list[int]:
    runtime = tmp / "runtime" / "attempts"
    out = []
    for f in runtime.glob("*.json"):
        pid = json.loads(f.read_text()).get("pid")
        if pid:
            try:
                os.kill(pid, 0)
                out.append(pid)
            except OSError:
                pass
    return out


def test_a_review_that_fails_every_run_blocks_with_the_reason_instead_of_waiting_for_ever(tmp_path, openai):
    openai.status = 401
    w = World(tmp_path)
    w.reviewers[:] = [gpt(tmp_path, w.repo, openai)]
    w.scenarios(EDIT_HELLO)
    w.objective()
    w.run_until(w.status_is(TaskStatus.BLOCKED), timeout=40)
    assert "could not be obtained" in w.state_of().blocker_reason and "HTTP 401" in w.state_of().blocker_reason
    assert len(openai.requests) == 3 and KEY not in w.state_of().blocker_reason


# ---------------------------------------------------------------- integration of divergent candidates

def _complete_one(w: World, oid: str, edits: list) -> str:
    w.scenarios({"edits": edits})
    w.objective(objective_id=oid, target_branch=f"clive/objective/{oid}")
    w.run_until(lambda: any(i.task_id == oid for i in w.store.read_integrations()))
    return next(i.accepted_sha for i in w.store.read_integrations() if i.task_id == oid)


def _integration(w: World, sources: tuple[str, ...]):
    from app.orchestrator.objectives import accepted_candidates, integration_scope
    shas = accepted_candidates(w.kernel, sources)
    return w.objective(objective_id="integration", target_branch="clive/integration/demo", builder="integrator",
                       integrates=shas, allowed_paths=integration_scope(w.kernel, w.base, shas),
                       max_repair_rounds=0), shas


def test_accepted_divergent_candidates_are_integrated_and_the_integrated_sha_is_reviewed_by_gpt(tmp_path, openai):
    w = World(tmp_path, max_concurrent=3)
    w.reviewers[:] = [gpt(tmp_path, w.repo, openai)]
    a = _complete_one(w, "obj-a", [["pkg/a.txt", "from a\n"]])
    b = _complete_one(w, "obj-b", [["pkg/b.txt", "from b\n"]])
    _, shas = _integration(w, ("obj-a", "obj-b"))
    assert shas == (a, b)
    w.run_until(lambda: any(i.task_id == "integration" for i in w.store.read_integrations()), timeout=30)

    integrated = next(i for i in w.store.read_integrations() if i.task_id == "integration")
    sha = integrated.accepted_sha
    assert _git(w.repo, "show", f"{sha}:pkg/a.txt") == "from a" and _git(w.repo, "show", f"{sha}:pkg/b.txt") == "from b"
    assert _git(w.repo, "rev-parse", "clive/integration/demo") == sha
    attempt = w.store.read_attempts("integration")[0]
    assert attempt.worker.principal.principal_id == "clive-integrator"
    # the integrated exact SHA went to GPT like any other candidate
    last = openai.requests[-1]["input"][0]["content"][0]["text"]
    assert f"CANDIDATE SHA: {sha}" in last and "TASK: integration r1" in last
    # neither source branch moved
    assert _git(w.repo, "rev-parse", "clive/objective/obj-a") == a
    assert _git(w.repo, "rev-parse", "clive/objective/obj-b") == b


def test_conflicting_candidates_block_the_integration_with_the_conflicting_paths(tmp_path, openai):
    w = World(tmp_path)
    w.reviewers[:] = [gpt(tmp_path, w.repo, openai)]
    _complete_one(w, "obj-a", [["pkg/hello.txt", "hello from a\n"]])
    _complete_one(w, "obj-b", [["pkg/hello.txt", "hello from b\n"]])
    _integration(w, ("obj-a", "obj-b"))
    w.run_until(lambda: w.store.read_task_state("integration", 1).status is TaskStatus.BLOCKED)
    assert "merge conflict in: pkg/hello.txt" in w.store.read_task_state("integration", 1).blocker_reason
    assert all("TASK: integration" not in r["input"][0]["content"][0]["text"] for r in openai.requests)
