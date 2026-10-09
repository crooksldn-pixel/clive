"""Engineering objectives, filed from CLIVE into the remote engineering loop.

Two tools. `engineering_status` reads the status the loop publishes and says where each request
is, in plain words. Each line also says what the build went through, as far as the loop publishes it
(`history`: how many times it was built and retried by itself, what the review and GitHub asked for,
the blocker in full, whether it landed on the trunk), and whether the loop will try again by itself
(`next_step`): a blocked build needs the Director, and filing the same request again fails the same
way unless the cause is different. A request held until its base commit reaches the build server is
said to be waiting for it. It also reads the inbox branch's head commit and returns it as the inbox's
`id`, which the dispatcher issues to the conversation exactly as it issues any id a read
returns (app/tools/dispatch.py `_harvest_ids`).

Its answer stays small however many requests the loop has recorded (9 Oct 2026: every request ever
recorded made it 56 KB, the claude CLI handed the model a "too large" note in its place, and the
owner's "yes" to filing a build failed for want of the inbox id). It always carries the counts, the
inbox id and the base; it lists the requests waiting on the owner, those open or blocked, and the
newest few, newest first and at most MAX_LISTED, and says how many more there are, by state, with the
ids of those not done (`not_listed_ids`); `request_ids` returns named ones in full. Each line is said whole while the listing fits, and by its headline when
it would not. Whatever the loop publishes, the answer is at most MAX_ANSWER_BYTES as the model reads it
(`_within`), so filing never depends on a read that can outgrow the CLI's limit.

`submit_engineering_request` is a write, and it acts on that issued inbox id: the gate's
existing issued-id rule is what stages it for the owner (app/tools/gate.py). Its handler only
prepares — builds the request, holds it to the loop's own intake rules
(app/engineering_bridge/requests.py) and reads the inbox. Nothing is filed until the owner
authorises the card; then the action engine re-reads the inbox head and confirms the file is
still absent, creates it, and proves it by reading the file back and comparing the bytes.

With no token in the secret store both tools say GitHub is not connected, and nothing is sent.

CLIVE's model cannot read its own code or know a commit, so it supplies only what the owner
wants: a title, the outcome, what done looks like and which parts of CLIVE the work may touch
(`engineering_status` with `areas` lists them). The rest is filled in here: the base is the
trunk's head read now (named by its SHA, which is how every request so far has named it, so a
trunk that moves before the loop's next fetch cannot unresolve it); the id is the title's words;
the checks are the named test files and ruff, run with the builders' own interpreter. A build
with no test file named is given one to write, and its check fails until it exists. The base
and the checks are never taken from the caller: the tool has no such arguments.

Filed for an objective (`objective_id`), the request is linked to it once GitHub has confirmed
the file was created (app/objectives/store.py `link_engineering`), and the objective becomes a build objective whose
progress is the loop's.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.actions.models import Observed, Prepared
from app.capabilities.families import CapabilityFamily, register
from app.engineering_bridge.github import (
    INBOX_BRANCH,
    TRUNK_REF,
    EngineeringInbox,
    GitHubError,
    InboxHead,
    LoopStatus,
    NotConnected,
    Refused,
)
from app.engineering_bridge.requests import (
    RequestRefused,
    build_request,
    target_branch,
    valid_request_id,
)
from app.logging.turnlog import redact_text
from app.orchestrator.objectives import protected_paths_in
from app.orchestrator.workers.check_server import redact as _redact_secrets
from app.tools.gate import Tier
from app.tools.registry import ToolError, WriteSpec, tool

log = logging.getLogger("crooks.tools.engineering")

STATUS_TOOL = "engineering_status"
SUBMIT_TOOL = "submit_engineering_request"
OPERATION = "engineering_request_file"

# How much of the loop's own words a line repeats.
MAX_REASON_CHARS = 300
# A blocker is said in full up to this: it is what the Director acts on. The story it ends runs to
# the second bound (its tries, retries and repairs are a few short clauses before it).
MAX_BLOCKER_CHARS = 1000
MAX_HISTORY_CHARS = 1400
MAX_GENERATED_NAMED = 3

# The checkout the builders build (this one's parent is the repository root), and the one
# folder of it CLIVE's code lives in: every path a request names is relative to the root.
APP_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = "crooks-assistant"
# Where a path the model gives without the folder ("app/recipes.py", "web/alpha.js") belongs.
APP_TOP = ("app", "web", "kb", "docs", "scripts", "config", "tests", "deploy")
# The builders' own interpreter (CROOKS_ENGINEERING_CHECK_PYTHON): checks run on their host,
# never this one, in a sandbox with PATH only.
DEFAULT_CHECK_PYTHON = "/home/user/clive/crooks-assistant/.venv/bin/python"
RUFF_ARGS = ("-m", "ruff", "check", "app", "config", "scripts", "tests")
MAX_AREAS = 160
MAX_ID_SUFFIX = 9

# The most one engineering_status answer may be, in UTF-8 bytes as the model reads it. The claude CLI
# (2.1.283, measured 9 Oct 2026) passes an MCP tool result on whole while its estimate, a quarter of
# its characters, is under half of MAX_MCP_OUTPUT_TOKENS (25,000 unless set, or lowered by Anthropic's
# own flag); past that it counts the tokens, and a result over the limit is replaced by a note that it
# was saved to a file, which CLIVE's model, with no file tools, cannot open. 16,000 bytes is an
# estimate of at most 4,000 tokens: a third of the 12,500 at which counting starts, so it is passed on
# uncounted even if the limit were cut to a third of today's.
MAX_ANSWER_BYTES = 16_000
MAX_LISTED = 20           # requests one listing names
MAX_RECENT = 5            # the newest requests, listed whatever their state
MAX_HEADLINE_CHARS = 200  # a listed request's words, when the listing is said by headlines
MAX_NAMED = 5             # requests one call returns in full (request_ids)
MAX_AREAS_BYTES = 6_000   # the areas a build may change, as listed (3,918 bytes on 9 Oct)
MAX_IDS_BYTES = 3_000     # the ids of requests not listed and not done (about 30 bytes each)

_inbox: EngineeringInbox | None = None
_check_python = DEFAULT_CHECK_PYTHON


def bind(inbox: EngineeringInbox) -> None:
    """The client the tools use. The runtime binds one at start-up; a test binds a fake."""
    global _inbox
    _inbox = inbox
    _progress_cache.clear()


def configure(*, check_python: str | None = None) -> None:
    """The builders' interpreter the default checks run with."""
    global _check_python
    if not check_python:
        return
    if not check_python.startswith("/") or any(c.isspace() for c in check_python):
        # A bad setting must not stop CLIVE starting; the builders' own default stands.
        log.warning("CROOKS_ENGINEERING_CHECK_PYTHON is not an absolute path without spaces; using %s", _check_python)
        return
    _check_python = check_python


def _client() -> EngineeringInbox:
    global _inbox
    if _inbox is None:
        _inbox = EngineeringInbox()
    return _inbox


register(CapabilityFamily(
    key="engineering", label="Engineering objectives", area="system",
    what="file an engineering objective into CLIVE's remote engineering loop and say how it is going",
    operations=(OPERATION,), tools=(STATUS_TOOL,),
    state="READY", detail="ready",
))


# ------------------------------------------------------------------ the read


