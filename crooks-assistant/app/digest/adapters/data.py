"""The digester's adapter for datasets: CSV and TSV, JSON arrays of records, JSON Lines and
SQLite databases. Each file, or each table of a database, becomes one data_schema Unit: its
columns, the type each holds (integer, number, boolean, date, datetime or text), how many rows
it has, how often each column is empty and roughly how many distinct values it holds.

Digesting is reading. Text files are read up to MAX_TEXT_BYTES and scanned up to MAX_ROWS rows;
a SQLite database is opened through a file URI with mode=ro and immutable=1, at most
MAX_SCHEMA_ENTRIES of its tables and views are listed, only its tables are read — never its
views, which would run SQL stored in the database — no value is fetched past its first
MAX_CELL_CHARS characters or bytes, and every statement is stopped once it has used its share
of work. However many files and tables the artifact holds, no more than MAX_TOTAL_CELLS values
and MAX_TOTAL_SQLITE_STEPS of SQLite's work are spent on it in all; what that leaves unread is
said so. Directories are walked without recursion, and a file whose name cannot be recorded is
counted, not read. Nothing is written back.

A column that looks like personal data — by its name (email, phone, postcode, a person's name,
in words or run together, as in "phonenumber") or because at least half its values look like
email addresses, phone numbers, postcodes or ZIP codes (punctuated or digits alone, stored as
text or as numbers) or people's names, or are JSON lists or objects holding any of these — is
marked personal, and none of its values appear in any Unit. Other columns show at most
MAX_EXAMPLES short example values, never one that itself looks personal and never a JSON list
or object. A first row with a cell that reads as a person's name is read as a record unless
something else says it is a header; a column name — a header cell, a record's key or a table's
column — that reads as a person's name is never shown, and neither is anything SQLite quotes
from the database in an error.

What cannot be read is skipped and said so, in a knowledge Unit tagged 'unparsed' with the
reason: decompose never raises on malformed input."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import sqlite3
from collections.abc import Callable, Sequence
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

from app.digest.model import MAX_BODY, MAX_TITLE, Location, Unit

NAME = "data"
HANDLES = ("dataset",)

SUFFIXES = {
    ".csv": "csv", ".tsv": "tsv", ".tab": "tsv", ".json": "json", ".jsonl": "jsonl",
    ".ndjson": "jsonl", ".sqlite": "sqlite", ".sqlite3": "sqlite", ".db": "sqlite",
    ".db3": "sqlite",
}
SKIPPED_DIRECTORIES = frozenset((".git",))

MAX_ENTRIES = 50_000              # directory entries, files or directories, looked at
MAX_FILES = 200                   # dataset files read per artifact
MAX_TEXT_BYTES = 4 * 1024 * 1024  # read from a text file; a larger JSON document is not read
MAX_ROWS = 50_000                 # rows scanned per file or table
MAX_CELLS = 1_000_000             # values scanned per file or table
MAX_COLUMNS = 100                 # columns profiled per file or table
MAX_TABLES = 100                  # tables read per database
MAX_SCHEMA_ENTRIES = 1_000        # tables and views looked at per database
MAX_CELL_CHARS = 4_096            # of a SQLite text or blob value, fetched for profiling
MAX_VALUE_BYTES = 4 * 1024 * 1024  # the largest value SQLite itself is let read
MAX_DISTINCT = 10_000             # distinct values counted per column before "more than"
MAX_EXAMPLES = 3
MAX_EXAMPLE_CHARS = 40
MAX_NAME_CHARS = 80
SNIFF_CHARS = 4 * 1024            # of a delimited file, to find its dialect: csv.Sniffer
                                  # costs its sample squared at worst, 0.1 s at this size
SQLITE_STEPS = 20_000             # progress callbacks, each 1,000 SQLite instructions, per table
# what the whole artifact may cost, however many files and tables it holds — a database can
# list one table's rows under a hundred names, and each would otherwise be scanned in full
MAX_TOTAL_CELLS = 2_000_000       # values profiled across every file and table
MAX_TOTAL_SQLITE_STEPS = 200_000  # progress callbacks across every database
MAX_REASON_CHARS = 300            # of an error message from a database, once made safe to show
SQLITE_MAGIC = b"SQLite format 3\x00"

NULL_WORDS = frozenset(("null", "none", "na", "n/a", "nan"))
BOOLEAN_WORDS = frozenset(("true", "false", "yes", "no"))
PERSONAL_WORDS = frozenset((
    "email", "phone", "telephone", "tel", "mobile", "cellphone", "fax", "postcode", "postal",
    "zip", "zipcode", "surname", "forename", "firstname", "lastname", "fullname", "username",
    "address", "street", "birthdate", "dob", "dateofbirth", "birthday", "mobileno",
    "mobilenumber", "cellno", "cellnumber", "telno", "phoneno",
))
# personal words long enough to be found inside a name written without separators, as in
# "contactemail", "phonenumber" or "billingaddress"
PERSONAL_PARTS = (
    "email", "phone", "postcode", "postal", "zipcode", "surname", "forename", "firstname",
    "lastname", "fullname", "username", "address", "birthdate",
)
# "name" on its own, or with one of these, is a person's name; "product_name" is not.
NAME_QUALIFIERS = frozenset((
    "first", "last", "full", "given", "family", "middle", "maiden", "nick", "display", "user",
    "customer", "contact", "person", "client", "owner", "recipient", "sender", "patient",
    "employee", "member", "student", "account", "holder", "billing", "shipping",
))
# lower-case words inside a person's name, and titles before one
NAME_PARTICLES = frozenset((
    "al", "bin", "da", "de", "del", "della", "der", "di", "du", "el", "la", "le", "van", "von",
))
HONORIFICS = frozenset(("mr", "mrs", "ms", "miss", "mx", "dr", "prof", "sir", "dame"))

_INTEGER = re.compile(r"[+-]?[0-9]+")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[eE][+-]?[0-9]+)?")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_DATETIME = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]{1,6})?)?"
    r"(?:Z|[+-][0-9]{2}:?[0-9]{2})?"
)
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}")
_POSTCODE = r"[A-Z]{1,2}[0-9][A-Z0-9]? ?[0-9][A-Z]{2}|[A-Z][0-9][A-Z] ?[0-9][A-Z][0-9]"
_POSTCODE_WHOLE = re.compile(_POSTCODE, re.IGNORECASE | re.ASCII)
_POSTCODE_WITHIN = re.compile(rf"\b(?:{_POSTCODE})\b", re.IGNORECASE | re.ASCII)
_PHONE = re.compile(r"\+?[0-9 ().-]{7,24}")
_SEPARATED_DIGITS = re.compile(r"[0-9][ ().-]+[0-9]")
# digits alone: a national number with its leading 0, an international one after 00, a North
# American one (area code and exchange each starting 2-9), with or without its 1, or another
# international one without its + (a country code from 2 to 9, E.164's 11 to 15 digits in all)
_DIGIT_PHONE = re.compile(
    r"0[0-9]{9,10}|00[1-9][0-9]{7,13}|1?[2-9][0-9]{2}[2-9][0-9]{6}|[2-9][0-9]{10,14}"
)
_ZIP = re.compile(r"[0-9]{5}(?:-[0-9]{4})?")
_WORDS = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|[0-9]+")
_NAME_MARKS = re.compile(r"['’.-]")
_MC = re.compile(r"^Ma?c(?=[A-Z])")


def decompose(root: Path, artifact_id: str) -> list[Unit]:
    """The Units read out of the datasets under root (a directory, or one dataset file), in
    the order of their relative paths. Reads only; never raises on malformed input."""
    root = Path(root)
    found, notes = _find(root)
    budget = _Budget()
    units: list[Unit] = []
    for rel, path, fmt in found:
        if budget.spent():
            units.append(_unparsed(artifact_id, rel, (
                f"Not read: the artifact's scan limit — {MAX_TOTAL_CELLS} values, or "
                f"{MAX_TOTAL_SQLITE_STEPS} steps of SQLite's work, across all its datasets — "
                "was reached before this file."
            )))
            continue
        try:
            units.extend(_READERS[fmt](artifact_id, rel, path, fmt, budget))
        except Exception as exc:
            units.append(_unparsed(artifact_id, rel, f"Could not be read: {type(exc).__name__}."))
    units.extend(_unparsed(artifact_id, ".", note) for note in notes)
    return units


class _Budget:
    """What is left of the scanning the whole artifact may cost: values profiled, and
    SQLite's work. Each file and table also has its own limits; these hold across them all."""

    def __init__(self) -> None:
        self.cells = MAX_TOTAL_CELLS
        self.steps = MAX_TOTAL_SQLITE_STEPS

    def spent(self) -> bool:
        return self.cells <= 0 or self.steps <= 0


