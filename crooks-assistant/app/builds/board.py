"""Every build of CLIVE itself, as George reads it: what it is for, where it is, why it stopped,
why it matters, and what it needs from him.

George's words (2 Oct 2026): "There is no way for me to simply see what is in progress. SHA and
79bcbcbi848 (or whatever) bears no meaning to me, and better yet I cannot see any build queue,
what's in progress, why it stopped, why it's important anywhere."

A build is one piece of work, however many times it was filed: the loop's convention for a request
asked again is the same id with -2, -3 ... (engineering_tools `_free_id`), so the requests are
grouped by that id, and the newest try says where the build is. The earlier tries stay behind the
details. Where it is comes from the loop's own published fields and two facts read from GitHub:
whether its work is on the trunk, and whether it is in the commit this CLIVE runs. It is one of:

    needs you     the loop left the next step to him (its words), and he has not answered yet; or he
                  asked for something to be done, which nothing has done yet ("answered, waiting to
                  be acted on": the loop cannot read his answers, app/builds/decisions.py)
    in progress   being built, being repaired, being reviewed, or approved and on its way in
    queued        filed, no builder has started it
    stopped       the loop stopped it and the Director, not George, decides what next; or he
                  answered that nothing more be done
    on the trunk  merged, not in the commit CLIVE runs yet
    live          in the commit CLIVE runs

and the board lists them in that order, newest first in each. A build stopped by the loop whose
work reached the trunk anyway (merged outside the loop) is on the trunk, and says so. Each build
carries its road: Filed, Built, Reviewed, On the trunk, Live, lit as far as it has come, with the
stage it is at marked as moving, waiting on him, or stopped.

Nothing on the face is a SHA, a branch name or a request id: those, and the loop's own words, sit
in `details`. Every word is the loop's, the request's or the reviewer's, cleaned by app/builds/
plain.py, or a fixed sentence here that says what a field means; a fact that could not be read is
said to be missing, never filled in.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from app.builds import decisions, plain
from app.tools.engineering_tools import _said

STAGES = ("Filed", "Built", "Reviewed", "On the trunk", "Live")
GROUPS = ("needs_you", "in_progress", "queued", "stopped", "landed", "live")
GROUP_TITLES = {"needs_you": "Needs you", "in_progress": "In progress", "queued": "Queued", "stopped": "Stopped",
                "landed": "On the trunk, not live yet", "live": "Live"}

_QUEUED = frozenset({"", "PROPOSED", "READY"})
_BUILDING = frozenset({"ASSIGNED", "RUNNING"})
_REVIEWING = frozenset({"EVIDENCE_READY", "REVIEWING", "ACCEPTED"})
_RETRY = re.compile(r"-(\d{1,2})$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
MAX_TRIES_SHOWN = 8
ASKED_CHARS = 1200


# ------------------------------------------------------------------ small readers


def _str(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _sha(value: Any) -> str:
    return value if isinstance(value, str) and _HEX40.fullmatch(value) else ""


def _iso(value: Any) -> str:
    """A time the loop published, in UTC to the second, or "" when it is not a time."""
    if not isinstance(value, str) or not value or len(value) > 40:
        return ""
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if stamp.tzinfo is None:
        return ""
    return stamp.astimezone(UTC).isoformat(timespec="seconds")


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _attempts(item: dict[str, Any]) -> list[dict[str, Any]]:
    listed = item.get("attempts")
    return [a for a in listed if isinstance(a, dict)] if isinstance(listed, list) else []


def family_key(request_id: str) -> str:
    """The build a request belongs to: its id without the -2, -3 ... of a request asked again."""
    return _RETRY.sub("", request_id)


def _order(item: dict[str, Any]) -> tuple[str, int]:
    match = _RETRY.search(_str(item.get("request_id")))
    return (_iso(item.get("recorded_at")), int(match.group(1)) if match else 1)


def families(items: list[dict[str, Any]], titles: dict[str, str]) -> list[list[dict[str, Any]]]:
    """The requests grouped into builds, each oldest try first. Ids that share a stem are one build
    when one of them is the stem itself or their titles agree; two differently titled requests
    that only share a stem stay two builds."""
    by_key: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        rid = _str(item.get("request_id"))
        if rid:
            by_key.setdefault(family_key(rid), []).append(item)
    out: list[list[dict[str, Any]]] = []
    for key, members in by_key.items():
        known = {titles[m["request_id"]] for m in members if titles.get(m["request_id"])}
        if len(known) > 1 and not any(m["request_id"] == key for m in members):
            for title in sorted(known):
                out.append(sorted([m for m in members if titles.get(m["request_id"]) == title], key=_order))
            rest = [m for m in members if not titles.get(m["request_id"])]
            if rest:
                out.append(sorted(rest, key=_order))
        else:
            out.append(sorted(members, key=_order))
    return out


# ------------------------------------------------------------------ where one build is


def _landed_sha(item: dict[str, Any]) -> str:
    landing = _dict(item.get("landing"))
    return _sha(landing.get("sha")) if landing.get("state") == "landed" else ""


def _fact(commits: dict[str, dict[str, Any]], shas: list[str], key: str) -> bool | None:
    """True when any of the commits is there, False when all were checked and none is, None when
    it could not be told."""
    seen = [commits.get(s, {}).get(key) for s in shas if s]
    if any(v is True for v in seen):
        return True
    return False if seen and all(v is False for v in seen) else None


def _when(item: dict[str, Any], state: str) -> dict[str, str]:
    """The moment that says the most about where it is, and what happened then."""
    attempts = _attempts(item)
    last = _iso(attempts[-1].get("at")) if attempts else ""
    filed = _iso(item.get("recorded_at"))
    gate = _dict(item.get("github_acceptance"))
    review = _dict(item.get("review"))
    accepted = _iso(_dict(item.get("acceptance")).get("at")) or _iso(_dict(item.get("integration")).get("at"))
    landing = _dict(item.get("landing"))
    if state == "queued":
        return {"event": "filed", "at": filed}
    if state == "building":
        return {"event": "started", "at": last or filed}
    if state == "reviewing":
        return {"event": "review", "at": _iso(review.get("dispatched_at")) or _iso(gate.get("checked_at")) or last or filed}
    if state in ("needs_you", "stopped", "decided"):
        times = [t for t in (last, _iso(gate.get("checked_at")), _iso(landing.get("at"))) if t]
        return {"event": "stopped", "at": max(times) if times else filed}
    if state == "built":
        return {"event": "approved", "at": accepted or last or filed}
    if landing.get("state") == "landed" and _iso(landing.get("at")):
        return {"event": "landed", "at": _iso(landing.get("at"))}
    return {"event": "finished", "at": accepted or last or filed}


def _road(lit: int, mark: int | None = None, kind: str | None = None) -> dict[str, Any]:
    return {"stages": list(STAGES), "lit": lit, "mark": mark, "mark_kind": kind if mark is not None else None}


def place(item: dict[str, Any], why: dict[str, Any] | None, commits: dict[str, dict[str, Any]],
          running_known: bool) -> dict[str, Any]:
    """Where the newest try of a build is: its state, group, words, road and note."""
    stage = _str(item.get("stage")).upper()
    outcome = _str(item.get("outcome"))
    shas = [_sha(item.get("candidate_sha")), _landed_sha(item)]
    on_trunk = _fact(commits, shas, "trunk")
    live = _fact(commits, shas, "running") if running_known else None
    note = ""
    if on_trunk or live:
        if stage != "COMPLETE":
            note = "The loop stopped it, but its work is on the trunk: it was merged outside the loop."
        if live:
            return {"state": "live", "group": "live", "words": "Live", "road": _road(5), "note": note}
        if not running_known:
            note = (note + " " if note else "") + "CLIVE can't tell which commit it is running, so it can't say whether this is live."
        return {"state": "landed", "group": "landed", "words": "On the trunk, not live yet" if running_known else "On the trunk",
                "road": _road(4, 4, "wait"), "note": note}
    if outcome == "waiting":
        return {"state": "queued", "group": "queued", "words": "Waiting for its starting point to reach the build server",
                "road": _road(1, 1, "wait"), "note": ""}
    if outcome == "refused" or stage in ("BLOCKED", "OWNER_GATE") or item.get("owner_gate") is True:
        stopped = why or plain.why_stopped(item)
        at = stopped["at"]
        if stopped["who"] == plain.YOU:
            return {"state": "needs_you", "group": "needs_you", "words": "Waiting on you", "road": _road(at, at, "you"), "note": ""}
        return {"state": "stopped", "group": "stopped", "words": "Waiting on the Director", "road": _road(at, at, "stop"),
                "note": ""}
    if stage == "COMPLETE":
        landing = _dict(item.get("landing"))
        state_of = _str(landing.get("state"))
        if state_of == "refused":
            return {"state": "stopped", "group": "stopped", "words": "Waiting on the Director",
                    "road": _road(3, 3, "stop"), "note": ""}
        words = {"waiting": "Approved, waiting to land on the trunk",
                 "refreshing": "Approved, being brought up to date with the trunk"}.get(state_of, "Approved, not on the trunk yet")
        if on_trunk is None:
            note = "CLIVE couldn't check the trunk for it just now."
        return {"state": "built", "group": "in_progress", "words": words, "road": _road(3, 3, "now"), "note": note}
    if stage in _QUEUED:
        return {"state": "queued", "group": "queued", "words": "Waiting for a builder", "road": _road(1, 1, "wait"), "note": ""}
    if stage in _BUILDING:
        return {"state": "building", "group": "in_progress", "words": "Being built", "road": _road(1, 1, "now"), "note": ""}
    if stage == "REJECTED":
        return {"state": "building", "group": "in_progress", "words": "Being repaired after review",
                "road": _road(1, 1, "now"), "note": ""}
    if stage in _REVIEWING:
        green = _dict(item.get("github_acceptance")).get("state") == "green"
        words = {"EVIDENCE_READY": "Waiting for the reviewer" if green else "Waiting for GitHub's tests",
                 "REVIEWING": "Being reviewed",
                 "ACCEPTED": "Approved, being merged into its branch"}[stage]
        return {"state": "reviewing", "group": "in_progress", "words": words, "road": _road(2, 2, "now"), "note": ""}
    return {"state": "stopped", "group": "stopped", "words": "Stopped", "road": _road(1, 1, "stop"),
            "note": f"The loop reports it as {stage.lower() or 'unknown'}."}


# ------------------------------------------------------------------ what it is for, why it matters


def _purpose(rids: list[str], links: dict[str, dict[str, Any]], asked: str) -> tuple[str, str]:
    """(what it is for, why it matters), from CLIVE's own records of the objective or gap a request
    serves; with neither, what was asked, and the plain fact that nothing of CLIVE's links to it."""
    objective = next((links[r]["objective"] for r in rids if links.get(r, {}).get("objective")), None)
    gaps: list[dict[str, Any]] = []
    for r in rids:
        for gap in links.get(r, {}).get("gaps") or []:
            if gap not in gaps:
                gaps.append(gap)
    gaps.sort(key=lambda g: -int(g.get("hits") or 0))
    serves = []
    if objective:
        serves.append(f"For your objective “{objective['title']}”.")
    if gaps:
        serves.append(f"It closes a gap: “{gaps[0]['title']}”.")
    if not serves and asked:
        serves.append(plain._stop(plain.first_sentence(asked, 240)))
    if gaps:
        top = gaps[0]
        hits = int(top.get("hits") or 0)
        matters = (f"CLIVE couldn't do this {plain.number_word(hits) if hits <= 10 else hits} "
                   f"time{'' if hits == 1 else 's'}")
        if top.get("last_seen"):
            matters += ", most recently on " + _day(top["last_seen"])
        matters += "."
        if len(gaps) > 1:
            matters += f" It closes {plain.number_word(len(gaps) - 1)} more gap{'' if len(gaps) == 2 else 's'} too."
    else:
        matters = "No gap or objective of CLIVE's is linked to it, so how often it came up isn't recorded."
    return " ".join(serves), matters


