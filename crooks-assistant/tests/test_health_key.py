"""The host's own status readers and the server's key (the 2026-09-28 deploy review, round 9,
A1B-KEY and A1B-STATUS; E-app2 E-01).

A1B-KEY: `launch_common.fetch_health` asked /health plainly and, when the answer was liveness
alone, asked again with the server's local command key. Whatever held the loopback port while
the service restarted could answer `limited: true` and be sent the key on the retry, and urllib
followed redirects, so the keyed request could be sent on to anywhere. Now the key is decided on
before anything is asked, sent on one connection only once the kernel says the service itself took
that connection, and never on a redirect. These tests put real listeners on loopback — a
competitor answering `limited`, a service answering a redirect — and look at what each received.
"""

from __future__ import annotations

import http.server
import json
import os
import socket
import sys
import threading
from pathlib import Path

import pytest

from app import identity, local_cli

KEY = "k" * 43
HEADER = local_cli.HEADER.lower()
LINUX = Path("/proc/net/tcp").exists()


def _scripts():
    scripts = str(Path(__file__).resolve().parents[1] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import launch_common

    return launch_common


class _Listener:
    """A real HTTP listener on loopback that writes down every request it is sent — its path, its
    headers and the client's port — and answers as told: a JSON body, or a redirect."""

    def __init__(self, body: dict | None = None, *, redirect: str = "", refuse_key: bool = False) -> None:
        self.seen: list[dict] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 - the standard library's name
                outer.seen.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                                   "port": self.client_address[1]})
                if refuse_key and HEADER in outer.seen[-1]["headers"]:
                    # A build from before /health took the key: the door refuses it outright.
                    data = b'{"code": "local_key_misused"}'
                    self.send_response(403)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if redirect:
                    self.send_response(302)
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

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/health"

    def keyed(self) -> list[bool]:
        return [HEADER in request["headers"] for request in self.seen]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture()
def lc():
    module = _scripts()
    yield module
    module.bind_listener_check(None)


@pytest.fixture()
def listeners():
    made: list[_Listener] = []

    def make(*args, **kwargs) -> _Listener:
        made.append(_Listener(*args, **kwargs))
        return made[-1]

    yield make
    for listener in made:
        listener.close()


LIMITED = {"status": "ok", "build": "b", "uptime_s": 1.0, "limited": True, "checks": {}}
WHOLE = {"status": "ok", "build": "b", "checks": {"speech": {"ok": True}, "claude": {"ok": True}, "shopify": {"ok": True}}}


@pytest.mark.skipif(not LINUX, reason="the kernel's account of a connection is a Linux /proc file")
def test_a_competitor_answering_limited_on_the_port_is_never_sent_the_key(lc, listeners):
    """A1B-KEY: a process that is not the service holds the port (here, this test's own listener,
    which is in no crooks-assistant.service cgroup) and answers `limited`. The reader, which can
    read the key, is answered once, plainly: no second request, and no request carrying the key.
    Decided by the real kernel check, nothing stood in for."""
    local_cli.bind_key(KEY)
    competitor = listeners(LIMITED)
    assert lc.fetch_health(competitor.url) == LIMITED
    assert competitor.keyed() == [False], "one plain question, and the key never sent"
    probe = socket.create_connection(("127.0.0.1", competitor.port))
    try:
        ok, why = lc._taken_by_the_service(probe)
    finally:
        probe.close()
    assert ok is False and "crooks-assistant.service" in why


def test_the_key_is_decided_before_anything_is_asked_never_on_a_limited_answer(lc, listeners):
    """A1B-KEY: the old reader retried with the key BECAUSE the plain answer was limited. Now, when
    the connection is not the service's, a limited answer is simply the answer; when it is the
    service's, the key goes on the first and only request — there is no plain question first for
    anything to answer `limited` to."""
    local_cli.bind_key(KEY)
    listener = listeners(LIMITED)
    lc.bind_listener_check(lambda sock: (False, "taken by something else"))
    assert lc.fetch_health(listener.url) == LIMITED and listener.keyed() == [False]
    service = listeners(WHOLE)
    checked: list[int] = []

    def the_service(sock):
        checked.append(sock.getsockname()[1])
        return True, "taken by crooks-assistant.service (pid 1)"

    lc.bind_listener_check(the_service)
    assert lc.fetch_health(service.url) == WHOLE
    assert service.keyed() == [True] and service.seen[0]["headers"][HEADER] == KEY
    assert checked == [service.seen[0]["port"]], "the key went down the very connection that was checked"
    # A build that does not take the key on /health yet refuses it; the plain answer stands.
    older = listeners(LIMITED, refuse_key=True)
    assert lc.fetch_health(older.url) == LIMITED and older.keyed() == [True, False]


