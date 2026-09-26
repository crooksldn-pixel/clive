"""The GitHub acceptance gate: green only on a complete, all-success answer about the exact SHA.

No test here reaches GitHub. The pure evaluator is fed check-runs answers directly; the HTTP client
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
    GATE_SCHEMA,
    GateResult,
    GateState,
    GitHubAcceptance,
    evaluate,
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
        name: str = "acceptance", app: str | None = "github-actions") -> dict:
    return {"id": run_id, "name": name, "head_sha": sha, "status": status, "conclusion": conclusion,
            "app": {"slug": app} if app is not None else None,
            "output": {"title": "attacker-chosen text", "summary": "never published"},
            "html_url": f"https://github.com/{REPOSITORY}/actions/runs/{run_id}"}


def answer(*runs: dict, total: int | None = None) -> dict:
    return {"total_count": len(runs) if total is None else total, "check_runs": list(runs)}


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


def test_a_run_from_another_app_can_neither_make_a_commit_green_nor_stand_in_for_the_workflow():
    assert evaluate(SHA, answer(run(9, app="some-other-app"))).state is GateState.MISSING
    assert evaluate(SHA, answer(run(9, app=None))).state is GateState.MISSING
    # ... and cannot turn the workflow's green red either: it is simply not the workflow.
    assert evaluate(SHA, answer(run(1), run(9, app="some-other-app", conclusion="failure"))).green


def test_a_check_of_another_name_is_not_the_acceptance_job():
    assert evaluate(SHA, answer(run(1, name="lint"))).state is GateState.MISSING


@pytest.mark.parametrize("body", [
    None, [], "ok", {}, {"check_runs": "x", "total_count": 0}, {"check_runs": [], "total_count": "0"},
    {"check_runs": [], "total_count": True}, answer(run(1), total=2), answer(run(1), total=0),
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


def test_the_gate_asks_for_the_check_run_the_acceptance_workflow_really_creates():
    """The gate is coupled to .github/workflows/acceptance.yml: one job, no matrix and no display name, so its
    check run is named exactly ``acceptance``; and every pushed branch runs it, candidate branches included."""
    yaml = pytest.importorskip("yaml")
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "acceptance.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"][ACCEPTANCE_CHECK]
    assert job.get("name", ACCEPTANCE_CHECK) == ACCEPTANCE_CHECK and "strategy" not in job
    triggers = workflow.get("on", workflow.get(True))        # YAML 1.1 reads a bare `on:` key as true
    assert triggers["push"]["branches"] == ["**"]


# ---------------------------------------------------------------- the HTTP client


def client(handler, token: str | None = None) -> GitHubAcceptance:
    return GitHubAcceptance(lambda _repository: token, transport=httpx.MockTransport(handler))


def test_it_asks_for_exactly_the_acceptance_runs_of_exactly_the_sha():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=answer(run(21)))

    result = client(handler).check(REPOSITORY, SHA)
    assert result.green
    [request] = seen
    assert request.method == "GET"
    assert request.url.host == "api.github.com"
    assert request.url.path == f"/repos/{REPOSITORY}/commits/{SHA}/check-runs"
    assert dict(request.url.params) == {"check_name": "acceptance", "filter": "latest", "per_page": "100"}
    assert "authorization" not in request.headers


def test_the_remote_credential_is_sent_only_as_a_bearer_header():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=answer(run(1)))

    assert client(handler, token=FAKE_TOKEN).check(REPOSITORY, SHA).green
    assert seen[0].headers["authorization"] == f"Bearer {FAKE_TOKEN}"
    assert FAKE_TOKEN not in str(seen[0].url)


@pytest.mark.parametrize("status", [301, 302, 401, 403, 404, 422, 429, 500, 502])
def test_any_answer_but_200_is_unavailable_and_carries_only_the_status(status):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, headers={"location": "https://evil.invalid/"},
                              text=f"echo {FAKE_TOKEN} {request.url}")

    result = client(handler, token=FAKE_TOKEN).check(REPOSITORY, SHA)
    assert result.state is GateState.UNAVAILABLE and f"HTTP {status}" in result.detail
    assert FAKE_TOKEN not in result.detail and "http" not in result.detail.replace("HTTP", "")


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
    gate = GitHubAcceptance(broken, transport=httpx.MockTransport(
        lambda request: seen.append(request) or httpx.Response(200, json=answer(run(1)))))
    assert gate.check(REPOSITORY, SHA).green and "authorization" not in seen[0].headers


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
