"""The door's second rule: a member of the team, on their own phone, whose login the owner let in.

The first rule is the owner's (app/routes/actions.py principal_verdict). A request it refuses is
asked this one before it is turned away: it came through `tailscale serve` (never from the server
itself), it carries a login an active grant names (app/people/access.py), the person is on CLIVE's
list as staff and still active, and, when CROOKS_TAILSCALE_VERIFY is on, Tailscale itself confirms
the device belongs to that login. All of it, or nobody. Then the request may reach only the staff
routes (app/people/staff.py), under a staff authority (app/tools/authority.py for_staff).
"""

from __future__ import annotations

from starlette.requests import Request

from app.people import access
from app.people.store import PeopleError, people


def staff_login(login: str) -> str:
    """The person an active grant lets in with this login, if they are still staff and active.
    The early check at the door, before identity is verified: it decides only whether to look further."""
    person_id = access.person_for_login(login)
    if not person_id:
        return ""
    try:
        person = people.get(person_id)
    except PeopleError:
        return ""
    if person is None or person.kind != "staff" or not person.active or person.login != str(login).strip().lower():
        return ""
    return person_id


def verdict(request: Request) -> tuple[str, str, str]:
    """(person_id, login, why refused): a staff member the door may let in, or why not."""
    from app.routes.actions import TAILSCALE, proxy_state

    route, why = proxy_state(request)
    if route != TAILSCALE:
        return "", "", "the team reach CLIVE through Tailscale, from their own phones"
    login = request.headers.get("tailscale-user-login", "").strip().lower()
    person_id = staff_login(login)
    if not person_id:
        return "", "", "this login is not one the owner has let in"
    runtime = getattr(request.app.state, "runtime", None)
    settings = getattr(runtime, "settings", None)
    if bool(getattr(settings, "tailscale_verify", True)):
        from app import identity

        ok, why = identity.verify(request.headers.get("x-forwarded-for", ""), login,
                                  cli=identity.cli_path(getattr(settings, "tailscale_cli", "")))
        if not ok:
            return "", "", f"Tailscale could not confirm this device's identity: {why}"
    return person_id, login, ""
