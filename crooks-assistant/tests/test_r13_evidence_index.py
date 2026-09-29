"""The evidence for round 12's findings (docs/review/evidence/round12.json), held to what its README
says every entry is.

Round 12's review BLOCKED on findings whose reviewers could not settle them from the files they
were handed. An entry names the bodies and the tests that settle one; this keeps each entry true
to that: one entry for each of round 12's 62 blocking findings (an id the record gives twice has
two, told apart by their parts), every file in the tree, every excerpt a range of its file, every
entry's bodies within one review packet, and every test it names a test that exists — a pytest
node id (a parametrised one as pytest collects it) or a node test's title.
The node tests it names are run here too, so the ones no other test runs are run somewhere.
"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
INDEX = ROOT / "docs" / "review" / "evidence" / "round12.json"
NODE = shutil.which("node")

FIELDS = {"finding", "parts", "status", "question", "files", "tests", "answer"}
STATUSES = {"FIXED", "EVIDENCED", "DEPLOY-TIME", "LEFT", "LEFT (real defect found)"}
# "Kept under about 250 KB together, so that one entry, with its question, fits one review packet."
BUDGET = 250 * 1024
RANGE = re.compile(r"^lines (\d+)-(\d+)\b")

# All 62 of round 12's blocking findings, as round 13's fix map sorts them, with the ids as the record
# gives them. The record gives one id twice: R9-B2-B2-01 is a finding of the pages evidence and
# another of the screens-server evidence, and each has its own entry, told apart by its parts (the
# round-11 evidence file's: pages ['S3P'], screens-server ['S3P', 'S3']).
FINDINGS = [
    # Class A: real, blocking (fixed in round 13).
    "F/F-01", "O2/O2-N-01", "S2Ba/F-01", "S2b/S2b-01", "R9-E-families1-E-04", "R9-I-tests3-I-02", "S2b/S2b-03",
    "S1/S1-NEW-02", "R9-D1-D1-01", "S2Ba/F-02", "S2a/S2a-01", "R9-I-tests2-I-01", "R9-I-tests5-I-03", "R9-D1-D1-02",
    "R9-D2-D2-04", "R9-D2-D2-05", "S2T/S2T-01", "R9-D2-D2-01", "S6/S6-01", "T4/T4-02", "T6/T6-01", "S6/S6-02",
    "S6/S6-03", "S6/S6-04",
    # Class B: real, not a blocker as configured (fixed, or left with the reason).
    "O1/O1-01", "R9-A3b-F-A3B-SHORT-WRITE", "O2/O2-N-02", "S3/S3-02", "S5/S5-01", "S3/S3-01", "W2/W2-03", "T1/T1-02",
    "S3P/S3P-NEW-01", "R9-B2-B2-02", "R9-B2-B2-04", "R9-A1a-F-05B-AVAIL", "R9-B2-B2-01", "R9-A3b-F-04-SHUTDOWN",
    "R9-I-tests5-I-01",
    # Class D: not a defect once read; class C: not a blocker by the rule's own terms.
    "S3/S3-03", "S3T1/S3T1-01", "T5/T5-01", "R9-B1-B-01-B-05-PATH", "S2T/S2T-02", "S2a/S2a-03", "S2b/S2b-02",
    "T1/T1-01", "T3/T3-01", "T3/T3-02", "T4/T4-01", "T7/T7-01", "W3/W3-02", "S1-KEY-SENDER", "R9-B2-B2-01",
    "R9-G-G-01", "R9-C-C-03", "R9-H-experience1-H-04", "R9-D1-D1-03",
    "R9-G-G-03", "R9-B1-B-04", "R9-A3a-A3a-LIVE-CLEAN", "R9-E-families1-E-05",
]


def _entries() -> list[dict]:
    return json.loads(INDEX.read_text(encoding="utf-8"))


def _named_tests() -> list[tuple[str, str]]:
    return [tuple(t.split("::", 1)) for e in _entries() for t in e["tests"]]


def test_there_is_one_entry_for_each_finding_round_13_took_on():
    found = [e["finding"] for e in _entries()]
    assert len(FINDINGS) == 62
    assert Counter(found) == Counter(FINDINGS), (Counter(found) - Counter(FINDINGS), Counter(FINDINGS) - Counter(found))
    # An id the record gives twice is two findings, one entry each, told apart by their parts.
    parts = Counter((e["finding"], tuple(e["parts"])) for e in _entries())
    assert max(parts.values()) == 1, [key for key, n in parts.items() if n > 1]


def test_every_entry_is_the_shape_the_readme_gives():
    for e in _entries():
        assert FIELDS <= set(e) <= FIELDS | {"excerpts"}, e["finding"]
        assert e["status"] in STATUSES, e["finding"]
        assert isinstance(e["parts"], list) and all(isinstance(p, str) and p for p in e["parts"]), e["finding"]
        for key in ("question", "answer"):
            assert isinstance(e[key], str) and e[key].strip(), (e["finding"], key)
        assert e["files"] and e["tests"], e["finding"]
        assert len(set(e["files"])) == len(e["files"]) and len(set(e["tests"])) == len(e["tests"]), e["finding"]
        assert set(e.get("excerpts", {})) <= set(e["files"]), e["finding"]


def test_every_file_is_in_the_tree_and_every_excerpt_is_a_range_of_it():
    for e in _entries():
        for name in e["files"]:
            assert (REPO / name).is_file(), (e["finding"], name)
        for name, ranges in e.get("excerpts", {}).items():
            lines = (REPO / name).read_text(encoding="utf-8").count("\n") + 1
            assert ranges, (e["finding"], name)
            for text in ranges:
                span = RANGE.match(text)
                assert span, (e["finding"], name, text)
                first, last = int(span.group(1)), int(span.group(2))
                assert 1 <= first <= last <= lines, (e["finding"], name, text, lines)


def _bytes(name: str, ranges: list[str] | None) -> int:
    data = (REPO / name).read_bytes()
    if not ranges:
        return len(data)
    lines = data.split(b"\n")
    total = 0
    for text in ranges:
        span = RANGE.match(text)
        first, last = int(span.group(1)), int(span.group(2))
        total += sum(len(line) + 1 for line in lines[first - 1:last])
    return total


def test_each_entrys_bodies_fit_one_review_packet():
    for e in _entries():
        size = sum(_bytes(name, e.get("excerpts", {}).get(name)) for name in e["files"])
        assert size <= BUDGET, (e["finding"], size)


def _defined(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_every_test_named_is_one_that_exists():
    parametrised: dict[str, set[str]] = {}
    for path, name in _named_tests():
        where = REPO / path
        assert where.is_file(), path
        if path.endswith(".py"):
            assert name.split("[", 1)[0] in _defined(where), f"{path}::{name}"
            if "[" in name:
                parametrised.setdefault(path, set()).add(name)
        else:
            source = where.read_text(encoding="utf-8").replace("\\'", "'")
            assert any(f"test({q}{name}{q}" in source for q in ("'", '"', "`")), f"{path}::{name}"
    for path, names in parametrised.items():
        # As pytest itself names them: collected, not guessed.
        collected = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", str(REPO / path)],
            cwd=ROOT, capture_output=True, text=True, timeout=300)
        ids = {line.split("::", 1)[1] for line in collected.stdout.splitlines() if "::" in line}
        assert names <= ids, (path, sorted(names - ids))


@pytest.mark.skipif(NODE is None, reason="node is not installed here")
@pytest.mark.parametrize("name", sorted({p for p, _ in _named_tests() if p.endswith(".test.js")}))
def test_the_node_tests_the_index_names_pass(name):
    result = subprocess.run([NODE, "--test", str(REPO / name)], capture_output=True, text=True, timeout=180, cwd=ROOT)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout
