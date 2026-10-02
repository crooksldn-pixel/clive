"""The voice the owner chose, and how he asked it to sound — kept, not compiled in.

Before this, changing CLIVE's voice meant a `.env` line on the server and a restart, and the
voice's expression could not be changed from CLIVE at all: the synthesis request deliberately sent
no voice settings, so ElevenLabs applied whatever the voice's own defaults were (owner, 2 October).
Both now live here, written from the Connections screen and applied without a restart.

Kept beside the Connections screen's other records (passkeys, grants) in the root-only directory,
0600, because that directory is writable to the service and `/var/lib/crooks-assistant` is not.
Nothing here is a secret — a voice id is not a key — but it is the owner's own setting, so it is
no more readable than the rest.

What is *not* changed here: a setting left unset is not sent. A fresh install, or a slider never
moved, asks ElevenLabs for the voice's own defaults exactly as this code always did, so the voice
only changes when the owner changes it.

The voice id and the name are always stored as a pair, read from ElevenLabs itself when the owner
picks a voice. `/health` asks ElevenLabs what the configured id is really called and reports a
mismatch (app/clients/elevenlabs_tts.py voice_mismatch), which is what stops the health page
naming one voice while the tablet and the shop's screens speak in another. Storing the pair
together is what keeps that check meaningful now the id is no longer fixed in the code.
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger("crooks.voice")

FILE_NAME = "voice.json"
FILE_MODE = 0o600
VERSION = 1

# ElevenLabs voice ids are opaque; this is a shape check, not an allow-list.
VOICE_ID = re.compile(r"^[A-Za-z0-9]{16,40}$")
# The models this project speaks with. Flash is the production choice: this is a conversation and
# latency is the thing the owner feels. The others are offered because a shop screen reading a
# slip is not a conversation and can afford to sound better.
MODELS: dict[str, str] = {
    "eleven_flash_v2_5": "Flash v2.5 — fastest, the production choice",
    "eleven_turbo_v2_5": "Turbo v2.5 — a little slower, a little better",
    "eleven_multilingual_v2": "Multilingual v2 — best quality, slowest",
}
# Each slider: what ElevenLabs accepts, and what it is called on the screen. `style` is the one
# the owner called expression.
SLIDERS: dict[str, tuple[float, float]] = {
    "stability": (0.0, 1.0),
    "similarity_boost": (0.0, 1.0),
    "style": (0.0, 1.0),
    "speed": (0.7, 1.2),
}
SWITCHES = ("use_speaker_boost",)

_CONFIG: dict[str, Path | None] = {"state_dir": None}


def configure(*, state_dir: Path | None) -> None:
    """Where the record lives. Given the same directory as the Connections screen's own records."""
    _CONFIG["state_dir"] = Path(state_dir) if state_dir else None


def _path() -> Path | None:
    folder = _CONFIG["state_dir"]
    return Path(folder) / FILE_NAME if folder else None


def _clamp(value: Any, low: float, high: float) -> float | None:
    """A number inside what ElevenLabs accepts, or None when it is not a number at all. Out of
    range is brought into range rather than refused: a slider cannot ask for the impossible."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:                                      # NaN
        return None
    return round(min(max(number, low), high), 3)


def clean(values: Any) -> dict[str, Any]:
    """What of `values` may be kept. Anything unrecognised, misshapen or empty is dropped, so a
    stored record only ever holds settings this code knows how to send."""
    if not isinstance(values, dict):
        return {}
    kept: dict[str, Any] = {}
    voice_id = str(values.get("voice_id") or "").strip()
    if voice_id and VOICE_ID.fullmatch(voice_id):
        kept["voice_id"] = voice_id
        # The name is only a label, and only meaningful beside its own id.
        name = " ".join(str(values.get("voice_name") or "").split())[:60]
        if name:
            kept["voice_name"] = name
    model = str(values.get("model") or "").strip()
    if model in MODELS:
        kept["model"] = model
    for key, (low, high) in SLIDERS.items():
        if key in values and values[key] is not None:
            number = _clamp(values[key], low, high)
            if number is not None:
                kept[key] = number
    for key in SWITCHES:
        if key in values and values[key] is not None:
            kept[key] = bool(values[key])
    return kept


def voice_settings(stored: dict[str, Any] | None = None) -> dict[str, Any]:
    """Just the part ElevenLabs takes as `voice_settings`. Empty when nothing was ever moved,
    which is what keeps "say nothing and get the voice's own defaults" the behaviour it was."""
    held = read() if stored is None else stored
    return {key: held[key] for key in (*SLIDERS, *SWITCHES) if key in held}


def read() -> dict[str, Any]:
    """What is stored, cleaned on the way out: a record edited by hand cannot widen what is sent."""
    path = _path()
    if path is None:
        return {}
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        log.warning("the voice record could not be read (%s); the configured voice stands", type(exc).__name__)
        return {}
    return clean((held or {}).get("voice") if isinstance(held, dict) else None)


def write(values: Any) -> dict[str, Any]:
    """Keep `values`, replacing what was there. Returns what was actually kept."""
    path = _path()
    if path is None:
        raise RuntimeError("there is nowhere to keep the voice settings on this machine")
    kept = clean(values)
    body = json.dumps({"version": VERSION, "voice": kept}, ensure_ascii=False, indent=2, sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    handle, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    temporary_path = Path(temporary)
    try:
        os.fchmod(handle, FILE_MODE)
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(body + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)
    if stat.S_IMODE(path.stat().st_mode) != FILE_MODE:
        path.chmod(FILE_MODE)
    return kept


def forget() -> None:
    """Back to the configured voice and its own defaults."""
    path = _path()
    if path is not None:
        path.unlink(missing_ok=True)
