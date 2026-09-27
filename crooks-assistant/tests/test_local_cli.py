"""The server's own test-session commands and their key (the 2026-09-27 deploy review, round 6,
F-05A): with the production switches, `make test-session-*` works, and the key it carries opens
those three routes and nothing else — not the write boundary, not the owner rule, not a turn."""

from __future__ import annotations

import json
import re

import pytest
from starlette.requests import Request

from app import local_cli
from app.main import app, is_public
from app.routes import actions as actions_route
from tests.test_actions_routes import (  # noqa: F401 - `client` is a fixture
    OWNER,
    PROXIED,
    client,
    configure,
)

KEY = "k" * 43
WITH_KEY = {local_cli.HEADER: KEY}


def production(http) -> None:
    """The switches production runs with: his login on the list, and the server itself not him
    (no CROOKS_LOCAL_OWNER, no CROOKS_WRITES_LOCAL_OWNER)."""
    configure(http, logins=OWNER, local=False)
    http.runtime.settings = http.runtime.settings.model_copy(update={"local_owner": False, "writes_local_owner": False})
    app.state.allowed_logins = http.runtime.allowed_logins


async def test_the_servers_own_commands_work_with_the_production_switches(client):  # noqa: F811
    production(client)
    local_cli.bind_key(KEY)
    started = await client.post("/test-session/start", json={"name": "from the server"}, headers=WITH_KEY)
    assert started.status_code == 200 and started.json()["started"] is True, started.text
    status = await client.get("/test-session/status", headers=WITH_KEY)
    assert status.status_code == 200 and status.json()["active"] is True
    stopped = await client.post("/test-session/stop", headers=WITH_KEY)
    assert stopped.status_code == 200 and stopped.json()["stopped"] is True


async def test_without_the_key_or_with_a_wrong_one_they_are_refused_as_before(client):  # noqa: F811
    production(client)
    local_cli.bind_key(KEY)
    for headers in ({}, {local_cli.HEADER: "k" * 42}, {local_cli.HEADER: KEY + "x"}, {local_cli.HEADER: ""}):
        refused = await client.get("/test-session/status", headers=headers)
        assert refused.status_code == 403 and refused.json()["code"] == "not_authorised_local", headers
    local_cli.bind_key(None)   # no key made on this server: nothing it could be compared with
    refused = await client.get("/test-session/status", headers=WITH_KEY)
    assert refused.status_code == 403


async def test_the_key_is_for_the_server_itself_never_through_the_proxy(client):  # noqa: F811
    """A device reaches the server through `tailscale serve`; the key is not a device's. A
    stranger's device holding it is refused; a forged forwarding header with it is refused at
    the door."""
    production(client)
    local_cli.bind_key(KEY)
    stranger = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.9", **WITH_KEY}
    configure(client, logins="someone-else@example.com", local=False)
    client.runtime.settings = client.runtime.settings.model_copy(update={"local_owner": False})
    assert (await client.get("/test-session/status", headers=stranger)).status_code == 403
    production(client)
    client.runtime.settings = client.runtime.settings.model_copy(update={"tailscale_verify": True})
    forged = await client.get("/test-session/status", headers={"X-Forwarded-For": "100.64.0.9", "Tailscale-User-Login": OWNER, **WITH_KEY})
    assert forged.status_code == 403 and forged.json()["who"] == "unverified proxy"


