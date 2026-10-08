"""What a run says, worked out from its files: the page and `python -m app.bench report` both read this.

Per run:
- scores by persona and by criterion (the judge's, averaged; results it did not score are counted
  apart, never as zeros);
- the worst ten results, each with the score that pulled it down and why;
- the tools each door was offered and never used in the run;
- what CLIVE could not do, grouped into candidate capability gaps: the judge names the missing
  capability, and the names are keyed exactly as CLIVE's own gap record keys them
  (app/objectives/gaps.py key_for), so the two can be compared (the owner's screen shows each beside
  that record: app/routes/bench.py). They are not written into that record: it counts what George
  and the team hit in real use, and how often a gap comes back once its fix is live; questions made
  up for a test would skew both;
- safety, measured rather than judged: changes executed, changes sent to the shop, proposals taken past
  their card, and anything the seal refused. All four should be nought;
- George's ratings beside the judge's: how often they agree (`agreement`), and the next results worth
  his rating (`to_rate`): unrated, spread across the personas, the worst-judged first.

Nothing here changes a file except `write`, which saves report.json and report.md in the run's folder.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from app.bench.judge import CRITERIA
from app.bench.store import Bench, write_json

WORST = 10
TO_RATE = 10


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _scored(verdict: dict[str, Any] | None) -> bool:
    return bool(verdict) and "scores" in verdict and "error" not in verdict and "not_judged" not in verdict


def agreement(pairs: list[tuple[int, int]]) -> dict[str, Any]:
    """George's score against the judge's overall, for every result he rated that the judge scored."""
    if not pairs:
        return {"rated": 0, "exact": 0, "within_one": 0, "mean_gap": None, "judge_higher": 0, "judge_lower": 0}
    gaps = [judge - george for george, judge in pairs]
    return {
        "rated": len(pairs), "exact": sum(1 for g in gaps if g == 0), "within_one": sum(1 for g in gaps if abs(g) <= 1),
        "mean_gap": round(sum(abs(g) for g in gaps) / len(gaps), 2),
        "judge_higher": sum(1 for g in gaps if g > 0), "judge_lower": sum(1 for g in gaps if g < 0),
    }


def agreement_for(bench: Bench, run_id: str | None = None) -> dict[str, Any]:
    pairs: list[tuple[int, int]] = []
    verdicts: dict[str, dict[str, dict[str, Any]]] = {}
    for (rated_run, result_id), rating in bench.ratings().items():
        if run_id and rated_run != run_id:
            continue
        if rated_run not in verdicts:
            try:
                verdicts[rated_run] = bench.judged(rated_run)
            except ValueError:
                verdicts[rated_run] = {}
        verdict = verdicts[rated_run].get(result_id)
        if _scored(verdict):
            pairs.append((int(rating["score"]), int(verdict["overall"])))
    return agreement(pairs)


def to_rate(results: list[dict[str, Any]], judged: dict[str, dict[str, Any]], rated: set[str],
            limit: int = TO_RATE) -> list[str]:
    """The next results worth George's rating: judged, not yet rated by him, taken in turn from each
    persona so one person's questions do not crowd the rest out, the worst-judged of each first."""
    queues: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for row in results:
        result_id = str(row.get("result_id"))
        verdict = judged.get(result_id)
        if result_id in rated or not _scored(verdict):
            continue
        queues[str(row.get("persona"))].append((int(verdict["overall"]), result_id))
    for queue in queues.values():
        queue.sort()
    picked: list[str] = []
    while len(picked) < limit and any(queues.values()):
        for persona in sorted(queues):
            if queues[persona] and len(picked) < limit:
                picked.append(queues[persona].pop(0)[1])
    return picked


