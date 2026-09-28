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


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
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


@pytest.mark.usefixtures("owner_asking")   # the admitted owner calling a tool directly (round 8, F-A2-FIXTURE)
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
    # The commit this CLIVE runs, fixed before the first refresh reads it: read from the real
    # checkout it is "" in a git worktree and a real SHA in a clone, and the count below changed
    # with it (found on clive-worker-01, 2026-09-27).
    monkeypatch.setattr(engineering_tools, "running_sha", lambda: RUNNING)
    engineering_tools._progress_cache.clear()   # the status read above was on the real clock
    fake.status["requests"] = [{"request_id": rid, "stage": "COMPLETE", "candidate_sha": CANDIDATE}]
    await engineering_tools.refresh_gaps()
    assert gap(record.report(), "web search")["stage"] == "built"

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


def _legacy_record(path, token: str) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = json.dumps({
        "version": 1,
        "gaps": {
            f"web search {token}": {"label": f"No web search ({token})", "hits": 2, "sources": {"blocker": 2},
                                    "objectives": ["obj_00000001"], "requests": [], "seen": ["2026-09-26T21:30:20+00:00"],
                                    "first_seen": "2026-09-26T21:30:20+00:00", "last_seen": "2026-09-26T21:30:20+00:00"},
            "Web  Search": {"label": "No web search", "hits": 1, "sources": {"blocker": 1}, "objectives": ["obj_00000002"],
                            "requests": [], "seen": ["2026-09-26T23:00:00+00:00"],
                            "first_seen": "2026-09-26T23:00:00+00:00", "last_seen": "2026-09-26T23:00:00+00:00"},
        },
        "builds": {}, "misjudged": {},
    }, indent=1).encode("utf-8")
    path.write_bytes(raw)
    return raw


def test_the_record_on_disk_is_cleaned_at_startup_and_the_original_kept_first(tmp_path, monkeypatch):
    """F-07, fourth round: load() cleaned only in memory, so the live file stayed dirty until an
    unrelated change saved it, and that save was one way. Now install() cleans the file on disk
    at startup, after copying the exact original aside (0600, beside it, never overwritten)."""
    from tests.fake_credentials import github_token

    token = github_token("startup-gap")
    path = tmp_path / "objectives" / "gaps.json"
    raw = _legacy_record(path, token)
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    ledger = gaps_module.install(path)
    assert token not in path.read_text(), "the file on disk is clean with no change having happened"
    kept = sorted(path.parent.glob("gaps.json.*.before-clean"))
    assert len(kept) == 1 and kept[0].read_bytes() == raw, "the original, byte for byte"
    assert oct(kept[0].stat().st_mode & 0o777) == "0o600"
    assert oct(path.parent.stat().st_mode & 0o777) == "0o700"
    cleaned = json.loads(path.read_text())["gaps"]
    assert "Web  Search" not in cleaned and cleaned["web search"]["hits"] == 1
    assert sum(g["hits"] for g in cleaned.values()) == 3 and not any(token in k for k in cleaned)
    # Rolling back is putting the copy back: nothing in it was lost.
    assert json.loads(kept[0].read_text())["gaps"][f"web search {token}"]["hits"] == 2
    # Idempotent: a clean record is left alone, and no second copy is made.
    assert ledger.repair() is None and gaps_module.install(path).repair() is None
    assert len(list(path.parent.glob("gaps.json.*.before-clean"))) == 1


def test_a_clean_record_is_never_rewritten_or_copied(tmp_path, monkeypatch):
    path = tmp_path / "objectives" / "gaps.json"
    ledger = gaps_module.GapLedger(path)
    ledger.note_blocker("obj_00000001", "No web search", "web search")
    before = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    assert gaps_module.install(path).repair() is None
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime
    assert not list(path.parent.glob("gaps.json.*"))


def test_nothing_is_saved_over_the_record_unless_the_original_could_be_kept(tmp_path, monkeypatch, caplog):
    from tests.fake_credentials import github_token

    token = github_token("no-copy")
    path = tmp_path / "objectives" / "gaps.json"
    raw = _legacy_record(path, token)

    def cannot_copy(self, data, why):
        raise OSError("disk full")

    monkeypatch.setattr(gaps_module.GapLedger, "_keep_original", cannot_copy)
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    ledger = gaps_module.install(path)
    assert "left exactly as it was" in caplog.text
    ledger.note_blocker("obj_00000003", "No web search", "web search")
    assert path.read_bytes() == raw, "no copy, no save: the change is dropped, not made one way"
    assert "gap record not updated" in caplog.text


def test_an_unreadable_record_is_kept_aside_before_a_fresh_one_is_started(tmp_path):
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)
    path.write_bytes(b'{"version": 1, "gaps": {')   # cut off mid-write by something else
    ledger = gaps_module.GapLedger(path)
    ledger.note_blocker("obj_00000004", "No web search", "web search")
    (kept,) = path.parent.glob("gaps.json.*.unreadable")
    assert kept.read_bytes() == b'{"version": 1, "gaps": {'
    assert json.loads(path.read_text())["gaps"]["web search"]["hits"] == 1


