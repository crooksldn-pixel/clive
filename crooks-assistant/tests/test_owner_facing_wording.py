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
  a `re` call, which recognises what the owner SAYS. The exception is the docstring of an HTTP
  route handler: FastAPI publishes it as the operation's description in /openapi.json and
  /docs, so it is read like any sentence. Past those, a literal is let through only where
  `NOT_SAID` declares it: that module, that top-level name, that exact text.

  Web: every file the page is built from. Scripts and stylesheets are lexed, strings, template
  literals and regular expressions included, so only a real comment is taken out and a `//` or
  `/*` inside a string is read as what the page says. A page is tokenized the same way: it
  loses the `<!-- -->` comments in its text and nothing else, so a `<!--` inside a quoted
  attribute or an inline script or style is read as what the page says.

The match ignores case: "MAC", "Tablet" and "Make up" are the same words on the glass.
Comments may keep their history; they are not read to anyone.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

# The runtime, named, in any case.
RUNTIME_WORDS = re.compile(r"\bmac\b|\btablets?\b|\blaunchd\b|\bmake\s+up\b", re.I)

PYTHON_SOURCES = (
    "app/recipes.py",
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
    "app/displays",
    "app/routes/displays.py",
)
WEB_SUFFIXES = (".js", ".html", ".css", ".webmanifest")

# Literals that are not words said to the owner, each let through only where it is declared:
# (module, the top-level assignment or function that holds it, the literal exactly as written).
# The same word anywhere else — another module, another name, another spelling — is read like
# any sentence, and a declaration nothing matches any more fails the scan.
NOT_SAID: frozenset[tuple[str, str, str]] = frozenset({
    # Words the owner may SAY, held in the set that recognises a question about the screen.
    ("app/observability/ui_semantics.py", "UI_WORDS", "tablet"),
    # "mac": the source tag, beside "shopify" and "gmail", for what this process answers from
    # what it already holds. It keys budgets, freshness and the manifest's sources.
    ("app/capabilities/manifest.py", "_FAMILY", "mac"),
    ("app/capabilities/manifest.py", "_source_of", "mac"),
    ("app/capabilities/manifest.py", "build", "mac"),
    ("app/capabilities/surface.py", "build_surface", "mac"),
    ("app/routes/turn.py", "_performance", "mac"),
})

# The decorators that make a function an HTTP route, whose docstring the API publishes.
_ROUTE_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options", "trace",
                            "api_route", "route", "websocket"})

# An HTML comment as the page parser ends it: at `-->` or `--!>`, or abruptly at `<!-->` and
# `<!--->`. Matched only where a comment can open, in the page's text between tags.
_HTML_COMMENT = re.compile(r"<!--(?:-?>|.*?--!?>)", re.S)
# A start or end tag: `<` or `</` and a letter.
_HTML_TAG = re.compile(r"<(/?)([A-Za-z][A-Za-z0-9-]*)")
# Elements whose contents are raw text to the parser, where `<!--` opens no comment.
_HTML_RAW = frozenset({"script", "style", "textarea", "title"})

# After these words a `/` opens a regular expression; after any other word it divides.
_REGEX_AFTER = frozenset({"return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
                          "throw", "case", "do", "else", "yield", "await"})


def _name_of(node: ast.stmt) -> str:
    """The name a top-level statement declares: a function's or class's, or what it assigns."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return node.name
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign):
        targets = [node.target]
    else:
        targets = []
    return ",".join(t.id for t in targets if isinstance(t, ast.Name))


def _is_route(node: ast.AST) -> bool:
    """Whether a function is an HTTP route: decorated `@router.get(...)`, `@app.post(...)` and
    the like."""
    return isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
        isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and d.func.attr in _ROUTE_METHODS
        for d in node.decorator_list)


def _route_docstrings(tree: ast.AST) -> set[int]:
    """The docstrings of the route handlers in a module. FastAPI publishes each as its
    operation's description in /openapi.json and /docs, so these are read out, not skipped."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if _is_route(node) and node.body and isinstance(node.body[0], ast.Expr):
            value = node.body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                found.add(id(value))
    return found


def _literals(source: str, filename: str) -> list[tuple[int, str, str]]:
    """Every string literal in a module that could reach the owner: (line, the top-level name
    that holds it, the text)."""
    tree = ast.parse(source, filename=filename)
    published = _route_docstrings(tree)
    skip: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str) and id(node.value) not in published):
            skip.add(id(node.value))
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and isinstance(node.func.value, ast.Name) and node.func.value.id == "re" and node.args):
            skip.update(id(n) for n in ast.walk(node.args[0]))
    return [(n.lineno, _name_of(top), n.value) for top in tree.body for n in ast.walk(top)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip]


