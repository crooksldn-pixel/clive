"""The GitHub acceptance gate: is the ``acceptance`` check green on this exact commit?

The owner's loop update (OWNER_DECISIONS_2026-09-25.md, "Loop update"): an objective counts as
accepted, and a landing may happen, only after a green GitHub acceptance run on that exact SHA.
The run is ``.github/workflows/acceptance.yml``, whose one job, ``acceptance``, checks out the
exact commit it was triggered for and refuses to produce evidence for any other. GitHub attaches
the job's check run to that commit, so the question asked here is about one SHA and nothing else:

    GET /repos/{repository}/commits/{sha}/check-runs?check_name=acceptance&filter=latest

Green means, and only means: at least one ``acceptance`` run created by GitHub Actions exists for
the SHA, every one of them has completed, and every one concluded ``success``. Everything else
fails closed and is named:

    missing       no acceptance run exists for the SHA (yet)
    pending       a run exists and has not completed
    red           a completed run concluded anything but success (failure, cancelled,
                  timed_out, skipped, neutral, ...), even beside a green duplicate
    unavailable   GitHub could not be asked, refused, or answered something this gate will
                  not decide on (an unexpected shape, a run for another commit, a partial list)

``filter=latest`` is GitHub's own default: a re-run replaces the earlier run of its check suite,
so a flaky failure that was re-run green is judged by the re-run. A commit pushed to a branch and
also opened as a pull request carries one run per event; both must be green. A run created by
anything other than GitHub Actions is not the workflow and is ignored, so a check run posted by
another app can neither make a commit green nor stand in for the workflow.

The credential is the one git already uses for the loop's remote (``git_remote_token``); no new
credential exists. It is read at the moment of each request, held in a local for that request,
and never logged, stored or put into an error. Nothing this module reports carries GitHub's own
text or a URL: every ``detail`` is a sentence built here from counts, run ids, an HTTP status or an
exception's type name, because it reaches kernel blocker reasons and the public status projection.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

__all__ = [
    "ACCEPTANCE_CHECK",
    "ACTIONS_APP",
    "GATE_SCHEMA",
    "AcceptanceChecks",
    "GateResult",
    "GateState",
    "GitHubAcceptance",
    "RunFact",
    "evaluate",
    "git_remote_token",
    "unavailable",
]

ACCEPTANCE_CHECK = "acceptance"      # the job name in .github/workflows/acceptance.yml
ACTIONS_APP = "github-actions"       # the app that creates a workflow job's check run
GATE_SCHEMA = "clive.github_acceptance_gate.v1"
API_URL = "https://api.github.com"
TIMEOUT_S = 15.0
MAX_RUNS = 100                       # one page; a longer list is refused, never guessed at

_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_WORD = re.compile(r"^[a-z_]{1,40}$")
_REMOTE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class GateState(StrEnum):
    GREEN = "green"
    PENDING = "pending"
    MISSING = "missing"
    RED = "red"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class RunFact:
    """One acceptance check run, reduced to what may be published: GitHub's id and two enum words."""

    id: int
    status: str
    conclusion: str | None

    def record(self) -> dict:
        return {"id": self.id, "status": self.status, "conclusion": self.conclusion}


@dataclass(frozen=True)
class GateResult:
    sha: str
    state: GateState
    detail: str
    runs: tuple[RunFact, ...] = ()

    @property
    def green(self) -> bool:
        return self.state is GateState.GREEN

    def record(self, *, checked_at: datetime) -> dict:
        """The JSON form kept in the runtime notes, the evidence file and the status projection."""
        return {
            "schema": GATE_SCHEMA,
            "check": ACCEPTANCE_CHECK,
            "sha": self.sha,
            "state": self.state.value,
            "green": self.green,
            "detail": self.detail,
            "runs": [run.record() for run in self.runs],
            "checked_at": checked_at.isoformat(),
        }

    @classmethod
    def from_record(cls, record: object) -> GateResult | None:
        """A result read back from a record this module wrote; None for anything else."""
        if not isinstance(record, dict) or record.get("schema") != GATE_SCHEMA:
            return None
        try:
            state = GateState(record["state"])
            sha = record["sha"]
            detail = record["detail"]
            runs = tuple(
                RunFact(id=int(r["id"]), status=str(r["status"]), conclusion=r.get("conclusion"))
                for r in record.get("runs", [])
            )
        except (KeyError, TypeError, ValueError):
            return None
        if not isinstance(sha, str) or not _SHA.fullmatch(sha) or not isinstance(detail, str):
            return None
        if record.get("green") is not (state is GateState.GREEN):
            return None
        return cls(sha=sha, state=state, detail=detail, runs=runs)


