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


def _addresses(root: Path, v4: list[str], v6: list[str] | None, *, ipv6_off: str | None = None) -> Path:
    """A /proc/net/fib_trie and if_inet6 holding these as the host's own (None: no if_inet6), and
    the kernel's IPv6 switch reading `ipv6_off` (None: no switch at all)."""
    (root / "net").mkdir(parents=True, exist_ok=True)
    switch = root / "sys" / "net" / "ipv6" / "conf" / "all" / "disable_ipv6"
    if ipv6_off is None:
        switch.unlink(missing_ok=True)
    else:
        switch.parent.mkdir(parents=True, exist_ok=True)
        switch.write_text(ipv6_off)
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
    interface = tailscale_interface(monkeypatch, "100.101.102.103")
    monkeypatch.setattr(socket.socket, "bind", lambda self, address: None)   # as if nonlocal bind were on
    assert identity.is_this_host("100.101.102.103") is True
    assert identity.is_this_host("fd7a:115c:a1e0::abcd") is True
    assert identity.is_this_host("100.64.0.9, 10.0.0.1") is False, "a route through the host is not an address it holds"
    assert identity.is_this_host("not an address") is False
    # The server's tailnet address changes: the very next request knows it.
    _addresses(root, ["100.101.102.200"], ["fd7a:115c:a1e0::abcd"])
    interface["v4"] = "100.101.102.200"
    assert identity.is_this_host("100.101.102.200") is True and identity.is_this_host("100.101.102.103") is False
    # IPv6 switched off on the host: no IPv6 address is its own, and IPv4 still answers. Off is
    # the kernel's switch saying so (round 8, F-05B-AVAIL), not the table being absent.
    _addresses(root, ["100.101.102.200"], None, ipv6_off="1\n")
    assert identity.is_this_host("fd7a:115c:a1e0::abcd") is False and identity.is_this_host("100.101.102.200") is True
    # The IPv4 table unreadable: it cannot say.
    (root / "net" / "fib_trie").unlink()
    assert identity.is_this_host("100.101.102.200") is None
    assert not hasattr(identity, "own_addresses") and not hasattr(identity, "SELF_CACHE_S"), "nothing is remembered"


@pytest.mark.skipif(not LINUX, reason="the kernel's own address tables are Linux /proc files")
def test_on_this_machine_the_kernels_tables_name_its_loopback():
    """The strict readers take this kernel's own tables as they are: the IPv4 table names the
    loopback address, the socket table parses whole, and so does the IPv6 table where there is
    one. Where this kernel says nothing of IPv6 at all — no if_inet6 and no switch reading 1, as on
    a kernel built without it — the answer is "cannot say", never "no IPv6" (round 8,
    F-05B-AVAIL)."""
    trie = Path("/proc/net/fib_trie").read_text(encoding="ascii")
    assert "127.0.0.1" in identity._ipv4_local(trie)
    assert identity._tcp_rows("net/tcp", Path("/proc/net/tcp").read_text(encoding="ascii"))
    inet6, switch = Path("/proc/net/if_inet6"), Path("/proc/sys/net/ipv6/conf/all/disable_ipv6")
    mine, why = identity.this_hosts_addresses()
    if inet6.exists():
        identity._ipv6_local(inet6.read_text(encoding="ascii"))
        assert mine is not None and "127.0.0.1" in mine
    elif switch.exists() and switch.read_text() == "1\n":
        assert mine is not None and "127.0.0.1" in mine
    else:
        assert mine is None and "if_inet6 is missing" in why


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
    # [messaging] The one public door for messages coming in (app/routes/hooks.py): it skips the owner
    # rule, so it is held to its own, stricter one here: anything unsigned, from anyone, is an empty
    # 403. tests/test_hooks_door.py proves what it does with a signed request and its near misses.
    from app.routes.hooks import HOOK_PATHS

    hooks_seen = set()
    for template, method in served:
        path = _re.sub(r"\{[^}]+\}", "scr_000000000000", template)
        if path in HOOK_PATHS:
            for headers in ({}, stranger, PROXIED):
                response = await client.request(method, path, headers=headers)
                assert response.status_code == 403 and response.content == b"", (method, path, headers)
            hooks_seen.add(path)
            continue
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
    # [channels] One door per channel since 8 Oct: WeCom, WhatsApp, Instagram.
    # [returns-events] And CROOKS Returns' doorbell, 8 Oct (DEC-077).
    assert hooks_seen == HOOK_PATHS == frozenset({"/hooks/wecom", "/hooks/whatsapp", "/hooks/instagram", "/hooks/returns"})
    # The pad's two routes left this list with the CROOKS Pad (DEC-071, ruling 40).
    for must in ("/turn", "/command", "/telemetry", "/objectives", "/displays", "/tools",
                 "/speak", "/support/investigate", "/openapi.json", "/media/shopify/scr_000000000000/scr_000000000000"):
        assert must in checked, must
    # And the owner's own device is let through the door (whatever the route then says).
    for path in ("/turn", "/tools", "/telemetry"):
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
    import re

    caplog.set_level(logging.INFO, logger="crooks.identity")
    configure(client, logins=OWNER, local=False)
    _settings(client, local_owner=False)
    mine = (await client.get("/whoami", headers=PROXIED)).json()
    # Round 8, F-05B-AVAIL-PREFLIGHT: the line carries the token the answer carries.
    assert re.fullmatch(r"[0-9a-f]{8}", mine["check"])
    assert f"whoami: id={mine['check']} through=tailscale owner=true refusal=none" in caplog.text and OWNER not in caplog.text
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


