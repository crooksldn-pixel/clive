"""Who opened the connection, and who may reach the owner's own routes (the 2026-09-27 deploy
review, F-05A and F-05B).

- F-05B, the header half: X-Forwarded-For and Tailscale-User-Login are claims any process on
  the server can make. With CROOKS_TAILSCALE_VERIFY on (production), a forwarded request counts
  as having come through `tailscale serve` only when the kernel says tailscaled opened the
  connection it arrived on; one that only claims it is refused before any route answers, by
  the one decision the middleware, the write boundary and the owner-only rule all read. One
  the server sent to itself through its own `tailscale serve` is judged as made on the server.
- F-05B, the fail-open half: with no allow-list the owner-only rule answers nobody, as the
  write boundary does.
- F-05A: the six observe routes are the owner's alone.
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest
from starlette.requests import Request

from app import identity
from app.main import app
from app.routes import actions as actions_route
from tests.test_actions_routes import (  # noqa: F401 - `client` is a fixture
    OWNER,
    PROXIED,
    client,
    configure,
)

STRANGER = {"Tailscale-User-Login": "other@example.com", "X-Forwarded-For": "100.64.0.3"}
LINUX = Path("/proc/net/tcp").exists()


# ------------------------------------------------------------------ the kernel's account


def _hex4(address: str, port: int) -> str:
    """How /proc/net/tcp writes an IPv4 address: its 32-bit word in this machine's byte order."""
    import ipaddress

    word = int.from_bytes(ipaddress.ip_address(address).packed, sys.byteorder)
    return f"{word:08X}:{port:04X}"


def _hex6(address: str, port: int) -> str:
    import ipaddress

    packed = ipaddress.ip_address(address).packed
    words = [int.from_bytes(packed[i:i + 4], sys.byteorder) for i in range(0, 16, 4)]
    return "".join(f"{w:08X}" for w in words) + f":{port:04X}"


def _row(local: str, remote: str, inode: int) -> str:
    return f"   0: {local} {remote} 01 00000000:00000000 00:00000000 00000000     0        0 {inode} 1 0000000000000000 20 4 30 10 -1"


def _fake_proc(root: Path, *, tcp: list[str], tcp6: list[str], processes: dict[int, tuple[str, list[int]]]) -> Path:
    header = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode"
    (root / "net").mkdir(parents=True)
    (root / "net" / "tcp").write_text("\n".join([header, *tcp]) + "\n")
    (root / "net" / "tcp6").write_text("\n".join([header, *tcp6]) + "\n")
    for pid, (name, inodes) in processes.items():
        (root / str(pid) / "fd").mkdir(parents=True)
        (root / str(pid) / "comm").write_text(name + "\n")
        for n, inode in enumerate(inodes):
            os.symlink(f"socket:[{inode}]", root / str(pid) / "fd" / str(n + 3))
        os.symlink("/dev/null", root / str(pid) / "fd" / "0")
    return root


