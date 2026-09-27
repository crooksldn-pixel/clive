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
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger("crooks.identity")

TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILNET_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
# A confirmed pairing of address and login is good for this long: short, because a yes that
# outlives what it was about is the one kind of mistake these checks exist to prevent (round 7).
CACHE_S = 60.0
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
# tailscaled.service unit's own cgroup, as listed by that cgroup's cgroup.procs and confirmed by
# the process's own /proc/<pid>/cgroup, whose executable (/proc/<pid>/exe, which only exec can
# set) is the distribution's tailscaled binary (PROXY_BINARIES) — the path itself, not a name that
# looks like it — and, unless an upgrade has replaced it since, a file only root can write. The
# unit's cgroup must itself be one only root can move a process into: its directory and its
# cgroup.procs owned by root and writable by nobody else (round 7). Its open files are read
# afresh for every check: nothing positive is ever remembered, so a socket inode the kernel later
# gives to something else cannot inherit a yes. And the process is pinned for the length of the
# check with a pidfd (round 7): if it exits while it is being looked at, and its pid is given to
# another, nothing read under that pid is believed. Root on this server can defeat any of this,
# as it can read every credential the service holds; this stops everything that is not root.
#
# uvicorn must be started with --no-proxy-headers for this: otherwise it replaces the connection's
# own address with the forwarded one before the app sees it, and there is nothing left to check.
# Every launcher passes it; a server started without it refuses every forwarded request.

PROXY_UNIT = "tailscaled.service"
# Where the distribution's package installs the service's binary. A process in the unit's cgroup
# exec'd from anywhere else is not the proxy.
PROXY_BINARIES = ("/usr/sbin/tailscaled",)
PROC = Path("/proc")
CGROUP = Path("/sys/fs/cgroup")
# Where a system service's cgroup lives: the unified hierarchy (cgroup v2, Ubuntu 24.04), then the
# named systemd hierarchy of a v1 or hybrid host.
_UNIT_CGROUPS = ("system.slice/{unit}", "systemd/system.slice/{unit}", "unified/system.slice/{unit}")
_peer_check = None      # tests hand in a fake
_self_check = None      # tests hand in a fake
_pinner = None          # tests hand in a fake pidfd
_root_only = None       # tests hand in a fake ownership check


def bind_peer_check(check) -> None:
    """Tests: `check(client, server) -> (ok, why)` in place of reading /proc."""
    global _peer_check
    _peer_check = check


def bind_self_check(check) -> None:
    """Tests: `check(address) -> bool | None` in place of reading this host's own addresses from
    the kernel (None: it could not say)."""
    global _self_check
    _self_check = check


def bind_pinner(pinner) -> None:
    """Tests: `pinner(pid)` returning an object with alive() and close(), in place of a pidfd."""
    global _pinner
    _pinner = pinner


def bind_root_only(check) -> None:
    """Tests: `check(path) -> bool` in place of stat()ing for root ownership."""
    global _root_only
    _root_only = check


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


class MalformedTable(ValueError):
    """A kernel table that is not in the shape the kernel writes: nothing in it is believed."""


# One row of /proc/net/tcp or /proc/net/tcp6, as the kernel writes it (net/ipv4/tcp_ipv4.c
# get_tcp4_sock, get_openreq4, get_timewait4_sock, and their tcp6 twins): a slot, the two
# address:port pairs in upper-case hex, the state, the queues, the timer, the retransmits, the uid,
# the timeout, the inode, and then either the full socket's seven fields or a request or
# time-wait socket's two (round 8, F-05B). Anything else is not a row the kernel wrote.
_TCP_ADDRESS = {"net/tcp": re.compile(r"[0-9A-F]{8}:[0-9A-F]{4}"), "net/tcp6": re.compile(r"[0-9A-F]{32}:[0-9A-F]{4}")}
_TCP_FIXED = (
    re.compile(r"\d+:"),                          # sl
    None, None,                                   # local and remote address:port, per table
    re.compile(r"[0-9A-F]{2}"),                   # st
    re.compile(r"[0-9A-F]{8}:[0-9A-F]{8}"),       # tx_queue:rx_queue
    re.compile(r"[0-9A-F]{2}:[0-9A-F]{8,16}"),    # tr:tm->when
    re.compile(r"[0-9A-F]{8}"),                   # retrnsmt
    re.compile(r"\d+"),                           # uid
    re.compile(r"-?\d+"),                         # timeout
    re.compile(r"\d+"),                           # inode
)
_TCP_TAIL = {
    2: (re.compile(r"-?\d+"), re.compile(r"[0-9a-fA-F]{8,16}")),
    7: (re.compile(r"-?\d+"), re.compile(r"[0-9a-fA-F]{8,16}"), re.compile(r"\d+"), re.compile(r"\d+"),
        re.compile(r"\d+"), re.compile(r"\d+"), re.compile(r"-?\d+")),
}
_ESTABLISHED = "01"


