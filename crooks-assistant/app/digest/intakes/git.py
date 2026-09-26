"""Intake handler: a git repository by https URL, pinned to one commit.

    intake("https://github.com/owner/repo", root, ref="v1.2.0")

Nothing from the repository is ever run, and nothing about this machine's git reaches it:

1. The URL must be https, with no credentials, fragment or private host (intake.https_url); the
   reference, when given, must be a plain branch, tag or full commit SHA (check_ref), never an
   option, a refspec or a revision expression.
2. A fresh bare repository is made in the intake's private scratch directory, from no template.
   Its info/attributes unsets, at the highest precedence git has, every attribute that would
   change what `git archive` writes — export-subst, export-ignore, ident, filter, text, eol,
   working-tree-encoding — so a .gitattributes in the repository changes nothing.
3. Every git command runs from an environment built from nothing: no system or global config
   (so no filter, hook, credential helper, fsmonitor, alias or url rewrite of this machine's),
   HOME in scratch (so no ~/.netrc is sent), no terminal prompt, LFS smudging off, and the
   hardening of HARDENED_CONFIG on the command line: hooks at /dev/null, every protocol but
   https refused (file and ext named too), no redirects, no submodules, fsck on every object
   received (which also refuses trees with '..' or '.git' in them), no automatic maintenance.
   Proxy and certificate settings are passed through, and nothing else.
4. The fetch — the only network step, injectable as the "git" fetcher — takes the one commit
   (depth 1, no tags), with the size of any file git writes bounded by
   Limits.max_download_bytes and the whole fetch by Limits.timeout.
5. The commit's SHA is the pin. Its tree is listed (`git ls-tree -r -l`) and checked against
   the limits before anything is unpacked, then materialised by `git archive <sha>` streamed
   straight through the archive handler's tar unpacker, and every file and link written is
   checked against the listing by its git object id: the quarantined copy is the commit's tree,
   byte for byte, or the intake fails as UnsafeArtifact.

Submodules are not fetched (each is noted with the commit it names), and Git LFS files stay as
the pointer files the commit holds (counted in a note)."""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import threading
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit

from app.digest.intake import (
    FetchFailed,
    IntakeError,
    LimitExceeded,
    Limits,
    Pinned,
    Request,
    SourceRefused,
    TreeWriter,
    UnsafeArtifact,
    https_url,
    shown,
)
from app.digest.intakes.archive import unpack_tar_stream

NAME = "git"
ORIGIN_KIND = "git"

PINNED = "refs/intake/pinned"
GIT_HOSTS = frozenset(("github.com", "gitlab.com", "codeberg.org", "bitbucket.org", "git.sr.ht"))

HARDENED_CONFIG: tuple[tuple[str, str], ...] = (
    ("core.hooksPath", "/dev/null"),
    ("core.fsmonitor", "false"),
    ("core.attributesFile", "/dev/null"),
    ("core.askPass", ""),
    ("credential.helper", ""),
    ("protocol.allow", "never"),
    ("protocol.https.allow", "always"),
    ("protocol.file.allow", "never"),
    ("protocol.ext.allow", "never"),
    ("http.followRedirects", "false"),
    ("transfer.fsckObjects", "true"),
    ("fetch.fsckObjects", "true"),
    ("submodule.recurse", "false"),
    ("fetch.recurseSubmodules", "false"),
    ("gc.auto", "0"),
    ("maintenance.auto", "false"),
)
# Unset, at info/attributes' highest precedence, everything that makes git archive write other
# than the committed bytes, or run a filter.
NEUTRAL_ATTRIBUTES = "* -export-subst -export-ignore -ident -filter -text -eol -working-tree-encoding\n"
# Passed through from the calling environment: the way out to the network, and nothing else.
PASSED_THROUGH = (
    "PATH", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy",
    "NO_PROXY", "no_proxy", "GIT_SSL_CAINFO", "GIT_SSL_CAPATH", "SSL_CERT_FILE", "SSL_CERT_DIR",
    "CURL_CA_BUNDLE",
)
_SHA = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_REF = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._/-]{0,254}")
_LS_TREE = re.compile(rb"(\d{6}) (blob|commit|tree) ([0-9a-f]{40,64}) +(\d+|-)\t(.*)", re.S)
_LFS_POINTER = b"version https://git-lfs.github.com/spec/v1"
_MAX_LISTING = 64 << 20
_STDERR_TAIL = 600
_DRAIN = 1 << 20                 # bytes a tar may still hold after its end marker


def claims(request: Request) -> int:
    try:
        url = urlsplit(https_url(request.source))
    except SourceRefused:
        return 0
    segments = [part for part in url.path.split("/") if part]
    if segments and segments[-1].endswith(".git"):
        return 60
    if (url.hostname or "") in GIT_HOSTS and len(segments) == 2:
        return 60
    return 0


