"""Failure modes of the remote engineering inbox. Every one of them writes nothing."""

from __future__ import annotations

from pydantic import ValidationError

__all__ = ["InboxError", "RequestSchemaError", "redact_validation_error"]


class InboxError(ValueError):
    """The inbox adapter refused a request, a fetch, or a replay. Nothing was written."""


class RequestSchemaError(InboxError):
    """A request's bytes are not a valid ``clive.remote_engineering_request.v1`` record."""


def redact_validation_error(exc: ValidationError) -> str:
    """A refusal reason built only from field locations and messages, never a rejected value.

    ``str(ValidationError)`` includes each error's ``input``, which is exactly the
    rejected content a caller supplied, e.g. a credential submitted as an unknown
    field. A refusal reason is logged and returned to the requester, so it must
    never carry that value forward. Reading only ``loc`` and ``msg`` off each error
    (and never ``input`` or ``ctx``) keeps the rejected value out regardless of
    which keys a given pydantic version includes.
    """
    parts = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"])
        parts.append(f"{loc}: {error['msg']}" if loc else error["msg"])
    return "; ".join(parts)
