"""[returns-events] The returns service's OWN doorbell against CLIVE's OWN door: the true contract of
/hooks/returns (DEC-077), offline.

The service's code is loaded as tests/returns_service.py loads it (the pinned SERVICE_SHA, or
CROOKS_RETURNS_SRC); its doorbell (crooks-returns/returns/doorbell.py) posts each event it recorded,
signed with the shared secret, through a transport that hands the request to CLIVE's real app; and
CLIVE reads the return back from the service's own app with its read key. What it proves: the
service's post passes CLIVE's door as it is (fields, signature, time, ids), CLIVE's 200 marks it
delivered so it is never sent again, a repeat is dropped, a wrong secret is a 403 the service retries,
and what George is told comes from CLIVE's own read of the service.

Skipped, saying why, where the loaded service has no doorbell yet: the pinned SERVICE_SHA is the
service deployed on 3 October, and the doorbell arrives with branch claude/n3-service-events. When
George deploys that, bump SERVICE_SHA (tests/returns_service.py says how) and this runs in acceptance.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from datetime import UTC, datetime

import httpx
import pytest

from app.clients import crooks_returns as rc
from app.returns import events
from app.secrets import keychain
from tests import returns_service
from tests.fake_credentials import bearer_token
from tests.test_actions_routes import (  # noqa: F401 - `client` is a fixture
    OWNER,
    PROXIED,
    client,
    configure,
)

READ = bearer_token("contract-events-read", length=32)
WRITE = bearer_token("contract-events-write", length=32)
SECRET = hashlib.sha256(b"returns-events-contract-secret").hexdigest()


class IntoClive(httpx.BaseTransport):
    """The service's doorbell posts from its own thread; this hands each post to CLIVE's app on the
    test's event loop and waits for CLIVE's answer, as the network would."""

    def __init__(self, http: httpx.AsyncClient, loop: asyncio.AbstractEventLoop) -> None:
        self.http, self.loop, self.posts = http, loop, []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        body = request.read()
        self.posts.append(body)
        done = asyncio.run_coroutine_threadsafe(
            self.http.post(request.url.path, content=body, headers=dict(request.headers)), self.loop)
        answer = done.result(30)
        return httpx.Response(answer.status_code, content=answer.content)


@pytest.fixture(scope="module")
def loaded(tmp_path_factory):
    """Module-scoped, like tests/test_crooks_returns_contract.py `service_code`: it is set up before
    conftest's `_offline_environment` takes every CROOKS_* variable away for the test, so
    CROOKS_RETURNS_SRC, as the skip below says, is still there to be read."""
    found = returns_service.load(tmp_path_factory.mktemp("service"))
    if found is None:
        pytest.skip(returns_service.WHY_NOT)
    if not (found.src / "returns" / "doorbell.py").is_file():
        returns_service.unload(found)
        pytest.skip(f"the returns service at {returns_service.SERVICE_SHA[:8]} has no doorbell yet: it arrives with "
                    "claude/n3-service-events; bump SERVICE_SHA when George deploys it, or set CROOKS_RETURNS_SRC")
    yield found
    returns_service.unload(found)


async def test_the_services_own_doorbell_rings_clives_own_door(client, loaded, monkeypatch, tmp_path):  # noqa: F811
    configure(client, logins=OWNER, local=False)
    client.runtime.settings = client.runtime.settings.model_copy(update={"local_owner": False})
    s = loaded
    settings = returns_service.settings(s, tmp_path, read_key=READ, write_key=WRITE)
    settings.label_provider = "none"
    settings.clive_webhook_url = "https://hooks.example.com/hooks/returns"
    settings.clive_webhook_secret = SECRET
    shop = s.fake.FakeShopify(s.fake.sample_orders(datetime.now(UTC)))
    svc = s.service.ReturnsService(settings, s.store.Store(settings.db_path), shop, s.fake.FakeLabels())
    service_app = s.app.create_app(settings, svc)
    keys = {rc.READ_KEY: READ, rc.WRITE_KEY: WRITE, events.SECRET_KEY: SECRET}
    monkeypatch.setattr(keychain, "get_optional", lambda key: keys.get(key))
    monkeypatch.setattr(rc, "http_client", lambda timeout_s: httpx.AsyncClient(
        transport=httpx.ASGITransport(app=service_app), timeout=timeout_s))
    rc.configure(base_url="https://returns.example.com")
    rc.forget()
    events.DOOR.forget()
    into = IntoClive(client, asyncio.get_running_loop())
    svc.doorbell._http = httpx.Client(transport=into)
    try:
        # A customer asks to return the tee on #1939, through the service's own workflow.
        session, _ = svc.lookup("1939", "customer@example.com", "1.2.3.4")
        order = svc.order_for_session(session)
        m = s.models
        asked = svc.submit(order, [m.Selection(fulfillment_line_item_id=order.lines[0].fulfillment_line_item_id,
                                               quantity=1, reason=m.Reason.too_small)],
                           m.Resolution.refund, m.Postage.self_ship)
        delivered = await asyncio.to_thread(svc.doorbell.deliver_due)
        await events.DOOR.settle()
        assert delivered == 1 and svc.store.outbox_counts() == {"delivered": 1}
        assert b"Sam Taylor" not in into.posts[0] and b"customer@example.com" not in into.posts[0]
        said = (await client.get("/returns/brief", headers=PROXIED)).json()
        assert [n["words"] for n in said["notices"]] == ["Return on #1939: waiting for your approval."]
        assert said["needs"] == 1 and "Sam Taylor" not in str(said)
        # Never sent again; and the same event, sent again by hand, is answered and dropped.
        assert await asyncio.to_thread(svc.doorbell.deliver_due) == 0
        again = await client.post("/hooks/returns", content=into.posts[0], headers={
            "Content-Type": "application/json",
            "X-Crooks-Returns-Signature": _signature(into.posts[0])})
        assert (again.status_code, again.content) == (200, b"") and events.DOOR.counts["repeats"] == 1
        # A secret that differs is CLIVE's empty 403, which the service keeps and tries again.
        settings.clive_webhook_secret = "f" * 64
        svc.execute(asked.id, "note", {"text": "rang them"}, "George", "contract-note-1")
        assert await asyncio.to_thread(svc.doorbell.deliver_due) == 0
        assert svc.store.outbox_counts() == {"delivered": 1, "waiting": 1}
    finally:
        await events.DOOR.settle()
        events.DOOR.forget()
        rc.configure(base_url=rc.DEFAULT_BASE_URL)
        rc.forget()


def _signature(raw: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
