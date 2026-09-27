"""The capability-gap record (app/objectives/gaps.py): what CLIVE cannot do yet, how often it
comes up, and what became of it. Whether CLIVE proposes builds for the gaps that come up most,
whether the owner filed them, whether they were built and merged, and whether a merged fix
stopped its gap coming back."""

from __future__ import annotations

import json

import httpx
import pytest

from app.engineering_bridge.github import EngineeringInbox
from app.objectives import gaps as gaps_module
from app.objectives import store as store_module
from app.routes import objectives as objectives_route
from app.session.models import Session
from app.tools import engineering_tools
from app.tools.dispatch import dispatch, make_pretooluse_hook
from tests.test_build_from_clive import HOST, REPO, TOKEN, TRUNK_SHA, FakeGitHub

CANDIDATE = "c" * 40
RUNNING = "d" * 40


class FakeWithTrunk(FakeGitHub):
    """The builder host's branches, and which commits the trunk and the running CLIVE have."""

    def __init__(self) -> None:
        super().__init__()
        self.contains: dict[str, set[str]] = {"clive/trunk": set(), RUNNING: set()}
        self.compares = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path[len(f"/repos/{REPO}"):]
        if request.method == "GET" and path.startswith("/compare/"):
            self.compares += 1
            base, head = path[len("/compare/"):].split("...", 1)
            return httpx.Response(200, json={"status": "ahead" if base in self.contains.get(head, set()) else "diverged"})
        return super().handle(request)


@pytest.fixture()
def record(tmp_path, monkeypatch) -> gaps_module.GapLedger:
    ledger = gaps_module.GapLedger(tmp_path / "objectives" / "gaps.json")
    monkeypatch.setattr(gaps_module, "_LEDGER", ledger)
    return ledger


@pytest.fixture()
def objectives(tmp_path, monkeypatch) -> store_module.ObjectiveStore:
    fresh = store_module.ObjectiveStore(tmp_path / "objectives")
    monkeypatch.setattr(store_module, "_STORE", fresh)
    return fresh


@pytest.fixture()
def fake() -> FakeWithTrunk:
    return FakeWithTrunk()


@pytest.fixture()
def bound(fake, monkeypatch) -> EngineeringInbox:
    inbox = EngineeringInbox(REPO, token_source=lambda: TOKEN, transport=fake.transport(), host=HOST)
    monkeypatch.setattr(engineering_tools, "_inbox", inbox)
    monkeypatch.setattr(engineering_tools, "_progress_cache", {})
    return inbox


def gap(report: dict, key: str) -> dict:
    return next(g for g in report["gaps"] if g["key"] == key)


# ------------------------------------------------------------------ what counts as a gap


def test_a_gap_is_keyed_by_the_capability_named_or_by_the_blockers_own_words():
    assert gaps_module.key_for("Web Search!", "anything") == "web search"
    assert gaps_module.key_for("", "No web or research tool to look up the trend.") == "web research tool look up trend"
    assert gaps_module.key_for("", "") == "unnamed"
    assert gaps_module.tool_key("web_search") == "tool: web_search"


def test_missing_capability_blockers_are_counted_and_other_blockers_are_not(record, objectives):
    trip = objectives.create(title="Trip", request="Get to Lagos by the 13th")
    shoot = objectives.create(title="Shoot", request="Book a studio")
    objectives.add_blocker(trip.id, "No web search to check flights", kind="missing_capability", capability="web search")
    objectives.add_blocker(shoot.id, "Cannot look studios up online", kind="missing_capability", capability="Web search")
    objectives.add_blocker(shoot.id, "Waiting for the studio to reply", kind="external")

    report = record.report()
    assert [g["key"] for g in report["gaps"]] == ["web search"]
    web = gap(report, "web search")
    assert web["hits"] == 2 and web["sources"] == {"blocker": 2}
    assert web["objectives"] == [trip.id, shoot.id] and web["stage"] == "open"
    assert web["title"] == "Web search" and web["label"] == "No web search to check flights"
    assert objectives.get(trip.id).blockers[0]["capability"] == "web search"
    assert objectives.gap_keys(shoot.id) == ["web search"]


