"""The interaction grammar: how the owner authorises a change, decided from what the change
is — never chosen by the model, never by the tablet.

One table. A change's computed tier (AMBER, or RED after the risk hook) and its class
(reversible; irreversible; money — money leaves or an order dies) name the gesture. Each
gesture carries its own words: the label on the surface, the footer under it, the fixed
sentence a spoken "yes" gets, and what the model is told so it says the right thing. Every
one of those is fixed text, synthesised once and kept.
"""

from __future__ import annotations

from typing import Any

# The kinds the tablet implements. A kind not here renders as unavailable, never as a button.
KINDS = ("tap_commit", "swipe_commit", "hold_to_arm", "hold_drag_target")

# (tier, class) → gesture. The class is the write's own declaration (app/tools/registry.py
# WriteSpec.op_class). RED is always a hold; a hold that also moves money or ends an order is
# a hold and a drag. AMBER is a tap when it can be undone and a swipe when it cannot.
GESTURE: dict[tuple[str, str], str] = {
    ("AMBER", "reversible"): "tap_commit",
    ("AMBER", "irreversible"): "swipe_commit",
    ("AMBER", "money"): "hold_to_arm",
    ("RED", "reversible"): "hold_to_arm",
    ("RED", "irreversible"): "hold_to_arm",
    ("RED", "money"): "hold_drag_target",
}

# Dead time, hold time and the window a hold stays armed. The Mac holds the same numbers
# (app/routes/actions.py checks the dwell of an arming against them).
ARMED_AFTER_MS = 650          # a surface cannot be used the instant it appears
HOLD_MS = 900                 # a hold this long arms a RED surface
ARMED_FOR_S = 5.0             # an armed surface disarms after this long untouched
SWIPE_FRACTION = 0.72         # how far across the handle must travel

WORDS: dict[str, dict[str, str]] = {
    "tap_commit": {
        "label": "Tap to apply",
        "footer": "nothing happens until you tap",
        "verb": "tapping the card applies it",
        "affirmation": "Nothing happens until you tap the card. It is still waiting on the screen.",
        "state_words": "Tap to apply",
    },
    "swipe_commit": {
        "label": "Swipe to apply",
        "footer": "nothing happens until you swipe",
        "verb": "swiping the card applies it",
        "affirmation": "Nothing happens until you swipe the card. It is still waiting on the screen.",
        "state_words": "Swipe to apply",
    },
    "hold_to_arm": {
        "label": "Hold to arm, then tap",
        "footer": "nothing happens until you hold the card, then tap it",
        "verb": "holding the card and then tapping it applies it",
        "affirmation": "Nothing happens until you hold the card and then tap it. It is still waiting on the screen.",
        "state_words": "Hold to arm",
    },
    "hold_drag_target": {
        "label": "Hold, then drag to the target",
        "footer": "nothing happens until you hold the card and drag the handle onto the target",
        "verb": "holding the card and dragging the handle onto the target applies it",
        "affirmation": "Nothing happens until you hold the card and drag the handle onto the target. It is still waiting on the screen.",
        "state_words": "Hold, then drag",
    },
}

# What a spoken yes gets while a card is waiting and a tap from there would be refused.
AFFIRMATION_BLOCKED = "That is prepared, but it cannot be applied from this device. The card says why."

# Every fixed sentence, so the voice can keep them: synthesised once, free after that.
FIXED_LINES = frozenset({w["affirmation"] for w in WORDS.values()} | {AFFIRMATION_BLOCKED})


def gesture_for(tier: str, op_class: str) -> str:
    """The gesture for a change of this tier and class. Unknown inputs fall to the
    strictest gesture, never the loosest."""
    tier = str(tier or "").upper()
    op_class = str(op_class or "irreversible").lower()
    if tier not in ("AMBER", "RED") or op_class not in ("reversible", "irreversible", "money"):
        return "hold_drag_target"
    return GESTURE[(tier, op_class)]


def words_for(kind: str) -> dict[str, str]:
    return dict(WORDS.get(kind, WORDS["hold_drag_target"]))


def affirmation_for(kind: str, *, blocked: bool = False) -> str:
    return AFFIRMATION_BLOCKED if blocked else words_for(kind)["affirmation"]


def dwell_ms(kind: str) -> int:
    """How long the owner must have held before the surface counts as armed."""
    return 0 if kind in ("tap_commit", "swipe_commit") else HOLD_MS


def public_timings() -> dict[str, Any]:
    return {"armed_after_ms": ARMED_AFTER_MS, "hold_ms": HOLD_MS, "armed_for_s": ARMED_FOR_S, "swipe_fraction": SWIPE_FRACTION}
