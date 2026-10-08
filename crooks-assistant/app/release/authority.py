"""Who may let a SHA reach production: the authorisation each deploy rule asks for, checked.

Why it exists: George approved the release service on one condition, "It only deploys once you've
said who holds deploy authority". He picks one of two rules (CLIVE_RELEASE_RULE), and this file is
what each one accepts, for exactly one SHA and nothing near it.

exact_sha_review: a reviewer's record for that exact SHA, on the branch claude/review-<sha8>-record,
in crooks-assistant/reports/review-<sha8>.json:

    {"schema": "clive.release.review.v1", "sha": "<40 hex: the trunk SHA to deploy>",
     "base_sha": "<40 hex: what production ran when it was reviewed>", "verdict": "SHIP",
     "blocking": [], "reviewer": "<who>", "reviewed_at": "<ISO time>",
     "rule": "regression-only (OWNER_DECISIONS_2026-09-30)", "summary": "<one line>"}

  Only SHIP deploys, only with nothing blocking, and only while the production SHA it was measured
  against is still what production runs or behind it (the ship rule measures against "the SHA
  production runs now"). Whoever can push to the repository can write such a branch: that is the
  authority this rule hands over, and docs/RELEASE_SERVICE.md says so to George in those words.

owner_waiver: George's waiver of the review for that exact SHA (as for b33ccbc2, cac1a9e7 and
66d3e05d), in one of two forms, both `{"schema": "clive.release.waiver.v1", "sha", "repository",
"waives": "exact_sha_review", "given_by", "given_at", "words", "source", "passkey"}`:

  host     written on the server (python -m app.release waive) into a root-only folder; trusted
           because only root can write there, and root can deploy by hand anyway.
  passkey  collected by CLIVE with his passkey, the way every Connections change is: the record
           carries the WebAuthn assertion itself, over a challenge derived from this repository,
           this SHA, a nonce CLIVE's server issued and the moments it was issued and expires
           (`waiver_challenge`), and is verified here against his registered public key with
           app/connections/passkeys.py's own checks. Where the file lies is not trusted; the
           signature is. A tap given for one SHA cannot authorise another.

           Since 8 October (DEC-072; the review of the release service, notes 10 and 11) the
           challenge is server-issued, expires and is good once: CLIVE issues the nonce and the two
           moments and checks the passkey's counter as it does for every approval; the moments are
           inside what the passkey signed, so a copied waiver cannot be given a longer life; here a
           waiver past its expiry is refused, and the approval it carries (`approval_id`) is marked
           used (app/release/state.py) before a live deploy begins, so it starts one deploy at most.

Every refusal is a sentence built here; nothing from the record is repeated except the reviewer's
name, George's name and a summary, each bounded to one line.
"""

from __future__ import annotations

import hashlib
import json
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REVIEW_SCHEMA = "clive.release.review.v1"
WAIVER_SCHEMA = "clive.release.waiver.v1"
SHIP = "SHIP"
_SHA = re.compile(r"^[0-9a-f]{40}$")
# v2 (8 Oct): the challenge also binds when CLIVE issued it and when it expires (DEC-072).
_CHALLENGE_TAG = b"clive.release.waiver.v2"
MAX_RECORD = 64 * 1024
NONCE_MIN = 16
# How long an approval given in CLIVE may start a deploy: the trigger starts one at once, and the
# timer (every five minutes, up to 30 s late) is the fallback, so ten minutes covers both.
APPROVAL_TTL_S = 600
# Longer than this was not issued by CLIVE (approve.py issues APPROVAL_TTL_S): refused, not trusted.
MAX_TTL_S = 900
# A moment of issue later than this host's clock by more than this is not believed either.
CLOCK_SLACK_S = 60


def review_path(sha: str) -> str:
    return f"crooks-assistant/reports/review-{sha[:8]}.json"


@dataclass(frozen=True)
class Authority:
    ok: bool
    reason: str
    kind: str = ""          # "review" or "waiver"
    by: str = ""
    at: str = ""
    source: str = ""        # where it was found, in words
    detail: dict[str, Any] = field(default_factory=dict)


