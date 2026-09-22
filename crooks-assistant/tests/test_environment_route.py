"""GET /environment/state: the Agent Environment's one read of CLIVE, and what it refuses to invent.

The route serves the document scripts/agent_state_view.py builds, so the projection's own
tests cover the probes. What is tested here is the route's part of the contract: the
schema, the owner-requested fields on every record, a roster that cannot be read reported
as a problem rather than an empty world, a declared worker with nothing behind it reported
OFFLINE rather than absent, and that the route changes nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from app.routes import environment

OWNER_REQUESTED = (
    "worker_id", "display_name", "role", "status", "current_task", "project", "branch",
    "head_sha", "last_heartbeat", "last_event", "last_event_at", "blocker", "owner_gate",
)
VOCABULARY = {"OFFLINE", "IDLE", "BUILDING", "REVIEWING", "BLOCKED", "OWNER_GATE", "STALE", "UNKNOWN"}


def roster_with(tmp_path: Path, workers: list[dict]) -> Path:
    path = tmp_path / "roster.json"
    path.write_text(json.dumps({"schema": "clive.agent_roster.v1", "fresh_window_s": 900,
                                "stale_window_s": 3600, "workers": workers}), encoding="utf-8")
    return path


@pytest.fixture()
async def client(tmp_path):
    """A minimal app carrying only this router, so nothing else's startup runs."""
    app = FastAPI()
    app.include_router(environment.router)
    app.state.agent_roster_path = roster_with(tmp_path, [
        {"worker_id": "ghost", "display_name": "Ghost", "role": "builder", "project": "clive",
         "probe": {"kind": "worktree_process", "worktree": str(tmp_path / "nowhere"),
                   "declared_branch": "claude/nothing"}},
    ])
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        c.app = app  # type: ignore[attr-defined]
        yield c


async def test_the_document_carries_its_schema_and_every_owner_requested_field(client):
    body = (await client.get("/environment/state")).json()
    assert body["schema"] == "clive.agent_environment_view.v1"
    datetime.fromisoformat(body["generated_at"].replace("Z", "+00:00")).astimezone(UTC)
    assert body["generator"] == "app/routes/environment.py"
    assert body["totals"]["declared"] == 1
    for record in body["workers"]:
        for field in OWNER_REQUESTED:
            assert field in record, field
        assert "status_reason" in record and "evidence" in record
        assert record["status"] in VOCABULARY


async def test_a_declared_worker_with_nothing_behind_it_is_offline_not_absent(client):
    body = (await client.get("/environment/state")).json()
    ghost = body["workers"][0]
    assert ghost["worker_id"] == "ghost"
    assert ghost["status"] == "OFFLINE"
    assert "does not exist" in ghost["status_reason"]
    assert body["totals"]["online"] == 0 and body["totals"]["working"] == 0


async def test_a_roster_the_route_cannot_read_is_a_problem_not_an_empty_campus(client, tmp_path):
    client.app.state.agent_roster_path = tmp_path / "missing.json"
    body = (await client.get("/environment/state")).json()
    assert body["schema"] == "clive.agent_environment_view.v1"
    assert body["workers"] == []
    assert body["totals"]["declared"] == 0
    assert body["problem"].startswith("roster unreadable")

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    client.app.state.agent_roster_path = broken
    body = (await client.get("/environment/state")).json()
    assert body["problem"].startswith("roster is not valid JSON")

    not_object = tmp_path / "list.json"
    not_object.write_text("[]", encoding="utf-8")
    client.app.state.agent_roster_path = not_object
    body = (await client.get("/environment/state")).json()
    assert body["problem"] == "roster is not a JSON object"


async def test_the_route_is_read_only_and_reads_nothing_into_existence(client, tmp_path):
    assert (await client.post("/environment/state")).status_code == 405
    before = sorted(p.name for p in tmp_path.iterdir())
    await client.get("/environment/state")
    assert sorted(p.name for p in tmp_path.iterdir()) == before, "the probe wrote something"


def test_the_real_app_mounts_the_route_at_the_documented_path():
    """Through the OpenAPI schema, which sees inside included routers whatever this FastAPI
    version wraps them in."""
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/environment/state" in paths
    assert set(paths["/environment/state"]) == {"get"}
