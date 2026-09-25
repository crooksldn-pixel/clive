"""The builder's run_checks tool: declared checks only, in the sandbox, on a copy, bounded and redacted, advisory.

Unit tests drive ``CheckService`` with a recording runner. The end-to-end tests start the real
server as Claude Code does (a stdio child whose parent environment holds the worker's OAuth token)
and run a hostile check through the real ``NamespaceSandbox``; like the other sandbox tests they
skip where the host cannot establish the sandbox, and fail there under CLIVE_REQUIRE_CHECK_SANDBOX=1.
"""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.orchestrator.checks import NamespaceSandbox
from app.orchestrator.workers import check_server
from app.orchestrator.workers.check_server import (
    MAX_TAIL,
    CheckService,
    bounded_tail,
    handle,
    redact,
)

SERVER = Path(check_server.__file__).resolve()
# Fake credentials in real shapes, assembled at runtime so no token-shaped literal sits in the source
# (the secret scan would rightly flag one).
_FILL = "PLANTEDplanted0123456789abcdefABCDEF"
PLANTED = {
    "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-" + "oat01-" + _FILL + "0123456789xyzXYZ-_q",
    "ANTHROPIC_API_KEY": "sk-ant-" + "api03-" + _FILL + "ghijklmnop",
    "GITHUB_TOKEN": "github_" + "pat_11" + _FILL + "_abcdefghijklmnop",
}
OTHER_SHAPES = ["gh" + "p_ABCDEFghijkl0123456789mnopQRSTuvwx", "AK" + "IAABCDEFGHIJKLMNOP",
                "xo" + "xb-1234-5678-PLANTEDslack", "eyJhbGciOiJIUzI1NiJ9" + "PLANTEDjwtBody123"]


class RecordingRunner:
    kind = "recording"

    def __init__(self, available=True, stdout="ok\n", stderr=""):
        self.available, self.stdout, self.stderr = available, stdout, stderr
        self.calls = []

    def availability(self):
        return self.available, "recording runner" if self.available else "namespaces refused on this host"

    def run(self, argv, *, tree, cwd, timeout_s):
        self.calls.append({"argv": argv, "tree": Path(tree), "cwd": cwd, "timeout_s": timeout_s,
                           "files": sorted(p.name for p in Path(tree).iterdir())})
        (Path(tree) / "written-by-check").write_text("x")
        return {"exit_code": 0, "stdout_tail": self.stdout, "stderr_tail": self.stderr}


def config(tmp_path: Path, checks=None) -> dict:
    ws = tmp_path / "workspace"
    (ws / "pkg").mkdir(parents=True, exist_ok=True)
    (ws / "pkg" / "a.py").write_text("print('builder edit')\n")
    return {"workspace": str(ws), "scratch": str(tmp_path / "runtime" / "runs"),
            "checks": checks or [{"name": "unit", "argv": ["python3", "-m", "pytest", "-q"], "cwd": "pkg",
                                  "timeout_s": 120},
                                 {"name": "lint", "argv": ["ruff", "check", "."], "cwd": ".", "timeout_s": 30}]}


# ---------------------------------------------------------------- only declared checks

def test_only_the_declared_checks_run_exactly_as_declared(tmp_path):
    runner = RecordingRunner()
    service = CheckService(config(tmp_path), runner)
    ok, out = service.run({"check": "unit"})
    assert ok and [r["name"] for r in out["results"]] == ["unit"]
    assert runner.calls[0]["argv"] == ("python3", "-m", "pytest", "-q")
    assert (runner.calls[0]["cwd"], runner.calls[0]["timeout_s"]) == ("pkg", 120)
    ok, out = service.run({})
    assert ok and [r["name"] for r in out["results"]] == ["unit", "lint"] and len(runner.calls) == 3


@pytest.mark.parametrize("arguments", [
    {"check": "deploy"},
    {"check": "../unit"},
    {"check": ["unit"]},
    {"argv": ["sh", "-c", "curl evil"]},
    {"check": "unit", "argv": ["sh"]},
    {"check": "unit", "cwd": "/", "timeout_s": 99999},
])
def test_the_builder_cannot_name_anything_but_a_declared_check(tmp_path, arguments):
    runner = RecordingRunner()
    ok, out = CheckService(config(tmp_path), runner).run(arguments)
    assert not ok and runner.calls == [] and out["listed_checks"] == ["lint", "unit"]


