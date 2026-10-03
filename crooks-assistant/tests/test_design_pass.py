"""The design pass of 3 October 2026: what the page promises, held without a browser.

The behaviour is proved under Node with the page's own code (tests/web/design.test.js for the
renderer: "Not now", each fact once, the warm colour only for what needs him; and
tests/web/startup.test.js for a tap during the start-up), run here so a run of the suite runs
them, skipped only where Node is absent as tests/test_web_js.py does. The rest is the page's
own text: the stylesheet that carries the pass is loaded last and kept in the offline shell, the
chip is Home, and nothing in the pass hides the dock from the 601 px Tab A.
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


@needs_node
@pytest.mark.parametrize("name", ["design.test.js", "startup.test.js"])
def test_the_page_under_node(name):
    result = subprocess.run([NODE, "--test", str(ROOT / "tests" / "web" / name)],
                            capture_output=True, text=True, timeout=120, cwd=ROOT)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
    assert "# fail 0" in result.stdout


def test_the_design_stylesheet_is_loaded_last_and_kept_offline():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    sheets = re.findall(r'<link rel="stylesheet" href="([^"]+)">', index)
    assert sheets[-1] == "/static/design.css", "it overrides the sheets before it, so it comes after all of them"
    assert "'/static/design.css'," in (WEB / "sw.js").read_text(encoding="utf-8")


def test_the_chip_is_home():
    index = (WEB / "index.html").read_text(encoding="utf-8")
    chip = index[index.index('<button id="home-btn"'):index.index("</button>", index.index('<button id="home-btn"'))]
    assert 'aria-label="Home"' in chip and "<span>Home</span>" in chip and "CLIVE" not in chip


def test_the_dock_is_hidden_only_on_a_phone():
    """The 601 px Tab A is George's tablet: alpha.css hid the dock up to 640 px. The design pass
    shows it on every width above a phone's and hides it at 480 px and under."""
    css = (WEB / "design.css").read_text(encoding="utf-8")
    shown = css[css.index("@media (min-width:481px){\n  body.alpha{--alpha-dock"):]
    assert "body.alpha .dock{\n    display:flex" in shown
    assert "@media (max-width:480px){ body.alpha .dock{display:none} }" in css
    # And it owns its band in both modes, so the ask bar sits above it rather than over it.
    assert "body.alpha .app,body.alpha[data-mode=\"context\"] .app{padding-bottom:calc(var(--alpha-dock)" in shown


def test_the_start_up_takes_no_touches_of_its_own():
    css = (WEB / "startup.css").read_text(encoding="utf-8")
    rule = css[css.index(".startup{"):css.index("}", css.index(".startup{"))]
    assert "pointer-events:none" in rule
