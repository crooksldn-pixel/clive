"""Every place that sends the server's local command key (the 2026-09-28 deploy review, round 10,
S1-KEY-SENDER and round 9 A1B-KEY).

The key (app/local_cli.py) leaves a process through one function, `launch_common._server_key`, and
travels down one path, `launch_common._one_connection`: a connection opened by the sender, the
kernel asked who took its far end (app/identity.py far_end_held_by), and the request sent down that
very connection only when the answer is the service — never through a proxy the environment names,
never on to a redirect. Two families of readers use it:

    fetch_health    `make health` (scripts/healthcheck.py), crooks-status (scripts/status.py),
                    `make install` and `make status` (scripts/install_systemd.py), CROOKS Control
                    and `make up` (scripts/control.py, scripts/service.py, scripts/up.py)
    call_service    `make test-session-*` (scripts/test_session.py) and CROOKS Control's session
                    buttons, through scripts/session_ops.py call

Round 10 found the second family was not on it: session_ops.call sent `local_cli.headers()` with
urllib, which asked nobody who held the port, read HTTP_PROXY, and followed a redirect with the key
still on it. Here every sender is driven against real listeners on loopback — a competitor holding
the port (judged by the real kernel check), the service answering a redirect, a proxy the
environment names — and what each listener received is looked at.
"""

from __future__ import annotations

import http.server
import json
import sys
import threading
from pathlib import Path

import pytest

from app import local_cli

KEY = "k" * 43
HEADER = local_cli.HEADER.lower()
LINUX = Path("/proc/net/tcp").exists()
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
WHOLE = {"status": "ok", "build": "b", "checks": {"speech": {"ok": True}, "claude": {"ok": True}, "shopify": {"ok": True}}}


def scripts():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import launch_common

    return launch_common


class Server:
    """A real HTTP listener on loopback that writes down every request — method, path, headers,
    body, the client's port — and answers as told: JSON, a redirect, or nothing at all (it takes
    the connection and never answers)."""

    def __init__(self, body: dict | None = None, *, redirect: str = "", status: int = 302) -> None:
        self.seen: list[dict] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def _answer(self):
                length = int(self.headers.get("Content-Length") or 0)
                outer.seen.append({"method": self.command, "path": self.path, "port": self.client_address[1],
                                   "headers": {k.lower(): v for k, v in self.headers.items()},
                                   "body": self.rfile.read(length) if length else b""})
                if redirect:
                    self.send_response(status)
                    self.send_header("Location", redirect)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = json.dumps(body if body is not None else {}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            do_GET = do_POST = _answer  # noqa: N815 - the standard library's names

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def keyed(self) -> list[bool]:
        return [HEADER in request["headers"] for request in self.seen]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def lc():
    module = scripts()
    yield module
    module.bind_listener_check(None)


@pytest.fixture()
def servers():
    made: list[Server] = []

    def make(*args, **kwargs) -> Server:
        made.append(Server(*args, **kwargs))
        return made[-1]

    yield make
    for server in made:
        server.close()


def _the_service(lc, checked: list[int] | None = None):
    def check(sock):
        if checked is not None:
            checked.append(sock.getsockname()[1])
        return True, "taken by crooks-assistant.service (pid 1)"

    lc.bind_listener_check(check)


# ------------------------------------------------------------------ the commands' own path


@pytest.mark.skipif(not LINUX, reason="the kernel's account of a connection is a Linux /proc file")
def test_a_competitor_holding_the_port_is_never_sent_the_key_by_the_session_commands(lc, servers):
    """S1-KEY-SENDER: whatever holds the port while the service restarts — here this test's own
    listener, in no crooks-assistant.service cgroup, judged by the real kernel check — gets each
    command once, plainly, and never the key: start (the typed CLI's path, test_session._call),
    status and stop (the Control app's, session_ops.call)."""
    import test_session

    from scripts import session_ops

    local_cli.bind_key(KEY)
    competitor = servers({"started": True, "test_session_id": "ts-x", "path": "/x"})
    assert test_session._call(competitor.port, "POST", "/test-session/start", {"name": "an hour"})["started"] is True
    session_ops.call(competitor.port, "GET", "/test-session/status")
    session_ops.call(competitor.port, "POST", "/test-session/stop")
    assert [r["path"] for r in competitor.seen] == ["/test-session/start", "/test-session/status", "/test-session/stop"]
    assert competitor.keyed() == [False, False, False], "asked once each, and the key never sent"
    assert KEY not in json.dumps([{**r, "body": r["body"].decode()} for r in competitor.seen])


def test_the_key_goes_down_the_very_connection_the_kernel_was_asked_about(lc, servers):
    from scripts import session_ops

    local_cli.bind_key(KEY)
    service = servers({"stopped": True})
    checked: list[int] = []
    _the_service(lc, checked)
    assert session_ops.call(service.port, "POST", "/test-session/stop") == {"stopped": True}
    assert service.keyed() == [True] and service.seen[0]["headers"][HEADER] == KEY
    assert checked == [service.seen[0]["port"]], "checked, then sent on that connection and no other"
    assert json.loads(service.seen[0]["body"]) == {}


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_is_an_answer_and_never_a_place_to_send_the_key(lc, servers, status):
    """urllib followed 301/302/303 on a POST as a GET, and anything on a GET, with the key still on
    it. Now the service's own connection answering a redirect is an answer, and nothing reaches
    where it points."""
    from scripts import session_ops

    elsewhere = servers({"stolen": True})
    redirecting = servers(redirect=f"http://127.0.0.1:{elsewhere.port}/stolen", status=status)
    local_cli.bind_key(KEY)
    _the_service(lc)
    for method, path in (("POST", "/test-session/start"), ("GET", "/test-session/status"), ("POST", "/test-session/stop")):
        assert session_ops.call(redirecting.port, method, path, {"name": "x"}) == {"code": f"http {status}"}
    assert redirecting.keyed() == [True, True, True]
    assert elsewhere.seen == [], "nothing reached the redirect's target"


def test_the_commands_never_go_through_a_proxy_the_environment_names(lc, servers, monkeypatch):
    from scripts import session_ops

    proxy, service = servers({"proxied": True}), servers({"active": False})
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, f"http://127.0.0.1:{proxy.port}")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    local_cli.bind_key(KEY)
    _the_service(lc)
    assert session_ops.call(service.port, "GET", "/test-session/status") == {"active": False}
    local_cli.bind_key(None)
    assert session_ops.call(service.port, "GET", "/test-session/status") == {"active": False}
    assert service.keyed() == [True, False] and proxy.seen == [], "straight to the port, with and without the key"


