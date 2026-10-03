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


def test_home_tells_the_mac_the_screen_went():
    """Review of the design pass (3 Oct): Home drew the home on the page and told the Mac nothing,
    so a reload redrew the order that had been up. `screen.home` clears the Mac's copy of the
    screen as "close that" does: put away, still there for "pull that back up", the trail kept."""
    from app import commands
    from app.families import load_all
    from app.session.models import Session

    load_all()
    spec = commands.get("screen.home")
    assert spec is not None and spec.touch, "the page can post it"
    session = Session(session_id="home")
    branch = session.branch()
    branch.shown([{"type": "order", "data": {"order_id": "gid://shopify/Order/1957", "order_number": "#1957"}}],
                 "Order 1957.", "show me 1957")
    trail = list(branch.nav)
    assert branch.public()["has_workspace"] is True
    out = commands.run("screen.home", commands.Ctx(runtime=None, session=session, branch=branch))
    assert out.ok and "recipe" not in out.changed, "it reads nothing and draws nothing"
    assert branch.public()["has_workspace"] is False, "a reload has no order to put back"
    assert [e["card"]["type"] for e in branch.shown_before] == ["order"], "pull that back up still finds it"
    assert list(branch.nav) == trail


def test_the_page_posts_it_on_home():
    app_js = (WEB / "app.js").read_text(encoding="utf-8")
    body = app_js[app_js.index("async function goHome()"):app_js.index("\n}\n", app_js.index("async function goHome()"))]
    assert "semanticCommand('screen.home')" in body
    assert "navigation.home" not in body, "the orders landing stays the Orders icon's"


def test_not_now_with_no_answer_does_not_claim_the_change_is_waiting():
    """Review of the design pass (3 Oct): a "Not now" that gets no answer may have withdrawn the
    change and lost the reply, so the page says it may still be waiting, not that it is."""
    app_js = (WEB / "app.js").read_text(encoding="utf-8")
    body = app_js[app_js.index("async function declineAction("):app_js.index("\n}\n", app_js.index("async function declineAction("))]
    assert "\"Couldn't reach CLIVE \\u2014 it may still be waiting.\"" in body
    assert "so it is still waiting" not in body
