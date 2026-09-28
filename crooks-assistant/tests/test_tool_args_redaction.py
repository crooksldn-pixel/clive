"""A read's arguments on the timeline, before any read has returned a name (round 10, the
residual the turn fixer found in app/tools/dispatch.py).

`tool_requested` is written the moment a call is made, with its arguments. A customer search
carries the name the owner has just said ("orders for Jo Bloggs"), and at that moment no read has
returned that name, so neither the timeline's name set (timeline.note_names) nor the session's
(Session.pii_seen) holds it, and a name has no shape the redactor can find. It went to the
always-on timeline, and to a production recording, as it was said.

Now the owner's own words in a read are written down by their shape — an order number, an id or
an email address as the redactor keeps it, anything else by its length and a digest that is the
same for the same words in this process — and every argument passes the names the conversation's
reads have already returned. Driven through the real dispatcher, the real timeline and the real
recorder mirror, with only the store's answer stood in for.
"""

from __future__ import annotations

import json
import re

import pytest

from app.observability import recorder as recorder_module
from app.observability import timeline as timeline_module
from app.observability.session import TestSessions
from app.observability.timeline import Timeline, read_events
from app.session.models import Session
from app.tools import (  # noqa: F401 - the tools, registered on import as the running app registers them
    authority,
    gmail_tools,
    registry,
    shopify_tools,
    shopify_writes,
)
from app.tools import dispatch as dispatch_module
from app.tools.dispatch import dispatch, loggable_args

SAID = "Rowan Mitcham"          # a name the owner says; no read has returned it yet
KNOWN = "Esther Quarrie"        # a name an earlier read in this conversation returned


@pytest.fixture()
def recording(tmp_path, monkeypatch):
    """A test-session timeline of the process's own, with a production recording as its mirror,
    both writing; the store answers every read with nothing in particular."""
    timeline_module.forget_names()
    store = TestSessions(tmp_path / "logs")
    line = Timeline(store)
    session = line.start("names in searches")
    recordings = recorder_module.Recordings(tmp_path / "logs")
    mirror = recorder_module.Recorder(recordings)
    recording_session = recordings.start("always on")
    line.mirror = mirror
    timeline_module.install(line)

    async def answered(name, args, *, timeout_s):
        return {"count": 0, "customers": [], "orders": []}

    monkeypatch.setattr(registry, "invoke", answered)
    try:
        yield line, store.timeline_path(session), mirror, recordings.timeline_path(recording_session)
    finally:
        timeline_module.install(timeline_module.NullTimeline())
        timeline_module.forget_names()


def _requested(path) -> list[dict]:
    return [e for e in read_events(path) if e.get("kind") == "tool_requested"]


async def test_a_name_the_owner_says_in_a_search_never_reaches_the_timeline_or_a_recording(recording):
    """The residual's case: shopify_find_customer and shopify_find_order for a name nobody has
    returned yet, and a mail search and a words-in-a-thread search with it in. None of the files
    holds any part of the name; each search is its length and a digest."""
    line, test_file, mirror, recording_file = recording
    conversation = Session(session_id="s-names")
    calls = (
        ("shopify_find_customer", {"query": SAID}),
        ("shopify_find_order", {"query": f"{SAID}'s last order"}),
        ("gmail_search", {"query": f"from:{SAID.split()[0].lower()} refund"}),
        ("gmail_find_in_email", {"contains": SAID.upper()}),
    )
    with authority.acting_as(authority.for_owner("owner@example.com")):
        for tool, args in calls:
            answer = await dispatch(tool, args, session=conversation, timeout_s=5)
            assert not answer.startswith("REFUSED"), (tool, answer)
    assert line.flush(timeout_s=5) and mirror.flush(timeout_s=5)
    for path in (test_file, recording_file):
        written = path.read_text(encoding="utf-8")
        for part in (SAID, *SAID.split(), SAID.lower().split()[0]):
            assert part.lower() not in written.lower(), (path.name, part)
    requested = _requested(test_file)
    assert [e["tool"] for e in requested] == [tool for tool, _args in calls]
    shaped = [next(iter(e["args"].values())) for e in requested]
    assert all(re.fullmatch(r"<\d+ chars ~[0-9a-f]{8}>", value) for value in shaped), shaped
    assert shaped[0].startswith(f"<{len(SAID)} chars")
    assert len(_requested(recording_file)) == len(calls), "the recording has the calls, and no name in them"


