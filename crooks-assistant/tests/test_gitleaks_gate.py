"""The gitleaks commit/publish gate: it scans what would be published, and it never prints
what it finds.

These tests build a throwaway repository, stage a synthetic token-shaped string, and run the
gate exactly as Claude Code would (JSON on stdin, verdict by exit code). The string is not a
credential: it is `ghp_` followed by mixed characters so that gitleaks' `github-pat` rule
(which has an entropy floor) fires on it. The tests assert the value never reaches stdout or
stderr — that is the property the gate exists for.

gitleaks itself is the builder's pinned binary (docs/DEV_ENVIRONMENT.md §4). If it is not
present, the gate must DENY (a publish with no scan is not a pass) and the scanning tests
here are skipped with the reason stated — a skipped test proves nothing and says so.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS_DIR = Path(__file__).resolve().parent.parent / "scripts" / "hooks"
GATE = HOOKS_DIR / "gitleaks_gate.py"
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

import gitleaks_gate as gate  # noqa: E402
import guard_bash as gb  # noqa: E402

SYNTHETIC = "ghp_" + "1a2B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ"  # token-SHAPED; not a credential


def _gitleaks() -> str | None:
    candidates = [
        Path(__file__).resolve().parents[2] / ".tooling" / "bin" / "gitleaks",
        Path("/opt/crooks-builder/.tooling/bin/gitleaks"),
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return shutil.which("gitleaks")


def _git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True,
                                   stderr=subprocess.STDOUT)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    (r / "a.txt").write_text("clean\n")
    _git(r, "add", "a.txt")
    _git(r, "commit", "-qm", "init")
    return r


def payload(command: str, cwd: Path) -> bytes:
    return json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                       "cwd": str(cwd)}).encode()


def run_gate_process(command: str, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    """Run the gate as Claude Code would. The candidate worktree has no `.tooling/` of its own
    (it is gitignored, per docs/DEV_ENVIRONMENT.md §2), so the pinned gitleaks is put on PATH
    for the subprocess — ordinary binary resolution, which is the gate's documented fallback.
    There is no variable that points the gate at a binary, on purpose."""
    env = dict(os.environ)
    binary = _gitleaks()
    if binary:
        env["PATH"] = str(Path(binary).parent) + os.pathsep + env.get("PATH", "")
    return subprocess.run([sys.executable, str(GATE)], input=payload(command, cwd),
                          capture_output=True, timeout=120, check=False, env=env)


# ---------------------------------------------------------------------------------------------


def test_non_publish_commands_are_not_scanned_and_pass(tmp_path: Path) -> None:
    for command in ("git status", "make test", "ls", "git diff --cached", "git add ."):
        assert not gate.run_gate(payload(command, tmp_path), gitleaks="/nonexistent").denied


def test_malformed_input_is_denied() -> None:
    for raw in (b"", b"nope", b"[]", json.dumps({"tool_name": "Write"}).encode(),
                json.dumps({"tool_name": "Bash", "tool_input": {"command": 1}}).encode()):
        assert gate.run_gate(raw).denied


def test_a_missing_gitleaks_denies_a_commit_rather_than_waving_it_through(repo: Path) -> None:
    d = gate.run_gate(payload("git commit -m x", repo), gitleaks="/nonexistent/gitleaks")
    assert d.denied and d.rule in ("GITLEAKS-MISSING", "GITLEAKS-ERROR")


def test_publishing_from_a_protected_checkout_is_refused_before_any_scan() -> None:
    d = gate.run_gate(payload("git commit -m x", Path("/opt/crooks-os/crooks-assistant")),
                      gitleaks="/nonexistent")
    assert d.rule == "PROTECTED-PATH"
    d = gate.run_gate(payload("git -C /opt/crooks-os push", Path("/tmp")), gitleaks="/nonexistent")
    assert d.rule == "PROTECTED-PATH"


def test_publish_actions_are_found_behind_wrappers_and_separators() -> None:
    actions = gate._publish_actions("cd x && sudo git -C /tmp/r commit -m 'a; b' ; git push -u o h")
    assert [(a[0], a[2]) for a in actions] == [("commit", "/tmp/r"), ("push", None)]
    assert gate._publish_actions("git commit --help | cat") == [("commit", ["--help"], None)] or \
        gate._publish_actions("git commit --help | cat")[0][0] == "commit"
    assert gate._publish_actions("echo 'git commit -m x'") == []


needs_gitleaks = pytest.mark.skipif(
    _gitleaks() is None, reason="gitleaks not installed; see docs/DEV_ENVIRONMENT.md §4 — "
    "this skip proves nothing about the gate"
)


@needs_gitleaks
def test_a_staged_secret_blocks_the_commit_and_is_never_printed(repo: Path) -> None:
    (repo / "leak.txt").write_text(f'token = "{SYNTHETIC}"\n')
    _git(repo, "add", "leak.txt")
    d = gate.run_gate(payload("git commit -m 'add config'", repo), gitleaks=_gitleaks())
    assert d.rule == "GITLEAKS-FINDING", d
    assert "github-pat" in d.reason and "leak.txt" in d.reason
    assert SYNTHETIC not in d.reason
    proc = run_gate_process("git commit -m 'add config'", repo)
    assert proc.returncode == 2
    assert b"github-pat" in proc.stderr and b"leak.txt" in proc.stderr
    assert SYNTHETIC.encode() not in proc.stderr + proc.stdout


@needs_gitleaks
def test_a_clean_stage_commits(repo: Path) -> None:
    (repo / "a.txt").write_text("clean\nmore\n")
    _git(repo, "add", "a.txt")
    d = gate.run_gate(payload("git commit -m 'more'", repo), gitleaks=_gitleaks())
    assert not d.denied, d
    assert run_gate_process("git commit -m 'more'", repo).returncode == 0


@needs_gitleaks
def test_commit_dash_a_scans_the_unstaged_working_tree_too(repo: Path) -> None:
    (repo / "a.txt").write_text(f"secret = {SYNTHETIC}\n")  # modified, NOT staged
    assert not gate.run_gate(payload("git commit -m x", repo), gitleaks=_gitleaks()).denied
    d = gate.run_gate(payload("git commit -am x", repo), gitleaks=_gitleaks())
    assert d.rule == "GITLEAKS-FINDING"
    d = gate.run_gate(payload("git commit -m x -- a.txt", repo), gitleaks=_gitleaks())
    assert d.rule == "GITLEAKS-FINDING"


@needs_gitleaks
def test_an_unpushed_commit_carrying_a_secret_blocks_the_push(repo: Path, tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    subprocess.check_call(["git", "init", "-q", "--bare", str(remote)])
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "HEAD")  # the clean history is published
    (repo / "leak.txt").write_text(f'token = "{SYNTHETIC}"\n')
    _git(repo, "add", "leak.txt")
    _git(repo, "commit", "-qm", "oops")  # committed directly, bypassing the hook
    d = gate.run_gate(payload("git push origin HEAD", repo), gitleaks=_gitleaks())
    assert d.rule == "GITLEAKS-FINDING", d
    assert "leak.txt" in d.reason and SYNTHETIC not in d.reason
    proc = run_gate_process("git push", repo)
    assert proc.returncode == 2 and SYNTHETIC.encode() not in proc.stderr + proc.stdout


@needs_gitleaks
def test_a_push_of_already_published_history_passes(repo: Path, tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    subprocess.check_call(["git", "init", "-q", "--bare", str(remote)])
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-q", "-u", "origin", "HEAD")
    assert not gate.run_gate(payload("git push", repo), gitleaks=_gitleaks()).denied


def test_the_gate_shares_the_guards_fail_closed_input_limits() -> None:
    assert gate.run_gate(b"x" * (gb.MAX_INPUT_BYTES + 1)).rule == "OVERSIZED-INPUT"
    long_cmd = json.dumps({"tool_name": "Bash",
                           "tool_input": {"command": "git commit " + "x" * gb.MAX_COMMAND_CHARS}})
    assert gate.run_gate(long_cmd.encode()).rule == "OVERSIZED-INPUT"
