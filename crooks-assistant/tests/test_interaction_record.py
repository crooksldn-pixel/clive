"""The interaction record, and CLIVE looking at it (George, 2 October 2026).

    "make sure clive is able to really record what it's doing"
    "I can go 'why aren't you showing me bulk actions?' and it can think about it."
    "When I was doing refunds I had to spell names out letter by letter."

Held here:
  * it is on by default, has a switch, and says itself apart from a test session;
  * it is bounded by days and by a day's size, and private on disk;
  * hostile customer data never reaches the file raw — by the timeline's own rules, with the
    owner's words and the cards' titles by their shape unless he chooses otherwise;
  * every turn carries its decision trace: which rule of app/screen.py chose the screen and which
    tool drew which card;
  * friction is found mechanically on two fixture timelines — the spam archive George described
    (taps that did nothing, a screen that changed by itself, archives refused and retried, a bulk
    request answered without a bulk card) and the refund where names were spelled letter by letter;
  * interaction_review answers what is on the screen word for word from what was drawn, why, where
    the friction was, and gives an excerpt a build request may carry — with no customer in it;
  * through the real routes: /turn writes the record, /telemetry is kept with no test session
    running, /health and /test-session/status say it is on without calling it a test.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from app import screen
from app.actions.ledger import NullLedger
from app.main import app
from app.observability import friction, interactions
from app.observability import timeline as timeline_module
from app.observability.interactions import InteractionDays, InteractionRecord
from app.observability.session import TestSessions
from app.observability.timeline import Timeline, read_events
from app.providers.base import ToolCall, TurnResult
from app.session.manager import SessionManager
from app.session.models import Session
from app.tools import (  # noqa: F401 — the bulk tools, as app/runtime.py registers them
    batch_tools,
    gmail_writes,
    interaction_tools,
    registry,
)
from app.tools.context import CURRENT_SESSION
from app.tools.dispatch import dispatch
from tests.fake_credentials import shopify_token
from tests.test_actions_routes import PROXIED, FakeProvider, configure

# A customer as hostile as a customer can be: a name the record has been told, an email address,
# a phone number, a postcode, a street, a card number and a credential in one place.
# The credential is assembled by the shared helper, as every fake credential in the tests is.
NAME = "Zoe Quill"
TOKEN = shopify_token("interaction-record")
HOSTILE = (f"{NAME} <zoe.quill@example.com> 07700 900123, 14 Ravensbourne Road SE6 4XY, "
           f"card 4111 1111 1111 1111, token {TOKEN}")
RAW = ("Zoe", "Quill", "zoe.quill@example.com", "07700 900123", "SE6 4XY", "4111 1111 1111 1111", TOKEN)


class Clock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def _fresh():
    timeline_module.forget_names()
    yield
    interactions.install(None)
    timeline_module.forget_names()


def record_in(tmp_path: Path, *, clock: Clock | None = None, words: bool = False, day_bytes: int = 16 * 1024 * 1024,
              keep_days: int = 7) -> InteractionRecord:
    clock = clock or Clock(time.time())
    days = InteractionDays(tmp_path / "logs", keep_days=keep_days, clock=clock)
    return interactions.install(InteractionRecord(days, clock=clock, keep_words=words, day_bytes=day_bytes))


def on_disk(record: InteractionRecord) -> str:
    record.flush()
    return "".join(p.read_text(encoding="utf-8") for p in sorted(record.sessions.root.glob("ts-*.jsonl")))


# ------------------------------------------------------------------------ on, off and apart


def test_it_is_on_unless_switched_off_and_never_called_a_test_session(monkeypatch, tmp_path):
    from config.settings import Settings

    monkeypatch.delenv("CROOKS_INTERACTION_RECORD", raising=False)
    settings = Settings(_env_file=None)
    assert settings.interaction_record is True, "always recording is the default"
    assert (settings.interaction_record_keep_days, settings.interaction_record_day_mb, settings.interaction_record_words) == (7, 16, False)
    monkeypatch.setenv("CROOKS_INTERACTION_RECORD", "false")
    assert Settings(_env_file=None).interaction_record is False, "the switch turns it off"

    record = InteractionRecord.from_settings(settings.model_copy(update={"log_dir": tmp_path}))
    assert record.active_id and record.active_id.endswith("-always-on") and record.sessions.root == tmp_path / "interactions"
    main = Timeline(TestSessions(tmp_path))
    main.mirror = interactions.install(record)
    assert main.own is None and interactions.on(main), "the record's day is not a test session"
    test = main.start("a real test")
    assert not interactions.on(main) and main.active.test_session_id == test.test_session_id
    main.stop()
    with pytest.raises(RuntimeError):
        record.sessions.start("by name")


# ---------------------------------------------------------------------------------- bounds


def test_it_is_bounded_by_days_and_by_a_days_size_and_private(tmp_path):
    clock = Clock()
    record = record_in(tmp_path, clock=clock, day_bytes=64 * 1024, keep_days=2)
    first = record.active_id
    for i in range(400):
        record.emit("tool_finished", tool="gmail_search", ok=True, ms=12.0, note="x" * 300, i=i)
    record.flush()
    path = record.sessions.timeline_path(first)
    lines = path.read_text().splitlines()
    assert path.stat().st_size <= 64 * 1024 + 200, "a day stops growing at its size"
    assert json.loads(lines[-1])["kind"] == "timeline_full" and json.loads(lines[-1])["max_bytes"] == 64 * 1024
    assert oct(path.stat().st_mode & 0o777) == "0o600" and oct(record.sessions.root.stat().st_mode & 0o777) == "0o700"
    assert interactions.private(path)
    # Day by day: a day older than the keep is deleted when the next one starts.
    os.utime(path, (clock.now, clock.now))
    seen = [first]
    for _ in range(3):
        clock.now += 86_400
        record.sessions._checked_at = -1.0
        record.emit("tool_finished", tool="gmail_search", ok=True)
        record.flush()
        seen.append(record.active_id)
        os.utime(record.sessions.timeline_path(record.active_id), (clock.now, clock.now))
    kept = {p.name.removesuffix(".jsonl") for p in record.sessions.days()}
    assert first not in kept and seen[-1] in kept and len(kept) <= 3, kept


# ------------------------------------------------------------------------------- redaction


def _hostile_turn(record: InteractionRecord, session_id: str = "s1") -> None:
    timeline_module.note_names([NAME])
    ui = [
        {"type": "customer", "data": {"customer_id": "gid://shopify/Customer/9", "name": NAME, "email": "zoe.quill@example.com"}},
        {"type": "email_list", "data": {"title": f"Emails from {NAME}", "threads": [
            {"thread_id": "abc123", "subject": HOSTILE, "from": NAME, "snippet": HOSTILE,
             "actions": [{"id": "email_archive", "label": "Archive", "enabled": True}]}]}},
    ]
    calls = [ToolCall(name="shopify_find_customer", args={"query": NAME}, ok=True, duration_ms=300.0,
                      result={"customers": [{"customer_id": "gid://shopify/Customer/9", "name": NAME}]}),
             ToolCall(name="gmail_search", args={"query": HOSTILE}, ok=True, duration_ms=900.0,
                      result={"threads": [{"thread_id": "abc123", "subject": HOSTILE}]})]
    interactions.after_turn(
        session_id=session_id, turn_id="turn_hostile", question=f"show me emails from {HOSTILE}",
        transcript={"raw_text": f"show me emails from {HOSTILE}", "text": f"show me emails from {HOSTILE}"},
        answer=f"Two emails from {HOSTILE}.", ui=ui, calls=calls, screen_state="new", carry=["nothing_up"],
        error_kind=None, abandoned=False, timings={"total": 2400.0})
    record.emit("tool_requested", session_id=session_id, turn_id="turn_hostile", tool="gmail_search", args={"query": HOSTILE})
    record.emit("tablet_render", source="tablet", session_id=session_id, screen="context",
                cards=[{"type": "email_list", "ref": "abc123"}], question=HOSTILE, label=HOSTILE)


def test_hostile_customer_data_never_reaches_the_file_raw(tmp_path):
    record = record_in(tmp_path)
    _hostile_turn(record)
    text = on_disk(record)
    assert "interaction_turn" in text and "tablet_render" in text
    for raw in RAW:
        assert raw not in text, f"{raw!r} reached the interaction record"
    turn = next(e for e in read_events(record.sessions.timeline_path(record.active_id)) if e["kind"] == "interaction_turn")
    # The owner's words and the titles by their shape; the structure as it was.
    assert turn["question"].startswith("<") and turn["heard"].startswith("<") and turn["answer"].startswith("<")
    assert all(t.startswith("<") or t == "" for t in turn["titles"])
    assert [c["type"] for c in turn["cards"]] == ["customer", "email_list"]
    assert turn["cards"][1]["drawn_by"] == ["gmail_search"] and turn["cards"][1]["rows"] == 1
    assert turn["cards"][1]["actions"] == [{"control": "email_archive", "enabled": True, "on_rows": 1}]
    # In memory, while the process lives, the words are there to answer "why did you show me that".
    held = record.recent.turns("s1")[0]
    assert NAME in held["question"] and held["cards"][1]["title"] == f"Emails from {NAME}"


def test_with_his_words_kept_they_are_still_scrubbed_of_names_and_contact_details(tmp_path):
    record = record_in(tmp_path, words=True)
    _hostile_turn(record)
    text = on_disk(record)
    for raw in RAW:
        assert raw not in text, f"{raw!r} reached the interaction record with words kept"
    turn = next(e for e in read_events(record.sessions.timeline_path(record.active_id)) if e["kind"] == "interaction_turn")
    assert turn["question"].startswith("show me emails from [name]") and "[email]" in turn["question"]
    assert turn["titles"][1] == "Emails from [name]"


# -------------------------------------------------------------------------- decision traces


class Half:
    """A half of the orb, as app/screen.py reads one."""

    def __init__(self, cards: list[dict], at: float | None = None) -> None:
        self.last_ui = cards
        self.last_at = at if at is not None else time.time()


ORDER_1938 = {"type": "order", "data": {"order_id": "gid://shopify/Order/1938", "order_number": "#1938", "detail": True}}
ORDER_1940 = {"type": "order", "data": {"order_id": "gid://shopify/Order/1940", "order_number": "#1940", "detail": True}}


def test_the_screen_rule_says_which_way_it_decided_and_decides_as_before():
    why: list[str] = []
    assert screen.carry([ORDER_1940], branch=Half([]), why=why) == [ORDER_1940] and why == ["nothing_up"]
    why = []
    assert screen.carry([ORDER_1940], branch=Half([ORDER_1938]), why=why) == [ORDER_1940] and why == ["new_subject"]
    why = []
    kept = screen.carry([], branch=Half([ORDER_1938]), why=why)
    assert why == ["continued"] and kept and kept[0].get("kept") is True
    why = []
    assert screen.carry([], branch=Half([ORDER_1938]), named={"1940"}, why=why) == [] and why == ["named_elsewhere"]
    # And with no `why`, nothing is different.
    assert screen.carry([ORDER_1940], branch=Half([ORDER_1938])) == [ORDER_1940]


def _trace(record, **kw):
    base = dict(session_id="s1", turn_id=kw.pop("turn_id", "turn_x"), question=kw.pop("question", "show me order 1940"),
                transcript=None, answer="Order 1940.", ui=[], calls=[], screen_state="new", carry=[], error_kind=None,
                abandoned=False, timings={"total": 1000.0})
    base.update(kw)
    interactions.after_turn(**base)
    record.flush()
    return [e for e in read_events(record.sessions.timeline_path(record.active_id)) if e["kind"] == "interaction_turn"][-1]


def test_every_turn_says_why_its_screen_is_what_it_is(tmp_path):
    record = record_in(tmp_path)
    read = ToolCall(name="shopify_order_detail", args={}, ok=True, duration_ms=200.0,
                    result={"order_id": "gid://shopify/Order/1940", "order_number": "#1940"})
    turn = _trace(record, ui=[ORDER_1940], calls=[read], carry=["new_subject"])
    assert turn["why"]["rule"] == "new" and turn["why"]["carry"] == "new_subject" and "new subject" in turn["why"]["says"]
    assert turn["cards"][0]["drawn_by"] == ["shopify_order_detail"] and turn["cards"][0]["numbers"] == ["1940"]
    assert turn["named_orders"] == ["1940"]

    kept = {**ORDER_1938, "kept": True}
    staged = ToolCall(name="shopify_order_note_append", args={}, ok=True, proposal_id="prop_1")
    note = {"type": "confirmation", "data": {"proposal_id": "prop_1", "title": "Add a note"}}
    turn = _trace(record, ui=[note, kept], calls=[staged], screen_state="kept", carry=["continued"], question="add a note")
    assert turn["why"]["rule"] == "carried" and "stayed" in turn["why"]["says"] and turn["why"]["staged"] == ["shopify_order_note_append"]
    assert [c.get("drawn_by") for c in turn["cards"]] == [["shopify_order_note_append"], ["(already on screen)"]]

    turn = _trace(record, ui=[], calls=[read], screen_state="cleared", carry=["read_elsewhere"], question="where is 1940")
    assert turn["why"]["rule"] == "cleared" and "not showing" in turn["why"]["says"] and turn["why"]["read_for_words"] == ["shopify_order_detail"]
    turn = _trace(record, ui=[], calls=[ToolCall(name="close_screen", args={}, ok=True, result={})], screen_state="cleared",
                  question="close that")
    assert turn["why"]["rule"] == "closed"
    failed = ToolCall(name="shopify_inventory", args={}, ok=False, error="rate limited")
    error = {"type": "error", "data": {"service": "shopify", "title": "Shopify did not answer"}}
    turn = _trace(record, ui=[error], calls=[failed], error_kind=None, question="stock of the jeans")
    assert turn["cards"][0]["drawn_by"] == ["shopify_inventory"] and turn["tools"] == [{"tool": "shopify_inventory", "ok": False}]
    turn = _trace(record, ui=[], abandoned=True, screen_state="kept")
    assert turn["why"]["rule"] == "abandoned"
    turn = _trace(record, ui=[], error_kind="timeout", screen_state="cleared")
    assert turn["why"]["rule"] == "error" and "timeout" in turn["why"]["says"]


# ----------------------------------------------------------------- what was said, read once


def test_a_name_spelled_letter_by_letter_is_counted_and_ordinary_speech_is_not():
    assert friction.spelled("refund the order for Z O E, Q U I L L") == (2, 8)
    assert friction.spelled("refund zed-O-E quill") == (1, 3)
    assert friction.spelled("it's Q-U-I double L") == (1, 5)
    assert friction.spelled("Q as in queen, U as in uniform") == (1, 2)
    for ordinary in ("I see you are busy", "show me order 1940", "a b", "why are you showing me that", "plan B is fine"):
        assert friction.spelled(ordinary) == (0, 0), ordinary
    signals = friction.speech_signals("refund zoe quill", "no, I said Z O E", previous=("turn_1", "refund zoe quill", 100.0), now=130.0)
    assert signals["spelled_runs"] == 1 and signals["correction"] is True and signals["changed"] is True
    again = friction.speech_signals("refund zoe quill please", "refund zoe quill please", previous=("turn_1", "refund zoe quill", 100.0), now=130.0)
    assert again["repeat_of"] == "turn_1" and again["repeat_ratio"] >= 0.75
    assert friction.expectations("who needs a reply") == ["needs_reply"]
    assert friction.expectations("archive all of them") == ["bulk"]
    assert friction.expectations("why aren't you showing me bulk actions?") == ["bulk", "review"]
    assert friction.expectations("what's on my screen") == ["review"]
    assert friction.expectations("close that") == ["close"]
    assert friction.named_orders("refund order 1940 and #1938") == ["1940", "1938"]


# ------------------------------------------------------------------- the fixture timelines


def spam_archive(record: InteractionRecord, clock: Clock, session_id: str = "tab1") -> None:
    """George's afternoon: the spam pulled up, the archive buttons that did not work, the screen
    that changed by itself, and "archive all of them" answered with the same list again."""
    t0 = clock.now

    def tablet(kind: str, at: float, **fields) -> None:
        clock.now = at
        record.emit(f"tablet_{kind}", source="tablet", session_id=session_id, t=int(at * 1000), **fields)

    spam = {"type": "email_list", "data": {"title": "Spam", "threads": [
        {"thread_id": f"t{i}", "subject": "WIN NOW", "actions": [{"id": "email_archive", "label": "Archive", "enabled": True}]}
        for i in range(9)]}}
    search = ToolCall(name="gmail_search", args={}, ok=True, duration_ms=1300.0, result={"threads": [{"thread_id": "t0"}]})
    tablet("turn_submitted", t0)
    clock.now = t0 + 3
    interactions.after_turn(session_id=session_id, turn_id="turn_spam", question="show me the spam in the inbox", transcript=None,
                            answer="Nine spam emails.", ui=[spam], calls=[search], screen_state="new", carry=["nothing_up"],
                            error_kind=None, abandoned=False, timings={"total": 3000.0})
    tablet("turn_response", t0 + 3.1, ms=3100)
    tablet("render", t0 + 3.3, screen="context", cards=[{"type": "email_list", "ref": "spam"}])
    # Archive tapped on a row, again and again: refused twice, then nothing.
    for i, outcome in enumerate(("refused", "refused", "staged", "staged", "staged")):
        tablet("row_action", t0 + 10 + i * 1.5, action="email_archive", status=409 if outcome == "refused" else 200, outcome=outcome)
        if outcome == "refused":
            clock.now = t0 + 10.2 + i * 1.5
            record.emit("row_action", session_id=session_id, action="email_archive", ok=False)
    # The screen changed with nothing asked.
    tablet("render", t0 + 25, screen="context", cards=[{"type": "email_list", "ref": "inbox"}, {"type": "working_set", "ref": "set_1"}])
    # "archive all of them": a model turn that drew the same plain list again.
    tablet("turn_submitted", t0 + 40)
    clock.now = t0 + 49.5
    interactions.after_turn(session_id=session_id, turn_id="turn_all", question="archive all of them", transcript=None,
                            answer="Here are the spam emails.", ui=[spam], calls=[search], screen_state="new",
                            carry=["new_subject"], error_kind=None, abandoned=False,
                            timings={"total": 9500.0, "agent": 8800.0})
    tablet("turn_response", t0 + 49.6, ms=9600)
    tablet("render", t0 + 49.8, screen="context", cards=[{"type": "email_list", "ref": "spam"}])


def refund_spelling(record: InteractionRecord, clock: Clock, session_id: str = "tab1") -> None:
    """The refunds: a name the recogniser could not hear, spelled letter by letter, corrected."""
    t0 = clock.now
    turns = (
        ("turn_r1", "refund zoe kwil's order", "refund zoe kwil's order", []),
        ("turn_r2", "no, I said Zoe Quill", "no, I said Zoe Quill", []),
        ("turn_r3", "Z O E, Q U I L L", "Z O E, Q U I L L", [ORDER_1940]),
    )
    for i, (turn_id, heard, used, ui) in enumerate(turns):
        clock.now = t0 + i * 20
        interactions.after_turn(session_id=session_id, turn_id=turn_id, question=used, transcript={"raw_text": heard, "text": used},
                                answer="", ui=ui, calls=[], screen_state="new" if ui else "cleared", carry=["nothing_up"],
                                error_kind=None, abandoned=False, timings={"total": 2500.0})


def test_the_spam_archive_friction_is_found_and_the_easier_way_named(tmp_path):
    clock = Clock(time.time() - 600)
    record = record_in(tmp_path, clock=clock)
    spam_archive(record, clock)
    clock.now += 5
    found = friction.find(record.window(minutes=30, now=clock.now))
    kinds = [f.kind for f in found]
    assert {"REPEATED_TAP", "ACTION_FAILED", "SCREEN_CHANGED_UNASKED", "MISSING_CAPABILITY", "LONG_WAIT"} <= set(kinds), kinds
    taps = next(f for f in found if f.kind == "REPEATED_TAP")
    assert taps.count == 5 and "email_archive was tapped 5 times" in taps.what and "2 of them were refused" in taps.what
    assert "batch_email_archive" in taps.easier and "one hold instead of 5 taps" in taps.easier
    failed = [f for f in found if f.kind == "ACTION_FAILED"]
    assert len(failed) == 1, "the page's and the Mac's account of one refusal are one finding"
    assert "retried" in failed[0].what and "went through" in failed[0].what
    changed = next(f for f in found if f.kind == "SCREEN_CHANGED_UNASKED")
    assert "nothing asked" in changed.what and changed.turn_id == "turn_spam"
    bulk = next(f for f in found if f.kind == "MISSING_CAPABILITY")
    assert bulk.turn_id == "turn_all" and "batch_email_archive" in bulk.easier
    wait = next(f for f in found if f.kind == "LONG_WAIT")
    assert wait.turn_id == "turn_all" and "9.5 s" in wait.what and "the model and its reads" in wait.what
    assert kinds.index("ACTION_FAILED") < kinds.index("LONG_WAIT"), "most severe first"


def test_the_refund_name_spelling_is_measured_so_the_speech_fix_can_be_targeted(tmp_path):
    clock = Clock(time.time() - 300)
    record = record_in(tmp_path, clock=clock)
    refund_spelling(record, clock)
    events = record.window(minutes=30, now=clock.now + 5)
    found = [f for f in friction.find(events) if f.kind == "SPELLED_OUT"]
    assert [f.turn_id for f in found] == ["turn_r2", "turn_r3"]
    assert "correction" in found[0].what and "2 name(s) spelled out, 8 letters" in found[1].what
    report = friction.speech_report(events)
    assert report["spelled_turns"] == 1 and report["letters_spelled"] == 8 and report["corrections"] == 1
    assert report["voice_turns"] == 3 and report["spelled_in"] == ["turn_r3"]
    assert "Zoe" not in on_disk(record) and "kwil" not in on_disk(record), "measured without keeping the words"


def test_a_request_answered_with_an_unrelated_scene_is_found(tmp_path):
    clock = Clock(time.time() - 100)
    record = record_in(tmp_path, clock=clock)
    plain = {"type": "email_list", "data": {"title": "Inbox", "threads": [{"thread_id": "t1", "subject": "hi"}]}}
    queue = {"type": "email_list", "surface": "work_queue", "data": {"title": "Waiting on a reply", "threads": [{"thread_id": "t1", "subject": "hi"}]}}
    for turn_id, ui in (("turn_plain", plain), ("turn_queue", queue)):
        clock.now += 10
        interactions.after_turn(session_id="s1", turn_id=turn_id, question="who needs a reply", transcript=None, answer="",
                                ui=[ui], calls=[], screen_state="new", carry=["nothing_up"], error_kind=None,
                                abandoned=False, timings={"total": 1000.0})
    found = [f for f in friction.find(record.window(minutes=10, now=clock.now)) if f.kind == "UNRELATED_SCENE"]
    assert [f.turn_id for f in found] == ["turn_plain"] and "no reply state" in found[0].what


def test_a_background_request_failing_on_every_turn_is_said_once_and_never_buries_what_he_did(tmp_path):
    """The voice with no credit fails on every answer. That is one finding for the window, weighed
    below what his own hands met."""
    clock = Clock(time.time() - 400)
    record = record_in(tmp_path, clock=clock)
    for _ in range(6):
        clock.now += 30
        record.emit("tablet_http_error", source="tablet", session_id="tab1", t=int(clock.now * 1000), path="/speak", status=503)
    for i in range(3):
        record.emit("tablet_rail_tap", source="tablet", session_id="tab1", t=int((clock.now + 1 + i) * 1000), action="note", state="enabled")
    found = friction.find(record.window(minutes=30, now=clock.now + 10))
    speak = [f for f in found if f.kind == "ACTION_FAILED"]
    assert len(speak) == 1 and speak[0].count == 6 and "/speak failed (503), 6 times in this window" in speak[0].what
    assert [f.kind for f in found] == ["REPEATED_TAP", "ACTION_FAILED"], "what he did comes first"


# --------------------------------------------------------------------------- the tool itself


async def _review(session: Session, **args) -> dict:
    token = CURRENT_SESSION.set(session)
    try:
        return await interaction_tools.interaction_review(**args)
    finally:
        CURRENT_SESSION.reset(token)


async def test_the_review_says_what_is_on_screen_word_for_word_from_what_was_drawn(tmp_path):
    clock = Clock(time.time() - 600)
    record = record_in(tmp_path, clock=clock)
    spam_archive(record, clock)
    session = Session(session_id="tab1")
    half = session.branch()
    spam = {"type": "email_list", "data": {"title": "Spam", "threads": [
        {"thread_id": "t1", "subject": "WIN A PRIZE NOW", "from": "Prize Desk",
         "actions": [{"id": "email_archive", "label": "Archive", "enabled": True}]}]}}
    half.shown([spam], "Nine spam emails.", "show me the spam")
    out = await _review(session, minutes=30, about="bulk actions")
    shown = out["on_screen"][0]
    assert shown["focused"] is True and shown["cards"][0]["title"] == "Spam"
    assert shown["cards"][0]["rows"]["shows"] == ["WIN A PRIZE NOW · Prize Desk"], "word for word, as drawn"
    assert shown["cards"][0]["actions"] == [{"control": "email_archive", "label": "Archive", "enabled": True, "on_rows": 1}]
    turns = {t["turn_id"]: t for t in out["turns"]}
    assert turns["turn_all"]["asked"] == "archive all of them" and turns["turn_all"]["asked_for"] == ["bulk"]
    assert turns["turn_spam"]["cards"][0] == {"type": "email_list", "drawn_by": ["gmail_search"], "title": "Spam", "rows": 9,
                                              "controls": [{"control": "email_archive", "enabled": True, "on_rows": 9}]}
    assert "nothing was on the screen" in turns["turn_spam"]["why"]
    assert {f["kind"] for f in out["friction"]} >= {"REPEATED_TAP", "ACTION_FAILED", "SCREEN_CHANGED_UNASKED", "MISSING_CAPABILITY"}
    about = out["about"]
    assert about["on_screen_now"] == "not on the screen now"
    assert "batch_email_archive" in [t["tool"] for t in about["tools_that_do_it"]]
    assert all("batch_action" in t["draws"] for t in about["tools_that_do_it"])
    assert "no turn in this window called" in about["called_in_window"] and "one-row actions only" in about["note"]
    assert out["tablet_last_drew"]["cards"] == [{"type": "email_list"}]
    assert out["record"]["on"] is True and out["record"]["words"] == "by their shape"
    assert "submit_engineering_request" in out["to_file"]


async def test_the_excerpt_for_a_build_carries_no_word_said_and_no_name(tmp_path):
    clock = Clock(time.time() - 600)
    record = record_in(tmp_path, clock=clock)
    _hostile_turn(record, session_id="tab1")
    spam_archive(record, clock)
    refund_spelling(record, clock)
    out = await _review(Session(session_id="tab1"), minutes=60)
    text = out["excerpt"]
    for raw in (*RAW, "kwil", "WIN NOW", "show me", "archive all of them"):
        assert raw not in text, f"{raw!r} reached the excerpt"
    assert "turn_spam" in text and "REPEATED_TAP" in text and "batch_email_archive" in text and "SPELLED_OUT" in text
    assert "drew email_list 9 rows by gmail_search controls email_archive" in text


async def test_with_the_record_off_it_still_says_what_is_on_screen_and_says_the_rest_plainly():
    interactions.install(None)
    session = Session(session_id="s1")
    session.branch().shown([ORDER_1940], "Order 1940.", "show me 1940")
    out = await _review(session)
    assert out["on_screen"][0]["cards"][0]["title"] == "#1940"
    assert "CROOKS_INTERACTION_RECORD=false" in out["record"] and "turns" not in out
    nothing = await _review(Session(session_id="s2"))
    assert nothing["on_screen"][0]["nothing"] == "nothing is drawn on this half"


def test_the_tool_is_a_read_on_the_gates_allow_list():
    from app.tools import gate

    assert "interaction_review" in gate._KNOWN_TOOLS and not gate._looks_like_mutation("interaction_review")
    decision = gate.classify("interaction_review", {"minutes": 30, "about": "bulk actions"})
    assert decision.executes and decision.tier.value == "GREEN"
    spec = registry.get("interaction_review")
    assert spec.write is None and spec.batch is None and len(spec.description) <= 600


# ----------------------------------------------------------------- through the real routes


class Looking(FakeProvider):
    """Claude, scripted: the spam, the reply queue asked for and a plain list drawn, then the
    question George asks of it — answered by calling interaction_review through the real gate."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.review = ""

    async def turn(self, session_id: str, text: str) -> TurnResult:
        session = self.runtime.sessions.get_or_create(session_id)
        words = text.split("\n")[1].lower() if text.startswith("[Now:") else text.lower()
        calls: list = []
        if "spam" in words or "reply" in words:
            await dispatch("gmail_search", {"query": "spam"}, session=session, timeout_s=5, calls=calls)
            return TurnResult(text="Nine of them.", tool_calls=calls, session_id=session_id)
        if "bulk" in words:
            self.review = await dispatch("interaction_review", {"minutes": 30, "about": "bulk actions"}, session=session,
                                         timeout_s=5, calls=calls)
            return TurnResult(text="Because no turn staged a bulk archive.", tool_calls=calls, session_id=session_id)
        return TurnResult(text="Noted.", session_id=session_id)


