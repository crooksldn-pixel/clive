"""A host with no local recogniser, and the difference between "absent" and "broken".

The server does not deploy whisper.cpp: no Core ML, no model, no build toolchain. The
question these tests settle is not whether /health mentions it, but whether /health stays
*truthful* about it — because the two easy answers are both wrong. Reporting a deliberate
absence as a failure gives the host a permanently red check, and a check that is always red
is one nobody reads. Reporting it as fine in every circumstance hides the outage that
actually matters: on the Mac, Scribe going down is a slower assistant, and on this host it is
a deaf one.

So the matrix below is the specification. The Mac's rows must not move — whisper enabled is
its behaviour exactly as it was — and the server's rows must go unhealthy on the one case
that leaves nothing able to hear.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.routes.health import _health


class _Writes:
    state, detail = "off", "writes are off (CROOKS_WRITES_ENABLED=false)"


def _settings(*, whisper_enabled: bool, tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        whisper_enabled=whisper_enabled,
        scribe_model="scribe_v2",
        whisper_model="small.en",
        whisper_bin_dir=tmp_path / "whisper.cpp",
    )


def _runtime(
    *,
    tmp_path: Path,
    whisper_enabled: bool = True,
    primary: str = "scribe",
    scribe_ok: bool = True,
    whisper_ok: bool = True,
) -> SimpleNamespace:
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
        settings=_settings(whisper_enabled=whisper_enabled, tmp_path=tmp_path),
        transcriber=SimpleNamespace(primary=primary),
        provider=SimpleNamespace(health=lambda: ok("claude cli")),
        shopify=SimpleNamespace(health=lambda: ok("store reachable")),
        gmail=SimpleNamespace(health=lambda: (True, "profile read")),
        whisper=SimpleNamespace(
            health=lambda: probe(whisper_ok, "inference ok" if whisper_ok else "unreachable")
        ),
        scribe=scribe,
        voice=voice,
        kb=SimpleNamespace(empty=False, files=["a.md"], chars=10),
        normaliser=SimpleNamespace(catalogue=["term"]),
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


# --------------------------------------------------------------- the setting itself


def test_the_default_is_enabled_so_the_mac_is_untouched():
    """Nothing about the Mac's deployment changes by this setting existing. It has whisper,
    it keeps whisper, and a Mac that never sets the variable never notices it was added."""
    from config.settings import Settings

    assert Settings(_env_file=None).whisper_enabled is True


def test_the_production_example_turns_it_off():
    text = (Path(__file__).resolve().parent.parent / "deploy" / "env.production.example").read_text()
    assert "CROOKS_WHISPER_ENABLED=false" in text


# --------------------------------------------------------------- disabled: reported, not failed


def test_a_disabled_whisper_is_reported_as_disabled_not_failed(tmp_path):
    health = health_of(tmp_path=tmp_path, whisper_enabled=False)
    whisper = health["checks"]["whisper"]
    assert whisper["ok"] is True
    assert whisper["disabled"] is True
    assert "disabled" in whisper["detail"].lower()


def test_an_intentionally_absent_whisper_does_not_degrade_the_host(tmp_path):
    """The point of the whole exercise: a machine that was never given a fallback is not a
    broken machine, and must not present as one."""
    health = health_of(tmp_path=tmp_path, whisper_enabled=False)
    assert health["status"] == "ok"


def test_no_core_ml_probe_runs_when_there_is_nothing_to_probe(tmp_path):
    health = health_of(tmp_path=tmp_path, whisper_enabled=False)
    assert "Core ML" not in health["checks"]["whisper"]["detail"]


def test_the_core_ml_probe_still_runs_where_whisper_is_deployed(tmp_path):
    health = health_of(tmp_path=tmp_path, whisper_enabled=True)
    assert "Core ML" in health["checks"]["whisper"]["detail"]


# --------------------------------------------------------------- speech, truthfully


def test_scribe_working_means_speech_is_healthy(tmp_path):
    health = health_of(tmp_path=tmp_path, whisper_enabled=False, scribe_ok=True)
    assert health["checks"]["speech"]["ok"] is True
    assert health["status"] == "ok"


def test_scribe_down_with_no_fallback_is_unhealthy(tmp_path):
    """The case the whole design turns on. On the Mac this same outage is a slower assistant;
    here there is nothing behind Scribe, so the tablet cannot be heard at all and /health has
    to say so rather than inheriting the Mac's reassurance."""
    health = health_of(tmp_path=tmp_path, whisper_enabled=False, scribe_ok=False)
    speech = health["checks"]["speech"]
    assert speech["ok"] is False
    assert "no local fallback" in speech["detail"]
    assert health["status"] == "degraded"