def test_a_redirect_is_never_followed_with_the_key_or_without_it(lc, listeners):
    """A1B-KEY: urllib followed redirects, so a keyed request could be sent on to anywhere. The
    service's own connection answering a redirect sends nothing further; nor does a plain read."""
    elsewhere = listeners(WHOLE)
    redirecting = listeners(redirect=f"http://127.0.0.1:{elsewhere.port}/stolen")
    local_cli.bind_key(KEY)
    lc.bind_listener_check(lambda sock: (True, "taken by crooks-assistant.service (pid 1)"))
    assert lc.fetch_health(redirecting.url) is None
    assert redirecting.keyed() == [True, False], "asked with the key, then plainly; neither followed"
    assert elsewhere.seen == [], "nothing reached the redirect's target"
    local_cli.bind_key(None)
    assert lc.fetch_health(redirecting.url) is None and elsewhere.seen == []


def test_the_key_is_read_only_for_the_servers_own_loopback_and_never_goes_through_a_proxy(lc, listeners, monkeypatch):
    """What the round-8 test held, kept: the key is for http on 127.0.0.1 or ::1 only; a user who
    cannot read it sends none; and neither read goes through a proxy the environment names."""
    local_cli.bind_key(KEY)
    lc.bind_listener_check(lambda sock: (True, "taken by crooks-assistant.service (pid 1)"))
    for url in ("http://100.64.0.9:8000/health", "https://127.0.0.1:8000/health", "http://localhost:8000/health",
                "https://crooks.example.com/health"):
        assert lc._server_key(url) == {}, url
    assert lc._server_key("http://127.0.0.1:8000/health") == {local_cli.HEADER: KEY}
    assert lc._server_key("http://[::1]:8000/health?fresh=1") == {local_cli.HEADER: KEY}
    proxy = listeners(WHOLE)
    service = listeners(WHOLE)
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, f"http://127.0.0.1:{proxy.port}")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    assert lc.fetch_health(service.url + "?fresh=1") == WHOLE and service.keyed() == [True]
    assert service.seen[0]["path"] == "/health?fresh=1"
    local_cli.bind_key(None)
    assert lc.fetch_health(service.url) == WHOLE and service.keyed() == [True, False]
    assert proxy.seen == [], "neither read went through the proxy"


def test_off_linux_the_key_is_not_even_read(lc, monkeypatch):
    """Only a Linux server can show who took a connection, so elsewhere the key stays unread: a Mac
    that speaks for the owner answers its own readers in full without it."""
    local_cli.bind_key(KEY)
    monkeypatch.setattr(lc, "is_linux", lambda: False)
    assert lc._server_key("http://127.0.0.1:8000/health") == {}


# ------------------------------------------------------------------ the kernel's answer


def _cgroup_for(tmp_path: Path, pids: list[int]) -> Path:
    root = tmp_path / "cgroup"
    unit = root / "system.slice" / identity.SERVICE_UNIT
    unit.mkdir(parents=True)
    (unit / "cgroup.procs").write_text("".join(f"{pid}\n" for pid in pids))
    return root


@pytest.mark.skipif(not LINUX, reason="the kernel's account of a connection is a Linux /proc file")
def test_the_kernel_says_who_took_the_connection_and_only_the_units_own_process_counts(tmp_path, monkeypatch):
    """identity.far_end_held_by, against this machine's real socket table and open files: a
    listener in this process accepts; the far end of the reader's connection is held by this
    process. Counted as the unit's only when this process is listed in the unit's (root-only)
    cgroup AND its own cgroup file names exactly that unit."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    accepted: list[socket.socket] = []
    taker = threading.Thread(target=lambda: accepted.append(listener.accept()[0]), daemon=True)
    taker.start()
    reader = socket.create_connection(listener.getsockname())
    taker.join(timeout=5)
    local, remote = reader.getsockname()[:2], reader.getpeername()[:2]
    try:
        identity.bind_root_only(lambda path: True)
        me = os.getpid()
        monkeypatch.setattr(identity, "in_unit_cgroup", lambda pid, unit, proc=None: pid == me)
        assert identity.far_end_held_by(local, remote, cgroup=_cgroup_for(tmp_path / "a", [me]))[0] is True
        # Listed, but its own cgroup file says otherwise (a pid reused by a process elsewhere).
        monkeypatch.setattr(identity, "in_unit_cgroup", lambda pid, unit, proc=None: False)
        assert identity.far_end_held_by(local, remote, cgroup=_cgroup_for(tmp_path / "b", [me]))[0] is False
        # Not listed in the unit at all: the holder is not the service.
        monkeypatch.setattr(identity, "in_unit_cgroup", lambda pid, unit, proc=None: True)
        ok, why = identity.far_end_held_by(local, remote, cgroup=_cgroup_for(tmp_path / "c", [1]))
        assert ok is False and "something other than" in why
        # A cgroup anyone could join is no evidence.
        identity.bind_root_only(lambda path: False)
        ok, why = identity.far_end_held_by(local, remote, cgroup=_cgroup_for(tmp_path / "d", [me]))
        assert ok is False and "not root" in why
        # No unit at all.
        ok, why = identity.far_end_held_by(local, remote, cgroup=tmp_path / "none")
        assert ok is False and "is not running" in why
    finally:
        reader.close()
        for s in (*accepted, listener):
            s.close()


@pytest.mark.skipif(not LINUX, reason="the kernel's account of a connection is a Linux /proc file")
def test_a_connection_nobody_has_accepted_is_nobodys(tmp_path, monkeypatch):
    """A connection waiting in a listener's queue has no inode yet: who holds it cannot be known,
    so after the wait the answer is no, and the key is not sent."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(4)
    reader = socket.create_connection(listener.getsockname())
    try:
        identity.bind_root_only(lambda path: True)
        monkeypatch.setattr(identity, "in_unit_cgroup", lambda pid, unit, proc=None: True)
        ok, why = identity.far_end_held_by(reader.getsockname()[:2], reader.getpeername()[:2], wait_s=0.2,
                                           cgroup=_cgroup_for(tmp_path, [os.getpid()]))
        assert ok is False and "in time" in why
    finally:
        reader.close()
        listener.close()