@tool(
    name=STATUS_TOOL,
    description=(
        "How the engineering objectives filed into the remote engineering loop are going: "
        "queued, building, in review, done, blocked, or needs the owner. Returns the inbox id "
        "that submit_engineering_request takes. areas: true lists the parts of CLIVE a build may change. "
        "request_ids: those requests in full."
    ),
    input_schema={"type": "object", "properties": {
        "areas": {"type": "boolean"},
        "request_ids": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_NAMED},
    }},
    tier=Tier.GREEN,
)
async def engineering_status(areas: bool = False, request_ids: list[str] | None = None) -> dict:
    inbox = _client()
    try:
        status = await inbox.status()
        if isinstance(status, NotConnected):
            return _not_connected(status)
        head = await inbox.inbox_head()
        if isinstance(head, NotConnected):
            return _not_connected(head)
        trunk = await inbox.trunk_head()
    except GitHubError as exc:
        raise ToolError(str(exc)) from None
    items = _items(status.data if status.published else {})
    rows = [progress(item) for item in items]
    _remember(status, items=items, rows=[dict(row) for row in rows])
    _with_owner_decisions(rows, items)
    extra: dict[str, Any] = {"host": inbox.host}
    if isinstance(trunk, InboxHead) and trunk.sha:
        extra["base"] = {"ref": TRUNK_REF, "sha": trunk.sha}
    if areas:
        extra.update(_areas(buildable_areas()))
        extra["tests"] = (
            f"Tests are files under {APP_DIR}/tests/: name the ones the build should add or change "
            f"(for example {APP_DIR}/tests/test_<topic>.py). With none named, one is added for it."
        )
    return project(status, head, branch=inbox.inbox_branch, rows=rows, request_ids=request_ids, extra=extra)


def _with_owner_decisions(rows: list[dict], items: list[dict]) -> None:
    """George's answer on a build that waited on him (the Builds screen, app/builds/decisions.py),
    put on the request it is about, so whoever reads the build reads his answer with it. Read from
    the judgment ledger; nothing is put on a row when there is none or it cannot be read. The loop
    cannot read the ledger, so an answer that asks for something to be done says that nothing has
    acted on it: whoever files builds is the one to act."""
    try:
        from app.builds import decisions
        from app.builds.board import _iso, family_key

        records = list(decisions.ledger().effective().values())
    except Exception:  # noqa: BLE001 - the status is said whole without them
        log.info("owner decisions unreadable for engineering_status", exc_info=True)
        return
    latest: dict[str, Any] = {}
    for record in records:
        rid = decisions.request_of(record)
        if rid and (rid not in latest or record.decided_at > latest[rid].decided_at):
            latest[rid] = record
    # A try filed after his answer, in the same build (the loop's -2, -3 ... convention), is what acting on it is.
    filed: dict[str, list[tuple[str, str]]] = {}
    for item in items:
        rid = str(item.get("request_id") or "")
        filed.setdefault(family_key(rid), []).append((_iso(item.get("recorded_at")), rid))
    for row in rows:
        rid = row.get("request_id", "")
        said = decisions.chosen(latest.get(rid))
        if not said:
            continue
        row["owner_decision"] = {"answer": said["label"], "means": said["then"], "decided_at": said["decided_at"],
                                 "needs_acting_on": said["acts"]}
        if said["acts"]:
            after = sorted(r for at, r in filed.get(family_key(rid), []) if r != rid and at > said["decided_at"])
            row["owner_decision"]["acted_on"] = (
                f"Yes: {_words(after[-1], 80)} was filed after it." if after else
                "No: the build loop cannot read the owner's answers, so nothing has acted on it yet. "
                "Filing the new try is what acts on it.")


def _not_connected(result: NotConnected) -> dict:
    return {"connected": False, "summary": result.reason, "requests": []}


def _items(data: Any) -> list[dict]:
    """Every request the loop's status names: those it decided, then those still waiting for their
    base commit to reach the build server (``waiting_requests``). An id is listed once."""
    if not isinstance(data, dict):
        return []
    items: list[dict] = []
    seen: set[str] = set()
    for key in ("requests", "waiting_requests"):
        listed = data.get(key)
        for item in listed if isinstance(listed, list) else ():
            if not isinstance(item, dict):
                continue
            rid = str(item.get("request_id") or "")
            if rid and rid in seen:
                continue
            seen.add(rid)
            items.append(item)
    return items


def project(status: LoopStatus, head: InboxHead, *, branch: str = INBOX_BRANCH, rows: list[dict] | None = None,
            request_ids: Any = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """The loop's status.json in plain words, at most MAX_ANSWER_BYTES as the model reads it: how many
    requests are in each state, the inbox's id, what `extra` adds (the host, the base, the areas), and
    the requests worth naming unasked (`_listed`) or, with `request_ids`, those named, in full
    (`_named`). `rows` are the requests' lines when the caller has them already (with the owner's
    answers put on them); otherwise they are read from the status here."""
    data = status.data if status.published else {}
    items = _items(data)
    rows = [progress(item) for item in items] if rows is None else rows
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["progress"]] = counts.get(row["progress"], 0) + 1
    if not status.published:
        summary = "The engineering loop has not published a status yet."
    elif not rows:
        summary = "The engineering loop has no requests yet."
    else:
        summary = f"{len(rows)} engineering request{'s' if len(rows) != 1 else ''}: " + ", ".join(
            f"{count} {label}" for label, count in counts.items()
        ) + "."
    adapter = data.get("adapter") if isinstance(data.get("adapter"), dict) else {}
    if adapter.get("intake_error"):
        summary += f" The loop could not read its inbox last time: {_said(adapter['intake_error'])}."
    if adapter.get("trunk_fetch_error"):
        summary += f" The loop could not fetch the trunk last time: {_said(adapter['trunk_fetch_error'])}."
    out: dict[str, Any] = {"connected": True, "summary": summary}
    if head.sha:
        # `id` is the key the dispatcher issues from; this is the inbox the owner may file into.
        out["inbox"] = {"id": head.sha, "branch": branch}
    else:
        out["summary"] += " The inbox branch does not exist yet, so nothing can be filed."
    if isinstance(data.get("generated_at"), str):
        out["as_of"] = data["generated_at"][:40]
    out.update(extra or {})
    asked = _asked(request_ids)
    return _within(out, _named(rows, asked) if asked else _listed(items, rows))


# ------------------------------------------------------------------ an answer that stays small

_OPEN_OR_BLOCKED = frozenset({"queued", "building", "in review", "blocked"})
# The order the model reads an answer's parts in: what filing needs before any request, so a reader
# that cuts a long answer short (an older CLI truncated instead) still has the inbox id and the base.
_ORDER = ("connected", "summary", "inbox", "base", "host", "as_of", "not_listed", "not_listed_ids", "not_found",
          "detail", "blocked_means", "requests", "areas", "areas_not_listed", "tests")
# The states a listing's left-out requests are counted in, in the order they are said.
_STATES = ("needs the owner", "queued", "building", "in review", "blocked", "done")