class AcceptanceChecks(Protocol):
    """What the dispatcher asks. Test doubles implement this; ``GitHubAcceptance`` is the real one."""

    def check(self, repository: str, sha: str) -> GateResult: ...


def unavailable(sha: str, detail: str) -> GateResult:
    return GateResult(sha=sha, state=GateState.UNAVAILABLE, detail=detail)


def _word(value: object) -> str | None:
    return value if isinstance(value, str) and _WORD.fullmatch(value) else None


def _ids(runs: list[RunFact]) -> str:
    return ", ".join(str(run.id) for run in runs)


def evaluate(sha: str, body: object) -> GateResult:
    """Decide one SHA from GitHub's check-runs answer. Pure; every doubt is a refusal."""
    if not isinstance(body, dict) or not isinstance(body.get("check_runs"), list):
        return unavailable(sha, "GitHub's check-runs answer was not in the expected shape")
    listed = body["check_runs"]
    total = body.get("total_count")
    if not isinstance(total, int) or isinstance(total, bool) or total != len(listed):
        return unavailable(
            sha, "GitHub's check-runs answer did not list every run it counted; a partial list is not decided on"
        )
    runs: list[RunFact] = []
    for raw in listed:
        if not isinstance(raw, dict):
            return unavailable(sha, "GitHub's check-runs answer held an entry that is not a check run")
        app = raw.get("app")
        if raw.get("name") != ACCEPTANCE_CHECK or not isinstance(app, dict) or app.get("slug") != ACTIONS_APP:
            continue  # not the workflow's job: it can neither make the commit green nor stand in for it
        if raw.get("head_sha") != sha:
            return unavailable(sha, "GitHub listed an acceptance run for another commit under this SHA")
        run_id, status = raw.get("id"), _word(raw.get("status"))
        if not isinstance(run_id, int) or isinstance(run_id, bool) or status is None:
            return unavailable(sha, "GitHub listed an acceptance run without an id or a status")
        conclusion = raw.get("conclusion")
        if conclusion is not None and _word(conclusion) is None:
            return unavailable(sha, f"acceptance run {run_id} carries a conclusion this gate does not recognise")
        runs.append(RunFact(id=run_id, status=status, conclusion=conclusion))
    runs.sort(key=lambda run: run.id)
    facts = tuple(runs)
    if not runs:
        return GateResult(sha, GateState.MISSING, "no GitHub Actions acceptance run exists for this commit", facts)
    done = [run for run in runs if run.status == "completed"]
    failed = [run for run in done if run.conclusion != "success"]
    if failed:
        how = ", ".join(f"run {run.id} {run.conclusion or 'without a conclusion'}" for run in failed)
        return GateResult(sha, GateState.RED, f"{len(failed)} of {len(runs)} acceptance run(s) not successful: {how}",
                          facts)
    open_ = [run for run in runs if run.status != "completed"]
    if open_:
        how = ", ".join(f"run {run.id} {run.status}" for run in open_)
        return GateResult(sha, GateState.PENDING, f"{len(open_)} of {len(runs)} acceptance run(s) not completed: {how}",
                          facts)
    return GateResult(sha, GateState.GREEN, f"acceptance run(s) {_ids(runs)} completed with success", facts)