def _day(iso: str) -> str:
    stamp = _iso(iso)
    if not stamp:
        return "an unknown day"
    when = datetime.fromisoformat(stamp)
    return f"{when.day} {when.strftime('%b')}"


# ------------------------------------------------------------------ one build


def _why(why: dict[str, Any]) -> dict[str, str]:
    """Why it stopped, and who it now waits on when that is not George."""
    says = why["says"]
    if why["who"] == plain.DIRECTOR:
        says += " The Director decides what happens next."
    return {"says": says, "who": why["who"]}


def _stopped(item: dict[str, Any]) -> bool:
    """The loop stopped this request: refused at its door, blocked, or at the owner gate."""
    return _str(item.get("outcome")) == "refused" or _str(item.get("stage")).upper() in ("BLOCKED", "OWNER_GATE") \
        or item.get("owner_gate") is True


def _try_words(item: dict[str, Any]) -> str:
    stage = _str(item.get("stage")).upper()
    if _stopped(item):
        return plain.why_stopped(item)["says"]
    if stage == "COMPLETE":
        return "Finished and approved."
    return "Still going."


def build(members: list[dict[str, Any]], requests: dict[str, dict[str, str]], commits: dict[str, dict[str, Any]],
          running_known: bool, links: dict[str, dict[str, Any]], judgments: dict[str, Any]) -> dict[str, Any]:
    """One build, from its tries (oldest first), as the screen draws it."""
    latest = members[-1]
    rid = _str(latest.get("request_id"))
    why = plain.why_stopped(latest) if _stopped(latest) else None
    where = place(latest, why, commits, running_known)
    rids = [_str(m.get("request_id")) for m in members]
    request = next((requests[r] for r in reversed(rids) if requests.get(r, {}).get("title")), {})
    serves, matters = _purpose(rids, links, request.get("asked", ""))
    out: dict[str, Any] = {
        "key": family_key(rid),
        "title": request.get("title") or "",
        "state": where["state"], "group": where["group"], "words": where["words"], "road": where["road"],
        "note": where["note"],
        "why": _why(why) if why and where["group"] in ("needs_you", "stopped") else None,
        "findings": None, "finding_ids": why["findings"] if why else [],
        "serves": serves, "matters": matters, "matters_known": any(links.get(r, {}).get("gaps") for r in rids),
        "tries": len(members),
        "decision": None, "chosen": None,
    }
    if why and where["group"] in ("needs_you", "stopped"):
        out["findings"] = plain.findings_of(latest)
        stops = sum(1 for m in members if _stopped(m) and plain.why_stopped(m)["kind"] == why["kind"])
        question = decisions.card(latest, why, tries=len(members), stops=max(stops, 1))
        if question is not None:
            answered = judgments.get(question["proposal_id"])
            out["decision"] = question
            out["chosen"] = decisions.chosen(answered)
            if out["chosen"] and out["chosen"]["acts"]:
                # He asked for something to be done, and nothing reads the ledger yet: it stays on his
                # list, answered, until the build moves on (the independent review of fe36872f, B-1).
                out.update(state="answered", words=out["chosen"]["after"])
                out["road"] = _road(where["road"]["lit"], where["road"]["mark"], "wait")
            elif out["chosen"]:
                # An answer that asks for nothing to be done is true once recorded: it leaves his list.
                out.update(state="decided", group="stopped", words=out["chosen"]["after"])
                out["road"] = _road(where["road"]["lit"], where["road"]["mark"], "stop")
    out["when"] = _when(latest, "stopped" if out["state"] in ("decided", "answered") else out["state"])
    out["details"] = _details(members, latest, request)
    return out