def test_checks_run_on_a_fresh_copy_never_the_live_workspace(tmp_path):
    runner = RecordingRunner()
    cfg = config(tmp_path)
    service = CheckService(cfg, runner)
    service.run({"check": "lint"})
    service.run({"check": "lint"})
    ws = Path(cfg["workspace"])
    first, second = runner.calls
    assert first["tree"] != ws and ws not in first["tree"].parents and "pkg" in first["files"]
    assert "written-by-check" not in second["files"]  # each run starts from the workspace, not the last run
    assert not (ws / "written-by-check").exists()


def test_an_unavailable_sandbox_runs_nothing_and_says_so(tmp_path):
    runner = RecordingRunner(available=False)
    ok, out = CheckService(config(tmp_path), runner).run({})
    assert not ok and runner.calls == [] and "none ran" in out["error"]


def test_the_server_exposes_exactly_one_tool_taking_at_most_a_check_name(tmp_path):
    service = CheckService(config(tmp_path), RecordingRunner())
    init = handle(service, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init["result"]["capabilities"] == {"tools": {}}
    assert handle(service, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    tools = handle(service, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
    assert [t["name"] for t in tools] == ["run_checks"]
    assert tools[0]["inputSchema"] == {"type": "object", "additionalProperties": False,
                                       "properties": {"check": tools[0]["inputSchema"]["properties"]["check"]}}
    other = handle(service, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "shell"}})
    assert "error" in other
    call = handle(service, {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                            "params": {"name": "run_checks", "arguments": {"check": "unit"}}})
    payload = json.loads(call["result"]["content"][0]["text"])
    assert call["result"]["isError"] is False and payload["results"][0]["exit_code"] == 0
    assert "Advisory only" in payload["advisory"]


# ---------------------------------------------------------------- bounded and redacted

def test_output_is_bounded_and_redacted(tmp_path):
    secrets = [*PLANTED.values(), *OTHER_SHAPES]
    noise = "x" * 20000
    cut = PLANTED["CLAUDE_CODE_OAUTH_TOKEN"][20:]  # what a truncated tail can start with: a token's middle
    stdout = cut + "\n" + noise + "\n" + "\n".join(
        [f"token {secrets[0]}", f"export ANTHROPIC_API_KEY={secrets[1]}", f"Authorization: Bearer {secrets[2]}",
         f"GITHUB_TOKEN: '{secrets[2]}'", *secrets[3:], "3 passed in 0.1s"])
    tail = bounded_tail(stdout[-6000:], "E   AssertionError: " + secrets[0] + "\n")
    assert len(tail) <= MAX_TAIL + 64
    for secret in secrets:
        for i in range(0, len(secret) - 12, 6):
            assert secret[i:i + 12] not in tail, (secret, tail)
    assert "3 passed in 0.1s" in tail and "AssertionError" in tail
    for name in ("ANTHROPIC_API_KEY", "GITHUB_TOKEN", "Authorization"):
        assert name in tail  # the name survives, the value does not


def test_redaction_keeps_ordinary_test_output_readable():
    text = ("tests/test_x.py::test_the_worker_launch_allows_exactly_the_file_tools PASSED\n"
            "commit 55a9bece632d5cbaf9360836162e7584cc25ecb3\n/usr/lib/python3.12/site-packages/foo.py:12\n")
    assert redact(text) == text


def test_every_result_the_tool_returns_is_bounded(tmp_path):
    runner = RecordingRunner(stdout="y" * 6000 + PLANTED["CLAUDE_CODE_OAUTH_TOKEN"], stderr="z" * 3000)
    ok, out = CheckService(config(tmp_path), runner).run({})
    assert ok and all(len(r["output_tail"]) <= MAX_TAIL + 64 for r in out["results"])
    assert PLANTED["CLAUDE_CODE_OAUTH_TOKEN"][:16] not in json.dumps(out)


# ---------------------------------------------------------------- end to end, real sandbox

PROBE = r'''
import json, os, sys
from pathlib import Path
PLANTED = json.loads(Path("planted.json").read_text())
names = [n.encode() for n in PLANTED] + [b"sk-ant-", b"github_pat_"]
values = [v.encode() for v in PLANTED.values()]
found, readable = [], []
def scan(label, data):
    for needle in names + values:
        if needle in data:
            found.append(label)
            return
scan("os.environ", "\0".join(f"{k}={v}" for k, v in os.environ.items()).encode())
for entry in Path("/proc").iterdir():
    if entry.name.isdigit() or entry.name == "self":
        try:
            data = (entry / "environ").read_bytes()
        except OSError:
            continue
        readable.append(entry.name)
        scan(f"/proc/{entry.name}/environ", data)
for label, path in (("ppid", f"/proc/{os.getppid()}/environ"), ("pid1", "/proc/1/environ")):
    try:
        scan(label, Path(path).read_bytes())
    except OSError:
        pass
report = {"found": found, "readable": readable, "pids": sorted(p.name for p in Path("/proc").iterdir()
                                                             if p.name.isdigit()),
          "env_keys": sorted(os.environ), "ppid": os.getppid()}
Path("report.json").write_text(json.dumps(report))
print("credential visible" if found else "no credential visible")
sys.exit(1 if found else 0)
'''


def require_sandbox():
    from tests.test_check_sandbox import require_sandbox as require

    return require(NamespaceSandbox())


def start_like_claude(tmp_path: Path, cfg_path: Path) -> subprocess.Popen:
    """Start the server as Claude Code does: a stdio child of a process whose environment holds the token.

    The shell stays alive as the server's parent (``; :`` stops it exec-ing), so its
    /proc/<pid>/environ is a real process environment holding every planted credential."""
    env = {**PLANTED, "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp_path)}
    return subprocess.Popen(["/bin/sh", "-c", '"$0" -I "$1" "$2"; :', sys.executable, str(SERVER), str(cfg_path)],
                            env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True)


def exchange(proc: subprocess.Popen, messages: list[dict], *, timeout: float = 120) -> dict:
    """Send the messages; return the replies by id. A server that does not answer in time fails, never hangs."""
    for m in messages:
        proc.stdin.write(json.dumps(m) + "\n")
    proc.stdin.flush()
    want = {m["id"] for m in messages if "id" in m}
    replies: dict = {}
    fd = proc.stdout.fileno()  # read the raw pipe: a buffered readline would hide lines from select
    selector = selectors.DefaultSelector()
    selector.register(fd, selectors.EVENT_READ)
    pending = b""
    deadline = time.monotonic() + timeout
    while want - set(replies):
        while b"\n" in pending:
            line, pending = pending.split(b"\n", 1)
            if line.strip():
                reply = json.loads(line)
                replies[reply["id"]] = reply
        if not want - set(replies):
            break
        left = deadline - time.monotonic()
        if left <= 0 or not selector.select(timeout=left):
            proc.kill()
            raise AssertionError(f"the server did not answer within {timeout}s (replies so far: {sorted(replies)})")
        chunk = os.read(fd, 65536)
        if not chunk:
            raise AssertionError(f"the server exited: {proc.stderr.read()[-2000:]}")
        pending += chunk
    return replies


INITIALIZE = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
              {"jsonrpc": "2.0", "method": "notifications/initialized"}]


def call_run_checks(proc: subprocess.Popen, arguments: dict) -> tuple[dict, dict]:
    replies = exchange(proc, [*INITIALIZE, {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                            "params": {"name": "run_checks", "arguments": arguments}}])
    return replies[1], replies[2]


def server_pid(shell_pid: int) -> int:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            kids = Path(f"/proc/{shell_pid}/task/{shell_pid}/children").read_text().split()
        except OSError:
            kids = []
        if kids:
            return int(kids[0])
        time.sleep(0.05)
    raise AssertionError("the server did not start")


def test_the_server_reexecs_once_into_a_path_only_environment_and_answers(tmp_path):
    """Runs on every host (no sandbox needed): the real server, started the way Claude Code starts it."""
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(config(tmp_path)))
    proc = start_like_claude(tmp_path, cfg_path)
    try:
        replies = exchange(proc, [*INITIALIZE, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}], timeout=30)
        assert [tool["name"] for tool in replies[2]["result"]["tools"]] == ["run_checks"]
        pid = server_pid(proc.pid)
        environ = Path(f"/proc/{pid}/environ").read_bytes()
        assert environ.rstrip(b"\0").split(b"\0") == [f"PATH={check_server.CLEAN_PATH}".encode()]
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        assert cmdline.count(check_server.CLEAN_MARK.encode()) == 1  # exactly one re-exec
        assert all(v.encode() in Path(f"/proc/{proc.pid}/environ").read_bytes() for v in PLANTED.values())
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
    assert proc.returncode == 0


