"""The boundary between CLIVE and the Shopify theme, and the scripts that clean the repository up.

Why this exists: the theme reached this repository by accident (October 2026). Its files are gone
from the root, it moves to the private repository crooksldn-pixel/crooksldn-theme with
scripts/repo/move_theme.sh, and about 230 landed or superseded branches are archived as tags by
scripts/repo/archive_branches.sh. Those scripts delete branches on the real remote, so they are
proved here first, on scratch repositories, never on GitHub:

- the root holds no theme files, and the README and CLAUDE.md say where the theme lives;
- the archive list and the theme list are well formed, and neither names a branch that is kept;
- archive_branches.sh changes nothing without --apply, tags before it deletes, refuses a branch
  that moved, GitHub's default branch and a kept branch, waits for a "requires" path on trunk,
  and is safe to run twice;
- move_theme.sh pushes the theme as main with its history, refuses a public theme repository,
  deletes from clive only with --delete-public and never the default branch;
- the documents imported into docs/history/branches/ are byte-for-byte what MANIFEST.txt says.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts" / "repo"
ARCHIVE = SCRIPTS / "archive_branches.sh"
MOVE = SCRIPTS / "move_theme.sh"
ARCHIVE_LIST = REPO / "docs" / "repo" / "BRANCHES_TO_ARCHIVE.txt"
THEME_LIST = REPO / "docs" / "repo" / "THEME_BRANCHES.txt"
HISTORY = REPO / "crooks-assistant" / "docs" / "history" / "branches"

THEME_AT_ROOT = ("assets", "blocks", "config", "layout", "locales", "sections", "snippets", "templates",
                 "image-backups", "package.json", ".theme-check.yml")
KEPT = re.compile(r"^(clive/trunk|clive/control/.*|clive/evidence/.*|clive/engineering-state|crooks-ai-bridge|"
                  r"claude/compassionate-dirac-44hnee|claude/crooksldn-theme-init-bnen7a|"
                  r"claude/venture-engine-v1-2026-09-29|claude/n2-.*)$")
SHA = re.compile(r"^[0-9a-f]{40}$")
IDENTITY = {"GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
            "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "test@example.invalid"}


def _rows(path: Path) -> list[list[str]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.startswith("#"):
            rows.append(line.split(" ", 3))
    return rows


# --- the root ---------------------------------------------------------------------------------


def test_the_root_holds_no_theme_files():
    assert [name for name in THEME_AT_ROOT if (REPO / name).exists()] == []


def test_the_readme_and_claude_md_say_the_theme_lives_in_its_own_private_repository():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    claude = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
    assert readme.startswith("# CLIVE\n")
    for text in (readme, claude):
        assert "crooksldn-pixel/crooksldn-theme" in text and "private" in text
    assert "claude/compassionate-dirac-44hnee" in readme


# --- the lists --------------------------------------------------------------------------------


def test_the_archive_list_is_well_formed_and_names_no_branch_that_is_kept():
    rows = _rows(ARCHIVE_LIST)
    assert len(rows) > 200
    branches = [row[0] for row in rows]
    assert len(set(branches)) == len(branches)
    tags = {"archive/" + branch.replace("/", "-") for branch in branches}
    assert len(tags) == len(branches)
    for branch, sha, requires, reason in rows:
        assert SHA.match(sha), branch
        assert not KEPT.match(branch), branch
        assert reason.split(":")[0] in ("landed", "superseded", "knowledge-only"), branch
        assert requires == "-" or (REPO / requires).is_file(), (branch, requires)
        assert (requires != "-") == reason.startswith("knowledge-only"), branch


def test_the_theme_list_makes_one_main_and_shares_no_branch_with_the_archive_list():
    rows = _rows(THEME_LIST)
    assert [row[0] for row in rows if row[2] == "refs/heads/main"] == ["claude/crooksldn-theme-init-bnen7a"]
    for branch, sha, target, _ in rows:
        assert SHA.match(sha) and (target == "refs/heads/main" or target == "refs/tags/archive/" + branch.replace("/", "-"))
    assert not {row[0] for row in rows} & {row[0] for row in _rows(ARCHIVE_LIST)}


# --- scratch repositories ---------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, **IDENTITY})
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def _commit(work: Path, name: str) -> str:
    (work / name).write_text(name, encoding="utf-8")
    _git(work, "add", name)
    _git(work, "commit", "-qm", name)
    return _git(work, "rev-parse", "HEAD")


def _run(script: Path, cwd: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(script), *args], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, **IDENTITY, **(env or {})}, timeout=120)


def _refs(remote: Path) -> dict[str, str]:
    out = _git(remote, "for-each-ref", "--format=%(refname) %(objectname)")
    return dict(line.split(" ", 1) for line in out.splitlines()) if out else {}


@pytest.fixture
def world(tmp_path: Path) -> dict:
    """A public remote shaped like clive: a trunk, a landed branch, a superseded one, one that moves
    after the list is made, one waiting on a document, a kept one, and the theme on its own line."""
    public = tmp_path / "public.git"
    theme = tmp_path / "theme.git"
    work = tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", "-b", "clive/trunk", str(public))
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(theme))
    _git(tmp_path, "init", "-q", "-b", "clive/trunk", str(work))
    ids = {"root": _commit(work, "root")}
    _git(work, "checkout", "-qb", "old/landed")
    ids["landed"] = _commit(work, "landed")
    _git(work, "checkout", "-q", "clive/trunk")
    _git(work, "merge", "-q", "--ff-only", "old/landed")
    for name in ("claude/superseded", "claude/moves", "claude/knowledge", "clive/control/status"):
        _git(work, "checkout", "-q", "-b", name, "clive/trunk")
        ids[name] = _commit(work, name.replace("/", "_"))
    _git(work, "checkout", "-q", "--orphan", "claude/crooksldn-theme-init-bnen7a")
    _git(work, "rm", "-rqf", ".")
    ids["theme"] = _commit(work, "theme.liquid")
    _git(work, "checkout", "-qb", "experiment/flatlay")
    ids["flatlay"] = _commit(work, "flatlay.liquid")
    _git(work, "checkout", "-q", "clive/trunk")
    _git(work, "push", "-q", str(public), "--all")
    _git(work, "remote", "add", "origin", str(public))
    _git(work, "checkout", "-q", "claude/moves")
    _commit(work, "moved-on")
    _git(work, "push", "-q", "origin", "claude/moves")
    _git(work, "checkout", "-q", "clive/trunk")
    archive_list = tmp_path / "archive.txt"
    archive_list.write_text(
        "# a test list\n\n"
        f"old/landed {ids['landed']} - landed: an ancestor of clive/trunk\n"
        f"claude/superseded {ids['claude/superseded']} - superseded: by a later attempt\n"
        f"claude/moves {ids['claude/moves']} - landed: listed before it moved\n"
        f"claude/knowledge {ids['claude/knowledge']} docs/imported.md knowledge-only: waits for the import\n",
        encoding="utf-8")
    theme_list = tmp_path / "theme.txt"
    theme_list.write_text(
        f"claude/crooksldn-theme-init-bnen7a {ids['theme']} refs/heads/main the theme\n"
        f"experiment/flatlay {ids['flatlay']} refs/tags/archive/experiment-flatlay a theme experiment\n",
        encoding="utf-8")
    return {"public": public, "theme": theme, "work": work, "ids": ids, "archive": archive_list, "themes": theme_list}


def _archive(world: dict, *args: str) -> subprocess.CompletedProcess:
    return _run(ARCHIVE, world["work"], "--list", str(world["archive"]), "--remote", str(world["public"]), *args)


def _move(world: dict, *args: str, env: dict | None = None, theme: str | None = None) -> subprocess.CompletedProcess:
    return _run(MOVE, world["work"], "--list", str(world["themes"]), "--public", str(world["public"]),
                "--theme", theme or str(world["theme"]), *args, env=env)


# --- archive_branches.sh ----------------------------------------------------------------------


def test_a_dry_run_changes_nothing_and_says_what_it_would_do(world):
    before = _refs(world["public"])
    done = _archive(world)
    assert _refs(world["public"]) == before
    assert done.returncode == 1  # one branch refused, one waiting
    assert "would archive" in done.stdout and "old/landed -> archive/old-landed" in done.stdout
    assert "REFUSED   claude/moves" in done.stdout and "WAITING   claude/knowledge" in done.stdout


def test_apply_tags_each_branch_at_its_sha_then_deletes_it_and_leaves_the_rest_alone(world):
    ids = world["ids"]
    done = _archive(world, "--apply")
    refs = _refs(world["public"])
    assert refs["refs/tags/archive/old-landed"] == ids["landed"]
    assert refs["refs/tags/archive/claude-superseded"] == ids["claude/superseded"]
    assert "refs/heads/old/landed" not in refs and "refs/heads/claude/superseded" not in refs
    # moved after the list was made: neither tagged nor deleted
    assert "refs/heads/claude/moves" in refs and "refs/tags/archive/claude-moves" not in refs
    # waiting for its document on trunk: untouched
    assert refs["refs/heads/claude/knowledge"] == ids["claude/knowledge"]
    assert "refs/heads/clive/trunk" in refs and "refs/heads/clive/control/status" in refs
    assert done.returncode == 1 and "Archived 2 of 2" in done.stdout
    assert _git(world["work"], "for-each-ref", "refs/archive-branches-run") == ""


def test_a_second_run_is_safe_and_a_waiting_branch_goes_once_its_document_is_on_trunk(world):
    _archive(world, "--apply")
    again = _archive(world, "--apply")
    assert "Already archived: 2" in again.stdout and "Archived 0 of 0" in again.stdout
    (world["work"] / "docs").mkdir()
    _commit(world["work"], "docs/imported.md")
    _git(world["work"], "push", "-q", "origin", "clive/trunk")
    third = _archive(world, "--apply")
    refs = _refs(world["public"])
    assert "refs/heads/claude/knowledge" not in refs
    assert refs["refs/tags/archive/claude-knowledge"] == world["ids"]["claude/knowledge"]
    assert "Archived 1 of 1" in third.stdout


def test_githubs_default_branch_is_never_deleted(world):
    _git(world["public"], "symbolic-ref", "HEAD", "refs/heads/claude/superseded")
    done = _archive(world, "--apply")
    assert "it is GitHub's default branch" in done.stdout
    assert "refs/heads/claude/superseded" in _refs(world["public"])


def test_a_kept_branch_on_the_list_stops_the_run_before_anything_happens(world):
    sha = world["ids"]["clive/control/status"]
    world["archive"].write_text(world["archive"].read_text() + f"clive/control/status {sha} - landed: wrongly listed\n")
    before = _refs(world["public"])
    done = _archive(world, "--apply")
    assert done.returncode == 2 and "must be kept" in done.stderr
    assert _refs(world["public"]) == before


def test_a_tag_already_at_another_commit_is_refused(world):
    _git(world["work"], "push", "-q", "origin", f"{world['ids']['root']}:refs/tags/archive/old-landed")
    done = _archive(world, "--apply")
    assert "REFUSED   old/landed: archive/old-landed already exists" in done.stdout
    assert "refs/heads/old/landed" in _refs(world["public"])


# --- move_theme.sh ----------------------------------------------------------------------------


def test_the_theme_becomes_main_with_its_history_and_nothing_leaves_clive_without_delete_public(world):
    ids = world["ids"]
    assert _move(world).returncode == 0 and _refs(world["theme"]) == {}
    done = _move(world, "--apply")
    theme = _refs(world["theme"])
    assert done.returncode == 0, done.stdout + done.stderr
    assert theme["refs/heads/main"] == ids["theme"]
    assert theme["refs/tags/archive/experiment-flatlay"] == ids["flatlay"]
    public = _refs(world["public"])
    assert public["refs/heads/claude/crooksldn-theme-init-bnen7a"] == ids["theme"]
    assert "refs/heads/experiment/flatlay" in public


def test_delete_public_removes_the_theme_from_clive_but_never_the_default_branch(world):
    assert _move(world, "--delete-public").returncode == 2
    _git(world["public"], "symbolic-ref", "HEAD", "refs/heads/experiment/flatlay")
    first = _move(world, "--apply", "--delete-public")
    assert first.returncode == 1 and "default branch" in first.stdout
    public = _refs(world["public"])
    assert "refs/heads/claude/crooksldn-theme-init-bnen7a" not in public and "refs/heads/experiment/flatlay" in public
    _git(world["public"], "symbolic-ref", "HEAD", "refs/heads/clive/trunk")
    second = _move(world, "--apply", "--delete-public")
    assert second.returncode == 0, second.stdout + second.stderr
    assert "refs/heads/experiment/flatlay" not in _refs(world["public"])


def test_a_theme_main_that_moved_on_counts_as_moved_and_a_foreign_tag_is_refused(world):
    _move(world, "--apply")
    clone = world["work"].parent / "theme-work"
    _git(world["work"].parent, "clone", "-q", str(world["theme"]), str(clone))
    _commit(clone, "new-section.liquid")
    _git(clone, "push", "-q", "origin", "main")
    _git(clone, "push", "-q", "origin", f"{world['ids']['theme']}:refs/tags/archive/experiment-flatlay", "--force")
    done = _move(world, "--apply")
    assert "refs/heads/main in the theme" not in done.stdout
    assert "REFUSED   experiment/flatlay: refs/tags/archive/experiment-flatlay in the theme repository is something else" in done.stdout


def test_a_public_theme_repository_is_refused_before_anything_is_pushed(world, tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    curl = bin_dir / "curl"
    curl.write_text("#!/bin/sh\nprintf 200\n", encoding="utf-8")
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    url = "https://github.com/crooksldn-pixel/crooksldn-theme.git"
    redirect = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": f"url.{world['theme']}.insteadOf", "GIT_CONFIG_VALUE_0": url}
    done = _move(world, "--apply", env=redirect, theme=url)
    assert done.returncode == 2 and "is PUBLIC" in done.stderr
    assert _refs(world["theme"]) == {}
    curl.write_text("#!/bin/sh\nprintf 404\n", encoding="utf-8")
    private = _move(world, "--apply", env=redirect, theme=url)
    assert private.returncode == 0, private.stdout + private.stderr
    assert _refs(world["theme"])["refs/heads/main"] == world["ids"]["theme"]


# --- the imported history ---------------------------------------------------------------------


def test_the_imported_documents_are_byte_for_byte_what_the_manifest_says():
    rows = [line.split(" ") for line in (HISTORY / "MANIFEST.txt").read_text(encoding="utf-8").splitlines()
            if line and not line.startswith("#")]
    listed = {row[0] for row in rows}
    on_disk = {str(p.relative_to(HISTORY)) for p in HISTORY.rglob("*") if p.is_file()} - {"README.md", "MANIFEST.txt"}
    assert listed == on_disk and len(rows) == 26
    for name, blob, commit, source in rows:
        assert _git(REPO, "hash-object", str(HISTORY / name)) == blob, name
        present = subprocess.run(["git", "cat-file", "-e", f"{commit}^{{commit}}"], cwd=REPO, capture_output=True)
        if present.returncode == 0:
            assert _git(REPO, "rev-parse", f"{commit}:{source}") == blob, name
