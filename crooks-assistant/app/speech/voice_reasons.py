"""What the owner is told when ElevenLabs cannot speak or cannot listen, in plain words.

One place, because the same failure is worded in three: the 503 from /speak, the line said
when nothing can hear, and /health. Each says what happened and what brings it back — never an
HTTP status, never ElevenLabs' own message (those are in the log), and nothing about which
machine the assistant happens to run on.

An empty account is the case that matters most: ElevenLabs answers it with a 401, and it was
reported as a rejected key while the only fix was topping the plan up.
"""

from __future__ import annotations

TOP_UP = "it comes back by itself once the ElevenLabs plan is topped up"

VOICE = {
    "off": "the ElevenLabs voice is switched off",
    "no_key": "the ElevenLabs key is not set up",
    "cooldown": "the ElevenLabs voice is unavailable at the moment",
    "rejected": "the ElevenLabs key was rejected as invalid; the voice comes back once a valid key is stored",
    "forbidden": "the ElevenLabs key is not allowed to speak",
    "credit": f"voice is paused because the ElevenLabs credits are used up; {TOP_UP}",
    "no_voice": "the ElevenLabs voice was not found",
    "timeout": "ElevenLabs did not answer in time",
    "network": "ElevenLabs could not be reached",
    "server_error": "ElevenLabs had a server error",
    "rate": "the ElevenLabs voice has been asked for too often this minute",
    "cancelled": "that answer was abandoned",
    "prefetch": "the ElevenLabs voice could not be prepared",
}

LISTENING = {
    "no_key": "the ElevenLabs key is not set up",
    "cooldown": "ElevenLabs speech recognition is unavailable at the moment",
    "rejected": "the ElevenLabs key was rejected as invalid; listening comes back once a valid key is stored",
    "forbidden": "the ElevenLabs key is not allowed to transcribe",
    "credit": f"speech recognition is paused because the ElevenLabs credits are used up; {TOP_UP}",
    "timeout": "ElevenLabs did not answer in time",
    "network": "ElevenLabs could not be reached",
    "server_error": "ElevenLabs had a server error",
    "rate": "ElevenLabs was asked for too much at once",
    "bad_response": "ElevenLabs sent back something that was not a transcript",
}

# Said aloud when the credits are gone and there is no other recogniser to fall back on.
LISTENING_CREDIT_SPOKEN = (
    "I cannot hear you right now: speech recognition is paused because the ElevenLabs "
    "credits are used up. It comes back by itself once the ElevenLabs plan is topped up."
)


def voice_reason(kind: str) -> str:
    return VOICE.get(kind, "the ElevenLabs voice is unavailable")


def listening_reason(kind: str) -> str:
    return LISTENING.get(kind, "ElevenLabs speech recognition is unavailable")