# ------------------------------------------------ round 8, F-05B: a listing or a row wrong in part


def _why(port: int = 40001) -> str:
    return identity._proc_peer_check(("127.0.0.1", port), SERVER)[1]


@pytest.mark.parametrize("listing", ["100\nabc\n", "100 300\n", "100\n\n", "100", "100\n-5\n", "0100\n",
                                     "100\n\x00\n", "100\n0\n", " 100\n", "100\t\n", "\n"])
async def test_at_both_gates_a_malformed_cgroup_listing_is_trusted_for_nothing(owner_world, tmp_path, monkeypatch, listing):
    """cgroup.procs is one pid per line. A listing with anything else in it is not read as the
    pids that happened to parse: nothing in it is believed, and both gates refuse."""
    _point_at(monkeypatch, tmp_path, {100: ("tailscaled", [777]), 300: ("helper", [666])})
    assert _gates(_from(40001)) == ("", ""), "the well-formed listing: the owner"
    procs = tmp_path / "cgroup" / "system.slice" / "tailscaled.service" / "cgroup.procs"
    procs.write_text(listing)
    assert identity.unit_pids(cgroup=tmp_path / "cgroup") is None
    assert "list of processes could not be read whole" in _why()
    assert _gates(_from(40001)) == REFUSED


def _rows(proc: Path, table: str = "tcp") -> list[str]:
    return (proc / "net" / table).read_text().splitlines()


def _write_rows(proc: Path, lines: list[str], table: str = "tcp") -> None:
    (proc / "net" / table).write_text("\n".join(lines) + "\n")


