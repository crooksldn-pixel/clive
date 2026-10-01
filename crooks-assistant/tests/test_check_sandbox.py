"""Adversarial: candidate-controlled check code cannot escape the check sandbox.

The candidate here is hostile test code run the way an objective's check runs it:
the real ``pytest`` of this virtualenv, inside ``NamespaceSandbox``, on an exported
tree. Every property is asserted from the host's side, not from what the code
inside reports about itself.

Not every test host can establish the sandbox (the CI runner is a non-root user on a
kernel that restricts unprivileged user namespaces). There the dispatcher fails
closed, which the tests at the end of this file prove on every host; the escape
tests skip with the canary's exact reason. A host that runs the dispatcher must
establish it: with ``CLIVE_REQUIRE_CHECK_SANDBOX=1`` a skip becomes a failure.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

from app.orchestrator.checks import UNPRIVILEGED_UID, NamespaceSandbox, SandboxUnavailable

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the sandbox is Linux namespaces")

HOSTILE_TEST = r'''
import json, os, socket
from pathlib import Path

SENTINEL = {sentinel!r}
OUTSIDE = {outside!r}
PORT = {port}

def test_escape_attempts():
    report = {{}}
    try:
        report["sentinel"] = Path(SENTINEL).read_text()
    except OSError as exc:
        report["sentinel"] = "denied: " + type(exc).__name__
    report["proc1_environ_keys"] = sorted(
        e.split(b"=", 1)[0].decode() for e in Path("/proc/1/environ").read_bytes().split(b"\0") if e)
    for name in ("shadow", "root_home"):
        path = {{"shadow": "/etc/shadow", "root_home": "/root"}}[name]
        try:
            report[name] = os.listdir(path) if os.path.isdir(path) else Path(path).read_bytes()[:40].hex()
        except OSError as exc:
            report[name] = "denied: " + type(exc).__name__
    written = []
    for target in (OUTSIDE, "/usr/clive-escape", "/etc/clive-escape", "/clive-escape"):
        try:
            Path(target).write_text("escaped")
            written.append(target)
        except OSError:
            pass
    report["written"] = written
    for name, address in (("loopback", ("127.0.0.1", PORT)), ("external", ("1.1.1.1", 443))):
        try:
            socket.create_connection(address, timeout=3).close()
            report[name] = "CONNECTED"
        except OSError as exc:
            report[name] = "denied: " + type(exc).__name__
    report["uid"] = os.getuid()
    report["cap_eff"] = [l.split()[1] for l in open("/proc/self/status") if l.startswith("CapEff")][0]
    Path("report.json").write_text(json.dumps(report))
    Path("/tmp/private-tmp-works").write_text("ok")
'''


def require_sandbox(box: NamespaceSandbox) -> NamespaceSandbox:
    """The sandbox, or a skip naming why this host cannot establish it (a failure where it is required)."""
    ok, why = box.availability()
    if not ok:
        if os.environ.get("CLIVE_REQUIRE_CHECK_SANDBOX") == "1":
            pytest.fail(f"CLIVE_REQUIRE_CHECK_SANDBOX=1 but the check sandbox cannot be established: {why}")
        pytest.skip(f"the check sandbox cannot be established on this host (the dispatcher fails closed): {why}")
    return box


@pytest.fixture
def sandbox() -> NamespaceSandbox:
    return require_sandbox(NamespaceSandbox(ro_paths=(sys.prefix,)))


@pytest.fixture
def listener():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(4)
    sock.settimeout(0.2)
    accepted: list[bool] = []
    stop = threading.Event()

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = sock.accept()
                accepted.append(True)
                conn.close()
            except OSError:
                continue

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield sock.getsockname()[1], accepted
    stop.set()
    thread.join(timeout=2)
    sock.close()


def test_hostile_candidate_test_code_cannot_read_write_or_connect_out(tmp_path, sandbox, listener):
    port, accepted = listener
    host = tmp_path / "host"
    host.mkdir()
    sentinel = host / "sentinel-secret"
    sentinel.write_text("TOP SECRET host credential\n")
    sentinel.chmod(0o644)  # readable by anyone on the host: only the sandbox keeps it out
    outside = host / "written-from-the-sandbox"
    tree = tmp_path / "candidate"
    tree.mkdir()
    (tree / "test_hostile.py").write_text(HOSTILE_TEST.format(sentinel=str(sentinel), outside=str(outside), port=port))

    result = sandbox.run((sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_hostile.py"),
                         tree=tree, cwd=".", timeout_s=120)

    assert result["exit_code"] == 0, result
    report = json.loads((tree / "report.json").read_text())
    # 1. the host sentinel is not readable
    assert report["sentinel"].startswith("denied") and "TOP SECRET" not in json.dumps(report)
    assert all(str(report[k]).startswith("denied") for k in ("shadow", "root_home")), report
    # /proc is the sandbox's own: PID 1 is the check's init, whose environment is the sandbox's, not the host's
    assert set(report["proc1_environ_keys"]) <= {"PATH", "HOME", "TMPDIR", "LANG", "PYTHONDONTWRITEBYTECODE",
                                                 "OLDPWD", "PWD", "SHLVL", "_"}, report
    # 2. nothing was written outside the tree and the private /tmp, checked on the host itself
    assert not outside.exists()
    for path in ("/usr/clive-escape", "/etc/clive-escape", "/clive-escape"):
        assert not Path(path).exists()
    assert not Path("/tmp/private-tmp-works").exists()  # the sandbox's /tmp is its own
    # 3. no network: neither the host's loopback service nor the outside world
    assert report["loopback"].startswith("denied") and report["external"].startswith("denied")
    assert accepted == []
    # a non-privileged identity with no capabilities
    assert report["uid"] == (UNPRIVILEGED_UID if os.geteuid() == 0 else 0)
    assert int(report["cap_eff"], 16) == 0
    assert sentinel.read_text() == "TOP SECRET host credential\n"


def test_the_host_filesystem_beyond_the_minimal_root_does_not_exist_inside(tmp_path, sandbox):
    tree = tmp_path / "candidate"
    tree.mkdir()
    probe = "import os, json; print(json.dumps({'root': sorted(os.listdir('/')), 'etc': sorted(os.listdir('/etc'))}))"
    result = sandbox.run((sys.executable, "-c", probe), tree=tree, cwd=".", timeout_s=60)
    seen = json.loads(result["stdout_tail"].strip().splitlines()[-1])
    assert set(seen["root"]) <= {"bin", "dev", "etc", "lib", "lib32", "lib64", "libx32", "proc", "sbin", "tmp", "usr",
                                 *(Path(p).parts[1] for p in (str(tree), sys.prefix))}
    assert "root" not in seen["root"] and "opt" not in seen["root"]
    assert set(seen["etc"]) <= {"passwd", "group", "hosts", "nsswitch.conf", "ld.so.cache", "localtime"}


def test_a_timeout_kills_the_whole_check_including_its_background_children(tmp_path, sandbox):
    tree = tmp_path / "candidate"
    tree.mkdir()
    # the background loop even leaves the process group; only the PID namespace can take it down
    script = "setsid sh -c 'while true; do date +%s%N >> beat; sleep 0.1; done' & sleep 300"
    started = time.monotonic()
    result = sandbox.run(("/bin/sh", "-c", script), tree=tree, cwd=".", timeout_s=2)
    assert result["exit_code"] == 124 and time.monotonic() - started < 15
    size = (tree / "beat").stat().st_size
    time.sleep(0.6)
    assert (tree / "beat").stat().st_size == size  # the background loop died with the PID namespace


def test_a_check_cwd_cannot_escape_the_tree(tmp_path, sandbox):
    tree = tmp_path / "candidate"
    tree.mkdir()
    result = sandbox.run(("/bin/true",), tree=tree, cwd="../..", timeout_s=10)
    assert result["exit_code"] == 126


def test_an_unestablishable_sandbox_is_unavailable_and_refuses_to_run(tmp_path):
    box = NamespaceSandbox(ro_paths=(str(tmp_path / "does-not-exist"),))
    ok, why = box.availability()
    assert not ok and "not a directory" in why
    with pytest.raises(SandboxUnavailable):
        box.run(("/bin/true",), tree=tmp_path, cwd=".", timeout_s=5)


def test_a_missing_unshare_is_unavailable_not_a_fallback(tmp_path, monkeypatch):
    import app.orchestrator.checks as checks

    monkeypatch.setattr(checks.shutil, "which", lambda name, path=None: None)
    ok, why = NamespaceSandbox().availability()
    assert not ok and "unshare is not installed" in why


def test_an_escaping_canary_makes_the_sandbox_unavailable(tmp_path, monkeypatch):
    import app.orchestrator.checks as checks

    require_sandbox(NamespaceSandbox())  # the canary must run for its report to be judged
    # The canary reports a connection (as it would in a sandbox that leaked the network): it must fail closed.
    monkeypatch.setattr(checks, "_CANARY", checks._CANARY.replace('out[f"connected_{name}"] = False',
                                                                  'out[f"connected_{name}"] = True'))
    ok, why = NamespaceSandbox().availability()
    assert not ok and "canary escaped" in why and "connected_loopback" in why


def test_a_host_that_refuses_namespaces_makes_the_sandbox_unavailable(tmp_path, monkeypatch):
    """What the CI runner sees: unshare exists but the kernel refuses the namespaces. Runs on every host."""
    import app.orchestrator.checks as checks

    refusing = tmp_path / "unshare"
    refusing.write_text("#!/bin/sh\necho 'unshare: write failed /proc/self/uid_map: Operation not permitted' >&2\nexit 1\n")
    refusing.chmod(0o755)
    real_which = checks.shutil.which
    monkeypatch.setattr(checks.shutil, "which",
                        lambda name, path=None: str(refusing) if name == "unshare" else real_which(name, path=path))
    box = NamespaceSandbox()
    ok, why = box.availability()
    assert not ok and "could not be established" in why and "Operation not permitted" in why
    with pytest.raises(SandboxUnavailable):
        box.run(("/bin/true",), tree=tmp_path, cwd=".", timeout_s=5)


OWN_LOOPBACK = r'''
import json, socket, sys
port = int(sys.argv[1])
report = {}
server = socket.socket()
server.bind(("127.0.0.1", 0))
server.listen(1)
client = socket.create_connection(server.getsockname(), timeout=3)
conn, _ = server.accept()
client.sendall(b"ping")
report["own"] = conn.recv(4).decode()
try:
    socket.create_connection(("127.0.0.1", port), timeout=3).close()
    report["host"] = "CONNECTED"
except OSError as exc:
    report["host"] = "denied: " + type(exc).__name__
print(json.dumps(report))
'''


def test_a_check_serves_and_connects_on_its_own_loopback_and_never_the_hosts(tmp_path, sandbox, listener):
    """A test server on 127.0.0.1 (uvicorn, websockets) works inside the check, on the namespace's own
    loopback; a listener on the host's loopback stays unreachable, as the canary requires."""
    port, accepted = listener
    tree = tmp_path / "tree"
    tree.mkdir()
    (tree / "own.py").write_text(OWN_LOOPBACK)
    result = sandbox.run((sys.executable, "own.py", str(port)), tree=tree, cwd=".", timeout_s=60)
    assert result["exit_code"] == 0, result
    report = json.loads(result["stdout_tail"].strip().splitlines()[-1])
    assert report["own"] == "ping"
    assert report["host"].startswith("denied"), report
    assert accepted == []
    assert "its own loopback up" in sandbox.availability()[1]
