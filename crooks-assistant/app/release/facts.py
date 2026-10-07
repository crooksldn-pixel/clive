"""What is true now, read and never changed: the trunk's head, what production runs, how they relate,
what the change touches, GitHub acceptance on the exact SHA, and the authorisation the rule asks for.

Why it exists: every decision the release service makes is made from these facts and nothing else,
so they are gathered in one place, each by the read DEPLOY_LINUX.md's procedure and the three deploy
records make by hand: the live SHA from git (never from a document), the target's place on the
trunk, a forward move only, the paths the change touches, and acceptance on exactly that commit.

The trunk is read into the service's own bare copy of the repository in its state folder
(repo.git), never into production's checkout, so working out a plan changes nothing production runs.
A fact that cannot be read is a `problem`, said in words, and a problem never deploys.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.orchestrator.github_acceptance import GateResult
from app.release import authority as authority_module
from app.release import github
from app.release.authority import Authority
from app.release.settings import EXACT_SHA_REVIEW, OWNER_WAIVER, TRUNK, ReleaseSettings

_SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_COMMITS = 40

# Paths whose change makes a deploy a hand deploy: how CLIVE is installed (deploy/, the Makefile, and
# the two scripts that render and install the unit) and what it needs installed (its dependencies;
# `make install` installs no package). The hand deploys' records check deploy/, the unit, .env and the
# Makefile before each deploy; the installer's own code and the dependencies are added here because a
# program cannot ask, as a person can, whether a change to them is harmless.
GUARDED = (
    "crooks-assistant/deploy/",
    "crooks-assistant/Makefile",
    "crooks-assistant/scripts/install_systemd.py",
    "crooks-assistant/scripts/launch_common.py",
    "crooks-assistant/pyproject.toml",
    "crooks-assistant/uv.lock",
    "crooks-assistant/requirements",
)


def guarded(path: str) -> bool:
    return any(path == g or path.startswith(g) for g in GUARDED) or Path(path).name.startswith(".env")


@dataclass
class Facts:
    trunk: str = ""
    live: str = ""
    trunk_title: str = ""
    live_title: str = ""
    forward: bool | None = None          # production's SHA is an ancestor of the trunk's head
    changed: list[str] = field(default_factory=list)
    dirty: list[str] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    acceptance: GateResult | None = None
    authority: Authority | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def up_to_date(self) -> bool:
        return bool(self.trunk) and self.trunk == self.live

    @property
    def guarded(self) -> list[str]:
        return [path for path in self.changed if guarded(path)]


def cache(settings: ReleaseSettings) -> Path:
    return settings.state_dir / "repo.git"


def git_cache(host, settings: ReleaseSettings, step: str, *args: str, token: github.Token | None = None,
              env: dict[str, str] | None = None, input: str | None = None):
    argv = ["git", *(token.git_config() if token is not None else []), "--git-dir", str(cache(settings)), *args]
    return host.run(step, argv, env={**(token.env() if token is not None else {}), **(env or {})}, input=input,
                    timeout=900)


def git_checkout(host, settings: ReleaseSettings, step: str, *args: str):
    return host.run(step, ["git", "-C", str(settings.checkout), *args], timeout=300)


def _sha(text: str) -> str:
    value = (text or "").strip()
    return value if _SHA.fullmatch(value) else ""


def _title(host, settings, step: str, sha: str) -> str:
    out = git_cache(host, settings, step, "log", "-1", "--format=%s", sha)
    return authority_module._line(out.out, 120) if out.ok else ""


def refresh_trunk(host, settings: ReleaseSettings, token: github.Token, facts: Facts) -> None:
    """The service's own copy of clive/trunk, fetched from GitHub; its head into `facts.trunk`."""
    if host.read(cache(settings) / "HEAD") is None:
        made = host.run("cache_init", ["git", "init", "--quiet", "--bare", str(cache(settings))])
        if not made.ok:
            facts.problems.append("the release service's copy of the repository could not be made")
            return
    fetched = git_cache(host, settings, "fetch_trunk", "fetch", "--quiet", "--no-tags",
                        github.git_url(settings.repository), f"+refs/heads/{TRUNK}:refs/heads/{TRUNK}", token=token)
    if not fetched.ok:
        facts.problems.append(f"{TRUNK} could not be fetched from GitHub")
        return
    facts.trunk = _sha(git_cache(host, settings, "trunk_head", "rev-parse", "--verify",
                                 f"refs/heads/{TRUNK}^{{commit}}").out)
    if not facts.trunk:
        facts.problems.append(f"{TRUNK}'s head could not be read")


