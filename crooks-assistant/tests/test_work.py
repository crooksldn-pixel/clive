"""The work list (app/work): jobs and their ladder, routines, what CLIVE finds by itself, how a
person's day is drawn from them, the change that closes a job, and the tools the model reaches it by.

Every service is a stand-in: Shopify's answers are a fake GraphQL client, Gmail's and Instagram's
the functions the sources call, replaced. Nothing reaches the network.
"""

from __future__ import annotations

import asyncio
import json
import stat
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.actions.models import ActionStatus
from app.people import access
from app.people.store import people
from app.tools import authority
from app.tools.registry import ToolError
from app.work import found as live
from app.work import hooks, view
from app.work import tools as work_tools
from app.work.store import ARCHIVE_AFTER_DAYS as ARCHIVE_DAYS
from app.work.store import MAX_COUNTS, WorkError, WorkStore, work
from tests.fake_credentials import bearer_token

ORDER_1 = "order:gid://shopify/Order/1001"
ORDER_2 = "order:gid://shopify/Order/1002"
EMAIL = "email:18c2a7f0b1d2e3f4"


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


def owner():
    return authority.acting_as(authority.for_owner("owner@example.com"))


def staff(person_id: str):
    return authority.acting_as(authority.for_staff(person_id, f"{person_id}@example.com"))


def order_row(ref=ORDER_1, number="#1001"):
    return {"ref": ref, "kind": "pack_order", "title": f"Pack {number}: 2 items for Jane", "details": "placed 2 hours ago",
            "lines": [{"item": "Hoodie (M)", "sku": "HD-M", "quantity": 2}], "since": "2026-10-01T08:00:00Z"}


def email_row(ref=EMAIL, since=None):
    return {"ref": ref, "kind": "reply_email", "title": "Reply to Sam: where is my order?", "details": "waiting 3 hours",
            "snippet": "Hi, it has been a week", "since": since or 1_759_300_000_000}


def finding(monkeypatch, orders=(), emails=(), instagram=()):
    """What CLIVE finds today, as the sources would answer."""
    answers = {"orders": {"available": True, "items": list(orders)},
               "emails": {"available": True, "items": list(emails)},
               "instagram": {"available": False, "reason": "Instagram is not connected", "items": list(instagram)}}

    async def found(runtime, *, fresh=False):
        return answers

    monkeypatch.setattr(live, "found", found)
    return answers


# ------------------------------------------------------------------ the ladder

def test_a_job_goes_open_claimed_done_and_the_record_says_who(stores):
    job = work.assign(title="Restock the shelves", details="hoodies first", by="owner")
    assert job.status == "open" and job.item_id.startswith("w_")
    work.claim(job.item_id, who="mia")
    with pytest.raises(WorkError, match="claimed by mia"):
        work.claim(job.item_id, who="kit")
    with pytest.raises(WorkError, match="only an order is packed"):
        work.packed(job.item_id, who="mia")
    done = work.done(job.item_id, who="mia", note="  all  done  ")
    assert done.status == "done" and done.done_by == "mia" and done.evidence["note"] == "all done"
    assert [e["what"] for e in done.events] == ["created", "claimed", "done"]
    assert [(e["who"], e["what"]) for e in work.history(ref=job.item_id)] == [("mia", "done"), ("mia", "claimed"), ("owner", "created")]
    for path in [stores / "work" / "record.jsonl", *(stores / "work" / "items").glob("*.json")]:
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with pytest.raises(WorkError, match="already done"):
        work.done(job.item_id, who="mia")


def test_a_job_for_someone_is_theirs_and_the_owner_may_take_any():
    job = work.assign(title="Upload the Vinted sales", assignee="mia", by="owner")
    with pytest.raises(WorkError, match="someone else's"):
        work.claim(job.item_id, who="kit")
    assert work.claim(job.item_id, who="owner", owner=True).claimed_by == "owner"


