"""CURRENT_TRUTH.md says production is at dc59047e since 14 October 2026, and that clive/trunk
additionally contains DEC-079, which is on the trunk only.

Proved here, on the file as it stands in this checkout:

- the "As of" line and the Production row name `dc59047e` and 14 Oct 2026, and `b33ccbc2` is no
  longer named as what production is or stays on;
- the Trunk row is `dc59047e` plus DEC-079, and says DEC-079 is not deployed;
- no line that names DEC-079 says it is deployed or in production without saying "not";
- the file's headings and the live table's shape are unchanged.
"""

from __future__ import annotations

import re
from pathlib import Path

TRUTH = Path(__file__).resolve().parents[1] / "docs" / "product-memory" / "CURRENT_TRUTH.md"

HEADINGS = [
    "# CLIVE — Current Truth",
    "## Now — 2026-10-05",
    "### What is live",
    "### Production switches and what runs",
    "### CROOKS Returns: live beside CLIVE, not in it",
    "### Open pull requests",
    "### Merged, not deployed",
    "### The build loop",
    "### Recorded in DECISIONS on 5 October",
    "### Still the owner's",
    "### Not verified from here",
]


def _text() -> str:
    return TRUTH.read_text(encoding="utf-8")


def _lines() -> list[str]:
    return _text().split("\n")


def _row(label: str) -> list[str]:
    for line in _lines():
        if line.startswith(f"| **{label}**"):
            return [cell.strip() for cell in line.strip().strip("|").split("|")]
    raise AssertionError(f"no {label} row in the live table")


def _as_of() -> str:
    lines = [line for line in _lines() if line.startswith("**As of:**")]
    assert len(lines) == 1
    return lines[0]


def test_as_of_line_names_production_and_date():
    line = _as_of()
    assert "2026-10-14" in line
    assert "production is `dc59047e`" in line
    assert "`clive/trunk` additionally contains DEC-079" in line
    assert "not in production" in line
    assert "b33ccbc2" not in line


def test_production_row_is_dc59047e_since_14_october():
    label, sha, what = _row("Production")
    assert "`crooks-os-prod-1`" in label
    assert sha == "`dc59047e`"
    assert "Live since **14 Oct 2026**" in what
    assert "DEC-079" not in what


def test_trunk_row_is_production_plus_dec_079_only_on_trunk():
    label, sha, what = _row("Trunk")
    assert "`clive/trunk`" in label
    assert sha == "head"
    assert what.startswith("`dc59047e` plus [DEC-079]")
    assert "on the trunk only" in what
    assert "not deployed to production" in what


def test_dec_079_is_never_said_to_be_in_production():
    for line in _lines():
        if "DEC-079" not in line:
            continue
        for sentence in re.split(r"(?<=[.;])\s+", line):
            if re.search(r"deployed|in production|to production", sentence):
                assert re.search(r"\bnot\b", sentence), sentence


def test_b33ccbc2_is_no_longer_said_to_be_production():
    text = _text()
    assert "Production stays on `b33ccbc2`" not in text
    assert "production is `b33ccbc2`" not in text
    # Its deploy is kept, now among the deploys before production.
    before = text.split("The deploys before it, newest first:\n", 1)[1]
    assert before.startswith("- **`b33ccbc2`**, 3 Oct 17:48 UTC.")


def test_structure_is_preserved():
    headings = [line for line in _lines() if line.startswith("#")]
    assert headings == HEADINGS
    table = [line for line in _lines() if line.startswith("| ")]
    assert table[0] == "| | SHA | What it is |"
    assert [line.split("|")[1].strip() for line in table[1:4]] == [
        "**Production** (`crooks-os-prod-1`, `/opt/crooks-os`)",
        "**Trunk** (`clive/trunk`)",
        "**The loop** (clive-worker-01)",
    ]