class _Listing:
    """The requests an answer would name. `chosen` is most important first, so the last is the first
    left out when the answer would not fit; `place` is where each stands when said, and `total` how
    many there are to say."""

    def __init__(self, rows: list[dict], chosen: list[int], place: dict[int, int], *, total: int,
                 named: bool, asked_more: int = 0, not_found: list[str] | None = None) -> None:
        self.rows, self.chosen, self.place, self.total, self.named = rows, chosen, place, total, named
        self.asked_more, self.not_found = asked_more, not_found or []


def _listed(items: list[dict], rows: list[dict]) -> _Listing:
    """The requests worth naming unasked, most important first, at most MAX_LISTED: those waiting
    on the owner, or carrying an answer of his nothing has acted on yet; then, newest first, those
    open or blocked and the MAX_RECENT newest whatever their state. A request that is done and
    older than those is counted, not named. Said newest first."""
    newest = _newest_first(items, rows)
    recent = set(newest[:MAX_RECENT])
    first = [n for n in newest if _waits_on_owner(rows[n])]
    taken = set(first)
    then = [n for n in newest if n not in taken and (rows[n].get("progress") in _OPEN_OR_BLOCKED or n in recent)]
    return _Listing(rows, (first + then)[:MAX_LISTED], {n: place for place, n in enumerate(newest)},
                    total=len(rows), named=False)


def _asked(request_ids: Any) -> list[str]:
    """The ids asked for, once each and in order: a list of them, or one given on its own. None, or
    nothing usable, asks for the listing."""
    asked = [request_ids] if isinstance(request_ids, str) else request_ids if isinstance(request_ids, list) else []
    return list(dict.fromkeys(r.strip() for r in asked if isinstance(r, str) and r.strip()))


def _named(rows: list[dict], wanted: list[str]) -> _Listing:
    """The requests asked for by id, each in full, in the order asked; at most MAX_NAMED."""
    at = {row.get("request_id"): n for n, row in enumerate(rows)}
    chosen = [at[r] for r in wanted[:MAX_NAMED] if r in at]
    return _Listing(rows, chosen, {n: place for place, n in enumerate(chosen)}, total=len(chosen), named=True,
                    asked_more=max(0, len(wanted) - MAX_NAMED),
                    not_found=[_words(r, 80) for r in wanted[:MAX_NAMED] if r not in at])


def _waits_on_owner(row: dict) -> bool:
    said = row.get("owner_decision")
    unacted = isinstance(said, dict) and said.get("needs_acting_on") is True and str(said.get("acted_on", "")).startswith("No")
    return row.get("progress") == "needs the owner" or unacted


def _newest_first(items: list[dict], rows: list[dict]) -> list[int]:
    """Each request's place, the latest to have something happen first: recorded, held waiting,
    landed, or answered by the owner. The loop publishes them by name, not by time; requests with the
    same time, or none, keep their places as published, after those with one."""
    from app.builds.board import _iso

    def latest(n: int) -> str:
        item, row = items[n], rows[n]
        landing = item.get("landing") if isinstance(item.get("landing"), dict) else {}
        said = row.get("owner_decision") if isinstance(row.get("owner_decision"), dict) else {}
        return max(_iso(item.get("recorded_at")), _iso(item.get("waiting_since")), _iso(landing.get("at")),
                   _iso(said.get("decided_at")))

    when = [latest(n) for n in range(len(items))]
    return sorted(range(len(items)), key=lambda n: (when[n], -n), reverse=True)


def _headline(row: dict) -> dict:
    """A listed request when the listing is said by headlines: its id, where it is, its words cut to
    MAX_HEADLINE_CHARS, and the owner's answer on it as he gave it."""
    out = {"request_id": row.get("request_id"), "progress": row.get("progress"),
           "words": _words(row.get("words"), MAX_HEADLINE_CHARS)}
    if "owner_decision" in row:
        out["owner_decision"] = row["owner_decision"]
    return out


def _size(answer: dict) -> int:
    """The answer's size as the model reads it: JSON as app/tools/dispatch.py `_render` writes it."""
    return _bytes(json.dumps(answer, ensure_ascii=False, default=str))


def _bytes(text: str) -> int:
    """UTF-8 bytes, never refused: a lone surrogate the loop published (a log cut through an emoji)
    counts as the six bytes of its escape, as the SDK sends it, and never makes the read fail."""
    return len(text.encode("utf-8", "backslashreplace"))


def _within(out: dict[str, Any], listing: _Listing) -> dict[str, Any]:
    """The answer, in the order the model reads it and at most MAX_ANSWER_BYTES. A listing's requests
    are put on whole while they all fit, said by their headlines when they do not, and then the least
    important are left out until it fits; a request named in full is left out rather than cut. What
    is not on it is said, by count. The parts every answer carries are bounded on their own."""
    kept, whole = list(listing.chosen), True
    while True:
        answer = _ordered({**out, **_put(listing, kept, whole=whole)})
        if _size(answer) <= MAX_ANSWER_BYTES or not kept:
            return answer
        if whole and not listing.named:
            whole = False       # by headlines first; only then is anything left out
        else:
            kept.pop()


def _put(listing: _Listing, kept: list[int], *, whole: bool) -> dict[str, Any]:
    """The requests part of an answer, as they are said, and what is not on it, by count."""
    shown = sorted(kept, key=lambda n: listing.place[n])
    rows = [listing.rows[n] if whole else _headline(listing.rows[n]) for n in shown]
    part: dict[str, Any] = {"requests": rows}
    left = listing.total - len(rows)
    if listing.named:
        if listing.not_found:
            part["not_found"] = (f"The loop's status has no request with the id {', '.join(listing.not_found)}. "
                                 "Ids are exact; engineering_status without request_ids lists the open ones.")
        if left or listing.asked_more:
            part["not_listed"] = (f"{left + listing.asked_more} of the requests named are not shown: name at most "
                                  f"{MAX_NAMED} at once, fewer when they are long.")
        return part
    if left:
        part.update(_left_out(listing, shown))
    if not whole:
        part["detail"] = "Each request here is its headline: request_ids returns its history and next step."
        if any(row.get("progress") == "blocked" for row in rows):
            part["blocked_means"] = f"For every blocked request: {NEEDS_THE_DIRECTOR} {REFILING_FAILS}"
    return part


def _left_out(listing: _Listing, shown: list[int]) -> dict[str, Any]:
    """What a listing does not name: how many, by state, and the ids of those not done (waiting on
    the owner first, then the newest), as many as MAX_IDS_BYTES holds, so the model can name each one
    in request_ids. A done request is counted only (review N2 of PR #122)."""
    taken = set(shown)
    out_of_it = sorted((n for n in range(len(listing.rows)) if n not in taken), key=lambda n: listing.place[n])
    counts: dict[str, int] = {}
    for n in out_of_it:
        label = str(listing.rows[n].get("progress") or "")
        counts[label] = counts.get(label, 0) + 1
    said = ", ".join(f"{counts[label]} {label}" for label in [*_STATES, *sorted(set(counts) - set(_STATES))]
                     if counts.get(label))
    waiting = [n for n in out_of_it if _waits_on_owner(listing.rows[n])]
    rest = [n for n in out_of_it if n not in set(waiting) and listing.rows[n].get("progress") != "done"]
    ids: list[str] = []
    spent = 2
    for n in waiting + rest:
        rid = str(listing.rows[n].get("request_id") or "")
        spent += _bytes(json.dumps(rid, ensure_ascii=False)) + 2
        if spent > MAX_IDS_BYTES:
            break
        ids.append(rid)
    named = len(waiting) + len(rest)
    left = len(out_of_it)
    line = f"{left} more request{'' if left == 1 else 's'} not listed: {said}."
    if ids and len(ids) == named:
        line += " not_listed_ids names each one not done; name any in request_ids to see it in full."
    elif ids:
        line += (f" not_listed_ids names {len(ids)} of the {named} not done, the owner's first and then the newest; "
                 "name any in request_ids to see it in full.")
    else:
        line += " Name any in request_ids to see it in full."
    return {"not_listed": line, **({"not_listed_ids": ids} if ids else {})}


