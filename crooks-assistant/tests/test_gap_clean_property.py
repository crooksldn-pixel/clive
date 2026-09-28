"""The start-up clean of the gap record loses nothing of the owner's (the 2026-09-28 deploy review,
round 9, A3a-LIVE-CLEAN).

GapLedger.repair brings the record on disk up to today's rule at start-up. The reviewer could not
see the ten live rows, so could not tell whether cleaning merges or drops any of them. What is
held here, over thousands of odd records built at random from a fixed seed (the same records on
every run) — keys that clean alike, keys that clean to nothing, rows that are not rows, fields of
every wrong type, fields nobody writes, builds and misjudged rows likewise:

- the clean never raises, and either leaves the file exactly as it was with no copy made, or first
  keeps a copy holding the original byte for byte and only then writes the clean record;
- a row the clean cannot clean (its cleaning raises) is not dropped: nothing is written at all, at
  start-up or by a later change, and the file stays exactly as it was;
- every row that is a row is still in the clean record, under its cleaned key — merged with the
  rows that clean alike, their hits added. The clean forgets no gap, stale or not: that is for a
  later change, as it always was (round 9);
- the whole start-up (install, then the seed) writes nothing to a record that is already clean
  and seeded, and forgets nothing in one that is not;
- a second clean changes nothing and makes no second copy;
- the code a rollback returns to (3e77f215, vendored) reads and reports every clean record.

tests/test_capability_gaps.py holds the particular cases; scripts/gap_clean_check.py runs this
same clean against a private copy of the live record and says, row by row, what it would change.
"""

from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from app.objectives import gaps as gaps_module
from app.objectives.gaps import GapLedger

SEED = 20260928
RECORDS = 400

_WORDS = ["web", "research", "tool", "look", "up", "trend", "custom", "line", "name", "order", "draft",
          "invoice", "No", "the", "a", "Clive", "can't", "mac", "read-only", "display", "project"]
_ODD_TEXT = ["", "   ", "\ud800", "é" * 70, "greg@example.com", "+44 7700 900123", "tool: ", "tool: Web.Search!",
             "tool: web.search", "TOOL: x", "unnamed", "x" * 300, "\n\t", "<b>web</b>", "0", "null"]
_FIELDS = list(gaps_module._GAP_FIELDS) + ["capability", "extra", "__proto__"]
_BUILD_FIELDS = list(gaps_module._BUILD_FIELDS) + ["secret", "note"]


def _odd_value(rng: random.Random, depth: int = 0):
    choice = rng.randrange(14)
    now = datetime(2026, 9, 27, tzinfo=UTC)
    if choice == 0:
        return (now - timedelta(days=rng.choice([0, 1, 30, 200, 400]))).isoformat()
    if choice == 1:
        return rng.choice(["2026-09-27T01:07:06Z", "0001-01-01T00:00:00+14:00", "9999-12-31T23:59:59-14:00", "not a time"])
    if choice == 2:
        return rng.choice([0, 1, 7, -3, 10**12, 2**63])
    if choice == 3:
        return rng.choice([True, False, None])
    if choice == 4:
        return rng.choice([1.5, -0.0, 1e308])
    if choice == 5:
        return rng.choice(_ODD_TEXT + ["12", "²", "007", "obj_abcd1234", "find-web-search", "a" * 40])
    if choice == 6 and depth < 3:
        return [_odd_value(rng, depth + 1) for _ in range(rng.randrange(4))]
    if choice == 7 and depth < 3:
        return {rng.choice(["blocker", "tool", "requests", "seen", "x"]): _odd_value(rng, depth + 1) for _ in range(rng.randrange(3))}
    if choice == 8:
        return [f"obj_{rng.randrange(16**8):08x}" for _ in range(rng.randrange(25))]
    if choice == 9:
        return [(now - timedelta(hours=rng.randrange(5000))).isoformat() for _ in range(rng.randrange(60))]
    if choice == 10:
        return rng.choice(["find-web-search", "build-custom-line", "Bad_Id", "x"])
    if choice == 11:
        return {"blocker": rng.randrange(5), "tool": str(rng.randrange(5))}
    if choice == 12:
        return rng.choice(["links", "history", "other"])
    return " ".join(rng.choice(_WORDS) for _ in range(rng.randrange(1, 6)))


def _odd_key(rng: random.Random) -> str:
    if rng.random() < 0.3:
        return rng.choice(_ODD_TEXT)
    words = [rng.choice(_WORDS) for _ in range(rng.randrange(1, 7))]
    key = " ".join(words)
    if rng.random() < 0.3:
        key = key.upper() if rng.random() < 0.5 else key.replace(" ", "  ") + "."
    if rng.random() < 0.2:
        key = "tool: " + key.replace(" ", "_")
    return key