async def test_at_both_gates_a_malformed_socket_row_is_no_match_and_a_malformed_table_is_believed_in_no_part(owner_world, tmp_path, monkeypatch):
    """/proc/net/tcp is read row by row whole — field count, the hex address:port pairs, the
    state, the numbers — and a table with one row the kernel would not write is not believed at
    all, even where its other rows would have said yes."""
    proc = _point_at(monkeypatch, tmp_path, {100: ("tailscaled", [777])})
    assert _gates(_from(40001)) == ("", "")
    good = _rows(proc)
    mine = next(i for i, line in enumerate(good) if line.split()[1:2] == [_hex4("127.0.0.1", 40001)])
    fields = good[mine].split()
    assert fields[9] == "777" and fields[1] != fields[1].lower(), "tailscaled's own end of the connection"

    def with_row(i: int, replaced: list[str]) -> list[str]:
        return [*good[:i], "   " + " ".join(replaced), *good[i + 1:]]

    malformed = {
        "a state that is not hex": with_row(mine, [*fields[:3], "ZZ", *fields[4:]]),
        "a field missing": with_row(mine, fields[:-1]),
        "a field too many": with_row(mine, [*fields, "0"]),
        "an address in lower case": with_row(mine, [fields[0], fields[1].lower(), *fields[2:]]),
        "an address without its port": with_row(mine, [fields[0], fields[1].split(":")[0], *fields[2:]]),
        "an inode that is not a number": with_row(mine, [*fields[:9], "777x", *fields[10:]]),
        "a negative inode": with_row(mine, [*fields[:9], "-777", *fields[10:]]),
        "another row that is not the kernel's": [*good, "   9: garbage"],
        "no header": good[1:],
    }
    for what, lines in malformed.items():
        _write_rows(proc, lines)
        with pytest.raises(identity.MalformedTable):
            identity.socket_inode(("127.0.0.1", 40001), SERVER, proc=proc)
        assert "socket table could not be read whole" in _why(), what
        assert _gates(_from(40001)) == REFUSED, what
    # Well-formed rows that are still no match: not established, or two sockets for one connection.
    _write_rows(proc, with_row(mine, [*fields[:3], "06", *fields[4:]]))
    assert identity.socket_inode(("127.0.0.1", 40001), SERVER, proc=proc) is None
    assert _gates(_from(40001)) == REFUSED
    _write_rows(proc, [*good, "   " + " ".join([fields[0], fields[1], fields[2], fields[3], *fields[4:9], "778", *fields[10:]])])
    assert identity.socket_inode(("127.0.0.1", 40001), SERVER, proc=proc) is None, "two sockets, no answer"
    assert _gates(_from(40001)) == REFUSED
    _write_rows(proc, good)
    assert _gates(_from(40001)) == ("", ""), "and the kernel's own table is believed again"


# ------------------------------------------------ round 8, F-05B-AVAIL: this host's own addresses, whole or not at all


V6_OWNER = {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "fd7a:115c:a1e0::9"}
HOST_TAILNET, HOST_TAILNET6 = ["100.101.102.103"], ["fd7a:115c:a1e0::abcd"]
FORGED_REFUSED = ("identity_unverified", "identity_unverified")
LOCAL_REFUSED = ("not_authorised_local", "not_authorised_local")


@pytest.fixture()
def kernel_world(owner_world, tmp_path, monkeypatch):
    """Production's switches, tailscaled really holding the connection (the fake /proc's own
    account of it), and this host's addresses read from the fake /proc's own tables — not stood
    in for — so each gate's answer below is the kernel tables' answer."""
    proc = _point_at(monkeypatch, tmp_path, {100: ("tailscaled", [777])})
    identity.bind_self_check(None)
    # A real server on the tailnet holds its own tailnet addresses, and since round 9
    # (F-05B-AVAIL) a reading of its tables without them is not taken as whole. Which address is
    # its own is the Tailscale interface's answer (round 10, S1T-01): the one thing here that is
    # not a /proc file, an ioctl, is stood in for.
    _addresses(proc, HOST_TAILNET, HOST_TAILNET6)
    tailscale_interface(monkeypatch, HOST_TAILNET[0])
    return proc


def _v6() -> Request:
    return _request(V6_OWNER, peer=("127.0.0.1", 40001))


def tailscale_interface(monkeypatch, address) -> dict:
    """What the kernel says TAILSCALE_INTERFACE holds (identity.interface_ipv4, an ioctl a test
    cannot make): `address`, or no IPv4 address at all when it is None. The answer is kept in
    the dict returned, so a test can change it as the host's address changes.

    Round 13 (R9-A1a-F-05B-AVAIL): the door also asks netlink for every address the interface
    holds (identity.interface_addresses, which a test cannot make of a tailscale0 either). It is
    stood in for with the same answer: the IPv4 address above, and the host's own tailnet IPv6
    address (`held["v6"]`), so the interface holds one of each, as the server's does."""
    held = {"v4": address, "v6": list(HOST_TAILNET6)}

    def asked(name=identity.TAILSCALE_INTERFACE):
        assert name == identity.TAILSCALE_INTERFACE
        if held["v4"] is None:
            raise OSError(99, "Cannot assign requested address")
        return held["v4"]

    def listed(name=identity.TAILSCALE_INTERFACE):
        assert name == identity.TAILSCALE_INTERFACE
        return frozenset([*([held["v4"]] if held["v4"] else []), *held["v6"]])

    monkeypatch.setattr(identity, "interface_ipv4", asked)
    monkeypatch.setattr(identity, "interface_addresses", listed)
    return held


