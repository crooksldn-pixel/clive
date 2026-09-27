"""The GitHub acceptance gate: green only on a complete, all-success answer about the exact SHA.

No test here reaches GitHub. The pure evaluators are fed Actions answers (workflow runs, jobs) directly; the HTTP client
runs against ``httpx.MockTransport``; the credential source runs real ``git`` against a local
repository whose remote URL or credential helper holds a fake token assembled at runtime.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.orchestrator.github_acceptance import (
    ACCEPTANCE_CHECK,
    ACCEPTANCE_WORKFLOW,
    GATE_SCHEMA,
    GateResult,
    GateState,
    GitHubAcceptance,
    RunFact,
    evaluate,
    evaluate_jobs,
    git_remote_token,
)
from tests.fake_credentials import github_token

REPO = Path(__file__).resolve().parents[2]
SHA = "a" * 40
OTHER = "b" * 40
REPOSITORY = "crooksldn-pixel/clive"
# A fake GitHub token, assembled here so no literal in this file has a real token's shape.
FAKE_TOKEN = github_token("github-acceptance")


def run(run_id: int = 1, *, status: str = "completed", conclusion: str | None = "success", sha: str = SHA,
        path: str = ACCEPTANCE_WORKFLOW, event: str = "push") -> dict:
    """One workflow run as GitHub's Actions API lists it, with text a commit author chose."""
    return {"id": run_id, "name": "acceptance", "path": path, "head_sha": sha, "event": event,
            "status": status, "conclusion": conclusion, "run_attempt": 1,
            "display_title": "attacker-chosen text", "head_commit": {"message": "never published"},
            "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}"}


def answer(*runs: dict, total: int | None = None) -> dict:
    return {"total_count": len(runs) if total is None else total, "workflow_runs": list(runs)}


def job(run_id: int = 1, *, name: str = ACCEPTANCE_CHECK, status: str = "completed",
        conclusion: str | None = "success", sha: str = SHA) -> dict:
    return {"id": run_id * 100, "run_id": run_id, "name": name, "head_sha": sha, "status": status,
            "conclusion": conclusion, "steps": [{"name": "attacker-chosen step"}]}


def jobs(*listed: dict, total: int | None = None) -> dict:
    return {"total_count": len(listed) if total is None else total, "jobs": list(listed)}


# ---------------------------------------------------------------- the evaluator


def test_one_completed_successful_acceptance_run_is_green():
    result = evaluate(SHA, answer(run(11)))
    assert result.state is GateState.GREEN and result.green
    assert result.sha == SHA and [r.id for r in result.runs] == [11]


def test_every_run_for_the_sha_must_be_green_push_and_pull_request_alike():
    assert evaluate(SHA, answer(run(1), run(2))).state is GateState.GREEN


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "skipped", "neutral",
                                        "action_required", "stale", "startup_failure"])
def test_any_completed_conclusion_but_success_is_red(conclusion):
    result = evaluate(SHA, answer(run(5, conclusion=conclusion)))
    assert result.state is GateState.RED and not result.green
    assert conclusion in result.detail and "run 5" in result.detail


def test_a_red_duplicate_beside_a_green_run_is_red():
    result = evaluate(SHA, answer(run(1), run(2, conclusion="failure")))
    assert result.state is GateState.RED and "1 of 2" in result.detail


def test_a_completed_run_without_a_conclusion_is_red():
    assert evaluate(SHA, answer(run(3, conclusion=None))).state is GateState.RED


@pytest.mark.parametrize("status", ["queued", "in_progress", "waiting", "requested", "pending"])
def test_a_run_that_has_not_completed_is_pending_even_beside_a_green_one(status):
    result = evaluate(SHA, answer(run(1), run(2, status=status, conclusion=None)))
    assert result.state is GateState.PENDING and status in result.detail


def test_red_is_decided_even_while_another_run_is_still_pending():
    result = evaluate(SHA, answer(run(1, conclusion="failure"), run(2, status="in_progress", conclusion=None)))
    assert result.state is GateState.RED


def test_no_acceptance_run_is_missing():
    assert evaluate(SHA, answer()).state is GateState.MISSING