def _tcp_rows(table: str, text: str) -> list[list[str]]:
    """Every row of one socket table, each checked whole; MalformedTable if any row, or the
    header, is not what the kernel writes. A table that cannot be trusted in part is not trusted
    in any part (round 8, F-05B)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or not lines[0].split() or lines[0].split()[:2] != ["sl", "local_address"]:
        raise MalformedTable(f"/proc/{table} has no header")
    address = _TCP_ADDRESS[table]
    rows: list[list[str]] = []
    for line in lines[1:]:
        parts = line.split()
        tail = _TCP_TAIL.get(len(parts) - len(_TCP_FIXED))
        if tail is None:
            raise MalformedTable(f"/proc/{table} has a row of {len(parts)} fields")
        for index, word in enumerate(parts):
            if index in (1, 2):
                rule = address
            elif index < len(_TCP_FIXED):
                rule = _TCP_FIXED[index]
            else:
                rule = tail[index - len(_TCP_FIXED)]
            if not rule.fullmatch(word):
                raise MalformedTable(f"/proc/{table} has a row that is not the kernel's")
        rows.append(parts)
    return rows


def socket_inode(client: tuple[str, int] | None, server: tuple[str, int] | None, *, proc: Path | None = None) -> int | None:
    """The inode of the socket at the CLIENT end of the connection client -> server: the one
    the process that opened the connection holds. None when the kernel lists no such socket,
    lists it with no inode or not established, or lists two sockets for it. Every row of every
    table read is checked whole (round 8, F-05B): a table with a row the kernel would not have
    written raises MalformedTable, and nothing in it is believed."""
    root = proc or PROC
    if not client or not server:
        return None
    local_ip, remote_ip = _ip(client[0]), _ip(server[0])
    local_port, remote_port = int(client[1] or 0), int(server[1] or 0)
    if local_ip is None or remote_ip is None or not local_port or not remote_port:
        return None
    local, remote = _proc_forms(local_ip, local_port), _proc_forms(remote_ip, remote_port)
    found: set[int] = set()
    for table in ("net/tcp", "net/tcp6"):
        if table not in local or table not in remote:
            continue
        try:
            text = (root / table).read_text(encoding="ascii", errors="replace")
        except OSError:
            continue        # a table that is not there lists nothing: never a yes
        for parts in _tcp_rows(table, text):
            if parts[1] != local[table] or parts[2] != remote[table]:
                continue
            inode = int(parts[9])
            if parts[3] == _ESTABLISHED and inode:
                found.add(inode)
    # One socket for one connection, or no answer: two would mean the tables were read across a
    # change, and which one is the request's is not something to guess.
    return next(iter(found)) if len(found) == 1 else None


def unit_cgroup(unit: str = PROXY_UNIT, *, cgroup: Path | None = None) -> Path | None:
    """The directory of a systemd service's own cgroup, or None when there is none."""
    root = cgroup or CGROUP
    for pattern in _UNIT_CGROUPS:
        folder = root / pattern.format(unit=unit)
        if (folder / "cgroup.procs").exists():
            return folder
    return None


_PID = re.compile(r"[1-9][0-9]*")


