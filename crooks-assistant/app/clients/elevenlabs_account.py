"""What the ElevenLabs account last said about its own credit, shared by the two clients.

Speaking and listening are two products on one account and one credential, so an empty account
is one fact and not two: on 2026-09-22 ElevenLabs answered `401 quota_exceeded` to Derek and to
Scribe alike, and topping the plan up brings both back together.

Until this existed the voice had nothing to answer a health check from except its own attempts,
and it will not make one: a check that synthesises a sentence on every poll is a bill, not a
check. So `VoiceClient.health()` said "key ok" whenever `attempts == 0` — true of every freshly
started process. A restart on an empty account put `voice.ok: true` back on the page while the
tablet fell back to the Android voice on every answer, which is the dishonest surface the
account-credit work set out to remove. Scribe already probes the account on every /health, on
the same credential; this is where that answer is put so the voice can read it.

One observation, and the newest wins. That is what "cleared only by newer evidence" means here:
a success at either product supersedes an exhaustion seen before it, an exhaustion supersedes a
success seen before it, and nothing supersedes an observation made after it. Both clients run
on the one event loop, so writes arrive in the order they were observed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass
class AccountCredit:
    """The latest word on whether the ElevenLabs account has credit left.

    `exhausted` is only ever set from evidence the account gave about itself — a
    `quota_exceeded` refusal, or a subscription that has spent its whole character allowance.
    A credential that is merely unreadable, restricted or wrong says nothing about credit and
    must leave this alone: `rejected` is a key to replace, not a plan to top up."""

    exhausted: bool = False
    #: Where the latest observation came from, for /health's detail line. Never a key, never
    #: ElevenLabs' own message — those belong in the log.
    source: str = ""
    at: float = 0.0
    observations: int = 0

    def observe(self, *, exhausted: bool, source: str, now: float | None = None) -> None:
        """Record what the account has just said about itself. The newest answer stands."""
        self.exhausted = exhausted
        self.source = source
        self.at = time.time() if now is None else now
        self.observations += 1

    @property
    def detail(self) -> str:
        """How /health explains where it learnt this, in words that name no machine."""
        return f"the ElevenLabs account reported no credit left ({self.source})" if self.exhausted else ""
