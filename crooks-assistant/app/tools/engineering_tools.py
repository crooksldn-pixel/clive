"""The remote engineering loop, as two tools: where CLIVE's engineering requests stand, and
filing a new one (app/engineering_bridge).

engineering_status is a read. It projects the loop's published status.json into plain words
per request — queued, building, in review, done, blocked and why, needs the owner — and it
returns the inbox branch's head commit as `inbox.id`. The dispatcher issues that id to the
conversation exactly as it issues any id a read exposes (app/tools/dispatch.py), and
submit_engineering_request takes it as the entity it acts on. So the gate's issued-id rule
stages a submission for the owner the same way it stages a change to an order, unchanged: no
id read this conversation, no submission.

submit_engineering_request is a write, and its handler sends nothing. It builds and validates
the request by the loop's own rules, confirms the inbox has not moved and the file is absent,
and prepares a card that says in plain words what will be filed. The owner's tap files it
(app/actions/engine.py): `observe` re-reads the inbox head and confirms the file is still
absent, `execute` creates it — only when absent, never overwriting — and `verify` re-reads
the file and compares its bytes with the bytes prepared.

The GitHub token never reaches this module: the client reads it per call and returns typed
results whose words carry no header, body or credential.
"""

from __future__ import annotations

import hashlib
from typing import Any

from app.actions.models import Observed, Prepared
from app.engineering_bridge.github import (
    Created,
    GitHubInbox,
    InboxHead,
    NotConnected,
    Refused,
    RequestFile,
    Status,
)
from app.engineering_bridge.requests import (
    DEFAULT_REPAIR_ROUNDS,
    MAX_OUTCOME,
    MAX_REPAIR_ROUNDS,
    MAX_TITLE,
    EngineeringRequest,
    RequestRefused,
    build_request,
)
from app.tools.gate import Tier
from app.tools.registry import ToolError, WriteSpec, tool

_client: GitHubInbox | None = None


def bind(client: GitHubInbox) -> None:
    global _client
    _client = client


def _c() -> GitHubInbox:
    """The bound client; unbound, one over the default repository — which, with no token
    stored, answers every call with NotConnected and makes none."""
    global _client
    if _client is None:
        _client = GitHubInbox()
    return _client


# ------------------------------------------------------------------ status, in plain words

# The loop's stages (app/orchestrator/lifecycle.py lifecycle_view), in the owner's words. A
# rejected revision is being repaired; an accepted one is waiting to be integrated.
_PROGRESS = {
    "PROPOSED": "queued", "READY": "queued",
    "ASSIGNED": "building", "RUNNING": "building", "EVIDENCE_READY": "building", "REJECTED": "building",
    "REVIEWING": "in review", "ACCEPTED": "in review",
    "COMPLETE": "done",
    "OWNER_GATE": "needs the owner",
    "BLOCKED": "blocked", "OBSOLETE": "blocked", "CANCELLED": "blocked", "UNKNOWN": "blocked",
}
# The most recent requests are the ones worth saying; the status keeps every one.
MAX_REPORTED = 25


def progress_of(item: dict[str, Any]) -> dict[str, Any]:
    """One request from status.json, as the owner hears it."""
    rid = _plain(item.get("request_id"), 140) or "an unnamed request"
    if item.get("outcome") == "refused":
        reason = _plain(item.get("reason")) or "no reason was given"
        return {"request_id": rid, "progress": "blocked", "words": f"{rid}: blocked — the loop refused it: {reason}"}
    stage = str(item.get("stage") or "").upper()
    progress = _PROGRESS.get(stage, "blocked" if stage else "queued")
    out: dict[str, Any] = {"request_id": rid, "progress": progress}
    if progress == "done":
        acceptance = item.get("acceptance") if isinstance(item.get("acceptance"), dict) else {}
        sha = _sha(item.get("candidate_sha")) or _sha(acceptance.get("sha"))
        out["candidate_sha"] = sha
        out["words"] = f"{rid}: done — candidate {sha}." if sha else f"{rid}: done."
    elif progress == "blocked":
        reason = _plain(item.get("blocker")) or _plain(item.get("stage_reason")) or f"the loop reports it as {stage.lower()}"
        out["words"] = f"{rid}: blocked — {reason}"
    elif progress == "needs the owner":
        reason = _gate_reason(item.get("owner_gate")) or _plain(item.get("stage_reason")) or "it is waiting for the owner's decision"
        out["words"] = f"{rid}: needs the owner — {reason}"
    elif progress == "in review":
        review = item.get("review") if isinstance(item.get("review"), dict) else {}
        verdicts = review.get("verdicts") if isinstance(review.get("verdicts"), list) else []
        count = len(verdicts)
        out["words"] = f"{rid}: in review" + (f" ({count} verdict{'' if count == 1 else 's'} so far)." if count else ".")
    else:
        out["words"] = f"{rid}: {progress}."
    return out