def test_a_stored_row_cannot_stand_in_for_its_cleaned_key_or_carry_fields_of_its_own(tmp_path, monkeypatch):
    """Round 6, F-07: the report spread each misjudged row after its key, so a legacy row carrying
    its own "capability" overrode the cleaned one. Only the fields the record writes survive a
    read, and the report names the cleaned key last."""
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)
    path.write_text(json.dumps({
        "version": 1, "seeded": "2026-09-20T00:00:00+00:00", "customer": "Greg Evans",
        "gaps": {"web search": {"label": "No web search", "hits": 2, "sources": {"blocker": 2, "Greg": 1},
                                "objectives": ["obj_00000001", "Greg Evans"], "requests": ["find-web-search", "../x"],
                                "seen": ["2026-09-26T21:30:20+00:00", "not a time"],
                                "first_seen": "2026-09-26T21:30:20+00:00", "last_seen": "2026-09-26T21:30:20+00:00",
                                "note": "call Greg on 07700 900123"}},
        "builds": {"find-web-search": {"objective_id": "obj_00000001", "gaps": ["web search"],
                                       "proposed_at": "2026-09-26T22:00:00+00:00", "email": "greg@example.com",
                                       "candidate_sha": "not-a-sha", "progress": "done"},
                   "Greg Evans": {"gaps": []}},
        "misjudged": {"best_sellers": {"count": 3, "capability": "Greg Evans", "note": "x"}},
    }))
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    ledger = gaps_module.install(path)
    report = ledger.report()
    assert report["misjudged"] == [{"count": 3, "first_seen": None, "last_seen": None, "capability": "best_sellers"}]
    stored = path.read_text()
    for leak in ("Greg", "07700", "greg@example.com", "not-a-sha", "../x", "not a time", "customer", "note"):
        assert leak not in stored, leak
    kept = json.loads(stored)
    assert set(kept) == {"version", "seeded", "gaps", "builds", "misjudged"}
    assert set(kept["gaps"]["web search"]) <= set(gaps_module._GAP_FIELDS)
    assert kept["gaps"]["web search"]["objectives"] == ["obj_00000001"]
    assert kept["gaps"]["web search"]["requests"] == ["find-web-search"]
    assert list(kept["builds"]) == ["find-web-search"]
    assert kept["builds"]["find-web-search"]["progress"] == "done"
    assert "candidate_sha" not in kept["builds"]["find-web-search"]
    assert len(list(path.parent.glob("gaps.json.*.before-clean"))) == 1, "the original was kept first"


def test_links_between_gaps_and_builds_point_only_at_what_is_still_there(tmp_path, monkeypatch):
    """Round 6, F-07: a build's gap keys were remapped with no check that the gap survived, and a
    gap could name a build the record no longer held. Merging two legacy keys into one sums their
    counts and joins their links; every link left points at something in the record."""
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)
    path.write_text(json.dumps({
        "version": 1,
        "gaps": {
            "Web  Search": {"label": "No web search", "hits": 2, "sources": {"blocker": 2}, "objectives": ["obj_00000001"],
                            "requests": ["find-web-search", "gone-away"], "seen": ["2026-09-26T21:00:00+00:00"],
                            "first_seen": "2026-09-26T21:00:00+00:00", "last_seen": "2026-09-26T21:00:00+00:00"},
            "web search": {"label": "No web search", "hits": 3, "sources": {"blocker": 1, "tool": 2},
                           "objectives": ["obj_00000002"], "requests": [], "seen": ["2026-09-26T22:00:00+00:00"],
                           "first_seen": "2026-09-26T22:00:00+00:00", "last_seen": "2026-09-26T22:00:00+00:00"},
        },
        "builds": {"find-web-search": {"objective_id": "obj_00000001", "gaps": ["Web  Search", "never-a-gap", "web search"],
                                       "proposed_at": "2026-09-26T22:30:00+00:00"}},
        "misjudged": {},
    }))
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    kept = json.loads(gaps_module.install(path) and path.read_text())
    assert list(kept["gaps"]) == ["web search"]
    gap = kept["gaps"]["web search"]
    assert gap["hits"] == 5 and gap["sources"] == {"blocker": 3, "tool": 2}
    assert sorted(gap["objectives"]) == ["obj_00000001", "obj_00000002"] and gap["requests"] == ["find-web-search"]
    assert kept["builds"]["find-web-search"]["gaps"] == ["web search"]
    assert gap["first_seen"] == "2026-09-26T21:00:00+00:00" and gap["last_seen"] == "2026-09-26T22:00:00+00:00"


def test_the_copy_and_the_clean_record_are_flushed_folder_and_all(tmp_path, monkeypatch):
    """Round 6, F-07: the copy was fsynced but its folder was not, so a power cut could lose the
    copy's name after the clean record had replaced the original. The folder is flushed after
    the copy and after every save."""
    from tests.fake_credentials import github_token

    path = tmp_path / "objectives" / "gaps.json"
    _legacy_record(path, github_token("fsync-dir"))
    synced: list[str] = []
    real = gaps_module._fsync_dir
    monkeypatch.setattr(gaps_module, "_fsync_dir", lambda folder: (synced.append("dir"), real(folder)))
    real_replace = gaps_module.os.replace
    monkeypatch.setattr(gaps_module.os, "replace", lambda a, b: (synced.append("replace"), real_replace(a, b)))
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    gaps_module.install(path)
    assert synced == ["dir", "replace", "dir"], "copy, its folder; then the clean record, its folder"


def _old_code():
    """The gap record's code as production runs it before this change (3e77f215), vendored
    verbatim in tests/rollback."""
    import hashlib
    from pathlib import Path

    from tests.rollback import gaps_3e77f215 as old

    source = Path(old.__file__).read_text(encoding="utf-8").split("\n", 5)[5]
    assert hashlib.sha256(source.encode()).hexdigest() == "b6bfba90973a1647659e4d3e24e61a006d8aaffbb03e52236ddc992c9f24c26f", \
        "the vendored copy is 3e77f215's file, byte for byte"
    return old


