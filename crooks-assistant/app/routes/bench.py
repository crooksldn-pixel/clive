"""The test bench's screen: George's runs, each result, and his ratings beside the judge's.

The bench itself runs on worker-01 (app/bench, docs/BENCH.md); this is where its runs are read. It
reads the data directory's bench/ folder and nothing else: a run's report is worked out from its
files on each look (app/bench/report.py), so a run judged after it was copied here shows its scores.

Behind the door (app/main.py): every route here is the owner's by its one rule (principal_verdict),
the team's door does not list any of them (app/people/staff.py), and a POST from another site is
refused before it arrives. The one thing it writes is a rating: a score from 1 to 5 and a short
note, appended to bench/ratings.jsonl with who rated and what the judge had said.

The pages hold no data. /bench draws the runs; /bench/cards is the frame a result's cards are drawn
in, with CLIVE's own card renderer (web/ui.js) and stylesheets, apart from this screen's styles, so a
card looks exactly as it did on the tablet. Nothing on a card works there: the app that would act on
a tap is not loaded.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from app.bench import report as bench_report
from app.bench.store import MAX_NOTE, RESULT_ID, RUN_ID, Bench, root_for

router = APIRouter()

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
MAX_BODY = 4 * 1024
MAX_RUNS = 40
_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
        "object-src 'none'; base-uri 'none'; form-action 'self'; frame-src 'self'; ")
PAGE_HEADERS = {"Cache-Control": "no-cache", "Content-Security-Policy": _CSP + "frame-ancestors 'none'",
                "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}
FRAME_HEADERS = {"Cache-Control": "no-cache", "Content-Security-Policy": _CSP + "frame-ancestors 'self'",
                 "X-Frame-Options": "SAMEORIGIN", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff"}


def _bench(request: Request) -> Bench:
    runtime = getattr(request.app.state, "runtime", None)
    return Bench(root_for(runtime.settings))


def _answer(payload: dict[str, Any], status: int = 200) -> JSONResponse:
    return JSONResponse(content=payload, status_code=status, headers={"Cache-Control": "no-store"})


def _refusal(status: int, code: str, detail: str) -> JSONResponse:
    return _answer({"ok": False, "code": code, "detail": detail}, status)


def _page(name: str, request: Request, headers: dict[str, str]) -> Response:
    source = (WEB_DIR / name).read_text(encoding="utf-8")
    build = getattr(getattr(request.app.state, "runtime", None), "build", "unknown")
    return Response(source.replace("__BUILD__", str(build)), media_type="text/html; charset=utf-8", headers=headers)


@router.get("/bench", include_in_schema=True)
async def bench_page(request: Request) -> Response:
    """The screen itself. It holds no data; it asks /bench/state."""
    return _page("bench.html", request, PAGE_HEADERS)


@router.get("/bench/cards", include_in_schema=True)
async def bench_cards_frame(request: Request) -> Response:
    """The frame a result's cards are drawn in (web/bench-cards.html), only inside the bench screen."""
    return _page("bench-cards.html", request, FRAME_HEADERS)


def _run_line(bench: Bench, run_id: str) -> dict[str, Any] | None:
    manifest = bench.manifest(run_id)
    if manifest is None:
        return None
    made = bench_report.build(bench, run_id)
    return {
        "run_id": run_id, "status": manifest.get("status"), "stopped": manifest.get("stopped", ""),
        "started_at": manifest.get("started_at"), "finished_at": manifest.get("finished_at"),
        "mode": manifest.get("mode"), "set_id": manifest.get("set_id"), "models": manifest.get("models") or {},
        "judge_version": manifest.get("judge_version", ""), "counts": made["counts"], "overall": made["overall"],
        "safety": made["safety"], "personas": [p["name"] for p in made["by_persona"]],
    }


@router.get("/bench/state")
async def bench_state(request: Request) -> JSONResponse:
    """Every run, newest first, and how often the judge agrees with George across all of them."""
    bench = _bench(request)
    runs = [line for line in (_run_line(bench, run_id) for run_id in bench.runs()[:MAX_RUNS]) if line]
    return _answer({"ok": True, "runs": runs, "agreement": bench_report.agreement_for(bench),
                    "sets": len(bench.sets())})