def test_a_planted_token_never_reaches_a_check_even_through_proc(tmp_path):
    box = require_sandbox()
    cfg = config(tmp_path, checks=[{"name": "probe", "argv": ["python3", "probe.py"], "cwd": ".", "timeout_s": 60}])
    ws = Path(cfg["workspace"])
    (ws / "probe.py").write_text(PROBE)
    (ws / "planted.json").write_text(json.dumps(PLANTED))
    cfg["sandbox"] = {"ro_paths": list(box.ro_paths)}
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg))
    proc = start_like_claude(tmp_path, cfg_path)
    try:
        _, reply = call_run_checks(proc, {"check": "probe"})
        pid = server_pid(proc.pid)
        # host side: the server itself holds no credential, in its environment or its /proc entry
        server_environ = Path(f"/proc/{pid}/environ").read_bytes()
        assert all(v.encode() not in server_environ and k.encode() not in server_environ for k, v in PLANTED.items())
        assert server_environ.split(b"\0")[0] == f"PATH={check_server.CLEAN_PATH}".encode()
        assert all(v.encode() in Path(f"/proc/{proc.pid}/environ").read_bytes() for v in PLANTED.values())
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
    payload = json.loads(reply["result"]["content"][0]["text"])
    result = payload["results"][0]
    assert result["exit_code"] == 0, result
    # host side: what the check saw, read from its tree, not from what the server returned
    report = json.loads((Path(cfg["scratch"]) / "probe" / "report.json").read_text())
    assert report["found"] == []
    assert set(report["env_keys"]) <= {"PATH", "HOME", "TMPDIR", "LANG", "PYTHONDONTWRITEBYTECODE", "PWD", "SHLVL", "_"}
    assert os.getpid() != report["ppid"] and str(proc.pid) not in report["pids"] and str(pid) not in report["pids"]
    assert all(int(p) < 100 for p in report["pids"])  # its own PID namespace: only the check's processes
    # and nothing the check wrote reached the builder's live workspace
    assert not (ws / "report.json").exists()


