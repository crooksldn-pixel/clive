"""The one new kind of record DEC-078 adds: an idea, everything the research says about one thing.

Why this exists: George's words (9 Oct 2026): "Research documents should be evidence contributing to
CLIVE's understanding. They should not each independently become roadmaps." An idea gathers every
recommendation (claim) from every document that says the same thing, keeps who argues against it,
and carries four separate answers (judgment, relationship, timing, execution) instead of one verdict.

What it promises:
- `new_idea` is the only way an idea is made; every field the screen reads is there from the start.
- `evidence_hash` changes exactly when what backs or opposes it changes, so only ideas a document
  touched are judged again.
- `fingerprint` is over exactly what George is shown (app.actions.judgment.proposal_fingerprint), so
  his answer binds to it; it never covers execution, his answer or the build, which change because
  of his answer.
- `active` follows merged ideas to the one they joined.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.research.synthesis.ask import line, words_at_most
from app.research.synthesis.words import KINDS

OWNER_VIEW = ("means", "today", "after", "example", "before_after", "why_care", "notice")


def new_idea(idea_id: str, *, name: str, statement: str, kind: str, at: str) -> dict[str, Any]:
    return {
        "id": idea_id, "name": words_at_most(line(name, 120), 8) or "An idea from research",
        "statement": line(statement, 500), "kind": kind if kind in KINDS else "capability",
        "sources": [], "against": [], "how_they_differ": "",
        "keys": [], "basis": [], "today": {"level": "none", "says": "", "where": [], "verified": False},
        "answers": {}, "reasons": {"judgment": "", "timing": ""}, "timing_held_by": [],
        "revisit": "", "needs_you": None, "effects": [], "touches": [], "protected": [], "done_when": [],
        "owner_view": None, "owner_view_complete": False, "checked_by": "", "rule_notes": [],
        "evidence_hash": "", "judged_with": None, "status": "active", "merged_into": "", "was": [],
        "fingerprint": "", "created_at": at, "updated_at": at,
    }


def evidence_hash(idea: dict[str, Any]) -> str:
    sources = sorted((s.get("claim_id", ""), s.get("quote", ""), s.get("stance", ""), s.get("centrality", ""))
                     for s in idea.get("sources") or [])
    against = sorted((a.get("claim_id", ""), a.get("why", "")) for a in idea.get("against") or [])
    body = json.dumps({"statement": idea.get("statement", ""), "sources": sources, "against": against}, sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def shown(idea: dict[str, Any]) -> dict[str, Any]:
    """What George is shown of an idea, as his answer binds to it."""
    answers = {k: v for k, v in (idea.get("answers") or {}).items() if k != "execution"}
    return {
        "id": idea.get("id"), "name": idea.get("name"), "statement": idea.get("statement"), "kind": idea.get("kind"),
        "answers": answers, "reasons": idea.get("reasons"), "timing_held_by": idea.get("timing_held_by"),
        "owner_view": idea.get("owner_view"), "needs_you": idea.get("needs_you"), "keys": idea.get("keys"),
        "today": idea.get("today"), "revisit": idea.get("revisit"), "effects": idea.get("effects"),
        "how_they_differ": idea.get("how_they_differ"), "touches": idea.get("touches"), "done_when": idea.get("done_when"),
        "sources": [{k: s.get(k) for k in ("document", "section", "quote", "stance", "centrality")}
                    for s in idea.get("sources") or []],
        "against": [{k: a.get(k) for k in ("claim_id", "why")} for a in idea.get("against") or []],
    }


def finish(idea: dict[str, Any], at: str) -> dict[str, Any]:
    """Bookkeeping before an idea is written: its evidence hash, its fingerprint, when it changed."""
    from app.actions.judgment import proposal_fingerprint

    idea["evidence_hash"] = evidence_hash(idea)
    idea["fingerprint"] = proposal_fingerprint(shown(idea))
    idea["updated_at"] = at
    return idea


def documents_backing(idea: dict[str, Any]) -> list[str]:
    """The documents that back it (supports or refines), in the order they joined."""
    out: list[str] = []
    for source in idea.get("sources") or []:
        if source.get("stance") != "opposes" and source.get("doc_id") and source["doc_id"] not in out:
            out.append(source["doc_id"])
    return out


def judged(idea: dict[str, Any]) -> bool:
    return bool((idea.get("answers") or {}).get("judgment")) and idea.get("judged_with") is not None


def active(ideas: dict[str, dict[str, Any]], idea_id: str) -> str:
    """The active idea `idea_id` is, following merges; "" when there is none."""
    seen = set()
    while idea_id and idea_id not in seen:
        seen.add(idea_id)
        idea = ideas.get(idea_id)
        if idea is None:
            return ""
        if idea.get("status") == "active":
            return idea_id
        idea_id = str(idea.get("merged_into") or "")
    return ""


def has_claim(idea: dict[str, Any], claim_id: str) -> bool:
    return any(s.get("claim_id") == claim_id for s in idea.get("sources") or [])
