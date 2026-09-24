"""Failure modes of the remote engineering inbox. Every one of them writes nothing."""

from __future__ import annotations

import re
from collections.abc import Iterable

from pydantic import ValidationError

__all__ = [
    "InboxBoundExceeded",
    "InboxError",
    "RequestContentChanged",
    "RequestSchemaError",
    "REDACTED",
    "TransportError",
    "redact_refusal",
    "redact_supplied",
    "redact_validation_error",
    "supplied_strings",
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


class InboxBoundExceeded(InboxError):
    """An inbox snapshot exceeded a fixed work bound. Nothing was admitted from it.

    The bounds are this host's constants (record count, per-record and aggregate bytes, listing
    bytes, wall-clock time), so the message names which bound and nothing a requester chose.
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


_MAX_SUPPLIED_STRINGS = 4096
_QUOTED = re.compile(r"'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"")


def supplied_strings(value: object) -> list[str]:
    """Every string a requester supplied inside ``value``, keys and values, without recursion.

    Iterative, so a deeply nested record cannot exhaust the stack, and capped, so a record
    with very many strings cannot make redaction itself unbounded.
    """
    out: list[str] = []
    stack: list[object] = [value]
    while stack and len(out) < _MAX_SUPPLIED_STRINGS:
        item = stack.pop()
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            stack.extend(item.keys())
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
    return out


def redact_supplied(text: str, supplied: Iterable[str], *, keep: Iterable[str] = ()) -> str:
    """``text`` with every supplied string (and its ``repr`` form) replaced by ``<redacted>``.

    Longest first, so a value containing another is removed whole. Strings shorter than three
    characters are left: they cannot carry a credential and would only mangle fixed wording.
    ``keep`` names values already published beside the text (the request id).
    """
    kept = set(keep)
    for value in sorted({s for s in supplied if len(s) >= 3 and s not in kept}, key=len, reverse=True):
        for form in (value, repr(value)[1:-1]):
            if form and form in text:
                text = text.replace(form, REDACTED)
    return text


def redact_refusal(text: str, supplied: Iterable[str], *, keep: Iterable[str] = ()) -> str:
    """A refusal reason safe to record and publish: quoted literals and supplied strings removed.

    Validators downstream of the adapter (the canonical Objective door, the kernel) quote the
    values they reject, and some normalise them first, so a supplied value can appear quoted
    in a form that is not byte-equal to what was supplied. Every quoted literal is therefore
    redacted outright, and any supplied string still present unquoted is redacted after it.
    """
    return redact_supplied(_QUOTED.sub(f"'{REDACTED}'", text), supplied, keep=keep)