def unit_pids(unit: str = PROXY_UNIT, *, cgroup: Path | None = None, folder: Path | None = None) -> list[int] | None:
    """The processes in a systemd service's own cgroup, as the kernel lists them: one pid per
    line. None when the listing cannot be read or any line of it is not a pid (round 8, F-05B):
    a listing that is wrong in part is not trusted in any part, never read as the pids that
    happened to parse."""
    folder = folder if folder is not None else unit_cgroup(unit, cgroup=cgroup)
    if folder is None:
        return []
    try:
        text = (folder / "cgroup.procs").read_text(encoding="ascii", errors="replace")
    except OSError:
        return None
    if text and not text.endswith("\n"):
        return None
    pids: list[int] = []
    for line in text.split("\n")[:-1]:
        if not _PID.fullmatch(line):
            return None
        pid = int(line)
        if pid not in pids:
            pids.append(pid)
    return pids


def root_only(path: Path | str) -> bool:
    """Owned by root and writable by nobody else."""
    if _root_only is not None:
        return bool(_root_only(Path(path)))
    try:
        st = os.stat(path)
    except OSError:
        return False
    return st.st_uid == 0 and not st.st_mode & 0o022


def cgroup_guarded(folder: Path) -> bool:
    """Whether only root can move a process into this cgroup: a process joins one by writing its
    pid to the cgroup's cgroup.procs, so that file and the folder it is in must be root's alone."""
    return root_only(folder) and root_only(folder / "cgroup.procs")


def is_proxy_process(pid: int, *, proc: Path | None = None, unit: str = PROXY_UNIT,
                     binaries: tuple[str, ...] | None = None) -> bool:
    """Whether a process is the tailscaled service, by what only the kernel writes: the cgroup
    it is in (/proc/<pid>/cgroup) and the file it was exec'd from (/proc/<pid>/exe). The file must
    be one of PROXY_BINARIES by its path, and root's alone; a binary an upgrade has since replaced
    reads "<path> (deleted)" and is judged by the path it had, which only root could write to.
    Never by the name a process gives itself."""
    root = proc or PROC
    try:
        groups = (root / str(pid) / "cgroup").read_text(encoding="utf-8", errors="replace").splitlines()
        target = os.readlink(root / str(pid) / "exe")
    except PermissionError:
        raise
    except OSError:
        return False
    in_unit = any(line.rsplit(":", 1)[-1].rstrip("/").endswith(f"/{unit}") for line in groups)
    deleted = target.endswith(" (deleted)")
    path = target[: -len(" (deleted)")] if deleted else target
    if path not in (binaries if binaries is not None else PROXY_BINARIES):
        return False
    return in_unit and (deleted or root_only(path))


class _Pin:
    """A pidfd: the one process that had this pid when it was opened, whatever the pid comes to
    mean later. Readable once that process has exited, which is how alive() knows."""

    def __init__(self, pid: int) -> None:
        self.fd = os.pidfd_open(pid)

    def alive(self) -> bool:
        import select

        poller = select.poll()
        poller.register(self.fd, select.POLLIN)
        return not poller.poll(0)

    def close(self) -> None:
        os.close(self.fd)


def pin(pid: int):
    """Pin a process for the length of a check (raises if it has already gone)."""
    return (_pinner or _Pin)(pid)


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


