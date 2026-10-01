"""The check-execution boundary: worker-authored code runs only inside an OS sandbox.

An objective's checks (pytest, a test runner, a linter) execute code the worker
wrote. They therefore never run as a plain subprocess of the dispatcher. They run
through a ``CheckRunner``, and the one runner that exists, ``NamespaceSandbox``,
gives every check:

- a fresh copy of the exact candidate tree (not the live workspace), the only
  writable path besides a size-limited private ``/tmp``;
- a minimal root filesystem assembled in a private mount namespace: ``/usr``,
  ``/bin``, ``/lib*`` and ``/sbin`` bound read-only, a curated ``/etc`` (passwd,
  group, hosts, nsswitch.conf, ld.so.cache, localtime; no shadow, no ssh, no
  credentials), private ``/proc`` and four ``/dev`` nodes, and any read-only paths
  the dispatcher operator names (an interpreter's virtualenv, for example).
  Nothing else of the host, no ``/root``, ``/home``, ``/opt``, runtime, store or
  repository, exists inside;
- an empty network namespace whose only interface is its own loopback, brought up so a
  test may serve and connect on 127.0.0.1 inside it (a uvicorn or websocket test server).
  It is not the host's loopback: no outbound connection and no host-local service;
- its own PID, IPC and UTS namespaces;
- a non-privileged identity. When the dispatcher runs as root, the check drops to
  uid/gid 65534 with every capability removed and ``no_new_privs``. Otherwise a
  user namespace maps the dispatcher's own unprivileged uid, capabilities removed.
- bounded resources: wall-clock timeout (the whole PID namespace dies with it),
  CPU, address space, file size, open files, and process count where it is per-uid.

The runner is established fail-closed. ``availability`` runs a canary inside the
sandbox that must fail to read a host sentinel, fail to write outside its tree
and ``/tmp``, fail to connect to a listener on the host's loopback, and run as the
expected uid with no effective capabilities. If any of that does not hold, or
``unshare`` is missing, the runner is unavailable and the dispatcher blocks the
task with the exact reason. There is no unsandboxed fallback.
"""

from __future__ import annotations

import json
import os
import resource
import shutil
import signal
import socket
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

__all__ = ["CheckRunner", "NamespaceSandbox", "SandboxUnavailable", "UNPRIVILEGED_UID"]

UNPRIVILEGED_UID = 65534

# Runs as root *inside* fresh namespaces, before anything of the check exists. It builds the
# root, then execs the check through chroot and setpriv. Every argument is passed positionally.
_SETUP = r'''
set -eu
tree="$1"; drop="$2"; shift 2
nro="$1"; shift
ro=""
i=0; while [ "$i" -lt "$nro" ]; do ro="$ro
$1"; shift; i=$((i+1)); done
# The new root is a tmpfs over /mnt, visible only in this mount namespace: nothing is left on the host.
R=/mnt
mount -t tmpfs -o mode=0755,nosuid,nodev,size=16m tmpfs "$R"
for d in /usr /bin /sbin /lib /lib32 /lib64 /libx32; do
  if [ -L "$d" ]; then ln -s "$(readlink "$d")" "$R$d"
  elif [ -d "$d" ]; then mkdir -p "$R$d"; mount --rbind "$d" "$R$d"; mount -o remount,bind,ro,nosuid,nodev "$R$d"; fi
done
mkdir -p "$R/etc" "$R/tmp" "$R/proc" "$R/dev"
for f in passwd group hosts nsswitch.conf ld.so.cache localtime; do
  if [ -e "/etc/$f" ]; then cp -L "/etc/$f" "$R/etc/$f"; fi
done
mount -t tmpfs -o mode=1777,nosuid,nodev,size=512m tmpfs "$R/tmp"
for n in null zero random urandom; do touch "$R/dev/$n"; mount --bind "/dev/$n" "$R/dev/$n"; done
printf '%s\n' "$ro" | while IFS= read -r p; do
  [ -n "$p" ] || continue
  mkdir -p "$R$p"; mount --rbind "$p" "$R$p"; mount -o remount,bind,ro,nosuid,nodev "$R$p"
done
mkdir -p "$R$tree"; mount --bind "$tree" "$R$tree"
mount -t proc -o nosuid,nodev,noexec proc "$R/proc"
mount -o remount,bind,ro "$R"
# The check's own loopback, in its own otherwise empty network namespace, so a test can serve and
# connect on 127.0.0.1 inside it. It is not the host's: the canary proves a listener on the host's
# loopback stays unreachable. iproute2 when there is one, else the same ioctl from python3; if both
# are missing or refused it stays down, as it was.
if command -v ip >/dev/null 2>&1; then ip link set lo up 2>/dev/null || true
elif command -v python3 >/dev/null 2>&1; then python3 -c 'import socket,fcntl,struct
s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
f=struct.unpack("16sH22x",fcntl.ioctl(s,0x8913,struct.pack("16sH22x",b"lo",0)))[1]
fcntl.ioctl(s,0x8914,struct.pack("16sH22x",b"lo",f|1))' 2>/dev/null || true; fi
if [ "$drop" = "yes" ]; then who="--reuid 65534 --regid 65534 --clear-groups"; else who=""; fi
# shellcheck disable=SC2086
exec chroot "$R" /usr/bin/setpriv $who --no-new-privs --inh-caps=-all --bounding-set=-all -- \
  /usr/bin/env -i PATH=/usr/local/bin:/usr/bin:/bin HOME=/tmp TMPDIR=/tmp LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 \
  /bin/sh -c 'cd "$0" && exec "$@"' "$@"
'''