async def test_at_both_gates_an_address_this_host_gains_is_its_own_on_the_next_request(kernel_world):
    assert _gates(_from(40001)) == ("", "") and _gates(_v6()) == ("", ""), "a device's addresses: the owner"
    _addresses(kernel_world, ["100.64.0.9"], [])
    assert _gates(_from(40001)) == LOCAL_REFUSED, "the IPv4 address is the server's own now"
    _addresses(kernel_world, ["100.64.0.9"], ["fd7a:115c:a1e0::9"])
    assert _gates(_v6()) == LOCAL_REFUSED, "and so is the IPv6 one"
    assert actions_route.proxy_state(_v6())[0] == actions_route.THIS_HOST


@pytest.mark.parametrize("switch", [None, "0\n", "", " 1\n", "01\n", "1 1\n", "true\n", "1\n\n"])
async def test_at_both_gates_a_missing_ipv6_table_with_ipv6_not_switched_off_refuses(kernel_world, switch):
    """No if_inet6 is not proof of no IPv6: with the switch absent, on, or anything but the
    kernel's own "1", this host's IPv6 addresses cannot be known, and a request it might have
    sent itself is not taken for the owner's — at either gate, on either family."""
    _addresses(kernel_world, ["100.101.102.103"], None, ipv6_off=switch)
    assert _gates(_from(40001)) == FORGED_REFUSED and _gates(_v6()) == FORGED_REFUSED
    request = _from(40001)
    route, why = actions_route.proxy_state(request)
    assert route == actions_route.FORGED and "if_inet6 is missing and IPv6 is not switched off" in why
    assert "if_inet6 is missing" in actions_route.principal_verdict(_from(40001))[2]


async def test_at_both_gates_a_missing_ipv6_table_with_ipv6_switched_off_is_no_ipv6(kernel_world):
    _addresses(kernel_world, ["100.101.102.103"], None, ipv6_off="1\n")
    assert _gates(_from(40001)) == ("", "") and _gates(_v6()) == ("", "")
    _addresses(kernel_world, ["100.64.0.9"], None, ipv6_off="1\n")
    assert _gates(_from(40001)) == LOCAL_REFUSED, "IPv4 is still read, and read whole"


_TRIE_BAD = {
    "a line the kernel does not write": "this is not a trie line",
    "an entry with no leaf above it": "Local:\n        /32 host LOCAL",
    "an address that is not one": "     |-- 999.64.0.9\n        /32 host LOCAL",
    "a leaf with a zero-padded address": "     |-- 100.064.0.9\n        /32 host LOCAL",
    "an entry of an unknown shape": "     |-- 100.64.0.9\n        /32 host local",
}
_INET6_BAD = {
    "a short address": "fd7a115ca1e0000000000000352b52 03 80 00 80 tailscale0",
    "an upper-case address": "FD7A115CA1E0000000000000352B5219 03 80 00 80 tailscale0",
    "a field missing": "fd7a115ca1e0000000000000352b5219 03 80 00 tailscale0",
    "a field too many": "fd7a115ca1e0000000000000352b5219 03 80 00 80 tailscale0 extra",
    "no interface": "fd7a115ca1e0000000000000352b5219 03 80 00 80",
}


@pytest.mark.parametrize("what", sorted(_TRIE_BAD) + ["no loopback address"])
async def test_at_both_gates_a_malformed_ipv4_table_is_believed_in_no_part(kernel_world, what):
    trie = kernel_world / "net" / "fib_trie"
    if what == "no loopback address":
        trie.write_text("Local:\n  +-- 0.0.0.0/0 3 0 5\n     |-- 100.101.102.103\n        /32 host LOCAL\n")
    else:
        trie.write_text(trie.read_text() + _TRIE_BAD[what] + "\n")
    assert identity.local_addresses(proc=kernel_world) is None
    assert _gates(_from(40001)) == FORGED_REFUSED and _gates(_v6()) == FORGED_REFUSED, what
    assert "fib_trie" in actions_route.proxy_state(_from(40001))[1]


