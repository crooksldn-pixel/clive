"""The integration builder: CLIVE's own deterministic merge of accepted candidates.

An integration objective (``Objective.builder == "integrator"``) names exact SHAs that
were each accepted and integrated on their own target branches. Its attempt is run by
this driver, not by a model: the process merges those commits onto the attempt's start
SHA with ``git merge-tree`` in the dispatcher's clone (no working tree, no ref moved),
writes the merged content of every changed path into the attempt workspace, and reports
through the same stream-json events the Claude builder writes. From there the dispatcher
treats it as any other attempt: CLIVE commits the workspace, derives the changed paths,
runs the objective's whole-product checks in the sandbox, and sends the exact integrated
SHA to the independent reviewer. Nothing here accepts, pushes or integrates.

A conflict is not resolved here. The attempt reports ``blocked`` with the conflicting
paths, so the task blocks with them; resolving it is a separate objective for a builder.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .base import LaunchSpec, Started
from .claude import ClaudeCodeWorker

__all__ = ["IntegratorWorker", "INTEGRATOR_TOOL"]

INTEGRATOR_TOOL = "Integrate"


class IntegratorWorker(ClaudeCodeWorker):
    principal_id = "clive-integrator"
    kind = "clive-integrator"

    def __init__(self, repo: Path) -> None:
        super().__init__(cli=sys.executable)
        self.repo = Path(repo)

    def argv(self, spec: LaunchSpec, cli_path: str) -> list[str]:
        return [cli_path, "-m", "app.orchestrator.workers.integrator", "--session-id", spec.session_id,
                "--repo", str(self.repo), "--job", spec.prompt]

    def environment(self, spec: LaunchSpec, cli_path: str) -> dict[str, str]:
        env = super().environment(spec, cli_path)
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
        return env

    def verify_started(self, started: Started, spec: LaunchSpec) -> list[str]:
        problems = []
        if started.session_id != spec.session_id:
            problems.append(f"session {started.session_id} is not the assigned session {spec.session_id}")
        if os.path.realpath(started.cwd) != os.path.realpath(spec.workspace):
            problems.append(f"cwd {started.cwd} is not the attempt workspace {spec.workspace}")
        if tuple(started.tools) != (INTEGRATOR_TOOL,) or started.mcp_servers or started.plugins:
            problems.append(f"integrator surface is not exactly ({INTEGRATOR_TOOL},): {started.tools}")
        return problems


# ------------------------------------------------------------------ the process
def _git(repo: str, *args: str, ok: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    proc = subprocess.run(["git", "-C", repo, *args], capture_output=True, timeout=300, check=False)
    if proc.returncode not in ok:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {proc.stderr.decode(errors='replace').strip()[:300]}")
    return proc


def _emit(event: dict) -> None:
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


def _ancestor(repo: str, a: str, b: str) -> bool:
    return _git(repo, "merge-base", "--is-ancestor", a, b, ok=(0, 1)).returncode == 0


def merge(repo: str, base: str, shas: list[str]) -> tuple[str | None, list[str]]:
    """(merged commit, []) or (None, conflicting paths). Writes objects only; moves no ref."""
    current = base
    for sha in shas:
        if _ancestor(repo, sha, current):
            continue
        if _ancestor(repo, current, sha):
            current = sha
            continue
        proc = _git(repo, "merge-tree", "--write-tree", "--no-messages", current, sha, ok=(0, 1))
        lines = proc.stdout.decode().splitlines()
        if proc.returncode == 1:
            return None, sorted({line.split("\t", 1)[1] for line in lines[1:] if "\t" in line})
        env = dict(os.environ, GIT_AUTHOR_NAME="CLIVE integrator", GIT_AUTHOR_EMAIL="clive@localhost",
                   GIT_COMMITTER_NAME="CLIVE integrator", GIT_COMMITTER_EMAIL="clive@localhost")
        current = subprocess.run(["git", "-C", repo, "commit-tree", lines[0], "-p", current, "-p", sha,
                                  "-m", f"integrate {sha}"], capture_output=True, env=env, check=True,
                                 timeout=60).stdout.decode().strip()
    return current, []


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--session-id", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--job", required=True)
    args = p.parse_args(argv)
    job = json.loads(args.job)
    _emit({"type": "system", "subtype": "init", "session_id": args.session_id, "cwd": os.getcwd(),
           "tools": [INTEGRATOR_TOOL], "mcp_servers": [], "plugins": [], "skills": [], "slash_commands": [],
           "permissionMode": None, "model": "deterministic", "apiKeySource": "none"})
    try:
        merged, conflicts = merge(args.repo, job["base"], job["integrate"])
        if conflicts:
            _emit({"type": "result", "subtype": "success", "is_error": False, "session_id": args.session_id,
                   "structured_output": {"status": "blocked", "summary": "the accepted candidates conflict",
                                         "reason": "merge conflict in: " + ", ".join(conflicts)[:1900]}})
            return 0
        changed = _git(args.repo, "diff", "--name-only", "--no-renames", job["base"], merged).stdout.decode().split("\n")
        for i, path in enumerate(p for p in changed if p):
            target = Path(os.getcwd()) / path
            listing = _git(args.repo, "ls-tree", merged, "--", path).stdout.decode().split()
            if not listing:
                target.unlink(missing_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(_git(args.repo, "cat-file", "blob", listing[2]).stdout)
                target.chmod(0o755 if listing[0] == "100755" else 0o644)
            _emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": f"i{i}", "name": "Write",
                                                                 "input": {"file_path": str(target)}}]}})
            _emit({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": f"i{i}"}]}})
        _emit({"type": "result", "subtype": "success", "is_error": False, "session_id": args.session_id,
               "structured_output": {"status": "completed",
                                     "summary": f"merged {len(job['integrate'])} accepted candidate(s) onto "
                                                f"{job['base']} as tree of {merged}"}})
    except Exception as exc:  # noqa: BLE001 — reported as the attempt's result, never swallowed
        _emit({"type": "result", "subtype": "success", "is_error": False, "session_id": args.session_id,
               "structured_output": {"status": "blocked", "summary": "integration could not run",
                                     "reason": str(exc)[:1900]}})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
