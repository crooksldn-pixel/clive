"""The strict JSON record a GitHub inbox request must be. Repository-only, immutable, bounded.

Deliberately excluded: repository, product-memory SHA, authority class, prohibited
actions, owner identity, builder/integrates. Those either name authority the remote
side must never assert (authority is always ``repository_only``, defaults are always
whole) or are host-configured (the repository and product-memory SHA the controller
already answers to, never something GPT supplies).
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field, ValidationError, field_validator

from app.orchestrator.contracts import ExactSha, StrictRecord, validate_exact_sha
from app.orchestrator.objectives import Check

from .errors import RequestSchemaError, redact_supplied, redact_validation_error, supplied_strings

REQUEST_SCHEMA = "clive.remote_engineering_request.v1"
# Bounded and safe to use as a filename and a record identity, but deliberately no
# stricter than that: the one canonical door (``app.orchestrator.objectives.Objective``)
# is what actually authorises an id, and a shorter duplicate rule here would only
# ever reject requests before the canonical validator gets to say why, hiding the
# real refusal reason (e.g. a protected path) behind a schema mismatch instead.
_REQUEST_ID = r"^[a-z0-9][a-z0-9.-]{0,79}$"
# ``base_ref`` is handed to ``git rev-parse`` before the canonical door sees it, so it has
# to be a bounded ref *here*. The character set excludes ``:``, ``@``, ``~``, ``^`` and
# whitespace, so it can be neither a URL (which could carry a credential) nor a revision
# expression, and the first character must be alphanumeric, so it can never be read as an
# option by the git command it is interpolated into.
_BASE_REF = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$"


class RemoteObjectiveRequest(StrictRecord):
    schema_version: Literal["clive.remote_engineering_request.v1"] = REQUEST_SCHEMA
    request_id: str = Field(pattern=_REQUEST_ID)
    title: str = Field(min_length=1, max_length=200)
    requested_outcome: str = Field(min_length=1, max_length=20000)
    base_ref: str = Field(pattern=_BASE_REF)
    base_sha: ExactSha
    allowed_paths: tuple[str, ...] = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = ()
    checks: tuple[Check, ...] = ()
    target_branch: str = Field(min_length=1, max_length=200)
    max_repair_rounds: int = Field(default=2, ge=0, le=5)

    @field_validator("base_ref")
    @classmethod
    def bounded_base_ref(cls, value: str) -> str:
        if ".." in value or "//" in value or value.endswith(("/", ".lock")):
            raise ValueError("base_ref must be a single bounded git ref, not a revision expression")
        return value

    @field_validator("base_sha")
    @classmethod
    def exact_sha(cls, value: str) -> str:
        return validate_exact_sha(value)


# Every field label this host itself defined, and therefore the only ones a refusal reason
# may repeat back. Anything else in a validation location was named by the requester.
REQUEST_LABELS = frozenset(RemoteObjectiveRequest.model_fields) | frozenset(Check.model_fields)


def parse_request(raw: bytes) -> RemoteObjectiveRequest:
    """Parse and validate one request's exact bytes. Fails closed on anything unexpected.

    Every decoder failure is a refusal, not a crash: besides malformed UTF-8 and JSON, Python's
    decoder raises ``RecursionError`` on deeply nested input and ``ValueError`` on an integer
    beyond the interpreter's digit limit, and either would otherwise escape into the loop.
    """
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, RecursionError):
        # Never ``{exc}``: a decode error quotes the offending bytes and a JSON error can
        # quote the offending token, either of which is rejected content verbatim.
        raise RequestSchemaError("request is not valid UTF-8 JSON") from None
    if not isinstance(data, dict):
        raise RequestSchemaError("request must be a JSON object")
    if data.get("schema_version") != REQUEST_SCHEMA:
        # The supplied value is rejected content and is never echoed: a refusal reason is
        # logged and published, and anything a requester chose could be a credential.
        raise RequestSchemaError(f"request schema_version is not {REQUEST_SCHEMA!r}")
    try:
        return RemoteObjectiveRequest.model_validate(data)
    except ValidationError as exc:
        detail = redact_supplied(redact_validation_error(exc, known=REQUEST_LABELS), supplied_strings(data))
        raise RequestSchemaError(f"request does not match {REQUEST_SCHEMA}: {detail}") from None
    except (ValueError, RecursionError):
        raise RequestSchemaError(f"request does not match {REQUEST_SCHEMA}") from None
