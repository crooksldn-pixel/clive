"""The owner's screens, the server's side: the round-10 deploy review's questions on it, answered
with the code running (round 11).

- F-A3B-SCREEN-EVIDENCE: what a keyed TV is given is pinned field by field, for every kind of
  thing it shows, and a record on disk holding more than that gives the TV none of it.
- B-01-B-05-PATH: a refused caller reaches no screen route and no screen tool, with production's
  switches as config/settings.py resolves them (CROOKS_TAILSCALE_VERIFY and CROOKS_LOCAL_OWNER
  unset, not forced), the kernel's own account of each connection, and an order id issued by the
  conversation's own lookup through a Shopify client that answers like the store.
- NEW-B-LOCAL-SLIP (the server's half): a TV whose device Tailscale no longer confirms, or whose
  slip is past its time, is given nothing, over HTTP.
- B-03: every kind of deletion, with the disk failing at every point of it, and every way a power
  cut could then leave the folder: a slip the caller was told is off (or off and not yet saved)
  never comes back, alone or after an earlier owed deletion, and nor after the retry.
- B-04: a screen using the remote's routes is still a screen: what it marks done there is
  recorded as a screen's word, never as the owner's own remote, cookie or no cookie.
- B2-01: once a page from before hands its old key in, that key opens nothing; and a new key
  whose record is in place but not yet durable is still handed over.
- The video pane: a screen's report of how its video plays is a state, numbers and true or false,
  and nothing else reaches the remote, CLIVE or the disk.
"""

from __future__ import annotations

import datetime as dt
import itertools
import json
import os
from pathlib import Path

import httpx
import pytest

from app import identity
from app.displays import store as store_module
from app.displays import views
from app.displays.store import SHOWING_KEEP_S, DisplayStore, NotDurable, NotSaved
from app.main import app
from app.session.manager import SessionManager
from tests.test_context import ORDER_NODE, Store, inbox
from tests.test_displays import (
    ORDER,
    OWNER,
    OWNER_LOGIN,
    Clock,
    Tick,
    ack_all,
    app_with,
    as_screen,
    handed_key,
    pair,
    run,
)
from tests.test_proxy_identity import HOST_TAILNET, HOST_TAILNET6, _addresses, _world
from tests.test_screen_paths import ScriptedModel

CUSTOMER = ("Sam Carter", "Sample Road", "E8 1AA", "gift", "HW-TEE")


def shape(value, at: str = "") -> set[str]:
    """Every field an answer carries, as dotted paths; a list's rows are `[]`."""
    out: set[str] = set()
    if isinstance(value, dict):
        for key, inner in value.items():
            path = f"{at}.{key}" if at else key
            out.add(path)
            out |= shape(inner, path)
    elif isinstance(value, list):
        for inner in value:
            out |= shape(inner, f"{at}[]")
    return out


def under(prefix: str, paths: set[str]) -> set[str]:
    return {f"{prefix}.{p}" for p in paths}


# --------------------------------------------------------------------------- F-A3B-SCREEN-EVIDENCE

# Everything a screen may be given, written out here rather than read from the store, so that a
# field added to what a screen is given fails this test until it is added here on purpose.
ANSWER = {"id", "name", "version", "showing", "beside", "pending", "now", "last_done"}
PANE = {"kind", "ref", "title", "at", "by", "v"}
ORDER_PANE = PANE | {"order", "ticked", "page"} | under("order", {
    "number", "placed_at", "customer", "company", "address", "phone", "items", "note", "tags", "fulfillment",
    "payment", "shipping_method", "items[].title", "items[].variant", "items[].sku", "items[].quantity",
    "items[].to_send", "items[].image"})
LIST_PANE = PANE | {"list", "list.lines", "ticked", "page"}
OBJECTIVE_PANE = PANE | {"objective"} | under("objective", {
    "deadline", "days_left", "doing", "next", "needs_you", "blocked_by", "items", "items[].text", "items[].state"})
VIDEO_PANE = PANE | {"video", "player", "player.jump"} | under("video", {"id", "channel", "duration_s", "live", "start"}) | \
    under("player", {"n", "paused", "muted", "volume", "skip", "jump.n", "jump.to", "jump.skip"})
DONE_PANE = PANE | {"done_at"}
LAST_DONE = {"last_done.title", "last_done.at"}