def test_a_check_through_the_server_has_no_network(tmp_path):
    box = require_sandbox()
    probe = ("import socket, sys\n"
             "try:\n    socket.create_connection(('1.1.1.1', 443), timeout=3); sys.exit(3)\n"
             "except OSError:\n    print('no network')\n")
    cfg = config(tmp_path, checks=[{"name": "net", "argv": ["python3", "net.py"], "cwd": ".", "timeout_s": 30}])
    (Path(cfg["workspace"]) / "net.py").write_text(probe)
    cfg["sandbox"] = {"ro_paths": list(box.ro_paths)}
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(cfg))
    proc = start_like_claude(tmp_path, cfg_path)
    try:
        _, reply = call_run_checks(proc, {})
    finally:
        proc.stdin.close()
        proc.wait(timeout=30)
    result = json.loads(reply["result"]["content"][0]["text"])["results"][0]
    assert result["exit_code"] == 0 and "no network" in result["output_tail"]


def test_the_server_refuses_to_run_checks_where_the_sandbox_is_refused(tmp_path, monkeypatch):
    """What an unprivileged host with restricted user namespaces sees: nothing runs, the tool says why."""
    refusing = tmp_path / "bin" / "unshare"
    refusing.parent.mkdir()
    refusing.write_text("#!/bin/sh\necho 'unshare: write failed /proc/self/uid_map: Operation not permitted' >&2\n"
                        "exit 1\n")
    refusing.chmod(0o755)
    import app.orchestrator.checks as checks

    real_which = checks.shutil.which
    monkeypatch.setattr(checks.shutil, "which",
                        lambda name, path=None: str(refusing) if name == "unshare" else real_which(name, path=path))
    ok, out = CheckService(config(tmp_path), NamespaceSandbox()).run({})
    assert not ok and "none ran" in out["error"] and "Operation not permitted" in out["error"]