async def test_a_tool_the_model_reaches_for_and_clive_lacks_is_a_gap(record):
    session = Session(session_id="gap-tool")
    out = await dispatch("web_search", {"query": "flights"}, session=session, timeout_s=5)
    assert out.startswith("REFUSED")
    hook = make_pretooluse_hook(lambda: session)
    await hook({"tool_name": "web_search", "tool_input": {}}, None, None)
    await dispatch("shopify_order_detail", {}, session=session, timeout_s=5)   # a rule, not a gap
    # Reaching for the owner's own gesture is never a gap, and never something to build.
    for name in ("approve_proposal", "execute_proposal", "confirm_action", "authorise_refund", "gate_override"):
        await dispatch(name, {}, session=session, timeout_s=5)

    report = record.report()
    assert [g["key"] for g in report["gaps"]] == ["tool: web_search"]
    assert gap(report, "tool: web_search")["hits"] == 2


def test_declining_what_clive_can_compose_is_counted_apart_from_the_gaps(record):
    record.note_misjudged(["best_sellers"])
    record.note_misjudged(["best_sellers", "comparison"])
    report = record.report()
    assert report["gaps"] == [] and report["summary"]["misjudged"] == 3
    assert report["misjudged"][0]["capability"] == "best_sellers" and report["misjudged"][0]["count"] == 2


def test_the_gaps_already_recorded_are_counted_once(record, objectives):
    obj = objectives.create(title="Display", request="Show a task on the big screen")
    objectives.add_blocker(obj.id, "No display tool to project an expanded view", kind="missing_capability")
    fresh = gaps_module.GapLedger(record.path.with_name("seeded.json"))
    fresh.seed(objectives.all())
    fresh.seed(objectives.all())
    (only,) = fresh.report()["gaps"]
    assert only["key"] == "display tool project expanded view" and only["hits"] == 1


def test_a_record_that_cannot_be_written_never_raises(tmp_path, caplog):
    blocked = tmp_path / "gaps.json"
    blocked.mkdir()   # a folder where the file should be
    ledger = gaps_module.GapLedger(blocked)
    ledger.note_blocker("obj_00000000", "No web search", "web search")
    assert "gap record not updated" in caplog.text


def test_nothing_is_recorded_before_the_runtime_installs_the_record(objectives, monkeypatch):
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    obj = objectives.create(title="Trip", request="Get to Lagos")
    objectives.add_blocker(obj.id, "No web search", kind="missing_capability", capability="web search")
    assert not (objectives.root / "gaps.json").exists()


# ------------------------------------------------------------------ what became of it


