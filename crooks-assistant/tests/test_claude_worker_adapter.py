"""The Claude Code builder driver: what it launches, what it passes on, how it reads the stream."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.orchestrator.workers.base import LaunchSpec, Started
from app.orchestrator.workers.claude import ClaudeCodeWorker, _finished, parse_events

# A real init event, as Claude Code 2.1.280 printed it on 2026-09-23 for the restricted launch
# (cwd and session shortened; every roster field verbatim).
REAL_INIT = {
    "type": "system", "subtype": "init", "cwd": "/w", "session_id": "cdf1d29b-6bab-4d69-a260-b958e06d3745",
    "tools": ["Bash", "Edit", "Glob", "Grep", "Read", "StructuredOutput", "Write"], "mcp_servers": [],
    "model": "claude-haiku-4-5-20251001", "permissionMode": "dontAsk", "slash_commands": [], "apiKeySource": "none",
    "claude_code_version": "2.1.280", "output_style": "default", "agents": ["claude"], "skills": [],
    "plugins": [{"name": "telemetry", "path": "builtin", "source": "telemetry@builtin"}],
}


def spec(tmp_path: Path, **kw) -> LaunchSpec:
    fields = dict(task_id="t", task_revision=1, attempt_id="t-a1", fencing_token=1,
                  session_id="cdf1d29b-6bab-4d69-a260-b958e06d3745", workspace=Path("/w"), home=tmp_path / "home",
                  log_path=tmp_path / "log", stderr_path=tmp_path / "err", prompt="do it")
    fields.update(kw)
    return LaunchSpec(**fields)


def test_the_launch_cuts_the_surface_by_flags_not_by_prompt(tmp_path):
    argv = ClaudeCodeWorker(model="sonnet").argv(spec(tmp_path), "/bin/claude")
    joined = " ".join(argv)
    for flag in ("--restricted", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence"):
        assert flag in argv
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--permission-mode") + 1] == "dontAsk"
    assert argv[argv.index("--session-id") + 1] == "cdf1d29b-6bab-4d69-a260-b958e06d3745"
    assert argv[argv.index("--tools") + 1] == "Read,Edit,Write,Glob,Grep"  # no Bash by default
    assert "Bash" not in joined and "--dangerously-skip-permissions" not in joined
    assert json.loads(argv[argv.index("--json-schema") + 1])["required"] == ["status", "summary"]


def test_bash_exists_only_with_explicit_prefixes(tmp_path):
    worker = ClaudeCodeWorker(bash_prefixes=("python -m pytest",))
    argv = worker.argv(spec(tmp_path), "/bin/claude")
    assert argv[argv.index("--tools") + 1].endswith(",Bash")
    assert "Bash(python -m pytest:*)" in argv


def test_the_environment_is_built_not_inherited(tmp_path, monkeypatch):
    for name in ("GH_TOKEN", "GITHUB_TOKEN", "ANTHROPIC_API_KEY", "SHOPIFY_TOKEN", "GMAIL_OAUTH", "HTTPS_PROXY"):
        monkeypatch.setenv(name, "secret")
    env = ClaudeCodeWorker().environment(spec(tmp_path), "/opt/node/bin/claude")
    assert set(env) == {"PATH", "HOME", "LANG", "TMPDIR", "CLIVE_ATTEMPT_ID"}
    assert env["HOME"] == str(tmp_path / "home") and env["PATH"].startswith("/opt/node/bin:")


def test_a_token_file_passes_exactly_one_credential_variable(tmp_path):
    token = tmp_path / "token"
    token.write_text("oauth-token\n")
    env = ClaudeCodeWorker(oauth_token_file=token).environment(spec(tmp_path), "/bin/claude")
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-token"
    assert set(env) == {"PATH", "HOME", "LANG", "TMPDIR", "CLIVE_ATTEMPT_ID", "CLAUDE_CODE_OAUTH_TOKEN"}


def test_the_real_restricted_init_event_passes_the_launch_check_only_with_bash_allowed(tmp_path):
    started = parse_events(json.dumps(REAL_INIT))[0]
    assert isinstance(started, Started) and started.mcp_servers == () and started.plugins == ("telemetry@builtin",)
    assert ClaudeCodeWorker(bash_prefixes=("git status",)).verify_started(started, spec(tmp_path)) == []
    problems = ClaudeCodeWorker().verify_started(started, spec(tmp_path))
    assert problems == ["tools beyond the launch policy: Bash"]


@pytest.mark.parametrize("change, expected", [
    ({"mcp_servers": [{"name": "claude.ai Gmail", "status": "connected"}]}, "MCP servers present: claude.ai Gmail"),
    ({"tools": ["Read", "mcp__Shopify__graphql_mutation"]}, "mcp__Shopify__graphql_mutation"),
    ({"plugins": [{"name": "ecc", "path": "/root/.claude/plugins/ecc", "source": "ecc@market"}]}, "ecc@market"),
    ({"skills": ["deploy"]}, "1 skills"),
    ({"session_id": "other"}, "not the assigned session"),
    ({"cwd": "/opt/crooks-os"}, "not the attempt workspace"),
    ({"permissionMode": "bypassPermissions"}, "permission mode"),
])
def test_any_widening_of_the_observed_surface_is_refused(tmp_path, change, expected):
    event = {**REAL_INIT, "tools": ["Read", "Edit", "Write", "Glob", "Grep", "StructuredOutput"], **change}
    problems = ClaudeCodeWorker().verify_started(parse_events(json.dumps(event))[0], spec(tmp_path))
    assert any(expected in p for p in problems), problems


def test_edits_are_named_only_when_the_tool_result_succeeded():
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "a", "name": "Edit",
                                                        "input": {"file_path": "/w/x.py"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "a"}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "b", "name": "Write",
                                                        "input": {"file_path": "/w/y.py"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "b", "is_error": True}]}},
        {"type": "system", "subtype": "permission_denied"},
        {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}},
    ]
    obs = parse_events("\n".join(json.dumps(line) for line in lines) + "\nnot json\n")
    assert [o.edited for o in obs if getattr(o, "edited", None)] == ["/w/x.py"]
    assert sum(o.denied for o in obs if hasattr(o, "denied")) == 1
    assert not any(getattr(o, "rate_limited", False) for o in obs)


@pytest.mark.parametrize("event, status, error_class", [
    ({"subtype": "success", "structured_output": {"status": "completed", "summary": "s"}}, "completed", "none"),
    ({"subtype": "success", "structured_output": {"status": "owner_decision_required", "summary": "s"}},
     "owner_decision_required", "none"),
    ({"subtype": "success", "result": "I am done!"}, "error", "deterministic"),  # prose is not a report
    ({"subtype": "error_max_turns", "is_error": True}, "error", "deterministic"),
    ({"subtype": "error_during_execution", "is_error": True, "api_error_status": 401}, "error", "deterministic"),
    ({"subtype": "error_during_execution", "is_error": True, "api_error_status": 529}, "error", "transient"),
    ({"subtype": "error_during_execution", "is_error": True, "api_error_status": 429}, "error", "transient"),
])
def test_results_are_classified_from_structure_not_prose(event, status, error_class):
    fin = _finished({"type": "result", "is_error": False, **event})
    assert (fin.status, fin.error_class) == (status, error_class)


def test_an_auth_failure_on_stderr_is_deterministic(tmp_path):
    err = tmp_path / "err"
    err.write_text("Invalid API key · Please run /login\n")
    reason, transient = ClaudeCodeWorker().diagnose_exit(err)
    assert not transient and "authentication" in reason
    err.write_text("Killed\n")
    assert ClaudeCodeWorker().diagnose_exit(err)[1] is True
