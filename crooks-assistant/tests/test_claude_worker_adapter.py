"""The Claude Code builder driver: what it launches, what it passes on, how it reads the stream."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.orchestrator.workers import check_server
from app.orchestrator.workers.base import LaunchSpec, Started
from app.orchestrator.workers.claude import FILE_TOOLS, ClaudeCodeWorker, _finished, parse_events

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


# ---------------------------------------------------------------- run_checks: exactly one server, one tool

CHECK_TOOL = "mcp__clive_checks__run_checks"


def test_without_declared_checks_the_launch_has_no_server_and_no_extra_tool(tmp_path):
    worker = ClaudeCodeWorker()
    argv = worker.argv(spec(tmp_path), "/bin/claude")
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert CHECK_TOOL not in argv
    assert "MCP_TOOL_TIMEOUT" not in worker.environment(spec(tmp_path), "/bin/claude")


def test_the_worker_launch_allows_exactly_the_file_tools_plus_run_checks(tmp_path):
    config = tmp_path / "runtime" / "config.json"
    worker = ClaudeCodeWorker(check_python="/venv/bin/python")
    argv = worker.argv(spec(tmp_path, check_config=config), "/bin/claude")
    assert argv[argv.index("--tools") + 1] == "Read,Edit,Write,Glob,Grep"  # the built-ins are unchanged
    start = argv.index("--allowedTools") + 1
    allowed = argv[start:argv.index("--permission-mode")]
    assert allowed == [*FILE_TOOLS, CHECK_TOOL] and CHECK_TOOL == check_server.QUALIFIED_TOOL
    assert "Bash" not in " ".join(argv)
    servers = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]
    assert servers == {"clive_checks": {"type": "stdio", "command": "/venv/bin/python",
                                        "args": ["-I", str(Path(check_server.__file__).resolve()), str(config)],
                                        "env": {}}}
    assert "--strict-mcp-config" in argv
    env = worker.environment(spec(tmp_path, check_config=config), "/bin/claude")
    assert set(env) == {"PATH", "HOME", "LANG", "TMPDIR", "CLIVE_ATTEMPT_ID", "MCP_TOOL_TIMEOUT"}


def test_the_launch_check_accepts_the_check_server_only_when_the_launch_asked_for_it(tmp_path):
    event = {**REAL_INIT, "tools": ["Read", "Edit", "Write", "Glob", "Grep", "StructuredOutput", CHECK_TOOL],
             "mcp_servers": [{"name": "clive_checks", "status": "connected"}]}
    started = parse_events(json.dumps(event))[0]
    asked = spec(tmp_path, check_config=tmp_path / "config.json")
    assert ClaudeCodeWorker().verify_started(started, asked) == []
    problems = ClaudeCodeWorker().verify_started(started, spec(tmp_path))
    assert any("MCP servers present: clive_checks" in p for p in problems)
    assert any(CHECK_TOOL in p for p in problems)


@pytest.mark.parametrize("change, expected", [
    ({"mcp_servers": [{"name": "clive_checks", "status": "connected"}, {"name": "claude.ai Gmail"}]},
     "MCP servers present: claude.ai Gmail"),
    ({"tools": ["Read", CHECK_TOOL, "mcp__clive_checks__shell"]}, "mcp__clive_checks__shell"),
    ({"tools": ["Read", CHECK_TOOL, "Bash"]}, "Bash"),
    ({"mcp_servers": [{"name": "clive-checks"}]}, "MCP servers present: clive-checks"),
])
def test_with_the_check_server_any_further_widening_is_still_refused(tmp_path, change, expected):
    event = {**REAL_INIT, "tools": ["Read", "Edit", "Write", "Glob", "Grep", "StructuredOutput", CHECK_TOOL],
             "mcp_servers": [{"name": "clive_checks", "status": "connected"}], **change}
    problems = ClaudeCodeWorker().verify_started(parse_events(json.dumps(event))[0],
                                                 spec(tmp_path, check_config=tmp_path / "config.json"))
    assert any(expected in p for p in problems), problems


# The init event Claude Code 2.1.285 printed on 2026-09-30 for a launch with the clive_checks server (the
# roster's tool and server fields verbatim; its plugins and other fields are REAL_INIT's).
REAL_CHECKS_ROSTER = {"tools": ["Read", "mcp__clive_checks__run_checks"],
                      "mcp_servers": [{"name": "clive_checks", "status": "connected", "source": "dynamic"}]}


def test_the_real_check_server_roster_passes_the_launch_check_that_asked_for_it(tmp_path):
    started = parse_events(json.dumps({**REAL_INIT, **REAL_CHECKS_ROSTER}))[0]
    assert started.mcp_server_status == (("clive_checks", "connected"),)
    assert ClaudeCodeWorker().verify_started(started, spec(tmp_path, check_config=tmp_path / "config.json")) == []


@pytest.mark.parametrize("change, expected", [
    ({"tools": ["Read", "Edit", "Write", "Glob", "Grep", "StructuredOutput"]},
     f"the declared checks' tool {CHECK_TOOL} is missing from the init roster"),
    ({"mcp_servers": []}, "the declared checks' MCP server clive_checks is not in the init roster"),
    ({"mcp_servers": [{"name": "clive_checks", "status": "failed"}]},
     "the declared checks' MCP server clive_checks is not connected (status failed)"),
    ({"mcp_servers": [{"name": "clive_checks", "status": "pending"}]},
     "the declared checks' MCP server clive_checks is not connected (status pending)"),
    ({"mcp_servers": [{"name": "clive_checks"}]},
     "the declared checks' MCP server clive_checks is not connected (status not reported)"),
    ({"mcp_servers": ["clive_checks"]},
     "the declared checks' MCP server clive_checks is not connected (status not reported)"),
], ids=["no-tool", "no-server", "server-failed", "server-pending", "no-status", "bare-name"])
def test_a_launch_with_declared_checks_requires_run_checks_and_its_connected_server(tmp_path, change, expected):
    """The 2026-09-30 re-pin review, second run, F-01: asked for, the tool and the server are required, not only
    allowed. Without declared checks neither is required (the launch asked for neither)."""
    event = {**REAL_INIT, "tools": ["Read", "Edit", "Write", "Glob", "Grep", "StructuredOutput", CHECK_TOOL],
             "mcp_servers": [{"name": "clive_checks", "status": "connected"}], **change}
    started = parse_events(json.dumps(event))[0]
    problems = ClaudeCodeWorker().verify_started(started, spec(tmp_path, check_config=tmp_path / "config.json"))
    assert expected in problems, problems
    assert problems == [expected]


def test_without_declared_checks_nothing_of_the_check_server_is_required(tmp_path):
    event = {**REAL_INIT, "tools": ["Read", "Edit", "Write", "Glob", "Grep", "StructuredOutput"]}
    assert ClaudeCodeWorker().verify_started(parse_events(json.dumps(event))[0], spec(tmp_path)) == []


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