def test_only_who_holds_a_job_may_give_it_back_or_finish_it():
    job = work.assign(title="Tidy the desks", by="owner")
    with pytest.raises(WorkError, match="claim it first"):
        work.done(job.item_id, who="mia")
    work.claim(job.item_id, who="mia")
    for step in (lambda: work.release(job.item_id, who="kit"), lambda: work.done(job.item_id, who="kit")):
        with pytest.raises(WorkError, match="mia has that job"):
            step()
    assert work.release(job.item_id, who="owner", owner=True).status == "open"
    assert work.done(job.item_id, who="owner", owner=True).done_by == "owner"     # the owner may close an open job


def test_two_people_claiming_one_found_thing_the_second_is_told_who_has_it():
    first = work.claim_found(ref=ORDER_1, kind="pack_order", title="Pack #1001", details="", who="mia")
    with pytest.raises(WorkError, match="mia has already claimed that"):
        work.claim_found(ref=ORDER_1, kind="pack_order", title="Pack #1001", details="", who="kit")
    assert work.claim_found(ref=ORDER_1, kind="pack_order", title="Pack #1001", details="", who="mia").item_id == first.item_id
    work.release(first.item_id, who="mia")
    again = work.claim_found(ref=ORDER_1, kind="pack_order", title="Pack #1001", details="", who="kit")
    assert again.item_id == first.item_id and again.claimed_by == "kit"              # one job, its whole story
    assert len(work.by_ref(ORDER_1)) == 1


def test_packing_is_recorded_on_the_order_with_who_and_when():
    job = work.claim_found(ref=ORDER_1, kind="pack_order", title="Pack #1001", details="", who="mia")
    packed = work.packed(job.item_id, who="mia")
    assert packed.status == "claimed" and packed.evidence["packed"] and packed.evidence["packed_by"] == "mia"
    assert work.history(who="mia", ref=ORDER_1)[0]["what"] == "packed"


def test_a_stock_count_needs_its_counts_and_keeps_them():
    job = work.assign(title="Count the hoodies", kind="stock_count", assignee="mia", by="owner")
    work.claim(job.item_id, who="mia")
    with pytest.raises(WorkError, match="enter the counts first"):
        work.done(job.item_id, who="mia")
    with pytest.raises(WorkError, match="whole number"):
        work.counted(job.item_id, [{"item": "Hoodie M", "counted": "lots"}], who="mia")
    with pytest.raises(WorkError, match="out of range"):
        work.counted(job.item_id, [{"item": "Hoodie M", "counted": -1}], who="mia")
    with pytest.raises(WorkError, match="at least one"):
        work.counted(job.item_id, ["not a row"], who="mia")
    with pytest.raises(WorkError, match=f"at most {MAX_COUNTS}"):
        work.counted(job.item_id, [{"item": f"x{i}", "counted": 1} for i in range(MAX_COUNTS + 1)], who="mia")
    counted = work.counted(job.item_id, [{"item": "Hoodie M", "sku": "HD-M", "counted": "12"},
                                         {"sku": "HD-L", "counted": 0}], who="mia")
    assert counted.evidence["counts"] == [{"item": "Hoodie M", "sku": "HD-M", "variant_id": "", "counted": 12},
                                          {"item": "HD-L", "sku": "HD-L", "variant_id": "", "counted": 0}]
    assert work.done(job.item_id, who="mia").evidence["counted_by"] == "mia"
    other = work.assign(title="Count the tees", kind="stock_count", by="owner")
    tidy = work.claim(work.assign(title="Tidy", by="owner").item_id, who="owner", owner=True)
    with pytest.raises(WorkError, match="belong to a stock count"):
        work.counted(tidy.item_id, [{"item": "x", "counted": 1}], who="owner", owner=True)
    assert work.done(other.item_id, who="owner", owner=True).status == "done"      # the owner may close one uncounted


