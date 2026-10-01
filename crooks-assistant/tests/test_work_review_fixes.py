"""The review of the team build (PR #73, 1 October), its findings on the work list (app/work), each
proven fixed: a read of another day writes nothing, a job CLIVE's assistant made says so, the work
tools are AMBER and say their text is untrusted, a change is recorded as whoever made it and never
as the owner by default, an undo is recorded, a change reads again only the source it is about,
and anyone may flag a job for the owner.

Every service is a stand-in, as in tests/test_work.py. Nothing reaches the network.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.people import access, staff
from app.people.store import people
from app.tools import registry
from app.tools.gate import Tier, classify
from app.tools.registry import ToolError
from app.work import found as live
from app.work import hooks
from app.work import tools as work_tools
from app.work.store import ARCHIVE_AFTER_DAYS, work
from tests.test_actions_routes import PROXIED, client  # noqa: F401 - `client` is a fixture
from tests.test_team import team  # noqa: F401 - a fixture
from tests.test_work import EMAIL, ORDER_1, finding, let_in, made, owner
from tests.test_work import staff as as_staff

WEB = Path(__file__).resolve().parent.parent / "web"


@pytest.fixture(autouse=True)
def stores(tmp_path):
    work.configure(tmp_path / "work")
    people.configure(tmp_path / "people.json")
    access.configure(state_dir=tmp_path / "secret")
    live.reset()
    yield tmp_path
    work.configure(None)
    people.configure(None)
    access.configure(state_dir=None)
    live.reset()
    work_tools.bind(None)


def kept_files(folder: Path) -> dict[str, bytes]:
    return {str(p.relative_to(folder)): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


def today() -> str:
    return datetime.now(UTC).date().isoformat()


# ------------------------------------------------------------------ (1) another day is read-only

async def test_a_past_or_future_day_makes_and_archives_nothing_and_today_makes_its_routines_once(stores, monkeypatch):
    finding(monkeypatch)
    work_tools.bind(SimpleNamespace())
    routine = work.add_routine(title="Tidy the desks", cadence="daily", by="owner")
    packed = work.claim_found(ref=ORDER_1, kind="pack_order", title="Pack #1001", details="", who="mia")
    work.packed(packed.item_id, who="mia")
    work.done(packed.item_id, who="mia")
    path = stores / "work" / "items" / f"{packed.item_id}.json"
    data = json.loads(path.read_text())
    data["done_at"] = today() + "T09:00:00+00:00"
    path.write_text(json.dumps(data))
    folder = stores / "work"
    before = kept_files(folder)
    past = (date.fromisoformat(today()) - timedelta(days=30)).isoformat()
    future = (date.fromisoformat(today()) + timedelta(days=ARCHIVE_AFTER_DAYS + 30)).isoformat()
    with owner():
        for day in (past, "2026-09-01", future):
            board = await work_tools.work_list(day=day)
            assert board["day"] == day
            assert kept_files(folder) == before, day                       # nothing made, nothing put away
        assert work.get(packed.item_id) is not None and not any(i.routine_id for i in work.items())
        await work_tools.work_list()
        await work_tools.work_list()
    todays = [i for i in work.items() if i.routine_id == routine.routine_id]
    assert [(i.due, i.source) for i in todays] == [(today(), "routine")]       # once, however often asked
    assert work.get(packed.item_id) is not None                                 # finished today: still in hand


async def test_another_day_shows_the_kept_records_for_it_not_what_is_found_today(stores, monkeypatch):
    finding(monkeypatch, orders=[{"ref": ORDER_1, "kind": "pack_order", "title": "Pack #1001", "details": "",
                                   "since": today() + "T08:00:00Z"}])
    work_tools.bind(SimpleNamespace())
    earlier = work.assign(title="Restock the shelves", by="owner")
    path = stores / "work" / "items" / f"{earlier.item_id}.json"
    data = json.loads(path.read_text())
    data["created_at"] = "2026-08-20T09:00:00+00:00"
    path.write_text(json.dumps(data))
    work.assign(title="Count the hoodies", by="owner")                       # made today
    past = "2026-09-01" if today() > "2026-09-01" else "2000-01-01"
    future = (date.fromisoformat(today()) + timedelta(days=30)).isoformat()
    with owner():
        then = await work_tools.work_list(day=past)
        ahead = await work_tools.work_list(day=future)
        now = await work_tools.work_list()
    assert then["found"] == ahead["found"] == [] and then["sources"] == ahead["sources"] == {}
    assert [i["title"] for i in then["up_for_grabs"]] == (["Restock the shelves"] if past == "2026-09-01" else [])
    assert sorted(i["title"] for i in ahead["up_for_grabs"]) == ["Count the hoodies", "Restock the shelves"]
    assert [r["ref"] for r in now["found"]] == [ORDER_1] and now["sources"]["orders"]["count"] == 1


@pytest.mark.parametrize("day", ["1 September", "2026-9-1", "20260901", "2026-02-30", "tomorrow"])
async def test_a_day_that_is_not_a_date_is_refused_in_words(monkeypatch, day):
    finding(monkeypatch)
    work_tools.bind(SimpleNamespace())
    with owner():
        for record in (False, True):
            with pytest.raises(ToolError, match=r"say the day as a date, like 2026-10-01"):
                await work_tools.work_list(day=day, record=record)
    assert work.items() == []


# ------------------------------------------------------------------ (2) made through CLIVE

async def test_a_job_or_routine_clives_assistant_made_says_so(monkeypatch):
    finding(monkeypatch)
    work_tools.bind(SimpleNamespace())
    people.note({"name": "Mia", "kind": "staff"})
    with owner():
        job = (await work_tools.work_note(action="assign", title="Restock the shelves", to="mia"))["job"]
        routine = await work_tools.work_note(action="routine", title="Tidy the desks", cadence="daily")
    assert job["created_via"] == "clive" and job["assignee"] == "mia" and job["created_by"] == "owner"
    [line] = work.history(ref=job["item_id"])
    assert line["what"] == "created" and line["via"] == "clive"
    assert routine["routine"]["created_via"] == "clive" and [i["created_via"] for i in routine["today"]] == ["clive"]
    assert work.history()[1]["what"] == "routine_set" and work.history()[1]["via"] == "clive"


def test_the_today_page_shows_via_clive_on_such_a_job():
    script = (WEB / "today.js").read_text(encoding="utf-8")
    assert "VIA_CLIVE = 'clive'" in script
    assert "if (job.created_via === VIA_CLIVE) bits.push('via CLIVE');" in script
    assert "entry.via === VIA_CLIVE ? ' · via CLIVE'" in script


async def test_a_job_the_owner_made_with_his_own_taps_is_not_marked(team):  # noqa: F811
    handed = await team.post("/today/assign", json={"title": "Count the hoodies"}, headers=PROXIED)
    assert handed.status_code == 200 and handed.json()["job"]["created_via"] == ""
    [line] = work.history(ref=handed.json()["job"]["item_id"])
    assert line["what"] == "created" and "via" not in line
    routine = await team.post("/today/routine", json={"title": "Tidy", "cadence": "daily"}, headers=PROXIED)
    assert routine.status_code == 200 and routine.json()["routine"]["created_via"] == ""
    assert all(i.created_via == "" for i in work.items())


# ------------------------------------------------------------------ (3) AMBER, and untrusted

async def test_work_note_is_amber_and_its_results_and_the_records_say_their_text_is_untrusted(monkeypatch):
    finding(monkeypatch, orders=[{"ref": ORDER_1, "kind": "pack_order", "title": "Pack #1001: 2 items for Jane",
                                  "details": "", "since": "2026-10-01T08:00:00Z"}])
    work_tools.bind(SimpleNamespace())
    assert registry.get("work_note").tier is Tier.AMBER and registry.get("work_list").tier is Tier.AMBER
    assert classify("work_note", {"action": "claim"}).tier is Tier.AMBER
    with as_staff("mia"):
        claimed = await work_tools.work_note(action="claim", ref=ORDER_1)
        assert claimed["note"] == work_tools.UNTRUSTED and "Jane" in claimed["job"]["title"]
        assert (await work_tools.work_list(record=True))["note"] == work_tools.UNTRUSTED
    with owner():
        routine = await work_tools.work_note(action="routine", title="Tidy", cadence="daily")
        assert routine["note"] == work_tools.UNTRUSTED
        assert (await work_tools.work_list(record=True, day=today()))["note"] == work_tools.UNTRUSTED


# ------------------------------------------------------------------ (4) who did it

def test_a_change_by_a_member_suspended_mid_commit_is_theirs_never_the_owners():
    let_in("mia")
    access.suspend("mia", by="owner")                                # while the change was still committing
    with as_staff("mia"):
        hooks.after_commit(made("gmail_draft_reply", entity=EMAIL.removeprefix("email:")))
    assert work.history()[0]["who"] == "mia"
    hooks.after_commit(made("gmail_draft_reply", entity=EMAIL.removeprefix("email:")))   # no authority to read
    assert work.history()[0]["who"] == "mia@example.com"
    with owner():
        hooks.after_commit(made("gmail_draft_reply", entity=EMAIL.removeprefix("email:"), caller="owner@example.com"))
    assert work.history()[0]["who"] == "owner"
    assert [e["who"] for e in work.history()].count("owner") == 1


def test_grants_unreadable_still_record_the_login(monkeypatch):
    def broken(login):
        raise OSError("access.json is being rewritten")

    monkeypatch.setattr(access, "person_for_login", broken)
    hooks.after_commit(made())
    assert work.history()[0]["who"] == "mia@example.com"


# ------------------------------------------------------------------ (5) undo

def test_the_undo_operations_are_the_engines_names_for_the_five():
    import inspect

    from app.actions.engine import ActionEngine

    assert 'operation=f"{write.operation}_undo"' in inspect.getsource(ActionEngine.stage_undo)
    assert set(hooks.EFFECTS) == staff.OPERATIONS
    assert {f"{o}{hooks.UNDO}" for o in hooks.EFFECTS} == staff.OPERATIONS_WITH_UNDO - staff.OPERATIONS


@pytest.mark.parametrize("operation", sorted(staff.OPERATIONS))
@pytest.mark.parametrize("status", ["claimed", "done"])
def test_an_undo_is_recorded_and_never_closes_or_reopens_a_job(operation, status):
    let_in("mia")
    what, kind, _ = hooks.EFFECTS[operation]
    ref = {"order": ORDER_1, "email": EMAIL}.get(kind, "")
    entity = ref.split(":", 1)[1] if ref else "gid://shopify/ProductVariant/7"
    about = ref or ORDER_1                                           # a stock change is about no job: any will do
    job = work.claim_found(ref=about, kind="reply_email" if about == EMAIL else "pack_order", title="A job", details="",
                           who="mia")
    if status == "done":
        work.done(job.item_id, who="mia")
    with as_staff("mia"):
        hooks.after_commit(made(f"{operation}_undo", entity=entity))
    assert work.get(job.item_id).status == status
    line = work.history()[0]
    assert (line["who"], line["what"], line["ref"]) == ("mia", f"{what}_undone", ref)


# ------------------------------------------------------------------ (6) only the source it is about

@pytest.mark.parametrize("operation, read_again", [
    ("fulfillment_create", ["orders"]), ("fulfillment_tracking_set", ["orders"]),
    ("gmail_send_reply", ["emails"]), ("gmail_draft_reply", ["emails"]), ("inventory_set", []),
    ("fulfillment_create_undo", ["orders"]), ("inventory_set_undo", []),
])
async def test_a_change_reads_again_only_the_source_it_is_about(monkeypatch, operation, read_again):
    asked = []

    def source(name):
        async def read(runtime):
            asked.append(name)
            return {"available": True, "items": []}
        return read

    monkeypatch.setattr(live, "SOURCES", {name: source(name) for name in ("orders", "emails", "instagram")})
    await live.found(None)
    asked.clear()
    entity = {"order": ORDER_1, "email": EMAIL}.get(hooks.EFFECTS[operation.removesuffix("_undo")][1], "x:v")
    hooks.after_commit(made(operation, entity=entity.split(":", 1)[1]))
    await live.found(None)
    assert asked == read_again


# ------------------------------------------------------------------ (7) a flag for the owner

async def test_anyone_may_flag_a_job_for_the_owner(monkeypatch):
    finding(monkeypatch)
    work_tools.bind(SimpleNamespace())
    assert "flag" not in staff.OWNER_WORK_ACTIONS
    with as_staff("mia"):
        out = await work_tools.work_note(action="flag", title="Refund #1001", details="the hoodie came torn", ref=ORDER_1)
        with pytest.raises(ToolError, match="say what the owner needs to do"):
            await work_tools.work_note(action="flag", title="  ")
    job = out["job"]
    assert (job["status"], job["assignee"], job["created_by"], job["ref"]) == ("open", "owner", "mia", ORDER_1)
    assert job["details"] == "the hoodie came torn" and job["title"] == "Refund #1001" and out["note"] == work_tools.UNTRUSTED
    [line] = work.history(ref=job["item_id"])
    assert (line["who"], line["what"], line["assignee"]) == ("mia", "flagged", "owner")
    with owner():
        mine = await work_tools.work_list()
        assert [i["item_id"] for i in mine["mine"]] == [job["item_id"]]
        own = (await work_tools.work_note(action="flag", title="Call the printer"))["job"]
    assert own["assignee"] == "owner" and own["created_by"] == "owner"
    with as_staff("kit"):
        assert job["item_id"] not in json.dumps(await work_tools.work_list())   # the owner's, not the team's
    assert "flag" in registry.get("work_note").input_schema["properties"]["action"]["enum"]