def _line(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join("".join(c if c.isprintable() else " " for c in value).split())[:limit]


def _when(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 40:
        return ""
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return value if stamp.tzinfo is not None else ""


def parse(raw: bytes | None) -> dict[str, Any] | None:
    if raw is None or len(raw) > MAX_RECORD:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None
    return data if isinstance(data, dict) else None


# ------------------------------------------------------------------ the exact-SHA review


def check_review(record: dict[str, Any] | None, sha: str, *, base_is_behind_production) -> Authority:
    """A reviewer's SHIP for exactly `sha`. `base_is_behind_production(base)` says whether the
    production SHA the review was measured against is production's own SHA or an ancestor of it."""
    if record is None:
        return Authority(False, "the review record is not readable JSON")
    if record.get("schema") != REVIEW_SCHEMA:
        return Authority(False, f"the review record is not a {REVIEW_SCHEMA} record")
    if record.get("sha") != sha:
        return Authority(False, "the review record is about another commit")
    verdict = record.get("verdict")
    if verdict != SHIP:
        return Authority(False, f"the review's verdict is {_line(verdict, 20) or 'missing'}, not SHIP")
    blocking = record.get("blocking")
    if not isinstance(blocking, list) or blocking:
        return Authority(False, "the review lists blocking findings" if isinstance(blocking, list) and blocking
                         else "the review does not say what blocks (its 'blocking' list is missing)")
    reviewer, at = _line(record.get("reviewer"), 120), _when(record.get("reviewed_at"))
    if not reviewer or not at:
        return Authority(False, "the review record does not say who reviewed it and when")
    base = record.get("base_sha")
    if not isinstance(base, str) or not _SHA.fullmatch(base):
        return Authority(False, "the review does not say which production SHA it was measured against")
    if not base_is_behind_production(base):
        return Authority(False, f"the review was measured against {base[:8]}, which is not what production runs "
                                "or behind it, so it did not cover this change")
    return Authority(True, f"reviewed SHIP by {reviewer}", kind="review", by=reviewer, at=at,
                     detail={"base_sha": base, "verdict": SHIP, "rule": _line(record.get("rule"), 160),
                             "summary": _line(record.get("summary"), 300)})


# ------------------------------------------------------------------ George's waiver


def waiver_challenge(repository: str, sha: str, nonce: bytes, *, issued_at: int, expires_at: int) -> bytes:
    """The WebAuthn challenge a passkey waiver answers: this repository, this SHA, the nonce CLIVE's
    server issued, and when it issued it and when it expires (whole seconds since 1970, UTC). Every
    part is inside what the passkey signs, so none can be changed after the tap."""
    return hashlib.sha256(b"\x00".join((_CHALLENGE_TAG, repository.encode("utf-8"), sha.encode("ascii"), nonce,
                                         str(int(issued_at)).encode("ascii"),
                                         str(int(expires_at)).encode("ascii")))).digest()


def approval_id(nonce: bytes) -> str:
    """The name one approval goes by once it is used (app/release/state.py) and on the status CLIVE
    reads: derived from the nonce, never the nonce itself."""
    return hashlib.sha256(b"clive.release.approval\x00" + nonce).hexdigest()[:32]


def _clock(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, UTC).strftime("%H:%M UTC")


def _waiver_basics(record: dict[str, Any] | None, sha: str, repository: str, source: str) -> str | None:
    if record is None:
        return "the waiver is not readable JSON"
    if record.get("schema") != WAIVER_SCHEMA:
        return f"the waiver is not a {WAIVER_SCHEMA} record"
    if record.get("sha") != sha:
        return "the waiver is for another commit"
    if record.get("repository") != repository:
        return "the waiver is for another repository"
    if record.get("waives") != "exact_sha_review":
        return "the waiver does not say it waives the exact-SHA review"
    if record.get("source") != source:
        return f"the waiver does not say it was given {'on the host' if source == 'host' else 'with a passkey'}"
    if not _line(record.get("given_by"), 80) or not _when(record.get("given_at")):
        return "the waiver does not say who gave it and when"
    return None


def _granted(record: dict[str, Any], source: str, how: str) -> Authority:
    by = _line(record.get("given_by"), 80)
    # His free-text "words" are not carried: nothing downstream may put them in the public record.
    return Authority(True, f"waived by {by} ({how})", kind="waiver", by=by, at=_when(record.get("given_at")),
                     source=source)


def _root_only(host, path: Path, kind: int) -> bool:
    found = host.stat(path)
    if found is None:
        return False
    uid, mode = found
    return uid == 0 and stat.S_IFMT(mode) == kind and not mode & 0o022


def host_waiver(host, folder: Path, sha: str, repository: str) -> Authority | None:
    """A waiver written on the server, believed only from a root-owned folder nobody else can write."""
    path = Path(folder) / f"{sha}.json"
    raw = host.read(path)
    if raw is None:
        return None
    if not (_root_only(host, Path(folder), stat.S_IFDIR) and _root_only(host, path, stat.S_IFREG)):
        return Authority(False, "a waiver is on the host, but its folder or file can be written by someone other "
                                "than root, so it is not believed")
    record = parse(raw)
    refused = _waiver_basics(record, sha, repository, "host")
    if refused:
        return Authority(False, refused)
    return _granted(record, "host", "given on the server")


def passkey_waiver(host, folder: Path, passkeys_file: Path, sha: str, repository: str, *,
                   used: Callable[[str], dict[str, Any] | None] = lambda _approval: None) -> Authority | None:
    """A waiver CLIVE collected with George's passkey: believed only if its signature is his, over
    a challenge CLIVE issued for exactly this SHA, still inside its life, and never used before
    (`used(approval_id)` answers when it was, from the service's own record)."""
    raw = host.read(Path(folder) / f"{sha}.json")
    if raw is None:
        return None
    record = parse(raw)
    refused = _waiver_basics(record, sha, repository, "passkey")
    if refused:
        return Authority(False, refused)
    credentials = _credentials(host.read(Path(passkeys_file)))
    why, approval = verify_passkey(record.get("passkey"), credentials, repository, sha,
                                   now=int(host.now().timestamp()), used=used)
    if why:
        return Authority(False, f"the passkey waiver does not hold: {why}")
    granted = _granted(record, "passkey", "with his passkey")
    return Authority(True, granted.reason, kind=granted.kind, by=granted.by, at=granted.at, source=granted.source,
                     detail={"approval": approval})


def _credentials(raw: bytes | None) -> list[dict[str, Any]]:
    data = parse(raw)
    found = data.get("credentials") if data else None
    return [c for c in found if isinstance(c, dict) and c.get("id")] if isinstance(found, list) else []


def _moments(signed: dict[str, Any]) -> tuple[int, int] | None:
    issued, expires = signed.get("issued_at"), signed.get("expires_at")
    if not all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in (issued, expires)):
        return None
    return issued, expires


def verify_passkey(signed: Any, credentials: list[dict[str, Any]], repository: str, sha: str, *, now: int,
                   used: Callable[[str], dict[str, Any] | None] = lambda _approval: None) -> tuple[str | None, str]:
    """(None, the approval's id) when `signed` is a WebAuthn assertion by one of `credentials` over the
    challenge CLIVE issued for this SHA, still inside its life at `now` and not used before; otherwise
    (why not, ""). The signature checks are app/connections/passkeys.py's: the page that asked, the
    passkey's site, the person present and verified, the signature with the registered key."""
    from app.connections import passkeys as pk

    if not isinstance(signed, dict):
        return "it carries no passkey assertion", ""
    if not credentials:
        return "no passkey is registered on this server", ""
    moments = _moments(signed)
    if moments is None:
        return ("it carries no challenge CLIVE issued with an expiry (an older form of approval): "
                "hold the card in CLIVE again"), ""
    issued, expires = moments
    try:
        nonce = pk.unb64url(signed.get("nonce"), field="the waiver's nonce")
        client_raw = pk.unb64url(signed.get("client_data_json"), field="the prompt's account")
        auth = pk.unb64url(signed.get("authenticator_data"), field="the passkey's data")
        signature = pk.unb64url(signed.get("signature"), field="the passkey's signature")
        identity = pk.b64url(pk.unb64url(signed.get("credential_id"), field="the passkey's identity"))
        if len(nonce) < NONCE_MIN:
            return "its nonce is too short to be one", ""
        record = next((c for c in credentials if c.get("id") == identity), None)
        if record is None:
            return "it was signed by a passkey that is not registered here", ""
        client = json.loads(client_raw.decode("utf-8"))
        if not isinstance(client, dict) or client.get("type") != "webauthn.get":
            return "it answered a different kind of prompt", ""
        if client.get("challenge") != pk.b64url(waiver_challenge(repository, sha, nonce, issued_at=issued,
                                                                 expires_at=expires)):
            return "it was given for something other than deploying this exact SHA", ""
        if client.get("crossOrigin") is True or client.get("origin") != record.get("origin"):
            return "the prompt did not come from CLIVE", ""
        pk._auth_data(auth, str(record.get("rp_id") or ""))           # site, present, verified
        pk._verify(int(record.get("alg") or 0), str(record.get("public_key") or ""), signature,
                   auth + hashlib.sha256(client_raw).digest())
    except pk.PasskeyRefused as exc:
        return str(exc), ""
    except (UnicodeDecodeError, ValueError, TypeError):
        return "it cannot be read", ""
    # Signed, so the moments are CLIVE's own: now judge them.
    if expires <= issued or expires - issued > MAX_TTL_S or issued > now + CLOCK_SLACK_S:
        return "its challenge does not have the life CLIVE gives one, so CLIVE did not issue it", ""
    if now > expires:
        return (f"the approval expired at {_clock(expires)} (an approval starts a deploy within "
                f"{APPROVAL_TTL_S // 60} minutes of the hold, or not at all): hold the card in CLIVE again"), ""
    approval = approval_id(nonce)
    spent = used(approval)
    if spent is not None:
        when = str(spent.get("at") or "")[:25] or "an earlier deploy"
        return f"this approval was already used ({when}); each hold starts one deploy: hold the card again", ""
    return None, approval


def waiver(host, settings, sha: str) -> Authority:
    """George's waiver for exactly `sha`: a valid passkey waiver, else a valid host waiver."""
    from app.release import state

    def used(approval: str) -> dict[str, Any] | None:
        return state.approval_used(host, settings.state_dir, approval)

    found = [passkey_waiver(host, settings.passkey_waivers_dir, settings.passkeys_file, sha, settings.repository,
                            used=used),
             host_waiver(host, settings.waivers_dir, sha, settings.repository)]
    for answer in found:
        if answer is not None and answer.ok:
            return answer
    refused = [answer.reason for answer in found if answer is not None]
    if refused:
        return Authority(False, "; ".join(refused))
    return Authority(False, "George has not waived the review for this SHA")
