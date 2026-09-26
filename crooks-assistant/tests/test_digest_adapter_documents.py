"""The documents adapter: sections with their heading paths, rules, checks, code examples and
claims read out of markdown, reStructuredText, plain text and HTML, with exact locations; HTML
read as text with its scripts dropped; and the shared adapter contract — read-only, bounded,
deterministic, and never raising on malformed input."""

from __future__ import annotations

import ast
import os
import signal
import tracemalloc
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.digest import Artifact, Location, Source, Unit, content_digest
from app.digest.adapters import documents
from app.digest.model import MAX_BODY, MAX_TITLE

SOURCE = Source(
    origin="/quarantine/docs", origin_kind="directory", pinned_ref=content_digest(b"docs"),
    licence=None, taken_at="2026-09-26T10:00:00+00:00", content_digest=content_digest(b"docs"),
)
ARTIFACT = SOURCE.artifact_id

GUIDE = "\n".join([
    "# Guide",                                                                   # 1
    "",
    "Read the [manual](https://example.invalid/manual).",                        # 3
    "",
    "## Rules",                                                                  # 5
    "",
    "- Always run the tests before merging.",                                    # 7
    "- Never commit secrets; see [the policy](https://example.invalid/policy).",
    "- The cache lives in memory",                                               # 9
    "",
    "## Checklist",                                                              # 11
    "",
    "- [ ] Write the changelog",                                                 # 13
    "- [x] Bump the version",
    "",                                                                          # 15
    "### Example",
    "",                                                                          # 17
    "```python",
    "print('hello')",                                                            # 19
    "```",
    "",                                                                          # 21
    "## Facts",
    "",                                                                          # 23
    "The service answers 500 requests per second. It shipped on 2024-03-01.",
    "Deploys are always reviewed.",                                              # 25
    "The new index is faster than the [old one](https://example.invalid/v1).",
    "Is it 3 times faster? Nobody said.",                                        # 27
]) + "\n"

INSTALL = "\n".join([
    "Install",                                                                   # 1
    "=======",
    "",                                                                          # 3
    "Use a virtual environment.",
    "",                                                                          # 5
    "Options",
    "-------",                                                                   # 7
    "",
    "- Pin every version.",                                                      # 9
    "- Keep the image small.",
    "- Images are rebuilt nightly",                                              # 11
    "",
    ".. code-block:: bash",                                                      # 13
    "",
    "   pip install thing",                                                      # 15
    "",
    "The download is 10 MB.",                                                    # 17
]) + "\n"

NOTES = "\n".join([
    "Release notes for the team.",                                               # 1
    "",
    "- [ ] Tag the release",                                                     # 3
    "- Always sign the tag.",
    "",                                                                          # 5
    "Version 2 replaced version 1 in March 2024.",
]) + "\n"

HANDBOOK = "\n".join([
    "<!DOCTYPE html>",                                                           # 1
    "<html><head><title>Handbook page</title>",
    "<style>p { color: red }</style>",                                           # 3
    '<script>document.title = "never 42";</script>',
    "</head><body>",                                                             # 5
    "<h1>Handbook</h1>",
    '<p>Read the <a href="https://example.invalid/policy">policy</a> first.</p>',  # 7
    "<h2>Duties</h2>",
    "<ul>",                                                                      # 9
    "<li>Always lock the door.</li>",
    '<li><input type="checkbox"> Water the plants</li>',                         # 11
    '<li><input type="checkbox" checked> Feed the cat</li>',
    "</ul>",                                                                     # 13
    '<pre><code class="language-python">total = 1',
    "print(total)</code></pre>",                                                 # 15
    '<p onclick="steal()">The shop opens 7 days a week.</p>',
    '<script src="tracker.js"></script>',                                        # 17
    "</body></html>",
]) + "\n"

FIXTURES = {
    "guide.md": GUIDE,
    "docs/install.rst": INSTALL,
    "docs/notes.txt": NOTES,
    "site/handbook.html": HANDBOOK,
}


def _write(root: Path, files: dict[str, str | bytes]) -> Path:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _one(tmp_path: Path, name: str, content: str | bytes) -> list[Unit]:
    return documents.decompose(_write(tmp_path / "art", {name: content}), ARTIFACT)


