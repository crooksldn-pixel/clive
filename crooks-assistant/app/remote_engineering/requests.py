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

from .errors import RequestSchemaError

REQUEST_SCHEMA = "clive.remote_engineering_request.v1"
_REQUEST_ID = r"^[a-z0-9][a-z0-9.-]{2,79}$"


class RemoteObjectiveRequest(StrictRecord):
    schema_version: Literal["clive.remote_engineering_request.v1"] = REQUEST_SCHEMA
    request_id: str = Field(pattern=_REQUEST_ID)
    title: str = Field(min_length=1, max_length=200)
    requested_outcome: str = Field(min_length=1, max_length=20000)
    base_ref: str = Field(min_length=1, max_length=300)
    base_sha: ExactSha
    allowed_paths: tuple[str, ...] = Field(min_length=1)
    acceptance_criteria: tuple[str, ...] = ()
    checks: tuple[Check, ...] = ()
    target_branch: str = Field(min_length=1, max_length=200)
    max_repair_rounds: int = Field(default=2, ge=0, le=5)

    @field_validator("base_sha")
    @classmethod
    def exact_sha(cls, value: str) -> str:
        return validate_exact_sha(value)


def parse_request(raw: bytes) -> RemoteObjectiveRequest:
    """Parse and validate one request's exact bytes. Fails closed on anything unexpected."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RequestSchemaError(f"request is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RequestSchemaError("request must be a JSON object")
    if data.get("schema_version") != REQUEST_SCHEMA:
        raise RequestSchemaError(
            f"request schema_version {data.get('schema_version')!r} is not {REQUEST_SCHEMA!r}"
        )
    try:
        return RemoteObjectiveRequest.model_validate(data)
    except ValidationError as exc:
        raise RequestSchemaError(f"request does not match {REQUEST_SCHEMA}: {exc}") from exc