def test_a_run_of_another_workflow_listed_under_acceptance_is_not_decided_on():
    assert evaluate(SHA, answer(run(9, path=".github/workflows/other.yml"))).state is GateState.UNAVAILABLE
    assert evaluate(SHA, answer(run(1), run(9, path=None))).state is GateState.UNAVAILABLE


def test_the_same_run_listed_twice_is_not_decided_on():
    assert evaluate(SHA, answer(run(1), run(1))).state is GateState.UNAVAILABLE


# ---------------------------------------------------------------- the acceptance job of a successful run

RUN = RunFact(id=7, status="completed", conclusion="success")


def test_a_run_whose_acceptance_job_succeeded_on_the_sha_is_confirmed():
    assert evaluate_jobs(SHA, RUN, jobs(job(7)), (RUN,)) is None
    assert evaluate_jobs(SHA, RUN, jobs(job(7, name="setup"), job(7)), (RUN,)) is None   # other jobs are not it


@pytest.mark.parametrize(("listed", "why"), [
    ((), "without an acceptance job"),
    ((job(7, name="lint"),), "without an acceptance job"),
    ((job(7, conclusion="skipped"),), "its acceptance job did not"),
    ((job(7, conclusion="failure"),), "its acceptance job did not"),
    ((job(7, status="in_progress", conclusion=None),), "its acceptance job did not"),
    ((job(7), job(7, conclusion="cancelled")), "its acceptance job did not"),
], ids=["no-jobs", "no-acceptance-job", "skipped", "failed", "unfinished", "one-of-two-cancelled"])
def test_a_run_that_succeeded_without_its_acceptance_job_succeeding_is_red(listed, why):
    result = evaluate_jobs(SHA, RUN, jobs(*listed), (RUN,))
    assert result is not None and result.state is GateState.RED and why in result.detail and "run 7" in result.detail


@pytest.mark.parametrize("body", [
    None, {}, {"jobs": "x", "total_count": 0}, jobs(job(7), total=2), jobs("not a job"),
    jobs(job(7, sha=OTHER)), jobs({**job(7), "run_id": 8}),
], ids=["none", "empty", "jobs-not-list", "partial-list", "entry-not-dict", "another-commit", "another-run"])
def test_every_jobs_answer_the_gate_cannot_trust_is_unavailable(body):
    result = evaluate_jobs(SHA, RUN, body, (RUN,))
    assert result is not None and result.state is GateState.UNAVAILABLE


@pytest.mark.parametrize("body", [
    None, [], "ok", {}, {"workflow_runs": "x", "total_count": 0}, {"workflow_runs": [], "total_count": "0"},
    {"workflow_runs": [], "total_count": True}, answer(run(1), total=2), answer(run(1), total=0),
    answer("not a run"), answer({**run(1), "id": "1"}), answer({**run(1), "id": True}),
    answer({**run(1), "status": None}), answer(run(1, conclusion="Success! <script>")),
    answer(run(1, sha=OTHER)),
], ids=["none", "list", "text", "empty", "runs-not-list", "count-not-int", "count-bool", "partial-list",
        "overfull-list", "entry-not-dict", "id-text", "id-bool", "no-status", "unknown-conclusion",
        "another-commit"])
def test_every_answer_the_gate_cannot_trust_is_unavailable(body):
    result = evaluate(SHA, body)
    assert result.state is GateState.UNAVAILABLE and not result.green


def test_nothing_github_wrote_travels_in_a_result():
    result = evaluate(SHA, answer(run(1, conclusion="failure")))
    record = json.dumps(result.record(checked_at=datetime(2026, 9, 26, tzinfo=UTC)))
    assert "attacker-chosen" not in record and "never published" not in record and "https://" not in record


def test_a_record_round_trips_and_a_forged_one_is_refused():
    checked = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)
    result = evaluate(SHA, answer(run(1), run(2)))
    record = result.record(checked_at=checked)
    assert record["schema"] == GATE_SCHEMA and record["sha"] == SHA and record["green"] is True
    assert GateResult.from_record(record) == result
    assert GateResult.from_record({**record, "state": "red"}) is None       # green flag disagrees
    assert GateResult.from_record({**record, "schema": "other"}) is None
    assert GateResult.from_record({**record, "sha": "HEAD"}) is None
    assert GateResult.from_record("green") is None


