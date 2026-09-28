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
    # An empty header is the header (round 8, F-05A): refused as a wrong key is, not as no key.
    for headers, code in (({}, "not_authorised_local"), ({local_cli.HEADER: ""}, "local_key_misused"),
                          ({local_cli.HEADER: "k" * 42}, "local_key_misused"), ({local_cli.HEADER: KEY + "x"}, "local_key_misused")):
        refused = await client.get("/test-session/status", headers=headers)
        assert refused.status_code == 403 and refused.json()["code"] == code, headers
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
        assert response.status_code == 403 and response.json().get("code") == "local_key_misused", (method, path)
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


async def test_a_verified_owner_device_carrying_the_key_is_refused_and_without_it_is_admitted(client, monkeypatch):  # noqa: F811
    """Round 7, F-05A: the key is the server's own command or nothing. The owner's own device,
    verified end to end by Tailscale, is refused when it presents it — on the three routes and
    anywhere else — and admitted as the owner without it."""
    from app import identity

    production(client)
    local_cli.bind_key(KEY)
    client.runtime.settings = client.runtime.settings.model_copy(update={"tailscale_verify": True})
    identity.bind_peer_check(lambda client_, server: (True, "opened by tailscaled (pid 1)"))
    identity.bind_self_check(lambda address: False)
    identity.bind_runner(lambda cli, address: {"UserProfile": {"LoginName": OWNER}})
    monkeypatch.setattr(identity, "cli_path", lambda configured="": "/usr/bin/tailscale")
    assert (await client.get("/whoami", headers=PROXIED)).json()["owner"] is True, "a verified owner device"
    for method, path in (("GET", "/test-session/status"), ("POST", "/test-session/start"), ("GET", "/objectives"), ("GET", "/health")):
        refused = await client.request(method, path, headers={**PROXIED, **WITH_KEY}, json={"name": "x"})
        assert refused.status_code == 403 and refused.json()["code"] == "local_key_misused", (path, refused.text)
    assert (await client.get("/test-session/status", headers=PROXIED)).status_code == 200
    # And on the server, the key on any route but its own is refused too.
    assert (await client.get("/objectives", headers=WITH_KEY)).json()["code"] == "local_key_misused"


# ------------------------------------------------ round 8, F-05A: the header, not its value


def _verified_owner_device(client, monkeypatch) -> None:  # noqa: F811
    """Production's switches with Tailscale verification on, and the kernel, the server's own
    addresses and `tailscale whois` all saying this is the owner's own device (stood in for:
    tests have no tailscaled; the phone check is the deploy's)."""
    from app import identity

    production(client)
    client.runtime.settings = client.runtime.settings.model_copy(update={"tailscale_verify": True})
    identity.bind_peer_check(lambda client_, server: (True, "opened by tailscaled (pid 1)"))
    identity.bind_self_check(lambda address: False)
    identity.bind_runner(lambda cli, address: {"UserProfile": {"LoginName": OWNER}})
    monkeypatch.setattr(identity, "cli_path", lambda configured="": "/usr/bin/tailscale")


async def test_through_the_proxy_a_right_wrong_or_empty_key_is_refused_on_each_command_route(client, monkeypatch):  # noqa: F811
    """The owner's verified device, on each of the three test-session routes: carrying the key,
    a wrong one or an empty one, it is refused at the door; the same device without the header is
    the owner and is let through."""
    _verified_owner_device(client, monkeypatch)
    local_cli.bind_key(KEY)
    assert (await client.get("/whoami", headers=PROXIED)).json()["owner"] is True, "a verified owner device"
    routes = (("POST", "/test-session/start"), ("GET", "/test-session/status"), ("POST", "/test-session/stop"))
    for method, path in routes:
        for value in (KEY, "k" * 42, ""):
            refused = await client.request(method, path, headers={**PROXIED, local_cli.HEADER: value}, json={"name": "x"})
            assert refused.status_code == 403 and refused.json()["code"] == "local_key_misused", (path, repr(value), refused.text)
    started = await client.post("/test-session/start", headers=PROXIED, json={"name": "from the phone"})
    assert started.status_code == 200 and started.json()["started"] is True, started.text
    status = await client.get("/test-session/status", headers=PROXIED)
    assert status.status_code == 200 and status.json()["active"] is True
    stopped = await client.post("/test-session/stop", headers=PROXIED)
    assert stopped.status_code == 200 and stopped.json()["stopped"] is True


async def test_an_empty_key_header_is_refused_wherever_the_key_does_not_apply(client):  # noqa: F811
    """Straight to the port, on routes that are not the key's: public or the owner's, an empty
    header is refused as a present one is. And on the key's own routes, two of them are refused
    even when both hold the key: one header, one claim."""
    production(client)
    local_cli.bind_key(KEY)
    for method, path in (("GET", "/objectives"), ("POST", "/turn"), ("GET", "/ping"), ("GET", "/whoami"), ("GET", "/")):
        for name in (local_cli.HEADER, local_cli.HEADER.lower()):
            refused = await client.request(method, path, headers={name: ""})
            assert refused.status_code == 403 and refused.json()["code"] == "local_key_misused", (method, path, name)
    doubled = await client.get("/test-session/status", headers=[(local_cli.HEADER, KEY), (local_cli.HEADER, KEY)])
    assert doubled.status_code == 403 and doubled.json()["code"] == "local_key_misused"
    assert (await client.get("/test-session/status", headers=WITH_KEY)).status_code == 200, "one header with the key still works"
    empty = _request({local_cli.HEADER: ""}, "/test-session/start")
    assert local_cli.presented(empty) is True and local_cli.admits(empty) is False
    assert local_cli.presented(_request({}, "/test-session/start")) is False


