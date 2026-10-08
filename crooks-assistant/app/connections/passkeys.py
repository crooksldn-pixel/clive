"""The passkey check: the owner's Face ID, fingerprint or device PIN, asked at the moment of every
change to a connection (the owner's decision, 1 October 2026).

The door (app/main.py) already knows a request comes from the owner's own device on the tailnet.
A passkey adds what that cannot: that the owner is there, now, and approved this change. A stolen
session or another site cannot produce one, and a save's approval signs the very values stored
(app/routes/connections.py, sealed), so a tap given for one key never stores another. What it
cannot do is vouch for a device that is itself compromised: the prompt does not say what it
approves, so something controlling the owner's own browser could ask for a tap of its own.

WebAuthn, verified here with `cryptography`. Every approval checks:
- the challenge is one this server issued, for this action, to this owner, unexpired, used once;
- the page that asked is this CLIVE (its origin), and the passkey was made for this host;
- the person was present and verified themselves (the UP and UV flags);
- the signature, over exactly what the authenticator signed, with the key registered for it;
- the signature counter, when the authenticator keeps one, only ever goes up.
Attestation is not asked for ("none"): which make of phone holds the passkey is not the question;
that it is the one registered on the owner's device is.

Registration: the first passkey is registered from the owner's own verified device when there is
none yet. Every later one needs an existing passkey to approve it, and so does removing one.
Public keys, never secrets, are kept in passkeys.json beside the app tier's keys (0600, in the
root-only directory), because adding a key there would grant the power to approve.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

RP_NAME = "CLIVE"
CHALLENGE_S = 180.0          # an approval prompt left open longer than this is asked again
MAX_PENDING = 64
TIMEOUT_MS = 120_000
FILE_NAME = "passkeys.json"
MAX_FIELD = 16 * 1024        # any one encoded field a browser sends
MAX_PASSKEYS = 10

ES256, EDDSA, RS256 = -7, -8, -257
SUPPORTED = (ES256, EDDSA, RS256)

FLAG_UP, FLAG_UV, FLAG_AT, FLAG_ED = 0x01, 0x04, 0x40, 0x80


class PasskeyRefused(Exception):
    """An approval or a registration that does not hold, with a reason fit to show the owner."""

    def __init__(self, reason: str, *, code: str = "passkey_refused") -> None:
        super().__init__(reason)
        self.code = code


@dataclass
class Pending:
    kind: str            # "create" or "get"
    action: str
    login: str
    origin: str
    rp_id: str
    expires: float


_LOCK = threading.RLock()
_CONFIG: dict[str, Any] = {"state_dir": None}
_PENDING: dict[str, Pending] = {}


def configure(*, state_dir: Path | None) -> None:
    with _LOCK:
        _CONFIG["state_dir"] = Path(state_dir) if state_dir else None


def reset() -> None:
    """Tests: forget every challenge this process has issued."""
    with _LOCK:
        _PENDING.clear()


# ------------------------------------------------------------------ encodings

def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(text: Any, *, field: str = "a field") -> bytes:
    if not isinstance(text, str) or not text or len(text) > MAX_FIELD:
        raise PasskeyRefused(f"the browser sent {field} in a shape a passkey never has")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError):
        raise PasskeyRefused(f"the browser sent {field} in a shape a passkey never has") from None


def cbor_decode(data: bytes) -> tuple[Any, int]:
    """One CBOR item from the start of `data` and where it ends: the subset WebAuthn uses
    (integers, byte and text strings, arrays, maps, true, false, null), definite lengths only,
    nested at most eight deep. Anything else is refused rather than guessed at."""

    def item(pos: int, depth: int) -> tuple[Any, int]:
        if depth > 8:
            raise PasskeyRefused("the passkey's data is nested too deeply")
        if pos >= len(data):
            raise PasskeyRefused("the passkey's data ends early")
        head = data[pos]
        major, info = head >> 5, head & 0x1F
        pos += 1
        if info < 24:
            value = info
        elif info in (24, 25, 26, 27):
            size = 1 << (info - 24)
            if pos + size > len(data):
                raise PasskeyRefused("the passkey's data ends early")
            value = int.from_bytes(data[pos:pos + size], "big")
            pos += size
        else:
            raise PasskeyRefused("the passkey's data uses a form this server does not read")
        if major == 0:
            return value, pos
        if major == 1:
            return -1 - value, pos
        if major in (2, 3):
            if pos + value > len(data):
                raise PasskeyRefused("the passkey's data ends early")
            raw = data[pos:pos + value]
            pos += value
            if major == 2:
                return raw, pos
            try:
                return raw.decode("utf-8"), pos
            except UnicodeDecodeError:
                raise PasskeyRefused("the passkey's data holds broken text") from None
        if major == 4:
            if value > 64:
                raise PasskeyRefused("the passkey's data is larger than any passkey's")
            out = []
            for _ in range(value):
                element, pos = item(pos, depth + 1)
                out.append(element)
            return out, pos
        if major == 5:
            if value > 64:
                raise PasskeyRefused("the passkey's data is larger than any passkey's")
            mapping: dict[Any, Any] = {}
            for _ in range(value):
                name, pos = item(pos, depth + 1)
                if isinstance(name, (list, dict)):
                    raise PasskeyRefused("the passkey's data uses a form this server does not read")
                mapping[name], pos = item(pos, depth + 1)
            return mapping, pos
        if major == 7 and info in (20, 21, 22):
            return {20: False, 21: True, 22: None}[info], pos
        raise PasskeyRefused("the passkey's data uses a form this server does not read")

    return item(0, 0)


# ------------------------------------------------------------------ keys

def _public_key(cose: Any) -> tuple[int, Any]:
    """The algorithm and a usable public key from a COSE key, for the three algorithms offered."""
    if not isinstance(cose, dict):
        raise PasskeyRefused("the passkey's public key is missing")
    kty, alg = cose.get(1), cose.get(3)
    try:
        if alg == ES256 and kty == 2 and cose.get(-1) == 1:
            x, y = cose.get(-2), cose.get(-3)
            if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == 32 and len(y) == 32):
                raise PasskeyRefused("the passkey's public key is malformed")
            return ES256, ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), b"\x04" + x + y)
        if alg == EDDSA and kty == 1 and cose.get(-1) == 6:
            x = cose.get(-2)
            if not (isinstance(x, bytes) and len(x) == 32):
                raise PasskeyRefused("the passkey's public key is malformed")
            return EDDSA, ed25519.Ed25519PublicKey.from_public_bytes(x)
        if alg == RS256 and kty == 3:
            n, e = cose.get(-1), cose.get(-2)
            if not (isinstance(n, bytes) and isinstance(e, bytes)):
                raise PasskeyRefused("the passkey's public key is malformed")
            modulus = int.from_bytes(n, "big")
            if modulus.bit_length() < 2048:
                raise PasskeyRefused("the passkey's RSA key is too short to trust")
            return RS256, rsa.RSAPublicNumbers(int.from_bytes(e, "big"), modulus).public_key()
    except ValueError:
        raise PasskeyRefused("the passkey's public key is not a valid key") from None
    raise PasskeyRefused("the passkey uses an algorithm this server does not accept")


def _der(public_key: Any) -> str:
    return base64.b64encode(public_key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode("ascii")


def _verify(alg: int, der_b64: str, signature: bytes, signed: bytes) -> None:
    try:
        key = serialization.load_der_public_key(base64.b64decode(der_b64))
        if alg == ES256 and isinstance(key, ec.EllipticCurvePublicKey):
            key.verify(signature, signed, ec.ECDSA(hashes.SHA256()))
            return
        if alg == EDDSA and isinstance(key, ed25519.Ed25519PublicKey):
            key.verify(signature, signed)
            return
        if alg == RS256 and isinstance(key, rsa.RSAPublicKey):
            key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
            return
    except InvalidSignature:
        raise PasskeyRefused("the passkey's signature does not match", code="passkey_signature") from None
    except (ValueError, TypeError):
        raise PasskeyRefused("the registered passkey could not be read") from None
    raise PasskeyRefused("the registered passkey could not be read")


# ------------------------------------------------------------------ the record

def _path() -> Path:
    folder = _CONFIG["state_dir"]
    if folder is None:
        raise PasskeyRefused("passkeys are not set up on this server", code="passkeys_unconfigured")
    return Path(folder) / FILE_NAME


def _load() -> list[dict[str, Any]]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        raise PasskeyRefused("the passkey record on this server cannot be read", code="passkeys_unreadable") from None
    found = data.get("credentials") if isinstance(data, dict) else None
    return [c for c in found if isinstance(c, dict) and c.get("id")] if isinstance(found, list) else []


def _save(credentials: list[dict[str, Any]]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=".passkeys.", suffix=".tmp")
    temporary_path = Path(temporary)
    try:
        os.fchmod(handle, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"version": 1, "credentials": credentials}, stream, indent=1)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def registered() -> list[dict[str, Any]]:
    """The owner's passkeys as the screen shows them: never a key, only which device and when."""
    with _LOCK:
        return [{
            "id": str(c["id"]),
            "label": str(c.get("label") or "a device"),
            "created_at": str(c.get("created_at") or ""),
            "last_used_at": str(c.get("last_used_at") or ""),
        } for c in _load()]


