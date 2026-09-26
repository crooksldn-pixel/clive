"""Intake and quarantine: an artifact is fetched or received, pinned, and copied read-only into a
directory of its own, and nothing it holds is ever run or followed out.

Everything here is offline. The git handler's fetch is injected (a local repository fetched over
file://, which the real fetch refuses), and so is the URL handler's download; everything after
the fetch — resolving the commit, archiving it with attributes neutralised, unpacking, checking
every object id, sealing and settling the copy — is the code that runs for real. The hostile
cases are built by hand: tar and zip entries that climb out, absolute names, links to /etc and
link chains that leave on disk, hard links out, devices and pipes, bombs by ratio, by count and
by header, overlapping and encrypted zips, and a repository whose hooks and .gitattributes
filters must not run."""

from __future__ import annotations

import importlib
import io
import os
import stat
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

import pytest

import app.digest
from app.digest import scan
from app.digest.intake import (
    ArchiveUnreadable,
    FetchFailed,
    IntakeError,
    LimitExceeded,
    Limits,
    NoHandler,
    SourceRefused,
    TreeWriter,
    UnsafeArtifact,
    clean_name,
    discover_handlers,
    https_url,
    intake,
    intake_records,
    remove_tree,
    shown,
)
from app.digest.intakes import git as git_handler
from app.digest.intakes import package as package_handler
from app.digest.intakes import url as url_handler
from app.digest.pipeline import digest, tree_digest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "digest_intake.py"
TAKEN_AT = "2026-09-26T10:00:00+00:00"
HANDLERS = ("archive", "directory", "file", "git", "package", "url")
MIT = (
    "MIT License\n\nCopyright (c) 2026 Example\n\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy\n"
    "of this software and associated documentation files, to deal in the Software.\n"
)
TREE = {
    "README.md": b"# Tally\n\nCounts things.\n",
    "LICENSE": MIT.encode(),
    "src/tally.py": b"def count(items):\n    return len(items)\n",
    "docs/guide.md": b"# Guide\n\n- Always count twice.\n",
}


# --- helpers ------------------------------------------------------------------------------------


def _modes(path: Path) -> list[tuple[str, int]]:
    """Every file and directory under path (and path) with its mode bits, links skipped."""
    found = [(".", stat.S_IMODE(os.lstat(path).st_mode))]
    for folder, dirs, files in os.walk(path):
        for name in dirs + files:
            full = Path(folder) / name
            if not full.is_symlink():
                found.append((str(full.relative_to(path)), stat.S_IMODE(os.lstat(full).st_mode)))
    return found


def _assert_read_only(path: Path) -> None:
    assert all(mode & 0o222 == 0 for _, mode in _modes(path)), _modes(path)


def _files(path: Path) -> dict[str, bytes]:
    out = {}
    for folder, _dirs, files in os.walk(path):
        for name in files:
            full = Path(folder) / name
            if not full.is_symlink():
                out[str(full.relative_to(path))] = full.read_bytes()
    return out


def _clean_root(root: Path) -> None:
    """No copy, staging or work directory was left behind."""
    leftovers = sorted(entry.name for entry in root.iterdir()) if root.exists() else []
    assert leftovers == [], leftovers


def _tar(path: Path, members: list[tuple[tarfile.TarInfo, bytes | None]], mode: str = "w") -> Path:
    with tarfile.open(path, mode, format=tarfile.PAX_FORMAT) as archive:
        for info, data in members:
            if data is not None:
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
            else:
                archive.addfile(info)
    return path


def _member(name: str, kind: bytes = tarfile.REGTYPE, *, link: str = "", mode: int = 0o644) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = link
    info.mode = mode
    return info


def _tree_members(tree: dict[str, bytes]) -> list[tuple[tarfile.TarInfo, bytes | None]]:
    return [(_member(name), data) for name, data in tree.items()]


def _zip(path: Path, entries: list[tuple[zipfile.ZipInfo | str, bytes]], *, deflate: bool = True) -> Path:
    compression = zipfile.ZIP_DEFLATED if deflate else zipfile.ZIP_STORED
    with zipfile.ZipFile(path, "w", compression=compression) as archive:
        for info, data in entries:
            archive.writestr(info, data)
    return path


def _zip_link(name: str, target: str) -> tuple[zipfile.ZipInfo, bytes]:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    return info, target.encode()


def _make_tree(root: Path, tree: dict[str, bytes]) -> Path:
    for name, data in tree.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return root


# --- git, offline -------------------------------------------------------------------------------

GIT_ENV = {
    "PATH": os.environ.get("PATH", os.defpath), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_AUTHOR_DATE": "2026-09-26T10:00:00Z",
    "GIT_COMMITTER_DATE": "2026-09-26T10:00:00Z", "LC_ALL": "C", "HOME": os.devnull,
}


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), "-c", "core.symlinks=true", *args], env=GIT_ENV,
                          capture_output=True, check=True, timeout=60)
    return done.stdout.decode().strip()


def _repo(path: Path, tree: dict[str, bytes], *, links: dict[str, str] | None = None,
          executable: tuple[str, ...] = (), gitlinks: dict[str, str] | None = None) -> str:
    path.mkdir(parents=True)
    _git(path, "init", "--quiet", "--initial-branch=main")
    _git(path, "config", "uploadpack.allowReachableSHA1InWant", "true")
    _make_tree(path, tree)
    for name in executable:
        (path / name).chmod(0o755)
    for name, target in (links or {}).items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, path / name)
    _git(path, "add", "--all")
    for name, sha in (gitlinks or {}).items():
        _git(path, "update-index", "--add", "--cacheinfo", f"160000,{sha},{name}")
    _git(path, "commit", "--quiet", "--no-verify", "-m", "one")
    return _git(path, "rev-parse", "HEAD")


def _local_fetch(origin: Path):
    """The git handler's fetch, from a local repository over file:// — which the real fetch
    refuses — into the repository the handler made."""
    calls = []

    def fetch(url, ref, git, limits):
        calls.append((url, ref))
        env = {**git.environment(), "GIT_ALLOW_PROTOCOL": "file"}
        subprocess.run(
            ["git", f"--git-dir={git.git_dir}", "-c", "protocol.file.allow=always", "fetch", "--quiet",
             "--depth=1", "--no-tags", f"file://{origin}", f"{ref or 'HEAD'}:{git_handler.PINNED}"],
            env=env, capture_output=True, check=True, timeout=60,
        )
    fetch.calls = calls
    return fetch


