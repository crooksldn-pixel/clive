"""A stand-in authenticator for the passkey tests: what a phone's Face ID prompt and the browser
hand back to CLIVE, built here with real keys made for the test and thrown away after.

It answers the options app/connections/passkeys.py issues exactly as navigator.credentials
create() and get() would, as the JSON the Connections screen sends (base64url fields), and can be
told to misbehave in each way a real one might: no user verification, another site, another key,
a counter that goes backwards.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

ES256, EDDSA, RS256 = -7, -8, -257
ORIGIN = "https://clive.tailnet-test.ts.net"
RP_ID = "clive.tailnet-test.ts.net"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def cbor(value: Any) -> bytes:
    """The CBOR WebAuthn uses: integers, byte and text strings, arrays and maps."""

    def head(major: int, n: int) -> bytes:
        if n < 24:
            return bytes([major << 5 | n])
        for info, size in ((24, 1), (25, 2), (26, 4), (27, 8)):
            if n < 1 << (8 * size):
                return bytes([major << 5 | info]) + n.to_bytes(size, "big")
        raise ValueError(n)

    if isinstance(value, bool):
        return bytes([0xF5 if value else 0xF4])
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return head(3, len(raw)) + raw
    if isinstance(value, list):
        return head(4, len(value)) + b"".join(cbor(v) for v in value)
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value.items())
    raise TypeError(type(value))


class Authenticator:
    """One passkey on one device."""

    def __init__(self, alg: int = ES256, *, origin: str = ORIGIN, rp_id: str = RP_ID) -> None:
        self.alg = alg
        self.origin = origin
        self.rp_id = rp_id
        self.counter = 0
        self.uv = True
        self.up = True
        self.credential_id = os.urandom(32)
        if alg == ES256:
            self._private = ec.generate_private_key(ec.SECP256R1())
        elif alg == EDDSA:
            self._private = ed25519.Ed25519PrivateKey.generate()
        elif alg == RS256:
            self._private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        else:
            raise ValueError(alg)

    # -------------------------------------------------------------- the pieces

    def cose(self) -> dict[int, Any]:
        public = self._private.public_key()
        if self.alg == ES256:
            point = public.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
            return {1: 2, 3: ES256, -1: 1, -2: point[1:33], -3: point[33:65]}
        if self.alg == EDDSA:
            return {1: 1, 3: EDDSA, -1: 6, -2: public.public_bytes(Encoding.Raw, PublicFormat.Raw)}
        numbers = public.public_numbers()
        return {1: 3, 3: RS256, -1: numbers.n.to_bytes(256, "big"), -2: numbers.e.to_bytes(3, "big")}

    def _flags(self, *, attested: bool) -> int:
        return (0x01 if self.up else 0) | (0x04 if self.uv else 0) | (0x40 if attested else 0)

    def _rp_hash(self) -> bytes:
        return hashlib.sha256(self.rp_id.encode()).digest()

    def _client(self, kind: str, challenge: str, **extra: Any) -> bytes:
        return json.dumps({"type": kind, "challenge": challenge, "origin": self.origin,
                           "crossOrigin": False, **extra}).encode()

    def sign(self, data: bytes) -> bytes:
        if self.alg == ES256:
            return self._private.sign(data, ec.ECDSA(hashes.SHA256()))
        if self.alg == EDDSA:
            return self._private.sign(data)
        return self._private.sign(data, padding.PKCS1v15(), hashes.SHA256())

    # -------------------------------------------------------------- the two prompts

    def create(self, options: dict[str, Any], **client_extra: Any) -> dict[str, Any]:
        auth = (self._rp_hash() + bytes([self._flags(attested=True)]) + self.counter.to_bytes(4, "big")
                + bytes(16) + len(self.credential_id).to_bytes(2, "big") + self.credential_id + cbor(self.cose()))
        attestation = cbor({"fmt": "none", "attStmt": {}, "authData": auth})
        client = self._client("webauthn.create", options["challenge"], **client_extra)
        identity = b64url(self.credential_id)
        return {"id": identity, "rawId": identity, "type": "public-key",
                "response": {"clientDataJSON": b64url(client), "attestationObject": b64url(attestation)}}

    def get(self, options: dict[str, Any], *, count: int | None = None, **client_extra: Any) -> dict[str, Any]:
        self.counter = self.counter if count is None else count
        auth = self._rp_hash() + bytes([self._flags(attested=False)]) + self.counter.to_bytes(4, "big")
        client = self._client("webauthn.get", options["challenge"], **client_extra)
        signature = self.sign(auth + hashlib.sha256(client).digest())
        identity = b64url(self.credential_id)
        return {"id": identity, "rawId": identity, "type": "public-key",
                "response": {"clientDataJSON": b64url(client), "authenticatorData": b64url(auth),
                             "signature": b64url(signature), "userHandle": None}}
