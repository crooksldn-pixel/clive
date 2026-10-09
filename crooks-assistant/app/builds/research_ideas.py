"""The Builds screen's Research section once research is read as ideas (DEC-078).

Why this exists: George's words (9 Oct 2026): "George should not need to review 113 recommendations."
Once a synthesis is live, the section shows what his research says CLIVE should become, the few ideas
that need him, then every idea by when (Now, Next, Later, No date), each with its four answers, and
each document with what became of it. Before one is live, the section is exactly DEC-070's
(app/builds/research.py), with `mode: "proposals"` and how far a synthesis run has got.

What it promises:
- Every word comes from a record or from the one table of words (app/research/synthesis/words.py);
  a document or idea that could not be read says so in `problem`, never silently left out.
- Execution is set here, by code, never the model: Not approved until he approves the work; Ready
  once he has; In progress once its build request is filed; Built when the build loop reports it
  finished; Blocked when the loop stopped it.
- His answer is shown as given: `current` is false when it was given to an earlier view of the idea.
- Approving prepares a build request through the existing path (app/builds/research.py `prepare`),
  behind his hold. The request is filed in CLIVE's public repository, so it carries CLIVE's words only:
  the idea's statement, the owner view's "after", its keys and timing; never a research quote, a
  document's name or a section's title (`requested_outcome` takes out any line that would).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.builds import decisions
from app.research.review import normalise
from app.research.synthesis import answers as idea_answers
from app.research.synthesis.ideas import OWNER_VIEW, documents_backing, judged
from app.research.synthesis.store import ReadProblem, synthesis_store
from app.research.synthesis.summary import counts
from app.research.synthesis.words import AXES, BUILD_WORDS, CHOICES, GROUPS, said, words

COUNTS = ("documents", "claims", "unplaced", "ideas", "converged", "disagreements", "validations", "changes")
STATE_TO_SYNTHESIS = {"queued": "reading", "reading": "reading", "stopped": "failed", "failed": "failed"}
_IMPORTANCE = {k: n for n, k in enumerate(AXES["importance"])}


# ------------------------------------------------------------------ before a synthesis is live


def run_summary(run: dict[str, Any] | None) -> dict[str, Any] | None:
    """How far a synthesis run has got, for the line the screen shows before one is live."""
    from app.research.synthesis.run import STAGE_WORDS

    if not run:
        return None
    stage = str(run.get("stage") or "")
    return {"generation": run.get("generation") or "", "stage": stage, "stage_words": STAGE_WORDS.get(stage, stage),
            "done": int(run.get("done") or 0), "of": int(run.get("of") or 0), "started_at": run.get("started_at") or "",
            "finished_at": run.get("finished_at") or "", "calls": int(run.get("calls") or 0),
            "errors": len(run.get("errors") or [])}


def not_live(research_store) -> dict[str, Any]:
    """What the old section adds before a synthesis is live: the mode, and the newest run if any."""
    synth = synthesis_store(research_store)
    run = None
    for gen in reversed(synth.generations()):
        try:
            run = synth.run(gen)
        except ReadProblem:
            run = None
        if run:
            break
    return {"mode": "proposals", "synthesis": {"state": "not_live", "run": run_summary(run)}}


# ------------------------------------------------------------------ the ideas section


async def current(research_store, ledger) -> dict[str, Any] | None:
    """The section in ideas mode, or None when no synthesis is live."""
    synth = synthesis_store(research_store)
    gen = synth.live()
    if not gen:
        return None
    problems: list[str] = []
    try:
        ideas, claims, events = synth.ideas(gen), synth.claims(gen), synth.events(gen)
        summary, prepared = synth.summary(gen) or {}, synth.prepared()
    except ReadProblem as exc:
        return _unreadable(research_store, str(exc))
    unreadable = sum(1 for e in events if e.get("type") == "unreadable")
    if unreadable:
        problems.append(f"{unreadable} line{'s' if unreadable != 1 else ''} of CLIVE's research history couldn't be read, "
                        "so some ideas' history is missing.")
    try:
        effective = ledger.effective()
    except decisions.DecisionError as exc:
        effective = {}
        problems.append(str(exc))
    the_map = _the_map()
    records = research_store.documents()
    names = {doc_id: c.get("document") or "" for doc_id, c in claims.items()}
    latest = idea_answers.latest(effective)
    history = _history(events)
    rows = []
    for idea in ideas.values():
        if idea.get("status") != "active" or not judged(idea):
            continue
        rows.append(await row(idea, names=names, the_map=the_map, history=history, answer=latest.get(idea["id"]),
                              prepared=prepared.get(idea["id"]), documents=len(claims)))
    rows.sort(key=_order)
    needs = [r for r in rows if r["needs_you"] and not (r["owner_answer"] and r["owner_answer"]["current"])]
    groups = [{"key": key, "title": title, "ideas": [r for r in rows if r["answers"]["timing"]["key"] == timing]}
              for key, timing, title in GROUPS]
    reading = sum(1 for r in records if r.get("state") in ("queued", "reading"))
    return {
        "mode": "ideas",
        "summary": _summary(len(rows), len(claims), len(needs), reading),
        "synthesis": {"generation": gen, "at": summary.get("at") or "", "points": list(summary.get("points") or []),
                      "before": summary.get("before") or "", "after": summary.get("after") or "",
                      # Counted by code from the ideas as they stand, never the model's.
                      "counts": {k: v for k, v in counts(ideas, claims).items() if k in COUNTS}},
        "needs_you": needs,
        "groups": [g for g in groups if g["ideas"]],
        "documents": [_document(r, claims, records) for r in records],
        "waiting": len(needs), "reading": reading, "accepts": _accepts(), "problem": " ".join(problems),
    }


def _unreadable(research_store, why: str) -> dict[str, Any]:
    records = research_store.documents()
    return {"mode": "ideas", "summary": "CLIVE's ideas couldn't be read just now.", "synthesis": {
        "generation": "", "at": "", "points": [], "before": "", "after": "", "counts": {}},
            "needs_you": [], "groups": [], "documents": [], "waiting": 0,
            "reading": sum(1 for r in records if r.get("state") in ("queued", "reading")), "accepts": _accepts(),
            "problem": f"CLIVE's ideas couldn't be read: {why}"}


def _the_map():
    try:
        from app.research.rules import read_map

        return read_map()
    except Exception:  # noqa: BLE001 - keys are then shown by themselves
        return None


def _accepts() -> str:
    from app.research.convert import ACCEPTED

    return ACCEPTED


def _summary(ideas: int, documents: int, waiting: int, reading: int) -> str:
    line = f"{ideas} idea{'' if ideas == 1 else 's'} from {documents} document{'' if documents == 1 else 's'}"
    if waiting:
        line += f"; {waiting} wait{'s' if waiting == 1 else ''} on you"
    if reading:
        line += f"; {reading} being read"
    return line + "."


def _order(row: dict[str, Any]) -> tuple:
    importance = row["answers"]["importance"]["key"]
    return (0 if importance == "FOUNDATIONAL" else 1, -row["backed_by"]["count"], _IMPORTANCE.get(importance, 9), row["id"])


def _history(events: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    out: dict[str, list[dict[str, str]]] = {}
    for event in events:
        if event.get("idea") and event.get("said"):
            out.setdefault(str(event["idea"]), []).append({"at": str(event.get("at") or ""), "said": str(event["said"])})
    return out


def _label(the_map, key: str) -> str:
    entry = the_map.get(key) if the_map is not None else None
    return entry.label() if entry is not None else key


async def row(idea: dict[str, Any], *, names: dict[str, str], the_map, history: dict[str, list[dict[str, str]]],
              answer, prepared: dict[str, Any] | None, documents: int) -> dict[str, Any]:
    """One idea as the screen draws it (the payload contract, docs/RESEARCH.md)."""
    owner = idea_answers.said(answer, idea) if answer is not None else None
    build = await build_state(prepared) if (owner and owner["key"] == "go") or prepared else None
    answers = {axis: said(axis, idea["answers"].get(axis, "")) for axis in AXES if axis != "execution"}
    answers["execution"] = said("execution", execution(owner, build))
    backing = documents_backing(idea)
    centrality = {}
    for source in idea.get("sources") or []:
        if source.get("stance") != "opposes":
            rank = ("central", "supporting", "passing")
            mine = centrality.get(source["doc_id"], "passing")
            centrality[source["doc_id"]] = min(mine, source.get("centrality") or "passing", key=rank.index)
    needs = idea.get("needs_you")
    view = idea.get("owner_view")
    lines = [line for i in [idea["id"], *(idea.get("was") or [])] for line in history.get(i, [])]
    return {
        "id": idea["id"], "fingerprint": idea["fingerprint"], "name": idea["name"], "statement": idea["statement"],
        "kind": idea["kind"], "answers": {axis: answers[axis] for axis in AXES},
        "reasons": {"judgment": idea["reasons"].get("judgment", ""), "timing": idea["reasons"].get("timing", "")},
        "timing_held_by": [{"key": k, "label": _label(the_map, k)} for k in idea.get("timing_held_by") or []],
        "backed_by": {"count": len(backing), "of": documents,
                      "documents": [{"name": names.get(d, ""), "centrality": centrality.get(d, "passing")} for d in backing]},
        "how_they_differ": idea.get("how_they_differ") or "",
        "against": [{"document": _against_document(a, names), "says": a.get("why") or ""} for a in idea.get("against") or []],
        "owner_view": ({k: (view.get(k) or ([] if k == "why_care" else "")) for k in OWNER_VIEW} if view else None),
        "needs_you": ({"trigger": needs["trigger"], "trigger_words": words("trigger", needs["trigger"]),
                       "question": needs["question"]} if needs else None),
        "keys": [{"key": k["key"], "label": _label(the_map, k["key"]), "how": k["how"]} for k in idea.get("keys") or []],
        "today": dict(idea.get("today") or {"level": "none", "says": "", "where": [], "verified": False}),
        "revisit": idea.get("revisit") or "", "effects": list(idea.get("effects") or []),
        "sources": [{k: s.get(k) or "" for k in ("document", "section", "quote", "stance", "centrality")}
                    for s in idea.get("sources") or []],
        "history": sorted(lines, key=lambda h: h["at"]),
        "owner_answer": owner,
        "choices": [{"key": k, "label": label, "then": then} for k, label, then in CHOICES],
        "build": build,
    }


def _against_document(against: dict[str, Any], names: dict[str, str]) -> str:
    claim = str(against.get("claim_id") or "")
    doc_id = claim.split(":")[1] if claim.startswith("stance:") else claim.split(":")[0]
    return names.get(doc_id, "")


def execution(owner: dict[str, Any] | None, build: dict[str, Any] | None) -> str:
    """Execution, set by code from his answer and the build's own state."""
    state = (build or {}).get("state")
    if state == "filed":
        return "IN_PROGRESS"
    if state == "done":
        return "IMPLEMENTED"
    if state == "blocked":
        return "BLOCKED"
    if owner and owner["key"] == "go" and owner["current"]:
        return "READY"
    return "NOT_AUTHORISED"


