"""Fake credentials for tests: every one is assembled here, at runtime, and nowhere else.

The rule (owner decision of 2026-09-25, "rule B", in
docs/product-memory/OWNER_DECISIONS_2026-09-25.md): fake credentials in tests are assembled at
runtime through one shared test helper, and they are never listed in the secret-scan baseline.
This module is that helper. Why it exists:

- The repository is public. A literal that looks like a real key reads, to anyone and to any
  crawler, exactly like a leaked one, and a tree full of them teaches its readers to shrug at
  key-shaped strings.
- The acceptance gate runs gitleaks over the whole tree with its default rules. A key-shaped
  literal in a test is a finding, and the only ways to quiet one are a baseline entry (ruled out
  for test fixtures by rule B) or a weaker scan (ruled out for everything).
- The Knowledge Digester's quarantine scanner (app/digest/scan.py) reads CLIVE like any other
  artifact. A key-shaped literal in a test makes CLIVE report CLIVE as carrying a credential,
  and the scanner would be right.

So no line of source holds a credential's prefix and its body together. Each function below
joins a prefix, written in pieces so this file never spells it whole, to a body generated from
a seed. Values are deterministic: the same seed gives the same value on every run and every
machine (the generator is FNV-1a over the seed feeding a 64-bit LCG, not ``random``), so a test
stays reproducible; a test that needs two different keys of one kind asks with two seeds.

What counts as a fake credential: any value a test uses in place of a credential that could pass
for a real one (a vendor prefix, a JWT, a PEM block, an opaque token- or password-like string),
or that either scanner reports. A plain word or phrase that names itself as a stand-in
("must-not-leak", "from-systemd", "anything at all", "supersecret"), or a value too short to be
anything ("x", "abc"), does not look like a secret and may stay as written.
tests/test_fake_credentials.py fails when a credential-shaped literal appears anywhere in the
tests. Where a test needs a credential on disk (a scanner test proving the scanner finds a key in
a file), it writes a value from here into a temporary file at runtime.

The Swift tests of mac/CrooksControl follow the same rule through their own helper,
Tests/CrooksControlCoreTests/FakeCredentials.swift, which uses the same approach.
"""

from __future__ import annotations

import base64
import json
import string
from collections.abc import Iterator, Sequence

UPPER = string.ascii_uppercase
LOWER = string.ascii_lowercase
DIGITS = string.digits
ALNUM = UPPER + LOWER + DIGITS
LOWER_ALNUM = LOWER + DIGITS
HEX = DIGITS + "abcdef"
BASE32 = UPPER + "234567"  # AWS access key ids use this alphabet
BASE64 = ALNUM + "+/"

_MASK = (1 << 64) - 1
_CLASSES = (str.isupper, str.islower, str.isdigit)


def _draws(seed: str) -> Iterator[int]:
    state = 0xCBF29CE484222325  # FNV-1a offset basis
    for byte in seed.encode("utf-8"):
        state = ((state ^ byte) * 0x100000001B3) & _MASK
    while True:
        state = (state * 6364136223846793005 + 1442695040888963407) & _MASK
        yield state >> 33


def body(seed: str, length: int, alphabet: str = ALNUM) -> str:
    """``length`` characters from ``alphabet``, fixed by ``seed``.

    When the alphabet mixes upper case, lower case and digits, so does every body long enough to
    hold one of each, as real tokens do: redactors that look for a mixed-case run must see one.
    """
    if length < 0 or not alphabet:
        raise ValueError("a body needs a length of zero or more and a non-empty alphabet")
    classes = [test for test in _CLASSES if any(test(c) for c in alphabet)]
    for attempt in range(1000):
        draws = _draws(f"{seed}#{attempt}" if attempt else seed)
        out = "".join(alphabet[next(draws) % len(alphabet)] for _ in range(length))
        if length < len(classes) or all(any(test(c) for c in out) for test in classes):
            return out
    return out


def _seed(shape: str, seed: str) -> str:
    return f"{shape}:{seed}"


# --- source hosts and model providers --------------------------------------------------------


def github_token(seed: str = "", *, kind: str = "p", length: int = 36, alphabet: str = ALNUM) -> str:
    """A classic GitHub token: ``kind`` is p (personal), o (OAuth), u (user), s (app installation,
    the one in an ``x-access-token`` URL) or r (refresh)."""
    return "gh" + kind + "_" + body(_seed("github-" + kind, seed), length, alphabet)


def github_fine_grained_token(seed: str = "") -> str:
    """A fine-grained GitHub personal access token: 22 characters, an underscore, 59 more."""
    return "github" + "_pat_" + body(_seed("github-pat-id", seed), 22) + "_" + body(_seed("github-pat", seed), 59)


def anthropic_key(seed: str = "", *, kind: str = "api03", length: int = 93) -> str:
    """An Anthropic credential: ``api03`` for an API key, ``oat01`` for a Claude Code OAuth token.
    Like the real ones, the body ends in AA."""
    return "sk" + "-ant-" + kind + "-" + body(_seed("anthropic-" + kind, seed), length) + "AA"


