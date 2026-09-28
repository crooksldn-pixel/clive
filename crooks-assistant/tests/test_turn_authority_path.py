"""A model turn's tool authority, end to end through the real door (the 2026-09-28 deploy review,
round 9, F-NEW-TOOLS-PATH).

The reviewer could see the SDK callback and the dispatcher refuse a call without authority, but not
the HTTP path that decides who gets one. This drives that path whole, with production's switches:
the real middleware (app/main.py guard_and_freshness), the real proxy decision and owner rule
(app/routes/actions.py proxy_state and principal_verdict) reading the kernel's account of the
connection from a fake /proc through the real code that reads it (app/identity.py
_proc_peer_check, host_addresses, verify — only `tailscale whois`, which tests do not have, and the
fake pids' pinning are stood in for), the authority the door stamps (app/tools/authority.py
for_owner), the real turn route (app/routes/turn.py), and the real dispatcher (app/tools/dispatch.py)
called by a model double exactly as the SDK callback calls it.

Every caller that is not the owner's verified device — the server itself, a stranger's device, a
device whose login Tailscale does not confirm, a process on the server forging Tailscale's
headers, the server's own request through its own `tailscale serve`, Funnel, the server's command
key — is refused at the door: the model is never asked and no tool handler is ever reached. The
owner's device is admitted, its turn holds an owner authority for his login alone, its tools run,
nothing is applied without his tap, and the authority is dead once the answer has been sent.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app import identity, local_cli
from app.main import app
from app.providers.base import TurnResult
from app.tools import authority
from app.tools import dispatch as dispatch_module
from app.tools.dispatch import dispatch
from tests.test_actions import ORDER, TOOL
from tests.test_actions_routes import OWNER, client, configure  # noqa: F401 - `client` is a fixture
from tests.test_proxy_identity import HOST_TAILNET, HOST_TAILNET6, _addresses, _world

PHONE, STRANGER_DEVICE = "100.64.0.9", "100.64.0.3"
STRANGER = "someone@example.com"
TAILSCALED_END, CURL_END, DIRECT_END = 40001, 40002, 40009   # the fake /proc's connections (tests/test_proxy_identity._world)
REFUSED = "REFUSED: this was not asked for by the owner"
KEY = "k" * 43


class Witness:
    """A model double that, asked anything, does what the real provider's tool callback does —
    calls the dispatcher — for a read and a change, and leaves one more read running for after the
    answer. It writes down the authority it held when it was asked."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.asked: list[str] = []
        self.held: list[authority.Authority | None] = []
        self.answers: list[str] = []
        self.late: asyncio.Task | None = None

    async def start(self): pass
    async def stop(self): pass
    async def health(self): return True, "fake"
    async def reset_session(self, session_id): pass
    async def set_system_prompt(self, prompt): pass
    async def interrupt(self, session_id): return True

    async def turn(self, session_id, text):
        self.asked.append(text)
        self.held.append(authority.TOOL_AUTHORITY.get())
        session = self.runtime.sessions.get_or_create(session_id)
        session.issue(ORDER)
        self.answers.append(await dispatch("shopify_order_detail", {"order_id": ORDER}, session=session, timeout_s=5))
        self.answers.append(await dispatch(TOOL, {"order_id": ORDER, "note": "Customer asked for an exchange"},
                                           session=session, timeout_s=5))

        async def later():
            await asyncio.sleep(0.2)          # well after the answer has been sent
            return await dispatch("shopify_order_detail", {"order_id": ORDER}, session=session, timeout_s=5)

        self.late = asyncio.get_running_loop().create_task(later())
        return TurnResult(text="done", session_id=session_id)


@pytest.fixture()
def production(client, tmp_path, monkeypatch):  # noqa: F811
    """Production's switches and the kernel's account: tailscaled (pid 100) holds the far end of
    the connection from port 40001, an ordinary process (pid 200) that of port 40002, and nothing
    holds 40009's (a request made straight to the port). This server's own addresses are read from
    the fake /proc's own tables. Tailscale says 100.64.0.9 is the owner's phone, 100.64.0.3 a
    stranger's, and the server's own address the owner's too (the server is on his login)."""
    configure(client, logins=OWNER, local=False)
    client.runtime.settings = client.runtime.settings.model_copy(update={
        "tailscale_verify": True, "local_owner": False, "writes_local_owner": False, "writes_enabled": True})
    app.state.allowed_logins = client.runtime.allowed_logins
    proc = _world(tmp_path, {100: ("tailscaled", [777]), 200: ("curl", [888])})
    _addresses(proc, HOST_TAILNET, HOST_TAILNET6)
    monkeypatch.setattr(identity, "PROC", proc)
    monkeypatch.setattr(identity, "CGROUP", tmp_path / "cgroup")
    whois = {PHONE: OWNER, STRANGER_DEVICE: STRANGER, HOST_TAILNET[0]: OWNER}
    identity.bind_runner(lambda cli, address: {"UserProfile": {"LoginName": whois.get(address, "")}})
    monkeypatch.setattr(identity, "cli_path", lambda configured="": "/usr/bin/tailscale")
    witness = Witness(client.runtime)
    client.runtime.provider = witness
    reached: list[tuple[str, authority.Authority | None]] = []
    for step in ("_read_once", "_stage"):
        real = getattr(dispatch_module, step)

        def spy(name, *args, _real=real, **kwargs):
            reached.append((name, authority.current()))
            return _real(name, *args, **kwargs)

        monkeypatch.setattr(dispatch_module, step, spy)
    return client, witness, reached