async def build_state(prepared: dict[str, Any] | None) -> dict[str, Any]:
    """Where an approved idea's build request is: not prepared, waiting for his hold, filed, done or
    blocked, from the build loop's own record of it."""
    from app.builds.research import _filed

    if not prepared:
        return {"state": "not_prepared", "words": BUILD_WORDS["not_prepared"], "request_id": ""}
    rid = str(prepared.get("request_id") or "")
    filed = await _filed(rid)
    if filed == "no":
        return {"state": "waiting", "words": BUILD_WORDS["waiting"], "request_id": rid}
    if filed != "yes":
        return {"state": "unknown", "words": f"Whether it was filed couldn't be read from GitHub: {filed}", "request_id": rid}
    progress = await _progress(rid)
    if progress == "done":
        return {"state": "done", "words": BUILD_WORDS["done"], "request_id": rid}
    if progress in ("blocked", "needs the owner"):
        return {"state": "blocked", "words": BUILD_WORDS["blocked"], "request_id": rid}
    return {"state": "filed", "words": BUILD_WORDS["filed"], "request_id": rid}


async def _progress(request_id: str) -> str:
    from app.tools.engineering_tools import build_progress

    try:
        return str(((await build_progress([request_id])).get(request_id) or {}).get("progress") or "")
    except Exception:  # noqa: BLE001 - the loop's status unread: it is filed, and that is all that is known
        return ""