def test_routines_make_one_job_on_each_day_they_are_due():
    daily = work.add_routine(title="Tidy the desks", cadence="daily", by="owner")
    monday = work.add_routine(title="Upload Vinted labels", cadence="Mondays", assignee="mia", by="owner")
    assert monday.cadence == "mon"
    a_monday = date(2026, 10, 5).isoformat()
    made = work.materialise(a_monday)
    assert sorted(i.title for i in made) == ["Tidy the desks", "Upload Vinted labels"]
    assert work.materialise(a_monday) == []                                         # once a day, however often asked
    tuesday = (date(2026, 10, 5) + timedelta(days=1)).isoformat()
    assert [i.title for i in work.materialise(tuesday)] == ["Tidy the desks"]
    assert work.stop_routine(daily.routine_id, by="owner") and not work.stop_routine(daily.routine_id, by="owner")
    assert work.materialise((date(2026, 10, 5) + timedelta(days=2)).isoformat()) == []
    made_for_mia = [i for i in work.items() if i.routine_id == monday.routine_id]
    assert made_for_mia[0].assignee == "mia" and made_for_mia[0].due == a_monday and made_for_mia[0].source == "routine"
    with pytest.raises(WorkError, match="daily, weekdays"):
        work.add_routine(title="Whenever", cadence="fortnightly", by="owner")


@pytest.mark.parametrize("fields, says", [
    ({"kind": "rocket"}, "not a kind of job"),
    ({"due": "tomorrow"}, "YYYY-MM-DD"),
])
def test_what_cannot_be_kept_is_refused_in_words(fields, says):
    with pytest.raises(WorkError, match=says):
        work.assign(title="X", by="owner", **fields)


def test_a_found_reference_must_be_one_clive_knows():
    with pytest.raises(WorkError, match="malformed"):
        work.claim_found(ref="file:/etc/passwd", kind="job", title="x", details="", who="mia")


def test_a_job_id_that_is_not_one_is_no_such_job_and_a_broken_file_is_passed_over(stores):
    for bad in ("../../etc/passwd", "w_", "", "W_ABC_DEF"):
        with pytest.raises(WorkError, match="no such job"):
            work.claim(bad, who="mia")
    job = work.assign(title="Keep me", by="owner")
    (stores / "work" / "items" / "w_260101_deadbeef.json").write_text("{broken")
    assert [i.item_id for i in work.items()] == [job.item_id]


def test_the_record_answers_who_did_what_by_person_thing_and_day():
    a = work.claim_found(ref=ORDER_1, kind="pack_order", title="Pack #1001", details="", who="mia")
    work.packed(a.item_id, who="mia")
    work.claim_found(ref=ORDER_2, kind="pack_order", title="Pack #1002", details="", who="kit")
    assert {e["what"] for e in work.history(who="mia")} == {"created", "claimed", "packed"}
    assert {e["who"] for e in work.history(ref=ORDER_2)} == {"kit"}
    today = datetime.now(UTC).date().isoformat()
    assert len(work.history(day=today)) == 5 and work.history(day="2001-01-01") == []
    assert len(work.history(limit=2)) == 2


def test_the_record_finds_an_order_by_its_number_as_well_as_its_reference():
    job = work.claim_found(ref=ORDER_1, kind="pack_order", title="Pack #1001: 2 items for Jane", details="", who="mia")
    work.packed(job.item_id, who="mia")
    work.record({"who": "mia", "what": "fulfilled", "ref": ORDER_1, "detail": "CROOKS-1001"})
    work.claim_found(ref=ORDER_2, kind="pack_order", title="Pack #10011: 1 item for Sam", details="", who="kit")
    for asked in ("#1001", "1001", ORDER_1):
        assert {e["what"] for e in work.history(ref=asked)} == {"created", "claimed", "packed", "fulfilled"}, asked
    assert work.history(ref="#100") == [] and work.history(ref="#99999") == []


