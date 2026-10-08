"""A Connections screen with something in every state, for a real browser to look at.

The screen's job is to say at a glance what CLIVE is connected to, put right what is broken and
add what is missing, so a picture of it is only honest when each of those is on it at once. This
stands the fixture world up (experience/browser.py) with the secret store in a temporary folder
and every service answered by a stand-in, then puts each connection in a state the owner meets:

  Shopify      set at the server, its test passes, last asked five minutes ago
  Gmail        set at the server, the inbox answers
  ElevenLabs   saved from this screen, its test passes, speaking as the configured voice
  Instagram    set at the server, its test passes, the sign-in runs out in three days
  GitHub       set at the server, GitHub refuses the token (needs a new one)
  Ship24       not connected
  CROOKS Returns not connected
  CLIVE Shipping not connected
  YouTube      not connected

and one passkey, on an iPhone. That passkey's key is handed to the browser's virtual
authenticator, and CLIVE's address is set to http://localhost:<port>, so the page's own passkey
approval runs end to end: the browser saves a new GitHub token with it, which GitHub (a stand-in
here too) accepts. Nothing reaches the network or a Keychain. Used by
tests/test_connections_browser.py, and by hand for the screenshots:

    NODE_PATH=<the node_modules holding playwright-core> python -m tests.connections_world <shots folder> <prefix>
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

from app.secrets import keychain as _keychain
from tests.fake_credentials import (
    DIGITS,
    HEX,
    bearer_token,
    body,
    elevenlabs_key,
    github_fine_grained_token,
    google_oauth_token,
    shopify_token,
)
from tests.fake_passkey import ORIGIN, RP_ID, Authenticator

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "browser" / "connections.js"
OWNER = "owner@example.com"
# Every value a stand-in service is given, so the browser run can prove none reached the page.
SECRETS = {
    "shopify_client_id": body("cw-shopify-id", 32, HEX),
    "shopify_client_secret": shopify_token("cw-shopify-secret", kind="ss"),
    "gmail_token": json.dumps({"refresh_token": bearer_token("cw-gmail-refresh"), "client_id": "x",
                               "client_secret": body("cw-gmail-secret", 24, HEX),
                               "token": google_oauth_token("cw-gmail"),
                               "scopes": ["https://www.googleapis.com/auth/gmail.modify"]}),
    "elevenlabs_api_key": elevenlabs_key("connections-world"),
    "instagram_access_token": bearer_token("cw-instagram", length=60),
    "instagram_app_id": body("cw-ig-app", 16, DIGITS),
    "instagram_app_secret": body("cw-ig-secret", 32, HEX),
    "github_engineering_inbox_token": github_fine_grained_token("cw-github"),
}
# The token the browser pastes over GitHub's refused one: the stand-in GitHub accepts this one.
NEW_GITHUB = github_fine_grained_token("cw-github-new")
# An app's ID is not a secret: the screen shows it, so the owner can see the right one is in.
NOT_SECRET = ("shopify_client_id", "instagram_app_id")
# Where each is: the server's own files, or saved from this screen.
AT_SERVER = ("shopify_client_id", "shopify_client_secret", "gmail_token", "instagram_access_token",
             "instagram_app_id", "instagram_app_secret", "github_engineering_inbox_token")
SAVED_HERE = ("elevenlabs_api_key",)

# The genuine readers, captured before tests/conftest.py's `_no_secrets` replaces them for each
# test: the world reads its keys back through the store as production does.
_REAL = {name: getattr(_keychain, name) for name in ("get", "get_optional", "present", "where")}


class Services:
    """What each service answers a key test with."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        host, path = request.url.host, request.url.path
        if host == "api.elevenlabs.io":
            return httpx.Response(200, json=[{"model_id": "eleven_flash_v2_5"}])
        if host.endswith(".myshopify.com") and path == "/admin/oauth/access_token":
            return httpx.Response(200, json={"access_token": shopify_token("cw-minted"), "scope": "read_orders"})
        if host == "api.github.com":
            if request.headers.get("authorization") == f"Bearer {NEW_GITHUB}":
                return httpx.Response(200, json={"permissions": {"push": True}})
            return httpx.Response(401, json={"message": "Bad credentials"})
        if host == "graph.instagram.com" and path.endswith("/me"):
            return httpx.Response(200, json={"user_id": "17841400000000000", "username": "crooksldn"})
        return httpx.Response(404, json={"error": "not part of the connections world"})