def _details(members: list[dict[str, Any]], latest: dict[str, Any], request: dict[str, str]) -> dict[str, Any]:
    """The technical record, for the details disclosure only: ids, branch, commits, the loop's own
    words, GitHub's runs and the review's verdicts, and what was asked."""
    integration = _dict(latest.get("integration"))
    gate = _dict(latest.get("github_acceptance"))
    review = _dict(latest.get("review"))
    runs = [r.get("id") for r in gate.get("runs") or [] if isinstance(r, dict) and isinstance(r.get("id"), int)]
    verdicts = [_said(v.get("verdict"), 40) for v in review.get("verdicts") or [] if isinstance(v, dict)]
    tries = []
    for m in members[-MAX_TRIES_SHOWN:]:
        tries.append({"request_id": _said(m.get("request_id"), 80), "stage": _said(m.get("stage") or m.get("outcome"), 30),
                      "words": _try_words(m), "loop_words": plain.why_stopped(m)["loop_words"] if _stopped(m) else "",
                      "filed": _iso(m.get("recorded_at"))})
    rid = _str(latest.get("request_id"))
    return {
        "request_id": _said(rid, 80),
        "branch": _said(integration.get("target_branch") or request.get("target_branch") or f"clive/objective/{rid}", 120),
        "candidate": _sha(latest.get("candidate_sha")),
        "base": _sha(request.get("base_sha")),
        "revision": latest.get("revision") if isinstance(latest.get("revision"), int) else None,
        "github_runs": runs[:6],
        "github": plain.loop_said(gate.get("detail"), latest, 300),
        "verdicts": verdicts[-6:],
        "loop_words": plain.why_stopped(latest)["loop_words"] if _str(latest.get("blocker") or latest.get("reason")) else "",
        "asked": _said(request.get("asked"), ASKED_CHARS),
        "tries": tries,
    }


