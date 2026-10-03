"""Objectives by touch, part C: a number to reach ("shift the last 200 hoodies by the 18th").

Any kind of objective may carry a number: what is counted (a product as George names it), the target,
the day counting starts and the unit's words. What is held here:

* the number is set, changed and taken off through the store and through the model's own tools
  (objective_open, objective_note `set`), validated and bounded like the rest of the design, with no
  new tool and nothing new on the gate's allow-list;
* it lives in the design file, so a record still reads in the store before round 12, and a record
  with no design reads exactly as it did, with no number;
* what has sold is counted from the order rows the sales figures use (app/objectives/count.py): per
  day since the start, the total, the pace over the last 14 whole days, the day the pace reaches the
  target and, against the deadline, days early or how many short; nothing sold is a pace of nothing;
  a shop that cannot be read, or orders still being read, is said in words with no figure at all;
* the owner's route moves the target, offered back for six seconds, and the undo puts it back;
* the model's tools never read the shop, and counting writes nothing anywhere;
* the drawing, under Node (tests/web/objective-number.test.js).

Every name and figure is invented (Loopback Hoodie, Rosa).
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
import types
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analytics.cache import CacheView
from app.objectives import cards, count, tools
from app.objectives import store as store_module
from app.objectives.store import RECORD_FIELDS, ObjectiveError, ObjectiveStore
from app.tools import analytics_tools, gate
from app.tools.registry import ToolError

LONDON = ZoneInfo("Europe/London")
ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "objectives"
REPO = Path(__file__).resolve().parents[2]
TRUNK = "547f652f"
# The design's own fortnight and a half: hoodies sold a day, 1 Sep to Tue 29 Sep 2026, 138 in all.
SOLD = [4, 3, 5, 6, 10, 8, 3, 4, 3, 4, 6, 9, 7, 2, 3, 4, 3, 5, 8, 6, 3, 2, 3, 4, 5, 7, 7, 2, 2]


def today() -> date:
    return datetime.now(LONDON).date()


# ------------------------------------------------------------------ the shop's orders, as the cache holds them


def order(n: int, when: datetime, *items: tuple[str, int], cancelled: bool = False, colour: str = "") -> dict:
    """One order row of the shape app/analytics/cache.py `shape_order` makes."""
    return {"order_id": f"gid://shopify/Order/{n}", "order_number": f"#{n}", "ts": when.timestamp(), "cancelled": cancelled,
            "fulfillment": "FULFILLED", "financial": "PAID", "customer": None, "tags": [], "country_code": "GB",
            "items": [{"product": p, "product_type": "Hoodie" if "Hoodie" in p else "Tee", "sku": "", "variant": colour,
                       "colour": colour, "size": "M", "quantity": q, "variant_id": "", "product_id": ""} for p, q in items]}


def sales(first: date, per_day: list[int], product: str = "Loopback Hoodie", colour: str = "Grey") -> list[dict]:
    """per_day[i] hoodies on first + i, at midday London, one order each, with noise that must not count.

    Today's sales are made before now: at midday only once midday has passed. The count reads up to
    now, so before noon a sale placed at noon today was still in the future and went uncounted, and
    the suite failed every morning (136 counted, not 138)."""
    rows, n = [], 1000
    now = datetime.now(LONDON)
    for i, sold in enumerate(per_day):
        midnight = datetime.combine(first + timedelta(days=i), datetime.min.time(), tzinfo=LONDON)
        noon = midnight + timedelta(hours=12)
        if noon > now:
            noon = max(midnight, now - timedelta(minutes=1))
        if sold:
            rows.append(order(n, noon, (product, sold), colour=colour))
        rows.append(order(n + 1, noon, ("Cell Block Tee", 3)))                      # another product
        rows.append(order(n + 2, noon, (product, 5), cancelled=True, colour=colour))  # cancelled: not a sale
        n += 3
    return rows


class Client:
    def __init__(self, zone=LONDON, fail: Exception | None = None, slow: float = 0.0):
        self.zone, self.fail, self.slow, self.graphql_calls, self.zone_calls = zone, fail, slow, 0, 0

    async def timezone(self):                         # a shop query on the real client when not held
        self.zone_calls += 1
        if self.slow:
            await asyncio.sleep(self.slow)
        if self.fail:
            raise self.fail
        return self.zone

    async def graphql(self, *_args, **_kwargs):      # the cache's own reads; counting never asks
        self.graphql_calls += 1
        raise AssertionError("counting must read the cache, not Shopify directly")


class Cache:
    """The order cache, as counting sees it: rows, and the truth about them."""

    def __init__(self, rows, *, complete=True, note="", fail: Exception | None = None, client: Client | None = None):
        self.rows, self.complete, self.note, self.fail = rows, complete, note, fail
        self.client = client or Client()
        self.views = 0

    def _client(self):
        return self.client

    async def view(self, period, *, timeout_s=6.0):
        self.views += 1
        if self.fail:
            raise self.fail
        now = datetime.now(LONDON).timestamp()
        return CacheView(rows=[r for r in self.rows if r["ts"] >= period.start.timestamp()], complete=self.complete,
                         covered_days=90.0, synced_at=now - 120, syncing=False, note=self.note, asked_at=now)


@pytest.fixture
def shop():
    """A cache bound where the sales tools find it, forgotten afterwards."""
    count.forget()
    holder = SimpleNamespace(cache=None)

    def bind(cache):
        holder.cache = cache
        analytics_tools.bind(cache)
        count.forget()
        return cache

    holder.bind = bind
    yield holder
    analytics_tools.bind(None)
    count.forget()


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives")


@pytest.fixture
def owner(tmp_path):
    from app.routes import objectives

    store = store_module.install(tmp_path / "objectives")
    app = FastAPI()
    app.include_router(objectives.router)
    settings = SimpleNamespace(writes_local_owner=True, tailscale_verify=False, tailscale_cli="")
    app.state.runtime = SimpleNamespace(allowed_logins=("owner@example.test",), settings=settings)
    return SimpleNamespace(client=TestClient(app), store=store, root=tmp_path / "objectives")


def hoodies(store: ObjectiveStore, *, since: date | None = None, deadline: date | None = None, target: int = 200):
    first = since or today() - timedelta(days=len(SOLD) - 1)
    return store.create(title="Loopback Hoodie", request="Shift the last 200 hoodies by the 18th",
                        deadline=(deadline or today() + timedelta(days=19)).isoformat(),
                        number={"of": "Loopback Hoodie", "target": target, "since": first.isoformat(), "unit": "hoodies"})


# ------------------------------------------------------------------ the field: set, changed, taken off


def test_a_number_is_set_changed_and_taken_off_through_the_store(s):
    first = today() - timedelta(days=28)
    obj = hoodies(s, since=first)
    assert obj.number == {"of": "Loopback Hoodie", "target": 200, "since": first.isoformat(), "unit": "hoodies"}
    assert obj.kind == "business" and obj.summary()["number"] == obj.number
    changed = s.design(obj.id, number={"target": 250})
    assert changed.number == {**obj.number, "target": 250}, "only what is passed changes"
    assert changed.events[-1]["text"] == "Target 250."
    moved = s.design(obj.id, number={"since": (first + timedelta(days=7)).isoformat(), "unit": "grey hoodies"})
    assert moved.number["target"] == 250 and moved.number["unit"] == "grey hoodies"
    assert "counted from" in moved.events[-1]["text"] and "counted as grey hoodies" in moved.events[-1]["text"]
    off = s.design(obj.id, number={})
    assert off.number is None and off.events[-1]["text"] == "No number." and "number" not in off.summary()
    with pytest.raises(ObjectiveError, match="no number to take off"):
        s.design(obj.id, number={})
    # A new one, on a project, counting from the day it is set when he gives no day.
    made = s.create(title="AW drop", request="AW drop", kind="project", stages=["Sampling", "Production"],
                    number={"of": "pink joggers", "target": 60})
    assert made.number == {"of": "pink joggers", "target": 60, "since": today().isoformat(), "unit": None}
    assert s.get(made.id).number == made.number, "read back from the design file"


@pytest.mark.parametrize(("number", "words"), [
    ({"of": "Loopback Hoodie", "target": 0}, "between 1 and 100,000"),
    ({"of": "Loopback Hoodie", "target": 100_001}, "between 1 and 100,000"),
    ({"of": "Loopback Hoodie", "target": "lots"}, "is a number"),
    ({"of": "Loopback Hoodie", "target": 1.5}, "whole number"),
    ({"of": "Loopback Hoodie", "target": True}, "is a number"),
    ({"of": "Loopback Hoodie"}, "what is counted (of) and its target"),
    ({"target": 200}, "what is counted (of) and its target"),
    ({"of": "   ", "target": 200}, "thing it counts is empty"),
    ({"of": "Loopback Hoodie", "target": 200, "colour": "grey"}, "not colour"),
    ({"of": "Loopback Hoodie", "target": 200, "since": "the 1st"}, "not a date"),
    ({"of": "Loopback Hoodie", "target": 200, "since": "2020-01-01"}, "read back a year at most"),
    ("200 hoodies", "A number is what is counted"),
])
def test_a_number_is_refused_whole_and_in_words(s, number, words):
    with pytest.raises(ObjectiveError, match=words.replace("(", r"\(").replace(")", r"\)")):
        s.create(title="Hoodies", request="Shift the hoodies", number=number)
    obj = s.create(title="Hoodies", request="Shift the hoodies")
    events = len(obj.events)
    with pytest.raises(ObjectiveError):
        s.design(obj.id, number=number)
    assert s.get(obj.id).number is None and len(s.get(obj.id).events) == events, "nothing was written"


def test_a_long_name_and_unit_are_bounded(s):
    obj = s.create(title="Hoodies", request="x", number={"of": "Loopback " * 20, "target": 5, "unit": "hoodie " * 10})
    assert len(obj.number["of"]) <= 60 and len(obj.number["unit"]) <= 30


def test_the_model_sets_and_changes_a_number_by_voice_on_the_tools_it_already_has(s):
    from app.tools import registry

    first = (today() - timedelta(days=3)).isoformat()
    opened = asyncio.run(tools.objective_open("Loopback Hoodie", "Shift the last 200 hoodies by the 18th", kind="business",
                                              deadline=(today() + timedelta(days=16)).isoformat(),
                                              number={"of": "Loopback Hoodie", "target": 200, "since": first, "unit": "hoodies"}))
    oid = opened["id"]
    assert opened["number"]["target"] == 200 and opened["summary"]["number"]["of"] == "Loopback Hoodie"
    card = opened["_surfaces"][0]["data"]
    assert card["number"] == {"of": "Loopback Hoodie", "target": 200, "since": first, "unit": "hoodies"}
    assert "count" not in card, "the model's tools never read the shop: the tablet asks its own route"
    moved = asyncio.run(tools.objective_note(oid, "set", number={"target": 180}))
    assert moved["objective"]["number"]["target"] == 180 and moved["_surfaces"][0]["data"]["number"]["target"] == 180
    cleared = asyncio.run(tools.objective_note(oid, "set", number={}))
    assert "number" not in cleared["objective"] and "number" not in cleared["_surfaces"][0]["data"]
    with pytest.raises(ToolError, match="between 1 and 100,000"):
        asyncio.run(tools.objective_note(oid, "set", number={"of": "hoodies", "target": -3}))
    # No new tool, and the four it has stay where the gate already lets them run.
    for name in ("objective_open", "objective_note"):
        assert registry.get(name).input_schema["properties"]["number"]["properties"].keys() == {"of", "target", "since", "unit"}
        assert gate.classify(name, {}).disposition is gate.Disposition.EXECUTE_NOW, name
    assert not [n for n in registry.names() if "number" in n or "target" in n]


def test_the_prompt_teaches_the_number_once(tmp_path):
    from app.kb.loader import build_system_prompt, load

    prompt = build_system_prompt(load(tmp_path))
    assert prompt.count("Any kind may carry number") == 1
    assert "never record a count" in prompt and "{} takes it off" in prompt


# ------------------------------------------------------------------ rollback: nothing already stored changes


def test_a_record_without_a_design_reads_as_before_with_no_number(tmp_path):
    raw = json.loads((FIXTURES / "business_v1.json").read_text(encoding="utf-8"))
    root = tmp_path / "objectives"
    root.mkdir()
    (root / f"{raw['id']}.json").write_text(json.dumps(raw), encoding="utf-8")
    loaded = ObjectiveStore(root).get(raw["id"])
    assert loaded.number is None and "number" not in loaded.summary(), "the summary reads exactly as it did"
    assert "number" not in cards.data(loaded) and "count" not in cards.data(loaded)
    assert {k: v for k, v in loaded.to_dict().items() if k in raw} == raw


def test_a_design_written_before_numbers_reads_with_none(s):
    obj = s.create(title="Hoodies", request="x", kind="tasks", tasks=[{"who": "Rosa", "text": "Steam the samples"}])
    path = s.root / "design" / f"{obj.id}.json"
    design = json.loads(path.read_text(encoding="utf-8"))
    design.pop("number")
    path.write_text(json.dumps(design), encoding="utf-8")
    again = ObjectiveStore(s.root).get(obj.id)
    assert again.number is None and [t["who"] for t in again.tasks] == ["Rosa"]


def _trunk_store():
    text = (FIXTURES / f"store_{TRUNK}.py.txt").read_text(encoding="utf-8")
    try:
        shown = subprocess.run(["git", "show", f"{TRUNK}:crooks-assistant/app/objectives/store.py"],
                               cwd=REPO, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        shown = None
    if shown is not None and shown.returncode == 0:
        assert shown.stdout == text
    name = f"number_trunk_objectives_store_{TRUNK}"
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(text, f"<{TRUNK}:app/objectives/store.py>", "exec"), module.__dict__)
    return name, module


def test_a_number_lives_in_the_design_file_and_the_store_before_round_12_still_reads_the_record(owner, shop):
    shop.bind(Cache([]))
    obj = hoodies(owner.store)
    moved = owner.client.post(f"/objectives/{obj.id}/target", json={"target": 240})
    assert moved.status_code == 200
    record = json.loads((owner.root / f"{obj.id}.json").read_text(encoding="utf-8"))
    assert list(record) == list(RECORD_FIELDS) and "number" not in json.dumps(record["events"][:1])
    design = json.loads((owner.root / "design" / f"{obj.id}.json").read_text(encoding="utf-8"))
    assert design["number"]["target"] == 240 and design["version"] == 3, "the same format: no rollback sets it aside"
    name, trunk = _trunk_store()
    try:
        old = trunk.ObjectiveStore(owner.root)
        assert [o.id for o in old.all()] == [obj.id]
        json.dumps({**old.get(obj.id).to_dict(), "summary": old.get(obj.id).summary()})
    finally:
        sys.modules.pop(name, None)
    assert ObjectiveStore(owner.root).get(obj.id).number["target"] == 240, "rolled forward, it is where it was"


# ------------------------------------------------------------------ counting, from the order rows


def run(number, *, deadline=None, now=None):
    return asyncio.run(count.count(number, deadline=deadline, now=now))


NOW = datetime(2026, 9, 29, 15, 0, tzinfo=LONDON)            # Tue 29 Sep 2026, mid-afternoon in London
HOODIE = {"of": "Loopback Hoodie", "target": 200, "since": "2026-09-01", "unit": "hoodies"}


def test_sales_are_counted_per_day_with_the_pace_and_the_day_it_lands(shop):
    shop.bind(Cache(sales(date(2026, 9, 1), SOLD)))
    tally = run(HOODIE, deadline="2026-10-18", now=NOW)
    assert tally["counted"] is True and tally["per_day"] == SOLD and tally["total"] == 138
    assert tally["pace_days"] == 14 and tally["pace"] == round(sum(SOLD[14:28]) / 14, 2), "the last 14 whole days, not today"
    assert tally["lands"] == "2026-10-13" and tally["days_early"] == 5 and tally["short"] is None
    assert count.pace_words(tally) == "At this pace: 200 by Tue 13 Oct, 5 days early"
    assert tally["counted_at"] and tally["age_s"] == 120 and tally["today"] == "2026-09-29"
    assert count.short(tally) == {"counted": True, "sold": 138, "lands": "2026-10-13", "reached_on": None, "far": False,
                                  "late": False, "days_early": 5, "by_deadline": None, "short": None}


def test_a_target_the_pace_falls_short_of_says_by_how_many(shop):
    shop.bind(Cache(sales(date(2026, 9, 1), SOLD)))
    tally = run({**HOODIE, "target": 250}, deadline="2026-10-18", now=NOW)
    assert tally["lands"] == "2026-10-25" and tally["days_early"] is None, "late is never a negative 'days early'"
    assert tally["by_deadline"] == 222 and tally["short"] == 28
    assert count.pace_words(tally) == "At this pace: 222 by Sun 18 Oct, 28 short"
    assert count.short(tally)["late"] is True
    gone = run({**HOODIE, "target": 250}, deadline="2026-09-20", now=NOW)
    assert gone["by_deadline"] == sum(SOLD[:20]) and count.pace_words(gone).startswith("Was due Sun 20 Sep: ")
    reached = run({**HOODIE, "target": 100}, deadline="2026-10-18", now=NOW)
    assert reached["reached_on"] == "2026-09-20" and count.pace_words(reached) == "100 reached on Sun 20 Sep"
    assert count.short(reached)["late"] is False


def test_words_match_as_the_sales_figures_match_them_and_cancelled_orders_are_not_sales(shop):
    shop.bind(Cache(sales(date(2026, 9, 1), SOLD, product="Loopback Hoodie", colour="Grey")))
    assert run({**HOODIE, "of": "grey hoodie"}, now=NOW)["total"] == 138, "every word, in any field the label prints"
    assert run({**HOODIE, "of": "black hoodie"}, now=NOW)["total"] == 0
    assert run({**HOODIE, "of": "cell block tee"}, now=NOW)["total"] == 3 * len(SOLD)


def test_nothing_sold_is_a_pace_of_nothing_and_no_day_is_invented(shop):
    shop.bind(Cache(sales(date(2026, 9, 1), [0] * 29)))
    tally = run(HOODIE, deadline="2026-10-18", now=NOW)
    assert tally["total"] == 0 and tally["pace"] == 0 and tally["lands"] is None
    assert tally["short"] == 200 and tally["by_deadline"] == 0
    assert count.pace_words({**tally, "short": None}) == "Nothing sold in the last 14 days, so no pace to go by"
    started = run({**HOODIE, "since": "2026-09-29"}, deadline="2026-10-18", now=NOW)
    assert started["pace"] is None and count.pace_words(started) == "No whole day counted yet, so no pace to go by"
    assert started["short"] is None and count.short(started)["late"] is False, "a first day is not called short"
    later = run({**HOODIE, "since": "2026-10-03"}, now=NOW)
    assert later == {"counted": False, "why": "Counting starts Sat 3 Oct.", "of": "Loopback Hoodie", "target": 200,
                     "since": "2026-10-03", "unit": "hoodies"}


@pytest.mark.parametrize("cache", [
    None,                                                                 # no cache on this backend
    Cache([], fail=RuntimeError("Shopify down")),
    Cache([], client=Client(fail=RuntimeError("no shop"))),
    Cache(sales(date(2026, 9, 1), SOLD), complete=False, note="The server holds 3 day(s) of orders so far."),
])
def test_a_shop_that_cannot_be_read_is_said_and_nothing_is_counted(shop, cache):
    shop.bind(cache)
    tally = run(HOODIE, deadline="2026-10-18", now=NOW)
    assert tally["counted"] is False and tally["why"]
    assert not {"per_day", "total", "pace", "lands", "short"} & set(tally), "no figure at all"
    if cache is not None and not cache.complete:
        assert tally["why"] == "The server holds 3 day(s) of orders so far."
    else:
        assert tally["why"] == "Shopify could not be read just now, so nothing is counted."
    assert count.pace_words(tally) == "" and count.short(tally) == {"counted": False, "why": tally["why"]}


def test_a_count_is_kept_for_a_minute_and_reads_nothing_but_the_cache(shop):
    cache = shop.bind(Cache(sales(date(2026, 9, 1), SOLD)))
    run(HOODIE, now=NOW)
    run({**HOODIE, "target": 300}, deadline="2026-10-18", now=NOW)
    assert cache.views == 1 and cache.client.graphql_calls == 0
    count.forget()
    run(HOODIE, now=NOW)
    assert cache.views == 2


# ------------------------------------------------------------------ the owner's routes


def test_the_sheet_and_the_home_carry_the_count(owner, shop):
    first = today() - timedelta(days=len(SOLD) - 1)
    shop.bind(Cache(sales(first, SOLD)))
    obj = hoodies(owner.store, since=first)
    body = owner.client.get(f"/objectives/{obj.id}").json()
    assert body["card"]["number"]["of"] == "Loopback Hoodie"
    got = body["card"]["count"]
    assert got["counted"] is True and got["total"] == 138 and len(got["per_day"]) == len(SOLD)
    assert body["summary"]["number"]["sold"] == 138 and body["summary"]["number"]["of"] == "Loopback Hoodie"
    listed = owner.client.get("/objectives").json()["objectives"]
    assert listed[0]["number"]["counted"] is True and listed[0]["number"]["sold"] == 138
    plain = owner.store.create(title="Lookbook", request="Shoot the lookbook")
    assert "count" not in owner.client.get(f"/objectives/{plain.id}").json()["card"]


def test_without_a_cache_the_sheet_says_why_and_counts_nothing(owner, shop):
    shop.bind(None)
    obj = hoodies(owner.store)
    card = owner.client.get(f"/objectives/{obj.id}").json()["card"]
    assert card["count"] == {"counted": False, "why": "Shopify could not be read just now, so nothing is counted."}
    assert owner.client.get("/objectives").json()["objectives"][0]["number"]["counted"] is False


def test_the_target_is_dragged_offered_back_and_undone(owner, shop):
    first = today() - timedelta(days=len(SOLD) - 1)
    shop.bind(Cache(sales(first, SOLD)))
    obj = hoodies(owner.store, since=first, deadline=today() + timedelta(days=19))
    answer = owner.client.post(f"/objectives/{obj.id}/target", json={"target": 250})
    body = answer.json()
    assert answer.status_code == 200, answer.text
    assert set(body["undo"]) == {"token", "ttl_s", "says"} and body["undo"]["ttl_s"] == 6 and body["said"] is None
    assert body["undo"]["says"].startswith("Target 250. At this pace: 222 by ") and body["undo"]["says"].endswith(", 28 short")
    assert body["number"]["target"] == 250 and body["card"]["number"]["target"] == 250
    assert body["events"][-1]["by"] == "owner" and body["events"][-1]["text"] == "Target 250."
    undone = owner.client.post(f"/objectives/{obj.id}/undo", json={"token": body["undo"]["token"]})
    assert undone.status_code == 200 and undone.json()["said"] == "Target 200 again"
    assert owner.store.get(obj.id).number == obj.number and undone.json()["events"][-1]["text"] == "Undone: Target 250."
    same = owner.client.post(f"/objectives/{obj.id}/target", json={"target": 200}).json()
    assert same["undo"] is None and same["said"] == "The target is already 200."
    for bad, words in ((0, "between 1 and 100,000"), (100_001, "between 1 and 100,000")):
        refused = owner.client.post(f"/objectives/{obj.id}/target", json={"target": bad})
        assert refused.status_code == 400 and words in refused.json()["detail"]
    plain = owner.store.create(title="Lookbook", request="Shoot the lookbook")
    none = owner.client.post(f"/objectives/{plain.id}/target", json={"target": 10})
    assert none.status_code == 400 and none.json()["detail"] == "This objective has no number, so it has no target to move."
    assert owner.store.get(obj.id).number["target"] == 200


def test_a_target_moved_while_the_shop_is_unread_still_moves_and_says_only_the_target(owner, shop):
    shop.bind(None)
    obj = hoodies(owner.store)
    body = owner.client.post(f"/objectives/{obj.id}/target", json={"target": 150}).json()
    assert body["undo"]["says"] == "Target 150" and body["card"]["count"]["counted"] is False


# ------------------------------------------------------------------ the review of PR #92


def test_the_day_it_lands_and_the_shortfall_are_one_fact_never_split_by_a_float():
    """65 more at 52 over 12 days is exactly 15 days: on the day, not one after it with nothing
    short (which said "-1 days early" and drew the row on pace)."""
    per_day = [1, 0, 1, 1, 7, 7, 7, 9, 5, 1, 7, 6, 1]
    today_ = date(2026, 10, 2)
    first = today_ - timedelta(days=len(per_day) - 1)
    due = (today_ + timedelta(days=15)).isoformat()
    on = {**count.project(per_day, 118, first, today_, due), "counted": True, "today": today_.isoformat(), "target": 118}
    assert on["lands"] == due and on["days_early"] == 0 and on["short"] is None
    assert count.pace_words(on) == "At this pace: 118 by Sat 17 Oct, on the day" and count.short(on)["late"] is False
    over = {**count.project(per_day, 119, first, today_, due), "counted": True, "today": today_.isoformat(), "target": 119}
    assert over["days_early"] is None and over["short"] == 1 and over["by_deadline"] == 118
    assert count.pace_words(over) == "At this pace: 118 by Sat 17 Oct, 1 short" and count.short(over)["late"] is True
    # And for every target and deadline nearby: late exactly when it lands after the deadline.
    for target in range(54, 260):
        for ahead in range(0, 40):
            due = today_ + timedelta(days=ahead)
            got = count.project(per_day, target, first, today_, due.isoformat())
            lands_after = got["lands"] is None or date.fromisoformat(got["lands"]) > due
            assert bool(got["short"]) == lands_after, (target, ahead, got)
            assert got["days_early"] is None or got["days_early"] >= 0, (target, ahead)
            words = count.pace_words({**got, "counted": True, "today": today_.isoformat(), "target": target})
            assert "-" not in words, words


def test_a_number_counted_for_more_than_a_year_sends_its_first_day_and_what_came_before(s):
    obj = s.create(title="Hoodies", request="x", number={"of": "Loopback Hoodie", "target": 900})
    per_day = [1] * 34 + [2] * 366
    tally = {"counted": True, "per_day": per_day, "total": sum(per_day), "today": "2026-10-02", "pace": 2.0, "pace_days": 14}
    sent = cards.data(obj, tally)["count"]
    assert len(sent["per_day"]) == 366 and sent["per_day"] == [2] * 366
    assert sent["first"] == (date(2026, 10, 2) - timedelta(days=365)).isoformat(), "indexed from the first day sent"
    assert sent["carried"] == 34 and sent["carried"] + sum(sent["per_day"]) == sent["total"] == 766
    short_run = cards.data(obj, {**tally, "per_day": [3, 4], "total": 7})["count"]
    assert short_run["first"] == "2026-10-01" and short_run["carried"] == 0


def test_an_old_number_keeps_its_day_when_its_target_moves(s, monkeypatch):
    long_ago = today() - timedelta(days=300)
    obj = hoodies(s, since=long_ago)
    later = today() + timedelta(days=100)
    monkeypatch.setattr(store_module, "_shop_today", lambda: later)     # the day it was set is now >365 days back
    moved = s.design(obj.id, number={"target": 250})
    assert moved.number["target"] == 250 and moved.number["since"] == long_ago.isoformat()
    touched, offer, said = s.touch_target(obj.id, 240)
    assert touched.number["target"] == 240 and offer and said is None
    assert s.design(obj.id, number={"unit": "grey hoodies"}).number["since"] == long_ago.isoformat()
    with pytest.raises(ObjectiveError, match="read back a year at most"):
        s.design(obj.id, number={"since": long_ago.isoformat()})     # set now, it is held to the year


def test_what_was_counted_is_named_the_most_sold_first(shop):
    noon = datetime(2026, 9, 20, 12, 0, tzinfo=LONDON)
    shop.bind(Cache([
        order(1, noon, ("Loopback Hoodie", 5), colour="Grey"),
        order(2, noon, ("Loopback Zip Hoodie", 2), colour="Black"),
        order(3, noon, ("Loopback Hoodie", 1), colour="Black"),
        order(4, noon, ("Loopback Hoodie Kids", 1), colour="Grey"),
        order(5, noon, ("Loopback Hoodie Bundle", 1), colour="Grey"),
        order(6, noon, ("Loopback Hoodie Gift Card", 1)),
        order(7, noon, ("Cell Block Tee", 9)),
    ]))
    broad = run(HOODIE, now=NOW)
    assert broad["matched"] == ["Loopback Hoodie", "Loopback Zip Hoodie", "Loopback Hoodie Bundle"]
    assert broad["matched_more"] == 2 and broad["total"] == 11
    grey = run({**HOODIE, "of": "grey hoodie"}, now=NOW)
    assert grey["matched"] == ["Loopback Hoodie (Grey)", "Loopback Hoodie Bundle (Grey)", "Loopback Hoodie Kids (Grey)"]
    assert grey["matched_more"] == 0 and grey["total"] == 7
    none = run({**HOODIE, "of": "pink joggers"}, now=NOW)
    assert none["matched"] == [] and none["total"] == 0


def test_returns_and_removals_are_not_sales(shop):
    noon = datetime(2026, 9, 20, 12, 0, tzinfo=LONDON)
    kept = order(1, noon, ("Loopback Hoodie", 3), colour="Grey")
    kept["items"][0]["current_quantity"] = 1                # two of the three came back
    older = order(2, noon, ("Loopback Hoodie", 2), colour="Grey")    # a row read before the cache kept it
    shop.bind(Cache([kept, older]))
    assert run(HOODIE, now=NOW)["total"] == 3


def test_an_unreadable_shop_is_asked_once_a_minute_and_once_for_every_count_waiting(shop):
    down = shop.bind(Cache([], client=Client(fail=RuntimeError("no shop"))))
    for _ in range(3):
        assert run(HOODIE, now=NOW)["counted"] is False
    assert run({**HOODIE, "of": "grey hoodie"}, now=NOW)["counted"] is False
    assert down.client.zone_calls == 1, "a failure to read the shop is kept for the minute"
    failing = shop.bind(Cache([], fail=RuntimeError("Shopify down")))
    run(HOODIE, now=NOW)
    run(HOODIE, now=NOW)
    assert failing.views == 1, "an unread answer is kept for the minute, as a count is"
    slow = shop.bind(Cache(sales(date(2026, 9, 1), SOLD), client=Client(slow=0.05)))

    async def together():
        return await asyncio.gather(*(count.count({**HOODIE, "of": of}, now=NOW) for of in ("Loopback Hoodie", "grey hoodie", "hoodie")))

    assert all(t["counted"] for t in asyncio.run(together()))
    assert slow.client.zone_calls == 1, "one call for the zone, shared by every count waiting on it"
    run({**HOODIE, "target": 300}, now=NOW)
    assert slow.client.zone_calls == 1, "and once read, it is known"


def test_the_home_polled_while_the_shop_is_down_asks_it_once(owner, shop):
    down = shop.bind(Cache([], client=Client(fail=RuntimeError("no shop"))))
    for of in ("Loopback Hoodie", "grey hoodie", "Cell Block Tee"):
        owner.store.create(title=of, request=of, number={"of": of, "target": 50})
    for _ in range(2):
        listed = owner.client.get("/objectives").json()["objectives"]
        assert [o["number"]["counted"] for o in listed] == [False, False, False]
    assert down.client.zone_calls == 1


# ------------------------------------------------------------------ the owner's alone, and nothing written


@pytest.fixture()
async def desk(tmp_path):
    from experience.harness import harness

    async with harness(admitted=True) as h:
        h.objectives = store_module.install(tmp_path / "objectives")
        count.forget()
        yield h
    count.forget()


async def test_the_target_and_its_undo_are_the_owners_alone_and_write_nothing_in_the_shop(desk, monkeypatch):
    """Through the whole application, against the golden world: the count reads the shop's orders,
    as the sales figures do, and nothing else is asked of it; a stranger is refused both routes."""
    from experience.harness import TABLET_HEADERS

    asked: list[str] = []
    real = desk.store.mutate

    async def mutate(name, variables):
        asked.append(name)
        return await real(name, variables)

    monkeypatch.setattr(desk.store, "mutate", mutate)
    obj = hoodies(desk.objectives)
    head = dict(TABLET_HEADERS)
    stranger = {"Tailscale-User-Login": "someone@example.com", "X-Forwarded-For": "100.64.0.9"}
    assert (await desk.client.post(f"/objectives/{obj.id}/target", json={"target": 250}, headers=stranger)).status_code == 403
    answer = await desk.client.post(f"/objectives/{obj.id}/target", json={"target": 250}, headers=head)
    assert answer.status_code == 200, answer.text
    assert "count" in answer.json()["card"], "the answer carries the count, whatever the shop said"
    token = answer.json()["undo"]["token"]
    assert (await desk.client.post(f"/objectives/{obj.id}/undo", json={"token": token}, headers=stranger)).status_code == 403
    undone = await desk.client.post(f"/objectives/{obj.id}/undo", json={"token": token}, headers=head)
    assert undone.status_code == 200 and desk.objectives.get(obj.id).number == obj.number
    assert asked == [] and desk.store.mutations_sent == 0 and desk.store.drafts == []


# ------------------------------------------------------------------ the drawing, under Node


@pytest.mark.skipif(NODE is None, reason="node is not installed here")
def test_the_number_shape_under_node():
    """The Number shape on the page's own code (tests/web/objective-number.test.js): the figure and
    the pace in the Mac's words, the chart of dots (ten a dot in total, one a day), Total and Per day
    by double-tap and by button, more or fewer days by pinch, the target dragged a dot at a time with
    Undo, the ring of twenty on the home and the projected day on the horizon, and every word as text."""
    result = subprocess.run(
        [NODE, "--test", str(ROOT / "tests" / "web" / "objective-number.test.js")],
        capture_output=True, text=True, timeout=120, cwd=ROOT,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout
