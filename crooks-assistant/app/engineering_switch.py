"""Whether CLIVE files build requests at all, and where (the 2026-09-28 deploy review, round 10,
CFG-01).

CROOKS_ENGINEERING_HOST names the engineering loop that takes CLIVE's build requests ("worker-01"
polls clive/control/worker-01-inbox; "owner" is the production host's own loop). Production leaves
it unset, and its template says what unset means: filing from CLIVE is deferred and its credential
parked. The setting used to default to "worker-01", so unset quietly meant "file to worker-01"
whenever a token could be read. Now unset is "off" (config/settings.py), and "off" — or an empty
value — binds the tools (app/tools/engineering_tools.py) to an inbox that answers every call,
read or write, with the reason filing is off, before a token is read or a request is made. There
is no path from it to GitHub: its HTTP call itself refuses.
"""

from __future__ import annotations

from typing import Any

from app.engineering_bridge.github import EngineeringInbox, GitHubError, NotConnected

OFF = "off"
OFF_REASON = (
    "Filing build requests from CLIVE is switched off on this server (CROOKS_ENGINEERING_HOST is "
    "not set). Nothing was sent to GitHub."
)


def filing_host(value: object) -> str | None:
    """The engineering host a setting names, or None when filing is off: unset (the default,
    "off"), empty, or "off" in any case."""
    host = str(value or "").strip()
    return None if not host or host.lower() == OFF else host


async def _off(_inbox: EngineeringInbox, *_args: Any, **_kwargs: Any) -> NotConnected:
    return NotConnected(OFF_REASON)


class FilingOff(EngineeringInbox):
    """The inbox bound when filing is off. Every read and the write — the status, the inbox's and
    the trunk's heads, the merge check, the look for a request file and the create — answer
    NotConnected with OFF_REASON, so each tool says filing is off and prepares nothing; no token is
    read, and the one HTTP call all of them would go through refuses before a client exists."""

    status = inbox_head = trunk_head = on_trunk = request_file = create_request = _off

    def __init__(self) -> None:
        super().__init__(token_source=lambda: None)
        self.host = OFF
        self.inbox_branch = self.status_branch = ""

    def _token(self) -> str | None:
        return None

    async def _call(self, token: str, method: str, url: str, **_kwargs: Any):
        raise GitHubError("Filing build requests is switched off on this server; nothing was sent.")


def inbox_for(setting: object) -> EngineeringInbox:
    """The inbox the engineering tools are bound to for CROOKS_ENGINEERING_HOST's value: FilingOff
    when filing is off, the named host's loop otherwise (which refuses a malformed name, as it
    always has)."""
    host = filing_host(setting)
    return FilingOff() if host is None else EngineeringInbox(host=host)