class VoiceService:
    """ElevenLabs as the voice's own client meets it (GET /voices/{id}). Derek, the voice in use,
    reports two of his own settings and not the rest, so the screen shows both kinds of untouched
    slider. Kept apart from the key tests above, so what those asked is still counted on its own."""

    VOICES = {"Q0Et7LOU7VpeoeCRQAVS": {"name": "Derek", "settings": {"stability": 0.5, "similarity_boost": 0.75}}}

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        voice_id = request.url.path.rsplit("/", 1)[-1]
        if request.url.path.startswith("/v1/voices/") and voice_id in self.VOICES:
            return httpx.Response(200, json={"voice_id": voice_id, **self.VOICES[voice_id]})
        return httpx.Response(404, json={"detail": {"status": "not part of the connections world"}})


class World:
    """The patches made, so they can be put back."""

    def __init__(self) -> None:
        self._undo: list[tuple[Any, str, Any]] = []
        self._env: dict[str, str | None] = {}
        self.services = Services()
        self.voice = VoiceService()
        self.device: Authenticator | None = None

    def patch(self, owner: Any, name: str, value: Any) -> None:
        self._undo.append((owner, name, getattr(owner, name)))
        setattr(owner, name, value)

    def env(self, name: str, value: str | None) -> None:
        self._env.setdefault(name, os.environ.get(name))
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value

    def restore(self) -> None:
        from app.clients import instagram as instagram_client
        from app.connections import passkeys, service
        from app.secrets import vault
        from app.speech import voice_prefs

        instagram_client.reset()
        vault.bind()
        service.configure(state_dir=None)
        voice_prefs.configure(state_dir=None)
        passkeys.reset()
        for owner, name, value in reversed(self._undo):
            setattr(owner, name, value)
        for name, value in self._env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _register_passkey(origin: str) -> Authenticator:
    """The owner's passkey, made for this CLIVE's address as his phone would make it."""
    from urllib.parse import urlsplit

    from app.connections import passkeys

    rp_id = urlsplit(origin).hostname or RP_ID
    device = Authenticator(origin=origin, rp_id=rp_id)
    begun = passkeys.begin_registration(login=OWNER, origin=origin, rp_id=rp_id, approved=False)
    passkeys.finish_registration(device.create(begun), login=OWNER, origin=origin, label="iPhone")
    return device


def passkey_for_the_browser(device: Authenticator) -> dict[str, str]:
    """The passkey as Chromium's virtual authenticator takes one (WebAuthn.addCredential): its id
    and its private key, PKCS#8, both in standard base64. A key made for this test, thrown away after."""
    import base64

    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    key = device._private.private_bytes(Encoding.DER, PrivateFormat.PKCS8, NoEncryption())
    return {"id": base64.b64encode(device.credential_id).decode(), "key": base64.b64encode(key).decode(),
            "rp_id": device.rp_id}


