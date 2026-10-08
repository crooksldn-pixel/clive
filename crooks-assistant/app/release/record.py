"""The deploy record: what was deployed (or tried and rolled back), on whose authority, what was checked,
and what to do to undo it, in the shape of reports/deploy-<sha8>.md, pushed to its own branch.

Why it exists: the three records written by hand (66d3e05d, cac1a9e7, b33ccbc2) are how anyone
learns what production runs and how to roll it back; scripts/map.py reads them for MAP.md. A deploy
the service makes leaves the same record: kept in its state folder, and pushed as one commit on top
of the deployed SHA to claude/deploy-<sha8>-record, ready to merge into the trunk like theirs.

Its words are built here from the outcome's own fields: SHAs, the trunk's commit titles, check
names, counts, the installer's status lines. Never a journal line, a /health detail, anything a
customer wrote or George's free-text waiver words, because the repository is public. A deploy that did not hold is recorded as
deploy-<sha8>-rolled-back.md (or -halted.md), a name scripts/map.py does not take for production.
"""

from __future__ import annotations

from pathlib import Path

from app.release import facts as facts_module
from app.release import github
from app.release.deploy import Outcome
from app.release.facts import Facts
from app.release.settings import ReleaseSettings

PROCEDURE = '`crooks-assistant/docs/DEPLOY_LINUX.md`, "Deploying a new build"'


def file_name(outcome: Outcome) -> str:
    short = outcome.sha[:8]
    return {"deployed": f"deploy-{short}.md", "rolled_back": f"deploy-{short}-rolled-back.md"}.get(
        outcome.result, f"deploy-{short}-{outcome.result.replace('_', '-')}.md")


def _clock(iso: str) -> str:
    return iso[11:19] if len(iso) >= 19 else "?"


def _table(rows: list[tuple[str, str]], head: tuple[str, str] = ("Check", "Result")) -> list[str]:
    out = [f"| {head[0]} | {head[1]} |", "|---|---|"]
    out += [f"| {a} | {b.replace('|', '/')} |" for a, b in rows]
    return out


def _authority(settings: ReleaseSettings, facts: Facts) -> list[str]:
    lines = ["## The authority for this deploy", ""]
    auth, gate = facts.authority, facts.acceptance
    lines.append(f"- **Rule:** `{settings.rule_named()}` (`CLIVE_RELEASE_RULE`).")
    if auth is not None and auth.ok and auth.kind == "review":
        base = str(auth.detail.get("base_sha") or "")
        lines.append(f"- **Exact-SHA review:** SHIP by {auth.by}, {auth.at}, from {auth.source}; measured against "
                     f"`{base[:8]}`. {auth.detail.get('summary') or ''}".rstrip())
    elif auth is not None and auth.ok:
        # Never his free-text words: they could carry a customer's name, and this record is pushed to a
        # public repository. They stay in the waiver file on the server.
        lines.append(f"- **The owner's waiver** of the exact-SHA review, for exactly this SHA: {auth.reason}, "
                     f"{auth.at}.")
    if gate is not None:
        runs = ", ".join(f"`{run.id}`" for run in gate.runs)
        lines.append(f"- **Acceptance on the exact SHA:** {gate.state.value}, run(s) {runs or 'none'}: {gate.detail}.")
    return lines + [""]


