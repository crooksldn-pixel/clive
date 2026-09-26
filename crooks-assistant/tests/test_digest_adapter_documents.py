"""The documents adapter: sections with their heading paths, rules, checks, code examples and
claims read out of markdown, reStructuredText, plain text and HTML, with exact locations; HTML
read as text with its scripts dropped; and the shared adapter contract — read-only, bounded,
deterministic, and never raising on malformed input."""

from __future__ import annotations

import ast
import os
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
