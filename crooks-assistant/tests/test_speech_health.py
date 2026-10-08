"""A server with one recogniser, and /health telling the truth about it.

ElevenLabs Scribe is the only thing that hears the owner (DEC-022: no local speech fallback on
the server). The local whisper.cpp client, its settings and its health check were deleted on the
owner's ruling of 8 October (DEC-071, ruling 39); this file was tests/test_whisper_disabled.py,
and what it held for the server's rows still holds, now that the server's rows are the only
ones. The rows that described a Mac with whisper behind Scribe went with the Mac runtime.

The question these settle is whether /health stays truthful about speech, because the two easy
answers are both wrong. A host with nothing behind Scribe must not borrow a reassurance it has
no fallback for: Scribe down is a deaf assistant, and `speech` says so. And the absence of a
fallback is a decision, so it never makes a host that is otherwise well read as degraded.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from app.routes.health import _health


class _Writes:
    state, detail = "off", "writes are off (CROOKS_WRITES_ENABLED=false)"


def _runtime(*, tmp_path: Path, scribe_ok: bool = True) -> SimpleNamespace:
    """A runtime that answers every probe /health makes, and nothing more.

    Every external call is a local coroutine: no network, no ElevenLabs, no Shopify, no Gmail.
    """

    async def ok(detail: str):
        return True, detail

    async def probe(good: bool, detail: str):
        return good, detail

    voice = SimpleNamespace(
        enabled=True, voice_name="Derek", model="eleven_flash_v2_5",
        output_format="mp3_44100_128", attempts=0, successes=0, failures=0,
        last_ms=0.0, last_bytes=0, last_error_kind=None, prefetches=0, prefetch_hits=0,
        health=lambda: (True, "configured"),
        verify_voice=lambda: ok("verified"),
    )
    scribe = SimpleNamespace(
        health=lambda: probe(scribe_ok, "scribe_v2" if scribe_ok else "401 rejected"),
        attempts=0, successes=0, failures=0, last_error_kind=None,
    )
    return SimpleNamespace(
        build="test-build",
        uptime_s=1.0,
        manifest=None,
        order_cache=None,
        settings=SimpleNamespace(scribe_model="scribe_v2"),
        provider=SimpleNamespace(health=lambda: ok("claude cli")),
        shopify=SimpleNamespace(health=lambda: ok("store reachable")),
        gmail=SimpleNamespace(health=lambda: (True, "profile read")),
        scribe=scribe,
        voice=voice,
        kb=SimpleNamespace(empty=False, files=["a.md"], chars=10),
        sessions=SimpleNamespace(count=lambda: 0),
        write_status=lambda: ok_writes(),
        capabilities=lambda: _async({}),
        family_states=lambda: _async({}),
    )


async def _async(value):
    return value


async def ok_writes():
    return _Writes()


def health_of(**kwargs) -> dict:
    return asyncio.run(_health(_runtime(**kwargs)))


# --------------------------------------------------------------- the settings are gone


def test_the_local_recognisers_settings_are_gone():
    """CROOKS_WHISPER_ENABLED and its neighbours went with the client. One left in an old .env is
    ignored, as every unknown key is, so a server whose .env still says it starts as before."""
    from config.settings import Settings

    settings = Settings(_env_file=None)
    for name in ("whisper_enabled", "whisper_url", "whisper_model", "whisper_bin_dir",
                 "whisper_vad_pad_ms", "stt_primary"):
        assert not hasattr(settings, name), name


def test_the_production_example_no_longer_sets_it():
    text = (Path(__file__).resolve().parent.parent / "deploy" / "env.production.example").read_text()
    keys = [line.split("=", 1)[0].strip() for line in text.splitlines()
            if "=" in line and not line.lstrip().startswith("#")]
    assert keys, "the template set nothing — the check would pass vacuously"
    assert not [k for k in keys if k.startswith("CROOKS_WHISPER") or k == "CROOKS_STT_PRIMARY"], keys


# --------------------------------------------------------------- no fallback, and no check for one


def test_there_is_no_whisper_check_and_the_host_is_not_degraded_for_its_absence(tmp_path):
    """The point the disabled check was made for, kept now that there is nothing to disable: a
    machine that was never given a fallback is not a broken machine, and must not present as
    one."""
    health = health_of(tmp_path=tmp_path)
    assert "whisper" not in health["checks"]
    assert health["status"] == "ok"
    assert "whisper_ok" not in health["speech"] and "whisper_enabled" not in health["speech"]


# --------------------------------------------------------------- speech, truthfully


def test_scribe_working_means_speech_is_healthy(tmp_path):
    health = health_of(tmp_path=tmp_path, scribe_ok=True)
    assert health["checks"]["speech"]["ok"] is True
    assert health["status"] == "ok"


def test_scribe_down_with_no_fallback_is_unhealthy(tmp_path):
    """The case the whole design turns on. There is nothing behind Scribe, so the tablet cannot
    be heard at all and /health has to say so."""
    health = health_of(tmp_path=tmp_path, scribe_ok=False)
    speech = health["checks"]["speech"]
    assert speech["ok"] is False
    assert "no local fallback" in speech["detail"]
    assert health["status"] == "degraded"


def test_redundancy_says_there_is_nothing_behind_scribe(tmp_path):
    assert health_of(tmp_path=tmp_path)["checks"]["speech"]["redundancy"] == "none"
    assert health_of(tmp_path=tmp_path)["speech"]["redundancy"] == "none"


def test_effective_says_none_when_nothing_can_hear(tmp_path):
    health = health_of(tmp_path=tmp_path, scribe_ok=False)
    assert health["speech"]["effective"] == "none"


def test_effective_names_scribe_when_it_hears(tmp_path):
    assert health_of(tmp_path=tmp_path)["speech"]["effective"] == "scribe_v2"


# --------------------------------------------------------------- the transcriber


def test_the_transcriber_reaches_for_nothing_behind_scribe():
    """Not merely that it fails — that it fails at once, with the one sentence production has
    always spoken when nothing could hear, and with Scribe's own reason kept for the record."""
    from app.clients.elevenlabs import ScribeUnavailable
    from app.speech.transcribe import UNHEARD_REASON, Transcriber

    class DownScribe:
        model = "scribe_v2"
        failing_kind = "server_error"

        def __init__(self) -> None:
            self.calls = 0

        async def transcribe(self, wav):
            self.calls += 1
            raise ScribeUnavailable("ElevenLabs answered 503", kind="server_error")

    scribe = DownScribe()
    transcript, why = asyncio.run(Transcriber(scribe)._recognise(b"audio", {}))
    assert transcript is None and scribe.calls == 1
    assert why == "server_error: ElevenLabs answered 503"
    assert Transcriber(scribe)._unheard_reason() == UNHEARD_REASON
