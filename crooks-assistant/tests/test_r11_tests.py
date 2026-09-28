"""The suite's own honesty, round 11: assertions that were vacuous or oracles that could not fail,
each held here to what the application actually produced (the 2026-09-28 deploy review, round 9:
I-tests1 I-01, H-experience1 H-03 and H-05).

- I-tests1 I-01: two privacy assertions in tests/test_actions_routes.py ended in `or True`. Round
  10 removed both; the read-argument half still asserted on `_loggable_args` and `redact` called
  by hand. Here the same property is read off the TURN LOG the application wrote for a real turn.
- H-03: the spoken change requests used to go to a model that called nothing, so "nothing was
  prepared" could not fail. They now script the model's attempt; here a model that calls nothing
  is shown to FAIL them, so their checks are about what the Mac did with the attempt.
- H-05: the needs-reply oracle compares the queue with the fixture world thread by thread; here
  a queue that also offers an answered thread, and an answer that names someone not waiting,
  are shown to fail it.
"""

from __future__ import annotations

import json

import pytest

from experience.harness import harness


@pytest.fixture()
async def stage():
    async with harness(admitted=True) as h:
        yield h


def _turn_record(h, turn_id: str) -> dict:
    """What the application wrote to the turn log for this turn (app/logging/turnlog.py)."""
    rows = [json.loads(line) for line in h.runtime.turnlog.path.read_text(encoding="utf-8").splitlines() if line.strip()]
    mine = [row for row in rows if row.get("turn_id") == turn_id]
    assert len(mine) == 1, f"{len(mine)} turn-log records for {turn_id}"
    return mine[0]


async def test_the_turn_log_keeps_a_reads_arguments_redacted_and_a_refused_writes_words_by_length_only(stage):
    """I-tests1 I-01, against the actual output. The owner names a customer and her email in a
    turn whose model finds her order by her email, looks her up by her name, and then tries a
    note carrying her name and street on an order this conversation was never shown —
    which the gate refuses. What the turn log keeps (app/routes/turn.py `_loggable_args`, then
    `TurnLog.write` with the names the turn's reads returned): the reads' arguments, with the email
    redacted by its shape and her name because a read returned it; the refused note by its length
    alone; and her name, her email and the street in the note nowhere in the record.

    (A name no read has returned has no shape to find, and is kept in a read's arguments as it
    is in the owner's own words: that is the turn log's stated rule, not something this asserts
    away. The always-on timeline keeps such words by length — app/tools/dispatch.py
    `loggable_args`.)"""
    note = "Refund Mia Jones, 12 Acacia Avenue"
    c = await stage.ask(
        "find Mia Jones by mia.jones@example.com and note the refund on her order",
        ("shopify_find_order", {"query": "mia.jones@example.com"}),
        ("shopify_find_customer", {"query": "Mia Jones"}),
        ("shopify_order_note_append", {"order_id": "gid://shopify/Order/9999", "note": note}),
        reply="Found her order.", session_id="turnlog")
    called = [(t.get("name"), t.get("ok")) for t in c.raw.get("tool_calls") or []]
    assert called == [("shopify_find_order", True), ("shopify_find_customer", True),
                      ("shopify_order_note_append", False)], called
    assert not stage.runtime.sessions.get("turnlog").proposals, "the gate refused the note"
    assert "Mia Jones" in stage.runtime.sessions.get("turnlog").pii_seen, "a read returned her name"

    record = _turn_record(stage, str(c.raw.get("turn_id") or ""))
    logged = {t["name"]: t["args"] for t in record["tool_calls"]}
    assert logged["shopify_order_note_append"] == {"order_id": "gid://shopify/Order/9999", "note": f"<{len(note)} chars>"}
    assert logged["shopify_find_order"] == {"query": "[email]"}, logged["shopify_find_order"]
    assert logged["shopify_find_customer"] == {"query": "[name]"}, logged["shopify_find_customer"]
    whole = json.dumps(record, ensure_ascii=False)
    for secret in ("mia.jones@example.com", "Mia Jones", "Acacia"):
        assert secret not in whole, f"{secret!r} reached the turn log"


# ------------------------------------------------------------- H-03: the oracle can fail


async def _with_a_model_that_calls_nothing(h, monkeypatch):
    """Every sentence answered in words, no tool called: the model the no-op scenarios had
    before round 10. `Harness.ask` still records the script, but nothing is made."""
    monkeypatch.setattr(h.provider, "will", lambda said, *tools, reply="": None)


@pytest.mark.parametrize("name", ["discount_sentence_defers", "order_add_item_sentence_defers", "unsupported_edit",
                                  "compose_send_spoken"])
async def test_a_spoken_change_scenario_fails_when_the_model_attempts_nothing(name, stage, monkeypatch):
    """H-03 and H-04: these scenarios assert what the Mac did with the model's ATTEMPT at a change
    — prepared as a card and not applied, or refused at the gate — so with a model that attempts
    nothing they must fail, not pass on an empty turn. (They pass with the scripted attempt:
    tests/test_experience.py::test_the_golden_scenarios.)"""
    from experience.scenarios import BY_NAME

    await _with_a_model_that_calls_nothing(stage, monkeypatch)
    result = await BY_NAME[name](stage)
    assert result.status != "PASS", f"{name} passed with a model that attempted nothing"
    assert result.failures, name


