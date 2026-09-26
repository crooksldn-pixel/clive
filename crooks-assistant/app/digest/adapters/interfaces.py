"""The interfaces adapter: API and tool specifications — OpenAPI and Swagger, GraphQL SDL, JSON
Schema and MCP tool manifests — read out of a quarantined artifact and into Units.

Each operation, query, mutation and tool becomes a capability Unit tagged 'read', 'write' or
'unknown'; each schema and type becomes an interface Unit. The access tag is what CLIVE's action
gate reads, so it is never guessed downwards: an HTTP method that changes things, a GraphQL
mutation and a tool whose own annotations say it changes things are 'write', and a tool that
says nothing about itself is 'unknown', never 'read'.

Reading only: nothing here executes, imports or installs what it reads, follows a symbolic link
or opens anything but a regular file, and every size and count is bounded. A file that cannot
be read is not an error — it becomes a knowledge Unit tagged 'unparsed' that says why — so
decompose never raises on what it finds. YAML is read by the small reader below, which accepts
the plain mappings, lists and scalars OpenAPI files use and refuses the rest."""

from __future__ import annotations

import bisect
import inspect
import json
import os
import re
import stat
from dataclasses import dataclass
from json.decoder import scanstring
from pathlib import Path, PurePosixPath
from typing import Any, NamedTuple

from app.digest.model import MAX_BODY, MAX_TAG, MAX_TITLE, Location, Unit

NAME = "interfaces"
HANDLES = ("api_spec", "tool_spec")
ACCESS = ("read", "write", "unknown")   # every capability carries exactly one

MAX_ENTRIES = 20_000            # directory entries looked at while finding specifications
MAX_FILES = 200                 # specification files read from one artifact
MAX_FILE_BYTES = 2_000_000      # one file
MAX_TOTAL_BYTES = 20_000_000    # all of them
MAX_UNITS = 5_000               # units returned for one artifact
MAX_DEPTH = 64                  # nesting, in every format
MAX_TOKENS = 200_000            # one GraphQL file
MAX_SKIPPED = 100               # malformed tools or parameters said of one by one in one list;
                                # more are counted

_JSON = (".json",)
_YAML = (".yaml", ".yml")
_GRAPHQL = (".graphql", ".graphqls", ".gql")
_SUFFIXES = _JSON + _YAML + _GRAPHQL
_SKIPPED_DIRS = frozenset({".git", ".hg", ".svn", "node_modules", "__pycache__"})
_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_WRITE_METHODS = frozenset({"post", "put", "patch", "delete"})
_OPENAPI_YAML = re.compile(r"""^["']?(?:openapi|swagger)["']?[ \t]*:""", re.MULTILINE)
_SCHEMA_KEYWORDS = frozenset(
    {"type", "properties", "items", "$ref", "$defs", "definitions", "oneOf", "anyOf", "allOf",
     "enum", "const"}
)
_METASCHEMA = re.compile(
    r"https?://json-schema\.org/(?:draft-0[0-9]/|draft/[0-9]{4}-[0-9]{2}/)?(?:hyper-)?schema#?"
)
_GQL_TYPES = ("type", "interface", "input", "enum", "union", "scalar")


class _Unparsed(Exception):
    """What could not be read, and why, in the words the 'unparsed' Unit carries."""


class _Map(dict):
    """A mapping read from a file, with the lines it spans and those each of its entries does."""

    __slots__ = ("lines", "spans")

    def __init__(self) -> None:
        super().__init__()
        self.spans: dict[str, tuple[int, int]] = {}


class _Seq(list):
    """A list read from a file, with the lines it spans and those each of its items does."""

    __slots__ = ("lines", "spans")

    def __init__(self) -> None:
        super().__init__()
        self.spans: dict[int, tuple[int, int]] = {}


# --- units -------------------------------------------------------------------------------------


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _word(value: Any) -> str:
    """A scalar as one line of text; nothing for a mapping, a list or null."""
    if value is None or isinstance(value, (dict, list)):
        return ""
    return " ".join(str(value).split())


