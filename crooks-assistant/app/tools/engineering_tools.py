"""Engineering objectives, filed from CLIVE into the remote engineering loop.

Two tools. `engineering_status` reads the status the loop publishes and says where each request
is, in plain words. It also reads the inbox branch's head commit and returns it as the inbox's
`id`, which the dispatcher issues to the conversation exactly as it issues any id a read
returns (app/tools/dispatch.py `_harvest_ids`).

`submit_engineering_request` is a write, and it acts on that issued inbox id: the gate's
existing issued-id rule is what stages it for the owner (app/tools/gate.py). Its handler only
prepares — builds the request, holds it to the loop's own intake rules
(app/engineering_bridge/requests.py) and reads the inbox. Nothing is filed until the owner
authorises the card; then the action engine re-reads the inbox head and confirms the file is
still absent, creates it, and proves it by reading the file back and comparing the bytes.

With no token in the secret store both tools say GitHub is not connected, and nothing is sent.
"""

from __future__ import annotations

from typing import Any

from app.actions.models import Observed, Prepared
from app.capabilities.families import CapabilityFamily, register
from app.engineering_bridge.github import (
    INBOX_BRANCH,
    EngineeringInbox,
    GitHubError,
    InboxHead,
    LoopStatus,
    NotConnected,
    Refused,
)
from app.engineering_bridge.requests import RequestRefused, build_request
from app.tools.gate import Tier
from app.tools.registry import ToolError, WriteSpec, tool

STATUS_TOOL = "engineering_status"
SUBMIT_TOOL = "submit_engineering_request"
OPERATION = "engineering_request_file"

# How much of the loop's own words a line repeats. Every request is listed: none is dropped.
MAX_REASON_CHARS = 300

_inbox: EngineeringInbox | None = None


def bind(inbox: EngineeringInbox) -> None:
    """The client the tools use. The runtime binds one at start-up; a test binds a fake."""
    global _inbox
    _inbox = inbox


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
        "that submit_engineering_request takes."
    ),
    input_schema={"type": "object", "properties": {}},
    tier=Tier.GREEN,
)
async def engineering_status() -> dict:
    inbox = _client()
    try:
        status = await inbox.status()
        if isinstance(status, NotConnected):
            return _not_connected(status)
        head = await inbox.inbox_head()
    except GitHubError as exc:
        raise ToolError(str(exc)) from None
    if isinstance(head, NotConnected):
        return _not_connected(head)
    return project(status, head)


def _not_connected(result: NotConnected) -> dict:
    return {"connected": False, "summary": result.reason, "requests": []}


def project(status: LoopStatus, head: InboxHead) -> dict[str, Any]:
    """The loop's status.json, one line per request in plain words, and the inbox's id."""
    data = status.data if status.published else {}
    requests = data.get("requests")
    items = [item for item in requests if isinstance(item, dict)] if isinstance(requests, list) else []
    rows = [progress(item) for item in items]
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
        summary += f" The loop could not read its inbox last time: {_words(adapter['intake_error'])}."
    out: dict[str, Any] = {"connected": True, "summary": summary, "requests": rows}
    if isinstance(data.get("generated_at"), str):
        out["as_of"] = data["generated_at"][:40]
    if head.sha:
        # `id` is the key the dispatcher issues from; this is the inbox the owner may file into.
        out["inbox"] = {"id": head.sha, "branch": INBOX_BRANCH}
    else:
        out["summary"] += " The inbox branch does not exist yet, so nothing can be filed."
    return out


_QUEUED = frozenset({"", "PROPOSED", "READY"})
_BUILDING = frozenset({"ASSIGNED", "RUNNING"})
_IN_REVIEW = frozenset({"EVIDENCE_READY", "REVIEWING", "ACCEPTED", "DONE"})