URL = "https://github.com/example/tally"


def _git_intake(tmp_path: Path, origin: Path, **kwargs):
    return intake(URL, tmp_path / "q", fetchers={"git": _local_fetch(origin)}, taken_at=TAKEN_AT, **kwargs)


def test_a_git_repository_is_pinned_to_its_commit_and_copied_byte_for_byte(tmp_path):
    origin = tmp_path / "origin"
    sha = _repo(origin, {**TREE, "run.sh": b"#!/bin/sh\necho hi\n"}, executable=("run.sh",),
                links={"docs/readme-link.md": "../README.md"})
    taken = _git_intake(tmp_path, origin)
    assert taken.handler == "git"
    assert taken.source.origin == URL and taken.source.origin_kind == "git"
    assert taken.source.pinned_ref == sha
    assert taken.source.licence == "MIT"
    assert taken.source.content_digest == tree_digest(taken.path)
    assert taken.path == tmp_path / "q" / taken.source.artifact_id
    assert _files(taken.path) == {**TREE, "run.sh": b"#!/bin/sh\necho hi\n"}
    assert os.readlink(taken.path / "docs/readme-link.md") == "../README.md"
    assert stat.S_IMODE(os.lstat(taken.path / "run.sh").st_mode) == 0o555
    assert stat.S_IMODE(os.lstat(taken.path / "README.md").st_mode) == 0o444
    _assert_read_only(taken.path)
    assert taken.withheld == () and not taken.reused


def test_a_branch_a_tag_and_a_full_sha_each_pin_their_own_commit(tmp_path):
    origin = tmp_path / "origin"
    first = _repo(origin, {"a.txt": b"one\n"})
    _git(origin, "tag", "v1")
    (origin / "a.txt").write_bytes(b"two\n")
    _git(origin, "commit", "--quiet", "-am", "two")
    _git(origin, "tag", "-a", "v2", "-m", "annotated")
    second = _git(origin, "rev-parse", "HEAD")
    assert _git_intake(tmp_path, origin, ref="main").source.pinned_ref == second
    assert _git_intake(tmp_path, origin, ref="v1").source.pinned_ref == first
    assert _git_intake(tmp_path, origin, ref="v2").source.pinned_ref == second   # peeled
    by_sha = _git_intake(tmp_path, origin, ref=first)
    assert by_sha.source.pinned_ref == first and _files(by_sha.path) == {"a.txt": b"one\n"}


def test_hooks_and_gitattributes_filters_never_run_and_change_nothing(tmp_path, monkeypatch):
    marker = tmp_path / "RAN"
    # This machine's own git config names a filter the repository asks for; the intake must not
    # read it, however it is supplied.
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(f"[filter \"evil\"]\n\tsmudge = touch {marker}; cat\n\trequired = true\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "filter.evil.smudge")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", f"touch {marker}; cat")
    hook = f"#!/bin/sh\ntouch {marker}\n".encode()
    tree = {
        ".gitattributes": b"* filter=evil export-subst\nhidden.txt export-ignore\nid.txt ident\n",
        "a.txt": b"rev $Format:%H$\n",
        "hidden.txt": b"still here\n",
        "id.txt": b"$Id$\n",
        ".githooks/post-checkout": hook,
        ".husky/pre-commit": hook,
        "hooks/post-merge": hook,
    }
    origin = tmp_path / "origin"
    _repo(origin, tree, executable=(".githooks/post-checkout", ".husky/pre-commit", "hooks/post-merge"))
    taken = _git_intake(tmp_path, origin)
    assert not marker.exists()
    assert _files(taken.path) == tree            # no substitution, nothing left out, no filter
    # Even with the filter configured on git's own command line, the neutral attributes win.
    monkeypatch.setattr(git_handler, "HARDENED_CONFIG",
                        (*git_handler.HARDENED_CONFIG, ("filter.evil.smudge", f"touch {marker}; cat")))
    again = intake(URL, tmp_path / "q2", fetchers={"git": _local_fetch(origin)})
    assert not marker.exists() and _files(again.path) == tree


def test_git_runs_from_nothing_but_the_hardening_and_the_way_out(tmp_path, monkeypatch):
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.fsmonitor")
    monkeypatch.setenv("GIT_SSH_COMMAND", "touch /tmp/x")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example.invalid:3128")
    git = git_handler.Git(tmp_path / "repo.git", tmp_path)
    env = git.environment()
    assert "GIT_CONFIG_COUNT" not in env and "GIT_SSH_COMMAND" not in env
    assert env["HTTPS_PROXY"] == "http://proxy.example.invalid:3128"
    assert env["HOME"] == str(tmp_path) and env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["GIT_CONFIG_NOSYSTEM"] == "1" and env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["GIT_LFS_SKIP_SMUDGE"] == "1" and env["GIT_ALLOW_PROTOCOL"] == "https"
    command = " ".join(git.command(["fetch"]))
    for setting in ("core.hooksPath=/dev/null", "protocol.file.allow=never", "protocol.ext.allow=never",
                    "protocol.allow=never", "protocol.https.allow=always", "credential.helper=",
                    "transfer.fsckObjects=true", "submodule.recurse=false", "http.followRedirects=false"):
        assert f"-c {setting}" in command
    git.init()
    assert (tmp_path / "repo.git" / "info" / "attributes").read_text() == git_handler.NEUTRAL_ATTRIBUTES
    assert not (tmp_path / "repo.git" / "hooks").exists()          # no template, so no hooks at all


def test_links_that_leave_the_tree_are_withheld_and_submodules_noted(tmp_path):
    origin = tmp_path / "origin"
    _repo(origin, {"a.txt": b"a\n", "sub/b.txt": b"b\n"},
          links={"etc-link": "/etc/passwd", "up": "../../outside", "sub/l": "..", "chain": "sub/l/sub/l/.."},
          gitlinks={"vendor/lib": "1" * 40})
    taken = _git_intake(tmp_path, origin)
    withheld = dict(taken.withheld)
    assert set(withheld) == {"etc-link", "up", "chain"}
    assert "absolute" in withheld["etc-link"] and "outside" in withheld["up"]
    for name in withheld:
        assert not os.path.lexists(taken.path / name)
    assert os.readlink(taken.path / "sub/l") == ".."          # inside: kept as a link
    assert any("submodule not fetched: vendor/lib" in note for note in taken.notes)


