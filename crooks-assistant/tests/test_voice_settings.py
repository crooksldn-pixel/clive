"""Changing CLIVE's voice, and how it sounds, from the Connections screen.

Before this it was a `.env` line on the server plus a restart, and the voice's expression could not
be changed from CLIVE at all (owner, 2 October). What is guarded here: an untouched install still
asks ElevenLabs for the voice's own defaults, a stored id is always kept beside the name ElevenLabs
gave it, and nothing here is reachable by anyone but the owner with a passkey for those very values.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.clients.elevenlabs_tts import VoiceClient
from app.speech import voice_prefs

pytestmark = pytest.mark.anyio


# ------------------------------------------------------------------ what may be kept

def test_only_settings_this_code_can_send_are_kept():
    kept = voice_prefs.clean({
        "voice_id": "Q0Et7LOU7VpeoeCRQAVS", "voice_name": "  Derek   the   voice ",
        "model": "eleven_turbo_v2_5", "style": 0.4, "use_speaker_boost": "yes",
        "latency": 3, "voice_settings": {"style": 1}, "text": "say this",   # none of these are ours
    })
    assert kept == {"voice_id": "Q0Et7LOU7VpeoeCRQAVS", "voice_name": "Derek the voice",
                    "model": "eleven_turbo_v2_5", "style": 0.4, "use_speaker_boost": True}


def test_a_misshapen_voice_id_or_unknown_model_is_dropped_rather_than_stored():
    assert voice_prefs.clean({"voice_id": "not a voice id!", "model": "eleven_wishful_v9"}) == {}
    # The name is only meaningful beside its own id, so it never survives alone.
    assert voice_prefs.clean({"voice_name": "Derek"}) == {}


@pytest.mark.parametrize(("asked", "kept"), [(-5, 0.0), (0.25, 0.25), (99, 1.0)])
def test_a_slider_outside_what_elevenlabs_takes_is_brought_into_range(asked, kept):
    assert voice_prefs.clean({"style": asked})["style"] == kept


def test_speed_has_its_own_narrower_range():
    assert voice_prefs.clean({"speed": 0.1})["speed"] == 0.7
    assert voice_prefs.clean({"speed": 5})["speed"] == 1.2


def test_a_slider_that_is_not_a_number_is_dropped_not_guessed():
    for value in ("fast", None, float("nan"), {}):
        assert "style" not in voice_prefs.clean({"style": value})


def test_what_is_stored_is_read_back_and_a_record_edited_by_hand_cannot_widen_it(tmp_path):
    voice_prefs.configure(state_dir=tmp_path)
    assert voice_prefs.read() == {}                                   # nothing stored yet
    voice_prefs.write({"voice_id": "Q0Et7LOU7VpeoeCRQAVS", "voice_name": "Derek", "style": 0.6})
    assert voice_prefs.read() == {"voice_id": "Q0Et7LOU7VpeoeCRQAVS", "voice_name": "Derek", "style": 0.6}
    path = tmp_path / voice_prefs.FILE_NAME
    assert path.stat().st_mode & 0o777 == 0o600
    path.write_text(json.dumps({"version": 1, "voice": {"style": 9, "model": "made_up", "text": "x"}}))
    assert voice_prefs.read() == {"style": 1.0}                        # clamped, and the rest gone
    voice_prefs.forget()
    assert voice_prefs.read() == {}


def test_an_unreadable_record_leaves_the_configured_voice_alone(tmp_path):
    voice_prefs.configure(state_dir=tmp_path)
    (tmp_path / voice_prefs.FILE_NAME).write_text("{ this is not json")
    assert voice_prefs.read() == {}


# ------------------------------------------------------------------ what is sent

def a_voice(**kwargs):
    return VoiceClient(voice_id="Q0Et7LOU7VpeoeCRQAVS", voice_name="Derek", model="eleven_flash_v2_5",
                       output_format="mp3_44100_128", timeout_s=10.0, base_url="https://eleven.test/v1",
                       max_chars=1200, cooldown_s=300.0, enabled=True, account=None, **kwargs)


def test_an_untouched_install_still_asks_for_the_voices_own_defaults():
    """The behaviour this change had to keep: no voice_settings in the body at all."""
    assert a_voice()._payload("hello") == {"text": "hello", "model_id": "eleven_flash_v2_5"}


def test_the_sliders_the_owner_moved_are_what_is_sent():
    voice = a_voice()
    voice.apply(voice_settings={"style": 0.4, "use_speaker_boost": True})
    assert a_voice()._payload("hello").get("voice_settings") is None   # and only on this client
    assert voice._payload("hello")["voice_settings"] == {"style": 0.4, "use_speaker_boost": True}


def test_choosing_a_voice_changes_what_speaks_and_asks_health_to_verify_the_new_one():
    voice = a_voice()
    voice._voice_checked_at, voice._voice_actual_name = 123.0, "Derek"
    voice.apply(voice_id="9375G6zswFk7v9bKTVQF", voice_name="Vikram", model="eleven_turbo_v2_5")
    assert (voice.voice_id, voice.voice_name, voice.model) == (
        "9375G6zswFk7v9bKTVQF", "Vikram", "eleven_turbo_v2_5")
    assert voice._url(stream=True).startswith("https://eleven.test/v1/text-to-speech/9375G6zswFk7v9bKTVQF")
    # The old name is forgotten, so /health does not report a mismatch against a voice that is gone.
    assert (voice._voice_checked_at, voice._voice_actual_name) == (0.0, None)


def test_changing_only_the_sliders_leaves_the_verified_name_alone():
    voice = a_voice()
    voice._voice_checked_at, voice._voice_actual_name = 123.0, "Derek"
    voice.apply(voice_settings={"style": 0.2})
    assert (voice._voice_checked_at, voice._voice_actual_name) == (123.0, "Derek")


def _previewable():
    """A voice whose one HTTP call is captured instead of made."""
    voice = a_voice()
    sent: dict = {}

    class Response:
        status_code, content = 200, b"audio"

    async def post(url, headers=None, json=None, timeout=None):
        sent.update(url=url, body=json, key=headers.get("xi-api-key"))
        return Response()

    voice._api_key = lambda: "a-key"                                   # noqa: SLF001 - the point of the test
    voice._client = lambda: SimpleNamespace(post=post)                 # noqa: SLF001
    return voice, sent


async def test_a_preview_speaks_in_the_asked_for_voice_and_changes_nothing():
    """A preview must not change what the next real answer sounds like."""
    voice, sent = _previewable()
    audio = await voice.say_once("sample", voice_id="9375G6zswFk7v9bKTVQF", model="eleven_turbo_v2_5",
                                 voice_settings={"style": 0.9})
    assert audio == b"audio"
    assert "9375G6zswFk7v9bKTVQF" in sent["url"]
    assert sent["body"] == {"text": "sample", "model_id": "eleven_turbo_v2_5",
                            "voice_settings": {"style": 0.9}}
    # The client itself is untouched: the next real answer is still Derek on Flash with no settings.
    assert (voice.voice_id, voice.model, voice.voice_settings) == (
        "Q0Et7LOU7VpeoeCRQAVS", "eleven_flash_v2_5", {})
    assert voice._payload("hello") == {"text": "hello", "model_id": "eleven_flash_v2_5"}