def test_what_a_keyed_tv_is_given_is_its_own_record_cut_to_the_fields_of_each_kind(s):
    """F-A3B-SCREEN-EVIDENCE (round 9, "cannot tell"; round 10, part S3 never reviewed): what a
    keyed production TV can have from its own routes, with CROOKS_SCREEN_SNAPSHOTS off (nothing
    here reads that switch or a conversation), field by field. The answer to its ask and to its
    Mark packed is its own record — its name, version, whether it waits, the time, the last done
    row's title and time — and each pane cut to the fields its kind has. The slip's customer
    details are among them: that is what a packing slip is. No key, hash, code or login. What
    its page is answered by the remote's routes it also uses (a tick, a page turned, a video's
    button) is a pane's state: numbers, and the ticks."""
    client = app_with(s)
    tv = pair(s, "Packing screen")
    sid, mine = tv["id"], as_screen(tv["screen_key"])
    goal = views.objective_view({"id": "obj_0123abcd", "title": "Autumn drop", "doing": "Shooting", "deadline": "2026-10-01",
                                 "days_left": 3, "next": ["Edit"], "needs_you": ["Sign off"], "blocked_by": ["Weather"]},
                                [{"text": "Book the studio", "state": "proposed"}])
    s.show(sid, views.order_view(ORDER))
    v = s.remote(sid)["panes"][0]["v"]
    ticked = client.post(f"/displays/{sid}/remote/tick", json={"pane": 0, "item": 0, "packed": True, "version": v}, headers=mine)
    turned = client.post(f"/displays/{sid}/remote/page", json={"pane": 0, "delta": 1, "version": v}, headers=mine)
    assert shape(ticked.json()) == shape(turned.json()) == {"version", "v", "ticked", "page"}
    s.show(sid, views.video_view("dQw4w9WgXcQ", title="Heat", channel="Warner", duration_s=151), beside=True)
    played = client.post(f"/displays/{sid}/remote/video", headers=mine,
                         json={"pane": 1, "version": s.remote(sid)["panes"][1]["v"], "action": "jump", "value": 30})
    assert shape(played.json()) == {"version", "v", "player", "playing"} | under("player", {
        "n", "paused", "muted", "volume", "skip", "jump", "jump.n", "jump.to", "jump.skip"})
    answer = client.get(f"/displays/{sid}?v=-1", headers=mine).json()
    assert shape(answer) == ANSWER | under("showing", ORDER_PANE) | under("beside", VIDEO_PANE)
    assert answer["showing"]["order"]["customer"] == "Sam Carter", "the slip is the slip"
    # A list and an objective.
    s.show(sid, views.list_view("Today", ["Steam the jackets", "Press the tees"]))
    s.tick(sid, 0, 0, True, s.remote(sid)["panes"][0]["v"])
    s.turn_page(sid, 0, 1, s.remote(sid)["panes"][0]["v"])
    s.show(sid, goal, beside=True)
    answer = client.get(f"/displays/{sid}?v=-1", headers=mine).json()
    assert shape(answer) == ANSWER | under("showing", LIST_PANE) | under("beside", OBJECTIVE_PANE)
    # Marked packed: the answer to the tap is the same shape, the slip its summary alone.
    s.show(sid, views.order_view(ORDER))
    ack_all(s, sid, tv["screen_key"])
    done = client.post(f"/displays/{sid}/done", json={"version": s.remote(sid)["panes"][0]["v"], "confirm": True},
                       headers=mine).json()
    assert shape(done) == ANSWER | under("showing", DONE_PANE) | LAST_DONE and done["beside"] is None
    for word in CUSTOMER:
        assert word not in json.dumps(done), word
    assert OWNER_LOGIN not in json.dumps(done), "who marked it is the done record's, not the screen's"
    # A screen still waiting for approval: its code's time and nothing else.
    waiting = s.register("Office screen")
    held = client.get(f"/displays/{waiting['id']}?v=-1", headers=as_screen(waiting["screen_key"])).json()
    assert shape(held) == ANSWER | {"code_expires_in"} and held["showing"] is None and held["last_done"] is None
    assert waiting["code"] not in json.dumps(held)


def test_a_record_holding_more_than_a_view_gives_the_tv_none_of_it(tmp_path):
    """F-A3B-SCREEN-EVIDENCE, the fix: the ask used to hand the screen each pane exactly as the
    record held it, so whatever a record on disk carried — written by another build, or put
    there by hand — went to the TV with it. Now every pane is cut to the fields its kind has,
    and a done pane to its summary: nothing else in the record reaches the screen."""
    path = tmp_path / "displays.json"
    key = "a-screen-key-for-this-test-only-0123"
    slip = {**views.order_view(ORDER), "at": store_module._now_iso(), "by": "clive", "v": 3,
            "email": "sam@example.com", "secret": "not-for-a-screen"}
    slip["order"] = {**slip["order"], "email": "sam@example.com", "customer_id": "gid://shopify/Customer/7",
                     "items": [{**item, "cost": "12.00", "supplier": "Sample Mill"} for item in slip["order"]["items"]]}
    clip = {**views.video_view("dQw4w9WgXcQ", title="Heat"), "at": store_module._now_iso(), "by": "clive", "v": 3,
            "url": "https://evil.example/x", "player": {"n": 1, "paused": True, "html": "<b>x</b>"}}
    clip["video"] = {**clip["video"], "embed": "https://evil.example/embed"}
    screen = {"id": "scr_0123456789ab", "name": "Packing screen", "key": "packing screen",
              "secret": store_module._key_hash(key), "created_at": "2026-09-27T10:00:00+00:00",
              "last_seen": "2026-09-27T10:00:00+00:00", "version": 3, "paired": True, "showing": slip, "beside": clip}
    path.write_text(json.dumps({"screens": {screen["id"]: screen}, "done": []}), encoding="utf-8")
    s = DisplayStore(path, mono=Tick())
    answer = s.poll(screen["id"], key)
    no_jump = {"player.jump.n", "player.jump.to", "player.jump.skip"}
    assert shape(answer) == ANSWER | under("showing", ORDER_PANE - {"ticked", "page"}) | under("beside", VIDEO_PANE - no_jump)
    said = json.dumps(answer)
    for extra in ("sam@example.com", "not-for-a-screen", "Customer/7", "12.00", "Sample Mill", "evil.example", "<b>"):
        assert extra not in said, extra
    # A done pane that a record left the customer's details on is its summary and nothing more.
    screen["showing"] = {**slip, "done_at": store_module._now_iso()}
    screen["beside"] = None
    path.write_text(json.dumps({"screens": {screen["id"]: screen}, "done": []}), encoding="utf-8")
    answer = DisplayStore(path, mono=Tick()).poll(screen["id"], key)
    assert shape(answer) == ANSWER | under("showing", DONE_PANE)
    for word in (*CUSTOMER, "sam@example.com"):
        assert word not in json.dumps(answer), word