def test_a_tree_that_is_not_the_commits_is_refused_and_nothing_is_left(tmp_path, monkeypatch):
    origin = tmp_path / "origin"
    _repo(origin, TREE)
    real = git_handler.unpack_tar_stream

    def tampered(stream, writer, **kwargs):
        real(stream, writer, **kwargs)
        writer.file("extra.txt", b"not in the commit\n", size=18)

    monkeypatch.setattr(git_handler, "unpack_tar_stream", tampered)
    with pytest.raises(UnsafeArtifact, match="not commit .*extra.txt"):
        _git_intake(tmp_path, origin)
    _clean_root(tmp_path / "q")


def test_a_commit_past_the_limits_is_refused_before_it_is_unpacked(tmp_path):
    origin = tmp_path / "origin"
    _repo(origin, {f"f{index}.txt": b"x\n" for index in range(12)})
    with pytest.raises(LimitExceeded, match="more than the 10 allowed"):
        _git_intake(tmp_path, origin, limits=Limits(max_entries=10))
    _clean_root(tmp_path / "q")


@pytest.mark.parametrize("source", [
    "http://github.com/example/tally",
    "file:///srv/repo.git",
    "ssh://git@github.com/example/tally.git",
    "git://github.com/example/tally.git",
    "ext::sh -c touch% /tmp/pwned",
    "git@github.com:example/tally.git",
    "/srv/repo.git",
    "https://github.com/example/tally#main",
    "https://localhost/repo.git",
    "https://127.0.0.1/repo.git",
    "https://127.1/repo.git",
    "https://2130706433/repo.git",
    "https://10.0.0.8/repo.git",
    "https://169.254.169.254/latest",
    "https://[::1]/repo.git",
    "https://metadata.internal/repo.git",
    "https://github.com/example/tally\nrm",
])
def test_only_public_https_urls_are_fetched(source):
    with pytest.raises(SourceRefused):
        https_url(source)


def test_credentials_in_a_url_are_refused_without_being_repeated():
    secret = "hunter" + "2-" + "not-real"
    with pytest.raises(SourceRefused) as refused:
        https_url("https://someone:" + secret + "@github.com/example/tally.git")
    assert secret not in str(refused.value)


def test_a_plain_public_https_url_is_normalised():
    assert https_url("HTTPS://GitHub.com/example/tally.git") == "https://github.com/example/tally.git"
    assert https_url("https://github.com:443/example/tally") == "https://github.com/example/tally"


@pytest.mark.parametrize("ref", ["-uflag", "main:refs/heads/x", "a..b", "HEAD~1", "v1^{}", "x y", "/abs", "a/", "x.lock", ""])
def test_a_reference_that_is_not_a_plain_name_or_sha_is_refused(ref):
    with pytest.raises(SourceRefused):
        git_handler.check_ref(ref)


def test_plain_references_pass():
    for ref in ("main", "v1.2.3", "feature/new-thing", "release_2026", "a" * 40):
        assert git_handler.check_ref(ref) == ref


def test_a_git_url_is_claimed_by_git_and_another_https_url_by_url():
    handlers, broken = discover_handlers()
    assert broken == () and tuple(handler.module for handler in handlers) == HANDLERS
    from app.digest.intake import Request, choose_handler
    assert choose_handler(Request(URL), handlers).name == "git"
    assert choose_handler(Request("https://example.org/repo.git"), handlers).name == "git"
    assert choose_handler(Request("https://example.org/spec/openapi.yaml"), handlers).name == "url"
    assert choose_handler(Request(URL, kind="url"), handlers).name == "url"
    with pytest.raises(NoHandler, match="no intake handler named"):
        choose_handler(Request(URL, kind="nope"), handlers)
    with pytest.raises(NoHandler):
        choose_handler(Request("ftp://example.org/x"), handlers)


# --- archives -----------------------------------------------------------------------------------


@pytest.mark.parametrize("suffix,mode", [
    (".tar", "w"), (".tar.gz", "w:gz"), (".tgz", "w:gz"), (".tar.bz2", "w:bz2"), (".tar.xz", "w:xz"),
])
def test_every_tar_format_unpacks_to_the_same_tree(tmp_path, suffix, mode):
    archive = _tar(tmp_path / f"tally{suffix}", _tree_members(TREE), mode)
    taken = intake(archive, tmp_path / "q", taken_at=TAKEN_AT)
    assert taken.handler == "archive" and taken.source.origin_kind == "archive"
    assert _files(taken.path) == TREE
    assert taken.source.pinned_ref == "sha256:" + __import__("hashlib").sha256(archive.read_bytes()).hexdigest()
    assert taken.source.licence == "MIT"
    _assert_read_only(taken.path)


def test_a_zip_unpacks_to_the_same_tree_and_the_same_content_digest(tmp_path):
    zipped = intake(_zip(tmp_path / "tally.zip", list(TREE.items())), tmp_path / "q")
    tarred = intake(_tar(tmp_path / "tally.tar", _tree_members(TREE)), tmp_path / "q")
    assert _files(zipped.path) == TREE
    assert zipped.source.content_digest == tarred.source.content_digest
    assert zipped.path == tarred.path            # the same content is the same quarantined copy


@pytest.mark.parametrize("name", ["../evil.txt", "/etc/cron.d/evil", "a/../../evil.txt", "ok/../../../x"])
def test_a_tar_entry_that_climbs_out_is_refused(tmp_path, name):
    archive = _tar(tmp_path / "bad.tar", [(_member("fine.txt"), b"ok"), (_member(name), b"evil")])
    with pytest.raises(UnsafeArtifact, match="outside the quarantine"):
        intake(archive, tmp_path / "q")
    _clean_root(tmp_path / "q")
    assert not (tmp_path / "evil.txt").exists()


def test_tar_links_out_are_withheld_and_links_in_kept(tmp_path):
    members = [
        (_member("real.txt"), b"real"),
        (_member("sub", tarfile.DIRTYPE), None),
        (_member("etc", tarfile.SYMTYPE, link="/etc"), None),
        (_member("passwd", tarfile.SYMTYPE, link="../../../etc/passwd"), None),
        (_member("sub/up", tarfile.SYMTYPE, link=".."), None),
        (_member("chain", tarfile.SYMTYPE, link="sub/up/sub/up/.."), None),
        (_member("loop-a", tarfile.SYMTYPE, link="loop-b/x"), None),
        (_member("loop-b", tarfile.SYMTYPE, link="loop-a/x"), None),
        (_member("inside", tarfile.SYMTYPE, link="real.txt"), None),
    ]
    taken = intake(_tar(tmp_path / "links.tar", members), tmp_path / "q")
    assert set(dict(taken.withheld)) == {"etc", "passwd", "chain", "loop-a", "loop-b"}
    assert os.readlink(taken.path / "inside") == "real.txt"
    assert os.readlink(taken.path / "sub/up") == ".."
    for name in ("etc", "passwd", "chain"):
        assert not os.path.lexists(taken.path / name)


