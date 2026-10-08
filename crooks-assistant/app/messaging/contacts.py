"""Who a thread is with, in CLIVE's own terms: the person card (app/people/store.py) whose
`channels` names the thread's contact, or nobody yet.

Why it exists: a channel knows a contact by an opaque id (WeCom's external_userid) and a
nickname; the owner knows them as "Jessica, our manufacturer". The card is the one place that
says who someone is, so the link lives there, and is made only when the owner says who a thread
is with (message_contact in app/tools/messaging_tools.py).
"""

from __future__ import annotations

from app.messaging.models import Thread
from app.people.store import PeopleError, Person, people


def person_for(thread: Thread) -> Person | None:
    try:
        return people.by_channel(thread.channel_key)
    except PeopleError:
        return None


def name_for(thread: Thread) -> str:
    """How the owner is told who a thread is with: the card's name, or the channel's own name for
    them, or plainly that the channel gave none."""
    person = person_for(thread)
    if person is not None:
        return person.name
    if thread.who:
        return thread.who
    return "someone on WeChat" if thread.route == "kf" else "a WeCom member"


def link(thread: Thread, who: str) -> Person:
    """Link this thread's contact to the card the owner named ("Jessica")."""
    person = people.find(who)
    if person is None:
        raise PeopleError(f"no one called {str(who)[:40]} is on CLIVE's list; add them with person_note first")
    return people.link_channel(person.person_id, thread.channel_key)


def channel_words(thread: Thread) -> str:
    if thread.channel == "wecom":
        return "WeChat" if thread.route == "kf" else "WeCom"
    return thread.channel
