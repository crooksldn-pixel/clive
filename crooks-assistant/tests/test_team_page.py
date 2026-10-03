"""The team's page (web/today*.js) under Node, and what its code may reach, read from the code itself.

tests/web/today-say.test.js (the sentence reader) and tests/web/today-voice.test.js (hold to speak
on the phone's own recogniser) are run here so CI runs them. And the page is held to the team's own
routes: what it sends goes to /today/*, /turn and the cards' /actions/*, the owner's voice path is
never asked from it, a recording is never made or uploaded, and nothing it builds is markup.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="node is not installed here")
TEAM_FILES = ("today.js", "today-say.js", "today-voice.js")


@needs_node
@pytest.mark.parametrize("name", ["today-say.test.js", "today-voice.test.js"])
def test_the_team_pages_parts_under_node(name):
    done = subprocess.run([NODE, "--test", str(ROOT / "tests" / "web" / name)], cwd=ROOT, capture_output=True, text=True,
                          timeout=120)
    assert done.returncode == 0, (done.stdout + done.stderr)[-3000:]


def _code(name: str) -> str:
    """The file without its comments, which name the owner's routes on purpose to say why not."""
    source = (WEB / name).read_text(encoding="utf-8")
    return re.sub(r"^\s*//.*$", "", re.sub(r"/\*.*?\*/", "", source, flags=re.S), flags=re.M)


def test_the_team_page_sends_only_to_the_teams_own_routes():
    paths = set()
    for name in TEAM_FILES:
        code = _code(name)
        paths |= set(re.findall(r"""(?:call|post)\(\s*['"`](/[^'"`?$]*)""", code))
        paths |= set(re.findall(r"""fetch\(\s*['"`](/[^'"`?$]*)""", code))
    assert paths, "the page talks to the Mac somewhere"
    for path in paths:
        assert path == "/turn" or path.startswith(("/today/", "/actions/")), path
    assert {"/today/claim", "/today/packed", "/today/done", "/today/release", "/today/undo", "/today/flag", "/turn"} <= paths


def test_the_team_page_never_asks_for_the_owners_voice_or_records_anything():
    for name in TEAM_FILES:
        code = _code(name)
        for owners in ("/voice/live", "/speak", "MediaRecorder", "getUserMedia", "FormData", "audio/", "new Blob"):
            assert owners not in code, f"{name} uses {owners}"


def test_the_page_loads_the_shared_parts_it_reuses_and_nothing_of_the_owners_app():
    page = (WEB / "today.html").read_text(encoding="utf-8")
    scripts = re.findall(r'<script src="/static/([^"?]+)', page)
    assert scripts == ["orb.js", "objective-touch.js", "today-say.js", "today-voice.js", "today.js", "today-owner.js"]
    assert 'id="ask-text"' in page and 'id="mic"' in page                 # the ask bar, on every screen


def test_where_the_teams_spoken_words_go_is_said_truly_and_george_is_told():
    """The review of 3 October: "the recording never leaves the phone" was not true. The phone's own
    speech service (Google's on Chrome and Android, Apple's on Safari) hears the audio; CLIVE's Mac
    does not. The doc and the voice file say so, and George's People screen says it in one line."""
    doc = (ROOT / "docs" / "TEAM.md").read_text(encoding="utf-8")
    voice = (WEB / "today-voice.js").read_text(encoding="utf-8")
    owner = (WEB / "today-owner.js").read_text(encoding="utf-8")
    for text in (doc, voice):
        assert "never leaves the phone" not in text and "Nothing is\n * recorded" not in text
        assert "Google" in text and "Apple" in text and "speech service" in text
    assert "their phone's speech service hears them (Google's on Android, \" +\n    \"Apple's on an iPhone)" in owner
    assert "box.append(el('p', 'hint', SPEECH_NOTE));" in owner