# --- finding the datasets --------------------------------------------------------------------


def _format(name: str) -> str | None:
    return SUFFIXES.get(os.path.splitext(name)[1].lower())


def _recordable(rel: str) -> bool:
    """Whether a relative path can be the path of a Unit's Location: a name that is not UTF-8
    could be made into a Unit but not into its id."""
    try:
        rel.encode("utf-8")
        Location(rel)
    except ValueError:
        return False
    return True


def _find(root: Path) -> tuple[list[tuple[str, Path, str]], list[str]]:
    """(relative path, path, format) of each regular dataset file, sorted and capped, and the
    notes to make about what was not looked at. Symbolic links are never followed.

    Directories are listed from a stack, not by recursion, so no depth of nesting can raise;
    every entry listed, a directory as much as a file, counts towards MAX_ENTRIES, and the
    directory that would take the count past it, and every one after it, is not taken. A file
    whose name cannot be recorded is left out and counted."""
    try:
        if root.is_file():
            fmt = _format(root.name)
            if fmt is None:
                return [], []
            if not _recordable(root.name):
                return [], ["A dataset file whose name cannot be recorded was not read."]
            return [(root.name, root, fmt)], []
        if not root.is_dir():
            return [], ["The artifact is not a readable file or directory."]
    except OSError as exc:
        return [], [f"The artifact could not be looked at: {type(exc).__name__}."]
    found: list[tuple[str, Path, str]] = []
    notes: list[str] = []
    entries = unnamed = 0
    pending: list[tuple[str, str]] = [(str(root), "")]
    while pending:
        directory, prefix = pending.pop()
        listed: list[os.DirEntry[str]] = []
        try:
            with os.scandir(directory) as listing:
                for entry in listing:
                    entries += 1
                    if entries > MAX_ENTRIES:
                        break
                    listed.append(entry)
        except OSError:
            continue
        if entries > MAX_ENTRIES:
            notes.append(
                f"Stopped looking for datasets after {MAX_ENTRIES} directory entries: the "
                "directory that went past them, and every one after it, was not looked at."
            )
            break
        subdirectories: list[tuple[str, str]] = []
        for entry in sorted(listed, key=lambda item: item.name):
            rel = prefix + entry.name
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in SKIPPED_DIRECTORIES:
                        subdirectories.append((entry.path, rel + "/"))
                    continue
                fmt = _format(entry.name)
                if fmt is None or not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            if _recordable(rel):
                found.append((rel, Path(entry.path), fmt))
            else:
                unnamed += 1
        pending.extend(reversed(subdirectories))
    if unnamed:
        notes.append(f"{unnamed} dataset files whose names cannot be recorded were not read.")
    found.sort(key=lambda item: item[0])
    if len(found) > MAX_FILES:
        notes.append(
            f"{len(found) - MAX_FILES} more dataset files were not read: at most {MAX_FILES} "
            "are read per artifact."
        )
        found = found[:MAX_FILES]
    return found, notes


