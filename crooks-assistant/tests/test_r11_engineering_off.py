"""CROOKS_ENGINEERING_HOST unset is off (the 2026-09-28 deploy review, round 10, CFG-01).

The reviewer found `engineering_host` defaulting to "worker-01" while the production template says
that leaving it unset defers filing: unset quietly meant "file to worker-01" whenever the host held
a readable token. Now unset resolves to "off", and "off" binds the engineering tools to an inbox
that refuses every call before a token is read (app/engineering_switch.py). These tests build the
runtime the way the service does, with the setting unset and a token the secret store would hand
over, and drive every filing path — the status read, the prepare, the write, the look before and
after it, the progress and gap refreshes — with httpx itself watched: not one request is made.
"""

from __future__ import annotations

import httpx
import pytest

from app import engineering_switch
from app.engineering_bridge import github as github_module
from app.engineering_bridge.github import EngineeringInbox, GitHubError, NotConnected
from app.secrets import keychain
from app.session.models import Session
from app.tools import engineering_tools
from app.tools.dispatch import dispatch
from app.tools.registry import ToolError
from tests.fake_credentials import github_token
from tests.test_actions_routes import client, configure  # noqa: F401 - `client` is a fixture

HEAD = "1" * 40


@pytest.fixture()
def github_watched(monkeypatch):
    """A token the secret store hands to anyone who asks for it, and every request any httpx
    AsyncClient sends written down and refused, so nothing leaves the machine and anything that
    tried is seen."""
    token = github_token("r11-cfg-01")
    asked: list[str] = []
    real_get = keychain.get_optional

    def get_optional(name):
        if name == github_module.TOKEN_KEY:
            asked.append(name)
            return token
        return real_get(name)

    monkeypatch.setattr(keychain, "get_optional", get_optional)
    sent: list[str] = []

    async def send(self, request, *args, **kwargs):
        sent.append(f"{request.method} {request.url.path}")
        raise httpx.ConnectError("a test never reaches GitHub")

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    return asked, sent


def test_unset_empty_or_off_is_off_and_only_a_named_host_files():
    from config.settings import Settings

    assert Settings(_env_file=None).engineering_host == engineering_switch.OFF
    for value in ("", "  ", "off", "OFF", " Off ", None):
        assert engineering_switch.filing_host(value) is None, value
        assert isinstance(engineering_switch.inbox_for(value), engineering_switch.FilingOff), value
    named = engineering_switch.inbox_for("worker-01")
    assert type(named) is EngineeringInbox and named.inbox_branch == "clive/control/worker-01-inbox"
    assert engineering_switch.inbox_for("owner").inbox_branch == "clive/control/owner-inbox"
    with pytest.raises(ValueError):
        engineering_switch.inbox_for("Worker/01")


def test_the_setting_is_read_from_its_environment_name(monkeypatch):
    from config.settings import Settings

    monkeypatch.setenv("CROOKS_ENGINEERING_HOST", "")
    assert engineering_switch.filing_host(Settings(_env_file=None).engineering_host) is None
    monkeypatch.setenv("CROOKS_ENGINEERING_HOST", "worker-01")
    assert engineering_switch.filing_host(Settings(_env_file=None).engineering_host) == "worker-01"


@pytest.mark.usefixtures("owner_asking")   # the admitted owner, as a request the door let through
async def test_with_the_setting_unset_no_filing_path_reaches_github_whatever_token_is_held(client, github_watched):  # noqa: F811
    """CFG-01: the runtime the lifespan built, with CROOKS_ENGINEERING_HOST unset (the offline
    environment carries none) and changes on, so the write tool is offered and prepared as in
    production. Every path answers that filing is off; no proposal is staged; the write and the
    looks either side of it refuse; the refreshes say nothing; no token is read; no request is
    sent. And the watch is real: a named host's inbox, asked the same, does try to send."""
    asked, sent = github_watched
    configure(client, writes=True)
    inbox = engineering_tools._client()
    assert isinstance(inbox, engineering_switch.FilingOff), "the runtime bound the off inbox"
    session = Session(session_id="cfg-01")

    status = await dispatch("engineering_status", {"areas": True}, session=session, timeout_s=5)
    assert "switched off" in status and "CROOKS_ENGINEERING_HOST" in status, status
    # With filing off the status names no inbox id, so the gate never lets the prepare run on an
    # id the model made up; issued here as if a lookup had named it, so the prepare itself is tried.
    session.issue(HEAD)
    filed = await dispatch("submit_engineering_request", {
        "inbox_id": HEAD, "title": "Show a task on the big screen", "requested_outcome": "Pull a slip up large.",
        "allowed_paths": ["app/scenes"], "acceptance_criteria": ["It shows."],
    }, session=session, timeout_s=5)
    assert filed.startswith("ERROR:") and "switched off" in filed, filed
    assert session.proposals == [], "nothing was prepared, so nothing waits for a tap"

    execution = {"request_id": "r11-cfg-01", "content": "{}", "head": HEAD, "objective_id": "", "host": "worker-01",
                 "path": "requests/r11-cfg-01.json", "target_branch": "x"}
    with pytest.raises(ToolError, match="switched off"):
        await engineering_tools._execute(execution)
    with pytest.raises(ToolError, match="switched off"):
        await engineering_tools._observe(execution)
    assert await engineering_tools.build_progress(["r11-cfg-01"]) == {}
    await engineering_tools.refresh_gaps()
    for call in (inbox.status(), inbox.inbox_head(), inbox.trunk_head(), inbox.on_trunk("a" * 40),
                 inbox.request_file("r11-cfg-01"), inbox.create_request("r11-cfg-01", b"{}")):
        answer = await call
        assert isinstance(answer, NotConnected) and answer.reason == engineering_switch.OFF_REASON
    with pytest.raises(GitHubError):
        await inbox._call("token", "PUT", "/repos/crooksldn-pixel/clive/contents/requests/x.json")
    assert sent == [] and asked == [] and inbox.requests_made == 0, (sent, asked)

    named = engineering_switch.inbox_for("worker-01")
    with pytest.raises(GitHubError):
        await named.status()
    assert asked and len(sent) == 1, "with a host named, the same token and the same watch do reach httpx"