# --------------------------------------------------------------------------- B-01-B-05-PATH, NEW-B-LOCAL-SLIP

PHONE, TV, STRANGER_DEVICE = "100.64.0.9", "100.64.0.7", "100.64.0.3"
STRANGER = "someone@example.com"
TAILSCALED_END, CURL_END, DIRECT_END = 40001, 40002, 40009     # the fake /proc's connections (_world)
SHOPPER = ("Daniel Sear", "Somewhere Street", "SL4 1AA", "Leave with the neighbour", "daniel@example.com")
ORDER_ID = ORDER_NODE["id"]


def _through(port: int) -> httpx.AsyncClient:
    """A client whose connection the app sees as arriving from 127.0.0.1:port, which the fake
    /proc says tailscaled (40001), an ordinary process (40002) or nothing (40009) holds."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", port)),
                             base_url="http://127.0.0.1:8000")


def _whois(table: dict[str, str]) -> None:
    identity.bind_runner(lambda cli, address: {"UserProfile": {"LoginName": table.get(address, "")}})


@pytest.fixture()
async def production(tmp_path, monkeypatch):
    """Production's switches (the round-10 preflight, 1.2) set as its .env sets them — and the
    two the review named, CROOKS_TAILSCALE_VERIFY and CROOKS_LOCAL_OWNER, left UNSET, so that
    config/settings.py resolves them and the app is built from what it resolved. The kernel's
    account of each connection is a fake /proc read by the real code (app/identity.py), as in
    tests/test_turn_authority_path.py; only `tailscale whois` and the fake pids' pinning are
    stood in for. Shopify is a client that answers like the store (tests/test_context.py)."""
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.providers import max_agent_sdk
    from app.tools import shopify_tools
    from config.settings import get_settings

    for name in ("CROOKS_TAILSCALE_VERIFY", "CROOKS_LOCAL_OWNER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CROOKS_ALLOWED_LOGINS", OWNER_LOGIN)
    monkeypatch.setenv("CROOKS_WRITES_LOCAL_OWNER", "false")
    monkeypatch.setenv("CROOKS_WRITES_ENABLED", "true")
    monkeypatch.setenv("CROOKS_SCREEN_SNAPSHOTS", "false")
    get_settings.cache_clear()
    resolved = get_settings()
    assert resolved.tailscale_verify is True and resolved.local_owner is False and resolved.writes_local_owner is False

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    async def scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))
    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        # The app runs on what settings.py resolved: nothing here is copied over it.
        assert runtime.settings.tailscale_verify is True and runtime.settings.local_owner is False
        assert runtime.settings.writes_local_owner is False and runtime.allowed_logins == (OWNER_LOGIN,)
        runtime.sessions = SessionManager()
        runtime.provider = ScriptedModel(runtime)
        proc = _world(tmp_path, {100: ("tailscaled", [777]), 200: ("curl", [888])})
        _addresses(proc, HOST_TAILNET, HOST_TAILNET6)
        monkeypatch.setattr(identity, "PROC", proc)
        monkeypatch.setattr(identity, "CGROUP", tmp_path / "cgroup")
        monkeypatch.setattr(identity, "cli_path", lambda configured="": "/usr/bin/tailscale")
        # Which IPv4 address is this server's own tailnet one, where app/identity.py asks the
        # Tailscale interface itself (an ioctl a test cannot make; the door's round-11 change):
        # the fake /proc's own. Set whether or not this build asks it.
        monkeypatch.setattr(identity, "interface_ipv4", lambda name="tailscale0": HOST_TAILNET[0], raising=False)
        _whois({PHONE: OWNER_LOGIN, TV: OWNER_LOGIN, STRANGER_DEVICE: STRANGER, HOST_TAILNET[0]: OWNER_LOGIN})
        monkeypatch.setattr(shopify_tools, "_client", shopify_tools._client)
        monkeypatch.setattr(shopify_tools, "_hydrator", shopify_tools._hydrator)
        shop = Store()
        shopify_tools.bind(shop, threads_for=inbox())
        clock = Clock()
        monkeypatch.setattr(store_module, "_now_iso",
                            lambda: dt.datetime.fromtimestamp(clock.now, dt.UTC).isoformat(timespec="seconds"))
        screens = store_module.install(tmp_path / "objectives" / "displays.json", clock=clock, mono=Tick())
        async with _through(TAILSCALED_END) as tailnet:
            yield runtime, runtime.provider, screens, tailnet, shop, clock


def refused():
    """Every caller the owner rule refuses on production's switches: (who, port, headers)."""
    return (
        ("the server itself, straight to the port", DIRECT_END, {}),
        ("a stranger's device", TAILSCALED_END, {"Tailscale-User-Login": STRANGER, "X-Forwarded-For": STRANGER_DEVICE}),
        ("his login on a device Tailscale says is not his", TAILSCALED_END,
         {"Tailscale-User-Login": OWNER_LOGIN, "X-Forwarded-For": STRANGER_DEVICE}),
        ("a process on the server writing Tailscale's headers", CURL_END,
         {"Tailscale-User-Login": OWNER_LOGIN, "X-Forwarded-For": TV}),
        ("the server's own request through its own tailscale serve", TAILSCALED_END,
         {"Tailscale-User-Login": OWNER_LOGIN, "X-Forwarded-For": HOST_TAILNET[0]}),
        ("Funnel, or a tagged node: forwarded with no login", TAILSCALED_END, {"X-Forwarded-For": TV}),
    )