def _gaps(results: list[dict[str, Any]], judged: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    from app.objectives.gaps import key_for

    groups: dict[str, dict[str, Any]] = {}
    for row in results:
        verdict = judged.get(str(row.get("result_id"))) or {}
        if not (_scored(verdict) and verdict.get("couldnt_do") and verdict.get("capability")):
            continue
        key = key_for(verdict["capability"])
        group = groups.setdefault(key, {"key": key, "names": Counter(), "count": 0, "personas": set(),
                                        "examples": [], "result_ids": []})
        group["names"][verdict["capability"]] += 1
        group["count"] += 1
        group["personas"].add(str(row.get("persona_name") or row.get("persona")))
        group["result_ids"].append(row.get("result_id"))
        if len(group["examples"]) < 3 and row.get("said"):
            group["examples"].append(str(row["said"][0]))
    out = [{"key": g["key"], "name": g["names"].most_common(1)[0][0], "count": g["count"],
            "personas": sorted(g["personas"]), "examples": g["examples"], "result_ids": g["result_ids"]}
           for g in groups.values()]
    return sorted(out, key=lambda g: (-g["count"], g["key"]))


def _worst(results: list[dict[str, Any]], judged: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = []
    for row in results:
        verdict = judged.get(str(row.get("result_id")))
        if not _scored(verdict):
            continue
        criterion, item = min(verdict["scores"].items(), key=lambda kv: (kv[1]["score"], CRITERIA.index(kv[0])))
        ranked.append((verdict["overall"], item["score"], str(row.get("result_id")), {
            "result_id": row.get("result_id"), "persona": row.get("persona"), "persona_name": row.get("persona_name"),
            "said": (row.get("said") or [""])[0], "overall": verdict["overall"],
            "worst": {"criterion": criterion, "score": item["score"], "why": item["why"]},
            "summary": verdict.get("summary", ""), "flags": verdict.get("flags", []),
        }))
    ranked.sort(key=lambda r: r[:3])
    return [r[3] for r in ranked[:WORST]]


def build(bench: Bench, run_id: str) -> dict[str, Any]:
    manifest = bench.manifest(run_id) or {"run_id": run_id}
    results = bench.results(run_id)
    judged = bench.judged(run_id)
    scored = {rid: v for rid, v in judged.items() if _scored(v)}
    by_persona: dict[str, dict[str, Any]] = {}
    by_criterion: dict[str, list[int]] = {c: [] for c in CRITERIA}
    flags: Counter = Counter()
    used: dict[str, Counter] = defaultdict(Counter)
    safety = {"executions": 0, "shop_changes": 0, "committed": 0, "breaches": 0, "staged": 0}
    for row in results:
        persona = str(row.get("persona"))
        entry = by_persona.setdefault(persona, {"persona": persona, "name": row.get("persona_name") or persona,
                                                "access": row.get("access"), "questions": 0, "errors": 0,
                                                "scored": 0, "overall": [], "criteria": {c: [] for c in CRITERIA}})
        entry["questions"] += 1
        entry["errors"] += 1 if row.get("error") else 0
        for name in row.get("tools_used") or []:
            used[str(row.get("access"))][name] += 1
        for key in ("executions", "shop_changes", "committed"):
            safety[key] += int((row.get("safety") or {}).get(key) or 0)
        safety["breaches"] += len((row.get("safety") or {}).get("breaches") or [])
        safety["staged"] += len(row.get("staged_writes") or [])
        verdict = scored.get(str(row.get("result_id")))
        if verdict is None:
            continue
        entry["scored"] += 1
        entry["overall"].append(verdict["overall"])
        flags.update(verdict.get("flags") or [])
        for criterion in CRITERIA:
            entry["criteria"][criterion].append(verdict["scores"][criterion]["score"])
            by_criterion[criterion].append(verdict["scores"][criterion]["score"])
    personas = [{**e, "overall": _mean(e["overall"]), "criteria": {c: _mean(v) for c, v in e["criteria"].items()}}
                for e in by_persona.values()]
    offered = manifest.get("offered_tools") or {}
    doors = {str(r.get("access")) for r in results}
    never = {door: [t for t in offered.get(door, []) if t not in used[door]] for door in sorted(doors) if offered.get(door)}
    rated = {rid for (rated_run, rid) in bench.ratings() if rated_run == run_id}
    return {
        "run": manifest,
        "counts": {"questions": len(results), "errors": sum(1 for r in results if r.get("error")),
                   "scored": len(scored), "judge_errors": sum(1 for v in judged.values() if "error" in v),
                   "not_judged": len(results) - len(scored), "rated": len(rated)},
        "overall": _mean([v["overall"] for v in scored.values()]),
        "by_persona": sorted(personas, key=lambda p: p["persona"]),
        "by_criterion": {c: _mean(v) for c, v in by_criterion.items()},
        "worst": _worst(results, judged),
        "gaps": _gaps(results, judged),
        "flags": dict(flags.most_common()),
        "tools_used": {door: dict(c.most_common()) for door, c in used.items()},
        "tools_never_used": never,
        "safety": safety,
        "agreement": agreement_for(bench, run_id),
        "to_rate": to_rate(results, judged, rated),
    }


def markdown(report: dict[str, Any]) -> str:
    run, counts = report["run"], report["counts"]
    lines = [f"# Bench run {run.get('run_id')}", "",
             f"- Set `{run.get('set_id')}` · turns by {(run.get('models') or {}).get('turns', '?')} · "
             f"judged by {(run.get('models') or {}).get('judge', 'nobody yet')} ({run.get('judge_version', '')})",
             f"- {counts['questions']} questions, {counts['errors']} errors, {counts['scored']} scored, "
             f"{counts['rated']} rated by George. Status: {run.get('status')}"
             + (f" ({run['stopped']})" if run.get("stopped") else ""),
             f"- Overall: {report['overall'] if report['overall'] is not None else 'not scored'}", "",
             "## Safety (measured)", ""]
    lines += [f"- {k.replace('_', ' ')}: {v}" for k, v in report["safety"].items()]
    lines += ["", "## By persona", "", "| Persona | Door | Qs | Scored | Overall | " + " | ".join(CRITERIA) + " |",
              "|---|---|---:|---:|---:|" + "---:|" * len(CRITERIA)]
    for p in report["by_persona"]:
        cells = " | ".join("–" if p["criteria"][c] is None else f"{p['criteria'][c]:.1f}" for c in CRITERIA)
        overall = "–" if p["overall"] is None else f"{p['overall']:.1f}"
        lines.append(f"| {p['name']} | {p['access']} | {p['questions']} | {p['scored']} | {overall} | {cells} |")
    lines += ["", "## Worst ten", ""]
    for w in report["worst"]:
        lines.append(f"- {w['result_id']} ({w['persona_name']}) {w['overall']}/5, {w['worst']['criterion']} "
                     f"{w['worst']['score']}: \"{w['said'][:120]}\" — {w['worst']['why']}")
    lines += ["", "## Could not do (candidate capability gaps)", ""]
    for g in report["gaps"]:
        lines.append(f"- {g['name']} ×{g['count']} ({', '.join(g['personas'])}): " + "; ".join(f"\"{e[:80]}\"" for e in g["examples"]))
    lines += ["", "## Tools never used", ""]
    for door, names in report["tools_never_used"].items():
        lines.append(f"- {door} door, {len(names)}: {', '.join(names)}")
    a = report["agreement"]
    lines += ["", "## Judge and George", "",
              f"- {a['rated']} rated; exact {a['exact']}, within one {a['within_one']}, mean gap {a['mean_gap']}"]
    return "\n".join(lines) + "\n"


def write(bench: Bench, run_id: str) -> dict[str, Any]:
    from app.bench.store import _write

    report = build(bench, run_id)
    folder = bench.folder(bench.run_dir(run_id))
    write_json(folder / "report.json", report)
    _write(folder / "report.md", markdown(report))
    return report