# ------------------------------------------------------------------ the board


def _words_count(n: int) -> str:
    return plain.number_word(n, lower=False)


def summary(counts: dict[str, int], running_known: bool) -> str:
    you = counts.get("needs_you", 0)
    answered = counts.get("answered", 0)
    moving = counts.get("in_progress", 0)
    landed = counts.get("landed", 0)
    parts = ["Nothing needs you." if not you else
             f"{_words_count(you)} build{' needs' if you == 1 else 's need'} you."]
    if answered:
        parts.append(f"{_words_count(answered)} answered, waiting to be acted on.")
    parts.append("Nothing is being built right now." if not moving else f"{_words_count(moving)} in progress.")
    if landed:
        parts.append(f"{_words_count(landed)} on the trunk, not live yet." if running_known else f"{_words_count(landed)} on the trunk.")
    return " ".join(parts)


def board(items: list[dict[str, Any]], *, requests: dict[str, dict[str, str]], commits: dict[str, dict[str, Any]],
          running_known: bool, links: dict[str, dict[str, Any]], judgments: dict[str, Any],
          as_of: str = "") -> dict[str, Any]:
    """Every build, grouped and ordered for the screen."""
    titles = {rid: r.get("title", "") for rid, r in requests.items()}
    built = [build(f, requests, commits, running_known, links, judgments) for f in families(items, titles)]
    groups = []
    counts: dict[str, int] = {}
    for key in GROUPS:
        rows = sorted((b for b in built if b["group"] == key), key=lambda b: b["when"].get("at") or "", reverse=True)
        counts[key] = len(rows)
        if key == "needs_you":
            # What still waits on his answer, and apart from it what he answered that waits on others.
            counts["answered"] = sum(1 for b in rows if b["state"] == "answered")
            counts[key] -= counts["answered"]
            rows.sort(key=lambda b: b["state"] == "answered")   # stable: unanswered first, newest first in each
        if rows:
            groups.append({"key": key, "title": GROUP_TITLES[key], "builds": rows})
    return {"summary": summary(counts, running_known), "counts": counts, "groups": groups,
            "as_of": _iso(as_of), "running_known": running_known}
