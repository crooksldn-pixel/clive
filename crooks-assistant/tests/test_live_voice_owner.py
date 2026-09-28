"""POST /voice/live under production's switches: nobody but the owner's own device mints a key.

Closes round-9 finding C-01. The reviewer could not see `principal_verdict`, and the route tests
in tests/test_live_voice.py run with CROOKS_TAILSCALE_VERIFY off, where a forwarding header is
believed as written. Here nothing about the owner rule is stood in for: the real app, its real
door (app/main.py guard_and_freshness), the route's own check (app/routes/voice.py _refused), the
real principal_verdict and proxy_state (app/routes/actions.py) and the real kernel check of who
opened the connection (app/identity.py peer_is_tailscaled), with CROOKS_TAILSCALE_VERIFY on,
CROOKS_LOCAL_OWNER and CROOKS_WRITES_LOCAL_OWNER off, and an allow-list naming the owner. What is
stood in for is only what a test cannot have: the kernel's tables (a /proc in a temporary folder,
built by tests/test_proxy_identity.py, in which tailscaled holds the socket at port 40001 and an
ordinary local process the one at 40002), pinning and root ownership on those fake pids, which
of this server's addresses are its own, and `tailscale whois` (100.64.0.9 is the owner's phone,
100.64.0.3 is someone else's, 100.64.0.1 is this server).

Every refusal is checked for the same three things: a 403, no key in the answer, and ElevenLabs
never asked. ElevenLabs is a mocked transport throughout; nothing here reaches the network.
"""

from __future__ import annotations

import httpx
import pytest
from starlette.requests import Request

from app import identity
from app.actions.ledger import NullLedger
from app.main import app
from app.routes import voice as voice_route
from app.session.manager import SessionManager
from tests.test_actions_routes import OWNER, FakeProvider
from tests.test_live_voice import KEY, TOKEN, Clock, ElevenLabs, store_key
from tests.test_proxy_identity import _point_at

SERVER = ("127.0.0.1", 8000)
TAILSCALED = 40001        # the fake /proc: tailscaled's end of a connection to the app
LOCAL_PROCESS = 40002     # an ordinary process on the server
UNKNOWN = 40009           # a connection the kernel's table does not list at all

OWNER_PHONE = "100.64.0.9"
STRANGER_PHONE = "100.64.0.3"
THIS_SERVER = "100.64.0.1"
UNKNOWN_DEVICE = "100.64.0.7"
STRANGER = "other@example.com"

WHOIS = {OWNER_PHONE: OWNER, STRANGER_PHONE: STRANGER, THIS_SERVER: OWNER}


def whois(cli, address):
    """`tailscale whois --json <address>`, as the tailnet would answer it. An address it does
    not know is an error, as the CLI's is."""
    if address not in WHOIS:
        raise RuntimeError(f"no peer found for {address}")
    return {"UserProfile": {"LoginName": WHOIS[address]}}


