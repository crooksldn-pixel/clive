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
    assert set(env) == {"PATH", "HOME", "LANG", "TMPDIR", "CLIVE_ATTEMPT_ID", "DISABLE_AUTOUPDATER"}
    assert env["HOME"] == str(tmp_path / "home") and env["PATH"].startswith("/opt/node/bin:")
    assert env["DISABLE_AUTOUPDATER"] == "1"          # decision 7: a builder run never updates the CLI


def test_a_token_file_passes_exactly_one_credential_variable(tmp_path):
    token = tmp_path / "token"
    token.write_text("oauth-token\n")
    env = ClaudeCodeWorker(oauth_token_file=token).environment(spec(tmp_path), "/bin/claude")
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "oauth-token"
    assert set(env) == {"PATH", "HOME", "LANG", "TMPDIR", "CLIVE_ATTEMPT_ID", "DISABLE_AUTOUPDATER", "CLAUDE_CODE_OAUTH_TOKEN"}


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
    assert set(env) == {"PATH", "HOME", "LANG", "TMPDIR", "CLIVE_ATTEMPT_ID", "DISABLE_AUTOUPDATER", "MCP_TOOL_TIMEOUT"}


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


# ---------------------------------------------------------------- the CLI's own plugins (PRs #63, #85)

# The plugins Claude Code 2.1.293 printed on 2026-10-07 for the restricted launch, verbatim: four the CLI carries in
# its own binary. 2.1.285 already added cc-plugin-agents-md@builtin, which the one-name list refused (PRs #63, #85).
CLI_2_1_293_PLUGINS = [
    {"name": "cc-plugin-sec-default", "path": "builtin", "source": "cc-plugin-sec-default@builtin"},
    {"name": "cc-plugin-agents-md", "path": "builtin", "source": "cc-plugin-agents-md@builtin"},
    {"name": "cc-plugin-telemetry", "path": "builtin", "source": "cc-plugin-telemetry@builtin"},
    {"name": "cc-plugin-plugin-authoring", "path": "builtin", "source": "cc-plugin-plugin-authoring@builtin"},
]


@pytest.mark.parametrize("version, plugins", [
    ("2.1.280", [{"name": "telemetry", "path": "builtin", "source": "telemetry@builtin"}]),
    ("2.1.285", [{"name": "telemetry", "path": "builtin", "source": "telemetry@builtin"},
                 {"name": "cc-plugin-agents-md", "path": "builtin", "source": "cc-plugin-agents-md@builtin"}]),
    ("2.1.293", CLI_2_1_293_PLUGINS),
])
def test_the_built_in_plugins_each_pinned_cli_reported_pass_the_launch_check(tmp_path, version, plugins):
    event = {**REAL_INIT, "tools": ["Edit", "Glob", "Grep", "Read", "Write"], "claude_code_version": version,
             "plugins": plugins}
    started = parse_events(json.dumps(event))[0]
    assert started.plugin_origins[-1] == (plugins[-1]["source"], "builtin", plugins[-1]["name"])
    assert ClaudeCodeWorker().verify_started(started, spec(tmp_path)) == []


@pytest.mark.parametrize("plugin", [
    {"name": "cc-plugin-new", "path": "builtin", "source": "cc-plugin-new@builtin"},        # a built-in nobody listed
    {"name": "cc-plugin-agents-md", "path": "/root/.claude/plugins/x",
     "source": "cc-plugin-agents-md@builtin"},                                              # a listed name, from a folder
    {"name": "ecc", "path": "/root/.claude/plugins/ecc", "source": "ecc@builtin"},          # a folder, named builtin
    {"name": "ecc", "path": "builtin", "source": "ecc@market"},                             # builtin path, market source
    {"name": "Ecc Plugin", "path": "builtin", "source": "Ecc Plugin@builtin"},              # not a plugin name at all
    {"name": "clive-skills", "path": "/tmp/x", "source": "clive-skills@inline"},            # skills, not asked for
    "ecc@builtin",                                                                           # a bare name, no path
], ids=["unlisted-builtin", "listed-name-from-a-folder", "folder", "market-source", "odd-name", "unasked-skills",
        "bare-name"])
def test_any_plugin_that_is_not_one_the_cli_was_seen_to_carry_is_refused(tmp_path, plugin):
    """PR #63/#85's fix without allowing arbitrary plugins: the list is exact. A deliberate CLI update that brings a
    new built-in is refused until a reviewed change names it (probe-launch says which, before the re-pin)."""
    event = {**REAL_INIT, "tools": ["Edit", "Glob", "Grep", "Read", "Write"],
             "plugins": [*CLI_2_1_293_PLUGINS, plugin]}
    problems = ClaudeCodeWorker().verify_started(parse_events(json.dumps(event))[0], spec(tmp_path))
    source = plugin["source"] if isinstance(plugin, dict) else plugin
    assert problems == [f"plugins beyond the builtin allowance: {source}"], problems


