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

Deploy now (DEC-072, the owner's rulings 6 to 8 of 8 October). George approves a deploy in CLIVE with
his passkey; CLIVE writes the waiver into the folder clive-release-now.path watches, and systemd starts
a tick at once (no timer wait). A waiver that arrives while a tick is already running (systemd folds
the trigger's start into it) is seen by the same tick, which looks once more if it began no deploy
itself; clive-release.service's time limit covers that second look (tests/test_release_service.py). The tick says each stage on the status as it is
reached (`deploy` in status.json: started, checks, installing, health, then done, rolled back with
why, halted, or refused with why), marks the approval used before anything changes, and says
`ready_for` when the only thing a deploy of the trunk's head lacks is his approval, which is when
CLIVE offers him the hold.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from app.release import deploy, github, record, state
from app.release import facts as facts_module
from app.release.authority import Authority
from app.release.decide import Decision, decide
from app.release.facts import Facts
from app.release.settings import OWNER_WAIVER, ReleaseSettings

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


def _stopped(host, settings: ReleaseSettings, halted: dict, say, facts: Facts | None = None, **extra) -> int:
    line = halted_line(halted)
    _status(host, settings, "halted", line, facts, **extra)
    say(line)
    return 1


def _status(host, settings: ReleaseSettings, state_name: str, line: str, facts: Facts | None = None,
            branch: str = "", ready_for: str = "", **deploy_now) -> None:
    state.write_status(host, settings.state_dir, state=state_name, line=line, at=deploy._iso(host.now()),
                       mode="dry_run" if settings.dry_run else "live", sha=(facts.trunk if facts else ""),
                       title=(facts.trunk_title if facts else ""), branch=branch, rule=settings.rule_named() or "",
                       ready_for=ready_for, **deploy_now)


def ready_for(settings: ReleaseSettings, facts: Facts, decision: Decision, *, failed, pinned: bool) -> str:
    """The trunk's head, when George's approval is the one thing its deploy lacks: the same decision,
    with the authorisation granted, would deploy. Only under owner_waiver, the rule his hold answers."""
    if decision.deploy or decision.state != "waiting" or settings.rule_named() != OWNER_WAIVER or not facts.trunk:
        return ""
    granted = replace(facts, authority=Authority(True, "approved in CLIVE", kind="waiver"))
    return facts.trunk if decide(settings, granted, failed=failed, pinned=pinned).deploy else ""


def _approval(facts: Facts) -> str:
    """The approval George gave in CLIVE that authorises this deploy, by its id; "" for any other kind."""
    found = facts.authority.detail.get("approval") if facts.authority is not None and facts.authority.ok else ""
    return found if isinstance(found, str) else ""


def _waivers(host, settings: ReleaseSettings) -> str:
    """A fingerprint of the approvals waiting in CLIVE's folder: a change while a tick runs is a new one."""
    seen = hashlib.sha256()
    for path in host.files(settings.passkey_waivers_dir, "*.json"):
        seen.update(path.name.encode("utf-8") + b"\x00" + hashlib.sha256(host.read(path) or b"").digest())
    return seen.hexdigest()


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
    pinned = running_pinned(settings) if pinned is None else pinned
    try:
        with state.Lock(settings.state_dir):
            before = _waivers(host, settings)
            code, began = _locked(host, settings, token=token, gate=gate, pinned=pinned, say=say)
            # His approval arrived while this tick ran: systemd folded the trigger's start into this tick,
            # so nothing else would act on it until the timer. Once more, if this tick began no deploy.
            if not began and settings.rule_named() == OWNER_WAIVER and _waivers(host, settings) != before:
                say("An approval arrived while this tick ran; looking again.")
                code, _ = _locked(host, settings, token=token, gate=gate, pinned=pinned, say=say)
            return code
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
    # The deploy CLIVE was following stopped part way: it ends here, halted, with why.
    extra = {}
    last = (state.read_status(host, settings.state_dir) or {}).get("deploy")
    if isinstance(last, dict) and last.get("sha") == sha and not last.get("end"):
        extra["deploy"] = {**last, "end": "halted", "reason": reason[:300],
                           "steps": [*(last.get("steps") or []), ["halted", at]][:12]}
    return _stopped(host, settings, halted or {"reason": reason}, say, **extra)


def _locked(host, settings: ReleaseSettings, *, token, gate, pinned: bool, say) -> tuple[int, bool]:
    """One look, holding the lock: (the exit code, whether a live deploy began)."""
    left = state.interrupted(host, settings.state_dir)
    if left is not None:
        return _interrupted(host, settings, left, say), False
    facts = facts_module.gather(host, settings, token, gate=gate)
    # HALT again, now the lock is held and just before anything could change: one written after this
    # tick's first look (a person stopping it while it waited or read the facts) still stops it.
    halted = state.halted(host, settings.state_dir)
    if halted is not None:
        return _stopped(host, settings, halted, say, facts), False
    failed = state.failed_before(host, settings.state_dir, facts.trunk) if facts.trunk else None
    decision = decide(settings, facts, failed=failed, pinned=pinned)
    approval = _approval(facts)
    if not decision.deploy or settings.dry_run:
        line = line_for(decision, facts, dry_run=settings.dry_run)
        extra = {}
        if decision.deploy and approval:
            # His hold, answered in dry run: the deploy CLIVE follows ends here, having changed nothing.
            extra["deploy"] = state.deploy_record(sha=facts.trunk, title=facts.trunk_title, approval=approval,
                                                  steps=[("started", deploy._iso(host.now()))], end="dry_run",
                                                  reason=line)
        _status(host, settings, decision.state, line, facts,
                ready_for=ready_for(settings, facts, decision, failed=failed, pinned=pinned), **extra)
        say(line)
        for reason in decision.reasons[1:]:
            say(f"  also: {reason}")
        return 0, False
    return _deploy(host, settings, facts, decision, approval, token=token, say=say), True


def _deploy(host, settings: ReleaseSettings, facts: Facts, decision: Decision, approval: str, *, token, say) -> int:
    """The live deploy: the approval spent, each stage on the status as it is reached, the outcome."""
    steps = [("started", deploy._iso(host.now()))]

    def followed(end: str = "", reason: str = "", branch: str = "") -> dict:
        return state.deploy_record(sha=facts.trunk, title=facts.trunk_title, approval=approval, steps=steps,
                                   end=end, reason=reason, branch=branch)

    if approval and not state.spend_approval(host, settings.state_dir, approval, sha=facts.trunk,
                                             at=steps[0][1]):
        steps.append(("refused", steps[0][1]))
        line = (f"Not deploying {_quoted(facts.trunk_title, facts.trunk)}: the approval could not be marked as "
                "used, so it was not used. Nothing was changed.")
        _status(host, settings, "waiting", line, facts, deploy=followed("refused", "the approval could not be marked "
                                                                                 "as used, so it was not used"))
        say(line)
        return 1
    _status(host, settings, "would_deploy", line_for(decision, facts, dry_run=False), facts, deploy=followed())

    def progress(stage: str) -> None:
        steps.append((stage, deploy._iso(host.now())))
        _status(host, settings, "would_deploy", line_for(decision, facts, dry_run=False), facts, deploy=followed())

    outcome = deploy.run(host, settings, facts, progress=progress)
    line = outcome_line(outcome, facts)
    if outcome.result == "refused":
        steps.append(("refused", outcome.finished_at))
        _status(host, settings, "waiting", line, facts, deploy=followed("refused", outcome.reason))
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
    end = {"deployed": "done", "rolled_back": "rolled_back"}.get(outcome.result, "halted")
    steps.append((end, outcome.finished_at))
    _status(host, settings, state_name, line, facts, branch=branch,
            deploy=followed(end, "" if end == "done" else outcome.reason, branch))
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
