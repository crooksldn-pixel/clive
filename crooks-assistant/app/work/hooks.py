"""When a change made through a card was what a job was for, the job closes itself, in the name of
whoever confirmed it, and the record says so: who fulfilled #1234, who replied to that email, who
set the stock of that hoodie, and who took one of those back. Called by the commit route once a
change has been made (app/routes/actions.py); never raises, because the change is made whatever
the list says. A job already finished on the list when the change lands (Today packs and finishes in
one tap, and the fulfilment card comes after) has the change written onto it, so it reads as
finished and its Undo is refused.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("crooks.work")

# What a made change does to the work list, by the engine's name for it: (what the record calls
# it, the kind of reference the change is about, whether a claimed job about it is now done).
EFFECTS = {
    "fulfillment_create": ("fulfilled", "order", True),
    "fulfillment_tracking_set": ("tracking_added", "order", False),
    "gmail_send_reply": ("replied", "email", True),
    "gmail_draft_reply": ("reply_drafted", "email", False),
    "inventory_set": ("stock_set", "variant", False),
}
# The engine names the undo of a change "<operation>_undo" (app/actions/engine.py stage_undo). An
# undo is recorded as "<what>_undone" about the same thing, and never closes or reopens a job.
UNDO = "_undo"
# The one source found.py reads again after a change about it: the others' answers still hold, and
# Instagram's is kept longest because its rate limit is the tightest. A stock change is on none.
FOUND_SOURCE = {"order": "orders", "email": "emails"}
MADE = ("VERIFIED", "UNVERIFIED", "EXECUTED")


def _who(caller: str) -> str:
    """Who made a change: the request's own authority (the owner, or the member of the team it was
    made for), else the person the confirming login belongs to, else the login itself. Never the
    owner by default: a staff member's change is never put down as his."""
    from app.people import access
    from app.tools import authority

    held = authority.current()
    if held is not None and held.kind == authority.OWNER:
        return "owner"
    if held is not None and held.kind == authority.STAFF and held.who:
        return str(held.who)
    try:
        person = access.person_for_login(caller)
    except Exception:  # noqa: BLE001 - the grants unreadable just now: the login says who it was
        person = ""
    return person or caller


def after_commit(proposal: Any) -> None:
    try:
        _after(proposal)
    except Exception as exc:  # noqa: BLE001 - the change is made; the list is a record of it
        log.warning("work: a made change could not be noted on the work list (%s)", type(exc).__name__)


def _after(proposal: Any) -> None:
    from app.work import found
    from app.work.store import WorkError, work

    operation = str(getattr(proposal, "operation", "") or "")
    undone = operation.endswith(UNDO) and operation.removesuffix(UNDO) in EFFECTS
    effect = EFFECTS.get(operation.removesuffix(UNDO) if undone else operation)
    status = str(getattr(getattr(proposal, "status", None), "value", getattr(proposal, "status", "")) or "")
    if effect is None or status not in MADE:
        return
    what, kind, closes = effect
    if kind in FOUND_SOURCE:
        found.reset(FOUND_SOURCE[kind])  # the order or the thread has changed: read it again next time
    if undone:
        what, closes = f"{what}_undone", False
    who = _who(str(getattr(proposal, "caller", "") or ""))
    entity = str(getattr(proposal, "entity_ref", "") or "")
    label = str(getattr(proposal, "entity_label", "") or entity)[:120]
    ref = f"{kind}:{entity}" if kind in ("order", "email") and entity else ""
    work.record({"who": who, "what": what, "ref": ref, "detail": label, "proposal_id": getattr(proposal, "proposal_id", "")})
    if not (closes and ref):
        return
    proof = {what: True, "by": who, "proposal_id": getattr(proposal, "proposal_id", "")}
    for item in work.by_ref(ref):
        # A change closes the found job it was for, never a job flagged for the owner about the
        # same order or email: that one is his to finish.
        if item.source != "found":
            continue
        if item.status == "done":
            # Finished on the list before the card landed (Today's one-tap Packed packs and finishes):
            # the change is written onto it, so it is not left "packed, waiting" and Undo cannot
            # reopen a job whose fulfilment stands (the review of 3 October).
            work.stamp(item.item_id, proof)
            continue
        if item.status not in ("open", "claimed"):
            continue
        try:
            work.done(item.item_id, who=who, owner=True, evidence=proof)
        except WorkError:
            continue