async def test_a_gap_is_followed_from_proposal_to_a_fix_that_held_or_came_back(record, objectives, fake, bound, monkeypatch):
    obj = objectives.create(title="Display", request="Show a task on the big screen")
    objectives.add_blocker(obj.id, "No big-screen display", kind="missing_capability", capability="big-screen display")
    objectives.add_blocker(obj.id, "No web search", kind="missing_capability", capability="web search")
    objectives.add_blocker(obj.id, "No web search", kind="missing_capability", capability="web search")

    session = Session(session_id="gap-build")
    await dispatch("engineering_status", {"areas": True}, session=session, timeout_s=5)
    out = await dispatch("submit_engineering_request", {
        "inbox_id": fake.heads["clive/control/worker-01-inbox"], "title": "Show a task on the big screen",
        "requested_outcome": "Pull a fulfilment slip up large.", "allowed_paths": ["app/scenes"], "objective_id": obj.id,
    }, session=session, timeout_s=5)
    assert out.startswith("PROPOSED ("), out
    rid = session.proposals[0].execution["request_id"]
    report = record.report()
    assert gap(report, "big screen display")["stage"] == "proposed"
    assert gap(report, "web search")["stage"] == "proposed"
    # The gap that came up most is first; both of the top gaps have a build proposed.
    assert [g["key"] for g in report["gaps"]] == ["web search", "big screen display"]
    assert report["summary"]["top_proposed"] == 2 == report["summary"]["top"]

    record.filed(rid)   # the owner's tap (the engine's own path is tests/test_build_from_clive.py)
    assert gap(record.report(), "web search")["stage"] == "filed"

    now = [100.0]
    monkeypatch.setattr(engineering_tools.time, "monotonic", lambda: now[0])
    engineering_tools._progress_cache.clear()   # the status read above was on the real clock
    fake.status["requests"] = [{"request_id": rid, "stage": "COMPLETE", "candidate_sha": CANDIDATE}]
    await engineering_tools.refresh_gaps()
    assert gap(record.report(), "web search")["stage"] == "built"

    monkeypatch.setattr(engineering_tools, "running_sha", lambda: RUNNING)
    fake.contains["clive/trunk"].add(CANDIDATE)
    await engineering_tools.refresh_gaps()
    assert fake.compares == 2, "the trunk and the running commit, compared at most once a minute"
    now[0] += engineering_tools.PROGRESS_TTL_S + 1
    await engineering_tools.refresh_gaps()
    report = record.report()
    assert gap(report, "web search")["stage"] == "merged"
    assert gap(report, "web search")["hits_after_fix"] is None, "not live, so not yet a fix"
    assert report["summary"]["merged"] == 2 and report["summary"]["live"] == 0

    fake.contains[RUNNING].add(CANDIDATE)   # deployed
    now[0] += engineering_tools.PROGRESS_TTL_S + 1
    await engineering_tools.refresh_gaps()
    report = record.report()
    assert gap(report, "web search")["stage"] == "live"
    assert gap(report, "web search")["hits_after_fix"] == 0
    assert report["summary"]["live"] == 2 and report["summary"]["fixes_held"] == 2

    # The fix did not stop one of them.
    later = "2999-01-01T00:00:00+00:00"
    record.note_blocker(obj.id, "Still no web search", "web search", at=later)
    report = record.report()
    assert gap(report, "web search")["hits_after_fix"] == 1
    assert report["summary"]["fixes_held"] == 1 and report["summary"]["fixes_recurred"] == 1


async def test_the_gaps_route_reports_the_record(record, objectives, fake, bound):
    obj = objectives.create(title="Trip", request="Get to Lagos")
    objectives.add_blocker(obj.id, "No web search", kind="missing_capability", capability="web search")
    out = await objectives_route.gaps()
    assert out["summary"]["gaps"] == 1 and out["gaps"][0]["key"] == "web search"
    json.dumps(out)


async def test_the_gaps_route_with_no_record_is_empty(monkeypatch):
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    assert (await objectives_route.gaps())["gaps"] == []


def test_the_prompt_asks_clive_to_name_what_it_lacks_the_same_way_each_time(tmp_path):
    from app.kb.loader import build_system_prompt, load

    prompt = build_system_prompt(load(tmp_path))
    assert "with capability naming what" in prompt and "the same words each time" in prompt


def test_the_running_commit_is_read_from_the_checkout(tmp_path):
    git = tmp_path / ".git"
    (git / "refs" / "heads").mkdir(parents=True)
    (git / "HEAD").write_text(RUNNING + "\n")
    assert engineering_tools.running_sha(tmp_path) == RUNNING
    (git / "HEAD").write_text("ref: refs/heads/clive/trunk\n")
    (git / "packed-refs").write_text(f"# pack-refs\n{CANDIDATE} refs/heads/clive/trunk\n")
    assert engineering_tools.running_sha(tmp_path) == CANDIDATE
    (git / "refs" / "heads" / "clive").mkdir()
    (git / "refs" / "heads" / "clive" / "trunk").write_text(TRUNK_SHA + "\n")
    assert engineering_tools.running_sha(tmp_path) == TRUNK_SHA
    assert engineering_tools.running_sha(tmp_path / "nowhere") == ""