def test_an_entry_written_through_a_link_is_refused(tmp_path):
    members = [
        (_member("lnk", tarfile.SYMTYPE, link="/etc"), None),
        (_member("lnk/cron.d/evil"), b"evil"),
    ]
    with pytest.raises(UnsafeArtifact, match="through a symbolic link"):
        intake(_tar(tmp_path / "through.tar", members), tmp_path / "q")
    inside = [(_member("dir", tarfile.SYMTYPE, link="real"), None), (_member("dir/x"), b"x")]
    with pytest.raises(UnsafeArtifact, match="through a symbolic link"):
        intake(_tar(tmp_path / "through2.tar", inside), tmp_path / "q")
    _clean_root(tmp_path / "q")


def test_hard_links_are_copies_and_one_that_leaves_is_refused(tmp_path):
    members = [(_member("a.txt"), b"shared"), (_member("b.txt", tarfile.LNKTYPE, link="a.txt"), None)]
    taken = intake(_tar(tmp_path / "hard.tar", members), tmp_path / "q")
    assert (taken.path / "b.txt").read_bytes() == b"shared"
    assert os.lstat(taken.path / "b.txt").st_nlink == 1 and os.lstat(taken.path / "a.txt").st_nlink == 1
    out = [(_member("x.txt", tarfile.LNKTYPE, link="../../etc/passwd"), None)]
    with pytest.raises(UnsafeArtifact):
        intake(_tar(tmp_path / "hard-out.tar", out), tmp_path / "q2")
    missing = [(_member("x.txt", tarfile.LNKTYPE, link="nowhere.txt"), None)]
    with pytest.raises(UnsafeArtifact, match="not a file written earlier"):
        intake(_tar(tmp_path / "hard-missing.tar", missing), tmp_path / "q2")
    _clean_root(tmp_path / "q2")


def test_devices_and_pipes_are_withheld_never_created(tmp_path):
    members = [
        (_member("ok.txt"), b"ok"),
        (_member("dev/null-ish", tarfile.CHRTYPE), None),
        (_member("dev/disk", tarfile.BLKTYPE), None),
        (_member("pipe", tarfile.FIFOTYPE), None),
    ]
    taken = intake(_tar(tmp_path / "dev.tar", members), tmp_path / "q")
    assert set(dict(taken.withheld)) == {"dev/null-ish", "dev/disk", "pipe"}
    assert _files(taken.path) == {"ok.txt": b"ok"}
    assert not os.path.lexists(taken.path / "pipe") and not os.path.lexists(taken.path / "dev/disk")
    assert "withheld" in str(intake_records(tmp_path / "q", taken.artifact_id))


def test_a_duplicate_entry_is_refused(tmp_path):
    members = [(_member("a.txt"), b"first"), (_member("a.txt"), b"second")]
    with pytest.raises(UnsafeArtifact, match="more than once"):
        intake(_tar(tmp_path / "dup.tar", members), tmp_path / "q")


def test_a_gzip_bomb_is_refused_by_its_ratio(tmp_path):
    zeros = b"\x00" * (6 << 20)
    archive = _tar(tmp_path / "bomb.tar.gz", [(_member("zeros.bin"), zeros)], "w:gz")
    assert archive.stat().st_size < 64 << 10
    with pytest.raises(UnsafeArtifact, match="decompression bomb"):
        intake(archive, tmp_path / "q", limits=Limits(ratio_floor=1 << 20, max_ratio=50))
    _clean_root(tmp_path / "q")


def test_too_many_entries_and_too_many_bytes_are_refused(tmp_path):
    many = _tar(tmp_path / "many.tar", [(_member(f"f{index}"), b"x") for index in range(30)])
    with pytest.raises(LimitExceeded, match="more than 20 entries"):
        intake(many, tmp_path / "q", limits=Limits(max_entries=20))
    big = _tar(tmp_path / "big.tar", [(_member("a"), b"x" * 4000), (_member("b"), b"y" * 4000)])
    with pytest.raises(LimitExceeded, match="5000-byte limit"):
        intake(big, tmp_path / "q", limits=Limits(max_total_bytes=5000))
    with pytest.raises(LimitExceeded, match="limit on one file"):
        intake(big, tmp_path / "q", limits=Limits(max_file_bytes=1000))
    _clean_root(tmp_path / "q")


def test_a_huge_tar_header_is_refused_before_it_is_read(tmp_path):
    header = _member("pax", tarfile.XHDTYPE)
    header.size = 8 * 1024 ** 3 - 1                      # 8 GiB of "attributes"
    raw = header.tobuf(format=tarfile.USTAR_FORMAT) + b"\x00" * 1024
    path = tmp_path / "header-bomb.tar"
    path.write_bytes(raw)
    with pytest.raises(UnsafeArtifact, match="header bomb"):
        intake(path, tmp_path / "q")
    _clean_root(tmp_path / "q")


