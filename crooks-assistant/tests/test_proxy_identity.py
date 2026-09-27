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

import ipaddress
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


def _fake_proc(root: Path, *, tcp: list[str], tcp6: list[str],
               processes: dict[int, tuple[str, list[int]]], cgroup: Path | None = None,
               unit_pids: list[int] | None = None) -> Path:
    """A /proc and a cgroup tree. Each process is (what it is, the socket inodes it holds); what it
    is decides its comm, its exe and its cgroup:
      tailscaled   the service: exe /usr/sbin/tailscaled, in system.slice/tailscaled.service
      upgraded     the service after a package upgrade: exe "/usr/sbin/tailscaled (deleted)"
      renamed      anything that called itself tailscaled: comm tailscaled, exe python, user.slice
      helper       another binary inside the service's cgroup (an ExecStartPre)
      curl         an ordinary local process
    The unit's cgroup.procs lists `unit_pids`, by default every tailscaled/upgraded/helper pid."""
    kinds = {
        "tailscaled": ("tailscaled", "/usr/sbin/tailscaled", "0::/system.slice/tailscaled.service"),
        "upgraded": ("tailscaled", "/usr/sbin/tailscaled (deleted)", "0::/system.slice/tailscaled.service"),
        "renamed": ("tailscaled", "/usr/bin/python3.12", "0::/user.slice/user-1000.slice/session-3.scope"),
        "helper": ("sh", "/usr/bin/dash", "0::/system.slice/tailscaled.service"),
        "curl": ("curl", "/usr/bin/curl", "0::/user.slice/user-1000.slice/session-3.scope"),
    }
    header = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode"
    (root / "net").mkdir(parents=True)
    (root / "net" / "tcp").write_text("\n".join([header, *tcp]) + "\n")
    (root / "net" / "tcp6").write_text("\n".join([header, *tcp6]) + "\n")
    for pid, (kind, inodes) in processes.items():
        comm, exe, group = kinds[kind]
        (root / str(pid) / "fd").mkdir(parents=True)
        (root / str(pid) / "comm").write_text(comm + "\n")
        (root / str(pid) / "cgroup").write_text(group + "\n")
        os.symlink(exe, root / str(pid) / "exe")
        for n, inode in enumerate(inodes):
            os.symlink(f"socket:[{inode}]", root / str(pid) / "fd" / str(n + 3))
        os.symlink("/dev/null", root / str(pid) / "fd" / "0")
    if cgroup is not None:
        listed = unit_pids if unit_pids is not None else [
            pid for pid, (kind, _) in processes.items() if kind in ("tailscaled", "upgraded", "helper")]
        unit = cgroup / "system.slice" / "tailscaled.service"
        unit.mkdir(parents=True)
        (unit / "cgroup.procs").write_text("".join(f"{pid}\n" for pid in listed))
    return root


SERVER = ("127.0.0.1", 8000)


class _Alive:
    """A pidfd stand-in for the fake /proc: the pinned process stays alive unless told."""

    def __init__(self, pid, *, dies=False):
        self.pid, self.dies, self.closed = pid, dies, False

    def alive(self):
        return not self.dies

    def close(self):
        self.closed = True


def _world(tmp_path, processes, **kw):
    # The fake /proc's pids are not this machine's: pinning and root ownership are stood in for,
    # and the tests that are about them say so themselves.
    identity.bind_pinner(lambda pid: _Alive(pid))
    identity.bind_root_only(lambda path: True)
    return _fake_proc(
        tmp_path / "proc", cgroup=tmp_path / "cgroup", processes=processes,
        tcp=[
            _row(_hex4("127.0.0.1", 8000), _hex4("0.0.0.0", 0), 111),               # the listener
            _row(_hex4("127.0.0.1", 8000), _hex4("127.0.0.1", 40001), 222),         # the app's end
            _row(_hex4("127.0.0.1", 40001), _hex4("127.0.0.1", 8000), 777),         # tailscaled's end
            _row(_hex4("127.0.0.1", 40002), _hex4("127.0.0.1", 8000), 888),         # someone else's end
            _row(_hex4("127.0.0.1", 40003), _hex4("127.0.0.1", 8000), 0),           # TIME_WAIT: no inode
            _row(_hex4("127.0.0.1", 40006), _hex4("127.0.0.1", 8000), 666),         # a helper's end
        ],
        tcp6=[
            _row(_hex6("::1", 40004), _hex6("::1", 8000), 999),
            _row(_hex6("::ffff:127.0.0.1", 40005), _hex6("::ffff:127.0.0.1", 8000), 555),
        ], **kw)


