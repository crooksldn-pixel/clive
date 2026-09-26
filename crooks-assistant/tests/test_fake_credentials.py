"""Owner rule B, enforced: no fake credential is written into the tests as a literal.

Fake credentials in tests are assembled at runtime by one shared helper, tests/fake_credentials.py
(the Swift tests have its counterpart, FakeCredentials.swift), and are never listed in the
secret-scan baseline (docs/product-memory/OWNER_DECISIONS_2026-09-25.md). The guard below reads
every test source and fixture for a credential's prefix followed by a plausible body, the way a
leaked key would appear, and fails naming the file, the line and the shape. Like the digester, it
never quotes what it found.

It is deliberately narrower than gitleaks or the digester: a bare prefix used as a needle
(``"shpat_" not in out``) and the helper's split pieces (``"gh" + kind + "_"``) are not
credentials and do not fire. A generic password has no shape to look for, so passwords are
covered by the scanners, not by this guard.
"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import pytest

from tests import fake_credentials as fake

PROJECT = Path(__file__).resolve().parent.parent
REPO = PROJECT.parent
HELPERS = (
    PROJECT / "tests" / "fake_credentials.py",
    PROJECT / "mac" / "CrooksControl" / "Tests" / "CrooksControlCoreTests" / "FakeCredentials.swift",
)

_START = r"(?<![A-Za-z0-9])"
SHAPES = {
    name: re.compile(pattern)
    for name, pattern in {
        "an Anthropic key": _START + r"sk-ant-[A-Za-z0-9_-]{8,}",
        "an OpenAI key": _START + r"sk-(?!ant-)[A-Za-z0-9_-]{16,}",
        "an sk_ key (ElevenLabs, Stripe)": _START + r"[sr]k_[A-Za-z0-9_]{16,}",
        "a GitHub token": _START + r"(?:gh[pousr]_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,})",
        "a Shopify token": _START + r"shp(?:at|ca|pa|ss)_[A-Za-z0-9]{6,}",
        "a Slack token": _START + r"xox[abposr]-[A-Za-z0-9-]{8,}",
        "a Google OAuth token": _START + r"ya29\.[A-Za-z0-9_-]{8,}",
        "a Google refresh token": _START + r"1//0[A-Za-z0-9_-]{8,}",
        "a Google API key": _START + r"AIza[A-Za-z0-9_-]{8,}",
        "a Google client secret": _START + r"GOCSPX-[A-Za-z0-9_-]{8,}",
        "an AWS access key id": _START + r"(?:AKIA|ASIA|ABIA|ACCA)[A-Z0-9]{12,}",
        "an AWS secret access key": r"(?i)aws.{0,20}secret.{0,20}[:=]\s*[\"']?[A-Za-z0-9/+=]{40}",
        "a GitLab token": _START + r"glpat-[A-Za-z0-9_-]{8,}",
        "a Tailscale key": _START + r"tskey-(?:auth|api|client)-[A-Za-z0-9-]{8,}",
        "a Telegram bot token": _START + r"\d{8,10}:AA[A-Za-z0-9_-]{30,}",
        "a JSON web token": _START + r"eyJ[A-Za-z0-9_-]{8,}",
        "a private key block": r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY",
        "a bearer token": r"(?i)" + _START + r"bearer\s+[A-Za-z0-9._~+/-]{16,}",
        "a password in a URL": r"://[^\s/@:'\"{}()<>]+:[^\s/@'\"{}()<>]{6,}@",
    }.items()
}


def credential_literals(text: str) -> list[tuple[int, str]]:
    """(line, shape) for every credential-shaped literal in ``text``. The value is not returned."""
    found = set()
    for name, pattern in SHAPES.items():
        for match in pattern.finditer(text):
            found.add((text.count("\n", 0, match.start()) + 1, name))
    return sorted(found)


def literals_in(path: Path) -> list[tuple[int, str]]:
    """``credential_literals`` for a file; a binary file (an image, an archive) has none."""
    data = path.read_bytes()
    return [] if b"\0" in data[:8192] else credential_literals(data.decode("utf-8", "replace"))


def guarded_files() -> list[Path]:
    """Every test source and fixture in the repository, the shared helpers apart."""
    roots = [PROJECT / "tests", PROJECT / "mac" / "CrooksControl" / "Tests",
             *sorted((PROJECT / "android").glob("*/src/test"))]
    return [path for root in roots for path in sorted(root.rglob("*"))
            if path.is_file() and "__pycache__" not in path.parts and path not in HELPERS]


def test_no_test_source_holds_a_credential_shaped_literal():
    files = guarded_files()
    assert len(files) > 150, "the guard must be reading the test suite, not an empty directory"
    offences = [f"{path.relative_to(REPO)}:{line}: {shape}" for path in files for line, shape in literals_in(path)]
    assert not offences, (
        "A fake credential is written into the tests as a literal. Owner rule B (2026-09-25): "
        "build it at runtime with tests/fake_credentials.py (FakeCredentials.swift for Swift) "
        "instead, and do not baseline it.\n" + "\n".join(offences)
    )


def _shaped() -> list[tuple[str, str]]:
    """(name, value) for every helper output that has a shape this guard knows."""
    return [
        ("github_token", fake.github_token()),
        ("github_token/s", fake.github_token(kind="s")),
        ("github_fine_grained_token", fake.github_fine_grained_token()),
        ("anthropic_key", fake.anthropic_key()),
        ("anthropic_key/oat01", fake.anthropic_key(kind="oat01")),
        ("openai_key", fake.openai_key()),
        ("openai_key/bare", fake.openai_key(kind="")),
        ("shopify_token", fake.shopify_token()),
        ("elevenlabs_key", fake.elevenlabs_key()),
        ("google_oauth_token", fake.google_oauth_token()),
        ("google_api_key", fake.google_api_key()),
        ("stripe_key", fake.stripe_key()),
        ("slack_token", fake.slack_token()),
        ("gitlab_token", fake.gitlab_token()),
        ("telegram_bot_token", fake.telegram_bot_token()),
        ("tailscale_auth_key", fake.tailscale_auth_key()),
        ("aws_access_key_id", fake.aws_access_key_id()),
        ("aws_secret_access_key", "aws_secret_access_key = " + fake.aws_secret_access_key()),
        ("jwt", fake.jwt()),
        ("private_key_pem", fake.private_key_pem()),
        ("bearer_token", "Authorization: Bearer " + fake.bearer_token()),
        ("credential_url", fake.credential_url(fake.password())),
    ]


@pytest.mark.parametrize(("name", "value"), _shaped(), ids=[name for name, _ in _shaped()])
def test_the_guard_would_catch_every_shape_the_helper_makes(name, value, tmp_path):
    """Pasting a helper value into a test as a literal is exactly what the guard is for. The
    literal is written to a temporary file at runtime, never into this source."""
    pasted = tmp_path / "test_pasted.py"
    pasted.write_text(f'VALUE = "{value}"\n', encoding="utf-8")
    assert literals_in(pasted), name


@pytest.mark.parametrize("helper", HELPERS, ids=lambda path: path.name)
def test_the_guard_does_not_fire_on_the_helpers_own_pieces(helper):
    """The helpers spell every prefix in pieces, so the guard (like gitleaks and the digester)
    finds nothing in them; the exclusion above is for their prose, not their code."""
    assert literals_in(helper) == []


def test_bare_prefixes_used_as_needles_do_not_fire():
    for needle in ('assert "shpat_" not in out', 'assert "sk-ant-api03" not in out', 'b"github_pat_"',
                   'for forbidden in ("Bearer", "xi-api-key")', '.sk-row{width:82%}',
                   'f"Bearer {token}"', 'credential_url(token, user="x", host="github.com")'):
        assert credential_literals(needle) == [], needle


def test_values_are_deterministic_and_seeds_keep_them_apart():
    assert fake.github_token("a") == fake.github_token("a")
    assert fake.github_token("a") != fake.github_token("b")
    assert fake.github_token("a") != fake.github_token("a", kind="s")
    assert fake.body("x", 40) == fake.body("x", 40) and len(fake.body("x", 40)) == 40


@pytest.mark.parametrize("length", [3, 8, 24, 64])
def test_a_mixed_alphabet_body_mixes_its_classes(length):
    """Real tokens mix upper case, lower case and digits, and redactors that look for a mixed
    run rely on it; a body long enough to hold one of each always does."""
    for seed in range(200):
        value = fake.body(str(seed), length)
        assert any(c.isupper() for c in value) and any(c.islower() for c in value)
        assert any(c.isdigit() for c in value)


def test_the_shapes_have_the_lengths_their_vendors_use():
    assert len(fake.github_token()) == 4 + 36
    assert len(fake.shopify_token()) == 6 + 32 and set(fake.shopify_token()[6:]) <= set(fake.HEX)
    assert len(fake.elevenlabs_key()) == 3 + 48
    assert len(fake.google_api_key()) == 4 + 35
    assert len(fake.aws_access_key_id()) == 20 and len(fake.aws_secret_access_key()) == 40
    header, payload, signature = fake.jwt().split(".")
    assert json.loads(_unpad(header)) == {"alg": "HS256", "typ": "JWT"} and "sub" in json.loads(_unpad(payload))
    block = fake.private_key_pem(lines=["abc", "def"]).splitlines()
    assert block[1:3] == ["abc", "def"] and block[0].endswith("PRIVATE KEY-----") and block[0].startswith("-----")


def _unpad(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def test_no_test_fixture_is_listed_in_the_secret_scan_baseline():
    """Rule B: a fake credential is fixed in the test, through the helper, never excused by a
    baseline fingerprint. With test_every_baselined_finding_is_a_test_fixture (which keeps
    application code out of the baseline too) this leaves the baseline empty; an entry needs an
    owner decision that changes one of the two."""
    baseline = json.loads((REPO / ".gitleaks-baseline.json").read_text(encoding="utf-8"))
    in_tests = [entry.get("File", "") for entry in baseline
                if "/tests/" in entry.get("File", "") or "/Tests/" in entry.get("File", "")]
    assert in_tests == []