def test_the_code_a_rollback_returns_to_reads_writes_and_reports_the_cleaned_record(tmp_path, monkeypatch):
    """Round 6, F-07: the rollback check read the backup with json.loads, which says nothing
    about whether the code a rollback returns to can use the cleaned file. This runs that code —
    3e77f215's gaps.py, vendored verbatim — against it: it reads it, reports it the same way, and
    can go on writing to it, and what it writes the new code reads. Putting the backup back (the
    documented restoration) gives it the original, byte for byte."""
    from tests.fake_credentials import github_token

    old = _old_code()
    token = github_token("rollback")
    path = tmp_path / "objectives" / "gaps.json"
    raw = _legacy_record(path, token)
    data = json.loads(raw)
    data["gaps"]["web search"] = {"label": "No web search", "hits": 1, "sources": {"tool": 1}, "objectives": [],
                                  "requests": ["find-web-search"], "seen": ["2026-09-26T23:30:00+00:00"],
                                  "first_seen": "2026-09-26T23:30:00+00:00", "last_seen": "2026-09-26T23:30:00+00:00"}
    data["builds"] = {"find-web-search": {"objective_id": "obj_00000001", "gaps": ["web search"],
                                          "proposed_at": "2026-09-26T23:40:00+00:00", "filed_at": "2026-09-26T23:41:00+00:00"}}
    data["misjudged"] = {"best_sellers": {"count": 2, "first_seen": "2026-09-26T20:00:00+00:00",
                                          "last_seen": "2026-09-26T20:30:00+00:00"}}
    raw = json.dumps(data, indent=1).encode()
    path.write_bytes(raw)

    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    new = gaps_module.install(path)
    (backup,) = path.parent.glob("gaps.json.*.before-clean")
    assert token not in path.read_text()

    # The old code, on the cleaned file: it reads it, and says what the new code says.
    before = old.GapLedger(path)
    old_report, new_report = before.report(), new.report()
    assert old_report["summary"] == new_report["summary"]
    assert [(g["key"], g["hits"], g["stage"]) for g in old_report["gaps"]] == \
           [(g["key"], g["hits"], g["stage"]) for g in new_report["gaps"]]
    assert old_report["gaps"][0]["key"] == "web search" and old_report["gaps"][0]["stage"] == "filed"

    # It can go on writing to it, and the new code reads what it wrote.
    before.note_blocker("obj_00000003", "No web search", "web search")
    before.note_missing_tool("mcp__fetch__web")
    before.note_misjudged(["best_sellers"])
    after = gaps_module.GapLedger(path).report()
    hits = {g["key"]: g["hits"] for g in after["gaps"]}
    was = {g["key"]: g["hits"] for g in new_report["gaps"]}
    assert hits["web search"] == was["web search"] + 1 and after["summary"]["misjudged"] == 3
    assert any(k.startswith("tool: ") for k in hits)

    # And the documented restoration gives it the original back, which it reads as it always did.
    path.write_bytes(backup.read_bytes())
    assert path.read_bytes() == raw
    restored = old.GapLedger(path).report()
    assert any(token in g["key"] for g in restored["gaps"]), "the original, as it was"


# --------------------------------------------------------------------------- round 7, F-07


def test_every_kept_value_is_what_its_field_says_it_is(tmp_path, monkeypatch):
    """Round 7, F-07-VALUES: field names were whitelisted but not their values, so an email in a
    misjudged row's first_seen survived the rewrite into the report, and a count that was not a
    number broke it. Every value is now checked for what it must be, and a time that is not a time
    is dropped, never replaced by now."""
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)
    hostile = "greg@example.com"
    path.write_text(json.dumps({
        "version": "Greg Evans", "seeded": hostile,
        "gaps": {"web search": {"label": "No web search", "hits": "lots", "sources": {"blocker": "2", "tool": hostile},
                                "objectives": ["obj_00000001", 7], "requests": "find-web-search",
                                "seen": [hostile, "2026-09-26T21:30:20+00:00", 5], "first_seen": hostile,
                                "last_seen": "2026-09-26T21:30:20+00:00", "dropped": {"seen": hostile, "Greg": 3},
                                "seen_dropped_last": hostile}},
        "builds": {"find-web-search": {"objective_id": "obj_00000001", "gaps": ["web search", 3, None],
                                       "proposed_at": hostile, "filed_at": "2026-09-26T22:00:00Z", "progress": "done"}},
        "misjudged": {"best_sellers": {"count": "lots", "first_seen": hostile, "last_seen": "2026-09-26T20:00:00+00:00"},
                      "other": {"count": 10**30, "first_seen": None}},
    }))
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    ledger = gaps_module.install(path)
    stored = path.read_text()
    for leak in ("greg@example.com", "Greg", "lots", "1000000000000000000000000000000"):
        assert leak not in stored, leak
    kept = json.loads(stored)
    assert kept["version"] == gaps_module.VERSION and "seeded" not in kept
    gap = kept["gaps"]["web search"]
    assert gap["hits"] == 0 and gap["sources"] == {"blocker": 2} and gap["objectives"] == ["obj_00000001"]
    assert gap["seen"] == ["2026-09-26T21:30:20+00:00"] and "first_seen" not in gap and "seen_dropped_last" not in gap
    assert "dropped" not in gap
    build = kept["builds"]["find-web-search"]
    assert "proposed_at" not in build and build["filed_at"] == "2026-09-26T22:00:00+00:00"
    report = ledger.report()
    assert [(m["capability"], m["count"], m["first_seen"]) for m in report["misjudged"]] == [
        ("other", gaps_module._MAX_COUNT, None), ("best_sellers", 0, None)]
    assert gaps_module._sanitise is not None and gaps_module.GapLedger(path).repair() is None, "idempotent"


