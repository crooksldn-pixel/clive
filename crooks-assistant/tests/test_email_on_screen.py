"""Ruling 29 (DEC-071): an email may go on a TV when George puts it there.

He holds an email thread (its card or its row) and drops it on one of his screens, or says "put
that email on the office TV": the screen_show tool reads the thread from Gmail the way the
conversation reads it, builds the screen's view of it from that read (app/displays/views.py
email_view), and the screen draws it as it draws every record. Only a thread this conversation was
shown goes up (the gate's issued ids); only the owner puts anything on a screen; the drop's body is
the conversation, the kind and the thread's id, and nothing about the email is in an address or an
attribute. A draft in the thread is not something anybody sent and never goes up. The model, Gmail
and the screen's clock are stand-ins; the app, the door, the route, the dispatcher and the gate are
real."""

from __future__ import annotations

import base64
import json
from unittest.mock import MagicMock

import pytest

from app.clients.gmail import GmailClient
from app.displays import views
from app.people import staff
from app.tools import gmail_tools
from tests.test_displays import pair
from tests.test_screen_paths import MINE, world  # noqa: F401 (the fixture)

THREAD = "18f3a9c2b1d4e5f6"


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def message(mid: str, sender: str, body: str, *, labels=("INBOX",), date="Wed, 7 Oct 2026 09:12:00 +0100") -> dict:
    headers = [{"name": "From", "value": sender}, {"name": "Subject", "value": "Where is my order?"}, {"name": "Date", "value": date}]
    return {"id": mid, "labelIds": list(labels), "payload": {"headers": headers, "mimeType": "text/plain", "body": {"data": b64(body)}}}


MESSAGES = [
    message("m1", "Ana Fixture <ana@example.com>", "Hi,\nmy order 1938 hasn't arrived yet.\nCould you check?"),
    message("m2", "CROOKS <team@crooksldn.com>", "Hi Ana, it left on Monday with Royal Mail.", labels=("SENT",), date="Wed, 7 Oct 2026 10:01:00 +0100"),
    message("m3", "Ana Fixture <ana@example.com>", "Thanks! Still nothing today though.", date="Thu, 8 Oct 2026 08:40:00 +0100"),
    message("m4", "CROOKS <team@crooksldn.com>", "Unsent words George is still writing.", labels=("DRAFT",)),
]


@pytest.fixture()
def mail(monkeypatch):
    fake = MagicMock()
    fake.users().threads().get().execute.return_value = {"messages": MESSAGES}
    client = GmailClient()
    client._service = fake
    monkeypatch.setattr(gmail_tools, "_client", client)
    return client


async def conversation(app, session_id: str = "s1"):
    """His conversation, made by a turn of his own; the thread is one it was shown (a search or the
    thread card issues it — here, the same issue the dispatcher makes)."""
    app.model.script = []
    answer = await app.client.post("/turn", json={"text": "show me Ana's email", "session_id": session_id}, headers=MINE)
    assert answer.status_code == 200
    session = app.runtime.sessions.get(session_id)
    session.issue(THREAD)
    return session


async def drop(app, screen_id: str, **body):
    payload = {"session_id": "s1", "kind": "email_thread", "ref": THREAD, **body}
    return await app.client.post(f"/displays/{screen_id}/show", json=payload, headers=MINE)


def showing(screens, tv):
    return screens.poll(tv["id"], tv["screen_key"])["showing"]


# --------------------------------------------------------------------------- the view


def test_the_screens_view_of_an_email_is_the_newest_messages_as_written_and_never_a_draft():
    thread = {"thread_id": THREAD, "message_count": 6, "awaiting_reply": True, "messages": [
        {"from": "Ana Fixture", "from_email": "ana@example.com", "date": "d1", "subject": "Hello", "body": "one", "outbound": False},
        {"from": "CROOKS", "date": "d2", "subject": "Re: Hello", "body": "two", "outbound": True},
        {"from": "Ana Fixture", "date": "d3", "subject": "Re: Hello", "body": "three\nlines", "outbound": False},
        {"from": "CROOKS", "date": "d4", "subject": "Re: Hello", "body": "four", "outbound": True},
        {"from": "Ana Fixture", "date": "d5", "subject": "Re: Hello", "body": "five " + "x" * 5000, "outbound": False},
        {"from": "CROOKS", "date": "d6", "subject": "Re: Hello", "body": "a draft", "outbound": True, "draft": True},
    ]}
    view = views.email_view(thread)
    assert view["kind"] == "email" and view["ref"] == THREAD and view["title"] == "Re: Hello"
    mail = view["email"]
    assert mail["with"] == "Ana Fixture" and mail["count"] == 6 and mail["waiting"] is True and mail["earlier"] == 1
    assert [m["body"][:5] for m in mail["messages"]] == ["two", "three", "four", "five "], "the newest four, never the draft"
    assert mail["messages"][1]["body"] == "three\nlines", "a line break is kept"
    assert len(mail["messages"][-1]["body"]) <= views.MAX_EMAIL_BODY and mail["messages"][0]["ours"] is True
    assert len(json.dumps(view)) < views.MAX_VIEW_BYTES