def test_the_gate_asks_about_the_workflow_and_job_that_really_exist():
    """The gate is coupled to .github/workflows/acceptance.yml: one job, no matrix and no display name, so the
    job is named exactly ``acceptance``; and every pushed branch runs it, candidate branches included."""
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((REPO / ACCEPTANCE_WORKFLOW).read_text(encoding="utf-8"))
    job = workflow["jobs"][ACCEPTANCE_CHECK]
    assert job.get("name", ACCEPTANCE_CHECK) == ACCEPTANCE_CHECK and "strategy" not in job
    triggers = workflow.get("on", workflow.get(True))        # YAML 1.1 reads a bare `on:` key as true
    assert triggers["push"]["branches"] == ["**"]


# ---------------------------------------------------------------- the HTTP client


def client(handler, token: str | None = None) -> GitHubAcceptance:
    return GitHubAcceptance(lambda _repository: token, transport=httpx.MockTransport(handler))


RUNS_PATH = f"/repos/{REPOSITORY}/actions/workflows/acceptance.yml/runs"


def github(runs_body: dict, jobs_by_run: dict[int, dict] | None = None, seen: list | None = None):
    """A handler answering the two Actions requests the gate makes, and nothing else."""
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == RUNS_PATH:
            return httpx.Response(200, json=runs_body)
        prefix = f"/repos/{REPOSITORY}/actions/runs/"
        if request.url.path.startswith(prefix) and request.url.path.endswith("/jobs"):
            run_id = int(request.url.path[len(prefix):-len("/jobs")])
            listed = (jobs_by_run or {}).get(run_id, jobs(job(run_id)))
            return httpx.Response(200, json=listed)
        return httpx.Response(404)
    return handler


def test_it_asks_for_exactly_the_acceptance_runs_of_exactly_the_sha_then_each_runs_job():
    seen: list[httpx.Request] = []
    result = client(github(answer(run(21), run(22, event="pull_request")), seen=seen)).check(REPOSITORY, SHA)
    assert result.green and [r.id for r in result.runs] == [21, 22]
    runs, first, second = seen
    assert all(r.method == "GET" and r.url.host == "api.github.com" for r in seen)
    assert runs.url.path == RUNS_PATH
    # Only the SHA and a page size: nothing that filters by event or names pull requests (re-pin F-01).
    assert dict(runs.url.params) == {"head_sha": SHA, "per_page": "100"}
    assert first.url.path == f"/repos/{REPOSITORY}/actions/runs/21/jobs"
    assert second.url.path == f"/repos/{REPOSITORY}/actions/runs/22/jobs"
    assert dict(first.url.params) == {"filter": "latest", "per_page": "100"}
    assert "authorization" not in runs.headers


def faithful_github(listed: list[dict], seen: list | None = None):
    """GitHub's workflow-runs endpoint as documented: `event` filters runs by what triggered them;
    `exclude_pull_requests` empties each run's `pull_requests` array and drops no run. Every run's
    acceptance job is green, so only the run list can decide."""
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == RUNS_PATH:
            params = request.url.params
            runs = [dict(r, pull_requests=[{"number": 7}] if r["event"] == "pull_request" else []) for r in listed]
            if params.get("head_sha"):
                runs = [r for r in runs if r["head_sha"] == params["head_sha"]]
            if params.get("event"):
                runs = [r for r in runs if r["event"] == params["event"]]
            if params.get("exclude_pull_requests") == "true":
                runs = [dict(r, pull_requests=[]) for r in runs]
            return httpx.Response(200, json=answer(*runs))
        prefix = f"/repos/{REPOSITORY}/actions/runs/"
        if request.url.path.startswith(prefix) and request.url.path.endswith("/jobs"):
            return httpx.Response(200, json=jobs(job(int(request.url.path[len(prefix):-len("/jobs")]))))
        return httpx.Response(404)
    return handler


