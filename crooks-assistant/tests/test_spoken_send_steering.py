"""The correction "don't save a draft, send it" is steered to a send, not to a draft.

Found in round 10 while restoring the spoken send-instead scenario (the 2026-09-28 deploy
review, round 9, H-04; experience/scenario_packs/compose.py `compose_send_spoken`). The turn
route hands the model one line saying whether a sentence asks for a draft or a send
(`app/routes/turn.py::_draft_or_send`). It matches words and does not read a negation, so:

    "no, don't save a draft, send it"          → "Stage the DRAFT"
    "No, don't save a draft. You want it sent." → "This asks for a DRAFT … not a send"

The second is the bench's own sentence. The Mac tells the model the opposite of what the owner
said. Nothing is SENT by that — every send waits for the hold — but the owner asked for a send
and is handed a draft, which is the bench failure back again by another road.

The turn route belongs to the turn fixer this round, so this is held as a strict expected
failure: the moment `_draft_or_send` reads the correction right, it passes, and the marker must
come off.
"""

from __future__ import annotations

import pytest


@pytest.mark.xfail(strict=True, reason=("app/routes/turn.py _draft_or_send does not read 'don't save a draft' as a "
                                        "negation (round 10 handoff to the turn fixer); remove this marker when it does"))
@pytest.mark.parametrize("said", [
    "no, don't save a draft, send it",
    "No, don't save a draft. You want it sent.",
])
def test_a_correction_from_draft_to_send_is_steered_to_a_send(said):
    from app.routes.turn import _draft_or_send

    line = _draft_or_send(said)
    assert "gmail_send" in line and "DRAFT" not in line, line


def test_a_plain_request_for_a_draft_is_still_a_draft():
    """The half that works today and must keep working."""
    from app.routes.turn import _draft_or_send

    assert "DRAFT" in _draft_or_send("draft a reply to Millie")
    assert "gmail_send" in _draft_or_send("send it instead")
