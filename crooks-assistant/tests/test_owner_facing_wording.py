"""No sentence the owner sees or hears names the machine CLIVE used to run on.

CLIVE runs on a Linux server now and the owner holds an iPhone, but the words on the glass and
in the voice still said "the Mac", "this tablet", "make up" and "launchd": "Is the Mac awake and
is it running (make up)?" to somebody with no Mac and no Terminal. Each of those was true once
and is false on any other host. The replacements say CROOKS, the server or this device, which
stay true wherever it runs.

This scans rather than asserting on the strings that were fixed, for the reason
tests/test_no_terminal.py gives: a sentence fixed by reading is fixed one at a time, and the next
one is written the following week.

WHAT IS READ

  * Python: every string constant in the modules that write the owner's words (the fast lane,
    the providers, the families, the presenter and the surfaces), from the AST. Docstrings and
    comments are the engineers' and may keep the history; the owner never sees them.
  * JavaScript: every string and template literal in web/*.js, with the comments skipped.
  * The page, its styles and its manifest, with their comments removed.

The code may still say "Mac" in a comment. What it may not do is put the word in front of the
owner.
"""

from __future__ import annotations

import ast
import bisect
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
WEB = ROOT / "web"

# The runtime, named as a machine the owner would have to have. "Mac" is matched on its own, so
# a font stack's BlinkMacSystemFont and the internal source token "mac" are not.
RUNTIME_WORDS = re.compile(
    r"\bMacs?\b|\bMAC\b|\b(?i:tablets?)\b|\b(?i:launchd)\b|\b(?i:make\s+up)\b"
)

PYTHON_SOURCES = sorted(
    [*(APP / "fastpath").rglob("*.py"), *(APP / "providers").rglob("*.py"),
     *(APP / "families").rglob("*.py"), APP / "presentation.py", APP / "surfaces.py"]
)
SCRIPT_SOURCES = sorted(WEB.glob("*.js"))
PAGE_SOURCES = sorted([*WEB.glob("*.html"), *WEB.glob("*.css"), *WEB.glob("*.webmanifest")])


def _name(path: Path) -> str:
    return str(path.relative_to(ROOT))


# ------------------------------------------------------------------------------ Python

