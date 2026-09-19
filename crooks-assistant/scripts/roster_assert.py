#!/usr/bin/env python3
"""roster_assert — fail closed on the tool roster a headless Claude session actually has.

PROPOSAL / REFERENCE IMPLEMENTATION. Nothing runs this yet. It is the deterministic half of the
worker tool-surface isolation design in docs/dev-environment/WORKER_TOOL_SURFACE_ISOLATION.md:
the watcher would launch Claude with `--output-format stream-json`, read the first
`{"type": "system", "subtype": "init", ...}` message, and pass it here. Any `mcp__*` tool, any
MCP server, any plugin-namespaced slash command, any agent/skill/plugin surface, any tool
outside the engineering allow-list — and any list- or object-valued key this module does not
know — is a violation, and a violation aborts the run.

It is a kill switch, not the gate. The init message is emitted after the session and its
tools exist; a watcher that acts on it terminates a violating session milliseconds later, not
before. The gate is the launch configuration (flags, identity). This assertion is the backstop
that turns "the launch was configured correctly" into a checked statement.

Why: the ECC audit (bridge round 2026-09-19) proved the current launch inherits the owner's
claude.ai business connectors (Gmail, Shopify, Google Drive, Resend, Omnisend, …) and
account-synced plugins. Prompt text cannot remove them; only the launch can, and only a check
of the observed roster can prove that it did.

What is documented vs assumed about the init message is in the design doc. This module treats
every field defensively: a missing or mis-typed `tools` is a violation, not a pass, and an
undocumented surface is UNKNOWN, which also fails (D-18).
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass, field

ENGINEERING_TOOLS = frozenset({"Read", "Edit", "Write", "Glob", "Grep", "Bash"})
# Built-in tools a bridge run has no contract to use. Present in the roster today; listed so
# the assertion names them explicitly rather than relying on "not in the allow-list".
DISALLOWED_BUILTINS = frozenset(
    {"WebFetch", "WebSearch", "Agent", "Workflow", "CronCreate", "CronDelete", "CronList",
     "RemoteTrigger", "SendMessage", "PushNotification", "NotebookEdit", "EnterWorktree",
     "ExitWorktree", "ToolSearch", "Skill"}
)
# Keys of the init message this module understands. Scalars among them are read or ignored;
# the surfaces are checked. Any key outside this set whose value is a list or an object is an
# undocumented tool surface: UNKNOWN, and UNKNOWN fails.
DOCUMENTED_SCALAR_KEYS = frozenset(
    {"type", "subtype", "cwd", "session_id", "model", "permissionMode", "apiKeySource",
     "claude_code_version", "output_style", "uuid"}
)
DOCUMENTED_SURFACES = ("tools", "mcp_servers", "slash_commands", "agents", "skills", "plugins")


@dataclass
class RosterReport:
    ok: bool
    violations: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    plugin_commands: list[str] = field(default_factory=list)
    surfaces: dict[str, list[str]] = field(default_factory=dict)  # every list-valued surface seen
    unknown_keys: list[str] = field(default_factory=list)  # scalar keys not documented here
    digest: str = ""

    def summary(self) -> str:
        head = "roster OK" if self.ok else f"roster VIOLATION ({len(self.violations)})"
        return f"{head}; tools={len(self.tools)} mcp_servers={len(self.mcp_servers)} " \
               f"plugin_commands={len(self.plugin_commands)} digest={self.digest[:16]}"


def _names(raw: object) -> list[str]:
    out: list[str] = []
    for item in raw if isinstance(raw, list) else []:
        name = item.get("name") if isinstance(item, dict) else item
        out.append(str(name))
    return out


def assert_roster(
    init_message: object,
    *,
    allowed_tools: frozenset[str] = ENGINEERING_TOOLS,
    allowed_mcp_servers: frozenset[str] = frozenset(),
    allowed_plugin_prefixes: frozenset[str] = frozenset(),
    allowed_agents: frozenset[str] = frozenset(),
    allowed_skills: frozenset[str] = frozenset(),
    require_permission_mode: str | None = "acceptEdits",
) -> RosterReport:
    """Decide whether the session described by `init_message` may proceed. Pure."""
    violations: list[str] = []
    if not isinstance(init_message, dict):
        return RosterReport(False, ["init message is not an object"], digest=_digest({}))
    if init_message.get("type") != "system" or init_message.get("subtype") != "init":
        violations.append("message is not system/init")

    raw_tools = init_message.get("tools")
    tools: list[str] = []
    if not isinstance(raw_tools, list):
        violations.append("`tools` missing or not a list — cannot prove the roster")
    else:
        for t in raw_tools:
            if not isinstance(t, str):
                violations.append("a tool entry is not a string")
                continue
            tools.append(t)
    for t in sorted(set(tools)):
        if t.startswith("mcp__"):
            violations.append(f"MCP tool present: {t}")
        elif t in DISALLOWED_BUILTINS:
            violations.append(f"disallowed built-in tool present: {t}")
        elif t not in allowed_tools:
            violations.append(f"tool outside the engineering allow-list: {t}")

    raw_servers = init_message.get("mcp_servers", [])
    servers: list[str] = []
    if raw_servers is None:
        raw_servers = []
    if not isinstance(raw_servers, list):
        violations.append("`mcp_servers` is not a list")
    else:
        servers = _names(raw_servers)
        for name in servers:
            if name not in allowed_mcp_servers:
                violations.append(f"MCP server configured: {name}")

    raw_cmds = init_message.get("slash_commands", [])
    plugin_cmds: list[str] = []
    commands: list[str] = []
    if raw_cmds is None:
        raw_cmds = []
    if not isinstance(raw_cmds, list):
        violations.append("`slash_commands` is not a list")
    else:
        for c in raw_cmds:
            if not isinstance(c, str):
                violations.append("a slash_commands entry is not a string")
                continue
            commands.append(c)
            if ":" in c:  # plugin-namespaced, e.g. design:accessibility-review
                prefix = c.split(":", 1)[0]
                plugin_cmds.append(c)
                if prefix not in allowed_plugin_prefixes:
                    violations.append(f"plugin command present: {c}")

    # Further documented surfaces (D-18): agents, skills and plugins are tool surface too. Each
    # must be absent or empty unless explicitly allowed; a mis-typed value is a violation.
    surfaces: dict[str, list[str]] = {"tools": sorted(tools), "mcp_servers": sorted(servers),
                                      "slash_commands": sorted(commands)}
    extra_allow = {"agents": allowed_agents, "skills": allowed_skills,
                   "plugins": allowed_plugin_prefixes}
    for key in ("agents", "skills", "plugins"):
        raw = init_message.get(key)
        if raw is None:
            continue
        if not isinstance(raw, list):
            violations.append(f"`{key}` is not a list — cannot prove that surface")
            continue
        names = _names(raw)
        surfaces[key] = sorted(names)
        for name in names:
            if name not in extra_allow[key]:
                violations.append(f"{key} surface present: {name}")

    # Anything else that is list- or object-valued is an undocumented surface: UNKNOWN fails.
    unknown_keys: list[str] = []
    for key in sorted(init_message):
        if key in DOCUMENTED_SCALAR_KEYS or key in DOCUMENTED_SURFACES:
            continue
        value = init_message[key]
        if isinstance(value, list | dict):
            violations.append(f"undocumented roster surface `{key}` present; it cannot be "
                              "proved empty")
            surfaces[key] = sorted(_names(value)) if isinstance(value, list) else \
                sorted(str(k) for k in value)
        else:
            unknown_keys.append(key)

    if require_permission_mode is not None:
        mode = init_message.get("permissionMode")
        if mode != require_permission_mode:
            violations.append(f"permissionMode is {mode!r}, expected {require_permission_mode!r}")

    digest = _digest(surfaces)
    return RosterReport(not violations, violations, sorted(tools), servers, plugin_cmds,
                        surfaces, unknown_keys, digest)


def _digest(surfaces: dict[str, list[str]]) -> str:
    """sha256 over every surface seen — tools, servers, slash commands, agents, skills,
    plugins and any undocumented one — sorted, so the same roster always hashes the same."""
    material = json.dumps({k: sorted(v) for k, v in sorted(surfaces.items())},
                          separators=(",", ":"))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def main(argv: list[str]) -> int:
    """`roster_assert.py < init.json` — exit 0 when the roster is clean, 3 when it is not."""
    try:
        message = json.load(sys.stdin)
    except ValueError:
        sys.stderr.write("roster_assert: stdin was not JSON\n")
        return 3
    report = assert_roster(message)
    sys.stdout.write(report.summary() + "\n")
    for v in report.violations:
        sys.stdout.write(f"  - {v}\n")
    return 0 if report.ok else 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
