"""The notification policy — D-10 and §10, enforced where a future call site will meet it.

THE DEFECT. Sixteen `tablet_notify` events in the live tablet session of 11 September, and
every one of them noise:

  * ELEVEN carried no text at all. The recorded event was `{name:"workspace", tone:"info"}`
    and nothing else — because `toast(words)` called `show()` with a sentence and no `code`,
    and because more than one call site passed a server field straight through with no
    fallback, so an empty `detail` produced an empty message. Eleven notifications nobody can
    name, deduplicate, test, or be held to.
  * FIVE carried a name, and it was `divided`, `merged`, `divided`, `merged`, `divided` —
    state changes the screen itself had just made. The orb visibly dividing IS the
    notification.

THE POLICY. Written in `docs/phase5/NOTIFICATION_POLICY.md`, implemented in `web/notify.js`
(`check`, `MAX_TRANSIENT`, `MAX_GOOD`, `SCREEN_SHOWS`, `CONTROL_SHOWS`) and proved as
behaviour by `tests/web/notify.test.js` under Node, which `tests/test_web_js.py` runs.

WHAT IS PROVED HERE is the half a behaviour test cannot reach: that no CALL SITE on the
tablet can produce one of the sixteen again. A policy the runtime enforces is one a future
call site discovers by having its message silently refused; a policy the source is held to is
one it cannot write in the first place. Both, so the eleven cannot come back either way.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = (ROOT / "web" / "app.js").read_text()
NOTIFY_JS = (ROOT / "web" / "notify.js").read_text()
WEB = ROOT / "web"
POLICY_DOC = ROOT / "docs" / "phase5" / "NOTIFICATION_POLICY.md"


def _code(source: str) -> str:
    """The source with its comments taken out. Every removal in this pass is explained in a
    comment that names the thing removed — so "it is gone" is a question for the code."""
    out = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"^\s*//.*$", "", out, flags=re.M)


APP_CODE = _code(APP_JS)
NOTIFY_CODE = _code(NOTIFY_JS)

# Every call that says something to the owner. `notifyControl` is `notify` with a host.
_CALL = re.compile(r"\bnotify(?:Control)?\(", re.M)


def _calls(source: str) -> list[str]:
    """Each `notify(...)`/`notifyControl(...)` call in the source, brackets balanced, so a
    template literal or a nested `String(... || '...')` comes back whole."""
    out: list[str] = []
    for match in _CALL.finditer(source):
        i = match.end() - 1
        depth, j = 0, i
        while j < len(source):
            if source[j] in "([{":
                depth += 1
            elif source[j] in ")]}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        out.append(source[match.start():j + 1])
    return out


def _call_sites(source: str) -> list[str]:
    """The calls that are call SITES: not the two wrapper definitions, and not a call whose
    first argument is the wrapper's own `message` parameter."""
    return [c for c in _calls(source)
            if not re.match(r"^notify(?:Control)?\((message|words)[,)]", c)]


# =============================================================== the eleven, at the source


def test_toast_is_gone_from_every_file_on_the_tablet():
    """`toast(words)` was the one way to say something without naming it, and eleven of the
    session's sixteen notifications came through it. It is not deprecated, it is removed —
    a wrapper that is still callable is still called."""
    for path in sorted(WEB.glob("*.js")):
        source = _code(path.read_text())
        assert not re.search(r"\btoast\s*\(", source), f"{path.name} still says toast()"
        assert not re.search(r"\bfunction\s+toast\b", source), f"{path.name} still defines toast()"


def test_every_notification_on_the_tablet_carries_a_name():
    """The eleven, made impossible at the source. `code:` is not optional and is not computed
    from something that might be empty: it is a literal here, or `codeOf(…, 'a_literal')`
    which normalises a name that came off the wire and falls back to one that did not."""
    sites = _call_sites(APP_CODE)
    assert len(sites) >= 12, f"the call sites moved: {len(sites)}"
    for call in sites:
        assert "code:" in call, f"a message with no name: {call[:120]}"
        code = re.search(r"code:\s*(.+?)(?:,\s*\w+:|\s*\}\s*\))", call, re.S)
        assert code, call[:160]
        value = code.group(1).strip().rstrip(",").strip()
        if value.startswith("codeOf("):
            assert re.search(r",\s*'[a-z][a-z0-9_]*'\s*\)$", value), f"no literal fallback: {value}"
        else:
            assert re.fullmatch(r"'[a-z][a-z0-9_]*'", value), f"not a plain lower_snake name: {value}"