def _rows(units: list[Unit]) -> list[tuple]:
    return [
        (u.kind, u.title, u.body, u.location.path, u.location.line_start, u.location.line_end, u.tags)
        for u in units
    ]


class _TooSlow(BaseException):
    """Raised by _deadline; not an Exception, so an adapter's catch-all cannot swallow it."""


@contextmanager
def _deadline(seconds: float):
    """Fails the block when it runs longer than seconds — a pattern that backtracks without
    bound is interrupted rather than left to run for hours."""
    if not hasattr(signal, "setitimer"):
        pytest.skip("no interval timer on this platform")

    def expire(*_):
        raise _TooSlow(f"took longer than {seconds} seconds")

    previous = signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _snapshot(root: Path) -> dict[str, tuple[bytes, int] | None]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        if path.is_file() else None
        for path in root.rglob("*")
    }


# --- what is read out of each kind of document -----------------------------------------------


def test_markdown_sections_rules_checks_examples_and_claims(tmp_path):
    facts = "\n".join(GUIDE.splitlines()[23:27])
    assert _rows(_one(tmp_path, "guide.md", GUIDE)) == [
        ("knowledge", "Guide", "Read the [manual](https://example.invalid/manual).", "guide.md", 1, 3, ()),
        ("knowledge", "Guide > Rules",
         "- Always run the tests before merging.\n"
         "- Never commit secrets; see [the policy](https://example.invalid/policy).\n"
         "- The cache lives in memory", "guide.md", 5, 9, ()),
        ("rule", "Guide > Rules", "Always run the tests before merging.", "guide.md", 7, 7, ()),
        ("rule", "Guide > Rules",
         "Never commit secrets; see [the policy](https://example.invalid/policy).", "guide.md", 8, 8, ()),
        ("knowledge", "Guide > Checklist", "- [ ] Write the changelog\n- [x] Bump the version",
         "guide.md", 11, 14, ()),
        ("check", "Guide > Checklist", "Write the changelog", "guide.md", 13, 13, ("open",)),
        ("check", "Guide > Checklist", "Bump the version", "guide.md", 14, 14, ("done",)),
        ("knowledge", "Guide > Checklist > Example", "```python\nprint('hello')\n```",
         "guide.md", 16, 20, ()),
        ("example", "Guide > Checklist > Example", "print('hello')", "guide.md", 18, 20, ("python",)),
        ("knowledge", "Guide > Facts", facts, "guide.md", 22, 27, ()),
        ("claim", "Guide > Facts", "The service answers 500 requests per second.", "guide.md", 24, 24, ("number",)),
        ("claim", "Guide > Facts", "It shipped on 2024-03-01.", "guide.md", 24, 24, ("date",)),
        ("claim", "Guide > Facts", "Deploys are always reviewed.", "guide.md", 25, 25, ("always",)),
        ("claim", "Guide > Facts",
         "The new index is faster than the [old one](https://example.invalid/v1).", "guide.md", 26, 26, ("comparison",)),
    ]


def test_restructuredtext_titles_rules_code_and_claims(tmp_path):
    options = "\n".join(INSTALL.splitlines()[8:17])
    assert _rows(_one(tmp_path, "install.rst", INSTALL)) == [
        ("knowledge", "Install", "Use a virtual environment.", "install.rst", 1, 4, ()),
        ("knowledge", "Install > Options", options, "install.rst", 6, 17, ()),
        ("rule", "Install > Options", "Pin every version.", "install.rst", 9, 9, ()),
        ("rule", "Install > Options", "Keep the image small.", "install.rst", 10, 10, ()),
        ("example", "Install > Options", "pip install thing", "install.rst", 13, 15, ("bash",)),
        ("claim", "Install > Options", "The download is 10 MB.", "install.rst", 17, 17, ("number",)),
    ]


def test_plain_text_is_one_section_with_its_checks_rules_and_claims(tmp_path):
    assert _rows(_one(tmp_path, "notes.txt", NOTES)) == [
        ("knowledge", "notes.txt", NOTES.rstrip("\n"), "notes.txt", 1, 6, ()),
        ("check", "notes.txt", "Tag the release", "notes.txt", 3, 3, ("open",)),
        ("rule", "notes.txt", "Always sign the tag.", "notes.txt", 4, 4, ()),
        ("claim", "notes.txt", "Version 2 replaced version 1 in March 2024.", "notes.txt", 6, 6,
         ("date", "number")),
    ]


