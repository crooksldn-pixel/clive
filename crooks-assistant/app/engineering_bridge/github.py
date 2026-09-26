"""A small client over GitHub's REST contents API, for the engineering loop's two branches.

    read    clive/control/status : status.json      what the loop publishes
            clive/control/owner-inbox               its head commit, and whether
                                                    requests/<id>.json exists there
    write   requests/<id>.json on the inbox         one new commit, only when the file is absent

The write is create-only by construction: the contents API's PUT without a blob sha creates a
file and refuses to replace one, and nothing here ever sends a sha, a force flag or a ref
update. The file is looked for first; a conflict on the write is re-read and refused.

The token is read from the secret store (app/secrets) at the moment of each call and held in a
local for that one call: it is never kept on the client, logged, or put into an error, and no
error here carries GitHub's own text or a URL. Without it every call returns NotConnected and
no request is made.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.engineering_bridge.requests import request_path

log = logging.getLogger("crooks.engineering")

TOKEN_KEY = "github_engineering_inbox_token"
DEFAULT_REPOSITORY = "crooksldn-pixel/clive"
INBOX_BRANCH = "clive/control/owner-inbox"
STATUS_BRANCH = "clive/control/status"
STATUS_PATH = "status.json"
# Which engineering host's loop takes CLIVE's requests (CROOKS_ENGINEERING_HOST). "owner" is the
# production host's own loop and its historical branch names; any other host polls
# clive/control/<host>-inbox and publishes clive/control/<host>-status (INFRASTRUCTURE docs).
DEFAULT_HOST = "owner"
TRUNK_REF = "clive/trunk"
_HOST = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")


def branches_for(host: str) -> tuple[str, str]:
    """The inbox and status branches of one engineering host's loop."""
    if host == DEFAULT_HOST:
        return INBOX_BRANCH, STATUS_BRANCH
    if not isinstance(host, str) or not _HOST.fullmatch(host):
        raise ValueError("an engineering host is lowercase letters, digits and hyphens")
    return f"clive/control/{host}-inbox", f"clive/control/{host}-status"
API_URL = "https://api.github.com"
TIMEOUT_S = 10.0

NOT_CONNECTED = (
    "GitHub is not connected for engineering requests: the inbox token has not been "
    "provisioned on this Mac. Nothing was sent to GitHub."
)

_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True, slots=True)
class NotConnected:
    """No token in the secret store. Nothing was attempted."""

    reason: str = NOT_CONNECTED


@dataclass(frozen=True, slots=True)
class Refused:
    """GitHub, or the file already there, said no. Nothing was written or overwritten."""

    reason: str


@dataclass(frozen=True, slots=True)
class InboxHead:
    sha: str | None         # None: the inbox branch does not exist


@dataclass(frozen=True, slots=True)
class RequestFile:
    path: str
    exists: bool
    content: bytes = b""


@dataclass(frozen=True, slots=True)
class LoopStatus:
    published: bool         # False: the loop has not published status.json yet
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Created:
    path: str
    commit_sha: str


class GitHubError(RuntimeError):
    """GitHub did not answer, or answered with something this client does not accept. The
    text is fixed: what was being done and an HTTP status, never a URL, a header or a body."""


def read_token() -> str | None:
    """The inbox token, read from the secret store now. Absent, not a key the store knows
    yet, or unreadable: None — which every call turns into NotConnected."""
    from app.secrets import keychain

    try:
        value = keychain.get_optional(TOKEN_KEY)
    except Exception:  # noqa: BLE001 — an unknown key or an unusable store is "not connected"
        return None
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


