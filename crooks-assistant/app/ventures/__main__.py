"""The venture engine from a terminal.

    python -m app.ventures brief CANDIDATE.json [--today YYYY-MM-DD] [--json]
    python -m app.ventures dates [--market UK] [--today YYYY-MM-DD] [--days 365]

``brief`` reads the one candidate file it is given and prints the decision package; ``dates``
prints the retail calendar for a market with the supplier slowdowns. Nothing else is read,
nothing is written and nothing leaves the machine: no network, no model, no store."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from app.ventures.brief import brief_to_dict, build_brief, load_candidate, render_markdown
from app.ventures.markets import MARKETS
from app.ventures.seasons import EVENTS, event_label, next_event_date, supplier_slowdowns


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ventures", description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    brief = commands.add_parser("brief", help="the decision package for one candidate file")
    brief.add_argument("candidate", type=Path)
    brief.add_argument("--today", type=date.fromisoformat, default=None)
    brief.add_argument("--json", action="store_true", help="print JSON instead of the readable brief")
    dates = commands.add_parser("dates", help="retail dates and supplier slowdowns for a market")
    dates.add_argument("--market", default="UK", choices=sorted(MARKETS))
    dates.add_argument("--today", type=date.fromisoformat, default=None)
    dates.add_argument("--days", type=int, default=365)
    args = parser.parse_args(argv)
    today = args.today or datetime.now(ZoneInfo("Europe/London")).date()

    if args.command == "brief":
        try:
            data = json.loads(args.candidate.read_text(encoding="utf-8"), parse_float=Decimal)
            result = build_brief(load_candidate(data), today)
        except (OSError, ValueError, TypeError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(brief_to_dict(result), indent=2, sort_keys=True, ensure_ascii=False))
        else:
            print(render_markdown(result), end="")
        return 0

    if not 1 <= args.days <= 730:
        print("error: --days must be between 1 and 730", file=sys.stderr)
        return 2
    horizon = today + timedelta(days=args.days)
    rows = []
    for event in EVENTS:
        try:
            day = next_event_date(event, args.market, today)
        except ValueError:
            continue
        if day <= horizon:
            rows.append((day, event_label(event, args.market)))
    for year in range(today.year, horizon.year + 1):
        for window in supplier_slowdowns(year):
            if window.end >= today and window.start <= horizon:
                rows.append((window.start, f"{window.name} supplier slowdown until {window.end.isoformat()}"))
    print(f"Retail calendar for {MARKETS[args.market].label}, {today.isoformat()} to {horizon.isoformat()}")
    for day, what in sorted(rows):
        print(f"{day.isoformat()}  {what}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
