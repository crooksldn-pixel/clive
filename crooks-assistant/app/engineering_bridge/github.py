"""A small client over the GitHub REST contents API, for the engineering loop's two branches.

  clive/control/status        status.json, published by the loop; read only
  clive/control/owner-inbox   requests/<request_id>.json; read, and created once when absent

It can do three things and nothing else: read the status, read the inbox (its head commit
and whether one request file is there), and create one request file as one new commit. The
create never overwrites — the contents API only replaces a file when it is handed the
existing blob's sha, and this client never sends one — and never forces. A conflict is
re-read and refused, never retried into place.

The token is read from the secret store at the moment of each call and held nowhere else:
not on the client, not in a result, not in a log line, not in an error. When it is not
stored, every call returns NotConnected and no request is made. Every result is a typed
value rather than an exception, so a caller cannot forget that GitHub may not answer.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.engineering_bridge.requests import request_path

log = logging.getLogger("crooks.engineering")

DEFAULT_REPOSITORY = "crooksldn-pixel/clive"
INBOX_BRANCH = "clive/control/owner-inbox"
STATUS_BRANCH = "clive/control/status"
STATUS_PATH = "status.json"
TOKEN_KEY = "github_engineering_inbox_token"
API_ROOT = "https://api.github.com"
TIMEOUT_S = 15.0
MAX_STATUS_BYTES = 2_000_000

NOT_CONNECTED = "GitHub is not connected for engineering: no inbox token is stored on this machine."

_REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
# What the owner is told about an HTTP status, in words. Never the body: GitHub's error
# bodies are not ours to repeat, and a proxy's might quote the request.
_HTTP_WORDS = {
    401: "the token was not accepted",
    403: "the token is not allowed to do this",
    404: "not found",
    409: "a conflict",
    422: "a conflict",
}


@dataclass(frozen=True, slots=True)
class NotConnected:
    """No token is stored. Nothing was attempted."""

    reason: str = NOT_CONNECTED


@dataclass(frozen=True, slots=True)
class Unavailable:
    """GitHub was asked and gave no usable answer. The reason names the step and the HTTP
    status or the kind of failure, and nothing else."""

    reason: str


@dataclass(frozen=True, slots=True)
class Status:
    """The loop's status.json, or found=False when it has not published one yet."""

    found: bool
    document: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class InboxHead:
    sha: str


@dataclass(frozen=True, slots=True)
class RequestFile:
    request_id: str
    exists: bool
    content: bytes = b""


@dataclass(frozen=True, slots=True)
class Created:
    request_id: str
    commit_sha: str


@dataclass(frozen=True, slots=True)
class Refused:
    """The file was not created: it is there already, or GitHub reported a conflict and a
    re-read was made. `exists` is what that re-read saw."""

    reason: str
    exists: bool


def stored_token() -> str | None:
    """The inbox token from the secret store, read now, or None."""
    from app.secrets import keychain

    try:
        return keychain.get_optional(TOKEN_KEY)
    except ValueError:
        # The store refuses a name it does not list (keychain.KNOWN_KEYS). Listing it and
        # storing the token is the owner's provisioning step; until then, not connected.
        return None