def test_finished_jobs_are_put_away_after_two_weeks_and_the_record_keeps_them(stores):
    from app.work import store as store_module

    old = work.assign(title="Old count", by="owner")
    work.done(old.item_id, who="owner", owner=True)
    recent = work.assign(title="Recent tidy", by="owner")
    work.done(recent.item_id, who="owner", owner=True)
    open_one = work.assign(title="Still to do", by="owner")
    for item, ended in ((old, "2026-09-01T10:00:00+00:00"), (recent, "2026-09-25T10:00:00+00:00")):
        data = json.loads((stores / "work" / "items" / f"{item.item_id}.json").read_text())
        data["done_at"] = ended
        (stores / "work" / "items" / f"{item.item_id}.json").write_text(json.dumps(data))
    assert work.archive("2026-10-01") == 1
    assert {i.item_id for i in work.items()} == {recent.item_id, open_one.item_id}
    assert (stores / "work" / "items" / "archive" / "2026-09" / f"{old.item_id}.json").exists()
    assert work.history(ref=old.item_id)[0]["what"] == "done"                     # its story is still told
    assert work.archive("2026-10-01") == 0
    work.configure(stores / "work")
    work.materialise((date.fromisoformat("2026-09-25") + timedelta(days=ARCHIVE_DAYS + 1)).isoformat())
    assert {i.item_id for i in work.items()} == {open_one.item_id}              # put away on a new day's first read
    assert store_module.ARCHIVE_AFTER_DAYS == ARCHIVE_DAYS


def test_the_screen_reads_the_records_latest_lines_and_a_question_reads_it_all(stores, monkeypatch):
    from app.work import store as store_module

    work.record({"who": "mia", "what": "packed", "ref": ORDER_1, "detail": "Pack #1001"})
    for n in range(40):
        work.record({"who": "kit", "what": "claimed", "detail": f"filler {n:03d} " + "x" * 60})
    monkeypatch.setattr(store_module, "TAIL_BYTES", 600)
    assert work.history(who="mia") == []                                          # beyond the screen's reach
    assert [e["what"] for e in work.history(who="mia", everything=True)] == ["packed"]
    assert len(work.history(who="kit", limit=100)) < 40 and len(work.history(who="kit", limit=100, everything=True)) == 40
    assert all(e["detail"].startswith("filler") for e in work.history(who="kit"))   # never half a line


def test_an_unconfigured_list_says_so():
    with pytest.raises(WorkError, match="not set up"):
        WorkStore(None).items()


# ------------------------------------------------------------------ the day as each person sees it

async def test_a_member_of_the_team_sees_theirs_what_is_up_for_grabs_and_not_another_persons(monkeypatch):
    finding(monkeypatch, orders=[order_row(), order_row(ORDER_2, "#1002")], emails=[email_row()])
    work.claim_found(ref=ORDER_1, kind="pack_order", title="Pack #1001", details="", who="mia")
    anyone = work.assign(title="Restock the shelves", by="owner")
    for_kit = work.assign(title="Kit's Vinted labels", assignee="kit", by="owner")
    later = work.assign(title="Next week", due=(datetime.now(UTC).date() + timedelta(days=7)).isoformat(), by="owner")

    mine = await view.today_for(None, who="mia", owner=False)
    assert [r["ref"] for r in mine["mine_found"]] == [ORDER_1] and mine["mine_found"][0]["lines"]
    assert mine["mine"] == []                                       # shown once: as the order, with its lines
    assert [r["ref"] for r in mine["found"]] == [ORDER_2, EMAIL]
    assert [i["item_id"] for i in mine["up_for_grabs"]] == [anyone.item_id]
    assert for_kit.item_id not in json.dumps(mine) and later.item_id not in json.dumps(mine)

    board = await view.today_for(None, who="owner", owner=True)
    assert [(r["ref"], r["claimed_by"]) for r in board["in_hand"]] == [(ORDER_1, "mia")]
    assert [i["item_id"] for i in board["team"]] == [for_kit.item_id]
    assert board["sources"]["instagram"] == {"available": False, "reason": "Instagram is not connected", "count": 0}


