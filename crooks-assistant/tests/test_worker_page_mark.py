"""Round 10 of the deploy review, B-07: the one page the app's worker keeps is the page the Mac
serves at '/', and nothing else.

What '/' is (app/main.py `index`): web/index.html with the build id written in, answered before
anything is asked for, byte for byte the same for every login (tests/test_displays.py
test_the_pages_a_browser_may_keep_are_the_same_for_every_login). The worker (web/sw.js) keeps an
answer at '/' only when it is a 200, HTML, not the end of a redirect, and carries this build's
own mark (`PAGE_MARK`); anything else is passed on and never kept (tests/web/sw.test.js). This
proves the two halves meet, end to end: the worker the Mac serves names exactly the mark in the
page the Mac serves, for the same build, and that page carries nothing of anyone's."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_the_page_at_the_root_carries_the_mark_the_served_worker_keeps_it_by(tmp_path, monkeypatch):
    monkeypatch.setenv("CROOKS_OBJECTIVES_DIR", str(tmp_path / "objectives"))
    from app.main import app

    with TestClient(app) as client:
        build = client.get("/ping").json()["build"]
        worker = client.get("/sw.js").text
        page = client.get("/")
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert f"const BUILD = '{build}';" in worker
    # The mark the worker keeps the page by, as the worker builds it from its own build id.
    assert "const PAGE_MARK = '<meta name=\"crooks-build\" content=\"' + BUILD + '\">';" in worker
    assert f'<meta name="crooks-build" content="{build}">' in page.text
    # Only the build id is written in: the page is the file on disk otherwise, so nothing of
    # anyone's can be in what the worker keeps.
    from app.main import WEB_DIR

    assert page.text == (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("__BUILD__", build)