def test_a_link_counts_only_when_both_sides_name_each_other(tmp_path, monkeypatch):
    """Round 7, F-07-LINKS: the link pass checked only that the other end existed, so a gap could
    report the stage of a build that was never for it."""
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)
    row = {"label": "x", "hits": 1, "sources": {"blocker": 1}, "objectives": [], "seen": ["2026-09-26T21:00:00+00:00"],
           "first_seen": "2026-09-26T21:00:00+00:00", "last_seen": "2026-09-26T21:00:00+00:00"}
    path.write_text(json.dumps({
        "version": 1,
        "gaps": {"web search": {**row, "requests": ["find-web-search"]}, "maps": {**row, "requests": ["find-web-search"]}},
        "builds": {"find-web-search": {"objective_id": "obj_00000001", "gaps": ["maps"], "proposed_at": "2026-09-26T22:00:00+00:00",
                                       "live_at": "2026-09-27T09:00:00+00:00", "merged_at": "2026-09-27T08:00:00+00:00"}},
        "misjudged": {},
    }))
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    report = {g["key"]: g for g in gaps_module.install(path).report()["gaps"]}
    assert report["web search"]["stage"] == "open" and report["web search"]["not_kept"] == {"requests": 1}
    assert report["maps"]["stage"] == "live" and report["maps"]["not_kept"] == {}


def test_two_gaps_that_are_one_past_every_limit_keep_their_stage_and_say_what_they_could_not_keep(tmp_path, monkeypatch):
    """Round 7, F-07-LINKS: _merge truncated links and history silently, so a merged gap could lose
    the build that fixed it (and report the wrong stage) or the hits that came back after it. Now
    the builds kept are the furthest along, the rest are counted, and a count after the fix that
    forgotten history could add to says it is a floor."""
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)

    def stamp(day, n):
        return f"2026-09-{day:02d}T{n // 60:02d}:{n % 60:02d}:00+00:00"

    builds, gaps = {}, {}
    for side, key in ((0, "Web  Search"), (1, "web search")):
        requests = [f"find-web-{side}-{i}" for i in range(15)]
        for i, r in enumerate(requests):
            builds[r] = {"objective_id": "obj_00000001", "gaps": [key], "proposed_at": stamp(1, i)}
        gaps[key] = {"label": "No web search", "hits": 40, "sources": {"blocker": 40}, "objectives": [],
                     "requests": requests, "seen": [stamp(10 + side * 10, i) for i in range(40)],
                     "first_seen": stamp(10 + side * 10, 0), "last_seen": stamp(10 + side * 10, 39)}
    # The oldest build of the first side is the one that went live, on the 5th: every hit since
    # came back after it.
    builds["find-web-0-0"].update(merged_at=stamp(5, 0), live_at=stamp(5, 0))
    path.write_text(json.dumps({"version": 1, "gaps": gaps, "builds": builds, "misjudged": {}}))
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    ledger = gaps_module.install(path)
    kept = json.loads(path.read_text())["gaps"]["web search"]
    assert kept["hits"] == 80 and len(kept["requests"]) == gaps_module.MAX_LINKS
    assert "find-web-0-0" in kept["requests"], "the build that went live is never the one let go"
    assert kept["dropped"]["requests"] == 30 - gaps_module.MAX_LINKS and kept["dropped"]["seen"] == 30
    row = ledger.report()["gaps"][0]
    assert row["stage"] == "live" and row["not_kept"] == {"requests": 10, "seen": 30}
    # 80 hits after the fix; the 30 oldest times were forgotten, and they too came after it: the
    # count is what is known, and it says it is a floor.
    assert row["hits_after_fix"] == 50 and row["hits_after_fix_exact"] is False
    assert gaps_module.GapLedger(path).repair() is None, "idempotent"


def test_a_copy_whose_folder_could_not_be_flushed_leaves_the_live_record_untouched(tmp_path, monkeypatch, caplog):
    """Round 7, F-07-DURABILITY: _fsync_dir passed over its own failures, so the live file could be
    replaced while the copy's name was not yet durable. It raises now, before the save."""
    from tests.fake_credentials import github_token

    path = tmp_path / "objectives" / "gaps.json"
    raw = _legacy_record(path, github_token("dir-fsync"))

    def cannot(folder):
        raise OSError(5, "I/O error", str(folder))

    monkeypatch.setattr(gaps_module, "_fsync_dir", cannot)
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    gaps_module.install(path)
    assert path.read_bytes() == raw, "the live record is exactly as it was"
    assert "gap record not cleaned at startup" in caplog.text