def _python_strings(source: str, filename: str) -> list[tuple[int, str]]:
    """The literals of a module that are read as words to the owner, with their lines."""
    return [(line, text) for line, owner, text in _literals(source, filename)
            if (filename, owner, text) not in NOT_SAID]


def _string_end(source: str, i: int) -> int:
    """Past the closing quote of the '…' or "…" string that opens at `i`."""
    quote, j = source[i], i + 1
    while j < len(source) and source[j] != "\n":
        if source[j] == "\\":
            j += 2
        elif source[j] == quote:
            return j + 1
        else:
            j += 1
    raise ValueError(f"a string opened at offset {i} does not close on its line")


def _template_end(source: str, i: int) -> tuple[int, bool]:
    """From inside a template literal at `i`: past its closing backtick (False), or past the
    `${` that opens its next hole (True)."""
    j = i
    while j < len(source):
        if source[j] == "\\":
            j += 2
        elif source[j] == "`":
            return j + 1, False
        elif source.startswith("${", j):
            return j + 2, True
        else:
            j += 1
    raise ValueError(f"a template literal open at offset {i} never closes")


def _regex_end(source: str, i: int) -> int:
    """Past the flags of the regular-expression literal that opens at `i`."""
    j, in_class = i + 1, False
    while j < len(source) and source[j] != "\n":
        c = source[j]
        if c == "\\":
            j += 2
            continue
        if c == "[":
            in_class = True
        elif c == "]":
            in_class = False
        elif c == "/" and not in_class:
            j += 1
            while j < len(source) and source[j].isalpha():
                j += 1
            return j
        j += 1
    raise ValueError(f"a regular expression opened at offset {i} does not close on its line")


def _regex_may_start(prev: str) -> bool:
    """Whether a `/` after this token opens a regular expression rather than dividing."""
    if not prev or prev in _REGEX_AFTER:
        return True
    return not (prev[-1].isalnum() or prev[-1] in "_$)]}\"")


def _without_comments(source: str, *, script: bool = True) -> str:
    """A script (or, with `script=False`, a stylesheet) with its comments removed, line for line.

    A lexer, not a pattern: it walks '…' and "…" strings, template literals and their `${…}`
    holes, and regular-expression literals, so a `//` or `/*` inside any of them stays as what
    the page says. Only a comment that begins in code is taken out, and it leaves its newlines
    so a hit still names its line. Where it cannot follow the source — a string that does not
    close, braces that do not balance — it raises rather than guess."""
    out: list[str] = []
    i, n = 0, len(source)
    depth = 0                    # open braces in code
    holes: list[int] = []        # the depth each open `${` returns to, innermost last
    prev = ""                    # the last token in code: a word, or one character ('"' a literal)
    while i < n:
        c = source[i]
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end < 0:
                raise ValueError(f"a comment opened at offset {i} never closes")
            out.append("\n" * source.count("\n", i, end))
            i = end + 2
        elif script and source.startswith("//", i):
            end = source.find("\n", i)
            i = n if end < 0 else end
        elif c in "'\"":
            end = _string_end(source, i)
            out.append(source[i:end])
            i, prev = end, '"'
        elif script and (c == "`" or (c == "}" and holes and holes[-1] == depth - 1)):
            if c == "}":
                depth = holes.pop()
            end, hole = _template_end(source, i + 1)
            out.append(source[i:end])
            i = end
            if hole:
                holes.append(depth)
                depth += 1
            prev = "{" if hole else '"'
        elif script and c == "/" and _regex_may_start(prev):
            end = _regex_end(source, i)
            out.append(source[i:end])
            i, prev = end, '"'
        elif c.isalnum() or c in "_$":
            j = i + 1
            while j < n and (source[j].isalnum() or source[j] in "_$"):
                j += 1
            out.append(source[i:j])
            i, prev = j, source[i:j]
        else:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
            if not c.isspace():
                prev = c
            out.append(c)
            i += 1
    if script and (depth or holes):
        raise ValueError("the braces do not balance: the lexer lost its place in this script")
    return "".join(out)


def _tag_end(text: str, i: int) -> int:
    """Past the `>` that closes the tag opening at `i`. A quoted attribute value is read whole,
    so a `>` or `<!--` inside one belongs to the value."""
    j, n, after_equals = i + 1, len(text), False
    while j < n:
        c = text[j]
        if c == ">":
            return j + 1
        if c in "'\"" and after_equals:
            end = text.find(c, j + 1)
            if end < 0:
                raise ValueError(f"an attribute value opened at offset {j} never closes")
            j, after_equals = end + 1, False
            continue
        if c == "=":
            after_equals = True
        elif not c.isspace():
            after_equals = False
        j += 1
    raise ValueError(f"a tag opened at offset {i} never closes")