def read_production(host, settings: ReleaseSettings, facts: Facts) -> None:
    """What production runs, from git in its checkout, and whether that checkout has local changes."""
    facts.live = _sha(git_checkout(host, settings, "live_head", "rev-parse", "--verify", "HEAD^{commit}").out)
    if not facts.live:
        facts.problems.append("the SHA production runs could not be read from its checkout")
        return
    status = git_checkout(host, settings, "live_status", "status", "--porcelain")
    if not status.ok:
        facts.problems.append("whether production's checkout has local changes could not be read")
        return
    facts.dirty = [line[3:] for line in status.out.splitlines() if line.strip()]


def read_change(host, settings: ReleaseSettings, facts: Facts) -> None:
    """How production's SHA and the trunk's head relate, and what the change between them touches."""
    if not facts.trunk or not facts.live or facts.up_to_date:
        return
    known = git_cache(host, settings, "live_known", "cat-file", "-e", f"{facts.live}^{{commit}}")
    if not known.ok:
        facts.forward = False
        return
    ancestry = git_cache(host, settings, "ancestry", "merge-base", "--is-ancestor", facts.live, facts.trunk)
    if ancestry.code not in (0, 1):
        facts.problems.append("whether production is behind the trunk could not be worked out")
        return
    facts.forward = ancestry.code == 0
    if not facts.forward:
        return
    diff = git_cache(host, settings, "diff", "diff", "--name-only", facts.live, facts.trunk)
    if not diff.ok:
        facts.problems.append("what the change touches could not be listed")
        return
    facts.changed = [line.strip() for line in diff.out.splitlines() if line.strip()]
    log = git_cache(host, settings, "commits", "log", "--first-parent", "--format=%s", f"-n{MAX_COMMITS + 1}",
                    f"{facts.live}..{facts.trunk}")
    facts.commits = [authority_module._line(line, 160) for line in log.out.splitlines() if line.strip()] if log.ok else []


def read_titles(host, settings: ReleaseSettings, facts: Facts) -> None:
    if facts.trunk:
        facts.trunk_title = _title(host, settings, "trunk_title", facts.trunk)
    if facts.live:
        facts.live_title = (_title(host, settings, "live_title", facts.live) if facts.live != facts.trunk
                            else facts.trunk_title)


def read_review(host, settings: ReleaseSettings, token: github.Token, facts: Facts) -> Authority:
    """The reviewer's record for exactly the trunk's head, from its branch on GitHub."""
    branch = github.review_branch(facts.trunk)
    listed = git_cache(host, settings, "review_listed", "ls-remote", github.git_url(settings.repository),
                       f"refs/heads/{branch}", token=token)
    if not listed.ok:
        facts.problems.append("whether a review record exists could not be asked of GitHub")
        return Authority(False, "the review record could not be looked for")
    if not listed.out.strip():
        return Authority(False, f"no review record for this SHA (no branch {branch})")
    fetched = git_cache(host, settings, "review_fetch", "fetch", "--quiet", "--no-tags",
                        github.git_url(settings.repository), f"+refs/heads/{branch}:refs/clive-release/review",
                        token=token)
    if not fetched.ok:
        facts.problems.append("the review record's branch could not be fetched")
        return Authority(False, "the review record could not be read")
    shown = git_cache(host, settings, "review_read", "show",
                      f"refs/clive-release/review:{authority_module.review_path(facts.trunk)}")
    if not shown.ok:
        return Authority(False, f"the branch {branch} holds no {authority_module.review_path(facts.trunk)}")

    def behind_production(base: str) -> bool:
        if base == facts.live:
            return True
        return git_cache(host, settings, "review_base", "merge-base", "--is-ancestor", base, facts.live).code == 0

    found = authority_module.check_review(authority_module.parse(shown.out.encode("utf-8")), facts.trunk,
                                          base_is_behind_production=behind_production)
    if found.ok:
        found = Authority(True, found.reason, kind=found.kind, by=found.by, at=found.at,
                          source=f"branch {branch}", detail=found.detail)
    return found


def gather(host, settings: ReleaseSettings, token: github.Token, *, gate=None) -> Facts:
    """Every fact a decision needs, read in the order the hand deploy reads them."""
    facts = Facts()
    refresh_trunk(host, settings, token, facts)
    read_production(host, settings, facts)
    read_change(host, settings, facts)
    read_titles(host, settings, facts)
    if not facts.trunk or facts.up_to_date or facts.forward is not True:
        return facts
    facts.acceptance = github.acceptance(token, settings.repository, facts.trunk, gate)
    rule = settings.rule_named()
    if rule == EXACT_SHA_REVIEW:
        facts.authority = read_review(host, settings, token, facts)
    elif rule == OWNER_WAIVER:
        facts.authority = authority_module.waiver(host, settings, facts.trunk)
    return facts
