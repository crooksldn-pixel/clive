"""The Agent Environment's one read: what CLIVE engineering is actually doing, from evidence.

The Agent Environment is a projection. It renders what this route says and asserts nothing of
its own, so this route must say only what the system can be made to prove. It serves the
``clive.agent_environment_view.v1`` document that ``scripts/agent_state_view.py`` builds —
the same code, the same roster, the same probes (process table, file mtimes, systemd, git),
read-only by construction — so a dashboard polling here and an operator running the script
cannot disagree.

Two things this route never does. It never fabricates a worker: a roster entry with nothing
behind it is reported OFFLINE, and a probe that cannot settle a question reports UNKNOWN with
its reason. And it never hides a failure of its own behind an empty world: a roster it cannot
read is reported as a problem with zero declared workers, which the environment shows as
"could not look", not as "nobody is here".
"""

from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

router = APIRouter()

SCHEMA = "clive.agent_environment_view.v1"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ROSTER = ROOT / "config" / "agent_roster.json"


def _state_view():
    # The script is the one source of the probes; importing it rather than copying it is the
    # whole point. ROOT is on sys.path wherever the app runs (uvicorn from ROOT, pytest from ROOT).
    from scripts import agent_state_view

    return agent_state_view


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _empty_totals() -> dict:
    return {"declared": 0, "online": 0, "working": 0, "idle": 0, "stale": 0, "blocked": 0,
            "owner_gate": 0, "unknown": 0}


def roster_path_for(request: Request) -> Path:
    """The roster this app reads. Tests point it elsewhere through app.state; nothing else does."""
    configured = getattr(request.app.state, "agent_roster_path", None)
    return Path(configured) if configured else DEFAULT_ROSTER


def unreadable(roster_path: Path, reason: str) -> dict:
    """A view that says the observer could not look. Same schema, no workers, and a `problem`
    the environment must show instead of an empty campus."""
    return {
        "schema": SCHEMA,
        "generated_at": _now(),
        "generator": "app/routes/environment.py",
        "host": os.uname().nodename,
        "fresh_window_s": None,
        "stale_window_s": None,
        "workers": [],
        "totals": _empty_totals(),
        "roster_path": str(roster_path),
        "problem": reason,
    }


@router.get("/environment/state")
async def environment_state(request: Request) -> dict:
    """Read-only. Safe to poll: it opens files, reads /proc, and runs git and systemctl in
    query form. It writes nothing, starts nothing and stops nothing. Every worker in the
    roster is probed against the live system on every call."""
    roster_path = roster_path_for(request)
    try:
        roster = json.loads(roster_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return unreadable(roster_path, f"roster unreadable: {exc}")
    except json.JSONDecodeError as exc:
        return unreadable(roster_path, f"roster is not valid JSON: {exc}")
    if not isinstance(roster, dict):
        return unreadable(roster_path, "roster is not a JSON object")

    started = time.monotonic()
    # The probes block (subprocess, os.walk); the event loop must not.
    view = await run_in_threadpool(_state_view().build_view, roster)
    view["generator"] = "app/routes/environment.py"
    view["roster_path"] = str(roster_path)
    view["probe_duration_s"] = round(time.monotonic() - started, 3)
    return view
