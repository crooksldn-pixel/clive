"""One engineering request, built from structured fields and checked against the loop's own
intake rules before anything leaves the Mac.

The rules are the loop's, imported rather than copied, so they cannot drift: the request
schema and its id pattern (app/remote_engineering/requests.py), the objective door every
request must then pass, PROTECTED_PATHS among it (app/orchestrator/objectives.py), and the
inbox's per-record size bound (app/remote_engineering/inbox.py). The exact bytes are finally
parsed by the loop's own `parse_request`, so a request built here is one the loop admits.

A refusal names the field and the rule, never the value. Anything the model supplied could be
a credential pasted in by mistake, and a refusal is read aloud, logged and shown on a card.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.orchestrator.contracts import validate_exact_sha
from app.orchestrator.objectives import PROTECTED_PATHS, Check, _overlaps
from app.remote_engineering.errors import RequestSchemaError
from app.remote_engineering.inbox import DEFAULT_INBOX_DIRECTORY, MAX_RECORD_BYTES
from app.remote_engineering.requests import (
    _REQUEST_ID,
    _TARGET_BRANCH_PREFIX,
    REQUEST_ID_MAX_LENGTH,
    REQUEST_LABELS,
    REQUEST_SCHEMA,
    RemoteObjectiveRequest,
    parse_request,
)

MAX_TITLE_CHARS = 200
MAX_OUTCOME_CHARS = 20000
MAX_REPAIR_ROUNDS = 5
CHECK_KEYS = frozenset({"name", "argv", "cwd"})

ID_RULE = (
    "request_id must be two to eight lowercase words of letters and digits joined by hyphens "
    f"(for example fix-order-notes), at most {REQUEST_ID_MAX_LENGTH} characters"
)


class RequestRefused(ValueError):
    """A request the loop would refuse. The message names fields and rules only."""


@dataclass(frozen=True, slots=True)
class EngineeringRequest:
    request_id: str
    record: dict[str, Any]
    content: bytes          # the exact bytes that will be filed

    @property
    def path(self) -> str:
        return request_path(self.request_id)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.content).hexdigest()


def valid_request_id(value: object) -> bool:
    return (
        isinstance(value, str) and len(value) <= REQUEST_ID_MAX_LENGTH
        and re.fullmatch(_REQUEST_ID, value) is not None
    )


def request_path(request_id: str) -> str:
    """requests/<request_id>.json, where the loop looks for it. Refused for any other id."""
    if not valid_request_id(request_id):
        raise RequestRefused(_refusal([ID_RULE]))
    return f"{DEFAULT_INBOX_DIRECTORY}/{request_id}.json"


def target_branch(request_id: str) -> str:
    """The one branch the loop publishes a request's work to: clive/objective/<request_id>."""
    return f"{_TARGET_BRANCH_PREFIX}{request_id}"