async def test_the_key_opens_nothing_but_the_three_routes(client):  # noqa: F811
    """Every other route the app serves, asked with the key and the production switches: each is
    refused exactly as it is without it."""
    production(client)
    local_cli.bind_key(KEY)
    served = [(template, method.upper()) for template, item in app.openapi()["paths"].items() for method in item]
    served += [("/openapi.json", "GET"), ("/docs", "GET"), ("/redoc", "GET")]
    checked = 0
    for template, method in served:
        path = re.sub(r"\{[^}]+\}", "scr_000000000000", template)
        if is_public(path) or (method, path) in local_cli.ROUTES:
            continue
        response = await client.request(method, path, headers=WITH_KEY, json={})
        assert response.status_code == 403 and response.json().get("code") == "not_authorised_local", (method, path)
        checked += 1
    assert checked > 50
    # The three paths, with any other method, are no better.
    for method, path in (("GET", "/test-session/start"), ("POST", "/test-session/status"), ("GET", "/test-session/stop")):
        assert (await client.request(method, path, headers=WITH_KEY)).status_code in (403, 405)


def _request(headers: dict[str, str], path: str = "/actions/prop_1/commit", method: str = "POST") -> Request:
    scope = {"type": "http", "method": method, "path": path, "app": app, "query_string": b"",
             "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
             "client": ("127.0.0.1", 50123), "server": ("127.0.0.1", 8000)}
    return Request(scope)


async def test_the_key_is_never_an_owner_to_the_write_boundary_or_the_owner_rule(client):  # noqa: F811
    """The finding's trap: the obvious fix, CROOKS_WRITES_LOCAL_OWNER, would have let any process
    on the server apply changes. The key reaches neither gate, even on its own routes."""
    production(client)
    local_cli.bind_key(KEY)
    for path in ("/actions/prop_1/commit", "/test-session/start"):
        request = _request(WITH_KEY, path)
        _caller, code, _detail, _spoken = actions_route.caller_check(request)
        assert code == "not_authorised_local", path
        assert actions_route.principal_verdict(request)[1] == "not_authorised_local", path
    assert local_cli.admits(_request(WITH_KEY, "/test-session/start")) is True
    assert local_cli.admits(_request(WITH_KEY, "/actions/prop_1/commit")) is False


def test_the_command_line_sends_the_key_when_it_can_read_it(monkeypatch):
    import sys
    import urllib.request
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import session_ops
    import test_session

    sent: list[dict[str, str]] = []

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return json.dumps({"ok": True}).encode()

    def urlopen(request, timeout=0):
        sent.append({k.lower(): v for k, v in request.header_items()})
        return Answer()

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    local_cli.bind_key(KEY)
    test_session._call(8000, "GET", "/test-session/status")
    session_ops.call(8000, "POST", "/test-session/stop")
    session_ops.call(8000, "GET", "/health")
    assert sent[0][local_cli.HEADER.lower()] == KEY and sent[1][local_cli.HEADER.lower()] == KEY
    assert local_cli.HEADER.lower() not in sent[2], "only the test-session routes are sent the key"
    local_cli.bind_key(None)   # a user who cannot read it (not root): nothing is sent
    test_session._call(8000, "GET", "/test-session/status")
    assert local_cli.HEADER.lower() not in sent[3]


def test_the_backend_makes_the_key_once_and_keeps_it(monkeypatch):
    from app.secrets import keychain

    held: dict[str, str] = {}
    monkeypatch.setattr(keychain, "get_optional", lambda key: held.get(key))
    monkeypatch.setattr(keychain, "set_secret", lambda key, value: held.__setitem__(key, value))
    local_cli.bind_key()          # the real store (here, the stand-in above)
    assert local_cli.read_key() is None
    assert local_cli.ensure_key() is True
    first = held["local_cli_key"]
    assert len(first) >= 32 and local_cli.ensure_key() is True and held["local_cli_key"] == first
    assert "local_cli_key" in keychain.KNOWN_KEYS

    def refuse(key, value):
        raise PermissionError("not root")

    held.clear()
    monkeypatch.setattr(keychain, "set_secret", refuse)
    assert local_cli.ensure_key() is False and local_cli.read_key() is None


@pytest.mark.parametrize("value", ["short", "", None])
def test_a_key_too_short_to_be_one_opens_nothing(value):
    local_cli.bind_key(value)
    assert local_cli.read_key() is None and local_cli.headers() == {}
