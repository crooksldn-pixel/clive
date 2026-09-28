"""YouTube on the owner's screens: "play the Heat trailer on the TV", then "turn it up".

What is held here. A link is read only when it is YouTube's own; a search offers only what can
actually play on a screen, and needs the stored key, which travels in a header and never in an
address, a log line or an answer. A video pane keeps an id, a title, a channel and numbers, and
never an address. Every command the owner gives it is applied exactly once however many arrive
between two of the screen's asks. How it is playing is the screen's own word, held in memory,
not faster than the store takes it, and only from the device holding the screen's key. Every
route and tool is the owner's alone, and a video is never marked done, ticked or paged.

YouTube is a mocked transport throughout. Nothing here reaches the network.
"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

from app.clients import youtube
from app.displays import store as store_module
from app.displays import views
from app.displays.store import PLAYING_GAP_S, DisplayError, NotPaired, NotThisScreen
from app.tools import authority, gate
from app.tools.gate import Tier
from app.tools.registry import ToolError
from tests import fake_credentials as fake
from tests.test_displays import OWNER, Tick, app_with, as_screen, later, owner, pair, run

KEY = fake.google_api_key("youtube")
HEAT = "dQw4w9WgXcQ"
OTHER = "aqz-KE-bpKQ"




@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives" / "displays.json", mono=Tick())


# --------------------------------------------------------------------------- YouTube itself


class YouTube:
    """The Data API and oEmbed, as a transport: `routes` maps a path to (status, body)."""

    def __init__(self) -> None:
        self.calls: list[httpx.Request] = []
        self.routes: dict[str, object] = {}

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        answer = self.routes.get(request.url.path)
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            answer = answer(request)
        if answer is None:
            return httpx.Response(404, json={"error": {"errors": [{"reason": "notFound"}]}})
        status, body = answer
        return httpx.Response(status, content=json.dumps(body), headers={"content-type": "application/json"})


@pytest.fixture
def yt(monkeypatch):
    fake_yt = YouTube()
    monkeypatch.setattr(youtube, "http_client", lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake_yt.handler)))
    return fake_yt


@pytest.fixture
def keyed(monkeypatch):
    from app.secrets import keychain

    monkeypatch.setattr(keychain, "get_optional", lambda name: KEY if name == "youtube_api_key" else None)


@pytest.fixture
def keyless(monkeypatch):
    from app.secrets import keychain

    monkeypatch.setattr(keychain, "get_optional", lambda name: None)


def _item(video, *, embeddable=True, privacy="public", duration="PT2M31S", region=None, rating=None, title=None, channel="Warner"):
    details = {"duration": duration}
    if region is not None:
        details["regionRestriction"] = region
    if rating is not None:
        details["contentRating"] = rating
    return {"id": video, "contentDetails": details, "status": {"embeddable": embeddable, "privacyStatus": privacy},
            "snippet": {"title": title or f"Title of {video}", "channelTitle": channel, "liveBroadcastContent": "none"}}


def _hit(video, title, *, state="none", channel="Warner"):
    return {"id": {"kind": "youtube#video", "videoId": video}, "snippet": {"title": title, "channelTitle": channel,
                                                                           "liveBroadcastContent": state}}


def test_only_youtubes_own_links_and_ids_are_read():
    ok = {
        HEAT: (HEAT, 0),
        f"https://www.youtube.com/watch?v={HEAT}": (HEAT, 0),
        f"youtube.com/watch?v={HEAT}&t=1m30s": (HEAT, 90),
        f"https://youtu.be/{HEAT}?t=90": (HEAT, 90),
        f"https://youtu.be/{HEAT}?si=abc&t=2h": (HEAT, 7200),
        f"https://m.youtube.com/shorts/{HEAT}": (HEAT, 0),
        f"https://www.youtube.com/embed/{HEAT}?start=45": (HEAT, 45),
        f"https://www.youtube.com/live/{HEAT}": (HEAT, 0),
        f"https://music.youtube.com/watch?v={HEAT}&list=RD": (HEAT, 0),
        f"https://www.youtube-nocookie.com/embed/{HEAT}": (HEAT, 0),
    }
    for text, want in ok.items():
        assert youtube.parse(text) == want, text
    for text in (
        "", "heat trailer", f"https://vimeo.com/{HEAT}", f"https://youtube.com.example.net/watch?v={HEAT}",
        f"https://example.net/?u=https://youtu.be/{HEAT}", f"javascript:alert(1)//youtu.be/{HEAT}",
        "https://www.youtube.com/watch?v=short", f"https://www.youtube.com/watch?v={HEAT}x",
        f"ftp://youtu.be/{HEAT}", "https://www.youtube.com/watch?v=<script>abc", f"https://youtu.be/ {HEAT}",
        f"https://www.youtube.com/channel/{HEAT}",
    ):
        assert youtube.parse(text) is None, text
    # A start point is bounded, and nonsense is the start.
    assert youtube.parse(f"https://youtu.be/{HEAT}?t=999h") == (HEAT, youtube.MAX_START_S)
    assert youtube.parse(f"https://youtu.be/{HEAT}?t=abc") == (HEAT, 0)


def test_search_needs_the_key_and_asks_youtube_nothing_without_it(yt, keyless):
    with pytest.raises(youtube.YouTubeUnavailable) as caught:
        asyncio.run(youtube.search("heat trailer"))
    assert caught.value.kind == "no_key" and "link plays without one" in str(caught.value)
    assert yt.calls == []


def test_search_offers_only_what_can_play_on_a_screen_best_first(yt, keyed, caplog):
    ids = [f"vid{n:08d}" for n in range(9)]
    yt.routes["/youtube/v3/search"] = (200, {"items": [
        _hit(ids[0], "Heat (1995) Official Trailer &#39;Remastered&#39; &amp; more"),
        _hit(ids[1], "Not embeddable"),
        _hit(ids[2], "Age restricted"),
        _hit(ids[3], "Blocked in the UK"),
        _hit(ids[4], "Only in the US"),
        _hit(ids[5], "Premieres tomorrow", state="upcoming"),
        _hit(ids[0], "A duplicate"),
        _hit("bad id", "Not an id"),
        _hit(ids[6], "Live now", state="live"),
        _hit(ids[7], "Private"),
        _hit(ids[8], "Fine too"),
    ]})
    yt.routes["/youtube/v3/videos"] = (200, {"items": [
        _item(ids[0], duration="PT2M31S"), _item(ids[1], embeddable=False), _item(ids[2], rating={"ytRating": "ytAgeRestricted"}),
        _item(ids[3], region={"blocked": ["GB", "IE"]}), _item(ids[4], region={"allowed": ["US"]}), _item(ids[5]),
        _item(ids[6], duration="P0D"), _item(ids[7], privacy="private"), _item(ids[8], duration="PT1H2M3S"),
    ]})
    with caplog.at_level(logging.DEBUG):
        found = asyncio.run(youtube.search("  heat   trailer "))
    assert [v.id for v in found] == [ids[0], ids[6], ids[8]]
    assert found[0].title == "Heat (1995) Official Trailer 'Remastered' & more"
    assert found[0].said() == {"video": ids[0], "title": found[0].title, "channel": "Warner",
                               "url": f"https://www.youtube.com/watch?v={ids[0]}", "duration": "2:31"}
    assert found[1].live and found[1].duration_s is None and found[1].said()["live"] is True
    assert found[2].said()["duration"] == "1:02:03"
    search, details = yt.calls
    assert search.url.params["q"] == "heat trailer"
    assert search.url.params["videoEmbeddable"] == "true" and search.url.params["regionCode"] == "GB"
    assert details.url.params["id"].split(",")[0] == ids[0]
    for call in yt.calls:
        # The key travels in a header, never in an address.
        assert call.headers["x-goog-api-key"] == KEY
        assert KEY not in str(call.url)
    assert KEY not in caplog.text


def test_youtube_saying_no_is_said_plainly_and_never_quotes_it(yt, keyed):
    for status, reason, kind in ((403, "quotaExceeded", "quota"), (400, "keyInvalid", "rejected"),
                                 (403, "accessNotConfigured", "rejected"), (500, "backendError", "refused")):
        yt.routes["/youtube/v3/search"] = (status, {"error": {"errors": [{"reason": reason, "message": f"echo {KEY}"}]}})
        with pytest.raises(youtube.YouTubeUnavailable) as caught:
            asyncio.run(youtube.search("heat"))
        assert caught.value.kind == kind, reason
        assert KEY not in str(caught.value) and "echo" not in str(caught.value)
    yt.routes["/youtube/v3/search"] = httpx.ReadTimeout("slow")
    with pytest.raises(youtube.YouTubeUnavailable) as caught:
        asyncio.run(youtube.search("heat"))
    assert caught.value.kind == "timeout"
    yt.routes["/youtube/v3/search"] = httpx.ConnectError("down")
    with pytest.raises(youtube.YouTubeUnavailable) as caught:
        asyncio.run(youtube.search("heat"))
    assert caught.value.kind == "unreachable"


def test_a_linked_video_is_read_with_the_key_or_through_oembed_without_it(yt, keyed, monkeypatch):
    yt.routes["/youtube/v3/videos"] = (200, {"items": [_item(HEAT, title="Heat &amp; Dust", duration="PT3M")]})
    got = asyncio.run(youtube.video(HEAT, start=30))
    assert (got.id, got.title, got.channel, got.duration_s, got.start) == (HEAT, "Heat & Dust", "Warner", 180, 30)
    yt.routes["/youtube/v3/videos"] = (200, {"items": [_item(HEAT, embeddable=False)]})
    with pytest.raises(youtube.YouTubeUnavailable) as caught:
        asyncio.run(youtube.video(HEAT))
    assert caught.value.kind == "not_playable"
    yt.routes["/youtube/v3/videos"] = (200, {"items": []})
    with pytest.raises(youtube.YouTubeUnavailable) as caught:
        asyncio.run(youtube.video(HEAT))
    assert caught.value.kind == "not_found"

    from app.secrets import keychain

    monkeypatch.setattr(keychain, "get_optional", lambda name: None)
    yt.calls.clear()
    yt.routes["/oembed"] = (200, {"title": "Heat | Official Trailer", "author_name": "Warner Bros."})
    got = asyncio.run(youtube.video(HEAT))
    assert (got.title, got.channel, got.duration_s) == ("Heat | Official Trailer", "Warner Bros.", None)
    (call,) = yt.calls
    assert call.url.host == "www.youtube.com" and call.url.params["url"] == f"https://www.youtube.com/watch?v={HEAT}"
    assert "x-goog-api-key" not in call.headers
    for status, kind in ((401, "not_playable"), (403, "not_playable"), (404, "not_found"), (400, "not_found"), (500, "refused")):
        yt.routes["/oembed"] = (status, {})
        with pytest.raises(youtube.YouTubeUnavailable) as caught:
            asyncio.run(youtube.video(HEAT))
        assert caught.value.kind == kind, status
    with pytest.raises(youtube.YouTubeUnavailable):
        asyncio.run(youtube.video("not-an-id"))


# --------------------------------------------------------------------------- the store


def _video(s, name="Living room TV", video=HEAT, **kw):
    screen = pair(s, name)
    s.show(screen["id"], views.video_view(video, title="Heat | Official Trailer", channel="Warner", duration_s=151), **kw)
    return screen


def _pane(s, screen, n=0):
    now = s.poll(screen["id"], screen["screen_key"])
    return (now["showing"], now["beside"])[n]


def test_a_video_pane_keeps_an_id_a_title_and_numbers_and_never_an_address(s, tmp_path):
    with pytest.raises(ValueError):
        views.video_view("https://evil.example/x", title="x")
    view = views.video_view(HEAT, title="  Heat\n  " + "x" * 400, channel="W" * 300, duration_s=10**9, start=10**9)
    assert view["ref"] == HEAT and len(view["title"]) == views.MAX_TITLE and len(view["video"]["channel"]) == 80
    assert view["video"]["duration_s"] == 100_000 and view["video"]["start"] == views.MAX_START_S
    assert views.video_view(HEAT, title="", live=True, duration_s=5)["video"]["duration_s"] is None
    screen = _video(s)
    s.player(screen["id"], 0, _pane(s, screen)["v"], "volume", 40)
    kept = (tmp_path / "objectives" / "displays.json").read_text()
    assert HEAT in kept and "http" not in kept and "youtube" not in kept.lower()


def test_every_command_is_applied_once_however_many_arrive_together(s):
    screen = _video(s)
    sid, v = screen["id"], _pane(s, screen)["v"]
    assert _pane(s, screen).get("player") is None, "nothing asked of it yet"
    s.player(sid, 0, v, "pause")
    s.player(sid, 0, v, "skip", 30)
    s.player(sid, 0, v, "skip", -10)
    s.player(sid, 0, v, "jump", 60)
    s.player(sid, 0, v, "skip", 15)
    state = s.player(sid, 0, v, "volume", 35)
    p = state["player"]
    assert p["n"] == 6 and p["paused"] is True and p["volume"] == 35 and p["muted"] is False
    # Every skip added up, and the jump knows which skips came before it: a screen that saw none
    # of this jumps to 60 and then skips the 15 that came after, and nothing else.
    assert p["skip"] == 35 and p["jump"] == {"n": 4, "to": 60, "skip": 20}
    assert _pane(s, screen)["player"] == p, "the screen is given exactly this on its next ask"
    assert _pane(s, screen)["v"] == v, "the pane is the same pane: its version did not move"
    for action, value in (("volume", 101), ("volume", None), ("skip", 0), ("skip", 3601), ("jump", -1),
                          ("louder", 0), ("dance", None)):
        with pytest.raises(DisplayError):
            s.player(sid, 0, v, action, value)
    with pytest.raises(DisplayError):
        s.player(sid, 0, v, "volume", True)
    assert s.player(sid, 0, v, "mute")["player"]["muted"] is True
    assert s.player(sid, 0, v, "louder")["player"] == {**p, "n": 8, "muted": False, "volume": 45}
    assert s.player(sid, 0, v, "quieter", 50)["player"]["volume"] == 0


def test_louder_starts_from_the_volume_the_screen_said(s):
    screen = _video(s)
    sid, key, v = screen["id"], screen["screen_key"], _pane(s, screen)["v"]
    s.report_playing(sid, 0, v, screen_key=key, state="playing", at=1.0, duration=151.0, volume=30, muted=False,
                     blocked=False, error=None)
    assert s.player(sid, 0, v, "louder")["player"]["volume"] == 40


def test_only_a_video_plays_and_a_video_is_never_done_ticked_or_paged(s):
    screen = pair(s, "Office screen")
    s.show(screen["id"], views.list_view("Today", ["One"]))
    v = _pane(s, screen)["v"]
    with pytest.raises(DisplayError, match="Nothing on this plays"):
        s.player(screen["id"], 0, v, "pause")
    s.show(screen["id"], views.video_view(HEAT, title="Heat"), beside=True)
    video = _pane(s, screen, 1)
    with pytest.raises(store_module.Stale):
        s.player(screen["id"], 1, video["v"] + 1, "pause")
    with pytest.raises(DisplayError, match="not marked done"):
        s.mark_done(screen["id"], video["v"], screen_key=screen["screen_key"], confirmed=True, pane=1)
    with pytest.raises(DisplayError):
        s.done_from_remote(screen["id"], 1, video["v"])
    with pytest.raises(DisplayError):
        s.tick(screen["id"], 1, 0, True, video["v"])
    with pytest.raises(DisplayError):
        s.turn_page(screen["id"], 1, 1, video["v"])
    with pytest.raises(DisplayError):
        s.acknowledge(screen["id"], video["v"], screen_key=screen["screen_key"], start=0, end=1, pane=1)
    waiting = s.register("Bedroom TV")
    with pytest.raises(NotPaired):
        s.show(waiting["id"], views.video_view(HEAT, title="Heat"))


def test_how_it_plays_is_the_screens_own_word_held_in_memory_and_not_hurried(s, tmp_path):
    screen = _video(s)
    sid, key, v = screen["id"], screen["screen_key"], _pane(s, screen)["v"]
    said = {"state": "playing", "at": 10.0, "duration": 151.0, "volume": 80, "muted": False, "blocked": False, "error": None}
    with pytest.raises(NotThisScreen):
        s.report_playing(sid, 0, v, screen_key="not-its-key", **said)
    with pytest.raises(store_module.Stale):
        s.report_playing(sid, 0, v + 1, screen_key=key, **said)
    with pytest.raises(DisplayError):
        s.report_playing(sid, 0, v, screen_key=key, **{**said, "state": "dancing"})
    assert s.report_playing(sid, 0, v, screen_key=key, **said) is True
    assert s.report_playing(sid, 0, v, screen_key=key, **{**said, "at": 99.0}) is False, "sooner than the store takes one"
    later(s, 5)
    (heard,) = s.playing(sid)
    assert heard["playing"]["state"] == "playing" and 14.9 < heard["playing"]["at"] < 15.2, "moved on while it played"
    remote = s.remote(sid)["panes"][0]
    assert remote["kind"] == "video" and remote["video"] == {"id": HEAT, "channel": "Warner", "duration_s": 151, "live": False}
    assert remote["playing"]["state"] == "playing" and remote["player"]["n"] == 0
    later(s, 500)
    assert s.playing(sid)[0]["playing"]["at"] == 151.0, "never past the end"
    later(s, PLAYING_GAP_S)
    s.report_playing(sid, 0, v, screen_key=key, **{**said, "state": "paused", "at": 20.0, "error": 777})
    later(s, 30)
    heard = s.playing(sid)[0]["playing"]
    assert heard["at"] == 20.0 and heard["error"] == 5, "paused stays put; an unknown error is YouTube's generic one"
    assert not any(k in (tmp_path / "objectives" / "displays.json").read_text() for k in ('"playing"', '"blocked"'))
    s.take_off(sid)
    assert s._playing == {}, "what was heard goes with the pane"


# --------------------------------------------------------------------------- the routes


def test_the_video_routes_are_the_owners_and_the_screens_own(s):
    client = app_with(s)
    screen = _video(s)
    sid, key, v = screen["id"], screen["screen_key"], _pane(s, screen)["v"]
    stranger = {**OWNER, "Tailscale-User-Login": "someone@example.com"}
    body = {"pane": 0, "version": v, "action": "pause"}
    assert client.post(f"/displays/{sid}/remote/video", json=body).status_code == 403
    assert client.post(f"/displays/{sid}/remote/video", json=body, headers=stranger).status_code == 403
    answer = client.post(f"/displays/{sid}/remote/video", json=body, headers=OWNER)
    assert answer.status_code == 200 and answer.json()["player"]["paused"] is True
    assert answer.headers["cache-control"] == "no-store"
    assert client.post(f"/displays/{sid}/remote/video", json={**body, "version": v + 5}, headers=OWNER).json()["code"] == "stale"
    for bad in ({**body, "action": "delete"}, {**body, "action": "volume", "value": "40"}, {**body, "pane": True},
                {**body, "action": "jump", "value": 10**9}):
        assert client.post(f"/displays/{sid}/remote/video", json=bad, headers=OWNER).status_code == 422, bad
    said = {"pane": 0, "version": v, "state": "playing", "at": 3.5, "duration": 151, "volume": 50, "muted": False}
    assert client.post(f"/displays/{sid}/video", json=said, headers=stranger).status_code == 403
    # The screen's own word, known by its cookie like its every other request (round 9, B2-01):
    # a wrong key, or the right one sent as the old header, is not the screen.
    for headers in (as_screen("wrong"), {**OWNER, "X-Screen-Key": key}):
        refused = client.post(f"/displays/{sid}/video", json=said, headers=headers)
        assert refused.status_code == 403 and refused.json()["code"] == "not_this_screen"
    ok = client.post(f"/displays/{sid}/video", json=said, headers=as_screen(key))
    assert ok.status_code == 200 and ok.json() == {"heard": True}
    assert client.post(f"/displays/{sid}/video", json={**said, "version": v + 1}, headers=as_screen(key)).status_code == 409
    assert client.post(f"/displays/{sid}/video", json={**said, "state": "x"}, headers=as_screen(key)).status_code == 422
    remote = client.get(f"/displays/{sid}/remote", headers=OWNER).json()["panes"][0]
    assert remote["playing"]["volume"] == 50 and remote["player"]["paused"] is True


# --------------------------------------------------------------------------- the tools


def _found(*ids):
    return [youtube.Video(id=i, title=f"Video {i}", channel="Channel", duration_s=60 * (n + 1)) for n, i in enumerate(ids)]


def test_screen_play_finds_it_puts_it_on_and_offers_the_others(s, monkeypatch):
    from app.presentation import _from_result
    from app.tools import display_tools

    asked: list[str] = []

    async def search(query):
        asked.append(query)
        return _found(HEAT, OTHER)

    monkeypatch.setattr(youtube, "search", search)
    screen = pair(s, "Living room TV")
    out = run(display_tools.screen_play(query="the heat trailer"))
    assert asked == ["the heat trailer"]
    assert out["screen"] == "Living room TV" and out["screen_id"] == screen["id"] and out["remote"] == "open"
    assert out["playing"]["video"] == HEAT and [c["video"] for c in out["choices"]] == [OTHER]
    up = _pane(s, screen)
    assert up["kind"] == "video" and up["ref"] == HEAT and up["video"]["duration_s"] == 60
    (card,) = _from_result("screen_play", out)
    assert card["type"] == "screen_remote" and card["data"]["screen_id"] == screen["id"]


def test_screen_play_reads_a_link_and_refuses_what_is_not_youtube(s, monkeypatch):
    from app.tools import display_tools

    looked: list[tuple[str, int]] = []

    async def video(ident, *, start=0):
        looked.append((ident, start))
        return youtube.Video(id=ident, title="Linked", channel="Someone", duration_s=None, start=start)

    monkeypatch.setattr(youtube, "video", video)
    screen = pair(s, "Living room TV")
    s.show(screen["id"], views.list_view("Packing", ["Tee"]))
    out = run(display_tools.screen_play(screen="living room", video=f"https://youtu.be/{OTHER}?t=90", beside=True))
    assert looked == [(OTHER, 90)] and out["showing"] == ["Packing", "Linked"]
    assert _pane(s, screen, 1)["video"]["start"] == 90
    for bad in ({"video": "https://vimeo.com/1"}, {}, {"query": "x", "video": OTHER}, {"query": "   "}):
        with pytest.raises(ToolError):
            run(display_tools.screen_play(**bad))


def test_screen_play_says_plainly_when_search_needs_the_key(s, yt, keyless):
    from app.tools import display_tools

    pair(s, "Living room TV")
    with pytest.raises(ToolError, match="needs a YouTube key"):
        run(display_tools.screen_play(query="heat trailer"))
    assert yt.calls == []


def test_screen_play_asks_which_screen_and_never_plays_on_one_waiting_for_approval(s, monkeypatch):
    from app.tools import display_tools

    async def search(query):
        return _found(HEAT)

    monkeypatch.setattr(youtube, "search", search)
    pair(s, "Living room TV")
    pair(s, "Office screen")
    with pytest.raises(ToolError, match="Which screen"):
        run(display_tools.screen_play(query="heat"))
    s.register("Bedroom TV")
    with pytest.raises(ToolError, match="hasn't been approved"):
        run(display_tools.screen_play(screen="Bedroom TV", query="heat"))


def test_screen_video_works_the_one_video_playing(s):
    from app.tools import display_tools

    with pytest.raises(ToolError, match="Nothing is playing"):
        run(display_tools.screen_video(action="pause"))
    screen = _video(s)
    out = run(display_tools.screen_video(action="pause"))
    assert out["screen"] == "Living room TV" and out["paused"] is True and out["done"] == "pause"
    assert run(display_tools.screen_video(action="volume", level=30))["volume"] == 30
    assert run(display_tools.screen_video(action="louder"))["volume"] == 40
    run(display_tools.screen_video(action="skip", seconds=-30))
    run(display_tools.screen_video(action="restart"))
    p = _pane(s, screen)["player"]
    assert p["skip"] == -30 and p["jump"] == {"n": p["n"], "to": 0, "skip": -30}
    for bad in ({"action": "volume"}, {"action": "skip"}, {"action": "skip", "seconds": 99999}, {"action": "jump"},
                {"action": "fly"}, {"action": "pause", "pane": "third"}):
        with pytest.raises(ToolError):
            run(display_tools.screen_video(**bad))
    other = _video(s, "Office screen", OTHER)
    with pytest.raises(ToolError, match="Which screen"):
        run(display_tools.screen_video(action="pause"))
    assert run(display_tools.screen_video(action="mute", screen="office"))["muted"] is True
    assert _pane(s, other)["player"]["muted"] is True and _pane(s, screen)["player"]["muted"] is False


def test_the_video_tools_answer_only_the_owners_own_request(s, monkeypatch):
    from app.tools import (
        display_tools,
        shopify_tools,  # noqa: F401  registers the reads a service authority may hold
    )

    async def search(query):
        raise AssertionError("YouTube is not asked for service work")

    monkeypatch.setattr(youtube, "search", search)
    _video(s)
    service = owner().derive("prefetch:screens", 60, tools=set(authority.SERVICE_READS) | {"screen_play", "screen_video"})
    assert service is not None and not any(service.permits(n) for n in ("screen_play", "screen_video"))
    for who in (service, None):
        for call in (display_tools.screen_play(query="heat"), display_tools.screen_video(action="pause")):
            with pytest.raises(ToolError, match="only the owner's own request"):
                run(call, held=who)
    for tool, args in (("screen_play", {"query": "heat"}), ("screen_video", {"action": "pause"})):
        decided = gate.classify(tool, args, issued_ids=[])
        assert decided.tier is Tier.GREEN and decided.executes, tool


# --------------------------------------------------------------------------- the pages


def test_the_screen_plays_youtube_in_its_own_player_and_trusts_only_its_messages():
    from tests.test_displays import WEB

    page = (WEB / "display.js").read_text(encoding="utf-8")
    # YouTube's privacy-enhanced embed, built from the id the screen was given, never an address.
    assert "const YT_EMBED = 'https://www.youtube-nocookie.com';" in page
    assert "YT_EMBED + '/embed/' + encodeURIComponent(id)" in page and "if (!VIDEO_ID.test(id)) return null;" in page
    # No script of YouTube's runs in the screen's page: the player is spoken to by postMessage.
    assert "iframe_api" not in page and "www-widgetapi" not in page
    assert "event.origin" in page and "event.source" in page
    remote = (WEB / "remote.js").read_text(encoding="utf-8")
    assert "'/remote/video'" in remote
