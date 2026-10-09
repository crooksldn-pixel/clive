"""George's answers to ideas: kept in the owner judgment ledger, bound to what he was shown.

Why this exists: his answers stay where all his answers are (app/builds/decisions.py, the owner
judgment ledger), not in the synthesis. An idea is put to him as a question whose proposal id holds
the idea's id and the start of its fingerprint, so an answer binds to exactly what he saw; when the
idea is judged again, its fingerprint changes and his earlier answer shows as "your answer to an
earlier view" until he answers again.

What it promises:
- `latest` finds his newest effective answer to each idea, whichever view it was given to.
- `current` is true only when that answer was given to the idea exactly as it stands.
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

PREFIX = "research-idea"


def proposal_id(idea_id: str, fingerprint: str) -> str:
    return f"{PREFIX}:{idea_id}:{fingerprint[:16]}"


def idea_of(proposal_id_: str) -> str:
    parts = str(proposal_id_ or "").split(":")
    return parts[1] if len(parts) == 3 and parts[0] == PREFIX else ""


def question(idea: dict[str, Any]) -> dict[str, Any]:
    """The idea as a question for decisions.decide: bound to its fingerprint, under its own action id."""
    from app.builds import decisions

    pid = proposal_id(idea["id"], idea["fingerprint"])
    return {"kind": decisions.RESEARCH_IDEA, "proposal_id": pid, "fingerprint": idea["fingerprint"],
            "task_id": f"{PREFIX}:{idea['id']}", "request_id": idea["id"],
            "action_id": f"{decisions.RESEARCH_IDEA_PREFIX}{pid}", "revision": None, "attempt_id": None}


def latest(effective: dict[str, Any]) -> dict[str, Any]:
    """His newest effective answer to each idea, by idea id (the ledger's JudgmentRecord)."""
    out: dict[str, Any] = {}
    for pid, record in effective.items():
        idea_id = idea_of(pid)
        if idea_id and (idea_id not in out or record.decided_at > out[idea_id].decided_at):
            out[idea_id] = record
    return out


def said(record, idea: dict[str, Any]) -> dict[str, Any] | None:
    """{"key", "label", "at", "current"} for the payload, or None when it isn't one of the idea answers."""
    from app.builds import decisions

    answer = decisions.answer_of(record) if record is not None else None
    if answer is None:
        return None
    return {"key": answer.key, "label": answer.label,
            "at": record.decided_at.astimezone(UTC).isoformat(timespec="seconds"),
            "current": record.proposal_fingerprint == idea.get("fingerprint")}


def keys(effective: dict[str, Any]) -> dict[str, str]:
    """His newest answer's key (go, later, no) to each idea, by idea id."""
    from app.builds import decisions

    out = {}
    for idea_id, record in latest(effective).items():
        answer = decisions.answer_of(record)
        if answer is not None:
            out[idea_id] = answer.key
    return out