def test_the_key_goes_only_on_its_own_routes_and_only_where_it_can_be_read_and_checked(lc, servers, monkeypatch):
    """The key's own routes (local_cli.ROUTES) and no other; nothing from a user who cannot read it;
    and nothing where who took the connection cannot be shown at all (off Linux, a Mac)."""
    from scripts import session_ops

    service = servers({"ok": True})
    local_cli.bind_key(KEY)
    _the_service(lc)
    session_ops.call(service.port, "GET", "/test-session/status")
    session_ops.call(service.port, "GET", "/objectives")
    session_ops.call(service.port, "POST", "/turn", {"text": "hi"})
    session_ops.call(service.port, "GET", "/test-session/start")          # a key path, not the key's method
    assert service.keyed() == [True, False, False, False]
    local_cli.bind_key(None)
    session_ops.call(service.port, "GET", "/test-session/status")
    local_cli.bind_key(KEY)
    lc.bind_listener_check(None)
    monkeypatch.setattr(lc, "is_linux", lambda: False)
    session_ops.call(service.port, "GET", "/test-session/status")
    assert service.keyed()[4:] == [False, False]


def test_the_session_commands_still_tell_no_backend_from_a_backend_that_did_not_answer(lc, monkeypatch):
    """Round 8, F-10, through the new path: a refused connection is None (nothing running); one
    that takes the connection and never answers is a failed call that says so, not "no backend"."""
    import socket

    from scripts import session_ops

    monkeypatch.setattr(session_ops, "TIMEOUT_S", 0.3)
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen(4)
    port = silent.getsockname()[1]
    try:
        answer = session_ops.call(port, "POST", "/test-session/stop")
    finally:
        silent.close()
    assert session_ops.failed(answer) == "it did not answer within 0.3 s"
    assert session_ops.call(port, "GET", "/test-session/status") is None


# ------------------------------------------------------------------ the status readers, each one


@pytest.mark.skipif(not LINUX, reason="the kernel's account of a connection is a Linux /proc file")
def test_every_status_reader_asks_a_competitor_plainly_and_never_with_the_key(lc, servers, monkeypatch, capsys):
    """Each reader that goes through fetch_health, driven whole against a competitor holding the
    port and judged by the real kernel check: `make health`, `make health --json`, crooks-status,
    `make status`, `make install`'s wait for health, CROOKS Control's read. One plain request each;
    the key never sent."""
    import importlib.util

    import control
    import healthcheck
    import status as crooks_status

    local_cli.bind_key(KEY)
    competitor = servers(WHOLE)
    port = competitor.port
    monkeypatch.setattr(lc, "serve_status", lambda p: ("crooks.example.ts.net", ""))
    assert healthcheck.main(["--port", str(port), "--timeout", "3"]) == 0
    assert healthcheck.main(["--port", str(port), "--json"]) == 0
    crooks_status.show(port)
    spec = importlib.util.spec_from_file_location("install_systemd_r11_senders", SCRIPTS / "install_systemd.py")
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)

    class Done:
        stdout, stderr, returncode = "active\n", "", 0

    monkeypatch.setattr(installer, "systemctl", lambda *args: Done())
    assert installer.status(port) == 0
    assert lc.wait_for_health(f"http://127.0.0.1:{port}/health", timeout_s=5) == WHOLE
    assert control.read_health(port) == WHOLE
    capsys.readouterr()
    assert len(competitor.seen) >= 5 and not any(competitor.keyed()), competitor.keyed()


def test_the_key_leaves_through_one_function_only():
    """A guard beside the behaviour above: in the app and the scripts, only launch_common's
    _server_key reads the key to send it. A new sender that reads it some other way fails here
    and has to take the checked path."""
    root = Path(__file__).resolve().parents[1]
    readers = []
    for folder in ("app", "scripts", "experience"):
        for path in sorted((root / folder).rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if path.name == "local_cli.py" and path.parent.name == "app":
                continue
            if "local_cli.headers(" in text or "local_cli.read_key(" in text or ".HEADER:" in text:
                readers.append(path.relative_to(root).as_posix())
    assert readers == ["scripts/launch_common.py"], readers
