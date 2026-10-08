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
- move_theme.sh pushes the theme as main with its history, refuses a public theme repository
  whatever form its github.com address takes (and refuses one it cannot check), never prints a
  credential, deletes from clive only with --delete-public and never the default branch;
- the documents imported into docs/history/branches/ are byte-for-byte what MANIFEST.txt says.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

from tests.fake_credentials import github_token

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
OPEN_PR = re.compile(r"\bopen (draft )?PR #\d+")
HISTORY_INDEX = "crooks-assistant/docs/history/branches/README.md"
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
        assert (requires != "-") == (reason.startswith("knowledge-only") or bool(OPEN_PR.search(reason))), branch
        if OPEN_PR.search(reason):
            assert requires == HISTORY_INDEX, branch


def test_the_branches_of_open_pull_requests_1_and_2_wait_until_step_5_has_closed_them():
    """Deleting a pull request's head or base branch closes it without a word, so each of the three
    branches waits on the path BOUNDARY.md's step 5 checks before it closes #1 and #2 with a comment."""
    requires = {row[0]: row[2] for row in _rows(ARCHIVE_LIST)}
    for branch in ("claude/product-memory-foundation", "chatgpt/ops-memory-2026-09-19",
                   "claude/crooks-assistant-build-lgxlau"):
        assert requires[branch] == HISTORY_INDEX, branch
    boundary = (REPO / "docs" / "repo" / "BOUNDARY.md").read_text(encoding="utf-8")
    assert f"git cat-file -e origin/clive/trunk:{HISTORY_INDEX} succeeds" in boundary
    assert "11 WAITING lines are expected if step 5 was skipped" in boundary


def test_a_loop_objective_branch_is_listed_only_once_landed_or_superseded_as_boundary_says():
    rows = [row for row in _rows(ARCHIVE_LIST) if row[0].startswith("clive/objective/")]
    assert rows and all(row[2] == "-" and row[3].startswith(("landed:", "superseded:")) for row in rows)
    boundary = (REPO / "docs" / "repo" / "BOUNDARY.md").read_text(encoding="utf-8")
    loop_row = next(line for line in boundary.splitlines() if line.startswith("| **The build loop's branches**"))
    assert "archived once its build has landed or been superseded, never while it is in flight" in loop_row
    assert "Never archived by hand" not in boundary


def test_no_text_of_the_boundary_points_at_the_possible_credential(world):
    """The texts say only that a credential may have been committed on the theme branch and must be
    rotated before the move. None names a file of the theme's phone app, where it would point."""
    texts = [REPO / "docs" / "repo" / "BOUNDARY.md", ARCHIVE_LIST, THEME_LIST, MOVE, ARCHIVE,
             REPO / "README.md", REPO / "CLAUDE.md", HISTORY / "README.md", HISTORY / "MANIFEST.txt"]
    for path in texts:
        assert not re.search(r"\bmobile/[\w.-]", path.read_text(encoding="utf-8")), path
    dry = _move(world)
    for text in ((REPO / "docs" / "repo" / "BOUNDARY.md").read_text(encoding="utf-8"), MOVE.read_text(encoding="utf-8"), dry.stdout):
        assert "may have been committed on the theme branch" in " ".join(text.split())
        assert "rotated before the move" in " ".join(text.split())
    assert "mobile/" not in dry.stdout + dry.stderr


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


def _github(world: dict, tmp_path: Path, url: str, answer: int) -> tuple[dict, Path]:
    """git reaches `url` as the scratch theme repository, and curl answers GitHub's API with
    `answer` and writes down what it was asked."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    asked = tmp_path / "curl.log"
    curl = bin_dir / "curl"
    curl.write_text(f'#!/bin/sh\necho "$@" >> "{asked}"\nprintf {answer}\n', encoding="utf-8")
    curl.chmod(curl.stat().st_mode | stat.S_IEXEC)
    return ({"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GIT_CONFIG_COUNT": "1",
             "GIT_CONFIG_KEY_0": f"url.{world['theme']}.insteadOf", "GIT_CONFIG_VALUE_0": url}, asked)


def _with_credential() -> tuple[str, str]:
    token = github_token("boundary-move-theme")
    return token, f"https://x-access-token:{token}@github.com/crooksldn-pixel/crooksldn-theme.git"


@pytest.mark.parametrize("url", [
    "credentialed",
    "http://www.github.com/crooksldn-pixel/crooksldn-theme",
    "https://WWW.GitHub.com/crooksldn-pixel/crooksldn-theme.git/",
    "ssh://git@github.com/crooksldn-pixel/crooksldn-theme.git",
    "ssh://git@github.com:22/crooksldn-pixel/crooksldn-theme.git",
    "git@github.com:crooksldn-pixel/crooksldn-theme.git",
])
def test_every_form_of_a_github_address_is_checked_and_a_public_one_is_refused(world, tmp_path, url):
    token = ""
    if url == "credentialed":
        token, url = _with_credential()
    env, asked = _github(world, tmp_path, url, 200)
    done = _move(world, "--apply", env=env, theme=url)
    assert done.returncode == 2 and "crooksldn-pixel/crooksldn-theme is PUBLIC" in done.stderr
    assert "https://api.github.com/repos/crooksldn-pixel/crooksldn-theme" in asked.read_text()
    assert _refs(world["theme"]) == {}
    if token:
        assert token not in asked.read_text() and token not in done.stdout + done.stderr


def test_a_credentialed_address_is_never_printed_even_when_the_move_goes_through(world, tmp_path):
    token, url = _with_credential()
    env, _ = _github(world, tmp_path, url, 404)
    dry = _move(world, env=env, theme=url)
    done = _move(world, "--apply", env=env, theme=url)
    assert dry.returncode == 0 and done.returncode == 0, done.stdout + done.stderr
    assert _refs(world["theme"])["refs/heads/main"] == world["ids"]["theme"]
    for run in (dry, done):
        assert token not in run.stdout + run.stderr
    assert "https://***@github.com/crooksldn-pixel/crooksldn-theme.git" in dry.stdout


@pytest.mark.parametrize("url", [
    "https://github.com/crooksldn-pixel/crooksldn-theme/tree/main",
    "https://github.com.example.invalid/crooksldn-pixel/crooksldn-theme.git",
    "https://example.invalid/github.com/crooksldn-pixel/crooksldn-theme.git",
])
def test_an_address_on_github_that_names_no_repository_stops_the_run_before_any_push(world, tmp_path, url):
    env, asked = _github(world, tmp_path, url, 404)
    done = _move(world, "--apply", env=env, theme=url)
    assert done.returncode == 2 and "does not say which repository" in done.stderr
    assert not asked.exists() and _refs(world["theme"]) == {}


def test_a_credentialed_origin_is_never_printed(world):
    token, _ = _with_credential()
    _git(world["work"], "remote", "set-url", "origin", f"https://x-access-token:{token}@github.com/someone/else.git")
    for script in (MOVE, ARCHIVE):
        done = _run(script, world["work"], "--list", str(world["themes"] if script == MOVE else world["archive"]))
        assert done.returncode == 2 and "https://***@github.com/someone/else.git" in done.stderr
        assert token not in done.stdout + done.stderr


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