def proxy_headers_off(argv: list[str]) -> bool:
    """Whether a uvicorn command line leaves the connection's own address alone: it says
    --no-proxy-headers, and says it after any --proxy-headers, since the last of the two is the
    one uvicorn obeys (round 8, F-05B-AVAIL-PREFLIGHT). Whole words only."""
    last = None
    for word in argv:
        if word in ("--no-proxy-headers", "--proxy-headers"):
            last = word
    return last == "--no-proxy-headers"


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
    if not proxy_headers_off(cmdline):
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
    try:
        inode = socket_inode(client, server)
    except MalformedTable:
        return False, "the kernel's socket table could not be read whole"
    if inode is None:
        return False, "the connection was not opened on this server"
    folder = unit_cgroup(PROXY_UNIT)
    if folder is None:
        return False, f"no tailscaled process is running in {PROXY_UNIT}"
    if not cgroup_guarded(folder):
        return False, f"{PROXY_UNIT}'s cgroup could be joined by a process that is not root"
    pids = unit_pids(folder=folder)
    if pids is None:
        return False, f"{PROXY_UNIT}'s list of processes could not be read whole"
    found = False
    for pid in pids:
        try:
            pinned = pin(pid)
        except (ProcessLookupError, OSError):
            continue          # gone before it could be pinned
        try:
            if not is_proxy_process(pid):
                continue
            found = True
            # Read afresh every time: a remembered yes could outlive the socket it was about.
            held = socket_inodes(pid)
            # Everything above was read under a pid. If the process it was pinned to is still
            # alive now, the pid meant that process throughout; if not, none of it is believed.
            if not pinned.alive():
                continue
            if inode in held:
                return True, f"opened by tailscaled (pid {pid})"
        finally:
            pinned.close()
    if not found:
        return False, f"no tailscaled process is running in {PROXY_UNIT}"
    return False, "the connection was opened by something other than tailscaled"


def peer_is_tailscaled(client: tuple[str, int] | None, server: tuple[str, int] | None) -> tuple[bool, str]:
    """Whether the process at the other end of this connection is tailscaled. (ok, why)."""
    check = _peer_check or _proc_peer_check
    try:
        return check(client, server)
    except Exception as exc:  # noqa: BLE001 — every failure is "cannot say", and that refuses
        return False, f"who opened the connection could not be read: {type(exc).__name__}"


IPV6_OFF = Path("sys/net/ipv6/conf/all/disable_ipv6")    # under /proc
_TRIE_TABLE = re.compile(r"(?:Main|Local|Id \d+):")
_TRIE_NODE = re.compile(r"\s*\+-- (\d{1,3}(?:\.\d{1,3}){3})/\d{1,2} \d+ \d+ \d+")
_TRIE_LEAF = re.compile(r"\s*\|-- (\d{1,3}(?:\.\d{1,3}){3})")
_TRIE_ALIAS = re.compile(r"\s*/(\d{1,2}) (universe|site|link|host|nowhere|scope=\d+) ([A-Z]+|type \d+)(?: tos=\d+)?")
_INET6_ROW = re.compile(r"([0-9a-f]{32}) [0-9a-f]{2,8} [0-9a-f]{2} [0-9a-f]{2} [0-9a-f]{2} +\S+")


def _read_table(path: Path) -> str:
    """One kernel table, read whole. Tests stand in for a read that fails once."""
    return path.read_text(encoding="ascii", errors="replace")


def _ipv4_local(trie: str) -> frozenset[str]:
    """The addresses /proc/net/fib_trie lists as this host's own (a /32 host LOCAL entry under
    its leaf). Every line must be one the kernel writes (net/ipv4/fib_trie.c fib_trie_seq_show):
    a table name, a node, a leaf or one of a leaf's entries; anything else, an entry with no leaf
    above it, or a table without the loopback address, raises MalformedTable (round 8,
    F-05B-AVAIL). A line that cannot be read is never skipped."""
    found: set[str] = set()
    leaf = None
    for line in trie.split("\n"):
        if not line.strip():
            continue
        if _TRIE_TABLE.fullmatch(line) or _TRIE_NODE.fullmatch(line):
            leaf = None
            continue
        match = _TRIE_LEAF.fullmatch(line)
        if match:
            try:
                leaf = str(ipaddress.IPv4Address(match.group(1)))
            except ValueError:
                raise MalformedTable("/proc/net/fib_trie names an address that is not one") from None
            continue
        match = _TRIE_ALIAS.fullmatch(line)
        if not match or leaf is None:
            raise MalformedTable("/proc/net/fib_trie has a line the kernel does not write")
        if match.group(1) == "32" and match.group(2) == "host" and match.group(3) == "LOCAL":
            found.add(leaf)
    if "127.0.0.1" not in found:
        # Every host that serves this app on loopback has it: a table without it is not whole.
        raise MalformedTable("/proc/net/fib_trie does not list the loopback address")
    return frozenset(found)


