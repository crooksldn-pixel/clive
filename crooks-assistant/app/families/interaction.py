"""Stop, tapped (§24).

An interruption that produces a paragraph is not an interruption. The tablet's stop control
posts `interaction.stop`, and this stops the three things the Mac owns that keep going after
the owner has stopped listening. It reads nothing, stages nothing and consults no model: a
button that names what it does needs nothing understood.

The word "stop" said out loud is not handled here. Every sentence is a model turn
(app/routes/turn.py), and holding the orb to say anything already silences the voice on the
tablet before the words are sent.
"""

from __future__ import annotations

import logging
from typing import Any

from app.commands import Command, Outcome
from app.commands import Ctx as CommandCtx
from app.commands import register as register_command

log = logging.getLogger("crooks.families.interaction")


def _stop(runtime: Any, session: Any, branch: Any) -> dict[str, Any]:
    """Everything an interruption stops, and nothing it does not.

    Three things, which are §24's three, and each is state the Mac already owns:

    * the VOICE. Any answer still being synthesised is dropped, so the tablet is not handed
      audio for a sentence the owner has already stopped listening to.
    * the WAITING CONTROL. A tapped Reply or Add a note is armed for the next sentence; leaving
      it armed after a stop means the next thing said is read as its words.
    * the BACKGROUND DISPLAY. A half working in the background pulses at him. Asked to stop,
      it stops asking for his attention; it is NOT cancelled, because he did not say cancel.

    Nothing is undone and nothing is withdrawn. A staged change is the action engine's, and an
    interruption is not an authorisation to throw one away.
    """
    stopped: dict[str, Any] = {}
    voice = getattr(runtime, "voice", None)
    if voice is not None and hasattr(voice, "cancel_prefetches"):
        try:
            stopped["voice"] = int(voice.cancel_prefetches())
        except Exception as exc:  # noqa: BLE001 — a voice that cannot be stopped is not a crash
            log.warning("the voice could not be stopped: %s", exc)
    if branch is not None and getattr(branch, "voice_context", None):
        branch.release_voice()
        stopped["listening"] = True
    quietened = 0
    for half in (getattr(session, "branches", {}) or {}).values():
        if half is branch or str(getattr(half, "status", "")) != "BACKGROUND":
            continue
        if getattr(half, "task", None):
            # Still working, and no longer asking to be looked at. `idle()` is the branch's own
            # word for "nothing to report" (app/session/branch.py).
            half.idle()
            quietened += 1
    if quietened:
        stopped["background"] = quietened
    return stopped


def _stop_command(ctx: CommandCtx) -> Outcome:
    """The interruption, tapped."""
    stopped = _stop(ctx.runtime, ctx.session, ctx.branch)
    return Outcome(answer="Stopped.", changed={"stopped": stopped, "listening_for": None})


register_command(Command("interaction.stop", "Stop the voice and stop listening", _stop_command, voice=False))
