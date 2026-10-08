"""One tick of the release service's timer, and the plan a dry run prints.

Why it exists: this is the whole loop George approved, in the order it runs. The timer
(deploy/release/clive-release.timer) starts `python -m app.release tick` every five minutes:

    switched off             say so in the status, touch nothing else, stop
    no rule named            the same
    halted                   the same: a rollback failed, or a deploy was interrupted, and a person
                             must look first
    the lock                 one deploy at a time; a tick that finds it held does nothing
    interrupted              holding the lock, a started marker with no outcome means the last deploy
                             stopped part way: HALT, and that SHA marked so it is not tried again
    the facts and decision   app/release/facts.py and decide.py; HALT read again just before, so a
                             HALT written while this tick waited or read the facts still stops it
    dry run                  CLIVE_RELEASE_DRY_RUN: say what it would do, change nothing
    deploy                   app/release/deploy.py; then the outcome on disk (after a rollback or a
                             halt, the SHA marked so it is not tried again on its own; after a halt,
                             HALT), the record kept, the started marker removed, the record pushed
                             to its branch, and the status line George reads on CLIVE's Builds screen

`plan` is the same reading and decision with nothing written at all: not the status, not the lock,
not a record. It prints every fact, the verdict with each reason, and the steps a deploy would take.
Everything printed goes through the token's scrub first.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from app.release import deploy, github, record, state
from app.release import facts as facts_module
from app.release.decide import Decision, decide
from app.release.facts import Facts
from app.release.settings import ReleaseSettings

STOPPED = "The release service has stopped until a person looks"
_SHA = re.compile(r"^[0-9a-f]{40}$")
LINES = {
    "off": "The release service is off. Deploys are done by hand.",
    "no_rule": "The release service is on, but it deploys nothing until you say who holds deploy authority.",
}
STEPS = (
    "check production is still on {live8} and its checkout clean; the checkout and the unit's folder writable",
    "make doctor; the tailnet self-check; /health well before anything changes",
    "save the live unit, .env's and the drop-ins' fingerprints; the live build must still render the live "
    "unit, byte for byte; bring {sha8} into production's checkout; write the started marker",
    "git checkout --detach {sha8}; the new build's gap_clean_check; the new build's unit must be the live "
    "one, byte for byte",
    "make install (with the PATH and HOME the live unit was made with)",
    "wait {settle}s; /health well with no check worse; the service steady; .env and drop-ins untouched; "
    "the new process's journal clean; the unit as it was",
    "on any failure: check out {live8} again, put the saved unit back, make install, read /health",
    "keep the record and push it to {branch}; set the line on CLIVE's Builds screen",
)


def running_pinned(settings: ReleaseSettings) -> bool:
    """Whether this code runs from its own pinned copy, not from the checkout it deploys: a deploy
    must never be able to change the program that decides the next one."""
    here = Path(__file__).resolve()
    try:
        here.relative_to(settings.checkout.resolve())
    except ValueError:
        return True
    return False


def _quoted(title: str, sha: str) -> str:
    return f"“{title}”" if title else sha[:8]


def line_for(decision: Decision, facts: Facts, *, dry_run: bool) -> str:
    target = _quoted(facts.trunk_title, facts.trunk)
    if decision.state in LINES:
        return LINES[decision.state]
    if decision.state == "up_to_date":
        return f"Production runs the trunk's latest: {target}."
    if decision.state == "would_deploy":
        return f"Dry run: it would deploy {target} now. Nothing was changed." if dry_run else f"Deploying {target}."
    if decision.state == "halted":
        return STOPPED + "."
    first = decision.reasons[0] if decision.reasons else "a condition is not met"
    return f"Not deploying {target}: {first}."


def outcome_line(outcome: deploy.Outcome, facts: Facts) -> str:
    target = _quoted(facts.trunk_title, facts.trunk)
    if outcome.result == "deployed":
        return f"Deployed {target}. Open /whoami on your phone to keep it."
    if outcome.result == "rolled_back":
        return (f"Tried {target} and rolled back: {outcome.reason}. Production is back on "
                f"{_quoted(facts.live_title, facts.live)}.")
    if outcome.result == "halted":
        return (f"Tried {target}, and the rollback did not finish ({outcome.reason}). Production needs a person; "
                "the release service has stopped.")
    return f"Not deploying {target}: {outcome.reason}."


def halted_line(halted: dict) -> str:
    why = " ".join(str(halted.get("reason") or "").split())[:240] or "no reason was written"
    return f"{STOPPED}: {why}."


def _stopped(host, settings: ReleaseSettings, halted: dict, say, facts: Facts | None = None) -> int:
    line = halted_line(halted)
    _status(host, settings, "halted", line, facts)
    say(line)
    return 1


def _status(host, settings: ReleaseSettings, state_name: str, line: str, facts: Facts | None = None,
            branch: str = "") -> None:
    state.write_status(host, settings.state_dir, state=state_name, line=line, at=deploy._iso(host.now()),
                       mode="dry_run" if settings.dry_run else "live", sha=(facts.trunk if facts else ""),
                       title=(facts.trunk_title if facts else ""), branch=branch)


def tick(host, settings: ReleaseSettings, *, token: github.Token, gate=None, pinned: bool | None = None,
         out: Callable[[str], None] = print) -> int:
    def say(text: str) -> None:
        out(token.scrub(text))

    if not settings.enabled or settings.rule_named() is None:
        name = "off" if not settings.enabled else "no_rule"
        _status(host, settings, name, LINES[name])
        say(LINES[name])
        return 0
    halted = state.halted(host, settings.state_dir)
    if halted is not None:
        return _stopped(host, settings, halted, say)
    try:
        with state.Lock(settings.state_dir):
            return _locked(host, settings, token=token, gate=gate,
                           pinned=running_pinned(settings) if pinned is None else pinned, say=say)
    except state.LockHeld:
        say("Another deploy holds the lock; this tick did nothing.")
        return 0


def interrupted_reason(left: dict) -> str:
    sha = str(left.get("sha") or "")
    named = sha[:8] if _SHA.fullmatch(sha) else "a SHA its marker does not say"
    return (f"the deploy of {named} that began at {str(left.get('at') or '?')[:25]} stopped part way, after it "
            "began changing production, and left no outcome (the service was stopped, killed or timed out): "
            "production may be half deployed")


def _interrupted(host, settings: ReleaseSettings, left: dict, say) -> int:
    """The last deploy stopped part way: HALT (read back), that SHA marked failed, then its marker
    removed, since HALT now says it. A person looks, puts production right and removes HALT."""
    at, sha, reason = deploy._iso(host.now()), str(left.get("sha") or ""), interrupted_reason(left)
    state.halt(host, settings.state_dir, at=at, reason=reason, sha=sha if _SHA.fullmatch(sha) else "")
    if _SHA.fullmatch(sha):
        state.mark_failed(host, settings.state_dir, sha, at=at, reason=reason)
    halted = state.halted(host, settings.state_dir)
    if halted is not None and halted.get("reason") == reason:
        host.remove(Path(left["marker"]))
    return _stopped(host, settings, halted or {"reason": reason}, say)


def _locked(host, settings: ReleaseSettings, *, token, gate, pinned: bool, say) -> int:
    left = state.interrupted(host, settings.state_dir)
    if left is not None:
        return _interrupted(host, settings, left, say)
    facts = facts_module.gather(host, settings, token, gate=gate)
    # HALT again, now the lock is held and just before anything could change: one written after this
    # tick's first look (a person stopping it while it waited or read the facts) still stops it.
    halted = state.halted(host, settings.state_dir)
    if halted is not None:
        return _stopped(host, settings, halted, say, facts)
    failed = state.failed_before(host, settings.state_dir, facts.trunk) if facts.trunk else None
    decision = decide(settings, facts, failed=failed, pinned=pinned)
    if not decision.deploy or settings.dry_run:
        line = line_for(decision, facts, dry_run=settings.dry_run)
        _status(host, settings, decision.state, line, facts)
        say(line)
        for reason in decision.reasons[1:]:
            say(f"  also: {reason}")
        return 0
    _status(host, settings, "would_deploy", line_for(decision, facts, dry_run=False), facts)
    outcome = deploy.run(host, settings, facts)
    line = outcome_line(outcome, facts)
    if outcome.result == "refused":
        _status(host, settings, "waiting", line, facts)
        say(line)
        return 1
    if outcome.result == "halted":
        state.halt(host, settings.state_dir, at=outcome.finished_at, sha=outcome.sha,
                   reason=f"the deploy of {outcome.sha[:8]} failed ({outcome.reason}) and its rollback did not finish")
    if outcome.result in ("rolled_back", "halted"):
        state.mark_failed(host, settings.state_dir, outcome.sha, at=outcome.finished_at, reason=outcome.reason)
    text = token.scrub(record.render(settings, facts, outcome, host.name()))
    kept = record.keep(host, settings, outcome, text)
    state.finished(host, settings.state_dir, outcome.sha)       # the outcome is on disk
    pushed, how = record.publish(host, settings, token, outcome, text)
    branch = github.record_branch(outcome.sha) if pushed else ""
    state_name = {"deployed": "deployed", "rolled_back": "rolled_back"}.get(outcome.result, "halted")
    _status(host, settings, state_name, line, facts, branch=branch)
    say(line)
    say(f"The record is at {kept}; {how}.")
    return 0 if outcome.result == "deployed" else 1


def plan(host, settings: ReleaseSettings, *, token: github.Token, requested: str | None = None, gate=None,
         pinned: bool | None = None, out: Callable[[str], None] = print) -> int:
    """The dry run: every fact, the verdict and its reasons, the steps a deploy would take; nothing written."""
    def say(text: str) -> None:
        out(token.scrub(text))

    facts = facts_module.gather(host, settings, token, gate=gate)
    failed = state.failed_before(host, settings.state_dir, facts.trunk) if facts.trunk else None
    held = state.lock_held(settings.state_dir)
    # A started marker while nobody holds the lock is a deploy that stopped part way: the next tick halts.
    left = None if held else state.interrupted(host, settings.state_dir)
    halted = state.halted(host, settings.state_dir) or ({"reason": interrupted_reason(left)} if left else None)
    decision = decide(settings, facts, requested=requested, lock_held=held, halted=halted, failed=failed,
                      pinned=running_pinned(settings) if pinned is None else pinned)
    say("Release plan: a dry run. Nothing on production changes, nothing is pushed, no status is written.")
    say(f"  trunk head    {facts.trunk[:8] or '?'}  {facts.trunk_title}")
    say(f"  production    {facts.live[:8] or '?'}  {facts.live_title}")
    say(f"  switched on   {'yes' if settings.enabled else 'no'}   dry run: {'yes' if settings.dry_run else 'no'}")
    say(f"  rule          {settings.rule_named() or 'none named'}")
    if facts.acceptance is not None:
        say(f"  acceptance    {facts.acceptance.state.value}: {facts.acceptance.detail}")
    if facts.authority is not None:
        say(f"  authority     {'yes' if facts.authority.ok else 'no'}: {facts.authority.reason}")
    if facts.changed:
        say(f"  the change    {len(facts.changed)} files, {len(facts.commits)} trunk commits")
    if decision.deploy:
        say("  verdict       WOULD DEPLOY")
        values = {"live8": facts.live[:8], "sha8": facts.trunk[:8], "settle": int(settings.settle_s),
                  "branch": github.record_branch(facts.trunk)}
        for number, step in enumerate(STEPS, start=1):
            say(f"    {number}. {step.format(**values)}")
        return 0
    if decision.state == "up_to_date":
        say("  verdict       NOTHING TO DEPLOY: production runs the trunk's head")
        return 1
    say("  verdict       WOULD NOT DEPLOY")
    for reason in decision.reasons:
        say(f"    - {reason}")
    return 1