def test_a_truncated_archive_is_unreadable_not_half_taken(tmp_path):
    whole = _tar(tmp_path / "whole.tar.gz", _tree_members(TREE), "w:gz").read_bytes()
    cut = tmp_path / "cut.tar.gz"
    cut.write_bytes(whole[: len(whole) // 2])
    with pytest.raises(ArchiveUnreadable):
        intake(cut, tmp_path / "q")
    _clean_root(tmp_path / "q")


@pytest.mark.parametrize("name", ["../evil.txt", "/abs.txt", "..\\..\\evil.txt", "C:/Windows/evil.txt"])
def test_zip_slip_is_refused(tmp_path, name):
    archive = _zip(tmp_path / "slip.zip", [("fine.txt", b"ok"), (name, b"evil")])
    with pytest.raises(UnsafeArtifact, match="outside the quarantine"):
        intake(archive, tmp_path / "q")
    _clean_root(tmp_path / "q")


def test_zip_symlinks_out_are_withheld_and_in_kept(tmp_path):
    archive = _zip(tmp_path / "links.zip", [
        ("real.txt", b"real"), _zip_link("passwd", "/etc/passwd"), _zip_link("inside", "real.txt"),
        _zip_link("up", "../../x"),
    ])
    taken = intake(archive, tmp_path / "q")
    assert set(dict(taken.withheld)) == {"passwd", "up"}
    assert os.readlink(taken.path / "inside") == "real.txt"


def test_a_zip_bomb_is_refused_before_it_is_read(tmp_path):
    archive = _zip(tmp_path / "bomb.zip", [("zeros.bin", b"\x00" * (6 << 20))])
    with pytest.raises(UnsafeArtifact, match="decompression bomb"):
        intake(archive, tmp_path / "q", limits=Limits(ratio_floor=1 << 20, max_ratio=50))
    many = _zip(tmp_path / "many.zip", [(f"f{index}.txt", b"x") for index in range(30)])
    with pytest.raises(LimitExceeded, match="30 entries"):
        intake(many, tmp_path / "q", limits=Limits(max_entries=20))
    _clean_root(tmp_path / "q")


def _central_records(data: bytes) -> list[int]:
    found, start = [], 0
    while (at := data.find(b"PK\x01\x02", start)) != -1:
        found.append(at)
        start = at + 4
    return found


def test_overlapping_zip_entries_are_refused(tmp_path):
    data = bytearray(_zip(tmp_path / "overlap.zip", [("a.txt", b"a" * 100), ("b.txt", b"b" * 100)], deflate=False).read_bytes())
    second = _central_records(bytes(data))[1]
    data[second + 42: second + 46] = (0).to_bytes(4, "little")      # b.txt's data is a.txt's
    path = tmp_path / "overlap.zip"
    path.write_bytes(bytes(data))
    with pytest.raises(UnsafeArtifact, match="share their data"):
        intake(path, tmp_path / "q")


def test_an_encrypted_zip_is_refused_plainly(tmp_path):
    data = bytearray(_zip(tmp_path / "locked.zip", [("secret.txt", b"x" * 50)]).read_bytes())
    data[6] |= 0x1                                                  # the local header's flag
    central = _central_records(bytes(data))[0]
    data[central + 8] |= 0x1                                        # and the central directory's
    path = tmp_path / "locked.zip"
    path.write_bytes(bytes(data))
    with pytest.raises(SourceRefused, match="encrypted"):
        intake(path, tmp_path / "q")
    _clean_root(tmp_path / "q")


def test_an_unsupported_archive_format_says_so(tmp_path):
    path = tmp_path / "x.zst"
    path.write_bytes(b"\x28\xb5\x2f\xfd" + b"\x00" * 64)
    with pytest.raises(SourceRefused, match="zstd archives are not supported"):
        intake(path, tmp_path / "q")


# --- directories and files ----------------------------------------------------------------------


def test_a_directory_is_copied_without_following_anything_out(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_bytes(b"do not copy")
    source = _make_tree(tmp_path / "src", TREE)
    os.symlink("/etc/passwd", source / "passwd")
    os.symlink(str(outside), source / "outside-dir")
    os.symlink("../outside/secret.txt", source / "relative-out")
    os.symlink("README.md", source / "readme-link")
    os.mkfifo(source / "pipe")
    (source / ".git" / "hooks").mkdir(parents=True)
    (source / ".git" / "hooks" / "post-checkout").write_bytes(b"#!/bin/sh\n")
    os.link(source / "README.md", source / "hard.md")
    taken = intake(source, tmp_path / "q")
    assert taken.handler == "directory" and taken.source.origin_kind == "directory"
    assert taken.source.pinned_ref == taken.source.content_digest
    assert _files(taken.path) == {**TREE, "hard.md": TREE["README.md"]}
    assert set(dict(taken.withheld)) == {"passwd", "outside-dir", "relative-out", "pipe", ".git"}
    assert "version-control" in dict(taken.withheld)[".git"]
    assert os.readlink(taken.path / "readme-link") == "README.md"
    assert os.lstat(taken.path / "hard.md").st_nlink == 1
    assert b"do not copy" not in b"".join(_files(taken.path).values())
    _assert_read_only(taken.path)


def test_a_single_file_is_placed_in_its_own_directory_and_an_archive_can_stay_opaque(tmp_path):
    doc = tmp_path / "notes.md"
    doc.write_bytes(b"# Notes\n\nAlways write things down.\n")
    taken = intake(doc, tmp_path / "q")
    assert taken.handler == "file" and _files(taken.path) == {"notes.md": doc.read_bytes()}
    assert taken.source.pinned_ref == "sha256:" + __import__("hashlib").sha256(doc.read_bytes()).hexdigest()
    archive = _tar(tmp_path / "t.tar", _tree_members(TREE))
    opaque = intake(archive, tmp_path / "q", kind="file")
    assert opaque.handler == "file" and list(_files(opaque.path)) == ["t.tar"]


# --- by URL, offline ----------------------------------------------------------------------------


def _serve(payload: bytes, final: str | None = None):
    def download(url, out, limits):
        out.write(payload)
        return final or url
    return download


def test_a_url_to_an_archive_is_unpacked_and_to_a_file_is_kept(tmp_path):
    tarball = _tar(tmp_path / "t.tar.gz", _tree_members(TREE), "w:gz").read_bytes()
    taken = intake("https://example.org/releases/tally-1.0.tar.gz", tmp_path / "q",
                   fetchers={"url": _serve(tarball, "https://cdn.example.org/tally-1.0.tar.gz")})
    assert taken.handler == "url" and taken.source.origin_kind == "url"
    assert _files(taken.path) == TREE
    assert taken.source.pinned_ref == "sha256:" + __import__("hashlib").sha256(tarball).hexdigest()
    assert any("redirected to https://cdn.example.org" in note for note in taken.notes)
    spec = intake("https://example.org/api/openapi.yaml", tmp_path / "q",
                  fetchers={"url": _serve(b"openapi: 3.0.3\n")})
    assert _files(spec.path) == {"openapi.yaml": b"openapi: 3.0.3\n"}
    odd = intake("https://example.org/", tmp_path / "q", fetchers={"url": _serve(b"<html></html>")})
    assert list(_files(odd.path)) == ["download"]


def test_a_download_redirected_off_public_https_is_refused():
    handler = url_handler._PublicHttpsRedirects()
    request = urllib.request.Request("https://example.org/a")
    for target in ("http://example.org/b", "https://127.0.0.1/b", "file:///etc/passwd", "https://10.1.2.3/x"):
        with pytest.raises(FetchFailed, match="redirected"):
            handler.redirect_request(request, None, 302, "Found", {}, target)


def test_a_download_past_its_limit_is_refused(tmp_path):
    with pytest.raises(LimitExceeded):
        intake("https://example.org/big.bin", tmp_path / "q", fetchers={"url": _serve(b"x" * 5000)},
               limits=Limits(max_download_bytes=1000))
    _clean_root(tmp_path / "q")


# --- a published package, offline ---------------------------------------------------------------


def _npm_tarball(tmp_path: Path, top: str = "package") -> bytes:
    manifest = b'{"name": "tally", "version": "1.0.0", "license": "MIT"}\n'
    tree = {f"{top}/package.json": manifest, f"{top}/LICENSE": MIT.encode(),
            f"{top}/index.js": b"module.exports = (xs) => xs.length;\n"}
    return _tar(tmp_path / "npm.tgz", _tree_members(tree), "w:gz").read_bytes()


def _registry(docs: dict[str, dict], asked: list[str] | None = None):
    def fetch(url, limits):
        if asked is not None:
            asked.append(url)
        if url not in docs:
            raise FetchFailed("the server answered 404")
        return __import__("json").dumps(docs[url]).encode()
    return fetch


def _npm_doc(tarball: bytes, *, name: str = "tally", version: str = "1.0.0", **dist) -> dict:
    import base64
    import hashlib
    integrity = "sha512-" + base64.b64encode(hashlib.sha512(tarball).digest()).decode()
    return {"name": name, "version": version,
            "dist": {"tarball": f"https://registry.npmjs.org/{name}/-/{name.rsplit('/', 1)[-1]}-{version}.tgz",
                     "integrity": integrity, **dist}}


def test_an_npm_package_is_fetched_by_name_checked_against_its_integrity_and_unwrapped(tmp_path):
    tarball = _npm_tarball(tmp_path)
    asked: list[str] = []
    fetchers = {"registry": _registry({"https://registry.npmjs.org/tally/1.0.0": _npm_doc(tarball)}, asked),
                "package": _serve(tarball)}
    taken = intake("npm:tally@1.0.0", tmp_path / "q", fetchers=fetchers, taken_at=TAKEN_AT)
    assert taken.handler == "package" and taken.source.origin_kind == "package"
    assert taken.source.origin == "npm:tally@1.0.0" and taken.source.licence == "MIT"
    assert sorted(_files(taken.path)) == ["LICENSE", "index.js", "package.json"]   # package/ taken off
    assert taken.source.pinned_ref == "sha256:" + __import__("hashlib").sha256(tarball).hexdigest()
    assert any("matched the sha512 digest" in note for note in taken.notes)
    assert asked == ["https://registry.npmjs.org/tally/1.0.0"]
    _assert_read_only(taken.path)
    # the version as ref=, the same package; with none, the latest, and the notes say which
    again = intake("npm:tally", tmp_path / "q", ref="1.0.0", fetchers=fetchers)
    assert again.path == taken.path
    latest = {"https://registry.npmjs.org/tally/latest": _npm_doc(tarball)}
    newest = intake("npm:tally", tmp_path / "q", fetchers={**fetchers, "registry": _registry(latest)})
    assert newest.source.origin == "npm:tally@1.0.0" and any("latest, 1.0.0" in n for n in newest.notes)


def test_a_scoped_npm_package_is_asked_for_by_its_escaped_name_and_its_own_folder_taken_off(tmp_path):
    tarball = _npm_tarball(tmp_path, top="node")                  # as @types packages wrap theirs
    asked: list[str] = []
    doc = _npm_doc(tarball, name="@types/node", version="20.1.0")
    taken = intake("npm:@types/node@20.1.0", tmp_path / "q", fetchers={
        "registry": _registry({"https://registry.npmjs.org/@types%2Fnode/20.1.0": doc}, asked),
        "package": _serve(tarball)})
    assert asked == ["https://registry.npmjs.org/@types%2Fnode/20.1.0"]
    assert sorted(_files(taken.path)) == ["LICENSE", "index.js", "package.json"]


def test_a_package_that_is_not_what_the_registry_published_is_refused(tmp_path):
    tarball = _npm_tarball(tmp_path)
    doc = _npm_doc(tarball)
    tampered = tarball[:-8] + b"\0" * 8
    with pytest.raises(UnsafeArtifact, match="not what was published"):
        intake("npm:tally@1.0.0", tmp_path / "q", fetchers={
            "registry": _registry({"https://registry.npmjs.org/tally/1.0.0": doc}),
            "package": _serve(tampered)})
    # no digest at all: nothing can be checked, so nothing is taken
    bare = {"name": "tally", "version": "1.0.0", "dist": {"tarball": doc["dist"]["tarball"]}}
    with pytest.raises(SourceRefused, match="no digest"):
        intake("npm:tally@1.0.0", tmp_path / "q", fetchers={
            "registry": _registry({"https://registry.npmjs.org/tally/1.0.0": bare}),
            "package": _serve(tarball)})
    # an archive URL the registry names off public https is refused like any intake URL
    for where in ("http://registry.npmjs.org/tally.tgz", "https://127.0.0.1/tally.tgz",
                  "file:///etc/passwd"):
        moved = {**doc, "dist": {**doc["dist"], "tarball": where}}
        with pytest.raises(SourceRefused):
            intake("npm:tally@1.0.0", tmp_path / "q", fetchers={
                "registry": _registry({"https://registry.npmjs.org/tally/1.0.0": moved}),
                "package": _serve(tarball)})
    # the registry answering for another version, or another package, is not believed
    for wrong in ({**doc, "version": "9.9.9"}, {**doc, "name": "other"}):
        with pytest.raises(FetchFailed):
            intake("npm:tally@1.0.0", tmp_path / "q", fetchers={
                "registry": _registry({"https://registry.npmjs.org/tally/1.0.0": wrong}),
                "package": _serve(tarball)})
    _clean_root(tmp_path / "q")


def test_a_pypi_package_prefers_its_source_distribution_and_checks_its_sha256(tmp_path):
    import hashlib
    sdist = _tar(tmp_path / "s.tar.gz", _tree_members({f"tally-1.0/{k}": v for k, v in TREE.items()}),
                 "w:gz").read_bytes()
    doc = {"info": {"version": "1.0"}, "urls": [
        {"filename": "tally-1.0-cp312-cp312-manylinux.whl", "packagetype": "bdist_wheel",
         "url": "https://files.pythonhosted.org/x/tally-1.0-cp312.whl", "digests": {"sha256": "0" * 64}},
        {"filename": "tally-1.0.tar.gz", "packagetype": "sdist",
         "url": "https://files.pythonhosted.org/x/tally-1.0.tar.gz",
         "digests": {"sha256": hashlib.sha256(sdist).hexdigest()}},
    ]}
    asked: list[str] = []
    taken = intake("pypi:tally==1.0", tmp_path / "q", fetchers={
        "registry": _registry({"https://pypi.org/pypi/tally/1.0/json": doc}, asked),
        "package": _serve(sdist)})
    assert asked == ["https://pypi.org/pypi/tally/1.0/json"]
    assert taken.source.origin == "pypi:tally==1.0" and _files(taken.path) == TREE
    assert taken.source.licence == "MIT"
    # only a wheel that needs building: nothing intake can read
    compiled = {**doc, "urls": doc["urls"][:1]}
    with pytest.raises(SourceRefused, match="without building"):
        intake("pypi:tally==1.0", tmp_path / "q2", fetchers={
            "registry": _registry({"https://pypi.org/pypi/tally/1.0/json": compiled}),
            "package": _serve(sdist)})
    _clean_root(tmp_path / "q2")


def test_a_package_source_is_named_exactly_or_refused():
    parse = package_handler.parse
    assert parse("npm:left-pad@1.3.0") == ("npm", "left-pad", "1.3.0")
    assert parse("npm:@scope/name") == ("npm", "@scope/name", None)
    assert parse("pypi:Requests==2.32.3") == ("pypi", "Requests", "2.32.3")
    assert parse("pypi:six@1.16.0") == ("pypi", "six", "1.16.0")
    assert parse("pypi:six", "1.16.0") == ("pypi", "six", "1.16.0")
    for bad in ("npm:", "npm:../etc", "npm:Tally", "npm:a/b", "pypi:-x", "pypi:a b",
                "npm:tally@1.0 ; rm", "pypi:six==../1", "cargo:serde", "npm:" + "a" * 300):
        with pytest.raises(SourceRefused):
            parse(bad)
    with pytest.raises(SourceRefused, match="give one"):
        parse("npm:tally@1.0.0", "2.0.0")


# --- the quarantine itself ----------------------------------------------------------------------


def test_the_same_artifact_again_is_the_same_copy_and_the_same_source(tmp_path):
    source = _make_tree(tmp_path / "src", TREE)
    first = intake(source, tmp_path / "q")
    again = intake(source, tmp_path / "q")
    assert again.reused and again.path == first.path and again.source == first.source
    assert sorted(entry.name for entry in (tmp_path / "q").iterdir()) == [
        first.artifact_id, first.artifact_id + ".intake.json",
    ]


def test_a_copy_that_no_longer_matches_is_replaced_cleanly(tmp_path):
    source = _make_tree(tmp_path / "src", TREE)
    first = intake(source, tmp_path / "q")
    victim = first.path / "README.md"
    os.chmod(first.path, 0o755)
    os.chmod(victim, 0o644)
    victim.write_bytes(b"tampered")
    again = intake(source, tmp_path / "q")
    assert not again.reused and again.path == first.path
    assert (again.path / "README.md").read_bytes() == TREE["README.md"]
    assert tree_digest(again.path) == first.source.content_digest
    _assert_read_only(again.path)


def test_a_failure_leaves_nothing_that_looks_complete(tmp_path, monkeypatch):
    source = _make_tree(tmp_path / "src", TREE)

    def broken(root, **kwargs):
        raise OSError("disk went away")

    import app.digest.intake as intake_module
    monkeypatch.setattr(intake_module, "tree_digest", broken)
    with pytest.raises(IntakeError):
        intake(source, tmp_path / "q")
    _clean_root(tmp_path / "q")


def test_names_are_cleaned_or_refused():
    assert clean_name("./a//b/./c") == "a/b/c"
    assert clean_name("a\\b", backslash_is_separator=True) == "a/b"
    assert clean_name("a\\b") == "a\\b"
    for bad in ("../x", "/x", "a/../b", "x\x00y", "C:/x"):
        with pytest.raises(UnsafeArtifact):
            clean_name(bad)
    with pytest.raises(LimitExceeded):
        clean_name("a" * 300)


def test_a_writer_refuses_a_file_that_lies_about_its_size(tmp_path):
    writer = TreeWriter(tmp_path / "t", Limits())
    (tmp_path / "t").mkdir()
    with pytest.raises(UnsafeArtifact, match="declares"):
        writer.file("a.txt", b"12345", size=3)
    with pytest.raises(UnsafeArtifact, match="not the 9"):
        writer.file("b.txt", b"12345", size=9)


def test_messages_escape_what_an_artifact_names():
    assert shown("evil\x1b[31mred\u202etxt") == "evil\\x1b[31mred\\u202etxt"
    assert len(shown("x" * 500)) == 160


def test_remove_tree_removes_a_sealed_copy(tmp_path):
    taken = intake(_make_tree(tmp_path / "src", TREE), tmp_path / "q")
    remove_tree(taken.path)
    assert not taken.path.exists()


# --- the handler registry is open ---------------------------------------------------------------

PROBE = '''
from app.digest.intake import Pinned

NAME = "probe"
ORIGIN_KIND = "upload"


def claims(request):
    return 90 if request.source.startswith("probe:") else 0


def materialise(request, writer):
    writer.file("said.txt", request.source.encode())
    return Pinned(origin=request.source)
'''


@pytest.fixture
def handler_portion(tmp_path, monkeypatch):
    """A second portion of the app.digest.intakes namespace in a temporary directory."""
    portion = tmp_path / "portion"
    (portion / "intakes").mkdir(parents=True)
    monkeypatch.setattr(app.digest, "__path__", [*app.digest.__path__, str(portion)])
    before = set(sys.modules)
    yield portion / "intakes"
    package = sys.modules["app.digest.intakes"]
    for name in sorted(set(sys.modules) - before):
        if name.startswith("app.digest.intakes."):
            del sys.modules[name]
            if hasattr(package, name.rpartition(".")[2]):
                delattr(package, name.rpartition(".")[2])
    importlib.invalidate_caches()


def test_a_new_kind_of_source_is_a_new_module(tmp_path, handler_portion):
    (handler_portion / "zz_probe.py").write_text(PROBE, encoding="utf-8")
    (handler_portion / "zz_badkind.py").write_text(PROBE.replace('"upload"', '"carrier-pigeon"'), encoding="utf-8")
    (handler_portion / "zz_broken.py").write_text("def claims(\n", encoding="utf-8")
    (handler_portion / "_helper.py").write_text("raise RuntimeError('never imported')\n", encoding="utf-8")
    handlers, broken = discover_handlers()
    assert [handler.module for handler in handlers] == [*HANDLERS, "zz_probe"]
    assert dict(broken) == {
        "zz_badkind": "names an origin kind the model does not know (carrier-pigeon)",
        "zz_broken": "could not be imported (SyntaxError)",
    }
    taken = intake("probe:hello", tmp_path / "q")
    assert taken.handler == "probe" and taken.source.origin_kind == "upload"
    assert _files(taken.path) == {"said.txt": b"probe:hello"}
    assert any("zz_broken" in note for note in taken.notes)


def test_the_probe_handler_is_gone_once_its_portion_is():
    handlers, _ = discover_handlers()
    assert tuple(handler.module for handler in handlers) == HANDLERS


# --- the licence the copy declares -------------------------------------------------------------


def test_the_intake_licence_is_the_scanners(tmp_path):
    root = _make_tree(tmp_path / "t", {"LICENSE": MIT.encode(), "package.json": b'{"name": "x", "license": "MIT"}'})
    assert scan.artifact_licence(root) == "MIT"


# --- intake, then digest ------------------------------------------------------------------------


def test_an_intake_digests_as_a_quarantined_directory_does(tmp_path):
    origin = tmp_path / "origin"
    _repo(origin, TREE)
    taken = _git_intake(tmp_path, origin)
    result = digest(taken.path, taken.source)
    assert not result.blocked and result.units
    assert result.artifact.source == taken.source


def _cli(*args, cwd):
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, args)], capture_output=True, text=True,
                          cwd=cwd, timeout=120, check=False)