def _ordered(out: dict[str, Any]) -> dict[str, Any]:
    known = {key: out[key] for key in _ORDER if key in out}
    return {**known, **{key: value for key, value in out.items() if key not in known}}


def _areas(areas: list[str]) -> dict[str, Any]:
    """The areas a build may change, as many as fit in MAX_AREAS_BYTES, and how many more there are."""
    shown: list[str] = []
    spent = 2
    for area in areas:
        spent += _bytes(json.dumps(area, ensure_ascii=False)) + 2
        if spent > MAX_AREAS_BYTES:
            break
        shown.append(area)
    out: dict[str, Any] = {"areas": shown}
    if len(shown) < len(areas):
        out["areas_not_listed"] = (f"{len(areas) - len(shown)} more areas are not listed: a path inside a listed "
                                   "folder may be named, and the loop's own rules judge any other.")
    return out


_QUEUED = frozenset({"", "PROPOSED", "READY"})
_BUILDING = frozenset({"ASSIGNED", "RUNNING"})
_IN_REVIEW = frozenset({"EVIDENCE_READY", "REVIEWING", "ACCEPTED", "DONE"})


def progress(item: dict[str, Any]) -> dict[str, Any]:
    """One request, in the owner's words: queued, building, in review, done, blocked (with the
    loop's reason), or needs the owner. Only the loop's own published fields are read.

    `words` is the headline. `history` says what the build went through, when the loop publishes
    it: how many times it was built and retried, what the review and GitHub asked for, and where it
    is now (the blocker in full, or where it stands with the trunk). `next_step` says whether the
    loop will try again by itself, and when it will not, who it needs and what filing it again would
    do. Nothing the loop does not publish is guessed at, and every word of the loop's is redacted."""
    rid = _words(item.get("request_id"), 80) or "A request"
    stage = str(item.get("stage") or "").upper()
    outcome = str(item.get("outcome") or "")
    reason = _said(item.get("blocker") or item.get("stage_reason") or item.get("reason"))
    row: dict[str, Any] = {"request_id": rid}
    if outcome == "waiting":
        # Filed, seen, and held at the loop's door until the build server has its base: queued.
        refuse_at = _when(item.get("refuse_after"))
        label, words = "queued", (
            f"{rid} is waiting for its base commit to reach the build server; the loop takes it in by itself "
            "as soon as it arrives" + (f", and refuses it if it has not arrived by {refuse_at}" if refuse_at else "")
            + "."
        )
    elif outcome == "refused":
        label, words = "blocked", f"{rid} is blocked: the loop refused it ({reason or 'no reason given'})."
    elif stage == "COMPLETE":
        label, words = "done", f"{rid} is done."
        sha = _sha(item.get("candidate_sha"))
        if sha:
            row["candidate_sha"] = sha
            words = f"{rid} is done: candidate {sha}."
    elif stage == "OWNER_GATE" or item.get("owner_gate") is True:
        label, words = "needs the owner", f"{rid} needs the owner: {reason or 'the loop is waiting for a decision'}."
    elif stage == "BLOCKED":
        label, words = "blocked", f"{rid} is blocked: {reason or 'no reason given'}."
    elif stage in _QUEUED:
        label, words = "queued", f"{rid} is queued; no builder has started it yet."
    elif stage in _BUILDING:
        label, words = "building", f"{rid} is being built."
    elif stage == "REJECTED":
        label, words = "building", f"{rid} is being built again: the review sent it back."
    elif stage in _IN_REVIEW:
        label, words = "in review", f"{rid} is in review."
        verdict = _last_verdict(item.get("review"))
        if verdict:
            words = f"{rid} is in review; the last verdict was {verdict}."
    else:
        label, words = "blocked", f"{rid} is blocked: the loop reports it as {stage.lower() or 'unknown'}" + (f" ({reason})." if reason else ".")
    row.update(progress=label, words=words)
    story = _Story(item, stage=stage, outcome=outcome, label=label)
    history = story.history()
    if history:
        row["history"] = history
    after = story.next_step()
    if after:
        row["next_step"] = after
    return row


# What the owner is told when the loop will not go on by itself. The re-filing sentence is the one
# that was missing on 30 Sep, when blocked builds were filed again and each failed the same way.
NEEDS_THE_DIRECTOR = "The loop will not try again by itself: a blocked build needs the Director."
REFILING_FAILS = "Filing the same request again will fail the same way unless the cause is different."


