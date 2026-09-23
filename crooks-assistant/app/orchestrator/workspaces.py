"""One attempt, one isolated workspace: a plain tree the worker edits, and git metadata it cannot reach.

    <root>/<task_id>/<attempt_id>/        the worker's tree (its cwd); no .git of CLIVE's inside
    <root>/<task_id>/<attempt_id>.git/    the attempt's git directory (CLIVE only)

The git directory is a bare ``git clone --local`` of the dispatcher's repository
with its remote removed, used with an explicit ``--work-tree``. It lives beside the
tree, not in it: the worker's file tools are confined to its cwd, so nothing the
worker writes can reach the metadata CLIVE later trusts. Anything the worker does
put in its tree (a ``.git`` directory or file, hooks, a config naming an fsmonitor
command) is inert: every CLIVE git command names ``--git-dir`` and ``--work-tree``
explicitly, ignores system and global config, and disables hooks and fsmonitor,
and git never adds a path named ``.git``.

CLIVE, not the worker, commits the result and fetches it back by its exact SHA;
the candidate's identity is what git says, never what the worker reports. Checks
never run in this tree: ``export`` writes a fresh copy of the committed candidate
for the sandbox (see ``checks.py``).

Paths are derived from identifiers the kernel already validated and are checked
again here: a single safe component each, and the resolved path must stay under
the root. A metadata file inside the git directory binds the workspace to its task,
attempt and base, so after a dispatcher restart the same workspace is recognised,
and a directory that is not that workspace is refused, never reused.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .contracts import validate_exact_sha

__all__ = ["WorkspaceError", "WorkspaceInfo", "WorkspaceManager", "git"]

_COMPONENT = re.compile(r"^[A-Za-z0-9._:-]+$")
META = "clive-workspace.json"
COMMITTER = ("CLIVE dispatcher", "dispatcher@clive.invalid")
# Configuration CLIVE forces on every git command that touches an attempt's metadata or tree.
_SAFE = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false",
         "-c", "safe.directory=*", "-c", "protocol.file.allow=always")


class WorkspaceError(RuntimeError):
    """A workspace could not be created, recognised or read. Deterministic, never retried."""


def _env(home: Path) -> dict[str, str]:
    return {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "LANG": "C.UTF-8"}


def git(cwd: Path, *args: str, check: bool = True, timeout: int = 120, env: dict | None = None) -> str:
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
                          env=env or _env(Path(cwd)))
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
    git_dir: Path
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
    def git_dir_for(path: Path) -> Path:
        return Path(path).with_name(Path(path).name + ".git")

    @staticmethod
    def branch_for(attempt_id: str) -> str:
        return f"clive/attempt/{_component(attempt_id, 'attempt id')}"

    @staticmethod
    def wgit(info_or_path, *args: str, check: bool = True) -> str:
        """A git command on an attempt: explicit git dir and work tree, no hooks, no fsmonitor, no user config."""
        path = Path(info_or_path.path if isinstance(info_or_path, WorkspaceInfo) else info_or_path)
        gd = WorkspaceManager.git_dir_for(path)
        return git(gd, *_SAFE, f"--git-dir={gd}", f"--work-tree={path}", *args, check=check, env=_env(gd))

    def create(self, repo: Path, *, task_id: str, attempt_id: str, base_sha: str) -> WorkspaceInfo:
        """A fresh tree at ``base_sha`` with its git directory beside it, or the same one after a restart."""
        base_sha = validate_exact_sha(base_sha)
        path = self.path_for(task_id, attempt_id)
        gd = self.git_dir_for(path)
        branch = self.branch_for(attempt_id)
        if path.exists() or gd.exists():
            info = self.recognise(path)
            if (info.task_id, info.attempt_id, info.base_sha) != (task_id, attempt_id, base_sha):
                raise WorkspaceError(f"{path} belongs to {info.task_id}/{info.attempt_id} at {info.base_sha}; refused")
            return info
        path.parent.mkdir(parents=True, exist_ok=True)
        staging_tree, staging_gd = path.with_name(path.name + ".creating"), gd.with_name(gd.name + ".creating")
        for leftover in (staging_tree, staging_gd):  # our own half-made attempt from an interrupted create
            if leftover.exists():
                shutil.rmtree(leftover)
        git(path.parent, *_SAFE, "clone", "--quiet", "--bare", "--local", str(Path(repo).resolve()), str(staging_gd))
        git(staging_gd, *_SAFE, f"--git-dir={staging_gd}", "remote", "remove", "origin", env=_env(staging_gd))
        git(staging_gd, *_SAFE, f"--git-dir={staging_gd}", "config", "core.bare", "false", env=_env(staging_gd))
        staging_tree.mkdir()
        run = lambda *a: git(staging_gd, *_SAFE, f"--git-dir={staging_gd}", f"--work-tree={staging_tree}", *a,  # noqa: E731
                             env=_env(staging_gd))
        run("checkout", "--quiet", "--detach", base_sha)
        run("switch", "--quiet", "-c", branch)
        (staging_gd / META).write_text(
            json.dumps({"task_id": task_id, "attempt_id": attempt_id, "base_sha": base_sha, "branch": branch},
                       sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging_gd.rename(gd)
        staging_tree.rename(path)
        return WorkspaceInfo(path, gd, task_id, attempt_id, base_sha, branch)

    def recognise(self, path: Path) -> WorkspaceInfo:
        gd = self.git_dir_for(path)
        meta = gd / META
        if not meta.is_file() or not Path(path).is_dir():
            raise WorkspaceError(f"{path} is not a CLIVE attempt workspace (no {meta}); refused")
        data = json.loads(meta.read_text(encoding="utf-8"))
        return WorkspaceInfo(Path(path), gd, data["task_id"], data["attempt_id"], data["base_sha"], data["branch"])

    # ---- facts, all from git -------------------------------------------------
    @staticmethod
    def head(path: Path) -> str:
        return validate_exact_sha(WorkspaceManager.wgit(path, "rev-parse", "HEAD"))

    @staticmethod
    def dirty_paths(path: Path) -> tuple[str, ...]:
        out = WorkspaceManager.wgit(path, "status", "--porcelain", "-z", "--untracked-files=all")
        entries = [e for e in out.split("\0") if e]
        return tuple(sorted(e[3:] for e in entries if len(e) > 3))

    @staticmethod
    def fast_forward_to(path: Path, sha: str) -> None:
        """Move the attempt branch forward to ``sha`` (a repair starts from the rejected candidate)."""
        sha = validate_exact_sha(sha)
        WorkspaceManager.wgit(path, "merge", "--quiet", "--ff-only", sha)
        if WorkspaceManager.head(path) != sha:
            raise WorkspaceError(f"workspace {path} did not reach {sha}")

    @staticmethod
    def commit_all(path: Path, *, message: str, author: str) -> str | None:
        """CLIVE commits whatever the worker left in the tree. None when nothing changed."""
        gd = WorkspaceManager.git_dir_for(path)
        WorkspaceManager.wgit(path, "add", "-A")
        staged = subprocess.run(["git", *_SAFE, f"--git-dir={gd}", f"--work-tree={path}", "diff", "--cached", "--quiet"],
                                cwd=str(gd), env=_env(gd), capture_output=True)
        if staged.returncode == 0:
            return None
        name, email = COMMITTER
        WorkspaceManager.wgit(path, "-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "--quiet",
                              "--no-verify", f"--author={author} <worker@clive.invalid>", "-m", message)
        return WorkspaceManager.head(path)

    @staticmethod
    def export(path: Path, sha: str, destination: Path) -> Path:
        """A fresh copy of exactly the committed tree at ``sha``: what a check runs on, never the live tree."""
        sha = validate_exact_sha(sha)
        destination = Path(destination)
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        gd = WorkspaceManager.git_dir_for(path)
        index = destination.with_name(destination.name + ".index")
        env = {**_env(gd), "GIT_INDEX_FILE": str(index)}
        try:
            git(gd, *_SAFE, f"--git-dir={gd}", f"--work-tree={destination}", "read-tree", sha, env=env)
            git(gd, *_SAFE, f"--git-dir={gd}", f"--work-tree={destination}", "checkout-index", "--all", env=env)
        finally:
            index.unlink(missing_ok=True)
        os.chmod(destination, 0o755)
        return destination

    @staticmethod
    def ingest(repo: Path, workspace: Path, *, branch: str, sha: str) -> str:
        """Fetch the attempt branch into the repository and prove it is exactly ``sha``."""
        sha = validate_exact_sha(sha)
        ref = f"refs/clive/candidates/{branch.rsplit('/', 1)[-1]}"
        gd = WorkspaceManager.git_dir_for(workspace)
        git(repo, *_SAFE, "fetch", "--quiet", "--no-tags", str(gd.resolve()), f"+refs/heads/{branch}:{ref}")
        got = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
        if got != sha:
            raise WorkspaceError(f"ingested {ref} is {got}, not the candidate {sha}")
        return got