def render(settings: ReleaseSettings, facts: Facts, outcome: Outcome, host_name: str) -> str:
    sha, prev = outcome.sha, outcome.previous
    day = outcome.started_at[:10]
    if outcome.result == "deployed":
        when = (f"**Deployed:** {day}, install {_clock(outcome.install_started_at)}–"
                f"{_clock(outcome.install_finished_at)} UTC, by the release service.")
        verdict = ("Installed, running, `/health` well with every check as before. One step outstanding: the "
                   "owner's own phone `/whoami`.")
    elif outcome.result == "rolled_back":
        when = f"**Tried:** {day} {_clock(outcome.started_at)} UTC by the release service, and **rolled back**."
        verdict = f"Not deployed: {outcome.reason}. Production is back on `{prev[:8]}` and well."
    else:
        when = f"**Tried:** {day} {_clock(outcome.started_at)} UTC by the release service. **The rollback failed.**"
        verdict = (f"{outcome.reason}; then the rollback did not complete. The release service has stopped itself "
                   f"(HALT). A person must look at production now.")
    lines = [
        f"# Deploy record — `{sha[:8]}` on `{host_name}`", "",
        when,
        f"**Host:** `{host_name}`, checkout `{settings.checkout}`.",
        f"**Procedure:** {PROCEDURE}, run by the release service (`app/release/`, `docs/RELEASE_SERVICE.md`).", "",
        "| | |", "|---|---|",
        f"| **Deployed SHA** | `{sha}` (`clive/trunk` head) — {facts.trunk_title} |"
        if outcome.result == "deployed" else f"| **Tried SHA** | `{sha}` (`clive/trunk` head) — {facts.trunk_title} |",
        f"| **Previous SHA** | `{prev}` — {facts.live_title} |",
    ]
    if outcome.result == "deployed":
        lines.append(f"| **Build id now live** | `{outcome.after.get('build') or '?'}` "
                     f"(was `{outcome.before.get('build') or '?'}`) |")
    lines += [f"| **Outcome** | {verdict} |", ""]
    lines += _authority(settings, facts)
    saved = outcome.before.get("unit_saved") or "(not saved)"
    lines += ["## Rollback target", "", "Both halves were captured **before anything changed**:", "",
              *_table([("Code", f"`git -C {settings.checkout} checkout --detach {prev}`"),
                       ("Unit — the copy to restore", f"`{saved}` (main unit only, sha256 "
                                                      f"`{str(outcome.before.get('unit_sha256') or '')[:8]}…`)")],
                      ("What", "Where")), ""]
    if outcome.result == "deployed":
        lines += ["Rollback, if it is ever wanted:", "", "```bash",
                  f"git -C {settings.checkout} checkout --detach {prev}",
                  f"install -m 0644 {saved} \\", f"  {settings.unit_path}",
                  f"cd {settings.assistant} && make install", "```", ""]
    def row(step) -> tuple[str, str]:
        return _LABELS.get(step.name, step.name), ("ok — " if step.ok else "**FAILED** — ") + step.said

    before = [row(s) for s in outcome.steps if s.name not in _CHANGE | _AFTER]
    change = [row(s) for s in outcome.steps if s.name in _CHANGE]
    after = [row(s) for s in outcome.steps if s.name in _AFTER]
    lines += ["## What was checked before anything changed", "", *_table(before), ""]
    if change:
        lines += ["## The install", "", *_table(change, ("Step", "Result")), ""]
    if outcome.install_lines:
        lines += ["`make install`, its own status lines:", "", "```", *outcome.install_lines, "```", ""]
    if after:
        rows = list(after)
        if outcome.result == "deployed":
            rows.append(("Switches", "untouched — no `.env` line and no credential was written by this deploy"))
            refusals = outcome.after.get("journal_refusals") or 0
            if refusals:
                rows.append(("Refusals in the journal", f"{refusals} (the door refusing a caller; not a failure)"))
        lines += ["## Verification after the install", "", *_table(rows), ""]
    if outcome.rollback:
        lines += ["## The rollback", "", f"Why: {outcome.reason}.", "",
                  *_table([row(s) for s in outcome.rollback], ("Step", "Result")), ""]
    if outcome.result == "deployed":
        lines += ["## Outstanding", "",
                  "- **The owner's phone `/whoami`.** Open `/whoami` at CLIVE's address on the owner's phone; it must "
                  "answer `\"owner\": true`, and `journalctl -u crooks-assistant.service | grep 'whoami: id=<the check "
                  "it showed>'` must show `through=tailscale owner=true refusal=none` with that same token. The deploy "
                  "is **kept** only once that line appears.", ""]
    commits = facts.commits[:facts_module.MAX_COMMITS]
    if commits:
        more = len(facts.commits) - len(commits)
        lines += ["## What this build changes", "",
                  f"`clive/trunk` from `{prev[:8]}` to `{sha[:8]}`, newest first:", "",
                  *[f"- {subject}" for subject in commits],
                  *([f"- and {more} more"] if more > 0 else []), ""]
    return "\n".join(lines)