def progress(item: dict[str, Any]) -> dict[str, Any]:
    """One request, in the owner's words: queued, building, in review, done, blocked (with the
    loop's reason), or needs the owner. Only the loop's own published fields are read."""
    rid = _words(item.get("request_id"), 80) or "A request"
    stage = str(item.get("stage") or "").upper()
    reason = _words(item.get("blocker") or item.get("stage_reason") or item.get("reason"))
    row: dict[str, Any] = {"request_id": rid}
    if str(item.get("outcome") or "") == "refused":
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
    return row


def _last_verdict(review: Any) -> str:
    verdicts = review.get("verdicts") if isinstance(review, dict) else None
    if not isinstance(verdicts, list) or not verdicts or not isinstance(verdicts[-1], dict):
        return ""
    return _words(verdicts[-1].get("verdict"), 40)


def _sha(value: Any) -> str:
    text = str(value or "")
    return text if len(text) == 40 and all(c in "0123456789abcdef" for c in text) else ""


def _words(value: Any, limit: int = MAX_REASON_CHARS) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


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
    return {"commit_id": outcome.commit_sha}


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
        {"label": "Repair rounds", "value": str(s.get("repair_rounds", 0))},
        {"label": "Filed as", "value": f"{s.get('path', '')} on {INBOX_BRANCH}"},
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
        "Prepare one engineering objective for the remote engineering loop; the owner approves "
        "filing it in CLIVE. Call engineering_status first and pass its inbox id. "
        "request_id: lowercase words joined by hyphens."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "inbox_id": {"type": "string", "description": "The inbox id from engineering_status."},
            "request_id": {"type": "string", "maxLength": 80},
            "title": {"type": "string", "maxLength": 200},
            "requested_outcome": {"type": "string", "maxLength": 20000},
            "base_ref": {"type": "string", "maxLength": 200},
            "base_sha": {"type": "string", "maxLength": 40},
            "allowed_paths": {"type": "array", "items": {"type": "string"}},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            "checks": {"type": "array", "items": {"type": "object"}, "description": "Each: name, argv, cwd."},
            "max_repair_rounds": {"type": "integer", "minimum": 0, "maximum": 5},
        },
        "required": ["inbox_id", "request_id", "title", "requested_outcome", "base_ref", "base_sha", "allowed_paths"],
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
    request_id: str,
    title: str,
    requested_outcome: str,
    base_ref: str,
    base_sha: str,
    allowed_paths: list[str],
    acceptance_criteria: list[str] | None = None,
    checks: list[dict] | None = None,
    max_repair_rounds: int = 2,
) -> Prepared:
    """Prepare, never file: build the request, hold it to the loop's rules, and read the inbox
    it will be filed into. The engine is handed the state it must see again before it writes."""
    try:
        request = build_request(
            request_id=request_id, title=title, requested_outcome=requested_outcome, base_ref=base_ref,
            base_sha=base_sha, allowed_paths=allowed_paths, acceptance_criteria=acceptance_criteria or [],
            checks=checks or [], max_repair_rounds=max_repair_rounds,
        )
    except RequestRefused as exc:
        raise ToolError(str(exc)) from None
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
        existing = await inbox.request_file(request.request_id)
        if isinstance(existing, NotConnected):
            raise ToolError(existing.reason)
    except GitHubError as exc:
        raise ToolError(str(exc)) from None
    if existing.exists:
        raise ToolError("A request with that id is already on the engineering inbox. An id is used once: choose a new one.")

    record = request.record
    checks_words = [f"{c['name']}: {' '.join(c['argv'])} (in {c['cwd']})" for c in record["checks"]]
    base = f"{record['base_ref']} at {record['base_sha'][:12]}"
    return Prepared(
        execution={
            "request_id": request.request_id,
            "path": request.path,
            "head": head.sha,
            "content": request.content.decode("utf-8"),
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
            "repair_rounds": record["max_repair_rounds"],
            "path": request.path,
            "read_back": f"file {request.request_id} ({record['title']}) with the engineering loop, from {base}",
            "payload_len": len(request.content),
        },
    )
