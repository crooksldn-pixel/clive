"""The owner boundary at the model's tools, not only at the routes (the 2026-09-27 deploy review,
round 6, F-NEW-TOOLS and B-01).

Gating routers one by one had left /turn open to any caller on the server, and so every tool
the model reaches through a turn — objectives, screens, engineering, the store and the inbox.
Two things hold it now, and both are tested here end to end: the door refuses a turn from
anyone but the owner before the model is ever asked (app/main.py), and a tool asked for by a
request that did not pass that rule is refused at the dispatcher whatever route asked
(app/tools/context.py OWNER_REQUEST)."""

from __future__ import annotations

import pytest

from app.displays import store as displays_store
from app.main import app
from app.providers.base import TurnResult
from app.tools.dispatch import dispatch
from tests.test_actions_routes import (  # noqa: F401 - `client` is a fixture
    OWNER,
    PROXIED,
    client,
    configure,
)

STRANGER = {"Tailscale-User-Login": "someone@example.com", "X-Forwarded-For": "100.64.0.3"}


class ToolingProvider:
    """A model that, asked anything, lists the screens and puts a list on one: what the prompt
    invites the real one to do."""

    def __init__(self, runtime) -> None:
        self.runtime = runtime
        self.asked: list[str] = []
        self.answers: list[str] = []

    async def start(self): pass
    async def stop(self): pass
    async def health(self): return True, "fake"
    async def reset_session(self, session_id): pass
    async def set_system_prompt(self, prompt): pass
    async def interrupt(self, session_id): return True

    async def turn(self, session_id, text):
        self.asked.append(text)
        session = self.runtime.sessions.get_or_create(session_id)
        self.answers.append(await dispatch("screen_list", {}, session=session, timeout_s=5))
        self.answers.append(await dispatch("screen_show", {"screen": "Office screen", "title": "From a turn", "lines": ["one"]},
                                           session=session, timeout_s=5))
        return TurnResult(text="done", session_id=session_id)


@pytest.fixture()
def world(client, tmp_path):  # noqa: F811
    from app.tools import display_tools  # noqa: F401  registers the tools

    configure(client, logins=OWNER, local=False)
    client.runtime.settings = client.runtime.settings.model_copy(update={"local_owner": False, "writes_local_owner": False})
    app.state.allowed_logins = client.runtime.allowed_logins
    screens = displays_store.install(tmp_path / "objectives" / "displays.json")
    screen = screens.register("Office screen")
    provider = ToolingProvider(client.runtime)
    client.runtime.provider = provider
    return client, provider, screens, screen


async def test_a_turn_from_anyone_but_the_owner_never_reaches_the_model_or_a_tool(world):
    http, provider, screens, screen = world
    for headers, who in (({}, "the server itself, with the production switches"), (STRANGER, "a stranger's device")):
        refused = await http.post("/turn", json={"text": "put my list on the office screen", "session_id": "s1"}, headers=headers)
        assert refused.status_code == 403, who
    assert provider.asked == [] and provider.answers == [], "the model was never asked"
    assert screens._data["screens"][screen["id"]]["showing"] is None

    # The owner's own device: the same turn reaches the model, and the model reaches its tools.
    answered = await http.post("/turn", json={"text": "put my list on the office screen", "session_id": "s1"}, headers=PROXIED)
    assert answered.status_code == 200, answered.text
    assert provider.asked and not any(a.startswith("REFUSED") for a in provider.answers), provider.answers
    assert screens._data["screens"][screen["id"]]["showing"]["title"] == "From a turn"


async def test_a_route_that_is_not_the_owners_has_no_tool_run_for_it(world, monkeypatch):
    """Were a route the owner rule does not cover ever to reach the dispatcher — a public path,
    or the server's own test-session command — the tools refuse it themselves."""
    from starlette.routing import Route

    from app import main as main_module
    from app.tools import display_tools

    http, provider, screens, screen = world
    answers: list[str] = []

    async def probe(request):
        from starlette.responses import PlainTextResponse

        session = http.runtime.sessions.get_or_create("probe")
        answers.append(await dispatch("screen_list", {}, session=session, timeout_s=5))
        answers.append(await dispatch("objective_list", {}, session=session, timeout_s=5))
        return PlainTextResponse("ok")

    def untouched(*_a, **_k):
        raise AssertionError("a tool ran for a request that was not the owner's")

    real_public = main_module.is_public
    monkeypatch.setattr(main_module, "is_public", lambda path: path == "/probe-tools" or real_public(path))
    monkeypatch.setattr(display_tools, "store", untouched)
    app.router.routes.insert(0, Route("/probe-tools", probe))
    try:
        for headers in ({}, PROXIED):
            assert (await http.get("/probe-tools", headers=headers)).status_code == 200
    finally:
        app.router.routes[:] = [r for r in app.router.routes if getattr(r, "path", "") != "/probe-tools"]
    assert len(answers) == 4 and all(a.startswith("REFUSED: this request is not the owner's") for a in answers), answers


async def test_outside_any_request_the_services_own_work_still_runs_its_tools(world):
    """The stamp is about requests: the service's own start-up and timers (no request at all) are
    not refused by it, as they were not before."""
    from app.session.models import Session
    from app.tools.context import OWNER_REQUEST

    assert OWNER_REQUEST.get() is None
    text = await dispatch("screen_list", {}, session=Session(session_id="own-work"), timeout_s=5)
    assert "Office screen" in text and not text.startswith("REFUSED")
