"""Deploy now, CLIVE's half: George's hold and passkey become an approval for exactly one SHA, and his
phone's own /whoami check keeps the deploy (DEC-072; the owner's rulings 6, 7 and 8 of 8 October 2026).

Why it exists. George, 8 Oct: "i want to say yes to deploy - but, once deploy should be instant, not
deploy and then the deploy service runs and takes hours. deploy as in, implement this now". So the
Builds screen offers "Deploy now" (app/release/offer.py), his hold asks for his passkey, and the
approval it gives is written into the folder the release service is started from at once
(deploy/release/clive-release-now.path). CLIVE never holds root and never starts a deploy itself: it
writes one file in its own state folder, and the release service checks everything again on its own.

    begin(...)    a challenge this server issues for exactly one SHA: a fresh nonce, the moment it was
                  issued and the moment it expires, bound into what the passkey signs
                  (app/release/authority.py waiver_challenge); held here, good once, for minutes
    finish(...)   the passkey's answer checked as every approval is (app/connections/passkeys.py: this
                  CLIVE's page, his passkey, present and verified, its counter going up), then the
                  waiver written and read back, with no words of his in it and no login
    latest(...)   the latest approval CLIVE wrote, for the progress it shows
    keep(...)     after the deploy, his phone's /whoami line found in this service's own journal, by
                  the build that was deployed: the deploy is kept (DEPLOY_LINUX.md), and recorded here

What it promises: an approval is for one SHA and one deploy, and expires in minutes; a refused,
stale or expired one writes nothing; a deploy is "kept" only once the journal holds the very line the
procedure asks for, with the token his phone was given.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.connections import passkeys
from app.release import authority

WAIVERS = "release-waivers"          # in CLIVE's objectives folder; the release service reads it
KEPT = "release-kept"                # CLIVE's own record of the deploys his phone kept
GIVEN_BY = "the owner"               # never a login: the release service's record of it is public
SERVICE = "crooks-assistant.service"
MAX_ASKED = 8
MAX_JOURNAL_LINES = 20000
_SHA = re.compile(r"^[0-9a-f]{40}$")
_TICKET = re.compile(r"^[A-Za-z0-9_-]{43}$")       # 32 bytes, base64url
_CHECK = re.compile(r"^[0-9a-f]{8}$")               # /whoami's token (app/routes/admin.py)


class Refused(Exception):
    """A deploy approval or a keep that does not hold, with words fit to show George."""

    def __init__(self, status: int, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status, self.code, self.detail = status, code, detail


@dataclass(frozen=True)
class Asked:
    sha: str
    title: str
    nonce: bytes
    issued_at: int
    expires_at: int
    login: str


_LOCK = threading.Lock()
_ASKED: dict[str, Asked] = {}


def reset() -> None:
    """Tests: forget every challenge this process has issued."""
    with _LOCK:
        _ASKED.clear()


def iso(seconds: float) -> str:
    return datetime.fromtimestamp(int(seconds), UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _epoch(text: Any) -> float | None:
    if not isinstance(text, str) or len(text) > 40:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment.timestamp() if moment.tzinfo is not None else None


def action(sha: str, nonce: bytes) -> str:
    """What the passkey approves, in passkeys.py's terms: deploying this SHA, under this one challenge."""
    return f"release:deploy:{sha}:{authority.approval_id(nonce)}"


# ------------------------------------------------------------------ the challenge, and his answer


