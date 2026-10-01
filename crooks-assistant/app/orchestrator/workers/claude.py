"""Builder driver: the Claude Code CLI in headless mode, with its surface cut at launch.

Mechanism, as verified against Claude Code 2.1.280 on 2026-09-23 (see
docs/product-memory/ENGINEERING_DISPATCHER_V1.md): ``claude -p`` with
``--output-format stream-json --verbose`` writes one JSON event per line; the
first ``system/init`` event reports the session id, the cwd and the exact tool,
MCP-server, plugin, skill and slash-command roster the session can use; the last
``result`` event carries ``structured_output`` validated against ``--json-schema``.

What reduces the worker's capability is the launch itself, not the prompt:

- ``env -i`` equivalent: the process gets PATH, a fresh HOME of its own, LANG,
  TMPDIR and the attempt marker, and nothing else from the dispatcher (no GitHub,
  Shopify, Gmail or cloud tokens, no proxy secrets, no owner config);
- ``--restricted``: user, project and local settings are ignored and file tools are
  confined to the workspace; ``--setting-sources ""`` and ``--disable-slash-commands``
  load no settings, skills or commands;
- ``--strict-mcp-config --mcp-config``: no MCP server, so no connector, however the
  host is configured, with one exception: when the objective declares checks, the
  config names exactly CLIVE's own ``run_checks`` server (``check_server.py``), started
  from the dispatcher's interpreter with a host-side config of those checks, and
  ``--allowedTools`` gains exactly its one tool. The checks it runs are the
  objective's, in the same sandbox the dispatcher uses; the runs are advisory;
- ``--tools`` names the built-in tools (file tools only, by default; Bash only when
  the dispatcher is configured with explicit command prefixes); ``--permission-mode
  dontAsk`` with an explicit ``--allowedTools`` list denies everything else (a denied
  call is reported, not run);
- ``--session-id`` is chosen by CLIVE before launch, so the session the kernel
  records at assignment is the session that runs.

Then the launch is checked, fail-closed: ``verify_started`` compares the init
event against what was asked for, and any extra tool, any MCP server but that one
(and it only when asked for), any non-builtin plugin, any skill, another cwd or another session is a deterministic
refusal; the dispatcher kills the worker and blocks the task. A launch that asked for the
checks server must also show it: its ``run_checks`` tool in the roster and the server itself
``connected``; a builder told it has run_checks and started without it is refused the same way
(the 2026-09-30 re-pin review, second run, F-01).

Stopping is confirmed, not assumed (the 2026-09-30 re-pin review, F-01): ``kill`` sends
SIGTERM to the worker's process group, waits (bounded) for every process carrying the
attempt marker to go, sends SIGKILL to whatever remains, waits again, and returns the pids
still alive. The dispatcher records a cancel or a block as a stop only on an empty answer.

Authentication is whatever the CLI resolves in that clean environment: a host
provider that authenticates the process, or, when ``oauth_token_file`` is set,
``CLAUDE_CODE_OAUTH_TOKEN`` read from that host-side file (the same variable the
application's own Agent SDK provider uses). Nothing here reads any other secret,
copies credentials into the workspace or selects API-key billing.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from . import check_server
from .base import (
    Activity,
    Finished,
    LaunchRecord,
    LaunchSpec,
    Observation,
    Started,
    WorkerLaunchError,
    pid_start_ticks,
    processes_with_marker,
)

__all__ = ["ClaudeCodeWorker", "WORKER_REPORT_SCHEMA", "parse_events"]

MARKER = "CLIVE_ATTEMPT_ID"
FILE_TOOLS = ("Read", "Edit", "Write", "Glob", "Grep")
# No Bash by default. A prefix allowlist is not a boundary (``git diff --no-index`` reads
# any file on the host, ``git log --output`` writes one), and ``--restricted`` confines
# the file tools, not shell commands. CLIVE runs the objective's checks itself.
DEFAULT_BASH: tuple[str, ...] = ()
ALLOWED_PLUGINS = frozenset({"telemetry@builtin"})
REPORT_TOOL = "StructuredOutput"
CHECK_SERVER = check_server.SERVER_NAME
CHECK_TOOL = check_server.QUALIFIED_TOOL
# An MCP tool call has its own client-side timeout; a declared check may run for up to 7200s.
CHECK_TOOL_TIMEOUT_MS = str((7200 + 300) * 1000)
EDIT_TOOLS = frozenset({"Edit", "Write"})
# Stopping a worker: how long SIGTERM gets before SIGKILL, and how long SIGKILL gets to be confirmed.
KILL_GRACE_S = 5.0
KILL_CONFIRM_S = 5.0
_KILL_POLL_S = 0.05

WORKER_REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["completed", "blocked", "owner_decision_required"]},
        "summary": {"type": "string", "maxLength": 4000},
        "reason": {"type": "string", "maxLength": 2000},
    },
    "required": ["status", "summary"],
    "additionalProperties": False,
}

_TRANSIENT_HTTP = {408, 409, 429, 500, 502, 503, 504, 529}
_AUTH_HINTS = ("invalid api key", "not logged in", "please run /login", "authentication_error",
               "oauth token", "credit balance", "unauthorized")


class ClaudeCodeWorker:
    principal_id = "claude"
    kind = "claude-code-cli"

    def __init__(
        self,
        *,
        cli: str = "claude",
        model: str | None = None,
        effort: str | None = None,
        max_turns: int = 200,
        bash_prefixes: tuple[str, ...] = DEFAULT_BASH,
        oauth_token_file: Path | None = None,
        check_python: str = sys.executable,
        kill_grace_s: float = KILL_GRACE_S,
        kill_confirm_s: float = KILL_CONFIRM_S,
    ) -> None:
        self.cli = cli
        self.model = model
        self.effort = effort
        self.max_turns = max_turns
        self.bash_prefixes = tuple(bash_prefixes)
        self.oauth_token_file = oauth_token_file
        self.check_python = check_python
        self.kill_grace_s = kill_grace_s
        self.kill_confirm_s = kill_confirm_s
        self._children: dict[int, subprocess.Popen] = {}

    # ---- launch --------------------------------------------------------------
    def builtin_tools(self) -> tuple[str, ...]:
        return (*FILE_TOOLS, "Bash") if self.bash_prefixes else FILE_TOOLS

    def allowed_tools(self, spec: LaunchSpec | None = None) -> tuple[str, ...]:
        extra = (CHECK_TOOL,) if spec is not None and spec.check_config is not None else ()
        return (*FILE_TOOLS, *(f"Bash({p}:*)" for p in self.bash_prefixes), *extra)

    def mcp_config(self, spec: LaunchSpec) -> str:
        """No MCP server, or exactly CLIVE's run_checks server bound to this attempt's declared checks."""
        servers = {}
        if spec.check_config is not None:
            servers[CHECK_SERVER] = {
                "type": "stdio",
                "command": self.check_python,
                "args": ["-I", str(Path(check_server.__file__).resolve()), str(spec.check_config)],
                "env": {},
            }
        return json.dumps({"mcpServers": servers}, separators=(",", ":"))

    def argv(self, spec: LaunchSpec, cli_path: str) -> list[str]:
        argv = [
            cli_path, "-p", spec.prompt,
            "--output-format", "stream-json", "--verbose",
            "--session-id", spec.session_id,
            "--restricted",
            "--tools", ",".join(self.builtin_tools()),
            "--allowedTools", *self.allowed_tools(spec),
            "--permission-mode", "dontAsk",
            "--strict-mcp-config", "--mcp-config", self.mcp_config(spec),
            "--setting-sources", "",
            "--disable-slash-commands",
            "--no-session-persistence",
            "--max-turns", str(self.max_turns),
            "--json-schema", json.dumps(WORKER_REPORT_SCHEMA, separators=(",", ":")),
        ]
        if self.model:
            argv += ["--model", self.model]
        if self.effort:
            argv += ["--effort", self.effort]
        return argv

    def environment(self, spec: LaunchSpec, cli_path: str) -> dict[str, str]:
        tmp = spec.home / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)
        env = {
            "PATH": f"{Path(cli_path).parent}:/usr/local/bin:/usr/bin:/bin",
            "HOME": str(spec.home),
            "LANG": "C.UTF-8",
            "TMPDIR": str(tmp),
            MARKER: spec.marker,
            # The owner's decision of 1 October 2026 (decision 7): the CLI on the build server is
            # never updated by a builder run. A newer CLI can bring a built-in plugin the launch
            # check refuses (ALLOWED_PLUGINS), which would stop every build at once; it is updated
            # deliberately, with the pin, instead.
            "DISABLE_AUTOUPDATER": "1",
        }
        if spec.check_config is not None:
            env["MCP_TOOL_TIMEOUT"] = CHECK_TOOL_TIMEOUT_MS
        if self.oauth_token_file is not None:
            try:
                token = Path(self.oauth_token_file).read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise WorkerLaunchError(f"worker token file unreadable: {exc}", transient=False) from exc
            if not token:
                raise WorkerLaunchError("worker token file is empty", transient=False)
            env["CLAUDE_CODE_OAUTH_TOKEN"] = token
        return env

    def launch(self, spec: LaunchSpec) -> LaunchRecord:
        cli_path = shutil.which(self.cli) if not os.path.isabs(self.cli) else self.cli
        if not cli_path or not os.access(cli_path, os.X_OK):
            raise WorkerLaunchError(f"worker CLI {self.cli!r} is not installed or not executable", transient=False)
        if self.live_pids(spec.marker):
            raise WorkerLaunchError(f"a worker for {spec.attempt_id} is already running; not launching a second",
                                    transient=False)
        spec.home.mkdir(parents=True, exist_ok=True)
        spec.log_path.parent.mkdir(parents=True, exist_ok=True)
        env = self.environment(spec, cli_path)
        argv = self.argv(spec, cli_path)
        with open(spec.log_path, "ab") as out, open(spec.stderr_path, "ab") as err:
            try:
                proc = subprocess.Popen(
                    argv, cwd=str(spec.workspace), env=env, stdin=subprocess.DEVNULL,
                    stdout=out, stderr=err, start_new_session=True, close_fds=True,
                )
            except OSError as exc:
                raise WorkerLaunchError(f"worker process could not start: {exc}", transient=True) from exc
        self._children[proc.pid] = proc
        shown = [a if i != 2 else f"<prompt {len(spec.prompt)} chars>" for i, a in enumerate(argv)]
        return LaunchRecord(
            pid=proc.pid, pid_start_ticks=pid_start_ticks(proc.pid), argv=tuple(shown),
            env_names=tuple(sorted(k if k != "CLAUDE_CODE_OAUTH_TOKEN" else k + " (from token file)" for k in env)),
            launched_at=datetime.now(UTC),
        )

    # ---- observe -------------------------------------------------------------
    def read(self, log_path: Path, offset: int = 0) -> tuple[list[Observation], int]:
        self._reap()
        try:
            data = Path(log_path).read_bytes()
        except FileNotFoundError:
            return [], 0
        end = data.rfind(b"\n") + 1  # only whole lines; a partial last line is read next time
        return parse_events(data[:end].decode("utf-8", errors="replace")), end

    def verify_started(self, started: Started, spec: LaunchSpec) -> list[str]:
        problems: list[str] = []
        if started.session_id != spec.session_id:
            problems.append(f"session {started.session_id} is not the assigned session {spec.session_id}")
        if os.path.realpath(started.cwd) != os.path.realpath(spec.workspace):
            problems.append(f"cwd {started.cwd} is not the attempt workspace {spec.workspace}")
        allowed = set(self.builtin_tools()) | {REPORT_TOOL}
        allowed_servers = set()
        if spec.check_config is not None:
            allowed.add(CHECK_TOOL)
            allowed_servers.add(CHECK_SERVER)
            problems += _declared_checks_missing(started)
        extra = sorted(set(started.tools) - allowed)
        if extra:
            problems.append("tools beyond the launch policy: " + ", ".join(extra))
        foreign_servers = sorted(set(started.mcp_servers) - allowed_servers)
        if foreign_servers:
            problems.append("MCP servers present: " + ", ".join(foreign_servers))
        foreign = sorted(set(started.plugins) - ALLOWED_PLUGINS)
        if foreign:
            problems.append("plugins beyond the builtin allowance: " + ", ".join(foreign))
        if started.skills or started.slash_commands:
            problems.append(f"{started.skills} skills and {started.slash_commands} slash commands loaded; expected none")
        if started.permission_mode != "dontAsk":
            problems.append(f"permission mode {started.permission_mode!r}, expected 'dontAsk'")
        return problems

    def diagnose_exit(self, stderr_path: Path) -> tuple[str, bool]:
        """Why a worker died without a result, and whether it is worth retrying."""
        try:
            text = Path(stderr_path).read_text(encoding="utf-8", errors="replace")[-4000:]
        except OSError:
            text = ""
        low = text.lower()
        if any(h in low for h in _AUTH_HINTS):
            return f"worker authentication failed in its isolated environment: {text.strip()[-300:]}", False
        return (f"worker process exited without a result: {text.strip()[-300:]}" if text.strip()
                else "worker process exited without a result and wrote nothing to stderr"), True

    def live_pids(self, marker: str) -> list[int]:
        return processes_with_marker(MARKER, marker)

    def kill(self, marker: str) -> list[int]:
        """Stop every process of the attempt, for sure, and say what is still alive ([] means confirmed gone).

        SIGTERM to each live process's group (the worker leads its own session), then up to ``kill_grace_s``
        for every process carrying the marker to exit; SIGKILL to whatever remains, then up to
        ``kill_confirm_s`` again. Both waits poll ``live_pids``, so a worker that ignores SIGTERM costs
        at most the grace period, and one that is gone at once costs nothing."""
        alive = self.live_pids(marker)
        if not alive:
            return []
        _signal(alive, signal.SIGTERM)
        alive = self._wait_gone(marker, self.kill_grace_s)
        if not alive:
            return []
        _signal(alive, signal.SIGKILL)
        return self._wait_gone(marker, self.kill_confirm_s)

    def _wait_gone(self, marker: str, bound_s: float) -> list[int]:
        deadline = time.monotonic() + max(0.0, bound_s)
        while True:
            alive = self.live_pids(marker)
            self._reap()
            if not alive or time.monotonic() >= deadline:
                return alive
            time.sleep(_KILL_POLL_S)

    def _reap(self) -> None:
        for pid, proc in list(self._children.items()):
            if proc.poll() is not None:
                del self._children[pid]  # reap: a finished child is not left a zombie


def _signal(pids: list[int], sig: signal.Signals) -> None:
    """``sig`` to each pid's process group, else to the pid alone (a process outside its leader's group).

    A process that is already gone, or that this user may not signal, is left to the caller's
    confirmation, which reports it if it is still alive."""
    for pid in pids:
        try:
            os.killpg(pid, sig)
            continue
        except (ProcessLookupError, PermissionError):
            pass
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass


def _declared_checks_missing(started: Started) -> list[str]:
    """What a launch that asked for the checks server lacks: the tool in the roster, or the server connected.

    Allowing the tool and server is not enough: a builder told it has run_checks (its prompt says so)
    and started without it is refused, as any other launch surface that is not the one asked for."""
    problems = []
    if CHECK_TOOL not in started.tools:
        problems.append(f"the declared checks' tool {CHECK_TOOL} is missing from the init roster")
    states = [status for name, status in started.mcp_server_status if name == CHECK_SERVER]
    if not states:
        problems.append(f"the declared checks' MCP server {CHECK_SERVER} is not in the init roster")
    elif "connected" not in states:
        problems.append(f"the declared checks' MCP server {CHECK_SERVER} is not connected "
                        f"(status {', '.join(s or 'not reported' for s in states)})")
    return problems


def _server_name(server: object) -> str:
    return str(server.get("name", server)) if isinstance(server, dict) else str(server)


def _at(event: dict) -> datetime | None:
    stamp = event.get("timestamp")
    if not isinstance(stamp, str):
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_events(text: str) -> list[Observation]:
    """Stream-json lines to observations. Unknown events are 'other'; nothing is invented."""
    out: list[Observation] = []
    pending: dict[str, tuple[str, str | None]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind, sub = event.get("type"), event.get("subtype")
        if kind == "system" and sub == "init":
            servers = tuple(event.get("mcp_servers") or ())
            out.append(Started(
                session_id=str(event.get("session_id", "")),
                cwd=str(event.get("cwd", "")),
                model=event.get("model"),
                tools=tuple(event.get("tools") or ()),
                mcp_servers=tuple(_server_name(s) for s in servers),
                mcp_server_status=tuple((_server_name(s), str(s.get("status") or "") if isinstance(s, dict) else "")
                                        for s in servers),
                plugins=tuple(str(p.get("source") or p.get("name")) if isinstance(p, dict) else str(p)
                              for p in event.get("plugins") or ()),
                skills=len(event.get("skills") or ()),
                slash_commands=len(event.get("slash_commands") or ()),
                permission_mode=event.get("permissionMode"),
                api_key_source=event.get("apiKeySource"),
            ))
        elif kind == "system" and sub == "permission_denied":
            out.append(Activity(at=_at(event), kind="tool_result", detail="permission denied", denied=True))
        elif kind == "assistant":
            for block in (event.get("message") or {}).get("content") or ():
                if block.get("type") == "tool_use":
                    name = str(block.get("name"))
                    target = (block.get("input") or {}).get("file_path")
                    pending[str(block.get("id"))] = (name, target)
                    out.append(Activity(at=_at(event), kind="tool_use", detail=name))
                elif block.get("type") == "text":
                    out.append(Activity(at=_at(event), kind="assistant", detail="text"))
        elif kind == "user":
            for block in (event.get("message") or {}).get("content") or ():
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    name, target = pending.pop(str(block.get("tool_use_id")), ("?", None))
                    ok = not block.get("is_error")
                    edited = target if ok and name in EDIT_TOOLS and target else None
                    out.append(Activity(at=_at(event), kind="tool_result",
                                        detail=f"{name} {'ok' if ok else 'error'}", edited=edited))
        elif kind == "rate_limit_event":
            info = event.get("rate_limit_info") or {}
            limited = info.get("status") not in (None, "allowed", "allowed_warning")
            out.append(Activity(at=None, kind="rate_limit", detail=str(info.get("status")), rate_limited=limited))
        elif kind == "result":
            out.append(_finished(event))
    return out


def _finished(event: dict) -> Finished:
    detail = {
        "subtype": event.get("subtype"),
        "num_turns": event.get("num_turns"),
        "duration_ms": event.get("duration_ms"),
        "total_cost_usd": event.get("total_cost_usd"),
        "api_error_status": event.get("api_error_status"),
        "permission_denials": len(event.get("permission_denials") or ()),
        "session_id": event.get("session_id"),
    }
    if event.get("is_error") or event.get("subtype") != "success":
        status = event.get("api_error_status")
        if event.get("subtype") == "error_max_turns":
            return Finished("error", reason="the worker ran out of its turn budget", error_class="deterministic",
                            detail=detail)
        if status in (401, 403):
            return Finished("error", reason=f"worker API refused authentication ({status})",
                            error_class="deterministic", detail=detail)
        if status in _TRANSIENT_HTTP or event.get("subtype") == "error_during_execution":
            return Finished("error", reason=f"transient worker failure ({event.get('subtype')}, {status})",
                            error_class="transient", detail=detail)
        return Finished("error", reason=f"worker ended in error ({event.get('subtype')}, {status})",
                        error_class="transient", detail=detail)
    report = event.get("structured_output")
    if not isinstance(report, dict) or report.get("status") not in ("completed", "blocked", "owner_decision_required"):
        return Finished("error", reason="the worker finished without a structured report",
                        error_class="deterministic", detail=detail)
    return Finished(report["status"], summary=str(report.get("summary", ""))[:4000],
                    reason=str(report.get("reason", ""))[:2000], detail=detail)
