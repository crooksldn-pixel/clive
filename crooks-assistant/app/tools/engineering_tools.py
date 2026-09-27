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

import logging
import re
import time
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
from app.orchestrator.objectives import protected_paths_in
from app.tools.gate import Tier
from app.tools.registry import ToolError, WriteSpec, tool

log = logging.getLogger("crooks.tools.engineering")

STATUS_TOOL = "engineering_status"
SUBMIT_TOOL = "submit_engineering_request"
OPERATION = "engineering_request_file"

# How much of the loop's own words a line repeats. Every request is listed: none is dropped.
MAX_REASON_CHARS = 300

# The checkout the builders build (this one's parent is the repository root), and the one
# folder of it CLIVE's code lives in: every path a request names is relative to the root.
APP_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = "crooks-assistant"
# Where a path the model gives without the folder ("app/fastpath", "web/alpha.js") belongs.
APP_TOP = ("app", "web", "kb", "docs", "scripts", "config", "tests", "deploy")
# The builders' own interpreter (CROOKS_ENGINEERING_CHECK_PYTHON): checks run on their host,
# never this one, in a sandbox with PATH only.
DEFAULT_CHECK_PYTHON = "/home/user/clive/crooks-assistant/.venv/bin/python"
RUFF_ARGS = ("-m", "ruff", "check", "app", "config", "scripts", "tests")
MAX_AREAS = 160
MAX_ID_SUFFIX = 9

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
        "that submit_engineering_request takes. areas: true lists the parts of CLIVE a build may change."
    ),
    input_schema={"type": "object", "properties": {"areas": {"type": "boolean"}}},
    tier=Tier.GREEN,
)
async def engineering_status(areas: bool = False) -> dict:
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
    _remember(status)
    out = project(status, head, branch=inbox.inbox_branch)
    out["host"] = inbox.host
    if isinstance(trunk, InboxHead) and trunk.sha:
        out["base"] = {"ref": TRUNK_REF, "sha": trunk.sha}
    if areas:
        out["areas"] = buildable_areas()
        out["tests"] = (
            f"Tests are files under {APP_DIR}/tests/: name the ones the build should add or change "
            f"(for example {APP_DIR}/tests/test_<topic>.py). With none named, one is added for it."
        )
    return out


def _not_connected(result: NotConnected) -> dict:
    return {"connected": False, "summary": result.reason, "requests": []}


def project(status: LoopStatus, head: InboxHead, *, branch: str = INBOX_BRANCH) -> dict[str, Any]:
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
        out["inbox"] = {"id": head.sha, "branch": branch}
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
        {"label": "Repair rounds", "value": str(s.get("repair_rounds", 0))},
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
    max_repair_rounds: int = 2,
) -> Prepared:
    """Prepare, never file: fill in what the model cannot know, build the request, hold it to
    the loop's rules, and read the inbox it will be filed into. The engine is handed the state
    it must see again before it writes.

    The base and the checks are never the caller's (the 2026-09-26 deploy review, F-06): a
    request that could name its own checks would choose the gate it is judged by, and one that
    could name its own base could start from anywhere. The base is the trunk's head, read here;
    the checks are built here, from fixed commands, over the test files the paths name."""
    objective_id = _objective(objective_id)
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
            "repair_rounds": record["max_repair_rounds"],
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
    """A path as the loop takes it, relative to the repository root. "app/fastpath" and
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


def _remember(status: LoopStatus) -> None:
    rows = _rows(status)
    _progress_cache.update(at=time.monotonic(), rows=rows)
    record = _gaps()
    if record is not None:
        record.progressed(rows)


def _rows(status: LoopStatus) -> dict[str, dict]:
    data = status.data if status.published else {}
    requests = data.get("requests") if isinstance(data, dict) else None
    items = [item for item in requests if isinstance(item, dict)] if isinstance(requests, list) else []
    return {str(item.get("request_id")): progress(item) for item in items if item.get("request_id")}


async def build_progress(request_ids: list[str]) -> dict[str, dict]:
    """Where each named request is, from the loop's status read at most once a minute. A request
    the loop has not picked up yet is queued; with GitHub unreachable, nothing is said."""
    wanted = [r for r in dict.fromkeys(request_ids) if isinstance(r, str) and r]
    if not wanted:
        return {}
    fresh = _progress_cache.get("at") is not None and time.monotonic() - _progress_cache["at"] < PROGRESS_TTL_S
    if not fresh:
        try:
            status = await _client().status()
        except GitHubError:
            log.info("engineering status unreadable for build progress", exc_info=True)
            return {}
        if isinstance(status, NotConnected):
            return {}
        _remember(status)
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