async def test_a_packed_order_waits_to_be_fulfilled_in_view_of_the_whole_team(monkeypatch):
    finding(monkeypatch, orders=[order_row()])
    job = work.claim_found(ref=ORDER_1, kind="pack_order", title="Pack #1001", details="", who="mia")
    work.packed(job.item_id, who="mia")
    work.done(job.item_id, who="mia")
    kit = await view.today_for(None, who="kit", owner=False)
    assert [(r["status"], r["done_by"]) for r in kit["in_hand"]] == [("packed", "mia")]
    assert kit["found"] == []
    mia = await view.today_for(None, who="mia", owner=False)
    assert [i["item_id"] for i in mia["done"]] == [job.item_id]


async def test_a_finished_reply_stays_finished_until_the_customer_writes_again(monkeypatch):
    answers = finding(monkeypatch, emails=[email_row()])
    job = work.claim_found(ref=EMAIL, kind="reply_email", title="Reply to Sam", details="", who="mia")
    work.done(job.item_id, who="mia", note="answered by phone")
    assert (await view.today_for(None, who="kit", owner=False))["found"] == []
    later = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp() * 1000)
    answers["emails"]["items"] = [email_row(since=later)]
    assert [r["status"] for r in (await view.today_for(None, who="kit", owner=False))["found"]] == ["open"]


async def test_a_claimed_job_that_is_no_longer_found_stays_on_the_list_to_finish(monkeypatch):
    answers = finding(monkeypatch, emails=[email_row()])
    job = work.claim_found(ref=EMAIL, kind="reply_email", title="Reply to Sam", details="", who="mia")
    answers["emails"]["items"] = []                                 # answered from Gmail itself, say
    mine = await view.today_for(None, who="mia", owner=False)
    assert [i["item_id"] for i in mine["mine"]] == [job.item_id] and mine["mine_found"] == []


# ------------------------------------------------------------------ a change that closes a job

def made(operation="fulfillment_create", entity=ORDER_1.removeprefix("order:"), caller="mia@example.com",
         status=ActionStatus.VERIFIED):
    return SimpleNamespace(operation=operation, status=status, caller=caller, entity_ref=entity,
                           entity_label="#1001", proposal_id="prop_0123456789ab")


def let_in(person_id="mia"):
    people.note({"name": person_id.title(), "kind": "staff", "login": f"{person_id}@example.com"})
    access.ask(person_id, f"{person_id}@example.com")
    access.approve(person_id, by="owner", passkey="pk")


def test_a_fulfilment_closes_the_job_it_was_for_in_the_name_of_who_confirmed_it():
    let_in("mia")
    job = work.claim_found(ref=ORDER_1, kind="pack_order", title="Pack #1001", details="", who="mia")
    work.packed(job.item_id, who="mia")
    live._CACHE["orders"] = (0.0, {})
    hooks.after_commit(made())
    closed = work.get(job.item_id)
    assert closed.status == "done" and closed.done_by == "mia"
    assert closed.evidence["fulfilled"] and closed.evidence["packed"] and closed.evidence["proposal_id"] == "prop_0123456789ab"
    assert work.history(ref=ORDER_1)[1]["what"] == "fulfilled" and live._CACHE == {}


def test_a_reply_sent_by_the_owner_is_recorded_as_his_and_closes_a_claimed_job():
    job = work.claim_found(ref=EMAIL, kind="reply_email", title="Reply to Sam", details="", who="mia")
    with owner():                                                   # the commit route runs in the owner's request
        hooks.after_commit(made("gmail_send_reply", entity=EMAIL.removeprefix("email:"), caller="owner@example.com"))
    assert work.get(job.item_id).done_by == "owner"
    assert work.history(who="owner")[1]["what"] == "replied"