async def furnish(runtime: Any, scratch: Path, world: World, origin: str = ORIGIN) -> None:
    """Put every connection in its state, as the owner would meet it."""
    from app.clients import gmail as gmail_client
    from app.clients import instagram as instagram_client
    from app.connections import ledger, passkeys, service, testers
    from app.secrets import keychain, linux_store, vault
    from app.speech import voice_prefs
    from tests.test_secrets_vault import FakeCipher

    secrets = scratch / "secrets"
    secrets.mkdir(parents=True, exist_ok=True, mode=0o700)
    world.env(linux_store.STORE_DIR_ENV, str(secrets))
    world.env(linux_store.CREDENTIALS_ENV, None)
    world.patch(keychain, "_on_linux", lambda: True)
    for name, function in _REAL.items():
        world.patch(keychain, name, function)
    world.patch(gmail_client, "TOKEN_PATH", scratch / "no-token.json")
    vault.bind(FakeCipher())
    for key in AT_SERVER:
        path = secrets / key
        path.write_text(SECRETS[key], encoding="utf-8")
        path.chmod(0o600)
    for key in SAVED_HERE:
        vault.store(key, SECRETS[key])
    state_dir = secrets / vault.DIR_NAME
    service.configure(state_dir=state_dir)
    voice_prefs.configure(state_dir=state_dir)
    passkeys.reset()
    transport = httpx.MockTransport(world.services)
    world.patch(testers, "http_client", lambda: httpx.AsyncClient(transport=transport))
    world.patch(instagram_client, "http_client", lambda: httpx.AsyncClient(transport=transport))
    world.patch(runtime.voice, "_http", httpx.AsyncClient(transport=httpx.MockTransport(world.voice)))
    instagram_client.configure(state_path=scratch / "instagram.json")
    now = time.time()
    # Renewed six weeks ago and not since: the sign-in runs out in three days.
    instagram_client._note(username="crooksldn", refreshed_at=now - 57 * 86400, expires_at=now + 3 * 86400 + 600,
                           first_seen_at=now - 90 * 86400)
    world.device = _register_passkey(origin)
    # The record of changes, as a week of use leaves it.
    ledger.record("passkey_added", who=OWNER, device="iPhone", detail="a passkey on iPhone")
    ledger.record("saved", connection="elevenlabs", keys=["elevenlabs_api_key"], who=OWNER, device="iPhone",
                  detail="ElevenLabs accepted the key.")
    # What the screen last learned about each: the existing testers, run once now.
    for name in ("shopify", "elevenlabs", "instagram", "github"):
        await service.test(runtime, name)
    # Shopify was last asked five minutes ago, so the screen asks it again as it opens.
    _age(ledger, "shopify", 300)


def _age(ledger: Any, name: str, seconds: float) -> None:
    from datetime import UTC, datetime, timedelta

    table = ledger.last_tests()
    at = datetime.fromisoformat(table[name]["at"]) - timedelta(seconds=seconds)
    table[name]["at"] = at.astimezone(UTC).isoformat(timespec="seconds")
    ledger._replace(ledger._folder() / ledger.TESTS, json.dumps(table))


async def serve(scratch: Path) -> tuple[Any, Any, int, World]:
    from experience.browser import _free_port, serve_fixture_world

    world = World()
    port = _free_port()
    server, task, _shop = await serve_fixture_world(port)
    from app.main import app

    runtime = app.state.runtime
    # CLIVE's own address, as CROOKS_PUBLIC_ORIGIN would name it: a passkey works at localhost.
    origin = f"http://localhost:{port}"
    runtime.settings = runtime.settings.model_copy(update={"local_owner": False, "public_origin": origin})
    try:
        await furnish(runtime, scratch, world, origin)
    except BaseException:
        world.restore()
        raise
    return server, task, port, world


def run_script(port: int, shots: str, prefix: str, world: World | None = None) -> dict[str, Any]:
    """The browser half: scripts/browser/connections.js, its last JSON line."""
    from experience.browser import CHROMIUM

    secrets = [v for k, v in SECRETS.items() if k not in NOT_SECRET] + [NEW_GITHUB]
    device = passkey_for_the_browser(world.device) if world is not None and world.device else {}
    flow = json.dumps({"passkey": device, "github": NEW_GITHUB}) if device else "{}"
    result = subprocess.run(
        ["node", str(SCRIPT), f"http://127.0.0.1:{port}", shots, prefix, json.dumps(secrets), flow],
        cwd=ROOT, capture_output=True, text=True, timeout=600, env={**os.environ, "CROOKS_CHROMIUM": CHROMIUM},
    )
    for line in reversed((result.stdout or "").strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return {"ok": False, "checks": [{"name": "the script ran", "ok": False,
                                     "detail": (result.stdout + result.stderr)[-2000:]}]}


async def _main(shots: str, prefix: str) -> int:
    from experience.browser import _stop

    with tempfile.TemporaryDirectory(prefix="connections-world-") as folder:
        server, task, port, world = await serve(Path(folder))
        try:
            payload = await asyncio.to_thread(run_script, port, shots, prefix, world)
        finally:
            await _stop(server, task)
            world.restore()
    print(json.dumps(payload, indent=1))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1] if len(sys.argv) > 1 else "", sys.argv[2] if len(sys.argv) > 2 else "")))
