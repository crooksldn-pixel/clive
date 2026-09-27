"""Who is on the other end of a proxied request, confirmed with Tailscale itself.

`tailscale serve` stamps Tailscale-User-Login and X-Forwarded-For on what it proxies. A
header is a claim, though, and the app listens on loopback, where any process on the Mac
can write one. Before a change is applied, the forwarded address is put to `tailscale
whois`, which answers from the tailnet's own state who holds that address; the login on
the header must be that person. Answers are cached briefly. No CLI, no answer, or a
different person: the change is refused — a claim is never trusted for want of a check."""

from __future__ import annotations

import ipaddress
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger("crooks.identity")

TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
CACHE_S = 600.0        # a confirmed pairing is good for this long
NEGATIVE_S = 30.0      # a refusal is remembered this long, so a busy tablet is not a whois storm
TIMEOUT_S = 2.5
MAC_APP_CLI = "/Applications/Tailscale.app/Contents/MacOS/Tailscale"

_cache: dict[tuple[str, str], tuple[bool, str, float]] = {}
_lock = threading.Lock()
_runner = None   # tests hand in a fake `tailscale whois`


def bind_runner(runner) -> None:
    global _runner
    _runner = runner
    with _lock:
        _cache.clear()


def cli_path(configured: str = "") -> str | None:
    """The Tailscale CLI: configured, on PATH, or inside the Mac app bundle."""
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("tailscale")
    if found:
        return found
    return MAC_APP_CLI if Path(MAC_APP_CLI).exists() else None


def forwarded_address(header: str) -> str:
    """The client address `tailscale serve` put first in X-Forwarded-For."""
    return str(header or "").split(",")[0].strip().strip("[]")


def on_tailnet(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip in TAILNET_V4 or ip in TAILNET_V6


def _run_whois(cli: str, address: str) -> str:
    completed = subprocess.run([cli, "whois", "--json", address], capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "").strip()[:160] or f"exit {completed.returncode}")
    return completed.stdout


def whois_login(address: str, *, cli: str) -> str | None:
    """The login Tailscale says holds this address, lower-cased; None when it cannot say."""
    runner = _runner or _run_whois
    try:
        out = runner(cli, address)
        data = json.loads(out) if isinstance(out, str) else out
    except Exception as exc:  # noqa: BLE001 — every failure is "cannot say"
        log.warning("tailscale whois %s failed: %s", address, str(exc)[:160])
        return None
    profile = (data or {}).get("UserProfile") or {}
    login = str(profile.get("LoginName") or "").strip().lower()
    return login or None


def verify(address: str, login: str, *, cli: str | None, now: float | None = None) -> tuple[bool, str]:
    """Whether Tailscale confirms that `login` holds `address`. (ok, why)."""
    login = str(login or "").strip().lower()
    address = forwarded_address(address)
    if not login or not address:
        return False, "no login or address to check"
    if not on_tailnet(address):
        return False, f"{address} is not a tailnet address"
    if not cli:
        return False, "the tailscale CLI was not found (set CROOKS_TAILSCALE_CLI)"
    now = time.time() if now is None else now
    key = (address, login)
    with _lock:
        cached = _cache.get(key)
        if cached is not None and now - cached[2] < (CACHE_S if cached[0] else NEGATIVE_S):
            return cached[0], cached[1]
    holder = whois_login(address, cli=cli)
    if holder is None:
        ok, why = False, "tailscale did not say who holds that address"
    elif holder != login:
        ok, why = False, "the address belongs to a different login"
    else:
        ok, why = True, "confirmed by tailscale whois"
    with _lock:
        _cache[key] = (ok, why, now)
    return ok, why


