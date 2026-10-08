"""Deploy or not: one pure function from the facts to a decision, with every reason in plain words.

Why it exists: the brief's conditions, all of them, in one place a test can drive without a server.
A deploy happens only when every one of these holds, and each one that does not is a sentence. Each
is required positively: a fact that was never read is not a reason to go ahead, so production known,
forward known to be true, acceptance known green and the authorisation known present are each asked
for in so many words (`_unproven`), whatever else was or was not recorded as a problem.

    switched on (CLIVE_RELEASE_ENABLED), and a rule named (CLIVE_RELEASE_RULE)
    not halted by a rollback that failed, running from its own pinned copy, the lock free
    every fact read; the SHA asked about is clive/trunk's head; production is behind it on the trunk
    production's checkout has no local changes; the change does not touch how CLIVE is installed,
    nor how it is checked (.github/, where the acceptance workflow lives)
    the SHA was not tried before and rolled back, halted or stopped part way
    GitHub acceptance green on exactly that SHA, and the authorisation the rule asks for
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.release.facts import Facts
from app.release.settings import ReleaseSettings

MAX_PATHS_NAMED = 5


@dataclass(frozen=True)
class Decision:
    deploy: bool
    state: str                      # off, no_rule, halted, up_to_date, waiting, would_deploy
    reasons: tuple[str, ...] = ()


def _paths(paths: list[str]) -> str:
    named = ", ".join(paths[:MAX_PATHS_NAMED])
    more = len(paths) - MAX_PATHS_NAMED
    return named + (f" and {more} more" if more > 0 else "")


def decide(settings: ReleaseSettings, facts: Facts, *, requested: str | None = None, lock_held: bool = False,
           halted: dict[str, Any] | None = None, failed: dict[str, Any] | None = None,
           pinned: bool = True) -> Decision:
    reasons: list[str] = []
    if not settings.enabled:
        reasons.append("the release service is switched off (CLIVE_RELEASE_ENABLED is off)")
    if settings.rule_named() is None:
        reasons.append(f"nobody has been named to hold deploy authority (CLIVE_RELEASE_RULE is "
                       f"'{(settings.rule or '')[:40]}', not exact_sha_review or owner_waiver)")
    if halted is not None:
        reasons.append(f"a deploy failed and could not be rolled back, or stopped part way "
                       f"({str(halted.get('reason') or '')[:240]}): a person must look, then remove "
                       f"{settings.state_dir}/HALT")
    if not pinned:
        reasons.append("the release service is running from the checkout it deploys; it runs only from its own "
                       "pinned copy (docs/RELEASE_SERVICE.md)")
    if lock_held:
        reasons.append("another deploy holds the lock")
    reasons.extend(facts.problems)
    if requested is not None and requested != facts.trunk:
        reasons.append(f"{requested[:12] or 'nothing'} is not clive/trunk's head"
                       f"{f' ({facts.trunk[:8]})' if facts.trunk else ''}: only the trunk's head is deployed")
    if facts.up_to_date and not reasons:
        return Decision(False, "up_to_date")
    if facts.forward is False:
        reasons.append(f"production runs {facts.live[:8]}, which is not behind the trunk's head on the trunk, so a "
                       "deploy would go backwards or sideways: a person must look")
    if facts.dirty:
        reasons.append(f"production's checkout has local changes ({_paths(facts.dirty)}): a person must look first")
    installs = [path for path in facts.guarded if path not in facts.checks_changed]
    if installs:
        reasons.append(f"the change touches how CLIVE is installed ({_paths(installs)}): that deploy stays a "
                       "hand deploy (DEPLOY_LINUX.md)")
    if facts.checks_changed:
        reasons.append(f"the change touches how CLIVE is checked ({_paths(facts.checks_changed)}), so its own "
                       "acceptance run cannot vouch for it: that deploy stays a hand deploy (DEPLOY_LINUX.md)")
    if failed is not None:
        reasons.append(f"this SHA was tried at {str(failed.get('at') or '?')[:25]} and did not hold "
                       f"({str(failed.get('reason') or '')[:200]}); it is not tried again on its own")
    if facts.trunk and not facts.up_to_date and facts.forward:
        if facts.acceptance is None:
            reasons.append("GitHub acceptance on this SHA was not asked")
        elif not facts.acceptance.green:
            reasons.append(f"GitHub acceptance on this SHA is {facts.acceptance.state.value}: "
                           f"{facts.acceptance.detail}")
        if facts.authority is None:
            if settings.rule_named() is not None:
                reasons.append("no authorisation was looked for")
        elif not facts.authority.ok:
            reasons.append(facts.authority.reason)
    if not settings.enabled:
        return Decision(False, "off", tuple(reasons))
    if settings.rule_named() is None:
        return Decision(False, "no_rule", tuple(reasons))
    if halted is not None:
        return Decision(False, "halted", tuple(reasons))
    unproven = _unproven(facts)
    if reasons or unproven:
        return Decision(False, "waiting", tuple(reasons) or tuple(unproven))
    return Decision(True, "would_deploy")


def _unproven(facts: Facts) -> list[str]:
    """Each condition a deploy needs that is not positively known to hold, in words. Empty only when
    the trunk's head and production's SHA are both known, production is known to be behind it on the
    trunk, acceptance on it is known green and the rule's authorisation is known present."""
    missing = []
    if not facts.trunk:
        missing.append("clive/trunk's head is not known")
    if not facts.live:
        missing.append("the SHA production runs is not known")
    if facts.forward is not True:
        missing.append("it is not known that production is behind the trunk's head on the trunk")
    if facts.acceptance is None or not facts.acceptance.green:
        missing.append("GitHub acceptance on this SHA is not known to be green")
    if facts.authority is None or not facts.authority.ok:
        missing.append("no authorisation for this SHA is known")
    return missing