@pytest.mark.parametrize("what", sorted(_INET6_BAD))
async def test_at_both_gates_a_malformed_ipv6_table_is_believed_in_no_part(kernel_world, what):
    inet6 = kernel_world / "net" / "if_inet6"
    inet6.write_text(inet6.read_text() + _INET6_BAD[what] + "\n")
    assert identity.local_addresses(proc=kernel_world) is None
    assert _gates(_from(40001)) == FORGED_REFUSED and _gates(_v6()) == FORGED_REFUSED, what
    assert "if_inet6" in actions_route.proxy_state(_from(40001))[1]


@pytest.mark.parametrize("table", ["fib_trie", "if_inet6"])
async def test_at_both_gates_a_read_that_fails_once_is_tried_again_before_anyone_is_refused(kernel_world, monkeypatch, table):
    """Availability: a table read that fails for an instant is read once more at once, and the
    owner's device is answered on what the second read says — which is still the whole truth, so
    an address of this host's own is still refused as the server. Failing on every reading but
    one refuses, and says how often it tried (round 9: up to four readings, two running of which
    must agree, with a short wait after each that went wrong — tests/test_host_addresses.py)."""
    _addresses(kernel_world, ["100.101.102.103"], ["fd7a:115c:a1e0::abcd"])
    real = identity._read_table
    failures = {"left": 0}

    def flaky(path):
        if path.name == table and failures["left"] > 0:
            failures["left"] -= 1
            raise OSError("Resource temporarily unavailable")
        return real(path)

    monkeypatch.setattr(identity, "_read_table", flaky)
    for request in (_from(40001), _v6()):
        # One decision per request, read by both gates (proxy_state): its first read fails.
        failures["left"] = 1
        assert _gates(request) == ("", ""), table
        assert failures["left"] == 0, "the first read failed and the second was believed"
    failures["left"] = 1
    self_request = _request({"Tailscale-User-Login": OWNER, "X-Forwarded-For": "100.101.102.103"}, peer=("127.0.0.1", 40001))
    assert _gates(self_request) == LOCAL_REFUSED, "a retried read is not a weaker one"
    failures["left"] = 3
    assert _gates(_from(40001)) == FORGED_REFUSED
    failures["left"] = 3
    route, why = actions_route.proxy_state(_from(40001))
    assert route == actions_route.FORGED and "could not be read (read 4 times" in why and table in why


# ------------------------------------------------ round 8, F-05B-AVAIL-PREFLIGHT: the phone's answer and the install's


async def test_every_whoami_carries_its_own_token_and_the_line_that_says_so(client, caplog):  # noqa: F811
    """A phone's /whoami answer and the one journal line it produced can be matched, and told
    apart from any other request's: each request makes its own token, and the line carries it
    beside the route, the verdict and the refusal."""
    import logging
    import re

    caplog.set_level(logging.INFO, logger="crooks.identity")
    configure(client, logins=OWNER, local=False)
    _settings(client, local_owner=False)
    phone = (await client.get("/whoami", headers=PROXIED)).json()
    here = (await client.get("/whoami")).json()
    assert phone["check"] != here["check"]
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("whoami:")]
    assert [line for line in lines if f"id={phone['check']} " in line] == [
        f"whoami: id={phone['check']} through=tailscale owner=true refusal=none"]
    assert [line for line in lines if f"id={here['check']} " in line] == [
        f"whoami: id={here['check']} through=direct owner=false refusal=not_authorised_local"]
    assert all(re.fullmatch(r"whoami: id=[0-9a-f]{8} through=\w+ owner=(true|false) refusal=\w+", line) for line in lines)