async def test_on_productions_own_switches_nobody_but_the_owner_reaches_a_screen_and_a_slip_needs_a_real_lookup(production):
    """B-01-B-05-PATH (round 10, S1 and S3T1, "cannot tell"): tests/test_screen_paths.py set
    tailscale_verify=True itself and issued the order id by hand. Here nothing is set over what
    config/settings.py resolves with CROOKS_TAILSCALE_VERIFY and CROOKS_LOCAL_OWNER unset, and
    the id is issued only by the conversation's own lookup (shopify_find_order, through the real
    dispatcher, against a client that answers like the store). A TV names itself through the
    door and is approved by the code the owner reads out; the slip goes up only after the
    lookup, in that conversation alone; and every caller the owner rule refuses — the server
    itself included, since CROOKS_LOCAL_OWNER is unset — is refused every screen route and /turn,
    with the TV's own cookie too: the model is never asked and the record does not move."""
    runtime, model, screens, tailnet, shop, _clock = production
    phone = {"Tailscale-User-Login": OWNER_LOGIN, "X-Forwarded-For": PHONE}
    tv = {"Tailscale-User-Login": OWNER_LOGIN, "X-Forwarded-For": TV}
    # The TV names itself through the door, and shows the code it was handed.
    named = await tailnet.post("/displays/register", json={"name": "Packing screen"}, headers=tv)
    assert named.status_code == 200 and named.json()["pending"] is True
    sid, key, code = named.json()["id"], handed_key(named), named.json()["code"]
    mine = {**tv, "Cookie": f"clive_screen={key}"}
    # The owner reads the code out, and CLIVE approves the screen with it.
    model.script = [("screen_pair", {"screen": "Packing screen", "code": code})]
    said = f"approve the packing screen, the code is {code[:3]} {code[3:]}"
    assert (await tailnet.post("/turn", json={"text": said, "session_id": "s1"}, headers=phone)).status_code == 200
    assert '"approved": true' in model.said[-1] and screens.poll(sid, key)["pending"] is False
    # Before any lookup the id is nobody's to put up: refused before an order is read.
    model.script = [("screen_show", {"screen": "Packing screen", "order_id": ORDER_ID})]
    await tailnet.post("/turn", json={"text": "put 1938 on the packing screen", "session_id": "s1"}, headers=phone)
    assert model.said[-1].startswith("NOT YET") and shop.queries == []
    # The conversation looks the order up: the lookup itself issues the id ...
    model.script = [("shopify_find_order", {"query": "1938"})]
    await tailnet.post("/turn", json={"text": "find order 1938", "session_id": "s1"}, headers=phone)
    assert ORDER_ID in runtime.sessions.get("s1").issued_ids, "issued by the lookup, not by this test"
    # ... and the same call now puts the slip up, which the TV is given on its next ask.
    model.script = [("screen_show", {"screen": "Packing screen", "order_id": ORDER_ID})]
    await tailnet.post("/turn", json={"text": "put it on the packing screen", "session_id": "s1"}, headers=phone)
    assert not model.said[-1].startswith(("NOT YET", "REFUSED", "ERROR")), model.said[-1]
    shown = await tailnet.get(f"/displays/{sid}?v=-1", headers=mine)
    assert shown.status_code == 200 and shown.json()["showing"]["order"]["customer"] == "Daniel Sear"
    # Another conversation was not issued it.
    await tailnet.post("/turn", json={"text": "put 1938 up", "session_id": "s2"}, headers=phone)
    assert model.said[-1].startswith("NOT YET")
    record = screens.path.read_bytes()
    turns = model.turns
    # Every caller the owner rule refuses, on every screen route (with the TV's own cookie
    # too) and on /turn: 403, nothing of the slip, the model never asked.
    from tests.test_screen_paths import _every_screen_route

    for who, port, headers in refused():
        async with _through(port) as caller:
            for method, path, body in _every_screen_route(sid):
                for extra in ({}, {"Cookie": f"clive_screen={key}"}):
                    answer = await caller.request(method, path, json=body, headers={**headers, **extra})
                    assert answer.status_code == 403, (who, method, path, answer.status_code)
                    for word in SHOPPER:
                        assert word not in answer.text, (who, path, word)
            turned = await caller.post("/turn", json={"text": "clear the packing screen", "session_id": "s3"}, headers=headers)
            assert turned.status_code == 403, (who, turned.status_code)
    assert model.turns == turns, "the model was never asked, so no tool ran"
    assert screens.path.read_bytes() == record and not screens.journal_path.exists(), "and nothing moved"


async def test_on_productions_switches_a_tv_refused_or_past_its_time_is_given_nothing(production):
    """NEW-B-LOCAL-SLIP, the server's half (round 10, S3T1; the page's half is web/display.js and
    tests/web/display.test.js). A TV showing a customer's slip whose device Tailscale no longer
    says is the owner's is answered 403 on its very next ask, with nothing of the slip, however
    recently it was admitted; and a slip up longer than SHOWING_KEEP_S is taken down on the next
    ask and off the disk."""
    _runtime, _model, screens, tailnet, _shop, clock = production
    made = pair(screens, "Packing screen")
    sid, key = made["id"], made["screen_key"]
    mine = {"Tailscale-User-Login": OWNER_LOGIN, "X-Forwarded-For": TV, "Cookie": f"clive_screen={key}"}
    screens.show(sid, views.order_view(ORDER))
    assert (await tailnet.get(f"/displays/{sid}?v=-1", headers=mine)).json()["showing"]["order"]["customer"] == "Sam Carter"
    # The TV is moved to another login in Tailscale: its very next ask carries nothing.
    _whois({PHONE: OWNER_LOGIN, TV: STRANGER})
    for v in (-1, 1):
        refused_ask = await tailnet.get(f"/displays/{sid}?v={v}", headers=mine)
        assert refused_ask.status_code == 403
        for word in CUSTOMER:
            assert word not in refused_ask.text, word
    _whois({PHONE: OWNER_LOGIN, TV: OWNER_LOGIN})
    assert (await tailnet.get(f"/displays/{sid}?v=-1", headers=mine)).status_code == 200
    # Past its time: taken down on the next ask, and off the disk.
    clock.now += SHOWING_KEEP_S + 60
    gone = await tailnet.get(f"/displays/{sid}?v=-1", headers=mine)
    assert gone.status_code == 200 and gone.json()["showing"] is None and gone.json()["beside"] is None
    for word in CUSTOMER:
        assert word not in gone.text and word not in screens.path.read_text(), word