def _odd_record(rng: random.Random) -> object:
    if rng.random() < 0.03:
        return rng.choice([[], "gaps", 7, None])
    gaps: dict = {}
    for _ in range(rng.randrange(12)):
        if rng.random() < 0.1:
            gaps[_odd_key(rng)] = _odd_value(rng)                    # not a row at all
            continue
        row = {field: _odd_value(rng) for field in rng.sample(_FIELDS, rng.randrange(len(_FIELDS)))}
        if rng.random() < 0.6:
            row["hits"] = rng.randrange(0, 50)
        if rng.random() < 0.5:
            row["last_seen"] = (datetime(2026, 9, 27, tzinfo=UTC) - timedelta(days=rng.choice([0, 3, 90, 181, 365]))).isoformat()
        gaps[_odd_key(rng)] = row
    keys = list(gaps)
    builds: dict = {}
    for _ in range(rng.randrange(4)):
        build = {field: _odd_value(rng) for field in rng.sample(_BUILD_FIELDS, rng.randrange(len(_BUILD_FIELDS)))}
        if keys and rng.random() < 0.7:
            build["gaps"] = rng.sample(keys, min(len(keys), rng.randrange(1, 4)))
        request_id = rng.choice(["find-web-search", "build-custom-line", "fix-thing-2", "Bad Id", ""])
        builds[request_id] = build
        if keys and rng.random() < 0.7:
            target = gaps.get(rng.choice(keys))
            if isinstance(target, dict):
                target["requests"] = [request_id]
    record = {"version": _odd_value(rng), "gaps": gaps, "builds": builds,
              "misjudged": {rng.choice(["best_sellers", "refunds", "other", "zzz", ""]): (_odd_value(rng) if rng.random() < 0.2 else
                            {"count": _odd_value(rng), "first_seen": _odd_value(rng), "last_seen": _odd_value(rng)})
                            for _ in range(rng.randrange(3))}}
    if rng.random() < 0.5:
        record["seeded"] = _odd_value(rng)
    if rng.random() < 0.3:
        record[rng.choice(["extra", "owner_note", "gapz"])] = _odd_value(rng)
    return record


def _encode(record: object, rng: random.Random) -> bytes:
    text = json.dumps(record, indent=rng.choice([None, 1, 2]), ensure_ascii=rng.random() < 0.5)
    return text.encode("utf-8", "surrogatepass")


def _readable(raw: bytes) -> bool:
    try:
        return isinstance(json.loads(raw.decode("utf-8")), dict)
    except (UnicodeDecodeError, ValueError):
        return False