def _document(record: dict[str, Any], claims: dict[str, dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, Any]:
    from app.builds.research import STATE_WORDS

    state = record.get("state") or "failed"
    source = record
    if record.get("repeat_of"):
        source = next((r for r in records if r.get("id") == record["repeat_of"]), record)
    mine = claims.get(source.get("id") or "") or next(
        (c for c in claims.values() if record.get("file_digest") and c.get("file_digest") == record.get("file_digest")), None)
    synthesis_state = STATE_TO_SYNTHESIS.get(state) or ("absorbed" if mine is not None else "waiting")
    from app.research.flow import WAITING_NOTE

    # A note written while it waited for the first synthesis is no longer true once it is in.
    notes = [str(n) for n in (record.get("notes") or []) if synthesis_state == "waiting" or WAITING_NOTE not in str(n)][:10]
    if synthesis_state == "waiting" and not any(WAITING_NOTE in n for n in notes):
        notes.append("Waiting for the next synthesis to take it in.")
    return {
        "id": record.get("id"), "name": record.get("name") or "", "state": state,
        "state_words": STATE_WORDS.get(state, state), "why": record.get("why") or "",
        "received_at": record.get("received_at") or "", "via": record.get("via") or "",
        "claims": len((mine or {}).get("claims") or []),
        "unplaced": [{"title": u.get("title") or "", "why": u.get("why") or ""} for u in (mine or {}).get("unplaced") or []],
        "synthesis_state": synthesis_state, "notes": notes,
    }


# ------------------------------------------------------------------ approving: the build request, behind his hold


QUOTE_WINDOW = 8


def _windows(text: str) -> set[str]:
    words_ = normalise(text).split()
    return {" ".join(words_[i:i + QUOTE_WINDOW]) for i in range(max(0, len(words_) - QUOTE_WINDOW + 1))}


def _forbidden(idea: dict[str, Any], names: list[str], texts: list[str] = ()) -> tuple[list[str], set[str]]:
    """The research's own words a filed request must never carry: (phrases, windows). Phrases are the
    documents' names, section titles of two words or more (a one-word heading is an ordinary word), and
    short quotes whole; any eight words in a row from a longer quote, or from the documents' own text
    when it is given, is a window."""
    phrases, windows = [], set()
    for text in texts:
        windows |= _windows(text)
    for source in idea.get("sources") or []:
        quote = source.get("quote") or ""
        if len(normalise(quote).split()) < QUOTE_WINDOW:
            phrases.append(normalise(quote))
        windows |= _windows(quote)
        section = str(source.get("section") or "").split(" > ")[-1]
        if len(section.split()) >= 2:
            phrases.append(normalise(section))
    for name in names:
        phrases += [normalise(name), normalise(name.rsplit(".", 1)[0])]
    return [p for p in phrases if len(p) >= 4], windows


def _clean(text: str, forbidden: tuple[list[str], set[str]]) -> bool:
    phrases, windows = forbidden
    said = normalise(text)
    return not any(p in said for p in phrases) and not (_windows(text) & windows)


def requested_outcome(idea: dict[str, Any], *, gen: str, names: list[str], texts: list[str] = (), the_map=None) -> str:
    """What the build request asks for, in CLIVE's words only: the statement, the owner view's
    "after", its keys and its timing. A line that would carry the research's own words is left out."""
    day = datetime.now(UTC).strftime("%-d %b %Y")
    a = idea.get("answers") or {}
    keys = ", ".join(_label(the_map, k["key"]) + f" ({k['how']})" for k in idea.get("keys") or [])
    held = ", ".join(_label(the_map, k) for k in idea.get("timing_held_by") or [])
    lines = [f"From research George gave CLIVE, approved by him on the Builds screen on {day}. The research's own words "
             f"stay in CLIVE's private research record on the server (idea {idea['id']}, {gen}).",
             f"What to build: {idea.get('name')}.",
             f"The idea, in CLIVE's words: {idea.get('statement')}"]
    after = ((idea.get("owner_view") or {}).get("after") or "").strip()
    if after:
        lines.append(f"Afterwards: {after}")
    lines.append(f"CLIVE's view: {words('judgment', a.get('judgment', ''))}; {words('relationship', a.get('relationship', ''))}; "
                 f"timing {words('timing', a.get('timing', ''))}{' (held by ' + held + ')' if held else ''}.")
    if keys:
        lines.append(f"It relates to: {keys}.")
    lines.append("Keep every rule in crooks-assistant/MAP.md; anything outward still waits for his gesture on its card.")
    forbidden = _forbidden(idea, names, texts)
    kept = [line for line in lines if _clean(line, forbidden)]
    if len(kept) < len(lines):
        kept.append("(A line was left out because it repeated the research's own words, which stay on the server.)")
    return "\n".join(kept)


def filing_args(idea: dict[str, Any], inbox_id: str, *, gen: str, names: list[str], texts: list[str] = (),
                the_map=None) -> dict[str, Any]:
    """The arguments `submit_engineering_request` is staged with for an approved idea. `texts` are the
    documents behind it, as the scanner read them: no eight words in a row of theirs go out."""
    forbidden = _forbidden(idea, names, texts)
    title = idea.get("name") if _clean(idea.get("name") or "", forbidden) else f"Research idea {idea['id']}"
    return {"inbox_id": inbox_id, "title": title or "Research idea",
            "requested_outcome": requested_outcome(idea, gen=gen, names=names, texts=texts, the_map=the_map),
            "allowed_paths": list(idea.get("touches") or []),
            "acceptance_criteria": [c for c in idea.get("done_when") or [] if _clean(c, forbidden)]}


def source_texts(research_store, idea: dict[str, Any], records: list[dict[str, Any]]) -> list[str]:
    """The text of every document behind an idea, as the scanner read it, so no run of its words can
    reach a filed request. One that can't be read leaves its quotes to stand for it."""
    from app.research.synthesis.run import document_text

    wanted = {s.get("doc_id") for s in idea.get("sources") or []}
    out = []
    for record in records:
        if record.get("id") in wanted and record.get("artifact_id"):
            try:
                out.append(document_text(research_store, record))
            except (OSError, ValueError):
                continue
    return out
