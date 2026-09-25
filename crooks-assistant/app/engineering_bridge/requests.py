"""An engineering request, built from structured fields and held to the loop's own intake rules.

The loop (app/remote_engineering/requests.py, then app/orchestrator/objectives.py) refuses a
request that breaks any of these rules, and a refusal there is a round trip through GitHub
and a published status. Checking here first means the owner is only ever asked to approve a
request the loop will accept.

A refusal names the field and the rule and never the value. What a model put in a field can
be anything — a pasted credential included — and a refusal is read aloud, logged and shown.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.orchestrator.objectives import PROTECTED_PATHS

REQUEST_SCHEMA = "clive.remote_engineering_request.v1"
REQUEST_ID = re.compile(r"^[a-z][a-z0-9]{0,15}(-[a-z0-9]{1,16}){1,7}$")
TARGET_BRANCH_PREFIX = "clive/objective/"

MAX_TITLE = 200
MAX_OUTCOME = 20_000
MAX_REPAIR_ROUNDS = 5
DEFAULT_REPAIR_ROUNDS = 2
# Bounds the loop does not set but a request filed from a conversation should keep.
MAX_PATHS = 50
MAX_PATH_CHARS = 300
MAX_CRITERIA = 50
MAX_CRITERION_CHARS = 2_000
MAX_CHECKS = 20
MAX_ARGV = 40
MAX_ARG_CHARS = 500

_BASE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_SHA = re.compile(r"^[0-9a-f]{40}$")
_CHECK_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_CHECK_KEYS = frozenset({"name", "argv", "cwd"})


class RequestRefused(ValueError):
    """A field broke a rule. The message names the field and the rule, never the value."""


@dataclass(frozen=True, slots=True)
class EngineeringRequest:
    request_id: str
    title: str
    requested_outcome: str
    base_ref: str
    base_sha: str
    allowed_paths: tuple[str, ...]
    acceptance_criteria: tuple[str, ...]
    checks: tuple[dict[str, Any], ...]
    target_branch: str
    max_repair_rounds: int

    def document(self) -> dict[str, Any]:
        """The request as the loop reads it, field for field."""
        return {
            "schema_version": REQUEST_SCHEMA,
            "request_id": self.request_id,
            "title": self.title,
            "requested_outcome": self.requested_outcome,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "allowed_paths": list(self.allowed_paths),
            "acceptance_criteria": list(self.acceptance_criteria),
            "checks": [
                {"name": c["name"], "argv": list(c["argv"]), "cwd": c["cwd"]} for c in self.checks
            ],
            "target_branch": self.target_branch,
            "max_repair_rounds": self.max_repair_rounds,
        }

    def to_bytes(self) -> bytes:
        """The exact bytes filed as requests/<request_id>.json."""
        return (json.dumps(self.document(), indent=2, ensure_ascii=False) + "\n").encode("utf-8")

    @property
    def path(self) -> str:
        return request_path(self.request_id)


def request_path(request_id: str) -> str:
    """Where a request lives on the inbox branch. Only for an id that has passed the rule."""
    return f"requests/{check_request_id(request_id)}.json"


def check_request_id(value: object) -> str:
    if not isinstance(value, str) or not REQUEST_ID.fullmatch(value):
        raise RequestRefused(
            "request_id must be 2 to 8 lowercase words of letters and digits joined by hyphens, "
            "starting with a letter, each word at most 16 characters (for example bridge-status-v1)"
        )
    return value


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
    max_repair_rounds: object = DEFAULT_REPAIR_ROUNDS,
    target_branch: object = None,
) -> EngineeringRequest:
    """Build a request, or refuse it with the first rule it breaks. `target_branch` is
    derived from the request id; when one is supplied it must be exactly that."""
    rid = check_request_id(request_id)
    branch = f"{TARGET_BRANCH_PREFIX}{rid}"
    if target_branch is not None and target_branch != branch:
        raise RequestRefused("target_branch must be exactly clive/objective/<request_id>")
    return EngineeringRequest(
        request_id=rid,
        title=_text("title", title, MAX_TITLE),
        requested_outcome=_text("requested_outcome", requested_outcome, MAX_OUTCOME),
        base_ref=_base_ref(base_ref),
        base_sha=_base_sha(base_sha),
        allowed_paths=_allowed_paths(allowed_paths),
        acceptance_criteria=_criteria(acceptance_criteria),
        checks=_checks(checks),
        target_branch=branch,
        max_repair_rounds=_repair_rounds(max_repair_rounds),
    )


def _text(field: str, value: object, limit: int) -> str:
    if not isinstance(value, str):
        raise RequestRefused(f"{field} must be text")
    if not value.strip():
        raise RequestRefused(f"{field} must not be empty")
    if len(value) > limit:
        raise RequestRefused(f"{field} must be at most {limit} characters")
    return value


def _base_ref(value: object) -> str:
    if not isinstance(value, str) or not _BASE_REF.fullmatch(value):
        raise RequestRefused(
            "base_ref must be a branch or tag name: letters, digits, '.', '_', '/' and '-', "
            "starting with a letter or digit, at most 200 characters"
        )
    if ".." in value or "//" in value or value.endswith(("/", ".lock")):
        raise RequestRefused("base_ref must be a single git ref, not a revision expression")
    return value


def _base_sha(value: object) -> str:
    text = value.lower() if isinstance(value, str) else ""
    if not _SHA.fullmatch(text):
        raise RequestRefused("base_sha must be a full 40-character hexadecimal commit id")
    return text


def _items(field: str, value: object, *, limit: int) -> list[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Iterable):
        raise RequestRefused(f"{field} must be a list")
    items = list(value)
    if len(items) > limit:
        raise RequestRefused(f"{field} must have at most {limit} entries")
    return items


def _allowed_paths(value: object) -> tuple[str, ...]:
    items = _items("allowed_paths", value, limit=MAX_PATHS)
    if not items:
        raise RequestRefused("allowed_paths must name at least one path")
    cleaned: list[str] = []
    for number, raw in enumerate(items, start=1):
        if not isinstance(raw, str) or len(raw) > MAX_PATH_CHARS:
            raise RequestRefused(f"allowed_paths entry {number} must be a path of at most {MAX_PATH_CHARS} characters")
        path = raw.strip().rstrip("/")
        if not path or path.startswith("/") or "\\" in path or any(
            part in {"", ".", ".."} for part in path.split("/")
        ):
            raise RequestRefused(f"allowed_paths entry {number} is not a repository-relative path")
        if any(_overlaps(path, protected) for protected in PROTECTED_PATHS):
            # Not named, even though the protected list is the host's own: when the entry IS
            # the protected path, naming one would repeat the rejected value back.
            raise RequestRefused(
                f"allowed_paths entry {number} overlaps a path the engineering loop protects "
                "(its kernel, reviewers, CI or service installers); the owner changes those by hand"
            )
        cleaned.append(path)
    return tuple(cleaned)


def _overlaps(a: str, b: str) -> bool:
    """Either path is the other or contains it — the loop's own test."""
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def _criteria(value: object) -> tuple[str, ...]:
    items = _items("acceptance_criteria", value, limit=MAX_CRITERIA)
    out: list[str] = []
    for number, item in enumerate(items, start=1):
        if not isinstance(item, str) or not item.strip():
            raise RequestRefused(f"acceptance_criteria entry {number} must be non-empty text")
        if len(item) > MAX_CRITERION_CHARS:
            raise RequestRefused(f"acceptance_criteria entry {number} must be at most {MAX_CRITERION_CHARS} characters")
        out.append(item)
    return tuple(out)