def _copies(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.*.before-clean")) + sorted(path.parent.glob(f"{path.name}.*.unreadable"))


def _expected_keys(original: dict) -> dict[str, int]:
    """Each row that is a row, by the key it cleans to, with the hits the rows that clean alike add
    up to — worked out from the original, one row at a time, not by running the clean."""
    out: dict[str, int] = {}
    for key, raw in (original.get("gaps") or {}).items() if isinstance(original.get("gaps"), dict) else ():
        if not isinstance(raw, dict):
            continue
        clean = gaps_module._clean_key(str(key))
        out[clean] = min(gaps_module._MAX_COUNT, out.get(clean, 0) + gaps_module._count(raw.get("hits")))
    return out


def _old_code():
    from tests.test_capability_gaps import _old_code as vendored

    return vendored()


def test_over_odd_records_the_clean_keeps_every_row_or_the_original_and_writes_nothing_it_cannot(tmp_path):
    rng = random.Random(SEED)
    old = _old_code()
    cleaned = untouched = 0
    for n in range(RECORDS):
        record = _odd_record(rng)
        raw = _encode(record, rng)
        folder = tmp_path / f"r{n}" / "objectives"
        folder.mkdir(parents=True, mode=0o700)
        path = folder / "gaps.json"
        path.write_bytes(raw)
        ledger = GapLedger(path)

        copy = ledger.repair()                                                    # never raises
        after = path.read_bytes()
        copies = _copies(path)
        if after == raw:
            untouched += 1
            if _readable(raw):
                assert copy is None and copies == [], n
            else:
                # Not a record at all (not JSON text, or not an object): left as it is, and a copy
                # kept against the day a change starts a fresh one over it.
                assert copies == [copy] and copy.name.endswith(".unreadable") and copy.read_bytes() == raw, n
        else:
            cleaned += 1
            assert copies == [copy] and copy.read_bytes() == raw, f"record {n}: the original, byte for byte, first"
            assert copy.stat().st_mode & 0o777 == 0o600
        # The clean record holds every row, under its cleaned key, hits added across rows that clean
        # alike — unless the record's own rule forgets it as stale, and then the copy holds it.
        now = json.loads(after.decode("utf-8")) if after != raw else None
        if now is not None and isinstance(record, dict):
            assert {k: now["gaps"][k]["hits"] for k in _expected_keys(record) if k in now["gaps"]} == _expected_keys(record), n
        # Idempotent: a second start-up changes nothing and keeps no second copy.
        again = GapLedger(path).repair()
        assert again is None or (not _readable(raw) and again == copy), n
        assert path.read_bytes() == after and _copies(path) == copies, n
        # The code a rollback returns to reads and reports whatever the clean left.
        if now is not None:
            old.GapLedger(path).report()
    assert cleaned > 100 and untouched > 5, (cleaned, untouched)


def test_the_ten_row_shape_of_the_live_record_is_cleaned_without_losing_a_row_or_a_field(tmp_path):
    """The shape the preflight showed of the live record (ten gaps under cleaned keys, two with
    names, no builds, no misjudged rows, a seeded time; gap texts are not ours to copy here, so
    stand-ins of the same form): it is already clean, so start-up writes nothing and makes no copy —
    the branch the reviewer could not confirm production takes."""
    keys = ["concept multiple users member accounts invite", "custom line name on an order",
            "display tool project expanded view onto", "log manual physically done state task",
            "mac read only shopify gmail writes", "order name lookup on order open order add name",
            "tool exposes draft order's invoice checkout", "tool set custom line name price",
            "visibility into how machine's access networking", "web research tool look up trend"]
    gaps = {}
    for i, key in enumerate(keys):
        at = f"2026-09-2{6 + i % 2}T1{i}:00:00+00:00"
        row = {"label": f"Stand-in label {i}", "hits": 1 + i, "sources": {"blocker": 1 + i},
               "objectives": [f"obj_{i:08x}"], "requests": [], "seen": [at], "first_seen": at, "last_seen": at}
        if i in (1, 7):
            row["name"] = f"Stand-in name {i}"
        gaps[key] = row
    record = {"version": 1, "gaps": gaps, "builds": {}, "misjudged": {}, "seeded": "2026-09-27T01:07:06+00:00"}
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)
    raw = json.dumps(record, indent=2, ensure_ascii=False).encode()
    path.write_bytes(raw)
    assert GapLedger(path).repair() is None
    assert path.read_bytes() == raw and _copies(path) == []
    assert GapLedger(path).load() == record, "every row and every field, as it was"


def test_a_row_the_clean_cannot_clean_is_kept_not_dropped(tmp_path, monkeypatch):
    """If cleaning one row raises — a value no rule foresaw — nothing is written: not at start-up,
    and not by a later change, which would otherwise save a record without that row. The file stays
    exactly as it was, and says so in the log; every other row is still in it."""
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)
    raw = json.dumps({"version": 1, "gaps": {
        "web research": {"label": "No web research", "hits": 2, "Legacy Field": "kept?"},
        "the odd one": {"label": "x", "hits": 1},
    }, "builds": {}, "misjudged": {}}).encode()
    path.write_bytes(raw)
    real = gaps_module._only_known_gap

    def cannot(row):
        if row.get("label") == "x":
            raise ValueError("a value no rule foresaw")
        return real(row)

    monkeypatch.setattr(gaps_module, "_only_known_gap", cannot)
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    ledger = gaps_module.install(path)                                   # logs, never raises
    assert path.read_bytes() == raw and _copies(path) == []
    ledger.note_blocker("obj_00000001", "No web research", "web research")
    assert path.read_bytes() == raw and _copies(path) == [], "a later change saves nothing over it"
    monkeypatch.setattr(gaps_module, "_only_known_gap", real)
    ledger.note_blocker("obj_00000001", "No web research", "web research")
    assert [c.read_bytes() for c in _copies(path)] == [raw], "once it can be cleaned, the original is kept first"
    assert set(json.loads(path.read_text())["gaps"]) == {"web research", "the odd one"}