# --- values ----------------------------------------------------------------------------------


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _shown(text: str) -> str:
    """A name as it may appear in a Unit: on one line, printable and not too long."""
    flat = " ".join(text.split())
    return _clip("".join(char if char.isprintable() else "?" for char in flat), MAX_NAME_CHARS)


def _infer(text: str) -> str:
    if text.lower() in BOOLEAN_WORDS:
        return "boolean"
    if _INTEGER.fullmatch(text):
        return "integer"
    if _NUMBER.fullmatch(text):
        return "number"
    try:
        if _DATE.fullmatch(text):
            date.fromisoformat(text)
            return "date"
        if _DATETIME.fullmatch(text):
            datetime.fromisoformat(text)
            return "datetime"
    except ValueError:
        pass
    return "text"


def _personal_value(text: str) -> bool:
    """Whether a value on its own looks like an email address, a phone number or a postcode —
    written with punctuation or as digits alone, like "07700900123" or a ZIP code "02139"."""
    if _EMAIL.fullmatch(text) or _POSTCODE_WHOLE.fullmatch(text):
        return True
    if _DIGIT_PHONE.fullmatch(text) or _ZIP.fullmatch(text):
        return True
    if not _PHONE.fullmatch(text) or _DATE.fullmatch(text) or _NUMBER.fullmatch(text):
        return False
    digits = sum(char.isdigit() for char in text)
    if not 7 <= digits <= 15:
        return False
    if text.startswith(("+", "(")):
        return True
    if _SEPARATED_DIGITS.search(text) is None:
        return False
    # dots alone, as in "415.555.0123", also separate a date's eight digits: a phone number
    # written so has at least nine
    return digits >= 9 or any(char in " ()-" for char in text)


def _digits_personal(text: str) -> bool:
    """Whether a number, written out, reads as a phone number or a ZIP code in digits alone."""
    return _DIGIT_PHONE.fullmatch(text) is not None or _ZIP.fullmatch(text) is not None


def _name_like(text: str) -> bool:
    """Whether a value reads as a person's name: two to four capitalised or upper-case words, as
    in "Ada Lovelace", "Hopper, Grace", "ADA LOVELACE" or "Dr J. Smith-Jones". A place or a
    product named the same way is withheld too: a name shown by mistake cannot be taken back."""
    words = text.replace(",", " ", 1).split()
    if len(text) > 60 or not 2 <= len(words) <= 4:
        return False
    named = 0
    for word in words:
        bare = _NAME_MARKS.sub("", word)
        if not bare.isalpha():
            return False
        if word in NAME_PARTICLES:
            continue
        if not (_MC.sub("", word).istitle() or word.isupper()):
            return False
        if len(bare) > 1 and bare.lower() not in HONORIFICS:
            named += 1
    return named > 0


def _personal_name(name: str) -> bool:
    """Whether a column's name says it holds personal data — written in words, as in
    "customer_email" or "First Name", or run together, as in "phonenumber" or
    "customername"."""
    words = [word.lower() for word in _WORDS.findall(name)]
    if "".join(words) in PERSONAL_WORDS or any(word in PERSONAL_WORDS for word in words):
        return True
    if any(part in word for word in words for part in PERSONAL_PARTS):
        return True
    if any(word.endswith("name") and word[:-4] in NAME_QUALIFIERS for word in words):
        return True
    return "name" in words and set(words) - {"name"} <= NAME_QUALIFIERS