def test_html_is_read_as_text_with_links_kept_and_scripts_dropped(tmp_path):
    units = _one(tmp_path, "handbook.html", HANDBOOK)
    duties = (
        "- Always lock the door.\n\n- [ ] Water the plants\n\n- [x] Feed the cat\n\n"
        "```python\ntotal = 1\nprint(total)\n```\n\nThe shop opens 7 days a week."
    )
    assert _rows(units) == [
        ("knowledge", "handbook.html", "Handbook page", "handbook.html", 2, 2, ()),
        ("knowledge", "Handbook", "Read the [policy](https://example.invalid/policy) first.",
         "handbook.html", 6, 7, ()),
        ("knowledge", "Handbook > Duties", duties, "handbook.html", 8, 16, ()),
        ("rule", "Handbook > Duties", "Always lock the door.", "handbook.html", 10, 10, ()),
        ("check", "Handbook > Duties", "Water the plants", "handbook.html", 11, 11, ("open",)),
        ("check", "Handbook > Duties", "Feed the cat", "handbook.html", 12, 12, ("done",)),
        ("example", "Handbook > Duties", "total = 1\nprint(total)", "handbook.html", 14, 15, ("python",)),
        ("claim", "Handbook > Duties", "The shop opens 7 days a week.", "handbook.html", 16, 16, ("number",)),
    ]
    text = "\n".join(u.title + "\n" + u.body for u in units)
    for unread in ("document.title", "never 42", "color", "tracker", "steal", "<"):
        assert unread not in text


def test_an_html_link_around_blocks_keeps_its_target_in_each(tmp_path):
    units = _one(tmp_path, "page.html", "\n".join([
        "<h1>Links</h1>",                                                        # 1
        '<a href="/guide"><p>Read the guide.</p>',
        "<p>Then the index.</p></a>",                                            # 3
    ]) + "\n")
    assert _rows(units) == [
        ("knowledge", "Links", "[Read the guide.](/guide)\n\n[Then the index.](/guide)",
         "page.html", 1, 3, ()),
    ]


def test_html_end_tags_that_may_be_left_out_are_not_reported(tmp_path):
    units = _one(tmp_path, "page.html", "\n".join([
        "<html><head><title>Omitted</title>",                                    # 1
        "<body><h1>Lists</h1>",
        "<ul><li>Rotate keys<li>Escalate incidents</ul>",                        # 3
        "<p>First paragraph<p>Second paragraph",
        "<dl><dt>Term<dd>Meaning</dl>",                                          # 5
        "<table><tr><td>a<td>b<tr><td>c</table>",
        "<p>Line<br>break<br/><img src=x.png><hr>",                              # 7
        "<table><tr><td>d</tbody></table>",
        "<table><col></colgroup><tr><td>e</table>",                              # 9
        "</body></html>",
    ]) + "\n")
    assert not [unit for unit in units if "unparsed" in unit.tags]
    assert [(u.body, u.location.line_start) for u in units if u.kind == "rule"] == [
        ("Rotate keys", 3), ("Escalate incidents", 3),
    ]


def test_mismatched_html_is_reported_and_what_was_read_is_kept(tmp_path):
    units = _one(tmp_path, "page.html", "<h1>Heading</h2>\n<p>Body text.</p>\n")
    assert _rows(units[:-1]) == [("knowledge", "Heading", "Body text.", "page.html", 1, 2, ())]
    report = units[-1]
    assert "unparsed" in report.tags and report.location == Location("page.html", 1, 1)
    assert "</h2> at line 1 closes nothing that is open" in report.body
    assert "<h1> opened at line 1 is never closed" in report.body


