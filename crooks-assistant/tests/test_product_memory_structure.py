"""The structural guard over canonical product memory.

Two things are proved here. First that the real ``docs/product-memory``
directory is clean, so the gate is meaningful rather than permanently red.
Second — and this is the part that matters — that each guard is load-bearing:
a directory corrupted in exactly one way is rejected for exactly that reason,
and repairing that one thing makes it pass again.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import product_memory_check as checker  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

CLEAN_INDEX = """# Index

## Files

- [ALPHA.md](./ALPHA.md) — the first document.
"""

CLEAN_DOC = """# Alpha

A paragraph of ordinary prose.

```json
{"quoted": "a \\" lives legitimately inside a fence"}
```
"""


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    directory = tmp_path / "product-memory"
    directory.mkdir()
    (directory / "README.md").write_text(CLEAN_INDEX, encoding="utf-8")
    (directory / "ALPHA.md").write_text(CLEAN_DOC, encoding="utf-8")
    return directory


def checks_raised(report: dict) -> set[str]:
    return {violation["check"] for violation in report["violations"]}


def test_the_real_product_memory_is_structurally_clean() -> None:
    """The gate is only worth running if the tree it guards can pass it."""

    report = checker.run()
    assert report["ok"], report["violations"]
    assert report["documents"] >= 20


def test_a_clean_fixture_passes_and_a_fence_may_quote_escapes(docs: Path) -> None:
    report = checker.run(docs)
    assert report["ok"], report["violations"]
    assert report["documents"] == 2


def test_literal_escaped_newline_is_rejected(docs: Path) -> None:
    """The corruption that fused DEC-052 onto a single line.

    The prose is entirely correct; only the two characters standing where a
    paragraph break belongs are wrong.
    """

    alpha = docs / "ALPHA.md"
    alpha.write_text("# Alpha\\n\\nA paragraph that never got its newlines.\n", encoding="utf-8")

    report = checker.run(docs)
    assert not report["ok"]
    assert checks_raised(report) == {"escaped_control_character"}

    # Load-bearing control: unescape that one thing and nothing else, and the
    # same directory passes — so the refusal above is this guard alone.
    alpha.write_text("# Alpha\n\nA paragraph that never got its newlines.\n", encoding="utf-8")
    assert checker.run(docs)["ok"]


@pytest.mark.parametrize("escape", ["\\n", "\\r", "\\t"])
def test_every_escaped_control_character_is_rejected(docs: Path, escape: str) -> None:
    (docs / "ALPHA.md").write_text(f"# Alpha\n\nprose{escape}more prose\n", encoding="utf-8")
    assert checks_raised(checker.run(docs)) == {"escaped_control_character"}


def test_escaped_quote_is_rejected_outside_a_fence_only(docs: Path) -> None:
    alpha = docs / "ALPHA.md"
    alpha.write_text('# Alpha\n\nShe said \\"hello\\" to nobody.\n', encoding="utf-8")
    assert checks_raised(checker.run(docs)) == {"escaped_quote"}

    # The identical text inside a fence is legitimate quoting, not corruption.
    alpha.write_text('# Alpha\n\n```\nShe said \\"hello\\".\n```\n', encoding="utf-8")
    assert checker.run(docs)["ok"]


def test_an_escaped_newline_is_rejected_even_inside_a_fence(docs: Path) -> None:
    """The control-character guard is deliberately not fence-aware.

    A fence may honestly quote a JSON string containing ``\\n``. We reject it
    anyway, because the corruption this guards against fuses the document onto
    one line — destroying the very fence a fence-aware reader would trust. A
    document that genuinely needs to show that escape can describe it instead.
    """

    (docs / "ALPHA.md").write_text(
        '# Alpha\n\n```json\n{"a": "x\\ny"}\n```\n', encoding="utf-8"
    )
    assert checks_raised(checker.run(docs)) == {"escaped_control_character"}


def test_a_document_missing_from_the_index_is_rejected(docs: Path) -> None:
    (docs / "BETA.md").write_text("# Beta\n\nUnindexed.\n", encoding="utf-8")

    report = checker.run(docs)
    assert checks_raised(report) == {"unindexed_document"}
    assert report["violations"][0]["path"] == "BETA.md"

    # Load-bearing control: index it and nothing else changes.
    index = docs / "README.md"
    index.write_text(index.read_text() + "- [BETA.md](./BETA.md) — the second.\n", encoding="utf-8")
    assert checker.run(docs)["ok"]


def test_an_index_link_to_a_missing_document_is_rejected(docs: Path) -> None:
    index = docs / "README.md"
    index.write_text(index.read_text() + "- [GONE.md](./GONE.md) — deleted.\n", encoding="utf-8")

    report = checker.run(docs)
    assert checks_raised(report) == {"dangling_index_link"}


def test_a_document_without_a_title_is_rejected(docs: Path) -> None:
    (docs / "ALPHA.md").write_text("Alpha\n=====\n\nSetext is not what we write.\n", encoding="utf-8")
    assert checks_raised(checker.run(docs)) == {"missing_title"}


def test_carriage_returns_are_rejected(docs: Path) -> None:
    (docs / "ALPHA.md").write_bytes(b"# Alpha\r\n\r\nWindows line endings.\r\n")
    assert "carriage_return" in checks_raised(checker.run(docs))


def test_a_missing_directory_fails_closed(tmp_path: Path) -> None:
    report = checker.run(tmp_path / "absent")
    assert not report["ok"]
    assert checks_raised(report) == {"missing_directory"}


def test_cli_exits_non_zero_and_emits_parseable_json_on_corruption(docs: Path) -> None:
    (docs / "ALPHA.md").write_text("# Alpha\\n\\nbroken\n", encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "product_memory_check.py"), "--json",
         "--docs", str(docs)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    report = json.loads(completed.stdout)
    assert report["ok"] is False
    assert checks_raised(report) == {"escaped_control_character"}


def test_cli_exits_zero_on_the_real_tree() -> None:
    completed = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "product_memory_check.py"), "--json"],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout
    assert json.loads(completed.stdout)["ok"] is True
