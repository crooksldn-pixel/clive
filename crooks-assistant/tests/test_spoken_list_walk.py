"""A list he asks for out loud is walked with Next and Previous, as the Orders icon's list is.

The checker's defect 1 (night of 7-8 October 2026): since every sentence became the model's
(28 September), "show me today's orders" drew the list and Next answered "There is no list open to
move through", while the same list opened from the Orders icon could be walked ("#1927. 1 of 3.").
The answer's own list now opens the walk the landing opens (`app/routes/turn.py`
`_walk_what_was_listed`, over `app/families/landings.py` `_open_workflow`), decided from the
cards the answer drew and never from the words.

The checker branch held the same walk from the other side (review note N2, 8 October): the Orders
icon's walk as it works, Home from a spoken list, and Next then Back on a spoken list, which it
marked as a STRICT expected failure until flow's fix landed. The browser gates hold the same walk
(scripts/browser/experience.js and touch.js). The waiting queue asked for out loud ("which customers
need replying to?") had the same gap, which the review of the checker branch noted: its rows
open, but Next did nothing, while the Inbox icon's queue walks. It is held the same way.

Scripted through the real gate and presenters on the golden world (`experience/harness.py`): what
is held is what the Mac does with the calls, not that Claude would make them.
"""

from __future__ import annotations

import re

import pytest

from app import progressive
from experience.harness import harness, todays_orders_reads

LIST = "show me today's orders"
QUEUE = "which customers need replying to?"
INBOX = ("email_query", {"days": 30})
DEFECT = ("KNOWN DEFECT spoken-list-walk: a list asked for out loud opens no walk "
          "(checker defect 1; flow is fixing it). Passing? Delete this mark.")


@pytest.fixture()
async def world():
    progressive.reset()
    async with harness(admitted=True) as h:
        yield h
    progressive.reset()


async def test_today_s_orders_asked_for_out_loud_are_walked_with_next(world):
    said = await world.list_todays_orders(session_id="walk")
    assert [i["type"] for i in said.surfaces] == ["order_list"], said.surface_types
    workflow = said.raw["branch"]["workflow"]
    total = len(said.surfaces[0]["data"]["orders"])
    assert workflow and workflow["total"] == total and total >= 1, workflow
    first = await world.touch("workflow.next", session_id="walk")
    assert first.raw["ok"] is True, first.raw
    assert re.fullmatch(rf"#\d+\. 1 of {total}\.", first.raw["answer"]), first.raw["answer"]
    number = first.raw["answer"].split(".")[0]
    orders = [i for i in first.surfaces if i["type"] in ("order", "order_workspace")]
    assert orders, first.surface_types
    assert number.lstrip("#") in str(orders[0]["data"].get("order_number") or orders[0]["data"].get("title")), orders[0]["data"]
    back = await world.touch("workflow.previous", session_id="walk")
    assert back.raw["answer"] == "That is the first one.", back.raw


async def test_the_summary_list_walks_the_set_its_read_made(world):
    said = await world.ask("what orders came in today", ("commerce_summary", {"task": "order_list", "period": "today"}),
                           session_id="summary", reply="Today's orders.")
    (card,) = [i for i in said.surfaces if i["type"] == "summary_list"]
    workflow = said.raw["branch"]["workflow"]
    assert workflow and workflow["set_id"] == card["data"]["set_id"], (workflow, card["data"].get("set_id"))
    moved = await world.touch("workflow.next", session_id="summary")
    assert moved.raw["ok"] is True and re.fullmatch(r"#\d+\. 1 of \d+\.", moved.raw["answer"]), moved.raw


async def test_one_record_answered_opens_no_walk(world):
    said = await world.open_order(1940, session_id="record")
    assert said.raw["branch"]["workflow"] is None, said.raw["branch"]["workflow"]
    refused = await world.touch("workflow.next", session_id="record")
    assert refused.raw["ok"] is False and refused.raw["code"] == "no_set"


async def test_the_orders_icon_s_list_walks_with_next_and_back(world):
    opened = await world.touch("open.area", area="orders", session_id="walk-icon")
    assert "order_list" in opened.surface_types, opened.surface_types
    step = await world.touch("workflow.next", session_id="walk-icon")
    assert step.raw.get("ok") is True and re.search(r"\b1 of \d+\b", str(step.raw.get("answer"))), step.raw
    back = await world.touch("navigation.back", session_id="walk-icon")
    assert "order_list" in back.surface_types, back.surface_types
    assert ((back.raw.get("changed") or {}).get("workspace") or {}).get("kind") == "list", back.raw.get("changed")


async def test_home_from_a_list_asked_for_out_loud_is_the_orders_landing(world):
    said = await world.ask(LIST, *todays_orders_reads(), reply="Today's orders.", session_id="walk-said-home")
    assert said.data("order_list").get("orders"), said.surface_types
    home = await world.touch("navigation.home", session_id="walk-said-home")
    changed = home.raw.get("changed") or {}
    assert "order_list" in home.surface_types and changed.get("home") is True and changed.get("area") == "orders", home.raw


@pytest.mark.xfail(strict=True, reason=DEFECT)
async def test_a_list_asked_for_out_loud_walks_with_next_and_back(world):
    said = await world.ask(LIST, *todays_orders_reads(), reply="Today's orders.", session_id="walk-said")
    rows = said.data("order_list").get("orders") or []
    step = await world.touch("workflow.next", session_id="walk-said")
    assert step.raw.get("ok") is True, step.raw
    assert re.search(rf"\b1 of {len(rows)}\b", str(step.raw.get("answer"))), (step.raw.get("answer"), len(rows))
    back = await world.touch("navigation.back", session_id="walk-said")
    assert "order_list" in back.surface_types, back.surface_types
    assert ((back.raw.get("changed") or {}).get("workspace") or {}).get("kind") == "list", back.raw.get("changed")


async def test_the_inbox_icon_s_queue_walks_with_next(world):
    await world.touch("open.area", area="email", session_id="walk-inbox")
    step = await world.touch("workflow.next", session_id="walk-inbox")
    assert step.raw.get("ok") is True and re.search(r"\b1 of \d+\b", str(step.raw.get("answer"))), step.raw
    assert "email_thread" in step.surface_types, step.surface_types


@pytest.mark.xfail(strict=True, reason=DEFECT)
async def test_the_waiting_queue_asked_for_out_loud_walks_with_next(world):
    said = await world.ask(QUEUE, INBOX, reply="Three people are waiting.", session_id="walk-queue")
    rows = said.data("email_list").get("threads") or []
    step = await world.touch("workflow.next", session_id="walk-queue")
    assert step.raw.get("ok") is True, step.raw
    assert re.search(rf"\b1 of {len(rows)}\b", str(step.raw.get("answer"))), (step.raw.get("answer"), len(rows))
    assert "email_thread" in step.surface_types, step.surface_types