@pytest.mark.parametrize("seed", range(3))
def test_a_clean_that_fails_after_its_copy_keeps_the_copy_and_the_original(tmp_path, monkeypatch, seed):
    """The copy is made, then the save fails: the live file is the original still, and the next
    start-up reuses the very copy (checked byte for byte) rather than making another."""
    rng = random.Random(SEED + seed)
    record = _odd_record(rng)
    while not isinstance(record, dict) or not _expected_keys(record):
        record = _odd_record(rng)
    record["gaps"]["Legacy Key With Extra"] = {"label": "No web", "hits": 1, "extra": "field"}
    raw = _encode(record, rng)
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)
    path.write_bytes(raw)

    def failing(self, data, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(GapLedger, "_save", failing)
    with pytest.raises(OSError):
        GapLedger(path).repair()
    assert path.read_bytes() == raw
    (copy,) = _copies(path)
    monkeypatch.undo()
    assert GapLedger(path).repair() == copy and _copies(path) == [copy] and copy.read_bytes() == raw


def test_over_odd_records_the_whole_start_up_forgets_nothing_and_rewrites_nothing_clean(tmp_path, monkeypatch):
    """Start-up is install (the clean) and then the seed. The seed used to save the record every
    time, already seeded or not, and that save forgot stale gaps with no copy kept. Now a record
    already clean and seeded is not written at all, and no start-up write forgets a gap."""
    rng = random.Random(SEED + 1)
    rewritten = kept = 0
    for n in range(RECORDS // 2):
        record = _odd_record(rng)
        raw = _encode(record, rng)
        folder = tmp_path / f"s{n}" / "objectives"
        folder.mkdir(parents=True, mode=0o700)
        path = folder / "gaps.json"
        path.write_bytes(raw)
        monkeypatch.setattr(gaps_module, "_LEDGER", None)
        gaps_module.install(path).seed([])
        after = path.read_bytes()
        if not _readable(raw):
            continue
        if after == raw:
            kept += 1
            continue
        rewritten += 1
        now = json.loads(after.decode("utf-8"))
        assert {k: now["gaps"][k]["hits"] for k in _expected_keys(record) if k in now["gaps"]} == _expected_keys(record), n
        copies = _copies(path)
        shaped = gaps_module._shaped(json.loads(raw.decode("utf-8")))
        clean = json.loads(json.dumps(shaped))
        gaps_module._sanitise(clean)
        if clean != shaped:
            assert [c.read_bytes() for c in copies] == [raw], n
        else:
            # Already clean: written only to seed it, which adds and takes nothing away.
            assert not shaped.get("seeded") or gaps_module._strict_iso(shaped["seeded"]) is None, n
            assert {k: v for k, v in now.items() if k != "seeded"} == {k: v for k, v in clean.items() if k != "seeded"}, n
        # And a second start-up writes nothing at all.
        monkeypatch.setattr(gaps_module, "_LEDGER", None)
        gaps_module.install(path).seed([])
        assert path.read_bytes() == after and _copies(path) == copies, n
    assert rewritten > 50 and kept >= 0, (rewritten, kept)


def test_the_deploys_check_says_row_by_row_what_start_up_would_do_without_touching_the_record(tmp_path, capsys):
    """scripts/gap_clean_check.py, for the deploy: run on a private copy of the live record, it says
    by row number and cleaned key what start-up would keep or change, how many copies it keeps, and
    whether the rollback code reads the result — and the record itself is not touched. An original
    key (which may be what the clean exists to redact) is never printed."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("gap_clean_check_under_test",
                                                  Path(__file__).resolve().parents[1] / "scripts" / "gap_clean_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    live = tmp_path / "live" / "gaps.json"
    live.parent.mkdir(mode=0o700)
    clean = {"version": 1, "gaps": {"web research tool look up trend": {
        "label": "No web research", "hits": 2, "sources": {"blocker": 2}, "objectives": [], "requests": [],
        "seen": ["2026-09-27T10:00:00+00:00"], "first_seen": "2026-09-27T10:00:00+00:00",
        "last_seen": "2026-09-27T10:00:00+00:00"}}, "builds": {}, "misjudged": {}, "seeded": "2026-09-27T01:07:06+00:00"}
    raw = json.dumps(clean, indent=2).encode()
    live.write_bytes(raw)
    assert module.main([str(live)]) == 0
    said = capsys.readouterr().out
    assert "1 gap row(s) before, 1 after; file unchanged; 0 copy/copies" in said and "kept as it was" in said
    assert "rollback code (3e77f215) reads and reports the result: yes" in said and "VERDICT: nothing lost" in said
    legacy = {"version": 1, "gaps": {"Web Research for greg@example.com": {"label": "x", "hits": 1, "legacy": True},
                                     "Web  Research, For!": {"label": "y", "hits": 2},
                                     "web research for": {"label": "z", "hits": 3}}, "builds": {}, "misjudged": {}}
    raw = json.dumps(legacy).encode()
    live.write_bytes(raw)
    assert module.main([str(live)]) == 0
    said = capsys.readouterr().out
    assert "greg@example.com" not in said and "Web Research for" not in said
    assert "1 byte-identical" in said and "fields dropped: legacy" in said and "merged with 1 other row(s)" in said
    assert "in the byte-identical copy the clean keeps" in said
    assert live.read_bytes() == raw and list(live.parent.iterdir()) == [live], "the live record only read"