def test_scribe_down_on_the_mac_still_falls_back_and_stays_healthy(tmp_path):
    """Mac behaviour, unchanged: whisper takes the turn and answers still work."""
    health = health_of(tmp_path=tmp_path, whisper_enabled=True, scribe_ok=False, whisper_ok=True)
    assert health["checks"]["speech"]["ok"] is True
    assert "whisper_fallback" in health["checks"]["speech"]["detail"]


def test_both_recognisers_down_on_the_mac_is_still_unhealthy(tmp_path):
    health = health_of(tmp_path=tmp_path, whisper_enabled=True, scribe_ok=False, whisper_ok=False)
    assert health["checks"]["speech"]["ok"] is False


# --------------------------------------------------------------- the absence, published


def test_redundancy_names_which_world_the_reader_is_in(tmp_path):
    assert health_of(tmp_path=tmp_path, whisper_enabled=False)["checks"]["speech"]["redundancy"] == "none"
    assert health_of(tmp_path=tmp_path, whisper_enabled=True)["checks"]["speech"]["redundancy"] == "whisper"


def test_whisper_ok_reports_usable_rather_than_merely_probed(tmp_path):
    """A disabled whisper reports its own check ok so the host is not degraded. Carrying that
    straight into whisper_ok would be the one place it turns into a claim about what can
    actually hear you."""
    speech = health_of(tmp_path=tmp_path, whisper_enabled=False)["speech"]
    assert speech["whisper_ok"] is False
    assert speech["whisper_enabled"] is False
    assert speech["redundancy"] == "none"


def test_effective_says_none_when_nothing_can_hear(tmp_path):
    health = health_of(tmp_path=tmp_path, whisper_enabled=False, scribe_ok=False)
    assert health["speech"]["effective"] == "none"


# --------------------------------------------------------------- the configuration mistake


def test_primary_whisper_with_whisper_disabled_is_named_as_a_mistake(tmp_path):
    """Neither setting is wrong alone, so no single check catches it. The pair leaves the host
    with no recogniser at all, and it must not read as an ordinary whisper outage."""
    health = health_of(tmp_path=tmp_path, whisper_enabled=False, primary="whisper")
    speech = health["checks"]["speech"]
    assert speech["ok"] is False
    assert "MISCONFIGURED" in speech["detail"]
    assert health["speech"]["effective"] == "none"


# --------------------------------------------------------------- the transcriber


def _transcriber(*, whisper_enabled: bool):
    from app.speech.transcribe import Transcriber

    calls = []

    class Client:
        async def transcribe(self, wav, prompt=""):
            calls.append(wav)
            raise AssertionError("whisper must not be called on a host without it")

    normaliser = SimpleNamespace(
        catalogue=SimpleNamespace(prompt_terms=lambda: [], external_terms=lambda: [])
    )
    return Transcriber(Client(), normaliser, whisper_enabled=whisper_enabled), calls


def test_the_transcriber_does_not_reach_for_a_fallback_it_does_not_have():
    """Not merely that it fails — that it fails *without* spending a connect-and-timeout on a
    port with nothing behind it, on every single Scribe failure."""
    from app.clients.whisper import WhisperUnavailable

    transcriber, calls = _transcriber(whisper_enabled=False)
    with pytest.raises(WhisperUnavailable) as caught:
        asyncio.run(transcriber._whisper(b"audio"))
    assert calls == []
    assert "not deployed on this host" in str(caught.value)


def test_the_transcriber_still_calls_whisper_where_it_is_deployed():
    transcriber, calls = _transcriber(whisper_enabled=True)
    with pytest.raises(AssertionError):
        asyncio.run(transcriber._whisper(b"audio"))
    assert calls == [b"audio"]
