#!/usr/bin/env python3
"""gitleaks_gate — scan what a `git commit` or `git push` would publish, before it does.

A project-scoped Claude Code PreToolUse hook on Bash. It does nothing for any other command.
For a commit it scans the staged changes (and the working-tree diff when the commit would
take unstaged content: `-a`, `--all`, `--include`, or explicit paths). For a push it scans
every local commit not reachable from any remote-tracking ref (`--all --not --remotes`).

Reports **rule id, path and line or commit only.** The gitleaks report is read from a temporary
file with `--redact`, its stdout and stderr go to /dev/null, and the `Secret` / `Match` /
`Line` fields are never touched. A finding names where to look, never what was found.

Fails closed: malformed hook input, a missing gitleaks binary, a scan that errors or times
out, and a report that cannot be parsed all DENY (exit 2). No environment variable relaxes
this. The gitleaks binary is resolved from the checkout's own pinned tooling
(`<repo>/.tooling/bin/gitleaks`, see docs/DEV_ENVIRONMENT.md §4) and, failing that, PATH.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import guard_bash as gb  # same directory; the shared lexer and the fail-closed input contract

SCAN_TIMEOUT_S = 90
PUBLISH_SUBCOMMANDS = ("commit", "push")


def _gitleaks_binary() -> str | None:
    repo_root = Path(__file__).resolve().parents[3]
    pinned = repo_root / ".tooling" / "bin" / "gitleaks"
    if pinned.is_file() and os.access(pinned, os.X_OK):
        return str(pinned)
    return shutil.which("gitleaks")


def _publish_actions(command: str) -> list[tuple[str, list[str], str | None]]:
    """(subcommand, rest, -C path) for every git commit/push segment in the command."""
    executable, extra = gb._strip_heredocs(command)
    actions: list[tuple[str, list[str], str | None]] = []
    for text in [executable, *(body for kind, body in extra if kind == "shell")]:
        for seg, _piped in gb._segments(text):
            toks = gb._tokens(seg)
            if not toks:
                continue
            # unwrap sudo/env/... exactly as the guard does
            for _ in range(8):
                base = gb._basename(toks[0]) if toks else ""
                if base in gb.PASSTHROUGH:
                    toks = gb._unwrap(base, toks)
                    continue
                break
            if not toks or gb._basename(toks[0]) != "git":
                continue
            sub = gb._git_subcommand(toks)
            if sub is None:
                continue
            name, rest, gpaths = sub
            if name in PUBLISH_SUBCOMMANDS:
                c_path = None
                for i, t in enumerate(toks):
                    if t == "-C" and i + 1 < len(toks):
                        c_path = toks[i + 1]
                actions.append((name, rest, c_path))
    return actions


def _scan(gitleaks: str, repo: str, mode_args: list[str]) -> gb.Decision:
    with tempfile.TemporaryDirectory(prefix="gitleaks-gate-") as tmp:
        report = os.path.join(tmp, "report.json")
        argv = [gitleaks, "git", "--no-banner", "--redact", "--exit-code", "1",
                "--report-format", "json", "--report-path", report, *mode_args, repo]
        try:
            proc = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=SCAN_TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return gb.deny("GITLEAKS-ERROR", "gitleaks could not be run or timed out; nothing is "
                           "published until it can")
        if proc.returncode == 0:
            return gb.ALLOW
        if proc.returncode != 1:
            return gb.deny("GITLEAKS-ERROR", f"gitleaks exited {proc.returncode}; nothing is "
                           "published until the scan can complete")
        try:
            with open(report, encoding="utf-8") as fh:
                findings = json.load(fh)
        except (OSError, ValueError):
            return gb.deny("GITLEAKS-ERROR", "gitleaks reported leaks but the report could not be "
                           "read; nothing is published")
        if not isinstance(findings, list):
            return gb.deny("GITLEAKS-ERROR", "unexpected gitleaks report shape")
        where = []
        for f in findings[:20]:
            if not isinstance(f, dict):
                continue
            rule = str(f.get("RuleID", "?"))
            path = str(f.get("File", "?"))
            commit = str(f.get("Commit", ""))[:7]
            line = f.get("StartLine", "")
            loc = f"{path}:{line}" if line != "" else path
            where.append(f"{rule} at {loc}" + (f" (commit {commit})" if commit else ""))
        return gb.deny("GITLEAKS-FINDING",
                       "secret scan found " + str(len(findings)) + " finding(s): "
                       + "; ".join(where) + ". Remove the value, then retry. The value itself is "
                       "never printed.")


def run_gate(raw: bytes, gitleaks: str | None = None) -> gb.Decision:
    if not isinstance(raw, bytes | bytearray) or not raw:
        return gb.deny("MALFORMED-INPUT", "hook input was empty")
    if len(raw) > gb.MAX_INPUT_BYTES:
        return gb.deny("OVERSIZED-INPUT", "hook input too large")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return gb.deny("MALFORMED-INPUT", "hook input was not valid JSON")
    if not isinstance(payload, dict) or payload.get("tool_name") != "Bash":
        return gb.deny("UNEXPECTED-TOOL", "this gate only decides Bash calls")
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str) or not command.strip():
        return gb.deny("MALFORMED-INPUT", "tool_input.command was not a non-empty string")
    if len(command) > gb.MAX_COMMAND_CHARS:
        return gb.deny("OVERSIZED-INPUT", "command too long")
    cwd = payload.get("cwd")
    if cwd is not None and not isinstance(cwd, str):
        return gb.deny("MALFORMED-INPUT", "cwd was not a string")

    try:
        actions = _publish_actions(command)
    except ValueError:
        return gb.deny("UNPARSEABLE", "command could not be tokenised")
    if not actions:
        return gb.ALLOW

    binary = gitleaks or _gitleaks_binary()
    if not binary:
        return gb.deny("GITLEAKS-MISSING", "gitleaks is not available at .tooling/bin/gitleaks or "
                       "on PATH; run `python3 crooks-assistant/scripts/dev_env.py plan` (step 4) "
                       "before committing or pushing")

    for name, rest, c_path in actions:
        repo = c_path or cwd or os.getcwd()
        if gb._protected_hit(repo):
            return gb.deny("PROTECTED-PATH", "refusing to scan or publish from a protected checkout")
        if name == "commit":
            result = _scan(binary, repo, ["--pre-commit", "--staged"])
            if result.denied:
                return result
            values = _value_after_message(rest)
            pathspecs = [t for t in rest if not t.startswith("-") and t not in values]
            takes_unstaged = bool(pathspecs) or any(
                t in ("-a", "--all", "--include", "-i") or gb._short_has(t, "a") for t in rest
            )
            if takes_unstaged:
                result = _scan(binary, repo, ["--pre-commit"])
                if result.denied:
                    return result
        else:
            result = _scan(binary, repo, ["--log-opts=--all --not --remotes"])
            if result.denied:
                return result
    return gb.ALLOW


def _value_after_message(rest: list[str]) -> set[str]:
    """Tokens that are the values of -m/-F/-C/--author and not pathspecs."""
    values: set[str] = set()
    for i, t in enumerate(rest):
        if t in ("-m", "--message", "-F", "--file", "-C", "-c", "--author", "--date", "-t",
                 "--template", "--trailer", "--fixup", "--squash", "--reuse-message",
                 "--reedit-message") and i + 1 < len(rest):
            values.add(rest[i + 1])
    return values


def main() -> int:
    raw = sys.stdin.buffer.read(gb.MAX_INPUT_BYTES + 1)
    result = run_gate(raw)
    if result.denied:
        sys.stderr.write(f"gitleaks_gate: DENY [{result.rule}] {result.reason}\n")
        return 2
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
