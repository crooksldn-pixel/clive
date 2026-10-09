"""Every fixed value an idea may hold, and the words George is shown for it: one table, here only.

Why this exists: an idea (DEC-078) answers four questions separately — is the direction right
(judgment), is it already in CLIVE (relationship), when (timing), and is the work approved
(execution) — plus how sure CLIVE is, how much it matters, and what it does to CLIVE's understanding.
The model may only choose from these values, code checks every one (app/research/synthesis/judge.py),
and the screen shows these words, never the raw key.

What it promises:
- Each enum is a tuple in its own order (the order the screen and the counts use), and `WORDS` holds
  a plain-English line for every value of every enum. `words(axis, key)` is the one way to say one.
- Execution is never the model's: code sets it from George's answer and the build's own state.
"""

from __future__ import annotations

KINDS = ("foundational", "capability", "safety", "tooling-choice", "process", "meta")
STANCES = ("supports", "opposes", "refines")
CENTRALITIES = ("central", "supporting", "passing")
LEVELS = ("none", "partial", "substantial", "complete")
CLAIM_KINDS = ("build", "principle", "avoid", "measure", "sequence", "process")

AXES: dict[str, tuple[str, ...]] = {
    "judgment": ("ADOPT", "ADOPT_PARTLY", "INVESTIGATE", "CONFLICT", "REJECT"),
    "relationship": ("ALREADY_SATISFIED", "PARTIALLY_SATISFIED", "EXTENDS_EXISTING", "NEW"),
    "timing": ("NOW", "NEXT", "LATER", "UNSCHEDULED"),
    "execution": ("NOT_AUTHORISED", "READY", "IN_PROGRESS", "IMPLEMENTED", "BLOCKED"),
    "confidence": ("high", "medium", "low"),
    "importance": ("FOUNDATIONAL", "HIGH_LEVERAGE", "USEFUL", "OPTIMISATION", "LOW_CURRENT_VALUE"),
    "knowledge": ("VALIDATED", "STRENGTHENED", "MODIFIED", "CHALLENGED", "NEW"),
}
MODEL_AXES = tuple(a for a in AXES if a != "execution")

EFFECTS = ("LESS HUMAN ATTENTION", "MORE AUTONOMY", "HIGHER RELIABILITY", "LOWER RISK", "FASTER EXECUTION",
           "MAKES / PROTECTS MONEY", "ENABLES NEW CAPABILITY", "MOSTLY INTERNAL")
TRIGGERS = ("clash", "direction", "opportunity", "uncertainty", "authority")

WORDS: dict[str, dict[str, str]] = {
    "judgment": {"ADOPT": "Right direction", "ADOPT_PARTLY": "Right in part", "INVESTIGATE": "Worth looking into",
                 "CONFLICT": "Needs your call", "REJECT": "Not for CLIVE"},
    "relationship": {"ALREADY_SATISFIED": "Already done", "PARTIALLY_SATISFIED": "Partly there",
                     "EXTENDS_EXISTING": "Builds on what exists", "NEW": "New"},
    "timing": {"NOW": "Now", "NEXT": "Next", "LATER": "Later", "UNSCHEDULED": "No date"},
    "execution": {"NOT_AUTHORISED": "Not approved", "READY": "Ready", "IN_PROGRESS": "In progress",
                  "IMPLEMENTED": "Built", "BLOCKED": "Blocked"},
    "confidence": {"high": "Sure", "medium": "Fairly sure", "low": "Unsure"},
    "importance": {"FOUNDATIONAL": "Foundational", "HIGH_LEVERAGE": "High leverage", "USEFUL": "Useful",
                   "OPTIMISATION": "Optimisation", "LOW_CURRENT_VALUE": "Low value now"},
    "knowledge": {"VALIDATED": "Confirms what CLIVE thought", "STRENGTHENED": "Strengthens it",
                  "MODIFIED": "Modifies it", "CHALLENGED": "Challenges it", "NEW": "New to CLIVE"},
    "trigger": {"clash": "Clashes with one of your rules or decisions",
                "direction": "CLIVE's view of it changed direction",
                "opportunity": "A big step CLIVE could take",
                "uncertainty": "CLIVE can't tell yet",
                "authority": "Only you can allow it"},
}

# Timing as the screen groups it, in order, with each group's title.
GROUPS = (("now", "NOW", "Now"), ("next", "NEXT", "Next"), ("later", "LATER", "Later"),
          ("unscheduled", "UNSCHEDULED", "No date"))

# George's three answers to an idea. Each says only what is true today.
CHOICES = (
    ("go", "Approve the work",
     "Prepares a build request on a card. Nothing is filed until you hold it; then it goes to CLIVE's public "
     "repository, in CLIVE's words, never the research's own."),
    ("later", "Not now", "Kept as an idea, with your answer. Nothing is built."),
    ("no", "Not for CLIVE", "Marked not for CLIVE, with your answer. Nothing is built, and it stays in the history."),
)

# Where an approved idea's build request is, as the screen says it.
BUILD_WORDS = {
    "not_prepared": "No build request is waiting for it. Prepare it again to file it.",
    "waiting": "Its build request waits for your hold on the card. If the card has gone, prepare it again.",
    "filed": "Filed with the build loop. It shows in the builds above once the loop reports it.",
    "done": "The build loop finished it.",
    "blocked": "The build loop stopped it. It is on the Builds screen with why.",
}


def words(axis: str, key: str) -> str:
    """What George is shown for one value; "" for a value that is not in the table."""
    return WORDS.get(axis, {}).get(str(key or ""), "")


def said(axis: str, key: str) -> dict[str, str]:
    """{"key", "words"} for the payload."""
    return {"key": str(key or ""), "words": words(axis, key)}