def begin(sha: str, title: str, *, repository: str, login: str, origin: str, rp_id: str, now: float) -> dict[str, Any]:
    """The passkey prompt for deploying exactly `sha`: options for navigator.credentials.get(), and the
    ticket the page sends back with the answer."""
    if not _SHA.fullmatch(sha or ""):
        raise Refused(400, "bad_request", "A deploy is for an exact version. Reload the Builds screen.")
    nonce = secrets.token_bytes(32)
    issued = int(now)
    expires = issued + authority.APPROVAL_TTL_S
    challenge = authority.waiver_challenge(repository, sha, nonce, issued_at=issued, expires_at=expires)
    options = passkeys.begin_approval(action(sha, nonce), login=login, origin=origin, rp_id=rp_id, challenge=challenge)
    ticket = passkeys.b64url(nonce)
    with _LOCK:
        for stale in [k for k, a in _ASKED.items() if a.expires_at <= now]:
            _ASKED.pop(stale, None)
        while len(_ASKED) >= MAX_ASKED:
            _ASKED.pop(min(_ASKED, key=lambda k: _ASKED[k].issued_at), None)
        _ASKED[ticket] = Asked(sha, " ".join(str(title or "").split())[:160], nonce, issued, expires, login)
    return {"publicKey": options, "ticket": ticket, "expires_at": iso(expires)}


def finish(sha: str, ticket: str, assertion: Any, *, repository: str, login: str, origin: str, folder: Path,
           now: float) -> dict[str, Any]:
    """His passkey's answer to the prompt `begin` made: checked, then the waiver for exactly that SHA
    written into `folder` and read back. The ticket is spent first, whatever happens next."""
    with _LOCK:
        asked = _ASKED.pop(ticket, None) if isinstance(ticket, str) and _TICKET.fullmatch(ticket) else None
    if asked is None:
        raise Refused(409, "approval_stale", "That approval wasn't asked for here, or was already used. "
                                             "Nothing was deployed. Hold the card again.")
    if asked.sha != sha or asked.login != login:
        raise Refused(409, "approval_other", "That approval was asked for another version. Nothing was deployed. "
                                             "Hold the card again.")
    if now > asked.expires_at:
        raise Refused(409, "approval_expired", "That approval took too long and expired. Nothing was deployed. "
                                               "Hold the card again.")
    try:
        passkeys.verify_approval(assertion, action(sha, asked.nonce), login=login, origin=origin)
    except passkeys.PasskeyRefused as exc:
        raise Refused(403, exc.code, f"{exc} Nothing was deployed.") from None
    response = assertion["response"]
    waiver = {
        "schema": authority.WAIVER_SCHEMA, "sha": sha, "repository": repository, "waives": "exact_sha_review",
        "given_by": GIVEN_BY, "given_at": iso(now), "words": "", "source": "passkey", "title": asked.title,
        "passkey": {
            "credential_id": passkeys.b64url(passkeys.unb64url(assertion.get("rawId") or assertion.get("id"),
                                                                field="the passkey's identity")),
            "nonce": ticket, "issued_at": asked.issued_at, "expires_at": asked.expires_at,
            "client_data_json": response.get("clientDataJSON"),
            "authenticator_data": response.get("authenticatorData"),
            "signature": response.get("signature"),
        },
    }
    data = (json.dumps(waiver, indent=1) + "\n").encode("utf-8")
    path = Path(folder) / f"{sha}.json"
    if not _write(path, data):
        raise Refused(500, "not_written", "Your approval could not be saved where the release service reads it, "
                                          "so nothing was deployed.")
    return {"sha": sha, "approval": authority.approval_id(asked.nonce), "given_at": waiver["given_at"],
            "expires_at": iso(asked.expires_at)}


def _write(path: Path, data: bytes) -> bool:
    """Beside it, flushed, renamed over it (the rename is what the release service's trigger sees),
    then read back: True only when the file holds exactly `data`."""
    tmp = path.with_name(f".{path.name}.new")
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, data)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
        return path.read_bytes() == data
    except OSError:
        tmp.unlink(missing_ok=True)
        return False


# ------------------------------------------------------------------ what CLIVE wrote, read back