def test_bullets_that_give_commands_are_rules_and_statements_are_not(tmp_path):
    units = _one(tmp_path, "ops.md", "\n".join([
        "# Ops",                                                                 # 1
        "",
        "- Test the backup.",                                                    # 3
        "- Document the API.",
        "- Monitor disk usage.",                                                 # 5
        "- Archive old logs.",
        "- Defragment every disk.",                                              # 7
        "- Rotate keys.",
        "- Escalate incidents",                                                  # 9
        "- Quarantine unknown files.",
        "- Shut down idle servers.",                                             # 11
        "- Backups run nightly.",
        "- The cache lives in memory",                                           # 13
        "- Monitoring covers the API.",
        "- Release notes are in the wiki.",                                      # 15
        "- Data lives in memory.",
        "- Cache stores the index.",                                             # 17
        "- Offline support",
        "- Configuration files.",                                                # 19
        "- Critical alerts",
        "- Rotate key",                                                          # 21
        "- Escalate incident",
        "- Normalise path",                                                      # 23
        "- Private key",
        "- Certificate chain",                                                   # 25
        "- State machine",
    ]) + "\n")
    assert [(u.body, u.location.line_start) for u in units if u.kind == "rule"] == [
        ("Test the backup.", 3), ("Document the API.", 4), ("Monitor disk usage.", 5),
        ("Archive old logs.", 6), ("Defragment every disk.", 7), ("Rotate keys.", 8),
        ("Escalate incidents", 9), ("Quarantine unknown files.", 10),
        ("Shut down idle servers.", 11), ("Rotate key", 21), ("Escalate incident", 22),
        ("Normalise path", 23),
    ]


def test_ascii_comparisons_are_claims_and_markup_is_not(tmp_path):
    root = _write(tmp_path / "art", {
        "order.md": "\n".join([
            "# Order",                                                           # 1
            "",
            "Primary > secondary.",                                              # 3
            "",
            "Minimum <= maximum.",                                               # 5
            "",
            "See <https://example.invalid/a> and <kbd>Ctrl</kbd>; a -> b => c <!-- note -->.",
            "",
            "> Quoted words.",                                                   # 9
        ]) + "\n",
        "order.txt": "Load >= capacity. Spare < used.\n",
    })
    assert [row for row in _rows(documents.decompose(root, ARTIFACT)) if row[0] == "claim"] == [
        ("claim", "Order", "Primary > secondary.", "order.md", 3, 3, ("comparison",)),
        ("claim", "Order", "Minimum <= maximum.", "order.md", 5, 5, ("comparison",)),
        ("claim", "order.txt", "Load >= capacity.", "order.txt", 1, 1, ("comparison",)),
        ("claim", "order.txt", "Spare < used.", "order.txt", 1, 1, ("comparison",)),
    ]


def test_questions_link_targets_and_code_are_not_claims(tmp_path):
    units = _one(tmp_path, "faq.md", "\n".join([
        "# FAQ",
        "",
        "Does it take 5 minutes? See [part two](https://example.invalid/2) and `retry(3)`.",
        "",
        "    x = 10",
    ]) + "\n")
    assert [u.kind for u in units] == ["knowledge", "example"]
    assert units[1].body == "x = 10" and units[1].tags == ()
    assert "[part two](https://example.invalid/2)" in units[0].body


# --- the shared contract ---------------------------------------------------------------------


def test_the_adapter_names_itself_and_what_it_handles():
    assert documents.NAME == "documents"
    assert isinstance(documents.HANDLES, tuple) and documents.HANDLES
    assert all(isinstance(kind, str) and kind for kind in documents.HANDLES)
    assert "document" in documents.HANDLES


def test_units_fit_the_model_and_one_artifact(tmp_path):
    units = documents.decompose(_write(tmp_path / "art", FIXTURES), ARTIFACT)
    artifact = Artifact(source=SOURCE, kinds=("document",), units=tuple(units))
    assert len(artifact.units) == len(units)
    for unit in units:
        assert Unit.from_dict(unit.to_dict()) == unit


def test_the_same_documents_give_the_same_units_in_the_same_order(tmp_path):
    one = _write(tmp_path / "one", FIXTURES)
    two = _write(tmp_path / "two", dict(reversed(FIXTURES.items())))
    first = [unit.to_dict() for unit in documents.decompose(one, ARTIFACT)]
    assert first == [unit.to_dict() for unit in documents.decompose(one, ARTIFACT)]
    assert first == [unit.to_dict() for unit in documents.decompose(two, ARTIFACT)]
    paths = list(dict.fromkeys(unit["location"]["path"] for unit in first))
    assert paths == ["guide.md", "docs/install.rst", "docs/notes.txt", "site/handbook.html"]


