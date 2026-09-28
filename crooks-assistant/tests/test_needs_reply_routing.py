"""No way of asking who needs a reply reads as a change, and every instruction to reply does.

On 2026-09-24 "customers who need a reply?" was filed as "asks for a change", because "reply"
was read as an instruction to send one. The instructions themselves — "reply to Mia", "send a
reply to order 2044" — must still be the change they are.

The rule that tells them apart lived in the word-matching router until that was removed on
28 September 2026 (every sentence is now a model turn). It stays in one place, the report's
request contract (app/observability/contract.py), because the report still grades a turn by
whether a change was asked for — and these are the sentences that hold it.
"""

from __future__ import annotations

import pytest

from app.observability import contract

QUESTIONS = [
    "any customers who need a reply",
    "customers who need a reply?",
    "anyone waiting on a reply",
    "who's waiting for a reply",
    "does anyone need an answer from us",
    "any emails I haven't replied to",
    "is anyone waiting on me",
    "who needs a reply",
    "who needs replying to",
    "which customers are waiting on a reply",
]


@pytest.mark.parametrize("said", QUESTIONS)
def test_no_way_of_asking_who_needs_a_reply_is_a_change(said):
    assert not contract._is_change(said), f"{said!r} was read as a change"
    assert contract.contract_of(said) != contract.WRITE_INTENT, said


INSTRUCTIONS = [
    "reply to Mia",
    "send a reply to order 2044",
    "reply to her about this",
    "draft a reply to Mia",
    "write a reply to Mia",
]


@pytest.mark.parametrize("said", INSTRUCTIONS)
def test_an_instruction_to_reply_is_still_the_change_it_is(said):
    assert contract._is_change(said), f"{said!r} lost its instruction"
    assert contract.contract_of(said) == contract.WRITE_INTENT, said