class _Story:
    """One build as the loop published it: from its own records (``build_history``, any loop) and
    from its Dispatcher (``attempts``, ``repairs``, ``generated``, ``landing``, once the loop has them)."""

    def __init__(self, item: dict[str, Any], *, stage: str, outcome: str, label: str) -> None:
        self.item, self.stage, self.outcome, self.label = item, stage, outcome, label
        record = item.get("build_history")
        self.record = record if isinstance(record, dict) else {}
        attempts = item.get("attempts")
        self.attempts = [a for a in attempts if isinstance(a, dict)] if isinstance(attempts, list) else None
        repairs = item.get("repairs")
        self.repairs = repairs if isinstance(repairs, dict) else None
        landing = item.get("landing")
        self.landing = landing if isinstance(landing, dict) and landing.get("state") in _LANDING else None
        generated = item.get("generated")
        self.generated = [p for p in generated if isinstance(p, str) and p.strip()] if isinstance(generated, list) else []

    # -- counts ---------------------------------------------------------------------------------

    def built(self) -> int | None:
        total = _count(self.record.get("attempts"))
        if total is None and self.attempts is not None:
            total = len(self.attempts)
        return total

    def revisions(self) -> list[dict[str, int]]:
        """Attempts per revision, and how the failed ones ended: from the records, else the Dispatcher."""
        listed = self.record.get("revisions")
        if isinstance(listed, list) and listed:
            return [{"attempts": _count(r.get("attempts")) or 0, "transient": _count(r.get("transient")) or 0,
                     "refused": _count(r.get("refused")) or 0, "cancelled": 0, "repair": r.get("kind") == "repair"}
                    for r in listed if isinstance(r, dict)]
        grouped: dict[Any, dict[str, int]] = {}
        for attempt in self.attempts or ():
            row = grouped.setdefault(attempt.get("revision"), {"attempts": 0, "transient": 0, "refused": 0,
                                                               "cancelled": 0, "repair": False})
            row["attempts"] += 1
            if attempt.get("outcome") in ("cancelled", "refused"):
                row[attempt["outcome"]] += 1
        return list(grouped.values())

    def review_changes(self) -> int | None:
        if self.repairs is not None and _count(self.repairs.get("review")) is not None:
            return _count(self.repairs.get("review"))
        return _count(self.record.get("review_changes_requested"))

    def github_repairs(self) -> int | None:
        return _count(self.repairs.get("ci")) if self.repairs is not None else None

    def repair_rounds(self) -> tuple[int | None, int | None]:
        """(used, limit): the Dispatcher's count when it reports one, else the records' repair revisions."""
        if self.repairs is not None:
            review, ci = _count(self.repairs.get("review")), _count(self.repairs.get("ci"))
            used = review + ci if review is not None and ci is not None else None
            return used, _count(self.repairs.get("max"))
        if not self.record:
            return None, None
        return sum(1 for r in self.revisions() if r["repair"]), _count(self.record.get("max_repair_rounds"))

    # -- words ----------------------------------------------------------------------------------

    def history(self) -> str:
        if self.outcome in ("waiting", "refused"):
            return ""
        if not (self.record or self.attempts is not None or self.repairs is not None or self.landing or self.generated):
            return ""   # the loop published nothing beyond the headline: nothing is guessed
        clauses: list[str] = []
        built = self.built()
        if built:
            clauses.append(f"built {_times(built)}")
        revisions = self.revisions()
        retries = sum(max(0, r["attempts"] - 1) for r in revisions)
        if retries:
            ends = [(sum(r[key] for r in revisions), one, many) for key, one, many in (
                ("transient", "transient failure", "transient failures"),
                ("refused", "result refused by CLIVE's checks", "results refused by CLIVE's checks"),
                ("cancelled", "attempt cancelled", "attempts cancelled"))]
            said = [f"{n} {one if n == 1 else many}" for n, one, many in ends if n]
            clauses.append(f"the loop retried it by itself {_times(retries)}" + (f" ({', '.join(said)})" if said else ""))
        review = self.review_changes()
        if review:
            clauses.append(f"the review asked for changes {_times(review)}")
        red = self.github_repairs()
        if red:
            clauses.append(f"GitHub's tests failed {_times(red)}")
        if self.generated:
            named = ", ".join(_said(p, 120) for p in self.generated[:MAX_GENERATED_NAMED])
            more = len(self.generated) - MAX_GENERATED_NAMED
            clauses.append(f"the loop regenerated {named}{f' and {more} more' if more > 0 else ''} itself")
        now = self.now()
        if now:
            clauses.append(now)
        return _words(_sentence("; ".join(clauses)), MAX_HISTORY_CHARS)

    def now(self) -> str:
        """Where the build is now, in the loop's words: the blocker in full, the trunk, or the stage."""
        blocker = _said(self.item.get("blocker"), MAX_BLOCKER_CHARS)
        if self.stage == "OWNER_GATE" or self.item.get("owner_gate") is True:
            return "waiting for the owner" + (f": {blocker}" if blocker else "")
        if self.stage == "BLOCKED":
            used, _limit = self.repair_rounds()
            after = f" after {used} repair round{'' if used == 1 else 's'}" if used else ""
            return f"blocked{after}" + (f": {blocker}" if blocker else "")
        if self.landing is not None:
            state, why = self.landing["state"], _said(self.landing.get("reason"))
            if state == "landed":
                sha = _sha(self.landing.get("sha"))
                where = "on the trunk" + (f" as {sha[:7]}" if sha else "")
                by = self.landing.get("by")
                if by == "other":
                    return f"{where}, put there by someone other than the loop"
                if by == "unconfirmed":
                    return f"{where}; the loop began pushing it, but cannot tell whether its push or someone else's put it there"
                return f"landed {where}"
            if state == "waiting":
                return "now waiting to land on the trunk" + (f": {why}" if why else "")
            if state == "refreshing":
                return "now being brought up to date with the trunk before it lands"
            if state == "refused":
                return "the loop would not land it on the trunk" + (f": {why}" if why else "")
            if state == "off":
                return "landing is switched off on the loop, so the owner merges it into the trunk"
        gate = self.item.get("github_acceptance")
        green = isinstance(gate, dict) and gate.get("state") == "green"
        if self.stage in _QUEUED:
            return "now waiting for a builder" if self.built() else ""
        if self.stage in _BUILDING:
            return "now building"
        if self.stage == "REJECTED":
            return "now going back to be repaired"
        if self.stage == "EVIDENCE_READY":
            return "now waiting for the reviewer" if green else "now waiting for GitHub"
        if self.stage == "REVIEWING":
            return "now in review"
        if self.stage == "ACCEPTED":
            return "accepted, now being merged into its branch" if green else "accepted, now waiting for GitHub"
        return ""

    def next_step(self) -> str:
        """Whether the loop will try again by itself; when it will not, who it needs and what filing
        the same request again would do."""
        if self.outcome == "waiting":
            return "Nothing needs filing again: the loop takes it in by itself once the build server has its base commit."
        if self.outcome == "refused":
            return ("The loop will not build it: it refused the request itself. Filing the same request again will "
                    "be refused the same way; a new request that fixes what the reason names can be filed.")
        if self.label == "needs the owner":
            return "The loop will not go on by itself: it needs the owner's decision."
        if self.label == "blocked":
            return f"{NEEDS_THE_DIRECTOR} {REFILING_FAILS}"
        if self.landing is not None and self.landing["state"] == "refused":
            return f"The loop will not land it by itself: it needs the Director. {REFILING_FAILS}"
        if self.label == "done":
            if self.landing is not None and self.landing["state"] in ("waiting", "refreshing"):
                return "The loop lands it on the trunk by itself; nothing needs filing again."
            return ""
        failing = "CLIVE's checks, GitHub's tests or the review" if self.github_repairs() is not None else \
            "CLIVE's checks or the review"
        used, limit = self.repair_rounds()
        if used is not None and limit is not None:
            left = max(0, limit - used)
            if left:
                return (f"The loop will try again by itself if {failing} fail: {left} repair round"
                        f"{'' if left == 1 else 's'} left. Nothing needs filing again.")
            return ("The loop still retries a failed attempt by itself, but no repair rounds are left: if the review "
                    "or GitHub fails it again, it blocks and needs the Director.")
        return f"The loop tries again by itself if {failing} fail, up to its limit; nothing needs filing again."


_LANDING = frozenset({"off", "waiting", "landed", "refused", "refreshing"})


def _times(n: int) -> str:
    return {1: "once", 2: "twice"}.get(n, f"{n} times")


def _sentence(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else f"{text}."


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10_000 else None


def _when(value: Any) -> str:
    """An ISO-8601 time the loop published, as the owner reads it: "2026-09-30 14:05 UTC"."""
    if not isinstance(value, str) or len(value) > 64:
        return ""
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return ""
    if stamp.tzinfo is None:
        return ""
    return stamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def _last_verdict(review: Any) -> str:
    verdicts = review.get("verdicts") if isinstance(review, dict) else None
    if not isinstance(verdicts, list) or not verdicts or not isinstance(verdicts[-1], dict):
        return ""
    return _words(verdicts[-1].get("verdict"), 40)


def _sha(value: Any) -> str:
    text = str(value or "")
    return text if len(text) == 40 and all(c in "0123456789abcdef" for c in text) else ""


def _words(value: Any, limit: int = MAX_REASON_CHARS) -> str:
    """One line of at most ``limit`` characters, the "..." that marks a cut included."""
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


# A URL's user part: git names the remote it failed to reach, and that name can carry a credential.
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^/\s@]*@")


