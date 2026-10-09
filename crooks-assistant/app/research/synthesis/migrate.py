"""The old screen's proposals (DEC-070), linked to the ideas their recommendations landed in.

Why this exists: before DEC-078, each document's recommendations were frozen as up to 25 proposals
in its record. Those records stay exactly as they are: George's answers bind to them, and the
history must stay true. Inside a full synthesis run, each old proposal is linked to the idea its
recommendation landed in, so the idea's history says what the old screen said:
"9 Oct, old screen: Park, DEC-018 (reason)".

A proposal is linked to a claim of the same document whose quote overlaps it once normalised (either
way round); failing that, to the claim whose `says` shares at least 60% of its words. Its idea is the
one that claim is in now (following merges).

What it promises:
- Nothing in a research record is written: it is read only, and stays byte for byte as it was.
- A proposal is linked at most once (an `old screen` event names it); those that can't be linked are
  listed in run.json.
- An answer George gave an old proposal, if the ledger holds one, is said in that event.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.research.review import _tokens, normalise
from app.research.synthesis.ideas import active

SAYS_SHARE = 0.6
VERDICT_WORDS = {"adopt": "Adopt", "park": "Park", "reject": "Reject"}


def claim_for(proposal: dict[str, Any], claims: list[dict[str, Any]]) -> dict[str, Any] | None:
    quote = normalise(proposal.get("quote") or "")
    if len(quote) >= 12:
        for claim in claims:
            theirs = normalise(claim.get("quote") or "")
            if theirs and (quote in theirs or theirs in quote):
                return claim
    mine = _tokens(proposal.get("says") or proposal.get("title") or "")
    best, score = None, 0.0
    for claim in claims:
        theirs = _tokens(claim.get("says") or "")
        if mine and theirs:
            share = len(mine & theirs) / len(mine | theirs)
            if share >= SAYS_SHARE and share > score:
                best, score = claim, share
    return best


def _day(iso: str) -> str:
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).strftime("%-d %b")
    except ValueError:
        return ""


def words_for(proposal: dict[str, Any], record: dict[str, Any], answer: dict[str, Any] | None) -> str:
    day = _day(record.get("finished_at") or record.get("received_at") or "")
    cite = (proposal.get("cites") or [""])[0]
    head = f"{day + ', ' if day else ''}old screen: {VERDICT_WORDS.get(proposal.get('verdict'), proposal.get('verdict') or '')}"
    said = f"{head}{', ' + cite if cite else ''} ({proposal.get('reason') or 'no reason given'})"
    if proposal.get("duplicate_of"):
        said += "; it repeated earlier research"
    if answer:
        said += f"; you answered {answer['label']}{' on ' + _day(answer['at']) if _day(answer['at']) else ''}"
    return said


def link(records: list[dict[str, Any]], claims: dict[str, dict[str, Any]], ideas: dict[str, dict[str, Any]],
         done: set[str], answers: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(links to write as events, proposals that couldn't be linked). `done` holds proposal ids already
    linked; `answers` his answer to an old proposal, by proposal id."""
    by_claim = {}
    for idea_id, idea in ideas.items():
        for source in idea.get("sources") or []:
            by_claim.setdefault(source.get("claim_id"), idea_id)
    links, unlinked = [], []
    for record in records:
        theirs = (claims.get(record.get("id") or "") or {}).get("claims") or []
        for proposal in record.get("proposals") or []:
            pid = str(proposal.get("id") or "")
            if not pid or pid in done:
                continue
            claim = claim_for(proposal, theirs)
            idea_id = active(ideas, by_claim.get(claim["id"], "")) if claim else ""
            if not idea_id:
                unlinked.append({"proposal_id": pid, "document": record.get("name") or "", "title": proposal.get("title") or "",
                                 "verdict": proposal.get("verdict") or "", "cites": list(proposal.get("cites") or [])})
                continue
            links.append({"idea": idea_id, "proposal_id": pid, "verdict": proposal.get("verdict") or "",
                          "cites": list(proposal.get("cites") or []), "reason": proposal.get("reason") or "",
                          "duplicate_of": proposal.get("duplicate_of") or "", "title": proposal.get("title") or "",
                          "said": words_for(proposal, record, answers.get(pid))})
    return links, unlinked


def resort(links: list[dict[str, Any]], unlinked: list[dict[str, Any]], ideas: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Item 7 and 8 of the run's report: how the old parks and rejects re-sort, and how often DEC-018
    was the reason."""
    rows, tally = [], {"held only by DEC-018 though the direction is right": 0, "partly done though called done": 0,
                       "already done, now right direction": 0, "still not for CLIVE": 0, "repeat": 0,
                       "now needs your call": 0, "now worth looking into": 0}
    for link_ in links:
        if link_["verdict"] not in ("park", "reject"):
            continue
        idea = ideas.get(link_["idea"]) or {}
        a = idea.get("answers") or {}
        rows.append({"proposal": link_["title"], "was": link_["verdict"], "cites": link_["cites"][:3], "idea": link_["idea"],
                     "name": idea.get("name", ""), "judgment": a.get("judgment", ""),
                     "relationship": a.get("relationship", ""), "timing": a.get("timing", "")})
        held = "DEC-018" in (idea.get("timing_held_by") or [])
        positive = a.get("judgment") in ("ADOPT", "ADOPT_PARTLY")
        called_done = link_["verdict"] == "reject" and any(c.startswith("FEAT-") or c == "TRUTH" for c in link_["cites"])
        if link_["duplicate_of"]:
            tally["repeat"] += 1
        if link_["verdict"] == "park" and "DEC-018" in link_["cites"] and held and positive:
            tally["held only by DEC-018 though the direction is right"] += 1
        if called_done and a.get("relationship") == "PARTIALLY_SATISFIED":
            tally["partly done though called done"] += 1
        if link_["verdict"] == "reject" and positive and a.get("relationship") == "ALREADY_SATISFIED":
            tally["already done, now right direction"] += 1
        if link_["verdict"] == "reject" and a.get("judgment") == "REJECT":
            tally["still not for CLIVE"] += 1
        if a.get("judgment") == "CONFLICT":
            tally["now needs your call"] += 1
        if a.get("judgment") == "INVESTIGATE":
            tally["now worth looking into"] += 1
    old_018 = [x for x in [*links, *unlinked] if "DEC-018" in x["cites"]]
    held_ideas = [i for i in ideas.values() if i.get("status") == "active" and "DEC-018" in (i.get("timing_held_by") or [])]
    return {"old_parks_and_rejects": rows, "resorted": tally, "unlinked": len(unlinked),
            "dec_018": {"old_proposals_citing_it": len(old_018),
                        "ideas_it_holds": len(held_ideas),
                        "of_those_called_right": sum(1 for i in held_ideas
                                                     if (i.get("answers") or {}).get("judgment") in ("ADOPT", "ADOPT_PARTLY"))}}