def _example_safe(text: str, kind: str) -> bool:
    if len(text) > MAX_EXAMPLE_CHARS or not text.isprintable() or _personal_value(text):
        return False
    if kind in ("boolean", "date", "datetime"):
        return True
    # seven digits or more, as text or as a number, may be a phone number written another way
    if sum(char.isdigit() for char in text) >= 7:
        return False
    return kind != "text" or not (_EMAIL.search(text) or _POSTCODE_WITHIN.search(text))


def _nested_personal(value: object) -> bool:
    """Whether anything inside a JSON list or object looks personal: a key naming personal
    data, as in {"full_name": ...}, or a key or value that would look personal on its own."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, inner in item.items():
                if _personal_name(str(key)):
                    return True
                stack.extend((str(key), inner))
        elif isinstance(item, list):
            stack.extend(item)
        else:
            seen = _classify(item, example=False)
            if seen is not None and seen[3]:
                return True
    return False


def _classify(value: object, example: bool = True) -> tuple[str, str, str | None, bool] | None:
    """(type, canonical form, the example it may be shown as, whether it looks personal), or
    None for a null. With example false no example is looked for: the column has its share."""
    if value is None:
        return None
    if isinstance(value, bool):
        text = "true" if value else "false"
        return "boolean", text, text, False
    if isinstance(value, int):
        text = str(value)
        # a phone number or a ZIP code may be stored as a number: five digits are withheld
        # even though they are as often an id, since a postcode shown cannot be taken back
        personal = _digits_personal(text)
        shown = example and not personal and _example_safe(text, "integer")
        return "integer", text, text if shown else None, personal
    if isinstance(value, float):
        text = repr(value)
        personal = value.is_integer() and _digits_personal(str(int(value)))
        shown = example and not personal and _example_safe(text, "number")
        return "number", text, text if shown else None, personal
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in NULL_WORDS:
            return None
        kind = _infer(text)
        personal = _personal_value(text) or (kind == "text" and _name_like(text))
        shown = example and not personal and _example_safe(text, kind)
        return kind, text, text if shown else None, personal
    if isinstance(value, (bytes, bytearray, memoryview)):
        return "text", "blob:" + hashlib.sha256(bytes(value)).hexdigest(), None, False
    # a JSON list or object is never shown: what it holds is looked at only to say whether it
    # is personal
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    return "text", text, None, _nested_personal(value)


# --- profiles --------------------------------------------------------------------------------


class _Column:
    def __init__(self, name: str, personal: bool) -> None:
        self.name = name
        self.personal = personal
        self.declared: str | None = None
        self.filled = 0
        self.types: set[str] = set()
        self.digests: set[bytes] = set()
        self.overflow = False
        self.examples: list[str] = []
        self.personal_hits = 0

    def add(self, value: object) -> None:
        seen = _classify(value, example=len(self.examples) < MAX_EXAMPLES)
        if seen is None:
            return
        kind, canonical, example, personal = seen
        self.filled += 1
        self.types.add(kind)
        if personal:
            self.personal_hits += 1
        digest = hashlib.blake2b(
            f"{kind}\x00{canonical}".encode("utf-8", "surrogatepass"), digest_size=8
        ).digest()
        if digest not in self.digests:
            if len(self.digests) < MAX_DISTINCT:
                self.digests.add(digest)
            else:
                self.overflow = True
        if example is not None and len(self.examples) < MAX_EXAMPLES and example not in self.examples:
            self.examples.append(example)

    def is_personal(self) -> bool:
        return self.personal or (self.personal_hits > 0 and self.personal_hits * 2 >= self.filled)

    def type(self) -> str:
        if len(self.types) == 1:
            return next(iter(self.types))
        if self.types and self.types <= {"integer", "number"}:
            return "number"
        if self.types and self.types <= {"date", "datetime"}:
            return "datetime"
        return "text"


def _column(raw: object, position: int) -> _Column:
    """A column named as it may appear in a Unit. A header that is itself personal-looking —
    an email address where a name should be — is replaced by the column's position."""
    name = " ".join(str(raw).split())
    if not name or _personal_value(name) or not name.isprintable():
        return _Column(f"column_{position}", personal=bool(name) and _personal_value(name))
    return _Column(_clip(name, MAX_NAME_CHARS), personal=_personal_name(name))


