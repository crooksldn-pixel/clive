"""The repo is public: no customer's parcel may be traceable from anything in it.

A Royal Mail (UPU S10) tracking number opens that parcel's journey to anyone, so a fixture
must never carry one copied from a live order. Real ones carry a valid check digit; made-up
ones in the tests deliberately don't, so this scan tells them apart.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WHERE = ("clive-shipping", "crooks-returns", "docs", "ops-shell")
TEXT = {".py", ".cjs", ".js", ".md", ".html", ".json", ".toml", ".txt", ".liquid"}
# Two letters, eight digits and a check digit (spaces allowed between them), two letters.
S10 = re.compile(
    r"(?<![A-Z0-9])([A-Z]{2}) ?((?:\d ?){8})(\d) ?([A-Z]{2})(?![A-Z0-9])", re.IGNORECASE
)
WEIGHTS = (8, 6, 4, 2, 3, 5, 9, 7)


def check_digit(serial: str) -> int:
    left = 11 - sum(int(d) * w for d, w in zip(serial, WEIGHTS, strict=True)) % 11
    return {10: 0, 11: 5}.get(left, left)


def real_looking(text: str) -> list[str]:
    return [
        m.group(0)
        for m in S10.finditer(text)
        if check_digit(m.group(2).replace(" ", "")) == int(m.group(3))
    ]


def test_the_check_digit_is_the_upu_one():
    # The UPU's published S10 example and one worked by hand; changing a check digit fails.
    assert real_looking("RA473124829GB, ab123456785gb") == ["RA473124829GB", "ab123456785gb"]
    assert real_looking("RA473124820GB AB123456780GB") == []
    assert real_looking("as printed: RA 473 124 829 GB") == ["RA 473 124 829 GB"]


def test_no_fixture_or_doc_carries_a_real_tracking_number():
    found = {}
    for top in WHERE:
        for path in (REPO / top).rglob("*"):
            if path.suffix not in TEXT or not path.is_file() or path == Path(__file__).resolve():
                continue
            if any(part in ("node_modules", "__pycache__") or part.endswith(".egg-info")
                   for part in path.parts):  # fmt: skip
                continue
            hits = real_looking(path.read_text("utf-8", errors="ignore"))
            if hits:
                found[str(path.relative_to(REPO))] = hits
    assert found == {}, f"tracking numbers that look real (copied from a live order?): {found}"