@pytest.mark.parametrize(("pr_status", "pr_conclusion", "state"), [
    ("in_progress", None, GateState.PENDING),
    ("queued", None, GateState.PENDING),
    ("completed", "failure", GateState.RED),
    ("completed", "cancelled", GateState.RED),
])
def test_a_green_push_run_never_hides_a_pull_request_run_that_is_not_green(pr_status, pr_conclusion, state):
    """The re-pin review's F-01, at the client: a green push run and a pending or failed pull-request
    run for the same SHA is not green, against a GitHub that filters exactly as its parameters say."""
    seen: list[httpx.Request] = []
    listed = [run(31, event="push"),
              run(32, event="pull_request", status=pr_status, conclusion=pr_conclusion),
              run(33, event="push", sha=OTHER)]
    result = client(faithful_github(listed, seen)).check(REPOSITORY, SHA)
    assert result.state is state and [r.id for r in result.runs] == [31, 32]
    assert "32" in result.detail
    (runs_request,) = [r for r in seen if r.url.path == RUNS_PATH]
    assert "event" not in runs_request.url.params and "exclude_pull_requests" not in runs_request.url.params
    # Both green: green, and each run's job was confirmed.
    both = [run(31, event="push"), run(32, event="pull_request")]
    seen.clear()
    assert client(faithful_github(both, seen)).check(REPOSITORY, SHA).green
    assert sorted(r.url.path for r in seen if r.url.path.endswith("/jobs")) == [
        f"/repos/{REPOSITORY}/actions/runs/31/jobs", f"/repos/{REPOSITORY}/actions/runs/32/jobs"]


def test_a_run_that_is_not_green_is_answered_without_asking_for_its_jobs():
    seen: list[httpx.Request] = []
    assert client(github(answer(run(1, conclusion="failure")), seen=seen)).check(REPOSITORY, SHA).state is GateState.RED
    assert client(github(answer(), seen=seen)).check(REPOSITORY, SHA).state is GateState.MISSING
    assert [r.url.path for r in seen] == [RUNS_PATH, RUNS_PATH]


def test_a_successful_run_whose_job_was_skipped_is_red_through_the_client():
    result = client(github(answer(run(3)), {3: jobs(job(3, conclusion="skipped"))})).check(REPOSITORY, SHA)
    assert result.state is GateState.RED and "run 3" in result.detail


def test_the_remote_credential_is_sent_only_as_a_bearer_header():
    seen: list[httpx.Request] = []

    assert client(github(answer(run(1)), seen=seen), token=FAKE_TOKEN).check(REPOSITORY, SHA).green
    assert len(seen) == 2
    assert all(r.headers["authorization"] == f"Bearer {FAKE_TOKEN}" for r in seen)
    assert all(FAKE_TOKEN not in str(r.url) for r in seen)


@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 422, 429, 500, 502])
def test_any_answer_but_200_is_unavailable_and_carries_only_the_status(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"location": "https://evil.invalid/"},
                              text=f"echo {FAKE_TOKEN} {request.url}")

    result = client(handler, token=FAKE_TOKEN).check(REPOSITORY, SHA)
    assert result.state is GateState.UNAVAILABLE and f"HTTP {status}" in result.detail
    assert FAKE_TOKEN not in result.detail and "http" not in result.detail.replace("HTTP", "")



@pytest.mark.parametrize("status", [403, 404, 500])
def test_a_refused_jobs_request_is_unavailable_never_green(status):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == RUNS_PATH:
            return httpx.Response(200, json=answer(run(1)))
        return httpx.Response(status, text=f"echo {FAKE_TOKEN}")

    result = client(handler, token=FAKE_TOKEN).check(REPOSITORY, SHA)
    assert result.state is GateState.UNAVAILABLE and f"HTTP {status}" in result.detail and "jobs" in result.detail
    assert FAKE_TOKEN not in result.detail


def test_a_refusal_names_the_permission_a_fine_grained_token_needs():
    result = client(lambda request: httpx.Response(403)).check(REPOSITORY, SHA)
    assert "Actions: read" in result.detail

def test_a_transport_failure_is_unavailable_by_type_name_only():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"cannot reach {request.url} with {FAKE_TOKEN}")

    result = client(handler, token=FAKE_TOKEN).check(REPOSITORY, SHA)
    assert result.state is GateState.UNAVAILABLE and "ConnectError" in result.detail
    assert FAKE_TOKEN not in result.detail and "api.github.com" not in result.detail


def test_an_answer_that_is_not_json_is_unavailable():
    result = client(lambda request: httpx.Response(200, text="<html>")).check(REPOSITORY, SHA)
    assert result.state is GateState.UNAVAILABLE