def test_a_process_is_the_units_only_by_the_units_whole_cgroup_path(tmp_path):
    """A user's own service can carry the system service's name under user.slice; only
    /system.slice/<unit>, whole, is the unit."""
    proc = tmp_path / "proc"
    unit = identity.SERVICE_UNIT
    cases = {
        1: f"0::/system.slice/{unit}\n",
        2: f"1:name=systemd:/system.slice/{unit}\n0::/system.slice/{unit}\n",
        3: f"0::/user.slice/user-1000.slice/user@1000.service/app.slice/{unit}\n",
        4: f"0::/system.slice/{unit}/child\n",
        5: "0::/system.slice/other.service\n",
        6: f"0::/evil/system.slice/{unit}\n",
    }
    for pid, text in cases.items():
        (proc / str(pid)).mkdir(parents=True)
        (proc / str(pid) / "cgroup").write_text(text)
    assert {pid for pid in cases if identity.in_unit_cgroup(pid, unit, proc=proc)} == {1, 2}
    assert identity.in_unit_cgroup(99, unit, proc=proc) is False, "a process that has gone is no one's"


# ------------------------------------------------------------------ A1B-STATUS and E-01


def _installer():
    import importlib.util

    _scripts()
    here = Path(__file__).resolve().parents[1] / "scripts" / "install_systemd.py"
    spec = importlib.util.spec_from_file_location("install_systemd_status_under_test", here)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Done:
    def __init__(self, stdout: str) -> None:
        self.stdout, self.stderr, self.returncode = stdout, "", 0


@pytest.mark.parametrize("health,expect", [
    (WHOLE, 0),
    (LIMITED, 1),
    ({"status": "ok", "build": "b"}, 1),
    ({"status": "ok", "build": "b", "checks": {}}, 1),
    (None, 1),
])
def test_make_status_is_well_only_on_a_health_answer_that_carries_its_checks(monkeypatch, capsys, health, expect):
    """A1B-STATUS: `install_systemd.status` returned success whenever the unit was active and
    /health answered at all — a `limited` answer, which says nothing of the essentials, included."""
    installer = _installer()
    monkeypatch.setattr(installer, "systemctl", lambda *args: _Done("active" if args[0] == "is-active" else "enabled"))
    monkeypatch.setattr(installer.lc, "serve_status", lambda port: ("crooks.example.ts.net", ""))
    monkeypatch.setattr(installer.lc, "fetch_health", lambda url, timeout_s=8.0: health)
    assert installer.status(8000) == expect
    if health is LIMITED:
        assert "the detail is the owner's" in capsys.readouterr().out


def test_crooks_status_reads_limited_whole_and_partial_answers_honestly(monkeypatch, capsys):
    """E-01: crooks-status's verdict, through the real helpers (launch_common.health_limited and
    summarise_health, not stood in for): a whole answer with the essentials well is 0; a limited
    one is 1 and says why; one that leaves an essential out is 1 and names it, where it used to
    count only the essentials it happened to be given."""
    lc = _scripts()
    import status

    answers = {"whole": WHOLE, "limited": LIMITED,
               "partial": {"status": "ok", "build": "b", "checks": {"speech": {"ok": True}}},
               "empty": {"status": "ok", "build": "b", "checks": {}}}
    current = {"answer": WHOLE}
    monkeypatch.setattr(lc, "fetch_health", lambda url, timeout_s=8.0: current["answer"])
    monkeypatch.setattr(lc, "serve_status", lambda port: ("crooks.example.ts.net", ""))
    results = {}
    for name, answer in answers.items():
        current["answer"] = answer
        results[name] = status.show(8000)
        results[name + "_out"] = capsys.readouterr().out
    assert results["whole"] == 0 and "Unknown" not in results["whole_out"]
    assert results["limited"] == 1 and "the detail is the owner's" in results["limited_out"]
    assert results["partial"] == 1 and "not reported: Claude, Shopify" in results["partial_out"]
    assert results["empty"] == 1 and "not reported: hearing, Claude, Shopify" in results["empty_out"]
    assert lc.health_limited(LIMITED) is True and lc.health_limited(WHOLE) is False and lc.health_limited(None) is False
    assert lc.summarise_health(WHOLE).startswith("all good") and lc.summarise_health(None) == "the assistant is not answering"