def build_request(
    *,
    request_id: object,
    title: object,
    requested_outcome: object,
    base_ref: object,
    base_sha: object,
    allowed_paths: object,
    acceptance_criteria: object = (),
    checks: object = (),
    max_repair_rounds: object = None,
) -> EngineeringRequest:
    """Build and validate one request. Every problem is named at once, and none is echoed."""
    problems: list[str] = []
    if not valid_request_id(request_id):
        problems.append(ID_RULE)
    if not _text(title, MAX_TITLE_CHARS):
        problems.append(f"title must be text of 1 to {MAX_TITLE_CHARS} characters")
    if not _text(requested_outcome, MAX_OUTCOME_CHARS):
        problems.append(f"requested_outcome must be text of 1 to {MAX_OUTCOME_CHARS} characters")
    if not isinstance(base_ref, str) or not base_ref.strip():
        problems.append("base_ref must be the name of the branch or tag the work starts from")
    if not _sha(base_sha):
        problems.append("base_sha must be a full 40-character lowercase commit SHA")
    paths = _paths(allowed_paths, problems)
    criteria = _criteria(acceptance_criteria, problems)
    check_records = _checks(checks, problems)
    # None leaves the number to the build server (its default, which the owner can raise: the loop upgrade of
    # 7 October 2026); a number is the request's own, kept as given.
    if max_repair_rounds is not None and (isinstance(max_repair_rounds, bool) or not isinstance(max_repair_rounds, int)
                                          or not 0 <= max_repair_rounds <= MAX_REPAIR_ROUNDS):
        problems.append(f"max_repair_rounds must be a whole number from 0 to {MAX_REPAIR_ROUNDS}")
    if problems:
        raise RequestRefused(_refusal(problems))

    record: dict[str, Any] = {
        "schema_version": REQUEST_SCHEMA,
        "request_id": request_id,
        "title": title,
        "requested_outcome": requested_outcome,
        "base_ref": base_ref,
        "base_sha": base_sha,
        "allowed_paths": paths,
        "acceptance_criteria": criteria,
        "checks": check_records,
        "target_branch": target_branch(str(request_id)),
    }
    if max_repair_rounds is not None:
        record["max_repair_rounds"] = max_repair_rounds
    try:
        RemoteObjectiveRequest.model_validate(record)
    except ValidationError as exc:
        # The loop's own schema has the last word on each field (base_ref's shape, for one).
        # Only the field's label is repeated: pydantic's own text quotes the input.
        raise RequestRefused(_refusal([f"{field} does not pass the loop's request schema" for field in _fields(exc)])) from None
    content = (json.dumps(record, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if len(content) > MAX_RECORD_BYTES:
        raise RequestRefused(_refusal([f"the whole request must be at most {MAX_RECORD_BYTES} bytes"]))
    try:
        parse_request(content)
    except RequestSchemaError:
        raise RequestRefused(_refusal(["the request does not pass the loop's own intake"])) from None
    return EngineeringRequest(request_id=str(request_id), record=record, content=content)


def _text(value: object, limit: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _sha(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return validate_exact_sha(value) == value
    except ValueError:
        return False


def _paths(value: object, problems: list[str]) -> list[str]:
    """Repository-relative paths, already in the form the objective door keeps them, and
    never over a path the loop protects."""
    if not isinstance(value, (list, tuple)) or not value:
        problems.append("allowed_paths must list at least one repository path")
        return []
    out: list[str] = []
    for index, path in enumerate(value, start=1):
        if (
            not isinstance(path, str) or not path or path != path.strip() or path.endswith("/")
            or path.startswith("/") or "\\" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
        ):
            problems.append(f"allowed_paths item {index} is not a repository-relative path")
            continue
        if any(_overlaps(path, protected) for protected in PROTECTED_PATHS):
            problems.append(f"allowed_paths item {index} overlaps a path the loop protects")
            continue
        out.append(path)
    return out


def _criteria(value: object, problems: list[str]) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        problems.append("acceptance_criteria must be a list of sentences")
        return []
    out: list[str] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, str) or not item.strip():
            problems.append(f"acceptance_criteria item {index} must be a sentence")
            continue
        out.append(item)
    return out


def _checks(value: object, problems: list[str]) -> list[dict[str, Any]]:
    """Each check as name, argv and cwd, held to the loop's own Check record."""
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        problems.append("checks must be a list of name, argv and cwd")
        return []
    out: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict) or not set(item) <= CHECK_KEYS or "name" not in item or "argv" not in item:
            problems.append(f"checks item {index} must have a name and an argv, and may have a cwd")
            continue
        argv = item.get("argv")
        cwd = item.get("cwd", ".")
        if not isinstance(argv, (list, tuple)) or not all(isinstance(arg, str) and arg for arg in argv) or not isinstance(cwd, str):
            problems.append(f"checks item {index} needs argv as a list of words and cwd as a path")
            continue
        try:
            check = Check.model_validate({"name": item.get("name"), "argv": list(argv), "cwd": cwd})
        except ValidationError:
            problems.append(
                f"checks item {index} is not a check the loop can run (name: lowercase letters, digits, "
                "- or _, at most 40; cwd: a path inside the repository)"
            )
            continue
        if check.name in names:
            problems.append(f"checks item {index} repeats the name of an earlier check")
            continue
        names.add(check.name)
        out.append({"name": check.name, "argv": list(check.argv), "cwd": check.cwd})
    return out


def _fields(exc: ValidationError) -> list[str]:
    """The labels of the fields the loop's schema refused, and nothing a requester chose."""
    out: list[str] = []
    for error in exc.errors():
        loc = error.get("loc") or ()
        # A whole-record rule (the target branch must be the request id's) has no location.
        label = str(loc[0]) if loc else "target_branch"
        label = label if label in REQUEST_LABELS else "request"
        if label not in out:
            out.append(label)
    return out or ["request"]


def _refusal(problems: list[str]) -> str:
    return "The request was refused: " + "; ".join(problems) + ". Nothing was filed."