class _Profile:
    def __init__(self, budget: _Budget) -> None:
        self.budget = budget
        self.columns: list[_Column] = []
        self.keys: dict[str, _Column] = {}
        self.unprofiled: set[str] = set()
        self.width = 0
        self.rows = 0
        self.cells = 0
        self.truncated = False
        self.spent = False      # stopped by the artifact's limit rather than its own

    def full(self) -> bool:
        if self.budget.cells <= 0:
            self.spent = True
            return True
        return self.rows >= MAX_ROWS or self.cells >= MAX_CELLS

    def fixed(self, names: Sequence[object]) -> None:
        self.width = len(names)
        self.columns = [_column(name, position) for position, name in enumerate(names[:MAX_COLUMNS], 1)]

    def add_row(self, values: Sequence[object]) -> None:
        self.rows += 1
        self.cells += max(1, len(values))
        self.budget.cells -= max(1, min(len(values), len(self.columns)))
        for column, value in zip(self.columns, values, strict=False):
            column.add(value)

    def add_record(self, record: dict) -> None:
        self.rows += 1
        self.cells += max(1, len(record))
        self.budget.cells -= max(1, len(record))
        for key, value in record.items():
            column = self.keys.get(key)
            if column is None:
                if key in self.unprofiled:
                    continue
                self.width += 1
                if len(self.columns) >= MAX_COLUMNS:
                    if len(self.unprofiled) < MAX_DISTINCT:
                        self.unprofiled.add(key)
                    continue
                column = self.keys[key] = _column(key, len(self.columns) + 1)
                self.columns.append(column)
            column.add(value)


