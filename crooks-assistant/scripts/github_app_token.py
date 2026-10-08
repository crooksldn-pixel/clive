#!/usr/bin/env python3
"""A GitHub App's installation token, minted on demand: the Director's and the build loop's own GitHub identity.

Why it exists: the owner's ruling of 8 October 2026 (DEC-071, ruling 13; DEC-076) gives the Director and CLIVE's
build loop each a GitHub identity of its own, a GitHub App, instead of his account and its personal tokens.
docs/GITHUB_IDENTITY.md says how George creates the two Apps and where each key lives; this mints the short-lived
token each one uses.

    github_app_token.py --app-id ID --installation-id ID --key-file PEM [options] token
        print one installation token (for GH_TOKEN, or an API call)
    github_app_token.py --app-id ID --installation-id ID --key-file PEM [options] credential get
        git's credential-helper protocol: answers https://github.com with the App's token

    options: --repository NAME (repeat; default clive)  --permission NAME=LEVEL (repeat; default contents=write,
             pull_requests=write, actions=read)  --cache-dir DIR  --api URL

What it promises:

- The App's private key is read from a host file only its owner can read: never from the repository, an
  argument or the environment. It signs one short JWT (RS256, nine minutes) and is never written anywhere.
- The installation token is narrowed when it is minted to the named repositories and exactly the named
  permissions, lives an hour, and goes only to stdout for the caller. A cache, when asked for, is one 0600 file
  in a 0700 folder, reused only for the same repositories and permissions and only while it has five minutes
  left.
- As a credential helper it answers only ``get`` for https://github.com; any other host, protocol or action gets
  nothing, so git falls through to its other helpers or fails closed. It never stores what git offers it.
- No error message carries the key, the JWT or a token.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.github.com"
DEFAULT_REPOSITORIES = ("clive",)
DEFAULT_PERMISSIONS = {"contents": "write", "pull_requests": "write", "actions": "read"}
JWT_LIFETIME_S = 540
REUSE_MARGIN_S = 300
TIMEOUT_S = 20


class TokenError(RuntimeError):
    """Why no token could be minted; never carries a secret."""


def key_file_problem(path: Path) -> str | None:
    """Why this private key must not be used, or None. Never returns the key."""
    try:
        info = os.stat(path)
    except OSError as exc:
        return f"the App's key file {path} is not readable: {exc.strerror}"
    if not stat.S_ISREG(info.st_mode):
        return f"the App's key file {path} is not a regular file"
    if info.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        return f"the App's key file {path} is readable by group or others (mode {oct(info.st_mode & 0o777)}); chmod 600 it"
    if info.st_uid != os.geteuid():
        return f"the App's key file {path} is not owned by this user"
    return None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def app_jwt(app_id: str, key_pem: bytes, now: int) -> str:
    """The App's own short JWT (RS256), the only thing that may ask GitHub for an installation token."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    try:
        key = serialization.load_pem_private_key(key_pem, password=None)
    except (ValueError, TypeError):
        raise TokenError("the App's key file does not hold an unencrypted PEM private key") from None
    if not isinstance(key, rsa.RSAPrivateKey):
        raise TokenError("the App's key file does not hold an RSA private key")
    header = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
    claims = _b64url(json.dumps({"iat": now - 60, "exp": now + JWT_LIFETIME_S, "iss": str(app_id)},
                                separators=(",", ":")).encode())
    signature = key.sign(f"{header}.{claims}".encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{header}.{claims}.{_b64url(signature)}"


def _api_url(api: str, path: str) -> str:
    parts = urllib.parse.urlsplit(api)
    if parts.scheme != "https" and parts.hostname not in ("127.0.0.1", "localhost"):
        raise TokenError(f"refusing to send the App's JWT to {parts.scheme}://{parts.hostname}: https only")
    return api.rstrip("/") + path


def mint(app_id: str, installation_id: str, key_file: Path, *, repositories=DEFAULT_REPOSITORIES,
         permissions: dict | None = None, api: str = API, now: int | None = None) -> dict:
    """One installation token narrowed to ``repositories`` and ``permissions``: ``{"token", "expires_at"}``."""
    problem = key_file_problem(key_file)
    if problem:
        raise TokenError(problem)
    if not str(installation_id).isdigit() or not str(app_id).strip():
        raise TokenError("the App id and a numeric installation id are both needed")
    jwt = app_jwt(str(app_id), Path(key_file).read_bytes(), int(time.time()) if now is None else now)
    body = {"repositories": list(repositories), "permissions": dict(permissions or DEFAULT_PERMISSIONS)}
    request = urllib.request.Request(
        _api_url(api, f"/app/installations/{installation_id}/access_tokens"), method="POST",
        data=json.dumps(body).encode(), headers={"Authorization": f"Bearer {jwt}",
                                                 "Accept": "application/vnd.github+json",
                                                 "X-GitHub-Api-Version": "2022-11-28",
                                                 "User-Agent": "clive-github-app-token"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            answer = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        message = ""
        try:
            message = str(json.loads(exc.read()).get("message", ""))[:200]
        except (ValueError, OSError, AttributeError):
            pass
        raise TokenError(f"GitHub refused the installation token: HTTP {exc.code} {message}".strip()) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TokenError(f"GitHub could not be reached: {getattr(exc, 'reason', exc)}") from None
    if not isinstance(answer, dict) or not answer.get("token") or not answer.get("expires_at"):
        raise TokenError("GitHub's answer carried no token")
    return {"token": answer["token"], "expires_at": answer["expires_at"]}


def _expires(stamp: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()


def token(app_id: str, installation_id: str, key_file: Path, *, repositories=DEFAULT_REPOSITORIES,
          permissions: dict | None = None, api: str = API, cache_dir: Path | None = None) -> str:
    """A token with at least five minutes left: the cached one when it fits, else a new one (then cached)."""
    scope = {"repositories": sorted(repositories), "permissions": dict(sorted((permissions or DEFAULT_PERMISSIONS).items()))}
    cache = Path(cache_dir) / f"installation-{installation_id}.json" if cache_dir else None
    if cache is not None:
        Path(cache_dir).mkdir(mode=0o700, parents=True, exist_ok=True)
        if Path(cache_dir).stat().st_mode & 0o077:
            raise TokenError(f"the token cache {cache_dir} is open to group or others; chmod 700 it")
        try:
            kept = json.loads(cache.read_text(encoding="utf-8"))
            if kept.get("scope") == scope and _expires(kept["expires_at"]) - time.time() > REUSE_MARGIN_S:
                return kept["token"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
    fresh = mint(app_id, installation_id, key_file, repositories=repositories, permissions=permissions, api=api)
    if cache is not None:
        tmp = cache.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump({**fresh, "scope": scope}, out)
        os.replace(tmp, cache)
    return fresh["token"]


def credential_request(text: str) -> dict[str, str]:
    return dict(line.split("=", 1) for line in text.splitlines() if "=" in line)


def answers(request: dict[str, str]) -> bool:
    """Whether a git credential request is one this helper answers: https on github.com, nothing else."""
    return request.get("protocol") == "https" and request.get("host", "").lower() == "github.com"


def _permissions(items: list[str]) -> dict | None:
    if not items:
        return None
    out = {}
    for item in items:
        name, _, level = item.partition("=")
        if not name or level not in ("read", "write"):
            raise TokenError(f"--permission {item!r}: expected NAME=read or NAME=write")
        out[name] = level
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--app-id", required=True, help="the App's id (or client id), from its settings page")
    p.add_argument("--installation-id", required=True, help="its installation on the account, from the install URL")
    p.add_argument("--key-file", required=True, help="the App's private key: a 0600 host file, never in the repository")
    p.add_argument("--repository", action="append", default=[], help="a repository the token may reach (default clive)")
    p.add_argument("--permission", action="append", default=[], help="NAME=read|write (default contents=write, "
                                                                     "pull_requests=write, actions=read)")
    p.add_argument("--cache-dir", default=None, help="a 0700 folder to keep the current token in between calls")
    p.add_argument("--api", default=API)
    p.add_argument("action", choices=["token", "credential"])
    p.add_argument("operation", nargs="?", default=None, help="credential only: git's get, store or erase")
    return p


def main(argv: list[str] | None = None, stdin=None, stdout=None) -> int:
    args = build_parser().parse_args(argv)
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    try:
        kwargs = dict(repositories=tuple(args.repository) or DEFAULT_REPOSITORIES,
                      permissions=_permissions(args.permission), api=args.api,
                      cache_dir=Path(args.cache_dir) if args.cache_dir else None)
        if args.action == "credential":
            if args.operation != "get" or not answers(credential_request(stdin.read())):
                return 0                        # store, erase, another host: nothing to say, nothing kept
            value = token(args.app_id, args.installation_id, Path(args.key_file), **kwargs)
            stdout.write(f"username=x-access-token\npassword={value}\n")
            return 0
        stdout.write(token(args.app_id, args.installation_id, Path(args.key_file), **kwargs) + "\n")
        return 0
    except TokenError as exc:
        print(f"github_app_token: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
