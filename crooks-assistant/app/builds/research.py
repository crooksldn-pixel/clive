"""The Builds screen's Research section: what CLIVE made of the research George gave it, and his answers.

Why this exists: George approved (7 Oct 2026) "Each recommendation becomes a proposal checked against
the map's rules (adopt, park or reject, with a reason), and you approve them on the Builds screen."
This draws that list from the research records (app/research/store.py) and puts each proposal to him
with three answers, CLIVE's own view marked as recommended with its reason and what it cites.

What it promises:
- Every word comes from a record: the research's own file name, the proposal as it was frozen, the
  map's own names for what it cites. A document still being read, stopped or failed says so, and why.
- His answer is an owner judgment in the judgment ledger (app/builds/decisions.py), bound to the
  proposal exactly as drawn (its fingerprint); a proposal that is not the one he saw records nothing.
- Adopt prepares a build request through the existing filing path — `submit_engineering_request`
  (app/tools/engineering_tools.py), staged on his conversation exactly as a tap stages any change
  (app/routes/command.py `_stage_change`) — and nothing is filed until he holds its card. Park and
  Reject prepare nothing.
- The build loop's inbox is in CLIVE's public repository, so a filed request carries what to build
  in CLIVE's words and never the research's own: not its quote, not its file name. It names the
  research record and the proposal by id, and they stay on the server (review note 6, 8 Oct).
- A proposal that repeats earlier research is not asked again: it is shown under the one it repeats.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

from app.builds import decisions

STATE_WORDS = {
    "queued": "Waiting to be read",
    "reading": "Being read now",
    "done": "Read",
    "stopped": "Stopped by the safety scan",
    "failed": "Couldn't be read",
}
VERDICT_WORDS = {"adopt": "Adopt", "park": "Park", "reject": "Reject"}
FILED_TTL_S = 60.0
_filed_cache: dict[str, tuple[float, str]] = {}


def question(record: dict[str, Any], proposal: dict[str, Any]) -> dict[str, Any]:
    """The proposal as a question for decisions.decide: bound to its fingerprint, its own action id."""
    return {"kind": decisions.RESEARCH, "proposal_id": proposal["id"], "fingerprint": proposal["fingerprint"],
            "task_id": f"research:{record.get('artifact_id') or record['id']}", "request_id": proposal["id"],
            "action_id": f"{decisions.RESEARCH_PREFIX}{proposal['id']}", "revision": None, "attempt_id": None}


# ------------------------------------------------------------------ the section


async def current(store, ledger) -> dict[str, Any]:
    """The Research section: each document and how it stands, then the proposals, his to answer first."""
    from app.research.rules import read_map

    records = store.documents()
    try:
        effective = ledger.effective()
        problem = ""
    except decisions.DecisionError as exc:
        effective, problem = {}, str(exc)
    names = _names(records)
    try:
        the_map = read_map()
    except Exception:  # noqa: BLE001 - citations are then shown by their keys alone
        the_map = None
    repeats: dict[str, list[str]] = {}
    for record in records:
        for p in record.get("proposals") or []:
            if p.get("duplicate_of"):
                repeats.setdefault(p["duplicate_of"], []).append(record.get("name") or "")
    groups: dict[str, list[dict[str, Any]]] = {"waiting": [], "adopt": [], "park": [], "reject": []}
    for record in records:
        for p in record.get("proposals") or []:
            if p.get("duplicate_of"):
                continue
            judged = effective.get(p.get("id"))
            row = await _row(record, p, judged, the_map, repeats.get(p.get("id"), []))
            groups[row["chosen"]["key"] if row.get("chosen") else "waiting"].append(row)
    waiting = len(groups["waiting"])
    reading = sum(1 for r in records if r.get("state") in ("queued", "reading"))
    return {
        "summary": _summary(waiting, reading, len(records)),
        "documents": [_document(r, names) for r in records],
        "groups": [{"key": k, "title": t, "proposals": groups[k]} for k, t in
                   (("waiting", "Waiting on you"), ("adopt", "Adopted"), ("park", "Parked"), ("reject", "Rejected"))
                   if groups[k]],
        "waiting": waiting,
        "reading": reading,
        "accepts": _accepts(),
        "problem": problem,
    }


def brief(payload: dict[str, Any]) -> dict[str, Any]:
    return {"waiting": payload.get("waiting", 0), "reading": payload.get("reading", 0), "summary": payload.get("summary", "")}


def _summary(waiting: int, reading: int, documents: int) -> str:
    if not documents:
        return "No research given yet. Add a file here, or put it in the research folder on the server."
    parts = []
    if waiting:
        parts.append(f"{waiting} recommendation{'s' if waiting != 1 else ''} from your research wait{'' if waiting != 1 else 's'} on you")
    if reading:
        parts.append(f"{reading} document{'s' if reading != 1 else ''} being read")
    return (". ".join(parts) + ".") if parts else "Every recommendation from your research has your answer."


def _accepts() -> str:
    from app.research.convert import ACCEPTED

    return ACCEPTED


def _names(records: list[dict[str, Any]]) -> dict[str, str]:
    return {r.get("id"): r.get("name") or "" for r in records}


def _document(record: dict[str, Any], names: dict[str, str]) -> dict[str, Any]:
    proposals = [p for p in record.get("proposals") or [] if not p.get("duplicate_of")]
    repeated = len(record.get("proposals") or []) - len(proposals)
    state = record.get("state") or "failed"
    return {
        "id": record.get("id"), "name": record.get("name") or "", "state": state,
        "state_words": STATE_WORDS.get(state, state), "why": record.get("why") or "",
        "received_at": record.get("received_at") or "", "via": record.get("via") or "",
        "proposals": len(proposals), "repeated": repeated,
        "dropped": [dict(d) for d in (record.get("dropped") or [])][:25],
        "notes": [str(n) for n in (record.get("notes") or [])][:10],
        "repeat_of": names.get(record.get("repeat_of") or "", "") if record.get("repeat_of") else "",
        "model": record.get("model") or "",
    }


async def _row(record, p, judged, the_map, also_in: list[str]) -> dict[str, Any]:
    q = question(record, p)
    answers = decisions.ANSWERS[decisions.RESEARCH]
    chosen = decisions.chosen(judged) if judged is not None and judged.proposal_fingerprint == p.get("fingerprint") else None
    row = {
        "id": p["id"], "fingerprint": p["fingerprint"], "document": record.get("name") or "",
        "title": p.get("title") or "", "says": p.get("says") or "", "quote": p.get("quote") or "",
        "verdict": p.get("verdict"), "verdict_words": VERDICT_WORDS.get(p.get("verdict"), ""),
        "reason": p.get("reason") or "", "checked_by": p.get("checked_by") or "model",
        "cites": [_cite(the_map, k) for k in p.get("cites") or []],
        "same_as": [_cite(the_map, k) for k in p.get("same_as") or []],
        "touches": list(p.get("touches") or []), "protected": list(p.get("protected") or []),
        "done_when": list(p.get("done_when") or []), "also_in": sorted(set(n for n in also_in if n)),
        "answers": [{"key": a.key, "label": a.label, "then": a.then, "recommended": a.key == p.get("verdict")}
                    for a in answers],
        "question_kind": q["kind"],
    }
    if chosen:
        row["chosen"] = chosen
        if chosen["key"] == "adopt":
            row["build"] = await _build_state(record, p)
    return row


def _cite(the_map, key: str) -> dict[str, str]:
    entry = the_map.get(key) if the_map is not None else None
    if entry is None:
        return {"key": key, "label": key, "status": ""}
    return {"key": key, "label": entry.label(), "status": entry.status}


async def _build_state(record: dict[str, Any], p: dict[str, Any]) -> dict[str, Any]:
    """Where an adopted proposal's build request is: prepared and waiting for his hold, filed, or not
    prepared (with why). Filed is read from the build loop's inbox, at most once a minute."""
    prepared = (record.get("prepared") or {}).get(p["id"])
    if not prepared:
        return {"state": "not_prepared", "words": "No build request is waiting for it. Prepare it again to file it."}
    rid = str(prepared.get("request_id") or "")
    filed = await _filed(rid)
    if filed == "yes":
        return {"state": "filed", "words": "Filed with the build loop. It shows in the builds below once the loop reports it.",
                "request_id": rid}
    if filed == "no":
        return {"state": "waiting", "words": "Its build request waits for your hold on the card. If the card has gone, prepare it again.",
                "request_id": rid}
    return {"state": "unknown", "words": f"Whether it was filed couldn't be read from GitHub: {filed}", "request_id": rid}


