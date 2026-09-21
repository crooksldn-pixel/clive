from __future__ import annotations

import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
APP = WEB / "app.js"
INDEX = WEB / "index.html"


def test_v05_removes_user_facing_split_entry_points_but_keeps_internal_branch_support() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "split.textContent = 'Split';" not in source
    assert "splitOrb('gesture')" not in source

    # Internal/legacy branch mechanics still exist so concurrency has not been deleted;
    # V0.5 changes who manages it, not whether the runtime can represent it.
    assert "async function splitOrb(" in source
    assert "if (branches.length < 2) {" in source
    assert "if (branches.length > 1)" in source


def test_v05_ready_copy_no_longer_frames_clive_as_an_empty_command_prompt() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "READY: ['CLIVE ready', 'Ask, interrupt, or continue']" in source
    assert "READY: ['System ready.', 'What do you need?']" not in source


def test_v05_initial_html_matches_clive_ready_framing_before_javascript_runs() -> None:
    source = INDEX.read_text(encoding="utf-8")

    assert ">CLIVE ready</p>" in source
    assert ">Ask, interrupt, or continue</p>" in source
    assert 'aria-label="Back to CLIVE"' in source
    assert "<span>CLIVE</span>" in source
    assert ">System ready.</p>" not in source
    assert ">What do you need?</p>" not in source


LIVE_STATE = WEB / "live-state.js"
SW = WEB / "sw.js"


def test_v05_ships_one_client_side_state_authority() -> None:
    """Invariant 2/B: one state machine, and it is a real file the page loads — not a
    convention spread across the call sites that write `stage.dataset.state`."""
    assert LIVE_STATE.is_file()
    source = LIVE_STATE.read_text(encoding="utf-8")

    for state in ("IDLE", "LISTENING", "HEARING", "UNDERSTOOD", "THINKING", "WORKING", "RESPONDING"):
        assert f"'{state}'" in source, f"the canonical state {state} is missing"
    # "Error, interruption and recovery states must be explicit."
    for state in ("INTERRUPTED", "FAULT", "RECOVERING"):
        assert f"'{state}'" in source, f"{state} must be a state, not an implication"

    # "Do not infer state from arbitrary DOM text." The authority cannot: past the two lines
    # that publish it on the global, there is no browser in the file at all.
    body = source[source.index("})(typeof window"):]
    body = body[body.index("'use strict';"):]
    body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
    body = "\n".join(re.sub(r"//.*$", "", line) for line in body.splitlines())
    for forbidden in ("document", "querySelector", "dataset", "textContent", "window", "navigator"):
        assert forbidden not in body, f"the state authority reaches for {forbidden}"

    # The page loads it, and the worker keeps it in the shell so it survives going offline.
    assert '<script src="/static/live-state.js"></script>' in INDEX.read_text(encoding="utf-8")
    assert "'/static/live-state.js'," in SW.read_text(encoding="utf-8")


def test_v05_state_transitions_are_events_and_not_assignments() -> None:
    """B: the page reports what HAPPENED; the machine decides what that means."""
    source = APP.read_text(encoding="utf-8")

    # Pointer-down enters LISTENING synchronously, and it is the machine that is told first.
    assert "if (live) live.pointerDown();\n  setState('LISTENING');" in source
    # The release is marked where it happens, so every later measurement has a true origin.
    assert "if (live && !discard) live.released();" in source
    # The transcript settling on screen is what UNDERSTOOD means here — and the machine is
    # handed a LENGTH, never the words (invariant 11).
    assert "live.final(String(data.heard).length);" in source
    assert "live.final(data.heard)" not in source
    # A question that was never spoken is still a turn.
    assert "if (live && !isAudio) live.asked(0);" in source
    # Everything else still speaks presentation words, and there is exactly one translator.
    assert "if (live) live.fromPresentation(state);" in source


def test_v05_measures_the_four_latencies_the_evidence_gate_names() -> None:
    """Evidence gate: pointer-down → acknowledgement, release → final transcript, release →
    first progress indication, release → first useful result."""
    machine = LIVE_STATE.read_text(encoding="utf-8")
    for mark in ("acknowledgedMs", "transcriptMs", "progressMs", "usefulMs"):
        assert mark in machine, f"{mark} is not measured"

    source = APP.read_text(encoding="utf-8")
    # A useful result is a thing the owner can read, reported from where one actually lands.
    assert "noteUseful('workspace patch');" in source
    assert "noteUseful('answer');" in source
    # And the turn's evidence is emitted as numbers and counts only.
    assert "T.record('live_marks', {" in source
    for field in ("ack_ms", "transcript_ms", "progress_ms", "useful_ms"):
        assert field in source, f"live_marks does not carry {field}"
    # Every value in it comes from the machine, which was never given a word of the
    # conversation: lengths and counts, never text. `heard_chars` is how MUCH was said.
    marks = source[source.index("T.record('live_marks', {"):]
    marks = marks[:marks.index("});")]
    values = re.findall(r":\s*([A-Za-z][\w.]*)", marks)
    for value in values:
        assert value.startswith("marks.") or value == "live.state" or value == "undefined", \
            f"live_marks reads {value!r}, which is not one of the machine's own measurements"
    assert "heard_chars: marks.heardChars" in marks
    for leak in ("el.heard", "data.answer", "data.question", "textContent"):
        assert leak not in marks, f"the evaluation record carries {leak!r}"