def _row(row: dict[str, Any], verdict: dict[str, Any] | None, rating: dict[str, Any] | None) -> dict[str, Any]:
    scored = bool(verdict) and "scores" in verdict and "error" not in verdict
    return {
        "result_id": row.get("result_id"), "persona": row.get("persona"), "persona_name": row.get("persona_name"),
        "access": row.get("access"), "category": row.get("category"), "said": (row.get("said") or [""])[0][:200],
        "turns": len(row.get("said") or []), "overall": verdict.get("overall") if scored else None,
        "flags": verdict.get("flags", []) if scored else [], "error": bool(row.get("error")),
        "rated": rating.get("score") if rating else None,
        "staged": len(row.get("staged_writes") or []), "tools": len(row.get("tools_used") or []),
    }


@router.get("/bench/runs/{run_id}")
async def bench_run(request: Request, run_id: str) -> JSONResponse:
    if not RUN_ID.fullmatch(run_id):
        return _refusal(404, "no_run", "There is no such run.")
    bench = _bench(request)
    if bench.manifest(run_id) is None:
        return _refusal(404, "no_run", "There is no such run.")
    made = bench_report.build(bench, run_id)
    judged = bench.judged(run_id)
    ratings = {rid: r for (rated_run, rid), r in bench.ratings().items() if rated_run == run_id}
    rows = [_row(r, judged.get(str(r.get("result_id"))), ratings.get(str(r.get("result_id"))))
            for r in bench.results(run_id)]
    return _answer({"ok": True, "report": made, "results": rows})


@router.get("/bench/runs/{run_id}/results/{result_id}")
async def bench_result(request: Request, run_id: str, result_id: str) -> JSONResponse:
    if not RUN_ID.fullmatch(run_id) or not RESULT_ID.fullmatch(result_id):
        return _refusal(404, "no_result", "There is no such result.")
    bench = _bench(request)
    row = next((r for r in bench.results(run_id) if r.get("result_id") == result_id), None)
    if row is None:
        return _refusal(404, "no_result", "There is no such result.")
    rating = bench.ratings().get((run_id, result_id))
    return _answer({"ok": True, "result": row, "verdict": bench.judged(run_id).get(result_id),
                    "rating": rating, "run": {"run_id": run_id, "mode": (bench.manifest(run_id) or {}).get("mode")}})


@router.post("/bench/ratings")
async def bench_rate(request: Request) -> JSONResponse:
    """George's rating of one result: 1 to 5 and a short note. Kept beside what the judge said."""
    from app.routes.actions import principal_check

    raw = await request.body()
    if len(raw) > MAX_BODY:
        return _refusal(413, "too_big", "That note is too long.")
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return _refusal(400, "bad_request", "The screen sent something unreadable. Reload it.")
    if not isinstance(body, dict):
        return _refusal(400, "bad_request", "The screen sent something unreadable. Reload it.")
    run_id, result_id, score = str(body.get("run_id") or ""), str(body.get("result_id") or ""), body.get("score")
    if not RUN_ID.fullmatch(run_id) or not RESULT_ID.fullmatch(result_id):
        return _refusal(404, "no_result", "There is no such result.")
    if not (isinstance(score, int) and not isinstance(score, bool) and 1 <= score <= 5):
        return _refusal(400, "bad_score", "A rating is a whole number from 1 to 5.")
    note = body.get("note") or ""
    if not isinstance(note, str) or len(note) > MAX_NOTE:
        return _refusal(400, "bad_note", f"A note is at most {MAX_NOTE} characters of text.")
    bench = _bench(request)
    if not any(r.get("result_id") == result_id for r in bench.results(run_id)):
        return _refusal(404, "no_result", "There is no such result.")
    who, _why = principal_check(request)
    kept = bench.rate(run_id, result_id, score, note, by=who, judge=bench.judged(run_id).get(result_id))
    return _answer({"ok": True, "rating": kept, "agreement": bench_report.agreement_for(bench),
                    "run_agreement": bench_report.agreement_for(bench, run_id)})
