"""The reports and what they are drawn from (the 2026-09-28 deploy review, round 9, parts
F-observability1 and F-observability2):

- F-01: a report is named by the session id its timeline's events carry; `../web/exposed` there
  wrote the owner's words outside reports/. Only an id in the shape the store makes names a file,
  and the file must land directly in its folder.
- F-03: store credit (and the other changes built since §27C) named no capability family, so a
  request for a live, money-moving write was reported as something to build.
- F-OBS2-01: visible.py hands the owner's words and the assistant's answers to the report. They
  leave it scrubbed and allow-listed, and they reach the owner only: the report is written 0600 in
  a 0700 folder, and nothing that answers a request or feeds a screen reads them.
- F-OBS2-02: a rule that could not read a timeline logged the exception's own words, which carry
  the value it could not read. Only the rule's name and the exception's type are logged now.
"""

from __future__ import annotations

import ast
import json
import logging
import os
from pathlib import Path

import pytest

from app.observability import visible
from app.observability.proposals import write_proposals
from app.observability.report import build_report, reconstruct, write_report
from app.observability.session import report_target, safe_session_id
from app.observability.timeline import read_events
from tests.fake_credentials import shopify_token
from tests.test_experience_analyser import (
    Tape,
    the_same_defects_recorded,
    turn,
    two_defects_narrated_and_discarded,
)

APP = Path(__file__).resolve().parents[1] / "app"


def _timeline(tmp_path: Path, name: str, session_id: str) -> Path:
    path = tmp_path / f"{name}.jsonl"
    events = [
        {"ts": 1_790_000_000.0, "seq": 1, "test_session_id": session_id, "source": "mac", "kind": "session_started", "name": "x"},
        {"ts": 1_790_000_001.0, "seq": 2, "test_session_id": session_id, "source": "mac", "kind": "turn_started",
         "session_id": "s1", "turn_id": "turn_a", "input": "text"},
        {"ts": 1_790_000_002.0, "seq": 3, "test_session_id": session_id, "source": "mac", "kind": "turn_finished",
         "session_id": "s1", "turn_id": "turn_a", "question": "what came in today", "answer": "Three orders."},
    ]
    path.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    return path


# ------------------------------------------------------------------ F-01


@pytest.mark.parametrize("carried", ["../web/exposed", "../../etc/cron.d/x", "/tmp/elsewhere", "ts-20260927-000000-a/../../x",
                                     "ts-20260927-000000-walk\x00", "ts-20260927-000000-UPPER", "rec-2026-0927", ".hidden",
                                     "ts-20260927-000000-" + "a" * 30, "ts-x"])
def test_a_session_id_that_is_not_one_names_no_file_anywhere(tmp_path, carried):
    reports = tmp_path / "reports"
    path = _timeline(tmp_path, "ts-20260927-000000-walk", carried)
    for write in (write_report, write_proposals):
        with pytest.raises(ValueError):
            write(path, reports)
    written = [p for p in tmp_path.rglob("*") if p.is_file() and p != path]
    assert written == [], written


def test_a_real_session_id_names_its_report_inside_its_folder(tmp_path):
    reports = tmp_path / "reports"
    for ident in ("ts-20260927-101500-first-hour", "rec-20260927-101500-always-on", "ts-20260910-125946"):
        assert safe_session_id(ident) == ident
        path = _timeline(tmp_path, ident, ident)
        report, proposals = write_report(path, reports), write_proposals(path, reports)
        assert report == reports / f"{ident}.md" and proposals == reports / f"{ident}-proposals.md"
        assert report.stat().st_mode & 0o777 == 0o600 and reports.stat().st_mode & 0o777 == 0o700
    # With no id in its events, the timeline file's own name is used, and held to the same shape.
    bare = tmp_path / "ts-20260927-111111-bare.jsonl"
    bare.write_text(json.dumps({"ts": 1.0, "seq": 1, "kind": "session_started", "source": "mac"}) + "\n")
    assert write_report(bare, reports) == reports / "ts-20260927-111111-bare.md"
    odd = tmp_path / "not a session.jsonl"
    odd.write_text(bare.read_text())
    with pytest.raises(ValueError):
        write_report(odd, reports)