def test_the_other_end_of_a_connection_is_found_by_inode_for_ipv4_and_ipv6(tmp_path, monkeypatch):
    proc = _world(tmp_path, {100: ("tailscaled", [777, 999, 555]), 200: ("curl", [888])})
    assert identity.socket_inode(("127.0.0.1", 40001), SERVER, proc=proc) == 777
    assert identity.socket_inode(("127.0.0.1", 40002), SERVER, proc=proc) == 888
    assert identity.socket_inode(("127.0.0.1", 40003), SERVER, proc=proc) is None, "no inode, no answer"
    assert identity.socket_inode(("::1", 40004), ("::1", 8000), proc=proc) == 999
    assert identity.socket_inode(("127.0.0.1", 40005), SERVER, proc=proc) == 555, "an IPv4-mapped entry is the same address"
    assert identity.socket_inodes(100, proc=proc) == {777, 999, 555}

    monkeypatch.setattr(identity, "PROC", proc)
    monkeypatch.setattr(identity, "CGROUP", tmp_path / "cgroup")
    assert identity.peer_is_tailscaled(("127.0.0.1", 40001), SERVER) == (True, "opened by tailscaled (pid 100)")
    ok, why = identity.peer_is_tailscaled(("127.0.0.1", 40002), SERVER)
    assert not ok and "something other than tailscaled" in why
    ok, why = identity.peer_is_tailscaled(("127.0.0.1", 49999), SERVER)
    assert not ok and "not opened on this server" in why
    assert identity.peer_is_tailscaled(("::1", 40004), ("::1", 8000))[0]


def test_a_process_that_calls_itself_tailscaled_is_not_tailscaled(tmp_path, monkeypatch):
    """Round 6, F-05B: comm is whatever a process says it is (prctl PR_SET_NAME). The service is
    what the kernel says: the unit's own cgroup, and the file it was exec'd from."""
    proc = _world(tmp_path, {100: ("tailscaled", [777]), 200: ("renamed", [888]), 300: ("helper", [666])})
    monkeypatch.setattr(identity, "PROC", proc)
    monkeypatch.setattr(identity, "CGROUP", tmp_path / "cgroup")
    assert (proc / "200" / "comm").read_text().strip() == "tailscaled"
    assert identity.unit_pids(cgroup=tmp_path / "cgroup") == [100, 300]
    assert identity.is_proxy_process(100) and not identity.is_proxy_process(200)
    assert not identity.is_proxy_process(300), "in the unit's cgroup, but not the tailscaled binary"
    ok, why = identity.peer_is_tailscaled(("127.0.0.1", 40002), SERVER)
    assert not ok and "something other than tailscaled" in why
    assert not identity.peer_is_tailscaled(("127.0.0.1", 40006), SERVER)[0], "a helper in the unit is not the proxy"
    # Listed in the unit's cgroup.procs but not in it by its own account: not trusted either.
    proc2 = _world(tmp_path / "b", {200: ("renamed", [888])}, unit_pids=[200])
    monkeypatch.setattr(identity, "PROC", proc2)
    monkeypatch.setattr(identity, "CGROUP", tmp_path / "b" / "cgroup")
    ok, why = identity.peer_is_tailscaled(("127.0.0.1", 40002), SERVER)
    assert not ok and "no tailscaled process is running" in why


