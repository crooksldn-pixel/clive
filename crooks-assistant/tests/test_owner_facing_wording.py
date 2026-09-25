"""The words the owner sees or hears name no host: not the Mac, not a tablet, not launchd, not
`make up`.

CLIVE runs on a Linux server and the owner holds an iPhone, but the screen, the voice and the
instructions the model repeats back went on saying "The Mac is still reading recent orders",
"Is the Mac awake and is it running (make up)?" and "It is still waiting on the tablet" long
after either was true. Each was fixed where it was found, and the next one was written the
following week. So this scans rather than asserting on the ones that were found.

WHAT IT READS

  Python: every string literal in the modules that write the owner's words — the cards, the
  spoken lines and refusals, the health and capability text, the tool results and prompts the
  model answers from. Two kinds of literal are not words said TO the owner and are left alone:
  docstrings (bare string statements, read by whoever reads the code) and the pattern handed to
  a `re` call, which recognises what the owner SAYS. A literal that is exactly one word of that
  input vocabulary ("tablet", in the set of words that make a question about the screen) is
  the same thing held in a set.

  Web: every file the page is built from, with its comments taken out.

Comments may keep their history; they are not read to anyone.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

# The runtime, named. "Mac" is case-sensitive so the internal source tag "mac" is not a hit.
RUNTIME_WORDS = re.compile(r"\bMac\b|\b[Tt]ablet\b|\blaunchd\b|\bmake up\b")

PYTHON_SOURCES = (
    "app/fastpath",
    "app/providers",
    "app/families",
    "app/presentation.py",
    "app/surfaces.py",
    "app/routes/actions.py",
    "app/routes/turn.py",
    "app/routes/admin.py",
    "app/routes/health.py",
    "app/routes/speak.py",
    "app/routes/command.py",
    "app/actions",
    "app/analytics",
    "app/summaries.py",
    "app/capabilities",
    "app/observability/ui_semantics.py",
    "app/runtime.py",
    "app/shipping",
    "app/tools",
)
WEB_SUFFIXES = (".js", ".html", ".css", ".webmanifest")

# Words the owner may say, held one to a literal so a sentence can be recognised by them.
VOCABULARY = frozenset({"tablet"})

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)


def _python_strings(source: str, filename: str) -> list[tuple[int, str]]:
    """Every string literal in a module that could reach the owner, with its line."""
    tree = ast.parse(source, filename=filename)
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            skip.add(id(node.value))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and isinstance(node.func.value, ast.Name) and node.func.value.id == "re" and node.args):
            skip.update(id(n) for n in ast.walk(node.args[0]))
    return [(getattr(n, "lineno", 0), n.value) for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in skip and n.value not in VOCABULARY]


def _line_comment(text: str) -> int:
    """Where a `//` comment starts on this line, or -1. A `//` after a colon is a URL."""
    start = 0
    while True:
        at = text.find("//", start)
        if at <= 0 or text[at - 1] != ":":
            return at
        start = at + 2


def _without_comments(source: str) -> str:
    """A script, stylesheet or page with its `//` and `/* */` comments removed, line for line.

    It does not parse strings, so a `//` or `/*` inside one hides the rest of it: the scan can
    only ever read LESS than the page says, never read a comment as something said."""
    out: list[str] = []
    in_block = False
    for line in source.splitlines():
        kept = ""
        rest = line
        while rest:
            if in_block:
                end = rest.find("*/")
                if end < 0:
                    break
                rest = rest[end + 2:]
                in_block = False
                continue
            block = rest.find("/*")
            inline = _line_comment(rest)
            if inline >= 0 and (block < 0 or inline < block):
                kept += rest[:inline]
                break
            if block >= 0:
                kept += rest[:block]
                rest = rest[block + 2:]
                in_block = True
                continue
            kept += rest
            break
        out.append(kept)
    return "\n".join(out)


def _page_text(text: str, suffix: str) -> str:
    """What a web file can put in front of the owner: itself, less its comments."""
    if suffix == ".html":
        text = _HTML_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    return _without_comments(text)


def _python_files() -> list[Path]:
    files: list[Path] = []
    for entry in PYTHON_SOURCES:
        path = ROOT / entry
        assert path.exists(), f"{entry} is listed as an owner-facing source and is not there"
        files.extend(sorted(path.rglob("*.py")) if path.is_dir() else [path])
    return files


def _web_files() -> list[Path]:
    return sorted(p for p in WEB.rglob("*") if p.is_file() and p.suffix in WEB_SUFFIXES)


def test_the_python_scan_reads_strings_and_not_comments_docstrings_or_patterns():
    """The guard on the scanner: it must see a sentence, and must not see the rest."""
    source = '''
"""A module about the Mac."""
import re

# A comment about the tablet.
PATTERN = re.compile(r"\\b(?:screen|tablet)\\b", re.I)
WORDS = frozenset({"screen", "tablet"})


def said():
    """A docstring about launchd."""
    return "Is the Mac awake?", f"run make up on the {1}", "nothing to see"
'''
    hits = [text for _, text in _python_strings(source, "probe.py") if RUNTIME_WORDS.search(text)]
    assert sorted(hits) == ["Is the Mac awake?", "run make up on the "], hits


def test_the_web_scan_reads_strings_and_not_comments():
    """The same guard for the page: comments of both kinds out, URLs and strings in."""
    source = "\n".join([
        "// the Mac, in a comment",
        "/* the tablet,",
        "   over two lines */",
        "const a = 'https://example.com'; // launchd",
        "const b = \"Is the Mac awake?\";",
        "const c = `run make up`; /* trailing */",
    ])
    stripped = _without_comments(source)
    assert "https://example.com" in stripped
    assert [m.group(0) for m in RUNTIME_WORDS.finditer(stripped)] == ["Mac", "make up"], stripped
    page = _page_text("<p>Ready</p>\n<!-- the Mac\n     and the tablet -->\n<p>On the Mac</p>", ".html")
    assert page.count("\n") == 3, "a comment keeps its lines, so a hit names the right one"
    assert [m.group(0) for m in RUNTIME_WORDS.finditer(page)] == ["Mac"], page


def test_no_owner_facing_python_string_names_the_runtime_host():
    files = _python_files()
    assert len(files) >= 30, f"the scan found only {len(files)} modules; a scan of nothing passes"
    bad: list[str] = []
    for path in files:
        where = path.relative_to(ROOT)
        for line, text in _python_strings(path.read_text(encoding="utf-8"), str(where)):
            if RUNTIME_WORDS.search(text):
                bad.append(f"{where}:{line}: {text[:160]!r}")
    assert not bad, "owner-facing strings still name the runtime host:\n" + "\n".join(bad)


def test_no_web_string_names_the_runtime_host():
    files = _web_files()
    names = {p.name for p in files}
    assert {"app.js", "ui.js", "index.html"} <= names, f"the page's own files were not found: {sorted(names)}"
    bad: list[str] = []
    for path in files:
        for number, line in enumerate(_page_text(path.read_text(encoding="utf-8"), path.suffix).splitlines(), 1):
            for match in RUNTIME_WORDS.finditer(line):
                bad.append(f"web/{path.relative_to(WEB)}:{number}: {match.group(0)!r} in {line.strip()[:160]!r}")
    assert not bad, "the page still names the runtime host:\n" + "\n".join(bad)