SPAM = {"query": "spam", "count": 2, "threads": [
    {"thread_id": "18f2a9c0b1d2e3f4", "from": NAME, "from_email": "zoe.quill@example.com", "subject": "WIN NOW", "snippet": "click", "likely_bulk": True},
    {"thread_id": "18f2a9c0b1d2e3f5", "from": "Prize Desk", "from_email": "prize@example.com", "subject": "Claim it", "snippet": "now", "likely_bulk": True}]}


@pytest.fixture()
async def client(monkeypatch, tmp_path):
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))
    spec = registry.get("gmail_search")

    async def spam(**_kwargs):
        return json.loads(json.dumps(SPAM))

    monkeypatch.setitem(registry._REGISTRY, "gmail_search", replace(spec, handler=spam))
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = Looking(runtime)
        runtime.actions.ledger = NullLedger()
        runtime.sessions = SessionManager()
        runtime.tests = TestSessions(tmp_path / "logs")
        runtime.timeline = timeline_module.install(Timeline(runtime.tests))
        runtime.timeline.mirror = interactions.install(InteractionRecord(InteractionDays(tmp_path / "logs")))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            c.runtime = runtime
            yield c
        timeline_module.install(timeline_module.NullTimeline())


async def test_through_the_routes_every_turn_and_tap_is_recorded_and_the_tool_reads_it(client):
    configure(client, local=True)
    record = interactions.current()
    health = (await client.get("/health")).json()["observability"]
    assert health == {"test_session": None, "name": None, "recording": record.active_id}, "on, and not called a test"
    status = (await client.get("/test-session/status")).json()
    assert status["active"] is False and status["recording"]["day"] == record.active_id and status["recording"]["keep_days"] == 7

    async def turn(text: str) -> dict:
        response = await client.post("/turn", json={"text": text, "session_id": "tab1"}, headers=PROXIED)
        assert response.status_code == 200, response.text
        return response.json()

    first = await turn("show me the spam")
    assert first["test_session_id"] == record.active_id, "the page keeps its account on through the turn"
    now_ms = int(time.time() * 1000)
    batch = [{"kind": "render", "t": now_ms, "turn_id": first["turn_id"], "screen": "context", "cards": [{"type": "email_list", "ref": "spam"}]}]
    batch += [{"kind": "row_action", "t": now_ms + 1000 + i * 900, "action": "email_archive", "status": 409, "outcome": "refused"} for i in range(4)]
    response = await client.post("/telemetry", json={"session_id": "tab1", "events": batch}, headers=PROXIED)
    assert response.status_code == 204 and response.headers["x-crooks-telemetry"] == str(len(batch)), "kept with no test session running"
    await turn("who needs a reply")
    await turn("why aren't you showing me bulk actions?")
    review = json.loads(client.runtime.provider.review)
    on = review["on_screen"][0]["cards"][0]
    assert on["type"] == "email_list" and on["rows"]["count"] == 2 and on["rows"]["shows"][1] == "Claim it · Prize Desk · now"
    turns = review["turns"]
    assert [t["asked"] for t in turns] == ["show me the spam", "who needs a reply"]
    assert turns[0]["cards"][0]["drawn_by"] == ["gmail_search"] and turns[0]["tools"] == ["gmail_search"]
    kinds = {f["kind"] for f in review["friction"]}
    assert {"REPEATED_TAP", "ACTION_FAILED", "UNRELATED_SCENE"} <= kinds, kinds
    assert "batch_email_archive" in [t["tool"] for t in review["about"]["tools_that_do_it"]]
    record.flush()
    text = "".join(p.read_text() for p in record.sessions.days())
    assert text.count('"kind": "interaction_turn"') == 3 and "tablet_row_action" in text and "tool_finished" in text
    for raw in ("zoe.quill@example.com", "Zoe Quill", "show me the spam", "who needs a reply"):
        assert raw not in text, f"{raw!r} reached the record"
    assert not list((client.runtime.tests.root).glob("ts-*.jsonl")), "no test session was written"
    # A test he starts by name is a test, said as one, with the record running beside it.
    started = (await client.post("/test-session/start", json={"name": "walkthrough"})).json()
    health = (await client.get("/health")).json()["observability"]
    assert health["test_session"] == started["test_session_id"] and health["recording"] == record.active_id
    status = (await client.get("/test-session/status")).json()
    assert status["active"] is True and status["test_session_id"] == started["test_session_id"]
    await turn("show me the spam")
    stopped = (await client.post("/test-session/stop")).json()
    assert stopped["stopped"], "and both were written: the test session and the record"
    client.runtime.timeline.flush()
    assert read_events(Path(stopped["path"])) and record.recent.last("tab1")["question"] == "show me the spam"



