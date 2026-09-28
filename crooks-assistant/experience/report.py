"""What a run leaves behind: a page to read and a file to compare against.

Two audiences. `report.md` is for a person deciding whether the thing is any good — the
scenarios, what each one showed, what it offered to do next, and how quickly the first useful
thing appeared. `report.json` is for the next run and for Phase 2: the same facts, unrounded
and unprosed, so two runs can be diffed without reading either.

The number that matters most is deliberately not the total. "First useful UI" is when
something worth looking at was on screen; enrichment is when the rest arrived; complete is
everything including speech. A turn that shows the order in 90 ms and finishes the inbox check
at 400 ms is a good turn, and reporting 490 ms describes an experience nobody had.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPORTS = Path(__file__).resolve().parent.parent / "reports" / "experience"
# How many runs to keep. Enough to compare against last week, few enough that the directory is
# not a database.
KEEP_RUNS = 20


def run_id(clock=None) -> str:
    now = (clock or (lambda: datetime.now(UTC)))()
    return now.strftime("run-%Y%m%d-%H%M%S")


def _ms(value: Any) -> str:
    return "—" if value is None else f"{float(value):.0f} ms"


def _timings(results: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        for capture in result.captures:
            if capture.first_ui_ms is None and capture.kind == "voice":
                continue
            rows.append({
                "scenario": result.name, "command": capture.command, "kind": capture.kind,
                "lane": capture.lane or ("TOUCH" if capture.kind == "touch" else ""),
                "recipe": capture.recipe_id, "model_calls": capture.model_calls,
                "first_ui_ms": capture.first_ui_ms, "enrichment_ms": capture.enrichment_ms,
                "total_ms": round(capture.total_ms, 1),
                "surfaces": capture.surface_types,
            })
    return rows


def write(results: list[Any], *, directory: Path | None = None, mode: str = "fixture",
          guarantees: list[str] | None = None, screenshots: list[Path] | None = None,
          identifier: str = "") -> Path:
    """Write one run's report. Returns the directory it went into."""
    out = directory or (REPORTS / (identifier or run_id()))
    out.mkdir(parents=True, exist_ok=True)
    (out / "screenshots").mkdir(exist_ok=True)
    for shot in screenshots or []:
        if shot.exists() and shot.parent != (out / "screenshots"):
            shutil.copy2(shot, out / "screenshots" / shot.name)

    timings = _timings(results)
    payload = {
        "run": out.name,
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "mode": mode,
        "guarantees": list(guarantees or []),
        "totals": {
            "scenarios": len(results),
            "pass": sum(1 for r in results if r.status == "PASS"),
            "partial": sum(1 for r in results if r.status == "PARTIAL"),
            "fail": sum(1 for r in results if r.status == "FAIL"),
            "checks": sum(len(r.checks) for r in results),
            "checks_failed": sum(len(r.failures) for r in results),
        },
        "scenarios": [r.as_dict() for r in results],
        "timings": timings,
        "screenshots": sorted(p.name for p in (out / "screenshots").glob("*.png")),
    }
    (out / "report.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    (out / "report.md").write_text(_markdown(payload, results), encoding="utf-8")
    _prune(out.parent)
    return out


def _markdown(payload: dict[str, Any], results: list[Any]) -> str:
    totals = payload["totals"]
    lines: list[str] = [
        f"# Experience run {payload['run']}",
        "",
        f"{payload['at']} · mode **{payload['mode']}**",
        "",
        f"**{totals['pass']}/{totals['scenarios']} scenarios pass** "
        f"({totals['checks'] - totals['checks_failed']}/{totals['checks']} checks)",
        "",
    ]
    if payload["guarantees"]:
        lines += ["## What this run could not do", ""]
        lines += [f"- {g}" for g in payload["guarantees"]]
        lines += [""]

    lines += ["## Scenarios", "",
              "A sentence's model here is the harness's: where a scenario says which tools it calls",
              "(**Scripted model**), the run proves what the gate, the action engine and the cards do",
              "with those calls — not that Claude would choose them.",
              "",
              "| | Scenario | Lane | Recipe | Surfaces | Actions | First UI | Model | Scripted model |",
              "|---|---|---|---|---|---|---|---|---|"]
    for result in results:
        mark = {"PASS": "✓", "PARTIAL": "~", "FAIL": "✗"}.get(result.status, "?")
        first = next((c for c in result.captures if c.surfaces), None)
        capture = first or (result.captures[0] if result.captures else None)
        lines.append(
            f"| {mark} | {result.title} | {getattr(capture, 'lane', '') or '—'} "
            f"| {getattr(capture, 'recipe_id', '') or '—'} "
            f"| {', '.join(getattr(capture, 'surface_types', []) or ['—'])} "
            f"| {len(getattr(capture, 'action_ids', []) or [])} "
            f"| {_ms(getattr(capture, 'first_ui_ms', None))} "
            f"| {getattr(capture, 'model_calls', 0)} "
            f"| {', '.join(sorted({t for c in result.captures for t in (getattr(c, 'scripted', None) or [])})) or '—'} |"
        )
    lines += [""]

    failed = [r for r in results if r.status != "PASS"]
    if failed:
        lines += ["## What failed", ""]
        for result in failed:
            lines += [f"### {result.title} — {result.status}", ""]
            if result.error:
                lines += [f"- **error**: {result.error}", ""]
            for c in result.failures:
                lines += [f"- {c.what} — `{c.detail}`"]
            lines += [""]

    lines += ["## First useful UI", "",
              "**Card** is the Mac's own time to an answer with something to look at — the",
              "backend's measure of its own work, which is the part of the experience this",
              "machine decides. **Round trip** adds the transport: ASGI in the fixture world,",
              "Wi-Fi on the workbench. **Enrichment** is the regions that were still loading",
              "when the card was drawn, and is measured by a second request.",
              "",
              "Nothing here includes speech: no run calls /speak.",
              "",
              "| Scenario | Asked | How | Card | Enrichment | Round trip |",
              "|---|---|---|---|---|---|"]
    for row in payload["timings"]:
        lines.append(
            f"| {row['scenario']} | {row['command'][:44]} | {row['kind']} "
            f"| {_ms(row['first_ui_ms'])} | {_ms(row['enrichment_ms'])} | {_ms(row['total_ms'])} |"
        )
    lines += [""]

    if payload["screenshots"]:
        lines += ["## Screenshots", ""]
        lines += [f"- `screenshots/{name}`" for name in payload["screenshots"]]
        lines += [""]
    return "\n".join(lines)


def _prune(root: Path, keep: int = KEEP_RUNS) -> None:
    """Keep the most recent runs and no more. A report directory is a record, not an archive."""
    runs = sorted((p for p in root.glob("run-*") if p.is_dir()), key=lambda p: p.name)
    for old in runs[:-keep] if len(runs) > keep else []:
        shutil.rmtree(old, ignore_errors=True)