def _said(value: Any, limit: int = MAX_REASON_CHARS) -> str:
    """The loop's own words, as CLIVE may repeat them: secrets (the builders' rules) and customer shapes
    (the app's log rules) redacted before the cut, so a cut can never leave half a secret unrecognised.
    The loop redacts what it publishes; this holds for a status written by any loop, old or new."""
    text = str(value or "") if isinstance(value, (str, int, float)) else ""
    if len(text) > 8 * limit:
        head = text[: 8 * limit]
        cut = max(head.rfind(" "), head.rfind("\n"), head.rfind("\t"))
        text = head[:cut] if cut > 0 else ""
    return _words(redact_text(_redact_secrets(_URL_USERINFO.sub(r"\1[redacted]@", text))), limit)


# ------------------------------------------------------------------ the write


async def _observe(execution: dict) -> Observed:
    """The inbox as it is now: its head, whether the request file is there, and whether what
    is there is byte for byte the request that was authorised."""
    inbox = _client()
    try:
        head = await inbox.inbox_head()
        if isinstance(head, NotConnected):
            raise ToolError(head.reason)
        found = await inbox.request_file(str(execution["request_id"]))
        if isinstance(found, NotConnected):
            raise ToolError(found.reason)
    except GitHubError as exc:
        raise ToolError(str(exc)) from None
    expected = str(execution["content"]).encode("utf-8")
    return Observed(fingerprint={
        "head": head.sha or "", "present": found.exists, "matches": found.exists and found.content == expected,
    })


async def _execute(execution: dict) -> dict:
    """The one write: requests/<id>.json, created, never overwritten."""
    from app.actions.engine import PreconditionFailed

    inbox = _client()
    try:
        outcome = await inbox.create_request(str(execution["request_id"]), str(execution["content"]).encode("utf-8"))
    except GitHubError as exc:
        raise ToolError(str(exc)) from None
    if isinstance(outcome, NotConnected):
        raise ToolError(outcome.reason)
    if isinstance(outcome, Refused):
        # Nothing was written: the file was already there, or GitHub refused the create.
        raise PreconditionFailed(outcome.reason)
    _link(execution)
    record = _gaps()
    if record is not None:
        record.filed(str(execution["request_id"]))
    return {"commit_id": outcome.commit_sha}


def _gaps():
    from app.objectives import gaps

    return gaps.ledger()


def _link(execution: dict) -> None:
    """The request is filed: put it on its objective. The filing stands whatever happens here,
    so a failure is logged and never raised (the owner's card still says what was filed)."""
    objective_id = str(execution.get("objective_id") or "")
    if not objective_id:
        return
    from app.objectives.store import store

    try:
        store().link_engineering(
            objective_id, request_id=str(execution["request_id"]), host=str(execution.get("host") or ""),
            target_branch=str(execution.get("target_branch") or target_branch(str(execution["request_id"]))),
        )
    except Exception:  # noqa: BLE001 - the write is done; the link is bookkeeping
        log.warning("engineering request %s filed but not linked to objective %s",
                    execution.get("request_id"), objective_id, exc_info=True)


def _verify(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    return bool(observed.get("present") and observed.get("matches")), ""


def _present(proposal) -> dict:
    s = proposal.summary
    paths = ", ".join(s.get("paths") or ()) or "nothing"
    checks = "; ".join(s.get("checks") or ()) or "none"
    facts = [
        {"label": "Title", "value": str(s.get("title") or "")},
        {"label": "May change", "value": paths},
        {"label": "Checks", "value": checks},
        {"label": "Base", "value": str(s.get("base") or "")},
        {"label": "Acceptance", "value": f"{s.get('criteria', 0)} criteria"},
        {"label": "Repair rounds", "value": "The build server's default" if s.get("repair_rounds") is None
         else str(s.get("repair_rounds"))},
        {"label": "Filed as", "value": f"{s.get('path', '')} on {s.get('branch') or INBOX_BRANCH}"},
    ]
    return {
        "title": "File an engineering request",
        "summary": (
            f"{s.get('title', '')}. It may change {paths}. The loop starts from {s.get('base', '')} "
            f"and runs these checks: {checks}."
        ),
        "detail": "Filing cannot be undone: the loop reads the request, and its id is used once.",
        "facts": facts,
        "target": "File the request",
        "done_title": "Filed",
    }


@tool(
    name=SUBMIT_TOOL,
    description=(
        "Prepare a build of CLIVE itself for the engineering loop's builders; the owner approves "
        "filing it. Call engineering_status (areas true) first and pass its inbox id. The base "
        "and the checks are CLIVE's own, never chosen here."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "inbox_id": {"type": "string"},
            "title": {"type": "string", "maxLength": 200},
            "requested_outcome": {"type": "string", "maxLength": 20000, "description": "What the owner wants, in his words."},
            "allowed_paths": {"type": "array", "items": {"type": "string"}, "description": "From the areas, plus test files."},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}, "description": "Checkable by a reviewer."},
            "objective_id": {"type": "string"},
            "request_id": {"type": "string", "maxLength": 80},
            "max_repair_rounds": {"type": "integer", "minimum": 0, "maximum": 5},
        },
        "required": ["inbox_id", "title", "requested_outcome", "allowed_paths"],
    },
    tier=Tier.RED,
    issued_id_args=("inbox_id",),
    write=WriteSpec(
        operation=OPERATION,
        entity_kind="engineering request",
        entity_arg="inbox_id",
        mutation="github:contents_create",
        observe=_observe,
        execute=_execute,
        present=_present,
        verify=_verify,
        interaction="tap_commit",
        op_class="irreversible",
        reversible=False,
        spoken_success="Filed {label} with the engineering loop.",
        spoken_failure="I couldn't confirm the request was filed. Check engineering status before asking again.",
        spoken_stale="The engineering inbox changed since this was prepared, so nothing was filed.",
    ),
)
async def submit_engineering_request(
    inbox_id: str,
    title: str,
    requested_outcome: str,
    allowed_paths: list[str],
    acceptance_criteria: list[str] | None = None,
    objective_id: str | None = None,
    request_id: str | None = None,
    max_repair_rounds: int | None = None,
) -> Prepared:
    """Prepare, never file: fill in what the model cannot know, build the request, hold it to
    the loop's rules, and read the inbox it will be filed into. The engine is handed the state
    it must see again before it writes.

    The base and the checks are never the caller's (the 2026-09-26 deploy review, F-06): a
    request that could name its own checks would choose the gate it is judged by, and one that
    could name its own base could start from anywhere. The base is the trunk's head, read here;
    the checks are built here, from fixed commands, over the test files the paths name."""
    objective_id = _objective(objective_id)
    # [recording] Nothing a customer said or is called reaches a build request: what is asked for
    # is scrubbed by the timeline's own rule — contact details by shape, and the names this process
    # has been shown — before it is built, so the card he holds shows what will be filed.
    from app.observability.timeline import holds_a_told_name, scrub_text

    if isinstance(requested_outcome, str) and (holds_a_told_name(requested_outcome) or scrub_text(requested_outcome) != requested_outcome):
        requested_outcome = scrub_text(requested_outcome)
    paths = [repo_path(p) for p in allowed_paths] if isinstance(allowed_paths, (list, tuple)) else allowed_paths
    criteria = list(acceptance_criteria or [])

    inbox = _client()
    try:
        head = await inbox.inbox_head()
        if isinstance(head, NotConnected):
            raise ToolError(head.reason)
        if head.sha is None:
            raise ToolError("The engineering inbox branch does not exist yet, so nothing can be filed.")
        if head.sha != inbox_id:
            raise ToolError(
                "The engineering inbox has moved since it was read. Call engineering_status again "
                "and use the inbox id it returns."
            )
        trunk = await inbox.trunk_head()
        if isinstance(trunk, NotConnected):
            raise ToolError(trunk.reason)
        if not trunk.sha:
            raise ToolError(f"{TRUNK_REF} could not be read, so there is nothing to build from.")
        # Named by its SHA: a branch name would stop resolving to it the moment the trunk moves.
        base_sha = trunk.sha
        chosen, existing = await _free_id(inbox, request_id, title)
    except GitHubError as exc:
        raise ToolError(str(exc)) from None
    if existing:
        raise ToolError("A request with that id is already on the engineering inbox. An id is used once: choose a new one.")

    check_list: list[dict] = []
    if isinstance(paths, list):
        paths, check_list, added = default_checks(paths, chosen)
        if added:
            criteria.append(f"The change is proven by tests in {added}, and they pass.")
    try:
        request = build_request(
            request_id=chosen, title=title, requested_outcome=requested_outcome, base_ref=base_sha,
            base_sha=base_sha, allowed_paths=paths, acceptance_criteria=criteria,
            checks=check_list, max_repair_rounds=max_repair_rounds,
        )
    except RequestRefused as exc:
        raise ToolError(str(exc)) from None

    _proposed(request.request_id, objective_id)
    record = request.record
    checks_words = [f"{c['name']}: {' '.join(c['argv'])} (in {c['cwd']})" for c in record["checks"]]
    base = f"{TRUNK_REF} at {record['base_sha'][:12]}" if record["base_ref"] == record["base_sha"] else (
        f"{record['base_ref']} at {record['base_sha'][:12]}")
    return Prepared(
        execution={
            "request_id": request.request_id,
            "path": request.path,
            "head": head.sha,
            "content": request.content.decode("utf-8"),
            "objective_id": objective_id,
            "host": inbox.host,
            "target_branch": record["target_branch"],
        },
        before={"head": head.sha, "present": False, "matches": False},
        expected_after={"present": True, "matches": True},
        entity_ref=request.path,
        entity_label=request.request_id,
        summary={
            "title": record["title"],
            "paths": list(record["allowed_paths"]),
            "checks": checks_words,
            "base": base,
            "criteria": len(record["acceptance_criteria"]),
            # None: the build server's own default, which the owner can raise there (loop upgrade, 7 Oct 2026).
            "repair_rounds": record.get("max_repair_rounds"),
            "path": request.path,
            "branch": inbox.inbox_branch,
            "host": inbox.host,
            "objective_id": objective_id,
            "read_back": f"file {request.request_id} ({record['title']}) with the engineering loop, from {base}",
            "payload_len": len(request.content),
        },
    )


