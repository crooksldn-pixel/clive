"""GitHub as transport only: a bounded remote name and ref, never an arbitrary URL or shell.

Every call here runs ``git`` with an argv list (never a shell string), against a
remote name and branch that must already look like a git identifier, not a URL. The
adapter fetches only the one configured remote and the one dedicated inbox branch; it
never accepts a URL, a refspec with wildcards, or a shell fragment from request content.

When a git call fails, only the operation and its exit status travel: git names the remote
it was talking to in its own diagnostics, and an authenticated remote URL carries a
credential, so remote output never enters an exception message here. See ``TransportError``.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .errors import InboxError, TransportError

DEFAULT_INBOX_BRANCH = "clive/control/owner-inbox"
DEFAULT_INBOX_DIRECTORY = "requests"

_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]+$")


def _validate_name(value: str, *, what: str) -> str:
    if (
        not value
        or value.startswith(("-", "/"))
        or value.endswith("/")
        or ".." in value
        or not _NAME_RE.fullmatch(value)
    ):
        # The rejected value is never echoed: this message reaches a long-lived process
        # log and, for the one-shot verbs, stdout -- and an operator who mistypes an
        # authenticated URL into --remote would otherwise print its credential.
        raise InboxError(f"{what} is not a bounded git identifier")
    return value


def _validate_remote(value: str) -> str:
    _validate_name(value, what="remote")
    if "://" in value or "@" in value or ":" in value:
        raise InboxError("remote must be a configured remote name, never a URL")
    return value


def fetch_inbox(
    repo: Path, *, remote: str = "origin", branch: str = DEFAULT_INBOX_BRANCH, timeout_s: int = 60
) -> str:
    """Fetch exactly one remote's one branch and return the commit it now points at."""
    remote = _validate_remote(remote)
    branch = _validate_name(branch, what="inbox branch")
    proc = subprocess.run(
        ["git", "fetch", "--quiet", remote, branch],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    if proc.returncode != 0:
        raise TransportError(f"fetch of {remote} {branch} failed (git exit {proc.returncode}); output withheld")
    rev = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{branch}^{{commit}}"],
        cwd=str(repo),
        capture_output=True,
        text=True,
    )
    sha = rev.stdout.strip()
    if rev.returncode != 0 or len(sha) != 40:
        raise TransportError(f"refs/remotes/{remote}/{branch} did not resolve to a commit after fetch")
    return sha


def discover_requests(
    repo: Path, ref_sha: str, directory: str = DEFAULT_INBOX_DIRECTORY
) -> tuple[tuple[str, bytes], ...]:
    """Every ``*.json`` request file under ``directory`` at ``ref_sha``, by name, oldest path order."""
    directory = directory.strip("/")
    listing = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", ref_sha, "--", directory],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=60,
    )
    if listing.returncode != 0:
        raise TransportError(f"cannot list the inbox directory at {ref_sha} (git exit {listing.returncode}); output withheld")
    names = sorted(name for name in listing.stdout.split("\0") if name.endswith(".json"))
    out: list[tuple[str, bytes]] = []
    for index, name in enumerate(names):
        show = subprocess.run(
            ["git", "show", f"{ref_sha}:{name}"], cwd=str(repo), capture_output=True, timeout=60
        )
        if show.returncode != 0:
            raise TransportError(
                f"cannot read inbox record {index} of {len(names)} at {ref_sha} "
                f"(git exit {show.returncode}); output withheld"
            )
        out.append((name, show.stdout))
    return tuple(out)


def bounded_source(directory: str, name: str, digest: str, request_id: str | None) -> str:
    """The discovered path only when it is the request's own id, else an opaque locator.

    A filename under the inbox directory is chosen by whoever opened the request, so it
    is exactly as untrusted as the file's content -- and a bounded character set is no
    defence here, because a credential is alphanumeric and ``sk-....json`` is a perfectly
    well-formed filename. ``source`` is written into a durable receipt and published on a
    public branch, so the only path safe to echo is one that repeats nothing the
    projection does not already carry: ``<directory>/<request_id>.json``, where the id is
    already published beside it. Every other path -- nested, oddly named, or simply not
    matching its own id -- and every record too malformed to have a trusted id at all is
    identified by the digest of its exact bytes, which is what a receipt keys on anyway.
    """
    if request_id is not None and name == f"{directory}/{request_id}.json":
        return name
    return f"{directory}/#{digest}"
