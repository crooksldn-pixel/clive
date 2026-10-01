"""When a change made through a card was what a job was for, the job closes itself, in the name of
whoever confirmed it, and the record says so: who fulfilled #1234, who replied to that email, who
set the stock of that hoodie. Called by the commit route once a change has been made
(app/routes/actions.py); never raises, because the change is made whatever the list says.
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
MADE = ("VERIFIED", "UNVERIFIED", "EXECUTED")


def _who(caller: str) -> str:
    """The person a confirming login belongs to, or the owner."""
    from app.people import access

    return access.person_for_login(caller) or "owner"


def after_commit(proposal: Any) -> None:
    try:
        _after(proposal)
    except Exception as exc:  # noqa: BLE001 - the change is made; the list is a record of it
        log.warning("work: a made change could not be noted on the work list (%s)", type(exc).__name__)


def _after(proposal: Any) -> None:
    from app.work import found
    from app.work.store import WorkError, work

    effect = EFFECTS.get(str(getattr(proposal, "operation", "") or ""))
    status = str(getattr(getattr(proposal, "status", None), "value", getattr(proposal, "status", "")) or "")
    if effect is None or status not in MADE:
        return
    found.reset()                       # the order or the thread has changed: read it again next time
    what, kind, closes = effect
    who = _who(str(getattr(proposal, "caller", "") or ""))
    entity = str(getattr(proposal, "entity_ref", "") or "")
    label = str(getattr(proposal, "entity_label", "") or entity)[:120]
    ref = f"{kind}:{entity}" if kind in ("order", "email") and entity else ""
    work.record({"who": who, "what": what, "ref": ref, "detail": label, "proposal_id": getattr(proposal, "proposal_id", "")})
    if not (closes and ref):
        return
    for item in work.by_ref(ref):
        if item.status not in ("open", "claimed"):
            continue
        try:
            work.done(item.item_id, who=who, owner=True,
                      evidence={what: True, "by": who, "proposal_id": getattr(proposal, "proposal_id", "")})
        except WorkError:
            continue
