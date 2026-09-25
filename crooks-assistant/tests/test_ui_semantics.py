"""The product's knowledge of its own interface (§15).

The live hour's seventh turn:

    "What does the split button do?"
    "I don't know what that button is — not something I control, so best to check with
     whoever built the tablet screen."

The five questions in §15 are the acceptance test, and each of them is a case below. The
other half of the file is the bound: the manifest may not answer a question about the SHOP,
it may not name a control that does not exist, and it may not drift from the command registry
that implements the controls.
"""

from __future__ import annotations

import pytest

from app import commands
from app.observability import ui_semantics

# ------------------------------------------------------------------ the five questions


@pytest.mark.parametrize(("said", "key", "must_say"), [
    ("What does the split button do?", "split", ("two", "half")),
    ("How do I go back?", "back", ("before",)),
    ("How do I type instead of speaking?", "composer", ("typ",)),
    ("What does Applying mean?", "applying", ("server",)),
    ("How do I get back to this order?", "return_here", ("Back",)),
])
def test_the_five_questions_are_answered_from_the_manifest(said, key, must_say):
    """§15's five questions, each answered by one named entry — and not by the model."""
    answer = ui_semantics.lookup(said)
    assert answer is not None, said
    assert answer.entry.key == key, f"{said!r} → {answer.entry.key}"
    for word in must_say:
        assert word.lower() in answer.words.lower(), (said, answer.words)
    assert len(answer.words) > 40, "an answer worth speaking, not a label"


def test_the_split_answer_no_longer_disclaims_the_interface():
    """The exact sentence from the live session, held against what is said now."""
    said = "What does the split button do?"
    answer = ui_semantics.lookup(said)
    assert answer is not None
    words = ui_semantics.spoken(answer).lower()
    for disclaimer in ("i don't know", "not something i control", "whoever built",
                       "check with whoever", "the tablet screen"):
        assert disclaimer not in words, words
    assert "divides the conversation in two" in words


# ------------------------------------------------------------------------ the bounds


def test_a_question_about_the_shop_is_not_answered_by_the_manifest():
    """The word "back" is in half of what a shop owner says. None of these is a question
    about a button, and the manifest must not take any of them."""
    for said in (
        "has the order come back yet",
        "send it back to them",
        "what did we sell today",
        "which customers need replying to",
        "refund the postage on 1938",
        "is that order going to be late",
        "read me the address",
    ):
        assert ui_semantics.lookup(said) is None, said


def test_the_manifest_cannot_drift_from_the_command_registry():
    """Every entry that names a semantic command names one that exists, and takes that
    command's own words with it. A control renamed in app/commands.py fails here."""
    assert ui_semantics.check() == []
    named = [e for e in ui_semantics.manifest() if e.command]
    assert len(named) >= 6, "Back, Home, Next, Previous, the tabs, the halves, the dock"
    for entry in named:
        assert commands.get(entry.command) is not None, entry.command
        assert entry.derived_what == commands.get(entry.command).what, entry.key


def test_back_home_and_next_mean_what_the_commands_mean():
    """Three controls the owner said had regressed, each described by the thing that runs it."""
    back, home, nxt = (ui_semantics.get(k) for k in ("back", "home", "next"))
    assert back.command == "navigation.back" and home.command == "navigation.home"
    assert nxt.command == "workflow.next"
    # Home is the start of the trail, not a replayed record — the D-10 distinction, in words.
    assert "start of this half's trail" in home.what
    assert "trail" in back.where and "list" in nxt.what
    # Next is the cursor over a set; Back is the trail. They are described as different things.
    assert "list" in nxt.what and "before this one" in back.what


def test_the_gestures_come_from_the_action_grammar():
    """The four approval gestures are the ones the tablet implements, from the one table that
    decides them — never a second list kept here."""
    from app.actions import grammar

    approval = ui_semantics.get("approval")
    assert approval is not None
    for kind in grammar.KINDS:
        assert grammar.words_for(kind)["label"].lower() in approval.where.lower(), kind
    assert "never by the assistant" in approval.what


def test_the_dock_names_the_landings_that_exist():
    from app.families import load_all
    from app.families.landings import AREAS

    load_all()
    dock = ui_semantics.get("dock")
    for area in AREAS:
        assert area in dock.what, area


def test_the_branch_states_are_the_sessions_own():
    entry = ui_semantics.get("branch_states")
    for state, _what in ui_semantics.BRANCH_STATES:
        assert state.lower() in entry.what.lower(), state


def test_the_manifest_is_a_card_the_tablet_can_already_draw():
    """Groups shaped for the `capability` renderer, which is in the tablet's vocabulary. A
    manifest that needed a new card type would be D-15 all over again."""
    groups = ui_semantics.groups()
    assert len(groups) == len(ui_semantics.GROUPS)
    for group in groups:
        assert group["items"] and all(i["what"] and i["name"] for i in group["items"])
        assert all(i["state"] == "ready" for i in group["items"])


def test_nothing_in_the_manifest_can_change_anything():
    """It is a table of sentences. Nothing it calls can stage, arm or commit a change."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(ui_semantics))
    called = {node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
              for node in ast.walk(tree) if isinstance(node, ast.Call)}
    for forbidden in ("propose", "stage", "arm", "commit", "execute", "run"):
        assert forbidden not in called, forbidden
    # And every entry it does reach for is a read-only semantic command.
    voice_or_touch = {c["name"] for c in commands.public()}
    for entry in ui_semantics.manifest():
        assert not entry.command or entry.command in voice_or_touch