def _first_argument(call: str) -> str:
    """The words argument of a `notify(...)` call — up to the top-level comma."""
    inner = call[call.index("(") + 1:-1]
    depth, quote = 0, ""
    for i, ch in enumerate(inner):
        if quote:
            if ch == quote and inner[i - 1] != "\\":
                quote = ""
            continue
        if ch in "'\"`":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            return inner[:i]
    return inner


# A sentence: a quoted or templated run with a letter in it and enough of them to be words.
_WORDS = re.compile(r"""(?:'([^']{8,})'|`([^`]{8,})`)""")


def test_no_call_site_can_produce_a_message_with_no_words():
    """The other half of the eleven.

    `toast(data.answer, 'bad')` said nothing at all when the recogniser returned an empty
    answer — and the page went to READY with the screen unexplained. The runtime refuses an
    empty message, which is right and is not enough: a refused message is a call site that
    MEANT to say something and said nothing. So every call site must carry words of its own —
    a literal, a template literal, or a literal behind `||` — so that whatever the Mac
    answered with, there is a sentence to draw.
    """
    for call in _call_sites(APP_CODE):
        first = _first_argument(call)
        assert first.strip(), call[:120]
        found = [m.group(1) or m.group(2) for m in _WORDS.finditer(first)]
        assert any(re.search(r"[A-Za-z]{3}", w) for w in found), \
            f"nothing here is words the owner could read: {call[:140]}"


def test_the_runtime_refuses_what_the_source_review_would_miss():
    """Belt and braces, and the braces are the ones that hold: `check()` is applied to every
    message before it is built, so a call site added by somebody who has not read this file
    is refused at runtime rather than drawn."""
    assert "const verdict = check(m);" in NOTIFY_CODE
    assert "if (!verdict.ok) return refuse(verdict.reason, m);" in NOTIFY_CODE
    for reason in ("no_words", "no_code", "bad_code", "screen_shows", "control_shows"):
        assert f"'{reason}'" in NOTIFY_CODE, reason
    # A refusal is an event. Eleven went unnoticed for an evening because a dropped message
    # left no trace, and a silence is not a policy.
    assert "onRecord('notify_refused'" in NOTIFY_CODE


# ================================================== the five, and §10's three homes


def test_no_call_site_announces_a_state_change_the_screen_already_shows():
    """The five. §10 · a state change updates THE PLACE THE STATE ALREADY LIVES: the orb that
    visibly divided, the two chips that became one, the branch chip that says READY, the tab
    that is now the selected tab, the card that is now on screen."""
    muted = _policy_list("SCREEN_SHOWS") | _policy_list("CONTROL_SHOWS")
    assert {"divided", "merged", "opened", "tab", "draft_saved"} <= muted
    for call in _call_sites(APP_CODE):
        for name in re.findall(r"code:\s*'([a-z][a-z0-9_]*)'", call):
            assert name not in muted, f"§10: `{name}` belongs where the state lives — {call[:100]}"


def test_divided_and_merged_are_not_said_anywhere_on_the_tablet():
    """Removed at the call site as well as refused by name, because a refused message is
    still a line of code claiming the owner needed telling."""
    assert "code: 'divided'" not in APP_CODE and "code: 'merged'" not in APP_CODE
    assert "Divided. Tap a half" not in APP_CODE, "the words are gone too"
    assert "Merged." not in APP_CODE
    # What survived the subtraction was `merge_waiting`: a change the OTHER half staged that
    # nobody had authorised came back with the merge, and no part of the screen showed it.
    # Changed on the owner's ruling of 8 October (DEC-071, ruling 37): Split's merge was
    # deleted, and its one surviving line with it, so this pins it gone rather than present.
    assert "code: 'merge_waiting'" not in APP_CODE
    assert "if (waiting) {" not in APP_CODE, "the merge's last line is back without a merge"