def _installer():
    import importlib.util

    scripts = Path(__file__).resolve().parents[1] / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    spec = importlib.util.spec_from_file_location("install_systemd_under_test", scripts / "install_systemd.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("argv,main_pid,proxy_ok,expect", [
    (["/opt/crooks/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--no-proxy-headers"], "2135565", True, 0),
    (["/opt/crooks/.venv/bin/python", "-m", "uvicorn", "app.main:app"], "2135565", True, 1),
    (["/opt/crooks/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--no-proxy-headers", "--proxy-headers"], "2135565", True, 1),
    (["/opt/crooks/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--no-proxy-headers=1"], "2135565", True, 1),
    (["/opt/crooks/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--no-proxy-headers"], "0", True, 1),
    (["/opt/crooks/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--no-proxy-headers"], "", True, 1),
    (["/opt/crooks/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--no-proxy-headers"], "2135565", False, 1),
    (["/opt/crooks/.venv/bin/python", "-m", "uvicorn", "app.main:app", "--no-proxy-headers"], "2135565", None, 1),
])
def test_the_install_is_done_only_when_the_running_service_has_the_flag_and_health_agrees(tmp_path, monkeypatch, capsys,
                                                                                         argv, main_pid, proxy_ok, expect):
    """`make install` on the server restarts the service and then asserts, of the process now
    running, that its own command line (/proc/<MainPID>/cmdline) says --no-proxy-headers and that
    /health's proxy_identity check is ok — exiting non-zero, saying which, when either is not so.
    The unit file saying so is not the running process doing so."""
    import subprocess

    installer = _installer()
    proc = tmp_path / "proc"
    (proc / "2135565").mkdir(parents=True)
    (proc / "2135565" / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    ran: list[tuple[str, ...]] = []

    def systemctl(*args):
        ran.append(args)
        out = main_pid if args[:1] == ("show",) else ""
        return subprocess.CompletedProcess(["systemctl", *args], 0, stdout=out + "\n", stderr="")

    checks = {} if proxy_ok is None else {"proxy_identity": {"ok": proxy_ok, "detail": "uvicorn started with --no-proxy-headers"}}
    monkeypatch.setattr(installer, "PROC", proc)
    monkeypatch.setattr(installer, "systemctl", systemctl)
    monkeypatch.setattr(installer, "preflight", lambda: [])
    monkeypatch.setattr(installer, "rendered_unit", lambda values=None: "[Unit]\n")
    monkeypatch.setattr(installer.lc, "SYSTEMD_UNIT_PATH", tmp_path / "crooks-assistant.service")
    monkeypatch.setattr(installer.lc, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(installer.lc, "ensure_serve", lambda port: ("crooks.example.com", "serving"))
    monkeypatch.setattr(installer.lc, "wait_for_health", lambda url, timeout_s=90: {"status": "ok", "checks": checks})
    # This host's own tailnet addresses (round 10, S1T-01) are the next gate's, in
    # tests/test_r11_install_gate.py; here they are in order.
    monkeypatch.setattr(identity, "tailnet_self_check", lambda: (True, "whole"))
    assert installer.install(8000) == expect
    out = capsys.readouterr().out
    assert ("show", "-p", "MainPID", "--value", "crooks-assistant.service") in ran
    assert ran.index(("restart", "crooks-assistant.service")) < ran.index(("show", "-p", "MainPID", "--value", "crooks-assistant.service"))
    if expect:
        assert "FAIL" in out and "the install is not done" in out
    else:
        assert "running with --no-proxy-headers" in out and "Done." in out


def test_the_last_of_the_two_proxy_header_flags_is_the_one_believed(monkeypatch):
    """uvicorn obeys the last of --proxy-headers and --no-proxy-headers, so /health's check and the
    install's both read the command line that way, word by word."""
    monkeypatch.setattr(identity, "rewritten_seen", 0)
    uvicorn = ["/opt/crooks/.venv/bin/python", "-m", "uvicorn", "app.main:app"]
    assert identity.served_without_proxy_headers([*uvicorn, "--no-proxy-headers"])[0] is True
    assert identity.served_without_proxy_headers([*uvicorn, "--no-proxy-headers", "--proxy-headers"])[0] is False
    assert identity.served_without_proxy_headers([*uvicorn, "--proxy-headers", "--no-proxy-headers"])[0] is True
    assert identity.served_without_proxy_headers([*uvicorn, "--no-proxy-headers=true"])[0] is False
    assert not identity.proxy_headers_off([]) and not identity.proxy_headers_off(["--no-proxy-headers-x"])