def _caller(port: int) -> httpx.AsyncClient:
    """A client whose connection the app sees as arriving from 127.0.0.1:port to 127.0.0.1:8000,
    the addresses the fake /proc's socket table names."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=("127.0.0.1", port)),
                             base_url="http://127.0.0.1:8000")


NOT_THE_OWNER = {
    "the server itself, straight to the port": (DIRECT_END, {}, "not_authorised_local"),
    "a stranger's device, through tailscaled": (TAILSCALED_END, {"Tailscale-User-Login": STRANGER, "X-Forwarded-For": STRANGER_DEVICE}, None),
    "the owner's login on a device Tailscale says is not his": (TAILSCALED_END, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": STRANGER_DEVICE}, "identity_unverified"),
    "a process on the server writing Tailscale's headers": (CURL_END, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": PHONE}, None),
    "the server's own request through its own tailscale serve": (TAILSCALED_END, {"Tailscale-User-Login": OWNER, "X-Forwarded-For": HOST_TAILNET[0]}, "not_authorised_local"),
    "Funnel, or a tagged node: forwarded with no login": (TAILSCALED_END, {"X-Forwarded-For": PHONE}, None),
    "the server's command key, on the turn route": (DIRECT_END, {local_cli.HEADER: KEY}, "local_key_misused"),
}


@pytest.mark.parametrize("who", sorted(NOT_THE_OWNER))
async def test_nobody_but_the_owner_reaches_the_model_or_any_tool_through_the_real_door(production, who):
    http, witness, reached = production
    local_cli.bind_key(KEY)
    port, headers, code = NOT_THE_OWNER[who]
    async with _caller(port) as caller:
        refused = await caller.post("/turn", json={"text": "what's on order 1930?", "session_id": "s-" + str(port)}, headers=headers)
    assert refused.status_code == 403, (who, refused.text)
    if code:
        assert refused.json().get("code") == code, (who, refused.json())
    assert witness.asked == [] and witness.held == [], "the model was never asked"
    assert reached == [], "no tool handler was reached"
    assert http.store.mutations == []


async def test_the_owners_device_holds_an_owner_authority_for_his_turn_and_only_for_it(production):
    http, witness, reached = production
    async with _caller(TAILSCALED_END) as caller:
        whoami = (await caller.get("/whoami", headers={"Tailscale-User-Login": OWNER, "X-Forwarded-For": PHONE})).json()
        assert whoami["through"] == "tailscale" and whoami["owner"] is True, whoami
        answered = await caller.post("/turn", json={"text": "what's on order 1930?", "session_id": "owner-1"},
                                     headers={"Tailscale-User-Login": OWNER, "X-Forwarded-For": PHONE})
    assert answered.status_code == 200, answered.text
    assert len(witness.asked) == 1
    held = witness.held[0]
    assert held is not None and held.kind == authority.OWNER and held.who == OWNER, held
    read, change = witness.answers
    assert not read.startswith(REFUSED) and not change.startswith(REFUSED), witness.answers
    assert [name for name, _ in reached] == ["shopify_order_detail", TOOL]
    assert all(during is held for _, during in reached), "every handler ran under this turn's own authority"
    assert http.store.mutations == [], "a change is staged for his tap, never applied by the turn"
    # Once the answer has been sent, the authority is dead, and what the turn left running holds nothing.
    late = await asyncio.wait_for(witness.late, timeout=5)
    assert held.revoked and late.startswith(REFUSED), late
    assert [name for name, _ in reached] == ["shopify_order_detail", TOOL], "the late read reached no handler"


async def test_with_no_allow_list_not_even_the_owners_device_is_given_authority(production):
    http, witness, reached = production
    configure(http, logins="", local=False)
    http.runtime.settings = http.runtime.settings.model_copy(update={"tailscale_verify": True, "local_owner": False})
    app.state.allowed_logins = http.runtime.allowed_logins
    async with _caller(TAILSCALED_END) as caller:
        refused = await caller.post("/turn", json={"text": "hi", "session_id": "owner-2"},
                                    headers={"Tailscale-User-Login": OWNER, "X-Forwarded-For": PHONE})
    assert refused.status_code == 403 and refused.json()["code"] == "allow_list_missing"
    assert witness.asked == [] and reached == []