def test_the_command_line_takes_in_digests_and_exits_as_digest_does(tmp_path):
    source = _make_tree(tmp_path / "src", TREE)
    store, report = tmp_path / "store", tmp_path / "out" / "report.md"
    done = _cli(source, "--quarantine", tmp_path / "q", "--store", store, "--report", report, cwd=tmp_path)
    assert done.returncode == 0, done.stderr
    [line] = done.stdout.splitlines()
    assert line.startswith("digested art-") and "kinds:" in line
    assert "intake: directory" in done.stderr and "pinned sha256:" in done.stderr
    assert report.read_text(encoding="utf-8").startswith("# Digest of ")
    again = _cli(source, "--quarantine", tmp_path / "q", "--store", store, cwd=tmp_path)
    assert (again.returncode, again.stdout) == (0, done.stdout) and ", reused" in again.stderr

    hostile = _tar(tmp_path / "bad.tar", [(_member("../evil"), b"x")])
    blocked = _cli(hostile, "--quarantine", tmp_path / "q", cwd=tmp_path)
    assert blocked.returncode == 2 and "blocked in quarantine" in blocked.stderr

    refused = _cli("http://example.org/x.git", "--quarantine", tmp_path / "q", cwd=tmp_path)
    assert refused.returncode == 1 and "only https is fetched" in refused.stderr
    missing = _cli(tmp_path / "missing", "--quarantine", tmp_path / "q", cwd=tmp_path)
    assert missing.returncode == 1 and "NoHandler" in missing.stderr
    inside = _cli(source, "--quarantine", SCRIPT.parent / "quarantine-here", cwd=tmp_path)
    assert inside.returncode == 1 and "inside this repository" in inside.stderr
    assert not (SCRIPT.parent / "quarantine-here").exists()
    usage = _cli(source, cwd=tmp_path)
    assert usage.returncode == 1 and "--quarantine" in usage.stderr