# --------------------------------------------------------------------------- B-03

class Disk:
    """The screens' folder as a power cut could leave it (round 11, B-03). The store puts each of
    its two files in place by renaming a temporary file it has already flushed, and removes the
    journal by unlinking it; a rename or a removal is known to outlive a power cut only once the
    folder has been flushed after it, and until then it may or may not. So after a power cut
    each file is its durable version or any version it was given since, and `states` is every
    such pair. `fail` makes operations fail as a failing disk does, counted from `mark`: each
    rename into the folder and each folder flush is one operation, in the order they are made.
    Flushing is otherwise not done for real here — the model above is what is durable."""

    NAMES = ("displays.json", "displays.purge.json")

    def __init__(self, monkeypatch) -> None:
        self.folder: Path | None = None
        self.fail: set[int] = set()
        self.ops = self.base = 0
        real_replace, real_unlink = os.replace, Path.unlink
        disk = self

        def replace(src, dst):
            target = Path(dst)
            if target.parent == disk.folder:
                if disk._next() in disk.fail:
                    raise OSError(5, "I/O error")
                real_replace(src, dst)
                if target.name in disk.NAMES:
                    disk.since[target.name].append(target.read_bytes())
                return
            real_replace(src, dst)

        def flush(folder):
            if Path(folder) == disk.folder:
                if disk._next() in disk.fail:
                    raise OSError(5, "I/O error")
                disk.durable = {name: disk._read(name) for name in disk.NAMES}
                disk.since = {name: [] for name in disk.NAMES}

        def unlink(path, missing_ok=False):
            real_unlink(path, missing_ok=missing_ok)
            target = Path(path)
            if target.parent == disk.folder and target.name in disk.NAMES:
                disk.since[target.name].append(None)

        monkeypatch.setattr(store_module.os, "replace", replace)
        monkeypatch.setattr(store_module.os, "fsync", lambda fd: None)
        monkeypatch.setattr(store_module, "_fsync_dir", flush)
        monkeypatch.setattr(Path, "unlink", unlink)

    def watch(self, folder: Path) -> None:
        """This folder, as it is now, taken as durable."""
        self.folder = folder
        self.durable = {name: self._read(name) for name in self.NAMES}
        self.since = {name: [] for name in self.NAMES}
        self.fail = set()

    def mark(self, fail: set[int]) -> None:
        self.base, self.fail = self.ops, {self.ops + n for n in fail}

    def _next(self) -> int:
        self.ops += 1
        return self.ops - 1

    def _read(self, name: str) -> bytes | None:
        path = self.folder / name
        return path.read_bytes() if path.exists() else None

    def states(self) -> list[tuple[bytes | None, ...]]:
        return list(itertools.product(*(list(dict.fromkeys([self.durable[n], *self.since[n]])) for n in self.NAMES)))

    def restarts(self, into: Path):
        """A store started from each way a power cut now could leave the folder."""
        for n, state in enumerate(self.states()):
            folder = into / f"after-{n}"
            folder.mkdir(parents=True)
            for name, data in zip(self.NAMES, state, strict=True):
                if data is not None:
                    (folder / name).write_bytes(data)
            yield DisplayStore(folder / "displays.json", mono=Tick())


def _tick_every_item(s, sid):
    view = s._data["screens"][sid]["showing"]
    for item in store_module._tickable(view):
        s.tick(sid, 0, item, True, store_module._pane_v(view))


# Every way a slip is taken down, each on a screen showing a customer's slip (with a list beside
# it where the deletion is of one of two panes). The value: (set-up, the deletion).
DELETIONS = {
    "clear": (None, lambda s, sid, key: s.show(sid, None)),
    "replace everything": (None, lambda s, sid, key: s.show(sid, views.list_view("Tomorrow", ["Two"]))),
    "replace the slip's pane": ("beside", lambda s, sid, key: s.show(sid, views.list_view("Tomorrow", ["Two"]), replace=0)),
    "take the slip's pane off": ("beside", lambda s, sid, key: s.take_off(sid, 0)),
    "turn the screen off": ("beside", lambda s, sid, key: s.take_off(sid)),
    "the remote's off": ("beside", lambda s, sid, key: s.take_off(sid, screen_version=s._data["screens"][sid]["version"])),
    "packed with the screen's button": ("acked", lambda s, sid, key: s.mark_done(sid, 1, screen_key=key, confirmed=True)),
    "packed from the remote": ("ticked", lambda s, sid, key: s.done_from_remote(sid, 0, 1, by=OWNER_LOGIN)),
    "the screen removed": (None, lambda s, sid, key: s.forget(sid)),
}
PACKED = ("packed with the screen's button", "packed from the remote")