def latest(folder: Path) -> dict[str, Any] | None:
    """The latest approval CLIVE wrote: {sha, title, approval, given_at, expires_at}, or None."""
    found = []
    try:
        # The newest first: one approval is written per version, so the folder only grows.
        paths = sorted(Path(folder).glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if Path(folder).is_dir() else []
    except OSError:
        return None
    for path in paths[:50]:
        record = authority.parse(_read(path))
        signed = record.get("passkey") if record else None
        if not record or not isinstance(signed, dict) or not _SHA.fullmatch(str(record.get("sha") or "")):
            continue
        given = _epoch(record.get("given_at"))
        try:
            nonce = passkeys.unb64url(signed.get("nonce"), field="the nonce")
        except passkeys.PasskeyRefused:
            continue
        expires = signed.get("expires_at")
        if given is None or not isinstance(expires, int):
            continue
        found.append({"sha": record["sha"], "title": " ".join(str(record.get("title") or "").split())[:160],
                      "approval": authority.approval_id(nonce), "given_at": iso(given), "given": given,
                      "expires_at": iso(expires), "expires": expires})
    return max(found, key=lambda a: a["given"]) if found else None


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes() if path.stat().st_size <= authority.MAX_RECORD else None
    except OSError:
        return None


def kept_record(folder: Path, sha: str) -> dict[str, Any] | None:
    if not _SHA.fullmatch(sha or ""):
        return None
    record = authority.parse(_read(Path(folder) / f"{sha}.json"))
    return record if record and record.get("sha") == sha and _epoch(record.get("kept_at")) else None


# ------------------------------------------------------------------ kept: his phone, through, on the new build


def whoami_line(check: str) -> str:
    """The journal line the procedure keeps a deploy on (DEPLOY_LINUX.md, "A real phone gets through")."""
    return f"whoami: id={check} through=tailscale owner=true refusal=none"


def journal_has(line: str, since: float) -> bool | None:
    """Whether this service's journal holds `line` since `since` (seconds since 1970): None when the
    journal could not be read, which is never taken as a yes."""
    try:
        done = subprocess.run(["journalctl", "-u", SERVICE, "--since", f"@{int(since)}", "--no-pager", "-o", "cat",
                               "-n", str(MAX_JOURNAL_LINES)], capture_output=True, text=True, errors="replace",
                              timeout=20, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    pattern = re.compile(r"(^|\s)" + re.escape(line) + r"\s*$")
    return any(pattern.search(text) for text in done.stdout.splitlines())


def keep(sha: str, check: str, *, process_sha: str, release: dict[str, Any], folder: Path, now: float,
         journal=None) -> dict[str, Any]:
    """Keep the deploy of `sha` once his phone's /whoami line (token `check`) is in the journal since the
    deploy was done, asked of the build that was deployed. Recorded in `folder`; returns the record."""
    if not _SHA.fullmatch(sha or "") or not _CHECK.fullmatch(check or ""):
        raise Refused(400, "bad_request", "That check isn't one /whoami gives. Reload the page.")
    done = _done_at(release, sha)
    if done is None:
        raise Refused(409, "not_deployed", "The release service hasn't said this version was deployed.")
    if process_sha != sha:
        raise Refused(409, "not_this_build", "CLIVE isn't running the new build yet, so it can't be kept yet.")
    found = (journal or journal_has)(whoami_line(check), done)
    if found is None:
        raise Refused(503, "journal_unreadable", "CLIVE couldn't read its own journal, so it can't tell your phone "
                                                 "got through. Not kept yet.")
    if not found:
        raise Refused(409, "not_in_journal", "Your phone's check isn't in CLIVE's journal yet. Not kept yet.")
    record = {"sha": sha, "kept_at": iso(now), "check": check, "how": whoami_line(check)}
    if not _write(Path(folder) / f"{sha}.json", (json.dumps(record, indent=1) + "\n").encode("utf-8")):
        raise Refused(500, "not_written", "Your phone got through, but CLIVE couldn't record that it was kept.")
    return record


def _done_at(release: dict[str, Any], sha: str) -> float | None:
    """When the release service says the deploy of `sha` was done, from its status (app/release/status.py)."""
    deploy = release.get("deploy") if isinstance(release, dict) else None
    if not isinstance(deploy, dict) or deploy.get("sha") != sha or deploy.get("end") != "done":
        return None
    at = next((step.get("at") for step in deploy.get("steps") or [] if step.get("stage") == "done"), None)
    return _epoch(at)