# ------------------------------------------------------------------ did it come through tailscaled
#
# A header is a claim: X-Forwarded-For and Tailscale-User-Login can be written by any process on
# this server that can reach the port, and `tailscale whois` says who holds the forwarded ADDRESS,
# not that the request came from that device (the 2026-09-27 deploy reviews, F-05B). What a header
# cannot write is who opened the TCP connection the request arrived on, and on Linux the kernel
# says: /proc/net/tcp names the socket at the other end of this connection by inode, and only the
# process holding that inode has it among its open files.
#
# Which process is tailscaled is also the kernel's answer, never a name a process gives itself
# (round 6: any process can set its own comm with prctl(PR_SET_NAME)). It is a process in the
# tailscaled.service unit's own cgroup, which only root can move a process into, as listed by that
# cgroup's cgroup.procs and confirmed by the process's own /proc/<pid>/cgroup, whose executable
# (/proc/<pid>/exe, which only exec can set) is a file named tailscaled. Its open files are read
# afresh for every check: nothing positive is ever remembered, so a socket inode the kernel later
# gives to something else cannot inherit a yes. Root on this server can defeat any of this, as it
# can read every credential the service holds; this stops everything that is not root.
#
# uvicorn must be started with --no-proxy-headers for this: otherwise it replaces the connection's
# own address with the forwarded one before the app sees it, and there is nothing left to check.
# Every launcher passes it; a server started without it refuses every forwarded request.

PROXY_UNIT = "tailscaled.service"
PROXY_EXE = "tailscaled"
PROC = Path("/proc")
CGROUP = Path("/sys/fs/cgroup")
# Where a system service's cgroup lives: the unified hierarchy (cgroup v2, Ubuntu 24.04), then the
# named systemd hierarchy of a v1 or hybrid host.
_UNIT_CGROUPS = ("system.slice/{unit}", "systemd/system.slice/{unit}", "unified/system.slice/{unit}")
_peer_check = None      # tests hand in a fake
_self_check = None      # tests hand in a fake
_self_cache: dict[str, tuple[frozenset[str] | None, float]] = {}
SELF_CACHE_S = 600.0


def bind_peer_check(check) -> None:
    """Tests: `check(client, server) -> (ok, why)` in place of reading /proc."""
    global _peer_check
    _peer_check = check


def bind_self_check(check) -> None:
    """Tests: `check(address) -> bool | None` in place of asking Tailscale for this node's own
    addresses (None: it could not say)."""
    global _self_check
    _self_check = check
    with _lock:
        _self_cache.clear()


def _ip(value: str):
    try:
        ip = ipaddress.ip_address(str(value or "").strip().strip("[]").split("%", 1)[0])
    except ValueError:
        return None
    mapped = getattr(ip, "ipv4_mapped", None)
    return mapped if mapped is not None else ip


def _proc_forms(ip, port: int) -> dict[str, str]:
    """How /proc/net/tcp and /proc/net/tcp6 write one address:port: each 32-bit word of the
    address in this machine's byte order, as upper-case hex, then the port. An IPv4 address is
    also looked for in its IPv4-mapped IPv6 form, which is how a dual-stack socket lists it."""
    import sys

    def words(packed: bytes) -> str:
        return "".join(f"{int.from_bytes(packed[i:i + 4], sys.byteorder):08X}" for i in range(0, len(packed), 4))

    forms: dict[str, str] = {}
    if ip.version == 4:
        forms["net/tcp"] = f"{words(ip.packed)}:{port:04X}"
        forms["net/tcp6"] = f"{words(ipaddress.IPv6Address('::ffff:' + str(ip)).packed)}:{port:04X}"
    else:
        forms["net/tcp6"] = f"{words(ip.packed)}:{port:04X}"
    return forms


