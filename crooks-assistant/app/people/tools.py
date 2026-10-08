"""CLIVE's hands on people cards: one read, and the one write the owner makes by saying who someone is.

Both change only CLIVE's own records on this machine, like the objective tools beside them on the
gate's read allow-list: no message goes to anyone and nobody is let in by them. A staff login
given here waits for the owner's passkey on the Today screen (app/people/access.py).
"""

from __future__ import annotations

from typing import Any

from app.capabilities.families import CapabilityFamily, register
from app.people import access
from app.people.store import KINDS, PeopleError, people
from app.tools import authority
from app.tools.gate import Tier
from app.tools.registry import ToolError, tool

TOOLS = ("people_list", "person_note")

register(CapabilityFamily(
    key="people", label="People", area="system",
    what="keep who works with CROOKS, what they do, and who on the team uses CLIVE",
    tools=TOOLS, state="READY", detail="ready",
))


def _caller() -> authority.Authority | None:
    return authority.current()


def _is_owner() -> bool:
    held = _caller()
    return held is not None and held.kind == authority.OWNER


def _card(person, *, owner: bool) -> dict[str, Any]:
    out = person.public(for_staff=not owner)
    if owner and person.kind == "staff":
        out["access"] = access.state(person.person_id) or ("no login yet" if not person.login else "")
        # [staff-links] How many phones are signed in by a staff link (DEC-075).
        from app.people import links

        out["phones_by_link"] = links.phones_signed_in(person.person_id)
    return out


@tool(
    name="people_list",
    description=("Who CROOKS works with: the team, and people to suggest for a job (a designer, a "
                 "photographer), with what each does. `who` finds one."),
    input_schema={"type": "object", "properties": {"who": {"type": "string"}}},
    tier=Tier.AMBER,
)
async def people_list(who: str = "") -> dict[str, Any]:
    owner = _is_owner()
    try:
        if who:
            person = people.find(who)
            if person is None:
                return {"people": [], "shown": 0, "note": f"No one called {who[:40]} is on CLIVE's list."}
            return {"people": [_card(person, owner=owner)], "shown": 1}
        found = people.all()
    except PeopleError as exc:
        raise ToolError(str(exc)) from None
    return {"people": [_card(p, owner=owner) for p in found], "shown": len(found)}


@tool(
    name="person_note",
    description=("Keep who someone is, in the owner's words. staff use CLIVE on their own phone (joined by a "
                 "staff link made on the Team page, or `login`: a Tailscale sign-in); a contact is someone to "
                 "suggest (`uses`: what for). Empty fields keep what is there; active false takes someone off."),
    input_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"}, "kind": {"type": "string", "enum": list(KINDS)}, "role": {"type": "string"},
            "areas": {"type": "string"}, "email": {"type": "string"}, "instagram": {"type": "string"},
            "phone": {"type": "string"}, "uses": {"type": "string"}, "notes": {"type": "string"},
            "login": {"type": "string"}, "active": {"type": "boolean"},
        },
        "required": ["name"],
    },
    tier=Tier.GREEN,
)
async def person_note(name: str, kind: str = "", role: str = "", areas: str | list[str] | None = None, email: str = "",
                      instagram: str = "", phone: str = "", uses: str = "", notes: str = "", login: str = "",
                      active: bool | None = None) -> dict[str, Any]:
    if not _is_owner():
        raise ToolError("Only the owner keeps people's cards.")
    fields = {"name": name, "kind": kind, "role": role, "areas": areas, "email": email, "instagram": instagram,
              "phone": phone, "uses": uses, "notes": notes, "login": login, "active": active}
    try:
        person, created = people.note(fields)
        state = ""
        if person.kind == "staff" and person.login and person.active:
            state = access.ask(person.person_id, person.login)
        elif access.state(person.person_id) in ("pending", "active"):
            # No longer staff, no login, or taken off: the door closes for them at once.
            access.suspend(person.person_id, by="the owner, through CLIVE")
            state = "suspended"
        if not (person.kind == "staff" and person.active):
            # [staff-links] Taken off, or no longer staff: their phones joined by link are signed out
            # and a waiting link cancelled, so putting them back later opens nothing by itself (DEC-075).
            from app.people import links

            links.sign_out_person(person.person_id, by="the owner, through CLIVE", why="taken off the team")
    except (PeopleError, access.AccessError) as exc:
        raise ToolError(str(exc)) from None
    out: dict[str, Any] = {"person": _card(person, owner=True), "created": created}
    if state == "pending":
        out["next"] = (f"{person.name} can use CLIVE once you approve their login with your passkey on the "
                       "Today screen (/today).")
    elif person.kind == "staff" and not person.login:
        # [staff-links] Ruling 35: the team join with a link and a code, made on Team › People (DEC-075).
        out["next"] = (f"To let {person.name} use CLIVE on their phone, make them a staff link on Team › People "
                       "(it needs your passkey), send it, and tell them the code yourself.")
    return out
