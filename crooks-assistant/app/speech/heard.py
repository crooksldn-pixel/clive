"""What a recogniser heard, and the sounds that are never speech.

ElevenLabs Scribe is CLIVE's only recogniser (DEC-022; the local whisper.cpp client was deleted
on the owner's ruling of 8 October, DEC-071 ruling 39). Its answer comes back as a `Transcript`,
and app/speech/transcribe.py throws away any transcript that is only one of the artefacts below:
an assistant that answers a question nobody asked is worse than one that says it did not hear.
The list started as whisper.cpp's silence artefacts and stays because it says nothing about any
one engine: a transcript of "Thank you." over a silent room is not a question from anyone.
"""

from __future__ import annotations

from dataclasses import dataclass

# What recognisers emit over silence: artefacts of their training data, not speech. They are the
# single most common way a voice assistant answers a question nobody asked.
HALLUCINATION_BLOCKLIST = frozenset(
    {
        "thank you.", "thank you", "thanks for watching!", "thanks for watching.",
        "you", "you.", "bye.", "bye", ".", "...", "[blank_audio]", "[music]",
        "subtitles by the amara.org community", "subs by www.zberg.net",
        "please subscribe to my channel.", "transcription by castingwords",
        "amara.org", "♪", "[silence]", "(silence)", "so.", "so",
    }
)


@dataclass(slots=True)
class Transcript:
    text: str
    ms: float
    model: str = ""

    @property
    def is_hallucination(self) -> bool:
        stripped = self.text.strip().lower()
        return not stripped or stripped in HALLUCINATION_BLOCKLIST
