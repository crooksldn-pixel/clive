"""One attempt, one isolated workspace: a private clone at the exact base, with no remote.

    <root>/<task_id>/<attempt_id>/        the worker's checkout (its cwd)

The workspace is a ``git clone --local`` of the dispatcher's repository, checked
out detached at the attempt base on a branch of its own, with its remote removed.
So a worker can read and edit its own tree and nothing else: it has no refs of
the canonical checkout, no production checkout, no other attempt's tree and no
remote to push to. CLIVE, not the worker, commits the result and fetches it back
by its exact SHA; the candidate's identity is what git says, never what the
worker reports.

Paths are derived from identifiers the kernel already validated and are checked
again here: a single safe component each, and the resolved path must stay under
the root. A small metadata file inside the clone's ``.git`` binds the workspace to
its task, attempt and base, so after a dispatcher restart the same workspace is
recognised, and a directory that is not that workspace is refused, never reused.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .contracts import validate_exact_sha

__all__ = ["WorkspaceError", "WorkspaceManager", "WorkspaceInfo", "git"]

_COMPONENT = re.compile(r"^[A-Za-z0-9._:-]+$")
META = "clive-workspace.json"
COMMITTER = ("CLIVE dispatcher", "dispatcher@clive.invalid")


class WorkspaceError(RuntimeError):
    """A workspace could not be created, recognised or read. Deterministic, never retried."""


def git(cwd: Path, *args: str, check: bool = True, timeout: int = 120) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
        env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(cwd), "GIT_CONFIG_NOSYSTEM": "1",
             "GIT_TERMINAL_PROMPT": "0", "LANG": "C.UTF-8"},
    )
    if check and proc.returncode != 0:
        raise WorkspaceError(f"git {' '.join(args[:3])} failed in {cwd}: {(proc.stderr or proc.stdout).strip()[:400]}")
    return proc.stdout.strip()


def _component(value: str, what: str) -> str:
    if not _COMPONENT.fullmatch(value) or value in {".", ".."}:
        raise WorkspaceError(f"{what} {value!r} is not a safe single path component")
    return value


@dataclass(frozen=True)
class WorkspaceInfo:
    path: Path
    task_id: str
    attempt_id: str
    base_sha: str
    branch: str


class WorkspaceManager:
    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()

    def path_for(self, task_id: str, attempt_id: str) -> Path:
        path = (self.root / _component(task_id, "task id") / _component(attempt_id, "attempt id")).resolve()
        if self.root not in path.parents:
            raise WorkspaceError(f"workspace {path} escapes the workspace root {self.root}")
        return path

    @staticmethod
    def branch_for(attempt_id: str) -> str:
        return f"clive/attempt/{_component(attempt_id, 'attempt id')}"

    def create(self, repo: Path, *, task_id: str, attempt_id: str, base_sha: str) -> WorkspaceInfo:
        """A fresh clone at ``base_sha``, or the same workspace recognised after a restart."""
        base_sha = validate_exact_sha(base_sha)
        path = self.path_for(task_id, attempt_id)
        branch = self.branch_for(attempt_id)
        if path.exists():
            info = self.recognise(path)
            if (info.task_id, info.attempt_id, info.base_sha) != (task_id, attempt_id, base_sha):
                raise WorkspaceError(f"{path} belongs to {info.task_id}/{info.attempt_id} at {info.base_sha}; refused")
            return info
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = path.with_name(path.name + ".creating")
        if staging.exists():
            shutil.rmtree(staging)  # our own half-made clone from an interrupted create; never a live tree
        git(path.parent, "clone", "--quiet", "--local", "--no-checkout", str(Path(repo).resolve()), str(staging))
        git(staging, "checkout", "--quiet", "--detach", base_sha)
        git(staging, "switch", "--quiet", "-c", branch)
        git(staging, "remote", "remove", "origin")
        (staging / ".git" / META).write_text(
            json.dumps({"task_id": task_id, "attempt_id": attempt_id, "base_sha": base_sha, "branch": branch},
                       sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.rename(path)
        return WorkspaceInfo(path, task_id, attempt_id, base_sha, branch)

    def recognise(self, path: Path) -> WorkspaceInfo:
        meta = Path(path) / ".git" / META
        if not meta.is_file():
            raise WorkspaceError(f"{path} exists but is not a CLIVE attempt workspace; refused")
        data = json.loads(meta.read_text(encoding="utf-8"))
        return WorkspaceInfo(Path(path), data["task_id"], data["attempt_id"], data["base_sha"], data["branch"])

    # ---- facts, all from git -------------------------------------------------
    @staticmethod
    def head(path: Path) -> str:
        return validate_exact_sha(git(path, "rev-parse", "HEAD"))

    @staticmethod
    def dirty_paths(path: Path) -> tuple[str, ...]:
        out = git(path, "status", "--porcelain", "-z", "--untracked-files=all")
        entries = [e for e in out.split("\0") if e]
        return tuple(sorted(e[3:] for e in entries if len(e) > 3))

    @staticmethod
    def fast_forward_to(path: Path, sha: str) -> None:
        """Move the attempt branch forward to ``sha`` (a repair starts from the rejected candidate)."""
        sha = validate_exact_sha(sha)
        git(path, "merge", "--quiet", "--ff-only", sha)
        if WorkspaceManager.head(path) != sha:
            raise WorkspaceError(f"workspace {path} did not reach {sha}")

    @staticmethod
    def commit_all(path: Path, *, message: str, author: str) -> str | None:
        """CLIVE commits whatever the worker left in the tree. None when nothing changed."""
        git(path, "add", "-A")
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(path)).returncode == 0:
            return None
        name, email = COMMITTER
        git(path, "-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "--quiet",
            "--no-verify", f"--author={author} <worker@clive.invalid>", "-m", message)
        return WorkspaceManager.head(path)

    @staticmethod
    def ingest(repo: Path, workspace: Path, *, branch: str, sha: str) -> str:
        """Fetch the workspace branch into the repository and prove it is exactly ``sha``."""
        sha = validate_exact_sha(sha)
        ref = f"refs/clive/candidates/{branch.rsplit('/', 1)[-1]}"
        git(repo, "fetch", "--quiet", "--no-tags", str(Path(workspace).resolve()), f"+refs/heads/{branch}:{ref}")
        got = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
        if got != sha:
            raise WorkspaceError(f"ingested {ref} is {got}, not the candidate {sha}")
        return got