def test_the_other_end_of_a_connection_is_found_by_inode_for_ipv4_and_ipv6(tmp_path, monkeypatch):
    proc = _fake_proc(
        tmp_path / "proc",
        tcp=[
            _row(_hex4("127.0.0.1", 8000), _hex4("0.0.0.0", 0), 111),               # the listener
            _row(_hex4("127.0.0.1", 8000), _hex4("127.0.0.1", 40001), 222),         # the app's end
            _row(_hex4("127.0.0.1", 40001), _hex4("127.0.0.1", 8000), 777),         # tailscaled's end
            _row(_hex4("127.0.0.1", 40002), _hex4("127.0.0.1", 8000), 888),         # a local curl's end
            _row(_hex4("127.0.0.1", 40003), _hex4("127.0.0.1", 8000), 0),           # TIME_WAIT: no inode
        ],
        tcp6=[
            _row(_hex6("::1", 40004), _hex6("::1", 8000), 999),
            _row(_hex6("::ffff:127.0.0.1", 40005), _hex6("::ffff:127.0.0.1", 8000), 555),
        ],
        processes={100: ("tailscaled", [777, 999, 555]), 200: ("curl", [888])},
    )
    server = ("127.0.0.1", 8000)
    assert identity.socket_inode(("127.0.0.1", 40001), server, proc=proc) == 777
    assert identity.socket_inode(("127.0.0.1", 40002), server, proc=proc) == 888
    assert identity.socket_inode(("127.0.0.1", 40003), server, proc=proc) is None, "no inode, no answer"
    assert identity.socket_inode(("::1", 40004), ("::1", 8000), proc=proc) == 999
    assert identity.socket_inode(("127.0.0.1", 40005), server, proc=proc) == 555, "an IPv4-mapped entry is the same address"
    assert identity.pids_named("tailscaled", proc=proc) == [100]
    assert identity.socket_inodes(100, proc=proc) == {777, 999, 555}

    monkeypatch.setattr(identity, "PROC", proc)
    assert identity.peer_is_tailscaled(("127.0.0.1", 40001), server) == (True, "opened by tailscaled (pid 100)")
    ok, why = identity.peer_is_tailscaled(("127.0.0.1", 40002), server)
    assert not ok and "something other than tailscaled" in why
    ok, why = identity.peer_is_tailscaled(("127.0.0.1", 49999), server)
    assert not ok and "not opened on this server" in why
    assert identity.peer_is_tailscaled(("::1", 40004), ("::1", 8000))[0]


def test_an_address_rewritten_before_the_app_saw_it_is_refused_and_says_how_to_fix_it():
    """uvicorn's own proxy-header handling replaces the connection's address with the forwarded
    one and a port of 0. Nothing is left to check, so nothing is trusted."""
    ok, why = identity._proc_peer_check(("100.64.0.9", 0), ("127.0.0.1", 8000)) if LINUX else (False, "--no-proxy-headers")
    assert not ok and "--no-proxy-headers" in why


def test_no_tailscaled_or_no_proc_is_a_refusal_never_a_pass(tmp_path, monkeypatch):
    proc = _fake_proc(tmp_path / "proc", tcp=[_row(_hex4("127.0.0.1", 40001), _hex4("127.0.0.1", 8000), 777)],
                      tcp6=[], processes={200: ("curl", [777])})
    monkeypatch.setattr(identity, "PROC", proc)
    ok, why = identity.peer_is_tailscaled(("127.0.0.1", 40001), ("127.0.0.1", 8000))
    assert not ok and "tailscaled is not running" in why
    monkeypatch.setattr(identity, "PROC", tmp_path / "nowhere")
    ok, why = identity.peer_is_tailscaled(("127.0.0.1", 40001), ("127.0.0.1", 8000))
    assert not ok and "no /proc" in why

    def broken(client_, server):
        raise PermissionError("denied")

    identity.bind_peer_check(broken)
    assert identity.peer_is_tailscaled(("127.0.0.1", 1), ("127.0.0.1", 2)) == (False, "who opened the connection could not be read: PermissionError")