def test_a_report_name_that_resolves_outside_its_folder_is_refused(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir(mode=0o700)
    ident = "ts-20260927-101500-first-hour"
    elsewhere = tmp_path / "web"
    elsewhere.mkdir()
    os.symlink(elsewhere / "exposed.md", reports / f"{ident}.md")
    with pytest.raises(ValueError):
        report_target(reports, ident, "", ".md")
    assert report_target(reports, "", ident, "-proposals.md") == reports / f"{ident}-proposals.md"


# ------------------------------------------------------------------ F-03


def _store_credit_tape(tmp_path: Path) -> Path:
    """A request for store credit, read by the router as a change, that the family staged and the
    owner's tap applied and proved."""
    from tests.test_analyser import Tape as AnalyserTape
    from tests.test_analyser import _finished, _lane, _tool, _turn

    tape = AnalyserTape("ts-20260927-120000-credit")
    said = "add ten pounds store credit to her account"
    t = _turn(tape, "turn_credit", said=said, input_="text")
    _lane(tape, t, lane="NORMAL", family=None, mutation=True, reason="asks for a change")
    _tool(tape, t, "shopify_store_credit", outcome="staged", result={"proposal_id": "prop_credit"})
    tape.add("action_commit", session_id="s1", turn_id=t, proposal_id="prop_credit", operation="store_credit_credit",
             status="VERIFIED", code="verified", verified=True, ms=900.0)
    _finished(tape, t, answer="Ten pounds of store credit is ready for her account. Tap to apply it.",
              question=said, ui=["action"])
    tmp_path.mkdir(parents=True, exist_ok=True)
    return tape.write(tmp_path)


def test_a_store_credit_request_that_was_carried_out_is_not_a_capability_to_build(tmp_path):
    from app.observability import semantics
    from app.observability.report import intelligence

    change = semantics.change_named("add ten pounds store credit to her account")
    assert change is not None and change.key == "store_credit" and change.capability == "store_credit"
    assert semantics.capability_state(change)["state"] == "READY", "the store credit family is registered and ready"
    rec, markdown = build_report(_store_credit_tape(tmp_path / "a"))
    turn_ = rec.turn("turn_credit")
    assert "MISSING_CAPABILITY" not in turn_.classes, turn_.classes
    assert not any("no capability family claims it" in s for s in turn_.signals), turn_.signals
    intel = intelligence(rec, [])
    assert not [key for key, *_ in intel["new_action_families"]]
    assert "put store credit on a customer" not in markdown
    proposals = write_proposals(_store_credit_tape(tmp_path / "b"), tmp_path / "reports").read_text(encoding="utf-8")
    assert "NEW_CAPABILITY_FAMILY" not in proposals
    # And a live table that says the store has not granted it is a grant, never a build.
    states = {"store_credit": {"key": "store_credit", "label": "Store credit", "state": "MISSING_SCOPE",
                               "scope": "write_store_credit_account_transactions"}}
    granted = write_proposals(_store_credit_tape(tmp_path / "c"), tmp_path / "reports2", capability_states=states)
    text = granted.read_text(encoding="utf-8")
    assert "NEW_CAPABILITY_FAMILY" not in text and "write_store_credit_account_transactions" in text
    # Every change §27C named now names the family that serves it, and each is registered.
    families = semantics._load_families()
    for key in ("order_create", "discount_code", "store_credit", "abandoned_checkout"):
        change = next(c for c in semantics.CHANGES if c.key == key)
        assert change.capability and families.get(change.capability) is not None, key


# ------------------------------------------------------------------ F-OBS2-01


def test_what_leaves_visible_is_scrubbed_and_holds_only_the_fields_the_report_prints(tmp_path):
    token = shopify_token("feedback")
    path = the_same_defects_recorded(tmp_path)
    events = read_events(path)
    for event in events:
        if event.get("kind") == "owner_feedback":
            event["raw_headers"] = {"authorization": f"Bearer {token}"}
            event["debug"] = {"customer_email": "greg@example.com", "token": token}
            event["text"] = f"log that the split is broken, greg@example.com said {token}"
    reading = visible.read(reconstruct(events))
    assert len(reading.feedback) == 2
    for kept in reading.feedback:
        assert set(kept) <= set(visible._FEEDBACK_FIELDS), sorted(kept)
        flat = json.dumps(kept)
        assert token not in flat and "greg@example.com" not in flat and "raw_headers" not in flat

    ignored_path = two_defects_narrated_and_discarded(tmp_path / "ignored")
    events = read_events(ignored_path)
    for event in events:
        if event.get("kind") == "turn_finished":
            event["answer"] = f"Write to greg@example.com — here is the key {token}. " + "x" * 600
    reading = visible.read(reconstruct(events))
    assert len(reading.ignored_feedback) == 2
    for row in reading.ignored_feedback:
        assert token not in row["answer"] and "greg@example.com" not in row["answer"] and len(row["answer"]) <= 200
    for finding in reading.findings:
        assert token not in finding.signal and "greg@example.com" not in finding.signal
    for row in reading.rows:
        assert token not in row.why and "greg@example.com" not in row.why


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_nothing_that_answers_a_request_or_feeds_a_screen_reads_the_owners_reports():
    """Who can see what visible.py and the report carry: the report's readers are imported by the
    command line and the Control app (scripts/), and by nothing under app/routes (what answers a
    request), app/displays or app/tools (what puts things on a screen), or the app itself. So the
    only way to the owner's words in a report is the file, 0600 in a 0700 folder on the server."""
    readers = {"app.observability.report", "app.observability.visible", "app.observability.proposals",
               "app.observability.report.build_report", "app.observability.report.write_report",
               "app.observability.report.reconstruct", "app.observability.proposals.write_proposals",
               "app.observability.visible.read", "app.observability.visible.apply"}
    checked = 0
    for folder in ("routes", "displays", "tools", "providers", "presentation.py", "main.py", "runtime.py"):
        target = APP / folder
        files = [target] if target.is_file() else sorted(target.rglob("*.py"))
        for path in files:
            checked += 1
            found = _imports(path) & readers
            assert not found, (str(path.relative_to(APP)), sorted(found))
    for path in sorted((APP / "observability").glob("*.py")):
        if path.name in ("report.py", "visible.py", "proposals.py", "recorder.py"):
            continue
        assert not (_imports(path) & readers), path.name
    assert checked > 40
    # The recorder's one use is the list a person picks an interaction from: ids, names, counts and
    # classes — never a signal, a question or an answer.
    source = (APP / "observability" / "recorder.py").read_text(encoding="utf-8")
    body = source[source.index("def interactions"):source.index("def save_as_test")]
    for word in ("signals", "question", "answer", "why", "ignored_feedback", "experience"):
        assert f".{word}" not in body and f'"{word}"' not in body, word


# ------------------------------------------------------------------ F-OBS2-02


def test_a_rule_that_cannot_read_a_value_logs_its_name_and_the_failure_never_the_value(tmp_path, monkeypatch, caplog):
    token = shopify_token("telemetry")
    rec = reconstruct(read_events(the_same_defects_recorded(tmp_path)))

    def reading_a_bad_value(rec_):
        int(f"{token} greg@example.com")        # the exception's words carry the value

    monkeypatch.setattr(visible, "RULES", (*visible.RULES, reading_a_bad_value))
    from app.observability import feedback as feedback_mod

    def recognise(text):
        raise ValueError(f"could not read {token}")

    monkeypatch.setattr(feedback_mod, "recognise", recognise)
    caplog.set_level(logging.DEBUG)
    reading = visible.read(rec)
    assert "reading_a_bad_value: ValueError" in reading.errors and "_feedback: ValueError" in reading.errors
    assert token not in caplog.text and "greg@example.com" not in caplog.text
    assert "reading_a_bad_value" in caplog.text and "ValueError" in caplog.text
    assert "owner feedback could not be read from this timeline (ValueError)" in caplog.text


def test_a_focus_rule_given_counts_that_are_not_numbers_still_reads_the_rest(tmp_path, caplog):
    """The finding's own case: tablet_compose_field.chars that is not a number. The rule reads it as
    nought instead of failing, and the rest of the timeline is still read."""
    token = shopify_token("chars")
    tape = Tape("ts-20260927-130000-focus")
    t = turn(tape, "turn_compose", said="write to the supplier", answer="The composer is open.", ui=["email_compose"])
    tape.add("tablet_compose_field", source="tablet", session_id="s1", turn_id=t, name="body", chars=12)
    tape.add("tablet_compose_field", source="tablet", session_id="s1", turn_id=t, name="body", chars=token)
    tape.add("tablet_compose_field", source="tablet", session_id="s1", turn_id=t, name="body", chars="twelve")
    (tmp_path / "f").mkdir()
    rec = reconstruct(read_events(tape.write(tmp_path / "f")))
    caplog.set_level(logging.DEBUG)
    reading = visible.read(rec)
    assert not [e for e in reading.errors if e.startswith("_focus_lost")]
    assert any(f.name == "FOCUS_LOST" and "held 12 character(s) and then held none" in f.signal for f in reading.findings)
    assert token not in caplog.text
