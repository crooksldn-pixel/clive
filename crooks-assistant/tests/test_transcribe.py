"""The transcription pipeline with a fake Scribe, and capture pruning.

What comes back is what was heard: nothing biases the recogniser and nothing rewrites the words
after it (the owner's decision of 28 September 2026). These ran against a fake whisper.cpp until
the local recogniser was deleted (DEC-071, ruling 39); the pipeline they hold is Scribe's."""

from __future__ import annotations

import time

import pytest

from app.clients.elevenlabs import ScribeUnavailable
from app.speech.heard import Transcript
from app.speech.transcribe import Transcriber, prune_captures

av = pytest.importorskip("av")
from tests.test_decode import speech_pcm, tone_pcm, webm_opus  # noqa: E402

DEVELOPER_DETAIL = "ElevenLabs answered 503 from api.elevenlabs.io"


class FakeScribe:
    model = "scribe_v2"
    failing_kind = ""

    def __init__(self, text: str = "", fail: bool = False) -> None:
        self.text, self.fail, self.calls = text, fail, 0

    async def transcribe(self, wav: bytes) -> Transcript:
        self.calls += 1       # the audio is all it is given
        if self.fail:
            raise ScribeUnavailable(DEVELOPER_DETAIL, kind="server_error")
        return Transcript(text=self.text, ms=12.0)


async def test_speech_path_keeps_the_words_and_reports_timings():
    t = Transcriber(FakeScribe("find the blue wash yard genes"))
    result = await t.from_blob(webm_opus(tone_pcm(1.0)))
    assert result.ok
    assert result.text == "find the blue wash yard genes", "no correction towards the catalogue"
    assert result.raw_text == "find the blue wash yard genes"
    assert {"decode", "transcribe"} <= result.timings_ms.keys()
    assert "normalise" not in result.timings_ms
    assert "matches" not in result.as_dict() and "order_numbers" not in result.as_dict()


async def test_silence_never_reaches_the_recogniser():
    fake = FakeScribe("Thank you.")
    result = await Transcriber(fake).from_blob(webm_opus(b"\x00\x00" * 48000))
    assert not result.ok
    assert fake.calls == 0, "the recogniser was called for a recording with no signal"
    assert "could not hear" in result.reason


@pytest.mark.parametrize("text", ["Thank you.", "", "you", "[BLANK_AUDIO]", "Subtitles by the Amara.org community"])
async def test_hallucinations_become_no_speech(text):
    result = await Transcriber(FakeScribe(text)).from_blob(webm_opus(tone_pcm(1.0)))
    assert not result.ok
    assert "did not catch" in result.reason


async def test_scribe_down_is_spoken_not_crashed():
    result = await Transcriber(FakeScribe(fail=True)).from_blob(webm_opus(tone_pcm(1.0)))
    assert not result.ok
    assert "speech recognition" in result.reason
    assert "elevenlabs" not in result.reason.lower() and "503" not in result.reason, (
        "developer detail must not be spoken aloud")
    assert DEVELOPER_DETAIL in result.engine_detail, "it goes to the record instead"


async def test_a_recording_that_only_touches_full_scale_is_transcribed():
    """The false rejection: the tablet said "that came through distorted" and the saved
    recording was perfectly intelligible. A peak is a moment; distortion is a proportion."""
    fake = FakeScribe("how many yard jeans are left")
    result = await Transcriber(fake).from_blob(webm_opus(speech_pcm(drive=1.0)))
    assert result.stats.peak >= 0.999, "it really does reach the rail"
    assert result.ok, f"refused a usable recording: {result.reason}"
    assert fake.calls, "the recogniser was never given the audio"
    assert result.text == "how many yard jeans are left"


async def test_a_genuinely_distorted_recording_is_still_refused():
    fake = FakeScribe("nonsense")
    result = await Transcriber(fake).from_blob(webm_opus(speech_pcm(drive=2.0)))
    assert not result.ok
    assert "distorted" in result.reason
    assert fake.calls == 0, "a mangled recording was sent to the recogniser anyway"
    assert result.stats.clipped_ratio >= 0.02


async def test_the_rejection_reason_says_which_check_failed():
    """Too quiet and too distorted are different problems with different fixes."""
    quiet = await Transcriber(FakeScribe()).from_blob(webm_opus(b"\x00\x00" * 48000))
    assert "closer to the microphone" in quiet.reason
    loud = await Transcriber(FakeScribe()).from_blob(webm_opus(speech_pcm(drive=2.0)))
    assert "further from the microphone" in loud.reason
    short = await Transcriber(FakeScribe()).from_blob(webm_opus(tone_pcm(0.1)))
    assert "too short" in short.reason


async def test_undecodable_upload_is_reported():
    result = await Transcriber(FakeScribe("x")).from_blob(b"not audio at all")
    assert not result.ok
    # The owner hears a fixed sentence (synthesised once, kept); the decoder's words go to
    # the detail, and the log.
    assert result.reason == "I could not make out that recording. Try once more."
    assert "Could not open" in result.engine_detail


async def test_captures_are_saved_and_pruned(tmp_path):
    t = Transcriber(FakeScribe("hi"), save_dir=tmp_path, max_saved=3)
    for i in range(5):
        await t.from_blob(webm_opus(tone_pcm(0.5)), filename_hint=f"t{i}.webm")
        time.sleep(0.01)
        # same-second timestamps collide; give each a distinct name by touching mtime order
    files = sorted(p for p in tmp_path.iterdir() if not p.name.startswith("."))
    assert len(files) <= 3


def test_prune_keeps_newest(tmp_path):
    for i in range(6):
        p = tmp_path / f"{i}.webm"
        p.write_bytes(b"x")
        ts = 1_700_000_000 + i
        import os

        os.utime(p, (ts, ts))
    (tmp_path / ".gitkeep").write_text("")
    removed = prune_captures(tmp_path, keep=2)
    assert removed == 4
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == [".gitkeep", "4.webm", "5.webm"]


def test_prune_handles_missing_dir(tmp_path):
    assert prune_captures(tmp_path / "nope", keep=5) == 0
    assert prune_captures(None, keep=5) == 0


async def test_the_log_never_carries_what_was_said(caplog):
    """Names and addresses the owner speaks are not for the operational log: it records
    lengths and timings, never the words."""
    import logging

    caplog.set_level(logging.INFO, logger="crooks")
    caplog.set_level(logging.INFO)
    t = Transcriber(FakeScribe("find the blue wash yard genes for daniel stub"))
    result = await t.from_blob(webm_opus(tone_pcm(1.0)))
    assert result.ok
    assert "daniel" not in caplog.text.lower() and "yard genes" not in caplog.text.lower()
    assert "recognised via scribe_v2" in caplog.text