def check_ref(ref: str | None) -> str | None:
    """The reference, if it is a plain branch or tag name or a full commit SHA; SourceRefused
    for anything git could read as an option, a refspec or a revision expression."""
    if ref is None:
        return None
    if (
        not isinstance(ref, str) or not _REF.fullmatch(ref) or ".." in ref or "//" in ref
        or ref.endswith(("/", ".", ".lock")) or "/." in ref
    ):
        raise SourceRefused(
            f"{shown(ref)} is not a plain branch, tag or commit SHA (letters, digits, '.', '_', '-' and '/')"
        )
    return ref


class Git:
    """git, run hardened against one bare repository (see the module's docstring)."""

    def __init__(self, git_dir: Path, home: Path, *, executable: str = "git") -> None:
        self.git_dir = Path(git_dir)
        self.home = Path(home)
        self.executable = executable

    def command(self, args: Sequence[str]) -> list[str]:
        hardening = [part for key, value in HARDENED_CONFIG for part in ("-c", f"{key}={value}")]
        return [self.executable, f"--git-dir={self.git_dir}", *hardening, *args]

    def environment(self) -> dict[str, str]:
        env = {key: os.environ[key] for key in PASSED_THROUGH if key in os.environ}
        env.setdefault("PATH", os.defpath)
        env.update({
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_PROTOCOL_FROM_USER": "0",
            "GIT_ALLOW_PROTOCOL": "https",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_ATTR_NOSYSTEM": "1",
            "LC_ALL": "C",
        })
        return env

    def init(self) -> None:
        """A bare repository from no template, its attributes neutralised."""
        self.git_dir.parent.mkdir(parents=True, exist_ok=True)
        self.run(["init", "--quiet", "--bare", "--template=", str(self.git_dir)], timeout=60, git_dir=False)
        info = self.git_dir / "info"
        info.mkdir(exist_ok=True)
        (info / "attributes").write_text(NEUTRAL_ATTRIBUTES, encoding="ascii")

    def run(self, args: Sequence[str], *, timeout: float, max_file_bytes: int | None = None,
            max_output: int = _MAX_LISTING, git_dir: bool = True) -> bytes:
        command = self.command(args) if git_dir else [self.executable, *self.command(args)[2:]]
        limit = _file_size_limit(max_file_bytes) if max_file_bytes else None
        try:
            done = subprocess.run(
                command, env=self.environment(), cwd=self.home, stdin=subprocess.DEVNULL,
                capture_output=True, timeout=timeout, check=False, preexec_fn=limit,
            )
        except subprocess.TimeoutExpired:
            raise FetchFailed(f"git {args[0]} took longer than {timeout:g} seconds") from None
        except FileNotFoundError:
            raise IntakeError("git is not installed, so no repository can be taken in") from None
        if len(done.stdout) > max_output:
            raise LimitExceeded(f"git {args[0]} said more than {max_output} bytes")
        if done.returncode != 0:
            raise FetchFailed(f"git {args[0]} failed ({_why(done.returncode)}): {_tail(done.stderr)}")
        return done.stdout

    @contextlib.contextmanager
    def stream(self, args: Sequence[str], *, timeout: float) -> Iterator[BinaryIO]:
        """git's output as a stream. Past timeout the process is killed; if the reader stops
        early it is killed; otherwise what is left (a tar's padding) is drained, bounded, and
        git must have succeeded."""
        errors = open(self.home / "stream.err", "w+b")  # noqa: SIM115 - closed below
        process = subprocess.Popen(
            self.command(args), env=self.environment(), cwd=self.home, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=errors,
        )
        expired = threading.Event()

        def expire() -> None:
            expired.set()
            process.kill()

        timer = threading.Timer(timeout, expire)
        timer.start()
        assert process.stdout is not None
        try:
            yield process.stdout
            left = process.stdout.read(_DRAIN + 1)
            if len(left) > _DRAIN:
                raise UnsafeArtifact(f"git {args[0]} wrote more after the end of its archive")
        except BaseException:
            process.kill()
            raise
        finally:
            timer.cancel()
            process.stdout.close()
            code = process.wait()
            errors.seek(0)
            message = errors.read()
            errors.close()
        if expired.is_set():
            raise FetchFailed(f"git {args[0]} took longer than {timeout:g} seconds")
        if code != 0:
            raise FetchFailed(f"git {args[0]} failed ({_why(code)}): {_tail(message)}")


def _file_size_limit(limit: int):
    def apply() -> None:
        import resource

        resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
    return apply


def _why(code: int) -> str:
    if code == -25 or code == 128 + 25:
        return "a file it wrote passed the download limit"
    if code < 0:
        return f"stopped by signal {-code}"
    return f"exit {code}"


def _tail(stderr: bytes) -> str:
    text = stderr.decode("utf-8", "replace").strip()
    return shown(text[-_STDERR_TAIL:], limit=_STDERR_TAIL) or "no message"


def live_fetch(url: str, ref: str | None, git: Git, limits: Limits) -> None:
    """Fetch the one commit url names at ref (HEAD by default) into git's repository as PINNED."""
    git.run(
        ["fetch", "--quiet", "--depth=1", "--no-tags", "--no-recurse-submodules",
         "--no-write-fetch-head", "--no-auto-maintenance", "--end-of-options",
         url, f"{ref or 'HEAD'}:{PINNED}"],
        timeout=limits.timeout, max_file_bytes=limits.max_download_bytes,
    )


