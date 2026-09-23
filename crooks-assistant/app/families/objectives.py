"""Objectives the owner keeps alive (app/objectives): CLIVE's own records, not a business system.

Four read-tier tools; nothing here stages a write, because nothing here reaches Shopify, Gmail
or the outside world. Authorising a work item and closing an objective are the owner's, on the
phone (app/routes/objectives.py), and the store refuses both to the model.
"""

from __future__ import annotations

from app.capabilities.families import CapabilityFamily, register
from app.objectives import (
    tools as _tools,  # noqa: F401 — importing registers the four tools with the family
)

register(CapabilityFamily(
    key="objectives", label="Objectives", area="system",
    what="keep a real-world goal alive across conversations: facts, unknowns, blockers, next steps and what needs you",
    tools=("objective_open", "objective_list", "objective_show", "objective_note"),
    state="READY", detail="ready",
))
