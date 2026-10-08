"""The GitHub App token helper (DEC-071 ruling 13, DEC-076) against a local stand-in for GitHub's API.

Only GitHub is replaced, by an HTTP server on 127.0.0.1 that answers the documented
``POST /app/installations/{id}/access_tokens`` and checks the App's JWT with the public half of a key made for the
test. The JWT signing, the key-file rule, the narrowing, the cache, the credential-helper protocol through real
``git`` and the loop's own GitHub acceptance credential (``git_remote_token``) are the real ones.
"""

from __future__ import annotations

import base64
import io
import json
import os
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.orchestrator.github_acceptance import git_remote_token
from tests.fake_credentials import github_token

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "github_app_token.py"
sys.path.insert(0, str(SCRIPT.parent))
import github_app_token as helper  # noqa: E402

APP_ID = "424242"
INSTALLATION = "777"


def _unb64(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


class FakeGitHub:
    """Answers the installation-token endpoint; refuses any JWT the App's public key does not verify."""

    def __init__(self, public_key) -> None:
        self.requests: list[dict] = []
        self.status = 201
        self.issued = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):  # noqa: N802
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                jwt = self.headers["Authorization"].removeprefix("Bearer ")
                header, claims, signature = jwt.split(".")
                public_key.verify(_unb64(signature), f"{header}.{claims}".encode(), padding.PKCS1v15(),
                                  hashes.SHA256())
                outer.requests.append({"path": self.path, "body": body, "header": json.loads(_unb64(header)),
                                       "claims": json.loads(_unb64(claims)), "jwt": jwt,
                                       "api_version": self.headers["X-GitHub-Api-Version"]})
                if outer.status != 201:
                    self.send_response(outer.status)
                    self.end_headers()
                    self.wfile.write(json.dumps({"message": "Bad credentials"}).encode())
                    return
                outer.issued += 1
                answer = {"token": github_token(f"installation-{outer.issued}", kind="s"),
                          "expires_at": (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")}
                self.send_response(201)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(answer).encode())

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.api = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def token(self, n: int) -> str:
        return github_token(f"installation-{n}", kind="s")


@pytest.fixture
def github(monkeypatch, tmp_path):
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
        monkeypatch.delenv(name, raising=False)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    path = tmp_path / "keys" / "loop-app.pem"
    path.parent.mkdir()
    path.write_bytes(pem)
    path.chmod(0o600)
    fake = FakeGitHub(key.public_key())
    fake.key_file = path
    fake.pem = pem
    yield fake
    fake.server.shutdown()


def run(github: FakeGitHub, *args: str, stdin: str = "", cache: Path | None = None) -> tuple[int, str]:
    out = io.StringIO()
    argv = ["--app-id", APP_ID, "--installation-id", INSTALLATION, "--key-file", str(github.key_file),
            "--api", github.api, *(["--cache-dir", str(cache)] if cache else []), *args]
    return helper.main(argv, stdin=io.StringIO(stdin), stdout=out), out.getvalue()


def test_a_token_is_minted_with_the_apps_own_jwt_and_narrowed_to_clive_and_the_named_permissions(github):
    code, out = run(github, "token")
    assert code == 0 and out == github.token(1) + "\n"
    [request] = github.requests
    assert request["path"] == f"/app/installations/{INSTALLATION}/access_tokens"
    assert request["body"] == {"repositories": ["clive"],
                               "permissions": {"contents": "write", "pull_requests": "write", "actions": "read"}}
    assert request["header"] == {"alg": "RS256", "typ": "JWT"} and request["claims"]["iss"] == APP_ID
    assert 0 < request["claims"]["exp"] - request["claims"]["iat"] <= 600 and request["api_version"] == "2022-11-28"
    code, _ = run(github, "--permission", "contents=write", "--permission", "workflows=write", "token")
    assert github.requests[-1]["body"]["permissions"] == {"contents": "write", "workflows": "write"}


def test_as_a_git_credential_helper_it_answers_only_get_for_github_and_stores_nothing(github):
    code, out = run(github, "credential", "get", stdin="protocol=https\nhost=github.com\npath=crooksldn-pixel/clive\n\n")
    assert code == 0 and out == f"username=x-access-token\npassword={github.token(1)}\n"
    for operation, stdin in (("get", "protocol=https\nhost=gitlab.com\n\n"), ("get", "protocol=http\nhost=github.com\n"),
                             ("store", "protocol=https\nhost=github.com\nusername=x\npassword=y\n"),
                             ("erase", "protocol=https\nhost=github.com\n")):
        assert run(github, "credential", operation, stdin=stdin) == (0, "")
    assert len(github.requests) == 1


def test_the_cache_is_private_reused_while_fresh_and_never_across_permissions(github, tmp_path):
    cache = tmp_path / "cache"
    assert run(github, "token", cache=cache)[1] == run(github, "token", cache=cache)[1] == github.token(1) + "\n"
    assert len(github.requests) == 1
    assert cache.stat().st_mode & 0o777 == 0o700
    assert (cache / f"installation-{INSTALLATION}.json").stat().st_mode & 0o777 == 0o600
    assert run(github, "--permission", "contents=read", "token", cache=cache)[1] == github.token(2) + "\n"
    cache.chmod(0o755)
    code, out = run(github, "token", cache=cache)
    assert code == 1 and out == ""


def test_a_key_others_can_read_or_a_refusal_from_github_is_an_error_that_carries_no_secret(github, capsys):
    github.key_file.chmod(0o644)
    code, out = run(github, "token")
    err = capsys.readouterr().err
    assert code == 1 and out == "" and "chmod 600" in err and github.requests == []
    assert github.pem.decode().splitlines()[1] not in err
    github.key_file.chmod(0o600)
    github.status = 401
    code, out = run(github, "token")
    err = capsys.readouterr().err
    assert code == 1 and out == "" and "HTTP 401 Bad credentials" in err
    assert github.requests[-1]["jwt"] not in err


def test_the_jwt_goes_nowhere_but_https_or_this_machine():
    with pytest.raises(helper.TokenError, match="https only"):
        helper._api_url("http://api.example.com", "/app")
    assert helper._api_url("https://api.github.com/", "/app") == "https://api.github.com/app"


def test_the_loops_github_acceptance_credential_becomes_the_apps_token_with_no_code_change(github, tmp_path,
                                                                                           monkeypatch):
    """The switch is configuration: git's credential helper for github.com, which ``git_remote_token`` already asks."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo = tmp_path / "dispatcher-clone"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/crooksldn-pixel/clive"],
                   check=True)
    command = (f"!{sys.executable} {SCRIPT} --app-id {APP_ID} --installation-id {INSTALLATION} "
               f"--key-file {github.key_file} --api {github.api} --cache-dir {tmp_path / 'cache'} credential")
    for value in ("", command):          # the empty value first: no other helper is asked before the App
        subprocess.run(["git", "-C", str(repo), "config", "--add", "credential.https://github.com.helper", value],
                       check=True)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    assert git_remote_token(repo, "origin")("crooksldn-pixel/clive") == github.token(1)
    assert git_remote_token(repo, "origin")("crooksldn-pixel/clive") == github.token(1)    # the cached one
    assert len(github.requests) == 1
