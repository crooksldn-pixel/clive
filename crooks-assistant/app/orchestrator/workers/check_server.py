"""The builder's one extra tool: ``run_checks``, a stdio MCP server the dispatcher ships with the launch.

A builder may run its objective's declared checks before it reports, and nothing else:

- the checks are the objective's own, written by the dispatcher into a host-side
  config file (outside the workspace, which is all the builder's file tools can
  reach) and passed to this server at launch; the tool takes at most the *name* of
  one of them and never an argv, a cwd or a timeout;
- each run is on a fresh copy of the builder's workspace as it stands, through the
  same ``NamespaceSandbox`` the dispatcher uses, with the same read-only paths,
  limits and per-check timeout: its own mount, PID, network, IPC and UTS namespaces,
  a private ``/proc`` that shows only the check's own processes, no network, an
  environment of PATH (and the sandbox's fixed HOME/TMPDIR/LANG) only, and uid 65534
  when the dispatcher runs as root. There is no unsandboxed fallback;
- the live workspace is never a check's tree, so nothing a check writes can enter
  the candidate CLIVE commits;
- what comes back is each check's name, exit code and a bounded, redacted tail of
  its output;
- the runs are advisory. The dispatcher runs every check itself on the committed
  candidate after the builder reports, and only that run is evidence.

Claude Code starts stdio servers with its own environment, which holds the worker's
``CLAUDE_CODE_OAUTH_TOKEN``. Before reading anything, this server re-executes itself
with an environment of PATH only, so the token is not in its memory or in its
``/proc/<pid>/environ``; and a check cannot read the Claude process's environment
through ``/proc`` because the check's ``/proc`` is its own PID namespace's.

Run as ``python -I check_server.py <config.json>``. The protocol is MCP over stdio:
newline-delimited JSON-RPC 2.0, one request at a time.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # crooks-assistant/, whatever the cwd

SERVER_NAME = "clive_checks"
TOOL_NAME = "run_checks"
QUALIFIED_TOOL = f"mcp__{SERVER_NAME}__{TOOL_NAME}"
CLEAN_PATH = "/usr/sbin:/usr/bin:/sbin:/bin"
PROTOCOL_VERSION = "2025-06-18"
MAX_TAIL = 4000  # characters of output returned per check, after redaction
ADVISORY = ("Advisory only: CLIVE runs every declared check itself on your committed result after you report; "
            "that run, not this one, is the evidence.")

TOOL = {
    "name": TOOL_NAME,
    "description": "Run your objective's listed checks in a sandboxed copy of your workspace as it is now. "
                   "Give `check` to run one of them by name, or nothing to run them all. " + ADVISORY,
    "inputSchema": {
        "type": "object",
        "properties": {"check": {"type": "string", "description": "the name of one listed check"}},
        "additionalProperties": False,
    },
}

# Secrets in output: known token shapes, credential assignments, and any long mixed-case
# alphanumeric run (which also catches a fragment of a token cut by truncation).
_TOKEN_SHAPES = re.compile(
    r"(?:sk-ant-[A-Za-z0-9_-]+|sk-[A-Za-z0-9_-]{16,}|github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9]{16,}"
    r"|xox[abprs]-[A-Za-z0-9-]+|AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{30,}|ya29\.[A-Za-z0-9._-]+)")
_BEARER = re.compile(r"(?i)\b(bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}")
_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|ACCESS_?KEY|CREDENTIALS?|AUTH)[A-Z0-9_]*)"
    r"(\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)")
_LONG_RUN = re.compile(r"[A-Za-z0-9_+=-]{24,}")
REDACTED = "[redacted]"


def _looks_secret(run: str) -> bool:
    return (any(c.isdigit() for c in run) and any(c.isupper() for c in run) and any(c.islower() for c in run))


def redact(text: str) -> str:
    text = _TOKEN_SHAPES.sub(REDACTED, text)
    text = _BEARER.sub(lambda m: f"{m.group(1)} {REDACTED}", text)
    text = _ASSIGNMENT.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", text)
    return _LONG_RUN.sub(lambda m: REDACTED if _looks_secret(m.group(0)) else m.group(0), text)


def bounded_tail(stdout: str, stderr: str, limit: int = MAX_TAIL) -> str:
    """The last ``limit`` characters of the check's output, redacted before and after cutting.

    The sandbox itself keeps only a tail, so the first line of what arrives may start mid-secret;
    a cut line is dropped rather than shown, and redaction runs again on what is returned."""
    parts = []
    for name, text in (("stdout", stdout or ""), ("stderr", stderr or "")):
        if text:
            parts.append(f"--- {name} ---\n{redact(text)}")
    joined = "\n".join(parts)
    if len(joined) > limit:
        cut = joined[-limit:]
        joined = "[… earlier output omitted]\n" + cut.split("\n", 1)[-1]
    return redact(joined)[-(limit + 64):]


class CheckService:
    """The declared checks, the workspace they run against, and the runner that runs them."""

    def __init__(self, config: dict, runner=None) -> None:
        self.workspace = Path(config["workspace"])
        self.scratch = Path(config["scratch"])
        self.checks = {c["name"]: c for c in config["checks"]}
        if runner is None:
            sys.path.insert(0, str(ROOT))
            from app.orchestrator.checks import NamespaceSandbox

            box = config.get("sandbox") or {}
            runner = NamespaceSandbox(ro_paths=tuple(box.get("ro_paths", ())),
                                      **{k: int(box[k]) for k in ("memory_bytes", "file_bytes", "open_files",
                                                                  "processes") if k in box})
        self.runner = runner

    def run(self, arguments: dict | None) -> tuple[bool, dict]:
        arguments = arguments or {}
        extra = sorted(set(arguments) - {"check"})
        if extra:
            return False, {"error": f"unknown argument(s) {', '.join(extra)}; only `check` (a listed check's name)",
                           "listed_checks": sorted(self.checks)}
        name = arguments.get("check")
        if name is not None and (not isinstance(name, str) or name not in self.checks):
            return False, {"error": "not a listed check; nothing was run", "listed_checks": sorted(self.checks)}
        chosen = [self.checks[name]] if name else list(self.checks.values())
        ok, why = self.runner.availability()
        if not ok:
            return False, {"error": f"check sandbox unavailable ({why}); checks run only in the sandbox, so none ran"}
        results = []
        for check in chosen:
            tree = self.scratch / check["name"]
            if tree.exists():
                shutil.rmtree(tree)
            self.scratch.mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.workspace, tree, symlinks=True)
            try:
                outcome = self.runner.run(tuple(check["argv"]), tree=tree, cwd=check.get("cwd", "."),
                                          timeout_s=int(check["timeout_s"]))
            except Exception as exc:  # the sandbox refused; report it, never fall back
                results.append({"name": check["name"], "exit_code": None, "output_tail": redact(str(exc))[-500:]})
                continue
            results.append({"name": check["name"], "exit_code": outcome.get("exit_code"),
                            "output_tail": bounded_tail(outcome.get("stdout_tail", ""),
                                                        outcome.get("stderr_tail", ""))})
        return True, {"advisory": ADVISORY, "results": results}


def handle(service: CheckService, message: dict) -> dict | None:
    """One JSON-RPC message in, at most one response out (notifications get none)."""
    method, mid = message.get("method"), message.get("id")
    if mid is None:
        return None
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                  "serverInfo": {"name": SERVER_NAME, "version": "1"}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [TOOL]}
    elif method == "tools/call":
        params = message.get("params") or {}
        if params.get("name") != TOOL_NAME:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": "unknown tool"}}
        ok, payload = service.run(params.get("arguments"))
        result = {"content": [{"type": "text", "text": json.dumps(payload, indent=1)}], "isError": not ok}
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _reexec_clean() -> None:
    """Replace this process with itself under an environment of PATH only (see the module docstring)."""
    if set(os.environ) - {"PATH"} or os.environ.get("PATH") != CLEAN_PATH:
        os.execve(sys.executable, [sys.executable, "-I", str(Path(__file__).resolve()), *sys.argv[1:]],
                  {"PATH": CLEAN_PATH})


def main(argv: list[str]) -> int:
    _reexec_clean()
    os.chdir("/")
    config = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    service = CheckService(config)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        reply = handle(service, message) if isinstance(message, dict) else None
        if reply is not None:
            sys.stdout.write(json.dumps(reply) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