def _python_strings(path: Path) -> list[tuple[int, str]]:
    """Every string constant in a module that is not prose standing on its own: a docstring,
    or a bare string used as one, is for whoever reads the code."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    prose = {id(node.value) for node in ast.walk(tree)
             if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
             and isinstance(node.value.value, str)}
    return [(node.lineno, node.value) for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
            and id(node) not in prose]


# -------------------------------------------------------------------------- JavaScript

# Where a `/` opens a regular expression rather than dividing: after one of these characters,
# or after one of these words. Anywhere else it divides.
_REGEX_AFTER_CHAR = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_AFTER_WORD = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete",
                     "void", "throw", "instanceof", "yield", "await"}
_WORD = re.compile(r"[A-Za-z0-9_$]+")


def _js_strings(source: str) -> list[tuple[int, str]]:
    """Every string, and every literal chunk of a template, in a script — never a comment.

    Just enough of a JavaScript lexer for that. A template's `${…}` is lexed as code, so a
    string inside one is found and a backtick inside one does not end the outer template. A
    regular expression is skipped where one may begin, so /['"]/ does not open a string. A
    string or a regular expression never runs past the end of its line, so a misreading costs
    one line and not the rest of the file.
    """
    found: list[tuple[int, str]] = []
    n = len(source)

    def regex_end(i: int) -> int:
        in_class = False
        j = i + 1
        while j < n:
            ch = source[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "\n":
                return -1
            if ch == "[":
                in_class = True
            elif ch == "]":
                in_class = False
            elif ch == "/" and not in_class:
                flags = _WORD.match(source, j + 1)
                return flags.end() if flags else j + 1
            j += 1
        return -1

    def template(i: int) -> int:
        j = start = i + 1
        while j < n:
            ch = source[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "`":
                found.append((start, source[start:j]))
                return j + 1
            if ch == "$" and source.startswith("{", j + 1):
                found.append((start, source[start:j]))
                j = start = code(j + 2, nested=True)
                continue
            j += 1
        found.append((start, source[start:n]))
        return n

    def code(i: int, nested: bool = False) -> int:
        depth = 0
        last_char, last_word = "", ""
        while i < n:
            ch = source[i]
            if ch.isspace():
                i += 1
                continue
            if source.startswith("//", i):
                end = source.find("\n", i)
                i = n if end < 0 else end
                continue
            if source.startswith("/*", i):
                end = source.find("*/", i + 2)
                i = n if end < 0 else end + 2
                continue
            if ch in "'\"":
                j = i + 1
                while j < n and source[j] != ch and source[j] != "\n":
                    j += 2 if source[j] == "\\" else 1
                found.append((i + 1, source[i + 1:j]))
                i, last_char, last_word = j + 1, ch, ""
                continue
            if ch == "`":
                i, last_char, last_word = template(i), ch, ""
                continue
            word = _WORD.match(source, i)
            if word:
                i, last_char, last_word = word.end(), "a", word.group(0)
                continue
            if ch == "/" and (not last_char or last_char in _REGEX_AFTER_CHAR
                              or last_word in _REGEX_AFTER_WORD):
                end = regex_end(i)
                if end > 0:
                    i, last_char, last_word = end, "a", ""
                    continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                if nested and depth == 0:
                    return i + 1
                depth -= 1
            i, last_char, last_word = i + 1, ch, ""
        return n

    code(0)
    newlines = [i for i, ch in enumerate(source) if ch == "\n"]
    return [(bisect.bisect_left(newlines, offset) + 1, text) for offset, text in found]


# ---------------------------------------------------------------- the page and its styles

def _page_text(path: Path) -> list[tuple[int, str]]:
    """The file line by line, with its comments blanked out and its line numbers kept."""
    source = path.read_text(encoding="utf-8")
    comment = r"<!--.*?-->" if path.suffix == ".html" else r"/\*.*?\*/"
    source = re.sub(comment, lambda m: re.sub(r"[^\n]", " ", m.group(0)), source, flags=re.S)
    return list(enumerate(source.splitlines(), start=1))


# ------------------------------------------------------------------------------- tests

def _offences(strings: list[tuple[int, str]]) -> list[str]:
    return [f"{line}: {text.strip()[:160]!r}" for line, text in strings
            if RUNTIME_WORDS.search(text)]


def test_the_scanner_finds_strings_and_skips_comments():
    """The guard on the lexer itself. A scanner that read nothing would pass everything, and
    one that read comments would fail on the history the code is allowed to keep."""
    sample = r"""
// the Mac, in a comment
/* the tablet, in a block */
const a = x.replace(/['"`]/g, '') / 2;   // a regex holding every quote, then a division
const b = `outer ${cond ? `inner ${'deep Mac'}` : 'no'} tail tablet`;
const c = 'plain launchd';
const d = total / count; const e = "make up";
"""
    said = sorted(text.strip() for _, text in _js_strings(sample) if RUNTIME_WORDS.search(text))
    assert said == ["deep Mac", "make up", "plain launchd", "tail tablet"], said
    # And the words themselves: the machine, not a font or an internal token.
    assert not RUNTIME_WORDS.search("-apple-system,BlinkMacSystemFont,Roboto")
    assert not RUNTIME_WORDS.search('Freshness(source="mac")')
    assert RUNTIME_WORDS.search("Is the Mac awake and is it running (make up)?")


def test_the_scan_reaches_the_sources_the_owner_named():
    """Each file the owner quoted is one this test reads — or the scan proves nothing."""
    named = {"app/fastpath/library.py", "app/providers/max_agent_sdk.py", "app/presentation.py",
             "web/app.js", "web/alpha.js", "web/action-state.js", "web/ui.js", "web/index.html"}
    scanned = {_name(p).replace("\\", "/") for p in [*PYTHON_SOURCES, *SCRIPT_SOURCES, *PAGE_SOURCES]}
    assert named <= scanned, named - scanned


@pytest.mark.parametrize("path", PYTHON_SOURCES, ids=_name)
def test_no_python_string_names_the_old_runtime(path):
    bad = _offences(_python_strings(path))
    assert not bad, f"{_name(path)} names the runtime:\n" + "\n".join(bad)


@pytest.mark.parametrize("path", SCRIPT_SOURCES, ids=_name)
def test_no_script_string_names_the_old_runtime(path):
    bad = _offences(_js_strings(path.read_text(encoding="utf-8")))
    assert not bad, f"{_name(path)} names the runtime:\n" + "\n".join(bad)


@pytest.mark.parametrize("path", PAGE_SOURCES, ids=_name)
def test_no_page_text_names_the_old_runtime(path):
    bad = _offences(_page_text(path))
    assert not bad, f"{_name(path)} names the runtime:\n" + "\n".join(bad)