_CANARY = r'''
import json, os, socket, sys
sentinel, host_write, port, expect_uid = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
out = {}
try:
    open(sentinel).read(); out["read_host_sentinel"] = True
except OSError:
    out["read_host_sentinel"] = False
try:
    with open(host_write, "w") as f: f.write("escaped")
    out["wrote_host_path"] = True
except OSError:
    out["wrote_host_path"] = False
for name in ("loopback", "external"):
    host = "127.0.0.1" if name == "loopback" else "1.1.1.1"
    try:
        socket.create_connection((host, port if name == "loopback" else 443), timeout=3).close()
        out[f"connected_{name}"] = True
    except OSError:
        out[f"connected_{name}"] = False
try:
    own = socket.socket(); own.bind(("127.0.0.1", 0)); own.listen(1)
    socket.create_connection(own.getsockname(), timeout=3).close(); own.close()
    out["own_loopback"] = True
except OSError:
    out["own_loopback"] = False
caps = [l.split()[1] for l in open("/proc/self/status") if l.startswith("CapEff")][0]
out["uid"] = os.getuid(); out["cap_eff"] = caps
out["expect_uid"] = expect_uid
open("tree_write_ok", "w").write("ok"); open("/tmp/tmp_write_ok", "w").write("ok")
print(json.dumps(out))
'''


def _children(pid: int) -> list[int]:
    try:
        return [int(c) for c in Path(f"/proc/{pid}/task/{pid}/children").read_text().split()]
    except OSError:
        found = []
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit():
                try:
                    if int((entry / "stat").read_text().rsplit(")", 1)[1].split()[1]) == pid:
                        found.append(int(entry.name))
                except (OSError, IndexError, ValueError):
                    continue
        return found