def socket_inode(client: tuple[str, int] | None, server: tuple[str, int] | None, *, proc: Path | None = None) -> int | None:
    """The inode of the socket at the CLIENT end of the connection client -> server: the one
    the process that opened the connection holds. None when the kernel lists no such socket.
    The tables are searched as text for the two addresses in the kernel's own form, so a busy
    server's thousands of rows cost one pass, not one parse each."""
    root = proc or PROC
    if not client or not server:
        return None
    local_ip, remote_ip = _ip(client[0]), _ip(server[0])
    local_port, remote_port = int(client[1] or 0), int(server[1] or 0)
    if local_ip is None or remote_ip is None or not local_port or not remote_port:
        return None
    local, remote = _proc_forms(local_ip, local_port), _proc_forms(remote_ip, remote_port)
    for table in ("net/tcp", "net/tcp6"):
        if table not in local or table not in remote:
            continue
        try:
            text = (root / table).read_text(encoding="ascii", errors="replace")
        except OSError:
            continue
        needle = f" {local[table]} {remote[table]} "
        at = text.find(needle)
        while at != -1:
            line_start = text.rfind("\n", 0, at) + 1
            line_end = text.find("\n", at)
            parts = text[line_start:line_end if line_end != -1 else None].split()
            if len(parts) >= 10 and parts[1] == local[table] and parts[2] == remote[table]:
                try:
                    inode = int(parts[9])
                except ValueError:
                    inode = 0
                if inode:
                    return inode
            at = text.find(needle, at + 1)
    return None


def unit_pids(unit: str = PROXY_UNIT, *, cgroup: Path | None = None) -> list[int]:
    """The processes in a systemd service's own cgroup, as the kernel lists them. Only root can
    move a process into another service's cgroup."""
    root = cgroup or CGROUP
    for pattern in _UNIT_CGROUPS:
        procs = root / pattern.format(unit=unit) / "cgroup.procs"
        try:
            text = procs.read_text(encoding="ascii", errors="replace")
        except OSError:
            continue
        return [int(word) for word in text.split() if word.isdigit()]
    return []


def is_proxy_process(pid: int, *, proc: Path | None = None, unit: str = PROXY_UNIT, exe: str = PROXY_EXE) -> bool:
    """Whether a process is the tailscaled service, by what only the kernel writes: the cgroup
    it is in (/proc/<pid>/cgroup) and the file it was exec'd from (/proc/<pid>/exe; a binary
    replaced by an upgrade reads "<path> (deleted)" until the restart). Never by its name."""
    root = proc or PROC
    try:
        groups = (root / str(pid) / "cgroup").read_text(encoding="utf-8", errors="replace").splitlines()
        target = os.readlink(root / str(pid) / "exe")
    except PermissionError:
        raise
    except OSError:
        return False
    in_unit = any(line.rsplit(":", 1)[-1].rstrip("/").endswith(f"/{unit}") for line in groups)
    path = target[: -len(" (deleted)")] if target.endswith(" (deleted)") else target
    return in_unit and Path(path).name == exe


def socket_inodes(pid: int, *, proc: Path | None = None) -> frozenset[int]:
    """The socket inodes a process holds open, read now. Reading another process's open files
    needs the rights this service runs with (root on the server, today). Without them this raises
    PermissionError, which `peer_is_tailscaled` turns into a refusal that says so: moving the
    service to its own user (docs/DEPLOY_LINUX.md) must bring a way to keep this answer, or
    every forwarded request is refused, never waved through."""
    root = proc or PROC
    held: set[int] = set()
    fds = root / str(pid) / "fd"
    try:
        names = [entry.name for entry in fds.iterdir()]
    except PermissionError:
        raise
    except OSError:
        return frozenset()
    for name in names:
        try:
            target = os.readlink(fds / name)
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            try:
                held.add(int(target[8:-1]))
            except ValueError:
                continue
    return frozenset(held)


# Forwarded requests refused because uvicorn had already put the forwarded address in place of
# the connection's own (a port of 0): the sign of a server started without --no-proxy-headers,
# counted so /health can say so (round 6, F-05B-AVAIL).
rewritten_seen = 0