def test_the_command_line_relates_and_reports_what_intake_withheld(tmp_path):
    """R7: what intake withheld and noted reaches the digest's result and report; and the
    command line relates to CLIVE's self-model as scripts/digest.py does (--no-relate,
    --self-model-root)."""
    source = _make_tree(tmp_path / "src", TREE)
    os.symlink("/etc/passwd", source / "etc-link")
    report = tmp_path / "report.md"
    plain = _cli(source, "--quarantine", tmp_path / "q", "--report", report, "--no-relate", cwd=tmp_path)
    assert plain.returncode == 0, plain.stderr
    assert plain.stdout.rstrip("\n").endswith("; not related")
    assert "intake: withheld etc-link" in plain.stderr
    intake_section = report.read_text(encoding="utf-8").split("## Intake")[1].split("## Outcome")[0]
    assert "Withheld from the copy (1)" in intake_section and "- `etc-link`: " in intake_section

    related = _cli(source, "--quarantine", tmp_path / "q", cwd=tmp_path)
    assert related.returncode == 0, related.stderr
    assert "; relations: " in related.stdout and "; proposals: " in related.stdout

    other = _make_tree(tmp_path / "other-clive", {
        "docs/product-memory/FEATURES.md": (
            b"| ID | Feature | Status | Phase | Notes |\n|---|---|---|---|---|\n"
            b"| FEAT-001 | Tally counting | SHIPPED | V1 | Counts orders. |\n"),
    })
    elsewhere = _cli(source, "--quarantine", tmp_path / "q", "--self-model-root", other,
                     "--report", report, cwd=tmp_path)
    assert elsewhere.returncode == 0, elsewhere.stderr
    assert "; relations: " in elsewhere.stdout and "tool:" not in report.read_text(encoding="utf-8")
    both = _cli(source, "--quarantine", tmp_path / "q", "--no-relate", "--self-model-root", other,
                cwd=tmp_path)
    assert both.returncode == 1 and "not allowed with" in both.stderr


def test_the_command_line_relates_by_default_and_can_take_clive_as_itself(tmp_path):
    source = _make_tree(tmp_path / "src", TREE)
    related = _cli(source, "--quarantine", tmp_path / "q", cwd=tmp_path)
    assert related.returncode == 0, related.stderr
    assert "; relations: " in related.stdout and "; proposals: " in related.stdout
    bare = _cli(source, "--quarantine", tmp_path / "q", "--no-relate", cwd=tmp_path)
    assert bare.returncode == 0 and "; relations: " not in bare.stdout
    itself = _cli(source, "--quarantine", tmp_path / "q", "--self", cwd=tmp_path)
    assert itself.returncode == 0 and "; self: " in itself.stdout and "proposals" not in itself.stdout
    both = _cli(source, "--quarantine", tmp_path / "q", "--self", "--no-relate", cwd=tmp_path)
    assert both.returncode == 1 and "not allowed with" in both.stderr

