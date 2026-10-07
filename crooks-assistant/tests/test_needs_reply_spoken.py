"""Asked out loud, "who needs a reply?" draws the queue the Inbox draws, and every row opens.

Why this exists (8 October 2026). Since 28 September every sentence is the model's, and the call
Claude makes for "which customers need replying to?" is the inbox read, `email_query` with no set.
Its result was drawn by the read layer as a count and a table of everyone who had written: rows
nobody could open, with the people already answered among those waiting. That is the screen
`app/families/landings.py` `_waiting_surface` was written to replace for the Inbox landing, back
on the glass the moment the question was spoken instead of tapped. The browser gates found it
(scripts/browser/email.js: "a thread from the work queue opens on a tap :: opened=false").

What it promises: the spoken question and the tapped Inbox draw the same queue, the waiting
threads and no other, longest first; each row's thread is one this conversation was shown, so a
tap opens it; and the table of who wrote is not drawn beside it.
"""

from __future__ import annotations

import pytest

from experience.fixtures import data
from experience.harness import harness

ASKED = "which customers need replying to?"
INBOX = ("email_query", {"days": 30})


@pytest.fixture()
async def stage():
    async with harness(admitted=True) as h:
        yield h


async def test_the_spoken_question_draws_the_queue_and_only_the_queue(stage):
    said = await stage.ask(ASKED, INBOX, reply="Three people are waiting.", session_id="nr-voice")
    assert said.surface_types == ["email_list"], said.surface_types
    card = said.data("email_list")
    assert card.get("title") == "Waiting on a reply"
    rows = [t for t in card.get("threads") or [] if isinstance(t, dict)]
    waiting = {t.thread_id for t in data.world.needs_reply()}
    assert sorted(str(r.get("thread_id")) for r in rows) == sorted(waiting), (rows, waiting)
    assert card.get("count") == len(rows)


async def test_the_spoken_queue_is_the_one_the_inbox_landing_draws(stage):
    said = await stage.ask(ASKED, INBOX, reply="Three people are waiting.", session_id="nr-same-a")
    tapped = await stage.touch("open.area", area="email", session_id="nr-same-b")
    queue = next(s for s in tapped.surfaces if s.get("surface") == "work_queue")
    spoken = [r.get("thread_id") for r in said.data("email_list").get("threads") or []]
    landed = [r.get("thread_id") for r in (queue.get("data") or {}).get("threads") or []]
    assert spoken == landed, (spoken, landed)


async def test_every_row_of_the_spoken_queue_opens_its_thread(stage):
    said = await stage.ask(ASKED, INBOX, reply="Three people are waiting.", session_id="nr-open")
    rows = said.data("email_list").get("threads") or []
    assert rows
    for row in rows:
        opened = await stage.touch("open.entity", session_id="nr-open", kind="email_thread",
                                   ref=str(row["thread_id"]))
        assert opened.raw.get("ok") is True, opened.raw
        assert "email_thread" in opened.surface_types, opened.surface_types


async def test_nobody_waiting_leaves_the_read_layer_to_say_who_wrote():
    from app.families.landings import queue_for_model, waits_in_inbox

    answered = {"scope": "inbox", "days": 30, "rows": [{"customer_name": "A", "needs_reply": False}]}
    assert not waits_in_inbox(answered) and queue_for_model(answered, None) == []
    # A set's correlation is not the inbox, and keeps its own cards.
    assert not waits_in_inbox({"scope": "set", "rows": [{"needs_reply": True}]})