def served_without_proxy_headers(cmdline: list[str] | None = None) -> tuple[bool, str]:
    """Whether this process was started so that the connection's own address reaches the app:
    uvicorn with --no-proxy-headers. (ok, why). A process that is not uvicorn started from the
    command line (the test suite, another ASGI host) has nothing here to check, and says so."""
    if cmdline is None:
        try:
            raw = (PROC / "self" / "cmdline").read_bytes()
        except OSError:
            return False, "this process's command line could not be read"
        cmdline = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
    started_by_uvicorn = any(Path(part).name in ("uvicorn", "uvicorn.exe") for part in cmdline[:3]) or (
        "-m" in cmdline[:3] and "uvicorn" in cmdline[:4])
    if not started_by_uvicorn:
        return True, "not started by uvicorn from the command line: nothing to check"
    if "--no-proxy-headers" not in cmdline:
        return False, "uvicorn was started without --no-proxy-headers: every forwarded request is refused"
    if rewritten_seen:
        return False, f"{rewritten_seen} forwarded request(s) arrived with their address already replaced"
    return True, "uvicorn started with --no-proxy-headers"


def _proc_peer_check(client, server) -> tuple[bool, str]:
    global rewritten_seen
    if not (PROC / "net" / "tcp").exists():
        return False, "this server cannot say who opened the connection (no /proc)"
    if client and not int(client[1] or 0):
        with _lock:
            rewritten_seen += 1
        return False, ("the connection's own address was replaced by a forwarded one before it reached "
                       "the app: start uvicorn with --no-proxy-headers (make install)")
    inode = socket_inode(client, server)
    if inode is None:
        return False, "the connection was not opened on this server"
    pids = [pid for pid in unit_pids() if is_proxy_process(pid)]
    if not pids:
        return False, f"no tailscaled process is running in {PROXY_UNIT}"
    for pid in pids:
        # Read afresh every time: a remembered yes could outlive the socket it was about.
        if inode in socket_inodes(pid):
            return True, f"opened by tailscaled (pid {pid})"
    return False, "the connection was opened by something other than tailscaled"


def peer_is_tailscaled(client: tuple[str, int] | None, server: tuple[str, int] | None) -> tuple[bool, str]:
    """Whether the process at the other end of this connection is tailscaled. (ok, why)."""
    check = _peer_check or _proc_peer_check
    try:
        return check(client, server)
    except Exception as exc:  # noqa: BLE001 — every failure is "cannot say", and that refuses
        return False, f"who opened the connection could not be read: {type(exc).__name__}"


def _run_ip(cli: str) -> str:
    completed = subprocess.run([cli, "ip"], capture_output=True, text=True, timeout=TIMEOUT_S, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"exit {completed.returncode}")
    return completed.stdout


def own_addresses(*, cli: str | None, now: float | None = None) -> frozenset[str] | None:
    """This node's own tailnet addresses, as Tailscale itself lists them (`tailscale ip`), cached
    briefly; None when it cannot say. Asked of Tailscale rather than inferred from what the kernel
    lets a socket bind to, which a sysctl (net.ipv4.ip_nonlocal_bind) can turn into "every
    address" (round 6, F-05B-AVAIL)."""
    now = time.time() if now is None else now
    with _lock:
        cached = _self_cache.get("")
        if cached is not None and now - cached[1] < (SELF_CACHE_S if cached[0] is not None else NEGATIVE_S):
            return cached[0]
    found: frozenset[str] | None = None
    if cli:
        try:
            listed = _run_ip(cli)
            addresses = frozenset(str(ip) for ip in (_ip(word) for word in listed.split()) if ip is not None)
            found = addresses if addresses and all(on_tailnet(a) for a in addresses) else None
        except Exception as exc:  # noqa: BLE001 — every failure is "cannot say"
            log.warning("tailscale ip failed: %s", type(exc).__name__)
    with _lock:
        _self_cache[""] = (found, now)
    return found


def is_this_host(address: str, *, cli: str | None = None) -> bool | None:
    """Whether a forwarded address is this server's own. The server is on the owner's tailnet
    login, so a request it sends through its own `tailscale serve` arrives stamped with the
    owner's login; it is still a request made on the server, and is judged as one. None when
    this node's addresses cannot be read, which the caller refuses."""
    ip = _ip(forwarded_address(address))
    if ip is None:
        return False
    if _self_check is not None:
        answer = _self_check(str(ip))
        return None if answer is None else bool(answer)
    mine = own_addresses(cli=cli)
    if mine is None:
        return None
    return str(ip) in mine