# ------------------------------------------------- the independent review's notes (2 October)


async def test_recording_is_said_only_to_the_owner_and_never_turns_the_teams_telemetry_on(client, monkeypatch):
    """/health is public. Its `recording` goes to the owner's own devices only (a team member's or
    a stranger's page gets liveness), a team member's turn never turns the page's telemetry on —
    the door would only refuse its batches — and the pad's own heartbeat says recording, so the
    appliance's bounded account is kept in the record too."""
    from app.routes import health as health_module
    from app.routes import turn as turn_module

    configure(client, local=True)
    record = interactions.current()
    owners = (await client.get("/health", headers=PROXIED)).json()
    assert owners["observability"]["recording"] == record.active_id
    stranger = {"Tailscale-User-Login": "someone@example.com", "X-Forwarded-For": "100.64.0.3"}
    theirs = (await client.get("/health", headers=stranger)).json()
    assert "observability" not in theirs and "recording" not in json.dumps(theirs)
    assert "recording" not in health_module._observability(client.runtime, None), "no request: not said"
    assert turn_module._writing_id(client.runtime.timeline) == record.active_id
    monkeypatch.setattr(turn_module, "_staff_request", lambda: True)
    assert turn_module._writing_id(client.runtime.timeline) is None, "a team member's page is never told"
    beat = (await client.post("/pad/heartbeat", headers=PROXIED, json={"app_version": "0.4.2", "device_model": "SM-T290"})).json()
    assert beat["recording"] is True