_CHANGE = {"checkout", "gap_check", "render_new", "install"}
_AFTER = {"health_after", "service_after", "switches_after", "journal", "unit_after"}
_LABELS = {
    "precheck_head": "Live SHA read from git", "precheck_tree": "Working tree", "writable": "Writable",
    "doctor": "`make doctor`", "tailnet": "`tailnet_self_check()`", "health_before": "Baseline `/health`",
    "capture_unit": "Live unit read", "capture_saved": "Live unit saved", "render": "Live build re-renders the unit",
    "fetch_into_checkout": "Target fetched", "started": "Started marker",
    "checkout": "`git checkout --detach`", "gap_check": "`scripts/gap_clean_check.py`",
    "render_new": "New build's unit, before `make install`", "install": "`make install`",
    "health_after": "`/health`", "service_after": "Service state", "switches_after": "`.env` and drop-ins",
    "journal": "Journal since restart", "unit_after": "Main unit",
    "rollback_checkout": "Code", "rollback_unit": "Unit",
    "rollback_reload": "systemd", "rollback_install": "`make install` on the previous SHA",
    "rollback_health": "`/health`",
}


def keep(host, settings: ReleaseSettings, outcome: Outcome, text: str) -> Path:
    """The record in the service's own folder, whatever happens to the push."""
    from app.release import state

    path = state.deploy_dir(settings.state_dir, outcome.sha) / file_name(outcome)
    host.write(path, text.encode("utf-8"), 0o644)
    return path


def publish(host, settings: ReleaseSettings, token: github.Token, outcome: Outcome, text: str) -> tuple[bool, str]:
    """One commit on top of the deployed SHA (or on the branch's own head, if a record is there already)
    adding the record, pushed to claude/deploy-<sha8>-record and nowhere else."""
    branch = github.record_branch(outcome.sha)
    if not token.present:
        return False, "the release service has no GitHub token, so the record was not pushed"
    url = github.git_url(settings.repository)
    path = f"crooks-assistant/reports/{file_name(outcome)}"
    blob = facts_module.git_cache(host, settings, "record_blob", "hash-object", "-w", "--stdin", input=text)
    listed = facts_module.git_cache(host, settings, "record_listed", "ls-remote", url, f"refs/heads/{branch}",
                                    token=token, timeout=facts_module.NETWORK_S)
    if not blob.ok or not listed.ok:
        return False, "the record could not be prepared for GitHub"
    parent = outcome.sha
    if listed.out.strip():
        fetched = facts_module.git_cache(host, settings, "record_fetch", "fetch", "--quiet", "--no-tags", url,
                                         f"+refs/heads/{branch}:refs/clive-release/record", token=token,
                                         timeout=facts_module.NETWORK_S)
        head = facts_module.git_cache(host, settings, "record_head", "rev-parse", "--verify",
                                      "refs/clive-release/record^{commit}")
        if not fetched.ok or not head.ok:
            return False, f"the existing {branch} could not be read, so the record was not pushed"
        parent = head.out.strip()
    index = {"GIT_INDEX_FILE": str(settings.state_dir / "record.index")}
    who = {"GIT_AUTHOR_NAME": "CLIVE release service", "GIT_AUTHOR_EMAIL": f"clive-release@{host.name()}",
           "GIT_COMMITTER_NAME": "CLIVE release service", "GIT_COMMITTER_EMAIL": f"clive-release@{host.name()}"}
    read = facts_module.git_cache(host, settings, "record_tree_read", "read-tree", parent, env=index)
    added = facts_module.git_cache(host, settings, "record_tree_add", "update-index", "--add", "--cacheinfo",
                                   f"100644,{blob.out.strip()},{path}", env=index)
    tree = facts_module.git_cache(host, settings, "record_tree", "write-tree", env=index)
    host.remove(settings.state_dir / "record.index")
    if not (read.ok and added.ok and tree.ok):
        return False, "the record's commit could not be made"
    title = {"deployed": "deployed", "rolled_back": "tried and rolled back"}.get(outcome.result, "rollback failed")
    commit = facts_module.git_cache(host, settings, "record_commit", "commit-tree", tree.out.strip(), "-p", parent,
                                    "-m", f"Deploy record: {outcome.sha[:8]} {title} by the release service", env=who)
    if not commit.ok:
        return False, "the record's commit could not be made"
    try:
        refspec = github.record_refspec(commit.out.strip(), branch)
    except ValueError as exc:
        return False, str(exc)
    pushed = facts_module.git_cache(host, settings, "record_push", "push", "--quiet", url, refspec, token=token,
                                    timeout=facts_module.NETWORK_S)
    return (True, f"pushed to {branch}") if pushed.ok else (False, f"the push to {branch} was refused (exit {pushed.code})")
