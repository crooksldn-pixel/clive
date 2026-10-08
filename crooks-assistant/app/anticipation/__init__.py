"""Anticipation: reading before being asked, and knowing when not to (§18, §19).

    app/anticipation/models.py     Signal, Prediction, and the privacy boundary of a state
    app/anticipation/rules.py      level 1 — deterministic rules, and the table level 2 uses
    app/anticipation/learning.py   level 2 — counted transitions, decayed, with a minimum
    app/anticipation/engine.py     the decision, the bounds, the cancellation, the debug view
    app/anticipation/internal.py   reads that are not model-facing tools (a closed table, empty)

Read engine.py first. Two things hold everywhere in this package:

* Nothing here can write. A prediction is a registered READ tool run through the read
  scheduler (which refuses a write tool before the plan starts) or a name in one closed table.
* The owner always outranks it. A requested read stands the speculative lane down; a different
  record cancels the conversation's speculation outright.
"""

from app.anticipation.engine import (
    Anticipator,
    Decision,
    current,
    install,
    observe,
    owner_read,
    scope_of,
)
from app.anticipation.models import P1, P2, PREDICTED, REQUESTED, Prediction, Signal

__all__ = [
    "Anticipator", "Decision", "P1", "P2", "PREDICTED", "Prediction", "REQUESTED", "Signal",
    "current", "install", "observe", "owner_read", "scope_of",
]