def _checks(value: object) -> tuple[dict[str, Any], ...]:
    items = _items("checks", value, limit=MAX_CHECKS)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for number, item in enumerate(items, start=1):
        if not isinstance(item, dict) or not set(item) <= _CHECK_KEYS:
            raise RequestRefused(f"checks entry {number} must have only name, argv and cwd")
        name = item.get("name")
        if not isinstance(name, str) or not _CHECK_NAME.fullmatch(name):
            raise RequestRefused(
                f"checks entry {number} needs a name of lowercase letters, digits, '_' and '-', "
                "at most 40 characters"
            )
        if name in seen:
            raise RequestRefused(f"checks entry {number} repeats the name of an earlier check")
        seen.add(name)
        argv = item.get("argv")
        if not isinstance(argv, (list, tuple)) or not argv or len(argv) > MAX_ARGV:
            raise RequestRefused(f"checks entry {number} needs argv: a list of 1 to {MAX_ARGV} arguments")
        if any(not isinstance(arg, str) or not arg or len(arg) > MAX_ARG_CHARS for arg in argv):
            raise RequestRefused(f"checks entry {number} has an argument that is empty, not text or too long")
        cwd = item.get("cwd", ".")
        if not isinstance(cwd, str) or not cwd or (
            cwd != "." and (cwd.startswith("/") or ".." in cwd.split("/") or "\\" in cwd)
        ):
            raise RequestRefused(f"checks entry {number} needs a cwd inside the repository, without '..'")
        out.append({"name": name, "argv": tuple(argv), "cwd": cwd})
    return tuple(out)


def _repair_rounds(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_REPAIR_ROUNDS:
        raise RequestRefused(f"max_repair_rounds must be a whole number from 0 to {MAX_REPAIR_ROUNDS}")
    return value