def test_the_pages_free_text_is_kept_by_its_shape_in_the_record_and_as_before_in_a_test(tmp_path):
    record = record_in(tmp_path)
    record.emit("tablet_tab", source="tablet", session_id="s1", label=f"{NAME}'s orders", detail="gid://x/1", name="customer")
    record.emit("tablet_render", source="tablet", session_id="s1", cards=[{
        "type": "order", "actions": [{"id": "refund", "enabled": False, "reason": f"Already refunded to {NAME}"}],
        "surface": {"kind": "hold", "state": "unavailable", "reason": "Ships to 14 Ravensbourne Road"}}])
    record.emit("tablet_exception", source="tablet", session_id="s1", message=f"TypeError at {NAME}", file="/static/ui.js")
    record.flush()
    events = {e["kind"]: e for e in read_events(record.sessions.timeline_path(record.active_id)) if e["kind"].startswith("tablet_")}
    assert events["tablet_tab"]["label"].startswith("<") and events["tablet_tab"]["detail"].startswith("<")
    assert events["tablet_tab"]["name"] == "customer", "the card's type is vocabulary and stays"
    card = events["tablet_render"]["cards"][0]
    assert card["actions"][0]["reason"].startswith("<") and card["surface"]["reason"].startswith("<")
    assert card["actions"][0]["id"] == "refund" and card["surface"]["state"] == "unavailable"
    assert events["tablet_exception"]["message"].startswith("<") and events["tablet_exception"]["file"] == "/static/ui.js"
    assert "Quill" not in on_disk(record) and "Ravensbourne" not in on_disk(record)
    # A test session he started by name keeps the page's words, as it always has.
    test = Timeline(TestSessions(tmp_path / "tests"))
    started = test.start("walkthrough")
    test.emit("tablet_tab", source="tablet", label="Items 2", name="order")
    test.stop()
    tab = next(e for e in read_events(test.sessions.timeline_path(started)) if e["kind"] == "tablet_tab")
    assert tab["label"] == "Items 2"