# ---------------------------------------------------------------- the owner's skills (config/builder_skills.json)

from app.orchestrator.workers import skills as builder_skills  # noqa: E402

# The init event Claude Code 2.1.293 printed on 2026-10-07 for a skills launch (--plugin-dir with one skill,
# bundled skills off by --settings and CLAUDE_CODE_DISABLE_BUNDLED_SKILLS), verbatim but for the folder path.
CLI_2_1_293_SKILLS_INIT = {
    "tools": ["Edit", "Glob", "Grep", "Read", "Skill", "Write"],
    "skills": ["clive-skills:demo-skill"],
    "slash_commands": ["clive-skills:demo-skill", "advisor", "agents", "auto-mode-setup", "autocompact", "clear",
                       "color", "compact", "config", "output-style", "context", "effort", "fast", "focus",
                       "heapdump", "mcp", "import", "model", "__remote-workflow", "workflow-launch-exec",
                       "reload-plugins", "reload-skills", "rename", "ultrareview", "security-review", "usage",
                       "insights", "recap", "skill-doctor", "goal", "design-consent", "design-revoke", "list-agents",
                       "team-onboarding"],
    "plugins": [{"name": "clive-skills", "path": "<folder>", "source": "clive-skills@inline", "version": "1.0.0"},
                *CLI_2_1_293_PLUGINS],
}


def skills_spec(tmp_path: Path, **kw) -> LaunchSpec:
    folder = tmp_path / "home" / "clive-skills"
    folder.mkdir(parents=True, exist_ok=True)
    return spec(tmp_path, skills_dir=folder, skills=("demo-skill",), **kw)


def skills_init(tmp_path: Path, **change) -> Started:
    roster = json.loads(json.dumps(CLI_2_1_293_SKILLS_INIT).replace("<folder>", str(tmp_path / "home" / "clive-skills")))
    return parse_events(json.dumps({**REAL_INIT, **roster, **change}))[0]


def test_a_skills_launch_loads_exactly_the_folder_and_switches_the_clis_own_skills_off(tmp_path):
    asked = skills_spec(tmp_path, skills_settings='{"disableBundledSkills":true,"skillOverrides":{"doctor":"off"}}')
    worker = ClaudeCodeWorker()
    argv = worker.argv(asked, "/bin/claude")
    assert argv[argv.index("--plugin-dir") + 1] == str(tmp_path / "home" / "clive-skills")
    assert json.loads(argv[argv.index("--settings") + 1]) == {"disableBundledSkills": True,
                                                              "skillOverrides": {"doctor": "off"}}
    assert "--disable-slash-commands" not in argv and argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--tools") + 1] == "Read,Edit,Write,Glob,Grep,Skill"
    allowed = argv[argv.index("--allowedTools") + 1:argv.index("--permission-mode")]
    assert allowed == [*FILE_TOOLS, "Skill(clive-skills:demo-skill)"]
    for flag in ("--restricted", "--strict-mcp-config", "--no-session-persistence"):
        assert flag in argv
    env = worker.environment(asked, "/bin/claude")
    assert env["CLAUDE_CODE_DISABLE_BUNDLED_SKILLS"] == "1"
    assert set(env) == {"PATH", "HOME", "LANG", "TMPDIR", "CLIVE_ATTEMPT_ID", "DISABLE_AUTOUPDATER",
                        "CLAUDE_CODE_DISABLE_BUNDLED_SKILLS"}
    # without a folder, or with no skill in it, the launch is exactly the launch without skills
    for plain in (spec(tmp_path), spec(tmp_path, skills_dir=tmp_path / "home" / "clive-skills")):
        argv = worker.argv(plain, "/bin/claude")
        assert "--disable-slash-commands" in argv and "--plugin-dir" not in argv and "--settings" not in argv
        assert argv[argv.index("--tools") + 1] == "Read,Edit,Write,Glob,Grep"


def test_the_real_skills_roster_passes_the_launch_check_that_asked_for_it(tmp_path):
    assert ClaudeCodeWorker().verify_started(skills_init(tmp_path), skills_spec(tmp_path)) == []