def test_a_clean_tried_again_uses_the_copy_it_already_made(tmp_path, monkeypatch):
    """Round 7, F-07-DURABILITY: a save that failed after the copy was made meant another copy
    on the next try, and another after that. The copy already made, verified byte for byte, is
    used instead."""
    from tests.fake_credentials import github_token

    path = tmp_path / "objectives" / "gaps.json"
    raw = _legacy_record(path, github_token("retry"))
    real_save = gaps_module.GapLedger._save

    def failing(self, data, **kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(gaps_module.GapLedger, "_save", failing)
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    gaps_module.install(path)
    gaps_module.install(path)
    assert path.read_bytes() == raw
    assert len(list(path.parent.glob("gaps.json.*.before-clean"))) == 1
    monkeypatch.setattr(gaps_module.GapLedger, "_save", real_save)
    gaps_module.install(path)
    copies = list(path.parent.glob("gaps.json.*.before-clean"))
    assert len(copies) == 1 and copies[0].read_bytes() == raw and path.read_bytes() != raw


# --------------------------------------------------------------------------- round 8, F-07


def _hostile_known_values(path) -> None:
    """A record whose known fields hold every kind of JSON value that is not what the field says:
    digits int() refuses, booleans, lists and objects nested where a value goes, times that are
    valid but cannot be put in UTC, and text UTF-8 cannot write."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    edge = "0001-01-01T00:00:00+01:00"      # a real time, before year 1 in UTC
    late = "9999-12-31T23:59:59-01:00"      # a real time, after 9999 in UTC
    good = "2026-09-26T21:30:20+00:00"
    path.write_text(json.dumps({
        "version": [1], "seeded": edge,
        "gaps": {
            "web search": {"label": "\ud800", "name": {"x": 1}, "hits": "²", "sources": {"blocker": "٣", "tool": True},
                           "objectives": [["obj_00000001"], {"obj": 1}, "obj_00000001"], "requests": [["find-web-search"]],
                           "seen": [edge, late, [good], {"t": good}, good, True], "first_seen": [good], "last_seen": edge,
                           "dropped": {"seen": "²", "requests": False, "objectives": {"n": 1}}, "seen_dropped_last": late,
                           "uncertain": [["links"], {"history": 1}, True]},
            "maps": {"label": ["No maps"], "hits": True, "sources": [["blocker", 2]], "objectives": {"a": 1},
                     "requests": {"find-web-search": 1}, "seen": {"t": good}, "first_seen": {"t": good},
                     "last_seen": late, "dropped": [["seen", 3]], "uncertain": "links"},
        },
        "builds": {"find-web-search": {"objective_id": ["obj_00000001"], "gaps": [["web search"], {"k": 1}, "web search"],
                                       "proposed_at": edge, "filed_at": [good], "built_at": {"t": good}, "merged_at": late,
                                       "live_at": True, "progress": ["done"], "candidate_sha": {"sha": "c" * 40}}},
        "misjudged": {"best_sellers": {"count": "²", "first_seen": edge, "last_seen": late},
                      "comparison": {"count": True, "first_seen": [good], "last_seen": {"t": good}},
                      "other": {"count": [3], "first_seen": good}},
    }, ensure_ascii=True))


def test_counts_and_times_that_are_not_what_they_say_never_raise_through_the_report_or_the_rewrite(tmp_path, monkeypatch, caplog):
    """Round 8, F-07-VALUES: `_count` took any text isdigit() said yes to and int() refused '²';
    `_strict_iso` let a valid time near year 1 with a positive offset raise OverflowError on its
    way to UTC. The start-up rewrite caught the failure and left the file, and every report()
    after it failed on the same value. Both are total now: each such value is dropped."""
    path = tmp_path / "objectives" / "gaps.json"
    _hostile_known_values(path)
    before = path.read_bytes()
    monkeypatch.setattr(gaps_module, "_LEDGER", None)

    # The report, on the file as it is, before anything has rewritten it.
    first = gaps_module.GapLedger(path).report()
    json.dumps(first, allow_nan=False)
    assert path.read_bytes() == before, "a report reads; it never writes"

    # The start-up rewrite: it completes, and what it keeps is what each field says it is.
    ledger = gaps_module.install(path)
    assert "not cleaned at startup" not in caplog.text and "left exactly as it was" not in caplog.text
    (kept_copy,) = path.parent.glob("gaps.json.*.before-clean")
    assert kept_copy.read_bytes() == before, "the original, byte for byte, before the rewrite"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["version"] == gaps_module.VERSION and "seeded" not in stored
    web = stored["gaps"]["web search"]
    assert web["hits"] == 0 and web["sources"] == {} and web["objectives"] == ["obj_00000001"]
    assert web["requests"] == [] and web["seen"] == ["2026-09-26T21:30:20+00:00"]
    assert web["label"] == "web search" and "name" not in web
    assert web["last_seen"] == "2026-09-26T21:30:20+00:00", "a last hit that was not a time is the newest kept"
    for field in ("first_seen", "seen_dropped_last", "dropped", "uncertain"):
        assert field not in web, field
    maps = stored["gaps"]["maps"]
    assert maps["label"] == "maps" and maps["hits"] == 0 and maps["seen"] == [] and maps["objectives"] == []
    for field in ("first_seen", "last_seen", "dropped", "uncertain"):
        assert field not in maps, field
    # With no time of its own at all it is not known to be stale, so it is not forgotten either.
    build = stored["builds"]["find-web-search"]
    assert build["gaps"] == [], "the gap does not name it back: no link"
    for field in ("objective_id", "proposed_at", "filed_at", "built_at", "merged_at", "live_at", "progress", "candidate_sha"):
        assert field not in build, field
    assert stored["misjudged"] == {
        "best_sellers": {"count": 0, "first_seen": None, "last_seen": None},
        "comparison": {"count": 0, "first_seen": None, "last_seen": None},
        "other": {"count": 0, "first_seen": "2026-09-26T21:30:20+00:00", "last_seen": None},
    }

    # The report after the rewrite says what the report before it said, and neither raised.
    after = ledger.report()
    assert after == first
    assert [(g["key"], g["hits"], g["stage"]) for g in after["gaps"]] == [("web search", 0, "open"), ("maps", 0, "open")] \
        or [(g["key"], g["hits"], g["stage"]) for g in after["gaps"]] == [("maps", 0, "open"), ("web search", 0, "open")]
    assert gaps_module.GapLedger(path).repair() is None, "idempotent"

    # And a blocker whose own time cannot be put in UTC is still counted, at the time it was noticed.
    ledger.note_blocker("obj_00000002", "No web search", "web search", at="0001-01-01T00:00:00+01:00")
    assert "gap record not updated" not in caplog.text
    web = json.loads(path.read_text(encoding="utf-8"))["gaps"]["web search"]
    assert web["hits"] == 1 and len(web["seen"]) == 2 and all(t > "2026-01-01" for t in web["seen"])


def test_a_count_is_ascii_digits_or_a_whole_number_and_nothing_else():
    count = gaps_module._count
    for value in ("²", "٣", "１２", "1 ", " 1", "+1", "-1", "1.0", "0x10", "", "123456789", True, False, None, 1.0,
                  [1], {"n": 1}, "1\n"):
        assert count(value) == 0, repr(value)
    assert count("12") == 12 and count("00000007") == 7 and count("99999999") == gaps_module._MAX_COUNT
    assert count(5) == 5 and count(-5) == 0 and count(10**30) == gaps_module._MAX_COUNT
    for value in ("0001-01-01T00:00:00+01:00", "9999-12-31T23:59:59-01:00", "2026-02-30T00:00:00", [], {}, 7, "x" * 41):
        assert gaps_module._strict_iso(value) is None, repr(value)
    assert gaps_module._strict_iso("0001-01-01T00:00:00-01:00") == "0001-01-01T01:00:00+00:00"


def test_json_nested_deeper_than_the_parser_goes_is_unreadable_not_a_raise(tmp_path, monkeypatch):
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)
    deep = "[" * 200_000 + "]" * 200_000
    raw = ('{"version": 1, "gaps": {"web search": {"hits": ' + deep + '}}, "builds": {}, "misjudged": {}}').encode()
    path.write_bytes(raw)
    assert gaps_module.GapLedger(path).report()["gaps"] == []
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    ledger = gaps_module.install(path)
    (kept,) = path.parent.glob("gaps.json.*.unreadable")
    assert kept.read_bytes() == raw and ledger.report()["gaps"] == []


def _row(report: dict, key: str) -> dict:
    return next(g for g in report["gaps"] if g["key"] == key)


def test_the_first_live_fix_is_kept_when_two_merged_gaps_hold_twenty_one_live_builds(tmp_path, monkeypatch):
    """Round 8, F-07-LINKS: _keep_requests kept the last twenty of equally ranked live builds, so
    with twenty-one the first to go live could be the one let go; the count after the fix then
    started at a later fix, and was called exact. Two legacy keys that clean to one, each with
    live builds, and the earliest fix placed where "the last twenty" would drop it."""
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)

    def at(hour: int, minute: int = 0) -> str:
        return f"2026-09-20T{hour:02d}:{minute:02d}:00+00:00"

    builds, sides = {}, (("Web  Search", range(0, 11)), ("web search", range(11, 21)))
    gaps = {}
    for key, numbers in sides:
        requests = [f"live-fix-{n}" for n in numbers]
        for n in numbers:
            # live-fix-0 went live first, at 01:00; every other at 10:00 or later.
            live = at(1) if n == 0 else at(10, n)
            builds[f"live-fix-{n}"] = {"objective_id": "obj_00000001", "gaps": [key], "proposed_at": at(0),
                                       "merged_at": live, "live_at": live}
        gaps[key] = {"label": "No web search", "hits": 3, "sources": {"blocker": 3}, "objectives": [], "requests": requests,
                     # Three hits between the first fix and the others, none after them.
                     "seen": [at(2), at(3), at(4)] if key == "web search" else [], "first_seen": at(2), "last_seen": at(4)}
    path.write_text(json.dumps({"version": 1, "gaps": gaps, "builds": builds, "misjudged": {}}))
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    ledger = gaps_module.install(path)
    kept = json.loads(path.read_text())["gaps"]["web search"]
    assert len(kept["requests"]) == gaps_module.MAX_LINKS and "live-fix-0" in kept["requests"], kept["requests"]
    assert kept["dropped"] == {"requests": 1} and "uncertain" not in kept, "a live fix kept: nothing let go matters"
    row = ledger.report()["gaps"][0]
    assert row["stage"] == "live" and row["stage_exact"] is True
    assert row["hits_after_fix"] == 3 and row["hits_after_fix_exact"] is True, "counted from the first fix, 01:00"
    assert row["not_kept"] == {"requests": 1} and row["uncertain"] == []
    assert gaps_module.GapLedger(path).repair() is None, "idempotent"


def test_links_let_go_with_no_live_fix_kept_leave_the_stage_uncertain(tmp_path, monkeypatch):
    """Round 8, F-07-LINKS: with no live build among those kept, one let go could go live later
    without the gap seeing it."""
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)
    builds = {f"find-web-{n}": {"objective_id": "obj_00000001", "gaps": ["web search"],
                                "proposed_at": "2026-09-20T00:00:00+00:00"} for n in range(25)}
    path.write_text(json.dumps({"version": 1, "misjudged": {}, "builds": builds, "gaps": {"web search": {
        "label": "No web search", "hits": 1, "sources": {"blocker": 1}, "objectives": [], "requests": list(builds),
        "seen": ["2026-09-21T00:00:00+00:00"]}}}))
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    row = gaps_module.install(path).report()["gaps"][0]
    assert row["stage"] == "proposed" and row["stage_exact"] is False
    assert row["hits_after_fix"] is None and row["hits_after_fix_exact"] is False
    assert row["not_kept"] == {"requests": 5} and row["uncertain"] == ["links"]


def test_every_list_past_the_read_limit_is_counted_and_makes_what_it_could_change_uncertain(tmp_path, monkeypatch):
    """Round 8, F-07-LINKS: requests past _MAX_READ, seen times past it and objectives past it
    were let go without a count; a fix among the requests not read, or a hit among the times not
    read, changed the report without it saying so."""
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)
    limit = gaps_module._MAX_READ
    fix = {"objective_id": "obj_00000001", "proposed_at": "2026-09-20T00:00:00+00:00",
           "merged_at": "2026-09-20T01:00:00+00:00", "live_at": "2026-09-20T01:00:00+00:00"}
    builds = {"early-fix": {**fix, "gaps": ["web search"]}, "late-fix": {**fix, "gaps": ["maps"]}}
    seen = [f"2026-09-{1 + n // 1440:02d}T{(n // 60) % 24:02d}:{n % 60:02d}:00+00:00" for n in range(limit + 200)]
    row = {"label": "x", "hits": 5, "sources": {"blocker": 5}, "first_seen": seen[0], "last_seen": seen[-1]}
    path.write_text(json.dumps({"version": 1, "misjudged": {}, "builds": builds, "gaps": {
        # The fix is read; what follows it past the limit is not, and neither are the oldest times.
        "web search": {**row, "requests": ["early-fix", *(f"never-built-{n}" for n in range(limit + 99))],
                       "seen": seen, "objectives": [f"obj_{n:08d}" for n in range(limit + 7)]},
        # The fix is the one entry past the limit: never read.
        "maps": {**row, "requests": [*(f"never-built-{n}" for n in range(limit)), "late-fix"], "seen": seen[-3:],
                 "objectives": []},
    }}))
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    ledger = gaps_module.install(path)
    report = ledger.report()
    web, maps = _row(report, "web search"), _row(report, "maps")

    # Every entry let go is counted: past the limit, not linked back, beyond what is kept.
    assert web["not_kept"] == {"requests": limit + 99, "seen": limit + 200 - 50, "objectives": limit + 7 - gaps_module.MAX_LINKS}
    assert web["uncertain"] == ["history", "links"]
    assert web["stage"] == "live" and web["stage_exact"] is True, "live is as far as it goes"
    assert web["hits_after_fix_exact"] is False, "requests and times went unread"

    assert maps["not_kept"] == {"requests": limit + 1} and maps["uncertain"] == ["links"]
    assert maps["stage"] == "open" and maps["stage_exact"] is False
    assert maps["hits_after_fix"] is None and maps["hits_after_fix_exact"] is False, "a fix may have been let go"
    assert gaps_module.GapLedger(path).repair() is None, "idempotent: what was let go is said once, and kept said"


def test_a_fix_whose_count_after_it_is_a_floor_of_nought_is_not_called_held(tmp_path, monkeypatch):
    """Round 8, F-07-LINKS: the summary counted every live fix reading nought as held, the ones
    whose nought is only a floor included."""
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)
    fix = {"objective_id": "obj_00000001", "gaps": ["web search"], "proposed_at": "2026-09-20T00:00:00+00:00",
           "merged_at": "2026-09-20T01:00:00+00:00", "live_at": "2026-09-20T01:00:00+00:00"}
    path.write_text(json.dumps({"version": 1, "misjudged": {}, "builds": {"early-fix": fix}, "gaps": {"web search": {
        "label": "x", "hits": 2, "sources": {"blocker": 2}, "objectives": [],
        "requests": ["early-fix", *(f"never-built-{n}" for n in range(gaps_module._MAX_READ))],
        "seen": ["2026-09-19T00:00:00+00:00"], "first_seen": "2026-09-19T00:00:00+00:00",
        "last_seen": "2026-09-19T00:00:00+00:00"}}}))
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    report = gaps_module.install(path).report()
    row = report["gaps"][0]
    assert row["stage"] == "live" and row["hits_after_fix"] == 0 and row["hits_after_fix_exact"] is False
    assert report["summary"]["live"] == 1 and report["summary"]["fixes_held"] == 0 and report["summary"]["fixes_recurred"] == 0


def test_a_build_naming_more_than_two_hundred_gap_keys_keeps_the_links_it_can_read(tmp_path, monkeypatch):
    """Round 8, F-07-LINKS: _only_known_build cut a build's gap keys at MAX_GAPS before they were
    cleaned, so a gap whose legacy key came 201st lost the build that fixed it, and nothing said
    so. The keys are read to _MAX_READ now; past that, the gaps it may name are marked."""
    path = tmp_path / "objectives" / "gaps.json"
    path.parent.mkdir(parents=True, mode=0o700)
    limit = gaps_module._MAX_READ
    live = {"objective_id": "obj_00000001", "proposed_at": "2026-09-20T00:00:00+00:00",
            "merged_at": "2026-09-20T01:00:00+00:00", "live_at": "2026-09-20T01:00:00+00:00"}
    # Legacy spellings of one key, 240 of them, then the one that names the gap as it is stored.
    spellings = [("Web" + " " * (n % 7 + 1) + "Search" + "!" * (n // 7)) for n in range(240)]
    many = [f"other gap {n}" for n in range(limit + 5)]
    builds = {"wide-fix": {**live, "gaps": [*spellings, "maps"]},
              "wider-fix": {**live, "gaps": [*many, "carrier tracking"]}}
    row = {"label": "x", "hits": 1, "sources": {"blocker": 1}, "objectives": [], "seen": ["2026-09-21T00:00:00+00:00"],
           "first_seen": "2026-09-21T00:00:00+00:00", "last_seen": "2999-01-01T00:00:00+00:00"}
    path.write_text(json.dumps({"version": 1, "misjudged": {}, "builds": builds, "gaps": {
        "web search": {**row, "requests": ["wide-fix"]}, "maps": {**row, "requests": ["wide-fix"]},
        "carrier tracking": {**row, "requests": ["wider-fix"]}}}))
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    report = gaps_module.install(path).report()
    for key in ("web search", "maps"):
        got = _row(report, key)
        assert got["stage"] == "live" and got["hits_after_fix"] == 1 and got["hits_after_fix_exact"] is True, key
        assert got["not_kept"] == {} and got["uncertain"] == [], key
    carrier = _row(report, "carrier tracking")
    assert carrier["stage"] == "open" and carrier["stage_exact"] is False and carrier["hits_after_fix_exact"] is False
    assert carrier["not_kept"] == {"requests": 1} and carrier["uncertain"] == ["links"]
    assert sorted(json.loads(path.read_text())["builds"]["wide-fix"]["gaps"]) == ["maps", "web search"]
    assert gaps_module.GapLedger(path).repair() is None, "idempotent"


def _second_dir_flush_fails(monkeypatch, *, fail_on: int) -> list[str]:
    """_fsync_dir fails on its `fail_on`th call only; every call is recorded."""
    calls: list[str] = []
    real = gaps_module._fsync_dir

    def flaky(folder):
        calls.append("dir")
        if len(calls) == fail_on:
            raise OSError(5, "I/O error", str(folder))
        return real(folder)

    monkeypatch.setattr(gaps_module, "_fsync_dir", flaky)
    return calls


def test_a_clean_whose_folder_flush_fails_after_the_replace_never_says_the_record_was_left_as_it_was(tmp_path, monkeypatch, caplog):
    """Round 8, F-07-DURABILITY: _save replaced the file and then flushed its folder; when only
    that second flush failed, start-up logged that the record was "left exactly as it was" though
    the clean record had replaced it. That outcome is its own now: written, not confirmed on
    disk, with the original's copy (flushed before the replace) named."""
    from tests.fake_credentials import github_token

    token = github_token("second-fsync")
    path = tmp_path / "objectives" / "gaps.json"
    raw = _legacy_record(path, token)
    calls = _second_dir_flush_fails(monkeypatch, fail_on=2)
    monkeypatch.setattr(gaps_module, "_LEDGER", None)
    ledger = gaps_module.install(path)
    assert calls == ["dir", "dir"], "the copy's folder, then the clean record's"
    (copy,) = path.parent.glob("gaps.json.*.before-clean")
    assert copy.read_bytes() == raw and token not in path.read_text(), "the replace happened"
    assert "left exactly as it was" not in caplog.text and "not cleaned" not in caplog.text
    assert "not confirmed on disk" in caplog.text and copy.name in caplog.text
    assert not list(path.parent.glob(".*.tmp"))
    # The clean record is not cleaned again over itself, and the next change saves normally.
    caplog.clear()
    ledger.note_blocker("obj_00000003", "No web search", "web search")
    assert "not updated" not in caplog.text and "not confirmed" not in caplog.text
    assert len(list(path.parent.glob("gaps.json.*.before-clean"))) == 1
    assert json.loads(path.read_text())["gaps"]["web search"]["hits"] == 2


def test_a_later_save_whose_folder_flush_fails_says_it_was_written_never_that_it_was_not(tmp_path, monkeypatch, caplog):
    path = tmp_path / "objectives" / "gaps.json"
    ledger = gaps_module.GapLedger(path)
    ledger.note_blocker("obj_00000001", "No web search", "web search")   # clean from the start
    calls = _second_dir_flush_fails(monkeypatch, fail_on=1)
    ledger.note_blocker("obj_00000002", "No web search", "web search")
    assert calls == ["dir"]
    assert "gap record not updated" not in caplog.text
    assert "gap record updated, but not confirmed on disk" in caplog.text
    assert json.loads(path.read_text())["gaps"]["web search"]["hits"] == 2, "the update is what the file holds"
    # A failure before the replace is still "not updated", and leaves no half-written file.
    caplog.clear()
    real_replace = gaps_module.os.replace
    monkeypatch.setattr(gaps_module.os, "replace", lambda a, b: (_ for _ in ()).throw(OSError(28, "No space left")))
    ledger.note_blocker("obj_00000003", "No web search", "web search")
    assert "gap record not updated" in caplog.text and "not confirmed" not in caplog.text
    assert json.loads(path.read_text())["gaps"]["web search"]["hits"] == 2
    assert not list(path.parent.glob(".*.tmp"))
    monkeypatch.setattr(gaps_module.os, "replace", real_replace)


def test_a_change_on_a_record_cleaned_but_not_confirmed_goes_on_and_says_both(tmp_path, monkeypatch, caplog):
    """The first change on a record not yet cleaned cleans it first; when that clean's second
    flush fails, the clean is said as written and the change is still made."""
    from tests.fake_credentials import github_token

    path = tmp_path / "objectives" / "gaps.json"
    _legacy_record(path, github_token("change-second-fsync"))
    ledger = gaps_module.GapLedger(path)
    _second_dir_flush_fails(monkeypatch, fail_on=2)
    ledger.note_blocker("obj_00000003", "No web search", "web search")
    assert "cleaned before this change and written, but not confirmed on disk" in caplog.text
    assert "gap record not updated" not in caplog.text
    assert json.loads(path.read_text())["gaps"]["web search"]["hits"] == 2