def test_only_a_hash_or_the_word_order_makes_a_number_an_order():
    assert friction.named_orders("send it to 1940 Acacia Avenue by 2026, the card ending 4242") == []
    assert friction.named_orders("refund #1938") == ["1938"]
    assert friction.named_orders("what about orders 1938 and 1940") == ["1938", "1940"]
    assert friction.named_orders("order number 2001, and order no. 2002") == ["2001", "2002"]


def test_a_card_number_typed_without_spaces_never_reaches_the_record(tmp_path):
    from app.logging.turnlog import redact_text

    bare = "4111111111111111"
    assert redact_text(f"card {bare} please") == "card [card] please"
    for kept in ("gid://shopify/Order/4111111111111111", "thread 18f2a9c0b1d2e3f4", "id 1234567890123456", "20260907-225520.webm"):
        assert redact_text(kept) == kept, kept
    record = record_in(tmp_path, words=True)
    interactions.after_turn(session_id="s1", turn_id="turn_card", question=f"refund the order paid with {bare}", transcript=None,
                            answer=f"The card {bare} was refunded.", ui=[], calls=[], screen_state="cleared", carry=[],
                            error_kind=None, abandoned=False, timings={"total": 900.0})
    text = on_disk(record)
    assert bare not in text and "[card]" in text


def test_the_words_held_in_memory_age_out_as_they_are_added_and_the_team_never_pushes_the_owners_out():
    clock = Clock(1_000_000.0)
    recent = interactions.Recent(clock=clock)
    recent.add("owner-tablet", {"turn_id": "turn_o1", "at": clock.now, "question": "show me order 1938"})
    for i in range(30):
        clock.now += 1
        recent.add(f"team-{i}", {"turn_id": f"turn_t{i}", "at": clock.now, "question": "anything to pack"}, team=True)
    assert recent.last("owner-tablet")["turn_id"] == "turn_o1", "thirty of the team's conversations did not push his out"
    assert recent.held() == {"owner": 1, "team": interactions.Recent.CONVERSATIONS}
    clock.now += interactions.Recent.MAX_AGE_S + 5
    recent.add("owner-phone", {"turn_id": "turn_o2", "at": clock.now, "question": "and now"})
    assert recent.held() == {"owner": 1, "team": 0}, "aged out when something was added, not only when read"