def _proposed(request_id: str, objective_id: str) -> None:
    """CLIVE proposed a build for an objective: the gaps its missing_capability blockers name
    now have a build proposed for them (app/objectives/gaps.py). Filing is the owner's tap."""
    record = _gaps()
    if record is None or not objective_id:
        return
    from app.objectives.store import store

    try:
        record.proposed(request_id, objective_id, store().gap_keys(objective_id))
    except Exception:  # noqa: BLE001 - bookkeeping; the card is what matters
        log.warning("build %s not recorded against its gaps", request_id, exc_info=True)


def _objective(objective_id: str | None) -> str:
    if not objective_id:
        return ""
    from app.objectives.store import ObjectiveError, store

    try:
        return store().get(str(objective_id)).id
    except ObjectiveError:
        raise ToolError("There is no objective with that id: call objective_list and use one it returns.") from None


async def _free_id(inbox: EngineeringInbox, request_id: str | None, title: str) -> tuple[str, bool]:
    """The id to file under, and whether it is taken. An id the model chose is used as given; one
    made from the title steps on to -2, -3 … past any already on the inbox, the loop's own
    convention for a request asked again."""
    if request_id is not None:
        candidates = [str(request_id)]
    else:
        base = _slug(title)
        candidates = [base] + [f"{base}-{n}" for n in range(2, MAX_ID_SUFFIX + 1)]
    for candidate in candidates:
        if not valid_request_id(candidate):
            return candidate, False  # build_request names the id rule
        found = await inbox.request_file(candidate)
        if isinstance(found, NotConnected):
            raise ToolError(found.reason)
        if not found.exists:
            return candidate, False
    return candidates[-1], True


_STOP = frozenset({"a", "an", "the", "to", "of", "for", "and", "on", "in", "with", "so", "it", "can", "that", "be"})


def _slug(title: object) -> str:
    """A request id from a title: its words, lowercase, at most six, each at most 16 letters."""
    words = re.findall(r"[a-z0-9]+", str(title or "").lower())
    while words and not words[0][0].isalpha():
        words.pop(0)
    kept = [w for w in words if w not in _STOP]
    words = kept if len(kept) >= 2 else words
    words = [w[:16] for w in words][:6]
    if not words:
        words = ["clive"]
    if len(words) < 2:
        words.append("build")
    return "-".join(words)


def repo_path(path: object) -> object:
    """A path as the loop takes it, relative to the repository root. "app/recipes.py" and
    "./web/alpha.js" are CLIVE's own folder's; anything else is left for the rules to judge."""
    if not isinstance(path, str):
        return path
    text = path.strip()
    while text.startswith("./"):
        text = text[2:]
    text = text.rstrip("/") if text not in ("", "/") else text
    if text.split("/", 1)[0] in APP_TOP:
        return f"{APP_DIR}/{text}"
    return text


# The only test files a check may name: a pytest module under tests/, by its plain name. They
# go into an argv (no shell), and nothing else a request says reaches a command.
_TEST_FILE = re.compile(rf"^{re.escape(APP_DIR)}/tests/(?:[a-z0-9_]+/)?test_[a-z0-9_]+\.py$")


# Every build is also judged by these, whatever it names and whatever it may change (the
# 2026-09-26 deploy review, F-06): the tests that hold the product's safety core — the gate, the
# read-only guard, the action engine and every write funnel. Each is a protected path, so no
# build can weaken the check it is judged by. About 550 tests, ten seconds. The full suite is
# still the GitHub acceptance run every merge waits for.
REGRESSION_TESTS = (
    "tests/test_gate.py", "tests/test_readonly.py", "tests/test_actions.py", "tests/test_actions_routes.py",
    "tests/test_engine_hooks.py", "tests/test_batch.py", "tests/test_available.py", "tests/test_judgment.py",
    "tests/test_judgment_construction.py", "tests/test_judgment_chain.py", "tests/test_judgment_ledger.py",
    "tests/test_cancel.py", "tests/test_refund.py", "tests/test_address.py", "tests/test_fulfil.py",
    "tests/test_inventory.py", "tests/test_tracking.py", "tests/test_order_edit.py", "tests/test_gmail_writes.py",
    "tests/test_compose.py",
)


