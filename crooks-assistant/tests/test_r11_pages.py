"""Round 11 of the deploy review, the pages: R9-B2-B-07, the Mac's half.

The app's service worker (web/sw.js) keeps one page, the answer at '/', and only when it is this
build's own (`isShell`: a 200, HTML, not the end of a redirect, carrying this build's mark), and
opens it when the Mac cannot be reached — to whoever opens the browser then. That is safe only if
what the Mac serves at '/' is the same data-free page for every login and every session: then
there is nothing of anyone's in it to keep. This proves that half, with the app's own routes and
middleware (app/main.py `index` and `guard_and_freshness`): two different logins on the list, the
server itself, with a screen's cookie or without, compressed or not, all get byte for byte
web/index.html with the build id written in, and nothing else — no cookie set, no login, nothing
the owner asked for before. A login not on the list and an anonymous caller through the proxy
get a refusal that is not HTML, which the worker never keeps. The worker's half — that it keeps
that page and nothing else, and opens it offline after an owner's load — is tests/web/sw.test.js.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests import fake_credentials

FIRST = {"Tailscale-User-Login": "owner@example.com", "X-Forwarded-For": "100.64.0.9"}
SECOND = {"Tailscale-User-Login": "packer@example.com", "X-Forwarded-For": "100.64.0.12"}
STRANGER = {"Tailscale-User-Login": "someone@example.com", "X-Forwarded-For": "100.64.0.3"}
ANONYMOUS = {"X-Forwarded-For": "100.64.0.4"}          # through the proxy with no login: Funnel, a tagged node


def test_the_page_at_the_root_is_the_same_data_free_file_for_every_login_and_session(tmp_path, monkeypatch):
    """R9-B2-B-07 (round 11): two logins, the server itself, any cookie, any encoding — one page,
    the file on disk with the build written in; a caller who may not use CLIVE is refused, not
    served a page the worker could keep."""
    monkeypatch.setenv("CROOKS_OBJECTIVES_DIR", str(tmp_path / "objectives"))
    from app.main import WEB_DIR, app
    from app.routes.displays import SCREEN_COOKIE

    with TestClient(app) as client:
        runtime = app.state.runtime
        # Both logins taken as really arriving through `tailscale serve` (the proof of that is
        # tests/test_proxy_identity.py), and both on the list.
        runtime.settings = runtime.settings.model_copy(update={
            "tailscale_verify": False, "allowed_logins": "owner@example.com,packer@example.com"})
        app.state.allowed_logins = runtime.allowed_logins
        build = client.get("/ping").json()["build"]
        expected = (WEB_DIR / "index.html").read_text(encoding="utf-8").replace("__BUILD__", build).encode("utf-8")
        # The owner has used CLIVE first (a screen named, so a cookie is in the browser): nothing
        # of that session reaches the page.
        named = client.post("/displays/register", json={"name": "Packing screen"}, headers=FIRST)
        assert named.status_code == 200
        client.cookies.clear()
        cookie = {"Cookie": f"{SCREEN_COOKIE}={fake_credentials.body('r11-pages-screen-cookie', 43)}"}
        pages = set()
        for who in (FIRST, SECOND, {}):
            for extra in ({}, cookie, {"Accept-Encoding": "gzip"}, {"Accept-Encoding": "identity"}):
                page = client.get("/", headers={**who, **extra})
                assert page.status_code == 200
                assert page.headers["content-type"].startswith("text/html")
                assert page.headers["cache-control"] == "no-cache"
                assert "set-cookie" not in page.headers, "the page hands nobody anything"
                assert not page.history, "never the end of a redirect"
                pages.add(page.content)
        assert pages == {expected}, "one page for everyone: the file, with the build written in"
        text = expected.decode("utf-8")
        for words in ("owner@example.com", "packer@example.com", "Packing screen", "__BUILD__"):
            assert words not in text
        # A caller who may not use CLIVE is refused the page too, and the refusal is not a page.
        for who in (STRANGER, ANONYMOUS):
            refused = client.get("/", headers=who)
            assert refused.status_code == 403
            assert refused.headers["content-type"].startswith("application/json")
