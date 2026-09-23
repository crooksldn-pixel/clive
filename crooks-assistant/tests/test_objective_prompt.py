"""George reads objective records on his phone: they must speak to him, not about him."""

from __future__ import annotations

from app.kb.loader import build_system_prompt, load


def test_objectives_section_teaches_verbatim_second_person_no_machine(tmp_path):
    prompt = build_system_prompt(load(tmp_path))
    assert "# Objectives the owner keeps alive" in prompt
    assert "shown to the owner verbatim" in prompt
    assert "second person" in prompt
    assert 'never as "the owner"' in prompt
    assert "Never name the machine" in prompt


def test_rest_of_the_prompt_is_unchanged(tmp_path):
    prompt = build_system_prompt(load(tmp_path))
    for phrase in (
        "read aloud", "No markdown", "ask which one", "cannot change anything",
        "REFUSED", "AMBER", "no tool call", "objective_list", "objective_note",
        "missing_capability", "ask_owner",
    ):
        assert phrase in prompt, phrase