@pytest.fixture()
async def world(monkeypatch, tmp_path):
    """The app as production runs it, with a client per connection the kernel can be asked
    about. `world.via(port)` is an HTTP client whose connection arrives from that port."""
    from app.clients.elevenlabs import ScribeClient
    from app.clients.elevenlabs_tts import VoiceClient
    from app.providers import max_agent_sdk

    async def no_start(self):
        raise RuntimeError("tests never start the real Claude provider")

    async def fake_scribe_health(self):
        return True, "fake scribe"

    monkeypatch.setattr(max_agent_sdk.MaxAgentSDKProvider, "start", no_start)
    monkeypatch.setattr(ScribeClient, "health", fake_scribe_health)
    monkeypatch.setattr(VoiceClient, "health", lambda self: (True, "fake voice"))

    clock = Clock()
    monkeypatch.setattr(voice_route, "PACE", voice_route.Pace(clock=clock))
    fake_api = ElevenLabs()
    monkeypatch.setattr(voice_route, "http_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(fake_api.handler), timeout=5.0))
    store_key(monkeypatch)

    _point_at(monkeypatch, tmp_path, {100: ("tailscaled", [777]), 200: ("curl", [888])})
    identity.bind_self_check(lambda address: address == THIS_SERVER)
    identity.bind_runner(whois)
    monkeypatch.setattr(identity, "cli_path", lambda configured="": "/usr/bin/tailscale")

    async with app.router.lifespan_context(app):
        runtime = app.state.runtime
        runtime.provider = FakeProvider()
        runtime.actions.ledger = NullLedger()
        runtime.sessions = SessionManager()
        runtime.settings = runtime.settings.model_copy(update={
            "allowed_logins": OWNER, "tailscale_verify": True, "local_owner": False,
            "writes_local_owner": False, "live_transcript": True,
        })
        app.state.allowed_logins = runtime.allowed_logins
        clients: dict[int, httpx.AsyncClient] = {}

        class World:
            elevenlabs = fake_api
            pace = clock

            @staticmethod
            def via(port: int) -> httpx.AsyncClient:
                if port not in clients:
                    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", port))
                    clients[port] = httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000")
                return clients[port]

        try:
            yield World
        finally:
            for c in clients.values():
                await c.aclose()


async def mint(world, port: int, headers: dict[str, str]) -> httpx.Response:
    return await world.via(port).post("/voice/live", headers=headers, json={})


def assert_refused_with_nothing(world, response: httpx.Response) -> None:
    assert response.status_code == 403, (response.status_code, response.text)
    assert "token" not in response.json()
    assert TOKEN not in response.text and KEY not in response.text
    assert world.elevenlabs.calls == [], "ElevenLabs is never asked for a key on a refused caller's behalf"


# ------------------------------------------------------------------ the owner, as production sees him


async def test_the_owners_phone_through_tailscaled_gets_a_key(world):
    """The control: with every production switch on, the owner's phone, through tailscaled, with
    whois agreeing, is let through the door and the route, and a key is minted for it once."""
    response = await mint(world, TAILSCALED, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": OWNER_PHONE})
    assert response.status_code == 200, response.text
    assert response.json()["token"] == TOKEN
    assert len(world.elevenlabs.calls) == 1


# ------------------------------------------------------------------ everyone else, at the door


REFUSED = [
    pytest.param(TAILSCALED, {"Tailscale-User-Login": STRANGER, "X-Forwarded-For": STRANGER_PHONE},
                 {"error": "not allowed", "who": STRANGER}, id="a-strangers-login-through-tailscaled"),
    pytest.param(TAILSCALED, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": STRANGER_PHONE},
                 "identity_unverified", id="the-owners-login-from-a-strangers-device"),
    pytest.param(TAILSCALED, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": "203.0.113.7"},
                 "identity_unverified", id="the-owners-login-forwarded-for-an-address-off-the-tailnet"),
    pytest.param(TAILSCALED, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": UNKNOWN_DEVICE},
                 "identity_unverified", id="the-owners-login-from-a-device-whois-cannot-name"),
    pytest.param(TAILSCALED, {"X-Forwarded-For": OWNER_PHONE},
                 {"error": "not allowed", "who": "unknown"}, id="through-tailscaled-with-no-login"),
    pytest.param(TAILSCALED, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": THIS_SERVER},
                 "not_authorised_local", id="this-server-asking-itself-through-tailscale-serve"),
    pytest.param(LOCAL_PROCESS, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": OWNER_PHONE},
                 {"error": "not allowed", "who": "unverified proxy"}, id="the-owners-headers-forged-by-a-process-on-the-server"),
    pytest.param(UNKNOWN, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": OWNER_PHONE},
                 {"error": "not allowed", "who": "unverified proxy"}, id="the-owners-headers-on-a-connection-the-kernel-does-not-list"),
    pytest.param(LOCAL_PROCESS, {"Tailscale-User-Login": OWNER},
                 "not_authorised_local", id="the-owners-login-with-no-forwarding-header"),
    pytest.param(LOCAL_PROCESS, {}, "not_authorised_local", id="no-header-at-all"),
    pytest.param(TAILSCALED, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": OWNER_PHONE, "Origin": "https://elsewhere.example"},
                 {"error": "cross-site request refused"}, id="a-page-on-another-site-in-the-owners-own-browser"),
    pytest.param(TAILSCALED, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": OWNER_PHONE, "Sec-Fetch-Site": "cross-site"},
                 {"error": "cross-site request refused"}, id="a-cross-site-fetch-the-browser-names"),
]


@pytest.mark.parametrize(("port", "headers", "expected"), REFUSED)
async def test_nobody_but_the_owners_device_mints_a_key(world, port, headers, expected):
    """C-01: a stranger's login, a forged forwarding header, no header, a request that did not
    come through Tailscale, the server itself, and a page on another site: each is refused
    before ElevenLabs is asked, by the real door and the real owner rule."""
    response = await mint(world, port, headers)
    assert_refused_with_nothing(world, response)
    body = response.json()
    if isinstance(expected, dict):
        assert body == expected, body
    else:
        assert body["code"] == expected, body
        assert body["who"] == "not the owner"


async def test_refused_callers_never_spend_the_owners_pace(world):
    """Forty refusals in the same instant leave the owner's next hold its key: a refusal is
    decided before the pace is counted, so a caller who is not the owner cannot use it up."""
    for _ in range(20):
        assert (await mint(world, LOCAL_PROCESS, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": OWNER_PHONE})).status_code == 403
        assert (await mint(world, TAILSCALED, {"Tailscale-User-Login": STRANGER, "X-Forwarded-For": STRANGER_PHONE})).status_code == 403
    assert world.elevenlabs.calls == []
    owner = await mint(world, TAILSCALED, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": OWNER_PHONE})
    assert owner.status_code == 200 and owner.json()["token"] == TOKEN


# ------------------------------------------------------------------ and the route, without the door


def _request(port: int, headers: dict[str, str]) -> Request:
    scope = {
        "type": "http", "method": "POST", "path": "/voice/live", "raw_path": b"/voice/live", "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("127.0.0.1", port), "server": SERVER, "scheme": "http", "app": app,
    }
    return Request(scope)


@pytest.mark.parametrize(("port", "headers", "code"), [
    (LOCAL_PROCESS, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": OWNER_PHONE}, "identity_unverified"),
    (TAILSCALED, {"Tailscale-User-Login": STRANGER, "X-Forwarded-For": STRANGER_PHONE}, "not_authorised"),
    (TAILSCALED, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": STRANGER_PHONE}, "identity_unverified"),
    (LOCAL_PROCESS, {}, "not_authorised_local"),
], ids=["forged-headers", "a-strangers-login", "the-owners-login-on-a-strangers-device", "the-server-itself"])
async def test_the_route_refuses_on_its_own_if_the_door_were_ever_opened(world, port, headers, code):
    """The same requests handed straight to the route, as if the door had let them by: its own
    check (voice._refused, the same principal_verdict) refuses them, and nothing is minted."""
    response = await voice_route.live(_request(port, headers))
    assert response.status_code == 403
    assert f'"code":"{code}"' in response.body.decode()
    assert TOKEN.encode() not in response.body
    assert world.elevenlabs.calls == []
    # And the owner's own phone, handed straight to it, is the owner.
    granted = await voice_route.live(_request(TAILSCALED, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": OWNER_PHONE}))
    assert granted.status_code == 200 and len(world.elevenlabs.calls) == 1