def openai_key(seed: str = "", *, kind: str = "proj", length: int = 48, alphabet: str = ALNUM) -> str:
    """An OpenAI key: ``kind`` proj, svcacct or admin; an empty ``kind`` is the older bare form."""
    middle = kind + "-" if kind else ""
    return "sk" + "-" + middle + body(_seed("openai-" + kind, seed), length, alphabet)


# --- the shop and its services ---------------------------------------------------------------


def shopify_token(seed: str = "", *, kind: str = "at", length: int = 32) -> str:
    """A Shopify token in lower-case hex: ``kind`` at (Admin API), ca (custom app), pa (private
    app) or ss (shared secret)."""
    return "shp" + kind + "_" + body(_seed("shopify-" + kind, seed), length, HEX)


def elevenlabs_key(seed: str = "") -> str:
    """An ElevenLabs API key: an underscore prefix and 48 lower-case hex characters."""
    return "sk" + "_" + body(_seed("elevenlabs", seed), 48, HEX)


def google_oauth_token(seed: str = "", *, length: int = 64) -> str:
    """A Google OAuth access token, as Gmail's client holds one."""
    return "ya" + "29." + body(_seed("google-oauth", seed), length)


def google_api_key(seed: str = "") -> str:
    """A Google API key: a fixed prefix and exactly 35 characters."""
    return "AI" + "za" + body(_seed("google-api", seed), 35)


def stripe_key(seed: str = "", *, mode: str = "live", length: int = 24) -> str:
    """A Stripe secret key, ``mode`` live or test."""
    return "sk" + "_" + mode + "_" + body(_seed("stripe-" + mode, seed), length)


def slack_token(seed: str = "", *, kind: str = "b") -> str:
    """A Slack token: ``kind`` b (bot) or p (user), then two numeric ids and a secret part."""
    return ("xo" + "x" + kind + "-" + body(_seed("slack-team", seed), 10, DIGITS) + "-"
            + body(_seed("slack-user", seed), 12, DIGITS) + "-" + body(_seed("slack-" + kind, seed), 24))


def gitlab_token(seed: str = "", *, length: int = 20) -> str:
    """A GitLab personal access token."""
    return "gl" + "pat-" + body(_seed("gitlab", seed), length)


def telegram_bot_token(seed: str = "") -> str:
    """A Telegram bot token: a numeric bot id, a colon, and 35 characters beginning AA."""
    return body(_seed("telegram-id", seed), 9, DIGITS) + ":" + "AA" + body(_seed("telegram", seed), 33)


def tailscale_auth_key(seed: str = "") -> str:
    """A Tailscale auth key, as the tablet route is joined with."""
    return "tskey" + "-auth-" + body(_seed("tailscale-id", seed), 12) + "-" + body(_seed("tailscale", seed), 32)


def aws_access_key_id(seed: str = "") -> str:
    """An AWS access key id: a fixed prefix and 16 characters of base32."""
    return "AK" + "IA" + body(_seed("aws-id", seed), 16, BASE32)


def aws_secret_access_key(seed: str = "") -> str:
    """An AWS secret access key: 40 characters of base64."""
    return body(_seed("aws-secret", seed), 40, BASE64)


# --- shapes that are not one vendor's ---------------------------------------------------------


def bearer_token(seed: str = "", *, length: int = 40) -> str:
    """An opaque bearer token, the part after ``Bearer `` in an Authorization header."""
    return body(_seed("bearer", seed), length)


def password(seed: str = "", *, length: int = 16) -> str:
    """A password as a person would have set one: nothing in it says it is a placeholder."""
    return body(_seed("password", seed), length)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def jwt(seed: str = "", *, claims: dict | None = None) -> str:
    """A signed-looking JSON web token: a real HS256 header, ``claims`` (or a subject and times
    fixed by the seed) as the payload, and a signature-shaped third part. Nothing verifies it."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = claims if claims is not None else {
        "sub": "user-" + body(_seed("jwt-sub", seed), 12, LOWER_ALNUM), "iat": 1760000000, "exp": 1760003600,
    }
    compact = {"separators": (",", ":"), "sort_keys": False}
    return ".".join((
        _b64url(json.dumps(header, **compact).encode()),
        _b64url(json.dumps(payload, **compact).encode()),
        body(_seed("jwt-signature", seed), 43),
    ))


def pem_line(seed: str = "", *, length: int = 64) -> str:
    """One base64 line of a PEM body."""
    return body(_seed("pem-line", seed), length)


def private_key_pem(seed: str = "", *, kind: str = "RSA", lines: Sequence[str] | None = None) -> str:
    """A PEM private-key block with no trailing newline. ``kind`` is RSA, EC, OPENSSH, or empty for
    PKCS #8; ``lines`` replaces the four generated body lines when a test needs to know them."""
    label = (kind + " " if kind else "") + "PRIVATE" + " " + "KEY"
    rows = list(lines) if lines is not None else [pem_line(f"{seed}/{index}") for index in range(4)]
    dashes = "-" * 5
    return "\n".join([dashes + "BEGIN " + label + dashes, *rows, dashes + "END " + label + dashes])


def credential_url(secret: str, *, user: str = "x-access-token", scheme: str = "https",
                   host: str = "example.invalid", path: str = "/r.git") -> str:
    """A URL carrying ``secret`` as its password, as git prints a remote that holds a token."""
    return f"{scheme}://{user}:{secret}@{host}{path}"