def test_a_draft_or_tracking_is_recorded_and_closes_nothing():
    job = work.claim_found(ref=EMAIL, kind="reply_email", title="Reply to Sam", details="", who="mia")
    hooks.after_commit(made("gmail_draft_reply", entity=EMAIL.removeprefix("email:")))
    assert work.get(job.item_id).status == "claimed" and work.history()[0]["what"] == "reply_drafted"


@pytest.mark.parametrize("change", [
    made(status=ActionStatus.FAILED), made(status=ActionStatus.STALE), made(operation="refund_create"),
])
def test_a_change_not_made_or_not_the_lists_changes_nothing(change):
    job = work.claim_found(ref=ORDER_1, kind="pack_order", title="Pack #1001", details="", who="mia")
    before = len(work.history())
    hooks.after_commit(change)
    assert work.get(job.item_id).status == "claimed" and len(work.history()) == before


def test_noting_a_change_never_gets_in_its_way():
    work.configure(None)
    hooks.after_commit(made())                                      # no list on this server: nothing, and no raise
    hooks.after_commit(object())


# ------------------------------------------------------------------ the model's hands on it

async def test_handing_out_jobs_and_routines_is_the_owners(monkeypatch):
    finding(monkeypatch)
    work_tools.bind(SimpleNamespace())
    people.note({"name": "Mia Rose", "kind": "staff"})
    with staff("mia-rose"):
        for action in ("assign", "routine", "cancel"):
            with pytest.raises(ToolError, match="Only the owner"):
                await work_tools.work_note(action=action, title="Restock")
    with owner():
        out = await work_tools.work_note(action="assign", title="Restock the shelves", to="mia")
        assert out["job"]["assignee"] == "mia-rose" and out["job"]["created_by"] == "owner"
        with pytest.raises(ToolError, match="No one called Zed"):
            await work_tools.work_note(action="assign", title="x", to="Zed")
        routine = await work_tools.work_note(action="routine", title="Tidy the desks", cadence="daily")
        assert routine["routine"]["cadence"] == "daily" and [i["title"] for i in routine["today"]] == ["Tidy the desks"]
        with pytest.raises(ToolError, match="not a step"):
            await work_tools.work_note(action="explode")


async def test_claiming_by_what_clive_found_and_a_record_of_ones_own(monkeypatch):
    finding(monkeypatch, orders=[order_row()])
    work_tools.bind(SimpleNamespace())
    with staff("mia"):
        claimed = await work_tools.work_note(action="claim", ref=ORDER_1)
        assert claimed["job"]["claimed_by"] == "mia" and claimed["job"]["kind"] == "pack_order"
        with pytest.raises(ToolError, match="not on today's list"):
            await work_tools.work_note(action="claim", ref=ORDER_2)
        packed = await work_tools.work_note(action="packed", item_id=claimed["job"]["item_id"])
        assert packed["job"]["evidence"]["packed"]
        own = await work_tools.work_list(record=True)
        assert {e["what"] for e in own["record"]} == {"created", "claimed", "packed"}
        people.note({"name": "Kit", "kind": "staff"})
        with pytest.raises(ToolError, match="your own record"):
            await work_tools.work_list(record=True, who="Kit")
        today = await work_tools.work_list()
        assert [r["ref"] for r in today["mine_found"]] == [ORDER_1]
    with staff("kit"), pytest.raises(ToolError, match="mia has already claimed that"):
        await work_tools.work_note(action="claim", ref=ORDER_1)


async def test_nobody_asking_is_refused():
    with authority.acting_as(None), pytest.raises(ToolError, match="Nobody is asking"):
        await work_tools.work_list()


# ------------------------------------------------------------------ what CLIVE finds by itself

class FakeShop:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked: list[tuple[str, dict]] = []

    async def graphql(self, query, variables=None):
        self.asked.append((query, variables or {}))
        return self.answers.pop(0) if self.answers else {"data": {}}