def _plain(value: object, limit: int = 300) -> str:
    if not isinstance(value, str):
        return ""
    text = " ".join(value.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _sha(value: object) -> str:
    text = value.strip().lower() if isinstance(value, str) else ""
    return text if len(text) == 40 and all(c in "0123456789abcdef" for c in text) else ""


def _gate_reason(value: object) -> str:
    if isinstance(value, dict):
        for key in ("reason", "gate_reason", "question"):
            if _plain(value.get(key)):
                return _plain(value.get(key))
        return ""
    return _plain(value)


@tool(
    name="engineering_status",
    description="Where CLIVE's engineering requests stand, in plain words, and the inbox id submit_engineering_request needs.",
    input_schema={"type": "object", "properties": {}},
    tier=Tier.GREEN,
)
async def engineering_status() -> dict[str, Any]:
    client = _c()
    status = await client.read_status()
    if isinstance(status, NotConnected):
        return {"connected": False, "summary": status.reason}
    head = await client.inbox_head()
    out: dict[str, Any] = {"connected": True, "requests": []}
    lines: list[str] = []
    if not isinstance(status, Status):
        lines.append(status.reason)
    elif not status.found:
        lines.append("The engineering loop has not published a status yet.")
    else:
        document = status.document or {}
        items = document.get("requests") if isinstance(document.get("requests"), list) else []
        items = [item for item in items if isinstance(item, dict)]
        requests = [progress_of(item) for item in items[-MAX_REPORTED:]]
        out["requests"] = requests
        if len(items) > MAX_REPORTED:
            out["earlier_requests"] = len(items) - MAX_REPORTED
        if _plain(document.get("generated_at"), 40):
            out["as_of"] = _plain(document.get("generated_at"), 40)
        adapter = document.get("adapter") if isinstance(document.get("adapter"), dict) else {}
        if _plain(adapter.get("intake_error")):
            lines.append(f"The loop could not read the inbox on its last pass: {_plain(adapter.get('intake_error'))}")
        refused = document.get("refused_records")
        if isinstance(refused, list) and refused:
            lines.append(f"{len(refused)} inbox file{'' if len(refused) == 1 else 's'} could not be read as a request.")
        lines.extend(r["words"] for r in requests)
        if not requests:
            lines.append("No engineering requests have been filed yet.")
    if isinstance(head, InboxHead):
        # An `id` in a read's result is issued to the conversation by the dispatcher; this is
        # the one submit_engineering_request must be handed back.
        out["inbox"] = {"id": head.sha}
    else:
        lines.append(f"{head.reason} A request cannot be submitted until the inbox can be read.")
    out["summary"] = " ".join(lines)
    return out


# ------------------------------------------------------------------ submitting a request


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _words(request: EngineeringRequest) -> dict[str, str]:
    """What will be filed, in plain words, for the card."""
    paths = list(request.allowed_paths)
    may_change = "Only " + ", ".join(paths[:12]) + (f", and {len(paths) - 12} more" if len(paths) > 12 else "")
    checks = "; ".join(
        _plain(f"{c['name']}: runs {' '.join(c['argv'])} in {c['cwd']}", 200) for c in request.checks
    )
    rounds = request.max_repair_rounds
    return {
        "may_change": _plain(may_change, 600),
        "checks": _plain(checks, 600) or "None listed; the loop's review still applies",
        "base": f"{request.base_ref} at commit {request.base_sha}",
        "repairs": f"Up to {rounds} repair round{'' if rounds == 1 else 's'}",
    }


async def _observe_inbox(execution: dict) -> Observed:
    """The inbox head, and whether the request file is there (and a digest of its bytes)."""
    client = _c()
    head = await client.inbox_head()
    if not isinstance(head, InboxHead):
        raise ToolError(head.reason)
    found = await client.request_file(str(execution["request_id"]))
    if not isinstance(found, RequestFile):
        raise ToolError(found.reason)
    return Observed(fingerprint={
        "head": head.sha, "exists": found.exists, "content_sha256": _sha256(found.content) if found.exists else "",
    })


async def _execute_create(execution: dict) -> dict:
    from app.actions.engine import PreconditionFailed

    result = await _c().create_request(str(execution["request_id"]), str(execution["content"]).encode("utf-8"))
    if isinstance(result, Created):
        return {"request_id": result.request_id, "commit_id": result.commit_sha}
    if isinstance(result, (Refused, NotConnected)):
        # Nothing was written: the file was there already, GitHub refused on a conflict, or
        # there was no token to ask with. The engine settles it with nothing applied.
        raise PreconditionFailed(result.reason)
    raise ToolError(result.reason)


def _verify_filed(before: dict, observed: dict, execution: dict) -> tuple[bool, str]:
    """Proven when the file is there and the bytes read back are the bytes prepared."""
    prepared = _sha256(str(execution["content"]).encode("utf-8"))
    return bool(observed.get("exists")) and observed.get("content_sha256") == prepared, ""


def _present_request(proposal) -> dict:
    s = proposal.summary
    return {
        "title": "File an engineering request",
        "summary": str(s.get("title") or ""),
        "detail": "Adds one new request to the engineering inbox for the loop to build. It never replaces a request, and once filed it cannot be taken back from here.",
        "facts": [
            {"label": "Request", "value": str(s.get("request_id") or "")},
            {"label": "May change", "value": str(s.get("may_change") or "")},
            {"label": "Checks", "value": str(s.get("checks") or "")},
            {"label": "Base", "value": str(s.get("base") or "")},
            {"label": "Repairs", "value": str(s.get("repairs") or "")},
        ],
        "done_title": "Filed",
    }


@tool(
    name="submit_engineering_request",
    description="File an engineering request into CLIVE's engineering loop. Prepares a card; nothing is filed until the owner approves it. inbox_id comes from engineering_status.",
    input_schema={
        "type": "object",
        "properties": {
            "inbox_id": {"type": "string"},
            "request_id": {"type": "string", "description": "Lowercase words joined by hyphens."},
            "title": {"type": "string", "minLength": 1, "maxLength": MAX_TITLE},
            "requested_outcome": {"type": "string", "minLength": 1, "maxLength": MAX_OUTCOME},
            "base_ref": {"type": "string"},
            "base_sha": {"type": "string"},
            "allowed_paths": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
            "checks": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "argv": {"type": "array", "items": {"type": "string"}}, "cwd": {"type": "string"}}}},
            "max_repair_rounds": {"type": "integer", "minimum": 0, "maximum": MAX_REPAIR_ROUNDS},
        },
        "required": ["inbox_id", "request_id", "title", "requested_outcome", "base_ref", "base_sha", "allowed_paths"],
    },
    tier=Tier.AMBER,
    issued_id_args=("inbox_id",),
    write=WriteSpec(
        operation="engineering_request_submit", entity_kind="engineering request", entity_arg="inbox_id",
        mutation="github:contents_create",
        observe=_observe_inbox, execute=_execute_create, present=_present_request, verify=_verify_filed,
        interaction="tap_commit", op_class="irreversible",
        spoken_success="Engineering request {label} is filed.",
        spoken_failure="I couldn't confirm the engineering request was filed. Check the engineering status before asking again.",
        spoken_stale="The engineering inbox changed since that was prepared, so I haven't filed it.",
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
    checks: list[dict[str, Any]] | None = None,
    max_repair_rounds: int = DEFAULT_REPAIR_ROUNDS,
) -> Prepared:
    try:
        request = build_request(
            request_id=request_id, title=title, requested_outcome=requested_outcome,
            base_ref=base_ref, base_sha=base_sha, allowed_paths=allowed_paths,
            acceptance_criteria=acceptance_criteria or (), checks=checks or (),
            max_repair_rounds=max_repair_rounds,
        )
    except RequestRefused as exc:
        raise ToolError(f"The request was not prepared: {exc}.") from None
    client = _c()
    head = await client.inbox_head()
    if not isinstance(head, InboxHead):
        raise ToolError(head.reason)
    if head.sha != inbox_id:
        raise ToolError(
            "The engineering inbox has moved on since it was read. Call engineering_status again "
            "and submit with the inbox id it returns."
        )
    found = await client.request_file(request.request_id)
    if not isinstance(found, RequestFile):
        raise ToolError(found.reason)
    if found.exists:
        raise ToolError(f"A request called {request.request_id} is already in the engineering inbox; choose a new request_id.")
    payload = request.to_bytes()
    return Prepared(
        execution={"request_id": request.request_id, "content": payload.decode("utf-8")},
        before={"head": head.sha, "exists": False, "content_sha256": ""},
        expected_after={"exists": True, "content_sha256": _sha256(payload)},
        entity_ref=head.sha,
        entity_label=request.request_id,
        summary={
            "title": request.title, "request_id": request.request_id, **_words(request),
            "read_back": _plain(f"file engineering request {request.request_id}: {request.title}", 200),
            "payload_len": len(payload), "ledger": {"kind": "engineering_request"},
        },
    )