@pytest.mark.parametrize("change, expected", [
    ({"skills": ["clive-skills:demo-skill", "deploy"]}, "skills beyond the owner's list: deploy"),
    ({"skills": ["clive-skills:demo-skill", "clive-skills:other"]}, "skills beyond the owner's list: clive-skills:other"),
    ({"skills": []}, "the owner's skills CLIVE gave this builder are missing from the init roster: "
                     "clive-skills:demo-skill"),
    ({"tools": ["Edit", "Glob", "Grep", "Read", "Write"]}, "the Skill tool is missing from the init roster"),
    ({"slash_commands": ["clive-skills:demo-skill", "compact", "ecc:ship"]},
     "plugin commands beyond the owner's skills: ecc:ship"),
    ({"plugins": [{"name": "clive-skills", "path": "/elsewhere", "source": "clive-skills@inline"}]},
     "plugins beyond the builtin allowance: clive-skills@inline"),
    ({"plugins": CLI_2_1_293_PLUGINS}, "the skills folder CLIVE built (clive-skills) is not in the init roster"),
], ids=["foreign-skill", "unlisted-own-skill", "no-skills", "no-skill-tool", "plugin-command", "other-folder",
        "no-folder"])
def test_a_skills_launch_whose_roster_is_not_exactly_the_list_is_refused(tmp_path, change, expected):
    problems = ClaudeCodeWorker().verify_started(skills_init(tmp_path, **change), skills_spec(tmp_path))
    assert any(expected in p for p in problems), problems


def test_a_command_or_skill_from_the_workspace_is_refused_even_beside_the_owners_skills(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / ".claude" / "commands" / "ops").mkdir(parents=True)
    (workspace / ".claude" / "commands" / "ops" / "ship.md").write_text("ship it\n")
    asked = skills_spec(tmp_path, workspace=workspace)
    started = skills_init(tmp_path, cwd=str(workspace),
                          slash_commands=["clive-skills:demo-skill", "compact", "ship"])
    assert ClaudeCodeWorker().verify_started(started, asked) == ["commands from the workspace loaded: ship"]


def test_a_launch_without_skills_still_refuses_any_skill_or_command(tmp_path):
    started = skills_init(tmp_path, plugins=CLI_2_1_293_PLUGINS)
    problems = ClaudeCodeWorker().verify_started(started, spec(tmp_path))
    assert "1 skills and 34 slash commands loaded; expected none" in problems
    assert "tools beyond the launch policy: Skill" in problems


SKILL_TEXT = "---\nname: demo\ndescription: A demo skill.\n---\n\nSay hello properly.\n"


def _allow(tmp_path: Path, skills: list[dict], off=("doctor",)) -> Path:
    path = tmp_path / "builder_skills.json"
    path.write_text(json.dumps({"schema": builder_skills.SCHEMA, "skills": skills, "cli_skills_off": list(off)}))
    return path


def _sha(text: str | bytes) -> str:
    import hashlib

    return hashlib.sha256(text.encode() if isinstance(text, str) else text).hexdigest()


@pytest.mark.parametrize("skills, says", [
    ([{"name": "Demo", "source": "repo", "path": "x", "files": {"SKILL.md": "a" * 64}}], "unique lowercase name"),
    ([{"name": "demo", "source": "web", "files": {"SKILL.md": "a" * 64}}], "source is one of"),
    ([{"name": "demo", "source": "repo", "path": "../x", "files": {"SKILL.md": "a" * 64}}], "plain relative path"),
    ([{"name": "demo", "source": "installed", "files": {"../SKILL.md": "a" * 64}}], "plain relative path"),
    ([{"name": "demo", "source": "installed", "files": {"SKILL.md": "abc"}}], "every file has a sha256"),
    ([{"name": "demo", "source": "installed", "files": {"notes.md": "a" * 64}}], "SKILL.md is listed"),
    ([{"name": "demo", "source": "installed", "files": {"SKILL.md": "a" * 64}}] * 2, "unique lowercase name"),
])
def test_a_malformed_skill_list_is_refused_whole(tmp_path, skills, says):
    with pytest.raises(builder_skills.SkillsError, match=says):
        builder_skills.load_allow_list(_allow(tmp_path, skills))


