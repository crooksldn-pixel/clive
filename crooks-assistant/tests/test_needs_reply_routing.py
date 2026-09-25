"""Every way of asking who needs a reply is the inbox answer, and no way of asking is a change.

On 2026-09-24 the owner asked "any customers who need a reply" twice and once got an answer
about orders to go out. On the trunk "anyone waiting on a reply" fell below needs_reply's floor
and went to the model, and "customers who need a reply?" was refused as "asks for a change",
because "reply" was read as an instruction to send one. The instructions themselves — "reply
to Mia", "send a reply to order 2044" — must still be the change they are.
"""

from __future__ import annotations

import pytest

from app.families import load_all
from app.fastpath import choose_lane, recipe_for
from app.fastpath.intent import family, resolve
from app.session.branch import Branch

load_all()
import app.fastpath.library  # noqa: E402, F401 — registers the core recipes


@pytest.fixture()
def branch():
    return Branch(branch_id="br_test", session_id="s1")


QUESTIONS = [
    "any customers who need a reply",
    "customers who need a reply?",
    "anyone waiting on a reply",
    "who's waiting for a reply",
    "does anyone need an answer from us",
    "any emails I haven't replied to",
    "is anyone waiting on me",
    # What already worked on the trunk, held so the fix cannot trade one for another.
    "who needs a reply",
    "who needs replying to",
    "which customers are waiting on a reply",
]


@pytest.mark.parametrize("said", QUESTIONS)
def test_every_way_of_asking_who_needs_a_reply_is_the_inbox_answer(said, branch):
    intent = resolve(said, branch=branch)
    assert not intent.signals.mutation, f"{said!r} was read as a change"
    assert intent.reason != "asks for a change", said
    assert intent.family == "needs_reply", (said, intent.public())
    assert intent.confidence > family("needs_reply").floor, (said, intent.confidence)
    recipe = recipe_for(intent.family)
    assert recipe is not None
    lane, why = choose_lane(intent, recipe=recipe, text=said)
    assert lane == "FAST", (said, why)


INSTRUCTIONS = [
    "reply to Mia",
    "send a reply to order 2044",
    "reply to her about this",
    "draft a reply to Mia",
    "write a reply to Mia",
]


@pytest.mark.parametrize("said", INSTRUCTIONS)
def test_an_instruction_to_reply_is_still_the_change_it_is(said, branch):
    intent = resolve(said, branch=branch)
    assert intent.signals.mutation, f"{said!r} lost its instruction"
    assert intent.family == "" and intent.reason == "asks for a change", (said, intent.public())
