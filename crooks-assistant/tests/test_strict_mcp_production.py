"""CLIVE's live turns load no MCP server of the host's (DEC-071, ruling 26).

The owner's assistant and every team member's, as app/runtime.py builds them, start the claude CLI
with strict_mcp_config on: it loads only the tool server CLIVE gives it, never the host user's own
MCP servers or claude.ai connectors. The provider's default is unchanged: built plainly, its options
do not name strict_mcp_config at all. No network and no CLI here: the options are captured, not used.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.people.store import Person
from app.providers.max_agent_sdk import MaxAgentSDKProvider
from app.tools import registry


@pytest.fixture
def captured(monkeypatch):
    """The Agent SDK's options class replaced by a capture: each call's arguments, kept as given."""
    import claude_agent_sdk

    calls: list[dict] = []

    def capture(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(**kwargs)

    monkeypatch.setattr(claude_agent_sdk, "ClaudeAgentOptions", capture)
    return calls


@pytest.fixture
def built():
    """A runtime from app/runtime.py's own build(), its tool bindings put back afterwards."""
    from app import runtime
    from config.settings import get_settings
    from experience import harness as harness_module

    bound = harness_module._tool_bindings()
    try:
        yield runtime.build(get_settings())
    finally:
        harness_module._put_back(bound)


def _options(provider, captured) -> dict:
    provider._auth_mode = "cli"                     # the CLI's own login: no token read
    before = len(captured)
    provider._options()
    assert len(captured) == before + 1
    return captured[-1]


def _clives_own_server_only(kwargs: dict) -> None:
    assert list(kwargs["mcp_servers"]) == [registry.MCP_SERVER_NAME]
    assert kwargs["mcp_servers"][registry.MCP_SERVER_NAME] is not None
    prefix = f"mcp__{registry.MCP_SERVER_NAME}__"
    assert kwargs["allowed_tools"] and all(name.startswith(prefix) for name in kwargs["allowed_tools"])
    assert kwargs["tools"] == [] and kwargs["setting_sources"] == [] and kwargs["permission_mode"] == "dontAsk"


def test_the_owners_assistant_is_strict_and_keeps_clives_own_server(built, captured):
    owner = built.provider
    assert isinstance(owner, MaxAgentSDKProvider) and owner.strict_mcp_config is True
    kwargs = _options(owner, captured)
    assert kwargs["strict_mcp_config"] is True
    _clives_own_server_only(kwargs)


def test_a_staff_assistant_is_strict_and_keeps_clives_own_server(built, captured):
    emily = Person(person_id="emily", name="Emily", kind="staff", role="packing")
    staff = built.staff_provider_factory(emily)
    assert isinstance(staff, MaxAgentSDKProvider) and staff is not built.provider
    assert staff.strict_mcp_config is True
    kwargs = _options(staff, captured)
    assert kwargs["strict_mcp_config"] is True
    _clives_own_server_only(kwargs)


def test_a_provider_built_with_the_default_does_not_name_it(captured):
    plain = MaxAgentSDKProvider(system_prompt="sys")
    assert plain.strict_mcp_config is False
    kwargs = _options(plain, captured)
    assert "strict_mcp_config" not in kwargs
    _clives_own_server_only(kwargs)