def _set_up(folder: Path, kind: str | None):
    s = DisplayStore(folder / "displays.json", mono=Tick())
    screen = pair(s, "Packing screen")
    sid, key = screen["id"], screen["screen_key"]
    s.show(sid, views.order_view(ORDER))
    if kind == "beside":
        s.show(sid, views.list_view("Today", ["One"]), beside=True)
    elif kind == "acked":
        ack_all(s, sid, key)
    elif kind == "ticked":
        _tick_every_item(s, sid)
    return s, sid, key


def _attempt(deletion, s, sid, key) -> str:
    try:
        deletion(s, sid, key)
    except NotDurable:
        return "not yet saved"
    except NotSaved:
        return "not made"
    return "done"


def _slip_is_off(restarted: DisplayStore, sid: str, key: str, *, packed: bool, why) -> None:
    """Nothing of the slip on this screen: not in what it is given, nor in its record on disk
    (another screen's slip may be the same order)."""
    shown = restarted.poll(sid, key)
    said = json.dumps(shown) + json.dumps(json.loads(restarted.path.read_text())["screens"].get(sid))
    for word in CUSTOMER:
        assert word not in said, (why, word)
    if packed:
        assert [row["ref"] for row in restarted.done()] == [ORDER["order_id"]], why


def test_a_slip_said_to_be_off_never_comes_back_however_the_disk_fails_and_the_power_goes(tmp_path, monkeypatch):
    """B-03 (round 9, "cannot tell"; round 10, S3T1: the store's body was not supplied). Every
    kind of deletion — a clear, a replacement of everything or of the slip's pane, one pane off,
    the screen off (CLIVE's and the remote's), Mark packed from the screen and from the remote,
    the screen removed — with the disk failing at every combination of its first five
    operations (the journal's rename and flush, the record's rename and flush, the journal put
    back), and then every way a power cut could leave the folder: a caller told the slip is off
    ("done", or 503 "not saved yet") never sees it come back after a restart, and a packed row
    it was told of is there; a caller told nothing was changed ("not made") still has it up.
    Then the disk is well again and housekeeping's retry (sweep) runs: the same holds."""
    disk = Disk(monkeypatch)
    told: dict[str, int] = {}
    case = itertools.count()
    for name, (kind, deletion) in DELETIONS.items():
        for size in range(6):
            for plan in itertools.combinations(range(5), size):
                folder = tmp_path / f"case-{next(case)}"
                s, sid, key = _set_up(folder, kind)
                disk.watch(folder)
                disk.mark(set(plan))
                outcome = _attempt(deletion, s, sid, key)
                told[outcome] = told.get(outcome, 0) + 1
                why = (name, plan, outcome)
                packed = name in PACKED
                if outcome == "not made":
                    kept = json.dumps(s._data["screens"][sid])
                    assert "Sam Carter" in kept and s.done() == [], why
                else:
                    for restarted in disk.restarts(folder / "power-cut"):
                        _slip_is_off(restarted, sid, key, packed=packed, why=why)
                # The disk well again, housekeeping's pass retries whatever is owed.
                disk.fail = set()
                assert s.sweep() == "", why
                if outcome != "not made":
                    for restarted in disk.restarts(folder / "after-retry"):
                        _slip_is_off(restarted, sid, key, packed=packed, why=why)
    assert set(told) == {"done", "not yet saved", "not made"}, told


def test_an_owed_deletion_is_never_lost_to_a_later_one_however_that_one_fails(tmp_path, monkeypatch):
    """B-03 across deletions: one clear told "not saved yet" (its journal durable, its record
    not) stays off through a second clear on another screen with the disk failing at every
    combination of that clear's operations, through every power cut after it, and after the
    retry; and the second is off exactly when its caller was told so."""
    disk = Disk(monkeypatch)
    told: set[str] = set()
    for size in range(6):
        for plan in itertools.combinations(range(5), size):
            folder = tmp_path / f"case-{size}-{'-'.join(map(str, plan))}"
            s, first, first_key = _set_up(folder, None)
            second = pair(s, "Office screen")
            s.show(second["id"], views.order_view(ORDER))
            disk.watch(folder)
            disk.mark({3})                                  # the record's flush fails
            assert _attempt(DELETIONS["clear"][1], s, first, first_key) == "not yet saved"
            disk.mark(set(plan))
            outcome = _attempt(DELETIONS["clear"][1], s, second["id"], second["screen_key"])
            told.add(outcome)
            for restarted in disk.restarts(folder / "power-cut"):
                _slip_is_off(restarted, first, first_key, packed=False, why=(plan, outcome, "the first"))
                if outcome != "not made":
                    _slip_is_off(restarted, second["id"], second["screen_key"], packed=False, why=(plan, outcome))
            disk.fail = set()
            assert s.sweep() == ""
            for restarted in disk.restarts(folder / "after-retry"):
                _slip_is_off(restarted, first, first_key, packed=False, why=(plan, outcome, "the first, retried"))
    assert told == {"done", "not yet saved", "not made"}, told


# --------------------------------------------------------------------------- B-04

