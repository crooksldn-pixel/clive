"""Nothing the owner sees or hears names the host CLIVE used to run on.

CLIVE runs on a Linux server now and the owner holds an iPhone, but the words on the screen and
in the voice still said "the Mac", "this tablet", launchd and `make up`. This reads every string
that can reach the owner from the sources that produce them — the fast lane, the providers, the
families, the presenter, the action and turn routes, and every file the page is served from —
and fails on any of those words, so they cannot come back. Comments and docstrings may keep
them: they are written for whoever reads the code, not for the owner.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
WEB = ROOT / "web"

# The runtime, named any of the ways the owner was shown or told it. Case matters for "Mac":
# "mac" is a machine token on the wire (a freshness source), never a word anybody reads.
RUNTIME_WORDS = re.compile(r"\b(?:Mac|MAC|[Tt]ablets?|TABLETS?|launchd|[Mm]ake up)\b")

PYTHON_SOURCES = sorted([
    *(APP / "fastpath").rglob("*.py"),
    *(APP / "providers").rglob("*.py"),
    *(APP / "families").rglob("*.py"),
    APP / "presentation.py",
    APP / "surfaces.py",
    APP / "routes" / "actions.py",
    APP / "routes" / "turn.py",
])
WEB_SOURCES = sorted(p for p in WEB.iterdir() if p.suffix in {".js", ".html", ".css", ".webmanifest"})

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"(^|\s)//.*$", re.MULTILINE)


def python_strings(source: str) -> list[tuple[int, str]]:
    """Every string literal in a module except its docstrings and bare string statements,
    which nothing at runtime ever reads."""
    tree = ast.parse(source)
    prose = {
        id(node.value) for node in ast.walk(tree)
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
    }
    return [
        (node.lineno, node.value) for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in prose
    ]


def _blank(match: re.Match[str]) -> str:
    return "\n" * match.group(0).count("\n")


def web_text(name: str, source: str) -> str:
    """A page file with its comments taken out. Blanked rather than removed, so a line number
    in a failure is the line in the file."""
    text = _HTML_COMMENT.sub(_blank, source) if name.endswith(".html") else source
    text = _BLOCK_COMMENT.sub(_blank, text)
    if not name.endswith(".css"):
        text = _LINE_COMMENT.sub(r"\1", text)
    return text


def test_the_scan_sees_a_string_and_not_a_comment():
    py = 'def f():\n    """The Mac holds it."""\n    # the tablet\n    return "Is the Mac awake?"\n'
    assert [s for _, s in python_strings(py) if RUNTIME_WORDS.search(s)] == ["Is the Mac awake?"]
    js = "// the Mac\n/* the tablet */\nconst a = 'Run make up'; // on the Mac\n"
    assert RUNTIME_WORDS.findall(web_text("x.js", js)) == ["make up"]
    html = "<!-- the Mac -->\n<p>If the voice fails, the tablet speaks.</p>\n"
    assert RUNTIME_WORDS.findall(web_text("x.html", html)) == ["tablet"]
    assert not RUNTIME_WORDS.search('source="mac"') and not RUNTIME_WORDS.search("tablet_notify")


def test_the_scan_covers_the_sources_the_owner_hears_from():
    names = {p.relative_to(ROOT).as_posix() for p in PYTHON_SOURCES}
    assert {"app/fastpath/library.py", "app/providers/max_agent_sdk.py", "app/presentation.py",
            "app/routes/actions.py", "app/routes/turn.py"} <= names
    assert {"app.js", "alpha.js", "action-state.js", "ui.js", "index.html"} <= {p.name for p in WEB_SOURCES}


@pytest.mark.parametrize("path", PYTHON_SOURCES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_no_string_the_server_says_names_the_old_host(path):
    found = [
        f"{path.relative_to(ROOT).as_posix()}:{line}: {text!r}"
        for line, text in python_strings(path.read_text(encoding="utf-8"))
        if RUNTIME_WORDS.search(text)
    ]
    assert not found, "owner-facing words name the Mac, a tablet, launchd or make up:\n" + "\n".join(found)


@pytest.mark.parametrize("path", WEB_SOURCES, ids=lambda p: p.name)
def test_nothing_the_page_says_names_the_old_host(path):
    text = web_text(path.name, path.read_text(encoding="utf-8"))
    found = [
        f"web/{path.name}:{number}: {line.strip()[:160]}"
        for number, line in enumerate(text.splitlines(), 1)
        if RUNTIME_WORDS.search(line)
    ]
    assert not found, "owner-facing words name the Mac, a tablet, launchd or make up:\n" + "\n".join(found)
