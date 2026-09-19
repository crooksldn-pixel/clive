"""The launch-time roster assertion, against fake system/init messages.

Reference implementation only (docs/dev-environment/WORKER_TOOL_SURFACE_ISOLATION.md). The
shape of the real init message must still be confirmed empirically; what these tests prove is
that, given the documented shape, the assertion fails closed on every kind of unexpected tool
and on every kind of missing evidence.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import roster_assert as ra  # noqa: E402

CLEAN = {
    "type": "system", "subtype": "init", "cwd": "/opt/crooks-builder", "session_id": "x",
    "tools": ["Read", "Edit", "Write", "Glob", "Grep", "Bash"],
    "mcp_servers": [], "slash_commands": ["init", "review"], "model": "claude-fable-5-1",
    "permissionMode": "acceptEdits",
}


def test_a_clean_engineering_roster_passes() -> None:
    r = ra.assert_roster(CLEAN)
    assert r.ok and r.violations == []
    assert r.tools == sorted(CLEAN["tools"])
    assert len(r.digest) == 64


def test_any_mcp_tool_is_a_violation() -> None:
    msg = dict(CLEAN, tools=[*CLEAN["tools"], "mcp__claude_ai_Gmail__send_message"])
    r = ra.assert_roster(msg)
    assert not r.ok
    assert r.violations == ["MCP tool present: mcp__claude_ai_Gmail__send_message"]


def test_a_configured_mcp_server_is_a_violation_even_with_no_tools_listed() -> None:
    msg = dict(CLEAN, mcp_servers=[{"name": "claude_ai_Shopify", "status": "connected"}])
    r = ra.assert_roster(msg)
    assert r.violations == ["MCP server configured: claude_ai_Shopify"]


def test_plugin_namespaced_commands_are_violations() -> None:
    msg = dict(CLEAN, slash_commands=["init", "design:accessibility-review", "marketing:seo-audit"])
    r = ra.assert_roster(msg)
    assert r.violations == ["plugin command present: design:accessibility-review",
                            "plugin command present: marketing:seo-audit"]
    assert ra.assert_roster(msg, allowed_plugin_prefixes=frozenset({"design", "marketing"})).ok


def test_disallowed_builtins_and_unknown_tools_are_named() -> None:
    msg = dict(CLEAN, tools=[*CLEAN["tools"], "WebFetch", "Agent", "SomethingNew"])
    r = ra.assert_roster(msg)
    assert "disallowed built-in tool present: Agent" in r.violations
    assert "disallowed built-in tool present: WebFetch" in r.violations
    assert "tool outside the engineering allow-list: SomethingNew" in r.violations


def test_missing_evidence_fails_closed() -> None:
    assert not ra.assert_roster(None).ok
    assert not ra.assert_roster("init").ok
    assert not ra.assert_roster({}).ok
    no_tools = {k: v for k, v in CLEAN.items() if k != "tools"}
    r = ra.assert_roster(no_tools)
    assert any("cannot prove the roster" in v for v in r.violations)
    assert not ra.assert_roster(dict(CLEAN, tools="Read,Edit")).ok
    assert not ra.assert_roster(dict(CLEAN, tools=["Read", 7])).ok
    assert not ra.assert_roster(dict(CLEAN, mcp_servers="none")).ok
    assert not ra.assert_roster(dict(CLEAN, type="assistant")).ok


def test_permission_mode_is_part_of_the_assertion() -> None:
    assert not ra.assert_roster(dict(CLEAN, permissionMode="bypassPermissions")).ok
    assert ra.assert_roster(dict(CLEAN, permissionMode="bypassPermissions"),
                            require_permission_mode=None).ok


def test_the_digest_is_deterministic_and_order_independent() -> None:
    a = ra.assert_roster(CLEAN).digest
    b = ra.assert_roster(dict(CLEAN, tools=list(reversed(CLEAN["tools"])))).digest
    c = ra.assert_roster(dict(CLEAN, tools=[*CLEAN["tools"], "WebFetch"])).digest
    assert a == b != c


def test_the_script_exit_code_is_the_verdict() -> None:
    script = SCRIPTS / "roster_assert.py"
    ok = subprocess.run([sys.executable, str(script)], input=json.dumps(CLEAN).encode(),
                        capture_output=True, check=False)
    assert ok.returncode == 0 and ok.stdout.startswith(b"roster OK")
    bad = dict(CLEAN, tools=[*CLEAN["tools"], "mcp__claude_ai_Resend__send_email"])
    fail = subprocess.run([sys.executable, str(script)], input=json.dumps(bad).encode(),
                          capture_output=True, check=False)
    assert fail.returncode == 3 and b"VIOLATION" in fail.stdout
    assert b"send_email" in fail.stdout  # a tool NAME is not a secret; naming it is the point
    garbage = subprocess.run([sys.executable, str(script)], input=b"{", capture_output=True,
                             check=False)
    assert garbage.returncode == 3