# --------------------------------------------------------------------------- held and dropped


async def test_an_email_he_drops_on_a_screen_goes_up_and_the_tv_draws_it_from_clives_read(world, mail):  # noqa: F811 - the fixture
    screens = world.screens
    tv = pair(screens, "Office TV")
    await conversation(world)
    turns = world.model.turns
    answer = await drop(world, tv["id"])
    assert answer.status_code == 200, answer.text
    assert answer.json() == {"ok": True, "screen": "Office TV", "screen_id": tv["id"], "showing": "Where is my order?", "on": True}
    assert world.model.turns == turns, "a drop is a tap: no model is asked"
    up = showing(screens, tv)
    assert up["kind"] == "email" and up["ref"] == THREAD and up["title"] == "Where is my order?"
    assert set(up["email"]) <= {"with", "count", "waiting", "messages", "earlier"}
    bodies = [m["body"] for m in up["email"]["messages"]]
    assert bodies == ["Hi,\nmy order 1938 hasn't arrived yet.\nCould you check?", "Hi Ana, it left on Monday with Royal Mail.", "Thanks! Still nothing today though."]
    assert "Unsent words" not in json.dumps(up), "a draft never goes up"
    assert up["email"]["messages"][1]["ours"] is True and up["email"]["with"] == "Ana Fixture"
    # The TV itself, with its own cookie, through the door: the same view, by its key in a cookie, and
    # nothing about the email in the address it asks.
    polled = await world.client.get(f"/displays/{tv['id']}?v=-1", headers={**MINE, "Cookie": f"clive_screen={tv['screen_key']}"})
    assert polled.status_code == 200 and polled.json()["showing"]["email"]["messages"][-1]["body"].startswith("Thanks!")
    # His remote names it and how many messages are up; the words stay on the screen.
    remote = screens.remote(tv["id"])
    pane = remote["panes"][0]
    assert pane["kind"] == "email" and pane["email"] == {"with": "Ana Fixture", "messages": 3}
    assert "Royal Mail" not in json.dumps(remote)


async def test_his_spoken_request_puts_up_the_same_email(world, mail):  # noqa: F811 - the fixture
    screens = world.screens
    tv = pair(screens, "Office TV")
    await conversation(world)
    world.model.script = [("screen_show", {"screen": "Office TV", "thread_id": THREAD})]
    answer = await world.client.post("/turn", json={"text": "put that email on the office TV", "session_id": "s1"}, headers=MINE)
    assert answer.status_code == 200
    up = showing(screens, tv)
    assert up["kind"] == "email" and len(up["email"]["messages"]) == 3


async def test_an_email_this_conversation_was_not_shown_never_goes_up(world, mail):  # noqa: F811 - the fixture
    screens = world.screens
    tv = pair(screens, "Office TV")
    app = world
    app.model.script = []
    await app.client.post("/turn", json={"text": "hello", "session_id": "s1"}, headers=MINE)
    answer = await drop(world, tv["id"])
    assert answer.status_code == 403 and answer.json()["code"] == "not_issued"
    assert "That email wasn't shown in this conversation" in answer.json()["detail"]
    assert showing(screens, tv) is None
    shaped = await drop(world, tv["id"], ref="gid://shopify/Order/1938")
    assert shaped.status_code == 403 and showing(screens, tv) is None, "an order's id is not a thread"


async def test_a_thread_with_only_a_draft_in_it_puts_nothing_up(world, monkeypatch):  # noqa: F811 - the fixture
    fake = MagicMock()
    fake.users().threads().get().execute.return_value = {"messages": [MESSAGES[3]]}
    client = GmailClient()
    client._service = fake
    monkeypatch.setattr(gmail_tools, "_client", client)
    tv = pair(world.screens, "Office TV")
    await conversation(world)
    answer = await drop(world, tv["id"])
    assert answer.status_code == 409 and "only a draft" in answer.json()["detail"] and showing(world.screens, tv) is None


def test_the_team_cannot_put_anything_on_a_screen():
    assert not {name for name in staff.TOOLS if name.startswith("screen_")}, "screens stay the owner's alone"