def _rate(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "n/a"


def _describe(column: _Column, rows: int) -> str:
    parts = [f"- {column.name}: {column.type()}"]
    if column.declared:
        parts.append(f"declared {column.declared}")
    personal = column.is_personal()
    if personal:
        parts.append("personal, values withheld")
    parts.append(f"nulls {_rate(rows - column.filled, rows)}")
    parts.append(
        f"distinct more than {MAX_DISTINCT}" if column.overflow
        else f"distinct ~{len(column.digests)}"
    )
    if column.examples and not personal:
        parts.append("examples " + ", ".join(json.dumps(e, ensure_ascii=False) for e in column.examples))
    return "; ".join(parts)


def _fit(lines: list[str]) -> str:
    body = "\n".join(lines)
    if len(body) <= MAX_BODY:
        return body
    room = MAX_BODY - 200
    kept: list[str] = []
    used = 0
    for line in lines:
        line = _clip(line, room)
        if used + len(line) + 1 > room:
            break
        kept.append(line)
        used += len(line) + 1
    kept.append(
        f"… {len(lines) - len(kept)} more lines not shown: a Unit's body is at most "
        f"{MAX_BODY} characters."
    )
    return "\n".join(kept)


def _schema_unit(artifact_id: str, title: str, facts: list[str], profile: _Profile,
                 location: Location, fmt: str) -> Unit:
    personal = [column.name for column in profile.columns if column.is_personal()]
    rows = (f"at least {profile.rows} (the scan stopped at its limit)" if profile.truncated
            else str(profile.rows))
    columns = str(profile.width)
    if profile.width > len(profile.columns):
        columns += f" (the first {len(profile.columns)} profiled)"
    lines = [*facts, f"Rows: {rows}", f"Columns: {columns}"]
    if profile.spent:
        lines.insert(len(facts), (
            f"The scan stopped at the artifact's limit of {MAX_TOTAL_CELLS} values across all "
            "its datasets."
        ))
    if personal:
        lines.append("Personal data, values withheld: " + ", ".join(personal))
    lines.append("")
    lines.extend(_describe(column, profile.rows) for column in profile.columns)
    tags = ["dataset", fmt]
    if personal:
        tags.append("personal")
    if profile.truncated:
        tags.append("truncated")
    return Unit(
        artifact_id=artifact_id, kind="data_schema", title=_clip(title, MAX_TITLE),
        body=_fit(lines), location=location, tags=tuple(tags),
    )


def _unparsed(artifact_id: str, path: str, reason: str, line: int | None = None,
              end: int | None = None) -> Unit:
    where = "the artifact" if path == "." else path
    return Unit(
        artifact_id=artifact_id, kind="knowledge", title=_clip(f"Not parsed: {where}", MAX_TITLE),
        body=_clip(reason, MAX_BODY),
        location=Location(path, line, end or line) if line else Location(path), tags=("unparsed",),
    )


# --- text files ------------------------------------------------------------------------------


def _read_text(path: Path) -> tuple[str, bool, list[str]]:
    """At most MAX_TEXT_BYTES of the file, cut back to its last whole line; whether it was cut;
    and what to say about how it was read."""
    with path.open("rb") as handle:
        data = handle.read(MAX_TEXT_BYTES + 1)
    facts: list[str] = []
    cut = len(data) > MAX_TEXT_BYTES
    if cut:
        data = data[: data.rfind(b"\n", 0, MAX_TEXT_BYTES) + 1]
        facts.append(f"Only the first {MAX_TEXT_BYTES} bytes were read.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
        facts.append("Not valid UTF-8: read as Latin-1.")
    return text, cut, facts


def _empty(cut: bool) -> str:
    return f"No complete line in the first {MAX_TEXT_BYTES} bytes." if cut else "The file is empty."


def _line_count(text: str) -> int:
    return text.count("\n") + (0 if text.endswith("\n") else 1)


def _dialect(text: str, fmt: str) -> type[csv.Dialect]:
    sample = text[:SNIFF_CHARS]
    if len(text) > SNIFF_CHARS:
        sample = sample[: sample.rfind("\n") + 1] or sample
    try:
        return csv.Sniffer().sniff(sample, delimiters="\t" if fmt == "tsv" else ",;|\t")
    except Exception:
        return csv.excel_tab if fmt == "tsv" else csv.excel


def _is_header(row: list[str]) -> bool:
    """The first row names the columns unless it looks like data: an empty, repeated, typed or
    personal-looking cell."""
    cells = [cell.strip() for cell in row]
    return all(cells) and len(set(cells)) == len(cells) and all(
        _infer(cell) == "text" and not _personal_value(cell) for cell in cells
    )


def _semantic_label(label: str) -> bool:
    """Whether a label names a column as only a header would: "First Name", "Product Name",
    "Email"."""
    words = [word.lower() for word in _WORDS.findall(label)]
    return "name" in words or _personal_name(label)


def _label_withheld(label: str) -> bool:
    """Whether a label from a first row reads as a person's name, like "Ada Lovelace", rather
    than as a column's name, like "First Name"."""
    return _name_like(label) and not _semantic_label(label)


def _header_is_a_record(profile: _Profile) -> bool:
    """Whether a first row taken for a header reads better as a record: one of its cells reads
    as a person's name and nothing says the row names the columns — none of its cells names a
    column as "First Name" or "Email" do, and no column below it holds numbers, dates or
    booleans. It is then read as data, so that the name is counted and withheld rather than
    shown as the name of a column, however few of the values below it are names."""
    columns = profile.columns
    return any(_label_withheld(column.name) for column in columns) and not any(
        _semantic_label(column.name) or (column.filled > 0 and column.type() != "text")
        for column in columns
    )


def _withhold_labels(profile: _Profile, facts: list[str]) -> None:
    """Number the columns whose names read as people's names — a header's, a record's keys or
    a table's columns — and say how many: a name that does head a column is still not shown."""
    withheld = 0
    for position, column in enumerate(profile.columns, 1):
        if _label_withheld(column.name):
            column.name = f"column_{position}"
            withheld += 1
    if withheld:
        facts.append(
            f"{withheld} column names are written like people's names and are withheld: those "
            "columns are numbered."
        )


def _delimited(artifact_id: str, rel: str, path: Path, fmt: str, budget: _Budget) -> list[Unit]:
    text, cut, facts = _read_text(path)
    if not text.strip():
        return [_unparsed(artifact_id, rel, _empty(cut))]
    dialect = _dialect(text, fmt)
    left = budget.cells
    profile, notes, started, named, ragged, last = _scan(
        artifact_id, rel, text, dialect, cut, budget, header=True
    )
    if named and _header_is_a_record(profile):
        budget.cells = left     # the first reading is not counted twice
        profile, notes, started, named, ragged, last = _scan(
            artifact_id, rel, text, dialect, cut, budget, header=False
        )
    if not started:
        return notes or [_unparsed(artifact_id, rel, _empty(cut))]
    heading = (
        f"Format: {fmt.upper()}, delimiter {json.dumps(dialect.delimiter)}, "
        + ("the first row names the columns." if named else "no header row: columns are numbered.")
    )
    facts.insert(0, heading)
    if named:
        _withhold_labels(profile, facts)
    if ragged:
        facts.append(f"{ragged} rows have a different number of fields from the first.")
    schema = _schema_unit(
        artifact_id, f"Data schema: {rel}", facts, profile, Location(rel, 1, max(last, 1)), fmt
    )
    return [schema, *notes]


def _scan(artifact_id: str, rel: str, text: str, dialect: type[csv.Dialect], cut: bool,
          budget: _Budget, header: bool) -> tuple[_Profile, list[Unit], bool, bool, int, int]:
    """(profile, notes, whether a row was found, whether the first row names the columns, rows
    of another width, the last line read) of a delimited text. The first row is taken for a
    header only when header is true and it looks like one."""
    # strict: malformed quoting, such as a quote never closed, stops the scan and is said so
    # rather than being read as a row
    reader = csv.reader(io.StringIO(text, newline=""), dialect, strict=True)
    profile = _Profile(budget)
    profile.truncated = cut
    notes: list[Unit] = []
    started = named = False
    ragged = last = read = 0
    try:
        for row in reader:
            read = reader.line_num
            if not row:
                continue
            if not started:
                started = True
                named = header and _is_header(row)
                profile.fixed(row if named else [""] * len(row))
                if named:
                    last = reader.line_num
                    continue
            if profile.full():
                profile.truncated = True
                break
            if len(row) != profile.width:
                ragged += 1
            profile.add_row(row)
            last = reader.line_num
    except csv.Error as exc:
        # the record that could not be read begins after the last one that could
        line = read + 1
        notes.append(_unparsed(
            artifact_id, rel, f"Stopped reading at line {line}: {exc}.", line,
            max(reader.line_num, line),
        ))
    return profile, notes, started, named, ragged, last


def _json_kind(value: object) -> str:
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, bool):
        return "a boolean"
    if value is None:
        return "null"
    return "a number"


def _json_array(artifact_id: str, rel: str, path: Path, fmt: str, budget: _Budget) -> list[Unit]:
    size = path.stat().st_size
    if size > MAX_TEXT_BYTES:
        return [_unparsed(
            artifact_id, rel,
            f"{size} bytes: a JSON document is read whole, and only up to {MAX_TEXT_BYTES} bytes.",
        )]
    text, cut, facts = _read_text(path)
    if not text.strip():
        return [_unparsed(artifact_id, rel, _empty(cut))]
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return [_unparsed(
            artifact_id, rel, f"Not valid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno}).",
            exc.lineno,
        )]
    except (RecursionError, ValueError):
        return [_unparsed(artifact_id, rel, "Not readable as JSON: nested too deeply or a number too long.")]
    if not isinstance(data, list):
        return [_unparsed(
            artifact_id, rel, f"The top-level JSON value is {_json_kind(data)}, not an array of records."
        )]
    profile = _Profile(budget)
    others = 0
    for item in data:
        if not isinstance(item, dict):
            others += 1
            continue
        if profile.full():
            profile.truncated = True
            break
        profile.add_record(item)
    if others and not profile.rows:
        return [_unparsed(artifact_id, rel, f"The array holds no objects, only {others} other values.")]
    facts.insert(0, "Format: JSON array of records.")
    if others:
        facts.append(f"{others} items of the array are not objects and were skipped.")
    _withhold_labels(profile, facts)
    return [_schema_unit(
        artifact_id, f"Data schema: {rel}", facts, profile, Location(rel, 1, _line_count(text)), fmt
    )]


def _json_lines(artifact_id: str, rel: str, path: Path, fmt: str, budget: _Budget) -> list[Unit]:
    text, cut, facts = _read_text(path)
    profile = _Profile(budget)
    profile.truncated = cut
    bad: list[int] = []
    bad_count = last = 0
    for number, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        if profile.full():
            profile.truncated = True
            break
        try:
            item = json.loads(line)
        except (RecursionError, ValueError):
            item = None
        if not isinstance(item, dict):
            bad_count += 1
            if len(bad) < 10:
                bad.append(number)
            continue
        profile.add_record(item)
        last = number
    if not profile.rows:
        if bad:
            return [_unparsed(
                artifact_id, rel, f"No line holds a JSON object: {bad_count} lines could not be read.",
                bad[0],
            )]
        return [_unparsed(artifact_id, rel, _empty(cut))]
    facts.insert(0, "Format: JSON Lines, one record per line.")
    _withhold_labels(profile, facts)
    units = [_schema_unit(
        artifact_id, f"Data schema: {rel}", facts, profile, Location(rel, 1, last), fmt
    )]
    if bad:
        lines = ", ".join(str(number) for number in bad) + (", …" if bad_count > len(bad) else "")
        units.append(_unparsed(
            artifact_id, rel,
            f"{bad_count} lines are not JSON objects and were skipped: lines {lines}.", bad[0],
        ))
    return units


# --- SQLite ----------------------------------------------------------------------------------


def _lenient_text(data: bytes) -> str:
    return data.decode("utf-8", "replace")


_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"|`[^`]*`|\[[^\]]*\]")


