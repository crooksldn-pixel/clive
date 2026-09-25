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
import threading
import time
from pathlib import Path

from .errors import InboxBoundExceeded, InboxError, TransportError

DEFAULT_INBOX_BRANCH = "clive/control/owner-inbox"
DEFAULT_INBOX_DIRECTORY = "requests"

REMOTE_NAME_MAX = 64
REF_NAME_MAX = 200

# Work bounds on one inbox snapshot. The inbox is remote input: without these a large listing,
# many files or one huge file would stall the long-lived loop before the Dispatcher ticks.
MAX_INBOX_RECORDS = 100
MAX_RECORD_BYTES = 64 * 1024
MAX_SNAPSHOT_BYTES = 1024 * 1024
MAX_LISTING_BYTES = 256 * 1024
MAX_DISCOVERY_S = 60.0

_NAME_RE = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")
_REMOTE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_DIRECTORY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_inbox_directory(value: str) -> str:
    """One plain path component under which request files live. Refused without echo."""
    if not isinstance(value, str) or not _DIRECTORY_RE.fullmatch(value):
        raise InboxError("inbox directory must be one plain path component")
    return value


def _validate_name(value: str, *, what: str) -> str:
    """A bounded, canonical git ref name, decided before any git call.

    Canonical here means what ``git check-ref-format`` would accept for a branch, restricted
    further to a small character set: no empty, ``.``-leading or ``.lock``-ending component, no
    ``..``, no trailing ``.`` and at most ``REF_NAME_MAX`` characters. The rejected value is never
    echoed: this message reaches a long-lived process log and one-shot stdout.
    """
    if not isinstance(value, str) or not _NAME_RE.fullmatch(value) or len(value) > REF_NAME_MAX:
        raise InboxError(f"{what} is not a bounded git identifier")
    parts = value.split("/")
    if (
        value.startswith("-")
        or ".." in value
        or value.endswith(".")
        or any(not part or part.startswith(".") or part.endswith(".lock") for part in parts)
    ):
        raise InboxError(f"{what} is not a canonical git ref name")
    return value


def _validate_remote(value: str) -> str:
    """A configured remote's name: short, one component, never a URL. Never echoed."""
    if not isinstance(value, str) or not _REMOTE_RE.fullmatch(value) or value.endswith(".lock"):
        raise InboxError("remote is not a bounded git identifier: it must be a configured remote name, never a URL")
    return value