# ------------------------------------------------------------- H-05: the needs-reply oracle


def _answered_thread():
    """A thread the golden world says has been answered, from someone the world knows, and the
    name its last message was sent under."""
    from experience.fixtures import world

    waiting = world.needs_reply()
    known = {p.name for p in world.people.values() if p.name}
    for thread in world.threads:
        if thread in waiting:
            continue
        last = max(thread.messages, key=lambda m: (-m.days_ago, m.hour)).sender.split("<")[0].strip()
        firsts = {m.sender.split("<")[0].strip() for m in thread.messages} & known
        if firsts:
            return thread, last, sorted(firsts)[0]
    raise AssertionError("the golden world has no answered thread from a person it knows")


async def test_the_needs_reply_oracle_fails_a_queue_that_offers_an_answered_thread(stage, monkeypatch):
    """H-05: the queue is compared with the fixture world's own threads, by id. A queue that also
    offers a thread the world says was answered fails the scenario — where the old check, a first
    name anywhere in the stringified card, could not tell."""
    from app.families import landings
    from experience.scenarios import BY_NAME

    answered, last, _person = _answered_thread()
    real = landings._waiting_surface

    def with_an_answered_thread(waiting, **kwargs):
        rows = [*waiting, {**(waiting[0] if waiting else {}), "last_thread_id": answered.thread_id,
                           "customer_name": last, "needs_reply": True}]
        return real(rows, **kwargs)

    monkeypatch.setattr(landings, "_waiting_surface", with_an_answered_thread)
    result = await BY_NAME["needs_reply"](stage)
    failed = {c.what for c in result.failures}
    assert result.status != "PASS", "a queue offering an answered thread passed"
    assert "the queue holds exactly the threads the world says are waiting, and no other" in failed, failed


async def test_the_needs_reply_oracle_fails_an_answer_that_names_someone_not_waiting(stage, monkeypatch):
    """H-05's other half: the spoken answer is held to the world too. An answer whose waiting
    clause also names a person the world says is not waiting fails the scenario."""
    import dataclasses

    from app.families import landings
    from experience.fixtures import world
    from experience.scenarios import BY_NAME

    waiting_names = {max(t.messages, key=lambda m: (-m.days_ago, m.hour)).sender.split("<")[0].strip()
                     for t in world.needs_reply()}
    other = sorted(p.name for p in world.people.values() if p.name and p.name not in waiting_names)[0]
    real = landings._needs_reply_render

    def naming_someone_else(ctx, result):
        answer = real(ctx, result)
        first, dot, rest = answer.answer.partition(". ")
        return dataclasses.replace(answer, answer=f"{first}, and {other}{dot}{rest}")

    monkeypatch.setattr(landings, "_needs_reply_render", naming_someone_else)
    result = await BY_NAME["needs_reply"](stage)
    failed = {c.what for c in result.failures}
    assert result.status != "PASS", "an answer naming someone who is not waiting passed"
    assert "and the answer names nobody the world says is not waiting" in failed, failed


# ------------------------------------------------------------- H-02: scripted, and said to be


async def test_a_scripted_model_choice_is_labelled_as_one_on_the_capture_and_in_the_report(stage, tmp_path):
    """H-02: `abandoned_window` scripts `days=7` for the harness's model — the reviewer's own
    example. What its result proves is what the Mac did with that call, and it says so: the
    capture names the tool as scripted, the capture's record carries it, and the run's report
    prints it in the Scripted model column under the paragraph saying what that means. A tapped
    scenario, which scripts nothing, shows none. Whether Claude WOULD choose the call is not
    something an offline run can show; that each call is one it COULD make is checked for every
    scenario (tests/test_experience.py `BEYOND_THE_MODEL`)."""
    from experience import report
    from experience.scenarios import BY_NAME

    scripted = await BY_NAME["abandoned_window"](stage)
    tapped = await BY_NAME["needs_reply"](stage)
    assert scripted.status == "PASS" and tapped.status == "PASS", (scripted.failures, tapped.failures)
    (capture,) = scripted.captures
    assert capture.scripted == ["shopify_abandoned_checkouts"] and not capture.unmakeable
    assert capture.as_dict()["scripted_model"] == ["shopify_abandoned_checkouts"]
    assert all(not c.scripted for c in tapped.captures)

    text = (report.write([scripted, tapped], directory=tmp_path / "run") / "report.md").read_text(encoding="utf-8")
    assert "not that Claude would choose them" in text
    rows = {line.split("|")[2].strip(): line for line in text.splitlines() if line.startswith("| ✓ |")}
    assert rows[scripted.title].rstrip().endswith("| shopify_abandoned_checkouts |"), rows[scripted.title]
    assert rows[tapped.title].rstrip().endswith("| — |"), rows[tapped.title]