async def _filed(request_id: str) -> str:
    """"yes", "no", or why it could not be read."""
    if not request_id:
        return "no"
    hit = _filed_cache.get(request_id)
    if hit and time.monotonic() - hit[0] < FILED_TTL_S:
        return hit[1]
    from app.engineering_bridge.github import GitHubError, NotConnected
    from app.tools.engineering_tools import _client

    try:
        found = await _client().request_file(request_id)
    except GitHubError as exc:
        return str(exc)[:200]
    if isinstance(found, NotConnected):
        return found.reason[:200]
    said = "yes" if found.exists else "no"
    _filed_cache[request_id] = (time.monotonic(), said)
    return said


# ------------------------------------------------------------------ adopting: the build request, behind his hold


def requested_outcome(record: dict[str, Any], p: dict[str, Any], the_map=None) -> str:
    """What the build request asks for, in words a builder can act on, from the frozen proposal. It is
    filed in the public repository, so the research's own words (its quote, its file name) stay in
    CLIVE's private record, which the request names by id."""
    day = datetime.now(UTC).strftime("%-d %b %Y")
    cites = ", ".join(_cite(the_map, k)["label"] for k in p.get("cites") or []) or "nothing in the map"
    lines = [f"From research George gave CLIVE, adopted by him on the Builds screen on {day}. The research's own words "
             f"stay in CLIVE's private research record ({record.get('id')}, proposal {p.get('id')}).",
             f"What to build: {p.get('title')}.", f"What the research recommends, in CLIVE's words: {p.get('says')}"]
    view = VERDICT_WORDS.get(p.get("verdict"), "")
    if p.get("verdict") == "adopt":
        lines.append(f"CLIVE's view: adopt. {p.get('reason')} (cites {cites})")
    else:
        lines.append(f"CLIVE recommended {view.lower()} ({p.get('reason')}; cites {cites}); George adopted it anyway.")
    if p.get("same_as"):
        lines.append("It repeats what is already written down: " + ", ".join(_cite(the_map, k)["label"] for k in p["same_as"]) + ".")
    lines.append("Keep every rule in crooks-assistant/MAP.md; anything outward still waits for his gesture on its card.")
    return "\n".join(lines)