def default_checks(paths: list, request_id: str, *, python: str | None = None) -> tuple[list, list[dict], str]:
    """Every request's checks, built here and never taken from the request: pytest over the
    test modules the paths name (and the web rules when the phone's files may change), then
    ruff over the whole package, as the builders run them. With no test module named, one is
    added to the paths for the build to write; its check fails until it exists."""
    python = python or _check_python
    prefix = f"{APP_DIR}/tests/"
    tests = [p[len(APP_DIR) + 1:] for p in paths if isinstance(p, str) and _TEST_FILE.fullmatch(p)]
    added = ""
    if not tests:
        name = "test_" + re.sub(r"[^a-z0-9]+", "_", str(request_id).lower()).strip("_")[:60] + ".py"
        added = f"{prefix}{name}"
        paths = [*paths, added]
        tests = [f"tests/{name}"]
    if any(isinstance(p, str) and p.startswith(f"{APP_DIR}/web") for p in paths) and "tests/test_web.py" not in tests:
        tests.append("tests/test_web.py")
    regression = [t for t in REGRESSION_TESTS if (APP_ROOT / t).is_file() and t not in tests]
    checks = [
        {"name": "tests", "argv": [python, "-m", "pytest", "-q", *tests], "cwd": APP_DIR},
        {"name": "regression", "argv": [python, "-m", "pytest", "-q", "-m", "not live", *regression], "cwd": APP_DIR},
        {"name": "ruff", "argv": [python, *RUFF_ARGS], "cwd": APP_DIR},
    ]
    return paths, checks, added


_SKIP_DIRS = frozenset({"__pycache__", "node_modules", ".venv", "logs", ".state", ".cache", "screens"})
_AREA_FILES = frozenset({".py", ".js", ".css", ".html", ".md", ".json", ".txt", ".yaml", ".yml"})
_AREA_TOPS = ("app", "web", "kb", "docs", "config")


def buildable_areas(root: Path | None = None) -> list[str]:
    """The widest parts of CLIVE a build may change: each folder that holds nothing the loop
    protects, and inside a folder that does, its unprotected files and folders. Read from the
    checkout, so it is the code as deployed; the builders start from the trunk."""
    root = root or APP_ROOT
    out: list[str] = []

    def walk(rel: str, depth: int) -> None:
        if len(out) >= MAX_AREAS:
            return
        full = f"{APP_DIR}/{rel}"
        if not protected_paths_in([full]):
            out.append(full)
            return
        here = root / rel
        if depth >= 3 or not here.is_dir():
            return
        for child in sorted(here.iterdir()):
            if child.name.startswith(".") or child.name in _SKIP_DIRS:
                continue
            if child.is_file() and child.suffix not in _AREA_FILES:
                continue
            walk(f"{rel}/{child.name}", depth + 1)

    for top in _AREA_TOPS:
        if (root / top).exists():
            walk(top, 0)
    return out


# ------------------------------------------------------------------ progress for the owner's screen

PROGRESS_TTL_S = 60.0
_progress_cache: dict[str, Any] = {}


def _remember(status: LoopStatus, *, items: list[dict] | None = None, rows: list[dict] | None = None) -> None:
    """The status read and each request's line, kept for the owner's screens; `items` and `rows` when
    the caller has made them already, so a long status is not said twice."""
    rows = _rows(status) if items is None or rows is None else {
        str(item.get("request_id")): row for item, row in zip(items, rows, strict=True) if item.get("request_id")}
    # `status` is the loop's published status itself, for the owner's Builds screen (app/builds/read.py).
    _progress_cache.update(at=time.monotonic(), rows=rows, status=status)
    record = _gaps()
    if record is not None:
        record.progressed(rows)


def _rows(status: LoopStatus) -> dict[str, dict]:
    data = status.data if status.published else {}
    return {str(item.get("request_id")): progress(item) for item in _items(data) if item.get("request_id")}


async def _fresh() -> str:
    """The loop's status read again if the last read is a minute old: "" when it is in hand, else
    why it is not (GitHub not connected, or not answering)."""
    fresh = _progress_cache.get("at") is not None and time.monotonic() - _progress_cache["at"] < PROGRESS_TTL_S
    if fresh:
        return ""
    try:
        status = await _client().status()
    except GitHubError as exc:
        log.info("engineering status unreadable for build progress", exc_info=True)
        return str(exc)
    if isinstance(status, NotConnected):
        return status.reason
    _remember(status)
    return ""


async def loop_status() -> tuple[LoopStatus | None, str]:
    """The loop's published status, read at most once a minute, and why not when it cannot be read.
    The last status read stays in hand while GitHub is away, with what stopped a fresh read."""
    problem = await _fresh()
    return _progress_cache.get("status"), problem


async def build_progress(request_ids: list[str]) -> dict[str, dict]:
    """Where each named request is, from the loop's status read at most once a minute. A request
    the loop has not picked up yet is queued; with GitHub unreachable, nothing is said."""
    wanted = [r for r in dict.fromkeys(request_ids) if isinstance(r, str) and r]
    if not wanted:
        return {}
    if await _fresh():
        return {}
    rows = _progress_cache.get("rows") or {}
    out = {}
    for rid in wanted:
        out[rid] = rows.get(rid) or {"request_id": rid, "progress": "queued",
                                     "words": f"{rid} is filed; the loop has not picked it up yet."}
    return out


MAX_MERGE_CHECKS = 5


async def refresh_gaps() -> None:
    """Bring the gap record's builds up to date: the loop's progress (read at most once a
    minute, by build_progress) and, for builds the loop finished, whether their candidate is
    on the trunk yet (at most once a minute, a few at a time). GitHub unreachable: unchanged."""
    record = _gaps()
    if record is None:
        return
    ids = list(record.load()["builds"])
    if ids:
        await build_progress(ids)
    last = _progress_cache.get("merge_checked_at")
    if last is not None and time.monotonic() - last < PROGRESS_TTL_S:
        return
    _progress_cache["merge_checked_at"] = time.monotonic()
    running = running_sha()
    checks = [(rid, sha, TRUNK_REF, record.merged) for rid, sha in record.unmerged_builds()]
    if running:
        checks += [(rid, sha, running, record.live) for rid, sha in record.unlive_builds()]
    for request_id, sha, ref, mark in checks[:MAX_MERGE_CHECKS]:
        try:
            on = await _client().on_trunk(sha, ref)
        except GitHubError:
            log.info("could not compare build %s with %s", request_id, ref, exc_info=True)
            return
        if isinstance(on, NotConnected):
            return
        if on:
            mark(request_id)


_HEX40 = re.compile(r"^[0-9a-f]{40}$")


def running_sha(root: Path | None = None) -> str:
    """The commit this CLIVE runs, read from its checkout's own git files (no git command):
    how a merged fix is known to be live. Empty when it cannot be told."""
    git = (root or APP_ROOT.parent) / ".git"
    try:
        head = (git / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            ref = head[5:].strip()
            path = git / ref
            if path.is_file():
                head = path.read_text(encoding="utf-8").strip()
            else:
                packed = (git / "packed-refs").read_text(encoding="utf-8").splitlines()
                head = next((line.split(" ", 1)[0] for line in packed if line.endswith(" " + ref)), "")
    except OSError:
        return ""
    return head if _HEX40.fullmatch(head) else ""