async def test_identifiers_and_catalogue_words_are_kept_as_they_are(recording):
    """What a report needs of a search is kept: an order's number, an id, an email address as the
    redactor keeps it ([email]), and a product's words, which are the catalogue's."""
    line, test_file, _mirror, _recording_file = recording
    conversation = Session(session_id="s-ids")
    calls = (
        ("shopify_find_order", {"query": "#1930"}),
        ("shopify_find_order", {"query": "CROOKS-1931"}),
        ("shopify_find_customer", {"query": "rowan.mitcham@example.com"}),
        ("shopify_inventory", {"product": "Yard Jeans", "size": "M"}),
    )
    with authority.acting_as(authority.for_owner("owner@example.com")):
        for tool, args in calls:
            await dispatch(tool, args, session=conversation, timeout_s=5)
    assert line.flush(timeout_s=5)
    args = [e["args"] for e in _requested(test_file)]
    assert args == [{"query": "#1930"}, {"query": "CROOKS-1931"}, {"query": "[email]"},
                    {"product": "Yard Jeans", "size": "M"}], args


async def test_the_same_search_is_known_again_and_a_different_one_is_not(recording):
    """The digest lets the report tell a repeated search from a new one (its duplicate-call rule)
    without the words: the same words, however cased, digest alike; other words of the same length
    do not."""
    line, test_file, _mirror, _recording_file = recording
    conversation = Session(session_id="s-again")
    with authority.acting_as(authority.for_owner("owner@example.com")):
        for query in (SAID, SAID.lower(), "Rowan Mitchum"):
            await dispatch("shopify_find_customer", {"query": query}, session=conversation, timeout_s=5)
    assert line.flush(timeout_s=5)
    first, again, other = (e["args"]["query"] for e in _requested(test_file))
    assert first == again and first != other and len(SAID) == len("Rowan Mitchum")


async def test_a_name_an_earlier_read_returned_is_redacted_wherever_it_is_in_the_arguments(recording):
    """The turn's own redaction, applied at the dispatcher without anything from the turn: the
    names this conversation's reads have returned (Session.pii_seen) come out of every argument,
    a product search and a query's filters included."""
    line, test_file, _mirror, _recording_file = recording
    conversation = Session(session_id="s-known")
    conversation.remember_pii(KNOWN)
    with authority.acting_as(authority.for_owner("owner@example.com")):
        await dispatch("shopify_inventory", {"product": f"the hoodie {KNOWN} asked about"}, session=conversation, timeout_s=5)
    assert line.flush(timeout_s=5)
    written = test_file.read_text(encoding="utf-8")
    assert KNOWN not in written and "[name]" in json.dumps(_requested(test_file)[0]["args"])
    # And a structured argument: the owner's words inside it are shaped, the rest kept.
    shaped = loggable_args("commerce_query", {"filters": {"fulfillment": "unfulfilled", "customer": SAID},
                                              "title": f"{SAID}'s orders"})
    assert SAID not in json.dumps(shaped) and "unfulfilled" in shaped["filters"], shaped
    assert re.fullmatch(r"<\d+ chars ~[0-9a-f]{8}>", shaped["title"]), shaped


def test_the_arguments_of_a_change_or_of_a_tool_nobody_has_are_kept_by_length_alone():
    """Unchanged for a write: its text is its length, its ids as they are. And a tool this process
    does not have — a name the model made up — is not known to be a read, so its text is kept the
    same way (it used to be kept as it was said)."""
    note = f"Call {SAID}"
    assert loggable_args("shopify_order_note_append", {"order_id": "gid://shopify/Order/1", "note": note}) == {
        "order_id": "gid://shopify/Order/1", "note": f"<{len(note)} chars>"}
    assert loggable_args("shopify_customer_lookup_by_name", {"customer_id": "gid://shopify/Customer/9", "who": SAID,
                                                             "surname": "Mitcham", "limit": 3}) == {
        "customer_id": "gid://shopify/Customer/9", "who": f"<{len(SAID)} chars>", "surname": "<7 chars>", "limit": 3}
    assert dispatch_module.SPOKEN_ARGS >= {"query", "contains", "sender", "title"}
