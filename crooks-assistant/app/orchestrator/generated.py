"""Generated files are the loop's job, not the builder's (OWNER_DECISIONS_2026-09-30, "go").

Some checked-in files are derived from the rest of the tree and pinned by a test to their
generator's output: ``docs/phase4/TOOL_MATRIX.md`` is ``experience/tool_matrix.write()``'s,
and ``tests/test_tool_matrix.py::test_the_checked_in_document_is_the_generated_one`` fails
whenever they differ. Any new test file changes it, and a builder may not regenerate it, so on
30 September six of seven builds were blocked by that one test and nothing else.

The repository declares its generators in ``crooks-assistant/config/generated_files.json``
(a protected path: no objective can change it). Each entry is a name, an argv, a cwd and the
output paths the generator writes, all repository-root relative except the cwd's use:

    {"schema": "clive.generated_files.v1",
     "generators": [{"name": "tool-matrix",
                     "argv": ["{python}", "-c", "... tool_matrix.write()"],
                     "cwd": "crooks-assistant",
                     "outputs": ["crooks-assistant/docs/phase4/TOOL_MATRIX.md"]}]}

``{python}`` stands for the builders' check interpreter, the one the objective's declared
checks name. This module only reads and validates the declaration and compares trees; the
dispatcher decides where the declaration comes from (always the task's base commit, never the
candidate), runs each generator in the check sandbox on a fresh export of the candidate, and
commits only the declared outputs (``Dispatcher._regenerate``).

Nothing here runs a generator, follows a symbolic link, or trusts a tree a generator touched:
a tree is read with ``lstat`` and ``O_NOFOLLOW`` only, and a declared output is taken back only
when every component on its way is a real directory and the output itself a regular file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .contracts import validate_exact_sha

__all__ = [
    "GENERATED_FILES",
    "GENERATED_FILES_SCHEMA",
    "PYTHON",
    "GeneratedFilesError",
    "Generator",
    "changed_files",
    "declared_at",
    "parse_generators",
    "read_regular",
    "tree_manifest",
]

GENERATED_FILES = "crooks-assistant/config/generated_files.json"
GENERATED_FILES_SCHEMA = "clive.generated_files.v1"
PYTHON = "{python}"                  # an argv word the dispatcher replaces with the builders' check interpreter
MAX_DECLARATION_BYTES = 64 * 1024
MAX_GENERATORS = 20
MAX_OUTPUTS = 20
MAX_ARGV = 64
MAX_OUTPUT_BYTES = 16 * 1024 * 1024  # a declared output larger than this is not taken back
_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


class GeneratedFilesError(ValueError):
    """The declaration is not one the loop runs. The task blocks with this reason; nothing runs."""


@dataclass(frozen=True)
class Generator:
    name: str
    argv: tuple[str, ...]
    cwd: str
    outputs: tuple[str, ...]
    timeout_s: int = 600

    def command(self, python: str) -> tuple[str, ...]:
        """The argv with ``{python}`` (a whole word only) replaced by the builders' check interpreter."""
        return tuple(python if word == PYTHON else word for word in self.argv)

    def record(self) -> dict:
        return {"name": self.name, "argv": list(self.argv), "cwd": self.cwd, "outputs": list(self.outputs),
                "timeout_s": self.timeout_s}