class EngineeringInbox:
    """The loop's inbox and status, on one repository."""

    def __init__(
        self,
        repository: str = DEFAULT_REPOSITORY,
        *,
        token_source: Callable[[], str | None] = read_token,
        transport: httpx.AsyncBaseTransport | None = None,
        api_url: str = API_URL,
        timeout_s: float = TIMEOUT_S,
        host: str = DEFAULT_HOST,
    ) -> None:
        if not isinstance(repository, str) or not _REPOSITORY.fullmatch(repository) or ".." in repository:
            raise ValueError("repository must be owner/name")
        self.repository = repository
        self.host = host
        self.inbox_branch, self.status_branch = branches_for(host)
        self._token_source = token_source
        self._transport = transport
        self._api_url = api_url
        self._timeout_s = timeout_s
        self.requests_made = 0   # every HTTP request this client has sent

    # ------------------------------------------------------------------ reads

    async def status(self) -> LoopStatus | NotConnected:
        """status.json from the status branch, as the loop published it."""
        token = self._token()
        if token is None:
            return NotConnected()
        response = await self._call(token, "GET", self._contents(STATUS_PATH), params={"ref": self.status_branch})
        if response.status_code == 404:
            return LoopStatus(published=False)
        raw = self._file_bytes(response, "the loop's status")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            raise GitHubError("The loop's status is not valid JSON.") from None
        if not isinstance(data, dict):
            raise GitHubError("The loop's status is not a JSON object.")
        return LoopStatus(published=True, data=data)

    async def inbox_head(self) -> InboxHead | NotConnected:
        """The inbox branch's head commit."""
        return await self._branch_head(self.inbox_branch, "the inbox branch")

    async def trunk_head(self, ref: str = TRUNK_REF) -> InboxHead | NotConnected:
        """The commit a new request starts from: the trunk's head, read now, so the model never
        has to know or guess a SHA."""
        return await self._branch_head(ref, "the trunk")

    async def _branch_head(self, branch: str, what: str) -> InboxHead | NotConnected:
        token = self._token()
        if token is None:
            return NotConnected()
        response = await self._call(token, "GET", f"/repos/{self.repository}/git/ref/heads/{branch}")
        if response.status_code == 404:
            return InboxHead(sha=None)
        if response.status_code != 200:
            raise self._failed(response, f"read {what}")
        body = self._json(response, what)
        target = body.get("object") if isinstance(body, dict) else None
        sha = target.get("sha") if isinstance(target, dict) else None
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise GitHubError(f"GitHub did not name {what}'s head commit.")
        return InboxHead(sha=sha)

    async def request_file(self, request_id: str) -> RequestFile | NotConnected:
        """requests/<request_id>.json on the inbox branch: whether it is there, and its bytes."""
        token = self._token()
        if token is None:
            return NotConnected()
        return await self._read_file(token, request_path(request_id))

    # ------------------------------------------------------------------ the write

    async def create_request(self, request_id: str, content: bytes) -> Created | Refused | NotConnected:
        """Create requests/<request_id>.json as one new commit on the inbox, only if absent.
        Never an overwrite and never a force: a file already there, or any conflict, is a
        refusal after a fresh read."""
        token = self._token()
        if token is None:
            return NotConnected()
        path = request_path(request_id)
        if (await self._read_file(token, path)).exists:
            return Refused(f"{path} is already on the engineering inbox; nothing was overwritten.")
        body = {
            "message": f"Request {request_id}",
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self.inbox_branch,
        }
        response = await self._call(token, "PUT", self._contents(path), body=body)
        if response.status_code in (409, 422):
            # A conflict: the branch moved, or the file appeared between the look and the
            # write. Look again and refuse either way; nothing is retried or forced.
            again = await self._read_file(token, path)
            if again.exists:
                return Refused(f"{path} is already on the engineering inbox; nothing was overwritten.")
            return Refused(f"GitHub refused to create {path} (HTTP {response.status_code}); nothing was written.")
        if response.status_code != 201:
            raise self._failed(response, "create the request file")
        answer = self._json(response, "the new commit")
        commit = answer.get("commit") if isinstance(answer, dict) else None
        sha = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(sha, str) or not _SHA.fullmatch(sha):
            raise GitHubError("GitHub created the request file but did not name the commit.")
        log.info("engineering inbox: filed %s as commit %s", path, sha[:12])
        return Created(path=path, commit_sha=sha)

    # ------------------------------------------------------------------ helpers

    def _token(self) -> str | None:
        try:
            token = self._token_source()
        except Exception:  # noqa: BLE001 — a token that cannot be read is no token
            return None
        return token if isinstance(token, str) and token else None

    def _contents(self, path: str) -> str:
        return f"/repos/{self.repository}/contents/{path}"

    async def _read_file(self, token: str, path: str) -> RequestFile:
        response = await self._call(token, "GET", self._contents(path), params={"ref": self.inbox_branch})
        if response.status_code == 404:
            return RequestFile(path=path, exists=False)
        return RequestFile(path=path, exists=True, content=self._file_bytes(response, "the request file"))

    async def _call(
        self, token: str, method: str, url: str, *, params: dict[str, str] | None = None, body: dict[str, Any] | None = None,
    ) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "clive-engineering-bridge",
        }
        self.requests_made += 1
        try:
            async with httpx.AsyncClient(
                base_url=self._api_url, transport=self._transport, timeout=self._timeout_s, follow_redirects=False,
            ) as client:
                response = await client.request(method, url, params=params, json=body, headers=headers)
        except httpx.HTTPError as exc:
            # The exception's own text can carry the URL; only its kind travels.
            log.warning("engineering inbox: %s did not complete (%s)", method, type(exc).__name__)
            raise GitHubError(f"GitHub could not be reached ({type(exc).__name__}).") from None
        log.info("engineering inbox: %s -> HTTP %s", method, response.status_code)
        return response

    def _json(self, response: httpx.Response, what: str) -> Any:
        try:
            return response.json()
        except ValueError:
            raise GitHubError(f"GitHub's answer about {what} was not JSON.") from None

    def _file_bytes(self, response: httpx.Response, what: str) -> bytes:
        if response.status_code != 200:
            raise self._failed(response, f"read {what}")
        body = self._json(response, what)
        if not isinstance(body, dict) or body.get("type") != "file" or body.get("encoding") != "base64" or not isinstance(body.get("content"), str):
            raise GitHubError(f"GitHub did not return {what} as a file.")
        try:
            return base64.b64decode(body["content"])
        except ValueError:   # binascii.Error is one
            raise GitHubError(f"GitHub returned {what} in a form that could not be decoded.") from None

    def _failed(self, response: httpx.Response, what: str) -> GitHubError:
        if response.status_code in (401, 403):
            return GitHubError(f"GitHub refused the engineering inbox token when asked to {what} (HTTP {response.status_code}).")
        return GitHubError(f"GitHub could not {what} (HTTP {response.status_code}).")