def _html_without_comments(text: str) -> str:
    """A page with its comments removed, line for line.

    A tokenizer, not a pattern: it walks the page's text, its tags with their quoted attribute
    values, and the raw contents of script, style, textarea and title, so a `<!--` inside a
    value or a script string is read as what the page says. Only a comment that opens in the
    page's text is taken out, and it leaves its newlines so a hit still names its line."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        tag = _HTML_TAG.match(text, i)
        if text.startswith("<!--", i):
            comment = _HTML_COMMENT.match(text, i)
            if comment is None:
                raise ValueError(f"a comment opened at offset {i} never closes")
            out.append("\n" * comment.group(0).count("\n"))
            i = comment.end()
        elif tag:
            end = _tag_end(text, i)
            out.append(text[i:end])
            i = end
            name = tag.group(2).lower()
            if not tag.group(1) and name in _HTML_RAW:
                close = re.compile(rf"</{name}(?=[\s/>])", re.I).search(text, i)
                if close is None:
                    raise ValueError(f"a <{name}> opened at offset {tag.start()} never closes")
                out.append(text[i:close.start()])
                i = close.start()
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _page_text(text: str, suffix: str) -> str:
    """What a web file can put in front of the owner: itself, less its comments."""
    if suffix == ".html":
        return _html_without_comments(text)
    if suffix == ".js":
        return _without_comments(text)
    if suffix == ".css":
        return _without_comments(text, script=False)
    return text


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


def said():
    """A docstring about launchd."""
    return "Is the Mac awake?", f"run make up on the {1}", "nothing to see"
'''
    hits = [text for _, text in _python_strings(source, "probe.py") if RUNTIME_WORDS.search(text)]
    assert sorted(hits) == ["Is the Mac awake?", "run make up on the "], hits


def test_the_python_scan_reads_a_route_handlers_docstring():
    """A route handler's docstring is published by /openapi.json and /docs, so it is read. The
    docstrings of the module, a class, a helper and an undecorated function are not."""
    source = '''
"""A module about the Mac."""
from fastapi import APIRouter

router = APIRouter()


class Helper:
    """A class about the tablet."""


def _helper():
    """A helper about launchd."""


@router.get("/ping")
async def ping():
    """Is the Mac there at all?"""
    return {"ok": True}


@router.post("/row", response_model=None)
def row():
    """The tablet posts WHICH row."""


@app.api_route("/other", methods=["GET"])
async def other():
    """Run make up first."""


@staticmethod
def plain():
    """Not a route, on the Mac."""
'''
    hits = [text for _, text in _python_strings(source, "app/routes/probe.py") if RUNTIME_WORDS.search(text)]
    assert sorted(hits) == ["Is the Mac there at all?", "Run make up first.", "The tablet posts WHICH row."], hits


def test_the_python_scan_ignores_case_and_lets_through_only_what_is_declared():
    """A declared word passes only in its own declaration. The same word as a label, a reply or
    a set anywhere else is a hit, and so is every spelling of every runtime word."""
    source = '''
UI_WORDS = frozenset({"screen", "tablet"})
OTHER_WORDS = frozenset({"screen", "tablet"})
LABEL = "tablet"


def said():
    return "tablet", "TABLET", "Tablets", "the MAC", "mac", "Launchd", "LAUNCHD", "Make up", "MAKE  UP"
'''
    hits = [text for _, text in _python_strings(source, "app/observability/ui_semantics.py")
            if RUNTIME_WORDS.search(text)]
    assert sorted(hits) == sorted(["tablet", "tablet", "tablet", "TABLET", "Tablets", "the MAC", "mac",
                                   "Launchd", "LAUNCHD", "Make up", "MAKE  UP"]), hits
    tag = '''
_FAMILY = {"batch_": ("mac", "bulk changes")}
LINE = "mac"
'''
    assert [text for _, text in _python_strings(tag, "app/capabilities/manifest.py")
            if RUNTIME_WORDS.search(text)] == ["mac"]
    assert [text for _, text in _python_strings(tag, "app/tools/probe.py")
            if RUNTIME_WORDS.search(text)] == ["mac", "mac"]
    assert [text for _, text in _python_strings('WORDS = {"Tablet"}\n', "app/observability/ui_semantics.py")
            if RUNTIME_WORDS.search(text)] == ["Tablet"]


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
    assert stripped.count("\n") == source.count("\n"), "a comment keeps its lines"
    assert [m.group(0) for m in RUNTIME_WORDS.finditer(stripped)] == ["Mac", "make up"], stripped
    page = _page_text("<p>Ready</p>\n<!-- the Mac\n     and the tablet -->\n<p>On the Mac</p>", ".html")
    assert page.count("\n") == 3, "a comment keeps its lines, so a hit names the right one"
    assert [m.group(0) for m in RUNTIME_WORDS.finditer(page)] == ["Mac"], page


def test_the_web_scan_reads_a_comment_marker_inside_a_string_as_words():
    """`//` and `/*` inside a string, a template or a regular expression open no comment, so
    what follows them on the glass is still read."""
    source = "\n".join([
        "const a = 'see https://example.com // then the Mac';",
        "const b = \"a /* the TABLET */ label\";",
        "const c = 'half /* open', d = 'and the tablet';",
        "const e = `run ${x} // make up`;",
        "const f = `${fn({ k: '}' })} is the Tablet`;   // the Mac, a comment",
        "const g = /[\"'/]/.test(y) ? 'LAUNCHD' : '';   /* the tablet, a comment */",
        "const h = n / 2; const i = 'the mac' // after division: a comment about launchd",
        "const j = `// the Mac, ${'/* the tablet'}`;",
    ])
    stripped = _without_comments(source)
    assert stripped.count("\n") == source.count("\n")
    assert [m.group(0) for m in RUNTIME_WORDS.finditer(stripped)] == [
        "Mac", "TABLET", "tablet", "make up", "Tablet", "LAUNCHD", "mac", "Mac", "tablet"], stripped
    css = _without_comments('a::after { content: "// the Mac /* on it"; } /* the tablet */', script=False)
    assert [m.group(0) for m in RUNTIME_WORDS.finditer(css)] == ["Mac"], css


def test_the_page_scan_reads_a_comment_marker_inside_an_attribute_or_a_script_as_words():
    """`<!--` and `-->` inside a quoted attribute, or inside an inline script or style, open no
    comment, so nothing the page says is taken out with them. A comment in the page's text is
    still taken out, keeping its lines."""
    source = "\n".join([
        '<button aria-label="Wake the tablet <!-- then -->" title=\'<!-- the Mac\'>Go</button>',
        "<script>",
        "  const s = '<!-- the Mac is asleep -->';",
        '  const t = "--> run make up";',
        "</script>",
        '<style>a::after { content: "<!-- launchd"; }</style>',
        "<p>On the TABLET</p>",
        "<!-- a real comment about the Mac,",
        "     and the tablet -->",
        "<textarea placeholder=\"x\"><!-- the mac --></textarea>",
        "<p>Ready</p>",
    ])
    page = _page_text(source, ".html")
    assert page.count("\n") == source.count("\n"), "a comment keeps its lines"
    assert [m.group(0) for m in RUNTIME_WORDS.finditer(page)] == [
        "tablet", "Mac", "Mac", "make up", "launchd", "TABLET", "mac"], page
    assert "<p>Ready</p>" in page and "a real comment" not in page, page


def test_no_owner_facing_python_string_names_the_runtime_host():
    files = _python_files()
    assert len(files) >= 30, f"the scan found only {len(files)} modules; a scan of nothing passes"
    bad: list[str] = []
    used: set[tuple[str, str, str]] = set()
    for path in files:
        where = path.relative_to(ROOT).as_posix()
        for line, owner, text in _literals(path.read_text(encoding="utf-8"), where):
            if (where, owner, text) in NOT_SAID:
                used.add((where, owner, text))
            elif RUNTIME_WORDS.search(text):
                bad.append(f"{where}:{line}: {text[:160]!r}")
    assert not bad, "owner-facing strings still name the runtime host:\n" + "\n".join(bad)
    assert used == NOT_SAID, f"declared and no longer there, so remove them: {sorted(NOT_SAID - used)}"


def test_no_web_string_names_the_runtime_host():
    files = _web_files()
    names = {p.name for p in files}
    assert {"app.js", "ui.js", "index.html"} <= names, f"the page's own files were not found: {sorted(names)}"
    bad: list[str] = []
    for path in files:
        where = f"web/{path.relative_to(WEB).as_posix()}"
        try:
            text = _page_text(path.read_text(encoding="utf-8"), path.suffix)
        except ValueError as exc:
            raise AssertionError(f"{where} could not be read: {exc}") from exc
        for number, line in enumerate(text.splitlines(), 1):
            for match in RUNTIME_WORDS.finditer(line):
                bad.append(f"{where}:{number}: {match.group(0)!r} in {line.strip()[:160]!r}")
    assert not bad, "the page still names the runtime host:\n" + "\n".join(bad)
