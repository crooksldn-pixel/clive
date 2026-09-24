"""Failure modes of the remote engineering inbox. Every one of them writes nothing."""

from __future__ import annotations

from pydantic import ValidationError

__all__ = [
    "InboxError",
    "RequestContentChanged",
    "RequestSchemaError",
    "REDACTED",
    "TransportError",
    "redact_validation_error",
]


class InboxError(ValueError):
    """The inbox adapter refused a request, a fetch, or a replay. Nothing was written."""


class RequestSchemaError(InboxError):
    """A request's bytes are not a valid ``clive.remote_engineering_request.v1`` record."""


class RequestContentChanged(InboxError):
    """An already-decided request id was presented again with different bytes. Nothing was written.

    Its message is built only from the schema-validated request id, so it is safe to
    project; it never carries the new or old request content.
    """


class TransportError(InboxError):
    """A git call failed. The message carries the operation and its exit status, never output.

    Git writes the remote it was talking to into its own diagnostics, and an authenticated
    remote URL carries a credential in its userinfo. That output must therefore never reach
    an exception message, because this loop's exception messages are printed to a long-lived
    process log and, for the inbox adapter, projected to a public branch. Only names this
    host itself configured (a remote name, a branch, a ref) and an exit status are bounded
    enough to travel; the operator diagnoses the rest from git's own stderr at the console.
    """


REDACTED = "<redacted>"


def _safe_segment(part: object, known: frozenset[str]) -> str:
    """A location segment only when this host already knew that label, else a placeholder.

    For a forbidden extra field, pydantic's ``loc`` segment *is* the rejected field name,
    which the requester chose: a credential put in an unknown key name would otherwise
    travel in a refusal reason exactly as a credential in an unknown key's value would.
    List indices are the host's own arithmetic and are bounded, so they travel as-is.
    """
    if isinstance(part, int):
        return str(part)
    return part if part in known else REDACTED


def redact_validation_error(exc: ValidationError, *, known: frozenset[str] = frozenset()) -> str:
    """A refusal reason built only from known field labels and messages, never rejected input.

    ``str(ValidationError)`` includes each error's ``input``, which is exactly the
    rejected content a caller supplied, e.g. a credential submitted as an unknown
    field. A refusal reason is logged and published, so it must never carry that value
    forward. Reading only ``loc`` and ``msg`` (never ``input`` or ``ctx``) keeps the
    rejected value out regardless of which keys a given pydantic version includes, and
    filtering ``loc`` through ``known`` keeps the rejected *label* out too. The default
    empty allowlist redacts every label, so a caller that forgets one fails safe.
    """
    parts = []
    for error in exc.errors():
        loc = ".".join(_safe_segment(part, known) for part in error["loc"])
        parts.append(f"{loc}: {error['msg']}" if loc else error["msg"])
    return "; ".join(parts)
