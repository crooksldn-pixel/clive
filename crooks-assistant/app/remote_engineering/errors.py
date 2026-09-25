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
    "redact_published",
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


# A private key block, whole; or, when a bounded tail cut its BEGIN line off, everything up to its END.
_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----|\Z)",
    re.S,
)
_KEY_BLOCK_END = re.compile(r"\A.*-----END [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----", re.S)
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://)[^\s/@]+@")
# Credential shapes, never inside a longer identifier: provider API keys, platform tokens, JWTs.
_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])(?:sk-ant-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9_\-]{16,}|[sr]k_(?:live|test)_[A-Za-z0-9]{8,}"
    r"|sk_[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_\-]{20,}"
    r"|xox[abposr]-[A-Za-z0-9\-]{8,}|(?:AKIA|ASIA)[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{35}"
    r"|shp(?:at|ca|ss|pa)_[A-Za-z0-9]{8,}|ya29\.[A-Za-z0-9_\-]{8,}|1//[A-Za-z0-9_\-]{20,}"
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})"
)
_AUTH_SCHEME = re.compile(r"(?i)\b(bearer|basic)(\s+)[A-Za-z0-9._~+/\-]{16,}=*")
# ``password=...``, ``"api_key": "..."``, ``Authorization: ...``: the name stays, the value goes.
_ASSIGNED = re.compile(
    r"(?i)\b((?:[a-z0-9]+[_\-]){0,4}(?:password|passwd|passphrase|secret|token|api[_\-]?key|access[_\-]?key"
    r"|private[_\-]?key|credentials?|authorization|cookie))(\s*[\"']?\s*[:=]\s*[\"']?)([^\s\"',;]+)"
)
# One word at a time, so a long run without a slash costs one pass, not one pass per character.
_WORD = re.compile(r"[^\s'\"`<>()\[\]{},;=]+")
_CREDENTIAL_PATH = re.compile(
    r"(?:^|/)(?:\.ssh|\.gnupg|\.aws|\.azure|\.kube|\.docker|\.password-store|secrets?|credentials?)(?:/|$)"
    r"|(?:^|/)(?:\.netrc|\.git-credentials|\.pgpass|\.npmrc|\.pypirc|id_(?:rsa|dsa|ecdsa|ed25519)(?:\.pub)?)$"
    r"|\.(?:pem|key|p12|pfx|jks|keystore|gpg)$",
    re.I,
)


def _credential_path(match: re.Match) -> str:
    word = match.group(0)
    return REDACTED if "/" in word and _CREDENTIAL_PATH.search(word.rstrip(".:")) else word


def redact_published(text: str, supplied: Iterable[str] = (), *, keep: Iterable[str] = ()) -> str:
    """Free text safe to publish: no private key, credential, token or credential path survives.

    For text this adapter did not write and cannot allowlist -- a reviewer's finding, a check's
    output, a worker's report -- so it is redacted by shape: private key blocks (also one whose
    BEGIN line a bounded tail cut off), credentials in URL userinfo, known token formats, the
    value of anything assigned to a secret-like name, and any path into a credential location
    (``.ssh``, ``secrets/``, ``*.pem``, ``*.key`` ...). ``redact_supplied`` then removes any
    supplied string, exactly as for a refusal reason. Quoted literals are kept, unlike in
    ``redact_refusal``: here they are the substance (an assertion's operands), not an echo of
    rejected input. Redact before truncating, so a cut can never leave half a secret unmatched.
    """
    text = _KEY_BLOCK.sub(REDACTED, text)
    text = _KEY_BLOCK_END.sub(REDACTED, text)
    text = _URL_USERINFO.sub(rf"\1{REDACTED}@", text)
    text = _TOKEN.sub(REDACTED, text)
    text = _AUTH_SCHEME.sub(rf"\1\2{REDACTED}", text)
    text = _ASSIGNED.sub(rf"\1\2{REDACTED}", text)
    text = _WORD.sub(_credential_path, text)
    return redact_supplied(text, supplied, keep=keep)
