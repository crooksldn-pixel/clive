"""What a channel must provide to plug into messaging, and the list of channels that have.

Why it exists: WeCom is the first channel; WhatsApp and Instagram follow. Each is one adapter
with the same four jobs, so the public door (app/routes/hooks.py), the store, the tools and the
Connections card never need to know which app a message came through:

    verify_inbound   is this request really from the channel? (signature first, then the
                     channel's own checks); returns what it carried, or raises Refused
    receive          turn a verified callback into the messages it stands for (for WeCom's
                     customer service that means reading them with sync_msg)
    send             one text to one thread; returns the channel's own message id only when
                     its API confirmed the send, and raises (with `refused` and plain words)
                     otherwise; why_not says beforehand why the channel would not take it
    probe            what this channel's account can do right now, route by route, in plain
                     words, with exactly what to switch on where it can't

An adapter never logs a message, a name or a contact id, and never sends without being asked by
the action engine after the owner's hold (app/tools/messaging_tools.py).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.messaging.models import Message, Thread


class Refused(Exception):
    """An inbound request that is not the channel's. `why` is a short kind for the count of
    refusals (signature, replay, size, crypto, unconfigured), never anything the request said."""

    def __init__(self, why: str) -> None:
        super().__init__(why)
        self.why = why


@dataclass(frozen=True)
class Inbound:
    """A verified inbound request. `echo` is the answer to a URL check (WeCom's GET); otherwise
    `fields` is the decrypted event, and `key` is what makes a repeat of it recognisable."""

    channel: str
    echo: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    key: str = ""
    timestamp: float = 0.0


@dataclass(frozen=True)
class Received:
    """One message the channel delivered, and the thread it belongs to."""

    thread: Thread
    message: Message


@dataclass(frozen=True)
class Failure:
    """The channel said later that a message it had accepted did not arrive."""

    thread: Thread
    remote_id: str
    reason: str


@dataclass(frozen=True)
class Route:
    """One way a channel can reach people, as the owner is told about it."""

    key: str              # "kf", "member", "external_contact", "archive", "appchat"
    label: str            # "WeChat contacts, through customer service"
    state: str            # "ready", "off" (he can switch it on), "not_used" (CLIVE does not use it), "unknown"
    can: str              # what it does, plainly
    switch_on: str = ""   # exactly what to do in the channel's console when it is off

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "state": self.state, "can": self.can, "switch_on": self.switch_on}


class Adapter(Protocol):
    channel: str
    label: str

    def configured(self) -> bool: ...

    def verify_inbound(self, method: str, query: Mapping[str, str], body: bytes) -> Inbound: ...

    async def receive(self, inbound: Inbound) -> list[Received | Failure]: ...

    async def why_not(self, thread: Thread) -> str: ...

    async def send(self, thread: Thread, text: str, *, client_id: str) -> str: ...

    async def names(self, threads: list[Thread]) -> dict[str, str]: ...

    async def probe(self) -> list[Route]: ...


ADAPTERS: dict[str, Adapter] = {}


def register(adapter: Adapter) -> Adapter:
    ADAPTERS[adapter.channel] = adapter
    return adapter


def get(channel: str) -> Adapter | None:
    return ADAPTERS.get(str(channel or ""))