def test_nothing_positive_is_remembered(tmp_path, monkeypatch):
    """Round 6, F-05B: a cached yes could outlive the socket it was about, and the kernel reuses
    inode numbers. Every check reads tailscaled's open files afresh."""
    proc = _world(tmp_path, {100: ("tailscaled", [777])})
    monkeypatch.setattr(identity, "PROC", proc)
    monkeypatch.setattr(identity, "CGROUP", tmp_path / "cgroup")
    assert identity.peer_is_tailscaled(("127.0.0.1", 40001), SERVER)[0]
    os.unlink(proc / "100" / "fd" / "3")                  # tailscaled closed that connection
    ok, why = identity.peer_is_tailscaled(("127.0.0.1", 40001), SERVER)
    assert not ok and "something other than tailscaled" in why
    assert not hasattr(identity, "_holdings") and not hasattr(identity, "_proxy_pids")


def test_the_service_after_a_package_upgrade_is_still_the_service(tmp_path, monkeypatch):
    proc = _world(tmp_path, {100: ("upgraded", [777])})
    monkeypatch.setattr(identity, "PROC", proc)
    monkeypatch.setattr(identity, "CGROUP", tmp_path / "cgroup")
    assert identity.peer_is_tailscaled(("127.0.0.1", 40001), SERVER) == (True, "opened by tailscaled (pid 100)")


def test_an_address_rewritten_before_the_app_saw_it_is_refused_and_says_how_to_fix_it():
    """uvicorn's own proxy-header handling replaces the connection's address with the forwarded
    one and a port of 0. Nothing is left to check, so nothing is trusted."""
    ok, why = identity._proc_peer_check(("100.64.0.9", 0), SERVER) if LINUX else (False, "--no-proxy-headers")
    assert not ok and "--no-proxy-headers" in why


def test_no_tailscaled_or_no_proc_is_a_refusal_never_a_pass(tmp_path, monkeypatch):
    proc = _world(tmp_path, {200: ("curl", [777])})
    monkeypatch.setattr(identity, "PROC", proc)
    monkeypatch.setattr(identity, "CGROUP", tmp_path / "cgroup")
    ok, why = identity.peer_is_tailscaled(("127.0.0.1", 40001), SERVER)
    assert not ok and "no tailscaled process is running" in why
    monkeypatch.setattr(identity, "CGROUP", tmp_path / "no-cgroups")
    assert not identity.peer_is_tailscaled(("127.0.0.1", 40001), SERVER)[0]
    monkeypatch.setattr(identity, "PROC", tmp_path / "nowhere")
    ok, why = identity.peer_is_tailscaled(("127.0.0.1", 40001), SERVER)
    assert not ok and "no /proc" in why

    def broken(client_, server):
        raise PermissionError("denied")

    identity.bind_peer_check(broken)
    assert identity.peer_is_tailscaled(("127.0.0.1", 1), ("127.0.0.1", 2)) == (False, "who opened the connection could not be read: PermissionError")


_RENAMED_OPENER = """
import ctypes, socket, sys
libc = ctypes.CDLL(None, use_errno=True)
libc.prctl(15, b"tailscaled", 0, 0, 0)            # PR_SET_NAME: what the reviewer did
s = socket.create_connection(("127.0.0.1", int(sys.argv[1])))
print(s.getsockname()[1], flush=True)
sys.stdin.read()
"""