def _ipv6_local(inet6: str) -> frozenset[str]:
    """The addresses /proc/net/if_inet6 lists (net/ipv6/addrconf.c if6_seq_show: the address in
    32 lower-case hex digits, the interface index, prefix length, scope and flags, and the
    interface's name). Any other line raises MalformedTable (round 8, F-05B-AVAIL)."""
    found: set[str] = set()
    for line in inet6.split("\n"):
        if not line:
            continue
        match = _INET6_ROW.fullmatch(line)
        if not match:
            raise MalformedTable("/proc/net/if_inet6 has a line the kernel does not write")
        found.add(str(ipaddress.IPv6Address(int(match.group(1), 16))))
    return frozenset(found)


def _addresses_once(root: Path) -> tuple[frozenset[str] | None, str]:
    try:
        trie = _read_table(root / "net" / "fib_trie")
    except OSError:
        return None, "/proc/net/fib_trie could not be read"
    try:
        inet6: str | None = _read_table(root / "net" / "if_inet6")
    except FileNotFoundError:
        inet6 = None
    except OSError:
        return None, "/proc/net/if_inet6 could not be read"
    if inet6 is None:
        # No table is not proof that there are no IPv6 addresses: only the kernel's own switch
        # saying IPv6 is off is (round 8, F-05B-AVAIL). A missing or renamed table with IPv6 on,
        # or with the switch unreadable, is "cannot say".
        try:
            switch = _read_table(root / IPV6_OFF)
        except OSError:
            switch = ""
        if switch.removesuffix("\n") != "1":
            return None, "/proc/net/if_inet6 is missing and IPv6 is not switched off (net.ipv6.conf.all.disable_ipv6 is not 1)"
        inet6 = ""
    try:
        return _ipv4_local(trie) | _ipv6_local(inet6), ""
    except MalformedTable as exc:
        return None, str(exc)


def this_hosts_addresses(*, proc: Path | None = None) -> tuple[frozenset[str] | None, str]:
    """Every address this host's interfaces own, read from the kernel's own tables now, never
    remembered (round 7, F-05B-AVAIL): IPv4 from /proc/net/fib_trie (the host's LOCAL routes),
    IPv6 from /proc/net/if_inet6. An address the host gains or loses is in or out on the very
    next request. Not inferred from what a socket may bind to (round 6: net.ipv4.ip_nonlocal_bind
    makes that "every address"), and not asked of a CLI that can be slow or fail.

    (addresses, "") or (None, why): None when either table cannot be read, is not whole or is
    not the kernel's shape, and when the IPv6 table is missing without IPv6 switched off (round
    8, F-05B-AVAIL) — never a partial set. A failed read is tried once more at once before the
    answer is None, so a read that fails for an instant does not refuse the owner's devices."""
    root = proc or PROC
    found, why = _addresses_once(root)
    if found is not None:
        return found, ""
    found, why = _addresses_once(root)
    if found is not None:
        return found, ""
    return None, f"{why} (read twice)"


def local_addresses(*, proc: Path | None = None) -> frozenset[str] | None:
    """this_hosts_addresses without the reason."""
    return this_hosts_addresses(proc=proc)[0]


_UNREADABLE_SELF = "this server's own addresses could not be read from the kernel"


def this_host(address: str) -> tuple[bool | None, str]:
    """Whether a forwarded address is this server's own, and why not when it cannot say. The
    server is on the owner's tailnet login, so a request it sends through its own `tailscale
    serve` arrives stamped with the owner's login; it is still a request made on the server, and
    is judged as one. (None, why) when this host's addresses cannot be read, which the caller
    refuses."""
    ip = _ip(forwarded_address(address))
    if ip is None:
        return False, ""
    if _self_check is not None:
        answer = _self_check(str(ip))
        return (None, _UNREADABLE_SELF) if answer is None else (bool(answer), "")
    mine, why = this_hosts_addresses()
    if mine is None:
        return None, f"{_UNREADABLE_SELF}: {why}"
    return str(ip) in mine, ""


def is_this_host(address: str) -> bool | None:
    """this_host without the reason: True, False, or None when it cannot say."""
    return this_host(address)[0]