# ------------------------------------------------ round 8, F-NEW-PAD: the host's own status readers


def _scripts():
    import sys
    from pathlib import Path

    scripts = str(Path(__file__).resolve().parents[1] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import launch_common

    return launch_common


class _Answer:
    def __init__(self, body: dict):
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self.body


def test_the_hosts_status_readers_carry_the_key_on_loopback_and_nowhere_else(monkeypatch):
    """`make health`, crooks-status, `make install` and CROOKS Control read /health through
    launch_common.fetch_health. It asks plainly; only when the answer is liveness alone does it
    ask again with the server's key — on the server's own loopback address, never any other, and
    never through a proxy — so the host keeps the whole document and the key goes nowhere it is
    not needed."""
    import io
    import urllib.error
    import urllib.request

    lc = _scripts()
    sent: list[tuple[str, dict[str, str]]] = []
    server = {"refuses_key": False, "owner_here": False}

    def opened(request, timeout_s):
        headers = {k.lower(): v for k, v in request.header_items()}
        sent.append((request.full_url, headers))
        keyed = local_cli.HEADER.lower() in headers
        if keyed and server["refuses_key"]:
            raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"code": "local_key_misused"}'))
        whole = keyed or server["owner_here"]
        return _Answer({"status": "ok", "checks": {}, **({"sessions": 1} if whole else {"limited": True})})

    real_open = lc._open
    monkeypatch.setattr(lc, "_open", opened)
    local_cli.bind_key(KEY)
    for url in ("http://127.0.0.1:8000/health", "http://[::1]:8000/health?fresh=1"):
        before = len(sent)
        assert "limited" not in lc.fetch_health(url)
        assert [local_cli.HEADER.lower() in h for _u, h in sent[before:]] == [False, True], url
        assert sent[-1][1][local_cli.HEADER.lower()] == KEY
    for url in ("http://100.64.0.9:8000/health", "https://127.0.0.1:8000/health", "http://localhost:8000/health",
                "https://crooks.example.com/health"):
        before = len(sent)
        assert lc.fetch_health(url)["limited"] is True
        assert [local_cli.HEADER.lower() in h for _u, h in sent[before:]] == [False], url
    # Where the reader is already the owner (a Mac that speaks for him), the key is never read.
    server["owner_here"] = True
    before = len(sent)
    assert "limited" not in lc.fetch_health("http://127.0.0.1:8000/health") and len(sent) == before + 1
    server["owner_here"] = False
    # A build that does not take the key on /health yet: its liveness answer stands.
    server["refuses_key"] = True
    before = len(sent)
    assert lc.fetch_health("http://127.0.0.1:8000/health")["limited"] is True
    assert [local_cli.HEADER.lower() in h for _u, h in sent[before:]] == [False, True]
    # A user who cannot read the key sends none.
    server["refuses_key"] = False
    local_cli.bind_key(None)
    before = len(sent)
    assert lc.fetch_health("http://127.0.0.1:8000/health")["limited"] is True
    assert [local_cli.HEADER.lower() in h for _u, h in sent[before:]] == [False]

    # Never through a proxy the environment names.
    handlers: list = []

    def build(*given):
        handlers.extend(given)
        raise OSError("not opened in a test")

    monkeypatch.setattr(lc, "_open", real_open)
    monkeypatch.setattr(urllib.request, "build_opener", build)
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example.com:3128")
    local_cli.bind_key(KEY)
    assert lc.fetch_health("http://127.0.0.1:8000/health") is None
    proxies = [h for h in handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert proxies and all(h.proxies == {} for h in proxies)


def test_a_status_reader_given_liveness_alone_says_so_and_never_calls_it_well(monkeypatch, capsys):
    """Without the key the answer is `limited`: the essentials are not in it, and an absent check
    is unknown, never working. `make health` and crooks-status say so and exit 1."""
    import sys

    lc = _scripts()
    import healthcheck
    import status

    limited = {"status": "ok", "build": "b", "uptime_s": 1.0, "limited": True,
               "checks": {"proxy_identity": {"ok": True, "detail": "uvicorn started with --no-proxy-headers"},
                          "housekeeping": {"ok": True}}}
    state, line = healthcheck.verdict(limited)
    assert state == healthcheck.LIMITED and "the detail is the owner's" in line
    whole = {"status": "ok", "build": "b", "checks": {name: {"ok": True} for name in ("speech", "claude", "shopify")}}
    assert healthcheck.verdict(whole)[0] == healthcheck.OK, "the whole answer is read as before"
    monkeypatch.setattr(healthcheck.lc, "fetch_health", lambda url, timeout_s=8.0: limited)
    assert healthcheck.main(["--port", "8000"]) == 1
    assert healthcheck.main(["--port", "8000", "--json"]) == 1
    monkeypatch.setattr(sys.modules["launch_common"], "fetch_health", lambda url, timeout_s=8.0: limited)
    assert status.show(8000) == 1
    assert "the detail is the owner's" in capsys.readouterr().out
    assert "the detail is the owner's" in lc.summarise_health(limited)
