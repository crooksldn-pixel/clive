"""The release service against real git: a local bare repository stands in for GitHub, a clone of it
for production's checkout, and every git command the service runs is the real one.

Why it exists: tests/test_release_service.py answers every command from a fake world, which proves
the procedure's order and its decisions but not that the git it asks for works. Here the trunk is
fetched into the service's own copy, production is checked out forward and back, a reviewer's
record is read from its branch, and the deploy record is committed with git's plumbing and pushed
to its claude/deploy-<sha8>-record branch, then read back from the "GitHub" side. Everything that
is not git (make, systemctl, journalctl, /health) is answered as a healthy server.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.orchestrator.github_acceptance import GateResult, GateState, RunFact
from app.release import authority, github, service
from app.release.host import Result, SystemHost
from app.release.settings import ReleaseSettings

ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@example.com", "GIT_CONFIG_NOSYSTEM": "1"}
HEALTHY = json.dumps({"status": "ok", "build": "b1", "checks": {"claude": {"ok": True}}})


def git(*args: str, cwd: Path | None = None) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, env={**os.environ, **ENV}, capture_output=True, text=True,
                          check=True)
    return done.stdout.strip()


class GitHost(SystemHost):
    """Real git and real files; the rest of the server answers as a healthy one."""

    def __init__(self, waivers: Path, unit: Path, fail: set[str] | None = None) -> None:
        self.waivers = waivers
        self.unit = unit
        self.fail = fail or set()
        self.steps: list[str] = []
        self.clock = datetime(2026, 10, 8, 2, 0, 0, tzinfo=UTC)

    def run(self, step, argv, *, cwd=None, env=None, input=None, timeout=600.0):
        self.steps.append(step)
        if step in self.fail:
            return Result(1, "", "failed")
        if argv[0] == "git":
            return super().run(step, argv, cwd=cwd, env={**ENV, **(env or {})}, input=input, timeout=timeout)
        if step in ("render", "render_new"):
            return Result(0, self.unit.read_text() + "\n")
        if "healthcheck.py" in " ".join(argv):
            return Result(0, HEALTHY)
        if step == "service_show":
            return Result(0, "ActiveState=active\nSubState=running\nNRestarts=0\nMainPID=7\n")
        if step == "journal":
            return Result(0, "INFO ready\n")
        return Result(0, "  ok     done\n")

    def stat(self, path):
        found = super().stat(path)
        if found and str(path).startswith(str(self.waivers)):
            return 0, found[1]
        return found

    def sleep(self, seconds):
        pass

    def now(self):
        self.clock += timedelta(seconds=1)
        return self.clock

    def name(self):
        return "crooks-os-prod-1"


class Green:
    def check(self, repository, sha):
        return GateResult(sha, GateState.GREEN, "acceptance run(s) 5 completed with success",
                          (RunFact(5, "completed", "success"),))


@pytest.fixture
def world(tmp_path, monkeypatch):
    remote = tmp_path / "github.git"
    git("init", "--quiet", "--bare", str(remote))
    work = tmp_path / "work"
    git("init", "--quiet", str(work))
    (work / "crooks-assistant" / "app").mkdir(parents=True)
    (work / ".gitignore").write_text(".env\nlogs/\n.venv/\n")
    (work / "crooks-assistant" / "app" / "store.py").write_text("DAYS = 'utc'\n")
    git("add", "-A", cwd=work)
    git("commit", "--quiet", "-m", "Seven fixes from the review (PR #95)", cwd=work)
    live = git("rev-parse", "HEAD", cwd=work)
    git("push", "--quiet", str(remote), "HEAD:refs/heads/clive/trunk", cwd=work)
    production = tmp_path / "opt"
    git("clone", "--quiet", str(remote), str(production))
    git("checkout", "--quiet", "--detach", live, cwd=production)
    (production / "crooks-assistant" / ".env").write_text("CROOKS_WRITES_ENABLED=true\n")
    (work / "crooks-assistant" / "app" / "store.py").write_text("DAYS = 'london'\n")
    git("commit", "--quiet", "-am", "Days left count London's day (PR #99)", cwd=work)
    trunk = git("rev-parse", "HEAD", cwd=work)
    git("push", "--quiet", str(remote), "HEAD:refs/heads/clive/trunk", cwd=work)
    unit = tmp_path / "etc" / "crooks-assistant.service"
    unit.parent.mkdir()
    unit.write_text("[Service]\nEnvironment=HOME=/root\n")
    settings = ReleaseSettings(enabled=True, rule="owner_waiver", dry_run=False, checkout=production,
                               state_dir=tmp_path / "state",
                               unit_path=unit, waivers_dir=tmp_path / "waivers", passkey_waivers_dir=tmp_path / "pkw",
                               passkeys_file=tmp_path / "passkeys.json", settle_s=0)
    monkeypatch.setattr(github, "git_url", lambda _repository: str(remote))
    return {"settings": settings, "remote": remote, "work": work, "production": production, "live": live,
            "trunk": trunk, "tmp": tmp_path}


def _waive(w) -> None:
    folder = w["settings"].waivers_dir
    folder.mkdir(mode=0o700)
    (folder / f"{w['trunk']}.json").write_text(json.dumps({
        "schema": authority.WAIVER_SCHEMA, "sha": w["trunk"], "repository": w["settings"].repository,
        "waives": "exact_sha_review", "given_by": "George", "given_at": "2026-10-08T01:00:00+00:00",
        "words": "waive", "source": "host", "passkey": None}))
    os.chmod(folder / f"{w['trunk']}.json", 0o600)


def _tick(w, host):
    printed: list[str] = []
    code = service.tick(host, w["settings"], token=github.Token("t0ken-for-the-local-remote"), gate=Green(),
                        pinned=True, out=printed.append)
    return code, printed


def test_a_deploy_moves_production_forward_and_pushes_its_record_to_its_branch(world):
    _waive(world)
    host = GitHost(world["settings"].waivers_dir, world["settings"].unit_path)
    code, printed = _tick(world, host)
    assert code == 0, printed
    assert git("rev-parse", "HEAD", cwd=world["production"]) == world["trunk"]
    branch = f"refs/heads/claude/deploy-{world['trunk'][:8]}-record"
    tip = git("--git-dir", str(world["remote"]), "rev-parse", branch)
    assert git("--git-dir", str(world["remote"]), "rev-parse", f"{tip}^") == world["trunk"]
    path = f"crooks-assistant/reports/deploy-{world['trunk'][:8]}.md"
    pushed = git("--git-dir", str(world["remote"]), "show", f"{tip}:{path}")
    assert pushed.startswith(f"# Deploy record — `{world['trunk'][:8]}`")
    assert "- Days left count London's day (PR #99)" in pushed
    assert git("--git-dir", str(world["remote"]), "diff", "--name-only", world["trunk"], tip) == path
    assert git("--git-dir", str(world["remote"]), "rev-parse", "refs/heads/clive/trunk") == world["trunk"], \
        "the trunk is never pushed"
    assert git("status", "--porcelain", cwd=world["production"]) == "", "the checkout is left clean"


def test_a_failure_after_the_checkout_puts_production_back_where_it_was(world):
    _waive(world)
    host = GitHost(world["settings"].waivers_dir, world["settings"].unit_path, fail={"journal"})
    code, _ = _tick(world, host)
    assert code == 1
    assert git("rev-parse", "HEAD", cwd=world["production"]) == world["live"]
    tip = git("--git-dir", str(world["remote"]), "rev-parse", f"refs/heads/claude/deploy-{world['trunk'][:8]}-record")
    assert "**rolled back**" in git("--git-dir", str(world["remote"]), "show",
                                    f"{tip}:crooks-assistant/reports/deploy-{world['trunk'][:8]}-rolled-back.md")


def test_a_reviewers_record_on_its_branch_is_read_and_a_second_record_builds_on_the_first(world):
    settings = world["settings"]
    settings.rule = "exact_sha_review"
    review = {"schema": authority.REVIEW_SCHEMA, "sha": world["trunk"], "base_sha": world["live"], "verdict": "SHIP",
              "blocking": [], "reviewer": "review session", "reviewed_at": "2026-10-08T01:30:00Z",
              "summary": "No regression."}
    work = world["work"]
    git("checkout", "--quiet", "-b", "review", cwd=work)
    (work / "crooks-assistant" / "reports").mkdir()
    (work / "crooks-assistant" / "reports" / f"review-{world['trunk'][:8]}.json").write_text(json.dumps(review))
    git("add", "-A", cwd=work)
    git("commit", "--quiet", "-m", "Review record", cwd=work)
    git("push", "--quiet", str(world["remote"]), f"HEAD:refs/heads/claude/review-{world['trunk'][:8]}-record", cwd=work)
    host = GitHost(settings.waivers_dir, settings.unit_path, fail={"journal"})
    code, printed = _tick(world, host)
    assert code == 1 and "review_read" in host.steps, printed
    first = git("--git-dir", str(world["remote"]), "rev-parse", f"refs/heads/claude/deploy-{world['trunk'][:8]}-record")
    # A person clears the failure; the next try's record is a second commit on the same branch.
    (settings.state_dir / "failed" / f"{world['trunk']}.json").unlink()
    code, printed = _tick(world, GitHost(settings.waivers_dir, settings.unit_path))
    assert code == 0, printed
    second = git("--git-dir", str(world["remote"]), "rev-parse", f"refs/heads/claude/deploy-{world['trunk'][:8]}-record")
    assert git("--git-dir", str(world["remote"]), "rev-parse", f"{second}^") == first
    assert "SHIP by review session" in git("--git-dir", str(world["remote"]), "show",
                                           f"{second}:crooks-assistant/reports/deploy-{world['trunk'][:8]}.md")


def test_the_plan_reads_real_git_and_changes_nothing_on_production(world):
    _waive(world)
    host = GitHost(world["settings"].waivers_dir, world["settings"].unit_path)
    before = git("rev-parse", "HEAD", cwd=world["production"])
    refs = git("for-each-ref", cwd=world["production"])
    printed: list[str] = []
    assert service.plan(host, world["settings"], token=github.Token(""), gate=Green(), pinned=True,
                        out=printed.append) == 0
    assert "  verdict       WOULD DEPLOY" in printed
    assert git("rev-parse", "HEAD", cwd=world["production"]) == before
    assert git("for-each-ref", cwd=world["production"]) == refs, "production's refs are untouched"
    assert not (world["settings"].state_dir / "status.json").exists()


def test_a_file_moved_out_of_a_guarded_path_is_still_seen(world):
    """Review note 9: git diff detects renames by default and lists only the new name, so a file moved out of
    deploy/ would not look guarded. The service diffs with --no-renames: the old name is listed too."""
    work, remote, production = world["work"], world["remote"], world["production"]
    unit = work / "crooks-assistant" / "deploy" / "systemd" / "crooks-assistant.service"
    unit.parent.mkdir(parents=True)
    unit.write_text("[Unit]\nDescription=CLIVE\n\n[Service]\nExecStart=/opt/crooks-os/run\nRestart=always\n")
    git("add", "-A", cwd=work)
    git("commit", "--quiet", "-m", "The unit, under deploy/", cwd=work)
    git("push", "--quiet", str(remote), "HEAD:refs/heads/clive/trunk", cwd=work)
    base = git("rev-parse", "HEAD", cwd=work)
    git("fetch", "--quiet", "origin", cwd=production)
    git("checkout", "--quiet", "--detach", base, cwd=production)
    git("mv", "crooks-assistant/deploy/systemd/crooks-assistant.service", "crooks-assistant/app/unit.service",
        cwd=work)
    git("commit", "--quiet", "-m", "The unit, moved out of deploy/", cwd=work)
    git("push", "--quiet", str(remote), "HEAD:refs/heads/clive/trunk", cwd=work)
    world["trunk"] = git("rev-parse", "HEAD", cwd=work)
    assert "R100" in git("diff", "--name-status", "-M", base, world["trunk"], cwd=work), "git sees a rename"
    _waive(world)
    host = GitHost(world["settings"].waivers_dir, world["settings"].unit_path)
    code, printed = _tick(world, host)
    assert "checkout" not in host.steps and git("rev-parse", "HEAD", cwd=production) == base
    assert "the change touches how CLIVE is installed (crooks-assistant/deploy/systemd/crooks-assistant.service)" \
        in "\n".join(printed), printed