def _reason(exc: sqlite3.Error) -> str:
    """What went wrong, as SQLite says it, safe to show. SQLite quotes what it found in the
    database — a token of a malformed schema, a name, a value an expression failed on — so
    whatever it quotes is withheld: a database's own text never reaches a Unit through an
    error."""
    said = _QUOTED.sub("(withheld)", " ".join(str(exc).split()))
    said = "".join(char if char.isprintable() else "?" for char in said)
    return _clip(said, MAX_REASON_CHARS) or type(exc).__name__


def _sqlite(artifact_id: str, rel: str, path: Path, fmt: str, budget: _Budget) -> list[Unit]:
    with path.open("rb") as handle:
        magic = handle.read(len(SQLITE_MAGIC))
    if magic != SQLITE_MAGIC:
        return [_unparsed(artifact_id, rel, "Named like a database but has no SQLite header.")]
    uri = f"{path.resolve().as_uri()}?mode=ro&immutable=1"
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            return _database(artifact_id, rel, connection, budget)
    except sqlite3.Error as exc:
        return [_unparsed(artifact_id, rel, f"Not readable as a SQLite database: {_reason(exc)}.")]


def _database(artifact_id: str, rel: str, connection: sqlite3.Connection,
              budget: _Budget) -> list[Unit]:
    spent = 0

    def progress() -> int:
        nonlocal spent
        spent += 1
        budget.steps -= 1
        return int(exhausted())

    def exhausted() -> bool:
        return spent > SQLITE_STEPS or budget.steps < 0

    connection.text_factory = _lenient_text
    # a larger value is refused by SQLite rather than read, whatever the query asks of it
    connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_VALUE_BYTES)
    connection.set_progress_handler(progress, 1_000)
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA trusted_schema = OFF")
    # listed up to a bound, and only the start of each CREATE statement: enough to tell a
    # virtual table
    entries = connection.execute(
        "SELECT type, name, substr(sql, 1, 32) FROM sqlite_master"
        " WHERE type IN ('table', 'view') AND substr(name, 1, 7) <> 'sqlite_'"
        " ORDER BY name LIMIT ?",
        (MAX_SCHEMA_ENTRIES + 1,),
    ).fetchall()
    unlisted = len(entries) > MAX_SCHEMA_ENTRIES
    tables: list[str] = []
    skipped: list[str] = []
    for kind, name, sql in entries[:MAX_SCHEMA_ENTRIES]:
        name = str(name)
        if kind == "view":
            skipped.append(f"view {_shown(name)} (reading it would run SQL stored in the database)")
        elif str(sql or "").lstrip().upper().startswith("CREATE VIRTUAL"):
            skipped.append(f"virtual table {_shown(name)} (reading it needs a module)")
        else:
            tables.append(name)
    units: list[Unit] = []
    unread = 0
    for name in tables[:MAX_TABLES]:
        if budget.spent():
            unread += 1
            continue
        spent = 0
        try:
            units.extend(_table(artifact_id, rel, connection, name, exhausted, budget))
        except sqlite3.Error as exc:
            units.append(_unparsed(
                artifact_id, rel, f"Table {_shown(name)} could not be read: {_reason(exc)}."
            ))
    if unread:
        units.append(_unparsed(
            artifact_id, rel,
            f"{unread} more tables were not read: the artifact's scan limit was reached.",
        ))
    if len(tables) > MAX_TABLES:
        units.append(_unparsed(
            artifact_id, rel,
            f"{len(tables) - MAX_TABLES} more tables were not read: at most {MAX_TABLES} are read "
            "per database.",
        ))
    if unlisted:
        units.append(_unparsed(
            artifact_id, rel,
            f"The database holds more than {MAX_SCHEMA_ENTRIES} tables and views: only the first "
            f"{MAX_SCHEMA_ENTRIES}, in name order, were looked at.",
        ))
    if skipped:
        units.append(_unparsed(artifact_id, rel, "Not read: " + "; ".join(skipped) + "."))
    if not tables and not skipped:
        units.append(_unparsed(artifact_id, rel, "The database holds no tables."))
    return units


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _table(artifact_id: str, rel: str, connection: sqlite3.Connection, name: str,
           exhausted: Callable[[], bool], budget: _Budget) -> list[Unit]:
    [(width,)] = connection.execute(
        "SELECT count(*) FROM pragma_table_info(?)", (name,)
    ).fetchall()
    declared = connection.execute(
        "SELECT name, type FROM pragma_table_info(?) ORDER BY cid LIMIT ?", (name, MAX_COLUMNS)
    ).fetchall()
    # only the profiled columns, and of a text or blob value only its first MAX_CELL_CHARS
    # characters or bytes and one more, to know that it was longer
    fetched = ", ".join(
        f"CASE WHEN typeof({quoted}) IN ('text', 'blob') "
        f"THEN substr({quoted}, 1, {MAX_CELL_CHARS + 1}) ELSE {quoted} END"
        for quoted in (_quote(str(raw)) for raw, _ in declared)
    )
    cursor = connection.execute(f"SELECT {fetched} FROM {_quote(name)} LIMIT ?", (MAX_ROWS + 1,))
    profile = _Profile(budget)
    profile.fixed([str(raw) for raw, _ in declared])
    profile.width = width
    for column, (_, kind) in zip(profile.columns, declared, strict=False):
        column.declared = _shown(str(kind)) if kind else None
    facts = [f"Format: SQLite table {_shown(name)}, opened read-only."]
    _withhold_labels(profile, facts)
    cut = 0
    try:
        for row in cursor:
            if profile.full():
                profile.truncated = True
                break
            values = list(row)
            for index, value in enumerate(values):
                if isinstance(value, str) and len(value) > MAX_CELL_CHARS:
                    values[index] = value[:MAX_CELL_CHARS] + "…"
                elif isinstance(value, bytes) and len(value) > MAX_CELL_CHARS:
                    values[index] = value[:MAX_CELL_CHARS]
                else:
                    continue
                cut += 1
            profile.add_row(values)
    except sqlite3.OperationalError:
        if not exhausted():
            raise
        profile.truncated = True
        facts.append("The scan stopped at its work limit.")
    notes: list[Unit] = []
    if cut:
        facts.append(f"{cut} values were read only up to {MAX_CELL_CHARS} characters or bytes.")
        notes.append(_unparsed(
            artifact_id, rel,
            f"Table {_shown(name)}: {cut} values longer than {MAX_CELL_CHARS} characters or bytes "
            "were read only up to that size, so the distinct counts of their columns are "
            "estimates.",
        ))
    schema = _schema_unit(
        artifact_id, f"Data schema: {rel} table {_shown(name)}", facts, profile, Location(rel),
        "sqlite",
    )
    return [schema, *notes]


_READERS: dict[str, Callable[[str, str, Path, str, _Budget], list[Unit]]] = {
    "csv": _delimited, "tsv": _delimited, "json": _json_array, "jsonl": _json_lines,
    "sqlite": _sqlite,
}