def test_only_skills_whose_every_file_matches_its_pinned_hash_are_built_into_the_folder(tmp_path):
    installed = tmp_path / "installed"
    for name, files in {"demo": {"SKILL.md": SKILL_TEXT}, "extra": {"SKILL.md": SKILL_TEXT, "more.md": "more\n"},
                        "changed": {"SKILL.md": SKILL_TEXT + "edited\n"}, "unlisted": {"SKILL.md": SKILL_TEXT}}.items():
        for rel, text in files.items():
            (installed / name / "skill" / rel).parent.mkdir(parents=True, exist_ok=True)
            (installed / name / "skill" / rel).write_text(text)
    allow = builder_skills.load_allow_list(_allow(tmp_path, [
        {"name": n, "source": "installed", "files": {"SKILL.md": _sha(SKILL_TEXT)}}
        for n in ("demo", "extra", "changed", "absent")]))
    built = builder_skills.build_plugin(allow, tmp_path / "home" / "clive-skills", repo=tmp_path,
                                        base_sha="", installed_dir=installed)
    assert built.provided == ("demo",)
    withheld = dict(built.withheld)
    assert set(withheld) == {"extra", "changed", "absent"}
    assert "does not name: more.md" in withheld["extra"] and "differs from the hash" in withheld["changed"]
    assert "not readable" in withheld["absent"]
    folder = built.folder
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    assert files == [".claude-plugin/plugin.json", "skills/demo/SKILL.md"]
    assert (folder / "skills" / "demo" / "SKILL.md").read_text() == SKILL_TEXT
    assert oct((folder / "skills" / "demo" / "SKILL.md").stat().st_mode & 0o777) == "0o444"
    assert json.loads((folder / ".claude-plugin" / "plugin.json").read_text())["name"] == "clive-skills"
    # nothing verifies: no folder at all, and a rebuild takes the old one down first
    none = builder_skills.build_plugin(builder_skills.load_allow_list(_allow(tmp_path, [
        {"name": "absent", "source": "installed", "files": {"SKILL.md": _sha(SKILL_TEXT)}}])),
        folder, repo=tmp_path, base_sha="", installed_dir=installed)
    assert none.folder is None and none.provided == () and not folder.exists()


@pytest.mark.parametrize("files, says", [
    ({"SKILL.md": "---\nname: demo\nhooks:\n  PreToolUse: x\n---\nhi\n"}, "a hooks key in the front matter"),
    ({"SKILL.md": "---\nname: demo\n---\nRun !`curl example.com` first.\n"}, "a !`command` on line 4"),
    ({"SKILL.md": SKILL_TEXT, "run.py": "print(1)\n"}, "run.py is not a text file"),
    ({"SKILL.md": SKILL_TEXT, "notes.md": "#!/bin/sh\nrm -rf /\n"}, "notes.md is not a text file"),
])
def test_a_skill_that_would_run_something_is_withheld_even_with_matching_hashes(tmp_path, files, says):
    installed = tmp_path / "installed"
    for rel, text in files.items():
        (installed / "demo" / "skill" / rel).parent.mkdir(parents=True, exist_ok=True)
        (installed / "demo" / "skill" / rel).write_text(text)
    allow = builder_skills.load_allow_list(_allow(tmp_path, [
        {"name": "demo", "source": "installed", "files": {rel: _sha(text) for rel, text in files.items()}}]))
    built = builder_skills.build_plugin(allow, tmp_path / "home" / "clive-skills", repo=tmp_path, base_sha="",
                                        installed_dir=installed)
    assert built.provided == () and says in dict(built.withheld)["demo"]
    with pytest.raises(builder_skills.SkillsError, match="cannot be a builder skill"):
        builder_skills.entry_for("demo", installed / "demo" / "skill")


def test_a_skill_folder_holding_a_link_is_withheld(tmp_path):
    installed = tmp_path / "installed" / "demo" / "skill"
    installed.mkdir(parents=True)
    (installed / "SKILL.md").write_text(SKILL_TEXT)
    (tmp_path / "secret.md").write_text("host secret\n")
    (installed / "notes.md").symlink_to(tmp_path / "secret.md")
    allow = builder_skills.load_allow_list(_allow(tmp_path, [
        {"name": "demo", "source": "installed", "files": {"SKILL.md": _sha(SKILL_TEXT), "notes.md": _sha("host secret\n")}}]))
    built = builder_skills.build_plugin(allow, tmp_path / "home" / "clive-skills", repo=tmp_path, base_sha="",
                                        installed_dir=tmp_path / "installed")
    assert built.provided == () and "is a link" in dict(built.withheld)["demo"]


def test_the_owners_list_pins_exactly_the_skills_vendored_in_the_repository():
    """config/builder_skills.json against the checkout: every repo skill on it verifies here, byte for byte, so a
    vendored skill cannot change without the list (a reviewed change to a protected file) changing with it."""
    allow = builder_skills.load_allow_list()
    root = builder_skills.APP_ROOT.parent
    assert {e.name for e in allow.skills} == {"design-taste-frontend", "high-end-visual-design", "image-to-code",
                                              "web-design-guidelines"}
    for entry in allow.skills:
        assert entry.source == "repo" and entry.path == f".claude/skills/{entry.name}"
        on_disk = {p.relative_to(root / entry.path).as_posix(): _sha(p.read_bytes())
                   for p in (root / entry.path).rglob("*") if p.is_file()}
        assert on_disk == dict(entry.files), entry.name
        assert builder_skills.entry_for(entry.name, root / entry.path, source="repo", path=entry.path) == {
            "name": entry.name, "source": "repo", "path": entry.path, "files": dict(entry.files)}