def count() -> int:
    with _LOCK:
        return len(_load())


# ------------------------------------------------------------------ challenges

def _issue(kind: str, action: str, *, login: str, origin: str, rp_id: str, challenge: bytes | None = None) -> bytes:
    now = time.monotonic()
    for stale in [k for k, p in _PENDING.items() if p.expires <= now]:
        _PENDING.pop(stale, None)
    while len(_PENDING) >= MAX_PENDING:
        _PENDING.pop(min(_PENDING, key=lambda k: _PENDING[k].expires), None)
    # [deploy-now] A caller's own challenge (app/release/approve.py: a deploy approval's challenge binds
    # the SHA and the nonce this server just made); otherwise a random one. Held and spent the same way.
    if challenge is None:
        challenge = secrets.token_bytes(32)
    elif not isinstance(challenge, bytes) or len(challenge) < 32 or b64url(challenge) in _PENDING:
        raise PasskeyRefused("that approval could not be asked for: try again")
    _PENDING[b64url(challenge)] = Pending(kind, action, login, origin, rp_id, now + CHALLENGE_S)
    return challenge


def _client_data(raw: bytes, kind: str) -> tuple[dict[str, Any], Pending]:
    """The browser's own account of the ceremony, checked against the challenge it answers.
    The challenge is spent here, whatever happens after: an approval is good once."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise PasskeyRefused("the browser's account of the passkey prompt cannot be read") from None
    if not isinstance(data, dict):
        raise PasskeyRefused("the browser's account of the passkey prompt cannot be read")
    expected_type = "webauthn.create" if kind == "create" else "webauthn.get"
    if data.get("type") != expected_type:
        raise PasskeyRefused("the passkey answered a different kind of prompt")
    pending = _PENDING.pop(str(data.get("challenge") or ""), None)
    if pending is None or pending.kind != kind:
        raise PasskeyRefused("that approval was not asked for here, or was already used: try again",
                             code="passkey_stale")
    if pending.expires <= time.monotonic():
        raise PasskeyRefused("that approval took too long: try again", code="passkey_stale")
    if data.get("crossOrigin") is True:
        raise PasskeyRefused("the passkey prompt came from inside another site")
    if data.get("origin") != pending.origin:
        raise PasskeyRefused("the passkey prompt did not come from this CLIVE")
    return data, pending


def _auth_data(raw: bytes, rp_id: str) -> tuple[int, int]:
    if len(raw) < 37:
        raise PasskeyRefused("the passkey's data is too short")
    if raw[:32] != hashlib.sha256(rp_id.encode("utf-8")).digest():
        raise PasskeyRefused("that passkey was made for another site")
    flags = raw[32]
    if not flags & FLAG_UP:
        raise PasskeyRefused("the passkey did not see you there")
    if not flags & FLAG_UV:
        raise PasskeyRefused("the passkey did not check it was you (Face ID, a fingerprint or the device PIN)",
                             code="passkey_unverified")
    return flags, int.from_bytes(raw[33:37], "big")


def _user_id(login: str) -> bytes:
    return hashlib.sha256(f"clive-owner:{login}".encode()).digest()[:16]


# ------------------------------------------------------------------ registration

def begin_registration(*, login: str, origin: str, rp_id: str, approved: bool) -> dict[str, Any]:
    """The options for navigator.credentials.create(). Open to the owner's device when no passkey
    is registered yet; otherwise only once an existing passkey has approved it (`approved`)."""
    with _LOCK:
        existing = _load()
        if existing and not approved:
            raise PasskeyRefused("adding another passkey needs one you already have to approve it",
                                 code="passkey_approval_needed")
        if len(existing) >= MAX_PASSKEYS:
            raise PasskeyRefused(f"there are already {MAX_PASSKEYS} passkeys: remove one first")
        # The first passkey and a later one are different actions, so a prompt opened while there
        # was none cannot be finished as a second passkey once one exists (finish_registration).
        action = "passkey:add" if existing else "passkey:first"
        challenge = _issue("create", action, login=login, origin=origin, rp_id=rp_id)
    return {
        "challenge": b64url(challenge),
        "rp": {"id": rp_id, "name": RP_NAME},
        "user": {"id": b64url(_user_id(login)), "name": login, "displayName": "CLIVE owner"},
        "pubKeyCredParams": [{"type": "public-key", "alg": alg} for alg in SUPPORTED],
        "authenticatorSelection": {"residentKey": "preferred", "userVerification": "required"},
        "attestation": "none",
        "excludeCredentials": [{"type": "public-key", "id": c["id"]} for c in existing],
        "timeout": TIMEOUT_MS,
    }


def finish_registration(credential: Any, *, login: str, origin: str, label: str) -> dict[str, Any]:
    """Verify what navigator.credentials.create() returned and keep the new passkey's public key."""
    if not isinstance(credential, dict) or not isinstance(credential.get("response"), dict):
        raise PasskeyRefused("the browser did not send a passkey")
    response = credential["response"]
    client_raw = unb64url(response.get("clientDataJSON"), field="the prompt's account")
    with _LOCK:
        _, pending = _client_data(client_raw, "create")
        if pending.login != login or pending.origin != origin:
            raise PasskeyRefused("that passkey prompt was opened by someone else")
        raw = unb64url(response.get("attestationObject"), field="the passkey")
        attestation, end = cbor_decode(raw)
        if end != len(raw) or not isinstance(attestation, dict) or not isinstance(attestation.get("authData"), bytes):
            raise PasskeyRefused("the passkey's data is missing or malformed")
        auth = attestation["authData"]
        flags, sign_count = _auth_data(auth, pending.rp_id)
        if not flags & FLAG_AT or len(auth) < 55:
            raise PasskeyRefused("the passkey did not include its key")
        id_length = int.from_bytes(auth[53:55], "big")
        if id_length < 16 or id_length > 1023 or 55 + id_length > len(auth):
            raise PasskeyRefused("the passkey's identity is malformed")
        credential_id = auth[55:55 + id_length]
        cose, used = cbor_decode(auth[55 + id_length:])
        if not flags & FLAG_ED and 55 + id_length + used != len(auth):
            raise PasskeyRefused("the passkey's data has something extra on the end")
        alg, public_key = _public_key(cose)
        sent = credential.get("rawId") or credential.get("id")
        if sent is not None and unb64url(sent, field="the passkey's identity") != credential_id:
            raise PasskeyRefused("the passkey's identity does not match its data")
        existing = _load()
        identity = b64url(credential_id)
        if any(c["id"] == identity for c in existing):
            raise PasskeyRefused("that passkey is already registered")
        if existing and pending.action != "passkey:add":
            raise PasskeyRefused("adding another passkey needs one you already have to approve it",
                                 code="passkey_approval_needed")
        record = {
            "id": identity, "alg": alg, "public_key": _der(public_key), "sign_count": sign_count,
            "login": login, "label": str(label or "a device")[:40], "rp_id": pending.rp_id,
            "origin": pending.origin, "created_at": _now(), "last_used_at": "",
        }
        _save([*existing, record])
    return {"id": identity, "label": record["label"], "created_at": record["created_at"], "last_used_at": ""}