def test_a_credential_source_that_fails_means_asking_without_one():
    def broken(_repository: str) -> str:
        raise RuntimeError(FAKE_TOKEN)

    seen: list[httpx.Request] = []
    gate = GitHubAcceptance(broken, transport=httpx.MockTransport(github(answer(run(1)), seen=seen)))
    assert gate.check(REPOSITORY, SHA).green and all("authorization" not in r.headers for r in seen)


@pytest.mark.parametrize(("repository", "sha"), [
    (REPOSITORY, "HEAD"), (REPOSITORY, SHA.upper()), (REPOSITORY, SHA[:12]), ("../etc", SHA),
    ("owner/repo/extra", SHA), ("owner", SHA), ("owner/..", SHA),
])
def test_a_malformed_sha_or_repository_is_refused_before_any_request(repository, sha):
    gate = client(lambda request: pytest.fail("no request may be made"))
    assert gate.check(repository, sha).state is GateState.UNAVAILABLE
    assert gate.requests_made == 0


# ---------------------------------------------------------------- the credential git already holds


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def isolated_git(monkeypatch, tmp_path):
    """No host git configuration, helper or askpass program can answer for these tests."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("GIT_ASKPASS", "/bin/false")
    monkeypatch.setenv("SSH_ASKPASS", "/bin/false")
    repo = tmp_path / "dispatcher-clone"
    repo.mkdir()
    _git(repo, "init", "-q")
    return repo


def test_the_token_git_holds_in_the_remote_url_is_reused_for_that_repository_only(isolated_git):
    _git(isolated_git, "remote", "add", "origin", f"https://x-access-token:{FAKE_TOKEN}@github.com/{REPOSITORY}.git")
    source = git_remote_token(isolated_git, "origin")
    assert source(REPOSITORY) == FAKE_TOKEN
    assert source(REPOSITORY.upper()) == FAKE_TOKEN          # GitHub names are case-insensitive
    assert source("crooksldn-pixel/other") is None            # never sent about another repository


def test_the_token_a_configured_credential_helper_holds_is_reused(isolated_git):
    _git(isolated_git, "remote", "add", "origin", f"https://github.com/{REPOSITORY}")
    _git(isolated_git, "config", "credential.helper",
         f"!f() {{ echo username=x-access-token; echo password={FAKE_TOKEN}; }}; f")
    assert git_remote_token(isolated_git, "origin")(REPOSITORY) == FAKE_TOKEN


def test_without_a_credential_git_is_never_left_prompting(isolated_git):
    _git(isolated_git, "remote", "add", "origin", f"https://github.com/{REPOSITORY}.git")
    assert git_remote_token(isolated_git, "origin", timeout_s=10)(REPOSITORY) is None


@pytest.mark.parametrize("url", [
    f"git@github.com:{REPOSITORY}.git",
    f"ssh://git@github.com/{REPOSITORY}.git",
    f"http://x:{FAKE_TOKEN}@github.com/{REPOSITORY}.git",
    f"https://x:{FAKE_TOKEN}@github.example.invalid/{REPOSITORY}.git",
    f"https://x:{FAKE_TOKEN}@github.com:8443/{REPOSITORY}.git",
    f"https://x:{FAKE_TOKEN}@github.com/{REPOSITORY}/extra.git",
], ids=["scp-ssh", "ssh", "plain-http", "another-host", "another-port", "another-path"])
def test_a_remote_that_is_not_https_github_for_the_repository_yields_no_token(isolated_git, url):
    _git(isolated_git, "remote", "add", "origin", url)
    assert git_remote_token(isolated_git, "origin")(REPOSITORY) is None


@pytest.mark.parametrize("remote", ["--upload-pack=touch pwned", "https://github.com/o/r", "", "a b"])
def test_a_remote_name_that_is_not_a_plain_name_never_reaches_git(isolated_git, remote):
    assert git_remote_token(isolated_git, remote)(REPOSITORY) is None
    assert not (isolated_git / "pwned").exists()


def test_an_unknown_remote_yields_no_token(isolated_git):
    assert git_remote_token(isolated_git, "nowhere")(REPOSITORY) is None
