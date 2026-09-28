"""§24: Stop, tapped, is an interruption, and an interruption that answers is not one.

The rules this file holds, for the stop control on the tablet (`interaction.stop`):

* stop stops the voice, drops a control that was waiting for words, and quietens a background
  half that was asking for attention
* stop does NOT undo anything and does NOT withdraw a staged change — he said stop, not cancel
* an expected interruption is not logged as a provider error

The word "stop" said out loud is a model turn like every other sentence since 28 September
2026 (tests/test_every_turn_is_the_model.py); holding the orb to say it already silences the
voice on the tablet.
"""

from __future__ import annotations

import pytest

from app import commands
from app.families import load_all
from app.session.branch import Branch
from app.session.models import Session

load_all()


class FakeVoice:
    """A voice that can be stopped, and counts being stopped."""

    def __init__(self) -> None:
        self.cancelled = 0

    def cancel_prefetches(self) -> int:
        self.cancelled += 1
        return 2


class FakeRuntime:
    def __init__(self) -> None:
        self.voice = FakeVoice()


@pytest.fixture()
def branch():
    return Branch(branch_id="br_test", session_id="s1")


@pytest.fixture()
def session(branch):
    live = Session(session_id="s1")
    live.branches = {branch.branch_id: branch}
    live.focused_branch = branch.branch_id
    return live


def _tap(session, branch, runtime=None):
    return commands.run("interaction.stop", commands.Ctx(runtime or FakeRuntime(), session, branch, {}))


def test_the_answer_is_an_acknowledgement_and_not_a_paragraph(session, branch):
    outcome = _tap(session, branch)
    assert outcome.ok
    assert 0 < len(outcome.answer) <= 80, outcome.answer
    assert not outcome.surfaces, "an interruption draws nothing"
    assert "can" not in outcome.answer.lower(), f"no capability blurb: {outcome.answer!r}"


def test_it_stops_the_voice(session, branch):
    runtime = FakeRuntime()
    outcome = _tap(session, branch, runtime=runtime)
    assert runtime.voice.cancelled == 1, "the voice being synthesised was not stopped"
    assert outcome.changed["stopped"].get("voice") == 2


def test_it_drops_a_control_that_was_waiting_for_words(session, branch):
    """Tap Add a note, then tap stop. The binding must go, or the next thing said is read as
    note text."""
    branch.bind_voice("order.add_note", kind="order", ref="gid://shopify/Order/1", label="#1938",
                      prompt="Add a note", phrase="Listening for the note")
    assert branch.voice_target() is not None
    outcome = _tap(session, branch)
    assert branch.voice_target() is None, "still listening for the note"
    assert outcome.changed["stopped"].get("listening") is True
    assert outcome.changed.get("listening_for") is None


def test_it_quietens_a_background_half_without_cancelling_it(session, branch):
    """§24's third: stop the background display on request. The half keeps its work — he said
    stop, not cancel — and stops asking to be looked at."""
    other = Branch(branch_id="br_other", session_id="s1", label="right", status="BACKGROUND")
    other.ready("the inbox")
    session.branches[other.branch_id] = other
    outcome = _tap(session, branch)
    assert other.task is None, "the background half is still asking for attention"
    assert other.status == "BACKGROUND", "the half was cancelled, and he did not say cancel"
    assert outcome.changed["stopped"].get("background") == 1


def test_it_withdraws_nothing(session, branch):
    """An interruption is not an authorisation. Anything staged is the action engine's, and
    stop must not throw it away."""
    session.proposals.append(object())
    before = len(session.proposals)
    _tap(session, branch)
    assert len(session.proposals) == before, "a staged change was withdrawn by an interruption"
    assert session.epoch == 0, "the epoch moved, which withdraws every pending card"


def test_the_stop_control_is_a_tap_and_never_reached_by_words():
    spec = commands.get("interaction.stop")
    assert spec is not None and spec.touch and not spec.voice


# ------------------------------------------------------- an interruption is not a failure


async def test_a_cancelled_prefetch_is_an_interruption_not_a_provider_error():
    """§24's last line, measured on the route that files it.

    A prefetch dropped because the owner moved on was reported to the timeline as
    `ok=False, failure="cancelled"` — his own Stop, in the ElevenLabs failure column. It is
    now `ok=True, interrupted=True`, and the tablet gets 204: there is nothing to say.
    """
    from app.clients.elevenlabs_tts import VoiceUnavailable
    from app.observability import timeline
    from experience.harness import harness

    async with harness() as stage:
        events: list[dict] = []

        def record(kind, **fields):
            events.append({"kind": kind, **fields})

        original = timeline.emit
        timeline.emit = record  # type: ignore[assignment]

        class Interrupted:
            voice_name, model, max_chars, cooling_down = "v", "m", 400, False

            async def take_ready(self, text):
                raise VoiceUnavailable("cancelled", kind="cancelled")

            async def open_stream(self, text):      # pragma: no cover — never reached
                raise AssertionError("a cancelled answer must not be synthesised again")

        stage.runtime.voice = Interrupted()
        try:
            response = await stage.client.post("/speak", json={"text": "Two orders today."})
        finally:
            timeline.emit = original  # type: ignore[assignment]

    assert response.status_code == 204, response.text
    tts = [e for e in events if e["kind"] == "tts"]
    assert tts, "nothing was filed at all"
    assert tts[-1]["ok"] is True and tts[-1].get("interrupted") is True, tts[-1]
    assert "failure" not in tts[-1], f"an expected interruption filed as a failure: {tts[-1]}"
