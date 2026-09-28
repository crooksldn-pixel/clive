"""The analyser, held against the session it got wrong.

The Phase 2 live tablet test (`ts-20260910-125946`) produced a report with five misleading
classifications, and the brief names each one. This file rebuilds that session's SHAPE as a
timeline — the same event kinds, the same fields, the same order — and asserts the corrected
reading. Every one of the five is written as a pair: what the September report said, and what
this one says. The first half of each pair is not a comment, it is an assertion, so a
regression that puts the old reading back fails here rather than being discovered on the next
hour with the tablet.

    A   six split-gesture failures reported as STT_ERROR      → GESTURE_COLLISION
    B   "Email correlation missing: never", on a surface       → UI_RELATION_MISSING
        that showed no order
    C   "Potential new actions: none", after three spoken      → the changes named, held
        requests for changes this Mac cannot make                against the capability table
    D   UNFULFILLED_ACTION on "the refund status"              → READ_INTENT, and the
                                                                 disagreement with the router
                                                                 on the record
    E   twenty-seven command events unread                     → read, counted, section 14

The session is read as it was RECORDED. Several of the failures in it are impossible now — an
email thread carries its linked order, two fingers cannot post a turn — and that changes
nothing here: the analyser's job is to say what happened in the hour it is given. What the
capability table decides is the other question, "what should be built", and that is asked of
the table as it stands now: a change with no family is still open, a change whose family
exists is a scope, and neither is reported as the other.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.observability import contract as contract_mod
from app.observability import semantics
from app.observability.report import build_report, intelligence, reconstruct
from app.observability.timeline import read_events

SESSION = "ts-20260910-125946"
ORDER = "gid://shopify/Order/1938"
THREAD = "aa70d3f83dbef06e"
T0 = 1_800_000_000.0
TOOLS = ["shopify_find_order", "shopify_order_detail", "gmail_read_thread", "gmail_search",
         "shopify_refund_create", "shopify_order_note_append", "gmail_draft_reply"]


# --------------------------------------------------------------------------- the fixture


class Tape:
    """A timeline, written the way the Mac and the tablet write one: one JSON object a line,
    every event carrying its clock, its sequence and its session."""

    def __init__(self, session_id: str = SESSION, start: float = T0) -> None:
        self.session_id = session_id
        self.now = start
        self.seq = 0
        self.events: list[dict[str, Any]] = []
        self.add("session_started", name="the live hour", started_at=start)

    def add(self, kind: str, *, source: str = "mac", step: float = 0.1, **fields: Any) -> dict[str, Any]:
        self.now += step
        self.seq += 1
        event = {"ts": round(self.now, 3), "iso": "2026-09-10T12:59:46", "seq": self.seq,
                 "test_session_id": self.session_id, "source": source, "kind": kind}
        event.update({k: v for k, v in fields.items() if v is not None})
        self.events.append(event)
        return event

    def gap(self, seconds: float = 45.0) -> None:
        """Time passing between two things the owner did. The rules that read this timeline
        are windowed in seconds, so a fixture with no pauses in it would prove nothing about
        them: a gesture six minutes before a failed recording did not cause it."""
        self.now += seconds

    def write(self, tmp_path: Path) -> Path:
        self.add("session_stopped", name="the live hour", duration_s=round(self.now - T0, 3))
        path = Path(tmp_path) / f"{self.session_id}.jsonl"
        path.write_text("".join(json.dumps(e) + "\n" for e in self.events), encoding="utf-8")
        return path


def _turn(tape: Tape, turn_id: str, *, conversation: str = "s1", said: str = "", input_: str = "audio") -> str:
    tape.add("turn_started", session_id=conversation, turn_id=turn_id, input=input_, turns_before=0, epoch=1)
    if said:
        tape.add("stt", session_id=conversation, turn_id=turn_id, ok=True, engine="scribe", text=said, raw_text=said, audio_s=1.4)
    return turn_id


def _lane(tape: Tape, turn_id: str, *, lane: str, family: str | None, mutation: bool = False,
          reason: str | None = None, conversation: str = "s1", **signals: Any) -> None:
    """The router's own verdict, exactly as app/routes/turn.py writes it: `intent.public()`
    flattened onto the event, with `signals` as `Signals.as_dict()` — which carries a key only
    when it is truthy, and never the words."""
    marks = {k: v for k, v in signals.items() if v}
    if mutation:
        marks["mutation"] = True
    tape.add("lane", session_id=conversation, turn_id=turn_id, lane=lane, why="", branch_id="br_left",
             family=family, confidence=0.8 if family else 0.0, runner_up=None, reason=reason,
             signals=marks or None)


def _tool(tape: Tape, turn_id: str, tool: str, *, result: dict[str, Any] | None = None,
          outcome: str = "ok", conversation: str = "s1", missing: str = "") -> None:
    call = f"tc_{tape.seq}"
    tape.add("tool_requested", session_id=conversation, turn_id=turn_id, tool_call_id=call, tool=tool, args={}, tier="read")
    tape.add("tool_finished", session_id=conversation, turn_id=turn_id, tool_call_id=call, tool=tool,
             outcome=outcome, ok=outcome in ("ok", "staged"), ms=120.0, result=result, missing_capability=missing or None)


def _finished(tape: Tape, turn_id: str, *, answer: str, ui: list[str] | None = None,
              ui_entities: list[dict[str, Any]] | None = None, error_kind: str | None = None,
              question: str = "", conversation: str = "s1", ms: float = 900.0) -> None:
    tape.add("turn_finished", session_id=conversation, turn_id=turn_id, question=question or None, answer=answer,
             ui=ui or ["assistant"], ui_entities=ui_entities, error_kind=error_kind, ms=ms,
             timings={"total": ms})


def _render(tape: Tape, turn_id: str, cards: list[dict[str, Any]], *, screen: str = "context", conversation: str = "s1") -> None:
    tape.add("tablet_render", source="tablet", session_id=conversation, turn_id=turn_id, screen=screen, cards=cards,
             viewport={"w": 601, "h": 889, "dpr": 1.33}, document={"cards_height": 800, "cards_visible": 800},
             overflow={"long_scroll": False, "clipped": 0}, t=int(tape.now * 1000))


def september(tmp_path: Path) -> Path:
    """The live hour's shape: the six blank turns, the email thread with no order on it, the
    three changes asked for out loud, the read questions that carry a mutation word as a noun,
    and the twenty-seven taps."""
    tape = Tape()

    # A — six times. Two fingers land on the orb, the recorder stops, the recogniser is handed
    # silence. The multitouch is reported by the tablet BEFORE the turn it ruined, and under
    # the previous turn's id, because the page had not been given a new one yet.
    previous = "turn_boot"
    for n in range(6):
        tape.add("tablet_hold", source="tablet", session_id="s1", turn_id=previous, phase="multitouch",
                 fingers=2, target="orb", t=int(tape.now * 1000))
        turn = _turn(tape, f"turn_blank_{n}")
        tape.add("stt", session_id="s1", turn_id=turn, ok=False, engine="scribe",
                 reason="I did not catch any speech there.", audio_s=0.2, audio_bytes=3200)
        _finished(tape, turn, answer="I did not catch that.", error_kind="speech", ms=310.0)
        previous = turn

    # The control for A: the recogniser genuinely could make nothing of it, and no finger is
    # anywhere near — a minute after the last of them. This one stays STT_ERROR, or the new
    # rule would have swallowed the class it is meant to narrow.
    tape.gap(60.0)
    turn = _turn(tape, "turn_mumbled")
    tape.add("tablet_hold", source="tablet", session_id="s1", turn_id=turn, phase="release", ms=2100, outcome="sent",
             t=int(tape.now * 1000))
    tape.add("stt", session_id="s1", turn_id=turn, ok=False, engine="whisper",
             reason="I could not hear that clearly — a bit closer to the microphone.", audio_s=2.1)
    _finished(tape, turn, answer="I could not hear that clearly.", error_kind="speech", ms=2400.0)

    tape.gap()
    # B — the email thread. The correlation is in the turn's own data (the read returned the
    # order the thread is about) and the card drew no order at all.
    turn = _turn(tape, "turn_thread", said="open mia's thread", input_="text")
    _lane(tape, turn, lane="FAST", family="order_email_waiting", email=True, question=True)
    _tool(tape, turn, "gmail_read_thread", result={"thread_id": THREAD, "orders": {"count": 1, "ids": [ORDER]}})
    _finished(tape, turn, answer="Mia is waiting on a reply about a hoodie.", question="open mia's thread",
              ui=["email_thread"], ui_entities=[{"type": "thread", "ref": THREAD}])
    _render(tape, turn, [{"i": 0, "type": "email_thread", "ref": THREAD, "sections": ["Messages", "Waiting"]}])

    # The control for B: the same shape with the strip drawn. The card reports the KINDS it
    # linked to, so this one is not a gap.
    turn = _turn(tape, "turn_thread_linked", said="open david's thread", input_="text")
    _lane(tape, turn, lane="FAST", family="order_email_waiting", email=True, question=True)
    _tool(tape, turn, "gmail_read_thread", result={"thread_id": "bb70d3f83dbef06e", "orders": {"count": 1, "ids": [ORDER]}})
    _finished(tape, turn, answer="David asked about #1938.", question="open david's thread",
              ui=["email_thread"], ui_entities=[{"type": "thread", "ref": "bb70d3f83dbef06e"}])
    _render(tape, turn, [{"i": 0, "type": "email_thread", "ref": "bb70d3f83dbef06e",
                          "sections": ["Messages"], "relations": ["customer", "order"]}])

    tape.gap()
    # C — three changes asked for out loud. Nothing reached a tool: the assistant declined in
    # words, which is exactly why the capability never appeared in a table built from tool
    # calls. The router's verdict is on each one.
    for turn_id, said, answer in (
        ("turn_create_order", "create an order for Mia for a black hoodie",
         "I can't create an order — I can only read them and change ones that exist."),
        ("turn_discount", "create a 15% discount called TEST15",
         "I can't create discount codes."),
        ("turn_credit", "add ten pounds store credit to her account",
         "I can't add store credit."),
    ):
        turn = _turn(tape, turn_id, said=said, input_="text")
        _lane(tape, turn, lane="NORMAL", family=None, mutation=True, reason="asks for a change")
        _finished(tape, turn, answer=answer, question=said)

    # C's other half: a change that WAS asked for and now has a family. This must not be
    # reported as a capability to build.
    said = "add a black medium Convict hoodie to this order"
    turn = _turn(tape, "turn_add_item", said=said, input_="text")
    _lane(tape, turn, lane="NORMAL", family=None, mutation=True, reason="asks for a change")
    _finished(tape, turn, answer="Shopify's order editing changes what the customer owes, so I cannot do it here.",
              question=said)

    tape.gap()
    # D — read questions carrying a mutation word as a noun or a state.
    for turn_id, said in (
        ("turn_refund_status", "what is the refund status on 1938"),
        ("turn_needs_reply", "which customers need replying to"),
        ("turn_unfulfilled", "find an order that has not been fulfilled"),
        ("turn_draft_noun", "is there a draft for that"),
    ):
        turn = _turn(tape, turn_id, said=said, input_="text")
        # The router's own reading of each: "refund" is STRONG and it saw a change; the other
        # three carry SOFT words in a question and it did not.
        _lane(tape, turn, lane="NORMAL" if "refund" in said else "FAST",
              family=None if "refund" in said else "needs_reply",
              mutation="refund" in said, reason="asks for a change" if "refund" in said else None,
              email="repl" in said or "draft" in said, question=True)
        _tool(tape, turn, "shopify_order_detail", result={"order_id": ORDER})
        _finished(tape, turn, answer="Nothing has been refunded on #1938.", question=said,
                  ui=["order"], ui_entities=[{"type": "order", "ref": ORDER}])
        _render(tape, turn, [{"i": 0, "type": "order", "ref": ORDER, "sections": ["Money"]}])

    # D's control: the same word as an instruction. This one IS a change, and nothing staged
    # it, so it keeps UNFULFILLED_ACTION.
    said = "refund them the postage"
    turn = _turn(tape, "turn_refund_them", said=said, input_="text")
    _lane(tape, turn, lane="NORMAL", family=None, mutation=True, reason="asks for a change")
    _finished(tape, turn, answer="Right.", question=said)

    tape.gap()
    # The rest of what §27 asks to be detected, each from something the timeline holds.
    #
    # A read the router placed in no family, asked twice: a possible new READ family, which is
    # a recipe and not a write.
    for n in range(2):
        said = "how many customers do we have today"
        turn = _turn(tape, f"turn_customers_{n}", said=said, input_="text")
        _lane(tape, turn, lane="NORMAL", family=None, reason="no family matched", question=True, period=True)
        _finished(tape, turn, answer="Three customers ordered today.", question=said)
        tape.gap(20.0)

    # A value that had to be exact, typed into the composer because saying it did not work.
    turn = _turn(tape, "turn_dictated", said="write to the supplier about the reprint", input_="text")
    _lane(tape, turn, lane="FAST", family="email_compose_any", mutation=True, email=True)
    tape.add("tablet_compose_field", source="tablet", session_id="s1", turn_id=turn, name="to", chars=27,
             t=int(tape.now * 1000))
    tape.add("tablet_recording_too_short", source="tablet", session_id="s1", turn_id=turn, ms=280,
             t=int(tape.now * 1000))
    _finished(tape, turn, answer="The composer is open.", question="write to the supplier about the reprint",
              ui=["email_compose"])
    tape.gap()

    # The same cross-source read twice: Shopify and Gmail in one turn, which one recipe would do
    # in one pass with the ids issued once.
    for n in range(2):
        said = "has this customer emailed about their order"
        turn = _turn(tape, f"turn_crossed_{n}", said=said, input_="text")
        _lane(tape, turn, lane="NORMAL", family=None, reason="no family matched", email=True, question=True, order=True)
        _tool(tape, turn, "shopify_find_order", result={"orders": {"count": 1, "ids": [ORDER]}})
        _tool(tape, turn, "gmail_search", result={"threads": {"count": 1, "ids": [THREAD]}})
        tape.add("cross_source", session_id="s1", turn_id=turn, set_id=f"ws_{n}", customers=1,
                 counts={"threads": 1}, ms=290.0)
        _finished(tape, turn, answer="Yes, once, three days ago.", question=said,
                  ui=["email_list"], ui_entities=[{"type": "order", "ref": ORDER}])
        _render(tape, turn, [{"i": 0, "type": "email_list", "sections": ["Threads"], "relations": ["order"]}])
        tape.gap(20.0)

    tape.gap()
    # E — the taps. Twenty-seven `command` events, the changes two of them prepared, a row
    # action, and the branch moves of a split conversation.
    names = ["open.entity", "surface.tab", "workflow.next", "navigation.back", "open.area", "voice.bind"]
    for n in range(27):
        name = names[n % len(names)]
        refused = n in (11, 23)
        tape.add("command", session_id="s1", branch_id="br_left", command=name,
                 ok=not refused, code="not_available" if refused else None, ms=9.0 + n,
                 entity="order" if name == "open.entity" else None, replayed=name == "open.entity")
    tape.add("command_stage", session_id="s1", branch_id="br_left", tool="shopify_order_note_append",
             ok=True, proposal_id="pr_1", risk="AMBER", interaction="tap_commit")
    tape.add("row_action", session_id="s1", action="archive", ok=True, proposal_id="pr_2")
    tape.add("branch_forked", session_id="s1", branch_id="br_right", parent_branch_id="br_left")
    tape.add("branch_focused", session_id="s1", branch_id="br_right")
    tape.add("branch_backgrounded", session_id="s1", branch_id="br_right")

    return tape.write(tmp_path)


# --------------------------------------------------------------------------- A


def test_a_a_gesture_that_ended_the_recording_is_not_a_failure_of_speech(tmp_path):
    """SEPTEMBER: six turns, class STT_ERROR, component "speech (Scribe / whisper.cpp)".
    NOW: six turns, class GESTURE_COLLISION, component the tablet's touch handling — and the
    one turn that really was mis-heard keeps STT_ERROR."""
    rec = reconstruct(read_events(september(tmp_path)))
    blank = [rec.turn(f"turn_blank_{n}") for n in range(6)]
    assert all(t is not None for t in blank)

    # The old rule, as the September report ran it: any recording that produced nothing was
    # the recogniser's. Kept here as an assertion so the pair is a test and not a claim.
    old = ["STT_ERROR" for t in blank if (t.stt or {}).get("ok") is False or t.error_kind in ("speech", "empty", "audio_too_large")]
    assert old == ["STT_ERROR"] * 6, "September filed all six under speech"

    for turn in blank:
        assert turn.classes == ["GESTURE_COLLISION"], turn.turn_id
        assert "STT_ERROR" not in turn.classes
        assert any("ended by a gesture" in s and "2 fingers on the orb" in s for s in turn.signals), turn.signals
    fingers = [c for c in rec.collisions if c["what"] == "multitouch"]
    assert len(fingers) == 6, "one per blank turn"
    assert {c["what"] for c in rec.collisions} == {"multitouch", "fork"}, "the split that forked a branch counts too"

    mumbled = rec.turn("turn_mumbled")
    assert mumbled.classes == ["STT_ERROR"], "a genuine mis-hearing is still the recogniser's"
    assert any("closer to the microphone" in s for s in mumbled.signals)


# --------------------------------------------------------------------------- B


def test_b_a_relation_in_the_data_is_not_a_relation_on_the_screen(tmp_path):
    """SEPTEMBER: "Email correlation missing: never" — read from the hydration, which had the
    correlation, while the thread card showed no order at all.
    NOW: UI_RELATION_MISSING on the turn whose card drew no order, and nothing on the turn
    whose card drew the strip."""
    rec, markdown = build_report(september(tmp_path), tools_registered=TOOLS)
    bare, linked = rec.turn("turn_thread"), rec.turn("turn_thread_linked")

    # The old reading: nothing in the hydrations said "email" was unavailable, so the report
    # said the correlation was never missing. That statement is still true of the DATA.
    assert not [t.turn_id for t in rec.turns if any("email" in (h.get("unavailable") or []) for h in t.hydrations)]
    assert "Email correlation missing FROM THE DATA (the hydration could not read it): never." in markdown

    assert "UI_RELATION_MISSING" in bare.classes, bare.classes
    assert any("email_thread surface drew no order" in s and ORDER in s for s in bare.signals), bare.signals
    assert "UI_RELATION_MISSING" not in linked.classes, "the card that drew the strip is not a gap"
    assert f"Email correlation missing FROM THE SURFACE (the card drew no order though the turn held one): {bare.turn_id}." in markdown
    assert "backend data existing is not a visible relationship existing" in markdown


# --------------------------------------------------------------------------- C


def test_c_a_change_asked_for_out_loud_is_a_capability_the_report_names(tmp_path):
    """SEPTEMBER: "Potential new actions: none", because the table counted only capabilities a
    TOOL asked for, and a change the assistant declines in words reaches no tool.
    NOW: the three changes are named, each held against the capability table — and the one
    that has since been built is NOT among them."""
    rec, markdown = build_report(september(tmp_path), tools_registered=TOOLS)
    intel = intelligence(rec, TOOLS)

    # The old table, still computed and still empty for this session: that is the assertion
    # that the September report said "none".
    assert intel["new_actions"] == [], "no tool ever asked for these; the old table could not see them"

    named = {key: (n, state) for key, n, _ids, state, _scope, _what in intel["spoken_capabilities"]}
    # CHANGED IN ROUND 9 (F-03), because the capabilities moved: order creation, discount codes
    # and store credit have all been built since September, as registered families that are
    # READY. The table named them "not built" all the same, so a request for store credit — a
    # live, money-moving write — was reported as a family to build. A READY family is neither a
    # build nor a grant, so none of the three is named now, exactly as order_edit was not.
    for key in ("order_create", "discount_code", "store_credit", "order_add_item"):
        assert key not in named, (key, "a registered, READY family is not a missing capability")

    families = {key for key, _n, _ids, _why in intel["new_action_families"]}
    assert not families & {"order_create", "discount_code", "store_credit", "order_add_item"}

    for turn_id in ("turn_create_order", "turn_discount", "turn_credit"):
        turn = rec.turn(turn_id)
        assert not any("no capability family claims it" in s for s in turn.signals), turn.signals

    # What the table is for still works: a change asked for out loud that no family serves.
    tape = Tape("ts-20260910-131500")
    turn = _turn(tape, "turn_price", said="change the price of the black hoodie to forty pounds", input_="text")
    _lane(tape, turn, lane="NORMAL", family=None, mutation=True, reason="asks for a change")
    _finished(tape, turn, answer="I can't change prices.", question="change the price of the black hoodie to forty pounds")
    (tmp_path / "price").mkdir()
    priced, priced_md = build_report(tape.write(tmp_path / "price"), tools_registered=TOOLS)
    priced_intel = intelligence(priced, TOOLS)
    assert {key: (n, state) for key, n, _ids, state, _scope, _what in priced_intel["spoken_capabilities"]} == {
        "price_change": (1, semantics.NO_FAMILY)}
    assert [key for key, _n, _ids, _why in priced_intel["new_action_families"]] == ["price_change"]
    assert "MISSING_CAPABILITY" in priced.turn("turn_price").classes
    assert any("no capability family claims it" in s for s in priced.turn("turn_price").signals)
    assert "change a price" in priced_md and "### Possible new action families" in priced_md


def test_c_a_capability_that_exists_and_lacks_a_scope_is_a_grant_and_not_a_build(tmp_path):
    """The other half of C, and the reason it matters: the same September sentence read against
    a live capability table. `order_edit` exists; without the scope it is a grant the owner has
    not made, with the scope named, and never a family to build."""
    path = september(tmp_path)
    states = {"order_edit": {"key": "order_edit", "label": "Order item editing", "state": "MISSING_SCOPE",
                             "detail": "the store has not granted write_order_edits", "scope": "write_order_edits"}}
    rec, markdown = build_report(path, tools_registered=TOOLS, capability_states=states)
    turn = rec.turn("turn_add_item")
    assert "PERMISSION_ERROR" in turn.classes, turn.classes
    assert any("Order item editing is MISSING_SCOPE (write_order_edits)" in s for s in turn.signals), turn.signals
    assert "MISSING_CAPABILITY" not in turn.classes, "a family that exists is not a family that is missing"
    intel = intelligence(rec, TOOLS, capability_states=states)
    assert ("order_add_item", 1, [turn.turn_id], "MISSING_SCOPE", "write_order_edits",
            "add, remove or swap a line on an order") in intel["spoken_capabilities"]
    assert "order_add_item" not in {k for k, _n, _i, _w in intel["new_action_families"]}
    assert "write_order_edits" in markdown and "grant write_order_edits" in markdown


# --------------------------------------------------------------------------- D


def test_d_a_noun_or_a_state_is_not_a_requested_mutation(tmp_path):
    """SEPTEMBER: "what is the refund status on 1938" was WRITE_INTENT and carried
    UNFULFILLED_ACTION — a change was asked for and nothing staged it.
    NOW: READ_INTENT, no UNFULFILLED_ACTION, and the disagreement with the router on the
    record. "Refund them the postage" is still a change, and still unfulfilled."""
    rec = reconstruct(read_events(september(tmp_path)))

    # The old rule, run here: the contract module's own reading of the words, which is what
    # the September report graded the turn against.
    assert contract_mod.contract_of("what is the refund status on 1938") == contract_mod.WRITE_INTENT

    status = rec.turn("turn_refund_status")
    assert status.contract == contract_mod.READ_INTENT
    assert "UNFULFILLED_ACTION" not in status.classes and status.classes == [], status.classes
    assert status.verdict is not None and status.verdict.mutation is False
    assert status.verdict.mutation_source == "router", "the router's verdict is what is narrowed, not a second reading"
    assert "'refund status'" in status.verdict.disagreement and "noun" in status.verdict.disagreement
    assert any("noun" in s for s in status.signals), status.signals

    for turn_id in ("turn_needs_reply", "turn_unfulfilled", "turn_draft_noun"):
        turn = rec.turn(turn_id)
        assert turn.contract == contract_mod.READ_INTENT, turn_id
        assert "UNFULFILLED_ACTION" not in turn.classes, turn_id

    instruction = rec.turn("turn_refund_them")
    assert instruction.contract == contract_mod.WRITE_INTENT
    assert "UNFULFILLED_ACTION" in instruction.classes, "an instruction with nothing staged is still unfulfilled"
    assert instruction.verdict.disagreement == "", "the narrowing rule only ever narrows"


def test_d_the_narrowing_rule_only_reads_the_words_the_router_knows():
    """The rule is bounded by the router's own vocabulary: it can say that a mutation word is a
    noun here, and it can never invent one. And where no `lane` event exists — an older
    timeline — the verdict says the router never saw the text."""
    assert semantics.nominal_only("what is the refund status") == "refund status"
    assert semantics.nominal_only("refund them") == ""
    # "Show" opens a request to FETCH, not a question, so a determiner alone does not make
    # "reply" a noun here — which is what keeps "give them the refund" an instruction.
    assert semantics.nominal_only("show me the reply") == ""
    assert semantics.nominal_only("give them the refund") == ""
    assert semantics.nominal_only("is there a draft for that") == "a draft"
    assert semantics.nominal_only("what is the weather") == "", "no mutation word: nothing to narrow"

    from_router = semantics.read_request("what is the refund status on 1938",
                                        lane={"family": None, "reason": "asks for a change", "signals": {"mutation": True}})
    assert from_router.mutation_source == "router" and from_router.mutation is False
    on_its_own = semantics.read_request("what is the refund status on 1938")
    assert on_its_own.mutation_source == "report" and on_its_own.mutation is False


# --------------------------------------------------------------------------- E


def test_e_the_report_reads_the_command_and_navigation_events(tmp_path):
    """SEPTEMBER: "Event kinds this report does not read: {'command': 27, …}" — an hour on a
    tablet, and the report said nothing about what was tapped on it.
    NOW: every one of them reconstructed, filed against a turn where it has one, and counted in
    section 14 with the refusal codes."""
    rec, markdown = build_report(september(tmp_path), tools_registered=TOOLS)

    # The old reading: these kinds fell through to `unknown_kinds` and into `orphans`.
    assert sum(1 for e in rec.events if e["kind"] == "command") == 27
    for kind in ("command", "command_stage", "row_action", "branch_forked", "branch_focused", "branch_backgrounded"):
        assert kind not in rec.unknown_kinds, kind
    assert not rec.unknown_kinds, dict(rec.unknown_kinds)
    assert len(rec.controls) == 32, "27 commands, a staged change, a row action, three branch moves"

    assert "## 14. Touch, commands and branches" in markdown
    assert "| open.entity | 5 |" in markdown or "open.entity" in markdown
    assert "not_available" in markdown, "the two refusals name their code"
    assert "Changes prepared by a tap (`command_stage`): 1" in markdown
    assert "Branch moves: {'branch_forked': 1, 'branch_focused': 1, 'branch_backgrounded': 1}" in markdown
    assert "Gestures that could end a recording: {'multitouch': 6, 'fork': 1}" in markdown
    assert "32 command / branch event(s)" in markdown

    posted = [e for e in rec.controls if e["kind"] == "command"]
    assert sum(1 for e in posted if e.get("ok") is False) == 2
    # A tap is not a turn: these were all made between two questions, so they belong to none —
    # and that is REPORTED rather than quietly filed against whichever turn ran last.
    assert "Commands outside any turn: 27" in markdown
    assert all(not t.commands for t in rec.turns), "no tap here happened while a turn was running"
    assert all(e in rec.controls for t in rec.turns for e in t.commands)


# ------------------------------------------------------- the rest of what §27 asks for


def test_the_report_names_the_branch_the_precision_input_and_the_repeats(tmp_path):
    """The detections §27 asks for beyond the five: a branch move that redrew nothing, a half
    put aside and never returned to, and the cross-source reads and repeats counted."""
    rec, markdown = build_report(september(tmp_path), tools_registered=TOOLS)
    intel = intelligence(rec, TOOLS)
    what = {row[1] for row in intel["branch_failures"]}
    assert "focus changed with nothing redrawn" in what
    assert "a half put aside was never returned to" in what
    assert any("was refused" in x for x in what)
    for heading in ("### UI component gaps", "### Branch (split orb) UX failures",
                    "### Precision input needed", "### Repeated corrections", "### Repeated cross-source workflows"):
        assert heading in markdown, heading


def test_each_detection_becomes_a_candidate_a_person_can_pick_up(tmp_path):
    """The report is read by `app/observability/proposals.py`, which turns each row into an
    IMPROVEMENT CANDIDATE with the turns it came from. A detection that reaches the report and
    not the candidates is a detection nobody acts on."""
    from app.observability.proposals import write_proposals

    path = september(tmp_path)
    rec, _ = build_report(path, tools_registered=TOOLS)
    intel = intelligence(rec, TOOLS)
    assert any("typed into the composer" in what for _t, what, _d in intel["precision_input"])
    # CHANGED IN PHASE 5, because the old expectation was provably wrong (§21).
    #
    # This line used to read `assert any("too short" in what ...)`: a recording the tablet
    # threw away counted as evidence that a value had to be exact. Held against the 11
    # September timeline, 61 of the 62 rows that expectation produced were ordinary taps on
    # Split, Merge and Close — 39–140 ms, 63 of them, in 17 bursts, with ZERO accepted commands
    # anywhere in the largest — swallowed by the voice layer because the branch bar sits inside
    # `.orb-zone`'s stacking context. Not one was about precision input, and the rule made the
    # precision-input path the report's number one improvement candidate at 2 × 62 = 124.
    #
    # A short recording is now `app/observability/touch.py`'s business, in four classes
    # (CONTROL_TAP_MISROUTED_TO_VOICE, REAL_SHORT_VOICE_RECORDING, GESTURE_COLLISION,
    # PRECISION_INPUT_REQUIRED), and this table holds only positive evidence of exact entry.
    assert not any("too short" in what for _t, what, _d in intel["precision_input"]), \
        "a tap the voice layer swallowed is not a value that had to be exact"
    assert [n for _shape, n, _ids in intel["cross_source_workflows"] if n >= 2], intel["cross_source_workflows"]

    text = write_proposals(path, tmp_path / "reports").read_text(encoding="utf-8")
    for kind in ("BRANCH_UX", "PRECISION_INPUT", "CORRECTION", "CROSS_SOURCE_RECIPE"):
        assert kind in text, kind
    # Round 9, F-03: the three changes September asked for have been built since, so none is a
    # family to build (the NEW_CAPABILITY_FAMILY candidate is held by test_c above, for a change
    # still unbuilt).
    for built in ("create a discount code", "put store credit on a customer", "add, remove or swap a line on an order"):
        assert built not in text, "a family that exists is not a family to build"

    states = {"order_edit": {"key": "order_edit", "label": "Order item editing", "state": "MISSING_SCOPE",
                             "detail": "not granted", "scope": "write_order_edits"}}
    with_states = write_proposals(path, tmp_path / "reports2", capability_states=states).read_text(encoding="utf-8")
    assert "CAPABILITY_STATE" in with_states and "Grant write_order_edits" in with_states
    assert "nothing is built here; a grant is the owner's to make." in with_states


def test_the_two_lane_numbers_are_reported_apart(tmp_path):
    """A slow model and slow reads are different faults in different files, so `facts_ms` and
    `prose_wait_ms` are two rows and the report says which dominates."""
    tape = Tape("ts-20260910-130000")
    turn = _turn(tape, "turn_compound", said="check whether they have emailed and draft the reply", input_="text")
    _lane(tape, turn, lane="NORMAL", family="order_email_draft", email=True, question=True)
    _tool(tape, turn, "gmail_read_thread", result={"thread_id": THREAD})
    tape.add("turn_performance", session_id="s1", turn_id=turn, lane="NORMAL", recipe_id="order_email_reply",
             fast_path_hit=False, model_calls=1, facts_ms=1400.0, workspace_ms=1500.0, prose_wait_ms=23_600.0,
             turn_total_ms=25_100.0)
    _finished(tape, turn, answer="Mia is waiting; here is the reply.", question="check whether they have emailed and draft the reply", ms=25_100.0)
    _, markdown = build_report(tape.write(tmp_path), tools_registered=TOOLS)

    assert "| Facts in hand | 1 |" in markdown and "| Waited after the facts | 1 |" in markdown
    assert "1,400 ms reading, 23,600 ms waiting" in markdown
    assert "the waiting dominates" in markdown
    assert "Slow prose wait (over 6,000 ms)" in markdown