class GitHubInbox:
    """The engineering loop's inbox and status, on one repository."""

    def __init__(
        self,
        repository: str = DEFAULT_REPOSITORY,
        *,
        token: Callable[[], str | None] = stored_token,
        transport: httpx.AsyncBaseTransport | None = None,
        api_root: str = API_ROOT,
        timeout_s: float = TIMEOUT_S,
    ) -> None:
        if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository):
            raise ValueError("repository must be owner/name")
        self.repository = repository
        self.inbox_branch = INBOX_BRANCH
        self.status_branch = STATUS_BRANCH
        self._token_source = token
        self._transport = transport
        self._api_root = api_root
        self._timeout_s = timeout_s

    def __repr__(self) -> str:
        return f"GitHubInbox({self.repository!r})"

    # ------------------------------------------------------------------ the three reads

    async def read_status(self) -> Status | NotConnected | Unavailable:
        token = self._token()
        if token is None:
            return NotConnected()
        step = "read the engineering status"
        answer = await self._call("GET", self._contents(STATUS_PATH), token, step=step, raw=True, params={"ref": self.status_branch})
        if isinstance(answer, Unavailable):
            return answer
        if answer.status_code == 404:
            return Status(found=False)
        if answer.status_code != 200:
            return _unavailable(step, answer.status_code)
        if len(answer.content) > MAX_STATUS_BYTES:
            return Unavailable("The engineering status is too large to read.")
        try:
            document = json.loads(answer.content.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            return Unavailable("The engineering status is not valid JSON.")
        if not isinstance(document, dict):
            return Unavailable("The engineering status is not a JSON object.")
        return Status(found=True, document=document)

    async def inbox_head(self) -> InboxHead | NotConnected | Unavailable:
        token = self._token()
        if token is None:
            return NotConnected()
        step = "read the engineering inbox"
        answer = await self._call("GET", f"/repos/{self.repository}/git/ref/heads/{self.inbox_branch}", token, step=step)
        if isinstance(answer, Unavailable):
            return answer
        if answer.status_code == 404:
            return Unavailable("The engineering inbox branch does not exist on GitHub.")
        if answer.status_code != 200:
            return _unavailable(step, answer.status_code)
        target = _json(answer).get("object")
        sha = target.get("sha") if isinstance(target, dict) else None
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            return Unavailable("GitHub's answer for the engineering inbox had no commit in it.")
        return InboxHead(sha=sha)

    async def request_file(self, request_id: str) -> RequestFile | NotConnected | Unavailable:
        token = self._token()
        if token is None:
            return NotConnected()
        step = "read the engineering inbox"
        answer = await self._call("GET", self._contents(request_path(request_id)), token, step=step, raw=True, params={"ref": self.inbox_branch})
        if isinstance(answer, Unavailable):
            return answer
        if answer.status_code == 404:
            return RequestFile(request_id=request_id, exists=False)
        if answer.status_code != 200:
            return _unavailable(step, answer.status_code)
        return RequestFile(request_id=request_id, exists=True, content=answer.content)

    # ------------------------------------------------------------------ the one write

    async def create_request(self, request_id: str, content: bytes) -> Created | Refused | NotConnected | Unavailable:
        """Create requests/<request_id>.json as one new commit on the inbox branch, only if
        it is absent. Never overwrites, never forces; a conflict is re-read and refused."""
        token = self._token()
        if token is None:
            return NotConnected()
        path = request_path(request_id)
        existing = await self.request_file(request_id)
        if not isinstance(existing, RequestFile):
            return existing
        if existing.exists:
            return Refused("A request with this id is already in the engineering inbox; nothing was written.", exists=True)
        body = {
            "message": f"Engineering request {request_id}",
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self.inbox_branch,
            # No "sha", ever: without one the contents API can only create, never replace.
        }
        step = "file the engineering request"
        answer = await self._call("PUT", self._contents(path), token, step=step, body=body)
        if isinstance(answer, Unavailable):
            return answer
        if answer.status_code == 201:
            commit = _json(answer).get("commit")
            sha = commit.get("sha") if isinstance(commit, dict) else None
            return Created(request_id=request_id, commit_sha=sha if isinstance(sha, str) and _SHA.fullmatch(sha) else "")
        if answer.status_code in (409, 422):
            again = await self.request_file(request_id)
            there = isinstance(again, RequestFile) and again.exists
            return Refused(
                "GitHub reported a conflict, so nothing was written; "
                + ("a request with this id is now in the inbox." if there else "the request is not in the inbox."),
                exists=there,
            )
        return _unavailable(step, answer.status_code)

    # ------------------------------------------------------------------ plumbing

    def _token(self) -> str | None:
        try:
            value = self._token_source()
        except Exception as exc:  # noqa: BLE001 — a store that cannot be read is not connected
            log.warning("engineering inbox token could not be read (%s)", type(exc).__name__)
            return None
        value = value.strip() if isinstance(value, str) else ""
        return value or None

    def _contents(self, path: str) -> str:
        return f"/repos/{self.repository}/contents/{path}"

    async def _call(
        self, method: str, url: str, token: str, *, step: str, raw: bool = False,
        params: dict[str, str] | None = None, body: dict[str, Any] | None = None,
    ) -> httpx.Response | Unavailable:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.raw+json" if raw else "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "clive-engineering-bridge",
        }
        try:
            async with httpx.AsyncClient(base_url=self._api_root, transport=self._transport, timeout=self._timeout_s) as client:
                answer = await client.request(method, url, params=params, json=body, headers=headers)
        except httpx.HTTPError as exc:
            # Only the kind of failure: an exception's text and its request are not ours to
            # repeat, and the request carries the token in its headers.
            log.warning("engineering inbox: could not %s (%s)", step, type(exc).__name__)
            return Unavailable(f"GitHub could not be reached to {step} ({type(exc).__name__}).")
        if answer.status_code >= 400 and answer.status_code != 404:
            log.warning("engineering inbox: could not %s (HTTP %s)", step, answer.status_code)
        return answer


def _unavailable(step: str, code: int) -> Unavailable:
    words = _HTTP_WORDS.get(code)
    return Unavailable(f"Could not {step}: GitHub answered HTTP {code}" + (f" ({words})." if words else "."))


def _json(answer: httpx.Response) -> dict[str, Any]:
    try:
        value = answer.json()
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}