def an_order(number, lines, *, status="UNFULFILLED", note=""):
    return {"node": {
        "id": f"gid://shopify/Order/{number}", "name": f"#{number}", "processedAt": "2026-10-01T08:00:00Z",
        "note": note, "displayFulfillmentStatus": status, "customer": {"displayName": "Jane Doe"},
        "shippingLine": {"title": "Royal Mail Tracked 48"},
        "lineItems": {"edges": [{"node": line} for line in lines]},
    }}


async def test_orders_to_pack_are_read_from_shopify_with_only_what_is_left_to_pack():
    shop = FakeShop({"data": {"orders": {"edges": [
        an_order(1001, [{"name": "Hoodie", "variantTitle": "M", "sku": "HD-M", "quantity": 2, "unfulfilledQuantity": 2},
                        {"name": "Tee", "variantTitle": None, "sku": "", "quantity": 1, "unfulfilledQuantity": 0}],
                 status="PARTIALLY_FULFILLED", note="gift   wrap"),
        {"node": {}},
    ]}}})
    answer = await live._orders(SimpleNamespace(shopify=shop))
    assert "fulfillment_status:unfulfilled" in shop.asked[0][1]["q"] and "voided" in shop.asked[0][1]["q"]
    [row] = answer["items"]
    assert row["ref"] == "order:gid://shopify/Order/1001" and row["kind"] == "pack_order"
    assert row["title"] == "Pack #1001: 2 items for Jane Doe" and row["partly"] is True
    assert row["lines"] == [{"item": "Hoodie (M)", "sku": "HD-M", "quantity": 2}]
    assert "Royal Mail Tracked 48" in row["details"] and "note: gift wrap" in row["details"]
    assert (await live._orders(SimpleNamespace(shopify=None)))["available"] is False


async def test_emails_waiting_carry_what_clive_knows_about_who_wrote(monkeypatch):
    from app.tools import gmail_tools

    threads = [{"thread_id": "t-waiting", "from": "Sam", "from_email": "sam@example.com", "subject": "Where is my order?",
                "snippet": "It has been a week"},
               {"thread_id": "t-answered", "from": "Ali", "from_email": "ali@example.com", "subject": "Thanks"}]

    async def inbox_threads(*, days, limit):
        return {"available": True, "threads": threads}

    async def reply_state(thread_id):
        if thread_id == "t-answered":
            return {"waiting_since": None, "has_reply_after_latest_inbound": True}
        return {"waiting_since": 1_759_300_000_000, "has_reply_after_latest_inbound": False}

    monkeypatch.setattr(gmail_tools, "inbox_threads", inbox_threads)
    monkeypatch.setattr(gmail_tools, "reply_state", reply_state)
    shop = FakeShop({"data": {"customers": {"edges": [{"node": {"numberOfOrders": 2, "orders": {"edges": [
        {"node": {"name": "#1001", "displayFulfillmentStatus": "UNFULFILLED"}}]}}}]}}})
    answer = await live._emails(SimpleNamespace(shopify=shop))
    [row] = answer["items"]
    assert row["ref"] == "email:t-waiting" and row["title"] == "Reply to Sam: Where is my order?"
    assert "2 orders; the latest, #1001, is unfulfilled." in row["details"]
    assert shop.asked[0][1] == {"q": "email:sam@example.com"}

    async def no_gmail(*, days, limit):
        return {"available": False, "reason": "Gmail is not configured on this backend.", "threads": []}

    monkeypatch.setattr(gmail_tools, "inbox_threads", no_gmail)
    assert (await live._emails(SimpleNamespace(shopify=shop)))["reason"].startswith("Gmail is not configured")