def _kill_namespace(unshare_pid: int) -> None:
    """SIGKILL the check's PID-namespace init; the kernel then kills every process in the namespace.

    ``unshare --kill-child`` is not enough on its own: the parent-death signal it relies on is cleared
    when ``setpriv`` changes the uid, and a process group can be left with ``setsid``. PID 1 of the
    namespace cannot be escaped from.
    """
    for child in _children(unshare_pid):
        try:
            os.kill(child, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        os.killpg(unshare_pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


class SandboxUnavailable(RuntimeError):
    """The sandbox cannot be established here. Checks are not run; the task blocks with this reason."""


class CheckRunner(Protocol):
    """Runs one check against an exact tree and reports what happened. Never on the host directly."""

    kind: str

    def availability(self) -> tuple[bool, str]: ...

    def run(self, argv: tuple[str, ...], *, tree: Path, cwd: str, timeout_s: int) -> dict: ...


@dataclass
class NamespaceSandbox:
    """Linux namespaces via util-linux ``unshare``, a chroot and ``setpriv``. Replaceable behind ``CheckRunner``."""

    ro_paths: tuple[str, ...] = ()
    memory_bytes: int = 4 * 1024**3
    file_bytes: int = 1024**3
    open_files: int = 1024
    processes: int = 512
    kind: str = "linux-namespaces"
    _verdict: tuple[bool, str] | None = field(default=None, init=False, repr=False)

    @property
    def as_root(self) -> bool:
        return os.geteuid() == 0

    def _argv(self, tree: Path, argv: tuple[str, ...]) -> list[str]:
        unshare = shutil.which("unshare", path="/usr/bin:/bin:/usr/sbin:/sbin")
        if unshare is None:
            raise SandboxUnavailable("util-linux unshare is not installed")
        ns = ["--mount", "--net", "--pid", "--ipc", "--uts", "--fork", "--kill-child", "--propagation", "private"]
        if not self.as_root:
            ns = ["--user", "--map-root-user", *ns]
        ro = [str(Path(p).resolve()) for p in self.ro_paths]
        for p in ro:
            if not Path(p).is_dir():
                raise SandboxUnavailable(f"read-only path {p} is not a directory")
        return [unshare, *ns, "/bin/sh", "-c", _SETUP, "clive-check",
                str(tree), "yes" if self.as_root else "no", str(len(ro)), *ro, *argv]

    def _limits(self, timeout_s: int):
        def apply() -> None:
            os.setsid()
            resource.setrlimit(resource.RLIMIT_CPU, (timeout_s + 5, timeout_s + 10))
            resource.setrlimit(resource.RLIMIT_AS, (self.memory_bytes, self.memory_bytes))
            resource.setrlimit(resource.RLIMIT_FSIZE, (self.file_bytes, self.file_bytes))
            resource.setrlimit(resource.RLIMIT_NOFILE, (self.open_files, self.open_files))
            if self.as_root:  # RLIMIT_NPROC counts per real uid: meaningful once the check is uid 65534
                resource.setrlimit(resource.RLIMIT_NPROC, (self.processes, self.processes))
        return apply

    def _prepare(self, tree: Path) -> None:
        if self.as_root:
            for root, dirs, files in os.walk(tree):
                for name in (*dirs, *files):
                    os.lchown(os.path.join(root, name), UNPRIVILEGED_UID, UNPRIVILEGED_UID)
            os.lchown(tree, UNPRIVILEGED_UID, UNPRIVILEGED_UID)

    def _exec(self, argv: tuple[str, ...], *, tree: Path, cwd: str, timeout_s: int) -> tuple[int, str, str]:
        tree = Path(tree).resolve()
        if tree == Path("/mnt") or Path("/mnt") in tree.parents:
            raise SandboxUnavailable("the candidate tree may not live under /mnt, where the sandbox builds its root")
        workdir = (tree / cwd).resolve()
        if tree not in (workdir, *workdir.parents):
            return 126, "", "check cwd escapes the candidate tree"
        self._prepare(tree)
        full = self._argv(tree, (str(workdir), *argv))
        proc = subprocess.Popen(full, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"}, preexec_fn=self._limits(timeout_s),
                                stdin=subprocess.DEVNULL)
        try:
            out, err = proc.communicate(timeout=timeout_s)
            return proc.returncode, out, err
        except subprocess.TimeoutExpired:
            _kill_namespace(proc.pid)
            out, err = proc.communicate()
            return 124, out, f"timed out after {timeout_s}s; the check's PID namespace was killed"

    def availability(self) -> tuple[bool, str]:
        if self._verdict is None:
            try:
                self._verdict = self._canary()
            except SandboxUnavailable as exc:
                self._verdict = (False, str(exc))
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                self._verdict = (False, f"sandbox canary failed to run: {exc}")
        return self._verdict

    def _canary(self) -> tuple[bool, str]:
        with tempfile.TemporaryDirectory(prefix="clive-canary-") as host:
            host_dir = Path(host)
            sentinel = host_dir / "host-sentinel"
            sentinel.write_text("host secret\n")
            sentinel.chmod(0o644)  # world-readable on purpose: only its absence from the sandbox protects it
            escape = host_dir / "escaped"
            tree = host_dir / "tree"
            tree.mkdir()
            (tree / "canary.py").write_text(_CANARY)
            self._argv(tree, ())  # unshare present and read-only paths valid, before anything else
            python = shutil.which("python3", path="/usr/local/bin:/usr/bin:/bin")
            if python is None:
                raise SandboxUnavailable("no python3 under /usr to run the sandbox canary")
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            accepted: list[bool] = []

            def accept() -> None:
                listener.settimeout(8)
                try:
                    conn, _ = listener.accept()
                    accepted.append(True)
                    conn.close()
                except OSError:
                    pass

            thread = threading.Thread(target=accept, daemon=True)
            thread.start()
            expect = UNPRIVILEGED_UID if self.as_root else 0
            code, out, err = self._exec((python, "canary.py", str(sentinel), str(escape),
                                         str(listener.getsockname()[1]), str(expect)),
                                        tree=tree, cwd=".", timeout_s=60)
            listener.close()
            if code != 0:
                raise SandboxUnavailable(f"sandbox could not be established (exit {code}): {err.strip()[-400:]}")
            facts = json.loads(out.strip().splitlines()[-1])
            # A write "succeeding" inside may have landed in the sandbox's private /tmp (the host path lies under
            # /tmp here); only the host's own file system says whether it escaped.
            problems = [k for k in ("read_host_sentinel", "connected_loopback", "connected_external") if facts.get(k)]
            if escape.exists():
                problems.append("wrote_host_path")
            if accepted:
                problems.append("host loopback listener accepted a connection")
            if facts.get("uid") != expect:
                problems.append(f"uid {facts.get('uid')} is not {expect}")
            if int(str(facts.get("cap_eff", "1")), 16) != 0:
                problems.append(f"effective capabilities {facts.get('cap_eff')}")
            if not (tree / "tree_write_ok").exists():
                problems.append("the candidate tree was not writable inside the sandbox")
            if problems:
                raise SandboxUnavailable("sandbox canary escaped: " + ", ".join(problems))
            who = f"uid {UNPRIVILEGED_UID}" if self.as_root else "a user namespace over the dispatcher's own uid"
            loopback = "its own loopback up" if facts.get("own_loopback") else "its own loopback down (no iproute2)"
            return True, (f"linux namespaces (mount, net, pid, ipc, uts), chroot, {who}, no capabilities, "
                          f"{loopback}; canary held")

    def run(self, argv: tuple[str, ...], *, tree: Path, cwd: str, timeout_s: int) -> dict:
        ok, why = self.availability()
        if not ok:
            raise SandboxUnavailable(why)
        code, out, err = self._exec(tuple(argv), tree=tree, cwd=cwd, timeout_s=timeout_s)
        return {"exit_code": code, "stdout_tail": out[-6000:], "stderr_tail": err[-3000:], "runner": self.kind,
                "sandbox": why}