def test_reading_changes_nothing_and_reads_only_documents(tmp_path):
    root = _write(tmp_path / "art", {
        **FIXTURES,
        "setup.py": "raise SystemExit('this ran')\n",
        "package.json": '{"scripts": {"postinstall": "touch pwned"}}\n',
        ".git/notes.md": "# Internal\n",
    })
    before = _snapshot(root)
    units = documents.decompose(root, ARTIFACT)
    assert _snapshot(root) == before
    assert {unit.location.path for unit in units} == set(FIXTURES)


def test_the_adapter_only_reads_and_uses_the_standard_library():
    tree = ast.parse(Path(documents.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    assert imported <= {
        "__future__", "bisect", "collections.abc", "dataclasses", "html.parser", "os",
        "pathlib", "re", "stat", "app.digest.model",
        "app.digest.adapters.skills",   # to leave the skills adapter the files it owns
    }
    calls = [node.func for node in ast.walk(tree) if isinstance(node, ast.Call)]
    names = {func.id for func in calls if isinstance(func, ast.Name)}
    attributes = {func.attr for func in calls if isinstance(func, ast.Attribute)}
    assert not names & {"eval", "exec", "compile", "__import__"}
    assert not attributes & {
        "system", "popen", "spawnv", "execv", "write", "write_text", "write_bytes", "unlink",
        "rmdir", "rename", "mkdir", "chmod", "import_module",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            assert [ast.literal_eval(arg) for arg in node.args[1:2]] == ["rb"]


def test_an_artifact_id_that_is_not_one_is_refused(tmp_path):
    with pytest.raises(ValueError):
        documents.decompose(tmp_path, "not-an-artifact")


# --- bounds ----------------------------------------------------------------------------------


def test_bodies_and_titles_are_cut_to_the_model_bounds(tmp_path):
    units = _one(tmp_path, "long.md", "# " + "H" * 300 + "\n\n" + "word " * 5000 + "\n")
    assert len(units) == 1
    assert len(units[0].title) == MAX_TITLE
    assert len(units[0].body) <= MAX_BODY and "truncated" in units[0].tags


def test_a_document_too_large_is_reported_not_read(tmp_path, monkeypatch):
    monkeypatch.setattr(documents, "MAX_FILE_BYTES", 64)
    root = _write(tmp_path / "art", {"big.md": "# Big\n\n" + "Always 1.\n" * 20, "small.md": "# Small\n"})
    assert _rows(documents.decompose(root, ARTIFACT)) == [
        ("knowledge", "Unparsed: big.md", "larger than 64 bytes; not read", "big.md", None, None, ("unparsed",)),
        ("knowledge", "Small", "", "small.md", 1, 1, ()),
    ]


def test_the_number_of_documents_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(documents, "MAX_DOCUMENTS", 2)
    root = _write(tmp_path / "art", {"a.md": "# A\n", "b.md": "# B\n", "c.md": "# C\n"})
    units = documents.decompose(root, ARTIFACT)
    assert [unit.title for unit in units] == ["A", "B", "Unparsed: the artifact"]
    assert "more than 2 documents" in units[-1].body


def test_the_number_of_units_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(documents, "MAX_UNITS", 5)
    root = _write(tmp_path / "art", {
        "a.md": "# Steps\n\n" + "".join(f"- Run step {n}.\n" for n in range(20)),
        "b.md": "# Never read\n",
    })
    units = documents.decompose(root, ARTIFACT)
    assert len(units) <= 6
    assert units[-1].location == Location(".") and "unparsed" in units[-1].tags
    assert "stopped after 5 units" in units[-1].body
    assert all(unit.location.path != "b.md" for unit in units)


def test_the_walk_is_bounded_in_depth_and_entries(tmp_path, monkeypatch):
    root = _write(tmp_path / "art", {"top.md": "# Top\n", "one/mid.md": "# Mid\n", "one/two/deep.md": "# Deep\n"})
    monkeypatch.setattr(documents, "MAX_DEPTH", 1)
    units = documents.decompose(root, ARTIFACT)
    assert [(unit.title, unit.location.path) for unit in units] == [
        ("Top", "top.md"), ("Mid", "one/mid.md"), ("Unparsed: one/two", "one/two"),
    ]
    monkeypatch.setattr(documents, "MAX_ENTRIES", 1)
    units = documents.decompose(root, ARTIFACT)
    assert all("unparsed" in unit.tags for unit in units)
    assert "more than 1 entries" in units[0].body


# --- malformed input -------------------------------------------------------------------------


def test_malformed_input_is_reported_as_unparsed_never_raised(tmp_path):
    root = _write(tmp_path / "art", {
        "bad.md": b"# Title\n\xff\xfe not utf-8\n",
        "blob.html": b"<p>hi</p>\x00\x01",
        "open.md": "# Code\n\n```sh\necho hi\n\n## Not a heading\n",
        "broken.html": "<p><a href='x'>unterminated <div <<>> <![if !mso]> </scr <pre class='language-'>\n",
        "broken.rst": "::\n\n.. code-block::\n\n=====\n\n- [\n",
        "empty.md": "",
    })
    units = documents.decompose(root, ARTIFACT)
    Artifact(source=SOURCE, kinds=("document",), units=tuple(units))
    unparsed = {unit.location.path: unit for unit in units if "unparsed" in unit.tags}
    assert all(unit.kind == "knowledge" for unit in unparsed.values())
    assert "not UTF-8" in unparsed["bad.md"].body
    assert "NUL" in unparsed["blob.html"].body
    assert "never closed" in unparsed["open.md"].body
    assert unparsed["open.md"].location == Location("open.md", 3, 6)
    example = next(u for u in units if u.kind == "example" and u.location.path == "open.md")
    assert example.tags == ("sh",) and example.body == "echo hi\n\n## Not a heading"
    assert not any(unit.title.endswith("Not a heading") for unit in units)
    assert not any(unit.location.path == "empty.md" for unit in units)


@pytest.mark.parametrize(("tail", "said"), [
    ("<script>\nsteal()\n<p>Lost words</p>\n", "<script> opened at line 3 is never closed"),
    ("<style>\np { color: red }\n<p>Lost words</p>\n", "<style> opened at line 3 is never closed"),
    ('<p>See <a href="https://example.invalid/x">the page</p>\n', "<a> opened at line 3 is never closed"),
    ("<pre>\nx = 1\n", "<pre> opened at line 3 is never closed"),
    ("<ul>\n<li>Test the backup.</li>\n", "<ul> opened at line 3 is never closed"),
    ("<p>More text.</p></script></a>\n", "</script> at line 3 closes nothing that is open"),
    ("<h2>Unclosed heading\n", "<h2> opened at line 3 is never closed"),
    ("<div><p>More text.</p>\n", "<div> opened at line 3 is never closed"),
    ("<h2>Mismatched</h3>\n", "</h3> at line 3 closes nothing that is open"),
    ("<p>More text.</p></tbody>\n", "</tbody> at line 3 closes nothing that is open"),
    ("<p>More text.</p></head>\n", "</head> at line 3 closes nothing that is open"),
    ("<section><h2>Cut short</section>\n",
     "<h2> opened at line 3 is never closed before </section> at line 3"),
])
def test_malformed_html_the_parser_lets_pass_is_reported_as_unparsed(tmp_path, tail, said):
    units = _one(tmp_path, "page.html", "<h1>Top</h1>\n<p>Kept text.</p>\n" + tail)
    assert (units[0].kind, units[0].title) == ("knowledge", "Top")
    assert units[0].body.startswith("Kept text.")
    report = units[-1]
    assert [unit for unit in units if "unparsed" in unit.tags] == [report]
    assert report.kind == "knowledge" and report.location == Location("page.html", 3, 3)
    assert said in report.body
    read = "\n".join(unit.body for unit in units[:-1])
    for unread in ("steal", "Lost", "color"):
        assert unread not in read


def test_the_report_on_malformed_html_is_bounded(tmp_path):
    units = _one(tmp_path, "page.html", "<p>Text.</p>" + "</a>" * 50 + "\n")
    report = units[-1]
    assert "unparsed" in report.tags and report.location == Location("page.html", 1, 1)
    assert report.body.count("closes nothing") == 20 and report.body.endswith("and 30 more.")


def test_a_missing_root_is_reported_and_a_single_file_is_read(tmp_path):
    assert _rows(documents.decompose(tmp_path / "absent", ARTIFACT)) == [
        ("knowledge", "Unparsed: the artifact",
         "the artifact could not be read: No such file or directory", ".", None, None, ("unparsed",)),
    ]
    single = tmp_path / "one.md"
    single.write_text("# One\n\nAlways 3.\n", encoding="utf-8")
    assert _rows(documents.decompose(single, ARTIFACT)) == [
        ("knowledge", "One", "Always 3.", "one.md", 1, 3, ()),
        ("claim", "One", "Always 3.", "one.md", 3, 3, ("number", "always")),
    ]


def test_links_on_disk_are_not_followed(tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("# Secret\n\nThe vault code is 1234.\n", encoding="utf-8")
    root = tmp_path / "art"
    root.mkdir()
    (root / "link.md").symlink_to(outside)
    (root / "linked").symlink_to(tmp_path, target_is_directory=True)
    assert _rows(documents.decompose(root, ARTIFACT)) == [
        ("knowledge", "Unparsed: link.md", "a symbolic link, not followed", "link.md", None, None, ("unparsed",)),
    ]


def test_a_root_that_is_a_link_is_not_followed(tmp_path):
    outside = _write(tmp_path / "outside", {"secret.md": "# Secret\n\nThe vault code is 1234.\n"})
    folder = tmp_path / "art"
    folder.symlink_to(outside, target_is_directory=True)
    single = tmp_path / "one.md"
    single.symlink_to(outside / "secret.md")
    for root in (folder, single):
        assert _rows(documents.decompose(root, ARTIFACT)) == [
            ("knowledge", "Unparsed: the artifact", "the artifact is a symbolic link, not followed",
             ".", None, None, ("unparsed",)),
        ]


def test_a_name_that_is_not_utf8_is_reported_not_read(tmp_path):
    root = tmp_path / "art"
    root.mkdir()
    try:
        (root / os.fsdecode(b"caf\xe9.md")).write_text("# Hidden\n", encoding="utf-8")
    except (OSError, UnicodeError):
        pytest.skip("this filesystem refuses names that are not UTF-8")
    (root / "fine.md").write_text("# Fine\n", encoding="utf-8")
    units = documents.decompose(root, ARTIFACT)
    assert [unit.title for unit in units] == ["Unparsed: the artifact", "Fine"]
    assert "not UTF-8" in units[0].body
    Artifact(source=SOURCE, kinds=("document",), units=tuple(units))


# --- hostile input: bounded in time and memory -----------------------------------------------


def test_a_long_run_of_stops_is_read_in_linear_time(tmp_path):
    """A run of full stops with no space after it was retried from each of its characters, so
    60 000 of them took most of a minute and a 2 MB file hours."""
    root = _write(tmp_path / "art", {
        "dots.md": "# Dots\n\n" + "." * 60_000 + "\n\n" + "!?" * 30_000 + "x\n\nIt is 5 km.\n",
    })
    with _deadline(5):
        units = documents.decompose(root, ARTIFACT)
    assert [(u.kind, u.body) for u in units if u.kind == "claim"] == [("claim", "It is 5 km.")]


def test_an_html_link_left_open_across_blocks_cannot_blow_up_the_text(tmp_path):
    """A link left open repeats its target in every block it reaches: a 30 kB page once grew
    to 40 MB of text in memory, and a 2 MB page to hundreds of gigabytes. The text a page gives
    is now bounded by its length, and the cut is reported."""
    page = '<h1>Links</h1>\n<a href="https://example.invalid/' + "x" * 20_000 + '">' + "<p>a\n" * 2_000
    root = _write(tmp_path / "art", {"page.html": page})
    tracemalloc.start()
    try:
        units = documents.decompose(root, ARTIFACT)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < 10_000_000
    assert units[0].title == "Links" and units[0].body.startswith("[a](https://example.invalid/xx")
    report = units[-1]
    assert "unparsed" in report.tags and report.location.path == "page.html"
    assert "the rest was not read" in report.body
    Artifact(source=SOURCE, kinds=("document",), units=tuple(units))


def test_html_text_that_looks_like_markdown_is_read_as_prose(tmp_path):
    """HTML is read as text: a paragraph that opens with a fence, a hash or a dash is prose, not
    a code block that swallows the rest of the page, a heading or a rule."""
    units = _one(tmp_path, "page.html", "\n".join([
        "<h1>Markdown</h1>",                                                     # 1
        "<p>```</p>",
        "<p># of users</p>",                                                     # 3
        "<p>- Keep the lid closed.</p>",
        "<h2>Next</h2>",                                                         # 5
        "<ul><li>Lock the door.</li></ul>",
    ]) + "\n")
    assert _rows(units) == [
        ("knowledge", "Markdown", "```\n\n# of users\n\n- Keep the lid closed.", "page.html", 1, 4, ()),
        ("knowledge", "Markdown > Next", "- Lock the door.", "page.html", 5, 6, ()),
        ("rule", "Markdown > Next", "Lock the door.", "page.html", 6, 6, ()),
    ]


def test_the_bytes_read_from_one_artifact_are_bounded(tmp_path, monkeypatch):
    """Each document was bounded, but not all of them together: a thousand 2 MB documents were
    all read. Documents past the artifact's reading budget are reported, not read."""
    monkeypatch.setattr(documents, "MAX_TOTAL_BYTES", 150, raising=False)
    root = _write(tmp_path / "art", {
        "a.md": "# A\n\n" + "Word. " * 14 + "Word.\n",
        "b.md": "# B\n\n" + "Word. " * 14 + "Word.\n",
        "c.md": "# C\n",
    })
    rows = _rows(documents.decompose(root, ARTIFACT))
    assert [row[:4] for row in rows] == [
        ("knowledge", "A", "Word. " * 14 + "Word.", "a.md"),
        ("knowledge", "Unparsed: b.md", "the 150-byte reading budget for the artifact was spent; not read", "b.md"),
        ("knowledge", "C", "", "c.md"),
    ]



# --- found by the first real digestions (2026-09-26) ---------------------------------------------


def test_skills_harness_files_and_prompts_are_left_to_the_skills_adapter(tmp_path):
    # Leonxlnx/taste-skill: every SKILL.md was read twice, as a skill and as prose, and 160 of one
    # file's 854 spans came out as two different Units.
    root = tmp_path / "collection"
    for rel, text in {
        "README.md": "# Collection\n\nAlways read the skill first.\n",
        "skills/taste/SKILL.md": "---\nname: taste\ndescription: d\n---\n# Taste\n\n- Never use purple.\n",
        "skills/taste/references/tokens.md": "# Tokens\n\nSpacing is 8px.\n",
        "AGENTS.md": "# Agents\n\n- Always run the tests.\n",
        "prompts/review.md": "Review this.\n",
        "docs/prompt-caching.md": "# Caching\n\nIt is a prefix match.\n",
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    read = {unit.location.path for unit in documents.decompose(root, ARTIFACT)}
    assert read == {"README.md", "skills/taste/references/tokens.md", "docs/prompt-caching.md"}


def test_a_bold_lead_in_does_not_hide_the_guideline_after_it(tmp_path):
    # vercel-labs/web-interface-guidelines: "**Links are links.** Use <a> ..." lost its rule, and
    # its "Never substitute ..." came back as a claim to verify.
    text = (
        "# Guide\n\n"
        "- **Links are links.** Use `<a>` for navigation. Never substitute with `<button>`.\n"
        "- **Deep-link everything.** Filters, tabs and pagination.\n"
        "- **Colour** is decided by the brand team.\n\n"
        "Never exceed 100 ms for a tap response. Deploys are always reviewed.\n"
    )
    rows = _rows(_one(tmp_path, "guide.md", text))
    rules = [row[2] for row in rows if row[0] == "rule"]
    assert rules[0].startswith("**Links are links.** Use `<a>`") and rules[1].startswith("**Deep-link everything.**")
    assert len(rules) == 2                                   # a lead-in that states is not a rule
    claims = {row[2]: row[6] for row in rows if row[0] == "claim"}
    assert claims == {
        "Never exceed 100 ms for a tap response.": ("number", "comparison"),   # a directive, but checkable
        "Deploys are always reviewed.": ("always",),
    }