def _prose(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def _lines(node: Any) -> tuple[int | None, int | None]:
    lines = getattr(node, "lines", None)
    return lines if lines else (None, None)


def _entry(container: Any, key: Any) -> tuple[int | None, int | None]:
    """The lines of one entry of a mapping or list read from a file: its value's own, if the
    value is a mapping or a list, and otherwise the entry's — so a scalar is placed too."""
    own = _lines(container[key])
    if own[0] is not None:
        return own
    return getattr(container, "spans", {}).get(key, (None, None))


def _unit(artifact_id: str, kind: str, title: str, body: str, path: str,
          lines: tuple[int | None, int | None], tags: tuple[str, ...] | list[str]) -> Unit:
    clean: list[str] = []
    for tag in tags:
        text = " ".join(str(tag).split())[:MAX_TAG]
        if text and text not in clean:
            clean.append(text)
    return Unit(
        artifact_id=artifact_id, kind=kind,
        title=_clip(" ".join(title.split()) or "untitled", MAX_TITLE),
        body=_clip(body, MAX_BODY), location=Location(path, *lines), tags=tuple(clean),
    )


def _unparsed(artifact_id: str, path: str, reason: str,
              lines: tuple[int | None, int | None] = (None, None)) -> Unit:
    return _unit(artifact_id, "knowledge", f"Unparsed: {path}", reason, path, lines, ("unparsed",))


class _File:
    """The Units read out of one file, each located in it."""

    def __init__(self, artifact_id: str, path: str) -> None:
        self.artifact_id = artifact_id
        self.path = path
        self.units: list[Unit] = []
        self.whole: tuple[int | None, int | None] = (None, None)    # every line of the file

    def add(self, kind: str, title: str, body: str, lines: tuple[int | None, int | None],
            tags: tuple[str, ...] | list[str]) -> None:
        self.units.append(_unit(self.artifact_id, kind, title, body, self.path, lines, tags))

    def unparsed(self, reason: str, lines: tuple[int | None, int | None] = (None, None)) -> None:
        self.units.append(_unparsed(self.artifact_id, self.path, reason, lines))


# --- JSON, with lines --------------------------------------------------------------------------

_JSON_SPACE = re.compile(r"[ \t\n\r]*")
_JSON_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?")


class _Json:
    """JSON, strictly, keeping the lines each object and array spans."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.breaks = [match.start() for match in re.finditer("\n", text)]

    def parse(self) -> Any:
        value, end = self._value(0, 0)
        end = self._space(end)
        if end != len(self.text):
            raise _Unparsed(f"line {self._line(end)}: unexpected text after the JSON value")
        return value

    def _line(self, position: int) -> int:
        return bisect.bisect_left(self.breaks, position) + 1

    def _space(self, position: int) -> int:
        return _JSON_SPACE.match(self.text, position).end()

    def _value(self, position: int, depth: int) -> tuple[Any, int]:
        position = self._space(position)
        if depth > MAX_DEPTH:
            raise _Unparsed(f"line {self._line(position)}: nested deeper than {MAX_DEPTH} levels")
        char = self.text[position:position + 1]
        if char == "{":
            return self._object(position, depth)
        if char == "[":
            return self._array(position, depth)
        if char == '"':
            return scanstring(self.text, position + 1)
        for word, value in (("true", True), ("false", False), ("null", None)):
            if self.text.startswith(word, position):
                return value, position + len(word)
        match = _JSON_NUMBER.match(self.text, position)
        if match is None:
            raise _Unparsed(f"line {self._line(position)}: expected a JSON value")
        token = match.group()
        if len(token) > 64:
            raise _Unparsed(f"line {self._line(position)}: a number too long to read")
        number = int(token) if token.lstrip("-").isdigit() else float(token)
        return number, match.end()

    def _object(self, start: int, depth: int) -> tuple[_Map, int]:
        node = _Map()
        position = self._space(start + 1)
        if not self.text.startswith("}", position):
            while True:
                position = self._space(position)
                if not self.text.startswith('"', position):
                    raise _Unparsed(f"line {self._line(position)}: expected a quoted key")
                first = self._line(position)
                key, position = scanstring(self.text, position + 1)
                position = self._space(position)
                if not self.text.startswith(":", position):
                    raise _Unparsed(f"line {self._line(position)}: expected ':'")
                value, position = self._value(position + 1, depth + 1)
                node[key] = value
                node.spans[key] = (first, self._line(position - 1))
                position = self._space(position)
                if not self.text.startswith(",", position):
                    break
                position += 1
            if not self.text.startswith("}", position):
                raise _Unparsed(f"line {self._line(position)}: expected ',' or '}}'")
        node.lines = (self._line(start), self._line(position))
        return node, position + 1

    def _array(self, start: int, depth: int) -> tuple[_Seq, int]:
        node = _Seq()
        position = self._space(start + 1)
        if not self.text.startswith("]", position):
            while True:
                first = self._line(self._space(position))
                value, position = self._value(position, depth + 1)
                node.spans[len(node)] = (first, self._line(position - 1))
                node.append(value)
                position = self._space(position)
                if not self.text.startswith(",", position):
                    break
                position += 1
            if not self.text.startswith("]", position):
                raise _Unparsed(f"line {self._line(position)}: expected ',' or ']'")
        node.lines = (self._line(start), self._line(position))
        return node, position + 1


# --- the YAML subset OpenAPI files use ---------------------------------------------------------

_YAML_INT = re.compile(r"[-+]?[0-9]+")
_YAML_FLOAT = re.compile(
    r"[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?|[-+]?[0-9]+[eE][-+]?[0-9]+"
)
_BEYOND = "is beyond the YAML this adapter reads"


class _Line(NamedTuple):
    number: int     # from 1
    indent: int
    text: str       # without its indentation or comment


def _is_item(text: str) -> bool:
    return text == "-" or text.startswith(("- ", "-\t"))


def _quote_end(text: str, start: int) -> int | None:
    """Where the quoted scalar opening at start closes, or None if it does not on this line."""
    quote = text[start]
    index = start + 1
    while index < len(text):
        char = text[index]
        if quote == '"' and char == "\\":
            index += 2
            continue
        if char == quote:
            if quote == "'" and text[index + 1:index + 2] == "'":
                index += 2
                continue
            return index
        index += 1
    return None


def _unquote(token: str) -> str:
    if token[0] == "'":
        return token[1:-1].replace("''", "'")
    try:
        return json.loads(token, strict=False)
    except ValueError:
        raise _Unparsed(f"an escape in {_clip(token, 80)} {_BEYOND}") from None


def _strip_comment(text: str) -> str:
    quote = None
    index = 0
    while index < len(text):
        char = text[index]
        if quote:
            if quote == '"' and char == "\\":
                index += 2
                continue
            if char == quote:
                if quote == "'" and text[index + 1:index + 2] == "'":
                    index += 2
                    continue
                quote = None
        elif char in "\"'" and (index == 0 or text[index - 1] in " \t[{,"):
            quote = char
        elif char == "#" and (index == 0 or text[index - 1] in " \t"):
            return text[:index].rstrip()
        index += 1
    return text.rstrip()


def _split_pair(text: str) -> tuple[str, str] | None:
    """'key: value' as its key and the rest; None if the line is not a mapping entry."""
    if text[:1] in ("\"", "'"):
        end = _quote_end(text, 0)
        if end is None:
            return None
        after = text[end + 1:].lstrip(" ")
        if not after.startswith(":") or after[1:2] not in ("", " ", "\t"):
            return None
        return _unquote(text[:end + 1]), after[1:].strip()
    if not text or text[0] in "[{?&*!|>%@`":
        return None
    index = 0
    while True:
        index = text.find(":", index)
        if index < 0:
            return None
        if text[index + 1:index + 2] in ("", " ", "\t"):
            break
        index += 1
    key = text[:index].rstrip()
    return (key, text[index + 1:].strip()) if key else None


def _plain(text: str) -> Any:
    if text in ("~", "null", "Null", "NULL"):
        return None
    if text in ("true", "True", "TRUE"):
        return True
    if text in ("false", "False", "FALSE"):
        return False
    if len(text) <= 64:
        if _YAML_INT.fullmatch(text):
            return int(text)
        if _YAML_FLOAT.fullmatch(text):
            return float(text)
    return text


def _scalar(text: str, number: int) -> Any:
    if text[0] in "\"'":
        end = _quote_end(text, 0)
        if end is None:
            raise _Unparsed(f"line {number}: a quoted scalar that does not close on its line {_BEYOND}")
        if text[end + 1:].strip():
            raise _Unparsed(f"line {number}: unexpected text after a quoted scalar")
        return _unquote(text[:end + 1])
    if text[0] in "&*!%@`":
        raise _Unparsed(f"line {number}: anchors, aliases, tags and reserved indicators {_BEYOND}")
    return _plain(text)


def _fold(lines: list[str]) -> str:
    text = lines[0]
    for index in range(1, len(lines)):
        before, line = lines[index - 1], lines[index]
        if not line:
            text += "\n"
        elif not before:
            text += line
        elif line[0] in " \t" or before[0] in " \t":
            text += "\n" + line
        else:
            text += " " + line
    return text


class _Flow:
    """A flow list or mapping — [a, b] or {a: b} — that opens and closes on one line."""

    def __init__(self, text: str, number: int) -> None:
        self.text = text
        self.number = number
        self.position = 0

    def parse(self) -> Any:
        value = self._node(0, key=False)
        self._space()
        if self.position != len(self.text):
            raise _Unparsed(f"line {self.number}: unexpected text after a flow collection")
        return value

    def _space(self) -> None:
        while self.text[self.position:self.position + 1] in (" ", "\t"):
            self.position += 1

    def _node(self, depth: int, *, key: bool) -> Any:
        if depth > MAX_DEPTH:
            raise _Unparsed(f"line {self.number}: nested deeper than {MAX_DEPTH} levels")
        self._space()
        char = self.text[self.position:self.position + 1]
        if char in ("[", "{") and not key:
            return self._collection(depth)
        if char in ("\"", "'"):
            end = _quote_end(self.text, self.position)
            if end is None:
                raise _Unparsed(f"line {self.number}: a quoted scalar that does not close on its line {_BEYOND}")
            token = self.text[self.position:end + 1]
            self.position = end + 1
            return _unquote(token)
        start = self.position
        while self.position < len(self.text):
            char = self.text[self.position]
            after = self.text[self.position + 1:self.position + 2]
            if char in ",[]{}" or (char == ":" and after in ("", " ", ",", "]", "}")):
                break
            self.position += 1
        token = self.text[start:self.position].strip()
        if not token:
            raise _Unparsed(f"line {self.number}: an empty entry in a flow collection")
        return token if key else _scalar(token, self.number)

    def _collection(self, depth: int) -> _Map | _Seq:
        close = "]" if self.text[self.position] == "[" else "}"
        node: _Map | _Seq = _Seq() if close == "]" else _Map()
        node.lines = (self.number, self.number)
        self.position += 1
        while True:
            self._space()
            char = self.text[self.position:self.position + 1]
            if char == close:
                self.position += 1
                return node
            if not char:
                raise _Unparsed(f"line {self.number}: a flow collection that does not close on its line {_BEYOND}")
            if isinstance(node, _Map):
                name = self._node(depth + 1, key=True)
                self._space()
                if self.text[self.position:self.position + 1] != ":":
                    raise _Unparsed(f"line {self.number}: expected ':' in a flow mapping")
                self.position += 1
                node[name] = self._node(depth + 1, key=False)
                node.spans[name] = (self.number, self.number)
            else:
                node.spans[len(node)] = (self.number, self.number)
                node.append(self._node(depth + 1, key=False))
            self._space()
            char = self.text[self.position:self.position + 1]
            if char == ",":
                self.position += 1
            elif char != close:
                raise _Unparsed(f"line {self.number}: expected ',' or '{close}' in a flow collection")


class _Yaml:
    """The YAML OpenAPI and Swagger files are written in: block mappings and lists; plain,
    quoted, literal and folded scalars; one-line flow lists and mappings; and comments.
    Anchors, aliases, tags, complex keys, multi-line flow or quoted scalars, more than one
    document and tab indentation are refused rather than guessed at. Nothing is constructed
    but mappings, lists, strings, numbers, booleans and null."""

    def __init__(self, text: str) -> None:
        self.lines = [line.rstrip("\r") for line in text.split("\n")]
        self.index = 0
        self.started = False
        self.last = 0       # the last line consumed, from 1

    def parse(self) -> Any:
        value = self._block(-1, 0)
        extra = self._peek()
        if extra is not None:
            raise _Unparsed(f"line {extra.number}: unexpected indentation")
        return value

    def _peek(self) -> _Line | None:
        while self.index < len(self.lines):
            raw = self.lines[self.index]
            number = self.index + 1
            stripped = raw.strip()
            if not stripped or stripped.startswith("#"):
                self.index += 1
                continue
            if raw.startswith("---") and raw[3:4] in ("", " ", "\t"):
                if self.started or _strip_comment(raw[3:]).strip():
                    raise _Unparsed(f"line {number}: more than one document, or content after '---', {_BEYOND}")
                self.started = True
                self.index += 1
                continue
            if raw.startswith(("%", "...")):
                raise _Unparsed(f"line {number}: directives and document ends {_BEYOND}")
            text = raw.lstrip(" ")
            if text.startswith("\t"):
                raise _Unparsed(f"line {number}: tab indentation {_BEYOND}")
            self.started = True
            return _Line(number, len(raw) - len(text), _strip_comment(text))
        return None

    def _block(self, parent: int, depth: int) -> Any:
        if depth > MAX_DEPTH:
            raise _Unparsed(f"line {self.index + 1}: nested deeper than {MAX_DEPTH} levels")
        line = self._peek()
        if line is None or line.indent <= parent:
            return None
        if _is_item(line.text):
            return self._sequence(line.indent, depth)
        return self._mapping(line.indent, depth)

    def _mapping(self, indent: int, depth: int) -> _Map:
        node = _Map()
        first = 0
        while (line := self._peek()) is not None and line.indent >= indent:
            if line.indent > indent or _is_item(line.text):
                raise _Unparsed(f"line {line.number}: unexpected indentation")
            pair = _split_pair(line.text)
            if pair is None:
                raise _Unparsed(f"line {line.number}: expected 'key: value'; anything else here {_BEYOND}")
            self.index += 1
            self.last = line.number
            first = first or line.number
            key, rest = pair
            value = self._value(rest, indent, line.number, depth + 1)
            if isinstance(value, (_Map, _Seq)):
                value.lines = (line.number, value.lines[1])    # a value spans from its key
            node[key] = value
            node.spans[key] = (line.number, self.last)
        node.lines = (first or self.last, self.last)
        return node

    def _sequence(self, indent: int, depth: int) -> _Seq:
        node = _Seq()
        first = 0
        while (line := self._peek()) is not None and line.indent >= indent:
            if line.indent > indent:
                raise _Unparsed(f"line {line.number}: unexpected indentation")
            if not _is_item(line.text):
                break
            first = first or line.number
            rest = line.text[1:].lstrip(" \t")
            if rest and (_is_item(rest) or (rest[0] not in "[{|>" and _split_pair(rest) is not None)):
                # "- key: value" or "- - item": the item is a block that begins after the dash,
                # so the line is read again as that block at the column it begins in.
                column = line.indent + len(line.text) - len(rest)
                self.lines[self.index] = " " * column + rest
                item = self._block(indent, depth + 1)
            else:
                self.index += 1
                self.last = line.number
                if rest:
                    item = self._value(rest, indent, line.number, depth + 1)
                else:
                    item = self._block(indent, depth + 1)
            node.spans[len(node)] = (line.number, self.last)
            node.append(item)
        node.lines = (first or self.last, self.last)
        return node

    def _value(self, rest: str, indent: int, number: int, depth: int) -> Any:
        if not rest:
            line = self._peek()
            if line is not None and line.indent == indent and _is_item(line.text):
                return self._sequence(indent, depth)
            return self._block(indent, depth)
        if rest[0] in "|>":
            return self._literal(rest, indent, number)
        if rest[0] in "[{":
            return _Flow(rest, number).parse()
        return _scalar(rest, number)

    def _literal(self, header: str, indent: int, number: int) -> str:
        match = re.fullmatch(r"([|>])([-+]?)", header)
        if match is None:
            raise _Unparsed(f"line {number}: the block scalar header {header!r} {_BEYOND}")
        style, chomping = match.groups()
        lines: list[str] = []
        width = None
        while self.index < len(self.lines):
            raw = self.lines[self.index]
            if raw.strip():
                spaces = len(raw) - len(raw.lstrip(" "))
                if width is None:
                    if spaces <= indent:
                        break
                    width = spaces
                if spaces < width:
                    break
                lines.append(raw[width:])
                self.last = self.index + 1
            else:
                lines.append("")
            self.index += 1
        trailing = 0
        while lines and not lines[-1]:
            lines.pop()
            trailing += 1
        if not lines:
            return ""
        text = "\n".join(lines) if style == "|" else _fold(lines)
        if chomping == "-":
            return text
        return text + "\n" * (trailing + 1 if chomping == "+" else 1)


# --- GraphQL SDL -------------------------------------------------------------------------------

_GQL_NAME = re.compile(r"[_A-Za-z][_0-9A-Za-z]*")
_GQL_NUMBER = re.compile(r"-?[0-9]+(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?")


class _Token(NamedTuple):
    kind: str       # name, number, string or punct
    value: str
    line: int


def _gql_tokens(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    index, line, size = 0, 1, len(text)
    while index < size:
        if len(tokens) > MAX_TOKENS:
            raise _Unparsed(f"line {line}: more than {MAX_TOKENS} tokens in one file")
        char = text[index]
        if char == "\n":
            line += 1
            index += 1
        elif char in " \t\r,﻿":
            index += 1
        elif char == "#":
            end = text.find("\n", index)
            index = size if end < 0 else end
        elif text.startswith('"""', index):
            end = index + 3
            while True:
                end = text.find('"""', end)
                if end < 0:
                    raise _Unparsed(f"line {line}: a block string that does not end")
                if text[end - 1] != "\\":
                    break
                end += 3
            value = inspect.cleandoc(text[index + 3:end].replace('\\"""', '"""'))
            tokens.append(_Token("string", value, line))
            line += text.count("\n", index, end)
            index = end + 3
        elif char == '"':
            end = index + 1
            while end < size and text[end] not in '"\n':
                end += 2 if text[end] == "\\" and text[end + 1:end + 2] not in ("", "\n") else 1
            if end >= size or text[end] != '"':
                raise _Unparsed(f"line {line}: a string that does not end on its line")
            try:
                value = json.loads(text[index:end + 1])
            except ValueError:
                value = text[index + 1:end]
            tokens.append(_Token("string", value, line))
            index = end + 1
        elif text.startswith("...", index):
            tokens.append(_Token("punct", "...", line))
            index += 3
        elif char in "!$&():=@[]{}|":
            tokens.append(_Token("punct", char, line))
            index += 1
        elif match := _GQL_NAME.match(text, index):
            tokens.append(_Token("name", match.group(), line))
            index = match.end()
        elif match := _GQL_NUMBER.match(text, index):
            tokens.append(_Token("number", match.group(), line))
            index = match.end()
        else:
            raise _Unparsed(f"line {line}: unexpected character {char!r}")
    return tokens


def _render(token: _Token) -> str:
    return json.dumps(token.value, ensure_ascii=False) if token.kind == "string" else token.value


@dataclass
class _GqlField:
    name: str
    signature: str                      # name(argument: Type): Type
    description: str
    arguments: list[tuple[str, str]]    # (argument: Type, description)
    lines: tuple[int, int]


@dataclass
class _GqlType:
    keyword: str                        # _GQL_TYPES
    name: str
    header: str                         # [extend] keyword Name [implements A & B]
    description: str
    fields: list[_GqlField]
    members: list[str]                  # an enum's values or a union's types
    lines: tuple[int, int]


class _Sdl:
    """GraphQL's schema definition language: type, interface, input, enum, union and scalar
    definitions and their extensions, the schema's root operation types, and directive
    definitions. An executable document — a query rather than a schema — is refused."""

    def __init__(self, text: str) -> None:
        self.tokens = _gql_tokens(text)
        self.index = 0
        self.roots: dict[str, str] = {}
        self.types: list[_GqlType] = []
        while self.index < len(self.tokens):
            self._definition()

    def _at(self, value: str) -> bool:
        if self.index >= len(self.tokens):
            return False
        token = self.tokens[self.index]
        return token.kind in ("name", "punct") and token.value == value

    def _take(self, kind: str | None = None, value: str | None = None) -> _Token:
        if self.index >= len(self.tokens):
            raise _Unparsed(f"the schema ends where {value or kind or 'more'} was expected")
        token = self.tokens[self.index]
        if (kind is not None and token.kind != kind) or (
            value is not None and (token.value != value or token.kind == "string")
        ):
            raise _Unparsed(f"line {token.line}: expected {value or kind}, found {_clip(token.value, 80)!r}")
        self.index += 1
        return token

    def _description(self) -> str:
        if self.index < len(self.tokens) and self.tokens[self.index].kind == "string":
            return self._take().value.strip()
        return ""

    def _definition(self) -> None:
        start = self.tokens[self.index].line
        description = self._description()
        extend = self._at("extend")
        if extend:
            self._take()
        keyword = self._take("name")
        word = keyword.value
        if word == "schema":
            self._directives()
            if self._at("{"):
                self._take()
                while not self._at("}"):
                    operation = self._take("name").value
                    self._take(value=":")
                    self.roots[operation] = self._take("name").value
                self._take(value="}")
            return
        if word == "directive":
            self._take(value="@")
            self._take("name")
            if self._at("("):
                self._arguments()
            if self._at("repeatable"):
                self._take()
            self._take(value="on")
            if self._at("|"):
                self._take()
            self._take("name")
            while self._at("|"):
                self._take()
                self._take("name")
            return
        if word not in _GQL_TYPES:
            raise _Unparsed(
                f"line {keyword.line}: {_clip(word, 80)!r} does not begin a type definition; "
                "this adapter reads schemas, not queries"
            )
        name = self._take("name").value
        header = f"{'extend ' if extend else ''}{word} {name}"
        if word in ("type", "interface") and self._at("implements"):
            self._take()
            if self._at("&"):
                self._take()
            implemented = [self._take("name").value]
            while self._at("&"):
                self._take()
                implemented.append(self._take("name").value)
            header += " implements " + " & ".join(implemented)
        self._directives()
        fields: list[_GqlField] = []
        members: list[str] = []
        if word in ("type", "interface", "input") and self._at("{"):
            fields = self._fields(word == "input")
        elif word == "enum" and self._at("{"):
            self._take()
            while not self._at("}"):
                self._description()
                members.append(self._take("name").value)
                self._directives()
            self._take(value="}")
        elif word == "union" and self._at("="):
            self._take()
            if self._at("|"):
                self._take()
            members.append(self._take("name").value)
            while self._at("|"):
                self._take()
                members.append(self._take("name").value)
        end = self.tokens[self.index - 1].line
        self.types.append(_GqlType(word, name, header, description, fields, members, (start, end)))

    def _fields(self, is_input: bool) -> list[_GqlField]:
        self._take(value="{")
        fields: list[_GqlField] = []
        while not self._at("}"):
            if self.index >= len(self.tokens):
                raise _Unparsed("the schema ends inside a definition")
            start = self.tokens[self.index].line
            description = self._description()
            name = self._take("name").value
            arguments = self._arguments() if self._at("(") else []
            self._take(value=":")
            kind = self._type(0)
            if is_input and self._at("="):
                self._take()
                kind += " = " + self._value()
            self._directives()
            listed = ", ".join(signature for signature, _ in arguments)
            signature = f"{name}({listed}): {kind}" if arguments else f"{name}: {kind}"
            end = self.tokens[self.index - 1].line
            fields.append(_GqlField(name, signature, description, arguments, (start, end)))
        self._take(value="}")
        return fields

    def _arguments(self) -> list[tuple[str, str]]:
        self._take(value="(")
        arguments: list[tuple[str, str]] = []
        while not self._at(")"):
            description = self._description()
            name = self._take("name").value
            self._take(value=":")
            kind = self._type(0)
            if self._at("="):
                self._take()
                kind += " = " + self._value()
            self._directives()
            arguments.append((f"{name}: {kind}", " ".join(description.split())))
        self._take(value=")")
        return arguments

    def _type(self, depth: int) -> str:
        if depth > MAX_DEPTH:
            raise _Unparsed(f"line {self.tokens[self.index - 1].line}: nested deeper than {MAX_DEPTH} levels")
        if self._at("["):
            self._take()
            text = f"[{self._type(depth + 1)}]"
            self._take(value="]")
        else:
            text = self._take("name").value
        if self._at("!"):
            self._take()
            text += "!"
        return text

    def _value(self) -> str:
        token = self._take()
        if token.kind == "punct" and token.value in ("[", "{"):
            close = "]" if token.value == "[" else "}"
            parts, depth = [token.value], 1
            while depth:
                inner = self._take()
                if inner.kind == "punct" and inner.value == token.value:
                    depth += 1
                elif inner.kind == "punct" and inner.value == close:
                    depth -= 1
                parts.append(_render(inner))
            return " ".join(parts)
        if token.kind == "punct" and token.value == "$":
            return "$" + self._take("name").value
        return _render(token)

    def _directives(self) -> None:
        while self._at("@"):
            self._take()
            self._take("name")
            if self._at("("):
                self._take()
                depth = 1
                while depth:
                    token = self._take()
                    if token.kind == "punct" and token.value == "(":
                        depth += 1
                    elif token.kind == "punct" and token.value == ")":
                        depth -= 1


def _graphql(out: _File, schema: _Sdl, roots: dict[str, str]) -> None:
    # Built so that a type named as both a mutation root and another root is a mutation.
    operations = {
        roots.get("subscription", "Subscription"): ("subscription", "read"),
        roots.get("query", "Query"): ("query", "read"),
        roots.get("mutation", "Mutation"): ("mutation", "write"),
    }
    for kind in schema.types:
        if kind.keyword == "type" and kind.name in operations:
            operation, access = operations[kind.name]
            for field in kind.fields:
                lines = [f"{operation} {field.signature}"]
                if field.description:
                    lines += ["", field.description]
                if field.arguments:
                    lines += ["", "Arguments:"]
                    lines += [f"- {text}" + (f" — {about}" if about else "")
                              for text, about in field.arguments]
                out.add("capability", f"{operation} {field.name}", "\n".join(lines), field.lines,
                        ("graphql", operation, access))
            continue
        lines = [kind.header]
        if kind.description:
            lines += ["", kind.description]
        if kind.fields:
            lines += ["", "Fields:"]
            for field in kind.fields:
                about = " ".join(field.description.split())
                lines.append(f"- {field.signature}" + (f" — {about}" if about else ""))
        if kind.members and kind.keyword == "enum":
            lines += ["", "Values: " + ", ".join(kind.members)]
        elif kind.members:
            lines += ["", "Members: " + " | ".join(kind.members)]
        out.add("interface", kind.header, "\n".join(lines), kind.lines, ("graphql", kind.keyword))


# --- OpenAPI and Swagger -----------------------------------------------------------------------


_MISSING = object()


def _target(doc: dict, ref: str) -> Any:
    """What a local $ref — '#/components/parameters/limit' — names in doc; _MISSING if it
    names nothing there. Nothing outside the file is ever looked at."""
    if not ref.startswith("#/"):
        return _MISSING
    target: Any = doc
    for part in ref[2:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(target, dict) and key in target:
            target = target[key]
        elif isinstance(target, list) and key.isdigit() and int(key) < len(target):
            target = target[int(key)]
        else:
            return _MISSING
    return target


def _resolve(doc: dict, node: Any) -> Any:
    """A local $ref followed once to what it names; anything else as it is."""
    if not isinstance(node, dict) or not isinstance(node.get("$ref"), str):
        return node
    target = _target(doc, node["$ref"])
    return node if target is _MISSING else target


def _schema_type(schema: Any, depth: int = 0) -> str:
    if not isinstance(schema, dict) or depth > MAX_DEPTH:
        return ""
    if isinstance(schema.get("$ref"), str):
        return schema["$ref"].rsplit("/", 1)[-1]
    kind = schema.get("type")
    if kind == "array":
        inner = _schema_type(schema.get("items"), depth + 1)
        return f"array of {inner}" if inner else "array"
    if isinstance(kind, list):
        return " | ".join(_word(item) for item in kind)
    return _word(kind)


def _parameter_problem(parameter: Any) -> str:
    """Why an entry of a parameter list cannot be read as a parameter; nothing if it can."""
    if not isinstance(parameter, dict):
        return "is not a mapping"
    if isinstance(parameter.get("$ref"), str):
        return ""       # one this file does not hold, listed as its reference
    for key in ("name", "in"):
        if not isinstance(parameter.get(key), str) or not _word(parameter[key]):
            return f"has no '{key}' that is text"
    return ""


def _parameter_list(out: _File, doc: dict, holder: dict, label: str) -> list[dict]:
    """The parameters holder lists for label, each resolved. A list that is not one, and each
    entry that is not a parameter, is said so of — entries up to MAX_SKIPPED, and then
    counted — and the well-formed entries beside them are still taken."""
    listed = holder["parameters"]
    if not isinstance(listed, list):
        out.unparsed(f"the parameters of {label} are not a list, so none of them was read",
                     _entry(holder, "parameters"))
        return []
    taken: list[dict] = []
    skipped = 0
    for number, item in enumerate(listed, 1):
        parameter = _resolve(doc, item)
        problem = _parameter_problem(parameter)
        if not problem:
            taken.append(parameter)
            continue
        skipped += 1
        if skipped <= MAX_SKIPPED:
            out.unparsed(f"parameter {number} of {label} {problem}, so it was not read",
                         _entry(listed, number - 1))
    if skipped > MAX_SKIPPED:
        out.unparsed(f"{skipped - MAX_SKIPPED} more parameters of {label} were not read either: "
                     f"each is malformed, and only the first {MAX_SKIPPED} are said of one by one",
                     _entry(holder, "parameters"))
    return taken


def _parameters(listed: list[dict]) -> list[str]:
    merged: dict[tuple[str, str], dict] = {}
    for parameter in listed:
        if isinstance(parameter.get("$ref"), str):
            merged[("$ref", parameter["$ref"])] = parameter     # one this file does not hold
        else:
            # An operation's own parameter replaces its path's of the same name and place.
            merged[(_word(parameter.get("name")), _word(parameter.get("in")))] = parameter
    lines = []
    for (name, where), parameter in merged.items():
        if isinstance(parameter.get("$ref"), str):
            lines.append(f"- $ref {_word(parameter['$ref'])}")
            continue
        facts = [where or "?"]
        kind = _schema_type(parameter.get("schema", parameter))
        if kind:
            facts.append(kind)
        if parameter.get("required") is True:
            facts.append("required")
        line = f"- {name or '?'} ({', '.join(facts)})"
        about = _word(parameter.get("description"))
        lines.append(line + (f" — {about}" if about else ""))
    return lines


def _request_body(doc: dict, body: Any) -> list[str]:
    body = _resolve(doc, body)
    if not isinstance(body, dict):
        return []
    lines = ["Request body (required):" if body.get("required") is True else "Request body:"]
    content = body.get("content")
    if isinstance(content, dict):
        for media, spec in content.items():
            kind = _schema_type(spec.get("schema")) if isinstance(spec, dict) else ""
            lines.append(f"- {media}: {kind}" if kind else f"- {media}")
    return lines


def _security(requirements: Any) -> str:
    """Who may call it: alternatives joined by 'or', each scheme with its scopes."""
    if requirements is None:
        return "none declared"
    if not isinstance(requirements, list):
        return "unreadable"
    options = []
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        if not requirement:
            options.append("anonymous")
            continue
        parts = []
        for scheme, scopes in requirement.items():
            listed = [_word(scope) for scope in scopes] if isinstance(scopes, list) else []
            parts.append(f"{scheme} [{', '.join(listed)}]" if listed else str(scheme))
        options.append(" and ".join(parts))
    return " or ".join(options) if options else "none"


def _operation(out: _File, doc: dict, heading: str, path: str, method: str,
               operation: dict, shared: list[dict]) -> None:
    own = (_parameter_list(out, doc, operation, f"{method.upper()} {path}")
           if "parameters" in operation else [])
    lines = [f"{method.upper()} {path}"]
    if heading:
        lines.append(heading)
    if _word(operation.get("operationId")):
        lines.append(f"Operation: {_word(operation.get('operationId'))}")
    if _word(operation.get("summary")):
        lines.append(f"Summary: {_word(operation.get('summary'))}")
    if _prose(operation.get("description")):
        lines.append(f"Description: {_prose(operation.get('description'))}")
    parameters = _parameters([*shared, *own])
    lines.append("Parameters:" if parameters else "Parameters: none")
    lines += parameters
    lines += _request_body(doc, operation.get("requestBody"))
    responses = operation.get("responses")
    if isinstance(responses, dict) and responses:
        lines.append("Responses: " + ", ".join(str(code) for code in responses))
    security = operation["security"] if "security" in operation else doc.get("security")
    lines.append(f"Security: {_security(security)}")
    access = "write" if method in _WRITE_METHODS else "read"
    tags = ["openapi", access]
    if operation.get("deprecated") is True:
        tags.append("deprecated")
    out.add("capability", f"{method.upper()} {path}", "\n".join(lines), _lines(operation), tags)


def _path_layers(out: _File, doc: dict, path: str, item: dict) -> list[dict]:
    """paths[path] and the Path Items it refers to, nearest first. Each $ref is followed within
    this file only, never twice to one place and at most MAX_DEPTH times; one that cannot be
    followed is said so of, and what was reached before it is still read."""
    layers = [item]
    followed: set[str] = set()
    node = item
    while "$ref" in node:
        ref = node["$ref"]
        if not isinstance(ref, str):
            problem = "is not text"
        elif not ref.startswith("#"):
            problem = f"refers outside this file, to {ref}, which is not read"
        elif ref in followed:
            problem = f"refers back to {ref}, which was already followed"
        elif len(followed) >= MAX_DEPTH:
            problem = f"ends a chain of more than {MAX_DEPTH} references"
        else:
            followed.add(ref)
            target = _target(doc, ref)
            if isinstance(target, dict):
                layers.append(target)
                node = target
                continue
            problem = (f"refers to {ref}, which names nothing in this file" if target is _MISSING
                       else f"refers to {ref}, which is not a mapping of methods to operations")
        out.unparsed(f"the $ref of path {path} {problem}, so it was not followed",
                     _entry(node, "$ref"))
        break
    return layers


def _openapi(out: _File, doc: dict) -> None:
    info = doc.get("info") if isinstance(doc.get("info"), dict) else {}
    api = " ".join(filter(None, (_word(info.get("title")), _word(info.get("version")))))
    heading = f"API: {api}" if api else ""
    # Only a container that is absent is empty: one that is there, even as null, must be one.
    paths = doc.get("paths", {})
    if not isinstance(paths, dict):
        out.unparsed("'paths' is not a mapping of paths to operations, so no operation was read",
                     _entry(doc, "paths"))
        paths = {}
    for path, item in paths.items():
        if not isinstance(item, dict):
            out.unparsed(f"path {path} is not a mapping of methods to operations",
                         _entry(paths, path))
            continue
        # A Path Item's own fields come before those of the Path Item it refers to.
        fields: dict[str, dict] = {}
        for layer in _path_layers(out, doc, path, item):
            for key in layer:
                fields.setdefault(key, layer)
        shared = (_parameter_list(out, doc, fields["parameters"], f"path {path}")
                  if "parameters" in fields else [])
        for method, holder in fields.items():
            if method.lower() not in _HTTP_METHODS:
                continue
            operation = holder[method]
            if not isinstance(operation, dict):
                out.unparsed(f"{method.upper()} {path} is not a mapping, so it was not read",
                             _entry(holder, method))
                continue
            _operation(out, doc, heading, path, method.lower(), operation, shared)
    sections: list[tuple[str, dict, str]] = []
    if "components" in doc:
        components = doc["components"]
        if not isinstance(components, dict):
            out.unparsed("'components' is not a mapping, so no schema in it was read",
                         _entry(doc, "components"))
        elif "schemas" in components:
            sections.append(("components.schemas", components, "schemas"))
    if "definitions" in doc:
        sections.append(("definitions", doc, "definitions"))     # Swagger 2
    for section, holder, key in sections:
        schemas = holder[key]
        if not isinstance(schemas, dict):
            out.unparsed(f"'{section}' is not a mapping of names to schemas, so no schema in it "
                         "was read", _entry(holder, key))
            continue
        for name, schema in schemas.items():
            lines = [f"schema {name}"] + ([heading] if heading else []) + ["", _dump(schema)]
            out.add("interface", f"schema {name}", "\n".join(lines), _entry(schemas, name),
                    ("openapi", "schema"))


# --- MCP tool manifests and JSON Schema --------------------------------------------------------


def _tool_access(annotations: dict) -> str:
    """What a tool says of itself. Destructive, or not read-only, is 'write'; read-only and
    nothing contrary is 'read'; saying nothing is 'unknown'. A tool that declares only that
    its updates are not destructive is still declaring updates, so it is 'write'."""
    read_only = annotations.get("readOnlyHint")
    destructive = annotations.get("destructiveHint")
    if destructive is True or read_only is False:
        return "write"
    if read_only is True:
        return "read"
    if destructive is False:
        return "write"
    return "unknown"


def _has_tool(candidate: Any) -> bool:
    return isinstance(candidate, list) and any(
        isinstance(item, dict) and ("inputSchema" in item or "input_schema" in item)
        for item in candidate
    )


def _tool_list(doc: Any) -> tuple[Any, tuple[int | None, int | None], str] | None:
    """Where a list of MCP tools is — the document's 'tools', a tools/list result's, or the
    document itself — as that value, its lines and its name. An explicit 'tools' is one
    whatever it holds, so a malformed list is still found, and said so of; a bare list is one
    when any entry carries an input schema."""
    if isinstance(doc, dict):
        if "tools" in doc:
            return doc["tools"], _entry(doc, "tools"), "'tools'"
        result = doc.get("result")
        if isinstance(result, dict) and "tools" in result:
            return result["tools"], _entry(result, "tools"), "'result.tools'"
        return None
    if _has_tool(doc):
        return doc, _lines(doc), "the document"
    return None


def _tool_schema(tool: dict) -> Any:
    return tool["inputSchema"] if "inputSchema" in tool else tool.get("input_schema")


def _tool_problem(tool: Any) -> str:
    """Why an entry of a tool list cannot be read as a tool; nothing if it can."""
    if not isinstance(tool, dict) or "name" not in tool:
        return "is not an object with a name"
    if not isinstance(tool["name"], str) or not _word(tool["name"]):
        return "has a name that is not text"
    if "inputSchema" not in tool and "input_schema" not in tool:
        return "has no input schema"
    if not isinstance(_tool_schema(tool), dict):
        return "has an input schema that is not an object"
    if tool.get("annotations") is not None and not isinstance(tool["annotations"], dict):
        return "has annotations that are not an object"
    return ""


def _mcp_tools(out: _File, tools: Any, at: tuple[int | None, int | None], where: str) -> None:
    """The tools in a list, each checked on its own: a malformed entry is said so of, up to
    MAX_SKIPPED of them and then counted, and the well-formed ones beside it are still read."""
    if not isinstance(tools, list):
        out.unparsed(f"{where} is not a list of tools, so no tool in it was read", at)
        return
    skipped = 0
    for number, tool in enumerate(tools, 1):
        problem = _tool_problem(tool)
        if problem:
            skipped += 1
            if skipped <= MAX_SKIPPED:
                out.unparsed(f"tool {number} {problem}, so it was not read",
                             _entry(tools, number - 1))
            continue
        name = _word(tool.get("name"))
        annotations = tool.get("annotations") or {}
        access = _tool_access(annotations)
        schema = _tool_schema(tool)
        lines = [f"MCP tool {name}"]
        title = _word(annotations.get("title")) or _word(tool.get("title"))
        if title:
            lines.append(f"Title: {title}")
        said = "from the tool's own annotations" if access != "unknown" else "the tool does not say"
        lines.append(f"Access: {access} ({said})")
        if annotations:
            lines += ["Annotations:", _dump(annotations)]
        lines += ["Input schema:", _dump(schema)]
        if _prose(tool.get("description")):
            lines.append(f"Description: {_prose(tool.get('description'))}")
        tags = ["mcp", access]
        if annotations.get("destructiveHint") is True:
            tags.append("destructive")
        out.add("capability", f"MCP tool {name}", "\n".join(lines), _lines(tool), tags)
    if skipped > MAX_SKIPPED:
        out.unparsed(f"{skipped - MAX_SKIPPED} more tools in {where} were not read either: each "
                     f"is malformed, and only the first {MAX_SKIPPED} are said of one by one", at)


def _mcp_server(out: _File, doc: dict) -> None:
    name = _word(doc.get("name")) or out.path
    tools = doc.get("tools", [])
    lines = [f"MCP server {name}"]
    if _word(doc.get("version")):
        lines.append(f"Version: {_word(doc.get('version'))}")
    if _prose(doc.get("description")):
        lines.append(f"Description: {_prose(doc.get('description'))}")
    lines.append("Access: unknown (a server does what its tools do; each is tagged on its own)")
    lines.append(f"Tools listed: {len(tools)}" if isinstance(tools, list)
                 else "Tools listed: unreadable, 'tools' is not a list")
    for key in ("packages", "remotes"):
        if isinstance(doc.get(key), list) and doc[key]:
            lines += [f"{key.capitalize()}:", _dump(doc[key])]
    out.add("capability", f"MCP server {name}", "\n".join(lines), _lines(doc),
            ("mcp", "server", "unknown"))
    if "tools" in doc:
        _mcp_tools(out, tools, _entry(doc, "tools"), "'tools'")


def _is_json_schema(path: str, doc: Any) -> bool:
    """A .schema.json file whose root is an object or a boolean; or an object that declares a
    JSON Schema metaschema; or one that declares another $schema and asserts something."""
    if path.lower().endswith(".schema.json"):
        return isinstance(doc, (dict, bool))
    if not isinstance(doc, dict) or not isinstance(doc.get("$schema"), str):
        return False
    return (_METASCHEMA.fullmatch(doc["$schema"].strip()) is not None
            or any(key in doc for key in _SCHEMA_KEYWORDS))


def _json_schema(out: _File, doc: dict | bool) -> None:
    if isinstance(doc, bool):
        # A boolean schema: true accepts every instance, false none. It has no lines of its
        # own, so it is the whole file.
        verdict = "every instance is valid against it" if doc else "no instance is valid against it"
        body = f"JSON Schema {out.path}\nA boolean schema: {verdict}.\n\n{_dump(doc)}"
        out.units.append(_unit(out.artifact_id, "interface", f"JSON Schema {out.path}", body,
                               out.path, out.whole, ("json_schema",)))
        return
    name = _word(doc.get("title")) or _word(doc.get("$id")) or out.path
    lines = [f"JSON Schema {name}"]
    if _prose(doc.get("description")):
        lines.append(_prose(doc.get("description")))
    lines += ["", _dump(doc)]
    out.add("interface", f"JSON Schema {name}", "\n".join(lines), _lines(doc), ("json_schema",))
    for key in ("$defs", "definitions"):
        definitions = doc.get(key)
        if isinstance(definitions, dict):
            for part, schema in definitions.items():
                body = f"{key}/{part} in JSON Schema {name}\n\n{_dump(schema)}"
                out.add("interface", f"JSON Schema {name}: {part}", body,
                        _entry(definitions, part), ("json_schema",))


def _document(out: _File, doc: Any) -> None:
    """A parsed JSON or YAML file, as whichever specification it is; if none, nothing."""
    if isinstance(doc, dict) and ("openapi" in doc or "swagger" in doc):
        _openapi(out, doc)
    elif isinstance(doc, dict) and PurePosixPath(out.path).name == "server.json":
        _mcp_server(out, doc)
    elif (found := _tool_list(doc)) is not None:
        _mcp_tools(out, *found)
    elif _is_json_schema(out.path, doc):
        _json_schema(out, doc)
    elif out.path.lower().endswith(".schema.json"):
        out.unparsed("not a JSON Schema: its root is neither an object nor a boolean",
                     _lines(doc))


# --- reading -----------------------------------------------------------------------------------


def _find(root: Path) -> tuple[list[str], list[str]]:
    """The specification files under root, as sorted relative paths — regular files only, no
    link followed — and what was left out, in words.

    Directories are read one entry at a time, and no more than MAX_ENTRIES + 1 entries are
    ever looked at. Which entries come first is the file system's order, not the artifact's,
    so an artifact past the bound gives no files at all rather than an arbitrary few of them."""
    found: list[str] = []
    notes: list[str] = []
    entries = 0
    unnamed = 0
    pending = [str(root)]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as listing:
                for entry in listing:
                    entries += 1
                    if entries > MAX_ENTRIES:
                        return [], [f"not read: the artifact has more than {MAX_ENTRIES} "
                                     "entries, so none of its files were read"]
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name not in _SKIPPED_DIRS:
                                pending.append(entry.path)
                            continue
                        if not entry.name.lower().endswith(_SUFFIXES) or not entry.is_file(
                            follow_symlinks=False
                        ):
                            continue
                    except OSError:
                        continue
                    relative = Path(entry.path).relative_to(root).as_posix()
                    try:
                        relative.encode("utf-8")
                    except UnicodeEncodeError:
                        unnamed += 1
                        continue
                    found.append(relative)
        except OSError:
            continue
    if unnamed:
        notes.append(f"not read: {unnamed} files whose names are not UTF-8")
    found.sort()
    if len(found) > MAX_FILES:
        notes.append(f"not read: {len(found) - MAX_FILES} more specification files; at most "
                     f"{MAX_FILES} are read from one artifact")
        found = found[:MAX_FILES]
    return found, notes


def _read(path: Path, limit: int) -> bytes:
    """At most limit + 1 bytes of a regular file: one more than may be taken, so that a file
    past the limit is known to be without reading the rest of it."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    with os.fdopen(os.open(path, flags), "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise _Unparsed("not read: not a regular file")
        return handle.read(limit + 1)


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise _Unparsed("not read: not UTF-8 text") from None


def _parse(out: _File, text: str) -> _Sdl | None:
    """Reads one file into out; a GraphQL schema is returned instead, to be read once every
    file's root operation types are known."""
    suffix = PurePosixPath(out.path).suffix.lower()
    out.whole = (1, text.count("\n") + (not text.endswith("\n")))
    if suffix in _GRAPHQL:
        return _Sdl(text)
    if suffix in _YAML:
        if _OPENAPI_YAML.search(text) is None:
            return None         # YAML that is not OpenAPI or Swagger is not this adapter's
        _document(out, _Yaml(text).parse())
    else:
        _document(out, _Json(text).parse())
    return None


def _reason(exc: Exception) -> str:
    if isinstance(exc, _Unparsed):
        return str(exc)
    if isinstance(exc, RecursionError):
        return "not read: nested too deeply"
    if isinstance(exc, OSError):
        return f"not read: {exc.strerror or type(exc).__name__}"
    return f"not read: {type(exc).__name__}: {exc}"


def decompose(root: Path, artifact_id: str) -> list[Unit]:
    """Every capability and interface in the specifications under root, file by file in path
    order and in document order within a file, each at its exact place. Reads only, within
    the bounds above, and never raises on what it finds: what it cannot read it says so of."""
    root = Path(root)
    try:
        readable = root.is_dir() and not root.is_symlink()
    except OSError:
        readable = False
    if not readable:
        return [_unparsed(artifact_id, ".", "not read: the artifact is not a directory")]
    paths, notes = _find(root)
    files: list[tuple[_File, _Sdl | None]] = []
    # Every byte read counts, whether or not its file is taken: no file is read past what is
    # left of MAX_TOTAL_BYTES, and one that would cross it ends the reading, so no more than
    # MAX_TOTAL_BYTES + 1 bytes are ever read and no more than MAX_TOTAL_BYTES are taken.
    total = 0
    for path in paths:
        out = _File(artifact_id, path)
        schema = None
        try:
            allowance = MAX_TOTAL_BYTES - total
            if allowance <= 0:
                raise _Unparsed("not read: the bytes read from the artifact's specification "
                                f"files already came to {MAX_TOTAL_BYTES} bytes")
            data = _read(root / path, min(MAX_FILE_BYTES, allowance))
            total += len(data)
            if len(data) > MAX_FILE_BYTES:
                raise _Unparsed(f"not read: larger than {MAX_FILE_BYTES} bytes")
            if len(data) > allowance:
                raise _Unparsed("not read: it would take the artifact's specification files "
                                f"past {MAX_TOTAL_BYTES} bytes")
            schema = _parse(out, _decode(data))
        except Exception as exc:  # noqa: BLE001 — what an artifact contains is never an error
            out.units = []
            out.unparsed(_reason(exc))
        files.append((out, schema))

    roots = {"query": "Query", "mutation": "Mutation", "subscription": "Subscription"}
    for _, schema in files:
        if schema is not None:
            roots.update(schema.roots)
    units: list[Unit] = []
    for out, schema in files:
        if schema is not None:
            try:
                _graphql(out, schema, roots)
            except Exception as exc:  # noqa: BLE001
                out.units = []
                out.unparsed(_reason(exc))
        units.extend(out.units)
    units.extend(_unparsed(artifact_id, ".", note) for note in notes)

    units = list({unit.id: unit for unit in units}.values())
    if len(units) > MAX_UNITS:
        dropped = len(units) - MAX_UNITS + 1
        units = units[:MAX_UNITS - 1] + [_unparsed(
            artifact_id, ".", f"not read: {dropped} more units; at most {MAX_UNITS} are taken "
            "from one artifact",
        )]
    return units