@pytest.mark.skipif(not LINUX, reason="the kernel's socket table is a Linux /proc file")
def test_the_kernel_names_the_process_that_opened_a_real_connection(monkeypatch):
    """The same reading, against this machine's own kernel: a real connection, found by inode
    in the process that opened it, and only there."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    opener = socket.socket()
    opener.connect(listener.getsockname())
    accepted, _ = listener.accept()
    try:
        client_end, server_end = opener.getsockname(), listener.getsockname()
        inode = identity.socket_inode(client_end, server_end)
        assert inode, "the kernel lists the connection"
        assert inode in identity.socket_inodes(os.getpid()), "held by the process that opened it"
        assert identity.socket_inode(server_end, client_end) != inode, "the app's own end is another socket"
        ok, why = identity._proc_peer_check(client_end, server_end)
        assert not ok, "this test process is not tailscaled"
        me = Path("/proc/self/comm").read_text().strip()
        monkeypatch.setattr(identity, "PROXY_PROCESS", me)
        ok, why = identity._proc_peer_check(client_end, server_end)
        assert ok and f"pid {os.getpid()}" in why
    finally:
        for s in (opener, accepted, listener):
            s.close()


def test_this_server_knows_its_own_addresses():
    assert identity.is_this_host("127.0.0.1") is True
    assert identity.is_this_host("100.64.0.9, 10.0.0.1") is False, "a tailnet address this machine does not hold"
    assert identity.is_this_host("not an address") is False


# ------------------------------------------------------------------ one decision, read by every gate


def _request(headers: dict[str, str], *, peer=("127.0.0.1", 51000)) -> Request:
    scope = {
        "type": "http", "method": "GET", "path": "/x", "raw_path": b"/x", "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": peer, "server": ("127.0.0.1", 8000), "scheme": "http", "app": app,
    }
    return Request(scope)


def _settings(http, **update):
    http.runtime.settings = http.runtime.settings.model_copy(update=update)
    app.state.allowed_logins = http.runtime.allowed_logins


async def test_forwarding_headers_from_anything_but_tailscaled_are_refused_everywhere(client):  # noqa: F811 - fixtures imported from the suite they belong to
    """F-05B: a process on the server writing both headers is refused by the middleware before
    any route, and the write boundary and the owner-only rule say the same thing on their own."""
    configure(client, local=True)
    _settings(client, tailscale_verify=True)
    identity.bind_peer_check(lambda client_, server: (False, "the connection was opened by something other than tailscaled"))
    for method, path in (("GET", "/whoami"), ("GET", "/objectives"), ("GET", "/displays"), ("GET", "/test-session/status"),
                         ("POST", "/telemetry"), ("POST", "/anticipation/reset"), ("POST", "/actions/prop_x/commit")):
        response = await client.request(method, path, headers=PROXIED)
        assert response.status_code == 403 and response.json() == {"error": "not allowed", "who": "unverified proxy"}, path
    request = _request(PROXIED)
    assert actions_route.proxy_state(request)[0] == actions_route.FORGED
    assert actions_route.principal_check(request)[1].startswith("This request did not come through Tailscale")
    assert actions_route.caller_check(request)[1] == "identity_unverified"
    assert actions_route.caller_identity(request) == "local" and not actions_route.made_on_this_server(request)
    # The same server, the same caller, no claim: made on the server, and the owner said it is him.
    assert (await client.get("/objectives")).status_code == 200


async def test_what_tailscaled_brings_from_another_device_is_judged_by_its_login(client, monkeypatch):  # noqa: F811 - fixtures imported from the suite they belong to
    configure(client, logins=f"{OWNER}, other@example.com")
    _settings(client, tailscale_verify=True)
    identity.bind_peer_check(lambda client_, server: (True, "opened by tailscaled (pid 1)"))
    identity.bind_self_check(lambda address: False)
    # Tailscale says 100.64.0.9 is the owner's and 100.64.0.3 is someone else's.
    identity.bind_runner(lambda cli, address: {"UserProfile": {"LoginName": OWNER if address == "100.64.0.9" else "other@example.com"}})
    monkeypatch.setattr(identity, "cli_path", lambda configured="": "/usr/bin/tailscale")
    request = _request(PROXIED)
    assert actions_route.proxy_state(request) == (actions_route.TAILSCALE, "")
    assert actions_route.principal_check(request) == (OWNER, "")
    assert actions_route.caller_identity(request) == OWNER
    body = (await client.get("/whoami", headers=PROXIED)).json()
    assert body["through"] == "tailscale" and body["proxied"] is True and body["login"] == OWNER
    assert (await client.get("/objectives", headers=PROXIED)).status_code == 200
    # A login on the list whose device Tailscale says is someone else's is refused.
    lying = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.64.0.3"}
    refused = await client.get("/objectives", headers=lying)
    assert refused.status_code == 403 and "different login" in refused.json()["detail"]


async def test_the_server_asking_itself_through_tailscale_is_the_server(client):  # noqa: F811 - fixtures imported from the suite they belong to
    """The server is on the owner's own tailnet login, so what it sends through its own
    `tailscale serve` arrives stamped with his login. It is still a request made on the server."""
    configure(client, local=False)
    _settings(client, tailscale_verify=True)
    identity.bind_peer_check(lambda client_, server: (True, "opened by tailscaled (pid 1)"))
    identity.bind_self_check(lambda address: address == "100.64.0.9")
    body = (await client.get("/whoami", headers=PROXIED)).json()
    assert body["through"] == "this_host" and body["proxied"] is False
    refused = await client.get("/objectives", headers=PROXIED)
    assert refused.status_code == 403 and "CROOKS_WRITES_LOCAL_OWNER" in refused.json()["detail"]
    request = _request(PROXIED)
    assert actions_route.caller_check(request)[1] == "not_authorised_local"
    assert actions_route.made_on_this_server(request) and actions_route.caller_identity(request) == "local"


async def test_with_no_allow_list_the_owners_routes_answer_nobody_as_the_write_boundary_does(client):  # noqa: F811 - fixtures imported from the suite they belong to
    """F-05B: principal_check returned ("local", "") and admitted everyone when the list was
    empty, while caller_check refused. They now fail the same way."""
    configure(client, logins="", local=True)
    for headers in ({}, PROXIED):
        request = _request(headers)
        who, why = actions_route.principal_check(request)
        assert who == "" and "CROOKS_ALLOWED_LOGINS" in why
        assert actions_route.caller_check(request)[1] == "allow_list_missing"
        assert (await client.get("/objectives", headers=headers)).status_code == 403
        assert (await client.get("/displays", headers=headers)).status_code == 403


async def test_the_six_observe_routes_are_the_owners_alone(client, tmp_path):  # noqa: F811 - fixtures imported from the suite they belong to
    """F-05A: they gated on "no X-Forwarded-For", which admitted any process on the server and
    refused every one of the owner's own devices."""
    from app.observability.session import TestSessions
    from app.observability.timeline import Timeline, install

    client.runtime.tests = TestSessions(tmp_path / "logs")
    client.runtime.timeline = install(Timeline(client.runtime.tests))
    configure(client, logins=f"{OWNER}, other@example.com", local=False)
    routes = (("POST", "/test-session/start"), ("GET", "/test-session/status"), ("POST", "/test-session/stop"),
              ("GET", "/anticipation"), ("POST", "/anticipation/reset"))
    for method, path in routes:
        refused = await client.request(method, path, json={"name": "x"} if path.endswith("start") else None)
        assert refused.status_code == 403 and refused.json()["code"] == "not_owner", path
    started = await client.post("/test-session/start", json={"name": "owner"}, headers=PROXIED)
    assert started.status_code == 200 and started.json()["started"]
    assert (await client.get("/test-session/status", headers=PROXIED)).json()["active"] is True
    # Telemetry from the server itself, uninvited, is dropped without a word and never written.
    dropped = await client.post("/telemetry", json={"events": [{"kind": "render", "screen": "orb"}]})
    assert dropped.status_code == 204 and "x-crooks-telemetry" not in dropped.headers
    kept = await client.post("/telemetry", json={"events": [{"kind": "render", "screen": "orb"}]}, headers=PROXIED)
    assert kept.status_code == 204 and kept.headers["x-crooks-telemetry"] == "1"
    stopped = (await client.post("/test-session/stop", headers=PROXIED)).json()
    client.runtime.timeline.flush()
    from app.observability.timeline import read_events

    renders = [e for e in read_events(Path(stopped["path"])) if e["kind"] == "tablet_render"]
    assert len(renders) == 1, "only the owner's device's event is in the record"
    # Not a login on his list: refused before the route (the middleware), as before.
    configure(client, logins=OWNER, local=False)
    assert (await client.get("/anticipation", headers=STRANGER)).status_code == 403


def test_without_the_right_to_read_tailscaleds_files_every_forwarded_request_is_refused(tmp_path, monkeypatch):
    proc = _fake_proc(tmp_path / "proc", tcp=[_row(_hex4("127.0.0.1", 40001), _hex4("127.0.0.1", 8000), 777)],
                      tcp6=[], processes={100: ("tailscaled", [777])})
    monkeypatch.setattr(identity, "PROC", proc)

    def denied(pid, *, proc=None):
        raise PermissionError("not root")

    monkeypatch.setattr(identity, "socket_inodes", denied)
    assert identity.peer_is_tailscaled(("127.0.0.1", 40001), ("127.0.0.1", 8000)) == (
        False, "who opened the connection could not be read: PermissionError")
