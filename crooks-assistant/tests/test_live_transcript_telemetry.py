"""What the record keeps of a `live_transcript` event (round 10, the residual the voice fixer
found in app/routes/observe.py).

The live words' telemetry is how a hold went, never what was said: an outcome and a reason from
web/live-voice.js's own fixed lists (CrooksLiveVoice.OUTCOMES and REASONS, every one a short
lowercase token) and three whole numbers. The page is built to send nothing else, but the route
took any bounded string in `outcome` and `reason` — two thousand characters of whatever a page put
there — and every other allowed field besides. Now the route holds the line itself: a word is kept
only in that shape, a count only as a number, and anything else in the event is dropped. Driven
through the real route, the owner's own device, and the real timeline file.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from app.observability.timeline import read_events
from app.routes import observe
from tests.test_actions_routes import (  # noqa: F401 - `client` is a fixture
    PROXIED,
    client,
    configure,
)

SAID = "Rowan Mitcham, cancel order 1930"


async def _recorded(client, *events: dict) -> list[dict]:  # noqa: F811
    configure(client, local=True)
    started = await client.post("/test-session/start", json={"name": f"live words {uuid.uuid4().hex[:8]}"})
    assert started.status_code == 200, started.text
    response = await client.post("/telemetry", json={"session_id": "phone", "events": list(events)}, headers=PROXIED)
    assert response.status_code == 204
    stopped = (await client.post("/test-session/stop")).json()
    client.runtime.timeline.flush()
    return [e for e in read_events(Path(stopped["path"])) if e.get("source") == "tablet"]


async def test_the_pages_own_words_and_counts_are_kept(client):  # noqa: F811
    kept = await _recorded(client, {"kind": "live_transcript", "outcome": "committed", "reason": "code_1000",
                                    "ms": 420, "partials": 3, "count": 12, "turn_id": "turn_1", "t": 1_790_000_000_000,
                                    "seq": 7})
    assert len(kept) == 1
    event = kept[0]
    assert event["kind"] == "tablet_live_transcript"
    assert {k: event[k] for k in ("outcome", "reason", "ms", "partials", "count", "turn_id", "session_id")} == {
        "outcome": "committed", "reason": "code_1000", "ms": 420, "partials": 3, "count": 12, "turn_id": "turn_1",
        "session_id": "phone"}


async def test_words_in_an_outcome_or_a_reason_and_every_other_field_are_dropped(client):  # noqa: F811
    """Whatever a page sends: a reason that is a sentence, an outcome with a capital or too long,
    words in fields a live_transcript event does not have, counts that are not numbers. None of it
    reaches the record, and the event is still counted, with what was in shape."""
    kept = await _recorded(
        client,
        {"kind": "live_transcript", "outcome": "error", "reason": SAID},
        {"kind": "live_transcript", "outcome": "Rowan", "reason": "x", "ms": "420", "partials": True, "count": -1,
         "message": SAID, "label": SAID, "detail": SAID, "question": SAID, "name": SAID, "code": SAID},
        {"kind": "live_transcript", "outcome": "a" * 25, "reason": "no audio", "ms": 1e14},
        {"kind": "live_transcript", "outcome": {"words": SAID}, "reason": [SAID]},
    )
    assert len(kept) == 4
    assert kept[0].get("outcome") == "error" and "reason" not in kept[0]
    for event in kept[1:]:
        assert "outcome" not in event and "reason" not in event, event
        assert not ({"ms", "partials", "count"} & set(event)), event
    for event in kept:
        assert not ({"message", "label", "detail", "question", "name", "code"} & set(event)), event
        assert "rowan" not in str(event).lower() and "1930" not in str(event), event


async def test_every_other_tablet_event_is_kept_as_before(client):  # noqa: F811
    """The rule is the live words' alone: another kind's reason and message are still kept as the
    allow-list says (bounded, and the timeline's own redaction on the way to disk)."""
    kept = await _recorded(client, {"kind": "exception", "reason": "a tap on the orb", "message": "Cannot read x"})
    assert kept[0]["reason"] == "a tap on the orb" and kept[0]["message"] == "Cannot read x"


def test_the_word_shape_is_the_pages_own():
    """Every word the page's lists hold is a short lowercase token (web/live-voice.js OUTCOMES and
    REASONS on the voice branch): the shape admits all of them, and no sentence."""
    for word in ("committed", "timeout", "cancelled", "no_tap", "provider_error", "time_limit", "http_503",
                 "code_1006", "code_app", "other"):
        assert observe._LIVE_WORD.fullmatch(word), word
    for sentence in ("", "a", "Rowan", "no audio", "error: Rowan", "x" * 25, "café"):
        assert not observe._LIVE_WORD.fullmatch(sentence), sentence