def test_the_record_is_private_minimal_and_forgets_what_nobody_hits(record, objectives):
    """The 2026-09-26 deploy review, F-07."""
    import os
    import stat
    from datetime import UTC, datetime, timedelta

    from app.observability import timeline as timeline_module

    timeline_module.note_names(["Greg Evans"])
    try:
        old = os.umask(0o022)
        try:
            record.note_blocker("obj_00000001", "Greg Evans (greg@example.com, 07700 900123) needs a custom price", "custom line price")
        finally:
            os.umask(old)
    finally:
        timeline_module.forget_names()
    assert stat.S_IMODE(record.path.stat().st_mode) == 0o600
    assert stat.S_IMODE(record.path.parent.stat().st_mode) == 0o700
    text = record.path.read_text()
    for leak in ("Greg", "greg@example.com", "07700 900123"):
        assert leak not in text, leak
    assert not list(record.path.parent.glob(".*.tmp"))

    import json

    record.note_blocker("obj_00000002", "No carrier tracking", "carrier tracking")
    record.note_blocker("obj_00000003", "No web search", "web search")
    record.proposed("add-web-search", "obj_00000003", ["web search"])
    stale = (datetime.now(UTC) - timedelta(days=gaps_module.KEEP_DAYS + 1)).isoformat(timespec="seconds")
    data = json.loads(record.path.read_text())
    for key in ("carrier tracking", "web search"):
        data["gaps"][key]["last_seen"] = stale
    record.path.write_text(json.dumps(data))
    record.note_misjudged(["best_sellers"])   # any write applies the age
    keys = {g["key"] for g in record.report()["gaps"]}
    assert "carrier tracking" not in keys, "unhit for half a year, nothing built: forgotten"
    assert {"web search", "custom line price"} <= keys, "a gap with a build proposed is kept"


def test_every_key_and_name_it_writes_is_redacted_or_allow_listed(record):
    """F-07, second round: not only the label."""
    from app.observability import timeline as timeline_module
    from tests.fake_credentials import github_token

    token = github_token("gap-keys")
    timeline_module.note_names(["Greg Evans"])
    try:
        record.note_blocker("obj_00000001", "needs a custom price", f"custom price for Greg Evans {token}")
        record.note_missing_tool(f"lookup_{token}")
        record.note_misjudged([f"leak {token}", "best_sellers"])
    finally:
        timeline_module.forget_names()
    text = record.path.read_text()
    assert token not in text and "Greg" not in text
    report = record.report()
    assert {m["capability"] for m in report["misjudged"]} == {"other", "best_sellers"}


def test_a_record_written_before_keys_were_cleaned_is_cleaned_when_read(record):
    """F-07, third round: the file on the server was written by the build before; its keys,
    names and labels are cleaned on load, duplicates merged, and saved clean with the next
    change."""
    import json

    from tests.fake_credentials import github_token

    token = github_token("legacy-gap")
    record.path.parent.mkdir(parents=True, exist_ok=True)
    record.path.write_text(json.dumps({
        "version": 1, "seeded": "2026-09-27T00:07:00+00:00",
        "gaps": {
            f"web search {token}": {"label": f"No web search ({token})", "hits": 2, "sources": {"blocker": 2},
                                    "objectives": ["obj_00000001"], "requests": [], "seen": ["2026-09-26T21:30:20+00:00"],
                                    "first_seen": "2026-09-26T21:30:20+00:00", "last_seen": "2026-09-26T21:30:20+00:00",
                                    "name": f"Web search {token}"},
            "Web  Search": {"label": "No web search", "hits": 1, "sources": {"blocker": 1}, "objectives": ["obj_00000002"],
                            "requests": [], "seen": ["2026-09-26T23:00:00+00:00"],
                            "first_seen": "2026-09-26T23:00:00+00:00", "last_seen": "2026-09-26T23:00:00+00:00"},
        },
        "builds": {}, "misjudged": {f"x {token}": {"count": 1}},
    }))
    report = record.report()
    assert token not in json.dumps(report)
    record.note_misjudged(["best_sellers"])   # any change saves the cleaned record
    assert token not in record.path.read_text()
    web = [g for g in report["gaps"] if g["key"].startswith("web search")]
    assert web, report["gaps"]