async def test_instagram_waiting_is_the_conversations_whose_last_word_is_theirs(monkeypatch):
    from app.clients import instagram

    ours = {"id": "1784", "username": "crooksldn"}
    monkeypatch.setattr(instagram, "token", lambda: bearer_token("work-instagram"))

    async def account():
        return {"id": "1784", "username": "crooksldn"}

    async def conversations(limit=10):
        return [
            {"conversation_id": "c2", "username": "late", "latest": {"from": {"id": "9"}, "text": "hello?", "created_time": "2026-10-01T09:00:00+0000"}},
            {"conversation_id": "c1", "username": "early", "latest": {"from": {"id": "8"}, "text": "", "attachments": 1, "created_time": "2026-10-01T07:00:00+0000"}},
            {"conversation_id": "c3", "username": "answered", "latest": {"from": ours, "text": "sorted", "created_time": "2026-10-01T10:00:00+0000"}},
            {"conversation_id": "c4", "username": "empty", "latest": None},
        ]

    monkeypatch.setattr(instagram, "account", account)
    monkeypatch.setattr(instagram, "conversations", conversations)
    answer = await live._instagram(SimpleNamespace())
    assert [(r["ref"], r["snippet"]) for r in answer["items"]] == [("instagram:c1", "(an attachment)"), ("instagram:c2", "hello?")]
    assert answer["items"][1]["title"] == "Instagram: @late is waiting"
    monkeypatch.setattr(instagram, "token", lambda: "")
    assert (await live._instagram(SimpleNamespace()))["available"] is False


async def test_one_source_failing_or_slow_never_hides_the_others_and_answers_are_kept_a_minute(monkeypatch):
    asked = []

    async def orders(runtime):
        asked.append("orders")
        return {"available": True, "items": [order_row()]}

    async def broken(runtime):
        raise RuntimeError("the inbox is down")

    async def slow(runtime):
        await asyncio.sleep(5)

    monkeypatch.setattr(live, "SOURCES", {"orders": orders, "emails": broken, "instagram": slow})
    monkeypatch.setattr(live, "SOURCE_TIMEOUT_S", 0.05)
    monkeypatch.setattr(live, "MIN_FRESH_S", 0.0)
    answers = await live.found(None)
    assert answers["orders"]["items"][0]["ref"] == ORDER_1
    assert answers["emails"] == {"available": False, "reason": "could not be read just now", "items": []}
    assert answers["instagram"] == {"available": False, "reason": "did not answer in time", "items": []}
    await live.found(None)
    assert asked == ["orders"]                                      # kept: not asked again within the minute
    await live.found(None, fresh=True)
    assert asked == ["orders", "orders"]


async def test_each_source_is_kept_for_its_own_time(monkeypatch):
    asked = []

    def source(name):
        async def read(runtime):
            asked.append(name)
            return {"available": True, "items": []}
        return read

    monkeypatch.setattr(live, "SOURCES", {name: source(name) for name in ("orders", "emails", "instagram")})
    clock = [1000.0]
    monkeypatch.setattr(live.time, "monotonic", lambda: clock[0])
    await live.found(None)
    clock[0] += 90                                                  # past a minute: the shop again, not the inboxes
    await live.found(None)
    clock[0] += 60                                                  # past two: email too
    await live.found(None)
    clock[0] += 200                                                 # past five: Instagram as well
    await live.found(None)
    assert asked.count("orders") == 4 and asked.count("emails") == 3 and asked.count("instagram") == 2
    clock[0] += 5
    await live.found(None, fresh=True)                              # a page opened seconds later asks nothing
    assert len(asked) == 9
    clock[0] += 10
    await live.found(None, fresh=True)
    assert len(asked) == 12


@pytest.mark.parametrize("stamp, expected", [
    (1_759_300_000_000, datetime.fromtimestamp(1_759_300_000, UTC)),
    ("2026-10-01T09:00:00+0000", datetime(2026, 10, 1, 9, tzinfo=UTC)),
    ("2026-10-01T09:00:00Z", datetime(2026, 10, 1, 9, tzinfo=UTC)),
    ("2026-10-01T09:00:00", datetime(2026, 10, 1, 9, tzinfo=UTC)),
    ("", None), (None, None), ("soon", None), (True, None),
])
def test_a_sources_time_is_read_whatever_its_form(stamp, expected):
    assert live.when(stamp) == expected