class GitHubAcceptance:
    """The real gate: GitHub's check-runs API for one repository and one exact SHA per call."""

    def __init__(
        self,
        token_source: Callable[[str], str | None] = lambda _repository: None,
        *,
        transport: httpx.BaseTransport | None = None,
        api_url: str = API_URL,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        self._token_source = token_source
        self._transport = transport
        self._api_url = api_url
        self._timeout_s = timeout_s
        self.requests_made = 0

    def check(self, repository: str, sha: str) -> GateResult:
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            return unavailable(str(sha)[:40], "the SHA asked about is not an exact commit id")
        if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository) or ".." in repository:
            return unavailable(sha, "the repository asked about is not owner/name")
        try:
            body = self._fetch(repository, sha)
        except _Unavailable as exc:
            return unavailable(sha, str(exc))
        except Exception as exc:  # noqa: BLE001 -- any surprise fails closed, by type name only
            return unavailable(sha, f"the check-runs request failed ({type(exc).__name__})")
        return evaluate(sha, body)

    def _token(self, repository: str) -> str | None:
        try:
            token = self._token_source(repository)
        except Exception:  # noqa: BLE001 -- a credential that cannot be read is no credential
            return None
        return token if isinstance(token, str) and token.strip() else None

    def _fetch(self, repository: str, sha: str) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "clive-engineering-dispatcher",
        }
        token = self._token(repository)
        if token is not None:
            headers["Authorization"] = f"Bearer {token.strip()}"
        del token
        params = {"check_name": ACCEPTANCE_CHECK, "filter": "latest", "per_page": str(MAX_RUNS)}
        self.requests_made += 1
        try:
            with httpx.Client(base_url=self._api_url, transport=self._transport, timeout=self._timeout_s,
                              follow_redirects=False) as client:
                response = client.get(f"/repos/{repository}/commits/{sha}/check-runs", params=params,
                                      headers=headers)
        except httpx.HTTPError as exc:
            # The exception's own text can carry the URL; only its kind travels.
            raise _Unavailable(f"GitHub could not be reached ({type(exc).__name__})") from None
        if response.status_code in (401, 403):
            raise _Unavailable(
                f"GitHub refused the check-runs request (HTTP {response.status_code}): the credential git uses "
                "for the remote cannot read checks, or the rate limit is exhausted"
            )
        if response.status_code != 200:
            raise _Unavailable(f"GitHub could not list the commit's check runs (HTTP {response.status_code})")
        try:
            return response.json()
        except ValueError:
            raise _Unavailable("GitHub's check-runs answer was not JSON") from None


class _Unavailable(RuntimeError):
    """Fixed text only: what failed and an HTTP status or exception type, never a URL, header or body."""


# --------------------------------------------------------------------------- the credential


def _github_repository_of(url: str) -> str | None:
    """``owner/name`` when ``url`` is an https URL of a repository on github.com, else None."""
    try:
        parts = urlsplit(url)
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme != "https" or host != "github.com" or parts.port not in (None, 443):
        return None
    path = parts.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path if _REPOSITORY.fullmatch(path) else None


def git_remote_token(repo: Path, remote: str, *, timeout_s: int = 15) -> Callable[[str], str | None]:
    """The credential git itself uses for ``remote``, as a token source for ``GitHubAcceptance``.

    This is the loop's existing way of talking to GitHub, reused: the dispatcher already pushes
    candidates, and the remote loop already fetches its inbox and pushes its status, with whatever
    git holds for that remote (a credential helper, or a token in the remote URL). Nothing new is
    provisioned. ``git credential fill`` is asked with prompts and askpass programs switched off,
    so it answers from what is configured or not at all; its output is never logged. The token is
    offered only when the remote is an https URL of exactly the repository being asked about on
    github.com; for any other remote (ssh, another host, another repository) the gate asks GitHub
    without a credential, which reads a public repository and fails closed on a private one.
    """
    repo = Path(repo)
    if not isinstance(remote, str) or not _REMOTE.fullmatch(remote):
        return lambda _repository: None  # an operator's mistyped remote is never handed to git

    def token(repository: str) -> str | None:
        env = {k: v for k, v in os.environ.items() if k not in ("GIT_ASKPASS", "SSH_ASKPASS")}
        env.update(GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
        try:
            url = subprocess.run(["git", "remote", "get-url", "--", remote], cwd=str(repo), env=env,
                                 capture_output=True, text=True, timeout=timeout_s, check=False)
            if url.returncode != 0:
                return None
            target = url.stdout.strip()
            named = _github_repository_of(target)
            if named is None or named.lower() != str(repository).lower():
                return None
            filled = subprocess.run(["git", "-c", "core.askPass=", "credential", "fill"], cwd=str(repo), env=env,
                                    input=f"url={target}\n\n", capture_output=True, text=True,
                                    timeout=timeout_s, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        if filled.returncode != 0:
            return None
        fields = dict(line.split("=", 1) for line in filled.stdout.splitlines() if "=" in line)
        if fields.get("host", "").lower() != "github.com":
            return None
        secret = fields.get("password", "").strip()
        return secret or None

    return token