def test_a_screen_using_the_remotes_routes_is_still_a_screen_and_never_the_owners_remote(tmp_path):
    """B-04 (round 9, no ruling in round 10): the done record says how each row was marked,
    "screen" for a screen's own button — its word, not a check — and "remote" for the owner's
    remote. But a screen is one of the owner's devices by its login, so it can reach the
    remote's routes (its own page ticks items through them), and from there it could tick every
    item and mark the order packed with no page drawn and nobody packing — and the row said the
    owner's own remote had. Now a request from a device that is itself a screen — carrying a
    screen's key, or asking from the tailnet address a screen's key-holder asks from, which a
    page that leaves its cookie out cannot change — is recorded as "screen_remote", a screen's
    word, and said so; across a restart too. The owner's phone is still "remote". And a screen's
    own Mark packed marks only what its page has a button for, an order or a list. Whether a
    screen's word counts as packed is the owner's ruling, still to be made."""
    from app.tools import display_tools

    s = store_module.install(tmp_path / "objectives" / "displays.json", mono=Tick())
    client = app_with(s)
    tv_device = {"Tailscale-User-Login": OWNER_LOGIN, "X-Forwarded-For": TV}
    made = client.post("/displays/register", json={"name": "Packing screen"}, headers=tv_device)
    sid, key = made.json()["id"], handed_key(made)
    s.approve("Packing screen", made.json()["code"])
    assert client.get(f"/displays/{sid}?v=-1", headers={**tv_device, "Cookie": f"clive_screen={key}"}).status_code == 200

    def forge(headers) -> str:
        """Every item ticked and the order marked packed through the remote's routes, with no
        page ever drawn: what the done row then says."""
        s.show(sid, views.order_view(ORDER))
        pane = client.get(f"/displays/{sid}/remote", headers=OWNER).json()["panes"][0]
        for item in pane["items"]:
            if not item["sent"]:
                ticked = client.post(f"/displays/{sid}/remote/tick", headers=headers,
                                     json={"pane": 0, "item": item["i"], "packed": True, "version": pane["v"]})
                assert ticked.status_code == 200
        done = client.post(f"/displays/{sid}/remote/done", json={"pane": 0, "version": pane["v"]}, headers=headers)
        assert done.status_code == 200, done.text
        return s.done()[0]["how"]

    assert forge({**tv_device, "Cookie": f"clive_screen={key}"}) == "screen_remote", "with its cookie"
    assert forge(tv_device) == "screen_remote", "its cookie left out: its address is still a screen's"
    said = run(display_tools.screen_list(order_id=ORDER["order_id"]))["done"][0]["marked"]
    assert said.endswith("not the owner's own remote: a screen's word, not a check"), said
    # The owner's own phone: the owner's remote.
    assert forge(OWNER) == "remote"
    # The screen's own Mark packed takes an order or a list, and nothing its page has no button
    # for: an objective marked done from the screen could only be a request the page never makes.
    s.show(sid, views.objective_view({"id": "obj_0123abcd", "title": "Autumn drop"}, []))
    rows = len(s.done(limit=50))
    goal = client.post(f"/displays/{sid}/done", json={"version": s.remote(sid)["panes"][0]["v"], "confirm": True},
                       headers={**tv_device, "Cookie": f"clive_screen={key}"})
    assert goal.status_code == 409 and len(s.done(limit=50)) == rows
    # Across a restart the screen's address is still known, from the record.
    s = store_module.install(tmp_path / "objectives" / "displays.json", mono=Tick())
    client = app_with(s)
    assert forge(tv_device) == "screen_remote"
    assert TV not in json.dumps(client.get("/displays", headers=OWNER).json()), "the address is the store's own"
    assert TV not in json.dumps(s.poll(sid, key)) and "asked_from" not in json.dumps(s.find("Packing screen"))


# --------------------------------------------------------------------------- B2-01

def test_once_an_old_page_hands_its_key_in_that_key_opens_nothing_and_the_new_one_everything(tmp_path):
    """B2-01, the server's half (round 10, S3P): the test of the move sent the old key back only
    as the X-Screen-Key header, which the screen's routes never read — so it could not show that
    the key itself was spent. Here the old key is sent as the cookie, as anything that copied it
    would send it: after the move it opens none of the screen's routes, and names nothing; the
    cookie handed in its place opens them all."""
    from tests.test_screen_cookie import _paired_before

    path = tmp_path / "objectives" / "displays.json"
    sid, old = _paired_before(path, marked=True)
    s = store_module.install(path, mono=Tick())
    client = app_with(s)
    before = client.get(f"/displays/{sid}?v=-1", headers=as_screen(old))
    assert before.status_code == 200, "until it moves, the old key is the screen's"
    moved = client.post("/displays/register", json={"name": "Office screen"}, headers={**OWNER, "X-Screen-Key": old})
    new = handed_key(moved)
    assert moved.status_code == 200 and new != old
    routes = (("get", f"/displays/{sid}?v=-1", None), ("post", f"/displays/{sid}/seen", {"version": 4, "start": 0, "end": 1}),
              ("post", f"/displays/{sid}/done", {"version": 4, "confirm": True}),
              ("post", f"/displays/{sid}/video", {"pane": 0, "version": 4, "state": "playing", "at": 1.0}))
    for method, route, body in routes:
        kwargs = {"json": body} if body is not None else {}
        spent = getattr(client, method)(route, headers=as_screen(old), **kwargs)
        assert spent.status_code == 403 and spent.json()["code"] == "not_this_screen", route
        assert "Sam Carter" not in spent.text
    for headers in (as_screen(old), {**OWNER, "X-Screen-Key": old}):
        again = client.post("/displays/register", json={"name": "Office screen"}, headers=headers)
        assert again.status_code == 409 and "set-cookie" not in again.headers
    assert client.get(f"/displays/{sid}?v=-1", headers=as_screen(new)).json()["showing"]["order"]["customer"] == "Sam Carter"
    assert client.post(f"/displays/{sid}/seen", json={"version": 4, "start": 0, "end": 1}, headers=as_screen(new)).status_code == 200