def materialise(request: Request, writer: TreeWriter) -> Pinned:
    url = https_url(request.source)
    ref = check_ref(request.ref)
    if shutil.which("git") is None:
        raise IntakeError("git is not installed, so no repository can be taken in")
    assert request.scratch is not None
    limits = request.limits
    git = Git(request.scratch / "repo.git", request.scratch)
    git.init()
    fetch = request.fetcher(NAME, live_fetch)
    fetch(url, ref, git, limits)
    sha = git.run(["rev-parse", "--verify", "--quiet", "--end-of-options", f"{PINNED}^{{commit}}"],
                  timeout=60).decode("ascii", "replace").strip()
    if not _SHA.fullmatch(sha):
        raise FetchFailed(f"the fetched reference does not name a commit ({shown(sha)})")
    notes: list[str] = []
    if ref is not None and _SHA.fullmatch(ref) and ref != sha:
        notes.append(f"the reference {ref} names a tag; pinned to its commit")
    object_format = git.run(["rev-parse", "--show-object-format"], timeout=60).decode("ascii").strip()
    if object_format not in ("sha1", "sha256"):
        raise FetchFailed(f"the repository uses an object format intake does not know ({shown(object_format)})")
    expected = list_tree(git, sha, limits)
    writer.blob_hash = object_format
    with git.stream(["archive", "--format=tar", "--end-of-options", sha], timeout=limits.timeout) as stream:
        unpack_tar_stream(stream, writer)
    notes.extend(verify(writer, expected, sha))
    return Pinned(origin=url, pinned_ref=sha, notes=tuple(notes))


def list_tree(git: Git, sha: str, limits: Limits) -> dict[str, tuple[str, str, str, int]]:
    """The commit's tree, path -> (mode, type, object id, size), checked against the limits
    before anything is unpacked."""
    listing = git.run(["ls-tree", "-r", "-z", "-l", "--full-tree", "--end-of-options", sha], timeout=120)
    expected: dict[str, tuple[str, str, str, int]] = {}
    total = 0
    for record in listing.split(b"\x00"):
        if not record:
            continue
        match = _LS_TREE.fullmatch(record)
        if match is None:
            raise FetchFailed("git ls-tree said something intake cannot read")
        mode, kind, oid, size, path = match.groups()
        amount = int(size) if size != b"-" else 0
        total += amount
        expected[os.fsdecode(path)] = (mode.decode(), kind.decode(), oid.decode(), amount)
    if len(expected) > limits.max_entries:
        raise LimitExceeded(f"the commit has {len(expected)} files, more than the {limits.max_entries} allowed")
    if total > limits.max_total_bytes:
        raise LimitExceeded(f"the commit holds {total} bytes, over the {limits.max_total_bytes}-byte limit")
    return expected


def verify(writer: TreeWriter, expected: dict[str, tuple[str, str, str, int]], sha: str) -> list[str]:
    """Check what was written against the commit's tree, object id by object id; UnsafeArtifact
    on any difference. Returns notes on submodules and Git LFS pointers."""
    problems: list[str] = []
    submodules: list[str] = []
    for path, (mode, kind, oid, _size) in sorted(expected.items()):
        entry = writer.entries.get(path)
        if kind == "commit":
            submodules.append(f"{path} at {oid}")
            if entry is not None and entry.kind not in ("dir",):
                problems.append(path)
            continue
        if entry is None:
            problems.append(path)
        elif mode == "120000":
            if entry.kind not in ("link", "withheld") or entry.blob_id != oid:
                problems.append(path)
        elif entry.kind != "file" or entry.blob_id != oid or entry.executable != (mode == "100755"):
            problems.append(path)
    for path, entry in writer.entries.items():
        if entry.kind in ("file", "link") and path not in expected:
            problems.append(path)
    if problems:
        raise UnsafeArtifact(
            f"the unpacked tree is not commit {sha}'s: {len(problems)} difference(s), the first at {shown(sorted(problems)[0])}"
        )
    notes = [f"submodule not fetched: {shown(item)}" for item in submodules[:20]]
    if len(submodules) > 20:
        notes.append(f"and {len(submodules) - 20} more submodules not fetched")
    pointers = sum(1 for path, entry in writer.entries.items() if entry.kind == "file" and _is_lfs_pointer(writer, path, entry.size))
    if pointers:
        notes.append(f"{pointers} Git LFS pointer file(s) kept as pointers: their content was not fetched")
    return notes


def _is_lfs_pointer(writer: TreeWriter, path: str, size: int) -> bool:
    if size > 1024:
        return False
    try:
        with open(os.path.join(os.fsencode(writer.root), os.fsencode(path)), "rb") as reader:
            return reader.read(len(_LFS_POINTER)) == _LFS_POINTER
    except OSError:
        return False