# ------------------------------------------------------------------ approval

def begin_approval(action: str, *, login: str, origin: str, rp_id: str, challenge: bytes | None = None) -> dict[str, Any]:
    """The options for navigator.credentials.get(): a challenge good for this one action. `challenge`:
    the caller's own (at least 32 bytes, made fresh by this server for this action), instead of a random one."""
    with _LOCK:
        existing = [c for c in _load() if c.get("rp_id") == rp_id]
        if not existing:
            raise PasskeyRefused("set up a passkey on this screen first: every change asks for it",
                                 code="passkey_none")
        challenge = _issue("get", action, login=login, origin=origin, rp_id=rp_id, challenge=challenge)
    return {
        "challenge": b64url(challenge),
        "rpId": rp_id,
        "allowCredentials": [{"type": "public-key", "id": c["id"]} for c in existing],
        "userVerification": "required",
        "timeout": TIMEOUT_MS,
    }


def verify_approval(assertion: Any, action: str, *, login: str, origin: str) -> dict[str, Any]:
    """Verify what navigator.credentials.get() returned, for exactly `action`. Returns the passkey
    used (without its key); raises PasskeyRefused, having spent the challenge, otherwise."""
    if not isinstance(assertion, dict) or not isinstance(assertion.get("response"), dict):
        raise PasskeyRefused("this change needs your passkey", code="passkey_missing")
    response = assertion["response"]
    client_raw = unb64url(response.get("clientDataJSON"), field="the prompt's account")
    auth = unb64url(response.get("authenticatorData"), field="the passkey's data")
    signature = unb64url(response.get("signature"), field="the passkey's signature")
    identity = b64url(unb64url(assertion.get("rawId") or assertion.get("id"), field="the passkey's identity"))
    with _LOCK:
        _, pending = _client_data(client_raw, "get")
        if pending.action != action:
            raise PasskeyRefused("that approval was for something else: try again", code="passkey_stale")
        if pending.login != login or pending.origin != origin:
            raise PasskeyRefused("that approval was opened by someone else")
        credentials = _load()
        record = next((c for c in credentials if c["id"] == identity), None)
        if record is None or record.get("rp_id") != pending.rp_id:
            raise PasskeyRefused("that passkey is not one registered here", code="passkey_unknown")
        _, sign_count = _auth_data(auth, pending.rp_id)
        _verify(int(record.get("alg") or 0), str(record.get("public_key") or ""), signature,
                auth + hashlib.sha256(client_raw).digest())
        stored = int(record.get("sign_count") or 0)
        if (stored or sign_count) and sign_count <= stored:
            raise PasskeyRefused("that passkey's counter went backwards, which a copied passkey does: "
                                 "remove it and register it again", code="passkey_counter")
        record["sign_count"] = sign_count
        record["last_used_at"] = _now()
        _save(credentials)
    return {"id": record["id"], "label": record.get("label") or "a device"}


def remove(credential_id: str) -> bool:
    """Forget one passkey (the route has had another, or this one, approve it)."""
    with _LOCK:
        credentials = _load()
        kept = [c for c in credentials if c["id"] != credential_id]
        if len(kept) == len(credentials):
            return False
        _save(kept)
        return True