def test_a_new_key_whose_record_is_not_yet_durable_is_still_handed_over(tmp_path, monkeypatch):
    """B2-01, a failure found reading the store (round 11): a screen naming itself again, while an
    earlier deletion is still owed and the folder cannot be flushed, had its key changed in
    memory and in the file — and was answered 503 with no cookie. Its old key no longer opened
    anything and it never had the new one: the screen was lost until the owner removed it and
    approved it again. The change stands, so the key is handed over; the old key is spent."""
    from tests.test_displays import _flaky_record_flush

    path = tmp_path / "objectives" / "displays.json"
    s = store_module.install(path, mono=Tick())
    client = app_with(s)
    tv = pair(s, "Packing screen")
    other = pair(s, "Office screen")
    s.show(other["id"], views.order_view(ORDER))
    _placed, restore = _flaky_record_flush(monkeypatch, fail_from=1, records_only=True)
    with pytest.raises(NotDurable):
        s.show(other["id"], None)                         # a deletion owed: its journal durable, its record not
    renamed = client.post("/displays/register", json={"name": "Packing screen"}, headers=as_screen(tv["screen_key"]))
    assert renamed.status_code == 200 and renamed.json()["pending"] is False
    new = handed_key(renamed)
    restore()
    assert client.get(f"/displays/{tv['id']}?v=-1", headers=as_screen(new)).status_code == 200
    spent = client.get(f"/displays/{tv['id']}?v=-1", headers=as_screen(tv["screen_key"]))
    assert spent.status_code == 403 and spent.json()["code"] == "not_this_screen"
    assert s.sweep() == "" and DisplayStore(path, mono=Tick()).poll(tv["id"], new)["pending"] is False


# --------------------------------------------------------------------------- the video pane

def test_a_screens_word_on_its_video_is_a_state_numbers_and_true_or_false_and_nothing_else(tmp_path):
    """The YouTube pane (PR #53, part S3): a screen tells CLIVE how its video plays
    (/displays/{id}/video, with its key). What it can put there is YouTube's player state, a
    position and a length in their bounds, a volume, muted and blocked, and one of YouTube's own
    error numbers: any other field, a string or a true where a number goes, a number out of
    bounds, and a NaN or an infinity are refused (422) with nothing heard; an error number
    YouTube does not have is its generic one. What the remote and CLIVE are then given of it is
    exactly those fields, and none of it is ever written down."""
    from app.tools import display_tools

    s = store_module.install(tmp_path / "objectives" / "displays.json", mono=Tick())
    client = app_with(s)
    tv = pair(s, "Living room TV")
    sid, mine = tv["id"], as_screen(tv["screen_key"])
    s.show(sid, views.video_view("dQw4w9WgXcQ", title="Heat", channel="Warner", duration_s=151))
    v = s.remote(sid)["panes"][0]["v"]
    good = {"pane": 0, "version": v, "state": "playing", "at": 12.5, "duration": 151, "volume": 40, "muted": False,
            "blocked": False, "error": None}
    for bad in ({**good, "title": "<script>alert(1)</script>"}, {**good, "note": "Sam Carter, E8 1AA"},
                {**good, "state": "hacked"}, {**good, "at": "12"}, {**good, "at": True}, {**good, "duration": "151"},
                {**good, "volume": 40.5}, {**good, "volume": "40"}, {**good, "volume": 101}, {**good, "muted": "yes"},
                {**good, "error": "boom"}, {**good, "error": 1000}, {**good, "at": 10**9}, {**good, "pane": 2}):
        refused = client.post(f"/displays/{sid}/video", json=bad, headers=mine)
        assert refused.status_code == 422, bad
    # A NaN or an infinity, which Python's JSON reader takes: refused too. (How the refusal is
    # written out is the app's own validation answer, app/main.py, and not this route's.)
    from fastapi.testclient import TestClient

    lenient = TestClient(client.app, base_url="https://testserver", raise_server_exceptions=False)
    for raw in ('"at": NaN', '"at": Infinity', '"at": 1, "duration": -Infinity', '"at": 1, "duration": NaN'):
        body = '{"pane": 0, "version": ' + str(v) + ', "state": "playing", ' + raw + "}"
        refused = lenient.post(f"/displays/{sid}/video", content=body, headers={**mine, "Content-Type": "application/json"})
        assert refused.status_code >= 400, raw
    assert s.remote(sid)["panes"][0]["playing"] is None, "nothing refused was heard"
    assert client.post(f"/displays/{sid}/video", json={**good, "error": 777}, headers=mine).json() == {"heard": True}
    playing = client.get(f"/displays/{sid}/remote", headers=OWNER).json()["panes"][0]["playing"]
    assert set(playing) == {"state", "at", "duration", "volume", "muted", "blocked", "error", "age_s"}
    assert playing["state"] == "playing" and playing["error"] == 5 and playing["volume"] == 40
    told = run(display_tools.screen_video(action="pause"))
    assert set(told) <= {"screen", "video", "done", "paused", "muted", "volume", "was", "at", "note"}
    assert told["was"] == "playing" and told["video"] == "Heat"
    kept = json.loads(s.path.read_text())
    assert shape(kept["screens"][sid]["showing"]) & {"playing", "state", "blocked", "error", "at_s"} == set()
    assert "12.5" not in s.path.read_text()


@pytest.fixture
def s(tmp_path):
    return store_module.install(tmp_path / "objectives" / "displays.json", mono=Tick())
