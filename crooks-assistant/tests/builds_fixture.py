"""The real engineering loop, as it stood on 2 Oct 2026, behind GitHub's REST shape, for the Builds tests.

tests/fixtures/builds/ holds three files, copied from the repository without redaction (nothing in
them is secret; they were checked for credential and customer shapes when copied):

- worker-01-status.json: clive/control/worker-01-status:status.json exactly as the worker-01 loop
  published it (commit and time in worker-01-git.json);
- worker-01-requests.json: every requests/<id>.json on clive/control/worker-01-inbox, byte for
  byte, each hashing to the request_sha256 the status names for it;
- worker-01-git.json: for every candidate and landed commit the status names, whether it is on
  clive/trunk (d74c99c3 when copied) and in the commit production runs (66d3e05d, the deploy record
  reports/deploy-66d3e05d.md on claude/deploy-66d3e05d-record), as `git merge-base --is-ancestor`
  answered.

`FakeLoop` answers exactly the calls app/engineering_bridge/github.py makes: the status file, a
request file, a branch head, and a compare of a commit with the trunk or the running commit.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import httpx

from app.engineering_bridge.github import EngineeringInbox
from tests.fake_credentials import github_token

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "builds"
REPO = "crooksldn-pixel/clive"
HOST = "worker-01"
INBOX = "clive/control/worker-01-inbox"
STATUS = "clive/control/worker-01-status"
TRUNK = "clive/trunk"


def status() -> dict:
    return json.loads((FIXTURES / "worker-01-status.json").read_text(encoding="utf-8"))


def request_files() -> dict[str, str]:
    return json.loads((FIXTURES / "worker-01-requests.json").read_text(encoding="utf-8"))["files"]


def git() -> dict:
    return json.loads((FIXTURES / "worker-01-git.json").read_text(encoding="utf-8"))


class FakeLoop:
    """The worker-01 loop's branches and the trunk, as the fixtures hold them."""

    def __init__(self) -> None:
        self.status = status()
        self.files = request_files()
        self.git = git()
        self.calls: list[str] = []
        self.down = False

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path[len(f"/repos/{REPO}"):]
        self.calls.append(path)
        if self.down:
            return httpx.Response(503, json={"message": "unavailable"})
        ref = request.url.params.get("ref")
        if path.startswith("/git/ref/heads/"):
            branch = path[len("/git/ref/heads/"):]
            heads = {INBOX: self.git["inbox_commit"], STATUS: self.git["status_commit"], TRUNK: self.git["trunk"]}
            return httpx.Response(200, json={"object": {"sha": heads[branch]}}) if branch in heads else \
                httpx.Response(404, json={"message": "Not Found"})
        if path == "/contents/status.json" and ref == STATUS:
            return self._file(json.dumps(self.status).encode("utf-8"))
        if path.startswith("/contents/requests/") and ref == INBOX:
            rid = path[len("/contents/requests/"):-len(".json")]
            return self._file(self.files[rid].encode("utf-8")) if rid in self.files else \
                httpx.Response(404, json={"message": "Not Found"})
        if path.startswith("/compare/"):
            sha, _, against = path[len("/compare/"):].partition("...")
            fact = self.git["commits"].get(sha)
            if fact is None:
                return httpx.Response(404, json={"message": "Not Found"})
            on = fact["trunk"] if against == TRUNK else fact["running"] if against == self.git["running"] else None
            if on is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(200, json={"status": "ahead" if on else "diverged"})
        return httpx.Response(404, json={"message": "Not Found"})

    @staticmethod
    def _file(content: bytes) -> httpx.Response:
        return httpx.Response(200, json={"type": "file", "encoding": "base64",
                                         "content": base64.encodebytes(content).decode("ascii")})

    def inbox(self) -> EngineeringInbox:
        return EngineeringInbox(REPO, token_source=lambda: github_token("builds-screen"), transport=self.transport(),
                                host=HOST)


def bind(monkeypatch, loop: FakeLoop, *, running: str | None = None) -> None:
    """The engineering tools read `loop`, and CLIVE runs the commit production ran on 2 Oct."""
    from app.builds import read
    from app.tools import engineering_tools

    monkeypatch.setattr(engineering_tools, "_inbox", loop.inbox())
    monkeypatch.setattr(engineering_tools, "_progress_cache", {})
    monkeypatch.setattr(engineering_tools, "running_sha", lambda root=None: loop.git["running"] if running is None else running)
    read.reset()