def _relative(value: object, what: str, *, allow_dot: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > 300:
        raise GeneratedFilesError(f"{what} must be a repository-relative path")
    if allow_dot and value == ".":
        return value
    parts = value.split("/")
    if value.startswith("/") or "\\" in value or any(p in ("", ".", "..") for p in parts) or "\0" in value:
        raise GeneratedFilesError(f"{what} {value!r} is not a repository-relative path without '.', '..' or '//'")
    return value


def parse_generators(payload: bytes) -> tuple[Generator, ...]:
    """The generators a declaration names, each validated; any doubt refuses the whole declaration."""
    if len(payload) > MAX_DECLARATION_BYTES:
        raise GeneratedFilesError(f"{GENERATED_FILES} is larger than {MAX_DECLARATION_BYTES} bytes")
    try:
        document = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise GeneratedFilesError(f"{GENERATED_FILES} is not JSON") from None
    if not isinstance(document, dict) or set(document) != {"schema", "generators"} \
            or document.get("schema") != GENERATED_FILES_SCHEMA or not isinstance(document["generators"], list):
        raise GeneratedFilesError(f"{GENERATED_FILES} is not a {GENERATED_FILES_SCHEMA} document "
                                  "(exactly `schema` and a `generators` list)")
    if len(document["generators"]) > MAX_GENERATORS:
        raise GeneratedFilesError(f"{GENERATED_FILES} declares more than {MAX_GENERATORS} generators")
    out: list[Generator] = []
    seen_outputs: set[str] = set()
    for index, raw in enumerate(document["generators"]):
        where = f"generator {index}"
        if not isinstance(raw, dict) or not {"name", "argv", "cwd", "outputs"} <= set(raw) \
                or not set(raw) <= {"name", "argv", "cwd", "outputs", "timeout_s"}:
            raise GeneratedFilesError(f"{where} must have exactly name, argv, cwd, outputs and optionally timeout_s")
        name = raw["name"]
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise GeneratedFilesError(f"{where}: its name must match {_NAME.pattern}")
        if any(g.name == name for g in out):
            raise GeneratedFilesError(f"generator {name!r} is declared twice")
        argv = raw["argv"]
        if not isinstance(argv, list) or not argv or len(argv) > MAX_ARGV \
                or not all(isinstance(a, str) and a and len(a) <= 4000 and "\0" not in a for a in argv):
            raise GeneratedFilesError(f"generator {name!r}: argv must be a list of 1-{MAX_ARGV} non-empty words")
        cwd = _relative(raw["cwd"], f"generator {name!r} cwd", allow_dot=True)
        outputs = raw["outputs"]
        if not isinstance(outputs, list) or not outputs or len(outputs) > MAX_OUTPUTS:
            raise GeneratedFilesError(f"generator {name!r}: outputs must list 1-{MAX_OUTPUTS} files")
        cleaned = tuple(_relative(p, f"generator {name!r} output") for p in outputs)
        for path in cleaned:
            if path in seen_outputs:
                raise GeneratedFilesError(f"output {path} is declared twice")
            seen_outputs.add(path)
        timeout = raw.get("timeout_s", 600)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 3600:
            raise GeneratedFilesError(f"generator {name!r}: timeout_s must be 1-3600 seconds")
        out.append(Generator(name=name, argv=tuple(argv), cwd=cwd, outputs=cleaned, timeout_s=timeout))
    return tuple(out)


def declared_at(repo: Path, sha: str) -> bytes | None:
    """The declaration's bytes at exactly commit ``sha`` of the dispatcher's own repository, or None.

    Read from git's object store at a commit the kernel already recorded (a task's base), never from a
    work tree and never from a candidate. A declaration that is not a regular file there is refused."""
    sha = validate_exact_sha(sha)
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
           "HOME": str(repo), "LANG": "C.UTF-8"}
    listing = subprocess.run(["git", "ls-tree", "-z", sha, "--", GENERATED_FILES], cwd=str(repo), env=env,
                             capture_output=True, timeout=60, check=False)
    if listing.returncode != 0:
        raise GeneratedFilesError(f"the repository cannot list {GENERATED_FILES} at {sha}")
    entry = listing.stdout.decode("utf-8", errors="replace").rstrip("\0")
    if not entry:
        return None
    mode, kind, blob = entry.split("\t", 1)[0].split()
    if kind != "blob" or mode not in ("100644", "100755"):
        raise GeneratedFilesError(f"{GENERATED_FILES} at {sha} is not a regular file")
    proc = subprocess.run(["git", "cat-file", "blob", blob], cwd=str(repo), env=env, capture_output=True,
                          timeout=60, check=False)
    if proc.returncode != 0:
        raise GeneratedFilesError(f"{GENERATED_FILES} at {sha} cannot be read")
    return proc.stdout


# ------------------------------------------------------------------ trees a generator touched

def tree_manifest(root: Path) -> dict[str, tuple]:
    """Every non-directory entry under ``root``: (kind, executable, digest or link target), never followed.

    Directories themselves are not entries: a generator that only leaves an empty directory changed no file."""
    root = Path(root)
    out: dict[str, tuple] = {}
    for current, dirs, files in os.walk(root, followlinks=False):
        base = Path(current)
        for name in (*files, *(d for d in dirs if os.path.islink(base / d))):
            path = base / name
            rel = path.relative_to(root).as_posix()
            mode = os.lstat(path).st_mode
            if stat.S_ISLNK(mode):
                out[rel] = ("link", False, os.readlink(path))
            elif stat.S_ISREG(mode):
                out[rel] = ("file", bool(mode & 0o111), _digest(path))
            else:
                out[rel] = ("special", False, stat.S_IFMT(mode))
    return out


def _digest(path: Path) -> str:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    digest = hashlib.sha256()
    with os.fdopen(fd, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def changed_files(before: dict[str, tuple], after: dict[str, tuple]) -> list[str]:
    """The entries that were added, removed or changed in content, kind or executable bit, sorted."""
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


def read_regular(root: Path, rel: str) -> bytes | None:
    """``root/rel``'s bytes when every component below ``root`` is a real directory and ``rel`` a regular
    file of at most ``MAX_OUTPUT_BYTES``; None otherwise. A link anywhere on the way is refused, never followed."""
    parts = rel.split("/")
    if not rel or any(p in ("", ".", "..") for p in parts):
        return None
    current = Path(root)
    for index, part in enumerate(parts):
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except OSError:
            return None
        last = index == len(parts) - 1
        if (not last and not stat.S_ISDIR(mode)) or (last and not stat.S_ISREG(mode)):
            return None
    fd = os.open(current, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as handle:
        data = handle.read(MAX_OUTPUT_BYTES + 1)
    return data if len(data) <= MAX_OUTPUT_BYTES else None