def filing_args(record: dict[str, Any], p: dict[str, Any], inbox_id: str, the_map=None) -> dict[str, Any]:
    """The arguments `submit_engineering_request` is staged with for an adopted proposal: only what
    the owner wants (a title, the outcome, the parts it may touch, what done looks like). The base,
    the id and the checks are the tool's own, as for every build CLIVE files."""
    return {"inbox_id": inbox_id, "title": p.get("title") or "Research recommendation",
            "requested_outcome": requested_outcome(record, p, the_map),
            "allowed_paths": list(p.get("touches") or []),
            "acceptance_criteria": list(p.get("done_when") or [])}


async def prepare(request, record: dict[str, Any], p: dict[str, Any], *, session_id: str) -> dict[str, Any]:
    """Stage the build request for an adopted proposal on George's conversation: the card he holds to
    file it. Returns {"ok": True, "ui", "answer", "branch", "proposal_id", "request_id"} or
    {"ok": False, "detail"} with why nothing was prepared."""
    from app.commands import Outcome
    from app.presentation import compact, present
    from app.routes.actions import session_matches
    from app.routes.command import _stage_change, _writes
    from app.tools.context import CURRENT_BRANCH
    from app.tools.dispatch import dispatch
    from app.tools.engineering_tools import STATUS_TOOL, SUBMIT_TOOL

    if not p.get("touches"):
        return {"ok": False, "detail": "CLIVE couldn't tell which parts of CLIVE this would change, so no build request "
                                      "was prepared. Ask CLIVE to build it in your own words."}
    runtime = request.app.state.runtime
    try:
        session = runtime.sessions.get(session_id) if session_id else None
    except KeyError:
        session = None
    if session is None:
        session = runtime.sessions.get_or_create(session_id or f"research-{int(time.time())}")
    if not session_matches(session, request):
        return {"ok": False, "detail": "That conversation belongs to another login, so nothing was prepared."}
    branch = session.branch()
    session.acting_branch = branch.branch_id
    token = CURRENT_BRANCH.set(branch.branch_id)
    try:
        calls: list = []
        await dispatch(STATUS_TOOL, {"areas": True}, session=session, timeout_s=runtime.settings.tool_timeout_s, calls=calls)
        status = next((c.result for c in calls if c.name == STATUS_TOOL and isinstance(c.result, dict)), None) or {}
        inbox = (status.get("inbox") or {}).get("id") if isinstance(status.get("inbox"), dict) else None
        if not status.get("connected") or not inbox:
            why = status.get("summary") or next((c.error for c in calls if c.error), "") or "the build loop couldn't be read"
            return {"ok": False, "detail": f"No build request was prepared: {why}"}
        try:
            from app.research.rules import read_map

            the_map = read_map()
        except Exception:  # noqa: BLE001 - the request names its citations by key alone
            the_map = None
        args = filing_args(record, p, inbox, the_map)
        outcome = await _stage_change(request, runtime, session, branch, {"tool": SUBMIT_TOOL, "args": args, "what": "research"},
                                      Outcome(answer=""))
    finally:
        CURRENT_BRANCH.reset(token)
    if not outcome.ok:
        return {"ok": False, "detail": f"No build request was prepared: {outcome.detail}"}
    ui = compact(present(list(outcome.calls), session=session, writes=await _writes(request)))
    if ui:
        branch.shown(ui, outcome.answer, "")
    proposal_id = str(outcome.changed.get("proposal_id") or "")
    staged = runtime.actions.find(proposal_id) if proposal_id else None
    request_id = str((getattr(staged, "execution", None) or {}).get("request_id") or "")
    return {"ok": True, "ui": ui, "answer": outcome.answer, "branch": branch.public(), "proposal_id": proposal_id,
            "request_id": request_id, "session_id": session.session_id}