def test_the_three_homes_and_only_the_three():
    """CONTROL-LOCAL, WORKSPACE-LOCAL, GLOBAL — and global is the machine's own state, which
    is two things: it cannot be reached, and it must be updated. Anything else that asks to be
    global is a workspace message that has not been told where it belongs."""
    assert "const CLASSES = ['control', 'workspace', 'global'];" in NOTIFY_CODE
    assert "if (entry.class === 'global' && !m.machine) entry.class = 'workspace';" in NOTIFY_CODE
    globals_ = [c for c in _call_sites(APP_CODE) if "'global'" in c]
    # Was `assert globals_, "the Mac being unreachable is still allowed to be global"`. The one
    # global call site in web/app.js was Split's branch command saying the server did not
    # answer, and it was deleted with Split on the owner's ruling of 8 October (DEC-071,
    # ruling 37). That the machine's own state is still ALLOWED to be global is the notify.js
    # line asserted above, and tests/web/notify.test.js shows a `machine: true` message there.
    for call in globals_:
        assert "machine: true" in call, f"only the machine's own state is global: {call[:100]}"


def test_a_refusal_about_one_control_is_drawn_beside_that_control():
    """§10's second home, and the three that moved into it this pass: a rejected typed value
    (it was a workspace line, 788px from the thumb that typed it), a row action the Mac
    refused, and a row action that got no answer at all."""
    for code in ("field_refused", "row_refused", "command_refused", "card_waiting", "nothing_open"):
        site = [c for c in _call_sites(APP_CODE) if f"'{code}'" in c]
        assert site, code
        assert all(c.startswith("notifyControl(") for c in site), f"{code} is about a control: {site}"


# ================================================================ the caps, and the doc


def _policy_list(name: str) -> set[str]:
    block = re.search(rf"const {name} = \[(.*?)\];", NOTIFY_CODE, re.S)
    assert block, name
    return set(re.findall(r"'([a-z][a-z0-9_]*)'", block.group(1)))


def test_the_caps_are_small_and_are_the_numbers_the_doc_justifies():
    """N is chosen, not inherited. Two transient rows is 88px of a ~700px workbench screen;
    three is 132px and starts costing a card. One success, because one event is one "done"."""
    assert "const MAX_TRANSIENT = 2;" in NOTIFY_CODE
    assert "const MAX_GOOD = 1;" in NOTIFY_CODE
    assert "const MAX_PER_HOST = 3;" in NOTIFY_CODE
    doc = POLICY_DOC.read_text()
    assert "MAX_TRANSIENT" in doc and "MAX_GOOD" in doc
    assert re.search(r"MAX_TRANSIENT\D{0,40}2", doc), "the doc has to name the number it justifies"


def test_deduplication_is_by_name_and_not_by_sentence():
    """It used to include the text, so every message carrying a count, a name or an amount
    defeated it by definition — "1 change still waiting" and "2 changes still waiting" were
    two rows about one recurring event."""
    assert "return `${entry.class}:${entry.code}:${entry.branch || ''}`;" in NOTIFY_CODE
    assert "${entry.text}" not in NOTIFY_CODE.split("function keyOf")[1].split("}")[0]


def test_the_policy_is_written_down_where_somebody_can_be_held_to_it():
    """A policy that exists only as code is a policy only its author knows. §10's three homes,
    the four refusals, the two caps and the D-10 evidence are all in the document, and the
    document names the file that enforces each one."""
    assert POLICY_DOC.exists(), POLICY_DOC
    doc = POLICY_DOC.read_text()
    for needed in ("CONTROL-LOCAL", "WORKSPACE-LOCAL", "GLOBAL",
                   "no_words", "no_code", "screen_shows", "control_shows",
                   "web/notify.js", "tests/web/notify.test.js", "D-10"):
        assert needed in doc, needed
    assert len(doc) > 3000, "a policy others can be held to, not a note"


@pytest.mark.parametrize("code", sorted({"divided", "merged", "opened", "tab", "tab_changed",
                                         "home", "back", "next", "navigated",
                                         "draft_saved", "saved", "sent", "archived", "ready"}))
def test_each_state_change_the_brief_names_is_muted_by_name(code):
    """§10's own examples, one test each: "Draft saved" becomes the Draft control; a branch
    result finishing says READY on the branch chip; an order opening says nothing; a tab
    changing says nothing; a split says nothing, because the UI visibly becoming split is
    sufficient."""
    assert code in (_policy_list("SCREEN_SHOWS") | _policy_list("CONTROL_SHOWS"))
