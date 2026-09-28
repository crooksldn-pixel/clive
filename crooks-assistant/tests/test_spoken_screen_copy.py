"""A copy of the screen never keeps what the owner is saying (the 2026-09-28 deploy review, round
9, F-02).

`sanitise_markup` treated `data-spoken` — the page's mark on the ask bar's live words
(web/live-voice.js, web/alpha.js #ask-words and #ask-heard) — as an ordinary attribute: the text
under the marked element was kept, scrubbed only of what the timeline's rule recognises (a
credential, a contact detail, a customer name already returned), which live dictation mostly is
not. And `data-words` was kept whenever its value looked like a token. With
CROOKS_SCREEN_SNAPSHOTS on, the owner's dictation would have been written into the reports.

Now the text of a spoken element and of everything inside it is masked like a textarea's, its
words-bearing attributes are kept empty, and `data-words` is kept empty wherever it is. The words
below are arbitrary speech, deliberately nothing the scrubber would recognise.
"""

from __future__ import annotations

import pytest

from app.observability.screens import DATA_FREE_TEXT, SPOKEN_MARK, sanitise_markup

SAID = "move the black hoodie to the Leeds shop and tell Rowan tomorrow"


def _words(text: str) -> set[str]:
    return {w for w in text.replace("<", " ").replace(">", " ").split() if w.isalpha()}


@pytest.mark.parametrize("mark", ['data-spoken="true"', "data-spoken", 'data-spoken=""', 'DATA-SPOKEN="false"'])
def test_the_live_words_are_masked_however_the_mark_is_written(mark):
    page = (f'<div class="ask"><span class="ask-words-frame" aria-hidden="true"><span id="ask-words" class="ask-words" '
            f'{mark}>{SAID}</span></span><p>Orders to send</p></div>')
    copy = sanitise_markup(page)
    assert not (_words(SAID) - {"the", "to", "and"}) & _words(copy), copy
    assert "•" in copy and "Orders to send" in copy, "the rest of the screen draws as it did"


def test_everything_inside_a_spoken_element_is_masked_and_nothing_after_it():
    page = (f"<div><span data-spoken><b>{SAID}</b> and <i>then Rowan</i></span> after</div>"
            f"<div><span data-spoken>left open {SAID}</div><p>still visible</p>")
    copy = sanitise_markup(page)
    assert "Rowan" not in copy and "hoodie" not in copy and "left open" not in copy, copy
    assert "after" in copy and "still visible" in copy, copy


def test_words_in_a_spoken_elements_attributes_are_kept_empty():
    page = (f'<span data-spoken title="{SAID}" aria-label="{SAID}" class="ask-heard" id="ask-heard">'
            f'<img alt="{SAID}" width="4"></span><span title="Orders">x</span>')
    copy = sanitise_markup(page)
    assert "hoodie" not in copy and 'title=""' in copy and 'aria-label=""' in copy and 'alt=""' in copy, copy
    assert 'class="ask-heard"' in copy and 'title="Orders"' in copy, "outside it, attributes are as before"


@pytest.mark.parametrize("value", [SAID, "rowan-mitcham-1930", "two", "leeds_shop"])
def test_data_words_is_kept_empty_whatever_it_holds(value):
    copy = sanitise_markup(f'<div class="ask-bar" data-words="{value}"></div>')
    assert 'data-words=""' in copy and value not in copy, copy
    assert "data-words" in DATA_FREE_TEXT and SPOKEN_MARK == "data-spoken"


def test_a_textarea_and_ordinary_text_are_as_before():
    copy = sanitise_markup("<p>Rowan's order</p><textarea>typed words</textarea>")
    assert "Rowan's order" in copy or "[name]" in copy
    assert "typed" not in copy and "•" in copy