def fetch_inbox(
    repo: Path, *, remote: str = "origin", branch: str = DEFAULT_INBOX_BRANCH, timeout_s: int = 60
) -> str:
    """Fetch exactly one remote's one branch into its own tracking ref; return that commit.

    ``--no-tags`` and an explicit full refspec confine the fetch to the dedicated inbox ref:
    git cannot auto-follow tags into local refs that a request's ``base_ref`` could then name.
    Failures carry fixed text only -- never the remote, the branch or git's own output.
    """
    remote = _validate_remote(remote)
    branch = _validate_name(branch, what="inbox branch")
    destination = f"refs/remotes/{remote}/{branch}"
    try:
        proc = subprocess.run(
            ["git", "fetch", "--quiet", "--no-tags", remote, f"+refs/heads/{branch}:{destination}"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        raise TransportError("inbox fetch exceeded its time bound; output withheld") from None
    if proc.returncode != 0:
        raise TransportError(f"inbox fetch failed (git exit {proc.returncode}); output withheld")
    rev = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{destination}^{{commit}}"],
        cwd=str(repo),
        capture_output=True,
        text=True,
        timeout=30,
    )
    sha = rev.stdout.strip()
    if rev.returncode != 0 or len(sha) != 40:
        raise TransportError("the inbox branch did not resolve to a commit after fetch")
    return sha


def _bounded_git(repo: Path, args: list[str], *, limit: int, deadline: float, what: str) -> bytes:
    """Run git and read at most ``limit`` bytes of its stdout before ``deadline``, or refuse.

    Memory and time are both bounded: output past ``limit`` kills the process instead of
    being buffered, and a timer kills it at the deadline. stderr is discarded unread.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise InboxBoundExceeded("inbox snapshot exceeded its time bound; nothing was admitted")
    proc = subprocess.Popen(["git", *args], cwd=str(repo), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    fired = threading.Event()

    def _expire() -> None:
        fired.set()
        proc.kill()

    timer = threading.Timer(remaining, _expire)
    timer.start()
    try:
        assert proc.stdout is not None
        data = proc.stdout.read(limit + 1)
        if len(data) > limit:
            proc.kill()
        returncode = proc.wait()
    finally:
        timer.cancel()
        if proc.stdout is not None:
            proc.stdout.close()
    if fired.is_set():
        raise InboxBoundExceeded("inbox snapshot exceeded its time bound; nothing was admitted")
    if len(data) > limit:
        raise InboxBoundExceeded(f"inbox {what} exceeded its size bound; nothing was admitted")
    if returncode != 0:
        raise TransportError(f"cannot read the inbox {what} (git exit {returncode}); output withheld")
    return data


def discover_requests(
    repo: Path, ref_sha: str, directory: str = DEFAULT_INBOX_DIRECTORY
) -> tuple[tuple[str, bytes], ...]:
    """Every ``*.json`` request file under ``directory`` at ``ref_sha``, by name, oldest path order.

    Bounded before anything is parsed: the listing, the number of records, each record's size
    and their total size are checked from the tree listing *before* any blob is read, and the
    whole discovery runs against one wall-clock deadline. Exceeding any bound admits nothing
    from the snapshot and raises ``InboxBoundExceeded`` with fixed text.
    """
    deadline = time.monotonic() + MAX_DISCOVERY_S
    directory = validate_inbox_directory(directory.strip("/"))
    listing = _bounded_git(
        repo, ["ls-tree", "-r", "-z", "-l", ref_sha, "--", directory],
        limit=MAX_LISTING_BYTES, deadline=deadline, what="listing",
    ).decode("utf-8", errors="replace")
    entries: list[tuple[str, str, int]] = []
    for record in listing.split("\0"):
        if not record:
            continue
        meta, _, name = record.partition("\t")
        if not name.endswith(".json"):
            continue
        fields = meta.split()
        if len(fields) != 4 or fields[1] != "blob" or not fields[3].isdigit():
            raise InboxBoundExceeded("inbox holds a request entry that is not a plain file; nothing was admitted")
        entries.append((name, fields[2], int(fields[3])))
    if len(entries) > MAX_INBOX_RECORDS:
        raise InboxBoundExceeded("inbox holds more records than its bound; nothing was admitted")
    if any(size > MAX_RECORD_BYTES for _, _, size in entries):
        raise InboxBoundExceeded("inbox holds a record larger than its bound; nothing was admitted")
    if sum(size for _, _, size in entries) > MAX_SNAPSHOT_BYTES:
        raise InboxBoundExceeded("inbox snapshot exceeds its aggregate size bound; nothing was admitted")
    out: list[tuple[str, bytes]] = []
    for name, oid, size in sorted(entries):
        body = _bounded_git(repo, ["cat-file", "blob", oid], limit=size, deadline=deadline, what="record")
        out.append((name, body))
    return tuple(out)


def bounded_source(directory: str, name: str, digest: str, request_id: str | None) -> str:
    """A locator for one inbox record that repeats nothing a requester or operator chose.

    A filename under the inbox directory is chosen by whoever opened the request, so it is
    exactly as untrusted as the file's content, and the directory itself is host configuration
    that must not be echoed either. The locator therefore uses the fixed label
    ``DEFAULT_INBOX_DIRECTORY`` whatever the configured directory is: ``requests/<id>.json``
    when the record sits at ``<directory>/<request_id>.json`` (the id is already published
    beside it), otherwise ``requests/#<sha256 of its exact bytes>``.
    """
    if request_id is not None and name == f"{directory}/{request_id}.json":
        return f"{DEFAULT_INBOX_DIRECTORY}/{request_id}.json"
    return f"{DEFAULT_INBOX_DIRECTORY}/#{digest}"
