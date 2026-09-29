"""Redacted per-turn JSONL logging with rotation.

Everything this application logs passes through redact() first. The rule the M13 check applies
is not "we intended not to log addresses" but "open a real log file and confirm there are none".
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

log = logging.getLogger("crooks.turnlog")

MAX_BYTES = 5_000_000
KEEP_FILES = 5

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# Things that look like personal data and are not: Shopify GIDs, proposal ids, hex ids, errnos
# ("[Errno -1094995529]"), timestamped filenames ("20260907-225520.webm"). Protected first.
_PROTECT = re.compile(
    r"gid://shopify/\w+/\d+|prop_[0-9a-f]+|[0-9a-f]{16,}|Errno -?\d+|\d{8}-\d{6}(?:\.\w+)?"
)
# UK mobile and landline shapes, and international. A digit run glued to a letter, hyphen or
# dot on either side is an identifier, not a number someone dials.
_PHONE = re.compile(r"(?<![\w.-])(?:\+\d{1,3}[\s-]?)?(?:\d[\s-]?){9,14}\d(?![\w.-])")
# UK postcode, excluding inward parts that are garment sizes (2XL, 3XS) or pack counts (3PK).
_POSTCODE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s*\d(?!XL|XS|PK|PC)[A-Z]{2}\b", re.I)
_CARD = re.compile(r"(?<![\w.-])(?:\d[ -]?){13,19}(?![\w.-])")

# Keys whose values are addresses or contact details however they are spelled.
_REDACT_KEYS = {
    "address", "address1", "address2", "shippingaddress", "billingaddress", "street",
    "phone", "phonenumber", "postcode", "zip", "postalcode", "email", "emailaddress",
    "from_email", "customer_email", "body", "snippet",
    # Names are personal data too. Order `name` (CROOKS-1928) is a different key and survives.
    "customer_name", "displayname", "from",
}


def redact_text(text: str, names: Iterable[str] = ()) -> str:
    """Redact by shape, and by the specific names this turn's tools returned. A name cannot be
    found by regex; it can be found because we know exactly which names the model was shown."""
    for name in sorted({n for n in names if n and len(n) >= 3}, key=len, reverse=True):
        text = re.sub(re.escape(name), "[name]", text, flags=re.I)
    protected: list[str] = []

    def keep(match: re.Match) -> str:
        protected.append(match.group(0))
        return f"\x00{len(protected) - 1}\x00"

    text = _PROTECT.sub(keep, text)
    text = _EMAIL.sub("[email]", text)
    text = _CARD.sub("[card]", text)
    text = _POSTCODE.sub("[postcode]", text)
    text = _PHONE.sub("[phone]", text)
    return re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], text)


class RedactingFilter(logging.Filter):
    """Redacts every formatted log message. Transcripts, tool arguments and API error text all
    pass through stdlib logging, and none of them may carry a customer's details to disk."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001
            return True
        record.msg = _with_names_out(redact_text(message))
        record.args = ()
        return True


def _with_names_out(text: str) -> str:
    """And the customer names this process has been told (the timeline's set): a log line can
    carry one a read returned — "Mia Kowalski has no email address" — as well as a shape."""
    try:
        from app.observability.timeline import _names_out

        return _names_out(text)
    except Exception:  # noqa: BLE001 — a log line is never lost to its own redaction
        return text


def redact(value: Any, names: Iterable[str] = ()) -> Any:
    """Walk any structure and redact by key name, by value shape, and by known names."""
    names = tuple(names)
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if str(key).lower().replace("_", "") in {k.replace("_", "") for k in _REDACT_KEYS}:
                out[key] = "[redacted]" if item not in (None, "", [], {}) else item
            else:
                out[key] = redact(item, names)
        return out
    if isinstance(value, list):
        return [redact(v, names) for v in value]
    if isinstance(value, str):
        return redact_text(value, names)
    return value


class TurnLog:
    def __init__(self, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / "turns.jsonl"

    def write(self, record: dict[str, Any], names: Iterable[str] = ()) -> None:
        record = {"ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S"), **redact(record, names)}
        try:
            self._rotate_if_needed()
            # It holds what was said and what was answered: the owner's to read and nobody
            # else's, like the action ledger beside it. Created 0600; an existing file that
            # anyone could read is tightened the first time this notices.
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
            if self.path.stat().st_mode & 0o077:
                self.path.chmod(0o600)
        except OSError as exc:
            log.warning("could not write turn log: %s", exc)

    def _rotate_if_needed(self) -> None:
        if not self.path.exists() or self.path.stat().st_size < MAX_BYTES:
            return
        for index in range(KEEP_FILES - 1, 0, -1):
            older = self.log_dir / f"turns.jsonl.{index}"
            newer = self.log_dir / f"turns.jsonl.{index + 1}"
            if older.exists():
                older.rename(newer)
        self.path.rename(self.log_dir / "turns.jsonl.1")
