#!/usr/bin/env python3
"""What start-up would do to the gap record, worked out on a private copy (the 2026-09-28 deploy
review, round 9, A3a-LIVE-CLEAN).

    python scripts/gap_clean_check.py [path]     default: <objectives dir>/gaps.json

Copies the record byte for byte into a private temporary folder (0700), runs this build's own
start-up on the copy — the clean (GapLedger.repair), then the seed — and says, row by row, what it
kept, merged, changed or dropped, by the row's number, its key as cleaned (redacted by the
record's own rule, as the result holds it) and field names only — never an original key, a label,
a name or any other text the record holds — how many copies of the original it kept, and whether
the code a rollback
returns to (3e77f215, vendored in tests/rollback) still reads and reports the result. The live
record is only read; the temporary folder is removed.

Exit 0 when every row and every field of every row is still in the result, or is in the copy of
the original the clean kept before it wrote anything; 1 when anything would be lost without such a
copy, or the rollback code cannot read the result.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))


def check(live: Path, out=print) -> int:
    from app.objectives import gaps as gaps_module

    raw = live.read_bytes()
    folder = Path(tempfile.mkdtemp(prefix="gap-clean-check-"))
    try:
        folder.chmod(0o700)
        objectives = folder / "objectives"
        objectives.mkdir(mode=0o700)
        copy = objectives / live.name
        copy.write_bytes(raw)
        copy.chmod(0o600)
        try:
            before = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError, RecursionError):
            before = None
        gaps_module._LEDGER = None
        gaps_module.install(copy).seed([])
        kept = sorted(objectives.glob(f"{live.name}.*.before-clean")) + sorted(objectives.glob(f"{live.name}.*.unreadable"))
        backed_up = [c for c in kept if c.read_bytes() == raw]
        unchanged = copy.read_bytes() == raw
        if not isinstance(before, dict):
            out(f"record: not readable as one; file {'unchanged' if unchanged else 'REWRITTEN'}; "
                f"{len(backed_up)} byte-identical copy/copies kept")
            return 0 if backed_up and unchanged else 1
        after = json.loads(copy.read_text(encoding="utf-8"))
        rows = before.get("gaps") if isinstance(before.get("gaps"), dict) else {}
        out(f"record: {len(rows)} gap row(s) before, {len(after['gaps'])} after; "
            f"file {'unchanged' if unchanged else 'rewritten'}; "
            f"{len(kept)} copy/copies of the original kept, {len(backed_up)} byte-identical")
        lost = False
        for number, (key, row) in enumerate(rows.items(), start=1):
            clean = gaps_module._clean_key(str(key))
            if not isinstance(row, dict):
                out(f"  row {number}: not a row (a {type(row).__name__}); dropped")
                lost = True
                continue
            now = after["gaps"].get(clean)
            if now is None:
                out(f"  row {number} -> {clean!r}: MISSING from the result")
                lost = True
                continue
            gone = sorted(set(row) - set(now))
            changed = sorted(f for f in set(row) & set(now) if row[f] != now[f])
            merged = [k for k in rows if k != key and gaps_module._clean_key(str(k)) == clean]
            state = "kept as it was" if not gone and not changed and clean == key and not merged else "changed"
            out(f"  row {number} -> {clean!r}: {state}" + ("" if clean == key else "; key cleaned")
                + (f"; merged with {len(merged)} other row(s)" if merged else "")
                + (f"; fields dropped: {', '.join(gone)}" if gone else "")
                + (f"; fields changed: {', '.join(changed)}" if changed else ""))
            lost = lost or bool(gone or changed or merged or clean != key)
        for section in ("builds", "misjudged"):
            if (before.get(section) or {}) != after[section]:
                out(f"  {section}: changed ({len(before.get(section) or {})} -> {len(after[section])})")
                lost = True
        extra = sorted(set(before) - set(after))
        if extra:
            out(f"  top-level fields dropped: {', '.join(extra)}")
            lost = True
        try:
            from tests.rollback import gaps_3e77f215 as old

            old.GapLedger(copy).report()
            out("  rollback code (3e77f215) reads and reports the result: yes")
            rollback_ok = True
        except Exception as exc:  # noqa: BLE001 - the answer is the finding
            out(f"  rollback code (3e77f215) reads and reports the result: NO ({type(exc).__name__})")
            rollback_ok = False
        if lost and not backed_up:
            out("VERDICT: something would change with no copy of the original kept")
            return 1
        if not rollback_ok:
            return 1
        out("VERDICT: nothing lost" + (" (what changed is in the byte-identical copy the clean keeps)" if lost else ""))
        return 0
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        live = Path(args[0])
    else:
        from config.settings import get_settings

        live = get_settings().objectives_dir / "gaps.json"
    if not live.is_file():
        print(f"no gap record at {live}")
        return 0
    return check(live)


if __name__ == "__main__":
    raise SystemExit(main())