@pytest.mark.skipif(not LINUX, reason="the kernel's socket table is a Linux /proc file")
def test_the_kernel_refuses_a_real_process_renamed_tailscaled(monkeypatch):
    """The reviewer's own demonstration, end to end on this machine's kernel: a process renames
    itself tailscaled and opens a real connection. It holds that connection's inode, and it is
    refused, because it is not in tailscaled.service and was not exec'd from tailscaled."""
    import subprocess
    import sys

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    opener = subprocess.Popen([sys.executable, "-c", _RENAMED_OPENER, str(listener.getsockname()[1])],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    accepted = None
    try:
        port = int(opener.stdout.readline())
        accepted, _ = listener.accept()
        client_end = ("127.0.0.1", port)
        assert Path(f"/proc/{opener.pid}/comm").read_text().strip() == "tailscaled", "renamed, as in the review"
        inode = identity.socket_inode(client_end, listener.getsockname())
        assert inode and inode in identity.socket_inodes(opener.pid), "it really holds the connection"
        assert not identity.is_proxy_process(opener.pid)
        ok, why = identity._proc_peer_check(client_end, listener.getsockname())
        assert not ok, why
    finally:
        opener.stdin.close()
        opener.wait(timeout=10)
        for s in (accepted, listener):
            if s is not None:
                s.close()


def _addresses(root: Path, v4: list[str], v6: list[str] | None) -> Path:
    """A /proc/net/fib_trie and if_inet6 holding these as the host's own (None: no IPv6)."""
    (root / "net").mkdir(parents=True, exist_ok=True)
    trie = ["Main:", "  +-- 0.0.0.0/0 3 0 5", "     |-- 0.0.0.0", "        /0 universe UNICAST"]
    for address in ["127.0.0.1", *v4]:
        trie += [f"     |-- {address}", "        /32 host LOCAL"]
    trie += ["     |-- 100.64.0.9", "        /32 link UNICAST"]          # a route, not an address held
    (root / "net" / "fib_trie").write_text("\n".join(trie) + "\n")
    inet6 = root / "net" / "if_inet6"
    if v6 is None:
        inet6.unlink(missing_ok=True)
    else:
        rows = [f"{ipaddress.IPv6Address(a).exploded.replace(':', '')} 02 40 00 80 tailscale0" for a in ["::1", *v6]]
        inet6.write_text("\n".join(rows) + "\n")
    return root


def test_this_servers_own_addresses_are_the_kernels_read_fresh_every_time(tmp_path, monkeypatch):
    """Round 6 took this from bind(), which net.ipv4.ip_nonlocal_bind turns into "every
    address"; round 7 found `tailscale ip`'s ten-minute cache let an address the server gained
    in that window pass as a device's. The kernel's own tables of the host's addresses are read
    on every request: gained, it is this host at once; unreadable, the caller refuses."""
    root = _addresses(tmp_path / "proc", ["100.101.102.103"], ["fd7a:115c:a1e0::abcd"])
    monkeypatch.setattr(identity, "PROC", root)
    monkeypatch.setattr(socket.socket, "bind", lambda self, address: None)   # as if nonlocal bind were on
    assert identity.is_this_host("100.101.102.103") is True
    assert identity.is_this_host("fd7a:115c:a1e0::abcd") is True
    assert identity.is_this_host("100.64.0.9, 10.0.0.1") is False, "a route through the host is not an address it holds"
    assert identity.is_this_host("not an address") is False
    # The server's tailnet address changes: the very next request knows it.
    _addresses(root, ["100.101.102.200"], ["fd7a:115c:a1e0::abcd"])
    assert identity.is_this_host("100.101.102.200") is True and identity.is_this_host("100.101.102.103") is False
    # IPv6 switched off on the host: no IPv6 address is its own, and IPv4 still answers.
    _addresses(root, ["100.101.102.200"], None)
    assert identity.is_this_host("fd7a:115c:a1e0::abcd") is False and identity.is_this_host("100.101.102.200") is True
    # The IPv4 table unreadable: it cannot say.
    (root / "net" / "fib_trie").unlink()
    assert identity.is_this_host("100.101.102.200") is None
    assert not hasattr(identity, "own_addresses") and not hasattr(identity, "SELF_CACHE_S"), "nothing is remembered"


@pytest.mark.skipif(not LINUX, reason="the kernel's own address tables are Linux /proc files")
def test_on_this_machine_the_kernels_tables_name_its_loopback():
    mine = identity.local_addresses()
    assert mine is not None and "127.0.0.1" in mine


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
    _settings(client, tailscale_verify=True, local_owner=False)
    identity.bind_peer_check(lambda client_, server: (True, "opened by tailscaled (pid 1)"))
    identity.bind_self_check(lambda address: address == "100.64.0.9")
    body = (await client.get("/whoami", headers=PROXIED)).json()
    assert body["through"] == "this_host" and body["proxied"] is False
    refused = await client.get("/objectives", headers=PROXIED)
    assert refused.status_code == 403 and refused.json()["code"] == "not_authorised_local"
    assert "CROOKS_LOCAL_OWNER" in refused.json()["detail"]
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
    _settings(client, local_owner=False)
    routes = (("POST", "/test-session/start"), ("GET", "/test-session/status"), ("POST", "/test-session/stop"),
              ("GET", "/anticipation"), ("POST", "/anticipation/reset"))
    for method, path in routes:
        refused = await client.request(method, path, json={"name": "x"} if path.endswith("start") else None)
        assert refused.status_code == 403 and refused.json()["code"] == "not_authorised_local", path
    started = await client.post("/test-session/start", json={"name": "owner"}, headers=PROXIED)
    assert started.status_code == 200 and started.json()["started"]
    assert (await client.get("/test-session/status", headers=PROXIED)).json()["active"] is True
    # Telemetry from the server itself, uninvited, is refused at the door and never written.
    dropped = await client.post("/telemetry", json={"events": [{"kind": "render", "screen": "orb"}]})
    assert dropped.status_code == 403 and "x-crooks-telemetry" not in dropped.headers
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
    proc = _world(tmp_path, {100: ("tailscaled", [777])})
    monkeypatch.setattr(identity, "PROC", proc)
    monkeypatch.setattr(identity, "CGROUP", tmp_path / "cgroup")

    def denied(pid, *, proc=None):
        raise PermissionError("not root")

    monkeypatch.setattr(identity, "socket_inodes", denied)
    assert identity.peer_is_tailscaled(("127.0.0.1", 40001), ("127.0.0.1", 8000)) == (
        False, "who opened the connection could not be read: PermissionError")


async def test_when_this_servers_own_addresses_cannot_be_read_a_forwarded_request_is_refused(client):  # noqa: F811 - fixtures imported from the suite they belong to
    """F-05B-AVAIL's other half: if Tailscale cannot say which addresses are this server's, a
    request the server sent itself cannot be told from the owner's device, so neither is let in."""
    configure(client, local=True)
    client.runtime.settings = client.runtime.settings.model_copy(update={"tailscale_verify": True})
    identity.bind_peer_check(lambda client_, server: (True, "opened by tailscaled (pid 1)"))
    identity.bind_self_check(lambda address: None)
    refused = await client.get("/whoami", headers=PROXIED)
    assert refused.status_code == 403 and refused.json() == {"error": "not allowed", "who": "unverified proxy"}
    request = _request(PROXIED)
    assert actions_route.proxy_state(request) == (actions_route.FORGED, "this server's own addresses could not be read from the kernel")


async def test_every_route_the_app_serves_is_the_owners_unless_it_is_named_public(client):  # noqa: F811 - fixtures imported from the suite they belong to
    """Round 6 (F-NEW-TOOLS, B-01, F-NEW-PAD): gating routers one at a time left /turn, and so
    every tool the model reaches through a turn, and the pad's heartbeat, open to any caller on
    the server. The rule is now at the door. This walks every route the app serves, so a route
    added later is covered or this fails."""
    import re as _re

    from app.main import PUBLIC_PATHS, PUBLIC_PREFIXES, is_public

    assert PUBLIC_PATHS == frozenset({"/health", "/ping", "/whoami", "/", "/display", "/sw.js",
                                      "/manifest.webmanifest", "/favicon.ico"})
    assert PUBLIC_PREFIXES == ("/static/",)
    configure(client, logins=OWNER, local=False)
    _settings(client, local_owner=False)
    stranger = {"Tailscale-User-Login": "other@example.com", "X-Forwarded-For": "100.64.0.3"}
    checked = []
    # Every route the app documents (the four it does not are page files, all public), and the
    # documentation itself.
    served = [(template, method.upper()) for template, item in app.openapi()["paths"].items() for method in item]
    served += [("/openapi.json", "GET"), ("/docs", "GET"), ("/redoc", "GET")]
    assert len(served) > 50
    for template, method in served:
        path = _re.sub(r"\{[^}]+\}", "scr_000000000000", template)
        if is_public(path):
            response = await client.request(method, path)
            assert response.status_code != 403 or "not the owner" not in response.text, path
            continue
        for headers, code in (({}, "not_authorised_local"), (stranger, None)):
            response = await client.request(method, path, headers=headers)
            assert response.status_code == 403, (method, path, headers, response.status_code)
            if code:
                assert response.json()["code"] == code, (path, response.json())
        checked.append(path)
    for must in ("/turn", "/command", "/pad/heartbeat", "/pad", "/telemetry", "/objectives", "/displays", "/tools",
                 "/speak", "/support/investigate", "/openapi.json", "/media/shopify/scr_000000000000/scr_000000000000"):
        assert must in checked, must
    # And the owner's own device is let through the door (whatever the route then says).
    for path in ("/turn", "/tools", "/pad/heartbeat"):
        response = await client.request("POST" if path != "/tools" else "GET", path, headers=PROXIED, json={})
        assert "not the owner" not in response.text, path


# ------------------------------------------------ round 6, F-05B: at the gates, from the kernel's answer


def _gates(request) -> tuple[str, str]:
    """What the owner-record rule and the business-write boundary each say: their codes."""
    _who, owner_code, _detail = actions_route.principal_verdict(request)
    _caller, write_code, _detail, _spoken = actions_route.caller_check(request)
    return owner_code, write_code


@pytest.fixture()
def owner_world(client, monkeypatch):  # noqa: F811
    """Production's switches, with Tailscale verification on and whois saying every forwarded
    address is the owner's — so whenever a gate refuses below, it is the kernel's answer about
    who opened the connection that refused it, and nothing else."""
    configure(client, logins=OWNER, local=False)
    _settings(client, tailscale_verify=True, local_owner=False, writes_local_owner=False)
    identity.bind_self_check(lambda address: False)
    identity.bind_runner(lambda cli, address: {"UserProfile": {"LoginName": OWNER}})
    monkeypatch.setattr(identity, "cli_path", lambda configured="": "/usr/bin/tailscale")
    return client


def _point_at(monkeypatch, tmp_path, processes, **kw):
    proc = _world(tmp_path, processes, **kw)
    monkeypatch.setattr(identity, "PROC", proc)
    monkeypatch.setattr(identity, "CGROUP", tmp_path / "cgroup")
    return proc


def _from(port: int) -> Request:
    return _request(PROXIED, peer=("127.0.0.1", port))


REFUSED = ("identity_unverified", "identity_unverified")


async def test_at_both_gates_a_renamed_process_is_refused_and_the_real_proxy_is_not(owner_world, tmp_path, monkeypatch):
    _point_at(monkeypatch, tmp_path, {100: ("tailscaled", [777]), 200: ("renamed", [888])})
    assert _gates(_from(40001)) == ("", ""), "tailscaled's own connection: the owner, at both gates"
    assert _gates(_from(40002)) == REFUSED, "the renamed process's connection, with the owner's headers"


async def test_at_both_gates_a_reused_pid_is_not_the_proxy(owner_world, tmp_path, monkeypatch):
    """tailscaled stops and its pid is given to something else holding the same socket number,
    while the unit's cgroup.procs still lists it: the pid's own cgroup and executable decide."""
    _point_at(monkeypatch, tmp_path / "a", {100: ("tailscaled", [777])})
    assert _gates(_from(40001)) == ("", "")
    _point_at(monkeypatch, tmp_path / "b", {100: ("curl", [777])}, unit_pids=[100])
    assert _gates(_from(40001)) == REFUSED


async def test_at_both_gates_a_reused_inode_is_judged_afresh(owner_world, tmp_path, monkeypatch):
    """A yes for inode 777 is not remembered: once tailscaled has let it go and the kernel has
    given the number to another process's connection, the next request on it is refused."""
    _point_at(monkeypatch, tmp_path / "a", {100: ("tailscaled", [777]), 200: ("curl", [888])})
    assert _gates(_from(40001)) == ("", "")
    _point_at(monkeypatch, tmp_path / "b", {100: ("tailscaled", [555]), 200: ("curl", [777])})
    assert _gates(_from(40001)) == REFUSED


async def test_at_both_gates_an_fd_table_that_cannot_be_read_refuses_even_after_a_yes(owner_world, tmp_path, monkeypatch):
    _point_at(monkeypatch, tmp_path, {100: ("tailscaled", [777])})
    assert _gates(_from(40001)) == ("", "")
    real = identity.socket_inodes

    def unreadable(pid, *, proc=None):
        raise PermissionError("not root")

    monkeypatch.setattr(identity, "socket_inodes", unreadable)
    assert _gates(_from(40001)) == REFUSED
    monkeypatch.setattr(identity, "socket_inodes", real)
    assert _gates(_from(40001)) == ("", "")


# ------------------------------------------------ round 6, F-05B-AVAIL: a deploy that forgot the unit


def test_the_server_says_when_it_was_started_without_no_proxy_headers(monkeypatch):
    """Without --no-proxy-headers uvicorn puts the forwarded address in place of the connection's
    own, and every request from the owner's devices is refused. /health says so from the
    command line the process was started with, and from any request that arrived rewritten."""
    monkeypatch.setattr(identity, "rewritten_seen", 0)
    ok, why = identity.served_without_proxy_headers(
        ["/opt/crooks/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"])
    assert not ok and "without --no-proxy-headers" in why
    ok, why = identity.served_without_proxy_headers(
        ["/opt/crooks/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--port", "8000", "--no-proxy-headers"])
    assert ok and why == "uvicorn started with --no-proxy-headers"
    assert identity.served_without_proxy_headers(["/usr/bin/uvicorn", "app.main:app", "--no-proxy-headers"])[0]
    assert not identity.served_without_proxy_headers(["/usr/local/bin/uvicorn", "app.main:app"])[0]
    assert identity.served_without_proxy_headers(["python", "-m", "pytest"]) == (
        True, "not started by uvicorn from the command line: nothing to check")
    # Started right, but a request still arrived rewritten: something in front is not what it seems.
    if LINUX:
        assert not identity._proc_peer_check(("100.64.0.9", 0), SERVER)[0]
        ok, why = identity.served_without_proxy_headers(["python", "-m", "uvicorn", "app.main:app", "--no-proxy-headers"])
        assert not ok and "1 forwarded request(s) arrived with their address already replaced" in why


async def test_health_carries_the_identity_check_and_turns_red_without_the_flag(client, monkeypatch):  # noqa: F811
    health = (await client.get("/health?fresh=1")).json()
    assert health["checks"]["proxy_identity"]["ok"] is True
    monkeypatch.setattr(identity, "served_without_proxy_headers",
                        lambda cmdline=None: (False, "uvicorn was started without --no-proxy-headers: every forwarded request is refused"))
    health = (await client.get("/health")).json()          # the cached answer is re-judged too
    assert health["checks"]["proxy_identity"]["ok"] is False and health["status"] == "degraded"
    assert "housekeeping" in health["checks"]


async def test_whoami_says_whether_the_request_is_the_owners(client, caplog):  # noqa: F811
    """What George opens on his phone after the deploy: the whole path, end to end, in one
    answer — through tailscale, his login, and the owner by the one rule — and one line in the
    service's own log, without the login, that the deploy reads (round 7)."""
    import logging

    caplog.set_level(logging.INFO, logger="crooks.identity")
    configure(client, logins=OWNER, local=False)
    _settings(client, local_owner=False)
    mine = (await client.get("/whoami", headers=PROXIED)).json()
    assert "whoami: through=tailscale owner=true refusal=none" in caplog.text and OWNER not in caplog.text
    assert mine["through"] == "tailscale" and mine["login"] == OWNER and mine["owner"] is True and mine["owner_refusal"] is None
    here = (await client.get("/whoami")).json()
    assert here["owner"] is False and here["owner_refusal"] == "not_authorised_local"
    assert "allowed" not in str(here).lower() or OWNER not in str(here), "never what the allow-list holds"


# ------------------------------------------------ round 7, F-05B: pinned, attested, and a cgroup only root can join


async def test_at_both_gates_a_process_that_exits_during_the_check_is_not_believed(owner_world, tmp_path, monkeypatch):
    """The race round 7 named: tailscaled's identity is read, it exits, its pid goes to another
    process holding the very socket, and the fds are read from that one. The process was pinned
    with a pidfd before anything was read, and it is not alive afterwards, so none of it counts."""
    proc = _point_at(monkeypatch, tmp_path / "a", {100: ("tailscaled", [555])})
    assert _gates(_from(40001)) == REFUSED, "tailscaled does not hold 777 here"
    impostor = _world(tmp_path / "b", {100: ("curl", [777])}, unit_pids=[100])
    real_inodes = identity.socket_inodes
    pins: list[_Alive] = []

    def pinned(pid):
        pins.append(_Alive(pid, dies=True))        # it exits while being looked at
        return pins[-1]

    def swapped(pid, *, proc=None):
        # Between reading who it is and reading its files, the pid became another process.
        monkeypatch.setattr(identity, "PROC", impostor)
        return real_inodes(pid)

    _point_at(monkeypatch, tmp_path / "c", {100: ("tailscaled", [555])})
    identity.bind_pinner(pinned)
    monkeypatch.setattr(identity, "socket_inodes", swapped)
    assert identity.socket_inode(("127.0.0.1", 40001), SERVER, proc=impostor) == 777
    assert _gates(_from(40001)) == REFUSED
    assert pins and all(p.closed for p in pins), "every pin is let go"
    # The same swap with the pinned process still alive cannot happen (a live process keeps its
    # pid); the control is the honest case: alive, and its own socket.
    monkeypatch.setattr(identity, "socket_inodes", real_inodes)
    _point_at(monkeypatch, tmp_path / "d", {100: ("tailscaled", [777])})
    assert _gates(_from(40001)) == ("", "")
    assert proc.exists()


async def test_at_both_gates_the_binary_must_be_the_distributions_tailscaled(owner_world, tmp_path, monkeypatch):
    """Not a file that is called tailscaled: the path the package installs, and a file only root
    can write. A copy run from elsewhere, inside the service's own cgroup, is still refused."""
    proc = _point_at(monkeypatch, tmp_path, {100: ("tailscaled", [777])})
    os.unlink(proc / "100" / "exe")
    os.symlink("/tmp/tailscaled", proc / "100" / "exe")
    assert not identity.is_proxy_process(100) and _gates(_from(40001)) == REFUSED
    os.unlink(proc / "100" / "exe")
    os.symlink("/usr/sbin/tailscaled", proc / "100" / "exe")
    assert _gates(_from(40001)) == ("", "")
    identity.bind_root_only(lambda path: str(path) != "/usr/sbin/tailscaled")   # the binary is writable by others
    assert _gates(_from(40001)) == REFUSED
    os.unlink(proc / "100" / "exe")
    os.symlink("/usr/sbin/tailscaled (deleted)", proc / "100" / "exe")        # replaced by an upgrade, not yet restarted
    assert identity.is_proxy_process(100), "judged by the path it was exec'd from, which only root could write"


async def test_at_both_gates_a_cgroup_anyone_could_join_is_trusted_by_no_one(owner_world, tmp_path, monkeypatch):
    _point_at(monkeypatch, tmp_path, {100: ("tailscaled", [777])})
    assert _gates(_from(40001)) == ("", "")
    identity.bind_root_only(lambda path: path.name != "cgroup.procs")
    ok, why = identity._proc_peer_check(("127.0.0.1", 40001), SERVER)
    assert not ok and "could be joined by a process that is not root" in why
    assert _gates(_from(40001)) == REFUSED


@pytest.mark.skipif(not LINUX or not hasattr(os, "pidfd_open"), reason="pidfd is Linux 5.3+")
def test_on_this_kernel_a_pin_knows_when_its_process_has_gone():
    import subprocess

    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    pinned = identity.pin(child.pid)
    try:
        assert pinned.alive()
        child.kill()
        child.wait(timeout=10)
        assert not pinned.alive(), "exited: nothing read under its pid after this is believed"
    finally:
        pinned.close()
    with pytest.raises(ProcessLookupError):
        identity.pin(child.pid)


def test_on_this_kernel_root_ownership_is_read_from_stat(tmp_path):
    held = tmp_path / "file"
    held.write_text("x")
    os.chmod(held, 0o644)
    assert identity.root_only(held) is (os.geteuid() == 0)
    os.chmod(held, 0o666)
    assert identity.root_only(held) is False, "writable by others is never root's alone"
    assert identity.root_only(tmp_path / "missing") is False
